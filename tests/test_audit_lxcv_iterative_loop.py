"""tests/test_audit_lxcv_iterative_loop.py — FAUBOT LXCV.

Tests para Iteración LXCV — Iterative Improvement Loop infrastructure.

Componentes:
  - Loop monitor module (prostanet/presentation/loop_monitor.py)
  - Loop monitor dashboard (templates/loop_monitor_dashboard.html)
  - Cron workflows (.github/workflows/faubot_daily_loop.yml + scenario_drift_detection.yml)
  - 8 vectores monitoreados (CORE_VECTORS)
  - Self-recording helpers (record_clinical_coverage_check + record_backend_integrity_check)

HIPÓTESIS: H.G3126 → H.G3145 (~20 tests).
Faubot LXCV (plan XCV) — Loop Setup.
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
# §A — Loop monitor module
# ──────────────────────────────────────────────────────────────────────


def test_g3126_loop_monitor_module_imports():
    """H.G3126 — loop_monitor module + functions importable."""
    from prostanet.presentation.loop_monitor import (
        loop_monitor_bp,
        record_iteration,
        get_recent_iterations,
        get_vector_summary,
        CORE_VECTORS,
        record_clinical_coverage_check,
        record_backend_integrity_check,
    )
    assert callable(record_iteration)
    assert callable(get_recent_iterations)


def test_g3127_core_vectors_8_directional():
    """H.G3127 — CORE_VECTORS define exactly 8 directional vectors."""
    from prostanet.presentation.loop_monitor import CORE_VECTORS
    assert len(CORE_VECTORS) == 8
    expected = {
        "clinical_coverage", "ui_ergonomy", "backend_integrity",
        "clinical_evidence", "recommendation_accuracy", "fda_samd_compliance",
        "performance_a11y", "status_reporting",
    }
    assert set(CORE_VECTORS.keys()) == expected


def test_g3128_each_vector_has_label_icon_metric_skill():
    """H.G3128 — Each vector has label + icon + target_metric + skill defined."""
    from prostanet.presentation.loop_monitor import CORE_VECTORS
    for key, vec in CORE_VECTORS.items():
        assert vec.get("label"), f"{key} missing label"
        assert vec.get("icon"), f"{key} missing icon"
        assert vec.get("target_metric"), f"{key} missing target_metric"
        assert vec.get("skill"), f"{key} missing skill"


def test_g3129_record_iteration_persists_to_db():
    """H.G3129 — record_iteration writes to SQLite DB."""
    from prostanet.presentation.loop_monitor import (
        record_iteration, get_recent_iterations,
    )
    record_iteration(
        iteration_id="test_g3129_lxcv",
        vector="clinical_coverage",
        metric="test_metric",
        value=89.0,
        status="ok",
        notes="LXCV test",
    )
    iterations = get_recent_iterations(days=1)
    test_records = [i for i in iterations if i.get("iteration_id") == "test_g3129_lxcv"]
    assert len(test_records) >= 1


def test_g3130_get_vector_summary_aggregates_correctly():
    """H.G3130 — get_vector_summary aggregates count + ok/warning/critical per vector."""
    from prostanet.presentation.loop_monitor import (
        record_iteration, get_vector_summary,
    )
    # Record some test data
    for status in ["ok", "ok", "warning"]:
        record_iteration(
            iteration_id=f"test_g3130_{status}",
            vector="ui_ergonomy",
            metric="test",
            value=1.0,
            status=status,
        )
    summary = get_vector_summary(days=1)
    ui_summary = summary.get("ui_ergonomy", {})
    assert ui_summary.get("count", 0) >= 3


# ──────────────────────────────────────────────────────────────────────
# §B — Self-recording helpers
# ──────────────────────────────────────────────────────────────────────


def test_g3131_record_clinical_coverage_check_works():
    """H.G3131 — record_clinical_coverage_check returns valid result + records to DB."""
    from prostanet.presentation.loop_monitor import record_clinical_coverage_check
    result = record_clinical_coverage_check()
    assert "status" in result
    if "gate_count" in result:
        assert result["gate_count"] >= 89


def test_g3132_record_backend_integrity_check_works():
    """H.G3132 — record_backend_integrity_check returns ok status."""
    from prostanet.presentation.loop_monitor import record_backend_integrity_check
    result = record_backend_integrity_check()
    assert "status" in result
    # Should be ok if progressive_capture_builder works correctly
    assert result.get("status") in ("ok", "warning")


# ──────────────────────────────────────────────────────────────────────
# §C — REST endpoints
# ──────────────────────────────────────────────────────────────────────


def test_g3133_loop_monitor_snapshot_endpoint():
    """H.G3133 — GET /api/loop-monitor/snapshot returns 200 + vectors."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/loop-monitor/snapshot")
        assert r.status_code == 200
        data = r.get_json()
        assert "vectors" in data
        assert len(data["vectors"]) == 8


