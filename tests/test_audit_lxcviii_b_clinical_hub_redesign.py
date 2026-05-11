"""tests/test_audit_lxcviii_b_clinical_hub_redesign.py — FAUBOT LXCVIII.B.

Tests para LXCVIII.B — Clinical Hub UI Redesign Bento Grid:

  B.1 Template stage_clinical_center_v2_redesign.html con bento grid + métricas en icono lateral sin rail lateral de loops
  B.2 Data wiring: stage_center_to_v2() returns kpi_hero + loop_vectors_live + cohort_filter_options
  B.3 JS interactividad: drill-down trigger + cohort filter dropdown
  B.4 A11y: skip-to-content + focus-visible + ARIA labels
  B.5 Routing: /clinical-hub default → redesign; ?v=v2_legacy retired → official; ?v=legacy → v1

HIPÓTESIS: H.G3216 → H.G3235 (~20 tests).
Faubot LXCVIII.B — Clinical Hub UI Redesign.
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
# §B.2 — Data wiring: stage_center_to_v2 enhanced
# ──────────────────────────────────────────────────────────────────────


def test_g3216_stage_center_returns_kpi_hero():
    """H.G3216 — stage_center_to_v2 retorna kpi_hero con 4 metrics."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    assert "kpi_hero" in data
    assert len(data["kpi_hero"]) == 4
    keys = {kpi["key"] for kpi in data["kpi_hero"]}
    assert keys == {"gates", "trials", "vectors", "modules"}


def test_g3217_stage_center_kpi_hero_values_realistic():
    """H.G3217 — KPI hero values: gates ≥89, trials ≥36, vectors=8, modules ≥10."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    kpi_dict = {kpi["key"]: int(kpi["value"]) for kpi in data["kpi_hero"]}
    assert kpi_dict["gates"] >= 89
    assert kpi_dict["trials"] >= 36
    assert kpi_dict["vectors"] == 8
    assert kpi_dict["modules"] >= 10


def test_g3218_stage_center_returns_loop_vectors_live():
    """H.G3218 — stage_center_to_v2 retorna loop_vectors_live con 8 vectores."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    assert "loop_vectors_live" in data
    assert len(data["loop_vectors_live"]) == 8
    expected_vectors = {"clinical_coverage", "ui_ergonomy", "backend_integrity",
                        "clinical_evidence", "recommendation_accuracy",
                        "fda_samd_compliance", "performance_a11y", "status_reporting"}
    actual_keys = {v["key"] for v in data["loop_vectors_live"]}
    assert actual_keys == expected_vectors


def test_g3219_loop_vectors_have_status_score():
    """H.G3219 — Cada loop vector tiene status (ok/warning/critical/no_data) + score 0-5."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    for vec in data["loop_vectors_live"]:
        assert vec["status"] in ("ok", "warning", "critical", "no_data")
        assert 0 <= vec["score"] <= 5


def test_g3220_stage_center_returns_cohort_filter_options():
    """H.G3220 — stage_center_to_v2 retorna cohort_filter_options con 4+ opciones."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    assert "cohort_filter_options" in data
    assert len(data["cohort_filter_options"]) >= 4
    values = {opt["value"] for opt in data["cohort_filter_options"]}
    assert "" in values  # Default "Todos los pacientes"
    assert "3m" in values
    assert "6m" in values


def test_g3236_stage_center_returns_official_quick_classifier_config():
    """H.G3236 — stage_center_to_v2 hidrata el clasificador oficial embebido."""
    from prostanet.presentation.v2_adapters import stage_center_to_v2
    data = stage_center_to_v2()
    classifier = data["quick_classifier"]
    assert classifier["source"] == "ProstaMed official clinical hub"
    assert classifier["endpoints"]["classify"] == "/api/state-classifier"
    assert classifier["endpoints"]["diagnosis_preview"] == "/api/official-diagnosis/preview"
    assert [step["key"] for step in classifier["steps"]] == ["diagnosis", "local", "metastatic", "adt"]
    field_names = {
        field["name"]
        for step in classifier["steps"]
        for field in step["fields"]
    }
    assert {"prior_local_therapy", "metastasis_site", "bone_axial_count", "systemic_progression_context"} <= field_names


# ──────────────────────────────────────────────────────────────────────
# §B.1 — Template stage_clinical_center_v2_redesign.html exists + structure
# ──────────────────────────────────────────────────────────────────────


def test_g3221_redesign_template_exists():
    """H.G3221 — templates/demos/stage_clinical_center_v2_redesign.html exists."""
    template = ROOT / "templates/demos/stage_clinical_center_v2_redesign.html"
    assert template.exists()


def test_g3222_redesign_template_moves_kpi_metrics_to_sidebar_panel():
    """H.G3222 — Template oculta KPI hero superior y conserva métricas desde icono lateral."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'class="pm2-kpi-hero"' not in template
    assert "data-system-metrics-toggle" in template
    assert "pm2SystemMetricsTemplate" in template
    assert "pm2-kpi-panel-grid" in template
    assert 'pm2-kpi-badge' in template
    assert 'kpi.value' in template


def test_g3223_redesign_template_hides_loops_rail_but_keeps_loop_access():
    """H.G3223 — Template oculta rail lateral de loops y conserva acceso dedicado."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'class="pm2-loops-rail"' not in template
    assert 'aria-label="Loop monitor compact rail"' not in template
    assert 'href="/loop-monitor"' in template
    assert "Loop monitor" in template


