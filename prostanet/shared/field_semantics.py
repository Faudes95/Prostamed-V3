from __future__ import annotations

from copy import deepcopy
from typing import Any

from prostanet.shared.advanced_support_catalog import (
    ADVANCED_VARIANT_HISTOLOGY_LABELS,
    COGNITIVE_SCREEN_SOURCE_LABELS,
    DDI_REVIEW_STATUS_LABELS,
    MINI_COG_OPTION_LABELS,
    pro_band_label_map,
)

CAPTURE_LAYER_METADATA: dict[str, dict[str, str]] = {
    "core_minimum": {
        "label": "Capa 1. Núcleo mínimo",
        "description": "Solo los datos que faltan para decidir hoy, abrir el expediente y sostener el basal clínico.",
    },
    "scenario_refiners": {
        "label": "Capa 2. Refinadores por escenario",
        "description": "Campos del estado activo que afinan la estadificación, el riesgo y la trayectoria clínica.",
    },
    "safety_eligibility": {
        "label": "Capa 3. Seguridad y elegibilidad",
        "description": "Se muestra solo cuando cambia elegibilidad terapéutica, contraindicaciones o vigilancia de seguridad.",
    },
    "research_optional": {
        "label": "Capa 4. Investigación y benchmarking",
        "description": "Opcional, no bloquea el registro y fortalece cohorte y benchmarking institucional.",
    },
}

FIELD_REUSE_KEYS: dict[str, str] = {
    "full_name": "identity_full_name",
    "nss": "identity_nss",
    "dob": "identity_dob",
    "baseline_psa": "psa_baseline",
    "psa_history": "psa_longitudinal_series",
    "ape_history": "psa_longitudinal_series",
    "testosterone_history": "testosterone_longitudinal_series",
    "gleason_score": "histopathology_gleason_profile",
    "gleason_primary": "histopathology_gleason_profile",
    "gleason_secondary": "histopathology_gleason_profile",
    "gleason_tertiary": "histopathology_gleason_profile",
    "isup_grade": "histopathology_gleason_profile",
    "ecog_score": "performance_ecog",
    "charlson_score": "charlson_score",
    "frailty_status": "frailty_status",
    "anesthesia_surgical_fitness": "anesthesia_surgical_fitness",
    "patient_priority_profile": "patient_priority_profile",
    "height_cm": "height_cm",
    "weight_loss_6m_pct": "recent_weight_loss",
    "weight_loss_6m_kg": "recent_weight_loss",
    "mini_cog_score": "cognition_screen",
    "fatigue_score": "fatigue_screen",
    "g8_food_intake": "g8_food_intake",
    "g8_weight_loss": "g8_weight_loss",
    "g8_mobility": "g8_mobility",
    "g8_neuropsych": "g8_neuropsych",
    "g8_bmi": "g8_bmi",
    "g8_medications": "g8_medications",
    "g8_self_health": "g8_self_health",
    "ipss_score": "ipss_score",
    "iief5_score": "iief5_score",
    "epic26_response_packet": "epic26_baseline_packet",
    "epic26_urinary_incontinence_domain": "epic26_baseline_packet",
    "epic26_urinary_irritative_domain": "epic26_baseline_packet",
    "epic26_bowel_domain": "epic26_baseline_packet",
    "epic26_sexual_domain": "epic26_baseline_packet",
    "epic26_hormonal_domain": "epic26_baseline_packet",
    "epic26_overall_urinary_bother": "epic26_baseline_packet",
    "risk_calculator_pathway": "risk_calculator_pathway",
    "metastasis_site": "metastatic_status",
    "volume_disease": "metastatic_volume",
    "metastatic_components_capture": "metastatic_composition_structured",
    "bone_site_entries": "metastatic_composition_structured",
    "visceral_site_entries": "metastatic_composition_structured",
    "nonregional_nodal_site_entries": "metastatic_composition_structured",
    "rare_histology_variant": "rare_histology_variant",
    "adverse_histology_variant_type": "rare_histology_variant",
    "eq5d_vas_band": "qol_eq5d_band",
    "fact_p_total_band": "qol_fact_p_band",
    "bpi_worst_pain_band": "pain_bpi_band",
    "fatigue_score_band": "fatigue_band",
    "ddi_review_status": "ddi_review_status",
    "active_liver_disease": "hepatic_safety_bundle",
    "cirrhosis_or_portal_hypertension": "hepatic_safety_bundle",
    "active_hepatitis_b_or_c": "hepatic_safety_bundle",
    "prior_drug_induced_liver_injury": "hepatic_safety_bundle",
    "mini_cog_date": "cognition_screen",
    "cognitive_screen_source": "cognition_screen",
    "neuroendocrine_features": "neuroendocrine_features",
    "line_of_therapy_number": "systemic_line_number",
    "drug_scheme": "systemic_regimen",
    "current_adt_context": "current_adt_context",
    "castrate_testosterone_status": "castrate_testosterone_status",
    "child_pugh_score": "child_pugh_score",
    "peripheral_neuropathy_grade": "peripheral_neuropathy_grade",
    "psma_rads_score": "psma_rads_score",
}

