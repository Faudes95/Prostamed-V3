from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.advanced_support_fields import (
    advanced_adt_timeline_fields,
    advanced_io_safety_fields,
    advanced_laboratory_baseline_fields,
    advanced_renal_function_fields,
    oncologic_emergency_fields,
    pivotal_contraindication_fields,
    pivotal_gate_supporting_fields,
)


RECURRENCE_BCR_SCHEMA = module_schema(
    "recurrence_bcr",
    "Recurrencia bioquímica y BCR2",
    "Distingue rescate postoperatorio, recurrencia tras radioterapia y elegibilidad exacta para BCR2 N0M0.",
    fields=[
        FieldSpec("prior_prostatectomy", "Prostatectomía previa", "select", required=True, options=["0", "1"], default="1", group="Contexto local previo", group_order=1, clinical_role="required"),
        FieldSpec("prior_radiation", "Radioterapia previa", "select", required=True, options=["0", "1"], default="0", group="Contexto local previo", group_order=1, clinical_role="required"),
        FieldSpec("local_therapy_date", "Fecha del tratamiento local principal", "date", group="Contexto local previo", group_order=1, clinical_role="decision_refiner"),
        *advanced_adt_timeline_fields(group="Terapia de privación androgénica", group_order=1),
        FieldSpec("bcr2", "Segunda recurrencia bioquímica", "select", options=["0", "1"], default="0", group="Criterios BCR2", group_order=2, clinical_role="required", evidence_tags=["bcr2"]),
        FieldSpec("psa_current", "PSA actual", "number", required=True, default=0.35, group="Criterios BCR2", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_nadir", "Nadir de PSA", "number", default=0.02, group="Criterios BCR2", group_order=2, clinical_role="decision_refiner", unit="ng/mL"),
        FieldSpec("psadt_months", "Tiempo de duplicación del PSA", "number", default=8, group="Criterios BCR2", group_order=2, clinical_role="required", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("time_to_recurrence_months", "Tiempo a recurrencia", "number", default=18, group="Criterios BCR2", group_order=2, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("ultrasensitive_psa_assay", "PSA ultrasensible documentado", "select", options=["0", "1"], default="1", group="Criterios BCR2", group_order=2, clinical_role="monitoring"),
        FieldSpec("eligible_pelvic_therapy", "Elegible para terapia pélvica", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("salvage_local_feasible", "Rescate local potencialmente curativo factible", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required", evidence_tags=["salvage"]),
        FieldSpec("local_salvage_candidate", "Candidato clínico a rescate local", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["salvage"]),
        FieldSpec("prior_secondary_rt", "Radioterapia secundaria previa", "select", options=["0", "1"], default="0", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("imaging_negative", "Imagen negativa (N0M0)", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("conventional_imaging_m0", "Imagen convencional sin metástasis (M0)", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required", evidence_tags=["imaging"]),
        FieldSpec(
            "m_stage",
            "Estadio M (TNM clínico)",
            "select",
            options=["", "M0", "M1a", "M1b", "M1c"],
            default="M0",
            group="Salvage y reestadificación",
            group_order=3,
            clinical_role="required",
            evidence_tags=["embark", "presto", "tnm"],
            help_text="EMBARK y PRESTO/AFT-19 requieren M0 confirmado por imagen.",
        ),
        FieldSpec(
            "salvage_rt_window_months",
            "Meses desde RP hasta salvage RT planeado",
            "number",
            default="",
            group="Salvage y reestadificación",
            group_order=3,
            clinical_role="decision_refiner",
            unit="meses",
            evidence_tags=["radicals_rt"],
            help_text="RADICALS-RT comparó RT adyuvante vs salvage temprano (PSA <0.1 o ventana <6m post-RP).",
        ),
        FieldSpec("imaging_modality", "Modalidad de imagen predominante", "select", options=["Convencional", "PSMA-PET", "Mixta"], default="Convencional", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"]),
        FieldSpec("psma_pet_done", "PSMA-PET realizado", "select", options=["0", "1"], default="0", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"]),
        FieldSpec("psma_pet_result", "Resultado dominante de PSMA-PET", "select", options=["No realizado", "Negativo", "Local/pélvico", "Oligometastásico", "Diseminado"], default="No realizado", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"], conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_radioligand", "Radioligando PSMA", "select", options=["68Ga-PSMA-11", "18F-DCFPyL", "18F-PSMA-1007", "Otro", "Desconocido"], default="Desconocido", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"], conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_index_lesion_site", "Lesión índice PSMA", "text", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_index_lesion_suvmax", "SUVmax lesión índice", "number", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", unit="SUV", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_uptake_pattern", "Patrón de captación", "select", options=["focal", "multifocal", "diseminado", "indeterminado"], default="indeterminado", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_rads_score", "PSMA-RADS", "select", options=["1", "2", "3", "4", "5", "Desconocido"], default="Desconocido", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_total_lesions", "Número total de lesiones PSMA", "number", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_lesion_locations", "Localización de lesiones PSMA", "text", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("conventional_stage_before_psma", "Stage convencional previo", "select", options=["No comparable", "M0", "M1a", "M1b", "M1c"], default="No comparable", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_stage_after_psma", "Stage posterior por PSMA", "select", options=["M0", "M1a", "M1b", "M1c"], default="M0", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_management_changed", "Cambio de conducta por PSMA", "select", options=["", "1", "0"], default="", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("phoenix_delta", "Incremento Phoenix tras radioterapia", "number", default=0, group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", unit="ng/mL"),
        FieldSpec("ecog_score", "ECOG", "select", options=["0", "1", "2", "3"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("frailty_status", "Estado de fragilidad", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("child_pugh_score", "Clase Child-Pugh", "select", options=["A", "B", "C"], default="A", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("hepatic_risk_factors", "Riesgo hepático basal", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("comorbidity_seizure", "Antecedentes de convulsiones", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("comorbidity_cardio", "Riesgo cardiovascular clínicamente relevante", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("drug_interaction_reviewed", "Interacciones farmacológicas revisadas", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("current_medications", "Medicamentos concomitantes", "text", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("dermatitis_history", "Antecedente de rash o dermatitis significativa", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("cognitive_risk", "Riesgo cognitivo basal", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("fall_risk", "Riesgo de caídas", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("stroke_history", "Antecedente de EVC/AIT", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("edema_risk", "Riesgo de edema o insuficiencia cardiaca", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("steroid_intolerance", "Intolerancia a esteroides", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("diabetes_uncontrolled", "Diabetes o metabolismo glucémico descontrolado", "select", options=["0", "1"], default="0", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="decision_refiner", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("baseline_qol", "Calidad de vida basal", "select", options=["Alta", "Intermedia", "Comprometida"], default="Intermedia", group="Selección ARPI y monitoreo basal", group_order=4, clinical_role="monitoring", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("baseline_bp", "Presión arterial basal", "number", default=120, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="mmHg", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("baseline_weight", "Peso basal", "number", default=75, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="kg", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("fatigue_baseline", "Fatiga basal", "select", options=["0", "1", "2", "3"], default="0", group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("neurocognitive_baseline", "Estado neurocognitivo basal", "select", options=["Intacto", "Leve alteración", "Alteración relevante"], default="Intacto", group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("fall_history_recent", "Caídas recientes", "select", options=["0", "1"], default="0", group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("lft_date", "Fecha de PFH basales", "date", group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("bilirubin", "Bilirrubina total", "number", default=0.8, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="mg/dL", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("ast", "AST", "number", default=28, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="U/L", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("alt", "ALT", "number", default=30, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="U/L", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("alp", "Fosfatasa alcalina", "number", default=110, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="U/L", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("potassium", "Potasio sérico", "number", default=4.1, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="mmol/L", conditional_visibility={"bcr2": ["1"]}),
        FieldSpec("glucose_or_hba1c", "Glucosa o HbA1c basal", "number", default=95, group="Monitoreo ARPI basal", group_order=5, clinical_role="monitoring", unit="mg/dL o %", conditional_visibility={"bcr2": ["1"]}),
        *advanced_renal_function_fields(group="Función renal basal", group_order=5),
        *advanced_laboratory_baseline_fields(group="Marcadores pronósticos Halabi", group_order=5),
        FieldSpec(
            "bone_lesions_outside_axial",
            "Lesiones óseas fuera del esqueleto axial",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group="Carga metastásica",
            group_order=6,
            clinical_role="decision_refiner",
            evidence_tags=["chaarted", "radicals_rt"],
            help_text=(
                "Lesiones apendiculares (costillas, diáfisis, pelvis) fuera del "
                "esqueleto axial. Criterio CHAARTED si progresa a mHSPC."
            ),
        ),
        *advanced_io_safety_fields(group="Seguridad inmunoterapia", group_order=60),
        # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # En BCR/BCR2 los pacientes pueden debutar con metástasis sintomáticas
        # incidentales (compresión por nueva vertebral, hidronefrosis tardía).
        *oncologic_emergency_fields(role="decision_refiner", group_order=70),
        # ── Contraindicaciones pivotal (Faubot 2026-04-23) ────────────
        # En BCR2 / EMBARK / PRESTO los pacientes pueden cursar con HTA
        # descontrolada, ICC, neuropatía residual de docetaxel previo, etc.
        # Captura los 7 FieldSpecs canónicos para que el filtro central
        # (`apply_pivotal_contraindication_gates`) recorte regímenes que
        # incluyen abiraterona, docetaxel/cabazitaxel o tripletes ARSI.
        *pivotal_contraindication_fields(group_order=80),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI: BCR aggressive (gates 53-55 ya integrados en helper) +
        # salvage RT consideration (gate 70) + atypical histology (gate 67).
        *pivotal_gate_supporting_fields(group_order=81),
    ],
)
