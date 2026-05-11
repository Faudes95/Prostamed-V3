"""tests/test_audit_lxxxiv_subspecialty_pre_dx.py — FAUBOT LXXXIV Iter #1.

Tests para Iteración #1 — Subspecialty Coverage + Pre-Dx Scenarios:

1. **3 nuevos gates YAML** (67B, 67C, 69B) cargan + disparan correctamente
2. **clinical_subspecialty_engine.py** retorna acciones priorizadas correctas
   para los 2 escenarios verbatim del usuario:
   - TR T4 + APE 100 sin RHP
   - APE 5000 + TR T4 fija + síntomas SCC + LDH 450
3. **recommend_flare_protection()** retorna protocolo correcto (degarelix
   si SCC, LHRH+bicalutamide si bulk, standard si low burden)
4. **FieldSpecs nuevos** (21 fields) registrados en helper
5. **2 stages nuevos UI v2** (subspecialty_pre_dx_decisions + mdt_genomic_hereditary)
6. **Coverage 100% mantenido** post-LXXXIV (404/404 fields helper en UI)
7. **88 gates loaded total** (85 + 3 nuevos LXXXIV)

HIPÓTESIS: H.G2730 → H.G2759 (~30 tests).

Faubot LXXXIV — cierre Iteración #1 antes de Iteración #2 (47 trials).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types
from pathlib import Path

# APFS lock workaround
if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")


ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")


# ──────────────────────────────────────────────────────────────────────
# §A — 3 nuevos gates YAML (67B, 67C, 69B)
# ──────────────────────────────────────────────────────────────────────


def test_g2730_gate_67b_loaded():
    """H.G2730 — Gate 67B (NEPC pre-biopsy) loaded en YAML catalog."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "nepc_pre_biopsy_risk_suspicion" in get_loaded_yaml_codes()


def test_g2731_gate_67c_loaded():
    """H.G2731 — Gate 67C (cT4 sin biopsia hard_block) loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "ct4_requires_histology_confirmation" in get_loaded_yaml_codes()


def test_g2732_gate_69b_loaded():
    """H.G2732 — Gate 69B (PSA velocity pre-biopsia) loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "psa_velocity_pre_biopsy_urgent" in get_loaded_yaml_codes()


def test_g2733_total_88_gates_loaded():
    """H.G2733 — Total ≥88 gates loaded (85 + 3 LXXXIV; LXXXIV.b agrega gate 55B → ≥89)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    # Faubot LXXXIV.b: gate 55B nuevo (PSMA-PET nmCRPC) lleva total a 89.
    # Aserción ≥88 mantiene compatibilidad y permite crecimiento futuro.
    assert len(get_loaded_yaml_codes()) >= 88


def test_g2734_gate_67b_fires_with_ldh_psa_visceral():
    """H.G2734 — Gate 67B dispara con LDH ≥400 + PSA ≥1000 + visceral mets."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "ldh_value": 500, "psa_value": 1500,
        "liver_metastasis_documented": True,
    })
    codes = [g["code"] for g in fired]
    assert "nepc_pre_biopsy_risk_suspicion" in codes


def test_g2735_gate_67c_fires_with_ct4_no_biopsy_active_decision():
    """H.G2735 — Gate 67C hard_block dispara con cT4 + sin biopsia + decisión activa."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
        "decision_rp_vs_rt_active": True,
    })
    codes = [g["code"] for g in fired]
    assert "ct4_requires_histology_confirmation" in codes


def test_g2736_gate_67c_blocked_by_override_histology_metastatic():
    """H.G2736 — Gate 67C NO dispara si histology_confirmed_metastatic_site=True."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
        "decision_rp_vs_rt_active": True,
        "histology_confirmed_metastatic_site": True,
    })
    codes = [g["code"] for g in fired]
    assert "ct4_requires_histology_confirmation" not in codes


def test_g2737_gate_69b_fires_with_high_psa_velocity():
    """H.G2737 — Gate 69B dispara con PSAv ≥20 + sin biopsia + sin RP/RT previa."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "psa_velocity_ng_ml_year": 25,
        "primary_biopsy_not_performed": True,
    })
    codes = [g["code"] for g in fired]
    assert "psa_velocity_pre_biopsy_urgent" in codes


def test_g2738_gate_69b_path_b_fires_psa_velocity_2_with_high_psa():
    """H.G2738 — Gate 69B Path B dispara con PSAv ≥2 + PSA ≥10 + sin biopsia."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "psa_velocity_ng_ml_year": 5, "psa_value": 15,
        "primary_biopsy_not_performed": True,
    })
    codes = [g["code"] for g in fired]
    assert "psa_velocity_pre_biopsy_urgent" in codes