FIELD_CAPTURE_LAYERS: dict[str, str] = {
    "full_name": "core_minimum",
    "nss": "core_minimum",
    "dob": "core_minimum",
    "baseline_psa": "core_minimum",
    "psa_history": "core_minimum",
    "ape_history": "core_minimum",
    "testosterone_history": "core_minimum",
    "histology_subtype": "core_minimum",
    "gleason_score": "core_minimum",
    "gleason_primary": "core_minimum",
    "gleason_secondary": "core_minimum",
    "gleason_tertiary": "core_minimum",
    "isup_grade": "core_minimum",
    "clinical_tstage": "core_minimum",
    "nodal_status": "core_minimum",
    "clinical_stage_group": "core_minimum",
    "clinical_risk_group": "core_minimum",
    "ecog_score": "core_minimum",
    "charlson_score": "core_minimum",
    "frailty_status": "core_minimum",
    "g8_score": "core_minimum",
    "anesthesia_surgical_fitness": "core_minimum",
    "baseline_urinary_qol": "scenario_refiners",
    "baseline_sexual_qol": "scenario_refiners",
    "epic26_response_packet": "scenario_refiners",
    "epic26_urinary_incontinence_domain": "scenario_refiners",
    "epic26_urinary_irritative_domain": "scenario_refiners",
    "epic26_bowel_domain": "scenario_refiners",
    "epic26_sexual_domain": "scenario_refiners",
    "epic26_hormonal_domain": "scenario_refiners",
    "epic26_overall_urinary_bother": "scenario_refiners",
    "family_history_detail": "scenario_refiners",
    "ipss_score": "scenario_refiners",
    "iief5_score": "scenario_refiners",
    "patient_priority_profile": "scenario_refiners",
    "line_of_therapy_number": "scenario_refiners",
    "line_of_therapy_context": "scenario_refiners",
    "drug_scheme": "scenario_refiners",
    "current_adt_context": "scenario_refiners",
    "castrate_testosterone_status": "scenario_refiners",
    "adverse_histology_variant_type": "scenario_refiners",
    "adverse_histology_variant_detail": "scenario_refiners",
    "variant_histology_report_date": "scenario_refiners",
    "variant_histology_source": "scenario_refiners",
    "conventional_imaging_status": "scenario_refiners",
    "hrr_status": "scenario_refiners",
    "hrr_gene": "scenario_refiners",
    "brca2_status": "scenario_refiners",
    "msi_status": "scenario_refiners",
    "tmb_high": "scenario_refiners",
    "biomarker_source": "scenario_refiners",
    "molecular_assay_date": "scenario_refiners",
    "psma_positive": "scenario_refiners",
    "psma_negative_dominant_lesions": "scenario_refiners",
    "metastatic_components_capture": "scenario_refiners",
    "metastatic_total_lesion_count": "scenario_refiners",
    "metastasis_assessment_date": "scenario_refiners",
    "metastasis_document_source": "scenario_refiners",
    "weight_kg": "safety_eligibility",
    "height_cm": "safety_eligibility",
    "bmi_current": "safety_eligibility",
    "weight_loss_6m_pct": "safety_eligibility",
    "weight_loss_6m_kg": "safety_eligibility",
    "mini_cog_score": "safety_eligibility",
    "mini_cog_date": "safety_eligibility",
    "cognitive_screen_source": "safety_eligibility",
    "fatigue_score": "safety_eligibility",
    "eq5d_vas_band": "safety_eligibility",
    "fact_p_total_band": "safety_eligibility",
    "bpi_worst_pain_band": "safety_eligibility",
    "fatigue_score_band": "safety_eligibility",
    "active_liver_disease": "safety_eligibility",
    "cirrhosis_or_portal_hypertension": "safety_eligibility",
    "active_hepatitis_b_or_c": "safety_eligibility",
    "prior_drug_induced_liver_injury": "safety_eligibility",
    "ddi_review_status": "safety_eligibility",
    "g8_food_intake": "safety_eligibility",
    "g8_weight_loss": "safety_eligibility",
    "g8_mobility": "safety_eligibility",
    "g8_neuropsych": "safety_eligibility",
    "g8_bmi": "safety_eligibility",
    "g8_medications": "safety_eligibility",
    "g8_self_health": "safety_eligibility",
    "low_activity": "safety_eligibility",
    "slow_gait": "safety_eligibility",
    "weak_grip": "safety_eligibility",
    "peripheral_neuropathy_grade": "safety_eligibility",
    "seizure_history": "safety_eligibility",
    "dermatitis_history": "safety_eligibility",
    "dxa_baseline_done": "safety_eligibility",
    "calcium_vitd_started": "safety_eligibility",
    "bone_protection_started": "safety_eligibility",
    "estado_residencia": "research_optional",
    "seguridad_social": "research_optional",
    "escolaridad": "research_optional",
    "ocupacion": "research_optional",
    "estado_civil": "research_optional",
    "tabaquismo": "research_optional",
    "paquetes_anio": "research_optional",
    "actividad_fisica": "research_optional",
    "diabetes_mellitus": "research_optional",
    "hipertension": "research_optional",
    "sindrome_metabolico": "research_optional",
}

