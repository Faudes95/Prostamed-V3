from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.decision_input_requirements_engine import _field_values as _decision_field_values
from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
from prostanet.domains.patient_tracking.score_interpretation_catalog import (
    build_score_interpretation_snapshot,
)
from prostanet.domains.reporting.decision_aids import DecisionAidService
from prostanet.shared.ddi_engine import DDIEngine


LOCALIZED_PRO_FIELDS = [
    "epic26_urinary_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
    "ipss_total",
    "iief5_score",
    "eq5d_vas",
]

ADVANCED_PRO_FIELDS = [
    "fact_p_total",
    "eortc_qlq_c30_global_health",
    "eortc_qlq_c30_physical",
    "eortc_qlq_c30_role",
    "eortc_qlq_c30_emotional",
    "eortc_qlq_c30_fatigue",
    "eortc_qlq_c30_pain",
    "bpi_worst_pain",
    "facit_fatigue_total",
    "eq5d_vas",
    "anxiety_score",
]

ICHOM_LOCALIZED_FIELDS = [
    "psa",
    "ipss_total",
    "iief5_score",
    "eq5d_vas",
    "epic26_urinary_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
]

ICHOM_ADVANCED_FIELDS = [
    "psa",
    "eq5d_vas",
    "fact_p_total",
    "bpi_worst_pain",
    "facit_fatigue_total",
    "eortc_qlq_c30_global_health",
    "eortc_qlq_c30_pain",
]

HIGH_IMPACT_TRANSITIONS = {
    ("localized_initial", "m1_crpc"),
    ("localized_initial", "mcspc_oligo_metachronous"),
    ("localized_initial", "mcspc_low_volume_sync_oligo"),
    ("localized_initial", "mcspc_high_volume"),
    ("localized_initial", "mcspc_high_volume_sync"),
    ("localized_initial", "mcspc_high_volume_metachronous"),
    ("post_prostatectomy", "m0_crpc"),
    ("recurrence_bcr", "m0_crpc"),
    ("adt_progression_verification", "m0_crpc"),
    ("adt_progression_verification", "m1_crpc"),
    ("mcspc_oligo_metachronous", "m1_crpc"),
    ("mcspc_low_volume_sync_oligo", "m1_crpc"),
    ("mcspc_high_volume", "m1_crpc"),
    ("mcspc_high_volume_sync", "m1_crpc"),
    ("mcspc_high_volume_metachronous", "m1_crpc"),
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


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in values if item not in (None, "", [], {})))


def _latest(items: list[dict[str, Any]], *date_keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in date_keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key) or ""), reverse=True)[0]
    return items[0]


