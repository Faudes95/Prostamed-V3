"""EPIC 43 — Inline stage-specific schemas para los 41 estados clínicos
que carecían de schema dedicado en _STAGE_SCHEMA_REGISTRY (fallback a
diagnostic_workup, perdiendo fidelidad clínica).

Estados cubiertos por cluster:
  · Risk-stratified localized (6): very_low/low/favorable_int/unfavorable_int/
    high/very_high_risk_localized — NCCN PROS-2/3/4/5 v2026
  · Post-local by modality (5): post_brachy_ldr/hdr, post_ebrt_alone,
    post_sbrt, post_focal_therapy — surveillance schedules distintos
  · Hereditary carriers (6+1 umbrella): brca1/brca2/atm/palb2/hoxb13/lynch
    + hereditary_germline_pathway_umbrella — NCCN PROS-A v2026
  · mCRPC subtypes (6): arsi_naive, post_arsi, hrr_positive_parp_naive,
    psma_eligible_lu177, msi_h_dmmr, nepc_differentiation — NCCN PROS-J
  · mCSPC refinements (3): latitude_high_risk, visceral_only_m1c,
    psma_only_metastatic
  · Oligometastatic (4): synchronous, metach_adt_naive,
    recurrent_post_definitive, oligo_progressive_on_therapy
  · Special populations (4): geriatric_frail_limited, young_onset_pca,
    comorbidity_cv, comorbidity_hepatic
  · Survivorship (3): post_curative_5y_plus, second_primary_surveillance,
    adt_long_term_complications
  · Pre-diagnostic (3): suspected_low_psa, suspected_elevated_psa_ww,
    negative_biopsy_age_lt_45
  · Post-RT BCR (1): post_rt_bcr

Diseño: cada estado tiene su builder function que retorna {module, title,
description, fields[]}. Fields organizados en grupos clínicos con
conditional_visibility para progressive disclosure. NO eliminamos campos
clínicos fundamentales (directiva usuario EPIC 42).

Refs: NCCN Prostate v5.2026, EAU 2026, AUA-SUO 2024.
"""
from __future__ import annotations

from typing import Any, Callable


# ─────────────────── Shared field templates (DRY) ───────────────────

def _psa_followup_fields(group: str = "PSA seguimiento", base_order: float = 1.0) -> list[dict]:
    """PSA follow-up: current value + sample date + nadir reference."""
    return [
        {"name": "current_psa", "label": "PSA actual (ng/mL)", "field_type": "number",
         "required": True, "unit": "ng/mL", "min_value": 0, "max_value": 5000,
         "group": group, "group_order": base_order, "clinical_role": "required",
         "help_text": "Valor PSA más reciente para evaluar progresión/respuesta"},
        {"name": "current_psa_date", "label": "Fecha PSA actual", "field_type": "date",
         "required": True, "group": group, "group_order": base_order,
         "clinical_role": "required"},
        {"name": "psa_nadir", "label": "PSA nadir documentado (ng/mL)", "field_type": "number",
         "required": False, "unit": "ng/mL", "min_value": 0,
         "group": group, "group_order": base_order, "clinical_role": "decision_refiner",
         "help_text": "Valor PSA más bajo alcanzado durante terapia previa"},
        {"name": "psa_nadir_date", "label": "Fecha PSA nadir", "field_type": "date",
         "required": False, "group": group, "group_order": base_order,
         "clinical_role": "decision_refiner"},
        {"name": "psadt_months", "label": "PSA doubling time (meses)", "field_type": "number",
         "required": False, "unit": "meses", "min_value": 0,
         "group": group, "group_order": base_order, "clinical_role": "decision_refiner",
         "help_text": "PSADT <6mo = high-risk recurrence; <10mo = SPARTAN/PROSPER/ARAMIS eligible"},
    ]


