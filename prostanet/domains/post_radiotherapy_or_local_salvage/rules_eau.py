from __future__ import annotations

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import build_post_rt_failure_definition


def classify_post_rt_eau(payload: dict) -> dict:
    failure_definition = build_post_rt_failure_definition(payload)
    if failure_definition.get("phoenix_status") == "met":
        recommendation = "La recurrencia bioquímica post-RT debe cerrarse con definición Phoenix antes de seleccionar salvage local o transición sistémica."
    elif failure_definition.get("failure_confirmation_basis") in {"biopsy_proven_local_failure", "radiographic_local_failure"}:
        recommendation = "La evidencia local equivalente permite discutir salvage, pero la factibilidad anatómica y la reestadificación siguen siendo obligatorias."
    else:
        recommendation = "La EAU 2026 no respalda salvage curativo sin definición Phoenix o confirmación local estructurada."
    return {
        "label": "Post-RT biochemical recurrence",
        "recommendation": recommendation,
        "post_rt_failure_definition": failure_definition,
    }
