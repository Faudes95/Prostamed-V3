"""Faubot Agentic Loop — orquestador 8-fase (LXXXVII bootstrap).

Pattern Faubot 8-fase para auto-mejora continua:

    Fase 1 — Observe  : lee gates_coverage_aggregator + decision_audit_history
    Fase 2 — Detect   : identifica patrones (low_confidence, missing_critical, dead_controls)
    Fase 3 — Hypothesize : genera propuesta de mejora (skill-delegated)
    Fase 4 — Validate : 4 safety gates → SafetyGateReport
    Fase 5 — Merge    : auto-merge si gates ✓ (gated por AGENTIC_AUTO_MERGE flag)
    Fase 6 — Audit    : bump FAUBOT_RELEASE patch + audit_tracking entry append
    Fase 7 — Smoke    : post-merge smoke 5min → rollback si falla
    Fase 8 — Schedule : agenda próxima ejecución (cron daily 06:00 UTC)

Bootstrap LXXXVII: stub minimal (Fases 1-2-3 generan dummy proposals para
validar el pipeline). LXXXVIII reemplaza con FDA SaMD-driven gap detection.

CLI:
    python -m prostanet.agentic.improvement_loop --dry-run
    python -m prostanet.agentic.improvement_loop --target-pillar 4

Feature flags (env):
    AGENTIC_AUTO_MERGE=false  → fase 5 sólo crea PR draft, no merge
    AGENTIC_KILL_SWITCH=1     → loop sale exit 0 inmediatamente
    AGENTIC_TARGET_PILLAR=N   → restringe gap detection a pilar N (1-7)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from prostanet.agentic.safety_gates import (
    SafetyGateReport, run_all_gates, report_summary,
)
from prostanet.agentic.rollback_engine import post_merge_workflow

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROPOSALS_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "proposals_log.jsonl"
LOCK_FILE = PROJECT_ROOT / "prostanet" / "agentic" / ".loop.lock"


@dataclass
class Proposal:
    """Propuesta de mejora generada por el loop (Fase 3)."""
    kind: str  # e.g., "low_confidence_gate", "missing_input_pattern", "fda_gap_p4"
    target_pillar: int = 0  # 0 = generic; 1-7 = FDA SaMD pillar
    description: str = ""
    estimated_effort_h: float = 0.0
    severity: int = 5  # 1-10
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    proposed_release_bump: str = "patch"  # "patch" | "minor" | "major"
    skill_delegated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IterationResult:
    """Outcome final de una iteración del loop."""
    success: bool
    proposal: Proposal | None
    safety_report: SafetyGateReport | None = None
    merged: bool = False
    rolled_back: bool = False
    delta_aggregate: float = 0.0
    next_release: str = ""
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "safety_report": self.safety_report.to_dict() if self.safety_report else None,
            "merged": self.merged,
            "rolled_back": self.rolled_back,
            "delta_aggregate": self.delta_aggregate,
            "next_release": self.next_release,
            "duration_s": self.duration_s,
            "notes": self.notes,
        }


def _acquire_lock() -> bool:
    """Lock-file con PID para prevenir overlapping runs (cron concurrency)."""
    if LOCK_FILE.exists():
        try:
            existing_pid = int(LOCK_FILE.read_text().strip())
            # Check if process still alive (best-effort)
            try:
                os.kill(existing_pid, 0)
                return False  # still running
            except OSError:
                LOCK_FILE.unlink()  # stale
        except (ValueError, FileNotFoundError):
            pass
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


def _phase_1_observe() -> dict[str, Any]:
    """LXXXVIII — Computa snapshot de compliance FDA SaMD (7 pilares)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot

    snapshot = compute_compliance_snapshot(persist=False)
    return {
        "faubot_release": FAUBOT_RELEASE,
        "timestamp": datetime.now().isoformat(),
        "compliance_snapshot": snapshot,  # full ComplianceSnapshot object
        "aggregate": snapshot.aggregate,
        "total_gaps": snapshot.total_gaps,
        "gap_top": snapshot.gap_top,
    }


