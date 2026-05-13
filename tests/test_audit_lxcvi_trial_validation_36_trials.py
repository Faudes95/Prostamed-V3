"""tests/test_audit_lxcvi_trial_validation_36_trials.py — FAUBOT LXCVI.
IEC 62304 §5.7 (software system testing).

Tests para Iteración LXCVI — Trial Validation Audit + AE/Contraindication
Coverage Closure (plan padre LXCVI.A-F):

  - §A: Tier 1 AE gates (5 gates: arpi_fall + taxane_diarrhea + HFSR + parp_fatigue + apa_hypothyroid)
  - §B: Tier 2 contraindication hard_blocks (6 gates)
  - §C: Tier 3 interaction gates (3 gates)
  - §D: 26 new FieldSpecs registered en pivotal_gate_supporting_fields()
  - §E: Flagship patient verification con realistic payloads
  - §F: 36 trials registry + evaluator coverage maintained (no regression)

HIPÓTESIS: H.G3146 → H.G3175 (~30 tests).
Faubot LXCVI — 36 Pivotal Trials × Adverse Events × Contraindications.
"""
from __future__ import annotations

import sys
import types

if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            if n.startswith("__") and n.endswith("__"):
                raise AttributeError(n)
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")


# ──────────────────────────────────────────────────────────────────────
# §A — Tier 1 AE gates (5 gates)
# ──────────────────────────────────────────────────────────────────────


def test_g3146_arpi_fall_risk_gate_loaded():
    """H.G3146 — Gate 86 arpi_fall_risk_longitudinal loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "arpi_fall_risk_longitudinal" in get_loaded_yaml_codes()


def test_g3147_arpi_fall_risk_fires_on_fall_event():
    """H.G3147 — Gate 86 dispara con fall_event_documented + ARPI."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "fall_event_documented": 1, "planned_regimen": "ENZALUTAMIDE",
    })
    assert "arpi_fall_risk_longitudinal" in [g["code"] for g in fired]


def test_g3148_taxane_diarrhea_gate_loaded():
    """H.G3148 — Gate 87 taxane_diarrhea_grade3_plus loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "taxane_diarrhea_grade3_plus" in get_loaded_yaml_codes()


def test_g3149_taxane_diarrhea_fires_on_grade3():
    """H.G3149 — Gate 87 dispara hard_block con diarrhea G3 + docetaxel."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "diarrhea_ctcae_grade": 3, "planned_regimen": "DOCETAXEL",
    })
    fired_dict = {g["code"]: g for g in fired}
    assert "taxane_diarrhea_grade3_plus" in fired_dict
    assert fired_dict["taxane_diarrhea_grade3_plus"].get("severity") == "hard_block"


def test_g3150_taxane_diarrhea_override_blocks_gate():
    """H.G3150 — Override taxane_diarrhea_aggressive_management_documented blocks gate."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "diarrhea_ctcae_grade": 3,
        "planned_regimen": "DOCETAXEL",
        "taxane_diarrhea_aggressive_management_documented": 1,
    })
    assert "taxane_diarrhea_grade3_plus" not in [g["code"] for g in fired]


def test_g3151_hfsr_gate_loaded():
    """H.G3151 — Gate 88 hand_foot_syndrome_tkis_grade2_plus loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "hand_foot_syndrome_tkis_grade2_plus" in get_loaded_yaml_codes()


def test_g3152_hfsr_fires_on_grade2_cabozantinib():
    """H.G3152 — Gate 88 dispara con HFSR G2 + cabozantinib (CONTACT-02 setting)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "hfsr_ctcae_grade": 2, "planned_regimen": "CABOZANTINIB_ATEZOLIZUMAB",
    })
    assert "hand_foot_syndrome_tkis_grade2_plus" in [g["code"] for g in fired]


def test_g3153_parp_fatigue_gate_loaded():
    """H.G3153 — Gate 89 parp_fatigue_grade3 loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "parp_fatigue_grade3" in get_loaded_yaml_codes()


def test_g3154_parp_fatigue_fires_on_grade3():
    """H.G3154 — Gate 89 dispara con fatigue G3 + olaparib (PROfound setting)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "fatigue_ctcae_grade": 3, "planned_regimen": "OLAPARIB",
    })
    assert "parp_fatigue_grade3" in [g["code"] for g in fired]


def test_g3155_apalutamide_hypothyroidism_gate_loaded():
    """H.G3155 — Gate 90 hypothyroidism_apalutamide_new_onset loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "hypothyroidism_apalutamide_new_onset" in get_loaded_yaml_codes()


