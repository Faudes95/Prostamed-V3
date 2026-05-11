from __future__ import annotations


def evaluate_mcspc_high_volume_eau(payload: dict, *, temporality: str = "sync") -> dict:
    label_suffix = "sincrónico" if temporality == "sync" else "metacrónico"
    return {
        "label": f"mCSPC high-volume {label_suffix}",
        "recommendation": "Use treatment intensification in fit patients and avoid undertreatment of high-volume disease; in metachronous high-volume disease, do not overstate PEACE-1 as the default backbone.",
    }