# ──────────────────────────────────────────────────────────────────────
# §B — clinical_subspecialty_engine.py
# ──────────────────────────────────────────────────────────────────────


def test_g2739_subspecialty_engine_imports():
    """H.G2739 — clinical_subspecialty_engine.py importa sin errores."""
    from prostanet.shared.clinical_subspecialty_engine import (
        recommend_next_clinical_action,
        recommend_flare_protection,
        summarize_subspecialty_recommendations,
        ClinicalAction,
    )
    assert callable(recommend_next_clinical_action)
    assert callable(recommend_flare_protection)


def test_g2740_caso_usuario_tr_t4_psa_100():
    """H.G2740 — Caso usuario verbatim 1: TR T4 + APE 100 sin RHP.

    Espera acciones: biopsia primaria transperineal urgente + workup extensión + MDT.
    """
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    case1 = {
        "psa_value": 100,
        "clinical_t_stage": "cT4",
        "dre_fixation": "Confirmada",
        "primary_biopsy_not_performed": True,
        "ecog_current": 1,
    }
    actions = recommend_next_clinical_action(case1)
    assert len(actions) >= 3
    # Top action debe ser biopsia primaria transperineal
    titles = [a.title for a in actions]
    assert any("biopsia" in t.lower() and "transperineal" in t.lower() for t in titles)
    # Workup extensión
    assert any("workup extensión" in t.lower() or "extensión" in t.lower() for t in titles)
    # MDT review
    assert any("mdt" in t.lower() for t in titles)


def test_g2741_caso_usuario_psa_5000_t4_scc():
    """H.G2741 — Caso usuario verbatim 2: APE 5000 + T4 fija + SCC + bulk + LDH 450.

    Espera: emergency-first + dexametasona + RM emergency + biopsia metastásica
    + workup NEPC + ADT empírico con flare protection (degarelix).
    """
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    case2 = {
        "psa_value": 5000,
        "clinical_t_stage": "cT4",
        "dre_fixation": "Confirmada",
        "primary_biopsy_not_performed": True,
        "spinal_cord_compression_suspected": True,
        "widespread_bone_metastases_documented": True,
        "liver_metastasis_documented": True,
        "ldh_value": 450,
        "ecog_current": 2,
    }
    actions = recommend_next_clinical_action(case2)
    assert len(actions) >= 5

    titles = [a.title.lower() for a in actions]
    # Emergency-first
    assert any("emergency" in t for t in titles)
    # Dexametasona
    assert any("dexametasona" in t for t in titles)
    # RM emergency
    assert any("rm columna" in t or "spine mri" in t for t in titles)
    # Biopsia metastásica urgente
    assert any("metastásica urgente" in t or "metastásica" in t for t in titles)
    # NEPC workup
    assert any("nepc" in t for t in titles)
    # ADT empírico con flare protection (degarelix por SCC)
    assert any("adt empírico" in t or "flare" in t for t in titles)


def test_g2742_top_action_emergency_when_scc():
    """H.G2742 — SCC suspect → top action priority=1 emergency-first."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    actions = recommend_next_clinical_action({
        "spinal_cord_compression_suspected": True,
        "psa_value": 50,
        "clinical_t_stage": "cT3a",
        "primary_biopsy_not_performed": True,
    })
    assert actions[0].priority == 1
    assert actions[0].urgency == "emergent"


def test_g2743_no_actions_for_routine_localized_low_risk():
    """H.G2743 — Paciente localized low-risk con biopsia: pocas acciones urgentes."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_next_clinical_action
    actions = recommend_next_clinical_action({
        "psa_value": 6.5,
        "clinical_t_stage": "cT1c",
        "histology_already_confirmed": True,
        "ecog_current": 0,
    })
    # Solo MDT review esperada, sin urgent/emergent actions
    assert all(a.urgency != "emergent" for a in actions)
    assert all(a.priority >= 4 for a in actions)


# ──────────────────────────────────────────────────────────────────────
# §C — recommend_flare_protection()
# ──────────────────────────────────────────────────────────────────────


