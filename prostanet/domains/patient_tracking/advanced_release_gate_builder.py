from __future__ import annotations

from typing import Any


MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

ADVANCED_GATE_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES

_MONITORING_SUPPORT_FIELDS = {
    "dxa_baseline_done",
    "calcium_vitd_started",
    "bone_protection_started",
    "hba1c",
    "total_cholesterol",
    "creatinine",
    "hemoglobin",
    "mini_cog_score",
    "g8_score",
}
_MHSPC_FITNESS_FIELDS = {
    "mini_cog_score",
    "g8_score",
    "ddi_review_status",
    "drug_interaction_reviewed",
    "current_medications",
    "cv_risk_documented",
    "comorbidity_cardio",
}
_PARP_TRACEABILITY_FIELDS = {
    "hrr_status",
    "hrr_gene",
    "biomarker_source",
    "molecular_assay_date",
}
_PSMA_TRACEABILITY_FIELDS = {
    "psma_positive",
    "psma_pet_done",
    "psma_negative_dominant_lesions",
    "conventional_imaging_status",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


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


def _extend_unique(target: list[str], values: list[Any]) -> None:
    for value in values:
        text = _normalize_text(value)
        if text and text not in target:
            target.append(text)


def _intersects(items: set[str], fields: set[str]) -> list[str]:
    return [field for field in fields if field in items]


def build_advanced_release_gate(
    *,
    state: str,
    next_best_action: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    advanced_followup_bundle: dict[str, Any] | None = None,
    staging_adjudication_bundle: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
    candidate_family: str = "",
) -> dict[str, Any]:
    state = _normalize_text(state)
    next_best_action = dict(next_best_action or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    advanced_followup_bundle = dict(advanced_followup_bundle or {})
    staging_adjudication_bundle = dict(staging_adjudication_bundle or {})
    signals = dict(signals or {})
    candidate_family = _normalize_text(candidate_family or next_best_action.get("recommendation_family"))

    missing_hard_existing = {
        _normalize_text(field)
        for field in list(decision_input_requirements.get("hard_blocking_inputs") or [])
        if _normalize_text(field)
    }
    missing_decision_existing = {
        _normalize_text(field)
        for field in list(decision_input_requirements.get("decision_blocking_inputs") or [])
        if _normalize_text(field)
    }
    monitoring_missing = {
        _normalize_text(field)
        for field in list(advanced_followup_bundle.get("missing_inputs") or [])
        if _normalize_text(field)
    }
    adjudication_missing = {
        _normalize_text(field)
        for field in list(staging_adjudication_bundle.get("missing_critical_inputs") or [])
        if _normalize_text(field)
    }
    monitoring_confidence = _normalize_text(advanced_followup_bundle.get("confidence_status"))
    concordance_status = _normalize_text(staging_adjudication_bundle.get("concordance_status"))
    adjudication_release_status = _normalize_text(
        staging_adjudication_bundle.get("adjudication_release_status")
    )
    restaging_update_required = bool(
        staging_adjudication_bundle.get("restaging_update_required")
        or signals.get("restaging_update_required")
    )
    psma_only_upstaging = bool(
        staging_adjudication_bundle.get("psma_only_upstaging")
        or signals.get("psma_only_upstaging")
    )
    adjudication_context_fields = _dedupe(
        list(adjudication_missing)
        + list(staging_adjudication_bundle.get("discordant_fields") or [])
        + list(staging_adjudication_bundle.get("superseded_evidence") or [])
    )
    adjudication_blocked = adjudication_release_status == "blocked_pending_adjudication"
    adjudication_review_needed = adjudication_release_status == "review_needed"
    adjudication_discordant = concordance_status == "discordant"
    adjudication_context_changed = concordance_status == "context_changed"
    adjudication_insufficient = concordance_status == "insufficient_concordance"

    hard_blocking_inputs: list[str] = []
    decision_blocking_inputs: list[str] = []
    confidence_decay_inputs: list[str] = []
    release_gate_reasons: list[str] = []
    confidence_decay_reasons: list[str] = []

    def add_hard(fields: list[str], reason: str) -> None:
        _extend_unique(hard_blocking_inputs, fields)
        if fields:
            _extend_unique(release_gate_reasons, [reason])

    def add_decision(fields: list[str], reason: str) -> None:
        _extend_unique(decision_blocking_inputs, fields)
        if fields:
            _extend_unique(release_gate_reasons, [reason])

    def add_confidence(fields: list[str], reason: str) -> None:
        _extend_unique(confidence_decay_inputs, fields)
        if fields:
            _extend_unique(confidence_decay_reasons, [reason])

    testosterone_gap = _intersects(
        monitoring_missing | missing_hard_existing | missing_decision_existing,
        {"testosterone", "testosterone_history"},
    )
    support_gap = _intersects(
        monitoring_missing | missing_decision_existing,
        _MONITORING_SUPPORT_FIELDS,
    )
    mhspc_fit_gap = _intersects(
        monitoring_missing | missing_decision_existing,
        _MHSPC_FITNESS_FIELDS,
    )

    if state == "adt_progression_verification":
        add_hard(
            testosterone_gap,
            "Confirmar castración con testosterona sérica actual o serie longitudinal antes de liberar ARPI o llamar CRPC.",
        )
        if adjudication_blocked or adjudication_discordant or adjudication_insufficient:
            add_hard(
                _dedupe(
                    list(adjudication_context_fields)
                    or ["conventional_imaging_status", "conventional_imaging_date", "psma_pet_done"]
                ),
                "La verificación CRPC sigue discordante o sin adjudicación suficiente; no debe liberarse la ruta avanzada todavía.",
            )
        elif adjudication_review_needed or restaging_update_required or adjudication_context_changed:
            add_decision(
                _dedupe(
                    list(adjudication_context_fields)
                    or ["conventional_imaging_status", "conventional_imaging_date"]
                ),
                "Hace falta cerrar la restadificación vigente antes de sostener una ruta avanzada bajo ADT.",
            )
        add_decision(
            _intersects(
                support_gap,
                {"dxa_baseline_done", "calcium_vitd_started", "bone_protection_started", "hba1c", "total_cholesterol", "creatinine"},
            ),
            "ADT prolongada requiere bundle óseo y cardiometabólico mínimo antes de considerar el caso realmente estabilizado.",
        )

    elif state == "m0_crpc":
        add_hard(
            testosterone_gap,
            "m0 CRPC no debe liberarse sin confirmar castración bioquímica sostenida.",
        )
        m0_adjudication_fields = _dedupe(
            list(adjudication_context_fields)
            + (
                ["conventional_imaging_status", "psma_positive", "psma_negative_dominant_lesions"]
                if psma_only_upstaging or adjudication_discordant
                else []
            )
        )
        if adjudication_blocked or psma_only_upstaging or adjudication_discordant or adjudication_insufficient:
            add_hard(
                m0_adjudication_fields or ["conventional_imaging_status", "psma_positive"],
                "La adjudicación M0/M1 sigue incompleta, discordante o cambió por PSMA; no debe liberarse el carril nmCRPC todavía.",
            )
        elif adjudication_review_needed or restaging_update_required or adjudication_context_changed:
            add_decision(
                m0_adjudication_fields or ["conventional_imaging_date", "psma_pet_done"],
                "El contexto nmCRPC requiere readjudicación anatómica/funcional antes de declararse plenamente liberado.",
            )
        add_decision(
            support_gap,
            "El caso nmCRPC sigue condicionado a cerrar soporte óseo, vigilancia cardiometabólica y fragilidad/cognición.",
        )

    elif state == "m1_crpc":
        add_hard(
            testosterone_gap,
            "m1 CRPC no debe liberar una nueva terapia si falta confirmar castración bioquímica.",
        )
        m1_adjudication_fields = _dedupe(
            list(adjudication_context_fields)
            + (
                ["conventional_imaging_status", "psma_positive", "psma_negative_dominant_lesions"]
                if psma_only_upstaging or adjudication_discordant
                else []
            )
        )
        if adjudication_blocked or adjudication_discordant or adjudication_insufficient:
            add_hard(
                m1_adjudication_fields or ["conventional_imaging_status", "psma_positive"],
                "La adjudicación anatómica/funcional sigue discordante; no debe liberarse la secuencia mCRPC hasta cerrar la reclasificación.",
            )
        elif adjudication_review_needed or restaging_update_required or psma_only_upstaging or adjudication_context_changed:
            add_decision(
                m1_adjudication_fields or ["conventional_imaging_date", "psma_pet_done"],
                "El contexto mCRPC cambió o quedó superseded; la secuencia debe readjudicarse antes de declararse plenamente liberada.",
            )
        if candidate_family == "parp_family":
            add_hard(
                _intersects(adjudication_missing | missing_hard_existing | missing_decision_existing, _PARP_TRACEABILITY_FIELDS),
                "La terapia PARP exige HRR trazable, gen/fuente documentados y fecha del ensayo molecular.",
            )
        if candidate_family == "psma_rlt_family":
            psma_fields = _dedupe(
                _intersects(adjudication_missing | missing_hard_existing | missing_decision_existing, _PSMA_TRACEABILITY_FIELDS)
                + (
                    ["psma_positive", "psma_negative_dominant_lesions"]
                    if psma_only_upstaging or adjudication_discordant
                    else []
                )
            )
            add_hard(
                psma_fields,
                "PSMA-RLT no debe liberarse sin PSMA documentado y sin una concordancia anatómica razonable.",
            )
        if restaging_update_required and not hard_blocking_inputs:
            add_decision(
                _dedupe(list(adjudication_missing) or ["conventional_imaging_date"]),
                "La restadificación está desactualizada; la siguiente línea sistémica no debe quedar como completamente liberada todavía.",
            )
        add_decision(
            support_gap,
            "El soporte longitudinal, la vigilancia óseo-metabólica y la fragilidad/pros deben cerrarse antes de declarar la terapia lista para liberación final.",
        )

    elif state in MHSPC_STATES:
        add_decision(
            mhspc_fit_gap,
            "La intensificación mHSPC debe quedar condicionada hasta cerrar cognición/fragilidad, DDI y riesgo cardiovascular.",
        )
        add_confidence(
            _intersects(support_gap, _MONITORING_SUPPORT_FIELDS),
            "Aunque el PSA parezca controlado, el seguimiento longitudinal avanzado aún está incompleto para sostener la liberación terapéutica con alta confianza.",
        )

    monitoring_gate_status = "not_applicable"
    adjudication_gate_status = "not_applicable"

    if state in ADVANCED_GATE_STATES:
        adjudication_context_field_set = set(adjudication_context_fields)
        if hard_blocking_inputs and any(
            field in {"testosterone", "testosterone_history"} or field in adjudication_context_field_set
            for field in hard_blocking_inputs
        ):
            monitoring_gate_status = "blocked_by_missing_data" if testosterone_gap else "conditional_pending_closure"
        elif decision_blocking_inputs or monitoring_confidence == "degraded_by_missing_data":
            monitoring_gate_status = "conditional_pending_closure"
        else:
            monitoring_gate_status = "supported"

    if state in {"adt_progression_verification", "m0_crpc", "m1_crpc"}:
        adjudication_hard_block = bool(
            set(hard_blocking_inputs).intersection(
                set(adjudication_context_fields) | _PARP_TRACEABILITY_FIELDS | _PSMA_TRACEABILITY_FIELDS
            )
        )
        if adjudication_blocked or adjudication_discordant or adjudication_insufficient or psma_only_upstaging or adjudication_hard_block:
            adjudication_gate_status = "blocked_by_missing_data"
        elif adjudication_review_needed or adjudication_context_changed or adjudication_missing:
            adjudication_gate_status = "conditional_pending_closure"
        elif restaging_update_required:
            adjudication_gate_status = "conditional_pending_closure"
        else:
            adjudication_gate_status = "supported"

    if hard_blocking_inputs:
        release_confidence_status = "blocked"
    elif decision_blocking_inputs or confidence_decay_inputs or monitoring_confidence == "degraded_by_missing_data":
        release_confidence_status = "degraded"
    else:
        release_confidence_status = "supported"

    if monitoring_confidence == "degraded_by_missing_data":
        add_confidence(
            list(monitoring_missing),
            "La confianza clínica del seguimiento avanzado sigue degradada porque faltan biomarcadores, restadificación o bundles de soporte.",
        )
    if (
        concordance_status in {"discordant", "context_changed", "insufficient_concordance"}
        or adjudication_review_needed
        or adjudication_blocked
    ):
        add_confidence(
            list(adjudication_context_fields) or ["conventional_imaging_status"],
            "La adjudicación anatómica/funcional aún no está completamente cerrada para sostener la liberación terapéutica con alta confianza.",
        )

    return {
        "available": state in ADVANCED_GATE_STATES,
        "state": state,
        "candidate_family": candidate_family,
        "monitoring_gate_status": monitoring_gate_status,
        "adjudication_gate_status": adjudication_gate_status,
        "release_confidence_status": release_confidence_status,
        "hard_blocking_inputs": _dedupe(hard_blocking_inputs),
        "decision_blocking_inputs": _dedupe(decision_blocking_inputs),
        "confidence_decay_inputs": _dedupe(confidence_decay_inputs),
        "release_gate_reasons": _dedupe(release_gate_reasons),
        "confidence_decay_reasons": _dedupe(confidence_decay_reasons),
    }


def merge_advanced_release_gate_into_requirements(
    decision_input_requirements: dict[str, Any] | None,
    advanced_release_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(decision_input_requirements or {})
    advanced_release_gate = dict(advanced_release_gate or {})

    hard_inputs = _dedupe(
        list(merged.get("hard_blocking_inputs") or [])
        + list(advanced_release_gate.get("hard_blocking_inputs") or [])
    )
    decision_inputs = _dedupe(
        list(merged.get("decision_blocking_inputs") or [])
        + list(advanced_release_gate.get("decision_blocking_inputs") or [])
    )
    confidence_inputs = _dedupe(
        list(merged.get("confidence_decay_inputs") or [])
        + list(advanced_release_gate.get("confidence_decay_inputs") or [])
    )
    merged["hard_blocking_inputs"] = hard_inputs
    merged["decision_blocking_inputs"] = decision_inputs
    merged["confidence_decay_inputs"] = confidence_inputs
    merged["blocking_inputs"] = _dedupe(
        list(merged.get("blocking_inputs") or [])
        + hard_inputs
        + decision_inputs
    )
    merged["required_to_recalculate"] = _dedupe(
        list(merged.get("required_to_recalculate") or [])
        + hard_inputs
        + decision_inputs
        + confidence_inputs
    )
    merged["why_these_fields_now"] = _dedupe(
        list(merged.get("why_these_fields_now") or [])
        + list(advanced_release_gate.get("release_gate_reasons") or [])
        + list(advanced_release_gate.get("confidence_decay_reasons") or [])
    )
    merged["advanced_release_gate"] = advanced_release_gate
    return merged
