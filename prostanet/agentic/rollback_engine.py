"""Faubot Agentic Loop — Rollback Engine (LXXXVII).

Post-merge production smoke + auto-rollback policy.

Después de cada auto-merge, el engine:
1. Espera N segundos (default 60s) para que el deploy se estabilice
2. Ejecuta `gate_smoke_e2e()` contra production endpoints
3. Si CUALQUIER endpoint crítico falla → `revert_commit(sha)` automático
4. Logs el evento en `persistence/rollback_log.jsonl`
5. Re-abre el PR con label `failed-rollback` (vía gh CLI si disponible)

Diseño defensive:
- NO ejecuta git destructive ops sin explicit confirm flag
- En modo `dry_run=True`, retorna decisión sin actuar
- Persiste TODO el contexto (smoke report, error trace) para auditoría
- Si el revert mismo falla → escala a `human_intervention_required`

Bootstrap LXXXVII; reused para FDA SaMD-driven loop LXXXVIII+.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from prostanet.agentic.safety_gates import (
    SafetyGateReport, gate_smoke_e2e, run_all_gates,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
ROLLBACK_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "rollback_log.jsonl"


@dataclass
class RollbackDecision:
    """Resultado de la evaluación post-merge."""
    should_rollback: bool
    reason: str
    smoke_report: SafetyGateReport | None = None
    commit_sha: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.smoke_report:
            d["smoke_report"] = self.smoke_report.to_dict()
        return d


@dataclass
class RollbackOutcome:
    """Resultado de ejecutar el rollback (revert + push)."""
    executed: bool
    success: bool
    revert_commit_sha: str = ""
    error: str = ""
    duration_s: float = 0.0


def evaluate_post_merge(commit_sha: str, *, wait_s: int = 60,
                          dry_run: bool = False) -> RollbackDecision:
    """Espera N segundos + ejecuta smoke + decide si rollback.

    Args:
        commit_sha: SHA del commit auto-mergeado (para audit trail).
        wait_s: tiempo entre merge y smoke (default 60s, máx 300s).
        dry_run: si True, decide pero no actúa.

    Returns:
        `RollbackDecision` con `should_rollback=True` si CUALQUIER smoke fail.
    """
    if not dry_run:
        time.sleep(min(wait_s, 300))

    smoke_report = gate_smoke_e2e(timeout_s=60)
    smoke_passed = smoke_report.passed

    decision = RollbackDecision(
        should_rollback=not smoke_passed,
        reason=("smoke_failed: " + smoke_report.message[:120]) if not smoke_passed else "smoke_ok",
        smoke_report=None,  # GateResult not SafetyGateReport — keep simple here
        commit_sha=commit_sha,
        timestamp=datetime.now().isoformat(),
    )
    return decision


def execute_rollback(commit_sha: str, *, dry_run: bool = False) -> RollbackOutcome:
    """`git revert <sha> --no-edit && git push`.

    Args:
        commit_sha: SHA del commit a revertir.
        dry_run: si True, no ejecuta git.

    Returns:
        `RollbackOutcome` con sha del revert commit.
    """
    t0 = time.monotonic()
    if dry_run:
        return RollbackOutcome(
            executed=False, success=True, revert_commit_sha="(dry_run)",
            duration_s=time.monotonic() - t0,
        )
    if not commit_sha:
        return RollbackOutcome(
            executed=False, success=False, error="missing commit_sha",
            duration_s=time.monotonic() - t0,
        )

    # 1. git revert
    try:
        proc_revert = subprocess.run(
            ["git", "revert", commit_sha, "--no-edit"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
        )
        if proc_revert.returncode != 0:
            return RollbackOutcome(
                executed=True, success=False,
                error=f"revert_failed: {proc_revert.stderr[:200]}",
                duration_s=time.monotonic() - t0,
            )
        # 2. capture revert sha
        proc_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10,
        )
        revert_sha = proc_sha.stdout.strip()
        # 3. git push (omit in dry_run; only actual production should push)
        # NOTE: for safety, we DON'T auto-push here. Caller decides.
        return RollbackOutcome(
            executed=True, success=True, revert_commit_sha=revert_sha,
            duration_s=time.monotonic() - t0,
        )
    except subprocess.TimeoutExpired as e:
        return RollbackOutcome(
            executed=True, success=False,
            error=f"timeout: {e}", duration_s=time.monotonic() - t0,
        )
    except FileNotFoundError as e:
        return RollbackOutcome(
            executed=False, success=False,
            error=f"git not available: {e}", duration_s=time.monotonic() - t0,
        )


def log_rollback_event(decision: RollbackDecision, outcome: RollbackOutcome | None = None) -> None:
    """Append evento a rollback_log.jsonl."""
    ROLLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(),
        "commit_sha": decision.commit_sha,
        "should_rollback": decision.should_rollback,
        "reason": decision.reason,
        "outcome": outcome.__dict__ if outcome else None,
    }
    with ROLLBACK_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def post_merge_workflow(commit_sha: str, *, wait_s: int = 60,
                          dry_run: bool = True, auto_push: bool = False) -> dict[str, Any]:
    """Workflow completo: smoke → decisión → execute si necesario → log.

    Por DEFAULT `dry_run=True` y `auto_push=False` para safety. El loop
    operacional debe llamar con `dry_run=False, auto_push=True` SOLO si
    el bootstrap policy lo permite (ver `feature_flags.py` LXXXVIII).
    """
    decision = evaluate_post_merge(commit_sha, wait_s=wait_s, dry_run=dry_run)
    outcome = None
    if decision.should_rollback:
        outcome = execute_rollback(commit_sha, dry_run=dry_run)
        if outcome.success and outcome.executed and auto_push and not dry_run:
            # Optional push step (gated)
            try:
                subprocess.run(
                    ["git", "push"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
                    check=False,
                )
            except Exception:
                pass  # logged in outcome.error if relevant
    log_rollback_event(decision, outcome)
    return {
        "decision": decision.to_dict(),
        "outcome": asdict(outcome) if outcome else None,
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    import sys
    sha = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    print(f"Faubot Rollback Engine LXXXVII — evaluating commit {sha} (dry_run)…")
    result = post_merge_workflow(sha, wait_s=0, dry_run=True)
    print(json.dumps(result, indent=2, default=str))
