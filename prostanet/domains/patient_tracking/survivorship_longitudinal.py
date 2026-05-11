from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.adt_side_effects import ADTSideEffectService
from prostanet.domains.patient_tracking.clinical_list_normalization import (
    normalize_followup_entries,
)
from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
from prostanet.domains.patient_tracking.survivorship import SurvivorshipCarePlan


SURVIVORSHIP_TRACK_LABELS = {
    "survivorship_followup": "Seguimiento de survivorship",
    "toxicity_recovery": "Recuperación de toxicidad",
    "late_effect_intervention": "Intervención de secuelas tardías",
}

SURVIVORSHIP_TRIGGER_LABELS = {
    "observe": "Seguimiento de baja intensidad",
    "monitor_recovery": "Monitorear recuperación funcional",
    "intensify_toxicity_management": "Intensificar manejo de toxicidad",
    "refer_rehabilitation": "Referir rehabilitación",
    "refer_specialist": "Referir especialista",
    "reenter_oncologic_decision": "Reabrir decisión oncológica",
}

SURVIVORSHIP_FIELD_BLOCKS = {
    "post_prostatectomy": {
        "title": "Secuelas post-prostatectomía",
        "fields": [
            "ipss_score",
            "pad_count",
            "continence_status",
            "leakage_bother",
            "iief5_score",
            "nerve_sparing",
            "pelvic_floor_pt_started",
        ],
    },
    "post_radiotherapy": {
        "title": "Toxicidad tardía post-radioterapia",
        "fields": [
            "gu_toxicity_grade",
            "gi_toxicity_grade",
            "rectal_toxicity_grade",
            "hematuria",
            "dysuria",
            "radiation_cystitis",
            "proctitis",
            "late_toxicity_json",
        ],
    },
    "adt": {
        "title": "Cardiometabólico y hueso bajo ADT",
        "fields": [
            "systolic_bp",
            "diastolic_bp",
            "hba1c",
            "total_cholesterol",
            "hdl_cholesterol",
            "triglycerides",
            "waist_circumference_cm",
            "dxa_t_score_lumbar",
            "dxa_t_score_hip",
            "vitamin_d_level",
            "calcium_level",
            "fall_risk",
            "cognitive_risk",
        ],
    },
    "systemic_recovery": {
        "title": "Recuperación post-sistémicos",
        "fields": [
            "neuropathy_grade",
            "fatigue_score",
            "hemoglobin",
            "weight_loss_pct",
            "functional_decline",
        ],
    },
    "bone_agent": {
        "title": "Seguridad de salud ósea / BMA",
        "fields": [
            "dental_clearance_done",
            "onj_monitoring",
            "creatinine",
            "bone_pain",
            "skeletal_events",
        ],
    },
    "psychosocial_sexual": {
        "title": "Psicosocial y sexual",
        "fields": [
            "depression_score",
            "anxiety_score",
            "sexual_bother",
            "body_image_distress",
            "return_to_work_status",
        ],
    },
}

