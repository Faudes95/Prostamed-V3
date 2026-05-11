from __future__ import annotations

from prostanet.domains.evidence_registry.models import GuidelineMetadata, ModuleEvidence
from prostanet.shared.contracts import EvidenceCitation


def citation(
    citation_id: str,
    title: str,
    guideline_or_trial: str,
    source_tier: str,
    *,
    effective_date: str = "",
    review_due_date: str = "",
    document_id: str = "",
    evidence_role: str = "",
    license_class: str = "",
    doi_or_url: str = "",
    local_pdf_path: str = "",
    disease_state: str = "",
    line_of_therapy: str = "",
    biomarker_scope: str = "",
    symptom_scope: str = "",
    toxicity_scope: str = "",
    followup_implications: str = "",
    supports_rule_ids: list[str] | None = None,
    applies_to_modules: list[str] | None = None,
    derived_rule_ids: list[str] | None = None,
    field_implications: list[str] | None = None,
    eligibility_implications: list[str] | None = None,
    required_traceable_fields: list[str] | None = None,
    applies_to_surfaces: list[str] | None = None,
    ui_surfaces: list[str] | None = None,
) -> dict:
    resolved_rule_ids = derived_rule_ids or supports_rule_ids or []
    resolved_surfaces = applies_to_surfaces or ui_surfaces or []
    return EvidenceCitation(
        citation_id=citation_id,
        title=title,
        guideline_or_trial=guideline_or_trial,
        source_tier=source_tier,
        effective_date=effective_date,
        review_due_date=review_due_date,
        document_id=document_id,
        evidence_role=evidence_role,
        license_class=license_class,
        doi_or_url=doi_or_url,
        local_pdf_path=local_pdf_path,
        disease_state=disease_state,
        line_of_therapy=line_of_therapy,
        biomarker_scope=biomarker_scope,
        symptom_scope=symptom_scope,
        toxicity_scope=toxicity_scope,
        followup_implications=followup_implications,
        supports_rule_ids=supports_rule_ids or resolved_rule_ids,
        applies_to_modules=applies_to_modules or [],
        derived_rule_ids=resolved_rule_ids,
        field_implications=field_implications or [],
        eligibility_implications=eligibility_implications or [],
        required_traceable_fields=required_traceable_fields or [],
        applies_to_surfaces=resolved_surfaces,
        ui_surfaces=ui_surfaces or [],
    ).to_dict()


def _document_registry(*documents: dict) -> dict[str, dict]:
    return {document["document_id"]: document for document in documents if document.get("document_id")}


GUIDELINES = {
    "nccn_2026": GuidelineMetadata(
        guideline="NCCN",
        version="5.2026",
        effective_date="2026-01-23",
        source_type="pdf",
        source_ref="/Users/oscaralvarado/Desktop/NCCN 2026.pdf",
        summary="Fuente normativa primaria para la estructura de los asistentes clínicos, la estadificación, la recurrencia, la segunda recurrencia bioquímica y la enfermedad avanzada.",
    ),
    "eau_2026": GuidelineMetadata(
        guideline="EAU",
        version="2026",
        effective_date="2026-03-01",
        source_type="pdf",
        source_ref="/Users/oscaralvarado/Desktop/EAU-EANM-ESTRO-ESUR-ISUP-SIOG-Guidelines-on-Prostate-Cancer-2026.pdf",
        summary="Capa comparativa paralela para clasificación, seguimiento, calidad de vida, enfermedad avanzada y cuidados paliativos frente a la Red Nacional Integral del Cáncer (NCCN) 2026.",
    ),
}

NCCN_PRIMARY = citation(
    "nccn_prostate_5_2026",
    "NCCN Clinical Practice Guidelines in Oncology: Prostate Cancer. Version 5.2026.",
    "NCCN 5.2026",
    "guideline_primary",
    effective_date="2026-01-23",
    review_due_date="2027-01-23",
    document_id="nccn_2026",
    evidence_role="primary_guideline",
    license_class="licensed_guideline_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/NCCN 2026.pdf",
    disease_state="Transversal",
    followup_implications="Define la recomendación principal, la jerarquía terapéutica y la estructura de monitoreo por estado clínico.",
    supports_rule_ids=["all.nccn_primary"],
    eligibility_implications=["primary_source_of_truth", "treatment_release_gate", "followup_requirements"],
    required_traceable_fields=["effective_state", "therapeutic_readiness_bundle", "decision_input_requirements"],
    applies_to_modules=[
        "diagnostic_workup",
        "post_negative_biopsy_followup",
        "localized_initial",
        "post_prostatectomy",
        "post_radiotherapy_followup",
        "recurrence_bcr",
        "post_radiotherapy_or_local_salvage",
        "adt_progression_verification",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
        "survivorship_and_toxicity_followup",
    ],
    field_implications=["guideline_versions", "primary_recommendation"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "dashboard", "schedule", "response_visualization"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "dashboard"],
)

