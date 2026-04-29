"""tests/test_audit67de_gates_71_85_progression_palliative.py — FAUBOT LXXVIII+LXXIX / Auditoría #67D+E.

Tests dedicados para gates 71-85 (Progression Detection + Palliative + Radiopharm + Palliative RT):

#67D — Progression Detection Composite Engine (gates 71-75):
- 71: psma_pet_progression_auto_trigger (soft_warning)
- 72: visceral_metastasis_new_appearance (soft_warning)
- 73: structured_pain_progression_bpi (soft_warning)
- 74: ecog_decline_alert (soft_warning)
- 75: composite_progression_rpfs_reroute (soft_warning meta-gate)

#67E — Palliative + Radiopharm + Palliative RT (gates 76-85):
- 76: samarium_153_edtmp_eligibility (informational)
- 77: iodine_131_mibg_nepc_eligibility (informational)
- 78: actinium_225_psma_investigational (informational)
- 79: palliative_sedation_protocol_initiation (hard_block + override EAPC)
- 80: esas_severity_alert (soft_warning)
- 81: phq9_depression_referral (soft_warning)
- 82: gad7_anxiety_referral (soft_warning)
- 83: palliative_rt_decision_engine (informational)
- 84: oligometastatic_sbrt_eligibility (informational)
- 85: cachexia_pharmacotherapy_consideration (informational)

Cubre:
- Multi-path triggers para cada gate
- Override mechanisms (gate 79 EAPC)
- UI FieldSpecs registrados en pivotal_gate_supporting_fields()
- Backend canonicalization

Hipótesis verificables: H.G2313 → H.G2370 (~58 tests).

Faubot 2026-04-26 LXXVIII+LXXIX — cierre #67D+E paralelo.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

# ── APFS lock workaround ───────────────────────────────────────────
if "tracking_db" not in sys.modules:
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")

from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
from prostanet.shared.pivotal_gates_yaml_loader import (
    _load_yaml_files,
    evaluate_all_yaml_gates,
    get_loaded_yaml_codes,
)


# ──────────────────────────────────────────────────────────────────────
# §A — Gate 71: PSMA-PET progression auto-trigger
# ──────────────────────────────────────────────────────────────────────


def test_g2313_gate71_loaded_in_yaml_catalog():
    """H.G2313 — Gate 71 loaded en YAML catalog."""
    _load_yaml_files(force_reload=True)
    assert "psma_pet_progression_auto_trigger" in get_loaded_yaml_codes()


def test_g2314_gate71_fires_new_psma_lesions():
    """H.G2314 — Gate 71 dispara con ≥1 nueva lesión PSMA."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"psma_new_lesion_count": 2})
    assert "psma_pet_progression_auto_trigger" in [g["code"] for g in fired]


def test_g2315_gate71_fires_suvmax_increase_30pct():
    """H.G2315 — Gate 71 dispara con SUVmax aumento ≥30%."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"psma_suvmax_increase_percent": 35})
    assert "psma_pet_progression_auto_trigger" in [g["code"] for g in fired]


def test_g2316_gate71_fires_explicit_flag():
    """H.G2316 — Gate 71 dispara con flag clínico explicit."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"psma_pet_progression_documented": True})
    assert "psma_pet_progression_auto_trigger" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §B — Gate 72: Visceral metastasis new appearance
# ──────────────────────────────────────────────────────────────────────


def test_g2317_gate72_loaded_in_yaml_catalog():
    """H.G2317 — Gate 72 loaded."""
    _load_yaml_files(force_reload=True)
    assert "visceral_metastasis_new_appearance" in get_loaded_yaml_codes()


def test_g2318_gate72_fires_new_liver_mets():
    """H.G2318 — Gate 72 dispara con nueva mets hepática."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"new_liver_metastasis_appeared": True})
    assert "visceral_metastasis_new_appearance" in [g["code"] for g in fired]


def test_g2319_gate72_fires_new_lung_mets():
    """H.G2319 — Gate 72 dispara con nueva mets pulmonar."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"new_lung_metastasis_appeared": True})
    assert "visceral_metastasis_new_appearance" in [g["code"] for g in fired]


