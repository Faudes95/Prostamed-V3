from __future__ import annotations

from prostanet.shared.advanced_support_catalog import (
    ADVANCED_VARIANT_HISTOLOGY_OPTIONS,
    COGNITIVE_SCREEN_SOURCE_OPTIONS,
    DDI_REVIEW_STATUS_OPTIONS,
    MINI_COG_OPTIONS,
    PRO_BAND_OPTIONS,
)
from prostanet.shared.contracts import FieldSpec


def advanced_hepatic_fields(
    *,
    group: str,
    group_order: int,
    child_pugh_role: str = "required",
    include_bundle_inputs: bool = True,
) -> list[FieldSpec]:
    fields = [
        FieldSpec(
            "child_pugh_score",
            "Child-Pugh",
            "select",
            options=["A", "B", "C"],
            default="A",
            group=group,
            group_order=group_order,
            clinical_role=child_pugh_role,
            evidence_tags=["hepatotoxicity"],
            help_text=(
                "Clasificación de función hepática Child-Pugh. B/C contraindica "
                "abiraterona (FDA Zytiga §5.1) y es gate compartido en PROpel, "
                "COU-AA-301/302, IPATential150, LATITUDE y PEACE-1. "
                "Acepta alias boolean `child_pugh_b_or_c` (Sí=B o C)."
            ),
        ),
    ]
    if include_bundle_inputs:
        fields.extend(
            [
                FieldSpec(
                    "active_liver_disease",
                    "Hepatopatía activa",
                    "select",
                    options=["0", "1"],
                    default="0",
                    group=group,
                    group_order=group_order,
                    clinical_role="decision_refiner",
                    evidence_tags=["hepatotoxicity"],
                ),
                FieldSpec(
                    "cirrhosis_or_portal_hypertension",
                    "Cirrosis o hipertensión portal",
                    "select",
                    options=["0", "1"],
                    default="0",
                    group=group,
                    group_order=group_order,
                    clinical_role="decision_refiner",
                    evidence_tags=["hepatotoxicity"],
                ),
                FieldSpec(
                    "active_hepatitis_b_or_c",
                    "Hepatitis B o C activa",
                    "select",
                    options=["0", "1"],
                    default="0",
                    group=group,
                    group_order=group_order,
                    clinical_role="decision_refiner",
                    evidence_tags=["hepatotoxicity"],
                ),
                FieldSpec(
                    "prior_drug_induced_liver_injury",
                    "Antecedente de hepatotoxicidad por fármacos",
                    "select",
                    options=["0", "1"],
                    default="0",
                    group=group,
                    group_order=group_order,
                    clinical_role="decision_refiner",
                    evidence_tags=["hepatotoxicity"],
                ),
            ]
        )
    return fields


def advanced_renal_function_fields(
    *,
    group: str = "Función renal basal",
    group_order: int = 3,
) -> list[FieldSpec]:
    """Captura creatinina sérica + eGFR (CKD-EPI 2021) + fecha + fórmula.

    Requerido por abiraterona (FDA §2.3: eGFR <30 → 500 mg), cabazitaxel,
    olaparib (reducción 31-50), talazoparib, radium-223, denosumab.
    """
    return [
        FieldSpec(
            "creatinine_mg_dl",
            "Creatinina sérica",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="mg/dL",
            min_value=0.05,
            max_value=30.0,
            allow_negative=False,
            evidence_tags=["renal_function", "ckd_epi"],
            help_text="Requerida para cálculo eGFR (CKD-EPI 2021) y dosificación de abiraterona/cabazitaxel/PARPi.",
        ),
        FieldSpec(
            "egfr_ml_min",
            "eGFR",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="mL/min/1.73m²",
            min_value=0.0,
            max_value=180.0,
            allow_negative=False,
            evidence_tags=["renal_function", "ckd_epi"],
            help_text="Si se ingresa creatinina + edad + sexo, ProstaNet calcula automáticamente el eGFR con CKD-EPI 2021.",
        ),
        FieldSpec(
            "egfr_formula",
            "Fórmula eGFR",
            "select",
            options=["ckd_epi_2021", "mdrd", "cockcroft_gault"],
            default="ckd_epi_2021",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["renal_function"],
            help_text="Inker 2021 NEJM (CKD-EPI 2021) sin coeficiente de raza — por defecto. Cockcroft-Gault requiere peso.",
        ),
        FieldSpec(
            "egfr_date",
            "Fecha de la creatinina/eGFR",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["renal_function"],
            help_text="Frescura recomendada ≤ 90 días para decisiones terapéuticas activas.",
        ),
    ]


def advanced_laboratory_baseline_fields(
    *,
    group: str = "Marcadores pronósticos Halabi",
    group_order: int = 4,
) -> list[FieldSpec]:
    """Halabi 2014 IPS: albumin, LDH, hemoglobin — todos log-transformados."""
    return [
        FieldSpec(
            "albumin_g_dl",
            "Albúmina sérica",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="g/dL",
            min_value=1.0,
            max_value=6.0,
            allow_negative=False,
            evidence_tags=["halabi", "laboratory"],
            help_text="Halabi 2014 JCO 32:671 — protector (β=−0.155 por g/dL).",
        ),
        FieldSpec(
            "ldh_u_l",
            "LDH sérica",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="U/L",
            min_value=1.0,
            max_value=10000.0,
            allow_negative=False,
            evidence_tags=["halabi", "laboratory"],
            help_text="Halabi 2014 — coeficiente log (β=0.652). Elevada en NEPC/carga tumoral alta.",
        ),
        FieldSpec(
            "hemoglobin_g_dl",
            "Hemoglobina",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="g/dL",
            min_value=3.0,
            max_value=22.0,
            allow_negative=False,
            evidence_tags=["halabi", "laboratory"],
            help_text="Halabi 2014 — protector (β=−0.124 por g/dL).",
        ),
        FieldSpec(
            "alkaline_phosphatase_u_l",
            "Fosfatasa alcalina (FA)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="U/L",
            min_value=1.0,
            max_value=5000.0,
            allow_negative=False,
            evidence_tags=["halabi", "laboratory"],
            help_text="Halabi 2014 — coeficiente log (β=0.318). Refleja carga ósea.",
        ),
        FieldSpec(
            "labs_baseline_date",
            "Fecha del panel basal (albumin/LDH/Hgb/FA)",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["halabi"],
            help_text="Frescura recomendada ≤ 60 días para cálculo Halabi reciente.",
        ),
    ]


def advanced_adt_timeline_fields(
    *,
    group: str = "Terapia de privación androgénica",
    group_order: int = 5,
) -> list[FieldSpec]:
    """Fecha de inicio ADT + agente principal (bloquea cálculo de castración
    resistencia sin este dato)."""
    return [
        FieldSpec(
            "adt_start_date",
            "Fecha de inicio de ADT",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["adt", "castration_resistance"],
            help_text="Requerida para calcular tiempo a CRPC y activar alertas Ra-223/denosumab tras 12m.",
        ),
        FieldSpec(
            "adt_primary_agent",
            "Agente ADT principal",
            "select",
            options=[
                "leuprolide_acetate",
                "goserelin",
                "triptorelin",
                "degarelix",
                "relugolix",
                "orquiectomia_bilateral",
                "combinado_arpi",
                "otro",
            ],
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["adt"],
            help_text="Necesario para detectar interrupciones y cobrar castration-gap.",
        ),
        FieldSpec(
            "adt_intent",
            "Intención ADT",
            "select",
            options=["continuous", "intermittent", "bridging", "completed"],
            default="continuous",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["adt"],
        ),
    ]


def advanced_visceral_site_fields(
    *,
    group: str = "Sitios viscerales estructurados",
    group_order: int = 6,
) -> list[FieldSpec]:
    """Halabi 2014 separa hígado (HR 2.1) vs pulmón (HR 1.4). Hoy ProstaNet
    agrega todos en ``visceral_metastases`` boolean, perdiendo esta señal."""
    return [
        FieldSpec(
            "visceral_lung",
            "Metástasis pulmonares",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["halabi", "visceral"],
            help_text="Halabi HR=1.41 vs no visceral.",
        ),
        FieldSpec(
            "visceral_liver",
            "Metástasis hepáticas",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["halabi", "visceral"],
            help_text="Halabi HR=2.09 vs no visceral — peor pronóstico visceral.",
        ),
        FieldSpec(
            "visceral_adrenal",
            "Metástasis suprarrenales",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["halabi", "visceral"],
        ),
        FieldSpec(
            "visceral_cns",
            "Metástasis SNC",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["halabi", "visceral"],
            help_text="CNS/leptomeníngeo — indicación de MRI/TC SNC + considerar derivación.",
        ),
    ]


def advanced_ddi_fields(*, group: str, group_order: int) -> list[FieldSpec]:
    return [
        FieldSpec(
            "ddi_review_status",
            "Estado de revisión de interacciones",
            "select",
            options=DDI_REVIEW_STATUS_OPTIONS,
            default="not_started",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["drug_interactions"],
        ),
        FieldSpec(
            "current_medications",
            "Medicaciones concomitantes",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["drug_interactions"],
            help_text="Ingrese fármacos concomitantes separados por coma para que el motor DDI detecte interacciones concretas por candidato terapéutico.",
        ),
    ]


def advanced_cognitive_fields(*, group: str, group_order: int) -> list[FieldSpec]:
    return [
        FieldSpec(
            "mini_cog_score",
            "Mini-Cog",
            "select",
            options=MINI_COG_OPTIONS,
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["neurotoxicity", "geriatric_screening"],
        ),
        FieldSpec(
            "mini_cog_date",
            "Fecha de Mini-Cog",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["geriatric_screening"],
        ),
        FieldSpec(
            "cognitive_screen_source",
            "Fuente del cribado cognitivo",
            "select",
            options=COGNITIVE_SCREEN_SOURCE_OPTIONS,
            default="bedside_clinic",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["geriatric_screening"],
        ),
    ]


def advanced_pro_dropdown_fields(*, group: str, group_order: int) -> list[FieldSpec]:
    return [
        FieldSpec(
            "eq5d_vas_band",
            "EQ-5D VAS basal",
            "select",
            options=PRO_BAND_OPTIONS["eq5d_vas_band"],
            default="60_79",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["qol"],
            help_text="Seleccione el rango que mejor represente el estado global basal del paciente.",
        ),
        FieldSpec(
            "fact_p_total_band",
            "FACT-P basal",
            "select",
            options=PRO_BAND_OPTIONS["fact_p_total_band"],
            default="90_109",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["qol"],
            help_text="Use el rango que mejor represente la carga sintomática y funcional basal en enfermedad avanzada.",
        ),
        FieldSpec(
            "bpi_worst_pain_band",
            "BPI dolor peor basal",
            "select",
            options=PRO_BAND_OPTIONS["bpi_worst_pain_band"],
            default="0_3",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["pain", "qol"],
        ),
        FieldSpec(
            "fatigue_score_band",
            "Fatiga basal",
            "select",
            options=PRO_BAND_OPTIONS["fatigue_score_band"],
            default="0_3",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["fatigue", "qol"],
        ),
    ]


def advanced_variant_histology_fields(
    *,
    group: str,
    group_order: int,
    include_neuroendocrine_toggle: bool = True,
) -> list[FieldSpec]:
    fields = [
        FieldSpec(
            "rare_histology_variant",
            "Variante histológica agresiva poco común",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="optional",
            evidence_tags=["variant_histology"],
        ),
        FieldSpec(
            "adverse_histology_variant_type",
            "Subtipo de variante histológica",
            "select",
            options=ADVANCED_VARIANT_HISTOLOGY_OPTIONS,
            default="none",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["variant_histology"],
            conditional_visibility={"rare_histology_variant": ["1"]},
        ),
        FieldSpec(
            "adverse_histology_variant_detail",
            "Detalle de la variante histológica",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["variant_histology"],
            conditional_visibility={"rare_histology_variant": ["1"]},
        ),
        FieldSpec(
            "variant_histology_report_date",
            "Fecha del reporte histológico",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["variant_histology"],
            conditional_visibility={"rare_histology_variant": ["1"]},
        ),
        FieldSpec(
            "variant_histology_source",
            "Fuente del reporte histológico",
            "select",
            options=["Desconocida", "Biopsia primaria", "Biopsia metastásica", "Pieza quirúrgica", "Documento externo"],
            default="Desconocida",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["variant_histology"],
            conditional_visibility={"rare_histology_variant": ["1"]},
        ),
    ]
    if include_neuroendocrine_toggle:
        fields.append(
            FieldSpec(
                "neuroendocrine_features",
                "Rasgos neuroendocrinos emergentes",
                "select",
                options=["0", "1"],
                default="0",
                group=group,
                group_order=group_order,
                clinical_role="optional",
                evidence_tags=["variant_histology"],
            )
        )
    return fields


def advanced_cardio_fields(
    *,
    group: str = "Cardio-oncología",
    group_order: int = 4,
) -> list[FieldSpec]:
    """FEVI, riesgo cardio basal y vigilancia ARPI / taxano.

    Referencia: SCA/ESC guidelines 2022 cardio-oncology; FDA ARPI label.
    """
    return [
        FieldSpec(
            "lvef_percent",
            "Fracción de eyección VI (FEVI)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="%",
            evidence_tags=["cardio_oncology", "lvef"],
        ),
        FieldSpec(
            "lvef_date",
            "Fecha del ecocardiograma/MUGA",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["cardio_oncology"],
        ),
        FieldSpec(
            "qtc_ms",
            "QTc basal (Fridericia)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ms",
            evidence_tags=["qtc"],
        ),
        # Faubot 2026-04-25 (VII) — Gate 17 ARPI cardiotox.
        # Cambio QTc desde basal — necesario para detectar ΔQTc grado 3
        # (>60 ms desde basal) según CTCAE v5.0 + ICH E14.
        FieldSpec(
            "qtc_change_ms",
            "Cambio QTc desde basal (ECG seguimiento)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ms",
            evidence_tags=["qtc", "ctcae_v5", "ich_e14", "enzamet"],
            help_text=(
                "ΔQTc = QTc actual - QTc basal. CTCAE v5.0 grado 3 = >60 ms. "
                "Si >60 ms, contraindica enzalutamida (gate 17 pivotal_contraindication_gates)."
            ),
        ),
        # Faubot 2026-04-25 (VII) — Gate 18 ARPI cardiotox.
        # FEVI basal pre-tratamiento — necesario para calcular caída
        # absoluta >10 puntos durante seguimiento con apalutamida.
        FieldSpec(
            "lvef_baseline_percent",
            "FEVI basal pre-tratamiento (eco/MUGA)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="%",
            evidence_tags=["cardio_oncology", "titan", "spartan", "asco_esc_2022"],
            help_text=(
                "FEVI documentada antes de iniciar ARPI cardiotóxico. "
                "Necesaria para detectar caída >10 puntos absolutos durante "
                "seguimiento (gate 18 pivotal_contraindication_gates - "
                "apalutamida). Si <50% absoluto, contraindica apalutamida."
            ),
        ),
        # Faubot 2026-04-25 (XIV) — Gate 19 ARSI × deterioro cognitivo.
        # FieldSpecs cognitivos: CTCAE grade + MMSE/MoCA basal + actual.
        # Todos clinical_role="decision_refiner" para ser consumidos por el
        # gate 19 (`arsi_in_cognitive_decline_grade2`) y futuro gate 20
        # (falls history). UCSF cohort 2024 + post-marketing surveillance
        # Xtandi documentaron aceleración de deterioro cognitivo en >80a
        # con enzalutamida.
        FieldSpec(
            "cognitive_disturbance_ctcae_grade",
            "Alteración cognitiva CTCAE v5 (grado)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="grado 0-5",
            evidence_tags=["ctcae_v5", "siog_geriatric_oncology", "ucsf_cohort_2024"],
            min_value=0,
            max_value=5,
            help_text=(
                "Alteración cognitiva CTCAE v5: 0=ninguna, 1=mild (no afecta "
                "ADL), 2=moderate (afecta ADL instrumentales), 3=severe "
                "(afecta ADL básicas), 4=life-threatening, 5=muerte. "
                "Grado ≥2 contraindica enzalutamida/apalutamida (gate 19)."
            ),
        ),
        FieldSpec(
            "mmse_baseline",
            "MMSE basal (Mini-Mental State Examination)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="puntos 0-30",
            evidence_tags=["mmse", "siog_geriatric_oncology"],
            min_value=0,
            max_value=30,
            help_text=(
                "MMSE basal ANTES de iniciar ARSI. Necesario para detectar "
                "caída ≥2 puntos durante seguimiento con enzalutamida/apalutamida "
                "(gate 19). Score normal: ≥24; deterioro leve: 18-23; moderado: "
                "10-17; severo: <10."
            ),
        ),
        FieldSpec(
            "mmse_current",
            "MMSE actual (seguimiento bajo ARSI)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="puntos 0-30",
            evidence_tags=["mmse", "siog_geriatric_oncology"],
            min_value=0,
            max_value=30,
            help_text=(
                "MMSE actual en seguimiento (3-6 meses post-inicio ARSI). "
                "Si MMSE_baseline - MMSE_current ≥ 2 → gate 19 dispara "
                "contraindicación de enzalutamida/apalutamida."
            ),
        ),
        FieldSpec(
            "moca_baseline",
            "MoCA basal (Montreal Cognitive Assessment)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="puntos 0-30",
            evidence_tags=["moca", "siog_geriatric_oncology"],
            min_value=0,
            max_value=30,
            help_text=(
                "MoCA basal pre-ARSI (alternativa a MMSE, más sensible para "
                "deterioro leve). Score normal ≥26."
            ),
        ),
        FieldSpec(
            "moca_current",
            "MoCA actual (seguimiento bajo ARSI)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="puntos 0-30",
            evidence_tags=["moca", "siog_geriatric_oncology"],
            min_value=0,
            max_value=30,
            help_text=(
                "MoCA actual en seguimiento. Si MoCA_baseline - MoCA_current ≥ 2 "
                "→ gate 19 dispara."
            ),
        ),
        FieldSpec(
            "cognitive_recovered_for_arpi",
            "Función cognitiva recuperada (override gate 19)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["siog_geriatric_oncology", "ucsf_cohort_2024"],
            help_text=(
                "Override del gate 19 (`arsi_in_cognitive_decline_grade2`). "
                "Marcar como 'Sí' SOLO si tras suspender ARSI temporalmente, "
                "el MMSE/MoCA volvieron a línea basal y se considera reintroducir "
                "el ARSI con monitoreo neurológico estrecho. Requiere documentación "
                "neurológica formal."
            ),
        ),
        FieldSpec(
            "troponin_baseline",
            "Troponina basal (hs-cTn)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ng/L",
            evidence_tags=["cardio_oncology"],
        ),
        FieldSpec(
            "nt_probnp",
            "NT-proBNP basal",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="pg/mL",
            evidence_tags=["cardio_oncology"],
        ),
        FieldSpec(
            "heart_failure_history",
            "Antecedente de insuficiencia cardíaca",
            "select",
            options=["0", "1"],
            default="0",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["cardio_oncology"],
        ),
        # EPIC 9 Group A (GAP-3): NYHA funcional explícito para bloqueo ARPI
        # (COU-AA-302 excluyó NYHA III/IV; FDA Zytiga §5.1; ENZAMET §5.4 cardiac).
        FieldSpec(
            "nyha_class",
            "Clase funcional NYHA",
            "select",
            options=["none", "I", "II", "III", "IV"],
            default="none",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["cardio_oncology", "nyha"],
        ),
    ]


def advanced_bone_turnover_fields(
    *,
    group: str = "Salud ósea",
    group_order: int = 5,
) -> list[FieldSpec]:
    """Biomarcadores de remodelado óseo y DEXA estructurado.

    Referencia: IOF/ASBMR 2023; NCCN Bone Health in cancer.
    """
    return [
        FieldSpec(
            "dexa_spine_tscore",
            "DEXA T-score columna",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="T-score",
            evidence_tags=["osteoporosis"],
        ),
        FieldSpec(
            "dexa_hip_tscore",
            "DEXA T-score cadera",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="T-score",
            evidence_tags=["osteoporosis"],
        ),
        FieldSpec(
            "dexa_date",
            "Fecha del DEXA",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["osteoporosis"],
        ),
        FieldSpec(
            "p1np_ng_ml",
            "P1NP (formación ósea)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ng/mL",
            evidence_tags=["bone_turnover"],
        ),
        FieldSpec(
            "ctx_ng_ml",
            "CTX / β-CrossLaps (resorción)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ng/mL",
            evidence_tags=["bone_turnover"],
        ),
        FieldSpec(
            "vitamin_d_25oh",
            "25-OH Vitamina D",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="ng/mL",
            evidence_tags=["bone_health"],
        ),
        FieldSpec(
            "ionized_calcium",
            "Calcio iónico",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="mg/dL",
            evidence_tags=["bone_health"],
        ),
        FieldSpec(
            "frax_major_10y",
            "FRAX® riesgo fractura mayor 10a",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="%",
            evidence_tags=["frax", "osteoporosis"],
        ),
    ]


def advanced_mental_health_fields(
    *,
    group: str = "Salud mental y apoyo",
    group_order: int = 7,
) -> list[FieldSpec]:
    """PHQ-9, GAD-7 y HADS estructurados para detección longitudinal.

    Referencia: Kroenke 2001 (PHQ-9); Spitzer 2006 (GAD-7); Zigmond 1983 (HADS).
    """
    return [
        FieldSpec(
            "phq9_score",
            "PHQ-9 (depresión, 0-27)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-27",
            evidence_tags=["depression", "phq9"],
        ),
        FieldSpec(
            "gad7_score",
            "GAD-7 (ansiedad, 0-21)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-21",
            evidence_tags=["anxiety", "gad7"],
        ),
        FieldSpec(
            "hads_depression",
            "HADS depresión (0-21)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="optional",
            unit="0-21",
            evidence_tags=["depression", "hads"],
        ),
        FieldSpec(
            "hads_anxiety",
            "HADS ansiedad (0-21)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="optional",
            unit="0-21",
            evidence_tags=["anxiety", "hads"],
        ),
        FieldSpec(
            "distress_thermometer",
            "Termómetro de distress (NCCN 0-10)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-10",
            evidence_tags=["distress"],
        ),
    ]


def advanced_function_longitudinal_fields(
    *,
    group: str = "Funcionalidad longitudinal",
    group_order: int = 8,
) -> list[FieldSpec]:
    """IIEF-5, IPSS y EPIC-26 longitudinales post-tratamiento local.

    Referencia: Rosen 1999 (IIEF-5); Barry 1992 (IPSS-AUA); Wei 2000 (EPIC-26).
    """
    return [
        FieldSpec(
            "iief5_score",
            "IIEF-5 (función eréctil, 1-25)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="1-25",
            evidence_tags=["sexual_function", "iief5"],
        ),
        FieldSpec(
            "ipss_score",
            "IPSS (síntomas urinarios, 0-35)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-35",
            evidence_tags=["luts", "ipss"],
        ),
        FieldSpec(
            "ipss_qol",
            "IPSS-QoL (0-6)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-6",
            evidence_tags=["luts", "ipss"],
        ),
        FieldSpec(
            "epic26_urinary_incontinence",
            "EPIC-26 incontinencia urinaria",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-100",
            evidence_tags=["qol", "epic26"],
        ),
        FieldSpec(
            "epic26_urinary_irritative",
            "EPIC-26 irritación urinaria",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-100",
            evidence_tags=["qol", "epic26"],
        ),
        FieldSpec(
            "epic26_sexual",
            "EPIC-26 sexual",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-100",
            evidence_tags=["qol", "epic26"],
        ),
        FieldSpec(
            "epic26_bowel",
            "EPIC-26 intestinal",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-100",
            evidence_tags=["qol", "epic26"],
        ),
        FieldSpec(
            "epic26_hormonal",
            "EPIC-26 hormonal",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-100",
            evidence_tags=["qol", "epic26"],
        ),
        FieldSpec(
            "bpi_worst_pain",
            "BPI worst pain 24h",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-10",
            evidence_tags=["pain", "bpi"],
        ),
        FieldSpec(
            "bpi_interference",
            "BPI interferencia funcional",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-10",
            evidence_tags=["pain", "bpi"],
        ),
        FieldSpec(
            "fact_p_total",
            "FACT-P total",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            unit="0-156",
            evidence_tags=["qol", "fact_p"],
        ),
    ]


def advanced_io_safety_fields(
    *,
    group: str = "Seguridad inmunoterapia",
    group_order: int = 60,
) -> list[FieldSpec]:
    """Contraindicaciones para inmunoterapias y checkpoint inhibitors.

    Aplica a sipuleucel-T (IMPACT), atezolizumab (CONTACT-02), pembrolizumab
    (KEYNOTE-158/199). Captura enfermedad autoinmune activa, inmunosupresión
    sistémica y EII activa (también relevante para RT pélvica en RADICALS-RT).
    """
    return [
        FieldSpec(
            "active_autoimmune_disease",
            "Enfermedad autoinmune activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["contact02", "keynote158", "keynote199", "atezolizumab_label"],
            help_text=(
                "Enfermedad autoinmune activa (lupus, AR, EII, psoriasis moderada-severa) "
                "que requiere o podría requerir inmunosupresión sistémica. "
                "Contraindicación relativa para inhibidores de punto de control "
                "(atezolizumab en CONTACT-02, pembrolizumab en KEYNOTE-199)."
            ),
        ),
        FieldSpec(
            "autoimmune_disease_name",
            "Enfermedad autoinmune — nombre específico",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="optional",
            evidence_tags=["contact02", "keynote158"],
            conditional_visibility={"active_autoimmune_disease": ["Sí"]},
            help_text=(
                "Obligatorio cuando active_autoimmune_disease = Sí. "
                "Ej: artritis reumatoide, lupus, EII, Graves, psoriasis severa."
            ),
        ),
        FieldSpec(
            "active_immunosuppression",
            "Inmunosupresión activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["impact", "keynote158", "keynote199"],
            help_text=(
                "Corticoides prednisona ≥10 mg/día crónicos, inmunomoduladores, "
                "trasplantados sólidos. Contraindicación para sipuleucel-T (IMPACT) "
                "y checkpoint inhibitors."
            ),
        ),
        FieldSpec(
            "active_inflammatory_bowel_disease",
            "Enfermedad inflamatoria intestinal activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["radicals_rt", "contact02"],
            help_text=(
                "Enfermedad de Crohn o colitis ulcerosa activa. Contraindica "
                "radioterapia pélvica (RADICALS-RT) e inmunoterapia (CONTACT-02) "
                "por riesgo de exacerbación severa."
            ),
        ),
    ]


def advanced_neutropenia_fields(
    *,
    group: str = "Seguridad hematológica",
    group_order: int = 55,
) -> list[FieldSpec]:
    """Estado hematológico basal y contraindicaciones para quimioterapia.

    Relevante para docetaxel (CHAARTED, TAX-327, STAMPEDE, PEACE-1, ARASENS),
    cabazitaxel (CARD, TROPIC), niraparib (MAGNITUDE, AMPLITUDE) y olaparib
    (PROfound, PROpel).
    """
    return [
        FieldSpec(
            "anc_baseline",
            "Neutrófilos absolutos (basal)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="/µL",
            min_value=0,
            max_value=20000,
            allow_negative=False,
            evidence_tags=["tax_327", "tropic", "card", "chaarted"],
            help_text=(
                "Recuento absoluto de neutrófilos basal. <1500/µL = riesgo "
                "quimioterapia; <1000/µL considerar aplazar."
            ),
        ),
        FieldSpec(
            "severe_neutropenia_grade4",
            "Neutropenia severa (grado 4) activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["tax_327", "tropic", "card", "chaarted"],
            help_text=(
                "ANC <500/µL en curso. Contraindica docetaxel, cabazitaxel, "
                "niraparib, olaparib hasta recuperación (ANC >1000/µL)."
            ),
        ),
        FieldSpec(
            "febrile_neutropenia_history",
            "Neutropenia febril previa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="monitoring",
            evidence_tags=["chaarted", "tax_327"],
            help_text=(
                "Episodio previo de fiebre + ANC <500/µL. Considerar reducción "
                "de dosis o G-CSF profiláctico en siguiente ciclo."
            ),
        ),
    ]


