from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


STATE_CONTEXT_OPTIONS = [
    "localized_initial",
    "post_prostatectomy",
    "recurrence_bcr",
    "post_radiotherapy_or_local_salvage",
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "m0_crpc",
    "m1_crpc",
]


SURVIVORSHIP_AND_TOXICITY_FOLLOWUP_SCHEMA = module_schema(
    "survivorship_and_toxicity_followup",
    "Survivorship y toxicidad por tratamiento",
    "Integra secuelas tardías, toxicidad acumulada, recuperación funcional y prevención secundaria sin reemplazar el estado oncológico principal.",
    fields=[
        FieldSpec("oncologic_state_context", "Estado oncológico actual", "select", required=True, options=STATE_CONTEXT_OPTIONS, default="post_prostatectomy", group="Contexto clínico", group_order=1, clinical_role="required"),
        FieldSpec("effective_management_track", "Track de manejo actual", "text", group="Contexto clínico", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("age", "Edad", "number", group="Contexto clínico", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("visit_date", "Fecha de revisión survivorship", "date", group="Contexto clínico", group_order=1, clinical_role="monitoring"),
        FieldSpec("prior_prostatectomy", "Prostatectomía previa", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("prior_radiation", "Radioterapia previa", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("prior_adt", "Exposición a ADT", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("adt_duration_months", "Duración acumulada de ADT", "number", default=24, unit="meses", group="Exposición terapéutica", group_order=2, clinical_role="decision_refiner", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("prior_docetaxel", "Docetaxel previo", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("prior_cabazitaxel", "Cabazitaxel previo", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("on_denosumab", "Denosumab activo o previo reciente", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),
        FieldSpec("on_zoledronate", "Ácido zoledrónico activo o previo reciente", "select", required=True, options=["0", "1"], default="0", group="Exposición terapéutica", group_order=2, clinical_role="required"),

        FieldSpec("ipss_score", "IPSS", "number", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("pad_count", "Pads por día", "number", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("continence_status", "Estado de continencia", "select", options=["Continente", "Leve", "Moderada", "Severa"], default="Continente", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("leakage_bother", "Molestia por fuga urinaria", "number", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("iief5_score", "IIEF-5", "number", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("nerve_sparing", "Preservación neurovascular", "select", options=["No", "Unilateral", "Bilateral", "Desconocido"], default="Desconocido", group="Secuelas post-prostatectomía", group_order=3, clinical_role="decision_refiner", conditional_visibility={"prior_prostatectomy": ["1"]}),
        FieldSpec("pelvic_floor_pt_started", "Fisioterapia de piso pélvico iniciada", "select", options=["0", "1"], default="0", group="Secuelas post-prostatectomía", group_order=3, clinical_role="required", conditional_visibility={"prior_prostatectomy": ["1"]}),

        FieldSpec("gu_toxicity_grade", "Grado de toxicidad GU", "select", options=["0", "1", "2", "3", "4"], default="0", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("gi_toxicity_grade", "Grado de toxicidad GI", "select", options=["0", "1", "2", "3", "4"], default="0", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("rectal_toxicity_grade", "Grado de toxicidad rectal", "select", options=["0", "1", "2", "3", "4"], default="0", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("hematuria", "Hematuria", "select", options=["No", "Leve", "Moderada", "Severa"], default="No", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("dysuria", "Disuria", "select", options=["No", "Leve", "Moderada", "Severa"], default="No", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("radiation_cystitis", "Cistitis actínica documentada", "select", options=["0", "1"], default="0", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("proctitis", "Proctitis documentada", "select", options=["0", "1"], default="0", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),
        FieldSpec("late_toxicity_json", "Resumen estructurado de toxicidad tardía", "textarea", group="Toxicidad tardía post-radioterapia", group_order=4, clinical_role="required", conditional_visibility={"prior_radiation": ["1"]}),

        FieldSpec("systolic_bp", "PA sistólica", "number", unit="mmHg", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("diastolic_bp", "PA diastólica", "number", unit="mmHg", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("hba1c", "HbA1c", "number", unit="%", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("total_cholesterol", "Colesterol total", "number", unit="mg/dL", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("hdl_cholesterol", "HDL", "number", unit="mg/dL", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("triglycerides", "Triglicéridos", "number", unit="mg/dL", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("waist_circumference_cm", "Perímetro abdominal", "number", unit="cm", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("dxa_t_score_lumbar", "DXA T-score lumbar", "number", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("dxa_t_score_hip", "DXA T-score cadera", "number", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("vitamin_d_level", "Vitamina D", "number", unit="ng/mL", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("calcium_level", "Calcio", "number", unit="mg/dL", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("fall_risk", "Riesgo de caída", "select", options=["0", "1"], default="0", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),
        FieldSpec("cognitive_risk", "Riesgo cognitivo", "select", options=["0", "1"], default="0", group="Cardiometabólico y hueso bajo ADT", group_order=5, clinical_role="required", conditional_visibility={"prior_adt": ["1"]}),

        FieldSpec("neuropathy_grade", "Grado de neuropatía", "select", options=["0", "1", "2", "3", "4"], default="0", group="Recuperación post-sistémicos", group_order=6, clinical_role="required", conditional_visibility={"__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}]}),
        FieldSpec("fatigue_score", "Fatiga", "number", group="Recuperación post-sistémicos", group_order=6, clinical_role="required", conditional_visibility={"__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}, {"prior_adt": ["1"]}]}),
        FieldSpec("hemoglobin", "Hemoglobina", "number", unit="g/dL", group="Recuperación post-sistémicos", group_order=6, clinical_role="required", conditional_visibility={"__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}]}),
        FieldSpec("weight_loss_pct", "Pérdida ponderal", "number", unit="%", group="Recuperación post-sistémicos", group_order=6, clinical_role="required", conditional_visibility={"__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}]}),
        FieldSpec("functional_decline", "Declive funcional", "select", options=["0", "1"], default="0", group="Recuperación post-sistémicos", group_order=6, clinical_role="required", conditional_visibility={"__any__": [{"prior_docetaxel": ["1"]}, {"prior_cabazitaxel": ["1"]}]}),

        FieldSpec("dental_clearance_done", "Clearance dental realizado", "select", options=["0", "1"], default="0", group="Salud ósea y BMA", group_order=7, clinical_role="required", conditional_visibility={"__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]}),
        FieldSpec("onj_monitoring", "Monitoreo de osteonecrosis mandibular", "select", options=["0", "1"], default="0", group="Salud ósea y BMA", group_order=7, clinical_role="required", conditional_visibility={"__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]}),
        FieldSpec("creatinine", "Creatinina", "number", unit="mg/dL", group="Salud ósea y BMA", group_order=7, clinical_role="required", conditional_visibility={"__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]}),
        FieldSpec("bone_pain", "Dolor óseo", "select", options=["0", "1"], default="0", group="Salud ósea y BMA", group_order=7, clinical_role="required", conditional_visibility={"__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]}),
        FieldSpec("skeletal_events", "Eventos esqueléticos estructurados", "textarea", group="Salud ósea y BMA", group_order=7, clinical_role="required", conditional_visibility={"__any__": [{"on_denosumab": ["1"]}, {"on_zoledronate": ["1"]}]}),

        FieldSpec("depression_score", "Depresión", "number", group="Psicosocial y sexual", group_order=8, clinical_role="required"),
        FieldSpec("anxiety_score", "Ansiedad", "number", group="Psicosocial y sexual", group_order=8, clinical_role="required"),
        FieldSpec("sexual_bother", "Carga sexual percibida", "number", group="Psicosocial y sexual", group_order=8, clinical_role="required"),
        FieldSpec("body_image_distress", "Distress por imagen corporal", "number", group="Psicosocial y sexual", group_order=8, clinical_role="required"),
        FieldSpec("return_to_work_status", "Retorno a trabajo / rol", "select", options=["Sin impacto", "Ajustado", "No retornó", "Jubilado", "No documentado"], default="No documentado", group="Psicosocial y sexual", group_order=8, clinical_role="required"),
    ],
)
