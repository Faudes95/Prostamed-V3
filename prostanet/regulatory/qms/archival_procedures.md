# ProstaMed Part 11 Archival Procedures

Document ID: QMS-P11-ARCH-001
Status: Active internal procedure
Owner: Quality Lead
Applies to: ProstaMed clinical decision records, audit exports, signed review bundles, read-model snapshots, validation artifacts, and software release evidence.

## Purpose

This procedure defines how ProstaMed electronic records are archived, retrieved, copied, integrity-checked, and protected from alteration or loss. It supports 21 CFR Part 11 electronic record controls and the ProstaMed human-governed clinical improvement loop.

## Scope

Archived records include:

- Clinical decision audit bundles and Decision Today snapshots.
- Readiness, Tumor Board OS, Care Pathway OS, Clinical Memory OS, Autodrive, and Loop Monitor evidence bundles.
- Clinical Field Router contracts, gate/trial coverage matrices, and validation test evidence.
- Signed human review packets, controlled patch records, rollback notes, and release validation outputs.
- De-identified research-readiness exports when explicitly approved.

Raw PHI-bearing audio, temporary transcripts, and temporary work files are not long-term archive records unless explicitly accepted, signed, and converted into a reviewed clinical source document.

## Archive Package

Each archive package must contain:

1. A manifest with package ID, creation time, creator, source system, record class, retention class, and hash algorithm.
2. Record payloads in human-readable and machine-readable form when available.
3. SHA-256 hashes for every payload file.
4. A package-level SHA-256 hash over the manifest.
5. Provenance pointers to patient, encounter, decision episode, software version, and gate/trial contract when applicable.
6. A retrieval note that identifies the approved viewer or export route.

## Schedule

- Daily: local operational backup of SQLite databases, audit JSONL files, regulatory documents, and generated read-model artifacts.
- Weekly: encrypted archive package for QMS, Loop Monitor, validation, and release evidence.
- Per release: immutable release archive containing code version, tests, evidence, contracts, and rollback notes.
- Per signed clinical review: archive the signed decision or source-document bundle after review completion.

## Storage And Encryption

- Archive packages must be encrypted at rest before off-machine storage.
- Archive keys are managed by the Quality Lead or delegated security owner.
- Offsite storage must be separate from the working development machine.
- Archive locations must not expose PHI in folder names, logs, or transport metadata.
- Access must be limited to authorized clinical, quality, or security roles.

## Retrieval

Retrieval requires:

1. Requester identity and role.
2. Reason for retrieval.
3. Package ID or patient/episode/release reference.
4. Integrity verification of manifest and payload hashes before use.
5. Audit entry documenting retrieval time, requester, reason, and result.

If integrity verification fails, the package must be quarantined and escalated to Quality and Security review before use.

## Copy Procedure

When a copy is needed for review, audit, or regulatory inspection:

- Generate an exact electronic copy from the archived payload.
- Generate a human-readable copy when the record class supports it.
- Preserve provenance, timestamps, signatures, hashes, and software version.
- Mark copies as copies, not source records.
- Record copy generation in the audit trail.

## Restoration Test

At least quarterly, the Quality Lead or delegate must perform a restoration test:

1. Select one recent release archive and one clinical decision archive.
2. Verify package hashes.
3. Restore into an isolated environment.
4. Confirm that human-readable and machine-readable records open correctly.
5. Record the result, issues, and CAPA references if restoration fails.

## Failure Handling

Archive failures must be handled as quality events:

- Missing package: open CAPA review.
- Hash mismatch: quarantine package and investigate tampering, corruption, or process failure.
- Missing retrieval audit: open QMS deviation.
- PHI leakage in archive metadata: notify Security and Privacy owners.

## Responsibilities

- Quality Lead: owns this procedure, archive reviews, restoration test evidence, and CAPA escalation.
- Software Lead: maintains archive generation scripts and verifies release package completeness.
- Clinical Lead: confirms clinical record readability and clinical provenance.
- Security Owner: validates encryption, access control, and offsite protection.

## Acceptance Criteria

The archival procedure is considered implemented when:

- This document is active and referenced by the Part 11 checklist.
- The Part 11 checklist marks archival procedures as implemented.
- Compliance scoring no longer reports `part11_control_missing:archival_procedures`.
- Tests verify the artifact exists and remains linked to the checklist.