def _yes_no_unknown(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1", "si", "sí"}:
        return "yes"
    if text in {"no", "false", "0"}:
        return "no"
    return "unknown"


def _is_advanced_state(state: str) -> bool:
    return state in {
        "adt_progression_verification",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "m0_crpc",
        "m1_crpc",
    }


def _is_localized_postlocal_state(state: str) -> bool:
    return state in {
        "localized_initial",
        "post_prostatectomy",
        "recurrence_bcr",
        "post_radiotherapy_or_local_salvage",
        "active_surveillance",
    }


def _map_treatment_to_decision_aid_key(name: str) -> str | None:
    text = str(name or "").lower()
    if not text:
        return None
    if "surveillance" in text or "vigilancia" in text:
        return "active_surveillance"
    if "prostatect" in text or "cirug" in text:
        return "radical_prostatectomy"
    if "radiot" in text or "sbrt" in text or "imrt" in text or "brachy" in text:
        return "radiation_therapy"
    if "docetax" in text:
        return "docetaxel"
    if any(token in text for token in ("abirater", "enzalut", "apalut", "darolut")):
        return "adt_plus_arpi"
    if "adt" in text or "castr" in text or "leuprolide" in text or "goserelin" in text:
        return "adt_monotherapy"
    return None


def _merge_score_fields(patient: dict[str, Any], field_values: dict[str, Any]) -> dict[str, Any]:
    merged = dict(field_values or {})
    latest_pro = _latest(patient.get("pros") or [], "assessment_date")
    if latest_pro:
        for key, value in latest_pro.items():
            if _is_present(value) and not _is_present(merged.get(key)):
                merged[key] = value
    latest_biomarker = _latest(patient.get("biomarker_longitudinal") or [], "sample_date")
    if _is_present(latest_biomarker.get("value")) and str(latest_biomarker.get("biomarker_type") or "").upper() == "PSA":
        merged.setdefault("psa", latest_biomarker.get("value"))
    return merged


def _build_recommendation_blocking_bundle(
    decision_input_requirements: dict[str, Any],
) -> tuple[dict[str, Any], str, str, list[str]]:
    hard = list(decision_input_requirements.get("hard_blocking_inputs") or [])
    decision = list(decision_input_requirements.get("decision_blocking_inputs") or [])
    supportive = list(decision_input_requirements.get("supportive_gaps") or [])
    if hard:
        status = "hard_stop"
        reason = (
            "Faltan datos críticos que cambian la conducta clínica: "
            + ", ".join(hard[:6])
        )
        allowed = ["captura_critica", "recoleccion_documental", "revaluacion"]
    elif decision:
        status = "provisional"
        reason = (
            "La recomendación sigue abierta hasta cerrar datos decisionales: "
            + ", ".join(decision[:6])
        )
        allowed = ["captura_dirigida", "discusion_compartida_provisional", "monitorizacion_temporal"]
    else:
        status = "clear"
        reason = "La recomendación tiene los datos mínimos para sostener una conducta visible."
        allowed = ["recomendacion_final", "shared_decision", "planificacion"]
    bundle = {
        "available": True,
        "recommendation_block_status": status,
        "recommendation_block_reason": reason,
        "allowed_actions_while_blocked": allowed,
        "hard_blocking_inputs": hard,
        "decision_blocking_inputs": decision,
        "supportive_gaps": supportive,
        "capture_block": dict(decision_input_requirements.get("capture_block") or {}),
        "blocking_input_descriptors": list(decision_input_requirements.get("blocking_input_descriptors") or []),
    }
    return bundle, status, reason, allowed


def _build_clinician_decision_capture_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
) -> dict[str, Any]:
    captures = list(patient.get("clinical_decision_captures") or [])
    latest_capture = _latest(captures, "decision_finalized_at", "created_at")
    if latest_capture:
        latest_capture = dict(latest_capture)
        latest_capture["available"] = True
        latest_capture["decision_capture_status"] = "captured"
        return latest_capture
    audits = list(patient.get("recommendation_audit") or [])
    latest_audit = _latest(audits, "recorded_at")
    if latest_audit:
        return {
            "available": True,
            "decision_capture_status": latest_audit.get("decision_capture_status") or "inferred_only",
            "recommended_option": latest_audit.get("recommended_option") or next_best_action.get("title") or "",
            "recommended_family": latest_audit.get("recommendation_family") or next_best_action.get("recommendation_family") or "",
            "clinician_selected_option": latest_audit.get("clinician_selected_option") or latest_audit.get("selected_option") or "",
            "clinician_selected_family": latest_audit.get("clinician_selected_family") or "",
            "followed_system_recommendation": latest_audit.get("followed_system_recommendation") or "unknown",
            "discordance_reason_category": latest_audit.get("discordance_reason_category") or "",
            "discordance_reason_free_text": latest_audit.get("discordance_reason") or "",
            "shared_with_patient": False,
            "tumor_board_required": False,
            "state_at_decision": (latest_assessment or {}).get("state") or "",
        }
    return {
        "available": False,
        "decision_capture_status": "missing",
        "recommended_option": next_best_action.get("title") or "",
        "recommended_family": next_best_action.get("recommendation_family") or "",
        "clinician_selected_option": "",
        "followed_system_recommendation": "unknown",
        "discordance_reason_category": "",
        "discordance_reason_free_text": "",
        "state_at_decision": (latest_assessment or {}).get("state") or "",
    }


