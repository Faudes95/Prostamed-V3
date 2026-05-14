# IEC 62304 §5.7 — EPIC 20 Phase 1 Fase B+D+E
"""Tests EPIC 20 Fase B (micro-forms) + Fase D (5 copilots) + Fase E (UI cards).

Verifica:
  Fase B:
    - 6 micro-forms registrados
    - Field count clínicamente validado (11-14 fields/form)
    - voice_required_confidence declarado per field
    - clinical_validation rationale presente
  Fase D:
    - 5 copilot services importables
    - Cada uno retorna bundle con available + therapeutic_preferred
    - Self-gating cuando patient no qualifica (available=False)
  Fase E:
    - patient_profile_v2.html contiene 5 data-testid para nuevas cards
    - Cards condicionales (renderan solo cuando bundle.available)
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────── Fase B — Micro-forms ───────────────────


def test_epic20_fase_b_six_microforms_registered():
    """MOMENT_CAPTURE_SCHEMAS includes the original 6 EPIC 20 micro-forms.

    EPIC 22b.2 added `biopsy_capture` (7th moment) to close the documented
    histopathology capture gap. The contract is now "at least 6, must include
    the original EPIC 20 moments" so future micro-forms can be appended
    without breaking this regression gate.
    """
    from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS
    original_six = {
        "bcr_detection", "oligoprogression", "crpc_transition",
        "adt_init", "rt_nadir", "salvage_eligibility",
    }
    actual = set(MOMENT_CAPTURE_SCHEMAS.keys())
    assert original_six.issubset(actual), (
        f"EPIC 20 original moments lost: missing={original_six - actual}"
    )
    assert len(actual) >= 6


def test_epic20_fase_b_field_counts_clinically_validated():
    """Cada micro-form debe tener 8-14 fields (NCCN-validated, sin data loss clínico)."""
    from prostanet.shared.moment_capture_schemas import get_field_count_reduction, MOMENT_CAPTURE_SCHEMAS
    for moment in MOMENT_CAPTURE_SCHEMAS:
        r = get_field_count_reduction(moment)
        assert 8 <= r["micro_form_fields"] <= 14, (
            f"{moment}: {r['micro_form_fields']} fields outside clinically safe range 8-14"
        )
        # Reduction must be ≥56% (median target) — sin compromiso clínico
        assert r["reduction_pct"] >= 56.0, (
            f"{moment}: reduction {r['reduction_pct']}% below 56% minimum"
        )


def test_epic20_fase_b_voice_required_confidence_per_field():
    """Cada field debe declarar voice_required_confidence (0.0-1.0)."""
    from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS
    for moment, form in MOMENT_CAPTURE_SCHEMAS.items():
        for f in form.fields:
            assert 0.0 <= f.voice_required_confidence <= 1.0, (
                f"{moment}.{f.name}: voice_required_confidence {f.voice_required_confidence} invalid"
            )


def test_epic20_fase_b_clinical_validation_rationale_present():
    """Cada micro-form debe documentar clinical_validation con NCCN 2026 reference."""
    from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS
    for moment, form in MOMENT_CAPTURE_SCHEMAS.items():
        cv = form.clinical_validation
        assert "must_capture_rationale" in cv
        assert "deferred_fields_safe_because" in cv
        assert "nccn_2026_reference" in cv or "phoenix_consensus" in cv


def test_epic20_fase_b_voice_targets_exportable_for_epic21():
    """get_voice_targets_for_intent_extractor() debe export per-field targets."""
    from prostanet.shared.moment_capture_schemas import get_voice_targets_for_intent_extractor
    targets = get_voice_targets_for_intent_extractor()
    # 6 forms × ~11 fields avg = ~66 targets
    assert len(targets) >= 60, f"Expected ≥60 voice targets, got {len(targets)}"
    # Sample target has expected fields
    t = targets[0]
    for k in ("moment", "field_name", "label", "type", "confidence_threshold", "required"):
        assert k in t


# ─────────────────── Fase D — Copilot services ───────────────────


def test_epic20_fase_d_mcrpc_subtype_copilot_imports():
    from prostanet.domains.patient_tracking.mcrpc_subtype_copilot_service import (
        build_mcrpc_subtype_bundle,
    )
    assert callable(build_mcrpc_subtype_bundle)


def test_epic20_fase_d_mcrpc_subtype_returns_hrr_subtype():
    """HRR+ PARP-naive case → mcrpc_hrr_positive_parp_naive bundle."""
    from prostanet.domains.patient_tracking.mcrpc_subtype_copilot_service import build_mcrpc_subtype_bundle
    bundle = build_mcrpc_subtype_bundle({
        "castration_resistance_confirmed": True,
        "bone_lesion_count_total": 5,
        "hrr_status": "positive",
        "parp_inhibitor_received": False,
    })
    assert bundle["available"] is True
    assert bundle["subtype_state"] == "mcrpc_hrr_positive_parp_naive"
    assert "parp" in bundle["therapeutic_preferred"].lower()
    assert "PROfound" in bundle["pivotal_trials_supporting"]


def test_epic20_fase_d_mcrpc_subtype_self_gates_when_not_crpc():
    """Sin castration_resistance_confirmed → available=False."""
    from prostanet.domains.patient_tracking.mcrpc_subtype_copilot_service import build_mcrpc_subtype_bundle
    bundle = build_mcrpc_subtype_bundle({"bone_lesion_count_total": 0})
    assert bundle["available"] is False


def test_epic20_fase_d_risk_stratified_localized_imports():
    from prostanet.domains.patient_tracking.risk_stratified_localized_copilot_service import (
        build_risk_stratified_localized_bundle,
    )
    assert callable(build_risk_stratified_localized_bundle)


def test_epic20_fase_d_risk_stratified_returns_very_low():
    """Very low risk case → very_low_risk_localized + AS preferred."""
    from prostanet.domains.patient_tracking.risk_stratified_localized_copilot_service import build_risk_stratified_localized_bundle
    bundle = build_risk_stratified_localized_bundle({
        "baseline_psa": 6, "gleason_score": 6, "clinical_t_stage": "cT1c",
        "percent_positive_cores": 20, "psa_density": 0.10,
    })
    assert bundle["available"] is True
    assert "very_low" in bundle["risk_tier"]
    assert "active_surveillance" in bundle["therapeutic_preferred"]
    assert "PRIAS" in bundle["pivotal_trials_supporting"]


def test_epic20_fase_d_hereditary_germline_triggers_metastatic():
    """Metastatic patient + family hx → hereditary umbrella triggered."""
    from prostanet.domains.patient_tracking.hereditary_germline_copilot_service import build_hereditary_germline_bundle
    bundle = build_hereditary_germline_bundle({
        "bone_lesion_count_total": 3,
        "family_history_breast_ovary_pancreas": True,
        "germline_testing_done": False,
    })
    assert bundle["available"] is True
    assert bundle["testing_indicated"] is True
    assert "germline" in bundle["therapeutic_preferred"].lower()
    assert "BRCA2" in bundle["surveillance_if_carrier"]


def test_epic20_fase_d_post_rt_bcr_phoenix_detection():
    """Post-RT + Phoenix criteria → post_rt_bcr bundle with NO salvage RT recommendation."""
    from prostanet.domains.patient_tracking.post_rt_bcr_copilot_service import build_post_rt_bcr_bundle
    bundle = build_post_rt_bcr_bundle({
        "prior_rt_received": True,
        "nadir_psa_post_rt": 0.5,
        "current_psa": 3.0,
    })
    assert bundle["available"] is True
    assert bundle["phoenix_criteria_met"] is True
    assert "biopsy" in str(bundle["workup_required"]).lower()
    # Critical: NO salvage RT a fossa
    not_recommended = " ".join(bundle["therapeutic_not_recommended"]).lower()
    assert "salvage rt a fossa" in not_recommended or "repeat full-dose" in not_recommended


def test_epic20_fase_d_oligoprogression_mdt_recommendation():
    """Oligo (≤3 lesions) + continued response → MDT preferred over class switch."""
    from prostanet.domains.patient_tracking.oligoprogression_copilot_service import build_oligoprogression_bundle
    bundle = build_oligoprogression_bundle({
        "progressing_on_systemic_therapy": True,
        "new_lesion_count_since_last_imaging": 2,
        "response_in_existing_lesions": "continued_response",
    })
    assert bundle["available"] is True
    assert bundle["eligible_for_mdt"] is True
    assert "STOMP" in bundle["pivotal_trials_supporting"]
    not_rec = " ".join(bundle["therapeutic_not_recommended"]).lower()
    assert "class switch" in not_rec or "abandon" in not_rec


def test_epic20_fase_d_oligoprogression_rejects_widespread():
    """≥4 new lesions → eligible_for_mdt=False, class switch preferred."""
    from prostanet.domains.patient_tracking.oligoprogression_copilot_service import build_oligoprogression_bundle
    bundle = build_oligoprogression_bundle({
        "progressing_on_systemic_therapy": True,
        "new_lesion_count_since_last_imaging": 5,
        "response_in_existing_lesions": "stable",
    })
    assert bundle["available"] is True
    assert bundle["eligible_for_mdt"] is False
    assert "class_switch" in bundle["therapeutic_preferred"]


# ─────────────────── Fase E — UI cards en v2 template ───────────────────


def test_epic20_fase_e_v2_template_includes_all_5_copilot_cards():
    """patient_profile_v2.html debe tener data-testid para los 5 EPIC 20 cards."""
    template = (PROJECT_ROOT / "templates" / "patient_profile_v2.html").read_text(encoding="utf-8")
    expected_test_ids = [
        "risk-stratified-localized-card",
        "mcrpc-subtype-card",
        "hereditary-germline-card",
        "post-rt-bcr-card",
        "oligoprogression-card",
    ]
    for tid in expected_test_ids:
        assert f'data-testid="{tid}"' in template, f"Missing card testid: {tid}"


def test_epic20_fase_e_v2_template_cards_conditional_on_available():
    """Cada card debe estar wrapped en {% if X.available %}."""
    template = (PROJECT_ROOT / "templates" / "patient_profile_v2.html").read_text(encoding="utf-8")
    conditional_patterns = [
        "{% if risk_stratified_localized and risk_stratified_localized.available %}",
        "{% if mcrpc_subtype and mcrpc_subtype.available %}",
        "{% if hereditary_germline and hereditary_germline.available %}",
        "{% if post_rt_bcr and post_rt_bcr.available %}",
        "{% if oligoprogression and oligoprogression.available %}",
    ]
    for pattern in conditional_patterns:
        assert pattern in template, f"Missing conditional: {pattern}"


def test_epic20_fase_e_app_py_wires_all_5_copilots():
    """app.py debe importar y llamar a los 5 build_*_bundle functions."""
    app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    expected_imports = [
        "build_risk_stratified_localized_bundle",
        "build_mcrpc_subtype_bundle",
        "build_hereditary_germline_bundle",
        "build_post_rt_bcr_bundle",
        "build_oligoprogression_bundle",
    ]
    for imp in expected_imports:
        assert imp in app_py, f"Missing import/wire: {imp}"


def test_epic20_fase_e_app_py_initializes_with_unavailable_default():
    """app.py debe inicializar v2_ctx['<copilot>'] = {'available': False} antes de try."""
    app_py = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    expected_defaults = [
        'v2_ctx["risk_stratified_localized"] = {"available": False}',
        'v2_ctx["mcrpc_subtype"] = {"available": False}',
        'v2_ctx["hereditary_germline"] = {"available": False}',
        'v2_ctx["post_rt_bcr"] = {"available": False}',
        'v2_ctx["oligoprogression"] = {"available": False}',
    ]
    for default in expected_defaults:
        assert default in app_py, f"Missing default initialization: {default}"
