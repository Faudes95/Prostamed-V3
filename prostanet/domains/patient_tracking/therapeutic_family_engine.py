from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import (
    build_treatment_option,
    normalize_regimen_code,
    regimen_label,
    regimen_metadata_bundle,
)


FAMILY_LABELS = {
    "arpi_family": "ARPI",
    "abiraterone_steroid_family": "Abiraterona + esteroide",
    "taxane_family": "Taxanos",
    "psma_rlt_family": "PSMA-RLT",
    "parp_family": "PARP",
    "radium223_family": "Radio-223",
    "immunotherapy_family": "Inmunoterapia",
    "platinum_family": "Quimioterapia platino (NEPC / rechallenge HRR)",
    "clinical_trial_family": "Ensayo clínico dirigido",
    "salvage_rt_family": "Salvage / RT",
    "local_mdt_family": "Control local / MDT",
    "active_surveillance_family": "Vigilancia activa",
    "surveillance_family": "Vigilancia",
    "surgery_family": "Cirugía",
    "radiotherapy_family": "Radioterapia",
    "multimodal_local_family": "Multimodal local",
    "observation_family": "Observación / backbone",
}


def family_label(family_code: str) -> str:
    return FAMILY_LABELS.get(str(family_code or "").strip(), str(family_code or "").strip())


def regimen_family_code(regimen_code: Any, *, fallback: str = "observation_family") -> str:
    normalized = normalize_regimen_code(regimen_code)
    if not normalized:
        return fallback
    if normalized in {"ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_DAROLUTAMIDE"}:
        return "arpi_family"
    if normalized in {"ADT_ABIRATERONE"}:
        return "abiraterone_steroid_family"
    if normalized in {"ADT_DOCETAXEL", "ADT_DOCETAXEL_DAROLUTAMIDE", "ADT_DOCETAXEL_ABIRATERONE", "DOCETAXEL", "CABAZITAXEL"}:
        return "taxane_family"
    if normalized in {"LU177_PSMA617"}:
        return "psma_rlt_family"
    if normalized in {"OLAPARIB", "RUCAPARIB", "TALAZOPARIB_ENZALUTAMIDE", "NIRAPARIB_ABIRATERONE"}:
        return "parp_family"
    if normalized in {"RADIUM223"}:
        return "radium223_family"
    # Auditoría Pacientes Insignia 2026-04-21 (§A.4) — IMPACT (Sipuleucel-T,
    # inmunoterapia celular autóloga) y CONTACT-02 (cabozantinib+atezolizumab)
    # se agrupan en immunotherapy_family para recibir family_profile y llegar
    # a `eligible_treatments` vía comparative_bundle.
    if normalized in {"PEMBROLIZUMAB", "SIPULEUCEL_T", "CABOZANTINIB_ATEZOLIZUMAB"}:
        return "immunotherapy_family"
    if normalized in {"CARBOPLATIN_ETOPOSIDE_NEPC", "CISPLATIN_DOCETAXEL_NEPC", "CARBOPLATIN_ETOPOSIDE"}:
        return "platinum_family"
    if normalized in {"CLINICAL_TRIAL_POST_PARP"}:
        return "clinical_trial_family"
    if normalized in {"ADT_MONO", "OBSERVATION", "RESTAGING", "PSMA_RESTAGING", "SYSTEMIC_RESTAGING"}:
        return "observation_family"
    if normalized in {"ACTIVE_SURVEILLANCE"}:
        return "active_surveillance_family"
    if normalized in {"SURVEILLANCE", "POST_RP_SURVEILLANCE"}:
        return "surveillance_family"
    if normalized in {"RADICAL_PROSTATECTOMY", "RP_PLND", "SALVAGE_PROSTATECTOMY"}:
        return "surgery_family"
    if normalized in {"DEFINITIVE_RT", "RT_SHORT_ADT", "RT_LONG_ADT", "POSTOP_RT", "RT_TO_PRIMARY"}:
        return "radiotherapy_family"
    if normalized in {"RT_ADT_ABIRATERONE", "REGIONAL_RT_ADT_ABIRATERONE"}:
        return "multimodal_local_family"
    if normalized in {
        "SALVAGE_RT_ALONE",
        "SALVAGE_RT_SHORT_HORMONE",
        "SALVAGE_RT_PELVIC_SHORT_HORMONE",
        "SALVAGE_RT_LONG_HORMONE",
    }:
        return "salvage_rt_family"
    if normalized in {"LOCAL_MDT", "PSMA_GUIDED_MDT", "PRIMARY_RT_MDT", "SALVAGE_CRYOTHERAPY", "SALVAGE_HIFU", "SALVAGE_BRACHYTHERAPY"}:
        return "local_mdt_family"
    if normalized in {"POST_RT_CONFIRMATION", "POST_RT_RESTAGING"}:
        return "observation_family"
    normalized_upper = str(normalized or "").upper()
    if normalized_upper.startswith("SALVAGE_RT"):
        return "salvage_rt_family"
    if normalized_upper.startswith("LOCAL_MDT") or normalized_upper.startswith("MDT"):
        return "local_mdt_family"
    if normalized_upper.startswith("ACTIVE_SURVEILLANCE"):
        return "active_surveillance_family"
    if normalized_upper.startswith("SURVEILLANCE"):
        return "surveillance_family"
    if "PROSTATECTOMY" in normalized_upper or normalized_upper.startswith("RP_"):
        return "surgery_family"
    if normalized_upper.startswith("RT_") or normalized_upper.endswith("_RT") or normalized_upper.startswith("DEFINITIVE_RT"):
        return "radiotherapy_family"
    return fallback


