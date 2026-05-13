# EPIC 18 — Weekly Evidence Freshness Cron Runbook

> Audit-grade runbook for activating the weekly external delta check.
> The script + tests + Loop Monitor wiring are deployed in commit landing alongside this file.
> The cron registration is a one-time user-supervised step (auto-mode cannot register scheduled tasks).

## Manual cron registration (one-time)

In Claude Code, run:

```
/schedule weekly evidence freshness check
```

Or invoke the tool directly:

```
mcp__scheduled-tasks__create_scheduled_task(
  taskId="weekly-evidence-freshness-check",
  cronExpression="0 9 * * 1",
  description="EPIC 18 — Weekly external delta check for ProstaNet evidence freshness manifest",
  notifyOnCompletion=True,
  prompt='''
  Run: cd /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6 && python3 scripts/epic15_evidence_refresh.py --external-delta-check 2>&1 | tee -a /tmp/prostanet_evidence_refresh.log

  Report: total deltas detected, path to evidence_delta_YYYYWW.md, freshness summary.
  '''
)
```

## What the cron does each Monday 09:00 local

1. Loads `evidence_freshness_manifest.yaml` (322 records).
2. Queries ClinicalTrials.gov v2 for trials with curated NCT mapping (27 high-impact trials).
3. Queries PubMed E-utilities `esearch.fcgi` for each trial acronym (rate-limited 2.5 req/s).
4. Detects:
   - `lastUpdatePostDate > last_reviewed` (trial status changes)
   - New PMIDs since `last_reviewed` (potential long-term follow-ups, retractions)
5. Generates `output/regulatory/evidence_delta_YYYYWW.md` — triage list for clinical team.
6. Updates manifest **honestly**:
   - Records with delta → `pending_human_review=True`, `last_reviewed` preserved.
   - Records without delta → marked `fresh` with `reviewer_role=external_validated_review`.

## Loop Monitor integration

If the delta report contains ≥1 delta:
- `build_gap_intelligence` auto-includes the `evidence_delta_pending_review` candidate.
- Clinical team sees it surfaced in `/loop-monitor` UI under `evidence_gap` lane.
- High-impact trials (CHAARTED, VISION, ARASENS, etc.) trigger priority boost (`clinical_impact` ≥ 8).

## Manual run (without cron)

```bash
cd /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6

# Dry-run (no manifest mutation)
python3 scripts/epic15_evidence_refresh.py --external-delta-check --dry-run

# Limited records for testing (e.g., 10)
python3 scripts/epic15_evidence_refresh.py --external-delta-check --max-records 10 --dry-run

# Full active surveillance pass
python3 scripts/epic15_evidence_refresh.py --external-delta-check
```

## Verification

After cron fires, check:

```bash
# 1. Delta report generated
ls -la /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/output/regulatory/evidence_delta_*.md

# 2. Manifest has external_validated_review entries
grep -c "external_validated_review" /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/prostanet/regulatory/clinical/evidence_freshness_manifest.yaml

# 3. Records with delta have pending_human_review=True
grep -A1 "pending_human_review: true" /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/prostanet/regulatory/clinical/evidence_freshness_manifest.yaml | head -10

# 4. Cron run log
tail -50 /tmp/prostanet_evidence_refresh.log
```

## Failure modes & mitigation

| Failure | Mitigation |
|---------|------------|
| ClinicalTrials.gov rate-limit (429) | Script catches `HTTPError`, returns `None`, continues. No manifest mutation for that record. |
| PubMed E-utilities timeout | Same graceful handling. Record stays as-is (last week's freshness). |
| Cron didn't fire (app closed) | Runs on next Claude app launch. Document app-uptime requirement to user. |
| Delta count = 0 | Normal weekly state when no external changes. NO Loop Monitor candidate surfaced (avoid noise). |
| Many false positives (PubMed acronym collisions) | Documented limitation: PubMed esearch on bare acronym ("ATLAS") may match unrelated trials. Clinical team triages — script is decision-support, not decision-maker. |

## Clinical safety statement

The cron does NOT auto-merge any code, NOT auto-update guidelines, NOT auto-modify clinical recommendations. Its single output is a triage list for the clinical team. All clinical decisions remain under human oversight per `authorization_scope: internal_shadow_observational_validation`.
