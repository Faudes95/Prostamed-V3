---
protocol_id: PM-CLIN-VAL-001
title: ProstaMed Prospective Shadow Validation Protocol
version: "1.0"
status: authorized_internal_shadow_validation
effective_date: "2026-05-12"
authorization_scope: internal_shadow_observational_validation
human_authorization_required: true
human_authorization_record: protocol_signed.flag
irb_approval_status: not_submitted
irb_approval_claimed: false
external_patient_enrollment_allowed: false
clinical_fact_mutation_allowed_by_protocol: false
orders_or_prescribing_allowed: false
---

# ProstaMed Prospective Shadow Validation Protocol

**Protocol ID:** PM-CLIN-VAL-001
**Version:** 1.0
**Status:** Authorized for internal shadow prospective validation
**Effective date:** 2026-05-12
**Standard anchor:** IMDRF/SaMD WG/N41 clinical evaluation, ProstaMed QMS, ProstaMed autonomous improvement safety gates

## 1. Purpose

This protocol defines the first prospective validation loop for ProstaMed as an
internal, observational, shadow-mode activity. Its purpose is to measure whether
the current ProstaMed clinical operating system can produce a coherent,
auditable **DECISION TODAY** for each patient from verified facts, longitudinal
signals, readiness, comparative options, pathway execution, memory/outcomes and
Autodrive prioritization.

This protocol does **not** claim IRB approval, does **not** enroll external
research subjects, does **not** prescribe, and does **not** allow automatic
clinical execution. It creates the controlled measurement layer required before
future IRB-bound prospective research.

## 2. Scope

Included ProstaMed subsystems:

- Official clinical classifier and Clinical Field Router.
- Longitudinal Truth Snapshot and append-only clinical facts.
- Clinical Readiness & Safety Tower.
- Tumor Board OS.
- Care Pathway OS.
- Clinical Memory & Outcomes Learning OS.
- Clinical Autodrive Command Center.
- Decision Today Fusion Kernel.
- Cortana Clinical OS only after medical review/acceptance of extracted facts.
- 103+ pivotal gates and 47 pivotal trial evaluators as implemented in the
  local clinical contract.

Excluded from this v1 protocol:

- External EHR, pharmacy, laboratory or calendar integration.
- Autonomous ML treatment recommendations.
- Automatic prescribing or external orders.
- External patient recruitment.
- Any claim of IRB approval or regulatory clearance for a prospective trial.

## 3. Study Design

**Type:** Prospective, internal, observational, shadow-mode validation.
**Unit of observation:** Patient-decision episode.
**Primary surface:** `patient_profile_v2` and `/api/patients/<patient_ref>/decision-today`.
**Secondary surfaces:** dashboard, patients list, longitudinal capture, Loop Monitor.
**Duration v1:** rolling internal validation, reviewed at least monthly.

Each eligible patient-decision episode is evaluated without changing clinical
facts or executing external orders. The system may display recommended capture
actions, blockers and next safe actions, but clinician review remains mandatory.

## 4. Eligibility

### Included episodes

- Patient has a resolvable ProstaMed identity or internal demo/test identity.
- At least one clinical state or Decision Today bundle can be generated.
- Data provenance can be traced to classifier, wizard, longitudinal append,
  verified document fact, voice-reviewed fact or seeded test fixture.

### Excluded episodes

- Episodes without traceable source facts.
- Episodes using fabricated PSA/APE, testosterone, treatment lines, imaging,
  toxicity, PROs or trial eligibility.
- Episodes with unreviewed Cortana transcripts.
- Episodes flagged as cross-patient conflict or PHI provenance conflict.

## 5. Primary Endpoint

**Canonical Decision Today concordance readiness:** percentage of patient-decision
episodes in which the platform returns exactly one canonical state:

- `releaseable`
- `requires_data`
- `blocked`
- `urgent_safety`
- `redecision_required`
- `not_actionable`

The endpoint is successful only when the returned state has a traceable clinical
rationale, deduplicated missing fields, source alignment and a safe next action.

## 6. Secondary Endpoints

