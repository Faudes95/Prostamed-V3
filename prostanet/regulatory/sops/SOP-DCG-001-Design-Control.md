# SOP-DCG-001 — Design Control SOP

**ID**: SOP-DCG-001 · **Version**: 0.1 (LXXXVIII bootstrap) · **Effective**: 2026-04-27
**Owner**: Software Lead · **Standards**: ISO 13485 §7.3 + 21 CFR §820.30 + IEC 62304 §5

## Purpose
Establish controls for design and development of ProstaMed/ProstaNet software medical device (SaMD Class IIb 510(k)).

## Scope
All software components contributing to clinical decision-making: 89 pivotal gates, 47 trial evaluators, 18 stage schemas, decision audit builder, patient profile UI v2, longitudinal capture, what-if simulator, intake wizard.

## Procedure (8 steps)
1. **Design Planning** — Each Faubot iteration produces plan in `~/.claude/plans/`. Plan includes Context, Bugs/Gaps, Phases, Verification.
2. **Design Inputs** — Source: NCCN 5.2026 + EAU 2026 + 37 trials (CLINICAL_EVIDENCE_2026.md). Constraints: IEC 62304 Class B + 510(k) + 21 CFR Part 11.
3. **Design Output** — Code (`prostanet/`), YAML (gates), Templates (`templates/`), Tests (≥80% coverage), Doc (`audit_tracking.md` + `CLAUDE.md`).
4. **Design Review** — Each iteration: sweep regression §7.2 (target 100%), 4 safety gates, audit_tracking entry with 5 dimensions, FAUBOT_RELEASE bump.
5. **Design Verification** — Unit tests `@iec62304_phase()` (§5.5), integration §5.6, system §5.7, smoke E2E (`gate_smoke_e2e`).
6. **Design Validation** — 89 gates clinically validated against 37 trials. Trial eligibility validated end-to-end (47 evaluators). Decision audit shows 5 dimensions.
7. **Design Transfer** — GitHub Actions deployment. Auto-merge gated by `AGENTIC_AUTO_MERGE` flag. Rollback engine post-merge smoke 5min.
8. **Design Changes** — Each change requires CR per SOP-CCG-002. CR logged in `prostanet/regulatory/dhf/change_request_log.yaml`.

## Records
- Plans: `~/.claude/plans/` · DHF: `audit_tracking.md` + `regulatory/dhf/`
- CR log: `regulatory/dhf/change_request_log.yaml`
- Tests: `tests/test_audit_*.py` · Compliance snapshots: `agentic/persistence/compliance_history.jsonl`

## References
ISO 13485:2016 §7.3 · 21 CFR §820.30 · IEC 62304:2006/AMD 1:2015 · IMDRF/SaMD WG/N12 + N41 · FDA Guidance Sept 2017

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