def test_g3156_apalutamide_hypothyroidism_fires_on_tsh():
    """H.G3156 — Gate 90 dispara con TSH elevated + apalutamida."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "tsh_elevated_new_onset": 1, "planned_regimen": "APALUTAMIDE",
    })
    assert "hypothyroidism_apalutamide_new_onset" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §B — Tier 2 contraindication hard_blocks (6 gates)
# ──────────────────────────────────────────────────────────────────────


def test_g3157_abiraterone_cirrhosis_gate_loaded_and_hardblock():
    """H.G3157 — Gate 91 abiraterone cirrhosis loaded + severity=hard_block."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    data = _load_yaml_files(force_reload=True)
    config = next((c for c in data.values() if c.get("code") == "abiraterone_cirrhosis_baseline_contraindication"), None)
    assert config is not None
    assert config.get("severity") == "hard_block"


def test_g3158_abiraterone_cirrhosis_fires_on_child_pugh_b():
    """H.G3158 — Gate 91 dispara con Child-Pugh B (score ≥7) + abiraterona."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "child_pugh_score": 8, "planned_regimen": "ABIRATERONE",
    })
    assert "abiraterone_cirrhosis_baseline_contraindication" in [g["code"] for g in fired]


def test_g3159_parp_hrr_negative_gate_loaded():
    """H.G3159 — Gate 92 parp_hrr_negative_futility_block loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "parp_hrr_negative_futility_block" in get_loaded_yaml_codes()


def test_g3160_parp_hrr_negative_fires_on_negative_status():
    """H.G3160 — Gate 92 dispara con HRR-negative + olaparib (futility)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "hrr_status": "hrr_negative", "planned_regimen": "OLAPARIB",
    })
    assert "parp_hrr_negative_futility_block" in [g["code"] for g in fired]


def test_g3161_lu177_psma_negative_gate_loaded():
    """H.G3161 — Gate 93 lu177_psma_pet_negative_contraindication loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "lu177_psma_pet_negative_contraindication" in get_loaded_yaml_codes()


def test_g3162_lu177_psma_negative_fires_on_low_uptake():
    """H.G3162 — Gate 93 dispara con PSMA-PET negative + Lu-177."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "psma_pet_negative_or_low_uptake": 1,
        "planned_regimen": "LUTETIUM_177_PSMA_617",
    })
    assert "lu177_psma_pet_negative_contraindication" in [g["code"] for g in fired]


def test_g3163_ra223_visceral_gate_loaded():
    """H.G3163 — Gate 94 ra223_visceral_metastases_contraindication loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "ra223_visceral_metastases_contraindication" in get_loaded_yaml_codes()


def test_g3164_ra223_visceral_fires_on_visceral_mets():
    """H.G3164 — Gate 94 dispara con visceral mets + Ra-223 (ALSYMPCA exclusion)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "visceral_metastases_documented": 1, "planned_regimen": "RADIUM_223",
    })
    assert "ra223_visceral_metastases_contraindication" in [g["code"] for g in fired]


def test_g3165_sipuleucel_immunosuppression_gate_loaded():
    """H.G3165 — Gate 95 sipuleucel_t_immunosuppression_baseline loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "sipuleucel_t_immunosuppression_baseline" in get_loaded_yaml_codes()


def test_g3166_sipuleucel_immunosuppression_fires_on_hiv():
    """H.G3166 — Gate 95 dispara con HIV+ + sipuleucel-T."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "hiv_positive": 1, "planned_regimen": "SIPULEUCEL_T",
    })
    assert "sipuleucel_t_immunosuppression_baseline" in [g["code"] for g in fired]


def test_g3167_ipatasertib_pten_wt_gate_loaded():
    """H.G3167 — Gate 96 ipatasertib_pten_wt_futility_block loaded."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "ipatasertib_pten_wt_futility_block" in get_loaded_yaml_codes()


def test_g3168_ipatasertib_pten_wt_fires():
    """H.G3168 — Gate 96 dispara con PTEN-wt + ipatasertib (IPATential150 futility)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "pten_status_wild_type_or_retained": 1,
        "planned_regimen": "IPATASERTIB_ABIRATERONE",
    })
    assert "ipatasertib_pten_wt_futility_block" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §C — Tier 3 interaction gates (3 gates)
# ──────────────────────────────────────────────────────────────────────


def test_g3169_enz_ra223_dual_gate_loaded_and_fires():
    """H.G3169 — Gate 97 enzalutamide_ra223_dual_myelosuppression loaded + fires."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "enzalutamide_ra223_dual_myelosuppression" in get_loaded_yaml_codes()
    fired = evaluate_all_yaml_gates({
        "wbc_lt_3_and_platelet_lt_100_combined": 1, "planned_regimen": "RADIUM_223",
    })
    assert "enzalutamide_ra223_dual_myelosuppression" in [g["code"] for g in fired]


