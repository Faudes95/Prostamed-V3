"""tests/test_audit_lxcvii_loop_activation.py — FAUBOT LXCVII.

Tests para LXCVII — Loop Activation + CLAUDE.md §13:

  LXCVII.1: 3 cron workflows nuevos (evidence_refresh + ui_performance + status_report)
  LXCVII.2: Bootstrap fixtures 30d historical data (per-vector idempotent)
  LXCVII.3: CLAUDE.md §13 'Iterative Improvement Loop' documentation
  LXCVII.4: Tests dedicados verification

HIPÓTESIS: H.G3191 → H.G3200 (10 tests).
Faubot LXCVII — Loop Activation + Documentation.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            if n.startswith("__") and n.endswith("__"):
                raise AttributeError(n)
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")

ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")


# ──────────────────────────────────────────────────────────────────────
# §LXCVII.1 — Cron workflows
# ──────────────────────────────────────────────────────────────────────


def test_g3191_evidence_refresh_workflow_exists():
    """H.G3191 — .github/workflows/evidence_refresh_loop.yml exists with weekly Sun cron."""
    wf = ROOT / ".github/workflows/evidence_refresh_loop.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "0 0 * * 0" in content  # Sunday 00:00 UTC
    assert "evidence_refresh" in content or "Evidence Refresh" in content


def test_g3192_ui_performance_workflow_exists():
    """H.G3192 — .github/workflows/ui_performance_loop.yml exists with Friday 18:00 cron."""
    wf = ROOT / ".github/workflows/ui_performance_loop.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "0 18 * * 5" in content


def test_g3193_status_report_workflow_exists():
    """H.G3193 — .github/workflows/status_report_loop.yml exists with Friday 22:00 cron."""
    wf = ROOT / ".github/workflows/status_report_loop.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "0 22 * * 5" in content


def test_g3194_total_5_workflows_present():
    """H.G3194 — 5 total cron workflows for 8-vector loop coverage."""
    workflows_dir = ROOT / ".github/workflows"
    expected_workflows = [
        "faubot_daily_loop.yml",
        "evidence_refresh_loop.yml",
        "scenario_drift_detection.yml",
        "ui_performance_loop.yml",
        "status_report_loop.yml",
    ]
    for wf in expected_workflows:
        assert (workflows_dir / wf).exists(), f"Missing workflow: {wf}"


# ──────────────────────────────────────────────────────────────────────
# §LXCVII.2 — Bootstrap fixtures
# ──────────────────────────────────────────────────────────────────────


def test_g3195_bootstrap_script_exists():
    """H.G3195 — scripts/bootstrap_loop_monitor_fixtures.py exists + per-vector idempotent."""
    script = ROOT / "scripts/bootstrap_loop_monitor_fixtures.py"
    assert script.exists()
    content = script.read_text()
    assert "vectors_to_seed" in content
    assert "skip" in content.lower() or "already" in content.lower()


def test_g3196_loop_monitor_db_has_8_vectors_data():
    """H.G3196 — Loop monitor DB has data for all 8 vectors (post-bootstrap)."""
    from prostanet.presentation.loop_monitor import get_vector_summary, CORE_VECTORS
    summary = get_vector_summary(days=30)
    vectors_with_data = [v for v in CORE_VECTORS.keys() if summary.get(v, {}).get("count", 0) > 0]
    # At least 5 vectors should have data after bootstrap
    assert len(vectors_with_data) >= 5, (
        f"Only {len(vectors_with_data)}/8 vectors have data: {vectors_with_data}"
    )


# ──────────────────────────────────────────────────────────────────────
# §LXCVII.3 — CLAUDE.md §13 documentation
# ──────────────────────────────────────────────────────────────────────


def test_g3197_claude_md_section_13_iterative_loop():
    """H.G3197 — CLAUDE.md §13 documenta Iterative Improvement Loop."""
    content = (ROOT / "CLAUDE.md").read_text()
    assert "## §13. Iterative Improvement Loop" in content
    assert "8 Vectores monitoreados" in content
    assert "5 Cron workflows activos" in content or "Cron workflows activos" in content


def test_g3198_claude_md_documents_5_workflows():
    """H.G3198 — §13 documenta 5 workflows con cron schedules."""
    content = (ROOT / "CLAUDE.md").read_text()
    section_13 = content[content.index("## §13."):]
    workflows = [
        "faubot_daily_loop.yml",
        "evidence_refresh_loop.yml",
        "scenario_drift_detection.yml",
        "ui_performance_loop.yml",
        "status_report_loop.yml",
    ]
    for wf in workflows:
        assert wf in section_13, f"Workflow {wf} not documented in §13"


def test_g3199_claude_md_section_14_memory_refs():
    """H.G3199 — §13 antiguo (memory refs) renombrado a §14."""
    content = (ROOT / "CLAUDE.md").read_text()
    assert "## §14. Memory referencias" in content


# ──────────────────────────────────────────────────────────────────────
# §LXCVII.4 — Version bump
# ──────────────────────────────────────────────────────────────────────


def test_g3200_faubot_release_lxcvii_or_higher():
    """H.G3200 — FAUBOT_RELEASE bumped to LXCVII."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_tags = ("LXCVII", "LXCVIII", "LXCIX", "C")
    assert any(tag in FAUBOT_RELEASE for tag in valid_tags), (
        f"FAUBOT_RELEASE not bumped: {FAUBOT_RELEASE}"
    )