def _phase_2_detect(observation: dict[str, Any]) -> list[Proposal]:
    """LXXXVIII — FDA-driven gap detection via gap_prioritizer.

    En lugar de propuestas genéricas, detecta el gap top del compliance snapshot
    (filtrado por target_pillar si se especifica) y retorna 1 propuesta con la
    información completa del gap (kind, severity, effort_h, artifact_path).
    """
    from prostanet.agentic.gap_prioritizer import top_gap, rank_gaps

    snapshot = observation.get("compliance_snapshot")
    if snapshot is None:
        return [Proposal(
            kind="snapshot_unavailable",
            target_pillar=0,
            description="compliance_snapshot missing from observation phase",
            estimated_effort_h=0.5,
            severity=2,
        )]

    target_pillar = int(os.environ.get("AGENTIC_TARGET_PILLAR", "0") or 0)
    if target_pillar:
        # Filter to gaps for this pillar only
        ranked = [g for _, g in rank_gaps(snapshot) if g.pillar_id == target_pillar]
        gap = ranked[0] if ranked else None
    else:
        gap = top_gap(snapshot)

    if gap is None:
        # All blocked or all clean
        if snapshot.aggregate >= 96.0:
            return [Proposal(
                kind="compliance_target_reached",
                target_pillar=0,
                description=f"Aggregate {snapshot.aggregate:.1f}% ≥ 96% target. Only prospective study unfinished.",
                estimated_effort_h=0.0,
                severity=1,
            )]
        return [Proposal(
            kind="all_gaps_blocked",
            target_pillar=0,
            description="No actionable gap (all blocked by human or stuck). Escalate.",
            estimated_effort_h=0.5,
            severity=4,
        )]

    return [Proposal(
        kind=gap.kind,
        target_pillar=gap.pillar_id,
        description=gap.description,
        estimated_effort_h=gap.effort_h,
        severity=gap.severity,
        proposed_changes=[{
            "artifact_path": gap.artifact_path,
            "evidence_source": gap.evidence_source,
        }] if (gap.artifact_path or gap.evidence_source) else [],
        skill_delegated=_route_skill_for_gap(gap.kind),
    )]


def _route_skill_for_gap(gap_kind: str) -> str:
    """Mapping gap.kind → skill name (per plan §C delegation pattern)."""
    if gap_kind.startswith("sop_missing"):
        return "anthropic-skills:docx + fda-medtech-compliance-auditor"
    if gap_kind.startswith("regulatory_doc_missing"):
        return "anthropic-skills:fda-medtech-compliance-auditor + docx"
    if gap_kind.startswith("fmea_entry_missing") or gap_kind == "fmea_file_missing":
        return "anthropic-skills:clinical-reports + xlsx + healthcare-cdss-patterns"
    if gap_kind == "trial_evidence_missing":
        return "anthropic-skills:pubmed-database + iterative-retrieval"
    if gap_kind == "retro_validation_missing":
        return "anthropic-skills:clinical-reports (custom AUC/PPV/NPV computation)"
    if gap_kind == "stride_threat_model_missing" or gap_kind.startswith("stride_threat_categories"):
        return "anthropic-skills:code-reviewer (custom STRIDE template)"
    if gap_kind == "sbom_missing" or gap_kind.startswith("sbom_"):
        return "anthropic-skills:code-reviewer + pip-audit"
    if gap_kind == "cve_critical_open":
        return "anthropic-skills:code-reviewer + fda-medtech-compliance-auditor"
    if gap_kind.startswith("traceability_") or gap_kind == "traceability_matrix_missing":
        return "anthropic-skills:xlsx + fda-medtech-compliance-auditor"
    if gap_kind == "iec62304_test_mapping_incomplete":
        return "anthropic-skills:code-reviewer + gate-validator"
    if gap_kind == "prospective_protocol_missing":
        return "anthropic-skills:clinical-reports + docx + fda-medtech-compliance-auditor"
    if gap_kind == "cds_criteria_yaml_missing" or gap_kind.startswith("cds_criteria"):
        return "anthropic-skills:fda-medtech-compliance-auditor"
    return "(no skill mapping; manual review)"


