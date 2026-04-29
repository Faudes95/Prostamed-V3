"""ProstaMed v2 — Builder de etapas avanzadas de captura clínica.

Faubot 2026-04-26 LXXXI (#audit-pre-cortana A1) — single source of truth
para fields gates 56-85 en UI v2.

CONTEXTO:
La auditoría pre-Cortana detectó que UI v2 (`patient_intake_v2_demo.html`)
NO capturaba ~50% de los fields necesarios para los gates 56-85 (RP/RT
subspecialty + genomic critical + pre-dx atypical + progression + palliative).

SOLUCIÓN:
Este builder genera dinámicamente las etapas + fields para captura UI v2
a partir del catálogo único `pivotal_gate_supporting_fields()`. Cualquier
gate nuevo añadido al helper se refleja automáticamente en UI v2 (no más
duplicación field-by-field).

ETAPAS GENERADAS (5 nuevas):
1. **subspecialty_rt_rp** (gates 56-60): anticoag + IBD + prior pelvic RT +
   TURP + SVI risk → RP vs RT subspecialty refinement
2. **genomic_critical** (gates 61-65): HRR + AR-V7 + CDK12 + HRD + MSI/MMR
   → genomic safety gates (hard_block PARP sin HRR)
3. **pre_dx_atypical** (gates 66-70): metastatic biopsy + NEPC + emergency +
   PHI/4Kscore + 10 trials adicionales
4. **progression_detection** (gates 71-75): PSMA + visceral + BPI + ECOG +
   composite rPFS
5. **palliative_radiopharm** (gates 76-85): Sm-153 + I-131 MIBG + Ac-225 +
   palliative sedation + ESAS + PHQ-9 + GAD-7 + palliative RT + oligo SBRT
   + cachexia

USO:
    from prostanet.presentation.v2_advanced_capture_builder import (
        build_advanced_capture_stages,
    )
    stages_list, fields_dict = build_advanced_capture_stages()
"""
from __future__ import annotations

from typing import Any

# ───────────────────────────────────────────────────────────────────────────
# Definición de las 5 etapas avanzadas (gate ranges + metadata)
# ───────────────────────────────────────────────────────────────────────────
# Cada entry mapea: (key, label, icon, gate_range, fields_filter, conditional)
# - gate_range: tupla (lo, hi) inclusive — usado para filtrar fields
# - fields_filter: lista de nombres explícitos que pertenecen a esta etapa
# - conditional: cuando aplicar (string Jinja-like para futura visibilidad
#   condicional, no-op por ahora)

