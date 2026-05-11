from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.advanced_therapy_decision_builder import (
    build_therapy_readiness_breakdown,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import family_label
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.domains.patient_tracking.therapy_evidence_currentness_builder import (
    build_therapy_evidence_currentness_bundle,
)
from prostanet.shared.ui_value_normalizer import (
    normalize_field_label,
    normalize_field_list,
)


_PALLIATIVE_REDIRECT_VALUES = {
    "dominant",
    "supportive_only",
    "redirect_supportive_only",
    "palliative_priority",
}
_BLOCK_STATUS_HARD = {"hard_stop", "blocked", "blocked_by_missing_data"}
_BLOCK_STATUS_PROVISIONAL = {"provisional", "conditional", "pending", "review_needed"}
_SAFETY_STATUSES = {"contraindicated", "hard_blocked", "blocked_by_safety"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if value in (None, "", {}):
        return []
    return [value]


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _family_from_action(value: Any) -> str:
    normalized = _lower(value)
    if normalized in {"salvage", "ruta de rescate", "rescate", "salvage_family"}:
        return "salvage_rt_family"
    if normalized in {"mcrpc_sequence", "m1_crpc_sequence"}:
        return "mcrpc_sequence"
    return _text(value)


def _display_fields(fields: list[Any]) -> list[str]:
    return normalize_field_list(_dedupe(list(fields or [])))


def _build_traceability_requirements(
    *,
    state: str,
    candidate_family: str,
    required_fields: list[str],
    stale_fields: list[str],
    decision_input_requirements: dict[str, Any],
    preferred_regimen: dict[str, Any],
    comparative_eligibility_matrix: dict[str, Any],
) -> list[dict[str, Any]]:
    required_set = set(_dedupe(required_fields))
    stale_set = set(_dedupe(stale_fields))
    family_missing = set(
        _dedupe(
            list((decision_input_requirements.get("family_missing_inputs") or {}).get(candidate_family) or [])
        )
    )
    family_stale = set(
        _dedupe(
            list((decision_input_requirements.get("family_stale_inputs") or {}).get(candidate_family) or [])
        )
    )
    missing = required_set | family_missing
    stale = stale_set | family_stale
    family_profile = dict(comparative_eligibility_matrix.get(candidate_family) or {})
    missing.update(_dedupe(list(family_profile.get("missing_inputs") or [])))
    stale.update(_dedupe(list(family_profile.get("stale_inputs") or [])))
    missing.update(_dedupe(list(preferred_regimen.get("required_missing_fields") or [])))
    stale.update(_dedupe(list(preferred_regimen.get("stale_inputs") or [])))

    specs = [
        (
            "psa_dynamics",
            "Dinámica de PSA / APE",
            {"psadt_months", "psa_history", "bcr_psa", "psa", "psa_current"},
            candidate_family in {"salvage_rt_family", "local_mdt_family"} or state in {"recurrence_bcr", "post_prostatectomy"},
        ),
        (
            "local_salvage_feasibility",
            "Factibilidad de rescate local",
            {"salvage_local_feasible", "local_salvage_candidate", "psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"},
            candidate_family in {"salvage_rt_family", "local_mdt_family"},
        ),
        (
            "castrate_confirmation",
            "Confirmación de castración",
            {"testosterone", "testosterone_history", "castrate_testosterone_status", "current_adt_context"},
            state in {"m0_crpc", "m1_crpc", "adt_progression_verification"} or candidate_family in {"arpi_family", "abiraterone_steroid_family"},
        ),
        (
            "restaging_negative_context",
            "Contexto M0/M1 por imagen",
            {"conventional_imaging_status", "conventional_imaging_date", "psma_pet_done", "psma_positive", "psma_negative_dominant_lesions"},
            state in {"m0_crpc", "m1_crpc", "adt_progression_verification"},
        ),
        (
            "molecular_traceability",
            "Trazabilidad molecular HRR",
            {"hrr_status", "hrr_gene", "biomarker_source", "molecular_report_date", "molecular_assay_date"},
            candidate_family == "parp_family",
        ),
        (
            "psma_traceability",
            "Trazabilidad PSMA-RLT",
            {"psma_positive", "psma_pet_done", "psma_negative_dominant_lesions", "psma_stage_after_psma"},
            candidate_family == "psma_rlt_family",
        ),
        (
            "mhspc_safety_readiness",
            "Seguridad para intensificación mHSPC",
            {"mini_cog_score", "g8_score", "ddi_review_status", "cv_risk_documented", "current_medications", "ecog_score"},
            state.startswith("mcspc_") or state == "mcspc_high_volume",
        ),
    ]

    requirements: list[dict[str, Any]] = []
    for key, label, fields, applicable in specs:
        if not applicable:
            continue
        missing_here = _dedupe([field for field in fields if field in missing])
        stale_here = _dedupe([field for field in fields if field in stale])
        if missing_here:
            status = "missing"
        elif stale_here:
            status = "stale"
        else:
            status = "captured"
        requirements.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "missing_fields": missing_here,
                "stale_fields": stale_here,
                "display_missing_fields": _display_fields(missing_here),
                "display_stale_fields": _display_fields(stale_here),
            }
        )
    return requirements


