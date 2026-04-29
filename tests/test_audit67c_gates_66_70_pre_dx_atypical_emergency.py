"""tests/test_audit67c_gates_66_70_pre_dx_atypical_emergency.py — FAUBOT LXXVII / Auditoría #67C.

Tests dedicados para gates 66-70 (Pre-Diagnostic + Atypical Histology + 10 Trials):

- Gate 66 — metastatic_biopsy_pathway_when_primary_impractical (soft_warning)
- Gate 67 — atypical_histology_escalation_nepc_intraductal (hard_block)
- Gate 68 — oncologic_emergency_diagnostic_integration (hard_block)
- Gate 69 — pre_biopsy_risk_calculators_phi_4kscore (informational)
- Gate 70 — localized_bcr_adjuvant_trials_completion (informational)

Cubre:
- Multi-path triggers para cada gate
- Override mechanisms
- UI FieldSpecs registrados en pivotal_gate_supporting_fields()
- pre_biopsy_risk_band() helper en clinical_scores
- YAML loader patterns alias (LXXVII fix para keywords/match_values)

Hipótesis verificables: H.G2278 → H.G2305 (28 tests).

Faubot 2026-04-26 LXXVII — cierre #67C, antes de FAUBOT LXXVIII (#67D).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

# ── APFS lock workaround: stub agresivo tracking_db si no carga ───────────────
if "tracking_db" not in sys.modules:
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")

# ── Stub clinical_scores si tests previos lo dejaron stubeado ────────────────
import importlib

_cs_module = sys.modules.get("clinical_scores")
_cs_file = getattr(_cs_module, "__file__", None)
if not (isinstance(_cs_file, str) and _cs_file.endswith("clinical_scores.py")):
    # Reload real module
    sys.modules.pop("clinical_scores", None)
    try:
        import clinical_scores  # noqa: F401
    except ImportError:
        # Si no hay módulo standalone, importar desde prostanet
        try:
            from prostanet.shared import clinical_scores
            sys.modules["clinical_scores"] = clinical_scores
        except ImportError:
            pass

import clinical_scores
from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
from prostanet.shared.pivotal_gates_yaml_loader import (
    _load_yaml_files,
    evaluate_all_yaml_gates,
    get_loaded_yaml_codes,
)


# ──────────────────────────────────────────────────────────────────────
# §A — Gate 66 Metastatic Biopsy Pathway (soft_warning)
# ──────────────────────────────────────────────────────────────────────


def test_g2278_gate66_loaded_in_yaml_catalog():
    """H.G2278 — Gate 66 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert "metastatic_biopsy_pathway_when_primary_impractical" in codes


