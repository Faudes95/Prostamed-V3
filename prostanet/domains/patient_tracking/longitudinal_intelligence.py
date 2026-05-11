from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.shared.metastatic_profile import (
    derive_legacy_metastasis,
    derive_mhspc_burden_context,
    resolve_metastatic_state_context,
)
from prostanet.shared.systemic_progression import resolve_systemic_progression_context

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
from prostanet.domains.patient_tracking.clinical_decision_governance import (
    apply_governance_to_next_best_action,
    build_clinical_decision_governance_bundle,
)
from prostanet.domains.patient_tracking.followup_agenda import (
    MANAGEMENT_TRACK_LABELS,
    build_agenda_board,
    infer_management_track,
)
from prostanet.domains.patient_tracking.followup_reconciliation_service import (
    build_decision_recalculation_trace,
)
from prostanet.domains.patient_tracking.guideline_schedule_engine import (
    build_guideline_followup_plan,
)
from prostanet.domains.patient_tracking.master_followup_plan import (
    build_master_followup_plan,
)
from prostanet.domains.patient_tracking.palliative_longitudinal import (
    build_palliative_monitoring_package,
    build_palliative_transition_bundle,
)
from prostanet.domains.patient_tracking.survivorship_longitudinal import (
    build_survivorship_monitoring_package,
    build_survivorship_plan_alias,
    build_survivorship_schedule_overlay,
    build_survivorship_transition_bundle,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_sequence_transition_bundle,
    family_label,
    regimen_family_code,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.service import (
    build_laboratory_intelligence_profile,
)
from prostanet.domains.patient_tracking.longitudinal_truth_service import (
    build_longitudinal_truth_snapshot,
)
from prostanet.domains.patient_tracking.reconciled_state import (
    build_reconciled_state,
    derive_post_prostatectomy_course,
    derive_post_prostatectomy_truth,
)
from prostanet.shared.contracts import ClinicalSignalSet, NextBestAction, RecommendationAudit, StateTransitionProposal
from prostanet.shared.presentation_text import state_display_label


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
ADVANCED_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES

COMMON_EVIDENCE = ["NCCN 2026", "EAU 2026"]


def _state_label(state: str) -> str:
    return state_display_label(state)


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida", "unknown", "UNKNOWN")


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


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return None


def _current_field_values(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    truth_snapshot = patient.get("longitudinal_truth_snapshot") or build_longitudinal_truth_snapshot(patient, latest_assessment)
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    latest_stage_payload = {}
    if isinstance(latest_stage_visit.get("visit_bundle"), dict):
        latest_stage_payload = dict((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {})
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    latest_assessment_inputs = dict((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    psma_profile = dict(patient.get("psma_structured_profile") or {})
    latest_treatment = _latest(patient.get("treatments", []), "start_date", "created_at")

    values: dict[str, Any] = {}
    for source in (
        patient.get("baseline") or {},
        dict(truth_snapshot.get("field_values") or {}),
        latest_signal_snapshot,
        latest_assessment_inputs,
        latest_followup,
        latest_stage_payload,
        latest_biopsy,
        patient.get("active_surveillance_protocol") or {},
        patient.get("active_surveillance") or {},
        psma_profile,
        latest_treatment,
        dict(latest_treatment.get("regimen_json") or {}) if isinstance(latest_treatment.get("regimen_json"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value):
                values[key] = value

    resolved_psa_current, _ = _resolve_current_psa(patient, latest_assessment, values)
    state_hint = str(values.get("state") or _current_state(patient, latest_assessment) or "")
    if resolved_psa_current is not None:
        values["psa_current"] = resolved_psa_current
        if state_hint in POSTLOCAL_STATES and not _is_present(values.get("psa_postop")):
            values["psa_postop"] = resolved_psa_current
    elif _is_present(values.get("psa")) and not _is_present(values.get("psa_current")):
        values["psa_current"] = values["psa"]
    if _is_present(values.get("testosterone")) and not _is_present(values.get("testosterone_value")):
        values["testosterone_value"] = values["testosterone"]
    if _is_present(values.get("ecog")) and not _is_present(values.get("ecog_score")):
        values["ecog_score"] = values["ecog"]
    if _is_present(values.get("current_treatment")) and not _is_present(values.get("drug_scheme")):
        values["drug_scheme"] = values["current_treatment"]
    if _is_present(latest_treatment.get("line_of_therapy")) and not _is_present(values.get("line_of_therapy_number")):
        values["line_of_therapy_number"] = latest_treatment.get("line_of_therapy")
    if _is_present(latest_treatment.get("drug_scheme")) and not _is_present(values.get("drug_scheme")):
        values["drug_scheme"] = latest_treatment.get("drug_scheme")
    if _is_present(latest_treatment.get("line_of_therapy_context")) and not _is_present(values.get("line_of_therapy_context")):
        values["line_of_therapy_context"] = latest_treatment.get("line_of_therapy_context")
    if not _is_present(values.get("management_track")) and _is_present(patient.get("schedule_management_track")):
        values["management_track"] = patient.get("schedule_management_track")
    if not _is_present(values.get("state")):
        values["state"] = _current_state(patient, latest_assessment)
    if not _is_present(values.get("prior_prostatectomy")):
        values["prior_prostatectomy"] = 1 if patient.get("surgery") else 0
    if not _is_present(values.get("prior_radiation")):
        values["prior_radiation"] = 1 if patient.get("radiation") else 0
    testosterone_value = _safe_float(values.get("testosterone")) or _safe_float(values.get("testosterone_value")) or _safe_float(values.get("testosterone_current"))
    if testosterone_value is not None and not _is_present(values.get("castrate_testosterone_status")):
        values["castrate_testosterone_status"] = "confirmed_castrate" if testosterone_value <= 50 else "not_castrate"
    if testosterone_value is not None and not _is_present(values.get("castrate_testosterone_confirmed")):
        values["castrate_testosterone_confirmed"] = 1 if testosterone_value <= 50 else 0
    if _is_present(values.get("seizure_history")) and not _is_present(values.get("comorbidity_seizure")):
        values["comorbidity_seizure"] = values.get("seizure_history")
    if _is_present(values.get("cv_risk_documented")) and not _is_present(values.get("comorbidity_cardio")):
        values["comorbidity_cardio"] = values.get("cv_risk_documented")
    if not _is_present(values.get("progression_pattern")):
        disease_status = str(latest_followup.get("disease_status") or "").lower()
        if "radiograf" in disease_status:
            values["progression_pattern"] = "radiographic"
        elif "clinic" in disease_status:
            values["progression_pattern"] = "clinical"
        elif any(token in disease_status for token in ("bioqu", "psa", "ascen", "progres")):
            values["progression_pattern"] = "biochemical_only"
    return values


def _resolve_current_psa(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
    current_values: dict[str, Any] | None = None,
) -> tuple[float | None, str]:
    values = dict(current_values or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_assessment_record = latest_assessment or patient.get("latest_assessment") or {}
    latest_inputs = dict(latest_assessment_record.get("input_snapshot") or {})
    state_hint = str(
        values.get("state")
        or latest_assessment_record.get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or ""
    )
    has_postlocal_context = state_hint in POSTLOCAL_STATES or bool(patient.get("bcr")) or bool(patient.get("surgery"))

    if has_postlocal_context:
        post_rp_truth = derive_post_prostatectomy_truth(patient)
        psa_points = list(post_rp_truth.get("psa_points") or [])
        if psa_points:
            latest_point = psa_points[-1]
            value = _safe_float(latest_point.get("value"))
            if value is not None:
                return value, str(latest_point.get("sample_date") or "")
        value = _safe_float(
            _first_nonempty(
                values.get("psa_current"),
                values.get("psa_postop"),
                latest_inputs.get("psa_current"),
                latest_inputs.get("psa_postop"),
                latest_followup.get("psa_current"),
                latest_followup.get("psa_postop"),
                (patient.get("bcr") or {}).get("bcr_psa"),
            )
        )
        if value is not None:
            return value, str(
                _first_nonempty(
                    latest_followup.get("visit_date"),
                    latest_assessment_record.get("assessment_date"),
                    (patient.get("bcr") or {}).get("bcr_date"),
                )
                or ""
            )

    value = _safe_float(
        _first_nonempty(
            values.get("psa_current"),
            latest_inputs.get("psa_current"),
            latest_followup.get("psa_current"),
            latest_followup.get("psa"),
            values.get("psa"),
            latest_inputs.get("psa"),
            (patient.get("bcr") or {}).get("bcr_psa"),
            (patient.get("baseline") or {}).get("baseline_psa"),
        )
    )
    return value, str(
        _first_nonempty(
            latest_followup.get("visit_date"),
            latest_assessment_record.get("assessment_date"),
            (patient.get("bcr") or {}).get("bcr_date"),
            patient.get("identity", {}).get("diagnosis_date"),
        )
        or ""
    )


def _current_state(patient: dict[str, Any], latest_assessment: dict[str, Any] | None) -> str:
    return (
        (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )


def _proposal_recommendation_family(base_family: str, proposal: dict[str, Any]) -> str:
    target_track = str(proposal.get("target_management_track") or "").strip()
    target_state = str(proposal.get("target_state") or "").strip()
    return (
        MANAGEMENT_TRACK_LABELS.get(target_track)
        or (target_track.replace("_", " ").title() if target_track else "")
        or (target_state.replace("_", " ").upper() if target_state else "")
        or base_family
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))


def build_transition_resolution(
    patient: dict[str, Any],
    signals: dict[str, Any],
    proposals: list[dict[str, Any]],
    *,
    decision_input_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirements = dict(decision_input_requirements or {})
    hard_blockers = [str(item) for item in list(requirements.get("hard_blocking_inputs") or []) if str(item or "").strip()]
    open_proposals = [dict(item) for item in list(proposals or []) if item]
    if not open_proposals:
        return {
            "available": False,
            "policy": "insufficient_evidence",
            "reason": "No existe una transición longitudinal abierta que resolver.",
            "target_state": signals.get("reconciled_state") or signals.get("state") or "",
            "target_management_track": signals.get("reconciled_management_track") or signals.get("management_track") or "",
            "manual_confirmation_required": False,
            "proposal_key": "",
            "decisive_fields": [],
            "hard_blocking_inputs_at_resolution": hard_blockers,
        }

    ranked = sorted(
        open_proposals,
        key=lambda item: (0 if str(item.get("priority") or "") == "high" else 1, str(item.get("proposal_key") or "")),
    )
    dominant = ranked[0]
    dominant_target = (
        str(dominant.get("target_state") or ""),
        str(dominant.get("target_management_track") or ""),
    )
    equally_dominant = [
        item
        for item in ranked
        if str(item.get("priority") or "") == str(dominant.get("priority") or "")
        and (
            str(item.get("target_state") or ""),
            str(item.get("target_management_track") or ""),
        ) != dominant_target
    ]
    rationale = str(dominant.get("rationale") or "")
    depends_on_external_document = any(
        needle in rationale.lower()
        for needle in ("verificable", "verificado", "documento", "documental")
    )
    if not hard_blockers and not equally_dominant and not depends_on_external_document:
        return {
            "available": True,
            "policy": "auto_applied",
            "reason": rationale or "La transición longitudinal es clínicamente dominante y no tiene hard blockers pendientes.",
            "target_state": dominant_target[0] or signals.get("reconciled_state") or signals.get("state") or "",
            "target_management_track": dominant_target[1] or signals.get("reconciled_management_track") or signals.get("management_track") or "",
            "manual_confirmation_required": False,
            "proposal_key": str(dominant.get("proposal_key") or ""),
            "decisive_fields": list((patient.get("latest_clinically_decisive_visit") or {}).get("changed_fields") or []),
            "hard_blocking_inputs_at_resolution": hard_blockers,
        }
    return {
        "available": True,
        "policy": "manual_confirmation_required" if equally_dominant or depends_on_external_document else "insufficient_evidence",
        "reason": rationale or "La transición todavía requiere confirmación clínica.",
        "target_state": dominant_target[0] or signals.get("reconciled_state") or signals.get("state") or "",
        "target_management_track": dominant_target[1] or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        "manual_confirmation_required": True,
        "proposal_key": str(dominant.get("proposal_key") or ""),
        "decisive_fields": list((patient.get("latest_clinically_decisive_visit") or {}).get("changed_fields") or []),
        "hard_blocking_inputs_at_resolution": hard_blockers,
    }


def build_care_intent_contract(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    next_best_action: dict[str, Any],
    signals: dict[str, Any],
    transition_resolution: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    palliative_transition_bundle: dict[str, Any] | None = None,
    survivorship_transition_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transition_resolution = dict(transition_resolution or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    palliative_transition_bundle = dict(palliative_transition_bundle or {})
    survivorship_transition_bundle = dict(survivorship_transition_bundle or {})
    recommendation_family = str(next_best_action.get("recommendation_family") or "").strip()
    if management_track and recommendation_family in {"", state}:
        recommendation_family = management_track
    if not recommendation_family:
        recommendation_family = str(management_track or state)
    headline = str(next_best_action.get("title") or "Sin siguiente acción prioritaria")
    rationale = str(next_best_action.get("rationale") or "")
    intent_key = f"{state}:{management_track}:{headline}".lower().replace(" ", "_")
    schedule_template_key = f"{state}:{management_track}"
    if state == "post_prostatectomy" and derive_post_prostatectomy_course(patient) == "persistent_psa":
        intent_key = "post_prostatectomy:persistent_psa_salvage_evaluation"
        schedule_template_key = "post_prostatectomy:salvage_evaluation"
    palliative_trigger_status = str(palliative_transition_bundle.get("trigger_status") or "")
    palliative_care_mode = str(palliative_transition_bundle.get("care_mode") or "")
    palliative_active = bool(palliative_transition_bundle.get("available")) and palliative_trigger_status not in {"", "observe"}
    if palliative_active:
        palliative_titles = {
            "concurrent_support": "Integrar cuidados paliativos concurrentes",
            "intensify_symptom_control": "Intensificar control sintomático y soporte paliativo",
            "urgent_local_palliation": "Activar paliación local urgente y control sintomático",
            "redirect_supportive_only": "Redirigir a soporte exclusivo y control sintomático",
            "hospice_candidate": "Activar ruta hospice y objetivos de cuidado",
        }
        recommendation_family = palliative_care_mode or recommendation_family
        headline = palliative_titles.get(palliative_trigger_status, headline or "Integrar soporte paliativo longitudinal")
        trigger_reasons = list(palliative_transition_bundle.get("trigger_reasons") or [])
        interventions = list(palliative_transition_bundle.get("recommended_interventions") or [])
        referrals = list(palliative_transition_bundle.get("recommended_referrals") or [])
        hospice_note = str((palliative_transition_bundle.get("hospice_eligibility") or {}).get("recommendation") or "").strip()
        rationale_parts = []
        if trigger_reasons:
            rationale_parts.append("Motivo: " + " · ".join(trigger_reasons[:3]))
        if interventions:
            rationale_parts.append("Intervenciones sugeridas: " + " · ".join(interventions[:3]))
        if referrals:
            rationale_parts.append("Referencias: " + " · ".join(str(item) for item in referrals[:3]))
        if hospice_note:
            rationale_parts.append(hospice_note)
        rationale = " ".join(part for part in rationale_parts if part).strip() or rationale
        intent_key = f"{state}:{palliative_care_mode or management_track}:{palliative_trigger_status}".lower().replace(" ", "_")
        schedule_template_key = f"{state}:{palliative_care_mode or management_track}"
    survivorship_trigger_status = str(survivorship_transition_bundle.get("trigger_status") or "")
    survivorship_track = str(survivorship_transition_bundle.get("survivorship_track") or "")
    survivorship_active = bool(survivorship_transition_bundle.get("available")) and survivorship_trigger_status not in {"", "observe"}
    survivorship_override_tracks = {"post_rp", "post_rt", "survivorship_followup", "toxicity_recovery", "late_effect_intervention"}
    survivorship_dominant = (
        survivorship_active
        and not palliative_active
        and (
            str(management_track or "").strip() in survivorship_override_tracks
            or str(state or "").strip() == "survivorship_and_toxicity_followup"
        )
    )
    if survivorship_dominant:
        survivorship_titles = {
            "monitor_recovery": "Monitorizar recuperación y survivorship",
            "intensify_toxicity_management": "Intensificar manejo de toxicidad tardía",
            "refer_rehabilitation": "Activar rehabilitación y recuperación funcional",
            "refer_specialist": "Referir secuela dominante a especialista",
            "reenter_oncologic_decision": "Reabrir decisión oncológica desde survivorship",
        }
        recommendation_family = survivorship_track or recommendation_family
        headline = survivorship_titles.get(
            survivorship_trigger_status,
            survivorship_transition_bundle.get("survivorship_track_label") or headline,
        )
        rationale_parts = []
        trigger_reasons = list(survivorship_transition_bundle.get("trigger_reasons") or [])
        active_alerts_survivorship = list(survivorship_transition_bundle.get("active_late_effect_alerts") or [])
        referrals = list(survivorship_transition_bundle.get("recommended_referrals") or [])
        interventions = list(survivorship_transition_bundle.get("recommended_interventions") or [])
        if trigger_reasons:
            rationale_parts.append("Motivo: " + " · ".join(trigger_reasons[:3]))
        if active_alerts_survivorship:
            rationale_parts.append("Alertas: " + " · ".join(active_alerts_survivorship[:3]))
        if interventions:
            rationale_parts.append("Intervenciones: " + " · ".join(interventions[:3]))
        if referrals:
            rationale_parts.append("Referencias: " + " · ".join(str(item) for item in referrals[:3]))
        rationale = " ".join(part for part in rationale_parts if part).strip() or rationale
        intent_key = f"{state}:{survivorship_track or management_track}:{survivorship_trigger_status}".lower().replace(" ", "_")
        schedule_template_key = f"{state}:{survivorship_track or management_track}"
    active_alerts = list(dict.fromkeys(list(signals.get("active_safety") or []) + list(palliative_transition_bundle.get("acute_palliative_alerts") or [])))
    if survivorship_dominant:
        active_alerts = list(
            dict.fromkeys(active_alerts + list(survivorship_transition_bundle.get("active_late_effect_alerts") or []))
        )
    survivorship_blocking_inputs = (
        list(survivorship_transition_bundle.get("missing_inputs") or [])
        if survivorship_dominant or survivorship_trigger_status == "reenter_oncologic_decision"
        else []
    )
    blocking_inputs = list(
        dict.fromkeys(
            list(decision_input_requirements.get("blocking_inputs") or [])
            + list(palliative_transition_bundle.get("missing_inputs") or [])
            + survivorship_blocking_inputs
        )
    )
    supportive_priority = str(palliative_transition_bundle.get("supportive_priority") or "background")
    care_goal = str(palliative_transition_bundle.get("care_goal") or "")
    recommended_supportive_referrals = list(palliative_transition_bundle.get("recommended_referrals") or [])
    if survivorship_dominant:
        supportive_priority = "visible"
        care_goal = (
            "Recuperación funcional, intervención de secuelas tardías y prevención secundaria"
        )
        recommended_supportive_referrals = list(survivorship_transition_bundle.get("recommended_referrals") or [])
    return {
        "intent_key": intent_key,
        "headline": headline,
        "narrative": rationale,
        "recommendation_family": recommendation_family,
        "urgency": "high" if transition_resolution.get("policy") == "auto_applied" or active_alerts or supportive_priority == "dominant" else "routine",
        "schedule_template_key": schedule_template_key,
        "blocking_inputs": blocking_inputs,
        "guideline_basis": list(next_best_action.get("evidence_basis") or COMMON_EVIDENCE),
        "active_alerts": active_alerts,
        "cadence_summary": str((patient.get("guideline_followup_plan") or {}).get("baseline_guideline_plan", {}).get("cadence_summary") or ""),
        "transition_resolution": transition_resolution,
        "care_goal": care_goal,
        "supportive_priority": supportive_priority,
        "palliative_trigger_status": palliative_trigger_status,
        "survivorship_trigger_status": survivorship_trigger_status,
        "survivorship_track": survivorship_track,
        "recommended_supportive_referrals": recommended_supportive_referrals,
        "acute_palliative_alerts": list(palliative_transition_bundle.get("acute_palliative_alerts") or []),
        "palliative_transition_bundle": palliative_transition_bundle,
        "survivorship_transition_bundle": survivorship_transition_bundle,
    }


def _align_next_best_action_with_care_intent(
    next_best_action: dict[str, Any],
    care_intent_contract: dict[str, Any],
    decision_input_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aligned = dict(next_best_action or {})
    care_intent_contract = dict(care_intent_contract or {})
    requirements = dict(decision_input_requirements or {})
    if not care_intent_contract:
        return aligned
    aligned["title"] = str(care_intent_contract.get("headline") or aligned.get("title") or "Sin siguiente acción prioritaria")
    aligned["rationale"] = str(care_intent_contract.get("narrative") or aligned.get("rationale") or "")
    aligned["recommendation_family"] = str(
        care_intent_contract.get("recommendation_family")
        or aligned.get("recommendation_family")
        or ""
    )
    aligned["care_goal"] = str(care_intent_contract.get("care_goal") or aligned.get("care_goal") or "")
    aligned["supportive_priority"] = str(care_intent_contract.get("supportive_priority") or aligned.get("supportive_priority") or "")
    aligned["palliative_trigger_status"] = str(
        care_intent_contract.get("palliative_trigger_status")
        or aligned.get("palliative_trigger_status")
        or ""
    )
    if care_intent_contract.get("recommended_supportive_referrals"):
        aligned["recommended_supportive_referrals"] = list(care_intent_contract.get("recommended_supportive_referrals") or [])
    if care_intent_contract.get("acute_palliative_alerts"):
        aligned["acute_palliative_alerts"] = list(care_intent_contract.get("acute_palliative_alerts") or [])
    if care_intent_contract.get("guideline_basis"):
        aligned["evidence_basis"] = list(care_intent_contract.get("guideline_basis") or [])
    blocking_inputs = list(requirements.get("blocking_inputs") or [])
    if blocking_inputs:
        aligned["data_that_could_change_course"] = blocking_inputs
    transition = dict(care_intent_contract.get("transition_resolution") or {})
    if transition.get("policy") == "auto_applied":
        immediate_actions = [
            str(aligned.get("title") or "").strip(),
            "Usar la agenda recalculada y la evidencia vigente del estado efectivo",
        ]
        aligned["immediate_actions"] = [item for item in immediate_actions if item]
    return aligned


def resolve_followup_runtime_context(
    patient: dict[str, Any],
    *,
    state: str,
    management_track: str,
    latest_assessment: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    transition_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reconciliation = build_reconciled_state(patient, latest_assessment)
    base_state = state or reconciliation.get("reconciled_state") or _current_state(patient, latest_assessment)
    base_track = management_track or reconciliation.get("reconciled_management_track") or infer_management_track(
        patient,
        base_state,
        latest_assessment or patient.get("latest_assessment"),
    )
    if reconciliation.get("state_conflict_flag") and reconciliation.get("state_conflict_reason"):
        return {
            "state": base_state,
            "management_track": base_track,
            "override_reason": str(reconciliation.get("state_conflict_reason") or ""),
            "proposal": {},
        }
    effective_signals = dict(signals or {})
    if not effective_signals:
        effective_signals.update(
            {
                "state": base_state,
                "management_track": base_track,
                "reconciled_state": reconciliation.get("reconciled_state") or base_state,
                "reconciled_management_track": reconciliation.get("reconciled_management_track") or base_track,
                "state_conflict_flag": reconciliation.get("state_conflict_flag"),
                "state_conflict_reason": reconciliation.get("state_conflict_reason"),
            }
        )
    resolution = dict(transition_resolution or {})
    if resolution.get("policy") == "auto_applied":
        target_state = str(resolution.get("target_state") or "")
        target_track = str(resolution.get("target_management_track") or "")
        if target_state:
            return {
                "state": target_state,
                "management_track": target_track or base_track,
                "override_reason": str(resolution.get("reason") or ""),
                "proposal": {},
            }
    return {
        "state": base_state,
        "management_track": base_track,
        "override_reason": "",
        "proposal": {},
    }


def _biopsy_confirms_cancer(patient: dict[str, Any]) -> bool:
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    return any(
        _is_present(latest_biopsy.get(field))
        for field in ("gleason_primary", "gleason_secondary", "isup_grade", "positive_cores")
    ) and (_safe_int(latest_biopsy.get("positive_cores")) or 0) > 0


def _derive_current_treatment(patient: dict[str, Any]) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    if _is_present(truth_values.get("current_treatment")):
        return str(truth_values.get("current_treatment"))
    if _is_present(truth_values.get("drug_scheme")):
        return str(truth_values.get("drug_scheme"))
    treatments = patient.get("treatments") or []
    if treatments:
        current = treatments[-1]
        regimen = current.get("regimen_json")
        if isinstance(regimen, dict) and regimen.get("summary"):
            return str(regimen["summary"])
        if isinstance(regimen, str) and regimen.strip():
            return regimen
        if current.get("drug_scheme"):
            return str(current.get("drug_scheme"))
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    return str(followup.get("current_treatment") or "")


def _state_module_result(
    patient: dict[str, Any],
    state: str,
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    module_id = state
    registry = ModuleRegistry()
    try:
        schema = registry.get_module_schema(module_id)
    except KeyError:
        return {}

    merged_payload = merge_record_into_assessment_payload(
        dict((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {}),
        patient,
    )
    merged_payload.update(_current_field_values(patient, latest_assessment))
    payload: dict[str, Any] = {}
    for field in list(schema.get("fields") or []):
        name = str(field.get("name") or "")
        if not name:
            continue
        if _is_present(merged_payload.get(name)):
            payload[name] = merged_payload.get(name)
    try:
        return registry.evaluate_module(module_id, payload) if payload else {}
    except Exception:
        return {}


def _resolve_runtime_regimen_contracts(
    patient: dict[str, Any],
    state: str,
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    module_result = _state_module_result(patient, state, latest_assessment)
    field_values = _current_field_values(patient, latest_assessment)
    preferred_regimen = dict(module_result.get("preferred_frontline_regimen") or {})
    eligible_treatments = list(module_result.get("eligible_treatments") or [])
    if not preferred_regimen and eligible_treatments:
        preferred_regimen = dict(eligible_treatments[0])
    active_regimen_code = str(
        preferred_regimen.get("regimen_code")
        or field_values.get("drug_scheme")
        or field_values.get("current_treatment")
        or ""
    )
    active_family = str(
        preferred_regimen.get("family_code")
        or regimen_family_code(active_regimen_code, fallback="observation_family")
    )
    monitoring_package = build_active_regimen_monitoring_package(
        active_regimen_code,
        family_code=active_family,
        field_values=field_values,
    )
    sequence_bundle = build_sequence_transition_bundle(
        state=state,
        preferred_regimen=preferred_regimen,
        eligible_treatments=eligible_treatments,
        current_treatment=field_values.get("drug_scheme") or field_values.get("current_treatment") or "",
        missing_critical_inputs=list(module_result.get("missing_critical_inputs") or []),
        progression_pattern=str(field_values.get("progression_pattern") or ""),
        line_context=str(
            field_values.get("line_of_therapy_context")
            or field_values.get("mcrpc_line_context")
            or field_values.get("line_context")
            or ""
        ),
        field_values=field_values,
        monitoring_package=monitoring_package,
        comparative_eligibility_matrix=dict(module_result.get("comparative_eligibility_matrix") or {}),
    )
    return {
        "module_result": module_result,
        "preferred_regimen": preferred_regimen,
        "eligible_treatments": eligible_treatments,
        "active_regimen_monitoring_package": monitoring_package,
        "sequence_transition_bundle": sequence_bundle,
        "comparative_eligibility_matrix": dict(module_result.get("comparative_eligibility_matrix") or {}),
    }


def _derive_metastatic_context(patient: dict[str, Any]) -> tuple[str, int]:
    baseline = patient.get("baseline") or {}
    metastasis_site, metastasis_count, _ = derive_legacy_metastasis(baseline)
    psma_profile = patient.get("psma_structured_profile") or {}
    if psma_profile.get("available") and psma_profile.get("clinical_pattern") != "negative":
        psma_stage = str(psma_profile.get("psma_stage_after_psma") or "")
        lesion_count = _safe_int(psma_profile.get("psma_total_lesions")) or 0
        metastasis_count = max(metastasis_count, lesion_count)
        if psma_stage == "M1a":
            metastasis_site = "Node"
        elif psma_stage == "M1b":
            metastasis_site = "Bone"
        elif psma_stage == "M1c":
            metastasis_site = "Visceral"
    imaging = patient.get("imaging") or []
    for study in imaging:
        study_type = str(study.get("study_type", "")).lower()
        findings = study.get("findings", {}) if isinstance(study.get("findings"), dict) else {}
        if "psma" in study_type:
            locations = findings.get("lesion_locations", []) or []
            lesion_count = _safe_int(findings.get("psma_total_lesions")) or 0
            if locations or lesion_count:
                metastasis_count = max(metastasis_count, lesion_count or len(locations))
                lowered = " ".join(str(item).lower() for item in locations)
                if "hueso" in lowered:
                    metastasis_site = "Bone"
                elif "higado" in lowered or "pulm" in lowered or "visceral" in lowered:
                    metastasis_site = "Visceral"
                elif "ganglio" in lowered:
                    metastasis_site = "Node"
                else:
                    metastasis_site = "M1"
        if "gammagrama" in study_type:
            bone_lesions = _safe_int(study.get("bone_lesion_count")) or _safe_int((findings or {}).get("bone_lesion_count")) or 0
            if bone_lesions:
                metastasis_site = "Bone"
                metastasis_count = max(metastasis_count, bone_lesions)
        if "tac" in study_type:
            summary = str((findings or {}).get("ct_summary") or "")
            locations = (findings or {}).get("ct_locations", []) or []
            if summary == "Metástasis" or locations:
                metastasis_count = max(metastasis_count, len(locations) or 1)
                lowered = " ".join(str(item).lower() for item in locations)
                if "hueso" in lowered:
                    metastasis_site = "Bone"
                elif "ganglio" in lowered:
                    metastasis_site = "Node"
                else:
                    metastasis_site = "Visceral"
    return metastasis_site, metastasis_count


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(followup.get("disease_status") or "").lower()
    if "radiograf" in disease_status:
        return "radiographic"
    if "clinic" in disease_status:
        return "clinical"
    if "bioqu" in disease_status or "psa" in disease_status:
        return "biochemical_only"
    if state in {"m1_crpc"}:
        return "mixed"
    return "biochemical_only"


def _derive_current_adt_context(patient: dict[str, Any], state: str) -> str:
    treatment_text = _derive_current_treatment(patient).lower()
    if "orchiect" in treatment_text:
        return "orchiectomy"
    adt_tokens = ("leupro", "degarelix", "goserelin", "triptorelin", "relugolix", "castr")
    if any(token in treatment_text for token in adt_tokens):
        return "medical_adt_continuous"
    if state in ADVANCED_STATES | MHSPC_STATES:
        return "medical_adt_continuous"
    return "none"


def _derive_castrate_status(patient: dict[str, Any], state: str) -> str:
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_testosterone = _safe_float(followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float(patient.get("baseline", {}).get("testosterone_baseline"))
        if state in {"m0_crpc", "m1_crpc", "adt_progression_verification"} and latest_testosterone is not None:
            return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"
        return "unknown"
    return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"


def _derive_conventional_imaging_status(patient: dict[str, Any], state: str) -> str:
    imaging = patient.get("imaging") or []
    for study in imaging:
        study_type = str(study.get("study_type", "")).lower()
        findings = study.get("findings", {}) if isinstance(study.get("findings"), dict) else {}
        if "tac" in study_type:
            status = str(findings.get("conventional_imaging_status") or "")
            if status:
                return status.upper()
        if "gammagrama" in study_type and str(study.get("bone_scan_result", "")).lower().startswith("positivo"):
            return "M1"
    if state in {"m1_crpc"}:
        return "M1"
    if state in {"m0_crpc", "adt_progression_verification"}:
        return "M0"
    return "NOT_RESTAGED"


def _build_metastatic_signal_payload(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    truth_values: dict[str, Any],
    latest_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(patient.get("baseline") or {})
    latest_snapshot = dict(latest_snapshot or patient.get("latest_signal_snapshot") or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_inputs = dict((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    for source in (truth_values, latest_inputs, latest_snapshot, latest_followup, stage_payload):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}):
                payload[key] = value
    psma_profile = patient.get("psma_structured_profile") or {}
    if isinstance(psma_profile, dict) and psma_profile.get("available"):
        overlay = {
            "psma_pet_done": "1",
            "psma_positive": "1" if psma_profile.get("psma_positive") else "0",
            "psma_result": psma_profile.get("psma_result"),
            "psma_radioligand": psma_profile.get("psma_radioligand"),
            "psma_rads_score": psma_profile.get("psma_rads_score"),
            "psma_uptake_pattern": psma_profile.get("psma_uptake_pattern"),
            "psma_stage_after_psma": psma_profile.get("psma_stage_after_psma"),
            "conventional_stage_before_psma": psma_profile.get("conventional_stage_before_psma"),
            "psma_study_date": psma_profile.get("study_date"),
        }
        for key, value in overlay.items():
            if value not in (None, "", [], {}) and payload.get(key) in (None, "", [], {}):
                payload[key] = value
        if payload.get("conventional_imaging_status") in (None, "", [], {}) and psma_profile.get("conventional_stage_before_psma"):
            payload["conventional_imaging_status"] = psma_profile.get("conventional_stage_before_psma")
    latest_psma = {}
    for study in patient.get("imaging") or []:
        if "psma" in str(study.get("study_type") or "").lower():
            latest_psma = dict(study)
            break
    if latest_psma:
        findings = latest_psma.get("findings") if isinstance(latest_psma.get("findings"), dict) else {}
        for key in (
            "psma_result",
            "psma_radioligand",
            "psma_rads_score",
            "psma_uptake_pattern",
            "conventional_stage_before_psma",
            "psma_stage_after_psma",
        ):
            value = latest_psma.get(key) or findings.get(key)
            if value not in (None, "", [], {}) and payload.get(key) in (None, "", [], {}):
                payload[key] = value
        if payload.get("psma_study_date") in (None, "", [], {}) and latest_psma.get("study_date"):
            payload["psma_study_date"] = latest_psma.get("study_date")
        if payload.get("psma_pet_done") in (None, "", [], {}):
            payload["psma_pet_done"] = "1"
    return payload


def build_state_classifier_payload(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    reconciliation = build_reconciled_state(patient, latest_assessment)
    state = reconciliation.get("reconciled_state") or _current_state(patient, latest_assessment)
    phenotype_state = reconciliation.get("phenotype_state") or state
    current_values = _current_field_values(patient, latest_assessment)
    current_psa, _ = _resolve_current_psa(patient, latest_assessment, current_values)
    metastasis_site, metastasis_count = _derive_metastatic_context(patient)
    supporting_evidence = reconciliation.get("supporting_evidence", {})
    burden_payload = dict(current_values)
    burden_payload.setdefault("metastasis_site", metastasis_site)
    burden_payload.setdefault("metastasis_count", _safe_int(current_values.get("metastasis_count")) or metastasis_count)
    burden_context = derive_mhspc_burden_context(burden_payload)
    state_payload = {
        "known_cancer_diagnosis": 1 if supporting_evidence.get("confirmed_cancer") or state not in DIAGNOSTIC_STATES else 0,
        "prior_negative_biopsy": 1 if state == "post_negative_biopsy_followup" else 0,
        "prior_prostatectomy": 1 if current_values.get("prior_prostatectomy") else 0,
        "prior_radiation": 1 if current_values.get("prior_radiation") else 0,
        "bcr2": 1 if str((patient.get("bcr") or {}).get("bcr_definition", "")).upper() == "BCR2" else 0,
        "metastasis_site": metastasis_site,
        "metastasis_count": _safe_int(current_values.get("metastasis_count")) or metastasis_count,
        "volume_disease": current_values.get("volume_disease") or burden_context.get("volume_disease") or "low",
        "metachronous_metastasis": 1 if state in {"mcspc_oligo_metachronous", "mcspc_high_volume_metachronous"} else 0,
        "psa_current": current_psa if current_psa is not None else _safe_float((patient.get("baseline") or {}).get("baseline_psa")),
        "current_adt_context": current_values.get("current_adt_context") or _derive_current_adt_context(patient, state),
        "castrate_testosterone_status": current_values.get("castrate_testosterone_status") or _derive_castrate_status(patient, state),
        "progression_pattern": current_values.get("progression_pattern") or _derive_progression_pattern(patient, state),
        "conventional_imaging_status": current_values.get("conventional_imaging_status") or _derive_conventional_imaging_status(patient, state),
        "line_of_therapy": _safe_int(current_values.get("line_of_therapy_number") or current_values.get("line_of_therapy")) or ((patient.get("treatments") or [{}])[-1].get("line_of_therapy", 1) if patient.get("treatments") else 1),
        "phenotype_state": phenotype_state,
        "progression_gate_active": 1 if reconciliation.get("progression_gate_active") else 0,
        "progression_gate_target": reconciliation.get("progression_gate_target") or "",
        "progression_gate_reason": reconciliation.get("progression_gate_reason") or "",
    }
    explicit_context = (
        current_values.get("systemic_progression_context")
        or reconciliation.get("systemic_progression_context_resolved")
        or ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {}).get("systemic_progression_context")
        or _latest(patient.get("follow_ups", []), "visit_date").get("systemic_progression_context")
    )
    state_payload["systemic_progression_context"] = resolve_systemic_progression_context(
        explicit_context,
        legacy_crpc_signal=state in {"m0_crpc", "m1_crpc"},
        line_of_therapy=state_payload.get("line_of_therapy"),
    )
    state_payload["systemic_progression_context_resolved"] = (
        reconciliation.get("systemic_progression_context_resolved")
        or state_payload["systemic_progression_context"]
    )
    return state_payload


def _build_mcode_projection(patient: dict[str, Any], state: str, management_track: str) -> dict[str, Any]:
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    genomics = patient.get("genomics") or {}
    return {
        "condition": {
            "primary_diagnosis": state,
            "management_track": management_track,
            "stage": (patient.get("prior_history") or {}).get("current_state") or state,
        },
        "disease_status": latest_followup.get("disease_status") or "Seguimiento estable",
        "biomarkers": {
            "hrr_status": genomics.get("hrr_overall"),
            "brca2_status": genomics.get("brca2_status"),
            "msi_status": genomics.get("msi_status"),
            "decipher_risk": genomics.get("decipher_risk"),
        },
        "procedures": {
            "biopsies": len(patient.get("biopsies") or []),
            "imaging_studies": len(patient.get("imaging") or []),
            "surgery": bool(patient.get("surgery")),
            "radiation_courses": len(patient.get("radiation") or []),
        },
        "medications": {
            "current_treatment": _derive_current_treatment(patient),
            "prior_lines": len(patient.get("treatments") or []),
        },
        "provenance": {
            "items": len(patient.get("data_provenance") or []),
        },
    }


def build_clinical_signals(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    truth_snapshot = patient.get("longitudinal_truth_snapshot") or build_longitudinal_truth_snapshot(patient, latest_assessment)
    truth_values = truth_snapshot.get("field_values") or {}
    reconciliation = build_reconciled_state(patient, latest_assessment)
    explicit_state = reconciliation.get("explicit_state") or _current_state(patient, latest_assessment)
    state = reconciliation.get("reconciled_state") or explicit_state
    management_track = reconciliation.get("reconciled_management_track") or infer_management_track(patient, state, latest_assessment or patient.get("latest_assessment"))
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    latest_mri = _latest(patient.get("mri_facts", []), "fact_date")
    latest_imaging = _latest(patient.get("imaging", []), "study_date")
    metastatic_payload = _build_metastatic_signal_payload(patient, latest_assessment, truth_values)
    metastatic_state_context = resolve_metastatic_state_context(metastatic_payload)
    metastatic_stage_resolved = str(metastatic_state_context.get("metastatic_stage_resolved") or "M0")
    metastatic_detection_basis = str(metastatic_state_context.get("metastatic_detection_basis") or "unknown")
    psma_only_upstaging = bool(
        metastatic_detection_basis == "psma_only"
        and metastatic_stage_resolved not in {"", "M0"}
    )
    nmcrpc_eligible = bool(
        state == "m0_crpc"
        and metastatic_stage_resolved == "M0"
        and str(metastatic_payload.get("conventional_imaging_status") or "").upper() in {"", "M0", "NOT_RESTAGED"}
    )
    nmcrpc_ineligibility_reason = ""
    if metastatic_stage_resolved != "M0":
        nmcrpc_ineligibility_reason = (
            f"M1 documentado ({metastatic_stage_resolved}) por {metastatic_detection_basis}; "
            "no corresponde liberar carril nmCRPC."
        )
    bcr = patient.get("bcr") or {}
    signals = []
    critical_missing = []
    awaiting_review = []
    active_safety = []

    psa, _ = _resolve_current_psa(patient, latest_assessment, truth_values)
    testosterone = _safe_float(truth_values.get("testosterone"))
    ecog = _safe_int(truth_values.get("ecog"))
    pain = _safe_int(truth_values.get("pain"))
    latest_mri_quality = latest_mri.get("mpmri_quality")
    pirads = latest_mri.get("pirads_score") or latest_imaging.get("pirads_score")
    psadt = _safe_float(bcr.get("psadt_at_bcr")) or _safe_float((latest_assessment or {}).get("input_snapshot", {}).get("psadt_months"))
    verified_document_types = {
        str(item.get("document_type") or "")
        for item in (patient.get("source_documents") or [])
        if str(item.get("verification_status") or "") == "verified"
    }

    if _is_present(psa):
        signals.append(
            {
                "key": "psa",
                "label": "PSA actual",
                "value": f"{psa:.2f} ng/mL",
                "status": "informative",
                "detail": "Último antígeno prostático específico disponible en el longitudinal.",
            }
        )
    if _is_present(testosterone) and state in ADVANCED_STATES | MHSPC_STATES:
        signals.append(
            {
                "key": "testosterone",
                "label": "Testosterona",
                "value": f"{testosterone:.1f} ng/dL",
                "status": "good" if testosterone <= 50 else "warning",
                "detail": "La enfermedad resistente a la castración requiere testosterona en rango de castración.",
            }
        )
    if reconciliation.get("progression_gate_active"):
        signals.append(
            {
                "key": "systemic_progression_gate",
                "label": "Gate de progresión bajo ADT activo",
                "value": reconciliation.get("phenotype_state") or state,
                "status": "warning",
                "detail": reconciliation.get("progression_gate_reason") or "Falta cerrar testosterona en rango de castración y/o la reestadificación suficiente.",
            }
        )

    if state in DIAGNOSTIC_STATES:
        if not _is_present(latest_mri_quality):
            critical_missing.append("Resonancia magnética multiparamétrica utilizable")
        if not _is_present(psa):
            critical_missing.append("PSA o densidad de PSA actual")
        if patient.get("biopsy_triggers") and not patient.get("biopsies"):
            awaiting_review.append("Existe trigger de biopsia activo sin histología confirmada")
        if _safe_int(pirads) is not None and _safe_int(pirads) >= 4:
            signals.append(
                {
                    "key": "pirads_high",
                    "label": "PI-RADS alto",
                    "value": f"PI-RADS {pirads}",
                    "status": "warning",
                    "detail": "El hallazgo radiológico exige ruta diagnóstica acelerada y confirmación histológica.",
                }
            )

    if state == "localized_initial":
        if management_track == "active_surveillance" and not patient.get("pros"):
            critical_missing.append("PROs basales/seriales para vigilancia activa")
        if management_track == "active_surveillance" and not patient.get("biopsies"):
            critical_missing.append("Biopsia confirmatoria o seguimiento histológico")
        if patient.get("biopsies") and "pathology_report" not in verified_document_types:
            critical_missing.append("Reporte histopatológico completo verificable")
        if latest_biopsy:
            adverse_variant = str(latest_biopsy.get("adverse_histology_variant_type") or "none")
            if adverse_variant not in {"", "none"}:
                awaiting_review.append("Histología adversa tipificada requiere revisión de manejo local")
            if _safe_int(latest_biopsy.get("isup_grade")) and _safe_int(latest_biopsy.get("isup_grade")) >= 2:
                signals.append(
                    {
                        "key": "histologic_progression",
                        "label": "Progresión histológica",
                        "value": f"ISUP {latest_biopsy.get('isup_grade')}",
                        "status": "warning",
                        "detail": "La progresión histológica puede obligar salida de vigilancia activa.",
                    }
                )

    if state in POSTLOCAL_STATES:
        if not _is_present(psa):
            critical_missing.append("PSA ultrasensible actual")
        if patient.get("biopsies") and "pathology_report" not in verified_document_types:
            critical_missing.append("Reporte histopatológico completo verificable")
        if state == "post_prostatectomy" and psa is not None and psa >= 0.2:
            signals.append(
                {
                    "key": "possible_bcr",
                    "label": "Señal de recurrencia bioquímica",
                    "value": f"PSA {psa:.2f} ng/mL",
                    "status": "warning",
                    "detail": "La elevación posoperatoria sugiere reestadificación y evaluación de rescate.",
                }
            )
        if state == "recurrence_bcr":
            if not _is_present(psadt):
                critical_missing.append("Tiempo de duplicación del PSA (PSADT)")
            if not patient.get("imaging"):
                awaiting_review.append("No existe imagen estructurada para decidir rescate o transición")

    if state in ADVANCED_STATES | MHSPC_STATES:
        if _derive_castrate_status(patient, state) == "unknown":
            critical_missing.append("Testosterona actual para contexto avanzado")
        if not patient.get("genomics"):
            critical_missing.append("Biomarcadores accionables documentados")
        if "genomic_report" not in verified_document_types:
            critical_missing.append("Resultado molecular verificable para PARP / biomarcadores")
        if ecog is not None and ecog >= 2:
            active_safety.append("Estado funcional comprometido; ajustar intensidad terapéutica")
        if pain is not None and pain >= 7:
            active_safety.append("Dolor significativo; integrar cuidados paliativos concurrentes")
        if str(truth_values.get("hepatic_risk_status") or latest_followup.get("hepatic_risk_status") or latest_followup.get("hepatic_risk_factors") or "").strip():
            active_safety.append("Riesgo hepático activo")
        if str(latest_followup.get("cv_risk_status") or "").strip():
            active_safety.append("Riesgo cardiovascular activo")
        if _safe_int(latest_followup.get("seizure_history")) == 1:
            active_safety.append("Antecedente convulsivo relevante para selección de ARPI")
        if _safe_int(latest_followup.get("dermatitis_history")) == 1:
            active_safety.append("Dermatitis/rash previo relevante para selección de ARPI")
        if management_track == "on_lu177" and not patient.get("imaging"):
            critical_missing.append("PSMA-PET válido para sostener elegibilidad a Lutecio-177")
        elif any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or [])) and "imaging_report" not in verified_document_types:
            critical_missing.append("Informe PSMA-PET verificable")

    lab_profile = build_laboratory_intelligence_profile(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
    )
    for alert in lab_profile.get("active_alerts", []):
        detail = str(alert.get("title") or "")
        if detail and detail not in active_safety:
            active_safety.append(detail)
        signals.append(
            {
                "key": f"lab_{alert.get('key')}",
                "label": alert.get("title") or "Alerta de laboratorio",
                "value": alert.get("triggering_value") or "",
                "status": "warning" if str(alert.get("severity")) == "warning" else "critical" if str(alert.get("severity")) == "critical" else "informative",
                "detail": alert.get("message") or "",
            }
        )

    palliative_transition_bundle = build_palliative_transition_bundle(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
        field_values=truth_values,
    )
    survivorship_transition_bundle = build_survivorship_transition_bundle(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=latest_assessment,
        field_values=truth_values,
    )
    if palliative_transition_bundle.get("available") and palliative_transition_bundle.get("trigger_status") not in {"", "observe"}:
        detail = " · ".join(list(palliative_transition_bundle.get("trigger_reasons") or [])[:3]) or "Se requiere integración paliativa longitudinal."
        signals.append(
            {
                "key": "palliative_lane",
                "label": "Carril paliativo",
                "value": palliative_transition_bundle.get("care_mode_label") or palliative_transition_bundle.get("care_mode") or "",
                "status": "critical" if str(palliative_transition_bundle.get("supportive_priority") or "") == "dominant" else "warning",
                "detail": detail,
            }
        )
        for alert in list(palliative_transition_bundle.get("acute_palliative_alerts") or []):
            if alert not in active_safety:
                active_safety.append(alert)
        care_goal = str(palliative_transition_bundle.get("care_goal") or "").strip()
        if care_goal:
            care_goal_alert = f"Objetivo de cuidado dominante: {care_goal}"
            if care_goal_alert not in active_safety:
                active_safety.append(care_goal_alert)
    if survivorship_transition_bundle.get("available") and survivorship_transition_bundle.get("trigger_status") not in {"", "observe"}:
        detail = " · ".join(list(survivorship_transition_bundle.get("trigger_reasons") or [])[:3]) or "Se requiere manejo estructurado de survivorship."
        signals.append(
            {
                "key": "survivorship_lane",
                "label": "Carril de survivorship",
                "value": survivorship_transition_bundle.get("survivorship_track_label") or survivorship_transition_bundle.get("survivorship_track") or "",
                "status": "warning" if str(survivorship_transition_bundle.get("trigger_status") or "") != "reenter_oncologic_decision" else "critical",
                "detail": detail,
            }
        )
        for alert in list(survivorship_transition_bundle.get("active_late_effect_alerts") or []):
            if alert not in active_safety:
                active_safety.append(alert)

    ready_to_restage = (
        bool(awaiting_review)
        or bool(metastatic_state_context.get("restaging_update_required"))
        or any(item.get("status") == "warning" for item in signals if item.get("key") in {"possible_bcr", "histologic_progression"})
    )
    return ClinicalSignalSet(
        state=state,
        management_track=management_track,
        ready_to_restage=ready_to_restage,
        signals=signals,
        critical_missing=critical_missing,
        awaiting_review=awaiting_review,
        active_safety=active_safety,
        mcode_projection=_build_mcode_projection(patient, state, management_track),
        evidence_basis=COMMON_EVIDENCE,
    ).to_dict() | {
        "explicit_state": explicit_state,
        "reconciled_state": state,
        "phenotype_state": reconciliation.get("phenotype_state", state),
        "reconciled_management_track": management_track,
        "state_conflict_flag": bool(reconciliation.get("state_conflict_flag")),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "progression_gate_active": bool(reconciliation.get("progression_gate_active")),
        "progression_gate_target": reconciliation.get("progression_gate_target", ""),
        "progression_gate_reason": reconciliation.get("progression_gate_reason", ""),
        "systemic_progression_context_resolved": reconciliation.get("systemic_progression_context_resolved", "none"),
        "supporting_evidence": reconciliation.get("supporting_evidence", {}),
        "metastatic_state_bundle": metastatic_state_context,
        "metastatic_stage_resolved": metastatic_stage_resolved,
        "metastatic_stage_label": metastatic_state_context.get("metastatic_stage_label") or metastatic_stage_resolved,
        "m_substage_resolved": metastatic_stage_resolved,
        "metastatic_detection_basis": metastatic_detection_basis,
        "psma_only_upstaging": psma_only_upstaging,
        "nmcrpc_eligible": nmcrpc_eligible,
        "nmcrpc_ineligibility_reason": nmcrpc_ineligibility_reason,
        "restaging_update_required": bool(metastatic_state_context.get("restaging_update_required")),
        "restaging_currentness_status": metastatic_state_context.get("restaging_currentness_status", "unknown"),
        "restaging_update_reason": metastatic_state_context.get("restaging_update_reason", ""),
        "longitudinal_truth_snapshot": truth_snapshot,
        "latest_clinically_decisive_visit": truth_snapshot.get("latest_clinically_decisive_visit", {}),
        "laboratory_intelligence_summary": {
            "alert_count": len(lab_profile.get("active_alerts") or []),
            "series_count": len(lab_profile.get("series") or []),
            "coverage": lab_profile.get("coverage", {}),
        },
        "post_prostatectomy_course": derive_post_prostatectomy_course(patient),
        "palliative_transition_bundle": palliative_transition_bundle,
        "survivorship_transition_bundle": survivorship_transition_bundle,
    }


def build_state_transition_proposals(
    patient: dict[str, Any],
    signals: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    reconciliation = build_reconciled_state(patient, latest_assessment)
    explicit_state = reconciliation.get("explicit_state") or _current_state(patient, latest_assessment)
    current_state = signals.get("reconciled_state") or signals.get("state") or reconciliation.get("reconciled_state") or explicit_state
    current_track = signals.get("reconciled_management_track") or signals.get("management_track") or reconciliation.get("reconciled_management_track") or infer_management_track(patient, current_state, latest_assessment or patient.get("latest_assessment"))
    proposals: list[dict[str, Any]] = []
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    psa = _safe_float(latest_followup.get("psa_current")) or _safe_float((patient.get("bcr") or {}).get("bcr_psa"))
    registry = ModuleRegistry()
    classifier_payload = build_state_classifier_payload(patient, latest_assessment)
    classifier_target = registry.classify_state(classifier_payload).get("state")

    if reconciliation.get("state_conflict_flag") and current_state != explicit_state:
        proposals.append(
            StateTransitionProposal(
                proposal_key=f"{explicit_state}:{current_state}:reconciled",
                from_state=explicit_state,
                from_management_track=infer_management_track(patient, explicit_state, latest_assessment or patient.get("latest_assessment")),
                target_state=current_state,
                target_management_track=current_track,
                priority="high",
                rationale=reconciliation.get("state_conflict_reason") or "La evolución longitudinal contradice el estado persistido.",
                trigger_signals=(signals.get("critical_missing") or [])[:2] or ["Reconciliación longitudinal del estado"],
                next_actions=[
                    f"Confirmar transición a {_state_label(current_state)}",
                    "Recalcular agenda, evidencia y seguimiento sobre el estado reconciliado",
                ],
                evidence_basis=COMMON_EVIDENCE,
                target_state_label=_state_label(current_state),
                from_state_label=_state_label(explicit_state),
            ).to_dict()
        )

    if current_state in DIAGNOSTIC_STATES and _biopsy_confirms_cancer(patient):
        proposals.append(
            StateTransitionProposal(
                proposal_key=f"{current_state}:localized_after_histology",
                from_state=current_state,
                from_management_track=current_track,
                target_state="localized_initial",
                target_management_track="localized_decision",
                priority="high",
                rationale="Ya existe histología confirmatoria compatible con cáncer de próstata y el caso debe pasar a estratificación localizada/regional.",
                trigger_signals=["Histología confirmada", "Ruta diagnóstica completada"],
                next_actions=["Confirmar transición a evaluación localizada", "Revisar grupo de riesgo y nomogramas quirúrgicos/locales"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    adverse_histology = str(latest_biopsy.get("adverse_histology_variant_type") or "none")
    biopsy_upgrade = _safe_int(latest_biopsy.get("isup_grade")) or 0
    if current_track == "active_surveillance" and (
        biopsy_upgrade >= 2
        or _safe_int(latest_biopsy.get("carcinoma_intraductal")) == 1
        or _safe_int(latest_biopsy.get("patron_cribiforme")) == 1
        or adverse_histology not in {"", "none"}
    ):
        proposals.append(
            StateTransitionProposal(
                proposal_key="localized_initial:exit_active_surveillance",
                from_state="localized_initial",
                from_management_track=current_track,
                target_state="localized_initial",
                target_management_track="localized_decision",
                priority="high",
                rationale="La vigilancia activa ya no parece segura por progresión histológica o histología adversa documentada.",
                trigger_signals=["Progresión histológica", "Histología adversa"],
                next_actions=["Confirmar salida de vigilancia activa", "Rediscutir cirugía o radioterapia definitiva"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    post_prostatectomy_course = derive_post_prostatectomy_course(patient)
    if current_state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr":
        proposals.append(
            StateTransitionProposal(
                proposal_key="post_prostatectomy:to_recurrence_bcr",
                from_state="post_prostatectomy",
                from_management_track=current_track,
                target_state="recurrence_bcr",
                target_management_track="salvage",
                priority="high",
                rationale="El PSA post prostatectomía sugiere recurrencia bioquímica y obliga reabrir la ruta de rescate.",
                trigger_signals=["PSA posoperatorio compatible con recurrencia"],
                next_actions=["Confirmar etapa de recurrencia bioquímica", "Recalcular PSADT y factibilidad de rescate"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    if classifier_target and classifier_target != current_state and not (
        current_state == "localized_initial" and classifier_target == "localized_initial"
    ) and not (
        current_state in POSTLOCAL_STATES and classifier_target == "localized_initial"
    ) and not (
        current_state in (MHSPC_STATES | {"m0_crpc", "m1_crpc"})
        and classifier_target == "adt_progression_verification"
    ):
        rationale = registry.classify_state(classifier_payload).get("classification_reason") or "La nueva información cambia la etapa clínica probable."
        proposals.append(
            StateTransitionProposal(
                proposal_key=f"{current_state}:{classifier_target}:classifier",
                from_state=current_state,
                from_management_track=current_track,
                target_state=classifier_target,
                target_management_track=infer_management_track(patient, classifier_target, latest_assessment or patient.get("latest_assessment")),
                priority="high" if classifier_target in ADVANCED_STATES else "routine",
                rationale=rationale,
                trigger_signals=signals.get("awaiting_review", [])[:2] or ["Señales longitudinales compatibles con cambio de etapa"],
                next_actions=[
                    f"Confirmar transición a {_state_label(classifier_target)}",
                    "Actualizar recomendación modular y agenda después de la confirmación",
                ],
                evidence_basis=COMMON_EVIDENCE,
                target_state_label=_state_label(classifier_target),
                from_state_label=_state_label(current_state),
            ).to_dict()
        )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in proposals:
        key = item.get("proposal_key")
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def build_next_best_action(
    patient: dict[str, Any],
    signals: dict[str, Any],
    proposals: list[dict[str, Any]],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    truth_snapshot = patient.get("longitudinal_truth_snapshot") or build_longitudinal_truth_snapshot(patient, latest_assessment)
    truth_values = _current_field_values(patient, latest_assessment)
    state = signals.get("reconciled_state") or signals.get("state") or _current_state(patient, latest_assessment)
    management_track = signals.get("reconciled_management_track") or signals.get("management_track") or infer_management_track(patient, state, latest_assessment or patient.get("latest_assessment"))
    agenda = build_agenda_board(patient, state, management_track, latest_assessment or patient.get("latest_assessment"))
    due_titles = [item.get("title") for item in agenda.get("active_items", agenda.get("items", [])) if item.get("status") in {"due", "overdue"}][:3]
    checkpoint_actions = [item.get("action") for item in agenda.get("therapy_checkpoints", []) if item.get("status") in {"attention", "ready"} and item.get("action")][:2]
    result = (latest_assessment or patient.get("latest_assessment") or {}).get("result_snapshot", {})
    eligible = result.get("eligible_treatments", []) or []
    recommended_option = ""
    if eligible:
        first = eligible[0]
        recommended_option = str(first.get("name") if isinstance(first, dict) else first)
    recommendation_family = (
        (result.get("decision_quality", {}) or {}).get("recommendation_family")
        or str(truth_values.get("current_treatment") or "")
        or state
    )
    runtime_trigger_status = ""
    runtime_line_change_reason = ""
    runtime_monitoring_focus = ""
    latest_inputs = dict((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    psa, _ = _resolve_current_psa(patient, latest_assessment, truth_values)
    clinical_tstage = str(
        truth_values.get("clinical_tstage")
        or latest_inputs.get("clinical_tstage")
        or latest_biopsy.get("clinical_tstage")
        or ""
    ).upper()
    isup_grade = _safe_int(
        truth_values.get("isup_grade")
        or latest_inputs.get("isup_grade")
        or latest_biopsy.get("isup_grade")
    ) or 0
    num_cores_positive = _safe_int(
        truth_values.get("num_cores_positive")
        or latest_inputs.get("num_cores_positive")
        or latest_biopsy.get("positive_cores")
    ) or 0
    max_core_involvement = _safe_float(
        truth_values.get("max_core_involvement")
        or latest_inputs.get("max_core_involvement")
        or latest_biopsy.get("max_core_involvement")
    ) or 0.0
    psad = _safe_float(truth_values.get("psad") or latest_inputs.get("psad"))
    pirads_score = _safe_int(truth_values.get("pirads_score") or truth_values.get("prior_mpmri_pirads_score") or latest_inputs.get("pirads_score") or latest_inputs.get("prior_mpmri_pirads_score")) or 0
    family_history_positive = _safe_int(truth_values.get("family_history_positive") or latest_inputs.get("family_history_positive")) == 1
    germline_risk_mutation = _safe_int(truth_values.get("germline_risk_mutation") or latest_inputs.get("germline_risk_mutation")) == 1
    confirmatory_biopsy_done = truth_values.get("confirmatory_biopsy_done", latest_inputs.get("confirmatory_biopsy_done"))
    mri_interval_months = _safe_float(truth_values.get("mri_interval_months", latest_inputs.get("mri_interval_months")))
    upgrade_detected = _safe_int(truth_values.get("upgrade_detected", latest_inputs.get("upgrade_detected"))) == 1
    psma_pattern = str(truth_values.get("psma_uptake_pattern") or "").strip().lower()
    psma_stage_after = str(truth_values.get("psma_stage_after_psma") or "").strip().upper()
    post_prostatectomy_course = derive_post_prostatectomy_course(patient)
    family_lower = recommendation_family.lower()
    has_high_risk_local_features = (
        isup_grade >= 4
        or (clinical_tstage.startswith("T3") or clinical_tstage.startswith("T4"))
        or (psa is not None and psa >= 20)
    )
    has_unfavorable_local_features = (
        isup_grade >= 3
        or (clinical_tstage.startswith("T2") and clinical_tstage not in {"T1C", "T1A", "T1B"})
        or (psa is not None and psa >= 10)
        or num_cores_positive >= 4
        or max_core_involvement >= 0.35
    )

    def _localized_title() -> tuple[str, str]:
        if management_track == "active_surveillance" or "surveillance" in family_lower:
            if upgrade_detected or isup_grade >= 2:
                return (
                    "Salir de vigilancia activa y definir tratamiento definitivo",
                    "La reclasificación histológica ya no sostiene vigilancia activa segura y obliga a rediscutir tratamiento definitivo.",
                )
            if pirads_score >= 4:
                return (
                    "Programar biopsia dirigida y reevaluar continuidad de vigilancia activa",
                    "Una nueva lesión MRI de mayor riesgo durante vigilancia activa exige confirmación histológica antes de sostener el mismo carril.",
                )
            if confirmatory_biopsy_done in {0, "0", False} or (mri_interval_months is not None and mri_interval_months >= 18):
                return (
                    "Programar biopsia confirmatoria y reevaluar continuidad de vigilancia activa",
                    "La vigilancia activa requiere confirmación histológica y MRI seriada para sostener seguridad oncológica.",
                )
            return (
                "Mantener vigilancia activa y vigilar triggers de reclasificación",
                "El escenario actual sigue siendo compatible con vigilancia activa siempre que continúe la monitorización protocolizada.",
            )
        if "review" in family_lower or "uropat" in family_lower or "tumor board" in family_lower:
            return (
                "Priorizar revisión uropatológica y discusión multidisciplinaria",
                "La histología variante o incierta puede cambiar la indicación terapéutica y requiere validación experta.",
            )
        if "rt" in family_lower or "radiot" in family_lower or "ebrt" in family_lower:
            if "adt" in family_lower or has_high_risk_local_features:
                return (
                    "Priorizar radioterapia definitiva con intensificación hormonal contextual",
                    "El riesgo localizado desfavorable/alto favorece tratamiento local intensificado y planificación oncológica estructurada.",
                )
            return (
                "Priorizar radioterapia definitiva y planificación local",
                "La enfermedad localizada actual favorece tratamiento con radioterapia frente a vigilancia simple.",
            )
        if has_high_risk_local_features:
            return (
                "Activar tratamiento local intensificado y discusión multimodal",
                "Las características de alto riesgo hacen improbable una estrategia conservadora y requieren intensificación temprana.",
            )
        if has_unfavorable_local_features:
            return (
                "Definir tratamiento local definitivo y counseling funcional",
                "La carga tumoral actual favorece tratamiento local definitivo más que vigilancia activa continuada.",
            )
        if management_track in {"pre_surgery", "localized_decision"}:
            return (
                "Definir tratamiento local definitivo y counseling funcional",
                "La preferencia terapéutica longitudinal ya está orientada a tratamiento definitivo y debe cerrarse con planeación funcional.",
            )
        return (
            "Mantener o redefinir la estrategia local según riesgo y función",
            "La decisión local depende de patología, MRI, PROs y algoritmos contextuales.",
        )

    if proposals:
        proposal = proposals[0]
        recommendation_family = _proposal_recommendation_family(recommendation_family, proposal)
        actions = proposal.get("next_actions", [])[:]
        actions.extend(due_titles)
        title = f"Confirmar transición a {_state_label(str(proposal.get('target_state') or ''))}"
        rationale = proposal.get("rationale") or "La nueva información longitudinal ya cambió la etapa clínica esperada."
        target_state = str(proposal.get("target_state") or "")
        if target_state == "recurrence_bcr":
            title = "Activar salvage y reestadificación dirigida"
        return NextBestAction(
            title=title,
            recommendation_family=recommendation_family,
            rationale=rationale,
            immediate_actions=[item for item in actions if item][:3],
            data_that_could_change_course=(signals.get("critical_missing") or [])[:3],
            contraindication_modifiers=(signals.get("active_safety") or [])[:3],
            evidence_basis=proposal.get("evidence_basis") or COMMON_EVIDENCE,
        ).to_dict()

    if state in DIAGNOSTIC_STATES:
        if (
            any("pirads_high" == str(item.get("key") or "") for item in signals.get("signals", []))
            or pirads_score >= 4
            or (psad is not None and psad >= 0.15)
            or family_history_positive
            or germline_risk_mutation
        ):
            title = "Acelerar biopsia dirigida y confirmación histológica"
            rationale = "La señal radiológica de alto riesgo ya justifica cierre diagnóstico rápido con histología."
        else:
            title = "Mantener seguimiento diagnóstico con PSA y MRI seriados"
            rationale = "La etapa diagnóstica actual favorece vigilancia estrecha y repetición estructurada de PSA/MRI antes de escalar la invasividad."
    elif state == "localized_initial":
        title, rationale = _localized_title()
    elif state in POSTLOCAL_STATES:
        if state == "post_radiotherapy_or_local_salvage":
            runtime_contracts = _resolve_runtime_regimen_contracts(patient, state, latest_assessment)
            module_result = dict(runtime_contracts.get("module_result") or {})
            post_rt_bundle = dict(module_result.get("post_rt_salvage_bundle") or {})
            post_rt_failure_definition = dict(
                module_result.get("post_rt_failure_definition")
                or post_rt_bundle.get("post_rt_failure_definition")
                or {}
            )
            post_rt_transition_bundle = dict(
                module_result.get("post_rt_transition_bundle")
                or post_rt_bundle.get("post_rt_transition_bundle")
                or {}
            )
            post_rt_local_ranking = list(
                module_result.get("post_rt_local_salvage_ranking")
                or post_rt_bundle.get("post_rt_local_salvage_ranking")
                or runtime_contracts.get("eligible_treatments")
                or []
            )
            dominant_local_option = dict(
                post_rt_transition_bundle.get("dominant_local_option")
                or post_rt_bundle.get("dominant_local_option")
                or (post_rt_local_ranking[0] if post_rt_local_ranking and isinstance(post_rt_local_ranking[0], dict) else {})
            )
            dominant_label = str(
                dominant_local_option.get("name")
                or dominant_local_option.get("regimen_label")
                or dominant_local_option.get("regimen_code")
                or ""
            ).strip()
            module_family = str(
                ((module_result.get("decision_quality") or {}).get("recommendation_family"))
                or dominant_label
                or recommendation_family
                or "Ruta post-RT"
            ).strip()
            transition_status = str(
                post_rt_transition_bundle.get("transition_status")
                or post_rt_bundle.get("post_rt_course")
                or post_rt_bundle.get("post_rt_salvage_window_status")
                or ""
            ).strip()
            transition_reasons = [
                str(item).strip()
                for item in list(post_rt_transition_bundle.get("trigger_reasons") or [])
                if str(item).strip()
            ]
            failure_rationale = str(post_rt_failure_definition.get("rationale") or "").strip()
            runtime_trigger_status = transition_status or runtime_trigger_status
            if transition_reasons:
                runtime_line_change_reason = " ".join(transition_reasons[:2])

            if transition_status == "redirect_systemic":
                title = "Redirigir a secuencia sistémica y reestadificación"
                recommendation_family = module_family or "Redirección sistémica / reestadificación"
                rationale = (
                    " ".join(transition_reasons[:2])
                    or "La reestadificación PSMA ya cerró la vía local curativa aislada y obliga a rediscutir el carril sistémico."
                )
            elif transition_status == "mdt_candidate":
                title = f"Priorizar {dominant_label or 'terapia dirigida a metástasis (MDT) guiada por PSMA'}"
                recommendation_family = module_family or dominant_label or "MDT post-RT"
                rationale = (
                    " ".join(transition_reasons[:2])
                    or "El patrón oligorrecurrente dirigido por PSMA favorece una ruta MDT antes de forzar salvage glandular puro."
                )
            elif transition_status == "local_salvage_candidate":
                title = f"Priorizar {dominant_label}" if dominant_label else "Sostener salvage local post-RT"
                recommendation_family = module_family or dominant_label or "Ruta de salvage post-RT"
                rationale = (
                    " ".join(transition_reasons[:2])
                    or failure_rationale
                    or "La vía local post-radioterapia sigue abierta y debe priorizarse la modalidad de rescate mejor posicionada."
                )
            else:
                title = "Confirmar fallo post-RT antes de abrir salvage"
                recommendation_family = "Confirmación post-RT"
                rationale = (
                    failure_rationale
                    or "No debe abrirse salvage curativo post-radioterapia sin Phoenix met o una confirmación local equivalente."
                )
        elif state == "post_prostatectomy" and post_prostatectomy_course == "persistent_psa":
            title = "Iniciar evaluación temprana de salvage por PSA persistente"
            rationale = "El PSA persistente posoperatorio obliga a recalcular PSADT, factibilidad local e imagen si cambia la conducta, sin forzar todavía una BCR verdadera."
        elif state == "recurrence_bcr" or (state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr"):
            if psma_pattern == "diseminado" or psma_stage_after in {"M1B", "M1C"}:
                title = "Redirigir a intensificación sistémica y staging avanzado"
                rationale = "La PSMA estructurada ya sugiere enfermedad diseminada y reduce la prioridad de rescate local aislado."
            else:
                title = "Activar salvage y reestadificación dirigida"
                rationale = "La recurrencia bioquímica posoperatoria exige definir ventana de rescate, PSADT e imagen dirigida sin demoras."
        else:
            title = "Mantener vigilancia post prostatectomía y control bioquímico"
            rationale = "El seguimiento posoperatorio estable exige PSA ultrasensible seriado, revisión funcional y preservación de la ventana de rescate."
    else:
        title = "Reevaluar secuencia sistémica y seguridad activa"
        rationale = "La enfermedad avanzada debe balancear elegibilidad terapéutica, biomarcadores y toxicidad."
        acute_safety_tokens = ("hep", "renal", "hipokal", "gluc", "bilir", "anemia", "testosterona > 50", "toxic")
        safety_priority = any(
            any(token in str(item or "").lower() for token in acute_safety_tokens)
            for item in list(signals.get("active_safety") or [])
        )
        castrate_status = str(truth_values.get("castrate_testosterone_status") or "")
        if state == "adt_progression_verification" and castrate_status == "not_castrate":
            title = "Optimizar ADT y confirmar testosterona en rango de castración"
            rationale = "La progresión no debe rotularse como CRPC mientras la testosterona siga por encima del umbral de castración."
        if state == "adt_progression_verification" and str(truth_values.get("castrate_testosterone_status") or "") == "confirmed_castrate":
            title = "Confirmar transición a CRPC y redefinir secuencia sistémica"
            rationale = "La testosterona ya está en rango de castración; la conducta debe salir del carril de optimización de ADT y centrarse en progresión confirmada."
        runtime_contracts = _resolve_runtime_regimen_contracts(patient, state, latest_assessment)
        module_result = dict(runtime_contracts.get("module_result") or {})
        eligible_treatments = list(runtime_contracts.get("eligible_treatments") or [])
        preferred_regimen = dict(runtime_contracts.get("preferred_regimen") or {})
        sequence_bundle = dict(runtime_contracts.get("sequence_transition_bundle") or {})
        monitoring_package = dict(runtime_contracts.get("active_regimen_monitoring_package") or {})
        top_treatment = ""
        if eligible_treatments:
            first = eligible_treatments[0]
            top_treatment = str(first.get("name") if isinstance(first, dict) else first)
        preferred_family = str(
            preferred_regimen.get("family_label")
            or preferred_regimen.get("family_code")
            or sequence_bundle.get("active_family")
            or ""
        )
        module_family = str(
            ((module_result.get("decision_quality") or {}).get("recommendation_family"))
            or preferred_family
            or top_treatment
            or recommendation_family
        )
        line_of_therapy_number = _safe_int(truth_values.get("line_of_therapy_number") or truth_values.get("line_of_therapy") or latest_inputs.get("line_of_therapy_number"))
        hrr_status = str(truth_values.get("hrr_status") or "").strip().lower()
        brca2_status = str(truth_values.get("brca2_status") or "").strip().lower()
        preferred_label = str(preferred_regimen.get("name") or preferred_regimen.get("regimen_label") or top_treatment)
        trigger_status = str(sequence_bundle.get("trigger_status") or "")
        monitoring_focus = str(monitoring_package.get("monitoring_focus") or "")
        runtime_trigger_status = trigger_status
        runtime_line_change_reason = str(sequence_bundle.get("line_change_reason") or "")
        runtime_monitoring_focus = monitoring_focus
        if trigger_status == "confirm" and not safety_priority:
            title = "Completar datos críticos y recalcular la secuencia"
            recommendation_family = module_family
            rationale = str(sequence_bundle.get("line_change_reason") or "La conducta actual sigue condicionada por datos faltantes antes de cerrar la secuencia terapéutica.")
        elif preferred_label and trigger_status == "hold" and not safety_priority:
            title = f"Pausar y reevaluar {preferred_label}"
            recommendation_family = module_family
            rationale = str(sequence_bundle.get("line_change_reason") or monitoring_focus or "La toxicidad o seguridad activa obligan a pausar el regimen actual.")
        elif preferred_label and trigger_status in {"switch", "intensify"} and not safety_priority:
            title = f"Priorizar {preferred_label}"
            recommendation_family = module_family
            rationale = str(sequence_bundle.get("line_change_reason") or "La secuencia actual favorece un nuevo backbone preferente según elegibilidad y línea.")
        elif preferred_label and trigger_status in {"redirect_local", "redirect_systemic"} and not safety_priority:
            direction = "local" if trigger_status == "redirect_local" else "sistémica"
            title = f"Redirigir la conducta {direction} con {preferred_label}"
            recommendation_family = module_family
            rationale = str(sequence_bundle.get("line_change_reason") or monitoring_focus or "La trayectoria clínica actual ya requiere redireccionar la siguiente línea.")
        elif preferred_label and trigger_status == "continue" and not safety_priority:
            title = f"Continuar {preferred_label}"
            recommendation_family = module_family
            rationale = str(sequence_bundle.get("line_change_reason") or monitoring_focus or "El backbone preferente actual sigue alineado con la trayectoria clínica.")
        if state == "m0_crpc" and preferred_label and not safety_priority:
            title = f"Priorizar {preferred_label}"
            recommendation_family = module_family
            rationale = "El nmCRPC longitudinal actual ya permite intensificación con el ARPI más consistente con riesgo y seguridad."
        elif (
            state == "m1_crpc"
            and line_of_therapy_number in (None, 0, 1)
            and hrr_status not in {"positivo", "positive", "pathogenic"}
            and brca2_status not in {"positivo", "positive", "pathogenic"}
            and not preferred_label
            and not safety_priority
        ):
            title = "Priorizar Enzalutamide"
            recommendation_family = "ARPI first-line"
            rationale = "La m1CRPC temprana sin biomarcadores de precisión dominantes ni exposición ARPI documentada favorece iniciar una vía ARPI antes de rutas posteriores."
        elif state == "m1_crpc" and preferred_label and not safety_priority:
            title = f"Priorizar {preferred_label}"
            recommendation_family = module_family
            rationale = "La secuencia mCRPC debe seguir la elegibilidad terapéutica longitudinal, biomarcadores accionables y seguridad vigente."
        elif state in MHSPC_STATES and preferred_label and not safety_priority:
            title = f"Priorizar {preferred_label}"
            recommendation_family = module_family
            rationale = "El mHSPC actual ya tiene suficiente contexto longitudinal para elegir el backbone sistémico más competitivo."

    immediate_actions = due_titles + checkpoint_actions
    if not immediate_actions and signals.get("critical_missing"):
        immediate_actions = signals.get("critical_missing", [])[:3]
    response = NextBestAction(
        title=title,
        recommendation_family=recommendation_family,
        rationale=rationale,
        immediate_actions=immediate_actions[:3],
        data_that_could_change_course=(signals.get("critical_missing") or [])[:3],
        contraindication_modifiers=(signals.get("active_safety") or [])[:3],
        evidence_basis=COMMON_EVIDENCE,
    ).to_dict()
    if runtime_trigger_status:
        response["trigger_status"] = runtime_trigger_status
    if runtime_line_change_reason:
        response["line_change_reason"] = runtime_line_change_reason
    if runtime_monitoring_focus:
        response["monitoring_focus"] = runtime_monitoring_focus
    return response


def build_recommendation_audit(
    patient_id: int,
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    event_id: int | None = None,
) -> dict[str, Any] | None:
    assessment = latest_assessment or patient.get("latest_assessment") or {}
    result = assessment.get("result_snapshot", {}) or {}
    eligible = result.get("eligible_treatments", []) or []
    recommended_option = ""
    if eligible:
        first = eligible[0]
        recommended_option = str(first.get("name") if isinstance(first, dict) else first)
    recommendation_family = (result.get("decision_quality", {}) or {}).get("recommendation_family") or result.get("state") or assessment.get("state") or ""
    if not recommendation_family and not recommended_option:
        return None
    selected_option = _derive_current_treatment(patient)
    clinician_decision = (patient.get("clinical_decision_captures") or [{}])[0] if patient.get("clinical_decision_captures") else {}
    clinician_selected_option = str(
        clinician_decision.get("clinician_selected_option")
        or clinician_decision.get("selected_option")
        or selected_option
        or ""
    )
    discordance_reason = str(
        clinician_decision.get("discordance_reason_free_text")
        or clinician_decision.get("discordance_reason")
        or ""
    )
    if not discordance_reason:
        if recommended_option and clinician_selected_option and recommended_option.lower() not in clinician_selected_option.lower():
            discordance_reason = "La decisión clínica capturada no coincide con la recomendación modular vigente."
        elif recommended_option and not clinician_selected_option:
            discordance_reason = "Aún no existe decisión clínica capturada."
    return RecommendationAudit(
        patient_id=patient_id,
        assessment_id=assessment.get("id"),
        event_id=event_id,
        recommendation_family=recommendation_family,
        recommended_option=recommended_option or assessment.get("state") or "",
        selected_option=selected_option,
        recommended_confidence=str(((result.get("decision_quality") or {}).get("confidence_label") or "")),
        clinician_selected_option=clinician_selected_option,
        clinician_selected_family=str(clinician_decision.get("clinician_selected_family") or ""),
        followed_system_recommendation=str(clinician_decision.get("followed_system_recommendation") or ("unknown" if not clinician_decision else "")),
        discordance_reason_category=str(clinician_decision.get("discordance_reason_category") or ""),
        decision_capture_status=str("captured" if clinician_decision else "inferred_only"),
        discordance_reason=discordance_reason,
        outcome_snapshot={
            "state": assessment.get("state"),
            "management_track": infer_management_track(patient, assessment.get("state") or "", assessment),
        },
    ).to_dict()


def build_longitudinal_intelligence_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    truth_snapshot = patient.get("longitudinal_truth_snapshot") or build_longitudinal_truth_snapshot(patient, latest_assessment)
    patient = dict(patient)
    patient["longitudinal_truth_snapshot"] = truth_snapshot
    signals = build_clinical_signals(patient, latest_assessment)
    proposals = build_state_transition_proposals(patient, signals, latest_assessment)
    from prostanet.domains.patient_tracking.decision_input_requirements_engine import build_decision_input_requirements

    initial_requirements = build_decision_input_requirements(
        patient,
        effective_state=signals.get("reconciled_state") or signals.get("state") or "",
        effective_management_track=signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        next_best_action={},
    )
    transition_resolution = build_transition_resolution(
        patient,
        signals,
        proposals,
        decision_input_requirements=initial_requirements,
    )
    followup_runtime = resolve_followup_runtime_context(
        patient,
        state=signals.get("reconciled_state") or signals.get("state") or _current_state(patient, latest_assessment),
        management_track=signals.get("reconciled_management_track") or signals.get("management_track") or infer_management_track(
            patient,
            signals.get("reconciled_state") or signals.get("state") or "",
            latest_assessment or patient.get("latest_assessment"),
        ),
        latest_assessment=latest_assessment,
        signals=signals,
        transition_resolution=transition_resolution,
    )
    runtime_field_values = _current_field_values(patient, latest_assessment)
    palliative_transition_bundle = build_palliative_transition_bundle(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        field_values=runtime_field_values,
    )
    palliative_monitoring_package = build_palliative_monitoring_package(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        field_values=runtime_field_values,
        transition_bundle=palliative_transition_bundle,
    )
    survivorship_transition_bundle = build_survivorship_transition_bundle(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        field_values=runtime_field_values,
    )
    survivorship_monitoring_package = build_survivorship_monitoring_package(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        field_values=runtime_field_values,
        transition_bundle=survivorship_transition_bundle,
    )
    survivorship_schedule_overlay = build_survivorship_schedule_overlay(
        survivorship_transition_bundle,
        survivorship_monitoring_package,
    )
    survivorship_plan = build_survivorship_plan_alias(
        survivorship_transition_bundle,
        survivorship_monitoring_package,
    )
    plan_signals = dict(signals)
    plan_signals["palliative_transition_bundle"] = palliative_transition_bundle
    plan_signals["survivorship_transition_bundle"] = survivorship_transition_bundle
    if palliative_transition_bundle.get("acute_palliative_alerts"):
        plan_signals["active_safety"] = list(
            dict.fromkeys(
                list(plan_signals.get("active_safety") or [])
                + list(palliative_transition_bundle.get("acute_palliative_alerts") or [])
            )
        )
    if survivorship_transition_bundle.get("active_late_effect_alerts"):
        plan_signals["active_safety"] = list(
            dict.fromkeys(
                list(plan_signals.get("active_safety") or [])
                + list(survivorship_transition_bundle.get("active_late_effect_alerts") or [])
            )
        )
    override_reason = str(followup_runtime.get("override_reason") or "").strip()
    if override_reason:
        cadence_adjusted = [str(item) for item in list(plan_signals.get("cadence_adjusted_by") or []) if str(item).strip()]
        if override_reason not in cadence_adjusted:
            cadence_adjusted.append(override_reason)
        plan_signals["cadence_adjusted_by"] = cadence_adjusted
    agenda_board = build_agenda_board(
        patient,
        followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or _current_state(patient, latest_assessment),
        followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or infer_management_track(patient, signals.get("reconciled_state") or signals.get("state") or "", latest_assessment or patient.get("latest_assessment")),
        latest_assessment or patient.get("latest_assessment"),
    )
    visible_proposals = proposals if transition_resolution.get("policy") != "auto_applied" else []
    next_best_action = build_next_best_action(patient, signals, visible_proposals, latest_assessment)
    decision_input_requirements = build_decision_input_requirements(
        patient,
        effective_state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        effective_management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        next_best_action=next_best_action,
    )
    care_intent_contract = build_care_intent_contract(
        patient=patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        next_best_action=next_best_action,
        signals=plan_signals,
        transition_resolution=transition_resolution,
        decision_input_requirements=decision_input_requirements,
        palliative_transition_bundle=palliative_transition_bundle,
        survivorship_transition_bundle=survivorship_transition_bundle,
    )
    next_best_action = _align_next_best_action_with_care_intent(
        next_best_action,
        care_intent_contract,
        decision_input_requirements,
    )
    governance_bundle = build_clinical_decision_governance_bundle(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        next_best_action=next_best_action,
        decision_input_requirements=decision_input_requirements,
        care_intent_contract=care_intent_contract,
        transition_proposals=visible_proposals,
    )
    next_best_action = apply_governance_to_next_best_action(next_best_action, governance_bundle)
    care_intent_contract = {
        **care_intent_contract,
        "recommendation_block_status": governance_bundle.get("recommendation_block_status"),
        "recommendation_block_reason": governance_bundle.get("recommendation_block_reason"),
        "allowed_actions_while_blocked": governance_bundle.get("allowed_actions_while_blocked", []),
    }
    master_followup_plan = build_master_followup_plan(
        patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        agenda_board=agenda_board,
        signals=plan_signals,
        copilot_alerts=[],
        next_best_action=next_best_action,
    )
    guideline_followup_plan = build_guideline_followup_plan(
        patient=patient,
        state=followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        management_track=followup_runtime.get("management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "",
        agenda_board=agenda_board,
        master_followup_plan=master_followup_plan,
        signals=plan_signals,
        care_intent_contract=care_intent_contract,
    )
    laboratory_intelligence_profile = build_laboratory_intelligence_profile(
        patient,
        state=signals.get("reconciled_state") or signals.get("state") or "",
        management_track=signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
    )
    runtime_regimen_contracts = _resolve_runtime_regimen_contracts(
        patient,
        followup_runtime.get("state") or signals.get("reconciled_state") or signals.get("state") or "",
        latest_assessment,
    )
    decision_recalculation_trace = build_decision_recalculation_trace(
        patient=patient,
        state=signals.get("reconciled_state") or signals.get("state") or "",
        management_track=signals.get("reconciled_management_track") or signals.get("management_track") or "",
        latest_assessment=latest_assessment,
        longitudinal_truth_snapshot=truth_snapshot,
        next_best_action=next_best_action,
        reconciliation=signals,
        transition_resolution=transition_resolution,
        care_intent_contract=care_intent_contract,
    )
    return {
        "signals": signals,
        "transition_proposals": proposals,
        "transition_resolution": transition_resolution,
        "next_best_action": next_best_action,
        "care_intent_contract": care_intent_contract,
        "decision_input_requirements": decision_input_requirements,
        "longitudinal_truth_snapshot": truth_snapshot,
        "decision_recalculation_trace": decision_recalculation_trace,
        "guideline_followup_plan": guideline_followup_plan,
        "laboratory_intelligence_profile": laboratory_intelligence_profile,
        "latest_clinically_decisive_visit": truth_snapshot.get("latest_clinically_decisive_visit", {}),
        "master_followup_plan": master_followup_plan,
        "master_followup_summary": master_followup_plan.get("summary", {}),
        "comparative_eligibility_matrix": runtime_regimen_contracts.get("comparative_eligibility_matrix", {}),
        "sequence_transition_bundle": runtime_regimen_contracts.get("sequence_transition_bundle", {}),
        "active_regimen_monitoring_package": runtime_regimen_contracts.get("active_regimen_monitoring_package", {}),
        "palliative_transition_bundle": palliative_transition_bundle,
        "palliative_monitoring_package": palliative_monitoring_package,
        "symptom_burden_profile": palliative_transition_bundle.get("symptom_burden_profile", {}),
        "advance_care_planning_status": palliative_transition_bundle.get("advance_care_planning_status", {}),
        "hospice_eligibility": palliative_transition_bundle.get("hospice_eligibility", {}),
        "acute_palliative_alerts": palliative_transition_bundle.get("acute_palliative_alerts", []),
        "recommended_supportive_referrals": palliative_transition_bundle.get("recommended_referrals", []),
        "survivorship_transition_bundle": survivorship_transition_bundle,
        "survivorship_monitoring_package": survivorship_monitoring_package,
        "late_effects_profile": {
            "dominant_late_effect_domain": survivorship_transition_bundle.get("dominant_late_effect_domain"),
            "active_late_effect_alerts": survivorship_transition_bundle.get("active_late_effect_alerts", []),
            "recommended_referrals": survivorship_transition_bundle.get("recommended_referrals", []),
            "recommended_interventions": survivorship_transition_bundle.get("recommended_interventions", []),
            "adt_side_effects_profile": survivorship_transition_bundle.get("adt_side_effects_profile", {}),
            "radiotherapy_detail_profile": survivorship_transition_bundle.get("radiotherapy_detail_profile", {}),
            "skeletal_event_profile": survivorship_transition_bundle.get("skeletal_event_profile", {}),
            "pro_alerts": survivorship_transition_bundle.get("pro_alerts", []),
        },
        "functional_recovery_profile": {
            "survivorship_track": survivorship_transition_bundle.get("survivorship_track"),
            "functional_recovery_status": survivorship_transition_bundle.get("functional_recovery_status"),
            "psychosexual_status": survivorship_transition_bundle.get("psychosexual_status"),
            "secondary_prevention_status": survivorship_transition_bundle.get("secondary_prevention_status"),
            "patient_reported_outcomes_expected": survivorship_monitoring_package.get("patient_reported_outcomes_expected", []),
            "rehab_checks": survivorship_monitoring_package.get("rehab_checks", []),
        },
        "survivorship_schedule_overlay": survivorship_schedule_overlay,
        "survivorship_plan": survivorship_plan,
        "decision_governance_bundle": governance_bundle.get("decision_governance_bundle", {}),
        "recommendation_block_status": governance_bundle.get("recommendation_block_status", ""),
        "recommendation_block_reason": governance_bundle.get("recommendation_block_reason", ""),
        "allowed_actions_while_blocked": governance_bundle.get("allowed_actions_while_blocked", []),
        "decision_blocking_bundle": governance_bundle.get("decision_blocking_bundle", {}),
        "diagnostic_certainty_bundle": governance_bundle.get("diagnostic_certainty_bundle", {}),
        "staging_certainty_bundle": governance_bundle.get("staging_certainty_bundle", {}),
        "minimum_decisive_dataset_bundle": governance_bundle.get("minimum_decisive_dataset_bundle", {}),
        "decision_evidence_currentness_bundle": governance_bundle.get("decision_evidence_currentness_bundle", {}),
        "therapeutic_window_bundle": governance_bundle.get("therapeutic_window_bundle", {}),
        "window_worklist_bundle": governance_bundle.get("window_worklist_bundle", {}),
        "clinician_decision_capture_bundle": governance_bundle.get("clinician_decision_capture_bundle", {}),
        "state_transition_confirmation_bundle": governance_bundle.get("state_transition_confirmation_bundle", {}),
        "adherence_tracking_bundle": governance_bundle.get("adherence_tracking_bundle", {}),
        "tumor_board_outcome_bundle": governance_bundle.get("tumor_board_outcome_bundle", {}),
        "pro_decision_bundle": governance_bundle.get("pro_decision_bundle", {}),
        "shared_decision_bundle": governance_bundle.get("shared_decision_bundle", {}),
        "localized_modality_fitness_bundle": governance_bundle.get("localized_modality_fitness_bundle", {}),
        "localized_tradeoff_bundle": governance_bundle.get("localized_tradeoff_bundle", {}),
        "patient_priority_profile": governance_bundle.get("patient_priority_profile", {}),
        "ctdna_refinement_bundle": governance_bundle.get("ctdna_refinement_bundle", {}),
        "multimodal_imaging_concordance_bundle": governance_bundle.get("multimodal_imaging_concordance_bundle", {}),
        "precision_workflow_bundle": governance_bundle.get("precision_workflow_bundle", {}),
        "registry_core_bundle": governance_bundle.get("registry_core_bundle", {}),
        "endpoint_adjudication_bundle": governance_bundle.get("endpoint_adjudication_bundle", {}),
        "data_certainty_bundle": governance_bundle.get("data_certainty_bundle", {}),
        "ichom_compliance_bundle": governance_bundle.get("ichom_compliance_bundle", {}),
        "treatment_adverse_event_bundle": governance_bundle.get("treatment_adverse_event_bundle", {}),
        "population_survival_context_bundle": governance_bundle.get("population_survival_context_bundle", {}),
        "cost_access_context_bundle": governance_bundle.get("cost_access_context_bundle", {}),
        "score_interpretation_catalog_snapshot": governance_bundle.get("score_interpretation_catalog_snapshot", {}),
        "clinical_fact_bundle": governance_bundle.get("clinical_fact_bundle", {}),
        "reconciliation": {
            "reconciled_state": signals.get("reconciled_state") or signals.get("state"),
            "reconciled_management_track": signals.get("reconciled_management_track") or signals.get("management_track"),
            "state_conflict_flag": signals.get("state_conflict_flag", False),
            "state_conflict_reason": signals.get("state_conflict_reason", ""),
        },
    }
