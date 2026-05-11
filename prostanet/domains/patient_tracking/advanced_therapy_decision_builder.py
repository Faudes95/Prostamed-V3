from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    family_label,
    regimen_family_code,
)


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


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value in (None, "", {}):
        return []
    return [value]


def _normalize_eligibility_status(raw_status: Any) -> str:
    normalized = str(raw_status or "").strip().lower()
    if normalized in {"preferred", "preferente"}:
        return "preferred"
    if normalized in {"eligible", "eligible_nonpreferred"}:
        return "eligible"
    if normalized in {"eligible_with_caution", "eligible_with_watchouts"}:
        return "eligible_with_caution"
    if normalized in {"conditional", "not_assessable"}:
        return "conditional"
    if normalized in {"hard_blocked", "contraindicated"}:
        return "contraindicated"
    if normalized in {"score_below_threshold", "not_preferred"}:
        return "not_preferred"
    return "not_applicable"


def _family_specific_requirement_keys(state: str, family_code: str, regimen_code: str) -> set[str]:
    family_code = str(family_code or "").strip()
    regimen_code = str(regimen_code or "").strip()
    keys: set[str] = set()
    if state in {"m0_crpc", "adt_progression_verification"} or family_code in {
        "arpi_family",
        "observation_family",
    }:
        keys.update({"castrate_confirmation", "restaging_negative_context"})
    if state.startswith("mcspc_") or state == "mcspc_high_volume":
        keys.add("mhspc_safety_readiness")
    if family_code in {"parp_family"} or regimen_code in {
        "OLAPARIB",
        "RUCAPARIB",
        "TALAZOPARIB_ENZALUTAMIDE",
        "NIRAPARIB_ABIRATERONE",
    }:
        keys.add("molecular_traceability")
    if family_code in {"psma_rlt_family"} or regimen_code in {"LU177_PSMA617"}:
        keys.add("psma_traceability")
    if family_code in {"salvage_rt_family", "local_mdt_family"}:
        keys.update({"psa_dynamics", "local_salvage_feasibility"})
    return keys


def _prerequisite_actions_for_fields(
    *,
    fields: list[str],
    fallback_title: str,
    fallback_rationale: str,
) -> list[dict[str, Any]]:
    fields = _dedupe(list(fields or []))
    if not fields:
        return []
    display_fields = fields[:4]
    return [
        {
            "title": fallback_title,
            "rationale": fallback_rationale,
            "required_fields": fields,
            "display_required_fields": display_fields,
        }
    ]


