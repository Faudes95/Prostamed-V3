from __future__ import annotations

from clinical_scores import docetaxel_fitness
from prostanet.shared.advanced_support_normalizer import (
    normalize_advanced_support_payload,
    resolve_child_pugh_bc,
    resolve_docetaxel_fit_override,
)


def _resolve_temporality(payload: dict, default: str = "auto") -> str:
    explicit = str(payload.get("disease_temporality", "") or "").strip().lower()
    if explicit in {"sync", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "sync"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "metachronous"
    metachronous = str(payload.get("metachronous_metastasis", "0")).strip().lower()
    if metachronous in {"1", "true", "yes", "si", "sí"}:
        return "metachronous"
    if default in {"sync", "metachronous"}:
        return default
    return "sync"


def evaluate_mcspc_high_volume(payload: dict, *, default_temporality: str = "auto") -> dict:
    temporality = _resolve_temporality(payload, default_temporality)
    resolved_state = "mcspc_high_volume_sync" if temporality == "sync" else "mcspc_high_volume_metachronous"
    payload = normalize_advanced_support_payload(payload, state=resolved_state)
    docetaxel = docetaxel_fitness({**payload, "state": resolved_state})
    child_pugh = str(payload.get("child_pugh_score", "A") or "A").strip().upper()
    # Auditoría Pacientes Insignia 2026-04-21 (§B.1) — gate hepático unificado
    # reconoce `child_pugh_score` canónico y `child_pugh_b_or_c` boolean de
    # perfiles insignia. Habilita bloqueo de LATITUDE/PEACE-1/abiraterone
    # doublet cuando el paciente tiene compromiso hepático moderado/severo.
    child_pugh_bc = resolve_child_pugh_bc(payload)
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    cardio_risk = str(payload.get("comorbidity_cardio", "0")) == "1" or str(payload.get("cv_risk_documented", "0")) == "1"
    frailty = str(payload.get("frailty_status", "Fit") or "Fit")
    assay_source = str(payload.get("molecular_assay_source", payload.get("biomarker_source", "Desconocida")) or "Desconocida")
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_status = str(payload.get("brca2_status", "Desconocido") or "Desconocido")
    hrr_gene = str(payload.get("hrr_gene", "Desconocido") or "Desconocido")
    ddi_reviewed = str(payload.get("ddi_review_status") or "").strip().lower() == "completed"

    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    brca2_origin = str(payload.get("brca2_origin", "unknown") or "unknown").strip().lower()
    molecular_traceable = brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date) and brca2_origin != "unknown"
    fit_for_docetaxel = bool(docetaxel["fit_for_docetaxel"])
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — override explícito de
    # docetaxel_fit si el clínico documentó Apto/No apto/Marginal.
    docetaxel_override = resolve_docetaxel_fit_override(payload)
    if docetaxel_override is not None:
        fit_for_docetaxel = docetaxel_override
    docetaxel_base_eligibility = str(docetaxel.get("docetaxel_base_eligibility") or "not_assessable")
    docetaxel_default_intensification = str(docetaxel.get("docetaxel_default_intensification") or "no")

    prefer_triplet_darolutamide = docetaxel_default_intensification == "yes" and (
        seizure_risk
        or cardio_risk
        or not ddi_reviewed
        or docetaxel.get("fit_status") == "fit_with_caution"
    )
    prefer_triplet_abiraterone = temporality == "sync" and docetaxel_default_intensification == "yes" and not cardio_risk and child_pugh == "A"
    prefer_doublet_darolutamide = (
        docetaxel_base_eligibility == "contraindicated" or docetaxel_default_intensification == "conditional"
    ) and (
        cardio_risk or seizure_risk or not ddi_reviewed or docetaxel.get("fit_status") == "fit_with_caution"
    )
    prefer_docetaxel_doublet = (
        docetaxel_base_eligibility in {"eligible", "eligible_with_caution"}
        and docetaxel_default_intensification != "yes"
        and temporality in {"sync", "metachronous"}
    )

    label_suffix = "sincrónico" if temporality == "sync" else "metacrónico"
    recommendation = (
        "Priorizar triplete si docetaxel tiene elegibilidad plena; si es condicional o contraindicado, reabrir la competencia entre dobletes y mantener ADT + docetaxel solo como alternativa estructurada."
        if temporality == "sync"
        else "Intensificar con triplete solo si docetaxel tiene elegibilidad plena; en caso contrario, priorizar dobletes hormonales y usar ADT + docetaxel solo como alternativa estructurada."
    )

    return {
        "label": f"mCSPC high-volume {label_suffix}",
        "temporal_pattern": temporality,
        "docetaxel_fitness": docetaxel,
        "fit_for_docetaxel": fit_for_docetaxel,
        "docetaxel_base_eligibility": docetaxel_base_eligibility,
        "docetaxel_default_intensification": docetaxel_default_intensification,
        "docetaxel_trial_fit": dict(docetaxel.get("docetaxel_trial_fit") or {}),
        "prefer_akeega": molecular_traceable,
        "prefer_triplet_darolutamide": prefer_triplet_darolutamide,
        "prefer_triplet_abiraterone": prefer_triplet_abiraterone,
        "prefer_doublet_darolutamide": prefer_doublet_darolutamide,
        "prefer_docetaxel_doublet": prefer_docetaxel_doublet,
        "prefer_abiraterone_doublet": child_pugh == "A" and not cardio_risk,
        "prefer_enzalutamide": not seizure_risk and frailty != "Frail",
        "prefer_apalutamide": frailty != "Frail" and not seizure_risk,
        "rezvilutamide_candidate": not seizure_risk and frailty != "Frail",
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "molecular_traceable": molecular_traceable,
        "brca2_origin": brca2_origin,
        # Auditoría Pacientes Insignia 2026-04-21 (§B.1) — dos vistas del gate:
        #   `abiraterone_hepatic_tier` (string, legacy compat) conserva la
        #   semántica histórica "contraindicated"/"caution"/"clear" usada por
        #   service.py para enriquecer contraindications.
        #   `abiraterone_hepatic_block` (bool) unifica la decisión clínica:
        #   True → abiraterona NO recomendada (Child-Pugh B/C o señal
        #   booleana `child_pugh_b_or_c`). Lo consume service.py para
        #   LATITUDE/PEACE-1 (§B.2) y suprime la emisión.
        "abiraterone_hepatic_tier": (
            "contraindicated" if child_pugh == "C"
            else "caution" if child_pugh == "B"
            else "clear"
        ),
        "abiraterone_hepatic_gate": child_pugh_bc,
        "abiraterone_hepatic_block": child_pugh_bc,
        "child_pugh_bc": child_pugh_bc,
        "ddi_review_status": str(payload.get("ddi_review_status") or ""),
        "recommendation": recommendation,
    }
