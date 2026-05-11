from __future__ import annotations

from typing import Any

from prostanet.shared.ui_value_normalizer import normalize_field_list


STRUCTURED_VISIBLE_FIELD_EXPANSIONS: dict[str, list[str]] = {
    "psa": ["psa", "psa_history"],
    "psa_history": ["psa", "psa_history"],
    "testosterone": ["testosterone", "testosterone_history"],
    "testosterone_history": ["testosterone", "testosterone_history"],
    "castrate_testosterone_status": ["castrate_testosterone_status", "testosterone", "testosterone_history"],
    "line_of_therapy_number": ["line_of_therapy_number", "line_of_therapy_context", "drug_scheme"],
    "line_of_therapy_context": ["line_of_therapy_number", "line_of_therapy_context", "drug_scheme"],
    "drug_scheme": ["line_of_therapy_number", "line_of_therapy_context", "drug_scheme"],
    "eq5d_vas": ["eq5d_vas_band", "eq5d_vas"],
    "eq5d_vas_band": ["eq5d_vas_band", "eq5d_vas"],
    "fact_p_total": ["fact_p_total_band", "fact_p_total"],
    "fact_p_total_band": ["fact_p_total_band", "fact_p_total"],
    "bpi_worst_pain": ["bpi_worst_pain_band", "bpi_worst_pain"],
    "bpi_worst_pain_band": ["bpi_worst_pain_band", "bpi_worst_pain"],
    "fatigue_score": ["fatigue_score_band", "fatigue_score"],
    "fatigue_score_band": ["fatigue_score_band", "fatigue_score"],
    "confirmatory_biopsy_done": ["confirmatory_biopsy_done", "mri_interval_months"],
    "mri_interval_months": ["confirmatory_biopsy_done", "mri_interval_months"],
}

FRAILTY_VISIBLE_FIELDS = [
    "weight_kg",
    "height_cm",
    "bmi_current",
    "weight_loss_6m_kg",
    "mini_cog_score",
    "weak_grip",
]

FRAILTY_EXPANSION_TRIGGERS = {
    "slow_gait",
    "weight_loss_6m_pct",
    "g8_weight_loss",
    "g8_self_health",
    "g8_food_intake",
    "weak_grip",
    "g8_medications",
    "low_activity",
    "g8_neuropsych",
    "g8_mobility",
    "weight_loss_6m_kg",
    "g8_bmi",
}

VISIBLE_REQUIRED_FIELD_ALIASES = {
    "weight_loss_6m_pct": "weight_loss_6m_kg",
    "baseline_qol": "eq5d_vas_band",
    "neurocognitive_baseline": "mini_cog_score",
    "drug_interaction_reviewed": "ddi_review_status",
}


def _clean_field_names(field_names: list[Any] | tuple[Any, ...] | None) -> list[str]:
    names: list[str] = []
    for name in field_names or []:
        text = str(name or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def expand_visible_capture_surface(field_names: list[Any] | tuple[Any, ...] | None) -> list[str]:
    requested = _clean_field_names(field_names)
    expanded: list[str] = []
    include_frailty_bundle = any(field in FRAILTY_EXPANSION_TRIGGERS for field in requested)
    for field in requested:
        for expanded_field in STRUCTURED_VISIBLE_FIELD_EXPANSIONS.get(field, [field]):
            if expanded_field not in expanded:
                expanded.append(expanded_field)
    if include_frailty_bundle:
        for field in FRAILTY_VISIBLE_FIELDS:
            if field not in expanded:
                expanded.append(field)
    return expanded


def visible_required_inputs(
    required_inputs: list[Any] | tuple[Any, ...] | None,
    visible_fields: list[Any] | tuple[Any, ...] | None = None,
) -> list[str]:
    visible_required: list[str] = []
    visible_set = set(_clean_field_names(visible_fields))
    for field in _clean_field_names(required_inputs):
        normalized = VISIBLE_REQUIRED_FIELD_ALIASES.get(field, field)
        if visible_set and normalized not in visible_set:
            continue
        if normalized not in visible_required:
            visible_required.append(normalized)
    return visible_required


def build_capture_surface_metadata(
    raw_fields: list[Any] | tuple[Any, ...] | None,
    *,
    required_inputs: list[Any] | tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    visible_fields = expand_visible_capture_surface(raw_fields)
    visible_required = visible_required_inputs(required_inputs or raw_fields, visible_fields)
    return {
        "visible_fields": visible_fields,
        "visible_required_inputs": visible_required,
        "display_fields_summary": display_capture_field_summary(visible_fields, limit=limit),
        "display_required_inputs": display_capture_field_summary(visible_required, limit=limit),
    }


def display_capture_field_summary(
    raw_fields: list[Any] | tuple[Any, ...] | None,
    *,
    required_inputs: list[Any] | tuple[Any, ...] | None = None,
    limit: int | None = None,
) -> list[str]:
    fields = expand_visible_capture_surface(raw_fields)
    if required_inputs:
        fields = visible_required_inputs(required_inputs, fields)
    return normalize_field_list(fields, limit=limit)


def enrich_capture_block(
    block: dict[str, Any] | None,
    *,
    fields_key: str = "fields",
    required_key: str = "required_inputs",
    limit: int | None = None,
) -> dict[str, Any]:
    payload = dict(block or {})
    raw_fields = payload.get(fields_key) or payload.get("capture_fields") or []
    required_inputs = payload.get(required_key) or payload.get("required_inputs") or raw_fields
    payload.update(
        build_capture_surface_metadata(
            raw_fields,
            required_inputs=required_inputs,
            limit=limit,
        )
    )
    return payload


__all__ = [
    "STRUCTURED_VISIBLE_FIELD_EXPANSIONS",
    "FRAILTY_VISIBLE_FIELDS",
    "FRAILTY_EXPANSION_TRIGGERS",
    "VISIBLE_REQUIRED_FIELD_ALIASES",
    "expand_visible_capture_surface",
    "visible_required_inputs",
    "build_capture_surface_metadata",
    "display_capture_field_summary",
    "enrich_capture_block",
]
