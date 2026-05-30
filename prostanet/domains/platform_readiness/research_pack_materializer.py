"""Materialize de-identified cohort research packs.

This layer consumes the de-identified export contract and produces reproducible
CSV/JSON artifacts with hashes. Freezing persists the derived pack only after
the PHI/interoperability gates pass; it never mutates source clinical facts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from typing import Any, Mapping

from prostanet.domains.platform_readiness.deidentified_export_contract import (
    build_deidentified_export_contract,
)
from prostanet.shared.utc_time import utc_now_iso


RESEARCH_PACK_MATERIALIZER_VERSION = "deidentified_research_pack_materializer_v1"
REGISTRY_TYPE = "deidentified_research_pack_v1"
CSV_COMPONENTS = (
    ("data_dictionary.csv", "data_dictionary"),
    ("fact_rows.csv", "fact_rows"),
    ("lineage_rows.csv", "lineage_rows"),
    ("events.csv", "event_rows"),
    ("treatments.csv", "treatment_rows"),
    ("biomarkers.csv", "biomarker_rows"),
)


def build_research_pack_materializer(
    *,
    scope: str = "full",
    limit: int = 50,
    real_only: bool = False,
) -> dict[str, Any]:
    """Build an in-memory materialized research pack preview."""
    scope_key = str(scope or "full").strip().lower()
    include_files = scope_key != "summary"
    contract = build_deidentified_export_contract(
        scope="full",
        limit=max(1, min(int(limit or 50), 500)),
        real_only=real_only,
    )
    export_summary = contract.get("summary") or {}
    blocked_reasons = _blocked_reasons(export_summary)
    bundle = _build_bundle(contract)
    files = _build_files(bundle, contract)
    file_manifest = _build_file_manifest(files, bundle)
    pack_summary = _build_summary(contract, file_manifest, blocked_reasons)
    payload: dict[str, Any] = {
        "available": True,
        "source": "deidentified_research_pack_materializer",
        "version": RESEARCH_PACK_MATERIALIZER_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "deidentified": True,
        "export_written": False,
        "freeze_created": False,
        "summary": pack_summary,
        "cohort_manifest": contract.get("cohort_manifest") or {},
        "export_quality": contract.get("export_quality") or {},
        "file_manifest": file_manifest,
        "blocked_reasons": blocked_reasons,
        "recommendations": _build_recommendations(pack_summary),
    }
    if include_files:
        payload["bundle"] = bundle
        payload["files"] = files
    return payload


def freeze_research_pack_materializer(
    *,
    limit: int = 50,
    real_only: bool = False,
    title: str | None = None,
    created_by: str = "clinician",
    audit_note: str | None = None,
    governance_status: str | None = None,
    clinical_objective: str | None = None,
    research_question: str | None = None,
    methodology_note: str | None = None,
    responsible: str | None = None,
) -> dict[str, Any]:
    """Persist a derived de-identified research pack if all gates pass."""
    pack = build_research_pack_materializer(scope="full", limit=limit, real_only=real_only)
    summary = pack.get("summary") or {}
    if not summary.get("next_layer_allowed"):
        return {
            "success": False,
            "error": "deidentified_research_pack_blocked",
            "blocked_reasons": pack.get("blocked_reasons") or [],
            "summary": summary,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }

    governance = _build_governance_metadata(
        governance_status=governance_status,
        clinical_objective=clinical_objective,
        research_question=research_question,
        methodology_note=methodology_note,
        responsible=responsible or created_by,
    )
    _attach_governance_metadata(pack, governance)
    canonical_payload = _canonical_json(pack)
    payload_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    freeze_key = f"dxpack_{payload_sha256[:12]}"
    freeze_title = (title or f"De-identified Research Pack {freeze_key}").strip()
    created_by_value = (created_by or "clinician").strip() or "clinician"
    audit_note_value = audit_note or (
        "Pack desidentificado congelado desde Platform Readiness; no muta hechos clinicos, no crea ordenes externas y no entrena modelos."
    )

    import tracking_db

    conn = tracking_db._connect(write=True)
    cursor = conn.cursor()
    try:
        tracking_db._ensure_research_cohort_freeze_table(cursor)
        manifest = pack.get("cohort_manifest") or {}
        cursor.execute(
            """
            INSERT OR IGNORE INTO research_cohort_freezes (
                freeze_key, title, registry_type, cohort_label, filters_json, weeks_json,
                real_only, trace_row_count, patient_count_primary_window, readiness_json,
                methods_json, bias_and_completeness_json, data_dictionary_json, dataset_json,
                registry_summary_json, suggested_questions_json, payload_json, payload_sha256,
                created_by, status, audit_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                freeze_key,
                freeze_title,
                REGISTRY_TYPE,
                manifest.get("cohort_label"),
                tracking_db._json_blob({"limit": limit}),
                tracking_db._json_blob([]),
                1 if real_only else 0,
                int(summary.get("total_data_rows") or 0),
                int(summary.get("cohort_subject_count") or 0),
                tracking_db._json_blob(pack.get("export_quality") or {}),
                tracking_db._json_blob(pack.get("bundle", {}).get("methods") or {}),
                tracking_db._json_blob(pack.get("bundle", {}).get("bias_and_completeness") or {}),
                tracking_db._json_blob(pack.get("bundle", {}).get("data_dictionary") or []),
                tracking_db._json_blob(pack.get("file_manifest") or []),
                tracking_db._json_blob(summary),
                tracking_db._json_blob(_build_suggested_questions(pack, governance)),
                tracking_db._json_blob(pack),
                payload_sha256,
                created_by_value,
                "frozen",
                audit_note_value,
            ),
        )
        created = cursor.rowcount == 1
        cursor.execute("SELECT * FROM research_cohort_freezes WHERE freeze_key = ?", (freeze_key,))
        row = cursor.fetchone()
        conn.commit()
        freeze = tracking_db._research_cohort_freeze_from_row(row, include_payload=True)
        return {
            "success": True,
            "created": bool(created),
            "freeze_key": freeze_key,
            "payload_sha256": payload_sha256,
            "freeze": freeze,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    except Exception as exc:
        conn.rollback()
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def build_research_pack_zip_bytes(pack: Mapping[str, Any]) -> bytes:
    """Build ZIP bytes from a materialized or frozen pack payload."""
    payload = dict(pack or {})
    if payload.get("payload") and isinstance(payload["payload"], Mapping):
        payload = dict(payload["payload"])
    files = dict(payload.get("files") or {})
    if not files and payload.get("bundle"):
        files = _build_files(payload["bundle"], payload)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, str(content or ""))
    return buffer.getvalue()


