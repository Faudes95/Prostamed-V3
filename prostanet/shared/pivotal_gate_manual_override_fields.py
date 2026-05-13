# IEC 62304 §5.5 (Software unit verification)
"""EPIC 10F — Pivotal gate manual override fields.

Declara como FieldSpecs canónicos los "override strings narrativos" usados
por los 20 gates pivotales que EPIC 10B identificó como huérfanos:
flags booleanos que un clínico debe declarar explícitamente para activar
un escape hatch (e.g., "PTEN IHC ordenado en últimas 2 semanas", "Child-Pugh
A con monitoreo hepatology documentado", "consenso multidisciplinario para
PARP en HRR-negative con justificación").

A diferencia de fields de captura clínica rutinaria (PSA, Gleason, etc.)
o de comorbilidades (NYHA, LVEF — añadidas en EPIC 10B paso A+D), estos
son **declaraciones procedimentales explícitas** del clínico que avalan
una decisión que normalmente sería contraindicada. Cada uno se modela
como `select 0/1` con `clinical_role="manual_override"` y evidence_tags
trazables al gate que lo consume.

Sin esta declaración el override no se aplica → el hard-block original
se mantiene. Por eso son flags binarios documentables, no campos de
captura libre.

Cobertura:
  18 categorías clínicas, 59 FieldSpecs flag, todos linkeados al gate
  pivotal correspondiente vía `evidence_tags`.

Categorías:
  - Anticoagulación pre-RP (gate anticoagulant_rp_bleeding_risk)
  - AR-V7 / ARPI resistance pathway (gate ar_v7_positive_arpi_resistance_pathway)
  - Brachytherapy post-TURP (gate turp_brachytherapy_contraindication)
  - Child-Pugh / hepatology (gate abiraterone_cirrhosis_baseline_contraindication)
  - Composite progression rPFS (gate composite_progression_rpfs_reroute)
  - Cognitive decline ARSI (gate arsi_in_cognitive_decline_grade2)
  - GI / diarrea taxanos (gate taxane_diarrhea_grade3_plus)
  - Neurology cumulative neuropathy (gate docetaxel_neuropathy_cumulative_postchemo)
  - Oncologic emergency management (gate oncologic_emergency_diagnostic_integration)
  - Oligometastatic palliative RT (gate palliative_rt_decision_engine)
  - HFSR aggressive management (gate hand_foot_syndrome_tkis_grade2_plus)
  - IBD pelvic RT (gate ibd_active_pelvic_rt_contraindication)
  - Immunosuppression sipuleucel-T (gate sipuleucel_t_immunosuppression_baseline)
  - PARP HRR-negative override (gate parp_hrr_negative_futility_block)
  - PTEN pending workflow (gate ipatasertib_pten_wt_futility_block)
  - RP multimodal patient-accept (gate svi_risk_high_rp_efficiency_warning)
  - Pelvic re-irradiation (gate prior_pelvic_rt_re_irradiation_contraindication)
  - PSMA-PET preferred for nmCRPC (gate psma_pet_preferred_for_nmcrpc_low_psa)
  - QTc grade 3 categorical (gate qtc_prolongation_grade3_for_enzalutamide)
"""
from __future__ import annotations

from prostanet.shared.contracts import FieldSpec


def _flag(
    name: str,
    label: str,
    *,
    group: str,
    group_order: int,
    evidence_tags: list[str],
    help_text: str = "",
) -> FieldSpec:
    """Helper para declarar un flag booleano de manual override."""
    return FieldSpec(
        name,
        label,
        "select",
        options=["0", "1"],
        default="0",
        group=group,
        group_order=group_order,
        clinical_role="manual_override",
        evidence_tags=["epic10f_manual_override", *evidence_tags],
        help_text=help_text,
    )


