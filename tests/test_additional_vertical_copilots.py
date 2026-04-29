# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import uuid

from prostanet.domains.clinical_validation.trajectory_catalog import build_trajectory_catalog
from prostanet.domains.clinical_validation.trajectory_seed_service import seed_trajectory_case


def _enable_new_verticals(monkeypatch, *, mode="shadow"):
    monkeypatch.setenv("ENABLE_MHSPC_COPILOT", "1")
    monkeypatch.setenv("ENABLE_DIAGNOSTIC_BIOPSY_COPILOT", "1")
    monkeypatch.setenv("ENABLE_LOCALIZED_SURVEILLANCE_COPILOT", "1")
    monkeypatch.setenv("ENABLE_POST_RT_SALVAGE_COPILOT", "1")
    monkeypatch.setenv("PROSTANET_AI_RUNTIME_MODE", mode)
    import prostanet.ai.config as ai_config_module

    monkeypatch.setattr(ai_config_module, "_config", None, raising=False)


def _trajectory(scenario_id: str) -> dict:
    for item in build_trajectory_catalog():
        if item.get("scenario_id") == scenario_id:
            return dict(item)
    raise AssertionError(f"Scenario {scenario_id} not found in trajectory catalog")


def _seed_case(scenario_id: str) -> dict:
    return seed_trajectory_case(
        _trajectory(scenario_id),
        run_id=uuid.uuid4().hex,
        case_index=1,
    )