def build_ranked_option(
    *,
    name: str = "",
    regimen_code: Any,
    rank: int,
    priority: str,
    eligibility_status: str,
    notes: str = "",
    family_code: str = "",
    molecule_or_backbone: str = "",
    why_this_rank: list[str] | None = None,
    hard_blocks: list[str] | None = None,
    caution_flags: list[str] | None = None,
    selection_rationale: list[str] | None = None,
    contraindication_reasons: list[str] | None = None,
    duration: str = "",
    description: str = "",
    dose: str = "",
    route: str = "",
    schedule: str = "",
    component_drugs: list[dict[str, Any]] | None = None,
    imss_key: str = "",
    clave_imss: str = "",
    metadata_source: str = "",
    therapy_class: str = "",
    evidence_tags: list[str] | None = None,
    ranking_score: float | None = None,
    family_rank: int | None = None,
    benefit_basis: str = "",
    benefit_endpoint_used: str = "",
    benefit_maturity: str = "",
    benefit_support: dict[str, Any] | None = None,
    preference_confidence: str = "",
    required_missing_fields: list[str] | None = None,
    safety_drivers_used: list[str] | None = None,
    stale_inputs: list[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_regimen_code(regimen_code)
    bundle = build_treatment_option(
        name=name or regimen_label(normalized) or str(regimen_code or ""),
        priority=priority,
        regimen_code=normalized,
        notes=notes,
        description=description,
        dose=dose,
        route=route,
        schedule=schedule,
        component_drugs=component_drugs,
        imss_key=imss_key,
        clave_imss=clave_imss,
        metadata_source=metadata_source,
        therapy_class=therapy_class,
        evidence_tags=evidence_tags,
        selection_rationale=list(selection_rationale or []),
        contraindication_reasons=list(contraindication_reasons or []),
        duration=duration,
        rank=rank,
        eligibility_status=eligibility_status,
        family_code=family_code or regimen_family_code(normalized),
        family_label=family_label(family_code or regimen_family_code(normalized)),
        molecule_or_backbone=molecule_or_backbone or regimen_label(normalized),
        why_this_rank=list(why_this_rank or []),
        hard_blocks=list(hard_blocks or []),
        caution_flags=list(caution_flags or []),
        ranking_score=ranking_score,
        family_rank=family_rank,
    )
    bundle["benefit_basis"] = benefit_basis
    bundle["benefit_endpoint_used"] = benefit_endpoint_used
    bundle["benefit_maturity"] = benefit_maturity
    bundle["benefit_support"] = dict(benefit_support or {})
    bundle["preference_confidence"] = preference_confidence
    bundle["required_missing_fields"] = list(required_missing_fields or [])
    bundle["safety_drivers_used"] = list(safety_drivers_used or [])
    bundle["stale_inputs"] = list(stale_inputs or [])
    bundle["is_preferred"] = str(priority or "").lower() in {"preferred", "preferente"} or str(eligibility_status or "").lower() in {"preferred", "preferente"}
    return bundle


def build_family_profile(
    *,
    family_code: str,
    ordered_regimens: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(context or {})
    ordered = [deepcopy(item) for item in ordered_regimens if isinstance(item, dict)]
    eligible = [item for item in ordered if str(item.get("eligibility_status") or "") in {"preferred", "eligible_nonpreferred", "eligible_with_caution"}]
    nonpreferred_or_ineligible = [item for item in ordered if item not in eligible]
    preferred = next((item for item in eligible if str(item.get("eligibility_status") or "") == "preferred"), {})
    if not preferred and eligible:
        fallback = dict(eligible[0])
        fallback["family_default_eligibility_status"] = str(eligible[0].get("eligibility_status") or "")
        fallback["family_default_priority"] = str(eligible[0].get("priority") or "")
        fallback["eligibility_status"] = "preferred"
        fallback["priority"] = "preferred"
        fallback["is_preferred"] = True
        eligible[0] = fallback
        preferred = fallback
    elif preferred:
        preferred_code = str(preferred.get("regimen_code") or "")
        preferred_name = str(preferred.get("name") or "")
        reordered: list[dict[str, Any]] = [preferred]
        consumed_preferred = False
        for item in eligible:
            same_item = (
                not consumed_preferred
                and str(item.get("regimen_code") or "") == preferred_code
                and str(item.get("name") or "") == preferred_name
            )
            if same_item:
                consumed_preferred = True
                continue
            reordered.append(item)
        eligible = reordered
    family_status = str(context.get("eligibility_status") or ("eligible" if eligible else "contraindicated" if nonpreferred_or_ineligible else "not_assessable"))
    missing_inputs = list(dict.fromkeys(context.get("missing_inputs") or []))
    stale_inputs = list(dict.fromkeys(context.get("stale_inputs") or []))
    if family_status == "eligible" and (missing_inputs or stale_inputs):
        family_status = "conditional"
    recency_status = str(context.get("recency_status") or ("stale" if stale_inputs else "missing" if missing_inputs else "fresh"))
    return {
        "family_code": family_code,
        "family_label": family_label(family_code),
        "eligibility_status": family_status,
        "hard_blocks": list(dict.fromkeys(context.get("hard_blocks") or [])),
        "caution_drivers": list(dict.fromkeys(context.get("caution_drivers") or [])),
        "preference_drivers": list(dict.fromkeys(context.get("preference_drivers") or [])),
        "missing_inputs": missing_inputs,
        "stale_inputs": stale_inputs,
        "recency_status": recency_status,
        "provenance_summary": dict(context.get("provenance_summary") or {}),
        "evidence_alignment": str(context.get("evidence_alignment") or "matched"),
        "comparative_priority_score": float(context.get("comparative_priority_score") or (100 - len(nonpreferred_or_ineligible) * 3 + len(eligible) * 2)),
        "winner_reason": str(context.get("winner_reason") or (preferred.get("why_this_rank") or [preferred.get("notes") or ""])[0] if preferred else ""),
        "why_not_preferred": str(context.get("why_not_preferred") or ""),
        "variant_ranking": {
            "preferred_regimen_code": str(preferred.get("regimen_code") or ""),
            "preferred_regimen_label": str(preferred.get("name") or ""),
            "eligible_regimens_ranked": eligible,
            "nonpreferred_or_ineligible_regimens": nonpreferred_or_ineligible,
            "ranking_trace": list(context.get("ranking_trace") or []),
        },
    }


def build_global_ranking(
    *,
    family_profiles: dict[str, dict[str, Any]],
    family_order: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    ordered_codes = list(family_order or [])
    for code in family_profiles:
        if code not in ordered_codes:
            ordered_codes.append(code)
    ordered_options: list[dict[str, Any]] = []
    preferred: dict[str, Any] = {}
    alternatives: list[dict[str, Any]] = []
    for family_rank, family_code in enumerate(ordered_codes, start=1):
        profile = family_profiles.get(family_code) or {}
        ranked = list(((profile.get("variant_ranking") or {}).get("eligible_regimens_ranked") or []))
        for variant_rank, item in enumerate(ranked, start=1):
            enriched = dict(item)
            enriched["family_rank"] = family_rank
            enriched["rank"] = len(ordered_options) + 1
            if ordered_options:
                prior_status = str(enriched.get("eligibility_status") or "")
                family_default_status = str(enriched.get("family_default_eligibility_status") or "")
                family_default_priority = str(enriched.get("family_default_priority") or "")
                if prior_status == "preferred":
                    enriched["eligibility_status"] = family_default_status or "eligible_nonpreferred"
                if str(enriched.get("priority") or "") == "preferred":
                    enriched["priority"] = family_default_priority or "eligible"
                enriched["is_preferred"] = False
            else:
                enriched["eligibility_status"] = "preferred"
                enriched["priority"] = "preferred"
                enriched["is_preferred"] = True
            ordered_options.append(enriched)
            if not preferred:
                preferred = deepcopy(enriched)
            elif len(alternatives) < 4:
                alternatives.append(deepcopy(enriched))
    return ordered_options, preferred, alternatives


def build_comparative_bundle(
    *,
    family_profiles: dict[str, dict[str, Any]],
    family_order: list[str] | None = None,
) -> dict[str, Any]:
    ordered_options, preferred, alternatives = build_global_ranking(
        family_profiles=family_profiles,
        family_order=family_order,
    )
    return {
        "comparative_eligibility_matrix": family_profiles,
        "eligible_treatments": ordered_options,
        "preferred_regimen": preferred,
        "alternative_regimens": alternatives,
    }


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "unknown", "UNKNOWN")


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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "present", "positive", "positivo"}


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))


