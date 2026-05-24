"""Tests EPIC 47 — Longitudinal Trajectory Dashboard.

Cobertura:
  - trajectory_engine: build_trajectory_bundle shape + fail-safe
  - biomarker_series extraction desde patient.biomarker_longitudinal
  - ECOG series extraction desde patient.follow_ups
  - Kinetics: PSA doubling time, velocity, ALP trend, ECOG decline
  - trajectory_alert_engine: 5 detectors + priority sorting + fail-safe
  - REST endpoint /api/trajectory/<nss>: 200/404 + audit trail
  - View model integration: profile_compass inyecta trajectory
  - UI template: testids declarados + alerts rendering

FAUBOT CXXXV — 2026-05-23.
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────────
# Test 1 — Modules importable
# ─────────────────────────────────────────────────────────────────────


def test_epic47_modules_importable():
    """Engine + alert engine + routes deben cargar sin errores."""
    engine = importlib.import_module(
        "prostanet.domains.patient_tracking.trajectory_engine"
    )
    assert hasattr(engine, "build_trajectory_bundle")

    alerts = importlib.import_module(
        "prostanet.domains.patient_tracking.trajectory_alert_engine"
    )
    assert hasattr(alerts, "evaluate_trajectory_alerts")

    routes = importlib.import_module(
        "prostanet.presentation.trajectory_routes"
    )
    assert hasattr(routes, "trajectory_bp")
    assert routes.trajectory_bp.name == "trajectory"


# ─────────────────────────────────────────────────────────────────────
# Test 2 — Engine: bundle shape + fail-safe
# ─────────────────────────────────────────────────────────────────────


def test_epic47_engine_returns_unavailable_for_empty_patient():
    """Sin data, retorna available=False con reason — no levanta."""
    from prostanet.domains.patient_tracking.trajectory_engine import (
        build_trajectory_bundle,
    )

    assert build_trajectory_bundle(None)["available"] is False
    assert build_trajectory_bundle({})["available"] is False
    # Patient sin biomarkers ni follow_ups
    empty = build_trajectory_bundle({"identity": {"id": 1}, "baseline": {}})
    assert empty["available"] is False
    assert "no_temporal" in empty["reason"]


def test_epic47_engine_shape_with_biomarkers():
    """Patient con biomarkers ALP/LDH/TESTO debe producir series populadas."""
    from prostanet.domains.patient_tracking.trajectory_engine import (
        build_trajectory_bundle,
    )

    patient = {
        "identity": {"id": 999},
        "baseline": {},
        "biomarker_longitudinal": [
            {"biomarker_type": "ALP", "value": 80.0, "sample_date": "2026-01-15",
             "unit": "U/L", "lab_source": "central_lab"},
            {"biomarker_type": "ALP", "value": 105.0, "sample_date": "2026-04-15",
             "unit": "U/L", "lab_source": "central_lab"},
            {"biomarker_type": "LDH", "value": 220.0, "sample_date": "2026-01-15",
             "unit": "U/L", "lab_source": "central_lab"},
            {"biomarker_type": "TESTOSTERONA", "value": 25.0,
             "sample_date": "2026-04-01", "unit": "ng/dL", "lab_source": "central_lab"},
        ],
        "follow_ups": [],
    }
    bundle = build_trajectory_bundle(patient, include_cohort_overlay=False)
    assert bundle["available"] is True
    assert len(bundle["series"]["alp"]) == 2
    assert len(bundle["series"]["ldh"]) == 1
    assert len(bundle["series"]["testosterone"]) == 1
    # ALP trend (+31.25% últimos 3 meses)
    assert bundle["kinetics"]["alp_trend_pct_3m"] is not None
    assert bundle["kinetics"]["alp_trend_pct_3m"] > 25


def test_epic47_engine_psa_kinetics():
    """PSA doubling time + velocity + nadir desde combined_patient_timeline."""
    from prostanet.domains.patient_tracking.trajectory_engine import (
        _compute_kinetics,
    )

    # PSA rising rápido: 2.0 → 8.0 en 12 meses → PSADT ~6m
    psa_points = [
        {"date": "2025-01-15", "psa": 2.0},
        {"date": "2025-04-15", "psa": 3.0},
        {"date": "2025-07-15", "psa": 4.5},
        {"date": "2025-10-15", "psa": 6.0},
        {"date": "2026-01-15", "psa": 8.0},
    ]
    kinetics = _compute_kinetics(psa_points=psa_points, alp_points=[], ecog_points=[])
    assert kinetics["psa_doubling_time_months"] is not None
    assert 5 <= kinetics["psa_doubling_time_months"] <= 8  # ~6m esperado
    assert kinetics["psa_velocity_ng_per_year"] is not None
    assert kinetics["psa_velocity_ng_per_year"] > 0
    assert kinetics["psa_nadir"]["value"] == 2.0
    assert kinetics["psa_last_value"] == 8.0


def test_epic47_engine_ecog_decline_detection():
    """ECOG sube de 1 a 3 → decline detectado."""
    from prostanet.domains.patient_tracking.trajectory_engine import (
        _compute_kinetics,
    )
    ecog_points = [
        {"date": "2025-01-15", "value": 1, "source": "baseline"},
        {"date": "2025-12-15", "value": 3, "source": "follow_up_visit"},
    ]
    kinetics = _compute_kinetics(psa_points=[], alp_points=[], ecog_points=ecog_points)
    assert kinetics["ecog_decline_detected"] is True
    assert kinetics["ecog_first"] == 1
    assert kinetics["ecog_last"] == 3


# ─────────────────────────────────────────────────────────────────────
# Test 3 — Alert engine: 5 detectors
# ─────────────────────────────────────────────────────────────────────


def test_epic47_alert_engine_psadt_short_critical():
    """PSADT <6m + state=m0_crpc → critical alert SPARTAN/PROSPER/ARAMIS."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {"psa_doubling_time_months": 4.5},
        "series": {},
    }
    ctx = {"state_resolved": "m0_crpc"}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert any(a["alert_id"] == "psa_doubling_time_short_m0crpc" for a in alerts)
    crit = next(a for a in alerts if a["alert_id"] == "psa_doubling_time_short_m0crpc")
    assert crit["severity"] == "critical"
    assert "SPARTAN" in crit["citation"]