def _ecog_pros_baseline(group: str = "Performance + PROs", base_order: float = 2.0) -> list[dict]:
    """ECOG actual + PROs baseline (IPSS, IIEF-5, EPIC-26)."""
    return [
        {"name": "ecog_current", "label": "ECOG actual", "field_type": "select",
         "required": True, "options": ["0", "1", "2", "3", "4"], "default": "0",
         "group": group, "group_order": base_order, "clinical_role": "required",
         "help_text": "Performance status actual (Oken 1982 PMID 7165009)"},
        {"name": "ipss_total", "label": "IPSS (síntomas urinarios)", "field_type": "number",
         "required": False, "min_value": 0, "max_value": 35,
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
        {"name": "iief5_score", "label": "IIEF-5 (función eréctil)", "field_type": "number",
         "required": False, "min_value": 0, "max_value": 25,
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
        {"name": "epic26_urinary_domain", "label": "EPIC-26 urinary", "field_type": "number",
         "required": False, "min_value": 0, "max_value": 100,
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
        {"name": "epic26_sexual_domain", "label": "EPIC-26 sexual", "field_type": "number",
         "required": False, "min_value": 0, "max_value": 100,
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
    ]


def _ctcae_toxicity_fields(group: str = "Toxicidad CTCAE", base_order: float = 5.0) -> list[dict]:
    """CTCAE toxicity tracking — generic per visit."""
    return [
        {"name": "ctcae_terms_observed", "label": "Términos CTCAE observados (lista)",
         "field_type": "textarea", "required": False, "group": group, "group_order": base_order,
         "clinical_role": "monitoring",
         "help_text": "Ej: fatigue grade 2, hypertension grade 1, diarrhea grade 2"},
        {"name": "max_ctcae_grade_visit", "label": "Grado CTCAE máximo en visita",
         "field_type": "select", "required": False,
         "options": ["0", "1", "2", "3", "4", "5"], "default": "0",
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
        {"name": "toxicity_required_intervention", "label": "Requirió intervención por toxicidad",
         "field_type": "select", "required": False,
         "options": ["unknown", "none", "supportive_only", "dose_reduction", "dose_hold", "discontinuation"],
         "default": "unknown",
         "group": group, "group_order": base_order, "clinical_role": "monitoring"},
    ]


def _imaging_followup_fields(group: str = "Imaging seguimiento", base_order: float = 3.0,
                              include_psma: bool = True) -> list[dict]:
    fields = [
        {"name": "imaging_modality_at_followup", "label": "Modalidad imagen reciente",
         "field_type": "select", "required": False,
         "options": ["none", "ct_only", "bone_scan_only", "ct_bone_scan", "mpmri",
                     "psma_pet", "whole_body_mri", "fdg_pet"],
         "default": "none", "group": group, "group_order": base_order,
         "clinical_role": "decision_refiner"},
        {"name": "imaging_date_followup", "label": "Fecha imagen reciente", "field_type": "date",
         "required": False, "group": group, "group_order": base_order,
         "conditional_visibility": {"imaging_modality_at_followup":
            ["ct_only", "bone_scan_only", "ct_bone_scan", "mpmri", "psma_pet", "whole_body_mri", "fdg_pet"]}},
        {"name": "imaging_progression_documented", "label": "Progresión en imagen",
         "field_type": "select", "required": False,
         "options": ["unknown", "no_progression", "progression_documented", "indeterminate"],
         "default": "unknown", "group": group, "group_order": base_order,
         "clinical_role": "decision_refiner"},
    ]
    if include_psma:
        fields.extend([
            {"name": "psma_pet_status_recent", "label": "PSMA-PET status reciente",
             "field_type": "select", "required": False,
             "options": ["unknown", "not_performed", "negative", "positive_oligometastatic",
                         "positive_metastatic", "positive_local_recurrence"],
             "default": "unknown", "group": group, "group_order": base_order,
             "clinical_role": "decision_refiner"},
        ])
    return fields


def _treatment_modification_fields(group: str = "Modificación tratamiento", base_order: float = 6.0) -> list[dict]:
    return [
        {"name": "treatment_modification_planned", "label": "Modificación planeada",
         "field_type": "select", "required": False,
         "options": ["continue_current", "dose_reduction", "switch_within_class",
                     "switch_class", "add_combination", "discontinue", "transition_palliative"],
         "default": "continue_current",
         "group": group, "group_order": base_order, "clinical_role": "decision_refiner"},
        {"name": "modification_rationale", "label": "Razón clínica de modificación",
         "field_type": "textarea", "required": False,
         "group": group, "group_order": base_order, "clinical_role": "decision_refiner"},
    ]


def _hereditary_counseling_fields(group: str = "Counseling genético", base_order: float = 7.0) -> list[dict]:
    return [
        {"name": "genetic_counseling_provided", "label": "Counseling genético provisto",
         "field_type": "select", "required": True,
         "options": ["unknown", "0", "1", "scheduled"], "default": "unknown",
         "group": group, "group_order": base_order, "clinical_role": "required"},
        {"name": "genetic_counseling_date", "label": "Fecha counseling", "field_type": "date",
         "required": False, "group": group, "group_order": base_order,
         "conditional_visibility": {"genetic_counseling_provided": ["1"]}},
        {"name": "family_cascade_testing_status", "label": "Cascade testing familiar",
         "field_type": "select", "required": False,
         "options": ["unknown", "not_initiated", "discussed", "in_progress", "completed_partial",
                     "completed_full", "declined_by_family"],
         "default": "unknown", "group": group, "group_order": base_order,
         "clinical_role": "decision_refiner",
         "help_text": "60% prob hijos heredan BRCA2/lynch — counseling familiar fundamental"},
        {"name": "intensified_surveillance_initiated", "label": "Vigilancia intensificada iniciada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": group, "group_order": base_order,
         "help_text": "PSA q6mo + MRI annual desde 40y para carriers"},
    ]


def _bone_health_monitoring_fields(group: str = "Salud ósea", base_order: float = 8.0) -> list[dict]:
    return [
        {"name": "bone_protective_agent_current", "label": "Agente protector óseo actual",
         "field_type": "select", "required": False,
         "options": ["none", "zoledronic_acid", "denosumab", "alendronate", "other_bisphosphonate"],
         "default": "none",
         "group": group, "group_order": base_order, "clinical_role": "decision_refiner"},
        {"name": "dexa_recent_t_score", "label": "DEXA T-score más reciente", "field_type": "number",
         "required": False, "min_value": -5, "max_value": 5,
         "group": group, "group_order": base_order, "clinical_role": "monitoring",
         "help_text": "T <-2.5 = osteoporosis → indicación bone-protective"},
        {"name": "skeletal_related_event_documented", "label": "SRE documentado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": group, "group_order": base_order, "clinical_role": "monitoring",
         "help_text": "Fractura patológica, compresión medular, RT antalgica, cirugía ósea"},
    ]


def _common_meta(state: str, title: str, description: str) -> dict[str, Any]:
    return {
        "module": f"{state}_inline",
        "title": title,
        "description": description,
        "state": state,
    }


# ─────────────────── Risk-stratified localized (6 states) ───────────────────

def schema_very_low_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "very_low_risk_localized",
        "Very-low-risk localized — Active Surveillance (NCCN PROS-3 v2026)",
        "AS strongly preferred. Discriminadores: PSA<10 + GS6 + cT1c + <34% positive cores + density<0.15.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields("AS monitoring (PSA q6mo)", 1.0),
        {"name": "as_repeat_biopsy_done", "label": "Biopsia confirmatoria realizada",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "AS confirmatoria", "group_order": 2,
         "clinical_role": "required",
         "help_text": "NCCN: biopsia confirmatoria a 6-12 meses del diagnóstico"},
        {"name": "as_repeat_biopsy_date", "label": "Fecha biopsia confirmatoria", "field_type": "date",
         "required": False, "group": "AS confirmatoria", "group_order": 2,
         "conditional_visibility": {"as_repeat_biopsy_done": ["1"]}},
        {"name": "as_repeat_biopsy_gleason_max", "label": "Gleason máximo biopsia confirmatoria",
         "field_type": "select", "required": False, "options": ["", "6", "7", "8", "9", "10"],
         "default": "", "group": "AS confirmatoria", "group_order": 2,
         "conditional_visibility": {"as_repeat_biopsy_done": ["1"]},
         "help_text": "Upgrade a GS≥7 = salida de AS, considerar treatment"},
        {"name": "mpmri_annual_done", "label": "mpMRI anual realizada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "AS confirmatoria", "group_order": 2},
        {"name": "as_trigger_for_treatment", "label": "Trigger para salir de AS",
         "field_type": "select", "required": False,
         "options": ["none", "psa_acceleration", "grade_upgrade", "imaging_progression",
                     "patient_anxiety_preference", "extracapsular_extension"],
         "default": "none", "group": "AS decisión", "group_order": 3,
         "clinical_role": "decision_refiner"},
        *_ecog_pros_baseline(),
        {"name": "patient_anxiety_about_as", "label": "Ansiedad del paciente respecto AS",
         "field_type": "select", "required": False,
         "options": ["unknown", "low", "moderate", "high"], "default": "unknown",
         "group": "Preferencias paciente", "group_order": 4, "clinical_role": "decision_refiner",
         "help_text": "Ansiedad alta sostenida = razón válida para salir de AS"},
    ]}


def schema_low_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "low_risk_localized",
        "Low-risk localized — AS preferred / Tx acceptable (NCCN PROS-3)",
        "AS preferida; RP/EBRT/brachy aceptables según preferencia paciente y life expectancy.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "treatment_path_selected", "label": "Vía terapéutica seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending_decision", "active_surveillance", "radical_prostatectomy",
                     "ebrt_external_beam", "brachytherapy_ldr", "brachytherapy_hdr", "focal_therapy"],
         "default": "pending_decision",
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "required"},
        {"name": "decision_aid_used", "label": "Decision aid utilizado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "Decisión terapéutica", "group_order": 2,
         "clinical_role": "decision_refiner"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
    ]}


def schema_favorable_intermediate_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "favorable_intermediate_risk_localized",
        "Favorable intermediate-risk localized (NCCN PROS-4)",
        "Discriminadores: PSA 10-20 OR cT2b OR GS 3+4=7 con <50% cores GS≥4. AS aceptable o tx; patient choice driven.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "percent_pattern_4_confirmed", "label": "% patrón 4 confirmado",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 100, "unit": "%",
         "group": "Discriminadores fav-int", "group_order": 2, "clinical_role": "required",
         "help_text": "<50% = favorable_intermediate; ≥50% = unfavorable_intermediate"},
        {"name": "mri_decipher_done", "label": "Decipher / Prolaris result",
         "field_type": "select", "required": False,
         "options": ["", "decipher_low", "decipher_intermediate", "decipher_high"],
         "default": "", "group": "Discriminadores fav-int", "group_order": 2,
         "clinical_role": "decision_refiner"},
        {"name": "treatment_path_selected", "label": "Vía terapéutica seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending_decision", "active_surveillance_selective", "radical_prostatectomy_eplnd",
                     "ebrt_short_adt_4_6mo", "brachytherapy_monotherapy", "ebrt_brachy_boost"],
         "default": "pending_decision",
         "group": "Decisión terapéutica", "group_order": 3, "clinical_role": "required"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
    ]}


def schema_unfavorable_intermediate_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "unfavorable_intermediate_risk_localized",
        "Unfavorable intermediate-risk localized (NCCN PROS-4)",
        "Tx recomendado. RP+ePLND OR EBRT+ADT 4-6m. No AS.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "treatment_path_selected", "label": "Vía terapéutica seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending_decision", "radical_prostatectomy_eplnd",
                     "ebrt_plus_adt_4_6mo", "brachytherapy_boost_plus_ebrt_adt"],
         "default": "pending_decision",
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "required"},
        {"name": "adt_planned_duration_months", "label": "Duración ADT planeada (meses)",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 60,
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "decision_refiner",
         "conditional_visibility": {"treatment_path_selected":
            ["ebrt_plus_adt_4_6mo", "brachytherapy_boost_plus_ebrt_adt"]}},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
        *_bone_health_monitoring_fields(),
    ]}


