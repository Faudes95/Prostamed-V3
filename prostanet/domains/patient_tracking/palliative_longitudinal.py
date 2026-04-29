from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from prostanet.domains.palliative_pathway.service import PalliativePathwayService
from prostanet.domains.patient_tracking.clinical_list_normalization import (
    normalize_followup_entries,
    normalize_imaging_entries,
    normalize_medication_entries,
)
from prostanet.domains.patient_tracking.terminal_care_pathway import TerminalCarePathway


ADVANCED_PALLIATIVE_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
    "recurrence_bcr",
}

PALLIATIVE_TRACKS = {
    "concurrent_palliative_care",
    "supportive_only",
    "hospice_pathway",
}

PALLIATIVE_ALIAS_TRACKS = PALLIATIVE_TRACKS | {"palliative_overlay"}

PALLIATIVE_REQUIRED_FIELDS = [
    "pain",
    "bpi_worst_pain",
    "bone_pain",
    "neuropathic_pain",
    "current_analgesics",
    "opioid_use",
    "breakthrough_pain",
    "bowel_regimen_started",
    "fatigue_score",
    "dyspnea_score",
    "nausea_score",
    "constipation_score",
    "appetite_loss",
    "insomnia_score",
    "depression_score",
    "anxiety_score",
    "ecog",
    "ecog_delta_3mo",
    "weight_loss_6m_kg",
    "albumin",
    "refractory_pain",
    "visceral_crisis",
    "spinal_cord_compression",
    "epidural_compression",
    "pathological_fracture_risk",
    "obstructive_uropathy",
    "hematuria_severe",
    "brain_metastasis",
    "advance_directive_documented",
    "goals_of_care_discussed",
    "healthcare_surrogate_designated",
    "patient_prefers_comfort",
    "prior_systemic_lines",
]

PALLIATIVE_GOALS_FIELDS = [
    "advance_directive_documented",
    "goals_of_care_discussed",
    "healthcare_surrogate_designated",
    "patient_prefers_comfort",
]

PALLIATIVE_URGENT_FIELDS = [
    "spinal_cord_compression",
    "epidural_compression",
    "pathological_fracture_risk",
    "obstructive_uropathy",
    "hematuria_severe",
    "brain_metastasis",
    "visceral_crisis",
]

PALLIATIVE_LAB_FIELDS = ["albumin"]

PALLIATIVE_FOLLOWUP_FIELDS = [
    field for field in PALLIATIVE_REQUIRED_FIELDS if field not in {"prior_systemic_lines"}
]

SYMPTOM_CLUSTER_MAP = {
    "pain_cluster": ["pain", "bpi_worst_pain", "bone_pain", "neuropathic_pain", "opioid_use", "breakthrough_pain"],
    "constitutional_cluster": ["fatigue_score", "appetite_loss", "weight_loss_6m_kg", "albumin"],
    "respiratory_gi_cluster": ["dyspnea_score", "nausea_score", "constipation_score", "insomnia_score"],
    "psychosocial_cluster": ["depression_score", "anxiety_score", "goals_of_care_discussed", "healthcare_surrogate_designated"],
    "oncologic_emergency_cluster": PALLIATIVE_URGENT_FIELDS,
}

TRACK_LABELS = {
    "observe": "Vigilancia paliativa de fondo",
    "concurrent_palliative_care": "Cuidados paliativos concurrentes",
    "supportive_only": "Soporte exclusivo",
    "hospice_pathway": "Ruta hospice",
}

TRIGGER_LABELS = {
    "observe": "Sin activacion paliativa dominante",
    "concurrent_support": "Integrar soporte paliativo concurrente",
    "intensify_symptom_control": "Intensificar control sintomatico",
    "urgent_local_palliation": "Activar paliacion local urgente",
    "redirect_supportive_only": "Redirigir a soporte exclusivo",
    "hospice_candidate": "Activar ruta hospice",
}


def _is_present(value: Any) -> bool:
    return value not in (
        None,
        "",
        [],
        {},
        "No aplica",
        "No documentado",
        "No realizado",
        "Desconocido",
        "Desconocida",
        "unknown",
        "UNKNOWN",
    )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "si", "on", "positivo", "pos", "cronico", "chronic"}


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(items: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in items if _is_present(item)))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if not _is_present(value):
        return []
    return [value]


