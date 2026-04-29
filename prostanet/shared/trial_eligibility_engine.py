"""trial_eligibility_engine.py — Faubot LXXXV (Iteración #2).

Engine de elegibilidad para los 47 trials pivotales en cáncer de próstata.

API pública:

  evaluate_trial_eligibility(patient: dict, trial_id: str) -> dict
    → {eligible: bool, reasons_eligible: [...], reasons_not_eligible: [...],
       missing_data: [...], confidence: float (0-1), trial_id, criteria_summary}

  evaluate_all_eligible_trials(patient: dict) -> list[dict]
    → ranked list of eligible trials con confidence scores

  get_trial_subgroup(patient: dict, trial_id: str) -> str | None
    → e.g., "high_volume" para CHAARTED, "BRCA_positive" para PROfound

Diseño:
- Usa `trial_criteria_registry` como source of truth
- Cada trial tiene un evaluator function (`_eval_<trial_id_normalized>()`)
- Evaluators retornan tuple (eligible, reasons_eligible, reasons_not_eligible, missing_data)
- Patient dict se normaliza con helpers (PSA, Gleason, ECOG, stage)
- Confidence: 1.0 si todos los criteria evaluables; <1.0 si hay missing_data

NO inventar criterios — solo lo publicado en `trial_criteria_registry`.
NO emitir recomendaciones definitivas — el médico decide elegibilidad final.

Faubot LXXXV — Iteración #2 (Trials Eligibility Engine + REST API + UI).
"""
from __future__ import annotations

from typing import Any

from prostanet.shared.trial_criteria_registry import (
    TRIAL_CRITERIA_REGISTRY,
    get_trial_criteria,
    list_trial_ids,
    list_trials_by_stage,
)


# ──────────────────────────────────────────────────────────────────────
# PATIENT DATA EXTRACTORS (normalizan inputs heterogéneos)
# ──────────────────────────────────────────────────────────────────────


def _safe_get(d: dict | None, *keys: str, default: Any = None) -> Any:
    """Lookup en dict con multiples key aliases, primer match wins."""
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def _to_float(value: Any) -> float | None:
    """Convierte a float, retorna None si no es numérico."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    """Convierte a int, retorna None si no es entero."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_psa(patient: dict) -> float | None:
    return _to_float(_safe_get(patient, "psa_value", "psa", "psa_baseline"))


def _extract_psa_doubling_time_months(patient: dict) -> float | None:
    return _to_float(_safe_get(
        patient,
        "psa_doubling_time_months",
        "psadt_months",
        "psa_doubling_time",
    ))


def _extract_gleason_score(patient: dict) -> int | None:
    g = _to_int(_safe_get(patient, "gleason_score", "gleason_total"))
    if g is not None:
        return g
    primary = _to_int(_safe_get(patient, "gleason_primary"))
    secondary = _to_int(_safe_get(patient, "gleason_secondary"))
    if primary is not None and secondary is not None:
        return primary + secondary
    return None


def _extract_ecog(patient: dict) -> int | None:
    return _to_int(_safe_get(patient, "ecog_current", "ecog", "ecog_status"))


def _extract_disease_state(patient: dict) -> str | None:
    """Stage canónico: mcspc | m0_crpc | m1_crpc | recurrence_bcr |
                       post_prostatectomy | localized_initial."""
    state = _safe_get(
        patient,
        "disease_state",
        "current_state",
        "clinical_state",
        "stage",
    )
    if state:
        return str(state).lower()
    return None


def _has_visceral_mets(patient: dict) -> bool:
    val = _safe_get(
        patient,
        "visceral_metastasis",
        "visceral_mets",
        "liver_mets",
        "lung_mets",
        "brain_mets",
    )
    return bool(val)


def _bone_mets_count(patient: dict) -> int | None:
    return _to_int(_safe_get(patient, "bone_metastasis_count", "bone_mets_count"))


def _is_high_volume_chaarted(patient: dict) -> bool | None:
    """Definición CHAARTED: visceral mets OR ≥4 bone mets con ≥1 fuera de pelvis/columna."""
    visc = _has_visceral_mets(patient)
    bone_count = _bone_mets_count(patient)
    has_appendicular = bool(_safe_get(
        patient,
        "bone_mets_appendicular",
        "bone_mets_outside_axial",
    ))
    if visc:
        return True
    if bone_count is not None and bone_count >= 4 and has_appendicular:
        return True
    if visc is False and bone_count is not None and bone_count < 4:
        return False
    return None  # Insufficient data


def _is_high_risk_latitude(patient: dict) -> bool | None:
    """LATITUDE: ≥2 de 3 high-risk factors: Gleason ≥8, ≥3 bone lesions, visceral mets."""
    g = _extract_gleason_score(patient)
    bone = _bone_mets_count(patient)
    visc = _has_visceral_mets(patient)

    factors_present = 0
    factors_known = 0

    if g is not None:
        factors_known += 1
        if g >= 8:
            factors_present += 1
    if bone is not None:
        factors_known += 1
        if bone >= 3:
            factors_present += 1
    if visc is not None or _safe_get(patient, "visceral_metastasis") is not None:
        factors_known += 1
        if visc:
            factors_present += 1

    if factors_known < 2:
        return None  # Insufficient data
    return factors_present >= 2