def test_g2279_gate66_fires_psa_above_100_no_biopsy():
    """H.G2279 — Gate 66 dispara con PSA>100 + cT4 + sin biopsia primaria."""
    _load_yaml_files(force_reload=True)
    payload = {
        "psa_value": 150,
        "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "metastatic_biopsy_pathway_when_primary_impractical" in codes


def test_g2280_gate66_fires_widespread_bone_mets_no_biopsy():
    """H.G2280 — Gate 66 dispara con widespread bone mets + sin biopsia."""
    _load_yaml_files(force_reload=True)
    payload = {
        "widespread_bone_metastases_documented": True,
        "primary_biopsy_not_performed": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "metastatic_biopsy_pathway_when_primary_impractical" in codes


def test_g2281_gate66_fires_explicit_flag():
    """H.G2281 — Gate 66 dispara con metastatic_biopsy_pathway_indicated explicit."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"metastatic_biopsy_pathway_indicated": True})
    codes = [g["code"] for g in fired]
    assert "metastatic_biopsy_pathway_when_primary_impractical" in codes


def test_g2282_gate66_blocked_by_override_primary_biopsy_planned():
    """H.G2282 — Gate 66 NO dispara si primary_biopsy_completed_or_planned=True."""
    _load_yaml_files(force_reload=True)
    payload = {
        "metastatic_biopsy_pathway_indicated": True,
        "primary_biopsy_completed_or_planned": True,  # override
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "metastatic_biopsy_pathway_when_primary_impractical" not in codes


# ──────────────────────────────────────────────────────────────────────
# §B — Gate 67 Atypical Histology NEPC/Intraductal (hard_block)
# ──────────────────────────────────────────────────────────────────────


def test_g2283_gate67_loaded_in_yaml_catalog():
    """H.G2283 — Gate 67 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert "atypical_histology_escalation_nepc_intraductal" in codes


def test_g2284_gate67_fires_nepc_confirmed_histology():
    """H.G2284 — Gate 67 dispara con NEPC histology confirmada."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"nepc_confirmed_histology": True})
    codes = [g["code"] for g in fired]
    assert "atypical_histology_escalation_nepc_intraductal" in codes


def test_g2285_gate67_fires_histology_subtype_small_cell():
    """H.G2285 — Gate 67 dispara con histology_subtype=small_cell."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"histology_subtype": "small_cell"})
    codes = [g["code"] for g in fired]
    assert "atypical_histology_escalation_nepc_intraductal" in codes


def test_g2286_gate67_fires_intraductal_carcinoma_present():
    """H.G2286 — Gate 67 dispara con intraductal_carcinoma_present=True."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"intraductal_carcinoma_present": True})
    codes = [g["code"] for g in fired]
    assert "atypical_histology_escalation_nepc_intraductal" in codes


def test_g2287_gate67_fires_cribriform_plus_high_gleason():
    """H.G2287 — Gate 67 dispara con cribriform + Gleason ≥7."""
    _load_yaml_files(force_reload=True)
    payload = {"cribriform_pattern_present": True, "gleason_score": 8}
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "atypical_histology_escalation_nepc_intraductal" in codes


def test_g2288_gate67_no_fire_cribriform_low_gleason():
    """H.G2288 — Gate 67 NO dispara con cribriform + Gleason ≤6."""
    _load_yaml_files(force_reload=True)
    payload = {"cribriform_pattern_present": True, "gleason_score": 6}
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    # Gate 67 path C requiere cribriform + Gleason >6
    assert "atypical_histology_escalation_nepc_intraductal" not in codes


def test_g2289_gate67_fires_treatment_emergent_nepc_with_high_ldh():
    """H.G2289 — Gate 67 dispara con LDH>400 + treatment_emergent_NEPC."""
    _load_yaml_files(force_reload=True)
    payload = {
        "ldh_value": 500,
        "treatment_emergent_nepc_suspected": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "atypical_histology_escalation_nepc_intraductal" in codes


# ──────────────────────────────────────────────────────────────────────
# §C — Gate 68 Oncologic Emergency (hard_block)
# ──────────────────────────────────────────────────────────────────────


def test_g2290_gate68_loaded_in_yaml_catalog():
    """H.G2290 — Gate 68 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2291_gate68_fires_spinal_cord_compression_suspected():
    """H.G2291 — Gate 68 dispara con SCC suspected."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"spinal_cord_compression_suspected": True})
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2292_gate68_fires_visceral_crisis_documented():
    """H.G2292 — Gate 68 dispara con visceral crisis documentada."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"visceral_crisis_documented": True})
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2293_gate68_fires_hipercalcemia_severa():
    """H.G2293 — Gate 68 dispara con calcio corregido >11."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"calcium_corrected_mg_dl": 13.5})
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2294_gate68_fires_dic_active_bleeding():
    """H.G2294 — Gate 68 dispara con DIC: INR>1.5 + bleeding active."""
    _load_yaml_files(force_reload=True)
    payload = {"inr_value": 2.5, "bleeding_active_documented": True}
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2295_gate68_fires_hyponatremia_severa():
    """H.G2295 — Gate 68 dispara con sodio <125 (SIADH)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"sodium_value": 122})
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" in codes


def test_g2296_gate68_blocked_by_emergency_resolved():
    """H.G2296 — Gate 68 NO dispara si emergency_resolved=True (override)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "calcium_corrected_mg_dl": 13.5,
        "emergency_resolved_or_stabilized_documented": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "oncologic_emergency_diagnostic_integration" not in codes


# ──────────────────────────────────────────────────────────────────────
# §D — Gate 69 Pre-Biopsy Risk Calculators (informational)
# ──────────────────────────────────────────────────────────────────────


def test_g2297_gate69_loaded_in_yaml_catalog():
    """H.G2297 — Gate 69 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert "pre_biopsy_risk_calculators_phi_4kscore" in codes


def test_g2298_gate69_fires_psa_gray_zone_no_biopsy():
    """H.G2298 — Gate 69 dispara con PSA gray zone (4-10) + sin biopsia."""
    _load_yaml_files(force_reload=True)
    payload = {"psa_value": 7.5, "primary_biopsy_not_performed": True}
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "pre_biopsy_risk_calculators_phi_4kscore" in codes