def _build_governance_metadata(
    *,
    governance_status: str | None,
    clinical_objective: str | None,
    research_question: str | None,
    methodology_note: str | None,
    responsible: str | None,
) -> dict[str, str]:
    allowed = {
        "exploratory",
        "audit_ready",
        "poster_ready",
        "publication_ready",
        "insufficient_quality",
    }
    status = str(governance_status or "audit_ready").strip().lower()
    if status not in allowed:
        status = "audit_ready"
    return {
        "governance_status": status,
        "clinical_objective": _clean_text(
            clinical_objective,
            "Auditoria institucional desidentificada de cancer de prostata.",
        ),
        "research_question": _clean_text(
            research_question,
            "Que patrones clinicos, longitudinales y economicos emergen en la cohorte congelada?",
        ),
        "methodology_note": _clean_text(
            methodology_note,
            "Pack local desidentificado, derivado de Ledger y tablas longitudinales; requiere revision humana antes de uso externo.",
        ),
        "responsible": _clean_text(responsible, "clinician"),
    }


def _attach_governance_metadata(pack: dict[str, Any], governance: Mapping[str, str]) -> None:
    pack["governance"] = dict(governance)
    bundle = dict(pack.get("bundle") or {})
    methods = dict(bundle.get("methods") or {})
    methods["governance"] = dict(governance)
    bundle["methods"] = methods
    pack["bundle"] = bundle
    files = _build_files(bundle, pack)
    file_manifest = _build_file_manifest(files, bundle)
    blocked_reasons = list(pack.get("blocked_reasons") or [])
    pack["files"] = files
    pack["file_manifest"] = file_manifest
    pack["summary"] = _build_summary(pack, file_manifest, blocked_reasons)


def _build_suggested_questions(
    pack: Mapping[str, Any],
    governance: Mapping[str, str],
) -> list[dict[str, str]]:
    questions = [
        {
            "question": str(governance.get("research_question") or "").strip(),
            "governance_status": str(governance.get("governance_status") or "audit_ready"),
            "source": "human_governance_metadata",
        }
    ]
    for item in pack.get("recommendations") or []:
        if isinstance(item, Mapping):
            questions.append({str(k): str(v) for k, v in item.items()})
    return [item for item in questions if item.get("question") or item.get("title")]


def _clean_text(value: str | None, default: str, *, max_len: int = 600) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        text = default
    return text[:max_len]


def _build_bundle(contract: Mapping[str, Any]) -> dict[str, Any]:
    summary = contract.get("summary") or {}
    return {
        "version": "deidentified_research_pack_v1",
        "cohort_manifest": contract.get("cohort_manifest") or {},
        "methods": {
            "study_design": "Registro longitudinal hospitalario desidentificado de cancer de prostata.",
            "source_system": "ProstaNet Clinical Fact Ledger + longitudinal tables.",
            "deidentification": [
                "No NSS, name, DOB or local internal identifiers in exported rows.",
                "Subject ids are local salted hashes.",
                "Clinical dates are reduced to month precision.",
                "Source record ids are hashed references.",
            ],
            "interoperability": "Fact rows include mCODE/FHIR and OMOP readiness targets.",
        },
        "bias_and_completeness": {
            "cohort_subject_count": summary.get("cohort_subject_count", 0),
            "real_world_readiness": summary.get("export_contract_status"),
            "direct_identifier_key_count": summary.get("direct_identifier_key_count", 0),
            "exact_phi_hit_count": summary.get("exact_phi_hit_count", 0),
            "unmapped_dictionary_count": summary.get("unmapped_dictionary_count", 0),
        },
        "export_quality": contract.get("export_quality") or {},
        "data_dictionary": contract.get("data_dictionary") or [],
        "fact_rows": contract.get("fact_rows") or [],
        "lineage_rows": contract.get("lineage_rows") or [],
        "event_rows": contract.get("event_rows") or [],
        "treatment_rows": contract.get("treatment_rows") or [],
        "biomarker_rows": contract.get("biomarker_rows") or [],
    }


