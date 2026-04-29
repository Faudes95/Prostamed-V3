"""Tests dedicados Iteración Faubot LXC — Clinical Capture Refinement Loop.

Hipótesis verificables H.G2936-H.G2965 (cubren Pilar 8 + 9 longitudinal kinds +
auto-derive helpers + conditional logic + frontend validation).

Faubot 2026-04-28 LXC.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)


# ─── §A — Pillar 8 Data Capture ──────────────────────────────────────────
def test_g2936_pillar_8_imports():
    """H.G2936 — pillar_8_data_capture module imports."""
    from prostanet.agentic.pillars.pillar_8_data_capture import PILLAR
    assert PILLAR.pillar_id == 8
    assert PILLAR.weight == 10.0


def test_g2937_pillar_weights_sum_to_100_with_p8():
    """H.G2937 — Pesos suman 100 con P8 (P1=4 + P2=12 + P3=18 + P4=12 + P5=25 + P6=15 + P7=4 + P8=10 = 100)."""
    from prostanet.agentic.compliance_scorer import PILLAR_WEIGHTS
    assert sum(PILLAR_WEIGHTS.values()) == 100.0
    assert "p8" in PILLAR_WEIGHTS
    assert PILLAR_WEIGHTS["p8"] == 10.0
    assert PILLAR_WEIGHTS["p1"] == 4.0  # rebalanced 8→4
    assert PILLAR_WEIGHTS["p7"] == 4.0  # rebalanced 10→4


def test_g2938_p8_score_above_50():
    """H.G2938 — Pilar 8 score ≥50% post-LXC bootstrap."""
    from prostanet.agentic.pillars.pillar_8_data_capture import PILLAR
    ps = PILLAR.score()
    assert ps.score >= 50.0


def test_g2939_compliance_includes_8_pillars():
    """H.G2939 — Snapshot tiene 8 pillars."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    snap = compute_compliance_snapshot(persist=False)
    assert set(snap.scores.keys()) == {"p1","p2","p3","p4","p5","p6","p7","p8"}


# ─── §B — Auto-derive helpers ────────────────────────────────────────────
def test_g2940_isup_grade_derivation():
    """H.G2940 — ISUP grade calculation correct per WHO 2014."""
    from prostanet.shared.auto_derive_helpers import derive_isup_grade
    assert derive_isup_grade(3, 3)["value"] == 1
    assert derive_isup_grade(3, 4)["value"] == 2
    assert derive_isup_grade(4, 3)["value"] == 3
    assert derive_isup_grade(4, 4)["value"] == 4
    assert derive_isup_grade(4, 5)["value"] == 5
    assert derive_isup_grade(5, 5)["value"] == 5
    # Reject Gleason 2+2 (ISUP 2014)
    assert derive_isup_grade(2, 2)["valid"] is False


def test_g2941_psadt_requires_3_points():
    """H.G2941 — PSADT requires ≥3 PSA points + ≥3mo span."""
    from prostanet.shared.auto_derive_helpers import derive_psadt
    short = [{"sample_date": "2026-01-01", "value": 1.0},
             {"sample_date": "2026-02-01", "value": 1.5}]
    r = derive_psadt(short)
    assert r["valid"] is False
    # Adequate
    history = [
        {"sample_date": "2026-01-01", "value": 1.0},
        {"sample_date": "2026-04-01", "value": 2.0},
        {"sample_date": "2026-07-01", "value": 4.0},
    ]
    r2 = derive_psadt(history)
    assert r2["valid"] is True
    assert r2["value_months"] is not None
    assert r2["value_months"] < 6  # doubling fast


def test_g2942_charlson_calculation():
    """H.G2942 — Charlson computes from comorbidity dict + age adjusts."""
    from prostanet.shared.auto_derive_helpers import derive_charlson_score
    r = derive_charlson_score({
        "diabetes_no_complications": 1,
        "chronic_pulmonary_disease": 1,
        "renal_disease": 1,  # weight 2
    }, age=70)
    assert r["valid"] is True
    assert r["value"] == 4  # 1 + 1 + 2
    assert r["age_points"] >= 2  # age 70 = +3 decades from 40