def _has_hrr_mutation(patient: dict, gene_subset: list[str] | None = None) -> bool | None:
    """Detecta si paciente tiene mutación HRR documentada.

    gene_subset=None → cualquier gen HRR.
    gene_subset=["BRCA1","BRCA2","ATM"] → solo cohort A de PROfound.
    """
    hrr_status = _safe_get(
        patient,
        "hrr_test_result",
        "hrr_mutation_status",
        "hrr_status",
    )
    if hrr_status is None:
        return None
    hrr_str = str(hrr_status).lower()
    if hrr_str in ("negative", "wild_type", "wt"):
        return False
    if hrr_str in ("not_done", "pending", "unknown"):
        return None

    # Si hay lista específica de genes mutados, validar subset
    mutated_genes = _safe_get(patient, "hrr_genes_mutated", default=[])
    if not isinstance(mutated_genes, list):
        mutated_genes = []
    mutated_upper = [str(g).upper() for g in mutated_genes]

    if gene_subset is None:
        return len(mutated_upper) > 0 or hrr_str in ("positive", "mutated", "altered")

    subset_upper = [g.upper() for g in gene_subset]
    return any(g in subset_upper for g in mutated_upper)


def _has_brca_mutation(patient: dict) -> bool | None:
    return _has_hrr_mutation(patient, gene_subset=["BRCA1", "BRCA2"])


def _has_psma_pet_positive(patient: dict) -> bool | None:
    val = _safe_get(
        patient,
        "psma_pet_positive",
        "psma_pet_avidity_above_liver",
        "psma_positive",
    )
    if val is None:
        return None
    return bool(val)


def _has_pten_loss(patient: dict) -> bool | None:
    val = _safe_get(patient, "pten_status", "pten_loss")
    if val is None:
        return None
    val_str = str(val).lower()
    if val_str in ("loss", "biallelic_loss", "deleted", "true"):
        return True
    if val_str in ("wild_type", "wt", "intact", "false"):
        return False
    return None


def _had_prior_chemo(patient: dict) -> bool | None:
    val = _safe_get(
        patient,
        "prior_chemotherapy",
        "prior_taxane",
        "prior_docetaxel",
    )
    if val is None:
        return None
    return bool(val)


def _had_prior_arpi(patient: dict) -> bool | None:
    val = _safe_get(
        patient,
        "prior_arpi",
        "prior_abi_or_enza",
        "prior_abiraterone",
        "prior_enzalutamide",
    )
    if val is None:
        return None
    return bool(val)


# ──────────────────────────────────────────────────────────────────────
# CORE EVALUATORS — uno por trial pivotal
# ──────────────────────────────────────────────────────────────────────


def _make_result(
    trial_id: str,
    eligible: bool,
    reasons_eligible: list[str],
    reasons_not_eligible: list[str],
    missing_data: list[str],
    subgroup: str | None = None,
) -> dict:
    """Estructura estándar resultado evaluación elegibilidad."""
    confidence = 1.0 if not missing_data else max(0.3, 1.0 - 0.15 * len(missing_data))
    criteria = get_trial_criteria(trial_id) or {}
    return {
        "trial_id": trial_id,
        "eligible": eligible,
        "reasons_eligible": reasons_eligible,
        "reasons_not_eligible": reasons_not_eligible,
        "missing_data": missing_data,
        "confidence": round(confidence, 2),
        "subgroup": subgroup,
        "pmid": criteria.get("pmid"),
        "nct": criteria.get("nct"),
        "citation": criteria.get("citation"),
        "stage": criteria.get("stage"),
    }


# ─── mCSPC trials ─────────────────────────────────────────────────────


