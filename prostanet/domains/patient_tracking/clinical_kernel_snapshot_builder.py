from __future__ import annotations

from typing import Any


def _build_state_reclassification_bundle(
    contradiction_resolution_bundle: dict[str, Any] | None,
    *,
    current_state: str = "",
) -> dict[str, Any]:
    contradiction_resolution_bundle = dict(contradiction_resolution_bundle or {})
    required = bool(contradiction_resolution_bundle.get("state_reclassification_required"))
    contradictions = list(contradiction_resolution_bundle.get("contradictions") or [{}])
    return {
        "available": required,
        "required": required,
        "reason": contradictions[0].get("rationale", "") if required else "",
        "target_states": list(contradiction_resolution_bundle.get("state_reclassification_targets") or []),
        "current_state": contradiction_resolution_bundle.get("current_state") or current_state or "",
    }


def build_patient_kernel_snapshot(
    patient_record: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.clinical_contradiction_engine import (
        build_clinical_contradiction_bundle,
    )
    from prostanet.domains.patient_tracking.longitudinal_truth_service import (
        build_longitudinal_truth_snapshot,
    )
    from prostanet.domains.patient_tracking.psma_imaging import (
        build_psma_decision_impact,
        build_psma_structured_profile,
    )
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
    from prostanet.shared.clinical_fact_resolver import (
        build_fact_conflict_summary,
        resolve_patient_clinical_facts,
    )

    patient_record = dict(patient_record or {})
    latest_assessment = dict(latest_assessment or patient_record.get("latest_assessment") or {})
    prior_history = dict(patient_record.get("prior_history") or {})
    latest_signal_snapshot = dict(patient_record.get("latest_signal_snapshot") or {})

    longitudinal_truth_snapshot = build_longitudinal_truth_snapshot(
        patient_record,
        latest_assessment=latest_assessment,
    )
    resolved_facts = clinical_fact_bundle or resolve_patient_clinical_facts(patient_record)
    fact_conflict_summary = build_fact_conflict_summary(
        patient_record.get("patient_fact_conflicts") or []
    )
    psma_structured_profile = build_psma_structured_profile(patient_record)
    psma_decision_impact = build_psma_decision_impact(
        psma_structured_profile,
        state=str(prior_history.get("current_state") or ""),
        management_track=str(prior_history.get("management_track") or ""),
        patient=patient_record,
    )
    reconciliation = build_reconciled_state(patient_record, latest_assessment)
    contradiction_resolution_bundle = build_clinical_contradiction_bundle(
        patient_record,
        latest_assessment=latest_assessment,
        clinical_fact_bundle=resolved_facts,
    )
    effective_state = str(
        reconciliation.get("reconciled_state")
        or latest_signal_snapshot.get("effective_state_final")
        or latest_signal_snapshot.get("effective_state")
        or latest_assessment.get("state")
        or prior_history.get("current_state")
        or ""
    )
    therapeutic_readiness_bundle = dict(
        patient_record.get("therapeutic_readiness_bundle")
        or latest_signal_snapshot.get("therapeutic_readiness_bundle")
        or {}
    )
    effective_recommendation_family = str(
        therapeutic_readiness_bundle.get("candidate_family")
        or (latest_signal_snapshot.get("next_best_action") or {}).get("recommendation_family")
        or ""
    )
    surface_flags = []
    if contradiction_resolution_bundle.get("critical_unresolved_count"):
        surface_flags.append("Persisten contradicciones clínicas críticas sin cierre.")
    if latest_signal_snapshot.get("state_conflict_flag"):
        surface_flags.append(
            str(latest_signal_snapshot.get("state_conflict_reason") or "Existe conflicto entre estado efectivo y superficies visibles.")
        )
    for item in list(latest_signal_snapshot.get("ui_contradiction_flags") or []):
        if isinstance(item, dict):
            text = str(item.get("message") or item.get("reason") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            surface_flags.append(text)
    surface_consistency_flags = list(dict.fromkeys(surface_flags))
    surface_consistency_status = "requires_review" if surface_consistency_flags else "consistent"
    clinical_kernel_snapshot = {
        "effective_state": effective_state,
        "effective_recommendation_family": effective_recommendation_family,
        "surface_consistency_status": surface_consistency_status,
        "surface_consistency_flags": surface_consistency_flags,
        "reconciled_state": reconciliation.get("reconciled_state") or "",
        "reconciled_management_track": reconciliation.get("reconciled_management_track") or "",
    }

    return {
        "longitudinal_truth_snapshot": longitudinal_truth_snapshot,
        "superseded_inputs": list(longitudinal_truth_snapshot.get("superseded_inputs") or []),
        "latest_clinically_decisive_visit": dict(
            longitudinal_truth_snapshot.get("latest_clinically_decisive_visit") or {}
        ),
        "clinical_fact_bundle": resolved_facts,
        "fact_freshness_summary": dict(resolved_facts.get("freshness_summary") or {}),
        "fact_conflict_summary": fact_conflict_summary,
        "psma_structured_profile": psma_structured_profile,
        "psma_decision_impact": psma_decision_impact,
        "reconciliation": reconciliation,
        "contradiction_resolution_bundle": contradiction_resolution_bundle,
        "state_reclassification_bundle": _build_state_reclassification_bundle(
            contradiction_resolution_bundle,
            current_state=str(reconciliation.get("explicit_state") or ""),
        ),
        "clinical_kernel_snapshot": clinical_kernel_snapshot,
        "effective_state": effective_state,
        "effective_recommendation_family": effective_recommendation_family,
        "surface_consistency_status": surface_consistency_status,
        "surface_consistency_flags": surface_consistency_flags,
    }


def build_runtime_kernel_shadow_context(
    patient_record: dict[str, Any],
    *,
    latest_assessment: dict[str, Any] | None = None,
    derived_fact_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    shadow_patient = dict(patient_record or {})
    shadow_patient["patient_clinical_facts"] = list(
        shadow_patient.get("patient_clinical_facts") or []
    ) + list(derived_fact_candidates or [])
    kernel_snapshot = build_patient_kernel_snapshot(
        shadow_patient,
        latest_assessment=latest_assessment,
    )
    return {
        **kernel_snapshot,
        "shadow_patient": shadow_patient,
    }
