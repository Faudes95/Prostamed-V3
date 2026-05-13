"""Unit tests para v2_adapters (Faubot 2026-04-26 LXXVIII #67E).

Verifica que los adaptadores producen el shape correcto y son defensivos:
si el bundle viene vacío o con keys faltantes, retornan placeholders seguros
en lugar de KeyError/AttributeError.

Run:
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/homebrew/bin/python3.12 -m pytest \
        tests/test_v2_adapters.py -v --no-header -c /dev/null \
        --rootdir=/tmp -o cache_dir=/tmp/pytest_cache
"""
# IEC 62304 §5.5 (Unit verification)


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub APFS-locked modules antes del import (CLAUDE.md §12.2)
import types as _types
for _stub in ("tracking_db",):
    if _stub not in sys.modules:
        class _Stub(_types.ModuleType):
            def __getattr__(self, name):
                def _noop(*a, **k): return {}
                _noop.__name__ = name
                return _noop
        sys.modules[_stub] = _Stub(_stub)

from prostanet.presentation.v2_adapters import (
    bundle_to_v2_profile,
    bundle_to_v2_profile_full,
    dashboard_summary_to_v2,
    stage_center_to_v2,
    intake_form_schema_v2,
    _stage_key,
    _format_date,
)


# ── _stage_key normalization ────────────────────────────────────────────────

def test_stage_key_m1crpc():
    assert _stage_key("m1CRPC metastásico") == "m1crpc"
    assert _stage_key("M1_CRPC_high_volume") == "m1crpc"

def test_stage_key_localized():
    assert _stage_key("Localizado bajo riesgo") == "localized"
    assert _stage_key("LOCALIZED_INITIAL") == "localized"

def test_stage_key_palliative():
    assert _stage_key("Paliativo BSC") == "palliative"
    assert _stage_key("palliative_pathway") == "palliative"

def test_stage_key_default_diagnostic():
    assert _stage_key("Sin clasificar") == "diagnostic"
    assert _stage_key(None) == "diagnostic"


# ── _format_date defensive ─────────────────────────────────────────────────

def test_format_date_iso():
    assert _format_date("2026-04-26") == "2026-04-26"

def test_format_date_iso_with_time():
    assert _format_date("2026-04-26T14:30:00") == "2026-04-26"

def test_format_date_none():
    assert _format_date(None) == "—"

def test_format_date_empty():
    assert _format_date("") == "—"


# ── bundle_to_v2_profile (compact) ─────────────────────────────────────────

def test_bundle_compact_empty_inputs():
    """Bundle vacío → shape completo con placeholders, no KeyError."""
    result = bundle_to_v2_profile({}, {})
    expected_keys = {
        "identity", "decision_today", "vitals",
        "gate_counts", "gates_top", "gates_all",
        "audit_dims", "consent",
        "profile_view_raw", "patient_raw",
    }
    assert expected_keys.issubset(set(result.keys()))

def test_bundle_compact_decision_today_unavailable_when_empty():
    result = bundle_to_v2_profile({}, {})
    # Sin clinical_compass.recommended_direction → available=False
    assert result["decision_today"]["available"] is False

def test_bundle_compact_decision_today_from_clinical_compass():
    profile_view = {
        "clinical_compass": {
            "recommended_direction": "Iniciar olaparib",
            "why_this_now": "BRCA2+ confirmado",
            "evidence_anchor": "PROfound NCCN cat 1",
            "recommendation_family": "PARP",
        }
    }
    result = bundle_to_v2_profile(profile_view, {})
    assert result["decision_today"]["available"] is True
    assert result["decision_today"]["headline"] == "Iniciar olaparib"
    assert "BRCA2+" in result["decision_today"]["rationale"]

def test_bundle_compact_gate_severity_normalization():
    """3-tier severity: hard / soft / info → tokens v2 normalizados."""
    profile_view = {
        "pivotal_contraindication_gates_panel": {
            "gates": [
                {"code": "G07", "severity": "hard_block", "title": "X"},
                {"code": "G47", "severity": "soft_warning", "title": "Y"},
                {"code": "G14", "severity": "informational", "title": "Z"},
                {"code": "G99", "severity": "critical", "title": "Q"},  # alias
            ]
        }
    }
    result = bundle_to_v2_profile(profile_view, {})
    counts = result["gate_counts"]
    assert counts["hard_block"] == 2  # hard_block + critical alias
    assert counts["soft_warning"] == 1
    assert counts["informational"] == 1
    assert counts["total"] == 4