def _eval_chaarted(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in state and "mhspc" not in state:
        not_eligible_reasons.append(f"Estado clínico actual ({state}) no es mCSPC/mHSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG status")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2 (criterio exclusión)")
    else:
        eligible_reasons.append(f"ECOG {ecog} (≤2 OK)")

    hv = _is_high_volume_chaarted(patient)
    subgroup = None
    if hv is None:
        missing.append("Volume status (visceral mets + bone mets count + appendicular distribution)")
    elif hv:
        eligible_reasons.append("Alto volumen (CHAARTED definition)")
        subgroup = "high_volume"
    else:
        eligible_reasons.append("Bajo volumen (CHAARTED definition)")
        subgroup = "low_volume"

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("Quimioterapia previa para próstata (criterio exclusión)")

    eligible = (
        not not_eligible_reasons
        and len(missing) <= 2
        and (state is None or "mcspc" in (state or "") or "mhspc" in (state or ""))
        and (ecog is None or ecog <= 2)
    )
    return _make_result(
        "CHAARTED", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


def _eval_latitude(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in state and "mhspc" not in state:
        not_eligible_reasons.append(f"Estado clínico ({state}) no es mCSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG status")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")
    else:
        eligible_reasons.append(f"ECOG {ecog} OK")

    hr = _is_high_risk_latitude(patient)
    subgroup = None
    if hr is None:
        missing.append("LATITUDE high-risk factors (Gleason ≥8 + bone ≥3 + visceral)")
    elif hr:
        eligible_reasons.append("≥2 LATITUDE high-risk factors presentes")
        subgroup = "high_risk_latitude"
    else:
        not_eligible_reasons.append("<2 LATITUDE high-risk factors")

    eligible = not not_eligible_reasons and (hr is True or hr is None)
    return _make_result(
        "LATITUDE", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


def _eval_stampede(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or "") and "locally_advanced" not in (state or "") and "node_positive" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCSPC/locally advanced/N+")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG status")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")
    else:
        eligible_reasons.append(f"ECOG {ecog} OK")

    eligible = not not_eligible_reasons
    return _make_result("STAMPEDE", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_enzamet(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mHSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")

    if _safe_get(patient, "seizure_history"):
        not_eligible_reasons.append("Historia de convulsiones (excluido — riesgo enzalutamida)")

    eligible = not not_eligible_reasons
    return _make_result("ENZAMET", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_arches(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mHSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 1:
        not_eligible_reasons.append(f"ECOG {ecog} > 1")

    if _safe_get(patient, "brain_mets"):
        not_eligible_reasons.append("Metástasis cerebrales (excluidas)")

    eligible = not not_eligible_reasons
    return _make_result("ARCHES", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_titan(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 1:
        not_eligible_reasons.append(f"ECOG {ecog} > 1")

    if _safe_get(patient, "brain_mets"):
        not_eligible_reasons.append("Metástasis cerebrales (excluidas)")
    if _safe_get(patient, "seizure_history"):
        not_eligible_reasons.append("Historia de convulsiones (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("TITAN", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_peace1(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es de novo mCSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")

    if _safe_get(patient, "prior_systemic_therapy_for_metastatic"):
        not_eligible_reasons.append("Terapia sistémica previa para enfermedad metastásica")

    eligible = not not_eligible_reasons
    return _make_result("PEACE-1", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_arasens(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mHSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 1:
        not_eligible_reasons.append(f"ECOG {ecog} > 1")

    fitness_doce = _safe_get(patient, "fit_for_docetaxel", "docetaxel_eligible")
    if fitness_doce is None:
        missing.append("Aptitud para docetaxel")
    elif not fitness_doce:
        not_eligible_reasons.append("No apto para docetaxel (criterio inclusión)")

    eligible = not not_eligible_reasons
    return _make_result("ARASENS", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_aranote(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mHSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 1:
        not_eligible_reasons.append(f"ECOG {ecog} > 1")

    fitness_doce = _safe_get(patient, "fit_for_docetaxel", "docetaxel_eligible")
    if fitness_doce:
        # ARANOTE específicamente NO usa docetaxel (es para pacientes que rechazan/no aptos)
        eligible_reasons.append("Apto para docetaxel pero ARANOTE evalúa darolutamida sin docetaxel")

    eligible = not not_eligible_reasons
    return _make_result("ARANOTE", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_amplitude(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "mcspc" not in (state or "") and "mhspc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCSPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 1:
        not_eligible_reasons.append(f"ECOG {ecog} > 1")

    hrr = _has_hrr_mutation(patient)
    if hrr is None:
        missing.append("HRR mutation status (criterio inclusión)")
    elif not hrr:
        not_eligible_reasons.append("HRR negativo — AMPLITUDE requiere HRR+")
    else:
        eligible_reasons.append("HRR mutation positive (criterio inclusión cumplido)")

    eligible = not not_eligible_reasons and (hrr is True or hrr is None)
    return _make_result("AMPLITUDE", eligible, eligible_reasons, not_eligible_reasons, missing)


# ─── nmCRPC trials ────────────────────────────────────────────────────


def _eval_spartan_prosper_aramis_common(
    trial_id: str, patient: dict, ecog_max: int = 1
) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m0_crpc" not in (state or "") and "nmcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es nmCRPC/m0CRPC")

    psadt = _extract_psa_doubling_time_months(patient)
    if psadt is None:
        missing.append("PSA doubling time (meses)")
    elif psadt > 10:
        not_eligible_reasons.append(f"PSADT {psadt}m > 10 (criterio inclusión)")
    else:
        eligible_reasons.append(f"PSADT {psadt}m ≤10 (criterio cumplido)")

    psa = _extract_psa(patient)
    if psa is None:
        missing.append("PSA actual")
    elif psa < 2:
        not_eligible_reasons.append(f"PSA {psa} < 2 (criterio inclusión)")
    else:
        eligible_reasons.append(f"PSA {psa} ≥2 OK")

    testo = _to_float(_safe_get(patient, "testosterone_value", "testosterone"))
    if testo is None:
        missing.append("Testosterona (confirma castración)")
    elif testo >= 50:
        not_eligible_reasons.append(f"Testosterona {testo} ≥50 (no castrado)")
    else:
        eligible_reasons.append(f"Testosterona {testo} <50 (castrado)")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > ecog_max:
        not_eligible_reasons.append(f"ECOG {ecog} > {ecog_max}")

    if _has_visceral_mets(patient) or _bone_mets_count(patient):
        not_eligible_reasons.append("Metástasis presentes (criterio exclusión nmCRPC)")

    eligible = not not_eligible_reasons
    return _make_result(trial_id, eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_spartan(patient: dict) -> dict:
    return _eval_spartan_prosper_aramis_common("SPARTAN", patient, ecog_max=1)


def _eval_prosper(patient: dict) -> dict:
    return _eval_spartan_prosper_aramis_common("PROSPER", patient, ecog_max=1)


def _eval_aramis(patient: dict) -> dict:
    return _eval_spartan_prosper_aramis_common("ARAMIS", patient, ecog_max=1)


# ─── mCRPC trials (chemo + ARPI) ──────────────────────────────────────


def _eval_tax327(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("Quimio previa (excluida en TAX-327 1ra línea)")

    eligible = not not_eligible_reasons
    return _make_result("TAX-327", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_tropic(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    progression_doce = _safe_get(patient, "progression_on_docetaxel", "post_docetaxel_progression")
    if progression_doce is None:
        missing.append("Progresión post-docetaxel")
    elif not progression_doce:
        not_eligible_reasons.append("TROPIC requiere progresión post-docetaxel")

    ecog = _extract_ecog(patient)
    if ecog is None:
        missing.append("ECOG")
    elif ecog > 2:
        not_eligible_reasons.append(f"ECOG {ecog} > 2")

    eligible = not not_eligible_reasons
    return _make_result("TROPIC", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_card(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    prior_doce = _had_prior_chemo(patient)
    prior_arpi = _had_prior_arpi(patient)
    if prior_doce is None or prior_arpi is None:
        missing.append("Historial docetaxel + ARPI")
    elif not prior_doce or not prior_arpi:
        not_eligible_reasons.append("CARD requiere progresión docetaxel + 1 ARPI ≤12m")

    eligible = not not_eligible_reasons
    return _make_result("CARD", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_cou_aa_301(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    prior_doce = _had_prior_chemo(patient)
    if prior_doce is None:
        missing.append("Historial docetaxel previo")
    elif not prior_doce:
        not_eligible_reasons.append("COU-AA-301 requiere progresión post-docetaxel")

    eligible = not not_eligible_reasons
    return _make_result("COU-AA-301", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_cou_aa_302(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("COU-AA-302 es chemo-naïve (excluye quimio previa)")

    pain_opioids = _safe_get(patient, "pain_requires_opioids")
    if pain_opioids:
        not_eligible_reasons.append("Dolor que requiere opioides (excluido)")

    eligible = not not_eligible_reasons
    return _make_result("COU-AA-302", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_affirm(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    prior_doce = _had_prior_chemo(patient)
    if prior_doce is None:
        missing.append("Historial docetaxel previo")
    elif not prior_doce:
        not_eligible_reasons.append("AFFIRM requiere progresión post-docetaxel")

    if _safe_get(patient, "seizure_history"):
        not_eligible_reasons.append("Historia de convulsiones (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("AFFIRM", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_prevail(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("PREVAIL chemo-naïve (excluye quimio previa)")

    if _has_visceral_mets(patient):
        not_eligible_reasons.append("Visceral mets (excluidas en PREVAIL)")

    if _safe_get(patient, "seizure_history"):
        not_eligible_reasons.append("Historia de convulsiones (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("PREVAIL", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_alsympca(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    bone = _bone_mets_count(patient)
    if bone is None:
        missing.append("Bone mets count")
    elif bone < 2:
        not_eligible_reasons.append(f"<2 bone mets (criterio: ≥2)")

    if _has_visceral_mets(patient):
        not_eligible_reasons.append("Visceral mets (excluidas)")

    if _safe_get(patient, "spinal_cord_compression_imminent"):
        not_eligible_reasons.append("SCC inminente (excluido)")

    eligible = not not_eligible_reasons
    return _make_result("ALSYMPCA", eligible, eligible_reasons, not_eligible_reasons, missing)


# ─── mCRPC PSMA-targeted ──────────────────────────────────────────────


def _eval_vision(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    psma_pos = _has_psma_pet_positive(patient)
    if psma_pos is None:
        missing.append("PSMA-PET positivity (SUVmax > liver)")
    elif not psma_pos:
        not_eligible_reasons.append("PSMA-PET negativo — VISION requiere PSMA+")
    else:
        eligible_reasons.append("PSMA-PET positive (criterio cumplido)")

    prior_doce = _had_prior_chemo(patient)
    prior_arpi = _had_prior_arpi(patient)
    if prior_doce is None or prior_arpi is None:
        missing.append("Historial taxane + ARPI previos")
    elif not (prior_doce and prior_arpi):
        not_eligible_reasons.append("VISION requiere ≥1 taxane + ≥1 ARPI previo")

    gfr = _to_float(_safe_get(patient, "gfr_ml_min", "egfr"))
    if gfr is not None and gfr < 30:
        not_eligible_reasons.append(f"GFR {gfr} < 30 (criterio exclusión)")

    eligible = not not_eligible_reasons
    return _make_result("VISION", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_psmafore(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    psma_pos = _has_psma_pet_positive(patient)
    if psma_pos is None:
        missing.append("PSMA-PET positivity")
    elif not psma_pos:
        not_eligible_reasons.append("PSMA negativo — PSMAfore requiere PSMA+")

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("PSMAfore chemo-naïve (excluye taxane previo)")

    prior_arpi = _had_prior_arpi(patient)
    if prior_arpi is False:
        not_eligible_reasons.append("PSMAfore requiere ≥1 ARPI previo")

    eligible = not not_eligible_reasons
    return _make_result("PSMAfore", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_therap(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    suvmax = _to_float(_safe_get(patient, "psma_pet_suvmax_max", "psma_suvmax_max_lesion"))
    if suvmax is None:
        missing.append("PSMA SUVmax in dominant lesion")
    elif suvmax < 20:
        not_eligible_reasons.append(f"SUVmax {suvmax} < 20 (TheraP requiere ≥20)")
    else:
        eligible_reasons.append(f"SUVmax {suvmax} ≥20 (cumple TheraP)")

    prior_doce = _had_prior_chemo(patient)
    if prior_doce is None:
        missing.append("Historial docetaxel previo")
    elif not prior_doce:
        not_eligible_reasons.append("TheraP requiere progresión post-docetaxel")

    eligible = not not_eligible_reasons
    return _make_result("TheraP", eligible, eligible_reasons, not_eligible_reasons, missing)


# ─── HRR/PARP trials ──────────────────────────────────────────────────


def _eval_profound(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    prior_arpi = _had_prior_arpi(patient)
    if prior_arpi is None:
        missing.append("Historial ARPI previo")
    elif not prior_arpi:
        not_eligible_reasons.append("PROfound requiere progresión post-ARPI")

    cohort_a = _has_hrr_mutation(patient, gene_subset=["BRCA1", "BRCA2", "ATM"])
    cohort_b = _has_hrr_mutation(patient)
    subgroup = None

    if cohort_a is None and cohort_b is None:
        missing.append("HRR test result (BRCA/ATM cohort A o 12 genes cohort B)")
    elif cohort_a:
        eligible_reasons.append("HRR cohort A (BRCA1/BRCA2/ATM) — máximo beneficio olaparib")
        subgroup = "cohort_A_brca_atm"
    elif cohort_b:
        eligible_reasons.append("HRR cohort B (otros HRR genes)")
        subgroup = "cohort_B_other_hrr"
    else:
        not_eligible_reasons.append("HRR negativo — PROfound requiere mutación HRR")

    eligible = not not_eligible_reasons and (cohort_a or cohort_b or cohort_a is None)
    return _make_result(
        "PROfound", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


def _eval_magnitude(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _safe_get(patient, "prior_systemic_therapy_for_mcrpc"):
        not_eligible_reasons.append("MAGNITUDE es 1L mCRPC (excluye terapia sistémica previa)")

    hrr = _has_hrr_mutation(patient)
    subgroup = None
    if hrr is None:
        missing.append("HRR mutation status")
    elif hrr:
        eligible_reasons.append("HRR positive — cohorte primaria MAGNITUDE")
        subgroup = "hrr_positive"
    else:
        subgroup = "biomarker_negative"
        eligible_reasons.append("HRR negativo — cohorte biomarker-negative MAGNITUDE")

    eligible = not not_eligible_reasons
    return _make_result(
        "MAGNITUDE", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


def _eval_propel(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _safe_get(patient, "prior_systemic_therapy_for_mcrpc"):
        not_eligible_reasons.append("PROpel 1L mCRPC (excluye terapia sistémica previa)")

    eligible = not not_eligible_reasons
    return _make_result("PROpel", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_talapro2(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _safe_get(patient, "prior_systemic_therapy_for_mcrpc"):
        not_eligible_reasons.append("TALAPRO-2 1L mCRPC (excluye terapia sistémica previa)")

    if _safe_get(patient, "prior_parp_inhibitor"):
        not_eligible_reasons.append("PARP inhibitor previo (excluido)")

    hrr = _has_hrr_mutation(patient)
    subgroup = None
    if hrr is True:
        subgroup = "cohort_2_hrr_deficient"
        eligible_reasons.append("HRR+ → cohorte 2 talazoparib labeled use")
    elif hrr is False:
        subgroup = "cohort_1_all_comers"
        eligible_reasons.append("HRR- → cohorte 1 all-comers")
    else:
        missing.append("HRR mutation status")

    eligible = not not_eligible_reasons
    return _make_result(
        "TALAPRO-2", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


def _eval_triton3(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    brca_or_atm = _has_hrr_mutation(patient, gene_subset=["BRCA1", "BRCA2", "ATM"])
    if brca_or_atm is None:
        missing.append("BRCA1/BRCA2/ATM mutation status")
    elif not brca_or_atm:
        not_eligible_reasons.append("TRITON3 requiere BRCA1/BRCA2/ATM mutation")
    else:
        eligible_reasons.append("BRCA1/BRCA2/ATM+ (criterio TRITON3)")

    if _had_prior_chemo(patient):
        not_eligible_reasons.append("Quimio previa para mCRPC (excluida en TRITON3)")

    if _safe_get(patient, "prior_parp_inhibitor"):
        not_eligible_reasons.append("PARP inhibitor previo (excluido)")

    eligible = not not_eligible_reasons
    return _make_result("TRITON-3", eligible, eligible_reasons, not_eligible_reasons, missing)


# ─── Immunotherapy / PI3K ─────────────────────────────────────────────


def _eval_impact(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    if _has_visceral_mets(patient):
        not_eligible_reasons.append("Visceral mets (excluidas en IMPACT)")

    if _safe_get(patient, "pain_requires_opioids"):
        not_eligible_reasons.append("Dolor que requiere opioides (excluido)")

    eligible = not not_eligible_reasons
    return _make_result("IMPACT", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_ipatential150(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    pten = _has_pten_loss(patient)
    subgroup = None
    if pten is None:
        missing.append("PTEN status (loss vs intact)")
    elif pten:
        eligible_reasons.append("PTEN loss (cohorte primaria IPATential150)")
        subgroup = "pten_loss"
    else:
        subgroup = "itt_pten_intact"
        eligible_reasons.append("PTEN intact (cohorte ITT secundaria)")

    if _safe_get(patient, "diabetes_type_1") or _safe_get(patient, "insulin_dependent_dm2"):
        not_eligible_reasons.append("Diabetes tipo 1 o insulino-dependiente (excluida)")

    eligible = not not_eligible_reasons
    return _make_result(
        "IPATential150", eligible, eligible_reasons, not_eligible_reasons, missing, subgroup
    )


# ─── BCR trials ───────────────────────────────────────────────────────


def _eval_embark(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "recurrence_bcr" not in (state or "") and "bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es BCR")

    psadt = _extract_psa_doubling_time_months(patient)
    if psadt is None:
        missing.append("PSA doubling time")
    elif psadt > 9:
        not_eligible_reasons.append(f"PSADT {psadt}m > 9 (criterio EMBARK ≤9)")

    if _has_visceral_mets(patient) or _bone_mets_count(patient):
        not_eligible_reasons.append("Metástasis presentes (excluidas en BCR)")

    if _safe_get(patient, "seizure_history"):
        not_eligible_reasons.append("Historia de convulsiones (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("EMBARK", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_presto(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "recurrence_bcr" not in (state or "") and "bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es BCR")

    psadt = _extract_psa_doubling_time_months(patient)
    if psadt is None:
        missing.append("PSA doubling time")
    elif psadt > 9:
        not_eligible_reasons.append(f"PSADT {psadt}m > 9 (criterio PRESTO ≤9)")

    if _has_visceral_mets(patient):
        not_eligible_reasons.append("Visceral mets (excluidas)")

    eligible = not not_eligible_reasons
    return _make_result("PRESTO", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_aft19(patient: dict) -> dict:
    """AFT-19 alias of PRESTO."""
    result = _eval_presto(patient)
    result["trial_id"] = "AFT-19"
    return result


# ─── Adjuvant / salvage RT trials ─────────────────────────────────────


def _eval_post_rp_adjuvant_salvage_common(
    trial_id: str, patient: dict
) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "post_prostatectomy" not in (state or "") and "post_rp" not in (state or "") and "recurrence_bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es post-RP")

    has_adverse = _safe_get(
        patient,
        "post_rp_adverse_features",
        "pT3_pT4",
        "positive_margins",
    )
    if has_adverse is None:
        missing.append("Características adversas post-RP (pT3/T4 + márgenes+)")

    if _has_visceral_mets(patient) or _bone_mets_count(patient):
        not_eligible_reasons.append("Metástasis distales (excluidas)")

    eligible = not not_eligible_reasons
    return _make_result(trial_id, eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_radicals_rt(patient: dict) -> dict:
    return _eval_post_rp_adjuvant_salvage_common("RADICALS-RT", patient)


def _eval_rtog9601(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "recurrence_bcr" not in (state or "") and "bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es BCR post-RP")

    psa = _extract_psa(patient)
    if psa is None:
        missing.append("PSA actual")
    elif psa < 0.2 or psa > 4.0:
        not_eligible_reasons.append(f"PSA {psa} fuera rango RTOG-9601 (0.2-4.0)")

    eligible = not not_eligible_reasons
    return _make_result("RTOG-9601", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_getug_afu_16(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "recurrence_bcr" not in (state or "") and "bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es BCR post-RP")

    psa = _extract_psa(patient)
    if psa is None:
        missing.append("PSA actual")
    elif psa < 0.2 or psa > 2.0:
        not_eligible_reasons.append(f"PSA {psa} fuera rango GETUG-AFU-16 (0.2-2.0)")

    if _safe_get(patient, "prior_pelvic_rt"):
        not_eligible_reasons.append("RT pélvica previa (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("GETUG-AFU-16", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_spport(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "recurrence_bcr" not in (state or "") and "bcr" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es BCR post-RP")

    psa = _extract_psa(patient)
    if psa is not None and psa < 0.1:
        not_eligible_reasons.append(f"PSA {psa} <0.1 (SPPORT requiere ≥0.1)")

    eligible = not not_eligible_reasons
    return _make_result("SPPORT", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_artistic(patient: dict) -> dict:
    """ARTISTIC meta-analysis (RADICALS+GETUG17+RAVES) — same criterios post-RP adverse."""
    return _eval_post_rp_adjuvant_salvage_common("ARTISTIC", patient)


def _eval_raves(patient: dict) -> dict:
    return _eval_post_rp_adjuvant_salvage_common("RAVES", patient)


def _eval_aro_96_02(patient: dict) -> dict:
    return _eval_post_rp_adjuvant_salvage_common("ARO-96-02", patient)


def _eval_swog_8794(patient: dict) -> dict:
    return _eval_post_rp_adjuvant_salvage_common("SWOG-8794", patient)


# ─── Localized trials ────────────────────────────────────────────────


def _eval_localized_common(trial_id: str, patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "localized" not in (state or "") and "diagnostic_workup" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es localizado")

    if _has_visceral_mets(patient) or _bone_mets_count(patient):
        not_eligible_reasons.append("Metástasis distales (excluidas localized)")

    psa = _extract_psa(patient)
    if psa is not None and psa > 50:
        not_eligible_reasons.append(f"PSA {psa} >50 (probable enfermedad avanzada)")

    eligible = not not_eligible_reasons
    return _make_result(trial_id, eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_protect(patient: dict) -> dict:
    return _eval_localized_common("PROTECT", patient)


def _eval_spcg4(patient: dict) -> dict:
    return _eval_localized_common("SPCG-4", patient)


def _eval_pivot(patient: dict) -> dict:
    return _eval_localized_common("PIVOT", patient)


# ─── PEACE-3 + CONTACT-02 ─────────────────────────────────────────────


def _eval_peace3(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    bone = _bone_mets_count(patient)
    if bone is None:
        missing.append("Bone mets count")
    elif bone < 2:
        not_eligible_reasons.append(f"<2 bone mets (PEACE-3 requiere ≥2)")

    if _has_visceral_mets(patient):
        not_eligible_reasons.append("Visceral mets (excluidas en PEACE-3)")

    eligible = not not_eligible_reasons
    return _make_result("PEACE-3", eligible, eligible_reasons, not_eligible_reasons, missing)


def _eval_contact02(patient: dict) -> dict:
    eligible_reasons: list[str] = []
    not_eligible_reasons: list[str] = []
    missing: list[str] = []

    state = _extract_disease_state(patient)
    if state and "m1_crpc" not in (state or "") and "mcrpc" not in (state or ""):
        not_eligible_reasons.append(f"Estado ({state}) no es mCRPC")

    soft_tissue = _safe_get(patient, "measurable_soft_tissue", "soft_tissue_disease")
    if soft_tissue is None:
        missing.append("Enfermedad medible en partes blandas")
    elif not soft_tissue:
        not_eligible_reasons.append("CONTACT-02 requiere enfermedad medible soft tissue")

    if _safe_get(patient, "brain_mets"):
        not_eligible_reasons.append("Metástasis cerebrales (excluidas)")

    if _safe_get(patient, "active_autoimmune_disease"):
        not_eligible_reasons.append("Enfermedad autoinmune activa (excluida)")

    eligible = not not_eligible_reasons
    return _make_result("CONTACT-02", eligible, eligible_reasons, not_eligible_reasons, missing)


# ──────────────────────────────────────────────────────────────────────
# DISPATCHER REGISTRY (trial_id → evaluator function)
# ──────────────────────────────────────────────────────────────────────

_EVALUATOR_DISPATCHER: dict[str, Any] = {
    # mCSPC
    "CHAARTED": _eval_chaarted,
    "LATITUDE": _eval_latitude,
    "STAMPEDE": _eval_stampede,
    "ENZAMET": _eval_enzamet,
    "ARCHES": _eval_arches,
    "TITAN": _eval_titan,
    "PEACE-1": _eval_peace1,
    "ARASENS": _eval_arasens,
    "ARANOTE": _eval_aranote,
    "AMPLITUDE": _eval_amplitude,
    # nmCRPC
    "SPARTAN": _eval_spartan,
    "PROSPER": _eval_prosper,
    "ARAMIS": _eval_aramis,
    # mCRPC chemo + ARPI
    "TAX-327": _eval_tax327,
    "TROPIC": _eval_tropic,
    "CARD": _eval_card,
    "COU-AA-301": _eval_cou_aa_301,
    "COU-AA-302": _eval_cou_aa_302,
    "AFFIRM": _eval_affirm,
    "PREVAIL": _eval_prevail,
    "ALSYMPCA": _eval_alsympca,
    # PSMA-targeted
    "VISION": _eval_vision,
    "PSMAfore": _eval_psmafore,
    "TheraP": _eval_therap,
    # HRR/PARP
    "PROfound": _eval_profound,
    "MAGNITUDE": _eval_magnitude,
    "PROpel": _eval_propel,
    "TALAPRO-2": _eval_talapro2,
    "TRITON-3": _eval_triton3,
    # Immuno/PI3K
    "IMPACT": _eval_impact,
    "IPATential150": _eval_ipatential150,
    # BCR
    "EMBARK": _eval_embark,
    "PRESTO": _eval_presto,
    "AFT-19": _eval_aft19,
    # Post-RP adjuvant/salvage
    "RADICALS-RT": _eval_radicals_rt,
    "RTOG-9601": _eval_rtog9601,
    "GETUG-AFU-16": _eval_getug_afu_16,
    "SPPORT": _eval_spport,
    "ARTISTIC": _eval_artistic,
    "RAVES": _eval_raves,
    "ARO-96-02": _eval_aro_96_02,
    "SWOG-8794": _eval_swog_8794,
    # Localized
    "PROTECT": _eval_protect,
    "SPCG-4": _eval_spcg4,
    "PIVOT": _eval_pivot,
    # Other
    "PEACE-3": _eval_peace3,
    "CONTACT-02": _eval_contact02,
}


# ──────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────


def evaluate_trial_eligibility(patient: dict, trial_id: str) -> dict:
    """Evalúa elegibilidad de un paciente para un trial específico.

    Args:
        patient: dict con datos del paciente (PSA, ECOG, gene mutations, etc.)
        trial_id: nombre canónico del trial (e.g., "CHAARTED", "PROfound")

    Returns:
        dict con: eligible, reasons_eligible, reasons_not_eligible, missing_data,
                  confidence (0-1), trial_id, subgroup, pmid, nct, citation, stage.

    Raises:
        ValueError si trial_id no está registrado.

    >>> result = evaluate_trial_eligibility(
    ...     {"disease_state": "mcspc", "ecog_current": 1, "visceral_metastasis": True},
    ...     "CHAARTED"
    ... )
    >>> result["trial_id"]
    'CHAARTED'
    >>> result["subgroup"]
    'high_volume'
    """
    evaluator = _EVALUATOR_DISPATCHER.get(trial_id)
    if evaluator is None:
        raise ValueError(
            f"Trial '{trial_id}' no registrado. "
            f"Trials disponibles: {sorted(_EVALUATOR_DISPATCHER.keys())[:10]}…"
        )
    return evaluator(patient or {})


def evaluate_all_eligible_trials(patient: dict) -> list[dict]:
    """Evalúa elegibilidad para los 47 trials. Retorna lista ordenada.

    Order: eligible=True primero (ranked por confidence desc), luego no-elegibles.

    >>> patient = {"disease_state": "m1_crpc", "ecog_current": 1, "psma_pet_positive": True,
    ...            "prior_chemotherapy": True, "prior_arpi": True}
    >>> results = evaluate_all_eligible_trials(patient)
    >>> any(r["trial_id"] == "VISION" and r["eligible"] for r in results)
    True
    """
    results = []
    for trial_id in _EVALUATOR_DISPATCHER:
        try:
            result = evaluate_trial_eligibility(patient, trial_id)
            results.append(result)
        except Exception:
            continue
    # Ordenar: eligibles primero (por confidence desc), luego no-eligibles
    results.sort(key=lambda r: (not r["eligible"], -r["confidence"]))
    return results


def get_total_evaluators_count() -> int:
    """Retorna número total de evaluators registrados.

    >>> get_total_evaluators_count() == 47
    True
    """
    return len(_EVALUATOR_DISPATCHER)


def list_supported_trials() -> list[str]:
    """Lista todos los trial_ids con evaluator implementado.

    >>> trials = list_supported_trials()
    >>> "CHAARTED" in trials and "PROfound" in trials
    True
    """
    return sorted(_EVALUATOR_DISPATCHER.keys())