def schema_high_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "high_risk_localized",
        "High-risk localized — EBRT+ADT 18-36m OR RP+ePLND (NCCN PROS-5)",
        "GS 8-10 OR PSA>20 OR cT2c-T3a. Triple modality consideration.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "treatment_path_selected", "label": "Vía terapéutica seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending_decision", "ebrt_plus_adt_18_36mo",
                     "ebrt_plus_brachy_boost_plus_adt", "radical_prostatectomy_eplnd_adjuvant"],
         "default": "pending_decision",
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "required"},
        {"name": "adt_planned_duration_months", "label": "Duración ADT planeada (meses)",
         "field_type": "number", "required": True, "min_value": 6, "max_value": 36, "default": 24,
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "required",
         "help_text": "NCCN: 18-36m para high-risk"},
        {"name": "ppi_arpi_intensification", "label": "Intensificación con ARPI (apalutamida/enzalutamida)",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "decision_refiner",
         "help_text": "ATLAS/PEACE-1 = ARPI added to ADT en algunos high-risk"},
        {"name": "germline_testing_universal_done", "label": "Germline testing (NCCN PROS-A universal)",
         "field_type": "select", "required": True,
         "options": ["unknown", "0", "1", "pending"], "default": "unknown",
         "group": "Genética molecular", "group_order": 3, "clinical_role": "required"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
        *_bone_health_monitoring_fields(),
    ]}


def schema_very_high_risk_localized() -> dict[str, Any]:
    meta = _common_meta(
        "very_high_risk_localized",
        "Very-high-risk localized — EBRT+brachy+ADT 2-3y o triple modality (NCCN PROS-5)",
        "cT3b-T4 OR primary GS 5 OR ≥2 high-risk features. Multidisciplinario obligatorio.",
    )
    fields = schema_high_risk_localized()["fields"]
    extras = [
        {"name": "multidisciplinary_review_completed", "label": "Revisión multidisciplinaria completada",
         "field_type": "select", "required": True, "options": ["0", "1", "pending"], "default": "pending",
         "group": "Multidisciplinario", "group_order": 0.5, "clinical_role": "required",
         "help_text": "MDT obligatorio en very-high-risk (urología + onco-radiología + medical onc)"},
        {"name": "triple_modality_considered", "label": "Triple modality considerada (cirugía + RT + ADT)",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Decisión terapéutica", "group_order": 2, "clinical_role": "decision_refiner"},
    ]
    return {**meta, "fields": extras + fields}


# ─────────────────── Post-local by modality (5 states) ───────────────────

def schema_post_brachy_ldr() -> dict[str, Any]:
    meta = _common_meta(
        "post_brachy_ldr",
        "Post-brachytherapy LDR — surveillance + bounce monitoring",
        "PSA bounce 18-36m common. Phoenix criterion = nadir+2 (after bounce excluded).",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "implant_date", "label": "Fecha implante", "field_type": "date",
         "required": True, "group": "Implante", "group_order": 0.5, "clinical_role": "required"},
        {"name": "psa_bounce_documented", "label": "PSA bounce documentado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Bounce monitoring", "group_order": 2, "clinical_role": "decision_refiner",
         "help_text": "Bounce típico 18-36m post-implante; NO es falla bioquímica"},
        {"name": "phoenix_bcr_criterion_met", "label": "Phoenix BCR (nadir+2) cumplido",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "BCR evaluation", "group_order": 3, "clinical_role": "decision_refiner"},
        {"name": "rectal_toxicity_late_grade", "label": "Toxicidad rectal tardía CTCAE",
         "field_type": "select", "required": False,
         "options": ["0", "1", "2", "3", "4"], "default": "0",
         "group": "Toxicidad tardía", "group_order": 4, "clinical_role": "monitoring"},
        {"name": "urinary_toxicity_late_grade", "label": "Toxicidad urinaria tardía CTCAE",
         "field_type": "select", "required": False,
         "options": ["0", "1", "2", "3", "4"], "default": "0",
         "group": "Toxicidad tardía", "group_order": 4, "clinical_role": "monitoring"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(include_psma=False),
    ]}


def schema_post_brachy_hdr() -> dict[str, Any]:
    s = schema_post_brachy_ldr()
    s["state"] = "post_brachy_hdr"
    s["module"] = "post_brachy_hdr_inline"
    s["title"] = "Post-brachytherapy HDR — surveillance"
    s["description"] = "HDR-specific nadir slower; similar surveillance pattern."
    return s


def schema_post_ebrt_alone() -> dict[str, Any]:
    meta = _common_meta(
        "post_ebrt_alone",
        "Post-EBRT alone — surveillance Phoenix criterion",
        "Phoenix BCR = nadir + 2 ng/mL (ASTRO 2007 consensus).",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "rt_completion_date", "label": "Fecha finalización RT",
         "field_type": "date", "required": True,
         "group": "RT contexto", "group_order": 0.5, "clinical_role": "required"},
        {"name": "rt_total_dose_gy", "label": "Dosis total RT (Gy)",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 100,
         "unit": "Gy", "group": "RT contexto", "group_order": 0.5,
         "clinical_role": "decision_refiner"},
        {"name": "phoenix_bcr_criterion_met", "label": "Phoenix BCR (nadir+2) cumplido",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "BCR evaluation", "group_order": 3, "clinical_role": "decision_refiner"},
        {"name": "rectal_toxicity_late_grade", "label": "Toxicidad rectal tardía CTCAE",
         "field_type": "select", "required": False, "options": ["0", "1", "2", "3", "4"],
         "default": "0", "group": "Toxicidad tardía", "group_order": 4,
         "clinical_role": "monitoring"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(include_psma=False),
    ]}


def schema_post_sbrt() -> dict[str, Any]:
    s = schema_post_ebrt_alone()
    s["state"] = "post_sbrt"
    s["module"] = "post_sbrt_inline"
    s["title"] = "Post-SBRT — surveillance + late toxicity"
    s["description"] = "SBRT typically 5 fractions, faster nadir."
    return s


def schema_post_focal_therapy() -> dict[str, Any]:
    meta = _common_meta(
        "post_focal_therapy",
        "Post-focal therapy (HIFU/cryo/IRE) — surveillance",
        "Residual disease MRI follow-up, biopsy in-field 6-12m.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "focal_modality", "label": "Modalidad focal",
         "field_type": "select", "required": True,
         "options": ["unknown", "hifu", "cryotherapy", "irreversible_electroporation",
                     "tulsa", "vascular_targeted_photodynamic"],
         "default": "unknown",
         "group": "Modalidad focal", "group_order": 0.5, "clinical_role": "required"},
        {"name": "focal_treatment_date", "label": "Fecha tratamiento focal",
         "field_type": "date", "required": True, "group": "Modalidad focal", "group_order": 0.5,
         "clinical_role": "required"},
        {"name": "mri_followup_6_12mo_done", "label": "MRI 6-12mo realizada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Surveillance", "group_order": 2, "clinical_role": "decision_refiner"},
        {"name": "in_field_biopsy_done", "label": "Biopsia in-field realizada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Surveillance", "group_order": 2, "clinical_role": "decision_refiner"},
        {"name": "out_field_progression_documented", "label": "Progresión out-of-field documentada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Surveillance", "group_order": 2, "clinical_role": "decision_refiner"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
    ]}


# ─────────────────── Hereditary carriers (7 states) ───────────────────

def _carrier_base(state: str, gene: str, description: str) -> dict[str, Any]:
    meta = _common_meta(state, f"{gene} carrier — surveillance intensificada + counseling familiar", description)
    return {**meta, "fields": [
        {"name": "germline_test_date", "label": "Fecha test germline", "field_type": "date",
         "required": True, "group": "Germline", "group_order": 1, "clinical_role": "required"},
        {"name": "germline_test_laboratory", "label": "Laboratorio (Invitae, Myriad, GeneDx, otro)",
         "field_type": "text", "required": False, "group": "Germline", "group_order": 1},
        {"name": "specific_variant", "label": "Variante específica (cDNA + protein)",
         "field_type": "text", "required": False, "group": "Germline", "group_order": 1,
         "clinical_role": "decision_refiner",
         "help_text": "Ej: c.5946delT (p.Ser1982fs)"},
        *_hereditary_counseling_fields(),
        *_psa_followup_fields("PSA surveillance intensificada", 4.0),
        *_ecog_pros_baseline(group="Status clínico", base_order=5.0),
    ]}


