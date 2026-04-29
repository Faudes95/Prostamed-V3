"""Tests dedicados Iteración Faubot LXC.1 — PSA Unified + Torre Vigilancia integration.

Hipótesis verificables H.G2966-H.G2980 cubriendo cierre de brechas A7+B1+C3:
- PSA unified source of truth (psa_unified.py)
- Endpoint /api/patient/<nss>/psa-unified
- psa_line_monitor refactored para usar unified
- Chart torre vigilancia consume bundle real (no hardcoded)
- Testosterona overlay + dynamic treatment bands
- Cross-field clinical validation (cT0+M1, Gleason ISUP, ECOG max)

Faubot 2026-04-28 LXC.1.
"""
# IEC 62304 §5.5 (Unit verification) + §5.6 (Integration testing)

from __future__ import annotations

import os, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)


@pytest.fixture(scope="module")
def client():
    from app import app
    return app.test_client()


# ─── §A — PSA Unified module (B1 fix) ────────────────────────────────────
def test_g2966_psa_unified_imports():
    """H.G2966 — psa_unified module exposes API."""
    from prostanet.shared.psa_unified import (
        unified_psa_timeline, latest_psa_value, psa_nadir,
        psa_doubling_time_months, is_psa_increasing,
    )
    assert callable(unified_psa_timeline)


def test_g2967_psa_unified_seeds_baseline_idempotent():
    """H.G2967 — baseline_psa auto-seeded as point 0 if not in biomarker_longitudinal."""
    from prostanet.shared.psa_unified import unified_psa_timeline
    patient = {
        "baseline": {"baseline_psa": 45.0},
        "identity": {"diagnosis_date": "2024-06-01"},
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "sample_date": "2024-09-01", "value": 12.0},
        ],
    }
    timeline = unified_psa_timeline(patient)
    assert len(timeline) == 2
    # baseline at point 0
    assert timeline[0]["value"] == 45.0
    assert timeline[0]["locked"] is True
    assert "intake_baseline" in timeline[0]["source"]


def test_g2968_psa_unified_no_double_seed():
    """H.G2968 — si baseline ya está en biomarker_longitudinal con misma fecha ±7d, NO duplica."""
    from prostanet.shared.psa_unified import unified_psa_timeline
    patient = {
        "baseline": {"baseline_psa": 45.0},
        "identity": {"diagnosis_date": "2024-06-01"},
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "sample_date": "2024-06-03", "value": 45.0},
            {"biomarker_type": "PSA", "sample_date": "2024-09-01", "value": 12.0},
        ],
    }
    timeline = unified_psa_timeline(patient)
    # NOT 3 points, just 2 (baseline already represented)
    assert len(timeline) == 2


def test_g2969_psa_nadir_post_treatment():
    """H.G2969 — psa_nadir filtra puntos post-treatment_start."""
    from prostanet.shared.psa_unified import psa_nadir
    patient = {
        "baseline": {"baseline_psa": 45.0},
        "identity": {"diagnosis_date": "2024-06-01"},
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "sample_date": "2024-09-01", "value": 12.0},
            {"biomarker_type": "PSA", "sample_date": "2025-02-01", "value": 0.5},
        ],
        "treatments": [{"start_date": "2024-08-01", "drug_scheme": "ADT"}],
    }
    nadir = psa_nadir(patient, since_treatment_start=True)
    assert nadir is not None
    assert nadir["value"] == 0.5


def test_g2970_psa_unified_endpoint(client):
    """H.G2970 — GET /api/patient/<nss>/psa-unified retorna timeline + PSADT."""
    r = client.get("/api/patient/97000000001/psa-unified")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert "timeline" in body
    assert "n_points" in body
    assert "psadt" in body
    assert "gate_55_m0crpc_psadt_alert" in body


def test_g2971_psa_unified_endpoint_404_unknown(client):
    """H.G2971 — Unknown patient returns 404."""
    r = client.get("/api/patient/99999999999/psa-unified")
    assert r.status_code == 404