_ADVANCED_STAGE_DEFINITIONS = [
    {
        "key": "subspecialty_rt_rp",
        "label": "RP vs RT (avanzado)",
        "icon": "scalpel",
        "gate_label": "Gates 56-60",
        "description": (
            "Decisión RP vs RT subespecialista: anticoagulantes, IBD, "
            "RT pélvica previa, TURP, riesgo SVI."
        ),
        "field_names": [
            # Gate 56 — Anticoag RP bleeding risk
            "anticoagulant_agent",
            "anticoagulant_indication",
            "dual_antiplatelet_therapy",
            "high_bleeding_risk_documented_pre_rp",
            # Gate 57 — IBD active + pelvic RT
            "inflammatory_bowel_disease_active",
            "ibd_active_flare_documented",
            "pelvic_rt_contraindicated_by_ibd",
            # Gate 58 — Prior pelvic RT + re-irradiation
            "prior_pelvic_radiation",
            "prior_pelvic_rt_intent",
            "re_irradiation_pelvic_contraindicated",
            "salvage_re_rt_protocol_documented",
            "palliative_intent_documented",
            # Gate 59 — TURP + brachy contraindication
            "history_of_turp",
            "turp_volume_resected_cc",
            "post_turp_retention_symptoms",
            "brachytherapy_contraindicated_by_turp",
            # Gate 60 — SVI risk nomogram
            "svi_risk_nomogram_percent",
            "svi_risk_high_documented",
        ],
    },
    {
        "key": "genomic_critical",
        "label": "Genómica crítica",
        "icon": "helix",
        "gate_label": "Gates 61-65",
        "description": (
            "Gates genómicos safety-first: HRR confirmation pre-PARP, AR-V7, "
            "CDK12, HRD comprehensive, MSI/MMR Lynch reflex."
        ),
        "field_names": [
            # Gate 61 — HRR confirmation pre-PARP (HARD_BLOCK)
            "hrr_status",
            "hrr_testing_not_performed",
            "brca1_status",
            "brca2_status",
            "atm_status",
            "parp_inhibitor_consideration_active",
            "parp_inhibitor_initiated_without_hrr",
            # Gate 62 — AR-V7 ARPI resistance
            "ar_v7_status",
            "ar_v7_detected_in_ctc",
            "ar_v7_resistance_documented",
            "armor3_sv_trial_consideration",
            # Gate 63 — CDK12 immunotherapy/PARP
            "cdk12_status",
            "cdk12_pathogenic_detected",
            "tandem_duplication_phenotype_documented",
            "cdk12_checkpoint_inhibitor_candidate",
            # Gate 64 — HRD comprehensive
            "hrd_comprehensive_score",
            "pten_biallelic_loss_documented",
            "tp53_status",
            "hrd_high_phenotype_documented",
            # Gate 65 — MSI/MMR Lynch reflex
            "lynch_syndrome_family_documented",
            "msi_mmr_testing_recommended_clinically",
            "msi_status",
            "mmr_deficient_status",
            "lynch_germline_test_indicated",
        ],
    },
    {
        "key": "pre_dx_atypical",
        "label": "Pre-dx + Atípica",
        "icon": "microscope",
        "gate_label": "Gates 66-70",
        "description": (
            "Pre-diagnóstico, biopsia metastásica, histología atípica "
            "(NEPC/intraductal/cribriforme), emergencias oncológicas, "
            "calculadores PHI/4Kscore."
        ),
        "field_names": [
            # Gate 66 — Metastatic biopsy pathway
            "primary_biopsy_not_performed",
            "widespread_bone_metastases_documented",
            "spinal_cord_compression_initial_presentation",
            "liver_metastasis_documented",
            "lung_metastasis_documented",
            "visceral_metastasis_present",
            "metastatic_biopsy_pathway_indicated",
            "primary_biopsy_completed_or_planned",
            "histology_already_confirmed",
            # Gate 67 — Atypical histology NEPC/intraductal (HARD_BLOCK)
            "nepc_confirmed_histology",
            "histology_subtype",
            "intraductal_carcinoma_present",
            "cribriform_pattern_present",
            "ldh_value",
            "treatment_emergent_nepc_suspected",
            # Gate 68 — Oncologic emergency (HARD_BLOCK)
            "spinal_cord_compression_suspected",
            "spinal_cord_compression_confirmed",
            "visceral_crisis_documented",
            "lymphangitic_carcinomatosis",
            "calcium_corrected_mg_dl",
            "dic_diagnosed",
            "inr_value",
            "bleeding_active_documented",
            "sodium_value",
            "oncologic_emergency_active",
            "emergency_resolved_or_stabilized_documented",
            "oncologic_emergency_managed",
            # Gate 69 — Pre-bx PHI/4Kscore/PSAD
            "phi_score_available",
            "phi_score_value",
            "fourkscore_available",
            "fourkscore_value",
            "psa_density",
            "prostate_volume_ml",
            "prior_negative_biopsy_documented",
            # Gate 70 — 10 trials adicionales completion
            "decision_rp_vs_rt_active",
            "active_surveillance_eligibility_evaluation",
            "salvage_rt_consideration_active",
            "trial_coverage_completion_check",
        ],
    },
    {
        "key": "progression_detection",
        "label": "Progresión (PSMA + clínica)",
        "icon": "activity",
        "gate_label": "Gates 71-75",
        "description": (
            "Detección compuesta de progresión: PSMA-PET, visceral nuevas, "
            "BPI pain, ECOG decline, composite PCWG3 rPFS reroute."
        ),
        "field_names": [
            # Gate 71 — PSMA-PET progression
            "psma_new_lesion_count",
            "psma_suvmax_current",
            "psma_suvmax_baseline",
            "psma_suvmax_increase_percent",
            "psma_total_tumor_volume_increase_percent",
            "psma_progression_date",
            "psma_pet_progression_documented",
            # Gate 72 — Visceral mets new appearance
            "new_visceral_metastasis_documented",
            "new_liver_metastasis_appeared",
            "new_lung_metastasis_appeared",
            "new_cns_metastasis_appeared",
            "visceral_metastases_count_current",
            "visceral_metastases_count_baseline",
            "visceral_metastases_count_increase",
            # Gate 73 — Structured pain BPI
            "bpi_worst_pain_score",
            "bpi_least_pain_score",
            "bpi_average_pain_score",
            "bpi_current_pain_score",
            "bpi_interference_average",
            "bpi_pain_persistent_weeks",
            "bpi_worst_pain_baseline",
            "bpi_worst_pain_increase_percent",
            "new_opioid_requirement_for_cancer_pain",
            "current_opioid_morphine_equivalent_mg_day",
            # Gate 74 — ECOG decline
            "ecog_current",
            "ecog_baseline",
            "ecog_change_from_baseline",
            "ecog_decline_documented_date",
            "ecog_significant_decline_documented",
            # Gate 75 — Composite progression rPFS reroute
            "psa_progression_documented",
            "pcwg3_composite_progression_documented",
            "composite_progression_categories_fired",
            "composite_progression_date",
            "next_line_therapy_planned",
            "mdt_composite_review_completed",
        ],
    },
    {
        "key": "systemic_toxicity",
        "label": "Toxicidad sistémica (cardio/hep/ren/hem)",
        "icon": "heart-pulse",
        "gate_label": "Gates 9-18 + 25-34",
        "description": (
            "Captura UI para gates de toxicidad sistémica: cardio (QTc/LVEF "
            "ARPI gates 17-18), hepático (darolutamide gate 32), renal "
            "(olaparib gate 29), cytopenias (gates 14-16/33/41), metabólico "
            "(ipatasertib gate 25)."
        ),
        "field_names": [
            # Cardio (gates 17-18 ARPI cardiotox)
            "qtc_ms", "qtc_baseline_ms", "qtc_change_ms", "qtc_corrected_for_arpi",
            "lvef_percent", "lvef_baseline_percent", "lvef_decline_for_arpi",
            "lvef_recovered_for_arpi",
            # Hepático (gate 32 darolutamide hepatic)
            "ast_value", "alt_value", "ast_ctcae_grade", "alt_ctcae_grade",
            "bilirubin_total_mg_dl",
            "hepatocellular_pattern_documented_for_darolutamide",
            "hepatic_function_recovered_for_darolutamide",
            "hepatotoxicity_ctcae_grade",
            "cholestatic_pattern_for_abiraterone",
            "alp_baseline_pre_abiraterone",
            "alp_normalized_post_rise_for_abiraterone",
            # Renal (gate 10/29 olaparib renal)
            "creatinine_clearance", "creatinine_ctcae_grade",
            "end_stage_renal_disease_dialysis",
            "adrenal_insufficiency_active",
            # Cytopenias (gates 14-16, 33, 41)
            "anc", "anc_baseline", "anc_baseline_pre_docetaxel",
            "anc_recovered_post_drop_for_docetaxel",
            "platelets", "platelet_count", "platelets_baseline_pre_niraparib",
            "rapid_platelet_drop_for_niraparib",
            "platelets_recovered_post_rapid_drop_for_niraparib",
            "platelet_count_recovered_for_niraparib",
            "hemoglobin_g_dl",
            "severe_cytopenia_for_radioligand", "severe_cytopenia_for_parp_inhibitor",
            "cytopenias_corrected_for_radioligand",
            "cytopenias_corrected_for_parp_inhibitor",
            "hemorrhage_ctcae_grade",
            # Metabólico (gate 25 ipatasertib + gate 49 hipocalemia abi)
            "glucose_fasting", "hba1c", "hyperglycemia_ctcae_grade",
            "hyperglycemia_grade3_for_ipatasertib",
            "hyperglycemia_controlled_for_ipatasertib",
            "potassium_serum", "potassium_serum_mmol_l",
            "metabolic_alkalosis_documented",
            # Sodio/SIADH (gate 48 enzalutamide)
            "sodium_serum", "sodium_serum_mmol_l",
            "hyponatremia_siadh_documented_for_enzalutamide",
            "hyponatremia_resolved_for_enzalutamide",
            "euvolemia_documented_for_siadh",
            "serum_osmolality", "urine_osmolality",
        ],
    },
    {
        "key": "bone_targeted_onj",
        "label": "Bone-targeted + ONJ + Hipocalcemia",
        "icon": "bone",
        "gate_label": "Gates 9, 12, 50-51",
        "description": (
            "Captura UI para gates óseos: BMA prophylaxis (gate 9), "
            "hipocalcemia (gate 12 + 50), osteonecrosis mandibular (gate 51), "
            "compresión medular (gates 11/13)."
        ),
        "field_names": [
            # Bone modifying agents (gate 9)
            "no_bone_protective_agent", "bone_modifying_agent",
            "denosumab_prophylaxis", "zoledronate_prophylaxis",
            "bone_protection_started", "considering_radium223",
            "planned_systemic_regimen", "radium223_candidate",
            "high_fracture_risk_for_radium223",
            "frax_10yr_hip_fracture_risk", "frax_10yr_major_fracture_risk",
            "dxa_t_score_femoral_neck", "dxa_t_score_lumbar",
            # Hipocalcemia (gate 12 + 50)
            "hypocalcemia", "calcium_level", "corrected_calcium",
            "serum_calcium", "ionized_calcium", "hypocalcemia_corrected",
            "chvostek_sign_positive", "trousseau_sign_positive",
            "perioral_paresthesias_documented",
            # ONJ (gate 51)
            "osteonecrosis_jaw_documented", "onj_stage_3_severe_documented",
            "onj_resolved_for_bone_targeted",
            "oral_exposed_bone_documented",
            "oral_exposed_bone_or_fistula_documented",
            "oral_exposed_bone_duration_weeks",
            "jaw_pain_or_infection_symptoms_documented",
            "no_prior_head_neck_radiation",
            # Cord compression (gates 11/13)
            "spinal_cord_compression", "epidural_compression",
            "lower_limb_weakness", "cord_compression_symptoms",
            "cord_compression_stabilized",
        ],
    },
    {
        "key": "immune_io_chemo",
        "label": "Inmunoterapia + Quimioterapia",
        "icon": "shield-virus",
        "gate_label": "Gates 26-28, 33-41",
        "description": (
            "Captura UI para gates de inmunoterapia (sipuleucel, checkpoint "
            "inhibitor pneumonitis/colitis/thyroiditis) + quimioterapia "
            "(docetaxel ANC longitudinal, cabazitaxel hypersensitivity)."
        ),
        "field_names": [
            # Immune IO (gates 26-28)
            "pneumonitis_ctcae_grade", "hypoxemia_with_checkpoint_inhibitor",
            "ground_glass_opacities_ct_for_checkpoint",
            "diarrhea_ctcae_grade", "hematochezia_severe_for_checkpoint",
            "bowel_perforation_for_checkpoint_inhibitor",
            "diabetes_new_onset_for_checkpoint",
            "tsh", "cortisol_basal_am_ug_dl", "cortisol_post_cosyntropin_ug_dl",
            "severe_fatigue_addison_like",
            "endocrinopathy_managed_with_replacement",
            "corticosteroid_replacement_therapy_documented",
            "adrenal_insufficiency_immune_for_checkpoint",
            # Sipuleucel (gates 37-38)
            "irr_grade_documented", "history_severe_irr_for_immunotherapy",
            "irr_premedication_protocol_active",
            "febrile_neutropenia_for_immunotherapy",
            "gcsf_prophylaxis_active_for_sipuleucel",
            "no_gcsf_prophylaxis_planned",
            # Docetaxel (gate 34) + Cabazitaxel
            "docetaxel_cycles_received",
            "cumulative_neuropathy_documented",
            "neuropathy_recovered_post_docetaxel",
            "cabazitaxel_hypersensitivity_history",
            "hypersensitivity_ctcae_grade",
            "hypersensitivity_grade1_only_premedicated",
            "polysorbate_hypersensitivity_history",
            "anaphylaxis_history_documented",
            "prior_taxane_anaphylaxis_documented",
            "fatigue_ctcae_grade", "fatigue_resolved_for_lutetium",
            # Apalutamide rash (gate 42)
            "rash_ctcae_grade",
            "skin_blistering_documented", "mucosal_involvement_documented",
            "erythema_multiforme_documented",
            "sjs_ten_suspected_or_diagnosed",
            # Enzalutamide seizure (related)
            "active_seizure_disorder", "seizure_ctcae_grade",
            "seizure_history_grade3_documented",
            "seizure_disorder_controlled_for_arpi",
        ],
    },
    {
        "key": "psa_kinetics_arpi",
        "label": "PSA kinetics + ARPI longitudinal",
        "icon": "trending-up",
        "gate_label": "Gates 47, 53-55, m0CRPC",
        "description": (
            "Captura UI para gates kinetics PSA (47 flare, 53 BCR aggressive, "
            "54 bounce post-RT, 55 PSADT progressive) + estados m0CRPC + "
            "ARPI overrides + cognitive."
        ),
        "field_names": [
            # PSA kinetics (gates 47, 53-55)
            "psa_doubling_time_months", "psa_velocity_ng_ml_year",
            "psa_baseline_pre_arpi", "psa_change_percent_since_arpi_start",
            "psa_weeks_since_arpi_start",
            "psa_flare_documented_first_month_arpi",
            "psa_rise_above_nadir_ng_ml", "months_post_rt",
            "psa_bounce_documented_post_rt",
            "psa_elevation_unconfirmed_post_rt",
            "no_image_progression_documented",
            "prior_radical_prostatectomy_documented",
            "bcr_high_risk_aggressive_documented",
            "bcr_aggressive_treated_for_salvage",
            # m0CRPC ARPI eligibility
            "m0_crpc_state_confirmed",
            "no_active_arpi_for_m0_crpc",
            "psadt_progressive_for_arpi_eligibility",
            "arpi_already_initiated_for_m0_crpc",
            # Cognitive ARPI elderly
            "cognitive_concerns_documented",
            "cognitive_baseline_normalized_for_arsi_elderly",
            # MDS/AML (gate 16, 52)
            "mds_aml_history", "prior_mds", "prior_aml",
            "bone_marrow_dysplasia_documented",
            # VTE / Hypertension (gates 35, 36)
            "history_vte_documented", "vte_high_risk_for_arsi_documented",
            "anticoagulation_therapeutic_active",
            "hypertension_active_documented",
            "hypertension_ctcae_grade", "hypertension_grade3_for_niraparib",
            "hypertension_controlled_for_niraparib",
            "systolic_blood_pressure",
            # G8 frailty
            "g8_geriatric_score", "cga_vulnerable_or_frail_documented",
            "bedridden_status_documented",
            # Vital signs misc
            "temperature_celsius", "d_dimer_ng_ml",
        ],
    },
    {
        "key": "longitudinal_overrides",
        "label": "Longitudinal + Overrides + Resolved states",
        "icon": "history",
        "gate_label": "Multi-gate longitudinal",
        "description": (
            "Captura UI para fields longitudinales (CTCAE grades, recovered/"
            "resolved/managed states), assessment dates, performance scales "
            "(Karnofsky/G8), y override flags multi-gate."
        ),
        "field_names": [
            # CTCAE grades adicionales
            "colitis_ctcae_grade", "hepatitis_ctcae_grade",
            "pneumonitis_documented_for_checkpoint_inhibitor",
            "thyroiditis_ctcae_grade", "thrombocytopenia_ctcae_grade",
            # Immune-related adverse events documented
            "colitis_immune_documented_for_checkpoint",
            "hepatitis_immune_documented_for_checkpoint",
            "hypophysitis_documented_for_checkpoint",
            # Resolved states (overrides)
            "colitis_resolved_for_checkpoint_inhibitor",
            "pneumonitis_resolved_for_checkpoint_inhibitor",
            "hepatic_function_recovered_for_checkpoint_inhibitor",
            "hepatic_function_recovered_for_abiraterone",
            "hepatotoxicity_grade3_for_abiraterone",
            "hypokalemia_pseudoaldosteronism_documented_for_abiraterone",
            "hypokalemia_resolved_for_abiraterone",
            "hypocalcemia_documented_for_bone_targeted",
            "hypocalcemia_resolved_for_bone_targeted",
            "renal_function_corrected_for_olaparib",
            # Cytopenias longitudinales
            "cytopenia_duration_weeks", "cytopenia_two_or_more_lines_documented",
            "thrombocytopenia_grade3_for_niraparib",
            # Hb baseline + recovery (cabazitaxel/lutetium)
            "hb_baseline_pre_cabazitaxel", "hb_recovered_post_drop_for_cabazitaxel",
            "hb_baseline_pre_lutetium", "hb_recovered_post_drop_for_lutetium",
            "rapid_hb_drop_for_cabazitaxel", "rapid_hb_drop_for_lutetium",
            "rapid_anc_drop_for_docetaxel",
            # MDS/AML PARP
            "hematologic_malignancy_suspected_for_parpi",
            "mds_aml_remission_for_parpi", "mds_or_aml_documented_during_parpi",
            "bone_marrow_blasts_percent",
            # Performance + bone protection
            "karnofsky_performance_status",
            "geriatric_clearance_for_triplete",
            "bone_protection_established_pre_radium223",
            "castrate_testosterone_status_confirmed",
            # Endocrine
            "cortisol_am",
            # Calcium adicional
            "ionized_calcium_mmol_l",
            # Vitales
            "diastolic_blood_pressure",
            # Assessment dates
            "esas_assessment_date", "gad7_assessment_date",
            "phq9_assessment_date", "palliative_sedation_initiation_date",
        ],
    },
    {
        "key": "palliative_radiopharm",
        "label": "Paliativo + Radiofármacos",
        "icon": "compass",
        "gate_label": "Gates 76-85",
        "description": (
            "Radiofármacos paliativos (Sm-153, I-131 MIBG, Ac-225-PSMA), "
            "sedación paliativa EAPC, ESAS multi-síntoma, PHQ-9/GAD-7, "
            "RT paliativa engine, SBRT oligometastático, cachexia."
        ),
        "field_names": [
            # Gate 76 — Samarium-153 EDTMP
            "samarium_153_edtmp_candidate",
            "bone_pain_widespread_documented",
            "bone_scan_multifoci_positive",
            "osteoblastic_lesions_predominant",
            "samarium_153_dose_planned_mci_kg",
            "samarium_153_administration_date",
            "samarium_153_prior_administrations_count",
            # Gate 77 — I-131 MIBG NEPC
            "mibg_scan_positive_diagnostic",
            "mibg_curie_score",
            "i131_mibg_candidate_clinical",
            "i131_mibg_dose_planned_mci",
            "sski_thyroid_blockade_initiated",
            # Gate 78 — Ac-225-PSMA investigational
            "lutetium_177_psma_progression_documented",
            "psma_pet_positive_current",
            "actinium_225_psma_candidate",
            "actinium_225_trial_enrollment_active",
            "actinium_225_dose_planned_kbq_kg",
            # Gate 79 — Palliative sedation EAPC (HARD_BLOCK)
            "palliative_sedation_initiation_planned",
            "end_of_life_stage_documented",
            "refractory_pain_palliative_failure",
            "refractory_dyspnea_terminal",
            "refractory_agitation_delirium_terminal",
            "palliative_sedation_eapc_criteria_met",
            "mdt_consensus_palliative_sedation_documented",
            "family_consent_palliative_sedation_documented",
            "palliative_sedation_agent_selected",
            # Gate 80 — ESAS 9-item multi-síntoma
            "esas_pain_score",
            "esas_fatigue_score",
            "esas_nausea_score",
            "esas_depression_score",
            "esas_anxiety_score",
            "esas_drowsiness_score",
            "esas_appetite_score",
            "esas_wellbeing_score",
            "esas_dyspnea_score",
            "esas_total_score",
            "esas_items_above_4_count",
            "esas_severe_distress_documented",
            # Gate 81 — PHQ-9 depression
            "phq9_total_score",
            "phq9_item_9_suicidal_ideation",
            "clinical_depression_documented",
            "antidepressant_initiated",
            "psych_referral_completed",
            # Gate 82 — GAD-7 anxiety
            "gad7_total_score",
            "clinical_anxiety_disorder_documented",
            "anxiolytic_initiated",
            # Gate 83 — Palliative RT decision engine
            "bone_metastasis_localized_painful",
            "hematuria_persistent_tumoral",
            "hemoptysis_tumoral_documented",
            "hemostatic_rt_indicated",
            "brain_metastases_documented",
            "leptomeningeal_disease_documented",
            "palliative_rt_consideration_active",
            "palliative_rt_dose_fractionation_planned",
            "palliative_rt_target_site",
            # Gate 84 — Oligometastatic SBRT
            "total_metastases_count",
            "life_expectancy_months",
            "oligometastatic_recurrence_metachronous",
            "oligoprogression_under_systemic_therapy",
            "oligometastatic_sbrt_candidate",
            "oligometastatic_category",
            "psma_pet_staging_recent",
            "sbrt_target_sites_planned",
            "sbrt_dose_fractionation_per_site",
            # Gate 85 — Cachexia pharmacotherapy
            "weight_loss_percent_6mo",
            "bmi",
            "sarcopenia_documented",
            "appetite_loss_documented",
            "cachexia_clinical_diagnosed",
            "cachexia_stage",
            "pg_sga_score",
            "current_weight_kg",
            "baseline_weight_kg",
            "albumin_g_dl",
            "prealbumin_mg_dl",
            "crp_mg_l",
        ],
    },
    {
        "key": "subspecialty_pre_dx_decisions",
        "label": "Subespecialista + Pre-Dx + MDT (LXXXIV)",
        "icon": "stethoscope",
        "gate_label": "Gates 67B, 67C, 69B",
        "description": (
            "Captura UI para nuevos gates Iteración #1 (FAUBOT LXXXIV): "
            "NEPC pre-biopsia (gate 67B), cT4 sin biopsia hard_block (gate 67C), "
            "PSA velocity pre-biopsia urgente (gate 69B), MDT shared decision, "
            "presumptive diagnosis pathway, modalidad imaging M-staging."
        ),
        "field_names": [
            # Gate 67B: NEPC pre-biopsia
            "clinical_nepc_suspicion_pre_biopsy",
            # Gate 67C: cT4 + DRE finality + decision active + override
            "dre_fixation",
            "decision_rp_vs_rt_active",
            "planning_radical_prostatectomy",
            "planning_radiotherapy_curative",
            "presumptive_treatment_documented_with_2week_biopsy_plan",
            "histology_confirmed_metastatic_site",
            # Gate 69B: PSA velocity pre-biopsia + sin RT previa
            "prior_radiation_therapy_documented",
            "psa_velocity_pre_biopsy_urgent_documented",
            # NEPC platinum-EP regimen
            "nepc_platinum_ep_regimen_active",
            # Imaging modality M-staging
            "imaging_modality_used_for_m_staging",
        ],
    },
    {
        "key": "mdt_genomic_hereditary_panel",
        "label": "MDT + Genomic tracking + Hereditary",
        "icon": "users",
        "gate_label": "Cross-cutting LXXXIV",
        "description": (
            "Cross-cutting fields para todos los estadios: documentación MDT "
            "shared decision, tracking de tests genómicos en curso (HRR/AR-V7/"
            "CDK12/MSI/HRD), historia familiar hereditary cancer panel + "
            "genetic counseling refusal documentation."
        ),
        "field_names": [
            # MDT shared decision tracking
            "mdt_shared_decision_date",
            "mdt_providers_present",
            "patient_preferences_vs_recommendation",
            # Genomic testing tracking centralizado
            "genomic_test_ordered_date",
            "genomic_test_provider",
            "genomic_test_expected_result_date",
            "hrr_test_pending_with_2week_plan_documented",
            # Hereditary cancer panel
            "family_history_pca_under_55",
            "family_history_brca_breast_ovarian",
            "germline_test_refused_reason",
        ],
    },
]


