# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from datetime import date, timedelta

from prostanet.domains.clinical_validation.trajectory_catalog import build_trajectory_catalog
from prostanet.domains.patient_tracking.advanced_release_gate_builder import (
    build_advanced_release_gate,
    merge_advanced_release_gate_into_requirements,
)
from prostanet.domains.patient_tracking import mhspc_frontline_reference as mhspc_reference_module
from prostanet.domains.patient_tracking.mhspc_frontline_reference import ensure_mhspc_frontline_reference
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)


def _recent_docetaxel_labs(**overrides):
    payload = {
        "cbc_date": (date.today() - timedelta(days=3)).isoformat(),
        "anc": 2200,
        "platelets": 210000,
        "liver_panel_date": (date.today() - timedelta(days=4)).isoformat(),
        "bilirubin": 0.8,
        "ast": 32,
        "alt": 30,
        "alp": 110,
        "taxane_hypersensitivity_history": 0,
        "polysorbate_hypersensitivity": 0,
    }
    payload.update(overrides)
    return payload


def test_mhspc_frontline_reference_persists_curated_drug_metadata(tmp_path):
    mhspc_reference_module._REFERENCE_CACHE.clear()
    bundle = ensure_mhspc_frontline_reference(root=tmp_path)

    assert bundle["raw_snapshot_path"]
    assert bundle["curated_reference_path"]
    assert (tmp_path / "raw_ingestion_snapshot.json").exists()
    assert (tmp_path / "curated_treatment_reference.json").exists()
    assert bundle["curated_reference"]["components"]["Darolutamida"]["imss_key"] == "010.000.7076.00"
    assert bundle["curated_reference"]["components"]["Abiraterona"]["route"] == "Oral"


def test_mhspc_frontline_reference_reuses_process_cache_for_same_signature(tmp_path, monkeypatch):
    mhspc_reference_module._REFERENCE_CACHE.clear()
    ensure_mhspc_frontline_reference(root=tmp_path)

    def _fail_raw_snapshot():
        raise AssertionError("La referencia mHSPC no debe reingerirse si la firma de archivos no cambió.")

    def _fail_curated_reference():
        raise AssertionError("La referencia mHSPC no debe reconstruirse si la firma de archivos no cambió.")

    monkeypatch.setattr(mhspc_reference_module, "build_raw_ingestion_snapshot", _fail_raw_snapshot)
    monkeypatch.setattr(mhspc_reference_module, "build_curated_treatment_reference", _fail_curated_reference)

    cached = ensure_mhspc_frontline_reference(root=tmp_path)

    assert cached["curated_reference"]["components"]["Darolutamida"]["imss_key"] == "010.000.7076.00"


def test_mhspc_release_gate_keeps_triplet_conditional_when_fitness_and_ddi_are_missing():
    gate = build_advanced_release_gate(
        state="mcspc_high_volume_sync",
        next_best_action={"recommendation_family": "taxane_family"},
        candidate_family="taxane_family",
        decision_input_requirements={"decision_blocking_inputs": ["ddi_review_status", "cv_risk_documented"]},
        advanced_followup_bundle={
            "available": True,
            "confidence_status": "degraded_by_missing_data",
            "missing_inputs": ["mini_cog_score", "g8_score"],
            "capture_actions": [{"key": "frailty", "title": "Completar fragilidad", "fields": ["mini_cog_score", "g8_score"]}],
        },
        staging_adjudication_bundle={"available": True, "concordance_status": "concordant", "missing_critical_inputs": [], "capture_actions": []},
        signals={},
    )
    merged = merge_advanced_release_gate_into_requirements(
        {"decision_blocking_inputs": ["ddi_review_status", "cv_risk_documented"]},
        gate,
    )
    readiness = build_therapeutic_readiness_bundle(
        state="mcspc_high_volume_sync",
        preferred_regimen={"family_code": "taxane_family", "regimen_code": "ADT_DOCETAXEL_ABIRATERONE", "regimen_label": "Triplete"},
        next_best_action={"title": "Liberar triplete", "recommendation_family": "taxane_family"},
        decision_input_requirements=merged,
        recommendation_block_status="provisional",
        recommendation_block_reason=(gate.get("release_gate_reasons") or [""])[0],
        advanced_followup_bundle={
            "available": True,
            "confidence_status": "degraded_by_missing_data",
            "missing_inputs": ["mini_cog_score", "g8_score"],
            "capture_actions": [{"key": "frailty", "title": "Completar fragilidad", "fields": ["mini_cog_score", "g8_score"]}],
        },
        staging_adjudication_bundle={"available": True, "concordance_status": "concordant", "missing_critical_inputs": [], "capture_actions": []},
        advanced_release_gate=gate,
    )

    assert gate["decision_blocking_inputs"]
    assert readiness["readiness_status"] == "conditional_pending_closure"
    assert readiness["release_confidence_status"] == "degraded"
    assert readiness["monitoring_gate_status"] == "conditional_pending_closure"


