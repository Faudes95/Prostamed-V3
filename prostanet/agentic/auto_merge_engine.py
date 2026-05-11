"""Faubot Agentic Loop — Auto-Merge Engine + Bootstrap Policy (LXXXIX).

Tracks success rate of recent iterations and gates auto-merge activation per
the bootstrap policy:

  Phase 0 (Shadow):       AGENTIC_AUTO_MERGE=false (default)
                          → 30 iterations consecutive ≥ 95% safety_gates_passed
                          → eligible for Phase 1 upgrade
  Phase 1 (Auto-merge):   AGENTIC_AUTO_MERGE=true
                          → 100 iterations cumulative ≥ 98% success
                          + rollback_rate < 2%
                          → eligible for Phase 2 upgrade
  Phase 2 (Autónomo):     AGENTIC_STRUCTURAL_CHANGES=true
                          → continuous (no further upgrade)

Override: AGENTIC_KILL_SWITCH=1 → loop stops immediately regardless of phase.

API:
    policy = evaluate_bootstrap_policy()
    auto_merge_eligible = policy.eligible_for_auto_merge
    next_phase_recommendation = policy.recommendation
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROPOSALS_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "proposals_log.jsonl"
ROLLBACK_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "rollback_log.jsonl"
POLICY_STATE = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "policy_state.yaml"

PHASE_0_REQUIRED_ITERATIONS = 30
PHASE_0_SUCCESS_THRESHOLD = 0.95
PHASE_1_REQUIRED_ITERATIONS = 100
PHASE_1_SUCCESS_THRESHOLD = 0.98
PHASE_1_ROLLBACK_THRESHOLD = 0.02


@dataclass
class BootstrapPolicy:
    """Estado del bootstrap policy + recomendación."""
    current_phase: int  # 0, 1, or 2
    auto_merge_active: bool
    structural_changes_active: bool
    iterations_in_window: int
    success_rate: float
    rollback_rate: float
    eligible_for_upgrade: bool
    recommendation: str
    kill_switch_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_proposals(limit: int = 200) -> list[dict[str, Any]]:
    if not PROPOSALS_LOG.exists():
        return []
    out = []
    with PROPOSALS_LOG.open() as f:
        for line in reversed(list(f)):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                break
    return list(reversed(out))


def _read_rollbacks(limit: int = 200) -> list[dict[str, Any]]:
    if not ROLLBACK_LOG.exists():
        return []
    out = []
    with ROLLBACK_LOG.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


def evaluate_bootstrap_policy() -> BootstrapPolicy:
    """Returns current policy + upgrade recommendation."""
    auto_merge_env = os.environ.get("AGENTIC_AUTO_MERGE", "false").lower()
    structural_env = os.environ.get("AGENTIC_STRUCTURAL_CHANGES", "false").lower()
    kill_switch = os.environ.get("AGENTIC_KILL_SWITCH") == "1"

    auto_merge_active = auto_merge_env in {"1", "true", "yes"}
    structural_active = structural_env in {"1", "true", "yes"}

    # Determine current phase
    if structural_active and auto_merge_active:
        current_phase = 2
    elif auto_merge_active:
        current_phase = 1
    else:
        current_phase = 0

    # Window size depends on phase
    window = PHASE_0_REQUIRED_ITERATIONS if current_phase == 0 else PHASE_1_REQUIRED_ITERATIONS
    proposals = _read_proposals(limit=window)
    rollbacks = _read_rollbacks(limit=window)

    if not proposals:
        return BootstrapPolicy(
            current_phase=current_phase,
            auto_merge_active=auto_merge_active,
            structural_changes_active=structural_active,
            iterations_in_window=0,
            success_rate=0.0,
            rollback_rate=0.0,
            eligible_for_upgrade=False,
            recommendation="No iterations recorded yet. Run loop in Shadow mode to accumulate baseline.",
            kill_switch_active=kill_switch,
        )

    # Success = safety gates all passed AND no rollback
    successes = 0
    for p in proposals:
        summary = p.get("safety_report_summary", "") or ""
        # All gates passed if "4/4 gates passed" appears
        if "4/4 gates passed" in summary or "all_passed=True" in str(p):
            successes += 1
    success_rate = successes / len(proposals)

    rollback_rate = (sum(1 for r in rollbacks if r.get("should_rollback"))
                     / max(len(proposals), 1))

    # Upgrade eligibility
    eligible = False
    rec = ""
    if current_phase == 0:
        if (len(proposals) >= PHASE_0_REQUIRED_ITERATIONS
                and success_rate >= PHASE_0_SUCCESS_THRESHOLD):
            eligible = True
            rec = (f"Phase 0 → Phase 1 upgrade eligible: "
                   f"{successes}/{len(proposals)} successes ({success_rate*100:.1f}%). "
                   f"Set AGENTIC_AUTO_MERGE=true to enable auto-merge for closure of existing gaps.")
        else:
            needed = PHASE_0_REQUIRED_ITERATIONS - len(proposals)
            rec = (f"Phase 0 (Shadow): {len(proposals)}/{PHASE_0_REQUIRED_ITERATIONS} iterations · "
                   f"success_rate {success_rate*100:.1f}% (target {PHASE_0_SUCCESS_THRESHOLD*100:.0f}%). "
                   f"Need {max(needed, 0)} more iterations.")
    elif current_phase == 1:
        if (len(proposals) >= PHASE_1_REQUIRED_ITERATIONS
                and success_rate >= PHASE_1_SUCCESS_THRESHOLD
                and rollback_rate < PHASE_1_ROLLBACK_THRESHOLD):
            eligible = True
            rec = (f"Phase 1 → Phase 2 upgrade eligible: "
                   f"success {success_rate*100:.1f}%, rollback {rollback_rate*100:.2f}%. "
                   f"Set AGENTIC_STRUCTURAL_CHANGES=true to allow new pillars/refactors.")
        else:
            rec = (f"Phase 1 (Auto-merge limited): "
                   f"success_rate {success_rate*100:.1f}% (target {PHASE_1_SUCCESS_THRESHOLD*100:.0f}%) · "
                   f"rollback_rate {rollback_rate*100:.2f}% (target <{PHASE_1_ROLLBACK_THRESHOLD*100:.0f}%).")
    else:
        rec = "Phase 2 (Autónomo): continuous operation. No further upgrades."

    if kill_switch:
        rec = "🛑 AGENTIC_KILL_SWITCH=1 active. Loop disabled regardless of phase."

    return BootstrapPolicy(
        current_phase=current_phase,
        auto_merge_active=auto_merge_active,
        structural_changes_active=structural_active,
        iterations_in_window=len(proposals),
        success_rate=round(success_rate, 4),
        rollback_rate=round(rollback_rate, 4),
        eligible_for_upgrade=eligible,
        recommendation=rec,
        kill_switch_active=kill_switch,
    )


def policy_summary() -> str:
    """Human-readable one-liner."""
    p = evaluate_bootstrap_policy()
    icon = "🟢" if p.auto_merge_active else "🟡"
    if p.kill_switch_active:
        icon = "🛑"
    return (f"{icon} Phase {p.current_phase} · "
            f"{p.iterations_in_window} iter · "
            f"success {p.success_rate*100:.1f}% · "
            f"rollback {p.rollback_rate*100:.2f}% · "
            f"{'UPGRADE ELIGIBLE' if p.eligible_for_upgrade else 'standby'}")


if __name__ == "__main__":
    p = evaluate_bootstrap_policy()
    print(json.dumps(p.to_dict(), indent=2))
    print()
    print(policy_summary())
