from __future__ import annotations

from copy import deepcopy
import re

from prostanet.shared.field_semantics import CAPTURE_LAYER_METADATA, field_semantics_for, semantic_option_label
from prostanet.shared.recommendation_enrichment import normalize_legacy_result


WIZARD_CANONICAL_ALIAS_SUPPRESSIONS = {
    "alp": "alkaline_phosphatase_u_l",
    "alkaline_phosphatase": "alkaline_phosphatase_u_l",
    "ldh": "ldh_u_l",
    "serum_ldh": "ldh_u_l",
    "hemoglobin": "hemoglobin_g_dl",
    "hgb": "hemoglobin_g_dl",
    "hb": "hemoglobin_g_dl",
    "creatinine": "creatinine_mg_dl",
}


MODULE_TITLE_MAP = {
    "diagnostic_workup": "Estudio diagnóstico antes de confirmar cáncer de próstata",
    "post_negative_biopsy_followup": "Seguimiento después de una biopsia benigna inicial",
    "localized_initial": "Diagnóstico inicial localizado o regional con ganglios regionales positivos y sin metástasis a distancia",
    "post_prostatectomy": "Seguimiento después de prostatectomía radical",
    "recurrence_bcr": "Recurrencia bioquímica y segunda recurrencia bioquímica sin metástasis",
    "post_radiotherapy_or_local_salvage": "Recurrencia post-radioterapia y salvage local",
    "adt_progression_verification": "Progresión bajo ADT / verificación de castración",
    "mcspc_oligo_metachronous": "Enfermedad metastásica sensible a la castración oligometastásica metacrónica",
    "mcspc_low_volume_sync_oligo": "Enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica",
    "mcspc_high_volume_sync": "Enfermedad metastásica sensible a la castración de alto volumen sincrónica",
    "mcspc_high_volume_metachronous": "Enfermedad metastásica sensible a la castración de alto volumen metacrónica",
    "mcspc_high_volume": "Enfermedad metastásica sensible a la castración de alto volumen",
    "m0_crpc": "Enfermedad resistente a la castración sin metástasis",
    "m1_crpc": "Enfermedad resistente a la castración con metástasis",
    "survivorship_and_toxicity_followup": "Survivorship y toxicidad por tratamiento",
    "state_classifier": "Clasificador de estado clínico",
}

STATE_SHORT_LABELS = {
    "diagnostic_workup": "Diagnóstico inicial",
    "post_negative_biopsy_followup": "Seguimiento tras biopsia benigna",
    "localized_initial": "Enfermedad localizada o regional N1M0",
    "post_prostatectomy": "Seguimiento posprostatectomía",
    "recurrence_bcr": "Recurrencia bioquímica",
    "post_radiotherapy_or_local_salvage": "Recurrencia post-RT",
    "adt_progression_verification": "Progresión bajo ADT / verificación",
    "mcspc_oligo_metachronous": "mHSPC oligometastásico metacrónico",
    "mcspc_low_volume_sync_oligo": "mHSPC sincrónico de bajo volumen",
    "mcspc_high_volume_sync": "mHSPC de alto volumen sincrónico",
    "mcspc_high_volume_metachronous": "mHSPC de alto volumen metacrónico",
    "mcspc_high_volume": "mHSPC de alto volumen",
    "m0_crpc": "CRPC sin metástasis",
    "m1_crpc": "CRPC metastásico",
    "survivorship_and_toxicity_followup": "Survivorship y toxicidad",
}

OPTION_LABELS = {
    # EPIC 44.A — labels clínicamente densos: el clínico escanea sin abrir help_text
    "known_cancer_diagnosis": {"1": "Sí, confirmado por biopsia", "0": "No, en evaluación por sospecha"},
    "prior_negative_biopsy": {"0": "Sin biopsia previa negativa", "1": "Biopsia previa negativa"},
    "metastasis_site": {
        "M0": "Sin metástasis a distancia (M0)",
        "Bone": "Metástasis ósea",
        "Node": "Metástasis ganglionar",
        "Visceral": "Metástasis visceral",
        "Oligometastatic": "Enfermedad oligometastásica",
    },
    "dre_suspicious": {"0": "Tacto no sospechoso", "1": "Tacto sospechoso (nódulo / induración)"},
    "family_history_positive": {"0": "Sin antecedentes familiares relevantes", "1": "Sí (1º grado CaP, mama u ovario)"},
    "germline_risk_mutation": {"0": "Sin mutación germline conocida", "1": "Sí, mutación germline patogénica documentada"},
    "pirads_score": {
        "0": "No disponible",
        "2": "PI-RADS 2 o menor",
        "3": "PI-RADS 3",
        "4": "PI-RADS 4",
        "5": "PI-RADS 5",
    },
    "gleason_primary": {"3": "Patrón 3", "4": "Patrón 4", "5": "Patrón 5"},
    "gleason_secondary": {"3": "Patrón 3", "4": "Patrón 4", "5": "Patrón 5"},
    "gleason_tertiary": {"3": "Patrón 3", "4": "Patrón 4", "5": "Patrón 5"},
    "volume_disease": {
        "Low": "Bajo volumen",
        "High": "Alto volumen",
    },
    "peripheral_neuropathy_grade": {
        "0": "Grado 0",
        "1": "Grado 1",
        "2": "Grado 2",
        "3": "Grado 3",
        "4": "Grado 4",
    },
    "castration_resistant": {"0": "Sensible a castración", "1": "Resistente a castración (CRPC)"},
    "systemic_progression_context": {
        "none": "No aplica / sin contexto de progresión bajo ADT",
        "progression_on_adt_verify_castration": "Progresión bajo ADT: verificar castración",
        "confirmed_crpc": "CRPC ya confirmado",
    },
    "current_adt_context": {
        "none": "Sin ADT activa",
        "medical_adt_continuous": "ADT médica continua",
        "orchiectomy": "Orquiectomía",
        "intermittent_adt": "ADT intermitente",
    },
    "castrate_testosterone_status": {
        "confirmed_castrate": "Castración confirmada",
        "not_castrate": "No castrado",
        "unknown": "Desconocido",
    },
    "progression_pattern": {
        "biochemical_only": "Solo bioquímica",
        "radiographic": "Radiográfica",
        "clinical": "Clínica",
        "mixed": "Mixta",
    },
    "conventional_imaging_status": {
        "not_restaged": "Sin reestadificación convencional reciente",
        "M0": "Imagen convencional M0",
        "M1": "Imagen convencional M1",
    },
    "prior_local_therapy_context": {
        "none": "Sin tratamiento local previo relevante",
        "prostatectomy": "Prostatectomía previa",
        "radiotherapy": "Radioterapia previa",
        "both": "Prostatectomía y radioterapia previas",
    },
    "prior_prostatectomy": {"0": "No", "1": "Sí, prostatectomía radical previa"},
    "prior_radiation": {"0": "No", "1": "Sí, radioterapia previa"},
    # EPIC 44.A — labels clínicamente densos (urólogo no debe abrir help_text para entender el campo)
    "bcr_detected": {"0": "Sin BCR confirmada", "1": "BCR confirmada (PSA ≥0.2 ng/mL ascendente)"},
    "bcr2": {"0": "Sin segunda recurrencia", "1": "Segunda BCR confirmada"},
    "metachronous_metastasis": {"0": "Sincrónica / de novo", "1": "Metacrónica (post-tratamiento local)"},
    "cribriform_pattern": {"0": "Ausente", "1": "Presente (patrón cribiforme adverso)"},
    "intraductal_carcinoma": {"0": "Ausente", "1": "Presente (componente intraductal)"},
    "prior_mpmri_pirads_score": {
        "2": "PI-RADS 2 o menor",
        "3": "PI-RADS 3",
        "4": "PI-RADS 4",
        "5": "PI-RADS 5",
        "desconocido": "Desconocido",
    },
    "prior_mpmri_targeted_biopsy_status": {
        "si": "Sí",
        "no": "No",
        "desconocido": "Desconocido",
    },
    "adverse_histology_variant_type": {
        "none": "Sin variante adversa adicional",
        "ductal_predominant": "Predominio ductal",
        "sarcomatoid": "Sarcomatoide",
        "signet_ring": "Células en anillo de sello",
        "adenosquamous_or_squamous": "Adenoescamoso o escamoso",
        "basal_cell": "Células basales",
        "mucinous_colloid": "Mucinoso / coloide",
        "small_cell_neuroendocrine": "Neuroendocrino de célula pequeña",
        "mixed_multiple": "Mixta / múltiple",
        "other_aggressive": "Otra agresiva",
        "other_aggressive_unspecified": "Otra agresiva no especificada",
    },
    "nodal_status": {
        "N0": "Sin ganglios regionales comprometidos (N0)",
        "N1": "Con ganglios regionales comprometidos (N1)",
    },
    # EPIC 44.A — comorbilidades + imaging + biomarcadores: labels que reflejan impacto clínico
    "comorbidity_seizure": {"0": "Sin antecedente de convulsiones", "1": "Sí (riesgo enzalutamida)"},
    "comorbidity_cardio": {"0": "Sin enfermedad CV severa", "1": "Sí (riesgo abi/enza, evaluar BP basal)"},
    "imaging_negative": {"0": "Imagen positiva o no realizada", "1": "Sí, imagen convencional negativa"},
    "eligible_pelvic_therapy": {"0": "No elegible para terapia pélvica", "1": "Elegible"},
    "prior_secondary_rt": {"0": "Sin RT secundaria previa", "1": "Sí, RT secundaria previa (riesgo toxicidad acumulada)"},
    "psma_positive": {"0": "Sin enfermedad PSMA-avid", "1": "PSMA-positiva (avid disease, candidato VISION/PSMAfore)", "unknown": "No documentado"},
    "surgical_margin": {"0": "Márgenes negativos (R0)", "1": "Márgenes positivos (R1)"},
    "ece_status": {"0": "Sin extensión extracapsular", "1": "Extensión extracapsular presente"},
    "svi_status": {"0": "Sin invasión vesical seminal", "1": "Invasión vesical seminal presente"},
    "lni_status": {"0": "Sin invasión ganglionar", "1": "Invasión ganglionar presente (pN1)"},
    "rt_primary_received": {"0": "Sin RT primaria recibida", "1": "RT primaria recibida"},
    "rt_intent": {
        "definitive": "Definitiva",
        "adjuvant": "Adyuvante",
        "salvage": "Salvamento",
        "palliative": "Paliativa",
        "MDT": "Terapia dirigida a metástasis (MDT)",
    },
    "modality": {
        "EBRT_IMRT": "Radioterapia externa IMRT",
        "EBRT_VMAT": "Radioterapia externa VMAT",
        "SBRT": "Radioterapia estereotáctica corporal (SBRT)",
        "LDR_brachy": "Braquiterapia de baja tasa",
        "HDR_brachy": "Braquiterapia de alta tasa",
        "protons": "Protones",
        "combined": "Combinada",
    },
    "target_volume": {
        "prostate_only": "Próstata solamente",
        "prostate_sv": "Próstata y vesículas seminales",
        "whole_pelvis": "Pelvis completa",
        "boost_dominant": "Refuerzo a lesión dominante",
        "metastasis_directed": "Dirigida a metástasis",
        "prostate_pelvis_boost": "Próstata + pelvis con refuerzo",
    },
    "salvage_pre_imaging": {
        "none": "Sin imagen previa",
        "ct_bone_scan": "Tomografía y gammagrama óseo",
        "psma_pet": "PET/CT con PSMA",
        "mpmri": "Resonancia multiparamétrica",
    },
    # EPIC 46.A — Ancestría con impacto clínico
    "primary_ancestry": {
        "no_declarado": "Prefiero no responder",
        "mestizo": "Mestizo (origen mixto indígena + europeo)",
        "afro_descendiente": "Afro-descendiente",
        "indigena": "Indígena (auto-adscrito)",
        "europeo": "Europeo / Caucásico",
        "asiatico": "Asiático",
        "otro": "Otro / Combinación específica",
    },
    "psma_pet_local_access": {
        "desconocido": "Desconocido",
        "1": "Sí, accesible localmente",
        "0": "No, requiere viaje o no disponible",
    },
    "lu_psma_local_access": {
        "desconocido": "Desconocido",
        "1": "Sí, Lu-PSMA disponible localmente",
        "0": "No, sin acceso a Lu-PSMA",
    },
    "arsi_local_access": {
        "desconocido": "Desconocido",
        "1": "Sí, ARSIs accesibles (cobertura o autofinanciamiento)",
        "0": "No, ARSIs no accesibles",
    },
}