def test_g2744_flare_protection_scc_returns_degarelix():
    """H.G2744 — SCC risk → degarelix (no flare)."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    result = recommend_flare_protection(
        tumor_burden="moderate", cord_compression_risk=True, ecog=2,
    )
    assert result["protocol"] == "degarelix"
    assert "flare" in result["rationale"].lower()


def test_g2745_flare_protection_high_burden_no_scc():
    """H.G2745 — High burden sin SCC → degarelix preferido O LHRH+bicalutamide."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    result = recommend_flare_protection(
        tumor_burden="high", cord_compression_risk=False, ecog=1,
    )
    assert "degarelix" in result["protocol"] or "lhrh" in result["protocol"]


def test_g2746_flare_protection_moderate_burden_lhrh_bicalutamide():
    """H.G2746 — Moderate burden → LHRH agonist + bicalutamida 14d."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    result = recommend_flare_protection(
        tumor_burden="moderate", cord_compression_risk=False, ecog=1,
    )
    assert "lhrh" in result["protocol"].lower()
    assert "bicalutamida" in result["title"].lower() or "bicalutamide" in result["title"].lower()


def test_g2747_flare_protection_low_burden_standard_lhrh():
    """H.G2747 — Low burden + sin SCC → LHRH agonist solo (no flare protection)."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    result = recommend_flare_protection(
        tumor_burden="low", cord_compression_risk=False, ecog=0,
    )
    assert "standard" in result["protocol"].lower()


def test_g2748_flare_protection_evidence_refs_present():
    """H.G2748 — Cada protocolo flare retorna evidence_refs."""
    from prostanet.shared.clinical_subspecialty_engine import recommend_flare_protection
    for burden in ["high", "moderate", "low"]:
        for scc in [True, False]:
            result = recommend_flare_protection(burden, scc, 1)
            assert "evidence_refs" in result
            assert isinstance(result["evidence_refs"], list)


# ──────────────────────────────────────────────────────────────────────
# §D — FieldSpecs nuevos LXXXIV
# ──────────────────────────────────────────────────────────────────────


def test_g2749_new_fieldspecs_registered_in_helper():
    """H.G2749 — 21 nuevos FieldSpecs LXXXIV registrados en helper."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    helper_names = {f.name for f in fields}
    new_fields = {
        "clinical_nepc_suspicion_pre_biopsy",
        "dre_fixation",
        "decision_rp_vs_rt_active",
        "planning_radical_prostatectomy",
        "planning_radiotherapy_curative",
        "presumptive_treatment_documented_with_2week_biopsy_plan",
        "histology_confirmed_metastatic_site",
        "prior_radiation_therapy_documented",
        "psa_velocity_pre_biopsy_urgent_documented",
        "mdt_shared_decision_date",
        "mdt_providers_present",
        "patient_preferences_vs_recommendation",
        "genomic_test_ordered_date",
        "genomic_test_provider",
        "genomic_test_expected_result_date",
        "hrr_test_pending_with_2week_plan_documented",
        "family_history_pca_under_55",
        "family_history_brca_breast_ovarian",
        "germline_test_refused_reason",
        "nepc_platinum_ep_regimen_active",
        "imaging_modality_used_for_m_staging",
    }
    missing = new_fields - helper_names
    assert not missing, f"FieldSpecs LXXXIV missing: {missing}"


def test_g2750_total_fieldspecs_above_400():
    """H.G2750 — Total FieldSpecs ≥400 post-LXXXIV (era 385 pre-LXXXIV)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    assert len(fields) >= 400


# ──────────────────────────────────────────────────────────────────────
# §E — 2 stages nuevos UI v2 (subspecialty + MDT/genomic/hereditary)
# ──────────────────────────────────────────────────────────────────────


def test_g2751_subspecialty_pre_dx_stage_added():
    """H.G2751 — Stage 'subspecialty_pre_dx_decisions' agregado al builder."""
    from prostanet.presentation.v2_advanced_capture_builder import get_advanced_stage_keys
    keys = get_advanced_stage_keys()
    assert "subspecialty_pre_dx_decisions" in keys


def test_g2752_mdt_genomic_hereditary_stage_added():
    """H.G2752 — Stage 'mdt_genomic_hereditary_panel' agregado al builder."""
    from prostanet.presentation.v2_advanced_capture_builder import get_advanced_stage_keys
    keys = get_advanced_stage_keys()
    assert "mdt_genomic_hereditary_panel" in keys