def schema_brca2_carrier() -> dict[str, Any]:
    s = _carrier_base("brca2_carrier", "BRCA2",
        "PARP first-line elegibilidad. Mayor riesgo CA mama familiar. NCCN PROS-A v2026.")
    s["fields"].extend([
        {"name": "parp_eligibility_evaluated", "label": "Elegibilidad PARP evaluada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "Targeted therapy", "group_order": 6,
         "clinical_role": "decision_refiner"},
        {"name": "parp_inhibitor_initiated", "label": "PARP inhibidor iniciado",
         "field_type": "select", "required": False,
         "options": ["none", "olaparib", "rucaparib", "talazoparib", "niraparib"],
         "default": "none", "group": "Targeted therapy", "group_order": 6,
         "clinical_role": "decision_refiner"},
    ])
    return s


def schema_brca1_carrier() -> dict[str, Any]:
    return _carrier_base("brca1_carrier", "BRCA1",
        "Menos común que BRCA2 en CA próstata; PARP response variable.")


def schema_atm_carrier() -> dict[str, Any]:
    return _carrier_base("atm_carrier", "ATM",
        "PARP response variable; considerar trial. Riesgo CA leucemia familiar.")


def schema_palb2_carrier() -> dict[str, Any]:
    return _carrier_base("palb2_carrier", "PALB2",
        "PARP-eligible. Surveillance familiar (mama).")


def schema_hoxb13_carrier() -> dict[str, Any]:
    return _carrier_base("hoxb13_carrier", "HOXB13 (G84E)",
        "Surveillance intensificada desde 40y. NO confiere PARP eligibility.")


def schema_lynch_carrier() -> dict[str, Any]:
    s = _carrier_base("lynch_carrier", "Lynch syndrome (MLH1/MSH2/MSH6/PMS2)",
        "Pembrolizumab eligibility (MSI-H/dMMR). Surveillance colon + endometrio familiar.")
    s["fields"].extend([
        {"name": "msi_status_tumor", "label": "MSI status del tumor", "field_type": "select",
         "required": False, "options": ["unknown", "stable", "high", "indeterminate"],
         "default": "unknown", "group": "Tumor molecular", "group_order": 6,
         "clinical_role": "decision_refiner"},
        {"name": "pembrolizumab_evaluated", "label": "Pembrolizumab evaluado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "Targeted therapy", "group_order": 7,
         "clinical_role": "decision_refiner",
         "help_text": "KEYNOTE-199 — MSI-H/dMMR → pembrolizumab cohort"},
        {"name": "colonoscopy_screening_status", "label": "Screening colonoscopy familiar",
         "field_type": "select", "required": False,
         "options": ["unknown", "current", "overdue", "not_applicable"],
         "default": "unknown", "group": "Cancer screening familiar", "group_order": 8},
    ])
    return s


def schema_hereditary_germline_pathway_umbrella() -> dict[str, Any]:
    meta = _common_meta(
        "hereditary_germline_pathway_umbrella",
        "Hereditary germline umbrella — NCCN PROS-A v2026 universal testing",
        "Testing germline universal en PCa avanzado/metastásico/high-risk familiar.",
    )
    return {**meta, "fields": [
        {"name": "germline_testing_ordered", "label": "Germline testing ordenado",
         "field_type": "select", "required": True,
         "options": ["unknown", "0", "1", "pending_result"], "default": "unknown",
         "group": "Germline", "group_order": 1, "clinical_role": "required"},
        {"name": "germline_panel_used", "label": "Panel utilizado",
         "field_type": "select", "required": False,
         "options": ["unknown", "Invitae_HBOC", "Myriad_myRisk", "GeneDx", "ColorHealth", "other"],
         "default": "unknown", "group": "Germline", "group_order": 1},
        {"name": "germline_result_summary", "label": "Resultado germline",
         "field_type": "select", "required": False,
         "options": ["pending", "negative", "vus_only", "pathogenic_brca1", "pathogenic_brca2",
                     "pathogenic_atm", "pathogenic_palb2", "pathogenic_chek2", "pathogenic_cdk12",
                     "pathogenic_hoxb13", "pathogenic_lynch", "pathogenic_other"],
         "default": "pending", "group": "Germline", "group_order": 1,
         "clinical_role": "decision_refiner"},
        *_hereditary_counseling_fields(),
        *_psa_followup_fields("PSA + surveillance", 4.0),
    ]}


# ─────────────────── mCRPC subtypes (6 states) ───────────────────

def _mcrpc_base(state: str, title: str, description: str) -> dict[str, Any]:
    meta = _common_meta(state, title, description)
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "testosterone_value_current", "label": "Testosterona actual (ng/dL)",
         "field_type": "number", "required": True, "unit": "ng/dL",
         "min_value": 0, "max_value": 2000,
         "group": "Castration verification", "group_order": 0.5, "clinical_role": "required",
         "help_text": "Confirmar <50 ng/dL (NCCN PROS-N1)"},
        {"name": "testosterone_sample_date", "label": "Fecha testosterona",
         "field_type": "date", "required": True,
         "group": "Castration verification", "group_order": 0.5, "clinical_role": "required"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
        *_ctcae_toxicity_fields(),
        *_treatment_modification_fields(),
        *_bone_health_monitoring_fields(),
    ]}


def schema_mcrpc_arsi_naive() -> dict[str, Any]:
    s = _mcrpc_base("mcrpc_arsi_naive",
        "mCRPC ARSI-naïve — first-line ARPI elegible (NCCN PROS-J)",
        "Sin ARSI previa en mCSPC. Opciones: abi/enza/apa/daro.")
    s["fields"].extend([
        {"name": "arpi_first_line_choice", "label": "ARPI first-line seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending", "abiraterone", "enzalutamide", "apalutamide", "darolutamide"],
         "default": "pending",
         "group": "ARPI decisión", "group_order": 7, "clinical_role": "required",
         "help_text": "Drug-selection by comorbidity profile (CV→enza/apa, hepatic→enza/apa, cognitive→abi/daro)"},
    ])
    return s


def schema_mcrpc_post_arsi() -> dict[str, Any]:
    s = _mcrpc_base("mcrpc_post_arsi",
        "mCRPC post-ARPI — cross-resistance considerations",
        "Cross-resistance ~80% entre abi↔enza. Considerar: cabazitaxel, PARP si HRR+, Lu-177 si PSMA+.")
    s["fields"].extend([
        {"name": "prior_arpi_class", "label": "Clase ARPI previa",
         "field_type": "select", "required": True,
         "options": ["pending", "abi_then_other", "enza_then_other", "apa_then_other",
                     "daro_then_other", "multiple_classes"],
         "default": "pending",
         "group": "ARPI historia", "group_order": 7, "clinical_role": "required"},
        {"name": "next_line_choice", "label": "Siguiente línea seleccionada",
         "field_type": "select", "required": True,
         "options": ["pending", "cabazitaxel", "lu177_psma617", "olaparib", "rucaparib",
                     "pembrolizumab_if_msi", "platinum_if_avpc", "rechallenge_arpi", "trial_enrollment"],
         "default": "pending",
         "group": "Next line", "group_order": 8, "clinical_role": "required"},
        {"name": "hrr_status_confirmed", "label": "HRR status confirmado",
         "field_type": "select", "required": False,
         "options": ["unknown", "negative", "positive", "pending"], "default": "unknown",
         "group": "Targeted eligibility", "group_order": 9, "clinical_role": "decision_refiner"},
        {"name": "psma_pet_done_post_arsi", "label": "PSMA-PET realizada post-progresión",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Targeted eligibility", "group_order": 9, "clinical_role": "decision_refiner",
         "help_text": "VISION eligibility requires PSMA+"},
    ])
    return s