MONITORING_TEMPLATES = {
    "arpi_family": {
        "response_metrics": ["psa", "testosterone", "symptom_burden"],
        "safety_metrics": ["blood_pressure", "falls", "cognition", "rash", "ddi_review"],
        "hold_rules": ["grade_3_neurotoxicity", "recurrent_falls", "uncontrolled_hypertension"],
        "switch_rules": ["radiographic_progression", "symptomatic_progression", "intolerable_cns_toxicity"],
        "required_visit_fields": ["psa", "testosterone", "systolic_bp", "fatigue_score", "mini_cog_score", "ddi_review_status", "dermatitis_history"],
        "monitoring_focus": "ARPI activa: respuesta bioquimica, seguridad neurologica, DDI y tolerabilidad.",
        "recommended_cadence": "Cada 4-6 semanas al inicio y luego cada 8-12 semanas si permanece estable.",
    },
    "abiraterone_steroid_family": {
        "response_metrics": ["psa", "testosterone", "symptom_burden"],
        "safety_metrics": ["ast", "alt", "bilirubin", "potassium", "blood_pressure", "glucose", "edema"],
        "hold_rules": ["grade_3_hepatotoxicity", "refractory_hypokalemia", "decompensated_edema_or_hf"],
        "switch_rules": ["radiographic_progression", "symptomatic_progression", "persistent_metabolic_toxicity"],
        "required_visit_fields": ["psa", "testosterone", "ast", "alt", "bilirubin", "potassium", "systolic_bp", "glucose", "edema_grade"],
        "monitoring_focus": "Abiraterona activa: respuesta, eje mineralocorticoide y seguridad hepatico-metabolica.",
        "recommended_cadence": "Cada 2-4 semanas al inicio y luego cada 4-8 semanas segun estabilidad.",
    },
    "taxane_family": {
        "response_metrics": ["psa", "radiographic_response", "pain_burden"],
        "safety_metrics": ["cbc", "ast", "alt", "bilirubin", "neuropathy_grade", "ecog_score"],
        "hold_rules": ["anc_below_threshold", "febrile_neutropenia", "grade_3_neuropathy"],
        "switch_rules": ["radiographic_progression", "clinical_progression", "taxane_intolerance"],
        "required_visit_fields": ["psa", "ecog_score", "cbc_date", "anc", "platelets", "liver_panel_date", "bilirubin", "ast", "alt", "alp", "peripheral_neuropathy_grade", "bpi_worst_pain"],
        "monitoring_focus": "Taxano activo: mielosupresion, neuropatia, respuesta clinica y tolerancia funcional.",
        "recommended_cadence": "Antes de cada ciclo y reevaluacion clinica/imaging cada 6-12 semanas.",
    },
    "psma_rlt_family": {
        "response_metrics": ["psa", "pain_burden", "radiographic_response"],
        "safety_metrics": ["cbc", "renal_function", "xerostomia", "nausea"],
        "hold_rules": ["marrow_suppression", "renal_decline"],
        "switch_rules": ["radiographic_progression", "symptomatic_progression", "psma_loss_or_intolerance"],
        "required_visit_fields": ["psa", "cbc_date", "hemoglobin", "platelets", "renal_function", "xerostomia_grade", "nausea_grade", "bpi_worst_pain", "psma_pet_date"],
        "monitoring_focus": "PSMA-RLT activa: mantenimiento de elegibilidad PSMA y seguridad medular/renal.",
        "recommended_cadence": "Antes de cada ciclo y reestadificacion segun protocolo radioligando.",
    },
    "parp_family": {
        "response_metrics": ["psa", "radiographic_response"],
        "safety_metrics": ["cbc", "renal_function", "fatigue", "anemia"],
        "hold_rules": ["grade_3_anemia", "severe_fatigue", "renal_decline"],
        "switch_rules": ["radiographic_progression", "clinical_progression", "parp_intolerance"],
        "required_visit_fields": ["psa", "cbc_date", "hemoglobin", "platelets", "renal_function", "fatigue_score", "hrr_status", "hrr_gene"],
        "monitoring_focus": "PARP activo: reserva hematologica, funcion renal y persistencia del racional molecular.",
        "recommended_cadence": "Cada 2-4 semanas al inicio y luego cada 4-8 semanas si estable.",
    },
    "radium223_family": {
        "response_metrics": ["pain_burden", "skeletal_events"],
        "safety_metrics": ["cbc", "fracture_prevention_status", "bone_support"],
        "hold_rules": ["marrow_suppression", "new_visceral_metastases"],
        "switch_rules": ["symptomatic_progression", "visceral_progression", "hematologic_toxicity"],
        "required_visit_fields": ["cbc_date", "hemoglobin", "platelets", "bpi_worst_pain", "visceral_metastases_present", "fracture_prevention_plan", "calcium_vitd_status"],
        "monitoring_focus": "Radio-223 activo: carga osea sintomatica, seguridad hematologica y prevencion de fracturas.",
        "recommended_cadence": "Antes de cada ciclo mensual y reevaluacion de patron metastasico.",
    },
    "immunotherapy_family": {
        "response_metrics": ["radiographic_response", "symptom_burden"],
        "safety_metrics": ["autoimmune_toxicity", "steroid_need", "performance_status"],
        "hold_rules": ["grade_3_immune_toxicity", "steroid_dependent_irAE"],
        "switch_rules": ["radiographic_progression", "symptomatic_progression", "immune_toxicity"],
        "required_visit_fields": ["ecog_score", "autoimmune_risk", "steroid_dependency", "immune_toxicity_grade", "msi_status", "dmmr_status", "tmb_status"],
        "monitoring_focus": "Inmunoterapia activa: irAE, dependencia a esteroides y sostén del biomarcador inmune.",
        "recommended_cadence": "Cada ciclo y con reevaluacion temprana ante sintomas inmunomediados.",
    },
    "salvage_rt_family": {
        "response_metrics": ["psa", "psadt_months", "restaging_result"],
        "safety_metrics": ["urinary_toxicity", "bowel_toxicity"],
        "hold_rules": ["unresolved_restaging", "local_infeasibility"],
        "switch_rules": ["systemic_redirect", "metastatic_restaging", "salvage_not_feasible"],
        "required_visit_fields": ["visit_date", "psa", "psadt_months", "restaging_imaging_type", "restaging_imaging_date", "salvage_local_feasible", "gu_toxicity_grade", "gi_toxicity_grade"],
        "monitoring_focus": "Salvage/RT activa: ventana curativa, reestadificacion y toxicidad GU/GI.",
        "recommended_cadence": "Revaluar cada 4-8 semanas mientras siga abierta la ventana de rescate.",
    },
    "local_mdt_family": {
        "response_metrics": ["psa", "site_control", "oligoprogression_count"],
        "safety_metrics": ["local_toxicity", "performance_status"],
        "hold_rules": ["mdt_not_feasible", "polymetastatic_shift"],
        "switch_rules": ["new_polymetastatic_progression", "systemic_progression"],
        "required_visit_fields": ["psa", "metastasis_count", "restaging_imaging_type", "restaging_imaging_date", "ecog_score", "local_toxicity_grade"],
        "monitoring_focus": "MDT/local activa: control de sitios, factibilidad local y señal de cambio a enfermedad policlonal.",
        "recommended_cadence": "Segun ventana MDT; reestadificacion cada 6-12 semanas o antes si cambia la carga.",
    },
    "active_surveillance_family": {
        "response_metrics": ["psa", "mpmri", "confirmatory_biopsy"],
        "safety_metrics": ["grade_group_upgrade", "core_burden_change"],
        "hold_rules": ["histologic_upgrade", "mpmri_progression"],
        "switch_rules": ["grade_progression", "volume_progression", "patient_preference_change"],
        "required_visit_fields": ["psa", "mri_interval_months", "confirmatory_biopsy_done", "pirads_score", "num_cores_positive"],
        "monitoring_focus": "Vigilancia activa: triggers de reclasificacion y confirmacion seriada.",
        "recommended_cadence": "PSA/MRI/biopsia segun protocolo de vigilancia activa.",
    },
    "surveillance_family": {
        "response_metrics": ["psa", "postop_psa", "time_to_recurrence"],
        "safety_metrics": ["urinary_function", "sexual_function"],
        "hold_rules": ["persistent_psa", "biochemical_recurrence"],
        "switch_rules": ["true_bcr", "persistent_psa", "new_restaging_signal"],
        "required_visit_fields": ["psa", "visit_date", "pad_usage", "iief5_score"],
        "monitoring_focus": "Vigilancia postlocal: control bioquimico y recuperacion funcional.",
        "recommended_cadence": "PSA seriado segun guideline y reevaluacion funcional periodica.",
    },
    "surgery_family": {
        "response_metrics": ["pathology_review", "postop_psa"],
        "safety_metrics": ["urinary_toxicity", "sexual_function", "surgical_complications"],
        "hold_rules": ["surgical_unfitness", "anatomic_infeasibility"],
        "switch_rules": ["pathologic_upstaging", "positive_margin_context", "patient_preference_change"],
        "required_visit_fields": ["visit_date", "ecog_score", "clinical_tstage", "ipss_total", "iief5_score"],
        "monitoring_focus": "Ruta quirurgica/local: factibilidad, funcion basal y correlacion anatomopatologica.",
        "recommended_cadence": "Reevaluacion preoperatoria segun board local.",
    },
    "radiotherapy_family": {
        "response_metrics": ["psa", "local_control"],
        "safety_metrics": ["urinary_toxicity", "bowel_toxicity", "fatigue"],
        "hold_rules": ["radiation_infeasibility", "active_bowel_toxicity"],
        "switch_rules": ["radiographic_progression", "biochemical_escape", "intolerable_gu_gi_toxicity"],
        "required_visit_fields": ["psa", "gu_toxicity_grade", "gi_toxicity_grade", "fatigue_score", "visit_date"],
        "monitoring_focus": "Radioterapia activa: control local y toxicidad GU/GI.",
        "recommended_cadence": "Controles seriados durante RT y luego segun respuesta/local symptoms.",
    },
    "multimodal_local_family": {
        "response_metrics": ["psa", "local_control", "systemic_control"],
        "safety_metrics": ["urinary_toxicity", "bowel_toxicity", "metabolic_toxicity"],
        "hold_rules": ["local_infeasibility", "systemic_intolerance"],
        "switch_rules": ["radiographic_progression", "clinical_progression", "intensification_intolerance"],
        "required_visit_fields": ["psa", "gu_toxicity_grade", "gi_toxicity_grade", "ast", "alt", "bilirubin", "potassium"],
        "monitoring_focus": "Multimodal local: control local mas seguridad sistemica del componente intensificador.",
        "recommended_cadence": "Segun componente activo mas intensivo en curso.",
    },
    "observation_family": {
        "response_metrics": ["psa", "testosterone", "symptom_burden"],
        "safety_metrics": ["none"],
        "hold_rules": ["none"],
        "switch_rules": ["psadt_shortening", "radiographic_progression", "symptomatic_progression"],
        "required_visit_fields": ["psa", "testosterone", "visit_date"],
        "monitoring_focus": "Observacion/ADT backbone: confirmar estabilidad biologica y sintomas.",
        "recommended_cadence": "PSA/testosterona cada 1-3 meses segun fenotipo.",
    },
}


