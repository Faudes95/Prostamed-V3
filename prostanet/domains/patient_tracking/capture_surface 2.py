from __future__ import annotations

from typing import Any

from prostanet.shared.ui_value_normalizer import normalize_field_list


STRUCTURED_VISIBLE_FIELD_EXPANSIONS: dict[str, list[str]] = {
    "psa": ["psa", "psa_history"],
    "psa_history": ["psa", "psa_history"],
    "testosterone": ["testosterone", "testosterone_history"],
    "testosterone_history": ["testosterone", "testosterone_history"],
    "castrate_testosterone_status": [
        "castrate_testosterone_status",
        "testosterone",
        "testosterone_history",
    ],
    "line_of_therapy_number": [
        "line_of_therapy_number",
        "line_of_therapy_context",
        "drug_scheme",
    ],
    "line_of_therapy_context": [
        "line_of_therapy_number",
        "line_of_therapy_context",
        "drug_scheme",
    ],
    "drug_scheme": [
        "line_of_therapy_number",
        "line_of_therapy_context",
        "drug_scheme",
    ],
    "eq5d_vas": ["eq5d_vas_band", "eq5d_vas"],
    "eq5d_vas_band": ["eq5d_vas_band", "eq5d_vas"],
    "fact_p_total": ["fact_p_total_band", "fact_p_total"],
    "fact_p_total_band": ["fact_p_total_band", "fact_p_total"],
    "bpi_worst_pain": ["bpi_worst_pain_band", "bpi_worst_pain"],
    "bpi_worst_pain_band": ["bpi_worst_pain_band", "bpi_worst_pain"],
    "fatigue_score": ["fatigue_score_band", "fatigue_score"],
    "fatigue_score_band": ["fatigue_score_band", "fatigue_score"],
    "confirmatory_biopsy_done": [
        "confirmatory_biopsy_done",
        "mri_interval_months",
    ],
    "mri_interval_months": [
        "confirmatory_biopsy_done",
        "mri_interval_months",
    ],
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
    "weight_loss_6m_kg",
    "weight_loss_6m_pct",
    "weak_grip",
    "low_activity",
    "slow_gait",
    "g8_food_intake",
    "g8_weight_loss",
    "g8_mobility",
    "g8_neuropsych",
    "g8_bmi",
    "g8_medications",
    "g8_self_health",
}

VISIBLE_REQUIRED_FIELD_ALIASES = {
    "weight_loss_6m_pct": "weight_loss_6m_kg",
    "baseline_qol": "eq5d_vas_band",
    "neurocognitive_baseline": "mini_cog_score",
    "drug_interaction_reviewed": "ddi_review_status",
}


def _clean_field_names(field_names: list[Any] | tuple[Any, ...] | None) -> list[str]:
    return [
        str(name)
        for name in list(field_names or [])
        if name and not str(name).startswith("source_document:")
    ]


def expand_visible_capture_surface(field_names: list[Any] | tuple[Any, ...] | None) -> list[str]:
    expanded: list[str] = []
    requested = _clean_field_names(field_names)
    include_frailty_bundle = any(
        field in FRAILTY_EXPANSION_TRIGGERS or field.startswith("g8_")
        for field in requested
    )

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
    visible_fields: list[str],
) -> list[str]:
    visible_required: list[str] = []
    visible_set = set(visible_fields or [])
    for field in _clean_field_names(required_inputs):
        normalized = VISIBLE_REQUIRED_FIELD_ALIASES.get(field, field)
        if normalized in visible_set and normalized not in visible_required:
            visible_required.append(normalized)
    return visible_required


def build_capture_surface_metadata(
    raw_fields: list[Any] | tuple[Any, ...] | None,
    *,
    required_inputs: list[Any] | tuple[Any, ...] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    visible_fields = expand_visible_capture_surface(raw_fields)
    return {
        "visible_fields": visible_fields,
        "visible_required_inputs": visible_required_inputs(
            required_inputs if required_inputs is not None else raw_fields,
            visible_fields,
        ),
        "display_fields_summary": normalize_field_list(visible_fields, limit=limit),
    }


def display_capture_field_summary(
    raw_fields: list[Any] | tuple[Any, ...] | None,
    *,
    required_inputs: list[Any] | tuple[Any, ...] | None = None,
    limit: int = 8,
) -> list[str]:
    return list(
        build_capture_surface_metadata(
            raw_fields,
            required_inputs=required_inputs,
            limit=limit,
        ).get("display_fields_summary")
        or []
    )


def enrich_capture_block(
    block: dict[str, Any] | None,
    *,
    fields_key: str = "fields",
    required_key: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    payload = dict(block or {})
    raw_fields = payload.get(fields_key) or []
    required_inputs = payload.get(required_key) if required_key else raw_fields
    payload.update(
        build_capture_surface_metadata(
            raw_fields,
            required_inputs=required_inputs,
            limit=limit,
        )
    )
    return payload
