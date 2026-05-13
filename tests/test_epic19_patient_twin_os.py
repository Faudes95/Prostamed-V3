# IEC 62304 §5.7 (System testing) — EPIC 19
"""Tests EPIC 19 — Patient Twin OS: true personalized SDM.

patient_twin_os.py orquesta:
  1. Preferences extraction (goal_of_care, tradeoff, tolerance, redecision)
  2. AI predictions (4 models via PredictionService)
  3. Regimen scoring 0-10 con weights del paciente
  4. Re-decision alerts cuando PROs cruzan thresholds del paciente
  5. Readiness % (preferences + AI substrate + alerts)

Beneficio clínico verificado:
  - Rankings de regímenes adaptados a goal_of_care del paciente
  - Tolerance mismatch detection (ej: hematológica G3+ EXCEDE tolerance)
  - Re-decision alerts (FACT-P drop, Karnofsky drop crossing thresholds)
  - Caveats explícitos: shadow validation NO production-ready
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── Module presence + version ───────────────────


def test_epic19_module_exists():
    """patient_twin_os.py debe existir y ser importable."""
    module_path = PROJECT_ROOT / "prostanet" / "domains" / "patient_tracking" / "patient_twin_os.py"
    assert module_path.exists(), f"Missing module: {module_path}"
    from prostanet.domains.patient_tracking import patient_twin_os as ptos
    assert hasattr(ptos, "build_patient_twin_view")
    assert hasattr(ptos, "PATIENT_TWIN_OS_VERSION")
    assert ptos.PATIENT_TWIN_OS_EPIC == 19


def test_epic19_regimen_catalog_includes_pivotal_regimens():
    """REGIMEN_CATALOG debe cubrir docetaxel, abiraterona, enzalutamida, apalutamida, darolutamide."""
    from prostanet.domains.patient_tracking.patient_twin_os import REGIMEN_CATALOG
    regimen_names = {r["regimen_name"] for r in REGIMEN_CATALOG.values()}
    must_have = {"docetaxel", "abiraterone", "enzalutamide", "apalutamide", "darolutamide_docetaxel"}
    missing = must_have - regimen_names
    assert not missing, f"Catalog missing regimens: {missing}"


# ─────────────────── Preference extraction ───────────────────


def test_epic19_extract_preferences_with_explicit_values():
    """Si patient_record tiene patient_values dict → extract correctamente."""
    from prostanet.domains.patient_tracking.patient_twin_os import extract_preferences

    record = {
        "patient_values": {
            "goal_of_care": "max_qol",
            "decision_tradeoff": {"os_weight": 0.3, "qol_weight": 0.7},
            "toxicity_tolerance": {"hematologic_g3": "intolerable", "hepatic_g3": "tolerable"},
            "redecision_threshold": {"fact_p_drop_pts": 3, "karnofsky_drop_pts": 15},
            "baseline_pro": {"fact_p": 87, "esas_pain": 2},
        }
    }
    profile = extract_preferences(record)
    assert profile.goal_of_care == "max_qol"
    assert profile.os_weight == 0.3
    assert profile.qol_weight == 0.7
    assert profile.toxicity_tolerance["hematologic_g3"] == "intolerable"
    assert profile.redecision_threshold["fact_p_drop_pts"] == 3
    assert profile.baseline_pro["fact_p"] == 87
    assert profile.capture_completeness_pct >= 80


def test_epic19_extract_preferences_uses_defaults_when_empty():
    """Sin preferences capturadas, usa defaults sin error."""
    from prostanet.domains.patient_tracking.patient_twin_os import extract_preferences

    profile = extract_preferences({})
    assert profile.goal_of_care == "balanced"
    assert profile.os_weight == 0.5
    assert profile.qol_weight == 0.5
    assert profile.capture_completeness_pct < 30


def test_epic19_extract_preferences_infers_weights_from_goal():
    """Si solo goal_of_care está set, infiere weights (max_os → 0.75/0.25)."""
    from prostanet.domains.patient_tracking.patient_twin_os import extract_preferences

    record = {"patient_values": {"goal_of_care": "max_os"}}
    profile = extract_preferences(record)
    assert profile.os_weight == 0.75
    assert profile.qol_weight == 0.25


# ─────────────────── Regimen scoring ───────────────────


def test_epic19_score_regimen_penalizes_tolerance_mismatch():
    """Hematologic G3+ 25% con tolerance 'intolerable' → tolerance_mismatch flag."""
    from prostanet.domains.patient_tracking.patient_twin_os import (
        score_regimen,
        PatientPreferenceProfile,
        REGIMEN_CATALOG,
    )
    docetaxel = REGIMEN_CATALOG[1]
    prefs = PatientPreferenceProfile(
        goal_of_care="balanced",
        os_weight=0.5,
        qol_weight=0.5,
        toxicity_tolerance={"hematologic_g3": "intolerable"},
    )
    score = score_regimen(docetaxel, prefs, patient_state="mcspc_high_volume")
    assert score.regimen_name == "docetaxel"
    # 25% hematologic + intolerable → mismatch
    assert len(score.tolerance_mismatches) >= 1
    assert "hematologic" in score.tolerance_mismatches[0].lower()
    # Score should be penalized
    assert score.score < 6.0


def test_epic19_score_regimen_prefers_high_os_when_max_os_goal():
    """Paciente con goal=max_os → darolutamide+docetaxel (best OS gain 19mo) ranks alto."""
    from prostanet.domains.patient_tracking.patient_twin_os import (
        score_regimen,
        PatientPreferenceProfile,
        REGIMEN_CATALOG,
    )
    daro_doce = REGIMEN_CATALOG[5]
    enza = REGIMEN_CATALOG[3]
    prefs_max_os = PatientPreferenceProfile(
        goal_of_care="max_os",
        os_weight=0.75,
        qol_weight=0.25,
        toxicity_tolerance={},  # No tolerance constraints
    )
    score_daro = score_regimen(daro_doce, prefs_max_os, patient_state="mcspc_high_volume")
    score_enza = score_regimen(enza, prefs_max_os, patient_state="mcspc_high_volume")
    # daro+doce has 19mo OS vs enza 13mo → should score higher when OS-weighted
    assert score_daro.score > score_enza.score, (
        f"daro_doce ({score_daro.score}) should beat enza ({score_enza.score}) for max_os patient"
    )


def test_epic19_score_regimen_indication_mismatch_penalty():
    """Regimen con indication mCSPC_high_volume aplicado a paciente M0_CRPC → penalty."""
    from prostanet.domains.patient_tracking.patient_twin_os import (
        score_regimen,
        PatientPreferenceProfile,
        REGIMEN_CATALOG,
    )
    daro_doce = REGIMEN_CATALOG[5]  # ARASENS — high_volume only
    prefs = PatientPreferenceProfile()
    score = score_regimen(daro_doce, prefs, patient_state="m0_crpc")
    assert score.indications_match is False
    # Score must reflect indication penalty
    assert score.score < 7.0


# ─────────────────── Re-decision alerts ───────────────────


def test_epic19_redecision_alert_fact_p_drop_crosses_threshold():
    """FACT-P drop > patient's threshold → alert."""
    from prostanet.domains.patient_tracking.patient_twin_os import (
        detect_redecision_alerts,
        PatientPreferenceProfile,
    )
    prefs = PatientPreferenceProfile(
        baseline_pro={"fact_p": 90.0},
        redecision_threshold={"fact_p_drop_pts": 3},
    )
    record = {
        "follow_ups": [
            {"fact_p": 85.0},  # 5 pt drop > 3
        ]
    }
    alerts = detect_redecision_alerts(record, prefs)
    assert len(alerts) == 1
    assert alerts[0].threshold_name == "fact_p_drop"
    assert alerts[0].observed_value == 5.0
    assert "FACT-P" in alerts[0].message