def test_mhspc_copilot_low_volume_sync_exposes_rt_primary_and_endpoint(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    client, _ = app_client

    case = _seed_case("mhspc_low_volume_sync_doublet")
    patient_ref = case["patient_nss"]
    bundle = case["final"]["longitudinal_bundle"]["mhspc_copilot_bundle"]

    assert bundle["available"] is True
    assert bundle["effective_state"] == "mcspc_low_volume_sync_oligo"
    assert bundle["rt_primary_candidate"] is True
    assert bundle["preferred_frontline_regimen"]
    assert bundle["status"] in {"shadow", "shadow-blocked"}

    endpoint_response = client.get(f"/api/mhspc-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["success"] is True
    assert endpoint_payload["mhspc_decision_bundle"]["effective_state"] == "mcspc_low_volume_sync_oligo"

    schedule_response = client.get(f"/api/patients/{patient_ref}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["mhspc_copilot_status"] in {"shadow", "shadow-blocked"}
    assert "mhspc_schedule_overlay" in schedule_payload

    profile_response = client.get(f"/patient_profile/{patient_ref}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Copiloto mHSPC" in profile_html
    profile_html_lower = profile_html.lower()
    assert (
        "frontline preferente" in profile_html_lower
        or "régimen frontline preferente" in profile_html_lower
        or "gate de progresión / recomendación final" in profile_html_lower
    )


def test_mhspc_copilot_high_volume_fit_keeps_triplet_visible(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    _client, _ = app_client

    case = _seed_case("mhspc_high_volume_triplet")
    bundle = case["final"]["longitudinal_bundle"]["mhspc_copilot_bundle"]

    assert bundle["available"] is True
    assert bundle["effective_state"] in {"mcspc_high_volume", "mcspc_high_volume_sync"}
    assert bundle["docetaxel_fitness"]["eligible"] is True
    assert (bundle.get("triplet_decision") or {}).get("status") in {"recommended", "eligible", "conditional"}
    triplet_text = " ".join(
        [
            str((bundle.get("triplet_decision") or {}).get("decision") or ""),
            str((bundle.get("triplet_decision") or {}).get("summary") or ""),
            str((bundle.get("triplet_decision") or {}).get("status_label") or ""),
            str((bundle.get("triplet_decision") or {}).get("primary_reason") or ""),
            str((bundle.get("triplet_decision") or {}).get("preferred_triplet_backbone_label") or ""),
            str((bundle.get("preferred_frontline_regimen") or {}).get("regimen_label") or ""),
        ]
    ).lower()
    assert "triplet" in triplet_text or "triplete" in triplet_text or "docetaxel" in triplet_text


def test_diagnostic_copilot_crosses_biopsy_threshold_when_signal_is_high(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    client, _ = app_client

    case = _seed_case("diagnostic_high_targeted_biopsy")
    patient_ref = case["patient_nss"]
    bundle = case["final"]["longitudinal_bundle"]["diagnostic_biopsy_bundle"]

    assert bundle["available"] is True
    assert bundle["diagnostic_track"] == "targeted_biopsy_ready"
    assert bundle["biopsy_readiness"]["ready"] is True
    assert "biops" in bundle["rule_based_recommendation"]["recommended_action"].lower()

    endpoint_response = client.get(f"/api/diagnostic-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["diagnostic_decision_bundle"]["diagnostic_track"] == "targeted_biopsy_ready"


def test_diagnostic_copilot_reopens_path_after_negative_biopsy(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    _client, _ = app_client

    case = _seed_case("post_negative_biopsy_reopen_due_to_mri")
    bundle = case["final"]["longitudinal_bundle"]["diagnostic_biopsy_bundle"]

    assert bundle["available"] is True
    assert bundle["effective_state"] == "post_negative_biopsy_followup"
    assert bundle["reopen_signal_after_negative_biopsy"] is True
    assert bundle["diagnostic_track"] == "reopen_after_negative_biopsy"


def test_localized_copilot_keeps_stable_active_surveillance_visible(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    client, _ = app_client

    case = _seed_case("active_surveillance_entry")
    patient_ref = case["patient_nss"]
    bundle = case["final"]["longitudinal_bundle"]["localized_surveillance_bundle"]

    assert bundle["available"] is True
    assert bundle["localized_track"] == "stable_active_surveillance"
    assert bundle["active_surveillance_course"]["has_data"] is True
    preferred_text = str((bundle.get("preferred_local_strategy") or {}).get("name") or (bundle.get("preferred_local_strategy") or {}).get("label") or "").lower()
    assert "vigilancia activa" in preferred_text

    endpoint_response = client.get(f"/api/localized-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["localized_decision_bundle"]["localized_track"] == "stable_active_surveillance"


def test_localized_copilot_exits_as_when_upgrade_detected(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    _client, _ = app_client

    case = _seed_case("active_surveillance_upgrade_conversion")
    bundle = case["final"]["longitudinal_bundle"]["localized_surveillance_bundle"]

    assert bundle["available"] is True
    assert bundle["localized_track"] == "as_exit_due_to_upgrade"
    preferred_text = str((bundle.get("preferred_local_strategy") or {}).get("name") or (bundle.get("preferred_local_strategy") or {}).get("label") or "").lower()
    assert "surveillance" not in preferred_text


def test_post_rt_copilot_keeps_local_salvage_visible_and_endpoint_resolves(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    client, _ = app_client

    case = _seed_case("post_rt_local_salvage_candidate")
    patient_ref = case["patient_nss"]
    bundle = case["final"]["longitudinal_bundle"]["post_rt_salvage_bundle"]

    assert bundle["available"] is True
    assert bundle["effective_state"] == "post_radiotherapy_or_local_salvage"
    assert bundle["post_rt_course"] == "local_salvage_candidate"
    assert bundle["post_rt_salvage_window_status"] == "local_salvage_candidate"
    assert bundle["local_salvage_pathway"]["visible"] is True
    assert bundle["post_rt_failure_definition"]["phoenix_status"] == "met"
    assert bundle["post_rt_transition_bundle"]["transition_status"] == "local_salvage_candidate"

    endpoint_response = client.get(f"/api/post-rt-copilot/{patient_ref}")
    assert endpoint_response.status_code == 200
    endpoint_payload = endpoint_response.get_json()
    assert endpoint_payload["post_rt_decision_bundle"]["post_rt_course"] == "local_salvage_candidate"

    signals_response = client.get(f"/api/patients/{patient_ref}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["post_rt_copilot_status"] in {"shadow", "shadow-blocked"}
    assert signals_payload["post_rt_salvage_window_status"] == "local_salvage_candidate"
    assert signals_payload["next_best_action"]["title"] == "Priorizar Salvage prostatectomy"
    assert signals_payload["next_best_action"]["recommendation_family"] == "Salvage prostatectomy"
    assert "vigilancia post prostatectomía" not in signals_payload["next_best_action"]["title"].lower()

    next_action_response = client.get(f"/api/patients/{patient_ref}/next-best-action")
    assert next_action_response.status_code == 200
    next_action_payload = next_action_response.get_json()
    assert next_action_payload["next_best_action"]["title"] == "Priorizar Salvage prostatectomy"
    assert next_action_payload["next_best_action"]["recommendation_family"] == "Salvage prostatectomy"

    profile_response = client.get(f"/patient_profile/{patient_ref}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Copiloto post-RT" in profile_html
    assert "Priorizar Salvage prostatectomy" in profile_html
    assert "Mantener vigilancia post prostatectomía y control bioquímico" not in profile_html


def test_post_rt_copilot_redirects_systemic_when_psma_is_disseminated(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    _client, _ = app_client

    case = _seed_case("post_rt_systemic_redirection")
    bundle = case["final"]["longitudinal_bundle"]["post_rt_salvage_bundle"]

    assert bundle["available"] is True
    assert bundle["post_rt_course"] == "redirect_systemic"
    assert bundle["post_rt_salvage_window_status"] == "redirect_systemic"
    assert bundle["local_salvage_pathway"]["visible"] is False
    assert bundle["post_rt_transition_bundle"]["transition_status"] == "redirect_systemic"
    assert bundle["systemic_redirection_status"]["redirected"] is True


def test_post_rt_copilot_holds_pending_confirmation_until_phoenix_or_local_failure_closes(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    _client, _ = app_client

    case = _seed_case("post_rt_psa_rise_restage")
    bundle = case["final"]["longitudinal_bundle"]["post_rt_salvage_bundle"]

    assert bundle["available"] is True
    assert bundle["post_rt_course"] == "pending_confirmation"
    assert bundle["post_rt_salvage_window_status"] == "pending_confirmation"
    assert bundle["post_rt_failure_definition"]["phoenix_status"] == "not_met"
    assert bundle["local_salvage_pathway"]["visible"] is False


def test_dashboard_research_intelligence_exposes_new_vertical_summaries(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)
    client, _ = app_client

    _seed_case("mhspc_low_volume_sync_doublet")
    _seed_case("diagnostic_high_targeted_biopsy")
    _seed_case("active_surveillance_entry")
    _seed_case("post_rt_local_salvage_candidate")

    response = client.get("/api/dashboard/research-intelligence")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["mhspc_copilot"]["available"] is True
    assert payload["diagnostic_biopsy_copilot"]["available"] is True
    assert payload["localized_surveillance_copilot"]["available"] is True
    assert payload["post_rt_salvage_copilot"]["available"] is True

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    dashboard_html = dashboard_response.get_data(as_text=True)
    assert "Copiloto mHSPC" in dashboard_html
    assert "Copiloto diagnóstico" in dashboard_html
    assert "Copiloto localizado / AS" in dashboard_html
    assert "Copiloto post-RT" in dashboard_html


def test_vertical_bundles_expose_histopathology_and_decision_delta_contract(app_client, monkeypatch):
    _enable_new_verticals(monkeypatch)

    mhspc_case = _seed_case("mhspc_high_volume_triplet")
    localized_case = _seed_case("active_surveillance_entry")
    post_rt_case = _seed_case("post_rt_local_salvage_candidate")

    mhspc_bundle = mhspc_case["final"]["longitudinal_bundle"]["mhspc_copilot_bundle"]
    localized_bundle = localized_case["final"]["longitudinal_bundle"]["localized_surveillance_bundle"]
    post_rt_bundle = post_rt_case["final"]["longitudinal_bundle"]["post_rt_salvage_bundle"]

    assert "histopathology_summary" in mhspc_bundle
    assert "histopathology_summary" in post_rt_bundle
    assert "Gleason" in str(localized_bundle.get("histopathology_summary") or "")

    for bundle in (mhspc_bundle, localized_bundle, post_rt_bundle):
        assert bundle.get("effective_management_track") is not None
        assert isinstance(bundle.get("decision_delta_since_last_visit"), dict)
        assert isinstance(bundle.get("evidence_basis_current_visit"), list)
        assert isinstance(bundle.get("blocked_by_overlay"), list)