def pivotal_gate_manual_override_fields(*, group_order: int) -> list[FieldSpec]:
    """Retorna 59 FieldSpec flags categorizados por gate clínico.

    Args:
        group_order: orden visual relativo a otros bloques del schema.
    """
    g = "Override manual de gates pivotales (declaración procedimental)"
    return [
        # ── Anticoagulación pre-RP (gate anticoagulant_rp_bleeding_risk) ──
        _flag("antiagregante", "Antiagregante en curso (ES alias)",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "es_alias"],
              help_text="Alias ES de antiplatelet. Activa evaluación de bleeding risk pre-RP."),
        _flag("antiplatelet", "Antiplatelet agent active",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp"],
              help_text="Antiagregante plaquetario activo (clopidogrel, ticagrelor, prasugrel, aspirina)."),
        _flag("antiplatelet_agent", "Antiplatelet agent (alt naming)",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "alias"]),
        _flag("anesthesia_approved_anticoag_management", "Anestesiología aprobó plan de manejo anticoagulante",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "anesthesia_clearance"],
              help_text="Override: anestesia documentó plan pre-operatorio explícito."),
        _flag("anticoagulation_bridged_with_anesthesia_clearance", "Bridging anticoagulante con clearance de anestesia",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "bridging"]),
        _flag("bridging_documented_pre_rp", "Bridging documentado pre-RP",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "bridging"]),
        _flag("puente_anticoagulacion_documentado", "Puente de anticoagulación documentado (ES)",
              group=g, group_order=group_order,
              evidence_tags=["anticoag_rp", "bridging", "es_alias"]),

        # ── AR-V7 / ARPI resistance (gate ar_v7_positive_arpi_resistance_pathway) ──
        _flag("ar_v7_positive_arpi_attempted_with_close_monitoring", "AR-V7+ con intento ARPI bajo monitoreo estrecho",
              group=g, group_order=group_order,
              evidence_tags=["arv7", "prophecy", "armstrong_2019"],
              help_text="Override PROPHECY: AR-V7+ permite intentar ARPI si hay monitoreo estrecho documentado."),
        _flag("arpi_attempted_despite_ar_v7", "ARPI intentada a pesar de AR-V7+",
              group=g, group_order=group_order,
              evidence_tags=["arv7", "prophecy"]),
        _flag("decisión_informada_arpi_ar_v7", "Decisión informada AR-V7 + ARPI (ES)",
              group=g, group_order=group_order,
              evidence_tags=["arv7", "prophecy", "es_alias"]),

        # ── Brachytherapy post-TURP (gate turp_brachytherapy_contraindication) ──
        _flag("brachy_after_turp_expert_protocol_documented", "Brachytherapy post-TURP con protocolo de centro experto documentado",
              group=g, group_order=group_order,
              evidence_tags=["brachy_post_turp"],
              help_text="Override: brachytherapy permisible tras TURP solo en centros con protocolo especializado."),
        _flag("brachytherapy_post_turp_specialized_protocol", "Brachytherapy post-TURP con protocolo especializado",
              group=g, group_order=group_order,
              evidence_tags=["brachy_post_turp"]),
        _flag("centro_experto_brachy_post_turp", "Centro experto brachy post-TURP (ES)",
              group=g, group_order=group_order,
              evidence_tags=["brachy_post_turp", "es_alias"]),

        # ── Child-Pugh / hepatology (gate abiraterone_cirrhosis_baseline_contraindication) ──
        _flag("child_pugh_a_confirmed_with_close_monitoring", "Child-Pugh A confirmado con monitoreo estrecho",
              group=g, group_order=group_order,
              evidence_tags=["child_pugh", "abiraterone_hepatotoxicity"],
              help_text="Override Zytiga §5.1: Child-Pugh A permisible con monitoreo hepático estrecho documentado."),
        _flag("child_pugh_a_with_hepatology_monitoring_documented", "Child-Pugh A con monitoreo hepatology documentado",
              group=g, group_order=group_order,
              evidence_tags=["child_pugh", "abiraterone_hepatotoxicity", "hepatology_consult"]),
        _flag("hepatology_consult_active", "Hepatology consult activa",
              group=g, group_order=group_order,
              evidence_tags=["hepatology_consult"]),

        # ── Composite progression rPFS (gate composite_progression_rpfs_reroute) ──
        _flag("clinical_progression_documented", "Progresión clínica documentada (rPFS reroute)",
              group=g, group_order=group_order,
              evidence_tags=["composite_progression", "rpfs", "pcwg3"],
              help_text="Override PCWG3: progresión clínica documentada permite reroute composite rPFS."),

        # ── Cognitive decline ARSI (gate arsi_in_cognitive_decline_grade2) ──
        _flag("cognitive_decline_documented", "Declive cognitivo documentado",
              group=g, group_order=group_order,
              evidence_tags=["cognitive_arsi", "siog_geriatric"],
              help_text="Override ARSI: declive cognitivo documentado bloquea o redirige ARSI según escenario."),
        _flag("cognitive_decline_grade2_documented", "Declive cognitivo grado 2 documentado (CTCAE)",
              group=g, group_order=group_order,
              evidence_tags=["cognitive_arsi", "ctcae_v5"]),

        # ── GI / diarrea taxanos (gate taxane_diarrhea_grade3_plus) ──
        _flag("diarrhea_octreotide_initiated", "Octreótido iniciado para diarrea taxanos",
              group=g, group_order=group_order,
              evidence_tags=["taxane_diarrhea", "octreotide", "asco_supportive_care"],
              help_text="Override: octreótido iniciado permite continuación cautelosa de taxano."),
        _flag("gi_consult_active", "Gastroenterología activa",
              group=g, group_order=group_order,
              evidence_tags=["gi_consult"]),
        _flag("taxane_diarrhea_aggressive_management_documented", "Manejo agresivo de diarrea taxánica documentado",
              group=g, group_order=group_order,
              evidence_tags=["taxane_diarrhea", "asco_supportive_care"]),

        # ── Neurology cumulative neuropathy (gate docetaxel_neuropathy_cumulative_postchemo) ──
        _flag("dose_reduced_with_neuro_consult_clearance", "Reducción de dosis con clearance neurología",
              group=g, group_order=group_order,
              evidence_tags=["taxane_neuropathy", "ctcae_v5", "neuro_consult"],
              help_text="Override: dose reduction 25% con clearance neurología permite continuación post-grade 2."),
        _flag("neurology_consult_active_continuation_documented", "Neurología activa con plan de continuación documentado",
              group=g, group_order=group_order,
              evidence_tags=["taxane_neuropathy", "neuro_consult"]),
        _flag("taxane_dose_reduction_25pct_with_neuro_clearance", "Reducción 25% taxano con clearance neurología",
              group=g, group_order=group_order,
              evidence_tags=["taxane_neuropathy", "neuro_consult"]),

        # ── Oncologic emergency management (gate oncologic_emergency_diagnostic_integration) ──
        _flag("emergency_managed_by_team_documented", "Equipo manejando emergencia oncológica documentado",
              group=g, group_order=group_order,
              evidence_tags=["oncologic_emergency", "nccn_emergencies"],
              help_text="Override NCCN Emergencies: emergencia bajo manejo activo del equipo multidisciplinario."),
        _flag("emergency_team_managed_documented", "Equipo de emergencia clínica documentado",
              group=g, group_order=group_order,
              evidence_tags=["oncologic_emergency", "nccn_emergencies"]),
        _flag("linfangitis_carcinomatosa_documentada", "Linfangitis carcinomatosa documentada (ES)",
              group=g, group_order=group_order,
              evidence_tags=["lymphangitic_carcinomatosis", "oncologic_emergency", "es_alias"]),
        _flag("lymphangitic_carcinomatosis_documented", "Lymphangitic carcinomatosis documented",
              group=g, group_order=group_order,
              evidence_tags=["lymphangitic_carcinomatosis", "oncologic_emergency"]),

        # ── Oligometastatic palliative RT (gate palliative_rt_decision_engine) ──
        _flag("enfermedad_oligometastasica", "Enfermedad oligometastásica (ES)",
              group=g, group_order=group_order,
              evidence_tags=["oligometastatic", "es_alias"]),
        _flag("oligometastatic_disease_documented", "Oligometastatic disease documented",
              group=g, group_order=group_order,
              evidence_tags=["oligometastatic", "stomp", "oriole"],
              help_text="Override STOMP/ORIOLE: enfermedad oligometastásica documentada habilita MDT/SBRT pathway."),

        # ── HFSR (TKI rash) (gate hand_foot_syndrome_tkis_grade2_plus) ──
        _flag("hfsr_aggressive_topical_management_documented", "HFSR manejo tópico agresivo documentado",
              group=g, group_order=group_order,
              evidence_tags=["hfsr_tki", "cabozantinib_safety"],
              help_text="Override TKI: HFSR grade ≥2 manejable con tópicos agresivos + monitoreo permite continuación."),
        _flag("hfsr_high_potency_steroid_initiated", "Esteroide tópico alta potencia iniciado para HFSR",
              group=g, group_order=group_order,
              evidence_tags=["hfsr_tki"]),
        _flag("hfsr_urea_20_started", "Urea 20% iniciada para HFSR",
              group=g, group_order=group_order,
              evidence_tags=["hfsr_tki"]),

        # ── IBD pelvic RT (gate ibd_active_pelvic_rt_contraindication) ──
        _flag("ibd_diagnosis_type", "Tipo de diagnóstico IBD (Crohn / UC)",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt"]),
        _flag("ibd_subtype", "Subtipo IBD (alias)",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "alias"]),
        _flag("tipo_ibd", "Tipo IBD (ES)",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "es_alias"]),
        _flag("ibd_quiescent_2yr_documented", "IBD quiescente ≥2 años documentado",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "ibd_remission"],
              help_text="Override: IBD en remisión ≥2 años permite pelvic RT cauteloso."),
        _flag("ibd_remision_2anios_gi_aprobado", "IBD remisión 2 años con clearance GI (ES)",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "ibd_remission", "gi_consult", "es_alias"]),
        _flag("ibd_remission_2yr_with_gi_clearance", "IBD remission 2yr with GI clearance",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "ibd_remission", "gi_consult"]),
        _flag("remission_2yr_gi_cleared", "Remission 2yr GI cleared (alias)",
              group=g, group_order=group_order,
              evidence_tags=["ibd_pelvic_rt", "ibd_remission", "alias"]),

        # ── Immunosuppression sipuleucel-T (gate sipuleucel_t_immunosuppression_baseline) ──
        _flag("immune_function_recovered_documented", "Función inmune recuperada documentada",
              group=g, group_order=group_order,
              evidence_tags=["sipuleucel_t", "immune_recovery"],
              help_text="Override sipuleucel-T: función inmune recuperada documentada permite vaccine therapy."),
        _flag("immunosuppression_resolved_with_id_clearance", "Inmunosupresión resuelta con clearance infectious disease",
              group=g, group_order=group_order,
              evidence_tags=["sipuleucel_t", "immune_recovery", "id_consult"]),
        _flag("infectious_disease_consult_cleared", "Infectious disease consult cleared",
              group=g, group_order=group_order,
              evidence_tags=["id_consult"]),

        # ── PARP HRR-negative override (gate parp_hrr_negative_futility_block) ──
        _flag("parp_in_all_comers_trial_with_rationale", "PARPi en all-comers trial con justificación",
              group=g, group_order=group_order,
              evidence_tags=["parp_hrr_neg", "trial_enrollment"],
              help_text="Override: PARPi en HRR-negative permisible solo dentro de ensayo all-comers con rationale documentado."),
        _flag("propel_or_talapro2_setting_documented", "Setting PROpel / TALAPRO-2 documentado",
              group=g, group_order=group_order,
              evidence_tags=["parp_hrr_neg", "propel", "talapro2"]),

        # ── PTEN pending workflow (gate ipatasertib_pten_wt_futility_block) ──
        _flag("pten_ihc_ordered_within_2weeks", "PTEN IHC ordenado en ≤2 semanas",
              group=g, group_order=group_order,
              evidence_tags=["pten", "ipatential150", "ipatasertib"],
              help_text="Override IPATential150: PTEN test pendiente con orden documentada en últimas 2 semanas permite hold cautious."),
        _flag("pten_pending_with_plan", "PTEN pending con plan documentado",
              group=g, group_order=group_order,
              evidence_tags=["pten", "ipatasertib"]),
        _flag("pten_test_pending_with_2week_plan_documented", "PTEN test pending con plan 2 semanas documentado",
              group=g, group_order=group_order,
              evidence_tags=["pten", "ipatasertib"]),

        # ── RP multimodal patient-accept (gate svi_risk_high_rp_efficiency_warning) ──
        _flag("patient_accepts_rp_with_adjuvant_plan", "Paciente acepta RP con plan adjuvante",
              group=g, group_order=group_order,
              evidence_tags=["rp_multimodal", "shared_decision_making"],
              help_text="Override: paciente con SVI alto riesgo acepta RP entendiendo necesidad probable de adjuvante."),
        _flag("rp_acepta_multimodal_post_op", "Paciente acepta RP multimodal post-operatoria (ES)",
              group=g, group_order=group_order,
              evidence_tags=["rp_multimodal", "shared_decision_making", "es_alias"]),
        _flag("rp_multimodal_planned", "RP multimodal planificada",
              group=g, group_order=group_order,
              evidence_tags=["rp_multimodal"]),
        _flag("rp_with_planned_adjuvant_documented", "RP con adjuvante planificado documentado",
              group=g, group_order=group_order,
              evidence_tags=["rp_multimodal"]),

        # ── Pelvic re-irradiation (gate prior_pelvic_rt_re_irradiation_contraindication) ──
        _flag("pelvic_re_rt_contraindicated", "Re-irradiación pélvica contraindicada",
              group=g, group_order=group_order,
              evidence_tags=["pelvic_reirradiation"],
              help_text="Flag explícito: contraindicación a re-irradiación pélvica confirmada por equipo radioterapia."),
        _flag("re_irradiation_pelvic_contraindicated_documented", "Re-irradiación pélvica contraindicada documentada",
              group=g, group_order=group_order,
              evidence_tags=["pelvic_reirradiation"]),
        _flag("reirradiacion_pelvica_contraindicada", "Reirradiación pélvica contraindicada (ES)",
              group=g, group_order=group_order,
              evidence_tags=["pelvic_reirradiation", "es_alias"]),

        # ── PSMA-PET preferred for nmCRPC (gate psma_pet_preferred_for_nmcrpc_low_psa) ──
        _flag("psma_pet_preferred_recommendation_documented", "PSMA-PET recomendado documentado",
              group=g, group_order=group_order,
              evidence_tags=["psma_pet_nmcrpc"],
              help_text="Informational: recomendación PSMA-PET preferida en nmCRPC con PSA bajo aceptada por equipo."),
        _flag("psma_pet_recomendado_documentado", "PSMA-PET recomendado documentado (ES)",
              group=g, group_order=group_order,
              evidence_tags=["psma_pet_nmcrpc", "es_alias"]),

        # ── QTc grade 3 categorical (gate qtc_prolongation_grade3_for_enzalutamide) ──
        _flag("qtc_prolongation_grade3", "QTc grade 3 prolongación (CTCAE)",
              group=g, group_order=group_order,
              evidence_tags=["qtc", "ctcae_v5", "enzamet"],
              help_text="Flag categórico CTCAE grade 3 QTc >501ms — alternativa al cálculo numérico qtc_ms/qtc_change_ms."),
    ]


__all__ = ["pivotal_gate_manual_override_fields"]