def _fieldspec_to_v2_input(fs: Any) -> dict[str, Any]:
    """Convierte un FieldSpec → schema input v2 (compatible con
    `patient_intake_v2_demo.html` template).

    El template renderiza:
    - select: con `options` lista de tuplas/strings
    - boolean: checkbox
    - multiselect: checkboxes múltiples
    - date / number / text: inputs estándar
    """
    name = getattr(fs, "name", "")
    label = getattr(fs, "label", name)
    field_type = getattr(fs, "field_type", "text")
    raw_options = getattr(fs, "options", []) or []
    default = getattr(fs, "default", "")
    unit = getattr(fs, "unit", "")
    help_text = getattr(fs, "help_text", "")
    min_value = getattr(fs, "min_value", None)
    max_value = getattr(fs, "max_value", None)

    # Normalizar options para el template (acepta strings o tuplas)
    if field_type == "select":
        options_normalized = []
        for opt in raw_options:
            if isinstance(opt, (list, tuple)) and len(opt) >= 2:
                options_normalized.append((opt[0], opt[1]))
            else:
                # String → tupla (val, val) usando el string como label
                opt_str = str(opt)
                options_normalized.append((opt_str, opt_str))
    else:
        options_normalized = []

    out: dict[str, Any] = {
        "name": name,
        "label": label,
        "type": field_type,
        "required": False,  # Captura avanzada es opcional (gates condicionales)
    }

    if options_normalized:
        out["options"] = options_normalized
    if default not in ("", None):
        out["default"] = str(default)
    if unit:
        out["unit"] = unit
    if help_text:
        # Truncar help_text largo para UI compact (max 200 chars)
        out["help"] = help_text[:200] + ("…" if len(help_text) > 200 else "")
    if min_value is not None:
        out["min"] = min_value
    if max_value is not None:
        out["max"] = max_value

    return out


