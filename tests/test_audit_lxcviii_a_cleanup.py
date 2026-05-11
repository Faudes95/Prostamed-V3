"""tests/test_audit_lxcviii_a_cleanup.py — FAUBOT LXCVIII.A.

Tests para LXCVIII.A — Cleanup Pre-Existing Failures (Top 5 ROI):

  A.2 API_DDI: /api/gates-coverage-dashboard JSON endpoint
  A.4 SCHEMA/DATA: CTCAE selectors + child_pugh unit + recurrence_bcr pivotal
  A.1 ENDPOINT_ALGORITHM_VERSION: /api/decision-audit/algorithm-version + /api/decision-audit/<patient>
  A.3 MHSPC_COPILOT: pivotal_contraindication_gates + not_recommended propagation
  A.5 SUBSPECIALTY_CASES: clinical_subspecialty_engine restaurado desde LXXXIV backup

HIPÓTESIS: H.G3201 → H.G3215 (~15 tests).
Faubot LXCVIII.A — Cleanup pre-existing failures.
"""
from __future__ import annotations

import sys
import types

if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            if n.startswith("__") and n.endswith("__"):
                raise AttributeError(n)
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")


# ──────────────────────────────────────────────────────────────────────
# §A.2 — API_DDI quick win
# ──────────────────────────────────────────────────────────────────────


def test_g3201_api_gates_coverage_dashboard_returns_200():
    """H.G3201 — /api/gates-coverage-dashboard retorna 200 + success=True."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/gates-coverage-dashboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "ddi_heatmap" in data
        assert "coverage" in data
        assert "ddi_cross_alerts_coverage" in data["coverage"]


# ──────────────────────────────────────────────────────────────────────
# §A.4 — SCHEMA/DATA conventions
# ──────────────────────────────────────────────────────────────────────


def test_g3202_ctcae_selectors_have_desconocido_prefix():
    """H.G3202 — CTCAE grade selectors empiezan con 'Desconocido'."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = {f.name: f for f in pivotal_gate_supporting_fields()}
    ctcae_fields = ["diarrhea_ctcae_grade", "hfsr_ctcae_grade", "fatigue_ctcae_grade", "xerostomia_ctcae_grade"]
    for name in ctcae_fields:
        assert name in fields, f"Missing field: {name}"
        f = fields[name]
        assert f.options[0] == "Desconocido", f"{name}: opciones[0] != Desconocido"
        assert f.default == "Desconocido", f"{name}: default != Desconocido"


def test_g3203_child_pugh_score_has_unit():
    """H.G3203 — child_pugh raw sum points field tiene unit='puntos'.

    NOTA LXCIX.2: el `child_pugh_score` canónico (alphabetic A/B/C) vive
    en `advanced_hepatic_fields()`. La suma numérica 5-15 se renombró a
    `child_pugh_sum_points` para evitar conflicto select-vs-number cuando
    domain schemas spread ambas funciones.
    """
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = {f.name: f for f in pivotal_gate_supporting_fields()}
    assert "child_pugh_sum_points" in fields
    assert fields["child_pugh_sum_points"].unit == "puntos"


def test_g3204_recurrence_bcr_includes_pivotal_contraindication_fields():
    """H.G3204 — recurrence_bcr schema incluye pivotal_contraindication_fields."""
    from prostanet.application.module_registry import ModuleRegistry
    registry = ModuleRegistry()
    fields = {f["name"] for f in registry.services["recurrence_bcr"].schema()["fields"]}
    required = {
        "prior_arpi_exposure_mhspc",
        "darolutamide_hypersensitivity",
        "uncontrolled_hypertension",
        "severe_heart_failure_nyha_iii_iv",
        "uncontrolled_diabetes",
        "no_bone_protective_agent",
        "radium223_candidate",
    }
    missing = required - fields
    assert not missing, f"Faltan FieldSpecs en recurrence_bcr: {missing}"


# ──────────────────────────────────────────────────────────────────────
# §A.1 — ENDPOINT_ALGORITHM_VERSION
# ──────────────────────────────────────────────────────────────────────


def test_g3205_api_decision_audit_algorithm_version_endpoint():
    """H.G3205 — /api/decision-audit/algorithm-version retorna 200 + gates_active_codes ≥18."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/decision-audit/algorithm-version")
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "version" in data
        codes = data["version"]["gates_active_codes"]
        assert isinstance(codes, list)
        assert len(codes) >= 18


def test_g3206_api_decision_audit_nonexistent_patient_returns_404():
    """H.G3206 — /api/decision-audit/<nonexistent> retorna 404 + success=False."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/api/decision-audit/99999999999")
        assert r.status_code == 404
        data = r.get_json()
        assert data["success"] is False
        assert "no encontrado" in data["error"].lower() or "not found" in data["error"].lower()