# ─── §B — psa_line_monitor uses unified (B1 fix) ─────────────────────────
def test_g2972_psa_line_monitor_uses_unified():
    """H.G2972 — _extract_psa_points uses unified_psa_timeline (B1 single source)."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _extract_psa_points
    patient = {
        "baseline": {"baseline_psa": 45.0},
        "identity": {"diagnosis_date": "2024-06-01"},
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "sample_date": "2024-09-01", "value": 12.0},
        ],
    }
    points, source = _extract_psa_points(patient)
    # baseline_psa now appears as point 0 (LXC fix B1)
    assert len(points) == 2
    assert points[0]["psa"] == 45.0
    assert "psa_unified" in source or "unified" in source


def test_g2973_psa_line_monitor_handles_unified_only():
    """H.G2973 — Si ONLY biomarker_longitudinal pero baseline missing, sigue funcionando."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _extract_psa_points
    patient = {
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "sample_date": "2024-09-01", "value": 12.0},
            {"biomarker_type": "PSA", "sample_date": "2024-12-01", "value": 8.0},
        ],
    }
    points, _ = _extract_psa_points(patient)
    assert len(points) == 2


# ─── §C — Torre vigilancia chart consumes bundle (B1+A7 fix) ─────────────
def test_g2974_profile_chart_consumes_psa_obs_bundle(client):
    """H.G2974 — Patient profile JS chart uses psa_obs bundle (no hardcoded demo arrays)."""
    r = client.get("/patient_profile/97000000001")
    assert r.status_code == 200
    src = r.data.decode("utf-8", errors="replace")
    # Bundle data injection markers
    assert "const psaObsBundle = " in src
    assert "const psaForecastBundle = " in src
    assert "const psaCohortBundle = " in src
    # LXC fix B1 marker
    assert "LXC fix B1" in src
    # Dynamic line colors (not hardcoded 1=blue, 2=purple)
    assert "_lineColorsList" in src
    assert "Object.values" in src or "[...new Set(lineAssign)]" in src


def test_g2975_profile_chart_has_testosterone_overlay(client):
    """H.G2975 — Chart includes testosterona dataset on y2 axis (LXC integration)."""
    r = client.get("/patient_profile/97000000001")
    src = r.data.decode("utf-8", errors="replace")
    assert "Testosterona (ng/dL)" in src
    assert "yAxisID: 'y2'" in src
    assert "y2: { type: 'linear'" in src
    assert "Testo castrate ≤50" in src


def test_g2976_profile_chart_dynamic_treatment_bands(client):
    """H.G2976 — buildTreatmentBandAnnotations() dynamic from bundle."""
    r = client.get("/patient_profile/97000000001")
    src = r.data.decode("utf-8", errors="replace")
    assert "function buildTreatmentBandAnnotations" in src
    assert "_bundleBands.forEach" in src
    # Castrate annotation
    assert "yScaleID: 'y2'" in src or 'yScaleID: \'y2\'' in src


# ─── §D — Adapter exposes new keys ───────────────────────────────────────
def test_g2977_adapter_exposes_psa_obs_in_profile_full():
    """H.G2977 — bundle_to_v2_profile_full includes psa_obs + testosterone_history."""
    import inspect
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    src = inspect.getsource(bundle_to_v2_profile_full)
    assert '"psa_obs"' in src
    assert '"testosterone_history"' in src


# ─── §E — Cross-field validation (C3 fix) ────────────────────────────────
def test_g2978_intake_wizard_has_cross_field_validation(client):
    """H.G2978 — Intake wizard includes iwCrossFieldValidate function."""
    r = client.get("/intake-wizard")
    src = r.data.decode("utf-8", errors="replace")
    assert "iwCrossFieldValidate" in src
    assert "cT0 + M1" in src or "cT0+M1" in src or "ct0" in src.lower()
    assert "ISUP 2014" in src
    assert "Gleason 2+2" in src


# ─── §F — PSADT auto-derive integration (A7 fix) ─────────────────────────
def test_g2979_auto_derive_endpoint_includes_psadt(client):
    """H.G2979 — /api/auto-derive/<nss> includes PSADT field."""
    r = client.get("/api/auto-derive/97000000001")
    assert r.status_code == 200
    body = r.get_json()
    assert "psadt" in body.get("derivations", {})


# ─── §G — FAUBOT_RELEASE LXC.1 ───────────────────────────────────────────
def test_g2980_faubot_release_lxc1():
    """H.G2980 — FAUBOT_RELEASE bumped to LXC.1."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    assert "LXC" in FAUBOT_RELEASE