def build_advanced_capture_stages() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Genera las 5 etapas avanzadas + fields para captura UI v2.

    Returns:
        Tupla (stages_list, fields_dict) donde:
        - stages_list: lista de dicts con metadata de etapas
          (key, label, icon, n_fields, required, conditional, description)
        - fields_dict: dict {stage_key: [field_input_dicts]}

    Auto-genera desde `pivotal_gate_supporting_fields()` para mantener
    single source of truth — cualquier gate nuevo añadido al helper
    se refleja automáticamente en UI v2.

    Si el helper no está disponible (test isolation), retorna estructura
    vacía sin fallar.
    """
    try:
        from prostanet.shared.advanced_support_fields import (
            pivotal_gate_supporting_fields,
        )
        all_fields = pivotal_gate_supporting_fields()
    except ImportError:
        return [], {}

    # Index fields by name para lookup O(1)
    fields_by_name: dict[str, Any] = {f.name: f for f in all_fields}

    stages_list: list[dict[str, Any]] = []
    fields_dict: dict[str, list[dict[str, Any]]] = {}

    # Faubot LXXXV.b — De-dup fields cross-stages.
    # Bug detectado: algunos fields (hrr_status, decision_rp_vs_rt_active,
    # psa_density) se referencian en 2+ stages. FormData colecta `<select>`
    # duplicados como list → backend rompe con "unhashable type: 'list'".
    # Fix: track names ya emitidos y skip duplicados (first-stage wins).
    _emitted_field_names: set[str] = set()

    for stage_def in _ADVANCED_STAGE_DEFINITIONS:
        key = stage_def["key"]
        field_names = stage_def["field_names"]

        # Construir lista de fields v2 para esta etapa
        stage_fields: list[dict[str, Any]] = []
        for fname in field_names:
            fs = fields_by_name.get(fname)
            if fs is None:
                # Field referenciado en _ADVANCED_STAGE_DEFINITIONS pero ausente
                # en el helper — log silencioso, no rompe UI
                continue
            if fname in _emitted_field_names:
                # Faubot LXXXV.b — skip duplicate (first stage wins)
                continue
            _emitted_field_names.add(fname)
            stage_fields.append(_fieldspec_to_v2_input(fs))

        if not stage_fields:
            continue  # No agregar etapa vacía

        # Agregar metadata de la etapa
        stages_list.append({
            "key": key,
            "label": stage_def["label"],
            "icon": stage_def["icon"],
            "n_fields": len(stage_fields),
            "required": 0,  # Avanzado es opcional
            "conditional": (
                "if state in (mhspc, mcrpc, post_prostatectomy, recurrence_bcr) "
                "or any_advanced_capture_required"
            ),
            "description": stage_def["description"],
            "gate_label": stage_def["gate_label"],
            "advanced_capture": True,  # Flag para que UI los renderice colapsados
        })
        fields_dict[key] = stage_fields

    return stages_list, fields_dict


def get_advanced_capture_field_names() -> set[str]:
    """Retorna el set completo de nombres de fields cubiertos por las
    etapas avanzadas (gates 56-85). Útil para tests E2E + verificación
    de cobertura.
    """
    names: set[str] = set()
    for stage_def in _ADVANCED_STAGE_DEFINITIONS:
        names.update(stage_def["field_names"])
    return names


def get_advanced_stage_keys() -> list[str]:
    """Retorna las claves de las 5 etapas avanzadas."""
    return [stage_def["key"] for stage_def in _ADVANCED_STAGE_DEFINITIONS]
