from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


POST_RT_FOLLOWUP_SCHEMA = module_schema(
    "post_radiotherapy_followup",
    "Seguimiento después de radioterapia radical",
    "Vigilancia post-radioterapia (NCCN PROS-9 / EAU 2026): cinética PSA con criterio Phoenix, manejo de toxicidad tardía RTOG/EORTC, vigilancia de segundos primarios pélvicos y survivorship asociado a ADT.",
    fields=[
        # Grupo 1 - Contexto del tratamiento RT
        FieldSpec("prior_radiation", "Radioterapia radical previa", "select", required=True, options=["0", "1"], default="1", group="Contexto del tratamiento RT", group_order=1, clinical_role="required"),
        FieldSpec("prior_prostatectomy", "Prostatectomía radical previa", "select", required=True, options=["0", "1"], default="0", group="Contexto del tratamiento RT", group_order=1, clinical_role="required"),
        FieldSpec(
            "prior_rt_modality",
            "Modalidad de radioterapia",
            "select",
            required=True,
            options=["EBRT 3D", "IMRT", "VMAT", "SBRT", "Brachy LDR", "Brachy HDR", "EBRT + Brachy boost", "Protonterapia"],
            default="IMRT",
            group="Contexto del tratamiento RT",
            group_order=1,
            clinical_role="required",
            evidence_tags=["NCCN PROS-3", "ASCENDE-RT", "PACE-B"],
        ),
        FieldSpec("prior_rt_dose_gy", "Dosis total al PTV (Gy)", "number", default=78, group="Contexto del tratamiento RT", group_order=1, clinical_role="decision_refiner", unit="Gy"),
        FieldSpec("prior_rt_fractions", "Número de fracciones", "number", default=39, group="Contexto del tratamiento RT", group_order=1, clinical_role="monitoring"),
        FieldSpec("prior_rt_completion_date", "Fecha de fin de RT", "date", required=True, group="Contexto del tratamiento RT", group_order=1, clinical_role="required"),
        FieldSpec("prior_rt_intent", "Intención del tratamiento RT", "select", options=["Definitive", "Adjuvant", "Salvage post-RP"], default="Definitive", group="Contexto del tratamiento RT", group_order=1, clinical_role="decision_refiner"),
        FieldSpec(
            "concurrent_adt_history",
            "Historia de ADT concomitante",
            "select",
            required=True,
            options=["Sin ADT", "Neoadyuvante (2-4m)", "Corto (4-6m)", "Largo (18-36m)", "Adyuvante en curso"],
            default="Sin ADT",
            group="Contexto del tratamiento RT",
            group_order=1,
            clinical_role="required",
            evidence_tags=["RTOG 9408", "DART01/05"],
        ),
        # EPIC 14b smart-form: adt_duration_months solo aplica si paciente
        # recibió ADT alguna vez. ADT con prior_rt_intent="Definitive" en
        # Low risk RT-only típicamente NO recibe ADT. Mostrar duration solo
        # si adt_active=1 OR (intent diferente a Low risk Definitive sola).
        # Para simplicidad y seguridad clínica: visible si adt_active=1
        # (caso obvio) — duración 0 sigue capturable manualmente por entrada
        # histórica completada.
        # Beneficio clínico: reduce form fatigue en RT-only low risk donde
        # ADT no se ofreció; preserva captura para todos los demás escenarios.
        FieldSpec("adt_duration_months", "Duración total ADT (meses)", "number", default=0, group="Contexto del tratamiento RT", group_order=1, clinical_role="decision_refiner", unit="meses", conditional_visibility={"adt_active": ["1"]}),
        FieldSpec("adt_active", "ADT activo en este momento", "select", required=True, options=["0", "1"], default="0", group="Contexto del tratamiento RT", group_order=1, clinical_role="required"),
        FieldSpec(
            "risk_group_at_treatment",
            "Grupo de riesgo NCCN al tratamiento",
            "select",
            options=["Low", "Favorable Intermediate", "Unfavorable Intermediate", "High", "Very High"],
            default="Unfavorable Intermediate",
            group="Contexto del tratamiento RT",
            group_order=1,
            clinical_role="decision_refiner",
        ),
        FieldSpec("gleason_at_diagnosis", "Grade Group al diagnóstico", "number", default=2, group="Contexto del tratamiento RT", group_order=1, clinical_role="monitoring"),
        FieldSpec("psa_at_diagnosis", "PSA basal pre-RT (ng/mL)", "number", default=10, group="Contexto del tratamiento RT", group_order=1, clinical_role="monitoring", unit="ng/mL"),
        FieldSpec("clinical_tstage_at_treatment", "Estadio clínico T al tratamiento", "select", options=["T1c", "T2a", "T2b", "T2c", "T3a", "T3b", "T4"], default="T2a", group="Contexto del tratamiento RT", group_order=1, clinical_role="monitoring"),

        # Grupo 2 - Confirmación de respuesta y nadir
        FieldSpec("psa_current", "PSA actual (ng/mL)", "number", required=True, default=0.4, group="Cinética PSA y nadir", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_current_date", "Fecha del PSA actual", "date", required=True, group="Cinética PSA y nadir", group_order=2, clinical_role="required"),
        FieldSpec("psa_nadir", "PSA nadir post-RT (ng/mL)", "number", required=True, default=0.3, group="Cinética PSA y nadir", group_order=2, clinical_role="required", unit="ng/mL", evidence_tags=["Crook 2006"]),
        FieldSpec("psa_nadir_date", "Fecha del PSA nadir", "date", group="Cinética PSA y nadir", group_order=2, clinical_role="decision_refiner"),
        FieldSpec("time_to_nadir_months", "Tiempo a nadir (meses)", "number", default=24, group="Cinética PSA y nadir", group_order=2, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("phoenix_failure_confirmed", "Phoenix confirmado en 2da medición", "select", options=["0", "1"], default="0", group="Cinética PSA y nadir", group_order=2, clinical_role="monitoring", evidence_tags=["Roach 2006 IJROBP"]),
        FieldSpec("psa_doubling_time_months", "PSA doubling time (meses)", "number", default=0, group="Cinética PSA y nadir", group_order=2, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("bounce_suspected", "Bounce post-braquiterapia sospechado", "select", options=["0", "1"], default="0", group="Cinética PSA y nadir", group_order=2, clinical_role="monitoring", evidence_tags=["ABS brachytherapy consensus"]),
        FieldSpec("psa_history_summary", "Resumen narrativo de la trayectoria PSA", "text", default="", group="Cinética PSA y nadir", group_order=2, clinical_role="monitoring"),

        # Grupo 3 - Toxicidad tardía urinaria
        FieldSpec("late_urinary_grade", "Grado RTOG/EORTC urinario tardío", "select", options=["0", "1", "2", "3", "4"], default="0", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring", evidence_tags=["RTOG/EORTC Late"]),
        FieldSpec("urinary_frequency", "Frecuencia urinaria", "select", options=["Normal", "Aumentada", "Severa"], default="Normal", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        FieldSpec("urinary_urgency", "Urgencia urinaria", "select", options=["0", "1"], default="0", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        FieldSpec("dysuria_present", "Disuria", "select", options=["0", "1"], default="0", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        FieldSpec("gross_hematuria", "Hematuria macroscópica", "select", options=["0", "1"], default="0", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        FieldSpec("urethral_stricture", "Estenosis uretral", "select", options=["0", "1"], default="0", group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        FieldSpec("urinary_incontinence_pads_per_day", "Pads/día por incontinencia", "number", default=0, group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring"),
        # EPIC 9 Group F (GAP-17) — IPSS degradado a `legacy`: EPIC-26 Urinary
        # (línea siguiente) es el instrumento primario post-RT (Wei 2000; EAU 2026
        # §6.3.3 prefiere EPIC-26 / EPIC-CP frente a IPSS porque captura irritativa
        # + obstructiva + incontinencia en la misma dimensión). Se mantiene como
        # alias retrocompatible para visitas históricas ya persistidas; no se
        # elimina físicamente para no romper `field_semantics.py` ni trayectorias
        # de validación seriadas.
        FieldSpec("ipss_score", "IPSS (0-35) [legacy]", "number", required=False, default=8, group="Toxicidad tardía urinaria", group_order=3, clinical_role="legacy", evidence_tags=["legacy_ipss_epic26_primary"]),
        FieldSpec("epic26_urinary_score", "EPIC-26 urinario (0-100)", "number", default=80, group="Toxicidad tardía urinaria", group_order=3, clinical_role="monitoring", evidence_tags=["epic26_primary"]),

        # Grupo 4 - Toxicidad tardía intestinal
        FieldSpec("late_bowel_grade", "Grado RTOG/EORTC intestinal tardío", "select", options=["0", "1", "2", "3", "4"], default="0", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring", evidence_tags=["RTOG/EORTC Late"]),
        # Grupo 4.5 - Toxicidad tardía acumulada RT (CTCAE v5)
        # RADICALS-RT long-term follow-up: flags GU/GI acumulados ≥3m post-RT,
        # grado ≥2 → derivación especializada; grado ≥3 → gate re-irradiación.
        FieldSpec(
            "late_rt_toxicity_gu",
            "Toxicidad genitourinaria tardía (CTCAE v5)",
            "select",
            options=[
                "Sin toxicidad",
                "Grado 1 – leve",
                "Grado 2 – moderado",
                "Grado 3 – severo",
                "Grado 4 – amenaza vida",
                "Grado 5 – muerte",
            ],
            default="Sin toxicidad",
            group="Toxicidad tardía acumulada",
            group_order=45,
            clinical_role="decision_refiner",
            evidence_tags=["radicals_rt", "rtog_late_toxicity"],
            help_text=(
                "Toxicidad GU acumulada >3 meses post-radioterapia (estenosis "
                "uretral, cistitis hemorrágica, incontinencia). Grado ≥2 → "
                "derivación urología; grado ≥3 contraindica re-irradiación."
            ),
        ),
        FieldSpec(
            "late_rt_toxicity_gi",
            "Toxicidad gastrointestinal tardía (CTCAE v5)",
            "select",
            options=[
                "Sin toxicidad",
                "Grado 1 – leve",
                "Grado 2 – moderado",
                "Grado 3 – severo",
                "Grado 4 – amenaza vida",
                "Grado 5 – muerte",
            ],
            default="Sin toxicidad",
            group="Toxicidad tardía acumulada",
            group_order=45,
            clinical_role="decision_refiner",
            evidence_tags=["radicals_rt", "rtog_late_toxicity"],
            help_text=(
                "Toxicidad GI acumulada >3 meses post-radioterapia (proctitis "
                "crónica, fístula, incontinencia fecal). Grado ≥2 → derivación "
                "GI; grado ≥3 contraindica re-irradiación."
            ),
        ),
        FieldSpec("rectal_bleeding", "Sangrado rectal", "select", options=["Ninguno", "Ocasional", "Frecuente", "Requiere transfusión"], default="Ninguno", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),
        FieldSpec("rectal_urgency", "Urgencia rectal", "select", options=["0", "1"], default="0", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),
        FieldSpec("fecal_incontinence", "Incontinencia fecal", "select", options=["0", "1"], default="0", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),
        FieldSpec("proctitis_treatment_required", "Tratamiento por proctitis radio-inducida", "select", options=["0", "1"], default="0", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),
        FieldSpec("rectal_fistula", "Fístula rectal", "select", options=["0", "1"], default="0", group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),
        FieldSpec("epic26_bowel_score", "EPIC-26 intestinal (0-100)", "number", default=85, group="Toxicidad tardía intestinal", group_order=4, clinical_role="monitoring"),

        # Grupo 5 - Toxicidad sexual y endocrina
        FieldSpec("late_sexual_function", "Función sexual tardía", "select", options=["Preservada", "Deteriorada", "Ausente"], default="Deteriorada", group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),
        # EPIC 9 Group F (GAP-17) — IIEF-5 degradado a `legacy`: EPIC-26 Sexual
        # (línea 96) y la escala hormonal (línea 97) son los instrumentos primarios
        # post-RT. IIEF-5 pierde precisión en pacientes con ADT concomitante porque
        # mezcla deseo, función eréctil y orgasmo sin discriminar la contribución
        # del eje hipotalámico-hipofisario-gonadal. Se mantiene para retrocompat.
        FieldSpec("iief5_score", "IIEF-5 (5-25) [legacy]", "number", required=False, default=15, group="Toxicidad sexual y endocrina", group_order=5, clinical_role="legacy", evidence_tags=["legacy_iief5_epic26_primary"]),
        FieldSpec("pde5_inhibitor_use", "Uso de PDE5", "select", options=["0", "1"], default="0", group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),
        FieldSpec("testosterone_recovery", "Recuperación de testosterona post-ADT", "select", options=["No aplica", "Recuperada", "Parcial", "Castrate persistente"], default="No aplica", group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),
        FieldSpec("testosterone_value", "Testosterona (ng/dL)", "number", default=300, group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring", unit="ng/dL"),
        FieldSpec("hot_flashes_grade", "Sofocos grado CTCAE", "select", options=["0", "1", "2", "3"], default="0", group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),
        FieldSpec("epic26_sexual_score", "EPIC-26 sexual (0-100)", "number", default=40, group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),
        FieldSpec("epic26_hormonal_score", "EPIC-26 hormonal (0-100)", "number", default=80, group="Toxicidad sexual y endocrina", group_order=5, clinical_role="monitoring"),

        # Grupo 6 - Vigilancia segundos primarios y comorbilidades
        FieldSpec("bladder_cancer_screening", "Vigilancia de cáncer de vejiga", "select", options=["No indicada", "Cistoscopía si hematuria", "Cistoscopía periódica"], default="No indicada", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),
        FieldSpec("colorectal_screening_current", "Tamizaje colorrectal al día", "select", options=["0", "1"], default="1", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),
        FieldSpec("smoking_status", "Tabaquismo", "select", options=["Nunca", "Ex", "Activo"], default="Nunca", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),
        FieldSpec("bone_health_dxa", "DXA óseo", "select", options=["No indicado", "Pendiente", "Realizado"], default="No indicado", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),
        FieldSpec("cv_risk_assessment", "Evaluación CV", "select", options=["No indicada", "Pendiente", "Realizada"], default="No indicada", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),
        FieldSpec("metabolic_syndrome_screening", "Tamizaje síndrome metabólico (HbA1c, lípidos)", "select", options=["0", "1"], default="0", group="Segundos primarios y comorbilidades", group_order=6, clinical_role="monitoring"),

        # Grupo 7 - Examen físico y restadificación
        FieldSpec("dre_finding", "Tacto rectal", "select", options=["Normal", "Anormal"], default="Normal", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("mpmri_done", "mpMRI prostático realizado", "select", options=["0", "1"], default="0", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("mpmri_recurrence_suspected", "mpMRI sugiere recurrencia local", "select", options=["0", "1"], default="0", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("psma_pet_done", "PSMA-PET realizado", "select", options=["0", "1"], default="0", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("prostate_biopsy_done", "Biopsia prostática post-RT realizada", "select", options=["0", "1"], default="0", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("biopsy_proven_local_recurrence", "Recurrencia local probada por biopsia", "select", options=["0", "1"], default="0", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),
        FieldSpec("imaging_negative_metastases", "Imagen negativa para metástasis (M0)", "select", options=["0", "1"], default="1", group="Examen físico y restadificación", group_order=7, clinical_role="monitoring"),

        # Grupo 8 - Contexto del paciente
        FieldSpec("age_current", "Edad actual (años)", "number", required=True, default=70, group="Contexto del paciente", group_order=8, clinical_role="required", unit="años"),
        FieldSpec("life_expectancy_years", "Esperanza de vida estimada (años)", "number", default=12, group="Contexto del paciente", group_order=8, clinical_role="decision_refiner", unit="años"),
        FieldSpec("ecog_score", "ECOG", "select", options=["0", "1", "2", "3", "4"], default="0", group="Contexto del paciente", group_order=8, clinical_role="decision_refiner"),
        FieldSpec("frailty_status", "Estado de fragilidad (G8)", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Contexto del paciente", group_order=8, clinical_role="decision_refiner"),
        FieldSpec("charlson_index", "Charlson Comorbidity Index", "number", default=2, group="Contexto del paciente", group_order=8, clinical_role="monitoring"),
        FieldSpec("patient_priority_profile", "Preferencias y prioridades del paciente", "text", default="", group="Contexto del paciente", group_order=8, clinical_role="monitoring"),
    ],
)