def _candidate_from_inputs(
    preferred_regimen: dict[str, Any],
    next_best_action: dict[str, Any],
    comparative_eligibility_matrix: dict[str, Any],
) -> tuple[str, str, str]:
    candidate_family = _first_nonempty(
        preferred_regimen.get("family_code"),
        preferred_regimen.get("recommendation_family"),
        _family_from_action(next_best_action.get("recommendation_family")),
    )
    candidate_regimen_code = _first_nonempty(
        preferred_regimen.get("regimen_code"),
        preferred_regimen.get("code"),
        preferred_regimen.get("therapy_key"),
    )
    if not candidate_regimen_code and candidate_family:
        family_profile = dict(comparative_eligibility_matrix.get(candidate_family) or {})
        variant = dict(family_profile.get("variant_ranking") or {})
        candidate_regimen_code = _first_nonempty(
            variant.get("preferred_regimen_code"),
            family_profile.get("preferred_regimen_code"),
        )
    candidate_regimen_label = _first_nonempty(
        preferred_regimen.get("regimen_label"),
        preferred_regimen.get("name"),
        preferred_regimen.get("display_label"),
        regimen_label(candidate_regimen_code),
        family_label(candidate_family),
        next_best_action.get("title"),
    )
    return candidate_family, candidate_regimen_code, candidate_regimen_label


def _collect_safety_blockers(
    preferred_regimen: dict[str, Any],
    comparative_eligibility_matrix: dict[str, Any],
    candidate_family: str,
) -> list[str]:
    blockers = _dedupe(
        list(preferred_regimen.get("contraindication_reasons") or [])
        + list(preferred_regimen.get("hard_blocks") or [])
        + list(preferred_regimen.get("safety_blockers") or [])
    )
    family_profile = dict(comparative_eligibility_matrix.get(candidate_family) or {})
    if _lower(family_profile.get("eligibility_status")) in _SAFETY_STATUSES:
        blockers.extend(_dedupe(list(family_profile.get("hard_blocks") or [])))
        blockers.extend(_dedupe(list(family_profile.get("contraindication_reasons") or [])))
        blockers.extend(_dedupe(list(family_profile.get("safety_blockers") or [])))
    return _dedupe(blockers)


