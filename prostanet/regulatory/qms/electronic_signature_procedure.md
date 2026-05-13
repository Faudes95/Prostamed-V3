# ProstaMed Part 11 Electronic Signature Procedure

Document ID: QMS-P11-ESIG-001
Status: Active internal procedure
Owner: Quality Lead
Applies to: clinical decision signatures, source-document verification, Cortana reviewed extraction acceptance, consent evidence, and human authorization of controlled loop patches.

## Purpose

This procedure defines the minimum electronic signature controls for ProstaMed records. It supports 21 CFR Part 11 Subpart C by binding a human signer, an authenticated session or re-authentication factor, explicit intent, record content hash, timestamp, software version, and a tamper-evident signature value.

## Scope

Electronic signatures are required for:

- Clinical decisions marked as released or approved for action.
- Reviewed Cortana candidates before writing accepted structured facts to the record.
- Source-document verification tasks.
- Consent evidence records.
- Human authorization of controlled autonomous-improvement patches.
- Any future release package that changes clinical logic, gates, trials, Decision Today, Readiness, Tumor Board OS, Care Pathway OS, Clinical Memory OS, Autodrive, or Cortana.

## Signature Envelope

Each signed record must include:

1. Record type and record reference.
2. SHA-256 content hash of the signed payload.
3. Signer ID, signer name, and signer role.
4. Explicit signing meaning such as `clinical_decision_signed`, `source_document_verified`, `voice_extraction_accepted`, `loop_patch_authorized`, or `consent_signed`.
5. Authentication method and verified authentication factor.
6. UTC timestamp.
7. Software version when available.
8. HMAC-SHA256 signature value over the canonical envelope.
9. Signature ID derived from the canonical envelope.

The implementation artifact is `prostanet/shared/electronic_signature.py`.

## Authentication Requirement

The signer must be bound to a unique user identity and a verified authentication method. Accepted v1 methods are:

- `clinical_session_reauth`
- `password_reentry`
- `idp_reauth`
- `voice_consent_review`
- `human_patch_authorization`

Production deployments must provide a stable signing secret through `PROSTAMED_ESIGN_SECRET` or `PROSTANET_SECRET_KEY`. If no stable secret is present in production, signature creation must fail closed.

## Record Binding

The signature binds to the signed record through `sha256:<hex>` content hash. The raw payload does not need to be stored in the signature envelope, but the signed payload or archived record must be retrievable through the audit trail and archival procedure.

If the record payload changes, signature validation must fail with `record_payload_hash_mismatch` or `signature_value_mismatch`.

## Clinical Safety Boundary

Electronic signature does not make a clinical recommendation correct by itself. It only proves that a specific human signed a specific payload with a specific intent at a specific time.

The following remain prohibited:

- Signing fabricated PSA/APE, testosterone, treatment lines, therapies, or trial eligibility.
- Using a signature to bypass missing Decision Today requirements.
- Writing voice-extracted fields without medical review.
- Auto-merging or auto-authorizing clinical logic changes.

## Verification And Audit

Before accepting a signed record, ProstaMed must verify:

1. Envelope schema is supported.
2. Required signer, record, intent, auth, and timestamp fields are present.
3. Signature meaning and authentication method are approved.
4. Record content hash matches the payload when payload is available.
5. Signature ID matches the canonical envelope.
6. HMAC signature value matches the canonical envelope.

Each accepted signature must be auditable through the associated patient event, decision bundle, verification task, consent evidence, or loop authorization packet.

## Failure Handling

Invalid signatures must not be accepted. The system must show the reason in audit-safe terms and avoid logging PHI-bearing payloads. Failed signatures must be re-created after the underlying record, signer identity, or authentication state is corrected.

## Acceptance Criteria

- `prostanet/shared/electronic_signature.py` creates and validates tamper-evident signature envelopes.
- The Part 11 checklist marks `electronic_signature` as implemented.
- Compliance scoring no longer reports `part11_control_missing:electronic_signature`.
- Regression tests prove hash binding, tamper detection, and required authentication metadata.
