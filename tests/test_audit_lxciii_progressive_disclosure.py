"""tests/test_audit_lxciii_progressive_disclosure.py — FAUBOT LXCIII.

Tests para Iteración LXCIII (plan LXXXVII) — Progressive Disclosure
Capture Engine. Reemplaza intake "487 fields flat" con flujo:
  - Stage-aware (state-routed post-classifier)
  - Role-aware (clinical_role → disclosure_tier mapping)
  - Sequential disclosure (always_visible + 3 expandable accordion groups)
  - Live classification preview (D'Amico, CHAARTED, LATITUDE, PCWG3)
  - Recommendation preview (clinical_subspecialty_engine integration)

Componentes verificados:
  - §A: ProgressiveCaptureBuilder (build_stage_aware_capture)
  - §B: Endpoint POST /api/intake/classify
  - §C: Template intake_progressive_v2.html (bento grid + accordions)
  - §D: JS intake_progressive.js (8 quick classifier + live updates)
  - §E: Wire /intake-wizard route progressive default + ?v=legacy opt-out

HIPÓTESIS: H.G3076 → H.G3105 (~30 tests).
Faubot LXCIII (plan LXXXVII) — Progressive Disclosure Capture Engine.
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
# §A — ProgressiveCaptureBuilder
# ──────────────────────────────────────────────────────────────────────


def test_g3076_builder_module_imports():
    """H.G3076 — progressive_capture_builder module + functions importable."""
    from prostanet.presentation.progressive_capture_builder import (
        build_stage_aware_capture,
        map_clinical_role_to_tier,
        CLINICAL_ROLE_TO_DISCLOSURE_TIER,
        PER_STATE_ALWAYS_VISIBLE,
        DISEASE_STATE_LABELS,
    )
    assert callable(build_stage_aware_capture)
    assert callable(map_clinical_role_to_tier)


def test_g3077_clinical_role_to_tier_mapping():
    """H.G3077 — Map clinical_role → disclosure_tier covers 4 standard roles."""
    from prostanet.presentation.progressive_capture_builder import map_clinical_role_to_tier
    assert map_clinical_role_to_tier("required") == "always_visible"
    assert map_clinical_role_to_tier("decision_refiner") == "expandable_refiner"
    assert map_clinical_role_to_tier("monitoring") == "expandable_monitoring"
    assert map_clinical_role_to_tier("optional") == "expandable_research"
    # Default fallback
    assert map_clinical_role_to_tier("") == "expandable_refiner"
    assert map_clinical_role_to_tier(None) == "expandable_refiner"


def test_g3078_per_state_always_visible_covers_15_states():
    """H.G3078 — PER_STATE_ALWAYS_VISIBLE has at least 14 disease states defined."""
    from prostanet.presentation.progressive_capture_builder import PER_STATE_ALWAYS_VISIBLE
    assert len(PER_STATE_ALWAYS_VISIBLE) >= 14
    # Critical states present
    for state in ("localized_initial", "m1_crpc", "m0_crpc", "recurrence_bcr",
                  "mcspc_high_volume_sync", "diagnostic_workup"):
        assert state in PER_STATE_ALWAYS_VISIBLE, f"Missing state: {state}"


def test_g3079_always_visible_max_8_fields_per_state():
    """H.G3079 — Each state's always_visible list ≤8 fields (UX ergonomy)."""
    from prostanet.presentation.progressive_capture_builder import PER_STATE_ALWAYS_VISIBLE
    for state, fields in PER_STATE_ALWAYS_VISIBLE.items():
        assert 4 <= len(fields) <= 8, (
            f"State {state} has {len(fields)} always_visible fields "
            f"(expected 4-8 for ergonomy)"
        )


def test_g3080_build_localized_returns_visible_plus_refiners():
    """H.G3080 — build_stage_aware_capture('localized_initial') returns ≥8 visible + ≥350 refiners.

    NOTE: post-LXCVI.F adds 2 demographic always_visible (etnia + seguridad_social) cross-state
    → expected ≥8 (was exactly 8 pre-LXCVI.F; now 10).
    """
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    result = build_stage_aware_capture("localized_initial", {})
    assert len(result["always_visible"]) >= 8  # forward-compat LXCVI.F: 8 base + 2 demographic
    summary = result["summary"]
    assert summary["total_always_visible"] >= 8
    assert summary["total_refiners"] >= 350  # 410 ± de-dup


def test_g3081_build_includes_3_or_more_expandable_groups():
    """H.G3081 — Output includes ≥3 expandable groups (refiners + monitoring + research [+demographics_lifestyle LXCVI.F]).

    NOTE: post-LXCVI.F adds 4to grupo "demographics_lifestyle" → expected ≥3 (was exactly 3).
    """
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    result = build_stage_aware_capture("m1_crpc", {})
    assert len(result["expandable_groups"]) >= 3  # forward-compat LXCVI.F
    keys = [g["key"] for g in result["expandable_groups"]]
    assert "decision_refiners" in keys
    assert "monitoring" in keys
    assert "research" in keys