def test_g2320_gate72_fires_new_cns_mets():
    """H.G2320 — Gate 72 dispara con nueva mets SNC."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"new_cns_metastasis_appeared": True})
    assert "visceral_metastasis_new_appearance" in [g["code"] for g in fired]


def test_g2321_gate72_fires_count_increase():
    """H.G2321 — Gate 72 dispara con visceral count increase."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"visceral_metastases_count_increase": 2})
    assert "visceral_metastasis_new_appearance" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §C — Gate 73: BPI pain progression
# ──────────────────────────────────────────────────────────────────────


def test_g2322_gate73_loaded_in_yaml_catalog():
    """H.G2322 — Gate 73 loaded."""
    _load_yaml_files(force_reload=True)
    assert "structured_pain_progression_bpi" in get_loaded_yaml_codes()


def test_g2323_gate73_fires_bpi_severo():
    """H.G2323 — Gate 73 dispara con BPI worst ≥7 (severo Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"bpi_worst_pain_score": 8})
    assert "structured_pain_progression_bpi" in [g["code"] for g in fired]


def test_g2324_gate73_fires_bpi_persistent_4_weeks():
    """H.G2324 — Gate 73 dispara con BPI ≥4 + ≥4 semanas (Path A)."""
    _load_yaml_files(force_reload=True)
    payload = {"bpi_worst_pain_score": 5, "bpi_pain_persistent_weeks": 6}
    fired = evaluate_all_yaml_gates(payload)
    assert "structured_pain_progression_bpi" in [g["code"] for g in fired]


def test_g2325_gate73_fires_interference_high():
    """H.G2325 — Gate 73 dispara con BPI interference ≥4 (Path C)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"bpi_interference_average": 5})
    assert "structured_pain_progression_bpi" in [g["code"] for g in fired]


def test_g2326_gate73_fires_pain_increase_30pct():
    """H.G2326 — Gate 73 dispara con BPI increase ≥30% (PCWG3 Path D)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"bpi_worst_pain_increase_percent": 35})
    assert "structured_pain_progression_bpi" in [g["code"] for g in fired]


def test_g2327_gate73_fires_new_opioid_requirement():
    """H.G2327 — Gate 73 dispara con nueva necesidad opioides (Path E)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"new_opioid_requirement_for_cancer_pain": True})
    assert "structured_pain_progression_bpi" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §D — Gate 74: ECOG decline alert
# ──────────────────────────────────────────────────────────────────────


def test_g2328_gate74_loaded_in_yaml_catalog():
    """H.G2328 — Gate 74 loaded."""
    _load_yaml_files(force_reload=True)
    assert "ecog_decline_alert" in get_loaded_yaml_codes()


def test_g2329_gate74_fires_ecog_decline_grade():
    """H.G2329 — Gate 74 dispara con ECOG decline ≥1 grade (Path A)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"ecog_change_from_baseline": 2})
    assert "ecog_decline_alert" in [g["code"] for g in fired]


def test_g2330_gate74_fires_ecog_current_2():
    """H.G2330 — Gate 74 dispara con ECOG actual ≥2 (Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"ecog_current": 3})
    assert "ecog_decline_alert" in [g["code"] for g in fired]


def test_g2331_gate74_fires_explicit_decline_flag():
    """H.G2331 — Gate 74 dispara con flag clínico decline (Path D)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"ecog_significant_decline_documented": True})
    assert "ecog_decline_alert" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §E — Gate 75: Composite progression rPFS reroute
# ──────────────────────────────────────────────────────────────────────


def test_g2332_gate75_loaded_in_yaml_catalog():
    """H.G2332 — Gate 75 loaded."""
    _load_yaml_files(force_reload=True)
    assert "composite_progression_rpfs_reroute" in get_loaded_yaml_codes()


def test_g2333_gate75_fires_psa_plus_radiographic():
    """H.G2333 — Gate 75 dispara con PSA + Radiographic progression simultáneo."""
    _load_yaml_files(force_reload=True)
    payload = {
        "psa_progression_documented": True,
        "psma_pet_progression_documented": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "composite_progression_rpfs_reroute" in [g["code"] for g in fired]


def test_g2334_gate75_fires_radiographic_plus_clinical():
    """H.G2334 — Gate 75 dispara con Radiographic + Clinical simultáneo."""
    _load_yaml_files(force_reload=True)
    payload = {
        "new_visceral_metastasis_documented": True,
        "ecog_change_from_baseline": 2,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "composite_progression_rpfs_reroute" in [g["code"] for g in fired]


def test_g2335_gate75_fires_explicit_composite_flag():
    """H.G2335 — Gate 75 dispara con flag composite explicit."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"pcwg3_composite_progression_documented": True})
    assert "composite_progression_rpfs_reroute" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §F — Gate 76: Samarium-153 EDTMP eligibility