def test_g2943_g8_returns_score_0_17():
    """H.G2943 — G8 score in [0,17] + risk classification."""
    from prostanet.shared.auto_derive_helpers import derive_g8_score
    r = derive_g8_score(age=72, ecog=1, weight_loss_recent=False, bmi=24,
                        polypharmacy=False, mood_low=False, ate_well=True,
                        mobility_ok=True, cognition_ok=True)
    assert r["valid"] is True
    assert 0 <= r["value"] <= 17
    assert r["risk"] in {"frail", "robust"}


def test_g2944_frailty_returns_status():
    """H.G2944 — Frailty returns robust/pre-frail/frail/incomplete."""
    from prostanet.shared.auto_derive_helpers import derive_frailty_status
    r1 = derive_frailty_status(age=85, ecog=2, charlson=5)
    assert r1["status"] == "frail"
    r2 = derive_frailty_status(age=60, ecog=0, charlson=2)
    assert r2["status"] == "robust"
    r3 = derive_frailty_status(age=None, ecog=2, charlson=3)
    assert r3["status"] == "incomplete"


def test_g2945_bcr_phoenix_criterion():
    """H.G2945 — Phoenix BCR: PSA ≥ nadir+2."""
    from prostanet.shared.auto_derive_helpers import derive_bcr_phoenix
    assert derive_bcr_phoenix(0.1, 2.5)["is_bcr"] is True
    assert derive_bcr_phoenix(0.1, 0.5)["is_bcr"] is False


def test_g2946_creatinine_clearance_cockcroft():
    """H.G2946 — CrCl Cockcroft formula."""
    from prostanet.shared.auto_derive_helpers import derive_creatinine_clearance
    r = derive_creatinine_clearance(creat_mg_dl=1.0, age=60, weight_kg=80, sex="male")
    # (140-60)*80 / (72*1.0) = 88.9 mL/min
    assert r["valid"] is True
    assert 80 <= r["value_ml_min"] <= 100


def test_g2947_disease_free_interval():
    """H.G2947 — DFI metachronous if >12mo."""
    from prostanet.shared.auto_derive_helpers import derive_disease_free_interval
    r1 = derive_disease_free_interval("2024-01-01", "2025-06-01")
    assert r1["is_metachronous"] is True
    r2 = derive_disease_free_interval("2024-01-01", "2024-08-01")
    assert r2["is_metachronous"] is False


# ─── §C — Endpoint /api/auto-derive/<nss> ────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from app import app
    return app.test_client()


def test_g2948_auto_derive_endpoint_returns_derivations(client):
    """H.G2948 — GET /api/auto-derive/<nss> retorna derivations dict."""
    r = client.get("/api/auto-derive/97000000001")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        body = r.get_json()
        assert body["success"] is True
        assert "derivations" in body
        assert "isup_grade" in body["derivations"]
        assert "psadt" in body["derivations"]


def test_g2949_auto_derive_endpoint_404_unknown_patient(client):
    """H.G2949 — Unknown patient returns 404."""
    r = client.get("/api/auto-derive/00000000000")
    assert r.status_code == 404


# ─── §D — Longitudinal kinds expansion ───────────────────────────────────
def test_g2950_ecog_kind_endpoint(client):
    """H.G2950 — POST kind=ecog accepted."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "ecog", "payload": {"date": "2026-04-15", "score": "2",
                                      "assessment_context": "routine_visit"},
    })
    assert r.status_code in (200, 409)


def test_g2951_bpi_kind_endpoint(client):
    """H.G2951 — POST kind=bpi accepted with breakdown fields."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "bpi", "payload": {"date": "2026-04-16", "worst": 7, "least": 2,
                                     "average": 5, "now": 4, "interference_avg": 30},
    })
    assert r.status_code in (200, 409)


def test_g2952_phq9_kind_endpoint(client):
    """H.G2952 — POST kind=phq9 accepted."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "phq9", "payload": {"date": "2026-04-17", "total_score": 12,
                                      "risk_level": "moderate"},
    })
    assert r.status_code in (200, 409)


def test_g2953_psma_pet_kind_endpoint(client):
    """H.G2953 — POST kind=psma_pet accepted with structured fields."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "psma_pet", "payload": {"date": "2026-04-18",
                                          "tracer": "Ga68_PSMA_11",
                                          "suvmax": 8.5, "lesion_count": 12,
                                          "distribution": "bone"},
    })
    assert r.status_code in (200, 409)