FIELD_STALE_THRESHOLDS = {
    "dxa_t_score_lumbar": 730,
    "dxa_t_score_hip": 730,
    "vitamin_d_level": 365,
    "calcium_level": 180,
    "creatinine": 180,
    "hba1c": 180,
    "total_cholesterol": 180,
    "hdl_cholesterol": 180,
    "triglycerides": 180,
    "hemoglobin": 90,
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on", "positivo", "iniciado", "iniciada"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in items if _is_present(item)))


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
    for followup in normalize_followup_entries(patient.get("follow_ups") or patient.get("follow_up_visits") or []):
        parsed = _parse_date(followup.get("visit_date"))
        if parsed:
            candidates.append(parsed)
    for visit in list(patient.get("stage_visits") or []):
        parsed = _parse_date((visit or {}).get("visit_date") or (visit or {}).get("recorded_at") or (visit or {}).get("created_at"))
        if parsed:
            candidates.append(parsed)
    parsed_assessment = _parse_date((latest_assessment or {}).get("assessment_date"))
    if parsed_assessment:
        candidates.append(parsed_assessment)
    return max(candidates) if candidates else None


def _latest_followup(patient: dict[str, Any]) -> dict[str, Any]:
    visits = normalize_followup_entries(patient.get("follow_ups") or patient.get("follow_up_visits") or [])
    if not visits:
        return {}
    ordered = sorted(visits, key=lambda item: str(item.get("visit_date") or ""), reverse=True)
    return ordered[0]


def _merge_context(
    patient: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    latest_followup = _latest_followup(patient)
    latest_inputs = dict((latest_assessment or {}).get("input_snapshot") or {})
    for source in (
        patient.get("identity") or {},
        patient.get("baseline") or {},
        patient.get("prior_history") or {},
        latest_followup,
        latest_inputs,
        field_values or {},
        patient,
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value):
                merged[key] = value
    if _is_present(merged.get("pad_usage")) and not _is_present(merged.get("pad_count")):
        merged["pad_count"] = merged.get("pad_usage")
    if _is_present(merged.get("ipss_total")) and not _is_present(merged.get("ipss_score")):
        merged["ipss_score"] = merged.get("ipss_total")
    if _is_present(merged.get("peripheral_neuropathy_grade")) and not _is_present(merged.get("neuropathy_grade")):
        merged["neuropathy_grade"] = merged.get("peripheral_neuropathy_grade")
    if _is_present(merged.get("weight_loss_6m_pct")) and not _is_present(merged.get("weight_loss_pct")):
        merged["weight_loss_pct"] = merged.get("weight_loss_6m_pct")
    return merged


def _build_context_patient(
    patient: dict[str, Any],
    *,
    state: str,
    management_track: str,
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = _merge_context(patient, latest_assessment=latest_assessment, field_values=field_values)
    context_patient = deepcopy(patient)
    context_patient.setdefault("identity", {})
    if _is_present(merged.get("age")) or _is_present(merged.get("edad")):
        context_patient["identity"]["age"] = merged.get("age") or merged.get("edad")
    context_patient["baseline"] = dict(context_patient.get("baseline") or {})
    context_patient["baseline"].update(merged)
    context_patient["prior_history"] = dict(context_patient.get("prior_history") or {})
    context_patient["prior_history"].update(
        {
            "prior_rp": 1 if _truthy(merged.get("prior_prostatectomy") or merged.get("prior_rp")) else 0,
            "prior_rt": 1 if _truthy(merged.get("prior_radiation") or merged.get("prior_rt")) else 0,
            "prior_adt": 1 if _truthy(merged.get("prior_adt")) or _safe_float(merged.get("adt_duration_months")) else 0,
            "prior_docetaxel": 1 if _truthy(merged.get("prior_docetaxel")) else 0,
            "prior_cabazitaxel": 1 if _truthy(merged.get("prior_cabazitaxel")) else 0,
            "adt_duration_months": merged.get("adt_duration_months"),
            "on_denosumab": 1 if _truthy(merged.get("on_denosumab")) else 0,
            "on_zoledronate": 1 if _truthy(merged.get("on_zoledronate")) else 0,
            "nerve_sparing": merged.get("nerve_sparing"),
            "continence_status": merged.get("continence_status"),
        }
    )
    followup_payload = dict(_latest_followup(context_patient))
    followup_payload.update(merged)
    if not _is_present(followup_payload.get("visit_date")):
        followup_payload["visit_date"] = date.today().isoformat()
    context_patient["follow_ups"] = [followup_payload]
    context_patient["follow_up_visits"] = [followup_payload]
    if _truthy(merged.get("prior_radiation") or merged.get("prior_rt")):
        rt_course = {
            "rt_intent": merged.get("rt_context") or "definitive",
            "modality": merged.get("prior_rt_modality") or merged.get("modality") or "EBRT_IMRT",
            "target_volume": merged.get("target_volume") or "prostate_only",
            "total_dose_gy": merged.get("prior_rt_dose") or merged.get("total_dose_gy"),
            "fractions": merged.get("fractions") or 39,
            "dose_per_fraction_gy": merged.get("dose_per_fraction_gy"),
            "rt_start_date": merged.get("local_therapy_date") or merged.get("rt_date") or "",
            "toxicity": [
                {"domain": "GU", "phase": "late", "grade": _safe_int(merged.get("gu_toxicity_grade")) or 0, "details": "Toxicidad GU tardía"},
                {"domain": "GI", "phase": "late", "grade": _safe_int(merged.get("gi_toxicity_grade") or merged.get("rectal_toxicity_grade")) or 0, "details": "Toxicidad GI tardía"},
            ],
        }
        context_patient["radiation"] = [rt_course]
        context_patient["radiation_details"] = [rt_course]
    bone_agent = {}
    if _truthy(merged.get("on_denosumab")):
        bone_agent["agent"] = "denosumab"
    elif _truthy(merged.get("on_zoledronate")):
        bone_agent["agent"] = "zoledronic_acid"
    if bone_agent:
        bone_agent.update(
            {
                "dental_clearance_done": _truthy(merged.get("dental_clearance_done")),
                "onj_monitoring": _truthy(merged.get("onj_monitoring")),
            }
        )
        context_patient["bone_modifying_agent"] = bone_agent
    if isinstance(merged.get("skeletal_events"), list):
        context_patient["skeletal_events"] = list(merged.get("skeletal_events") or [])
    return context_patient, merged


def _build_service_context(context_patient: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten the merged runtime context for legacy helper services that still read
    top-level fields directly, while preserving the nested patient structure they
    also rely on.
    """
    service_context = deepcopy(context_patient)
    for key, value in merged.items():
        if _is_present(value):
            service_context[key] = value
    identity = service_context.get("identity") or {}
    if _is_present(identity.get("age")) and not _is_present(service_context.get("age")):
        service_context["age"] = identity.get("age")
    if _is_present(identity.get("edad")) and not _is_present(service_context.get("edad")):
        service_context["edad"] = identity.get("edad")
    return service_context


def _detect_exposures(context_patient: dict[str, Any], merged: dict[str, Any]) -> dict[str, bool]:
    prior = context_patient.get("prior_history") or {}
    treatment_text = " ".join(
        str(part or "")
        for part in (
            merged.get("current_treatment"),
            merged.get("drug_scheme"),
            merged.get("line_of_therapy_context"),
        )
    ).lower()
    return {
        "post_prostatectomy": bool(prior.get("prior_rp")) or bool(context_patient.get("surgery")) or _truthy(merged.get("prior_prostatectomy")),
        "post_radiotherapy": bool(prior.get("prior_rt")) or bool(context_patient.get("radiation")) or _truthy(merged.get("prior_radiation")),
        "adt": bool(prior.get("prior_adt")) or (_safe_float(merged.get("adt_duration_months")) or 0) > 0 or any(token in treatment_text for token in ("adt", "leuprolide", "goserelin", "degarelix", "relugolix")),
        "systemic_recovery": bool(prior.get("prior_docetaxel")) or bool(prior.get("prior_cabazitaxel")) or any(token in treatment_text for token in ("docetaxel", "cabazitaxel", "taxane", "taxano")),
        "bone_agent": _truthy(merged.get("on_denosumab")) or _truthy(merged.get("on_zoledronate")) or bool(context_patient.get("bone_modifying_agent")),
        "psychosocial_sexual": True,
    }


def _domain_blocks_for_exposures(exposures: dict[str, bool]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for key, config in SURVIVORSHIP_FIELD_BLOCKS.items():
        if exposures.get(key):
            blocks.append({"key": key, "title": config["title"], "fields": list(config["fields"])})
    return blocks


def _field_present(field: str, merged: dict[str, Any]) -> bool:
    aliases = {
        "ipss_score": ["ipss_score", "ipss_total"],
        "pad_count": ["pad_count", "pad_usage"],
        "neuropathy_grade": ["neuropathy_grade", "peripheral_neuropathy_grade"],
        "weight_loss_pct": ["weight_loss_pct", "weight_loss_6m_pct", "weight_loss"],
        "skeletal_events": ["skeletal_events"],
    }
    return any(_is_present(merged.get(alias)) for alias in aliases.get(field, [field]))


def _field_stale(field: str, *, latest_visit_date: date | None) -> bool:
    if not latest_visit_date:
        return False
    threshold = FIELD_STALE_THRESHOLDS.get(field, 180)
    return (date.today() - latest_visit_date).days > threshold


def _contains_high_burden_label(value: Any) -> bool:
    return str(value or "").strip().lower() in {"moderada", "moderado", "severa", "severo", "grave", "alto", "high"}


def _status_from_bool(flag: bool, positive: str, negative: str) -> str:
    return positive if flag else negative


def build_survivorship_transition_bundle(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context_patient, merged = _build_context_patient(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
        field_values=field_values,
    )
    service_context = _build_service_context(context_patient, merged)
    exposures = _detect_exposures(context_patient, merged)
    available = any(exposures.values())
    domain_blocks = _domain_blocks_for_exposures(exposures)
    required_visit_fields = _dedupe(
        [field for block in domain_blocks for field in list(block.get("fields") or [])]
    )
    latest_visit_date = _latest_visit_date(context_patient, latest_assessment)
    missing_inputs = [field for field in required_visit_fields if not _field_present(field, merged)]
    stale_inputs = [field for field in required_visit_fields if field not in missing_inputs and _field_stale(field, latest_visit_date=latest_visit_date)]

    if not available:
        return {
            "available": False,
            "oncologic_state_context": state,
            "survivorship_track": "survivorship_followup",
            "survivorship_track_label": SURVIVORSHIP_TRACK_LABELS["survivorship_followup"],
            "trigger_status": "observe",
            "trigger_status_label": SURVIVORSHIP_TRIGGER_LABELS["observe"],
            "trigger_reasons": [],
            "dominant_late_effect_domain": "not_applicable",
            "active_late_effect_alerts": [],
            "functional_recovery_status": "not_applicable",
            "bone_health_status": "not_applicable",
            "cardiometabolic_status": "not_applicable",
            "psychosexual_status": "not_applicable",
            "secondary_prevention_status": "not_applicable",
            "recommended_referrals": [],
            "recommended_interventions": [],
            "required_visit_fields": [],
            "missing_inputs": [],
            "stale_inputs": [],
            "late_effect_domain_blocks": [],
            "patient_reported_outcomes_expected": [],
        }

    care_plan = SurvivorshipCarePlan.generate(service_context, state, management_track or "systemic_surveillance")
    adt_profile = ADTSideEffectService.full_assessment(service_context).to_dict() if exposures.get("adt") else {}
    rt_history = RadiotherapyDetailService.build_rt_history(service_context).to_dict() if exposures.get("post_radiotherapy") else {}
    skeletal_profile = SkeletalEventService.build_sre_profile(service_context, state or "").to_dict() if exposures.get("bone_agent") else {}
    pro_alerts = [
        alert.to_dict()
        for alert in PRODecisionEngine.evaluate_all(
            int(_safe_int(context_patient.get("patient_id")) or 0),
            merged,
        )
    ]

    active_late_effect_alerts: list[str] = []
    trigger_reasons: list[str] = []
    recommended_referrals: list[str] = []
    recommended_interventions: list[str] = []
    domain_scores: dict[str, int] = {}

    pad_count = _safe_float(merged.get("pad_count") or merged.get("pad_usage")) or 0.0
    ipss_score = _safe_float(merged.get("ipss_score") or merged.get("ipss_total")) or 0.0
    leakage_bother = _safe_float(merged.get("leakage_bother")) or 0.0
    iief5 = _safe_float(merged.get("iief5_score"))
    urinary_high = exposures.get("post_prostatectomy") and (
        pad_count >= 2 or ipss_score >= 20 or _contains_high_burden_label(merged.get("continence_status")) or leakage_bother >= 5
    )
    sexual_high = (exposures.get("post_prostatectomy") or exposures.get("adt") or exposures.get("post_radiotherapy")) and (
        (iief5 is not None and iief5 < 12)
        or (_safe_float(merged.get("sexual_bother")) or 0) >= 5
        or (_safe_float(merged.get("body_image_distress")) or 0) >= 5
    )
    if urinary_high:
        domain_scores["urinary_recovery"] = 3
        active_late_effect_alerts.append("Incontinencia o LUTS persistentes tras tratamiento local.")
        trigger_reasons.append("La recuperación urinaria sigue siendo un problema clínico activo.")
        recommended_referrals.extend(["Urología funcional", "Fisioterapia de piso pélvico"])
        recommended_interventions.extend(["Escalar rehabilitación urinaria y revisar carga de incontinencia.", "No dejar secuelas urinarias sin pathway de recuperación."])
    if sexual_high:
        domain_scores["psychosexual"] = max(domain_scores.get("psychosexual", 0), 2)
        active_late_effect_alerts.append("Disfunción sexual o carga psicosexual persistentes.")
        recommended_referrals.extend(["Sexología oncológica", "Psicooncología"])
        recommended_interventions.extend(["Revisar rehabilitación sexual, PDE5i y carga psicosocial asociada al tratamiento."])

    gu_grade = _safe_int(merged.get("gu_toxicity_grade")) or 0
    gi_grade = max(_safe_int(merged.get("gi_toxicity_grade")) or 0, _safe_int(merged.get("rectal_toxicity_grade")) or 0)
    rt_high = exposures.get("post_radiotherapy") and (
        gu_grade >= 2
        or gi_grade >= 2
        or _contains_high_burden_label(merged.get("hematuria"))
        or _contains_high_burden_label(merged.get("dysuria"))
        or _truthy(merged.get("radiation_cystitis"))
        or _truthy(merged.get("proctitis"))
    )
    if rt_high:
        domain_scores["rt_late_toxicity"] = 4 if max(gu_grade, gi_grade) >= 3 else 3
        active_late_effect_alerts.append("Toxicidad tardía GU/GI post-radioterapia clínicamente relevante.")
        trigger_reasons.append("La toxicidad tardía post-RT requiere intervención dirigida y no solo seguimiento genérico.")
        recommended_referrals.extend(["Uro-oncología funcional", "Gastroenterología / manejo de toxicidad por radiación"])
        recommended_interventions.extend(["Escalar manejo de cistitis actínica / proctitis y documentar grado de toxicidad tardía."])

    cv_risk = str((adt_profile.get("cv_risk") or {}).get("risk_category") or "")
    metabolic_syndrome = bool((adt_profile.get("metabolic_syndrome") or {}).get("has_metabolic_syndrome"))
    bone_category = str((adt_profile.get("bone_health") or {}).get("bone_category") or "")
    cardiometabolic_high = exposures.get("adt") and (cv_risk == "high" or metabolic_syndrome)
    if cardiometabolic_high:
        domain_scores["cardiometabolic"] = 3
        active_late_effect_alerts.append("Riesgo cardiometabólico relevante bajo ADT.")
        trigger_reasons.append("La exposición a ADT ya exige corrección cardiometabólica estructurada.")
        recommended_referrals.extend(["Cardio-oncología", "Nutrición / medicina interna"])
        recommended_interventions.extend(list((adt_profile.get("cv_risk") or {}).get("recommendations") or [])[:3])

    bone_high = exposures.get("adt") and bone_category in {"osteopenia", "osteoporosis"}
    if bone_high:
        domain_scores["bone_health"] = 3 if bone_category == "osteoporosis" else 2
        active_late_effect_alerts.append(f"Salud ósea comprometida ({bone_category}).")
        trigger_reasons.append("La salud ósea necesita intervención y prevención secundaria estructuradas.")
        recommended_referrals.extend(["Clínica de salud ósea / endocrinología"])
        recommended_interventions.extend(list((adt_profile.get("bone_health") or {}).get("recommendations") or [])[:3])

    neuropathy_grade = _safe_int(merged.get("neuropathy_grade") or merged.get("peripheral_neuropathy_grade")) or 0
    fatigue_score = _safe_float(merged.get("fatigue_score")) or 0.0
    hemoglobin = _safe_float(merged.get("hemoglobin"))
    systemic_recovery_high = exposures.get("systemic_recovery") and (
        neuropathy_grade >= 2
        or fatigue_score >= 7
        or (hemoglobin is not None and hemoglobin < 10)
        or (_safe_float(merged.get("weight_loss_pct")) or 0) >= 10
        or _truthy(merged.get("functional_decline"))
    )
    if systemic_recovery_high:
        domain_scores["systemic_recovery"] = 3
        active_late_effect_alerts.append("Neuropatía, fatiga o declive funcional post-sistémicos.")
        trigger_reasons.append("La recuperación post-sistémicos requiere rehabilitación y vigilancia funcional.")
        recommended_referrals.extend(["Rehabilitación oncológica", "Nutrición clínica"])
        recommended_interventions.extend(["Escalar recuperación funcional, neuropatía y fatiga con objetivos medibles."])

    bma_safety_issue = exposures.get("bone_agent") and (
        not _truthy(merged.get("dental_clearance_done"))
        or not _truthy(merged.get("onj_monitoring"))
        or ((_safe_float(merged.get("creatinine")) or 0) > 1.5 and _truthy(merged.get("on_zoledronate")))
    )
    if bma_safety_issue:
        domain_scores["bone_agent_safety"] = 3
        active_late_effect_alerts.append("Seguridad incompleta del agente modificador óseo.")
        trigger_reasons.append("La seguridad dental / renal del agente óseo debe cerrarse antes de continuar inercialmente.")
        recommended_referrals.extend(["Odontología oncológica", "Nefrología" if _truthy(merged.get("on_zoledronate")) else "Clínica de salud ósea"])
        recommended_interventions.extend(list(skeletal_profile.get("bma_compliance_warnings") or [])[:3] or ["Completar clearance dental y monitoreo de ONJ."])

    psychosocial_high = (_safe_float(merged.get("depression_score")) or 0) >= 7 or (_safe_float(merged.get("anxiety_score")) or 0) >= 7
    if psychosocial_high:
        domain_scores["psychosocial"] = max(domain_scores.get("psychosocial", 0), 2)
        active_late_effect_alerts.append("Carga psicosocial relevante durante survivorship.")
        recommended_referrals.extend(["Psicooncología", "Trabajo social"])
        recommended_interventions.extend(["Escalar soporte emocional, retorno a trabajo y distress relacionado con tratamiento."])

    explicit_oncologic_reentry = (
        _truthy(merged.get("reenter_oncologic_decision"))
        or _truthy(merged.get("oncologic_redecision_required"))
        or _truthy(merged.get("oncologic_reassessment_needed"))
        or _truthy(merged.get("new_progression_suspected"))
    )
    severe_oncologic_impact = (
        max(gu_grade, gi_grade) >= 3
        or (_contains_high_burden_label(merged.get("hematuria")) and str(merged.get("hematuria")).strip().lower() == "severa")
        or explicit_oncologic_reentry
    )
    dominant_domain = max(domain_scores, key=domain_scores.get) if domain_scores else "general_survivorship"

    if severe_oncologic_impact:
        trigger_status = "reenter_oncologic_decision"
        survivorship_track = "late_effect_intervention"
        trigger_reasons.append("La secuela actual puede cambiar elegibilidad o conducta oncológica y debe reabrir la decisión principal.")
    elif systemic_recovery_high and dominant_domain == "systemic_recovery":
        trigger_status = "refer_rehabilitation"
        survivorship_track = "toxicity_recovery"
        trigger_reasons.append("La recuperación post-sistémicos domina la conducta actual y requiere un track explícito de rehabilitación.")
    elif any(score >= 3 for score in domain_scores.values()):
        trigger_status = "refer_specialist"
        survivorship_track = "late_effect_intervention"
    elif urinary_high or systemic_recovery_high or _truthy(merged.get("pelvic_floor_pt_started")) is False and exposures.get("post_prostatectomy"):
        trigger_status = "refer_rehabilitation"
        survivorship_track = "toxicity_recovery"
    elif active_late_effect_alerts:
        trigger_status = "intensify_toxicity_management"
        survivorship_track = "late_effect_intervention"
    elif missing_inputs or stale_inputs:
        trigger_status = "monitor_recovery"
        survivorship_track = "survivorship_followup"
        trigger_reasons.append("Persisten brechas de captura para sostener un seguimiento de survivorship robusto.")
    else:
        trigger_status = "observe"
        survivorship_track = "survivorship_followup"

    active_late_effect_alerts.extend(str(alert.get("title") or "").strip() for alert in pro_alerts[:3] if str(alert.get("title") or "").strip())

    bone_status = "osteoporosis" if bone_category == "osteoporosis" else "osteopenia" if bone_category == "osteopenia" else "stable"
    if bma_safety_issue:
        bone_status = "bma_safety_issue"
    cardiometabolic_status = "high_risk" if cardiometabolic_high else "monitoring_due" if exposures.get("adt") else "not_applicable"
    psychosexual_status = "high_burden" if sexual_high or psychosocial_high else "monitoring_due" if exposures.get("psychosocial_sexual") else "not_applicable"
    functional_recovery_status = "needs_rehab" if urinary_high or systemic_recovery_high else "stable"
    secondary_prevention_status = "incomplete" if missing_inputs else "active"

    return {
        "available": True,
        "oncologic_state_context": state,
        "survivorship_track": survivorship_track,
        "survivorship_track_label": SURVIVORSHIP_TRACK_LABELS[survivorship_track],
        "trigger_status": trigger_status,
        "trigger_status_label": SURVIVORSHIP_TRIGGER_LABELS[trigger_status],
        "trigger_reasons": _dedupe(trigger_reasons or [SURVIVORSHIP_TRIGGER_LABELS[trigger_status]]),
        "dominant_late_effect_domain": dominant_domain,
        "active_late_effect_alerts": _dedupe(active_late_effect_alerts),
        "functional_recovery_status": functional_recovery_status,
        "bone_health_status": bone_status,
        "cardiometabolic_status": cardiometabolic_status,
        "psychosexual_status": psychosexual_status,
        "secondary_prevention_status": secondary_prevention_status,
        "recommended_referrals": _dedupe(recommended_referrals),
        "recommended_interventions": _dedupe(recommended_interventions),
        "required_visit_fields": required_visit_fields,
        "missing_inputs": missing_inputs,
        "stale_inputs": stale_inputs,
        "late_effect_domain_blocks": domain_blocks,
        "patient_reported_outcomes_expected": _dedupe(
            [field for field in required_visit_fields if field in {"ipss_score", "iief5_score", "fatigue_score", "depression_score", "anxiety_score", "sexual_bother", "body_image_distress", "return_to_work_status"}]
        ),
        "exposures": exposures,
        "survivorship_plan": care_plan,
        "adt_side_effects_profile": adt_profile,
        "radiotherapy_detail_profile": rt_history,
        "skeletal_event_profile": skeletal_profile,
        "pro_alerts": pro_alerts,
    }


def build_survivorship_monitoring_package(
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
        or build_survivorship_transition_bundle(
            patient,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=field_values,
        )
    )
    if not bundle.get("available"):
        return {
            "required_visit_fields": [],
            "missing_inputs": [],
            "stale_inputs": [],
            "recommended_cadence": "",
            "rehab_checks": [],
            "toxicity_checks": [],
            "screening_checks": [],
            "patient_reported_outcomes_expected": [],
        }
    trigger_status = str(bundle.get("trigger_status") or "observe")
    cadence = {
        "reenter_oncologic_decision": "Revisión prioritaria en 2 a 4 semanas o antes si cambia elegibilidad oncológica.",
        "refer_specialist": "Revisión de survivorship cada 4 a 8 semanas hasta estabilizar la secuela dominante.",
        "refer_rehabilitation": "Revisión funcional cada 6 a 8 semanas con metas objetivas de recuperación.",
        "intensify_toxicity_management": "Revisión clínica cada 4 a 8 semanas hasta mejorar toxicidad o QoL.",
        "monitor_recovery": "Revisión cada 3 a 6 meses con captura estructurada de toxicidad y PROs.",
        "observe": "Revisión survivorship cada 6 a 12 meses si no emergen nuevas secuelas.",
    }.get(trigger_status, "Revisión cada 3 a 6 meses.")
    return {
        "required_visit_fields": list(bundle.get("required_visit_fields") or []),
        "missing_inputs": list(bundle.get("missing_inputs") or []),
        "stale_inputs": list(bundle.get("stale_inputs") or []),
        "recommended_cadence": cadence,
        "rehab_checks": _dedupe(
            [
                field
                for field in list(bundle.get("required_visit_fields") or [])
                if field in {"pad_count", "continence_status", "leakage_bother", "pelvic_floor_pt_started", "neuropathy_grade", "fatigue_score", "functional_decline", "return_to_work_status"}
            ]
        ),
        "toxicity_checks": _dedupe(
            [
                field
                for field in list(bundle.get("required_visit_fields") or [])
                if field in {"gu_toxicity_grade", "gi_toxicity_grade", "rectal_toxicity_grade", "hematuria", "dysuria", "radiation_cystitis", "proctitis", "systolic_bp", "diastolic_bp", "hba1c", "total_cholesterol", "hdl_cholesterol", "triglycerides", "dxa_t_score_lumbar", "dxa_t_score_hip", "vitamin_d_level", "calcium_level", "creatinine", "dental_clearance_done", "onj_monitoring"}
            ]
        ),
        "screening_checks": _dedupe(
            [
                "secondary_prevention_status",
                "depression_score",
                "anxiety_score",
                "sexual_bother",
                "body_image_distress",
            ]
        ),
        "patient_reported_outcomes_expected": list(bundle.get("patient_reported_outcomes_expected") or []),
    }


def build_survivorship_schedule_overlay(
    transition_bundle: dict[str, Any],
    monitoring_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(transition_bundle or {})
    monitoring = dict(monitoring_package or {})
    if not bundle.get("available"):
        return {}
    return {
        "available": True,
        "title": bundle.get("survivorship_track_label") or "Seguimiento de survivorship",
        "trigger_status": bundle.get("trigger_status"),
        "dominant_domain": bundle.get("dominant_late_effect_domain"),
        "cadence_summary": monitoring.get("recommended_cadence") or "",
        "capture_focus": list((bundle.get("missing_inputs") or bundle.get("stale_inputs") or bundle.get("required_visit_fields") or [])[:10]),
        "recommended_referrals": list(bundle.get("recommended_referrals") or []),
    }


def build_survivorship_plan_alias(
    transition_bundle: dict[str, Any],
    monitoring_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = dict(transition_bundle or {})
    monitoring = dict(monitoring_package or {})
    care_plan = dict(bundle.get("survivorship_plan") or {})
    return {
        **care_plan,
        "available": bool(bundle.get("available")),
        "oncologic_state_context": bundle.get("oncologic_state_context"),
        "survivorship_track": bundle.get("survivorship_track"),
        "trigger_status": bundle.get("trigger_status"),
        "dominant_late_effect_domain": bundle.get("dominant_late_effect_domain"),
        "active_late_effect_alerts": list(bundle.get("active_late_effect_alerts") or []),
        "recommended_referrals": list(bundle.get("recommended_referrals") or []),
        "recommended_interventions": list(bundle.get("recommended_interventions") or []),
        "required_visit_fields": list(bundle.get("required_visit_fields") or []),
        "missing_inputs": list(bundle.get("missing_inputs") or []),
        "stale_inputs": list(bundle.get("stale_inputs") or []),
        "recommended_cadence": monitoring.get("recommended_cadence") or "",
        "late_effect_domain_blocks": list(bundle.get("late_effect_domain_blocks") or []),
    }