def state_display_label(state: str, *, short: bool = True) -> str:
    key = str(state or "").strip()
    if not key:
        return ""
    if short:
        return STATE_SHORT_LABELS.get(key, MODULE_TITLE_MAP.get(key, key.replace("_", " ")))
    return MODULE_TITLE_MAP.get(key, STATE_SHORT_LABELS.get(key, key.replace("_", " ")))

BOOLEAN_OPTION_LABELS = {"0": "No", "1": "Sí"}

BOOLEAN_CONTEXTUAL_OPTION_LABELS = {
    "bone_protection_started": {"0": "No iniciada", "1": "Iniciada"},
    "calcium_vitd_started": {"0": "No iniciados", "1": "Iniciados"},
    "castrate_testosterone_confirmed": {"0": "No confirmada", "1": "Confirmada"},
    "confirmatory_biopsy_planned": {"0": "No planificada", "1": "Planificada"},
    "cv_risk_documented": {"0": "No documentado", "1": "Documentado"},
    "drug_interaction_reviewed": {"0": "No revisadas", "1": "Revisadas"},
    "ddi_review_status": {
        "not_started": "No iniciada",
        "in_progress": "En curso",
        "completed": "Completada",
    },
    "dxa_baseline_done": {"0": "No realizada", "1": "Realizada"},
    "active_liver_disease": {"0": "Ausente", "1": "Presente"},
    "cirrhosis_or_portal_hypertension": {"0": "Ausente", "1": "Presente"},
    "active_hepatitis_b_or_c": {"0": "Ausente", "1": "Presente"},
    "prior_drug_induced_liver_injury": {"0": "Ausente", "1": "Presente"},
    "hepatic_risk_factors": {"0": "Ausentes", "1": "Presentes"},
    "micro_us_available": {"0": "No disponible", "1": "Disponible"},
    "low_activity": {"0": "No documentada", "1": "Sí, actividad reducida"},
    "slow_gait": {"0": "No documentada", "1": "Sí, marcha lenta"},
    "weak_grip": {"0": "No documentada", "1": "Sí, prensión baja"},
    "protein_supplements": {"0": "No consume", "1": "Sí consume"},
    "neuroendocrine_features": {"0": "Ausentes", "1": "Presentes"},
    "persistent_lesion_signal": {"0": "Ausente", "1": "Presente"},
    "post_biopsy_mri": {"0": "No realizada", "1": "Realizada"},
    "prior_mpmri": {"0": "No disponible", "1": "Disponible"},
    "psma_negative_dominant_lesions": {"0": "Ausentes", "1": "Presentes"},
    "psma_pet_done": {"0": "No realizado", "1": "Realizado"},
    "rare_histology_variant": {"0": "Ausente", "1": "Presente"},
    "ultrasensitive_psa_assay": {"0": "No documentado", "1": "Documentado"},
    # EPIC 44.A FAUBOT 2026-05-17 CXXIV — anti-patterns inventariados en intake_smart_capture
    # (urólogo reportó "0/1" raw para campos críticos NCCN/EAU)
    "perineural_invasion": {"0": "Ausente", "1": "Presente", "unknown": "No documentada"},
    "extracapsular_extension_on_biopsy": {"0": "Ausente", "1": "Presente (factor adverso pT3a)", "unknown": "No documentada"},
    "lymphovascular_invasion": {"0": "Ausente", "1": "Presente", "unknown": "No documentada"},
    "biopsy_scheduled": {"0": "No agendada", "1": "Programada"},
    "screening_context": {"0": "Evaluación con sospecha (PSA/DRE+)", "1": "Screening poblacional"},
    "germline_testing_performed": {"0": "No realizado", "1": "Realizado", "pending": "Resultado pendiente", "unknown": "No documentado"},
    "first_degree_relative_pca_lt60": {"0": "No", "1": "Sí, familiar 1º grado CaP <60 años", "unknown": "No documentado"},
    "first_degree_relative_brca_breast_ovarian": {"0": "No", "1": "Sí, familiar 1º grado BRCA/mama/ovario", "unknown": "No documentado"},
    "lynch_syndrome_features": {"0": "Sin sospecha Lynch", "1": "Características de síndrome de Lynch", "unknown": "No documentado"},
    "mpmri_done": {"0": "No realizada", "1": "Realizada", "unknown": "No documentado"},
    "bone_scan_done": {"0": "No realizada", "1": "Realizada", "unknown": "No documentado"},
    "ct_abdomen_pelvis_done": {"0": "No realizada", "1": "Realizada", "unknown": "No documentado"},
    "severe_cv_disease": {"0": "Sin enfermedad CV severa", "1": "Sí (IC NYHA III-IV, MI <6m, arritmia maligna)", "unknown": "No documentado"},
    "cognitive_impairment_documented": {"0": "Sin deterioro documentado", "1": "Deterioro cognitivo documentado (riesgo enza)", "unknown": "No documentado"},
    "visceral_metastasis_present": {"0": "No (M ósea/ganglionar solo)", "1": "Sí (hígado/pulmón/cerebro/SNC)", "unknown": "No documentado"},
    "metastatic_disease_known": {"0": "Sin evidencia de enfermedad metastásica", "1": "Enfermedad metastásica documentada", "unknown": "No documentado"},
    "nonregional_nodal_metastasis_present": {"0": "Sin ganglios no regionales", "1": "Sí (cadena no regional comprometida)", "unknown": "No documentado"},
    "bone_metastasis_present": {"0": "Sin metástasis óseas", "1": "Metástasis óseas presentes", "unknown": "No documentado"},
    "primary_tumor_treated": {"0": "Primario no tratado", "1": "Primario tratado"},
    "hrr_pathogenic_variant": {"0": "Sin variante HRR patogénica", "1": "Variante HRR patogénica (candidato PARP)", "unknown": "No documentado"},
    "msi_high": {"0": "MSS / MSI estable", "1": "MSI-high (candidato pembrolizumab)", "unknown": "No documentado"},
    "tmb_high": {"0": "TMB no alto", "1": "TMB ≥10 mut/Mb", "unknown": "No documentado"},
    "p53_mutated": {"0": "TP53 wild-type / no testeado", "1": "TP53 mutado", "unknown": "No documentado"},
    "rb1_loss": {"0": "RB1 intacto / no testeado", "1": "Pérdida de RB1", "unknown": "No documentado"},
    "ar_amplification": {"0": "Sin amplificación AR / no testeado", "1": "Amplificación AR detectada", "unknown": "No documentado"},
    "ar_v7_positive": {"0": "AR-V7 negativo / no testeado", "1": "AR-V7 positivo", "unknown": "No documentado"},
}

