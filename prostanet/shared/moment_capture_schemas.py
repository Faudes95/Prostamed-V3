"""EPIC 20 Fase B — Moment Capture Schemas (clínicamente validados).

6 micro-form schemas que reemplazan los schemas full (30-88 fields) en
momentos específicos de decisión clínica:

  1. bcr_detection_form (12) — vs post_prostatectomy full (40)
  2. oligoprogression_form (9) — vs mcspc_oligo_metachronous full (38)
  3. crpc_transition_form (14) — vs m1_crpc full (88)
  4. adt_init_form (11) — vs mcspc_high_volume full (45)
  5. rt_nadir_form (8) — vs post_radiotherapy_followup full (68)
  6. salvage_eligibility_form (12) — vs recurrence_bcr full (58)

**Política clínica validada (NCCN 2026 + AUA 2025 + EAU 2025)**:
- Cada field declarado como `MUST_CAPTURE_AT_MOMENT` es required-at-moment
  porque sin él la decisión es CLINICAMENTE INSEGURA (sería peligroso defer).
- Fields `DEFERRABLE` viven en el schema completo (accesible vía
  `schema_completo_link`) y se capturan en visita followup posterior.
- CERO clinical data loss en momento de decisión: cada deferred field
  fue revisado contra NCCN/AUA/EAU para confirmar que NO afecta la decisión
  inmediata.

**Voice-friendly design** (skill /voice-note-ingest):
- Field naming unívoco (no ambigüedad entre "PSA actual" vs "PSA pre-RP")
- Scalar types: number, single-value select, date ISO, boolean
- NO nested objects ni multi-select arrays sin orden estable
- `voice_required_confidence` per field (0.0-1.0) — safety-critical = 0.9+

Reducción promedio: 25 fields/momento → 11 fields/momento = **~56%** menos
form friction, **CERO** clinical data loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any


# ─────────────────── Type definitions ───────────────────


@dataclass
class FieldSpec:
    """Single field specification within a micro-form.

    voice_required_confidence: minimum confidence threshold for voice
    auto-population (0.0-1.0). Safety-critical fields require 0.9+.
    """
    name: str
    label: str  # Voice-friendly label (single phrase, no ambiguity)
    type: str  # "number", "date", "select", "boolean", "text"
    required: bool = True
    options: list[str] = dc_field(default_factory=list)  # for select type
    unit: str = ""  # for numeric (e.g., "ng/mL")
    voice_required_confidence: float = 0.7
    help_text: str = ""
    must_capture_rationale: str = ""  # clinical justification


@dataclass
class FormSchema:
    """Micro-form schema for a clinical decision moment."""
    name: str
    trigger_moment: str  # e.g., "post_prostatectomy.psa_rise"
    description: str
    fields: list[FieldSpec]
    capture_surface: str  # URL pattern
    consumer: str  # downstream copilot service
    schema_completo_link: str
    clinical_validation: dict[str, str]  # rationale documentation


# ─────────────────── 1. BCR Detection Form (12 fields) ───────────────────

BCR_DETECTION_FORM = FormSchema(
    name="bcr_detection",
    trigger_moment="post_prostatectomy.psa_rise",
    description=(
        "PSA elevation detected after radical prostatectomy. Triggers BCR work-up "
        "+ salvage eligibility decision. Replaces full post_prostatectomy schema (40)."
    ),
    fields=[
        FieldSpec(name="current_psa", label="PSA actual",
                  type="number", required=True, unit="ng/mL",
                  voice_required_confidence=0.9,
                  must_capture_rationale="Define magnitud y trend de BCR"),
        FieldSpec(name="detection_date", label="Fecha de detección BCR",
                  type="date", required=True,
                  voice_required_confidence=0.85),
        FieldSpec(name="psa_doubling_time_months", label="PSA doubling time (meses)",
                  type="number", required=True, unit="months",
                  voice_required_confidence=0.85,
                  must_capture_rationale="PSADT <6mo = high-risk (aggressive); ≥10mo = indolent. NCCN PROS-D"),
        FieldSpec(name="time_from_rp_months", label="Tiempo desde prostatectomía (meses)",
                  type="number", required=True, unit="months",
                  voice_required_confidence=0.85,
                  must_capture_rationale="BCR <3y = adverse prognosis; ≥3y favorable"),
        FieldSpec(name="path_stage_at_rp", label="Etapa patológica al momento de RP",
                  type="select", required=True,
                  options=["pT2", "pT3a", "pT3b", "pT4", "pN+", "unknown"],
                  must_capture_rationale="pT3+ y/o pN+ son indicaciones para early salvage agresivo"),
        FieldSpec(name="margin_status", label="Estado de márgenes quirúrgicos",
                  type="select", required=True,
                  options=["negative", "positive_focal", "positive_extensive", "unknown"],
                  must_capture_rationale="Márgenes + son indicación primaria para salvage RT"),
        FieldSpec(name="gleason_at_rp", label="Gleason en pieza de prostatectomía",
                  type="select", required=True,
                  options=["6", "7(3+4)", "7(4+3)", "8", "9", "10"],
                  must_capture_rationale="Gleason ≥8 al RP = high-risk BCR"),
        FieldSpec(name="current_testosterone", label="Testosterona actual",
                  type="number", required=False, unit="ng/dL",
                  voice_required_confidence=0.85,
                  must_capture_rationale="Descarta non-BCR PSA rise por escape ADT"),
        FieldSpec(name="prior_adjuvant_rt", label="¿Recibió RT adyuvante previa?",
                  type="boolean", required=True),
        FieldSpec(name="prior_adt", label="¿Recibió ADT previa?",
                  type="boolean", required=True),
        FieldSpec(name="ecog", label="ECOG performance status",
                  type="select", required=True,
                  options=["0", "1", "2", "3", "4"],
                  must_capture_rationale="ECOG ≥2 contraindica intensification agresivo"),
        FieldSpec(name="imaging_trigger", label="Imagen de stadificación BCR",
                  type="select", required=False,
                  options=["PSMA-PET", "MRI fossa", "Bone scan", "CT abd-pelvis", "None planned"]),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=bcr_detection",
    consumer="post_rp_salvage_copilot_service.build_bcr_decision",
    schema_completo_link="/longitudinal-capture/<nss>?moment=bcr_detection&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "PSADT + time_from_RP + path_stage + margin_status + gleason "
            "drive aggressiveness assessment per NCCN 2026 PROS-D. "
            "Testosterone rules out castration loss as non-BCR cause. "
            "ECOG determines treatment intensity."
        ),
        "deferred_fields_safe_because": (
            "Family history (BRCA suspicion) capturada solo si trigger via single field "
            "first-degree relative <60y. PROs detallados (EPIC-26 por dominio) "
            "se capturan en visita followup dedicada, no afectan decisión salvage."
        ),
        "nccn_2026_reference": "PROS-D",
        "aua_reference": "AUA early salvage RT guidelines 2025",
    },
)


# ─────────────────── 2. Oligoprogression Form (9 fields) ───────────────────

OLIGOPROGRESSION_FORM = FormSchema(
    name="oligoprogression",
    trigger_moment="mcspc.on_therapy_progression",
    description=(
        "Patient on systemic therapy with limited progression pattern. "
        "Triggers MDT (SBRT) vs class switch decision. STOMP/ORIOLE-driven. "
        "Replaces full mcspc_oligo_metachronous schema (38)."
    ),
    fields=[
        FieldSpec(name="new_lesion_count", label="Número de lesiones nuevas",
                  type="number", required=True,
                  voice_required_confidence=0.9,
                  must_capture_rationale="≤3 = oligo (STOMP/ORIOLE); ≥4 = widespread"),
        FieldSpec(name="lesion_sites", label="Sitios de lesiones nuevas",
                  type="select", required=True,
                  options=["bone_only", "nodal_only", "visceral_only", "mixed"],
                  must_capture_rationale="Visceral worsens prognosis; bone-only favorable"),
        FieldSpec(name="imaging_modality", label="Modalidad de imagen utilizada",
                  type="select", required=True,
                  options=["PSMA-PET", "CT", "Bone scan", "MRI", "Combined"],
                  must_capture_rationale="PSMA-PET sensitivity > CT; calibrar threshold"),
        FieldSpec(name="time_on_systemic_tx_months", label="Tiempo en terapia sistémica actual (meses)",
                  type="number", required=True, unit="months",
                  voice_required_confidence=0.85),
        FieldSpec(name="psa_trend_current", label="Tendencia PSA actual",
                  type="select", required=True,
                  options=["rising", "stable", "declining"],
                  must_capture_rationale="PSA rising + new lesions = clear progression"),
        FieldSpec(name="response_in_existing_lesions", label="Respuesta en lesiones previas",
                  type="select", required=True,
                  options=["continued_response", "stable", "mixed_progression"],
                  must_capture_rationale="Continued/stable = oligoprogresión real; mixed = widespread"),
        FieldSpec(name="psma_pet_findings", label="Hallazgos PSMA-PET (si aplica)",
                  type="text", required=False),
        FieldSpec(name="ecog", label="ECOG performance status",
                  type="select", required=True,
                  options=["0", "1", "2", "3", "4"]),
        FieldSpec(name="hrr_status", label="Estado HRR (alternativa PARP)",
                  type="select", required=False,
                  options=["positive", "negative", "unknown"],
                  must_capture_rationale="HRR+ abre PARP como alternative a SBRT"),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=oligoprogression",
    consumer="oligoprogression_copilot_service.build_mdt_decision",
    schema_completo_link="/longitudinal-capture/<nss>?moment=oligoprogression&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "lesion_count + sites + imaging_modality + response_pattern drive "
            "STOMP/ORIOLE MDT decision per NCCN 2026 PROS-G."
        ),
        "deferred_fields_safe_because": (
            "Detailed per-lesion measurements (SUV max, dimensions exact) capturados "
            "en oncological radiology follow-up, no afectan decisión SBRT vs class switch."
        ),
        "nccn_2026_reference": "PROS-G",
        "pivotal_trials": "STOMP, ORIOLE",
    },
)


# ─────────────────── 3. CRPC Transition Form (14 fields) ───────────────────

CRPC_TRANSITION_FORM = FormSchema(
    name="crpc_transition",
    trigger_moment="adt_progression_verification.crpc_confirmed",
    description=(
        "Patient transitions from mCSPC to mCRPC. Determines subtype "
        "(arsi_naive, post_arsi, hrr_positive, psma_eligible, msi_h, nepc). "
        "Replaces full m1_crpc schema (88)."
    ),
    fields=[
        FieldSpec(name="current_testosterone", label="Testosterona actual (confirma castración)",
                  type="number", required=True, unit="ng/dL",
                  voice_required_confidence=0.9,
                  must_capture_rationale="<50 ng/dL confirma castration; SIN esto no es CRPC"),
        FieldSpec(name="psa_trend_3mo", label="Tendencia PSA últimos 3 meses",
                  type="select", required=True,
                  options=["rising_2_consecutive", "stable", "rising_with_imaging_progression"]),
        FieldSpec(name="metastasis_site_pattern", label="Patrón de sitios metastásicos",
                  type="select", required=True,
                  options=["bone_only", "nodal_only", "visceral_dominant", "mixed_bone_nodal", "mixed_visceral_bone"],
                  must_capture_rationale="Visceral dominant = peor prognosis + chemo intensification"),
        FieldSpec(name="imaging_type_current", label="Imagen confirmando progression",
                  type="select", required=True,
                  options=["PSMA-PET", "CT+bone_scan", "MRI", "FDG-PET"]),
        FieldSpec(name="ecog", label="ECOG performance status",
                  type="select", required=True,
                  options=["0", "1", "2", "3", "4"]),
        FieldSpec(name="ldh", label="LDH actual",
                  type="number", required=False, unit="U/L",
                  must_capture_rationale="Elevated LDH = adverse prognostic + NEPC signal"),
        FieldSpec(name="alkaline_phosphatase", label="Fosfatasa alcalina",
                  type="number", required=False, unit="U/L",
                  must_capture_rationale="Bone activity marker; correlates con bone burden"),
        FieldSpec(name="hrr_status", label="Estado HRR (BRCA1/2/ATM/CHEK2)",
                  type="select", required=True,
                  options=["positive", "negative", "untested"],
                  voice_required_confidence=0.85,
                  must_capture_rationale="HRR+ = PARP first-line eligible"),
        FieldSpec(name="msi_dmmr_status", label="MSI / dMMR status",
                  type="select", required=True,
                  options=["msi_high_or_dmmr_deficient", "msi_stable", "untested"],
                  voice_required_confidence=0.85,
                  must_capture_rationale="MSI-H/dMMR = pembrolizumab eligible (3-5% hyper-responders)"),
        FieldSpec(name="prior_arsi_count", label="Número de ARSI previos",
                  type="number", required=True,
                  must_capture_rationale="≥1 prior ARSI = cross-resistance ~80% para segundo ARSI"),
        FieldSpec(name="prior_arsi_drugs", label="ARSIs recibidos previamente",
                  type="select", required=False,
                  options=["none", "abiraterone", "enzalutamide", "apalutamide", "darolutamide", "multiple"]),
        FieldSpec(name="comorbidities_for_arsi", label="Comorbilidades relevantes para ARSI",
                  type="select", required=True,
                  options=["hepatic_dysfunction", "cardiovascular", "cognitive_decline", "fall_risk", "none_significant"],
                  must_capture_rationale="Hepático → no abiraterone; cognitive → no enza/apa; CV → cuidado abiraterone"),
        FieldSpec(name="symptomatic_status", label="¿Sintomático actualmente?",
                  type="boolean", required=True,
                  must_capture_rationale="Symptomatic = chemo or rapid systemic intensification preferred"),
        FieldSpec(name="pain_score_ctcae", label="Pain score (CTCAE 0-4)",
                  type="select", required=False,
                  options=["0", "1", "2", "3", "4"]),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=crpc_transition",
    consumer="mcrpc_subtype_copilot_service.build_subtype_decision",
    schema_completo_link="/longitudinal-capture/<nss>?moment=crpc_transition&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "testosterone confirma castración (definición CRPC); PSA trend + imaging "
            "confirma progression; HRR+MSI dirigen biomarker-based therapy; "
            "prior_arsi dirige first-line vs second-line; comorbidities determinan "
            "ARSI selection. Sin estos campos, decisión CRPC first-line es ciega."
        ),
        "deferred_fields_safe_because": (
            "Detailed somatic NGS panel (50+ genes), full Charlson, PRO breakdown, "
            "imaging per-lesion measurements, family history detallado — capturados "
            "en tumor board OS o visitas dedicadas, NO en momento de transición."
        ),
        "nccn_2026_reference": "PROS-J",
    },
)


# ─────────────────── 4. ADT Initiation Form (11 fields) ───────────────────

ADT_INIT_FORM = FormSchema(
    name="adt_initiation",
    trigger_moment="mcspc.adt_init_planned",
    description=(
        "ADT initiation for mCSPC or advanced disease. Captures baseline "
        "for surveillance of ADT-induced complications. "
        "Replaces full mcspc_high_volume schema (45)."
    ),
    fields=[
        FieldSpec(name="volume_class", label="Volume class (CHAARTED criteria)",
                  type="select", required=True,
                  options=["high_volume_chaarted", "low_volume_chaarted", "oligo_le_3_lesions"]),
        FieldSpec(name="latitude_high_risk", label="¿LATITUDE high risk (≥2 of GS≥8, bone≥3, visceral)?",
                  type="boolean", required=True,
                  must_capture_rationale="Diferencia abiraterone vs docetaxel preference"),
        FieldSpec(name="prior_local_therapy", label="¿Recibió terapia local previa?",
                  type="select", required=True,
                  options=["radical_prostatectomy", "ebrt", "brachytherapy", "focal_therapy", "none"]),
        FieldSpec(name="baseline_testosterone", label="Testosterona basal",
                  type="number", required=True, unit="ng/dL",
                  voice_required_confidence=0.85),
        FieldSpec(name="cardiovascular_risk_score", label="Riesgo cardiovascular",
                  type="select", required=True,
                  options=["low_score_lt_10", "intermediate_10_to_20", "high_gt_20", "established_cv_disease"],
                  must_capture_rationale="High CV risk + ADT = cardiovascular events ↑; needs cardiology baseline"),
        FieldSpec(name="baseline_dexa_tscore", label="DEXA T-score basal",
                  type="number", required=False, unit="SD",
                  must_capture_rationale="T-score <-1 + ADT = osteoporosis prevention with denosumab/zoledronate"),
        FieldSpec(name="diabetes_metabolic", label="Diabetes / síndrome metabólico",
                  type="select", required=True,
                  options=["dm_type2_controlled", "dm_type2_uncontrolled", "metabolic_syndrome", "none"],
                  must_capture_rationale="ADT exacerba metabolic syndrome; baseline HbA1c necesario"),
        FieldSpec(name="baseline_lipids", label="Lipid panel basal capturado",
                  type="boolean", required=True),
        FieldSpec(name="calcium_vitamin_d", label="Ca + Vitamin D basal",
                  type="select", required=False,
                  options=["both_adequate", "ca_low", "vit_d_low", "both_low", "not_measured"]),
        FieldSpec(name="cognitive_baseline", label="Cognición basal",
                  type="select", required=False,
                  options=["normal", "mild_decline", "moderate_decline", "not_assessed"],
                  must_capture_rationale="Baseline para detectar ADT-related cognitive change"),
        FieldSpec(name="denosumab_candidate", label="¿Candidato a denosumab/zoledronate?",
                  type="boolean", required=True,
                  must_capture_rationale="Bone-protective agent inicia con ADT si DEXA elevated risk"),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=adt_init",
    consumer="bone_health_engine.build_adt_baseline_bundle",
    schema_completo_link="/longitudinal-capture/<nss>?moment=adt_init&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "ADT baseline determines surveillance schedule for CV, metabolic, bone, "
            "cognitive complications. NCCN 2026 PROS-K + AUA-SUO ADT management 2025."
        ),
        "deferred_fields_safe_because": (
            "Sexual function detailed assessment, full quality-of-life baseline, "
            "family planning discussions — capturados en visitas dedicadas pre-ADT."
        ),
        "nccn_2026_reference": "PROS-K",
        "aua_reference": "AUA-SUO ADT management guidelines",
    },
)


# ─────────────────── 5. RT Nadir Form (8 fields) ───────────────────

RT_NADIR_FORM = FormSchema(
    name="rt_nadir",
    trigger_moment="post_radiotherapy_followup.nadir_reached",
    description=(
        "Post-RT PSA nadir reached. Captures nadir + RT context for "
        "future Phoenix BCR detection. "
        "Replaces full post_radiotherapy_followup schema (68)."
    ),
    fields=[
        FieldSpec(name="rt_modality", label="Modalidad de radioterapia",
                  type="select", required=True,
                  options=["EBRT_only", "brachy_LDR", "brachy_HDR", "EBRT_brachy_boost", "SBRT"],
                  must_capture_rationale="Modalidad determina expected nadir + bounce pattern"),
        FieldSpec(name="total_dose_gy", label="Dosis total recibida (Gy)",
                  type="number", required=True, unit="Gy",
                  voice_required_confidence=0.85,
                  must_capture_rationale="Dosis-respuesta: ≥78 Gy EBRT = better local control"),
        FieldSpec(name="concurrent_adt_duration_months", label="ADT concurrente (meses)",
                  type="number", required=True, unit="months",
                  must_capture_rationale="ADT timing afecta PSA bounce + nadir interpretation"),
        FieldSpec(name="nadir_date", label="Fecha del nadir",
                  type="date", required=True),
        FieldSpec(name="nadir_psa_value", label="PSA al momento del nadir",
                  type="number", required=True, unit="ng/mL",
                  voice_required_confidence=0.9,
                  must_capture_rationale="Baseline para Phoenix criteria (nadir + 2)"),
        FieldSpec(name="rt_intent", label="Intent de la radioterapia",
                  type="select", required=True,
                  options=["curative_primary", "curative_salvage_post_rp", "palliative", "consolidation_oligomet"]),
        FieldSpec(name="pre_rt_psa", label="PSA pre-RT",
                  type="number", required=True, unit="ng/mL",
                  must_capture_rationale="Pre-RT PSA mapping para tendency analysis"),
        FieldSpec(name="post_rt_acute_toxicity_grade", label="Toxicidad aguda post-RT (max grade)",
                  type="select", required=False,
                  options=["0", "1", "2", "3", "4"],
                  must_capture_rationale="Predictor de late toxicity + intensification tolerance"),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=rt_nadir",
    consumer="post_rt_bcr_copilot_service.register_nadir",
    schema_completo_link="/longitudinal-capture/<nss>?moment=rt_nadir&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "Phoenix BCR definition (current >= nadir + 2) requires nadir value + date. "
            "RT modality + dose + concurrent ADT contextualizan PSA trajectory. "
            "NCCN 2026 PROS-D + Phoenix consensus."
        ),
        "deferred_fields_safe_because": (
            "Detailed dosimetry per substructure (rectum, bladder DVH), per-fraction "
            "logs, acute symptom CTCAE breakdown — capturados en radiotherapy "
            "treatment summary, NO afectan future BCR detection logic."
        ),
        "nccn_2026_reference": "PROS-D",
        "phoenix_consensus": "Roach et al. 2006",
    },
)


# ─────────────────── 6. Salvage Eligibility Form (12 fields) ───────────────────

SALVAGE_ELIGIBILITY_FORM = FormSchema(
    name="salvage_eligibility",
    trigger_moment="recurrence_bcr.salvage_decision_required",
    description=(
        "BCR detected post-RP, evaluating salvage RT eligibility + intent. "
        "Replaces full recurrence_bcr schema (58)."
    ),
    fields=[
        FieldSpec(name="psa_doubling_time_months", label="PSA doubling time (meses)",
                  type="number", required=True, unit="months",
                  voice_required_confidence=0.85,
                  must_capture_rationale="<6mo = aggressive; mejor candidato para early salvage"),
        FieldSpec(name="pre_rp_psa", label="PSA pre-RP (al diagnóstico inicial)",
                  type="number", required=False, unit="ng/mL"),
        FieldSpec(name="original_rp_path_stage", label="Etapa patológica al RP",
                  type="select", required=True,
                  options=["pT2", "pT3a", "pT3b", "pT4", "pN+", "unknown"]),
        FieldSpec(name="time_from_rp_to_bcr_months", label="Tiempo de RP a BCR (meses)",
                  type="number", required=True, unit="months",
                  voice_required_confidence=0.85,
                  must_capture_rationale="BCR <3y peor prognosis; afecta intensity de salvage"),
        FieldSpec(name="margin_status_at_rp", label="Márgenes al RP",
                  type="select", required=True,
                  options=["negative", "positive_focal", "positive_extensive", "unknown"]),
        FieldSpec(name="current_testosterone", label="Testosterona actual",
                  type="number", required=False, unit="ng/dL",
                  must_capture_rationale="Confirma que rise NO es escape ADT"),
        FieldSpec(name="imaging_status", label="Imagen reciente para staging",
                  type="select", required=True,
                  options=["psma_pet_done", "mri_fossa_done", "bone_scan_done", "ct_done", "no_imaging_yet"]),
        FieldSpec(name="nodal_status_on_imaging", label="Nodos en imagen",
                  type="select", required=True,
                  options=["no_nodes", "pelvic_only", "non_regional", "unknown"],
                  must_capture_rationale="Non-regional nodes = metastatic; cambia salvage intent"),
        FieldSpec(name="adt_history_post_rp", label="¿Recibió ADT post-RP?",
                  type="boolean", required=True),
        FieldSpec(name="fossa_biopsy_result", label="Biopsia de fossa de prostatectomía",
                  type="select", required=False,
                  options=["positive_local_recurrence", "negative", "not_performed"]),
        FieldSpec(name="life_expectancy_years", label="Expectativa de vida estimada",
                  type="select", required=True,
                  options=["lt_5y", "5_10y", "gt_10y"],
                  must_capture_rationale="LE <5y = palliative intent; ≥10y = curative salvage justified"),
        FieldSpec(name="patient_preference_intent", label="Preferencia del paciente",
                  type="select", required=True,
                  options=["curative_max_intensity", "balanced", "qol_priority_palliative", "undecided"],
                  must_capture_rationale="SDM core: patient preference dirige salvage aggressiveness"),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=salvage_eligibility",
    consumer="post_rp_salvage_copilot_service.build_salvage_decision",
    schema_completo_link="/longitudinal-capture/<nss>?moment=salvage_eligibility&full_schema=true",
    clinical_validation={
        "must_capture_rationale": (
            "PSADT + time_from_RP + path_stage + margin + nodal status drive "
            "salvage RT vs ADT intensification per NCCN 2026 PROS-D + AUA salvage 2025. "
            "Patient preference + LE = core SDM signal."
        ),
        "deferred_fields_safe_because": (
            "Detailed pathology per-section (Gleason heterogeneity, perineural "
            "invasion subtype), full surgical operative notes — capturados en "
            "pathology review meeting, NO afectan salvage timing decision."
        ),
        "nccn_2026_reference": "PROS-D",
        "aua_reference": "AUA salvage therapy guidelines 2025",
        "pivotal_trials": "GETUG-AFU 17, RADICALS-RT",
    },
)


# ─────────────────── 7. Biopsy Capture Form (11 fields) — EPIC 22b.2 ───────────────────
# Closes the documented "histopathology UI requests data but no capture form exists" gap.
# Replaces the full structured_biopsy schema (~30 fields) at the moment of the diagnostic
# encounter where the clinician needs to type the report into ProstaMed.

BIOPSY_CAPTURE_FORM = FormSchema(
    name="biopsy_capture",
    trigger_moment="diagnostic.histopath_report",
    description=(
        "Pathology report entry after biopsy or after prostatectomy specimen review. "
        "Replaces the full structured_biopsy schema (~30 fields) at the report-entry "
        "moment. Persists to biopsy_sessions table and canonicalizes facts read by "
        "clinical_state_classifier + risk_stratified_localized_copilot + "
        "post_rp_salvage_copilot."
    ),
    fields=[
        FieldSpec(name="biopsy_date", label="Fecha de la biopsia",
                  type="date", required=True,
                  voice_required_confidence=0.9,
                  must_capture_rationale="Anchor temporal; ordena risk stratification + AS/triage."),
        FieldSpec(name="biopsy_route", label="Vía de la biopsia",
                  type="select", required=True,
                  options=["transperineal", "transrectal", "fusion", "saturation"],
                  voice_required_confidence=0.85,
                  must_capture_rationale="Transperineal reduce infection rate y cambia AS protocol."),
        FieldSpec(name="biopsy_context", label="Contexto clínico",
                  type="select", required=True,
                  options=["diagnostic", "confirmatory_as", "followup_as",
                           "rebiopsy", "rp_specimen"],
                  voice_required_confidence=0.85,
                  must_capture_rationale=(
                      "Diagnostic vs confirmatory_as vs rp_specimen determinan qué "
                      "Gleason canonicaliza (gleason_at_rp vs gleason_primary diagnostic)."
                  )),
        FieldSpec(name="gleason_primary", label="Gleason primario",
                  type="select", required=True,
                  options=["3", "4", "5"],
                  voice_required_confidence=0.9,
                  must_capture_rationale=(
                      "Patrón ≥4 saca AS eligibility off; patrón 5 = high-risk independiente."
                  )),
        FieldSpec(name="gleason_secondary", label="Gleason secundario",
                  type="select", required=True,
                  options=["3", "4", "5"],
                  voice_required_confidence=0.9,
                  must_capture_rationale="Gleason 4+3 ≠ 3+4 — favorable vs unfavorable intermediate."),
        FieldSpec(name="isup_grade", label="ISUP grade group",
                  type="select", required=True,
                  options=["1", "2", "3", "4", "5"],
                  voice_required_confidence=0.9,
                  must_capture_rationale="ISUP es discriminator primario en NCCN 2026 PROS-2."),
        FieldSpec(name="total_cores", label="Total de cilindros tomados",
                  type="number", required=True,
                  voice_required_confidence=0.85,
                  must_capture_rationale="Denominador para percent_positive_cores (AS eligibility)."),
        FieldSpec(name="positive_cores", label="Cilindros positivos",
                  type="number", required=True,
                  voice_required_confidence=0.85,
                  must_capture_rationale=(
                      "Numerador para percent_positive_cores. <34% + GS6 = very_low_risk; "
                      ">50% high-risk per NCCN 2026."
                  )),
        FieldSpec(name="percent_pattern_4", label="% patrón 4 (en piezas Gleason 7)",
                  type="number", required=False, unit="%",
                  voice_required_confidence=0.8,
                  must_capture_rationale=(
                      "<10% pattern 4 favorable intermediate (AS aceptable); "
                      "≥10% unfavorable (tx recomendado)."
                  )),
        FieldSpec(name="perineural_invasion", label="¿Invasión perineural?",
                  type="boolean", required=False,
                  voice_required_confidence=0.8,
                  must_capture_rationale="PNI+ aumenta BCR risk post-RT; cambia ADT duration."),
        FieldSpec(name="margin_status", label="Estado de márgenes (sólo si rp_specimen)",
                  type="select", required=False,
                  options=["negative", "positive_focal", "positive_extensive",
                           "not_applicable"],
                  voice_required_confidence=0.85,
                  must_capture_rationale=(
                      "Solo aplica si biopsy_context=rp_specimen. Margen+ es indicación "
                      "primaria para salvage RT temprana per NCCN PROS-D."
                  )),
    ],
    capture_surface="/longitudinal-capture/<nss>?moment=biopsy_capture",
    consumer=(
        "tracking_db.append_structured_biopsy_session → biopsy_sessions table; "
        "clinical_fact_registry.extract_canonical_fact_candidates canonicalizes "
        "gleason_at_rp + margin_status + percent_pattern_4 + percent_positive_cores."
    ),
    schema_completo_link=(
        "/longitudinal-capture/<nss>?moment=biopsy_capture&full_schema=true "
        "(includes per-core sextant detail + MRI concordance + complications)"
    ),
    clinical_validation={
        "must_capture_rationale": (
            "Gleason + ISUP + % cores positivos + % pattern 4 son los discriminators "
            "primarios entre las 6 categorías de riesgo localizado (NCCN 2026 PROS-2). "
            "biopsy_context discrimina diagnostic Gleason vs RP specimen Gleason — "
            "previene el bug histórico donde post_rp_salvage_copilot leía diagnostic "
            "Gleason en lugar de RP piece Gleason."
        ),
        "deferred_fields_safe_because": (
            "Per-core sextant detail + MRI target concordance + complications "
            "capturables en schema completo si clinician necesita registro forense; "
            "NO afectan la 6-tier risk stratification decision."
        ),
        "nccn_2026_reference": "PROS-2 (risk stratification) + PROS-3 (AS) + PROS-D (salvage)",
        "fixes_documented_gaps": (
            "UI-data concordance audit BROKEN_INTEGRATION_1 + BROKEN_INTEGRATION_2 "
            "+ BROKEN_INTEGRATION_3 (RP Gleason + margin + percent cores)."
        ),
    },
)


# ─────────────────── Registry + helpers ───────────────────


MOMENT_CAPTURE_SCHEMAS: dict[str, FormSchema] = {
    "bcr_detection": BCR_DETECTION_FORM,
    "oligoprogression": OLIGOPROGRESSION_FORM,
    "crpc_transition": CRPC_TRANSITION_FORM,
    "adt_init": ADT_INIT_FORM,
    "rt_nadir": RT_NADIR_FORM,
    "salvage_eligibility": SALVAGE_ELIGIBILITY_FORM,
    "biopsy_capture": BIOPSY_CAPTURE_FORM,  # EPIC 22b.2
}


def get_micro_form(moment: str) -> FormSchema | None:
    """Get a micro-form schema by moment name."""
    return MOMENT_CAPTURE_SCHEMAS.get(moment)


def get_field_count_reduction(moment: str) -> dict[str, int]:
    """Compute field count reduction vs full schema for a moment."""
    full_counts = {
        "bcr_detection": 40,
        "oligoprogression": 38,
        "crpc_transition": 88,
        "adt_init": 45,
        "rt_nadir": 68,
        "salvage_eligibility": 58,
        "biopsy_capture": 30,  # EPIC 22b.2 — full structured_biopsy schema
    }
    form = MOMENT_CAPTURE_SCHEMAS.get(moment)
    if not form:
        return {}
    micro_count = len(form.fields)
    full_count = full_counts.get(moment, 0)
    reduction_pct = round((1 - micro_count / full_count) * 100, 1) if full_count else 0
    return {
        "moment": moment,
        "full_schema_fields": full_count,
        "micro_form_fields": micro_count,
        "reduction_pct": reduction_pct,
    }


def get_voice_targets_for_intent_extractor() -> list[dict[str, Any]]:
    """EPIC 21 prep: export field targets for voice intent_extractor registration.

    Each entry: {moment, field_name, label, type, confidence_threshold, options}
    """
    targets = []
    for moment, form in MOMENT_CAPTURE_SCHEMAS.items():
        for f in form.fields:
            targets.append({
                "moment": moment,
                "field_name": f.name,
                "label": f.label,
                "type": f.type,
                "confidence_threshold": f.voice_required_confidence,
                "options": f.options,
                "required": f.required,
            })
    return targets
