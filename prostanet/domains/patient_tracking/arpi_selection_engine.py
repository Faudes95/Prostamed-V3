from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.arpi_benefit_matrix import benefit_profile_for_state
from prostanet.domains.patient_tracking.therapy_catalog import normalize_regimen_code, regimen_label
from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload
from prostanet.shared.renal_function import renal_dosing_flag


# EPIC 2 FIX-ARPI-RENAL: mapeo régimen canónico → fármacos con rango renal.
# Permite consumir renal_dosing_flag() sin hard-coding.
_ARPI_REGIMEN_TO_RENAL_AGENTS: dict[str, tuple[str, ...]] = {
    "ADT_ABIRATERONE": ("abiraterone",),
    "ADT_ENZALUTAMIDE": (),  # Xtandi no requiere ajuste renal (label §2.3).
    "ADT_APALUTAMIDE": (),  # Erleada tampoco.
    "ADT_DAROLUTAMIDE": (),  # Nubeqa tampoco.
    "ADT_DOCETAXEL_ABIRATERONE": ("abiraterone",),
    "ADT_DOCETAXEL_DAROLUTAMIDE": (),
    "CABAZITAXEL": ("cabazitaxel",),
    "OLAPARIB": ("olaparib",),
    "TALAZOPARIB": ("talazoparib",),
    "RADIUM_223": ("radium_223",),
    "LU_177_PSMA": ("psma_iodine_contrast",),
}


ARPI_ELIGIBLE_STATES = {
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "m0_crpc",
    "m1_crpc",
    "recurrence_bcr",
}

ARPI_MOLECULE_DISCRIMINATION_BUNDLE = [
    "ecog_score",
    "frailty_status",
    "child_pugh_score",
    "active_liver_disease",
    "cirrhosis_or_portal_hypertension",
    "active_hepatitis_b_or_c",
    "prior_drug_induced_liver_injury",
    "comorbidity_seizure",
    "comorbidity_cardio",
    "cv_risk_documented",
    "ddi_review_status",
    "current_medications",
    "dermatitis_history",
    "cognitive_risk",
    "fall_risk",
    "stroke_history",
    "edema_risk",
    "steroid_intolerance",
    "diabetes_uncontrolled",
    # EPIC 9 Group A (GAP-1/2/3): discriminadores geriátricos + cardiológicos
    # para penalty/hard-block en mhspc_regimen_selector y arpi_selection_engine.
    "patient_age",
    "qtc_baseline_ms",
    "nyha_class",
    "lvef_percent",
]

ARPI_MONITORING_BUNDLE = [
    "baseline_bp",
    "baseline_weight",
    "fatigue_score",
    "mini_cog_score",
    "mini_cog_date",
    "cognitive_screen_source",
    "fall_history_recent",
    "potassium",
    "glucose_or_hba1c",
    # EPIC 2 FIX-ARPI-RENAL / FIX-ARPI-HALABI: marcadores de seguridad renal y
    # de pronóstico Halabi consumidos por abiraterona, cabazitaxel, olaparib,
    # talazoparib, Ra-223 y el nomograma pronóstico IPS.
    "egfr_ml_min",
    "creatinine_mg_dl",
    "albumin_g_dl",
    "ldh_u_l",
    "hemoglobin_g_dl",
]

ARPI_ONCOLOGIC_CONTEXT_BY_STATE = {
    "m0_crpc": [
        "psadt_months",
        "imaging_negative",
        "conventional_imaging_modality",
        "conventional_imaging_date",
        "castrate_testosterone_confirmed",
    ],
    "m1_crpc": [
        "metastasis_site",
        "prior_therapy",
        "mcrpc_line_context",
        "castrate_testosterone_confirmed",
    ],
    "mcspc_high_volume_sync": [
        "metastatic_components_capture",
        "metastasis_count",
        "bone_pain",
    ],
    "mcspc_high_volume_metachronous": [
        "metastatic_components_capture",
        "metastasis_count",
        "prior_radiation",
    ],
    "mcspc_low_volume_sync_oligo": [
        "metastatic_components_capture",
        "metastasis_count",
        "rt_primary_received",
    ],
    "mcspc_oligo_metachronous": [
        "metastatic_components_capture",
        "metastasis_count",
        "prior_radiation",
        "mdt_context",
    ],
    "recurrence_bcr": [
        "psadt_months",
        "salvage_local_feasible",
        "psma_pet_done",
    ],
}