FIELD_WHEN_TO_ASK: dict[str, str] = {
    "baseline_psa": "Pídalo siempre que falte el APE basal clínicamente útil.",
    "psa_history": "Úselo cuando ya exista más de una medición de APE/PSA y quiera preservar la dinámica longitudinal desde el ingreso.",
    "testosterone_history": "Úselo cuando ya exista más de una testosterona documentada y quiera preservar la serie longitudinal para verificación de castración y CRPC.",
    "gleason_score": "Úselo cuando necesite capturar el patrón Gleason formal, derivar el ISUP y sostener el diagnóstico principal con histopatología estructurada.",
    "ecog_score": "Pregúntelo cuando cambie elegibilidad terapéutica o la tolerancia esperada.",
    "charlson_score": "Úselo para capturar comorbilidad con una escala objetiva y reproducible antes de cerrar candidacidad quirúrgica.",
    "frailty_status": "Pregúntelo cuando la intensidad terapéutica pueda cambiar por fragilidad.",
    "g8_score": "Úselo como cribado geriátrico estructurado cuando la decisión local dependa de reserva funcional real y no de impresión subjetiva.",
    "anesthesia_surgical_fitness": "Úselo para documentar aptitud quirúrgica real antes de decidir prostatectomía radical.",
    "mini_cog_score": "Úselo si hay sospecha de vulnerabilidad cognitiva o selección fina entre ARPI/quimioterapia.",
    "height_cm": "Úselo para calcular automáticamente el IMC basal y evitar un BMI manual inconsistente.",
    "weight_loss_6m_kg": "Úselo para documentar pérdida ponderal real en kilogramos; el sistema deriva automáticamente el porcentaje legacy.",
    "fatigue_score": "Úselo cuando la carga sintomática pueda modificar tolerancia o priorización.",
    "eq5d_vas_band": "Úselo en enfermedad avanzada para registrar rápidamente calidad de vida global basal con una banda validada y clínicamente interpretable.",
    "fact_p_total_band": "Úselo en enfermedad avanzada para capturar calidad de vida específica de próstata avanzada sin exigir al clínico recordar el significado de cada rango.",
    "bpi_worst_pain_band": "Úselo cuando el dolor basal pueda cambiar soporte sintomático, sospecha de progresión o tolerancia terapéutica.",
    "fatigue_score_band": "Úselo cuando la fatiga basal pueda cambiar elegibilidad, intensidad o seguimiento del tratamiento.",
    "ddi_review_status": "Úselo cuando haya medicación concomitante y la elección del tratamiento dependa de cerrar una revisión DDI real, no solo de documentar polifarmacia.",
    "active_liver_disease": "Úselo para sustituir el proxy binario de riesgo hepático y sostener decisiones sobre abiraterona, taxanos y monitoreo.",
    "adverse_histology_variant_type": "Úselo cuando exista una variante histológica agresiva porque el subtipo exacto puede cambiar tratamiento, copy y necesidad de tumor board.",
    "ipss_score": "Úselo si la carga urinaria modifica la decisión local o la línea basal funcional.",
    "iief5_score": "Úselo cuando la función sexual basal sea relevante para comparar estrategias locales.",
    "epic26_response_packet": "Úselo en localizada para capturar el EPIC-26 basal completo y derivar sus dominios oficiales sin pedir puntajes manuales 0-100.",
    "patient_priority_profile": "Úselo para cerrar decisión compartida cuando cirugía y radioterapia siguen siendo plausibles tras resolver candidacidad objetiva.",
    "line_of_therapy_number": "Solo en enfermedad avanzada o si la línea terapéutica cambia conducta hoy.",
    "drug_scheme": "Solo cuando exista tratamiento sistémico actual o la secuenciación dependa del esquema activo.",
    "current_adt_context": "Solo si el estado avanzado depende de exposición/castración actual.",
    "castrate_testosterone_status": "Solo si la confirmación de castración cambia la estadificación o elegibilidad.",
    "metastatic_components_capture": "Úselo cuando la composición anatómica metastásica ya cambie el fenotipo, el volumen, la narrativa clínica o la elegibilidad terapéutica.",
}

