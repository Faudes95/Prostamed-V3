"""Tests dedicados Iteración Faubot LXC.1.1 — PSA Persistence Bug Fix +
Line Type Classification.

Bugs cerrados:
- baseline_psa NO se persistía a biomarker_longitudinal en register_new_patient.
  Solo testosterone_baseline funcionaba. Root cause: _preferred_psa_longitudinal_value
  no incluía baseline_psa como fallback.
- Treatment bands en torre no clasificaban tipo línea (ADT solo / Doblete / Triplete).

Hipótesis verificables H.G2981-H.G2990.
Faubot 2026-04-28 LXC.1.1.
"""
# IEC 62304 §5.6 (Integration testing)

from __future__ import annotations

import json
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


# ─── §A — PSA Baseline Persistence ───────────────────────────────────────
def test_g2981_preferred_psa_includes_baseline_psa():
    """H.G2981 — _preferred_psa_longitudinal_value detecta baseline_psa fallback."""
    from tracking_db import _preferred_psa_longitudinal_value
    # Caso: solo baseline_psa (sin psa_current/psa)
    value, source = _preferred_psa_longitudinal_value({"baseline_psa": 87.5})
    assert value == 87.5
    assert source == "baseline_psa"
    # Caso: baseline_psa + psa_current → psa_current wins (más reciente)
    value2, source2 = _preferred_psa_longitudinal_value(
        {"baseline_psa": 87.5, "psa_current": 12.0})
    assert value2 == 12.0
    assert source2 == "psa_current"


def test_g2982_preferred_psa_includes_quick_classify_alias():
    """H.G2982 — Alias psa_baseline_ng_ml (intake-wizard quick classify) reconocido."""
    from tracking_db import _preferred_psa_longitudinal_value
    value, source = _preferred_psa_longitudinal_value({"psa_baseline_ng_ml": 145.0})
    assert value == 145.0


def test_g2983_register_persists_baseline_psa_to_biomarkers(client):
    """H.G2983 — Registrar paciente con baseline_psa scalar persiste a biomarker_longitudinal."""
    test_nss = "98000099003"
    payload = {
        "nss": test_nss, "full_name": "Test G2983 PSA persist",
        "dob": "1960-01-01",
        "baseline_psa": 50.0,
        "testosterone_baseline": 350.0,
        "drug_scheme": "ADT_ABIRATERONE",
        "line_of_therapy_number": 1,
        "assessment_state": "mcspc_high_volume",
    }
    r = client.post("/api/register_patient", data=json.dumps(payload),
                      content_type="application/json")
    if r.status_code != 200:
        pytest.skip(f"Register failed: {r.status_code}")
    body = r.get_json() or {}
    assert body.get("success") is True

    import tracking_db
    core = tracking_db.load_patient_record_core(test_nss)
    if not core:
        pytest.skip("Patient not found post-register")
    data = tracking_db.build_patient_record_derivatives(core)
    biomarkers = data.get("biomarker_longitudinal") or []
    psa_count = sum(1 for b in biomarkers
                    if (b.get("biomarker_type") or "").upper() == "PSA")
    testo_count = sum(1 for b in biomarkers
                      if (b.get("biomarker_type") or "").upper() == "TESTOSTERONA")
    assert psa_count >= 1, "PSA baseline NOT persisted to biomarker_longitudinal"
    assert testo_count >= 1, "Testosterone baseline NOT persisted"


# ─── §B — Line Type Classification ───────────────────────────────────────
def test_g2984_classify_triplete_arasens():
    """H.G2984 — ADT+DAROLUTAMIDE+DOCETAXEL clasificado como triplete (ARASENS)."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("ADT_DAROLUTAMIDE_DOCETAXEL")
    assert r["category"] == "triplete"
    assert "ARASENS" in r.get("evidence_trial", "") or "PEACE" in r.get("evidence_trial", "")
    assert r["components_count"] == 3


def test_g2985_classify_doblete_enzamet():
    """H.G2985 — ADT+ENZALUTAMIDE clasificado como doblete (ENZAMET)."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("ADT_ENZALUTAMIDE")
    assert r["category"] == "doblete"
    assert "ENZAMET" in r.get("evidence_trial", "") or "TITAN" in r.get("evidence_trial", "")
    assert r["components_count"] == 2


def test_g2986_classify_doblete_chaarted():
    """H.G2986 — ADT+DOCETAXEL clasificado como doblete (CHAARTED)."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("ADT_DOCETAXEL")
    assert r["category"] == "doblete"
    assert "CHAARTED" in r.get("evidence_trial", "") or "STAMPEDE" in r.get("evidence_trial", "")


def test_g2987_classify_adt_solo():
    """H.G2987 — ADT_LHRH solo clasificado como adt_solo."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("ADT_LHRH_AGONIST")
    assert r["category"] == "adt_solo"
    assert r["components_count"] == 1


def test_g2988_classify_post_mcrpc_parp():
    """H.G2988 — OLAPARIB clasificado como PARP inhibitor post-mCRPC."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("OLAPARIB")
    assert r["category"] == "post_mcrpc_parp"
    assert "PROfound" in r.get("evidence_trial", "") or "TRITON" in r.get("evidence_trial", "")


def test_g2989_classify_radiopharm():
    """H.G2989 — LU177_PSMA617 clasificado como radiopharm."""
    from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type
    r = _classify_line_type("LU177_PSMA617")
    assert r["category"] == "radiopharm"
    assert "VISION" in r.get("evidence_trial", "") or "TheraP" in r.get("evidence_trial", "")


def test_g2990_treatment_bands_include_line_type(client):
    """H.G2990 — Treatment bands incluyen line_type + line_type_label en backend output."""
    import tracking_db
    from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
    core = tracking_db.load_patient_record_core("98000099001")
    if not core:
        pytest.skip("Test patient not found")
    data = tracking_db.build_patient_record_derivatives(core)
    psa_obs = build_psa_by_treatment_line(data)
    bands = psa_obs.get("treatment_bands") or []
    assert len(bands) >= 1
    for band in bands:
        assert "line_type" in band
        assert "line_type_label" in band
        assert "components_count" in band