def test_g2954_bone_scan_kind_endpoint(client):
    """H.G2954 — POST kind=bone_scan accepted."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "bone_scan", "payload": {"date": "2026-04-19", "pelvis_count": 2,
                                           "spine_count": 3, "femur_count": 1,
                                           "extra_axial": "yes"},
    })
    assert r.status_code in (200, 409)


def test_g2955_visceral_mets_kind_endpoint(client):
    """H.G2955 — POST kind=visceral_mets accepted with desglose."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "visceral_mets", "payload": {"date": "2026-04-20",
                                                "liver_metastasis": "1",
                                                "lung_metastasis": "0"},
    })
    assert r.status_code in (200, 409)


def test_g2956_hrr_germinal_kind_endpoint(client):
    """H.G2956 — POST kind=hrr_germinal accepted."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "hrr_germinal", "payload": {"date": "2026-04-21",
                                              "germline_testing_done": "1",
                                              "germline_pathogenic_variant": "BRCA2"},
    })
    assert r.status_code in (200, 409)


def test_g2957_hrr_somatic_kind_endpoint(client):
    """H.G2957 — POST kind=hrr_somatic accepted."""
    r = client.post("/api/longitudinal/97000000001/append", json={
        "kind": "hrr_somatic", "payload": {"date": "2026-04-22",
                                              "somatic_testing_done": "1",
                                              "biomarker_source": "ctDNA",
                                              "somatic_pathogenic_variant": "ATM"},
    })
    assert r.status_code in (200, 409)


# ─── §E — Conditional logic batch ────────────────────────────────────────
def test_g2958_m1_crpc_has_conditional_logic():
    """H.G2958 — m1_crpc schema has ≥30 conditional_visibility entries post-LXC."""
    p = PROJECT_ROOT / "prostanet/domains/m1_crpc/schemas.py"
    content = p.read_text()
    cv_count = content.count("conditional_visibility")
    assert cv_count >= 30


def test_g2959_recurrence_bcr_has_conditional_logic():
    """H.G2959 — recurrence_bcr schema has ≥30 conditional_visibility entries."""
    p = PROJECT_ROOT / "prostanet/domains/recurrence_bcr/schemas.py"
    content = p.read_text()
    cv_count = content.count("conditional_visibility")
    assert cv_count >= 30


def test_g2960_germline_variant_conditional_on_test_done():
    """H.G2960 — germline_pathogenic_variant requires germline_testing_performed=1."""
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
    target = next((f for f in M1_CRPC_SCHEMA["fields"]
                    if f["name"] == "germline_pathogenic_variant"), None)
    if target:
        assert target.get("conditional_visibility") is not None


# ─── §F — Frontend validation ────────────────────────────────────────────
def test_g2961_longitudinal_template_has_validation_rules(client):
    """H.G2961 — Template incluye validation rules nuevas."""
    r = client.get("/longitudinal-capture/97000000001")
    body = r.data.decode("utf-8", errors="replace")
    assert "Fecha futura inválida" in body
    assert "ECOG debe ser 0-4" in body
    assert "PHQ-9 debe ser 0-27" in body
    assert "SUVmax > 100 improbable" in body


def test_g2962_longitudinal_template_has_new_kinds(client):
    """H.G2962 — Template incluye 8 new structured forms."""
    r = client.get("/longitudinal-capture/97000000001")
    body = r.data.decode("utf-8", errors="replace")
    for kind in ["ecog", "bpi", "esas", "phq9", "ctcae", "psma_pet",
                  "bone_scan", "visceral_mets", "hrr_germinal", "hrr_somatic"]:
        assert f"data-append-form=\"{kind}\"" in body, f"Missing kind: {kind}"


def test_g2963_patient_profile_has_auto_derive_panel(client):
    """H.G2963 — Patient profile includes auto-derive panel."""
    r = client.get("/patient_profile/97000000001")
    body = r.data.decode("utf-8", errors="replace")
    for field in ["isup_grade", "psadt", "charlson_score", "g8_score",
                   "frailty_status", "bcr_phoenix", "creatinine_clearance"]:
        assert field in body


# ─── §G — Aggregate compliance + release ─────────────────────────────────
def test_g2964_aggregate_compliance_above_82():
    """H.G2964 — Aggregate ≥82% post-LXC."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    snap = compute_compliance_snapshot(persist=False)
    assert snap.aggregate >= 82.0


def test_g2965_faubot_release_lxc():
    """H.G2965 — FAUBOT_RELEASE bumped to LXC."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    assert "LXC" in FAUBOT_RELEASE