def test_bundle_compact_consent_signed_vs_pending():
    signed = bundle_to_v2_profile({}, {"consent": {"status": "signed"}})
    assert signed["consent"]["is_signed"] is True
    assert "autorizado" in signed["consent"]["badge_text"]

    pending = bundle_to_v2_profile({}, {"consent": {"status": "pending"}})
    assert pending["consent"]["is_signed"] is False
    assert "pendiente" in pending["consent"]["badge_text"].lower()


# ── bundle_to_v2_profile_full (9 tabs) ─────────────────────────────────────

def test_bundle_full_extends_compact():
    """Full debe incluir todas las keys del compact + extras."""
    full = bundle_to_v2_profile_full({}, {})
    compact_keys = {"identity", "decision_today", "vitals", "gate_counts",
                    "gates_top", "gates_all", "audit_dims", "consent"}
    extra_keys = {"psa_obs", "timeline_horizontal", "therapy_checkpoints",
                  "clinical_alerts", "evidence_table", "cohort_references",
                  "timeline_vertical", "intake_widgets", "changelog"}
    assert compact_keys.issubset(set(full.keys()))
    assert extra_keys.issubset(set(full.keys()))

def test_bundle_full_cohort_references_11_pivotales():
    full = bundle_to_v2_profile_full({}, {})
    assert len(full["cohort_references"]) == 11
    trials = {c["trial"] for c in full["cohort_references"]}
    assert {"CHAARTED", "ARASENS", "PROfound", "VISION"}.issubset(trials)

def test_bundle_full_changelog_min_entries():
    full = bundle_to_v2_profile_full({}, {})
    assert len(full["changelog"]) >= 10
    assert full["changelog"][0]["release"] == "LXXVII"

def test_bundle_full_psa_obs_no_data_safe():
    """Sin psa_observability → has_data=False, listas vacías."""
    full = bundle_to_v2_profile_full({}, {})
    assert full["psa_obs"]["has_data"] is False
    assert full["psa_obs"]["points"] == []
    assert full["psa_obs"]["per_line"] == []


# ── dashboard_summary_to_v2 ─────────────────────────────────────────────────

def test_dashboard_summary_empty_returns_kpis():
    """Summary vacío → 6 KPIs con placeholders, no error."""
    result = dashboard_summary_to_v2({})
    assert "kpis" in result
    assert len(result["kpis"]) == 6
    assert "cohort_distribution" in result
    assert "heatmap" in result
    assert "alert_stream" in result

def test_dashboard_summary_with_real_data():
    summary = {
        "total_patients": 192,
        "metastasis_distribution": {"M0": 100, "M1": 92},
    }
    result = dashboard_summary_to_v2(summary)
    assert result["kpis"][0]["value"] == "192"
    assert "M0" in result["cohort_distribution"]["labels"]


# ── stage_center_to_v2 ─────────────────────────────────────────────────────

def test_stage_center_returns_7_stages():
    result = stage_center_to_v2()
    assert len(result["stages"]) == 7
    keys = [s["key"] for s in result["stages"]]
    assert keys == ["diagnostic", "localized", "mcspc", "m0crpc", "m1crpc", "nepc", "palliative"]

def test_stage_center_default_stage():
    result = stage_center_to_v2()
    assert result["default_stage"] == ""

def test_stage_center_canvases_match_stages():
    result = stage_center_to_v2()
    for stage in result["stages"]:
        assert stage["key"] in result["canvases"]


# ── intake_form_schema_v2 ──────────────────────────────────────────────────

def test_intake_schema_returns_dict():
    schema = intake_form_schema_v2()
    assert isinstance(schema, dict)
    assert "presets" in schema or "stages" in schema  # builder mock fallback


if __name__ == "__main__":
    import sys as _sys
    import pytest
    _sys.exit(pytest.main([__file__, "-v"]))