# ──────────────────────────────────────────────────────────────────────


def test_g2336_gate76_loaded_in_yaml_catalog():
    """H.G2336 — Gate 76 loaded."""
    _load_yaml_files(force_reload=True)
    assert "samarium_153_edtmp_eligibility" in get_loaded_yaml_codes()


def test_g2337_gate76_fires_explicit_candidate_flag():
    """H.G2337 — Gate 76 dispara con flag candidate explicit (Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"samarium_153_edtmp_candidate": True})
    assert "samarium_153_edtmp_eligibility" in [g["code"] for g in fired]


def test_g2338_gate76_fires_widespread_pain_counts_ok():
    """H.G2338 — Gate 76 dispara con widespread pain + counts OK (Path A)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "bpi_worst_pain_score": 6,
        "widespread_bone_metastases_documented": True,
        "anc": 2000,
        "platelets": 150000,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "samarium_153_edtmp_eligibility" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §G — Gate 77: I-131 MIBG NEPC eligibility
# ──────────────────────────────────────────────────────────────────────


def test_g2339_gate77_loaded_in_yaml_catalog():
    """H.G2339 — Gate 77 loaded."""
    _load_yaml_files(force_reload=True)
    assert "iodine_131_mibg_nepc_eligibility" in get_loaded_yaml_codes()


