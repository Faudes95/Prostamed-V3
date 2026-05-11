# SOP-CAPA-003 — Corrective and Preventive Action (CAPA) SOP

**ID**: SOP-CAPA-003 · **Version**: 0.1 (LXXXVIII bootstrap) · **Effective**: 2026-04-27
**Owner**: Quality Lead · **Standards**: ISO 13485 §8.5.2 + §8.5.3 + 21 CFR §820.100

## Purpose
Establish process to investigate, correct, and prevent recurrence of nonconformities in ProstaMed software, processes, and documentation.

## Triggers (initiate CAPA when)
- Sweep regression test failures detected post-release
- Gate firing produces clinically incorrect recommendation (post-market complaint)
- Auto-merge by Faubot Agentic Loop triggered rollback
- Audit (internal or external) finding
- User-reported safety concern (via `SECURITY.md` disclosure or clinical channel)
- Compliance score regression (any pillar drops ≥5pp without explanation)

## Procedure

### Investigation (within 5 business days)
1. Quality Lead opens CAPA record: `regulatory/qms/capa_log.yaml` with id (CAPA-YYYY-NNN).
2. Root cause analysis (RCA): use 5 Whys + fishbone where applicable.
3. Document affected components (code paths, gate codes, patient cohort impact).
4. Severity classification (Class A/B/C per IEC 62304 + clinical impact).

### Corrective Action (within 30 days)
1. Implement fix via CR (SOP-CCG-002).
2. Verify fix via dedicated test (H.G#### hypothesis).
3. Run sweep §7.2 + 4 safety gates.
4. Bump FAUBOT_RELEASE patch (e.g., LXXXVIII.1).
5. Update audit_tracking.md with CAPA reference.

### Preventive Action
1. Identify systemic causes (not just symptom).
2. Update affected SOPs (e.g., SOP-DCG-001 if design gap, SOP-CCG-002 if change process gap).
3. Update FMEA (`regulatory/risk/fmea-prostanet-2026.yaml`) if new hazard discovered.
4. Update DHF traceability matrix to add new req → test row.
5. Communicate lessons learned to all roles (roster.yaml).

### Effectiveness Review (90 days post-implementation)
1. Verify no recurrence in monitoring period (compliance dashboard).
2. Quality Lead signs off effectiveness review.
3. CAPA closed with `closed_at` timestamp + effectiveness evidence.

## Records
- CAPA log: `regulatory/qms/capa_log.yaml`
- RCA reports: `regulatory/qms/rca/CAPA-YYYY-NNN-rca.md`
- Effectiveness reviews: `regulatory/qms/effectiveness_reviews.yaml`

## Integration with Faubot Agentic Loop
- Each rollback event in `rollback_log.jsonl` auto-creates CAPA stub.
- Compliance regressions detected by `compliance_scorer` raise gap with `kind=regression_recovery` severity=10 → CAPA prioritized.

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
