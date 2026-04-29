from __future__ import annotations

from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload

def evaluate_mcspc_oligo_metachronous(payload: dict) -> dict:
    payload = normalize_advanced_support_payload(payload, state="mcspc_oligo_metachronous")
    count = int(float(payload.get("metastasis_count", 0) or 0))
    site = str(payload.get("metastasis_site", "Bone"))
    ecog = int(float(payload.get("ecog_score", 0) or 0))
    fit_for_intensification = ecog <= 2
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    cardio_risk = str(payload.get("comorbidity_cardio", "0")) == "1" or str(payload.get("cv_risk_documented", "0")) == "1"
    ddi_reviewed = str(payload.get("ddi_review_status") or "").strip().lower() == "completed"
    brca2_status = str(payload.get("brca2_status", "Desconocido"))
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    assay_source = str(payload.get("molecular_assay_source", "Desconocida"))
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    mdt_context = str(payload.get("mdt_context", "No documentado"))
    return {
        "label": "mCSPC oligometastatic metachronous",
        "fit_for_intensification": fit_for_intensification,
        "mdt_candidate": count <= 5 and site.lower() != "visceral" and mdt_context in {"Ensayo/cohorte prospectiva", "Discusión multidisciplinaria"},
        "mdt_context": mdt_context,
        "prefer_darolutamide": fit_for_intensification and (seizure_risk or cardio_risk or not ddi_reviewed),
        "prefer_enzalutamide": fit_for_intensification and not seizure_risk,
        "prefer_abiraterone": fit_for_intensification and not cardio_risk,
        "prefer_akeega": brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date),
        "rezvilutamide_candidate": fit_for_intensification and not seizure_risk,
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "ddi_review_status": str(payload.get("ddi_review_status") or ""),
        "recommendation": "Combine systemic intensification with MDT discussion when disease is limited.",
    }
