from __future__ import annotations

from typing import Any

from prostanet.shared.presentation_text import state_display_label


_PROGRESSION_CONTEXTS = {"none", "progression_on_adt_verify_castration", "confirmed_crpc"}
_PROGRESSION_PATTERNS = {"biochemical_only", "radiographic", "clinical", "mixed"}
_TRUTHY = {"1", "true", "yes", "si", "sí", "on"}


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def is_true(value: Any) -> bool:
    return normalize_text(value).lower() in _TRUTHY


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_progression_pattern(value: Any, default: str = "biochemical_only") -> str:
    text = normalize_text(value).lower()
    return text if text in _PROGRESSION_PATTERNS else default


def normalize_castrate_status(
    explicit_status: Any,
    *,
    testosterone_value: Any = None,
    castrate_confirmed_flag: Any = None,
) -> str:
    normalized = normalize_text(explicit_status)
    if normalized in {"confirmed_castrate", "not_castrate", "unknown"}:
        return normalized
    if castrate_confirmed_flag not in (None, ""):
        return "confirmed_castrate" if is_true(castrate_confirmed_flag) else "not_castrate"
    testosterone = safe_float(testosterone_value)
    if testosterone is None:
        return "unknown"
    return "confirmed_castrate" if testosterone <= 50 else "not_castrate"


def resolve_systemic_progression_context(
    explicit_context: Any,
    *,
    legacy_crpc_signal: bool = False,
    line_of_therapy: Any = None,
) -> str:
    normalized = normalize_text(explicit_context)
    if normalized in _PROGRESSION_CONTEXTS:
        return normalized
    line_number = safe_int(line_of_therapy) or 0
    if legacy_crpc_signal or line_number > 1:
        return "confirmed_crpc"
    return "none"


def requires_adt_progression_gate(
    *,
    systemic_progression_context: str,
    on_adt: bool,
    castrate_status: str,
    progression_pattern: str,
    prior_prostatectomy: bool,
    prior_radiation: bool,
) -> bool:
    normalized_context = resolve_systemic_progression_context(systemic_progression_context)
    normalized_pattern = normalize_progression_pattern(progression_pattern)
    if normalized_context == "progression_on_adt_verify_castration":
        return True
    if normalized_context == "confirmed_crpc" and castrate_status != "confirmed_castrate":
        return True
    if on_adt and castrate_status != "confirmed_castrate" and normalized_pattern in _PROGRESSION_PATTERNS:
        return True
    if (prior_prostatectomy or prior_radiation) and on_adt and castrate_status != "confirmed_castrate":
        return True
    return False


def build_progression_gate(
    *,
    systemic_progression_context: str,
    on_adt: bool,
    castrate_status: str,
    progression_pattern: str,
    prior_prostatectomy: bool,
    prior_radiation: bool,
    phenotype_state: str = "",
) -> dict[str, Any]:
    resolved_context = resolve_systemic_progression_context(systemic_progression_context)
    active = requires_adt_progression_gate(
        systemic_progression_context=resolved_context,
        on_adt=on_adt,
        castrate_status=castrate_status,
        progression_pattern=progression_pattern,
        prior_prostatectomy=prior_prostatectomy,
        prior_radiation=prior_radiation,
    )
    phenotype_label = state_display_label(phenotype_state)
    if active and phenotype_label:
        reason = (
            f"El fenotipo {phenotype_label} ya es visible, pero la intensificación resistente sigue bloqueada "
            "hasta confirmar testosterona en rango de castración y reestadificación convencional."
        )
    elif active:
        reason = (
            "La progresión bajo ADT requiere confirmar testosterona en rango de castración y reestadificación "
            "convencional antes de cerrar el carril resistente."
        )
    elif resolved_context == "confirmed_crpc":
        reason = "La progresión resistente a la castración ya quedó cerrada con la información longitudinal disponible."
    else:
        reason = ""
    return {
        "progression_gate_active": active,
        "progression_gate_target": "adt_progression_verification" if active else "",
        "progression_gate_reason": reason,
        "systemic_progression_context_resolved": resolved_context,
    }
