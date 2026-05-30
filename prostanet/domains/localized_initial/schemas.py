from __future__ import annotations

from dataclasses import replace

from prostanet.shared.advanced_support_fields import (
    advanced_staging_imaging_fields,
    oncologic_emergency_fields,
    pivotal_contraindication_fields,
    pivotal_gate_supporting_fields,
)
from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.epic26 import epic26_widget_config
from prostanet.shared.pcothercause import pcothercause_widget_config


_SYSTEMIC_PIVOTAL_VISIBILITY = {"show_systemic_pivotal_contraindications": ["1"]}


def _merge_visibility(existing: dict | None, required: dict) -> dict:
    if not existing:
        return dict(required)
    return {"__all__": [dict(required), dict(existing)]}


def _with_visibility(fields: list[FieldSpec], required: dict, *, role: str | None = None) -> list[FieldSpec]:
    return [
        replace(
            field,
            clinical_role=role if role is not None else field.clinical_role,
            conditional_visibility=_merge_visibility(field.conditional_visibility, required),
        )
        for field in fields
    ]


LOCALIZED_SCHEMA = module_schema(
    "localized_initial",
    "Diagnóstico inicial localizado o regional con ganglios regionales positivos y sin metástasis a distancia",
    "Estratificación de riesgo, vigilancia activa y elegibilidad terapéutica alineadas con la Red Nacional Integral del Cáncer (NCCN) 5.2026 y comparadas con la Asociación Europea de Urología (EAU) 2026.",
    fields=[
        FieldSpec("age", "Edad", "number", required=True, default=65, group="Contexto clínico", group_order=1, clinical_role="required", unit="años"),
        FieldSpec(
            "life_expectancy_years",
            "Esperanza de vida estimada",
            "occam_life_expectancy",
            default=15,
            group="Contexto clínico",
            group_order=1,
            clinical_role="decision_refiner",
            unit="años",
            evidence_tags=["nccn_primary", "eau_2026", "occam_pcothercause"],
            help_text="Se calcula automáticamente con el modelo público Other-Cause Comorbidity-Adjusted Mortality (OCCAM) y se ajusta con ECOG e índice de Charlson para la lógica local NCCN 2026.",
            benchmark_note="Ya no se captura como número manual. Si el valor derivado cae en ≤5 años o entre 5–10 años, modula de forma distinta el balance entre observación y tratamiento local definitivo según NCCN 2026.",
            widget_config=pcothercause_widget_config(),
        ),
        FieldSpec("occam_height_cm", "Talla para OCCAM", "number", default=170, group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", unit="cm", help_text="Capture la talla observada para derivar índice de masa corporal en el modelo público OCCAM."),
        FieldSpec("occam_weight_kg", "Peso para OCCAM", "number", default=78, group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", unit="kg", help_text="Capture el peso observado para derivar índice de masa corporal en el modelo público OCCAM."),
        FieldSpec("occam_diabetes", "Diabetes para OCCAM", "select", options=["0", "1"], default="0", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", display_options=[{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}]),
        FieldSpec("occam_hypertension", "Hipertensión para OCCAM", "select", options=["0", "1"], default="0", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", display_options=[{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}]),
        FieldSpec("occam_stroke", "Evento vascular cerebral previo para OCCAM", "select", options=["0", "1"], default="0", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", display_options=[{"value": "0", "label": "No"}, {"value": "1", "label": "Sí"}]),
        FieldSpec("occam_smoking_status", "Tabaquismo para OCCAM", "select", options=["never", "current", "former"], default="never", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", display_options=[{"value": "never", "label": "Nunca"}, {"value": "current", "label": "Actual"}, {"value": "former", "label": "Previo"}]),
        FieldSpec("occam_education", "Escolaridad para OCCAM", "select", options=["not_used", "less_than_9th", "9th_11th", "hs_graduate", "some_college", "college_graduate"], default="not_used", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", help_text="Opcional. Si no se usa, el sistema cambia a la variante pública sin escolaridad.", display_options=[{"value": "not_used", "label": "No usar en el modelo"}, {"value": "less_than_9th", "label": "Menos de 9° grado"}, {"value": "9th_11th", "label": "9°-11° grado"}, {"value": "hs_graduate", "label": "Preparatoria / bachillerato"}, {"value": "some_college", "label": "Algo de universidad"}, {"value": "college_graduate", "label": "Título universitario"}]),
        FieldSpec("occam_marital_status", "Estado civil para OCCAM", "select", options=["not_used", "married", "separated", "single"], default="not_used", group="Pronóstico de otras causas (OCCAM)", group_order=1, clinical_role="decision_refiner", help_text="Opcional. Si no se usa, el sistema cambia a la variante pública sin estado civil.", display_options=[{"value": "not_used", "label": "No usar en el modelo"}, {"value": "married", "label": "Casado o en unión libre"}, {"value": "separated", "label": "Antes casado / previamente en unión libre"}, {"value": "single", "label": "Nunca casado / convivencia no matrimonial"}]),
        FieldSpec("psa", "Antígeno prostático específico (PSA)", "number", required=True, default=8.5, group="Estadificación primaria", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("psad", "Densidad del antígeno prostático específico (PSAD)", "number", default="", group="Estadificación primaria", group_order=2, clinical_role="derived", unit="ng/mL/cc", derived_from=["psa", "prostate_volume_ml"], evidence_tags=["psad"], benchmark_note="Se calcula desde PSA y volumen prostático; se conserva compatibilidad si llega por API o registros históricos."),
        FieldSpec("clinical_tstage", "Estadio clínico T", "select", required=True, options=["T1c", "T2a", "T2b", "T2c", "T3a", "T3b", "T4"], default="T2a", group="Estadificación primaria", group_order=2, clinical_role="required"),
        FieldSpec("gleason_primary", "Gleason primario", "select", required=True, options=["3", "4", "5"], default="3", group="Patología de biopsia", group_order=3, clinical_role="required"),
        FieldSpec("gleason_secondary", "Gleason secundario", "select", required=True, options=["3", "4", "5"], default="4", group="Patología de biopsia", group_order=3, clinical_role="required"),
        FieldSpec("isup_grade", "Grupo de grado de la Sociedad Internacional de Patología Urológica (ISUP)", "select", required=True, options=["1", "2", "3", "4", "5"], default="2", group="Patología de biopsia", group_order=3, clinical_role="required"),
        FieldSpec("num_cores_positive", "Cores positivos", "number", required=True, default=2, group="Patología de biopsia", group_order=3, clinical_role="required", unit="cores"),
        FieldSpec("total_cores", "Cores totales", "number", required=True, default=12, group="Patología de biopsia", group_order=3, clinical_role="required", unit="cores"),
        FieldSpec("max_core_involvement", "Máximo compromiso por cilindro", "number", default=0.2, help_text="Use 0.20 para representar 20 % de compromiso.", group="Patología de biopsia", group_order=3, clinical_role="decision_refiner", unit="proporción"),
        FieldSpec("percent_pattern_4", "Porcentaje de patrón 4", "number", default=10, group="Patología de biopsia", group_order=3, clinical_role="decision_refiner", unit="%", evidence_tags=["active_surveillance", "risk_refinement"]),
        FieldSpec("cribriform_pattern", "Patrón cribiforme", "select", options=["0", "1"], default="0", group="Patología de biopsia", group_order=3, clinical_role="decision_refiner"),
        FieldSpec("intraductal_carcinoma", "Carcinoma intraductal", "select", options=["0", "1"], default="0", group="Patología de biopsia", group_order=3, clinical_role="decision_refiner"),
        FieldSpec("prior_mpmri", "Resonancia magnética previa disponible", "select", options=["0", "1"], default="1", group="Imagen y riesgo", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("prior_mpmri_pirads_score", "PI-RADS de la resonancia magnética previa", "select", options=["2", "3", "4", "5", "desconocido"], default="desconocido", group="Imagen y riesgo", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"], conditional_visibility={"prior_mpmri": ["1"]}),
        FieldSpec("prior_mpmri_targeted_biopsy_status", "Biopsia dirigida a lesión por resonancia magnética previa", "select", options=["si", "no", "desconocido"], default="desconocido", group="Imagen y riesgo", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"], conditional_visibility={"prior_mpmri": ["1"]}),
        # EPIC 9 Group A GAP-16 — biopsia confirmatoria de AS ya la consume
        # rules_nccn.py (_active_surveillance_position_core) pero la captura no
        # estaba expuesta; NCCN PROS-C (cat 1 muy bajo/bajo) exige confirmación
        # en 6-12 meses antes de anclar la elección de AS.
        FieldSpec(
            "confirmatory_biopsy_planned",
            "Biopsia confirmatoria de vigilancia activa planificada",
            "select",
            options=["0", "1"],
            default="0",
            group="Imagen y riesgo",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["active_surveillance", "nccn_pros_c"],
            display_options=[{"value": "0", "label": "No planificada"}, {"value": "1", "label": "Sí, planificada"}],
            help_text="NCCN PROS-C recomienda biopsia confirmatoria en los primeros 6-12 meses tras elegir vigilancia activa en riesgo muy bajo/bajo.",
        ),
        FieldSpec("prostate_volume_ml", "Volumen prostático", "number", default=40, group="Imagen y riesgo", group_order=4, clinical_role="decision_refiner", unit="mL", evidence_tags=["psad", "mpmri"]),
        FieldSpec("nodal_status", "Estado ganglionar", "select", options=["N0", "N1"], default="N0", group="Imagen y riesgo", group_order=4, clinical_role="required"),
        FieldSpec("metastasis_site", "Sitio de metástasis", "select", options=["M0"], default="M0", group="Imagen y riesgo", group_order=4, clinical_role="required"),
        # EPIC 8 — campos para evaluar candidatura a terapia focal (NCCN PROS-C cat 2B).
        # Se capturan en el flujo localizado para decidir si el paciente debe
        # ser derivado al módulo focal_therapy; no reemplazan la evaluación
        # completa que realiza ese dominio con todos sus gates.
        FieldSpec(
            "lesion_unilateral",
            "Lateralidad de la lesión índice en mpMRI",
            "select",
            options=["Desconocido", "Unilateral (afecta un solo lóbulo)", "Bilateral"],
            default="Desconocido",
            group="Imagen y riesgo",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["mpmri", "focal_eligibility"],
            help_text="Lesión unilateral documentada es requisito NCCN PROS-C categoría 2B para considerar terapia focal selectiva.",
        ),
        FieldSpec(
            "lesion_maxdim_mm",
            "Diámetro máximo de la lesión índice",
            "number",
            default="",
            group="Imagen y riesgo",
            group_order=4,
            clinical_role="decision_refiner",
            unit="mm",
            min_value=0.0,
            max_value=80.0,
            allow_negative=False,
            evidence_tags=["mpmri", "focal_eligibility"],
            help_text="Lesión ≤ 15 mm favorece control focal; > 15 mm requiere vigilancia post-procedimiento más estricta.",
        ),
        FieldSpec(
            "mri_psa_density",
            "Densidad PSA derivada de MRI (mpMRI)",
            "number",
            default="",
            group="Imagen y riesgo",
            group_order=4,
            clinical_role="derived",
            unit="ng/mL/cc",
            derived_from=["psa", "prostate_volume_ml"],
            evidence_tags=["mpmri", "psad"],
            help_text="Densidad PSA calculada sobre volumen prostático por mpMRI; útil para decisión AS vs terapia local o focal.",
        ),
        FieldSpec(
            "focal_therapy_candidate_profile",
            "Perfil de candidatura a terapia focal",
            "select",
            options=[
                "No evaluado",
                "Candidato — intermedio favorable unilateral",
                "No candidato — bilateral o alto riesgo",
                "Prefiere tratamiento de glándula entera",
                "Prefiere vigilancia activa",
            ],
            default="No evaluado",
            group="Imagen y riesgo",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["focal_eligibility", "shared_decision"],
        ),
        FieldSpec("ecog_score", "Estado funcional ECOG", "select", required=True, options=["0", "1", "2", "3", "4"], default="0", group="Aptitud para tratamiento local", group_order=6, clinical_role="required", evidence_tags=["performance_status"]),
        FieldSpec("charlson_score", "Índice de Charlson", "number", required=True, default=1, group="Aptitud para tratamiento local", group_order=6, clinical_role="required", unit="puntos", evidence_tags=["comorbidity"]),
        FieldSpec("frailty_status", "Fragilidad clínica", "select", required=True, options=["Fit", "Vulnerable", "Frail", "No documentado"], default="No documentado", group="Aptitud para tratamiento local", group_order=6, clinical_role="required", evidence_tags=["geriatric_screening"]),
        FieldSpec("g8_score", "Puntaje G8 geriátrico", "number", required=True, group="Aptitud para tratamiento local", group_order=6, clinical_role="required", unit="0-17", evidence_tags=["geriatric_screening"]),
        FieldSpec("anesthesia_surgical_fitness", "Aptitud anestésico-quirúrgica", "select", required=True, options=["Fit", "Vulnerable", "No apto", "No documentado"], default="No documentado", group="Aptitud para tratamiento local", group_order=6, clinical_role="required"),
        FieldSpec("baseline_obstruction", "Obstrucción urinaria basal", "select", options=["none", "mild", "moderate", "severe", "unknown"], default="unknown", group="Aptitud por modalidad local", group_order=6, clinical_role="decision_refiner"),
        FieldSpec("plnd_likely_indicated", "Disección ganglionar pélvica probablemente indicada", "select", options=["0", "1", "unknown"], default="unknown", group="Aptitud por modalidad local", group_order=6, clinical_role="decision_refiner"),
        FieldSpec("radiotherapy_feasibility", "Factibilidad radioterápica", "select", options=["feasible", "conditional", "not_feasible", "unknown"], default="unknown", group="Aptitud por modalidad local", group_order=6, clinical_role="decision_refiner"),
        FieldSpec("brachy_feasibility", "Factibilidad de braquiterapia", "select", options=["feasible", "conditional", "not_feasible", "not_applicable", "unknown"], default="unknown", group="Aptitud por modalidad local", group_order=6, clinical_role="decision_refiner"),
        FieldSpec("patient_priority_profile", "Perfil de prioridades del paciente", "text", help_text="Use etiquetas canónicas separadas por coma: maximize_cancer_control, preserve_urinary_function, preserve_sexual_function, avoid_bowel_toxicity, avoid_surgery, avoid_radiation, minimize_treatment_burden.", group="Aptitud por modalidad local", group_order=6, clinical_role="decision_refiner", evidence_tags=["shared_decision"]),
        FieldSpec("genomic_classifier", "Clasificador genómico", "select", options=["No realizado", "Decipher", "Prolaris", "Oncotype"], default="No realizado", group="Refinadores biológicos", group_order=5, clinical_role="optional", evidence_tags=["genomic_classifier"], benchmark_note="Captura opcional para benchmarking y refinamiento sin sobreescribir el riesgo de guías."),
        FieldSpec("genomic_classifier_result", "Resultado del clasificador genómico", "select", options=["No aplica", "Bajo", "Intermedio", "Alto"], default="No aplica", group="Refinadores biológicos", group_order=5, clinical_role="optional", evidence_tags=["genomic_classifier"], conditional_visibility={"genomic_classifier": ["Decipher", "Prolaris", "Oncotype"]}),
        FieldSpec("decipher_score_numeric", "Decipher score numérico", "number", default="", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", unit="score", min_value=0.0, max_value=1.0, allow_negative=False, evidence_tags=["genomic_classifier", "decipher", "spratt_2018"], conditional_visibility={"genomic_classifier": ["Decipher"]}, help_text="Veracyte Decipher 22-gen. Bandas: <0.45 bajo, 0.45–0.60 intermedio, ≥0.60 alto (Spratt 2018 HR 1.24 por 0.1 punto)."),
        FieldSpec("prolaris_ccp_score", "Prolaris CCP score", "number", default="", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", unit="log₂", min_value=-3.0, max_value=3.0, allow_negative=True, evidence_tags=["genomic_classifier", "prolaris", "cuzick_2012"], conditional_visibility={"genomic_classifier": ["Prolaris"]}, help_text="Myriad Prolaris CCP 31-gen. Bandas: <−1.0 bajo, −1.0 a +1.0 intermedio, ≥+1.0 alto."),
        FieldSpec("oncotype_gps", "Oncotype DX GPS", "number", default="", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", unit="0-100", min_value=0.0, max_value=100.0, allow_negative=False, evidence_tags=["genomic_classifier", "oncotype", "klein_2014"], conditional_visibility={"genomic_classifier": ["Oncotype"]}, help_text="Genomic Prostate Score. Bandas: <20 bajo, 20–40 intermedio, ≥40 alto (Klein 2014, Cullen 2015)."),
        FieldSpec("genomic_classifier_date", "Fecha del clasificador genómico", "date", group="Refinadores biológicos", group_order=5, clinical_role="monitoring", evidence_tags=["genomic_classifier"], conditional_visibility={"genomic_classifier": ["Decipher", "Prolaris", "Oncotype"]}, help_text="Frescura recomendada ≤ 180 días al momento de decidir vigilancia vs tratamiento definitivo."),
        FieldSpec("risk_calculator_pathway", "Pathway MRI + PSAD / calculadora", "select", options=["No usado", "EAU MRI + PSAD", "Calculadora externa"], default="No usado", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", evidence_tags=["benchmark"]),
        FieldSpec("family_history_positive", "Historia familiar relevante", "select", options=["0", "1"], default="0", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        FieldSpec("brca2_family_risk", "BRCA2 conocido o altamente sospechado", "select", options=["0", "1"], default="0", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", evidence_tags=["germline"]),
        FieldSpec("micro_us_available", "Micro-US disponible", "select", options=["0", "1"], default="0", group="Refinadores biológicos", group_order=5, clinical_role="optional", evidence_tags=["phase2_placeholder"]),
        FieldSpec("adverse_histology_variant_type", "Variante histológica adversa específica", "select", options=["none", "ductal_predominant", "sarcomatoid", "signet_ring", "adenosquamous_or_squamous", "basal_cell", "mucinous_colloid", "small_cell_neuroendocrine", "mixed_multiple", "other_aggressive"], default="none", group="Refinadores biológicos", group_order=5, clinical_role="decision_refiner", evidence_tags=["phase2_placeholder", "histology_variant"]),
        FieldSpec("adverse_histology_variant_detail", "Detalle de la variante histológica adversa", "text", group="Refinadores biológicos", group_order=5, clinical_role="optional", evidence_tags=["phase2_placeholder", "histology_variant"], conditional_visibility={"adverse_histology_variant_type": ["mixed_multiple", "other_aggressive"]}),
        FieldSpec("neuroendocrine_features", "Rasgos neuroendocrinos emergentes", "select", options=["0", "1"], default="0", group="Refinadores biológicos", group_order=5, clinical_role="optional", evidence_tags=["phase2_placeholder"]),
        FieldSpec(
            "epic26_response_packet",
            "EPIC-26 basal en español",
            "epic26_questionnaire",
            group="Refinadores RP vs RT",
            group_order=7,
            clinical_role="decision_refiner",
            help_text="Capture los ítems estructurados del EPIC-26 en español; el sistema recalcula los 5 dominios oficiales y la molestia urinaria global.",
            evidence_tags=["qol", "epic26"],
            widget_config=epic26_widget_config(),
        ),
        FieldSpec("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", default=8, group="Refinadores RP vs RT", group_order=7, clinical_role="decision_refiner", unit="0-35", evidence_tags=["qol"]),
        FieldSpec("iief5_score", "Índice internacional de función eréctil de 5 preguntas (IIEF-5)", "number", default=18, group="Refinadores RP vs RT", group_order=7, clinical_role="decision_refiner", unit="5-25", evidence_tags=["qol"]),
        # ── Estadificación M obligatoria + Gate B (RP en cT4) ──
        # NCCN PROS-2/PROS-3 v5.2026 cat 1; EAU 2026 §6.4.1-6.4.3 + §6.5.1.
        # ProPSMA (Hofman 2020) → PSMA PET/CT preferente.
        # Cierra brecha auditoría 2026-04-22 (paciente PSA 36 + cT4 sin staging).
        *advanced_staging_imaging_fields(
            psma_pet_done_role="decision_refiner",
            bone_scan_done_role="decision_refiner",
            cross_sectional_role="decision_refiner",
            include_local_invasion=True,
        ),
        # ── Triaje de emergencia oncológica (Brecha 2026-04-23) ────────
        # Reusable; aplica a todos los pacientes para detectar compresión
        # medular, hidronefrosis, hipercalcemia, fractura patológica antes
        # de cualquier decisión de tratamiento curativo.
        *oncologic_emergency_fields(role="decision_refiner"),
        FieldSpec(
            "show_systemic_pivotal_contraindications",
            "Abrir contraindicaciones sistémicas de ensayos pivote",
            "select",
            options=["0", "1"],
            default="0",
            group="Captura avanzada por etapa",
            group_order=79,
            clinical_role="decision_refiner",
            help_text=(
                "Abrir sólo si se planea intensificación sistémica, inclusión en ensayo, "
                "tratamiento fuera del circuito local estándar o revisión explícita de seguridad."
            ),
            evidence_tags=["pivotal_gates", "progressive_disclosure"],
            display_options=[
                {"value": "0", "label": "No abrir"},
                {"value": "1", "label": "Abrir seguridad sistémica"},
            ],
        ),
        # ── Contraindicaciones pivotal (Faubot 2026-04-23) ────────────
        # Aplica a la rama VERY HIGH (STAMPEDE arm G — RT+ADT+abiraterona)
        # y a cualquier régimen sistémico empírico desencadenado por gates
        # downstream. Captura HTA descontrolada, ICC NYHA III-IV y demás
        # contraindicaciones documentadas en los protocolos pivote.
        *_with_visibility(
            pivotal_contraindication_fields(group_order=80),
            _SYSTEMIC_PIVOTAL_VISIBILITY,
        ),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI de fields para gates de RP-vs-RT subspecialty (anticoag,
        # IBD, prior_pelvic_RT, TURP, SVI), genomic critical (HRR, AR-V7,
        # CDK12, HRD, MSI), pre-dx atypical (metastatic bx, NEPC, emergency,
        # PHI/4Kscore, 10 trials adicionales).
        *pivotal_gate_supporting_fields(group_order=81),
    ],
)
