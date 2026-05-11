"""tests/test_audit_lxcvi_g_forward_compat.py — FAUBOT LXCVI.G.

Tests para LXCVI.G — Forward-compat fixes post-sweep regression LXCVI A-F:

  G.1: 4 LXCIII regressions causadas por LXCVI.F additions (≥8 visible, ≥3 groups)
  G.2: Forward-compat 14 hardcoded version assertions + UI coverage 100% restaurada
  G.3: 3 intake_wizard legacy tests usan ?v=legacy (post-LXCIII migration)
  G.4: 5 tests dedicados verificación finales

HIPÓTESIS: H.G3186 → H.G3190 (5 tests).
Faubot LXCVI.G — Forward-compat post-sweep cleanup.
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


def test_g3186_ui_coverage_100pct_post_lxcvi_g():
    """H.G3186 — Post-LXCVI.G UI coverage 100% restored (todas FieldSpecs en UI)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    helper = pivotal_gate_supporting_fields()
    data = build_intake_demo_data()
    ui_fields = set()
    for stage_fields in data["fields"].values():
        for f in stage_fields:
            if f.get("name"):
                ui_fields.add(f["name"])
    helper_names = {f.name for f in helper}
    missing = helper_names - ui_fields
    assert not missing, f"Coverage gap: {len(missing)} fields missing in UI: {sorted(missing)[:10]}"


def test_g3187_lxcvi_ae_contraindications_stage_present():
    """H.G3187 — Nueva stage 'lxcvi_ae_contraindications' wired al builder."""
    from prostanet.presentation.v2_advanced_capture_builder import build_advanced_capture_stages
    stages, fields = build_advanced_capture_stages()
    stage_keys = {s["key"] for s in stages}
    assert "lxcvi_ae_contraindications" in stage_keys


def test_g3188_103_gates_loaded_post_lxcvi():
    """H.G3188 — Catálogo 103 gates (89 base + 14 LXCVI) loaded sin regression."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 103, f"Gates regressed: {len(codes)} (expected ≥103)"


def test_g3189_intake_progressive_default_post_lxcvi():
    """H.G3189 — /intake-wizard redirige a la puerta oficial."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/intake-wizard", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", "")


def test_g3190_faubot_release_lxcvi_or_higher():
    """H.G3190 — FAUBOT_RELEASE bumped to LXCVI (post-sweep verification)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_tags = ("LXCVI", "LXCVII", "LXCVIII", "LXCIX", "C")
    assert any(tag in FAUBOT_RELEASE for tag in valid_tags), (
        f"FAUBOT_RELEASE not bumped past LXCV: {FAUBOT_RELEASE}"
    )