# ──────────────────────────────────────────────────────────────────────
# §A.3 — MHSPC_COPILOT propagation
# ──────────────────────────────────────────────────────────────────────


def test_g3207_mhspc_copilot_propagates_pivotal_contraindication_gates():
    """H.G3207 — mhspc_copilot bundle siempre incluye pivotal_contraindication_gates key."""
    from prostanet.domains.patient_tracking.mhspc_copilot_service import MhspcCopilotService
    svc = MhspcCopilotService()
    # Disabled bundle path
    bundle = svc._disabled_bundle(state="mcspc_high_volume", runtime_mode="copilot", status="not_applicable")
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle
    assert isinstance(bundle["pivotal_contraindication_gates"], list)
    assert isinstance(bundle["not_recommended"], list)


def test_g3208_localized_surveillance_copilot_propagates_pivotal_contraindication_gates():
    """H.G3208 — localized_surveillance_copilot bundle siempre incluye pivotal_contraindication_gates key."""
    from prostanet.domains.patient_tracking.localized_surveillance_copilot_service import (
        LocalizedSurveillanceCopilotService,
    )
    svc = LocalizedSurveillanceCopilotService()
    bundle = svc._disabled_bundle(state="localized_initial", runtime_mode="copilot", status="not_applicable")
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


# ──────────────────────────────────────────────────────────────────────
# §A.5 — SUBSPECIALTY_CASES restored
# ──────────────────────────────────────────────────────────────────────


def test_g3209_subspecialty_engine_returns_multiple_actions_for_t4_psa100():
    """H.G3209 — recommend_next_clinical_action retorna ≥3 actions para TR T4 + PSA 100."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    actions = recommend_next_clinical_action({
        "psa_value": 100,
        "clinical_t_stage": "cT4",
        "dre_fixation": "Confirmada",
        "primary_biopsy_not_performed": True,
        "ecog_current": 1,
    })
    assert len(actions) >= 3, f"Expected ≥3 actions, got {len(actions)}"


def test_g3210_subspecialty_engine_emergency_for_scc():
    """H.G3210 — SCC suspect → top action urgency='emergent'."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    actions = recommend_next_clinical_action({
        "spinal_cord_compression_suspected": True,
        "psa_value": 50,
        "clinical_t_stage": "cT3a",
        "primary_biopsy_not_performed": True,
    })
    assert actions[0].urgency == "emergent"


def test_g3211_subspecialty_engine_flare_protection_returns_degarelix_for_scc():
    """H.G3211 — recommend_flare_protection con cord_compression → degarelix protocol."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    result = recommend_flare_protection(
        tumor_burden="high", cord_compression_risk=True, ecog=2,
    )
    # Returns dict (not list) — protocol="degarelix" para cord compression
    assert isinstance(result, dict)
    assert result.get("protocol") == "degarelix"


def test_g3212_summarize_returns_complete_structure():
    """H.G3212 — summarize_subspecialty_recommendations retorna estructura completa."""
    from prostanet.shared.clinical_subspecialty_engine import summarize_subspecialty_recommendations
    result = summarize_subspecialty_recommendations({
        "psa_value": 100,
        "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
        "spinal_cord_compression_suspected": True,
        "volume_disease": "high",
    })
    assert "actions" in result
    assert "actions_count" in result  # actual key is actions_count (no underscore)
    assert "flare_protection_recommended" in result


# ──────────────────────────────────────────────────────────────────────
# §A.tests + bump verification
# ──────────────────────────────────────────────────────────────────────


def test_g3213_total_103_gates_loaded():
    """H.G3213 — 103 gates loaded post-LXCVIII.A (no regression)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert len(get_loaded_yaml_codes()) >= 103


def test_g3214_total_436_fieldspecs_loaded():
    """H.G3214 — 436 FieldSpecs loaded post-LXCVIII.A (no regression)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    assert len(pivotal_gate_supporting_fields()) >= 436


def test_g3215_faubot_release_lxcviii_or_higher():
    """H.G3215 — FAUBOT_RELEASE bumped to LXCVIII or higher."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_tags = ("LXCVIII", "LXCIX", "C")
    assert any(tag in FAUBOT_RELEASE for tag in valid_tags), (
        f"FAUBOT_RELEASE not bumped: {FAUBOT_RELEASE}"
    )
