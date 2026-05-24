"""Sprint 7 — Audit Analytics + OIDC + Observability + MLOps tests (FAUBOT CXLV)."""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# Sprint 7.A — Audit Analytics Dashboard
# ─────────────────────────────────────────────────────────────────────


def test_s7_a_module_importable():
    from prostanet.presentation import audit_analytics_routes
    assert hasattr(audit_analytics_routes, "audit_analytics_bp")
    assert hasattr(audit_analytics_routes, "_cohort_breakdown")
    assert hasattr(audit_analytics_routes, "_blocked_hard_pending")
    assert hasattr(audit_analytics_routes, "_override_stats")
    assert hasattr(audit_analytics_routes, "_endpoint_usage")
    assert hasattr(audit_analytics_routes, "_godibot_trends")


def test_s7_a_cohort_breakdown_returns_shape():
    from prostanet.presentation.audit_analytics_routes import (
        _cohort_breakdown, _get_conn,
    )
    conn = _get_conn()
    try:
        data = _cohort_breakdown(conn)
        assert "total_patients" in data
        assert "by_state" in data
        assert "by_ethnicity" in data
        assert "by_ecog" in data
        assert "by_hrr_documentation" in data
        assert isinstance(data["by_state"], list)
        assert data["total_patients"] >= 0
    finally:
        conn.close()


def test_s7_a_blocked_hard_pending_has_sla_buckets():
    from prostanet.presentation.audit_analytics_routes import (
        _blocked_hard_pending, _get_conn,
    )
    conn = _get_conn()
    try:
        data = _blocked_hard_pending(conn)
        assert "blocked_hard_count" in data
        assert "sla_buckets" in data
        sla = data["sla_buckets"]
        assert "green" in sla and "yellow" in sla and "red" in sla
    finally:
        conn.close()


def test_s7_a_godibot_trends_returns_12_weeks():
    from prostanet.presentation.audit_analytics_routes import (
        _godibot_trends, _get_conn, TRENDS_WINDOW_WEEKS,
    )
    conn = _get_conn()
    try:
        data = _godibot_trends(conn)
        assert "weekly_trend" in data
        assert len(data["weekly_trend"]) == TRENDS_WINDOW_WEEKS
        for w in data["weekly_trend"]:
            assert "week_start" in w
            assert "total" in w
            assert "internal_validation_pct" in w
    finally:
        conn.close()


def test_s7_a_template_exists_with_data_testids():
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "audit_analytics_dashboard.html"
    assert template.exists()
    content = template.read_text(encoding="utf-8")
    for testid in (
        "card-cohort-breakdown", "card-blocked-pending",
        "card-override-stats", "card-endpoint-usage", "card-godibot-trends",
    ):
        assert f'data-testid="{testid}"' in content


