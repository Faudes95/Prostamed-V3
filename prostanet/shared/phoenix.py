"""Helper centralizado para el criterio Phoenix (RTOG-ASTRO 2006).

Phoenix = PSA actual ≥ nadir + 2.0 ng/mL, verificable contra PSA post-RT.
Este módulo existe para que los dominios `recurrence_bcr`,
`post_radiotherapy_followup`, `post_rt_salvage_copilot_service` y cualquier
consumidor futuro lean el mismo gate sin duplicar lógica.

Evidencia: Roach M et al. *IJROBP* 2006;65:965 (category 1 NCCN PROS-10,
EAU 2026 §6.3.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PhoenixEvaluation:
    nadir: float | None
    current: float | None
    delta: float | None
    threshold: float | None
    threshold_reached: bool
    assessable: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "psa_nadir": self.nadir,
            "psa_current": self.current,
            "phoenix_delta": self.delta,
            "phoenix_threshold": self.threshold,
            "phoenix_threshold_reached": self.threshold_reached,
            "phoenix_assessable": self.assessable,
            "phoenix_rationale": self.rationale,
        }


def evaluate_phoenix(payload: dict[str, Any] | None) -> PhoenixEvaluation:
    data = dict(payload or {})
    nadir = _safe_float(data.get("psa_nadir"))
    current = _safe_float(data.get("psa_current") or data.get("psa"))
    stored_delta = _safe_float(data.get("phoenix_delta"))
    stored_threshold = _safe_float(data.get("phoenix_threshold"))

    threshold = (
        stored_threshold
        if stored_threshold is not None
        else (round(nadir + 2.0, 3) if nadir is not None else None)
    )
    delta = (
        stored_delta
        if stored_delta is not None
        else (
            round(current - nadir, 3)
            if nadir is not None and current is not None
            else None
        )
    )
    threshold_reached = bool(
        (threshold is not None and current is not None and current >= threshold)
        or (delta is not None and delta >= 2.0)
    )
    assessable = nadir is not None and current is not None

    if not assessable:
        rationale = "Sin PSA actual o nadir disponible: Phoenix no evaluable."
    elif threshold_reached:
        rationale = "PSA actual ≥ nadir + 2.0 ng/mL: criterio Phoenix cumplido."
    else:
        rationale = (
            "Aumento de PSA aún no cumple Phoenix (nadir + 2 ng/mL); "
            "mantener vigilancia — no detonar salvage prematuro."
        )

    return PhoenixEvaluation(
        nadir=nadir,
        current=current,
        delta=delta,
        threshold=threshold,
        threshold_reached=threshold_reached,
        assessable=assessable,
        rationale=rationale,
    )


def phoenix_failure(payload: dict[str, Any] | None) -> bool:
    """Booleano compacto: ¿el paciente cumple Phoenix?"""
    return evaluate_phoenix(payload).threshold_reached


__all__ = ["PhoenixEvaluation", "evaluate_phoenix", "phoenix_failure"]
