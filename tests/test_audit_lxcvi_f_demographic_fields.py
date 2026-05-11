"""tests/test_audit_lxcvi_f_demographic_fields.py — FAUBOT LXCVI.F.

Tests para LXCVI.F — Demographic Fields Gap Closure:

  F.1: Step 1 quick classifier expanded 8 → 12 fields (nss + full_name +
       preferred_language + country)
  F.2: Step 2 always_visible cross-state +2 (etnia + seguridad_social)
  F.3: Step 2 expandable_groups +1 group "demographics_lifestyle" con 8 fields
  F.4: Backend migration 2 columns (country + preferred_language)
  F.5: Redirect /patient_intake?v=2 → /clinical-hub#pm2OfficialClassifier

HIPÓTESIS: H.G3176 → H.G3185 (10 tests).
Faubot LXCVI.F — Demographic Coverage Gap Closure.
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
# §F.1 — Step 1 Quick Classifier expanded
# ──────────────────────────────────────────────────────────────────────


def test_g3176_quick_classifier_includes_nss():
    """H.G3176 — QUICK_CLASSIFIER_FIELDS incluye nss (required identifier)."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert '"nss"' in js or "name: \"nss\"" in js
    # nss debe ser required
    nss_section = js[js.index('"nss"') if '"nss"' in js else js.index('name: "nss"'):][:300]
    assert "required: true" in nss_section


def test_g3177_quick_classifier_includes_full_name():
    """H.G3177 — QUICK_CLASSIFIER_FIELDS incluye full_name (required for legal)."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert '"full_name"' in js


def test_g3178_quick_classifier_includes_preferred_language():
    """H.G3178 — QUICK_CLASSIFIER_FIELDS incluye preferred_language (Cortana + reports)."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert '"preferred_language"' in js


def test_g3179_quick_classifier_includes_country():
    """H.G3179 — QUICK_CLASSIFIER_FIELDS incluye country (NCCN-US/EAU/COFEPRIS routing)."""
    js = (ROOT / "static/js/intake_progressive.js").read_text()
    assert '"country"' in js


# ──────────────────────────────────────────────────────────────────────
# §F.2 — Step 2 always_visible expansion
# ──────────────────────────────────────────────────────────────────────


def test_g3180_always_visible_includes_etnia():
    """H.G3180 — Step 2 always_visible incluye etnia cross-state (CHAARTED/STAMPEDE subgroup)."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    for state in ("localized_initial", "m1_crpc", "mcspc_high_volume_sync"):
        result = build_stage_aware_capture(state, {})
        names = [f["name"] for f in result["always_visible"]]
        assert "etnia" in names, f"State {state}: etnia missing"


def test_g3181_always_visible_includes_seguridad_social():
    """H.G3181 — Step 2 always_visible incluye seguridad_social cross-state (workflow routing)."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    for state in ("localized_initial", "m1_crpc", "recurrence_bcr"):
        result = build_stage_aware_capture(state, {})
        names = [f["name"] for f in result["always_visible"]]
        assert "seguridad_social" in names, f"State {state}: seguridad_social missing"


# ──────────────────────────────────────────────────────────────────────
# §F.3 — Demographics expandable group
# ──────────────────────────────────────────────────────────────────────


def test_g3182_demographics_expandable_group_present():
    """H.G3182 — Step 2 expandable_groups incluye 'demographics_lifestyle' con 8 fields."""
    from prostanet.presentation.progressive_capture_builder import build_stage_aware_capture
    result = build_stage_aware_capture("localized_initial", {})
    groups = result["expandable_groups"]
    demo_group = next((g for g in groups if g["key"] == "demographics_lifestyle"), None)
    assert demo_group is not None, "demographics_lifestyle group missing"
    assert demo_group["field_count"] >= 8

    expected_fields = [
        "estado_residencia", "escolaridad", "ocupacion", "estado_civil",
        "tabaquismo", "paquetes_anio", "actividad_fisica", "ipss_score",
    ]
    actual_names = [f["name"] for f in demo_group["fields"]]
    for f in expected_fields:
        assert f in actual_names, f"Field {f} missing in demographics group"


# ──────────────────────────────────────────────────────────────────────
# §F.4 — Backend migration
# ──────────────────────────────────────────────────────────────────────


def test_g3183_tracking_db_country_column_migration():
    """H.G3183 — tracking_db.py incluye ALTER patient_identity ADD COLUMN country."""
    db = (ROOT / "tracking_db.py").read_text()
    assert "ALTER TABLE patient_identity ADD COLUMN country TEXT" in db


def test_g3184_tracking_db_preferred_language_column_migration():
    """H.G3184 — tracking_db.py incluye ALTER patient_demographics ADD COLUMN preferred_language."""
    db = (ROOT / "tracking_db.py").read_text()
    assert "ALTER TABLE patient_demographics ADD COLUMN preferred_language TEXT" in db


# ──────────────────────────────────────────────────────────────────────
# §F.5 — Redirect /patient_intake?v=2 → official classifier
# ──────────────────────────────────────────────────────────────────────


def test_g3185_patient_intake_v2_redirects_to_official_classifier():
    """H.G3185 — /patient_intake?v=2 → official classifier entry."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/patient_intake?v=2", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308), (
            f"Expected redirect, got {r.status_code}"
        )
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", ""), (
            f"Expected official classifier redirect, got {r.headers.get('Location')}"
        )

        r2 = client.get("/patient_intake?v=2&keep_legacy=1", follow_redirects=False)
        assert r2.status_code in (301, 302, 303, 307, 308)
        assert "/clinical-hub#pm2OfficialClassifier" in r2.headers.get("Location", "")