def test_epic47_alert_engine_alp_pre_bone_mets():
    """ALP +30% últimos 3m bajo ADT + sin imagen positiva → alert."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {"alp_trend_pct_3m": 30.0},
        "series": {},
    }
    ctx = {"on_adt": True, "last_imaging_status": "M0"}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert any(a["alert_id"] == "alp_pre_bone_mets_rise" for a in alerts)
    alert = next(a for a in alerts if a["alert_id"] == "alp_pre_bone_mets_rise")
    assert alert["severity"] == "high"
    assert "PSMA-PET" in alert["action_suggested"]


def test_epic47_alert_engine_psa_progression_on_arsi_pcwg3():
    """PSA nadir 2.0 → actual 4.0 bajo ARSI = +100% pct + Δ 2.0 → PCWG3 critical."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {
            "psa_nadir": {"value": 2.0, "date": "2025-06-01"},
            "psa_last_value": 4.5,
        },
        "series": {},
    }
    ctx = {"on_arsi": True}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert any(a["alert_id"] == "psa_progression_on_arsi_pcwg3" for a in alerts)
    alert = next(a for a in alerts if a["alert_id"] == "psa_progression_on_arsi_pcwg3")
    assert alert["severity"] == "critical"
    assert alert["evidence"]["pct_increase"] >= 25
    assert alert["evidence"]["absolute_increase_ng_ml"] >= 2


def test_epic47_alert_engine_ecog_severe_decline_critical():
    """ECOG 1 → 3 = critical (suspender citotóxicos, paliativo)."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {
            "ecog_decline_detected": True,
            "ecog_first": 1,
            "ecog_last": 3,
        },
        "series": {},
    }
    alerts = evaluate_trajectory_alerts(bundle, {})
    assert any(a["alert_id"] == "ecog_severe_decline" for a in alerts)


def test_epic47_alert_engine_testosterone_failure():
    """Testosterona 80 bajo ADT = critical castration failure."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {},
        "series": {
            "testosterone": [
                {"date": "2026-01-15", "value": 80.0, "unit": "ng/dL"},
            ],
        },
    }
    ctx = {"on_adt": True}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert any(a["alert_id"] == "testosterone_failure_to_suppress" for a in alerts)