def test_g2340_gate77_fires_nepc_plus_mibg_positive():
    """H.G2340 — Gate 77 dispara con NEPC confirmed + MIBG scan positive."""
    _load_yaml_files(force_reload=True)
    payload = {
        "nepc_confirmed_histology": True,
        "mibg_scan_positive_diagnostic": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "iodine_131_mibg_nepc_eligibility" in [g["code"] for g in fired]


def test_g2341_gate77_no_fire_without_nepc():
    """H.G2341 — Gate 77 NO dispara sin NEPC (gate requires NEPC)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"mibg_scan_positive_diagnostic": True})
    # MIBG positive sin NEPC NO debe disparar gate 77
    assert "iodine_131_mibg_nepc_eligibility" not in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §H — Gate 78: Actinium-225-PSMA investigational
# ──────────────────────────────────────────────────────────────────────


def test_g2342_gate78_loaded_in_yaml_catalog():
    """H.G2342 — Gate 78 loaded."""
    _load_yaml_files(force_reload=True)
    assert "actinium_225_psma_investigational" in get_loaded_yaml_codes()


def test_g2343_gate78_fires_post_lu177_progression():
    """H.G2343 — Gate 78 dispara con progression post Lu-177 + PSMA+."""
    _load_yaml_files(force_reload=True)
    payload = {
        "lutetium_177_psma_progression_documented": True,
        "psma_pet_positive_current": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "actinium_225_psma_investigational" in [g["code"] for g in fired]


def test_g2344_gate78_fires_explicit_candidate():
    """H.G2344 — Gate 78 dispara con flag candidate explicit."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"actinium_225_psma_candidate": True})
    assert "actinium_225_psma_investigational" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §I — Gate 79: Palliative sedation protocol (hard_block + override EAPC)
# ──────────────────────────────────────────────────────────────────────


def test_g2345_gate79_loaded_in_yaml_catalog():
    """H.G2345 — Gate 79 loaded."""
    _load_yaml_files(force_reload=True)
    assert "palliative_sedation_protocol_initiation" in get_loaded_yaml_codes()


def test_g2346_gate79_fires_initiation_planned():
    """H.G2346 — Gate 79 hard_block dispara con sedation initiation planeada."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"palliative_sedation_initiation_planned": True})
    assert "palliative_sedation_protocol_initiation" in [g["code"] for g in fired]


def test_g2347_gate79_fires_eol_plus_refractory_pain():
    """H.G2347 — Gate 79 dispara con EOL stage + refractory pain (Path B)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "end_of_life_stage_documented": True,
        "refractory_pain_palliative_failure": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "palliative_sedation_protocol_initiation" in [g["code"] for g in fired]


def test_g2348_gate79_blocked_by_eapc_criteria_override():
    """H.G2348 — Gate 79 NO dispara con EAPC criteria + MDT + family consent override."""
    _load_yaml_files(force_reload=True)
    payload = {
        "palliative_sedation_initiation_planned": True,
        # Override criteria all met
        "palliative_sedation_eapc_criteria_met": True,
        "mdt_consensus_palliative_sedation_documented": True,
        "family_consent_palliative_sedation_documented": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "palliative_sedation_protocol_initiation" not in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §J — Gate 80: ESAS severity alert
# ──────────────────────────────────────────────────────────────────────


def test_g2349_gate80_loaded_in_yaml_catalog():
    """H.G2349 — Gate 80 loaded."""
    _load_yaml_files(force_reload=True)
    assert "esas_severity_alert" in get_loaded_yaml_codes()


def test_g2350_gate80_fires_2_items_above_4():
    """H.G2350 — Gate 80 dispara con 2+ ítems ESAS ≥4 (Path A)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"esas_items_above_4_count": 3})
    assert "esas_severity_alert" in [g["code"] for g in fired]


def test_g2351_gate80_fires_total_above_30():
    """H.G2351 — Gate 80 dispara con total ESAS ≥30 (Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"esas_total_score": 35})
    assert "esas_severity_alert" in [g["code"] for g in fired]


def test_g2352_gate80_fires_pain_severo():
    """H.G2352 — Gate 80 dispara con ESAS pain ≥7 (Path C)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"esas_pain_score": 8})
    assert "esas_severity_alert" in [g["code"] for g in fired]


def test_g2353_gate80_fires_dyspnea_severo():
    """H.G2353 — Gate 80 dispara con ESAS dyspnea ≥7 (Path C)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"esas_dyspnea_score": 8})
    assert "esas_severity_alert" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §K — Gate 81: PHQ-9 depression
# ──────────────────────────────────────────────────────────────────────


def test_g2354_gate81_loaded_in_yaml_catalog():
    """H.G2354 — Gate 81 loaded."""
    _load_yaml_files(force_reload=True)
    assert "phq9_depression_referral" in get_loaded_yaml_codes()


def test_g2355_gate81_fires_phq9_moderate():
    """H.G2355 — Gate 81 dispara con PHQ-9 ≥10 (moderate Path A)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"phq9_total_score": 15})
    assert "phq9_depression_referral" in [g["code"] for g in fired]


def test_g2356_gate81_fires_suicidal_ideation_critical():
    """H.G2356 — Gate 81 CRITICAL dispara con ítem 9 ≥1 (suicidal ideation)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"phq9_item_9_suicidal_ideation": 2})
    assert "phq9_depression_referral" in [g["code"] for g in fired]


def test_g2357_gate81_no_fire_minimal_score():
    """H.G2357 — Gate 81 NO dispara con PHQ-9 <10 (sin suicidal)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"phq9_total_score": 5, "phq9_item_9_suicidal_ideation": 0})
    assert "phq9_depression_referral" not in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §L — Gate 82: GAD-7 anxiety
# ──────────────────────────────────────────────────────────────────────


def test_g2358_gate82_loaded_in_yaml_catalog():
    """H.G2358 — Gate 82 loaded."""
    _load_yaml_files(force_reload=True)
    assert "gad7_anxiety_referral" in get_loaded_yaml_codes()


def test_g2359_gate82_fires_gad7_moderate():
    """H.G2359 — Gate 82 dispara con GAD-7 ≥10 (moderate Path A)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"gad7_total_score": 12})
    assert "gad7_anxiety_referral" in [g["code"] for g in fired]


