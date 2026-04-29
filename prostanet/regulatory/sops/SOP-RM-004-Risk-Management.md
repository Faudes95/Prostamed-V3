# SOP-RM-004 — Risk Management SOP

**ID**: SOP-RM-004 · **Version**: 0.1 (LXXXVIII bootstrap) · **Effective**: 2026-04-27
**Owner**: Clinical Lead · **Standards**: ISO 14971:2019 + AAMI TIR57:2016 + IEC 62304 §7

## Purpose
Establish risk management process for ProstaMed throughout software lifecycle, identifying clinical hazards, assessing severity/probability, and verifying mitigations.

## Scope
All clinical decision pathways: classification, risk stratification, treatment selection, longitudinal monitoring, trial eligibility, transition proposals.

## Procedure

### 1. Hazard Identification
Maintain `regulatory/risk/fmea-prostanet-2026.yaml` with ≥15 prostate-cancer-specific hazards:

Required canonical hazards (LXXXVIII seed):
- psa_stale_decision (data freshness)
- gate_misclassification (incorrect gate firing)
- arpi_dose_miscalc (dose calculation error)
- crpc_transition_missed (transition proposal ignored)
- false_negative_localized_delays_treatment
- false_positive_biopsy_overtreatment
- gleason_scoring_error
- hrr_missing_blocks_parp
- ddi_undetected_toxicity
- transition_proposal_ignored
- trial_eligibility_false_positive
- psa_history_data_loss
- phi_exposure_unauthorized_access (cybersecurity)
- ml_inference_drift (ML model degradation)
- dose_calculation_unit_mismatch

### 2. Risk Assessment (per hazard)
- **Severity**: 1-10 (10 = death/serious injury possible)
- **Occurrence**: 1-10 (probability of hazard manifesting)
- **Detectability**: 1-10 (10 = undetectable until harm)
- **RPN** (Risk Priority Number) = Severity × Occurrence × Detectability
- Threshold for action: RPN ≥ 100

### 3. Risk Control Measures
For each hazard, document:
- `mitigation_id` (e.g., MIT-001)
- `mitigation_description` (control measure)
- `mitigation_status` (planned / implemented / verified / controlled)
- `control_verification` (test_id from `tests/`)
- `residual_risk` (post-mitigation RPN)

### 4. Risk Traceability
Each FMEA row MUST trace to:
- Software requirement (in SRS/CLINICAL_EVIDENCE_2026.md or gate YAML)
- Implementation code path (`prostanet/...`)
- Verification test (`tests/test_audit_*.py`)
- Mitigation evidence (commit SHA + test pass)

This trace lives in `regulatory/dhf/traceability_matrix.yaml`.

### 5. Cybersecurity-Risk Coupling (AAMI TIR57)
Each hazard with cybersecurity dimension also documented in:
- STRIDE threat model (`regulatory/security/STRIDE-threat-model.md`)
- VEX addendum (`regulatory/security/vex.json`)

### 6. Periodic Review
- **Quarterly**: full FMEA review by Clinical Lead + Quality Lead.
- **On any release**: re-verify mitigations not regressed (compliance scorer Pilar 4).
- **On NCCN/EAU update**: re-evaluate hazards against new evidence.

## Records
- FMEA: `regulatory/risk/fmea-prostanet-2026.yaml`
- TIR57 addendum: `regulatory/risk/tir57_addendum.md`
- Risk management report: `regulatory/risk/rmp-prostanet-{version}.md` (yearly)
- Periodic review minutes: `regulatory/risk/periodic_reviews/`

## Integration with Faubot Agentic Loop
- `pillar_4_risk.py` scorer reads FMEA and reports gaps as `fmea_entry_missing`, `fmea_mitigations_incomplete`.
- Loop generates new FMEA entries via `clinical-reports` + `xlsx` skills (delegation pattern).

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