- **Data sufficiency:** percentage of episodes with all dominant blockers mapped
  to a capture surface.
- **Clinical safety:** percentage of episodes with no fabricated PSA/APE,
  testosterone, therapy, treatment line, imaging result, toxicity or trial
  eligibility.
- **Readiness consistency:** agreement between Decision Today, Readiness Tower,
  Tumor Board OS, Care Pathway OS, Clinical Memory OS and Autodrive.
- **Execution closure:** percentage of Care Pathway actions resolved or blocked
  with an auditable reason.
- **Outcome memory readiness:** percentage of episodes with expected vs observed
  assessment possible from real longitudinal facts.
- **Cortana safety:** percentage of voice-derived facts accepted only after
  consent, review and provenance capture.

## 7. Critical Safety Rules

The protocol fails an episode if any of the following occur:

- A therapy, line, PSA/APE value, testosterone value, imaging result, toxicity,
  PRO score, trial eligibility or outcome is shown without a real source.
- A trial evaluator returns positive eligibility with empty or critically missing
  data.
- CRPC is released without castration/testosterone and progression context.
- mHSPC intensification is released without M1 composition, volume/risk and
  fitness.
- m1CRPC sequencing is released without a real therapeutic line.
- PARP is released without traceable HRR/BRCA status and safety context.
- PSMA-RLT is released without structured PSMA PET and marrow/renal/hepatic
  safety context.
- BCR shows CRPC/PARP/PSMA-RLT pathways without documented clinical transition.

## 8. Data Sources

Allowed sources:

- Verified patient clinical facts.
- Append-only longitudinal biomarkers and clinical events.
- Structured imaging capture: MRI/PI-RADS, PSMA-PET, bone scan, CT/RECIST.
- Treatment lines only when explicitly entered.
- PROs/toxicity only when explicitly entered.
- Reviewed Cortana extraction candidates with provenance.
- Local deterministic read models and clinical gates.

Disallowed sources:

- Demo fallbacks in productive clinical surfaces.
- Unreviewed transcripts.
- Inferred treatment lines without explicit source.
- Fabricated biomarker curves.
- Untraceable trial eligibility.

## 9. Data Quality Contract

Each episode must emit an audit bundle containing:

- Patient reference or test fixture reference.
- Clinical state and Decision Today state.
- Facts used and provenance.
- Missing fields and capture surface.
- Gates/trials affected.
- Source alignment across Readiness, Tumor Board, Care Pathway, Memory and
  Autodrive.
- Anti-fallback checks.
- Timestamp and code version.

## 10. Statistical Plan v1

This v1 protocol uses descriptive validation only:

- Count of eligible episodes.
- Count and percentage by Decision Today state.
- Count and percentage of episodes blocked by each dominant field.
- Concordance between source bundles.
- Safety failure rate.
- Time-to-closure of data blockers when an action is captured.

No predictive ML model is trained or deployed under this protocol.

## 11. Human Review

Human review is required for:

- Protocol activation and amendments.
- Any claim that an episode is clinically releaseable.
- Any use of voice-derived facts.
- Any change to gate/trial logic or treatment recommendations.
- Any transition from internal shadow validation to external clinical research.

## 12. Governance

The loop may generate improvement candidates, test reports and draft artifacts.
It may not self-merge clinical logic, open external orders, modify source
clinical facts, enroll patients or claim IRB approval.

## 13. Stop Rules

Pause prospective shadow operation if:

- Any fabricated clinical fact is displayed as real.
- A cross-patient data conflict is detected.
- A critical safety blocker is bypassed.
- Decision Today differs materially between surfaces without audit explanation.
- PHI appears in logs or artifacts.

## 14. Authorization

This protocol is activated for internal shadow validation by the paired
authorization record:

`prostanet/regulatory/clinical/protocol_signed.flag`

That record is a local QMS authorization artifact, not an IRB approval and not a
site activation letter.

## 15. Next Milestone

After this protocol is active, the next clinical validation gap is prospective
data collection maturity: measuring live episodes against this protocol until
the platform has enough audited observations to support broader IRB-bound
research design.