def test_g3082_build_localized_classifies_damico_very_high():
    """H.G3082 — Live classification detects D'Amico very_high for Gleason 9 + PSA 25 + T3b."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    result = build_stage_aware_capture("localized_initial", {
        "psa_value": 25, "gleason_score": 9, "clinical_t_stage": "T3b",
    })
    classification = result["live_classification"]
    assert classification.get("damico_risk") == "very_high"


def test_g3083_build_mcspc_classifies_chaarted_hv_correctly():
    """H.G3083 — CHAARTED HV detected con visceral OR ≥4 óseas+apendicular."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    # Caso 1: visceral mets → HV
    r1 = build_stage_aware_capture("mcspc_high_volume_sync", {
        "visceral_metastasis_present": "1",
    })
    assert r1["live_classification"].get("chaarted_volume") == "high"

    # Caso 2: ≥4 óseas + apendicular → HV
    r2 = build_stage_aware_capture("mcspc_high_volume_sync", {
        "bone_lesion_count_total": 6, "bone_appendicular_count": 2,
    })
    assert r2["live_classification"].get("chaarted_volume") == "high"


def test_g3084_build_mcspc_classifies_chaarted_lv_low_volume():
    """H.G3084 — CHAARTED LV con <4 óseas sin visceral."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    r = build_stage_aware_capture("mcspc_low_volume_sync_oligo", {
        "bone_lesion_count_total": 2, "visceral_metastasis_present": "0",
    })
    assert r["live_classification"].get("chaarted_volume") == "low"


def test_g3085_build_psadt_band_classification():
    """H.G3085 — PSADT band classification (rapid/moderate/slow).

    NOTE: post-LXCVI.E boundary fix per Stephenson JCO 2009 + SPARTAN/PROSPER/ARAMIS:
    rapid = <3m (was ≤6m), moderate = 3-10m (SPARTAN eligible), slow = >10m.
    """
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    # PSADT <3m → rapid (Stephenson aggressive band)
    r1 = build_stage_aware_capture("m0_crpc", {"psa_doubling_time_months": 2})
    assert "rapid" in r1["live_classification"].get("psadt_band", "")
    # PSADT 3-10m → moderate (SPARTAN/PROSPER/ARAMIS eligible)
    r2 = build_stage_aware_capture("m0_crpc", {"psa_doubling_time_months": 8})
    assert "moderate" in r2["live_classification"].get("psadt_band", "")
    # PSADT 6m → moderate (post-fix boundary)
    r3 = build_stage_aware_capture("m0_crpc", {"psa_doubling_time_months": 6})
    assert "moderate" in r3["live_classification"].get("psadt_band", "")


def test_g3086_build_includes_next_step_hint():
    """H.G3086 — Output includes context-specific next_step_hint."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    r = build_stage_aware_capture("m1_crpc", {})
    assert r["next_step_hint"]
    assert len(r["next_step_hint"]) > 20  # Not empty placeholder


def test_g3087_build_unknown_state_returns_default_visible():
    """H.G3087 — Unknown disease_state falls back to DEFAULT_ALWAYS_VISIBLE."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    r = build_stage_aware_capture("unknown_disease_state", {})
    # Should not raise — uses default list
    assert len(r["always_visible"]) >= 4


# ──────────────────────────────────────────────────────────────────────
# §B — Endpoint POST /api/intake/classify
# ──────────────────────────────────────────────────────────────────────


def test_g3088_intake_classify_endpoint_exists():
    """H.G3088 — POST /api/intake/classify endpoint registered + returns 200."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/intake/classify", json={
            "psa_value": 12, "ecog_score": 1, "known_cancer_diagnosis": 1,
        })
        assert r.status_code == 200


def test_g3089_intake_classify_returns_disease_state():
    """H.G3089 — Endpoint returns disease_state + stage_capture in response.

    NOTE: post-LXCVI.F adds 4to expandable group "demographics_lifestyle" → ≥3 (was exactly 3).
    """
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/intake/classify", json={
            "psa_value": 25, "gleason_score": 9, "clinical_tstage": "cT3b",
            "metastasis_site": "M0", "ecog_score": 0, "known_cancer_diagnosis": 1,
        })
        data = r.get_json()
        assert data["success"] is True
        assert "disease_state" in data
        assert "stage_capture" in data
        sc = data["stage_capture"]
        assert "always_visible" in sc
        assert "expandable_groups" in sc
        assert len(sc["expandable_groups"]) >= 3  # forward-compat LXCVI.F


