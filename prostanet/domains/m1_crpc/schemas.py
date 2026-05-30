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
from prostanet.shared.pivotal_gate_manual_override_fields import (
    pivotal_gate_manual_override_fields,
)


M1_CRPC_SCHEMA = module_schema(
    "m1_crpc",
    "M1 CRPC",
    "Ruta de enfermedad resistente a la castración con metástasis, dirigida por biomarcadores, secuencia terapéutica y elegibilidad estructurada a taxanos.",
    fields=[
        FieldSpec("hrr_status", "Estado HRR", "select", options=["Desconocido", "Positivo", "Negativo"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="required", evidence_tags=["hrr"]),
        FieldSpec("hrr_gene", "Gen HRR predominante", "select", options=["Desconocido", "BRCA2", "BRCA1", "ATM", "PALB2", "CDK12", "Otro"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["hrr"], conditional_visibility={'hrr_status': ['Positivo']}),
        FieldSpec("msi_status", "Estado MSI", "select", options=["desconocido", "inestable", "estable"], default="desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["msi"]),
        FieldSpec("mmr_ihc_status", "Estado dMMR por IHC", "select", options=["desconocido", "proficient_pMMR", "deficient_dMMR"], default="desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["msi", "dmmr", "keynote_158"], help_text="IHC para MLH1/MSH2/MSH6/PMS2 — pérdida ≥1 confirma dMMR aunque MSI PCR sea indeterminado.", conditional_visibility={'msi_status': ['inestable', 'desconocido']}),
        FieldSpec("tmb_high", "Carga mutacional tumoral alta", "select", options=["0", "1"], default="0", group="Biomarcadores", group_order=1, clinical_role="optional", evidence_tags=["tmb"]),
        FieldSpec("tmb_value", "TMB (mutaciones/Mb)", "number", default="", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", unit="mut/Mb", evidence_tags=["tmb"], help_text="Pembrolizumab aprobado en TMB ≥10 mut/Mb (KEYNOTE-158).", conditional_visibility={'tmb_high': ['1']}),
        FieldSpec("biomarker_source", "Fuente del biomarcador", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=1, clinical_role="required", evidence_tags=["hrr", "msi", "vision"], conditional_visibility={'somatic_testing_performed': ['1']}),
        FieldSpec("molecular_report_date", "Fecha del informe molecular", "date", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["molecular_traceability"], conditional_visibility={'somatic_testing_performed': ['1']}),
        FieldSpec("germline_testing_performed", "Pruebas germinales realizadas", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="required", evidence_tags=["germline", "nccn_pros_h"], help_text="NCCN PROS-H categoría 2A: obligatorio en enfermedad metastásica."),
        FieldSpec("germline_pathogenic_variant", "Variante germinal patogénica", "select", options=["ninguna", "BRCA2", "BRCA1", "ATM", "PALB2", "CHEK2", "MSH2", "MLH1", "MSH6", "PMS2", "Otro", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["germline"], conditional_visibility={"germline_testing_performed": ["1"]}, help_text="Variante patogénica/probablemente patogénica germinal. Detonante de consejería genética para familiares."),
        FieldSpec("germline_test_date", "Fecha de la prueba germinal", "date", group="Biomarcadores", group_order=1, clinical_role="monitoring", evidence_tags=["germline"], conditional_visibility={"germline_testing_performed": ["1"]}),
        FieldSpec("somatic_testing_performed", "Pruebas somáticas realizadas", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="required", evidence_tags=["somatic", "hrr"], help_text="Tejido tumoral/ctDNA — HRR somático amplía candidatos PARPi aunque germinal sea negativo."),
        FieldSpec("somatic_pathogenic_variant", "Variante somática patogénica", "select", options=["ninguna", "BRCA2", "BRCA1", "ATM", "PALB2", "CHEK2", "CDK12", "MSH2", "MLH1", "MSH6", "PMS2", "Otro", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["somatic", "hrr"], conditional_visibility={"somatic_testing_performed": ["1"]}),
        FieldSpec(
            "pten_loss",
            "Pérdida de PTEN (IHC o NGS)",
            "select",
            options=["", "0", "1", "Desconocido"],
            default="",
            group="Biomarcadores",
            group_order=1,
            clinical_role="decision_refiner",
            evidence_tags=["ipatential150", "capitello281"],
            help_text="Pérdida bialélica de PTEN — gatilla IPATential150 (ipatasertib + abiraterona) en mCRPC.",
        ),
        FieldSpec(
            "prior_arpi_progression_months",
            "Meses desde inicio de ARPI hasta progresión",
            "number",
            default="",
            group="Secuencia terapéutica",
            group_order=3,
            clinical_role="decision_refiner",
            unit="meses",
            evidence_tags=["card", "psmafore", "vision"],
            help_text="Tiempo a progresión bajo ARPI previo — informa elegibilidad CARD (rapid progression <12m), PSMAfore y VISION.",
        ),
        FieldSpec("family_history_cancer", "Historia familiar oncológica relevante", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=1, clinical_role="decision_refiner", evidence_tags=["germline"], help_text="CA próstata metastásico, mama, ovario, páncreas, colorrectal — criterio NCCN PROS-H para extender testing."),
        FieldSpec("metastasis_site", "Sitio metastásico", "select", options=["Bone", "Node", "Visceral"], default="Bone", group="Carga tumoral", group_order=2, clinical_role="required"),
        FieldSpec(
            "extra_pelvic_nodal_metastasis",
            "Adenopatías extra-pélvicas",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group="Carga tumoral",
            group_order=2,
            clinical_role="decision_refiner",
            evidence_tags=["contact02"],
            help_text=(
                "Adenopatías no regionales (retroperitoneales, mediastínicas, "
                "supraclaviculares). Criterio CONTACT-02 junto con viscerales."
            ),
        ),
        *advanced_visceral_site_fields(group="Sitios viscerales estructurados", group_order=2),
        FieldSpec("prior_therapy", "Terapias previas", "text", default="Abiraterona", group="Secuencia terapéutica", group_order=3, clinical_role="required", evidence_tags=["sequence"]),
        # EPIC 9 Group F (GAP-14) — Campos decisivos mínimos CRPC declarados explícitamente
        # en el schema para alinear captura con `clinical_decision_governance.CRPC_MINIMUM_DECISIVE_FIELDS`
        # (líneas 159-167) y con `decision_input_requirements_engine.REQUIREMENTS["m1_crpc"]`
        # (línea 285, blocking_inputs=testosterone+line_of_therapy_number+drug_scheme+progression_pattern).
        # Defaults retrocompatibles: backward-compat con visitas preexistentes EPIC 3.
        # Options canónicas `current_adt_context` desde `shared/presentation_text.py:84`.
        # Options canónicas `drug_scheme` alineadas con `therapy_catalog.THERAPY_CATALOG` regimen_codes.
        FieldSpec("current_adt_context", "Contexto actual de ADT", "select", options=["none", "medical_adt_continuous", "orchiectomy", "intermittent_adt"], default="medical_adt_continuous", group="Secuencia terapéutica", group_order=3, clinical_role="required", evidence_tags=["castration_context", "governance_crpc_minimum"]),
        FieldSpec("line_of_therapy_number", "Número de línea terapéutica actual", "number", default=1, group="Secuencia terapéutica", group_order=3, clinical_role="required", unit="línea", evidence_tags=["sequence", "governance_crpc_minimum"], conditional_visibility={'current_treatment_active': ['yes', '1']}),
        FieldSpec("drug_scheme", "Esquema farmacológico actual", "select", options=["Desconocido", "ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE", "DOCETAXEL", "CABAZITAXEL", "OLAPARIB", "TALAZOPARIB_ENZALUTAMIDE", "NIRAPARIB_ABIRATERONE", "LU177_PSMA617"], default="Desconocido", group="Secuencia terapéutica", group_order=3, clinical_role="required", evidence_tags=["sequence", "therapy_catalog", "governance_crpc_minimum"], conditional_visibility={'current_treatment_active': ['yes', '1']}),
        *advanced_adt_timeline_fields(group="Terapia de privación androgénica", group_order=3),
        FieldSpec("prior_docetaxel_cycles", "Ciclos previos de docetaxel", "number", default=0, group="Secuencia terapéutica", group_order=3, clinical_role="required", unit="ciclos"),
        FieldSpec("prior_parp_inhibitor", "Inhibidor PARP previo", "select", options=["0", "1"], default="0", group="Secuencia terapéutica", group_order=3, clinical_role="decision_refiner", evidence_tags=["sequence", "parp"], help_text="Activa ruta post-PARP (rules_post_parp) — mecanismo ortogonal preferido."),
        FieldSpec("months_since_last_parp", "Meses desde última exposición PARP", "number", default="", group="Secuencia terapéutica", group_order=3, clinical_role="decision_refiner", unit="meses", conditional_visibility={"prior_parp_inhibitor": ["1"]}, help_text="≥6 meses habilita rechallenge platino en BRCA/HRR+ con reserva medular preservada."),
        FieldSpec("castrate_testosterone_confirmed", "Testosterona en rango de castración confirmada", "select", options=["0", "1"], default="1", group="Secuencia terapéutica", group_order=3, clinical_role="required", evidence_tags=["castration_confirmation"]),
        FieldSpec("mcrpc_line_context", "Contexto de línea en mCRPC", "select", options=["first_line_mcrpc", "post_arpi_pre_taxane", "post_taxane", "later_line"], default="first_line_mcrpc", group="Secuencia terapéutica", group_order=3, clinical_role="required", evidence_tags=["sequence"]),
        FieldSpec("chemotherapy_delay_candidate", "Candidato a diferir o evitar docetaxel", "select", options=["0", "1"], default="0", group="Secuencia terapéutica", group_order=3, clinical_role="decision_refiner", evidence_tags=["sequence"]),
        FieldSpec(
            "not_chemotherapy_candidate",
            "No candidato a quimioterapia",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group="Secuencia terapéutica",
            group_order=3,
            clinical_role="decision_refiner",
            evidence_tags=["contact02", "card"],
            help_text=(
                "Paciente rehúsa o no es candidato a quimioterapia por fragilidad, "
                "comorbilidad o elección informada. Criterio CONTACT-02 y CARD."
            ),
        ),
        FieldSpec("pain_symptoms", "Síntomas óseos / dolor", "select", options=["Asintomatico", "Leve", "Sintomatico"], default="Asintomatico", group="Secuencia terapéutica", group_order=3, clinical_role="decision_refiner", evidence_tags=["symptoms"]),
        FieldSpec(
            "opioid_use_for_pain",
            "Uso de opioides para dolor",
            "select",
            options=["Ninguno", "Intermitente", "Crónico", "Inicio reciente", "Desconocido"],
            default="Desconocido",
            group="Secuencia terapéutica",
            group_order=3,
            clinical_role="decision_refiner",
            evidence_tags=["impact"],
            help_text=(
                "Uso de opioides para dolor oncológico. IMPACT restringe sipuleucel-T "
                "a pacientes asintomáticos o mínimamente sintomáticos sin opioides "
                "crónicos."
            ),
        ),
        FieldSpec("ecog_score", "ECOG", "number", default=1, group="Fitness y seguridad", group_order=4, clinical_role="required", unit="0-4"),
        FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["frailty"]),
        *advanced_hepatic_fields(group="Fitness y seguridad", group_order=4, child_pugh_role="decision_refiner"),
        *advanced_renal_function_fields(group="Función renal basal", group_order=4),
        *advanced_laboratory_baseline_fields(group="Marcadores pronósticos Halabi", group_order=4),
        FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
        FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
        FieldSpec("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["0", "1", "2", "3", "4"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", unit="CTCAE"),
        *advanced_variant_histology_fields(group="Fitness y seguridad", group_order=4, include_neuroendocrine_toggle=False),
        FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
        *advanced_ddi_fields(group="Fitness y seguridad", group_order=4),
        FieldSpec("dermatitis_history", "Antecedente dermatológico relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
        FieldSpec("cognitive_risk", "Riesgo cognitivo clínicamente relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["neurotoxicity"]),
        FieldSpec("fall_risk", "Riesgo de caídas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["falls"]),
        FieldSpec("stroke_history", "Antecedente de EVC/AIT", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["neurovascular"]),
        FieldSpec("edema_risk", "Riesgo de edema / IC", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
        FieldSpec("steroid_intolerance", "Intolerancia a esteroides", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["steroids"]),
        FieldSpec("diabetes_uncontrolled", "Diabetes no controlada", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=4, clinical_role="decision_refiner", evidence_tags=["metabolic_risk"]),
        FieldSpec("baseline_bp", "Presión arterial basal sistólica", "number", default="", group="Monitoreo basal ARPI", group_order=5, clinical_role="monitoring", unit="mmHg", evidence_tags=["cardio_oncology"]),
        FieldSpec("baseline_weight", "Peso basal", "number", default="", group="Monitoreo basal ARPI", group_order=5, clinical_role="monitoring", unit="kg", evidence_tags=["qol"]),
        *advanced_cognitive_fields(group="Monitoreo basal ARPI", group_order=5),
        FieldSpec("fall_history_recent", "Caídas recientes", "select", options=["0", "1"], default="0", group="Monitoreo basal ARPI", group_order=5, clinical_role="monitoring", evidence_tags=["falls"]),
        FieldSpec("potassium", "Potasio basal", "number", default="", group="Monitoreo basal ARPI", group_order=5, clinical_role="monitoring", unit="mEq/L", evidence_tags=["metabolic_risk"]),
        FieldSpec("glucose_or_hba1c", "Glucosa o HbA1c basal", "number", default="", group="Monitoreo basal ARPI", group_order=5, clinical_role="monitoring", evidence_tags=["metabolic_risk"]),
        FieldSpec("cbc_date", "Fecha de biometría hemática", "date", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("anc", "Neutrófilos absolutos", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="/mm3", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("platelets", "Plaquetas", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="/mm3", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("liver_panel_date", "Fecha de pruebas hepáticas", "date", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("bilirubin", "Bilirrubina total", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="mg/dL", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("ast", "AST", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="U/L", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("alt", "ALT", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="U/L", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("alp", "Fosfatasa alcalina", "number", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", unit="U/L", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("taxane_hypersensitivity_history", "Hipersensibilidad previa a taxanos", "select", options=["0", "1"], default="0", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("polysorbate_hypersensitivity", "Hipersensibilidad a polisorbato 80", "select", options=["0", "1"], default="0", group="Elegibilidad taxano", group_order=5, clinical_role="decision_refiner", evidence_tags=["taxane_fitness"], conditional_visibility={"prior_docetaxel_cycles": ["0"]}),
        FieldSpec("psma_positive", "PSMA positivo", "select", options=["0", "1"], default="0", group="Imagen funcional", group_order=6, clinical_role="required", evidence_tags=["vision"]),
        FieldSpec("psma_negative_dominant_lesions", "Lesiones dominantes PSMA-negativas", "select", options=["0", "1"], default="0", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", evidence_tags=["vision"]),
        FieldSpec("psma_pet_done", "PSMA-PET estructurado disponible", "select", options=["0", "1"], default="0", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", evidence_tags=["vision"]),
        FieldSpec("psma_radioligand", "Radioligando PSMA", "select", options=["68Ga-PSMA-11", "18F-DCFPyL", "18F-PSMA-1007", "Otro", "Desconocido"], default="Desconocido", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", evidence_tags=["vision"], conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_index_lesion_site", "Lesión índice PSMA", "text", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_index_lesion_suvmax", "SUVmax lesión índice", "number", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", unit="SUV", conditional_visibility={"psma_pet_done": ["1"]}, help_text="Criterio VISION: SUVmax lesión índice ≥ SUV medio hepático."),
        FieldSpec("psma_suvmean_liver", "SUV medio hepático (referencia VISION)", "number", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", unit="SUV", conditional_visibility={"psma_pet_done": ["1"]}, help_text="Referencia hepática para criterio VISION/PSMAfore (valor medio en región hepática sana)."),
        FieldSpec("psma_lesion_suvmax_minimum", "SUVmax mínimo de lesiones tratables", "number", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", unit="SUV", conditional_visibility={"psma_pet_done": ["1"]}, help_text="SUVmax de la lesión tratable con menor captación — apoya control de clones heterogéneos."),
        FieldSpec("psma_uptake_pattern", "Patrón de captación", "select", options=["focal", "multifocal", "diseminado", "indeterminado"], default="indeterminado", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_rads_score", "PSMA-RADS", "select", options=["1", "2", "3", "4", "5", "Desconocido"], default="Desconocido", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_total_lesions", "Número total de lesiones PSMA", "number", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_lesion_locations", "Localización de lesiones PSMA", "text", group="Imagen funcional", group_order=6, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("neuroendocrine_features", "Rasgos neuroendocrinos clínicos", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc", "variant_histology"], help_text="Patrón viscerales + PSA bajo + LDH elevada + marcadores CgA/NSE elevados."),
        FieldSpec("nepc_confirmed_histology", "NEPC confirmado histológicamente", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc", "variant_histology"], help_text="IHC positiva para sinaptofisina y/o cromogranina confirma NEPC — activa régimen platino."),
        FieldSpec("ihc_synaptophysin_positive", "IHC sinaptofisina positiva", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"], conditional_visibility={"nepc_confirmed_histology": ["1"]}),
        FieldSpec("ihc_chromogranin_positive", "IHC cromogranina A positiva", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"], conditional_visibility={"nepc_confirmed_histology": ["1"]}),
        FieldSpec("ihc_ar_loss", "Pérdida de AR por IHC", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"], conditional_visibility={"nepc_confirmed_histology": ["1"]}),
        FieldSpec("ki67_percent", "Ki-67 (%)", "number", default="", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", unit="%", evidence_tags=["nepc"], conditional_visibility={"nepc_confirmed_histology": ["1"]}),
        FieldSpec("small_cell_morphology", "Morfología de células pequeñas", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"]),
        FieldSpec("nse", "NSE (enolasa neuronal específica)", "number", default="", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", unit="ng/mL", evidence_tags=["nepc"], help_text="Umbral orientativo: >16.3 ng/mL apoya sospecha NEPC."),
        FieldSpec("chromogranin_a", "Cromogranina A sérica", "number", default="", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", unit="ng/mL", evidence_tags=["nepc"], help_text="Umbral orientativo: >100 ng/mL apoya sospecha neuroendocrina."),
        FieldSpec("ldh", "LDH", "number", default="", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", unit="U/L", evidence_tags=["nepc", "halabi"], help_text=">250 U/L apoya sospecha NEPC y es marcador Halabi."),
        FieldSpec("psa_discordant_low", "PSA discordantemente bajo para carga", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"], help_text="PSA bajo a pesar de carga tumoral alta — señal de transformación neuroendocrina."),
        FieldSpec("visceral_without_bone_progression", "Progresión viscerales sin óseo", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc"]),
        FieldSpec("cisplatin_hearing_loss_history", "Hipoacusia/ototoxicidad previa", "select", options=["0", "1"], default="0", group="Histología agresiva y NEPC", group_order=6, clinical_role="decision_refiner", evidence_tags=["nepc", "cisplatin_safety"], help_text="Si está presente, preferir carboplatino sobre cisplatino."),
        *advanced_pro_dropdown_fields(group="Resultados reportados por el paciente", group_order=7),
        *advanced_chemotherapy_fitness_fields(group="Aptitud a quimioterapia", group_order=52),
        *advanced_neutropenia_fields(group="Seguridad hematológica", group_order=55),
        *advanced_io_safety_fields(group="Seguridad inmunoterapia", group_order=60),
        # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # En m1 CRPC se mantiene como decision_refiner para escalar a
        # urgencia sin bloquear la captura cuando estos campos no aplican.
        *oncologic_emergency_fields(role="decision_refiner", group_order=70),
        # ── Contraindicaciones de ensayos pivote (FAUBOT 2026-04-23) ──
        # IPATential150 (ipatasertib) / TROPIC-CARD (cabazitaxel) / TRITON-3
        # (rucaparib) / ERA-223-PEACE-3 (Ra-223) / CONTACT-02 (cabozantinib).
        *pivotal_contraindication_fields(role="decision_refiner", group_order=80),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI de fields para gates de RP-vs-RT subspecialty, genomic
        # critical (HRR/AR-V7/CDK12/HRD/MSI), pre-dx atypical (NEPC/emergency).
        *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
        # ── EPIC 10B fix — Cableado cardio-cognitivo y minerales óseos ──
        # advanced_cardio_fields y advanced_bone_turnover_fields contienen
        # los FieldSpecs canónicos (`nyha_class`, `lvef_percent`,
        # `qtc_change_ms`, `mmse_baseline/current`, `moca_baseline/current`,
        # `ionized_calcium`, etc.) pero no estaban siendo invocados en
        # ningún schema, dejando 7 hard-blocks pivotales con triggers
        # huérfanos (NUNCA disparaban con datos reales). Detectado por
        # `tests/test_epic10b_gate_field_coverage.py`.
        *advanced_cardio_fields(group="Cardio-cognitivo basal y dinámica", group_order=82),
        *advanced_bone_turnover_fields(group="Soporte óseo y mineral", group_order=83),
        # ── EPIC 10B fix — Aliases canónicos para gates pivotales ──
        # Resuelve el naming drift detectado entre el catálogo YAML
        # (`hemoglobin`, `mds_history`, `aml_history`, `clinical_t_stage`)
        # y los helpers canónicos (`hemoglobin_g_dl`, `prior_mds`,
        # `prior_aml`, `clinical_tstage`). Declaramos los aliases como
        # FieldSpecs explícitos para que el audit los reconozca y el
        # runtime pueda recibir cualquier naming.
        FieldSpec("hemoglobin", "Hemoglobina (g/dL) — alias EPIC 10B", "number", default="", group="Aliases canónicos EPIC 10B", group_order=84, clinical_role="decision_refiner", unit="g/dL", evidence_tags=["epic10b_alias", "halabi"], help_text="Alias de hemoglobin_g_dl. Aceptado por gates pivotales (cabazitaxel/lutetium Hb drop). Captura idéntica."),
        FieldSpec("mds_history", "Historia de SMD — alias EPIC 10B", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Aliases canónicos EPIC 10B", group_order=84, clinical_role="decision_refiner", evidence_tags=["epic10b_alias", "parp_safety"], help_text="Alias de prior_mds/mds_aml_history. Contraindica PARPi."),
        FieldSpec("aml_history", "Historia de LMA — alias EPIC 10B", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Aliases canónicos EPIC 10B", group_order=84, clinical_role="decision_refiner", evidence_tags=["epic10b_alias", "parp_safety"], help_text="Alias de prior_aml/mds_aml_history. Contraindica PARPi."),
        FieldSpec("clinical_t_stage", "Estadio clínico T (cT) — alias EPIC 10B", "select", options=["", "T1a", "T1b", "T1c", "T2a", "T2b", "T2c", "T3a", "T3b", "T4"], default="", group="Aliases canónicos EPIC 10B", group_order=84, clinical_role="decision_refiner", evidence_tags=["epic10b_alias", "ajcc_8"], help_text="Alias de clinical_tstage. Captura TNM cT directamente con prefix clínico."),
        # ── EPIC 10F — Manual override flags para gates pivotales ──
        # 59 FieldSpecs flag (select 0/1) que declaran procedimientos
        # explícitos del clínico (consultas, planes, monitoreo) que activan
        # override de hard-blocks pivotales. Cierra los 20 gates huérfanos
        # restantes del audit EPIC 10B detectados como "override strings
        # narrativos no capturables". Cada flag traza al gate específico
        # vía evidence_tags. Ver prostanet/shared/pivotal_gate_manual_override_fields.py.
        *pivotal_gate_manual_override_fields(group_order=85),
    ],
)
