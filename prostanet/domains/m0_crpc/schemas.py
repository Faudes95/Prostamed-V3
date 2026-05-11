from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.advanced_support_fields import (
    advanced_adt_timeline_fields,
    advanced_cognitive_fields,
    advanced_ddi_fields,
    advanced_hepatic_fields,
    advanced_laboratory_baseline_fields,
    advanced_pro_dropdown_fields,
    advanced_renal_function_fields,
    advanced_staging_imaging_fields,
    oncologic_emergency_fields,
    pivotal_contraindication_fields,
    pivotal_gate_supporting_fields,
)


M0_CRPC_SCHEMA = module_schema(
    "m0_crpc",
    "M0 CRPC",
    "Ruta de intensificación adaptada al riesgo en enfermedad resistente a la castración sin metástasis, con discriminación explícita de seguridad entre ARPI.",
    fields=[
        FieldSpec("psadt_months", "Tiempo de duplicación del PSA", "number", required=True, default=7, group="Riesgo oncológico", group_order=1, clinical_role="required", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("castration_resistant", "Resistente a la castración", "select", required=True, options=["Pendiente", "0", "1"], default="Pendiente", group="Riesgo oncológico", group_order=1, clinical_role="required"),
        FieldSpec("imaging_negative", "Imagen negativa", "select", options=["Pendiente", "0", "1"], default="Pendiente", group="Riesgo oncológico", group_order=1, clinical_role="required"),
        FieldSpec("castrate_testosterone_confirmed", "Testosterona en rango de castración confirmada", "select", options=["Pendiente", "0", "1"], default="Pendiente", group="Riesgo oncológico", group_order=1, clinical_role="required", evidence_tags=["castration_confirmation"]),
        FieldSpec("progression_pattern", "Patrón de progresión", "select", required=True, options=["Pendiente", "biochemical_only", "radiographic", "clinical", "mixed", "discordant"], default="Pendiente", group="Riesgo oncológico", group_order=1, clinical_role="required", evidence_tags=["progression_pattern"]),
        FieldSpec("conventional_imaging_status", "Estado de imagen convencional", "select", required=True, options=["Pendiente", "NOT_RESTAGED", "M0", "M1", "M1a", "M1b", "M1c"], default="Pendiente", group="Riesgo oncológico", group_order=1, clinical_role="required", evidence_tags=["restaging"]),
        FieldSpec("conventional_imaging_modality", "Modalidad de imagen convencional", "select", options=["Desconocida", "TC + gammagrama óseo", "TC sola", "RM", "PET/CT", "Otra"], default="Desconocida", group="Riesgo oncológico", group_order=1, clinical_role="decision_refiner", evidence_tags=["restaging"]),
        FieldSpec("conventional_imaging_date", "Fecha de imagen convencional", "date", group="Riesgo oncológico", group_order=1, clinical_role="decision_refiner", evidence_tags=["restaging"]),
        *advanced_adt_timeline_fields(group="Terapia de privación androgénica", group_order=1),
        # EPIC 9 Group F (GAP-14) — Campos decisivos mínimos CRPC declarados explícitamente
        # en el schema para alinear captura con `clinical_decision_governance.CRPC_MINIMUM_DECISIVE_FIELDS`
        # (líneas 159-167) y con `decision_input_requirements_engine.REQUIREMENTS["m0_crpc"]`
        # (línea 268). Defaults retrocompatibles: backward-compat con visitas preexistentes.
        # Options canónicas `current_adt_context` desde `shared/presentation_text.py:84`.
        FieldSpec("current_adt_context", "Contexto actual de ADT", "select", options=["none", "medical_adt_continuous", "orchiectomy", "intermittent_adt"], default="medical_adt_continuous", group="Secuencia terapéutica", group_order=1, clinical_role="required", evidence_tags=["castration_context", "governance_crpc_minimum"]),
        FieldSpec("line_of_therapy_number", "Número de línea terapéutica actual", "number", default=1, group="Secuencia terapéutica", group_order=1, clinical_role="decision_refiner", unit="línea", evidence_tags=["sequence", "governance_crpc_minimum"], conditional_visibility={'current_treatment_active': ['yes', '1']}),
        FieldSpec("drug_scheme", "Esquema farmacológico actual", "select", options=["Desconocido", "ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE", "DOCETAXEL", "CABAZITAXEL", "OLAPARIB", "TALAZOPARIB_ENZALUTAMIDE", "NIRAPARIB_ABIRATERONE", "LU177_PSMA617"], default="Desconocido", group="Secuencia terapéutica", group_order=1, clinical_role="decision_refiner", evidence_tags=["sequence", "therapy_catalog", "governance_crpc_minimum"], conditional_visibility={'current_treatment_active': ['yes', '1']}),
        FieldSpec("ecog_score", "ECOG", "number", default=1, group="Seguridad y tolerabilidad", group_order=2, clinical_role="required", unit="0-4", evidence_tags=["performance_status"]),
        FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
        FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
        FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["frailty"]),
        *advanced_hepatic_fields(group="Seguridad y tolerabilidad", group_order=2, child_pugh_role="required"),
        *advanced_renal_function_fields(group="Función renal basal", group_order=2),
        *advanced_laboratory_baseline_fields(group="Marcadores pronósticos Halabi", group_order=2),
        FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
        *advanced_ddi_fields(group="Seguridad y tolerabilidad", group_order=2),
        FieldSpec("dermatitis_history", "Antecedente dermatológico relevante", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
        FieldSpec("cognitive_risk", "Riesgo cognitivo clínicamente relevante", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurotoxicity"]),
        FieldSpec("fall_risk", "Riesgo de caídas", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["falls"]),
        FieldSpec("stroke_history", "Antecedente de EVC/AIT", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurovascular"]),
        FieldSpec("edema_risk", "Riesgo de edema / insuficiencia cardiaca", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
        FieldSpec("steroid_intolerance", "Intolerancia a esteroides", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["steroids"]),
        FieldSpec("diabetes_uncontrolled", "Diabetes no controlada", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["metabolic_risk"]),
        FieldSpec("baseline_bp", "Presión arterial basal sistólica", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="mmHg", evidence_tags=["arsi_safety"]),
        FieldSpec("baseline_weight", "Peso basal", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="kg", evidence_tags=["qol"]),
        *advanced_cognitive_fields(group="Monitoreo basal ARPI", group_order=3),
        FieldSpec("fall_history_recent", "Caídas recientes", "select", options=["0", "1"], default="0", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", evidence_tags=["falls"]),
        FieldSpec("liver_panel_date", "Fecha de pruebas hepáticas basales", "date", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", evidence_tags=["hepatotoxicity"]),
        FieldSpec("bilirubin", "Bilirrubina total", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="mg/dL", evidence_tags=["hepatotoxicity"]),
        FieldSpec("ast", "AST (TGO)", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="U/L", evidence_tags=["hepatotoxicity"]),
        FieldSpec("alt", "ALT (TGP)", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="U/L", evidence_tags=["hepatotoxicity"]),
        FieldSpec("alp", "Fosfatasa alcalina", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="U/L", evidence_tags=["hepatotoxicity"]),
        FieldSpec("potassium", "Potasio basal", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", unit="mEq/L", evidence_tags=["metabolic_risk"]),
        FieldSpec("glucose_or_hba1c", "Glucosa o HbA1c basal", "number", default="", group="Monitoreo basal ARPI", group_order=3, clinical_role="monitoring", evidence_tags=["metabolic_risk"]),
        *advanced_pro_dropdown_fields(group="Resultados reportados por el paciente", group_order=4),
        # ── Imagenología de estadificación / restaging M (PSMA / GGO / TAC / RM) ──
        # NCCN PROS-2 v5.2026 cat 1; EAU 2026 §6.4.1-6.4.3.
        # En m0_crpc el restaging es decisivo: confirma "M0" antes de elegir
        # darolutamida/apalutamida/enzalutamida (SPARTAN/PROSPER/ARAMIS) y descarta
        # M1 oculto que rerutearía a m1_crpc/mCSPC. ProPSMA (Hofman 2020) refuerza
        # PSMA PET/CT como preferente en CRPC con PSADT corto. NO duplicar
        # `imaging_negative` (binario legacy m0_crpc) ni `conventional_imaging_status`
        # (M-stage convencional ya declarado).
        *advanced_staging_imaging_fields(
            psma_pet_done_role="decision_refiner",
            bone_scan_done_role="decision_refiner",
            cross_sectional_role="decision_refiner",
            include_local_invasion=False,
        ),
        # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # m0 CRPC raramente debuta con emergencia activa, pero PSADT corto
        # + síntomas óseos puede presagiar transición a m1 con compresión.
        *oncologic_emergency_fields(role="decision_refiner", group_order=70),
        # ── Contraindicaciones de ensayos pivote (FAUBOT 2026-04-23) ──
        # SPARTAN/PROSPER/ARAMIS: hipersensibilidad a ARPI + control HTA/IC.
        *pivotal_contraindication_fields(role="decision_refiner", group_order=80),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI de fields para gates de RP-vs-RT subspecialty, genomic
        # critical (HRR/AR-V7/CDK12/HRD/MSI), pre-dx atypical (NEPC/emergency).
        *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
    ],
)