def _normalize_matrix_entry(
    *,
    state: str,
    item: dict[str, Any],
    family_profile: dict[str, Any],
    candidate_regimen_code: str,
    candidate_family: str,
    readiness_status: str,
    next_best_action_if_not_ready: dict[str, Any],
    traceable_evidence_requirements: list[dict[str, Any]],
    sequence_transition_bundle: dict[str, Any],
    domain_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    regimen_code = str(item.get("regimen_code") or "").strip()
    family_code = str(
        item.get("family_code") or family_profile.get("family_code") or regimen_family_code(regimen_code)
    ).strip()
    therapy_key = _first_nonempty(regimen_code, family_code, item.get("name"))
    therapy_label = _first_nonempty(
        item.get("name"),
        item.get("regimen_label"),
        item.get("display_label"),
        regimen_label(regimen_code),
        family_profile.get("family_label"),
        family_label(family_code),
    )
    normalized_status = _normalize_eligibility_status(
        item.get("eligibility_status") or family_profile.get("eligibility_status")
    )
    missing_release_inputs = _dedupe(
        list(item.get("required_missing_fields") or [])
        + list(item.get("missing_inputs") or [])
        + list(family_profile.get("missing_inputs") or [])
    )
    stale_inputs = _dedupe(
        list(item.get("stale_inputs") or [])
        + list(family_profile.get("stale_inputs") or [])
    )
    contraindication_reasons = _dedupe(
        list(item.get("hard_blocks") or [])
        + list(item.get("contraindication_reasons") or [])
    )
    why_selected = _dedupe(
        list(item.get("why_this_rank") or [])
        + [_first_nonempty(family_profile.get("winner_reason"))]
    )
    why_not_selected = _dedupe(
        contraindication_reasons
        + list(item.get("caution_flags") or [])
        + list(item.get("data_quality_caveats") or [])
        + [_first_nonempty(family_profile.get("why_not_preferred"))]
    )
    evidence_basis = _dedupe(
        [
            _first_nonempty(item.get("benefit_basis")),
            _first_nonempty(item.get("benefit_endpoint_used")),
            _first_nonempty(item.get("benefit_maturity")),
        ]
    )
    selected = bool(
        regimen_code
        and candidate_regimen_code
        and regimen_code == candidate_regimen_code
    ) or (
        not candidate_regimen_code
        and family_code
        and family_code == candidate_family
        and normalized_status == "preferred"
    )
    if selected:
        decision_role = "selected"
        release_status = readiness_status or "ready_to_release"
    elif normalized_status in {"contraindicated", "not_preferred", "not_applicable"}:
        decision_role = "blocked"
        release_status = "blocked_by_safety" if normalized_status == "contraindicated" else "not_preferred"
    elif normalized_status == "conditional" or missing_release_inputs or stale_inputs:
        decision_role = "deferred"
        release_status = "conditional_pending_closure"
    else:
        decision_role = "runner_up"
        release_status = "ready_to_release"

    therapy_override = dict(domain_overrides.get(regimen_code) or {})
    why_selected = _dedupe(why_selected + list(therapy_override.get("why_selected") or []))
    why_not_selected = _dedupe(why_not_selected + list(therapy_override.get("why_not_selected") or []))
    contraindication_reasons = _dedupe(
        contraindication_reasons + list(therapy_override.get("contraindication_reasons") or [])
    )
    missing_release_inputs = _dedupe(
        missing_release_inputs + list(therapy_override.get("missing_release_inputs") or [])
    )
    stale_inputs = _dedupe(stale_inputs + list(therapy_override.get("stale_inputs") or []))
    evidence_basis = _dedupe(evidence_basis + list(therapy_override.get("evidence_basis") or []))

    traceable_keys = _family_specific_requirement_keys(state, family_code, regimen_code)
    traceable_by_therapy = [
        requirement
        for requirement in list(traceable_evidence_requirements or [])
        if str(requirement.get("key") or "").strip() in traceable_keys
    ]
    if not traceable_by_therapy and selected:
        traceable_by_therapy = list(traceable_evidence_requirements or [])

    prerequisite_actions = []
    if selected and next_best_action_if_not_ready and release_status != "ready_to_release":
        prerequisite_actions = [
            {
                "title": _first_nonempty(next_best_action_if_not_ready.get("title"), "Cerrar prerequisitos terapéuticos"),
                "rationale": _first_nonempty(
                    next_best_action_if_not_ready.get("rationale"),
                    "La terapia sigue condicionada a cerrar brechas visibles.",
                ),
                "required_fields": list(next_best_action_if_not_ready.get("required_fields") or missing_release_inputs),
                "display_required_fields": list(
                    next_best_action_if_not_ready.get("display_required_fields") or missing_release_inputs[:4]
                ),
            }
        ]
    elif (missing_release_inputs or stale_inputs) and release_status != "ready_to_release":
        prerequisite_actions = _prerequisite_actions_for_fields(
            fields=missing_release_inputs or stale_inputs,
            fallback_title="Completar prerequisitos para liberar terapia",
            fallback_rationale="La terapia sigue condicionada a datos faltantes o desactualizados.",
        )

    sequence_context = _dedupe(
        list(therapy_override.get("sequence_context") or [])
        + [
            _first_nonempty(sequence_transition_bundle.get("line_change_reason")) if selected else "",
        ]
    )

    return {
        "therapy_key": therapy_key,
        "therapy_label": therapy_label,
        "family_code": family_code,
        "family_label": _first_nonempty(family_profile.get("family_label"), family_label(family_code)),
        "eligibility_status": normalized_status,
        "release_status": release_status,
        "decision_role": decision_role,
        "why_selected": why_selected[:3],
        "why_not_selected": why_not_selected[:3],
        "contraindication_reasons": contraindication_reasons[:3],
        "missing_release_inputs": missing_release_inputs,
        "stale_inputs": stale_inputs,
        "prerequisite_actions": prerequisite_actions,
        "evidence_basis": evidence_basis[:3],
        "traceable_evidence_requirements": traceable_by_therapy,
        "sequence_context": sequence_context[:3],
        "visibility_priority": 100 if selected else 75 if decision_role == "runner_up" else 55 if decision_role == "deferred" else 40,
        "source": "comparative_eligibility_matrix",
        "regimen_code": regimen_code,
    }


def _local_adjunct_entry(adjunct: dict[str, Any]) -> dict[str, Any]:
    label = _first_nonempty(adjunct.get("label"))
    rationale = _first_nonempty(adjunct.get("rationale"))
    normalized = label.lower()
    if "rt al primario" in normalized or "radioterapia al primario" in normalized:
        family_code = "local_primary_rt"
    elif "mdt" in normalized or "metastasis-directed" in normalized:
        family_code = "mdt_candidate"
    elif "salvage" in normalized or "rescate" in normalized:
        family_code = "salvage_rt_family"
    else:
        family_code = "local_adjunct"
    return {
        "therapy_key": label,
        "therapy_label": label,
        "family_code": family_code,
        "family_label": family_label(family_code) or "Adjunto local",
        "eligibility_status": "eligible" if str(adjunct.get("priority") or "").strip() == "required" else "eligible_with_caution",
        "release_status": "ready_to_release",
        "evidence_status": "current",
        "release_blocked_by_stale_evidence": False,
        "refresh_action_needed": "",
        "evidence_dates_used": [],
        "traceability_gaps": [],
        "stale_evidence_fields": [],
        "aging_evidence_fields": [],
        "decision_role": "supportive_only",
        "why_selected": [rationale] if rationale else [],
        "why_not_selected": [],
        "contraindication_reasons": [],
        "missing_release_inputs": [],
        "stale_inputs": [],
        "prerequisite_actions": [],
        "evidence_basis": [],
        "traceable_evidence_requirements": [],
        "sequence_context": [],
        "visibility_priority": 65 if str(adjunct.get("priority") or "").strip() == "required" else 50,
        "source": _first_nonempty(adjunct.get("source"), "local_adjuncts_visible"),
        "regimen_code": "",
    }


def _build_domain_overrides(active_copilot_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    bundle = dict(active_copilot_bundle or {})
    overrides: dict[str, dict[str, Any]] = {}

    frontline_trace = dict(bundle.get("frontline_ranking_trace") or {})
    winner_reason = _first_nonempty(frontline_trace.get("winner_reason"))
    preferred = dict(
        bundle.get("overall_preferred_frontline_regimen")
        or bundle.get("preferred_frontline_regimen")
        or {}
    )
    preferred_code = str(preferred.get("regimen_code") or "").strip()
    if preferred_code and winner_reason:
        overrides.setdefault(preferred_code, {}).setdefault("why_selected", []).append(winner_reason)

    docetaxel_fitness = dict(bundle.get("docetaxel_fitness") or {})
    docetaxel_reason = _first_nonempty(
        docetaxel_fitness.get("docetaxel_fit_summary"),
        docetaxel_fitness.get("summary"),
    )
    if docetaxel_reason:
        for regimen_code in ("ADT_DOCETAXEL", "ADT_DOCETAXEL_DAROLUTAMIDE", "ADT_DOCETAXEL_ABIRATERONE", "DOCETAXEL", "CABAZITAXEL"):
            target = overrides.setdefault(regimen_code, {})
            if docetaxel_fitness.get("eligible") is False:
                target.setdefault("contraindication_reasons", []).append(docetaxel_reason)
                target.setdefault("why_not_selected", []).append(docetaxel_reason)
            else:
                target.setdefault("why_selected", []).append(docetaxel_reason)

    sequence_transition_bundle = dict(bundle.get("sequence_transition_bundle") or {})
    line_change_reason = _first_nonempty(sequence_transition_bundle.get("line_change_reason"))
    preferred_regimen = dict(bundle.get("preferred_frontline_regimen") or {})
    preferred_code = _first_nonempty(preferred_regimen.get("regimen_code"), preferred_code)
    if preferred_code and line_change_reason:
        overrides.setdefault(preferred_code, {}).setdefault("sequence_context", []).append(line_change_reason)

    for candidate in list(bundle.get("sequence_candidates") or []):
        regimen_code = _first_nonempty(candidate.get("regimen_code"))
        if not regimen_code:
            continue
        target = overrides.setdefault(regimen_code, {})
        blocked_reasons = list(candidate.get("blocked_by") or [])
        if blocked_reasons:
            target.setdefault("contraindication_reasons", []).extend(blocked_reasons)
            target.setdefault("why_not_selected", []).extend(blocked_reasons)
        if candidate.get("biomarker_driven"):
            target.setdefault("evidence_basis", []).append("Biomarcador accionable requerido o priorizado para esta secuencia.")

    return {
        key: {
            subkey: _dedupe(list(value) if isinstance(value, list) else [value])
            for subkey, value in dict(item or {}).items()
        }
        for key, item in overrides.items()
    }


def build_therapy_readiness_breakdown(
    *,
    state: str,
    candidate_family: str,
    candidate_regimen_code: str,
    readiness_status: str,
    comparative_eligibility_matrix: dict[str, Any] | None = None,
    next_best_action_if_not_ready: dict[str, Any] | None = None,
    traceable_evidence_requirements: list[dict[str, Any]] | None = None,
    active_copilot_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparative_eligibility_matrix = dict(comparative_eligibility_matrix or {})
    next_best_action_if_not_ready = dict(next_best_action_if_not_ready or {})
    traceable_evidence_requirements = list(traceable_evidence_requirements or [])
    active_copilot_bundle = dict(active_copilot_bundle or {})
    domain_overrides = _build_domain_overrides(active_copilot_bundle)
    sequence_transition_bundle = dict(active_copilot_bundle.get("sequence_transition_bundle") or {})

    family_profiles = sorted(
        [
            dict(profile)
            for profile in comparative_eligibility_matrix.values()
            if isinstance(profile, dict)
        ],
        key=lambda item: float(item.get("comparative_priority_score") or 0),
        reverse=True,
    )

    entries: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for family_profile in family_profiles:
        ranked = list((family_profile.get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
        rejected = list((family_profile.get("variant_ranking") or {}).get("nonpreferred_or_ineligible_regimens") or [])
        for item in ranked + rejected:
            if not isinstance(item, dict):
                continue
            entry = _normalize_matrix_entry(
                state=state,
                item=item,
                family_profile=family_profile,
                candidate_regimen_code=candidate_regimen_code,
                candidate_family=candidate_family,
                readiness_status=readiness_status,
                next_best_action_if_not_ready=next_best_action_if_not_ready,
                traceable_evidence_requirements=traceable_evidence_requirements,
                sequence_transition_bundle=sequence_transition_bundle,
                domain_overrides=domain_overrides,
            )
            therapy_key = str(entry.get("therapy_key") or "").strip()
            if not therapy_key or therapy_key in seen_keys:
                continue
            seen_keys.add(therapy_key)
            entries.append(entry)

    if not entries and (candidate_regimen_code or candidate_family):
        entries.append(
            {
                "therapy_key": _first_nonempty(candidate_regimen_code, candidate_family),
                "therapy_label": _first_nonempty(regimen_label(candidate_regimen_code), family_label(candidate_family)),
                "family_code": candidate_family,
                "family_label": family_label(candidate_family),
                "eligibility_status": "preferred",
                "release_status": readiness_status or "ready_to_release",
                "decision_role": "selected",
                "why_selected": [],
                "why_not_selected": [],
                "contraindication_reasons": [],
                "missing_release_inputs": list(next_best_action_if_not_ready.get("required_fields") or []),
                "stale_inputs": [],
                "prerequisite_actions": [],
                "evidence_basis": [],
                "traceable_evidence_requirements": list(traceable_evidence_requirements or []),
                "sequence_context": list(
                    filter(None, [_first_nonempty(sequence_transition_bundle.get("line_change_reason"))])
                ),
                "visibility_priority": 100,
                "source": "fallback_candidate",
                "regimen_code": candidate_regimen_code,
            }
        )

    entries.sort(
        key=lambda item: (
            0 if item.get("decision_role") == "selected" else 1 if item.get("decision_role") == "runner_up" else 2,
            -int(item.get("visibility_priority") or 0),
            str(item.get("therapy_label") or ""),
        )
    )

    release_status_by_therapy = {
        str(item["therapy_key"]): {
            "therapy_label": item["therapy_label"],
            "family_code": item["family_code"],
            "release_status": item["release_status"],
            "eligibility_status": item["eligibility_status"],
            "decision_role": item["decision_role"],
        }
        for item in entries
    }
    hard_blockers_by_therapy = {
        str(item["therapy_key"]): list(item.get("contraindication_reasons") or [])
        for item in entries
        if item.get("contraindication_reasons")
    }
    traceable_evidence_requirements_by_therapy = {
        str(item["therapy_key"]): list(item.get("traceable_evidence_requirements") or [])
        for item in entries
        if item.get("traceable_evidence_requirements")
    }
    next_best_action_if_not_ready_by_therapy = {
        str(item["therapy_key"]): list(item.get("prerequisite_actions") or [])
        for item in entries
        if item.get("prerequisite_actions")
    }
    return {
        "therapy_rationale_entries": entries,
        "release_status_by_therapy": release_status_by_therapy,
        "hard_blockers_by_therapy": hard_blockers_by_therapy,
        "traceable_evidence_requirements_by_therapy": traceable_evidence_requirements_by_therapy,
        "next_best_action_if_not_ready_by_therapy": next_best_action_if_not_ready_by_therapy,
    }


def build_advanced_therapy_decision_panel(
    *,
    state: str,
    therapeutic_readiness_bundle: dict[str, Any] | None = None,
    active_copilot_bundle: dict[str, Any] | None = None,
    local_adjuncts_visible: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    therapeutic_readiness_bundle = dict(therapeutic_readiness_bundle or {})
    active_copilot_bundle = dict(active_copilot_bundle or {})
    local_adjuncts_visible = list(local_adjuncts_visible or [])

    entries = [
        dict(item)
        for item in list(therapeutic_readiness_bundle.get("therapy_rationale_entries") or [])
        if isinstance(item, dict)
    ]
    if not entries:
        breakdown = build_therapy_readiness_breakdown(
            state=state,
            candidate_family=str(therapeutic_readiness_bundle.get("candidate_family") or ""),
            candidate_regimen_code=str(therapeutic_readiness_bundle.get("candidate_regimen_code") or ""),
            readiness_status=str(therapeutic_readiness_bundle.get("readiness_status") or ""),
            comparative_eligibility_matrix=dict(active_copilot_bundle.get("comparative_eligibility_matrix") or {}),
            next_best_action_if_not_ready=dict(
                therapeutic_readiness_bundle.get("next_best_action_if_not_ready") or {}
            ),
            traceable_evidence_requirements=list(
                therapeutic_readiness_bundle.get("traceable_evidence_requirements") or []
            ),
            active_copilot_bundle=active_copilot_bundle,
        )
        entries = list(breakdown.get("therapy_rationale_entries") or [])

    for adjunct in local_adjuncts_visible:
        entries.append(_local_adjunct_entry(dict(adjunct or {})))

    deduped_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        key = _first_nonempty(entry.get("therapy_key"), entry.get("therapy_label"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_entries.append(entry)

    selected = next((item for item in deduped_entries if item.get("decision_role") == "selected"), {})
    if not selected and deduped_entries:
        selected = dict(deduped_entries[0])
    other_viable = [
        item
        for item in deduped_entries
        if item.get("therapy_key") != selected.get("therapy_key")
        and item.get("decision_role") in {"runner_up", "supportive_only"}
    ][:5]
    blocked_or_deferred = [
        item
        for item in deduped_entries
        if item.get("therapy_key") != selected.get("therapy_key")
        and item.get("decision_role") in {"blocked", "deferred"}
    ][:6]

    return {
        "available": bool(selected or other_viable or blocked_or_deferred),
        "state": state,
        "selected_therapy": selected,
        "selected_therapy_evidence_status": _first_nonempty(
            therapeutic_readiness_bundle.get("selected_therapy_evidence_status"),
            selected.get("evidence_status"),
        ),
        "selected_therapy_release_status": _first_nonempty(
            therapeutic_readiness_bundle.get("selected_therapy_release_status"),
            selected.get("release_status"),
        ),
        "refresh_actions": list(therapeutic_readiness_bundle.get("refresh_actions") or []),
        "supportive_readiness_status": str(
            therapeutic_readiness_bundle.get("supportive_readiness_status") or "ready"
        ),
        "supportive_priority": str(
            therapeutic_readiness_bundle.get("supportive_priority") or "background"
        ),
        "required_support_actions": list(
            therapeutic_readiness_bundle.get("required_support_actions") or []
        ),
        "hard_support_blockers": list(
            therapeutic_readiness_bundle.get("hard_support_blockers") or []
        ),
        "recommended_supportive_referrals": list(
            therapeutic_readiness_bundle.get("recommended_supportive_referrals") or []
        ),
        "other_viable_options": other_viable,
        "blocked_or_deferred_options": blocked_or_deferred,
        "therapy_rationale_entries": deduped_entries,
        "local_adjuncts": [_local_adjunct_entry(dict(item or {})) for item in local_adjuncts_visible],
    }


__all__ = [
    "build_advanced_therapy_decision_panel",
    "build_therapy_readiness_breakdown",
]