def advanced_chemotherapy_fitness_fields(
    *,
    group: str = "Aptitud a quimioterapia",
    group_order: int = 52,
) -> list[FieldSpec]:
    """Aptitud clínica para docetaxel/cabazitaxel/taxanos.

    Canónico para CHAARTED/STAMPEDE/TAX-327/ARASENS/PEACE-1 (docetaxel) y
    CARD/TROPIC (cabazitaxel). Captura juicio clínico explícito (ECOG,
    comorbilidad, neuropatía, soporte social) que la heurística derivada
    (`clinical_scores.docetaxel_fitness`) no siempre refleja correctamente.
    Acepta alias boolean 1=Apto / 0=No apto para compatibilidad con perfiles
    insignia históricos.
    """
    return [
        FieldSpec(
            "docetaxel_fit",
            "Aptitud para docetaxel",
            "select",
            options=["Desconocido", "Apto (fit)", "Marginal", "No apto"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["chaarted", "stampede", "tax_327", "arasens", "peace1"],
            help_text=(
                "Valoración del clínico sobre si el paciente tolerará docetaxel "
                "(ECOG, comorbilidad cardíaca, neuropatía, hematología, soporte social). "
                "Canónico para CHAARTED/STAMPEDE/ARASENS/PEACE-1/TAX-327. "
                "Acepta alias boolean: 1='Apto (fit)', 0='No apto'."
            ),
        ),
        FieldSpec(
            "cabazitaxel_fit",
            "Aptitud para cabazitaxel",
            "select",
            options=["Desconocido", "Apto (fit)", "Marginal", "No apto"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["card", "tropic"],
            help_text=(
                "Valoración de tolerancia a cabazitaxel post-docetaxel (CARD/TROPIC). "
                "Generalmente mejor tolerado que docetaxel en pacientes frágiles."
            ),
        ),
        FieldSpec(
            "taxane_fitness",
            "Aptitud general a taxanos",
            "select",
            options=["Desconocido", "Apto", "No apto"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="optional",
            evidence_tags=["stampede"],
            help_text=(
                "Alias histórico — equivalente a docetaxel_fit. "
                "Se conserva para compatibilidad con perfiles insignia."
            ),
        ),
    ]


def advanced_staging_imaging_fields(
    *,
    group: str = "Estadificación M (extensión)",
    group_order: int = 25,
    psma_pet_done_role: str | None = None,
    bone_scan_done_role: str | None = None,
    cross_sectional_role: str | None = None,
    include_local_invasion: bool = False,
) -> list[FieldSpec]:
    """Captura imagenología de estadificación M obligatoria en HIGH/VERY-HIGH risk.

    NCCN PROS-2/PROS-3 v5.2026 (cat 1) + EAU 2026 §6.4.1-6.4.3.
    ProPSMA (Hofman 2020) → PSMA PET/CT preferente sobre imagen convencional.

    Si ``include_local_invasion`` se activa, añade FieldSpec para invasión
    rectal/vesical/fijación pélvica/SV extensa — usado por
    ``radical_prostatectomy_contraindicated`` (Gate B en cT4 / cT3b).
    """
    fields: list[FieldSpec] = [
        FieldSpec(
            "psma_pet_done",
            "PSMA PET/CT realizado",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=psma_pet_done_role or "",
            evidence_tags=["propsma_2020", "nccn_pros2", "eau_2026_6.4.2"],
            help_text=(
                "PSMA PET/CT realizado para estadificación M. ProPSMA (Hofman 2020) "
                "muestra sensibilidad 85% vs 38% para imagen convencional. NCCN cat 1 "
                "alternativa o complemento a GGO+TAC en riesgo alto/muy alto."
            ),
        ),
        FieldSpec(
            "psma_pet_result",
            "Resultado PSMA PET/CT",
            "select",
            options=[
                "Desconocido",
                "Negativo (M0)",
                "Positivo extra-prostático",
                "Positivo M1",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            evidence_tags=["propsma_2020"],
            help_text="Resultado integrado del PSMA PET/CT. PSMA-RADS ≥4 sugiere M1.",
            conditional_visibility={"psma_pet_done": ["Sí"]},
        ),
        FieldSpec(
            "psma_rads_score_staging",
            "PSMA-RADS score (estadificación)",
            "select",
            options=[
                "Desconocido",
                "1 (benigno)",
                "2 (probablemente benigno)",
                "3a/3b (equívoco)",
                "4 (probablemente maligno)",
                "5 (maligno)",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            evidence_tags=["psma_rads"],
            conditional_visibility={"psma_pet_done": ["Sí"]},
        ),
        FieldSpec(
            "bone_scan_done",
            "Gammagrafía ósea (GGO) realizada",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=bone_scan_done_role or "",
            evidence_tags=["nccn_pros2", "eau_2026_6.4.1"],
            help_text=(
                "Gammagrafía ósea Tc-99m (GGO). NCCN cat 1 en riesgo alto/muy "
                "alto si no hay PSMA PET/CT disponible."
            ),
        ),
        FieldSpec(
            "bone_scan_result",
            "Resultado gammagrafía ósea",
            "select",
            options=[
                "Desconocido",
                "Negativo (M0)",
                "Lesiones equívocas",
                "Positivo M1 óseo",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            conditional_visibility={"bone_scan_done": ["Sí"]},
        ),
        FieldSpec(
            "ct_abdomen_pelvis_done",
            "TAC abdomino-pélvico con contraste realizado",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=cross_sectional_role or "",
            evidence_tags=["nccn_pros2", "eau_2026_6.4.3"],
        ),
        FieldSpec(
            "ct_abdomen_pelvis_result",
            "Resultado TAC abdomino-pélvico",
            "select",
            options=[
                "Desconocido",
                "Negativo",
                "Adenopatías sospechosas",
                "Visceral M1",
                "Equívoco",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            conditional_visibility={"ct_abdomen_pelvis_done": ["Sí"]},
        ),
        FieldSpec(
            "mri_abdomen_pelvis_done",
            "RM abdomino-pélvica realizada",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            evidence_tags=["nccn_pros2"],
        ),
        FieldSpec(
            "mri_abdomen_pelvis_result",
            "Resultado RM abdomino-pélvica",
            "select",
            options=[
                "Desconocido",
                "Negativo",
                "Adenopatías sospechosas",
                "Visceral M1",
                "Equívoco",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            conditional_visibility={"mri_abdomen_pelvis_done": ["Sí"]},
        ),
        FieldSpec(
            "imaging_negative_metastases",
            "Estadificación completa M0 confirmada",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            evidence_tags=["nccn_pros2", "eau_2026_6.4"],
            help_text=(
                "Confirma que la estadificación completa (PSMA PET/CT o "
                "GGO + TAC/RM) descartó enfermedad metastásica. Requerido "
                "para indicar tratamiento curativo en riesgo alto/muy alto."
            ),
        ),
        FieldSpec(
            "staging_imaging_date",
            "Fecha de imagenología de estadificación",
            "date",
            group=group,
            group_order=group_order,
        ),
    ]
    if include_local_invasion:
        local_group = "Invasión local extensa"
        fields.extend(
            [
                FieldSpec(
                    "rectal_invasion",
                    "Invasión rectal documentada",
                    "select",
                    options=["Desconocido", "No", "Sí"],
                    default="Desconocido",
                    group=local_group,
                    group_order=group_order + 1,
                    evidence_tags=["nccn_pros3", "eau_2026_6.5.1"],
                    help_text=(
                        "Invasión rectal documentada por tacto, RM o TAC. "
                        "Contraindica prostatectomía radical (NCCN PROS-3 / EAU §6.5.1)."
                    ),
                ),
                FieldSpec(
                    "bladder_invasion",
                    "Invasión vesical documentada",
                    "select",
                    options=["Desconocido", "No", "Sí"],
                    default="Desconocido",
                    group=local_group,
                    group_order=group_order + 1,
                    evidence_tags=["nccn_pros3", "eau_2026_6.5.1"],
                    help_text=(
                        "Invasión del cuello vesical o trígono. Contraindica RP "
                        "salvo casos altamente seleccionados en centros expertos."
                    ),
                ),
                FieldSpec(
                    "pelvic_fixation",
                    "Fijación pélvica clínica",
                    "select",
                    options=["Desconocido", "No", "Sí"],
                    default="Desconocido",
                    group=local_group,
                    group_order=group_order + 1,
                    evidence_tags=["nccn_pros3"],
                    help_text=(
                        "Tumor fijo a pared pélvica o elevadores en exploración. "
                        "Contraindicación absoluta de RP (cT4)."
                    ),
                ),
                FieldSpec(
                    "extensive_seminal_vesicle_invasion",
                    "Invasión extensa de vesículas seminales",
                    "select",
                    options=["Desconocido", "No", "Sí"],
                    default="Desconocido",
                    group=local_group,
                    group_order=group_order + 1,
                    evidence_tags=["nccn_pros3"],
                    help_text=(
                        "cT3b con invasión bilateral o extensa de vesículas "
                        "seminales. Contraindicación relativa de RP — preferir "
                        "EBRT + ADT 2-3 años."
                    ),
                ),
            ]
        )
    return fields


# ── Triaje pre-biopsia: emergencias oncológicas + diagnóstico provisional ──
# Brecha clínica 2026-04-23: paciente con APE 5000 + cT4 fijo+pétreo sin BTR.
# NCCN PROS-G v5.2026 + EAU 2026 §6.5.4 + Loblaw ASCO 2012 + Briganti 2012.

def oncologic_emergency_fields(
    *,
    group: str = "Triaje de emergencia oncológica",
    group_order: int = 4,
    role: str | None = "decision_refiner",
) -> list[FieldSpec]:
    """11 FieldSpecs de cribado de emergencias oncológicas.

    NCCN Oncologic Emergencies v3.2026; Loblaw ASCO 2012; ASCO/AUA Bone
    Health 2024; EAU 2026 §6.5.5.

    Reusable desde diagnostic_workup, localized_initial, mcspc_*, m1_crpc,
    palliative_pathway, recurrence_bcr.
    """
    role_value = role or ""
    return [
        FieldSpec(
            "spinal_cord_compression",
            "Sospecha de compresión medular",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loblaw_2012", "nccn_oncologic_emergencies"],
            help_text=(
                "Debilidad MMII + dolor dorso-lumbar + retención urinaria/fecal. "
                "Requiere RM urgente <24h, dexametasona 16 mg IV + RT/cirugía urgente."
            ),
        ),
        FieldSpec(
            "cord_compression_symptoms",
            "Síntomas neurológicos sugerentes",
            "select",
            options=[
                "Ninguno",
                "Debilidad MMII",
                "Anestesia en silla de montar",
                "Retención urinaria nueva",
                "Incontinencia fecal",
                "Dolor dorso-lumbar progresivo",
                "Hiperreflexia",
            ],
            default="Ninguno",
            group=group,
            group_order=group_order,
            evidence_tags=["loblaw_2012"],
        ),
        FieldSpec(
            "lower_limb_weakness",
            "Debilidad de miembros inferiores",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — leve",
                "Sí — moderada",
                "Sí — severa/paresia",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loblaw_2012"],
        ),
        FieldSpec(
            "acute_urinary_retention",
            "Retención urinaria aguda",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — sondaje requerido",
                "Sí — refractaria",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_oncologic_emergencies"],
        ),
        FieldSpec(
            "obstructive_uropathy_severity",
            "Uropatía obstructiva (hidronefrosis)",
            "select",
            options=[
                "Desconocido",
                "No",
                "Unilateral leve",
                "Unilateral severa",
                "Bilateral con IRA",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_oncologic_emergencies"],
            help_text=(
                "Bilateral con IRA → nefrostomía/JJ urgentes + ADT empírico."
            ),
        ),
        FieldSpec(
            "gross_hematuria_severity",
            "Hematuria macroscópica",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — sin coágulos",
                "Sí — con coágulos",
                "Sí — con retención por coágulos",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_oncologic_emergencies"],
        ),
        FieldSpec(
            "pathological_fracture_present",
            "Fractura patológica documentada",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — vertebral",
                "Sí — cuerpo largo (fémur/húmero)",
                "Sí — pelvis",
                "Sí — múltiples",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_aua_bone_health_2024"],
        ),
        FieldSpec(
            "hypercalcemia_present",
            "Hipercalcemia maligna",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — Ca 10.5-12",
                "Sí — Ca >12 sintomática",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_oncologic_emergencies"],
        ),
        FieldSpec(
            "bone_pain_severity",
            "Dolor óseo",
            "select",
            options=[
                "Desconocido",
                "Ninguno",
                "Leve (NRS 1-3)",
                "Moderado (NRS 4-6)",
                "Severo (NRS 7-10)",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_pain_ladder"],
        ),
        FieldSpec(
            "bowel_dysfunction",
            "Disfunción intestinal nueva",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — estreñimiento severo",
                "Sí — incontinencia fecal",
                "Sí — obstrucción",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loblaw_2012"],
        ),
        FieldSpec(
            "weight_loss_kg_3mo",
            "Pérdida de peso (kg, últimos 3 meses)",
            "number",
            default=0,
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="kg",
            evidence_tags=["nccn_oncologic_emergencies"],
        ),
    ]


def pre_biopsy_diagnostic_fields(
    *,
    group: str = "Estado pre-biopsia y características DRE",
    group_order: int = 3,
    role: str | None = "decision_refiner",
) -> list[FieldSpec]:
    """8 FieldSpecs para estratificar pacientes pre-biopsia con sospecha alta.

    Extiende dre_finding existente con detalles de consistencia/fijación
    requeridos para identificar cT4 fijo y elegir vía de biopsia adecuada.
    NCCN PROS-1 v5.2026 + EAU 2026 §6.5.4.
    """
    role_value = role or ""
    return [
        FieldSpec(
            "dre_prostate_consistency",
            "Consistencia al tacto rectal",
            "select",
            options=[
                "No evaluable",
                "Blanda elástica",
                "Firme nodular",
                "Pétrea / dura",
                "Pétrea con nódulos múltiples",
            ],
            default="No evaluable",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eau_2026_dre"],
            help_text="Pétrea = sospecha alta de neoplasia avanzada.",
        ),
        FieldSpec(
            "dre_fixation",
            "Fijación a estructuras adyacentes",
            "select",
            options=[
                "No evaluable",
                "Móvil",
                "Móvil con limitación",
                "Fija a pared rectal",
                "Fija a pared pélvica/sacro",
            ],
            default="No evaluable",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eau_2026_dre", "nccn_pros1"],
            help_text=(
                "Fija = cT4 clínico, contraindicación relativa de biopsia transrectal."
            ),
        ),
        FieldSpec(
            "dre_module_size_cm",
            "Tamaño del módulo dominante (cm)",
            "number",
            default=0,
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            unit="cm",
        ),
        FieldSpec(
            "dre_extracapsular_extension_clinical",
            "Extensión extracapsular clínica",
            "select",
            options=["No evaluable", "No", "Sospechosa", "Definitiva"],
            default="No evaluable",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eau_2026_dre"],
        ),
        FieldSpec(
            "clinical_tstage_dre_estimate",
            "Estadio T clínico estimado por DRE",
            "select",
            options=[
                "No estadificable",
                "T1c",
                "T2a",
                "T2b",
                "T2c",
                "T3a",
                "T3b",
                "T4 - vesical",
                "T4 - rectal",
                "T4 - elevadores/pared pélvica",
                "T4 - sacro",
            ],
            default="No estadificable",
            group=group,
            group_order=group_order,
            clinical_role="required",
            evidence_tags=["nccn_pros1", "eau_2026_dre"],
        ),
        FieldSpec(
            "biopsy_status",
            "Estado de biopsia prostática",
            "select",
            options=[
                "No realizada",
                "Programada",
                "En proceso",
                "Realizada — pendiente resultado",
                "Realizada — confirma cáncer",
                "Realizada — benigna",
                "Contraindicada",
            ],
            default="No realizada",
            group=group,
            group_order=group_order,
            clinical_role="required",
            evidence_tags=["nccn_pros1"],
        ),
        FieldSpec(
            "biopsy_contraindicated_reason",
            "Motivo de contraindicación de biopsia",
            "select",
            options=[
                "No aplica",
                "Próstata fija inaccesible",
                "Coagulopatía severa",
                "Sepsis activa",
                "Comorbilidad descompensada",
                "Preferencia del paciente",
                "Vía transrectal contraindicada — derivar transperineal",
            ],
            default="No aplica",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["nccn_pros1"],
        ),
        FieldSpec(
            "biopsy_planned_date",
            "Fecha planificada de biopsia",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
        ),
    ]


def provisional_diagnosis_fields(
    *,
    group: str = "Diagnóstico provisional clínico",
    group_order: int = 6,
) -> list[FieldSpec]:
    """4 FieldSpecs para declarar diagnóstico provisional pre-histología.

    NCCN PROS-G v5.2026 + EAU 2026 §6.5.4 + Briganti / ProsTIC nomograms.

    Permite activar workflows downstream (mHSPC empírico, palliative,
    emergencies) sin contaminar `known_cancer_diagnosis` (reservado para
    confirmación histológica).
    """
    return [
        FieldSpec(
            "provisional_diagnosis_assumed",
            "Diagnóstico provisional clínico asumido",
            "select",
            options=[
                "No",
                "Adenocarcinoma de próstata clínicamente probable",
                "Adenocarcinoma de próstata altamente probable",
                "Adenocarcinoma de próstata virtualmente cierto",
            ],
            default="No",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["nccn_pros_g", "eau_2026_6_5_4", "briganti_nomogram"],
            help_text=(
                "Permite activar workflows clínicos sin biopsia confirmatoria. "
                "NCCN PROS-G v5.2026: APE>100+cT3b-T4+síntomas justifica diagnóstico provisional."
            ),
        ),
        FieldSpec(
            "provisional_diagnosis_basis",
            "Fundamento del diagnóstico provisional",
            "select",
            options=[
                "No aplica",
                "APE >100 ng/mL",
                "APE >500 ng/mL",
                "APE >1000 ng/mL",
                "DRE cT3b-T4 fijo+pétreo",
                "Lesión metastásica biopsada (no prostática)",
                "PSMA PET/CT con captación intensa multifocal",
                "Síntomas óseos + APE elevado",
                "Emergencia oncológica activa",
            ],
            default="No aplica",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["nccn_pros_g", "briganti_nomogram"],
        ),
        FieldSpec(
            "empiric_adt_initiated",
            "ADT empírico iniciado pre-biopsia",
            "select",
            options=[
                "Desconocido",
                "No",
                "Sí — agonista LHRH + flare protection",
                "Sí — antagonista LHRH (degarelix)",
                "Sí — ARPI agregado",
            ],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
            evidence_tags=["nccn_pros_g", "stampede_2017"],
        ),
        FieldSpec(
            "empiric_adt_start_date",
            "Fecha de inicio de ADT empírico",
            "date",
            group=group,
            group_order=group_order,
            clinical_role="decision_refiner",
        ),
    ]


# ── FAUBOT auditoría 2026-04-23 — Pivotal contraindication fields ────────
# Power los 10 gates de `prostanet/shared/pivotal_contraindication_gates.py`
# unificando la convención ES-médica `["Desconocido", "No", "Sí"]` cuando
# corresponde. Reusable desde mcspc_*, m1_crpc, m0_crpc, recurrence_bcr,
# post_*, palliative_pathway.


def pivotal_contraindication_fields(
    *,
    group: str = "Contraindicaciones de ensayos pivote",
    group_order: int = 80,
    role: str | None = "decision_refiner",
) -> list[FieldSpec]:
    """7 FieldSpecs de contraindicaciones documentadas en ensayos pivote.

    Cubre las brechas detectadas por la auditoría FAUBOT 2026-04-23 sobre los
    36 estudios insignia (RADICALS-RT … CONTACT-02). Los campos
    `nyha_class`, `peripheral_neuropathy_grade`, `polysorbate_hypersensitivity`
    y `diabetes_uncontrolled` ya viven en otros helpers y se respetan como
    canónicos; este helper sólo introduce las señales aún huérfanas.

    Referencias:
      - ARANOTE: Saad Lancet Oncol 2024;25:1422
      - LATITUDE / PEACE-1 / COU-AA-301/302 / CONTACT-02: protocolos
      - IPATential150: Sweeney Lancet 2021;398:131
      - ERA-223: Smith Lancet Oncol 2019;20:408
      - PEACE-3: Tombal ESMO 2024
      - TRITON-3: Fizazi NEJM 2023;388:719
    """
    role_value = role or ""
    return [
        FieldSpec(
            "prior_arpi_exposure_mhspc",
            "Exposición previa a ARPI antes de mHSPC",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aranote_saad_2024"],
            help_text=(
                "ARANOTE excluyó pacientes con enzalutamida/abiraterona/apalutamida/"
                "darolutamida en contexto previo. Determina si darolutamida monoterapia "
                "mHSPC sigue siendo opción o se requiere otra intensificación."
            ),
        ),
        FieldSpec(
            "darolutamide_hypersensitivity",
            "Hipersensibilidad documentada a darolutamida",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aramis_arasens_aranote_label"],
            help_text=(
                "Reacción de hipersensibilidad documentada al fármaco. Bloquea "
                "darolutamida en mHSPC (ARANOTE/ARASENS) y nmCRPC (ARAMIS); "
                "considerar enzalutamida o apalutamida."
            ),
        ),
        FieldSpec(
            "uncontrolled_hypertension",
            "Hipertensión arterial no controlada",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["latitude_peace1_couaa_contact02"],
            help_text=(
                "PA sostenida >160/100 mmHg pese a tratamiento. Bloquea abiraterona "
                "(exceso mineralocorticoide) y cabozantinib (inhibición VEGFR). "
                "Estabilizar <140/90 antes de iniciar."
            ),
        ),
        FieldSpec(
            "severe_heart_failure_nyha_iii_iv",
            "Insuficiencia cardíaca NYHA III-IV",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["latitude_couaa301_couaa302"],
            help_text=(
                "Atajo booleano para NYHA III-IV (alternativa a `nyha_class`). "
                "LATITUDE / PEACE-1 / COU-AA-301/302 excluyeron NYHA III-IV por "
                "retención hidrosalina inducida por abiraterona."
            ),
        ),
        FieldSpec(
            "uncontrolled_diabetes",
            "Diabetes mellitus no controlada",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150"],
            help_text=(
                "HbA1c >8% o glicemias en ayuno >200 mg/dL persistentes. Bloquea "
                "ipatasertib (inhibición AKT empeora hiperglucemia). Optimizar control "
                "glicémico antes de iniciar (IPATential150)."
            ),
        ),
        FieldSpec(
            "no_bone_protective_agent",
            "Sin agente protector óseo concomitante (Ra-223)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["smith_era223_2019_peace3_2024"],
            help_text=(
                "ERA-223 demostró exceso de fracturas con Ra-223 + abiraterona sin "
                "denosumab/zoledronato (28% vs 12%). PEACE-3 hizo obligatorio "
                "bisfosfonato/denosumab. Marcar 'Sí' si Ra-223 está bajo consideración "
                "y NO hay agente óseo activo."
            ),
        ),
        FieldSpec(
            "radium223_candidate",
            "Radio-223 bajo consideración",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["alsympca_peace3"],
            help_text=(
                "Activa el gate de protección ósea: si se considera Ra-223 sin "
                "agente óseo declarado, el sistema bloquea la opción y emite la "
                "alerta clínica (ALSYMPCA / PEACE-3)."
            ),
        ),
    ]


# ──────────────────────────────────────────────────────────────────────
# Faubot 2026-04-25 (XX) — pivotal_gate_supporting_fields
# Cierre de la dimensión DATOS al 100% del scorecard CDE Auditable.
# Declara los 23 FieldSpecs faltantes que los gates pivotal usaban como
# alias/triggers/overrides pero no estaban formalizados.
# ──────────────────────────────────────────────────────────────────────


def pivotal_gate_supporting_fields(
    *,
    group: str = "Soportes adicionales de gates pivote",
    group_order: int = 81,
    role: str | None = "decision_refiner",
) -> list[FieldSpec]:
    """23 FieldSpecs de soporte para los 19 gates pivotal centralizados.

    Cubre las brechas detectadas por la auditoría FAUBOT 2026-04-25 (XX)
    cierre del scorecard CDE Auditable a 5/5 dimensiones en 100%.
    Los campos están agrupados por gate origen:

      - Gate 9 (no_bone_protective_agent): 6 fields (alias + agentes óseos)
      - Gates 11/13 (cord compression): 2 fields (override + alias)
      - Gate 12 (hypocalcemia): 5 fields (flag + 3 calcium types + override)
      - Gates 14/15 (cytopenias): 5 fields (flags + alias + 2 overrides)
      - Gate 16 (mds_aml history): 3 fields (flag + 2 alias)
      - Gates 17/18 (ARPI cardiotox): 4 fields (qtc/lvef + 3 overrides)
      = 25 fields total (alias `qtc_baseline_ms`, `hb`, `serum_calcium` no
        son "field" formales pero se incluyen como alias documentados).

    Aporte a auditabilidad (DATOS):
      - Schema completo del input declarativo
      - Validación de tipos al input
      - UI generation consistente
      - Métricas de captura por field más precisas
    """
    role_value = role or ""

    return [
        # ── Gate 9 — no_bone_protective_agent ─────────────────────────
        FieldSpec(
            "considering_radium223",
            "Ra-223 en consideración (alias)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Alias para `radium223_candidate`. Activa el gate 9 si no hay "
                "agente óseo declarado."
            ),
        ),
        FieldSpec(
            "planned_systemic_regimen",
            "Régimen sistémico planeado (código canónico)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Código canónico del régimen planeado (e.g., RADIUM_223, "
                "ADT_DOCETAXEL, ADT_ABIRATERONE). Si ∈ {RADIUM_223, RA_223, "
                "RADIUM223}, dispara gate 9 ante ausencia de agente óseo."
            ),
        ),
        FieldSpec(
            "bone_modifying_agent",
            "Agente óseo activo (denosumab/zoledronato/ninguno)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Texto libre con el agente óseo en uso. Tokens negativos "
                "reconocidos: `ninguno`, `none`, `no` (gate 9 activa con "
                "estos valores). Cualquier otro valor (e.g., 'denosumab', "
                "'zoledronato', 'ácido zoledrónico') desactiva el gate."
            ),
        ),
        FieldSpec(
            "denosumab_prophylaxis",
            "Profilaxis denosumab activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Marcar 'Sí' si el paciente recibe denosumab 120 mg SC c/4 sem. "
                "Desactiva gate 9 (agente protector óseo declarado)."
            ),
        ),
        FieldSpec(
            "zoledronate_prophylaxis",
            "Profilaxis ácido zoledrónico activa",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Marcar 'Sí' si el paciente recibe ácido zoledrónico 4 mg IV "
                "c/4 sem. Desactiva gate 9."
            ),
        ),
        FieldSpec(
            "bone_protection_started",
            "Protección ósea iniciada (genérico)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223_peace3"],
            help_text=(
                "Flag genérico para indicar que ya se inició algún agente "
                "protector óseo (alternativo a `denosumab_prophylaxis` o "
                "`zoledronate_prophylaxis`). Desactiva gate 9."
            ),
        ),

        # ── Gates 11/13 — cord compression overrides + alias ──────────
        FieldSpec(
            "epidural_compression",
            "Compresión epidural (alias de spinal_cord_compression)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loblaw_2012", "vision_protocol"],
            help_text=(
                "Alias de `spinal_cord_compression` para cobertura terminológica. "
                "Activa gates 11 y 13 (Ra-223 y Lu-177 NO con compresión activa)."
            ),
        ),
        FieldSpec(
            "cord_compression_stabilized",
            "Compresión medular ya estabilizada (override)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loblaw_2012", "patchell_criteria"],
            help_text=(
                "Marcar 'Sí' SOLO tras estabilización estructural documentada "
                "(post-RT 30 Gy/10 fx + recuperación neurológica O cirugía "
                "descompresiva con criterios Patchell cumplidos). Desactiva "
                "gates 11 y 13 (override Ra-223/Lu-177)."
            ),
        ),

        # ── Gate 12 — hypocalcemia + 3 calcium types + override ───────
        FieldSpec(
            "hypocalcemia",
            "Hipocalcemia documentada (flag explícito)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xofigo_label_hypocalcemia"],
            help_text=(
                "Marcar 'Sí' si el clínico documenta hipocalcemia clínicamente "
                "relevante. Activa gate 12 (Ra-223 NO con hipocalcemia no "
                "corregida). Alternativa numérica: `corrected_calcium <8.5` o "
                "`ionized_calcium <4.5`."
            ),
        ),
        FieldSpec(
            "corrected_calcium",
            "Calcio sérico corregido por albúmina",
            "number",
            default=None,
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="mg/dL",
            evidence_tags=["xofigo_label_hypocalcemia"],
            help_text=(
                "Calcio total ajustado por albúmina (fórmula: Ca + 0.8×(4-alb)). "
                "Threshold gate 12: <8.5 mg/dL dispara hipocalcemia."
            ),
        ),
        FieldSpec(
            "calcium_level",
            "Calcio sérico (alias 'calcium_level')",
            "number",
            default=None,
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="mg/dL",
            evidence_tags=["xofigo_label_hypocalcemia"],
            help_text=(
                "Alias para `corrected_calcium` en payloads que no usan corrección "
                "por albúmina. Misma semántica para gate 12."
            ),
        ),
        FieldSpec(
            "serum_calcium",
            "Calcio sérico (alias 'serum_calcium')",
            "number",
            default=None,
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="mg/dL",
            evidence_tags=["xofigo_label_hypocalcemia"],
            help_text=(
                "Alias para `corrected_calcium`. Misma semántica para gate 12 "
                "(<8.5 mg/dL dispara hipocalcemia)."
            ),
        ),
        FieldSpec(
            "hypocalcemia_corrected",
            "Hipocalcemia corregida (override gate 12)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xofigo_label_hypocalcemia"],
            help_text=(
                "Marcar 'Sí' tras documentar corrección laboratorial: calcio "
                "total ≥8.5 mg/dL + iónico ≥4.5 mg/dL. Desactiva gate 12 y "
                "permite considerar Ra-223 nuevamente."
            ),
        ),

        # ── Gates 14/15 — cytopenias flags + alias + 2 overrides ──────
        FieldSpec(
            "platelets",
            "Plaquetas (recuento)",
            "number",
            default=None,
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="/µL",
            evidence_tags=["pluvicto_label", "lynparza_label"],
            help_text=(
                "Recuento de plaquetas. Threshold gate 14 Lu-177: <75 000/µL. "
                "Threshold gate 15 PARP (más estricto): <100 000/µL."
            ),
        ),
        FieldSpec(
            "severe_cytopenia_for_radioligand",
            "Citopenia severa para radioligando (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pluvicto_label_vision"],
            help_text=(
                "Flag explícito que activa gate 14 (Lu-177 con citopenias) sin "
                "necesidad de capturar valores numéricos individuales."
            ),
        ),
        FieldSpec(
            "severe_cytopenia_for_parp_inhibitor",
            "Citopenia severa para PARPi (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_magnitude_talapro_triton3_labels"],
            help_text=(
                "Flag explícito que activa gate 15 (PARPi con citopenias) sin "
                "necesidad de capturar ANC/plaquetas/Hb individuales."
            ),
        ),
        FieldSpec(
            "cytopenias_corrected_for_radioligand",
            "Citopenias corregidas para radioligando (override)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pluvicto_label_vision"],
            help_text=(
                "Marcar 'Sí' tras documentar recuperación laboratorial: "
                "ANC ≥1500, plaq ≥75 000, Hb ≥9. Desactiva gate 14 (Lu-177). "
                "NO desactiva gate 15 (PARPi tiene threshold más estricto)."
            ),
        ),
        FieldSpec(
            "cytopenias_corrected_for_parp_inhibitor",
            "Citopenias corregidas para PARPi (override)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_magnitude_talapro_triton3_labels"],
            help_text=(
                "Marcar 'Sí' tras documentar recuperación laboratorial: "
                "ANC ≥1500, plaq ≥100 000, Hb ≥9. Desactiva gate 15 (PARPi). "
                "Threshold de plaq más estricto que el override Lu-177."
            ),
        ),

        # ── Gate 16 — MDS/AML history + 2 alias ───────────────────────
        FieldSpec(
            "mds_aml_history",
            "Antecedente de SMD/LMA (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lynparza_akeega_talzenna_rubraca_labels"],
            help_text=(
                "Síndrome mielodisplásico o leucemia mieloide aguda. Boxed "
                "warning en TODOS los PARPi (Lynparza/Akeega/Talzenna/Rubraca "
                "§5.1). Sin override clínico — bloqueo absoluto del gate 16."
            ),
        ),
        FieldSpec(
            "prior_mds",
            "Antecedente SMD (alias)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lynparza_akeega_talzenna_rubraca_labels"],
            help_text="Alias para `mds_aml_history` cuando solo aplica SMD.",
        ),
        FieldSpec(
            "prior_aml",
            "Antecedente LMA (alias)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lynparza_akeega_talzenna_rubraca_labels"],
            help_text="Alias para `mds_aml_history` cuando solo aplica LMA.",
        ),

        # ── Gates 17/18 — ARPI cardiotox overrides ────────────────────
        FieldSpec(
            "qtc_corrected_for_arpi",
            "QTc corregido para ARPI (override gate 17)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label_qtc"],
            help_text=(
                "Marcar 'Sí' tras corrección de causas reversibles "
                "(hipokalemia, hipomagnesemia, suspender DDI cardio-tóxicos) "
                "y QTc <470 ms documentado. Desactiva gate 17 (enzalutamida)."
            ),
        ),
        FieldSpec(
            "lvef_decline_for_arpi",
            "Caída LVEF para ARPI (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label", "titan_spartan"],
            help_text=(
                "Flag explícito que activa gate 18 (apalutamida con caída "
                "LVEF) sin necesidad de capturar valores LVEF individuales."
            ),
        ),
        FieldSpec(
            "lvef_recovered_for_arpi",
            "LVEF recuperada para ARPI (override gate 18)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label", "asco_esc_2022"],
            help_text=(
                "Marcar 'Sí' tras optimización de IC (IECA + BB + diurético) y "
                "LVEF ≥50% documentado en eco/MUGA seguimiento. Desactiva "
                "gate 18 (apalutamida)."
            ),
        ),

        # ── Faubot 2026-04-25 (XXVI) — Tier 2/3 D-F gates 20-23 ───────
        # Gate 20 — ARSI seizure (3 fields + 1 override)
        FieldSpec(
            "seizure_ctcae_grade",
            "Convulsiones CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5 de convulsiones (0=ninguno, 1=convulsión "
                "única autolimitada, 2=tratamiento médico requerido, "
                "3=prolongadas/repetitivas con intervención urgente, "
                "4=status epilepticus, 5=muerte). Activa gate 20 si ≥3."
            ),
        ),
        FieldSpec(
            "active_seizure_disorder",
            "Trastorno convulsivo activo (epilepsia)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label", "erleada_label", "nubeqa_label"],
            help_text=(
                "Marcar 'Sí' si el paciente tiene historia de epilepsia "
                "activa, status epilepticus reciente, o convulsiones "
                "no controladas. Activa gate 20 (ARSI contraindicado)."
            ),
        ),
        FieldSpec(
            "seizure_history_grade3_documented",
            "Historia convulsiva grado ≥3 documentada (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label", "ctcae_v5"],
            help_text=(
                "Flag explícito si neurología documentó convulsiones "
                "grado ≥3 sin necesidad de capturar grado numérico. "
                "Activa gate 20 (ARSI contraindicado)."
            ),
        ),
        FieldSpec(
            "seizure_disorder_controlled_for_arpi",
            "Trastorno convulsivo controlado para ARPI (override gate 20)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label", "neurology_uptodate"],
            help_text=(
                "Marcar 'Sí' tras ≥6 meses libre de convulsiones + EEG "
                "normal + aval neurología. Desactiva gate 20."
            ),
        ),

        # Gate 21 — Abiraterone hepatotoxicity (5 fields + 1 override)
        FieldSpec(
            "ast_value",
            "AST sérico (IU/L) basal o seguimiento",
            "number",
            default="",
            unit="IU/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "ctcae_v5"],
            help_text=(
                "Valor AST sérico (IU/L). Threshold gate 21 = >200 (≈ "
                ">5× ULN típico 40 IU/L = grado 3 CTCAE v5). "
                "Aliases canónicos: ast_iu_l, ast_baseline, ast_serum, sgot."
            ),
        ),
        FieldSpec(
            "alt_value",
            "ALT sérico (IU/L) basal o seguimiento",
            "number",
            default="",
            unit="IU/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "ctcae_v5"],
            help_text=(
                "Valor ALT sérico (IU/L). Threshold gate 21 = >200 (≈ "
                ">5× ULN típico 40 IU/L = grado 3 CTCAE v5). "
                "Aliases canónicos: alt_iu_l, alt_baseline, alt_serum, sgpt."
            ),
        ),
        FieldSpec(
            "bilirubin_total_mg_dl",
            "Bilirrubina total sérica (mg/dL)",
            "number",
            default="",
            unit="mg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "ctcae_v5"],
            help_text=(
                "Valor bilirrubina total sérica (mg/dL). Threshold gate 21 "
                "= >3.0 (≈ >3× ULN típico 1.0 mg/dL). Activa gate 21 "
                "(contraindica abiraterona)."
            ),
        ),
        FieldSpec(
            "hepatotoxicity_ctcae_grade",
            "Hepatotoxicidad CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5 de hepatotoxicidad (0=ninguno, 1=AST/ALT "
                "1-3× ULN, 2=3-5× ULN, 3=5-20× ULN sintomática, "
                "4=>20× ULN o falla hepática, 5=muerte). "
                "Activa gate 21 si ≥3."
            ),
        ),
        FieldSpec(
            "hepatotoxicity_grade3_for_abiraterone",
            "Hepatotoxicidad grado 3 para abiraterona (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label"],
            help_text=(
                "Flag explícito si hepatólogo documentó hepatotoxicidad "
                "grado ≥3 sin necesidad de capturar AST/ALT/bilirrubina "
                "individuales. Activa gate 21."
            ),
        ),
        FieldSpec(
            "hepatic_function_recovered_for_abiraterone",
            "Función hepática recuperada para abiraterona (override gate 21)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label"],
            help_text=(
                "Marcar 'Sí' tras AST/ALT <2.5× ULN documentado + "
                "bilirrubina <1.5× ULN + ningún signo activo de "
                "hepatopatía. Desactiva gate 21."
            ),
        ),

        # Gate 22 — Niraparib thrombocytopenia (3 fields + 1 override)
        FieldSpec(
            "thrombocytopenia_ctcae_grade",
            "Trombocitopenia CTCAE v5 grado (0-4)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "magnitude", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5 de trombocitopenia (0=≥150K, 1=75K-150K, "
                "2=50K-75K, 3=25K-50K, 4=<25K). Activa gate 22 si ≥3 "
                "(específico niraparib, más estricto que gate 15)."
            ),
        ),
        FieldSpec(
            "thrombocytopenia_grade3_for_niraparib",
            "Trombocitopenia grado 3 para niraparib (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "magnitude"],
            help_text=(
                "Flag explícito si hematólogo documentó trombocitopenia "
                "grado ≥3 sin necesidad de capturar plaquetas numéricas. "
                "Activa gate 22 (más estricto que gate 15 PARPi general)."
            ),
        ),
        FieldSpec(
            "hemorrhage_ctcae_grade",
            "Hemorragia CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5 de hemorragia (0=ninguno, 1=mínimo sin "
                "intervención, 2=tratamiento médico, 3=transfusión + "
                "intervención urgente, 4=amenaza vida, 5=muerte). "
                "Activa gate 22 si ≥3 (sangrado activo + niraparib = "
                "contraindicación)."
            ),
        ),
        FieldSpec(
            "platelet_count_recovered_for_niraparib",
            "Plaquetas recuperadas para niraparib (override gate 22)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label"],
            help_text=(
                "Marcar 'Sí' tras plaquetas ≥150K documentadas + sin "
                "sangrado activo ≥7 días. Desactiva gate 22."
            ),
        ),

        # Gate 23 — Niraparib hypertension (4 fields + 1 override)
        FieldSpec(
            "systolic_blood_pressure",
            "Presión arterial sistólica (mmHg)",
            "number",
            default="",
            unit="mmHg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "magnitude", "ctcae_v5"],
            help_text=(
                "PA sistólica medida (mmHg). Threshold gate 23 = >179 "
                "(≥180 = grado 3 CTCAE v5 + Akeega §5.2 trigger). "
                "Aliases: sbp, systolic_bp, blood_pressure_systolic."
            ),
        ),
        FieldSpec(
            "diastolic_blood_pressure",
            "Presión arterial diastólica (mmHg)",
            "number",
            default="",
            unit="mmHg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "magnitude", "ctcae_v5"],
            help_text=(
                "PA diastólica medida (mmHg). Threshold gate 23 = >119 "
                "(≥120 = grado 3 CTCAE v5). Aliases: dbp, diastolic_bp, "
                "blood_pressure_diastolic."
            ),
        ),
        FieldSpec(
            "hypertension_ctcae_grade",
            "Hipertensión CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5 de hipertensión (0=normal, 1=PA elevada "
                "sin tratamiento, 2=tratamiento médico, 3=PA ≥160/100 "
                "sintomática o medidas urgentes, 4=crisis hipertensiva "
                "amenaza vida, 5=muerte). Activa gate 23 si ≥3."
            ),
        ),
        FieldSpec(
            "hypertension_grade3_for_niraparib",
            "Hipertensión grado 3 para niraparib (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "magnitude"],
            help_text=(
                "Flag explícito si cardiólogo/médico documentó HTA grado "
                "≥3 específica de niraparib (DAT inhibition) sin necesidad "
                "de capturar PA sistólica/diastólica. Activa gate 23."
            ),
        ),
        FieldSpec(
            "hypertension_controlled_for_niraparib",
            "Hipertensión controlada para niraparib (override gate 23)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["akeega_label", "esc_2018_htn"],
            help_text=(
                "Marcar 'Sí' tras optimización antihipertensiva con PA "
                "<140/90 sostenida ≥4 semanas documentada. Desactiva "
                "gate 23."
            ),
        ),

        # ── Faubot 2026-04-25 (XXVII) — Auditoría #39 gate 24 ─────────
        # Gate 24 — Docetaxel neuropathy longitudinal (3 fields + 1 override)
        FieldSpec(
            "docetaxel_cycles_received",
            "Ciclos de docetaxel completados (cuenta acumulada)",
            "number",
            default="",
            unit="ciclos",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["tax327", "tropic", "chaarted"],
            help_text=(
                "Número total de ciclos de docetaxel recibidos por el "
                "paciente (cuenta acumulada longitudinal). Threshold "
                "gate 24 = ≥4 ciclos AND neuropatía G≥2 → contraindica "
                "re-tratamiento taxane. Aliases canónicos: "
                "taxane_cycles_received, docetaxel_cycle_count, "
                "docetaxel_total_cycles."
            ),
        ),
        FieldSpec(
            "cumulative_neuropathy_documented",
            "Neuropatía acumulativa post-taxane documentada (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["tax327", "card", "ctcae_v5"],
            help_text=(
                "Flag explícito si oncología/neurología documentó "
                "neuropatía acumulativa post-taxane (G≥2 sintomática) "
                "sin necesidad de capturar grade + ciclos individuales. "
                "Activa gate 24."
            ),
        ),
        FieldSpec(
            "neuropathy_recovered_post_docetaxel",
            "Neuropatía recuperada post-docetaxel (override gate 24)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_cipn_2020", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' tras dose-hold + recuperación a CTCAE G≤1 "
                "documentada por neurología/oncología (típicamente ≥3 "
                "meses post-suspensión). Desactiva gate 24, permite "
                "re-rechallenge taxane bajo monitorización estrecha."
            ),
        ),

        # ── Faubot 2026-04-25 (XXXIII) — Auditoría #41 gate 25 ────────
        # Gate 25 — Ipatasertib hyperglycemia (4 fields + 1 override)
        FieldSpec(
            "glucose_fasting",
            "Glucosa en ayuno (mg/dL)",
            "number",
            default="",
            unit="mg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150", "ctcae_v5", "ada_2024"],
            help_text=(
                "Glucosa plasmática en ayuno (mg/dL, valor numérico). "
                "Threshold gate 25 = >250 (CTCAE v5 grado 3 + IPATential150 "
                "trigger para suspensión ipatasertib). Aliases canónicos: "
                "glucose_fasting_mg_dl, fasting_glucose, glucemia_ayuno."
            ),
        ),
        FieldSpec(
            "hba1c",
            "Hemoglobina glucosilada HbA1c (%)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150", "ada_2024"],
            help_text=(
                "HbA1c (% glucosilación, valor numérico). Threshold gate 25 "
                "= >10% (control crónico severamente comprometido + "
                "exclusion criterion IPATential150). Aliases: a1c, "
                "hba1c_percent, hemoglobina_glucosilada."
            ),
        ),
        FieldSpec(
            "hyperglycemia_ctcae_grade",
            "Hiperglucemia CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "ipatential150"],
            help_text=(
                "Grado CTCAE v5 de hiperglucemia (0=normal, 1=116-160 "
                "mg/dL, 2=161-250, 3=>250 sintomática o medidas urgentes, "
                "4=>500 o cetoacidosis, 5=muerte). Activa gate 25 si ≥3."
            ),
        ),
        FieldSpec(
            "hyperglycemia_grade3_for_ipatasertib",
            "Hiperglucemia grado ≥3 para ipatasertib (flag explícito)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150", "ctcae_v5"],
            help_text=(
                "Flag explícito si endocrinología/oncología documentó "
                "hiperglucemia G≥3 sin necesidad de capturar valores "
                "numéricos individuales. Activa gate 25 (contraindica "
                "ipatasertib)."
            ),
        ),
        FieldSpec(
            "hyperglycemia_controlled_for_ipatasertib",
            "Hiperglucemia controlada para ipatasertib (override gate 25)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150", "ada_2024"],
            help_text=(
                "Marcar 'Sí' tras optimización antidiabética con metformina "
                "± SGLT2i ± insulina, glucosa ayuno <180 mg/dL + HbA1c <8% "
                "sostenidos ≥4 semanas + sin episodios sintomáticos. "
                "Desactiva gate 25 (permite reintroducción ipatasertib)."
            ),
        ),

        # ── Faubot 2026-04-25 (XXXIV) — Auditoría #42 gate 26 ─────────
        # Gate 26 — Cabazitaxel hipersensibilidad (4 fields + 1 override)
        FieldSpec(
            "cabazitaxel_hypersensitivity_history",
            "Historia hipersensibilidad cabazitaxel previa (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["jevtana_label", "tropic", "card"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia documentada de "
                "reacción hipersensibilidad cabazitaxel previa. CONTRAINDICACIÓN "
                "ABSOLUTA per Jevtana §4. Activa gate 26."
            ),
        ),
        FieldSpec(
            "polysorbate_hypersensitivity_history",
            "Historia hipersensibilidad polysorbate-80 (Tween-80)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["jevtana_label"],
            help_text=(
                "Marcar 'Sí' si historia documentada de anaphylaxis o "
                "reacción severa a polysorbate-80 (Tween-80, diluyente "
                "cabazitaxel). CONTRAINDICACIÓN ABSOLUTA per Jevtana §4."
            ),
        ),
        FieldSpec(
            "hypersensitivity_ctcae_grade",
            "Hipersensibilidad CTCAE v5 grado (0-5)",
            "number",
            default="",
            unit="grado",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "tropic", "card"],
            help_text=(
                "Grado CTCAE v5 hipersensibilidad: G1 mild (rash, flushing), "
                "G2 moderate (broncoespasmo, requiere intervención), G3 severe "
                "(hipotensión, angioedema, requiere hospitalización), G4 anaphylaxis, "
                "G5 muerte. Activa gate 26 si ≥3."
            ),
        ),
        FieldSpec(
            "prior_taxane_anaphylaxis_documented",
            "Anaphylaxis previa a taxane (cross-reactivity ~30%)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["jevtana_label", "card"],
            help_text=(
                "Marcar 'Sí' si paciente tuvo anaphylaxis (G4) a docetaxel "
                "u otro taxane previamente. Cross-reactivity ~30% per CARD "
                "trial. Activa gate 26 (cabazitaxel)."
            ),
        ),
        FieldSpec(
            "hypersensitivity_grade1_only_premedicated",
            "Hipersensibilidad G1 mild + premedication completa (override gate 26)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["jevtana_label", "asco_2021"],
            help_text=(
                "Marcar 'Sí' SOLO si reacción previa fue G1 mild (rash + "
                "flushing sin compromiso cardio-respiratorio) + premedication "
                "completa pre-infusión documentada (dexametasona 8mg + "
                "ranitidina 50mg + difenhidramina 25mg IV) + hospital "
                "observation primer ciclo + sin polysorbate-80 anaphylaxis "
                "history. NO override para G≥3 anaphylaxis (contraindicación "
                "absoluta Jevtana §4)."
            ),
        ),

        # ── Auditoría #42 gate 27 — Ra-223 + FRAX ──────────────────────
        # Gate 27 — Radium-223 high fracture risk (5 fields + 1 override)
        FieldSpec(
            "frax_10yr_major_fracture_risk",
            "FRAX 10-year major osteoporotic fracture risk (% MOF)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_frax_2008", "nof_2022", "era223"],
            help_text=(
                "FRAX 10-year probability of major osteoporotic fracture "
                "(spine, hip, wrist, humerus). Calculado en "
                "https://www.sheffield.ac.uk/FRAX. Threshold gate 27 = >20% "
                "(NOF/WHO high fracture risk threshold). Activa gate 27 "
                "(Ra-223 requiere bone protection establecida)."
            ),
        ),
        FieldSpec(
            "frax_10yr_hip_fracture_risk",
            "FRAX 10-year hip fracture risk (% Hip)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_frax_2008", "nof_2022"],
            help_text=(
                "FRAX 10-year probability of hip fracture específicamente. "
                "Threshold gate 27 = >3% (NOF high hip fracture risk). "
                "Activa gate 27 (Ra-223 + osteoporosis severa)."
            ),
        ),
        FieldSpec(
            "dxa_t_score_lumbar",
            "DXA T-score lumbar spine",
            "number",
            default="",
            unit="DS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_dxa", "nof_2022"],
            help_text=(
                "T-score DXA columna lumbar (L1-L4). T-score = (BMD paciente - "
                "BMD adulto joven referencia) / DS. Threshold WHO osteoporosis "
                "= <-2.5 DS (gate 27 activa). Osteopenia: -2.5 a -1.0; "
                "Normal: >-1.0. Aliases: dxa_lumbar_t_score, "
                "bmd_t_score_lumbar_spine."
            ),
        ),
        FieldSpec(
            "dxa_t_score_femoral_neck",
            "DXA T-score femoral neck",
            "number",
            default="",
            unit="DS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_dxa", "nof_2022"],
            help_text=(
                "T-score DXA cuello femoral. Threshold WHO osteoporosis = "
                "<-2.5 DS (gate 27 activa). Sitio crítico para fracture "
                "hip risk assessment. Aliases: dxa_femoral_t_score, "
                "bmd_t_score_femoral_neck."
            ),
        ),
        FieldSpec(
            "high_fracture_risk_for_radium223",
            "Alto riesgo fractura para Ra-223 (flag explícito)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223", "peace3", "xofigo_label"],
            help_text=(
                "Marcar 'Sí' si endocrinología/oncología documentó alto "
                "riesgo fractura específico para Ra-223 sin necesidad de "
                "capturar FRAX/DXA numéricos. Activa gate 27."
            ),
        ),
        FieldSpec(
            "bone_protection_established_pre_radium223",
            "Bone protection establecida pre-Ra-223 (override gate 27)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["era223", "peace3", "xofigo_label"],
            help_text=(
                "Marcar 'Sí' tras: (1) denosumab 120mg SC c/4 sem O "
                "zoledronate 4mg IV c/4 sem documentado ≥6 semanas pre-Ra-223, "
                "(2) Vitamin D ≥800 IU/d (25-OH-vit D >30 ng/mL), "
                "(3) calcio ≥1200 mg/d, (4) DXA basal documentada. "
                "Desactiva gate 27."
            ),
        ),

        # ── Auditoría #43 gate 28 — abiraterone adrenal insufficiency ──
        # Gate 28 — Abiraterone adrenal insufficiency (6 fields + 1 override)
        FieldSpec(
            "cortisol_basal_am_ug_dl",
            "Cortisol basal AM (µg/dL, 8-9 AM)",
            "number",
            default="",
            unit="µg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "endocrine_2016"],
            help_text=(
                "Cortisol sérico basal en la mañana (8-9 AM). Rango normal: "
                "6-23 µg/dL. Threshold gate 28 = <5 µg/dL (adrenal "
                "insufficiency severa). Aliases: cortisol_basal, "
                "cortisol_morning, am_cortisol."
            ),
        ),
        FieldSpec(
            "cortisol_post_cosyntropin_ug_dl",
            "Cortisol post-Cosyntropin stimulation (µg/dL @ 30-60 min)",
            "number",
            default="",
            unit="µg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["endocrine_2016", "addison_uk_2023"],
            help_text=(
                "Cortisol post-ACTH (Cosyntropin/Synacthen) stimulation test. "
                "Threshold normal: ≥18 µg/dL @ 30-60 min. Gate 28 activa si "
                "<18 µg/dL (adrenal insufficiency, gold standard test). "
                "Aliases: cosyntropin_stim_cortisol, acth_stim_cortisol."
            ),
        ),
        FieldSpec(
            "adrenal_insufficiency_active",
            "Insuficiencia adrenal activa documentada (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "endocrine_2016"],
            help_text=(
                "Marcar 'Sí' si endocrinología documentó insuficiencia "
                "adrenal activa (Addison primary, secondary post-pituitary, "
                "panhipopituitarismo, supresión crónica esteroides). "
                "Activa gate 28 (contraindica abiraterona sin replacement)."
            ),
        ),
        FieldSpec(
            "sodium_serum_mmol_l",
            "Sodio sérico (mmol/L)",
            "number",
            default="",
            unit="mmol/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["addison_uk_2023"],
            help_text=(
                "Sodio sérico. Rango normal: 135-145 mmol/L. Hiponatremia "
                "<130 + hiperkalemia + fatigue = symptom complex Addison-like "
                "(combinado activa gate 28 trigger 4)."
            ),
        ),
        FieldSpec(
            "potassium_serum_mmol_l",
            "Potasio sérico (mmol/L)",
            "number",
            default="",
            unit="mmol/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["addison_uk_2023"],
            help_text=(
                "Potasio sérico. Rango normal: 3.5-5.0 mmol/L. Hiperkalemia "
                ">5.5 + hiponatremia + fatigue = symptom complex Addison-like "
                "(combinado activa gate 28 trigger 4)."
            ),
        ),
        FieldSpec(
            "severe_fatigue_addison_like",
            "Fatiga severa Addison-like (flag)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["addison_uk_2023"],
            help_text=(
                "Marcar 'Sí' si paciente reporta fatiga severa + debilidad + "
                "hipotensión postural + pérdida peso + náusea + hiperpigmentación "
                "(Addison-like). Combinado con hipoNa <130 + hiperK >5.5 "
                "activa gate 28 trigger 4."
            ),
        ),
        FieldSpec(
            "corticosteroid_replacement_therapy_documented",
            "Corticoides replacement adecuado documentado (override gate 28)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label", "endocrine_2016"],
            help_text=(
                "Marcar 'Sí' tras: (1) prednisona ≥5mg BID O hidrocortisona "
                "≥20mg/d split AM/PM documentado, (2) endocrinology "
                "endorsement, (3) cortisol monitoring estable ≥4 sem, "
                "(4) educación stress-dose + emergency hydrocortisone IM "
                "kit, (5) si Addison primario: fludrocortisona 0.05-0.1mg/d. "
                "Desactiva gate 28."
            ),
        ),
        # ── Gate 29 — olaparib_renal_dysfunction_grade3 (Faubot XLI / #44) ──
        FieldSpec(
            "creatinine_ctcae_grade",
            "AKI / Creatinina CTCAE grade",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "lynparza_label_section_2_3"],
            help_text=(
                "Grado CTCAE v5 de injuria renal aguda: 0 (sin AKI), "
                "1 (creatinine 1.5-2× baseline), 2 (2-4×), 3 (4-6×), "
                "4 (>6× O renal replacement therapy). G≥3 activa gate 29 "
                "(olaparib contraindicado por toxicidad acumulativa renal "
                "documentada en PROfound + Lynparza §2.3)."
            ),
        ),
        FieldSpec(
            "end_stage_renal_disease_dialysis",
            "ESRD on dialysis (flag gate 29)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lynparza_label_section_2_3"],
            help_text=(
                "Marcar 'Sí' si paciente está en hemodiálisis o diálisis "
                "peritoneal. Olaparib NO es removido por hemodiálisis y "
                "no hay datos farmacocinéticos en CKD stage 5 — Lynparza "
                "§2.3 contraindica explícitamente. Activa gate 29."
            ),
        ),
        FieldSpec(
            "renal_function_corrected_for_olaparib",
            "Función renal corregida para olaparib (override gate 29)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lynparza_label_section_2_3", "profound_propel"],
            help_text=(
                "Marcar 'Sí' tras: (1) corrección de causa reversible "
                "documentada (deshidratación, AINE suspendidos, contrastes "
                "washout), (2) CrCl ≥30 mL/min en 2 mediciones separadas "
                "≥7d (Cockcroft-Gault o CKD-EPI 2021), (3) nefrología "
                "endorsement explícito en HC, (4) plan de monitoring renal "
                "mensual primer trimestre. Desactiva gate 29."
            ),
        ),
        # ── Gate 30 — lutetium177_fatigue_grade3 (Faubot XLI / #44) ──
        FieldSpec(
            "fatigue_ctcae_grade",
            "Fatigue CTCAE grade baseline",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "vision_pluvicto", "psmafore"],
            help_text=(
                "Grado CTCAE v5 de fatigue baseline (clinician-rated o "
                "self-reported BFI/FACT-F): 0 (sin fatigue), 1 (alivia "
                "con descanso), 2 (no alivia, limita instrumental ADL), "
                "3 (no alivia, limita SELF-CARE ADL — gate 30 activo), "
                "4 (incapacitante, bedridden). VISION trial protocolo §3.4 "
                "desaconsejó G≥3 baseline por mortalidad temprana ~20% "
                "vs ~6% en G≤2 + discontinuación <3 cycles en 38%."
            ),
        ),
        FieldSpec(
            "karnofsky_performance_status",
            "Karnofsky Performance Status (KPS)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="%",
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["karnofsky_1948", "vision_pluvicto"],
            help_text=(
                "Karnofsky Performance Status escala 0-100 (incrementos 10): "
                "100 (normal), 90 (síntomas leves), 80 (actividad normal con "
                "esfuerzo), 70 (auto-cuidado, no trabajo), 60 (auto-cuidado "
                "ocasional), 50 (asistencia frecuente), 40 (asistencia + "
                "cuidados médicos — ✦ THRESHOLD GATE 30 ≤40), 30 (severamente "
                "incapacitado), 20 (muy enfermo, hospitalización), 10 "
                "(moribundo). Equivalente aprox: KPS 40 ≈ ECOG 3."
            ),
        ),
        FieldSpec(
            "bedridden_status_documented",
            "Bedridden status documentado (flag gate 30)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["vision_pluvicto", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' si paciente está postrado en cama (bedbound) "
                "o requiere asistencia continua para todas las actividades "
                "básicas (alimentación, higiene, transfer cama-silla). "
                "Equivale a ECOG 4 o KPS ≤30. Activa gate 30 (Lu-177 "
                "contraindicado por mortalidad temprana >50% en estos "
                "casos según VISION subset analysis)."
            ),
        ),
        FieldSpec(
            "fatigue_resolved_for_lutetium",
            "Fatigue resuelta para Lu-177 (override gate 30)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["vision_pluvicto", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' tras intervención multidisciplinar de causas "
                "reversibles (anemia tratada, hipotiroidismo corregido, "
                "depresión tratada, dolor controlado, nutrition support, "
                "etc.) Y fatigue baseline ≤G2 en evaluación seguimiento "
                "≥7d Y ECOG ≤2 documentado Y palliative care endorsement "
                "explícito Y plan de monitoring fatigue cada ciclo "
                "(BFI o FACT-F). Desactiva gate 30."
            ),
        ),
        # ── Gate 31 — enzalutamide_cognitive_decline_elderly (Faubot XLIII / #46) ──
        # NOTA: `age` (canonical) + `mmse_baseline` + `moca_baseline` ya
        # están declarados en otros builders (advanced_cognitive_fields,
        # patient demographics). Aquí declaramos solo:
        #   1. cognitive_concerns_documented (Path B trigger flag, NUEVO)
        #   2. cognitive_baseline_normalized_for_arsi_elderly (override, NUEVO)
        # Aliases (mmse_baseline_score, moca_baseline_score, age_at_assessment)
        # se manejan vía YAML alias_fields, no requieren FieldSpec separado.
        FieldSpec(
            "cognitive_concerns_documented",
            "Cognitive concerns baseline documentadas (flag gate 31)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ucsf_cohort_2024", "siog_geriatric_oncology"],
            help_text=(
                "Marcar 'Sí' si el clínico (oncólogo, neurólogo, geriatra) "
                "ha documentado preocupaciones cognitivas baseline en el "
                "paciente — incluso si MMSE/MoCA no captan déficit objetivo. "
                "Ejemplos: pérdida de memoria reciente notable, dificultad "
                "para nombrar objetos, desorientación leve, lentitud "
                "cognitiva, caregiver concerns. Combinado con edad ≥75 años "
                "activa gate 31 trigger Path B (enzalutamida contraindicada "
                "por mayor penetración SNC; preferir darolutamida)."
            ),
        ),
        FieldSpec(
            "cognitive_baseline_normalized_for_arsi_elderly",
            "Cognitive baseline normalizado para ARSI elderly (override gate 31)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ucsf_cohort_2024", "siog_geriatric_oncology"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) geriatric assessment formal "
                "(G8 score + comprehensive per SIOG), (2) neurology "
                "endorsement explícito por escrito, (3) plan de monitoring "
                "trimestral MMSE+MoCA con criterios pre-definidos de "
                "discontinuación (caída ≥2 puntos = stop), (4) caregiver "
                "education estructurada sobre signos de alarma (confusion, "
                "falls, judgment changes, anomia), (5) patient/family "
                "informed consent específico mencionando HR 2.7 cohort "
                "UCSF 2024. Desactiva gate 31."
            ),
        ),
        # ── Gate 32 — darolutamide_hepatotoxicity_grade3 (Faubot XLIV / #47) ──
        # NOTA: ast_value, alt_value, bilirubin_total_mg_dl ya están
        # declarados en advanced_hepatic_fields() (canonical). Aquí declaramos:
        #   1. ast_ctcae_grade (NUEVO — trigger 3 gate 32)
        #   2. alt_ctcae_grade (NUEVO — trigger 4 gate 32)
        #   3. hepatocellular_pattern_documented_for_darolutamide (NUEVO flag)
        #   4. hepatic_function_recovered_for_darolutamide (override)
        # Aliases (sgot, sgpt, ast_iu_l, etc.) se manejan vía YAML alias_fields.
        FieldSpec(
            "ast_ctcae_grade",
            "AST CTCAE grade (gate 32)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "nubeqa_label_section_6"],
            help_text=(
                "Grado CTCAE v5 de AST elevation: 0 (normal), 1 (>ULN-3× "
                "ULN), 2 (>3-5× ULN), 3 (>5-20× ULN — ✦ THRESHOLD GATE 32), "
                "4 (>20× ULN — contraindicación absoluta). Combinado con "
                "ALT grade ≥3 indica patrón hepatocelular típico de "
                "darolutamida (vs colestásico de abiraterona en gate 21)."
            ),
        ),
        FieldSpec(
            "alt_ctcae_grade",
            "ALT CTCAE grade (gate 32)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "nubeqa_label_section_6"],
            help_text=(
                "Grado CTCAE v5 de ALT elevation: 0 (normal), 1 (>ULN-3× "
                "ULN), 2 (>3-5× ULN), 3 (>5-20× ULN — ✦ THRESHOLD GATE 32), "
                "4 (>20× ULN — contraindicación absoluta). ALT más específico "
                "para hepatocellular damage que AST (que también puede "
                "elevarse en daño muscular)."
            ),
        ),
        FieldSpec(
            "hepatocellular_pattern_documented_for_darolutamide",
            "Patrón hepatocelular documentado para darolutamida (flag gate 32)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nubeqa_label_section_6", "aranote_arasens"],
            help_text=(
                "Marcar 'Sí' si hepatology confirmó patrón hepatocelular "
                "(AST/ALT >>5× ULN sin colestasis significativa, R-ratio "
                ">5 en pattern analysis) atribuible a darolutamida tras "
                "descartar causas alternativas (DILI por DDIs, hepatitis "
                "viral A/B/C, autoinmune, NAFLD, alcoholic, biliary "
                "obstruction). Activa gate 32 de manera definitiva."
            ),
        ),
        FieldSpec(
            "hepatic_function_recovered_for_darolutamide",
            "Función hepática recuperada para darolutamida (override gate 32)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nubeqa_label_section_6", "aranote_arasens"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) AST/ALT <2.5× ULN documentado "
                "en 2 mediciones separadas ≥7d, (2) bilirubina total <1.5× "
                "ULN, (3) causa alternativa descartada O DDI hepatotóxica "
                "corregida documentada, (4) hepatology endorsement explícito "
                "en HC, (5) plan monitoring CADA SEMANA × 4 sem post-"
                "reintroducción, luego cada 2 sem × 4 sem, luego mensual, "
                "(6) considerar dosis REDUCIDA inicial (300mg BID en vez de "
                "600mg BID) primer mes. Desactiva gate 32."
            ),
        ),
        # ── Gate 33 — niraparib_thrombocytopenia_rapid_drop (Faubot XLVII / #48) ──
        # NOTA: `platelets` ya es FieldSpec canónico (advanced_laboratory_baseline).
        # Aquí declaramos solo:
        #   1. platelets_baseline_pre_niraparib (NUEVO — baseline LONGITUDINAL)
        #   2. rapid_platelet_drop_for_niraparib (NUEVO Path C trigger flag)
        #   3. platelets_recovered_post_rapid_drop_for_niraparib (NUEVO override)
        FieldSpec(
            "platelets_baseline_pre_niraparib",
            "Plaquetas baseline pre-niraparib (CBC visita 0)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="/µL",
            min_value=0,
            max_value=2000000,
            allow_negative=False,
            evidence_tags=["magnitude_chi_nejm_2023", "akeega_label_section_5_1"],
            help_text=(
                "Plaquetas BASELINE documentadas en CBC INMEDIATAMENTE "
                "antes de iniciar niraparib (visita 0 del tratamiento). "
                "Necesario para gate 33 longitudinal — detecta caída ≥75K "
                "absolutos (Path A) o caída ≥50K + current <175K (Path B "
                "compound). MAGNITUDE subset analysis (Chi NEJM 2023) "
                "documentó que 70% de pacientes con caída ≥30% durante "
                "primeras 2 sem discontinuaron <3 ciclos. Si NO se "
                "documenta baseline, gate 33 NO puede evaluar (gate 22 "
                "sigue cubriendo threshold absoluto <150K)."
            ),
        ),
        FieldSpec(
            "rapid_platelet_drop_for_niraparib",
            "Caída rápida plt para niraparib documentada (flag gate 33)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["magnitude_chi_nejm_2023", "akeega_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' si hematology o oncology documentó caída "
                "rápida de plaquetas atribuible a niraparib durante "
                "seguimiento (incluso si no se cumple threshold absoluto "
                "Path A o Path B compound). Activa gate 33 Path C "
                "(documentación clínica). Útil cuando el clínico observa "
                "patrón idiosincrásico de hipersensibilidad hematológica "
                "con baseline pre-niraparib no documentado o data "
                "longitudinal incompleta."
            ),
        ),
        FieldSpec(
            "platelets_recovered_post_rapid_drop_for_niraparib",
            "Plt recuperadas post-caída para niraparib (override gate 33)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["magnitude_chi_nejm_2023", "akeega_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) plaquetas ≥75% del baseline "
                "pre-niraparib documentado en 2 mediciones separadas ≥7d, "
                "(2) sin sangrado activo ≥7 días, (3) hematology "
                "endorsement explícito en HC, (4) plan reducción dosis "
                "200mg → 100mg per Akeega label dose modification table, "
                "(5) monitoreo CBC SEMANAL × 4 sem post-reintroducción, "
                "(6) si recurrencia caída rápida → discontinuación "
                "PERMANENTE. Desactiva gate 33."
            ),
        ),
        # ── Gate 34 — docetaxel_neutropenia_rapid_drop (Faubot XLVIII / #49) ──
        FieldSpec(
            "anc_baseline_pre_docetaxel",
            "ANC baseline pre-docetaxel (CBC visita 0)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="/µL",
            min_value=0,
            max_value=50000,
            allow_negative=False,
            evidence_tags=["tax327_supplementary", "taxotere_label_section_5"],
            help_text=(
                "ANC baseline documentado en CBC INMEDIATAMENTE antes de "
                "iniciar docetaxel (visita 0). Necesario para gate 34 "
                "longitudinal — detecta caída ≥1500 absolutos (Path A) "
                "o caída ≥1000 + current <2000 (Path B). TAX-327 "
                "supplementary: 60% discontinuación + 22% sepsis G≥3 "
                "con caída ≥50%."
            ),
        ),
        FieldSpec(
            "rapid_anc_drop_for_docetaxel",
            "Caída rápida ANC para docetaxel (flag gate 34)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["tax327_supplementary"],
            help_text=(
                "Marcar 'Sí' si oncólogo o hematology documentaron caída "
                "rápida ANC atribuible a docetaxel (incluso si data "
                "longitudinal incompleta). Activa gate 34 Path C."
            ),
        ),
        FieldSpec(
            "anc_recovered_post_drop_for_docetaxel",
            "ANC recuperado para docetaxel (override gate 34)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["tax327_supplementary", "taxotere_label_section_5"],
            help_text=(
                "Marcar 'Sí' tras: (1) ANC ≥75% baseline pre-docetaxel, "
                "(2) sin febrile neutropenia ≥7d, (3) GCSF profilaxis "
                "ACTIVA pegfilgrastim documented, (4) reducción dosis "
                "75→60 mg/m² per Taxotere label. Desactiva gate 34."
            ),
        ),
        # ── Gate 35 — arsi_abiraterone_vte_risk_high (Faubot XLIX / #56) ──
        FieldSpec(
            "history_vte_documented",
            "Historia TEV previo documentado (flag gate 35)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["cou_aa_302", "latitude", "klil_drori_2019"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia previa de TEV "
                "(trombosis venosa profunda DVT o embolia pulmonar PE) "
                "documentada. HR 5.2x recurrencia con ARSI/abiraterona. "
                "Activa gate 35 Path A."
            ),
        ),
        FieldSpec(
            "bmi",
            "Índice de masa corporal (IMC)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="kg/m²",
            min_value=10,
            max_value=80,
            allow_negative=False,
            evidence_tags=["khorana_score", "improve_score"],
            help_text=(
                "IMC = peso(kg) / altura(m)². Categorías: <18.5 bajo peso, "
                "18.5-24.9 normal, 25-29.9 sobrepeso, ≥30 obesidad. IMC ≥30 "
                "+ edad ≥75 activa gate 35 Path B compound (riesgo TEV)."
            ),
        ),
        FieldSpec(
            "d_dimer_ng_ml",
            "D-dímero (ng/mL)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="ng/mL",
            min_value=0,
            max_value=50000,
            allow_negative=False,
            evidence_tags=["khorana_score"],
            help_text=(
                "D-dímero sérico. ULN típico ~500 ng/mL. Valores >1000 "
                "indican hipercoagulabilidad activa — activa gate 35 Path C "
                "(riesgo TEV alto en ARSI/abiraterona)."
            ),
        ),
        FieldSpec(
            "vte_high_risk_for_arsi_documented",
            "Riesgo TEV alto para ARSI documentado (flag gate 35)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["khorana_score", "improve_score"],
            help_text=(
                "Marcar 'Sí' si Khorana score ≥3 o IMPROVE score ≥4 "
                "documentados, o si oncology/hematology evaluó riesgo "
                "TEV alto multifactorial. Activa gate 35 Path D."
            ),
        ),
        FieldSpec(
            "anticoagulation_therapeutic_active",
            "Anticoagulación terapéutica activa (override gate 35)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_vte_2023"],
            help_text=(
                "Marcar 'Sí' SOLO si paciente está en anticoagulación "
                "terapéutica activa (DOAC apixaban/rivaroxaban dose "
                "tratamiento, warfarin INR 2-3 documentado, O HBPM "
                "enoxaparina dose tratamiento) + hematology endorsement "
                "explícito. Desactiva gate 35."
            ),
        ),
        # ── Gate 36 — triplete_frailty_g8_low (Faubot L / #60) ──
        FieldSpec(
            "g8_geriatric_score",
            "G8 Geriatric Screening Score (8 ítems, 0-17)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="puntos 0-17",
            min_value=0,
            max_value=17,
            allow_negative=False,
            evidence_tags=["bellera_g8_2012", "siog_2024"],
            help_text=(
                "G8 (Bellera Ann Oncol 2012) — screening tool SIOG para "
                "vulnerabilidad geriátrica multidimensional (8 ítems: "
                "nutrición + movilidad + medicación + cognición + estado "
                "psicológico + apoyo social + comorbilidad + edad). "
                "Cutoffs: >14 fit, 11-14 vulnerable (CGA recomendado), "
                "≤10 frail (triplete contraindicado). Activa gate 36 si ≤14."
            ),
        ),
        FieldSpec(
            "cga_vulnerable_or_frail_documented",
            "CGA vulnerable o frail documentado (flag gate 36)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["siog_2024", "asco_geriatric_oncology_2018"],
            help_text=(
                "Marcar 'Sí' si Comprehensive Geriatric Assessment (CGA "
                "per SIOG) clasificó al paciente como VULNERABLE o FRAIL. "
                "Activa gate 36 Path C (proxy si G8 no aplicable)."
            ),
        ),
        FieldSpec(
            "geriatric_clearance_for_triplete",
            "Geriatric clearance para triplete (override gate 36)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["siog_2024"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) CGA completa por geriatra "
                "oncológico, (2) clearance explícito para triplete con "
                "reducción dosis docetaxel 60mg/m², (3) GCSF profilaxis "
                "primaria pegfilgrastim ciclo 1, (4) monitoring CBC "
                "semanal × 8 sem, (5) re-evaluar G8 cada 2 ciclos con "
                "criterio discontinuación si cae a ≤10. Desactiva gate 36."
            ),
        ),
        # ── Gate 37 — sipuleucel_t_severe_irr (Faubot LI / #53) ──
        FieldSpec(
            "history_severe_irr_for_immunotherapy",
            "Historia IRR severo para immunoterapia (flag gate 37)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["impact_kantoff_2010", "provenge_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia previa de IRR "
                "(Infusion-Related Reaction) G≥3 con immunoterapia o "
                "biológicos. HR 8.2x recurrencia G≥3 en re-exposición "
                "Provenge sin premedicación. Activa gate 37 Path A."
            ),
        ),
        FieldSpec(
            "irr_grade_documented",
            "IRR grade CTCAE documentado en infusión previa",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ctcae_v5", "provenge_label_section_5_1"],
            help_text=(
                "Grado CTCAE v5 de IRR documentado en infusión previa: "
                "0 (sin reacción), 1 (mild, no intervención), 2 (moderate, "
                "infusión interrupted), 3 (severe, prolonged interruption + "
                "intervention), 4 (life-threatening, anafilaxis). G≥3 "
                "activa gate 37 Path B (criterio absoluto IMPACT protocol)."
            ),
        ),
        FieldSpec(
            "anaphylaxis_history_documented",
            "Historia anafilaxis documentada (flag gate 37)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["provenge_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia documentada de "
                "anafilaxis (a cualquier alergeno: alimento, medicamento, "
                "vacuna, picadura). Riesgo cross-reactivity con PA2024 "
                "antigen Provenge. Activa gate 37 Path C."
            ),
        ),
        FieldSpec(
            "irr_premedication_protocol_active",
            "Premedicación IRR protocol activo (override gate 37)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["provenge_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) acetaminofén 650mg + "
                "difenhidramina 25-50mg + metilprednisolona 100mg IV "
                "30 min pre-infusión, (2) epinefrina 1:1000 disponible, "
                "(3) hospitalary monitoring ≥30 min post-infusión, "
                "(4) velocidad infusión REDUCIDA 50% post-IRR. "
                "Desactiva gate 37."
            ),
        ),
        # ── Gate 38 — sipuleucel_t_febrile_neutropenia (Faubot LI / #53) ──
        FieldSpec(
            "temperature_celsius",
            "Temperatura corporal (°C)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="°C",
            min_value=30,
            max_value=45,
            allow_negative=False,
            evidence_tags=["ctcae_v5"],
            help_text=(
                "Temperatura corporal (oral o axilar). T ≥38.3°C = febrile. "
                "Combinado con ANC <500 activa gate 38 Path A (febrile "
                "neutropenia G≥3 absoluta per CTCAE v5)."
            ),
        ),
        FieldSpec(
            "no_gcsf_prophylaxis_planned",
            "Sin GCSF profilaxis planeada (flag gate 38)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["provenge_label_section_5_2"],
            help_text=(
                "Marcar 'Sí' si NO hay plan de GCSF profilaxis (pegfilgrastim "
                "o filgrastim) pre-leukapheresis. Combinado con ANC baseline "
                "<1500 activa gate 38 Path B (alto riesgo descompensación)."
            ),
        ),
        FieldSpec(
            "febrile_neutropenia_for_immunotherapy",
            "Febrile neutropenia post-immunoterapia documentada (flag gate 38)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["impact_kantoff_2010"],
            help_text=(
                "Marcar 'Sí' si paciente tuvo febrile neutropenia (T ≥38.3°C "
                "+ ANC <500) post-leukapheresis o post-infusión Provenge "
                "previa. Activa gate 38 Path C."
            ),
        ),
        FieldSpec(
            "gcsf_prophylaxis_active_for_sipuleucel",
            "GCSF profilaxis activa para Sipuleucel-T (override gate 38)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["provenge_label_section_5_2", "asco_neutropenia_2018"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) pegfilgrastim 6mg SC día +1 "
                "post-leukapheresis (NO post-infusión), (2) monitoring CBC "
                "diario × 5d post-leukapheresis, (3) ANC ≥1500 confirmado "
                "pre-CADA infusión Provenge, (4) si nueva febrile neutropenia "
                "→ discontinuación PERMANENTE. Desactiva gate 38."
            ),
        ),
        # ── Gate 39 — abiraterone_alp_rapid_rise_longitudinal (Faubot LIII / #50) ──
        FieldSpec(
            "alp_baseline_pre_abiraterone",
            "ALP baseline pre-abiraterona (CBC visita 0)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="U/L",
            min_value=0,
            max_value=5000,
            allow_negative=False,
            evidence_tags=["latitude_supplementary", "zytiga_label_section_5_1"],
            help_text=(
                "Alkaline Phosphatase (ALP) BASELINE documentada en CBC "
                "INMEDIATAMENTE antes de iniciar abiraterona (visita 0). "
                "Necesario para gate 39 longitudinal — detecta rise ≥150 "
                "absolutos (Path A) o rise ≥75 + current >300 IU/L (Path B "
                "compound). LATITUDE supplementary documentó 8% progresión "
                "a hepatotox G≥3 con rise ≥2× ULN durante primeros 3 meses. "
                "Patrón COLESTÁSICO: ALP↑ + GGT↑ + bili↑ con AST/ALT "
                "preservadas — distinto de gate 32 darolutamida hepatocelular. "
                "ULN típico ALP: 30-130 U/L."
            ),
        ),
        FieldSpec(
            "cholestatic_pattern_for_abiraterone",
            "Patrón colestásico para abiraterona documentado (flag gate 39)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["latitude_supplementary", "zytiga_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' si hepatology o oncology documentaron patrón "
                "COLESTÁSICO atribuible a abiraterona (R-ratio <2 en pattern "
                "analysis: ALP↑ + GGT↑ + bili↑ con AST/ALT relativamente "
                "preservadas) — incluso si data longitudinal incompleta. "
                "Activa gate 39 Path C. Útil cuando baseline ALP no "
                "documentado o paciente inicia con AST/ALT normales pero "
                "ALP rising."
            ),
        ),
        FieldSpec(
            "alp_normalized_post_rise_for_abiraterone",
            "ALP normalizado post-rise para abiraterona (override gate 39)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["latitude_supplementary", "zytiga_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) ALP ≤1.5× ULN documentado en "
                "2 mediciones separadas ≥7d, (2) bilirubina total <1.5× "
                "ULN, (3) causa alternativa descartada (progresión ósea, "
                "obstrucción biliar, hepatitis viral, DDI), (4) hepatology "
                "endorsement explícito en HC, (5) plan monitoring QUINCENAL "
                "× 4 sem post-reintroducción + reducción dosis 1000 → 500 "
                "mg/d primer mes (per Zytiga §2.4 dose modification). "
                "Desactiva gate 39."
            ),
        ),
        # ── Gate 40 — lutetium177_hb_rapid_drop_longitudinal (Faubot LIV / #51) ──
        FieldSpec(
            "hb_baseline_pre_lutetium",
            "Hb baseline pre-Lu-177 (CBC visita 0)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="g/dL",
            min_value=0,
            max_value=25,
            allow_negative=False,
            evidence_tags=["vision_supplementary", "pluvicto_label_section_6"],
            help_text=(
                "Hemoglobina BASELINE documentada en CBC INMEDIATAMENTE "
                "antes de iniciar Lu-177-PSMA (visita 0). Necesario para "
                "gate 40 longitudinal — detecta drop ≥2 g/dL absolutos "
                "(Path A) o drop ≥1 g/dL + current <9 g/dL (Path B "
                "compound). VISION supplementary documentó: 65% transfusión "
                "+ 30% discontinuación con drop ≥2 g/dL en <8 sem; signal "
                "predictivo PRE-transfusión con ventana 2-4 sem para "
                "optimización (suplementación hierro/B12/folato + EPO si "
                "insuficiencia renal)."
            ),
        ),
        FieldSpec(
            "rapid_hb_drop_for_lutetium",
            "Caída rápida Hb para Lu-177 documentada (flag gate 40)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["vision_supplementary", "pluvicto_label_section_6"],
            help_text=(
                "Marcar 'Sí' si hematology u oncology documentaron caída "
                "rápida de Hb atribuible a Lu-177 con riesgo transfusional "
                "(incluso si data longitudinal incompleta o baseline "
                "pre-Lu-177 no documentado). Activa gate 40 Path C "
                "(documentación clínica). Útil para anemia idiosincrásica "
                "post-cycle 1-2 con baseline marginal."
            ),
        ),
        FieldSpec(
            "hb_recovered_post_drop_for_lutetium",
            "Hb recuperado post-drop para Lu-177 (override gate 40)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["vision_supplementary", "asco_anemia_2024"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) Hb ≥85% baseline pre-Lu-177 "
                "documentado en 2 mediciones separadas ≥7d, (2) sin "
                "transfusión activa ≥7 días, (3) suplementación hierro IV "
                "(ferritina <100 + sat trans <20%) + B12/folato + EPO si "
                "CrCl <60 documentada, (4) hematology endorsement explícito "
                "en HC, (5) plan monitoring CBC SEMANAL × 4 sem "
                "post-reintroducción, (6) si recurrencia drop rápido → "
                "discontinuación PERMANENTE. Desactiva gate 40."
            ),
        ),
        # ── Gate 41 — cabazitaxel_hb_rapid_drop_longitudinal (Faubot LV / #52) ──
        FieldSpec(
            "hb_baseline_pre_cabazitaxel",
            "Hb baseline pre-cabazitaxel (CBC visita 0)",
            "number",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            unit="g/dL",
            min_value=0,
            max_value=25,
            allow_negative=False,
            evidence_tags=["tropic_supplementary", "card_subset", "jevtana_label_section_6"],
            help_text=(
                "Hemoglobina BASELINE documentada en CBC INMEDIATAMENTE "
                "antes de iniciar cabazitaxel (visita 0). Necesario para "
                "gate 41 longitudinal — detecta drop ≥2 g/dL absolutos "
                "(Path A) o drop ≥1 g/dL + current <9 g/dL (Path B "
                "compound). CARD subset analysis (de Wit NEJM 2019) "
                "documentó: 70% transfusión + 35% discontinuación con drop "
                "≥2 g/dL en primeras 6 sem; 85% transfusión + 6% "
                "mortalidad temprana con drop ≥3 g/dL en <8 sem sin GCSF "
                "profilaxis. Cofactor edad >75 multiplica HR 2.3."
            ),
        ),
        FieldSpec(
            "rapid_hb_drop_for_cabazitaxel",
            "Caída rápida Hb para cabazitaxel documentada (flag gate 41)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["card_subset", "jevtana_label_section_6"],
            help_text=(
                "Marcar 'Sí' si hematology u oncology documentaron caída "
                "rápida de Hb atribuible a cabazitaxel con riesgo "
                "transfusional (incluso si data longitudinal incompleta "
                "o baseline pre-cabazitaxel no documentado). Activa gate "
                "41 Path C (documentación clínica)."
            ),
        ),
        FieldSpec(
            "hb_recovered_post_drop_for_cabazitaxel",
            "Hb recuperado post-drop para cabazitaxel (override gate 41)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["card_subset", "jevtana_label_section_2_4", "asco_anemia_2024"],
            help_text=(
                "Marcar 'Sí' SOLO tras: (1) Hb ≥85% baseline pre-cabazitaxel "
                "en 2 mediciones separadas ≥7d, (2) sin transfusión activa "
                "≥7 días, (3) GCSF profilaxis primaria pegfilgrastim 6mg "
                "SC día +1 documented, (4) reducción dosis 25 → 20 mg/m² "
                "en elderly (>65 años) per Jevtana §2.4, (5) hematology "
                "endorsement explícito + monitoring CBC SEMANAL × 4 sem "
                "post-reintroducción. Desactiva gate 41."
            ),
        ),
        # ── Gate 42 — apalutamide_severe_rash_sjs_ten (Faubot LVI / #57) ──
        # ⚠️ DISTINTIVO: PRIMER gate del catálogo SIN OVERRIDE — discontinuación
        # PERMANENTE per Erleada §5.2 (sienta precedente arquitectónico para
        # gates con contraindicación absoluta irreversible).
        FieldSpec(
            "rash_ctcae_grade",
            "Grado CTCAE v5 de rash cutáneo (Path A gate 42)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label_section_5_2", "spartan", "titan", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 del rash cutáneo (0-5). Gate 42 dispara "
                "con grado ≥3: 'Severe; medical intervention indicated; "
                "limiting self care ADL; ulcerative; involving >30% BSA; "
                "associated systemic findings'. SPARTAN (Smith NEJM 2018) + "
                "TITAN (Chi NEJM 2019) documentaron G≥3 5.2-6.3% apalutamida "
                "(vs 0.3% placebo). G≥3 = ALERTA SCAR — descartar SJS/TEN "
                "URGENTE. CTCAE: G1 macular/papular eruption <10% BSA; G2 "
                "10-30% BSA; G3 >30% BSA o ulcerative; G4 life-threatening "
                "(SCAR fenotipo); G5 muerte."
            ),
        ),
        FieldSpec(
            "skin_blistering_documented",
            "Blistering cutáneo documentado para apalutamida (Path B gate 42)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label_section_5_2", "sjs_ten_post_marketing"],
            help_text=(
                "Marcar 'Sí' si dermatology u oncology documentaron presencia "
                "de ampollas/vesículas (vesiculobullous lesions) en piel — "
                "fenotipo PRECURSOR Stevens-Johnson Syndrome (SJS) / Toxic "
                "Epidermal Necrolysis (TEN). ZERO TOLERANCE: blistering en "
                "contexto apalutamida = DISCONTINUACIÓN PERMANENTE per "
                "Erleada §5.2 (no override). Activa gate 42 Path B."
            ),
        ),
        FieldSpec(
            "mucosal_involvement_documented",
            "Involvement mucosal documentado para apalutamida (Path C gate 42)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label_section_5_2", "sjs_ten_post_marketing"],
            help_text=(
                "Marcar 'Sí' si exam clínico documenta involvement de ≥1 "
                "mucosa (oral, conjuntival, urogenital, perianal, esofágica) "
                "en contexto apalutamida — fenotipo PATOGNOMÓNICO SJS-spectrum "
                "(involvement mucoso = criterio diagnóstico mayor SJS/TEN per "
                "Mockenhaupt Lancet Oncol 2017). Cuidado oftalmológico urgente "
                "si conjuntival involvement (prevenir cicatrices). Activa "
                "gate 42 Path C."
            ),
        ),
        FieldSpec(
            "erythema_multiforme_documented",
            "Erythema multiforme (target lesions) documentado (Path D gate 42)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label_section_5_2", "ctcae_v5", "em_major_phenotype"],
            help_text=(
                "Marcar 'Sí' si dermatology documenta lesiones target "
                "concéntricas (erythema multiforme — fenotipo INTERMEDIO "
                "EM-major / SJS overlap). Target lesions = patrón "
                "tricolor (centro oscuro + zona pálida + halo eritematoso) "
                "en piel + ocasionalmente mucosas. EM-major con mucositis = "
                "ya en spectrum SJS, requiere DISCONTINUACIÓN PERMANENTE "
                "apalutamida. Activa gate 42 Path D."
            ),
        ),
        FieldSpec(
            "sjs_ten_suspected_or_diagnosed",
            "SJS/TEN sospechado o diagnosticado (Path E gate 42)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["erleada_label_section_5_2", "sjs_ten_post_marketing", "scorten"],
            help_text=(
                "Marcar 'Sí' si dermatology u oncology documentan sospecha "
                "clínica O diagnóstico explícito de Stevens-Johnson Syndrome "
                "(SJS, BSA <10% epidermolysis) / Toxic Epidermal Necrolysis "
                "(TEN, BSA >30%) / SJS-TEN overlap (BSA 10-30%) en contexto "
                "apalutamida. Mortalidad SJS 5-12%, TEN 25-50% per SCORTEN "
                "Bastuji-Garin J Invest Dermatol 2000. ⚠️ DISCONTINUACIÓN "
                "PERMANENTE inmediata — NO re-rechallenge en NINGUNA "
                "circunstancia per Erleada §5.2. Notificación FDA MedWatch + "
                "Janssen Pharmaceutical Affairs obligatoria. Activa gate 42 "
                "Path E."
            ),
        ),
        # ── Gates 43-46 — Checkpoint inhibitors irAE (Faubot LVII / #54) ──
        # 4 gates simultáneos: pneumonitis (43) + hepatitis (44) + colitis (45)
        # + endocrinopathies (46). Comparten REGIMEN_CODES_CHECKPOINT_INHIBITORS
        # pero scope clínico distinto. 2da clase IO del catálogo (post Sipuleucel-T #53).
        # ─── Gate 43: pneumonitis irAE ───
        FieldSpec(
            "pneumonitis_ctcae_grade",
            "Grado CTCAE v5 de pneumonitis (Path A gate 43)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["keynote_365", "keynote_921", "nccn_io_toxicity_2024", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 de pneumonitis immune-related (irAE pulmonar). "
                "Gate 43 dispara con G≥2: 'Symptomatic; medical intervention "
                "indicated; limiting instrumental ADL'. KEYNOTE-365/921 "
                "documentaron pneumonitis G≥2 en 2.1-3.2% pembrolizumab; "
                "G≥3 mortalidad 5-10% sin tratamiento. Tiempo medio aparición "
                "3.1 meses (rango 0.5-13.6). DISCONTINUACIÓN PERMANENTE "
                "checkpoint inhibitor en G3-G4 per NCCN IO Toxicity 2024 §PNEU-1."
            ),
        ),
        FieldSpec(
            "pneumonitis_documented_for_checkpoint_inhibitor",
            "Pneumonitis IO documentada (Path B gate 43)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024", "brahmer_jco_2018"],
            help_text=(
                "Marcar 'Sí' si pulmonology u oncology documentaron pneumonitis "
                "immune-related (irAE) en contexto checkpoint inhibitor. "
                "Activa gate 43 Path B incluso si CTCAE grade no documentado. "
                "Evaluación urgente HRCT thorax + spirometría + DLCO."
            ),
        ),
        FieldSpec(
            "hypoxemia_with_checkpoint_inhibitor",
            "Hipoxemia (SpO2 <92% RA) con checkpoint inhibitor (Path C gate 43)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024", "brahmer_jco_2018"],
            help_text=(
                "Marcar 'Sí' si SpO2 <92% room air documentado en contexto "
                "checkpoint inhibitor (sospecha alta pneumonitis irAE). "
                "Activa gate 43 Path C como signo precoz crítico — workup "
                "HRCT urgente + considerar suspensión IO + esteroides empíricos."
            ),
        ),
        FieldSpec(
            "ground_glass_opacities_ct_for_checkpoint",
            "Ground-glass opacities CT en contexto checkpoint inhibitor (Path D gate 43)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024", "naidoo_jco_2017"],
            help_text=(
                "Marcar 'Sí' si HRCT thorax documenta ground-glass opacities "
                "(GGO) en contexto checkpoint inhibitor — patrón radiográfico "
                "típico irAE pulmonar (también consolidación, opacidades "
                "reticulares, derrame pleural en casos severos). Activa "
                "gate 43 Path D — workup BAL + biopsia si dx incierto."
            ),
        ),
        FieldSpec(
            "pneumonitis_resolved_for_checkpoint_inhibitor",
            "Pneumonitis IO recuperada (override gate 43)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_pneu1"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) CTCAE G≤1 documentada en 2 visitas "
                "separadas ≥7d, (2) esteroides taper completado (prednisona "
                "<10 mg/d), (3) HRCT control SIN nuevos infiltrados, "
                "(4) DLCO recuperada >75% baseline, (5) pulmonology endorsement "
                "explícito + monitoring SpO2 + CT mensual × 3 meses. Desactiva "
                "gate 43."
            ),
        ),
        # ─── Gate 44: hepatitis irAE ───
        FieldSpec(
            "hepatitis_ctcae_grade",
            "Grado CTCAE v5 de hepatitis (Path D gate 44)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["keynote", "keylynk_010", "checkmate_9kd", "nccn_io_toxicity_2024", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 de hepatitis immune-related (irAE hepático). "
                "Gate 44 dispara con G≥3: AST/ALT >5× ULN, ALP >5× ULN, "
                "bilirubin >3× ULN. KEYNOTE/KeyLynk-010/CheckMate-9KD "
                "documentaron hepatitis G≥3 en 1.8-3.4% pembro/nivo; "
                "G≥4 mortalidad 5-15% sin tratamiento. Patrón HEPATOCELULAR "
                "immune-mediated (T-cell infiltrate portal/centrolobulillar) "
                "distinto de gates 21+39 abi (CYP17/colestásico) y gate 32 "
                "darolutamida (CYP3A4+UGT1A9 hepatocelular metabólico)."
            ),
        ),
        FieldSpec(
            "hepatitis_immune_documented_for_checkpoint",
            "Hepatitis IO immune documentada (Path E gate 44)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_hep1", "de_martin_j_hepatol_2018"],
            help_text=(
                "Marcar 'Sí' si hepatology documenta hepatitis immune-related "
                "(irAE) en contexto checkpoint inhibitor. Distintivo: ANA/SMA/LKM "
                "frecuentemente NEGATIVOS (vs AIH clásica). Biopsia hepática "
                "muestra infiltrado linfocítico CD8+ portal y centrolobulillar. "
                "Activa gate 44 Path E."
            ),
        ),
        FieldSpec(
            "hepatic_function_recovered_for_checkpoint_inhibitor",
            "Función hepática recuperada IO (override gate 44)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_hep1"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) AST/ALT <2.5× ULN documentada en 2 "
                "visitas separadas ≥7d, (2) bilirubin <1.5× ULN, (3) esteroides "
                "taper completado (prednisona <10 mg/d), (4) hepatology "
                "endorsement + biopsia hepática control considerada, "
                "(5) monitoring semanal × 4 sem post-reintroducción. Desactiva "
                "gate 44."
            ),
        ),
        # ─── Gate 45: colitis irAE ───
        FieldSpec(
            "colitis_ctcae_grade",
            "Grado CTCAE v5 de colitis (Path A gate 45)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["keynote", "checkmate_650", "nccn_io_toxicity_2024_gi1", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 de colitis immune-related (irAE GI). Gate 45 "
                "dispara con G≥3: severa, hospitalización, hemorragia, perforación, "
                "peritonitis. KEYNOTE/CheckMate-650/KeyLynk-010 documentaron colitis "
                "G≥3 en 1.4-3.8% (combo nivo+ipi 2-3× MÁS ALTA ~10%); G≥3 mortalidad "
                "5-12% (mayoría perforación). DISCONTINUACIÓN PERMANENTE en G≥3 "
                "per NCCN IO Toxicity 2024 §GI-1."
            ),
        ),
        FieldSpec(
            "diarrhea_ctcae_grade",
            "Grado CTCAE v5 de diarrhea (Path B gate 45)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_gi1", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 de diarrhea (puede coexistir con colitis irAE). "
                "Gate 45 dispara con G≥3: ≥7 episodios/d, hospitalización, "
                "limitando self-care ADL. Distinguir de causas infecciosas "
                "(C. difficile PCR + coprocultivo + parásitos) antes de atribuir "
                "a irAE. Calprotectina fecal >250 µg/g sospecha alta colitis."
            ),
        ),
        FieldSpec(
            "bowel_perforation_for_checkpoint_inhibitor",
            "Perforación intestinal con checkpoint inhibitor (Path C gate 45 — emergencia)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_gi1"],
            help_text=(
                "Marcar 'Sí' ante perforación intestinal documentada (CT con "
                "neumoperitoneo, peritonitis clínica, signos sepsis abdominal) "
                "en contexto checkpoint inhibitor. EMERGENCIA QUIRÚRGICA — "
                "consulta colorrectal urgente, posible colectomía. Mortalidad "
                "alta sin cirugía oportuna. Activa gate 45 Path C — DISCONTINUACIÓN "
                "PERMANENTE checkpoint inhibitor."
            ),
        ),
        FieldSpec(
            "colitis_immune_documented_for_checkpoint",
            "Colitis IO immune documentada (Path D gate 45)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_gi1", "bertrand_j_crohns_colitis_2017"],
            help_text=(
                "Marcar 'Sí' si gastroenterology documenta colitis immune-related "
                "vía colonoscopia + biopsias (patrón histológico linfocítico "
                "T CD8+ con apoptosis criptas, sin pathógeno identificable). "
                "Distribución típicamente continua descendente (vs IBD parches). "
                "Activa gate 45 Path D."
            ),
        ),
        FieldSpec(
            "hematochezia_severe_for_checkpoint",
            "Hematochezia severa con checkpoint inhibitor (Path E gate 45)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_gi1"],
            help_text=(
                "Marcar 'Sí' ante sangrado digestivo low severo (hematochezia "
                "abundante, anemia ferropénica progresiva, transfusión RBC "
                "requerida) en contexto checkpoint inhibitor. Sospecha alta "
                "colitis severa hemorrágica. Activa gate 45 Path E — "
                "endoscopia urgente + valoración cirugía si refractario."
            ),
        ),
        FieldSpec(
            "colitis_resolved_for_checkpoint_inhibitor",
            "Colitis IO recuperada (override gate 45)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_gi1"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) CTCAE G≤1 documentada en 2 visitas "
                "separadas ≥7d, (2) calprotectina fecal <100 µg/g (marker "
                "objetivo recovery), (3) colonoscopia control SIN ulceración "
                "activa, (4) esteroides taper completado, (5) GI endorsement + "
                "monitoring quincenal × 3 meses. Desactiva gate 45."
            ),
        ),
        # ─── Gate 46: endocrinopathies irAE ───
        FieldSpec(
            "hypophysitis_documented_for_checkpoint",
            "Hipofisitis IO documentada (Path A gate 46)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_end1", "faje_jco_2018", "sznol_jco_2017"],
            help_text=(
                "Marcar 'Sí' si endocrinology documenta hipofisitis immune-related "
                "(panel TSH/T4/LH/FSH/cortisol AM/IGF-1/prolactina con déficits "
                "múltiples + MRI hipófisis con realce difuso/engrosamiento tallo). "
                "Combo nivo+ipi: 6-13% incidencia (vs 1.4-3.2% mono). Reemplazo "
                "hormonal IRREVERSIBLE típicamente. Activa gate 46 Path A."
            ),
        ),
        FieldSpec(
            "thyroiditis_ctcae_grade",
            "Grado CTCAE v5 de thyroiditis (Path B gate 46)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["keynote", "nccn_io_toxicity_2024_end1", "ctcae_v5"],
            help_text=(
                "Grado CTCAE v5.0 de thyroiditis immune-related (típicamente "
                "transitorio hipertiroidismo seguido de hipotiroidismo permanente "
                "en 80% casos). Gate 46 dispara con G≥3: crisis tiroidea, mixedema, "
                "hospitalización. KEYNOTE: thyroiditis 5-12% any grade, 0.5-1.5% G≥3. "
                "Reemplazo levotiroxina permanente en hipotiroidismo definitivo."
            ),
        ),
        FieldSpec(
            "diabetes_new_onset_for_checkpoint",
            "DM autoinmune nueva con checkpoint inhibitor (Path C gate 46)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_end1", "stamatouli_diabetes_2018"],
            help_text=(
                "Marcar 'Sí' ante diabetes mellitus nueva insulinodependiente "
                "(similar DM tipo 1) en contexto checkpoint inhibitor. Diagnóstico: "
                "glucosa + HbA1c + cetonas + péptido C bajo + anti-GAD/anti-IA2 "
                "puede ser positivo. Riesgo cetoacidosis diabética alta — "
                "insulina basal-bolus permanente requerida. Mortalidad sin "
                "reconocimiento 5-25%. Activa gate 46 Path C."
            ),
        ),
        FieldSpec(
            "adrenal_insufficiency_immune_for_checkpoint",
            "Insuficiencia adrenal IO documentada (Path D gate 46)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_end1", "sznol_jco_2017"],
            help_text=(
                "Marcar 'Sí' si endocrinology documenta insuficiencia adrenal "
                "immune-related (cortisol AM <3 µg/dL + ACTH alto = primaria; "
                "ACTH bajo = central por hipofisitis). Síntomas: hipotensión, "
                "náusea, vómito, hiponatremia, hiperkalemia (primaria). "
                "EMERGENCIA crisis adrenal (mortalidad 5-25%) — hidrocortisona "
                "100 mg IV STAT. Activa gate 46 Path D."
            ),
        ),
        FieldSpec(
            "tsh",
            "TSH (mIU/L) — Path E gate 46 hipotiroidismo nuevo",
            "number",
            default="",
            unit="mIU/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=200,
            allow_negative=False,
            evidence_tags=["nccn_io_toxicity_2024_end1"],
            help_text=(
                "TSH sérica en mIU/L (rango normal típico 0.4-4.5). Gate 46 "
                "dispara con TSH >10 mIU/L (hipotiroidismo claro). Pre-IO + "
                "monitoring cada 6 sem × 3 meses, luego trimestral. T4 libre "
                "complementario para distinguir primario vs central."
            ),
        ),
        FieldSpec(
            "cortisol_am",
            "Cortisol AM (µg/dL) — Path F gate 46 insuf adrenal",
            "number",
            default="",
            unit="µg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["nccn_io_toxicity_2024_end1"],
            help_text=(
                "Cortisol sérico AM 8-9h en µg/dL (rango normal 5-25). Gate 46 "
                "dispara con cortisol AM <3 µg/dL (sospecha alta insuficiencia "
                "adrenal — primaria si ACTH alto, central si bajo). Confirmar "
                "con estimulación ACTH (Cosyntropin 250 µg IV → cortisol 60 min "
                "<18 µg/dL = insuficiencia)."
            ),
        ),
        FieldSpec(
            "endocrinopathy_managed_with_replacement",
            "Endocrinopatía IO manejada con reemplazo hormonal (override gate 46)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_io_toxicity_2024_end1"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) reemplazo hormonal estable documentado "
                "≥4 sem (levotiroxina/hidrocortisona/insulina según déficit), "
                "(2) endocrinology endorsement explícito en HC, (3) paciente "
                "educado en signos crisis (cortisol stress dose si "
                "cirugía/infección/fiebre), (4) monitoring específico planeado "
                "(TSH trimestral, glucosa trimestral, electrolitos cada 3 meses), "
                "(5) medical alert bracelet recomendado (insuf adrenal + DM "
                "insulinodependiente). ⚠️ NO desactiva el gate completamente — "
                "endocrinopatías irAE típicamente IRREVERSIBLES; sirve como flag "
                "de manejo en curso para permitir continuación IO con precauciones."
            ),
        ),
        # ── Gate 47 — psa_flare_arpi_pseudoprogression (Faubot LVIII / #62) ──
        # 🆕 PRIMER gate informacional/anti-misinterpretation del catálogo
        # (severity="soft_warning" — NO bloquea ARPI, solo advierte clínico).
        FieldSpec(
            "psa_baseline_pre_arpi",
            "PSA baseline pre-inicio ARPI (ng/mL)",
            "number",
            default="",
            unit="ng/mL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10000,
            allow_negative=False,
            evidence_tags=["pcwg3_scher_jco_2016", "prevail", "titan", "spartan", "arasens"],
            help_text=(
                "PSA documentado INMEDIATAMENTE antes de iniciar ARPI. Necesario "
                "para Path A (rise ≥25%) y Path C (rise ≥50%) del gate."
            ),
        ),
        FieldSpec(
            "psa_change_percent_since_arpi_start",
            "Cambio % PSA desde inicio ARPI (Path A/C gate 47)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-100,
            max_value=10000,
            allow_negative=True,
            evidence_tags=["pcwg3_scher_jco_2016", "psa_flare_arpi"],
            help_text=(
                "Cambio % del PSA actual vs baseline pre-ARPI. Gate 47 dispara "
                "con elevación >25% (Path A si tiempo <9 sem + sin imagen "
                "progresión) o >50% (Path C si tiempo <5 sem). PSA flare típico "
                "ARPI: 25-100% above baseline en primeras 2-6 sem."
            ),
        ),
        FieldSpec(
            "psa_weeks_since_arpi_start",
            "Semanas desde inicio ARPI (Path A/C gate 47)",
            "number",
            default="",
            unit="semanas",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=520,
            allow_negative=False,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Semanas desde inicio ARPI. Gate 47 dispara con tiempo <9 sem "
                "(Path A) o <5 sem (Path C — flare clásico). Tiempo evaluación "
                "real progresión per PCWG3: ≥12 sem desde inicio ARPI."
            ),
        ),
        FieldSpec(
            "no_image_progression_documented",
            "Sin progresión imagen documentada durante PSA flare (Path A gate 47)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si CT/MRI/bone scan recientes NO muestran nuevas "
                "lesiones (RECIST 1.1 estable). Distingue PSA flare benigno de "
                "progresión REAL. Gate 47 Path A requiere AMBOS: PSA elevación "
                ">25% + tiempo <9 sem + sin imagen progresión."
            ),
        ),
        FieldSpec(
            "psa_flare_documented_first_month_arpi",
            "PSA flare ARPI documentado por urólogo/oncólogo (Path B gate 47)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016", "psa_flare_arpi"],
            help_text=(
                "Marcar 'Sí' si urólogo u oncólogo documentaron PSA flare en "
                "primer mes ARPI con interpretación clínica explícita ('PSA "
                "elevación transitoria compatible con flare ARPI, no progresión'). "
                "Activa gate 47 Path B."
            ),
        ),
        # ── Gate 48 — enzalutamide_hyponatremia_siadh (Faubot LIX / #58) ──
        # 🆕 PRIMER gate del catálogo para electrólitos críticos (Na/K).
        # Sienta arquitectura electrólitos preparada para futuros gates.
        FieldSpec(
            "sodium_serum",
            "Sodio sérico (mEq/L) — Path A/C gate 48",
            "number",
            default="",
            unit="mEq/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=80,
            max_value=200,
            allow_negative=False,
            evidence_tags=["prevail", "affirm", "xtandi_label_section_6", "ctcae_v5"],
            help_text=(
                "Sodio sérico en mEq/L (rango normal 135-145). Gate 48 dispara "
                "con Na <125 (Path A, CTCAE v5 G≥3 severo) o Na <120 (Path C, "
                "G≥4 emergencia neurológica — riesgo edema cerebral). PREVAIL+"
                "AFFIRM documentaron 1.0-1.6% G≥3 en enzalutamida (vs 0.4% "
                "placebo). Mortalidad sin reconocimiento 5-15% por edema cerebral."
            ),
        ),
        FieldSpec(
            "serum_osmolality",
            "Osmolaridad sérica (mOsm/kg) — Path B SIADH compound",
            "number",
            default="",
            unit="mOsm/kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=200,
            max_value=400,
            allow_negative=False,
            evidence_tags=["bartter_schwartz_1967", "verbalis_endocrine_society_2014"],
            help_text=(
                "Osmolaridad sérica medida o calculada (rango normal 280-300). "
                "Gate 48 Path B SIADH compound requiere osmolaridad sérica "
                "<270 mOsm/kg (hiposmolaridad) + osmolaridad urinaria >100 + "
                "euvolemia (criterios Bartter-Schwartz 1967). Cálculo: "
                "2×Na + glucosa/18 + BUN/2.8."
            ),
        ),
        FieldSpec(
            "urine_osmolality",
            "Osmolaridad urinaria (mOsm/kg) — Path B SIADH compound",
            "number",
            default="",
            unit="mOsm/kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=1500,
            allow_negative=False,
            evidence_tags=["bartter_schwartz_1967", "verbalis_endocrine_society_2014"],
            help_text=(
                "Osmolaridad urinaria spot (rango variable 50-1200 según "
                "hidratación). Gate 48 Path B SIADH requiere >100 mOsm/kg "
                "(orina inapropiadamente concentrada ante hipoosmolaridad "
                "sérica — falla supresión ADH). Criterio Bartter-Schwartz."
            ),
        ),
        FieldSpec(
            "euvolemia_documented_for_siadh",
            "Euvolemia documentada para SIADH (Path B gate 48)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bartter_schwartz_1967", "verbalis_endocrine_society_2014"],
            help_text=(
                "Marcar 'Sí' si exam clínico documenta volemia normal "
                "(euvolemia: turgor piel normal, mucosas húmedas, sin edema, "
                "presión venosa central normal, sin signos depleción ni "
                "sobrecarga). SIADH requiere euvolemia (vs depleción = "
                "hipovolemia hyponatremia, vs ICC/sirosis = hipervolemia "
                "hyponatremia). Activa gate 48 Path B compound (junto con "
                "osmolaridades anormales)."
            ),
        ),
        FieldSpec(
            "hyponatremia_siadh_documented_for_enzalutamide",
            "Hyponatremia/SIADH documentada por nefrólogo/endocrinólogo (Path D gate 48)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label_section_6", "verbalis_endocrine_society_2014"],
            help_text=(
                "Marcar 'Sí' si nephrology o endocrinology documentaron "
                "hyponatremia/SIADH atribuible a enzalutamida (mecanismo: "
                "enzalutamida cruza BBB + interactúa receptor V2 ADH "
                "hipofisario → secreción inadecuada ADH → retención hídrica "
                "→ hyponatremia dilucional). Activa gate 48 Path D "
                "independiente de los valores numéricos (paths A/B/C)."
            ),
        ),
        FieldSpec(
            "hyponatremia_resolved_for_enzalutamide",
            "Hyponatremia recuperada para enzalutamida (override gate 48)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["xtandi_label_section_6", "verbalis_endocrine_society_2014"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) Na ≥130 mEq/L documentado en 2 "
                "mediciones separadas ≥7d, (2) restricción hídrica documentada "
                "(800-1000 mL/d) o tolvaptán activo manteniendo Na normal, "
                "(3) causas alternativas descartadas (TSH normal + cortisol "
                "normal + sin SSRI/opioide/anti-epiléptico activo), "
                "(4) nephrology endorsement explícito en HC, (5) plan "
                "monitoring Na sérico SEMANAL × 4 sem post-reintroducción "
                "+ quincenal × 8 sem. ⚠️ NO override si G3 recurrente o "
                "cualquier evento G4 (Na <120) — discontinuación PERMANENTE."
            ),
        ),
        # ── Gate 49 — abiraterone_hypokalemia_grade3 (Faubot LX / #59) ──
        # 🆕 SEGUNDO gate del catálogo para electrólitos críticos —
        # completa eje Na+K junto con gate 48 (hyponatremia enzalutamida).
        FieldSpec(
            "potassium_serum",
            "Potasio sérico (mEq/L) — Path A/B/C gate 49",
            "number",
            default="",
            unit="mEq/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=1.5,
            max_value=8.0,
            allow_negative=False,
            evidence_tags=["cou_aa_302", "latitude", "zytiga_label_section_5_4", "ctcae_v5"],
            help_text=(
                "Potasio sérico en mEq/L (rango normal 3.5-5.0). Gate 49 "
                "dispara con K <3.0 (Path A, CTCAE v5 G≥3 severo), K <2.5 "
                "(Path B, G≥4 emergencia — riesgo torsades de pointes), "
                "o K <3.5 + HTA + alcalosis metabólica (Path C compound — "
                "pseudo-aldosteronismo). COU-AA-302+LATITUDE: 4-6% G≥3 en "
                "abiraterona vs <2% placebo. Mortalidad G≥3 ~3% por "
                "arritmias ventriculares. PROFILAXIS: prednisona 5-10 mg/d + "
                "considerar eplerenone 50 mg BID + KCl oral si K basal <4.0."
            ),
        ),
        FieldSpec(
            "hypertension_active_documented",
            "HTA activa documentada (Path C gate 49 pseudo-aldosteronismo)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["cou_aa_302", "latitude", "zytiga_label_section_5_4"],
            help_text=(
                "Marcar 'Sí' si HTA documentada en visita actual (PA "
                "sistólica >140 mmHg o diastólica >90 mmHg en ≥2 lecturas, "
                "o requiere tratamiento antihipertensivo activo). Componente "
                "del compound Path C (pseudo-aldosteronismo: hipokalemia + "
                "HTA + alcalosis metabólica). Coexiste con gate 3 HTA "
                "descontrolada. NO marcar 'Sí' si solo HTA controlada con "
                "medicación — debe ser activa en visita actual."
            ),
        ),
        FieldSpec(
            "metabolic_alkalosis_documented",
            "Alcalosis metabólica documentada (Path C gate 49)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["cou_aa_302", "latitude", "yamada_endocr_rev_2017"],
            help_text=(
                "Marcar 'Sí' si gasometría arterial o ionograma documenta "
                "alcalosis metabólica (HCO3 sérico >28 mEq/L o pH arterial "
                ">7.45 con HCO3 elevado). Componente del compound Path C "
                "(pseudo-aldosteronismo CYP17 inhibition). Mecanismo: "
                "activación MR → excreción H+ → alcalosis. Distinguir de "
                "alcalosis respiratoria (PaCO2 bajo, pH alto, HCO3 normal "
                "compensatorio)."
            ),
        ),
        FieldSpec(
            "hypokalemia_pseudoaldosteronism_documented_for_abiraterone",
            "Hipokalemia/pseudo-aldosteronismo documentado por especialista (Path D gate 49)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label_section_5_4", "yamada_endocr_rev_2017", "auchus_jco_2014"],
            help_text=(
                "Marcar 'Sí' si endocrinología, nefrología o cardiología "
                "documentaron pseudo-aldosteronismo atribuible a abiraterona "
                "(mecanismo: CYP17 inhibition → ↑DOC → activación receptor "
                "MR → retención Na + excreción K + excreción H+). Workup "
                "típico: aldosterona BAJA + renina BAJA + K bajo + HTA + "
                "alcalosis (vs hiperaldosteronismo primario: aldosterona "
                "ALTA + renina BAJA). Activa gate 49 Path D independiente "
                "de los valores numéricos (paths A/B/C)."
            ),
        ),
        FieldSpec(
            "hypokalemia_resolved_for_abiraterone",
            "Hipokalemia recuperada para abiraterona (override gate 49)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["zytiga_label_section_5_4", "asco_cardio_oncology_2024"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) K ≥3.5 mEq/L documentado en 2 "
                "mediciones separadas ≥7d, (2) suplementación oral KCl "
                "60-80 mEq/d activa, (3) eplerenone 50 mg BID o "
                "spironolactone 100 mg/d activos (antagonistas MR), "
                "(4) ECG baseline normal sin QT prolongation >500 ms, "
                "(5) cardiology endorsement explícito en HC, (6) plan "
                "monitoring K + ECG QUINCENAL × 4 sem post-reintroducción "
                "+ mensual × 8 sem. ⚠️ NO override si G3 recurrente o "
                "cualquier evento G4 (K <2.5) — discontinuación PERMANENTE "
                "por riesgo arritmia letal recurrente."
            ),
        ),
        # ── Gate 50 — bone_targeted_hypocalcemia_extended (Faubot LXI / #64) ──
        # 🆕 EXTIENDE gate 12 (Ra-223 limitado) → CLASE ENTERA bone-targeted
        # (Ra-223 + Lu-177 + denosumab + bisfosfonatos). Sienta categoría
        # bone-modifying agents completa.
        FieldSpec(
            "ionized_calcium_mmol_l",
            "Calcio ionizado (mmol/L) — Path C gate 50 (gold standard)",
            "number",
            default="",
            unit="mmol/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0.5,
            max_value=2.0,
            allow_negative=False,
            evidence_tags=["asco_bone_health_2024", "henry_jco_2011", "fizazi_lancet_2011", "ctcae_v5"],
            help_text=(
                "Calcio ionizado en mmol/L (rango normal 1.10-1.30). Gate 50 "
                "Path C dispara con Ca ionizado <1.0 mmol/L (≈ Ca total <8.0 "
                "mg/dL en paciente normoalbumineémico). Ca ionizado es GOLD "
                "STANDARD — NO afectado por albúmina sérica (vs Ca total que "
                "requiere corrección por albúmina si hipoalbuminemia). Rango "
                "convertir a mg/dL: 1 mmol/L = 4.0 mg/dL."
            ),
        ),
        FieldSpec(
            "chvostek_sign_positive",
            "Signo de Chvostek positivo (Path D gate 50 tetania)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_bone_health_2024", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' si percusión nervio facial pre-auricular induce "
                "contracción ipsilateral muscular facial (signo Chvostek "
                "positivo). Indicador clínico de hipocalcemia + tetania "
                "latente. Componente del compound Path D (Chvostek + "
                "Trousseau + parestesias periorales = patognomónico)."
            ),
        ),
        FieldSpec(
            "trousseau_sign_positive",
            "Signo de Trousseau positivo (Path D gate 50 tetania)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_bone_health_2024", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' si insuflación esfigmomanómetro 20 mmHg sobre "
                "presión sistólica × 3 min induce espasmo carpopedal (mano "
                "obstétrica — signo Trousseau positivo). Más sensible y "
                "específico que Chvostek. Componente compound Path D gate 50."
            ),
        ),
        FieldSpec(
            "perioral_paresthesias_documented",
            "Parestesias periorales/digitales documentadas (Path D gate 50)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_bone_health_2024", "ctcae_v5"],
            help_text=(
                "Marcar 'Sí' si paciente reporta parestesias periorales "
                "(hormigueo alrededor de boca) o digitales (manos/pies). "
                "Síntoma temprano hipocalcemia + tetania latente. "
                "Componente compound Path D gate 50 (junto con Chvostek + "
                "Trousseau positivos)."
            ),
        ),
        FieldSpec(
            "hypocalcemia_documented_for_bone_targeted",
            "Hipocalcemia documentada por especialista (Path E gate 50)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_bone_health_2024", "henry_jco_2011", "fizazi_lancet_2011"],
            help_text=(
                "Marcar 'Sí' si endocrinology, oncology o nephrology "
                "documentaron hipocalcemia atribuible a bone-targeted agent "
                "(Ra-223/Lu-177/denosumab/bisfosfonato). Distintivo: PTH "
                "elevada secundaria + 25-OH-vitD frecuentemente bajo "
                "(<30 ng/mL). Activa gate 50 Path E independiente de los "
                "valores numéricos (paths A/B/C/D)."
            ),
        ),
        FieldSpec(
            "hypocalcemia_resolved_for_bone_targeted",
            "Hipocalcemia recuperada para bone-targeted (override gate 50)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_bone_health_2024", "esmo_bone_health_2024"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) Ca corregido ≥8.5 mg/dL "
                "documentado en 2 mediciones separadas ≥7d, (2) 25-OH-vitD "
                "≥30 ng/mL documentado, (3) suplementación oral Ca "
                "1000-1200 mg/d + vitD 2000-5000 IU/d activa, (4) sin "
                "tetania clínica (Chvostek/Trousseau negativos), "
                "(5) endocrinology endorsement explícito en HC, (6) plan "
                "monitoring Ca + PTH + 25-OH-vitD QUINCENAL × 8 sem "
                "post-reintroducción. ⚠️ NO override si G3 recurrente o "
                "cualquier evento G4 (Ca <7.0) — discontinuación PERMANENTE "
                "por riesgo tetania/arritmia letal recurrente."
            ),
        ),
        # ── Gate 51 — bone_targeted_osteonecrosis_jaw (Faubot LXII / #65) ──
        # 🆕 SEGUNDO gate del catálogo en categoría bone-targeted (post #64).
        # Continúa categoría bone-modifying agents iniciada en #64.
        FieldSpec(
            "osteonecrosis_jaw_documented",
            "ONJ documentado por oral surgery (Path A gate 51)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "asco_bone_health_2024", "ruggiero_joms_2014"],
            help_text=(
                "Marcar 'Sí' si oral surgery o maxilofacial documentaron "
                "ONJ (Osteonecrosis of the Jaw) per criterios AAOMS 2022 "
                "(cualquier estadio 1-3): hueso expuesto en mandíbula/maxila "
                "O fístula intra/extraoral persistente >8 semanas + sin "
                "radiación H&N previa + sin metástasis mandibular evidente. "
                "Activa gate 51 Path A — DISCONTINUACIÓN bone-targeted "
                "INMEDIATA + consulta oral surgery URGENTE."
            ),
        ),
        FieldSpec(
            "oral_exposed_bone_documented",
            "Hueso expuesto oral documentado (Path B gate 51 compound)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "ruggiero_joms_2014"],
            help_text=(
                "Marcar 'Sí' si exam oral documenta hueso expuesto en "
                "mandíbula o maxila (visualmente o vía sondaje fistula "
                "intra/extraoral). Componente compound Path B (junto con "
                "duración >8 semanas — distingue ONJ de osteítis reactiva "
                "post-extracción típicamente <8 sem)."
            ),
        ),
        FieldSpec(
            "oral_exposed_bone_duration_weeks",
            "Duración hueso expuesto oral (semanas) — Path B gate 51",
            "number",
            default="",
            unit="semanas",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=520,
            allow_negative=False,
            evidence_tags=["aaoms_2022"],
            help_text=(
                "Número de semanas desde detección hueso expuesto. Gate 51 "
                "Path B compound dispara con duración >8 semanas (criterio "
                "diagnóstico AAOMS 2022 classic — distingue ONJ persistente "
                "de osteítis reactiva post-extracción dental que suele curar "
                "espontáneamente en <8 sem)."
            ),
        ),
        FieldSpec(
            "oral_exposed_bone_or_fistula_documented",
            "Hueso expuesto O fístula oral documentada (Path C gate 51)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "ruggiero_joms_2014"],
            help_text=(
                "Marcar 'Sí' si exam oral documenta hueso expuesto O "
                "fístula intraoral/extraoral que sondea hasta hueso. "
                "Componente compound Path C AAOMS stage 2+ (junto con "
                "síntomas + sin radiación H&N previa)."
            ),
        ),
        FieldSpec(
            "jaw_pain_or_infection_symptoms_documented",
            "Síntomas mandibulares (dolor/infección) documentados (Path C gate 51)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "ruggiero_joms_2014"],
            help_text=(
                "Marcar 'Sí' si paciente reporta síntomas mandibulares: "
                "dolor mandibular crónico + signos infección local "
                "(eritema, edema, supuración, halitosis). Componente "
                "compound Path C (junto con hueso expuesto/fístula + "
                "sin radiación H&N previa)."
            ),
        ),
        FieldSpec(
            "no_prior_head_neck_radiation",
            "Sin radiación cabeza/cuello previa (Path C gate 51 — exclusión osteorradionecrosis)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "ruggiero_joms_2014"],
            help_text=(
                "Marcar 'Sí' si paciente NO ha recibido radioterapia a "
                "cabeza/cuello (criterio diagnóstico AAOMS 2022 para excluir "
                "osteorradionecrosis — entidad distinta con mecanismo "
                "vascular, no medication-related). Componente compound Path C. "
                "NB: marcar 'No' si paciente tiene historia RT H&N — esto "
                "EXCLUYE diagnóstico ONJ (es osteorradionecrosis)."
            ),
        ),
        FieldSpec(
            "onj_stage_3_severe_documented",
            "ONJ stage 3 severo documentado (Path D gate 51 — emergencia)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "khan_jbmr_2015"],
            help_text=(
                "Marcar 'Sí' si oral surgery documenta ONJ AAOMS stage 3 "
                "severo: hueso expuesto + ≥1 de (fistulas extraorales, "
                "osteolisis extendida hasta cortical inferior, fractura "
                "patológica mandibular, osteomielitis profunda, "
                "comunicación oroantral/oronasal). EMERGENCIA QUIRÚRGICA — "
                "consulta maxilofacial urgente, posible resección "
                "segmentaria mandibular o hemimaxilectomía. Mortalidad ~3% "
                "por sepsis. Activa gate 51 Path D — DISCONTINUACIÓN "
                "PERMANENTE bone-targeted."
            ),
        ),
        FieldSpec(
            "onj_resolved_for_bone_targeted",
            "ONJ recuperado para bone-targeted (override gate 51)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aaoms_2022", "asco_bone_health_2024"],
            help_text=(
                "Marcar 'Sí' SOLO si: (1) resolución completa AAOMS stage 0 "
                "documentada (sin hueso expuesto + sin fistulas + sin "
                "síntomas + healing completo de mucosa oral), (2) dental "
                "clearance post-resolución completo (panorámica + exam "
                "periodontal sin lesiones activas), (3) 25-OH-vitD ≥30 "
                "ng/mL + Ca normales (descartar hipocalcemia secundaria — "
                "gate 50 monitor), (4) oral surgery endorsement explícito "
                "en HC, (5) consideración cambio a bone-targeted ALTERNATIVO "
                "per ASCO Bone Health 2024 (denosumab→bisfos PO o viceversa). "
                "⚠️ NO override si ONJ stage 3 recurrente o cualquier ONJ "
                "que requiera >12 meses para resolución — discontinuación "
                "PERMANENTE por riesgo recurrencia + complicaciones "
                "quirúrgicas mayores."
            ),
        ),
        # ── Gate 52 — parp_inhibitor_mds_aml_longitudinal (Faubot LXIII / #66) ──
        # 🆕 SEXTO gate longitudinal del catálogo (post niraparib gate 33,
        # docetaxel gate 34, abi gate 39, Lu-177 gate 40, cabazitaxel gate 41).
        # Cubre MDS/AML EMERGENTE durante tratamiento PARPi (vs gate 16 que
        # cubre history pre-tratamiento).
        FieldSpec(
            "mds_or_aml_documented_during_parpi",
            "MDS/AML emergente durante PARPi documentado (Path A gate 52)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["magnitude_chi_nejm_2023", "profound_de_bono_nejm_2020", "morton_jco_2019", "lynparza_label_section_5_1"],
            help_text=(
                "Marcar 'Sí' si hematology documentó MDS o AML EMERGENTE "
                "durante tratamiento PARPi (no antecedente pre-tratamiento — "
                "ese caso está cubierto por gate 16). Datos prevalencia: "
                "olaparib 0.5-1.5%, niraparib 1.4-2.3%, talazoparib 0.8-1.8%, "
                "rucaparib 0.7-1.5%. Tiempo medio aparición 18-32 meses "
                "post-inicio PARPi. **Mortalidad MDS post-PARP ~25-50%** "
                "(peor pronóstico que MDS de novo). Activa gate 52 Path A — "
                "DISCONTINUACIÓN PERMANENTE PARPi inmediata."
            ),
        ),
        FieldSpec(
            "cytopenia_two_or_more_lines_documented",
            "Cytopenia ≥2 líneas documentada (Path B gate 52 compound)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_2022_classification", "ipss_r_2012"],
            help_text=(
                "Marcar 'Sí' si CBC documenta citopenia en ≥2 líneas: "
                "Hb <10 g/dL + plt <100K + ANC <1500 (al menos 2 de 3). "
                "Componente compound Path B (junto con persistencia >12 sem + "
                "sospecha clínica). Bicitopenia/pancitopenia persistente "
                "inexplicada en paciente PARPi = sospecha alta MDS emergente."
            ),
        ),
        FieldSpec(
            "cytopenia_duration_weeks",
            "Duración citopenia (semanas) — Path B gate 52",
            "number",
            default="",
            unit="semanas",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=520,
            allow_negative=False,
            evidence_tags=["who_2022_classification", "magnitude_chi_nejm_2023"],
            help_text=(
                "Número de semanas con citopenia ≥2 líneas persistente. "
                "Gate 52 Path B compound dispara con duración >12 semanas "
                "(criterio per WHO 2022 + MAGNITUDE subset analysis — "
                "distingue citopenia transitoria post-PARPi mielosupresión "
                "esperada de citopenia persistente sospechosa de MDS "
                "secundaria emergente)."
            ),
        ),
        FieldSpec(
            "hematologic_malignancy_suspected_for_parpi",
            "Sospecha clínica MDS/AML para PARPi (Path B gate 52)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_2022_classification", "csizmar_jco_2024"],
            help_text=(
                "Marcar 'Sí' si oncology o hematology documentaron sospecha "
                "clínica fuerte MDS/AML emergente atribuible a PARPi "
                "(workup en curso pero diagnóstico no confirmado aún). "
                "Componente compound Path B (junto con citopenia ≥2 líneas + "
                "persistencia >12 sem). Sienta criterio para suspender "
                "PARPi durante workup definitivo BMA."
            ),
        ),
        FieldSpec(
            "bone_marrow_dysplasia_documented",
            "Displasia medular documentada en BMA (Path C gate 52 compound MDS)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_2022_classification", "ipss_r_2012"],
            help_text=(
                "Marcar 'Sí' si BMA (aspirado de médula ósea) documenta "
                "displasia morfológica en ≥1 línea (eritropoyética, "
                "granulopoyética, megacariocítica). Componente compound "
                "Path C (junto con blasts BMA 5-19%). Criterio diagnóstico "
                "WHO 2022 MDS clásico. Cariotipo + FISH + NGS panel "
                "complementarios (TP53, RUNX1, ASXL1, DNMT3A, TET2)."
            ),
        ),
        FieldSpec(
            "bone_marrow_blasts_percent",
            "Blastos en médula ósea o sangre periférica (%) — Path C/D gate 52",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["who_2022_classification"],
            help_text=(
                "Porcentaje de blastos en médula ósea (BMA) o sangre "
                "periférica (PB). Gate 52 dispara con: blasts >5% (Path C "
                "MDS compound — junto con displasia morfológica), o blasts "
                "≥20% (Path D AML — emergencia oncohematológica). Rango "
                "normal BMA: <5%. WHO 2022 cutoffs: <5% normal/MDS-EB-0, "
                "5-19% MDS-EB-1/MDS-EB-2, ≥20% AML."
            ),
        ),
        FieldSpec(
            "mds_aml_remission_for_parpi",
            "MDS/AML en remisión completa para PARPi (override gate 52)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_2022_classification", "iwg_2018"],
            help_text=(
                "Marcar 'Sí' SOLO en escenarios EXCEPCIONALES si: (1) "
                "remisión completa documentada post-tratamiento intensivo "
                "MDS/AML (CR per IWG 2018: blasts <5% + recuperación CBC + "
                "sin transfusión-dependencia), (2) hematology clearance "
                "explícito en HC con justificación clínica multidisciplinaria, "
                "(3) CBC normal estable ≥6 meses, (4) **considerar SIEMPRE "
                "transición a regímenes NO-PARPi primero** (taxanos, ARSI, "
                "Lu-177-PSMA, abiraterona). ⚠️ Override raro — mayoría de "
                "casos requieren discontinuación PERMANENTE PARPi por "
                "riesgo recurrencia."
            ),
        ),
        # ── Gates 53/54/55 — PSA Kinetics (Faubot LXIV / #63A) ──
        # 🆕 PRIMER trio gates PSA kinetics post-RP/RT/m0CRPC.
        # Sienta categoría kinetics PSA — todos severity=soft_warning
        # (informacional/anti-misinterpretation per pattern gate 47).
        # ─── Gate 53: BCR aggressive post-RP ───
        FieldSpec(
            "psa_doubling_time_months",
            "PSA Doubling Time (PSADT) en meses — Path A gates 53/55",
            "number",
            default="",
            unit="meses",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0.1,
            max_value=120,
            allow_negative=False,
            evidence_tags=["stephenson_jco_2009", "spartan_smith_nejm_2018", "prosper_hussain_nejm_2018", "aramis_fizazi_nejm_2019"],
            help_text=(
                "PSA Doubling Time (PSADT) en meses. Cálculo per Saad JCO 2017 "
                "metodología robust (≥3 mediciones PSA separadas ≥4 sem). "
                "Gate 53 dispara con PSADT <3m post-RP (BCR agresivo, "
                "Stephenson JCO 2009 — mortalidad cáncer-específica 50% 5 años). "
                "Gate 55 dispara con PSADT ≤10m en m0CRPC (criterio "
                "SPARTAN/PROSPER/ARAMIS pivotal para iniciar ARPI). PSADT ≤8m + "
                "castrate confirmed = criterio agresivo (mayor urgencia)."
            ),
        ),
        FieldSpec(
            "psa_velocity_ng_ml_year",
            "PSA Velocity (ng/mL/año) — Path B gate 53",
            "number",
            default="",
            unit="ng/mL/año",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=1000,
            allow_negative=False,
            evidence_tags=["stephenson_jco_2009", "freedland_jama_2005"],
            help_text=(
                "PSA Velocity en ng/mL/año (cambio absoluto PSA por unidad "
                "tiempo). Cálculo: (PSA_actual - PSA_previo) / tiempo_años. "
                "Gate 53 dispara con velocity >2 ng/mL/año + PSA >0.5 + "
                "post-RP (criterio Stephenson JCO 2009 — predictor metástasis "
                "HR 4.5)."
            ),
        ),
        FieldSpec(
            "prior_radical_prostatectomy_documented",
            "Prostatectomía radical previa documentada (Path A/B gate 53)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["stephenson_jco_2009", "eau_2026_section_6_4_1"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia documentada de "
                "prostatectomía radical (RP) — abierta, laparoscópica o "
                "robótica. Componente de paths A y B gate 53 (BCR aggressive). "
                "Distingue BCR post-RP (Stephenson criteria) de BCR post-RT "
                "(Phoenix criteria, gate 54)."
            ),
        ),
        FieldSpec(
            "bcr_high_risk_aggressive_documented",
            "BCR de alto riesgo agresivo documentado (Path C gate 53)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["stephenson_jco_2009", "rtog_9601_shipley_nejm_2017"],
            help_text=(
                "Marcar 'Sí' si urology/oncology documentó BCR (Recurrencia "
                "Bioquímica) de alto riesgo agresivo post-RP basado en "
                "criterios clínicos integrados (PSADT corto + Gleason ≥8 + "
                "tiempo a BCR <18m). Activa gate 53 Path C — recomendación "
                "salvage RT urgente + ADT 24 meses (RTOG-9601)."
            ),
        ),
        FieldSpec(
            "bcr_aggressive_treated_for_salvage",
            "BCR agresivo bajo salvage RT activo (override gate 53)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["getug_afu_16_carrie_lancet_oncol_2016", "rtog_9601"],
            help_text=(
                "Marcar 'Sí' si paciente ya está bajo salvage RT activo + "
                "ADT concurrente per protocolo GETUG-AFU-16 (6 meses ADT) o "
                "RTOG-9601 (24 meses bicalutamida) + radiation oncology "
                "endorsement explícito en HC. Desactiva gate 53 (paciente "
                "ya recibiendo intervención recomendada)."
            ),
        ),
        # ─── Gate 54: PSA bounce post-RT ───
        FieldSpec(
            "psa_rise_above_nadir_ng_ml",
            "PSA rise above nadir (ng/mL) — Path A gate 54",
            "number",
            default="",
            unit="ng/mL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=200,
            allow_negative=False,
            evidence_tags=["crook_ijrobp_2010", "phoenix_2006_roach"],
            help_text=(
                "PSA elevation sobre el nadir documentado post-RT. Cálculo: "
                "PSA_actual - PSA_nadir. Gate 54 Path A dispara con elevation "
                "<2 ng/mL above nadir + tiempo post-RT 12-30m + sin imagen "
                "progresión (probable bounce, NO BCR Phoenix). Phoenix BCR "
                "criterion (Roach RTOG-ASTRO 2006): elevation ≥2 ng/mL above "
                "nadir confirma BCR REAL."
            ),
        ),
        FieldSpec(
            "months_post_rt",
            "Meses desde fin de radioterapia — Path A gate 54",
            "number",
            default="",
            unit="meses",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=600,
            allow_negative=False,
            evidence_tags=["crook_ijrobp_2010", "kuban_ijrobp_2003"],
            help_text=(
                "Meses transcurridos desde fin de radioterapia (EBRT o "
                "braquiterapia). Gate 54 Path A compound dispara con tiempo "
                "12-30 meses (ventana típica PSA bounce per Crook IJROBP "
                "2010 + Kuban IJROBP 2003). Fuera de ventana 12-30m → "
                "elevation más probable BCR real (gate NO dispara)."
            ),
        ),
        FieldSpec(
            "psa_bounce_documented_post_rt",
            "PSA bounce post-RT documentado por especialista (Path B gate 54)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["crook_ijrobp_2010", "pickles_ijrobp_2011"],
            help_text=(
                "Marcar 'Sí' si urology o radiation oncology documentaron "
                "PSA bounce post-RT con interpretación clínica explícita "
                "('elevation transitoria compatible con bounce, NO BCR "
                "Phoenix per Crook IJROBP 2010'). Activa gate 54 Path B "
                "independiente de los valores numéricos (paths A/C)."
            ),
        ),
        FieldSpec(
            "psa_elevation_unconfirmed_post_rt",
            "PSA elevation NO confirmada por 2da medición ≥3m post-RT (Path C gate 54)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si la PSA elevation post-RT NO ha sido confirmada "
                "por 2da medición separada ≥3 meses (criterio PCWG3 Scher "
                "JCO 2016 para confirmar progresión real). Sin confirmación, "
                "elevation puede ser bounce transitorio o variabilidad ensayo. "
                "Gate 54 Path C alerta esperar 2da medición antes de salvage."
            ),
        ),
        # ─── Gate 55: PSADT progressive m0CRPC ARPI eligibility ───
        FieldSpec(
            "m0_crpc_state_confirmed",
            "Estado m0CRPC confirmado (Path A gate 55)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spartan_smith_nejm_2018", "prosper_hussain_nejm_2018", "aramis_fizazi_nejm_2019"],
            help_text=(
                "Marcar 'Sí' si estado m0CRPC (no metastatic Castration-"
                "Resistant Prostate Cancer) está confirmado: PSA progressing "
                "+ testosterona <50 ng/dL + sin metástasis evidentes en "
                "imagen (idealmente PSMA PET/CT — más sensible que CT/bone "
                "scan a PSA <2 ng/mL). Activa gate 55 Path A + B compound "
                "(criterio inclusión ensayos pivote SPARTAN/PROSPER/ARAMIS)."
            ),
        ),
        FieldSpec(
            "castrate_testosterone_status_confirmed",
            "Castrate testosterone status confirmado <50 ng/dL (Path B gate 55)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eau_2026_section_6_5_4"],
            help_text=(
                "Marcar 'Sí' si testosterona sérica documentada <50 ng/dL "
                "(idealmente <20 ng/dL per EAU 2026 §6.5.4). Confirma estado "
                "castración medicamentosa o quirúrgica. Componente compound "
                "Path B gate 55 (criterio agresivo PSADT ≤8m + castrate)."
            ),
        ),
        FieldSpec(
            "no_active_arpi_for_m0_crpc",
            "Sin ARPI activo actualmente (Path A/B gate 55)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spartan_smith_nejm_2018", "prosper_hussain_nejm_2018", "aramis_fizazi_nejm_2019"],
            help_text=(
                "Marcar 'Sí' si paciente NO está actualmente bajo ARPI "
                "(apalutamida/enzalutamida/darolutamida) — ARPI naive. "
                "Componente compound paths A/B gate 55 (gate alerta urgencia "
                "iniciar ARPI per criterios pivotales). Si paciente ya bajo "
                "ARPI activo, usar override `arpi_already_initiated_for_m0_crpc`."
            ),
        ),
        FieldSpec(
            "psadt_progressive_for_arpi_eligibility",
            "PSADT progresivo para elegibilidad ARPI documentado (Path C gate 55)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spartan_smith_nejm_2018", "nccn_pros_g_v5_2026_m0crpc"],
            help_text=(
                "Marcar 'Sí' si urology/oncology documentaron PSADT progresivo "
                "que cumple criterios m0CRPC + elegibilidad ARPI per ensayos "
                "pivote (SPARTAN/PROSPER/ARAMIS). Activa gate 55 Path C "
                "independiente de los valores numéricos paths A/B."
            ),
        ),
        FieldSpec(
            "arpi_already_initiated_for_m0_crpc",
            "ARPI ya iniciado para m0CRPC (override gate 55)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spartan_smith_nejm_2018"],
            help_text=(
                "Marcar 'Sí' si paciente ya está bajo apalutamida (Erleada) o "
                "enzalutamida (Xtandi) o darolutamida (Nubeqa) activo para "
                "manejo m0CRPC. Desactiva gate 55 (ARPI ya iniciado per "
                "recomendación pivotal)."
            ),
        ),
        # ── Gates 56-60 — RP vs RT Subspecialty (Faubot LXXV / #67A) ──
        # 🆕 Anticoag + IBD + prior pelvic RT + TURP + SVI risk fields para
        # decisión RP vs RT vs AS subespecialista.
        # ─── Gate 56: Anticoagulant + RP bleeding risk ───
        FieldSpec(
            "anticoagulant_agent",
            "Anticoagulante activo (Path A gate 56)",
            "select",
            options=["Desconocido", "none", "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban", "aspirin", "clopidogrel", "ticagrelor", "prasugrel", "enoxaparin", "fondaparinux", "other"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_3_v5_2026", "asco_perioperative_anticoag_2023"],
            help_text=(
                "Agente anticoagulante/antiagregante actual del paciente. "
                "Path A gate 56 dispara con cualquier valor != 'none' + "
                "decisión RP activa (riesgo sangrado PLND ≥4× per NCCN). "
                "Si DOAC/warfarin: requiere bridging perioperatorio. "
                "Si DAPT: contraindicación relativa fuerte → favorecer RT."
            ),
        ),
        FieldSpec(
            "anticoagulant_indication",
            "Indicación clínica del anticoagulante (gate 56)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_perioperative_anticoag_2023", "nccn_pros_3_v5_2026"],
            help_text=(
                "Indicación clínica (ej. fibrilación atrial CHA2DS2-VASc 4, "
                "TVP/TEP previa, válvula mecánica, stent coronario reciente). "
                "Crítico para evaluar viabilidad bridging perioperatorio o "
                "preferencia RT que evita interrupción anticoagulación."
            ),
        ),
        FieldSpec(
            "dual_antiplatelet_therapy",
            "Terapia antiagregante dual (DAPT) activa (Path A gate 56)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_perioperative_anticoag_2023"],
            help_text=(
                "Marcar 'Sí' si paciente bajo DAPT (aspirin + clopidogrel/ticagrelor/prasugrel) "
                "típicamente post-stent coronario reciente (<12m DES, <1m BMS). "
                "Componente Path A gate 56 — riesgo sangrado RP/PLND prohibitivo. "
                "Diferir RP o preferir RT."
            ),
        ),
        FieldSpec(
            "high_bleeding_risk_documented_pre_rp",
            "Alto riesgo sangrado pre-RP documentado (Path B gate 56)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_3_v5_2026"],
            help_text=(
                "Marcar 'Sí' si urology/hematology documentaron alto riesgo "
                "sangrado pre-RP (HAS-BLED ≥3, trombocitopatía, vWf disease, "
                "hemofilia, etc.). Activa gate 56 Path B — favorecer RT."
            ),
        ),
        # ─── Gate 57: IBD active + Pelvic RT contraindication ───
        FieldSpec(
            "inflammatory_bowel_disease_active",
            "Estado IBD (Inflammatory Bowel Disease) (Path A gate 57)",
            "select",
            options=["Desconocido", "none", "history_inactive", "active_mild", "active_moderate", "active_severe", "post_colectomy"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_ibd_radiation_2023", "eau_2026_section_8_2"],
            help_text=(
                "Estado actual de IBD (Crohn / Ulcerative Colitis / IBD-U). "
                "Path A gate 57 dispara con 'active_mild/moderate/severe' + "
                "decisión RT pélvica activa (NCCN — IBD activa contraindicación "
                "relativa para RT pélvica por toxicidad GI severa)."
            ),
        ),
        FieldSpec(
            "ibd_active_flare_documented",
            "Brote IBD activo documentado (Path B gate 57)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_ibd_radiation_2023"],
            help_text=(
                "Marcar 'Sí' si gastroenterology documentó brote IBD activo "
                "(endoscopy + biopsia). Path B gate 57 — RT pélvica diferir "
                "hasta remisión inducida."
            ),
        ),
        FieldSpec(
            "pelvic_rt_contraindicated_by_ibd",
            "RT pélvica contraindicada por IBD documentada (Path C gate 57)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_ibd_radiation_2023", "eau_2026_section_8_2"],
            help_text=(
                "Marcar 'Sí' si MDT documentó RT pélvica contraindicada por "
                "IBD (típicamente IBD severa/perianal + history fistulas). "
                "Activa gate 57 hard_block — favorecer RP o ARPI sistémico."
            ),
        ),
        # ─── Gate 58: Prior pelvic RT + Re-irradiation contraindication ───
        FieldSpec(
            "prior_pelvic_radiation",
            "Radioterapia pélvica previa (Path A gate 58)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eau_2026_section_8_2", "qutob_re_irradiation_2022"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia de RT pélvica previa "
                "por cualquier causa (PCa primario, vejiga, recto, cervix, etc.). "
                "Path A gate 58 — re-irradiación pélvica curativa contraindicada "
                "por dosis acumulada órganos riesgo (recto, vejiga)."
            ),
        ),
        FieldSpec(
            "prior_pelvic_rt_intent",
            "Intent RT pélvica previa (gate 58 contexto)",
            "select",
            options=["Desconocido", "curative", "adjuvant", "salvage", "palliative"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["qutob_re_irradiation_2022", "eau_2026_section_8_2"],
            help_text=(
                "Intent RT pélvica previa para contextualizar gate 58. "
                "RT curativa previa = dosis acumulada típicamente prohibitiva. "
                "RT paliativa previa = dosis menor, posible re-RT con cuidado."
            ),
        ),
        FieldSpec(
            "re_irradiation_pelvic_contraindicated",
            "Re-irradiación pélvica contraindicada documentada (Path B gate 58)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["qutob_re_irradiation_2022"],
            help_text=(
                "Marcar 'Sí' si radiation oncology documentó re-irradiación "
                "pélvica curativa contraindicada. Activa gate 58 hard_block — "
                "favorecer RP salvage, ARPI sistémico o focal therapy."
            ),
        ),
        FieldSpec(
            "salvage_re_rt_protocol_documented",
            "Protocolo re-RT salvataje aprobado (override gate 58)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["qutob_re_irradiation_2022"],
            help_text=(
                "Marcar 'Sí' si MDT aprobó protocolo re-RT salvataje (ej. SBRT "
                "ultra-focal, brachy salvage post-EBRT) con dosimetría que "
                "respeta tolerancia órganos riesgo. Override gate 58."
            ),
        ),
        FieldSpec(
            "palliative_intent_documented",
            "Intent paliativo RT documentado (override gate 58)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["qutob_re_irradiation_2022"],
            help_text=(
                "Marcar 'Sí' si re-RT pélvica con intent paliativo (control síntomas, "
                "no curación). Override gate 58 — dosis menores, riesgo aceptable."
            ),
        ),
        # ─── Gate 59: TURP history + Brachytherapy contraindication ───
        FieldSpec(
            "history_of_turp",
            "Historia de TURP (Resección Transuretral Próstata) (Path A gate 59)",
            "select",
            options=["Desconocido", "never", "long_ago_>5yr", "recent_2_5yr", "recent_<2yr", "multiple"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aapm_tg_137_brachytherapy", "abs_brachy_consensus_2020"],
            help_text=(
                "Historia de TURP (resección transuretral próstata) por HBP. "
                "Path A gate 59 dispara con 'recent_<2yr/recent_2_5yr/multiple' + "
                "decisión brachy LDR/HDR activa (AAPM TG-137 — TURP previo "
                "complica setup brachy, ↑ riesgo retención urinaria/fistula)."
            ),
        ),
        FieldSpec(
            "turp_volume_resected_cc",
            "Volumen resecado en TURP (cc) (Path A gate 59)",
            "number",
            default="",
            unit="cc",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=200,
            allow_negative=False,
            evidence_tags=["aapm_tg_137_brachytherapy"],
            help_text=(
                "Volumen prostático resecado en TURP previo (cc). Path A gate "
                "59 dispara con valor >30cc (cavidad significativa post-TURP "
                "complica brachy seed placement)."
            ),
        ),
        FieldSpec(
            "post_turp_retention_symptoms",
            "Síntomas retención urinaria post-TURP (Path B gate 59)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aapm_tg_137_brachytherapy"],
            help_text=(
                "Marcar 'Sí' si paciente desarrolló retención urinaria persistente "
                "post-TURP. Path B gate 59 — brachy ↑ severamente riesgo retención "
                "post-implant en estos pacientes."
            ),
        ),
        FieldSpec(
            "brachytherapy_contraindicated_by_turp",
            "Brachytherapy contraindicada por TURP documentada (Path C gate 59)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aapm_tg_137_brachytherapy", "abs_brachy_consensus_2020"],
            help_text=(
                "Marcar 'Sí' si brachy specialist documentó brachy LDR/HDR "
                "contraindicada por TURP previo. Activa gate 59 hard_block — "
                "favorecer EBRT-IMRT o SBRT."
            ),
        ),
        # ─── Gate 60: SVI risk nomogram (MSKCC) ───
        FieldSpec(
            "svi_risk_nomogram_percent",
            "SVI Risk Nomogram (MSKCC) — riesgo invasión vesículas seminales (%)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["mskcc_svi_nomogram", "grubbs_ijrobp_2016"],
            help_text=(
                "Probabilidad calculada de invasión de vesículas seminales (SVI) "
                "per nomogram MSKCC (calculate_svi_risk_nomogram en clinical_scores.py). "
                "Path A gate 60 dispara con valor >30% — RP monoterapia sub-óptima "
                "(positive margins probables, ADT post-op casi obligatoria) — "
                "favorecer RT+ADT multimodal."
            ),
        ),
        FieldSpec(
            "svi_risk_high_documented",
            "SVI alto riesgo clínicamente documentado (Path B gate 60)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["grubbs_ijrobp_2016"],
            help_text=(
                "Marcar 'Sí' si urology/MDT documentaron clínicamente SVI alto "
                "riesgo (mpMRI sospecha + Gleason ≥4+3 + cT2c/T3a + PSA >20). "
                "Activa gate 60 — recomienda RT+ADT preferencia vs RP."
            ),
        ),
        # ── Gates 61-65 — Genomic Critical Gates (Faubot LXXVI / #67B) ──
        # 🆕 HRR/AR-V7/CDK12/HRD/MSI fields para decisión genómica auditable.
        # ─── Gate 61: HRR status required before PARP inhibitor ───
        FieldSpec(
            "hrr_status",
            "Estado HRR (Homologous Recombination Repair) global (Path A gate 61)",
            "select",
            options=["Desconocido", "Tested_pathogenic", "Tested_VUS", "Tested_wild_type", "Not_tested", "Pending", "Inconclusive"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026", "profound_de_bono_nejm_2020", "magnitude_chi_jco_2023"],
            help_text=(
                "Estado HRR global del paciente — incluye BRCA1/2, ATM, CHEK2, "
                "PALB2, RAD51 family, FANCA, BRIP1, NBN, MRE11. Path A gate 61 "
                "hard_block dispara con 'Not_tested' + consideración PARP inhibitor "
                "(olaparib/rucaparib/talazoparib) — confirmar HRR antes de iniciar."
            ),
        ),
        FieldSpec(
            "hrr_testing_not_performed",
            "Testing HRR no realizado documentado (Path A gate 61)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si paciente NO ha tenido testing HRR (germline + "
                "somatic) documentado. Path A gate 61 hard_block — solicitar "
                "panel HRR antes de iniciar PARP inhibitor."
            ),
        ),
        FieldSpec(
            "brca1_status",
            "Estado BRCA1 germinal/somático (Path B gate 61, 64)",
            "select",
            options=["Desconocido", "Mutado", "Pathogenic", "Likely_pathogenic", "VUS", "Wild_type", "Not_tested", "Pending"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_de_bono_nejm_2020", "talapro_2_agarwal_jco_2023"],
            help_text=(
                "Estado BRCA1 (germinal o somático). Componente HRR + HRD score. "
                "BRCA1 Mutado/Pathogenic = elegible PARP (olaparib/talazoparib) "
                "y mejor respuesta platino-based chemo + cisplatin."
            ),
        ),
        FieldSpec(
            "brca2_status",
            "Estado BRCA2 germinal/somático (Path B gate 61, 64)",
            "select",
            options=["Desconocido", "Mutado", "Pathogenic", "Likely_pathogenic", "VUS", "Wild_type", "Not_tested", "Pending"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_de_bono_nejm_2020", "propel_clarke_jco_2022"],
            help_text=(
                "Estado BRCA2 (germinal o somático). Componente HRR + HRD score. "
                "BRCA2 Mutado/Pathogenic = más fuerte indicación PARP inhibitor. "
                "BRCA2 enriquecido en mCRPC (germinal ~5%, somático adicional)."
            ),
        ),
        FieldSpec(
            "atm_status",
            "Estado ATM germinal/somático (Path B gate 61, 64)",
            "select",
            options=["Desconocido", "Mutado", "Pathogenic", "Likely_pathogenic", "VUS", "Wild_type", "Not_tested", "Pending"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_de_bono_nejm_2020"],
            help_text=(
                "Estado ATM (germinal o somático). Componente HRR + HRD score. "
                "ATM Mutado = elegible PARP pero respuesta menor que BRCA1/2. "
                "Consider trial enrollment (ATM-specific PARP combos)."
            ),
        ),
        FieldSpec(
            "parp_inhibitor_consideration_active",
            "Consideración PARP inhibitor activa clínicamente (gate 61 trigger)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["profound_de_bono_nejm_2020"],
            help_text=(
                "Marcar 'Sí' si MDT activamente considera PARP inhibitor "
                "(olaparib/rucaparib/talazoparib/niraparib). Activa evaluación "
                "gate 61 hard_block si HRR no está confirmado."
            ),
        ),
        FieldSpec(
            "parp_inhibitor_initiated_without_hrr",
            "PARP inhibitor iniciado SIN HRR confirmado (override gate 61)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' SOLO si MDT autorizó PARP inhibitor sin HRR "
                "confirmado (excepción documentada — pej. estudio clínico, "
                "uso compasivo). Override gate 61."
            ),
        ),
        # ─── Gate 62: AR-V7 positive ARPI resistance pathway ───
        FieldSpec(
            "ar_v7_status",
            "Estado AR-V7 (Androgen Receptor splice variant 7) (Path A gate 62)",
            "select",
            options=["Desconocido", "Positive", "Negative", "Not_tested", "Pending", "Inconclusive"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["antonarakis_jco_2017", "armor3_sv_trial"],
            help_text=(
                "Estado AR-V7 (Androgen Receptor splice variant 7) en CTC "
                "(Circulating Tumor Cells). Path A gate 62 dispara con 'Positive' "
                "+ consideración ARPI — AR-V7+ predice resistencia a abiraterone/"
                "enzalutamide. Considerar taxane (docetaxel/cabazitaxel) o niclosamide+abi."
            ),
        ),
        FieldSpec(
            "ar_v7_detected_in_ctc",
            "AR-V7 detectado en CTC documentado (Path B gate 62)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["antonarakis_jco_2017"],
            help_text=(
                "Marcar 'Sí' si test CTC AR-V7 (Adnatest, Epic Sciences) detectó "
                "transcrito AR-V7 positivo. Path B gate 62 — confirma resistencia "
                "ARPI esperada."
            ),
        ),
        FieldSpec(
            "ar_v7_resistance_documented",
            "Resistencia clínica ARPI por AR-V7 documentada (Path C gate 62)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["antonarakis_jco_2017"],
            help_text=(
                "Marcar 'Sí' si MDT documentó resistencia clínica ARPI atribuible "
                "a AR-V7 (PSA progression rápida + AR-V7+). Activa gate 62 — "
                "switch a taxane o trial enrollment."
            ),
        ),
        FieldSpec(
            "armor3_sv_trial_consideration",
            "Consideración ARMOR3-SV trial (niclosamide + abi) (gate 62 acción)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["armor3_sv_trial"],
            help_text=(
                "Marcar 'Sí' si paciente AR-V7+ está siendo considerado para "
                "ARMOR3-SV trial (niclosamide + abiraterone) — overcome AR-V7 "
                "resistance via niclosamide-mediated AR-V7 degradation."
            ),
        ),
        # ─── Gate 63: CDK12 alteration immunotherapy eligibility ───
        FieldSpec(
            "cdk12_status",
            "Estado CDK12 (Cyclin Dependent Kinase 12) (Path A gate 63)",
            "select",
            options=["Desconocido", "Mutado", "Pathogenic", "Wild_type", "Not_tested", "Pending"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["wu_cell_2018_cdk12", "antonarakis_jco_2020_cdk12"],
            help_text=(
                "Estado CDK12 (Cyclin Dependent Kinase 12). Path A gate 63 "
                "dispara con 'Mutado/Pathogenic' — fenotipo Tandem Duplication "
                "(TDP), elegible immunotherapy (pembrolizumab) + neoantigen-rich "
                "tumor. Trial enrollment priorizar (mivebresib + abi en estudio)."
            ),
        ),
        FieldSpec(
            "cdk12_pathogenic_detected",
            "CDK12 alteración patogénica detectada (Path B gate 63)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["wu_cell_2018_cdk12"],
            help_text=(
                "Marcar 'Sí' si NGS panel detectó alteración CDK12 patogénica "
                "(loss-of-function biallelic). Path B gate 63 — fenotipo TDP."
            ),
        ),
        FieldSpec(
            "tandem_duplication_phenotype_documented",
            "Fenotipo Tandem Duplication (TDP) documentado (Path C gate 63)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["wu_cell_2018_cdk12"],
            help_text=(
                "Marcar 'Sí' si análisis genómico documentó fenotipo Tandem "
                "Duplication (TDP) — patrón estructural distintivo CDK12-mutated. "
                "Path C gate 63 — neoantigen-rich → immunotherapy candidate."
            ),
        ),
        FieldSpec(
            "cdk12_checkpoint_inhibitor_candidate",
            "CDK12-mutado candidato checkpoint inhibitor (gate 63 acción)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["antonarakis_jco_2020_cdk12"],
            help_text=(
                "Marcar 'Sí' si paciente CDK12-mutado considerado para "
                "checkpoint inhibitor (pembrolizumab off-label o trial). "
                "Activa gate 63 — referir a oncología trial enrollment."
            ),
        ),
        # ─── Gate 64: Comprehensive HRD phenotype high ───
        FieldSpec(
            "hrd_comprehensive_score",
            "HRD Comprehensive Score (0-100) — composite genomic instability (Path A gate 64)",
            "number",
            default="",
            unit="score 0-100",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["myriad_myChoice_hrd_score", "ovarian_hrd_extrapolation"],
            help_text=(
                "HRD Comprehensive Score 0-100 (composite genomic instability — "
                "LOH + TAI + LST + BRCA1/2/ATM/PALB2 status). Path A gate 64 "
                "dispara con score ≥42 (HRD-high cutoff Myriad myChoice) — "
                "extrapolated PCa from ovarian. Mayor probabilidad respuesta PARP."
            ),
        ),
        FieldSpec(
            "pten_biallelic_loss_documented",
            "PTEN pérdida bialélica documentada (Path B gate 64)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["ipatential150_de_bono_lancet_2021", "akt_inhibitor_pca"],
            help_text=(
                "Marcar 'Sí' si NGS/IHC documentó PTEN loss biallelic (homozigous "
                "deletion o LOH + mutation). Path B gate 64 — activa PI3K/AKT pathway, "
                "elegible IPATential150 (ipatasertib + abiraterone)."
            ),
        ),
        FieldSpec(
            "tp53_status",
            "Estado TP53 (Tumor Protein 53) (Path B gate 64)",
            "select",
            options=["Desconocido", "Mutado", "Pathogenic", "Wild_type", "Not_tested", "Pending"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_genomic_instability"],
            help_text=(
                "Estado TP53 (Tumor Protein 53). Path B gate 64 — TP53 mutated + "
                "PTEN loss + HRR alteration = fenotipo HRD-high agresivo. "
                "TP53 mutated por sí solo = peor pronóstico mCRPC, considerar "
                "intensificación tratamiento."
            ),
        ),
        FieldSpec(
            "hrd_high_phenotype_documented",
            "Fenotipo HRD-high documentado clínicamente (Path C gate 64)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["myriad_myChoice_hrd_score"],
            help_text=(
                "Marcar 'Sí' si MDT/genomic counselor documentó fenotipo HRD-high "
                "global (composite BRCA1/2 + ATM + PALB2 + LOH/TAI/LST). Activa "
                "gate 64 — PARP inhibitor + platinum-based chemo highly preferred."
            ),
        ),
        # ─── Gate 65: MSI/MMR reflex testing Lynch family ───
        FieldSpec(
            "lynch_syndrome_family_documented",
            "Síndrome Lynch familiar documentado (Path A gate 65)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_genetic_familial_v3_2026", "lynch_pca_ncbi_2020"],
            help_text=(
                "Marcar 'Sí' si historia familiar cumple criterios Amsterdam II "
                "o Bethesda (≥3 familiares con cáncer Lynch-spectrum: colon, "
                "endometrio, ovario, gástrico, urotelial, biliar). Path A gate 65 "
                "— reflex testing MSI/MMR + germline Lynch panel obligatorio."
            ),
        ),
        FieldSpec(
            "msi_mmr_testing_recommended_clinically",
            "Testing MSI/MMR recomendado clínicamente (Path B gate 65)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si MDT recomendó testing MSI/MMR por características "
                "histológicas sospechosas (mucinoso, signet ring, infiltrado linfocítico) "
                "o presentación atípica. Path B gate 65."
            ),
        ),
        FieldSpec(
            "msi_status",
            "Estado MSI (Microsatellite Instability) (Path C gate 65)",
            "select",
            options=["Desconocido", "MSI-H", "MSI-L", "MSS", "Not_tested", "Pending", "Inconclusive"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pembrolizumab_msi_h_fda_2017", "keynote_158_marabelle_jco_2020"],
            help_text=(
                "Estado MSI (Microsatellite Instability) por PCR/NGS. Path C "
                "gate 65 dispara con 'MSI-H' — elegible pembrolizumab tumor-agnostic "
                "(FDA-approved). Considerar trial inmunotherapy + germline Lynch test."
            ),
        ),
        FieldSpec(
            "mmr_deficient_status",
            "Estado MMR (Mismatch Repair) por IHC (Path C gate 65)",
            "select",
            options=["Desconocido", "dMMR", "pMMR", "Not_tested", "Pending", "Inconclusive"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Estado MMR (Mismatch Repair) por IHC (MLH1/MSH2/MSH6/PMS2). "
                "Path C gate 65 dispara con 'dMMR' (deficient) — equivalente "
                "MSI-H, elegible pembrolizumab + germline Lynch test."
            ),
        ),
        FieldSpec(
            "lynch_germline_test_indicated",
            "Test germline Lynch indicado clínicamente (gate 65 acción)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_genetic_familial_v3_2026"],
            help_text=(
                "Marcar 'Sí' si genetic counselor recomendó test germline panel "
                "Lynch (MLH1/MSH2/MSH6/PMS2/EPCAM). Activa gate 65 acción — "
                "diagnóstico Lynch impacta family screening + manejo cáncer."
            ),
        ),
        # ── Gates 66-70 — Pre-Diagnostic + Atypical Histology + 10 Trials (Faubot LXXVII / #67C) ──
        # 🆕 Metastatic biopsy pathway + NEPC/intraductal + emergencias oncológicas + PHI/4Kscore + 10 trials.
        # ─── Gate 66: Metastatic biopsy pathway when primary impractical ───
        FieldSpec(
            "primary_biopsy_not_performed",
            "Biopsia primaria prostática no realizada (gates 66, 69)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026", "eau_2026_section_5_3"],
            help_text=(
                "Marcar 'Sí' si paciente NO ha tenido biopsia prostática primaria "
                "(TRUS/MRI-guided). Componente trigger gates 66 (metastatic biopsy "
                "pathway) y 69 (pre-bx calculators)."
            ),
        ),
        FieldSpec(
            "widespread_bone_metastases_documented",
            "Metástasis óseas extensas documentadas (Path B gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Marcar 'Sí' si bone scan/PSMA-PET muestran metástasis óseas extensas "
                "(>4 lesiones o axiales múltiples). Path B gate 66 — biopsia "
                "ósea preferencia (más rendimiento que primario en mets bulk)."
            ),
        ),
        FieldSpec(
            "spinal_cord_compression_initial_presentation",
            "Compresión medular como presentación inicial (Path C gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["patchell_lancet_2005", "loblaw_jco_2012"],
            help_text=(
                "Marcar 'Sí' si paciente debutó con compresión medular (SCC) — "
                "presentación inicial PCa avanzado. Path C gate 66 — biopsia "
                "lesión epidural si es la única accesible (paralelo a tratamiento "
                "emergency-first gate 68)."
            ),
        ),
        FieldSpec(
            "liver_metastasis_documented",
            "Metástasis hepática documentada (Path D gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si imagen (CT/MRI/PSMA-PET) documentó metástasis "
                "hepática. Path D gate 66 — biopsia hepática rendimiento alto + "
                "considerar NEPC (visceral mets prominent gate 67)."
            ),
        ),
        FieldSpec(
            "lung_metastasis_documented",
            "Metástasis pulmonar documentada (Path D gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si imagen documentó metástasis pulmonar. Path D "
                "gate 66 — biopsia transbronquial/percutánea + considerar NEPC."
            ),
        ),
        FieldSpec(
            "visceral_metastasis_present",
            "Metástasis visceral (hepática/pulmonar/peritoneal) presente (gate 66, 67)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Marcar 'Sí' si paciente tiene metástasis viscerales (cualquier "
                "órgano). Componente trigger gate 66 + considerar NEPC (visceral "
                "prominent en NEPC/small cell)."
            ),
        ),
        FieldSpec(
            "metastatic_biopsy_pathway_indicated",
            "Pathway biopsia metastásica indicada (Path E gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si MDT explícitamente indicó biopsia metastásica "
                "(no primaria) por practicidad/rendimiento clínico. Activa gate 66 "
                "Path E — soft_warning recomienda sitio óptimo."
            ),
        ),
        FieldSpec(
            "primary_biopsy_completed_or_planned",
            "Biopsia primaria completada o planeada (override gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si biopsia primaria prostática ya completada o "
                "agendada en próximas 2 semanas. Override gate 66 — gate informativo "
                "sobre alternativa metastásica innecesario."
            ),
        ),
        FieldSpec(
            "histology_already_confirmed",
            "Histología PCa ya confirmada por cualquier sitio (override gate 66)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si histología PCa ya confirmada (cualquier sitio: "
                "primary, bone, lymph node, visceral). Override gate 66 — "
                "diagnóstico tisular ya establecido."
            ),
        ),
        # ─── Gate 67: Atypical histology escalation NEPC/intraductal ───
        FieldSpec(
            "nepc_confirmed_histology",
            "NEPC (Neuroendocrine PCa) histología confirmada (Path A gate 67)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024", "beltran_jco_2018", "nccn_pros_a_v5_2026"],
            help_text=(
                "Marcar 'Sí' si patología confirmó NEPC (Neuroendocrine PCa) "
                "via IHC (chromogranin A+, synaptophysin+, NSE+, AR loss). "
                "Path A gate 67 hard_block — bloquea AS/ARPI (futile), "
                "requiere platinum-based chemo (EP regimen)."
            ),
        ),
        FieldSpec(
            "histology_subtype",
            "Subtipo histológico PCa (Path A gate 67, 70)",
            "select",
            options=["Desconocido", "adenocarcinoma", "intraductal", "intraductal_carcinoma", "cribriform", "neuroendocrine", "small_cell", "small_cell_neuroendocrine", "NEPC", "mixed_adeno_neuroendocrine", "ductal", "mucinous", "signet_ring", "other"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["who_pca_classification_2022", "nccn_pros_1_v5_2026"],
            help_text=(
                "Subtipo histológico del PCa per WHO 2022 classification. "
                "Path A gate 67 dispara con 'neuroendocrine/small_cell/NEPC/"
                "mixed_adeno_neuroendocrine'. Path B con 'intraductal'. "
                "Path C con 'cribriform' + Gleason ≥7."
            ),
        ),
        FieldSpec(
            "intraductal_carcinoma_present",
            "Carcinoma intraductal (IDC) presente (Path B gate 67)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["kweldam_eur_urol_2017", "risbridger_nat_rev_cancer_2018"],
            help_text=(
                "Marcar 'Sí' si patología documentó componente intraductal (IDC) "
                "— variante agresiva adenocarcinoma. Path B gate 67 hard_block — "
                "reclasificar very-high-risk, NO AS, multimodal intensified."
            ),
        ),
        FieldSpec(
            "cribriform_pattern_present",
            "Patrón cribiforme presente (Path C gate 67)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["kweldam_histopathology_2015", "iczkowski_mod_pathol_2018"],
            help_text=(
                "Marcar 'Sí' si patología documentó patrón cribiforme. Path C "
                "gate 67 dispara con cribriform + Gleason ≥7 — independent "
                "adverse prognostic factor (BCR-FS shorter, lethal phenotype)."
            ),
        ),
        FieldSpec(
            "ldh_value",
            "LDH (Lactato Deshidrogenasa) sérica (U/L) (Path D gate 67)",
            "number",
            default="",
            unit="U/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10000,
            allow_negative=False,
            reference_range_low=140,
            reference_range_high=280,
            reference_range_unit="U/L",
            reference_range_label="Rango normal adulto",
            evidence_tags=["aparicio_eur_urol_2024_ldh_nepc"],
            help_text=(
                "LDH sérica en U/L. Path D gate 67 dispara con LDH ≥400 + "
                "treatment_emergent_NEPC suspected — high turnover indicador "
                "NEPC transformation post-ARPI/ADT (15-20% mCRPC tarde)."
            ),
        ),
        FieldSpec(
            "treatment_emergent_nepc_suspected",
            "NEPC treatment-emergent sospechado (Path D gate 67)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024", "beltran_jco_2018"],
            help_text=(
                "Marcar 'Sí' si MDT sospecha NEPC treatment-emergent post-ARPI "
                "(PSA progression rápida + LDH elevado + visceral mets nuevos + "
                "AR signaling loss). Path D gate 67 — biopsia + chromogranin/NSE."
            ),
        ),
        # ─── Gate 68: Oncologic emergency diagnostic integration ───
        FieldSpec(
            "spinal_cord_compression_suspected",
            "Compresión medular sospechada clínicamente (Path A gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["patchell_lancet_2005", "loblaw_jco_2012"],
            help_text=(
                "Marcar 'Sí' si síntomas neurológicos sugieren SCC (back pain "
                "agudo + radiculopatía + debilidad MMII + retención urinaria/"
                "incontinencia fecal). Path A gate 68 hard_block — RM columna "
                "emergency <24h + dexametasona 16mg IV load."
            ),
        ),
        FieldSpec(
            "spinal_cord_compression_confirmed",
            "Compresión medular confirmada por imagen (Path A gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["patchell_lancet_2005"],
            help_text=(
                "Marcar 'Sí' si RM columna confirmó SCC (compresión epidural "
                "con desplazamiento médula/cauda). Path A gate 68 — decisión "
                "cirugía descompresiva + RT post-op vs RT alone <48h."
            ),
        ),
        FieldSpec(
            "visceral_crisis_documented",
            "Crisis visceral documentada (hepática/pulmonar/GI) (Path B gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' si crisis visceral documentada: liver failure (ascitis "
                "tensa + encefalopatía + INR↑), lung crisis (linfangitis + disnea "
                "severa), GI obstruction. Path B gate 68 hard_block — UCI + biopsia "
                "rapid + ADT empírico SI virtually_certain."
            ),
        ),
        FieldSpec(
            "lymphangitic_carcinomatosis",
            "Linfangitis carcinomatosa documentada (Path B gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' si CT thorax mostró patrón linfangitis carcinomatosa "
                "(reticulación septal + nodularidad). Path B gate 68 — O2 + "
                "corticoides + bronco dilatadores + chemo urgente."
            ),
        ),
        FieldSpec(
            "calcium_corrected_mg_dl",
            "Calcio corregido (mg/dL) (Path C gate 68)",
            "number",
            default="",
            unit="mg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=4,
            max_value=20,
            allow_negative=False,
            reference_range_low=8.5,
            reference_range_high=10.5,
            reference_range_unit="mg/dL",
            reference_range_label="Rango normal adulto",
            evidence_tags=["major_nejm_2016_hypercalcemia"],
            help_text=(
                "Calcio corregido por albúmina (mg/dL). Cálculo: Ca medido + "
                "0.8×(4 - albúmina). Path C gate 68 dispara con valor >11 — "
                "hipercalcemia maligna requiere zoledronic acid 4mg IV + hidratación. "
                ">14 = adicionar calcitonin (efecto rápido)."
            ),
        ),
        FieldSpec(
            "dic_diagnosed",
            "CID (Coagulación Intravascular Diseminada) diagnosticada (Path D gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' si CID diagnosticada formalmente (PT/INR↑ + "
                "fibrinógeno↓ + dímero-D↑ + plaquetas↓ + esquistocitos+). "
                "Path D gate 68 — FFP + plaquetas + crioprecipitado si bleeding active."
            ),
        ),
        FieldSpec(
            "inr_value",
            "INR (International Normalized Ratio) (Path D gate 68)",
            "number",
            default="",
            unit="ratio",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0.5,
            max_value=15,
            allow_negative=False,
            reference_range_low=0.8,
            reference_range_high=1.2,
            reference_range_unit="ratio",
            reference_range_label="Rango normal sin anticoagulación",
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "INR sérico. Path D gate 68 dispara con valor >1.5 + bleeding "
                "active — sospecha CID. También para monitoreo bridging "
                "perioperatorio (gate 56 anticoag + RP)."
            ),
        ),
        FieldSpec(
            "bleeding_active_documented",
            "Sangrado activo documentado clínicamente (Path D gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' si sangrado activo documentado (hematuria masiva, "
                "epistaxis, gastrointestinal, mucosas múltiples). Path D gate 68 "
                "— combina con INR>1.5 para sospecha CID."
            ),
        ),
        FieldSpec(
            "sodium_value",
            "Sodio sérico (Na) (mEq/L) (Path E gate 68)",
            "number",
            default="",
            unit="mEq/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=100,
            max_value=180,
            allow_negative=False,
            reference_range_low=135,
            reference_range_high=145,
            reference_range_unit="mEq/L",
            reference_range_label="Rango normal adulto",
            evidence_tags=["nccn_pros_x_v5_2026", "siadh_paraneoplastic_pca"],
            help_text=(
                "Sodio sérico (mEq/L). Path E gate 68 dispara con valor <125 — "
                "hiponatremia severa (sospecha SIADH paraneoplastic, raro PCa). "
                "Restricción agua libre + tolvaptan + corregir lentamente "
                "(<8-10 mEq/L/24h)."
            ),
        ),
        FieldSpec(
            "oncologic_emergency_active",
            "Emergencia oncológica activa documentada (Path F gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026", "eau_2026_section_11"],
            help_text=(
                "Marcar 'Sí' si MDT documentó emergencia oncológica activa "
                "(SCC/visceral crisis/hipercalcemia/CID/SIADH/etc.). Path F "
                "gate 68 hard_block — emergency-first pathway obligatorio."
            ),
        ),
        FieldSpec(
            "emergency_resolved_or_stabilized_documented",
            "Emergencia oncológica resuelta o estabilizada (override gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' SOLO cuando emergency team documentó resolución/"
                "estabilización (SCC: function preservada O deficit established; "
                "Visceral: hemodinámica estable; Hipercalcemia: Ca <11; CID: "
                "INR <1.5 + bleeding controlled; SIADH: Na >130 sostenida). "
                "Override gate 68."
            ),
        ),
        FieldSpec(
            "oncologic_emergency_managed",
            "Emergencia oncológica manejada por equipo emergency (override gate 68)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_x_v5_2026"],
            help_text=(
                "Marcar 'Sí' si emergency team/UCI/oncology emergency manejó "
                "el evento agudo y paciente está en fase de recuperación. "
                "Override gate 68."
            ),
        ),
        # ─── Gate 69: Pre-biopsy risk calculators (PHI/4Kscore/PSAv/PSAD) ───
        FieldSpec(
            "phi_score_available",
            "PHI (Prostate Health Index) score disponible (gate 69)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["loeb_j_urol_2015_phi"],
            help_text=(
                "Marcar 'Sí' si PHI score disponible/calculado (Beckman Coulter "
                "FDA-approved). Activa gate 69 informativo — interpretar con "
                "phi_score_value."
            ),
        ),
        FieldSpec(
            "phi_score_value",
            "PHI score value (0-150) — Prostate Health Index (gate 69)",
            "number",
            default="",
            unit="score 0-150",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=150,
            allow_negative=False,
            evidence_tags=["loeb_j_urol_2015_phi"],
            help_text=(
                "PHI score (Prostate Health Index). Formula: ([-2]proPSA/freePSA)×√PSA. "
                "Cutoffs HighRisk PCa Gleason ≥7: <27 low, 27-36 intermediate, "
                ">36 high. Reduce biopsias 25-30% vs PSA alone."
            ),
        ),
        FieldSpec(
            "fourkscore_available",
            "4Kscore disponible (gate 69)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["parekh_jco_2015_4kscore"],
            help_text=(
                "Marcar 'Sí' si 4Kscore disponible/calculado (OPKO Health). "
                "Activa gate 69 informativo — interpretar con fourkscore_value."
            ),
        ),
        FieldSpec(
            "fourkscore_value",
            "4Kscore value (0-100%) — probability HighRisk PCa (gate 69)",
            "number",
            default="",
            unit="% probability",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["parekh_jco_2015_4kscore"],
            help_text=(
                "4Kscore probability HighRisk PCa (PSA + free + intact + hK2 + "
                "age + DRE + prior bx). Cutoffs: <7.5% very low, 7.5-15% intermediate, "
                ">15% high. Reduce biopsias 30-40% vs PSA alone."
            ),
        ),
        FieldSpec(
            "psa_density",
            "PSA Density (PSAD) ng/mL/cc (gate 69)",
            "number",
            default="",
            unit="ng/mL/cc",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["roobol_eur_urol_2015_psad", "eau_2026_section_5_1_2"],
            help_text=(
                "PSA Density (PSAD) = PSA / volumen prostático (ng/mL/cc). "
                "Cutoffs EAU 2026: <0.10 low, 0.10-0.15 intermediate, >0.15 high "
                "(biopsy indicated). Requires prostate volume (mpMRI/TRUS)."
            ),
        ),
        FieldSpec(
            "prostate_volume_ml",
            "Volumen prostático (mL/cc) (gate 69)",
            "number",
            default="",
            unit="mL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=500,
            allow_negative=False,
            evidence_tags=["roobol_eur_urol_2015_psad", "abs_brachy_consensus_2020"],
            help_text=(
                "Volumen prostático medido por mpMRI o TRUS (mL = cc). Necesario "
                "para calcular PSA density (gate 69) y para decisiones brachy "
                "(gate 59 — LDR brachy ideal 30-50cc, HDR <80cc)."
            ),
        ),
        FieldSpec(
            "prior_negative_biopsy_documented",
            "Biopsia prostática previa negativa documentada (gate 69)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si paciente tuvo biopsia prostática previa con "
                "resultado negativo + PSA persistentemente elevado. Path B gate 69 "
                "— calculadores adicionales (PHI/4Kscore) reducen biopsias "
                "repetidas innecesarias."
            ),
        ),
        # ─── Gate 70: 10 trials completion (PROTECT/SPCG-4/PIVOT/SWOG/RAVES/RTOG/SPPORT/GETUG) ───
        FieldSpec(
            "decision_rp_vs_rt_active",
            "Decisión RP vs RT vs AS activa (Path A gate 70)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["protect_hamdy_nejm_2023", "spcg4_bill_axelson_nejm_2014", "pivot_wilt_nejm_2017"],
            help_text=(
                "Marcar 'Sí' si decisión modalidad localizada (RP vs RT vs AS) "
                "está activa. Path A gate 70 — informativo trials PROTECT/SPCG-4/"
                "PIVOT data para counseling subgroup risk."
            ),
        ),
        FieldSpec(
            "active_surveillance_eligibility_evaluation",
            "Evaluación elegibilidad vigilancia activa en curso (Path A gate 70)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["protect_hamdy_nejm_2023"],
            help_text=(
                "Marcar 'Sí' si MDT evalúa elegibilidad para vigilancia activa "
                "(very-low/low/favorable-intermediate risk). Path A gate 70 — "
                "PROTECT data: AS conversion 27% 5yr, 44% 10yr, CSS similar 3 grupos."
            ),
        ),
        FieldSpec(
            "salvage_rt_consideration_active",
            "Consideración salvage RT post-RP activa (Path B gate 70)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["raves_kneebone_lancet_oncol_2020", "artistic_vale_lancet_oncol_2020", "rtog9601_shipley_nejm_2017", "spport_pollack_lancet_2022", "getug_afu16_carrie_lancet_oncol_2016"],
            help_text=(
                "Marcar 'Sí' si MDT considera salvage RT post-RP (BCR + PSA "
                "rising). Path B gate 70 — informativo trials RAVES/ARTISTIC "
                "(salvage non-inferior adjuvant) + RTOG 9601/SPPORT/GETUG-AFU 16 "
                "(salvage RT + ADT improves OS/PFS)."
            ),
        ),
        FieldSpec(
            "trial_coverage_completion_check",
            "Check cobertura trials (37→47 trials) (Path C gate 70)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["protect_hamdy_nejm_2023", "spcg4_bill_axelson_nejm_2014"],
            help_text=(
                "Marcar 'Sí' para activar reporte cobertura completa 47 trials "
                "(37 sistémicos + 10 localized/BCR adjuvant gate 70). Útil para "
                "trial matching engine + evidence drill-down (#65A backend)."
            ),
        ),
        # ── Gates 71-75 — Progression Detection (Faubot LXXVIII / #67D) ──
        # 🆕 PSMA-PET progression + visceral mets + BPI pain + ECOG decline + composite rPFS.
        # ─── Gate 71: PSMA-PET progression auto-trigger ───
        FieldSpec(
            "psma_new_lesion_count",
            "Número nuevas lesiones PSMA-positive (Path A gate 71)",
            "number",
            default="",
            unit="lesiones",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["pcwg3_scher_jco_2016", "promise_hofman_lancet_2020"],
            help_text=(
                "Número nuevas lesiones PSMA-positive en PSMA-PET vs basal. "
                "Path A gate 71 dispara con ≥1 nueva lesión — alerta progresión "
                "radiográfica + auto-disparo rPFS event PCWG3."
            ),
        ),
        FieldSpec(
            "psma_suvmax_current",
            "PSMA SUVmax actual (lesiones top 5) (gate 71)",
            "number",
            default="",
            unit="SUVmax",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=200,
            allow_negative=False,
            evidence_tags=["percist_wahl_jnm_2009"],
            help_text=(
                "SUVmax actual en lesiones PSMA-positive (promedio top 5 más "
                "ávidas). Comparar con PSMA SUVmax baseline para calcular "
                "porcentaje cambio (PERCIST 1.0)."
            ),
        ),
        FieldSpec(
            "psma_suvmax_baseline",
            "PSMA SUVmax baseline (comparator) (gate 71)",
            "number",
            default="",
            unit="SUVmax",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=200,
            allow_negative=False,
            evidence_tags=["percist_wahl_jnm_2009"],
            help_text=(
                "PSMA SUVmax baseline (PSMA-PET previo o pre-treatment). "
                "Comparator para calcular psma_suvmax_increase_percent."
            ),
        ),
        FieldSpec(
            "psma_suvmax_increase_percent",
            "PSMA SUVmax cambio % (Path B gate 71)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-100,
            max_value=1000,
            allow_negative=True,
            evidence_tags=["percist_wahl_jnm_2009"],
            help_text=(
                "Cambio porcentual SUVmax actual vs baseline (calculado). "
                "Path B gate 71 dispara con ≥30% incremento (PERCIST 1.0 "
                "progression criterion)."
            ),
        ),
        FieldSpec(
            "psma_total_tumor_volume_increase_percent",
            "PSMA-TTV cambio % (Path C gate 71)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-100,
            max_value=1000,
            allow_negative=True,
            evidence_tags=["percist_wahl_jnm_2009"],
            help_text=(
                "Cambio porcentual PSMA Total Tumor Volume (PSMA-TTV) actual "
                "vs baseline. Path C gate 71 dispara con ≥30% (mayor "
                "sensibilidad que SUVmax single-lesion)."
            ),
        ),
        FieldSpec(
            "psma_progression_date",
            "Fecha PSMA-PET progression (rPFS event marker)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Fecha primera detección PSMA progression formal — usado como "
                "rPFS event marker PCWG3 endpoint."
            ),
        ),
        FieldSpec(
            "psma_pet_progression_documented",
            "PSMA-PET progression documentada por radiólogo (Path D gate 71)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si radiólogo documentó PSMA-PET progression formal "
                "(nuevas lesiones + SUVmax aumento + correlación clínica). "
                "Path D gate 71 — activa rPFS event auto."
            ),
        ),
        # ─── Gate 72: Visceral metastasis new appearance ───
        FieldSpec(
            "new_visceral_metastasis_documented",
            "Nuevas metástasis viscerales documentadas (Path A gate 72)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["chaarted_sweeney_nejm_2015", "vision_sartor_nejm_2021"],
            help_text=(
                "Marcar 'Sí' si imagen documentó nuevas metástasis viscerales "
                "(hígado, pulmón, peritoneo, SNC) vs estudio previo. Path A "
                "gate 72 — auto-disparo rPFS + considerar NEPC (gate 67)."
            ),
        ),
        FieldSpec(
            "new_liver_metastasis_appeared",
            "Nueva metástasis hepática (Path B gate 72)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Marcar 'Sí' si nueva metástasis hepática aparece (CT/MRI/PSMA-PET). "
                "Path B gate 72 — biopsia hepática rendimiento alto + sospecha NEPC."
            ),
        ),
        FieldSpec(
            "new_lung_metastasis_appeared",
            "Nueva metástasis pulmonar (Path C gate 72)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Marcar 'Sí' si nueva metástasis pulmonar aparece. Path C gate 72."
            ),
        ),
        FieldSpec(
            "new_cns_metastasis_appeared",
            "Nueva metástasis SNC (cerebro/leptomeningeal) (Path D gate 72)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024"],
            help_text=(
                "Marcar 'Sí' si nueva metástasis SNC (brain mets, leptomeningeal). "
                "Path D gate 72 — sospecha NEPC/small cell, considerar SRS/WBRT "
                "(gate 83 palliative RT)."
            ),
        ),
        FieldSpec(
            "visceral_metastases_count_current",
            "Count metástasis viscerales actual (gate 72)",
            "number",
            default="",
            unit="lesiones",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Número total metástasis viscerales actual. Comparar con baseline "
                "para calcular visceral_metastases_count_increase."
            ),
        ),
        FieldSpec(
            "visceral_metastases_count_baseline",
            "Count metástasis viscerales baseline (comparator)",
            "number",
            default="",
            unit="lesiones",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["chaarted_sweeney_nejm_2015"],
            help_text=(
                "Count metástasis viscerales baseline (estudio previo). Comparator."
            ),
        ),
        FieldSpec(
            "visceral_metastases_count_increase",
            "Cambio count visceral mets (Path E gate 72)",
            "number",
            default="",
            unit="lesiones",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-50,
            max_value=100,
            allow_negative=True,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Cambio count visceral mets (current - baseline). Path E gate 72 "
                "dispara con ≥1 nueva visceral."
            ),
        ),
        # ─── Gate 73: Structured pain progression BPI ───
        FieldSpec(
            "bpi_worst_pain_score",
            "BPI worst pain (peor dolor 24h) 0-10 (Path A/B gate 73)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bpi_cleeland_1994", "pcwg3_scher_jco_2016"],
            help_text=(
                "Brief Pain Inventory worst pain 24h NRS 0-10. Cutoffs: 0-3 leve, "
                "4-6 moderado (Path A gate 73 ≥4 + persistente ≥4 sem), 7-10 "
                "severo (Path B gate 73 urgent ≥7)."
            ),
        ),
        FieldSpec(
            "bpi_least_pain_score",
            "BPI least pain (mejor dolor 24h) 0-10",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bpi_cleeland_1994"],
            help_text=(
                "BPI least pain 24h NRS. Componente BPI estándar + indicador "
                "control basal."
            ),
        ),
        FieldSpec(
            "bpi_average_pain_score",
            "BPI average pain (promedio 24h) 0-10",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bpi_cleeland_1994"],
            help_text=(
                "BPI average pain 24h NRS. Componente BPI estándar."
            ),
        ),
        FieldSpec(
            "bpi_current_pain_score",
            "BPI current pain (dolor actual) 0-10",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bpi_cleeland_1994"],
            help_text=(
                "BPI pain right now NRS. Componente BPI estándar."
            ),
        ),
        FieldSpec(
            "bpi_interference_average",
            "BPI interference promedio 7 ítems 0-10 (Path C gate 73)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bpi_cleeland_1994"],
            help_text=(
                "BPI interference promedio 7 ítems (actividad, mood, ambulación, "
                "trabajo, relaciones, sueño, disfrute vida). Path C gate 73 ≥4 "
                "= functional impact significativo."
            ),
        ),
        FieldSpec(
            "bpi_pain_persistent_weeks",
            "Semanas dolor sostenido (Path A gate 73)",
            "number",
            default="",
            unit="semanas",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=520,
            allow_negative=False,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Duración dolor sostenido en semanas. Path A gate 73 requiere "
                "≥4 semanas + BPI worst ≥4 (PCWG3 sustained criterion)."
            ),
        ),
        FieldSpec(
            "bpi_worst_pain_baseline",
            "BPI worst pain baseline (comparator) 0-10",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "BPI worst pain baseline (treatment start). Comparator para "
                "calcular bpi_worst_pain_increase_percent (PCWG3 progression)."
            ),
        ),
        FieldSpec(
            "bpi_worst_pain_increase_percent",
            "BPI worst pain cambio % (Path D gate 73)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-100,
            max_value=1000,
            allow_negative=True,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Cambio porcentual BPI worst pain vs baseline. Path D gate 73 "
                "dispara con ≥30% (PCWG3 pain progression criterion)."
            ),
        ),
        FieldSpec(
            "new_opioid_requirement_for_cancer_pain",
            "Nueva necesidad opioides cancer pain (Path E gate 73)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si paciente previamente sin opioides ahora requires. "
                "Path E gate 73 — PCWG3 pain progression criterion."
            ),
        ),
        FieldSpec(
            "current_opioid_morphine_equivalent_mg_day",
            "Opioides actual MED (morphine equivalent dose) mg/día (gate 73)",
            "number",
            default="",
            unit="mg MED/día",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10000,
            allow_negative=False,
            evidence_tags=["nccn_pain_v2_2026"],
            help_text=(
                "Dosis opioides actual en MED (morphine equivalent dose) mg/día. "
                "Calculator: oxicodona × 1.5, metadona × 4-12, fentanilo TTS × "
                "2.4, hidromorfona × 4. Útil para escalación tracking."
            ),
        ),
        # ─── Gate 74: ECOG decline alert ───
        FieldSpec(
            "ecog_current",
            "ECOG performance status actual 0-5 (Path B/C gate 74)",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4", "5"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["oken_ecog_1982", "pcwg3_scher_jco_2016"],
            help_text=(
                "ECOG Performance Status actual. 0=fully active, 1=ambulatorio "
                "+ ligera actividad, 2=≥50% día up, 3=>50% cama, 4=totalmente "
                "cama/silla, 5=muerto. Path B gate 74 dispara ≥2, Path C ≥3."
            ),
        ),
        FieldSpec(
            "ecog_baseline",
            "ECOG baseline (treatment start) 0-5",
            "select",
            options=["Desconocido", "0", "1", "2", "3", "4"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["oken_ecog_1982"],
            help_text=(
                "ECOG baseline (treatment start). Comparator para calcular "
                "ecog_change_from_baseline."
            ),
        ),
        FieldSpec(
            "ecog_change_from_baseline",
            "ECOG cambio vs baseline (Path A gate 74)",
            "number",
            default="",
            unit="grados",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=-5,
            max_value=5,
            allow_negative=True,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Cambio ECOG vs baseline (current - baseline). Path A gate 74 "
                "dispara con ≥1 grado peor (positive change). PCWG3 clinical "
                "progression criterion."
            ),
        ),
        FieldSpec(
            "ecog_decline_documented_date",
            "Fecha ECOG decline documentado (gate 74)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Fecha decline ECOG documentado — útil para tracking + rPFS "
                "event documentation."
            ),
        ),
        FieldSpec(
            "ecog_significant_decline_documented",
            "ECOG significant decline documentado clínicamente (Path D gate 74)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si MDT documentó decline funcional significativo "
                "(ECOG worsening + functional impact + treatment reevaluation "
                "needed). Path D gate 74."
            ),
        ),
        # ─── Gate 75: Composite progression rPFS reroute ───
        FieldSpec(
            "psa_progression_documented",
            "PSA progression documentada (gate 75 composite)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si PSA progression documentada (Phoenix BCR, PSADT "
                "≤10m, PSA rise ≥25% + ≥2 ng/mL absoluto). Componente gate 75 "
                "composite progression."
            ),
        ),
        FieldSpec(
            "pcwg3_composite_progression_documented",
            "PCWG3 composite progression documentada (Path D gate 75)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Marcar 'Sí' si MDT documentó composite progression PCWG3 "
                "(≥2 categorías: PSA + radiographic + clinical). Path D gate 75 "
                "— rPFS event formal + reroute next-line obligatorio."
            ),
        ),
        FieldSpec(
            "composite_progression_categories_fired",
            "Categorías composite progression fired (gate 75)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Lista categorías PCWG3 que fired (PSA/radiographic/clinical). "
                "Útil para auditoría + tracking pathway reroute."
            ),
        ),
        FieldSpec(
            "composite_progression_date",
            "Fecha primera composite progression (rPFS event)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["pcwg3_scher_jco_2016"],
            help_text=(
                "Fecha primera composite progression PCWG3 — rPFS event formal "
                "para trial endpoint + survival analysis."
            ),
        ),
        FieldSpec(
            "next_line_therapy_planned",
            "Next-line therapy plan (post-composite progression)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Pathway next-line therapy planeada post composite progression "
                "(taxane, ARPI switch, PARP, Lu-177-PSMA, Ra-223, trial, BSC)."
            ),
        ),
        FieldSpec(
            "mdt_composite_review_completed",
            "MDT review composite progression completed (gate 75)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si MDT review completed para composite progression "
                "+ pathway reroute decision documented. Critical para auditabilidad."
            ),
        ),
        # ── Gates 76-85 — Palliative + Radiopharm + Palliative RT (Faubot LXXIX / #67E) ──
        # 🆕 Sm-153 + I-131 MIBG + Ac-225-PSMA + palliative sedation + ESAS + PHQ-9 + GAD-7 + palliative RT + oligo SBRT + cachexia.
        # ─── Gate 76: Samarium-153 EDTMP eligibility ───
        FieldSpec(
            "samarium_153_edtmp_candidate",
            "Sm-153-EDTMP candidate clínico (Path B gate 76)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sartor_jco_2004_sm153", "quadramet_fda_1997"],
            help_text=(
                "Marcar 'Sí' si paciente candidato a Sm-153-EDTMP (Quadramet) "
                "para palliación bone pain widespread + multi-foci + ANC/plaquetas "
                "OK. Path B gate 76. Dosis 1.0 mCi/kg IV single."
            ),
        ),
        FieldSpec(
            "bone_pain_widespread_documented",
            "Bone pain widespread documentado (gate 76)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sartor_jco_2004_sm153"],
            help_text=(
                "Marcar 'Sí' si bone pain widespread (multi-sitio, no focal). "
                "Componente gate 76 Sm-153 candidacy."
            ),
        ),
        FieldSpec(
            "bone_scan_multifoci_positive",
            "Bone scan multi-foci positive (gate 76)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sartor_jco_2004_sm153"],
            help_text=(
                "Marcar 'Sí' si bone scan Tc-99m MDP múltiples foci positive "
                "(≥2 sitios). Necesario para Sm-153 eligibility."
            ),
        ),
        FieldSpec(
            "osteoblastic_lesions_predominant",
            "Lesiones predominantemente osteoblastic (gate 76)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sartor_jco_2004_sm153"],
            help_text=(
                "Marcar 'Sí' si lesiones óseas predominantemente osteoblastic "
                "(no osteolytic). Sm-153 más útil osteoblastic patterns."
            ),
        ),
        FieldSpec(
            "samarium_153_dose_planned_mci_kg",
            "Sm-153 dosis planeada (mCi/kg) (gate 76)",
            "number",
            default="1.0",
            unit="mCi/kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0.5,
            max_value=2.0,
            allow_negative=False,
            evidence_tags=["quadramet_fda_1997"],
            help_text=(
                "Sm-153 dosis planeada en mCi/kg (1.0 mCi/kg IV single dose "
                "default). Quadramet FDA-approved 1997."
            ),
        ),
        FieldSpec(
            "samarium_153_administration_date",
            "Fecha Sm-153 administración planeada (gate 76)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["quadramet_fda_1997"],
            help_text=(
                "Fecha Sm-153 administración planeada. Repetir cada 3 meses si "
                "respuesta + counts adecuados."
            ),
        ),
        FieldSpec(
            "samarium_153_prior_administrations_count",
            "Sm-153 administraciones previas count (gate 76)",
            "number",
            default="0",
            unit="dosis",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=20,
            allow_negative=False,
            evidence_tags=["quadramet_fda_1997"],
            help_text=(
                "Número administraciones Sm-153 previas (lifetime). Maximum "
                "típico 4-6 dosis lifetime."
            ),
        ),
        # ─── Gate 77: I-131 MIBG NEPC eligibility ───
        FieldSpec(
            "mibg_scan_positive_diagnostic",
            "MIBG scan positive diagnostic (Path B gate 77)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bombardieri_eur_j_nucl_med_2010"],
            help_text=(
                "Marcar 'Sí' si MIBG scan diagnostic positive (I-123 o I-131 "
                "low-dose). Prerequisite para I-131 MIBG therapy. Path B gate 77."
            ),
        ),
        FieldSpec(
            "mibg_curie_score",
            "MIBG Curie score (quantification uptake) (gate 77)",
            "number",
            default="",
            unit="score",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=30,
            allow_negative=False,
            evidence_tags=["bombardieri_eur_j_nucl_med_2010"],
            help_text=(
                "Modified Curie score quantification MIBG uptake (0-30). Útil "
                "para evaluar MIBG-avidity tumor + therapy candidacy."
            ),
        ),
        FieldSpec(
            "i131_mibg_candidate_clinical",
            "I-131 MIBG candidate clinical evaluation (gate 77)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024"],
            help_text=(
                "Marcar 'Sí' si MDT considera I-131 MIBG en NEPC MIBG-avid "
                "subset. Trial enrollment priority (rare disease)."
            ),
        ),
        FieldSpec(
            "i131_mibg_dose_planned_mci",
            "I-131 MIBG dosis planeada (mCi) (gate 77)",
            "number",
            default="",
            unit="mCi",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=50,
            max_value=300,
            allow_negative=False,
            evidence_tags=["bombardieri_eur_j_nucl_med_2010"],
            help_text=(
                "I-131 MIBG dosis planeada (range 100-200 mCi típico). High-dose "
                "radiation requires hospitalización inpatient + aislamiento."
            ),
        ),
        FieldSpec(
            "sski_thyroid_blockade_initiated",
            "SSKI bloqueo tiroideo iniciado pre-I-131 MIBG (gate 77)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bombardieri_eur_j_nucl_med_2010"],
            help_text=(
                "Marcar 'Sí' si SSKI 130 mg/d iniciado 2-3 sem pre-I-131 MIBG. "
                "Continúa 4-6 sem post-Rx. Crítico para protección tiroides."
            ),
        ),
        # ─── Gate 78: Actinium-225-PSMA investigational ───
        FieldSpec(
            "lutetium_177_psma_progression_documented",
            "Progression post Lu-177-PSMA documentada (Path A gate 78)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sathekge_jnm_2024"],
            help_text=(
                "Marcar 'Sí' si paciente progresó tras Lu-177-PSMA-617 (VISION-"
                "based o equivalente). Path A gate 78 — Ac-225-PSMA candidate "
                "investigational."
            ),
        ),
        FieldSpec(
            "psma_pet_positive_current",
            "PSMA-PET positive actual (Path A gate 78)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["promise_hofman_lancet_2020"],
            help_text=(
                "Marcar 'Sí' si PSMA-PET actual muestra uptake significativo "
                "(SUVmax ≥10). Necesario para Ac-225-PSMA targeting."
            ),
        ),
        FieldSpec(
            "actinium_225_psma_candidate",
            "Ac-225-PSMA candidate evaluation (Path B gate 78)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["kratochwil_jnm_2016", "sathekge_jnm_2024"],
            help_text=(
                "Marcar 'Sí' si MDT considera Ac-225-PSMA investigational "
                "(centros expertise + trial enrollment). Path B gate 78."
            ),
        ),
        FieldSpec(
            "actinium_225_trial_enrollment_active",
            "Ac-225-PSMA trial enrollment active (Path C gate 78)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["violet_trial_nct05477576"],
            help_text=(
                "Marcar 'Sí' si paciente enrolled en trial Ac-225-PSMA activo "
                "(VIOLET, otros). Path C gate 78."
            ),
        ),
        FieldSpec(
            "actinium_225_dose_planned_kbq_kg",
            "Ac-225-PSMA dosis planeada (kBq/kg) (gate 78)",
            "number",
            default="100",
            unit="kBq/kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=50,
            max_value=200,
            allow_negative=False,
            evidence_tags=["sathekge_jnm_2024"],
            help_text=(
                "Ac-225-PSMA dosis planeada (range 50-200 kBq/kg, 100 default). "
                "Cada 8 semanas. Hospitalización inpatient required."
            ),
        ),
        # ─── Gate 79: Palliative sedation protocol ───
        FieldSpec(
            "palliative_sedation_initiation_planned",
            "Palliative sedation iniciación planeada (Path A gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si MDT considera iniciar palliative sedation. "
                "Path A gate 79 hard_block — requires criterios EAPC completos "
                "(refractory + MDT consensus + family consent)."
            ),
        ),
        FieldSpec(
            "end_of_life_stage_documented",
            "End-of-life stage imminente documentado (Path B gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si paciente en EOL stage (esperanza vida horas-"
                "días-semanas, ECOG 4, Karnofsky <30, DNR/DNI confirmed). "
                "Componente gate 79."
            ),
        ),
        FieldSpec(
            "refractory_pain_palliative_failure",
            "Pain refractory máximas medidas paliativas (Path B gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si pain refractary tras máximas medidas analgésicas "
                "(opioides altas dosis + adyuvantes + interventional). Componente "
                "gate 79 indication palliative sedation."
            ),
        ),
        FieldSpec(
            "refractory_dyspnea_terminal",
            "Disnea refractaria terminal (Path B gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si disnea refractaria EOL (O2 + opioides + benzo "
                "no efectivos). Componente gate 79."
            ),
        ),
        FieldSpec(
            "refractory_agitation_delirium_terminal",
            "Agitation/delirium refractary terminal (Path B gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si agitation/delirium EOL refractary (haloperidol "
                "+ benzo failure). Componente gate 79."
            ),
        ),
        FieldSpec(
            "palliative_sedation_eapc_criteria_met",
            "EAPC criteria sedation met (override gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' SOLO si TODOS criterios EAPC met: EOL + refractory "
                "+ MDT + family consent + documentation. Override gate 79 "
                "hard_block."
            ),
        ),
        FieldSpec(
            "mdt_consensus_palliative_sedation_documented",
            "MDT consensus sedation documentado (override gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si MDT (oncology + palliative + ethics) documentó "
                "consensus formal para palliative sedation. Override gate 79."
            ),
        ),
        FieldSpec(
            "family_consent_palliative_sedation_documented",
            "Family consent palliative sedation documentado (override gate 79)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Marcar 'Sí' si family/representante legal consentimiento "
                "escrito firmado. Override gate 79."
            ),
        ),
        FieldSpec(
            "palliative_sedation_agent_selected",
            "Palliative sedation agente seleccionado (gate 79)",
            "select",
            options=["Desconocido", "midazolam", "propofol", "phenobarbital", "levomepromazine", "haloperidol", "combination"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Agente palliative sedation seleccionado. Midazolam preferred "
                "(EAPC), propofol alternativo, phenobarbital refractary, "
                "levomepromazine/haloperidol delirium."
            ),
        ),
        FieldSpec(
            "palliative_sedation_initiation_date",
            "Fecha palliative sedation iniciación (gate 79)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["eapc_cherny_palliat_med_2009"],
            help_text=(
                "Fecha palliative sedation iniciada. Tracking + auditabilidad."
            ),
        ),
        # ─── Gate 80: ESAS severity alert ───
        FieldSpec(
            "esas_pain_score",
            "ESAS pain (dolor) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem pain 0-10 NRS. ≥4 trigger optimización analgesia. "
                "≥7 severo urgent."
            ),
        ),
        FieldSpec(
            "esas_fatigue_score",
            "ESAS fatigue (fatiga) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem fatigue 0-10 NRS. ≥4 corregir anemia + sleep "
                "optimization."
            ),
        ),
        FieldSpec(
            "esas_nausea_score",
            "ESAS nausea (náusea) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem nausea 0-10 NRS. ≥4 anti-emetic optimization."
            ),
        ),
        FieldSpec(
            "esas_depression_score",
            "ESAS depression (depresión) 0-10 (gate 80, trigger gate 81)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem depression 0-10 NRS. ≥4 trigger PHQ-9 formal screening "
                "(gate 81)."
            ),
        ),
        FieldSpec(
            "esas_anxiety_score",
            "ESAS anxiety (ansiedad) 0-10 (gate 80, trigger gate 82)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem anxiety 0-10 NRS. ≥4 trigger GAD-7 formal screening "
                "(gate 82)."
            ),
        ),
        FieldSpec(
            "esas_drowsiness_score",
            "ESAS drowsiness (somnolencia) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem drowsiness 0-10 NRS. ≥4 revisar opioides + benzo."
            ),
        ),
        FieldSpec(
            "esas_appetite_score",
            "ESAS appetite (apetito invertido) 0-10 (gate 80, trigger gate 85)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem appetite (INVERTIDO: 0=mejor, 10=peor). ≥4 trigger "
                "cachexia evaluation (gate 85)."
            ),
        ),
        FieldSpec(
            "esas_wellbeing_score",
            "ESAS wellbeing (bienestar invertido) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem wellbeing (INVERTIDO: 0=mejor, 10=peor). ≥4 spiritual "
                "care + family meeting."
            ),
        ),
        FieldSpec(
            "esas_dyspnea_score",
            "ESAS dyspnea (disnea) 0-10 (gate 80)",
            "number",
            default="",
            unit="0-10 NRS",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "ESAS ítem dyspnea 0-10 NRS. ≥4 O2 + opioides + benzo. ≥7 "
                "severo urgent."
            ),
        ),
        FieldSpec(
            "esas_total_score",
            "ESAS total score (suma 9 ítems) 0-90 (gate 80)",
            "number",
            default="",
            unit="0-90",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=90,
            allow_negative=False,
            evidence_tags=["hui_cancer_2014_esas"],
            help_text=(
                "ESAS total score (suma 9 ítems). ≥30 distress severo + "
                "palliative care referral."
            ),
        ),
        FieldSpec(
            "esas_items_above_4_count",
            "Count ESAS ítems ≥4 (Path A gate 80)",
            "number",
            default="",
            unit="ítems",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=9,
            allow_negative=False,
            evidence_tags=["nccn_distress_v3_2026"],
            help_text=(
                "Count ítems ESAS ≥4. Path A gate 80 dispara con ≥2 ítems ≥4 "
                "(distress multi-síntoma)."
            ),
        ),
        FieldSpec(
            "esas_assessment_date",
            "Fecha ESAS evaluación (gate 80)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bruera_esas_1991"],
            help_text=(
                "Fecha ESAS evaluación. Track longitudinal cada visita (mín 4-8 sem)."
            ),
        ),
        FieldSpec(
            "esas_severe_distress_documented",
            "ESAS severe distress documentado clínicamente (Path D gate 80)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_distress_v3_2026"],
            help_text=(
                "Marcar 'Sí' si MDT documentó distress multi-síntoma severo. "
                "Path D gate 80."
            ),
        ),
        # ─── Gate 81: PHQ-9 depression ───
        FieldSpec(
            "phq9_total_score",
            "PHQ-9 total score (0-27) (Path A gate 81)",
            "number",
            default="",
            unit="0-27",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=27,
            allow_negative=False,
            evidence_tags=["kroenke_phq9_2001"],
            help_text=(
                "PHQ-9 total score (suma 9 ítems × 0-3). 0-4 minimal, 5-9 mild, "
                "10-14 moderate (Path A gate 81 ≥10 trigger), 15-19 mod-severe, "
                "20-27 severe (urgent)."
            ),
        ),
        FieldSpec(
            "phq9_item_9_suicidal_ideation",
            "PHQ-9 ítem 9 suicidal ideation 0-3 (Path B gate 81 CRITICAL)",
            "number",
            default="",
            unit="0-3",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=3,
            allow_negative=False,
            evidence_tags=["kroenke_phq9_2001"],
            help_text=(
                "PHQ-9 ítem 9 (suicidal ideation): 0=nunca, 1=varios días, "
                "2=más de la mitad, 3=casi todos. Path B gate 81 CRITICAL: "
                "CUALQUIER ≥1 = EMERGENCY ASSESSMENT."
            ),
        ),
        FieldSpec(
            "phq9_assessment_date",
            "Fecha PHQ-9 assessment (gate 81)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["kroenke_phq9_2001"],
            help_text=(
                "Fecha PHQ-9 evaluación. Track longitudinal."
            ),
        ),
        FieldSpec(
            "clinical_depression_documented",
            "Depresión clínica documentada (Path C gate 81)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_distress_v3_2026"],
            help_text=(
                "Marcar 'Sí' si depresión clínica diagnosticada formalmente "
                "(DSM-5 criteria + psych assessment). Path C gate 81."
            ),
        ),
        FieldSpec(
            "antidepressant_initiated",
            "Antidepresivo iniciado (gate 81)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["cipriani_lancet_2018"],
            help_text=(
                "Marcar 'Sí' si antidepresivo iniciado (mirtazapine, sertraline, "
                "escitalopram, etc). Tracking treatment."
            ),
        ),
        FieldSpec(
            "psych_referral_completed",
            "Psych referral completed (gate 81)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_distress_v3_2026"],
            help_text=(
                "Marcar 'Sí' si referral a psicología/psiquiatría completed."
            ),
        ),
        # ─── Gate 82: GAD-7 anxiety ───
        FieldSpec(
            "gad7_total_score",
            "GAD-7 total score (0-21) (Path A gate 82)",
            "number",
            default="",
            unit="0-21",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=21,
            allow_negative=False,
            evidence_tags=["spitzer_gad7_2006"],
            help_text=(
                "GAD-7 total score (suma 7 ítems × 0-3). 0-4 minimal, 5-9 mild, "
                "10-14 moderate (Path A gate 82 ≥10 trigger), 15-21 severe."
            ),
        ),
        FieldSpec(
            "gad7_assessment_date",
            "Fecha GAD-7 assessment (gate 82)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spitzer_gad7_2006"],
            help_text=(
                "Fecha GAD-7 evaluación. Track longitudinal."
            ),
        ),
        FieldSpec(
            "clinical_anxiety_disorder_documented",
            "Trastorno ansiedad clínico documentado (Path B gate 82)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bandelow_2017"],
            help_text=(
                "Marcar 'Sí' si trastorno ansiedad diagnosticado formalmente "
                "(GAD, panic, social, etc). Path B gate 82."
            ),
        ),
        FieldSpec(
            "anxiolytic_initiated",
            "Anxiolítico iniciado (gate 82)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["bandelow_2017"],
            help_text=(
                "Marcar 'Sí' si anxiolítico iniciado (SSRI/buspirone/mirtazapine/"
                "pregabalin). Tracking treatment."
            ),
        ),
        # ─── Gate 83: Palliative RT decision engine ───
        FieldSpec(
            "bone_metastasis_localized_painful",
            "Bone metastasis localizada dolorosa (Path A gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["hartsell_jnci_2005", "lutz_pract_radiat_oncol_2017"],
            help_text=(
                "Marcar 'Sí' si bone metastasis localizada + dolorosa (sitio "
                "focal). Path A gate 83 — 8 Gy SF o 30 Gy/10fx según life exp."
            ),
        ),
        FieldSpec(
            "hematuria_persistent_tumoral",
            "Hematuria persistente tumoral (Path C gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_o_v5_2026"],
            help_text=(
                "Marcar 'Sí' si hematuria persistente atribuible a tumor (PCa "
                "primario o invasión vesical). Path C gate 83 — RT hemostatic "
                "20 Gy/5fx pelvis."
            ),
        ),
        FieldSpec(
            "hemoptysis_tumoral_documented",
            "Hemoptisis tumoral documentada (Path C gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_o_v5_2026"],
            help_text=(
                "Marcar 'Sí' si hemoptisis atribuible a metástasis pulmonar. "
                "Path C gate 83 — RT hemostatic 20-30 Gy/5-10fx."
            ),
        ),
        FieldSpec(
            "hemostatic_rt_indicated",
            "RT hemostatic indicada clínicamente (Path C gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_o_v5_2026"],
            help_text=(
                "Marcar 'Sí' si MDT indicó RT hemostatic (sangrado tumoral "
                "refractary). Path C gate 83."
            ),
        ),
        FieldSpec(
            "brain_metastases_documented",
            "Metástasis cerebrales documentadas (Path D gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["yamamoto_lancet_oncol_2014"],
            help_text=(
                "Marcar 'Sí' si MRI cerebral confirmó metástasis (raro PCa "
                "1-3% mCRPC). Path D gate 83 — SRS si ≤5 + <3cm, WBRT si >10."
            ),
        ),
        FieldSpec(
            "leptomeningeal_disease_documented",
            "Enfermedad leptomeningeal documentada (Path D gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024"],
            help_text=(
                "Marcar 'Sí' si LCR + MRI confirmó disease leptomeningeal "
                "(sospecha NEPC gate 67). Path D gate 83 — WBRT 30 Gy/10fx."
            ),
        ),
        FieldSpec(
            "palliative_rt_consideration_active",
            "Palliative RT consideration active (Path F gate 83)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lutz_pract_radiat_oncol_2017"],
            help_text=(
                "Marcar 'Sí' si MDT activamente considera palliative RT. Path F "
                "gate 83 — recomienda esquema según indicación."
            ),
        ),
        FieldSpec(
            "palliative_rt_dose_fractionation_planned",
            "Palliative RT esquema planeado (gate 83)",
            "select",
            options=["Desconocido", "8 Gy SF", "20 Gy/5fx", "30 Gy/10fx", "30 Gy/3-5fx SBRT", "50 Gy/4-5fx SBRT", "WBRT 30 Gy/10fx", "SRS single dose", "other"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["hartsell_jnci_2005"],
            help_text=(
                "Esquema palliative RT planeado. 8 Gy SF preferred bone pain "
                "esperanza vida ≤6m, 30 Gy/10fx para support, SBRT para oligo."
            ),
        ),
        FieldSpec(
            "palliative_rt_target_site",
            "Palliative RT sitio target (gate 83)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lutz_pract_radiat_oncol_2017"],
            help_text=(
                "Sitio target palliative RT (vertebra L3, pelvis, fémur, hígado, "
                "etc). Útil para tracking + auditoría."
            ),
        ),
        # ─── Gate 84: Oligometastatic SBRT eligibility ───
        FieldSpec(
            "total_metastases_count",
            "Count total metástasis (Path A gate 84)",
            "number",
            default="",
            unit="lesiones",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["stomp_ost_jco_2018", "oriole_phillips_jama_oncol_2020"],
            help_text=(
                "Count total metástasis actual. Path A gate 84 dispara con ≤5 "
                "+ esperanza vida >12m (oligometastatic SBRT eligibility)."
            ),
        ),
        FieldSpec(
            "life_expectancy_months",
            "Esperanza vida estimada (meses) (gate 84)",
            "number",
            default="",
            unit="meses",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=240,
            allow_negative=False,
            evidence_tags=["occam_pcothercause"],
            help_text=(
                "Esperanza vida estimada en meses (calc OCCAM o clinical "
                "judgment). Path A gate 84 requiere ≥12 meses."
            ),
        ),
        FieldSpec(
            "oligometastatic_recurrence_metachronous",
            "Oligo recurrencia metacrónica (Path B gate 84)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["stomp_ost_jco_2018"],
            help_text=(
                "Marcar 'Sí' si oligometastatic recurrence metacrónica (≤5 "
                "nuevas mets post-curative treatment). Path B gate 84 — STOMP "
                "trial-eligible."
            ),
        ),
        FieldSpec(
            "oligoprogression_under_systemic_therapy",
            "Oligoprogression bajo systemic (Path C gate 84)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lievens_radiother_oncol_2020"],
            help_text=(
                "Marcar 'Sí' si oligoprogression (≤3 sitios progressing bajo "
                "systemic therapy). Path C gate 84 — SBRT progressing sites + "
                "continuar systemic."
            ),
        ),
        FieldSpec(
            "oligometastatic_sbrt_candidate",
            "Oligometastatic SBRT candidate (Path D gate 84)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sabr_comet_palma_lancet_2019"],
            help_text=(
                "Marcar 'Sí' si MDT considera SBRT oligometastatic curative-"
                "intent. Path D gate 84."
            ),
        ),
        FieldSpec(
            "oligometastatic_category",
            "Oligometastatic categoría (gate 84)",
            "select",
            options=["Desconocido", "synchronous", "metachronous_oligorecurrence", "oligoprogression", "oligopersistence"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["lievens_radiother_oncol_2020"],
            help_text=(
                "Categoría oligometastatic ESTRO/EORTC: synchronous (al dx), "
                "metachronous_oligorecurrence (post-treatment), oligoprogression "
                "(bajo systemic), oligopersistence (residual stable)."
            ),
        ),
        FieldSpec(
            "psma_pet_staging_recent",
            "PSMA-PET staging reciente (gate 84)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["promise_hofman_lancet_2020"],
            help_text=(
                "Marcar 'Sí' si PSMA-PET staging reciente (<3 meses) confirma "
                "oligo + descarta sitios ocultos. Crítico para SBRT planning."
            ),
        ),
        FieldSpec(
            "sbrt_target_sites_planned",
            "SBRT target sites planeados (gate 84)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sabr_comet_palma_lancet_2019"],
            help_text=(
                "Lista sitios target SBRT planeados (vertebra T7, lymph node "
                "iliac, lung mets RUL, etc). Útil para planning + auditoría."
            ),
        ),
        FieldSpec(
            "sbrt_dose_fractionation_per_site",
            "SBRT dose/fractionation per site (gate 84)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["sabr_comet_palma_lancet_2019"],
            help_text=(
                "Esquema SBRT por sitio (24 Gy SF bone, 30 Gy/3fx vertebra, "
                "50 Gy/4fx lung peripheral, etc)."
            ),
        ),
        # ─── Gate 85: Cachexia pharmacotherapy ───
        FieldSpec(
            "weight_loss_percent_6mo",
            "Pérdida peso % en 6 meses (Path A/B/C gate 85)",
            "number",
            default="",
            unit="%",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=100,
            allow_negative=False,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Pérdida peso porcentual en 6 meses (sin condicionantes). "
                "Path A gate 85 dispara >5%. Path B con BMI <20 + >2%. Path C "
                "con sarcopenia + >2%."
            ),
        ),
        FieldSpec(
            "bmi",
            "Body Mass Index (BMI) (Path B gate 85)",
            "number",
            default="",
            unit="kg/m²",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=10,
            max_value=70,
            allow_negative=False,
            reference_range_low=18.5,
            reference_range_high=25,
            reference_range_unit="kg/m²",
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "BMI = peso (kg) / altura² (m²). Path B gate 85 dispara <20 + "
                "weight loss >2%."
            ),
        ),
        FieldSpec(
            "sarcopenia_documented",
            "Sarcopenia documentada (Path C gate 85)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Marcar 'Sí' si sarcopenia confirmed (DEXA, CT L3 muscle area, "
                "MRI). Path C gate 85 + weight loss >2%."
            ),
        ),
        FieldSpec(
            "appetite_loss_documented",
            "Appetite loss documentada (Path D gate 85)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Marcar 'Sí' si anorexia/appetite loss documentado clínicamente. "
                "Path D gate 85 + cachexia clinical diagnosed."
            ),
        ),
        FieldSpec(
            "cachexia_clinical_diagnosed",
            "Cachexia clínica diagnosticada (Path D gate 85)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Marcar 'Sí' si cachexia diagnosticada formalmente per Fearon "
                "2011 criteria. Path D gate 85."
            ),
        ),
        FieldSpec(
            "cachexia_stage",
            "Cachexia stage (gate 85)",
            "select",
            options=["Desconocido", "pre_cachexia", "cachexia", "refractory_cachexia"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Stage cachexia per Fearon: pre_cachexia (≤5% + síntomas), "
                "cachexia (>5% + síntomas asociados), refractory_cachexia "
                "(procatabolismo + life exp <3m)."
            ),
        ),
        FieldSpec(
            "pg_sga_score",
            "PG-SGA score (Patient-Generated Subjective Global Assessment)",
            "number",
            default="",
            unit="score",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=50,
            allow_negative=False,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "PG-SGA score (0-50). 0-1 well-nourished, 2-3 mild malnutrition, "
                "4-8 moderate, 9+ severe. Útil tracking nutritional status."
            ),
        ),
        FieldSpec(
            "current_weight_kg",
            "Peso actual (kg) (gate 85)",
            "number",
            default="",
            unit="kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=20,
            max_value=300,
            allow_negative=False,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Peso actual paciente (kg). Comparator weight_loss_percent_6mo."
            ),
        ),
        FieldSpec(
            "baseline_weight_kg",
            "Peso baseline 6m antes (kg) (gate 85)",
            "number",
            default="",
            unit="kg",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=20,
            max_value=300,
            allow_negative=False,
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Peso baseline 6 meses antes (kg). Comparator para calcular "
                "weight_loss_percent_6mo."
            ),
        ),
        FieldSpec(
            "albumin_g_dl",
            "Albúmina sérica (g/dL) (gate 85 inflamación marker)",
            "number",
            default="",
            unit="g/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=10,
            allow_negative=False,
            reference_range_low=3.5,
            reference_range_high=5.0,
            reference_range_unit="g/dL",
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Albúmina sérica. <3.5 sugiere malnutrición/inflamación. <2.5 "
                "severa. Marker indirecto procatabolismo cachexia."
            ),
        ),
        FieldSpec(
            "prealbumin_mg_dl",
            "Prealbúmina sérica (mg/dL) (gate 85)",
            "number",
            default="",
            unit="mg/dL",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=50,
            allow_negative=False,
            reference_range_low=15,
            reference_range_high=36,
            reference_range_unit="mg/dL",
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "Prealbúmina (transthyretin). T½ 2 días — marker más rápido "
                "que albumin para nutritional status changes."
            ),
        ),
        FieldSpec(
            "crp_mg_l",
            "PCR (Proteína C Reactiva) (mg/L) (gate 85 inflamación)",
            "number",
            default="",
            unit="mg/L",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            min_value=0,
            max_value=500,
            allow_negative=False,
            reference_range_low=0,
            reference_range_high=10,
            reference_range_unit="mg/L",
            evidence_tags=["fearon_cachexia_2011"],
            help_text=(
                "PCR sérica. >10 mg/L sugiere inflamación sistémica. Componente "
                "diagnóstico cachexia (Fearon 2011 + GLIM criteria)."
            ),
        ),
        # ── Gates 67B/67C/69B Pre-Dx + MDT + Hereditary (Faubot LXXXIV / Iter #1) ──
        # 🆕 Subspecialty oncourología: pre-dx scenarios + MDT decision tracking
        # + genomic testing tracking + hereditary cancer panel.
        # ─── Gate 67B: NEPC pre-biopsy suspicion ───
        FieldSpec(
            "clinical_nepc_suspicion_pre_biopsy",
            "Sospecha clínica NEPC pre-biopsia (Path C gate 67B)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024", "mostaghel_jco_2014"],
            help_text=(
                "Marcar 'Sí' si MDT documentó sospecha clínica NEPC ANTES de "
                "biopsia confirmatoria (LDH muy elevada + PSA paradójicamente "
                "alto + visceral mets prominentes + curso agresivo). Path C "
                "gate 67B — biopsia metastásica urgente + considerar EP empírico."
            ),
        ),
        # ─── Gate 67C: cT4 sin biopsia hard_block + DRE finality ───
        FieldSpec(
            "dre_fixation",
            "DRE — fijación cápsula prostática (gate 67C)",
            "select",
            options=["Desconocido", "No", "Sospecha", "Confirmada", "T4_fijo_petreo"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aua_guidelines_2024", "eau_2026_section_5_3"],
            help_text=(
                "Tacto rectal — fijación de la próstata a tejidos pélvicos. "
                "'Confirmada' o 'T4_fijo_petreo' = lesión clínica T4 (gate 67C "
                "hard_block decisión RP/RT hasta histología confirmada O "
                "presumptive virtually_certain)."
            ),
        ),
        FieldSpec(
            "decision_rp_vs_rt_active",
            "Decisión modalidad local RP vs RT activa (gate 67C, 70)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si MDT activamente considera tratamiento local "
                "(prostatectomía radical o radioterapia curativa o brachy). "
                "Componente trigger gate 67C (cT4 sin biopsia bloquea decisión)."
            ),
        ),
        FieldSpec(
            "planning_radical_prostatectomy",
            "Planning RP (prostatectomía radical) activo (gate 67C)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si RP está activamente planeada. Componente trigger "
                "gate 67C — requires histología confirmada antes de cirugía."
            ),
        ),
        FieldSpec(
            "planning_radiotherapy_curative",
            "Planning RT curativa activo (gate 67C)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si RT curativa está activamente planeada. Componente "
                "trigger gate 67C — requires histología confirmada antes de RT."
            ),
        ),
        FieldSpec(
            "presumptive_treatment_documented_with_2week_biopsy_plan",
            "Tratamiento presuntivo + biopsia agendada 2 sem (override gate 67C)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["clinical_provisional_diagnosis_engine"],
            help_text=(
                "Marcar 'Sí' SOLO si presumptive_diagnosis_tier ≥ highly_probable "
                "+ biopsia formalmente agendada en próximas 2 semanas + "
                "documentación HC. Override gate 67C (permite ADT empírico antes "
                "de resultado biopsia)."
            ),
        ),
        FieldSpec(
            "histology_confirmed_metastatic_site",
            "Histología confirmada en sitio metastásico (gate 66/67C link)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_2_v5_2026"],
            help_text=(
                "Marcar 'Sí' si biopsia metastásica (sitio accesible: hepática, "
                "ósea, ganglionar, pulmonar) confirmó adenocarcinoma de próstata. "
                "Override gate 67C + complementa gate 66."
            ),
        ),
        # ─── Gate 69B: PSA velocity pre-biopsia urgent ───
        FieldSpec(
            "prior_radiation_therapy_documented",
            "Radioterapia previa documentada (gate 54/58/69B)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si paciente tiene historia documentada de RT prostática "
                "previa (curativa o paliativa). Componente para excluir gate 69B "
                "(pre-biopsy kinetics) y activar gate 54 (PSA bounce post-RT)."
            ),
        ),
        FieldSpec(
            "psa_velocity_pre_biopsy_urgent_documented",
            "PSA velocity pre-biopsia urgente documentada (Path C gate 69B)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["d_amico_jnci_1995", "carter_jnci_2006"],
            help_text=(
                "Marcar 'Sí' si urology/oncology documentó PSA velocity >20 ng/mL/"
                "año + sin biopsia previa + sin RP/RT previa = biopsia urgente "
                "<2 semanas. Path C gate 69B."
            ),
        ),
        # ─── Cross-cutting: MDT shared decision tracking ───
        FieldSpec(
            "mdt_shared_decision_date",
            "Fecha decisión MDT compartida (cross-cutting LXXXIV)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_prostate_v5_2026", "eau_2026_section_6"],
            help_text=(
                "Fecha de la reunión MDT (Multidisciplinary Team) donde se "
                "consensuó la decisión clínica. Crítico para auditabilidad + "
                "documentar que decisión NO fue unilateral."
            ),
        ),
        FieldSpec(
            "mdt_providers_present",
            "Especialidades MDT presentes en decisión (cross-cutting LXXXIV)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_prostate_v5_2026"],
            help_text=(
                "Lista de especialidades presentes (separadas por coma): "
                "uro, radonc, oncology, palliative, genetic, pathology, etc. "
                "Documentar quién participó en la decisión MDT."
            ),
        ),
        FieldSpec(
            "patient_preferences_vs_recommendation",
            "Preferencias paciente vs recomendación MDT (cross-cutting LXXXIV)",
            "select",
            options=["Desconocido", "concordant", "divergent_informed_refusal", "divergent_unknown_reason", "pending_discussion"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_shared_decision_2024"],
            help_text=(
                "Documentar si decisión paciente fue concordante con recomendación "
                "MDT. 'divergent_informed_refusal' = paciente eligió contra "
                "recomendación tras informed consent (autonomía paciente, válido). "
                "Crítico para audit trail + ética clínica."
            ),
        ),
        # ─── Cross-cutting: Genomic testing tracking centralizado ───
        FieldSpec(
            "genomic_test_ordered_date",
            "Fecha orden test genómico HRR/AR-V7/CDK12/MSI (cross-cutting LXXXIV)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Fecha en que se solicitó el test genómico (HRR panel, AR-V7, "
                "CDK12, MSI/MMR, comprehensive HRD). Útil para tracking + "
                "evitar gate 61 hard_block PARP si test pending."
            ),
        ),
        FieldSpec(
            "genomic_test_provider",
            "Lab provider test genómico (cross-cutting LXXXIV)",
            "select",
            options=["Desconocido", "Foundation_Medicine", "Caris_Life_Sciences", "Tempus", "Guardant_Health", "MyriadGenetics", "Color_Health", "germline_in_house", "other"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Lab provider del test genómico. Util para tracking turnaround "
                "time esperado (Foundation/Caris/Tempus ~14d, Myriad ~21d)."
            ),
        ),
        FieldSpec(
            "genomic_test_expected_result_date",
            "Fecha esperada resultado test genómico (cross-cutting LXXXIV)",
            "date",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Fecha esperada de resultado. Componente del override "
                "`hrr_test_pending_with_2week_plan_documented` para gate 61 "
                "(permite considerar PARP futuro mientras espera)."
            ),
        ),
        FieldSpec(
            "hrr_test_pending_with_2week_plan_documented",
            "HRR test pending con plan 2 semanas documentado (override gate 61)",
            "select",
            options=["Desconocido", "No", "Sí"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_pros_g_v5_2026"],
            help_text=(
                "Marcar 'Sí' si HRR test ordenado + lab confirmado + fecha "
                "esperada resultado <2 semanas + plan documentado. Override "
                "gate 61 hard_block (permite considerar PARP en 2 sem)."
            ),
        ),
        # ─── Cross-cutting: Hereditary cancer panel ───
        FieldSpec(
            "family_history_pca_under_55",
            "Historia familiar PCa <55 años (cross-cutting LXXXIV)",
            "select",
            options=["Desconocido", "No", "Sí_1_familiar", "Sí_2_o_más_familiares"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_genetic_familial_v3_2026"],
            help_text=(
                "Familiar de primer grado (padre, hermano, hijo) con PCa "
                "diagnosticado <55 años. Indicación germline testing + "
                "genetic counseling (NCCN cat 1)."
            ),
        ),
        FieldSpec(
            "family_history_brca_breast_ovarian",
            "Historia familiar BRCA/breast/ovarian (cross-cutting LXXXIV)",
            "select",
            options=["Desconocido", "No", "Sí_breast", "Sí_ovarian", "Sí_both", "Sí_brca_confirmed"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["nccn_genetic_familial_v3_2026"],
            help_text=(
                "Historia familiar BRCA1/2 confirmado o cáncer de mama/ovario "
                "en familiares cercanos. Indicación germline BRCA testing + "
                "genetic counseling (NCCN cat 1)."
            ),
        ),
        FieldSpec(
            "germline_test_refused_reason",
            "Razón refusal germline testing (cross-cutting LXXXIV)",
            "text",
            default="",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["asco_genetic_counseling_2024"],
            help_text=(
                "Si paciente refusal germline testing tras genetic counseling, "
                "documentar razón (ej. costo, religion, family pressure, no "
                "implications offspring). Crítico para audit trail."
            ),
        ),
        # ─── NEPC platinum-EP regimen flag ───
        FieldSpec(
            "nepc_platinum_ep_regimen_active",
            "NEPC EP regimen (carboplatin + etoposide) activo (gate 67)",
            "select",
            options=["Desconocido", "No", "Sí_iniciado", "Sí_completado_4_6_ciclos"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["aparicio_eur_urol_2024_nepc"],
            help_text=(
                "Marcar si paciente NEPC confirmado está bajo EP regimen "
                "(carboplatin AUC 5 D1 + etoposide 100 mg/m² D1-3 cada 3 sem × "
                "4-6 ciclos). Componente regimen_selector m1_crpc para NEPC."
            ),
        ),
        # ─── Imaging modality choice nmCRPC ───
        FieldSpec(
            "imaging_modality_used_for_m_staging",
            "Modalidad imaging usada para staging M (gate nmCRPC)",
            "select",
            options=["Desconocido", "CT_only", "CT_plus_bone_scan", "PSMA_PET", "PSMA_PET_plus_CT", "MRI_whole_body", "FDG_PET"],
            default="Desconocido",
            group=group,
            group_order=group_order,
            clinical_role=role_value,
            evidence_tags=["spartan_smith_jama_oncol_2018", "promise_hofman_lancet_2020"],
            help_text=(
                "Modalidad imaging usada para confirmar M0 status. Si PSA 0.5-2 "
                "ng/mL → PSMA PET preferido (más sensible que CT/bone scan). "
                "SPARTAN/PROSPER/ARAMIS criteria + PROMISE recommendations."
            ),
        ),
    ]