def test_epic19_redecision_alert_karnofsky_drop_critical():
    """Karnofsky drop > 20 → critical severity."""
    from prostanet.domains.patient_tracking.patient_twin_os import (
        detect_redecision_alerts,
        PatientPreferenceProfile,
    )
    prefs = PatientPreferenceProfile(
        redecision_threshold={"karnofsky_drop_pts": 10},
    )
    record = {
        "baseline": {"karnofsky": 90},
        "follow_ups": [
            {"karnofsky": 60},  # 30 pt drop, very critical
        ]
    }
    alerts = detect_redecision_alerts(record, prefs)
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


# ─────────────────── End-to-end build_patient_twin_view ───────────────────


def test_epic19_build_view_returns_serializable_dict():
    """build_patient_twin_view debe retornar dict serializable."""
    import json
    from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view

    record = {
        "identity": {"id": 1, "nss": "12345"},
        "patient_values": {
            "goal_of_care": "max_qol",
            "decision_tradeoff": {"os_weight": 0.3, "qol_weight": 0.7},
            "toxicity_tolerance": {"hematologic_g3": "intolerable"},
        },
        "latest_assessment": {"reconciled_state": "mcspc_high_volume_sync"},
        "follow_ups": [],
        "baseline": {},
    }
    view = build_patient_twin_view(record, prediction_service=MagicMock(predict_state_transition=MagicMock(return_value=None), predict_treatment_response=MagicMock(return_value=None)))
    # Must be JSON-serializable
    serialized = json.dumps(view)
    assert serialized is not None
    assert view["available"] is True
    assert "regimen_rankings" in view
    assert "redecision_alerts" in view
    assert "preferences" in view
    assert "caveats" in view