def test_g2360_gate82_fires_explicit_anxiety_disorder():
    """H.G2360 — Gate 82 dispara con flag anxiety disorder (Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"clinical_anxiety_disorder_documented": True})
    assert "gad7_anxiety_referral" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §M — Gate 83: Palliative RT decision engine
# ──────────────────────────────────────────────────────────────────────


def test_g2361_gate83_loaded_in_yaml_catalog():
    """H.G2361 — Gate 83 loaded."""
    _load_yaml_files(force_reload=True)
    assert "palliative_rt_decision_engine" in get_loaded_yaml_codes()


def test_g2362_gate83_fires_bone_pain_localized():
    """H.G2362 — Gate 83 dispara con bone pain localized + BPI ≥4 (Path A)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "bpi_worst_pain_score": 6,
        "bone_metastasis_localized_painful": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "palliative_rt_decision_engine" in [g["code"] for g in fired]


def test_g2363_gate83_fires_hematuria():
    """H.G2363 — Gate 83 dispara con hematuria persistente (Path C)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"hematuria_persistent_tumoral": True})
    assert "palliative_rt_decision_engine" in [g["code"] for g in fired]


def test_g2364_gate83_fires_brain_mets():
    """H.G2364 — Gate 83 dispara con brain mets (Path D)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"brain_metastases_documented": True})
    assert "palliative_rt_decision_engine" in [g["code"] for g in fired]


def test_g2365_gate83_fires_explicit_consideration():
    """H.G2365 — Gate 83 dispara con flag consideration (Path F)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"palliative_rt_consideration_active": True})
    assert "palliative_rt_decision_engine" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §N — Gate 84: Oligometastatic SBRT eligibility
# ──────────────────────────────────────────────────────────────────────


def test_g2366_gate84_loaded_in_yaml_catalog():
    """H.G2366 — Gate 84 loaded."""
    _load_yaml_files(force_reload=True)
    assert "oligometastatic_sbrt_eligibility" in get_loaded_yaml_codes()


def test_g2367_gate84_fires_oligo_plus_life_exp():
    """H.G2367 — Gate 84 dispara con ≤5 mets + esperanza vida >12m (Path A)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "total_metastases_count": 3,
        "life_expectancy_months": 24,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "oligometastatic_sbrt_eligibility" in [g["code"] for g in fired]


def test_g2368_gate84_fires_metachronous_oligo():
    """H.G2368 — Gate 84 dispara con metachronous oligo recurrence (Path B)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"oligometastatic_recurrence_metachronous": True})
    assert "oligometastatic_sbrt_eligibility" in [g["code"] for g in fired]


def test_g2369_gate84_fires_oligoprogression():
    """H.G2369 — Gate 84 dispara con oligoprogression bajo systemic (Path C)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"oligoprogression_under_systemic_therapy": True})
    assert "oligometastatic_sbrt_eligibility" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §O — Gate 85: Cachexia pharmacotherapy consideration
# ──────────────────────────────────────────────────────────────────────


def test_g2370_gate85_loaded_in_yaml_catalog():
    """H.G2370 — Gate 85 loaded."""
    _load_yaml_files(force_reload=True)
    assert "cachexia_pharmacotherapy_consideration" in get_loaded_yaml_codes()