def _build_capture_actions(
    *,
    required_fields: list[str],
    decision_input_requirements: dict[str, Any],
    advanced_release_gate: dict[str, Any],
    staging_adjudication_bundle: dict[str, Any],
    advanced_followup_bundle: dict[str, Any],
    supportive_care_toxicity_readiness_bundle: dict[str, Any],
    treatment_shaping_companion_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    gate_fields = _dedupe(
        list(advanced_release_gate.get("hard_blocking_inputs") or [])
        + list(advanced_release_gate.get("decision_blocking_inputs") or [])
    )
    if gate_fields:
        actions.append(
            {
                "key": "therapeutic_readiness_remaining_gate_fields",
                "title": "Cerrar adjudicación clínica antes de liberar tratamiento",
                "summary": "Persisten campos que cambian la ruta terapéutica o la seguridad de liberación.",
                "raw_fields": gate_fields,
                "fields": gate_fields,
                "display_fields_summary": _display_fields(gate_fields),
                "focus": "therapeutic_readiness",
                "capture_target": "followup",
            }
        )
    for source_key in (
        "capture_block",
        "monitoring_capture_block",
        "restaging_capture_block",
        "palliative_capture_block",
    ):
        block = decision_input_requirements.get(source_key)
        if not isinstance(block, dict) or not block:
            continue
        fields = _dedupe(list(block.get("fields") or block.get("raw_fields") or []))
        actions.append(
            {
                "key": source_key,
                **block,
                "raw_fields": fields,
                "fields": fields,
                "display_fields_summary": list(block.get("display_fields_summary") or _display_fields(fields)),
            }
        )
    for bundle_key, bundle in (
        ("staging_adjudication", staging_adjudication_bundle),
        ("advanced_followup", advanced_followup_bundle),
        ("supportive_care", supportive_care_toxicity_readiness_bundle),
    ):
        for index, action in enumerate(list(bundle.get("capture_actions") or [])):
            if not isinstance(action, dict):
                continue
            fields = _dedupe(list(action.get("fields") or action.get("raw_fields") or []))
            actions.append(
                {
                    "key": _first_nonempty(action.get("key"), f"{bundle_key}_capture_{index + 1}"),
                    **action,
                    "raw_fields": fields,
                    "fields": fields,
                    "display_fields_summary": list(action.get("display_fields_summary") or _display_fields(fields)),
                }
            )
    for index, action in enumerate(treatment_shaping_companion_actions):
        if not isinstance(action, dict):
            continue
        fields = _dedupe(list(action.get("fields") or action.get("raw_fields") or []))
        actions.append(
            {
                "key": _first_nonempty(action.get("key"), f"treatment_shaping_companion_{index + 1}"),
                **action,
                "raw_fields": fields,
                "fields": fields,
                "display_fields_summary": list(action.get("display_fields_summary") or _display_fields(fields)),
            }
        )
    if required_fields and not actions:
        actions.append(
            {
                "key": "therapeutic_readiness_missing_inputs",
                "title": "Completar datos para liberar tratamiento",
                "summary": "Cerrar los campos faltantes que sostienen la decisión terapéutica.",
                "raw_fields": list(required_fields),
                "fields": list(required_fields),
                "display_fields_summary": _display_fields(required_fields),
                "focus": "therapeutic_readiness",
                "capture_target": "followup",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        key = _first_nonempty(action.get("key"), action.get("title"))
        fields_key = ",".join(action.get("raw_fields") or action.get("fields") or [])
        signature = f"{key}|{fields_key}"
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(action)
    return deduped


def _readiness_summary(status: str, candidate_label: str, blockers: list[str]) -> str:
    if status == "ready_to_release":
        return f"{candidate_label or 'La terapia seleccionada'} queda lista para liberación clínica documentada."
    if status == "blocked_by_safety":
        return "La opción seleccionada queda bloqueada por seguridad o contraindicación documentada."
    if status == "palliative_priority":
        return "La prioridad clínica dominante es soporte/paliación; la terapia oncológica debe reabrirse contra objetivos de cuidado."
    if status == "blocked_by_missing_data":
        return "La liberación queda bloqueada hasta cerrar datos críticos que cambian estadio, elegibilidad o seguridad."
    if blockers:
        return "La liberación es condicional: " + blockers[0]
    return "La liberación terapéutica sigue condicionada a cierre de brechas clínicas visibles."


def build_therapeutic_readiness_bundle(
    *,
    state: str = "",
    phenotype_state: str = "",
    preferred_regimen: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    comparative_eligibility_matrix: dict[str, Any] | None = None,
    systemic_regimen_scope_contract: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
    palliative_transition_bundle: dict[str, Any] | None = None,
    survivorship_transition_bundle: dict[str, Any] | None = None,
    therapeutic_window_bundle: dict[str, Any] | None = None,
    active_regimen_monitoring_package: dict[str, Any] | None = None,
    recommendation_block_status: str = "",
    recommendation_block_reason: str = "",
    allowed_actions_while_blocked: list[dict[str, Any]] | None = None,
    signals: dict[str, Any] | None = None,
    advanced_followup_bundle: dict[str, Any] | None = None,
    staging_adjudication_bundle: dict[str, Any] | None = None,
    supportive_care_toxicity_readiness_bundle: dict[str, Any] | None = None,
    advanced_release_gate: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = _text(state)
    phenotype_state = _text(phenotype_state or state)
    preferred_regimen = dict(preferred_regimen or {})
    next_best_action = dict(next_best_action or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    comparative_eligibility_matrix = dict(comparative_eligibility_matrix or {})
    systemic_regimen_scope_contract = dict(systemic_regimen_scope_contract or {})
    care_intent_contract = dict(care_intent_contract or {})
    palliative_transition_bundle = dict(palliative_transition_bundle or {})
    survivorship_transition_bundle = dict(survivorship_transition_bundle or {})
    therapeutic_window_bundle = dict(therapeutic_window_bundle or {})
    active_regimen_monitoring_package = dict(active_regimen_monitoring_package or {})
    signals = dict(signals or {})
    advanced_followup_bundle = dict(advanced_followup_bundle or {})
    staging_adjudication_bundle = dict(staging_adjudication_bundle or {})
    supportive_care_toxicity_readiness_bundle = dict(supportive_care_toxicity_readiness_bundle or {})
    advanced_release_gate = dict(advanced_release_gate or {})
    clinical_fact_bundle = dict(clinical_fact_bundle or {})

    candidate_family, candidate_regimen_code, candidate_regimen_label = _candidate_from_inputs(
        preferred_regimen,
        next_best_action,
        comparative_eligibility_matrix,
    )
    candidate_family_label = _first_nonempty(
        preferred_regimen.get("family_label"),
        family_label(candidate_family),
        candidate_family,
    )

    hard_inputs = _dedupe(list(decision_input_requirements.get("hard_blocking_inputs") or []))
    decision_inputs = _dedupe(
        list(decision_input_requirements.get("decision_blocking_inputs") or [])
        + list(decision_input_requirements.get("blocking_inputs") or [])
    )
    confidence_inputs = _dedupe(list(decision_input_requirements.get("confidence_decay_inputs") or []))
    gate_hard_inputs = _dedupe(list(advanced_release_gate.get("hard_blocking_inputs") or []))
    gate_decision_inputs = _dedupe(list(advanced_release_gate.get("decision_blocking_inputs") or []))
    required_to_release = _dedupe(
        hard_inputs
        + gate_hard_inputs
        + decision_inputs
        + gate_decision_inputs
        + list(preferred_regimen.get("required_missing_fields") or [])
    )

    family_missing = (decision_input_requirements.get("family_missing_inputs") or {}).get(candidate_family)
    family_stale = (decision_input_requirements.get("family_stale_inputs") or {}).get(candidate_family)
    required_to_release = _dedupe(required_to_release + list(family_missing or []))
    stale_inputs = _dedupe(
        list(preferred_regimen.get("stale_inputs") or [])
        + list(family_stale or [])
        + confidence_inputs
    )

    safety_blockers = _collect_safety_blockers(
        preferred_regimen,
        comparative_eligibility_matrix,
        candidate_family,
    )
    palliative_priority = bool(
        _lower(care_intent_contract.get("supportive_priority")) in _PALLIATIVE_REDIRECT_VALUES
        or _lower(care_intent_contract.get("palliative_trigger_status")) in _PALLIATIVE_REDIRECT_VALUES
        or _lower(palliative_transition_bundle.get("care_mode")) in _PALLIATIVE_REDIRECT_VALUES
        or _lower(palliative_transition_bundle.get("trigger_status")) in _PALLIATIVE_REDIRECT_VALUES
    )

    release_blockers = _dedupe(
        list(decision_input_requirements.get("why_these_fields_now") or [])
        + list(advanced_release_gate.get("release_gate_reasons") or [])
        + [recommendation_block_reason]
    )
    if required_to_release and not release_blockers:
        release_blockers.append(
            "Faltan datos críticos que cambian estadio, elegibilidad o seguridad terapéutica: "
            + ", ".join(required_to_release[:5])
        )
    release_blockers = _dedupe(release_blockers)

    if palliative_priority:
        readiness_status = "palliative_priority"
    elif safety_blockers:
        readiness_status = "blocked_by_safety"
    elif gate_hard_inputs or _lower(recommendation_block_status) in _BLOCK_STATUS_HARD or hard_inputs:
        readiness_status = "blocked_by_missing_data"
    elif gate_decision_inputs or decision_inputs or stale_inputs or _lower(recommendation_block_status) in _BLOCK_STATUS_PROVISIONAL:
        readiness_status = "conditional_pending_closure"
    else:
        readiness_status = "ready_to_release"

    release_confidence_status = _first_nonempty(
        advanced_release_gate.get("release_confidence_status"),
        "blocked" if readiness_status in {"blocked_by_missing_data", "blocked_by_safety"} else "degraded" if readiness_status == "conditional_pending_closure" else "supported",
    )
    monitoring_gate_status = _first_nonempty(
        advanced_release_gate.get("monitoring_gate_status"),
        "blocked_by_missing_data" if readiness_status == "blocked_by_missing_data" else "conditional_pending_closure" if readiness_status == "conditional_pending_closure" else "supported",
    )
    adjudication_gate_status = _first_nonempty(
        advanced_release_gate.get("adjudication_gate_status"),
        "blocked_by_missing_data" if gate_hard_inputs else "conditional_pending_closure" if gate_decision_inputs else "supported",
    )

    next_best_action_if_not_ready = {}
    if readiness_status != "ready_to_release":
        next_best_action_if_not_ready = {
            "title": "Cerrar brechas antes de liberar tratamiento",
            "rationale": release_blockers[0] if release_blockers else "La decisión requiere datos adicionales antes de liberarse.",
            "required_fields": required_to_release,
            "display_required_fields": _display_fields(required_to_release),
        }
        if next_best_action.get("title"):
            next_best_action_if_not_ready["source_action_title"] = next_best_action.get("title")

    treatment_shaping_companion_inputs = _dedupe(
        list(decision_input_requirements.get("treatment_shaping_companion_inputs") or [])
    )
    treatment_shaping_companion_actions = [
        dict(item)
        for item in list(decision_input_requirements.get("treatment_shaping_companion_actions") or [])
        if isinstance(item, dict)
    ]

    capture_actions = _build_capture_actions(
        required_fields=required_to_release,
        decision_input_requirements=decision_input_requirements,
        advanced_release_gate=advanced_release_gate,
        staging_adjudication_bundle=staging_adjudication_bundle,
        advanced_followup_bundle=advanced_followup_bundle,
        supportive_care_toxicity_readiness_bundle=supportive_care_toxicity_readiness_bundle,
        treatment_shaping_companion_actions=treatment_shaping_companion_actions,
    )

    traceable_evidence_requirements = _build_traceability_requirements(
        state=state,
        candidate_family=candidate_family,
        required_fields=required_to_release,
        stale_fields=stale_inputs,
        decision_input_requirements=decision_input_requirements,
        preferred_regimen=preferred_regimen,
        comparative_eligibility_matrix=comparative_eligibility_matrix,
    )

    competing_intent = {"status": "aligned", "reason": ""}
    if palliative_priority:
        competing_intent = {
            "status": "palliative_priority",
            "reason": _first_nonempty(
                palliative_transition_bundle.get("care_goal"),
                care_intent_contract.get("care_goal"),
                "La agenda de soporte/paliación domina la decisión de hoy.",
            ),
        }
    elif care_intent_contract:
        normalized_care_family = _family_from_action(care_intent_contract.get("recommendation_family"))
        if normalized_care_family and candidate_family and normalized_care_family != candidate_family:
            compatible = {
                ("salvage_rt_family", "salvage"),
                ("salvage_rt_family", "ruta de rescate"),
            }
            if (candidate_family, _lower(care_intent_contract.get("recommendation_family"))) not in compatible:
                competing_intent = {
                    "status": "requires_review",
                    "reason": "La intención de cuidado y la familia terapéutica seleccionada no están plenamente alineadas.",
                }

    breakdown = build_therapy_readiness_breakdown(
        state=state,
        candidate_family=candidate_family,
        candidate_regimen_code=candidate_regimen_code,
        readiness_status=readiness_status,
        comparative_eligibility_matrix=comparative_eligibility_matrix,
        next_best_action_if_not_ready=next_best_action_if_not_ready,
        traceable_evidence_requirements=traceable_evidence_requirements,
        active_copilot_bundle={},
    )

    therapy_rationale_entries = list(breakdown.get("therapy_rationale_entries") or [])
    release_status_by_therapy = dict(breakdown.get("release_status_by_therapy") or {})
    hard_blockers_by_therapy = dict(breakdown.get("hard_blockers_by_therapy") or {})

    supportive_status = _text(
        supportive_care_toxicity_readiness_bundle.get("supportive_readiness_status") or "ready"
    )
    supportive_priority = _text(
        supportive_care_toxicity_readiness_bundle.get("supportive_priority") or "background"
    )
    required_support_actions = _dedupe(
        list(supportive_care_toxicity_readiness_bundle.get("required_support_actions") or [])
    )
    hard_support_blockers = _dedupe(
        list(supportive_care_toxicity_readiness_bundle.get("hard_support_blockers") or [])
    )
    recommended_supportive_referrals = _dedupe(
        list(supportive_care_toxicity_readiness_bundle.get("recommended_referrals") or [])
    )

    selected_therapy_key = _first_nonempty(candidate_regimen_code, candidate_family)
    selected_support = {}
    family_support_map = dict(
        supportive_care_toxicity_readiness_bundle.get("sustainability_status_by_therapy") or {}
    )
    if candidate_family:
        selected_support = dict(family_support_map.get(candidate_family) or {})
    if selected_therapy_key and selected_support:
        release_status_by_therapy.setdefault(selected_therapy_key, {})
        release_status_by_therapy[selected_therapy_key].update(
            {
                "supportive_readiness_status": selected_support.get("status") or supportive_status,
                "required_support_actions": list(selected_support.get("required_support_actions") or required_support_actions),
                "hard_support_blockers": list(selected_support.get("hard_support_blockers") or hard_support_blockers),
                "why_support_changes_choice": list(selected_support.get("why_support_changes_choice") or []),
            }
        )
        if selected_support.get("status") in {"co_manage_required", "blocking_support_gap"}:
            release_status_by_therapy[selected_therapy_key]["release_status"] = selected_support.get("status")
            for entry in therapy_rationale_entries:
                if entry.get("therapy_key") == selected_therapy_key:
                    entry["release_status"] = selected_support.get("status")
                    entry["supportive_readiness_status"] = selected_support.get("status")
                    entry["required_support_actions"] = list(
                        selected_support.get("required_support_actions") or required_support_actions
                    )
                    entry["hard_support_blockers"] = list(
                        selected_support.get("hard_support_blockers") or hard_support_blockers
                    )
                    entry["why_support_changes_choice"] = list(
                        selected_support.get("why_support_changes_choice") or []
                    )

    pre_evidence_bundle = {
        "readiness_status": readiness_status,
        "therapy_rationale_entries": therapy_rationale_entries,
        "release_status_by_therapy": release_status_by_therapy,
    }
    evidence_bundle = build_therapy_evidence_currentness_bundle(
        state=state,
        clinical_fact_bundle=clinical_fact_bundle,
        therapeutic_readiness_bundle=pre_evidence_bundle,
        signals=signals,
        decision_input_requirements=decision_input_requirements,
        staging_adjudication_bundle=staging_adjudication_bundle,
    )
    if evidence_bundle.get("available"):
        therapy_rationale_entries = list(evidence_bundle.get("therapy_rationale_entries") or therapy_rationale_entries)
        release_status_by_therapy = dict(evidence_bundle.get("release_status_by_therapy") or release_status_by_therapy)

    selected_therapy_release_status = _first_nonempty(
        (release_status_by_therapy.get(selected_therapy_key) or {}).get("release_status"),
        evidence_bundle.get("selected_therapy_release_status"),
        readiness_status,
    )
    selected_therapy_evidence_status = _first_nonempty(
        evidence_bundle.get("selected_therapy_evidence_status"),
        "unknown",
    )
    refresh_actions = _dedupe(list(evidence_bundle.get("refresh_actions") or []))

    return {
        "available": True,
        "state": state,
        "phenotype_state": phenotype_state,
        "candidate_family": candidate_family,
        "candidate_family_label": candidate_family_label,
        "candidate_regimen_code": candidate_regimen_code,
        "candidate_regimen_label": candidate_regimen_label,
        "readiness_status": readiness_status,
        "release_confidence_status": release_confidence_status,
        "monitoring_gate_status": monitoring_gate_status,
        "adjudication_gate_status": adjudication_gate_status,
        "recommendation_block_status": recommendation_block_status,
        "recommendation_block_reason": recommendation_block_reason,
        "allowed_actions_while_blocked": list(allowed_actions_while_blocked or []),
        "release_blockers": release_blockers,
        "display_release_blockers": [normalize_field_label(item) if "_" in item and " " not in item else item for item in release_blockers],
        "safety_blockers": safety_blockers,
        "display_safety_blockers": [normalize_field_label(item) if "_" in item and " " not in item else item for item in safety_blockers],
        "required_to_release": required_to_release,
        "display_required_to_release": _display_fields(required_to_release),
        "stale_inputs": stale_inputs,
        "display_stale_inputs": _display_fields(stale_inputs),
        "confidence_decay_inputs": confidence_inputs,
        "next_best_action_if_not_ready": next_best_action_if_not_ready,
        "capture_actions": capture_actions,
        "traceable_evidence_requirements": traceable_evidence_requirements,
        "competing_intent": competing_intent,
        "treatment_shaping_companion_inputs": treatment_shaping_companion_inputs,
        "treatment_shaping_companion_actions": treatment_shaping_companion_actions,
        "therapeutic_window_bundle": therapeutic_window_bundle,
        "systemic_regimen_scope_contract": systemic_regimen_scope_contract,
        "care_intent_contract": care_intent_contract,
        "palliative_transition_bundle": palliative_transition_bundle,
        "survivorship_transition_bundle": survivorship_transition_bundle,
        "active_regimen_monitoring_package": active_regimen_monitoring_package,
        "advanced_followup_bundle": advanced_followup_bundle,
        "staging_adjudication_bundle": staging_adjudication_bundle,
        "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
        "advanced_release_gate": advanced_release_gate,
        "supportive_readiness_status": supportive_status,
        "supportive_priority": supportive_priority,
        "required_support_actions": required_support_actions,
        "hard_support_blockers": hard_support_blockers,
        "recommended_supportive_referrals": recommended_supportive_referrals,
        "selected_therapy_release_status": selected_therapy_release_status,
        "selected_therapy_evidence_status": selected_therapy_evidence_status,
        "refresh_actions": refresh_actions,
        "release_blocked_by_stale_evidence": bool(evidence_bundle.get("release_blocked_by_stale_evidence")),
        "evidence_currentness_by_therapy": dict(evidence_bundle.get("evidence_currentness_by_therapy") or {}),
        "evidence_currentness_by_family": dict(evidence_bundle.get("evidence_currentness_by_family") or {}),
        "evidence_dates_used": list(evidence_bundle.get("evidence_dates_used") or []),
        "traceability_gaps": list(evidence_bundle.get("traceability_gaps") or []),
        "stale_evidence_fields": list(evidence_bundle.get("stale_evidence_fields") or []),
        "aging_evidence_fields": list(evidence_bundle.get("aging_evidence_fields") or []),
        "therapy_rationale_entries": therapy_rationale_entries,
        "release_status_by_therapy": release_status_by_therapy,
        "hard_blockers_by_therapy": hard_blockers_by_therapy,
        "traceable_evidence_requirements_by_therapy": dict(
            breakdown.get("traceable_evidence_requirements_by_therapy") or {}
        ),
        "next_best_action_if_not_ready_by_therapy": dict(
            breakdown.get("next_best_action_if_not_ready_by_therapy") or {}
        ),
        "readiness_summary": _readiness_summary(readiness_status, candidate_regimen_label, release_blockers),
    }


__all__ = ["build_therapeutic_readiness_bundle"]
