# AAMI TIR57 Cybersecurity-Risk Addendum — ProstaMed

**Standard**: AAMI TIR57:2016 — Principles for medical device security — Risk management
**Version**: 0.1 (LXXXVIII bootstrap) · **Date**: 2026-04-27 · **Owner**: Quality Lead

## Purpose
Couple cybersecurity threats with clinical safety risks per AAMI TIR57. Each cybersecurity threat in STRIDE-threat-model.md is evaluated for downstream clinical impact.

## Coupling Matrix

| STRIDE category | Specific threat | Clinical hazard linked | FMEA mitigation |
|---|---|---|---|
| **Spoofing** | Unauthorized clinician impersonation | gate_misclassification (false override) | MIT-002 + auth ABAC |
| **Tampering** | Unauthorized DB write to clinical_assessments | psa_history_data_loss | MIT-012 + audit_trail |
| **Repudiation** | Clinical action denial | transition_proposal_ignored (no audit) | MIT-010 + 21 CFR Part 11 e-sign |
| **Information Disclosure** | PHI leak | phi_exposure_unauthorized_access | MIT-013 + decision_audit PHI scrub |
| **Denial of Service** | Loop infinite or DoS attack | crpc_transition_missed (system unavailable) | MIT-004 + rate-limit + safety_gates timeout |
| **Elevation of Privilege** | Scope ABAC bypass | All hazards (catastrophic) | MIT-013 + require_clinical_session decorator |

## Risk-cybersecurity score (combined)
Each FMEA hazard with cybersecurity coupling gets `cyber_residual_rpn` added.

## References
- STRIDE threat model: `regulatory/security/STRIDE-threat-model.md`
- VEX: `regulatory/security/vex.json`
- FDA Premarket Cybersecurity Guidance Sept 2023

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
