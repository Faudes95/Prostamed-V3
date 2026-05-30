"""Prospective pilot adoption and completeness command center.

This read model turns the platform-readiness stack into an operational pilot
dashboard: are patients actually being captured, are critical facts reusable,
and which V2 surface should close each gap. It does not create clinical facts,
orders, model training jobs or external exports.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from statistics import median
from typing import Any, Mapping

from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
    build_nas_pilot_evidence_vault,
)
from prostanet.shared.utc_time import utc_now_iso


PILOT_ADOPTION_COMMAND_CENTER_VERSION = "pilot_adoption_completeness_command_center_v1"

DIRECT_IDENTIFIER_KEYS = {
    "nss",
    "full_name",
    "name",
    "patient_name",
    "dob",
    "date_of_birth",
    "birth_date",
    "patient_id",
    "patient_ref",
    "profile_url",
}

CORE_REQUIREMENTS = (
    {"key": "psa_any", "label": "APE documentado", "family": "biochemical"},
    {"key": "assessment_linked", "label": "Evaluacion clinica vinculada", "family": "workflow"},
    {"key": "clinical_tstage", "label": "Estadio clinico T", "family": "staging"},
)

DIAGNOSTIC_REQUIREMENTS = CORE_REQUIREMENTS + (
    {"key": "prostate_volume_ml", "label": "Volumen prostatico para PSAD", "family": "diagnostic"},
    {"key": "pirads_score", "label": "mpMRI / PI-RADS", "family": "diagnostic"},
    {"key": "biopsy_date", "label": "Estatus/fecha de biopsia", "family": "pathology"},
)

LOCALIZED_REQUIREMENTS = CORE_REQUIREMENTS + (
    {"key": "isup_grade", "label": "ISUP", "family": "pathology"},
    {"key": "gleason_primary", "label": "Gleason primario", "family": "pathology"},
    {"key": "gleason_secondary", "label": "Gleason secundario", "family": "pathology"},
    {"key": "num_cores_positive", "label": "Cilindros positivos", "family": "pathology"},
    {"key": "total_cores_biopsied", "label": "Total de cilindros", "family": "pathology"},
    {"key": "ipss_total", "label": "Funcion urinaria basal", "family": "pros"},
    {"key": "iief5_score", "label": "Funcion sexual basal", "family": "pros"},
)

SYSTEMIC_REQUIREMENTS = CORE_REQUIREMENTS + (
    {"key": "metastatic_stage_resolved", "label": "Contexto metastasico", "family": "metastatic"},
    {"key": "ecog_score", "label": "ECOG basal/actual", "family": "fitness"},
    {"key": "testosterone", "label": "Testosterona/castracion", "family": "biochemical"},
    {"key": "line_of_therapy_number", "label": "Linea terapeutica", "family": "systemic"},
    {"key": "treatment_context", "label": "Tratamiento registrado", "family": "treatment"},
    {"key": "psa_history", "label": "Historial APE longitudinal", "family": "biochemical"},
)

PRECISION_REQUIREMENTS = SYSTEMIC_REQUIREMENTS + (
    {"key": "hrr_status", "label": "HRR", "family": "precision"},
    {"key": "msi_status", "label": "MSI", "family": "precision"},
)

STATE_FAMILIES = {
    "diagnostic_workup": DIAGNOSTIC_REQUIREMENTS,
    "screening": DIAGNOSTIC_REQUIREMENTS,
    "post_negative_biopsy_followup": DIAGNOSTIC_REQUIREMENTS,
    "localized_initial": LOCALIZED_REQUIREMENTS,
    "regional_n1m0": LOCALIZED_REQUIREMENTS,
    "post_prostatectomy": LOCALIZED_REQUIREMENTS,
    "post_radiotherapy_or_local_salvage": LOCALIZED_REQUIREMENTS,
    "recurrence_bcr": LOCALIZED_REQUIREMENTS,
    "m0_crpc": SYSTEMIC_REQUIREMENTS,
    "m1_crpc": PRECISION_REQUIREMENTS,
    "mHSPC": SYSTEMIC_REQUIREMENTS,
    "mCSPC": SYSTEMIC_REQUIREMENTS,
    "oligometastatic": SYSTEMIC_REQUIREMENTS,
    "adt_progression_verification": SYSTEMIC_REQUIREMENTS,
}


def build_pilot_adoption_command_center(
    *,
    scope: str = "summary",
    limit: int = 100,
    real_only: bool = False,
    nas_pilot_evidence_vault: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only adoption/completeness dashboard for the local pilot."""
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 100), 500))
    patient_rows = _load_patient_index(limit=safe_limit, real_only=real_only)
    patient_ids = [int(row["id"]) for row in patient_rows]
    context = _load_context(patient_ids)
    patient_summaries = [
        _build_patient_summary(row, context)
        for row in patient_rows
    ]
    nas_vault = dict(nas_pilot_evidence_vault or build_nas_pilot_evidence_vault(scope="summary", limit=100))
    freeze_summary = _build_freeze_summary()
    summary = _build_summary(patient_summaries, nas_vault=nas_vault, freeze_summary=freeze_summary)
    weekly = _build_weekly_adoption(patient_summaries)
    module_summary = _build_module_summary(context.get("assessments_by_patient") or {})
    capture_gaps = _build_capture_gap_summary(patient_summaries)
    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_fact_ledger_v2_pilot_adoption",
        "version": PILOT_ADOPTION_COMMAND_CENTER_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "clinical_internal_surface": True,
        "deidentified_export_written": False,
        "summary": summary,
        "weekly_adoption": weekly,
        "module_summary": module_summary,
        "capture_gap_summary": capture_gaps,
        "nas_operational_summary": nas_vault.get("summary") or {},
        "research_freeze_summary": freeze_summary,
        "recommended_next_actions": _build_recommended_actions(summary, capture_gaps, nas_vault),
        "summary_no_phi_scan": _scan_for_phi(_summary_only_payload(summary, weekly, module_summary, capture_gaps)),
    }
    if scope_key == "full":
        payload.update(
            {
                "patient_worklist": _build_patient_worklist(patient_summaries),
                "drilldown_policy": {
                    "surface": "patient_profile_v2",
                    "profile_route_template": "/patient_profile/<patient_ref>?v=2",
                    "clinical_identifiers_included": True,
                    "export_policy": "No usar este payload como export externo; para comite use paquetes desidentificados.",
                },
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
            SELECT id, nss, diagnosis_date, created_at,
                   COALESCE(is_synthetic, 1) AS is_synthetic,
                   synthetic_flag_reason, real_patient_consent_signed_at
            FROM patient_identity
            {where}
            ORDER BY COALESCE(created_at, '') DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _load_context(patient_ids: list[int]) -> dict[str, Any]:
    context: dict[str, Any] = {
        "facts_by_patient": defaultdict(dict),
        "biomarkers_by_patient": defaultdict(list),
        "assessments_by_patient": defaultdict(list),
        "events_by_patient": defaultdict(list),
        "treatments_by_patient": defaultdict(list),
        "doses_by_patient": defaultdict(list),
        "prior_history_by_patient": {},
    }
    if not patient_ids:
        return context
    placeholders = ",".join("?" for _ in patient_ids)
    conn = _connect()
    try:
        for row in conn.execute(
            f"""
            SELECT patient_id, fact_key, normalized_value_text, source_date,
                   observed_at, freshness_status, clinician_verified, updated_at
            FROM patient_clinical_facts
            WHERE patient_id IN ({placeholders}) AND COALESCE(is_active, 1) = 1
            ORDER BY patient_id ASC, fact_key ASC, updated_at DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["facts_by_patient"][int(item["patient_id"])].setdefault(str(item["fact_key"]), item)
        for row in conn.execute(
            f"""
            SELECT patient_id, biomarker_type, value, sample_date, created_at
            FROM biomarker_longitudinal
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(sample_date, '') ASC, id ASC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["biomarkers_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT id, patient_id, module_id, state, status, created_at
            FROM clinical_assessments
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(created_at, '') DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["assessments_by_patient"][int(item["patient_id"])].append(item)
        prior_columns = _table_columns(conn, "prior_clinical_history")
        if "patient_id" in prior_columns:
            selected = [
                column for column in (
                    "patient_id",
                    "current_state",
                    "management_track",
                    "latest_assessment_id",
                    "assessment_module",
                    "assessment_state",
                )
                if column in prior_columns
            ]
            for row in conn.execute(
                f"""
                SELECT {', '.join(selected)}
                FROM prior_clinical_history
                WHERE patient_id IN ({placeholders})
                """,
                patient_ids,
            ).fetchall():
                item = dict(row)
                context["prior_history_by_patient"][int(item["patient_id"])] = item
        for row in conn.execute(
            f"""
            SELECT patient_id, event_type, event_date, state_context, management_track, status, created_at
            FROM patient_events
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(event_date, '') DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["events_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT patient_id, drug_scheme, line_of_therapy, line_of_therapy_context,
                   start_date, end_date, outcome
            FROM treatment_history
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(start_date, '') DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["treatments_by_patient"][int(item["patient_id"])].append(item)
        for row in conn.execute(
            f"""
            SELECT patient_id, regimen_code, dose_number_local, dose_number_global,
                   dose_date, estimated_cost_mxn
            FROM treatment_dose_administrations
            WHERE patient_id IN ({placeholders})
            ORDER BY patient_id ASC, COALESCE(dose_date, '') DESC, id DESC
            """,
            patient_ids,
        ).fetchall():
            item = dict(row)
            context["doses_by_patient"][int(item["patient_id"])].append(item)
    finally:
        conn.close()
    return context


def _build_patient_summary(row: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    patient_id = int(row["id"])
    facts = dict((context.get("facts_by_patient") or {}).get(patient_id) or {})
    biomarkers = list((context.get("biomarkers_by_patient") or {}).get(patient_id) or [])
    assessments = list((context.get("assessments_by_patient") or {}).get(patient_id) or [])
    events = list((context.get("events_by_patient") or {}).get(patient_id) or [])
    treatments = list((context.get("treatments_by_patient") or {}).get(patient_id) or [])
    doses = list((context.get("doses_by_patient") or {}).get(patient_id) or [])
    prior_history = dict((context.get("prior_history_by_patient") or {}).get(patient_id) or {})
    state = _effective_state(assessments, prior_history)
    requirements = _requirements_for_state(state)
    missing = [
        requirement
        for requirement in requirements
        if not _requirement_satisfied(requirement["key"], facts, biomarkers, assessments, treatments, doses)
    ]
    satisfied = len(requirements) - len(missing)
    score = round((satisfied / len(requirements)) * 100, 1) if requirements else 0.0
    psa_points = [
        item for item in biomarkers
        if str(item.get("biomarker_type") or "").upper() == "PSA"
    ]
    latest_assessment = assessments[0] if assessments else {}
    latest_event = events[0] if events else {}
    created_at = str(row.get("created_at") or "")
    return {
        "patient_id": patient_id,
        "patient_ref": str(row.get("nss") or ""),
        "subject_id": _subject_id(patient_id),
        "profile_url": f"/patient_profile/{row.get('nss')}?v=2" if row.get("nss") else "",
        "created_at": created_at,
        "created_week": _week_key(created_at),
        "diagnosis_month": _month(row.get("diagnosis_date")),
        "is_synthetic": bool(row.get("is_synthetic")),
        "real_patient_consent_present": bool(row.get("real_patient_consent_signed_at")),
        "effective_state": state,
        "management_track": prior_history.get("management_track") or "",
        "assessment_count": len(assessments),
        "latest_assessment_module": latest_assessment.get("module_id") or prior_history.get("assessment_module") or "",
        "latest_assessment_state": latest_assessment.get("state") or prior_history.get("assessment_state") or "",
        "latest_assessment_at": latest_assessment.get("created_at") or "",
        "fact_count": len(facts),
        "psa_point_count": len(psa_points),
        "has_psa_any": _requirement_satisfied("psa_any", facts, biomarkers, assessments, treatments, doses),
        "has_psa_history": _requirement_satisfied("psa_history", facts, biomarkers, assessments, treatments, doses),
        "treatment_count": len(treatments),
        "dose_count": len(doses),
        "event_count": len(events),
        "latest_event_type": latest_event.get("event_type") or "",
        "latest_event_date": latest_event.get("event_date") or "",
        "required_fact_count": len(requirements),
        "satisfied_fact_count": satisfied,
        "missing_fact_count": len(missing),
        "completeness_pct": score,
        "missing_fields": [
            {
                "key": item["key"],
                "label": item["label"],
                "family": item["family"],
                "capture_route": _capture_route_for_missing(item["key"], row.get("nss"), state),
            }
            for item in missing
        ],
        "registry_ready": score >= 80.0 and len(assessments) > 0 and _requirement_satisfied("psa_any", facts, biomarkers, assessments, treatments, doses),
    }


def _requirements_for_state(state: str) -> tuple[dict[str, str], ...]:
    normalized = str(state or "").strip()
    if normalized in STATE_FAMILIES:
        return STATE_FAMILIES[normalized]
    lowered = normalized.lower()
    if "crpc" in lowered or "mhspc" in lowered or "mcspc" in lowered or "metast" in lowered:
        return SYSTEMIC_REQUIREMENTS
    if "diagnostic" in lowered or "screen" in lowered or "biopsy" in lowered:
        return DIAGNOSTIC_REQUIREMENTS
    if "localized" in lowered or "prostatectomy" in lowered or "radiotherapy" in lowered or "bcr" in lowered:
        return LOCALIZED_REQUIREMENTS
    return CORE_REQUIREMENTS


def _requirement_satisfied(
    key: str,
    facts: Mapping[str, Any],
    biomarkers: list[Mapping[str, Any]],
    assessments: list[Mapping[str, Any]],
    treatments: list[Mapping[str, Any]],
    doses: list[Mapping[str, Any]],
) -> bool:
    if key == "assessment_linked":
        return bool(assessments)
    if key == "psa_any":
        return any(item in facts for item in ("baseline_psa", "current_psa")) or any(
            str(item.get("biomarker_type") or "").upper() == "PSA" for item in biomarkers
        )
    if key == "psa_history":
        return sum(1 for item in biomarkers if str(item.get("biomarker_type") or "").upper() == "PSA") >= 2
    if key == "treatment_context":
        return bool(treatments)
    if key == "treatment_doses":
        return bool(doses)
    return key in facts and str((facts.get(key) or {}).get("normalized_value_text") or "").strip() != ""


def _effective_state(assessments: list[Mapping[str, Any]], prior_history: Mapping[str, Any]) -> str:
    if assessments:
        return str(assessments[0].get("state") or assessments[0].get("module_id") or "")
    return str(
        prior_history.get("current_state")
        or prior_history.get("assessment_state")
        or prior_history.get("assessment_module")
        or "unknown"
    )


def _build_summary(
    rows: list[Mapping[str, Any]],
    *,
    nas_vault: Mapping[str, Any],
    freeze_summary: Mapping[str, Any],
) -> dict[str, Any]:
    patient_count = len(rows)
    real_count = sum(1 for row in rows if not row.get("is_synthetic"))
    synthetic_count = patient_count - real_count
    completeness_values = [float(row.get("completeness_pct") or 0) for row in rows]
    fact_counts = [int(row.get("fact_count") or 0) for row in rows]
    psa_counts = [int(row.get("psa_point_count") or 0) for row in rows]
    assessment_count = sum(1 for row in rows if int(row.get("assessment_count") or 0) > 0)
    psa_any_count = sum(1 for row in rows if row.get("has_psa_any"))
    psa_history_count = sum(1 for row in rows if row.get("has_psa_history"))
    treatment_count = sum(1 for row in rows if int(row.get("treatment_count") or 0) > 0)
    registry_ready_count = sum(1 for row in rows if row.get("registry_ready"))
    high_priority_gap_count = sum(1 for row in rows if float(row.get("completeness_pct") or 0) < 60 or not row.get("has_psa_any"))
    nas_summary = nas_vault.get("summary") or {}
    avg_completeness = round(sum(completeness_values) / patient_count, 1) if patient_count else 0.0
    status = (
        "no_patients_captured" if not patient_count
        else "pilot_adoption_ready" if avg_completeness >= 80 and high_priority_gap_count == 0 and int(nas_summary.get("block_count") or 0) == 0
        else "needs_capture_hardening"
    )
    return {
        "patient_count": patient_count,
        "real_patient_count": real_count,
        "synthetic_patient_count": synthetic_count,
        "assessment_linked_patient_count": assessment_count,
        "assessment_linkage_pct": _pct(assessment_count, patient_count),
        "psa_any_patient_count": psa_any_count,
        "psa_any_coverage_pct": _pct(psa_any_count, patient_count),
        "psa_history_patient_count": psa_history_count,
        "psa_history_coverage_pct": _pct(psa_history_count, patient_count),
        "treatment_context_patient_count": treatment_count,
        "treatment_context_coverage_pct": _pct(treatment_count, patient_count),
        "registry_ready_patient_count": registry_ready_count,
        "registry_ready_pct": _pct(registry_ready_count, patient_count),
        "median_facts_per_patient": _median_or_zero(fact_counts),
        "median_psa_points_per_patient": _median_or_zero(psa_counts),
        "mean_completeness_pct": avg_completeness,
        "high_priority_gap_count": high_priority_gap_count,
        "nas_operational_completion_pct": nas_summary.get("completion_pct") or 0,
        "nas_operational_watch_count": nas_summary.get("watch_count") or 0,
        "freeze_count": freeze_summary.get("freeze_count") or 0,
        "download_ready_freeze_count": freeze_summary.get("download_ready_count") or 0,
        "command_status": status,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
    }


def _build_weekly_adoption(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    today = date.today()
    week_keys = [f"{(today - timedelta(days=7 * offset)).isocalendar().year}-W{(today - timedelta(days=7 * offset)).isocalendar().week:02d}" for offset in range(7, -1, -1)]
    grouped: dict[str, list[Mapping[str, Any]]] = {key: [] for key in week_keys}
    for row in rows:
        week = str(row.get("created_week") or "")
        if week in grouped:
            grouped[week].append(row)
    out = []
    for week in week_keys:
        items = grouped.get(week) or []
        out.append(
            {
                "week": week,
                "patient_count": len(items),
                "registry_ready_count": sum(1 for item in items if item.get("registry_ready")),
                "mean_completeness_pct": round(sum(float(item.get("completeness_pct") or 0) for item in items) / len(items), 1) if items else 0.0,
                "median_facts_per_patient": _median_or_zero([int(item.get("fact_count") or 0) for item in items]),
            }
        )
    return out


def _build_module_summary(assessments_by_patient: Mapping[int, list[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str]] = Counter()
    for assessments in assessments_by_patient.values():
        for assessment in assessments:
            counter[(str(assessment.get("module_id") or ""), str(assessment.get("state") or ""))] += 1
    rows = [
        {
            "module_id": module_id,
            "state": state,
            "assessment_count": count,
        }
        for (module_id, state), count in counter.most_common(20)
    ]
    return rows


def _build_capture_gap_summary(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str, str]] = Counter()
    examples: dict[tuple[str, str, str], str] = {}
    for row in rows:
        for missing in row.get("missing_fields") or []:
            key = (str(missing.get("key") or ""), str(missing.get("label") or ""), str(missing.get("family") or ""))
            counter[key] += 1
            examples.setdefault(key, _generic_capture_route(str(missing.get("key") or "")))
    return [
        {
            "field_key": key,
            "label": label,
            "family": family,
            "patient_count": count,
            "capture_route": examples.get((key, label, family), ""),
        }
        for (key, label, family), count in counter.most_common(18)
    ]


def _build_patient_worklist(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda item: (
            0 if not item.get("has_psa_any") else 1,
            float(item.get("completeness_pct") or 0),
            -int(item.get("missing_fact_count") or 0),
        ),
    )
    return [
        {
            "patient_ref": row.get("patient_ref"),
            "subject_id": row.get("subject_id"),
            "profile_url": row.get("profile_url"),
            "effective_state": row.get("effective_state"),
            "latest_assessment_module": row.get("latest_assessment_module"),
            "completeness_pct": row.get("completeness_pct"),
            "fact_count": row.get("fact_count"),
            "psa_point_count": row.get("psa_point_count"),
            "treatment_count": row.get("treatment_count"),
            "event_count": row.get("event_count"),
            "missing_fact_count": row.get("missing_fact_count"),
            "missing_fields": row.get("missing_fields")[:6],
            "registry_ready": row.get("registry_ready"),
        }
        for row in sorted_rows[:40]
    ]


def _build_freeze_summary() -> dict[str, Any]:
    try:
        import tracking_db

        freezes = tracking_db.list_research_cohort_freezes(limit=50)
    except Exception:
        freezes = []
    return {
        "freeze_count": len(freezes),
        "download_ready_count": sum(1 for item in freezes if item.get("download_ready", True)),
        "latest_freeze_key": (freezes[0] or {}).get("freeze_key") if freezes else "",
    }


def _build_recommended_actions(
    summary: Mapping[str, Any],
    capture_gaps: list[Mapping[str, Any]],
    nas_vault: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if int(summary.get("patient_count") or 0) == 0:
        actions.append(
            {
                "priority": "high",
                "title": "Iniciar captura prospectiva",
                "action": "Registrar los primeros pacientes desde Clinical Hub -> intake V2 para medir adopcion real.",
                "route": "/clinical-hub",
            }
        )
    if float(summary.get("psa_history_coverage_pct") or 0) < 80:
        actions.append(
            {
                "priority": "high",
                "title": "Cerrar historial APE",
                "action": "Usar captura longitudinal para convertir APE aislado en serie temporal reutilizable.",
                "route": "/patients",
            }
        )
    if capture_gaps:
        top = capture_gaps[0]
        actions.append(
            {
                "priority": "medium",
                "title": f"Completar {top.get('label')}",
                "action": f"{top.get('patient_count')} pacientes requieren este dato para investigacion/auditoria.",
                "route": top.get("capture_route") or "/patients",
            }
        )
    nas_summary = nas_vault.get("summary") or {}
    if int(nas_summary.get("watch_count") or 0) > 0:
        actions.append(
            {
                "priority": "medium",
                "title": "Cerrar watches operacionales NAS",
                "action": "Verificar backup/restore, roles, consentimiento, capacitacion, incidente y protocolo en el vault.",
                "route": "/api/platform-readiness/nas-pilot-evidence-vault?scope=full",
            }
        )
    return actions[:5]


def _capture_route_for_missing(key: str, patient_ref: Any, state: str) -> str:
    ref = str(patient_ref or "")
    if key in {"psa_any", "psa_history", "testosterone"} and ref:
        return f"/longitudinal-capture/{ref}?decision_lane={state or 'pilot'}&decision_field={key}"
    if key in {"treatment_context", "treatment_doses"} and ref:
        return f"/patient_profile/{ref}?v=2#treatment-course"
    if ref:
        return f"/wizard/{state or 'localized_initial'}?patient_ref={ref}&readiness_lane=pilot_adoption&decision_field={key}"
    return "/patients"


def _generic_capture_route(key: str) -> str:
    if key in {"psa_any", "psa_history", "testosterone"}:
        return "/patients"
    if key in {"treatment_context", "treatment_doses"}:
        return "/population/treatment-value-registry"
    if key in {"pirads_score", "prostate_volume_ml", "biopsy_date"}:
        return "/wizard/diagnostic_workup"
    return "/clinical-hub"


def _summary_only_payload(
    summary: Mapping[str, Any],
    weekly: list[Mapping[str, Any]],
    module_summary: list[Mapping[str, Any]],
    gaps: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "weekly_adoption": weekly,
        "module_summary": module_summary,
        "capture_gap_summary": gaps,
    }


def _scan_for_phi(value: Any) -> dict[str, Any]:
    hits: list[str] = []
    direct_keys: list[str] = []

    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text.lower() in DIRECT_IDENTIFIER_KEYS:
                    direct_keys.append(child_path)
                walk(child, child_path)
            return
        if isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")
            return
        text = str(node or "")
        if "/patient_profile/" in text:
            hits.append(path or "value")
        if not _is_hash_like_path(path) and re.search(r"\b\d{10,11}\b", text):
            hits.append(path or "value")

    walk(value)
    return {
        "direct_identifier_key_count": len(set(direct_keys)),
        "exact_phi_hit_count": len(set(hits)),
        "direct_identifier_keys": sorted(set(direct_keys)),
        "exact_phi_hits": sorted(set(hits)),
        "no_phi_status": "pass" if not direct_keys and not hits else "block",
    }


def _table_columns(conn: Any, table_name: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()


def _subject_id(patient_id: int) -> str:
    digest = hashlib.sha256(f"prostanet-pilot-adoption:{int(patient_id)}".encode("utf-8")).hexdigest()
    return f"sub_{digest[:16]}"


def _week_key(value: Any) -> str:
    parsed = _parse_date(value)
    if not parsed:
        return ""
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month(value: Any) -> str:
    text = str(value or "")[:7]
    return text if re.match(r"^\d{4}-\d{2}$", text) else ""


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _pct(numerator: int, denominator: int) -> float:
    return round((int(numerator) / int(denominator)) * 100, 1) if denominator else 0.0


def _median_or_zero(values: list[int]) -> float:
    return float(median(values)) if values else 0.0


def _is_hash_like_path(path: str) -> bool:
    lowered = str(path or "").lower()
    return any(token in lowered for token in ("subject_id", "sha256", "hash", "checksum"))


__all__ = ["build_pilot_adoption_command_center"]
