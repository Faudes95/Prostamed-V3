"""Read-only de-identified cohort export contract.

This is a readiness layer, not a production data export. It proves that the
Clinical Fact Ledger can be projected into a reproducible research package
without direct patient identifiers and with fact-level interoperability lineage.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping

from prostanet.domains.platform_readiness.interoperability_map import (
    INTEROPERABILITY_MAP_VERSION,
    build_interoperability_map,
)
from prostanet.domains.platform_readiness.ledger_release_gate import DOMAIN_OWNERS
from prostanet.shared.clinical_fact_registry import FACT_SPECS
from prostanet.shared.utc_time import utc_now_iso


DEIDENTIFIED_EXPORT_CONTRACT_VERSION = "deidentified_cohort_export_contract_v1"
DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "full_name",
    "name",
    "nombre",
    "patient_name",
    "dob",
    "date_of_birth",
    "birth_date",
    "patient_id",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


def build_deidentified_export_contract(
    *,
    scope: str = "full",
    limit: int = 50,
    real_only: bool = False,
) -> dict[str, Any]:
    """Build a read-only, PHI-suppressed export readiness package."""
    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    row_limit = max(1, min(int(limit or 50), 500))
    patients = _load_patient_index(limit=row_limit, real_only=real_only)
    patient_ids = [int(row["id"]) for row in patients]
    subject_by_patient_id = {
        int(row["id"]): _subject_id(row["id"])
        for row in patients
    }
    interop = build_interoperability_map(scope="full", field_limit=2000)
    interop_by_fact = {
        str(row.get("fact_key") or ""): row
        for row in interop.get("mapping") or []
        if row.get("fact_key")
    }

    fact_rows = _build_fact_rows(patient_ids, subject_by_patient_id, interop_by_fact)
    event_rows = _build_event_rows(patient_ids, subject_by_patient_id)
    treatment_rows = _build_treatment_rows(patient_ids, subject_by_patient_id)
    biomarker_rows = _build_biomarker_rows(patient_ids, subject_by_patient_id)
    lineage_rows = _build_lineage_rows(fact_rows)
    data_dictionary = _build_data_dictionary(interop_by_fact)
    export_quality = _build_export_quality(
        patients,
        fact_rows=fact_rows,
        event_rows=event_rows,
        treatment_rows=treatment_rows,
        biomarker_rows=biomarker_rows,
        lineage_rows=lineage_rows,
        data_dictionary=data_dictionary,
        interop_summary=interop.get("summary") or {},
    )
    recommendations = _build_recommendations(export_quality)

    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_fact_ledger_deidentified_export_contract",
        "version": DEIDENTIFIED_EXPORT_CONTRACT_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "deidentified": True,
        "export_written": False,
        "external_transfer_performed": False,
        "date_policy": "clinical_dates_month_precision",
        "subject_id_policy": "sha256_local_surrogate_not_reversible_without_local_source",
        "interop_map_version": INTEROPERABILITY_MAP_VERSION,
        "summary": export_quality["summary"],
        "cohort_manifest": _build_manifest(patients, real_only=real_only),
        "export_quality": export_quality,
        "recommendations": recommendations,
    }
    if include_rows:
        payload.update(
            {
                "data_dictionary": data_dictionary,
                "fact_rows": fact_rows,
                "event_rows": event_rows,
                "treatment_rows": treatment_rows,
                "biomarker_rows": biomarker_rows,
                "lineage_rows": lineage_rows,
            }
        )
    return payload


def _connect():
    import tracking_db

    return tracking_db._connect()


def _load_patient_index(*, limit: int, real_only: bool) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        where = "WHERE COALESCE(is_synthetic, 1) = 0" if real_only else ""
        rows = conn.execute(
            f"""
            SELECT id, is_synthetic, diagnosis_date, created_at
            FROM patient_identity
            {where}
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _build_fact_rows(
    patient_ids: list[int],
    subject_by_patient_id: Mapping[int, str],
    interop_by_fact: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    conn = _connect()
    try:
        placeholders = ",".join(["?"] * len(patient_ids))
        rows = conn.execute(
            f"""
            SELECT fact_key, patient_id, value_json, normalized_value_text,
                   source_type, source_record_type, source_record_id,
                   source_date, observed_at, state_context, management_track,
                   certainty_tier, freshness_status, clinician_verified,
                   created_at, updated_at
            FROM patient_clinical_facts
            WHERE patient_id IN ({placeholders}) AND COALESCE(is_active, 1) = 1
            ORDER BY patient_id ASC, fact_key ASC, updated_at DESC, id DESC
            """,
            patient_ids,
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        item = dict(row)
        fact_key = str(item.get("fact_key") or "")
        spec = FACT_SPECS.get(fact_key)
        interop = dict(interop_by_fact.get(fact_key) or {})
        out.append(
            {
                "subject_id": subject_by_patient_id.get(int(item["patient_id"])),
                "fact_key": fact_key,
                "domain": spec.domain if spec else "",
                "owner": DOMAIN_OWNERS.get(spec.domain, f"{spec.domain}_owner") if spec else "",
                "value_type": spec.value_type if spec else "unknown",
                "value": _safe_value(item.get("normalized_value_text"), item.get("value_json")),
                "source_type": _safe_text(item.get("source_type")),
                "source_record_type": _safe_text(item.get("source_record_type")),
                "source_record_ref": _row_ref("source", item.get("source_record_id")),
                "source_month": _month(item.get("source_date")),
                "observed_month": _month(item.get("observed_at")),
                "state_context": _safe_text(item.get("state_context")),
                "management_track": _safe_text(item.get("management_track")),
                "certainty_tier": _safe_text(item.get("certainty_tier")),
                "freshness_status": _safe_text(item.get("freshness_status")),
                "clinician_verified": bool(item.get("clinician_verified")),
                "updated_month": _month(item.get("updated_at")),
                "mcode_profile": interop.get("mcode_profile", ""),
                "omop_target": interop.get("omop_target", ""),
                "mapping_status": interop.get("mapping_status", "unmapped"),
            }
        )
    return out


def _build_event_rows(
    patient_ids: list[int],
    subject_by_patient_id: Mapping[int, str],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    conn = _connect()
    try:
        placeholders = ",".join(["?"] * len(patient_ids))
        patient_events = conn.execute(
            f"""
            SELECT id, patient_id, event_type, event_date, state_context,
                   management_track, source_type, source_record_id, status,
                   created_at
            FROM patient_events
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, event_date DESC, id DESC
            """,
            patient_ids,
        ).fetchall()
        outcome_events = conn.execute(
            f"""
            SELECT id, patient_id, event_type, event_date, scenario_state,
                   management_track, axis, adjudication_status, source_priority,
                   decision_impact, provisional, active, created_at
            FROM outcome_events
            WHERE patient_id IN ({placeholders}) AND COALESCE(active, 1) = 1
            ORDER BY patient_id ASC, event_date DESC, id DESC
            """,
            patient_ids,
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in patient_events:
        item = dict(row)
        out.append(
            {
                "subject_id": subject_by_patient_id.get(int(item["patient_id"])),
                "event_ref": _row_ref("patient_event", item.get("id")),
                "event_family": "patient_event",
                "event_type": _safe_text(item.get("event_type")),
                "event_month": _month(item.get("event_date")),
                "state_context": _safe_text(item.get("state_context")),
                "management_track": _safe_text(item.get("management_track")),
                "source_type": _safe_text(item.get("source_type")),
                "source_record_ref": _row_ref("source", item.get("source_record_id")),
                "status": _safe_text(item.get("status")),
            }
        )
    for row in outcome_events:
        item = dict(row)
        out.append(
            {
                "subject_id": subject_by_patient_id.get(int(item["patient_id"])),
                "event_ref": _row_ref("outcome_event", item.get("id")),
                "event_family": "outcome_event",
                "event_type": _safe_text(item.get("event_type")),
                "event_month": _month(item.get("event_date")),
                "state_context": _safe_text(item.get("scenario_state")),
                "management_track": _safe_text(item.get("management_track")),
                "axis": _safe_text(item.get("axis")),
                "adjudication_status": _safe_text(item.get("adjudication_status")),
                "source_priority": _safe_text(item.get("source_priority")),
                "decision_impact": _safe_text(item.get("decision_impact")),
                "provisional": bool(item.get("provisional")),
            }
        )
    return out


def _build_treatment_rows(
    patient_ids: list[int],
    subject_by_patient_id: Mapping[int, str],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    conn = _connect()
    try:
        placeholders = ",".join(["?"] * len(patient_ids))
        treatments = conn.execute(
            f"""
            SELECT id, patient_id, line_of_therapy, drug_scheme, start_date,
                   end_date, outcome, nadir_psa, time_to_nadir_months,
                   class_exhausted, discontinuation_reason, line_of_therapy_context
            FROM treatment_history
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, start_date ASC, id ASC
            """,
            patient_ids,
        ).fetchall()
        doses = conn.execute(
            f"""
            SELECT id, patient_id, treatment_history_id, regimen_code,
                   dose_number_local, dose_number_global, dose_date,
                   administered_in_unit, referral_target, estimated_cost_mxn,
                   created_at
            FROM treatment_dose_administrations
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, dose_date ASC, id ASC
            """,
            patient_ids,
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in treatments:
        item = dict(row)
        out.append(
            {
                "subject_id": subject_by_patient_id.get(int(item["patient_id"])),
                "row_ref": _row_ref("treatment", item.get("id")),
                "row_type": "treatment_line",
                "treatment_ref": _row_ref("treatment", item.get("id")),
                "line_of_therapy": item.get("line_of_therapy"),
                "regimen_code": _safe_text(item.get("drug_scheme")),
                "start_month": _month(item.get("start_date")),
                "end_month": _month(item.get("end_date")),
                "outcome": _safe_text(item.get("outcome")),
                "nadir_psa": item.get("nadir_psa"),
                "time_to_nadir_months": item.get("time_to_nadir_months"),
                "class_exhausted": _safe_text(item.get("class_exhausted")),
                "discontinuation_reason": _safe_text(item.get("discontinuation_reason")),
                "line_context": _safe_text(item.get("line_of_therapy_context")),
            }
        )
    for row in doses:
        item = dict(row)
        out.append(
            {
                "subject_id": subject_by_patient_id.get(int(item["patient_id"])),
                "row_ref": _row_ref("dose", item.get("id")),
                "row_type": "dose_administration",
                "treatment_ref": _row_ref("treatment", item.get("treatment_history_id")),
                "regimen_code": _safe_text(item.get("regimen_code")),
                "dose_number_local": item.get("dose_number_local"),
                "dose_number_global": item.get("dose_number_global"),
                "dose_month": _month(item.get("dose_date")),
                "administered_in_unit": bool(item.get("administered_in_unit")),
                "referral_target": _safe_text(item.get("referral_target")),
                "estimated_cost_mxn": item.get("estimated_cost_mxn"),
            }
        )
    return out


def _build_biomarker_rows(
    patient_ids: list[int],
    subject_by_patient_id: Mapping[int, str],
) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    conn = _connect()
    try:
        placeholders = ",".join(["?"] * len(patient_ids))
        rows = conn.execute(
            f"""
            SELECT id, patient_id, biomarker_type, value, unit, sample_date,
                   lab_source, created_at
            FROM biomarker_longitudinal
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, sample_date ASC, id ASC
            """,
            patient_ids,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "subject_id": subject_by_patient_id.get(int(row["patient_id"])),
            "biomarker_ref": _row_ref("biomarker", row["id"]),
            "biomarker_type": _safe_text(row["biomarker_type"]),
            "value": row["value"],
            "unit": _safe_text(row["unit"]),
            "sample_month": _month(row["sample_date"]),
            "lab_source_category": "documented" if row["lab_source"] else "",
        }
        for row in rows
    ]


def _build_lineage_rows(fact_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "subject_id": row["subject_id"],
            "fact_key": row["fact_key"],
            "source_type": row["source_type"],
            "source_record_type": row["source_record_type"],
            "source_record_ref": row["source_record_ref"],
            "source_month": row["source_month"],
            "observed_month": row["observed_month"],
            "freshness_status": row["freshness_status"],
            "mapping_status": row["mapping_status"],
            "mcode_profile": row["mcode_profile"],
            "omop_target": row["omop_target"],
        }
        for row in fact_rows
    ]


def _build_data_dictionary(interop_by_fact: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fact_key, spec in FACT_SPECS.items():
        interop = dict(interop_by_fact.get(fact_key) or {})
        rows.append(
            {
                "field": fact_key,
                "domain": spec.domain,
                "value_type": spec.value_type,
                "blocking": bool(spec.blocking),
                "owner": DOMAIN_OWNERS.get(spec.domain, f"{spec.domain}_owner"),
                "legacy_aliases": list(spec.legacy_aliases or ()),
                "consumers": list(spec.consumers or ()),
                "mcode_profile": interop.get("mcode_profile", ""),
                "fhir_target": interop.get("fhir_target", ""),
                "omop_target": interop.get("omop_target", ""),
                "vocabulary": interop.get("vocabulary", ""),
                "mapping_status": interop.get("mapping_status", "unmapped"),
            }
        )
    return rows


def _build_manifest(patients: list[Mapping[str, Any]], *, real_only: bool) -> dict[str, Any]:
    synthetic_counts = Counter(
        "synthetic" if int(row.get("is_synthetic") or 0) else "real"
        for row in patients
    )
    return {
        "cohort_label": "institutional_deidentified_readiness_sample",
        "record_count": len(patients),
        "real_only": bool(real_only),
        "synthetic_count": int(synthetic_counts.get("synthetic") or 0),
        "real_count": int(synthetic_counts.get("real") or 0),
        "id_policy": "subject_id only; no NSS, name, DOB or local internal identifiers",
        "date_policy": "month precision for clinical dates; DOB excluded",
        "lineage_policy": "fact rows retain source type, source record hash and interoperability target",
    }


def _build_export_quality(
    patients: list[Mapping[str, Any]],
    *,
    fact_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    treatment_rows: list[dict[str, Any]],
    biomarker_rows: list[dict[str, Any]],
    lineage_rows: list[dict[str, Any]],
    data_dictionary: list[dict[str, Any]],
    interop_summary: Mapping[str, Any],
) -> dict[str, Any]:
    payload_for_scan = {
        "fact_rows": fact_rows,
        "event_rows": event_rows,
        "treatment_rows": treatment_rows,
        "biomarker_rows": biomarker_rows,
        "lineage_rows": lineage_rows,
    }
    direct_identifier_keys = sorted(_find_direct_identifier_keys(payload_for_scan))
    exact_phi_hits = _find_exact_phi_hits(payload_for_scan)
    critical_blocks = int(interop_summary.get("critical_block_count") or 0)
    missing_mapping_count = sum(1 for row in data_dictionary if row.get("mapping_status") == "unmapped")
    status = (
        "export_blocked"
        if direct_identifier_keys or exact_phi_hits or critical_blocks or missing_mapping_count
        else "ready_for_local_deidentified_export"
    )
    summary = {
        "cohort_subject_count": len(patients),
        "fact_row_count": len(fact_rows),
        "event_row_count": len(event_rows),
        "treatment_row_count": len(treatment_rows),
        "biomarker_row_count": len(biomarker_rows),
        "lineage_row_count": len(lineage_rows),
        "data_dictionary_field_count": len(data_dictionary),
        "direct_identifier_key_count": len(direct_identifier_keys),
        "exact_phi_hit_count": len(exact_phi_hits),
        "critical_interop_block_count": critical_blocks,
        "unmapped_dictionary_count": missing_mapping_count,
        "export_contract_status": status,
        "next_layer_allowed": status == "ready_for_local_deidentified_export",
    }
    return {
        "summary": summary,
        "direct_identifier_keys": direct_identifier_keys,
        "exact_phi_hits": exact_phi_hits[:10],
        "phi_scan_policy": "recursive key scan plus exact local identifier suppression",
        "interop_summary": dict(interop_summary),
    }


def _build_recommendations(export_quality: Mapping[str, Any]) -> list[dict[str, str]]:
    summary = export_quality.get("summary") or {}
    recommendations: list[dict[str, str]] = []
    if summary.get("direct_identifier_key_count") or summary.get("exact_phi_hit_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Bloquear export por identificadores directos",
                "benefit": "Evita liberar NSS, nombre, DOB o identificadores internos locales en paquetes de investigacion.",
            }
        )
    if summary.get("critical_interop_block_count") or summary.get("unmapped_dictionary_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Cerrar mapa interoperable antes de exportar",
                "benefit": "Cada variable exportada debe tener diccionario y destino semantico defendible.",
            }
        )
    recommendations.append(
        {
            "priority": "P1",
            "title": "Usar este contrato antes de conectores reales",
            "benefit": "Permite validar cohorts, CSV/JSON y publicaciones sin PHI ni recaptura.",
        }
    )
    return recommendations


def _safe_value(normalized: Any, value_json: Any) -> Any:
    candidate = normalized
    if candidate in (None, "") and value_json not in (None, ""):
        try:
            parsed = json.loads(value_json) if isinstance(value_json, str) else value_json
        except Exception:
            parsed = value_json
        if isinstance(parsed, (str, int, float, bool)) or parsed is None:
            candidate = parsed
        else:
            return {"value_kind": type(parsed).__name__, "value_exported": False}
    if isinstance(candidate, str) and DATE_RE.match(candidate.strip()):
        return _month(candidate)
    return candidate


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if DATE_RE.match(text):
        return _month(text)
    return text[:160]


def _month(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 7 and re.match(r"^\d{4}-\d{2}", text):
        return text[:7]
    return ""


def _subject_id(patient_id: Any) -> str:
    return "sub_" + hashlib.sha256(f"prostanet_export_v1:{patient_id}".encode()).hexdigest()[:16]


def _row_ref(prefix: str, row_id: Any) -> str:
    if row_id in (None, ""):
        return ""
    return f"{prefix}_" + hashlib.sha256(f"{prefix}:{row_id}".encode()).hexdigest()[:12]


def _find_direct_identifier_keys(value: Any, *, prefix: str = "") -> set[str]:
    hits: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in DIRECT_IDENTIFIER_KEYS:
                hits.add(f"{prefix}.{key_text}" if prefix else key_text)
            hits.update(_find_direct_identifier_keys(child, prefix=f"{prefix}.{key_text}" if prefix else key_text))
    elif isinstance(value, list):
        for idx, child in enumerate(value[:2000]):
            hits.update(_find_direct_identifier_keys(child, prefix=f"{prefix}[{idx}]"))
    return hits


def _find_exact_phi_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    identifiers = _load_direct_identifier_values()
    if not identifiers:
        return []
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    hits = []
    for kind, raw in identifiers:
        value = str(raw or "").strip()
        if value and value in serialized:
            hits.append({"identifier_type": kind, "match": value})
    return hits


def _load_direct_identifier_values() -> list[tuple[str, str]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT nss, full_name, dob FROM patient_identity").fetchall()
    finally:
        conn.close()
    out: list[tuple[str, str]] = []
    for row in rows:
        item = dict(row)
        for key in ("nss", "full_name", "dob"):
            value = str(item.get(key) or "").strip()
            if value:
                out.append((key, value))
    return out
