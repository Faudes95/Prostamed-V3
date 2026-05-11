from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.advanced_therapy_decision_builder import (
    build_therapy_readiness_breakdown,
)
from prostanet.domains.patient_tracking.capture_surface import (
    display_capture_field_summary,
    enrich_capture_block,
)
from prostanet.domains.patient_tracking.therapy_evidence_currentness_builder import (
    build_therapy_evidence_currentness_bundle,
)
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.domains.patient_tracking.therapeutic_family_engine import family_label, regimen_family_code


_PARP_CODES = {
    "OLAPARIB",
    "RUCAPARIB",
    "TALAZOPARIB_ENZALUTAMIDE",
    "NIRAPARIB_ABIRATERONE",
}
_PSMA_CODES = {
    "LU177_PSMA617",
}
_SYSTEMIC_FAMILIES = {
    "arpi_family",
    "abiraterone_steroid_family",
    "taxane_family",
    "psma_rlt_family",
    "parp_family",
    "radium223_family",
    "immunotherapy_family",
}
_SALVAGE_FAMILIES = {
    "salvage_rt_family",
    "local_mdt_family",
}
_LOCALIZED_FAMILIES = {
    "active_surveillance_family",
    "surveillance_family",
    "surgery_family",
    "radiotherapy_family",
    "multimodal_local_family",
}
_SYSTEMIC_BUCKET = "systemic"
_SALVAGE_BUCKET = "salvage_local"
_LOCALIZED_BUCKET = "localized_management"


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _candidate_from_matrix(
    comparative_eligibility_matrix: dict[str, Any],
) -> tuple[str, str, str]:
    ranked_profiles = sorted(
        [
            dict(profile)
            for profile in dict(comparative_eligibility_matrix or {}).values()
            if isinstance(profile, dict)
        ],
        key=lambda item: float(item.get("comparative_priority_score") or 0),
        reverse=True,
    )
    for profile in ranked_profiles:
        ranking = dict(profile.get("variant_ranking") or {})
        regimen_code = str(ranking.get("preferred_regimen_code") or "").strip()
        if not regimen_code:
            continue
        return (
            str(profile.get("family_code") or regimen_family_code(regimen_code)),
            regimen_code,
            _first_nonempty(
                ranking.get("preferred_regimen_label"),
                regimen_label(regimen_code),
            ),
        )
    return "", "", ""


def _resolve_candidate(
    *,
    preferred_regimen: dict[str, Any],
    active_regimen_monitoring_package: dict[str, Any],
    comparative_eligibility_matrix: dict[str, Any],
    next_best_action: dict[str, Any],
) -> dict[str, str]:
    preferred_regimen = dict(preferred_regimen or {})
    monitoring_package = dict(active_regimen_monitoring_package or {})
    next_best_action = dict(next_best_action or {})

    regimen_code = _first_nonempty(
        preferred_regimen.get("regimen_code"),
        monitoring_package.get("active_regimen_code"),
    )
    family_code = _first_nonempty(
        preferred_regimen.get("family_code"),
        monitoring_package.get("family_code"),
        regimen_family_code(regimen_code, fallback=""),
    )
    regimen_name = _first_nonempty(
        preferred_regimen.get("regimen_label"),
        monitoring_package.get("active_regimen_label"),
        regimen_label(regimen_code),
    )
    if regimen_code or family_code:
        return {
            "family_code": family_code,
            "family_label": _first_nonempty(
                preferred_regimen.get("family_label"),
                family_label(family_code),
            ),
            "regimen_code": regimen_code,
            "regimen_label": regimen_name,
            "source": "preferred_regimen" if preferred_regimen else "active_regimen_monitoring_package",
        }

    matrix_family, matrix_regimen, matrix_label = _candidate_from_matrix(comparative_eligibility_matrix)
    if matrix_family or matrix_regimen:
        return {
            "family_code": matrix_family,
            "family_label": family_label(matrix_family),
            "regimen_code": matrix_regimen,
            "regimen_label": matrix_label,
            "source": "comparative_eligibility_matrix",
        }

    family_text = _first_nonempty(next_best_action.get("recommendation_family"))
    return {
        "family_code": family_text,
        "family_label": family_label(family_text),
        "regimen_code": "",
        "regimen_label": "",
        "source": "next_best_action" if family_text else "",
    }


def _collect_required_to_release(
    *,
    candidate_family: str,
    decision_input_requirements: dict[str, Any],
    family_profile: dict[str, Any],
    preferred_regimen: dict[str, Any],
    active_regimen_monitoring_package: dict[str, Any],
) -> list[str]:
    decision_input_requirements = dict(decision_input_requirements or {})
    family_profile = dict(family_profile or {})
    preferred_regimen = dict(preferred_regimen or {})
    monitoring_package = dict(active_regimen_monitoring_package or {})

    fields = _dedupe(
        list(decision_input_requirements.get("hard_blocking_inputs") or [])
        + list(decision_input_requirements.get("decision_blocking_inputs") or [])
        + list((decision_input_requirements.get("family_missing_inputs") or {}).get(candidate_family) or [])
        + list((decision_input_requirements.get("family_stale_inputs") or {}).get(candidate_family) or [])
        + list(family_profile.get("missing_inputs") or [])
        + list(family_profile.get("stale_inputs") or [])
        + list(preferred_regimen.get("required_missing_fields") or [])
        + list(preferred_regimen.get("stale_inputs") or [])
    )
    if candidate_family and str(monitoring_package.get("family_code") or "") == candidate_family:
        fields = _dedupe(
            fields
            + list(monitoring_package.get("missing_inputs") or [])
            + list(monitoring_package.get("stale_inputs") or [])
            + list(monitoring_package.get("required_visit_fields") or [])
        )
    return fields