def test_g2371_gate85_fires_weight_loss_above_5pct():
    """H.G2371 — Gate 85 dispara con pérdida peso >5% en 6m (Path A)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"weight_loss_percent_6mo": 8})
    assert "cachexia_pharmacotherapy_consideration" in [g["code"] for g in fired]


def test_g2372_gate85_fires_low_bmi_plus_loss():
    """H.G2372 — Gate 85 dispara con BMI <20 + weight loss >2% (Path B)."""
    _load_yaml_files(force_reload=True)
    payload = {"bmi": 18.5, "weight_loss_percent_6mo": 3}
    fired = evaluate_all_yaml_gates(payload)
    assert "cachexia_pharmacotherapy_consideration" in [g["code"] for g in fired]


def test_g2373_gate85_fires_sarcopenia_plus_loss():
    """H.G2373 — Gate 85 dispara con sarcopenia + weight loss >2% (Path C)."""
    _load_yaml_files(force_reload=True)
    payload = {"sarcopenia_documented": True, "weight_loss_percent_6mo": 3}
    fired = evaluate_all_yaml_gates(payload)
    assert "cachexia_pharmacotherapy_consideration" in [g["code"] for g in fired]


def test_g2374_gate85_fires_appetite_plus_cachexia_dx():
    """H.G2374 — Gate 85 dispara con appetite loss + cachexia dx (Path D)."""
    _load_yaml_files(force_reload=True)
    payload = {
        "appetite_loss_documented": True,
        "cachexia_clinical_diagnosed": True,
    }
    fired = evaluate_all_yaml_gates(payload)
    assert "cachexia_pharmacotherapy_consideration" in [g["code"] for g in fired]


def test_g2375_gate85_fires_esas_appetite_high():
    """H.G2375 — Gate 85 dispara con ESAS appetite ≥4 (Path E)."""
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({"esas_appetite_score": 5})
    assert "cachexia_pharmacotherapy_consideration" in [g["code"] for g in fired]


# ──────────────────────────────────────────────────────────────────────
# §P — UI Integration: FieldSpecs registrados (gates 71-85)
# ──────────────────────────────────────────────────────────────────────


def test_g2376_ui_fieldspecs_for_gate71_72_psma_visceral():
    """H.G2376 — FieldSpecs para gates 71/72 (PSMA + visceral) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "psma_new_lesion_count", "psma_suvmax_current", "psma_suvmax_increase_percent",
        "psma_pet_progression_documented", "psma_progression_date",
        "new_visceral_metastasis_documented", "new_liver_metastasis_appeared",
        "new_lung_metastasis_appeared", "new_cns_metastasis_appeared",
        "visceral_metastases_count_increase",
    }
    missing = expected - names
    assert not missing, f"Gates 71/72 fields missing: {missing}"


def test_g2377_ui_fieldspecs_for_gate73_74_bpi_ecog():
    """H.G2377 — FieldSpecs para gates 73/74 (BPI + ECOG) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "bpi_worst_pain_score", "bpi_least_pain_score", "bpi_average_pain_score",
        "bpi_current_pain_score", "bpi_interference_average",
        "bpi_pain_persistent_weeks", "bpi_worst_pain_increase_percent",
        "new_opioid_requirement_for_cancer_pain", "current_opioid_morphine_equivalent_mg_day",
        "ecog_current", "ecog_baseline", "ecog_change_from_baseline",
        "ecog_significant_decline_documented",
    }
    missing = expected - names
    assert not missing, f"Gates 73/74 fields missing: {missing}"


def test_g2378_ui_fieldspecs_for_gate75_composite():
    """H.G2378 — FieldSpecs para gate 75 (composite rPFS) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "psa_progression_documented", "pcwg3_composite_progression_documented",
        "composite_progression_categories_fired", "composite_progression_date",
        "next_line_therapy_planned", "mdt_composite_review_completed",
    }
    missing = expected - names
    assert not missing, f"Gate 75 fields missing: {missing}"


def test_g2379_ui_fieldspecs_for_gate76_77_78_radiopharm():
    """H.G2379 — FieldSpecs para gates 76/77/78 (Sm-153 + I-131 MIBG + Ac-225) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "samarium_153_edtmp_candidate", "bone_pain_widespread_documented",
        "bone_scan_multifoci_positive", "samarium_153_dose_planned_mci_kg",
        "mibg_scan_positive_diagnostic", "mibg_curie_score",
        "i131_mibg_candidate_clinical", "sski_thyroid_blockade_initiated",
        "lutetium_177_psma_progression_documented", "psma_pet_positive_current",
        "actinium_225_psma_candidate", "actinium_225_dose_planned_kbq_kg",
    }
    missing = expected - names
    assert not missing, f"Gates 76/77/78 fields missing: {missing}"


def test_g2380_ui_fieldspecs_for_gate79_palliative_sedation():
    """H.G2380 — FieldSpecs para gate 79 (palliative sedation EAPC) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "palliative_sedation_initiation_planned", "end_of_life_stage_documented",
        "refractory_pain_palliative_failure", "refractory_dyspnea_terminal",
        "refractory_agitation_delirium_terminal",
        "palliative_sedation_eapc_criteria_met",
        "mdt_consensus_palliative_sedation_documented",
        "family_consent_palliative_sedation_documented",
        "palliative_sedation_agent_selected",
    }
    missing = expected - names
    assert not missing, f"Gate 79 fields missing: {missing}"