def test_s7_a_endpoints_have_admin_auth():
    """5 endpoints + dashboard view requieren @require_admin (IP institucional)."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "audit_analytics_routes.py"
    content = src.read_text(encoding="utf-8")
    for endpoint_def in (
        "def api_cohort_breakdown",
        "def api_blocked_hard_pending",
        "def api_override_stats",
        "def api_endpoint_usage",
        "def api_godibot_trends",
        "def view_dashboard",
    ):
        idx = content.find(endpoint_def)
        assert idx > 0, f"{endpoint_def} not found"
        prev = content[max(0, idx - 200):idx]
        assert "@require_admin" in prev, f"{endpoint_def} missing @require_admin"


# ─────────────────────────────────────────────────────────────────────
# Sprint 7.B — OIDC production wiring
# ─────────────────────────────────────────────────────────────────────


def test_s7_b_oidc_status_endpoint_defined():
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "auth_endpoints.py"
    content = src.read_text(encoding="utf-8")
    assert '"/oidc/status"' in content
    assert "def oidc_status" in content
    # No requires auth (es diagnostic)
    idx = content.find("def oidc_status")
    prev = content[max(0, idx - 300):idx]
    # Should NOT have @require_clinician or @require_admin (diagnostic public)


def test_s7_b_role_mapper_handles_keycloak_realm_access():
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    userinfo_keycloak = {
        "sub": "kc-abc-123",
        "realm_access": {"roles": ["clinician", "user"]},
    }
    role = backend._role_from_userinfo(userinfo_keycloak, default="viewer")
    assert role == "clinician"


def test_s7_b_role_mapper_handles_auth0_custom_namespace():
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    userinfo_auth0 = {
        "sub": "auth0|abc123",
        "https://prostanet/roles": ["admin"],
    }
    role = backend._role_from_userinfo(userinfo_auth0, default="clinician")
    assert role == "admin"


def test_s7_b_role_mapper_priority_admin_over_clinician():
    """Admin role debe ganar sobre clinician (mayor privilegio)."""
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    userinfo = {
        "sub": "x",
        "roles": ["clinician", "admin", "viewer"],
    }
    role = backend._role_from_userinfo(userinfo, default="viewer")
    assert role == "admin"


def test_s7_b_role_mapper_keycloak_resource_access():
    from prostanet.shared.auth_backends import OidcBackend
    backend = OidcBackend()
    userinfo = {
        "sub": "x",
        "resource_access": {
            "prostanet-app": {"roles": ["physician"]},
        },
    }
    role = backend._role_from_userinfo(userinfo, default="clinician")
    assert role == "physician"


def test_s7_b_oidc_docs_exist():
    from pathlib import Path
    docs = Path(__file__).parent.parent / "docs" / "OIDC_PRODUCTION_SETUP.md"
    assert docs.exists()
    content = docs.read_text(encoding="utf-8")
    assert "Auth0" in content
    assert "Keycloak" in content
    assert "PROSTANET_OIDC_ISSUER" in content
    assert "PROSTANET_OIDC_CLIENT_ID" in content


# ─────────────────────────────────────────────────────────────────────
# Sprint 7.C — Observability (rate limit + Prometheus)
# ─────────────────────────────────────────────────────────────────────


def test_s7_c_observability_module_importable():
    from prostanet.shared import observability
    assert hasattr(observability, "register_observability")
    assert hasattr(observability, "instrument_handler")
    assert hasattr(observability, "is_metrics_enabled")
    assert hasattr(observability, "is_rate_limit_enabled")


def test_s7_c_metric_helpers_noop_when_disabled():
    """Cuando Prometheus no está instalado o disabled, helpers son no-op."""
    from prostanet.shared.observability import (
        inc_api_request, observe_api_duration,
        inc_ml_inference, inc_audit_failure,
    )
    # Estos deben no levantar ni con valores arbitrarios
    inc_api_request("test_endpoint", "GET", "2xx")
    observe_api_duration("test_endpoint", "GET", 0.123)
    inc_ml_inference("treatment_response", "success")
    inc_audit_failure("ml_inference")


def test_s7_c_instrument_handler_decorator_works():
    from prostanet.shared.observability import instrument_handler

    @instrument_handler("test_handler")
    def my_func(x):
        return x * 2

    # Funciona fuera de Flask context (no se rompe sin request)
    result = my_func(5)
    assert result == 10


def test_s7_c_observability_docs_exist():
    from pathlib import Path
    docs = Path(__file__).parent.parent / "docs" / "OBSERVABILITY_SETUP.md"
    assert docs.exists()
    content = docs.read_text(encoding="utf-8")
    assert "prometheus_client" in content
    assert "flask-limiter" in content
    assert "PROSTANET_METRICS_ENABLED" in content


# ─────────────────────────────────────────────────────────────────────
# Sprint 7.D — MLOps retrain CLI
# ─────────────────────────────────────────────────────────────────────


def test_s7_d_retrain_cli_module_importable():
    from prostanet.ai.training import retrain_cli
    assert hasattr(retrain_cli, "run_retrain")
    assert hasattr(retrain_cli, "extract_training_records")
    assert hasattr(retrain_cli, "evaluate_quality_gate")
    assert hasattr(retrain_cli, "retrain_model")
    assert hasattr(retrain_cli, "main")


def test_s7_d_quality_gate_blocks_small_cohort():
    from prostanet.ai.training.retrain_cli import (
        evaluate_quality_gate, MIN_PATIENTS_FOR_RETRAIN,
    )
    # Cohorte chica → bloqueado
    summary_small = {"n_eligible": 50, "freshness_days": 30}
    passed, reasons = evaluate_quality_gate(summary_small)
    assert not passed
    assert any("insufficient_cohort" in r.lower() or "insufficient cohort" in r.lower()
               for r in reasons)


def test_s7_d_quality_gate_blocks_stale_data():
    from prostanet.ai.training.retrain_cli import evaluate_quality_gate
    # Cohorte vieja → bloqueado
    summary_stale = {"n_eligible": 500, "freshness_days": 400}
    passed, reasons = evaluate_quality_gate(summary_stale)
    assert not passed
    assert any("stale" in r.lower() for r in reasons)


def test_s7_d_quality_gate_passes_valid():
    from prostanet.ai.training.retrain_cli import evaluate_quality_gate
    summary_ok = {"n_eligible": 200, "freshness_days": 30}
    passed, reasons = evaluate_quality_gate(summary_ok)
    assert passed
    assert reasons == []


def test_s7_d_retrain_dry_run_returns_structure():
    """Smoke test del retrain dry-run end-to-end (no escribe artifact)."""
    from prostanet.ai.training.retrain_cli import run_retrain
    result = run_retrain(model="state_transition", apply=False)
    assert "model" in result
    assert "status" in result
    assert result["dry_run"] is True
    assert result["applied"] is False
    # Status válido según cohorte real
    assert result["status"] in (
        "dry_run_complete", "quality_gate_failed", "training_failed",
        "deploy_blocked_thresholds",
    )


def test_s7_d_thresholds_constants_defined():
    from prostanet.ai.training.retrain_cli import (
        AUC_DEPLOY_THRESHOLD, CALIBRATION_BRIER_MAX,
        MIN_PATIENTS_FOR_RETRAIN, MIN_OUTCOMES_FOR_RETRAIN,
    )
    # AUC threshold debe ser razonable (no <0.5 = random, no >0.95 = imposible)
    assert 0.5 <= AUC_DEPLOY_THRESHOLD <= 0.95
    # Brier max debe ser positivo y <0.5 (Brier perfecto = 0)
    assert 0 < CALIBRATION_BRIER_MAX < 0.5
    # Mínimos de cohorte razonables
    assert MIN_PATIENTS_FOR_RETRAIN >= 50
    assert MIN_OUTCOMES_FOR_RETRAIN >= 20
