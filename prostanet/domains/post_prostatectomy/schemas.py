from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.advanced_support_fields import (
    advanced_io_safety_fields,
    oncologic_emergency_fields,
    pivotal_gate_supporting_fields,
)
from prostanet.shared.epic26 import epic26_widget_config


POST_PROSTATECTOMY_SCHEMA = module_schema(
    "post_prostatectomy",
    "Post-prostatectomía / patología",
    "Evaluación postoperatoria basada en patología, CAPRA-S, riesgo genómico y monitoreo funcional.",
    fields=[
        FieldSpec("psa", "PSA preoperatorio", "number", required=True, default=12, group="PSA y cronología", group_order=1, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_postop", "PSA posoperatorio", "number", default=0.03, group="PSA y cronología", group_order=1, clinical_role="required", unit="ng/mL"),
        FieldSpec("ultrasensitive_psa_assay", "PSA ultrasensible documentado", "select", options=["0", "1"], default="1", group="PSA y cronología", group_order=1, clinical_role="monitoring", evidence_tags=["ultrasensitive_psa"]),
        FieldSpec("local_therapy_date", "Fecha de prostatectomía radical", "date", group="PSA y cronología", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("time_to_recurrence_months", "Tiempo a recurrencia o persistencia", "number", default=0, group="PSA y cronología", group_order=1, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("gleason_primary", "Gleason patológico primario", "select", options=["3", "4", "5"], default="4", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("gleason_secondary", "Gleason patológico secundario", "select", options=["3", "4", "5"], default="3", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("pathologic_stage", "Estadio patológico", "select", options=["pT2", "pT3a", "pT3b", "pT4"], default="pT2", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("surgical_margin", "Margen quirúrgico positivo", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("margin_location", "Localización del margen positivo", "select", options=["", "Ápex", "Base", "Posterolateral", "Múltiple", "Otro"], default="Ápex", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["margin_location"]),
        FieldSpec("ece_status", "Extensión extracapsular", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("svi_status", "Invasión de vesículas seminales", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("lni_status", "Invasión ganglionar", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("lni_positive_count", "N° ganglios positivos", "number", default=0, group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", unit="ganglios", evidence_tags=["lni", "briganti"], conditional_visibility={"lni_status": ["1"]}),
        FieldSpec("lni_total_removed", "N° ganglios totales removidos", "number", default=0, group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", unit="ganglios", evidence_tags=["plnd"]),
        FieldSpec("plnd_extent", "Extensión de PLND", "select", options=["no_plnd", "limited", "standard", "extended"], default="standard", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["plnd"]),
        FieldSpec("margin_length_mm", "Longitud del margen positivo", "number", default=0, group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", unit="mm", evidence_tags=["margin_length"], conditional_visibility={"surgical_margin": ["1"]}),
        FieldSpec("margin_focality", "Focalidad del margen positivo", "select", options=["", "focal", "multifocal", "extenso"], default="focal", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", conditional_visibility={"surgical_margin": ["1"]}),
        FieldSpec("margin_gleason_pattern", "Patrón Gleason en margen", "select", options=["", "3", "4", "5"], default="4", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", conditional_visibility={"surgical_margin": ["1"]}),
        FieldSpec("perineural_invasion", "Invasión perineural (PNI)", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["pni"]),
        FieldSpec("lymphovascular_invasion", "Invasión linfovascular (LVI)", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["lvi"]),
        FieldSpec("cribriform_pattern", "Patrón cribriforme", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["cribriform"]),
        FieldSpec("idc_p_present", "Carcinoma intraductal (IDC-P)", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["idcp"]),
        FieldSpec("histology_variant", "Variante histológica", "select", options=["acinar_estandar", "ductal", "mucinoso", "sarcomatoide", "celula_pequena_NE", "adenoescamoso", "basaloide", "otro"], default="acinar_estandar", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["variant_histology"]),
        FieldSpec("pct_pattern_4_or_5", "Porcentaje de patrón 4/5", "number", default=0, group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", unit="%"),
        FieldSpec("tumor_volume_cc", "Volumen tumoral (cc)", "number", default=0, group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", unit="cc"),
        FieldSpec("surgical_approach", "Abordaje quirúrgico", "select", options=["abierta", "laparoscopica", "robot_asistida"], default="robot_asistida", group="Patología posoperatoria", group_order=2, clinical_role="optional"),
        FieldSpec("clavien_dindo_grade", "Complicaciones Clavien-Dindo", "select", options=["0", "I", "II", "IIIa", "IIIb", "IVa", "IVb", "V"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="monitoring", evidence_tags=["surgical_complication"]),
        FieldSpec("decipher_score", "Decipher GC", "number", default=0.45, group="Refinadores genómicos", group_order=3, clinical_role="optional", unit="0-1", evidence_tags=["decipher"]),
        FieldSpec("decipher_risk", "Riesgo según Decipher", "select", options=["No realizado", "Bajo", "Intermedio", "Alto"], default="No realizado", group="Refinadores genómicos", group_order=3, clinical_role="optional", evidence_tags=["decipher"]),
        FieldSpec("imaging_modality", "Modalidad de imagen para vigilancia", "select", options=["Ninguna", "Convencional", "PSMA-PET"], default="Ninguna", group="Imagen y rescate", group_order=4, clinical_role="monitoring", evidence_tags=["imaging"]),
        FieldSpec("eligible_pelvic_therapy", "Elegible para rescate pélvico", "select", options=["0", "1"], default="1", group="Imagen y rescate", group_order=4, clinical_role="decision_refiner", evidence_tags=["salvage"]),
        FieldSpec(
            "m_stage",
            "Estadio M (TNM clínico)",
            "select",
            options=["", "M0", "M1a", "M1b", "M1c"],
            default="M0",
            group="Imagen y rescate",
            group_order=4,
            clinical_role="required",
            evidence_tags=["embark", "presto", "tnm"],
            help_text="Confirma ausencia de metástasis (M0) — requerido para EMBARK, PRESTO/AFT-19 y RADICALS-RT.",
        ),
        FieldSpec(
            "salvage_rt_window_months",
            "Meses desde RP hasta inicio de salvage RT planeado",
            "number",
            default="",
            group="Imagen y rescate",
            group_order=4,
            clinical_role="decision_refiner",
            unit="meses",
            evidence_tags=["radicals_rt"],
            help_text="RADICALS-RT comparó RT adyuvante vs salvage temprano (PSA <0.1 ng/mL o ventana <6m post-RP).",
        ),
        FieldSpec(
            "early_salvage_window",
            "Ventana de salvage temprano vigente",
            "select",
            options=["", "0", "1"],
            default="",
            group="Imagen y rescate",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["radicals_rt"],
            help_text="1 = sigue dentro de la ventana RADICALS-RT (PSA <0.5 ng/mL post-RP).",
        ),
        FieldSpec(
            "adverse_pathology",
            "Patología adversa post-prostatectomía",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group="Patología posoperatoria",
            group_order=2,
            clinical_role="decision_refiner",
            evidence_tags=["radicals_rt", "swog_8794"],
            help_text=(
                "Uno o más de: Gleason ≥8 pT3+, márgenes positivos, invasión de "
                "vesículas seminales, ISUP ≥4. Gatilla énfasis de salvage RT "
                "temprana (RADICALS-RT, SWOG 8794)."
            ),
        ),
        FieldSpec(
            "bone_lesions_outside_axial",
            "Lesiones óseas fuera del esqueleto axial",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group="Carga metastásica",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["chaarted", "radicals_rt"],
            help_text=(
                "Lesiones apendiculares (costillas, diáfisis, pelvis) fuera del "
                "esqueleto axial. Criterio CHAARTED para clasificación de volumen "
                "alto si el paciente progresa a mHSPC."
            ),
        ),
        FieldSpec("baseline_urinary_qol", "Función urinaria basal posoperatoria", "number", default=60, group="Supervivencia funcional", group_order=5, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
        FieldSpec("baseline_sexual_qol", "Función sexual basal posoperatoria", "number", default=45, group="Supervivencia funcional", group_order=5, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
        # EPIC 9 Group F (GAP-17) — Packet EPIC-26 estructurado post-RP.
        # EPIC-26 es el instrumento primario para cuantificar toxicidad funcional
        # post-prostatectomía (Wei 2000; Sanda 2008 PROST-QA; EAU 2026 §6.3.3).
        # Los campos `baseline_urinary_qol` / `baseline_sexual_qol` (arriba) se
        # mantienen para retrocompat pero el score preciso sale del packet: el
        # service invoca `normalize_epic26_payload` post-captura y deriva los 5
        # dominios (incontinencia urinaria, irritativo/obstructivo, intestinal,
        # sexual, hormonal) + molestia urinaria global. EPIC-26 reemplaza a
        # IPSS/IIEF-5 como fuente primaria de QoL (GAP-17 en post_radiotherapy
        # ya marcó esos instrumentos como `clinical_role="legacy"`).
        FieldSpec(
            "epic26_response_packet",
            "EPIC-26 basal post-prostatectomía",
            "epic26_questionnaire",
            group="Supervivencia funcional",
            group_order=5,
            clinical_role="decision_refiner",
            help_text="Capture los ítems estructurados del EPIC-26; el sistema deriva los 5 dominios oficiales y la molestia urinaria global. Reemplaza IPSS/IIEF-5 como instrumento primario de QoL post-RP.",
            evidence_tags=["qol", "epic26", "epic26_primary_post_rp"],
            widget_config=epic26_widget_config(),
        ),
        *advanced_io_safety_fields(group="Seguridad inmunoterapia", group_order=60),
        # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # Post-RP rara vez debuta emergencia, pero patrón pT3b + Gleason ≥8
        # con PSA persistente puede coincidir con M1 sintomático no detectado.
        *oncologic_emergency_fields(role="decision_refiner", group_order=70),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI: BCR aggressive (gates 53-55), salvage RT (gate 70),
        # atypical histology post-RP (gate 67 IDC/cribriform), trial enrollment.
        *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
    ],
)
