from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.advanced_support_fields import (
    advanced_adt_timeline_fields,
    advanced_bone_turnover_fields,
    advanced_cardio_fields,
    advanced_chemotherapy_fitness_fields,
    advanced_cognitive_fields,
    advanced_ddi_fields,
    advanced_hepatic_fields,
    advanced_io_safety_fields,
    advanced_laboratory_baseline_fields,
    advanced_neutropenia_fields,
    advanced_pro_dropdown_fields,
    advanced_renal_function_fields,
    advanced_variant_histology_fields,
    advanced_visceral_site_fields,
    oncologic_emergency_fields,
    pivotal_contraindication_fields,
    pivotal_gate_supporting_fields,
)


def _docetaxel_visibility() -> dict:
    return {
        "ecog_score": ["", "0", "1", "2"],
        "peripheral_neuropathy_grade": ["", "0", "1", "2"],
        "frailty_status": ["", "Fit", "Vulnerable"],
        "child_pugh_score": ["", "A", "B"],
    }


def _build_schema(module_id: str, title: str, description: str) -> dict:
    return module_schema(
        module_id,
        title,
        description,
        fields=[
            FieldSpec(
                "metastatic_components_capture",
                "Distribución metastásica documentada",
                "metastatic_components",
                required=True,
                group="Carga metastásica",
                group_order=1,
                clinical_role="required",
                help_text="Documente componentes óseos, viscerales y ganglionares no regionales. El asistente derivará automáticamente la composición metastásica, el subtipo M y la carga total.",
                benchmark_note="Permite enfermedad mixta visceral + ósea + nodal sin colapsarla a un solo sitio metastásico legado.",
            ),
            FieldSpec(
                "gleason_score",
                "Perfil Gleason / ISUP",
                "gleason_profile",
                default={"gleason_primary": "4", "gleason_secondary": "4", "gleason_tertiary": "", "gleason_score": "8", "isup_grade": "4"},
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                help_text="Documente patrón primario, secundario y el terciario si existe. El sistema derivará automáticamente el Gleason total y el ISUP para alimentar diagnóstico y decisión terapéutica.",
            ),
            *advanced_visceral_site_fields(group="Sitios viscerales estructurados", group_order=1),
            FieldSpec(
                "bone_lesions_outside_axial",
                "Lesiones óseas fuera del esqueleto axial",
                "select",
                options=["", "0", "1"],
                default="",
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                evidence_tags=["chaarted", "high_volume"],
                help_text="Apendicular (huesos largos / costillas / cráneo) — criterio CHAARTED de alto volumen junto a ≥4 mets óseos.",
            ),
            FieldSpec(
                "extra_pelvic_nodal_metastasis",
                "Adenopatías metastásicas extra-pélvicas",
                "select",
                options=["", "0", "1"],
                default="",
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                evidence_tags=["contact02", "extra_pelvic"],
                help_text="Adenopatías retroperitoneales/mediastínicas/supradiafragmáticas — criterio CONTACT-02 e impacto pronóstico.",
            ),
            FieldSpec(
                "bone_lesion_count",
                "Número total de lesiones óseas",
                "number",
                default="",
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                unit="lesiones",
                evidence_tags=["chaarted", "latitude"],
                help_text="≥4 + apendicular = CHAARTED alto volumen; ≥3 = factor LATITUDE.",
            ),
            FieldSpec(
                "metachronous_metastasis",
                "Metástasis metacrónicas (>12m post-tratamiento local)",
                "select",
                options=["Desconocido", "No", "Sí"],
                default="Desconocido",
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                evidence_tags=["latitude", "metachronous"],
                help_text=(
                    "Metástasis metacrónica (aparecida >6-12 meses tras diagnóstico de "
                    "enfermedad localizada). Criterio para LATITUDE bajo-riesgo vs "
                    "ARCHES/ENZAMET. Acepta legacy boolean '0'/'1' por compatibilidad."
                ),
            ),
            FieldSpec(
                "pten_loss",
                "Pérdida de PTEN (IHC o NGS)",
                "select",
                options=["", "0", "1", "Desconocido"],
                default="",
                group="Biomarcadores",
                group_order=3,
                clinical_role="decision_refiner",
                evidence_tags=["capitello281", "ipatential150"],
                help_text="Pérdida bialélica de PTEN — gatilla CAPItello-281 (capivasertib + abiraterona) en mHSPC.",
            ),
            *advanced_adt_timeline_fields(group="Terapia de privación androgénica", group_order=1),
            FieldSpec("ecog_score", "ECOG", "number", default=1, group="Fitness y seguridad", group_order=2, clinical_role="required", unit="0-4"),
            FieldSpec(
                "performance_status_driver",
                "Origen del deterioro funcional",
                "select",
                options=["mixed_or_unclear", "cancer_related", "comorbidity_or_frailty"],
                default="mixed_or_unclear",
                group="Fitness y seguridad",
                group_order=2,
                clinical_role="decision_refiner",
                help_text="Úselo sobre todo cuando ECOG es 2 para distinguir si el deterioro parece impulsado por cáncer/dolor óseo o por comorbilidad/fragilidad.",
                conditional_visibility={"ecog_score": ["2"]},
            ),
            FieldSpec("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["", "0", "1", "2", "3", "4"], default="", group="Fitness y seguridad", group_order=2, clinical_role="required", unit="CTCAE"),
            FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["frailty"]),
            *advanced_hepatic_fields(group="Fitness y seguridad", group_order=2, child_pugh_role="required"),
            *advanced_renal_function_fields(group="Función renal basal", group_order=2),
            *advanced_laboratory_baseline_fields(group="Marcadores pronósticos Halabi", group_order=2),
            FieldSpec(
                "cbc_date",
                "Fecha de biometría hemática",
                "date",
                group="Elegibilidad a docetaxel",
                group_order=3,
                clinical_role="required",
                help_text="Use una biometría hemática vigente de 14 días o menos cuando docetaxel siga siendo opción real.",
                conditional_visibility=_docetaxel_visibility(),
            ),
            FieldSpec("anc", "ANC basal", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", evidence_tags=["cbc"], conditional_visibility=_docetaxel_visibility()),
            FieldSpec("platelets", "Plaquetas basales", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", evidence_tags=["cbc"], conditional_visibility=_docetaxel_visibility()),
            FieldSpec(
                "liver_panel_date",
                "Fecha de pruebas hepáticas",
                "date",
                group="Elegibilidad a docetaxel",
                group_order=3,
                clinical_role="required",
                help_text="Use pruebas hepáticas vigentes de 14 días o menos cuando compitan docetaxel, ARPI o abiraterona.",
            ),
            FieldSpec("bilirubin", "Bilirrubina total", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="mg/dL", evidence_tags=["hepatotoxicity"]),
            FieldSpec("ast", "AST (TGO)", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("alt", "ALT (TGP)", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("alp", "Fosfatasa alcalina", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("taxane_hypersensitivity_history", "Hipersensibilidad previa a taxanos", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            FieldSpec("polysorbate_hypersensitivity", "Hipersensibilidad a polisorbato 80", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            FieldSpec("bone_pain", "Dolor óseo relacionado con la enfermedad", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="decision_refiner", help_text="Especialmente útil si ECOG es 2 para adjudicar un deterioro cáncer-relacionado tipo PEACE-1 / CHAARTED parcial.", conditional_visibility={"ecog_score": ["2"]}),
            FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner"),
            FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
            FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
            *advanced_ddi_fields(group="Fitness y seguridad", group_order=2),
            FieldSpec("dermatitis_history", "Antecedente dermatológico relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
            FieldSpec("cognitive_risk", "Riesgo cognitivo clínicamente relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurotoxicity"]),
            FieldSpec("fall_risk", "Riesgo de caídas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["falls"]),
            FieldSpec("stroke_history", "Antecedente de EVC/AIT", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurovascular"]),
            FieldSpec("edema_risk", "Riesgo de edema / IC", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
            FieldSpec("steroid_intolerance", "Intolerancia a esteroides", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["steroids"]),
            FieldSpec("diabetes_uncontrolled", "Diabetes no controlada", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["metabolic_risk"]),
            FieldSpec("baseline_bp", "Presión arterial basal sistólica", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="mmHg", evidence_tags=["cardio_oncology"]),
            FieldSpec("baseline_weight", "Peso basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="kg", evidence_tags=["qol"]),
            *advanced_cognitive_fields(group="Monitoreo basal ARPI", group_order=4),
            FieldSpec("fall_history_recent", "Caídas recientes", "select", options=["0", "1"], default="0", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", evidence_tags=["falls"]),
            FieldSpec("potassium", "Potasio basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="mEq/L", evidence_tags=["metabolic_risk"]),
            FieldSpec("glucose_or_hba1c", "Glucosa o HbA1c basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", evidence_tags=["metabolic_risk"]),
            FieldSpec("biomarker_source", "Fuente del biomarcador", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=3, clinical_role="optional", evidence_tags=["biomarkers"], conditional_visibility={'somatic_testing_performed': ['1']}),
            FieldSpec("molecular_assay_source", "Fuente del ensayo molecular", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
            FieldSpec("molecular_assay_date", "Fecha del ensayo molecular", "date", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
            FieldSpec("hrr_gene", "Gen HRR predominante", "select", options=["Desconocido", "BRCA2", "BRCA1", "ATM", "PALB2", "CDK12", "Otro"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="optional", evidence_tags=["hrr"], conditional_visibility={'hrr_status': ['Positivo']}),
            FieldSpec("brca2_status", "Estado BRCA2", "select", options=["Desconocido", "Positivo", "Negativo"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["hrr"]),
            FieldSpec("dxa_baseline_done", "DXA basal realizada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            FieldSpec("calcium_vitd_started", "Calcio y vitamina D iniciados", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            FieldSpec("bone_protection_started", "Protección ósea iniciada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            *advanced_variant_histology_fields(group="Salud ósea", group_order=4, include_neuroendocrine_toggle=True),
            *advanced_pro_dropdown_fields(group="Resultados reportados por el paciente", group_order=4),
            *advanced_chemotherapy_fitness_fields(group="Aptitud a quimioterapia", group_order=52),
            *advanced_neutropenia_fields(group="Seguridad hematológica", group_order=55),
            *advanced_io_safety_fields(group="Seguridad inmunoterapia", group_order=60),
            # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──
            # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
            # En mCSPC alto volumen, hidronefrosis/compresión/hipercalcemia
            # tienen prevalencia >10%; mantenerlo como decision_refiner
            # permite escalada urgente sin bloquear captura.
            *oncologic_emergency_fields(role="decision_refiner", group_order=70),
            # ── Contraindicaciones de ensayos pivote (FAUBOT 2026-04-23) ──
            # ARANOTE / LATITUDE / PEACE-1 / IPATential150 / ERA-223 / PEACE-3.
            # Habilita los 10 gates de pivotal_contraindication_gates.py.
            *pivotal_contraindication_fields(role="decision_refiner", group_order=80),
            # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
            # Captura UI de fields para gates RP-vs-RT subspecialty, genomic
            # critical (HRR/AR-V7/CDK12/HRD/MSI), pre-dx atypical (NEPC/emergency).
            *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
            # ── EPIC 10B fix — Cableado cardio-cognitivo y mineral óseo ──
            # Replica del fix EPIC 10B aplicado a m1_crpc/schemas.py. Estos
            # helpers están definidos pero no se invocaban en mhspc, dejando
            # huérfanos los triggers de NYHA III-IV (abiraterona/enzalutamida),
            # LVEF<40% (apalutamida), QTc ms basal+dynamic (enzalutamida),
            # MMSE/MOCA cognición (ARSIs), e ionized_calcium (Ra-223). Crítico
            # en mHSPC porque aquí es donde se inicia ARPI/quimio frontline.
            *advanced_cardio_fields(group="Cardio-cognitivo basal y dinámica", group_order=82),
            *advanced_bone_turnover_fields(group="Soporte óseo y mineral", group_order=83),
        ],
    )


MCSPC_HIGH_VOLUME_SCHEMA = _build_schema(
    "mcspc_high_volume",
    "mCSPC alto volumen",
    "Ruta de tripletes y dobletes para enfermedad metastásica sensible a la castración de alto volumen.",
)

MCSPC_HIGH_VOLUME_SYNC_SCHEMA = _build_schema(
    "mcspc_high_volume_sync",
    "mCSPC alto volumen sincrónico",
    "Ruta de tripletes y dobletes para enfermedad metastásica sensible a la castración de alto volumen sincrónica / de novo.",
)

MCSPC_HIGH_VOLUME_METACHRONOUS_SCHEMA = _build_schema(
    "mcspc_high_volume_metachronous",
    "mCSPC alto volumen metacrónico",
    "Ruta de intensificación sistémica para enfermedad metastásica sensible a la castración de alto volumen metacrónica.",
)
