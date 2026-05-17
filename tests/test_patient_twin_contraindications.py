"""BUG FIX 2026-05-17 — Patient Twin OS contraindication awareness.

Pre-fix: ranking ciego a pivotal_contraindication_gates → mostraba
abiraterona #1 (score 10.0) incluso con ALT 6.2× LSN (G07 hard_block),
contradiciendo el banner de seguridad clínica.

Post-fix: `_apply_contraindications` marca regímenes con
is_contraindicated=True + razón clínica + sinks score a -1.0 para
hard_block (van al final del ranking, transparencia preservada).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def base_patient_record():
    return {
        "identity": {"id": 999, "nss": "TEST-CONTRA-001", "full_name": "Test Patient"},
        "baseline": {"clinical_state": "mcspc_low_volume_sync_oligo"},
        "latest_assessment": {"state": "mcspc_low_volume_sync_oligo"},
        "patient_clinical_facts": [],
    }


class TestHepaticContraindication:
    """G07 — Abiraterona contraindicada por hepatotoxicidad."""

    def test_alt_above_120_marks_abi_contraindicated(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["alt"] = 250.0  # 6.2× LSN
        twin = build_patient_twin_view(p)
        rankings = twin.get("regimen_rankings", [])
        abi = next((r for r in rankings if "abirat" in str(r.get("regimen_name")).lower()), None)
        assert abi is not None
        assert abi["is_contraindicated"] is True
        assert abi["contraindication_severity"] == "hard_block"
        assert abi["contraindication_gate_id"] == "G07"
        assert "hepatotox" in abi["contraindication_reason"].lower() or "alt" in abi["contraindication_reason"].lower()
        assert abi["score"] == -1.0

    def test_ast_above_120_also_marks_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["ast"] = 200.0
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True

    def test_active_liver_disease_marks_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["active_liver_disease"] = "1"
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True

    def test_normal_lfts_does_not_mark_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["alt"] = 25.0
        p["baseline"]["ast"] = 30.0
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is False

    def test_abi_score_minus_one_sinks_to_bottom(self, base_patient_record):
        """Verify hard_block contraindication makes abi rank LAST."""
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["alt"] = 300.0
        twin = build_patient_twin_view(p)
        rankings = twin["regimen_rankings"]
        last_regimen = rankings[-1]
        assert "abirat" in str(last_regimen["regimen_name"]).lower()
        assert last_regimen["score"] == -1.0
        # No first-ranked regimen should be abiraterone
        assert "abirat" not in str(rankings[0]["regimen_name"]).lower()


class TestCardiovascularContraindication:
    """G54 — Abiraterona contraindicada por enfermedad CV severa."""

    def test_nyha_iv_marks_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["nyha_class"] = "IV"
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True
        assert abi["contraindication_gate_id"] == "G54"

    def test_severe_cv_disease_marks_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["severe_cv_disease"] = "1"
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True

    def test_lvef_below_40_marks_abi(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["ejection_fraction_baseline"] = 25.0
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True


class TestSeizureContraindication:
    """Enzalutamida contraindicada por historia de convulsiones (AFFIRM exclusion)."""

    def test_seizure_history_marks_enza(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["seizure_history"] = "1"
        twin = build_patient_twin_view(p)
        enza = next((r for r in twin["regimen_rankings"] if "enzalut" in str(r["regimen_name"]).lower()), None)
        assert enza["is_contraindicated"] is True
        assert enza["contraindication_severity"] == "hard_block"


class TestCognitiveSoftWarning:
    """Enzalutamida soft warning por deterioro cognitivo (no hard_block)."""

    def test_cognitive_impairment_soft_marks_enza(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["cognitive_impairment_documented"] = "1"
        twin = build_patient_twin_view(p)
        enza = next((r for r in twin["regimen_rankings"] if "enzalut" in str(r["regimen_name"]).lower()), None)
        assert enza["is_contraindicated"] is True
        assert enza["contraindication_severity"] == "soft_warning"
        # Soft warning: score NOT sunk to -1
        assert enza["score"] >= 0


class TestArbiterPropagation:
    """EPIC 23 Recommendation Arbiter pre-computed exclusions also respected."""

    def test_arbiter_exclusion_propagates(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["arbitrated_exclusions"] = {
            "abiraterone": {
                "severity": "hard_block",
                "reason": "Arbiter detectó conflict crítico custom",
                "gate_id": "EPIC23-CUSTOM",
            }
        }
        twin = build_patient_twin_view(p)
        abi = next((r for r in twin["regimen_rankings"] if "abirat" in str(r["regimen_name"]).lower()), None)
        assert abi["is_contraindicated"] is True
        assert "Arbiter" in abi["contraindication_reason"]


class TestTransparencyPreserved:
    """Contraindicated regimens REMAIN in the ranking list (transparency for clinician).
    No silent filtering."""

    def test_contraindicated_regimens_not_removed(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        p = dict(base_patient_record)
        p["baseline"] = dict(p["baseline"])
        p["baseline"]["alt"] = 300.0
        twin = build_patient_twin_view(p)
        rankings = twin["regimen_rankings"]
        # 7 regimens in catalog — all should still be present
        assert len(rankings) >= 6
        abi_present = any("abirat" in str(r["regimen_name"]).lower() for r in rankings)
        assert abi_present, "Abiraterona debe seguir visible en la lista (transparencia clínica), aunque marcada contraindicada"


class TestRegressionNoContraindication:
    """Pacientes sin contraindicaciones siguen funcionando igual que pre-fix."""

    def test_clean_patient_no_contraindications(self, base_patient_record):
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        twin = build_patient_twin_view(base_patient_record)
        rankings = twin["regimen_rankings"]
        contra = [r for r in rankings if r.get("is_contraindicated")]
        assert len(contra) == 0
        # Score normal positive
        assert all(r["score"] >= 0 for r in rankings)
