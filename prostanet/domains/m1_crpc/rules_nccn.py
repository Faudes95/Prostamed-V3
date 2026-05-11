from __future__ import annotations

from clinical_scores import docetaxel_fitness
from prostanet.shared.advanced_support_normalizer import (
    normalize_advanced_support_payload,
    resolve_child_pugh_bc,
    resolve_docetaxel_fit_override,
)


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _has_visceral_disease_local(payload: dict) -> bool:
    """Detecta enfermedad visceral usando las mismas heurísticas que
    `trial_matching_engine._has_visceral_disease` (sin import cíclico).
    """
    for key in ("visceral_disease", "visceral_metastasis", "visceral_metastases",
                "visceral_metastasis_present"):
        raw = payload.get(key)
        if str(raw or "").strip().lower() in {"1", "true", "yes", "si", "sí", "positive", "positivo"}:
            return True
    site = str(payload.get("metastasis_site", "")).lower()
    return any(tok in site for tok in ("visceral", "liver", "lung", "hígado", "pulmón", "pulmon"))


def _status_positive(payload: dict, key: str) -> bool:
    val = str(payload.get(key, "Desconocido")).lower()
    return val.startswith("pos") or val in {"detected", "detectado", "mutado", "loss", "perdida", "biallelic", "bialélico"}