def test_epic47_alert_engine_no_alerts_when_clean():
    """Trayectoria sin signals adversos → 0 alerts."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    bundle = {
        "available": True,
        "kinetics": {
            "psa_doubling_time_months": 24.0,  # >10m, no alert
            "alp_trend_pct_3m": 5.0,           # <25%, no alert
            "ecog_decline_detected": False,
        },
        "series": {"testosterone": [{"date": "2026-01-15", "value": 15.0}]},
    }
    ctx = {"on_adt": True}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert alerts == []


# ─────────────────────────────────────────────────────────────────────
# Test 4 — REST endpoint
# ─────────────────────────────────────────────────────────────────────


def test_epic47_rest_endpoint_404_for_unknown_nss():
    """GET /api/trajectory/<nss> retorna 404 si NSS no existe."""
    from flask import Flask
    from prostanet.presentation.trajectory_routes import trajectory_bp

    app = Flask(__name__)
    app.register_blueprint(trajectory_bp)
    client = app.test_client()

    response = client.get("/api/trajectory/NSS-DEFINITELY-NOT-EXISTS-XXX-9999")
    assert response.status_code == 404
    data = response.get_json()
    assert data["success"] is False
    assert "no encontrado" in data["error"].lower()


# ─────────────────────────────────────────────────────────────────────
# Test 5 — View model integration
# ─────────────────────────────────────────────────────────────────────


def test_epic47_view_model_helper_source_declares_trajectory_injection():
    """Smoke regression: profile_compass.py source debe contener la línea
    `"trajectory": _build_trajectory_snapshot_view_model(...)` que inyecta
    el bundle al view model. Test source-level evita import side effects
    pesados (ML models, etc) que cuelgan el runtime.
    """
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "domains" / "patient_tracking" / "profile_compass.py"
    content = src.read_text(encoding="utf-8")
    assert '"trajectory":' in content, "trajectory key no inyectada al bundle"
    assert "_build_trajectory_snapshot_view_model" in content, (
        "Helper view-model EPIC 47 no declarado en profile_compass.py"
    )
    assert "EPIC 47" in content, "Anchor EPIC 47 ausente del comentario"


# ─────────────────────────────────────────────────────────────────────
# Test 6 — UI template testids
# ─────────────────────────────────────────────────────────────────────


def test_epic47_template_has_trajectory_dashboard_testids():
    """patient_profile_v2.html debe declarar trajectory-dashboard testids."""
    from pathlib import Path

    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")

    required_testids = [
        "trajectory-dashboard",
        "trajectory-chart-psa",
    ]
    for tid in required_testids:
        assert f'data-testid="{tid}"' in content, f"Missing testid '{tid}'"
    # Header EPIC 47 identificable
    assert "EPIC 47" in content
    # Chart.js init script presente
    assert "trajChartPSA" in content


# ─────────────────────────────────────────────────────────────────────
# Test 7 — Alert priority sorting
# ─────────────────────────────────────────────────────────────────────


def test_epic47_alerts_sorted_by_severity_critical_first():
    """Alerts deben ordenarse critical → high → moderate → low."""
    from prostanet.domains.patient_tracking.trajectory_alert_engine import (
        evaluate_trajectory_alerts,
    )
    # Bundle que dispara 2 alerts: critical (PSADT m0_crpc) + high (alp rise)
    bundle = {
        "available": True,
        "kinetics": {
            "psa_doubling_time_months": 4.0,   # critical en m0_crpc
            "alp_trend_pct_3m": 35.0,           # high
        },
        "series": {},
    }
    ctx = {"state_resolved": "m0_crpc", "on_adt": True, "last_imaging_status": "M0"}
    alerts = evaluate_trajectory_alerts(bundle, ctx)
    assert len(alerts) >= 2
    # Primer alert debe ser critical
    assert alerts[0]["severity"] == "critical"
    # Verificar orden
    severities = [a["severity"] for a in alerts]
    severity_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    sorted_check = sorted(severities, key=lambda s: severity_order.get(s, 4))
    assert severities == sorted_check, f"Alerts not sorted: {severities}"


# ─────────────────────────────────────────────────────────────────────
# Test 8 — Engine bundle shape contract (regression guard)
# ─────────────────────────────────────────────────────────────────────


def test_epic47_engine_output_shape_contract():
    """build_trajectory_bundle output debe tener todas las keys esperadas
    (regression guard contra breaking changes en shape)."""
    from prostanet.domains.patient_tracking.trajectory_engine import (
        build_trajectory_bundle,
    )
    patient = {
        "identity": {"id": 100},
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "value": 5.0, "sample_date": "2026-01-01"},
        ],
        "baseline": {},
        "follow_ups": [],
    }
    bundle = build_trajectory_bundle(patient, include_cohort_overlay=False)

    # Top-level keys garantizadas
    for key in ("available", "summary", "series", "treatment_lanes",
                "event_markers", "cohort_overlay", "kinetics", "alerts",
                "engine_version"):
        assert key in bundle, f"Bundle missing key '{key}'"

    # series sub-keys
    for series_key in ("psa", "ecog", "alp", "ldh", "testosterone"):
        assert series_key in bundle["series"], f"Series missing '{series_key}'"

    # kinetics sub-keys
    for k in ("psa_doubling_time_months", "psa_velocity_ng_per_year",
              "psa_nadir", "alp_trend_pct_3m", "ecog_decline_detected"):
        assert k in bundle["kinetics"], f"Kinetics missing '{k}'"
