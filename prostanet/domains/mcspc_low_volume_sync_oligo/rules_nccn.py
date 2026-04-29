from __future__ import annotations

from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload

def evaluate_mcspc_low_volume(payload: dict) -> dict:
    payload = normalize_advanced_support_payload(payload, state="mcspc_low_volume_sync_oligo")
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    cardio_risk = str(payload.get("comorbidity_cardio", "0")) == "1" or str(payload.get("cv_risk_documented", "0")) == "1"
    child_pugh = str(payload.get("child_pugh_score", "A"))
    rt_primary_received = str(payload.get("rt_primary_received", "0")) == "1"
    ddi_reviewed = str(payload.get("ddi_review_status") or "").strip().lower() == "completed"
    brca2_status = str(payload.get("brca2_status", "Desconocido"))
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    assay_source = str(payload.get("molecular_assay_source", "Desconocida"))
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    return {
        "label": "mCSPC low-volume / synchronous oligometastatic",
        "rt_primary_candidate": not rt_primary_received,
        "prefer_darolutamide": seizure_risk or cardio_risk or not ddi_reviewed,
        "prefer_enzalutamide": not seizure_risk,
        "prefer_abiraterone": child_pugh != "C",
        "prefer_akeega": brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date),
        "rezvilutamide_candidate": not seizure_risk,
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "ddi_review_status": str(payload.get("ddi_review_status") or ""),
        "recommendation": "Prefer systemic doublets and evaluate RT to the primary when the prostate remains untreated.",
    }
