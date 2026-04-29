from __future__ import annotations


def classify_post_rp_eau(payload: dict) -> dict:
    psa_postop = float(payload.get("psa_postop", payload.get("psa_current", 0)) or 0)
    bcr_confirmed = str(payload.get("bcr_detected", "0")).lower() in {"1", "true", "yes", "si"}
    if bcr_confirmed or psa_postop >= 0.2:
        label = "Post-RP biochemical recurrence"
    elif psa_postop >= 0.1:
        label = "Post-RP low-level detectable PSA"
    else:
        label = "Post-RP follow-up"
    return {
        "label": label,
        "recommendation": "Prefiera seguimiento adaptado al riesgo y toma temprana de decisiones de rescate por encima de tratamiento adyuvante reflejo.",
    }