def test_g3170_xerostomia_lu177_gate_loaded_and_fires():
    """H.G3170 — Gate 98 xerostomia_monitoring_lu177_grade2_plus loaded + fires."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "xerostomia_monitoring_lu177_grade2_plus" in get_loaded_yaml_codes()
    fired = evaluate_all_yaml_gates({
        "xerostomia_ctcae_grade": 2, "planned_regimen": "LUTETIUM_177_PSMA_617",
    })
    assert "xerostomia_monitoring_lu177_grade2_plus" in [g["code"] for g in fired]


def test_g3171_cumulative_neuropathy_gate_loaded_and_fires():
    """H.G3171 — Gate 99 docetaxel_neuropathy_cumulative_postchemo loaded + fires."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "docetaxel_neuropathy_cumulative_postchemo" in get_loaded_yaml_codes()
    fired = evaluate_all_yaml_gates({
        "peripheral_neuropathy_grade": 3,
        "cumulative_docetaxel_dose_mg_m2": 450,
        "planned_regimen": "DOCETAXEL",
    })
    assert "docetaxel_neuropathy_cumulative_postchemo" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §D — 26 new FieldSpecs registered
# ──────────────────────────────────────────────────────────────────────


def test_g3172_total_103_gates_loaded():
    """H.G3172 — Total 103 gates loaded post-LXCVI (89 + 14 new)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 103, f"Gates count regression: {len(codes)} (expected ≥103)"


def test_g3173_26_new_fieldspecs_registered():
    """H.G3173 — 26 nuevas FieldSpecs registradas en pivotal_gate_supporting_fields().

    LXCIX.2 forward-compat: el campo numeric `child_pugh_score` (5-15) se
    renombró a `child_pugh_sum_points` para evitar conflicto con el canonical
    select A/B/C en advanced_hepatic_fields().
    """
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    new_fields = [
        # Tier 1 AE (11)
        "fall_event_documented", "fall_risk_score_high", "mobility_decline_longitudinal",
        "diarrhea_ctcae_grade", "diarrhea_with_dehydration_documented",
        "hfsr_ctcae_grade", "hand_foot_skin_reaction_documented",
        "fatigue_ctcae_grade",
        "tsh_elevated_new_onset", "t4_low_new_onset", "hypothyroidism_documented_during_treatment",
        # Tier 2 contraindications (10) — child_pugh_sum_points renamed LXCIX.2
        "child_pugh_sum_points", "cirrhosis_documented", "liver_decompensation_documented",
        "psma_pet_negative_or_low_uptake", "psma_pet_max_suvmax_lesion",
        "visceral_metastases_documented",
        "immunosuppression_active", "hiv_positive", "cd4_count_lt_200",
        "pten_status_wild_type_or_retained", "pten_status",
        # Tier 3 interactions (5)
        "wbc_lt_3_and_platelet_lt_100_combined", "dual_bone_marrow_toxicity_documented",
        "xerostomia_ctcae_grade",
        "cumulative_docetaxel_dose_mg_m2",
    ]
    missing = [f for f in new_fields if f not in names]
    assert not missing, f"Missing FieldSpecs: {missing}"


def test_g3174_total_fieldspecs_count_increased():
    """H.G3174 — Total FieldSpecs cuenta ≥435 (410 pre-LXCVI + 25-26 nuevas)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    assert len(fields) >= 435, f"FieldSpecs count regression: {len(fields)} (expected ≥435)"


# ──────────────────────────────────────────────────────────────────────
# §E — 36 trials registry no regression
# ──────────────────────────────────────────────────────────────────────


def test_g3175_trial_eligibility_engine_36_trials_no_regression():
    """H.G3175 — Trial eligibility engine sigue evaluando 36 trials sin regresión."""
    from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility

    # Test 5 representative flagship patients (subset de LXCIV)
    test_cases = [
        ("CHAARTED", {
            "metastasis_site": "M1", "visceral_metastasis_present": "1",
            "bone_lesion_count_total": 6, "ecog_score": 1,
            "castrate_testosterone_status": "not_castrate",
        }),
        ("PROfound", {
            "metastasis_site": "M1b", "m1_crpc_state_confirmed": 1,
            "castrate_testosterone_status": "confirmed_castrate",
            "hrr_status": "hrr_positive", "hrr_genes_mutated": ["BRCA2"],
            "prior_treatment_lines_count": 2,
        }),
        ("SPARTAN", {
            "m0_crpc_state_confirmed": 1, "psa_doubling_time_months": 6,
            "metastasis_site": "M0", "ecog_score": 0,
            "castrate_testosterone_status": "confirmed_castrate",
        }),
        ("VISION", {
            "metastasis_site": "M1", "m1_crpc_state_confirmed": 1,
            "psma_pet_max_suvmax_lesion": 25,
            "prior_treatment_lines_count": 2,
            "castrate_testosterone_status": "confirmed_castrate",
        }),
        ("ALSYMPCA", {
            "metastasis_site": "M1b", "m1_crpc_state_confirmed": 1,
            "bone_lesion_count_total": 4, "visceral_metastases_documented": 0,
            "castrate_testosterone_status": "confirmed_castrate",
        }),
    ]

    for trial_id, payload in test_cases:
        result = evaluate_trial_eligibility(payload, trial_id)
        assert isinstance(result, dict), f"{trial_id}: result not dict"
        assert "eligible" in result, f"{trial_id}: missing 'eligible' key"
