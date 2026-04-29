# SOP-CCG-002 — Change Control SOP

**ID**: SOP-CCG-002 · **Version**: 0.1 (LXXXVIII bootstrap) · **Effective**: 2026-04-27
**Owner**: Software Lead · **Standards**: ISO 13485 §7.3.7 + 21 CFR §820.70(b) + IEC 62304 §6

## Purpose
Control all changes to ProstaMed software, configurations, and regulatory documentation throughout lifecycle.

## Scope
Applies to:
- Code changes (any commit to `prostanet/`)
- YAML catalog changes (89 gates + DDI cross-checks)
- Template changes (UI v2)
- SOP changes (this file + others in `regulatory/`)
- FAUBOT_RELEASE bumps
- Auto-merged changes by Faubot Agentic Loop (LXXXVII bootstrap)

## Procedure

### Manual changes
1. Create CR in `regulatory/dhf/change_request_log.yaml` with: id (CR-YYYY-NNN), title, description, impact_clinical, impact_regulatory, risk_assessment_link, approver.
2. Reviewer (Software Lead OR Quality Lead) signs off CR.
3. Implement change in feature branch.
4. Run sweep §7.2 + 4 safety gates locally.
5. Open PR linking CR-id.
6. Reviewer approves merge.
7. Post-merge: bump FAUBOT_RELEASE, update audit_tracking.md.
8. CR marked `closed=true` with merge_commit_sha.

### Auto-merged changes (Faubot Agentic Loop)
1. `improvement_loop.py` generates Proposal with `kind`, `target_pillar`, `severity`.
2. CR auto-created with `controlled_change=true` flag pointing to this SOP.
3. 4 safety gates MUST pass.
4. Post-merge smoke 5min (rollback_engine.py).
5. If smoke fails → auto-revert + CR marked `rolled_back=true`.
6. Bootstrap policy: shadow mode (false) → auto_merge=true after 30 PRs ≥95% success.

## Emergency changes
Critical security/safety fixes can bypass standard review with CMO + Quality Lead joint approval. Must complete retrospective full review within 5 business days.

## Records
- CR log: `prostanet/regulatory/dhf/change_request_log.yaml`
- Audit trail: `prostanet/audit_tracking.md`
- Auto-merge log: `prostanet/agentic/persistence/proposals_log.jsonl`
- Rollback log: `prostanet/agentic/persistence/rollback_log.jsonl`

## Revision History
| Version | Date | Description | Approved By |
|---|---|---|---|
| 0.1 | 2026-04-27 | Initial bootstrap (Faubot LXXXVIII) | pending |