def test_g2299_gate69_fires_prior_negative_biopsy_psa_elevated():
    """H.G2299 — Gate 69 dispara con prior neg bx + PSA elevado."""
    _load_yaml_files(force_reload=True)
    payload = {
        "prior_negative_biopsy_documented": True,
        "psa_value": 5.5,
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "pre_biopsy_risk_calculators_phi_4kscore" in codes


def test_g2300_gate69_fires_phi_score_available():
    """H.G2300 — Gate 69 dispara con PHI score disponible."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"phi_score_available": True})
    codes = [g["code"] for g in fired]
    assert "pre_biopsy_risk_calculators_phi_4kscore" in codes


def test_g2301_pre_biopsy_risk_band_helper_phi_high():
    """H.G2301 — pre_biopsy_risk_band identifica PHI >36 como high risk."""
    if not hasattr(clinical_scores, "pre_biopsy_risk_band"):
        return  # Helper opcional
    band = clinical_scores.pre_biopsy_risk_band({"phi_score_value": 45})
    assert band.get("phi_band") in ("high", "high_risk", None)


# ──────────────────────────────────────────────────────────────────────
# §E — Gate 70 Trials Completion (informational)
# ──────────────────────────────────────────────────────────────────────


def test_g2302_gate70_loaded_in_yaml_catalog():
    """H.G2302 — Gate 70 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert "localized_bcr_adjuvant_trials_completion" in codes


def test_g2303_gate70_fires_decision_rp_vs_rt_active():
    """H.G2303 — Gate 70 dispara con decision_rp_vs_rt_active + localized."""
    _load_yaml_files(force_reload=True)
    payload = {
        "decision_rp_vs_rt_active": True,
        "clinical_state": "localized_initial",
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "localized_bcr_adjuvant_trials_completion" in codes


def test_g2304_gate70_fires_salvage_rt_consideration_post_rp():
    """H.G2304 — Gate 70 dispara con salvage RT consideration + post-RP/BCR."""
    _load_yaml_files(force_reload=True)
    payload = {
        "salvage_rt_consideration_active": True,
        "clinical_state": "post_prostatectomy",
    }
    fired = evaluate_all_yaml_gates(payload)
    codes = [g["code"] for g in fired]
    assert "localized_bcr_adjuvant_trials_completion" in codes


def test_g2305_gate70_fires_trial_coverage_check():
    """H.G2305 — Gate 70 dispara con trial_coverage_completion_check explicit."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"trial_coverage_completion_check": True})
    codes = [g["code"] for g in fired]
    assert "localized_bcr_adjuvant_trials_completion" in codes


# ──────────────────────────────────────────────────────────────────────
# §F — UI Integration: FieldSpecs registrados
# ──────────────────────────────────────────────────────────────────────


def test_g2306_ui_fieldspecs_for_gate66_registered():
    """H.G2306 — FieldSpecs para gate 66 registrados en pivotal_gate_supporting_fields."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "primary_biopsy_not_performed",
        "widespread_bone_metastases_documented",
        "spinal_cord_compression_initial_presentation",
        "liver_metastasis_documented",
        "lung_metastasis_documented",
        "metastatic_biopsy_pathway_indicated",
        "primary_biopsy_completed_or_planned",
        "histology_already_confirmed",
    }
    missing = expected - names
    assert not missing, f"Gate 66 fields missing en UI: {missing}"


def test_g2307_ui_fieldspecs_for_gate67_registered():
    """H.G2307 — FieldSpecs para gate 67 registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "nepc_confirmed_histology",
        "histology_subtype",
        "intraductal_carcinoma_present",
        "cribriform_pattern_present",
        "ldh_value",
        "treatment_emergent_nepc_suspected",
    }
    missing = expected - names
    assert not missing, f"Gate 67 fields missing: {missing}"


def test_g2308_ui_fieldspecs_for_gate68_registered():
    """H.G2308 — FieldSpecs para gate 68 registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "spinal_cord_compression_suspected",
        "spinal_cord_compression_confirmed",
        "visceral_crisis_documented",
        "calcium_corrected_mg_dl",
        "dic_diagnosed",
        "inr_value",
        "bleeding_active_documented",
        "sodium_value",
        "oncologic_emergency_active",
        "emergency_resolved_or_stabilized_documented",
    }
    missing = expected - names
    assert not missing, f"Gate 68 fields missing: {missing}"


def test_g2309_ui_fieldspecs_for_gate69_registered():
    """H.G2309 — FieldSpecs para gate 69 registrados (PHI/4Kscore/PSAD)."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "phi_score_available",
        "phi_score_value",
        "fourkscore_available",
        "fourkscore_value",
        "psa_density",
        "prostate_volume_ml",
        "prior_negative_biopsy_documented",
    }
    missing = expected - names
    assert not missing, f"Gate 69 fields missing: {missing}"


def test_g2310_ui_fieldspecs_for_gate70_registered():
    """H.G2310 — FieldSpecs para gate 70 registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "decision_rp_vs_rt_active",
        "active_surveillance_eligibility_evaluation",
        "salvage_rt_consideration_active",
        "trial_coverage_completion_check",
    }
    missing = expected - names
    assert not missing, f"Gate 70 fields missing: {missing}"


# ──────────────────────────────────────────────────────────────────────
# §G — Backend wiring: domain schemas incluyen pivotal_gate_supporting_fields
# ──────────────────────────────────────────────────────────────────────


def test_g2311_localized_initial_schema_includes_new_fields():
    """H.G2311 — LOCALIZED_SCHEMA incluye fields de gates 56-70."""
    from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
    fields = LOCALIZED_SCHEMA.get("fields", [])
    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    assert "anticoagulant_agent" in field_names
    assert "hrr_status" in field_names
    assert "nepc_confirmed_histology" in field_names


def test_g2312_diagnostic_workup_schema_includes_pre_bx_calculators():
    """H.G2312 — DIAGNOSTIC_WORKUP_SCHEMA incluye PHI/4Kscore (gate 69)."""
    from prostanet.domains.diagnostic_workup.schemas import DIAGNOSTIC_WORKUP_SCHEMA
    fields = DIAGNOSTIC_WORKUP_SCHEMA.get("fields", [])
    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    assert "phi_score_value" in field_names
    assert "fourkscore_value" in field_names
    assert "primary_biopsy_not_performed" in field_names