FIELD_RECENCY_RULES = {
    "psa": {"date_fields": ["visit_date", "psa_date"], "max_age_days": 30},
    "testosterone": {"date_fields": ["visit_date", "testosterone_date"], "max_age_days": 30},
    "systolic_bp": {"date_fields": ["visit_date", "blood_pressure_date"], "max_age_days": 30},
    "fatigue_score": {"date_fields": ["visit_date"], "max_age_days": 30},
    "mini_cog_score": {"date_fields": ["visit_date"], "max_age_days": 30},
    "ast": {"date_fields": ["liver_panel_date", "visit_date"], "max_age_days": 14},
    "alt": {"date_fields": ["liver_panel_date", "visit_date"], "max_age_days": 14},
    "bilirubin": {"date_fields": ["liver_panel_date", "visit_date"], "max_age_days": 14},
    "alp": {"date_fields": ["liver_panel_date", "visit_date"], "max_age_days": 14},
    "potassium": {"date_fields": ["chemistry_panel_date", "visit_date"], "max_age_days": 14},
    "glucose": {"date_fields": ["chemistry_panel_date", "visit_date"], "max_age_days": 14},
    "cbc_date": {"date_fields": ["cbc_date"], "max_age_days": 14},
    "anc": {"date_fields": ["cbc_date", "visit_date"], "max_age_days": 14},
    "platelets": {"date_fields": ["cbc_date", "visit_date"], "max_age_days": 14},
    "hemoglobin": {"date_fields": ["cbc_date", "visit_date"], "max_age_days": 14},
    "renal_function": {"date_fields": ["renal_function_date", "visit_date"], "max_age_days": 14},
    "restaging_imaging_date": {"date_fields": ["restaging_imaging_date"], "max_age_days": 90},
    "psma_pet_date": {"date_fields": ["psma_pet_date"], "max_age_days": 90},
}