def test_g2381_ui_fieldspecs_for_gate80_esas():
    """H.G2381 — FieldSpecs para gate 80 (ESAS 9 ítems) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "esas_pain_score", "esas_fatigue_score", "esas_nausea_score",
        "esas_depression_score", "esas_anxiety_score", "esas_drowsiness_score",
        "esas_appetite_score", "esas_wellbeing_score", "esas_dyspnea_score",
        "esas_total_score", "esas_items_above_4_count",
    }
    missing = expected - names
    assert not missing, f"Gate 80 ESAS fields missing: {missing}"


def test_g2382_ui_fieldspecs_for_gate81_82_phq_gad():
    """H.G2382 — FieldSpecs para gates 81/82 (PHQ-9 + GAD-7) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "phq9_total_score", "phq9_item_9_suicidal_ideation",
        "clinical_depression_documented", "antidepressant_initiated",
        "gad7_total_score", "clinical_anxiety_disorder_documented",
        "anxiolytic_initiated",
    }
    missing = expected - names
    assert not missing, f"Gates 81/82 fields missing: {missing}"


def test_g2383_ui_fieldspecs_for_gate83_84_palliative_rt_sbrt():
    """H.G2383 — FieldSpecs para gates 83/84 (Palliative RT + Oligo SBRT) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "bone_metastasis_localized_painful", "hematuria_persistent_tumoral",
        "hemoptysis_tumoral_documented", "brain_metastases_documented",
        "palliative_rt_consideration_active", "palliative_rt_dose_fractionation_planned",
        "total_metastases_count", "life_expectancy_months",
        "oligometastatic_recurrence_metachronous", "oligoprogression_under_systemic_therapy",
        "oligometastatic_sbrt_candidate", "oligometastatic_category",
        "psma_pet_staging_recent",
    }
    missing = expected - names
    assert not missing, f"Gates 83/84 fields missing: {missing}"


def test_g2384_ui_fieldspecs_for_gate85_cachexia():
    """H.G2384 — FieldSpecs para gate 85 (Cachexia) registrados."""
    fields = pivotal_gate_supporting_fields()
    names = {f.name for f in fields}
    expected = {
        "weight_loss_percent_6mo", "bmi", "sarcopenia_documented",
        "appetite_loss_documented", "cachexia_clinical_diagnosed",
        "cachexia_stage", "current_weight_kg", "baseline_weight_kg",
        "albumin_g_dl", "prealbumin_mg_dl", "crp_mg_l",
    }
    missing = expected - names
    assert not missing, f"Gate 85 fields missing: {missing}"


# ──────────────────────────────────────────────────────────────────────
# §Q — Domain schema integration verification
# ──────────────────────────────────────────────────────────────────────


def test_g2385_m1_crpc_schema_includes_progression_fields():
    """H.G2385 — M1_CRPC_SCHEMA incluye fields gate 71-75 progression."""
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
    fields = M1_CRPC_SCHEMA.get("fields", [])
    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    assert "psma_new_lesion_count" in field_names
    assert "bpi_worst_pain_score" in field_names
    assert "ecog_current" in field_names


def test_g2386_m1_crpc_schema_includes_palliative_fields():
    """H.G2386 — M1_CRPC_SCHEMA incluye fields gate 76-85 palliative."""
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
    fields = M1_CRPC_SCHEMA.get("fields", [])
    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    assert "samarium_153_edtmp_candidate" in field_names
    assert "esas_pain_score" in field_names
    assert "phq9_total_score" in field_names


def test_g2387_total_yaml_gates_count_at_least_85():
    """H.G2387 — Total YAML gates loaded ≥85 (gates 1-85 base + future iters).

    Faubot LXXXIV: ampliado a 88 gates (+3 nuevos: 67B/67C/69B).
    Forward-compat para iteraciones futuras.
    """
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 85, f"Expected ≥85 gates, got {len(codes)}"