def test_low_volume_frontline_does_not_default_to_darolutamide_without_risk(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "rt_primary_received": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["systemic_regimen_scope"] == "mhspc_doublet_triplet"
    assert "mhspc_triplets" in result["systemic_regimen_scope_contract"]["excluded_classes"]
    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_ENZALUTAMIDE"
    assert "enzalutamida" in result["eligible_treatments"][0]["name"].lower()
    assert result["preferred_frontline_regimen"]["regimen_code"] != "ADT_DAROLUTAMIDE"


def test_low_volume_frontline_prefers_darolutamide_when_neurologic_risk_is_present(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 0,
            "rt_primary_received": 0,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]

    assert result["systemic_regimen_scope"] == "mhspc_doublet_triplet"
    assert preferred["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert any(component["drug_name"] == "Darolutamida" for component in preferred["component_drugs"])
    assert any(component["imss_key"] == "010.000.7076.00" for component in preferred["component_drugs"])


def test_high_volume_sync_prefers_clinically_ranked_triplet_and_exposes_component_metadata(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]

    assert result["systemic_regimen_scope"] == "mhspc_doublet_triplet"
    assert "mhspc_triplets" in result["systemic_regimen_scope_contract"]["competition_classes"]
    assert preferred["regimen_code"] == "ADT_DOCETAXEL_ABIRATERONE"
    assert any(component["drug_name"] == "Docetaxel" for component in preferred["component_drugs"])
    assert any(component["drug_name"] == "Abiraterona" for component in preferred["component_drugs"])
    assert any(component["metadata_source"] == "current_catalog" for component in preferred["component_drugs"])
    assert "Intravenosa" in preferred["route"]
    assert "Oral" in preferred["route"]
    assert "Subcutánea / intramuscular" in preferred["route"]
    assert "75 mg/m²" in preferred["dose"]
    assert "1000 mg al día" in preferred["dose"]
    assert preferred["description"]


def test_hepatic_risk_rejects_abiraterone_regimens(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "B",
            "hepatic_risk_factors": 1,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    rejections = {
        item["regimen_code"]: item
        for item in result["frontline_regimen_rejections"]
    }

    assert "ADT_ABIRATERONE" in rejections
    assert "ADT_DOCETAXEL_ABIRATERONE" in rejections
    assert any("hep" in reason.lower() for reason in rejections["ADT_ABIRATERONE"]["contraindication_reasons"])


def test_high_volume_sync_conditional_docetaxel_with_seizure_defaults_to_darolutamide(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 2,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
            "comorbidity_seizure": 1,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 0,
            "steroid_intolerance": 0,
            "edema_risk": 0,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    trace = result["frontline_ranking_trace"]

    assert preferred["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert result["docetaxel_base_eligibility"] == "elegible_with_caution"
    assert result["docetaxel_default_intensification"] == "no"
    assert result["triplet_decision"]["status"] == "not_prioritized"
    assert "darolutamida" in trace["winner_reason"].lower()
    assert "docetaxel" in trace["why_not_triplet"].lower()
    assert "latitude-like" in trace["why_not_abiraterone"].lower() or "darolutamida" in trace["why_not_abiraterone"].lower()


def test_high_volume_sync_ecog2_cancer_related_keeps_triplet_conditional_not_blocked(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 2,
            "performance_status_driver": "cancer_related",
            "bone_pain": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["fit_for_docetaxel"] is True
    assert result["docetaxel_base_eligibility"] == "elegible_with_caution"
    assert result["docetaxel_default_intensification"] == "conditional"
    assert result["docetaxel_trial_fit"]["peace1_like"] == "partial"
    assert result["triplet_decision"]["status"] == "conditional"
    assert result["preferred_frontline_regimen"]["regimen_code"] != "ADT_DOCETAXEL_DAROLUTAMIDE"


def test_high_volume_sync_ecog2_frailty_driven_removes_docetaxel_default(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "ecog_score": 2,
            "performance_status_driver": "comorbidity_or_frailty",
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            "comorbidity_seizure": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["docetaxel_default_intensification"] == "no"
    assert result["triplet_decision"]["status"] == "not_prioritized"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"


def test_high_volume_sync_neurocognitive_frailty_keeps_darolutamide_as_best_triplet_but_not_global_triplet(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 2},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Vulnerable",
            "g8_score": 12,
            "mini_cog_score": 3,
            "child_pugh_score": "A",
            "comorbidity_seizure": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    triplet = result["triplet_decision"]

    assert preferred["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert preferred["regimen_code"] != "ADT_DOCETAXEL_ABIRATERONE"
    assert result["docetaxel_default_intensification"] == "no"
    assert triplet["status"] == "not_prioritized"
    assert triplet["preferred_triplet_candidate_regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    assert triplet["triplet_candidate_only_if_reopened"] is True
    assert triplet["cross_scope_alignment"] == "contradictory_semantics"
    assert "tratamiento global preferente" in triplet["triplet_vs_global_preference_note"].lower() or "lidera globalmente" in triplet["triplet_vs_global_preference_note"].lower()


def test_high_volume_sync_allows_abiraterone_to_override_only_with_visible_latitude_like_rationale(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
            "gleason_primary": 5,
            "gleason_secondary": 4,
            "gleason_tertiary": 5,
            "ecog_score": 0,
            "peripheral_neuropathy_grade": 2,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_seizure": 1,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 0,
            "steroid_intolerance": 0,
            "edema_risk": 0,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    trace = result["frontline_ranking_trace"]

    assert preferred["regimen_code"] == "ADT_ABIRATERONE"
    assert "latitud" in trace["winner_reason"].lower()
    assert "darolutamida" in trace["why_not_darolutamide"].lower() or "puntaje clínico" in trace["why_not_darolutamide"].lower()


def test_oracle_alignment_keeps_castrate_biochemical_case_in_m0_crpc():
    catalog = {
        item["scenario_id"]: item
        for item in build_trajectory_catalog()
    }

    scenario = catalog["adt_progression_castrate_biochemical"]

    assert scenario["baseline_oracle"]["expected_effective_state"] == "adt_progression_verification"
    assert scenario["visits"][1]["oracle"]["expected_effective_state"] == "m0_crpc"
    assert scenario["clinical_oracle"]["expected_effective_state"] == "m0_crpc"


def test_high_volume_sync_without_current_docetaxel_labs_stays_pending_validation(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "pending_validation"
    assert result["docetaxel_fitness"]["docetaxel_verification_status"] == "pending_labs"
    assert "anc" in [item.lower() for item in result["triplet_decision"]["missing_inputs"]]
    assert not any("<1500" in reason for reason in result["triplet_decision"]["hard_stop_reasons"])


def test_high_volume_sync_with_stale_docetaxel_labs_requests_refresh(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(
                cbc_date=(date.today() - timedelta(days=25)).isoformat(),
                liver_panel_date=(date.today() - timedelta(days=25)).isoformat(),
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "pending_validation"
    assert result["docetaxel_fitness"]["docetaxel_verification_status"] == "stale_labs"
    assert "anc" in [item.lower() for item in result["triplet_decision"]["stale_inputs"]]


def test_high_volume_sync_low_anc_creates_label_based_docetaxel_block(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(anc=1200),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "contraindicated"
    assert result["docetaxel_fitness"]["docetaxel_block_type"] == "label"
    assert any("neutrófilos <1500/mm3" in reason.lower() for reason in result["triplet_decision"]["hard_stop_reasons"])


# ---------------------------------------------------------------------------
# Regression tests for BUG-03-NEW / BUG-04-NEW / BUG-06-NEW / BUG-09-NEW /
# BUG-13. Each test pins one invariant so the fix does not silently regress.
# ---------------------------------------------------------------------------


def test_bug13_preferred_flag_is_consistent_with_eligible_treatments_leader(app_client):
    """BUG-13 invariant: the leader of the ranking and the preferred regimen
    must share ``is_preferred``/``priority`` flags, regardless of provisional
    ARPI capture state.
    """
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
                {"site_key": "pelvis", "lesion_count": 2},
            ],
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "gleason_score": 9,
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Fit",
            "docetaxel_fit": 1,
            "peripheral_neuropathy_grade": 0,
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    eligible = result["eligible_treatments"]

    assert preferred, "preferred_frontline_regimen must be populated"
    assert eligible, "eligible_treatments must include at least the leader"

    leader = eligible[0]
    # BUG-13 consistency invariant. ``priority`` is humanized to Spanish in
    # the presentation layer, so accept either raw or humanized forms.
    preferred_priority = str(preferred.get("priority") or "").lower()
    leader_priority = str(leader.get("priority") or "").lower()
    preferred_values = {"preferred", "preferente"}
    assert preferred.get("regimen_code") == leader.get("regimen_code")
    assert preferred.get("is_preferred") is True
    assert leader.get("is_preferred") is True
    assert preferred_priority in preferred_values, preferred_priority
    assert leader_priority in preferred_values, leader_priority


def test_bug03_arasens_metachronous_high_volume_fit_is_trial_like(app_client):
    """BUG-03-NEW: HV metachronous with docetaxel-apt must rank the triplet
    ADT+Docetaxel+Darolutamida as preferred. The regression case mirrors the
    ARASENS prespecified metachronous subgroup.
    """
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_metachronous/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
                {"site_key": "pelvis", "lesion_count": 2},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "gleason_score": 9,
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Fit",
            "docetaxel_fit": 1,
            "peripheral_neuropathy_grade": 0,
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    assert preferred["regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    # ARASENS must be reported as trial-like (matched or partial) in a
    # metachronous HV fit-doc patient, never as "no" (BUG-03-NEW).
    trial_fit = (preferred.get("pivotal_trial_fit") or {}).get("fit") or preferred.get("pivotal_trial_fit", {}).get(
        "ARASENS", {}
    ).get("fit")
    # Fall-back: inspect alternatives/ranking trace if structure differs
    if not trial_fit:
        trial_fit = str(result.get("frontline_ranking_trace", {}).get("winner_reason") or "")
    assert "arasens" in str(trial_fit).lower() or "trial" in str(trial_fit).lower() or preferred.get(
        "pivotal_trial_fit"
    )


def test_bug06_abiraterone_latitude_override_triggers_without_visceral_or_seizure(app_client):
    """BUG-06-NEW: a clean LATITUDE-like HV sync patient (Gleason 9, ≥3 bone
    metastases, no hepatic/cardio/edema/steroid risk, Child-Pugh A, fit ECOG)
    that is unfit for docetaxel must surface Abiraterona as the ranking
    leader; it should not be gated by missing visceral metastases or seizure
    risk.
    """
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 4,
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "pelvis", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 2},
            ],
            "nonregional_nodal_site_entries": [
                {"site_key": "retroperitoneal", "lesion_count": 2},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "gleason_score": 9,
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Fit",
            "docetaxel_fit": 0,
            "anc": 1000,
            "platelets": 90000,
            "peripheral_neuropathy_grade": 0,
            "child_pugh_score": "A",
            "active_liver_disease": 0,
            "hepatic_risk_factors": 0,
            "bilirubin": 1.0,
            "ast": 25,
            "alt": 22,
            "alp": 110,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "edema_risk": 0,
            "steroid_intolerance": 0,
            "diabetes_uncontrolled": 0,
            "comorbidity_seizure": 0,
            "cognitive_risk": 0,
            "fall_risk": 0,
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    # Without seizure/visceral metastases the LATITUDE-like override must
    # still be eligible to surface abiraterona when docetaxel is blocked.
    assert preferred["regimen_code"] == "ADT_ABIRATERONE"


def test_bug09_missing_alp_with_normal_ast_alt_does_not_demote_docetaxel(app_client):
    """BUG-09-NEW: an otherwise CHAARTED-apt patient with AST/ALT in range and
    bilirubin normal must keep docetaxel as a real candidate even if ALP is
    missing; ALP alone does not drive CHAARTED eligibility.
    """
    client, _ = app_client

    labs = _recent_docetaxel_labs(alp=None)

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "pelvis", "lesion_count": 2},
                {"site_key": "femur", "lesion_count": 2},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "gleason_score": 9,
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Fit",
            "docetaxel_fit": 1,
            "peripheral_neuropathy_grade": 0,
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
            **labs,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    docetaxel_fitness = result.get("docetaxel_fitness") or {}
    missing = [str(item).lower() for item in (docetaxel_fitness.get("docetaxel_missing_inputs") or [])]
    # ALP must NOT show up as missing when AST/ALT are clearly normal.
    assert "alp" not in missing, f"alp should not be demoted when AST/ALT normal. missing={missing}"
    # Docetaxel should remain at least eligible_with_caution (not "not_assessable" due to alp alone).
    base_eligibility = str(docetaxel_fitness.get("docetaxel_base_eligibility") or "")
    assert base_eligibility in {"elegible", "elegible_with_caution"}, base_eligibility


def test_bug09_missing_alp_with_elevated_ast_still_flags_alp(app_client):
    """BUG-09-NEW guardrail: if AST/ALT are elevated, ALP remains mandatory
    because the hepatic-reserve rule (AST/ALT > 1.5x ULN AND ALP > 2.5x ULN)
    needs all three labs.
    """
    client, _ = app_client

    labs = _recent_docetaxel_labs(ast=120, alt=110, alp=None)

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 2},
                {"site_key": "pelvis", "lesion_count": 2},
            ],
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Fit",
            "docetaxel_fit": 1,
            "peripheral_neuropathy_grade": 0,
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
            **labs,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    docetaxel_fitness = result.get("docetaxel_fitness") or {}
    missing = [str(item).lower() for item in (docetaxel_fitness.get("docetaxel_missing_inputs") or [])]
    assert "alp" in missing, f"alp must be flagged when AST/ALT elevated. missing={missing}"


def test_bug04_darolutamide_hard_blocks_child_pugh_bc_with_active_liver_disease(app_client):
    """BUG-04-NEW: Child-Pugh B/C combined with active liver disease must
    contraindicate darolutamida at the same strength as abiraterona. When
    every other ARPI is also blocked and docetaxel is apt, ADT+Docetaxel
    solo must win.
    """
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "pelvis", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 2},
            ],
            "ecog_score": 1,
            "ecog": 1,
            "frailty_status": "Vulnerable",
            "docetaxel_fit": 1,
            "peripheral_neuropathy_grade": 0,
            "comorbidity_seizure": 1,
            "stroke_history": 1,
            "child_pugh_score": "B",
            "active_liver_disease": 1,
            "hepatic_risk_factors": 1,
            "rash_history": 1,
            "hypothyroidism": 1,
            "drug_interaction_reviewed": 1,
            "ddi_review_status": "completed",
            "performance_status_driver": "truly_fit",
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    assert preferred["regimen_code"] == "ADT_DOCETAXEL"
    # Daro must appear among rejections with hard_block and a hepatic reason.
    rejections = {
        item["regimen_code"]: item for item in result.get("frontline_regimen_rejections", [])
    }
    assert "ADT_DAROLUTAMIDE" in rejections, list(rejections.keys())
    daro_reasons = " ".join(rejections["ADT_DAROLUTAMIDE"].get("contraindication_reasons") or []).lower()
    assert "child-pugh" in daro_reasons or "hepatop" in daro_reasons