def _field_is_stale(field_name: str, field_values: dict[str, Any]) -> bool:
    rule = FIELD_RECENCY_RULES.get(field_name)
    if not rule:
        return False
    max_age_days = int(rule.get("max_age_days") or 0)
    for candidate in rule.get("date_fields") or []:
        candidate_date = _as_date(field_values.get(candidate))
        if candidate_date:
            return (date.today() - candidate_date).days > max_age_days
    return False


def _field_value_present(field_name: str, field_values: dict[str, Any]) -> bool:
    if _is_present(field_values.get(field_name)):
        return True
    aliases = {
        "blood_pressure": ["systolic_bp"],
        "ddi_review": ["ddi_review_status", "drug_interaction_reviewed"],
        "cognition": ["mini_cog_score"],
        "rash": ["dermatitis_history", "rash_grade"],
        "cbc": ["hemoglobin", "anc", "platelets"],
        "neuropathy_grade": ["peripheral_neuropathy_grade"],
        "pain_burden": ["bpi_worst_pain", "pain_score"],
        "symptom_burden": ["disease_status", "bpi_worst_pain", "fatigue_score"],
        "radiographic_response": ["conventional_imaging_status", "psma_stage_after_psma", "radiographic_progression_date"],
        "restaging_result": ["conventional_imaging_status", "psma_stage_after_psma", "psma_uptake_pattern"],
        "urinary_toxicity": ["gu_toxicity_grade", "pad_usage"],
        "bowel_toxicity": ["gi_toxicity_grade"],
        "site_control": ["local_toxicity_grade", "conventional_imaging_status"],
        "confirmatory_biopsy": ["confirmatory_biopsy_done", "confirmatory_biopsy_date"],
        "mpmri": ["mri_interval_months", "prior_mpmri_pirads_score", "pirads_score"],
        "pathology_review": ["clinical_tstage", "pathologic_stage_group"],
    }
    for alias in aliases.get(field_name, []):
        if _is_present(field_values.get(alias)):
            return True
    return False