BADGE_LABELS = {
    "preferred": "Preferente",
    "selected_candidate": "Candidato seleccionado",
    "guideline-consistent": "Alineado con las guías",
    "eligible": "Elegible",
    "observation_preferred": "Observación preferente",
    "not_preferred": "No preferente",
    "not_recommended": "No recomendado",
}

CLINICAL_ROLE_LABELS = {
    "required": "Mínimo para decidir",
    "decision_refiner": "Afina la recomendación",
    "derived": "Calculado",
    "monitoring": "Monitoreo",
    "optional": "Opcional",
}

EVENT_KIND_LABELS = {
    "recommendation_generated": "Recomendación generada",
    "management_selected": "Conducta seleccionada",
    "procedure_ordered": "Procedimiento solicitado",
    "procedure_performed": "Procedimiento realizado",
    "pathology_confirmed": "Patología confirmada",
    "molecular_result_verified": "Biomarcador verificado",
    "followup_visit_recorded": "Seguimiento registrado",
}

MANAGEMENT_INTENT_STATUS_LABELS = {
    "candidate": "Pendiente de confirmación",
    "discussed": "Discutido",
    "chosen": "Planificado",
    "delivered": "En curso",
    "completed": "Completado",
    "progressed": "Progresado",
    "escalated": "Escalado",
}

