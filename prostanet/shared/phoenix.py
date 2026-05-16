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
    """Phoenix BCR criterion: PSA ≥ nadir + 2.0 ng/mL (RTOG-ASTRO 2006).

    EPIC 31.F (Explore EXP-11 MOD) — context awareness:
    - Para POST-RT BCR (state ∈ post_ebrt_alone, post_brachy_*, post_sbrt,
      post_focal_therapy): Phoenix nadir+2 es el criterio canonical.
    - Para CRPC (state ∈ m0_crpc, m1_crpc, adt_progression_verification):
      PCWG3 Scher JCO 2016 requiere additionally ≥25% rise from nadir +
      ≥2 ng/mL absolute + confirmatory ≥21d. El threshold Phoenix solo
      es part of the picture — el rationale debe indicarlo claramente.
    """
    data = dict(payload or {})
    nadir = _safe_float(data.get("psa_nadir"))
    current = _safe_float(data.get("psa_current") or data.get("psa"))
    stored_delta = _safe_float(data.get("phoenix_delta"))
    stored_threshold = _safe_float(data.get("phoenix_threshold"))
    # Context: state-aware rationale
    state_context = str(
        data.get("reconciled_state")
        or data.get("current_state")
        or data.get("clinical_state")
        or ""
    ).lower()
    POST_RT_STATES = {
        "post_ebrt_alone", "post_brachy_ldr", "post_brachy_hdr",
        "post_sbrt", "post_focal_therapy", "post_rt_bcr",
        "post_combined_modality",
    }
    CRPC_STATES = {
        "m0_crpc", "m1_crpc", "adt_progression_verification",
        "mcrpc_arsi_naive", "mcrpc_post_arsi", "mcrpc_hrr_positive_parp_naive",
        "mcrpc_psma_eligible_lu177", "mcrpc_msi_h_dmmr",
    }
    is_post_rt = any(s in state_context for s in POST_RT_STATES)
    is_crpc = any(s in state_context for s in CRPC_STATES)

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
        # EPIC 31.F — context-aware rationale
        if is_post_rt:
            rationale = (
                "PSA actual ≥ nadir + 2.0 ng/mL: criterio Phoenix BCR post-RT "
                "(RTOG-ASTRO 2006) cumplido. Evaluar salvage local."
            )
        elif is_crpc:
            rationale = (
                "PSA actual ≥ nadir + 2.0 ng/mL: criterio absoluto cumplido. "
                "Para confirmar progresión CRPC, PCWG3 (Scher JCO 2016) "
                "requiere TAMBIÉN ≥25% rise desde nadir + confirmación ≥21d."
            )
        else:
            rationale = "PSA actual ≥ nadir + 2.0 ng/mL: criterio Phoenix cumplido."
    else:
        if is_post_rt:
            rationale = (
                "Aumento de PSA aún no cumple Phoenix (nadir + 2 ng/mL) "
                "post-RT; mantener vigilancia — no detonar salvage prematuro."
            )
        elif is_crpc:
            rationale = (
                "PSA bajo umbral Phoenix; para CRPC, PCWG3 evalúa rising "
                "como nadir + ≥25% + ≥2 ng/mL absoluto + confirmación ≥21d. "
                "Mantener vigilancia."
            )
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