def test_g3224_redesign_template_has_cohort_filter():
    """H.G3224 — Template incluye cohort filter dropdown."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'data-cohort-filter' in template
    assert 'cohort_filter_options' in template


def test_g3225_redesign_template_has_trial_drilldown_triggers():
    """H.G3225 — Template incluye trial drill-down trigger buttons."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'data-trial-detail' in template
    assert 'pm2-trial-drilldown-trigger' in template
    assert 'Ver criterios' in template


def test_g3226_redesign_template_has_responsive_breakpoints():
    """H.G3226 — Template incluye media queries responsive (1280/1024/768/375)."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert "@media (max-width: 1280px)" in template
    assert "@media (max-width: 768px)" in template
    assert "@media (max-width: 375px)" in template


def test_g3227_redesign_template_has_skip_to_content():
    """H.G3227 — Template incluye skip-to-content link (WCAG 2.4.1)."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'href="#main-content"' in template
    assert 'class="skip-to-content"' in template


def test_g3237_redesign_template_embeds_official_classifier_panel():
    """H.G3237 — Hub v2 incluye panel oficial de selección rápida."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    assert 'id="pm2OfficialClassifier"' in template
    assert "Selección rápida del módulo clínico" in template
    assert "secuencia oficial de captura" in template
    assert "Ver v2 legacy" not in template
    assert "?v=v2_legacy" not in template
    assert 'href="/intake-wizard"' not in template
    assert 'href="#pm2OfficialClassifier"' in template
    assert "pm2OfficialClassifierConfig" in template
    assert "clinical_hub_quick_classifier.js" in template


def test_g3238_official_classifier_js_normalizes_aliases():
    """H.G3238 — JS dedicado normaliza alias visuales hacia StateClassifierService."""
    js = (ROOT / "static/js/clinical_hub_quick_classifier.js").read_text()
    assert "prior_local_therapy" in js
    assert "prior_prostatectomy" in js
    assert "prior_radiation" in js
    assert "bone_site_entries" in js
    assert "/api/state-classifier" in js
    assert "/api/official-diagnosis/preview" in js


# ──────────────────────────────────────────────────────────────────────
# §B.3 + B.5 — Routing + integration
# ──────────────────────────────────────────────────────────────────────


def test_g3228_clinical_hub_default_serves_redesign():
    """H.G3228 — GET /clinical-hub default → renderea stage_clinical_center_v2_redesign.html."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        assert "pm2-redesign-shell" in html  # New redesign marker
        assert "pm2-kpi-hero" not in html
        assert "data-system-metrics-toggle" in html
        assert "pm2SystemMetricsTemplate" in html
        assert "pm2-loops-rail" not in html


def test_g3229_clinical_hub_v2_legacy_redirects_to_official():
    """H.G3229 — GET /clinical-hub?v=v2_legacy ya no abre demo anterior; redirige al oficial."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub?v=v2_legacy")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/clinical-hub")
        followed = client.get("/clinical-hub?v=v2_legacy", follow_redirects=True)
        html = followed.data.decode("utf-8")
        assert "pm2-redesign-shell" in html
        assert "Selección rápida del módulo clínico" in html
        assert "Ver v2 legacy" not in html


def test_g3230_clinical_hub_legacy_v1_opt_out():
    """H.G3230 — GET /clinical-hub?v=legacy → renderea clinical_hub.html v1 legacy."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub?v=legacy")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        # Old v1 doesn't have v2 redesign markers
        assert "pm2-redesign-shell" not in html
        assert "pm2-kpi-hero" not in html


def test_g3231_redesign_renders_kpi_metrics_in_sidebar_panel_template():
    """H.G3231 — Redesign conserva métricas reales detrás del icono lateral."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub")
        html = r.data.decode("utf-8")
        assert "data-system-metrics-toggle" in html
        assert "pm2-kpi-panel-grid" in html
        assert "Gates pivotal" in html
        assert "Trials pivotales" in html
        assert "Loop vectors" in html
        assert "Módulos clínicos" in html


def test_g3232_redesign_does_not_render_loop_vector_rail_items():
    """H.G3232 — Redesign ya no renderiza items del rail lateral de loops."""
    import app as app_module
    import re
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub")
        html = r.data.decode("utf-8")
        # Count <li class="pm2-loop-vector-item">
        vector_items = re.findall(r'<li class="pm2-loop-vector-item"', html)
        assert len(vector_items) == 0
        assert 'href="/loop-monitor"' in html


# ──────────────────────────────────────────────────────────────────────
# §B.4 — A11y compliance
# ──────────────────────────────────────────────────────────────────────


def test_g3233_redesign_has_aria_labels():
    """H.G3233 — Redesign tiene aria-label en componentes críticos."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/clinical-hub")
        html = r.data.decode("utf-8")
        # Critical aria-labels
        assert 'aria-label="Mostrar métricas clave del sistema"' in html
        assert 'aria-label="Filtrar cohorte por rango de fecha"' in html


def test_g3234_redesign_has_focus_visible_styles():
    """H.G3234 — Redesign tiene focus-visible styles para WCAG 2.4.7."""
    template = (ROOT / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()
    # focus-visible class hooks present
    assert ":focus-visible" in template
    assert "outline: 2px solid #67e8f9" in template or "outline-color" in template


# ──────────────────────────────────────────────────────────────────────
# §B.5 — Version bump
# ──────────────────────────────────────────────────────────────────────


def test_g3235_faubot_release_lxcviii():
    """H.G3235 — FAUBOT_RELEASE bumped to LXCVIII."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_tags = ("LXCVIII", "LXCIX", "C")
    assert any(tag in FAUBOT_RELEASE for tag in valid_tags), (
        f"FAUBOT_RELEASE not bumped: {FAUBOT_RELEASE}"
    )