TEXT_REPLACEMENTS = [
    ("Clinical Hub", "Centro clínico por estadio"),
    ("Legacy calculator", "Ruta antigua retirada"),
    ("wizard", "asistente clínico"),
    ("wizards", "asistentes clínicos"),
    ("State classifier", "Clasificador de estado clínico"),
    ("Policy", "Normativa"),
    ("Inputs", "Datos clínicos"),
    ("Pivotal trials", "Estudios pivotales"),
    ("Core questions", "Preguntas clínicas centrales"),
    ("Evidence trace", "Trazabilidad de evidencia"),
    ("local_computation", "cálculo local"),
    ("external_calculator", "calculadora externa"),
    ("external_result", "resultado externo"),
    ("calculado", "calculado"),
    ("listo_para_calculadora", "listo para calculadora"),
    ("faltan_datos", "faltan datos"),
    ("pendiente_de_resultado", "pendiente de resultado"),
    ("no_documentado", "no documentado"),
    ("contextual", "contextual"),
    ("alta", "alta"),
    ("vigilada", "vigilada"),
    ("escalar", "escalar"),
    ("No prior local therapy or advanced-state markers were detected.", "No se detectaron tratamientos locales previos ni marcadores de enfermedad avanzada."),
    ("Prior prostatectomy without recurrent-state override.", "Se detectó prostatectomía radical previa sin criterios que desplacen el caso a recurrencia."),
    ("Recurrence or BCR2 markers detected after local therapy.", "Se detectaron marcadores de recurrencia o de segunda recurrencia bioquímica después de tratamiento local."),
    ("Metachronous limited metastatic hormone-sensitive state.", "Se detectó enfermedad metastásica sensible a la castración, oligometastásica y metacrónica."),
    ("Metastatic hormone-sensitive disease with low-volume/sync-oligo pattern.", "Se detectó enfermedad metastásica sensible a la castración con patrón de bajo volumen u oligometastásico sincrónico."),
    ("High-volume metastatic hormone-sensitive disease.", "Se detectó enfermedad metastásica sensible a la castración de alto volumen."),
    ("Castration-resistant non-metastatic state.", "Se detectó enfermedad resistente a la castración sin metástasis."),
    ("Metastatic castration-resistant state.", "Se detectó enfermedad resistente a la castración con metástasis."),
    ("Module selected by state classifier.", "El módulo fue seleccionado por el clasificador de estado clínico."),
    (
        "Risk grouping, active surveillance and treatment eligibility aligned to NCCN 5.2026 with EAU 2026 comparison.",
        "Estratificación de riesgo, vigilancia activa y elegibilidad terapéutica alineadas con la Red Nacional Integral del Cáncer (NCCN) 5.2026 y comparadas con la Asociación Europea de Urología (EAU) 2026.",
    ),
    ("ISUP grade group", "Grupo de grado de la Sociedad Internacional de Patología Urológica (ISUP)"),
    ("Use 0.20 for 20%.", "Use 0.20 para representar 20 %."),
    ("Use M0 if no distant disease is known.", "Use M0 si no se conoce enfermedad metastásica a distancia."),
    ("State classifier", "Clasificador de estado clínico"),
    ("Favorable Intermediate", "Intermedio favorable"),
    ("Unfavorable Intermediate", "Intermedio desfavorable"),
    ("Intermediate (Favorable)", "Intermedio favorable"),
    ("Intermediate (Unfavorable)", "Intermedio desfavorable"),
    ("High", "Alto"),
    ("Very High", "Muy alto"),
    ("Low", "Bajo"),
    ("Metastatic", "Metastásico"),
    ("Locally Advanced", "Localmente avanzado"),
    ("Definitive local therapy with long-course systemic intensification when indicated.", "Terapia local definitiva con intensificación sistémica prolongada cuando esté indicada."),
    ("Consider definitive RT plus long-course ADT and systemic intensification in eligible patients.", "Considerar radioterapia definitiva más terapia de privación androgénica prolongada e intensificación sistémica en pacientes elegibles."),
    ("EBRT plus long-course ADT with systemic intensification for eligible patients, or RP in selected candidates.", "Radioterapia externa más terapia de privación androgénica prolongada con intensificación sistémica en pacientes elegibles, o prostatectomía radical en candidatos seleccionados."),
    ("EBRT plus long-course ADT, or RP with pelvic nodal dissection in selected patients.", "Radioterapia externa más terapia de privación androgénica prolongada, o prostatectomía radical con disección ganglionar pélvica en pacientes seleccionados."),
    ("RT plus short-course ADT or RP in eligible patients.", "Radioterapia más terapia de privación androgénica de corta duración, o prostatectomía radical en pacientes elegibles."),
    ("Observation or definitive local therapy; AS only in carefully selected patients with >10-year life expectancy.", "Observación o terapia local definitiva; la vigilancia activa (AS) solo debe plantearse en pacientes cuidadosamente seleccionados con una esperanza de vida mayor de 10 años."),
    ("Observation is preferred below 10-year life expectancy.", "La observación es preferente cuando la esperanza de vida es menor de 10 años."),
    ("For appropriate surgical candidates after shared decision-making.", "Opción apropiada para candidatos quirúrgicos después de una toma de decisiones compartida."),
    ("Reasonable standard option for FIR disease.", "Opción estándar razonable para enfermedad intermedia favorable."),
    ("Standard option for suitable surgical candidates.", "Opción estándar para candidatos quirúrgicos adecuados."),
    ("AS may be considered only in selected favorable-intermediate cases without adverse histology.", "La vigilancia activa (AS) solo puede considerarse en casos intermedios favorables seleccionados y sin histología adversa."),
    ("This NCCN 2026 risk group is not appropriate for active surveillance as a primary management strategy.", "Este grupo de riesgo de la Red Nacional Integral del Cáncer (NCCN) 2026 no es apropiado para vigilancia activa como estrategia principal de manejo."),
    ("Active surveillance is preferred for most men with >=10-year life expectancy; observation if <10 years.", "La vigilancia activa es preferente para la mayoría de los pacientes con una esperanza de vida mayor o igual a 10 años; observación si es menor de 10 años."),
    ("Short-course ADT should be paired with RT in most eligible patients.", "La terapia de privación androgénica de corta duración debe combinarse con radioterapia en la mayoría de los pacientes elegibles."),
    ("Use in properly selected patients with pelvic nodal planning as indicated.", "Usar en pacientes cuidadosamente seleccionados con planificación ganglionar pélvica cuando esté indicada."),
    ("For selected surgical candidates in experienced centers.", "Reservado para candidatos quirúrgicos seleccionados en centros con experiencia."),
    ("Use long-course ADT and intensification for eligible men.", "Usar terapia de privación androgénica prolongada e intensificación en pacientes elegibles."),
    ("Systemic intensification path for very-high-risk disease.", "Ruta de intensificación sistémica para enfermedad de muy alto riesgo."),
    ("Reserved for carefully chosen surgical candidates.", "Reservado para candidatos quirúrgicos cuidadosamente seleccionados."),
    ("Use in eligible regional node-positive disease per NCCN 2026 pathway.", "Usar en enfermedad regional con ganglios positivos en pacientes elegibles según la ruta NCCN 2026."),
    ("NCCN 5.2026 classifies this patient as ", "La Red Nacional Integral del Cáncer (NCCN) 5.2026 clasifica a este paciente como "),
    ("EAU 2026 comparison:", "comparación con la Asociación Europea de Urología (EAU) 2026:"),
    ("Regional N1M0", "Regional N1M0"),
    ("Classification and staging systems", "Clasificación y sistemas de estadificación"),
    ("Mayo Clinic Inspired", "Referencia visual inspirada en la Clínica Mayo"),
    ("Journey Clínico del Paciente", "Trayectoria clínica del paciente"),
    ("Patient Journey", "trayectoria clínica del paciente"),
    ("Status", "Estado actual"),
    ("Waterfall", "gráfico de cascada"),
    ("Outcomes Reportados por Paciente", "Resultados reportados por el paciente"),
    ("Patient-Reported Outcomes", "resultados reportados por el paciente"),
    ("PROs", "resultados reportados por el paciente (PROs)"),
    ("Mayo Clinic PSA Tower", "Torre de control del antígeno prostático específico de la Clínica Mayo"),
    ("MSKCC Nomograms", "Nomogramas del Centro Oncológico Memorial Sloan Kettering (MSKCC)"),
    ("CaPSURE Registry", "Registro CaPSURE de evolución clínica"),
    ("OncoLens / PCaGuard", "Plataformas oncológicas de apoyo clínico"),
    ("AI prediction", "predicción asistida por inteligencia artificial"),
    ("Risk trajectory", "trayectoria de riesgo clínico"),
    ("Trial matching", "emparejamiento con ensayos clínicos"),
    ("Patient portal", "portal del paciente"),
    ("Research export", "exportación para investigación"),
    ("Cohorte analytics", "analítica de cohortes"),
    ("Multi-site", "multisitio"),
    ("Salvage RT", "radioterapia de rescate"),
    ("Clinical summary", "Resumen clínico"),
    ("M0 CRPC risk-adapted intensification pathway.", "Ruta de intensificación adaptada al riesgo en enfermedad resistente a la castración sin metástasis."),
    ("M1 CRPC sequencing and precision-oncology pathway.", "Ruta de secuenciación terapéutica y oncología de precisión en enfermedad resistente a la castración con metástasis."),
    ("ADT progression verification pathway.", "Ruta de progresión bajo terapia de privación androgénica con verificación de castración."),
    ("Low-volume metastatic hormone-sensitive pathway.", "Ruta de enfermedad metastásica sensible a la castración de bajo volumen."),
    ("High-volume metastatic hormone-sensitive pathway.", "Ruta de enfermedad metastásica sensible a la castración de alto volumen."),
    ("Metachronous oligometastatic hormone-sensitive pathway.", "Ruta de enfermedad oligometastásica metacrónica sensible a la castración."),
    ("suppression_failure_or_inadequate_castration", "Fracaso de supresión androgénica o castración inadecuada"),
    ("biochemical_progression_on_adt_pending_verification", "Progresión bioquímica bajo terapia de privación androgénica pendiente de verificación"),
    ("confirmed_nmcrpc_candidate", "Candidato confirmado a enfermedad resistente a la castración sin metástasis"),
    ("confirmed_mcrpc_candidate", "Candidato confirmado a enfermedad resistente a la castración con metástasis"),
    ("Post-RP status:", "Estado posterior a prostatectomía radical:"),
    ("Recurrence pathway:", "Ruta de recurrencia:"),
    ("RT ", "Radioterapia "),
    ("PSA persistence/recurrence", "Persistencia o recurrencia del antígeno prostático específico"),
    ("Adverse pathology under surveillance", "Patología adversa bajo vigilancia"),
    ("Post-RP surveillance", "Vigilancia posterior a prostatectomía radical"),
    ("Post-RP recurrence", "Recurrencia posterior a prostatectomía radical"),
    ("Post-RT recurrence", "Recurrencia posterior a radioterapia"),
    ("mCSPC high-volume", "enfermedad metastásica sensible a la castración de alto volumen"),
    ("mCSPC low-volume / synchronous oligometastatic", "enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica"),
    ("mCSPC oligometastatic metachronous", "enfermedad metastásica sensible a la castración oligometastásica metacrónica"),
    ("M1 CRPC", "enfermedad resistente a la castración con metástasis"),
    ("M0 CRPC", "enfermedad resistente a la castración sin metástasis"),
    ("Factores de riesgo", "Fundamentos personalizados"),
    ("Treatment", "Tratamiento"),
    ("Follow-up", "Seguimiento"),
    ("Biochemical recurrence", "Recurrencia bioquímica"),
    ("Perfil Biológico & Laboratorios (Basal)", "Perfil biológico y laboratorios basales"),
    ("Estadificación & Volumen de Enfermedad", "Estadificación y volumen de enfermedad"),
    ("Medicina de Precisión & Función", "Medicina de precisión y función"),
    ("Sitio de Metástasis (Predominante)", "Sitio de metástasis predominante"),
    ("Panel Genético Realizado", "Panel genético realizado"),
    ("Línea Terapéutica", "Línea terapéutica"),
    ("Esquema (Fármacos)", "Esquema farmacológico"),
    ("Comorbilidades Críticas (Contraindicaciones)", "Comorbilidades críticas y contraindicaciones"),
    ("Historial Terapéutico Previo (Opcional)", "Historial terapéutico previo (opcional)"),
    ("Perfil Demográfico México (Investigación)", "Perfil demográfico de México para investigación"),
    ("Paquetes-Año", "Paquetes-año"),
    ("Sx. Metabólico", "Síndrome metabólico"),
    ("Dx:", "Fecha de diagnóstico:"),
    ("SS:", "Seguridad social:"),
    ("Toxicidad (CTCAE)", "Toxicidad según los Criterios Comunes de Terminología para Eventos Adversos"),
    ("Eventos Esqueléticos (SREs)", "Eventos esqueléticos relacionados"),
    ("Escala Dolor", "Escala de dolor"),
    ("Active surveillance is not favored because adverse histology is present.", "La vigilancia activa no se favorece porque existe histología adversa."),
    ("Active surveillance is preferred in low-risk disease with >=10-year life expectancy.", "La vigilancia activa es preferente en enfermedad de bajo riesgo con una esperanza de vida mayor o igual a 10 años."),
    ("Definitive local therapy is favored over AS in this setting.", "En este contexto se favorece la terapia local definitiva por encima de la vigilancia activa."),
    ("Regional node-positive non-metastatic disease.", "Enfermedad regional con ganglios positivos y sin metástasis a distancia."),
    ("At least two very-high-risk features by NCCN 5.2026.", "Al menos dos características de muy alto riesgo según la Red Nacional Integral del Cáncer (NCCN) 5.2026."),
    ("At least one high-risk feature by NCCN 5.2026.", "Al menos una característica de alto riesgo según la Red Nacional Integral del Cáncer (NCCN) 5.2026."),
    ("GG3, multiple intermediate-risk factors, or >=50% positive cores.", "Grupo de grado 3, múltiples factores de riesgo intermedio o 50 % o más de cilindros positivos."),
    ("Single intermediate-risk factor, GG1-2, and <50% positive cores.", "Un solo factor de riesgo intermedio, grupo de grado 1 a 2 y menos de 50 % de cilindros positivos."),
    ("cT1-T2a, GG1, PSA <10 without higher-risk features.", "cT1 a cT2a, grupo de grado 1, antígeno prostático específico menor de 10 y sin características de mayor riesgo."),
    ("Risk-adapted ARPI intensification in high-risk nmCRPC.", "Intensificación con inhibidor de la vía del receptor androgénico adaptada al riesgo en enfermedad resistente a la castración sin metástasis de alto riesgo."),
    ("Use ARPI intensification when PSADT is short and metastatic imaging is negative.", "Usar intensificación con inhibidor de la vía del receptor androgénico cuando el tiempo de duplicación del antígeno prostático específico sea corto y la imagen metastásica sea negativa."),
    ("M0 CRPC risk-adapted intensification pathway.", "Ruta de intensificación adaptada al riesgo para enfermedad resistente a la castración sin metástasis."),
    ("Prioritize triplet therapy when clinically fit; otherwise use best doublet option.", "Priorizar terapia triplete cuando el paciente sea clínicamente apto; de lo contrario usar el mejor doblete disponible."),
    ("High-volume metastatic hormone-sensitive pathway.", "Ruta para enfermedad metastásica sensible a la castración de alto volumen."),
    ("Combine systemic intensification with MDT discussion when disease is limited.", "Combinar la intensificación sistémica con discusión de terapia dirigida a metástasis cuando la carga de enfermedad sea limitada."),
    ("Metachronous oligometastatic hormone-sensitive pathway.", "Ruta para enfermedad metastásica sensible a la castración oligometastásica metacrónica."),
    ("Prefer systemic doublets and evaluate RT to the primary when the prostate remains untreated.", "Preferir dobletes sistémicos y evaluar radioterapia al tumor primario cuando la próstata permanezca sin tratamiento local."),
    ("Low-volume metastatic hormone-sensitive pathway.", "Ruta para enfermedad metastásica sensible a la castración de bajo volumen."),
    ("Use dedicated high-risk BCR2 systemic pathways only when criteria are met.", "Usar rutas sistémicas específicas para segunda recurrencia bioquímica de alto riesgo solo cuando se cumplan los criterios."),
    ("Favor early salvage RT evaluation and risk-adapted ADT rather than delayed treatment.", "Favorecer la evaluación temprana de radioterapia de rescate y la terapia de privación androgénica adaptada al riesgo en lugar de retrasar el tratamiento."),
    ("Re-stage and consider local salvage versus systemic transition based on imaging and kinetics.", "Reestadificar y considerar rescate local frente a transición sistémica según la imagen y la cinética de la enfermedad."),
    ("Insufficient local-therapy context; confirm recurrence setting.", "Contexto insuficiente de tratamiento local; confirmar el escenario de recurrencia."),
    ("Use BCR high-risk systemic intensification only when the EMBARK-like pattern is documented on conventional M0 imaging and no curative local salvage path remains.", "Usar intensificación sistémica para recurrencia bioquímica de alto riesgo solo cuando el patrón tipo EMBARK esté documentado en imagen convencional M0 y ya no exista una vía curativa de rescate local."),
    ("Prefer risk-adapted follow-up and early salvage decision-making over reflex adjuvant treatment.", "Preferir seguimiento adaptado al riesgo y toma de decisiones tempranas sobre rescate antes que tratamiento adyuvante reflejo."),
    ("Prefer early risk-adapted salvage and avoid undifferentiated recurrence outputs.", "Preferir rescate temprano adaptado al riesgo y evitar salidas indiferenciadas de recurrencia."),
    ("Escalate to recurrence/salvage assessment rather than routine surveillance.", "Escalar a evaluación de recurrencia o rescate en lugar de vigilancia rutinaria."),
    ("Prefer close monitoring with early salvage planning; avoid routine adjuvant treatment for every patient.", "Preferir monitorización estrecha con planificación temprana de rescate y evitar tratamiento adyuvante rutinario para todos los pacientes."),
    ("Confirm castrate-range testosterone and optimize androgen deprivation before assigning a non-metastatic castration-resistant state.", "Confirmar testosterona en rango de castración y optimizar la terapia de privación androgénica antes de asignar un estado resistente a la castración sin metástasis."),
    ("Post-RP status: ", "Estado posterior a prostatectomía radical: "),
    ("CAPRA-S belongs only to this module.", "El puntaje postoperatorio CAPRA-S pertenece exclusivamente a este módulo."),
    ("Close surveillance", "Vigilancia estrecha"),
    ("Early salvage planning", "Planificación temprana de rescate"),
    ("Routine postoperative surveillance", "Vigilancia posoperatoria rutinaria"),
    ("Use the recurrence module for salvage and BCR2 logic.", "Usar el módulo de recurrencia para la lógica de rescate y segunda recurrencia bioquímica."),
    ("Monitor PSA closely and trigger early salvage when indicated.", "Monitorizar de cerca el antígeno prostático específico y activar rescate temprano cuando esté indicado."),
    ("Continue PSA monitoring.", "Continuar la monitorización del antígeno prostático específico."),
    ("High-risk BCR2 pattern with N0M0 imaging and no pelvic-directed option.", "Patrón de segunda recurrencia bioquímica de alto riesgo con imagen N0M0 y sin opción de tratamiento pélvico dirigido."),
    ("Post-RP BCR2 with short PSADT and salvage-ineligible or previously irradiated pelvis.", "Segunda recurrencia bioquímica posterior a prostatectomía radical con tiempo de duplicación del antígeno prostático específico corto y pelvis no elegible para rescate o previamente irradiada."),
    ("Use PSA persistence/recurrence thresholds and clinical risk.", "Usar umbrales de persistencia o recurrencia del antígeno prostático específico y el riesgo clínico."),
    ("If ADT is added with secondary RT, use a risk-adapted duration in the 6-24 month range.", "Si se añade terapia de privación androgénica con radioterapia secundaria, usar una duración adaptada al riesgo en el rango de 6 a 24 meses."),
    ("Confirm local-only versus systemic recurrence before treatment selection.", "Confirmar recurrencia exclusivamente local frente a recurrencia sistémica antes de seleccionar tratamiento."),
    ("Enzalutamide +/- leuprolide", "Enzalutamida con o sin leuprorelina"),
    ("PSMA-PET directed salvage staging", "PSMA-PET dirigido a rescate"),
    ("Post-RT local salvage review", "Discusión de rescate local posradioterapia"),
    ("Docetaxel", "Docetaxel"),
    ("Cabazitaxel", "Cabazitaxel"),
    ("Olaparib", "Olaparib"),
    ("Pembrolizumab", "Pembrolizumab"),
    ("Darolutamide", "Darolutamida"),
    ("Enzalutamide", "Enzalutamida"),
    ("Abiraterone", "Abiraterona"),
    ("Apalutamide", "Apalutamida"),
    ("Talazoparib + Enzalutamide", "Talazoparib + enzalutamida"),
    ("Niraparib + Abiraterone", "Niraparib + abiraterona"),
    ("ADT + Niraparib + Abiraterone", "Terapia de privación androgénica + niraparib + abiraterona"),
    ("ADT + Rezvilutamida", "Terapia de privación androgénica + rezvilutamida"),
    ("Confirm castrate testosterone and optimize ADT", "Confirmar testosterona en rango de castración y optimizar la terapia de privación androgénica"),
    ("Active surveillance loses priority when the genomic classifier suggests high biological risk.", "La vigilancia activa pierde prioridad cuando el clasificador genómico sugiere alto riesgo biológico."),
    ("Active surveillance remains reasonable, but 2026-style readiness requires prior MRI and a confirmatory biopsy plan.", "La vigilancia activa sigue siendo razonable, pero la preparación estilo 2026 requiere resonancia magnética previa y un plan de biopsia confirmatoria."),
    ("Classification and staging systems, Treatment", "Clasificación y sistemas de estadificación, Tratamiento"),
    ("Badge de aplicabilidad", "Nivel de aplicabilidad"),
    ("No recomendado", "No recomendado"),
    ("NCCN primaria", "Recomendación principal según la Red Nacional Integral del Cáncer (NCCN)"),
    ("EAU 2026", "Comparación con la Asociación Europea de Urología (EAU) 2026"),
    ("BCR2 N0M0", "segunda recurrencia bioquímica sin metástasis ni ganglios regionales comprometidos"),
    ("Active surveillance", "Vigilancia activa"),
    ("Observation", "Observación"),
    ("Definitive RT", "Radioterapia definitiva"),
    ("Radical prostatectomy", "Prostatectomía radical"),
    ("RT + ADT", "Radioterapia + terapia de privación androgénica"),
    ("EBRT + ADT + abiraterone", "Radioterapia externa + terapia de privación androgénica + abiraterona"),
    ("EBRT + ADT", "Radioterapia externa + terapia de privación androgénica"),
    ("Radical prostatectomy + PLND", "Prostatectomía radical + linfadenectomía pélvica"),
    ("Definitive RT + ADT", "Radioterapia definitiva + terapia de privación androgénica"),
    ("Systemic intensification", "Intensificación sistémica"),
    ("Early salvage RT evaluation", "Evaluación de radioterapia de rescate temprana"),
    ("Re-staging after RT recurrence", "Reestadificación después de la recurrencia posterior a radioterapia"),
    ("Enzalutamide +/- leuprolide", "Enzalutamida con o sin leuprorelina"),
    ("Apalutamide", "Apalutamida"),
    ("Apalutamide + ADT", "Apalutamida + terapia de privación androgénica"),
    ("ADT + monitorizacion", "Terapia de privación androgénica + monitorización"),
    ("monitorizacion", "monitorización"),
    ("Darolutamida + ADT", "Darolutamida + terapia de privación androgénica"),
    ("Lu-177 PSMA-617", "Lutecio-177 dirigido al antígeno prostático específico de membrana"),
    ("Radium-223", "Radio-223"),
    ("preferred", "preferente"),
    ("eligible", "elegible"),
    ("selected_candidate", "candidato seleccionado"),
    ("guideline-consistent", "alineado con las guías"),
    ("No applies", "No aplica"),
    ("aplica", "aplica"),
]