FIELD_SCALE_SEMANTICS: dict[str, dict[str, Any]] = {
    "ecog_score": {
        "scale_descriptor": "ECOG 0-4: cuantifica desempeño funcional basal.",
        "score_interpretation": "0 completamente activo; 1 limitado para actividad extenuante; 2 ambulatorio >50% del día; 3 cama/silla >50%; 4 totalmente postrado.",
        "options": {
            "": "Seleccionar",
            "0": "0 - Completamente activo",
            "1": "1 - Limitación leve, ambulatorio",
            "2": "2 - Ambulatorio, incapaz de trabajar",
            "3": "3 - En cama o silla más del 50% del día",
            "4": "4 - Totalmente postrado",
        },
    },
    "g8_food_intake": {
        "scale_descriptor": "G8: cambio reciente en la ingesta alimentaria.",
        "score_interpretation": "El G8 total ≤14 sugiere vulnerabilidad geriátrica y justifica valorar fragilidad con mayor profundidad.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - Disminución severa de la ingesta",
            "1": "1 punto - Disminución moderada de la ingesta",
            "2": "2 puntos - Sin disminución de la ingesta",
        },
    },
    "g8_weight_loss": {
        "scale_descriptor": "G8: pérdida de peso en los últimos 3 meses.",
        "score_interpretation": "Un puntaje menor empuja el perfil hacia mayor vulnerabilidad nutricional.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - Pérdida mayor de 3 kg",
            "1": "1 punto - No sabe",
            "2": "2 puntos - Pérdida entre 1 y 3 kg",
            "3": "3 puntos - Sin pérdida de peso",
        },
    },
    "g8_mobility": {
        "scale_descriptor": "G8: movilidad basal del paciente.",
        "score_interpretation": "La movilidad reducida incrementa fragilidad y cambia tolerancia terapéutica esperada.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - En cama o silla",
            "1": "1 punto - Se levanta pero no sale de casa",
            "2": "2 puntos - Sale de casa",
        },
    },
    "g8_neuropsych": {
        "scale_descriptor": "G8: estado neuropsicológico basal.",
        "score_interpretation": "Útil para reconocer vulnerabilidad cognitiva o afectiva relevante para elegibilidad y soporte.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - Demencia o depresión severa",
            "1": "1 punto - Deterioro leve",
            "2": "2 puntos - Sin problema relevante",
        },
    },
    "g8_bmi": {
        "scale_descriptor": "G8: categoría de IMC.",
        "score_interpretation": "El puntaje disminuye con IMC más bajo y fragilidad nutricional.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - IMC menor de 19",
            "1": "1 punto - IMC 19 a menor de 21",
            "2": "2 puntos - IMC 21 a menor de 23",
            "3": "3 puntos - IMC 23 o mayor",
        },
    },
    "g8_medications": {
        "scale_descriptor": "G8: carga de polifarmacia.",
        "score_interpretation": "Ayuda a anticipar fragilidad y riesgo de interacciones.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - Toma más de 3 medicamentos al día",
            "1": "1 punto - Toma 3 o menos medicamentos al día",
        },
    },
    "g8_self_health": {
        "scale_descriptor": "G8: autopercepción de salud comparada con personas de su edad.",
        "score_interpretation": "Integra percepción funcional global y ayuda a contextualizar vulnerabilidad clínica.",
        "options": {
            "": "Seleccionar",
            "0": "0 puntos - Peor",
            "0.5": "0.5 puntos - No sabe",
            "1": "1 punto - Igual",
            "2": "2 puntos - Mejor",
        },
    },
    "mini_cog_score": {
        "scale_descriptor": "Mini-Cog 0-5: tamiz cognitivo breve.",
        "score_interpretation": "0-2 sugiere compromiso cognitivo y requiere cautela; 3-5 hace menos probable un deterioro significativo.",
        "options": MINI_COG_OPTION_LABELS,
    },
    "cognitive_screen_source": {
        "scale_descriptor": "Fuente del cribado cognitivo basal.",
        "score_interpretation": "Aclara si el Mini-Cog proviene de consulta, cuidador o documento externo y mejora trazabilidad clínica.",
        "options": COGNITIVE_SCREEN_SOURCE_LABELS,
    },
    "fatigue_score": {
        "scale_descriptor": "Fatiga 0-10: más alto implica mayor carga sintomática.",
        "score_interpretation": "0-3 leve; 4-6 moderada; 7-10 severa. Puede modificar tolerancia y priorización terapéutica.",
    },
    "eq5d_vas_band": {
        "scale_descriptor": "EQ-5D VAS agrupado en bandas clínicamente interpretables.",
        "score_interpretation": "La banda seleccionada autopuebla un valor representativo canónico, pero mantiene el significado clínico del rango.",
        "options": pro_band_label_map("eq5d_vas_band"),
    },
    "fact_p_total_band": {
        "scale_descriptor": "FACT-P agrupado en bandas clínicamente interpretables.",
        "score_interpretation": "Permite documentar rápidamente carga funcional y sintomática específica de próstata avanzada.",
        "options": pro_band_label_map("fact_p_total_band"),
    },
    "bpi_worst_pain_band": {
        "scale_descriptor": "BPI dolor peor agrupado por severidad clínica.",
        "score_interpretation": "Identifica de inmediato si el dolor basal es leve, moderado o severo.",
        "options": pro_band_label_map("bpi_worst_pain_band"),
    },
    "fatigue_score_band": {
        "scale_descriptor": "Fatiga 0-10 agrupada por carga sintomática.",
        "score_interpretation": "La banda seleccionada se convierte a un valor representativo para el motor clínico.",
        "options": pro_band_label_map("fatigue_score_band"),
    },
    "ddi_review_status": {
        "scale_descriptor": "Estado operativo de la revisión de interacciones farmacológicas.",
        "score_interpretation": "Permite diferenciar una lista de fármacos solo capturada de una revisión DDI ya cerrada.",
        "options": DDI_REVIEW_STATUS_LABELS,
    },
    "adverse_histology_variant_type": {
        "scale_descriptor": "Subtipo estructurado de variante histológica agresiva.",
        "score_interpretation": "Evita un booleano inespecífico y permite reconocer subtipos que exigen revisión experta o redirección terapéutica.",
        "options": ADVANCED_VARIANT_HISTOLOGY_LABELS,
    },
    "ipss_score": {
        "scale_descriptor": "IPSS 0-35: severidad de síntomas urinarios.",
        "score_interpretation": "0-7 leve; 8-19 moderado; 20-35 severo. Ayuda a valorar impacto funcional y estrategia local.",
    },
    "iief5_score": {
        "scale_descriptor": "IIEF-5 5-25: función eréctil basal.",
        "score_interpretation": "22-25 sin disfunción; 17-21 leve; 12-16 leve-moderada; 8-11 moderada; 5-7 severa.",
    },
    "child_pugh_score": {
        "scale_descriptor": "Child-Pugh: reserva hepática clínica.",
        "score_interpretation": "A reserva conservada; B compromiso moderado; C compromiso severo. Impacta elegibilidad y seguridad de terapias.",
        "options": {
            "": "Seleccionar",
            "A": "A - Reserva hepática conservada",
            "B": "B - Compromiso hepático moderado",
            "C": "C - Compromiso hepático severo",
        },
    },
    "peripheral_neuropathy_grade": {
        "scale_descriptor": "Neuropatía periférica CTCAE 0-4.",
        "score_interpretation": "Grados más altos elevan riesgo funcional y pueden limitar taxanos u otras estrategias.",
        "options": {
            "": "Seleccionar",
            "0": "Grado 0 - Ausente",
            "1": "Grado 1 - Leve",
            "2": "Grado 2 - Moderada",
            "3": "Grado 3 - Severa",
            "4": "Grado 4 - Discapacitante",
        },
    },
    "psma_rads_score": {
        "scale_descriptor": "PSMA-RADS: confianza estructurada de captación PSMA.",
        "score_interpretation": "Puntajes más altos apoyan mayor certeza de enfermedad PSMA-positiva y elegibilidad radioligando según contexto.",
        "options": {
            "": "Seleccionar",
            "1": "PSMA-RADS 1 - Benigno",
            "2": "PSMA-RADS 2 - Probablemente benigno",
            "3": "PSMA-RADS 3 - Indeterminado",
            "4": "PSMA-RADS 4 - Probablemente maligno",
            "5": "PSMA-RADS 5 - Altamente probable malignidad",
        },
    },
}


