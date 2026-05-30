from __future__ import annotations

from pathlib import Path


def test_read_model_cache_ttl_refresh_and_prefix_invalidation():
    from prostanet.shared.read_model_cache import (
        build_cache_key,
        get_or_build_read_model,
        invalidate_read_model_cache,
    )

    invalidate_read_model_cache()
    calls = {"count": 0}
    key = build_cache_key("patient_decision_today", "PX-1", scope="summary")

    def build():
        calls["count"] += 1
        return {"value": calls["count"]}

    assert get_or_build_read_model(key, build, ttl_seconds=60) == {"value": 1}
    assert get_or_build_read_model(key, build, ttl_seconds=60) == {"value": 1}
    assert calls["count"] == 1
    assert get_or_build_read_model(key, build, ttl_seconds=60, refresh=True) == {"value": 2}
    assert invalidate_read_model_cache("patient_decision_today") == 1
    assert get_or_build_read_model(key, build, ttl_seconds=60) == {"value": 3}


def test_patient_profile_drilldown_is_hidden_and_inert_when_closed():
    template = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    script = Path("static/js/clinical_intelligence_v2.js").read_text(encoding="utf-8")

    aside_line = next(line for line in template.splitlines() if 'id="pm2-drilldown"' in line)
    assert 'aria-hidden="true"' in aside_line
    assert "hidden" in aside_line
    assert "inert" in aside_line
    assert "aria-modal" not in aside_line
    assert "window.PM2.showDrillDown" in template
    assert 'panel.removeAttribute("inert")' in script
    assert 'panel.setAttribute("aria-modal", "true")' in script
    assert 'panel.removeAttribute("aria-modal")' in script
    assert 'panel.setAttribute("inert", "")' in script
    assert "panel.hidden = true" in script


def test_clinical_hub_drilldown_is_hidden_and_inert_when_closed():
    template = Path("templates/demos/stage_clinical_center_v2_redesign.html").read_text(encoding="utf-8")

    aside_line = next(line for line in template.splitlines() if 'id="pm2-drilldown"' in line)
    assert 'aria-hidden="true"' in aside_line
    assert "hidden" in aside_line
    assert "inert" in aside_line
    assert "aria-modal" not in aside_line
    assert "drilldown.removeAttribute('inert')" in template
    assert "drilldown.setAttribute('aria-modal', 'true')" in template
    assert "drilldown.removeAttribute('aria-modal')" in template
    assert "drilldown.setAttribute('inert', '')" in template
    assert "drilldown.hidden = true" in template


def test_patient_profile_decision_today_uses_autodrive_api_contract():
    source = Path("app.py").read_text(encoding="utf-8")

    assert "_canonical_decision_today" in source
    assert 'profile_view["decision_today_fusion_kernel"] = _canonical_decision_today' in source
    assert "_canonical_next_safe_action" in source
    assert 'profile_view["next_best_action"] = _canonical_next_safe_action' in source
    assert 'structured_decision_headline ("Priorizar ADT + enzalutamida")' not in source


def test_autodrive_decision_operability_explains_clinical_recommendation_without_queue():
    from prostanet.domains.patient_tracking.clinical_autodrive_command_center import (
        _build_decision_operability,
    )

    operability = _build_decision_operability(
        {
            "decision_state": "ready_to_decide",
            "decision_today": {"title": "Priorizar ADT + enzalutamida"},
        },
        [],
        {},
    )

    assert operability["clinical_recommendation_title"] == "Priorizar ADT + enzalutamida"
    assert operability["operational_queue_state"] == "clinical_recommendation_only"
    assert operability["queue_count"] == 0
    assert "solo encola tareas operativas" in operability["why_no_queue"]


def test_patient_profile_copy_distinguishes_recommendation_from_operational_queue():
    template = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")

    assert "Recomendación clínica activa; sin tarea operativa hoy porque" in template
    assert "_ad_clinical_title" in template
    assert "decision_operability" in template


def test_stt_health_summary_alias_is_fast_default_contract():
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp

    app = flask.Flask("stt_summary_contract")
    app.register_blueprint(epic21_bp)
    client = app.test_client()

    response = client.get("/api/stt/health?scope=summary")
    assert response.status_code == 200
    data = response.get_json()
    assert data["scope"] == "summary"
    assert data["status"] in {"ok", "degraded", "unavailable"}
    assert "missing_dependencies" in data
    assert "recommended_action" in data
    assert "stt_health" in data
    assert "summary" in data["stt_health"]


def test_autodrive_today_summary_endpoint_contract(app_client):
    client, _db_path = app_client

    response = client.get("/api/autodrive/today?scope=summary&limit=2")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["scope"] == "summary"
    assert data["autodrive"]["audit"]["summary_payload"] is True
    assert isinstance(data["today_queue"], list)
