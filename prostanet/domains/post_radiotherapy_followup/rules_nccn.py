from __future__ import annotations

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)

def _classify_late_rt_toxicity(payload: dict) -> dict:
    """Auditoría Pacientes Insignia 2026-04-21 (§C.4) — detecta toxicidad RT
    tardía RADICALS-RT/RTOG. Acepta CTCAE v5 canónico ("Grado 2 – moderado",
    etc.) y alias legacy boolean ("1","Sí") que usan perfiles insignia.

    Devuelve dict con tiers numéricos (0-5) por sitio y flag agregado que
    bloquea re-irradiación y gatilla derivación multidisciplinar.
    """
    def _tier(text: str) -> int:
        raw = str(text or "").strip().lower()
        if not raw:
            return 0
        if "grado 5" in raw or "muerte" in raw:
            return 5
        if "grado 4" in raw:
            return 4
        if "grado 3" in raw:
            return 3
        if "grado 2" in raw:
            return 2
        if "grado 1" in raw:
            return 1
        if raw in {"sí", "si", "1", "yes", "true"}:
            # Alias legacy del perfil insignia RADICALS-RT.
            return 2
        return 0

    gu_tier = _tier(payload.get("late_rt_toxicity_gu"))
    gi_tier = _tier(payload.get("late_rt_toxicity_gi"))
    return {
        "late_rt_toxicity_gu_tier": gu_tier,
        "late_rt_toxicity_gi_tier": gi_tier,
        "late_toxicity_present": gu_tier >= 2 or gi_tier >= 2,
        "late_toxicity_blocks_reirradiation": gu_tier >= 3 or gi_tier >= 3,
    }


def classify_post_rt_followup_nccn(payload: dict) -> dict:
    """NCCN Prostate Cancer v5.2026 PROS-9 - Follow-up after radiation therapy."""
    failure = build_post_rt_failure_definition(payload)
    phoenix = bool(failure.get("phoenix_threshold_reached"))
    bounce_suspected = bool(failure.get("bounce_suspected"))
    confirmation_status = str(failure.get("phoenix_confirmation_status") or "not_met")
    late_toxicity = _classify_late_rt_toxicity(payload)

    if phoenix and not bounce_suspected:
        return {
            "guideline": "NCCN",
            "version": "5.2026",
            "panel": "PROS-9",
            "label": "Fallo bioquímico post-RT (Phoenix umbral alcanzado)",
            "recommendation": (
                "Restadificar con PSMA-PET preferente (alternativa CT abdomen-pelvis + bone scan), "
                "complementar con mpMRI prostático y biopsia prostática si el paciente es candidato a salvage local. "
                "Transición sugerida al asistente post_radiotherapy_or_local_salvage."
            ),
            "rationale": (
                "Se alcanzó el umbral Phoenix (PSA actual >= nadir + 2.0 ng/mL). "
                + (
                    "La serie longitudinal ya ofrece soporte confirmatorio suficiente."
                    if confirmation_status in {"confirmed_explicit", "confirmed_longitudinal", "biopsy_confirmed", "radiographic_localized"}
                    else "Todavía debe confirmarse longitudinalmente y descartarse bounce post-braquiterapia si aplica."
                )
            ),
            "evidence": ["NCCN Prostate v5.2026 PROS-9", "Roach 2006 IJROBP"],
            "post_rt_failure_definition": failure,
            **late_toxicity,
        }
    return {
        "guideline": "NCCN",
        "version": "5.2026",
        "panel": "PROS-9",
        "label": "Vigilancia post-radioterapia sin recurrencia",
        "recommendation": (
            "PSA cada 3-6 meses los primeros 5 años, luego anual de por vida. DRE anual; puede omitirse si PSA bien controlado. "
            "Manejo proactivo de toxicidad tardía urinaria, intestinal y sexual con escala RTOG/EORTC. "
            "Vigilancia de segundos primarios pélvicos (vejiga, recto). Survivorship dirigido a ADT si aplica."
        ),
        "rationale": (
            "Sin criterio Phoenix cumplido. Protocolo NCCN PROS-9 estándar de seguimiento post-radioterapia radical."
        ),
        "evidence": ["NCCN Prostate v5.2026 PROS-9", "NCCN Survivorship"],
        "post_rt_failure_definition": failure,
        **late_toxicity,
    }