def field_reuse_key(field_name: str) -> str:
    return FIELD_REUSE_KEYS.get(field_name, field_name)


def field_capture_layer(field_name: str, *, optional_research: bool = False) -> str:
    if optional_research:
        return "research_optional"
    return FIELD_CAPTURE_LAYERS.get(field_name, "scenario_refiners")


def field_when_to_ask(field_name: str) -> str:
    return FIELD_WHEN_TO_ASK.get(field_name, "")


def field_scale_semantics(field_name: str) -> dict[str, Any]:
    return deepcopy(FIELD_SCALE_SEMANTICS.get(field_name, {}))


def semantic_option_label(field_name: str, option: Any) -> str | None:
    option_key = str(option)
    options = FIELD_SCALE_SEMANTICS.get(field_name, {}).get("options", {})
    if option_key in options:
        return options[option_key]
    return None


def field_semantics_for(field_name: str, *, optional_research: bool = False) -> dict[str, Any]:
    scale = field_scale_semantics(field_name)
    capture_layer = field_capture_layer(field_name, optional_research=optional_research)
    layer_meta = CAPTURE_LAYER_METADATA.get(capture_layer, {})
    return {
        "reuse_key": field_reuse_key(field_name),
        "capture_layer": capture_layer,
        "capture_layer_label": layer_meta.get("label", ""),
        "capture_layer_description": layer_meta.get("description", ""),
        "when_to_ask": field_when_to_ask(field_name),
        "scale_descriptor": scale.get("scale_descriptor", ""),
        "score_interpretation": scale.get("score_interpretation", ""),
    }


def build_score_semantics(field_names: list[str]) -> dict[str, dict[str, Any]]:
    semantics: dict[str, dict[str, Any]] = {}
    for field_name in field_names:
        meta = field_scale_semantics(field_name)
        if not meta:
            continue
        semantics[field_name] = {
            "scale_descriptor": meta.get("scale_descriptor", ""),
            "score_interpretation": meta.get("score_interpretation", ""),
        }
    return semantics