def schema_mcrpc_hrr_positive_parp_naive() -> dict[str, Any]:
    s = _mcrpc_base("mcrpc_hrr_positive_parp_naive",
        "mCRPC HRR+ PARP-naïve — PROfound/MAGNITUDE eligible",
        "BRCA1/2 + ATM = HRR+ con PARP first-line evidencia robusta.")
    s["fields"].extend([
        {"name": "hrr_gene_specific", "label": "Gen HRR específico",
         "field_type": "select", "required": True,
         "options": ["pending", "BRCA2", "BRCA1", "ATM", "PALB2", "CDK12", "CHEK2", "FANCA",
                     "RAD51B", "RAD51C", "RAD51D", "BARD1", "OTHER_HRR"],
         "default": "pending",
         "group": "HRR detalle", "group_order": 7, "clinical_role": "required"},
        {"name": "biomarker_source_germline_or_somatic", "label": "Fuente biomarcador",
         "field_type": "select", "required": True,
         "options": ["pending", "germline", "somatic_tumor", "ctdna", "both_germline_somatic"],
         "default": "pending",
         "group": "HRR detalle", "group_order": 7, "clinical_role": "required",
         "help_text": "Germline → cascade testing familiar; somatic → screen germline anyway"},
        {"name": "parp_initiated", "label": "PARP inhibidor iniciado",
         "field_type": "select", "required": False,
         "options": ["pending", "olaparib", "rucaparib", "talazoparib", "niraparib", "deferred"],
         "default": "pending",
         "group": "PARP terapia", "group_order": 8, "clinical_role": "required"},
        {"name": "hemoglobin_baseline_parp", "label": "Hemoglobina baseline pre-PARP",
         "field_type": "number", "required": False, "unit": "g/dL", "min_value": 5, "max_value": 20,
         "group": "PARP safety monitoring", "group_order": 9, "clinical_role": "monitoring"},
        {"name": "platelet_baseline_parp", "label": "Plaquetas baseline (×10⁹/L)",
         "field_type": "number", "required": False, "min_value": 50, "max_value": 700,
         "group": "PARP safety monitoring", "group_order": 9, "clinical_role": "monitoring"},
    ])
    return s


def schema_mcrpc_psma_eligible_lu177() -> dict[str, Any]:
    s = _mcrpc_base("mcrpc_psma_eligible_lu177",
        "mCRPC PSMA+ Lu-177 eligible — VISION/PSMAfore",
        "Sartor NEJM 2021 PMID 34161051 (VISION) + Sartor ASCO 2024 (PSMAfore).")
    s["fields"].extend([
        {"name": "psma_pet_status", "label": "PSMA-PET status",
         "field_type": "select", "required": True,
         "options": ["pending", "positive_oligometastatic", "positive_metastatic",
                     "positive_local_recurrence", "negative"],
         "default": "pending",
         "group": "PSMA evaluation", "group_order": 7, "clinical_role": "required"},
        {"name": "psma_index_lesion_suvmax", "label": "SUVmax lesión índice",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 200,
         "group": "PSMA evaluation", "group_order": 7, "clinical_role": "decision_refiner"},
        {"name": "gfr_baseline_lu177", "label": "GFR baseline (mL/min/1.73m²)",
         "field_type": "number", "required": True, "min_value": 0, "max_value": 200,
         "unit": "mL/min/1.73m²",
         "group": "Lu-177 safety", "group_order": 8, "clinical_role": "required",
         "help_text": "GFR <50 = contraindica Lu-177 PSMA"},
        {"name": "salivary_gland_baseline_function", "label": "Función salival baseline",
         "field_type": "select", "required": False,
         "options": ["unknown", "normal", "mild_dryness", "moderate_dryness", "severe_dryness"],
         "default": "unknown",
         "group": "Lu-177 safety", "group_order": 8, "clinical_role": "monitoring",
         "help_text": "Lu-177 causa xerostomía dose-dependent"},
        {"name": "lu177_cycle_count", "label": "Ciclos Lu-177 administrados",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 8, "default": 0,
         "group": "Lu-177 administración", "group_order": 9, "clinical_role": "monitoring"},
    ])
    return s


def schema_mcrpc_msi_h_dmmr() -> dict[str, Any]:
    s = _mcrpc_base("mcrpc_msi_h_dmmr",
        "mCRPC MSI-H/dMMR — pembrolizumab eligible (KEYNOTE-199)",
        "MSI-high o dMMR = pembrolizumab 200mg q3wk. Mejor durabilidad de respuesta en mCRPC.")
    s["fields"].extend([
        {"name": "msi_test_method", "label": "Método test MSI",
         "field_type": "select", "required": True,
         "options": ["pending", "ihc_mmr", "pcr_msi", "ngs_panel", "ctdna_msi"],
         "default": "pending",
         "group": "MSI testing", "group_order": 7, "clinical_role": "required"},
        {"name": "dmmr_status", "label": "dMMR status",
         "field_type": "select", "required": False,
         "options": ["unknown", "proficient", "deficient", "indeterminate"],
         "default": "unknown",
         "group": "MSI testing", "group_order": 7, "clinical_role": "decision_refiner"},
        {"name": "tumor_mutational_burden", "label": "TMB (mutations/Mb)",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 200,
         "unit": "mut/Mb",
         "group": "MSI testing", "group_order": 7, "clinical_role": "decision_refiner",
         "help_text": "TMB ≥10 mut/Mb = TMB-high (pembro candidate)"},
        {"name": "pembrolizumab_initiated", "label": "Pembrolizumab iniciado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Immunotherapy", "group_order": 8, "clinical_role": "required"},
    ])
    return s


def schema_nepc_differentiation() -> dict[str, Any]:
    s = _mcrpc_base("nepc_differentiation",
        "Neuroendocrine prostate cancer (NEPC) — platinum-based therapy",
        "De novo OR treatment-emergent. NO responde a ARSI. Platino+topo recomendado.")
    s["fields"].extend([
        {"name": "nepc_confirmed_histology", "label": "NEPC confirmado por histología",
         "field_type": "select", "required": True,
         "options": ["pending", "0", "1", "suspected_only"], "default": "pending",
         "group": "NEPC confirmación", "group_order": 7, "clinical_role": "required"},
        {"name": "small_cell_morphology", "label": "Morfología small cell",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "NEPC confirmación", "group_order": 7, "clinical_role": "decision_refiner"},
        {"name": "chromogranin_a_value", "label": "Cromogranina A (ng/mL)",
         "field_type": "number", "required": False, "unit": "ng/mL", "min_value": 0,
         "group": "NEPC marcadores", "group_order": 8, "clinical_role": "decision_refiner"},
        {"name": "synaptophysin_positive", "label": "Sinaptofisina positiva",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "NEPC marcadores", "group_order": 8, "clinical_role": "decision_refiner"},
        {"name": "nse_value", "label": "NSE (Enolasa Neuroespecífica)",
         "field_type": "number", "required": False, "unit": "ng/mL", "min_value": 0,
         "group": "NEPC marcadores", "group_order": 8, "clinical_role": "decision_refiner"},
        {"name": "platinum_regimen", "label": "Regimen platino-basado",
         "field_type": "select", "required": False,
         "options": ["pending", "carboplatin_etoposide", "cisplatin_etoposide",
                     "platinum_taxane", "other"],
         "default": "pending",
         "group": "NEPC tratamiento", "group_order": 9, "clinical_role": "required"},
    ])
    return s


# ─────────────────── mCSPC refinements (3 states) ───────────────────

def _mcspc_base(state: str, title: str, description: str) -> dict[str, Any]:
    meta = _common_meta(state, title, description)
    return {**meta, "fields": [
        *_psa_followup_fields("PSA response a ADT", 1.0),
        *_ecog_pros_baseline(),
        {"name": "adt_start_date", "label": "Fecha inicio ADT",
         "field_type": "date", "required": True,
         "group": "ADT contexto", "group_order": 0.5, "clinical_role": "required"},
        {"name": "intensification_class", "label": "Clase de intensificación",
         "field_type": "select", "required": True,
         "options": ["pending", "adt_alone", "adt_plus_arpi_doublet",
                     "adt_plus_docetaxel_doublet", "adt_plus_arpi_plus_docetaxel_triplet"],
         "default": "pending",
         "group": "Intensificación", "group_order": 7, "clinical_role": "required",
         "help_text": "ARASENS triplet en HV mCSPC; PEACE-1 en de novo mCSPC HV"},
        *_imaging_followup_fields(),
        *_ctcae_toxicity_fields(),
        *_bone_health_monitoring_fields(),
    ]}


