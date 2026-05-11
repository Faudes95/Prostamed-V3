# Software Development Plan (SDP) — ProstaMed/ProstaNet

**Version**: 0.1 (LXXXVIII bootstrap) · **Date**: 2026-04-27 · **Owner**: Software Lead
**Standard**: IEC 62304:2006/AMD 1:2015 §5.1 + ISO 13485 §7.3.2

## 1. Purpose

This Software Development Plan (SDP) defines the lifecycle approach for ProstaMed/ProstaNet, a Class II 510(k) Software as a Medical Device (SaMD) for prostate cancer clinical decision support.

## 2. Scope

Applies to all software components in `prostanet/` repository. Covers code, YAML catalogs, Jinja2 templates, tests, and regulatory documentation.

## 3. Process Model — Faubot Iterative

ProstaMed follows a **Faubot Iterative Lifecycle**:
- Each iteration is documented in `prostanet/audit_tracking.md`
- Each iteration produces a discrete release (FAUBOT_RELEASE bumped)
- Each iteration includes 8 phases (per `prostanet/agentic/improvement_loop.py`):
  1. Observe (current state)
  2. Detect (patterns/gaps)
  3. Hypothesize (proposal)
  4. Validate (4 safety gates)
  5. Merge (gated by AGENTIC_AUTO_MERGE flag)
  6. Audit (release bump + audit_tracking entry)
  7. Smoke (post-merge verification)
  8. Schedule (next iteration)

This maps to IEC 62304 §5 lifecycle phases:
- §5.1 Software development planning → **this SDP** + `~/.claude/plans/`
- §5.2 Software requirements analysis → `prostanet/CLINICAL_EVIDENCE_2026.md`
- §5.3 Software architectural design → `CLAUDE.md §6` + module structure
- §5.4 Software detailed design → per-module in `prostanet/`
- §5.5 Software unit implementation and verification → `tests/test_*.py` (3942+)
- §5.6 Software integration and integration testing → `tests/test_audit*.py`
- §5.7 Software system testing → smoke E2E + Playwright (LXXXVIII +N)
- §5.8 Software release → FAUBOT_RELEASE versioning

## 4. Roles

Per `prostanet/regulatory/qms/roster.yaml`:
- Quality Lead (Management Representative)
- Software Lead (this SDP owner)
- Clinical Lead

## 5. Software Safety Class

**Class B** per `prostanet/regulatory/regulatory/iec62304_class.md`. Specific modules may escalate to Class C upon FMEA refinement (Pilar 4 LXXXVIII).

## 6. Methodology

- **Language**: Python 3.12 (target), 3.14 (compatible)
- **Framework**: Flask (web), pytest (testing)
- **Persistence**: SQLite (`prostanet_tracking.db`)
- **Frontend**: Jinja2 + Tailwind CSS + Chart.js + chartjs-plugin-annotation
- **Version Control**: Git
- **CI/CD**: GitHub Actions (`.github/workflows/agentic_loop.yml`)
- **Documentation**: Markdown (audit_tracking.md, CLAUDE.md, regulatory/*)

## 7. Verification & Validation Strategy

| IEC 62304 Phase | Verification | Validation |
|---|---|---|
| §5.5 (unit) | pytest with `@iec62304_phase("5.5")` decorators | Per-gate clinical evidence |
| §5.6 (integration) | `tests/test_audit_*.py` cross-domain integration | Round-trip canonicalize→torre→forecast |
| §5.7 (system) | Flask test client + Playwright (LXXXVIII +N) | Real patient profile renders end-to-end |
| §5.8 (release) | 4 safety gates + audit_tracking entry | FAUBOT_RELEASE bump |

## 8. Configuration Management

- Git for code
- YAML for declarative gates catalog (per-gate SHA via gates_yaml_loader)
- audit_tracking.md as append-only iteration log (pseudo-DHF until formal LXXXVIII)
- FAUBOT_RELEASE constant in `prostanet/shared/algorithm_version.py`

## 9. Problem Resolution

Per SOP-CAPA-003. Each issue tracked in CAPA log. Auto-merge rollbacks auto-create CAPA stubs.

## 10. Software Maintenance

- Monthly NCCN/EAU guideline check (cron-detected version bumps)
- Quarterly FMEA review (Clinical Lead)
- Yearly Risk Management Plan (RMP) refresh

## 11. Deliverables per iteration

Each Faubot iteration produces:
1. Code changes in `prostanet/`
2. Updated `audit_tracking.md` entry with 5 dimensions (Razón / Componentes / Métricas / Hipótesis / Próximo paso)
3. Updated `CLAUDE.md` §2 + §3 + §4
4. Tests dedicated (`tests/test_audit_lxxxvi*` etc)
5. Bumped FAUBOT_RELEASE
6. (If applicable) Compliance snapshot in `compliance_history.jsonl`

## 12. References
- IEC 62304:2006/AMD 1:2015
- ISO 13485:2016 §7.3
- 21 CFR §820.30
- IMDRF/SaMD WG/N12FINAL:2014 + N41 FINAL:2017
- FDA Guidance: SaMD Clinical Evaluation (Sept 2017)
- FDA Guidance: Premarket Cybersecurity (Sept 2023)

## 13. Revision History

| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