TOKEN_REPLACEMENTS = [
    (r"\bpsadt_months\b", "tiempo de duplicación del antígeno prostático específico"),
    (r"\bpsa_current\b", "antígeno prostático específico actual"),
    (r"\bpsa_postop\b", "antígeno prostático específico posoperatorio"),
    (r"\bclinical_tstage\b", "estadio clínico"),
    (r"\bisup_grade\b", "grupo de grado de la Sociedad Internacional de Patología Urológica"),
    (r"\bnum_cores_positive\b", "cilindros positivos"),
    (r"\btotal_cores\b", "cilindros totales"),
    (r"\bhrr_status\b", "estado de reparación por recombinación homóloga"),
    (r"\bmsi_status\b", "estado de inestabilidad microsatelital"),
    (r"\bipss_score\b", "puntaje internacional de síntomas prostáticos"),
    (r"\biief5_score\b", "índice internacional de función eréctil de 5 preguntas"),
    (r"\bPSADT\b(?!\))", "tiempo de duplicación del antígeno prostático específico (PSADT)"),
    (r"\bPSAD\b(?!\))", "densidad del antígeno prostático específico (PSAD)"),
    (r"\bPSA density\b", "densidad del antígeno prostático específico (PSAD)"),
    (r"\bPSA\b(?!\))", "antígeno prostático específico (PSA)"),
    (r"\bBCR2 N0M0\b", "segunda recurrencia bioquímica sin metástasis ni ganglios regionales comprometidos"),
    (r"\bBCR2\b(?!\))", "segunda recurrencia bioquímica (BCR2)"),
    (r"\bBCR\b(?!\))", "recurrencia bioquímica (BCR)"),
    (r"\bM1 CRPC\b(?!\))", "enfermedad resistente a la castración con metástasis (M1 CRPC)"),
    (r"\bM0 CRPC\b(?!\))", "enfermedad resistente a la castración sin metástasis (M0 CRPC)"),
    (r"\bmCSPC\b(?!\))", "enfermedad metastásica sensible a la castración (mCSPC)"),
    (r"\bCRPC\b(?!\))", "enfermedad resistente a la castración (CRPC)"),
    (r"\bADT\b(?!\))", "terapia de privación androgénica (ADT)"),
    (r"\bEBRT\b(?!\))", "radioterapia externa (EBRT)"),
    (r"(?<![-\w])RT\b(?!\))", "radioterapia (RT)"),
    (r"\bePLND\b(?!\))", "linfadenectomía pélvica extendida (ePLND)"),
    (r"\bPLND\b(?!\))", "linfadenectomía pélvica (PLND)"),
    (r"\bMSI-H\b(?!\))", "inestabilidad microsatelital alta (MSI-H)"),
    (r"\bMSI\b(?![-\w]|\))", "inestabilidad microsatelital (MSI)"),
    (r"\bHRR\b(?!\))", "reparación por recombinación homóloga (HRR)"),
    (r"\bALP\b(?!\))", "fosfatasa alcalina (ALP)"),
    (r"\bLDH\b(?!\))", "lactato deshidrogenasa (LDH)"),
    (r"\bIPSS\b(?!\))", "puntaje internacional de síntomas prostáticos (IPSS)"),
    (r"\bIIEF-5\b(?!\))", "índice internacional de función eréctil de 5 preguntas (IIEF-5)"),
    (r"\bEQ-5D\b(?!\))", "cuestionario EQ-5D"),
    (r"\bFACT-P\b(?!\))", "cuestionario FACT-P"),
    (r"\bECOG\b(?!\))", "estado funcional del Grupo Cooperativo Oncológico del Este (ECOG)"),
    (r"\bDM2\b(?!\))", "diabetes mellitus tipo 2"),
    (r"\bHTA\b(?!\))", "hipertensión arterial"),
    (r"\bSRE\b(?!\w)", "evento esquelético relacionado"),
    (r"\bCTCAE\b(?!\))", "Criterios Comunes de Terminología para Eventos Adversos (CTCAE)"),
    (r"\bPFS\b(?!\))", "supervivencia libre de progresión (PFS)"),
    (r"\bAUC\b(?!\))", "área bajo la curva (AUC)"),
    (r"\bNLP\b(?!\))", "procesamiento de lenguaje natural (NLP)"),
    (r"\bML\b(?!\))", "aprendizaje automático (ML)"),
    (r"\bUSA\b(?!\))", "Estados Unidos"),
    (r"\bMSS\b(?!\))", "estable a nivel microsatelital"),
    (r"\bRP\b(?!\))", "prostatectomía radical (RP)"),
    (r"\bSBRT\b(?!\))", "radioterapia corporal estereotáctica (SBRT)"),
    (r"\bMDT\b(?!\))", "terapia dirigida a metástasis (MDT)"),
    (r"\bARPI\b(?!\))", "inhibidor de la vía del receptor androgénico (ARPI)"),
    (r"(?<!panel )\bPROS-([A-Z0-9]+)\b", r"panel PROS-\1 de la guía de la Red Nacional Integral del Cáncer (NCCN)"),
    (r"(?<!estudio )\bCHAARTED\b", "estudio CHAARTED"),
    (r"(?<!estudio )\bLATITUDE\b", "estudio LATITUDE"),
    (r"(?<!estudio )\bARASENS\b", "estudio ARASENS"),
    (r"(?<!estudio )\bPEACE-1\b", "estudio PEACE-1"),
    (r"(?<!estudio )\bEMBARK\b", "estudio EMBARK"),
    (r"(?<!estudio )\bSPARTAN\b", "estudio SPARTAN"),
    (r"(?<!estudio )\bARAMIS\b", "estudio ARAMIS"),
    (r"(?<!estudio )\bPROSPER\b", "estudio PROSPER"),
    (r"(?<!estudio )\bRAVES\b", "estudio RAVES"),
    (r"(?<!estudio )\bRADICALS-RT\b", "estudio RADICALS-RT"),
    (r"(?<!estudio )\bGETUG-AFU 16\b", "estudio GETUG-AFU 16"),
    (r"(?<!estudio )\bRTOG 9601\b", "estudio RTOG 9601"),
    (r"(?<!estudio )\bPROfound\b", "estudio PROfound"),
    (r"(?<!estudio )\bVISION\b", "estudio VISION"),
    (r"(?<!estudio )\bKEYNOTE-158\b", "estudio KEYNOTE-158"),
]