def schema_mcspc_latitude_high_risk() -> dict[str, Any]:
    s = _mcspc_base("mcspc_latitude_high_risk",
        "mCSPC LATITUDE high-risk — abiraterone eligible",
        "≥2 de 3: GS≥8, ≥3 bone lesions, viscerales. LATITUDE permite abi aunque NO HV CHAARTED.")
    s["fields"].extend([
        {"name": "latitude_criteria_count", "label": "Criterios LATITUDE cumplidos (0-3)",
         "field_type": "number", "required": True, "min_value": 0, "max_value": 3, "default": 0,
         "group": "LATITUDE criteria", "group_order": 0.7, "clinical_role": "required",
         "help_text": "Cuenta: GS≥8, ≥3 bone, viscerales"},
    ])
    return s


def schema_mcspc_visceral_only_m1c() -> dict[str, Any]:
    s = _mcspc_base("mcspc_visceral_only_m1c",
        "mCSPC visceral only M1c — chemo intensification frecuente",
        "Visceral mets = peor pronóstico. ARASENS regimen (daro+docetaxel+ADT) recomendado.")
    s["fields"].extend([
        {"name": "visceral_sites", "label": "Sitios viscerales documentados",
         "field_type": "select", "required": True,
         "options": ["pending", "liver_only", "lung_only", "liver_lung", "brain_documented",
                     "multiple_viscera"],
         "default": "pending",
         "group": "Visceral disease", "group_order": 0.7, "clinical_role": "required"},
    ])
    return s


def schema_mcspc_psma_only_metastatic() -> dict[str, Any]:
    s = _mcspc_base("mcspc_psma_only_metastatic",
        "mCSPC PSMA-only metastatic — M0 conv + M1 PSMA-PET",
        "PROMETHEUS: ARSI mono o RT+ADT local, NO chemo systemic.")
    s["fields"].extend([
        {"name": "psma_pet_only_disease", "label": "Disease detected ONLY por PSMA-PET",
         "field_type": "select", "required": True, "options": ["pending", "0", "1"],
         "default": "pending",
         "group": "PSMA-only confirm", "group_order": 0.7, "clinical_role": "required",
         "help_text": "Si bone scan + CT son negativos pero PSMA-PET muestra lesiones"},
        {"name": "psma_lesion_count_total", "label": "Lesiones PSMA totales",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 100,
         "group": "PSMA-only confirm", "group_order": 0.7, "clinical_role": "decision_refiner"},
    ])
    return s


# ─────────────────── Oligometastatic (4 states) ───────────────────

def _oligo_base(state: str, title: str, description: str) -> dict[str, Any]:
    meta = _common_meta(state, title, description)
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "oligometastatic_lesion_count", "label": "Lesiones oligometastásicas (N)",
         "field_type": "number", "required": True, "min_value": 1, "max_value": 10, "default": 1,
         "group": "Oligomet detalle", "group_order": 0.5, "clinical_role": "required",
         "help_text": "Cutoff típico ≤5 (algunos protocolos ≤3)"},
        {"name": "oligomet_anatomic_sites", "label": "Sitios anatómicos",
         "field_type": "textarea", "required": False,
         "group": "Oligomet detalle", "group_order": 0.5,
         "help_text": "Ej: L4 vertebral, ilíaco izquierdo, ganglio retroperitoneal"},
        {"name": "mdt_metastasis_directed_therapy_planned", "label": "MDT planeado",
         "field_type": "select", "required": True,
         "options": ["pending", "sbrt_all_lesions", "sbrt_index_lesion", "surgery_metastasectomy",
                     "rfa_cryoablation", "rt_palliative", "systemic_only_no_local"],
         "default": "pending",
         "group": "Decisión MDT", "group_order": 6, "clinical_role": "required",
         "help_text": "STOMP/ORIOLE: SBRT a todas las lesiones + ADT"},
        *_imaging_followup_fields(),
    ]}


def schema_oligometastatic_synchronous() -> dict[str, Any]:
    return _oligo_base("oligometastatic_synchronous",
        "Oligomet synchronous (de novo ≤3-5 lesiones)",
        "STOMP-arm: SBRT a todas + ADT systemic.")


def schema_oligometastatic_metachronous_adt_naive() -> dict[str, Any]:
    return _oligo_base("oligometastatic_metachronous_adt_naive",
        "Oligomet metachronous ADT-naïve",
        "MDT preferida sobre ARSI escalation; difiere ADT systemic.")


def schema_oligo_recurrent_post_definitive() -> dict[str, Any]:
    return _oligo_base("oligo_recurrent_post_definitive",
        "Oligo recurrent post-definitive (post-RP/RT, ≤3-5)",
        "MDT a sitios recurrentes; considerar salvage local + MDT.")


def schema_oligo_progressive_on_therapy() -> dict[str, Any]:
    s = _oligo_base("oligo_progressive_on_therapy",
        "Oligo-progressive on therapy",
        "Continuar terapia + SBRT a lesiones progresivas vs cambiar clase.")
    s["fields"].append(
        {"name": "current_systemic_therapy", "label": "Terapia sistémica actual",
         "field_type": "select", "required": True,
         "options": ["pending", "adt_alone", "adt_arpi", "adt_chemo", "parp",
                     "lu177", "other"],
         "default": "pending",
         "group": "Terapia actual", "group_order": 7, "clinical_role": "required"},
    )
    return s


# ─────────────────── Special populations (4 states) ───────────────────

def schema_geriatric_frail_limited() -> dict[str, Any]:
    meta = _common_meta(
        "geriatric_frail_limited",
        "Geriatric frail/limited (>75y o G8 ≤14) — de-escalation",
        "Treatment de-escalation, palliative options, supportive care intensificado.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "g8_score_current", "label": "G8 score actual", "field_type": "number",
         "required": True, "min_value": 0, "max_value": 17,
         "group": "Geriatric assessment", "group_order": 1, "clinical_role": "required"},
        {"name": "mini_cog_current", "label": "Mini-Cog actual",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 5,
         "group": "Geriatric assessment", "group_order": 1, "clinical_role": "decision_refiner"},
        {"name": "falls_last_6mo", "label": "Caídas últimos 6 meses",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 50, "default": 0,
         "group": "Geriatric assessment", "group_order": 1, "clinical_role": "monitoring"},
        {"name": "treatment_intent", "label": "Intención terapéutica",
         "field_type": "select", "required": True,
         "options": ["pending", "curative_de_escalated", "disease_control_supportive",
                     "best_supportive_care", "palliative_only"],
         "default": "pending",
         "group": "Decisión terapéutica", "group_order": 6, "clinical_role": "required"},
        {"name": "advance_care_planning_documented", "label": "Advance care planning documentado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown", "group": "EOL planning", "group_order": 7,
         "clinical_role": "decision_refiner"},
    ]}


def schema_young_onset_pca() -> dict[str, Any]:
    meta = _common_meta(
        "young_onset_pca",
        "Young-onset PCa (<55y) — aggressive biology consideration",
        "Germline universal, fertility preservation, surveillance familiar.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "age_at_diagnosis", "label": "Edad al diagnóstico",
         "field_type": "number", "required": True, "min_value": 18, "max_value": 65,
         "group": "Contexto", "group_order": 0.5, "clinical_role": "required"},
        {"name": "fertility_preservation_discussed", "label": "Fertility preservation discutida",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1", "declined"],
         "default": "unknown",
         "group": "Fertility", "group_order": 2, "clinical_role": "required",
         "help_text": "Sperm banking ANTES de cualquier ADT/RT"},
        {"name": "sperm_banking_completed", "label": "Sperm banking completado",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Fertility", "group_order": 2, "clinical_role": "decision_refiner",
         "conditional_visibility": {"fertility_preservation_discussed": ["1"]}},
        {"name": "germline_testing_completed", "label": "Germline testing completado",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1", "pending"],
         "default": "unknown",
         "group": "Genética", "group_order": 3, "clinical_role": "required",
         "help_text": "Universal en <55y per NCCN PROS-A"},
    ]}