def test_epic19_build_view_includes_shadow_caveat():
    """Caveats deben mencionar shadow validation honesto."""
    from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view

    view = build_patient_twin_view({"identity": {"id": 1}})
    caveats_text = " ".join(view.get("caveats") or [])
    assert "shadow" in caveats_text.lower(), "Caveats must declare shadow validation"
    assert "synthetic" in caveats_text.lower() or "epic 16" in caveats_text.lower() or "epic 17" in caveats_text.lower()


def test_epic19_build_view_rankings_sorted_descending():
    """regimen_rankings debe estar ordenado por score descendente."""
    from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view

    record = {
        "identity": {"id": 1},
        "patient_values": {"goal_of_care": "max_os"},
        "latest_assessment": {"reconciled_state": "mcspc_high_volume_sync"},
    }
    view = build_patient_twin_view(record)
    rankings = view["regimen_rankings"]
    assert len(rankings) >= 2
    for i in range(len(rankings) - 1):
        assert rankings[i]["score"] >= rankings[i + 1]["score"], (
            f"Rankings not sorted descending at position {i}"
        )


# ─────────────────── Loop Monitor integration (PTR → 100) ───────────────────


def test_epic19_loop_monitor_ptr_reaches_100():
    """Con patient_twin_os.py existente, PTR debe ser 100 (patient_twin_available=True)."""
    from prostanet.agentic.autonomous_improvement_os import build_autonomous_improvement_bundle

    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    metrics = bundle.get("mission_control", {}).get("metrics", []) or []
    ptr = next((m for m in metrics if m.get("key") == "patient_twin_readiness"), None)
    assert ptr is not None
    assert float(ptr.get("value", 0)) == 100.0, (
        f"EPIC 19: PTR should be 100 with patient_twin_os.py present, got {ptr.get('value')}"
    )
    assert ptr.get("status") == "validated"


def test_epic19_overall_pct_rises_post_epic_19():
    """Overall mission_control debe subir post-EPIC 19 (PTR es 25% weight aprox)."""
    from prostanet.agentic.autonomous_improvement_os import build_autonomous_improvement_bundle

    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    overall = float(bundle.get("mission_control", {}).get("summary", {}).get("overall_pct", 0))
    # Pre EPIC 17b: 75.82
    # Post EPIC 17b: 76.98
    # Post EPIC 19: ≥ 78 (PTR jumps 75 → 100)
    assert overall >= 78.0, (
        f"EPIC 19: overall_pct should rise to ≥78, got {overall}"
    )