def _collect_safety_blockers(
    *,
    recommendation_block_status: str,
    recommendation_block_reason: str,
    family_profile: dict[str, Any],
    preferred_regimen: dict[str, Any],
) -> tuple[list[str], list[str]]:
    family_profile = dict(family_profile or {})
    preferred_regimen = dict(preferred_regimen or {})
    safety_blockers = _dedupe(
        list(family_profile.get("hard_blocks") or [])
        + list(preferred_regimen.get("hard_blocks") or [])
        + list(preferred_regimen.get("contraindication_reasons") or [])
    )
    safety_watchouts = _dedupe(
        list(family_profile.get("caution_drivers") or [])
        + list(preferred_regimen.get("caution_flags") or [])
        + list(preferred_regimen.get("safety_drivers_used") or [])
    )
    lowered_reason = str(recommendation_block_reason or "").strip().lower()
    if (
        str(recommendation_block_status or "").strip().lower() == "hard_stop"
        and not safety_blockers
        and any(token in lowered_reason for token in ("contraindic", "toxic", "seguridad", "variant", "neuroendocr", "small-cell"))
    ):
        safety_blockers = _dedupe(safety_blockers + [recommendation_block_reason])
    return safety_blockers, safety_watchouts


def _build_competing_intent(
    *,
    candidate_family: str,
    care_intent_contract: dict[str, Any],
    palliative_transition_bundle: dict[str, Any],
) -> dict[str, Any]:
    care_intent_contract = dict(care_intent_contract or {})
    palliative_transition_bundle = dict(palliative_transition_bundle or {})

    supportive_priority = _first_nonempty(
        care_intent_contract.get("supportive_priority"),
        palliative_transition_bundle.get("supportive_priority"),
    )
    care_goal = _first_nonempty(
        care_intent_contract.get("care_goal"),
        palliative_transition_bundle.get("care_goal"),
    )
    care_mode = _first_nonempty(
        palliative_transition_bundle.get("care_mode"),
        care_intent_contract.get("care_mode"),
    )
    trigger_status = _first_nonempty(
        care_intent_contract.get("palliative_trigger_status"),
        palliative_transition_bundle.get("trigger_status"),
    )
    intent_family = _first_nonempty(care_intent_contract.get("recommendation_family"))

    def _family_bucket(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        if any(
            marker in normalized
            for marker in (
                "reestadific",
                "re-stage",
                "restage",
                "reclasific",
                "reclassif",
                "fuera de nmcrpc",
                "confirmar progres",
                "confirmación de progres",
                "confirmacion de progres",
            )
        ):
            return ""
        if normalized in {
            "window_closure",
            "governance_block",
            "observe",
            "observation",
            "observation_family",
            "observación / backbone",
            "observacion / backbone",
            "molecular_restaging",
            "precision_oncology",
            "restaging",
            "restadificación",
            "restadificacion",
            "progression_confirmation",
            "confirmación crpc",
            "confirmacion crpc",
            "confirmación post-rt",
            "confirmacion post-rt",
            "crpc_verification",
        }:
            return ""
        if "seguimiento post " in normalized or "post-" in normalized and "seguimiento" in normalized:
            return ""
        if "post prostatectom" in normalized or "post-radiotherap" in normalized or "post radiotherap" in normalized:
            return ""
        if "followup" in normalized or "follow-up" in normalized:
            return ""
        if normalized in {
            "salvage",
            "ruta de rescate",
            "post_rt_salvage",
            "salvage_rt_family",
            "salvage / rt",
            "local_mdt_family",
            "control local / mdt",
            "ruta post-rt",
            "mdt",
        }:
            return _SALVAGE_BUCKET
        if normalized in {
            "localized_management",
            "active_surveillance_family",
            "surveillance_family",
            "surgery_family",
            "radiotherapy_family",
            "multimodal_local_family",
            "vigilancia activa",
            "vigilancia",
            "cirugía",
            "cirugia",
            "radioterapia",
            "multimodal local",
        }:
            return _LOCALIZED_BUCKET
        if normalized in {
            "systemic_intensification",
            "frontline_regimen",
            "arpi first-line",
            "arpi_family",
            "abiraterone_steroid_family",
            "taxane_family",
            "psma_rlt_family",
            "parp_family",
            "radium223_family",
            "immunotherapy_family",
            "arpi",
            "abiraterona + esteroide",
            "taxanos",
            "psma-rlt",
            "parp",
            "radio-223",
            "inmunoterapia",
        }:
            return _SYSTEMIC_BUCKET
        if any(
            marker in normalized
            for marker in (
                "enzalut",
                "apalut",
                "darolut",
                "abirater",
                "docetax",
                "cabazitax",
                "olapar",
                "talaz",
                "nirapar",
                "pluvicto",
                "luteci",
                "radium",
                "radio-223",
                "sipuleucel",
                "pembrol",
            )
        ):
            return _SYSTEMIC_BUCKET
        return normalized

    intent_bucket = _family_bucket(intent_family)
    candidate_bucket = _family_bucket(candidate_family) or _family_bucket(family_label(candidate_family))

    palliative_priority = (
        supportive_priority == "dominant"
        or care_mode in {"supportive_only", "hospice", "comfort_only"}
        or trigger_status in {"redirect_supportive_only", "hospice_candidate"}
    )
    competing_intent = (
        not palliative_priority
        and bool(intent_bucket)
        and bool(candidate_bucket)
        and intent_bucket != candidate_bucket
    )

    reason = ""
    if palliative_priority:
        reason = _first_nonempty(
            care_goal,
            palliative_transition_bundle.get("headline"),
            "El objetivo dominante actual prioriza soporte paliativo o control sintomático.",
        )
    elif competing_intent:
        reason = _first_nonempty(
            care_goal,
            care_intent_contract.get("headline"),
            f"El carril clínico activo hoy prioriza {family_label(intent_family)} por encima de {family_label(candidate_family)}.",
        )

    return {
        "available": bool(palliative_priority or competing_intent or care_goal or supportive_priority or trigger_status),
        "status": "palliative_priority" if palliative_priority else "blocked_by_competing_intent" if competing_intent else "aligned",
        "reason": reason,
        "care_goal": care_goal,
        "supportive_priority": supportive_priority,
        "care_mode": care_mode,
        "palliative_trigger_status": trigger_status,
        "recommendation_family": intent_family,
    }


def _traceable_requirement(
    *,
    key: str,
    label: str,
    required_fields: set[str],
    trigger_fields: set[str],
) -> dict[str, str]:
    status = "missing" if required_fields.intersection(trigger_fields) else "satisfied"
    return {"key": key, "label": label, "status": status}


def _build_traceable_evidence_requirements(
    *,
    state: str,
    candidate_family: str,
    candidate_regimen_code: str,
    required_to_release: list[str],
    signals: dict[str, Any],
) -> list[dict[str, str]]:
    state = str(state or "").strip()
    candidate_family = str(candidate_family or "").strip()
    candidate_regimen_code = str(candidate_regimen_code or "").strip()
    required_fields = {str(item) for item in list(required_to_release or [])}
    signal_text = {str(key) for key in dict(signals or {}).keys()}

    requirements: list[dict[str, str]] = []
    if state in {"recurrence_bcr", "post_radiotherapy_or_local_salvage"} or candidate_family in _SALVAGE_FAMILIES:
        requirements.extend(
            [
                _traceable_requirement(
                    key="psa_dynamics",
                    label="PSA longitudinal y cinética documentadas para definir la ventana de salvage.",
                    required_fields=required_fields,
                    trigger_fields={"psa", "psa_history", "psadt_months", "time_to_recurrence_months"},
                ),
                _traceable_requirement(
                    key="local_salvage_feasibility",
                    label="Factibilidad local y restadificación dirigidas antes de liberar rescate curativo.",
                    required_fields=required_fields,
                    trigger_fields={"psma_positive", "psma_stage_after_psma", "salvage_local_feasible", "biopsy_proven_local_recurrence", "mpmri_recurrence_suspected"},
                ),
            ]
        )
    if state in {"adt_progression_verification", "m0_crpc"}:
        trigger_fields = {"testosterone", "testosterone_history", "current_treatment", "drug_scheme"}
        if "castrate_testosterone_status" not in signal_text:
            trigger_fields.add("castrate_testosterone_status")
        requirements.extend(
            [
                _traceable_requirement(
                    key="castrate_confirmation",
                    label="Testosterona en rango de castración y backbone ADT documentados antes de etiquetar CRPC.",
                    required_fields=required_fields,
                    trigger_fields=trigger_fields,
                ),
                _traceable_requirement(
                    key="restaging_negative_context",
                    label="Imagen negativa o contexto de progresión no metastásica trazable.",
                    required_fields=required_fields,
                    trigger_fields={"conventional_imaging_current", "psma_positive", "metastatic_disease_known"},
                ),
            ]
        )
    if state.startswith("mcspc_") or state == "mcspc_high_volume":
        requirements.append(
            _traceable_requirement(
                key="mhspc_safety_readiness",
                label="Fragilidad, cognición, DDI, hígado, CV y aptitud a taxanos cerrados antes de liberar intensificación.",
                required_fields=required_fields,
                trigger_fields={"mini_cog_score", "weight_kg", "height_cm", "weight_loss_6m_kg", "ddi_review_status", "child_pugh_score", "cv_risk_documented", "peripheral_neuropathy_grade"},
            )
        )
    if state == "localized_initial":
        requirements.append(
            _traceable_requirement(
                key="localized_tradeoffs",
                label="Riesgo, fitness/comorbilidad objetivos, factibilidad local y prioridades del paciente documentadas antes de liberar vigilancia, cirugía o RT.",
                required_fields=required_fields,
                trigger_fields={"ecog_score", "charlson_score", "frailty_status", "g8_score", "anesthesia_surgical_fitness", "radiotherapy_feasibility", "patient_priority_profile", "gleason_primary", "gleason_secondary", "clinical_tstage", "psad"},
            )
        )
    if state == "m1_crpc" or candidate_family == "parp_family" or candidate_regimen_code in _PARP_CODES:
        requirements.append(
            _traceable_requirement(
                key="molecular_traceability",
                label="Trazabilidad HRR/BRCA o biomarcador molecular obligatoria antes de liberar PARP.",
                required_fields=required_fields,
                trigger_fields={"hrr_status", "hrr_gene", "genomic_test_done", "molecular_report_date", "genomic_profile"},
            )
        )
    if state == "m1_crpc" or candidate_family == "psma_rlt_family" or candidate_regimen_code in _PSMA_CODES:
        requirements.append(
            _traceable_requirement(
                key="psma_traceability",
                label="PSMA PET/CT concordante y documentado antes de liberar PSMA-RLT.",
                required_fields=required_fields,
                trigger_fields={"psma_positive", "psma_stage_after_psma", "psma_uptake_pattern", "psma_imaging_date"},
            )
        )
    return requirements


def _capture_blocks_from_requirements(
    decision_input_requirements: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    blocks: list[tuple[str, dict[str, Any]]] = []
    for key, value in dict(decision_input_requirements or {}).items():
        if not key.endswith("capture_block"):
            continue
        if not isinstance(value, dict):
            continue
        block = enrich_capture_block(value, limit=24)
        if not block.get("fields"):
            continue
        blocks.append((key, block))
    return blocks


def _build_release_capture_actions(
    *,
    required_to_release: list[str],
    decision_input_requirements: dict[str, Any],
    readiness_status: str,
    candidate_family: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    required_fields = {str(field) for field in list(required_to_release or [])}
    actions: list[dict[str, Any]] = []
    release_blocker_capture_map: dict[str, str] = {}

    for key, block in _capture_blocks_from_requirements(decision_input_requirements):
        raw_fields = [str(field) for field in list(block.get("fields") or [])]
        relevant_fields = [field for field in raw_fields if field in required_fields]
        if not relevant_fields:
            continue
        action = {
            "key": key,
            "title": str(block.get("title") or "Completar captura clínica dirigida"),
            "summary": str(block.get("summary") or "Cerrar brechas de liberación terapéutica."),
            "raw_fields": raw_fields,
            "fields": raw_fields,
            "display_fields_summary": list(block.get("display_fields_summary") or display_capture_field_summary(raw_fields, limit=24)),
            "capture_target": str(block.get("capture_target") or "followup"),
            "focus": str(block.get("focus") or ""),
            "decision_affected": str(block.get("focus") or candidate_family or "therapeutic_readiness"),
            "form_scope": {
                "mode": "capture_block",
                "focus": str(block.get("focus") or candidate_family or "therapeutic_readiness"),
                "capture_fields": raw_fields,
            },
            "display_group": "Liberación terapéutica",
            "display_cta": "Completar captura dirigida",
            "display_why_now": str(block.get("summary") or "Este bloque cierra datos decisivos para liberar la terapia."),
            "display_impact": "Si se completa hoy, puede recalcular el readiness terapéutico visible.",
            "linked_agenda_ids": list(block.get("linked_agenda_ids") or []),
        }
        actions.append(action)
        for field in relevant_fields:
            release_blocker_capture_map.setdefault(field, key)

    if not actions and required_fields:
        fallback_fields = list(required_to_release or [])
        actions.append(
            {
                "key": "therapeutic_readiness_fallback",
                "title": "Cerrar brechas para liberar terapia",
                "summary": "Completa el bloque clínico faltante antes de publicar una recomendación final.",
                "raw_fields": fallback_fields,
                "fields": fallback_fields,
                "display_fields_summary": display_capture_field_summary(fallback_fields, limit=24),
                "capture_target": "followup",
                "focus": "therapeutic_readiness",
                "decision_affected": candidate_family or "therapeutic_readiness",
                "form_scope": {
                    "mode": "capture_block",
                    "focus": candidate_family or "therapeutic_readiness",
                    "capture_fields": fallback_fields,
                },
                "display_group": "Liberación terapéutica",
                "display_cta": "Completar captura dirigida",
                "display_why_now": "La terapia preferida sigue condicionada a cerrar datos visibles.",
                "display_impact": "Si se completa hoy, puede recalcular el readiness terapéutico visible.",
                "linked_agenda_ids": [],
            }
        )
        for field in fallback_fields:
            release_blocker_capture_map.setdefault(str(field), "therapeutic_readiness_fallback")

    return actions, release_blocker_capture_map


def _merge_capture_actions(
    *groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    merged: list[dict[str, Any]] = []
    field_map: dict[str, str] = {}
    seen_keys: set[str] = set()
    for group in groups:
        for action in list(group or []):
            current = dict(action or {})
            key = _first_nonempty(
                current.get("key"),
                current.get("title"),
                repr(sorted(str(field) for field in list(current.get("fields") or current.get("raw_fields") or []))),
            )
            if key in seen_keys:
                for field in list(current.get("fields") or current.get("raw_fields") or []):
                    text = str(field or "").strip()
                    if text:
                        field_map.setdefault(text, key)
                continue
            seen_keys.add(key)
            merged.append(current)
            for field in list(current.get("fields") or current.get("raw_fields") or []):
                text = str(field or "").strip()
                if text:
                    field_map.setdefault(text, key)
    return merged, field_map


def _prioritize_capture_actions(
    *,
    actions: list[dict[str, Any]],
    required_to_release: list[str],
    advanced_release_gate: dict[str, Any],
    staging_adjudication_bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    required_fields = {
        str(field).strip()
        for field in list(required_to_release or [])
        if str(field or "").strip()
    }
    hard_fields = {
        str(field).strip()
        for field in list(advanced_release_gate.get("hard_blocking_inputs") or [])
        if str(field or "").strip()
    }
    decision_fields = {
        str(field).strip()
        for field in list(advanced_release_gate.get("decision_blocking_inputs") or [])
        if str(field or "").strip()
    }
    confidence_fields = {
        str(field).strip()
        for field in list(advanced_release_gate.get("confidence_decay_inputs") or [])
        if str(field or "").strip()
    }
    adjudication_fields = {
        str(field).strip()
        for field in (
            list(staging_adjudication_bundle.get("missing_critical_inputs") or [])
            + list(staging_adjudication_bundle.get("discordant_fields") or [])
            + list(staging_adjudication_bundle.get("superseded_evidence") or [])
        )
        if str(field or "").strip()
    }
    concordance_status = str(staging_adjudication_bundle.get("concordance_status") or "").strip()
    adjudication_release_status = str(
        staging_adjudication_bundle.get("adjudication_release_status") or ""
    ).strip()
    if (
        bool(staging_adjudication_bundle.get("psma_only_upstaging"))
        or concordance_status in {"discordant", "context_changed", "insufficient_concordance"}
        or adjudication_release_status in {"blocked_pending_adjudication", "review_needed"}
    ):
        adjudication_fields.update(
            {
                "conventional_imaging_status",
                "psma_positive",
                "psma_pet_done",
                "psma_negative_dominant_lesions",
            }
        )

    def _score(action: dict[str, Any], index: int) -> tuple[int, int, int, int, int]:
        fields = {
            str(field).strip()
            for field in list(action.get("fields") or action.get("raw_fields") or [])
            if str(field or "").strip()
        }
        focus = str(action.get("focus") or "").strip()
        key = str(action.get("key") or "").strip()
        hard_overlap = len(fields.intersection(hard_fields))
        adjudication_overlap = len(fields.intersection(adjudication_fields))
        decision_overlap = len(fields.intersection(decision_fields))
        confidence_overlap = len(fields.intersection(confidence_fields))
        required_overlap = len(fields.intersection(required_fields))
        score = 0
        score += hard_overlap * 100
        score += adjudication_overlap * 80
        score += decision_overlap * 60
        score += confidence_overlap * 30
        score += required_overlap * 5
        if focus == "staging_adjudication":
            score += 40
        if key == "therapeutic_readiness_remaining_gate_fields":
            score += 35
        return (-score, -required_overlap, -hard_overlap, -adjudication_overlap, index)

    indexed_actions = list(enumerate([dict(action or {}) for action in list(actions or [])]))
    indexed_actions.sort(key=lambda pair: _score(pair[1], pair[0]))
    return [action for _, action in indexed_actions]


def _merge_supportive_release_status(
    current_release_status: str,
    supportive_status: str,
) -> str:
    current_release_status = str(current_release_status or "").strip()
    supportive_status = str(supportive_status or "").strip()
    if supportive_status == "blocking_support_gap":
        return "blocked_by_supportive_gap"
    if supportive_status == "co_manage_required" and current_release_status == "ready_to_release":
        return "co_manage_required"
    if supportive_status == "review_needed" and current_release_status == "ready_to_release":
        return "review_needed"
    return current_release_status


def _supportive_entry_snapshot(
    *,
    entry: dict[str, Any],
    supportive_bundle: dict[str, Any],
) -> dict[str, Any]:
    if not supportive_bundle:
        return {
            "supportive_readiness_status": "ready",
            "required_support_actions": [],
            "hard_support_blockers": [],
            "why_support_changes_choice": [],
        }
    sustainability = dict(supportive_bundle.get("sustainability_status_by_therapy") or {})
    by_therapy = (
        dict(sustainability.get(str(entry.get("therapy_key") or "")) or {})
        or dict(sustainability.get(str(entry.get("regimen_code") or "")) or {})
        or dict(sustainability.get(str(entry.get("family_code") or "")) or {})
    )
    return {
        "supportive_readiness_status": str(by_therapy.get("status") or supportive_bundle.get("supportive_readiness_status") or "ready"),
        "required_support_actions": list(by_therapy.get("required_support_actions") or supportive_bundle.get("required_support_actions") or []),
        "hard_support_blockers": list(by_therapy.get("hard_support_blockers") or supportive_bundle.get("hard_support_blockers") or []),
        "why_support_changes_choice": list(by_therapy.get("why_support_changes_choice") or []),
    }


def build_therapeutic_readiness_bundle(
    *,
    state: str,
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
    allowed_actions_while_blocked: list[str] | None = None,
    signals: dict[str, Any] | None = None,
    advanced_followup_bundle: dict[str, Any] | None = None,
    staging_adjudication_bundle: dict[str, Any] | None = None,
    supportive_care_toxicity_readiness_bundle: dict[str, Any] | None = None,
    advanced_release_gate: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = str(state or "").strip()
    phenotype_state = str(phenotype_state or state).strip()
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
    supportive_care_toxicity_readiness_bundle = dict(
        supportive_care_toxicity_readiness_bundle or {}
    )
    advanced_release_gate = dict(advanced_release_gate or {})
    clinical_fact_bundle = dict(clinical_fact_bundle or {})

    candidate = _resolve_candidate(
        preferred_regimen=preferred_regimen,
        active_regimen_monitoring_package=active_regimen_monitoring_package,
        comparative_eligibility_matrix=comparative_eligibility_matrix,
        next_best_action=next_best_action,
    )
    candidate_family = str(candidate.get("family_code") or "")
    candidate_regimen_code = str(candidate.get("regimen_code") or "")
    family_profile = dict(comparative_eligibility_matrix.get(candidate_family) or {})
    required_to_release = _collect_required_to_release(
        candidate_family=candidate_family,
        decision_input_requirements=decision_input_requirements,
        family_profile=family_profile,
        preferred_regimen=preferred_regimen,
        active_regimen_monitoring_package=active_regimen_monitoring_package,
    )
    required_to_release = _dedupe(
        required_to_release
        + list(advanced_release_gate.get("hard_blocking_inputs") or [])
        + list(advanced_release_gate.get("decision_blocking_inputs") or [])
        + list(advanced_release_gate.get("confidence_decay_inputs") or [])
    )
    display_required_to_release = (
        display_capture_field_summary(required_to_release, limit=24) or required_to_release
    )

    safety_blockers, safety_watchouts = _collect_safety_blockers(
        recommendation_block_status=recommendation_block_status,
        recommendation_block_reason=recommendation_block_reason,
        family_profile=family_profile,
        preferred_regimen=preferred_regimen,
    )
    competing_intent = _build_competing_intent(
        candidate_family=candidate_family,
        care_intent_contract=care_intent_contract,
        palliative_transition_bundle=palliative_transition_bundle,
    )

    window_summary = dict(therapeutic_window_bundle.get("opportunity_loss_summary") or {})
    top_active_window = dict(therapeutic_window_bundle.get("top_active_window") or {})
    release_blockers = list(advanced_release_gate.get("release_gate_reasons") or [])
    if str(recommendation_block_status or "").strip().lower() in {"hard_stop", "provisional"} and recommendation_block_reason:
        release_blockers.append(recommendation_block_reason)
    if family_profile.get("eligibility_status") == "conditional":
        release_blockers.append(
            f"La familia {family_label(candidate_family)} permanece condicional hasta cerrar dataset y recencia."
        )
    if top_active_window and str(top_active_window.get("opportunity_loss_risk") or "").lower() in {"possible", "confirmed"}:
        release_blockers.append(
            _first_nonempty(
                top_active_window.get("window_reason"),
                top_active_window.get("why_this_matters_now"),
            )
        )
    release_blockers = _dedupe(release_blockers)

    monitoring_gate_status = str(
        advanced_release_gate.get("monitoring_gate_status")
        or ("supported" if not advanced_followup_bundle else "conditional_pending_closure" if advanced_followup_bundle.get("missing_inputs") else "supported")
    )
    adjudication_gate_status = str(
        advanced_release_gate.get("adjudication_gate_status")
        or ("supported" if not staging_adjudication_bundle else "conditional_pending_closure" if staging_adjudication_bundle.get("missing_critical_inputs") else "supported")
    )
    release_confidence_status = str(
        advanced_release_gate.get("release_confidence_status")
        or ("degraded" if advanced_followup_bundle.get("confidence_status") == "degraded_by_missing_data" else "supported")
    )
    confidence_decay_reasons = _dedupe(
        list(advanced_release_gate.get("confidence_decay_reasons") or [])
    )

    if competing_intent.get("status") == "palliative_priority":
        readiness_status = "palliative_priority"
    elif competing_intent.get("status") == "blocked_by_competing_intent":
        readiness_status = "blocked_by_competing_intent"
    elif safety_blockers:
        readiness_status = "blocked_by_safety"
    elif (
        list(advanced_release_gate.get("hard_blocking_inputs") or [])
        or (required_to_release and str(recommendation_block_status or "").strip().lower() == "hard_stop")
    ):
        readiness_status = "blocked_by_missing_data"
    elif (
        list(advanced_release_gate.get("decision_blocking_inputs") or [])
        or list(advanced_release_gate.get("confidence_decay_inputs") or [])
        or required_to_release
        or str(recommendation_block_status or "").strip().lower() == "provisional"
    ):
        readiness_status = "conditional_pending_closure"
    elif not candidate_family and not candidate_regimen_code:
        readiness_status = "conditional_pending_closure"
    else:
        readiness_status = "ready_to_release"

    supportive_readiness_status = str(
        supportive_care_toxicity_readiness_bundle.get("supportive_readiness_status") or ""
    ).strip()
    if supportive_readiness_status == "blocking_support_gap" and readiness_status in {
        "ready_to_release",
        "conditional_pending_closure",
    }:
        readiness_status = "blocked_by_supportive_gap"
        release_blockers = _dedupe(
            release_blockers
            + list(supportive_care_toxicity_readiness_bundle.get("hard_support_blockers") or [])
            + [
                "La decisión oncológica no es clínicamente sostenible hoy sin cerrar soporte/toxicidad críticos."
            ]
        )

    traceable_evidence_requirements = _build_traceable_evidence_requirements(
        state=state,
        candidate_family=candidate_family,
        candidate_regimen_code=candidate_regimen_code,
        required_to_release=required_to_release,
        signals=signals,
    )
    capture_actions, release_blocker_capture_map = _build_release_capture_actions(
        required_to_release=required_to_release,
        decision_input_requirements=decision_input_requirements,
        readiness_status=readiness_status,
        candidate_family=candidate_family,
    )
    gate_capture_fields = {
        str(field)
        for field in (
            list(advanced_release_gate.get("hard_blocking_inputs") or [])
            + list(advanced_release_gate.get("decision_blocking_inputs") or [])
            + list(advanced_release_gate.get("confidence_decay_inputs") or [])
        )
        if str(field or "").strip()
    }
    advanced_capture_actions = [
        dict(action)
        for action in list(advanced_followup_bundle.get("capture_actions") or [])
        if gate_capture_fields.intersection(
            {str(field) for field in list(action.get("fields") or action.get("raw_fields") or []) if str(field or "").strip()}
        )
    ]
    adjudication_capture_actions = [
        dict(action)
        for action in list(staging_adjudication_bundle.get("capture_actions") or [])
        if gate_capture_fields.intersection(
            {str(field) for field in list(action.get("fields") or action.get("raw_fields") or []) if str(field or "").strip()}
        )
    ]
    companion_capture_actions = [
        dict(action)
        for action in list(decision_input_requirements.get("treatment_shaping_companion_actions") or [])
    ]
    capture_actions, gate_capture_map = _merge_capture_actions(
        capture_actions,
        advanced_capture_actions,
        adjudication_capture_actions,
        companion_capture_actions,
    )
    release_blocker_capture_map = {
        **gate_capture_map,
        **release_blocker_capture_map,
    }
    uncovered_gate_fields = [
        str(field)
        for field in list(required_to_release or [])
        if str(field or "").strip() and str(field) not in release_blocker_capture_map
    ]
    if uncovered_gate_fields:
        adjudication_missing_fields = {
            str(field)
            for field in list(staging_adjudication_bundle.get("missing_critical_inputs") or [])
            if str(field or "").strip()
        }
        fallback_focus = (
            "staging_adjudication"
            if adjudication_missing_fields.intersection(uncovered_gate_fields)
            else (candidate_family or "therapeutic_readiness")
        )
        fallback_action = {
            "key": "therapeutic_readiness_remaining_gate_fields",
            "title": (
                "Completar adjudicación y seguimiento decisivo"
                if fallback_focus == "staging_adjudication"
                else "Cerrar brechas residuales de liberación"
            ),
            "summary": release_blockers[0] if release_blockers else "Completa los campos remanentes antes de liberar la terapia visible.",
            "raw_fields": uncovered_gate_fields,
            "fields": uncovered_gate_fields,
            "display_fields_summary": display_capture_field_summary(uncovered_gate_fields, limit=24),
            "capture_target": "followup",
            "focus": fallback_focus,
            "decision_affected": candidate_family or "therapeutic_readiness",
            "form_scope": {
                "mode": "capture_block",
                "focus": fallback_focus,
                "capture_fields": uncovered_gate_fields,
            },
            "display_group": "Liberación terapéutica",
            "display_cta": "Completar captura dirigida",
            "display_why_now": release_blockers[0] if release_blockers else "Aún faltan datos estructurados para liberar la terapia visible.",
            "display_impact": "Si se completa hoy, puede recalcular el readiness terapéutico visible.",
            "linked_agenda_ids": [],
        }
        capture_actions.append(fallback_action)
        for field in uncovered_gate_fields:
            release_blocker_capture_map[str(field)] = fallback_action["key"]
    capture_actions = _prioritize_capture_actions(
        actions=capture_actions,
        required_to_release=required_to_release,
        advanced_release_gate=advanced_release_gate,
        staging_adjudication_bundle=staging_adjudication_bundle,
    )
    readiness_summary = {
        "ready_to_release": "Liberación terapéutica disponible hoy.",
        "conditional_pending_closure": "La terapia preferida sigue condicionada a cerrar brechas visibles.",
        "blocked_by_missing_data": "No debe liberarse la terapia hasta cerrar datos decisivos faltantes.",
        "blocked_by_supportive_gap": "La terapia no es clínicamente sostenible hoy hasta cerrar brechas críticas de soporte/toxicidad.",
        "blocked_by_safety": "La seguridad o contraindicación actual bloquea la liberación terapéutica.",
        "blocked_by_competing_intent": "Existe un carril clínico dominante que hoy desplaza esta terapia.",
        "palliative_priority": "El objetivo clínico dominante hoy prioriza soporte/paliación sobre intensificación oncológica.",
    }
    next_best_action_if_not_ready = {
        "title": _first_nonempty(
            (capture_actions[0] or {}).get("title") if capture_actions else "",
            top_active_window.get("what_closes_this_window"),
            next_best_action.get("title"),
            "Cerrar brechas decisionales antes de liberar terapia",
        ),
        "rationale": _first_nonempty(
            release_blockers[0] if release_blockers else "",
            competing_intent.get("reason"),
            recommendation_block_reason,
            family_profile.get("winner_reason"),
            readiness_summary.get(readiness_status),
        ),
        "immediate_actions": list(next_best_action.get("immediate_actions") or []),
        "required_fields": required_to_release,
        "display_required_fields": display_required_to_release,
    }
    if not next_best_action_if_not_ready["immediate_actions"] and display_required_to_release:
        next_best_action_if_not_ready["immediate_actions"] = [
            f"Completar: {', '.join(display_required_to_release[:4])}"
        ]
    therapy_breakdown = build_therapy_readiness_breakdown(
        state=state,
        candidate_family=candidate_family,
        candidate_regimen_code=candidate_regimen_code,
        readiness_status=readiness_status,
        comparative_eligibility_matrix=comparative_eligibility_matrix,
        next_best_action_if_not_ready=next_best_action_if_not_ready,
        traceable_evidence_requirements=traceable_evidence_requirements,
    )
    currentness_bundle = build_therapy_evidence_currentness_bundle(
        state=state,
        clinical_fact_bundle=clinical_fact_bundle,
        therapeutic_readiness_bundle={
            "readiness_status": readiness_status,
            "therapy_rationale_entries": list(therapy_breakdown.get("therapy_rationale_entries") or []),
            "release_status_by_therapy": dict(therapy_breakdown.get("release_status_by_therapy") or {}),
        },
        comparative_eligibility_matrix=comparative_eligibility_matrix,
        staging_adjudication_bundle=staging_adjudication_bundle,
        signals=signals,
        decision_input_requirements=decision_input_requirements,
    )

    supportive_enriched_entries: list[dict[str, Any]] = []
    supportive_release_status_by_therapy = dict(currentness_bundle.get("release_status_by_therapy") or {})
    for item in list(currentness_bundle.get("therapy_rationale_entries") or []):
        entry = dict(item or {})
        supportive_snapshot = _supportive_entry_snapshot(
            entry=entry,
            supportive_bundle=supportive_care_toxicity_readiness_bundle,
        )
        merged_release_status = _merge_supportive_release_status(
            str(entry.get("release_status") or ""),
            supportive_snapshot.get("supportive_readiness_status") or "",
        )
        entry = {
            **entry,
            "release_status": merged_release_status,
            **supportive_snapshot,
        }
        supportive_enriched_entries.append(entry)
        therapy_key = str(entry.get("therapy_key") or "").strip()
        if therapy_key:
            supportive_release_status_by_therapy.setdefault(therapy_key, {})
            supportive_release_status_by_therapy[therapy_key] = {
                **dict(supportive_release_status_by_therapy.get(therapy_key) or {}),
                "release_status": merged_release_status,
                "supportive_readiness_status": entry.get("supportive_readiness_status"),
                "required_support_actions": list(entry.get("required_support_actions") or []),
                "hard_support_blockers": list(entry.get("hard_support_blockers") or []),
                "why_support_changes_choice": list(entry.get("why_support_changes_choice") or []),
            }

    selected_supportive_entry = next(
        (item for item in supportive_enriched_entries if item.get("decision_role") == "selected"),
        supportive_enriched_entries[0] if supportive_enriched_entries else {},
    )

    return {
        "available": True,
        "scenario_state": state,
        "phenotype_state": phenotype_state,
        "candidate_family": candidate_family,
        "candidate_family_label": _first_nonempty(candidate.get("family_label"), family_label(candidate_family)),
        "candidate_regimen_code": candidate_regimen_code,
        "candidate_regimen_label": _first_nonempty(candidate.get("regimen_label"), regimen_label(candidate_regimen_code)),
        "candidate_source": str(candidate.get("source") or ""),
        "current_scope": str(systemic_regimen_scope_contract.get("scope") or ""),
        "readiness_status": readiness_status,
        "readiness_summary": readiness_summary.get(readiness_status, ""),
        "release_blockers": release_blockers,
        "safety_blockers": safety_blockers,
        "safety_watchouts": safety_watchouts,
        "competing_intent": competing_intent,
        "required_to_release": required_to_release,
        "display_required_to_release": display_required_to_release,
        "display_release_blockers": _dedupe(release_blockers + display_required_to_release),
        "display_safety_blockers": _dedupe(safety_blockers + safety_watchouts),
        "monitoring_gate_status": monitoring_gate_status,
        "adjudication_gate_status": adjudication_gate_status,
        "release_confidence_status": release_confidence_status,
        "confidence_decay_reasons": confidence_decay_reasons,
        "next_best_action_if_not_ready": next_best_action_if_not_ready,
        "traceable_evidence_requirements": traceable_evidence_requirements,
        "selected_therapy_evidence_status": str(
            currentness_bundle.get("selected_therapy_evidence_status") or "unknown"
        ),
        "selected_therapy_release_status": str(
            selected_supportive_entry.get("release_status")
            or currentness_bundle.get("selected_therapy_release_status")
            or readiness_status
        ),
        "evidence_currentness_by_therapy": dict(currentness_bundle.get("evidence_currentness_by_therapy") or {}),
        "evidence_currentness_by_family": dict(currentness_bundle.get("evidence_currentness_by_family") or {}),
        "refresh_actions": list(currentness_bundle.get("refresh_actions") or []),
        "evidence_dates_used": list(currentness_bundle.get("evidence_dates_used") or []),
        "traceability_gaps": list(currentness_bundle.get("traceability_gaps") or []),
        "stale_evidence_fields": list(currentness_bundle.get("stale_evidence_fields") or []),
        "aging_evidence_fields": list(currentness_bundle.get("aging_evidence_fields") or []),
        "release_blocked_by_stale_evidence": bool(
            currentness_bundle.get("release_blocked_by_stale_evidence")
        ),
        "therapy_rationale_entries": supportive_enriched_entries,
        "release_status_by_therapy": supportive_release_status_by_therapy,
        "hard_blockers_by_therapy": dict(therapy_breakdown.get("hard_blockers_by_therapy") or {}),
        "traceable_evidence_requirements_by_therapy": dict(
            therapy_breakdown.get("traceable_evidence_requirements_by_therapy") or {}
        ),
        "next_best_action_if_not_ready_by_therapy": dict(
            therapy_breakdown.get("next_best_action_if_not_ready_by_therapy") or {}
        ),
        "capture_actions": capture_actions,
        "display_release_actions": [
            {
                "title": action.get("title"),
                "summary": action.get("summary"),
                "display_fields_summary": list(action.get("display_fields_summary") or []),
            }
            for action in capture_actions
        ],
        "release_blocker_capture_map": release_blocker_capture_map,
        "recommendation_block_status": str(recommendation_block_status or ""),
        "recommendation_block_reason": str(recommendation_block_reason or ""),
        "allowed_actions_while_blocked": list(allowed_actions_while_blocked or []),
        "family_profile_snapshot": family_profile,
        "advanced_release_gate": advanced_release_gate,
        "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
        "supportive_readiness_status": supportive_readiness_status or "ready",
        "supportive_priority": str(
            supportive_care_toxicity_readiness_bundle.get("supportive_priority") or "background"
        ),
        "required_support_actions": list(
            supportive_care_toxicity_readiness_bundle.get("required_support_actions") or []
        ),
        "hard_support_blockers": list(
            supportive_care_toxicity_readiness_bundle.get("hard_support_blockers") or []
        ),
        "recommended_supportive_referrals": list(
            supportive_care_toxicity_readiness_bundle.get("recommended_referrals") or []
        ),
        "supportive_domains_active": list(
            supportive_care_toxicity_readiness_bundle.get("supportive_domains_active") or []
        ),
        "treatment_shaping_companion_inputs": list(
            decision_input_requirements.get("treatment_shaping_companion_inputs") or []
        ),
        "treatment_shaping_companion_actions": companion_capture_actions,
        "sustainability_status_by_therapy": dict(
            supportive_care_toxicity_readiness_bundle.get("sustainability_status_by_therapy") or {}
        ),
        "therapeutic_window_summary": {
            "opportunity_loss_risk_summary": str(therapeutic_window_bundle.get("opportunity_loss_risk_summary") or ""),
            "critical_windows_open_count": int(window_summary.get("critical_windows_open_count") or 0),
            "top_active_window_key": str(top_active_window.get("window_key") or ""),
        },
        "survivorship_context": {
            "track": str(survivorship_transition_bundle.get("survivorship_track") or ""),
            "trigger_status": str(survivorship_transition_bundle.get("trigger_status") or ""),
        },
    }