def schema_comorbidity_limited_severe_cv() -> dict[str, Any]:
    meta = _common_meta(
        "comorbidity_limited_severe_cv",
        "Comorbidity severe CV — avoid abiraterone, prefer enza/apa con CV monitoring",
        "MI <6mo, IC NYHA III-IV, arritmia maligna → contraindicación abi (mineralocorticoid).",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "cv_event_history", "label": "Historia evento CV",
         "field_type": "select", "required": True,
         "options": ["pending", "recent_mi_lt_6mo", "mi_6_12mo", "mi_gt_12mo",
                     "chronic_chf_nyha_3_4", "chronic_chf_nyha_1_2",
                     "uncontrolled_arrhythmia", "controlled_arrhythmia", "cabg_pci_lt_6mo"],
         "default": "pending",
         "group": "CV detalle", "group_order": 0.5, "clinical_role": "required"},
        {"name": "ejection_fraction_baseline", "label": "FEVI baseline (%)",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 100, "unit": "%",
         "group": "CV detalle", "group_order": 0.5, "clinical_role": "monitoring"},
        {"name": "cardio_oncology_consult_obtained", "label": "Consulta cardio-oncología",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1", "scheduled"],
         "default": "unknown",
         "group": "Manejo", "group_order": 6, "clinical_role": "decision_refiner"},
        {"name": "arpi_choice_cv_safe", "label": "ARPI seleccionada (CV-safe)",
         "field_type": "select", "required": False,
         "options": ["pending", "enzalutamide", "apalutamide", "darolutamide", "avoid_arpi"],
         "default": "pending",
         "group": "Manejo", "group_order": 6, "clinical_role": "decision_refiner"},
    ]}


def schema_comorbidity_limited_severe_hepatic() -> dict[str, Any]:
    meta = _common_meta(
        "comorbidity_limited_severe_hepatic",
        "Comorbidity severe hepatic (LFT >3x ULN) — abi contraindicada",
        "Prefer enza/apa con LFT monitoring; abi contraindicada por hepatotoxicidad.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "ast_value", "label": "AST (U/L)", "field_type": "number",
         "required": True, "min_value": 0, "max_value": 5000, "unit": "U/L",
         "group": "Hepatic detalle", "group_order": 0.5, "clinical_role": "required"},
        {"name": "alt_value", "label": "ALT (U/L)", "field_type": "number",
         "required": True, "min_value": 0, "max_value": 5000, "unit": "U/L",
         "group": "Hepatic detalle", "group_order": 0.5, "clinical_role": "required"},
        {"name": "bilirubin_total", "label": "Bilirrubina total (mg/dL)",
         "field_type": "number", "required": False, "min_value": 0, "max_value": 30,
         "unit": "mg/dL",
         "group": "Hepatic detalle", "group_order": 0.5, "clinical_role": "monitoring"},
        {"name": "child_pugh_class", "label": "Child-Pugh class",
         "field_type": "select", "required": False, "options": ["unknown", "A", "B", "C"],
         "default": "unknown",
         "group": "Hepatic detalle", "group_order": 0.5, "clinical_role": "decision_refiner"},
        {"name": "arpi_choice_hepatic_safe", "label": "ARPI seleccionada (hepatic-safe)",
         "field_type": "select", "required": False,
         "options": ["pending", "enzalutamide", "apalutamide", "darolutamide",
                     "avoid_arpi_use_chemo"],
         "default": "pending",
         "group": "Manejo", "group_order": 6, "clinical_role": "decision_refiner"},
    ]}


# ─────────────────── Survivorship (3 states) ───────────────────

def _survivorship_base(state: str, title: str, description: str) -> dict[str, Any]:
    meta = _common_meta(state, title, description)
    return {**meta, "fields": [
        *_psa_followup_fields("PSA anual surveillance", 1.0),
        *_ecog_pros_baseline(),
        *_bone_health_monitoring_fields(),
        {"name": "secondary_malignancy_screening_done", "label": "Screening malignidad secundaria",
         "field_type": "select", "required": False, "options": ["unknown", "current", "overdue"],
         "default": "unknown",
         "group": "Cancer screening", "group_order": 7, "clinical_role": "decision_refiner",
         "help_text": "Post-RT pelvis: cribar bladder + rectal cancer; long-term PARP: MDS surveillance"},
    ]}


def schema_survivorship_post_curative_5y_plus() -> dict[str, Any]:
    return _survivorship_base("survivorship_post_curative_5y_plus",
        "Survivorship post-curative 5y+ NED",
        "PSA anual + late effects surveillance + reactive symptom-driven care.")


def schema_second_primary_surveillance() -> dict[str, Any]:
    s = _survivorship_base("second_primary_surveillance",
        "Second primary surveillance (post-RT bladder/rectal/MDS, post-PARP MDS/AML)",
        "Screening cadence dirigido al primary risk del primario.")
    s["fields"].append(
        {"name": "primary_risk_secondary_malignancy", "label": "Tipo primario de riesgo",
         "field_type": "select", "required": True,
         "options": ["pending", "bladder_post_pelvic_rt", "rectal_post_pelvic_rt",
                     "mds_aml_post_rt_or_parp", "lung_smoker", "skin_chronic_immune_suppression",
                     "other"],
         "default": "pending",
         "group": "Riesgo principal", "group_order": 0.5, "clinical_role": "required"},
    )
    return s


def schema_adt_long_term_complications() -> dict[str, Any]:
    s = _survivorship_base("adt_long_term_complications",
        "ADT long-term complications (≥2y on ADT) — multi-organ surveillance",
        "Bone + CV + metabolic + cognitive surveillance estructurada.")
    s["fields"].extend([
        {"name": "adt_total_duration_years", "label": "Duración total ADT (años)",
         "field_type": "number", "required": True, "min_value": 2, "max_value": 30,
         "unit": "años",
         "group": "ADT contexto", "group_order": 0.5, "clinical_role": "required"},
        {"name": "metabolic_syndrome_screening", "label": "Screening síndrome metabólico",
         "field_type": "select", "required": False,
         "options": ["unknown", "current", "overdue", "diagnosed_metabolic_syndrome"],
         "default": "unknown",
         "group": "ADT toxicidad metabólica", "group_order": 6, "clinical_role": "decision_refiner"},
        {"name": "hot_flashes_severity", "label": "Hot flashes severidad",
         "field_type": "select", "required": False,
         "options": ["unknown", "none", "mild", "moderate", "severe"],
         "default": "unknown",
         "group": "ADT QoL", "group_order": 7, "clinical_role": "monitoring"},
        {"name": "fatigue_severity", "label": "Fatiga severidad",
         "field_type": "select", "required": False,
         "options": ["unknown", "none", "mild", "moderate", "severe"],
         "default": "unknown",
         "group": "ADT QoL", "group_order": 7, "clinical_role": "monitoring"},
        {"name": "cognitive_complaints_documented", "label": "Quejas cognitivas documentadas",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "ADT QoL", "group_order": 7, "clinical_role": "decision_refiner"},
    ])
    return s


# ─────────────────── Pre-diagnostic (3 states) ───────────────────

def schema_suspected_low_psa_no_biopsy() -> dict[str, Any]:
    meta = _common_meta(
        "suspected_low_psa_no_biopsy",
        "Suspected low PSA, no biopsy — repeat PSA q6mo + lifestyle",
        "PSA 4-10, no PIRADS≥3, age <70. NCCN PROS-1 algorithm.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields("PSA q6mo", 1.0),
        {"name": "lifestyle_counseling_provided", "label": "Lifestyle counseling provisto",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Counseling", "group_order": 3, "clinical_role": "monitoring"},
        {"name": "mri_indicated_now", "label": "MRI indicada en próxima visita",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Próxima conducta", "group_order": 4, "clinical_role": "decision_refiner"},
    ]}


def schema_suspected_elevated_psa_watchful_wait() -> dict[str, Any]:
    meta = _common_meta(
        "suspected_elevated_psa_watchful_wait",
        "Suspected elevated PSA, watchful waiting (frail, ECOG ≥3, life_exp <5y)",
        "PSA >10 en paciente frail/limited life expectancy. NCCN PROS-1.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        *_ecog_pros_baseline(),
        {"name": "life_expectancy_estimated_years", "label": "Esperanza de vida estimada (años)",
         "field_type": "number", "required": True, "min_value": 0, "max_value": 30,
         "unit": "años",
         "group": "Contexto", "group_order": 1, "clinical_role": "required"},
        {"name": "watchful_wait_documented_decision", "label": "Decisión watchful wait documentada",
         "field_type": "select", "required": True, "options": ["pending", "0", "1"],
         "default": "pending",
         "group": "Decisión", "group_order": 5, "clinical_role": "required"},
    ]}