ARPI_FIELD_ALIASES = {
    "baseline_bp": ["systolic_bp"],
    "baseline_weight": ["weight_kg"],
    "fall_history_recent": ["falls_recent"],
    "liver_panel_date": ["lft_date"],
    "ddi_review_status": ["drug_interaction_reviewed"],
    "glucose_or_hba1c": ["glucose", "hba1c"],
    "metastatic_components_capture": [
        "metastatic_components_capture",
        "metastatic_disease_known",
        "bone_site_entries",
        "visceral_site_entries",
        "nonregional_nodal_site_entries",
    ],
    "bone_pain": ["pain_burden", "pain_symptoms"],
    "prior_radiation": ["rt_primary_received"],
    # EPIC 9 Group A: canonicalizar inputs geriátricos/cardiológicos.
    "patient_age": ["age"],
    "qtc_baseline_ms": ["qtc_ms"],
    # Auditoría Pacientes Insignia 2026-04-21 (§A.2) — IMPACT/CONTACT-02:
    # el schema m1_crpc usa `pain_symptoms` pero los perfiles insignia y el
    # trial matching engine emiten `pain_status`; añadimos fallback bidireccional.
    "pain_symptoms": ["pain_status"],
    "opioid_use_for_pain": ["opioid_use"],
    "extra_pelvic_nodal_metastasis": [
        "nodal_extrapelvic",
        "extrapelvic_nodes",
    ],
    "visceral_metastasis_present": ["visceral_mets"],
    # Auditoría Pacientes Insignia 2026-04-21 (§B.1) — gate hepático abiraterona:
    # perfiles insignia emiten señal boolean `child_pugh_b_or_c`; el canónico
    # es `child_pugh_score` (A/B/C) declarado en advanced_hepatic_fields.
    "child_pugh_score": ["child_pugh_b_or_c", "child_pugh_class"],
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — docetaxel_fit canónico:
    # reemplaza `taxane_fitness`, `fit_for_docetaxel`, `chemotherapy_fitness`
    # legacy. Selector de regimen mHSPC lo usa como gate de elegibilidad a
    # doblete/triplete docetaxel (CHAARTED/STAMPEDE/ARASENS/PEACE-1).
    "docetaxel_fit": [
        "taxane_fitness",
        "fit_for_docetaxel",
        "chemotherapy_fitness",
    ],
    # Brecha M-staging gate + RP-cT4 — 2026-04-22 (§A.3):
    # Aliases canónicos para imagenología de estadificación. Permite que
    # perfiles legacy / clasificadores externos usen nombres cortos sin
    # romper el contrato del FieldSpec ES-médico
    # (`["Desconocido","No","Sí"]`) introducido por `advanced_staging_imaging_fields`.
    "clinical_mstage": ["m_stage"],
    "imaging_negative_metastases": ["staging_complete"],
    "psma_pet_done": ["psma_pet"],
    "bone_scan_done": ["ggo_done", "gammagrafia_done"],
    "ct_abdomen_pelvis_done": ["tac_done"],
    # Faubot 2026-04-24 (IV) — Gates 11-12 Ra-223 × emergencias.
    # Aliases canónicos para que payloads legacy / clasificadores externos
    # disparen correctamente los nuevos detectores
    # `radium223_in_cord_compression` y `radium223_in_hypocalcemia`.
    "spinal_cord_compression": [
        "cord_compression",
        "epidural_compression",
        "compresion_medular",
    ],
    "lower_limb_weakness": ["debilidad_mmii", "weakness_lower_limbs"],
    "cord_compression_symptoms": ["sintomas_compresion_medular"],
    "cord_compression_stabilized": [
        "cord_compression_resolved",
        "compresion_medular_estabilizada",
    ],
    "hypocalcemia": ["hipocalcemia", "low_calcium", "calcio_bajo"],
    "hypocalcemia_corrected": [
        "hipocalcemia_corregida",
        "calcium_corrected",
    ],
    "corrected_calcium": ["calcio_corregido", "albumin_corrected_calcium"],
    "calcium_level": ["calcio_serico", "serum_calcium"],
    "ionized_calcium": ["calcio_ionico"],
    # Faubot 2026-04-24 (V) — Gates 13-14 Lu-177-PSMA × emergencias.
    # Aliases canónicos para que payloads legacy disparen correctamente
    # `lutetium177_in_cord_compression` y `lutetium177_in_severe_cytopenias`.
    # `spinal_cord_compression` ya está canonicalizado por gate 11; los
    # campos hematológicos requieren múltiples sinónimos por la diversidad
    # de schemas (anc/anc_baseline, hemoglobin/hemoglobin_g_dl/hb,
    # platelets/platelets_baseline).
    "anc": ["anc_baseline", "absolute_neutrophil_count", "neutrofilos_absolutos"],
    "platelets": ["platelets_baseline", "platelet_count", "plaquetas"],
    "hemoglobin_g_dl": ["hemoglobin", "hb", "hemoglobina"],
    "severe_cytopenia_for_radioligand": [
        "citopenia_severa_radioligando",
        "cytopenia_severe",
    ],
    "cytopenias_corrected_for_radioligand": [
        "citopenias_corregidas_radioligando",
        "cytopenias_corrected",
    ],
    # Faubot 2026-04-24 (VI) — Gates 15-16 PARP inhibitors × hematología.
    # Aliases canónicos para que payloads legacy disparen correctamente
    # `parp_inhibitor_in_severe_cytopenias` y `parp_inhibitor_in_mds_aml_history`.
    # Los campos hematológicos básicos (anc/platelets/hemoglobin) ya están
    # canonicalizados por gate 14; aquí registramos los específicos PARPi.
    "severe_cytopenia_for_parp_inhibitor": [
        "citopenia_severa_parp",
        "parp_cytopenia_severe",
    ],
    "cytopenias_corrected_for_parp_inhibitor": [
        "citopenias_corregidas_parp",
        "parp_cytopenias_corrected",
    ],
    "mds_aml_history": [
        "antecedente_smd_lma",
        "history_mds_aml",
        "smd_lma_history",
    ],
    "prior_mds": ["antecedente_smd", "smd_previo"],
    "prior_aml": ["antecedente_lma", "lma_previa"],
    "secondary_hematologic_malignancy": [
        "neoplasia_hematologica_secundaria",
        "secondary_hem_malignancy",
    ],
    "prolonged_cytopenia_unexplained": [
        "citopenia_prolongada_inexplicada",
        "unexplained_prolonged_cytopenia",
    ],
    # Faubot 2026-04-25 (VII) — Gates 17-18 ARPI cardiotoxicidad.
    # Aliases canónicos para que payloads legacy disparen correctamente
    # `qtc_prolongation_grade3_for_enzalutamide` y `lvef_decline_for_apalutamide`.
    "qtc_change_ms": ["qtc_delta_ms", "qtc_change", "qtc_delta"],
    "lvef_baseline_percent": [
        "fevi_basal",
        "lvef_baseline",
        "lvef_pre_treatment",
    ],
    "qtc_corrected_for_arpi": [
        "qtc_corregido_para_arpi",
        "qtc_corrected",
    ],
    "lvef_recovered_for_arpi": [
        "lvef_recuperada_para_arpi",
        "lvef_recovered",
        "fevi_recuperada",
    ],
    "lvef_percent": [
        "fevi",
        "ejection_fraction",
        "fraccion_eyeccion",
    ],
}

