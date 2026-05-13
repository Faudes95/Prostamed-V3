"""ProstaMed Autonomous Clinical Improvement OS.

Read-only, shadow-mode layer that turns existing clinical engines into a
controlled improvement loop. It does not mutate clinical facts, train models,
merge code, prescribe, or execute external orders.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).parent.parent.parent
PERSISTENCE_DIR = PROJECT_ROOT / "prostanet" / "agentic" / "persistence"
REVIEW_LOG = PERSISTENCE_DIR / "autonomous_improvement_reviews.jsonl"
SHADOW_EXECUTION_ARTIFACTS_DIRNAME = "shadow_execution_artifacts"

AUTONOMOUS_LOOP_ROADMAP_PHASES = (
    ("1_mission_control", "build_mission_control"),
    ("2_gap_intelligence", "build_gap_intelligence"),
    ("3a_development_autodrive", "build_development_autodrive"),
    ("3b_shadow_pr_factory", "build_shadow_pr_factory"),
    ("3c_safety_gate_runner", "build_safety_gate_runner"),
    ("3d_shadow_execution_artifacts", "build_shadow_execution_artifacts"),
    ("3e_human_review_decision_gate", "build_human_review_decision_gate"),
    ("3f_draft_pr_handoff", "build_draft_pr_handoff"),
    ("3g_pr_review_monitor", "build_pr_review_monitor"),
    ("4a_agent_lane_registry", "build_agent_lane_registry"),
    ("4b_agent_proposal_packets", "build_agent_proposal_packets"),
    ("4c_agent_consensus_synthesizer", "build_agent_consensus_synthesizer"),
    ("4d_implementation_brief", "build_agent_implementation_brief"),
    ("4e_shadow_patch_blueprint", "build_shadow_patch_blueprint"),
    ("4f_human_patch_authorization", "build_human_patch_authorization"),
    ("4g_controlled_patch_application", "build_controlled_patch_application"),
    ("5a_controlled_pr_implementation", "build_controlled_pr_implementation"),
    ("5b_draft_pr_publication_gate", "build_draft_pr_publication_gate"),
    ("6a_required_safety_gate_contract", "build_required_safety_gate_contract"),
    ("7a_evidence_refresh_shadow_loop", "build_evidence_refresh_shadow_loop"),
    ("8a_patient_twin_readiness_loop", "build_patient_twin_readiness_loop"),
    ("9a_ai_readiness_dataset_loop", "build_ai_readiness_dataset_loop"),
    ("10a_cortana_loop_interface", "build_cortana_loop_interface"),
)

ALLOWED_STATES = (
    "shadow",
    "proposal_ready",
    "validated",
    "human_review_required",
    "blocked",
    "rollback_required",
)

DEVELOPMENT_LANES = (
    "critical_clinical_gap",
    "data_integrity_gap",
    "evidence_gap",
    "safety_security_gap",
    "ui_workflow_gap",
    "regulatory_traceability_gap",
)

DEVELOPMENT_PRIORITIZATION_FACTORS = (
    {
        "key": "clinical_severity",
        "label": "Clinical severity",
        "description": "How much harm, delay or misclassification this gap can avoid.",
    },
    {
        "key": "decision_today_blocking",
        "label": "Decision Today blocking",
        "description": "Whether the gap blocks or contradicts the canonical Decision Today.",
    },
    {
        "key": "patient_scope",
        "label": "Patient scope",
        "description": "How many scanned patients, states or contracts are affected.",
    },
    {
        "key": "safety_security",
        "label": "Safety/security",
        "description": "PHI, unsafe fallback, auto-merge or provenance risk.",
    },
    {
        "key": "evidence_traceability",
        "label": "Evidence and traceability",
        "description": "Evidence freshness, tests, rollback and regulatory traceability.",
    },
    {
        "key": "effort_penalty",
        "label": "Effort penalty",
        "description": "Smaller, testable changes should win within one iteration.",
    },
)

SHADOW_PR_LABELS = (
    "prostamed-autonomous-improvement",
    "shadow-mode",
    "human-review-required",
    "clinical-safety-gated",
)

SAFETY_GATE_STATUSES = ("passed", "blocked", "requires_human_review")
SHADOW_EXECUTION_STATUSES = (
    "pending_execution",
    "partial_execution",
    "failed",
    "requires_visual_validation",
    "verified_pending_human_review",
    "blocked",
)
HUMAN_REVIEW_DECISIONS = (
    "approve_for_pr",
    "request_changes",
    "reject",
    "hold",
)
DRAFT_PR_HANDOFF_STATUSES = (
    "blocked_no_shadow_package",
    "blocked_until_artifact_verified",
    "blocked_until_human_approval",
    "ready_for_manual_pr_creation",
)
PR_REVIEW_MONITOR_STATUSES = (
    "blocked_until_handoff_ready",
    "no_pr_yet",
    "branch_ready_no_pr",
    "pr_open",
    "ci_running",
    "changes_requested",
    "blocked",
    "validated_pending_human_merge",
)
PR_REVIEW_CI_STATUSES = ("unknown", "pending", "running", "passed", "failed", "cancelled")
PR_REVIEW_REVIEW_STATUSES = ("pending", "approved", "changes_requested", "blocked", "commented")
PATCH_AUTHORIZATION_DECISIONS = (
    "authorize_patch",
    "request_changes",
    "reject",
    "hold",
)
SHADOW_COMMAND_ALLOWLIST = (
    "python3 -m py_compile ",
    "pytest -q tests/",
)

AGENT_LANES = {
    "clinical_logic": {
        "label": "Clinical Logic Agent",
        "scope": "gates, trials, state, Decision Today",
        "may_modify": False,
    },
    "data_contract": {
        "label": "Data Contract Agent",
        "scope": "fields, provenance, persistence, router",
        "may_modify": False,
    },
    "ui_verification": {
        "label": "UI Verification Agent",
        "scope": "hub, profile, longitudinal, dashboard, mobile",
        "may_modify": False,
    },
    "evidence": {
        "label": "Evidence Agent",
        "scope": "EAU/FDA/NCI/ClinicalTrials.gov evidence changes",
        "may_modify": False,
    },
    "security": {
        "label": "Security Agent",
        "scope": "PHI, permissions, headers, encryption, logs",
        "may_modify": False,
    },
    "regulatory": {
        "label": "Regulatory Agent",
        "scope": "QMS, DHF, traceability, change control",
        "may_modify": False,
    },
}

GOAL_REGISTRY = {
    "objective": (
        "For this patient, with these data, values and trajectory, ProstaMed "
        "returns the best releaseable Decision Today, what is expected, what "
        "will be watched, and what would change course."
    ),
    "metrics": [
        {
            "key": "clinical_coverage",
            "label": "Clinical coverage",
            "target": "103/103 gates + 47/47 trials under explicit contracts",
            "weight": 0.18,
        },
        {
            "key": "data_quality",
            "label": "Data quality",
            "target": "critical fields captured, persisted and provenanced",
            "weight": 0.14,
        },
        {
            "key": "decision_today_alignment",
            "label": "Decision Today coherence",
            "target": "dashboard, patients, profile, signals and Cortana agree",
            "weight": 0.16,
        },
        {
            "key": "patient_twin_readiness",
            "label": "Patient Twin readiness",
            "target": "values, PROs, preferences and longitudinal thresholds ready",
            "weight": 0.12,
        },
        {
            "key": "safety_security",
            "label": "Safety and security",
            "target": "no PHI leakage, no unsafe auto-merge, no clinical fallback",
            "weight": 0.12,
        },
        {
            "key": "evidence_currentness",
            "label": "Evidence currentness",
            "target": "EAU/FDA/NCI/ClinicalTrials.gov changes reviewed",
            "weight": 0.1,
        },
        {
            "key": "ui_performance",
            "label": "UI performance",
            "target": "visual validation, no overlap, reachable CTAs",
            "weight": 0.06,
        },
        {
            "key": "usability_clinical",
            "label": "Clinical usability",
            "target": "low friction capture and correct surface routing",
            "weight": 0.06,
        },
        {
            "key": "autonomous_loop_maturity",
            "label": "Autonomous loop maturity",
            "target": "mission control, gaps, safety, PR monitor, specialized agents, consensus, implementation brief, patch blueprint and human authorization wired",
            "weight": 0.06,
        },
        {
            "key": "regulatory_readiness",
            "label": "Regulatory readiness",
            "target": "DHF/QMS/traceability/change-control ready",
            "weight": 0.04,
        },
    ],
    "states": list(ALLOWED_STATES),
    "default_mode": "shadow",
    "auto_merge_default": False,
}

EVIDENCE_REFRESH_SOURCE_REGISTRY = (
    {
        "source_id": "eau_prostate_cancer_guidelines",
        "label": "EAU Prostate Cancer Guidelines",
        "url": "https://uroweb.org/guidelines/prostate-cancer",
        "scope": "diagnosis, localized disease, recurrence, metastatic states and follow-up",
        "cadence": "weekly_shadow_check",
        "mapped_consumers": ["decision_today", "readiness", "tumor_board_os", "care_pathway_os", "pivotal_gates"],
    },
    {
        "source_id": "fda_oncology_approvals",
        "label": "FDA Oncology Approval Notifications",
        "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/oncology-cancer-hematologic-malignancies-approval-notifications",
        "scope": "new approvals, indication changes, safety updates and labels",
        "cadence": "weekly_shadow_check",
        "mapped_consumers": ["tumor_board_os", "therapeutic_readiness", "pivotal_trials", "evidence_currentness"],
    },
    {
        "source_id": "clinicaltrials_pivotal_trials",
        "label": "ClinicalTrials.gov pivotal prostate cancer trials",
        "url": "https://clinicaltrials.gov/",
        "scope": "trial status, criteria, NCT metadata and pivotal trial mappings",
        "cadence": "weekly_shadow_check",
        "mapped_consumers": ["trial_eligibility", "tumor_board_os", "pivotal_trials", "autodrive"],
    },
    {
        "source_id": "nci_pro_ctcae",
        "label": "NCI PRO-CTCAE",
        "url": "https://healthcaredelivery.cancer.gov/pro-ctcae/",
        "scope": "patient-reported toxicity and symptom measurement vocabulary",
        "cadence": "monthly_shadow_check",
        "mapped_consumers": ["longitudinal_followup", "care_pathway_os", "clinical_memory_os", "supportive_care"],
    },
    {
        "source_id": "fda_project_patient_voice",
        "label": "FDA Project Patient Voice",
        "url": "https://www.fda.gov/about-fda/oncology-center-excellence/project-patient-voice",
        "scope": "patient-reported symptomatic adverse events for oncology therapies",
        "cadence": "monthly_shadow_check",
        "mapped_consumers": ["clinical_memory_os", "supportive_care", "safety_readiness", "patient_twin"],
    },
    {
        "source_id": "fda_patient_focused_drug_development",
        "label": "FDA Patient-Focused Drug Development",
        "url": "https://www.fda.gov/drugs/development-approval-process-drugs/fda-patient-focused-drug-development-guidance-series-enhancing-incorporation-patients-voice-medical",
        "scope": "preference, outcomes, COA and patient voice regulatory guidance",
        "cadence": "monthly_shadow_check",
        "mapped_consumers": ["patient_twin", "clinical_memory_os", "regulatory_readiness"],
    },
)

PATIENT_TWIN_READINESS_DIMENSIONS = (
    {
        "dimension_id": "patient_values",
        "label": "Valores y preferencia del paciente",
        "required_fields": ["patient_values", "goal_of_care", "decision_tradeoff"],
        "field_aliases": ["patient_values", "patient_preference", "values", "goal_of_care", "decision_tradeoff", "tradeoff"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=patient_values",
        "persistence": "patient_clinical_facts + patient_events + data_provenance",
        "consumer": "Decision Today + Patient Twin + Tumor Board OS",
    },
    {
        "dimension_id": "baseline_pro",
        "label": "PRO baseline",
        "required_fields": ["baseline_pro", "epic26_or_esas", "pain_or_function_baseline"],
        "field_aliases": ["baseline_pro", "pros", "pro", "epic26", "esas", "pain", "function_baseline"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=baseline_pro",
        "persistence": "PRO baseline + stage_visit_records",
        "consumer": "Patient Twin + Clinical Memory OS + Supportive Care",
    },
    {
        "dimension_id": "longitudinal_trajectory",
        "label": "Trayectoria longitudinal",
        "required_fields": ["psa_series", "testosterone_series_if_applicable", "treatment_timeline"],
        "field_aliases": ["psa_series", "ape_series", "testosterone_series", "testosterone", "treatment_timeline", "treatment_line"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=longitudinal_trajectory",
        "persistence": "biomarker_longitudinal + treatment_lines + longitudinal_truth_snapshot",
        "consumer": "Clinical Memory OS + Patient Twin + Decision Today",
    },
    {
        "dimension_id": "toxicity_tolerance",
        "label": "Tolerancia y seguridad",
        "required_fields": ["toxicity_tolerance", "ctcae_or_pro_ctcae", "safety_priorities"],
        "field_aliases": ["toxicity_tolerance", "toxicity", "ctcae", "pro_ctcae", "safety_priorities", "falls", "cognition"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=toxicity_tolerance",
        "persistence": "patient_clinical_facts + PRO baseline + toxicity events",
        "consumer": "Care Pathway OS + Patient Twin + Tumor Board OS",
    },
    {
        "dimension_id": "redecision_threshold",
        "label": "Umbral de nueva decisión",
        "required_fields": ["redecision_threshold", "unacceptable_toxicity_threshold", "progression_threshold"],
        "field_aliases": ["redecision_threshold", "unacceptable_toxicity_threshold", "progression_threshold", "new_decision_threshold"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=redecision_threshold",
        "persistence": "patient_clinical_facts + patient_events",
        "consumer": "Decision Today + Clinical Memory OS + Autodrive",
    },
    {
        "dimension_id": "learning_consent",
        "label": "Consentimiento y trazabilidad para aprendizaje",
        "required_fields": ["learning_consent", "provenance_ready", "deidentification_ok"],
        "field_aliases": ["learning_consent", "consent", "provenance", "deidentification", "traceability"],
        "capture_surface": "/longitudinal-capture/<nss>?decision_lane=patient_twin_readiness&decision_field=learning_consent",
        "persistence": "consent + data_provenance",
        "consumer": "Clinical Memory OS + AI readiness dataset",
    },
)

AI_READINESS_DATASET_GATES = (
    {
        "gate_id": "consent_governance",
        "label": "Consentimiento y gobernanza de aprendizaje",
        "required_fields": ["learning_consent", "consent_version", "deidentification_ok", "retention_policy"],
        "field_aliases": ["learning_consent", "consent", "consent_version", "deidentification", "retention_policy"],
        "risk_if_missing": "No se puede usar el registro para entrenamiento futuro sin consentimiento y gobernanza trazable.",
    },
    {
        "gate_id": "provenance_traceability",
        "label": "Provenance y trazabilidad por feature",
        "required_fields": ["data_provenance", "source_document_hash", "capture_surface", "verification_status"],
        "field_aliases": ["provenance", "data_provenance", "source_document", "hash", "verification", "verified"],
        "risk_if_missing": "Evita features sin fuente, sin hash o sin superficie de captura verificable.",
    },
    {
        "gate_id": "outcome_maturity",
        "label": "Madurez de outcome observado",
        "required_fields": ["decision_episode_outcome", "outcome_timestamp", "followup_duration", "redecision_reason"],
        "field_aliases": ["outcome", "observed", "decision_episode", "followup", "redecision_reason", "progression"],
        "risk_if_missing": "Evita entrenar con desenlaces inmaduros o sin fecha clínica.",
    },
    {
        "gate_id": "sample_size_by_state",
        "label": "Tamaño muestral comparable por estado",
        "required_fields": ["clinical_state", "therapy_line", "treatment_exposure", "outcome_target"],
        "field_aliases": ["clinical_state", "state", "therapy_line", "treatment_line", "treatment", "outcome_target"],
        "risk_if_missing": "Evita conclusiones poblacionales con cohortes demasiado pequeñas o no comparables.",
    },
    {
        "gate_id": "missingness_profile",
        "label": "Perfil de missingness por feature crítica",
        "required_fields": ["missingness_map", "feature_completeness", "critical_field_completeness"],
        "field_aliases": ["missingness", "missing", "completeness", "critical_field"],
        "risk_if_missing": "Evita entrenar modelos sesgados por campos críticos ausentes.",
    },
    {
        "gate_id": "leakage_prevention",
        "label": "Prevención de leakage temporal",
        "required_fields": ["event_time_alignment", "feature_timestamp", "outcome_timestamp", "no_future_features"],
        "field_aliases": ["event_time", "feature_timestamp", "outcome_timestamp", "leakage", "future_feature"],
        "risk_if_missing": "Evita que el modelo aprenda datos posteriores a la decisión clínica.",
    },
    {
        "gate_id": "selection_bias_review",
        "label": "Revisión de sesgo de selección",
        "required_fields": ["age", "ecog", "clinical_state", "access_context", "treatment_exposure"],
        "field_aliases": ["age", "ecog", "clinical_state", "access", "treatment_exposure", "comorbidity"],
        "risk_if_missing": "Evita extrapolar a pacientes que no se parecen a la cohorte entrenable.",
    },
)

CORTANA_LOOP_COMMAND_REGISTRY = (
    {
        "command_id": "final_goal_gap",
        "label": "Qué falta para alcanzar el objetivo final",
        "phrases": ["que falta", "objetivo final", "alcanzar el objetivo", "camino al objetivo"],
        "response_key": "mission_gap_summary",
        "sources": ["mission_control", "gap_intelligence", "ai_readiness_dataset_loop"],
        "cta": "/loop-monitor#pm2MissionControl",
    },
    {
        "command_id": "dominant_clinical_gap",
        "label": "Qué brecha clínica bloquea más decisiones",
        "phrases": ["brecha clinica", "brecha clínica", "bloquea mas", "bloquea más", "bloqueo dominante"],
        "response_key": "dominant_gap",
        "sources": ["development_autodrive", "gap_intelligence", "decision_today"],
        "cta": "/loop-monitor#pm2DevelopmentAutodrive",
    },
    {
        "command_id": "today_improvement",
        "label": "Qué mejora toca hoy",
        "phrases": ["mejora toca hoy", "que sigue", "qué sigue", "siguiente fase", "proxima fase", "próxima fase"],
        "response_key": "next_improvement",
        "sources": ["development_autodrive", "cortana_loop_interface"],
        "cta": "/loop-monitor#pm2CortanaLoopInterface",
    },
    {
        "command_id": "pr_rationale",
        "label": "Por qué este PR mejora ProstaMed",
        "phrases": ["por que este pr", "por qué este pr", "mejora prostamed", "rationale", "implementacion"],
        "response_key": "implementation_rationale",
        "sources": ["implementation_brief", "shadow_patch_blueprint", "agent_consensus"],
        "cta": "/loop-monitor#pm2ImplementationBrief",
    },
    {
        "command_id": "evidence_support",
        "label": "Qué evidencia respalda este cambio",
        "phrases": ["evidencia respalda", "que evidencia", "qué evidencia", "fuentes", "guideline", "fda", "eau"],
        "response_key": "evidence_support",
        "sources": ["evidence_refresh_shadow_loop", "required_safety_gate_contract"],
        "cta": "/loop-monitor#pm2EvidenceRefreshShadowLoop",
    },
    {
        "command_id": "patient_twin_status",
        "label": "Estado de Patient Twin",
        "phrases": ["patient twin", "gemelo clinico", "gemelo clínico", "preferencias", "pros"],
        "response_key": "patient_twin_status",
        "sources": ["patient_twin_readiness_loop"],
        "cta": "/loop-monitor#pm2PatientTwinReadinessLoop",
    },
    {
        "command_id": "ai_readiness_status",
        "label": "Estado de IA entrenable",
        "phrases": ["ia entrenable", "dataset", "modelo", "entrenar", "learning", "ai readiness"],
        "response_key": "ai_readiness_status",
        "sources": ["ai_readiness_dataset_loop"],
        "cta": "/loop-monitor#pm2AiReadinessDatasetLoop",
    },
)

FORBIDDEN_FABRICATION_PATTERNS = (
    r"\binvent(ar|a|e|ado|ados)?\s+(psa|ape|testosterona|tratamiento|linea)",
    r"\bfabricat(e|ed|ing)\s+(psa|testosterone|therapy|treatment|line)",
    r"\bdemo\s+(psa|ape|testosterone|therapy|treatment|line)",
    r"\bfallback\s+(psa|ape|testosterone|therapy|treatment|line)",
)

CONTRACT_APPLICATION_TELEMETRY_CHECKS = {
    "diagnostic_truth_minimum": {
        "applied_phase": "diagnostic_truth_minimum",
        "readiness_lanes": ["diagnostic_biopsy_readiness", "diagnostic_truth_minimum"],
        "expected_readiness_fields": [
            "psa_density",
            "mri_pirads_score",
            "dre_suspicious",
            "biopsy_status",
            "family_history",
            "germline_risk",
            "phi_value",
            "fourkscore_value",
        ],
        "router_checks": [
            {
                "state": "diagnostic_workup",
                "phase": "initial_wizard",
                "readiness_lane": "diagnostic_truth_minimum",
                "expected_fields": [
                    "psa_density",
                    "mri_pirads_score",
                    "biopsy_status",
                    "family_history",
                    "germline_risk",
                    "phi_value",
                    "fourkscore_value",
                ],
            }
        ],
        "test_symbols": [
            "test_diagnostic_truth_minimum_requires_dominant_decision_fields",
            "test_diagnostic_truth_minimum_can_be_satisfied_by_legacy_aliases",
            "test_field_router_diagnostic_truth_minimum_is_compact_and_state_scoped",
            "test_fusion_routes_diagnostic_truth_gap_to_diagnostic_readiness",
            "test_wizard_form_uses_router_fields_when_readiness_lane_is_active",
        ],
        "evidence": [
            "Diagnostic readiness now requires the dominant fields blocking Decision Today.",
            "Clinical Field Router routes diagnostic truth fields to the diagnostic wizard without CRPC/PARP/RLT noise.",
            "Decision Today routes diagnostic missing fields to diagnostic_biopsy_readiness.",
        ],
    },
    "patient_twin_preference_pro_minimum": {
        "applied_phase": "8A_patient_twin_preference_pro_minimum",
        "readiness_lanes": ["patient_twin_readiness"],
        "expected_readiness_fields": [
            "patient_values",
            "baseline_pro",
            "toxicity_tolerance",
            "decision_tradeoff",
            "redecision_threshold",
        ],
        "router_checks": [
            {
                "state": "localized_initial",
                "phase": "longitudinal_followup",
                "readiness_lane": "patient_twin_readiness",
                "expected_fields": ["patient_values", "baseline_pro", "decision_tradeoff"],
            }
        ],
        "test_symbols": [
            "test_patient_twin_preference_pro_minimum_requires_values_pros_and_thresholds",
            "test_fusion_routes_patient_twin_preference_gap_to_patient_twin_readiness",
            "test_router_can_filter_patient_twin_preference_and_pro_fields",
        ],
        "evidence": [
            "Clinical Readiness lane patient_twin_readiness exposes preference/PRO fields.",
            "Clinical Field Router routes Patient Twin fields to longitudinal capture.",
            "Decision Today keeps preference-sensitive decisions requires_data until values/PROs exist.",
        ],
    },
    "localized_function_preference_minimum": {
        "applied_phase": "localized_function_preference_minimum",
        "readiness_lanes": ["localized_treatment_readiness", "localized_function_preference_minimum"],
        "expected_readiness_fields": [
            "localized_patient_values",
            "urinary_function_baseline",
            "sexual_function_baseline",
            "bowel_function_baseline",
            "rp_rt_as_tradeoff_documented",
        ],
        "router_checks": [
            {
                "state": "localized_initial",
                "phase": "initial_wizard",
                "readiness_lane": "localized_treatment_readiness",
                "expected_fields": [
                    "localized_patient_values",
                    "urinary_function_baseline",
                    "sexual_function_baseline",
                    "bowel_function_baseline",
                ],
            }
        ],
        "test_symbols": [
            "test_localized_function_preference_minimum_blocks_as_rp_rt_until_complete",
            "test_localized_function_preference_minimum_can_be_satisfied_by_preference_aliases",
            "test_fusion_routes_localized_function_preference_gap_to_localized_readiness",
        ],
        "evidence": [
            "Localized readiness lane requires function and patient values before AS/RP/RT release.",
            "Clinical Field Router exposes localized function/preference fields in the localized wizard.",
            "Decision Today routes localized preference gaps to localized_treatment_readiness.",
        ],
    },
    "bcr_salvage_window_minimum": {
        "applied_phase": "bcr_salvage_window_minimum",
        "readiness_lanes": ["bcr_salvage_readiness", "bcr_salvage_window_minimum"],
        "expected_readiness_fields": [
            "post_local_context",
            "psa_value",
            "psa_doubling_time_months",
            "salvage_context_marker",
            "surgical_margins_status",
            "pathological_t_stage",
            "psma_pet_status",
        ],
        "router_checks": [
            {
                "state": "recurrence_bcr",
                "phase": "initial_wizard",
                "readiness_lane": "bcr_salvage_window_minimum",
                "expected_fields": [
                    "psa_value",
                    "psa_doubling_time_months",
                    "prior_prostatectomy",
                    "prior_radiation",
                    "bcr_detected",
                    "bcr_date",
                    "bcr_psa",
                    "psma_pet_staging_recent",
                    "psa_nadir_post_rt",
                    "psa_rise_above_nadir_ng_ml",
                    "surgical_margins_status",
                    "pathological_t_stage",
                ],
            }
        ],
        "test_symbols": [
            "test_bcr_salvage_window_minimum_requires_psadt_and_context",
            "test_bcr_salvage_window_minimum_can_be_satisfied_by_legacy_aliases",
            "test_field_router_bcr_salvage_window_minimum_is_compact_and_excludes_crpc_domains",
            "test_fusion_routes_bcr_salvage_gap_to_bcr_readiness",
        ],
        "evidence": [
            "BCR readiness now exposes the salvage-window fields that block Decision Today.",
            "Clinical Field Router routes BCR salvage fields to the BCR wizard without CRPC/PARP/RLT activation.",
            "Decision Today routes BCR salvage missing fields to bcr_salvage_readiness.",
        ],
    },
}


@dataclass
class ImprovementCandidate:
    """Structured clinical improvement candidate emitted by the shadow loop."""

    id: str
    lane: str
    title: str
    description: str
    clinical_impact: int
    severity: int
    effort_h: float
    risk_avoided: str
    source: str
    evidence: list[str] = field(default_factory=list)
    tests_required: list[str] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)
    affected_states: list[str] = field(default_factory=list)
    patient_scope: dict[str, Any] = field(default_factory=dict)
    clinical_contract: dict[str, Any] = field(default_factory=dict)
    contract_gaps: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    agent_lane: str = "clinical_logic"
    rollback: str = ""
    status: str = "shadow"
    blockers: list[str] = field(default_factory=list)
    priority_score: float = 0.0
    created_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "lane": self.lane,
            "title": self.title,
            "description": self.description,
            "clinical_impact": self.clinical_impact,
            "severity": self.severity,
            "effort_h": self.effort_h,
            "risk_avoided": self.risk_avoided,
            "source": self.source,
            "evidence": list(self.evidence),
            "tests_required": list(self.tests_required),
            "surfaces": list(self.surfaces),
            "affected_states": list(self.affected_states),
            "patient_scope": dict(self.patient_scope),
            "clinical_contract": dict(self.clinical_contract),
            "contract_gaps": list(self.contract_gaps),
            "contradictions": list(self.contradictions),
            "agent_lane": self.agent_lane,
            "agent": AGENT_LANES.get(self.agent_lane, {}),
            "rollback": self.rollback,
            "status": self.status,
            "blockers": list(self.blockers),
            "priority_score": round(float(self.priority_score or 0.0), 2),
            "created_at": self.created_at,
        }
        return validate_candidate(payload)


def build_autonomous_improvement_bundle(*, patient_limit: int = 35) -> dict[str, Any]:
    """Build the complete shadow-mode improvement read model."""
    gaps = build_gap_intelligence(patient_limit=patient_limit)
    development = build_development_autodrive(gaps.get("candidates", []))
    mission = build_mission_control(gap_bundle=gaps, development_autodrive=development)
    proposals = build_proposals(gaps.get("candidates", []))
    shadow_pr = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety_gates = build_safety_gate_runner(shadow_pr_factory=shadow_pr)
    shadow_execution = build_shadow_execution_artifacts(safety_gate_runner=safety_gates)
    human_review = build_human_review_decision_gate(
        shadow_pr_factory=shadow_pr,
        shadow_execution_artifacts=shadow_execution,
    )
    draft_pr_handoff = build_draft_pr_handoff(
        human_review_decision_gate=human_review,
        shadow_pr_factory=shadow_pr,
        shadow_execution_artifacts=shadow_execution,
    )
    pr_review_monitor = build_pr_review_monitor(
        draft_pr_handoff=draft_pr_handoff,
        human_review_decision_gate=human_review,
        shadow_pr_factory=shadow_pr,
        shadow_execution_artifacts=shadow_execution,
    )
    agent_lane_registry = build_agent_lane_registry(
        gap_bundle=gaps,
        pr_review_monitor=pr_review_monitor,
    )
    agent_proposal_packets = build_agent_proposal_packets(
        agent_lane_registry=agent_lane_registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    agent_consensus_synthesizer = build_agent_consensus_synthesizer(
        agent_proposal_packets=agent_proposal_packets,
        development_autodrive=development,
    )
    implementation_brief = build_agent_implementation_brief(
        agent_consensus_synthesizer=agent_consensus_synthesizer,
    )
    shadow_patch_blueprint = build_shadow_patch_blueprint(
        implementation_brief=implementation_brief,
    )
    human_patch_authorization = build_human_patch_authorization(
        shadow_patch_blueprint=shadow_patch_blueprint,
    )
    controlled_patch_application = build_controlled_patch_application(
        shadow_patch_blueprint=shadow_patch_blueprint,
        human_patch_authorization=human_patch_authorization,
    )
    controlled_pr_implementation = build_controlled_pr_implementation(
        controlled_patch_application=controlled_patch_application,
    )
    draft_pr_publication_gate = build_draft_pr_publication_gate(
        controlled_pr_implementation=controlled_pr_implementation,
    )
    required_safety_gate_contract = build_required_safety_gate_contract(
        draft_pr_publication_gate=draft_pr_publication_gate,
    )
    evidence_refresh_shadow_loop = build_evidence_refresh_shadow_loop(
        required_safety_gate_contract=required_safety_gate_contract,
    )
    patient_twin_readiness_loop = build_patient_twin_readiness_loop(
        evidence_refresh_shadow_loop=evidence_refresh_shadow_loop,
        gap_bundle=gaps,
    )
    ai_readiness_dataset_loop = build_ai_readiness_dataset_loop(
        patient_twin_readiness_loop=patient_twin_readiness_loop,
        gap_bundle=gaps,
    )
    cortana_loop_interface = build_cortana_loop_interface(
        ai_readiness_dataset_loop=ai_readiness_dataset_loop,
        mission_control=mission,
        development_autodrive=development,
        gap_bundle=gaps,
        patient_twin_readiness_loop=patient_twin_readiness_loop,
        evidence_refresh_shadow_loop=evidence_refresh_shadow_loop,
    )
    continuous_shadow_operation = build_continuous_shadow_operation(
        cortana_loop_interface=cortana_loop_interface,
        mission_control=mission,
        development_autodrive=development,
        gap_bundle=gaps,
        proposals=proposals,
        shadow_pr_factory=shadow_pr,
        safety_gate_runner=safety_gates,
        shadow_execution_artifacts=shadow_execution,
        agent_consensus_synthesizer=agent_consensus_synthesizer,
        implementation_brief=implementation_brief,
        shadow_patch_blueprint=shadow_patch_blueprint,
        human_patch_authorization=human_patch_authorization,
        required_safety_gate_contract=required_safety_gate_contract,
    )
    return {
        "success": True,
        "source": "autonomous_improvement_os",
        "version": "autonomous_improvement_shadow_v1",
        "phase": "continuous_shadow_operation",
        "mission_control": mission,
        "gaps": gaps,
        "application_telemetry": gaps.get("application_telemetry", {}),
        "development_autodrive": development,
        "proposals": proposals,
        "shadow_pr_factory": shadow_pr,
        "safety_gate_runner": safety_gates,
        "shadow_execution_artifacts": shadow_execution,
        "human_review_decision_gate": human_review,
        "draft_pr_handoff": draft_pr_handoff,
        "pr_review_monitor": pr_review_monitor,
        "agent_lane_registry": agent_lane_registry,
        "agent_proposal_packets": agent_proposal_packets,
        "agent_consensus_synthesizer": agent_consensus_synthesizer,
        "implementation_brief": implementation_brief,
        "shadow_patch_blueprint": shadow_patch_blueprint,
        "human_patch_authorization": human_patch_authorization,
        "controlled_patch_application": controlled_patch_application,
        "controlled_pr_implementation": controlled_pr_implementation,
        "draft_pr_publication_gate": draft_pr_publication_gate,
        "required_safety_gate_contract": required_safety_gate_contract,
        "evidence_refresh_shadow_loop": evidence_refresh_shadow_loop,
        "patient_twin_readiness_loop": patient_twin_readiness_loop,
        "ai_readiness_dataset_loop": ai_readiness_dataset_loop,
        "cortana_loop_interface": cortana_loop_interface,
        "continuous_shadow_operation": continuous_shadow_operation,
        "summary": {
            "mode": mission.get("summary", {}).get("mode", "shadow"),
            "overall_pct": mission.get("summary", {}).get("overall_pct", 0),
            "candidate_count": len(gaps.get("candidates", [])),
            "software_gap_closed_count": (gaps.get("application_telemetry", {}).get("summary") or {}).get("software_gap_closed_count", 0),
            "patient_capture_monitoring_count": (gaps.get("application_telemetry", {}).get("summary") or {}).get("patient_capture_monitoring_count", 0),
            "top_candidate": (development.get("today_queue") or [{}])[0],
            "shadow_pr_ready": shadow_pr.get("summary", {}).get("ready_for_human_review", False),
            "safety_gates_status": safety_gates.get("summary", {}).get("release_gate", "blocked"),
            "shadow_execution_status": shadow_execution.get("summary", {}).get("artifact_status", "pending_execution"),
            "human_review_state": human_review.get("summary", {}).get("decision_state", "pending_human_review"),
            "draft_pr_handoff_status": draft_pr_handoff.get("summary", {}).get("handoff_status", "blocked_until_human_approval"),
            "pr_review_monitor_status": pr_review_monitor.get("summary", {}).get("monitor_status", "blocked_until_handoff_ready"),
            "agent_lane_registry_status": agent_lane_registry.get("summary", {}).get("registry_status", "shadow_active"),
            "agent_proposal_packets_status": agent_proposal_packets.get("summary", {}).get("packet_status", "shadow_packets_ready"),
            "agent_consensus_status": agent_consensus_synthesizer.get("summary", {}).get("consensus_status", "requires_data"),
            "implementation_brief_status": implementation_brief.get("summary", {}).get("brief_status", "blocked"),
            "shadow_patch_blueprint_status": shadow_patch_blueprint.get("summary", {}).get("blueprint_status", "blocked"),
            "human_patch_authorization_state": human_patch_authorization.get("summary", {}).get("authorization_state", "pending_human_authorization"),
            "controlled_patch_application_status": controlled_patch_application.get("summary", {}).get("application_status", "blocked_until_authorization"),
            "controlled_pr_implementation_status": controlled_pr_implementation.get("summary", {}).get("implementation_status", "blocked_until_4g_ready"),
            "draft_pr_publication_gate_status": draft_pr_publication_gate.get("summary", {}).get("publication_status", "blocked_until_5a_ready"),
            "required_safety_gate_contract_status": required_safety_gate_contract.get("summary", {}).get("safety_contract_status", "blocked_until_5b_ready"),
            "evidence_refresh_shadow_loop_status": evidence_refresh_shadow_loop.get("summary", {}).get("evidence_refresh_status", "blocked_until_6a_ready"),
            "patient_twin_readiness_loop_status": patient_twin_readiness_loop.get("summary", {}).get("patient_twin_readiness_status", "blocked_until_7a_ready"),
            "ai_readiness_dataset_loop_status": ai_readiness_dataset_loop.get("summary", {}).get("ai_readiness_status", "blocked_until_8a_ready"),
            "cortana_loop_interface_status": cortana_loop_interface.get("summary", {}).get("cortana_loop_status", "blocked_until_9a_ready"),
            "continuous_shadow_operation_status": continuous_shadow_operation.get("summary", {}).get("continuous_status", "blocked_until_10a_ready"),
            "source_clinical_facts_mutated": False,
            "auto_merge_enabled": mission.get("safety", {}).get("auto_merge_enabled", False),
        },
        "audit": _audit_footer(),
    }


def build_mission_control(
    *,
    gap_bundle: Mapping[str, Any] | None = None,
    development_autodrive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Official progress bar toward the ProstaMed longitudinal OS objective."""
    gap_bundle = dict(gap_bundle or build_gap_intelligence(patient_limit=20))
    development_autodrive = dict(development_autodrive or build_development_autodrive(gap_bundle.get("candidates", [])))
    metrics = _compute_goal_metrics(gap_bundle)
    overall = _weighted_overall(metrics)
    pipeline_progress = _autonomous_pipeline_progress()
    selected = dict((development_autodrive.get("summary") or {}).get("selected_improvement") or {})
    top = selected or (development_autodrive.get("today_queue") or [{}])[0]
    safety = _safety_controls()
    application_summary = dict((gap_bundle.get("application_telemetry") or {}).get("summary") or {})
    status = "blocked" if safety.get("kill_switch_active") else "shadow"
    if top.get("status") == "human_review_required":
        status = "human_review_required"

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "mission_control_v1",
        "goal_registry": GOAL_REGISTRY,
        "summary": {
            "overall_pct": overall,
            "clinical_goal_pct": overall,
            "pipeline_maturity_pct": pipeline_progress["pct"],
            "pipeline_completed_count": pipeline_progress["implemented_count"],
            "pipeline_total_count": pipeline_progress["total_count"],
            "status": status,
            "mode": "shadow",
            "top_gap_id": top.get("id", ""),
            "top_gap_title": top.get("title", "No active candidate"),
            "top_lane": top.get("lane", ""),
            "candidate_count": len(gap_bundle.get("candidates", [])),
            "validated_count": sum(1 for c in gap_bundle.get("candidates", []) if c.get("status") == "validated"),
            "blocked_count": sum(1 for c in gap_bundle.get("candidates", []) if c.get("status") == "blocked"),
            "human_review_required_count": sum(
                1 for c in gap_bundle.get("candidates", []) if c.get("status") == "human_review_required"
            ),
            "software_gap_closed_count": int(application_summary.get("software_gap_closed_count") or 0),
            "implemented_contract_count": int(application_summary.get("implemented_contract_count") or 0),
            "patient_capture_monitoring_count": int(application_summary.get("patient_capture_monitoring_count") or 0),
        },
        "metrics": metrics,
        "progress_diagnostics": _mission_progress_diagnostics(metrics, gap_bundle, pipeline_progress),
        "pipeline_progress": pipeline_progress,
        "safety": safety,
        "agent_lanes": AGENT_LANES,
        "interfaces": [
            "/api/autonomous-improvement/mission-control",
            "/api/autonomous-improvement/gaps",
            "/api/autonomous-improvement/proposals",
            "/api/autonomous-improvement/agent-proposal-packets",
            "/api/autonomous-improvement/agent-consensus-synthesizer",
            "/api/autonomous-improvement/implementation-brief",
            "/api/autonomous-improvement/shadow-patch-blueprint",
            "/api/autonomous-improvement/human-patch-authorization",
            "/api/autonomous-improvement/controlled-patch-application",
            "/api/autonomous-improvement/controlled-pr-implementation",
            "/api/autonomous-improvement/draft-pr-publication-gate",
            "/api/autonomous-improvement/required-safety-gate-contract",
            "/api/autonomous-improvement/evidence-refresh-shadow-loop",
            "/api/autonomous-improvement/patient-twin-readiness-loop",
            "/api/autonomous-improvement/ai-readiness-dataset-loop",
            "/api/autonomous-improvement/cortana-loop-interface",
            "/api/autonomous-improvement/recompute",
            "/api/loop-monitor/snapshot",
        ],
        "audit": _audit_footer(),
    }


def build_gap_intelligence(*, patient_limit: int = 35) -> dict[str, Any]:
    """Detect clinical, data, evidence, UI, security and regulatory gaps."""
    context = _build_context(patient_limit=patient_limit)
    candidates: list[dict[str, Any]] = []
    candidates.extend(_patient_twin_candidates(context))
    candidates.extend(_contractual_clinical_candidates(context))
    candidates.extend(_contradiction_candidates(context))
    candidates.extend(_decision_today_candidates(context))
    candidates.extend(_contract_candidates(context))
    candidates.extend(_compliance_candidates(context))
    candidates.extend(_loop_monitor_candidates(context))
    candidates.extend(_security_candidates(context))
    # EPIC 18: surface external evidence deltas detected by weekly refresh.
    candidates.extend(_evidence_delta_candidates(context))
    candidates = _dedupe_candidates(candidates)
    candidates = rank_candidates(candidates)
    reviews = load_proposal_reviews()
    candidates = [_apply_review(c, reviews) for c in candidates]

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "gap_intelligence_v1",
        "phase": "2B_contradiction_intelligence",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "clinical_gap_contracts": build_clinical_gap_contract_registry(),
        "application_telemetry": context.get("application_telemetry", {}),
        "contractual_gap_rows": context.get("contractual_gap_rows", []),
        "contradiction_rules": build_contradiction_rule_registry(),
        "contradiction_rows": context.get("contradiction_rows", []),
        "critical": [c for c in candidates if c.get("lane") == "critical_clinical_gap"][:12],
        "data_integrity": [c for c in candidates if c.get("lane") == "data_integrity_gap"][:12],
        "evidence": [c for c in candidates if c.get("lane") == "evidence_gap"][:12],
        "security": [c for c in candidates if c.get("lane") == "safety_security_gap"][:12],
        "ui": [c for c in candidates if c.get("lane") == "ui_workflow_gap"][:12],
        "regulatory": [c for c in candidates if c.get("lane") == "regulatory_traceability_gap"][:12],
        "context": _public_context(context),
        "audit": _audit_footer(),
    }


def build_development_autodrive(candidates: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Prioritize one safe improvement at a time."""
    ranked = rank_candidates(candidates or [])
    lanes: dict[str, list[dict[str, Any]]] = {lane: [] for lane in DEVELOPMENT_LANES}
    for candidate in ranked:
        lane = str(candidate.get("lane") or "")
        if lane in lanes:
            lanes[lane].append(candidate)
    actionable = [candidate for candidate in ranked if _candidate_actionable(candidate)]
    deferred = [candidate for candidate in ranked if not _candidate_actionable(candidate)]
    top = actionable[0] if actionable else {}
    scoring_transparency = _build_scoring_transparency(ranked, actionable, top)
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "development_autodrive_v2",
        "phase": "3A_development_autodrive",
        "summary": {
            "candidate_count": len(ranked),
            "actionable_count": len(actionable),
            "deferred_count": len(deferred),
            "selected_improvement": top,
            "selected_id": top.get("id", ""),
            "selected_reason": _selected_reason(top),
            "one_change_per_iteration": True,
            "mode": "shadow",
            "next_phase_suggested": "3B_shadow_pr_factory",
            "clinical_candidate_count": scoring_transparency["clinical_candidate_count"],
            "clinical_candidates_open": scoring_transparency["clinical_candidates_open"],
            "critical_clinical_below_nonclinical": scoring_transparency["critical_clinical_below_nonclinical"],
        },
        "scoring_transparency": scoring_transparency,
        "priority_factors": list(DEVELOPMENT_PRIORITIZATION_FACTORS),
        "selection_guardrails": {
            "shadow_mode_only": True,
            "one_change_per_iteration": True,
            "clinical_fact_writes_allowed": False,
            "auto_merge_allowed": False,
            "requires_evidence": True,
            "requires_tests": True,
            "requires_rollback": True,
            "blocked_candidates_never_selected": True,
        },
        "selected_iteration": _selected_iteration_plan(top),
        "today_queue": ranked[:12],
        "actionable_queue": actionable[:12],
        "deferred_queue": deferred[:12],
        "lanes": lanes,
        "critical_clinical_gap": lanes["critical_clinical_gap"],
        "data_integrity_gap": lanes["data_integrity_gap"],
        "evidence_gap": lanes["evidence_gap"],
        "safety_security_gap": lanes["safety_security_gap"],
        "ui_workflow_gap": lanes["ui_workflow_gap"],
        "regulatory_traceability_gap": lanes["regulatory_traceability_gap"],
        "audit": _audit_footer(),
    }


def _build_scoring_transparency(
    ranked: Iterable[Mapping[str, Any]],
    actionable: Iterable[Mapping[str, Any]],
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    ranked_list = [dict(item) for item in ranked or []]
    actionable_list = [dict(item) for item in actionable or []]
    clinical_ranked = [item for item in ranked_list if _candidate_is_clinical_priority(item)]
    clinical_actionable = [item for item in actionable_list if _candidate_is_clinical_priority(item)]
    selected_is_clinical = bool(selected) and _candidate_is_clinical_priority(selected)
    critical_below_nonclinical = bool(
        selected
        and not selected_is_clinical
        and any(str(item.get("lane") or "") == "critical_clinical_gap" for item in clinical_actionable)
    )
    alerts: list[str] = []
    if not clinical_actionable:
        alerts.append("no_open_clinical_candidates")
    if critical_below_nonclinical:
        alerts.append("critical_clinical_candidate_ranked_below_nonclinical")
    return {
        "available": True,
        "version": "scoring_transparency_v1",
        "score_formula": "priority_score = raw_score / effort_divisor * blocker_penalty",
        "effort_policy": "Effort is capped so it guides execution fit without burying clinical priority.",
        "selected_candidate": _candidate_score_card(selected),
        "top_clinical_candidate": _candidate_score_card(clinical_actionable[0] if clinical_actionable else {}),
        "clinical_candidate_count": len(clinical_ranked),
        "clinical_candidates_open": len(clinical_actionable),
        "critical_clinical_below_nonclinical": critical_below_nonclinical,
        "alerts": alerts,
        "top_queue": [_candidate_score_card(item) for item in ranked_list[:5]],
    }


def build_proposals(candidates: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Convert candidates into structured shadow proposals."""
    proposals = []
    for candidate in rank_candidates(candidates or []):
        proposals.append({
            "id": candidate.get("id"),
            "status": candidate.get("status", "shadow"),
            "lane": candidate.get("lane"),
            "title": candidate.get("title"),
            "hypothesis": candidate.get("description"),
            "minimal_change": _minimal_change_for(candidate),
            "risks": _risks_for(candidate),
            "tests_required": candidate.get("tests_required", []),
            "rollback": candidate.get("rollback") or "Revert the small PR or disable this candidate via review log.",
            "acceptance": _acceptance_for(candidate),
            "evidence": candidate.get("evidence", []),
            "clinical_contract": candidate.get("clinical_contract", {}),
            "contract_gaps": candidate.get("contract_gaps", []),
            "contradictions": candidate.get("contradictions", []),
            "development_priority": {
                "priority_score": candidate.get("priority_score", 0),
                "priority_class": candidate.get("priority_class", "not_scored"),
                "score_breakdown": candidate.get("score_breakdown", {}),
            },
            "human_review_required": candidate.get("status") in {"human_review_required", "validated"},
            "shadow_mode_only": True,
        })
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "proposal_factory_v1",
        "proposals": proposals,
        "n": len(proposals),
        "review_log": list(load_proposal_reviews().values()),
        "audit": _audit_footer(),
    }


def build_shadow_pr_factory(
    *,
    development_autodrive: Mapping[str, Any] | None = None,
    proposals: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a draft PR package for the selected improvement without touching git."""
    development = dict(development_autodrive or build_development_autodrive([]))
    selected = dict((development.get("summary") or {}).get("selected_improvement") or {})
    selected_id = str(selected.get("id") or "")
    proposal_rows = list((proposals or {}).get("proposals") or [])
    proposal = next((dict(row) for row in proposal_rows if str(row.get("id") or "") == selected_id), {})
    if not proposal and selected:
        proposal = {
            "id": selected_id,
            "title": selected.get("title", ""),
            "hypothesis": selected.get("description", ""),
            "minimal_change": _minimal_change_for(selected),
            "tests_required": selected.get("tests_required", []),
            "rollback": selected.get("rollback", ""),
            "acceptance": _acceptance_for(selected),
            "evidence": selected.get("evidence", []),
            "clinical_contract": selected.get("clinical_contract", {}),
            "contract_gaps": selected.get("contract_gaps", []),
            "contradictions": selected.get("contradictions", []),
        }

    if not selected:
        return {
            "available": False,
            "source": "autonomous_improvement_os",
            "version": "shadow_pr_factory_v1",
            "phase": "3B_shadow_pr_factory",
            "summary": {
                "mode": "shadow",
                "ready_for_human_review": False,
                "reason": "No actionable Development Autodrive candidate was selected.",
                "next_phase_suggested": "3C_safety_gate_runner",
            },
            "audit": _audit_footer(),
        }

    package = _build_shadow_pr_package(selected, proposal, development)
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "shadow_pr_factory_v1",
        "phase": "3B_shadow_pr_factory",
        "summary": {
            "mode": "shadow",
            "selected_id": selected_id,
            "title": package.get("draft_pr", {}).get("title", ""),
            "branch_name": package.get("draft_pr", {}).get("branch_name", ""),
            "ready_for_human_review": package.get("safety_report", {}).get("release_gate") == "ready_for_human_review",
            "auto_merge_allowed": False,
            "source_clinical_facts_mutated": False,
            "next_phase_suggested": "3C_safety_gate_runner",
        },
        "package": package,
        "audit": _audit_footer(),
    }


def build_safety_gate_runner(*, shadow_pr_factory: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate the selected shadow PR package against clinical safety gates.

    Phase 3C is deliberately plan-only: it reports required commands and visual
    routes but does not execute shell commands, mutate git, or change clinical
    facts.
    """
    shadow = dict(shadow_pr_factory or build_shadow_pr_factory())
    package = dict(shadow.get("package") or {})
    gates = _build_safety_gate_rows(shadow, package)
    counts = Counter(str(gate.get("status") or "blocked") for gate in gates)
    blocked = counts.get("blocked", 0)
    release_gate = "ready_for_human_review" if package and blocked == 0 else "blocked"
    test_commands = list((package.get("validation_plan") or {}).get("test_commands") or [])
    visual_routes = list((package.get("validation_plan") or {}).get("visual_validation") or [])
    return {
        "available": bool(package),
        "source": "autonomous_improvement_os",
        "version": "safety_gate_runner_v1",
        "phase": "3C_safety_gate_runner",
        "summary": {
            "mode": "shadow",
            "executor_mode": "plan_only_v1",
            "release_gate": release_gate,
            "passed": counts.get("passed", 0),
            "blocked": blocked,
            "requires_human_review": counts.get("requires_human_review", 0),
            "gate_count": len(gates),
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "commands_executed": False,
            "next_phase_suggested": "3D_shadow_execution_artifacts",
        },
        "gates": gates,
        "required_test_commands": test_commands,
        "required_visual_routes": visual_routes,
        "anti_fallback": {
            "no_fabricated_psa": _safety_bool(package, "no_fabricated_psa"),
            "no_fabricated_testosterone": _safety_bool(package, "no_fabricated_testosterone"),
            "no_fabricated_treatments": _safety_bool(package, "no_fabricated_treatments"),
            "no_fabricated_trial_eligibility": _safety_bool(package, "no_fabricated_trial_eligibility"),
        },
        "audit": _audit_footer(),
    }


def build_shadow_execution_artifacts(
    *,
    safety_gate_runner: Mapping[str, Any] | None = None,
    command_results: Iterable[Mapping[str, Any]] | None = None,
    visual_results: Iterable[Mapping[str, Any]] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Build or record Phase 3D execution evidence without exposing a shell runner.

    The web surface is read-only. Actual command execution must happen in the
    controlled local developer workflow; this function only validates and stores
    sanitized result metadata.
    """
    safety = dict(safety_gate_runner or build_safety_gate_runner())
    fingerprint = _shadow_execution_fingerprint(safety)
    latest = _load_latest_shadow_execution_artifact(fingerprint)
    if latest and command_results is None and visual_results is None:
        return latest

    planned_commands = list(safety.get("required_test_commands") or [])
    planned_visual_routes = list(safety.get("required_visual_routes") or [])
    normalized_results = [_normalize_command_result(row) for row in (command_results or [])]
    normalized_visuals = [_normalize_visual_result(row) for row in (visual_results or [])]
    planned_cmds = [str(row.get("cmd") or "") for row in planned_commands if row.get("cmd")]
    result_cmds = {str(row.get("cmd") or "") for row in normalized_results if row.get("cmd")}
    missing_cmds = [cmd for cmd in planned_cmds if cmd not in result_cmds]
    unsafe_cmds = [
        row for row in normalized_results
        if not _shadow_command_allowed(str(row.get("cmd") or ""))
    ]
    failed_cmds = [row for row in normalized_results if int(row.get("exit_code") or 0) != 0]
    visual_routes_seen = {str(row.get("route") or "") for row in normalized_visuals if row.get("route")}
    missing_visuals = [route for route in planned_visual_routes if route not in visual_routes_seen]
    commands_executed = bool(normalized_results)

    artifact_status = "pending_execution"
    if unsafe_cmds or safety.get("summary", {}).get("release_gate") != "ready_for_human_review":
        artifact_status = "blocked"
    elif commands_executed and failed_cmds:
        artifact_status = "failed"
    elif commands_executed and missing_cmds:
        artifact_status = "partial_execution"
    elif commands_executed and missing_visuals:
        artifact_status = "requires_visual_validation"
    elif commands_executed:
        artifact_status = "verified_pending_human_review"

    artifact = {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "shadow_execution_artifacts_v1",
        "phase": "3D_shadow_execution_artifacts",
        "summary": {
            "mode": "shadow",
            "execution_mode": "local_controlled_artifacts",
            "artifact_status": artifact_status,
            "release_gate": "ready_for_human_review" if artifact_status == "verified_pending_human_review" else "blocked",
            "commands_executed": commands_executed,
            "planned_command_count": len(planned_cmds),
            "executed_command_count": len(normalized_results),
            "passed_command_count": sum(1 for row in normalized_results if int(row.get("exit_code") or 0) == 0),
            "failed_command_count": len(failed_cmds),
            "missing_command_count": len(missing_cmds),
            "visual_route_count": len(planned_visual_routes),
            "validated_visual_count": len(normalized_visuals),
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "auto_merge_allowed": False,
            "clinical_release_allowed": False,
            "human_review_required": True,
            "next_phase_suggested": "3E_human_review_decision_gate",
        },
        "execution_plan": {
            "commands": planned_commands,
            "visual_routes": planned_visual_routes,
            "allowlist": list(SHADOW_COMMAND_ALLOWLIST),
        },
        "command_results": normalized_results,
        "visual_results": normalized_visuals,
        "blocking_findings": _shadow_execution_blocking_findings(
            unsafe_cmds=unsafe_cmds,
            failed_cmds=failed_cmds,
            missing_cmds=missing_cmds,
            missing_visuals=missing_visuals,
            safety=safety,
            commands_executed=commands_executed,
        ),
        "artifact_controls": {
            "raw_phi_allowed": False,
            "raw_audio_allowed": False,
            "raw_transcript_allowed": False,
            "stdout_sanitized": True,
            "retention": "metadata_only_until_human_review",
            "source_safety_fingerprint": fingerprint,
        },
        "audit": {
            **_audit_footer(),
            "source_safety_fingerprint": fingerprint,
            "persisted": False,
            "artifact_path": "",
        },
    }
    if persist:
        artifact = _persist_shadow_execution_artifact(artifact)
    return artifact


def build_human_review_decision_gate(
    *,
    shadow_pr_factory: Mapping[str, Any] | None = None,
    shadow_execution_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 3E: explicit human decision over the verified shadow artifact."""
    shadow = dict(shadow_pr_factory or build_shadow_pr_factory())
    package = dict(shadow.get("package") or {})
    execution = dict(shadow_execution_artifacts or build_shadow_execution_artifacts())
    execution_summary = dict(execution.get("summary") or {})
    artifact_controls = dict(execution.get("artifact_controls") or {})
    fingerprint = str(artifact_controls.get("source_safety_fingerprint") or "")
    latest = _load_latest_human_review_gate_decision(fingerprint)
    artifact_verified = execution_summary.get("artifact_status") == "verified_pending_human_review"
    decision = str(latest.get("decision") or "hold")

    if not artifact_verified:
        decision_state = "blocked_until_artifact_verified"
        release_gate = "blocked"
        next_phase = "3D_shadow_execution_artifacts"
    elif latest.get("decision") == "approve_for_pr":
        decision_state = "approved_for_pr_handoff"
        release_gate = "approved_for_draft_pr_handoff"
        next_phase = "3F_draft_pr_handoff"
    elif latest.get("decision") == "request_changes":
        decision_state = "changes_requested"
        release_gate = "blocked"
        next_phase = "3B_shadow_pr_factory"
    elif latest.get("decision") == "reject":
        decision_state = "rejected"
        release_gate = "blocked"
        next_phase = "3A_development_autodrive"
    else:
        decision_state = "pending_human_review"
        release_gate = "human_review_required" if artifact_verified else "blocked"
        next_phase = "3E_human_review_decision_gate"

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "human_review_decision_gate_v1",
        "phase": "3E_human_review_decision_gate",
        "summary": {
            "mode": "shadow",
            "decision_state": decision_state,
            "decision": decision,
            "release_gate": release_gate,
            "artifact_verified": artifact_verified,
            "human_review_required": decision_state == "pending_human_review",
            "pr_handoff_allowed": decision_state == "approved_for_pr_handoff",
            "pull_request_created": False,
            "branch_created": False,
            "auto_merge_allowed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "next_phase_suggested": next_phase,
        },
        "allowed_decisions": _allowed_human_review_decisions(artifact_verified),
        "candidate": dict(package.get("candidate") or {}),
        "draft_pr": {
            "title": (package.get("draft_pr") or {}).get("title", ""),
            "branch_name": (package.get("draft_pr") or {}).get("branch_name", ""),
            "is_draft": (package.get("draft_pr") or {}).get("is_draft", True),
        },
        "artifact": {
            "status": execution_summary.get("artifact_status", "pending_execution"),
            "artifact_path": (execution.get("audit") or {}).get("artifact_path", ""),
            "source_safety_fingerprint": fingerprint,
            "executed_command_count": execution_summary.get("executed_command_count", 0),
            "failed_command_count": execution_summary.get("failed_command_count", 0),
            "validated_visual_count": execution_summary.get("validated_visual_count", 0),
        },
        "latest_decision": latest,
        "controls": {
            "requires_verified_artifact": True,
            "requires_human_reviewer": True,
            "records_audit_only": True,
            "creates_pr": False,
            "creates_branch": False,
            "auto_merge_allowed": False,
            "clinical_fact_writes_allowed": False,
        },
        "audit": _audit_footer(),
    }


def build_draft_pr_handoff(
    *,
    human_review_decision_gate: Mapping[str, Any] | None = None,
    shadow_pr_factory: Mapping[str, Any] | None = None,
    shadow_execution_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 3F: manual draft-PR handoff package, without touching git."""
    shadow = dict(shadow_pr_factory or build_shadow_pr_factory())
    package = dict(shadow.get("package") or {})
    execution = dict(shadow_execution_artifacts or build_shadow_execution_artifacts())
    human_review = dict(
        human_review_decision_gate
        or build_human_review_decision_gate(
            shadow_pr_factory=shadow,
            shadow_execution_artifacts=execution,
        )
    )
    execution_summary = dict(execution.get("summary") or {})
    human_summary = dict(human_review.get("summary") or {})
    draft = dict(package.get("draft_pr") or {})
    candidate = dict(package.get("candidate") or {})
    branch_name = _redact_phi_like(str(draft.get("branch_name") or "codex/autodrive-pending"))
    artifact_verified = execution_summary.get("artifact_status") == "verified_pending_human_review"
    human_approved = human_summary.get("decision_state") == "approved_for_pr_handoff"

    if not package:
        handoff_status = "blocked_no_shadow_package"
        next_phase = "3B_shadow_pr_factory"
    elif not artifact_verified:
        handoff_status = "blocked_until_artifact_verified"
        next_phase = "3D_shadow_execution_artifacts"
    elif not human_approved:
        handoff_status = "blocked_until_human_approval"
        next_phase = "3E_human_review_decision_gate"
    else:
        handoff_status = "ready_for_manual_pr_creation"
        next_phase = "3G_pr_review_monitor"

    manual_handoff_ready = handoff_status == "ready_for_manual_pr_creation"
    files_to_stage = _draft_pr_handoff_files(package)
    commands_to_run = _draft_pr_handoff_commands(
        package=package,
        branch_name=branch_name,
        manual_handoff_ready=manual_handoff_ready,
        handoff_status=handoff_status,
    )

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "draft_pr_handoff_v1",
        "phase": "3F_draft_pr_handoff",
        "summary": {
            "mode": "shadow",
            "handoff_status": handoff_status,
            "manual_handoff_ready": manual_handoff_ready,
            "artifact_verified": artifact_verified,
            "human_approved": human_approved,
            "files_to_stage_count": len(files_to_stage),
            "planned_command_count": len(commands_to_run),
            "branch_created": False,
            "pull_request_created": False,
            "auto_merge_allowed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "next_phase_suggested": next_phase,
        },
        "candidate": candidate,
        "branch_plan": {
            "branch_name": branch_name,
            "base_branch": _redact_phi_like(str(draft.get("base_branch") or "main")),
            "branch_prefix_required": "codex/",
            "create_branch_now": False,
            "manual_only": True,
        },
        "pr_plan": {
            "title": _redact_phi_like(str(draft.get("title") or candidate.get("title") or "")),
            "is_draft": bool(draft.get("is_draft", True)),
            "labels": list(draft.get("labels") or SHADOW_PR_LABELS),
            "body_source": "shadow_pr_factory.package.draft_pr.body",
            "review_required": True,
            "auto_merge_allowed": False,
        },
        "files_to_stage": files_to_stage,
        "commands_to_run": commands_to_run,
        "review_checklist": _draft_pr_handoff_review_checklist(
            artifact_verified=artifact_verified,
            human_approved=human_approved,
            manual_handoff_ready=manual_handoff_ready,
        ),
        "artifact_refs": {
            "shadow_execution_artifact_path": _redact_phi_like(
                str((execution.get("audit") or {}).get("artifact_path") or "")
            ),
            "source_safety_fingerprint": _redact_phi_like(
                str(((execution.get("artifact_controls") or {}).get("source_safety_fingerprint")) or "")
            ),
            "executed_command_count": execution_summary.get("executed_command_count", 0),
            "failed_command_count": execution_summary.get("failed_command_count", 0),
            "validated_visual_count": execution_summary.get("validated_visual_count", 0),
        },
        "blocking_findings": _draft_pr_handoff_blockers(
            handoff_status=handoff_status,
            artifact_verified=artifact_verified,
            human_approved=human_approved,
        ),
        "controls": {
            "records_plan_only": True,
            "requires_verified_artifact": True,
            "requires_human_approval": True,
            "creates_branch": False,
            "creates_pr": False,
            "runs_git_commands": False,
            "auto_merge_allowed": False,
            "clinical_fact_writes_allowed": False,
        },
        "audit": _audit_footer(),
    }


def build_pr_review_monitor(
    *,
    draft_pr_handoff: Mapping[str, Any] | None = None,
    human_review_decision_gate: Mapping[str, Any] | None = None,
    shadow_pr_factory: Mapping[str, Any] | None = None,
    shadow_execution_artifacts: Mapping[str, Any] | None = None,
    git_snapshot: Mapping[str, Any] | None = None,
    pr_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 3G: monitor an existing draft PR without creating or merging it."""
    handoff = dict(
        draft_pr_handoff
        or build_draft_pr_handoff(
            human_review_decision_gate=human_review_decision_gate,
            shadow_pr_factory=shadow_pr_factory,
            shadow_execution_artifacts=shadow_execution_artifacts,
        )
    )
    handoff_summary = dict(handoff.get("summary") or {})
    branch_plan = dict(handoff.get("branch_plan") or {})
    branch_name = _redact_phi_like(str(branch_plan.get("branch_name") or ""))
    local_git = dict(git_snapshot or _build_local_git_snapshot(branch_name=branch_name))
    metadata = dict(pr_metadata or _load_latest_pr_review_metadata(branch_name))

    handoff_ready = handoff_summary.get("manual_handoff_ready") is True
    branch_present = bool(local_git.get("branch_present") or local_git.get("current_branch") == branch_name)
    pull_request_detected = bool(metadata.get("pr_url") or metadata.get("pr_number"))
    ci_status = _normalize_pr_review_choice(metadata.get("ci_status"), PR_REVIEW_CI_STATUSES, "unknown")
    review_status = _normalize_pr_review_choice(
        metadata.get("review_status"),
        PR_REVIEW_REVIEW_STATUSES,
        "pending",
    )

    if not handoff_ready:
        monitor_status = "blocked_until_handoff_ready"
        next_phase = handoff_summary.get("next_phase_suggested", "3E_human_review_decision_gate")
    elif not pull_request_detected and branch_present:
        monitor_status = "branch_ready_no_pr"
        next_phase = "3F_manual_pr_creation"
    elif not pull_request_detected:
        monitor_status = "no_pr_yet"
        next_phase = "3F_manual_pr_creation"
    elif ci_status in {"pending", "running", "unknown"}:
        monitor_status = "ci_running" if ci_status in {"pending", "running"} else "pr_open"
        next_phase = "3G_pr_review_monitor"
    elif ci_status in {"failed", "cancelled"} or review_status == "blocked":
        monitor_status = "blocked"
        next_phase = "3G_pr_review_monitor"
    elif review_status == "changes_requested":
        monitor_status = "changes_requested"
        next_phase = "3B_shadow_pr_factory"
    elif ci_status == "passed" and review_status == "approved":
        monitor_status = "validated_pending_human_merge"
        next_phase = "4A_agent_lane_registry"
    else:
        monitor_status = "pr_open"
        next_phase = "3G_pr_review_monitor"

    merge_blockers = _pr_review_monitor_blockers(
        monitor_status=monitor_status,
        handoff_ready=handoff_ready,
        pull_request_detected=pull_request_detected,
        branch_present=branch_present,
        ci_status=ci_status,
        review_status=review_status,
    )
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "pr_review_monitor_v1",
        "phase": "3G_pr_review_monitor",
        "summary": {
            "mode": "shadow",
            "monitor_status": monitor_status,
            "handoff_ready": handoff_ready,
            "branch_present": branch_present,
            "pull_request_detected": pull_request_detected,
            "pull_request_created_by_monitor": False,
            "ci_status": ci_status,
            "review_status": review_status,
            "merge_blocker_count": len(merge_blockers),
            "validated_pending_human_merge": monitor_status == "validated_pending_human_merge",
            "merge_performed": False,
            "branch_created": False,
            "pull_request_created": False,
            "auto_merge_allowed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "next_phase_suggested": next_phase,
        },
        "pr_status": {
            "status": monitor_status,
            "branch_name": branch_name,
            "pr_number": _redact_phi_like(str(metadata.get("pr_number") or "")),
            "pr_url": _redact_phi_like(str(metadata.get("pr_url") or "")),
            "source": "local_review_metadata" if pull_request_detected else "not_detected",
            "detected_only": pull_request_detected,
            "created_by_monitor": False,
        },
        "ci_status": {
            "status": ci_status,
            "passed": ci_status == "passed",
            "required": True,
            "source": "local_review_metadata" if metadata else "not_connected",
        },
        "review_status": {
            "status": review_status,
            "approved": review_status == "approved",
            "required": True,
            "source": "local_review_metadata" if metadata else "not_connected",
        },
        "local_git": local_git,
        "handoff_summary": handoff_summary,
        "review_findings": _pr_review_monitor_findings(
            local_git=local_git,
            metadata=metadata,
            monitor_status=monitor_status,
        ),
        "merge_blockers": merge_blockers,
        "clinical_safety_delta": {
            "no_new_clinical_logic_since_handoff": True,
            "requires_re_run_safety_gates_if_diff_changes": True,
            "anti_fallback_checks_required": [
                "no fabricated PSA/APE",
                "no fabricated testosterone",
                "no invented treatment lines",
                "no eligible trials with empty payload",
                "no PHI in logs or artifacts",
            ],
            "source_clinical_facts_mutated": False,
        },
        "required_actions": _pr_review_monitor_required_actions(
            monitor_status=monitor_status,
            branch_name=branch_name,
        ),
        "rollback_plan": [
            "Cerrar o abandonar el PR draft si falla CI o revisión clínica.",
            "Eliminar rama local sólo con autorización explícita del usuario.",
            "Registrar rechazo en Fase 3E si la propuesta deja de ser segura.",
        ],
        "controls": {
            "records_monitor_only": True,
            "creates_branch": False,
            "creates_pr": False,
            "runs_git_commands": False,
            "runs_gh_commands": False,
            "merges_pr": False,
            "auto_merge_allowed": False,
            "clinical_fact_writes_allowed": False,
        },
        "latest_metadata": metadata,
        "audit": _audit_footer(),
    }


def build_agent_lane_registry(
    *,
    gap_bundle: Mapping[str, Any] | None = None,
    pr_review_monitor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4A: official registry for specialized proposal agents."""
    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=35))
    candidates = [dict(row) for row in gaps.get("candidates") or []]
    assignments = Counter(str(row.get("agent_lane") or _agent_lane_for_development_lane(row.get("lane"))) for row in candidates)
    lanes = []
    for key, meta in AGENT_LANES.items():
        lane = {
            "agent_lane": key,
            "label": meta.get("label", key),
            "scope": meta.get("scope", ""),
            "may_modify": False,
            "mode": "shadow_proposal_only",
            "candidate_count": int(assignments.get(key, 0)),
            "allowed_outputs": [
                "clinical_improvement_candidate_review",
                "agent_proposal_packet",
                "risk_note",
                "test_plan",
                "rollback_plan",
                "evidence_gap_note",
            ],
            "forbidden_actions": [
                "modify_production_code_directly",
                "write_clinical_facts",
                "store_phi_in_logs_or_artifacts",
                "create_or_merge_pr",
                "prescribe_or_execute_external_orders",
                "train_or_release_autonomous_ml",
            ],
            "required_packet_fields": list(_agent_packet_required_fields()),
            "quality_gates": _agent_lane_quality_gates(key),
        }
        lanes.append(lane)

    monitor_summary = dict((pr_review_monitor or {}).get("summary") or {})
    mutating_count = sum(1 for row in lanes if row.get("may_modify"))
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "agent_lane_registry_v1",
        "phase": "4A_agent_lane_registry",
        "summary": {
            "mode": "shadow",
            "registry_status": "shadow_active" if mutating_count == 0 else "blocked",
            "agent_count": len(lanes),
            "mutating_agent_count": mutating_count,
            "candidate_count": len(candidates),
            "proposal_packets_enabled": True,
            "agent_code_execution_allowed": False,
            "production_mutation_allowed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "auto_merge_allowed": False,
            "pr_review_monitor_status": monitor_summary.get("monitor_status", "unknown"),
            "next_phase_suggested": "4B_agent_proposal_packets",
        },
        "lanes": lanes,
        "routing_rules": _agent_lane_routing_rules(),
        "proposal_packet_contract": {
            "required_fields": list(_agent_packet_required_fields()),
            "blocked_if_missing": [
                "evidence",
                "tests_required",
                "rollback",
                "clinical_safety_analysis",
                "anti_fallback_checks",
            ],
            "output_statuses": [
                "proposal_ready",
                "requires_data",
                "blocked",
                "human_review_required",
            ],
        },
        "handoff_dependency": {
            "pr_review_monitor_status": monitor_summary.get("monitor_status", "unknown"),
            "agents_can_propose_without_pr_merge": True,
            "agents_can_merge": False,
        },
        "controls": {
            "shadow_mode_only": True,
            "agents_may_modify_code": False,
            "agents_may_write_clinical_facts": False,
            "agents_may_create_pr": False,
            "agents_may_merge": False,
            "requires_human_review": True,
        },
        "audit": _audit_footer(),
    }


def build_agent_proposal_packets(
    *,
    agent_lane_registry: Mapping[str, Any] | None = None,
    proposals: Mapping[str, Any] | None = None,
    gap_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4B: specialized agent packets; proposal-only, no code execution."""
    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=35))
    registry = dict(agent_lane_registry or build_agent_lane_registry(gap_bundle=gaps))
    proposal_bundle = dict(proposals or build_proposals(gaps.get("candidates", [])))
    candidates = [dict(row) for row in gaps.get("candidates") or []]
    proposals_by_id = {
        str(row.get("id") or ""): dict(row)
        for row in proposal_bundle.get("proposals") or []
    }
    packets: list[dict[str, Any]] = []
    for lane in registry.get("lanes") or []:
        agent_lane = str(lane.get("agent_lane") or "")
        assigned = [
            dict(candidate)
            for candidate in candidates
            if str(candidate.get("agent_lane") or _agent_lane_for_development_lane(candidate.get("lane"))) == agent_lane
        ]
        candidate = assigned[0] if assigned else {}
        proposal = proposals_by_id.get(str(candidate.get("id") or ""), {})
        packets.append(_build_agent_proposal_packet(agent_lane=agent_lane, lane=lane, candidate=candidate, proposal=proposal))

    ready = sum(1 for row in packets if row.get("packet_status") == "proposal_ready")
    blocked = sum(1 for row in packets if row.get("packet_status") == "blocked")
    requires_data = sum(1 for row in packets if row.get("packet_status") == "requires_data")
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "agent_proposal_packets_v1",
        "phase": "4B_agent_proposal_packets",
        "summary": {
            "mode": "shadow",
            "packet_status": "shadow_packets_ready" if ready else "requires_candidate_data",
            "packet_count": len(packets),
            "proposal_ready_count": ready,
            "requires_data_count": requires_data,
            "blocked_count": blocked,
            "agents_may_modify_code": False,
            "agents_may_write_clinical_facts": False,
            "agent_code_execution_allowed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": "4C_consensus_synthesizer",
        },
        "packets": packets,
        "by_agent": {packet["agent_lane"]: packet for packet in packets},
        "quality_gate": {
            "all_packets_have_required_fields": all(packet.get("quality", {}).get("complete") for packet in packets),
            "blocked_packet_count": blocked,
            "requires_human_review": True,
            "no_production_mutation": True,
        },
        "consensus_inputs": [
            {
                "agent_lane": packet.get("agent_lane"),
                "position": packet.get("position"),
                "top_risk": (packet.get("risks") or [""])[0],
                "minimum_test": (packet.get("tests_required") or [""])[0],
            }
            for packet in packets
        ],
        "controls": {
            "shadow_mode_only": True,
            "packets_are_proposals_only": True,
            "agents_execute_code": False,
            "agents_modify_production": False,
            "clinical_fact_writes_allowed": False,
            "requires_human_review": True,
        },
        "audit": _audit_footer(),
    }


def build_agent_consensus_synthesizer(
    *,
    agent_proposal_packets: Mapping[str, Any] | None = None,
    development_autodrive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4C: synthesize agent packets into one reviewable next step."""
    packets_bundle = dict(agent_proposal_packets or build_agent_proposal_packets())
    packets = [dict(row) for row in packets_bundle.get("packets") or []]
    ready_packets = [row for row in packets if row.get("packet_status") == "proposal_ready"]
    blocked_packets = [row for row in packets if row.get("packet_status") == "blocked"]
    watchlist_packets = [row for row in packets if row.get("packet_status") == "requires_data"]
    selected = _select_consensus_packet(ready_packets, development_autodrive=development_autodrive)
    conflicts = _derive_agent_consensus_conflicts(packets, selected)
    blocking_conditions = _derive_agent_consensus_blockers(selected, blocked_packets, conflicts)
    consensus_status = _agent_consensus_status(selected, blocking_conditions)
    agent_positions = [_agent_consensus_position(packet, selected=selected) for packet in packets]
    agreement_score = _agent_consensus_agreement_score(agent_positions, blocked_packets)
    work_order_preview = _agent_consensus_work_order(selected)

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "agent_consensus_synthesizer_v1",
        "phase": "4C_consensus_synthesizer",
        "summary": {
            "mode": "shadow",
            "consensus_status": consensus_status,
            "selected_candidate_id": selected.get("candidate_id", ""),
            "selected_title": selected.get("candidate_title", ""),
            "selected_agent_lane": selected.get("agent_lane", ""),
            "agreement_score": agreement_score,
            "ready_packet_count": len(ready_packets),
            "watchlist_packet_count": len(watchlist_packets),
            "blocked_packet_count": len(blocked_packets),
            "conflict_count": len(conflicts),
            "blocking_condition_count": len(blocking_conditions),
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": "4D_implementation_brief",
        },
        "consensus_decision": {
            "recommendation": _agent_consensus_recommendation(selected, consensus_status),
            "clinical_or_operational_impact": selected.get("clinical_or_operational_impact", ""),
            "selected_packet_id": selected.get("packet_id", ""),
            "rationale": _agent_consensus_rationale(selected, agent_positions, conflicts),
            "risk_avoided": selected.get("clinical_or_operational_impact", ""),
            "minimum_tests": list(selected.get("tests_required") or []),
            "rollback": selected.get("rollback", ""),
            "cta": "Preparar implementation brief revisable" if selected else "Esperar paquete proposal_ready",
        },
        "agent_positions": agent_positions,
        "conflicts": conflicts,
        "blocking_conditions": blocking_conditions,
        "work_order_preview": work_order_preview,
        "quality_gate": {
            "single_next_iteration_selected": bool(selected),
            "no_blocking_packet_for_selected_candidate": not blocking_conditions,
            "ready_for_implementation_brief": consensus_status == "consensus_ready",
            "requires_human_review": True,
            "no_production_mutation": True,
        },
        "controls": {
            "shadow_mode_only": True,
            "consensus_is_read_model_only": True,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "requires_human_review": True,
        },
        "audit": _audit_footer(),
    }


def build_agent_implementation_brief(
    *,
    agent_consensus_synthesizer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4D: convert consensus into a reviewable implementation brief."""
    consensus = dict(agent_consensus_synthesizer or build_agent_consensus_synthesizer())
    summary = dict(consensus.get("summary") or {})
    decision = dict(consensus.get("consensus_decision") or {})
    work_order = dict(consensus.get("work_order_preview") or {})
    selected_ready = (
        summary.get("consensus_status") == "consensus_ready"
        and bool(work_order.get("available"))
    )
    file_scope = _implementation_file_scope(work_order)
    test_plan = _implementation_test_plan(work_order)
    visual_plan = _implementation_visual_validation_plan(work_order)
    security_plan = _implementation_security_plan(work_order)
    rollback_plan = _implementation_rollback_plan(work_order)
    blockers = _implementation_brief_blockers(
        consensus=consensus,
        work_order=work_order,
        file_scope=file_scope,
        test_plan=test_plan,
        selected_ready=selected_ready,
    )
    brief_status = "brief_ready" if selected_ready and not blockers else "blocked"
    brief_id = _stable_id("4d", work_order.get("candidate_id"), work_order.get("candidate_title"))

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "implementation_brief_v1",
        "phase": "4D_implementation_brief",
        "summary": {
            "mode": "shadow",
            "brief_status": brief_status,
            "brief_id": brief_id,
            "selected_candidate_id": work_order.get("candidate_id", ""),
            "selected_title": work_order.get("candidate_title", ""),
            "agent_lane": work_order.get("agent_lane", ""),
            "development_lane": work_order.get("development_lane", ""),
            "file_count": len(file_scope),
            "test_count": len(test_plan),
            "visual_validation_required": bool(visual_plan),
            "blocker_count": len(blockers),
            "commands_executed": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": "4E_shadow_patch_blueprint",
        },
        "brief": {
            "title": _redact_phi_like(str(work_order.get("candidate_title") or "Implementation brief pending")),
            "objective": _redact_phi_like(str(decision.get("recommendation") or "Prepare a minimal, reviewable implementation plan.")),
            "rationale": _redact_phi_like(str(decision.get("rationale") or "")),
            "risk_avoided": _redact_phi_like(str(decision.get("risk_avoided") or "")),
            "minimal_change": _redact_phi_like(str(work_order.get("minimal_change") or "")),
            "non_goals": [
                "no clinical fact mutation",
                "no PHI in logs or artifacts",
                "no branch, PR or merge creation in this phase",
                "no autonomous change to clinical recommendations",
            ],
        },
        "file_scope": file_scope,
        "change_plan": _implementation_change_plan(work_order),
        "test_plan": test_plan,
        "visual_validation_plan": visual_plan,
        "security_review": security_plan,
        "rollback_plan": rollback_plan,
        "acceptance_checklist": _implementation_acceptance_checklist(work_order, test_plan, visual_plan),
        "risk_register": _implementation_risk_register(consensus, work_order),
        "handoff_packet": {
            "branch_suggestion": f"codex/autodrive-{brief_id}",
            "pr_title_suggestion": _redact_phi_like(f"Autodrive brief: {work_order.get('candidate_title') or 'implementation'}"),
            "ready_for_shadow_patch": brief_status == "brief_ready",
            "human_review_required": True,
            "review_surfaces": sorted(set(list(work_order.get("surfaces") or []) + ["/loop-monitor"])),
        },
        "blockers": blockers,
        "quality_gate": {
            "has_consensus_ready": selected_ready,
            "has_file_scope": bool(file_scope),
            "has_tests": bool(test_plan),
            "has_rollback": bool(rollback_plan.get("primary")),
            "ready_for_shadow_patch_blueprint": brief_status == "brief_ready",
            "requires_human_review": True,
            "no_production_mutation": True,
        },
        "controls": {
            "shadow_mode_only": True,
            "brief_is_read_model_only": True,
            "commands_executed": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "requires_human_review": True,
        },
        "audit": _audit_footer(),
    }


def build_shadow_patch_blueprint(
    *,
    implementation_brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4E: plan patch hunks from the brief without applying them."""
    brief_bundle = dict(implementation_brief or build_agent_implementation_brief())
    summary = dict(brief_bundle.get("summary") or {})
    file_scope = [dict(row) for row in brief_bundle.get("file_scope") or []]
    test_plan = [dict(row) for row in brief_bundle.get("test_plan") or []]
    visual_plan = [dict(row) for row in brief_bundle.get("visual_validation_plan") or []]
    blockers = _shadow_patch_blueprint_blockers(
        implementation_brief=brief_bundle,
        file_scope=file_scope,
        test_plan=test_plan,
    )
    file_blueprints = _shadow_patch_file_blueprints(brief_bundle, file_scope)
    planned_hunk_count = sum(int(row.get("planned_hunk_count") or 0) for row in file_blueprints)
    blueprint_status = "blueprint_ready" if not blockers else "blocked"
    blueprint_id = _stable_id("4e", summary.get("brief_id"), summary.get("selected_candidate_id"))

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "shadow_patch_blueprint_v1",
        "phase": "4E_shadow_patch_blueprint",
        "summary": {
            "mode": "shadow",
            "blueprint_status": blueprint_status,
            "blueprint_id": blueprint_id,
            "brief_id": summary.get("brief_id", ""),
            "selected_candidate_id": summary.get("selected_candidate_id", ""),
            "selected_title": summary.get("selected_title", ""),
            "planned_file_count": len(file_blueprints),
            "planned_hunk_count": planned_hunk_count,
            "test_count": len(test_plan),
            "visual_validation_count": len(visual_plan),
            "blocker_count": len(blockers),
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": "4F_human_patch_authorization",
        },
        "patch_blueprint": {
            "objective": brief_bundle.get("brief", {}).get("objective", ""),
            "minimal_change": brief_bundle.get("brief", {}).get("minimal_change", ""),
            "file_blueprints": file_blueprints,
            "patch_sequence": _shadow_patch_sequence(file_blueprints),
            "non_goals": list(brief_bundle.get("brief", {}).get("non_goals") or []),
        },
        "validation_blueprint": {
            "tests": test_plan,
            "visual_validation": visual_plan,
            "security_review": dict(brief_bundle.get("security_review") or {}),
            "acceptance_checklist": list(brief_bundle.get("acceptance_checklist") or []),
        },
        "rollback_blueprint": _shadow_patch_rollback_blueprint(brief_bundle, file_blueprints),
        "review_packet": {
            "branch_suggestion": brief_bundle.get("handoff_packet", {}).get("branch_suggestion", f"codex/autodrive-{blueprint_id}"),
            "pr_title_suggestion": brief_bundle.get("handoff_packet", {}).get("pr_title_suggestion", "Autodrive patch blueprint"),
            "review_surfaces": list(brief_bundle.get("handoff_packet", {}).get("review_surfaces") or ["/loop-monitor"]),
            "human_review_required": True,
            "ready_for_human_authorization": blueprint_status == "blueprint_ready",
        },
        "blockers": blockers,
        "quality_gate": {
            "has_ready_brief": summary.get("brief_status") == "brief_ready",
            "has_file_blueprints": bool(file_blueprints),
            "has_planned_hunks": planned_hunk_count > 0,
            "has_test_blueprint": bool(test_plan),
            "has_rollback_blueprint": True,
            "ready_for_human_patch_authorization": blueprint_status == "blueprint_ready",
            "requires_human_review": True,
            "no_production_mutation": True,
        },
        "controls": {
            "shadow_mode_only": True,
            "blueprint_is_read_model_only": True,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "requires_human_review": True,
        },
        "audit": _audit_footer(),
    }


def build_human_patch_authorization(
    *,
    shadow_patch_blueprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4F: explicit human authorization gate before any patch can be applied."""
    blueprint = dict(shadow_patch_blueprint or build_shadow_patch_blueprint())
    summary = dict(blueprint.get("summary") or {})
    blueprint_id = str(summary.get("blueprint_id") or "")
    latest = _load_latest_human_patch_authorization(blueprint_id)
    blueprint_ready = (
        summary.get("blueprint_status") == "blueprint_ready"
        and bool(blueprint.get("quality_gate", {}).get("ready_for_human_patch_authorization"))
    )
    decision = str(latest.get("decision") or "hold")

    if not blueprint_ready:
        authorization_state = "blocked_until_blueprint_ready"
        authorization_gate = "blocked"
        next_phase = "4E_shadow_patch_blueprint"
    elif decision == "authorize_patch":
        authorization_state = "authorized_for_controlled_patch"
        authorization_gate = "authorized_for_controlled_patch"
        next_phase = "4G_controlled_patch_application"
    elif decision == "request_changes":
        authorization_state = "changes_requested"
        authorization_gate = "blocked"
        next_phase = "4D_implementation_brief"
    elif decision == "reject":
        authorization_state = "rejected"
        authorization_gate = "blocked"
        next_phase = "3A_development_autodrive"
    else:
        authorization_state = "pending_human_authorization"
        authorization_gate = "human_authorization_required"
        next_phase = "4F_human_patch_authorization"

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "human_patch_authorization_v1",
        "phase": "4F_human_patch_authorization",
        "summary": {
            "mode": "shadow",
            "authorization_state": authorization_state,
            "authorization_gate": authorization_gate,
            "decision": decision,
            "blueprint_ready": blueprint_ready,
            "human_authorization_required": authorization_state == "pending_human_authorization",
            "patch_application_allowed": authorization_state == "authorized_for_controlled_patch",
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "allowed_decisions": _allowed_patch_authorization_decisions(blueprint_ready),
        "blueprint": {
            "blueprint_id": blueprint_id,
            "status": summary.get("blueprint_status", "blocked"),
            "selected_candidate_id": summary.get("selected_candidate_id", ""),
            "selected_title": summary.get("selected_title", ""),
            "planned_file_count": summary.get("planned_file_count", 0),
            "planned_hunk_count": summary.get("planned_hunk_count", 0),
            "test_count": summary.get("test_count", 0),
            "review_packet": dict(blueprint.get("review_packet") or {}),
        },
        "latest_decision": latest,
        "authorization_requirements": {
            "requires_blueprint_ready": True,
            "requires_human_reviewer": True,
            "requires_security_review": True,
            "requires_test_plan": bool((blueprint.get("validation_blueprint") or {}).get("tests")),
            "requires_rollback_blueprint": bool(blueprint.get("rollback_blueprint")),
        },
        "controls": {
            "shadow_mode_only": True,
            "records_audit_only": True,
            "authorization_does_not_apply_patch": True,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "blueprint_ready": blueprint_ready,
            "human_authorization_recorded": bool(latest),
            "ready_for_controlled_patch_application": authorization_state == "authorized_for_controlled_patch",
            "no_production_mutation": True,
        },
        "audit": _audit_footer(),
    }


def build_controlled_patch_application(
    *,
    shadow_patch_blueprint: Mapping[str, Any] | None = None,
    human_patch_authorization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4G: build the controlled patch application packet without applying it."""
    blueprint = dict(shadow_patch_blueprint or build_shadow_patch_blueprint())
    authorization = dict(
        human_patch_authorization
        or build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    )
    blueprint_summary = dict(blueprint.get("summary") or {})
    auth_summary = dict(authorization.get("summary") or {})
    patch_blueprint = dict(blueprint.get("patch_blueprint") or {})
    file_blueprints = list(patch_blueprint.get("file_blueprints") or [])
    validation_blueprint = dict(blueprint.get("validation_blueprint") or {})
    tests = list(validation_blueprint.get("tests") or [])
    rollback_blueprint = dict(blueprint.get("rollback_blueprint") or {})
    authorized = bool(auth_summary.get("patch_application_allowed"))
    blueprint_ready = blueprint_summary.get("blueprint_status") == "blueprint_ready"
    has_minimum_packet = bool(file_blueprints and tests and rollback_blueprint)

    blockers: list[str] = []
    if not blueprint_ready:
        blockers.append("shadow_patch_blueprint_not_ready")
    if not authorized:
        blockers.append("human_patch_authorization_missing")
    if not file_blueprints:
        blockers.append("file_blueprints_missing")
    if not tests:
        blockers.append("test_blueprint_missing")
    if not rollback_blueprint:
        blockers.append("rollback_blueprint_missing")

    if blockers:
        application_status = "blocked_until_authorization" if "human_patch_authorization_missing" in blockers else "blocked"
        application_gate = "blocked"
        next_phase = "4F_human_patch_authorization" if "human_patch_authorization_missing" in blockers else "4E_shadow_patch_blueprint"
    else:
        application_status = "ready_for_phase_5_controlled_pr"
        application_gate = "controlled_application_packet_ready"
        next_phase = "5A_controlled_pr_implementation"

    branch_name = str((blueprint.get("review_packet") or {}).get("branch_suggestion") or f"codex/autodrive-{blueprint_summary.get('blueprint_id', 'patch')}")
    safe_files = [
        {
            "path": str(row.get("path") or ""),
            "planned_hunk_count": int(row.get("planned_hunk_count") or 0),
            "review_risk": str(row.get("review_risk") or "medium"),
            "requires_manual_apply": True,
        }
        for row in file_blueprints
    ]
    execution_steps = [
        {
            "step": "create_branch",
            "label": "Crear rama controlada",
            "command": f"git checkout -b {branch_name}",
            "automatic_execution_allowed": False,
        },
        {
            "step": "apply_patch",
            "label": "Aplicar hunks mínimos revisados",
            "command": "manual apply_patch from reviewed blueprint",
            "automatic_execution_allowed": False,
        },
        {
            "step": "run_tests",
            "label": "Ejecutar pruebas declaradas",
            "command": " && ".join(str(test.get("command") or "") for test in tests[:3]),
            "automatic_execution_allowed": False,
        },
        {
            "step": "visual_validation",
            "label": "Validar UI en navegador local",
            "command": "browser validation on declared visual routes",
            "automatic_execution_allowed": False,
        },
        {
            "step": "human_review",
            "label": "Revisión humana antes de PR/merge",
            "command": "manual review required",
            "automatic_execution_allowed": False,
        },
    ]
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "controlled_patch_application_v1",
        "phase": "4G_controlled_patch_application",
        "summary": {
            "mode": "shadow",
            "application_status": application_status,
            "application_gate": application_gate,
            "blueprint_id": blueprint_summary.get("blueprint_id", ""),
            "authorized": authorized,
            "planned_file_count": len(safe_files),
            "planned_hunk_count": sum(int(row.get("planned_hunk_count") or 0) for row in safe_files),
            "test_count": len(tests),
            "blocker_count": len(blockers),
            "ready_for_phase_5": application_status == "ready_for_phase_5_controlled_pr",
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "application_packet": {
            "branch_name": branch_name,
            "pr_title": str((blueprint.get("review_packet") or {}).get("pr_title_suggestion") or "Autodrive controlled patch"),
            "objective": patch_blueprint.get("objective", ""),
            "minimal_change": patch_blueprint.get("minimal_change", ""),
            "files": safe_files,
            "execution_steps": execution_steps,
            "tests": tests,
            "visual_validation": list(validation_blueprint.get("visual_validation") or []),
            "rollback": rollback_blueprint,
            "review_required": True,
        },
        "blockers": blockers,
        "controls": {
            "requires_4f_authorization": True,
            "requires_phase_5_human_operator": True,
            "automatic_execution_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "blueprint_ready": blueprint_ready,
            "human_authorized": authorized,
            "has_application_packet": has_minimum_packet,
            "ready_for_phase_5_controlled_pr": application_status == "ready_for_phase_5_controlled_pr",
            "no_production_mutation": True,
        },
        "audit": _audit_footer(),
    }


def build_controlled_pr_implementation(
    *,
    controlled_patch_application: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 5A: prepare a human-run branch/patch/PR packet without mutating git."""
    application = dict(controlled_patch_application or build_controlled_patch_application())
    summary = dict(application.get("summary") or {})
    packet = dict(application.get("application_packet") or {})
    files = list(packet.get("files") or [])
    tests = list(packet.get("tests") or [])
    visual_validation = list(packet.get("visual_validation") or [])
    rollback = dict(packet.get("rollback") or {})
    ready_4g = bool(summary.get("ready_for_phase_5"))
    branch_name = str(packet.get("branch_name") or f"codex/autodrive-{summary.get('blueprint_id', 'manual')}")

    blockers: list[str] = []
    if not ready_4g:
        blockers.append("controlled_patch_application_not_ready")
    if not branch_name.startswith("codex/"):
        blockers.append("branch_prefix_invalid")
    if not files:
        blockers.append("implementation_files_missing")
    if not tests:
        blockers.append("test_commands_missing")
    if not rollback:
        blockers.append("rollback_plan_missing")

    if blockers:
        implementation_status = "blocked_until_4g_ready"
        implementation_gate = "blocked"
        next_phase = "4F_human_patch_authorization" if "controlled_patch_application_not_ready" in blockers else "4G_controlled_patch_application"
    else:
        implementation_status = "ready_for_manual_branch_patch_and_draft_pr"
        implementation_gate = "manual_pr_packet_ready"
        next_phase = "5B_draft_pr_publication_gate"

    manual_commands = [
        {
            "cmd": "git status --short",
            "purpose": "Confirmar estado del worktree antes de crear rama controlada.",
            "automatic_execution_allowed": False,
        },
        {
            "cmd": f"git checkout -b {branch_name}",
            "purpose": "Crear rama codex/autodrive para el patch autorizado.",
            "automatic_execution_allowed": False,
        },
        {
            "cmd": "manual apply_patch from controlled packet",
            "purpose": "Aplicar sólo hunks revisados del paquete 4G.",
            "automatic_execution_allowed": False,
        },
    ]
    manual_commands.extend(
        {
            "cmd": str(test.get("command") or ""),
            "purpose": str(test.get("purpose") or "Validar el patch controlado."),
            "automatic_execution_allowed": False,
        }
        for test in tests
        if test.get("command")
    )
    manual_commands.extend([
        {
            "cmd": "visual validation on /loop-monitor and impacted surfaces",
            "purpose": "Confirmar que la UI refleja el cambio sin errores de consola.",
            "automatic_execution_allowed": False,
        },
        {
            "cmd": "git diff --check",
            "purpose": "Evitar whitespace/errors antes del PR draft.",
            "automatic_execution_allowed": False,
        },
    ])

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "controlled_pr_implementation_v1",
        "phase": "5A_controlled_pr_implementation",
        "summary": {
            "mode": "controlled_manual",
            "implementation_status": implementation_status,
            "implementation_gate": implementation_gate,
            "branch_name": branch_name,
            "ready_for_manual_execution": implementation_status == "ready_for_manual_branch_patch_and_draft_pr",
            "planned_file_count": len(files),
            "test_count": len(tests),
            "visual_validation_count": len(visual_validation),
            "blocker_count": len(blockers),
            "commands_prepared": bool(manual_commands),
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "implementation_packet": {
            "branch_name": branch_name,
            "pr_title": packet.get("pr_title", "Autodrive controlled patch"),
            "objective": packet.get("objective", ""),
            "minimal_change": packet.get("minimal_change", ""),
            "manual_commands": manual_commands,
            "files": files,
            "tests": tests,
            "visual_validation": visual_validation,
            "rollback": rollback,
            "draft_pr_body_sections": [
                "Clinical rationale",
                "Files changed",
                "Safety gates",
                "Visual validation",
                "Rollback",
                "Human review checklist",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_4g_ready_packet": True,
            "requires_human_operator": True,
            "automatic_execution_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "controlled_patch_application_ready": ready_4g,
            "has_branch_plan": branch_name.startswith("codex/"),
            "has_file_scope": bool(files),
            "has_tests": bool(tests),
            "has_rollback": bool(rollback),
            "ready_for_5b_draft_pr_publication_gate": implementation_status == "ready_for_manual_branch_patch_and_draft_pr",
            "no_production_mutation": True,
        },
        "audit": _audit_footer(),
    }


def build_draft_pr_publication_gate(
    *,
    controlled_pr_implementation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 5B: gate draft PR publication readiness without creating the PR."""
    implementation = dict(controlled_pr_implementation or build_controlled_pr_implementation())
    summary = dict(implementation.get("summary") or {})
    packet = dict(implementation.get("implementation_packet") or {})
    commands = list(packet.get("manual_commands") or [])
    files = list(packet.get("files") or [])
    tests = list(packet.get("tests") or [])
    visual_validation = list(packet.get("visual_validation") or [])
    rollback = dict(packet.get("rollback") or {})
    ready_5a = bool(summary.get("ready_for_manual_execution"))
    branch_name = str(packet.get("branch_name") or summary.get("branch_name") or "")
    pr_title = str(packet.get("pr_title") or "Autodrive controlled patch")

    blockers: list[str] = []
    if not ready_5a:
        blockers.append("controlled_pr_implementation_not_ready")
    if not branch_name.startswith("codex/"):
        blockers.append("branch_prefix_invalid")
    if not pr_title.strip():
        blockers.append("pr_title_missing")
    if not commands:
        blockers.append("manual_command_plan_missing")
    if not files:
        blockers.append("file_scope_missing")
    if not tests:
        blockers.append("test_plan_missing")
    if not rollback:
        blockers.append("rollback_plan_missing")

    if blockers:
        publication_status = "blocked_until_5a_ready"
        publication_gate = "blocked"
        next_phase = "5A_controlled_pr_implementation"
    else:
        publication_status = "ready_for_manual_draft_pr_publication"
        publication_gate = "manual_publication_packet_ready"
        next_phase = "6A_required_safety_gate_contract"

    draft_body_sections = [
        {
            "title": "Clinical rationale",
            "content": packet.get("objective", "Controlled improvement packet."),
        },
        {
            "title": "Minimal change",
            "content": packet.get("minimal_change", "Apply only reviewed hunks from the controlled packet."),
        },
        {
            "title": "Files changed",
            "content": ", ".join(str(row.get("path") or "") for row in files[:8]),
        },
        {
            "title": "Safety gates",
            "content": "; ".join(str(test.get("command") or "") for test in tests[:6]),
        },
        {
            "title": "Visual validation",
            "content": "; ".join(str(row.get("route") or row.get("surface") or row) for row in visual_validation[:6]) or "/loop-monitor",
        },
        {
            "title": "Rollback",
            "content": str(rollback.get("primary") or rollback.get("manual") or rollback or "Revert controlled patch before merge."),
        },
    ]

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "draft_pr_publication_gate_v1",
        "phase": "5B_draft_pr_publication_gate",
        "summary": {
            "mode": "controlled_manual",
            "publication_status": publication_status,
            "publication_gate": publication_gate,
            "branch_name": branch_name,
            "pr_title": pr_title,
            "ready_for_manual_publication": publication_status == "ready_for_manual_draft_pr_publication",
            "publication_allowed": publication_status == "ready_for_manual_draft_pr_publication",
            "planned_file_count": len(files),
            "test_count": len(tests),
            "blocker_count": len(blockers),
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "publication_packet": {
            "branch_name": branch_name,
            "pr_title": pr_title,
            "draft_body_sections": draft_body_sections,
            "manual_publication_steps": [
                {
                    "step": "review_worktree",
                    "label": "Confirmar diff y estado local",
                    "command": "git status --short && git diff --check",
                    "automatic_execution_allowed": False,
                },
                {
                    "step": "run_declared_tests",
                    "label": "Ejecutar pruebas declaradas",
                    "command": " && ".join(str(test.get("command") or "") for test in tests[:3]),
                    "automatic_execution_allowed": False,
                },
                {
                    "step": "open_draft_pr",
                    "label": "Abrir PR draft manualmente",
                    "command": "gh pr create --draft --fill",
                    "automatic_execution_allowed": False,
                },
                {
                    "step": "attach_visual_validation",
                    "label": "Adjuntar validación visual",
                    "command": "manual browser validation artifacts",
                    "automatic_execution_allowed": False,
                },
            ],
            "required_reviewers": ["clinical_owner", "security_owner", "engineering_owner"],
            "merge_policy": {
                "auto_merge_allowed": False,
                "requires_human_review": True,
                "requires_ci_passed": True,
                "requires_visual_validation": True,
                "requires_no_phi_artifacts": True,
            },
        },
        "blockers": blockers,
        "controls": {
            "requires_5a_ready_packet": True,
            "requires_human_operator": True,
            "automatic_publication_allowed": False,
            "automatic_execution_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "controlled_pr_implementation_ready": ready_5a,
            "has_branch_name": branch_name.startswith("codex/"),
            "has_draft_pr_body": bool(draft_body_sections),
            "has_tests": bool(tests),
            "has_rollback": bool(rollback),
            "ready_for_6a_required_safety_gate_contract": publication_status == "ready_for_manual_draft_pr_publication",
            "no_production_mutation": True,
        },
        "audit": _audit_footer(),
    }


def build_required_safety_gate_contract(
    *,
    draft_pr_publication_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 6A: canonical required safety gates before PR publication/merge.

    This is a contract read-model only. It defines what must pass after the
    draft PR packet exists, but it never runs commands, creates branches or
    mutates clinical facts.
    """
    publication = dict(draft_pr_publication_gate or build_draft_pr_publication_gate())
    summary = dict(publication.get("summary") or {})
    packet = dict(publication.get("publication_packet") or {})
    ready_5b = bool(summary.get("ready_for_manual_publication"))
    packet_text = json.dumps(packet, sort_keys=True, ensure_ascii=True).lower()

    touches_voice = any(token in packet_text for token in ("voice", "cortana", "prostamed_voice_os"))
    touches_field_router = any(token in packet_text for token in ("clinical_field_router", "field router", "clinical-hub"))

    required_gates = [
        {
            "gate_id": "unit_tests_declared",
            "label": "Pruebas declaradas del paquete 5B",
            "category": "technical_regression",
            "command": "pytest -q tests/test_autonomous_improvement_os.py",
            "blocking": True,
            "required": True,
            "status": "pending_manual_execution" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "decision_today_regression",
            "label": "Regresión Decision Today Fusion Kernel",
            "category": "clinical_logic",
            "command": "pytest -q tests/test_decision_today_fusion_kernel.py",
            "blocking": True,
            "required": True,
            "status": "pending_manual_execution" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "autodrive_regression",
            "label": "Regresión Clinical Autodrive Command Center",
            "category": "clinical_priority_queue",
            "command": "pytest -q tests/test_clinical_autodrive_command_center.py",
            "blocking": True,
            "required": True,
            "status": "pending_manual_execution" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "readiness_tumor_care_memory_regression",
            "label": "Regresión Readiness, Tumor Board, Care Pathway y Memory",
            "category": "clinical_os_stack",
            "command": (
                "pytest -q tests/test_clinical_readiness_tower.py tests/test_tumor_board_os.py "
                "tests/test_care_pathway_os.py tests/test_clinical_memory_os.py"
            ),
            "blocking": True,
            "required": True,
            "status": "pending_manual_execution" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "field_router_gate_if_fields_touched",
            "label": "Clinical Field Router si el patch toca campos o clasificador",
            "category": "data_contract",
            "command": "pytest -q tests/test_clinical_field_router_closure.py tests/test_clinical_hub_legacy_classifier_flow.py",
            "blocking": bool(touches_field_router),
            "required": bool(touches_field_router),
            "status": (
                "pending_manual_execution" if ready_5b and touches_field_router
                else "not_applicable" if ready_5b else "blocked_until_5b_ready"
            ),
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "voice_gate_if_cortana_touched",
            "label": "Voice OS si el patch toca Cortana",
            "category": "voice_safety",
            "command": "pytest -q tests/test_voice_clinical_os.py",
            "blocking": bool(touches_voice),
            "required": bool(touches_voice),
            "status": (
                "pending_manual_execution" if ready_5b and touches_voice
                else "not_applicable" if ready_5b else "blocked_until_5b_ready"
            ),
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "visual_validation_browser",
            "label": "Validación visual Browser desktop/móvil",
            "category": "ui_safety",
            "command": "browser validation on /loop-monitor, /dashboard, /patients, /patient_profile, /clinical-hub, /longitudinal-capture",
            "blocking": True,
            "required": True,
            "status": "pending_manual_validation" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "security_phi_artifact_scan",
            "label": "Escaneo PHI/logs/artifacts",
            "category": "security",
            "command": "manual security scan: no PHI in logs, artifacts or PR body",
            "blocking": True,
            "required": True,
            "status": "pending_manual_review" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "anti_fallback_clinical_data",
            "label": "Anti-fallback clínico",
            "category": "clinical_safety",
            "command": "assert no invented PSA/APE, testosterone, therapy lines or trial eligibility",
            "blocking": True,
            "required": True,
            "status": "pending_manual_review" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
        {
            "gate_id": "gates_trials_contract",
            "label": "Contrato 103 gates y 47 trials",
            "category": "clinical_contract",
            "command": "pytest -q tests/test_pivotal_gates_yaml_loader.py tests/test_v2_production_routes.py",
            "blocking": True,
            "required": True,
            "status": "pending_manual_execution" if ready_5b else "blocked_until_5b_ready",
            "automatic_execution_allowed": False,
        },
    ]

    blockers: list[str] = []
    if not ready_5b:
        blockers.append("draft_pr_publication_gate_not_ready")
    if not required_gates:
        blockers.append("required_safety_gate_rows_missing")

    blocking_gate_count = sum(1 for gate in required_gates if gate.get("blocking"))
    executable_gate_count = sum(1 for gate in required_gates if gate.get("status") != "not_applicable")
    if blockers:
        contract_status = "blocked_until_5b_ready"
        safety_gate = "blocked"
        next_phase = "5B_draft_pr_publication_gate"
    else:
        contract_status = "ready_for_manual_safety_gate_execution"
        safety_gate = "manual_required_gates_declared"
        next_phase = "7A_evidence_refresh_shadow_loop"

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "required_safety_gate_contract_v1",
        "phase": "6A_required_safety_gate_contract",
        "summary": {
            "mode": "controlled_manual",
            "safety_contract_status": contract_status,
            "safety_gate": safety_gate,
            "ready_for_safety_execution": contract_status == "ready_for_manual_safety_gate_execution",
            "gate_count": len(required_gates),
            "blocking_gate_count": blocking_gate_count,
            "executable_gate_count": executable_gate_count,
            "blocker_count": len(blockers),
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "required_gates": required_gates,
        "contract": {
            "review_surfaces": [
                "/loop-monitor",
                "/dashboard",
                "/patients",
                "/patient_profile/<nss>?v=2",
                "/clinical-hub",
                "/longitudinal-capture/<nss>",
            ],
            "failure_policy": "any_blocking_gate_failed_blocks_publication_and_merge",
            "required_status_before_publication": "all_blocking_gates_passed_or_human_accepted",
            "required_status_before_merge": "ci_passed_and_clinical_security_engineering_reviews_complete",
            "clinical_blockers": [
                "invented_psa_or_testosterone",
                "invented_therapy_or_line",
                "eligible_trial_with_empty_or_missing_critical_payload",
                "decision_today_contradiction_unresolved",
                "phi_in_logs_or_artifacts",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_5b_publication_packet": True,
            "requires_human_operator": True,
            "automatic_execution_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "code_execution_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "draft_pr_publication_ready": ready_5b,
            "has_required_gates": bool(required_gates),
            "has_clinical_regression_gates": any(g.get("category") == "clinical_os_stack" for g in required_gates),
            "has_security_phi_gate": any(g.get("gate_id") == "security_phi_artifact_scan" for g in required_gates),
            "has_anti_fallback_gate": any(g.get("gate_id") == "anti_fallback_clinical_data" for g in required_gates),
            "ready_for_7a_evidence_refresh_shadow_loop": contract_status == "ready_for_manual_safety_gate_execution",
            "no_production_mutation": True,
        },
        "audit": _audit_footer(),
    }


def build_evidence_refresh_shadow_loop(
    *,
    required_safety_gate_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 7A: shadow evidence surveillance without changing clinical logic.

    The loop declares authoritative sources and impact contracts. It can create
    review candidates, but guideline/trial logic changes remain blocked until a
    clinician reviews evidence, tests and rollback.
    """
    safety_contract = dict(required_safety_gate_contract or build_required_safety_gate_contract())
    safety_summary = dict(safety_contract.get("summary") or {})
    ready_6a = bool(safety_summary.get("ready_for_safety_execution"))

    source_registry = [
        {
            **dict(source),
            "status": "registered_for_shadow_surveillance" if ready_6a else "blocked_until_6a_ready",
            "requires_human_review_before_logic_change": True,
            "automatic_recommendation_update_allowed": False,
        }
        for source in EVIDENCE_REFRESH_SOURCE_REGISTRY
    ]
    review_queue = [
        {
            "candidate_id": f"evidence-change-{source['source_id']}",
            "source_id": source["source_id"],
            "title": f"Review evidence changes from {source['label']}",
            "status": "watching_shadow" if ready_6a else "blocked_until_6a_ready",
            "clinical_impact_surfaces": list(source.get("mapped_consumers") or []),
            "risk_avoided": "Avoids stale Decision Today, trial, gate or safety recommendations.",
            "change_types": [
                "new_or_updated_recommendation",
                "indication_or_label_change",
                "trial_status_or_criteria_change",
                "safety_signal_or_patient_reported_outcome_change",
            ],
            "required_human_review": True,
            "required_tests": [
                "test_evidence_change_candidate_requires_human_review",
                "test_evidence_loop_does_not_change_recommendations_automatically",
                "test_decision_today_fusion_kernel_regression_after_evidence_review",
            ],
            "automatic_application_allowed": False,
        }
        for source in source_registry
    ]
    shadow_checks = [
        {
            "check_id": "source_registry_complete",
            "label": "Fuentes oficiales mínimas registradas",
            "status": "ready" if len(source_registry) >= 5 else "blocked",
            "blocking": True,
        },
        {
            "check_id": "human_review_required",
            "label": "Revisión humana requerida antes de modificar lógica",
            "status": "ready",
            "blocking": True,
        },
        {
            "check_id": "no_automatic_guideline_change",
            "label": "No cambia recomendaciones ni gates automáticamente",
            "status": "ready",
            "blocking": True,
        },
        {
            "check_id": "safety_gate_contract_ready",
            "label": "Contrato 6A listo antes de activar vigilancia de evidencia",
            "status": "ready" if ready_6a else "blocked_until_6a_ready",
            "blocking": True,
        },
    ]

    blockers: list[str] = []
    if not ready_6a:
        blockers.append("required_safety_gate_contract_not_ready")
    if not source_registry:
        blockers.append("evidence_source_registry_missing")
    if not review_queue:
        blockers.append("evidence_review_queue_missing")

    if blockers:
        evidence_refresh_status = "blocked_until_6a_ready"
        evidence_gate = "blocked"
        next_phase = "6A_required_safety_gate_contract"
    else:
        evidence_refresh_status = "ready_for_shadow_evidence_surveillance"
        evidence_gate = "shadow_surveillance_registered"
        next_phase = "8A_patient_twin_readiness_loop"

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "evidence_refresh_shadow_loop_v1",
        "phase": "7A_evidence_refresh_shadow_loop",
        "summary": {
            "mode": "shadow",
            "evidence_refresh_status": evidence_refresh_status,
            "evidence_gate": evidence_gate,
            "ready_for_shadow_surveillance": evidence_refresh_status == "ready_for_shadow_evidence_surveillance",
            "source_count": len(source_registry),
            "review_candidate_count": len(review_queue),
            "blocking_check_count": sum(1 for row in shadow_checks if row.get("blocking")),
            "blocker_count": len(blockers),
            "evidence_changes_applied": False,
            "recommendation_logic_mutated": False,
            "trial_logic_mutated": False,
            "gate_logic_mutated": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "source_registry": source_registry,
        "review_queue": review_queue,
        "shadow_checks": shadow_checks,
        "workflow_contract": {
            "workflow": ".github/workflows/evidence_refresh_loop.yml",
            "cadence": "weekly_sunday_0000_utc_plus_manual_dispatch",
            "allowed_outputs": [
                "evidence_change_candidate",
                "impact_map",
                "tests_required",
                "human_review_packet",
            ],
            "forbidden_outputs": [
                "automatic_guideline_logic_change",
                "automatic_trial_eligibility_change",
                "automatic_gate_logic_change",
                "automatic_recommendation_release",
            ],
        },
        "impact_contract": {
            "must_map_change_to": [
                "gate_code_or_not_applicable",
                "trial_id_or_not_applicable",
                "clinical_state",
                "capture_surface",
                "persistence_contract",
                "consumer_bundle",
                "regression_test",
            ],
            "must_block_if": [
                "source_unverified",
                "no_human_review",
                "no_regression_test",
                "conflicts_with_decision_today_without_resolution",
                "would_make_trial_eligible_with_missing_critical_data",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_6a_required_safety_gate_contract": True,
            "requires_human_review": True,
            "automatic_evidence_application_allowed": False,
            "automatic_recommendation_update_allowed": False,
            "automatic_execution_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "clinical_fact_writes_allowed": False,
            "clinical_logic_writes_allowed": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "required_safety_gate_contract_ready": ready_6a,
            "has_official_source_registry": len(source_registry) >= 5,
            "has_review_queue": bool(review_queue),
            "human_review_required_for_each_candidate": all(row.get("required_human_review") for row in review_queue),
            "no_automatic_clinical_logic_mutation": True,
            "ready_for_8a_patient_twin_readiness_loop": evidence_refresh_status == "ready_for_shadow_evidence_surveillance",
        },
        "audit": _audit_footer(),
    }


def build_patient_twin_readiness_loop(
    *,
    evidence_refresh_shadow_loop: Mapping[str, Any] | None = None,
    gap_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 8A: Patient Twin readiness scan without simulation or ML release."""
    evidence_loop = dict(evidence_refresh_shadow_loop or build_evidence_refresh_shadow_loop())
    evidence_summary = dict(evidence_loop.get("summary") or {})
    ready_7a = bool(evidence_summary.get("ready_for_shadow_surveillance"))

    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=20))
    context = dict(gaps.get("context") or {})
    patients = dict(context.get("patients") or context.get("patient_scan") or {})
    evaluated = int(patients.get("evaluated") or 0)
    scanned = int(patients.get("scanned") or evaluated or 0)
    patient_scope_estimate = max(evaluated, scanned)
    missing_pairs = list(patients.get("missing_fields_top") or [])
    patient_twin_available = bool(context.get("patient_twin_available"))
    contract = _contract_by_id("patient_twin_preference_pro_minimum")

    readiness_dimensions: list[dict[str, Any]] = []
    for dimension in PATIENT_TWIN_READINESS_DIMENSIONS:
        aliases = list(dimension.get("field_aliases") or dimension.get("required_fields") or [])
        missing_count = _missing_count_for_aliases(missing_pairs, aliases)
        if not ready_7a:
            status = "blocked_until_7a_ready"
        elif not patient_twin_available:
            status = "requires_data"
        elif missing_count > 0 or patient_scope_estimate <= 0:
            status = "requires_data"
        else:
            status = "ready"
        readiness_dimensions.append({
            "dimension_id": dimension["dimension_id"],
            "label": dimension["label"],
            "required_fields": list(dimension.get("required_fields") or []),
            "capture_surface": dimension["capture_surface"],
            "persistence": dimension["persistence"],
            "consumer": dimension["consumer"],
            "status": status,
            "missing_count_estimate": int(missing_count or (patient_scope_estimate if status == "requires_data" else 0)),
            "patient_scope_estimate": patient_scope_estimate,
            "cta": dimension["capture_surface"],
            "blocking": status != "ready",
            "automatic_simulation_allowed": False,
        })

    capture_plan = [
        {
            "dimension_id": row["dimension_id"],
            "label": row["label"],
            "field": (row.get("required_fields") or ["patient_twin_readiness"])[0],
            "status": row["status"],
            "cta": row["cta"],
            "capture_surface": row["capture_surface"],
            "persistence": row["persistence"],
            "consumer": row["consumer"],
        }
        for row in readiness_dimensions
        if row.get("status") != "ready"
    ]

    blockers: list[str] = []
    if not ready_7a:
        blockers.append("evidence_refresh_shadow_loop_not_ready")
    if not readiness_dimensions:
        blockers.append("patient_twin_readiness_dimensions_missing")
    if not contract:
        blockers.append("patient_twin_preference_pro_contract_missing")

    if blockers:
        readiness_status = "blocked_until_7a_ready"
        readiness_gate = "blocked"
        next_phase = "7A_evidence_refresh_shadow_loop"
    else:
        readiness_status = "ready_for_patient_twin_readiness_shadow_scan"
        readiness_gate = "readiness_contract_registered"
        next_phase = "9A_ai_readiness_dataset_loop"

    dominant = next((row for row in readiness_dimensions if row.get("status") != "ready"), {})
    dimension_count = len(readiness_dimensions)
    not_ready_count = sum(1 for row in readiness_dimensions if row.get("status") != "ready")

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "patient_twin_readiness_loop_v1",
        "phase": "8A_patient_twin_readiness_loop",
        "summary": {
            "mode": "shadow",
            "patient_twin_readiness_status": readiness_status,
            "patient_twin_gate": readiness_gate,
            "ready_for_shadow_scan": readiness_status == "ready_for_patient_twin_readiness_shadow_scan",
            "patient_twin_os_available": patient_twin_available,
            "evaluated_patient_count": evaluated,
            "scanned_patient_count": scanned,
            "dimension_count": dimension_count,
            "not_ready_dimension_count": not_ready_count,
            "capture_action_count": len(capture_plan),
            "dominant_missing_dimension": dominant.get("dimension_id", ""),
            "twin_ready_pct": 100.0 if patient_twin_available and not_ready_count == 0 and dimension_count else 0.0,
            "preference_complete_pct": _dimension_completion_pct(readiness_dimensions, "patient_values"),
            "pro_baseline_pct": _dimension_completion_pct(readiness_dimensions, "baseline_pro"),
            "longitudinal_trajectory_pct": _dimension_completion_pct(readiness_dimensions, "longitudinal_trajectory"),
            "redecision_threshold_pct": _dimension_completion_pct(readiness_dimensions, "redecision_threshold"),
            "simulation_release_allowed": False,
            "patient_twin_models_trained": False,
            "patient_twin_predictions_released": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "readiness_dimensions": readiness_dimensions,
        "patient_scope": {
            "evaluated": evaluated,
            "scanned": scanned,
            "state_counts": patients.get("state_counts") or {},
            "decision_state_counts": patients.get("decision_state_counts") or {},
            "missing_fields_top": missing_pairs[:8],
            "sample_ref_hints": patients.get("sample_ref_hints") or [],
            "errors": patients.get("errors") or [],
        },
        "capture_plan": capture_plan,
        "contract": {
            "contract_id": contract.get("contract_id", "patient_twin_preference_pro_minimum"),
            "label": contract.get("label", "Patient Twin preference and PRO minimum"),
            "must_capture": contract.get("required_fields") or [
                "patient_values",
                "baseline_pro",
                "toxicity_tolerance",
                "decision_tradeoff",
                "redecision_threshold",
            ],
            "capture_surface": contract.get("capture_surface", "longitudinal-capture?decision_lane=patient_twin_readiness"),
            "persistence": contract.get("persistence", "patient_clinical_facts + PRO baseline + patient_events + data_provenance"),
            "consumer": contract.get("consumer", "Decision Today + Patient Twin + Clinical Memory OS"),
            "must_not_simulate_if": [
                "no_patient_values",
                "no_baseline_pro",
                "no_longitudinal_trajectory",
                "no_redecision_threshold",
                "no_traceable_provenance",
            ],
            "allowed_outputs": [
                "patient_twin_readiness_gap",
                "capture_plan",
                "readiness_metrics",
                "ai_readiness_input_gap",
            ],
            "forbidden_outputs": [
                "treatment_prediction",
                "survival_prediction",
                "recommendation_override",
                "autonomous_model_training",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_7a_evidence_shadow_loop": True,
            "automatic_simulation_allowed": False,
            "model_training_allowed": False,
            "prediction_release_allowed": False,
            "clinical_fact_writes_allowed": False,
            "requires_traceable_provenance": True,
            "requires_patient_consent_for_learning_dataset": True,
            "requires_human_review": True,
            "commands_executed": False,
            "files_modified": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "evidence_refresh_shadow_loop_ready": ready_7a,
            "has_patient_twin_contract": bool(contract),
            "has_readiness_dimensions": bool(readiness_dimensions),
            "has_capture_plan": bool(capture_plan),
            "no_predictions_released": True,
            "no_models_trained": True,
            "no_clinical_fact_mutation": True,
            "ready_for_9a_ai_readiness_dataset_loop": readiness_status == "ready_for_patient_twin_readiness_shadow_scan",
        },
        "audit": _audit_footer(),
    }


def build_ai_readiness_dataset_loop(
    *,
    patient_twin_readiness_loop: Mapping[str, Any] | None = None,
    gap_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 9A: AI readiness dataset audit without export, training or predictions."""
    twin_loop = dict(patient_twin_readiness_loop or build_patient_twin_readiness_loop())
    twin_summary = dict(twin_loop.get("summary") or {})
    ready_8a = bool(twin_summary.get("ready_for_shadow_scan"))

    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=20))
    context = dict(gaps.get("context") or {})
    patients = dict(context.get("patients") or context.get("patient_scan") or twin_loop.get("patient_scope") or {})
    evaluated = int(patients.get("evaluated") or 0)
    scanned = int(patients.get("scanned") or evaluated or 0)
    missing_pairs = list(patients.get("missing_fields_top") or [])
    state_counts = dict(patients.get("state_counts") or {})
    scope_estimate = max(scanned, evaluated)
    explicit_dataset_ready = bool(
        context.get("ai_readiness_dataset_available")
        or context.get("model_readiness_dataset_available")
        or context.get("learning_dataset_available")
    )

    dataset_gates: list[dict[str, Any]] = []
    for gate in AI_READINESS_DATASET_GATES:
        missing_count = _missing_count_for_aliases(missing_pairs, gate.get("field_aliases") or gate.get("required_fields") or [])
        if not ready_8a:
            status = "blocked_until_8a_ready"
        elif explicit_dataset_ready and missing_count <= 0 and scope_estimate > 0:
            status = "shadow_ready"
        else:
            status = "requires_data"
        dataset_gates.append({
            "gate_id": gate["gate_id"],
            "label": gate["label"],
            "required_fields": list(gate.get("required_fields") or []),
            "status": status,
            "missing_count_estimate": int(missing_count or (scope_estimate if status == "requires_data" else 0)),
            "patient_scope_estimate": scope_estimate,
            "risk_if_missing": gate["risk_if_missing"],
            "blocking": status != "shadow_ready",
        })

    blockers: list[str] = []
    if not ready_8a:
        blockers.append("patient_twin_readiness_loop_not_ready")
    if not dataset_gates:
        blockers.append("ai_readiness_dataset_gates_missing")

    if blockers:
        ai_readiness_status = "blocked_until_8a_ready"
        ai_readiness_gate = "blocked"
        next_phase = "8A_patient_twin_readiness_loop"
    else:
        ai_readiness_status = "ready_for_ai_readiness_shadow_audit"
        ai_readiness_gate = "dataset_contract_registered"
        next_phase = "10A_cortana_loop_interface"

    trainable_gate_count = sum(1 for gate in dataset_gates if gate.get("status") == "shadow_ready")
    blocked_gate_count = sum(1 for gate in dataset_gates if gate.get("status") != "shadow_ready")
    dominant = next((gate for gate in dataset_gates if gate.get("status") != "shadow_ready"), {})
    dataset_ready_for_export = False
    model_training_allowed = False
    prediction_release_allowed = False

    model_readiness_report = {
        "overall_status": "not_trainable_shadow_only",
        "sample_size_status": _dataset_gate_status(dataset_gates, "sample_size_by_state"),
        "consent_status": _dataset_gate_status(dataset_gates, "consent_governance"),
        "traceability_status": _dataset_gate_status(dataset_gates, "provenance_traceability"),
        "outcome_maturity_status": _dataset_gate_status(dataset_gates, "outcome_maturity"),
        "missingness_status": _dataset_gate_status(dataset_gates, "missingness_profile"),
        "leakage_risk_status": _dataset_gate_status(dataset_gates, "leakage_prevention"),
        "bias_risk_status": _dataset_gate_status(dataset_gates, "selection_bias_review"),
        "trainable_now": False,
        "reason": "9A sólo audita readiness; entrenamiento y predicciones siguen bloqueados hasta revisión humana, consentimiento, trazabilidad y outcomes maduros.",
    }

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "ai_readiness_dataset_loop_v1",
        "phase": "9A_ai_readiness_dataset_loop",
        "summary": {
            "mode": "shadow",
            "ai_readiness_status": ai_readiness_status,
            "ai_readiness_gate": ai_readiness_gate,
            "ready_for_shadow_audit": ai_readiness_status == "ready_for_ai_readiness_shadow_audit",
            "evaluated_patient_count": evaluated,
            "scanned_patient_count": scanned,
            "state_count": len(state_counts),
            "dataset_gate_count": len(dataset_gates),
            "shadow_ready_gate_count": trainable_gate_count,
            "blocked_gate_count": blocked_gate_count,
            "dominant_dataset_blocker": dominant.get("gate_id", ""),
            "model_readiness_score": _ai_readiness_score(dataset_gates, ready_8a=ready_8a),
            "dataset_export_allowed": dataset_ready_for_export,
            "dataset_export_written": False,
            "deidentified_dataset_written": False,
            "model_training_allowed": model_training_allowed,
            "model_training_executed": False,
            "models_trained": False,
            "prediction_release_allowed": prediction_release_allowed,
            "predictions_released": False,
            "recommendation_logic_mutated": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "dataset_gates": dataset_gates,
        "model_readiness_report": model_readiness_report,
        "read_only_dataset_manifest": {
            "dataset_name": "model_readiness_dataset_v1",
            "dataset_version": "shadow_contract_only",
            "rows_estimate": evaluated,
            "state_counts": state_counts,
            "feature_groups": [
                "clinical_state",
                "decision_episode",
                "psa_trajectory",
                "testosterone_trajectory",
                "treatment_exposure",
                "toxicity_and_pros",
                "patient_values",
                "provenance",
            ],
            "outcome_targets": [
                "time_to_new_decision",
                "psa_response",
                "progression",
                "toxicity_limited",
                "requires_redecision",
            ],
            "export_path": None,
            "manifest_hash": None,
            "export_written": False,
            "deidentified_dataset_written": False,
        },
        "cohort_readiness": {
            "minimum_state_cohort_size": 30,
            "states_observed": state_counts,
            "insufficient_state_cohorts": [
                {"state": state, "count": int(count)}
                for state, count in state_counts.items()
                if int(count or 0) < 30
            ],
            "insufficient_cohort_size": any(int(count or 0) < 30 for count in state_counts.values()) or not state_counts,
        },
        "capture_plan": [
            {
                "gate_id": gate["gate_id"],
                "label": gate["label"],
                "required_fields": gate["required_fields"],
                "status": gate["status"],
                "risk_if_missing": gate["risk_if_missing"],
                "cta": "/loop-monitor#pm2PatientTwinReadinessLoop",
            }
            for gate in dataset_gates
            if gate.get("status") != "shadow_ready"
        ],
        "contract": {
            "contract_id": "ai_readiness_dataset_shadow_contract",
            "must_have": [
                "learning_consent",
                "deidentification_ok",
                "feature_level_provenance",
                "event_time_alignment",
                "outcome_maturity",
                "missingness_profile",
                "selection_bias_review",
            ],
            "allowed_outputs": [
                "model_readiness_report",
                "read_only_dataset_manifest",
                "missingness_profile",
                "leakage_risk_report",
                "cohort_readiness_report",
            ],
            "forbidden_outputs": [
                "model_training",
                "treatment_prediction",
                "survival_prediction",
                "recommendation_override",
                "automatic_dataset_export",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_8a_patient_twin_readiness_loop": True,
            "dataset_export_allowed": False,
            "deidentified_dataset_write_allowed": False,
            "model_training_allowed": False,
            "prediction_release_allowed": False,
            "recommendation_override_allowed": False,
            "clinical_fact_writes_allowed": False,
            "requires_human_review": True,
            "requires_learning_consent": True,
            "requires_feature_level_provenance": True,
            "commands_executed": False,
            "files_modified": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "patient_twin_readiness_loop_ready": ready_8a,
            "has_dataset_gates": bool(dataset_gates),
            "has_model_readiness_report": bool(model_readiness_report),
            "no_dataset_export_written": True,
            "no_model_training": True,
            "no_predictions_released": True,
            "no_clinical_fact_mutation": True,
            "ready_for_10a_cortana_loop_interface": ai_readiness_status == "ready_for_ai_readiness_shadow_audit",
        },
        "audit": _audit_footer(),
    }


def build_cortana_loop_interface(
    *,
    ai_readiness_dataset_loop: Mapping[str, Any] | None = None,
    mission_control: Mapping[str, Any] | None = None,
    development_autodrive: Mapping[str, Any] | None = None,
    gap_bundle: Mapping[str, Any] | None = None,
    patient_twin_readiness_loop: Mapping[str, Any] | None = None,
    evidence_refresh_shadow_loop: Mapping[str, Any] | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Phase 10A: read-only Cortana interface for the autonomous improvement loop."""
    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=20))
    development = dict(development_autodrive or build_development_autodrive(gaps.get("candidates", [])))
    mission = dict(mission_control or build_mission_control(gap_bundle=gaps, development_autodrive=development))
    twin_loop = dict(patient_twin_readiness_loop or build_patient_twin_readiness_loop(gap_bundle=gaps))
    evidence_loop = dict(evidence_refresh_shadow_loop or build_evidence_refresh_shadow_loop())
    ai_loop = dict(ai_readiness_dataset_loop or build_ai_readiness_dataset_loop(
        patient_twin_readiness_loop=twin_loop,
        gap_bundle=gaps,
    ))
    ai_summary = dict(ai_loop.get("summary") or {})
    ready_9a = bool(ai_summary.get("ready_for_shadow_audit"))
    pipeline_complete = float((mission.get("summary") or {}).get("pipeline_maturity_pct") or 0.0) >= 100.0
    ready_for_consultation = ready_9a or pipeline_complete

    command_routes = [
        {
            **dict(command),
            "status": "available" if ready_for_consultation else "blocked_until_9a_ready",
            "write_allowed": False,
            "merge_allowed": False,
            "clinical_fact_write_allowed": False,
        }
        for command in CORTANA_LOOP_COMMAND_REGISTRY
    ]

    blockers: list[str] = []
    if not ready_for_consultation:
        blockers.append("ai_readiness_dataset_loop_not_ready")
    if not command_routes:
        blockers.append("cortana_loop_command_registry_missing")

    if blockers:
        cortana_status = "blocked_until_9a_ready"
        cortana_gate = "blocked"
        next_phase = "9A_ai_readiness_dataset_loop"
    else:
        cortana_status = "ready_for_consultative_loop_interface"
        cortana_gate = "consultative_interface_registered"
        next_phase = "continuous_shadow_operation"

    response_cards = _build_cortana_loop_response_cards(
        mission=mission,
        development=development,
        gaps=gaps,
        ai_loop=ai_loop,
        twin_loop=twin_loop,
        evidence_loop=evidence_loop,
    )
    resolved_response = _resolve_cortana_loop_query(
        query,
        command_routes=command_routes,
        response_cards=response_cards,
        default_cta="/loop-monitor#pm2CortanaLoopInterface",
    )

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "cortana_loop_interface_v1",
        "phase": "10A_cortana_loop_interface",
        "summary": {
            "mode": "shadow",
            "cortana_loop_status": cortana_status,
            "cortana_loop_gate": cortana_gate,
            "ready_for_loop_queries": cortana_status == "ready_for_consultative_loop_interface",
            "supported_command_count": len(command_routes),
            "response_card_count": len(response_cards),
            "clinical_goal_pct": (mission.get("summary") or {}).get("clinical_goal_pct", 0),
            "pipeline_maturity_pct": (mission.get("summary") or {}).get("pipeline_maturity_pct", 0),
            "top_gap_title": (mission.get("summary") or {}).get("top_gap_title", ""),
            "ai_readiness_status": ai_summary.get("ai_readiness_status", ""),
            "ai_readiness_has_active_gaps": not ready_9a,
            "patient_twin_readiness_status": (twin_loop.get("summary") or {}).get("patient_twin_readiness_status", ""),
            "evidence_refresh_status": (evidence_loop.get("summary") or {}).get("evidence_refresh_status", ""),
            "voice_write_allowed": False,
            "clinical_fact_writes_allowed": False,
            "code_mutation_allowed": False,
            "merge_allowed": False,
            "model_training_allowed": False,
            "prediction_release_allowed": False,
            "external_action_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
            "next_phase_suggested": next_phase,
        },
        "command_routes": command_routes,
        "response_cards": response_cards,
        "resolved_response": resolved_response,
        "interface_contract": {
            "contract_id": "cortana_autonomous_loop_interface_contract",
            "allowed_outputs": [
                "mission_status_summary",
                "dominant_gap_summary",
                "next_phase_explanation",
                "evidence_support_summary",
                "patient_twin_readiness_summary",
                "ai_readiness_summary",
                "safe_navigation_cta",
            ],
            "forbidden_outputs": [
                "clinical_fact_write",
                "code_mutation",
                "git_branch_creation",
                "pull_request_creation",
                "merge",
                "model_training",
                "dataset_export",
                "recommendation_override",
            ],
            "must_disclose": [
                "shadow_mode",
                "human_review_required",
                "no_automatic_clinical_action",
                "no_model_training",
                "no_code_mutation",
            ],
        },
        "blockers": blockers,
        "controls": {
            "requires_9a_ai_readiness_dataset_loop": True,
            "voice_write_allowed": False,
            "clinical_fact_writes_allowed": False,
            "code_mutation_allowed": False,
            "dataset_export_allowed": False,
            "model_training_allowed": False,
            "prediction_release_allowed": False,
            "recommendation_override_allowed": False,
            "external_action_allowed": False,
            "safe_navigation_allowed": True,
            "requires_human_review": True,
            "commands_executed": False,
            "files_modified": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "ai_readiness_dataset_loop_ready": ready_9a,
            "technical_roadmap_complete": pipeline_complete,
            "has_command_registry": bool(command_routes),
            "has_response_cards": bool(response_cards),
            "resolved_response_read_only": True,
            "no_clinical_fact_mutation": True,
            "no_code_mutation": True,
            "no_git_mutation": True,
            "roadmap_cycle_complete": cortana_status == "ready_for_consultative_loop_interface",
        },
        "audit": _audit_footer(),
    }


def build_continuous_shadow_operation(
    *,
    cortana_loop_interface: Mapping[str, Any] | None = None,
    mission_control: Mapping[str, Any] | None = None,
    development_autodrive: Mapping[str, Any] | None = None,
    gap_bundle: Mapping[str, Any] | None = None,
    proposals: Mapping[str, Any] | None = None,
    shadow_pr_factory: Mapping[str, Any] | None = None,
    safety_gate_runner: Mapping[str, Any] | None = None,
    shadow_execution_artifacts: Mapping[str, Any] | None = None,
    agent_consensus_synthesizer: Mapping[str, Any] | None = None,
    implementation_brief: Mapping[str, Any] | None = None,
    shadow_patch_blueprint: Mapping[str, Any] | None = None,
    human_patch_authorization: Mapping[str, Any] | None = None,
    required_safety_gate_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Continuous post-roadmap operation: choose one real gap and request human control.

    This read-model intentionally does not execute commands, create branches, open
    PRs, run visual automation, or mutate clinical facts. It packages the next
    small shadow cycle so a human can authorize the controlled local workflow.
    """
    gaps = dict(gap_bundle or build_gap_intelligence(patient_limit=20))
    development = dict(development_autodrive or build_development_autodrive(gaps.get("candidates", [])))
    mission = dict(mission_control or build_mission_control(gap_bundle=gaps, development_autodrive=development))
    cortana = dict(cortana_loop_interface or build_cortana_loop_interface(
        mission_control=mission,
        development_autodrive=development,
        gap_bundle=gaps,
    ))
    shadow = dict(shadow_pr_factory or build_shadow_pr_factory(
        development_autodrive=development,
        proposals=proposals or build_proposals(gaps.get("candidates", [])),
    ))
    safety = dict(safety_gate_runner or build_safety_gate_runner(shadow_pr_factory=shadow))
    artifacts = dict(shadow_execution_artifacts or build_shadow_execution_artifacts(safety_gate_runner=safety))
    blueprint = dict(shadow_patch_blueprint or build_shadow_patch_blueprint(
        implementation_brief=implementation_brief or build_agent_implementation_brief(
            agent_consensus_synthesizer=agent_consensus_synthesizer or build_agent_consensus_synthesizer(
                development_autodrive=development,
            )
        )
    ))
    authorization = dict(human_patch_authorization or build_human_patch_authorization(
        shadow_patch_blueprint=blueprint,
    ))
    required_contract = dict(required_safety_gate_contract or build_required_safety_gate_contract())

    selected = dict((development.get("summary") or {}).get("selected_improvement") or {})
    selected_id = str(selected.get("id") or "")
    ready_10a = bool((cortana.get("quality_gate") or {}).get("roadmap_cycle_complete"))
    safety_release_ready = (safety.get("summary") or {}).get("release_gate") == "ready_for_human_review"
    blueprint_ready = bool((blueprint.get("quality_gate") or {}).get("ready_for_human_patch_authorization"))
    auth_summary = dict(authorization.get("summary") or {})
    authorization_state = str(auth_summary.get("authorization_state") or "pending_human_authorization")

    blockers: list[str] = []
    if not ready_10a:
        blockers.append("cortana_loop_interface_not_ready")
    if not selected_id:
        blockers.append("no_actionable_gap_selected")
    if not safety_release_ready:
        blockers.append("safety_gates_not_ready")
    if not blueprint_ready:
        blockers.append("shadow_patch_blueprint_not_ready")

    if not ready_10a:
        continuous_status = "blocked_until_10a_ready"
        cycle_gate = "blocked"
        next_step = "10A_cortana_loop_interface"
    elif not selected_id:
        continuous_status = "no_actionable_gap"
        cycle_gate = "watchlist"
        next_step = "gap_intelligence_recompute"
    elif blockers:
        continuous_status = "blocked_by_shadow_cycle_contract"
        cycle_gate = "blocked"
        next_step = "resolve_shadow_cycle_blockers"
    elif authorization_state == "authorized_for_controlled_patch":
        continuous_status = "authorized_pending_controlled_application"
        cycle_gate = "authorized_for_controlled_patch"
        next_step = "4G_controlled_patch_application"
    else:
        continuous_status = "awaiting_human_authorization"
        cycle_gate = "human_authorization_required"
        next_step = "human_patch_authorization_decision"

    package = dict(shadow.get("package") or {})
    validation_plan = dict(package.get("validation_plan") or {})
    implementation_plan = dict(package.get("implementation_plan") or {})
    visual_routes = list(validation_plan.get("visual_validation") or safety.get("required_visual_routes") or ["/loop-monitor"])
    test_commands = list(validation_plan.get("test_commands") or safety.get("required_test_commands") or [])
    cycle_id = _continuous_shadow_cycle_id(selected_id, package)

    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "continuous_shadow_operation_v1",
        "phase": "continuous_shadow_operation",
        "summary": {
            "mode": "shadow",
            "continuous_status": continuous_status,
            "cycle_gate": cycle_gate,
            "cycle_id": cycle_id,
            "selected_gap_id": selected_id,
            "selected_gap_title": selected.get("title", ""),
            "selected_gap_lane": selected.get("lane", ""),
            "one_change_per_cycle": True,
            "safety_release_ready": safety_release_ready,
            "visual_validation_required": bool(visual_routes),
            "ready_for_human_authorization": cycle_gate in {"human_authorization_required", "authorized_for_controlled_patch"},
            "human_authorization_state": authorization_state,
            "next_step": next_step,
            "commands_executed": False,
            "files_modified": False,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "branch_created": False,
            "pull_request_created": False,
            "merge_performed": False,
            "auto_merge_allowed": False,
        },
        "selected_gap": selected,
        "cycle_packet": {
            "cycle_id": cycle_id,
            "selected_gap_id": selected_id,
            "hypothesis": selected.get("description", ""),
            "risk_avoided": selected.get("risk_avoided", ""),
            "minimal_change": implementation_plan.get("minimal_change") or _minimal_change_for(selected),
            "one_change_scope": "exactly_one_candidate_per_cycle",
            "file_targets": implementation_plan.get("file_targets", []),
            "tests_required": selected.get("tests_required", []),
            "rollback": package.get("rollback_plan") or selected.get("rollback") or "Reject this cycle; no code or clinical data was changed.",
            "evidence": selected.get("evidence", []),
            "source_bundles": [
                "gap_intelligence",
                "development_autodrive",
                "shadow_pr_factory",
                "safety_gate_runner",
                "shadow_patch_blueprint",
                "human_patch_authorization",
            ],
        },
        "minimal_change_proposal": {
            "title": (package.get("draft_pr") or {}).get("title", selected.get("title", "")),
            "branch_name_proposed": (package.get("draft_pr") or {}).get("branch_name", ""),
            "create_branch_now": False,
            "create_pr_now": False,
            "auto_merge_allowed": False,
            "human_review_required": True,
            "implementation_plan": implementation_plan,
        },
        "safety_gate_plan": {
            "release_gate": (safety.get("summary") or {}).get("release_gate", "blocked"),
            "gate_count": (safety.get("summary") or {}).get("gate_count", 0),
            "passed": (safety.get("summary") or {}).get("passed", 0),
            "blocked": (safety.get("summary") or {}).get("blocked", 0),
            "gates": safety.get("gates", []),
            "required_test_commands": test_commands,
            "required_safety_contract_status": (required_contract.get("summary") or {}).get("safety_contract_status", ""),
            "anti_fallback": safety.get("anti_fallback", {}),
        },
        "visual_validation_plan": {
            "status": (artifacts.get("summary") or {}).get("artifact_status", "pending_execution"),
            "required": bool(visual_routes),
            "routes": visual_routes,
            "viewports": ["1440x696", "1180x760", "827x814", "390x844"],
            "evidence_required": [
                "desktop_browser_validation",
                "mobile_browser_validation",
                "no_console_errors",
                "no_overlap_or_demo_data_regression",
            ],
        },
        "human_authorization_request": {
            "endpoint": "/api/autonomous-improvement/human-patch-authorization/decision",
            "method": "POST",
            "authorization_state": authorization_state,
            "allowed_decisions": ["authorize_patch", "hold", "reject"],
            "payload_template": {
                "decision": "authorize_patch|hold|reject",
                "reviewer": "<human_reviewer>",
                "note": "Why this exact one-change shadow cycle is safe or blocked.",
            },
            "requires_human_authorization": True,
            "patch_application_allowed_now": authorization_state == "authorized_for_controlled_patch",
        },
        "blockers": blockers,
        "controls": {
            "shadow_mode_only": True,
            "one_change_per_cycle": True,
            "clinical_fact_writes_allowed": False,
            "commands_executed": False,
            "files_modified": False,
            "git_mutation_allowed": False,
            "branch_creation_allowed": False,
            "pull_request_creation_allowed": False,
            "merge_allowed": False,
            "auto_merge_allowed": False,
        },
        "quality_gate": {
            "cortana_loop_interface_ready": ready_10a,
            "has_selected_gap": bool(selected_id),
            "safety_release_ready": safety_release_ready,
            "shadow_patch_blueprint_ready": blueprint_ready,
            "human_authorization_required": True,
            "no_clinical_fact_mutation": True,
            "no_code_mutation": True,
            "no_git_mutation": True,
        },
        "audit": _audit_footer(),
    }


def recompute_shadow_bundle(*, patient_limit: int = 35) -> dict[str, Any]:
    """Explicit recompute endpoint payload. It never mutates source facts."""
    bundle = build_autonomous_improvement_bundle(patient_limit=patient_limit)
    bundle["source_clinical_facts_mutated"] = False
    bundle["proposal_store_mutated"] = False
    bundle["mode"] = "shadow"
    return bundle


def rank_candidates(candidates: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Deterministic scoring for Development Autodrive."""
    ranked = []
    for raw in candidates or []:
        candidate = validate_candidate(dict(raw))
        score, breakdown = _score_candidate(candidate)
        candidate["priority_score"] = score
        candidate["score_breakdown"] = breakdown
        candidate["priority_class"] = _priority_class(score, candidate)
        ranked.append(candidate)
    return sorted(
        ranked,
        key=lambda c: (
            -float(c.get("priority_score") or 0),
            -int(c.get("severity") or 0),
            str(c.get("title") or ""),
        ),
    )


def _score_candidate(candidate: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    """Explainable Development Autodrive score for one candidate."""
    effort = max(float(candidate.get("effort_h") or 1.0), 0.25)
    affected = int((candidate.get("patient_scope") or {}).get("affected_count") or 0)
    has_decision_block = _candidate_blocks_decision_today(candidate)
    has_contradiction = bool(candidate.get("contradictions"))
    has_contract_gap = bool(candidate.get("contract_gaps") or candidate.get("clinical_contract"))
    severity_component = float(candidate.get("severity") or 0) * 2.0
    impact_component = float(candidate.get("clinical_impact") or 0) * 1.8
    lane_component = _lane_weight(str(candidate.get("lane") or ""))
    status_component = _status_weight(str(candidate.get("status") or ""))
    review_component = _review_weight(candidate)
    scope_component = min(8.0, affected * 0.8)
    decision_component = 7.0 if has_contradiction else 4.5 if has_decision_block else 2.0 if has_contract_gap else 0.0
    safety_component = 5.0 if candidate.get("lane") == "safety_security_gap" else 0.0
    evidence_component = min(3.0, len(candidate.get("evidence") or []) * 0.75) + min(3.0, len(candidate.get("tests_required") or []) * 0.75)
    clinical_priority = (
        severity_component
        + impact_component
        + scope_component
        + decision_component
        + safety_component
    )
    raw_score = (
        severity_component
        + impact_component
        + lane_component
        + status_component
        + review_component
        + scope_component
        + decision_component
        + safety_component
        + evidence_component
    )
    blocker_penalty = 0.62 if candidate.get("blockers") else 1.0
    effort_divisor = _effort_divisor(candidate, effort, has_decision_block, has_contradiction, has_contract_gap)
    final_score = round((raw_score / effort_divisor) * blocker_penalty, 2)
    return final_score, {
        "clinical_severity": round(severity_component, 2),
        "clinical_impact": round(impact_component, 2),
        "lane_weight": round(lane_component, 2),
        "status_weight": round(status_component, 2),
        "review_weight": round(review_component, 2),
        "patient_scope": round(scope_component, 2),
        "decision_today_blocking": round(decision_component, 2),
        "safety_security": round(safety_component, 2),
        "evidence_traceability": round(evidence_component, 2),
        "clinical_priority": round(clinical_priority, 2),
        "execution_fit": round(10.0 / max(effort_divisor, 0.25), 2),
        "effort_h": effort,
        "effort_divisor": round(effort_divisor, 2),
        "effort_penalty_model": "capped_clinical_divisor",
        "blocker_penalty": blocker_penalty,
        "raw_score": round(raw_score, 2),
        "final_score": final_score,
    }


def _candidate_is_clinical_priority(candidate: Mapping[str, Any]) -> bool:
    lane = str(candidate.get("lane") or "")
    return (
        lane == "critical_clinical_gap"
        or bool(candidate.get("clinical_contract"))
        or bool(candidate.get("contract_gaps"))
        or bool(candidate.get("contradictions"))
        or (lane == "data_integrity_gap" and _candidate_blocks_decision_today(candidate))
    )


def _candidate_score_card(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {}
    breakdown = dict(candidate.get("score_breakdown") or {})
    return {
        "id": candidate.get("id", ""),
        "title": candidate.get("title", ""),
        "lane": candidate.get("lane", ""),
        "status": candidate.get("status", ""),
        "priority_score": candidate.get("priority_score", 0),
        "priority_class": candidate.get("priority_class", ""),
        "clinical_priority": breakdown.get("clinical_priority", 0),
        "execution_fit": breakdown.get("execution_fit", 0),
        "effort_h": breakdown.get("effort_h", candidate.get("effort_h", 0)),
        "effort_divisor": breakdown.get("effort_divisor", 0),
        "effort_penalty_model": breakdown.get("effort_penalty_model", ""),
        "decision_today_blocking": breakdown.get("decision_today_blocking", 0),
        "patient_scope": breakdown.get("patient_scope", 0),
        "raw_score": breakdown.get("raw_score", 0),
        "is_clinical_priority": _candidate_is_clinical_priority(candidate),
    }


def _effort_divisor(
    candidate: Mapping[str, Any],
    effort: float,
    has_decision_block: bool,
    has_contradiction: bool,
    has_contract_gap: bool,
) -> float:
    """Bound effort so high-value clinical gaps are not structurally buried.

    Effort is still a real execution-fit signal, but it must not divide away
    clinical severity, Decision Today blockage, patient scope or safety risk.
    """
    lane = str(candidate.get("lane") or "")
    divisor = min(max(effort, 0.25), 3.0)
    if lane == "critical_clinical_gap" or has_decision_block or has_contradiction or has_contract_gap:
        divisor = min(divisor, 2.5)
    return divisor


def _candidate_actionable(candidate: Mapping[str, Any]) -> bool:
    status = str(candidate.get("status") or "")
    return status in {"proposal_ready", "human_review_required"} and not candidate.get("blockers")


def _selected_reason(candidate: Mapping[str, Any]) -> str:
    if not candidate:
        return "No actionable improvement candidate is currently available."
    pieces = []
    lane = str(candidate.get("lane") or "").replace("_", " ")
    if lane:
        pieces.append(lane)
    pieces.append(f"score {candidate.get('priority_score', 0)}")
    if candidate.get("contradictions"):
        pieces.append("active clinical contradiction")
    elif candidate.get("contract_gaps"):
        pieces.append("contractual clinical gap")
    elif _candidate_blocks_decision_today(candidate):
        pieces.append("Decision Today blocker")
    return "Selected because it is the highest-ranked actionable candidate: " + ", ".join(pieces) + "."


def _selected_iteration_plan(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not candidate:
        return {
            "available": False,
            "mode": "shadow",
            "one_change_per_iteration": True,
            "reason": "No actionable candidate passed safety gates.",
        }
    return {
        "available": True,
        "mode": "shadow",
        "candidate_id": candidate.get("id", ""),
        "title": candidate.get("title", ""),
        "lane": candidate.get("lane", ""),
        "agent_lane": candidate.get("agent_lane", ""),
        "priority_score": candidate.get("priority_score", 0),
        "priority_class": candidate.get("priority_class", ""),
        "score_breakdown": candidate.get("score_breakdown", {}),
        "minimal_change": _minimal_change_for(candidate),
        "tests_required": candidate.get("tests_required", []),
        "rollback": candidate.get("rollback") or "Reject candidate or revert the next small patch.",
        "acceptance": _acceptance_for(candidate),
        "one_change_per_iteration": True,
        "clinical_fact_writes_allowed": False,
        "auto_merge_allowed": False,
        "human_review_required": True,
    }


def _continuous_shadow_cycle_id(selected_id: str, package: Mapping[str, Any]) -> str:
    source = "|".join([
        str(selected_id or "no_candidate"),
        str((package.get("draft_pr") or {}).get("branch_name") or ""),
        str((package.get("implementation_plan") or {}).get("minimal_change") or ""),
    ])
    return "cso-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _priority_class(score: float, candidate: Mapping[str, Any]) -> str:
    if candidate.get("blockers"):
        return "deferred_blocked"
    if score >= 32:
        return "critical_clinical_gap"
    if score >= 18:
        return "high_today"
    if score >= 10:
        return "routine_today"
    return "watchlist"


def _candidate_blocks_decision_today(candidate: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "description", "risk_avoided", "source")
    ).lower()
    return (
        "decision today" in text
        or "decision hoy" in text
        or bool(candidate.get("contract_gaps"))
        or bool(candidate.get("contradictions"))
    )


def _build_shadow_pr_package(
    candidate: Mapping[str, Any],
    proposal: Mapping[str, Any],
    development: Mapping[str, Any],
) -> dict[str, Any]:
    branch_name = f"codex/autodrive-{_sanitize_branch_slug(candidate.get('title') or candidate.get('id'))}-{str(candidate.get('id') or '')[:8]}"
    file_targets = _shadow_file_targets(candidate, proposal)
    test_commands = _shadow_test_commands(candidate, proposal, file_targets)
    safety_report = _shadow_safety_report(candidate, proposal, file_targets, test_commands)
    draft_pr = {
        "title": f"[Shadow] {candidate.get('title', 'Autonomous improvement')}",
        "branch_name": branch_name,
        "base_branch": "main",
        "labels": list(SHADOW_PR_LABELS),
        "is_draft": True,
        "create_branch_now": False,
        "create_pr_now": False,
        "auto_merge_allowed": False,
        "human_review_required": True,
        "body": _shadow_pr_body(candidate, proposal, file_targets, test_commands, safety_report),
    }
    return {
        "candidate": {
            "id": candidate.get("id"),
            "title": candidate.get("title"),
            "lane": candidate.get("lane"),
            "agent_lane": candidate.get("agent_lane"),
            "priority_score": candidate.get("priority_score", 0),
            "priority_class": candidate.get("priority_class", ""),
            "score_breakdown": candidate.get("score_breakdown", {}),
        },
        "draft_pr": draft_pr,
        "implementation_plan": {
            "minimal_change": proposal.get("minimal_change") or _minimal_change_for(candidate),
            "file_targets": file_targets,
            "one_change_per_iteration": True,
            "clinical_scope": _clinical_scope_for(candidate),
            "non_goals": [
                "No clinical fact mutation",
                "No database migration unless a later reviewed proposal explicitly proves it is necessary",
                "No recommendation release without tests and human review",
                "No auto-merge",
            ],
        },
        "validation_plan": {
            "test_commands": test_commands,
            "acceptance": list(proposal.get("acceptance") or _acceptance_for(candidate)),
            "visual_validation": _shadow_visual_targets(candidate),
            "security_checks": [
                "Confirm no PHI in logs/artifacts",
                "Confirm source_clinical_facts_mutated=false",
                "Confirm no fabricated PSA/testosterone/treatment/trial eligibility",
            ],
        },
        "rollback_plan": proposal.get("rollback") or candidate.get("rollback") or "Reject the shadow proposal; no branch or clinical data has been changed.",
        "evidence_packet": {
            "evidence": list(proposal.get("evidence") or candidate.get("evidence") or []),
            "clinical_contract": dict(proposal.get("clinical_contract") or candidate.get("clinical_contract") or {}),
            "contract_gaps": list(proposal.get("contract_gaps") or candidate.get("contract_gaps") or []),
            "contradictions": list(proposal.get("contradictions") or candidate.get("contradictions") or []),
        },
        "safety_report": safety_report,
        "development_autodrive_context": {
            "phase": development.get("phase", ""),
            "selected_reason": (development.get("summary") or {}).get("selected_reason", ""),
            "selection_guardrails": development.get("selection_guardrails", {}),
        },
    }


def _shadow_file_targets(candidate: Mapping[str, Any], proposal: Mapping[str, Any]) -> list[dict[str, Any]]:
    surfaces = {str(item).lower() for item in (candidate.get("surfaces") or [])}
    text = " ".join(sorted(surfaces) + [str(candidate.get("source") or ""), str(candidate.get("title") or "")]).lower()
    targets: list[dict[str, Any]] = [
        {
            "path": "prostanet/agentic/autonomous_improvement_os.py",
            "reason": "Autonomous improvement proposal, scoring, safety or shadow PR packaging.",
            "write_scope": "read-model only",
        },
        {
            "path": "tests/test_autonomous_improvement_os.py",
            "reason": "Regression contract for the selected autonomous improvement behavior.",
            "write_scope": "tests only",
        },
    ]
    mapping = [
        ("decision", "prostanet/domains/patient_tracking/clinical_decision_today_fusion_kernel.py", "Canonical Decision Today alignment."),
        ("autodrive", "prostanet/domains/patient_tracking/clinical_autodrive_command_center.py", "Population/patient prioritization alignment."),
        ("readiness", "prostanet/domains/patient_tracking/clinical_readiness_tower.py", "Clinical readiness blockers and capture plan."),
        ("tumor", "prostanet/domains/patient_tracking/tumor_board_os.py", "Comparative option release state."),
        ("care_pathway", "prostanet/domains/patient_tracking/care_pathway_os.py", "Execution action status and audit trail."),
        ("memory", "prostanet/domains/patient_tracking/clinical_memory_os.py", "Outcome/redecision memory alignment."),
        ("clinical-field-router", "prostanet/presentation/clinical_field_router.py", "Capture surface routing for missing fields."),
        ("longitudinal", "templates/demos/longitudinal_capture_v2_demo.html", "Longitudinal capture CTA and visual route."),
        ("dashboard", "templates/demos/clinical_dashboard_v2_demo.html", "Dashboard summary alignment."),
        ("patients", "templates/patients_v2.html", "Patients table compact signal alignment."),
        ("profile", "templates/patient_profile_v2.html", "Patient profile Decision Today/readiness display."),
        ("voice", "static/js/prostamed_voice_os.js", "Cortana command/query integration."),
        ("security", "prostanet/shared/security_middleware.py", "Security/PHI/header safety control."),
        ("loop", "templates/loop_monitor_dashboard.html", "Loop Monitor visibility of the improvement package."),
    ]
    for token, path, reason in mapping:
        if token in text:
            targets.append({"path": path, "reason": reason, "write_scope": "minimal targeted patch"})
    for test_name in proposal.get("tests_required") or candidate.get("tests_required") or []:
        guessed = _guess_test_file(str(test_name))
        if guessed:
            targets.append({"path": guessed, "reason": f"Test target for {test_name}.", "write_scope": "tests only"})
    return _dedupe_target_rows(targets)


def _shadow_test_commands(
    candidate: Mapping[str, Any],
    proposal: Mapping[str, Any],
    file_targets: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    paths = {str(row.get("path") or "") for row in file_targets}
    commands = [
        {
            "cmd": "python3 -m py_compile prostanet/agentic/autonomous_improvement_os.py",
            "purpose": "Verify the autonomous improvement package compiles.",
        },
        {
            "cmd": "pytest -q tests/test_autonomous_improvement_os.py",
            "purpose": "Verify shadow loop, proposal safety and PR factory contracts.",
        },
    ]
    test_map = {
        "clinical_decision_today_fusion_kernel.py": "pytest -q tests/test_decision_today_fusion_kernel.py",
        "clinical_autodrive_command_center.py": "pytest -q tests/test_clinical_autodrive_command_center.py",
        "clinical_readiness_tower.py": "pytest -q tests/test_clinical_readiness_tower.py",
        "tumor_board_os.py": "pytest -q tests/test_tumor_board_os.py",
        "care_pathway_os.py": "pytest -q tests/test_care_pathway_os.py",
        "clinical_memory_os.py": "pytest -q tests/test_clinical_memory_os.py",
        "clinical_field_router.py": "pytest -q tests/test_clinical_field_router_closure.py",
        "prostamed_voice_os.js": "pytest -q tests/test_voice_clinical_os.py",
    }
    for key, command in test_map.items():
        if any(path.endswith(key) for path in paths):
            commands.append({"cmd": command, "purpose": f"Regression for {key}."})
    commands.append({
        "cmd": (
            "pytest -q tests/test_autonomous_improvement_os.py "
            "tests/test_decision_today_fusion_kernel.py "
            "tests/test_clinical_autodrive_command_center.py "
            "tests/test_clinical_readiness_tower.py "
            "tests/test_tumor_board_os.py "
            "tests/test_care_pathway_os.py "
            "tests/test_clinical_memory_os.py "
            "tests/test_clinical_field_router_closure.py "
            "tests/test_voice_clinical_os.py"
        ),
        "purpose": "Core clinical regression before human review.",
    })
    for test_name in proposal.get("tests_required") or candidate.get("tests_required") or []:
        guessed = _guess_test_file(str(test_name))
        if guessed:
            commands.append({"cmd": f"pytest -q {guessed}", "purpose": f"Required test family for {test_name}."})
    return _dedupe_command_rows(commands)


def _shadow_safety_report(
    candidate: Mapping[str, Any],
    proposal: Mapping[str, Any],
    file_targets: Iterable[Mapping[str, Any]],
    test_commands: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    blockers = list(candidate.get("blockers") or [])
    missing = []
    if not (proposal.get("evidence") or candidate.get("evidence")):
        missing.append("evidence")
    if not (proposal.get("tests_required") or candidate.get("tests_required")):
        missing.append("tests")
    if not (proposal.get("rollback") or candidate.get("rollback")):
        missing.append("rollback")
    release_gate = "ready_for_human_review" if not blockers and not missing else "blocked"
    return {
        "release_gate": release_gate,
        "blockers": blockers,
        "missing_package_parts": missing,
        "source_clinical_facts_mutated": False,
        "clinical_fact_writes_allowed": False,
        "database_migration_allowed": False,
        "external_orders_allowed": False,
        "auto_merge_allowed": False,
        "raw_phi_allowed_in_artifacts": False,
        "no_fabricated_psa": True,
        "no_fabricated_testosterone": True,
        "no_fabricated_treatments": True,
        "no_fabricated_trial_eligibility": True,
        "human_review_required": True,
        "file_target_count": len(list(file_targets)),
        "test_command_count": len(list(test_commands)),
    }


def _shadow_pr_body(
    candidate: Mapping[str, Any],
    proposal: Mapping[str, Any],
    file_targets: Iterable[Mapping[str, Any]],
    test_commands: Iterable[Mapping[str, Any]],
    safety_report: Mapping[str, Any],
) -> str:
    files = "\n".join(f"- `{row.get('path')}`: {row.get('reason')}" for row in file_targets)
    tests = "\n".join(f"- `{row.get('cmd')}`: {row.get('purpose')}" for row in test_commands)
    acceptance = "\n".join(f"- {item}" for item in (proposal.get("acceptance") or _acceptance_for(candidate)))
    evidence = "\n".join(f"- {item}" for item in (proposal.get("evidence") or candidate.get("evidence") or []))
    return (
        "## Shadow PR Package\n"
        f"Candidate: `{candidate.get('id')}`\n\n"
        f"### Hypothesis\n{proposal.get('hypothesis') or candidate.get('description')}\n\n"
        f"### Minimal Change\n{proposal.get('minimal_change') or _minimal_change_for(candidate)}\n\n"
        "### Target Files\n"
        f"{files or '- No file targets inferred yet.'}\n\n"
        "### Validation\n"
        f"{tests or '- No tests inferred yet.'}\n\n"
        "### Acceptance\n"
        f"{acceptance or '- Human review required.'}\n\n"
        "### Evidence\n"
        f"{evidence or '- Evidence required before implementation.'}\n\n"
        "### Safety\n"
        f"- Release gate: `{safety_report.get('release_gate')}`\n"
        "- No clinical fact writes\n"
        "- No external orders\n"
        "- No auto-merge\n"
        "- No fabricated PSA/testosterone/treatment/trial eligibility\n\n"
        f"### Rollback\n{proposal.get('rollback') or candidate.get('rollback') or 'Reject the shadow proposal.'}\n"
    )


def _build_safety_gate_rows(shadow: Mapping[str, Any], package: Mapping[str, Any]) -> list[dict[str, Any]]:
    draft = dict(package.get("draft_pr") or {})
    implementation = dict(package.get("implementation_plan") or {})
    validation = dict(package.get("validation_plan") or {})
    safety = dict(package.get("safety_report") or {})
    evidence = dict(package.get("evidence_packet") or {})
    file_targets = list(implementation.get("file_targets") or [])
    test_commands = list(validation.get("test_commands") or [])
    visual_routes = list(validation.get("visual_validation") or [])
    checks = list(validation.get("security_checks") or [])
    gates = [
        _gate(
            "shadow_package_available",
            "Shadow PR package exists",
            bool(package and shadow.get("available")),
            evidence=["Package is present" if package else "Package missing"],
            blocks_release=True,
        ),
        _gate(
            "no_git_mutation",
            "No branch/PR/git mutation",
            draft.get("create_branch_now") is False
            and draft.get("create_pr_now") is False
            and draft.get("auto_merge_allowed") is False,
            evidence=[
                f"create_branch_now={draft.get('create_branch_now')}",
                f"create_pr_now={draft.get('create_pr_now')}",
                f"auto_merge_allowed={draft.get('auto_merge_allowed')}",
            ],
            blocks_release=True,
        ),
        _gate(
            "no_clinical_fact_mutation",
            "No clinical facts, external orders or DB migration",
            safety.get("source_clinical_facts_mutated") is False
            and safety.get("clinical_fact_writes_allowed") is False
            and safety.get("external_orders_allowed") is False
            and safety.get("database_migration_allowed") is False,
            evidence=[
                f"source_clinical_facts_mutated={safety.get('source_clinical_facts_mutated')}",
                f"clinical_fact_writes_allowed={safety.get('clinical_fact_writes_allowed')}",
                f"external_orders_allowed={safety.get('external_orders_allowed')}",
                f"database_migration_allowed={safety.get('database_migration_allowed')}",
            ],
            blocks_release=True,
        ),
        _gate(
            "evidence_present",
            "Evidence packet present",
            bool(evidence.get("evidence")),
            evidence=evidence.get("evidence") or ["No evidence in package"],
            blocks_release=True,
        ),
        _gate(
            "tests_declared",
            "Required tests declared",
            bool(test_commands) and any("tests/test_autonomous_improvement_os.py" in str(row.get("cmd") or "") for row in test_commands),
            evidence=[str(row.get("cmd") or "") for row in test_commands[:8]] or ["No test commands"],
            blocks_release=True,
        ),
        _gate(
            "core_regression_declared",
            "Core clinical regression declared",
            any("test_decision_today_fusion_kernel.py" in str(row.get("cmd") or "") for row in test_commands)
            and any("test_clinical_autodrive_command_center.py" in str(row.get("cmd") or "") for row in test_commands),
            evidence=[str(row.get("cmd") or "") for row in test_commands[-3:]] or ["No core regression command"],
            blocks_release=True,
        ),
        _gate(
            "rollback_present",
            "Rollback path present",
            bool(str(package.get("rollback_plan") or "").strip()),
            evidence=[str(package.get("rollback_plan") or "Rollback missing")],
            blocks_release=True,
        ),
        _gate(
            "anti_fallback_assertions",
            "Anti-fallback clinical fabrication checks",
            all(_safety_bool(package, key) for key in (
                "no_fabricated_psa",
                "no_fabricated_testosterone",
                "no_fabricated_treatments",
                "no_fabricated_trial_eligibility",
            )),
            evidence=[
                f"no_fabricated_psa={_safety_bool(package, 'no_fabricated_psa')}",
                f"no_fabricated_testosterone={_safety_bool(package, 'no_fabricated_testosterone')}",
                f"no_fabricated_treatments={_safety_bool(package, 'no_fabricated_treatments')}",
                f"no_fabricated_trial_eligibility={_safety_bool(package, 'no_fabricated_trial_eligibility')}",
            ],
            blocks_release=True,
        ),
        _gate(
            "phi_artifact_control",
            "No raw PHI in artifacts",
            safety.get("raw_phi_allowed_in_artifacts") is False
            and any("PHI" in str(item) for item in checks),
            evidence=checks or ["No security checks declared"],
            blocks_release=True,
        ),
        _gate(
            "visual_validation_declared",
            "Visual validation targets declared",
            bool(visual_routes),
            evidence=visual_routes or ["No visual routes"],
            blocks_release=False,
        ),
        _gate(
            "small_patch_scope",
            "Small patch scope",
            0 < len(file_targets) <= 14,
            evidence=[f"file_target_count={len(file_targets)}"],
            blocks_release=True,
        ),
        _gate(
            "human_review_required",
            "Human review remains required",
            draft.get("is_draft") is True and draft.get("human_review_required") is True,
            evidence=[f"is_draft={draft.get('is_draft')}", f"human_review_required={draft.get('human_review_required')}"],
            blocks_release=True,
        ),
    ]
    return gates


def _gate(
    gate_id: str,
    label: str,
    passed: bool,
    *,
    evidence: Iterable[Any] | None = None,
    blocks_release: bool = True,
) -> dict[str, Any]:
    status = "passed" if passed else "blocked" if blocks_release else "requires_human_review"
    return {
        "gate_id": gate_id,
        "label": label,
        "status": status,
        "blocks_release": bool(blocks_release),
        "evidence": [_redact_phi_like(str(item)) for item in (evidence or []) if str(item or "").strip()][:12],
    }


def _safety_bool(package: Mapping[str, Any], key: str) -> bool:
    safety = dict((package or {}).get("safety_report") or {})
    return safety.get(key) is True


def _shadow_execution_fingerprint(safety: Mapping[str, Any]) -> str:
    payload = {
        "phase": safety.get("phase"),
        "release_gate": (safety.get("summary") or {}).get("release_gate"),
        "commands": [row.get("cmd") for row in safety.get("required_test_commands") or []],
        "visual_routes": list(safety.get("required_visual_routes") or []),
        "gates": [
            {
                "gate_id": row.get("gate_id"),
                "status": row.get("status"),
            }
            for row in safety.get("gates") or []
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shadow_execution_dir() -> Path:
    return PERSISTENCE_DIR / SHADOW_EXECUTION_ARTIFACTS_DIRNAME


def _load_latest_shadow_execution_artifact(fingerprint: str) -> dict[str, Any]:
    directory = _shadow_execution_dir()
    if not directory.exists():
        return {}
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        controls = dict(payload.get("artifact_controls") or {})
        audit = dict(payload.get("audit") or {})
        if controls.get("source_safety_fingerprint") == fingerprint or audit.get("source_safety_fingerprint") == fingerprint:
            payload.setdefault("audit", {})
            payload["audit"]["artifact_path"] = _project_relative_path(path)
            payload["audit"]["persisted"] = True
            return payload
    return {}


def _persist_shadow_execution_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(artifact))
    directory = _shadow_execution_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = str((payload.get("artifact_controls") or {}).get("source_safety_fingerprint") or _stable_id(_now_iso()))
    filename = f"{_now_iso().replace(':', '').replace('+', 'Z')}-{fingerprint[:12]}.json"
    path = directory / filename
    payload.setdefault("audit", {})
    payload["audit"]["persisted"] = True
    payload["audit"]["artifact_path"] = _project_relative_path(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return payload


def _normalize_command_result(row: Mapping[str, Any]) -> dict[str, Any]:
    command = str(row.get("cmd") or row.get("command") or "")
    return {
        "cmd": command,
        "purpose": _redact_phi_like(str(row.get("purpose") or "")),
        "exit_code": int(row.get("exit_code") if row.get("exit_code") is not None else row.get("returncode") or 0),
        "duration_seconds": round(float(row.get("duration_seconds") or row.get("duration_s") or 0), 3),
        "artifact_ref": _redact_phi_like(str(row.get("artifact_ref") or row.get("artifact_path") or "")),
        "output_excerpt": _artifact_excerpt(row.get("output_excerpt") or row.get("stdout") or row.get("stderr") or ""),
        "allowed": _shadow_command_allowed(command),
    }


def _normalize_visual_result(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route": str(row.get("route") or row.get("url") or ""),
        "viewport": _redact_phi_like(str(row.get("viewport") or "")),
        "status": str(row.get("status") or "passed"),
        "console_errors": int(row.get("console_errors") or 0),
        "overlap_detected": bool(row.get("overlap_detected", False)),
        "artifact_ref": _redact_phi_like(str(row.get("artifact_ref") or row.get("screenshot") or "")),
        "notes": _artifact_excerpt(row.get("notes") or ""),
    }


def _shadow_command_allowed(command: str) -> bool:
    return any(str(command or "").startswith(prefix) for prefix in SHADOW_COMMAND_ALLOWLIST)


def _artifact_excerpt(value: Any) -> str:
    return _redact_phi_like(str(value or "").replace("\n", " "))[:360]


def _project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except Exception:
        return _redact_phi_like(str(path))


def _shadow_execution_blocking_findings(
    *,
    unsafe_cmds: Iterable[Mapping[str, Any]],
    failed_cmds: Iterable[Mapping[str, Any]],
    missing_cmds: Iterable[str],
    missing_visuals: Iterable[str],
    safety: Mapping[str, Any],
    commands_executed: bool,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if safety.get("summary", {}).get("release_gate") != "ready_for_human_review":
        findings.append({
            "code": "safety_gate_not_ready",
            "severity": "blocker",
            "message": "Safety Gate Runner is not ready for human review.",
        })
    if not commands_executed:
        findings.append({
            "code": "execution_pending",
            "severity": "pending",
            "message": "Controlled local command execution artifact has not been recorded yet.",
        })
    for row in unsafe_cmds:
        findings.append({
            "code": "unsafe_command",
            "severity": "blocker",
            "message": f"Command outside allowlist: {_artifact_excerpt(row.get('cmd'))}",
        })
    for row in failed_cmds:
        findings.append({
            "code": "failed_command",
            "severity": "blocker",
            "message": f"Command failed: {_artifact_excerpt(row.get('cmd'))}",
        })
    for cmd in missing_cmds:
        findings.append({
            "code": "missing_command_artifact",
            "severity": "blocker",
            "message": f"Missing result for declared command: {_artifact_excerpt(cmd)}",
        })
    for route in missing_visuals:
        findings.append({
            "code": "missing_visual_artifact",
            "severity": "review",
            "message": f"Missing visual validation artifact for route: {_artifact_excerpt(route)}",
        })
    return findings


def _clinical_scope_for(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "affected_states": list(candidate.get("affected_states") or []),
        "patient_scope": dict(candidate.get("patient_scope") or {}),
        "clinical_contract": dict(candidate.get("clinical_contract") or {}),
        "contract_gap_count": len(candidate.get("contract_gaps") or []),
        "contradiction_count": len(candidate.get("contradictions") or []),
    }


def _shadow_visual_targets(candidate: Mapping[str, Any]) -> list[str]:
    surfaces = {str(item).lower() for item in (candidate.get("surfaces") or [])}
    targets = []
    if any("dashboard" in item for item in surfaces):
        targets.append("/dashboard")
    if any("patients" in item for item in surfaces):
        targets.append("/patients")
    if any("profile" in item or "decision" in item for item in surfaces):
        targets.append("/patient_profile/<nss>?v=2")
    if any("longitudinal" in item for item in surfaces):
        targets.append("/longitudinal-capture/<nss>")
    if any("clinical-hub" in item or "hub" in item for item in surfaces):
        targets.append("/clinical-hub")
    if any("loop" in item for item in surfaces):
        targets.append("/loop-monitor")
    return targets or ["/loop-monitor"]


def _guess_test_file(test_name: str) -> str:
    text = str(test_name or "").lower()
    if "decision_today" in text:
        return "tests/test_decision_today_fusion_kernel.py"
    if "autodrive" in text:
        return "tests/test_clinical_autodrive_command_center.py"
    if "readiness" in text or "m0crpc" in text or "m1crpc" in text or "bcr" in text:
        return "tests/test_clinical_readiness_tower.py"
    if "tumor" in text:
        return "tests/test_tumor_board_os.py"
    if "care_pathway" in text:
        return "tests/test_care_pathway_os.py"
    if "memory" in text:
        return "tests/test_clinical_memory_os.py"
    if "field_router" in text or "capture_route" in text:
        return "tests/test_clinical_field_router_closure.py"
    if "voice" in text or "cortana" in text:
        return "tests/test_voice_clinical_os.py"
    if "autonomous" in text or "shadow" in text or "proposal" in text:
        return "tests/test_autonomous_improvement_os.py"
    return ""


def _dedupe_target_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = str(row.get("path") or "")
        if path:
            out[path] = dict(row)
    return list(out.values())


def _dedupe_command_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cmd = str(row.get("cmd") or "")
        if cmd:
            out[cmd] = dict(row)
    return list(out.values())


def _sanitize_branch_slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "improvement").lower()).strip("-")
    return (slug or "improvement")[:48]


def validate_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Safety validation. Missing evidence/tests or fabricated facts block."""
    data = deepcopy(dict(candidate))
    blockers = list(data.get("blockers") or [])
    status = str(data.get("status") or "shadow")
    lane = str(data.get("lane") or "")
    text = " ".join(str(data.get(k) or "") for k in ("title", "description", "risk_avoided", "source"))

    if lane not in DEVELOPMENT_LANES:
        blockers.append("invalid_development_lane")
    if not data.get("evidence"):
        blockers.append("missing_evidence")
    if not data.get("tests_required"):
        blockers.append("missing_tests")
    if data.get("fabricates_clinical_data") or any(re.search(pattern, text, flags=re.I) for pattern in FORBIDDEN_FABRICATION_PATTERNS):
        blockers.append("fabricates_clinical_data")
    if status not in ALLOWED_STATES:
        status = "shadow"

    if blockers:
        status = "blocked"
    elif status == "shadow" and data.get("evidence") and data.get("tests_required"):
        status = "proposal_ready"

    data["status"] = status
    data["blockers"] = sorted(set(str(b) for b in blockers if b))
    data["contract_gaps"] = list(data.get("contract_gaps") or [])
    data["clinical_contract"] = dict(data.get("clinical_contract") or {})
    data["contradictions"] = list(data.get("contradictions") or [])
    return data


def build_contradiction_rule_registry() -> list[dict[str, Any]]:
    """Phase 2B rules that compare source bundles for coherent Decision Today."""
    return [
        {
            "rule_id": "decision_autodrive_lane_mismatch",
            "label": "Decision Today and Autodrive lane mismatch",
            "sources": ["decision_today", "clinical_autodrive"],
            "violation": "releaseable decision paired with blocked Autodrive lane, or requires_data paired with ready_to_decide",
            "severity": 9,
            "tests": ["test_contradiction_decision_autodrive_mismatch_detected"],
            "risk_avoided": "Avoids showing one module ready while the daily queue says the same decision is blocked.",
        },
        {
            "rule_id": "readiness_tumor_board_release_mismatch",
            "label": "Readiness blocks but Tumor Board releases",
            "sources": ["clinical_readiness_tower", "tumor_board_os"],
            "violation": "Tumor Board releaseable option exists while readiness has active blockers or missing decisive fields",
            "severity": 10,
            "tests": ["test_contradiction_readiness_blocks_tumor_board_release"],
            "risk_avoided": "Avoids releasing treatment options before required safety/data readiness is complete.",
        },
        {
            "rule_id": "care_pathway_executes_blocked_decision",
            "label": "Care Pathway action exists while Decision Today is blocked",
            "sources": ["decision_today", "care_pathway_os"],
            "violation": "executable treatment action is pending/ordered/scheduled while Decision Today is blocked/requires_data",
            "severity": 10,
            "tests": ["test_contradiction_care_pathway_does_not_execute_blocked_decision"],
            "risk_avoided": "Avoids operationalizing an internal action from an unreleased or unsafe decision.",
        },
        {
            "rule_id": "memory_redecision_not_reflected",
            "label": "Clinical Memory requires redecision but Decision Today does not",
            "sources": ["clinical_memory_os", "decision_today", "clinical_autodrive"],
            "violation": "Clinical Memory flags off-track/progression/toxicity but Decision Today and Autodrive do not surface redecision",
            "severity": 9,
            "tests": ["test_contradiction_memory_redecision_dominates_decision_today"],
            "risk_avoided": "Avoids missing a new decision after observed progression, toxicity or off-track outcome.",
        },
        {
            "rule_id": "bcr_cross_state_crpc_activation",
            "label": "BCR surface activates CRPC/PARP/PSMA-RLT pathway",
            "sources": ["state", "tumor_board_os", "care_pathway_os", "decision_today"],
            "violation": "BCR state shows CRPC/PARP/PSMA-RLT options without documented transition",
            "severity": 10,
            "tests": ["test_contradiction_bcr_excludes_crpc_parp_rlt"],
            "risk_avoided": "Avoids cross-state therapeutic drift before CRPC/metastatic transition is documented.",
        },
        {
            "rule_id": "m0crpc_release_without_confirmation",
            "label": "m0CRPC release without testosterone, PSADT or M0 conventional imaging",
            "sources": ["decision_today", "clinical_readiness_tower", "longitudinal_truth_snapshot"],
            "violation": "m0CRPC decision releaseable while critical CRPC confirmation fields are still missing",
            "severity": 10,
            "tests": ["test_contradiction_m0crpc_release_requires_confirmation_fields"],
            "risk_avoided": "Avoids releasing ARPI logic without castration, PSADT and conventional M0 confirmation.",
        },
        {
            "rule_id": "m1crpc_sequence_without_real_line",
            "label": "m1CRPC sequencing without real treatment line",
            "sources": ["decision_today", "tumor_board_os", "treatment_lines"],
            "violation": "m1CRPC sequencing option is releaseable while no real treatment line is documented",
            "severity": 10,
            "tests": ["test_contradiction_m1crpc_sequence_requires_real_line"],
            "risk_avoided": "Avoids invented sequencing and unsafe PARP/RLT/taxane decisions.",
        },
        {
            "rule_id": "missing_field_without_capture_route",
            "label": "Missing decisive field without capture route",
            "sources": ["decision_today", "clinical_field_router", "longitudinal_capture"],
            "violation": "Decision Today missing field lacks capture surface, CTA, decision_lane or decision_field",
            "severity": 8,
            "tests": ["test_contradiction_missing_field_has_capture_route"],
            "risk_avoided": "Avoids dead-end blockers where the clinician cannot capture the exact data needed.",
        },
    ]


def derive_contradiction_rows(source_bundle: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Evaluate Phase 2B contradiction rules against a patient source bundle."""
    source = dict(source_bundle or {})
    state = str(source.get("state") or source.get("clinical_state") or "").lower()
    decision = dict(source.get("decision_today") or {})
    readiness = dict(source.get("clinical_readiness_tower") or {})
    tumor_board = dict(source.get("tumor_board_os") or {})
    care_pathway = dict(source.get("care_pathway_os") or {})
    memory = dict(source.get("clinical_memory_os") or {})
    autodrive = dict(source.get("clinical_autodrive") or source.get("autodrive") or {})
    patient = dict(source.get("patient") or {})
    rules = {rule["rule_id"]: rule for rule in build_contradiction_rule_registry()}
    rows: list[dict[str, Any]] = []

    decision_state = _decision_state(decision)
    autodrive_lane = _autodrive_lane(autodrive)
    missing_fields = _missing_field_names(decision, readiness, autodrive)
    releaseable_options = _releaseable_option_texts(tumor_board)
    executable_actions = _executable_action_texts(care_pathway)
    all_option_text = " ".join(releaseable_options + executable_actions + [_decision_title(decision)]).lower()

    if (decision_state == "releaseable" and autodrive_lane == "blocked_by_data") or (
        decision_state in {"requires_data", "blocked"} and autodrive_lane == "ready_to_decide"
    ):
        rows.append(_contradiction_row(
            rules["decision_autodrive_lane_mismatch"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=[f"decision_state={decision_state}", f"autodrive_lane={autodrive_lane}"],
            source_values={"decision_state": decision_state, "autodrive_lane": autodrive_lane},
        ))

    if releaseable_options and _readiness_has_blockers(readiness):
        rows.append(_contradiction_row(
            rules["readiness_tumor_board_release_mismatch"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=releaseable_options[:4] + missing_fields[:6],
            source_values={"releaseable_options": releaseable_options[:6], "missing_fields": missing_fields[:12]},
        ))

    if decision_state in {"requires_data", "blocked"} and executable_actions:
        rows.append(_contradiction_row(
            rules["care_pathway_executes_blocked_decision"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=executable_actions[:4] + [f"decision_state={decision_state}"],
            source_values={"decision_state": decision_state, "actions": executable_actions[:6]},
        ))

    if _memory_requires_redecision(memory) and decision_state not in {"urgent_safety", "redecision_required"} and autodrive_lane != "redecision_required":
        rows.append(_contradiction_row(
            rules["memory_redecision_not_reflected"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=[f"memory_requires_redecision=true", f"decision_state={decision_state}", f"autodrive_lane={autodrive_lane}"],
            source_values={"decision_state": decision_state, "autodrive_lane": autodrive_lane},
        ))

    if state in {"recurrence_bcr", "post_prostatectomy", "post_radiotherapy_or_local_salvage"} and _has_crpc_cross_state_text(all_option_text):
        rows.append(_contradiction_row(
            rules["bcr_cross_state_crpc_activation"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=(releaseable_options + executable_actions + [_decision_title(decision)])[:6],
            source_values={"option_text": all_option_text[:500]},
        ))

    if state == "m0_crpc" and decision_state == "releaseable" and _missing_any(missing_fields, ["testosterone", "psadt", "m0", "conventional_imaging"]):
        rows.append(_contradiction_row(
            rules["m0crpc_release_without_confirmation"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=missing_fields[:8],
            source_values={"decision_state": decision_state, "missing_fields": missing_fields[:12]},
        ))

    if state == "m1_crpc" and decision_state == "releaseable" and _sequence_text(all_option_text) and not _has_real_treatment_line(patient, source):
        rows.append(_contradiction_row(
            rules["m1crpc_sequence_without_real_line"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=[_decision_title(decision)] + releaseable_options[:4],
            source_values={"decision_state": decision_state, "treatment_line_count": _treatment_line_count(patient, source)},
        ))

    missing_without_route = [
        item for item in _missing_field_objects(decision)
        if not _missing_field_has_route(item)
    ]
    if missing_without_route:
        rows.append(_contradiction_row(
            rules["missing_field_without_capture_route"],
            patient_ref=source.get("patient_ref"),
            state=state,
            evidence=[str(item.get("field") or item.get("key") or item.get("label") or item) for item in missing_without_route[:8]],
            source_values={"missing_fields_without_route": missing_without_route[:8]},
        ))

    return sorted(rows, key=lambda row: (-int(row.get("severity") or 0), str(row.get("rule_id") or "")))


def _contradiction_row(
    rule: Mapping[str, Any],
    *,
    patient_ref: Any = "",
    state: str = "",
    evidence: Iterable[Any] | None = None,
    source_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": str(rule.get("rule_id") or ""),
        "label": str(rule.get("label") or ""),
        "severity": int(rule.get("severity") or 8),
        "state": str(state or "unknown"),
        "patient_ref_hint": _mask_ref(str(patient_ref or "")),
        "status": "active_contradiction",
        "sources": list(rule.get("sources") or []),
        "evidence": [_redact_phi_like(str(item)) for item in (evidence or []) if str(item or "").strip()][:12],
        "source_values": _safe_public_mapping(source_values or {}),
        "risk_avoided": str(rule.get("risk_avoided") or ""),
        "tests": list(rule.get("tests") or []),
    }


def _decision_state(decision: Mapping[str, Any]) -> str:
    source = dict(decision or {})
    nested = dict(source.get("decision_today") or {})
    recommendation = dict(source.get("recommendation") or {})
    return _normalize_status(
        source.get("decision_state")
        or source.get("status")
        or nested.get("status")
        or recommendation.get("status")
        or ""
    )


def _decision_title(decision: Mapping[str, Any]) -> str:
    source = dict(decision or {})
    nested = dict(source.get("decision_today") or {})
    next_action = dict(source.get("next_safe_action") or {})
    recommendation = dict(source.get("recommendation") or {})
    return _first_text(
        nested.get("title"),
        source.get("decision_today"),
        source.get("title"),
        next_action.get("title"),
        recommendation.get("title"),
        recommendation.get("label"),
    )


def _autodrive_lane(autodrive: Mapping[str, Any]) -> str:
    source = dict(autodrive or {})
    summary = dict(source.get("summary") or {})
    queue = source.get("today_queue") or []
    first = dict(queue[0] or {}) if isinstance(queue, list) and queue else {}
    lane = _first_text(
        source.get("dominant_lane"),
        summary.get("dominant_lane"),
        summary.get("lane"),
        first.get("lane"),
        first.get("autodrive_lane"),
        first.get("category"),
    )
    return _normalize_status(lane)


def _missing_field_objects(*sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("unified_missing_fields", "missing_fields"):
            out.extend(_coerce_missing_items(source.get(key)))
        capture_plan = source.get("capture_plan")
        if isinstance(capture_plan, Mapping):
            out.extend(_coerce_missing_items(capture_plan.get("missing_fields")))
            out.extend(_coerce_missing_items(capture_plan.get("fields")))
            for group in capture_plan.get("groups") or []:
                if isinstance(group, Mapping):
                    out.extend(_coerce_missing_items(group.get("fields")))
        summary = source.get("summary")
        if isinstance(summary, Mapping):
            out.extend(_coerce_missing_items(summary.get("missing_fields")))
        for lane in source.get("lanes") or []:
            if isinstance(lane, Mapping):
                out.extend(_coerce_missing_items(lane.get("missing_fields")))
    return _dedupe_missing_objects(out)


def _missing_field_names(*sources: Mapping[str, Any]) -> list[str]:
    names = []
    for item in _missing_field_objects(*sources):
        label = _first_text(item.get("field"), item.get("key"), item.get("name"), item.get("label"), item.get("id"))
        if label:
            names.append(label)
    return _dedupe([_normalize_field_name(name) for name in names if name])


def _coerce_missing_items(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        if any(key in raw for key in ("field", "key", "name", "label", "id")):
            return [dict(raw)]
        return [dict(value, field=key) if isinstance(value, Mapping) else {"field": key, "label": value} for key, value in raw.items()]
    if isinstance(raw, (list, tuple, set)):
        out = []
        for item in raw:
            if isinstance(item, Mapping):
                out.append(dict(item))
            else:
                out.append({"field": str(item)})
        return out
    return [{"field": str(raw)}]


def _dedupe_missing_objects(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for raw in items:
        item = dict(raw or {})
        name = _normalize_field_name(_first_text(item.get("field"), item.get("key"), item.get("name"), item.get("label"), item.get("id")))
        if not name or name in seen:
            continue
        seen.add(name)
        if not item.get("field"):
            item["field"] = name
        out.append(item)
    return out


def _releaseable_option_texts(tumor_board: Mapping[str, Any]) -> list[str]:
    source = dict(tumor_board or {})
    out: list[str] = []
    for option in source.get("options") or []:
        if not isinstance(option, Mapping):
            continue
        status = _normalize_status(option.get("release_state") or option.get("status") or option.get("state"))
        if status in {"releaseable", "ready", "released", "eligible"} or option.get("releaseable") is True:
            out.append(_option_text(option))
    recommendation = source.get("recommendation")
    if isinstance(recommendation, Mapping):
        status = _normalize_status(recommendation.get("release_state") or recommendation.get("status") or recommendation.get("state"))
        if status in {"releaseable", "ready", "released"}:
            out.append(_option_text(recommendation))
    return [item for item in _dedupe(out) if item]


def _executable_action_texts(care_pathway: Mapping[str, Any]) -> list[str]:
    source = dict(care_pathway or {})
    out: list[str] = []
    for key in ("pathway_actions", "actions", "autodrive_actions", "execution_timeline"):
        for action in source.get(key) or []:
            if not isinstance(action, Mapping):
                continue
            status = _normalize_status(action.get("status") or action.get("state") or action.get("execution_status"))
            mode = str(action.get("action_mode") or action.get("family") or action.get("type") or action.get("category") or "").lower()
            text = _option_text(action)
            if status in {"pending", "ordered", "scheduled", "active"} and "capture" not in mode:
                out.append(text)
    return [item for item in _dedupe(out) if item]


def _option_text(option: Mapping[str, Any]) -> str:
    return _first_text(
        option.get("title"),
        option.get("label"),
        option.get("option"),
        option.get("key"),
        option.get("reason"),
        option.get("rationale"),
        option.get("action_key"),
    )


def _readiness_has_blockers(readiness: Mapping[str, Any]) -> bool:
    source = dict(readiness or {})
    summary = dict(source.get("summary") or {})
    status = _normalize_status(summary.get("status") or summary.get("dominant_status") or source.get("status"))
    if status in {"requires_data", "blocked", "active_risk", "overdue"}:
        return True
    if _first_text(summary.get("dominant_blocker"), source.get("dominant_blocker")):
        return True
    if _missing_field_objects(source):
        return True
    for lane in source.get("lanes") or []:
        if not isinstance(lane, Mapping):
            continue
        lane_status = _normalize_status(lane.get("status") or lane.get("state"))
        if lane_status in {"requires_data", "blocked", "active_risk", "overdue"}:
            return True
    return False


def _memory_requires_redecision(memory: Mapping[str, Any]) -> bool:
    source = dict(memory or {})
    summary = dict(source.get("summary") or {})
    expected = dict(source.get("expected_vs_observed") or {})
    if summary.get("requires_redecision") is True or source.get("requires_redecision") is True:
        return True
    status = _normalize_status(
        summary.get("outcome_status")
        or summary.get("status")
        or expected.get("status")
        or expected.get("outcome_status")
    )
    return status in {"requires_redecision", "off_track", "toxicity_limited", "progression"}


def _has_crpc_cross_state_text(text: str) -> bool:
    return bool(re.search(r"\b(crpc|mcrpc|parp|psma[-_\s]?rlt|lutetium|lu[-\s]?177|pluvicto|olaparib|rucaparib)\b", str(text or ""), flags=re.I))


def _missing_any(missing_fields: Iterable[str], required: Iterable[str]) -> bool:
    normalized = {_normalize_field_name(item) for item in missing_fields}
    aliases = {
        "testosterone": {"testosterone", "testosterona", "testosterone_value", "castrate_testosterone"},
        "psadt": {"psadt", "psa_doubling_time", "psa_doubling", "tdpa", "psa_dt"},
        "m0": {"m0", "m0_conventional", "conventional_m0", "metastasis_absent"},
        "conventional_imaging": {"conventional_imaging", "imagen_convencional", "ct_bone_scan", "ct_and_bone_scan"},
    }
    for key in required:
        choices = aliases.get(str(key), {str(key)})
        if normalized.intersection({_normalize_field_name(choice) for choice in choices}):
            return True
    return False


def _sequence_text(text: str) -> bool:
    return bool(re.search(r"\b(sequence|secuencia|sequencing|parp|psma[-_\s]?rlt|taxane|taxano|docetaxel|cabazitaxel|olaparib|rucaparib|lutetium|pluvicto)\b", str(text or ""), flags=re.I))


def _has_real_treatment_line(patient: Mapping[str, Any], source: Mapping[str, Any]) -> bool:
    return _treatment_line_count(patient, source) > 0


def _treatment_line_count(patient: Mapping[str, Any], source: Mapping[str, Any]) -> int:
    candidates = [
        patient.get("treatment_lines") if isinstance(patient, Mapping) else None,
        patient.get("treatments") if isinstance(patient, Mapping) else None,
        source.get("treatment_lines") if isinstance(source, Mapping) else None,
        (source.get("longitudinal_truth_snapshot") or {}).get("treatment_lines") if isinstance(source.get("longitudinal_truth_snapshot"), Mapping) else None,
        (source.get("clinical_memory_os") or {}).get("treatment_lines") if isinstance(source.get("clinical_memory_os"), Mapping) else None,
    ]
    count = 0
    for raw in candidates:
        if isinstance(raw, list):
            count = max(count, len([item for item in raw if item]))
        elif isinstance(raw, Mapping):
            count = max(count, len([item for item in raw.values() if item]))
    for key in ("real_treatment_line", "treatment_line", "line_of_therapy", "current_line"):
        value = patient.get(key) if isinstance(patient, Mapping) else None
        if value not in (None, "", 0, "0", "none", "sin linea"):
            count = max(count, 1)
    return count


def _missing_field_has_route(item: Mapping[str, Any]) -> bool:
    if not isinstance(item, Mapping):
        return False
    for key in (
        "capture_surface",
        "capture_url",
        "cta",
        "href",
        "url",
        "decision_lane",
        "readiness_lane",
        "decision_field",
    ):
        value = item.get(key)
        if isinstance(value, Mapping):
            if value.get("href") or value.get("url") or value.get("label"):
                return True
        elif str(value or "").strip():
            return True
    return False


def _contract_for_contradiction(rule_id: str) -> dict[str, Any]:
    mapping = {
        "bcr_cross_state_crpc_activation": "bcr_salvage_window_minimum",
        "m0crpc_release_without_confirmation": "m0crpc_confirmation_minimum",
        "m1crpc_sequence_without_real_line": "m1crpc_sequence_precision_minimum",
        "missing_field_without_capture_route": "patient_twin_preference_pro_minimum",
    }
    return _contract_by_id(mapping.get(str(rule_id), ""))


def _normalize_status(value: Any) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "ready_to_decide": "ready_to_decide",
        "ready": "ready",
        "liberable": "releaseable",
        "releasable": "releaseable",
        "requires_data": "requires_data",
        "blocked_by_data": "blocked_by_data",
        "bloqueado": "blocked",
        "redecision": "redecision_required",
        "urgent": "urgent_safety",
    }
    return aliases.get(text, text)


def _normalize_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("title") or value.get("label") or value.get("value")
        if value is None:
            continue
        text = str(value).strip()
        if text and text != "{}":
            return text
    return ""


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, default=str) if isinstance(value, (Mapping, list, tuple)) else str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _safe_public_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in dict(data or {}).items():
        if isinstance(value, str):
            public[str(key)] = _redact_phi_like(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            public[str(key)] = value
        elif isinstance(value, list):
            public[str(key)] = [_redact_phi_like(str(item)) if not isinstance(item, (int, float, bool, type(None))) else item for item in value[:12]]
        elif isinstance(value, Mapping):
            public[str(key)] = {
                str(inner_key): _redact_phi_like(str(inner_value))
                for inner_key, inner_value in list(value.items())[:12]
            }
        else:
            public[str(key)] = _redact_phi_like(str(value))
    return public


def build_clinical_gap_contract_registry() -> list[dict[str, Any]]:
    """Canonical Phase 2A contracts: field -> surface -> persistence -> consumer."""
    return [
        {
            "contract_id": "diagnostic_truth_minimum",
            "label": "Diagnostic truth minimum",
            "trigger_states": ["diagnostic_workup", "screening", "post_negative_biopsy_followup"],
            "field_aliases": [
                "psa_density",
                "psad",
                "mri_pirads_score",
                "pirads",
                "mri_pirads",
                "dre",
                "biopsy_status",
                "prior_negative_biopsy",
                "family_history",
                "germline_risk",
                "phi_value",
                "fourkscore_value",
            ],
            "required_fields": [
                "psa_density",
                "mri_pirads_score",
                "dre_suspicious",
                "biopsy_status",
                "family_history",
                "germline_risk",
            ],
            "capture_surface": "clinical-hub classifier + diagnostic wizard?readiness_lane=diagnostic_truth_minimum + longitudinal-capture",
            "persistence": "clinical_baseline + stage_visit_records + patient_clinical_facts",
            "consumer": "Decision Today + diagnostic biopsy readiness + Tumor Board OS",
            "tests": [
                "test_diagnostic_truth_minimum_requires_dominant_decision_fields",
                "test_diagnostic_truth_minimum_can_be_satisfied_by_legacy_aliases",
                "test_field_router_diagnostic_truth_minimum_is_compact_and_state_scoped",
                "test_fusion_routes_diagnostic_truth_gap_to_diagnostic_readiness",
                "test_wizard_form_uses_router_fields_when_readiness_lane_is_active",
            ],
            "risk_avoided": "Avoids biopsy/workup recommendations without the minimum diagnostic truth set.",
            "severity": 7,
        },
        {
            "contract_id": "localized_function_preference_minimum",
            "label": "Localized function and preference minimum",
            "trigger_states": ["localized_initial"],
            "field_aliases": [
                "urinary_function_baseline",
                "sexual_function_baseline",
                "bowel_function_baseline",
                "life_expectancy",
                "patient_preference",
                "preference",
                "pros",
                "epic26",
            ],
            "required_fields": [
                "risk_group",
                "life_expectancy",
                "urinary_function_baseline",
                "sexual_function_baseline",
                "bowel_function_baseline",
                "patient_values",
            ],
            "capture_surface": "localized wizard + longitudinal-capture?decision_lane=preference_function_baseline",
            "persistence": "patient_clinical_facts + stage_visit_records + PRO baseline",
            "consumer": "Decision Today + Patient Twin + Tumor Board OS",
            "tests": ["test_localized_contract_requires_function_and_preferences"],
            "risk_avoided": "Avoids choosing AS/RP/RT without function, quality-of-life and preference context.",
            "severity": 8,
        },
        {
            "contract_id": "bcr_salvage_window_minimum",
            "label": "BCR salvage window minimum",
            "trigger_states": ["recurrence_bcr", "post_prostatectomy", "post_radiotherapy_or_local_salvage"],
            "field_aliases": ["psadt", "psa_doubling_time", "ultrasensitive_psa", "psa_nadir", "phoenix", "margin_status", "path_margin", "psma_pet"],
            "required_fields": [
                "post_local_context",
                "psa_value",
                "psa_doubling_time_months",
                "salvage_context_marker",
                "surgical_margins_status_or_rt_nadir",
                "psma_pet_if_changes_management",
            ],
            "capture_surface": "BCR wizard?readiness_lane=bcr_salvage_window_minimum + longitudinal-capture?decision_lane=bcr_salvage_readiness",
            "persistence": "biomarker_longitudinal + clinical_baseline + patient_clinical_facts",
            "consumer": "Decision Today + BCR salvage readiness + Care Pathway OS",
            "tests": [
                "test_bcr_salvage_window_minimum_requires_psadt_and_context",
                "test_bcr_salvage_window_minimum_can_be_satisfied_by_legacy_aliases",
                "test_field_router_bcr_salvage_window_minimum_is_compact_and_excludes_crpc_domains",
                "test_fusion_routes_bcr_salvage_gap_to_bcr_readiness",
            ],
            "risk_avoided": "Avoids missing early salvage windows or activating CRPC/PARP/RLT prematurely.",
            "severity": 9,
        },
        {
            "contract_id": "mhspc_m1_volume_fitness_minimum",
            "label": "mHSPC M1 composition, volume and fitness minimum",
            "trigger_states": ["mcspc_low_volume", "mcspc_high_volume", "m1_cspc", "metastatic_cspc"],
            "field_aliases": ["m1", "m1_composition", "m1a", "m1b", "m1c", "chaarted", "latitude", "volume", "fitness", "ecog"],
            "required_fields": ["m1_composition", "chaarted_volume", "latitude_risk", "ecog_fitness", "systemic_safety"],
            "capture_surface": "mHSPC wizard + longitudinal-capture?decision_lane=mhspc_precision_readiness",
            "persistence": "clinical_baseline.metastatic_profile + patient_clinical_facts + stage_visit_records",
            "consumer": "Decision Today + mHSPC readiness + Tumor Board OS + Autodrive",
            "tests": ["test_mhspc_contract_requires_m1_volume_risk_and_fitness"],
            "risk_avoided": "Avoids releasing doublet/triplet decisions without metastatic composition and safety context.",
            "severity": 9,
        },
        {
            "contract_id": "m0crpc_confirmation_minimum",
            "label": "m0CRPC confirmation minimum",
            "trigger_states": ["m0_crpc", "adt_progression_verification"],
            "field_aliases": ["testosterone", "testosterone_value", "psadt", "psa_doubling_time", "m0", "conventional_imaging", "adt_active"],
            "required_fields": ["adt_active", "testosterone_castrate", "psadt", "conventional_imaging_m0"],
            "capture_surface": "CRPC wizard + longitudinal-capture?decision_lane=crpc_confirmation_readiness",
            "persistence": "biomarker_longitudinal + patient_clinical_facts + stage_visit_records",
            "consumer": "Decision Today + CRPC confirmation readiness + Tumor Board OS",
            "tests": ["test_m0crpc_contract_requires_testosterone_psadt_m0"],
            "risk_avoided": "Avoids ARPI release without confirmed castration, PSADT and conventional M0 status.",
            "severity": 10,
        },
        {
            "contract_id": "m1crpc_sequence_precision_minimum",
            "label": "m1CRPC sequencing and precision minimum",
            "trigger_states": ["m1_crpc"],
            "field_aliases": ["real_treatment_line", "treatment_line", "hrr", "brca", "psma_pet", "marrow", "renal", "hepatic", "prior_taxane", "prior_arpi"],
            "required_fields": ["real_treatment_line", "progression_pattern", "hrr_brca_status_if_parp_competes", "psma_pet_if_rlt_competes", "marrow_renal_hepatic_safety"],
            "capture_surface": "m1CRPC wizard + longitudinal-capture?decision_lane=m1crpc_sequence_readiness",
            "persistence": "treatment_lines + patient_clinical_facts + stage_visit_records + verified_document_facts",
            "consumer": "Decision Today + Tumor Board OS + Care Pathway OS + Clinical Memory OS",
            "tests": ["test_m1crpc_contract_requires_real_line_and_precision_safety"],
            "risk_avoided": "Avoids invented sequencing, PARP or PSMA-RLT options without real lines and traceable precision data.",
            "severity": 10,
        },
        {
            "contract_id": "patient_twin_preference_pro_minimum",
            "label": "Patient Twin preference and PRO minimum",
            "trigger_states": ["localized_initial", "recurrence_bcr", "m0_crpc", "m1_crpc", "palliative"],
            "field_aliases": [
                "patient_preference",
                "patient_preferences",
                "patient_values",
                "values",
                "goal_of_care",
                "goals_of_care",
                "pros",
                "pro_baseline",
                "baseline_pro",
                "epic26",
                "esas",
                "toxicity_tolerance",
                "decision_tradeoff",
                "tradeoff",
                "redecision_threshold",
            ],
            "required_fields": ["patient_values", "baseline_pro", "toxicity_tolerance", "decision_tradeoff", "redecision_threshold"],
            "capture_surface": "Patient Twin panel + longitudinal-capture?decision_lane=patient_twin_readiness + Cortana reviewed note",
            "persistence": "patient_clinical_facts + PRO baseline + patient_events + data_provenance",
            "consumer": "Decision Today + Patient Twin + Clinical Memory OS",
            "tests": ["test_patient_twin_contract_requires_values_pros_and_thresholds"],
            "risk_avoided": "Avoids preference-sensitive recommendations that are guideline-correct but wrong for the patient.",
            "severity": 10,
        },
    ]


def build_application_telemetry(
    *,
    patient_summary: Mapping[str, Any] | None = None,
    contractual_gap_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Track software contracts already applied separately from patient data gaps."""
    base_rows = [
        dict(row)
        for row in (
            contractual_gap_rows
            if contractual_gap_rows is not None
            else derive_contractual_gap_rows(patient_summary, include_application_telemetry=False)
        )
    ]
    rows_by_id = {str(row.get("contract_id") or ""): row for row in base_rows}
    telemetry_index = _contract_application_telemetry_index()
    implementations: list[dict[str, Any]] = []
    for contract_id, telemetry in telemetry_index.items():
        contract = _contract_by_id(contract_id)
        active_row = rows_by_id.get(contract_id, {})
        patient_data_gap_open = _contract_row_has_patient_gap(active_row)
        implementations.append({
            **telemetry,
            "contract_id": contract_id,
            "label": contract.get("label", contract_id),
            "risk_avoided": contract.get("risk_avoided", ""),
            "capture_surface": contract.get("capture_surface", ""),
            "consumer": contract.get("consumer", ""),
            "patient_data_gap_open": patient_data_gap_open,
            "patient_capture_status": (
                "capture_still_required"
                if patient_data_gap_open
                else "no_active_patient_gap_detected"
            ),
            "matched_missing_fields": list(active_row.get("matched_missing_fields") or []),
            "triggered_state_count": int(active_row.get("triggered_state_count") or 0),
        })

    closed_count = sum(1 for row in implementations if row.get("software_gap_closed"))
    monitoring_count = sum(1 for row in implementations if row.get("patient_data_gap_open"))
    return {
        "available": True,
        "source": "autonomous_improvement_os",
        "version": "application_telemetry_v1",
        "summary": {
            "implemented_contract_count": len(implementations),
            "software_gap_closed_count": closed_count,
            "patient_capture_monitoring_count": monitoring_count,
            "telemetry_gap_count": sum(1 for row in implementations if not row.get("software_gap_closed")),
            "source_clinical_facts_mutated": False,
            "files_modified_by_telemetry": False,
            "git_mutated": False,
            "mode": "shadow_observation",
        },
        "implementations": implementations,
        "audit": _audit_footer(),
    }


def derive_contractual_gap_rows(
    patient_summary: Mapping[str, Any] | None,
    *,
    include_application_telemetry: bool = True,
) -> list[dict[str, Any]]:
    """Map scanned Decision Today gaps to Phase 2A clinical contracts."""
    summary = dict(patient_summary or {})
    missing_pairs = summary.get("missing_fields_top") or []
    state_counts = Counter(summary.get("state_counts") or {})
    rows: list[dict[str, Any]] = []
    registry = build_clinical_gap_contract_registry()
    telemetry_index = _contract_application_telemetry_index() if include_application_telemetry else {}

    for contract in registry:
        trigger_states = set(contract.get("trigger_states") or [])
        active_state_count = sum(count for state, count in state_counts.items() if state in trigger_states)
        matched_missing: list[dict[str, Any]] = []
        aliases = [str(alias).lower() for alias in contract.get("field_aliases") or []]
        for field, count in missing_pairs:
            field_text = str(field or "").lower()
            if any(alias and alias in field_text for alias in aliases):
                matched_missing.append({"field": str(field), "count": int(count or 0)})
        if active_state_count or matched_missing:
            row = {
                "contract_id": contract["contract_id"],
                "label": contract["label"],
                "triggered_state_count": active_state_count,
                "matched_missing_fields": matched_missing,
                "required_fields": list(contract.get("required_fields") or []),
                "capture_surface": contract.get("capture_surface", ""),
                "persistence": contract.get("persistence", ""),
                "consumer": contract.get("consumer", ""),
                "tests": list(contract.get("tests") or []),
                "risk_avoided": contract.get("risk_avoided", ""),
                "severity": int(contract.get("severity") or 5),
            }
            if include_application_telemetry:
                row.update(_contract_row_application_overlay(row, telemetry_index.get(str(contract["contract_id"]))))
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            1 if row.get("software_gap_closed") else 0,
            -int(row.get("severity") or 0),
            -int(row.get("triggered_state_count") or 0),
            -sum(int(m.get("count") or 0) for m in row.get("matched_missing_fields") or []),
            str(row.get("contract_id") or ""),
        ),
    )


def _contract_application_telemetry_index() -> dict[str, dict[str, Any]]:
    """Probe implemented software paths without mutating code, git or clinical facts."""
    out: dict[str, dict[str, Any]] = {}
    for contract_id, spec in CONTRACT_APPLICATION_TELEMETRY_CHECKS.items():
        readiness_ok, readiness_evidence = _readiness_lane_application_probe(spec)
        router_ok, router_evidence = _field_router_application_probe(spec)
        test_ok, test_evidence = _test_symbol_application_probe(spec)
        checks = {
            "readiness_lane": readiness_ok,
            "field_router": router_ok,
            "regression_tests_declared": test_ok,
        }
        software_gap_closed = all(checks.values())
        out[contract_id] = {
            "contract_id": contract_id,
            "implementation_status": (
                "implemented_validated"
                if software_gap_closed
                else "application_telemetry_incomplete"
            ),
            "software_gap_closed": software_gap_closed,
            "applied_phase": str(spec.get("applied_phase") or ""),
            "checks": checks,
            "evidence": list(spec.get("evidence") or []) + readiness_evidence + router_evidence + test_evidence,
            "source_clinical_facts_mutated": False,
            "files_modified_by_telemetry": False,
            "git_mutated": False,
        }
    return out


def _readiness_lane_application_probe(spec: Mapping[str, Any]) -> tuple[bool, list[str]]:
    try:
        from prostanet.domains.patient_tracking.clinical_readiness_tower import fields_for_readiness_lane

        expected = {str(field) for field in spec.get("expected_readiness_fields") or []}
        evidence: list[str] = []
        for lane in spec.get("readiness_lanes") or []:
            fields = {str(field) for field in fields_for_readiness_lane(str(lane))}
            missing = sorted(expected - fields)
            if missing:
                return False, [f"Readiness lane {lane} missing: {', '.join(missing)}"]
            evidence.append(f"Readiness lane {lane} exposes {len(expected)} expected fields.")
        return True, evidence
    except Exception as exc:
        return False, [f"Readiness probe unavailable: {type(exc).__name__}"]


def _field_router_application_probe(spec: Mapping[str, Any]) -> tuple[bool, list[str]]:
    try:
        from prostanet.presentation.clinical_field_router import build_clinical_field_router

        evidence: list[str] = []
        for check in spec.get("router_checks") or []:
            bundle = build_clinical_field_router(
                str(check.get("state") or "localized_initial"),
                phase=str(check.get("phase") or "initial_wizard"),
                readiness_lane=str(check.get("readiness_lane") or ""),
            )
            field_names = _router_field_names(bundle)
            expected = {str(field) for field in check.get("expected_fields") or []}
            missing = sorted(expected - field_names)
            if missing:
                return False, [f"Field Router {check.get('readiness_lane')} missing: {', '.join(missing)}"]
            evidence.append(
                f"Field Router {check.get('readiness_lane')} routes {len(expected)} expected fields."
            )
        return True, evidence
    except Exception as exc:
        return False, [f"Field Router probe unavailable: {type(exc).__name__}"]


def _test_symbol_application_probe(spec: Mapping[str, Any]) -> tuple[bool, list[str]]:
    tests = [str(symbol) for symbol in spec.get("test_symbols") or []]
    if not tests:
        return True, ["No explicit test symbols required for this telemetry check."]
    test_path = PROJECT_ROOT / "tests" / "test_autonomous_improvement_os.py"
    extra_paths = [
        PROJECT_ROOT / "tests" / "test_clinical_readiness_tower.py",
        PROJECT_ROOT / "tests" / "test_decision_today_fusion_kernel.py",
        PROJECT_ROOT / "tests" / "test_clinical_field_router_closure.py",
    ]
    text = ""
    for path in [test_path, *extra_paths]:
        if path.exists():
            try:
                text += "\n" + path.read_text(encoding="utf-8")
            except OSError:
                continue
    missing = [symbol for symbol in tests if symbol not in text]
    if missing:
        return False, [f"Regression test symbols missing: {', '.join(missing)}"]
    return True, [f"Regression test symbols declared: {', '.join(tests)}"]


def _router_field_names(bundle: Mapping[str, Any]) -> set[str]:
    groups = bundle.get("groups") or {}
    if isinstance(groups, Mapping):
        iterable = groups.values()
    elif isinstance(groups, list):
        iterable = groups
    else:
        iterable = []
    fields: set[str] = set()
    for group in iterable:
        if not isinstance(group, Mapping):
            continue
        for field in group.get("fields") or []:
            if isinstance(field, Mapping):
                name = str(field.get("name") or field.get("key") or "")
                if name:
                    fields.add(name)
    return fields


def _contract_row_has_patient_gap(row: Mapping[str, Any]) -> bool:
    return bool(int(row.get("triggered_state_count") or 0) or list(row.get("matched_missing_fields") or []))


def _contract_row_application_overlay(
    row: Mapping[str, Any],
    telemetry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    patient_data_gap_open = _contract_row_has_patient_gap(row)
    if not telemetry:
        return {
            "implementation_status": "unverified_software_gap",
            "software_gap_closed": False,
            "patient_data_gap_open": patient_data_gap_open,
            "cycle_telemetry_status": "software_gap_candidate",
            "application_evidence": [],
        }
    software_gap_closed = bool(telemetry.get("software_gap_closed"))
    return {
        "implementation_status": telemetry.get("implementation_status", "application_telemetry_incomplete"),
        "software_gap_closed": software_gap_closed,
        "patient_data_gap_open": patient_data_gap_open,
        "cycle_telemetry_status": (
            "software_closed_patient_capture_monitoring"
            if software_gap_closed and patient_data_gap_open
            else "software_closed_no_active_patient_gap"
            if software_gap_closed
            else "software_gap_candidate"
        ),
        "application_evidence": list(telemetry.get("evidence") or []),
        "application_checks": dict(telemetry.get("checks") or {}),
    }


def escalate_stuck_candidate(candidate: Mapping[str, Any], *, consecutive_count: int) -> dict[str, Any]:
    """Escalate a repeated unresolved candidate to human review."""
    data = dict(candidate)
    if consecutive_count >= 3 and data.get("status") not in {"blocked", "validated"}:
        data["status"] = "human_review_required"
        data.setdefault("blockers", [])
        if "stuck_gap_repeated" not in data["blockers"]:
            data["blockers"].append("stuck_gap_repeated")
    return data


def record_proposal_review(proposal_id: str, *, status: str, reviewer: str = "", note: str = "") -> dict[str, Any]:
    """Append a human review decision without storing PHI."""
    normalized = "approved" if status == "approved" else "rejected"
    event = {
        "ts": _now_iso(),
        "proposal_id": _sanitize_id(proposal_id),
        "status": normalized,
        "reviewer": _redact_phi_like(reviewer or "local_clinical_reviewer"),
        "note": _redact_phi_like(note or ""),
        "source": "autonomous_improvement_review",
        "source_clinical_facts_mutated": False,
    }
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def record_human_review_gate_decision(
    *,
    decision: str,
    reviewer: str = "",
    note: str = "",
    shadow_pr_factory: Mapping[str, Any] | None = None,
    shadow_execution_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an explicit Phase 3E decision without mutating git or medicine."""
    normalized = str(decision or "hold").strip().lower()
    if normalized not in HUMAN_REVIEW_DECISIONS:
        normalized = "hold"
    shadow = dict(shadow_pr_factory or build_shadow_pr_factory())
    package = dict(shadow.get("package") or {})
    execution = dict(shadow_execution_artifacts or build_shadow_execution_artifacts())
    execution_summary = dict(execution.get("summary") or {})
    artifact_controls = dict(execution.get("artifact_controls") or {})
    artifact_verified = execution_summary.get("artifact_status") == "verified_pending_human_review"
    if normalized == "approve_for_pr" and not artifact_verified:
        normalized = "hold"
    event = {
        "ts": _now_iso(),
        "source": "autonomous_improvement_human_review_gate",
        "phase": "3E_human_review_decision_gate",
        "decision": normalized,
        "reviewer": _redact_phi_like(reviewer or "local_clinical_reviewer"),
        "note": _redact_phi_like(note or ""),
        "artifact_status": execution_summary.get("artifact_status", ""),
        "artifact_verified": artifact_verified,
        "source_safety_fingerprint": str(artifact_controls.get("source_safety_fingerprint") or ""),
        "artifact_path": (execution.get("audit") or {}).get("artifact_path", ""),
        "candidate_id": _sanitize_id(str((package.get("candidate") or {}).get("id") or "")),
        "candidate_title": _redact_phi_like(str((package.get("candidate") or {}).get("title") or "")),
        "branch_name": _redact_phi_like(str((package.get("draft_pr") or {}).get("branch_name") or "")),
        "pull_request_created": False,
        "branch_created": False,
        "git_mutated": False,
        "auto_merge_allowed": False,
        "source_clinical_facts_mutated": False,
        "next_phase_suggested": _next_phase_for_human_decision(normalized),
    }
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    with _human_review_gate_log().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def record_pr_review_monitor_metadata(
    *,
    branch_name: str = "",
    pr_url: str = "",
    pr_number: str | int = "",
    ci_status: str = "unknown",
    review_status: str = "pending",
    reviewer: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Record external PR/CI/review metadata for Phase 3G; no git or merge action."""
    event = {
        "ts": _now_iso(),
        "source": "autonomous_improvement_pr_review_monitor",
        "phase": "3G_pr_review_monitor",
        "branch_name": _redact_phi_like(str(branch_name or "")),
        "pr_url": _redact_phi_like(str(pr_url or "")),
        "pr_number": _redact_phi_like(str(pr_number or "")),
        "ci_status": _normalize_pr_review_choice(ci_status, PR_REVIEW_CI_STATUSES, "unknown"),
        "review_status": _normalize_pr_review_choice(review_status, PR_REVIEW_REVIEW_STATUSES, "pending"),
        "reviewer": _redact_phi_like(reviewer or "local_clinical_reviewer"),
        "note": _redact_phi_like(note or ""),
        "pull_request_created_by_monitor": False,
        "merge_performed": False,
        "git_mutated": False,
        "auto_merge_allowed": False,
        "source_clinical_facts_mutated": False,
    }
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    with _pr_review_monitor_log().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def record_human_patch_authorization_decision(
    *,
    decision: str,
    reviewer: str = "",
    note: str = "",
    shadow_patch_blueprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an explicit Phase 4F patch authorization decision; no file/git mutation."""
    normalized = str(decision or "hold").strip().lower()
    if normalized not in PATCH_AUTHORIZATION_DECISIONS:
        normalized = "hold"
    blueprint = dict(shadow_patch_blueprint or build_shadow_patch_blueprint())
    summary = dict(blueprint.get("summary") or {})
    blueprint_ready = (
        summary.get("blueprint_status") == "blueprint_ready"
        and bool(blueprint.get("quality_gate", {}).get("ready_for_human_patch_authorization"))
    )
    if normalized == "authorize_patch" and not blueprint_ready:
        normalized = "hold"
    event = {
        "ts": _now_iso(),
        "source": "autonomous_improvement_human_patch_authorization",
        "phase": "4F_human_patch_authorization",
        "decision": normalized,
        "reviewer": _redact_phi_like(reviewer or "local_clinical_reviewer"),
        "note": _redact_phi_like(note or ""),
        "blueprint_id": _sanitize_id(str(summary.get("blueprint_id") or "")),
        "blueprint_ready": blueprint_ready,
        "selected_candidate_id": _sanitize_id(str(summary.get("selected_candidate_id") or "")),
        "selected_title": _redact_phi_like(str(summary.get("selected_title") or "")),
        "planned_file_count": int(summary.get("planned_file_count") or 0),
        "planned_hunk_count": int(summary.get("planned_hunk_count") or 0),
        "test_count": int(summary.get("test_count") or 0),
        "commands_executed": False,
        "files_modified": False,
        "branch_created": False,
        "pull_request_created": False,
        "merge_performed": False,
        "git_mutated": False,
        "auto_merge_allowed": False,
        "source_clinical_facts_mutated": False,
        "next_phase_suggested": _next_phase_for_patch_authorization_decision(normalized),
    }
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    with _human_patch_authorization_log().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def _human_review_gate_log() -> Path:
    return PERSISTENCE_DIR / "human_review_gate_log.jsonl"


def _pr_review_monitor_log() -> Path:
    return PERSISTENCE_DIR / "pr_review_monitor_log.jsonl"


def _human_patch_authorization_log() -> Path:
    return PERSISTENCE_DIR / "human_patch_authorization_log.jsonl"


def _load_latest_human_review_gate_decision(fingerprint: str) -> dict[str, Any]:
    path = _human_review_gate_log()
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if fingerprint and event.get("source_safety_fingerprint") != fingerprint:
                continue
            latest = event
    return latest


def _load_latest_pr_review_metadata(branch_name: str) -> dict[str, Any]:
    path = _pr_review_monitor_log()
    if not path.exists():
        return {}
    branch = str(branch_name or "")
    latest: dict[str, Any] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if branch and event.get("branch_name") != branch:
                continue
            latest = event
    return latest


def _load_latest_human_patch_authorization(blueprint_id: str) -> dict[str, Any]:
    path = _human_patch_authorization_log()
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    target = str(blueprint_id or "")
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if target and event.get("blueprint_id") != target:
                continue
            latest = event
    return latest


def _allowed_human_review_decisions(artifact_verified: bool) -> list[dict[str, Any]]:
    decisions = [
        {
            "decision": "hold",
            "label": "Mantener en revisión",
            "allowed": True,
            "effect": "No avanza; conserva el artifact en espera.",
        },
        {
            "decision": "request_changes",
            "label": "Solicitar cambios",
            "allowed": True,
            "effect": "Regresa a Shadow PR Factory con cambios requeridos.",
        },
        {
            "decision": "reject",
            "label": "Rechazar",
            "allowed": True,
            "effect": "Bloquea esta mejora y regresa a Development Autodrive.",
        },
        {
            "decision": "approve_for_pr",
            "label": "Aprobar handoff a PR",
            "allowed": bool(artifact_verified),
            "effect": "Permite preparar rama/PR draft en la fase siguiente; no crea PR ni mergea.",
        },
    ]
    return decisions


def _allowed_patch_authorization_decisions(blueprint_ready: bool) -> list[dict[str, Any]]:
    return [
        {
            "decision": "hold",
            "label": "Mantener en autorización",
            "allowed": True,
            "effect": "No aplica patch; conserva el blueprint en espera.",
        },
        {
            "decision": "request_changes",
            "label": "Solicitar cambios al blueprint",
            "allowed": True,
            "effect": "Regresa a Implementation Brief o Shadow Patch Blueprint para ajuste.",
        },
        {
            "decision": "reject",
            "label": "Rechazar patch",
            "allowed": True,
            "effect": "Bloquea este patch y regresa al Autodrive de desarrollo.",
        },
        {
            "decision": "authorize_patch",
            "label": "Autorizar patch controlado",
            "allowed": bool(blueprint_ready),
            "effect": "Permite que una fase posterior aplique el patch controlado; esta fase no modifica archivos.",
        },
    ]


def _next_phase_for_patch_authorization_decision(decision: str) -> str:
    if decision == "authorize_patch":
        return "4G_controlled_patch_application"
    if decision == "request_changes":
        return "4D_implementation_brief"
    if decision == "reject":
        return "3A_development_autodrive"
    return "4F_human_patch_authorization"


def _next_phase_for_human_decision(decision: str) -> str:
    if decision == "approve_for_pr":
        return "3F_draft_pr_handoff"
    if decision == "request_changes":
        return "3B_shadow_pr_factory"
    if decision == "reject":
        return "3A_development_autodrive"
    return "3E_human_review_decision_gate"


def _normalize_pr_review_choice(value: Any, allowed: Iterable[str], default: str) -> str:
    text = str(value or default).strip().lower()
    allowed_set = {str(row) for row in allowed}
    return text if text in allowed_set else default


def _agent_packet_required_fields() -> tuple[str, ...]:
    return (
        "agent_lane",
        "hypothesis",
        "clinical_or_operational_impact",
        "evidence",
        "minimal_change",
        "risks",
        "tests_required",
        "visual_validation_required",
        "security_privacy_review",
        "rollback",
        "acceptance_criteria",
        "human_review_required",
    )


def _agent_lane_for_development_lane(lane: Any) -> str:
    mapping = {
        "critical_clinical_gap": "clinical_logic",
        "data_integrity_gap": "data_contract",
        "evidence_gap": "evidence",
        "safety_security_gap": "security",
        "ui_workflow_gap": "ui_verification",
        "regulatory_traceability_gap": "regulatory",
    }
    return mapping.get(str(lane or ""), "clinical_logic")


def _agent_lane_routing_rules() -> list[dict[str, Any]]:
    return [
        {
            "development_lane": lane,
            "agent_lane": _agent_lane_for_development_lane(lane),
            "routing_reason": "primary owner for this gap family",
        }
        for lane in DEVELOPMENT_LANES
    ]


def _agent_lane_quality_gates(agent_lane: str) -> list[str]:
    shared = [
        "no clinical facts mutated",
        "no PHI in logs or artifacts",
        "human review required",
        "rollback documented",
    ]
    specialized = {
        "clinical_logic": ["gates/trials/state impact mapped", "Decision Today delta explained"],
        "data_contract": ["capture surface and persistence path mapped", "provenance fields declared"],
        "ui_verification": ["desktop/mobile visual validation required", "CTA path verified"],
        "evidence": ["EAU/FDA/ClinicalTrials.gov source impact declared", "no automatic guideline change"],
        "security": ["headers/logs/encryption/privacy reviewed", "no external data transmission"],
        "regulatory": ["change-control rationale and DHF/QMS traceability declared"],
    }
    return shared + specialized.get(agent_lane, [])


def _build_agent_proposal_packet(
    *,
    agent_lane: str,
    lane: Mapping[str, Any],
    candidate: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_id = str(candidate.get("id") or f"{agent_lane}-watchlist")
    has_candidate = bool(candidate.get("id"))
    evidence = list(proposal.get("evidence") or candidate.get("evidence") or [])
    tests_required = list(proposal.get("tests_required") or candidate.get("tests_required") or [])
    risks = list((proposal.get("risks") or _risks_for(candidate)) if has_candidate else [])
    if not has_candidate:
        evidence = ["Agent Lane Registry 4A", "No active candidate currently assigned to this lane"]
        tests_required = ["test_phase_4b_agent_proposal_packets"]
        risks = ["Lane has no active candidate; keep it in watchlist mode."]
    missing = []
    if not evidence:
        missing.append("evidence")
    if not tests_required:
        missing.append("tests_required")
    if not (proposal.get("rollback") or candidate.get("rollback") or not has_candidate):
        missing.append("rollback")
    if candidate.get("status") == "blocked":
        packet_status = "blocked"
    elif missing:
        packet_status = "blocked"
    elif not has_candidate:
        packet_status = "requires_data"
    else:
        packet_status = "proposal_ready"

    return {
        "packet_id": _stable_id(f"4b:{agent_lane}:{candidate_id}"),
        "agent_lane": agent_lane,
        "agent_label": lane.get("label", agent_lane),
        "scope": lane.get("scope", ""),
        "candidate_id": candidate_id if has_candidate else "",
        "candidate_title": _redact_phi_like(str(candidate.get("title") or "Sin candidato activo")),
        "development_lane": candidate.get("lane", ""),
        "candidate_priority_score": round(float(candidate.get("priority_score") or 0.0), 2),
        "candidate_severity": int(candidate.get("severity") or 0),
        "affected_states": list(candidate.get("affected_states") or []),
        "surfaces": list(candidate.get("surfaces") or []),
        "packet_status": packet_status,
        "position": _agent_packet_position(agent_lane=agent_lane, has_candidate=has_candidate),
        "hypothesis": _redact_phi_like(str(proposal.get("hypothesis") or candidate.get("description") or "No active gap assigned; monitor lane.")),
        "clinical_or_operational_impact": _redact_phi_like(str(candidate.get("risk_avoided") or "Avoids unsupervised changes by keeping the agent in shadow mode.")),
        "evidence": evidence,
        "minimal_change": _redact_phi_like(str((proposal.get("minimal_change") or _minimal_change_for(candidate)) if has_candidate else "No-op watchlist packet.")),
        "risks": risks,
        "tests_required": tests_required,
        "visual_validation_required": agent_lane == "ui_verification" or "loop-monitor" in [str(s) for s in candidate.get("surfaces") or []],
        "security_privacy_review": "required" if agent_lane == "security" else "standard_no_phi_check",
        "rollback": _redact_phi_like(str(proposal.get("rollback") or candidate.get("rollback") or "No-op packet; remove from consensus queue.")),
        "acceptance_criteria": list((proposal.get("acceptance") or _acceptance_for(candidate)) if has_candidate else ["packet remains proposal-only", "human review remains required"]),
        "human_review_required": True,
        "quality": {
            "complete": not missing,
            "missing_fields": missing,
            "forbidden_actions_respected": True,
            "source_clinical_facts_mutated": False,
            "git_mutated": False,
            "auto_merge_allowed": False,
        },
    }


def _agent_packet_position(*, agent_lane: str, has_candidate: bool) -> str:
    if not has_candidate:
        return "watchlist"
    positions = {
        "clinical_logic": "evaluate clinical state, gates, trials and Decision Today implications",
        "data_contract": "verify field, provenance, persistence and consumer contract",
        "ui_verification": "verify reachable UI surface, CTA and visual workflow",
        "evidence": "verify source evidence and guideline/currentness implication",
        "security": "verify PHI, permissions, headers, encryption and logs",
        "regulatory": "verify change control, traceability and review requirements",
    }
    return positions.get(agent_lane, "evaluate assigned gap")


def _select_consensus_packet(
    ready_packets: Iterable[Mapping[str, Any]],
    *,
    development_autodrive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ready = [dict(row) for row in ready_packets if row.get("candidate_id")]
    if not ready:
        return {}
    selected_id = str(
        (development_autodrive or {}).get("summary", {}).get("selected_id")
        or (development_autodrive or {}).get("selected_iteration", {}).get("id")
        or ""
    )
    if selected_id:
        for packet in ready:
            if str(packet.get("candidate_id") or "") == selected_id:
                return packet
    return sorted(
        ready,
        key=lambda row: (
            -_agent_consensus_packet_score(row),
            _agent_consensus_agent_order(str(row.get("agent_lane") or "")),
            str(row.get("candidate_title") or ""),
        ),
    )[0]


def _agent_consensus_packet_score(packet: Mapping[str, Any]) -> float:
    lane_bonus = {
        "safety_security_gap": 18,
        "critical_clinical_gap": 16,
        "data_integrity_gap": 13,
        "regulatory_traceability_gap": 11,
        "evidence_gap": 9,
        "ui_workflow_gap": 6,
    }.get(str(packet.get("development_lane") or ""), 4)
    agent_bonus = {
        "security": 7,
        "clinical_logic": 6,
        "data_contract": 5,
        "regulatory": 4,
        "evidence": 3,
        "ui_verification": 2,
    }.get(str(packet.get("agent_lane") or ""), 1)
    return (
        float(packet.get("candidate_priority_score") or 0.0)
        + float(packet.get("candidate_severity") or 0) * 2.0
        + lane_bonus
        + agent_bonus
    )


def _agent_consensus_agent_order(agent_lane: str) -> int:
    order = {
        "security": 0,
        "clinical_logic": 1,
        "data_contract": 2,
        "regulatory": 3,
        "evidence": 4,
        "ui_verification": 5,
    }
    return order.get(agent_lane, 99)


def _derive_agent_consensus_conflicts(
    packets: Iterable[Mapping[str, Any]],
    selected: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected_id = str(selected.get("candidate_id") or "")
    ready_candidates = {
        str(packet.get("candidate_id") or ""): str(packet.get("candidate_title") or "")
        for packet in packets
        if packet.get("packet_status") == "proposal_ready" and packet.get("candidate_id")
    }
    conflicts: list[dict[str, Any]] = []
    competing = sorted(candidate_id for candidate_id in ready_candidates if candidate_id and candidate_id != selected_id)
    if selected_id and competing:
        conflicts.append({
            "type": "competing_ready_candidates",
            "severity": "informational",
            "selected_candidate_id": selected_id,
            "competing_candidate_ids": competing[:5],
            "resolution": "single_iteration_rule_prioritized_highest_score_candidate",
        })
    for packet in packets:
        if (
            selected_id
            and packet.get("packet_status") == "blocked"
            and str(packet.get("candidate_id") or "") == selected_id
        ):
            conflicts.append({
                "type": "selected_candidate_blocked_by_agent",
                "severity": "blocking",
                "agent_lane": packet.get("agent_lane", ""),
                "resolution": "resolve_packet_quality_before_implementation_brief",
            })
    return conflicts


def _derive_agent_consensus_blockers(
    selected: Mapping[str, Any],
    blocked_packets: Iterable[Mapping[str, Any]],
    conflicts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not selected:
        blockers.append({
            "type": "no_proposal_ready_packet",
            "reason": "Ningún agente produjo un paquete proposal_ready para sintetizar.",
            "cta": "Completar evidencia, pruebas y rollback en 4B.",
        })
    selected_id = str(selected.get("candidate_id") or "")
    for packet in blocked_packets:
        if selected_id and str(packet.get("candidate_id") or "") == selected_id:
            blockers.append({
                "type": "selected_packet_blocked",
                "agent_lane": packet.get("agent_lane", ""),
                "reason": "El paquete seleccionado tiene bloqueo de calidad.",
                "missing_fields": list(packet.get("quality", {}).get("missing_fields") or []),
            })
    for conflict in conflicts:
        if str(conflict.get("severity") or "") == "blocking":
            blockers.append({
                "type": conflict.get("type", "blocking_conflict"),
                "reason": "Existe un conflicto bloqueante entre paquetes de agentes.",
                "agent_lane": conflict.get("agent_lane", ""),
            })
    return blockers


def _agent_consensus_status(selected: Mapping[str, Any], blocking_conditions: Iterable[Mapping[str, Any]]) -> str:
    blockers = list(blocking_conditions or [])
    if blockers:
        return "blocked"
    if selected:
        return "consensus_ready"
    return "requires_data"


def _agent_consensus_position(packet: Mapping[str, Any], *, selected: Mapping[str, Any]) -> dict[str, Any]:
    selected_id = str(selected.get("candidate_id") or "")
    packet_id = str(packet.get("candidate_id") or "")
    status = str(packet.get("packet_status") or "")
    if status == "blocked":
        vote = "block"
        reason = "Paquete bloqueado por calidad o seguridad."
    elif not packet_id:
        vote = "watchlist"
        reason = "Lane sin candidato activo; vigila sin objetar."
    elif selected_id and packet_id == selected_id:
        vote = "support"
        reason = "Paquete seleccionado para la siguiente iteración única."
    elif status == "proposal_ready":
        vote = "defer"
        reason = "Paquete listo pero diferido por regla de una mejora por iteración."
    else:
        vote = "watchlist"
        reason = "Requiere más datos antes de competir por consenso."
    return {
        "agent_lane": packet.get("agent_lane", ""),
        "agent_label": packet.get("agent_label", packet.get("agent_lane", "")),
        "vote": vote,
        "packet_status": status,
        "candidate_id": packet_id,
        "candidate_title": packet.get("candidate_title", ""),
        "reason": reason,
        "required_before_implementation": list(packet.get("quality", {}).get("missing_fields") or []),
    }


def _agent_consensus_agreement_score(
    agent_positions: Iterable[Mapping[str, Any]],
    blocked_packets: Iterable[Mapping[str, Any]],
) -> float:
    positions = [dict(row) for row in agent_positions]
    if not positions:
        return 0.0
    vote_weight = {
        "support": 1.0,
        "defer": 0.55,
        "watchlist": 0.35,
        "block": 0.0,
    }
    raw = sum(vote_weight.get(str(row.get("vote") or ""), 0.0) for row in positions) / len(positions)
    penalty = min(0.25, 0.05 * len(list(blocked_packets or [])))
    return round(max(0.0, min(100.0, (raw - penalty) * 100)), 2)


def _agent_consensus_recommendation(selected: Mapping[str, Any], consensus_status: str) -> str:
    if consensus_status == "consensus_ready" and selected:
        return (
            "Convertir el paquete seleccionado en un implementation brief revisable; "
            "mantener shadow mode y aprobación humana antes de cualquier cambio."
        )
    if consensus_status == "blocked":
        return "Resolver bloqueos de paquete antes de preparar una implementación."
    return "Esperar un paquete proposal_ready con evidencia, pruebas y rollback completos."


def _agent_consensus_rationale(
    selected: Mapping[str, Any],
    positions: Iterable[Mapping[str, Any]],
    conflicts: Iterable[Mapping[str, Any]],
) -> str:
    if not selected:
        return "No hay paquete listo para consenso."
    support = sum(1 for row in positions if row.get("vote") == "support")
    deferred = sum(1 for row in positions if row.get("vote") == "defer")
    conflict_count = len(list(conflicts or []))
    return (
        f"Seleccionado por prioridad determinística de lane, severidad y regla de una mejora por iteración; "
        f"soporte directo {support}, diferidos {deferred}, conflictos informativos {conflict_count}."
    )


def _agent_consensus_work_order(selected: Mapping[str, Any]) -> dict[str, Any]:
    if not selected:
        return {
            "available": False,
            "reason": "No hay paquete seleccionado.",
            "clinical_fact_writes_allowed": False,
            "git_mutation_allowed": False,
            "requires_human_review": True,
        }
    return {
        "available": True,
        "candidate_id": selected.get("candidate_id", ""),
        "candidate_title": selected.get("candidate_title", ""),
        "agent_lane": selected.get("agent_lane", ""),
        "development_lane": selected.get("development_lane", ""),
        "minimal_change": selected.get("minimal_change", ""),
        "tests_required": list(selected.get("tests_required") or []),
        "visual_validation_required": bool(selected.get("visual_validation_required")),
        "security_privacy_review": selected.get("security_privacy_review", "standard_no_phi_check"),
        "rollback": selected.get("rollback", ""),
        "acceptance_criteria": list(selected.get("acceptance_criteria") or []),
        "affected_states": list(selected.get("affected_states") or []),
        "surfaces": list(selected.get("surfaces") or []),
        "clinical_fact_writes_allowed": False,
        "code_execution_allowed": False,
        "git_mutation_allowed": False,
        "requires_human_review": True,
    }


def _implementation_file_scope(work_order: Mapping[str, Any]) -> list[dict[str, str]]:
    files: dict[str, str] = {
        "prostanet/agentic/autonomous_improvement_os.py": "read-model and phase contract",
        "tests/test_autonomous_improvement_os.py": "unit/API/contract regression",
    }
    surfaces = {str(surface) for surface in work_order.get("surfaces") or []}
    lane = str(work_order.get("development_lane") or "")
    agent_lane = str(work_order.get("agent_lane") or "")
    if "/loop-monitor" in surfaces or "loop-monitor" in surfaces or agent_lane in {"ui_verification", "security", "regulatory"}:
        files.update({
            "app.py": "public API endpoint contract",
            "prostanet/presentation/loop_monitor.py": "Loop Monitor snapshot integration",
            "templates/loop_monitor_dashboard.html": "Loop Monitor visual surface",
        })
    if lane == "safety_security_gap" or agent_lane == "security":
        files.setdefault("prostanet/shared/security_middleware.py", "security/header/logging policy review")
        files.setdefault(".github/workflows/autonomous_improvement_shadow_loop.yml", "shadow CI guardrails")
    if lane in {"critical_clinical_gap", "data_integrity_gap"} or agent_lane in {"clinical_logic", "data_contract"}:
        files.setdefault("prostanet/domains/patient_tracking/clinical_decision_today_fusion_kernel.py", "Decision Today alignment review")
        files.setdefault("prostanet/domains/patient_tracking/clinical_field_router.py", "capture-route contract review")
    if lane == "evidence_gap" or agent_lane == "evidence":
        files.setdefault("prostanet/shared/evidence_currentness.py", "evidence/currentness review")
    if lane == "regulatory_traceability_gap" or agent_lane == "regulatory":
        files.setdefault("docs/clinical_change_control.md", "traceability/change-control artifact")
    return [
        {"path": path, "reason": reason, "write_scope": "candidate_review"}
        for path, reason in sorted(files.items())
    ]


def _implementation_test_plan(work_order: Mapping[str, Any]) -> list[dict[str, str]]:
    tests = [str(test) for test in work_order.get("tests_required") or [] if str(test)]
    tests.extend([
        "python3 -m py_compile prostanet/agentic/autonomous_improvement_os.py app.py prostanet/presentation/loop_monitor.py",
        "pytest -q tests/test_autonomous_improvement_os.py",
    ])
    if str(work_order.get("development_lane") or "") in {"critical_clinical_gap", "data_integrity_gap"}:
        tests.append("pytest -q tests/test_decision_today_fusion_kernel.py tests/test_clinical_autodrive_command_center.py")
    if str(work_order.get("agent_lane") or "") == "security":
        tests.append("pytest -q tests/test_security_headers.py tests/test_autonomous_improvement_os.py")
    unique = []
    for test in tests:
        if test not in unique:
            unique.append(test)
    return [
        {
            "command": test,
            "required": "true",
            "execution_policy": "next_phase_only",
        }
        for test in unique
    ]


def _implementation_visual_validation_plan(work_order: Mapping[str, Any]) -> list[dict[str, str]]:
    routes = ["/loop-monitor"]
    for surface in work_order.get("surfaces") or []:
        value = str(surface or "")
        if value.startswith("/"):
            routes.append(value)
        elif value in {"profile_v2", "patient_profile_v2"}:
            routes.append("/patient_profile/<patient_ref>?v=2")
        elif value in {"decision-today", "autodrive"}:
            routes.append("/patient_profile/<patient_ref>?v=2")
        elif value == "clinical-hub":
            routes.append("/clinical-hub")
    unique = []
    for route in routes:
        if route not in unique:
            unique.append(route)
    return [
        {
            "route": route,
            "viewports": "1440x900, 390x844",
            "checks": "no console errors, no overlap, CTA visible",
        }
        for route in unique[:5]
    ]


def _implementation_security_plan(work_order: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "required": True,
        "review_type": work_order.get("security_privacy_review", "standard_no_phi_check"),
        "checks": [
            "no PHI in logs or artifacts",
            "no invented PSA/testosterone/treatment/trial eligibility",
            "source_clinical_facts_mutated remains false",
            "auto_merge remains disabled",
        ],
    }


def _implementation_rollback_plan(work_order: Mapping[str, Any]) -> dict[str, Any]:
    primary = _redact_phi_like(str(work_order.get("rollback") or "Revert the candidate patch and keep the previous read-model contract."))
    return {
        "primary": primary,
        "data_rollback_required": False,
        "clinical_fact_rollback_required": False,
        "safe_state": "keep current production logic; leave candidate in shadow review",
    }


def _implementation_change_plan(work_order: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "step": "confirm_scope",
            "description": "Reconfirm selected consensus candidate, file scope and non-goals before edits.",
            "mutation_allowed": "false",
        },
        {
            "step": "prepare_minimal_patch",
            "description": _redact_phi_like(str(work_order.get("minimal_change") or "Prepare the smallest test-backed patch.")),
            "mutation_allowed": "next_phase_only",
        },
        {
            "step": "update_tests",
            "description": "Add or update the listed regression tests before visual validation.",
            "mutation_allowed": "next_phase_only",
        },
        {
            "step": "validate_and_review",
            "description": "Run required tests, attach visual validation and request human review.",
            "mutation_allowed": "false",
        },
    ]


def _implementation_acceptance_checklist(
    work_order: Mapping[str, Any],
    test_plan: Iterable[Mapping[str, Any]],
    visual_plan: Iterable[Mapping[str, Any]],
) -> list[str]:
    checklist = list(work_order.get("acceptance_criteria") or [])
    checklist.extend([
        "implementation brief remains read-only in 4D",
        "all required tests in the brief pass in the implementation phase",
        "rollback plan is explicit and does not require clinical data mutation",
    ])
    if list(visual_plan or []):
        checklist.append("Browser visual validation is attached for required routes")
    if list(test_plan or []):
        checklist.append("test evidence is attached to the review packet")
    unique = []
    for item in checklist:
        text = _redact_phi_like(str(item))
        if text and text not in unique:
            unique.append(text)
    return unique


def _implementation_risk_register(
    consensus: Mapping[str, Any],
    work_order: Mapping[str, Any],
) -> list[dict[str, str]]:
    risks = [
        {
            "risk": "scope_creep",
            "mitigation": "one selected consensus candidate per iteration",
        },
        {
            "risk": "false_release_confidence",
            "mitigation": "Decision Today, Autodrive and safety regressions stay mandatory",
        },
    ]
    for conflict in consensus.get("conflicts") or []:
        risks.append({
            "risk": _redact_phi_like(str(conflict.get("type") or "agent_conflict")),
            "mitigation": _redact_phi_like(str(conflict.get("resolution") or "document and defer competing packets")),
        })
    if str(work_order.get("agent_lane") or "") == "security":
        risks.append({
            "risk": "security_patch_regression",
            "mitigation": "keep PHI/log/header tests in the mandatory test plan",
        })
    return risks[:6]


def _implementation_brief_blockers(
    *,
    consensus: Mapping[str, Any],
    work_order: Mapping[str, Any],
    file_scope: Iterable[Mapping[str, Any]],
    test_plan: Iterable[Mapping[str, Any]],
    selected_ready: bool,
) -> list[dict[str, Any]]:
    blockers = [dict(row) for row in consensus.get("blocking_conditions") or []]
    if not selected_ready:
        blockers.append({
            "type": "consensus_not_ready",
            "reason": "4C consensus is not ready for an implementation brief.",
        })
    if not list(file_scope or []):
        blockers.append({
            "type": "missing_file_scope",
            "reason": "Implementation brief has no bounded file scope.",
        })
    if not list(test_plan or []):
        blockers.append({
            "type": "missing_test_plan",
            "reason": "Implementation brief has no mandatory tests.",
        })
    if not work_order.get("rollback"):
        blockers.append({
            "type": "missing_rollback",
            "reason": "Implementation brief has no rollback plan from the selected packet.",
        })
    return blockers


def _shadow_patch_blueprint_blockers(
    *,
    implementation_brief: Mapping[str, Any],
    file_scope: Iterable[Mapping[str, Any]],
    test_plan: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers = [dict(row) for row in implementation_brief.get("blockers") or []]
    summary = dict(implementation_brief.get("summary") or {})
    if summary.get("brief_status") != "brief_ready":
        blockers.append({
            "type": "brief_not_ready",
            "reason": "4D implementation brief is not ready for a patch blueprint.",
        })
    if not list(file_scope or []):
        blockers.append({
            "type": "missing_file_scope",
            "reason": "Shadow patch blueprint needs at least one bounded file.",
        })
    if not list(test_plan or []):
        blockers.append({
            "type": "missing_test_plan",
            "reason": "Shadow patch blueprint needs mandatory tests.",
        })
    return blockers


def _shadow_patch_file_blueprints(
    implementation_brief: Mapping[str, Any],
    file_scope: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    brief = dict(implementation_brief.get("brief") or {})
    minimal_change = _redact_phi_like(str(brief.get("minimal_change") or "Apply the minimal test-backed change."))
    file_blueprints: list[dict[str, Any]] = []
    for index, item in enumerate(file_scope or [], start=1):
        path = str(item.get("path") or "")
        if not path:
            continue
        planned_hunks = _shadow_patch_hunks_for_file(path=path, minimal_change=minimal_change)
        file_blueprints.append({
            "order": index,
            "path": path,
            "reason": _redact_phi_like(str(item.get("reason") or "")),
            "write_scope": item.get("write_scope", "candidate_review"),
            "operation": "update",
            "planned_hunk_count": len(planned_hunks),
            "planned_hunks": planned_hunks,
            "review_risk": _shadow_patch_file_risk(path),
            "requires_manual_review": True,
        })
    return file_blueprints


def _shadow_patch_hunks_for_file(*, path: str, minimal_change: str) -> list[dict[str, str]]:
    lower = path.lower()
    if lower.endswith("autonomous_improvement_os.py"):
        return [
            {
                "target": "phase builder and summary contract",
                "intent": minimal_change,
                "constraint": "preserve shadow mode and mutation flags",
            },
            {
                "target": "quality gates and controls",
                "intent": "add explicit no-mutation, review and rollback checks",
                "constraint": "do not execute commands or write clinical facts",
            },
        ]
    if lower.endswith("app.py"):
        return [
            {
                "target": "autonomous improvement API route",
                "intent": "expose the read-model contract through a non-mutating endpoint",
                "constraint": "return explicit mutation flags as false",
            },
        ]
    if "loop_monitor.py" in lower:
        return [
            {
                "target": "snapshot and template context",
                "intent": "include the new read-model in /api/loop-monitor/snapshot and dashboard context",
                "constraint": "fallback must keep Loop Monitor available on failure",
            },
        ]
    if lower.endswith(".html"):
        return [
            {
                "target": "Loop Monitor panel",
                "intent": "render a compact clinical-technical blueprint without crowding the dashboard",
                "constraint": "desktop and mobile layouts must not overlap",
            },
        ]
    if "test_" in lower:
        return [
            {
                "target": "contract tests",
                "intent": "prove read-only flags, API contract, UI exposure and next phase",
                "constraint": "tests must not rely on external services or PHI",
            },
        ]
    return [
        {
            "target": "bounded file scope",
            "intent": minimal_change,
            "constraint": "apply only if human review authorizes the next phase",
        },
    ]


def _shadow_patch_file_risk(path: str) -> str:
    lower = path.lower()
    if lower.endswith("app.py") or "security" in lower:
        return "high"
    if "domains/patient_tracking" in lower:
        return "high"
    if "templates" in lower or "presentation" in lower:
        return "medium"
    return "low"


def _shadow_patch_sequence(file_blueprints: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "tests/test_autonomous_improvement_os.py": 0,
        "prostanet/agentic/autonomous_improvement_os.py": 1,
        "app.py": 2,
        "prostanet/presentation/loop_monitor.py": 3,
        "templates/loop_monitor_dashboard.html": 4,
    }
    rows = sorted(
        [dict(row) for row in file_blueprints or []],
        key=lambda row: (priority.get(str(row.get("path") or ""), 20), int(row.get("order") or 99)),
    )
    return [
        {
            "step": index,
            "path": row.get("path", ""),
            "action": "plan_update_only",
            "planned_hunks": row.get("planned_hunk_count", 0),
            "requires_human_authorization": True,
        }
        for index, row in enumerate(rows, start=1)
    ]


def _shadow_patch_rollback_blueprint(
    implementation_brief: Mapping[str, Any],
    file_blueprints: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rollback = dict(implementation_brief.get("rollback_plan") or {})
    return {
        "primary": rollback.get("primary", "Discard the planned patch blueprint."),
        "file_level": [
            {
                "path": row.get("path", ""),
                "rollback_action": "revert planned hunks before merge",
            }
            for row in file_blueprints or []
        ],
        "data_rollback_required": False,
        "clinical_fact_rollback_required": False,
        "safe_state": rollback.get("safe_state", "keep current production logic"),
    }


def _build_local_git_snapshot(*, branch_name: str) -> dict[str, Any]:
    snapshot = {
        "available": False,
        "current_branch": "",
        "target_branch": _redact_phi_like(branch_name),
        "branch_present": False,
        "dirty_file_count": 0,
        "dirty_files_sample": [],
        "inspection_only": True,
        "git_mutated": False,
    }
    try:
        current = _run_git_readonly(["rev-parse", "--abbrev-ref", "HEAD"])
        branch_list = _run_git_readonly(["branch", "--list", branch_name]) if branch_name else ""
        status = _run_git_readonly(["status", "--short"])
        dirty_lines = [
            _redact_phi_like(line.strip())
            for line in status.splitlines()
            if line.strip()
        ]
        snapshot.update({
            "available": True,
            "current_branch": _redact_phi_like(current.strip()),
            "branch_present": bool(branch_list.strip()),
            "dirty_file_count": len(dirty_lines),
            "dirty_files_sample": dirty_lines[:12],
        })
    except Exception as exc:
        snapshot["error"] = _redact_phi_like(str(exc))
    return snapshot


def _run_git_readonly(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        timeout=4,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout or ""


def _pr_review_monitor_blockers(
    *,
    monitor_status: str,
    handoff_ready: bool,
    pull_request_detected: bool,
    branch_present: bool,
    ci_status: str,
    review_status: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not handoff_ready:
        blockers.append({
            "severity": "blocked",
            "message": "Falta handoff 3F listo; no se puede monitorizar PR antes de aprobación/handoff.",
            "next_step": "Completar aprobación 3E y handoff 3F.",
        })
    if handoff_ready and not branch_present:
        blockers.append({
            "severity": "pending",
            "message": "La rama sugerida aún no existe localmente.",
            "next_step": "Crear rama manual sólo después de aprobar 3F.",
        })
    if handoff_ready and not pull_request_detected:
        blockers.append({
            "severity": "pending",
            "message": "No hay PR draft registrado para esta rama.",
            "next_step": "Abrir PR draft manual y registrar metadata local.",
        })
    if pull_request_detected and ci_status != "passed":
        blockers.append({
            "severity": "blocked" if ci_status in {"failed", "cancelled"} else "pending",
            "message": f"CI no está aprobado: {ci_status}.",
            "next_step": "Esperar CI o corregir fallos antes de revisión de merge.",
        })
    if pull_request_detected and review_status != "approved":
        blockers.append({
            "severity": "blocked" if review_status in {"blocked", "changes_requested"} else "pending",
            "message": f"Revisión humana del PR no aprobada: {review_status}.",
            "next_step": "Resolver comentarios o solicitar aprobación clínica/técnica.",
        })
    if monitor_status == "validated_pending_human_merge":
        return []
    return blockers


def _pr_review_monitor_findings(
    *,
    local_git: Mapping[str, Any],
    metadata: Mapping[str, Any],
    monitor_status: str,
) -> list[dict[str, Any]]:
    findings = [
        {
            "severity": "info",
            "message": "3G inspecciona estado y metadata; no ejecuta git, gh ni merge.",
        }
    ]
    dirty_count = int(local_git.get("dirty_file_count") or 0)
    if dirty_count:
        findings.append({
            "severity": "warning",
            "message": f"Working tree con {dirty_count} cambios; el PR debe stagear sólo archivos del paquete.",
        })
    if metadata:
        findings.append({
            "severity": "info",
            "message": f"Metadata PR registrada con CI={metadata.get('ci_status', 'unknown')} y review={metadata.get('review_status', 'pending')}.",
        })
    if monitor_status == "validated_pending_human_merge":
        findings.append({
            "severity": "human_review_required",
            "message": "CI y review reportan aprobado; falta decisión humana final de merge fuera del monitor.",
        })
    return findings


def _pr_review_monitor_required_actions(*, monitor_status: str, branch_name: str) -> list[dict[str, Any]]:
    if monitor_status == "blocked_until_handoff_ready":
        return [{
            "action": "complete_3e_3f",
            "label": "Completar aprobación humana y handoff PR",
            "cta": "/loop-monitor",
        }]
    if monitor_status in {"no_pr_yet", "branch_ready_no_pr"}:
        return [{
            "action": "create_manual_draft_pr",
            "label": "Crear PR draft manual desde la rama sugerida",
            "branch_name": _redact_phi_like(branch_name),
            "cta": "/loop-monitor",
        }]
    if monitor_status == "ci_running":
        return [{"action": "wait_for_ci", "label": "Esperar resultado de CI", "cta": "/loop-monitor"}]
    if monitor_status == "changes_requested":
        return [{"action": "resolve_review_comments", "label": "Resolver cambios solicitados", "cta": "/loop-monitor"}]
    if monitor_status == "blocked":
        return [{"action": "fix_ci_or_review_blocker", "label": "Corregir bloqueo de CI/review", "cta": "/loop-monitor"}]
    if monitor_status == "validated_pending_human_merge":
        return [{
            "action": "human_merge_review",
            "label": "Revisión humana final antes de merge",
            "cta": "/loop-monitor",
        }]
    return [{"action": "monitor_pr", "label": "Continuar vigilancia del PR", "cta": "/loop-monitor"}]


def _draft_pr_handoff_files(package: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    implementation = dict((package or {}).get("implementation_plan") or {})
    file_targets = implementation.get("file_targets") or []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in file_targets:
        if not isinstance(raw, Mapping):
            continue
        path = _redact_phi_like(str(raw.get("path") or "")).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        rows.append({
            "path": path,
            "reason": _redact_phi_like(str(raw.get("reason") or raw.get("change") or "planned change")),
            "stage_now": False,
        })
    if not rows:
        candidate = dict((package or {}).get("candidate") or {})
        for surface in candidate.get("surfaces") or []:
            path = _redact_phi_like(str(surface or "")).strip()
            if path and path not in seen:
                seen.add(path)
                rows.append({"path": path, "reason": "surface affected by candidate", "stage_now": False})
    return rows[:24]


def _draft_pr_handoff_commands(
    *,
    package: Mapping[str, Any] | None,
    branch_name: str,
    manual_handoff_ready: bool,
    handoff_status: str,
) -> list[dict[str, Any]]:
    draft = dict((package or {}).get("draft_pr") or {})
    file_paths = [row.get("path", "") for row in _draft_pr_handoff_files(package)]
    add_targets = " ".join(_shell_quote_arg(path) for path in file_paths if path) or "."
    base_branch = _shell_quote_arg(str(draft.get("base_branch") or "main"))
    title = _shell_quote_arg(str(draft.get("title") or "ProstaMed autonomous improvement"))
    branch = _shell_quote_arg(branch_name)
    blocked_until = "" if manual_handoff_ready else handoff_status
    commands = [
        ("git status --short", "confirmar cambios locales antes de crear rama"),
        (f"git checkout -b {branch}", "crear rama codex/ sólo si el revisor lo aprueba"),
        (f"git add -- {add_targets}", "stagear exclusivamente archivos del paquete revisado"),
        (
            "pytest -q tests/test_autonomous_improvement_os.py tests/test_decision_today_fusion_kernel.py",
            "ejecutar regresión mínima antes de abrir PR",
        ),
        (
            f"git commit -m {_shell_quote_arg('[Autodrive] draft clinical improvement handoff')}",
            "crear commit revisable si las pruebas pasan",
        ),
        (
            f"gh pr create --draft --base {base_branch} --head {branch} --title {title} --body-file <reviewed-shadow-pr-body.md>",
            "abrir PR draft manual con body revisado",
        ),
    ]
    return [
        {
            "cmd": _redact_phi_like(cmd),
            "purpose": purpose,
            "manual_only": True,
            "execute_now": False,
            "blocked_until": blocked_until,
        }
        for cmd, purpose in commands
    ]


def _draft_pr_handoff_review_checklist(
    *,
    artifact_verified: bool,
    human_approved: bool,
    manual_handoff_ready: bool,
) -> list[dict[str, Any]]:
    rows = [
        ("artifact_verified", "Artifact 3D verificado", artifact_verified),
        ("human_approved", "Decisión humana 3E aprobó handoff a PR", human_approved),
        ("no_auto_merge", "Auto-merge permanece desactivado", True),
        ("no_clinical_fact_mutation", "No muta hechos clínicos ni datos fuente", True),
        ("manual_only_git", "Rama, commit y PR son pasos manuales", True),
        ("ready_for_handoff", "Paquete listo para handoff manual", manual_handoff_ready),
    ]
    return [
        {"key": key, "label": label, "passed": bool(passed)}
        for key, label, passed in rows
    ]


def _draft_pr_handoff_blockers(
    *,
    handoff_status: str,
    artifact_verified: bool,
    human_approved: bool,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if handoff_status == "blocked_no_shadow_package":
        blockers.append({
            "severity": "blocked",
            "message": "No existe paquete Shadow PR Factory para preparar handoff.",
            "next_step": "Regresar a Fase 3B.",
        })
    if not artifact_verified:
        blockers.append({
            "severity": "blocked",
            "message": "Falta artifact 3D verificado con tests y validación visual.",
            "next_step": "Completar Fase 3D.",
        })
    if artifact_verified and not human_approved:
        blockers.append({
            "severity": "human_review_required",
            "message": "Falta aprobación humana explícita approve_for_pr en Fase 3E.",
            "next_step": "Registrar decisión humana antes de crear rama o PR.",
        })
    return blockers


def _shell_quote_arg(value: str) -> str:
    text = _redact_phi_like(str(value or ""))
    return "'" + text.replace("'", "'\"'\"'") + "'"


def load_proposal_reviews() -> dict[str, dict[str, Any]]:
    """Latest review event per proposal id."""
    if not REVIEW_LOG.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    with REVIEW_LOG.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            proposal_id = str(event.get("proposal_id") or "")
            if proposal_id:
                latest[proposal_id] = event
    return latest


def _build_context(*, patient_limit: int) -> dict[str, Any]:
    compliance_snapshot = {}
    ranked_gaps: list[tuple[float, Any]] = []
    try:
        from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
        from prostanet.agentic.gap_prioritizer import rank_gaps

        snap = compute_compliance_snapshot(persist=False)
        compliance_snapshot = snap.to_dict()
        ranked_gaps = rank_gaps(snap)[:12]
    except Exception as exc:
        compliance_snapshot = {"error": str(exc), "aggregate": 0, "scores": {}}

    loop_summary = {}
    try:
        from prostanet.presentation.loop_monitor import get_vector_summary

        loop_summary = get_vector_summary(days=30)
    except Exception as exc:
        loop_summary = {"error": str(exc)}

    contracts = {}
    try:
        from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
            build_autodrive_contract_matrix,
            summarize_autodrive_contracts,
        )

        matrix = build_autodrive_contract_matrix()
        contracts = summarize_autodrive_contracts(matrix)
        contracts["matrix_count"] = len(matrix)
    except Exception as exc:
        contracts = {"error": str(exc)}

    patients = _scan_patient_decision_today(limit=patient_limit)
    contractual_gap_rows = derive_contractual_gap_rows(patients)
    application_telemetry = build_application_telemetry(
        patient_summary=patients,
        contractual_gap_rows=contractual_gap_rows,
    )
    contradiction_rows = _scan_patient_contradictions(limit=patient_limit)
    patient_twin_available = (PROJECT_ROOT / "prostanet" / "domains" / "patient_tracking" / "patient_twin_os.py").exists()
    # EPIC 17b: detectar AI substrate (4 models entrenados + loadables) sin
    # ejecutar inference real para no penalizar requests del Loop Monitor.
    # Solo verifica file existence + size > 1KB para cada artifact esperado.
    ai_substrate = _detect_ai_substrate_ready()
    return {
        "compliance_snapshot": compliance_snapshot,
        "compliance_ranked_gaps": ranked_gaps,
        "loop_summary": loop_summary,
        "contracts": contracts,
        "patients": patients,
        "contractual_gap_rows": contractual_gap_rows,
        "application_telemetry": application_telemetry,
        "contradiction_rows": contradiction_rows,
        "patient_twin_available": patient_twin_available,
        "patient_twin_ai_substrate_ready": ai_substrate["ready"],
        "patient_twin_ai_substrate": ai_substrate,
        "generated_at": _now_iso(),
    }


def _detect_ai_substrate_ready() -> dict[str, Any]:
    """EPIC 17b: Check if the 4 AI model artifacts exist + are non-trivial.

    Lightweight: file stat only. Validates that EPIC 16 + 17 training run
    completed successfully so Patient Twin readiness can honestly reflect
    AI infrastructure availability without exercising inference per request.
    """
    models_dir = PROJECT_ROOT / "output" / "models"
    expected = {
        "state_transition": models_dir / "state_transition" / "best.pt",
        "treatment_response": models_dir / "treatment_response" / "best.pt",
        "deep_surv": models_dir / "deep_surv_OS" / "best.pt",
        "anomaly_detector": models_dir / "anomaly_detector" / "best.pt",
    }
    per_model = {}
    for mid, path in expected.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        per_model[mid] = {
            "artifact_path": str(path),
            "exists": exists,
            "size_bytes": size,
            "non_trivial": size > 1024,
        }
    ready_count = sum(1 for m in per_model.values() if m["non_trivial"])
    return {
        "ready": ready_count == len(expected),
        "ready_count": ready_count,
        "total_count": len(expected),
        "per_model": per_model,
    }


def _scan_patient_decision_today(*, limit: int) -> dict[str, Any]:
    rows = _patient_refs(limit=limit)
    states = Counter()
    decision_states = Counter()
    missing_fields = Counter()
    blockers = Counter()
    samples: list[str] = []
    errors: list[str] = []
    evaluated = 0

    for row in rows:
        patient_id = row.get("id")
        ref = str(row.get("nss") or patient_id or "")
        try:
            import tracking_db
            from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import build_decision_today

            record = tracking_db.get_patient_full_record(patient_id)
            bundle = tracking_db.refresh_longitudinal_intelligence(
                patient_id,
                force_recompute=False,
                record=record,
                include_live_benchmark=False,
            ) or {}
            decision = build_decision_today(record, longitudinal_bundle=bundle, patient_ref=ref)
            state = str(decision.get("state") or decision.get("clinical_state") or "")
            dstate = str(decision.get("decision_state") or "not_actionable")
            states[state or "unknown"] += 1
            decision_states[dstate] += 1
            evaluated += 1
            if dstate in {"blocked", "requires_data", "urgent_safety", "redecision_required"}:
                samples.append(_mask_ref(ref))
                for field in decision.get("unified_missing_fields") or []:
                    if isinstance(field, Mapping):
                        key = str(field.get("field") or field.get("key") or field.get("label") or "unknown")
                    else:
                        key = str(field)
                    missing_fields[key] += 1
                blockers[str(decision.get("decision_today") or decision.get("dominant_blocker") or dstate)] += 1
        except Exception as exc:
            errors.append(f"{_mask_ref(ref)}:{type(exc).__name__}")
            if len(errors) >= 8:
                break

    return {
        "scanned": len(rows),
        "evaluated": evaluated,
        "state_counts": dict(states),
        "decision_state_counts": dict(decision_states),
        "missing_fields_top": missing_fields.most_common(12),
        "blockers_top": blockers.most_common(8),
        "sample_ref_hints": samples[:8],
        "errors": errors,
    }


def _scan_patient_contradictions(*, limit: int) -> list[dict[str, Any]]:
    """Scan live patient read-models for Phase 2B cross-module contradictions."""
    rows = _patient_refs(limit=limit)
    out: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in rows:
        patient_id = row.get("id")
        ref = str(row.get("nss") or patient_id or "")
        try:
            import tracking_db
            from prostanet.domains.patient_tracking.clinical_autodrive_command_center import build_patient_autodrive
            from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import build_decision_today

            record = tracking_db.get_patient_full_record(
                patient_id,
                include_derivatives=False,
                include_ledger=False,
            )
            if not record:
                continue
            bundle = tracking_db.refresh_longitudinal_intelligence(
                patient_id,
                force_recompute=False,
                record=record,
                include_live_benchmark=False,
            ) or {}
            signals = dict(bundle.get("signals") or record.get("latest_signal_snapshot") or {})
            state = str(
                signals.get("effective_state_final")
                or signals.get("effective_state")
                or signals.get("reconciled_state")
                or (record.get("latest_assessment") or {}).get("state")
                or (record.get("prior_history") or {}).get("current_state")
                or ""
            )
            management_track = str(
                signals.get("effective_management_track_final")
                or signals.get("effective_management_track")
                or signals.get("reconciled_management_track")
                or ""
            )
            autodrive = build_patient_autodrive(
                record,
                longitudinal_bundle=bundle,
                state=state,
                management_track=management_track,
                patient_ref=ref,
            )
            decision_today = autodrive.get("decision_today") or build_decision_today(
                record,
                longitudinal_bundle=bundle,
                clinical_autodrive=autodrive,
                state=state,
                management_track=management_track,
                patient_ref=ref,
            )
            source_bundle = {
                "patient_ref": ref,
                "patient": record,
                "state": state,
                "decision_today": decision_today,
                "clinical_autodrive": autodrive,
                "clinical_readiness_tower": bundle.get("clinical_readiness_tower") or (bundle.get("signals") or {}).get("clinical_readiness_tower") or {},
                "tumor_board_os": bundle.get("tumor_board_os") or (bundle.get("signals") or {}).get("tumor_board_os") or {},
                "care_pathway_os": bundle.get("care_pathway_os") or (bundle.get("signals") or {}).get("care_pathway_os") or {},
                "clinical_memory_os": bundle.get("clinical_memory_os") or (bundle.get("signals") or {}).get("clinical_memory_os") or {},
                "longitudinal_truth_snapshot": bundle.get("longitudinal_truth_snapshot") or {},
            }
            out.extend(derive_contradiction_rows(source_bundle))
        except Exception as exc:
            errors.append({
                "rule_id": "contradiction_scan_error",
                "severity": 5,
                "patient_ref_hint": _mask_ref(ref),
                "evidence": [type(exc).__name__],
                "status": "scan_error",
            })
            if len(errors) >= 8:
                break
    return (out + errors)[:80]


def _patient_refs(*, limit: int) -> list[dict[str, Any]]:
    try:
        import tracking_db

        db_path = Path(getattr(tracking_db, "DB_PATH", "") or getattr(tracking_db, "DEFAULT_DB_PATH", ""))
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, nss FROM patient_identity ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?",
            (max(1, min(int(limit or 35), 120)),),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _patient_twin_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    if context.get("patient_twin_available"):
        return []
    application = {
        str(row.get("contract_id") or ""): dict(row)
        for row in ((context.get("application_telemetry") or {}).get("implementations") or [])
    }
    twin_application = application.get("patient_twin_preference_pro_minimum", {})
    if twin_application.get("software_gap_closed"):
        return []
    twin_contract = _contract_by_id("patient_twin_preference_pro_minimum")
    return [_candidate(
        lane="critical_clinical_gap",
        title="Implement Patient Twin & Preference OS readiness layer",
        description=(
            "Decision Today can be correct but still incomplete without patient "
            "values, PRO baseline, trajectory thresholds and a safe simulation "
            "readiness contract."
        ),
        clinical_impact=10,
        severity=9,
        effort_h=6.0,
        risk_avoided="Avoids releasing technically correct decisions that ignore preference-sensitive tradeoffs.",
        source="goal_registry.patient_twin_readiness",
        evidence=[
            "FDA Patient-Focused Drug Development",
            "FDA Clinical Outcome Assessment guidance",
            "NCI PRO-CTCAE",
            "EAU prostate cancer quality-of-life follow-up principles",
        ],
        tests_required=[
            "test_patient_twin_requires_preferences_and_pro_baseline",
            "test_decision_today_marks_preference_sensitive_decision_requires_data",
            "test_patient_twin_never_simulates_with_missing_psa_or_treatment",
        ],
        surfaces=["patient_profile_v2", "longitudinal-capture", "decision-today", "clinical-memory-os"],
        affected_states=["localized_initial", "recurrence_bcr", "m0_crpc", "m1_crpc"],
        patient_scope={"affected_count": context.get("patients", {}).get("evaluated", 0)},
        clinical_contract=twin_contract,
        contract_gaps=[{
            "contract_id": twin_contract.get("contract_id"),
            "required_fields": twin_contract.get("required_fields", []),
            "capture_surface": twin_contract.get("capture_surface", ""),
            "persistence": twin_contract.get("persistence", ""),
            "consumer": twin_contract.get("consumer", ""),
        }],
        agent_lane="clinical_logic",
        rollback="Disable Patient Twin panel and remove it from Decision Today source_alignment.",
    )]


def _contractual_clinical_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = list(context.get("contractual_gap_rows") or [])
    out: list[dict[str, Any]] = []
    for row in rows[:5]:
        if row.get("software_gap_closed"):
            continue
        contract = _contract_by_id(str(row.get("contract_id") or ""))
        matched = row.get("matched_missing_fields") or []
        affected = int(row.get("triggered_state_count") or 0)
        if not affected and not matched:
            continue
        missing_label = ", ".join(str(item.get("field")) for item in matched[:5]) or "decisive fields not complete"
        lane = "critical_clinical_gap" if int(row.get("severity") or 0) >= 9 else "data_integrity_gap"
        out.append(_candidate(
            lane=lane,
            title=f"Contractual clinical gap: {row.get('label')}",
            description=(
                f"Phase 2A contract {row.get('contract_id')} is active in {affected} scanned patients "
                f"or matched missing fields: {missing_label}."
            ),
            clinical_impact=min(10, max(7, int(row.get("severity") or 7))),
            severity=int(row.get("severity") or 7),
            effort_h=2.5 if matched else 3.5,
            risk_avoided=str(row.get("risk_avoided") or contract.get("risk_avoided") or "Avoids incomplete clinical release."),
            source=f"clinical_gap_contract_registry.{row.get('contract_id')}",
            evidence=[
                "Decision Today missing-field scan",
                "Clinical Field Router capture contract",
                "Readiness/Tumor Board/Care Pathway consumer alignment",
            ],
            tests_required=list(row.get("tests") or contract.get("tests") or ["test_clinical_gap_contract_has_route"]),
            surfaces=[
                str(row.get("capture_surface") or contract.get("capture_surface") or "longitudinal-capture"),
                str(row.get("consumer") or contract.get("consumer") or "decision-today"),
            ],
            affected_states=list(contract.get("trigger_states") or []),
            patient_scope={
                "affected_count": affected,
                "matched_missing_fields": matched,
                "sample_ref_hints": (context.get("patients") or {}).get("sample_ref_hints", []),
            },
            clinical_contract=contract,
            contract_gaps=[row],
            agent_lane="data_contract" if lane == "data_integrity_gap" else "clinical_logic",
            rollback="Keep Decision Today in requires_data and remove this contract change from the proposal queue.",
        ))
    return out


def _contradiction_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in (context.get("contradiction_rows") or []) if row.get("rule_id") != "contradiction_scan_error"]
    if not rows:
        return []
    registry = {rule["rule_id"]: rule for rule in build_contradiction_rule_registry()}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("rule_id") or "unknown")].append(row)

    out: list[dict[str, Any]] = []
    for rule_id, group in sorted(grouped.items(), key=lambda item: (-max(int(r.get("severity") or 0) for r in item[1]), item[0])):
        rule = registry.get(rule_id, {"label": rule_id, "severity": 8, "risk_avoided": "Avoids incoherent clinical release.", "tests": []})
        severity = int(rule.get("severity") or max(int(r.get("severity") or 0) for r in group))
        lane = "critical_clinical_gap" if severity >= 9 else "data_integrity_gap"
        states = sorted({str(row.get("state") or "unknown") for row in group if row.get("state")})
        hints = sorted({str(row.get("patient_ref_hint") or "") for row in group if row.get("patient_ref_hint")})[:8]
        evidence = [
            f"{len(group)} active contradiction(s) for {rule.get('label')}",
            str(rule.get("violation") or ""),
            "Decision Today/Readiness/Tumor Board/Care Pathway/Memory alignment scan",
        ]
        out.append(_candidate(
            lane=lane,
            title=f"Resolve contradiction: {rule.get('label')}",
            description=(
                f"Phase 2B found {len(group)} patient-level contradiction(s) for rule {rule_id}. "
                "The next proposal must harmonize source precedence, blockers and CTAs before clinical release."
            ),
            clinical_impact=10 if severity >= 9 else 8,
            severity=severity,
            effort_h=2.0 if rule_id == "missing_field_without_capture_route" else 3.0,
            risk_avoided=str(rule.get("risk_avoided") or "Avoids incoherent clinical decisions."),
            source=f"contradiction_rule_registry.{rule_id}",
            evidence=evidence,
            tests_required=list(rule.get("tests") or ["test_contradiction_rule_has_regression"]),
            surfaces=list(rule.get("sources") or []) + ["decision-today", "profile_v2", "autodrive"],
            affected_states=states,
            patient_scope={
                "affected_count": len(group),
                "sample_ref_hints": hints,
                "rule_id": rule_id,
            },
            clinical_contract=_contract_for_contradiction(rule_id),
            contradictions=group[:10],
            agent_lane="clinical_logic" if lane == "critical_clinical_gap" else "data_contract",
            rollback="Keep the affected decision in requires_data and hide releaseable/executable surfaces until bundles align.",
        ))
    return out


def _decision_today_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    patients = dict(context.get("patients") or {})
    counts = Counter(patients.get("decision_state_counts") or {})
    blocked = sum(counts.get(k, 0) for k in ("blocked", "requires_data", "urgent_safety", "redecision_required"))
    evaluated = int(patients.get("evaluated") or 0)
    if not evaluated or not blocked:
        return []
    missing = patients.get("missing_fields_top") or []
    contractual_rows = derive_contractual_gap_rows(patients)
    closed_fields = {
        str(item.get("field") or "").lower()
        for row in contractual_rows
        if row.get("software_gap_closed")
        for item in (row.get("matched_missing_fields") or [])
    }
    open_contract_rows = [row for row in contractual_rows if not row.get("software_gap_closed")]
    missing_labels = [
        str(pair[0] if isinstance(pair, (list, tuple)) and pair else pair.get("field") if isinstance(pair, Mapping) else pair)
        for pair in missing[:8]
    ]
    open_missing_labels = [label for label in missing_labels if label.lower() not in closed_fields]
    if not open_missing_labels and not open_contract_rows:
        return []
    if not open_missing_labels:
        return []
    title = _decision_today_gap_title(open_missing_labels)
    return [_candidate(
        lane="data_integrity_gap" if open_missing_labels else "critical_clinical_gap",
        title=title,
        description=(
            f"{blocked}/{evaluated} scanned patients have Decision Today blocked or requiring data. "
            f"Dominant missing fields: {', '.join(open_missing_labels[:5]) or 'not classified'}."
        ),
        clinical_impact=9,
        severity=8,
        effort_h=3.0,
        risk_avoided="Avoids incomplete release, delayed salvage/CRPC decisions, and duplicate manual data hunts.",
        source="clinical_decision_today_fusion_kernel",
        evidence=[
            "Internal Decision Today Fusion Kernel audit",
            "Clinical Field Router capture contract",
            "Autodrive blocked_by_data lane",
        ],
        tests_required=[
            "test_decision_today_missing_fields_have_capture_surface",
            "test_longitudinal_accepts_decision_field_prefilter",
            "test_dashboard_patients_profile_show_same_decision_today",
        ],
        surfaces=["dashboard", "patients", "patient_profile_v2", "longitudinal-capture"],
        affected_states=list((patients.get("state_counts") or {}).keys())[:8],
        patient_scope={
            "affected_count": blocked,
            "evaluated_count": evaluated,
            "sample_ref_hints": patients.get("sample_ref_hints", []),
            "missing_fields_top": [
                item for item in missing[:8]
                if (
                    str(item[0] if isinstance(item, (list, tuple)) and item else item.get("field") if isinstance(item, Mapping) else item).lower()
                    not in closed_fields
                )
            ],
        },
        contract_gaps=open_contract_rows[:8],
        agent_lane="data_contract",
        rollback="Revert Field Router mapping changes and keep Decision Today requiring data.",
    )]


def _decision_today_gap_title(missing_fields: Iterable[str]) -> str:
    fields = [str(field or "").strip() for field in missing_fields if str(field or "").strip()]
    if not fields:
        return "Close dominant fields blocking canonical Decision Today"
    first = _decision_today_field_label(fields[0])
    if len(fields) == 1:
        return f"Resolve {first} blocking canonical Decision Today"
    return f"Resolve {first} and related fields blocking canonical Decision Today"


def _decision_today_field_label(field: str) -> str:
    labels = {
        "repeat_psa_value": "repeat PSA confirmation",
        "psa_density": "PSA density",
        "mri_pirads_score": "mpMRI PI-RADS",
        "biopsy_status": "biopsy status",
        "family_history": "family history",
        "germline_risk": "germline risk",
        "psa_doubling_time_months": "PSA doubling time",
        "salvage_context_marker": "BCR/Phoenix context",
        "patient_values": "patient values",
        "baseline_pro": "baseline PRO",
        "bowel_function_baseline": "baseline bowel function",
        "testosterone": "testosterone",
        "testosterone_value": "testosterone",
    }
    return labels.get(field, field.replace("_", " "))


def _contract_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    contracts = dict(context.get("contracts") or {})
    out: list[dict[str, Any]] = []
    if not contracts.get("gates_coverage_ok", False):
        out.append(_candidate(
            lane="critical_clinical_gap",
            title="Map every pivotal gate to capture, persistence and consumer",
            description=(
                f"Gate contract reports {contracts.get('gates_contract_covered', 0)}/"
                f"{contracts.get('gates_total', 0)} gates covered."
            ),
            clinical_impact=10,
            severity=10,
            effort_h=4.0,
            risk_avoided="Avoids silent non-evaluation of pivotal clinical criteria.",
            source="autodrive_contract_matrix",
            evidence=["103 pivotal gates contract requirement", "Readiness Tower gate matrix"],
            tests_required=["test_103_gates_have_capture_persistence_consumer_contract"],
            surfaces=["clinical-field-router", "readiness", "decision-today"],
            agent_lane="clinical_logic",
            rollback="Restore previous gate contract matrix and block releaseable decisions if coverage falls.",
        ))
    if not contracts.get("trials_contract_ok", False):
        out.append(_candidate(
            lane="critical_clinical_gap",
            title="Enforce 47 pivotal trials as requires_data on empty payload",
            description="Trial contract is not fully proving that empty payloads avoid eligible=true.",
            clinical_impact=9,
            severity=9,
            effort_h=2.5,
            risk_avoided="Avoids false trial eligibility from missing data.",
            source="trial_empty_payload_contract",
            evidence=["ClinicalTrials.gov pivotal criteria", "Internal 47-trial evaluator contract"],
            tests_required=["test_47_trials_empty_payload_requires_data_never_eligible"],
            surfaces=["tumor-board-os", "decision-today", "trials-panel"],
            agent_lane="clinical_logic",
            rollback="Revert evaluator changes and force trials to non-evaluable when critical fields are missing.",
        ))
    return out


def _compliance_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    ranked = context.get("compliance_ranked_gaps") or []
    out: list[dict[str, Any]] = []
    for score, gap in ranked[:4]:
        try:
            gap_dict = gap.to_dict()
        except Exception:
            gap_dict = dict(gap or {})
        lane = _lane_from_gap(gap_dict)
        candidate = _candidate(
            lane=lane,
            title=f"Resolve compliance gap: p{gap_dict.get('pillar_id')}.{gap_dict.get('kind')}",
            description=str(gap_dict.get("description") or "Compliance gap detected by agentic scorer."),
            clinical_impact=min(10, max(3, int(gap_dict.get("severity") or 5))),
            severity=int(gap_dict.get("severity") or 5),
            effort_h=float(gap_dict.get("effort_h") or 1.0),
            risk_avoided="Avoids regulatory traceability, safety or validation debt before clinical expansion.",
            source=str(gap_dict.get("evidence_source") or "compliance_scorer"),
            evidence=[str(gap_dict.get("evidence_source") or "FDA SaMD compliance scorer")],
            tests_required=[
                "test_autonomous_improvement_proposal_requires_evidence_and_tests",
                "test_safety_gates_block_clinical_proposal_without_tests",
            ],
            surfaces=[str(gap_dict.get("artifact_path") or "prostanet/agentic")],
            agent_lane="regulatory" if lane == "regulatory_traceability_gap" else "security" if lane == "safety_security_gap" else "evidence",
            rollback="Revert the associated small compliance patch or mark candidate rejected.",
        )
        candidate = escalate_stuck_candidate(candidate, consecutive_count=_proposal_streak(gap_dict))
        out.append(candidate)
    return out


def _loop_monitor_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary = dict(context.get("loop_summary") or {})
    out = []
    ui = summary.get("ui_ergonomy") or {}
    perf = summary.get("performance_a11y") or {}
    evidence = summary.get("clinical_evidence") or {}
    if not ui.get("count") or not perf.get("count"):
        out.append(_candidate(
            lane="ui_workflow_gap",
            title="Add required visual validation artifact for core clinical surfaces",
            description="Loop Monitor has no recent UI ergonomics or performance/a11y validation evidence.",
            clinical_impact=6,
            severity=6,
            effort_h=2.0,
            risk_avoided="Avoids hidden UI overlap, unreachable CTAs and capture friction in clinical workflows.",
            source="loop_monitor.ui_ergonomy.performance_a11y",
            evidence=["Browser visual validation requirement", "Loop Monitor 30-day vector summary"],
            tests_required=[
                "test_loop_monitor_mission_control_renders",
                "visual_validation_dashboard_patients_profile_clinical_hub_mobile",
            ],
            surfaces=["loop-monitor", "dashboard", "patients", "patient_profile_v2", "clinical-hub"],
            agent_lane="ui_verification",
            rollback="Remove added validation card and keep existing Loop Monitor vectors.",
        ))
    if not evidence.get("count"):
        out.append(_candidate(
            lane="evidence_gap",
            title="Run weekly evidence refresh candidate review",
            description="No recent clinical evidence loop iteration is visible in the 30-day Loop Monitor summary.",
            clinical_impact=7,
            severity=6,
            effort_h=1.5,
            risk_avoided="Avoids stale recommendations after EAU/FDA/ClinicalTrials.gov changes.",
            source="loop_monitor.clinical_evidence",
            evidence=["EAU prostate cancer", "FDA oncology approvals", "ClinicalTrials.gov"],
            tests_required=[
                "test_evidence_change_candidate_requires_human_review",
                "test_evidence_loop_does_not_change_recommendations_automatically",
            ],
            surfaces=["evidence-refresh-loop", "tumor-board-os", "decision-today"],
            agent_lane="evidence",
            rollback="Disable evidence candidate display; no clinical logic is changed by this proposal.",
        ))
    return out


def _security_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    snapshot = dict(context.get("compliance_snapshot") or {})
    p6 = ((snapshot.get("scores") or {}).get("p6") or {})
    score = float(p6.get("score") or 0.0)
    out = []
    if score and score < 96:
        out.append(_candidate(
            lane="safety_security_gap",
            title="Close PHI/security gaps before any autonomous clinical loop expansion",
            description=f"Security pillar p6 score is {score:.1f}%, below the autonomous-loop target.",
            clinical_impact=8,
            severity=8,
            effort_h=3.0,
            risk_avoided="Avoids PHI leakage, unsafe headers, weak audit or unsafe cloud use.",
            source="compliance_scorer.p6",
            evidence=["FDA Premarket Cybersecurity guidance", "Internal PHI/logging policy"],
            tests_required=[
                "test_no_phi_in_autonomous_improvement_artifacts",
                "test_autonomous_loop_auto_merge_disabled_by_default",
            ],
            surfaces=["security_middleware", "voice-os", "agentic-loop"],
            agent_lane="security",
            rollback="Revert security patch or keep the autonomous loop in blocked shadow mode.",
        ))
    if _safety_controls().get("auto_merge_enabled"):
        out.append(validate_candidate(_candidate(
            lane="safety_security_gap",
            title="Disable autonomous clinical auto-merge",
            description="AGENTIC_AUTO_MERGE is enabled while clinical autonomous improvement must remain human-reviewed.",
            clinical_impact=9,
            severity=10,
            effort_h=0.5,
            risk_avoided="Avoids unreviewed clinical logic changes reaching production.",
            source="environment.AGENTIC_AUTO_MERGE",
            evidence=["Autonomous improvement safety contract"],
            tests_required=["test_autonomous_loop_auto_merge_disabled_by_default"],
            surfaces=["agentic-loop", "github-workflow"],
            agent_lane="security",
            rollback="Set AGENTIC_AUTO_MERGE=false.",
        )))
    return out


def _evidence_delta_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """EPIC 18: Surface evidence deltas detected by external delta check.

    Reads the latest `output/regulatory/evidence_delta_*.md` and creates a
    Loop Monitor candidate if the report contains ≥1 delta. The candidate
    is `pending_human_review` and recommends clinical team triage before
    re-marking manifest records as `fresh`.
    """
    delta_dir = PROJECT_ROOT / "output" / "regulatory"
    if not delta_dir.exists():
        return []
    delta_reports = sorted(delta_dir.glob("evidence_delta_*.md"))
    if not delta_reports:
        return []
    latest = delta_reports[-1]
    try:
        content = latest.read_text(encoding="utf-8")
    except OSError:
        return []
    # Parse "**Total deltas detected:** N" line
    delta_count = 0
    for line in content.splitlines():
        if "Total deltas detected:" in line:
            try:
                delta_count = int(line.split(":")[-1].strip().replace("**", "").strip())
            except (ValueError, IndexError):
                pass
            break
    if delta_count == 0:
        return []
    # Detect high-impact trials in deltas (clinical priority boost)
    high_impact_trials = {
        "CHAARTED", "ARASENS", "ARCHES", "ENZAMET", "LATITUDE", "STAMPEDE",
        "PEACE-1", "TITAN", "EMBARK", "VISION", "TheraP", "PROfound", "PROpel",
        "MAGNITUDE", "TALAPRO-2", "ARAMIS", "SPARTAN", "PROSPER",
    }
    impacted_high = [t for t in high_impact_trials if t in content]
    priority_boost = 2 if impacted_high else 0
    return [_candidate(
        lane="evidence_gap",
        title=f"EPIC 18: {delta_count} evidence source(s) updated externally — clinical review required",
        description=(
            f"Weekly external delta check detected {delta_count} update(s) from "
            f"ClinicalTrials.gov and/or PubMed. Records remain "
            f"`pending_human_review=True` until clinical team triages the delta "
            f"report. Affected high-impact trials: {sorted(impacted_high) if impacted_high else 'none'}"
        ),
        clinical_impact=7 + priority_boost,
        severity=6 + priority_boost,
        effort_h=1.5,
        risk_avoided=(
            "Avoids citing stale clinical evidence in shared decision making and FDA "
            "Pre-Sub Q-Sub submissions when external sources (long-term follow-ups, "
            "label updates, retractions) have moved."
        ),
        source="epic15_evidence_refresh.external_delta_check",
        evidence=[str(latest)],
        tests_required=[
            "test_epic18_loop_monitor_surfaces_evidence_delta_candidate",
        ],
        surfaces=["evidence_freshness_manifest", "loop_monitor", "pillar_5_clinical"],
        agent_lane="evidence_curator",
        rollback="No code change required — delta report is informational only.",
    )]


def _candidate(**kwargs: Any) -> dict[str, Any]:
    parts = [kwargs.get("lane", ""), kwargs.get("title", ""), kwargs.get("source", "")]
    candidate = ImprovementCandidate(
        id=_stable_id(*parts),
        lane=str(kwargs.get("lane") or "critical_clinical_gap"),
        title=str(kwargs.get("title") or "Untitled improvement"),
        description=str(kwargs.get("description") or ""),
        clinical_impact=int(kwargs.get("clinical_impact") or 5),
        severity=int(kwargs.get("severity") or 5),
        effort_h=float(kwargs.get("effort_h") or 1.0),
        risk_avoided=str(kwargs.get("risk_avoided") or ""),
        source=str(kwargs.get("source") or ""),
        evidence=list(kwargs.get("evidence") or []),
        tests_required=list(kwargs.get("tests_required") or []),
        surfaces=list(kwargs.get("surfaces") or []),
        affected_states=list(kwargs.get("affected_states") or []),
        patient_scope=dict(kwargs.get("patient_scope") or {}),
        clinical_contract=dict(kwargs.get("clinical_contract") or {}),
        contract_gaps=list(kwargs.get("contract_gaps") or []),
        contradictions=list(kwargs.get("contradictions") or []),
        agent_lane=str(kwargs.get("agent_lane") or "clinical_logic"),
        rollback=str(kwargs.get("rollback") or ""),
        status=str(kwargs.get("status") or "shadow"),
        blockers=list(kwargs.get("blockers") or []),
    )
    return candidate.to_dict()


def _compute_goal_metrics(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    metrics = deepcopy(GOAL_REGISTRY["metrics"])
    ctx = dict((context or {}).get("context") or {})
    contracts = dict(ctx.get("contracts") or {})
    patients = dict(ctx.get("patients") or ctx.get("patient_scan") or {})
    loop_summary = dict(ctx.get("loop_summary") or {})
    compliance = dict(ctx.get("compliance_snapshot") or ctx.get("compliance") or {})

    values = {
        "clinical_coverage": _clinical_coverage_value(contracts),
        "data_quality": _data_quality_value(patients),
        "decision_today_alignment": _decision_alignment_value(patients),
        "patient_twin_readiness": _patient_twin_readiness_value(ctx),
        "safety_security": _pillar_score(compliance, "p6", default=100.0 if not _safety_controls().get("auto_merge_enabled") else 0.0),
        "evidence_currentness": _evidence_value(loop_summary, compliance),
        "ui_performance": _loop_vector_value(loop_summary, "performance_a11y"),
        "usability_clinical": _loop_vector_value(loop_summary, "ui_ergonomy"),
        "autonomous_loop_maturity": _autonomous_loop_maturity_value(),
        "regulatory_readiness": float(compliance.get("aggregate") or 0.0),
    }
    for metric in metrics:
        key = metric["key"]
        metric["value"] = round(float(values.get(key, 0.0)), 2)
        metric["status"] = _metric_status(metric["value"])
    return metrics


def _patient_twin_readiness_value(ctx: Mapping[str, Any]) -> float:
    if ctx.get("patient_twin_available"):
        return 100.0
    contract = _contract_by_id("patient_twin_preference_pro_minimum")
    if not contract:
        return 0.0
    application_rows = {
        str(row.get("contract_id") or ""): dict(row)
        for row in ((ctx.get("application_telemetry") or {}).get("implementations") or [])
    }
    twin_application = application_rows.get("patient_twin_preference_pro_minimum", {})
    patients = dict(ctx.get("patients") or ctx.get("patient_scan") or {})
    evaluated = int(patients.get("evaluated") or 0)
    missing_pairs = list(patients.get("missing_fields_top") or [])
    all_aliases: list[str] = []
    for dimension in PATIENT_TWIN_READINESS_DIMENSIONS:
        all_aliases.extend(str(alias) for alias in dimension.get("field_aliases") or [])
    missing_count = _missing_count_for_aliases(missing_pairs, all_aliases)
    value = 55.0 if twin_application.get("software_gap_closed") else 20.0
    if callable(globals().get("build_patient_twin_readiness_loop")):
        value += 15.0
    if evaluated > 0:
        value += 10.0
    if missing_count:
        value -= min(15.0, float(missing_count) * 3.0)
    # EPIC 17b: AI substrate boost — 4 models (state_transition, treatment_response,
    # deep_surv, anomaly_detector) entrenados y artifact on-disk señalan que el
    # Patient Twin tiene infraestructura AI lista. Cap sube de 75 → 85 (NO 100
    # porque patient_twin_os.py module aún no existe).
    ai_substrate_ready = bool(ctx.get("patient_twin_ai_substrate_ready"))
    if ai_substrate_ready:
        value += 10.0
    cap = 75.0 if twin_application.get("software_gap_closed") else 45.0
    if ai_substrate_ready and twin_application.get("software_gap_closed"):
        cap = 85.0  # EPIC 17b: AI substrate ready + software gap closed → 85 cap.
    return round(max(0.0, min(cap, value)), 2)


def _missing_count_for_aliases(missing_pairs: Iterable[Any], aliases: Iterable[str]) -> int:
    alias_terms = [str(alias or "").lower() for alias in aliases if str(alias or "").strip()]
    total = 0
    for raw in missing_pairs or []:
        field = ""
        count = 0
        if isinstance(raw, Mapping):
            field = str(raw.get("field") or raw.get("key") or raw.get("label") or "")
            count = int(raw.get("count") or 0)
        elif isinstance(raw, (list, tuple)) and raw:
            field = str(raw[0] or "")
            try:
                count = int(raw[1] or 0) if len(raw) > 1 else 1
            except (TypeError, ValueError):
                count = 1
        else:
            field = str(raw or "")
            count = 1
        field_lower = field.lower()
        if any(alias and alias in field_lower for alias in alias_terms):
            total += max(1, count)
    return total


def _dimension_completion_pct(dimensions: Iterable[Mapping[str, Any]], dimension_id: str) -> float:
    row = next((dict(dimension) for dimension in dimensions if dimension.get("dimension_id") == dimension_id), {})
    if not row:
        return 0.0
    if row.get("status") == "ready":
        return 100.0
    scope = int(row.get("patient_scope_estimate") or 0)
    missing = int(row.get("missing_count_estimate") or 0)
    if scope <= 0 or missing <= 0:
        return 0.0
    return round(max(0.0, 100.0 - (missing / max(scope, 1)) * 100.0), 2)


def _dataset_gate_status(gates: Iterable[Mapping[str, Any]], gate_id: str) -> str:
    row = next((dict(gate) for gate in gates if gate.get("gate_id") == gate_id), {})
    return str(row.get("status") or "requires_data")


def _ai_readiness_score(gates: Iterable[Mapping[str, Any]], *, ready_8a: bool) -> float:
    if not ready_8a:
        return 0.0
    rows = [dict(gate) for gate in gates]
    if not rows:
        return 0.0
    ready = sum(1 for gate in rows if gate.get("status") == "shadow_ready")
    # Phase 9A is deliberately capped below trainable readiness because it only
    # registers the audit contract. Actual export/training remains blocked.
    return round(min(55.0, 25.0 + (ready / max(len(rows), 1)) * 30.0), 2)


def _build_cortana_loop_response_cards(
    *,
    mission: Mapping[str, Any],
    development: Mapping[str, Any],
    gaps: Mapping[str, Any],
    ai_loop: Mapping[str, Any],
    twin_loop: Mapping[str, Any],
    evidence_loop: Mapping[str, Any],
) -> list[dict[str, Any]]:
    mission_summary = dict(mission.get("summary") or {})
    development_summary = dict(development.get("summary") or {})
    selected = dict(development_summary.get("selected_improvement") or {})
    ai_summary = dict(ai_loop.get("summary") or {})
    twin_summary = dict(twin_loop.get("summary") or {})
    evidence_summary = dict(evidence_loop.get("summary") or {})
    candidates = list(gaps.get("candidates") or [])
    top_candidate = dict(candidates[0]) if candidates else selected
    dominant_ai_gate = str(ai_summary.get("dominant_dataset_blocker") or "consent_governance")

    return [
        {
            "response_key": "mission_gap_summary",
            "title": "Camino al objetivo final",
            "answer": (
                f"ProstaMed está en {mission_summary.get('clinical_goal_pct', 0)}% del objetivo clínico global "
                f"y {mission_summary.get('pipeline_maturity_pct', 0)}% de madurez del pipeline. "
                f"La prioridad visible es: {mission_summary.get('top_gap_title') or 'sin brecha activa'}."
            ),
            "risk_avoided": "Evita confundir avance técnico con seguridad clínica real.",
            "cta": "/loop-monitor#pm2MissionControl",
            "source_bundles": ["mission_control", "gap_intelligence"],
        },
        {
            "response_key": "dominant_gap",
            "title": "Brecha dominante",
            "answer": (
                f"La brecha con mayor prioridad es: {top_candidate.get('title') or 'sin brecha priorizada'}. "
                f"Riesgo evitado: {top_candidate.get('risk_avoided') or 'mantener decisiones auditables'}."
            ),
            "risk_avoided": top_candidate.get("risk_avoided") or "Reduce bloqueo de Decision Today y Patient Twin.",
            "cta": "/loop-monitor#pm2DevelopmentAutodrive",
            "source_bundles": ["development_autodrive", "gap_intelligence"],
        },
        {
            "response_key": "next_improvement",
            "title": "Mejora que toca hoy",
            "answer": (
                "El ciclo 10A queda como interfaz consultiva. Después de esto, la ruta correcta es operación "
                "shadow continua: detectar una brecha, proponer patch, exigir safety gates, validar visualmente y pedir revisión humana."
            ),
            "risk_avoided": "Evita que Cortana pase de explicar a ejecutar cambios sin autorización.",
            "cta": "/loop-monitor#pm2CortanaLoopInterface",
            "source_bundles": ["cortana_loop_interface", "mission_control"],
        },
        {
            "response_key": "implementation_rationale",
            "title": "Por qué el cambio mejora ProstaMed",
            "answer": (
                f"El cambio seleccionado en Development Autodrive es: {selected.get('title') or top_candidate.get('title') or 'sin selección activa'}. "
                "Debe mantenerse pequeño, testeado, reversible y sin mutar hechos clínicos."
            ),
            "risk_avoided": selected.get("risk_avoided") or top_candidate.get("risk_avoided") or "Evita cambios opacos o no revertibles.",
            "cta": "/loop-monitor#pm2ImplementationBrief",
            "source_bundles": ["implementation_brief", "shadow_patch_blueprint", "agent_consensus"],
        },
        {
            "response_key": "evidence_support",
            "title": "Evidencia y vigilancia",
            "answer": (
                f"Evidence Refresh está en estado {evidence_summary.get('evidence_refresh_status', 'desconocido')}. "
                "Puede crear candidatos de revisión, pero no cambia gates, trials ni recomendaciones sin revisión humana."
            ),
            "risk_avoided": "Evita recomendaciones desactualizadas por cambios EAU/FDA/ClinicalTrials.gov.",
            "cta": "/loop-monitor#pm2EvidenceRefreshShadowLoop",
            "source_bundles": ["evidence_refresh_shadow_loop"],
        },
        {
            "response_key": "patient_twin_status",
            "title": "Patient Twin readiness",
            "answer": (
                f"Patient Twin está en {twin_summary.get('patient_twin_readiness_status', 'desconocido')}. "
                f"Dimensión faltante dominante: {twin_summary.get('dominant_missing_dimension') or 'sin datos'}."
            ),
            "risk_avoided": "Evita personalización falsa sin preferencias, PROs y umbrales de nueva decisión.",
            "cta": "/loop-monitor#pm2PatientTwinReadinessLoop",
            "source_bundles": ["patient_twin_readiness_loop"],
        },
        {
            "response_key": "ai_readiness_status",
            "title": "AI readiness",
            "answer": (
                f"AI readiness está en {ai_summary.get('ai_readiness_status', 'desconocido')} con score "
                f"{ai_summary.get('model_readiness_score', 0)}. Bloqueo dataset dominante: {dominant_ai_gate}. "
                "No hay export, entrenamiento ni predicciones liberadas."
            ),
            "risk_avoided": "Evita entrenar con consentimiento, provenance, outcomes o leakage incompletos.",
            "cta": "/loop-monitor#pm2AiReadinessDatasetLoop",
            "source_bundles": ["ai_readiness_dataset_loop"],
        },
    ]


def _resolve_cortana_loop_query(
    query: str,
    *,
    command_routes: Iterable[Mapping[str, Any]],
    response_cards: Iterable[Mapping[str, Any]],
    default_cta: str,
) -> dict[str, Any]:
    text = _normalize_query_text(query)
    routes = [dict(route) for route in command_routes]
    cards = {str(card.get("response_key") or ""): dict(card) for card in response_cards}
    matched = None
    if text:
        for route in routes:
            phrases = [_normalize_query_text(str(phrase or "")) for phrase in route.get("phrases") or []]
            if any(phrase and phrase in text for phrase in phrases):
                matched = route
                break
    if not matched:
        matched = next((route for route in routes if route.get("command_id") == "final_goal_gap"), {})
    card = cards.get(str(matched.get("response_key") or "mission_gap_summary"), {})
    return {
        "query": query,
        "matched_command_id": matched.get("command_id", "final_goal_gap"),
        "matched_label": matched.get("label", "Qué falta para alcanzar el objetivo final"),
        "status": matched.get("status", "available"),
        "title": card.get("title", "Automejora clínica"),
        "answer": card.get("answer", "Cortana puede consultar el loop, pero no ejecutar cambios."),
        "risk_avoided": card.get("risk_avoided", "Mantiene la automejora en shadow mode."),
        "cta": card.get("cta") or matched.get("cta") or default_cta,
        "source_bundles": card.get("source_bundles") or matched.get("sources") or [],
        "confidence": "deterministic_phrase_match" if text else "default_overview",
        "write_allowed": False,
        "clinical_fact_write_allowed": False,
        "code_mutation_allowed": False,
        "merge_allowed": False,
    }


def _normalize_query_text(query: str) -> str:
    text = str(query or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _clinical_coverage_value(contracts: Mapping[str, Any]) -> float:
    gates_total = max(103, int(contracts.get("gates_total") or 0))
    gates = min(int(contracts.get("gates_contract_covered") or 0), gates_total)
    gate_score = (gates / gates_total) * 70.0 if gates_total else 0.0
    trial_score = 30.0 if contracts.get("trials_contract_ok") else 0.0
    return min(100.0, gate_score + trial_score)


def _data_quality_value(patients: Mapping[str, Any]) -> float:
    evaluated = int(patients.get("evaluated") or 0)
    if evaluated <= 0:
        return 0.0
    counts = Counter(patients.get("decision_state_counts") or {})
    blocked = sum(counts.get(k, 0) for k in ("blocked", "requires_data", "urgent_safety", "redecision_required"))
    return max(0.0, 100.0 - (blocked / evaluated) * 100.0)


def _decision_alignment_value(patients: Mapping[str, Any]) -> float:
    evaluated = int(patients.get("evaluated") or 0)
    if evaluated <= 0:
        return 0.0
    errors = len(patients.get("errors") or [])
    return max(0.0, 100.0 - (errors / max(evaluated, 1)) * 100.0)


def _evidence_value(loop_summary: Mapping[str, Any], compliance: Mapping[str, Any]) -> float:
    vector = _loop_vector_value(loop_summary, "clinical_evidence")
    pillar = _pillar_score(compliance, "p5", default=0.0)
    if vector <= 0:
        return round(pillar * 0.65, 2)
    return round(min(100.0, (vector * 0.45) + (pillar * 0.55)), 2)


def _loop_vector_value(summary: Mapping[str, Any], key: str) -> float:
    row = dict(summary.get(key) or {})
    if not row.get("count"):
        return 0.0
    latest = row.get("latest_value")
    try:
        value = float(latest)
    except (TypeError, ValueError):
        value = 100.0 if int(row.get("critical") or 0) == 0 else 50.0
    return max(0.0, min(100.0, value))


def _pillar_score(compliance: Mapping[str, Any], key: str, *, default: float = 0.0) -> float:
    try:
        return float(((compliance.get("scores") or {}).get(key) or {}).get("score"))
    except (TypeError, ValueError):
        return default


def _autonomous_loop_maturity_value() -> float:
    return _autonomous_pipeline_progress()["pct"]


def _autonomous_pipeline_progress() -> dict[str, Any]:
    rows = [
        {
            "phase": phase,
            "function": function_name,
            "implemented": callable(globals().get(function_name)),
        }
        for phase, function_name in AUTONOMOUS_LOOP_ROADMAP_PHASES
    ]
    implemented = sum(1 for row in rows if row["implemented"])
    total = len(rows) or 1
    return {
        "pct": round((implemented / total) * 100.0, 2),
        "implemented_count": implemented,
        "total_count": total,
        "implemented_phases": [row["phase"] for row in rows if row["implemented"]],
        "pending_phases": [row["phase"] for row in rows if not row["implemented"]],
        "rows": rows,
        "note": "Este progreso mide fases técnicas del bucle; el objetivo clínico global mide calidad clínica real.",
    }


def _mission_progress_diagnostics(
    metrics: Iterable[Mapping[str, Any]],
    gap_bundle: Mapping[str, Any],
    pipeline_progress: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    low = [
        {
            "key": str(metric.get("key") or ""),
            "label": str(metric.get("label") or ""),
            "value": float(metric.get("value") or 0.0),
            "reason": _mission_metric_reason(metric, gap_bundle),
        }
        for metric in metrics
        if float(metric.get("value") or 0.0) < 65.0
    ]
    application_summary = dict((gap_bundle.get("application_telemetry") or {}).get("summary") or {})
    return {
        "why_progress_may_not_rise": (
            "El objetivo final pondera datos clínicos reales, Decision Today, Patient Twin, evidencia y regulación; "
            "por eso no sube linealmente con cada fase técnica del pipeline."
        ),
        "new_dynamic_metric": "autonomous_loop_maturity",
        "application_telemetry_metric": "software_gap_closed_vs_patient_capture_pending",
        "clinical_goal_is_not_phase_completion": True,
        "pipeline_maturity_pct": float((pipeline_progress or {}).get("pct") or 0.0),
        "pipeline_completed_count": int((pipeline_progress or {}).get("implemented_count") or 0),
        "pipeline_total_count": int((pipeline_progress or {}).get("total_count") or 0),
        "software_gap_closed_count": int(application_summary.get("software_gap_closed_count") or 0),
        "patient_capture_monitoring_count": int(application_summary.get("patient_capture_monitoring_count") or 0),
        "low_metrics": low[:6],
        "dominant_blocker": (low[0]["label"] if low else ""),
        "candidate_count": len(gap_bundle.get("candidates") or []),
    }


def _mission_metric_reason(metric: Mapping[str, Any], gap_bundle: Mapping[str, Any]) -> str:
    key = str(metric.get("key") or "")
    ctx = dict((gap_bundle or {}).get("context") or {})
    patients = dict((ctx.get("patient_scan") or {}))
    if key == "data_quality":
        return f"Decision Today tiene estados bloqueados/requires_data en el escaneo: {patients.get('decision_state_counts', {})}."
    if key == "decision_today_alignment":
        return f"Errores o contradicciones detectadas en escaneo: {len(patients.get('errors') or [])}."
    if key == "patient_twin_readiness":
        app_summary = dict((ctx.get("application_telemetry") or {}).get("summary") or {})
        return (
            "El contrato de captura puede estar implementado, pero el score aún exige datos reales de valores, PROs, "
            f"trayectoria y umbrales. Contratos aplicados: {app_summary.get('software_gap_closed_count', 0)}."
        )
    if key == "regulatory_readiness":
        return "Depende del score FDA SaMD/QMS actual, no sólo de fases técnicas completadas."
    if key == "usability_clinical":
        return "Depende de iteraciones reales registradas para UI ergonomía en loop_monitor."
    return "Métrica por debajo del umbral de propuesta/validación."


def _weighted_overall(metrics: Iterable[Mapping[str, Any]]) -> float:
    total = 0.0
    weight = 0.0
    for metric in metrics:
        w = float(metric.get("weight") or 0.0)
        total += float(metric.get("value") or 0.0) * w
        weight += w
    return round(total / weight, 2) if weight else 0.0


def _metric_status(value: float) -> str:
    if value >= 90:
        return "validated"
    if value >= 65:
        return "proposal_ready"
    if value >= 35:
        return "human_review_required"
    return "blocked"


def _safety_controls() -> dict[str, Any]:
    auto_merge = str(os.getenv("AGENTIC_AUTO_MERGE", "false")).lower() in {"1", "true", "yes"}
    kill_switch = str(os.getenv("PROSTAMED_AUTONOMOUS_LOOP_DISABLED", "false")).lower() in {"1", "true", "yes"}
    return {
        "mode": "shadow",
        "auto_merge_enabled": bool(auto_merge),
        "kill_switch_active": bool(kill_switch),
        "human_review_required": True,
        "clinical_fact_writes_allowed": False,
        "source_clinical_facts_mutated": False,
        "external_orders_allowed": False,
        "ml_training_allowed": False,
        "raw_phi_in_artifacts_allowed": False,
    }


def _lane_from_gap(gap: Mapping[str, Any]) -> str:
    kind = str(gap.get("kind") or "").lower()
    pillar = int(gap.get("pillar_id") or 0)
    if pillar == 6 or "security" in kind or "cve" in kind:
        return "safety_security_gap"
    if pillar in {1, 2, 3, 4, 7}:
        return "regulatory_traceability_gap"
    if pillar == 5 or "evidence" in kind or "trial" in kind:
        return "evidence_gap"
    if "capture" in kind or "field" in kind or "data" in kind:
        return "data_integrity_gap"
    return "critical_clinical_gap"


def _proposal_streak(gap: Mapping[str, Any]) -> int:
    try:
        from prostanet.agentic.gap_prioritizer import PROPOSALS_LOG

        if not PROPOSALS_LOG.exists():
            return 0
        kind = str(gap.get("kind") or "")
        streak = 0
        with PROPOSALS_LOG.open(encoding="utf-8") as handle:
            for line in reversed(list(handle)):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                proposal = payload.get("proposal") or {}
                if proposal.get("kind") == kind or str(proposal.get("kind") or "").endswith(kind):
                    streak += 1
                else:
                    break
        return streak
    except Exception:
        return 0


def _dedupe_candidates(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        data = validate_candidate(candidate)
        result[str(data.get("id"))] = data
    return list(result.values())


def _apply_review(candidate: Mapping[str, Any], reviews: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    data = dict(candidate)
    review = dict(reviews.get(str(data.get("id"))) or {})
    if not review:
        return data
    data["review"] = review
    if review.get("status") == "approved" and data.get("status") != "blocked":
        data["status"] = "validated"
    elif review.get("status") == "rejected":
        data["status"] = "blocked"
        blockers = set(data.get("blockers") or [])
        blockers.add("human_rejected")
        data["blockers"] = sorted(blockers)
    return data


def _minimal_change_for(candidate: Mapping[str, Any]) -> str:
    lane = str(candidate.get("lane") or "")
    if lane == "critical_clinical_gap":
        return "Add or adjust the smallest clinical contract and tests needed to unblock the targeted scenario."
    if lane == "data_integrity_gap":
        return "Map the missing field through Clinical Field Router, persistence and the consuming read-model."
    if lane == "ui_workflow_gap":
        return "Add targeted visual validation and a compact UI/CTA correction only on affected surfaces."
    if lane == "evidence_gap":
        return "Open an evidence change candidate; do not change recommendations without human review."
    if lane == "safety_security_gap":
        return "Tighten safety controls or logging/header policy and prove no PHI/artifact leakage."
    return "Add one small traceability artifact or test-backed contract change."


def _risks_for(candidate: Mapping[str, Any]) -> list[str]:
    risks = [
        "scope creep if more than one clinical gap is changed per iteration",
        "false confidence if tests do not cover Decision Today regressions",
    ]
    if candidate.get("lane") in {"critical_clinical_gap", "data_integrity_gap"}:
        risks.append("clinical misclassification if capture/persistence aliases diverge")
    if candidate.get("lane") == "ui_workflow_gap":
        risks.append("visual regression on mobile or dense clinical panels")
    return risks


def _acceptance_for(candidate: Mapping[str, Any]) -> list[str]:
    acceptance = [
        "all listed tests pass",
        "source_clinical_facts_mutated remains false",
        "no fabricated PSA, testosterone, therapy line, treatment or trial eligibility",
        "human review remains required for clinical change",
    ]
    if candidate.get("lane") == "ui_workflow_gap":
        acceptance.append("Browser visual validation attached for desktop and mobile")
    return acceptance


def _public_context(context: Mapping[str, Any]) -> dict[str, Any]:
    patients = dict(context.get("patients") or {})
    return {
        "generated_at": context.get("generated_at"),
        "patient_scan": {
            "scanned": patients.get("scanned", 0),
            "evaluated": patients.get("evaluated", 0),
            "decision_state_counts": patients.get("decision_state_counts", {}),
            "missing_fields_top": patients.get("missing_fields_top", []),
            "sample_ref_hints": patients.get("sample_ref_hints", []),
            "errors": patients.get("errors", []),
        },
        "contractual_gap_rows": context.get("contractual_gap_rows", []),
        "application_telemetry": context.get("application_telemetry", {}),
        "contradiction_rows": context.get("contradiction_rows", []),
        "contracts": context.get("contracts", {}),
        "patient_twin_available": bool(context.get("patient_twin_available")),
        # EPIC 17b: propagar AI substrate signal al public context para que
        # _compute_goal_metrics → _patient_twin_readiness_value tenga acceso.
        "patient_twin_ai_substrate_ready": bool(context.get("patient_twin_ai_substrate_ready")),
        "patient_twin_ai_substrate": context.get("patient_twin_ai_substrate") or {},
        "loop_summary": context.get("loop_summary", {}),
        "compliance": {
            "aggregate": (context.get("compliance_snapshot") or {}).get("aggregate", 0),
            "gap_top": (context.get("compliance_snapshot") or {}).get("gap_top", ""),
            # EPIC 15 — expose pillar scores so _evidence_value y otros metric
            # computers tengan acceso al pillar number-only (no gaps detail).
            # Necesario para que Pillar 5 freshness boost (EPIC 15) llegue a
            # evidence_currentness mission control metric.
            "scores": {
                pid: {"score": float((pdata or {}).get("score") or 0.0)}
                for pid, pdata in ((context.get("compliance_snapshot") or {}).get("scores") or {}).items()
            },
        },
    }


def _contract_by_id(contract_id: str) -> dict[str, Any]:
    for contract in build_clinical_gap_contract_registry():
        if contract.get("contract_id") == contract_id:
            return dict(contract)
    return {}


def _audit_footer() -> dict[str, Any]:
    return {
        "deterministic_v1": True,
        "read_model_only": True,
        "shadow_mode": True,
        "source_clinical_facts_mutated": False,
        "no_auto_merge": not _safety_controls().get("auto_merge_enabled"),
        "no_ml_model_trained": True,
        "no_external_orders": True,
        "no_fabricated_psa": True,
        "no_fabricated_testosterone": True,
        "no_fabricated_treatments": True,
        "no_fabricated_trial_eligibility": True,
        "human_review_required": True,
        "generated_at": _now_iso(),
    }


def _review_weight(candidate: Mapping[str, Any]) -> float:
    if candidate.get("status") == "human_review_required":
        return 6.0
    if candidate.get("status") == "validated":
        return 2.0
    if candidate.get("status") == "blocked":
        return -6.0
    return 0.0


def _status_weight(status: str) -> float:
    return {
        "human_review_required": 5.0,
        "proposal_ready": 3.0,
        "shadow": 1.0,
        "validated": 1.0,
        "blocked": -6.0,
        "rollback_required": 8.0,
    }.get(status, 0.0)


def _lane_weight(lane: str) -> float:
    return {
        "critical_clinical_gap": 8.0,
        "safety_security_gap": 7.0,
        "data_integrity_gap": 6.0,
        "evidence_gap": 4.0,
        "regulatory_traceability_gap": 3.5,
        "ui_workflow_gap": 2.5,
    }.get(lane, 0.0)


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _sanitize_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]", "", str(value or ""))[:96]


def _redact_phi_like(value: str) -> str:
    text = str(value or "")[:500]
    text = re.sub(r"/Users/[^/\s]+", "/Users/***", text)
    text = re.sub(r"\b\d{6,}\b", "***", text)
    text = re.sub(r"\b[A-Z]{2,}-\d{3,}\b", "***", text)
    return text


def _mask_ref(ref: str) -> str:
    text = str(ref or "")
    if len(text) <= 4:
        return "***"
    return f"***{text[-4:]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
