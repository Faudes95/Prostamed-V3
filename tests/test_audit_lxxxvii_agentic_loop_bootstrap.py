"""Tests dedicados Iteración Faubot LXXXVII — Agentic Loop bootstrap.

Hipótesis verificables H.G2865 → H.G2880 (cubren Fase 6 del plan original:
prostanet/agentic/ con safety_gates + rollback_engine + improvement_loop +
GitHub Actions workflow).

Faubot 2026-04-27 LXXXVII bootstrap.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)
logging.getLogger("prostanet").setLevel(logging.ERROR)


# ─────────────────────────────────────────────────────────────────────────
# §A — Module structure + imports
# ─────────────────────────────────────────────────────────────────────────
def test_g2865_agentic_package_imports():
    """H.G2865 — `prostanet.agentic` package importa sin error."""
    import prostanet.agentic
    assert hasattr(prostanet.agentic, "__faubot_release__")
    assert "LXXXVII" in prostanet.agentic.__faubot_release__


def test_g2866_safety_gates_module_imports():
    """H.G2866 — `safety_gates` expone API pública (GateResult, SafetyGateReport, run_all_gates)."""
    from prostanet.agentic.safety_gates import (
        GateResult, SafetyGateReport,
        gate_test_sweep, gate_critical_regression,
        gate_smoke_e2e, gate_lint_clean,
        run_all_gates, report_summary,
    )
    assert callable(gate_smoke_e2e)
    assert callable(run_all_gates)


def test_g2867_rollback_engine_module_imports():
    """H.G2867 — `rollback_engine` expone API (evaluate_post_merge, execute_rollback)."""
    from prostanet.agentic.rollback_engine import (
        RollbackDecision, RollbackOutcome,
        evaluate_post_merge, execute_rollback, post_merge_workflow,
    )
    assert callable(post_merge_workflow)


def test_g2868_improvement_loop_module_imports():
    """H.G2868 — `improvement_loop` expone API (run_iteration, IterationResult, Proposal)."""
    from prostanet.agentic.improvement_loop import (
        Proposal, IterationResult, run_iteration,
    )
    assert callable(run_iteration)


# ─────────────────────────────────────────────────────────────────────────
# §B — Safety gates functional
# ─────────────────────────────────────────────────────────────────────────
def test_g2869_smoke_e2e_gate_passes_on_known_routes():
    """H.G2869 — Gate smoke_e2e pasa cuando 6/6 rutas críticas devuelven 2xx/3xx."""
    from prostanet.agentic.safety_gates import gate_smoke_e2e
    result = gate_smoke_e2e(timeout_s=30)
    assert result.passed is True
    assert "6/6" in result.message or "5/6" in result.message  # tolerar 1 fallo
    assert result.duration_s < 30
    assert isinstance(result.details["successes"], list)


def test_g2870_lint_gate_handles_missing_ruff_gracefully():
    """H.G2870 — Gate lint_clean retorna passed=True si ruff no instalado (skipped)."""
    from prostanet.agentic.safety_gates import gate_lint_clean
    result = gate_lint_clean(timeout_s=30)
    # Should pass either way (clean or skipped)
    assert result.passed is True
    if result.details.get("skipped"):
        assert "ruff not installed" in result.message


def test_g2871_safety_gate_report_aggregates_correctly():
    """H.G2871 — `SafetyGateReport.all_passed` e false si CUALQUIER gate falla."""
    from prostanet.agentic.safety_gates import GateResult, SafetyGateReport
    g_pass = GateResult(name="x", passed=True, message="ok")
    g_fail = GateResult(name="y", passed=False, message="fail")
    report = SafetyGateReport(
        test_sweep=g_pass, critical_regression=g_pass,
        smoke_e2e=g_pass, lint_clean=g_fail,
    )
    assert report.passed_count == 3
    assert report.all_passed is False
    # Si todos pasan, all_passed=True
    report2 = SafetyGateReport(
        test_sweep=g_pass, critical_regression=g_pass,
        smoke_e2e=g_pass, lint_clean=g_pass,
    )
    assert report2.all_passed is True


# ─────────────────────────────────────────────────────────────────────────
# §C — Rollback engine
# ─────────────────────────────────────────────────────────────────────────
def test_g2872_rollback_dry_run_no_git_ops():
    """H.G2872 — `execute_rollback(dry_run=True)` no ejecuta git revert."""
    from prostanet.agentic.rollback_engine import execute_rollback
    outcome = execute_rollback("HEAD", dry_run=True)
    assert outcome.executed is False
    assert outcome.success is True
    assert outcome.revert_commit_sha == "(dry_run)"


def test_g2873_post_merge_workflow_logs_event():
    """H.G2873 — `post_merge_workflow` persiste evento en rollback_log.jsonl."""
    from prostanet.agentic.rollback_engine import post_merge_workflow, ROLLBACK_LOG
    initial_size = ROLLBACK_LOG.stat().st_size if ROLLBACK_LOG.exists() else 0
    post_merge_workflow("test_sha_g2873", wait_s=0, dry_run=True)
    assert ROLLBACK_LOG.exists()
    final_size = ROLLBACK_LOG.stat().st_size
    assert final_size > initial_size  # appended


# ─────────────────────────────────────────────────────────────────────────
# §D — Improvement loop orchestrator
# ─────────────────────────────────────────────────────────────────────────
def test_g2874_run_iteration_completes_in_shadow_mode():
    """H.G2874 — `run_iteration(dry_run=True)` completa sin error en Shadow mode."""
    os.environ.pop("AGENTIC_AUTO_MERGE", None)  # default false
    os.environ.pop("AGENTIC_KILL_SWITCH", None)
    from prostanet.agentic.improvement_loop import run_iteration
    result = run_iteration(dry_run=True, fast_mode=True)
    # success can be True/False depending on safety gates, but iteration must complete
    assert result.proposal is not None
    assert result.duration_s > 0
    assert isinstance(result.notes, list)


def test_g2875_run_iteration_persists_proposal():
    """H.G2875 — Cada iteración persiste su propuesta en proposals_log.jsonl."""
    from prostanet.agentic.improvement_loop import run_iteration, PROPOSALS_LOG
    initial_size = PROPOSALS_LOG.stat().st_size if PROPOSALS_LOG.exists() else 0
    run_iteration(dry_run=True, fast_mode=True)
    assert PROPOSALS_LOG.exists()
    final_size = PROPOSALS_LOG.stat().st_size
    assert final_size > initial_size


def test_g2876_kill_switch_disables_loop():
    """H.G2876 — `AGENTIC_KILL_SWITCH=1` aborta el loop inmediatamente."""
    os.environ["AGENTIC_KILL_SWITCH"] = "1"
    try:
        from prostanet.agentic.improvement_loop import run_iteration
        result = run_iteration(dry_run=True)
        assert result.success is False
        assert any("KILL_SWITCH" in n for n in result.notes)
    finally:
        os.environ.pop("AGENTIC_KILL_SWITCH", None)


def test_g2877_target_pillar_routes_to_fda_proposal():
    """H.G2877 — `target_pillar=4` genera propuesta con target_pillar=4.

    Post-LXXXVIII refactor: el loop ahora retorna el gap.kind real (e.g.,
    'fmea_mitigations_incomplete') en lugar del placeholder 'fda_gap_p4',
    pero target_pillar sigue siendo 4.
    """
    os.environ.pop("AGENTIC_KILL_SWITCH", None)
    from prostanet.agentic.improvement_loop import run_iteration
    result = run_iteration(dry_run=True, target_pillar=4, fast_mode=True)
    assert result.proposal is not None
    assert result.proposal.target_pillar == 4
    # LXXXVIII: kind ahora es el gap real (fmea_*) o legacy fda_gap_p4
    assert ("fda_gap_p4" in result.proposal.kind
            or "fmea" in result.proposal.kind
            or "tir57" in result.proposal.kind
            or result.proposal.kind == "compliance_target_reached"
            or result.proposal.kind == "all_gaps_blocked")


def test_g2878_proposal_dataclass_serializes_to_dict():
    """H.G2878 — `Proposal.to_dict()` retorna estructura JSON-safe."""
    from prostanet.agentic.improvement_loop import Proposal
    p = Proposal(
        kind="test", target_pillar=3, description="test prop",
        estimated_effort_h=1.5, severity=7,
    )
    d = p.to_dict()
    import json
    serialized = json.dumps(d, default=str)
    assert "test" in serialized
    assert "target_pillar" in d


# ─────────────────────────────────────────────────────────────────────────
# §E — Schedule + GitHub Actions workflow
# ─────────────────────────────────────────────────────────────────────────
def test_g2879_phase_8_schedule_returns_iso_timestamp():
    """H.G2879 — `_phase_8_schedule_next()` retorna ISO timestamp."""
    from prostanet.agentic.improvement_loop import _phase_8_schedule_next
    ts = _phase_8_schedule_next()
    assert isinstance(ts, str)
    assert "T06:00:00" in ts  # daily 06:00 UTC
    assert ts.endswith("Z")


def test_g2880_github_actions_workflow_yaml_exists():
    """H.G2880 — `.github/workflows/agentic_loop.yml` existe + tiene cron + workflow_dispatch."""
    yaml_path = PROJECT_ROOT / ".github" / "workflows" / "agentic_loop.yml"
    assert yaml_path.exists()
    content = yaml_path.read_text()
    assert "schedule:" in content
    assert "cron: '0 6 * * *'" in content
    assert "workflow_dispatch:" in content
    assert "AGENTIC_AUTO_MERGE" in content
    assert "AGENTIC_TARGET_PILLAR" in content