def test_g2753_total_stages_ui_v2_above_19():
    """H.G2753 — Total stages UI v2 ≥21 post-LXXXIV (era 19 pre-LXXXIV)."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    assert len(data["stages"]) >= 21


# ──────────────────────────────────────────────────────────────────────
# §F — Coverage 100% mantenido post-LXXXIV
# ──────────────────────────────────────────────────────────────────────


def test_g2754_coverage_100pct_helper_to_ui_v2_post_lxxxiv():
    """H.G2754 — Coverage helper→UI v2 mantiene 100% post-LXXXIV."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    helper = pivotal_gate_supporting_fields()
    data = build_intake_demo_data()
    ui_fields = set()
    for sf in data["fields"].values():
        for f in sf:
            ui_fields.add(f.get("name", ""))
    helper_names = {f.name for f in helper}
    coverage = (helper_names & ui_fields)
    assert coverage == helper_names, (
        f"Coverage broken post-LXXXIV: {len(helper_names - coverage)} fields missing"
    )


# ──────────────────────────────────────────────────────────────────────
# §G — FAUBOT bump LXXXIII → LXXXIV
# ──────────────────────────────────────────────────────────────────────


def test_g2755_faubot_release_bumped_to_lxxxiv():
    """H.G2755 — FAUBOT_RELEASE ≥ LXXXIV (forward-compat con LXXXV+)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Forward-compat: LXXXIV o LXXXV o cualquier release posterior
    assert any(tag in FAUBOT_RELEASE for tag in ("LXXXIV", "LXXXV", "LXXXVI", "LXXXVII", "LXXXVIII", "LXXXIX", "XC", "XCI", "XCII", "XCIII", "XCIV", "XCV", "XCVI", "XCVII", "XCVIII", "XCIX", "C", "LXCI", "LXCII", "LXCIII", "LXCIV", "LXCV", "LXCVI", "LXCVII"))


def test_g2756_algorithm_version_returns_88_gates():
    """H.G2756 — get_algorithm_version retorna ≥88 gates (LXXXIV.b → 89 con 55B)."""
    from prostanet.shared.algorithm_version import get_algorithm_version
    v = get_algorithm_version()
    # Faubot LXXXIV.b: gate 55B nuevo lleva total a 89; aserción ≥88 permite crecimiento.
    assert v["gates_active_count"] >= 88


# ──────────────────────────────────────────────────────────────────────
# §H — summarize_subspecialty_recommendations() para UI panel
# ──────────────────────────────────────────────────────────────────────


def test_g2757_summarize_returns_complete_structure():
    """H.G2757 — summarize_subspecialty_recommendations() retorna dict completo."""
    from prostanet.shared.clinical_subspecialty_engine import summarize_subspecialty_recommendations
    summary = summarize_subspecialty_recommendations({
        "psa_value": 100, "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
    })
    expected_keys = {
        "actions_count", "highest_priority", "urgency_level",
        "next_action_title", "actions", "flare_protection_recommended",
        "flare_protocol",
    }
    assert set(summary.keys()) == expected_keys
    assert summary["actions_count"] >= 1
    assert summary["highest_priority"] >= 1


def test_g2758_summarize_flare_protection_recommended_for_scc():
    """H.G2758 — summarize() retorna flare_protection_recommended=True con SCC."""
    from prostanet.shared.clinical_subspecialty_engine import summarize_subspecialty_recommendations
    summary = summarize_subspecialty_recommendations({
        "psa_value": 1500, "clinical_t_stage": "cT4",
        "primary_biopsy_not_performed": True,
        "spinal_cord_compression_suspected": True,
        "widespread_bone_metastases_documented": True,
        "liver_metastasis_documented": True,
    })
    assert summary["flare_protection_recommended"] == True
    assert summary["flare_protocol"] is not None
    assert "degarelix" in summary["flare_protocol"]["protocol"]


def test_g2759_summarize_no_flare_protection_for_localized():
    """H.G2759 — summarize() flare_protection_recommended=False en localized routine."""
    from prostanet.shared.clinical_subspecialty_engine import summarize_subspecialty_recommendations
    summary = summarize_subspecialty_recommendations({
        "psa_value": 6.5, "clinical_t_stage": "cT1c",
        "histology_already_confirmed": True,
        "ecog_current": 0,
    })
    assert summary["flare_protection_recommended"] == False