def prioritize_items_for_window_worklist(
    agenda_items: list[dict[str, Any]],
    window_worklist_bundle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank agenda items that close the active therapeutic/diagnostic window.

    The profile already applies its own chronological sort before calling this
    helper. This function keeps that relative order inside each priority band
    while lifting closure tasks and fields tied to the top active window.
    """

    bundle = dict(window_worklist_bundle or {})
    top_window = dict(bundle.get("top_active_window") or {})
    closure_tasks = list(bundle.get("closure_tasks") or [])
    task_keys = {
        str(task.get("agenda_key") or task.get("key") or task.get("item_key") or "").strip()
        for task in closure_tasks
        if str(task.get("agenda_key") or task.get("key") or task.get("item_key") or "").strip()
    }
    decisive_fields = set()
    for source in (
        top_window.get("required_inputs"),
        top_window.get("missing_decisive_fields"),
        top_window.get("display_missing_decisive_fields"),
        bundle.get("blocking_dataset_fields"),
        bundle.get("display_blocking_dataset_fields"),
    ):
        decisive_fields.update(str(item).strip() for item in (source or []) if str(item or "").strip())
    owner_domain = str(top_window.get("owner_domain") or "").strip().lower()

    def _item_fields(item: dict[str, Any]) -> set[str]:
        fields: set[str] = set()
        for key in (
            "fields",
            "capture_fields",
            "required_inputs",
            "raw_fields",
            "display_fields_summary",
            "missing_inputs",
        ):
            fields.update(str(value).strip() for value in (item.get(key) or []) if str(value or "").strip())
        return fields

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, raw_item in enumerate(agenda_items or []):
        item = dict(raw_item or {})
        agenda_key = str(item.get("agenda_key") or item.get("key") or item.get("item_key") or "").strip()
        item_fields = _item_fields(item)
        item_owner = str(item.get("owner_domain") or item.get("module_owner") or item.get("category") or "").strip().lower()
        if agenda_key and agenda_key in task_keys:
            priority = 0
            item["window_worklist_priority"] = "closure_task"
        elif decisive_fields and item_fields.intersection(decisive_fields):
            priority = 1
            item["window_worklist_priority"] = "decisive_field"
        elif owner_domain and item_owner and owner_domain == item_owner:
            priority = 2
            item["window_worklist_priority"] = "owner_domain"
        else:
            priority = 3
            item.setdefault("window_worklist_priority", "")
        ranked.append((priority, index, item))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [item for _, _, item in ranked]


def _is_high_impact_transition(proposal: dict[str, Any]) -> bool:
    from_state = str(proposal.get("from_state") or "")
    target_state = str(proposal.get("target_state") or "")
    if (from_state, target_state) in HIGH_IMPACT_TRANSITIONS:
        return True
    if target_state in {"supportive_only", "hospice_pathway"}:
        return True
    if "salvage" in target_state or "salvage" in str(proposal.get("proposal_key") or ""):
        return True
    return False


def _build_state_transition_confirmation_bundle(
    patient: dict[str, Any],
    transition_proposals: list[dict[str, Any]],
    decision_input_requirements: dict[str, Any],
) -> dict[str, Any]:
    proposals = [
        dict(proposal)
        for proposal in (transition_proposals or patient.get("transition_proposals") or [])
        if _is_high_impact_transition(proposal)
    ]
    for proposal in proposals:
        proposal.setdefault("confirmation_status", proposal.get("proposal_status") or "pending")
        proposal.setdefault(
            "requires_more_data_fields",
            list(decision_input_requirements.get("hard_blocking_inputs") or []),
        )
    return {
        "available": bool(proposals),
        "pending_count": sum(
            1 for proposal in proposals if str(proposal.get("confirmation_status") or "pending") == "pending"
        ),
        "requires_confirmation": bool(proposals),
        "high_impact_proposals": proposals,
    }


def _build_adherence_tracking_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    items = []
    today_iso = date.today().isoformat()
    for raw in list(patient.get("scheduled_events") or []):
        item = dict(raw)
        completed_at = str(item.get("performed_date") or item.get("completed_date") or item.get("completed_at") or "")[:10]
        due_at = str(item.get("scheduled_due_at") or item.get("due_date") or item.get("due_at") or "")[:10]
        completion_status = str(item.get("completion_status") or "").strip()
        if not completion_status:
            if completed_at and due_at:
                completion_status = "completed_on_time" if completed_at <= due_at else "completed_late"
            elif completed_at:
                completion_status = "completed_on_time"
            elif due_at and due_at < today_iso:
                completion_status = "missed"
            else:
                completion_status = "scheduled"
        days_late = item.get("days_late")
        if days_late in (None, "") and completed_at and due_at and completed_at > due_at:
            days_late = (datetime.fromisoformat(completed_at) - datetime.fromisoformat(due_at)).days
        elif days_late in (None, "") and due_at and due_at < today_iso and not completed_at:
            days_late = (datetime.fromisoformat(today_iso) - datetime.fromisoformat(due_at)).days
        item.update(
            {
                "scheduled_item_id": item.get("id"),
                "expected_action": item.get("label") or item.get("event_type") or "",
                "due_at": due_at,
                "performed_date": completed_at,
                "completion_status": completion_status,
                "completion_source": item.get("completion_source") or ("stage_visit" if item.get("completed_visit_id") else "manual"),
                "days_late": int(days_late or 0),
                "adherence_impact": item.get("adherence_impact") or (
                    "alto" if completion_status in {"missed", "completed_late"} else "controlado"
                ),
                "next_recovery_action": item.get("next_recovery_action") or (
                    "Reprogramar y recapturar evidencia de ejecución." if completion_status == "missed" else ""
                ),
            }
        )
        items.append(item)
    completed_on_time = sum(1 for item in items if item.get("completion_status") == "completed_on_time")
    eligible_items = [item for item in items if item.get("completion_status") in {"completed_on_time", "completed_late", "missed", "superseded"}]
    protocol_adherence_pct = round((completed_on_time / len(eligible_items)) * 100, 1) if eligible_items else 100.0
    guideline_concordance_pct = round((sum(1 for item in items if item.get("completion_status") in {"completed_on_time", "superseded"}) / len(eligible_items)) * 100, 1) if eligible_items else 100.0
    return {
        "available": bool(items),
        "items": items,
        "protocol_adherence_pct": protocol_adherence_pct,
        "guideline_concordance_pct": guideline_concordance_pct,
        "research_endpoint_validity": "robusta" if guideline_concordance_pct >= 80 else "limitada",
        "overdue_or_missed_count": sum(1 for item in items if item.get("completion_status") in {"completed_late", "missed"}),
    }


def _build_tumor_board_outcome_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    outcomes = list(patient.get("tumor_board_outcomes") or [])
    latest_outcome = _latest(outcomes, "discussion_date", "created_at")
    if latest_outcome:
        latest_outcome = dict(latest_outcome)
        latest_outcome["available"] = True
        return latest_outcome
    return {
        "available": False,
        "board_pending": bool(
            (latest_assessment or {}).get("result_snapshot", {}).get("tumor_board_required")
        ),
        "system_recommendation_at_board": "",
        "board_recommendation": "",
        "board_overrode_system": "unknown",
    }


def _build_pro_decision_bundle(
    patient: dict[str, Any],
    state: str,
    decision_input_requirements: dict[str, Any],
    field_values: dict[str, Any],
) -> dict[str, Any]:
    score_fields = _merge_score_fields(patient, field_values)
    score_snapshot = build_score_interpretation_snapshot(score_fields)
    alerts = [alert.to_dict() for alert in PRODecisionEngine.evaluate_all(int((patient.get("identity") or {}).get("id") or 0), score_fields)]
    if _is_advanced_state(state):
        required_fields = ADVANCED_PRO_FIELDS
    elif _is_localized_postlocal_state(state):
        required_fields = LOCALIZED_PRO_FIELDS
    else:
        required_fields = ["eq5d_vas", "ipss_total", "iief5_score"]
    missing_inputs = [field for field in required_fields if not _is_present(score_fields.get(field))]
    if any(alert.get("severity") == "critical" for alert in alerts):
        status = "escalation_trigger"
    elif any(alert.get("category") in {"pain", "qol", "fatigue"} for alert in alerts):
        status = "decision_modifier"
    elif alerts:
        status = "supportive_modifier"
    else:
        status = "none"
    recommended_modifier = ""
    if status == "escalation_trigger":
        recommended_modifier = "priorizar soporte, paliativos o reestadificación antes de intensificar."
    elif status == "decision_modifier":
        recommended_modifier = "recalibrar la intensidad terapéutica con base en calidad de vida y síntomas."
    elif status == "supportive_modifier":
        recommended_modifier = "mantener la recomendación oncológica, pero con mitigación sintomática activa."
    return {
        "available": bool(score_snapshot or alerts),
        "pro_decision_status": status,
        "dominant_pro_domain": (alerts[0].get("category") if alerts else ""),
        "pro_decision_reasons": [alert.get("title") for alert in alerts[:4]],
        "recommended_course_modifier": recommended_modifier,
        "pro_capture_readiness": "complete" if not missing_inputs else "incomplete",
        "required_fields": required_fields,
        "missing_inputs": missing_inputs,
        "alerts": alerts,
        "score_interpretation_catalog_snapshot": score_snapshot,
        "decision_input_overlap": _dedupe(
            list(decision_input_requirements.get("decision_blocking_inputs") or []) + missing_inputs
        ),
    }


def _build_cost_access_context_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
) -> dict[str, Any]:
    institution = str(
        (patient.get("baseline") or {}).get("institution")
        or (patient.get("baseline") or {}).get("institucion")
        or (patient.get("identity") or {}).get("institution")
        or "IMSS"
    )
    preferred = dict(((latest_assessment or {}).get("result_snapshot") or {}).get("preferred_frontline_regimen") or {})
    regimen_label = str(
        preferred.get("regimen_label")
        or preferred.get("regimen_code")
        or next_best_action.get("title")
        or ""
    )
    formulary = DDIEngine.check_formulary(regimen_label, institution) if regimen_label else {}
    return {
        "available": bool(regimen_label),
        "payer_context": institution.upper() if institution else "IMSS",
        "recommended_option": regimen_label,
        "monthly_cost_estimate": formulary.get("monthly_cost_mxn", 0),
        "access_status": "available" if formulary.get("available") else "restricted",
        "formularies_available": [formulary] if formulary else [],
        "cost_access_driver": formulary.get("exception_path", ""),
        "cost_effectiveness_context": (
            "Costo cubierto por formulario institucional." if formulary.get("monthly_cost_mxn", 0) == 0 else "Costo estimado mensual sin sustituir juicio clínico."
        ),
    }


def _build_shared_decision_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
    recommendation_block_status: str,
    pro_decision_bundle: dict[str, Any],
    clinician_decision_capture_bundle: dict[str, Any],
    cost_access_context_bundle: dict[str, Any],
) -> dict[str, Any]:
    assessment = latest_assessment or patient.get("latest_assessment") or {}
    result = dict(assessment.get("result_snapshot") or {})
    eligible = list(result.get("eligible_treatments") or [])
    patient_priorities = []
    if clinician_decision_capture_bundle.get("patient_preference_driver"):
        patient_priorities.append(str(clinician_decision_capture_bundle.get("patient_preference_driver")))
    if str((patient.get("baseline") or {}).get("patient_prefers_comfort") or "").lower() in {"1", "true", "yes", "si", "sí"}:
        patient_priorities.append("calidad de vida")
    mapped_options = []
    patient_facing = []
    for option in eligible[:3]:
        option_name = str(option.get("name") if isinstance(option, dict) else option)
        if not option_name:
            continue
        patient_facing.append(option_name)
        mapped = _map_treatment_to_decision_aid_key(option_name)
        if mapped:
            mapped_options.append(mapped)
    if not patient_facing and next_best_action.get("title"):
        patient_facing.append(str(next_best_action.get("title")))
        mapped = _map_treatment_to_decision_aid_key(next_best_action.get("title"))
        if mapped:
            mapped_options.append(mapped)
    comparison = (
        DecisionAidService.generate_comparison(_dedupe(mapped_options), patient_priorities=patient_priorities)
        if mapped_options and recommendation_block_status != "hard_stop"
        else {}
    )
    readiness = "blocked" if recommendation_block_status == "hard_stop" else "provisional" if recommendation_block_status == "provisional" else "ready"
    qol_tradeoffs = list(pro_decision_bundle.get("pro_decision_reasons") or [])
    if cost_access_context_bundle.get("cost_access_driver"):
        qol_tradeoffs.append(f"Acceso/costo: {cost_access_context_bundle.get('cost_access_driver')}")
    return {
        "available": bool(patient_facing),
        "eligible_options_patient_facing": patient_facing,
        "absolute_benefit_display": comparison.get("options", []),
        "absolute_harm_display": [entry.get("side_effects_pictogram", []) for entry in comparison.get("options", [])],
        "qol_tradeoffs": qol_tradeoffs[:5],
        "patient_priority_alignment": comparison.get("priority_alignment", []),
        "decision_readiness": readiness,
        "second_opinion_printable_summary": comparison.get("shared_decision_note", ""),
    }


def _build_ctdna_refinement_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    detected = _yes_no_unknown(field_values.get("ctdna_detected"))
    vaf = _safe_float(field_values.get("ctdna_vaf"))
    rising = _yes_no_unknown(field_values.get("ctdna_rising"))
    role = "none"
    if rising == "yes":
        role = "escalation_trigger"
    elif detected == "yes" or vaf is not None:
        role = "monitoring_refiner"
    return {
        "available": detected != "unknown" or vaf is not None,
        "ctdna_detected": detected,
        "ctdna_vaf": vaf,
        "ctdna_rising": rising,
        "ctdna_sample_date": field_values.get("ctdna_sample_date") or "",
        "ctdna_platform": field_values.get("ctdna_platform") or "",
        "ctdna_hrr_status": field_values.get("ctdna_hrr_status") or field_values.get("hrr_status") or "",
        "ctdna_resistance_signals": _dedupe(
            [
                field_values.get("ctdna_arpi_resistance"),
                field_values.get("ctdna_psma_resistance"),
            ]
        ),
        "decision_role": role,
    }


def _build_multimodal_imaging_concordance_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    pirads = str(
        field_values.get("pirads_v21_score")
        or field_values.get("pirads_score")
        or field_values.get("prior_mpmri_pirads_score")
        or ""
    ).strip()
    psma_rads = str(field_values.get("psma_rads_score") or "").strip()
    mpmri_available = _yes_no_unknown(field_values.get("mpmri_done")) == "yes" or bool(pirads)
    psma_available = _yes_no_unknown(field_values.get("psma_pet_done")) == "yes" or bool(psma_rads)
    concordance = "insufficient_data"
    implication = ""
    if mpmri_available and psma_available:
        if pirads in {"4", "5"} and psma_rads in {"4", "5"}:
            concordance = "concordant"
            implication = "La lesión dominante es concordante en ambas modalidades."
        elif pirads in {"1", "2"} and psma_rads in {"4", "5"}:
            concordance = "discordant"
            implication = "Discordancia local vs sistémica; considerar correlación dirigida y biopsia."
        elif pirads in {"4", "5"} and psma_rads in {"1", "2", "3A", "3B"}:
            concordance = "partially_concordant"
            implication = "La MRI sugiere lesión significativa sin pleno soporte PSMA; requiere integración clínica."
        else:
            concordance = "partially_concordant"
            implication = "La imagen es incompletamente concordante y debe integrarse con biopsia/PSA."
    return {
        "available": mpmri_available or psma_available,
        "mpmri_available": mpmri_available,
        "pirads_v21_score": pirads,
        "prostate_volume_ml": _safe_float(field_values.get("prostate_volume") or field_values.get("prostate_volume_ml")),
        "psma_available": psma_available,
        "psma_rads_score": psma_rads,
        "uptake_pattern": field_values.get("psma_uptake_pattern") or "",
        "lesion_concordance_status": concordance,
        "discordance_implication": implication,
        "lesion_tracking_ready": bool(
            (field_values.get("index_lesion_location") or field_values.get("local_recurrence_site"))
            and (field_values.get("psma_lesion_locations") or field_values.get("psma_uptake_pattern"))
        ),
    }


def _build_ichom_compliance_bundle(state: str, field_values: dict[str, Any]) -> dict[str, Any]:
    required_fields = ICHOM_ADVANCED_FIELDS if _is_advanced_state(state) else ICHOM_LOCALIZED_FIELDS
    captured_fields = [field for field in required_fields if _is_present(field_values.get(field))]
    missing_fields = [field for field in required_fields if field not in captured_fields]
    compliance_pct = round((len(captured_fields) / len(required_fields)) * 100, 1) if required_fields else 0.0
    return {
        "available": True,
        "set_name": "ICHOM Advanced" if _is_advanced_state(state) else "ICHOM Localized",
        "required_fields": required_fields,
        "captured_fields": captured_fields,
        "missing_fields": missing_fields,
        "compliance_pct": compliance_pct,
        "comparable_export_ready": compliance_pct >= 70,
    }


def _build_treatment_adverse_event_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    adverse_events = list(patient.get("treatment_adverse_events") or [])
    recent = adverse_events[:8]
    grade_ge_3 = [event for event in adverse_events if int(event.get("ctcae_grade") or 0) >= 3]
    return {
        "available": bool(adverse_events),
        "events": recent,
        "grade_ge_3_count": len(grade_ge_3),
        "regimen_codes": _dedupe([event.get("regimen_code") for event in adverse_events]),
        "expected_vs_observed_context": [event.get("expected_vs_observed_context") for event in recent if event.get("expected_vs_observed_context")],
    }


def _build_population_survival_context_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    live_benchmark = dict(patient.get("live_benchmark") or {})
    trial_profile = dict(patient.get("current_trial_comparable_profile") or {})
    benchmark_reliability = dict(patient.get("benchmark_reliability") or {})
    return {
        "available": bool(live_benchmark or trial_profile),
        "seer_reference": live_benchmark.get("external_reference") or "SEER-like contextual reference unavailable",
        "pcbase_reference": live_benchmark.get("population_reference") or "",
        "population_match_quality": benchmark_reliability.get("cohort_tier") or benchmark_reliability.get("display_confidence_label") or "No disponible",
        "individual_vs_population_delta": trial_profile.get("recommended_trial_backbone_note") or "",
        "matched_population_snapshot": live_benchmark.get("matched_population_snapshot") or {},
    }


def apply_governance_to_next_best_action(
    next_best_action: dict[str, Any],
    governance_bundle: dict[str, Any],
) -> dict[str, Any]:
    action = dict(next_best_action or {})
    block_status = str(governance_bundle.get("recommendation_block_status") or "clear")
    block_reason = str(governance_bundle.get("recommendation_block_reason") or "")
    blocking_bundle = dict(governance_bundle.get("decision_blocking_bundle") or {})
    pro_bundle = dict(governance_bundle.get("pro_decision_bundle") or {})
    if block_status == "hard_stop":
        capture_block = dict(blocking_bundle.get("capture_block") or {})
        action.update(
            {
                "title": capture_block.get("title") or "Completar datos críticos antes de cerrar recomendación",
                "recommendation_family": "governance_block",
                "rationale": block_reason,
                "immediate_actions": _dedupe(
                    list(action.get("immediate_actions") or []) + [capture_block.get("summary") or block_reason]
                ),
                "data_that_could_change_course": list(blocking_bundle.get("hard_blocking_inputs") or []),
                "governance_status": block_status,
            }
        )
        return action
    if block_status == "provisional":
        action["rationale"] = f"{action.get('rationale') or ''} {block_reason}".strip()
        action["governance_status"] = block_status
        action["data_that_could_change_course"] = _dedupe(
            list(action.get("data_that_could_change_course") or [])
            + list(blocking_bundle.get("decision_blocking_inputs") or [])
        )
    if str(pro_bundle.get("pro_decision_status") or "") in {"decision_modifier", "escalation_trigger"}:
        action["rationale"] = (
            f"{action.get('rationale') or ''} PROs: "
            + "; ".join(list(pro_bundle.get("pro_decision_reasons") or [])[:2])
        ).strip()
        action["immediate_actions"] = _dedupe(
            list(action.get("immediate_actions") or [])
            + ([pro_bundle.get("recommended_course_modifier")] if pro_bundle.get("recommended_course_modifier") else [])
        )
    return action


def build_clinical_decision_governance_bundle(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
    transition_proposals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = state or (latest_assessment or {}).get("state") or (patient.get("prior_history") or {}).get("current_state") or "diagnostic_workup"
    management_track = management_track or patient.get("schedule_management_track") or ""
    latest_assessment = latest_assessment or patient.get("latest_assessment") or {}
    next_best_action = dict(next_best_action or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    care_intent_contract = dict(care_intent_contract or {})
    field_values = _decision_field_values(patient)
    decision_blocking_bundle, block_status, block_reason, allowed_actions = _build_recommendation_blocking_bundle(
        decision_input_requirements
    )
    clinician_decision_capture_bundle = _build_clinician_decision_capture_bundle(
        patient,
        latest_assessment,
        next_best_action,
    )
    state_transition_confirmation_bundle = _build_state_transition_confirmation_bundle(
        patient,
        transition_proposals or [],
        decision_input_requirements,
    )
    adherence_tracking_bundle = _build_adherence_tracking_bundle(patient)
    tumor_board_outcome_bundle = _build_tumor_board_outcome_bundle(patient, latest_assessment)
    pro_decision_bundle = _build_pro_decision_bundle(
        patient,
        state,
        decision_input_requirements,
        field_values,
    )
    ctdna_refinement_bundle = _build_ctdna_refinement_bundle(field_values)
    multimodal_imaging_concordance_bundle = _build_multimodal_imaging_concordance_bundle(field_values)
    ichom_compliance_bundle = _build_ichom_compliance_bundle(state, _merge_score_fields(patient, field_values))
    treatment_adverse_event_bundle = _build_treatment_adverse_event_bundle(patient)
    population_survival_context_bundle = _build_population_survival_context_bundle(patient)
    cost_access_context_bundle = _build_cost_access_context_bundle(patient, latest_assessment, next_best_action)
    shared_decision_bundle = _build_shared_decision_bundle(
        patient,
        latest_assessment,
        next_best_action,
        block_status,
        pro_decision_bundle,
        clinician_decision_capture_bundle,
        cost_access_context_bundle,
    )
    score_snapshot = dict(pro_decision_bundle.get("score_interpretation_catalog_snapshot") or {})
    governance_summary = {
        "available": True,
        "state": state,
        "management_track": management_track,
        "recommendation_block_status": block_status,
        "recommendation_block_reason": block_reason,
        "allowed_actions_while_blocked": allowed_actions,
        "care_goal": care_intent_contract.get("care_goal") or "",
        "supportive_priority": care_intent_contract.get("supportive_priority") or "",
        "palliative_trigger_status": care_intent_contract.get("palliative_trigger_status") or "",
    }
    return {
        "decision_governance_bundle": governance_summary,
        "recommendation_block_status": block_status,
        "recommendation_block_reason": block_reason,
        "allowed_actions_while_blocked": allowed_actions,
        "decision_blocking_bundle": decision_blocking_bundle,
        "clinician_decision_capture_bundle": clinician_decision_capture_bundle,
        "state_transition_confirmation_bundle": state_transition_confirmation_bundle,
        "adherence_tracking_bundle": adherence_tracking_bundle,
        "tumor_board_outcome_bundle": tumor_board_outcome_bundle,
        "pro_decision_bundle": pro_decision_bundle,
        "shared_decision_bundle": shared_decision_bundle,
        "ctdna_refinement_bundle": ctdna_refinement_bundle,
        "multimodal_imaging_concordance_bundle": multimodal_imaging_concordance_bundle,
        "ichom_compliance_bundle": ichom_compliance_bundle,
        "treatment_adverse_event_bundle": treatment_adverse_event_bundle,
        "population_survival_context_bundle": population_survival_context_bundle,
        "cost_access_context_bundle": cost_access_context_bundle,
        "score_interpretation_catalog_snapshot": score_snapshot,
    }