def _hold_transition_for_family(family_code: str, field_values: dict[str, Any]) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    if family_code == "arpi_family":
        if (_safe_float(field_values.get("systolic_bp")) or 0) >= 180:
            evidence.append("Presion arterial severamente elevada bajo ARPI.")
        if (_safe_int(field_values.get("falls_recent")) or 0) >= 2:
            evidence.append("Caidas recurrentes documentadas bajo ARPI.")
        if (_safe_int(field_values.get("mini_cog_score")) or 99) <= 2:
            evidence.append("Declive cognitivo relevante durante ARPI.")
        if (_safe_int(field_values.get("rash_grade")) or 0) >= 3:
            evidence.append("Toxicidad cutanea grado alto bajo ARPI.")
    elif family_code == "abiraterone_steroid_family":
        if (_safe_float(field_values.get("potassium")) or 99) < 3.0:
            evidence.append("Hipokalemia significativa durante abiraterona.")
        if max(_safe_float(field_values.get("ast")) or 0, _safe_float(field_values.get("alt")) or 0) >= 250:
            evidence.append("Hepatotoxicidad significativa durante abiraterona.")
        if (_safe_int(field_values.get("edema_grade")) or 0) >= 3 or _coerce_bool(field_values.get("heart_failure_or_edema_risk")):
            evidence.append("Edema o riesgo cardiaco que obliga a pausar abiraterona.")
    elif family_code == "taxane_family":
        anc = _safe_float(field_values.get("anc"))
        if anc is not None and anc < 1.0:
            evidence.append("ANC por debajo de umbral seguro para taxano.")
        if _coerce_bool(field_values.get("febrile_neutropenia")):
            evidence.append("Neutropenia febril documentada.")
        if (_safe_int(field_values.get("peripheral_neuropathy_grade")) or 0) >= 3:
            evidence.append("Neuropatia periferica grado alto durante taxano.")
    elif family_code == "parp_family":
        hemoglobin = _safe_float(field_values.get("hemoglobin"))
        platelets = _safe_float(field_values.get("platelets"))
        if hemoglobin is not None and hemoglobin < 8:
            evidence.append("Anemia significativa bajo PARP.")
        if platelets is not None and platelets < 75000:
            evidence.append("Trombocitopenia significativa bajo PARP.")
        if (_safe_float(field_values.get("renal_function")) or 0) > 2.5:
            evidence.append("Deterioro renal que exige pausar PARP.")
    elif family_code == "psma_rlt_family":
        hemoglobin = _safe_float(field_values.get("hemoglobin"))
        platelets = _safe_float(field_values.get("platelets"))
        if hemoglobin is not None and hemoglobin < 8:
            evidence.append("Reserva medular insuficiente para continuar PSMA-RLT.")
        if platelets is not None and platelets < 75000:
            evidence.append("Plaquetas insuficientes para continuar PSMA-RLT.")
        if (_safe_float(field_values.get("renal_function")) or 0) > 2.5:
            evidence.append("Funcion renal comprometida para PSMA-RLT.")
    elif family_code == "radium223_family":
        if _coerce_bool(field_values.get("visceral_metastases_present")):
            evidence.append("Visceralidad dominante que saca al paciente de radio-223.")
        if (_safe_float(field_values.get("hemoglobin")) or 99) < 8:
            evidence.append("Reserva hematologica insuficiente para radio-223.")
    elif family_code == "immunotherapy_family":
        if (_safe_int(field_values.get("immune_toxicity_grade")) or 0) >= 3:
            evidence.append("irAE grado alto documentado.")
        if _coerce_bool(field_values.get("steroid_dependency")):
            evidence.append("Dependencia a esteroides que obliga a pausa inmunoterapica.")
    elif family_code in {"salvage_rt_family", "local_mdt_family"}:
        if (_safe_int(field_values.get("gu_toxicity_grade")) or 0) >= 3 or (_safe_int(field_values.get("gi_toxicity_grade")) or 0) >= 3:
            evidence.append("Toxicidad local grado alto que obliga a pausar la via local.")
        if family_code == "salvage_rt_family" and not _coerce_bool(field_values.get("salvage_local_feasible")) and _is_present(field_values.get("salvage_local_feasible")):
            evidence.append("La factibilidad local ya no esta demostrada.")
    return bool(evidence), evidence


