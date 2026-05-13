# ProstaMed Part 11 Record Retention Policy

Document ID: QMS-P11-RET-001
Status: Active internal policy
Owner: Quality Lead
Applies to: clinical records, Decision Today bundles, longitudinal evidence, signed source documents, Cortana artifacts, QMS evidence, security logs, research-readiness datasets, and autonomous-improvement loop artifacts.

## Purpose

This policy defines how long ProstaMed electronic records are retained, when they must be archived, and when temporary artifacts must be purged. It supports 21 CFR Part 11 record retention expectations by ensuring electronic records remain accurate, protected, and readily retrievable throughout their retention period.

The machine-readable implementation is `prostanet/shared/retention_policy.py`.

## Regulatory Basis

Part 11 applies to electronic records and signatures that are required to be maintained under predicate rules or submitted to FDA in electronic form. FDA guidance emphasizes that organizations should determine and document which records are Part 11 records and should preserve accurate, ready retrieval throughout the retention period required by applicable predicate rules.

This v1 policy is an internal ProstaMed minimum. It does not replace institutional, jurisdictional, hospital, sponsor, IRB, or legal-hold requirements. If another applicable rule requires longer retention, the longer retention period wins.

## Retention Schedule

| Record class | Retention trigger | Minimum retention | Archive? | Disposition |
| --- | --- | ---: | --- | --- |
| Patient clinical record | Last clinical use or record close | 10 years | Yes | Retain secure archive, then legal/quality review before purge |
| Clinical decision audit / Decision Today bundle | Decision signature or creation | 10 years | Yes | Retain secure archive, then legal/quality review before purge |
| Signed source document or verified extracted fact bundle | Signature or verification date | 10 years | Yes | Retain secure archive, then legal/quality review before purge |
| QMS, validation, release, and rollback evidence | Release or quality review date | 10 years | Yes | Retain secure archive |
| Raw Cortana audio pending review | Capture time | 7 days maximum | No | Purge after review signature/discard or expiry |
| Temporary unverified Cortana transcript | Capture time | 30 days maximum | No | Purge after review signature/discard or expiry |
| Reviewed and signed voice transcript/source document | Signature date | 10 years | Yes | Retain secure archive, then legal/quality review before purge |
| Approved de-identified research/readiness dataset | Dataset version release | 25 years or protocol-defined | Yes | Retain research archive or protocol-defined disposition |
| Security/access audit log without PHI payload | Log event time | 2 years | Yes | Retain security archive |
| Debug/application log without PHI payload | Log event time | 90 days | No | Purge after expiry |
| Temporary work file or staging artifact | Creation time | 30 days | No | Purge after expiry |

## PHI And Voice Artifacts

Raw audio and temporary transcripts are temporary working artifacts. They must not become long-term records unless a clinician reviews them, accepts the relevant content, signs the resulting transcript/source document, and stores provenance.

After signature or discard:

1. Raw audio should be deleted.
2. Temporary transcript should be deleted or converted into a signed source document.
3. The system should retain only signed transcript, accepted fields, hashes, model/runtime provenance, user, timestamp, and audit trail.
4. No PHI-bearing audio/transcript content should be written to application logs.

## Legal Hold And Quality Hold

Any record may be placed on legal hold or quality hold. Hold status overrides routine purge eligibility. A held record may not be purged until the hold is released by the responsible quality/legal owner.

## Archive And Retrieval

Records marked as archive-required must follow `QMS-P11-ARCH-001`. Archive packages must preserve:

- Record payload or approved export.
- Human-readable copy when applicable.
- SHA-256 hashes.
- Signature envelope when signed.
- Provenance and source references.
- Software version and validation context.
- Retrieval instructions.

## Research Dataset Boundary

Research-readiness and AI-readiness datasets may be retained longer only when they are de-identified or approved by the applicable protocol/consent pathway. Patient-identifiable records used to generate those datasets remain governed by the patient clinical record retention class unless a stricter rule applies.

## Purge Requirements

Purge jobs must be controlled and auditable. Before purging, the system or reviewer must confirm:

1. Record class is known.
2. Retention period elapsed or artifact was signed/discarded.
3. No legal hold, quality hold, investigation, or active clinical dependency exists.
4. Archive package exists when required.
5. Purge event is recorded without PHI payload in logs.

## Acceptance Criteria

- `retention_policy` is marked implemented in the Part 11 checklist.
- `prostanet/shared/retention_policy.py` exposes the official v1 retention schedule.
- Compliance scoring no longer reports `part11_control_missing:retention_policy`.
- Tests verify schedule coverage, temporary Cortana purge behavior, long-retention clinical records, and legal-hold override.