def schema_negative_biopsy_age_lt_45() -> dict[str, Any]:
    meta = _common_meta(
        "negative_biopsy_age_lt_45",
        "Negative biopsy age <45 (high-risk family hx) — aggressive re-biopsy MRI-targeted",
        "Joven con high-risk hereditario. Re-biopsy MRI-fusion en 6-12m + germline testing universal.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "age", "label": "Edad", "field_type": "number", "required": True,
         "min_value": 18, "max_value": 45,
         "group": "Contexto", "group_order": 0.5, "clinical_role": "required"},
        {"name": "first_degree_relative_pca_lt_55", "label": "Familiar 1er grado con CA próstata <55y",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Riesgo familiar", "group_order": 1, "clinical_role": "required"},
        {"name": "germline_testing_status", "label": "Germline testing status",
         "field_type": "select", "required": True,
         "options": ["pending", "0", "1", "in_progress"], "default": "pending",
         "group": "Germline", "group_order": 2, "clinical_role": "required"},
        {"name": "mri_fusion_re_biopsy_planned", "label": "Re-biopsy MRI-fusion planeada",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Próxima conducta", "group_order": 5, "clinical_role": "required"},
    ]}


# ─────────────────── Post-RT BCR (1 state) ───────────────────

def schema_post_rt_bcr() -> dict[str, Any]:
    meta = _common_meta(
        "post_rt_bcr",
        "Post-RT BCR (Phoenix criterion nadir+2) — salvage cryo/HIFU/SBRT vs ADT",
        "Phoenix BCR diferente de post-RP. Salvage local requiere biopsia confirmatoria + imaging completo.",
    )
    return {**meta, "fields": [
        *_psa_followup_fields(),
        {"name": "rt_modality_prior", "label": "Modalidad RT previa",
         "field_type": "select", "required": True,
         "options": ["pending", "ebrt_only", "brachy_ldr", "brachy_hdr",
                     "ebrt_plus_brachy_boost", "sbrt"],
         "default": "pending",
         "group": "RT historia", "group_order": 0.5, "clinical_role": "required"},
        {"name": "rt_completion_date_prior", "label": "Fecha finalización RT previa",
         "field_type": "date", "required": True,
         "group": "RT historia", "group_order": 0.5, "clinical_role": "required"},
        {"name": "phoenix_bcr_psa", "label": "PSA al cumplir Phoenix BCR",
         "field_type": "number", "required": True, "unit": "ng/mL", "min_value": 0,
         "group": "BCR detail", "group_order": 1, "clinical_role": "required"},
        {"name": "salvage_local_biopsy_done", "label": "Biopsia salvage local realizada",
         "field_type": "select", "required": False, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Salvage evaluation", "group_order": 5, "clinical_role": "decision_refiner",
         "help_text": "Mandatorio antes de salvage cryo/HIFU/SBRT"},
        {"name": "psma_pet_post_rt_bcr", "label": "PSMA-PET post-BCR realizada",
         "field_type": "select", "required": True, "options": ["unknown", "0", "1"],
         "default": "unknown",
         "group": "Salvage evaluation", "group_order": 5, "clinical_role": "required",
         "help_text": "NCCN PROS-D v2026 preferred over conventional en BCR"},
        {"name": "salvage_modality_planned", "label": "Modalidad salvage planeada",
         "field_type": "select", "required": False,
         "options": ["pending", "salvage_cryoablation", "salvage_hifu", "salvage_sbrt_to_prostate",
                     "salvage_rp_post_rt", "adt_systemic", "trial_enrollment", "observation"],
         "default": "pending",
         "group": "Salvage decisión", "group_order": 6, "clinical_role": "required"},
        *_ecog_pros_baseline(),
        *_imaging_followup_fields(),
    ]}


# ─────────────────── Public registry ───────────────────

INLINE_STAGE_SCHEMAS: dict[str, Callable[[], dict[str, Any]]] = {
    # Risk-stratified localized (6)
    "very_low_risk_localized": schema_very_low_risk_localized,
    "low_risk_localized": schema_low_risk_localized,
    "favorable_intermediate_risk_localized": schema_favorable_intermediate_risk_localized,
    "unfavorable_intermediate_risk_localized": schema_unfavorable_intermediate_risk_localized,
    "high_risk_localized": schema_high_risk_localized,
    "very_high_risk_localized": schema_very_high_risk_localized,
    # Post-local by modality (5)
    "post_brachy_ldr": schema_post_brachy_ldr,
    "post_brachy_hdr": schema_post_brachy_hdr,
    "post_ebrt_alone": schema_post_ebrt_alone,
    "post_sbrt": schema_post_sbrt,
    "post_focal_therapy": schema_post_focal_therapy,
    # Hereditary carriers (7)
    "brca2_carrier": schema_brca2_carrier,
    "brca1_carrier": schema_brca1_carrier,
    "atm_carrier": schema_atm_carrier,
    "palb2_carrier": schema_palb2_carrier,
    "hoxb13_carrier": schema_hoxb13_carrier,
    "lynch_carrier": schema_lynch_carrier,
    "hereditary_germline_pathway_umbrella": schema_hereditary_germline_pathway_umbrella,
    # mCRPC subtypes (6)
    "mcrpc_arsi_naive": schema_mcrpc_arsi_naive,
    "mcrpc_post_arsi": schema_mcrpc_post_arsi,
    "mcrpc_hrr_positive_parp_naive": schema_mcrpc_hrr_positive_parp_naive,
    "mcrpc_psma_eligible_lu177": schema_mcrpc_psma_eligible_lu177,
    "mcrpc_msi_h_dmmr": schema_mcrpc_msi_h_dmmr,
    "nepc_differentiation": schema_nepc_differentiation,
    # mCSPC refinements (3)
    "mcspc_latitude_high_risk": schema_mcspc_latitude_high_risk,
    "mcspc_visceral_only_m1c": schema_mcspc_visceral_only_m1c,
    "mcspc_psma_only_metastatic": schema_mcspc_psma_only_metastatic,
    # Oligometastatic (4)
    "oligometastatic_synchronous": schema_oligometastatic_synchronous,
    "oligometastatic_metachronous_adt_naive": schema_oligometastatic_metachronous_adt_naive,
    "oligo_recurrent_post_definitive": schema_oligo_recurrent_post_definitive,
    "oligo_progressive_on_therapy": schema_oligo_progressive_on_therapy,
    # Special populations (4)
    "geriatric_frail_limited": schema_geriatric_frail_limited,
    "young_onset_pca": schema_young_onset_pca,
    "comorbidity_limited_severe_cv": schema_comorbidity_limited_severe_cv,
    "comorbidity_limited_severe_hepatic": schema_comorbidity_limited_severe_hepatic,
    # Survivorship (3)
    "survivorship_post_curative_5y_plus": schema_survivorship_post_curative_5y_plus,
    "second_primary_surveillance": schema_second_primary_surveillance,
    "adt_long_term_complications": schema_adt_long_term_complications,
    # Pre-diagnostic (3)
    "suspected_low_psa_no_biopsy": schema_suspected_low_psa_no_biopsy,
    "suspected_elevated_psa_watchful_wait": schema_suspected_elevated_psa_watchful_wait,
    "negative_biopsy_age_lt_45": schema_negative_biopsy_age_lt_45,
    # Post-RT BCR (1)
    "post_rt_bcr": schema_post_rt_bcr,
}


__all__ = ["INLINE_STAGE_SCHEMAS"]