def _parse_date(value: Any) -> date | None:
    if not _is_present(value):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _latest_visit_date(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> date | None:
    candidates: list[date] = []
    for followup in list(patient.get("follow_ups") or []):
        parsed = _parse_date(followup.get("visit_date"))
        if parsed:
            candidates.append(parsed)
    for visit in list(patient.get("stage_visits") or []):
        parsed = _parse_date(visit.get("visit_date") or visit.get("recorded_at") or visit.get("created_at"))
        if parsed:
            candidates.append(parsed)
    parsed_assessment = _parse_date((latest_assessment or {}).get("assessment_date"))
    if parsed_assessment:
        candidates.append(parsed_assessment)
    return max(candidates) if candidates else None


def _lab_reference_date(merged: dict[str, Any], latest_visit_date: date | None) -> date | None:
    return (
        _parse_date(merged.get("lft_date"))
        or _parse_date(merged.get("laboratory_date"))
        or _parse_date(merged.get("lab_date"))
        or latest_visit_date
    )


def _merge_patient_context(
    patient: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    latest_followup = (list(patient.get("follow_ups") or []) or [{}])[-1]
    latest_stage_visit = (list(patient.get("stage_visits") or []) or [{}])[-1]
    latest_stage_payload = {}
    if isinstance(latest_stage_visit.get("visit_bundle"), dict):
        latest_stage_payload = dict((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {})
    for source in (
        patient.get("identity") or {},
        patient.get("baseline") or {},
        patient.get("prior_history") or {},
        latest_followup or {},
        latest_stage_payload,
        dict((latest_assessment or {}).get("input_snapshot") or {}),
        field_values or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value):
                merged[key] = value
    if _is_present(merged.get("pain")) and not _is_present(merged.get("pain_score")):
        merged["pain_score"] = merged.get("pain")
    if _is_present(merged.get("ecog")) and not _is_present(merged.get("ecog_score")):
        merged["ecog_score"] = merged.get("ecog")
    if _is_present(merged.get("weight_loss_6m_kg")) and not _is_present(merged.get("weight_loss_6m_pct")):
        try:
            current_weight = float(merged.get("weight_kg") or 0)
            loss_kg = float(merged.get("weight_loss_6m_kg") or 0)
            prior_weight = current_weight + loss_kg
            if prior_weight > 0 and loss_kg >= 0:
                merged["weight_loss_6m_pct"] = round((loss_kg / prior_weight) * 100, 1)
        except (TypeError, ValueError):
            pass
    if _is_present(merged.get("weight_loss_6m_pct")) and not _is_present(merged.get("weight_loss_pct")):
        merged["weight_loss_pct"] = merged.get("weight_loss_6m_pct")
    if _is_present(merged.get("prior_systemic_lines")) and not _is_present(merged.get("treatment_lines_exhausted")):
        merged["treatment_lines_exhausted"] = merged.get("prior_systemic_lines")
    return merged


def _field_present(field: str, merged: dict[str, Any]) -> bool:
    aliases = {
        "pain": ["pain", "pain_score", "bpi_worst_pain"],
        "bpi_worst_pain": ["bpi_worst_pain", "pain_score", "pain"],
        "ecog": ["ecog", "ecog_score"],
        "weight_loss_6m_kg": ["weight_loss_6m_kg", "weight_loss_6m_pct", "weight_loss_pct", "weight_loss"],
        "weight_loss_6m_pct": ["weight_loss_6m_pct", "weight_loss_pct", "weight_loss"],
        "prior_systemic_lines": ["prior_systemic_lines", "treatment_lines_exhausted", "prior_lines"],
    }
    candidates = aliases.get(field, [field])
    return any(_is_present(merged.get(name)) for name in candidates)


def _field_stale(field: str, merged: dict[str, Any], *, latest_visit_date: date | None = None, lab_reference_date: date | None = None) -> bool:
    today = date.today()
    if field in PALLIATIVE_LAB_FIELDS:
        reference = lab_reference_date
        return bool(reference and (today - reference).days > 14)
    reference = latest_visit_date
    return bool(reference and (today - reference).days > 30)


def _flatten_interventions(active_interventions: dict[str, list[dict[str, Any]]], pain_assessment: dict[str, Any], rt_candidates: list[dict[str, Any]]) -> list[str]:
    interventions: list[str] = []
    for items in active_interventions.values():
        for item in items:
            text = str(item.get("intervention") or item.get("indication") or "").strip()
            if text:
                interventions.append(text)
    for rec in list(pain_assessment.get("recommendations") or []):
        text = str(rec).strip()
        if text:
            interventions.append(text)
    for item in rt_candidates:
        indication = str(item.get("indication") or "").strip()
        regimen = str(item.get("regimen") or "").strip()
        if indication and regimen:
            interventions.append(f"{indication}: {regimen}")
        elif indication:
            interventions.append(indication)
    return _dedupe(interventions)


def _support_service_checks(acp: dict[str, Any], hospice: dict[str, Any], palliative: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": "advance_directive_documented",
            "label": "Voluntades anticipadas",
            "status": "complete" if _coerce_bool(acp.get("advance_directive_documented")) else "missing",
        },
        {
            "key": "goals_of_care_discussed",
            "label": "Objetivos de cuidado",
            "status": "complete" if _coerce_bool(acp.get("goals_of_care_discussed")) else "missing",
        },
        {
            "key": "healthcare_surrogate_designated",
            "label": "Representante de salud",
            "status": "complete" if _coerce_bool(acp.get("healthcare_surrogate_designated")) else "missing",
        },
        {
            "key": "hospice_eligibility",
            "label": "Elegibilidad hospice",
            "status": "positive" if _coerce_bool(hospice.get("is_eligible")) else "negative",
            "detail": str(hospice.get("recommendation") or ""),
        },
        {
            "key": "concurrent_palliative_integration",
            "label": "Integracion paliativa",
            "status": str((palliative.get("concurrent_palliative_care") or {}).get("integration_level") or "standard"),
        },
    ]


def build_palliative_transition_bundle(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = str(state or "").strip()
    applicable = state in ADVANCED_PALLIATIVE_STATES
    merged = _merge_patient_context(patient, latest_assessment=latest_assessment, field_values=field_values)
    latest_visit_date = _latest_visit_date(patient, latest_assessment)
    if not applicable:
        return {
            "available": False,
            "care_mode": "observe",
            "care_mode_label": TRACK_LABELS["observe"],
            "trigger_status": "observe",
            "trigger_status_label": TRIGGER_LABELS["observe"],
            "trigger_reasons": [],
            "acute_palliative_alerts": [],
            "goals_of_care_status": "not_applicable",
            "hospice_eligibility": {},
            "recommended_referrals": [],
            "recommended_interventions": [],
            "care_goal": "",
            "supportive_priority": "background",
            "recommended_management_track": management_track if management_track not in PALLIATIVE_ALIAS_TRACKS else "concurrent_palliative_care",
            "track_should_override": False,
            "symptom_burden_profile": {},
            "advance_care_planning_status": {},
            "bone_event_risk": {},
            "spinal_cord_compression_risk": False,
            "palliative_rt_candidates": [],
            "required_visit_fields": [],
            "missing_inputs": [],
            "stale_inputs": [],
            "last_palliative_review_date": latest_visit_date.isoformat() if latest_visit_date else "",
        }

    context_patient = deepcopy(patient)
    context_patient.update(merged)
    context_patient["current_medications"] = normalize_medication_entries(
        context_patient.get("current_medications") or context_patient.get("medications") or []
    )
    context_patient["medications"] = list(context_patient.get("current_medications") or [])
    context_patient["imaging_studies"] = normalize_imaging_entries(
        context_patient.get("imaging_studies") or context_patient.get("imaging") or []
    )
    context_patient["follow_up_visits"] = normalize_followup_entries(
        context_patient.get("follow_up_visits") or context_patient.get("follow_ups") or []
    )
    palliative_assessment = PalliativePathwayService.full_assessment(context_patient).to_dict()
    terminal_assessment = TerminalCarePathway.assess(context_patient)

    symptom_burden = dict(terminal_assessment.get("symptom_burden") or {})
    acp = dict(palliative_assessment.get("advance_care_planning") or {})
    hospice = dict(terminal_assessment.get("hospice_eligibility") or {})
    rt_candidates = list(palliative_assessment.get("palliative_rt_indications") or [])
    emergency_alerts = _dedupe(list(terminal_assessment.get("emergency_alerts") or []))
    transition_criteria = list(palliative_assessment.get("transition_criteria_met") or [])
    concurrent = dict(palliative_assessment.get("concurrent_palliative_care") or {})
    pain_assessment = dict(palliative_assessment.get("pain_assessment") or {})
    active_interventions = dict(terminal_assessment.get("active_interventions") or {})

    severe_symptom_burden = (
        (_safe_int(merged.get("pain_score") or merged.get("pain")) or 0) >= 7
        or (_safe_int(merged.get("bpi_worst_pain")) or 0) >= 7
        or any(item.get("severity") == "severe" for item in list((palliative_assessment.get("symptom_burden") or {}).get("symptom_details") or []))
    )
    urgent_local_palliation = bool(
        emergency_alerts
        or any(_coerce_bool(merged.get(field)) for field in PALLIATIVE_URGENT_FIELDS)
    )
    hospice_candidate = _coerce_bool(hospice.get("is_eligible"))
    comfort_preference = _coerce_bool(merged.get("patient_prefers_comfort") or merged.get("preference_comfort_over_treatment"))
    should_transition_to_bsc = _coerce_bool(palliative_assessment.get("should_transition_to_bsc"))
    concurrent_level = str(concurrent.get("integration_level") or "standard")

    care_mode = "observe"
    trigger_status = "observe"
    supportive_priority = "background"
    reasons: list[str] = []
    track_should_override = False

    if urgent_local_palliation:
        care_mode = "concurrent_palliative_care"
        trigger_status = "urgent_local_palliation"
        supportive_priority = "dominant"
        reasons = emergency_alerts or [item.get("indication") for item in rt_candidates if _is_present(item.get("indication"))]
        track_should_override = True
    elif hospice_candidate:
        care_mode = "hospice_pathway"
        trigger_status = "hospice_candidate"
        supportive_priority = "dominant"
        reasons = list(hospice.get("criteria_met") or []) or [str(hospice.get("recommendation") or "").strip()]
        track_should_override = True
    elif comfort_preference or should_transition_to_bsc:
        care_mode = "supportive_only"
        trigger_status = "redirect_supportive_only"
        supportive_priority = "dominant"
        reasons = transition_criteria or [str(hospice.get("recommendation") or "").strip() or "Preferencia explicita por confort."]
        track_should_override = True
    elif concurrent_level in {"enhanced", "full"} or severe_symptom_burden or _coerce_bool(merged.get("refractory_pain")) or (_safe_int(merged.get("ecog") or merged.get("ecog_score")) or 0) >= 2:
        care_mode = "concurrent_palliative_care"
        trigger_status = "intensify_symptom_control" if severe_symptom_burden or _coerce_bool(merged.get("refractory_pain")) else "concurrent_support"
        supportive_priority = "shared"
        reasons = transition_criteria or list(concurrent.get("triggers") or []) or ["Carga sintomatica o funcional suficiente para integrar paliativos de forma estructurada."]
        track_should_override = True

    monitoring_fields = list(PALLIATIVE_FOLLOWUP_FIELDS)
    if care_mode in {"supportive_only", "hospice_pathway"}:
        monitoring_fields = _dedupe(monitoring_fields + PALLIATIVE_GOALS_FIELDS)
    if trigger_status == "urgent_local_palliation":
        monitoring_fields = _dedupe(monitoring_fields + PALLIATIVE_URGENT_FIELDS)
    missing_inputs = [field for field in monitoring_fields if not _field_present(field, merged)]
    stale_inputs = [
        field
        for field in monitoring_fields
        if field not in missing_inputs and _field_stale(field, merged, latest_visit_date=latest_visit_date, lab_reference_date=_lab_reference_date(merged, latest_visit_date))
    ]
    recommended_track = care_mode if care_mode != "observe" else ("concurrent_palliative_care" if management_track == "palliative_overlay" else management_track)
    bone_event_risk = {
        "risk_level": (
            "high"
            if _coerce_bool(merged.get("spinal_cord_compression"))
            or _coerce_bool(merged.get("epidural_compression"))
            or _coerce_bool(merged.get("pathological_fracture_risk"))
            else "elevated"
            if _coerce_bool(merged.get("bone_pain"))
            else "background"
        ),
        "drivers": _dedupe(
            [
                "Compresion medular" if _coerce_bool(merged.get("spinal_cord_compression")) else "",
                "Fractura patologica inminente" if _coerce_bool(merged.get("pathological_fracture_risk")) else "",
                "Dolor oseo" if _coerce_bool(merged.get("bone_pain")) else "",
            ]
        ),
    }
    goals_status = "complete" if str(acp.get("completeness_score") or "") == "3/3" else "needs_conversation"
    if care_mode == "observe" and not any(_coerce_bool(acp.get(key)) for key in ["advance_directive_documented", "goals_of_care_discussed", "healthcare_surrogate_designated"]):
        goals_status = "not_started"

    return {
        "available": True,
        "care_mode": care_mode,
        "care_mode_label": TRACK_LABELS.get(care_mode, care_mode),
        "trigger_status": trigger_status,
        "trigger_status_label": TRIGGER_LABELS.get(trigger_status, trigger_status),
        "trigger_reasons": _dedupe([str(item).strip() for item in reasons if _is_present(item)]),
        "acute_palliative_alerts": emergency_alerts,
        "goals_of_care_status": goals_status,
        "hospice_eligibility": hospice,
        "recommended_referrals": _dedupe(list(terminal_assessment.get("mdt_referrals") or [])),
        "recommended_interventions": _flatten_interventions(active_interventions, pain_assessment, rt_candidates),
        "care_goal": str(terminal_assessment.get("goals_of_care") or ""),
        "supportive_priority": supportive_priority,
        "recommended_management_track": recommended_track,
        "track_should_override": track_should_override,
        "symptom_burden_profile": {
            "terminal": symptom_burden,
            "palliative": dict(palliative_assessment.get("symptom_burden") or {}),
            "pain_assessment": pain_assessment,
        },
        "advance_care_planning_status": acp,
        "bone_event_risk": bone_event_risk,
        "spinal_cord_compression_risk": bool(symptom_burden.get("spinal_cord_compression_risk")),
        "palliative_rt_candidates": rt_candidates,
        "required_visit_fields": monitoring_fields,
        "missing_inputs": missing_inputs,
        "stale_inputs": stale_inputs,
        "support_service_checks": _support_service_checks(acp, hospice, palliative_assessment),
        "last_palliative_review_date": latest_visit_date.isoformat() if latest_visit_date else "",
    }


def build_palliative_monitoring_package(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
    transition_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(
        transition_bundle
        or build_palliative_transition_bundle(
            patient,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=field_values,
        )
    )
    recommended_cadence = "cada 30 dias"
    if bundle.get("trigger_status") == "urgent_local_palliation":
        recommended_cadence = "cada 48-72 horas hasta resolver urgencia"
    elif bundle.get("care_mode") == "hospice_pathway":
        recommended_cadence = "cada 7 dias o antes segun sintomas"
    elif bundle.get("care_mode") in {"supportive_only", "concurrent_palliative_care"}:
        recommended_cadence = "cada 14 dias o antes segun carga sintomatica"
    symptom_clusters = [
        {
            "key": key,
            "label": key.replace("_", " "),
            "fields": fields,
        }
        for key, fields in SYMPTOM_CLUSTER_MAP.items()
    ]
    return {
        "family_code": "palliative_support_family",
        "family_label": "Soporte paliativo longitudinal",
        "active_regimen_code": str(bundle.get("care_mode") or ""),
        "response_metrics": ["pain", "bpi_worst_pain", "fatigue_score", "dyspnea_score", "appetite_loss", "ecog"],
        "safety_metrics": ["opioid_use", "breakthrough_pain", "bowel_regimen_started", "albumin", "weight_loss_6m_kg"],
        "hold_rules": list(bundle.get("acute_palliative_alerts") or []),
        "switch_rules": list(bundle.get("trigger_reasons") or []),
        "required_visit_fields": list(bundle.get("required_visit_fields") or []),
        "missing_inputs": list(bundle.get("missing_inputs") or []),
        "stale_inputs": list(bundle.get("stale_inputs") or []),
        "monitoring_focus": str(bundle.get("trigger_status_label") or bundle.get("care_mode_label") or "Seguimiento paliativo"),
        "recommended_cadence": recommended_cadence,
        "symptom_clusters": symptom_clusters,
        "oncologic_emergency_checks": [
            {
                "field": field,
                "active": field in set(bundle.get("required_visit_fields") or []) and field in PALLIATIVE_URGENT_FIELDS,
            }
            for field in PALLIATIVE_URGENT_FIELDS
        ],
        "support_service_checks": list(bundle.get("support_service_checks") or []),
    }


def resolve_canonical_palliative_track(
    *,
    patient: dict[str, Any],
    state: str,
    current_track: str,
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> str:
    bundle = build_palliative_transition_bundle(
        patient,
        state=state,
        management_track=current_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
    )
    recommended_track = str(bundle.get("recommended_management_track") or "").strip()
    if recommended_track in PALLIATIVE_TRACKS and bundle.get("track_should_override"):
        return recommended_track
    if current_track == "palliative_overlay":
        return "concurrent_palliative_care"
    return current_track


__all__ = [
    "ADVANCED_PALLIATIVE_STATES",
    "PALLIATIVE_ALIAS_TRACKS",
    "PALLIATIVE_GOALS_FIELDS",
    "PALLIATIVE_REQUIRED_FIELDS",
    "PALLIATIVE_TRACKS",
    "build_palliative_monitoring_package",
    "build_palliative_transition_bundle",
    "resolve_canonical_palliative_track",
]