def _normalize_line_context(value: str, *, prior_arpi: bool, prior_docetaxel: bool) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "first_line_mcrpc", "line_1", "line1", "first_line", "pre_arpi"}:
        return "first_line_mcrpc"
    if normalized in {"post_arpi_pre_taxane", "pre_taxane"}:
        return "post_arpi_pre_taxane"
    if normalized in {"post_taxane", "post_docetaxel", "later_line"}:
        return "post_taxane"
    if prior_arpi and prior_docetaxel:
        return "post_taxane"
    if prior_arpi:
        return "post_arpi_pre_taxane"
    return "first_line_mcrpc"


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def evaluate_m1_crpc(payload: dict) -> dict:
    payload = normalize_advanced_support_payload(payload, state="m1_crpc")
    hrr = str(payload.get("hrr_status", "Desconocido"))
    msi = str(payload.get("msi_status", "desconocido"))
    # dMMR por IHC (KEYNOTE-158/199): pérdida de MLH1/MSH2/MSH6/PMS2 en IHC
    # o variante patogénica somática/germinal en esos genes.
    mmr_ihc = str(payload.get("mmr_ihc_status", "desconocido")).lower()
    mmr_genes = {"MSH2", "MLH1", "MSH6", "PMS2"}
    somatic_variant = str(payload.get("somatic_pathogenic_variant", "")).upper()
    germline_variant = str(payload.get("germline_pathogenic_variant", "")).upper()
    dmmr_detected = (
        mmr_ihc in {"deficient_dmmr", "deficient", "dmmr"}
        or somatic_variant in mmr_genes
        or germline_variant in mmr_genes
    )
    psma_positive = _flag(payload, "psma_positive")
    tmb_high = _flag(payload, "tmb_high")
    prior_docetaxel_cycles = int(float(payload.get("prior_docetaxel_cycles", 0) or 0))
    prior_therapy = str(payload.get("prior_therapy", ""))
    prior_therapy_lower = prior_therapy.lower()
    prior_arpi = any(
        token in prior_therapy_lower
        for token in ["abirater", "enzalut", "apalut", "darolut", "rezvilut"]
    )
    chemotherapy_delay_candidate = _flag(payload, "chemotherapy_delay_candidate")
    castrate_confirmed = _flag(payload, "castrate_testosterone_confirmed")
    if not castrate_confirmed:
        castrate_status = str(payload.get("castrate_testosterone_status") or "").strip().lower()
        testosterone_value = _safe_float(
            payload.get("testosterone_value")
            or payload.get("testosterone")
            or payload.get("testosterone_current")
        )
        castrate_confirmed = castrate_status == "confirmed_castrate" or (
            testosterone_value is not None and testosterone_value <= 50
        )
    prior_abiraterone = "abirater" in prior_therapy_lower
    prior_enza_class = any(
        token in prior_therapy_lower for token in ["enzalut", "apalut", "darolut", "rezvilut"]
    )
    prior_docetaxel = prior_docetaxel_cycles >= 6 or "docetax" in prior_therapy_lower
    line_context = _normalize_line_context(
        str(payload.get("mcrpc_line_context", payload.get("line_context", "first_line_mcrpc")) or "first_line_mcrpc"),
        prior_arpi=prior_arpi,
        prior_docetaxel=prior_docetaxel,
    )
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    symptomatic_bone_only = str(payload.get("pain_symptoms", "Asintomatico")) != "Asintomatico" and str(payload.get("metastasis_site", "Bone")) == "Bone"

    ecog_score = _safe_int(payload.get("ecog_score") or payload.get("ecog_performance_status") or payload.get("ecog") or 1) or 1
    frailty_status = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    child_pugh_score = str(payload.get("child_pugh_score", "A") or "A").strip().upper()
    # Auditoría Pacientes Insignia 2026-04-21 (§B.1) — unificar gate hepático
    # reconociendo tanto `child_pugh_score` (canónico A/B/C) como la señal
    # legacy boolean `child_pugh_b_or_c`/`child_pugh_class` que usan perfiles
    # insignia sin UI completa.
    child_pugh_bc = resolve_child_pugh_bc(payload)
    cardio_risk = _flag(payload, "cv_risk_documented")
    ddi_review_status = str(payload.get("ddi_review_status") or "").strip().lower()
    ddi_reviewed = ddi_review_status == "completed"
    hepatic_bundle = dict(payload.get("hepatic_safety_bundle") or {})
    hepatic_risk = bool(hepatic_bundle.get("hepatic_risk_present")) or child_pugh_bc
    current_medications = str(payload.get("current_medications") or "").strip()
    current_medications_present = bool(payload.get("normalized_medication_list")) or bool(current_medications)
    seizure_risk = _flag(payload, "comorbidity_seizure") or _status_positive(payload, "seizure_history")
    taxane_candidate_now = not prior_docetaxel and line_context in {"first_line_mcrpc", "post_arpi_pre_taxane"}

    taxane_payload = dict(payload)
    taxane_payload.setdefault("ecog_score", ecog_score)
    taxane_payload["force_docetaxel_verification"] = 1 if taxane_candidate_now else 0
    taxane_payload["docetaxel_context"] = "mcrpc_taxane_competition"
    docetaxel_bundle = docetaxel_fitness(taxane_payload)
    docetaxel_fit = bool(docetaxel_bundle.get("fit_for_docetaxel"))
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — override explícito del
    # clínico. `resolve_docetaxel_fit_override` reconoce ES-médica
    # ("Apto (fit)", "No apto", "Marginal", "Desconocido") y alias legacy
    # ("0", "1", "taxane_fitness", etc.). Ignoramos el override cuando el
    # contexto exige verificación estructural (taxane_candidate_now) para no
    # saltarnos el clinical_scores.docetaxel_fitness en 1L/post-ARPI.
    docetaxel_override = resolve_docetaxel_fit_override(payload)
    if docetaxel_override is not None and not taxane_candidate_now:
        docetaxel_fit = docetaxel_override

    abiraterone_hard_block = hepatic_risk
    abiraterone_caution = cardio_risk or not ddi_reviewed
    # Auditoría Pacientes Insignia 2026-04-21 (§B.1) — gate explícito reusable
    # por PROpel/COU-AA-301/302/IPATential150 sin recalcular cada vez.
    abiraterone_hepatic_gate = abiraterone_hard_block

    # ── Biomarcadores expandidos ─────────────────────────────────────
    ar_v7_positive = _status_positive(payload, "ar_v7_status")
    tp53_altered = _status_positive(payload, "tp53_status")
    rb1_loss = _status_positive(payload, "rb1_status")
    pten_loss = _status_positive(payload, "pten_loss") or _status_positive(payload, "pten_status")
    cdk12_biallelic = _status_positive(payload, "cdk12_status")

    tmb_value = _safe_float(payload.get("tmb_value") or payload.get("tmb_mutations_per_mb") or 0)
    tmb_zone = "high" if (tmb_high or (tmb_value is not None and tmb_value > 10)) else (
        "gray" if (tmb_value is not None and 6 <= tmb_value <= 10) else "low"
    )

    ctdna_detected = _flag(payload, "ctdna_detected")
    ctdna_vaf = _safe_float(payload.get("ctdna_vaf") or 0) or None
    ctdna_rising = _flag(payload, "ctdna_rising")

    neuroendocrine_features = _flag(payload, "neuroendocrine_features")
    nepc_suspicion_score = 0
    if tp53_altered and rb1_loss:
        nepc_suspicion_score += 2
    if neuroendocrine_features:
        nepc_suspicion_score += 2
    nse_elevated = False
    nse = _safe_float(payload.get("nse") or payload.get("neuron_specific_enolase") or 0)
    if nse is not None and nse > 16.3:
        nse_elevated = True
        nepc_suspicion_score += 1
    ldh_elevated = False
    ldh = _safe_float(payload.get("ldh") or payload.get("lactate_dehydrogenase") or 0)
    if ldh is not None and ldh > 250:
        ldh_elevated = True
        nepc_suspicion_score += 1
    psa_discordant_low = _flag(payload, "psa_discordant_low")
    if psa_discordant_low:
        nepc_suspicion_score += 1
    nepc_suspected = nepc_suspicion_score >= 3
    lineage_plasticity_risk = tp53_altered and rb1_loss

    # MSI-H/dMMR combinados (KEYNOTE-158 / KEYNOTE-199). TMB ≥10 también
    # activa pembrolizumab (agnostic approval FDA 2020, Marabelle JCO 2020).
    msi_high = msi == "inestable"
    dmmr_high_confidence = msi_high or dmmr_detected
    tmb_high_flag = tmb_high or (tmb_value is not None and tmb_value > 10)
    pembrolizumab_candidate = dmmr_high_confidence or tmb_high_flag

    # ── Auditoría Pacientes Insignia 2026-04-21 (§A.3) ──────────────────
    # IMPACT (sipuleucel-T, Kantoff NEJM 2010) — inmunoterapia autóloga en
    # mCRPC asintomático o mínimamente sintomático sin enfermedad visceral
    # y sin uso crónico de opioides, en 1L o post-ARPI pre-taxane.
    #
    # CONTACT-02 (cabo+atezo, Agarwal Lancet Oncol 2024) — mCRPC post-ARPI
    # con enfermedad visceral o adenopatías extra-pélvicas que rehúsan o no
    # son candidatos a docetaxel. Contraindicado con autoinmunidad activa.
    _pain_tier = str(
        payload.get("pain_status") or payload.get("pain_symptoms") or ""
    ).strip().lower()
    _opioid_use = str(
        payload.get("opioid_use_for_pain") or payload.get("opioid_use") or ""
    ).strip().lower()
    _is_asymptomatic_or_mild = (
        any(tok in _pain_tier for tok in ("asintomatic", "asymptom", "leve", "mild"))
        and "cron" not in _opioid_use
        and "chronic" not in _opioid_use
    )

    _extra_pelvic = str(
        payload.get("extra_pelvic_nodal_metastasis")
        or payload.get("nodal_extrapelvic")
        or ""
    ).strip().lower()
    _extra_pelvic_present = _extra_pelvic in {"sí", "si", "1", "yes", "true"}

    _autoimmune_active = str(
        payload.get("active_autoimmune_disease") or ""
    ).strip().lower() in {"sí", "si", "1", "yes", "true"}
    _immunosuppression_active = str(
        payload.get("active_immunosuppression") or ""
    ).strip().lower() in {"sí", "si", "1", "yes", "true"}
    _not_chemo_cand = str(
        payload.get("not_chemotherapy_candidate") or ""
    ).strip().lower() in {"sí", "si", "1", "yes", "true"}

    _has_visceral = _has_visceral_disease_local(payload)

    impact_candidate = (
        line_context in {"first_line_mcrpc", "post_arpi_pre_taxane"}
        and not _has_visceral
        and _is_asymptomatic_or_mild
        and not prior_docetaxel
    )
    impact_blocked_by_immunosuppression = impact_candidate and _immunosuppression_active
    contact02_candidate = (
        prior_arpi
        and (_has_visceral or _extra_pelvic_present)
        and (not prior_docetaxel or _not_chemo_cand)
        and not _autoimmune_active
    )
    contact02_blocked_by_autoimmune = (
        prior_arpi
        and (_has_visceral or _extra_pelvic_present)
        and _autoimmune_active
    )

    return {
        "label": "M1 CRPC",
        "hrr_positive": hrr.lower().startswith("pos"),
        "msi_high": msi_high,
        "dmmr_detected": dmmr_detected,
        "dmmr_high_confidence": dmmr_high_confidence,
        "mmr_ihc_status": mmr_ihc,
        "tmb_high": tmb_high_flag,
        "pembrolizumab_candidate": pembrolizumab_candidate,
        "psma_positive": psma_positive,
        "prior_arpi": prior_arpi,
        "prior_docetaxel": prior_docetaxel,
        "prior_abiraterone": prior_abiraterone,
        "prior_enza_class": prior_enza_class,
        "symptomatic_bone_only": symptomatic_bone_only,
        "line_context": line_context,
        "docetaxel_fit": docetaxel_fit,
        "taxane_candidate_now": taxane_candidate_now,
        "docetaxel_fitness": docetaxel_bundle,
        "docetaxel_base_eligibility": str(docetaxel_bundle.get("docetaxel_base_eligibility") or "not_assessable"),
        "docetaxel_verification_status": str(docetaxel_bundle.get("docetaxel_verification_status") or "verified"),
        "docetaxel_block_type": str(docetaxel_bundle.get("docetaxel_block_type") or "none"),
        "docetaxel_required_now": bool(docetaxel_bundle.get("docetaxel_required_now")),
        "docetaxel_default_intensification": str(docetaxel_bundle.get("docetaxel_default_intensification") or "no"),
        "docetaxel_hard_stop_reasons": list(docetaxel_bundle.get("docetaxel_hard_stop_reasons") or []),
        "docetaxel_missing_inputs": list(docetaxel_bundle.get("docetaxel_missing_inputs") or []),
        "docetaxel_stale_inputs": list(docetaxel_bundle.get("docetaxel_stale_inputs") or []),
        "chemotherapy_delay_candidate": chemotherapy_delay_candidate,
        "castrate_confirmed": castrate_confirmed,
        "brca_pathway": hrr_gene in {"BRCA1", "BRCA2"},
        "hrr_gene": hrr_gene,
        "rare_histology_variant": str(payload.get("rare_histology_variant", "0")) == "1",
        "neuroendocrine_features": neuroendocrine_features,
        "ecog_score": ecog_score,
        "frailty_status": frailty_status,
        "child_pugh_score": child_pugh_score,
        "cv_risk_documented": cardio_risk,
        "ddi_review_status": ddi_review_status,
        "current_medications_present": current_medications_present,
        "current_medications": current_medications,
        "comorbidity_seizure": seizure_risk,
        "hepatic_risk": hepatic_risk,
        "child_pugh_bc": child_pugh_bc,
        "abiraterone_hard_block": abiraterone_hard_block,
        "abiraterone_hepatic_gate": abiraterone_hepatic_gate,
        "abiraterone_caution": abiraterone_caution,
        "impact_candidate": impact_candidate,
        "impact_blocked_by_immunosuppression": impact_blocked_by_immunosuppression,
        "contact02_candidate": contact02_candidate,
        "contact02_blocked_by_autoimmune": contact02_blocked_by_autoimmune,
        "active_autoimmune_disease": _autoimmune_active,
        "active_immunosuppression": _immunosuppression_active,
        "not_chemotherapy_candidate": _not_chemo_cand,
        "extra_pelvic_nodal_present": _extra_pelvic_present,
        "visceral_disease_present": _has_visceral,
        "selection_safety_profile": {
            "ecog_score": ecog_score,
            "frailty_status": frailty_status,
            "child_pugh_score": child_pugh_score,
            "cardio_risk": cardio_risk,
            "ddi_review_status": ddi_review_status,
            "current_medications_present": current_medications_present,
            "seizure_risk": seizure_risk,
            "hepatic_risk": hepatic_risk,
            "advanced_pro_bundle": dict(payload.get("advanced_pro_bundle") or {}),
            "cognitive_screening_bundle": dict(payload.get("cognitive_screening_bundle") or {}),
            "variant_histology_bundle": dict(payload.get("variant_histology_bundle") or {}),
        },
        "ar_v7_positive": ar_v7_positive,
        "tp53_altered": tp53_altered,
        "rb1_loss": rb1_loss,
        "lineage_plasticity_risk": lineage_plasticity_risk,
        "pten_loss": pten_loss,
        "cdk12_biallelic": cdk12_biallelic,
        "tmb_value": tmb_value,
        "tmb_zone": tmb_zone,
        "ctdna_detected": ctdna_detected,
        "ctdna_vaf": ctdna_vaf,
        "ctdna_rising": ctdna_rising,
        "nepc_suspected": nepc_suspected,
        "nepc_suspicion_score": nepc_suspicion_score,
        "nse_elevated": nse_elevated,
        "ldh_elevated": ldh_elevated,
        "psa_discordant_low": psa_discordant_low,
        "recommendation": "Prioritize biomarker-driven and sequence-aware options before recycling exhausted classes, while verifying taxane eligibility structurally when docetaxel still competes.",
    }
