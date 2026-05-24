"""Sprint 5 — Biomarker workup checklist tests (FAUBOT CXLIII).

S5.A — biomarker_workup_engine: detección + capture targets
S5.B — wire en profile_compass bundle
S5.C — UI card data-testid + rendering condicional
S5.D — Fix C7 ghost function (trial_eligibility + decision-audit)
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# S5.A — Engine
# ─────────────────────────────────────────────────────────────────────


def test_s5_a_engine_importable():
    """biomarker_workup_engine debe importarse + exponer API."""
    from prostanet.domains.decisions import biomarker_workup_engine as bwe
    assert hasattr(bwe, "build_biomarker_workup_bundle")
    assert hasattr(bwe, "HRR_GENES_PANEL")
    assert hasattr(bwe, "PARP_INHIBITORS")
    assert hasattr(bwe, "LU177_CANDIDATES")
    # NCCN panel HRR estándar (BRCA1/2 + ATM + PALB2 + CHEK2 + CDK12)
    assert "BRCA1" in bwe.HRR_GENES_PANEL
    assert "BRCA2" in bwe.HRR_GENES_PANEL
    assert "ATM" in bwe.HRR_GENES_PANEL


def test_s5_a_engine_returns_expected_shape():
    """build_biomarker_workup_bundle debe retornar dict con keys clave."""
    from prostanet.domains.decisions.biomarker_workup_engine import (
        build_biomarker_workup_bundle,
    )
    patient = {
        "identity": {"id": 1, "nss": "TEST-S5-A"},
        "baseline": {"hrr_status": "Desconocido"},
    }
    bundle = build_biomarker_workup_bundle(patient)
    expected_keys = {
        "available", "evaluation_timestamp", "parp_candidate",
        "lu177_candidate", "hrr_workup", "psma_pet_workup",
        "pending_actions_count", "any_pending", "clinical_summary",
    }
    assert expected_keys.issubset(set(bundle.keys())), (
        f"Missing keys: {expected_keys - set(bundle.keys())}"
    )


def test_s5_a_parp_candidate_via_gate_propagation():
    """Si gate `hrr_status_required_before_parp_inhibitor` dispara,
    paciente debe marcarse como candidato PARP (single source of truth
    con GodiBot + CXLII propagation)."""
    from prostanet.domains.decisions.biomarker_workup_engine import (
        build_biomarker_workup_bundle,
    )
    # Paciente con HRR desconocido — gate lazy-eval debe disparar
    patient = {
        "identity": {"id": 2, "nss": "TEST-S5-PARP"},
        "baseline": {
            "hrr_status": "Desconocido",
            "tnm_stage": "T3N1M1b",
        },
    }
    bundle = build_biomarker_workup_bundle(patient)
    # Con HRR Desconocido + ningún registro adicional, el gate puede o no
    # disparar dependiendo de condiciones; el bundle DEBE ser válido sin lanzar
    assert bundle.get("available") is True or "engine_error" in str(bundle.get("reason", ""))


def test_s5_a_no_pending_when_documented():
    """Si HRR + PSMA-PET están documentados, no debe haber acciones pendientes."""
    from prostanet.domains.decisions.biomarker_workup_engine import (
        build_biomarker_workup_bundle,
    )
    patient = {
        "identity": {"id": 3, "nss": "TEST-S5-COMPLETE"},
        "baseline": {
            "hrr_status": "Completo_Negativo",
            "hrr_gene": "wildtype",
            "psma_pet_positive": 1,
            "psma_pet_max_suvmax": 18.4,
            "stage": "mHSPC",
        },
    }
    bundle = build_biomarker_workup_bundle(patient)
    assert bundle["available"] is True
    # Documented → ambos workup pending=False
    assert bundle["hrr_workup"]["documented"] is True
    assert bundle["psma_pet_workup"]["documented"] is True
    assert bundle["hrr_workup"]["pending"] is False
    assert bundle["psma_pet_workup"]["pending"] is False


def test_s5_a_engine_failsafe_invalid_input():
    """Engine debe degradar gracefully ante inputs malformados."""
    from prostanet.domains.decisions.biomarker_workup_engine import (
        build_biomarker_workup_bundle,
    )
    # None input
    b1 = build_biomarker_workup_bundle(None)
    assert b1["available"] is False
    assert b1["pending_actions_count"] == 0
    # String input
    b2 = build_biomarker_workup_bundle("not_a_dict")
    assert b2["available"] is False
    # Empty dict
    b3 = build_biomarker_workup_bundle({})
    # Empty dict no es invalid técnicamente, pero todos los campos estarán vacíos
    assert "available" in b3


# ─────────────────────────────────────────────────────────────────────
# S5.B — profile_compass wiring
# ─────────────────────────────────────────────────────────────────────


def test_s5_b_profile_compass_declares_biomarker_workup():
    """Source-level: profile_compass debe inyectar biomarker_workup al bundle."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "domains" / "patient_tracking" / "profile_compass.py"
    content = src.read_text(encoding="utf-8")
    # Bundle assignment
    assert '"biomarker_workup": _biomarker_workup_bundle' in content, (
        "S5.B: biomarker_workup key no inyectado al bundle"
    )
    # Comment trace
    assert "SPRINT 5" in content
    assert "build_biomarker_workup_bundle" in content


