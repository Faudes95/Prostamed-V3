from __future__ import annotations

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)

def classify_post_rt_followup_eau(payload: dict) -> dict:
    """EAU Guidelines 2026 - Follow-up after radical radiotherapy."""
    failure = build_post_rt_failure_definition(payload)
    phoenix = bool(failure.get("phoenix_threshold_reached"))
    bounce_suspected = bool(failure.get("bounce_suspected"))
    confirmation_status = str(failure.get("phoenix_confirmation_status") or "not_met")

    if phoenix and not bounce_suspected:
        return {
            "guideline": "EAU",
            "version": "2026",
            "section": "Follow-up after radical radiotherapy - biochemical failure",
            "label": "Recurrencia bioquímica post-RT con umbral Phoenix alcanzado",
            "recommendation": (
                "mpMRI prostático seguido de PSMA-PET. Biopsia prostática confirmatoria si el paciente "
                "es candidato a salvage local. Considerar tiempo a fallo, PSADT, función basal y esperanza de vida "
                "antes de proponer prostatectomía, criocirugía, HIFU o re-irradiación de salvage."
            ),
            "rationale": (
                "El umbral Phoenix ya se alcanzó."
                if confirmation_status in {"confirmed_explicit", "confirmed_longitudinal", "biopsy_confirmed", "radiographic_localized"}
                else "El umbral Phoenix ya se alcanzó, pero la liberación curativa debe esperar confirmación longitudinal suficiente o evidencia local equivalente."
            ),
            "evidence": ["EAU Guidelines 2026"],
            "post_rt_failure_definition": failure,
        }
    return {
        "guideline": "EAU",
        "version": "2026",
        "section": "Follow-up after radical radiotherapy",
        "label": "Seguimiento post-RT sin recurrencia",
        "recommendation": (
            "PSA + DRE cada 3 meses durante el primer año, cada 6 meses durante años 2-3, anual posteriormente. "
            "Atención al bounce phenomenon en braquiterapia LDR (primeros 18-36 meses). "
            "Vigilar toxicidad tardía y segundos primarios pélvicos."
        ),
        "evidence": ["EAU Guidelines 2026"],
        "post_rt_failure_definition": failure,
    }