ARPI_FRESHNESS_RULES = {
    "lft_date": 14,
    "conventional_imaging_date": 90,
    "molecular_assay_date": 3650,
    "molecular_report_date": 3650,
    "psadt_months": 30,
}

ARPI_STATE_CANDIDATES = {
    "m0_crpc": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"],
    "m1_crpc": ["ADT_ENZALUTAMIDE", "ADT_ABIRATERONE"],
    # EPIC 9 Group C (GAP-5) — ADT_TALAZO_ENZA_HRR (TALAPRO-3 precision doublet)
    # añadido como candidato en los 4 fenotipos mHSPC. El selector aplica gate
    # de biomarcador HRR (BRCA1/2/ATM/PALB2/CDK12/CHEK2/FANCA/MLH1/MRE11A/NBN/
    # RAD51B/RAD51C); hrr_negative o hrr_not_tested resultan en hard-block
    # desde `mhspc_regimen_selector.py::_regimen_profile`.
    "mcspc_high_volume_sync": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
        "ADT_TALAZO_ENZA_HRR",
    ],
    "mcspc_high_volume_metachronous": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
        "ADT_TALAZO_ENZA_HRR",
    ],
    "mcspc_low_volume_sync_oligo": [
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
        "ADT_TALAZO_ENZA_HRR",
    ],
    "mcspc_oligo_metachronous": [
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
        "ADT_TALAZO_ENZA_HRR",
    ],
    "recurrence_bcr": ["ADT_ENZALUTAMIDE"],
}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "present", "positive", "positivo"}


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _nonempty_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _field_value(payload: dict[str, Any], field_name: str) -> Any:
    if field_name in payload and payload.get(field_name) not in (None, ""):
        return payload.get(field_name)
    for alias in ARPI_FIELD_ALIASES.get(field_name, []):
        value = payload.get(alias)
        if value not in (None, "", [], {}):
            return value
    return payload.get(field_name)