def _phase_3_hypothesize(proposals: list[Proposal]) -> Proposal | None:
    """Selecciona la mejor propuesta. LXXXVIII: gap_prioritizer ya devolvió el top en Fase 2."""
    if not proposals:
        return None
    return proposals[0]  # phase 2 already returns top-1 sorted


def _phase_4_validate(proposal: Proposal, *, fast_mode: bool = False) -> SafetyGateReport:
    """Run 4 safety gates."""
    return run_all_gates(fast_mode=fast_mode)


def _phase_5_merge(proposal: Proposal, report: SafetyGateReport) -> tuple[bool, str]:
    """Auto-merge si todos los gates pasan + AGENTIC_AUTO_MERGE=true.

    Returns:
        (merged: bool, message: str)
    """
    if not report.all_passed:
        return False, f"safety_gates failed: {report_summary(report)}"
    auto_merge = os.environ.get("AGENTIC_AUTO_MERGE", "false").lower() in {"1", "true", "yes"}
    if not auto_merge:
        return False, "AGENTIC_AUTO_MERGE=false · PR draft only (Shadow mode)"
    # Bootstrap LXXXVII: NO ejecuta git ops aún (proposal es dummy)
    return False, "LXXXVII bootstrap · merge stub no-op (real merge in LXXXVIII)"


def _phase_6_audit(proposal: Proposal, merged: bool, report: SafetyGateReport,
                    *, snapshot_after: Any = None, snapshot_before: Any = None) -> str:
    """Append entry a proposals_log.jsonl + persist snapshot + return next release bump."""
    PROPOSALS_LOG.parent.mkdir(parents=True, exist_ok=True)
    delta = 0.0
    if snapshot_before is not None and snapshot_after is not None:
        delta = snapshot_after.aggregate - snapshot_before.aggregate
    entry = {
        "ts": datetime.now().isoformat(),
        "proposal": proposal.to_dict() if proposal else None,
        "safety_report_summary": report_summary(report) if report else None,
        "merged": merged,
        "compliance_aggregate_before": snapshot_before.aggregate if snapshot_before else None,
        "compliance_aggregate_after": snapshot_after.aggregate if snapshot_after else None,
        "compliance_delta": round(delta, 2),
        "gap_top_before": snapshot_before.gap_top if snapshot_before else None,
        "gap_top_after": snapshot_after.gap_top if snapshot_after else None,
    }
    with PROPOSALS_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")

    # Persist new snapshot to history (only if merged + delta non-trivial)
    if merged and snapshot_after is not None:
        snapshot_after.persist()

    # Decide bump: patch by default, minor if pillar crossed bracket (each 10%)
    bump = "patch"
    if snapshot_before and snapshot_after:
        for key in snapshot_after.scores:
            ps_before = snapshot_before.scores.get(key)
            ps_after = snapshot_after.scores[key]
            if ps_before is None:
                continue
            bracket_before = int(ps_before.score) // 10
            bracket_after = int(ps_after.score) // 10
            if bracket_after > bracket_before:
                bump = "minor"
                break
    return bump


def _phase_7_post_merge_smoke(proposal: Proposal, merged: bool) -> dict[str, Any]:
    """Post-merge smoke 5min + rollback si falla."""
    if not merged:
        return {"skipped": True, "reason": "not merged"}
    # Bootstrap LXXXVII: dry-run mode (no real git revert)
    return post_merge_workflow("HEAD", wait_s=0, dry_run=True)