def translate_text(value):
    if not isinstance(value, str):
        return value
    text = value
    for source, target in TEXT_REPLACEMENTS:
        text = text.replace(source, target)
    for pattern, target in TOKEN_REPLACEMENTS:
        text = re.sub(pattern, target, text)
    lowered = text.lower()
    if "NCCN" in text and "Red Nacional Integral del Cáncer (NCCN)" not in text:
        text = text.replace("NCCN", "Red Nacional Integral del Cáncer (NCCN)")
    if "EAU" in text and "Asociación Europea de Urología (EAU)" not in text:
        text = text.replace("EAU", "Asociación Europea de Urología (EAU)")
    if "capra-s" in lowered and "puntaje postoperatorio capra-s" not in lowered:
        text = text.replace("CAPRA-S", "puntaje postoperatorio CAPRA-S")
    lowered = text.lower()
    if "capra" in lowered and "capra-s" not in lowered and "puntaje pronóstico capra" not in lowered:
        text = text.replace("CAPRA", "puntaje pronóstico CAPRA")
    text = text.replace("estudios estudio ", "estudios ")
    text = text.replace("según el estudio estudio ", "según el estudio ")
    text = text.replace("según los estudios estudio ", "según los estudios ")
    return text


def _uses_boolean_option_labels(raw_options) -> bool:
    normalized = []
    for option in raw_options or []:
        if isinstance(option, dict):
            value = option.get("value")
        elif isinstance(option, (list, tuple)) and option:
            value = option[0]
        else:
            value = option
        normalized.append(str(value).strip())
    filtered = [option for option in normalized if option != ""]
    neutral_values = {
        "Desconocido",
        "desconocido",
        "Pendiente",
        "pendiente",
        "No disponible",
        "no disponible",
        "unknown",
    }
    decision_values = [option for option in filtered if option not in neutral_values]
    return set(decision_values) == {"0", "1"}


