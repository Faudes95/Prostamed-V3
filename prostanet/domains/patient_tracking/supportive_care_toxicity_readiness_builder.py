from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.palliative_longitudinal import (
    build_palliative_monitoring_package,
    build_palliative_transition_bundle,
)
from prostanet.domains.patient_tracking.survivorship_longitudinal import (
    build_survivorship_monitoring_package,
    build_survivorship_transition_bundle,
)


SYSTEMIC_FAMILIES = {
    "arpi_family",
    "abiraterone_steroid_family",
    "taxane_family",
    "parp_family",
    "psma_rlt_family",
    "radium223_family",
    "immunotherapy_family",
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


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _normalize_text(value).lower() in {"1", "true", "yes", "si", "sí", "on", "positive", "positivo", "high", "alto"}


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


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _merge_field_values(
    patient_record: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    latest_followup = (list(patient_record.get("follow_ups") or []) or [{}])[-1]
    latest_signal_snapshot = dict(patient_record.get("latest_signal_snapshot") or {})
    latest_inputs = dict((latest_assessment or patient_record.get("latest_assessment") or {}).get("input_snapshot") or {})
    fact_values = dict((clinical_fact_bundle or {}).get("field_values") or {})
    for source in (
        patient_record.get("baseline") or {},
        patient_record.get("prior_history") or {},
        latest_followup or {},
        latest_signal_snapshot,
        latest_inputs,
        fact_values,
        field_values or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value):
                merged[key] = value
    return merged


def _display_status_from_supportive(status: str) -> str:
    mapping = {
        "ready": "ready_to_release",
        "review_needed": "conditional_pending_closure",
        "co_manage_required": "co_manage_required",
        "blocking_support_gap": "blocking_support_gap",
    }
    return mapping.get(_normalize_text(status), "ready_to_release")


def _build_domain_snapshot(
    *,
    key: str,
    active: bool,
    status: str,
    reasons: list[str],
    missing_inputs: list[str],
    stale_inputs: list[str],
    actions: list[str],
) -> dict[str, Any]:
    return {
        "domain_key": key,
        "active": active,
        "status": status,
        "reasons": _dedupe(reasons),
        "missing_inputs": _dedupe(missing_inputs),
        "stale_inputs": _dedupe(stale_inputs),
        "required_support_actions": _dedupe(actions),
    }


def _therapy_support_status(
    *,
    family_code: str,
    frailty_high: bool,
    cognition_or_falls_high: bool,
    cardiometabolic_high: bool,
    bone_support_gap: bool,
    palliative_dominant: bool,
    concurrent_palliative: bool,
    taxane_unsustainable: bool,
    missing_support_inputs: list[str],
    stale_support_inputs: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    actions: list[str] = []
    blockers: list[str] = []
    status = "ready"

    if palliative_dominant:
        status = "blocking_support_gap"
        blockers.append("La prioridad clínica dominante hoy es soporte/paliación y obliga revaluar la intensificación.")
        actions.append("Confirmar si la agenda dominante debe pasar a soporte exclusivo o paliación concurrente estructurada.")
    elif family_code == "taxane_family" and taxane_unsustainable:
        status = "blocking_support_gap"
        blockers.append("El taxano no es clínicamente sostenible hoy con fragilidad, neuropatía o declive funcional actuales.")
        actions.extend(
            [
                "Optimizar fragilidad, neuropatía y recuperación funcional antes de sostener taxano.",
                "Reabrir la preferencia entre taxano y alternativas menos tóxicas si persiste el deterioro.",
            ]
        )
    elif family_code in {"arpi_family", "abiraterone_steroid_family"} and cognition_or_falls_high:
        status = "co_manage_required"
        reasons.append("El riesgo de caídas o deterioro cognitivo obliga co-manejo antes de sostener ARPI.")
        actions.append("Completar evaluación de caídas/cognición y plan de mitigación antes de sostener ARPI.")
    elif family_code == "abiraterone_steroid_family" and cardiometabolic_high:
        status = "co_manage_required"
        reasons.append("El riesgo cardiometabólico actual exige co-manejo antes de sostener abiraterona.")
        actions.append("Optimizar presión arterial, metabolismo y riesgo cardiovascular durante abiraterona + esteroide.")
    elif family_code in SYSTEMIC_FAMILIES and concurrent_palliative:
        status = "co_manage_required"
        reasons.append("La carga sintomática exige soporte paliativo concurrente para sostener la terapia oncológica.")
        actions.append("Integrar cuidados paliativos concurrentes y control sintomático estructurado.")
    elif family_code in SYSTEMIC_FAMILIES and bone_support_gap:
        status = "co_manage_required"
        reasons.append("Existe una brecha de salud ósea/SRE que debe cerrarse para sostener la terapia de forma segura.")
        actions.append("Activar bundle óseo: calcio/vitamina D, BMA cuando aplique y seguridad dental.")
    elif family_code in SYSTEMIC_FAMILIES and cardiometabolic_high:
        status = "review_needed"
        reasons.append("La seguridad cardiometabólica requiere revisión activa para sostener tratamiento.")
        actions.append("Actualizar monitoreo cardiometabólico y documentar mitigación de riesgo.")

    if status == "ready" and (missing_support_inputs or stale_support_inputs):
        status = "review_needed"
        reasons.append("Persisten brechas de soporte o toxicidad que deben cerrarse para sostener la decisión.")
        actions.append("Actualizar bundle de soporte, toxicidad y funcionalidad antes de la siguiente liberación.")

    if frailty_high and family_code == "taxane_family" and status != "blocking_support_gap":
        status = "co_manage_required"
        reasons.append("La fragilidad actual obliga un plan de soporte si se mantiene taxano.")
        actions.append("Completar evaluación geriátrica/rehabilitación antes de mantener taxano.")

    return {
        "status": status,
        "required_support_actions": _dedupe(actions),
        "hard_support_blockers": _dedupe(blockers),
        "why_support_changes_choice": _dedupe(reasons + blockers),
    }


def build_supportive_care_toxicity_readiness_bundle(
    *,
    patient_record: dict[str, Any],
    state: str,
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    field_values: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    palliative_transition_bundle: dict[str, Any] | None = None,
    palliative_monitoring_package: dict[str, Any] | None = None,
    survivorship_transition_bundle: dict[str, Any] | None = None,
    survivorship_monitoring_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    values = _merge_field_values(
        patient_record,
        latest_assessment=latest_assessment,
        field_values=field_values,
        clinical_fact_bundle=clinical_fact_bundle,
    )

    palliative_transition_bundle = dict(
        palliative_transition_bundle
        or build_palliative_transition_bundle(
            patient_record,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=values,
        )
    )
    palliative_monitoring_package = dict(
        palliative_monitoring_package
        or build_palliative_monitoring_package(
            patient_record,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=values,
            transition_bundle=palliative_transition_bundle,
        )
    )
    survivorship_transition_bundle = dict(
        survivorship_transition_bundle
        or build_survivorship_transition_bundle(
            patient_record,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=values,
        )
    )
    survivorship_monitoring_package = dict(
        survivorship_monitoring_package
        or build_survivorship_monitoring_package(
            patient_record,
            state=state,
            management_track=management_track,
            latest_assessment=latest_assessment,
            field_values=values,
            transition_bundle=survivorship_transition_bundle,
        )
    )

    mini_cog = _safe_float(values.get("mini_cog_score"))
    g8_score = _safe_float(values.get("g8_score"))
    ecog = _safe_int(values.get("ecog") or values.get("ecog_score")) or 0
    neuropathy_grade = _safe_int(values.get("neuropathy_grade") or values.get("peripheral_neuropathy_grade")) or 0
    hemoglobin = _safe_float(values.get("hemoglobin"))
    weight_loss_pct = _safe_float(values.get("weight_loss_pct") or values.get("weight_loss_6m_pct")) or 0.0
    frailty_status = _normalize_text(values.get("frailty_status")).lower()
    ddi_completed = _normalize_text(values.get("ddi_review_status")).lower() == "completed"
    cv_documented = _truthy(values.get("cv_risk_documented"))
    fall_risk_high = _truthy(values.get("fall_risk")) or _normalize_text(values.get("fall_risk")).lower() in {"high", "alto"}
    cognitive_risk_high = _truthy(values.get("cognitive_risk")) or _normalize_text(values.get("cognitive_risk")).lower() in {"high", "alto"}
    on_denosumab = _truthy(values.get("on_denosumab"))
    on_zoledronate = _truthy(values.get("on_zoledronate"))
    dental_clearance_done = _truthy(values.get("dental_clearance_done"))
    bone_pain = _truthy(values.get("bone_pain"))

    palliative_dominant = _normalize_text(palliative_transition_bundle.get("supportive_priority")) == "dominant"
    concurrent_palliative = _normalize_text(palliative_transition_bundle.get("care_mode")) == "concurrent_palliative_care"
    urgent_palliative = _normalize_text(palliative_transition_bundle.get("trigger_status")) == "urgent_local_palliation"

    frailty_high = frailty_status in {"frail", "vulnerable"} or (g8_score is not None and g8_score < 14) or ecog >= 2
    cognition_or_falls_high = (mini_cog is not None and mini_cog <= 2) or fall_risk_high or cognitive_risk_high
    cardiometabolic_high = _normalize_text(survivorship_transition_bundle.get("cardiometabolic_status")) == "high_risk"
    bone_high = _normalize_text(survivorship_transition_bundle.get("bone_health_status")) in {"osteopenia", "osteoporosis", "bma_safety_issue"} or _normalize_text((palliative_transition_bundle.get("bone_event_risk") or {}).get("risk_level")) in {"elevated", "high"}
    bone_support_gap = bone_high and (
        not on_denosumab
        and not on_zoledronate
        and (bone_pain or _normalize_text(survivorship_transition_bundle.get("bone_health_status")) != "stable")
        or (_normalize_text(survivorship_transition_bundle.get("bone_health_status")) == "bma_safety_issue")
        or ((on_denosumab or on_zoledronate) and not dental_clearance_done)
    )
    taxane_unsustainable = frailty_high or neuropathy_grade >= 2 or weight_loss_pct >= 10 or (hemoglobin is not None and hemoglobin < 10)

    missing_support_inputs = _dedupe(
        list(survivorship_transition_bundle.get("missing_inputs") or [])
        + list(palliative_transition_bundle.get("missing_inputs") or [])
        + ([] if _is_present(values.get("mini_cog_score")) else ["mini_cog_score"])
        + ([] if _is_present(values.get("g8_score")) else ["g8_score"])
        + ([] if ddi_completed else ["ddi_review_status"])
        + ([] if cv_documented else ["cv_risk_documented"])
    )
    stale_support_inputs = _dedupe(
        list(survivorship_transition_bundle.get("stale_inputs") or [])
        + list(palliative_transition_bundle.get("stale_inputs") or [])
    )

    bone_domain_actions = _dedupe(
        list(survivorship_transition_bundle.get("recommended_interventions") or [])
        + (
            ["Activar bundle óseo: calcio/vitamina D, BMA cuando aplique y revisión dental."]
            if bone_support_gap
            else []
        )
    )
    frailty_domain_actions = _dedupe(
        [
            "Completar evaluación geriátrica/fragilidad, cognición y riesgo de caídas."
            if (frailty_high or cognition_or_falls_high)
            else "",
            "Activar rehabilitación funcional con objetivos medibles."
            if _normalize_text(survivorship_transition_bundle.get("functional_recovery_status")) == "needs_rehab"
            else "",
        ]
    )
    metabolic_domain_actions = _dedupe(
        list((survivorship_transition_bundle.get("recommended_interventions") or [])[:3])
        + (
            ["Completar revisión de DDI y riesgo cardiovascular antes de sostener ARPI/ADT."]
            if (not ddi_completed or not cv_documented)
            else []
        )
    )
    symptom_domain_actions = _dedupe(
        list(palliative_transition_bundle.get("recommended_interventions") or [])
        + (
            ["Integrar cuidados paliativos concurrentes y control sintomático estructurado."]
            if concurrent_palliative
            else []
        )
    )

    bone_domain = _build_domain_snapshot(
        key="bone_health_and_sre",
        active=bone_high or bone_support_gap,
        status="blocking_support_gap" if urgent_palliative and bone_pain else "co_manage_required" if bone_support_gap else "review_needed" if bone_high else "ready",
        reasons=[
            "La salud ósea o el riesgo de SRE ya influyen en la sostenibilidad del tratamiento."
            if bone_high
            else "",
            "Persisten brechas de seguridad dental o BMA."
            if _normalize_text(survivorship_transition_bundle.get("bone_health_status")) == "bma_safety_issue"
            else "",
        ],
        missing_inputs=[field for field in missing_support_inputs if field in {"dxa_t_score_lumbar", "dxa_t_score_hip", "vitamin_d_level", "calcium_level", "creatinine", "dental_clearance_done", "onj_monitoring"}],
        stale_inputs=[field for field in stale_support_inputs if field in {"dxa_t_score_lumbar", "dxa_t_score_hip", "vitamin_d_level", "calcium_level", "creatinine"}],
        actions=bone_domain_actions,
    )
    frailty_domain = _build_domain_snapshot(
        key="frailty_cognition_falls",
        active=frailty_high or cognition_or_falls_high or _normalize_text(survivorship_transition_bundle.get("functional_recovery_status")) == "needs_rehab",
        status="co_manage_required" if (frailty_high or cognition_or_falls_high) else "review_needed" if _normalize_text(survivorship_transition_bundle.get("functional_recovery_status")) == "needs_rehab" else "ready",
        reasons=[
            "La fragilidad, cognición o riesgo de caídas ya pueden modificar intensidad o sostenibilidad terapéutica."
            if (frailty_high or cognition_or_falls_high)
            else "",
        ],
        missing_inputs=[field for field in missing_support_inputs if field in {"mini_cog_score", "g8_score", "fall_risk", "cognitive_risk", "frailty_status"}],
        stale_inputs=[field for field in stale_support_inputs if field in {"mini_cog_score", "g8_score"}],
        actions=frailty_domain_actions,
    )
    metabolic_domain = _build_domain_snapshot(
        key="adt_arpi_metabolic_cv",
        active=cardiometabolic_high or not ddi_completed or not cv_documented or _normalize_text(survivorship_transition_bundle.get("cardiometabolic_status")) == "monitoring_due",
        status="co_manage_required" if cardiometabolic_high else "review_needed" if (not ddi_completed or not cv_documented or _normalize_text(survivorship_transition_bundle.get("cardiometabolic_status")) == "monitoring_due") else "ready",
        reasons=[
            "La seguridad cardiometabólica bajo ADT/ARPI exige co-manejo activo."
            if cardiometabolic_high
            else "La seguridad cardiometabólica o de interacciones sigue incompleta."
            if (not ddi_completed or not cv_documented)
            else "",
        ],
        missing_inputs=[field for field in missing_support_inputs if field in {"ddi_review_status", "cv_risk_documented", "current_medications", "hba1c", "total_cholesterol", "hdl_cholesterol", "triglycerides"}],
        stale_inputs=[field for field in stale_support_inputs if field in {"hba1c", "total_cholesterol", "hdl_cholesterol", "triglycerides"}],
        actions=metabolic_domain_actions,
    )
    symptom_domain = _build_domain_snapshot(
        key="symptom_burden_and_palliative",
        active=concurrent_palliative or palliative_dominant or urgent_palliative or bool(palliative_transition_bundle.get("acute_palliative_alerts")),
        status="blocking_support_gap" if (palliative_dominant or urgent_palliative) else "co_manage_required" if concurrent_palliative else "ready",
        reasons=[
            "La carga sintomática o un trigger paliativo ya cambian la sostenibilidad clínica del plan."
            if (concurrent_palliative or palliative_dominant or urgent_palliative)
            else "",
        ],
        missing_inputs=[field for field in missing_support_inputs if field in {"pain", "bpi_worst_pain", "opioid_use", "breakthrough_pain", "ecog", "goals_of_care_discussed"}],
        stale_inputs=[field for field in stale_support_inputs if field in {"pain", "bpi_worst_pain", "opioid_use", "ecog"}],
        actions=symptom_domain_actions,
    )

    sustainability_status_by_therapy: dict[str, dict[str, Any]] = {}
    why_support_changes_choice_by_therapy: dict[str, list[str]] = {}
    required_support_actions = _dedupe(
        bone_domain["required_support_actions"]
        + frailty_domain["required_support_actions"]
        + metabolic_domain["required_support_actions"]
        + symptom_domain["required_support_actions"]
        + list(survivorship_transition_bundle.get("recommended_interventions") or [])
        + list(palliative_transition_bundle.get("recommended_interventions") or [])
    )
    recommended_referrals = _dedupe(
        list(survivorship_transition_bundle.get("recommended_referrals") or [])
        + list(palliative_transition_bundle.get("recommended_referrals") or [])
    )
    hard_support_blockers = _dedupe(
        list(palliative_transition_bundle.get("acute_palliative_alerts") or [])
        + (
            ["La prioridad clínica dominante hoy exige soporte/paliación antes de sostener intensificación."]
            if palliative_dominant
            else []
        )
        + (
            ["El taxano no es sostenible hoy sin cerrar fragilidad, neuropatía o declive funcional."]
            if taxane_unsustainable
            else []
        )
    )

    for family_code in sorted(SYSTEMIC_FAMILIES):
        snapshot = _therapy_support_status(
            family_code=family_code,
            frailty_high=frailty_high,
            cognition_or_falls_high=cognition_or_falls_high,
            cardiometabolic_high=cardiometabolic_high,
            bone_support_gap=bone_support_gap,
            palliative_dominant=palliative_dominant or urgent_palliative,
            concurrent_palliative=concurrent_palliative,
            taxane_unsustainable=taxane_unsustainable,
            missing_support_inputs=missing_support_inputs,
            stale_support_inputs=stale_support_inputs,
        )
        sustainability_status_by_therapy[family_code] = snapshot
        why_support_changes_choice_by_therapy[family_code] = list(snapshot.get("why_support_changes_choice") or [])

    therapy_domain = _build_domain_snapshot(
        key="therapy_sustainability",
        active=True,
        status="blocking_support_gap"
        if any(item.get("status") == "blocking_support_gap" for item in sustainability_status_by_therapy.values())
        else "co_manage_required"
        if any(item.get("status") == "co_manage_required" for item in sustainability_status_by_therapy.values())
        else "review_needed"
        if missing_support_inputs or stale_support_inputs
        else "ready",
        reasons=_dedupe(
            [
                "Una terapia puede ser oncológicamente correcta pero no sostenible hoy sin soporte explícito."
            ]
            + [reason for item in why_support_changes_choice_by_therapy.values() for reason in item]
        ),
        missing_inputs=missing_support_inputs,
        stale_inputs=stale_support_inputs,
        actions=required_support_actions,
    )

    supportive_domains_active = [
        domain["domain_key"]
        for domain in (
            bone_domain,
            frailty_domain,
            metabolic_domain,
            symptom_domain,
            therapy_domain,
        )
        if domain.get("active")
    ]

    supportive_readiness_status = "ready"
    if therapy_domain["status"] == "blocking_support_gap":
        supportive_readiness_status = "blocking_support_gap"
    elif therapy_domain["status"] == "co_manage_required":
        supportive_readiness_status = "co_manage_required"
    elif therapy_domain["status"] == "review_needed":
        supportive_readiness_status = "review_needed"

    supportive_priority = "background"
    if palliative_dominant:
        supportive_priority = "dominant"
    elif supportive_readiness_status in {"co_manage_required", "blocking_support_gap"} or concurrent_palliative:
        supportive_priority = "co_primary"

    summary = "El soporte longitudinal es suficiente para sostener la decisión clínica visible hoy."
    if supportive_readiness_status == "blocking_support_gap":
        summary = "La terapia o decisión sigue siendo clínicamente frágil hoy hasta cerrar brechas de soporte/toxicidad."
    elif supportive_readiness_status == "co_manage_required":
        summary = "La decisión oncológica puede sostenerse, pero requiere soporte o co-manejo explícito."
    elif supportive_readiness_status == "review_needed":
        summary = "Persisten brechas de soporte y toxicidad que deben actualizarse para sostener la decisión con seguridad."

    return {
        "available": bool(
            supportive_domains_active
            or palliative_transition_bundle.get("available")
            or survivorship_transition_bundle.get("available")
        ),
        "supportive_readiness_status": supportive_readiness_status,
        "supportive_priority": supportive_priority,
        "sustainability_status_by_therapy": sustainability_status_by_therapy,
        "why_support_changes_choice_by_therapy": why_support_changes_choice_by_therapy,
        "required_support_actions": required_support_actions,
        "missing_support_inputs": missing_support_inputs,
        "stale_support_inputs": stale_support_inputs,
        "hard_support_blockers": hard_support_blockers,
        "recommended_referrals": recommended_referrals,
        "supportive_domains_active": supportive_domains_active,
        "summary": summary,
        "bone_health_and_sre": bone_domain,
        "frailty_cognition_falls": frailty_domain,
        "adt_arpi_metabolic_cv": metabolic_domain,
        "symptom_burden_and_palliative": symptom_domain,
        "therapy_sustainability": therapy_domain,
        "palliative_transition_bundle": palliative_transition_bundle,
        "palliative_monitoring_package": palliative_monitoring_package,
        "survivorship_transition_bundle": survivorship_transition_bundle,
        "survivorship_monitoring_package": survivorship_monitoring_package,
    }


__all__ = ["build_supportive_care_toxicity_readiness_bundle"]