def _build_files(bundle: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {
        "manifest.json": _pretty_json(
            {
                "version": bundle.get("version"),
                "cohort_manifest": bundle.get("cohort_manifest") or {},
                "methods": bundle.get("methods") or {},
                "export_quality": bundle.get("export_quality") or {},
            }
        ),
        "bundle.json": _pretty_json(bundle),
    }
    for filename, key in CSV_COMPONENTS:
        files[filename] = _rows_to_csv(bundle.get(key) or [])
    return files


def _build_file_manifest(files: Mapping[str, str], bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    row_counts = {
        "data_dictionary.csv": len(bundle.get("data_dictionary") or []),
        "fact_rows.csv": len(bundle.get("fact_rows") or []),
        "lineage_rows.csv": len(bundle.get("lineage_rows") or []),
        "events.csv": len(bundle.get("event_rows") or []),
        "treatments.csv": len(bundle.get("treatment_rows") or []),
        "biomarkers.csv": len(bundle.get("biomarker_rows") or []),
        "manifest.json": 1,
        "bundle.json": 1,
    }
    out = []
    for filename, content in sorted(files.items()):
        raw = str(content or "").encode("utf-8")
        out.append(
            {
                "file_name": filename,
                "content_type": "text/csv" if filename.endswith(".csv") else "application/json",
                "row_count": int(row_counts.get(filename) or 0),
                "byte_count": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return out


def _build_summary(
    contract: Mapping[str, Any],
    file_manifest: list[dict[str, Any]],
    blocked_reasons: list[str],
) -> dict[str, Any]:
    contract_summary = contract.get("summary") or {}
    total_data_rows = sum(
        int(contract_summary.get(key) or 0)
        for key in (
            "fact_row_count",
            "lineage_row_count",
            "event_row_count",
            "treatment_row_count",
            "biomarker_row_count",
        )
    )
    bundle_hash = hashlib.sha256(_canonical_json(file_manifest).encode("utf-8")).hexdigest()
    status = "materialization_blocked" if blocked_reasons else "ready_to_freeze_or_download"
    return {
        **contract_summary,
        "materializer_status": status,
        "next_layer_allowed": not blocked_reasons,
        "file_count": len(file_manifest),
        "total_data_rows": total_data_rows,
        "bundle_sha256": bundle_hash,
        "freeze_allowed": not blocked_reasons,
        "download_allowed": not blocked_reasons,
    }


def _blocked_reasons(summary: Mapping[str, Any]) -> list[str]:
    checks = {
        "direct_identifier_key_count": "direct_identifier_keys_present",
        "exact_phi_hit_count": "exact_phi_hits_present",
        "critical_interop_block_count": "critical_interop_blocks_present",
        "unmapped_dictionary_count": "unmapped_dictionary_fields_present",
    }
    reasons = [
        reason
        for key, reason in checks.items()
        if int(summary.get(key) or 0) > 0
    ]
    if summary.get("export_contract_status") != "ready_for_local_deidentified_export":
        reasons.append("export_contract_not_ready")
    return list(dict.fromkeys(reasons))


def _build_recommendations(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    if not summary.get("next_layer_allowed"):
        return [
            {
                "priority": "P0",
                "title": "No congelar ni descargar hasta cerrar PHI/interoperabilidad",
                "benefit": "Evita un research pack no defendible o con identificadores.",
            }
        ]
    return [
        {
            "priority": "P1",
            "title": "Congelar pack para auditoria reproducible",
            "benefit": "Cada archivo queda con hash, manifest y lineage antes de usarlo en posters o publicaciones.",
        }
    ]


def _rows_to_csv(rows: list[Mapping[str, Any]]) -> str:
    output = io.StringIO()
    if not rows:
        return ""
    fieldnames = sorted({str(key) for row in rows for key in row.keys()})
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
        )
    return output.getvalue()


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _canonical_json(value: Any) -> str:
    return json.dumps(_stable_for_hash(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_for_hash(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_for_hash(child)
            for key, child in value.items()
            if str(key) not in {"computed_at", "generated_at"}
        }
    if isinstance(value, list):
        return [_stable_for_hash(item) for item in value]
    return value