def _field_present(payload: dict[str, Any], field_name: str) -> bool:
    value = _field_value(payload, field_name)
    if field_name == "metastatic_components_capture":
        if _truthy(payload.get("metastatic_disease_known")):
            return True
        if any(payload.get(alias) not in (None, "", [], {}) for alias in ARPI_FIELD_ALIASES[field_name][1:]):
            return True
    if field_name in {"current_medications"}:
        return _nonempty_text(value)
    return value not in (None, "", [], {}, "Desconocido", "Desconocida", "No documentado", "No aplica", "unknown")


def _field_is_stale(payload: dict[str, Any], field_name: str) -> bool:
    max_age_days = ARPI_FRESHNESS_RULES.get(field_name)
    if not max_age_days:
        return False
    field_date = _as_date(_field_value(payload, field_name))
    if not field_date:
        return False
    return (date.today() - field_date).days > max_age_days


def canonical_arpi_state(state: str) -> str:
    return str(state or "").strip()


def is_arpi_eligible_state(state: str) -> bool:
    return canonical_arpi_state(state) in ARPI_ELIGIBLE_STATES


def candidate_regimens_for_state(
    state: str,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    payload = payload or {}
    canonical = canonical_arpi_state(state)
    candidates = list(ARPI_STATE_CANDIDATES.get(canonical, []))
    if canonical == "m1_crpc":
        prior_therapy = str(payload.get("prior_therapy") or "").lower()
        if any(token in prior_therapy for token in ("enzalut", "apalut", "darolut")):
            candidates = [code for code in candidates if code != "ADT_ENZALUTAMIDE"]
        if "abirater" in prior_therapy:
            candidates = [code for code in candidates if code != "ADT_ABIRATERONE"]
    if canonical == "recurrence_bcr" and str(payload.get("salvage_local_feasible") or "").strip().lower() in {"1", "true", "yes", "si", "sí"}:
        return []
    return candidates


def arpi_required_fields_for_state(
    state: str,
    *,
    include_monitoring: bool = True,
) -> list[str]:
    canonical = canonical_arpi_state(state)
    required = list(ARPI_ONCOLOGIC_CONTEXT_BY_STATE.get(canonical, []))
    required.extend(ARPI_MOLECULE_DISCRIMINATION_BUNDLE)
    if include_monitoring:
        required.extend(ARPI_MONITORING_BUNDLE)
    return list(dict.fromkeys(required))


def build_arpi_capture_contract(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    payload = normalize_advanced_support_payload(payload or {}, state=state)
    canonical = canonical_arpi_state(state)
    candidates = list(candidate_regimens or candidate_regimens_for_state(canonical, payload))
    # Separate decision-critical vs recommended-monitoring fields. Only the
    # decision-critical set should gate ``preference_confidence``; monitoring
    # gaps attach a soft caveat but never disqualify the clinical leader
    # (BUG ERR-03 / ERR-17).
    decision_fields = (
        arpi_required_fields_for_state(canonical, include_monitoring=False) if candidates else []
    )
    monitoring_fields = list(ARPI_MONITORING_BUNDLE) if candidates else []
    required_fields = list(dict.fromkeys(decision_fields + monitoring_fields))

    decision_missing = [field for field in decision_fields if not _field_present(payload, field)]
    decision_stale = [
        field for field in decision_fields
        if field not in decision_missing and _field_is_stale(payload, field)
    ]
    monitoring_missing = [
        field for field in monitoring_fields if not _field_present(payload, field)
    ]
    monitoring_stale = [
        field for field in monitoring_fields
        if field not in monitoring_missing and _field_is_stale(payload, field)
    ]
    missing_inputs = list(dict.fromkeys(decision_missing + monitoring_missing))
    stale_inputs = list(dict.fromkeys(decision_stale + monitoring_stale))

    completeness = (
        "complete"
        if decision_fields and not decision_missing and not decision_stale
        else "partial"
        if decision_fields and (decision_missing or decision_stale or monitoring_missing or monitoring_stale)
        else "not_applicable"
    )
    preference_readiness = (
        "ready"
        if decision_fields and not decision_missing and not decision_stale
        else "needs_data"
        if decision_fields
        else "not_applicable"
    )
    return {
        "state": canonical,
        "candidate_regimens": candidates,
        "arpi_required_fields": required_fields,
        "arpi_decision_required_fields": decision_fields,
        "arpi_monitoring_required_fields": monitoring_fields,
        "arpi_missing_inputs": missing_inputs,
        "arpi_stale_inputs": stale_inputs,
        "arpi_decision_missing_inputs": decision_missing,
        "arpi_decision_stale_inputs": decision_stale,
        "arpi_monitoring_missing_inputs": monitoring_missing,
        "arpi_monitoring_stale_inputs": monitoring_stale,
        "arpi_profile_completeness": completeness,
        "arpi_preference_readiness": preference_readiness,
        "arpi_oncologic_context_bundle": list(ARPI_ONCOLOGIC_CONTEXT_BY_STATE.get(canonical, [])),
        "arpi_molecule_discrimination_bundle": list(ARPI_MOLECULE_DISCRIMINATION_BUNDLE),
        "arpi_monitoring_bundle": list(ARPI_MONITORING_BUNDLE),
    }


def _strength_value(value: str) -> float:
    return {
        "none": 0.0,
        "low": 1.0,
        "moderate": 2.0,
        "high": 3.0,
    }.get(str(value or "").strip().lower(), 0.0)


def _scenario_match_value(value: str) -> float:
    return {
        "exact": 4.0,
        "supported_extrapolation": 1.5,
        "weak_extrapolation": -1.5,
    }.get(str(value or "").strip().lower(), 0.0)


def _maturity_value(value: str) -> float:
    return {
        "early": 0.5,
        "intermediate": 1.25,
        "mature": 2.0,
    }.get(str(value or "").strip().lower(), 0.0)


def _endpoint_multiplier(state: str, endpoint: str) -> float:
    canonical = canonical_arpi_state(state)
    endpoint_key = str(endpoint or "").strip().upper()
    if canonical == "m0_crpc":
        return {"MFS": 2.0, "OS": 1.0, "RPFS": 0.5}.get(endpoint_key, 0.5)
    if canonical == "recurrence_bcr":
        return {"MFS": 2.0, "OS": 1.0, "RPFS": 0.5}.get(endpoint_key, 0.5)
    if canonical == "m1_crpc":
        return {"OS": 2.0, "RPFS": 1.5, "MFS": 0.5}.get(endpoint_key, 0.5)
    return {"OS": 2.0, "RPFS": 1.25, "MFS": 0.5}.get(endpoint_key, 0.5)


def _benefit_score(state: str, benefit_profile: dict[str, Any]) -> float:
    if not benefit_profile:
        return 0.0
    endpoint = str(benefit_profile.get("primary_benefit_endpoint") or "")
    benefit = float(benefit_profile.get("benefit_score") or 0.0)
    if benefit:
        return benefit
    return round(
        _scenario_match_value(str(benefit_profile.get("scenario_match") or ""))
        + _maturity_value(str(benefit_profile.get("evidence_maturity") or ""))
        + _strength_value(str(benefit_profile.get("os_benefit_strength") or ""))
        + _strength_value(str(benefit_profile.get("mfs_benefit_strength") or ""))
        + (_strength_value(str(benefit_profile.get("rpfs_benefit_strength") or "")) * _endpoint_multiplier(state, endpoint)),
        2,
    )


def _renal_penalty_for_regimen(payload: dict[str, Any], normalized_regimen: str) -> tuple[float, list[str], list[str]]:
    """EPIC 2 FIX-ARPI-RENAL: consume renal_dosing_flag() para traducir eGFR
    a penalización o "avoid" cuando el régimen incluye fármacos con rango
    renal (FDA Zytiga §2.3, Jevtana §2.2, Lynparza §2.3, Talzenna §2.3,
    Xofigo §5.3)."""
    agents = _ARPI_REGIMEN_TO_RENAL_AGENTS.get(normalized_regimen, ())
    if not agents:
        return 0.0, [], []
    egfr = _safe_float(_field_value(payload, "egfr_ml_min"))
    if egfr is None:
        egfr = _safe_float(payload.get("egfr_ml_min_1_73m2"))
    if egfr is None:
        return 0.0, [], []
    penalty = 0.0
    reasons: list[str] = []
    drivers: list[str] = []
    for agent in agents:
        flag = renal_dosing_flag(agent, egfr_ml_min_1_73m2=egfr)
        status = str(flag.get("status") or "").lower()
        label = regimen_label(normalized_regimen)
        if status == "avoid":
            penalty -= 9.0
            reasons.append(
                f"{label} se penaliza por eGFR {egfr:.0f} ml/min que contraindica "
                f"{agent} según {flag.get('evidence') or 'FDA label'}."
            )
            drivers.append("renal_avoid")
        elif status == "dose_reduce":
            penalty -= 4.0
            reasons.append(
                f"{label} requiere reducción de dosis por eGFR {egfr:.0f} "
                f"ml/min ({agent}: {flag.get('notes')})."
            )
            drivers.append("renal_dose_reduce")
    return penalty, reasons, drivers


def _safety_adjustment(payload: dict[str, Any], regimen_code: str) -> tuple[float, list[str], list[str]]:
    normalized = normalize_regimen_code(regimen_code)
    value = 0.0
    reasons: list[str] = []
    drivers: list[str] = []

    seizure = _truthy(_field_value(payload, "comorbidity_seizure"))
    cardio = _truthy(_field_value(payload, "comorbidity_cardio")) or _truthy(_field_value(payload, "cv_risk_documented"))
    ddi_review_status = str(_field_value(payload, "ddi_review_status") or "").strip().lower()
    ddi_reviewed = ddi_review_status == "completed"
    current_meds_present = bool(payload.get("normalized_medication_list")) or _nonempty_text(_field_value(payload, "current_medications"))
    ddi_matrix = dict(payload.get("ddi_regimen_matrix") or {})
    # EPIC 4.3: fallback real-time matrix. Si el payload trae una lista
    # estructurada de medicaciones pero el normalizador de soporte avanzado
    # no se corrió (tests directos / llamadas externas), la matriz DDI se
    # computa aquí sobre la marcha para el régimen evaluado y la revisión
    # queda "engine-completed" sin depender del flag UI.
    if not ddi_matrix and payload.get("normalized_medication_list"):
        try:
            from prostanet.shared.ddi_engine import DDIEngine as _DDIEngine
            ddi_matrix = _DDIEngine.compute_regimen_ddi_matrix(
                payload.get("normalized_medication_list") or [],
                [normalized],
                seizure_history=seizure,
            )
            if ddi_matrix:
                ddi_reviewed = True
        except Exception:
            ddi_matrix = {}
    regimen_ddi = dict(ddi_matrix.get(normalized) or {})
    ddi_status = str(regimen_ddi.get("status") or "none").strip().lower()
    ddi_families = tuple(regimen_ddi.get("families") or ())
    dermatitis = _truthy(_field_value(payload, "dermatitis_history"))
    cognitive_risk = _truthy(_field_value(payload, "cognitive_risk"))
    fall_risk = _truthy(_field_value(payload, "fall_risk"))
    stroke_history = _truthy(_field_value(payload, "stroke_history"))
    edema_risk = _truthy(_field_value(payload, "edema_risk"))
    steroid_intolerance = _truthy(_field_value(payload, "steroid_intolerance"))
    diabetes_uncontrolled = _truthy(_field_value(payload, "diabetes_uncontrolled"))
    hepatic_risk = _truthy(_field_value(payload, "hepatic_risk_factors")) or str(_field_value(payload, "child_pugh_score") or "").strip().upper() in {"B", "C"}
    frailty = str(_field_value(payload, "frailty_status") or "").strip().lower()
    flags = {
        "seizure_risk": seizure,
        "cardio_risk": cardio,
        "cognitive_risk": cognitive_risk,
        "fall_risk": fall_risk,
        "stroke_history": stroke_history,
        "edema_risk": edema_risk,
        "steroid_intolerance": steroid_intolerance,
        "diabetes_uncontrolled": diabetes_uncontrolled,
        "dermatitis_history": dermatitis,
        "frailty_status": frailty in {"vulnerable", "frail"},
        "hepatic_risk": hepatic_risk,
        "polypharmacy": current_meds_present and not ddi_reviewed,
        "ddi_major_or_worse": ddi_status in {"major", "contraindicated"},
    }

    # EPIC 9 Group E (GAP-9) — cuando la medicación estructurada
    # (`normalized_medication_list`) alimenta el matriz DDI en tiempo real,
    # la severidad "contraindicated" debe actuar como hard-block efectivo.
    # Penalty −40 garantiza que el régimen no gane ranking aun con bonos
    # fuertes de fenotipo (+22 HRR, +18 pivotal). La severidad "major" pasa
    # de −5.5 a −12 para degradar el régimen sin bloquearlo totalmente. El
    # driver "ddi_hard_block" se propaga a `alert_engine` para UI y a
    # `clinical_decision_governance` para gating de la decisión.
    if ddi_status == "contraindicated":
        value -= 40.0
        reasons.append(
            f"{regimen_label(normalized)} se bloquea por interacción farmacológica "
            "CONTRAINDICADA con la medicación concomitante documentada "
            "(DDIEngine runtime; EPIC 9 GAP-9)."
        )
        drivers.append("ddi_contraindicated")
        drivers.append("ddi_hard_block")
    elif ddi_status == "major":
        value -= 12.0
        reasons.append(
            f"{regimen_label(normalized)} se penaliza por interacción farmacológica "
            "MAYOR con la medicación concomitante documentada; requiere ajuste de "
            "dosis/monitorización estricta o alternativa."
        )
        drivers.append("ddi_major")
    elif ddi_status == "caution":
        value -= 2.0
        reasons.append(f"{regimen_label(normalized)} requiere cautela por interacción farmacológica moderada.")
        drivers.append("ddi_caution")

    # EPIC 4.4: propagar familias DDI específicas (ddi_qtc, ddi_seizure,
    # ddi_bone_health) como drivers adicionales para alert_engine + UI.
    for family in ddi_families:
        family_key = str(family or "").strip().lower()
        if family_key and family_key not in {"ddi_critical", "ddi_major", "ddi_moderate", "ddi_info"}:
            drivers.append(family_key)
    drivers = list(dict.fromkeys(drivers))

    if normalized.endswith("DAROLUTAMIDE"):
        if seizure:
            value += 6.0
            reasons.append("Darolutamida gana valor por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if cognitive_risk or fall_risk or stroke_history:
            value += 5.0
            reasons.append("Darolutamida gana valor por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if current_meds_present and ddi_status == "none" and ddi_reviewed:
            value += 2.0
            reasons.append("Darolutamida gana valor relativo porque no se detectaron interacciones mayores con la medicación concomitante.")
            drivers.append("ddi_clearance")
        elif current_meds_present and not ddi_reviewed:
            value += 2.0
            reasons.append("Darolutamida gana valor relativo ante polifarmacia con revisión DDI pendiente.")
            drivers.append("polypharmacy")
        if cardio:
            value += 1.5
            reasons.append("El contexto cardiovascular favorece un eje androgénico sin esteroide.")
            drivers.append("cardio_risk")
    elif normalized.endswith("ENZALUTAMIDE"):
        if seizure:
            value -= 8.0
            reasons.append("Enzalutamida se penaliza por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if cognitive_risk or fall_risk or stroke_history:
            value -= 5.5
            reasons.append("Enzalutamida se penaliza por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if current_meds_present and not ddi_reviewed:
            value -= 2.5
            reasons.append("Enzalutamida se penaliza por polifarmacia sin revisión DDI formal.")
            drivers.append("polypharmacy")
    elif normalized.endswith("APALUTAMIDE"):
        if seizure:
            value -= 8.0
            reasons.append("Apalutamida se penaliza por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if dermatitis:
            value -= 6.0
            reasons.append("Apalutamida se penaliza por antecedente de rash/dermatitis.")
            drivers.append("dermatitis_history")
        if cognitive_risk or fall_risk or stroke_history:
            value -= 4.5
            reasons.append("Apalutamida se penaliza por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if frailty in {"vulnerable", "frail"}:
            value -= 2.5
            reasons.append("La fragilidad reduce el atractivo de apalutamida.")
            drivers.append("frailty_status")
    elif normalized.endswith("ABIRATERONE"):
        if hepatic_risk:
            value -= 9.0
            reasons.append("Abiraterona se penaliza por riesgo hepático/Child-Pugh desfavorable.")
            drivers.append("hepatic_risk")
        if cardio or edema_risk:
            value -= 5.5
            reasons.append("Abiraterona se penaliza por edema o riesgo cardiometabólico.")
            drivers.extend([item for item in ("cardio_risk", "edema_risk") if flags[item]])
        if steroid_intolerance or diabetes_uncontrolled:
            value -= 6.0
            reasons.append("Abiraterona se penaliza por carga de esteroides.")
            drivers.extend([item for item in ("steroid_intolerance", "diabetes_uncontrolled") if flags[item]])
        if seizure:
            value += 1.0
            reasons.append("Abiraterona gana algo de valor relativo frente a ARPI con mayor carga central.")
            drivers.append("seizure_risk")

    # EPIC 2 FIX-ARPI-RENAL: aplicar penalización renal al final para que
    # cualquier régimen con fármacos renal-sensibles herede el gate eGFR sin
    # duplicar lógica por rama.
    renal_penalty, renal_reasons, renal_drivers = _renal_penalty_for_regimen(payload, normalized)
    if renal_penalty:
        value += renal_penalty
        reasons.extend(renal_reasons)
        drivers.extend(renal_drivers)

    return value, reasons, sorted(set(drivers))


def evaluate_arpi_candidate(
    state: str,
    payload: dict[str, Any] | None,
    regimen_code: str,
    *,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    payload = normalize_advanced_support_payload(payload, state=state)
    normalized_regimen = normalize_regimen_code(regimen_code)
    canonical = canonical_arpi_state(state)
    capture = build_arpi_capture_contract(canonical, payload, candidate_regimens=candidate_regimens)
    benefit_profile = benefit_profile_for_state(canonical, normalized_regimen)
    benefit_score = _benefit_score(canonical, benefit_profile)
    safety_adjustment, safety_reasons, safety_drivers = _safety_adjustment(payload, normalized_regimen)
    decision_missing = list(capture.get("arpi_decision_missing_inputs") or [])
    decision_stale = list(capture.get("arpi_decision_stale_inputs") or [])
    monitoring_missing = list(capture.get("arpi_monitoring_missing_inputs") or [])
    monitoring_stale = list(capture.get("arpi_monitoring_stale_inputs") or [])
    # Only decision-critical fields flip the confidence to provisional; missing
    # monitoring fields apply a soft caveat without disqualifying the leader
    # (BUG ERR-03 / ERR-17).
    required_missing_fields = list(capture.get("arpi_missing_inputs") or [])
    stale_inputs = list(capture.get("arpi_stale_inputs") or [])
    if decision_missing or decision_stale:
        completeness_penalty = -18.0
        preference_confidence = "provisional"
    elif monitoring_missing or monitoring_stale:
        completeness_penalty = -4.0
        preference_confidence = "definitive"
    else:
        completeness_penalty = 0.0
        preference_confidence = "definitive"
    total_adjustment = benefit_score + safety_adjustment + completeness_penalty
    benefit_endpoint_used = str(benefit_profile.get("primary_benefit_endpoint") or "")
    benefit_maturity = str(benefit_profile.get("evidence_maturity") or "")
    trial_basis = str(benefit_profile.get("trial_basis") or "")
    regulatory_support = str(benefit_profile.get("regulatory_support") or "")
    benefit_basis = (
        f"{trial_basis} con endpoint primario {benefit_endpoint_used} y soporte regulatorio {regulatory_support}."
        if trial_basis or regulatory_support
        else ""
    ).strip()
    return {
        "regimen_code": normalized_regimen,
        "regimen_label": regimen_label(normalized_regimen),
        "benefit_profile": benefit_profile,
        "benefit_score": benefit_score,
        "benefit_basis": benefit_basis,
        "benefit_endpoint_used": benefit_endpoint_used,
        "benefit_maturity": benefit_maturity,
        "benefit_adjustment": total_adjustment,
        "benefit_support": {
            "trial_basis": trial_basis,
            "regulatory_support": regulatory_support,
            "scenario_match": str(benefit_profile.get("scenario_match") or ""),
        },
        "safety_rationale": safety_reasons,
        "safety_drivers_used": safety_drivers,
        "required_missing_fields": required_missing_fields,
        "stale_inputs": stale_inputs,
        "preference_confidence": preference_confidence,
        "arpi_capture_contract": capture,
    }


def enrich_ranked_option_with_arpi_metadata(
    option: dict[str, Any],
    *,
    state: str,
    payload: dict[str, Any] | None,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    enriched = dict(option or {})
    regimen_code = str(enriched.get("regimen_code") or "")
    if not regimen_code:
        return enriched
    metadata = evaluate_arpi_candidate(
        state,
        payload or {},
        regimen_code,
        candidate_regimens=candidate_regimens,
    )
    enriched["benefit_basis"] = metadata.get("benefit_basis", "")
    enriched["benefit_endpoint_used"] = metadata.get("benefit_endpoint_used", "")
    enriched["benefit_maturity"] = metadata.get("benefit_maturity", "")
    enriched["benefit_support"] = dict(metadata.get("benefit_support") or {})
    enriched["required_missing_fields"] = list(metadata.get("required_missing_fields") or [])
    enriched["stale_inputs"] = list(metadata.get("stale_inputs") or [])
    enriched["preference_confidence"] = metadata.get("preference_confidence", "")
    enriched["safety_drivers_used"] = list(metadata.get("safety_drivers_used") or [])
    return enriched