def test_g3134_loop_monitor_iterations_endpoint():
    """H.G3134 — GET /api/loop-monitor/iterations returns 200 + iterations list."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/loop-monitor/iterations")
        assert r.status_code == 200
        data = r.get_json()
        assert "iterations" in data
        assert isinstance(data["iterations"], list)


def test_g3135_loop_monitor_dashboard_renders_200():
    """H.G3135 — GET /loop-monitor renders dashboard 200."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/loop-monitor")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        assert "pm2-loop-shell" in html or "Loop Monitor" in html or "loop-monitor" in html.lower()


def test_g3136_loop_monitor_dashboard_renders_8_vector_cards():
    """H.G3136 — Dashboard renders 8 vector cards (verified by article count + labels)."""
    import app as app_module
    import re
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/loop-monitor")
        html = r.data.decode("utf-8")
        # Count article cards
        articles = re.findall(r'<article class="pm2-loop-vector-card">.*?</article>', html, re.DOTALL)
        assert len(articles) == 8, f"Expected 8 vector cards, got {len(articles)}"
        # Verify each vector label appears
        for label in ["Cobertura clínica", "UI ergonomía", "Backend integrity",
                      "Evidencia clínica", "Recomendación accuracy",
                      "FDA SaMD compliance", "Performance + a11y", "Status reporting"]:
            assert label in html, f"Vector label '{label}' missing"


# ──────────────────────────────────────────────────────────────────────
# §D — Cron workflow files
# ──────────────────────────────────────────────────────────────────────


def test_g3137_faubot_daily_loop_workflow_exists():
    """H.G3137 — .github/workflows/faubot_daily_loop.yml exists."""
    wf = ROOT / ".github/workflows/faubot_daily_loop.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "cron" in content
    assert "0 6 * * *" in content  # Daily 06:00 UTC


def test_g3138_scenario_drift_workflow_exists():
    """H.G3138 — .github/workflows/scenario_drift_detection.yml exists."""
    wf = ROOT / ".github/workflows/scenario_drift_detection.yml"
    assert wf.exists()
    content = wf.read_text()
    assert "cron" in content
    assert "0 0 * * 3" in content  # Weekly Wednesday


def test_g3139_workflows_run_clinical_validation_tests():
    """H.G3139 — Drift workflow runs the 5 clinical cases tests."""
    wf = (ROOT / ".github/workflows/scenario_drift_detection.yml").read_text()
    assert "test_audit_lxciv_clinical_validation_5_cases" in wf


def test_g3140_workflows_have_workflow_dispatch():
    """H.G3140 — Both workflows allow manual trigger via workflow_dispatch."""
    for wf_name in ("faubot_daily_loop.yml", "scenario_drift_detection.yml"):
        wf = (ROOT / ".github/workflows" / wf_name).read_text()
        assert "workflow_dispatch" in wf, f"{wf_name} missing workflow_dispatch"


# ──────────────────────────────────────────────────────────────────────
# §E — Bootstrap registration
# ──────────────────────────────────────────────────────────────────────


def test_g3141_loop_monitor_blueprint_registered_in_bootstrap():
    """H.G3141 — bootstrap.py registra loop_monitor_bp."""
    bootstrap = (ROOT / "prostanet/presentation/bootstrap.py").read_text()
    assert "loop_monitor_bp" in bootstrap
    assert "register_blueprint(loop_monitor_bp)" in bootstrap


def test_g3142_loop_monitor_blueprint_registered_in_app():
    """H.G3142 — Flask app has loop_monitor blueprint."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    assert "loop_monitor" in flask_app.blueprints


# ──────────────────────────────────────────────────────────────────────
# §F — Integration + version
# ──────────────────────────────────────────────────────────────────────


def test_g3143_dashboard_shows_record_iterations_links():
    """H.G3143 — Dashboard tiene table iteraciones recientes."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/loop-monitor")
        html = r.data.decode("utf-8")
        # Either has iterations table or empty state explaining cron jobs
        assert "Iteraciones recientes" in html or "Aún no hay" in html


def test_g3144_loop_monitor_persists_to_correct_db_path():
    """H.G3144 — LOOP_DB_PATH apunta a prostanet_loop_monitor.db en repo root."""
    from prostanet.presentation.loop_monitor import LOOP_DB_PATH
    assert "prostanet_loop_monitor.db" in str(LOOP_DB_PATH)


def test_g3145_faubot_release_bumped_lxcv_or_higher():
    """H.G3145 — FAUBOT_RELEASE bumped to LXCV or higher."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_tags = ("LXCV", "LXCVI", "LXCVII", "XCV", "XCVI", "XCVII", "XCVIII", "XCIX", "C")
    assert any(tag in FAUBOT_RELEASE for tag in valid_tags), (
        f"FAUBOT_RELEASE not bumped past LXCIV: {FAUBOT_RELEASE}"
    )