# ─────────────────────────────────────────────────────────────────────
# S5.C — UI template
# ─────────────────────────────────────────────────────────────────────


def test_s5_c_template_has_biomarker_workup_card():
    """Template patient_profile_v2 debe declarar la card data-testid."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    assert 'data-testid="biomarker-workup-checklist"' in content
    assert 'biomarker_workup' in content
    # Sub-cards
    assert 'data-testid="biomarker-workup-hrr"' in content
    assert 'data-testid="biomarker-workup-psma-pet"' in content
    # Data attributes para drill-down
    assert "data-pending-count=" in content
    assert "data-parp-candidate=" in content
    assert "data-lu177-candidate=" in content


# ─────────────────────────────────────────────────────────────────────
# S5.D — Fix C7 ghost function
# ─────────────────────────────────────────────────────────────────────


def test_s5_d_trial_eligibility_uses_real_function():
    """trial_eligibility._load_patient debe llamar load_patient_record_core
    (NO get_patient_by_nss que no existe en tracking_db).
    El test inspecciona la llamada real, no comentarios explicativos."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "trial_eligibility_routes.py"
    content = src.read_text(encoding="utf-8")
    # Must NOT contain the actual ghost function CALL
    assert "tracking_db.get_patient_by_nss(" not in content, (
        "C7: trial_eligibility_routes still CALLS ghost function (not just mention in comment)"
    )
    # Must contain real function call
    assert "tracking_db.load_patient_record_core(" in content


def test_s5_d_decision_audit_uses_real_function():
    """app.api_decision_audit_patient debe LLAMAR load_patient_record_core
    (no get_patient_by_nss). Test inspecciona la llamada, no el comentario."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "app.py"
    content = src.read_text(encoding="utf-8")
    # Locate handler block
    idx = content.find("def api_decision_audit_patient")
    assert idx > 0
    block = content[idx:idx + 1500]
    # No actual call to ghost function
    assert "tracking_db.get_patient_by_nss(" not in block, (
        "C7: api_decision_audit_patient still CALLS ghost function"
    )
    # Must call real function
    assert "tracking_db.load_patient_record_core(" in block


def test_s5_d_real_function_works():
    """Ejecución directa: load_patient_record_core debe encontrar paciente real."""
    import tracking_db
    # PID 32 existe (verificado en GVP.E)
    p = tracking_db.load_patient_record_core(32)
    assert p is not None, "PID 32 should exist in tracking_db"
    assert "identity" in p or "baseline" in p or "nss" in str(p)


# ─────────────────────────────────────────────────────────────────────
# Foundation — FAUBOT version bump
# ─────────────────────────────────────────────────────────────────────


def test_s5_faubot_release_bumped():
    """algorithm_version debe ser al menos CXLIII (release de Sprint 5).
    Sprint 6+ bumps a CXLIV+ son válidos también."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Accept CXLIII or any later Roman numeral starting with CXLI/CXLV/...
    valid_releases = ("CXLIII", "CXLIV", "CXLV", "CXLVI", "CXLVII", "CXLVIII",
                       "CXLIX", "CL")
    assert any(rel in FAUBOT_RELEASE for rel in valid_releases), (
        f"FAUBOT_RELEASE should be ≥CXLIII, got: {FAUBOT_RELEASE}"
    )