EAU_PRIMARY = citation(
    "eau_prostate_2026",
    "EAU-EANM-ESTRO-ESUR-ISUP-SIOG Guidelines on Prostate Cancer 2026.",
    "EAU 2026",
    "guideline_comparator",
    effective_date="2026-03-01",
    review_due_date="2027-03-01",
    document_id="eau_2026",
    evidence_role="primary_guideline",
    license_class="licensed_guideline_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/EAU-EANM-ESTRO-ESUR-ISUP-SIOG-Guidelines-on-Prostate-Cancer-2026.pdf",
    disease_state="Transversal",
    followup_implications="Aporta comparación estructurada en diagnóstico, seguimiento, calidad de vida, transición entre estados y cuidados paliativos.",
    supports_rule_ids=["all.eau_comparison"],
    eligibility_implications=["comparator_followup_guardrail", "frailty_and_survivorship_overlay"],
    required_traceable_fields=["testosterone_history", "restaging_status", "survivorship_monitoring"],
    applies_to_modules=[
        "diagnostic_workup",
        "post_negative_biopsy_followup",
        "localized_initial",
        "post_prostatectomy",
        "post_radiotherapy_followup",
        "recurrence_bcr",
        "post_radiotherapy_or_local_salvage",
        "adt_progression_verification",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
        "survivorship_and_toxicity_followup",
    ],
    field_implications=["guideline_versions", "comparison_layer"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "schedule", "response_visualization"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

ACTIVE_SURVEILLANCE_REAL_WORLD = citation(
    "olsson_active_surveillance_2020",
    "Intensity of Active Surveillance and Transition to Treatment in Men with Low-risk Prostate Cancer.",
    "Olsson 2020",
    "supporting_study",
    document_id="olsson_2020_active_surveillance",
    evidence_role="real_world",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/j.euo.2019.05.005",
    local_pdf_path="/Users/oscaralvarado/Desktop/4.pdf",
    disease_state="Localized low-risk",
    followup_implications="Apoya la intensidad de vigilancia activa y la interpretación de la transición desde vigilancia activa hacia tratamiento curativo.",
    supports_rule_ids=["localized_initial.active_surveillance_followup"],
    applies_to_modules=["localized_initial"],
    field_implications=["confirmatory_biopsy_planned", "baseline_qol", "genomic_classifier"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

BENIGN_BIOPSY_LONG_TERM = citation(
    "palmstedt_benign_biopsy_2019",
    "Long-term Outcomes for Men in a Prostate Screening Trial with an Initial Benign Prostate Biopsy: A Population-based Cohort.",
    "Palmstedt 2019",
    "supporting_study",
    document_id="palmstedt_2019_negative_biopsy",
    evidence_role="real_world",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/j.euo.2019.01.016",
    local_pdf_path="/Users/oscaralvarado/Desktop/5.pdf",
    disease_state="Post-negative biopsy follow-up",
    followup_implications="Sustenta un seguimiento de baja intensidad tras biopsia benigna cuando la densidad del antígeno prostático específico y la sospecha clínica permanecen bajas.",
    supports_rule_ids=["post_negative_biopsy_followup.low_intensity_followup"],
    applies_to_modules=["post_negative_biopsy_followup"],
    field_implications=["repeat_biopsy_trigger", "prior_biopsy_count", "psa_kinetics"],
    ui_surfaces=["wizard.sidebar", "wizard.results"],
)

LATE_RT_TOXICITY = citation(
    "irradiate_reply_2026",
    "Re: Real-World Burden and Management of Late Genitourinary Toxicity After Prostate RT: Insights from IRRADIaTE.",
    "IRRADIaTE 2026",
    "supporting_study",
    document_id="irradiate_2026_late_rt_toxicity",
    evidence_role="safety_signal",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/j.euo.2026.02.022",
    local_pdf_path="/Users/oscaralvarado/Desktop/1.pdf",
    disease_state="Post-radiotherapy survivorship",
    toxicity_scope="Toxicidad genitourinaria tardía tras radioterapia",
    followup_implications="Refuerza la necesidad de seguimiento prolongado de toxicidad urinaria tardía tras radioterapia definitiva o de rescate.",
    supports_rule_ids=["localized_initial.radiotherapy_survivorship", "recurrence_bcr.salvage_radiotherapy_toxicity"],
    applies_to_modules=[
        "localized_initial",
        "recurrence_bcr",
        "post_radiotherapy_or_local_salvage",
        "post_radiotherapy_followup",
        "survivorship_and_toxicity_followup",
    ],
    field_implications=["baseline_bowel_qol", "baseline_urinary_qol"],
    ui_surfaces=["wizard.results", "patient_profile"],
)

PROPEL_SYMPTOMATIC = citation(
    "propel_symptomatic_subgroups_2025",
    "Efficacy and Safety of Olaparib Plus Abiraterone Versus Placebo Plus Abiraterone in the First-line Treatment of Patients with Asymptomatic/Mildly Symptomatic and Symptomatic Metastatic Castration-resistant Prostate Cancer: Analyses from the Phase 3 PROpel Trial.",
    "PROpel symptomatic subgroup analysis",
    "supporting_study",
    document_id="propel_symptomatic_2025",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/j.euo.2024.09.013",
    local_pdf_path="/Users/oscaralvarado/Desktop/2.pdf",
    disease_state="Metastatic castration-resistant disease",
    line_of_therapy="First line",
    biomarker_scope="Combinación de olaparib con abiraterona",
    symptom_scope="Pacientes asintomáticos, levemente sintomáticos y sintomáticos",
    followup_implications="Aporta contexto de subgrupos sintomáticos y tolerabilidad para la combinación olaparib más abiraterona, sin reemplazar la jerarquía primaria de las guías.",
    supports_rule_ids=["m1_crpc.propel_context"],
    applies_to_modules=["m1_crpc"],
    field_implications=["pain_symptoms", "baseline_qol"],
    ui_surfaces=["wizard.sidebar", "wizard.results"],
)

CARD_TRIAL = citation(
    "card_2019_cabazitaxel",
    "Cabazitaxel versus Abiraterone or Enzalutamide in Metastatic Prostate Cancer.",
    "CARD",
    "supporting_study",
    document_id="doc_33_card",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1056/NEJMoa1911206",
    local_pdf_path="/Users/oscaralvarado/Desktop/33.pdf",
    disease_state="M1 CRPC",
    line_of_therapy="Post-docetaxel and prior ARPI",
    followup_implications="Prioriza cabazitaxel frente a una nueva secuencia ARPI-ARPI cuando ya hubo docetaxel y progresión temprana en ARPI.",
    supports_rule_ids=["m1_crpc.card_cabazitaxel_preference"],
    applies_to_modules=["m1_crpc"],
    field_implications=["prior_therapy", "prior_docetaxel_cycles", "current_sequence_goal"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

VISION_TRIAL = citation(
    "vision_2021_lu177_psma",
    "Lutetium-177-PSMA-617 for Metastatic Castration-Resistant Prostate Cancer.",
    "VISION",
    "supporting_study",
    document_id="doc_34_vision",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1056/NEJMoa2107322",
    local_pdf_path="/Users/oscaralvarado/Desktop/34.pdf",
    disease_state="M1 CRPC",
    line_of_therapy="Post-ARPI with taxane exposure",
    biomarker_scope="PSMA-positive disease with imaging selection",
    followup_implications="Estructura elegibilidad para lutecio-177 PSMA-617 y exige positividad PSMA sin lesiones dominantes PSMA-negativas clínicamente relevantes.",
    supports_rule_ids=["m1_crpc.vision_psma_eligibility"],
    applies_to_modules=["m1_crpc"],
    field_implications=["psma_positive", "psma_negative_dominant_lesions", "biomarker_source"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

# Brecha M-staging gate + RP-cT4 — 2026-04-22 (§F.10): citaciones que respaldan
# el módulo `staging_requirements_engine.py` y los Gate A/B emitidos en
# localized_initial / diagnostic_workup / m0_crpc / recurrence_bcr.
PROPSMA_TRIAL = citation(
    "propsma_2020_hofman_lancet",
    "Prostate-specific membrane antigen PET-CT in patients with high-risk prostate cancer "
    "before curative-intent surgery or radiotherapy (proPSMA): a prospective, randomised, "
    "multicentre study.",
    "ProPSMA",
    "supporting_study",
    document_id="doc_propsma_2020",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/S0140-6736(20)30314-7",
    disease_state="High-risk localized / regional prostate cancer pre-curative",
    line_of_therapy="Pre-treatment staging",
    biomarker_scope="PSMA imaging vs conventional imaging (CT + bone scan)",
    followup_implications=(
        "Sustenta PSMA PET/CT como modalidad preferente para estadificación M en riesgo "
        "alto/muy alto antes de cirugía o radioterapia curativa. Sensibilidad 85% vs 38% "
        "para imagen convencional. Detecta M1 oculto en 30% de candidatos a tratamiento radical."
    ),
    supports_rule_ids=[
        "shared.staging_requirements_engine.staging_modality_recommended",
        "localized_initial.staging_gate_a",
        "diagnostic_workup.staging_imaging_recommendation",
        "m0_crpc.restaging_gate",
        "recurrence_bcr.restaging_gate",
    ],
    applies_to_modules=["localized_initial", "diagnostic_workup", "m0_crpc", "recurrence_bcr", "m1_crpc"],
    field_implications=[
        "psma_pet_done", "psma_pet_result", "psma_rads_score_staging",
        "imaging_negative_metastases", "staging_imaging_date",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

NCCN_PROS2_GUIDELINE = citation(
    "nccn_pros2_v5_2026_staging",
    "NCCN Clinical Practice Guidelines in Oncology — Prostate Cancer (PROS-2): Staging and "
    "Initial Risk Stratification (PSA, DRE, biopsy, imaging recommendations).",
    "NCCN PROS-2 v5.2026",
    "primary_guideline",
    document_id="doc_nccn_pros2_v5_2026",
    evidence_role="primary_guideline",
    license_class="publisher_pdf",
    disease_state="Newly diagnosed / restaging across all states",
    line_of_therapy="Pre-treatment staging across all risk strata",
    followup_implications=(
        "Define umbrales obligatorios de imagenología M: PSA>20 ng/mL, cT2b-T4, ISUP≥4 "
        "(Gleason 8-10) o sintomatología ósea/adenopatías → estadificación M obligatoria "
        "(PSMA PET/CT cat 1 o GGO+TAC abdomino-pélvico cat 1). Aplica también a restaging "
        "en BCR con PSA muy alto y a m0CRPC antes de iniciar ARPI (SPARTAN/PROSPER/ARAMIS)."
    ),
    supports_rule_ids=[
        "shared.staging_requirements_engine.staging_required",
        "shared.staging_requirements_engine.staging_complete",
        "localized_initial.staging_gate_a",
        "diagnostic_workup.staging_imaging_recommendation",
        "m0_crpc.restaging_gate",
        "recurrence_bcr.restaging_gate",
    ],
    applies_to_modules=["localized_initial", "diagnostic_workup", "m0_crpc", "recurrence_bcr"],
    field_implications=[
        "psa", "clinical_tstage", "isup_grade", "gleason_total",
        "psma_pet_done", "bone_scan_done", "ct_abdomen_pelvis_done",
        "mri_abdomen_pelvis_done", "imaging_negative_metastases",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

NCCN_PROS3_GUIDELINE = citation(
    "nccn_pros3_v5_2026_local_treatment",
    "NCCN Clinical Practice Guidelines in Oncology — Prostate Cancer (PROS-3): Initial "
    "Treatment by Risk Stratification (RP+PLND, EBRT+ADT, brachytherapy, contraindications).",
    "NCCN PROS-3 v5.2026",
    "primary_guideline",
    document_id="doc_nccn_pros3_v5_2026",
    evidence_role="primary_guideline",
    license_class="publisher_pdf",
    disease_state="Localized / regional prostate cancer initial treatment",
    line_of_therapy="Initial curative treatment selection",
    followup_implications=(
        "Define candidabilidad de prostatectomía radical (RP+PLND): cT2-T3a seleccionado en "
        "manejo multimodal en centros expertos. cT4 (invasión a recto, vejiga, elevadores o "
        "pared pélvica) constituye CONTRAINDICACIÓN ABSOLUTA de RP — el tratamiento radical "
        "local estándar es EBRT 78-80 Gy + ADT 1.5-3 años ± braquiterapia boost ± "
        "intensificación sistémica con abiraterona (STAMPEDE arm G/H si M0)."
    ),
    supports_rule_ids=[
        "shared.staging_requirements_engine.radical_prostatectomy_contraindicated",
        "localized_initial.staging_gate_b_rp_ct4",
    ],
    applies_to_modules=["localized_initial", "diagnostic_workup"],
    field_implications=[
        "clinical_tstage", "rectal_invasion", "bladder_invasion",
        "pelvic_fixation", "extensive_seminal_vesicle_invasion",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

# ── Triaje pre-biopsia + emergencias oncológicas + ADT empírico ──────
# Brecha clínica reportada (2026-04-23): paciente APE 5000 + cT4 fijo+pétreo
# sin BTR. Citaciones que sustentan la respuesta clínica.

NCCN_PROS_G_GUIDELINE = citation(
    "nccn_pros_g_v5_2026_empiric_adt",
    "NCCN Clinical Practice Guidelines in Oncology — Prostate Cancer (PROS-G): "
    "Empiric androgen deprivation therapy in symptomatic locally advanced or "
    "metastatic prostate cancer with biopsy contraindicated or delayed.",
    "NCCN PROS-G v5.2026",
    "primary_guideline",
    document_id="doc_nccn_pros_g_v5_2026",
    evidence_role="primary_guideline",
    license_class="publisher_pdf",
    disease_state="Pre-histology suspected advanced prostate cancer",
    line_of_therapy="Empiric ADT pre-biopsy",
    followup_implications=(
        "Justifica iniciar ADT empírico (agonista LHRH + bicalutamida 14 d "
        "flare protection o antagonista LHRH degarelix/relugolix) cuando la "
        "probabilidad clínica de adenocarcinoma de próstata avanzado es alta "
        "(APE>100 + cT3b-T4 + síntomas) y la histología se demora ≥7 días o "
        "está contraindicada. En compresión medular o uropatía obstructiva "
        "severa se prefiere antagonista LHRH por descenso rápido sin flare."
    ),
    supports_rule_ids=[
        "shared.clinical_provisional_diagnosis_engine.assess_provisional_diagnosis",
        "shared.clinical_provisional_diagnosis_engine.empiric_adt_protocol",
        "diagnostic_workup.empiric_adt_branch",
    ],
    applies_to_modules=["diagnostic_workup", "localized_initial", "mcspc_high_volume"],
    field_implications=[
        "empiric_adt_initiated", "empiric_adt_start_date",
        "provisional_diagnosis_assumed", "provisional_diagnosis_basis",
        "biopsy_status", "biopsy_contraindicated_reason",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

EAU_2026_LOCALLY_ADVANCED_NEOADJ = citation(
    "eau_2026_6_5_4_neoadjuvant_adt",
    "EAU-EANM-ESTRO-ESUR-ISUP-SIOG Guidelines on Prostate Cancer 2026 — "
    "§6.5.4 Neoadjuvant ADT in locally advanced disease.",
    "EAU 2026 §6.5.4",
    "primary_guideline",
    document_id="doc_eau_2026_6_5_4",
    evidence_role="primary_guideline",
    license_class="publisher_pdf",
    doi_or_url="https://uroweb.org/guidelines/prostate-cancer",
    disease_state="Locally advanced (cT3-T4) with symptoms or pre-RT",
    line_of_therapy="Neoadjuvant / pre-RT ADT",
    followup_implications=(
        "Sustenta uso de ADT neoadyuvante en enfermedad localmente avanzada "
        "sintomática y pre-radioterapia. En cT4 con próstata fija+pétrea, ADT "
        "puede preceder a la confirmación histológica si la probabilidad "
        "clínica es muy alta y existen síntomas o emergencia oncológica."
    ),
    supports_rule_ids=[
        "shared.clinical_provisional_diagnosis_engine.assess_provisional_diagnosis",
        "diagnostic_workup.empiric_adt_branch",
    ],
    applies_to_modules=["diagnostic_workup", "localized_initial"],
    field_implications=[
        "clinical_tstage_dre_estimate", "dre_fixation",
        "dre_prostate_consistency", "empiric_adt_initiated",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

LOBLAW_CORD_COMPRESSION = citation(
    "loblaw_2012_cord_compression",
    "Loblaw DA et al. — A 2011 updated guideline on initial management of "
    "metastatic spinal cord compression.",
    "Loblaw / ASCO 2012",
    "supporting_study",
    document_id="doc_loblaw_2012",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1200/JCO.2011.40.0234",
    disease_state="Metastatic prostate cancer with neurological compromise",
    line_of_therapy="Oncologic emergency management",
    symptom_scope="Spinal cord compression, neurologic deficits",
    followup_implications=(
        "Sustenta protocolo de manejo de compresión medular metastásica: RM "
        "urgente <24 h, dexametasona 16 mg IV bolo + 4 mg c/6 h, RT 30 Gy/10 "
        "fx o cirugía descompresiva (criterios de Patchell), inicio simultáneo "
        "de ADT. Demora >24 h se asocia a paraplejia irreversible."
    ),
    supports_rule_ids=[
        "shared.oncologic_emergency_triage_engine._detect_cord_compression",
        "shared.oncologic_emergency_triage_engine.emergency_triage_descriptor",
    ],
    applies_to_modules=[
        "diagnostic_workup", "localized_initial", "mcspc_high_volume",
        "m1_crpc", "palliative_pathway",
    ],
    field_implications=[
        "spinal_cord_compression", "cord_compression_symptoms",
        "lower_limb_weakness", "bowel_dysfunction",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

NCCN_ONCOLOGIC_EMERGENCIES = citation(
    "nccn_oncologic_emergencies_v3_2026",
    "NCCN Clinical Practice Guidelines in Oncology — Oncologic Emergencies "
    "v3.2026: cord compression, hypercalcemia, urinary tract obstruction, "
    "severe hematuria, acute urinary retention, hyperviscosity.",
    "NCCN Oncologic Emergencies v3.2026",
    "primary_guideline",
    document_id="doc_nccn_oncologic_emergencies_v3_2026",
    evidence_role="primary_guideline",
    license_class="publisher_pdf",
    disease_state="All oncology states with acute complications",
    line_of_therapy="Oncologic emergency triage",
    symptom_scope="Cord compression, hypercalcemia, obstruction, bleeding",
    followup_implications=(
        "Define criterios de triaje, tiempos a acción y protocolos para "
        "emergencias oncológicas. Aplicable a pacientes pre-biopsia con "
        "síntomas que requieren intervención inmediata independiente del "
        "estado de confirmación histológica."
    ),
    supports_rule_ids=[
        "shared.oncologic_emergency_triage_engine.detect_oncologic_emergencies",
        "shared.oncologic_emergency_triage_engine.emergency_triage_descriptor",
    ],
    applies_to_modules=[
        "diagnostic_workup", "localized_initial", "mcspc_high_volume",
        "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous",
        "m1_crpc", "m0_crpc", "recurrence_bcr", "palliative_pathway",
    ],
    field_implications=[
        "spinal_cord_compression", "obstructive_uropathy_severity",
        "hypercalcemia_present", "gross_hematuria_severity",
        "acute_urinary_retention", "pathological_fracture_present",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

ASCO_AUA_BONE_HEALTH_2024 = citation(
    "asco_aua_bone_health_2024",
    "ASCO/AUA Bone Health Guidelines 2024 — bone-modifying agents and "
    "pathological fracture management in advanced prostate cancer.",
    "Saylor PJ et al. JCO 2024",
    "supporting_study",
    document_id="doc_asco_aua_bone_health_2024",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    disease_state="Advanced prostate cancer with bone metastases",
    line_of_therapy="Bone-modifying therapy",
    symptom_scope="Pathological fracture risk and management",
    followup_implications=(
        "Sustenta uso de denosumab 120 mg SC c/4 sem o zoledronato 4 mg IV "
        "c/4 sem en mCRPC con metástasis óseas, evaluación de Mirels score "
        "para fijación profiláctica, y RT post-fijación 8 Gy/1 fx o 30 Gy/10 fx."
    ),
    supports_rule_ids=[
        "shared.oncologic_emergency_triage_engine._detect_pathological_fracture",
    ],
    applies_to_modules=[
        "m1_crpc", "mcspc_high_volume", "palliative_pathway",
    ],
    field_implications=["pathological_fracture_present", "bone_pain_severity"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

BRIGANTI_NOMOGRAM_2012 = citation(
    "briganti_2012_eur_urol_nomogram",
    "Briganti A et al. — Updated nomogram predicting lymph node invasion in "
    "patients with prostate cancer undergoing extended pelvic lymph node "
    "dissection.",
    "Briganti 2012",
    "supporting_study",
    document_id="doc_briganti_2012",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1016/j.eururo.2011.10.044",
    disease_state="Localized / locally advanced prostate cancer pre-treatment",
    line_of_therapy="Pre-treatment risk assessment",
    biomarker_scope="Pre-test probability of LN invasion / occult M1",
    followup_implications=(
        "Sustenta los umbrales de probabilidad pre-test de M1 oculto codificados "
        "en el motor de diagnóstico provisional: APE>100 ng/mL ~60-75%, "
        "APE>500 ng/mL ~80-90%, APE>1000 ng/mL >93%, APE>5000 ng/mL >97%. "
        "Combinado con cT4 y GG≥4 incrementa la probabilidad."
    ),
    supports_rule_ids=[
        "shared.clinical_provisional_diagnosis_engine.assess_provisional_diagnosis",
    ],
    applies_to_modules=["diagnostic_workup", "localized_initial"],
    field_implications=[
        "psa", "clinical_tstage_dre_estimate", "isup_grade",
        "gleason_total", "provisional_diagnosis_assumed",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

PROFOUND_TRIAL = citation(
    "profound_2020_olaparib",
    "Survival with Olaparib in Metastatic Castration-Resistant Prostate Cancer.",
    "PROfound",
    "supporting_study",
    document_id="doc_35_profound",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1056/NEJMoa2022485",
    local_pdf_path="/Users/oscaralvarado/Desktop/35.pdf",
    disease_state="M1 CRPC",
    line_of_therapy="Post-next-generation hormonal agent",
    biomarker_scope="Alteraciones HRR trazables a nivel de gen",
    followup_implications="Refuerza que olaparib requiere biomarcador HRR trazable y documentado por gen, con fuente analítica identificable.",
    supports_rule_ids=["m1_crpc.profound_hrr_pathway"],
    applies_to_modules=["m1_crpc"],
    field_implications=["hrr_status", "hrr_gene", "biomarker_source"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

IMPACT_TRIAL = citation(
    "impact_2010_sipuleucel_t",
    "IMPACT: Sipuleucel-T Immunotherapy for Castration-Resistant Prostate Cancer (Kantoff 2010).",
    "IMPACT",
    "trial_pivotal",
    document_id="impact_2010_sipuleucel_t",
    evidence_role="pivotal_trial_class_1",
    license_class="public_web_reference",
    doi_or_url="https://doi.org/10.1056/NEJMoa1001294",
    disease_state="M1 CRPC",
    line_of_therapy="Pre-docetaxel asintomático o mínimamente sintomático",
    biomarker_scope="Inmunoterapia autóloga sin biomarcador molecular obligatorio",
    symptom_scope="Asintomático o mínimamente sintomático sin opioides crónicos",
    followup_implications="Reserva sipuleucel-T para mCRPC pre-quimio asintomático o mínimamente sintomático sin metástasis viscerales y sin inmunosupresión activa.",
    supports_rule_ids=["m1_crpc.impact_sipuleucel_t"],
    applies_to_modules=["m1_crpc"],
    field_implications=[
        "pain_status",
        "opioid_use_for_pain",
        "visceral_metastasis_present",
        "prior_docetaxel_cycles",
        "active_immunosuppression",
    ],
    eligibility_implications=[
        "requires_asymptomatic_or_minimally_symptomatic",
        "blocks_if_visceral_metastasis_present",
        "blocks_if_active_immunosuppression",
    ],
    required_traceable_fields=[
        "pain_status",
        "opioid_use_for_pain",
        "visceral_metastasis_present",
        "active_immunosuppression",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

CONTACT02_TRIAL = citation(
    "contact02_2024_cabozantinib_atezolizumab",
    "CONTACT-02: Cabozantinib Plus Atezolizumab versus Second Novel Hormonal Therapy in Metastatic Castration-Resistant Prostate Cancer Previously Treated with One Novel Hormonal Therapy (Agarwal Lancet Oncol 2024).",
    "CONTACT-02",
    "trial_pivotal",
    document_id="contact02_2024_cabozantinib_atezolizumab",
    evidence_role="pivotal_trial_class_1",
    license_class="public_web_reference",
    doi_or_url="https://doi.org/10.1016/S1470-2045(24)00403-1",
    disease_state="M1 CRPC",
    line_of_therapy="Post-ARPI con enfermedad visceral o adenopatías extra-pélvicas",
    biomarker_scope="Sin biomarcador molecular obligatorio; estratificación por sitio de enfermedad y exposición previa",
    followup_implications="Combina TKI VEGFR-MET con anti-PD-L1 cuando el paciente progresa tras ARPI, presenta enfermedad visceral o adenopatías extra-pélvicas y rehúsa o no es candidato a docetaxel; requiere descartar autoinmunidad activa antes de iniciar atezolizumab.",
    supports_rule_ids=["m1_crpc.contact02_cabo_atezo"],
    applies_to_modules=["m1_crpc"],
    field_implications=[
        "prior_arpi",
        "visceral_metastasis_present",
        "extra_pelvic_nodal_metastasis",
        "not_chemotherapy_candidate",
        "active_autoimmune_disease",
        "prior_docetaxel_cycles",
    ],
    eligibility_implications=[
        "requires_prior_arpi_exposure",
        "requires_visceral_or_extra_pelvic_disease",
        "blocks_if_active_autoimmune_disease",
    ],
    required_traceable_fields=[
        "prior_arpi",
        "visceral_metastasis_present",
        "extra_pelvic_nodal_metastasis",
        "active_autoimmune_disease",
    ],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

EMBARK_FDA = citation(
    "embark_fda_2023",
    "FDA approves enzalutamide for non-metastatic castration-sensitive prostate cancer with biochemical recurrence.",
    "FDA EMBARK approval",
    "regulatory_update",
    effective_date="2023-11-16",
    review_due_date="2027-11-16",
    document_id="fda_enza_bcr_2023",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-enzalutamide-non-metastatic-castration-sensitive-prostate-cancer-biochemical-recurrence",
    disease_state="Biochemical recurrence",
    line_of_therapy="High-risk BCR",
    followup_implications="Restringe la vía con enzalutamida a patrones high-risk BCR documentados y sin opción local curativa predominante.",
    supports_rule_ids=["recurrence_bcr.embark_gating"],
    eligibility_implications=["blocks_systemic_bcr_if_local_salvage_feasible", "requires_high_risk_bcr_characterization"],
    required_traceable_fields=["psadt_months", "salvage_local_feasible", "conventional_imaging_m0"],
    applies_to_modules=["recurrence_bcr"],
    field_implications=["conventional_imaging_m0", "salvage_local_feasible", "psadt_months"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "schedule", "therapeutic_readiness"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

AUA_ASTRO_SUO_SALVAGE = citation(
    "aua_astro_suo_salvage_2024",
    "Salvage Therapy for Prostate Cancer: AUA/ASTRO/SUO Guideline (2024).",
    "AUA/ASTRO/SUO salvage guideline",
    "guideline_comparator",
    effective_date="2024-02-01",
    review_due_date="2027-02-01",
    document_id="aua_astro_suo_salvage_2024",
    evidence_role="primary_guideline",
    license_class="public_web_reference",
    doi_or_url="https://www.astro.org/provider-resources/guidelines/clinical-practice-guidelines/salvage-therapy-guideline",
    disease_state="Biochemical recurrence and local salvage",
    line_of_therapy="Post-local therapy salvage decision-making",
    followup_implications="Centraliza el carril salvage tras recurrencia bioquímica y ayuda a decidir entre salvage local, intensificación sistémica y restadificación avanzada después de prostatectomía radical o radioterapia.",
    supports_rule_ids=["recurrence_bcr.salvage_guideline", "post_radiotherapy_or_local_salvage.salvage_guideline"],
    eligibility_implications=["requires_restaging_before_curative_salvage", "preserves_salvage_window"],
    required_traceable_fields=["psma_pet_done", "conventional_imaging_status", "salvage_local_feasible", "psadt_months"],
    applies_to_modules=["post_prostatectomy", "recurrence_bcr", "post_radiotherapy_followup", "post_radiotherapy_or_local_salvage"],
    field_implications=["salvage_local_feasible", "psadt_months", "conventional_imaging_status", "psma_pet_done"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "schedule", "therapeutic_readiness"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

PSMAFORE_REGULATORY = citation(
    "psmafore_regulatory_2025",
    "Pluvicto approved by FDA for expanded indication in earlier use for PSMA-positive metastatic castration-resistant prostate cancer.",
    "Pluvicto earlier-line FDA expansion",
    "regulatory_update",
    effective_date="2025-03-28",
    review_due_date="2027-03-28",
    document_id="fda_pluvicto_earlier_2025",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.novartis.com/us-en/news/media-releases/pluvicto-approved-fda-expanded-indication-earlier-use-psma-positive-metastatic-castration-resistant-prostate-cancer",
    disease_state="M1 CRPC",
    line_of_therapy="Pre-taxane PSMA-positive disease",
    biomarker_scope="PSMA-positive disease without dominant PSMA-negative lesions",
    followup_implications="Permite abrir una rama pre-taxano conservadora para lutecio-177 PSMA-617 cuando se documenta necesidad clínica de diferir o evitar docetaxel.",
    supports_rule_ids=["m1_crpc.psmafore_pre_taxane"],
    eligibility_implications=["requires_psma_positive_with_no_dominant_psma_negative_lesions", "requires_taxane_context_traceability"],
    required_traceable_fields=["psma_positive", "psma_negative_dominant_lesions", "docetaxel_verification_status", "mcrpc_line_context"],
    applies_to_modules=["m1_crpc"],
    field_implications=["psma_positive", "psma_negative_dominant_lesions", "docetaxel_base_eligibility", "docetaxel_verification_status", "chemotherapy_delay_candidate", "mcrpc_line_context"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "schedule", "therapeutic_readiness"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

TALAPRO2_REGULATORY = citation(
    "talapro2_regulatory_2025",
    "Pfizer provides update on U.S. regulatory review for TALZENNA in combination with XTANDI.",
    "Pfizer TALAPRO-2 regulatory update",
    "regulatory_update",
    effective_date="2025-01-15",
    review_due_date="2027-01-15",
    document_id="pfizer_talapro2_2025",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.pfizer.com/news/announcements/pfizer-provides-update-us-regulatory-review-talzenna-combination-xtandi-broader",
    disease_state="M1 CRPC",
    line_of_therapy="First line",
    biomarker_scope="HRR-mutated disease",
    followup_implications="Mantiene un uso conservador de talazoparib más enzalutamida restringido a mCRPC HRR-mutado.",
    supports_rule_ids=["m1_crpc.talapro2_first_line_hrr"],
    eligibility_implications=["requires_hrr_traceability_before_parp_release", "requires_first_line_mcrpc_context"],
    required_traceable_fields=["hrr_status", "hrr_gene", "molecular_report_date", "biomarker_source"],
    applies_to_modules=["m1_crpc"],
    field_implications=["hrr_status", "hrr_gene", "mcrpc_line_context", "molecular_report_date"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "schedule", "therapeutic_readiness"],
    ui_surfaces=["wizard.sidebar", "wizard.results"],
)

AKEEGA_MHSPC = citation(
    "akeega_brca2_mcspc_2025",
    "U.S. FDA approves AKEEGA as the first precision therapy for BRCA2-mutated metastatic castration-sensitive prostate cancer.",
    "J&J AKEEGA BRCA2 mCSPC",
    "regulatory_update",
    document_id="jnj_akeega_mcspc_2025",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.jnj.com/media-center/press-releases/u-s-fda-approves-akeega-as-the-first-precision-therapy-for-brca2-mutated-metastatic-castration-sensitive-prostate-cancer-with-54-reduction-in-disease-progression-vs-standard-of-care",
    disease_state="mHSPC",
    line_of_therapy="Frontline precision therapy",
    biomarker_scope="BRCA2-mutated disease",
    followup_implications="Activa una ruta de precisión en mHSPC solo cuando BRCA2, fuente y fecha del ensayo molecular son trazables.",
    supports_rule_ids=["mcspc.akeega_brca2_precision"],
    applies_to_modules=["mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"],
    field_implications=["brca2_status", "hrr_gene", "molecular_assay_source", "molecular_assay_date"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

# EPIC 9 Group C (GAP-5) — TALAPRO-3 (Agarwal ASCO GU 2025 LBA18) es el
# primer pivote positivo en mHSPC HRR-mutado que muestra beneficio de
# rPFS (HR≈0.67) añadiendo talazoparib a enzalutamida+ADT. Se registra
# como `pivotal_abstract` (evidencia provisional; approval regulatorio
# pendiente). El patrón clonado es `AKEEGA_MHSPC` (líneas 402-419) porque
# ambos son rutas de precisión mHSPC HRR-driven.
TALAPRO3_MHSPC_HRR = citation(
    "talapro3_hrr_mhspc_2025",
    "TALAPRO-3: Talazoparib plus enzalutamide significantly improves radiographic progression-free survival versus placebo plus enzalutamide in metastatic castration-sensitive prostate cancer with HRR gene alterations.",
    "TALAPRO-3",
    "pivotal_abstract",
    document_id="talapro3_asco_gu_2025_lba18",
    effective_date="2025-02-13",
    review_due_date="2026-06-30",
    evidence_role="pivotal_trial_abstract",
    license_class="public_web_reference",
    doi_or_url="https://meetings.asco.org/abstracts-presentations/243126",
    disease_state="mHSPC",
    line_of_therapy="Frontline precision therapy",
    biomarker_scope="HRR-mutated disease (BRCA1, BRCA2, ATM, PALB2, CDK12, CHEK2, FANCA, MLH1, MRE11A, NBN, RAD51B, RAD51C)",
    followup_implications="Activa la propuesta de talazoparib+enzalutamida+ADT en mHSPC únicamente cuando HRR (BRCA1/2/ATM/PALB2/otros HRR) y su fuente molecular son trazables; flag regulatory_pending=True hasta aprobación FDA/EMA.",
    supports_rule_ids=["mcspc.talapro3_hrr_precision"],
    applies_to_modules=["mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"],
    field_implications=["hrr_status", "hrr_gene", "molecular_assay_source", "molecular_assay_date"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

ARANOTE_DAROLUTAMIDE_FDA = citation(
    "darolutamide_aranote_fda_2025",
    "FDA approves darolutamide for metastatic castration-sensitive prostate cancer.",
    "FDA darolutamide ARANOTE approval",
    "regulatory_update",
    document_id="fda_darolutamide_aranote_2025",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-darolutamide-metastatic-castration-sensitive-prostate-cancer",
    disease_state="mHSPC",
    line_of_therapy="Frontline doublet intensification",
    biomarker_scope="Darolutamide plus ADT based on ARANOTE",
    followup_implications="Añade una ancla regulatoria explícita para darolutamide en mHSPC y documenta que la indicación FDA 2025 deriva del estudio pivotal ARANOTE.",
    supports_rule_ids=["mcspc.darolutamide_aranote_backbone"],
    applies_to_modules=["mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"],
    field_implications=["drug_interaction_reviewed", "cv_risk_documented", "line_of_therapy_context"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

REZVILUTAMIDE_CHART = citation(
    "rezvilutamide_chart_2024",
    "Addition of rezvilutamide to androgen-deprivation therapy in patients with high-volume metastatic hormone-sensitive prostate cancer (CHART).",
    "CHART",
    "supporting_study",
    document_id="chart_rezvilutamide_2024",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://pubmed.ncbi.nlm.nih.gov/39269783/",
    disease_state="mHSPC",
    line_of_therapy="Frontline doublet",
    followup_implications="Permite visibilizar rezvilutamida como opción hormonal soportada por EAU 2026 sin desplazar la jerarquía primaria de NCCN.",
    supports_rule_ids=["mcspc.rezvilutamide_option"],
    applies_to_modules=["mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"],
    field_implications=["comorbidity_seizure", "frailty_status", "metastasis_site"],
    ui_surfaces=["wizard.results", "patient_profile"],
)

APCCC_2024 = citation(
    "apccc_2024_advanced_pc",
    "Management of Patients with Advanced Prostate Cancer. Report from the 2024 Advanced Prostate Cancer Consensus Conference (APCCC).",
    "APCCC 2024",
    "consensus_support",
    document_id="doc_36_apccc",
    evidence_role="consensus",
    license_class="publisher_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/36.pdf",
    disease_state="Advanced disease",
    followup_implications="Añade una capa de consenso para zonas grises de secuenciación y selección, pero no reemplaza la recomendación primaria basada en guías.",
    supports_rule_ids=["advanced.supportive_consensus_overlay"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
    ],
    field_implications=["frailty_status", "cv_risk_documented", "drug_interaction_reviewed"],
    ui_surfaces=["wizard.results", "patient_profile"],
)

ARSI_CV_META = citation(
    "arsi_cv_meta_2024",
    "Cardiovascular Events and Androgen Receptor Signaling Inhibitors in Advanced Prostate Cancer: A Systematic Review and Meta-Analysis.",
    "ARSI CV meta-analysis",
    "safety_signal",
    effective_date="2024-06-01",
    review_due_date="2027-06-01",
    document_id="doc_37_arsi_cv_meta",
    evidence_role="safety_signal",
    license_class="publisher_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/37.pdf",
    disease_state="Advanced prostate cancer",
    toxicity_scope="Riesgo cardiovascular asociado a ARPI",
    followup_implications="Activa evaluación cardiovascular basal y seguimiento serial cuando se plantea intensificación con ARPI.",
    supports_rule_ids=["advanced.cardio_oncology_overlay"],
    eligibility_implications=["requires_cv_baseline_before_arpi_release", "requires_serial_monitoring_after_arpi_start"],
    required_traceable_fields=["cv_risk_documented", "current_medications", "drug_interaction_reviewed"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
    ],
    field_implications=["cv_risk_documented", "baseline_qol", "drug_interaction_reviewed"],
    applies_to_surfaces=["wizard.results", "patient_profile", "dashboard", "schedule", "advanced_followup"],
    ui_surfaces=["wizard.results", "patient_profile", "dashboard"],
)

FRAILTY_COMORBIDITY = citation(
    "frailty_comorbidity_2025",
    "Association between frailty and specific comorbidities on oncological outcomes in metastatic hormone-sensitive and castration resistant prostate cancer.",
    "Frailty and comorbidity outcomes",
    "supporting_study",
    document_id="doc_39_frailty",
    evidence_role="supportive_trial",
    license_class="publisher_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/39.pdf",
    disease_state="mHSPC and mCRPC",
    followup_implications="Refuerza la necesidad de documentar fragilidad y comorbilidades específicas antes de escalar intensidad terapéutica.",
    supports_rule_ids=["advanced.frailty_geriatric_overlay"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
    ],
    field_implications=["frailty_status", "baseline_qol", "ecog_score"],
    ui_surfaces=["wizard.results", "patient_profile", "dashboard"],
)

ARPI_DDI_REVIEW = citation(
    "arpi_ddi_2024",
    "Androgen receptor pathway inhibitors and drug-drug interactions in prostate cancer.",
    "ARPI DDI review",
    "supporting_study",
    document_id="doc_40_arpi_ddi",
    evidence_role="safety_signal",
    license_class="publisher_pdf",
    local_pdf_path="/Users/oscaralvarado/Desktop/40.pdf",
    disease_state="Advanced prostate cancer",
    toxicity_scope="Interacciones farmacológicas por CYP y polifarmacia",
    followup_implications="Añade revisión estructurada de interacciones farmacológicas antes de iniciar ARPI, especialmente con polifarmacia y fragilidad.",
    supports_rule_ids=["advanced.drug_interaction_review"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
    ],
    field_implications=["drug_interaction_reviewed", "current_medications", "cv_risk_documented"],
    ui_surfaces=["wizard.results", "patient_profile", "dashboard"],
)

EAU_ADT_FOLLOWUP = citation(
    "eau_followup_adt_2026",
    "EAU Guidelines on Prostate Cancer - Follow-up.",
    "EAU 2026 ADT follow-up",
    "guideline_comparator",
    effective_date="2026-03-01",
    review_due_date="2027-03-01",
    document_id="eau_followup_adt_2026",
    evidence_role="primary_guideline",
    license_class="public_web_reference",
    doi_or_url="https://uroweb.org/guidelines/prostate-cancer/chapter/followup",
    disease_state="ADT follow-up and survivorship",
    line_of_therapy="Hormonal treatment monitoring",
    toxicity_scope="Bone mineral density, metabolic syndrome, HbA1c and lipid surveillance during ADT",
    followup_implications="Centraliza el seguimiento oficial en ADT: bone mineral density con DEXA, protección ósea, testosterone monitoring, creatinine, alkaline phosphatase, metabolic syndrome, HbA1c y lipid profiles a intervalos regulares.",
    supports_rule_ids=["advanced.adt_followup_monitoring_bundle"],
    eligibility_implications=["requires_testosterone_and_restaging_for_advanced_followup_confidence", "requires_bone_and_metabolic_monitoring_for_longitudinal_release"],
    required_traceable_fields=["testosterone_history", "dxa_baseline_done", "bone_protection_started", "hba1c", "lipid_panel", "creatinine", "alp"],
    applies_to_modules=["adt_progression_verification", "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m0_crpc", "m1_crpc", "survivorship_and_toxicity_followup"],
    field_implications=["dxa_baseline_done", "bone_protection_started", "calcium_vitd_started", "testosterone", "hba1c", "lipid_panel", "creatinine", "alp"],
    applies_to_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "dashboard", "schedule", "advanced_followup"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile", "dashboard"],
)

ABIRATERONE_DILI = citation(
    "abiraterone_dili_2025",
    "Drug-Induced Liver Injury Caused by Abiraterone Acetate in Patients With Prostate Cancer.",
    "Abiraterone DILI",
    "safety_signal",
    document_id="doc_41_abiraterone_dili",
    evidence_role="safety_signal",
    license_class="open_access_pdf",
    doi_or_url="https://doi.org/10.7759/cureus.83494",
    local_pdf_path="/Users/oscaralvarado/Desktop/41.pdf",
    disease_state="mHSPC and mCRPC",
    toxicity_scope="Hepatotoxicidad por abiraterona",
    followup_implications="Dispara bundle de monitoreo hepático basal y en semanas 4 a 8 cuando se considera o usa abiraterona.",
    supports_rule_ids=["advanced.hepatic_monitoring_bundle"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "m1_crpc",
    ],
    field_implications=["child_pugh_score", "hepatic_risk_factors", "baseline_lft_documented"],
    ui_surfaces=["wizard.results", "patient_profile", "dashboard"],
)

MHSPC_REAL_WORLD = citation(
    "mhspc_real_world_2025",
    "Real-World Evidence of Combination Therapy Use in Metastatic Hormone-Sensitive Prostate Cancer in the United States From 2017 to 2023.",
    "Real-world mHSPC combinations",
    "benchmarking_study",
    document_id="doc_42_mhspc_real_world",
    evidence_role="real_world",
    license_class="publisher_pdf",
    doi_or_url="https://doi.org/10.1200/OP-24-00690",
    local_pdf_path="/Users/oscaralvarado/Desktop/42.pdf",
    disease_state="mHSPC",
    followup_implications="Se usa para benchmarking de adopción de dobletes y tripletes, no para desplazar la jerarquía terapéutica primaria.",
    supports_rule_ids=["mcspc.benchmark_adoption"],
    applies_to_modules=[
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
    ],
    field_implications=["combination_adherence", "baseline_qol", "biomarker_completion"],
    ui_surfaces=["wizard.results", "patient_profile", "dashboard"],
)

MSK_PREOP_NOMOGRAM = citation(
    "msk_preop_nomogram",
    "MSK pre-radical prostatectomy nomogram.",
    "MSK nomogram",
    "benchmark_reference",
    document_id="benchmark_msk_preop",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://www.mskcc.org/nomograms/prostate/pre_op",
    disease_state="Localized initial",
    followup_implications="Sirve como benchmark de producto para variables preoperatorias y refinamiento de riesgo, sin actuar como motor normativo.",
    supports_rule_ids=["localized_initial.product_benchmark"],
    applies_to_modules=["localized_initial"],
    field_implications=["clinical_tstage", "psa", "gleason_primary", "gleason_secondary"],
    ui_surfaces=["wizard.sidebar", "dashboard"],
)

CANARY_PASS = citation(
    "canary_pass",
    "Canary PASS active surveillance program.",
    "Canary PASS",
    "benchmark_reference",
    document_id="benchmark_canary_pass",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://canarypass.org/",
    disease_state="Active surveillance",
    followup_implications="Sirve como benchmark de producto para seguimiento estructurado y confirmatory biopsy en vigilancia activa.",
    supports_rule_ids=["localized_initial.active_surveillance_benchmark"],
    applies_to_modules=["localized_initial", "post_negative_biopsy_followup"],
    field_implications=["confirmatory_biopsy_planned", "psa_kinetics", "active_surveillance_monitoring_only"],
    ui_surfaces=["wizard.sidebar", "dashboard"],
)

ERSPC_RISK_CALCULATOR = citation(
    "erspc_risk_calculator",
    "European Randomized Study of Screening for Prostate Cancer (ERSPC) Risk Calculator.",
    "ERSPC Risk Calculator",
    "benchmark_reference",
    document_id="benchmark_erspc",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://www.prostatecancer-riskcalculator.com/",
    disease_state="Deteccion temprana y rebiopsia",
    followup_implications="Permite refinar umbral diagnostico y de rebiopsia junto con MRI, PSAD y antecedentes, sin sustituir la recomendacion primaria de guias.",
    supports_rule_ids=["diagnostic_workup.erspc_support", "post_negative_biopsy_followup.erspc_support"],
    applies_to_modules=["diagnostic_workup", "post_negative_biopsy_followup"],
    field_implications=["age", "psa", "dre_suspicious", "prior_biopsy_count", "prostate_volume_ml"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "dashboard"],
)

PREDICT_PROSTATE = citation(
    "predict_prostate",
    "PREDICT Prostate survival model.",
    "PREDICT Prostate",
    "benchmark_reference",
    document_id="benchmark_predict_prostate",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://prostate.predict.nhs.uk/",
    disease_state="Localized initial",
    followup_implications="Ayuda a cuantificar beneficio absoluto y apoyar decision compartida en enfermedad localizada, sin desplazar NCCN/EAU.",
    supports_rule_ids=["localized_initial.predict_support"],
    applies_to_modules=["localized_initial"],
    field_implications=["age", "psa", "clinical_tstage", "isup_grade", "life_expectancy_years", "ecog_score", "charlson_score"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

PARTIN_TABLES = citation(
    "partin_tables",
    "Updated Partin Tables for the prediction of final pathological stage.",
    "Partin Tables",
    "benchmark_reference",
    document_id="benchmark_partin",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://pubmed.ncbi.nlm.nih.gov/28318271/",
    disease_state="Localized initial",
    followup_implications="Ayuda a counseling patologico preoperatorio y riesgo ganglionar, sin sustituir la jerarquia de guias.",
    supports_rule_ids=["localized_initial.partin_support"],
    applies_to_modules=["localized_initial"],
    field_implications=["clinical_tstage", "psa", "isup_grade"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

CAPRA_UCSF = citation(
    "capra_ucsf",
    "Cancer of the Prostate Risk Assessment (CAPRA) and CAPRA-S.",
    "CAPRA / CAPRA-S",
    "benchmark_reference",
    document_id="benchmark_capra",
    evidence_role="benchmark",
    license_class="public_web_reference",
    doi_or_url="https://urology.ucsf.edu/research/cancer/prostate-cancer-risk-assessment-and-the-ucla-prostate-cancer-index",
    disease_state="Localized and post-prostatectomy",
    followup_implications="Permite refinar riesgo preoperatorio y posoperatorio como capa de apoyo compatible con NCCN/EAU.",
    supports_rule_ids=["localized_initial.capra_support", "post_prostatectomy.capra_s_support"],
    applies_to_modules=["localized_initial", "post_prostatectomy", "recurrence_bcr"],
    field_implications=["psa", "clinical_tstage", "isup_grade", "pathologic_stage"],
    ui_surfaces=["wizard.sidebar", "wizard.results", "patient_profile"],
)

CRPC_PUBLIC_DEFINITION = citation(
    "nci_crpc_definition",
    "Castrate-resistant prostate cancer definition.",
    "NCI definition",
    "supporting_study",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.cancer.gov/publications/dictionaries/cancer-terms/def/castrate-resistant-prostate-cancer",
    disease_state="CRPC verification",
    followup_implications="Refuerza que la enfermedad resistente a la castración exige progresión con testosterona en rango de castración.",
    supports_rule_ids=["adt_progression_verification.crpc_definition_support"],
    applies_to_modules=["adt_progression_verification"],
    field_implications=["castrate_testosterone_status", "testosterone_value", "progression_pattern"],
    ui_surfaces=["wizard.sidebar", "wizard.results"],
)

FDA_APALUTAMIDE_NMCRPC = citation(
    "fda_apalutamide_nmcrpc",
    "FDA approves apalutamide for non-metastatic castration-resistant prostate cancer.",
    "FDA apalutamide nmCRPC",
    "supporting_study",
    evidence_role="supportive_trial",
    license_class="public_web_reference",
    doi_or_url="https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-apalutamide-non-metastatic-castration-resistant-prostate-cancer",
    disease_state="M0 CRPC",
    followup_implications="Aporta soporte regulatorio para el carril nmCRPC una vez confirmadas castración e imagen convencional M0.",
    supports_rule_ids=["adt_progression_verification.nmcrpc_redirection"],
    applies_to_modules=["adt_progression_verification", "m0_crpc"],
    field_implications=["psadt_months", "castrate_testosterone_status", "conventional_imaging_status"],
    ui_surfaces=["wizard.sidebar", "wizard.results"],
)

DOCUMENTS = _document_registry(
    NCCN_PRIMARY,
    EAU_PRIMARY,
    ACTIVE_SURVEILLANCE_REAL_WORLD,
    BENIGN_BIOPSY_LONG_TERM,
    LATE_RT_TOXICITY,
    PROPEL_SYMPTOMATIC,
    CARD_TRIAL,
    VISION_TRIAL,
    PROFOUND_TRIAL,
    IMPACT_TRIAL,
    CONTACT02_TRIAL,
    EMBARK_FDA,
    AUA_ASTRO_SUO_SALVAGE,
    PSMAFORE_REGULATORY,
    TALAPRO2_REGULATORY,
    AKEEGA_MHSPC,
    TALAPRO3_MHSPC_HRR,
    ARANOTE_DAROLUTAMIDE_FDA,
    REZVILUTAMIDE_CHART,
    APCCC_2024,
    ARSI_CV_META,
    FRAILTY_COMORBIDITY,
    ARPI_DDI_REVIEW,
    EAU_ADT_FOLLOWUP,
    ABIRATERONE_DILI,
    MHSPC_REAL_WORLD,
    MSK_PREOP_NOMOGRAM,
    CANARY_PASS,
    ERSPC_RISK_CALCULATOR,
    PREDICT_PROSTATE,
    PARTIN_TABLES,
    CAPRA_UCSF,
    PROPSMA_TRIAL,
    NCCN_PROS2_GUIDELINE,
    NCCN_PROS3_GUIDELINE,
    NCCN_PROS_G_GUIDELINE,
    EAU_2026_LOCALLY_ADVANCED_NEOADJ,
    LOBLAW_CORD_COMPRESSION,
    NCCN_ONCOLOGIC_EMERGENCIES,
    ASCO_AUA_BONE_HEALTH_2024,
    BRIGANTI_NOMOGRAM_2012,
)

MODULES = {
    "diagnostic_workup": ModuleEvidence(
        module="diagnostic_workup",
        title="Estudio diagnóstico antes de confirmar cáncer de próstata",
        nccn_panels=["PROS-A", "PROS-B"],
        eau_sections=["Diagnostic evaluation", "Risk-adapted early detection"],
        pivotal_trials=[],
        core_questions=[
            "¿La sospecha de cáncer clínicamente significativo justifica resonancia magnética multiparamétrica, biopsia dirigida y biopsia sistemática?",
            "¿Existe un patrón de sospecha suficientemente alto como para planear imagen avanzada tras confirmación histológica?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, ERSPC_RISK_CALCULATOR],
    ),
    "post_negative_biopsy_followup": ModuleEvidence(
        module="post_negative_biopsy_followup",
        title="Seguimiento después de una biopsia benigna inicial",
        nccn_panels=["PROS-A", "PROS-B"],
        eau_sections=["Follow-up after negative biopsy"],
        pivotal_trials=["Palmstedt 2019"],
        core_questions=[
            "¿El seguimiento puede mantenerse de baja intensidad después de una biopsia benigna inicial?",
            "¿Cuándo debe reabrirse el estudio diagnóstico con resonancia magnética o nueva biopsia?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, BENIGN_BIOPSY_LONG_TERM, CANARY_PASS, ERSPC_RISK_CALCULATOR],
    ),
    "localized_initial": ModuleEvidence(
        module="localized_initial",
        title="Diagnóstico inicial localizado o regional con ganglios regionales positivos y sin metástasis a distancia",
        nccn_panels=["PROS-1", "PROS-2", "PROS-3", "PROS-4", "PROS-5", "PROS-6", "PROS-7", "PROS-A", "PROS-B", "PROS-F", "PROS-G", "PROS-H"],
        eau_sections=["Classification and staging systems", "Treatment"],
        pivotal_trials=["ProtecT", "SPCG-4", "PIVOT"],
        core_questions=[
            "¿Cuál es el grupo de riesgo exacto según la Red Nacional Integral del Cáncer (NCCN) versión 5.2026?",
            "¿La vigilancia activa está indicada, es preferente o no se recomienda?",
            "¿Qué tratamientos locales son elegibles según riesgo, expectativa de vida e histología?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, ACTIVE_SURVEILLANCE_REAL_WORLD, LATE_RT_TOXICITY, MSK_PREOP_NOMOGRAM, CANARY_PASS, PARTIN_TABLES, PREDICT_PROSTATE, CAPRA_UCSF],
    ),
    "post_prostatectomy": ModuleEvidence(
        module="post_prostatectomy",
        title="Seguimiento después de prostatectomía radical",
        nccn_panels=["PROS-8", "PROS-9", "PROS-G", "PROS-H"],
        eau_sections=["Treatment", "Follow-up"],
        pivotal_trials=["SWOG-8794", "ARO 96-02", "RADICALS-RT"],
        core_questions=[
            "¿El paciente está en vigilancia, consideración de adyuvancia o escenario de rescate temprano?",
            "¿Cuál es la estimación del puntaje postoperatorio CAPRA-S en el contexto correcto?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, AUA_ASTRO_SUO_SALVAGE, LATE_RT_TOXICITY, CAPRA_UCSF],
    ),
    "post_radiotherapy_followup": ModuleEvidence(
        module="post_radiotherapy_followup",
        title="Seguimiento después de radioterapia radical",
        nccn_panels=["PROS-9"],
        eau_sections=["Follow-up after radical radiotherapy"],
        pivotal_trials=["ProtecT", "RTOG 9408", "DART01/05", "CHHiP", "PACE-B", "ASCENDE-RT"],
        core_questions=[
            "¿El paciente está libre de recurrencia bioquímica post-RT según el criterio Phoenix (PSA nadir + 2.0 ng/mL)?",
            "¿Cuál es la cadencia de PSA y tacto rectal recomendada según el tiempo desde la radioterapia?",
            "¿Qué toxicidad tardía urinaria, intestinal o sexual presenta y cómo debe gestionarse según RTOG/EORTC?",
            "¿Cuándo escalar a restadificación con PSMA-PET, mpMRI y biopsia para evaluar salvage local?",
            "¿Está indicada vigilancia activa de segundos primarios pélvicos (vejiga, recto) y survivorship dirigido a ADT?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, LATE_RT_TOXICITY],
    ),
    "recurrence_bcr": ModuleEvidence(
        module="recurrence_bcr",
        title="Recurrencia bioquímica y segunda recurrencia bioquímica sin metástasis",
        nccn_panels=["PROS-9", "PROS-10", "PROS-11", "PROS-12", "PROS-H"],
        eau_sections=["Treatment", "Biochemical recurrence"],
        pivotal_trials=["RAVES", "GETUG-AFU 16", "SPPORT", "RTOG 9601", "RADICALS-HD", "RADICALS-RT", "EMBARK", "PRESTO"],
        core_questions=[
            "¿Se trata de recurrencia posterior a prostatectomía radical, posterior a radioterapia o segunda recurrencia bioquímica?",
            "¿Está indicado el rescate temprano y debe añadirse terapia de privación androgénica?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, AUA_ASTRO_SUO_SALVAGE, LATE_RT_TOXICITY, EMBARK_FDA, APCCC_2024, CAPRA_UCSF],
    ),
    "post_radiotherapy_or_local_salvage": ModuleEvidence(
        module="post_radiotherapy_or_local_salvage",
        title="Recurrencia post-radioterapia y salvage local",
        nccn_panels=["PROS-10", "PROS-11", "PROS-12", "PROS-H"],
        eau_sections=["Biochemical recurrence", "Salvage after radiotherapy"],
        pivotal_trials=["Salvage modalities post-RT", "PSMA-directed restaging"],
        core_questions=[
            "¿La recurrencia post-RT cumple Phoenix o una confirmación local equivalente antes de abrir salvage curativo?",
            "¿Qué modalidad de salvage local domina hoy frente a MDT o redirección sistémica?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, AUA_ASTRO_SUO_SALVAGE, LATE_RT_TOXICITY, APCCC_2024],
    ),
    "adt_progression_verification": ModuleEvidence(
        module="adt_progression_verification",
        title="Progresión bajo ADT / verificación de castración",
        nccn_panels=["PROS-16", "PROS-17", "PROS-M"],
        eau_sections=["Castration-resistant disease", "Follow-up"],
        pivotal_trials=["SPARTAN", "ARAMIS", "PROSPER"],
        core_questions=[
            "¿Existe testosterona en rango de castración confirmada o primero debe optimizarse la supresión androgénica?",
            "¿La imagen convencional define ya un carril M0 o M1 resistente a la castración?",
            "¿La progresión bajo ADT es solo bioquímica o ya existe progresión radiográfica o clínica con castración confirmada?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, CRPC_PUBLIC_DEFINITION, FDA_APALUTAMIDE_NMCRPC],
    ),
    "mcspc_oligo_metachronous": ModuleEvidence(
        module="mcspc_oligo_metachronous",
        title="Enfermedad metastásica sensible a la castración oligometastásica metacrónica",
        nccn_panels=["PROS-13", "PROS-M", "PROS-N"],
        eau_sections=["Metastatic disease treatment"],
        pivotal_trials=["STAMPEDE", "STAMPEDE-2", "PEACE-1", "ARASENS", "ARCHES", "ENZAMET", "TITAN", "ARANOTE"],
        core_questions=[
            "¿Puede considerarse el tratamiento dirigido a metástasis?",
            "¿Qué intensificación sistémica es elegible?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, AKEEGA_MHSPC, TALAPRO3_MHSPC_HRR, ARANOTE_DAROLUTAMIDE_FDA, REZVILUTAMIDE_CHART, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI, MHSPC_REAL_WORLD],
    ),
    "mcspc_low_volume_sync_oligo": ModuleEvidence(
        module="mcspc_low_volume_sync_oligo",
        title="Enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica",
        nccn_panels=["PROS-14", "PROS-M", "PROS-N"],
        eau_sections=["Metastatic disease treatment"],
        pivotal_trials=["STAMPEDE", "STAMPEDE H", "ARCHES", "ENZAMET", "TITAN", "ARANOTE", "PEACE-1"],
        core_questions=[
            "¿La radioterapia al tumor primario es apropiada?",
            "¿Qué doblete se ajusta mejor a este paciente?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, AKEEGA_MHSPC, TALAPRO3_MHSPC_HRR, ARANOTE_DAROLUTAMIDE_FDA, REZVILUTAMIDE_CHART, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI, MHSPC_REAL_WORLD],
    ),
    "mcspc_high_volume_sync": ModuleEvidence(
        module="mcspc_high_volume_sync",
        title="Enfermedad metastásica sensible a la castración de alto volumen sincrónica",
        nccn_panels=["PROS-15", "PROS-M", "PROS-N"],
        eau_sections=["Metastatic disease treatment"],
        pivotal_trials=["CHAARTED", "LATITUDE", "STAMPEDE", "ARANOTE", "ARASENS", "PEACE-1"],
        core_questions=[
            "¿El paciente es apto para docetaxel según ECOG, neuropatía, fragilidad y Child-Pugh?",
            "¿Debe priorizarse triplete y qué backbone trial-like corresponde en enfermedad de novo/sincrónica?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, AKEEGA_MHSPC, TALAPRO3_MHSPC_HRR, ARANOTE_DAROLUTAMIDE_FDA, REZVILUTAMIDE_CHART, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI, MHSPC_REAL_WORLD],
    ),
    "mcspc_high_volume_metachronous": ModuleEvidence(
        module="mcspc_high_volume_metachronous",
        title="Enfermedad metastásica sensible a la castración de alto volumen metacrónica",
        nccn_panels=["PROS-15", "PROS-M", "PROS-N"],
        eau_sections=["Metastatic disease treatment"],
        pivotal_trials=["CHAARTED", "LATITUDE", "STAMPEDE", "ARANOTE", "ARASENS", "PEACE-1"],
        core_questions=[
            "¿El paciente es apto para docetaxel según ECOG, neuropatía, fragilidad y Child-Pugh?",
            "¿Debe intensificarse con triplete o doblete visible sin sobreextrapolar PEACE-1 como backbone principal?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, AKEEGA_MHSPC, TALAPRO3_MHSPC_HRR, ARANOTE_DAROLUTAMIDE_FDA, REZVILUTAMIDE_CHART, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI, MHSPC_REAL_WORLD],
    ),
    "mcspc_high_volume": ModuleEvidence(
        module="mcspc_high_volume",
        title="Enfermedad metastásica sensible a la castración de alto volumen",
        nccn_panels=["PROS-15", "PROS-M", "PROS-N"],
        eau_sections=["Metastatic disease treatment"],
        pivotal_trials=["CHAARTED", "LATITUDE", "STAMPEDE", "ARANOTE", "ARASENS", "PEACE-1"],
        core_questions=[
            "¿El paciente es apto para docetaxel?",
            "¿Qué triplete o doblete debe priorizarse?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, AKEEGA_MHSPC, TALAPRO3_MHSPC_HRR, ARANOTE_DAROLUTAMIDE_FDA, REZVILUTAMIDE_CHART, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI, MHSPC_REAL_WORLD],
    ),
    "m0_crpc": ModuleEvidence(
        module="m0_crpc",
        title="Enfermedad resistente a la castración sin metástasis",
        nccn_panels=["PROS-16", "PROS-M"],
        eau_sections=["Castration-resistant disease"],
        pivotal_trials=["SPARTAN", "PROSPER", "ARAMIS", "AMPLITUDE"],
        core_questions=[
            "¿El paciente tiene alto riesgo de enfermedad resistente a la castración sin metástasis según el tiempo de duplicación del antígeno prostático específico?",
            "¿Qué inhibidor del receptor androgénico se ajusta mejor a las contraindicaciones?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW],
    ),
    "m1_crpc": ModuleEvidence(
        module="m1_crpc",
        title="Enfermedad resistente a la castración con metástasis",
        nccn_panels=["PROS-17", "PROS-18", "PROS-C", "PROS-M"],
        eau_sections=["Castration-resistant disease"],
        pivotal_trials=[
            "PROfound", "VISION", "CARD", "TALAPRO-2", "MAGNITUDE", "PROpel", "KEYNOTE-158",
            "TAX-327", "TROPIC", "COU-AA-301", "COU-AA-302", "AFFIRM", "PREVAIL",
            "TheraP", "PEACE-3", "IMPACT", "CONTACT-02", "ALSYMPCA",
            "PSMAfore", "TRITON-3", "IPATential150",
        ],
        core_questions=[
            "¿Qué clase terapéutica permanece activa después de la exposición previa a inhibidores del receptor androgénico y taxanos?",
            "¿Existen opciones guiadas por biomarcadores?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, CARD_TRIAL, VISION_TRIAL, PROFOUND_TRIAL, IMPACT_TRIAL, CONTACT02_TRIAL, PSMAFORE_REGULATORY, TALAPRO2_REGULATORY, PROPEL_SYMPTOMATIC, APCCC_2024, ARSI_CV_META, FRAILTY_COMORBIDITY, ARPI_DDI_REVIEW, ABIRATERONE_DILI],
    ),
    "survivorship_and_toxicity_followup": ModuleEvidence(
        module="survivorship_and_toxicity_followup",
        title="Survivorship y toxicidad por tratamiento",
        nccn_panels=["Survivorship", "Supportive Care"],
        eau_sections=["Quality of life", "Treatment toxicity follow-up", "Survivorship"],
        pivotal_trials=["IRRADIaTE late toxicity", "ICHOM PROs", "ADT survivorship"],
        core_questions=[
            "¿Qué secuela tardía o toxicidad domina hoy la conducta clínica?",
            "¿Debe priorizarse rehabilitación, referencia específica o reabrir una decisión oncológica desde survivorship?",
        ],
        source_citations=[NCCN_PRIMARY, EAU_PRIMARY, EAU_ADT_FOLLOWUP, LATE_RT_TOXICITY],
    ),
}
