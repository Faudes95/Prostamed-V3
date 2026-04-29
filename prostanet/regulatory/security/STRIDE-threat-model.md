# STRIDE Threat Model — ProstaMed/ProstaNet

**Methodology**: Microsoft STRIDE framework
**Standard**: FDA Premarket Cybersecurity Guidance Sept 2023 + AAMI TIR57:2016
**Version**: 0.1 (LXXXVIII bootstrap) · **Date**: 2026-04-27
**Owner**: Software Lead + Cybersecurity Consultant (TBD)

---

## System overview

ProstaMed is a Flask web app (Python 3.12) backed by SQLite (`prostanet_tracking.db`),
serving clinical decision recommendations to authenticated users (urologists,
oncologists). PHI (NSS, name, clinical history) flows through:

- Frontend: Jinja2 templates + Tailwind + Chart.js (browser)
- Backend: Flask routes + service layer + decision engines
- Persistence: SQLite (encrypted at rest TBD) + audit logs
- Optional: GitHub Actions cron for Faubot Agentic Loop

## Trust boundaries
1. Browser ↔ Flask (HTTPS required production)
2. Flask ↔ SQLite (local file, perms 600)
3. Flask ↔ GitHub Actions (cron via PAT/OIDC)
4. Flask ↔ External evidence sources (NCCN PDFs, PubMed API)

---

## STRIDE analysis

### S — Spoofing
**Threats**:
- S.1 Clinician impersonation via stolen credentials
- S.2 Forged session cookie
- S.3 Auto-merge actor impersonation in GitHub Actions

**Mitigations**:
- M.S.1 require_clinical_session decorator + scope ABAC (phi:read/write/audit)
- M.S.2 Flask session signed with strong secret + httponly + secure flags
- M.S.3 GitHub PAT scoped + branch protection + signed commits (planned)

### T — Tampering
**Threats**:
- T.1 Unauthorized DB write to clinical_assessments (alter PSA values)
- T.2 YAML catalog tampering (89 gates)
- T.3 audit_tracking.md tampering (cover up regression)

**Mitigations**:
- M.T.1 SQL parameterized queries + scope phi:write enforcement
- M.T.2 Per-gate YAML SHA validated by gates_yaml_loader
- M.T.3 audit_tracking.md append-only convention + git history immutable
- M.T.4 Faubot Agentic Loop safety gates pre-merge

### R — Repudiation
**Threats**:
- R.1 Clinician denies issuing override on transition_proposal
- R.2 Auto-merge actor denies introducing a regression
- R.3 Patient denies consent received

**Mitigations**:
- M.R.1 Override requires justification ≥10 chars + audit log entry
- M.R.2 Each auto-merge logs proposal + safety_gates report + commit SHA
- M.R.3 Consent signature with content_hash + timestamp + signer name
- M.R.4 21 CFR Part 11 electronic signature (planned, see part11_checklist.yaml)

### I — Information Disclosure
**Threats**:
- I.1 PHI leak via decision_audit endpoint without scrubbing
- I.2 Stack trace exposes internal paths/tokens
- I.3 Log files contain PHI (nss + full_name)

**Mitigations**:
- M.I.1 decision_audit endpoint scrubs nss + full_name from input_snapshot (LXX #65A)
- M.I.2 Production WSGI: debug=False + custom 500 handler
- M.I.3 Logger sanitizes PHI in structured fields
- M.I.4 HTTPS enforced production + HSTS header (planned)

### D — Denial of Service
**Threats**:
- D.1 Faubot Agentic Loop infinite iteration on stuck gap
- D.2 Decision audit recompute loop on malformed input
- D.3 Rate-limited brute force on /login
- D.4 Concurrent cron runs of Faubot loop

**Mitigations**:
- M.D.1 improvement_loop.py: skip after ≥3 consecutive iterations on same gap (`human_intervention_required`)
- M.D.2 Input validation in canonicalize_payload (LXXXV.b unhashable list defensive fix)
- M.D.3 Rate limit on /login (planned, ALT-1 from SECURITY_REVIEW.md)
- M.D.4 Lock-file `agentic/.loop.lock` + PID check prevents overlapping cron runs

### E — Elevation of Privilege
**Threats**:
- E.1 Scope ABAC bypass (phi:read access without role)
- E.2 Auto-merge bypass with malicious PR
- E.3 SQL injection escalating to admin

**Mitigations**:
- M.E.1 require_clinical_session decorator strict enforcement + DENY by default
- M.E.2 4 safety gates MUST pass + AGENTIC_AUTO_MERGE feature flag + Shadow mode default
- M.E.3 Parameterized SQL throughout (no string interpolation in queries)
- M.E.4 No `eval()` or `exec()` on user input (verified in pillar_3 tests-mapped)

---

## Open issues / TODO
- HSTS header enforcement (currently flag-controlled in Flask config)
- Encrypted at rest for SQLite (currently filesystem-level only)
- Coordinated disclosure policy formalization (`SECURITY.md` minimal stub exists)
- Penetration testing by external consultant (planned LXXXVIII iteration +N)

## References
- FDA Premarket Cybersecurity Guidance Sept 2023
- AAMI TIR57:2016
- OWASP Top 10 (2021)
- NIST SP 800-53 (PHI handling)

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