def _phase_8_schedule_next() -> str:
    """Returns ISO timestamp of next scheduled run (cron daily 06:00 UTC)."""
    from datetime import timedelta
    now = datetime.utcnow()
    next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run.isoformat() + "Z"


def run_iteration(*, dry_run: bool = False, target_pillar: int | None = None,
                    fast_mode: bool = False) -> IterationResult:
    """Ejecuta 1 iteración completa del loop (8 fases)."""
    import time
    t0 = time.monotonic()

    if os.environ.get("AGENTIC_KILL_SWITCH") == "1":
        return IterationResult(
            success=False, proposal=None,
            notes=["AGENTIC_KILL_SWITCH=1 · loop disabled"],
            duration_s=time.monotonic() - t0,
        )

    if not _acquire_lock():
        return IterationResult(
            success=False, proposal=None,
            notes=["another iteration in flight (lock held) · skipping"],
            duration_s=time.monotonic() - t0,
        )

    if target_pillar:
        os.environ["AGENTIC_TARGET_PILLAR"] = str(target_pillar)

    try:
        observation = _phase_1_observe()
        snapshot_before = observation.get("compliance_snapshot")
        candidates = _phase_2_detect(observation)
        proposal = _phase_3_hypothesize(candidates)
        if not proposal:
            return IterationResult(
                success=True, proposal=None,
                notes=["no proposals generated · system healthy or skill backend unavailable"],
                duration_s=time.monotonic() - t0,
            )
        report = _phase_4_validate(proposal, fast_mode=fast_mode)
        merged, merge_msg = _phase_5_merge(proposal, report)

        # LXXXVIII — re-snapshot post-merge para computar delta
        snapshot_after = None
        delta_aggregate = 0.0
        if merged:
            from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
            snapshot_after = compute_compliance_snapshot(persist=False)
            delta_aggregate = snapshot_after.aggregate - (snapshot_before.aggregate if snapshot_before else 0.0)

        bump = _phase_6_audit(proposal, merged, report,
                                 snapshot_before=snapshot_before,
                                 snapshot_after=snapshot_after)
        smoke_outcome = _phase_7_post_merge_smoke(proposal, merged)
        next_run = _phase_8_schedule_next()

        notes = [merge_msg]
        if proposal.skill_delegated:
            notes.append(f"skill_delegated: {proposal.skill_delegated}")
        if snapshot_before:
            notes.append(f"compliance: {snapshot_before.aggregate:.2f}% → " +
                         (f"{snapshot_after.aggregate:.2f}% (Δ {delta_aggregate:+.2f}pp)"
                          if snapshot_after else "(unchanged · dry_run)"))
        if smoke_outcome.get("decision", {}).get("should_rollback"):
            notes.append("ROLLED BACK: smoke failed post-merge")
            rolled_back = True
        else:
            rolled_back = False

        return IterationResult(
            success=report.all_passed,
            proposal=proposal,
            safety_report=report,
            merged=merged,
            rolled_back=rolled_back,
            delta_aggregate=delta_aggregate,
            next_release=f"bump_{bump}",
            duration_s=time.monotonic() - t0,
            notes=notes + [f"next scheduled: {next_run}"],
        )
    finally:
        _release_lock()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Faubot Agentic Loop — 8-phase orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="No git ops, no DB writes")
    parser.add_argument("--target-pillar", type=int, choices=range(0, 8), default=0,
                        help="Restrict to FDA SaMD pillar (1-7) or generic (0)")
    parser.add_argument("--fast", action="store_true", help="Faster safety gates (subset tests)")
    args = parser.parse_args()

    print(f"Faubot Agentic Loop LXXXVII — starting iteration (dry_run={args.dry_run})")
    result = run_iteration(
        dry_run=args.dry_run,
        target_pillar=args.target_pillar or None,
        fast_mode=args.fast,
    )
    print(json.dumps(result.to_dict(), indent=2, default=str))
    sys.exit(0 if result.success else 1)
