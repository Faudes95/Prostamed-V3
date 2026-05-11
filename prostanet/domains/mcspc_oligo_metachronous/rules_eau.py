from __future__ import annotations


def evaluate_mcspc_oligo_metachronous_eau(payload: dict) -> dict:
    count = int(float(payload.get("metastasis_count", 0) or 0))
    return {
        "label": "mCSPC oligometastatic metachronous",
        "recommendation": "Consider MDT plus systemic therapy in carefully selected patients." if count <= 5 else "Escalate to broader metastatic pathway.",
    }