def _progression_type(progression_pattern: str, field_values: dict[str, Any]) -> str:
    pattern = str(progression_pattern or field_values.get("progression_pattern") or "").strip().lower()
    if _coerce_bool(field_values.get("aggressive_variant")) or _coerce_bool(field_values.get("nepc_transform")):
        return "transformation_progression"
    if pattern in {"transformation", "nepc", "aggressive_variant"}:
        return "transformation_progression"
    if pattern in {"mixed", "mixto"}:
        return "mixed_progression"
    if pattern in {"radiographic", "radiographic_progression", "radiografica"}:
        return "radiographic_progression"
    if pattern in {"symptomatic", "symptomatic_progression", "clinica", "clinical"}:
        return "symptomatic_progression"
    if pattern in {"biochemical", "biochemical_only", "bioquimica"}:
        return "biochemical_progression"
    if _coerce_bool(field_values.get("radiographic_progression")) or _is_present(field_values.get("radiographic_progression_date")):
        return "radiographic_progression"
    if (_safe_int(field_values.get("bpi_worst_pain")) or 0) >= 7 and _coerce_bool(field_values.get("new_cancer_related_symptoms")):
        return "symptomatic_progression"
    return "none"


def build_active_regimen_monitoring_package(
    regimen_code: Any,
    *,
    family_code: str = "",
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_regimen_code(regimen_code)
    family_code = family_code or regimen_family_code(normalized)
    field_values = dict(field_values or {})
    template = deepcopy(MONITORING_TEMPLATES.get(family_code, MONITORING_TEMPLATES["observation_family"]))
    required_visit_fields = _dedupe(template.get("required_visit_fields") or [])
    missing_inputs = [field for field in required_visit_fields if not _field_value_present(field, field_values)]
    stale_inputs = [field for field in required_visit_fields if field not in missing_inputs and _field_is_stale(field, field_values)]
    template["family_code"] = family_code
    template["family_label"] = family_label(family_code)
    template["active_regimen_code"] = normalized
    template["active_regimen_label"] = regimen_label(normalized)
    template["required_visit_fields"] = required_visit_fields
    template["missing_inputs"] = missing_inputs
    template["stale_inputs"] = stale_inputs
    template["monitoring_focus"] = str(template.get("monitoring_focus") or family_label(family_code))
    template["recommended_cadence"] = str(template.get("recommended_cadence") or "")
    return template


def build_sequence_transition_bundle(
    *,
    state: str,
    preferred_regimen: dict[str, Any] | None,
    eligible_treatments: list[dict[str, Any]] | None,
    current_treatment: Any = "",
    missing_critical_inputs: list[str] | None = None,
    progression_pattern: str = "",
    line_context: str = "",
    field_values: dict[str, Any] | None = None,
    monitoring_package: dict[str, Any] | None = None,
    comparative_eligibility_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preferred_regimen = dict(preferred_regimen or {})
    eligible_treatments = list(eligible_treatments or [])
    missing_critical_inputs = list(dict.fromkeys(missing_critical_inputs or []))
    field_values = dict(field_values or {})
    monitoring_package = dict(monitoring_package or {})
    comparative_eligibility_matrix = dict(comparative_eligibility_matrix or {})
    active_code = str(preferred_regimen.get("regimen_code") or "")
    active_family = str(preferred_regimen.get("family_code") or regimen_family_code(active_code))
    current_regimen = normalize_regimen_code(current_treatment)
    if not active_code and current_regimen:
        active_code = current_regimen
        active_family = regimen_family_code(active_code)
    progression_type = _progression_type(progression_pattern, field_values)
    castrate_status = str(field_values.get("castrate_testosterone_status") or "").strip().lower()
    hold_due_to_toxicity, hold_evidence = _hold_transition_for_family(active_family, field_values)
    monitoring_missing = list(monitoring_package.get("missing_inputs") or [])
    monitoring_stale = list(monitoring_package.get("stale_inputs") or [])
    pending_inputs = _dedupe(missing_critical_inputs + monitoring_missing + monitoring_stale)
    systemic_redirect = False
    systemic_redirect_reasons: list[str] = []
    local_redirect_context = (
        active_family in {"salvage_rt_family", "local_mdt_family"}
        or state in {"recurrence_bcr", "post_radiotherapy_or_local_salvage"}
        or regimen_family_code(current_regimen, fallback="") in {"salvage_rt_family", "local_mdt_family"}
    )
    if local_redirect_context:
        psma_stage_after = str(field_values.get("psma_stage_after_psma") or "").strip().upper()
        psma_pattern = str(field_values.get("psma_uptake_pattern") or "").strip().lower()
        salvage_local_feasible = field_values.get("salvage_local_feasible")
        systemic_redirect = (
            psma_stage_after in {"M1B", "M1C"}
            or psma_pattern in {"diseminado", "widespread", "systemic"}
            or (_is_present(salvage_local_feasible) and not _coerce_bool(salvage_local_feasible))
        )
        if psma_stage_after in {"M1B", "M1C"}:
            systemic_redirect_reasons.append("La restadificacion ya documenta enfermedad sistemica incompatible con rescate local aislado.")
        if psma_pattern in {"diseminado", "widespread", "systemic"}:
            systemic_redirect_reasons.append("El patron de PSMA sugiere diseminacion y obliga a redirigir el carril.")
        if _is_present(salvage_local_feasible) and not _coerce_bool(salvage_local_feasible):
            systemic_redirect_reasons.append("La factibilidad local documentada ya no sostiene salvage con intencion curativa.")
    if progression_type == "transformation_progression":
        trigger_status = "redirect_systemic"
        line_change_reason = "La evidencia actual sugiere transformacion/aggressive variant y obliga a redirigir la secuencia."
        trigger_evidence = ["Transformacion/aggressive variant documentada o inferida."]
    elif hold_due_to_toxicity:
        trigger_status = "hold"
        line_change_reason = "La seguridad actual obliga a pausar el backbone activo antes de mantener o cambiar linea."
        trigger_evidence = hold_evidence
    elif systemic_redirect:
        trigger_status = "redirect_systemic"
        line_change_reason = systemic_redirect_reasons[0]
        trigger_evidence = systemic_redirect_reasons
    elif local_redirect_context and pending_inputs:
        trigger_status = "confirm"
        line_change_reason = "La via local sigue siendo la dominante, pero faltan datos de monitorizacion/restadificacion para cerrarla."
        trigger_evidence = pending_inputs
    elif local_redirect_context and current_regimen and current_regimen == active_code:
        trigger_status = "continue"
        line_change_reason = "La estrategia local preferente sigue activa y la ventana clinica permanece abierta."
        trigger_evidence = [line_change_reason]
    elif local_redirect_context:
        trigger_status = "redirect_local"
        line_change_reason = "La via local sigue siendo dominante y debe priorizarse por encima de una intensificacion sistemica equivalente."
        trigger_evidence = [line_change_reason]
    elif castrate_status == "not_castrate":
        trigger_status = "confirm"
        line_change_reason = "La progresion no debe secuenciarse como resistente a la castracion hasta confirmar testosterona en rango objetivo."
        trigger_evidence = ["La testosterona actual no confirma rango de castracion."]
    elif pending_inputs and not active_code:
        trigger_status = "confirm"
        line_change_reason = "Faltan datos críticos antes de cerrar una intensificación o un cambio de línea."
        trigger_evidence = pending_inputs
    elif progression_type in {"radiographic_progression", "symptomatic_progression", "mixed_progression"} and current_regimen and active_code and current_regimen == active_code:
        trigger_status = "switch"
        line_change_reason = "Existe progresion clinicamente relevante bajo el regimen activo y debe cambiarse o secuenciarse otra familia."
        trigger_evidence = [progression_type]
    elif current_regimen and current_regimen == active_code:
        trigger_status = "continue"
        line_change_reason = "El régimen preferente coincide con la estrategia ya activa."
        trigger_evidence = [line_change_reason]
    elif current_regimen and current_regimen != active_code:
        trigger_status = "switch"
        line_change_reason = "El régimen preferente ya no coincide con la exposición actual y debe reevaluarse el cambio de línea."
        trigger_evidence = [line_change_reason]
    else:
        trigger_status = "intensify"
        line_change_reason = "Existe una opción preferente mejor alineada que todavía no está activa."
        trigger_evidence = [line_change_reason]
    if pending_inputs and active_code and trigger_status in {"continue", "intensify", "switch"}:
        line_change_reason = (
            f"{line_change_reason} Persisten datos pendientes que deben cerrarse para consolidar seguridad y seguimiento."
        ).strip()
        trigger_evidence = _dedupe(trigger_evidence + pending_inputs)
    family_profile = dict(comparative_eligibility_matrix.get(active_family) or {})
    if family_profile and family_profile.get("eligibility_status") in {"conditional", "not_assessable"} and trigger_status == "continue":
        trigger_status = "confirm"
        line_change_reason = line_change_reason or "La familia activa sigue siendo la dominante, pero aun no esta completamente asegurada."
        trigger_evidence = _dedupe(trigger_evidence + list(family_profile.get("missing_inputs") or []) + list(family_profile.get("stale_inputs") or []))
    return {
        "current_state_family": state,
        "current_line_context": str(line_context or ""),
        "active_family": active_family,
        "active_regimen_code": active_code,
        "progression_type": progression_type,
        "trigger_status": trigger_status,
        "trigger_evidence": trigger_evidence,
        "line_change_reason": line_change_reason,
        "next_sequence_candidates": [str(item.get("regimen_code") or "") for item in eligible_treatments[:3]],
        "monitoring_package_key": active_family,
        "transition_confidence": "limitada" if pending_inputs else "vigilada" if hold_due_to_toxicity else "alta",
    }