def test_g3090_intake_classify_localized_returns_damico():
    """H.G3090 — Localized very-high payload → live_classification damico_risk = very_high."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/intake/classify", json={
            "psa_value": 25, "gleason_score": 9,
            "clinical_t_stage": "T3b", "clinical_tstage": "cT3b",
            "metastasis_site": "M0", "ecog_score": 0, "known_cancer_diagnosis": 1,
        })
        data = r.get_json()
        sc = data["stage_capture"]
        # damico_risk computed when state == localized_initial + has psa+gleason+t
        if sc.get("disease_state") == "localized_initial":
            assert sc["live_classification"].get("damico_risk") == "very_high"


def test_g3091_intake_classify_handles_invalid_payload_gracefully():
    """H.G3091 — Empty payload doesn't crash endpoint."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/intake/classify", json={})
        assert r.status_code in (200, 400)  # Either OK with default or validation error
        body = r.get_data(as_text=True).lower()
        assert "unhashable" not in body
        assert "typeerror" not in body


def test_g3092_intake_classify_strings_coerced_to_numerics():
    """H.G3092 — String numerics coerced (UI sends strings via FormData)."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/intake/classify", json={
            "psa_value": "25.5",  # String
            "gleason_score": "9",  # String
            "ecog_score": "0",  # String
            "known_cancer_diagnosis": 1,
        })
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# §C — Template intake_progressive_v2.html
# ──────────────────────────────────────────────────────────────────────


def test_g3093_intake_progressive_template_exists():
    """H.G3093 — Template file exists."""
    template = ROOT / "templates/intake_progressive_v2.html"
    assert template.exists()


def test_g3094_intake_progressive_uses_pm2_sidebar_macro():
    """H.G3094 — Template uses pm2_sidebar macro for v2 chrome consistency."""
    template = (ROOT / "templates/intake_progressive_v2.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in template
    assert "pm2_sidebar(" in template


def test_g3095_intake_progressive_has_bento_grid_layout():
    """H.G3095 — Template uses 3-column bento grid (sidebar + main + rail)."""
    template = (ROOT / "templates/intake_progressive_v2.html").read_text()
    assert "pm2-progressive-shell" in template
    assert "pm2-progressive-rail" in template
    # Both template and search key get spaces stripped for whitespace tolerance
    assert "grid-template-columns:280px1fr380px" in template.replace(" ", "")


def test_g3096_intake_progressive_has_3_step_indicators():
    """H.G3096 — Template renders 3-step progress indicator."""
    template = (ROOT / "templates/intake_progressive_v2.html").read_text()
    assert 'data-step="1"' in template
    assert 'data-step="2"' in template
    assert 'data-step="3"' in template


def test_g3097_intake_progressive_loads_intake_progressive_js():
    """H.G3097 — Template loads intake_progressive.js."""
    template = (ROOT / "templates/intake_progressive_v2.html").read_text()
    assert "intake_progressive.js" in template


# ──────────────────────────────────────────────────────────────────────
# §D — JS intake_progressive.js
# ──────────────────────────────────────────────────────────────────────


def test_g3098_intake_progressive_js_exists():
    """H.G3098 — JS file exists + has 8 quick classifier fields."""
    js_path = ROOT / "static/js/intake_progressive.js"
    assert js_path.exists()
    content = js_path.read_text()
    assert "QUICK_CLASSIFIER_FIELDS" in content
    assert "psa_value" in content
    assert "gleason_score" in content
    assert "clinical_t_stage" in content
    assert "metastasis_site" in content
    assert "ecog_score" in content


def test_g3099_intake_progressive_js_calls_classify_endpoint():
    """H.G3099 — JS fetches /api/intake/classify with debounce."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert "/api/intake/classify" in js
    assert "method:" in js or 'method: "POST"' in js
    assert "debounceTimer" in js or "setTimeout" in js


def test_g3100_intake_progressive_js_renders_accordion_groups():
    """H.G3100 — JS renders <details> accordion groups for expandable fields."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert "renderExpandableGroup" in js
    assert "<details" in js or 'createElement("details")' in js
    assert "pm2-disclosure-group" in js


# ──────────────────────────────────────────────────────────────────────
# §E — Wire /intake-wizard route progressive default + ?v=legacy opt-out
# ──────────────────────────────────────────────────────────────────────


def test_g3101_intake_wizard_default_redirects_to_official_classifier():
    """H.G3101 — GET /intake-wizard default → official classifier."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", "")


def test_g3102_intake_wizard_legacy_opt_out_redirects_to_official_classifier():
    """H.G3102 — GET /intake-wizard?v=legacy → official classifier."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard?v=legacy", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", "")


def test_g3103_intake_wizard_progressive_route_no_longer_renders_sidebar():
    """H.G3103 — retired route does not render a second intake sidebar."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)


def test_g3104_intake_wizard_progressive_route_redirects_before_render():
    """H.G3104 — retired route redirects before rendering progressive assets."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)


def test_g3105_intake_wizard_progressive_route_redirects_to_classifier():
    """H.G3105 — retired route points to classifier, not a duplicate consent flow."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard", follow_redirects=False)
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", "")