def _uses_graded_numeric_options(raw_options) -> bool:
    normalized = []
    for option in raw_options or []:
        if isinstance(option, dict):
            value = option.get("value")
        elif isinstance(option, (list, tuple)) and option:
            value = option[0]
        else:
            value = option
        normalized.append(str(value).strip())
    filtered = [
        option
        for option in normalized
        if option
        and option.lower() not in {"desconocido", "pendiente", "no disponible", "unknown"}
    ]
    return bool(filtered) and all(re.fullmatch(r"\d+(?:\.\d+)?", option) for option in filtered) and any(
        option not in {"0", "1"} for option in filtered
    )


def resolve_option_label(field_name: str, option, raw_options=None):
    option_key = str(option)
    semantic_label = semantic_option_label(field_name, option)
    if semantic_label is not None:
        return semantic_label
    explicit_labels = OPTION_LABELS.get(field_name, {})
    if option_key in explicit_labels:
        return explicit_labels[option_key]
    if _uses_boolean_option_labels(raw_options):
        contextual_labels = BOOLEAN_CONTEXTUAL_OPTION_LABELS.get(field_name, BOOLEAN_OPTION_LABELS)
        if option_key in contextual_labels:
            return contextual_labels[option_key]
    if _uses_graded_numeric_options(raw_options) and option_key not in {"", "Desconocido", "Pendiente", "No disponible", "unknown"}:
        return f"Grado {option_key}"
    return translate_text(option)


def _humanize_field(field: dict, *, optional_research: bool = False) -> dict:
    translated = deepcopy(field)
    semantics = field_semantics_for(translated.get("name", ""), optional_research=optional_research)
    translated["label"] = translate_text(translated.get("label", ""))
    translated["help_text"] = translate_text(translated.get("help_text", ""))
    translated["group"] = translate_text(translated.get("group", ""))
    translated["unit"] = translate_text(translated.get("unit", ""))
    translated["benchmark_note"] = translate_text(translated.get("benchmark_note", ""))
    translated["clinical_role"] = translated.get("clinical_role") or ("required" if translated.get("required") else "optional")
    translated["clinical_role_label"] = CLINICAL_ROLE_LABELS.get(translated["clinical_role"], translate_text(translated["clinical_role"]))
    translated["reuse_key"] = translated.get("reuse_key") or semantics["reuse_key"]
    translated["capture_layer"] = translated.get("capture_layer") or semantics["capture_layer"]
    translated["capture_layer_label"] = semantics["capture_layer_label"]
    translated["capture_layer_description"] = semantics["capture_layer_description"]
    translated["when_to_ask"] = translate_text(translated.get("when_to_ask") or semantics["when_to_ask"])
    translated["scale_descriptor"] = translate_text(translated.get("scale_descriptor") or semantics["scale_descriptor"])
    translated["score_interpretation"] = translate_text(translated.get("score_interpretation") or semantics["score_interpretation"])
    translated["reference_range_unit"] = translate_text(translated.get("reference_range_unit", ""))
    translated["reference_range_label"] = translate_text(translated.get("reference_range_label", ""))
    raw_options = translated.get("options", [])
    explicit_display_options = translated.get("display_options") or []
    display_options = []
    source_options = explicit_display_options or raw_options
    for option in source_options:
        if isinstance(option, dict):
            option_value = option.get("value")
            option_label = option.get("label") or resolve_option_label(translated.get("name"), option_value, raw_options)
            normalized_option = deepcopy(option)
            normalized_option["value"] = option_value
            normalized_option["label"] = translate_text(option_label)
            display_options.append(normalized_option)
            continue
        if isinstance(option, (list, tuple)) and len(option) >= 2:
            option_value = option[0]
            option_label = option[1]
            display_options.append(
                {
                    "value": option_value,
                    "label": translate_text(option_label),
                }
            )
            continue
        display_options.append(
            {
                "value": option,
                "label": resolve_option_label(translated.get("name"), option, raw_options),
            }
        )
    translated["display_options"] = display_options
    return translated


def humanize_schema(schema: dict) -> dict:
    translated = deepcopy(schema)
    translated["title"] = MODULE_TITLE_MAP.get(schema.get("module"), translate_text(schema.get("title", "")))
    translated["description"] = translate_text(schema.get("description", ""))
    translated["fields"] = [_humanize_field(field) for field in translated.get("fields", [])]
    translated["fields"] = _mark_wizard_alias_suppressions(translated["fields"])
    translated["fields"] = sorted(
        translated.get("fields", []),
        key=lambda item: (item.get("group_order", 0), item.get("label", "")),
    )
    return translated


def _mark_wizard_alias_suppressions(fields: list[dict]) -> list[dict]:
    names = {str(field.get("name") or "") for field in fields}
    out: list[dict] = []
    for field in fields:
        item = dict(field)
        name = str(item.get("name") or "")
        canonical = WIZARD_CANONICAL_ALIAS_SUPPRESSIONS.get(name)
        if canonical and canonical in names:
            item["suppress_in_wizard"] = True
            item["canonical_fact_key"] = canonical
            item["derived_from"] = list(dict.fromkeys([*(item.get("derived_from") or []), canonical]))
            item["clinical_role"] = item.get("clinical_role") or "derived"
            item["benchmark_note"] = item.get("benchmark_note") or (
                f"Alias compatible de {canonical}; el wizard V2 captura el valor canonico una sola vez."
            )
        out.append(item)
    return out


def humanize_module_listing(module: dict) -> dict:
    translated = deepcopy(module)
    translated["title"] = MODULE_TITLE_MAP.get(module.get("module"), translate_text(module.get("title", "")))
    translated["core_questions"] = [translate_text(item) for item in module.get("core_questions", [])]
    translated["pivotal_trials"] = [translate_text(item) for item in module.get("pivotal_trials", [])]
    translated["nccn_panels"] = [translate_text(item) for item in module.get("nccn_panels", [])]
    return translated


