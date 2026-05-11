from __future__ import annotations

from prostanet.shared.phoenix import evaluate_phoenix


def classify_recurrence_eau(payload: dict) -> dict:
    prior_radiation = str(payload.get("prior_radiation", "0")) == "1"
    prior_prostatectomy = str(payload.get("prior_prostatectomy", "0")) == "1"
    bcr2 = str(payload.get("bcr2", "0")) == "1"
    phoenix = evaluate_phoenix(payload)

    # EAU 2026 §6.3.2 exige cumplir Phoenix (nadir + 2 ng/mL) antes de
    # etiquetar BCR post-radioterapia. Si aún no se cumple, la guía
    # recomienda mantener vigilancia y NO abrir vía de rescate.
    if prior_radiation and not prior_prostatectomy and not bcr2 and not phoenix.threshold_reached:
        return {
            "label": "Pre-Phoenix monitoring",
            "recommendation": (
                "EAU 2026: PSA aún no cumple criterio Phoenix (nadir + 2 ng/mL). "
                "Mantener PSA cada 3 meses y no iniciar rescate ni re-estadificación "
                "hasta confirmación longitudinal del umbral."
            ),
            "phoenix": phoenix.to_dict(),
            "phoenix_gate_blocked": True,
        }

    if bcr2:
        label = "BCR2 N0M0"
    elif prior_prostatectomy:
        label = "Post-RP biochemical recurrence"
    else:
        label = "Post-RT biochemical recurrence"
    return {
        "label": label,
        "recommendation": "Prefiera rescate temprano adaptado al riesgo y evite salidas indiferenciadas de recurrencia.",
        "phoenix": phoenix.to_dict(),
    }
