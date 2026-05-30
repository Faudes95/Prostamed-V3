"""Reproducible no-PHI snapshot packs for the epidemiology command center."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from typing import Any, Mapping

from prostanet.domains.population_intelligence.arpi_value_analytics import (
    build_epidemiology_command_center,
)
from prostanet.shared.utc_time import utc_now_iso


EPIDEMIOLOGY_METRIC_SNAPSHOT_VERSION = "epidemiology_metric_snapshot_pack_v1"
STATISTICAL_REPRODUCTION_PACK_VERSION = "statistical_reproduction_notebook_pack_v1"
REGISTRY_TYPE = "epidemiology_metric_snapshot_v1"
DEFAULT_METHODOLOGY_VERSION = "epi_snapshot_methods_v1.0"
SUPPORTED_WEEKS = (8, 12, 16, 24, 36, 52)
GOVERNANCE_STATUSES = (
    "exploratory",
    "audit_ready",
    "poster_ready",
    "publication_ready",
    "insufficient_quality",
)
APPROVAL_STATUSES = (
    "draft",
    "human_reviewed",
    "approved_internal_audit",
    "approved_research_use",
    "blocked_quality",
)
DIRECT_IDENTIFIER_KEYS = {
    "patient_id",
    "patient_ref",
    "patient_name",
    "nss",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "capture_url",
    "local_patient_id",
    "missing_patient_refs",
}
PHI_SENTINELS = (
    "REG" + "-VALUE-",
    "ARPI" + "-VALUE-",
    "Paciente Registro " + "Valor",
    "Paciente Valor " + "ARPI",
    "/" + "patient_profile" + "/",
)


def build_epidemiology_metric_snapshot_pack(
    *,
    weeks_list: tuple[int, ...] = (12, 24, 36, 52),
    real_only: bool = False,
    filters: Mapping[str, Any] | None = None,
    trace_limit: int = 250,
    source_freeze_key: str | None = None,
    governance_status: str | None = None,
    approval_status: str | None = None,
    approved_by: str | None = None,
    reviewer_role: str | None = None,
    approval_note: str | None = None,
    methodology_version: str | None = None,
    signed_at: str | None = None,
) -> dict[str, Any]:
    """Build a frozen-dashboard preview without direct patient identifiers."""
    weeks = _normalize_weeks(weeks_list)
    dashboard = build_epidemiology_command_center(
        weeks_list=weeks,
        real_only=real_only,
        filters=filters or {},
        trace_limit=trace_limit,
        source_freeze_key=source_freeze_key,
    )
    provenance = _sanitize_value(dashboard.get("metric_provenance") or {})
    frozen_dashboard = _build_sanitized_dashboard(dashboard)
    summary = _build_summary(frozen_dashboard, provenance)
    cohort_definition = _build_cohort_definition(dashboard, weeks, real_only)
    human_approval = _build_human_approval_metadata(
        governance_status=governance_status,
        approval_status=approval_status,
        approved_by=approved_by,
        reviewer_role=reviewer_role,
        approval_note=approval_note,
        methodology_version=methodology_version,
        signed_at=signed_at,
    )
    methodology = _build_methodology(
        dashboard,
        methodology_version=human_approval["methodology_version"],
    )
    methodology["human_approval"] = dict(human_approval)
    pack_core: dict[str, Any] = {
        "available": True,
        "version": EPIDEMIOLOGY_METRIC_SNAPSHOT_VERSION,
        "snapshot_type": REGISTRY_TYPE,
        "title": "Epidemiology Metric Snapshot Pack V1",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "deidentified": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "source_context": {
            "source_mode": provenance.get("source_mode") or "live_cohort_exploratory",
            "source_freeze_key": provenance.get("source_freeze_key"),
            "payload_sha256": provenance.get("payload_sha256"),
            "registry_type": provenance.get("registry_type"),
            "requested_source_freeze_key": bool(source_freeze_key),
        },
        "cohort_definition": cohort_definition,
        "governance": {
            "human_approval": human_approval,
            "governance_statuses": list(GOVERNANCE_STATUSES),
            "approval_statuses": list(APPROVAL_STATUSES),
            "approval_contract": (
                "Snapshots exploratorios pueden congelarse como draft; uso para "
                "auditoria formal, poster o investigacion requiere revision humana, "
                "responsable, nota metodologica y version de metodo."
            ),
        },
        "summary": summary,
        "metric_provenance": provenance,
        "frozen_dashboard": frozen_dashboard,
        "methodology": methodology,
        "data_dictionary": _build_snapshot_dictionary(),
        "audit_note": (
            "Snapshot derivado del tablero epidemiologico V2. No contiene NSS, "
            "nombres, fecha de nacimiento ni URL de perfil; no muta hechos clinicos."
        ),
    }
    pack_core["snapshot_hashes"] = _build_snapshot_hashes(pack_core)
    files = _build_files(pack_core)
    pack_core["file_manifest"] = _build_file_manifest(files)
    pack_core["files"] = files
    no_phi_scan = _no_phi_scan(pack_core)
    pack_core["no_phi_scan"] = no_phi_scan
    pack_core["summary"] = {
        **pack_core["summary"],
        "no_phi_status": "pass" if _no_phi_passed(no_phi_scan) else "block",
        "governance_status": human_approval["governance_status"],
        "approval_status": human_approval["approval_status"],
        "methodology_version": human_approval["methodology_version"],
        "human_signature_required_for_external_use": human_approval["requires_signature_for_external_use"],
        "human_signature_present": human_approval["signature_present"],
        "direct_identifier_key_count": no_phi_scan["direct_identifier_key_count"],
        "exact_phi_hit_count": no_phi_scan["exact_phi_hit_count"],
        "file_count": len(files),
    }
    return pack_core


def freeze_epidemiology_metric_snapshot_pack(
    *,
    weeks_list: tuple[int, ...] = (12, 24, 36, 52),
    real_only: bool = False,
    filters: Mapping[str, Any] | None = None,
    trace_limit: int = 250,
    source_freeze_key: str | None = None,
    title: str | None = None,
    created_by: str = "clinician",
    audit_note: str | None = None,
    governance_status: str | None = None,
    approval_status: str | None = None,
    approved_by: str | None = None,
    reviewer_role: str | None = None,
    approval_note: str | None = None,
    methodology_version: str | None = None,
    signed_at: str | None = None,
) -> dict[str, Any]:
    """Persist a reproducible no-PHI snapshot in the shared freeze table."""
    pack = build_epidemiology_metric_snapshot_pack(
        weeks_list=weeks_list,
        real_only=real_only,
        filters=filters or {},
        trace_limit=trace_limit,
        source_freeze_key=source_freeze_key,
        governance_status=governance_status,
        approval_status=approval_status,
        approved_by=approved_by,
        reviewer_role=reviewer_role,
        approval_note=approval_note,
        methodology_version=methodology_version,
        signed_at=signed_at,
    )
    no_phi_scan = pack.get("no_phi_scan") or {}
    if not _no_phi_passed(no_phi_scan):
        return {
            "success": False,
            "error": "epidemiology_metric_snapshot_blocked_by_phi_scan",
            "no_phi_scan": no_phi_scan,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    governance_errors = _validate_governance_for_freeze(pack.get("governance") or {})
    if governance_errors:
        return {
            "success": False,
            "error": "epidemiology_metric_snapshot_governance_incomplete",
            "governance_errors": governance_errors,
            "governance": pack.get("governance") or {},
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }
    canonical_payload = _canonical_json(pack)
    payload_sha256 = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    freeze_key = f"episnap_{payload_sha256[:12]}"
    cohort = pack.get("cohort_definition") or {}
    summary = pack.get("summary") or {}
    freeze_title = (title or f"Epidemiology Metric Snapshot {freeze_key}").strip()
    created_by_value = (created_by or "clinician").strip() or "clinician"
    audit_note_value = audit_note or (
        "Snapshot congelado desde el gran tablero epidemiologico V2; no muta hechos "
        "clinicos, no crea ordenes externas y no entrena modelos."
    )

    import tracking_db

    conn = tracking_db._connect(write=True)
    cursor = conn.cursor()
    try:
        tracking_db._ensure_research_cohort_freeze_table(cursor)
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
                cohort.get("label"),
                tracking_db._json_blob(cohort.get("active_filters") or {}),
                tracking_db._json_blob(cohort.get("weeks") or []),
                1 if cohort.get("real_only") else 0,
                int(summary.get("metric_row_count") or 0),
                int(summary.get("patient_count_primary_window") or 0),
                tracking_db._json_blob({
                    "no_phi_scan": no_phi_scan,
                    "metric_provenance_summary": (pack.get("metric_provenance") or {}).get("summary") or {},
                    "snapshot_hashes": pack.get("snapshot_hashes") or {},
                    "human_approval": ((pack.get("governance") or {}).get("human_approval") or {}),
                }),
                tracking_db._json_blob(pack.get("methodology") or {}),
                tracking_db._json_blob({
                    "completeness_tower": (pack.get("frozen_dashboard") or {}).get("completeness_tower") or {},
                    "bias_and_readiness": (pack.get("frozen_dashboard") or {}).get("bias_and_readiness") or {},
                }),
                tracking_db._json_blob(pack.get("data_dictionary") or []),
                tracking_db._json_blob(pack.get("file_manifest") or []),
                tracking_db._json_blob(summary),
                tracking_db._json_blob(
                    ((pack.get("frozen_dashboard") or {}).get("research_workspace") or {}).get(
                        "suggested_research_questions"
                    )
                    or []
                ),
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


def list_epidemiology_metric_snapshot_freezes(*, limit: int = 25, include_payload: bool = False) -> dict[str, Any]:
    """Return only epidemiology snapshot freezes."""
    import tracking_db

    safe_limit = max(1, min(int(limit or 25), 100))
    conn = tracking_db._connect()
    cursor = conn.cursor()
    try:
        tracking_db._ensure_research_cohort_freeze_table(cursor)
        cursor.execute(
            """
            SELECT *
            FROM research_cohort_freezes
            WHERE registry_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (REGISTRY_TYPE, safe_limit),
        )
        freezes = [
            tracking_db._research_cohort_freeze_from_row(row, include_payload=include_payload)
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()
    return {
        "available": True,
        "version": "epidemiology_metric_snapshot_freeze_library_v1",
        "registry_type": REGISTRY_TYPE,
        "computed_at": utc_now_iso(),
        "summary": {
            "freeze_count": len(freezes),
            "download_ready_count": sum(1 for item in freezes if _freeze_download_allowed(item)),
        },
        "freezes": [_summarize_freeze(item, include_payload=include_payload) for item in freezes],
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def get_epidemiology_metric_snapshot_freeze(freeze_key: str) -> dict[str, Any] | None:
    """Load a single snapshot freeze with payload."""
    import tracking_db

    freeze = tracking_db.get_research_cohort_freeze(freeze_key)
    if not freeze or freeze.get("registry_type") != REGISTRY_TYPE:
        return None
    return freeze


def build_epidemiology_metric_snapshot_zip_bytes(pack_or_freeze: Mapping[str, Any]) -> bytes:
    """Build an in-memory ZIP for a preview pack or persisted freeze."""
    payload = dict(pack_or_freeze or {})
    if isinstance(payload.get("payload"), Mapping):
        payload = dict(payload["payload"])
    files = dict(payload.get("files") or {})
    if not files:
        files = _build_files(payload)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, str(content or ""))
    return buffer.getvalue()


def build_statistical_reproduction_pack(
    pack_or_freeze: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a no-DB reproduction package from a frozen snapshot payload."""
    payload = _snapshot_payload(pack_or_freeze)
    checks = run_statistical_reproduction_checks(payload)
    source_files = dict(payload.get("files") or {})
    if not source_files:
        source_files = _build_files(payload)
    reconstructed = checks.get("reconstructed_kpi_matrix") or {}
    report = _build_reproduction_report(payload, checks)
    notebook = _build_reproduction_notebook()
    script = _build_reproduction_script()
    files = {
        "README.md": _build_reproduction_readme(payload, checks),
        "snapshot.json": _pretty_json({key: value for key, value in payload.items() if key not in {"files", "file_manifest"}}),
        "governance.json": source_files.get("governance.json") or _pretty_json(payload.get("governance") or {}),
        "methodology.json": source_files.get("methodology.json") or _pretty_json(payload.get("methodology") or {}),
        "executive_kpis.csv": source_files.get("executive_kpis.csv") or "",
        "outcome_matrix.csv": source_files.get("outcome_matrix.csv") or "",
        "comparison_panel.csv": source_files.get("comparison_panel.csv") or "",
        "metric_provenance.csv": source_files.get("metric_provenance.csv") or "",
        "reconstructed_kpi_matrix.json": _pretty_json(reconstructed),
        "reproduction_report.md": report,
        "reproduce_snapshot.py": script,
        "reproduction_notebook.ipynb": _pretty_json(notebook),
    }
    manifest = _build_file_manifest(files)
    files["reproduction_manifest.json"] = _pretty_json({
        "version": STATISTICAL_REPRODUCTION_PACK_VERSION,
        "source_snapshot_version": payload.get("version"),
        "source_snapshot_sha256": (payload.get("snapshot_hashes") or {}).get("snapshot_sha256"),
        "kpi_matrix_sha256": checks.get("kpi_matrix_sha256"),
        "kpi_matrix_match": checks.get("kpi_matrix_match"),
        "no_phi_status": checks.get("no_phi_scan", {}).get("status"),
        "files": manifest,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    })
    final_manifest = _build_file_manifest(files)
    no_phi_scan = _no_phi_scan({"files": files, "checks": checks})
    return {
        "available": True,
        "version": STATISTICAL_REPRODUCTION_PACK_VERSION,
        "source_snapshot_version": payload.get("version"),
        "source_freeze_key": _source_freeze_key(pack_or_freeze),
        "generated_at": utc_now_iso(),
        "checks": checks,
        "file_manifest": final_manifest,
        "files": files,
        "no_phi_scan": {
            **no_phi_scan,
            "status": "pass" if _no_phi_passed(no_phi_scan) else "block",
        },
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def run_statistical_reproduction_checks(pack_or_freeze: Mapping[str, Any]) -> dict[str, Any]:
    """Recalculate snapshot KPI hashes and safety checks without live DB access."""
    payload = _snapshot_payload(pack_or_freeze)
    dashboard = payload.get("frozen_dashboard") or {}
    hashes = payload.get("snapshot_hashes") or {}
    reconstructed = {
        "executive_kpis": dashboard.get("executive_kpis") or [],
        "outcome_matrix": dashboard.get("outcome_matrix") or [],
        "economic_layer": dashboard.get("economic_layer") or {},
    }
    kpi_matrix_sha256 = _sha256_json(reconstructed)
    no_phi_scan = _no_phi_scan(payload)
    suppression = _audit_suppression(dashboard, payload.get("metric_provenance") or {})
    return {
        "version": "statistical_reproduction_checks_v1",
        "computed_at": utc_now_iso(),
        "reconstructed_kpi_matrix": reconstructed,
        "expected_kpi_matrix_sha256": hashes.get("kpi_matrix_sha256"),
        "kpi_matrix_sha256": kpi_matrix_sha256,
        "kpi_matrix_match": bool(hashes.get("kpi_matrix_sha256") == kpi_matrix_sha256),
        "expected_filters_sha256": hashes.get("filters_sha256"),
        "filters_sha256": _sha256_json((payload.get("cohort_definition") or {}).get("active_filters") or {}),
        "filters_hash_match": bool(
            hashes.get("filters_sha256")
            == _sha256_json((payload.get("cohort_definition") or {}).get("active_filters") or {})
        ),
        "expected_provenance_sha256": hashes.get("provenance_sha256"),
        "provenance_sha256": _sha256_json(payload.get("metric_provenance") or {}),
        "provenance_hash_match": bool(hashes.get("provenance_sha256") == _sha256_json(payload.get("metric_provenance") or {})),
        "no_phi_scan": {
            **no_phi_scan,
            "status": "pass" if _no_phi_passed(no_phi_scan) else "block",
        },
        "suppression_audit": suppression,
        "all_checks_passed": bool(
            hashes.get("kpi_matrix_sha256") == kpi_matrix_sha256
            and hashes.get("filters_sha256")
            == _sha256_json((payload.get("cohort_definition") or {}).get("active_filters") or {})
            and hashes.get("provenance_sha256") == _sha256_json(payload.get("metric_provenance") or {})
            and _no_phi_passed(no_phi_scan)
            and not suppression.get("unsuppressed_small_n_metric_count")
        ),
        "db_accessed": False,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def build_statistical_reproduction_pack_zip_bytes(pack_or_freeze: Mapping[str, Any]) -> bytes:
    """Build a ZIP containing the executable reproduction bundle."""
    package = build_statistical_reproduction_pack(pack_or_freeze)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in sorted((package.get("files") or {}).items()):
            archive.writestr(filename, str(content or ""))
    return buffer.getvalue()


def csv_for_snapshot_component(pack: Mapping[str, Any], component: str) -> str:
    """Return one public CSV component for API format adapters."""
    files = pack.get("files") or {}
    key = {
        "executive_kpis_csv": "executive_kpis.csv",
        "outcome_matrix_csv": "outcome_matrix.csv",
        "metric_provenance_csv": "metric_provenance.csv",
        "comparison_panel_csv": "comparison_panel.csv",
    }.get(component)
    return str(files.get(key) or "")


def _snapshot_payload(pack_or_freeze: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(pack_or_freeze or {})
    if isinstance(payload.get("payload"), Mapping):
        payload = dict(payload["payload"])
    return payload


def _source_freeze_key(pack_or_freeze: Mapping[str, Any]) -> str | None:
    if not isinstance(pack_or_freeze, Mapping):
        return None
    return pack_or_freeze.get("freeze_key") or (pack_or_freeze.get("source_context") or {}).get("source_freeze_key")


def _normalize_weeks(values: tuple[int, ...]) -> tuple[int, ...]:
    out: list[int] = []
    for item in values or (12, 24, 36, 52):
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value in SUPPORTED_WEEKS and value not in out:
            out.append(value)
    return tuple(out or (12, 24, 36, 52))


def _build_sanitized_dashboard(dashboard: Mapping[str, Any]) -> dict[str, Any]:
    raw_workspace = dashboard.get("research_workspace") or {}
    workspace = _sanitize_value({
        key: value
        for key, value in raw_workspace.items()
        if key not in {"recent_freezes", "freeze_count_visible"}
    })
    workspace["recent_freeze_library_omitted_from_snapshot_hash"] = True
    workspace["snapshot_pack_ready"] = True
    workspace["snapshot_freeze_endpoint"] = "/api/analytics/epidemiology-command-center/snapshot-pack/freeze"
    return {
        "version": dashboard.get("version"),
        "kpi_id": dashboard.get("kpi_id"),
        "title": dashboard.get("title"),
        "real_only": bool(dashboard.get("real_only")),
        "weeks_list": list(dashboard.get("weeks_list") or []),
        "primary_window_weeks": dashboard.get("primary_window_weeks"),
        "active_filters": _sanitize_filters(dashboard.get("active_filters") or {}),
        "filter_summary": _build_filter_summary(dashboard.get("active_filters") or {}),
        "cohort_builder": _sanitize_value(dashboard.get("cohort_builder") or {}),
        "executive_kpis": _sanitize_value(dashboard.get("executive_kpis") or []),
        "outcome_matrix": _sanitize_value(dashboard.get("outcome_matrix") or []),
        "comparison_panel": _sanitize_value(dashboard.get("comparison_panel") or {}),
        "completeness_tower": _sanitize_value(dashboard.get("completeness_tower") or {}),
        "bias_and_readiness": _sanitize_value(dashboard.get("bias_and_readiness") or {}),
        "economic_layer": _sanitize_value(dashboard.get("economic_layer") or {}),
        "longitudinal_outcomes": _sanitize_value(dashboard.get("longitudinal_outcomes") or {}),
        "operational_gap_latency": _sanitize_value(dashboard.get("operational_gap_latency") or {}),
        "patient_metric_trace_summary": _summarize_patient_trace(dashboard.get("patient_metric_trace") or []),
        "research_workspace": workspace,
        "strategic_note": dashboard.get("strategic_note"),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
    }


def _build_summary(dashboard: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    primary_week = dashboard.get("primary_window_weeks")
    primary_row = None
    for row in dashboard.get("outcome_matrix") or []:
        if str(row.get("week")) == str(primary_week):
            primary_row = row
            break
    provenance_summary = provenance.get("summary") or {}
    return {
        "primary_window_weeks": primary_week,
        "patient_count_primary_window": int((primary_row or {}).get("n_patients") or 0),
        "metric_row_count": int(provenance_summary.get("metric_count") or 0),
        "metrics_bound_to_freeze": int(provenance_summary.get("metrics_bound_to_freeze") or 0),
        "reconstructable_metric_count": int(provenance_summary.get("reconstructable_metric_count") or 0),
        "source_mode": provenance.get("source_mode") or "live_cohort_exploratory",
        "source_freeze_key": provenance.get("source_freeze_key"),
        "payload_sha256": provenance.get("payload_sha256"),
    }


def _build_cohort_definition(
    dashboard: Mapping[str, Any],
    weeks: tuple[int, ...],
    real_only: bool,
) -> dict[str, Any]:
    active_filters = dashboard.get("active_filters") or {}
    return {
        "label": _cohort_label(active_filters, weeks),
        "weeks": list(weeks),
        "primary_window_weeks": dashboard.get("primary_window_weeks"),
        "real_only": bool(real_only),
        "active_filters": _sanitize_filters(active_filters),
        "patient_ref_filter_applied": bool(str(active_filters.get("patient_ref") or "").strip()),
        "inclusion_criteria": [
            "Ventanas longitudinales ARPI calculadas en el registro V2.",
            "Metricas agregadas por semana, molecula, regimen y estado basal.",
            "Procedencia metrica disponible desde live cohort o freeze gobernado.",
        ],
        "exclusion_criteria": [
            "Identificadores directos del paciente en el snapshot no-PHI.",
            "Filas paciente-a-metrica con NSS, nombre, fecha de nacimiento o URL de perfil.",
        ],
    }


def _build_methodology(
    dashboard: Mapping[str, Any],
    *,
    methodology_version: str = DEFAULT_METHODOLOGY_VERSION,
) -> dict[str, Any]:
    return {
        "methodology_version": _clean_text(methodology_version, DEFAULT_METHODOLOGY_VERSION, max_len=80),
        "study_design": "Fotografia reproducible no-PHI del gran tablero epidemiologico V2.",
        "source_dashboard_version": dashboard.get("version"),
        "baseline_adjustment": (
            (dashboard.get("comparison_panel") or {}).get("adjustment_method")
            or "Direct standardization by baseline_state_bucket."
        ),
        "metric_families": [
            "executive_kpis",
            "outcome_matrix_12_24_36_52",
            "molecule_regimen_comparison",
            "completeness_tower",
            "economic_layer",
            "metric_provenance",
        ],
        "statistical_note": (
            "Snapshot descriptivo y auditable. No inferir causalidad hasta contar con "
            "N real suficiente, completitud alta y protocolo causal preespecificado."
        ),
        "suppression_policy": (
            (dashboard.get("metric_provenance") or {}).get("suppression_policy")
            or "n<5 suppressed for subgroup comparisons."
        ),
    }


def _build_snapshot_dictionary() -> list[dict[str, str]]:
    return [
        {"field": "snapshot_sha256", "source": "derived", "definition": "Hash estable del snapshot no-PHI."},
        {"field": "methodology_version", "source": "human_governance", "definition": "Version humana del metodo usado para interpretar el snapshot."},
        {"field": "approval_status", "source": "human_governance", "definition": "Estado de revision/aprobacion humana del snapshot."},
        {"field": "metric_id", "source": "metric_provenance", "definition": "Identificador reproducible de metrica."},
        {"field": "metric_family", "source": "metric_provenance", "definition": "Familia de metrica del tablero."},
        {"field": "primary_window_weeks", "source": "epidemiology_command_center_v2", "definition": "Ventana principal seleccionada."},
        {"field": "n_patients", "source": "outcome_matrix", "definition": "Conteo agregado de pacientes; no identificador."},
        {"field": "estimated_spend_to_window_mxn", "source": "economic_layer", "definition": "Gasto local estimado agregado."},
        {"field": "source_freeze_key", "source": "metric_provenance", "definition": "Freeze gobernado usado para procedencia, si existe."},
    ]


def _build_snapshot_hashes(pack: Mapping[str, Any]) -> dict[str, str]:
    dashboard = pack.get("frozen_dashboard") or {}
    provenance = pack.get("metric_provenance") or {}
    return {
        "snapshot_sha256": _sha256_json(pack),
        "filters_sha256": _sha256_json((pack.get("cohort_definition") or {}).get("active_filters") or {}),
        "kpi_matrix_sha256": _sha256_json({
            "executive_kpis": dashboard.get("executive_kpis") or [],
            "outcome_matrix": dashboard.get("outcome_matrix") or [],
            "economic_layer": dashboard.get("economic_layer") or {},
        }),
        "provenance_sha256": _sha256_json(provenance),
    }


def _build_files(pack: Mapping[str, Any]) -> dict[str, str]:
    payload = {key: value for key, value in dict(pack or {}).items() if key not in {"files", "file_manifest"}}
    dashboard = payload.get("frozen_dashboard") or {}
    provenance = payload.get("metric_provenance") or {}
    files = {
        "manifest.json": _pretty_json({
            "version": payload.get("version"),
            "snapshot_type": payload.get("snapshot_type"),
            "summary": payload.get("summary") or {},
            "snapshot_hashes": payload.get("snapshot_hashes") or {},
            "no_phi_scan": payload.get("no_phi_scan") or {},
            "governance": payload.get("governance") or {},
        }),
        "snapshot.json": _pretty_json(payload),
        "methodology.json": _pretty_json(payload.get("methodology") or {}),
        "governance.json": _pretty_json(payload.get("governance") or {}),
        "executive_kpis.csv": _rows_to_csv(dashboard.get("executive_kpis") or []),
        "outcome_matrix.csv": _rows_to_csv(dashboard.get("outcome_matrix") or []),
        "comparison_panel.csv": _comparison_rows_to_csv((dashboard.get("comparison_panel") or {}).get("cohort_matrix") or []),
        "metric_provenance.csv": _metric_provenance_to_csv(provenance.get("metrics") or []),
    }
    return files


def _build_file_manifest(files: Mapping[str, str]) -> list[dict[str, Any]]:
    manifest = []
    for filename, content in sorted(files.items()):
        raw = str(content or "").encode("utf-8")
        row_count = max(0, str(content or "").count("\n") - 1) if filename.endswith(".csv") else 1
        manifest.append(
            {
                "file_name": filename,
                "content_type": "text/csv" if filename.endswith(".csv") else "application/json",
                "row_count": row_count,
                "byte_count": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return manifest


def _audit_suppression(
    dashboard: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    small_n_metrics = []
    for row in provenance.get("metrics") or []:
        if not isinstance(row, Mapping):
            continue
        n_value = _safe_int(row.get("n"), None)
        if n_value is not None and 0 < n_value < 5:
            small_n_metrics.append(
                {
                    "metric_id": row.get("metric_id"),
                    "metric_key": row.get("metric_key"),
                    "n": n_value,
                    "suppression_policy": row.get("suppression_policy") or provenance.get("suppression_policy"),
                }
            )
    unsuppressed = [
        item for item in small_n_metrics
        if not str(item.get("suppression_policy") or "").strip()
    ]
    comparison_small_n = []
    for group in ((dashboard.get("comparison_panel") or {}).get("cohort_matrix") or []):
        if not isinstance(group, Mapping):
            continue
        for week, window in (group.get("windows") or {}).items():
            if not isinstance(window, Mapping):
                continue
            n_value = _safe_int(window.get("n"), None)
            if n_value is not None and 0 < n_value < 5:
                comparison_small_n.append(
                    {
                        "group_type": group.get("group_type"),
                        "key": group.get("key"),
                        "week": week,
                        "n": n_value,
                        "suppressed": bool(window.get("suppressed")),
                    }
                )
    return {
        "policy": provenance.get("suppression_policy") or "n<5 suppressed for subgroup comparisons.",
        "small_n_metric_count": len(small_n_metrics),
        "unsuppressed_small_n_metric_count": len(unsuppressed),
        "comparison_small_n_count": len(comparison_small_n),
        "comparison_small_n_review": comparison_small_n[:25],
        "metric_small_n_review": small_n_metrics[:25],
    }


def _build_reproduction_report(payload: Mapping[str, Any], checks: Mapping[str, Any]) -> str:
    summary = payload.get("summary") or {}
    governance = (payload.get("governance") or {}).get("human_approval") or {}
    no_phi = checks.get("no_phi_scan") or {}
    suppression = checks.get("suppression_audit") or {}
    status = "PASS" if checks.get("all_checks_passed") else "REVIEW_REQUIRED"
    lines = [
        "# Statistical Reproduction Report",
        "",
        f"- Status: {status}",
        f"- Snapshot version: {payload.get('version')}",
        f"- Methodology version: {governance.get('methodology_version') or summary.get('methodology_version')}",
        f"- Governance: {governance.get('governance_status') or summary.get('governance_status')}",
        f"- Approval: {governance.get('approval_status') or summary.get('approval_status')}",
        f"- Signature present: {bool(governance.get('signature_present'))}",
        f"- Primary window: {summary.get('primary_window_weeks')} weeks",
        f"- Primary patients: {summary.get('patient_count_primary_window')}",
        "",
        "## Hash Checks",
        "",
        f"- KPI matrix SHA256: {checks.get('kpi_matrix_sha256')}",
        f"- KPI matrix match: {checks.get('kpi_matrix_match')}",
        f"- Filters hash match: {checks.get('filters_hash_match')}",
        f"- Provenance hash match: {checks.get('provenance_hash_match')}",
        "",
        "## No-PHI Checks",
        "",
        f"- Status: {no_phi.get('status')}",
        f"- Direct identifier key count: {no_phi.get('direct_identifier_key_count')}",
        f"- Exact PHI hit count: {no_phi.get('exact_phi_hit_count')}",
        "",
        "## Suppression Checks",
        "",
        f"- Policy: {suppression.get('policy')}",
        f"- Small-n metric count: {suppression.get('small_n_metric_count')}",
        f"- Unsuppressed small-n metric count: {suppression.get('unsuppressed_small_n_metric_count')}",
        "",
        "## Boundary",
        "",
        "This package reproduces aggregate tables from snapshot.json only. It does not access the live database, mutate clinical facts, create external orders, or train models.",
    ]
    return "\n".join(lines) + "\n"


def _build_reproduction_readme(payload: Mapping[str, Any], checks: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# ProstaNet Statistical Reproduction Pack",
            "",
            "Run locally with:",
            "",
            "```bash",
            "python3 reproduce_snapshot.py",
            "```",
            "",
            "Expected outputs:",
            "",
            "- `reproduction_report.md`",
            "- `reconstructed_kpi_matrix.json`",
            "",
            f"Snapshot version: `{payload.get('version')}`",
            f"KPI matrix hash match at generation: `{checks.get('kpi_matrix_match')}`",
            f"No-PHI status at generation: `{(checks.get('no_phi_scan') or {}).get('status')}`",
            "",
            "No database connection is required.",
        ]
    ) + "\n"


def _build_reproduction_script() -> str:
    return r'''#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DIRECT_IDENTIFIER_KEYS = {
    "patient_id",
    "patient_ref",
    "patient_name",
    "nss",
    "full_name",
    "dob",
    "date_of_birth",
    "profile_url",
    "local_patient_id",
}
PHI_SENTINELS = (
    "REG" + "-VALUE-",
    "ARPI" + "-VALUE-",
    "Paciente Registro " + "Valor",
    "Paciente Valor " + "ARPI",
    "/" + "patient_profile" + "/",
)


def stable(value):
    if isinstance(value, dict):
        return {
            str(key): stable(item)
            for key, item in value.items()
            if key not in {"generated_at", "computed_at", "created_at", "signed_at", "files", "file_manifest"}
        }
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def sha256_json(value):
    raw = json.dumps(stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def collect_direct_keys(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in DIRECT_IDENTIFIER_KEYS:
                found.add(str(key))
            found |= collect_direct_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= collect_direct_keys(item)
    return found


def no_phi_scan(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    direct_keys = sorted(collect_direct_keys(payload))
    exact_hits = sorted(token for token in PHI_SENTINELS if token in text)
    return {
        "status": "pass" if not direct_keys and not exact_hits else "block",
        "direct_identifier_key_count": len(direct_keys),
        "direct_identifier_keys": direct_keys,
        "exact_phi_hit_count": len(exact_hits),
        "exact_phi_hits": exact_hits,
    }


def main():
    snapshot = json.loads(Path("snapshot.json").read_text(encoding="utf-8"))
    dashboard = snapshot.get("frozen_dashboard") or {}
    reconstructed = {
        "executive_kpis": dashboard.get("executive_kpis") or [],
        "outcome_matrix": dashboard.get("outcome_matrix") or [],
        "economic_layer": dashboard.get("economic_layer") or {},
    }
    checks = {
        "kpi_matrix_sha256": sha256_json(reconstructed),
        "expected_kpi_matrix_sha256": (snapshot.get("snapshot_hashes") or {}).get("kpi_matrix_sha256"),
        "filters_sha256": sha256_json((snapshot.get("cohort_definition") or {}).get("active_filters") or {}),
        "expected_filters_sha256": (snapshot.get("snapshot_hashes") or {}).get("filters_sha256"),
        "provenance_sha256": sha256_json(snapshot.get("metric_provenance") or {}),
        "expected_provenance_sha256": (snapshot.get("snapshot_hashes") or {}).get("provenance_sha256"),
        "no_phi_scan": no_phi_scan(snapshot),
        "db_accessed": False,
    }
    checks["kpi_matrix_match"] = checks["kpi_matrix_sha256"] == checks["expected_kpi_matrix_sha256"]
    checks["filters_hash_match"] = checks["filters_sha256"] == checks["expected_filters_sha256"]
    checks["provenance_hash_match"] = checks["provenance_sha256"] == checks["expected_provenance_sha256"]
    checks["all_checks_passed"] = (
        checks["kpi_matrix_match"]
        and checks["filters_hash_match"]
        and checks["provenance_hash_match"]
        and checks["no_phi_scan"]["status"] == "pass"
    )
    Path("reconstructed_kpi_matrix.json").write_text(
        json.dumps(reconstructed, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    report = [
        "# Statistical Reproduction Report",
        "",
        f"- Status: {'PASS' if checks['all_checks_passed'] else 'REVIEW_REQUIRED'}",
        f"- KPI matrix match: {checks['kpi_matrix_match']}",
        f"- Filters hash match: {checks['filters_hash_match']}",
        f"- Provenance hash match: {checks['provenance_hash_match']}",
        f"- No-PHI status: {checks['no_phi_scan']['status']}",
        f"- DB accessed: {checks['db_accessed']}",
        "",
    ]
    Path("reproduction_report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
'''


def _build_reproduction_notebook() -> dict[str, Any]:
    code = "\n".join(
        [
            "import json, hashlib",
            "from pathlib import Path",
            "snapshot = json.loads(Path('snapshot.json').read_text(encoding='utf-8'))",
            "dashboard = snapshot.get('frozen_dashboard', {})",
            "reconstructed = {",
            "    'executive_kpis': dashboard.get('executive_kpis', []),",
            "    'outcome_matrix': dashboard.get('outcome_matrix', []),",
            "    'economic_layer': dashboard.get('economic_layer', {}),",
            "}",
            "print('Rows:', len(reconstructed['executive_kpis']), len(reconstructed['outcome_matrix']))",
            "print('Expected KPI matrix SHA:', snapshot.get('snapshot_hashes', {}).get('kpi_matrix_sha256'))",
        ]
    )
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# ProstaNet Statistical Reproduction Notebook\n",
                    "Reconstructs aggregate KPI tables from `snapshot.json` without live DB access.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [line + "\n" for line in code.splitlines()],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.x"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _build_human_approval_metadata(
    *,
    governance_status: str | None,
    approval_status: str | None,
    approved_by: str | None,
    reviewer_role: str | None,
    approval_note: str | None,
    methodology_version: str | None,
    signed_at: str | None,
) -> dict[str, Any]:
    governance = _normalize_choice(governance_status, GOVERNANCE_STATUSES, "exploratory")
    approval = _normalize_choice(approval_status, APPROVAL_STATUSES, "draft")
    reviewer = _clean_text(approved_by, "", max_len=120)
    role = _clean_text(reviewer_role, "clinician", max_len=80)
    note = _clean_text(approval_note, "", max_len=900)
    method_version = _clean_text(methodology_version, DEFAULT_METHODOLOGY_VERSION, max_len=80)
    signature_present = bool(reviewer and approval != "draft")
    signature_payload = {
        "governance_status": governance,
        "approval_status": approval,
        "approved_by": reviewer,
        "reviewer_role": role,
        "approval_note": note,
        "methodology_version": method_version,
    }
    return {
        **signature_payload,
        "signed_at": _clean_text(signed_at, utc_now_iso() if signature_present else "", max_len=40),
        "signature_present": signature_present,
        "requires_signature_for_external_use": governance in {"poster_ready", "publication_ready"}
        or approval in {"approved_internal_audit", "approved_research_use"},
        "approval_statement": _approval_statement(governance, approval),
        "approval_signature_sha256": _sha256_json(signature_payload),
        "data_use_boundary": (
            "Uso interno local y auditoria institucional; uso externo requiere "
            "revision humana, aprobacion institucional y cumplimiento de protocolo."
        ),
    }


def _validate_governance_for_freeze(governance: Mapping[str, Any]) -> list[str]:
    approval = (governance.get("human_approval") or {}) if isinstance(governance, Mapping) else {}
    governance_status = str(approval.get("governance_status") or "")
    approval_status = str(approval.get("approval_status") or "")
    approved_by = str(approval.get("approved_by") or "").strip()
    approval_note = str(approval.get("approval_note") or "").strip()
    errors: list[str] = []
    if governance_status in {"poster_ready", "publication_ready"} and approval_status != "approved_research_use":
        errors.append("poster_or_publication_ready_requires_approved_research_use")
    if approval_status in {"approved_internal_audit", "approved_research_use"}:
        if not approved_by:
            errors.append("approved_snapshot_requires_approved_by")
        if len(approval_note) < 8:
            errors.append("approved_snapshot_requires_methodology_note")
    if governance_status == "insufficient_quality" and approval_status.startswith("approved_"):
        errors.append("insufficient_quality_cannot_be_approved")
    return errors


def _normalize_choice(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in allowed else default


def _approval_statement(governance_status: str, approval_status: str) -> str:
    if approval_status == "approved_research_use":
        return "Aprobado por revision humana para uso metodologico de investigacion interna segun alcance indicado."
    if approval_status == "approved_internal_audit":
        return "Aprobado por revision humana para auditoria interna institucional."
    if approval_status == "human_reviewed":
        return "Revisado por humano; requiere aprobacion adicional antes de uso externo."
    if governance_status == "insufficient_quality" or approval_status == "blocked_quality":
        return "Bloqueado por calidad; no usar para inferencia, poster o decision institucional."
    return "Draft exploratorio sin firma humana formal."


def _clean_text(value: str | None, default: str, *, max_len: int = 300) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        text = default
    return text[:max_len]


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "patient_metric_trace":
                continue
            if key_text in DIRECT_IDENTIFIER_KEYS:
                continue
            if key_text == "active_filters":
                out[key_text] = _sanitize_filters(item if isinstance(item, Mapping) else {})
                continue
            out[key_text] = _sanitize_value(item)
        return out
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    return value


def _sanitize_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in (filters or {}).items():
        key_text = str(key)
        if key_text in {"patient_ref", "nss"}:
            continue
        out[key_text] = _sanitize_value(value)
    return out


def _build_filter_summary(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "active_filter_keys": sorted(
            key for key, value in (filters or {}).items()
            if key not in {"patient_ref", "nss"} and value not in (None, "")
        ),
        "patient_ref_filter_applied": bool(str((filters or {}).get("patient_ref") or "").strip()),
    }


def _summarize_patient_trace(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    week_counts: dict[str, int] = {}
    regimen_counts: dict[str, int] = {}
    for row in rows:
        week = str(row.get("week") or "")
        regimen = str(row.get("regimen_code") or row.get("regimen_label") or "")
        if week:
            week_counts[week] = week_counts.get(week, 0) + 1
        if regimen:
            regimen_counts[regimen] = regimen_counts.get(regimen, 0) + 1
    return {
        "source_trace_row_count": len(rows),
        "weeks": week_counts,
        "regimens": regimen_counts,
        "patient_level_rows_omitted_for_no_phi": True,
    }


def _cohort_label(filters: Mapping[str, Any], weeks: tuple[int, ...]) -> str:
    active = [
        f"{key}={value}"
        for key, value in (filters or {}).items()
        if key not in {"patient_ref", "nss"} and value not in (None, "")
    ]
    return "Epidemiology snapshot " + "/".join(str(item) for item in weeks) + (" | " + ", ".join(active) if active else "")


def _metric_provenance_to_csv(rows: list[Mapping[str, Any]]) -> str:
    fieldnames = [
        "metric_id",
        "metric_key",
        "metric_family",
        "label",
        "value",
        "n",
        "source_freeze_key",
        "payload_sha256",
        "reconstruction_status",
        "dictionary_fields",
        "row_families",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        reconstruction = row.get("reconstruction") or {}
        writer.writerow(
            {
                "metric_id": row.get("metric_id"),
                "metric_key": row.get("metric_key"),
                "metric_family": row.get("metric_family"),
                "label": row.get("label"),
                "value": row.get("value"),
                "n": row.get("n"),
                "source_freeze_key": row.get("source_freeze_key"),
                "payload_sha256": row.get("payload_sha256"),
                "reconstruction_status": reconstruction.get("status"),
                "dictionary_fields": "|".join(
                    str(item.get("field") or "")
                    for item in row.get("data_dictionary_refs") or []
                    if isinstance(item, Mapping)
                ),
                "row_families": "|".join(
                    f"{item.get('family')}:{item.get('row_count')}"
                    for item in row.get("row_family_refs") or []
                    if isinstance(item, Mapping)
                ),
            }
        )
    return out.getvalue()


def _comparison_rows_to_csv(rows: list[Mapping[str, Any]]) -> str:
    fieldnames = ["group_type", "key", "label", "weeks_json"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "group_type": row.get("group_type"),
                "key": row.get("key"),
                "label": row.get("label"),
                "weeks_json": json.dumps(row.get("windows") or {}, ensure_ascii=False, sort_keys=True),
            }
        )
    return out.getvalue()


def _rows_to_csv(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    fieldnames = sorted({str(key) for row in rows if isinstance(row, Mapping) for key in row.keys()})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            }
        )
    return out.getvalue()


def _no_phi_scan(payload: Mapping[str, Any]) -> dict[str, Any]:
    direct_keys = sorted(_collect_direct_identifier_keys(payload))
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    exact_hits = sorted(token for token in PHI_SENTINELS if token and token in text)
    return {
        "direct_identifier_key_count": len(direct_keys),
        "direct_identifier_keys": direct_keys,
        "exact_phi_hit_count": len(exact_hits),
        "exact_phi_hits": exact_hits,
        "patient_level_trace_omitted": True,
    }


def _collect_direct_identifier_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in DIRECT_IDENTIFIER_KEYS:
                found.add(key_text)
            found |= _collect_direct_identifier_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _collect_direct_identifier_keys(item)
    return found


def _no_phi_passed(scan: Mapping[str, Any]) -> bool:
    return int(scan.get("direct_identifier_key_count") or 0) == 0 and int(scan.get("exact_phi_hit_count") or 0) == 0


def _freeze_download_allowed(freeze: Mapping[str, Any]) -> bool:
    readiness = freeze.get("readiness") or {}
    scan = readiness.get("no_phi_scan") or {}
    return _no_phi_passed(scan)


def _summarize_freeze(freeze: Mapping[str, Any], *, include_payload: bool) -> dict[str, Any]:
    readiness = freeze.get("readiness") or {}
    scan = readiness.get("no_phi_scan") or {}
    human_approval = readiness.get("human_approval") or {}
    methods = freeze.get("methods") or {}
    if not human_approval and isinstance(methods.get("human_approval"), Mapping):
        human_approval = dict(methods.get("human_approval") or {})
    item = {
        "freeze_key": freeze.get("freeze_key"),
        "title": freeze.get("title"),
        "registry_type": freeze.get("registry_type"),
        "cohort_label": freeze.get("cohort_label"),
        "created_at": freeze.get("created_at"),
        "created_by": freeze.get("created_by"),
        "status": freeze.get("status"),
        "audit_note": freeze.get("audit_note"),
        "payload_sha256": freeze.get("payload_sha256"),
        "weeks": freeze.get("weeks") or [],
        "filters": freeze.get("filters") or {},
        "trace_row_count": freeze.get("trace_row_count") or 0,
        "patient_count_primary_window": freeze.get("patient_count_primary_window") or 0,
        "summary": freeze.get("registry_summary") or {},
        "human_approval": human_approval,
        "governance_status": human_approval.get("governance_status") or "exploratory",
        "approval_status": human_approval.get("approval_status") or "draft",
        "methodology_version": human_approval.get("methodology_version")
        or methods.get("methodology_version")
        or DEFAULT_METHODOLOGY_VERSION,
        "no_phi_scan": scan,
        "download_allowed": _no_phi_passed(scan),
        "detail_url": f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze.get('freeze_key')}",
        "download_url": f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze.get('freeze_key')}/download",
        "reproduction_pack_url": f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze.get('freeze_key')}/reproduction-pack",
        "reproduction_pack_download_url": f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze.get('freeze_key')}/reproduction-pack/download",
    }
    if include_payload:
        item["payload"] = freeze.get("payload") or {}
    return item


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int | None = 0) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _canonical_json(value: Any) -> str:
    stable = _stable_for_hash(value)
    return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_for_hash(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_for_hash(item)
            for key, item in value.items()
            if key not in {"generated_at", "computed_at", "created_at", "signed_at", "files", "file_manifest"}
        }
    if isinstance(value, list):
        return [_stable_for_hash(item) for item in value]
    return value


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