def humanize_registration_context(context: dict) -> dict:
    translated = deepcopy(context)
    translated["scope_label"] = translate_text(context.get("scope_label", ""))
    translated["scope_description"] = translate_text(context.get("scope_description", ""))
    translated["scope_bullets"] = [translate_text(item) for item in context.get("scope_bullets", [])]

    fragments = []
    for fragment in context.get("registration_fragments", []):
        humanized_fields = sorted(
            [
                _humanize_field(field, optional_research=fragment.get("optional_research", False))
                for field in fragment.get("fields", [])
            ],
            key=lambda item: (item.get("group_order", 0), item.get("label", "")),
        )
        fragments.append(
            {
                **fragment,
                "title": translate_text(fragment.get("title", "")),
                "persist_targets": [translate_text(item) for item in fragment.get("persist_targets", [])],
                "clinical_influence": [translate_text(item) for item in fragment.get("clinical_influence", [])],
                "capture_layer_label": translate_text(CAPTURE_LAYER_METADATA.get(fragment.get("capture_layer", ""), {}).get("label", "")),
                "when_to_ask": translate_text(fragment.get("when_to_ask", "")),
                "fields": humanized_fields,
            }
        )
    translated["registration_fragments"] = fragments
    translated["capture_layers"] = [
        {
            **layer,
            "label": translate_text(layer.get("label", "")),
            "description": translate_text(layer.get("description", "")),
        }
        for layer in context.get("capture_layers", [])
    ]
    translated["field_semantics"] = {
        key: {
            **value,
            "capture_layer_label": translate_text(value.get("capture_layer_label", "")),
            "capture_layer_description": translate_text(value.get("capture_layer_description", "")),
            "when_to_ask": translate_text(value.get("when_to_ask", "")),
            "scale_descriptor": translate_text(value.get("scale_descriptor", "")),
            "score_interpretation": translate_text(value.get("score_interpretation", "")),
        }
        for key, value in context.get("field_semantics", {}).items()
    }
    translated["score_semantics"] = {
        key: {
            "scale_descriptor": translate_text(value.get("scale_descriptor", "")),
            "score_interpretation": translate_text(value.get("score_interpretation", "")),
        }
        for key, value in context.get("score_semantics", {}).items()
    }
    translated["deduped_visible_fields"] = [
        {
            **item,
            "label": translate_text(item.get("label", "")),
            "capture_layer_label": translate_text(item.get("capture_layer_label", "")),
        }
        for item in context.get("deduped_visible_fields", [])
    ]

    imported_fields = []
    for item in context.get("imported_clinical_fields", []):
        semantics = field_semantics_for(item.get("name", ""))
        imported_fields.append(
            {
                **item,
                "label": translate_text(item.get("label", "")),
                "value_label": item.get("value_label") or resolve_option_label(item.get("name", ""), item.get("value"), item.get("options", [])),
                "clinical_role_label": CLINICAL_ROLE_LABELS.get(item.get("clinical_role", ""), translate_text(item.get("clinical_role", ""))),
                "persist_targets": [translate_text(value) for value in item.get("persist_targets", [])],
                "capture_layer_label": translate_text(item.get("capture_layer_label") or semantics.get("capture_layer_label", "")),
                "when_to_ask": translate_text(item.get("when_to_ask") or semantics.get("when_to_ask", "")),
            }
        )
    translated["imported_clinical_fields"] = imported_fields
    return translated


def humanize_guidelines(guidelines: dict[str, dict]) -> dict[str, dict]:
    translated = deepcopy(guidelines)
    for metadata in translated.values():
        metadata["summary"] = translate_text(metadata.get("summary", ""))
        metadata["guideline"] = translate_text(metadata.get("guideline", ""))
    return translated


def humanize_evidence(evidence: dict) -> dict:
    translated = deepcopy(evidence)
    translated["title"] = MODULE_TITLE_MAP.get(evidence.get("module"), translate_text(evidence.get("title", "")))
    translated["core_questions"] = [translate_text(item) for item in evidence.get("core_questions", [])]
    translated["pivotal_trials"] = [translate_text(item) for item in evidence.get("pivotal_trials", [])]
    translated["nccn_panels"] = [translate_text(item) for item in evidence.get("nccn_panels", [])]
    translated["eau_sections"] = [translate_text(item) for item in evidence.get("eau_sections", [])]
    translated["nccn"]["summary"] = translate_text(translated["nccn"].get("summary", ""))
    translated["eau"]["summary"] = translate_text(translated["eau"].get("summary", ""))
    translated["nccn"]["guideline"] = translate_text(translated["nccn"].get("guideline", ""))
    translated["eau"]["guideline"] = translate_text(translated["eau"].get("guideline", ""))
    translated["source_citations"] = humanize_sources(evidence.get("source_citations", []))
    return translated


def _humanize_value(value):
    if isinstance(value, dict):
        translated = {}
        for key, item in value.items():
            translated[key] = _humanize_value(item)
        return translated
    if isinstance(value, list):
        return [_humanize_value(item) for item in value]
    return translate_text(value)


def humanize_result(result: dict) -> dict:
    normalized = normalize_legacy_result(result)
    translated = _humanize_value(deepcopy(normalized))
    if normalized.get("trial_matches"):
        translated["trial_matches"] = _humanize_value(deepcopy(normalized.get("trial_matches", [])))
        for original, item in zip(normalized.get("trial_matches", []), translated["trial_matches"]):
            raw_trial = original.get("trial", "")
            raw_study_name = original.get("study_name", "")
            if raw_trial:
                item["trial_key"] = raw_trial
                item["trial_label"] = item.get("trial", "")
                item["trial"] = raw_trial
            if raw_study_name:
                item["study_name_key"] = raw_study_name
                item["study_name_label"] = item.get("study_name", "")
                item["study_name"] = raw_study_name
    if normalized.get("source_citations"):
        translated["source_citations"] = humanize_sources(normalized.get("source_citations", []))
    if normalized.get("validated_algorithms"):
        translated["validated_algorithms"] = _humanize_value(deepcopy(normalized.get("validated_algorithms", [])))
        for original, item in zip(normalized.get("validated_algorithms", []), translated["validated_algorithms"]):
            item["name"] = original.get("name", "")
            item["source_label"] = original.get("source_label", "")
            item["source_url"] = original.get("source_url", "")
    translated["state"] = result.get("state")
    translated["state_label"] = MODULE_TITLE_MAP.get(result.get("state"), translate_text(result.get("state", "")))
    translated["applicability_badge_key"] = result.get("applicability_badge")
    translated["applicability_badge"] = BADGE_LABELS.get(result.get("applicability_badge"), translate_text(result.get("applicability_badge", "")))
    return translated


def humanize_assessment(assessment: dict) -> dict:
    translated = deepcopy(assessment)
    translated["module_label"] = MODULE_TITLE_MAP.get(assessment.get("module_id"), translate_text(assessment.get("module_id", "")))
    translated["state_label"] = MODULE_TITLE_MAP.get(assessment.get("state"), translate_text(assessment.get("state", "")))
    translated["display_result"] = humanize_result(assessment.get("result_snapshot", {}))
    translated["display_guidelines"] = humanize_guidelines(assessment.get("guideline_versions", {}))
    return translated


def humanize_sources(sources: list[dict]) -> list[dict]:
    translated = _humanize_value(deepcopy(sources))
    for original, item in zip(sources, translated):
        item["citation_id"] = original.get("citation_id")
        item["title"] = original.get("title", "")
        item["guideline_or_trial"] = original.get("guideline_or_trial", "")
        item["doi_or_url"] = original.get("doi_or_url", "")
        item["local_pdf_path"] = original.get("local_pdf_path", "")
        item["document_id"] = original.get("document_id", "")
        item["evidence_role"] = original.get("evidence_role", "")
        item["license_class"] = original.get("license_class", "")
        item["applies_to_modules"] = original.get("applies_to_modules", [])
        item["derived_rule_ids"] = original.get("derived_rule_ids", [])
        item["field_implications"] = [translate_text(value) for value in original.get("field_implications", [])]
        item["ui_surfaces"] = original.get("ui_surfaces", [])
        item["private_index"] = original.get("private_index", {})
    return translated


def humanize_state_timeline(entries: list[dict]) -> list[dict]:
    translated = _humanize_value(deepcopy(entries))
    for original, item in zip(entries, translated):
        item["state_label"] = MODULE_TITLE_MAP.get(original.get("state"), translate_text(original.get("state", "")))
        item["event_kind_label"] = EVENT_KIND_LABELS.get(original.get("event_kind"), translate_text(original.get("event_kind", "")))
        item["management_intent_status_label"] = MANAGEMENT_INTENT_STATUS_LABELS.get(
            original.get("management_intent_status"),
            translate_text(original.get("management_intent_status", "")),
        )
    return translated


def humanize_care_overlays(overlays: list[dict]) -> list[dict]:
    return _humanize_value(deepcopy(overlays))


# ──────────────────────────────────────────────────────────────────────────
# Auditoría Pacientes Insignia 2026-04-21 (§B.3) — mensaje unificado para
# todas las emisiones de abiraterona con gate hepático (Child-Pugh B/C o
# `child_pugh_b_or_c` boolean). Se comparte entre 6 trials: LATITUDE,
# PEACE-1, COU-AA-301, COU-AA-302, PROpel, IPATential150.
# ──────────────────────────────────────────────────────────────────────────


def abiraterone_hepatic_contraindication_note(
    trial: str,
    alternative: str = "enzalutamida o darolutamida",
) -> str:
    """Mensaje homogéneo de `not_recommended` cuando la abiraterona está
    bloqueada por hepatopatía moderada/severa.

    `trial` — identificador corto del estudio/contexto (ej. "PROpel", "LATITUDE",
    "COU-AA-302").
    `alternative` — ARPI(s) alternativa(s) sugerida(s); default cubre la
    mayoría de escenarios (mHSPC y mCRPC post-ARPI naive).
    """
    return (
        f"Abiraterona no recomendada en {trial} por compromiso hepático "
        f"moderado/severo (Child-Pugh B/C o riesgo hepático documentado). "
        f"Considerar {alternative} como ARPI alternativa y monitoreo ALT/AST."
    )
