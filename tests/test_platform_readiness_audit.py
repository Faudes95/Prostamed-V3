import io
import json
import time
import zipfile

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.platform_readiness.ape_longitudinal_completion_sprint import (
    build_ape_capture_impact,
    build_ape_longitudinal_completion_csv_bytes,
    build_ape_longitudinal_completion_sprint,
    build_patient_ape_completion_snapshot,
)
from prostanet.domains.platform_readiness.audit import build_platform_readiness_audit
from prostanet.domains.platform_readiness.capture_integrity import (
    build_capture_integrity_readiness,
)
from prostanet.domains.platform_readiness.v2_persistence_closure import (
    build_v2_initial_staging_persistence_closure,
)
from prostanet.domains.platform_readiness.v2_treatment_value_closure import (
    build_v2_treatment_value_closure,
)
from prostanet.domains.platform_readiness.deidentified_export_contract import (
    build_deidentified_export_contract,
)
from prostanet.domains.platform_readiness.external_validation_worklist import (
    build_external_validation_worklist,
    build_external_validation_worklist_csv_bytes,
)
from prostanet.domains.platform_readiness.interoperability_map import build_interoperability_map
from prostanet.domains.platform_readiness.ledger_release_gate import build_ledger_release_gate
from prostanet.domains.platform_readiness.ledger_persistence_matrix import (
    build_ledger_persistence_matrix,
)
from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
    build_nas_pilot_evidence_vault,
    build_nas_pilot_evidence_vault_zip_bytes,
)
from prostanet.domains.platform_readiness.pilot_adoption_command_center import (
    build_pilot_adoption_command_center,
)
from prostanet.domains.platform_readiness.prospective_pilot_governance import (
    build_prospective_pilot_governance_pack,
)
from prostanet.domains.platform_readiness.prospective_real_world_completion_queue import (
    build_prospective_real_world_completion_csv_bytes,
    build_prospective_real_world_completion_queue,
)
from prostanet.domains.platform_readiness.real_world_first_patient_launch_mode import (
    build_real_world_first_patient_launch_mode,
    build_real_world_first_patient_launch_mode_markdown_bytes,
)
from prostanet.domains.platform_readiness.real_world_launch_flow_verifier import (
    build_real_world_launch_flow_verifier,
    build_real_world_launch_flow_verifier_markdown_bytes,
)
from prostanet.domains.platform_readiness.real_world_pilot_execution_log import (
    build_real_world_pilot_execution_log,
    build_real_world_pilot_execution_log_markdown_bytes,
)
from prostanet.domains.platform_readiness.real_world_pilot_packet import (
    build_real_world_pilot_packet,
    build_real_world_pilot_packet_markdown_bytes,
)
from prostanet.domains.platform_readiness.real_world_sample_maturity import (
    build_real_world_sample_maturity_csv_bytes,
    build_real_world_sample_maturity_gate,
)
from prostanet.domains.platform_readiness.prospective_gap_closure_huddle import (
    build_prospective_gap_closure_huddle,
    build_prospective_gap_huddle_csv_bytes,
)
from prostanet.domains.platform_readiness.research_pack_governance import (
    build_research_pack_freeze_library,
)
from prostanet.domains.platform_readiness.research_pack_materializer import (
    build_research_pack_materializer,
)
from prostanet.domains.platform_readiness.world_class_benchmark import (
    build_world_class_benchmark_radar,
)
from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload
from prostanet.shared.clinical_fact_registry import extract_canonical_fact_candidates
from prostanet.shared.presentation_text import humanize_schema


def test_platform_readiness_audit_is_read_only_and_maps_canonical_facts():
    audit = build_platform_readiness_audit(ModuleRegistry(), field_limit=500)

    assert audit["available"] is True
    assert audit["read_only"] is True
    assert audit["source_clinical_facts_mutated"] is False
    assert audit["external_order_created"] is False
    assert audit["model_trained"] is False
    assert audit["summary"]["modules_scanned"] >= 10
    assert audit["summary"]["fact_specs_total"] > 50

    psa_density = next(row for row in audit["field_matrix"] if row["fact_key"] == "psa_density")
    assert "psad" in psa_density["legacy_aliases"]
    assert psa_density["schema_appearances_count"] >= 1
    assert set(psa_density["direct_schema_fields"] + psa_density["legacy_alias_schema_fields"]) & {
        "psa_density",
        "psad",
    }
    baseline_psa = next(row for row in audit["field_matrix"] if row["fact_key"] == "baseline_psa")
    assert "psa" in baseline_psa["legacy_alias_schema_fields"]
    total_cores = next(row for row in audit["field_matrix"] if row["fact_key"] == "total_cores_biopsied")
    assert "total_cores" in total_cores["legacy_alias_schema_fields"]
    metastatic_stage = next(row for row in audit["field_matrix"] if row["fact_key"] == "metastatic_stage_resolved")
    assert metastatic_stage["coverage_status"] == "documented_non_schema_source"
    clinical_tstage = next(row for row in audit["field_matrix"] if row["fact_key"] == "clinical_tstage")
    assert "clinical_t_stage" in clinical_tstage["legacy_aliases"]
    assert clinical_tstage["schema_appearances_count"] >= 1
    num_cores = next(row for row in audit["field_matrix"] if row["fact_key"] == "num_cores_positive")
    assert "positive_cores" in num_cores["legacy_aliases"]
    assert num_cores["schema_appearances_count"] >= 1
    unregistered_moderate = {
        (gap.get("module"), gap.get("field"))
        for gap in audit["gaps"]
        if gap.get("category") == "schema_field_without_fact_spec"
    }
    assert ("localized_initial", "clinical_tstage") not in unregistered_moderate
    assert ("localized_initial", "num_cores_positive") not in unregistered_moderate
    assert not any(field == "metastatic_components_capture" for _, field in unregistered_moderate)
    duplicate_gap_modules = {
        gap.get("module")
        for gap in audit["gaps"]
        if gap.get("category") == "duplicate_field_name_in_schema"
    }
    assert "diagnostic_workup" not in duplicate_gap_modules
    assert "m1_crpc" not in duplicate_gap_modules


def test_platform_readiness_audit_detects_schema_and_route_contracts(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/audit?scope=summary")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["scope"] == "summary"
    assert payload["route_contracts"]["missing_count"] == 0
    assert payload["database_snapshot"]["available"] is True
    assert payload["summary"]["modules_scanned"] >= 10
    assert payload["summary"]["high_gap_count"] <= 2
    assert "field_matrix" not in payload


def test_capture_integrity_readiness_maps_no_recapture_and_stage_relevance():
    payload = build_capture_integrity_readiness(ModuleRegistry(), scope="full")

    assert payload["available"] is True
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["next_layer_allowed"] is True
    assert payload["summary"]["capture_integrity_status"] == "capture_integrity_ready"

    checks = {row["key"]: row for row in payload["checks"]}
    expected = {
        "diagnostic_wizard_single_ape",
        "diagnostic_psad_is_derived_or_override_only",
        "localized_wizard_single_ape",
        "localized_psad_is_derived",
        "localized_systemic_noise_deferred",
        "localized_systemic_contraindications_gated",
        "localized_evaluate_tolerates_unavailable_psad",
        "diagnostic_dre_t2a_to_t4_is_suspicious",
        "diagnostic_registration_psa_history_only",
        "localized_registration_psa_history_only",
        "localized_registration_no_systemic_labs",
        "localized_registration_no_unselected_as_rt",
        "advanced_registration_keeps_systemic_context",
        "localized_longitudinal_router_single_ape",
        "localized_longitudinal_router_no_systemic_noise",
        "diagnostic_longitudinal_router_no_manual_psad",
        "diagnostic_longitudinal_router_no_systemic_noise",
        "multistage_wizard_systemic_gate_noise_deferred",
        "multistage_longitudinal_router_stage_specific",
    }
    assert expected.issubset(checks)
    assert all(checks[key]["status"] == "pass" for key in expected)
    assert checks["localized_registration_psa_history_only"]["evidence"]["psa_related_visible"] == ["psa_history"]
    assert checks["localized_registration_no_systemic_labs"]["evidence"]["visible_systemic_fields"] == []
    assert checks["localized_registration_no_unselected_as_rt"]["evidence"]["visible_route_fields"] == []
    assert checks["localized_longitudinal_router_single_ape"]["evidence"]["psa_related_visible"] == ["psa_value"]
    assert checks["diagnostic_longitudinal_router_no_manual_psad"]["evidence"]["psa_related_visible"] == ["prostate_volume_ml", "psa_value"]
    assert checks["multistage_wizard_systemic_gate_noise_deferred"]["evidence"]["visible_noise_by_module"]["mcspc_high_volume_sync"] == []
    assert checks["multistage_longitudinal_router_stage_specific"]["evidence"]["m1_relevant"] == [
        "ctcae_grade_max",
        "ecog_score",
        "psa_value",
        "testosterone_value",
    ]


def test_capture_integrity_api_is_read_only(app_client):
    client, _db_path = app_client

    summary = client.get("/api/platform-readiness/capture-integrity?scope=summary")
    assert summary.status_code == 200
    payload = summary.get_json()
    assert payload["success"] is True
    assert payload["scope"] == "summary"
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["summary"]["critical_failure_count"] == 0
    assert "checks" not in payload

    full = client.get("/api/platform-readiness/capture-integrity?scope=full")
    assert full.status_code == 200
    assert full.get_json()["checks"]


def test_v2_initial_staging_persistence_closure_gate_maps_e2e_contracts():
    payload = build_v2_initial_staging_persistence_closure(
        registered_rules=[
            "/api/clinical-assessments/draft",
            "/api/register_patient",
            "/api/patients/<patient_ref>/clinical-fact-ledger/summary",
            "/api/patients/<patient_ref>/decision-today",
            "/api/patients/<patient_ref>/schedule",
            "/patient_profile/<nss>",
            "/api/platform-readiness/capture-integrity",
        ],
        capture_integrity={"summary": {"capture_integrity_status": "capture_integrity_ready"}},
        scope="full",
    )

    assert payload["available"] is True
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["real_database_mutated"] is False
    assert payload["isolated_database_required"] is True
    assert payload["next_layer_allowed"] is True
    assert payload["summary"]["v2_persistence_closure_status"] == "v2_persistence_closure_ready"
    assert payload["summary"]["critical_failure_count"] == 0
    assert "biomarker_longitudinal" in payload["summary"]["proven_surfaces"]
    assert "patient_profile_v2" in payload["summary"]["proven_surfaces"]
    assert payload["dry_run_command"] == "python3 -m pytest -q tests/test_v2_initial_staging_persistence_closure.py"

    checks = {row["key"]: row for row in payload["verification_matrix"]}
    for key in {
        "dry_run_blocks_ape_recapture",
        "dry_run_asserts_biomarker_persistence",
        "dry_run_asserts_latest_assessment",
        "dry_run_asserts_ledger_decision_schedule",
        "profile_v2_has_psa_treatment_timeline",
        "profile_v2_has_clinical_fact_ledger_panel",
        "capture_integrity_gate_green",
    }:
        assert checks[key]["status"] == "pass"


def test_v2_persistence_closure_api_is_read_only(app_client):
    client, _db_path = app_client

    summary = client.get("/api/platform-readiness/v2-persistence-closure?scope=summary")
    assert summary.status_code == 200
    payload = summary.get_json()
    assert payload["success"] is True
    assert payload["scope"] == "summary"
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["real_database_mutated"] is False
    assert payload["summary"]["critical_failure_count"] == 0
    assert "verification_matrix" not in payload

    full = client.get("/api/platform-readiness/v2-persistence-closure?scope=full")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert full_payload["verification_matrix"]
    assert full_payload["flow_contract"]["longitudinal_series"] == ["psa_history"]


def test_v2_treatment_value_closure_gate_maps_profile_v2_contracts():
    payload = build_v2_treatment_value_closure(
        registered_rules=[
            "/patient_profile/<nss>",
            "/api/patients/<patient_ref>/treatment-course/current",
            "/api/patients/<patient_ref>/treatment-course",
            "/api/patients/<patient_ref>/treatment-course/<int:course_id>/dose",
            "/api/patients/<patient_ref>/treatment-economic-impact",
            "/api/analytics/arpi-spend",
            "/api/analytics/price-catalog-audit",
            "/api/analytics/arpi-real-world-value",
            "/api/analytics/treatment-value-registry",
            "/population/treatment-value-registry",
        ],
        scope="full",
    )

    assert payload["available"] is True
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["real_database_mutated"] is False
    assert payload["isolated_database_required"] is True
    assert payload["next_layer_allowed"] is True
    assert payload["summary"]["v2_treatment_value_closure_status"] == "v2_treatment_value_closure_ready"
    assert payload["summary"]["critical_failure_count"] == 0
    assert payload["summary"]["triplet_reference_scenario"]["warning_arpi_spend_mxn"] == 190000.0
    assert payload["summary"]["triplet_reference_scenario"]["critical_arpi_spend_mxn"] == 285000.0
    assert "patient_profile_v2" in payload["summary"]["proven_surfaces"]
    assert "treatment_value_registry_v2" in payload["summary"]["proven_surfaces"]
    assert payload["dry_run_command"] == "python3 -m pytest -q tests/test_v2_treatment_value_persistence_closure.py"

    checks = {row["key"]: row for row in payload["verification_matrix"]}
    for key in {
        "triplet_v2_asserts_warning_190k",
        "triplet_v2_asserts_critical_285k",
        "triplet_v2_asserts_profile_surface",
        "dose_alerts_define_warning_and_critical",
        "profile_v2_has_treatment_course_card",
        "profile_v2_has_value_summary",
        "profile_v2_has_treatment_timelines",
        "registry_builder_has_12_24_windows_and_traceability",
        "registry_runtime_is_read_only",
    }:
        assert checks[key]["status"] == "pass"


def test_v2_treatment_value_closure_api_is_read_only(app_client):
    client, _db_path = app_client

    summary = client.get("/api/platform-readiness/v2-treatment-value-closure?scope=summary")
    assert summary.status_code == 200
    payload = summary.get_json()
    assert payload["success"] is True
    assert payload["scope"] == "summary"
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["real_database_mutated"] is False
    assert payload["summary"]["critical_failure_count"] == 0
    assert "verification_matrix" not in payload

    full = client.get("/api/platform-readiness/v2-treatment-value-closure?scope=full")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert full_payload["verification_matrix"]
    assert full_payload["flow_contract"]["reference_regimen"] == "ADT_DOCETAXEL_DAROLUTAMIDE"


def test_world_class_benchmark_radar_maps_strategy_and_sources():
    radar = build_world_class_benchmark_radar(
        v2_treatment_value_closure={
            "summary": {
                "v2_treatment_value_closure_status": "v2_treatment_value_closure_ready",
            }
        },
        epidemiology_command_center={
            "version": "epidemiology_command_center_v2",
            "kpi_id": "grand_epidemiology_dashboard_v2",
            "metric_provenance": {"version": "metric_provenance_binding_v1"},
        },
    )

    assert radar["version"] == "world_class_prostate_platform_benchmark_v1"
    assert radar["source_clinical_facts_mutated"] is False
    assert radar["external_order_created"] is False
    assert radar["model_trained"] is False
    assert radar["external_transfer_performed"] is False
    assert radar["summary"]["benchmark_class_count"] >= 6
    assert radar["summary"]["source_count"] >= 8
    assert radar["summary"]["achievement_count"] >= 5
    assert "learning-health-system" in radar["summary"]["direction_of_travel"]
    assert radar["summary"]["recommended_next_move"]
    assert radar["evidence_context"]["as_of"] == "2026-05-30"
    assert any(row["platform_class"] == "Oncology EHR / CDS" for row in radar["benchmark_matrix"])
    assert any(row["key"] == "tempus_lens" for row in radar["sources"])
    assert any(row["key"] == "epic_cosmos" for row in radar["sources"])
    assert any(row["key"] == "artera_tempus" and "2026" in row["evidence_note"] for row in radar["sources"])
    assert any(item["key"] == "profile_v2_treatment_value" for item in radar["achievements"])
    assert any(item["key"] == "multistage_capture_integrity" for item in radar["achievements"])
    assert any(item["key"] == "auditable_every_number" for item in radar["operating_principles"])
    assert any(item["key"] == "no_silent_default_facts" for item in radar["operating_principles"])
    assert any(row["key"] == "interoperability" for row in radar["capability_radar"])
    scores = {row["key"]: row["prostanet_score"] for row in radar["capability_radar"]}
    assert scores["economic_value"] == 5
    assert scores["longitudinal_outcomes"] == 5
    assert any(phase["name"] == "Piloto prospectivo NAS" for phase in radar["strategic_phases"])
    assert radar["ui_contract"]["read_only"] is True
    assert radar["ui_contract"]["uses_v2_treatment_value_evidence"] is True
    assert radar["ui_contract"]["uses_epidemiology_command_center_evidence"] is True


def test_world_class_benchmark_api_and_platform_readiness_panel(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/world-class-benchmark?scope=full&evidence=audit")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["version"] == "world_class_prostate_platform_benchmark_v1"
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["summary"]["world_class_readiness_score"] > 0
    assert payload["ui_contract"]["uses_v2_treatment_value_evidence"] is True
    assert payload["ui_contract"]["uses_epidemiology_command_center_evidence"] is True
    assert len(payload["benchmark_matrix"]) >= 6

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="world-class-benchmark-radar"' in html
    assert 'data-testid="world-class-benchmark-kpi"' in html
    assert 'data-testid="world-class-achievements"' in html
    assert 'data-testid="world-class-operating-principles"' in html
    assert "Benchmark JSON" in html


def test_external_validation_worklist_prioritizes_multicenter_closure_without_mutation():
    pilot = {
        "summary": {
            "pilot_status": "pilot_blocked",
            "pilot_gate_score": 53.3,
            "pilot_block_count": 1,
            "ready_for_external_deployment": False,
        },
        "gate_matrix": [
            {
                "gate_key": "clinical_fact_ledger",
                "status": "block",
                "next_action": "Close Ledger block.",
            },
            {
                "gate_key": "v2_persistence_matrix",
                "status": "pass",
                "next_action": "Keep V2 green.",
            },
            {"gate_key": "no_recapture_contract", "status": "pass"},
            {"gate_key": "nas_local_operations", "status": "watch"},
            {"gate_key": "backup_restore_drill", "status": "watch"},
            {"gate_key": "access_control_roles", "status": "watch"},
            {"gate_key": "consent_and_data_use", "status": "watch"},
            {"gate_key": "incident_response_contingency", "status": "watch"},
            {"gate_key": "prospective_protocol_approval", "status": "watch"},
        ],
        "pilot_packet_manifest": [{"component": "Platform Readiness", "kind": "dashboard", "url": "/platform-readiness", "required": True}],
    }
    worklist = build_external_validation_worklist(
        scope="full",
        world_class_benchmark={
            "summary": {
                "top_gap_key": "external_validation",
                "top_gap_label": "Validacion externa/multicentro",
                "world_class_readiness_score": 66.7,
            }
        },
        prospective_pilot_governance=pilot,
        nas_pilot_evidence_vault={"summary": {"completion_pct": 14.3, "verified_gate_count": 1, "gate_count": 7}},
        pilot_adoption_command_center={
            "summary": {
                "patient_count": 12,
                "real_patient_count": 0,
                "synthetic_patient_count": 12,
                "registry_ready_pct": 50,
                "high_priority_gap_count": 3,
            }
        },
        prospective_gap_closure_huddle={"summary": {"open_gap_count": 8, "reviewed_gap_count": 1, "high_priority_gap_count": 3}},
        ape_longitudinal_completion_sprint={"summary": {"psa_history_coverage_pct": 75, "ape_gap_patient_count": 2, "potential_registry_unlock_count": 2}},
        deidentified_export_contract={
            "summary": {
                "next_layer_allowed": True,
                "direct_identifier_key_count": 0,
                "exact_phi_hit_count": 0,
                "critical_interop_block_count": 0,
            }
        },
        research_pack_materializer={
            "summary": {
                "next_layer_allowed": True,
                "direct_identifier_key_count": 0,
                "exact_phi_hit_count": 0,
                "critical_interop_block_count": 0,
            }
        },
        research_pack_freeze_library={
            "summary": {"freeze_count": 1, "download_ready_count": 1},
            "freezes": [{"download_url": "/api/download/freeze", "freeze_key": "freeze_demo"}],
        },
        interoperability_map={
            "summary": {
                "next_layer_allowed": True,
                "critical_block_count": 0,
                "critical_ready_count": 29,
                "critical_fact_count": 29,
                "overall_mapping_coverage_pct": 21.1,
            }
        },
    )

    assert worklist["version"] == "external_validation_readiness_worklist_v1"
    assert worklist["read_only"] is True
    assert worklist["source_clinical_facts_mutated"] is False
    assert worklist["external_order_created"] is False
    assert worklist["model_trained"] is False
    assert worklist["external_transfer_performed"] is False
    assert worklist["external_validation_claim_made"] is False
    assert worklist["summary"]["external_validation_status"] == "external_validation_blocked_by_readiness_gates"
    assert worklist["summary"]["top_blocker_key"] == "clinical_fact_ledger_v2_flow"
    assert worklist["summary"]["world_class_top_gap_key"] == "external_validation"
    assert any(item["key"] == "real_world_sample_maturity" for item in worklist["worklist"])
    assert worklist["no_phi_scan"]["no_phi_status"] == "pass"


def test_external_validation_worklist_api_page_and_csv_are_read_only(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/external-validation-worklist?scope=full&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "external_validation_readiness_worklist_v1"
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["external_validation_claim_made"] is False
    assert payload["summary"]["item_count"] >= 8
    assert payload["summary"]["world_class_top_gap_key"] == "external_validation"
    assert payload["worklist"]
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"

    csv_response = client.get("/api/platform-readiness/external-validation-worklist/export?limit=20")
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert "clinical_fact_ledger_v2_flow" in csv_text
    assert "patient_ref" not in csv_text

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="external-validation-worklist"' in html
    assert 'data-testid="external-validation-worklist-kpi"' in html
    assert "/api/platform-readiness/external-validation-worklist" in html
    assert "Validacion externa JSON" in html


def test_real_world_sample_maturity_gate_separates_synthetic_from_real(app_client):
    _client, _db_path = app_client
    import tracking_db

    conn = tracking_db._connect(write=True)
    try:
        conn.execute(
            """
            INSERT INTO patient_identity (
                nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason
            ) VALUES (?, ?, ?, ?, 1, ?)
            """,
            ("QA-RWS-001", "QA Synthetic", "1950-01-01", "2026-05-01", "unit_test_fixture"),
        )
        conn.execute(
            """
            INSERT INTO patient_identity (
                nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason,
                real_patient_consent_signed_at, real_patient_consent_actor_user_id
            ) VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
            """,
            ("REAL-RWS-001", "Real Consentido", "1951-01-01", "2026-05-01", "2026-05-29T10:00:00Z", 7),
        )
        conn.execute(
            """
            INSERT INTO patient_identity (
                nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason,
                real_patient_consent_signed_at, real_patient_consent_actor_user_id
            ) VALUES (?, ?, ?, ?, 0, NULL, ?, NULL)
            """,
            ("REAL-RWS-002", "Real Sin Actor", "1952-01-01", "2026-05-01", "2026-05-29T11:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    gate = build_real_world_sample_maturity_gate(scope="full", limit=20)

    assert gate["version"] == "real_world_sample_maturity_gate_v1"
    assert gate["read_only"] is True
    assert gate["source_clinical_facts_mutated"] is False
    assert gate["external_order_created"] is False
    assert gate["model_trained"] is False
    assert gate["external_transfer_performed"] is False
    assert gate["summary"]["real_patient_count"] == 2
    assert gate["summary"]["synthetic_patient_count"] == 1
    assert gate["summary"]["real_without_actor_count"] == 1
    assert gate["summary"]["sample_maturity_status"] == "blocked_real_patient_consent_audit_gap"
    assert gate["summary"]["external_validation_claim_allowed"] is False
    assert gate["no_phi_scan"]["no_phi_status"] == "pass"
    assert all("REAL-RWS" not in str(row) for row in gate["recent_cohort_rows"])


def test_real_world_sample_maturity_api_page_and_csv(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/real-world-sample-maturity?scope=full&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "real_world_sample_maturity_gate_v1"
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["summary"]["sample_maturity_status"] in {
        "blocked_no_real_world_sample",
        "blocked_real_patient_consent_audit_gap",
        "needs_prospective_enrollment",
        "needs_real_cohort_completeness",
        "needs_pilot_governance_closure",
        "ready_for_internal_real_world_signal",
        "ready_for_external_preflight_not_multicenter",
        "ready_for_multicenter_preflight",
    }
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"

    csv_response = client.get("/api/platform-readiness/real-world-sample-maturity/export?limit=20")
    assert csv_response.status_code == 200
    csv_text = csv_response.get_data(as_text=True)
    assert "subject_id" in csv_text
    assert "patient_ref" not in csv_text

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="real-world-sample-maturity"' in html
    assert 'data-testid="real-world-sample-maturity-kpi"' in html
    assert "/api/platform-readiness/real-world-sample-maturity" in html
    assert "Muestra real JSON" in html


def test_prospective_real_world_completion_queue_is_real_only_and_read_only(app_client):
    client, _db_path = app_client

    real_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 65,
                "psa": 12.0,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 4,
                "total_cores": 12,
            },
        },
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": real_draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "REAL-COMPLETE-001",
            "full_name": "Paciente Real Completion PHI",
            "dob": "1961-05-29",
            "is_real_patient": 1,
            "consent_signed": 1,
            "actor_user_id": 77,
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 12.0}],
        },
    ).status_code == 200

    synthetic_draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 8.1, "clinical_tstage": "T2a"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": synthetic_draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "SYN-COMPLETE-001",
            "full_name": "Paciente QA Completion PHI",
            "dob": "1964-05-29",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 8.1}],
        },
    ).status_code == 200

    queue = build_prospective_real_world_completion_queue(scope="full", limit=20)

    assert queue["version"] == "prospective_real_world_completion_queue_v1"
    assert queue["read_only"] is True
    assert queue["source_clinical_facts_mutated"] is False
    assert queue["external_order_created"] is False
    assert queue["model_trained"] is False
    assert queue["external_transfer_performed"] is False
    assert queue["clinical_values_captured_here"] is False
    assert queue["summary"]["real_patient_count"] == 1
    assert queue["summary"]["queued_real_patient_count"] == 1
    assert queue["summary"]["real_world_claim_allowed"] is False
    assert queue["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "real_patient_queue" in queue

    row = queue["real_patient_queue"][0]
    assert row["patient_ref"] == "REAL-COMPLETE-001"
    assert row["profile_url"] == "/patient_profile/REAL-COMPLETE-001?v=2"
    assert row["evidence_use_status"] in {
        "needs_ape_history",
        "needs_registry_completion",
        "registry_ready_internal_signal_candidate",
    }
    assert row["consent_present"] is True
    assert row["actor_present"] is True
    assert row["source_clinical_facts_mutated"] is False

    serialized = json.dumps(queue, ensure_ascii=False)
    assert "SYN-COMPLETE-001" not in serialized
    assert "Paciente QA Completion PHI" not in serialized

    csv_text = build_prospective_real_world_completion_csv_bytes(queue).decode("utf-8")
    assert "subject_id,evidence_use_status" in csv_text
    assert "REAL-COMPLETE-001" not in csv_text
    assert "Paciente Real Completion PHI" not in csv_text
    assert "patient_ref" not in csv_text


def test_prospective_real_world_completion_queue_api_page_and_csv(app_client):
    client, _db_path = app_client

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 9.4, "clinical_tstage": "T2c"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "REAL-COMPLETE-API",
            "full_name": "Paciente Real API PHI",
            "dob": "1962-05-29",
            "is_real_patient": 1,
            "consent_signed": 1,
            "actor_user_id": 81,
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 9.4}],
        },
    ).status_code == 200

    summary_response = client.get("/api/platform-readiness/prospective-real-world-completion-queue?scope=summary&limit=20")
    assert summary_response.status_code == 200
    summary = summary_response.get_json()

    assert summary["success"] is True
    assert summary["version"] == "prospective_real_world_completion_queue_v1"
    assert summary["scope"] == "summary"
    assert summary["read_only"] is True
    assert summary["summary"]["real_patient_count"] == 1
    assert summary["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "real_patient_queue" not in summary
    assert "REAL-COMPLETE-API" not in json.dumps(summary, ensure_ascii=False)

    full_response = client.get("/api/platform-readiness/prospective-real-world-completion-queue?scope=full&limit=20")
    assert full_response.status_code == 200
    full = full_response.get_json()
    assert any(row["patient_ref"] == "REAL-COMPLETE-API" for row in full["real_patient_queue"])
    assert full["drilldown_policy"]["surface"] == "patient_profile_v2"

    csv_response = client.get("/api/platform-readiness/prospective-real-world-completion-queue/export?limit=20")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    csv_text = csv_response.get_data(as_text=True)
    assert "subject_id,evidence_use_status" in csv_text
    assert "REAL-COMPLETE-API" not in csv_text
    assert "patient_ref" not in csv_text

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="prospective-real-world-completion-queue"' in html
    assert 'data-testid="prospective-real-world-completion-queue-kpi"' in html
    assert "/api/platform-readiness/prospective-real-world-completion-queue" in html
    assert "Cola real-only JSON" in html


def test_real_world_pilot_packet_is_no_phi_operational_runbook(app_client):
    _client, _db_path = app_client

    packet = build_real_world_pilot_packet(scope="full", limit=20)

    assert packet["version"] == "real_world_pilot_packet_v1"
    assert packet["read_only"] is True
    assert packet["source_clinical_facts_mutated"] is False
    assert packet["external_order_created"] is False
    assert packet["model_trained"] is False
    assert packet["external_transfer_performed"] is False
    assert packet["clinical_values_captured_here"] is False
    assert packet["deidentified_export_written"] is False
    assert packet["summary"]["packet_status"] == "ready_to_capture_first_real_patient"
    assert packet["summary"]["real_patient_count"] == 0
    assert packet["summary"]["external_validation_claim_allowed"] is False
    assert packet["no_phi_scan"]["no_phi_status"] == "pass"
    assert any(item["key"] == "first_real_patient" and item["status"] == "block" for item in packet["launch_checklist"])
    assert any(item["field"] == "psa_history" for item in packet["required_capture_fields"])
    assert any(step["surface"] == "patient_profile_v2" for step in packet["capture_workflow"])
    assert any(rule["title"] == "APE aislado" for rule in packet["stop_rules"])

    markdown = build_real_world_pilot_packet_markdown_bytes(packet).decode("utf-8")
    assert "primer paciente real prospectivo" in markdown
    assert "NSS" not in markdown
    assert "patient_ref" not in markdown


def test_real_world_pilot_packet_api_page_and_download(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/real-world-pilot-packet?scope=summary&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "real_world_pilot_packet_v1"
    assert payload["scope"] == "summary"
    assert payload["read_only"] is True
    assert payload["summary"]["real_patient_count"] == 0
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"
    assert "capture_workflow" not in payload
    assert "patient_ref" not in json.dumps(payload, ensure_ascii=False)

    full = client.get("/api/platform-readiness/real-world-pilot-packet?scope=full&limit=20")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert "capture_workflow" in full_payload
    assert "post_capture_verification" in full_payload

    download = client.get("/api/platform-readiness/real-world-pilot-packet/download?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/markdown"
    markdown = download.get_data(as_text=True)
    assert "Paquete operativo" in markdown
    assert "NSS" not in markdown
    assert "patient_ref" not in markdown

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="real-world-pilot-packet"' in html
    assert 'data-testid="real-world-pilot-packet-kpi"' in html
    assert "/api/platform-readiness/real-world-pilot-packet" in html
    assert "Paquete real JSON" in html


def test_real_world_pilot_execution_log_summarizes_dry_run_and_live_blocks(app_client):
    _client, _db_path = app_client

    log = build_real_world_pilot_execution_log(scope="full", limit=20)

    assert log["version"] == "real_world_pilot_execution_log_v1"
    assert log["read_only"] is True
    assert log["source_clinical_facts_mutated"] is False
    assert log["external_order_created"] is False
    assert log["model_trained"] is False
    assert log["external_transfer_performed"] is False
    assert log["clinical_values_captured_here"] is False
    assert log["deidentified_export_written"] is False
    assert log["summary"]["dry_run_contract_status"] == "pass"
    assert log["summary"]["log_status"] == "dry_run_verified_waiting_first_real_patient"
    assert log["summary"]["real_patient_count"] == 0
    assert log["summary"]["external_validation_claim_allowed"] is False
    assert log["no_phi_scan"]["no_phi_status"] == "pass"
    assert any(item["evidence_key"] == "dry_run_v2_end_to_end" and item["status"] == "pass" for item in log["execution_log"])
    assert any(item["evidence_key"] == "first_real_capture" and item["status"] == "block" for item in log["execution_log"])
    assert log["dry_run_evidence"]["contract_present"] is True
    assert "biomarker_longitudinal" in json.dumps(log["dry_run_evidence"], ensure_ascii=False) or "APE longitudinal" in json.dumps(log["dry_run_evidence"], ensure_ascii=False)

    markdown = build_real_world_pilot_execution_log_markdown_bytes(log).decode("utf-8")
    assert "Bitacora operacional" in markdown
    assert "dry_run_verified_waiting_first_real_patient" in markdown
    assert "NSS" not in markdown
    assert "patient_ref" not in markdown


def test_real_world_pilot_execution_log_api_page_and_download(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/real-world-pilot-execution-log?scope=summary&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "real_world_pilot_execution_log_v1"
    assert payload["scope"] == "summary"
    assert payload["summary"]["dry_run_contract_status"] == "pass"
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"
    assert "execution_log" not in payload
    assert "dry_run_evidence" not in payload
    assert "patient_ref" not in json.dumps(payload, ensure_ascii=False)

    full = client.get("/api/platform-readiness/real-world-pilot-execution-log?scope=full&limit=20")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert "execution_log" in full_payload
    assert "dry_run_evidence" in full_payload
    assert full_payload["dry_run_evidence"]["contract_present"] is True

    download = client.get("/api/platform-readiness/real-world-pilot-execution-log/download?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/markdown"
    markdown = download.get_data(as_text=True)
    assert "Bitacora operacional" in markdown
    assert "NSS" not in markdown
    assert "patient_ref" not in markdown

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="real-world-pilot-execution-log"' in html
    assert 'data-testid="real-world-pilot-execution-log-kpi"' in html
    assert "/api/platform-readiness/real-world-pilot-execution-log" in html
    assert "Bitacora real JSON" in html


def test_real_world_first_patient_launch_mode_guides_v2_capture_without_phi(app_client):
    _client, _db_path = app_client

    launch_mode = build_real_world_first_patient_launch_mode(scope="full", limit=20)

    assert launch_mode["version"] == "real_world_first_patient_launch_mode_v1"
    assert launch_mode["read_only"] is True
    assert launch_mode["source_clinical_facts_mutated"] is False
    assert launch_mode["external_order_created"] is False
    assert launch_mode["model_trained"] is False
    assert launch_mode["external_transfer_performed"] is False
    assert launch_mode["clinical_values_captured_here"] is False
    assert launch_mode["deidentified_export_written"] is False
    assert launch_mode["summary"]["dry_run_contract_status"] == "pass"
    assert launch_mode["summary"]["launch_mode_status"] == "ready_for_institutional_first_real_capture"
    assert launch_mode["summary"]["real_patient_count"] == 0
    assert launch_mode["summary"]["external_validation_claim_allowed"] is False
    assert launch_mode["summary"]["real_world_claim_allowed"] is False
    assert launch_mode["no_phi_scan"]["no_phi_status"] == "pass"

    step_keys = {step["step_key"] for step in launch_mode["guided_steps"]}
    assert {"sign_real_world_consent", "capture_ape_history", "verify_profile_v2"} <= step_keys
    assert any(check["check_key"] == "ape_history_not_isolated" for check in launch_mode["post_capture_auto_checks"])
    assert any(item["component"] == "Perfil V2" for item in launch_mode["operator_packet_manifest"])

    serialized = json.dumps(launch_mode, ensure_ascii=False)
    assert "patient_ref" not in serialized
    assert "NSS" not in serialized

    markdown = build_real_world_first_patient_launch_mode_markdown_bytes(launch_mode).decode("utf-8")
    assert "Modo de ejecucion institucional del primer real" in markdown
    assert "capture_ape_history" in markdown
    assert "patient_ref" not in markdown
    assert "NSS" not in markdown


def test_real_world_first_patient_launch_mode_api_page_and_download(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/real-world-first-patient-launch-mode?scope=summary&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "real_world_first_patient_launch_mode_v1"
    assert payload["scope"] == "summary"
    assert payload["summary"]["launch_mode_status"] == "ready_for_institutional_first_real_capture"
    assert payload["summary"]["dry_run_contract_status"] == "pass"
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"
    assert "guided_steps_preview" in payload
    assert "guided_steps" not in payload
    assert "post_capture_auto_checks" not in payload
    assert "patient_ref" not in json.dumps(payload, ensure_ascii=False)

    full = client.get("/api/platform-readiness/real-world-first-patient-launch-mode?scope=full&limit=20")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert "guided_steps" in full_payload
    assert "post_capture_auto_checks" in full_payload
    assert any(step["step_key"] == "verify_real_only_queue" for step in full_payload["guided_steps"])

    download = client.get("/api/platform-readiness/real-world-first-patient-launch-mode/download?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/markdown"
    markdown = download.get_data(as_text=True)
    assert "Modo de ejecucion institucional" in markdown
    assert "patient_ref" not in markdown
    assert "NSS" not in markdown

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="real-world-first-patient-launch-mode"' in html
    assert 'data-testid="real-world-first-patient-launch-mode-kpi"' in html
    assert "Modo de ejecucion institucional del primer real" in html
    assert "/api/platform-readiness/real-world-first-patient-launch-mode" in html
    assert "Lanzamiento real JSON" in html


def test_clinical_hub_v2_first_real_launch_strip_is_query_gated_and_no_phi(app_client):
    client, _db_path = app_client

    normal = client.get("/clinical-hub")
    assert normal.status_code == 200
    normal_html = normal.get_data(as_text=True)
    assert "pm2-redesign-shell" in normal_html
    assert 'data-testid="first-real-v2-launch-strip"' not in normal_html

    response = client.get("/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "pm2-redesign-shell" in html
    assert 'data-testid="first-real-v2-launch-strip"' in html
    assert 'data-testid="first-real-v2-operator-checklist"' in html
    assert 'data-testid="first-real-v2-operator-step-select_clinical_module"' in html
    assert 'data-testid="first-real-v2-session-step-registration_prepared"' in html
    assert 'data-source-clinical-facts-mutated="false"' in html
    assert "first_real_launch_checklist.js" in html
    assert "Lanzamiento institucional activo" in html
    assert "ready_for_institutional_first_real_capture" in html
    assert "/platform-readiness#real-world-first-patient-launch-mode" in html
    assert "/api/platform-readiness/real-world-first-patient-launch-mode/download" in html
    assert 'href="#pm2OfficialClassifier"' in html
    assert "?real_world_enrollment=1" in html
    assert "patient_ref" not in html
    assert "NSS" not in html

    wizard = client.get("/wizard/localized_initial?prefill_source=clinical_hub&real_world_enrollment=1")
    assert wizard.status_code == 200
    wizard_html = wizard.get_data(as_text=True)
    assert 'data-testid="first-real-wizard-handoff-guard"' in wizard_html
    assert 'data-testid="first-real-wizard-registration-guard"' in wizard_html
    assert 'data-testid="real-world-enrollment-panel"' in wizard_html
    assert 'name="consent_signed" value="0"' in wizard_html
    assert "first_real_launch_checklist.js" in wizard_html
    assert "recordFirstRealLaunchStep" in wizard_html
    assert "registration_prepared" in wizard_html
    assert 'data-source-clinical-facts-mutated="false"' in wizard_html
    guard_visible_text = (
        wizard_html.split('data-testid="first-real-wizard-handoff-guard"', 1)[-1]
        .split('data-testid="first-real-wizard-registration-guard"', 1)[0]
    )
    registration_guard_text = (
        wizard_html.split('data-testid="first-real-wizard-registration-guard"', 1)[-1]
        .split('data-testid="real-world-enrollment-panel"', 1)[0]
    )
    assert "patient_ref" not in guard_visible_text
    assert "NSS" not in guard_visible_text
    assert "patient_ref" not in registration_guard_text
    assert "NSS" not in registration_guard_text


def test_real_world_launch_flow_verifier_proves_v2_handoff_without_phi(app_client):
    client, _db_path = app_client

    verifier = build_real_world_launch_flow_verifier(
        scope="full",
        limit=20,
        registered_rules=client.application.url_map.iter_rules(),
    )

    assert verifier["version"] == "real_world_launch_flow_verifier_v1"
    assert verifier["read_only"] is True
    assert verifier["source_clinical_facts_mutated"] is False
    assert verifier["external_order_created"] is False
    assert verifier["model_trained"] is False
    assert verifier["external_transfer_performed"] is False
    assert verifier["clinical_values_captured_here"] is False
    assert verifier["deidentified_export_written"] is False
    assert verifier["summary"]["flow_verifier_status"] == "launch_flow_verified_waiting_first_real"
    assert verifier["summary"]["ui_backend_sync_status"] == "pass"
    assert verifier["summary"]["real_patient_count"] == 0
    assert verifier["summary"]["external_validation_claim_allowed"] is False
    assert verifier["no_phi_scan"]["no_phi_status"] == "pass"

    by_key = {item["key"]: item for item in verifier["verification_matrix"]}
    for key in (
        "clinical_hub_v2_entry",
        "wizard_v2",
        "consent_draft_api",
        "consent_sign_api",
        "consent_finalize_api",
        "clinical_hub_launch_strip_v2",
        "quick_classifier_real_world_handoff_v2",
        "wizard_real_world_panel_v2",
        "first_real_operator_checklist_js_v2",
        "profile_v2_truth_surface",
        "dry_run_v2_contract",
        "launch_strip_contract",
        "first_real_ape_series_guard_contract",
        "claims_governed",
    ):
        assert by_key[key]["status"] == "pass"
    assert by_key["sample_boundary_clear"]["status"] == "watch"

    serialized = json.dumps(verifier, ensure_ascii=False)
    assert "patient_ref" not in serialized
    assert "NSS" not in serialized

    markdown = build_real_world_launch_flow_verifier_markdown_bytes(verifier).decode("utf-8")
    assert "Verificador del handoff V2" in markdown
    assert "clinical_hub_launch_strip_v2" in markdown
    assert "patient_ref" not in markdown
    assert "NSS" not in markdown

    response = client.get("/api/platform-readiness/real-world-launch-flow-verifier?scope=summary&limit=20")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["summary"]["ui_backend_sync_status"] == "pass"
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"
    assert "verification_matrix" not in payload


def test_real_world_launch_flow_verifier_api_page_and_download(app_client):
    client, _db_path = app_client

    full = client.get("/api/platform-readiness/real-world-launch-flow-verifier?scope=full&limit=20")
    assert full.status_code == 200
    full_payload = full.get_json()
    assert full_payload["version"] == "real_world_launch_flow_verifier_v1"
    assert full_payload["summary"]["flow_verifier_status"] == "launch_flow_verified_waiting_first_real"
    assert "verification_matrix" in full_payload
    assert any(item["key"] == "profile_v2_truth_surface" for item in full_payload["verification_matrix"])
    assert any(item["key"] == "quick_classifier_real_world_handoff_v2" for item in full_payload["verification_matrix"])

    download = client.get("/api/platform-readiness/real-world-launch-flow-verifier/download?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/markdown"
    markdown = download.get_data(as_text=True)
    assert "Verificador del handoff V2" in markdown
    assert "NSS" not in markdown
    assert "patient_ref" not in markdown

    page = client.get("/platform-readiness")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-testid="real-world-launch-flow-verifier"' in html
    assert 'data-testid="real-world-launch-flow-verifier-kpi"' in html
    assert "Verificador del flujo V2 del primer real" in html
    assert "/api/platform-readiness/real-world-launch-flow-verifier" in html
    assert "Verificador real JSON" in html


def test_real_world_v2_registration_surface_sets_explicit_enrollment_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    panel = (root / "templates/components/real_world_enrollment_panel.html").read_text()
    wizard = (root / "templates/clinical_wizard.html").read_text()
    intake = (root / "templates/patient_intake.html").read_text()
    registration_js = (root / "static/js/registration_context_ui.js").read_text()
    classifier_js = (root / "static/js/clinical_hub_quick_classifier.js").read_text()
    checklist_js = (root / "static/js/first_real_launch_checklist.js").read_text()
    clinical_hub_v2 = (root / "templates/demos/stage_clinical_center_v2_redesign.html").read_text()

    assert 'data-testid="real-world-enrollment-panel"' in panel
    assert 'name="is_real_patient" value="0"' in panel
    assert 'name="is_real_patient" value="1"' in panel
    assert 'name="consent_signed" value="0"' in panel
    assert 'name="actor_user_id"' in panel
    assert 'include "components/real_world_enrollment_panel.html"' in wizard
    assert 'include "components/real_world_enrollment_panel.html"' in intake
    assert "real_world_enrollment_panel.js" in wizard
    assert "real_world_enrollment_panel.js" in intake
    assert "ProstaNetRealWorldEnrollment" in registration_js
    assert 'data-testid="first-real-wizard-handoff-guard"' in wizard
    assert 'data-testid="first-real-wizard-registration-guard"' in wizard
    assert "real_world_launch_requested" in wizard
    assert "first_real_launch_checklist.js" in wizard
    assert "recordFirstRealLaunchStep" in wizard
    assert "requireFirstRealApeSeriesBeforeConsent" in wizard
    assert "first_real_wizard_v2" in wizard
    assert "buildWizardHref" in classifier_js
    assert "isRealWorldLaunchMode" in classifier_js
    assert 'params.set("real_world_enrollment", "1")' in classifier_js
    assert "ProstaNetFirstRealLaunchChecklist" in classifier_js
    assert "module_classified" in classifier_js
    assert "sessionStorage" in checklist_js
    assert "MIN_VALID_PSA_HISTORY_POINTS" in checklist_js
    assert "recordStepStatus" in checklist_js
    assert "validPsaHistoryRows" in checklist_js
    assert "hasPsaHistorySeries" in checklist_js
    assert "launch_strip_opened" in checklist_js
    assert "wizard_context_preserved" in checklist_js
    assert "registration_prepared" in checklist_js
    assert "real_panel_activated" in checklist_js
    assert "actor_present" in checklist_js
    assert "ape_payload_ready" in checklist_js
    assert 'data-testid="first-real-v2-operator-checklist"' in clinical_hub_v2
    assert "data-first-real-session-step" in clinical_hub_v2
    assert "module_wizard_href" in clinical_hub_v2
    assert "real_world_enrollment=1" in clinical_hub_v2


def test_first_real_consent_requires_two_dated_ape_points(app_client):
    client, _db_path = app_client

    base_payload = {
        "nss": "RW-FIRST-APE-GUARD-001",
        "full_name": "Paciente APE Guard PHI",
        "dob": "1958-03-10",
        "is_real_patient": "1",
        "consent_signed": "1",
        "actor_user_id": "77",
        "real_world_enrollment_mode": "prospective_v2",
        "assessment_state": "localized_initial",
    }
    one_point = client.post(
        "/api/research/consent/draft",
        json={
            "payload": {
                **base_payload,
                "psa_history": [{"sample_date": "2026-05-01", "psa_value": 8.4, "context": "pretratamiento"}],
            },
            "source_context": "first_real_wizard_v2",
        },
    )
    assert one_point.status_code == 400
    assert "2 mediciones APE" in one_point.get_json()["error"]

    two_points = client.post(
        "/api/research/consent/draft",
        json={
            "payload": {
                **base_payload,
                "nss": "RW-FIRST-APE-GUARD-002",
                "psa_history": [
                    {"sample_date": "2026-04-01", "psa_value": 8.0, "context": "pretratamiento"},
                    {"sample_date": "2026-05-01", "psa_value": 8.4, "context": "pretratamiento"},
                ],
            },
            "source_context": "first_real_wizard_v2",
        },
    )
    assert two_points.status_code == 200
    assert two_points.get_json()["success"] is True


def test_real_world_consent_finalize_promotes_patient_with_actor(app_client):
    client, _db_path = app_client
    import tracking_db

    payload = {
        "nss": "RW-ONBOARD-001",
        "full_name": "Paciente Real Onboarding",
        "dob": "1958-03-10",
        "is_real_patient": "1",
        "consent_signed": "1",
        "actor_user_id": "77",
        "psa": "8.4",
        "assessment_state": "diagnostic_workup",
    }
    draft_response = client.post(
        "/api/research/consent/draft",
        json={"payload": payload, "source_context": "wizard_real_world_v2"},
    )
    assert draft_response.status_code == 200
    draft_id = draft_response.get_json()["draft_id"]
    sign_response = client.post(
        f"/api/research/consent/draft/{draft_id}/sign",
        json={
            "signer_name": "Paciente Real Onboarding",
            "signature_data_url": "data:image/png;base64,AAAA",
            "accepted": True,
            "audit_metadata": {"source_context": "unit_real_world_v2"},
        },
    )
    assert sign_response.status_code == 200
    finalize_response = client.post(f"/api/research/consent/draft/{draft_id}/finalize")
    assert finalize_response.status_code == 200
    finalized = finalize_response.get_json()
    assert finalized["success"] is True

    conn = tracking_db._connect()
    try:
        row = conn.execute(
            """
            SELECT is_synthetic, synthetic_flag_reason,
                   real_patient_consent_signed_at,
                   real_patient_consent_actor_user_id
            FROM patient_identity
            WHERE nss = ?
            """,
            ("RW-ONBOARD-001",),
        ).fetchone()
    finally:
        conn.close()

    assert int(row["is_synthetic"]) == 0
    assert row["synthetic_flag_reason"] is None
    assert row["real_patient_consent_signed_at"]
    assert int(row["real_patient_consent_actor_user_id"]) == 77

    gate = build_real_world_sample_maturity_gate(scope="full", limit=20)
    assert gate["summary"]["real_patient_count"] == 1
    assert gate["summary"]["synthetic_patient_count"] == 0
    assert gate["summary"]["real_without_actor_count"] == 0
    assert gate["summary"]["real_without_identity_consent_count"] == 0
    assert gate["summary"]["sample_maturity_status"] == "needs_prospective_enrollment"


def test_real_world_registration_rejects_missing_actor(app_client):
    _client, _db_path = app_client
    import tracking_db

    patient_id, message, metadata = tracking_db.register_new_patient(
        {
            "nss": "RW-NO-ACTOR-001",
            "full_name": "Paciente Real Sin Actor",
            "dob": "1958-03-10",
            "is_real_patient": "1",
            "consent_signed": "1",
        }
    )

    assert patient_id is None
    assert metadata == {}
    assert "actor_user_id" in message
    gate = build_real_world_sample_maturity_gate(scope="full", limit=20)
    assert gate["summary"]["real_patient_count"] == 0
    assert gate["summary"]["synthetic_patient_count"] == 0


def test_first_real_patient_dry_run_v2_persists_consent_ape_profile_and_gates(app_client):
    client, _db_path = app_client
    import tracking_db

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 66,
                "psa": 12.0,
                "clinical_tstage": "T2c",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 5,
                "total_cores": 12,
                "ipss_score": 7,
                "iief5_score": 18,
                "life_expectancy_years": 12,
            },
        },
    )
    assert draft.status_code == 200
    assessment_id = draft.get_json()["assessment_id"]

    patient_ref = "RW-DRYRUN-001"
    consent_payload = {
        "assessment_id": assessment_id,
        "assessment_state": "localized_initial",
        "nss": patient_ref,
        "full_name": "Paciente Real Dry Run PHI",
        "dob": "1960-05-29",
        "is_real_patient": "1",
        "consent_signed": "1",
        "actor_user_id": "91",
        "psa_history": [
            {"sample_date": "2026-04-01", "psa_value": 11.2, "context": "pretratamiento"},
            {"sample_date": "2026-05-01", "psa_value": 12.0, "context": "pretratamiento"},
        ],
    }
    draft_response = client.post(
        "/api/research/consent/draft",
        json={"payload": consent_payload, "source_context": "first_real_patient_dry_run_v2"},
    )
    assert draft_response.status_code == 200
    consent_draft_id = draft_response.get_json()["draft_id"]

    sign_response = client.post(
        f"/api/research/consent/draft/{consent_draft_id}/sign",
        json={
            "signer_name": "Paciente Real Dry Run PHI",
            "signature_data_url": "data:image/png;base64,RFJZUlVOX1NJRw==",
            "accepted": True,
            "audit_metadata": {"source_context": "first_real_patient_dry_run_v2"},
        },
    )
    assert sign_response.status_code == 200
    assert sign_response.get_json()["evidence"]["content_hash"]

    finalize = client.post(f"/api/research/consent/draft/{consent_draft_id}/finalize")
    assert finalize.status_code == 200
    finalize_payload = finalize.get_json()
    assert finalize_payload["success"] is True
    assert finalize_payload["consent"]["status"] == "signed"

    conn = tracking_db._connect()
    try:
        identity = conn.execute(
            """
            SELECT id, is_synthetic, synthetic_flag_reason,
                   real_patient_consent_signed_at,
                   real_patient_consent_actor_user_id
            FROM patient_identity
            WHERE nss = ?
            """,
            (patient_ref,),
        ).fetchone()
        assert identity is not None
        patient_id = int(identity["id"])
        biomarker_rows = conn.execute(
            """
            SELECT biomarker_type, value, sample_date
            FROM biomarker_longitudinal
            WHERE patient_id = ? AND UPPER(biomarker_type) = 'PSA'
            ORDER BY sample_date ASC
            """,
            (patient_id,),
        ).fetchall()
        linked_assessment = conn.execute(
            """
            SELECT module_id, state, patient_id, status
            FROM clinical_assessments
            WHERE id = ?
            """,
            (int(assessment_id),),
        ).fetchone()
        consent_count = conn.execute(
            "SELECT COUNT(*) AS total FROM patient_consents WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()["total"]
        evidence_count = conn.execute(
            "SELECT COUNT(*) AS total FROM consent_signature_evidence WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()["total"]
    finally:
        conn.close()

    assert int(identity["is_synthetic"]) == 0
    assert identity["synthetic_flag_reason"] is None
    assert identity["real_patient_consent_signed_at"]
    assert int(identity["real_patient_consent_actor_user_id"]) == 91
    assert len(biomarker_rows) == 2
    assert [round(float(row["value"]), 1) for row in biomarker_rows] == [11.2, 12.0]
    assert linked_assessment["patient_id"] == patient_id
    assert linked_assessment["module_id"] == "localized_initial"
    assert linked_assessment["status"] == "linked"
    assert consent_count == 1
    assert evidence_count == 1

    profile = client.get(f"/patient_profile/{patient_ref}?v=2")
    assert profile.status_code == 200
    profile_html = profile.get_data(as_text=True)
    assert "Consentimiento de uso secundario de datos" in profile_html
    assert "Firma electrónica del paciente" in profile_html
    assert "Hash de evidencia" in profile_html
    assert "psaTreatmentTimelineChart" in profile_html
    assert "psaCombinedTimelineChart" in profile_html
    assert "12.0" in profile_html or "12" in profile_html

    sample = client.get("/api/platform-readiness/real-world-sample-maturity?scope=full&limit=20").get_json()
    assert sample["summary"]["real_patient_count"] == 1
    assert sample["summary"]["synthetic_patient_count"] == 0
    assert sample["summary"]["real_without_actor_count"] == 0
    assert sample["summary"]["real_without_identity_consent_count"] == 0
    assert sample["summary"]["external_validation_claim_allowed"] is False

    summary_queue = client.get(
        "/api/platform-readiness/prospective-real-world-completion-queue?scope=summary&limit=20"
    ).get_json()
    assert summary_queue["summary"]["real_patient_count"] == 1
    assert summary_queue["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "real_patient_queue" not in summary_queue
    assert patient_ref not in json.dumps(summary_queue, ensure_ascii=False)
    assert "Paciente Real Dry Run PHI" not in json.dumps(summary_queue, ensure_ascii=False)

    full_queue = client.get(
        "/api/platform-readiness/prospective-real-world-completion-queue?scope=full&limit=20"
    ).get_json()
    row = next(item for item in full_queue["real_patient_queue"] if item["patient_ref"] == patient_ref)
    assert row["consent_present"] is True
    assert row["actor_present"] is True
    assert row["valid_psa_point_count"] >= 2
    assert row["ape_status"] == "history_ready"
    assert row["evidence_use_status"] not in {
        "blocked_missing_consent_audit",
        "blocked_no_ape",
        "needs_ape_history",
    }

    packet = client.get("/api/platform-readiness/real-world-pilot-packet?scope=summary&limit=20").get_json()
    assert packet["summary"]["real_patient_count"] == 1
    assert packet["summary"]["packet_status"] != "ready_to_capture_first_real_patient"
    assert packet["no_phi_scan"]["no_phi_status"] == "pass"
    assert patient_ref not in json.dumps(packet, ensure_ascii=False)


def test_first_real_institutional_launch_rehearsal_v2_from_strip_to_profile(app_client):
    client, _db_path = app_client
    import tracking_db

    timings_ms: dict[str, float] = {}

    def timed(label: str, method: str, path: str, **kwargs):
        started = time.perf_counter()
        response = getattr(client, method)(path, **kwargs)
        timings_ms[label] = round((time.perf_counter() - started) * 1000, 2)
        return response

    launch = timed("clinical_hub_launch_strip", "get", "/clinical-hub?real_world_enrollment=1#pm2OfficialClassifier")
    assert launch.status_code == 200
    launch_html = launch.get_data(as_text=True)
    assert 'data-testid="first-real-v2-launch-strip"' in launch_html
    assert "ready_for_institutional_first_real_capture" in launch_html
    assert "patient_ref" not in launch_html
    assert "NSS" not in launch_html

    wizard = timed("wizard_v2", "get", "/wizard/localized_initial?real_world_enrollment=1")
    assert wizard.status_code == 200
    wizard_html = wizard.get_data(as_text=True)
    assert 'data-testid="real-world-enrollment-panel"' in wizard_html
    assert "real_world_enrollment_panel.js" in wizard_html
    assert 'name="consent_signed" value="0"' in wizard_html
    assert "actor_user_id" in wizard_html

    draft = timed(
        "assessment_draft",
        "post",
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 66,
                "psa": 12.0,
                "clinical_tstage": "T2c",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 5,
                "total_cores": 12,
                "ipss_score": 7,
                "iief5_score": 18,
                "life_expectancy_years": 12,
            },
        },
    )
    assert draft.status_code == 200
    assessment_id = draft.get_json()["assessment_id"]

    patient_ref = "RW-LAUNCH-REHEARSAL-001"
    consent_payload = {
        "assessment_id": assessment_id,
        "assessment_state": "localized_initial",
        "nss": patient_ref,
        "full_name": "Paciente Launch Rehearsal PHI",
        "dob": "1960-05-29",
        "is_real_patient": "1",
        "consent_signed": "1",
        "actor_user_id": "93",
        "psa_history": [
            {"sample_date": "2026-04-01", "psa_value": 11.2, "context": "pretratamiento"},
            {"sample_date": "2026-05-01", "psa_value": 12.0, "context": "pretratamiento"},
        ],
    }
    consent_draft = timed(
        "consent_draft",
        "post",
        "/api/research/consent/draft",
        json={"payload": consent_payload, "source_context": "first_real_institutional_launch_rehearsal_v2"},
    )
    assert consent_draft.status_code == 200
    consent_draft_id = consent_draft.get_json()["draft_id"]

    sign = timed(
        "consent_sign",
        "post",
        f"/api/research/consent/draft/{consent_draft_id}/sign",
        json={
            "signer_name": "Paciente Launch Rehearsal PHI",
            "signature_data_url": "data:image/png;base64,TEFVTkNIX1JFSF8=",
            "accepted": True,
            "audit_metadata": {"source_context": "first_real_institutional_launch_rehearsal_v2"},
        },
    )
    assert sign.status_code == 200
    assert sign.get_json()["evidence"]["content_hash"]

    finalize = timed("consent_finalize", "post", f"/api/research/consent/draft/{consent_draft_id}/finalize")
    assert finalize.status_code == 200
    assert finalize.get_json()["consent"]["status"] == "signed"

    profile = timed("profile_v2", "get", f"/patient_profile/{patient_ref}?v=2")
    assert profile.status_code == 200
    profile_html = profile.get_data(as_text=True)
    assert "Consentimiento de uso secundario de datos" in profile_html
    assert "Firma electrónica del paciente" in profile_html
    assert "psaTreatmentTimelineChart" in profile_html
    assert "psaCombinedTimelineChart" in profile_html

    conn = tracking_db._connect()
    try:
        identity = conn.execute(
            """
            SELECT id, is_synthetic, synthetic_flag_reason,
                   real_patient_consent_signed_at,
                   real_patient_consent_actor_user_id
            FROM patient_identity
            WHERE nss = ?
            """,
            (patient_ref,),
        ).fetchone()
        assert identity is not None
        patient_id = int(identity["id"])
        biomarker_rows = conn.execute(
            """
            SELECT biomarker_type, value, sample_date
            FROM biomarker_longitudinal
            WHERE patient_id = ? AND UPPER(biomarker_type) = 'PSA'
            ORDER BY sample_date ASC
            """,
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()

    assert int(identity["is_synthetic"]) == 0
    assert identity["synthetic_flag_reason"] is None
    assert identity["real_patient_consent_signed_at"]
    assert int(identity["real_patient_consent_actor_user_id"]) == 93
    assert len(biomarker_rows) == 2
    assert [round(float(row["value"]), 1) for row in biomarker_rows] == [11.2, 12.0]

    sample = timed(
        "sample_maturity",
        "get",
        "/api/platform-readiness/real-world-sample-maturity?scope=full&limit=20",
    ).get_json()
    assert sample["summary"]["real_patient_count"] == 1
    assert sample["summary"]["synthetic_patient_count"] == 0
    assert sample["summary"]["real_without_actor_count"] == 0
    assert sample["summary"]["real_without_identity_consent_count"] == 0

    summary_queue = timed(
        "real_only_queue_summary",
        "get",
        "/api/platform-readiness/prospective-real-world-completion-queue?scope=summary&limit=20",
    ).get_json()
    assert summary_queue["summary"]["real_patient_count"] == 1
    assert summary_queue["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "real_patient_queue" not in summary_queue
    assert patient_ref not in json.dumps(summary_queue, ensure_ascii=False)
    assert "Paciente Launch Rehearsal PHI" not in json.dumps(summary_queue, ensure_ascii=False)

    full_queue = timed(
        "real_only_queue_full",
        "get",
        "/api/platform-readiness/prospective-real-world-completion-queue?scope=full&limit=20",
    ).get_json()
    row = next(item for item in full_queue["real_patient_queue"] if item["patient_ref"] == patient_ref)
    assert row["consent_present"] is True
    assert row["actor_present"] is True
    assert row["valid_psa_point_count"] == 2
    assert row["ape_status"] == "history_ready"

    verifier_after = timed(
        "launch_flow_verifier_after",
        "get",
        "/api/platform-readiness/real-world-launch-flow-verifier?scope=summary&limit=20",
    ).get_json()
    assert verifier_after["summary"]["real_patient_count"] == 1
    assert verifier_after["summary"]["ui_backend_sync_status"] == "pass"
    assert verifier_after["summary"]["flow_verifier_status"] in {
        "first_real_flow_in_progress",
        "first_real_flow_ready_for_method_review",
    }
    assert verifier_after["summary"]["external_validation_claim_allowed"] is False
    assert verifier_after["no_phi_scan"]["no_phi_status"] == "pass"
    assert patient_ref not in json.dumps(verifier_after, ensure_ascii=False)

    assert max(timings_ms.values()) < 15000
    assert sum(timings_ms.values()) < 45000


def test_clinical_fact_ledger_release_gate_maps_persistence_and_recapture(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/ledger-release-gate?scope=full&field_limit=250")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["summary"]["facts_total"] > 50
    assert payload["summary"]["surface_missing_count"] == 0
    assert payload["summary"]["block_count"] == 0
    assert payload["summary"]["watch_count"] == 0
    assert payload["summary"]["recapture_watch_count"] == 0
    assert payload["summary"]["release_gate_status"] == "ready_for_next_layer"
    assert payload["summary"]["next_layer_allowed"] is True

    baseline_psa = next(row for row in payload["matrix"] if row["fact_key"] == "baseline_psa")
    assert baseline_psa["owner"] == "urology_oncology_data_owner"
    assert "patient_clinical_facts" in baseline_psa["persistence_targets"]
    assert baseline_psa["persistence_status"] == "covered_by_extractor"
    assert baseline_psa["freshness_policy"]["expires"] is True
    assert baseline_psa["recapture_status"] == "normalized_alias"

    current_psa = next(row for row in payload["matrix"] if row["fact_key"] == "current_psa")
    assert current_psa["recapture_status"] == "normalized_alias"

    psa_density = next(row for row in payload["matrix"] if row["fact_key"] == "psa_density")
    assert "psad" in psa_density["legacy_aliases"]
    assert psa_density["persistence_status"] == "covered_by_extractor"
    assert psa_density["recapture_status"] == "normalized_alias"
    assert psa_density["recapture_detail"]["same_module_recapture"] == {}
    assert psa_density["recapture_detail"]["contextual_same_module_alias"]

    ecog_score = next(row for row in payload["matrix"] if row["fact_key"] == "ecog_score")
    assert ecog_score["recapture_status"] == "normalized_alias"
    assert ecog_score["recapture_detail"]["same_module_recapture"] == {}
    assert ecog_score["recapture_detail"]["contextual_same_module_alias"]


def test_clinical_fact_ledger_release_gate_domain_builder_is_read_only():
    gate = build_ledger_release_gate(ModuleRegistry(), scope="full", field_limit=250)

    assert gate["available"] is True
    assert gate["read_only"] is True
    assert gate["source_clinical_facts_mutated"] is False
    assert gate["external_order_created"] is False
    assert gate["model_trained"] is False
    assert gate["summary"]["facts_total"] > 50
    baseline_psa = next(row for row in gate["matrix"] if row["fact_key"] == "baseline_psa")
    assert baseline_psa["persistence_status"] == "covered_by_extractor"


def test_interoperability_map_covers_critical_ledger_facts():
    interop = build_interoperability_map(scope="full", field_limit=500)

    assert interop["available"] is True
    assert interop["read_only"] is True
    assert interop["source_clinical_facts_mutated"] is False
    assert interop["external_order_created"] is False
    assert interop["model_trained"] is False
    assert interop["summary"]["facts_total"] > 100
    assert interop["summary"]["critical_block_count"] == 0
    assert interop["summary"]["critical_mapping_coverage_pct"] == 100.0
    assert interop["summary"]["interoperability_status"] == "ready_for_initial_interop"
    assert interop["summary"]["next_layer_allowed"] is True

    mapping = {row["fact_key"]: row for row in interop["mapping"]}
    baseline_psa = mapping["baseline_psa"]
    assert "PSA" in baseline_psa["mcode_profile"]
    assert baseline_psa["omop_target"] == "MEASUREMENT"
    assert baseline_psa["mapping_status"] == "mapped"

    ecog_score = mapping["ecog_score"]
    assert "ECOGPerformanceStatus" in ecog_score["mcode_profile"]
    assert ecog_score["omop_target"] == "MEASUREMENT"

    clinical_tstage = mapping["clinical_tstage"]
    assert "TNMClinicalPrimaryTumorCategory" in clinical_tstage["mcode_profile"]
    assert "AJCC" in clinical_tstage["vocabulary"]


def test_interoperability_map_api_is_read_only(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/interoperability-map?scope=summary")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["scope"] == "summary"
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["summary"]["critical_block_count"] == 0
    assert payload["summary"]["next_layer_allowed"] is True
    assert "mapping" not in payload


def test_deidentified_export_contract_api_suppresses_direct_phi(app_client):
    client, _db_path = app_client
    payload = {
        "age": 65,
        "psa": 8.5,
        "prostate_volume_ml": 47.2,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "ipss_score": 7,
        "iief5_score": 18,
    }
    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": payload},
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]
    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "localized_initial",
            "nss": "33333339991",
            "full_name": "Paciente Export PHI",
            "dob": "1962-05-28",
            "psa_history": [
                {"sample_date": "2026-05-01", "psa_value": 8.5, "context": "pretratamiento"},
            ],
        },
    )
    assert register_response.status_code == 200

    response = client.get("/api/platform-readiness/deidentified-export-contract?scope=full&limit=20")
    assert response.status_code == 200
    export = response.get_json()

    assert export["success"] is True
    assert export["read_only"] is True
    assert export["source_clinical_facts_mutated"] is False
    assert export["external_order_created"] is False
    assert export["model_trained"] is False
    assert export["deidentified"] is True
    assert export["export_written"] is False
    assert export["external_transfer_performed"] is False
    assert export["summary"]["direct_identifier_key_count"] == 0
    assert export["summary"]["exact_phi_hit_count"] == 0
    assert export["summary"]["next_layer_allowed"] is True
    assert export["summary"]["data_dictionary_field_count"] > 100

    serialized = json.dumps(export, ensure_ascii=False)
    assert "33333339991" not in serialized
    assert "Paciente Export PHI" not in serialized
    assert "1962-05-28" not in serialized
    assert '"patient_id"' not in serialized
    assert "subject_id" in serialized
    assert "baseline_psa" in {row["fact_key"] for row in export["fact_rows"]}

    baseline_row = next(row for row in export["fact_rows"] if row["fact_key"] == "baseline_psa")
    assert baseline_row["subject_id"].startswith("sub_")
    assert baseline_row["omop_target"] == "MEASUREMENT"
    assert "PSA" in baseline_row["mcode_profile"]
    assert baseline_row["source_record_ref"] != str(assessment_id)
    assert all("patient_id" not in row for row in export["fact_rows"])
    assert any(row["fact_key"] == "baseline_psa" for row in export["lineage_rows"])
    assert any(row["biomarker_type"] == "PSA" for row in export["biomarker_rows"])


def test_deidentified_export_contract_domain_builder_is_read_only():
    export = build_deidentified_export_contract(scope="summary", limit=10)

    assert export["available"] is True
    assert export["scope"] == "summary"
    assert export["read_only"] is True
    assert export["source_clinical_facts_mutated"] is False
    assert export["external_order_created"] is False
    assert export["model_trained"] is False
    assert export["deidentified"] is True
    assert export["summary"]["direct_identifier_key_count"] == 0
    assert export["summary"]["unmapped_dictionary_count"] == 0
    assert "fact_rows" not in export


def test_research_pack_materializer_builds_hashes_and_csv_without_phi(app_client):
    client, _db_path = app_client
    payload = {
        "age": 65,
        "psa": 8.5,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
    }
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": payload},
    ).get_json()
    register = client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339992",
            "full_name": "Paciente Pack PHI",
            "dob": "1962-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 8.5}],
        },
    )
    assert register.status_code == 200

    response = client.get("/api/platform-readiness/research-pack-materializer?scope=full&limit=20")
    assert response.status_code == 200
    pack = response.get_json()

    assert pack["success"] is True
    assert pack["read_only"] is True
    assert pack["source_clinical_facts_mutated"] is False
    assert pack["external_order_created"] is False
    assert pack["model_trained"] is False
    assert pack["deidentified"] is True
    assert pack["export_written"] is False
    assert pack["summary"]["next_layer_allowed"] is True
    assert pack["summary"]["file_count"] >= 8
    assert pack["summary"]["total_data_rows"] > 0
    assert pack["summary"]["direct_identifier_key_count"] == 0
    assert pack["summary"]["exact_phi_hit_count"] == 0

    file_names = {item["file_name"] for item in pack["file_manifest"]}
    assert {
        "manifest.json",
        "bundle.json",
        "data_dictionary.csv",
        "fact_rows.csv",
        "lineage_rows.csv",
        "events.csv",
        "treatments.csv",
        "biomarkers.csv",
    } <= file_names
    assert all(len(item["sha256"]) == 64 for item in pack["file_manifest"])

    serialized = json.dumps(pack, ensure_ascii=False)
    assert "33333339992" not in serialized
    assert "Paciente Pack PHI" not in serialized
    assert "1962-05-28" not in serialized
    assert '"patient_id"' not in serialized
    assert "baseline_psa" in pack["files"]["fact_rows.csv"]
    assert "subject_id" in pack["files"]["fact_rows.csv"]


def test_research_pack_materializer_freeze_and_download_are_reproducible(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 8.5, "clinical_tstage": "T2a"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339993",
            "full_name": "Paciente Freeze PHI",
            "dob": "1962-05-28",
        },
    ).status_code == 200

    freeze_response = client.post(
        "/api/platform-readiness/research-pack-materializer/freeze",
        json={
            "limit": 20,
            "title": "Pack desidentificado test",
            "created_by": "unit_test",
            "governance_status": "poster_ready",
            "clinical_objective": "Validar la cohorte institucional sin PHI",
            "research_question": "Cual es la trazabilidad fact-a-outcome de la cohorte?",
            "methodology_note": "Prueba unitaria de freeze gobernado",
            "responsible": "unit_test",
        },
    )
    assert freeze_response.status_code == 200
    freeze = freeze_response.get_json()
    assert freeze["success"] is True
    assert freeze["created"] is True
    assert freeze["freeze_key"].startswith("dxpack_")
    assert freeze["source_clinical_facts_mutated"] is False
    assert freeze["external_order_created"] is False
    assert freeze["model_trained"] is False
    assert freeze["external_transfer_performed"] is False
    freeze_key = freeze["freeze_key"]

    duplicate = client.post(
        "/api/platform-readiness/research-pack-materializer/freeze",
        json={
            "limit": 20,
            "title": "Pack desidentificado test",
            "created_by": "unit_test",
            "governance_status": "poster_ready",
            "clinical_objective": "Validar la cohorte institucional sin PHI",
            "research_question": "Cual es la trazabilidad fact-a-outcome de la cohorte?",
            "methodology_note": "Prueba unitaria de freeze gobernado",
            "responsible": "unit_test",
        },
    ).get_json()
    assert duplicate["created"] is False
    assert duplicate["freeze_key"] == freeze_key

    detail_response = client.get(f"/api/platform-readiness/research-pack-materializer/freezes/{freeze_key}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["freeze"]
    assert detail["registry_type"] == "deidentified_research_pack_v1"
    assert detail["payload_sha256"] == freeze["payload_sha256"]
    assert detail["payload"]["summary"]["next_layer_allowed"] is True
    governance_summary = detail_response.get_json()["governance_summary"]
    assert governance_summary["governance"]["governance_status"] == "poster_ready"
    assert governance_summary["governance"]["research_question"] == "Cual es la trazabilidad fact-a-outcome de la cohorte?"
    assert governance_summary["download_allowed"] is True

    library_response = client.get("/api/platform-readiness/research-pack-materializer/freezes?limit=10")
    assert library_response.status_code == 200
    library = library_response.get_json()
    assert library["success"] is True
    assert library["read_only"] is True
    assert library["source_clinical_facts_mutated"] is False
    assert library["external_order_created"] is False
    assert library["model_trained"] is False
    assert library["external_transfer_performed"] is False
    assert library["registry_type"] == "deidentified_research_pack_v1"
    assert library["summary"]["freeze_count"] >= 1
    assert library["summary"]["download_ready_count"] >= 1
    assert library["freezes"][0]["governance"]["governance_status"] == "poster_ready"
    assert library["freezes"][0]["detail_url"].endswith(f"/{freeze_key}")
    assert library["freezes"][0]["download_url"].endswith(f"/{freeze_key}/download")

    download = client.get(f"/api/platform-readiness/research-pack-materializer/freezes/{freeze_key}/download")
    assert download.status_code == 200
    assert "application/zip" in download.content_type
    import io

    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "fact_rows.csv" in names
        fact_csv = archive.read("fact_rows.csv").decode("utf-8")
        assert "subject_id" in fact_csv
        assert "33333339993" not in fact_csv
        assert "Paciente Freeze PHI" not in fact_csv


def test_research_pack_materializer_domain_builder_summary_is_read_only():
    pack = build_research_pack_materializer(scope="summary", limit=10)

    assert pack["available"] is True
    assert pack["scope"] == "summary"
    assert pack["read_only"] is True
    assert pack["source_clinical_facts_mutated"] is False
    assert pack["external_order_created"] is False
    assert pack["model_trained"] is False
    assert pack["summary"]["direct_identifier_key_count"] == 0
    assert pack["summary"]["download_allowed"] is True
    assert "files" not in pack


def test_research_pack_governance_library_domain_builder_is_read_only():
    library = build_research_pack_freeze_library(limit=5, include_current_preview=False)

    assert library["available"] is True
    assert library["read_only"] is True
    assert library["source_clinical_facts_mutated"] is False
    assert library["external_order_created"] is False
    assert library["model_trained"] is False
    assert library["external_transfer_performed"] is False
    assert library["registry_type"] == "deidentified_research_pack_v1"
    assert "audit_ready" in library["governance_statuses"]
    assert "publication_ready" in library["governance_statuses"]


def test_prospective_pilot_governance_pack_exposes_nas_and_pilot_gates():
    pack = build_prospective_pilot_governance_pack(ModuleRegistry(), scope="full", limit=10)

    assert pack["available"] is True
    assert pack["version"] == "prospective_pilot_governance_pack_v1"
    assert pack["scope"] == "full"
    assert pack["read_only"] is True
    assert pack["source_clinical_facts_mutated"] is False
    assert pack["external_order_created"] is False
    assert pack["model_trained"] is False
    assert pack["external_transfer_performed"] is False
    assert pack["ready_for_external_deployment"] is False
    assert pack["nas_vision_source"]["source_label"] == "Sistema NAS Urologia.docx"
    assert pack["summary"]["source_document_integrated"] is True
    assert pack["summary"]["gate_count"] >= 12
    assert pack["summary"]["ready_for_external_deployment"] is False
    assert pack["summary"]["pilot_status"] in {
        "ready_for_internal_prospective_pilot",
        "ready_for_internal_prospective_pilot_with_watches",
        "pilot_blocked",
    }

    gates = {row["gate_key"]: row for row in pack["gate_matrix"]}
    assert gates["clinical_fact_ledger"]["pilot_blocking"] is True
    assert gates["v2_persistence_matrix"]["pilot_blocking"] is True
    assert gates["clinical_use_boundary"]["status"] == "pass"
    assert gates["nas_local_operations"]["status"] in {"pass", "watch"}
    assert gates["backup_restore_drill"]["status"] in {"pass", "watch"}
    assert pack["protocol_outline"]["primary_endpoints"]
    assert pack["responsibility_matrix"]
    assert pack["nas_operational_readiness"]["deployment_target"].startswith("Local NAS")
    assert any(item["component"] == "Platform Readiness" for item in pack["pilot_packet_manifest"])


def test_prospective_pilot_governance_api_is_read_only(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/prospective-pilot-governance?scope=summary&limit=20")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["version"] == "prospective_pilot_governance_pack_v1"
    assert payload["scope"] == "summary"
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["ready_for_external_deployment"] is False
    assert payload["summary"]["gate_count"] >= 12
    assert "gate_matrix" in payload
    assert "required_actions" in payload
    assert "protocol_outline" not in payload

    full = client.get("/api/platform-readiness/prospective-pilot-governance?scope=full&limit=20").get_json()
    assert full["success"] is True
    assert full["scope"] == "full"
    assert full["protocol_outline"]["pilot_name"].startswith("ProstaMed local")
    assert full["responsibility_matrix"]
    assert full["consent_and_data_use"]["required_items"]
    assert full["nas_operational_readiness"]["source"]["source_label"] == "Sistema NAS Urologia.docx"
    assert full["adoption_milestones"][0]["window"] == "0-3 months"


def test_nas_pilot_evidence_vault_domain_builder_is_read_only(app_client):
    _client, _db_path = app_client

    vault = build_nas_pilot_evidence_vault(scope="full", limit=10)

    assert vault["available"] is True
    assert vault["version"] == "nas_pilot_operations_evidence_vault_v1"
    assert vault["scope"] == "full"
    assert vault["read_only"] is True
    assert vault["source_clinical_facts_mutated"] is False
    assert vault["external_order_created"] is False
    assert vault["model_trained"] is False
    assert vault["external_transfer_performed"] is False
    assert vault["deidentified"] is True
    assert len(vault["gate_statuses"]) == 7
    assert vault["summary"]["gate_count"] == 7
    assert vault["summary"]["vault_status"] in {"needs_operational_evidence", "complete", "blocked"}
    assert vault["no_phi_scan"]["no_phi_status"] == "pass"
    assert "nas_local_operations" in {
        option["gate_key"] for option in vault["evidence_form_schema"]["gate_options"]
    }


def test_nas_pilot_evidence_vault_api_attestation_closes_gate_without_phi(app_client):
    client, _db_path = app_client

    initial = client.get("/api/platform-readiness/nas-pilot-evidence-vault?scope=summary&limit=20")
    assert initial.status_code == 200
    initial_payload = initial.get_json()
    assert initial_payload["success"] is True
    assert initial_payload["gate_statuses"]["nas_local_operations"]["gate_status"] == "watch"

    response = client.post(
        "/api/platform-readiness/nas-pilot-evidence-vault/attest",
        json={
            "gate_key": "nas_local_operations",
            "title": "Runbook local NAS validado",
            "verified_by": "it_nas_owner",
            "reviewer_role": "it_nas_owner",
            "evidence_date": "2026-05-28",
            "evidence_ref": "NAS-RUNBOOK-LOCAL-001",
            "audit_note": "Docker, IP local, firewall, UPS y health check documentados sin PHI.",
            "attestation_details": {
                "runbook": "docker-compose local",
                "health_check": "http://127.0.0.1:8093/platform-readiness",
            },
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["no_phi_scan"]["no_phi_status"] == "pass"
    assert payload["gate_status"]["gate_status"] == "pass"

    full = client.get("/api/platform-readiness/nas-pilot-evidence-vault?scope=full&limit=20").get_json()
    assert full["gate_statuses"]["nas_local_operations"]["gate_status"] == "pass"
    assert full["summary"]["verified_gate_count"] >= 1
    assert full["no_phi_scan"]["no_phi_status"] == "pass"

    prospective = client.get(
        "/api/platform-readiness/prospective-pilot-governance?scope=summary&limit=20"
    ).get_json()
    gates = {row["gate_key"]: row for row in prospective["gate_matrix"]}
    assert gates["nas_local_operations"]["status"] == "pass"
    assert prospective["summary"]["operational_evidence_verified_gate_count"] >= 1

    rejected = client.post(
        "/api/platform-readiness/nas-pilot-evidence-vault/attest",
        json={
            "gate_key": "backup_restore_drill",
            "title": "Restore con identificador directo",
            "verified_by": "it_nas_owner",
            "reviewer_role": "it_nas_owner",
            "audit_note": "Debe bloquearse antes de persistir.",
            "attestation_details": {"nss": "33333339999"},
        },
    )
    assert rejected.status_code == 400
    rejected_payload = rejected.get_json()
    assert rejected_payload["error"] == "phi_like_content_rejected"
    assert rejected_payload["no_phi_scan"]["no_phi_status"] == "block"


def test_nas_pilot_evidence_vault_zip_is_no_phi(app_client):
    client, _db_path = app_client

    response = client.post(
        "/api/platform-readiness/nas-pilot-evidence-vault/attest",
        json={
            "gate_key": "training_and_adoption",
            "title": "Capacitacion inicial equipo urologia",
            "verified_by": "clinical_operations_owner",
            "reviewer_role": "clinical_operations_owner",
            "evidence_date": "2026-05-28",
            "audit_note": "Asistentes por rol, objetivo de captura y huddle semanal documentados sin PHI.",
        },
    )
    assert response.status_code == 200

    download = client.get("/api/platform-readiness/nas-pilot-evidence-vault/download")
    assert download.status_code == 200
    assert download.mimetype == "application/zip"

    zip_file = zipfile.ZipFile(io.BytesIO(download.data))
    names = set(zip_file.namelist())
    assert {"README.md", "evidence_vault.json", "gate_status.csv", "evidence_manifest.csv"} <= names
    combined = "\n".join(zip_file.read(name).decode("utf-8") for name in sorted(names))
    assert "33333339999" not in combined
    assert "patient_profile" not in combined

    vault = build_nas_pilot_evidence_vault(scope="full", limit=20)
    zip_bytes = build_nas_pilot_evidence_vault_zip_bytes(vault)
    assert len(zip_bytes) > 500


def test_pilot_adoption_command_center_domain_builder_is_summary_safe(app_client):
    _client, _db_path = app_client

    command = build_pilot_adoption_command_center(scope="summary", limit=20)

    assert command["available"] is True
    assert command["version"] == "pilot_adoption_completeness_command_center_v1"
    assert command["scope"] == "summary"
    assert command["read_only"] is True
    assert command["source_clinical_facts_mutated"] is False
    assert command["external_order_created"] is False
    assert command["model_trained"] is False
    assert command["external_transfer_performed"] is False
    assert command["deidentified_export_written"] is False
    assert command["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "patient_worklist" not in command
    assert command["summary"]["command_status"] in {
        "no_patients_captured",
        "needs_capture_hardening",
        "pilot_adoption_ready",
    }


def test_pilot_adoption_command_center_api_tracks_v2_capture_and_drilldown(app_client):
    client, _db_path = app_client

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 65,
                "psa": 8.5,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 4,
                "total_cores": 12,
                "ipss_score": 7,
                "iief5_score": 18,
            },
        },
    ).get_json()
    register = client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339994",
            "full_name": "Paciente Adoption PHI",
            "dob": "1961-05-28",
            "psa_history": [
                {"sample_date": "2026-04-01", "psa_value": 7.9, "context": "pretratamiento"},
                {"sample_date": "2026-05-01", "psa_value": 8.5, "context": "pretratamiento"},
            ],
        },
    )
    assert register.status_code == 200

    summary_response = client.get("/api/platform-readiness/pilot-adoption-command-center?scope=summary&limit=20")
    assert summary_response.status_code == 200
    summary = summary_response.get_json()

    assert summary["success"] is True
    assert summary["scope"] == "summary"
    assert summary["read_only"] is True
    assert summary["source_clinical_facts_mutated"] is False
    assert summary["external_order_created"] is False
    assert summary["model_trained"] is False
    assert summary["external_transfer_performed"] is False
    assert summary["summary"]["patient_count"] >= 1
    assert summary["summary"]["assessment_linked_patient_count"] >= 1
    assert summary["summary"]["psa_history_patient_count"] >= 1
    assert summary["summary_no_phi_scan"]["no_phi_status"] == "pass"
    serialized_summary = json.dumps(summary, ensure_ascii=False)
    assert "33333339994" not in serialized_summary
    assert "Paciente Adoption PHI" not in serialized_summary
    assert "patient_worklist" not in summary

    full_response = client.get("/api/platform-readiness/pilot-adoption-command-center?scope=full&limit=20")
    assert full_response.status_code == 200
    full = full_response.get_json()

    assert full["success"] is True
    assert full["scope"] == "full"
    assert full["drilldown_policy"]["surface"] == "patient_profile_v2"
    worklist = full["patient_worklist"]
    assert any(row["profile_url"] == "/patient_profile/33333339994?v=2" for row in worklist)
    row = next(row for row in worklist if row["profile_url"] == "/patient_profile/33333339994?v=2")
    assert row["psa_point_count"] >= 2
    assert row["completeness_pct"] > 50
    assert row["subject_id"].startswith("sub_")


def test_prospective_gap_closure_huddle_domain_builder_is_summary_safe(app_client):
    _client, _db_path = app_client

    huddle = build_prospective_gap_closure_huddle(scope="summary", limit=20)

    assert huddle["available"] is True
    assert huddle["version"] == "prospective_gap_closure_huddle_v1"
    assert huddle["scope"] == "summary"
    assert huddle["read_only"] is True
    assert huddle["source_clinical_facts_mutated"] is False
    assert huddle["external_order_created"] is False
    assert huddle["model_trained"] is False
    assert huddle["external_transfer_performed"] is False
    assert huddle["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "huddle_items" not in huddle
    assert "weekly_export_preview" in huddle


def test_prospective_gap_closure_huddle_close_writes_event_only_and_keeps_gap_visible(app_client):
    client, _db_path = app_client

    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 66,
                "psa": 10.2,
                "clinical_tstage": "T2c",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 5,
                "total_cores": 12,
            },
        },
    ).get_json()
    register = client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339995",
            "full_name": "Paciente Huddle PHI",
            "dob": "1960-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 10.2}],
        },
    )
    assert register.status_code == 200

    full = client.get("/api/platform-readiness/prospective-gap-closure-huddle?scope=full&limit=20")
    assert full.status_code == 200
    huddle = full.get_json()
    assert huddle["success"] is True
    assert huddle["summary_no_phi_scan"]["no_phi_status"] == "pass"
    item = next(
        row for row in huddle["huddle_items"]
        if row["patient_ref"] == "33333339995" and row["gap_key"] == "ipss_total"
    )
    assert item["huddle_status"] == "open"
    assert item["profile_url"] == "/patient_profile/33333339995?v=2"

    close = client.post(
        "/api/platform-readiness/prospective-gap-closure-huddle/close",
        json={
            "patient_ref": "33333339995",
            "gap_key": "ipss_total",
            "closure_status": "reviewed_still_missing",
            "reviewed_by": "clinician",
            "clinical_note": "Se solicitara IPSS en la siguiente captura longitudinal.",
        },
    )
    assert close.status_code == 200
    result = close.get_json()
    assert result["success"] is True
    assert result["event_id"]
    assert result["source_clinical_facts_mutated"] is False
    assert result["external_order_created"] is False
    assert result["model_trained"] is False
    assert result["external_transfer_performed"] is False
    assert result["huddle_item"]["huddle_status"] == "reviewed_still_open"
    assert result["huddle_item"]["gap_still_visible_if_missing"] is True

    refreshed = client.get("/api/platform-readiness/prospective-gap-closure-huddle?scope=full&limit=20").get_json()
    refreshed_item = next(
        row for row in refreshed["huddle_items"]
        if row["patient_ref"] == "33333339995" and row["gap_key"] == "ipss_total"
    )
    assert refreshed_item["huddle_status"] == "reviewed_still_open"
    assert refreshed_item["closure_status"] == "reviewed_still_missing"

    rejected = client.post(
        "/api/platform-readiness/prospective-gap-closure-huddle/close",
        json={
            "patient_ref": "33333339995",
            "gap_key": "iief5_score",
            "closure_status": "reviewed_still_missing",
            "reviewed_by": "clinician",
            "clinical_note": "Incluye identificador 33333339995 y debe bloquearse.",
        },
    )
    assert rejected.status_code == 400
    assert rejected.get_json()["error"] == "phi_like_content_rejected"


def test_prospective_gap_closure_huddle_export_is_no_phi(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 9.1, "clinical_tstage": "T2a"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339996",
            "full_name": "Paciente Huddle Export PHI",
            "dob": "1963-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 9.1}],
        },
    ).status_code == 200

    download = client.get("/api/platform-readiness/prospective-gap-closure-huddle/export?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/csv"
    csv_text = download.data.decode("utf-8")
    assert "subject_id,gap_key" in csv_text
    assert "33333339996" not in csv_text
    assert "Paciente Huddle Export PHI" not in csv_text
    assert "1963-05-28" not in csv_text

    huddle = build_prospective_gap_closure_huddle(scope="full", limit=20)
    csv_bytes = build_prospective_gap_huddle_csv_bytes(huddle)
    assert b"subject_id,gap_key" in csv_bytes


def test_ape_longitudinal_completion_sprint_domain_builder_is_summary_safe(app_client):
    _client, _db_path = app_client

    sprint = build_ape_longitudinal_completion_sprint(scope="summary", limit=20)

    assert sprint["available"] is True
    assert sprint["version"] == "ape_longitudinal_completion_sprint_v1"
    assert sprint["scope"] == "summary"
    assert sprint["read_only"] is True
    assert sprint["source_clinical_facts_mutated"] is False
    assert sprint["external_order_created"] is False
    assert sprint["model_trained"] is False
    assert sprint["external_transfer_performed"] is False
    assert sprint["summary"]["clinical_values_captured_here"] is False
    assert sprint["summary_no_phi_scan"]["no_phi_status"] == "pass"
    assert "ape_worklist" not in sprint
    assert "weekly_export_preview" in sprint


def test_ape_longitudinal_completion_sprint_api_routes_single_psa_to_official_capture(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "psa": 11.4,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "num_cores_positive": 4,
                "total_cores": 12,
            },
        },
    ).get_json()
    register = client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339997",
            "full_name": "Paciente APE Sprint PHI",
            "dob": "1964-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 11.4}],
        },
    )
    assert register.status_code == 200

    summary_response = client.get("/api/platform-readiness/ape-longitudinal-completion-sprint?scope=summary&limit=20")
    assert summary_response.status_code == 200
    summary = summary_response.get_json()

    assert summary["success"] is True
    assert summary["scope"] == "summary"
    assert summary["read_only"] is True
    assert summary["source_clinical_facts_mutated"] is False
    assert summary["external_order_created"] is False
    assert summary["model_trained"] is False
    assert summary["external_transfer_performed"] is False
    assert summary["summary_no_phi_scan"]["no_phi_status"] == "pass"
    serialized_summary = json.dumps(summary, ensure_ascii=False)
    assert "33333339997" not in serialized_summary
    assert "Paciente APE Sprint PHI" not in serialized_summary
    assert "1964-05-28" not in serialized_summary
    assert "ape_worklist" not in summary

    full_response = client.get("/api/platform-readiness/ape-longitudinal-completion-sprint?scope=full&limit=20")
    assert full_response.status_code == 200
    full = full_response.get_json()

    row = next(row for row in full["ape_worklist"] if row["patient_ref"] == "33333339997")
    assert row["ape_status"] == "single_psa_point"
    assert row["psa_point_count"] == 1
    assert row["capture_url"] == "/longitudinal-capture/33333339997?decision_lane=localized_initial&decision_field=psa_history"
    assert row["profile_url"] == "/patient_profile/33333339997?v=2"
    assert row["registry_unlock_potential"] is True
    assert row["no_duplicate_capture_policy"].startswith("reuse existing baseline")
    assert row["ledger_lineage"]
    assert {fact["fact_key"] for fact in row["ledger_lineage"]} & {"baseline_psa", "current_psa"}


def test_ape_longitudinal_completion_sprint_export_is_no_phi(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 8.9, "clinical_tstage": "T2a"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339998",
            "full_name": "Paciente APE Export PHI",
            "dob": "1965-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 8.9}],
        },
    ).status_code == 200

    download = client.get("/api/platform-readiness/ape-longitudinal-completion-sprint/export?limit=20")
    assert download.status_code == 200
    assert download.mimetype == "text/csv"
    csv_text = download.data.decode("utf-8")
    assert "subject_id,ape_status" in csv_text
    assert "33333339998" not in csv_text
    assert "Paciente APE Export PHI" not in csv_text
    assert "1965-05-28" not in csv_text

    sprint = build_ape_longitudinal_completion_sprint(scope="full", limit=20)
    csv_bytes = build_ape_longitudinal_completion_csv_bytes(sprint)
    assert b"subject_id,ape_status" in csv_bytes


def test_ape_capture_impact_loop_closes_single_psa_gap_after_append(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "psa": 10.6,
                "clinical_tstage": "T2b",
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
            },
        },
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339999",
            "full_name": "Paciente APE Impact PHI",
            "dob": "1966-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 10.6}],
        },
    ).status_code == 200

    before = build_patient_ape_completion_snapshot("33333339999")
    assert before["available"] is True
    assert before["ape_status"] == "single_psa_point"
    assert before["valid_psa_point_count"] == 1

    current_response = client.get("/api/patients/33333339999/ape-capture-impact")
    assert current_response.status_code == 200
    assert current_response.get_json()["snapshot"]["ape_status"] == "single_psa_point"

    append = client.post(
        "/api/longitudinal/33333339999/append",
        json={
            "kind": "psa",
            "payload": {
                "date": "2026-06-01",
                "value": 8.4,
                "context": "impact_loop_test",
            },
        },
    )
    assert append.status_code == 200
    body = append.get_json()
    impact = body["ape_capture_impact"]

    assert impact["version"] == "ape_capture_impact_loop_v1"
    assert impact["append_success"] is True
    assert impact["source_clinical_facts_mutated"] is False
    assert impact["external_order_created"] is False
    assert impact["model_trained"] is False
    assert impact["external_transfer_performed"] is False
    assert impact["before"]["ape_status"] == "single_psa_point"
    assert impact["after"]["ape_status"] == "history_ready"
    assert impact["point_count_delta"] == 1
    assert impact["gap_closed"] is True
    assert impact["registry_ready_after_capture"] is True
    assert "patient_profile_v2_psa_tower" in impact["refreshed_surfaces"]
    assert impact["next_surfaces"]["profile_v2"] == "/patient_profile/33333339999?v=2"
    assert impact["next_surfaces"]["sprint"] == "/platform-readiness#ape-longitudinal-completion-sprint"
    assert body["cache_invalidation"]["success"] is True

    after = build_patient_ape_completion_snapshot("33333339999")
    assert after["ape_status"] == "history_ready"
    direct_impact = build_ape_capture_impact(
        "33333339999",
        before_snapshot=before,
        kind="psa",
        append_result={"success": True, "appended_id": body["appended_id"]},
        recompute_result={"success": True},
    )
    assert direct_impact["gap_closed"] is True
    assert direct_impact["after"]["valid_psa_point_count"] == 2


def test_longitudinal_capture_v2_renders_ape_capture_impact_panel(app_client):
    client, _db_path = app_client
    draft = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": {"psa": 7.2, "clinical_tstage": "T2a"}},
    ).get_json()
    assert client.post(
        "/api/register_patient",
        json={
            "assessment_id": draft["assessment_id"],
            "assessment_state": "localized_initial",
            "nss": "33333339995",
            "full_name": "Paciente APE Panel PHI",
            "dob": "1967-05-28",
            "psa_history": [{"sample_date": "2026-05-01", "psa_value": 7.2}],
        },
    ).status_code == 200

    response = client.get("/longitudinal-capture/33333339995?decision_field=psa_history")
    assert response.status_code == 200
    html = response.data.decode("utf-8", errors="replace")
    assert 'data-testid="ape-capture-impact-panel"' in html
    assert 'data-ape-status="single_psa_point"' in html
    assert "function pm2RenderApeCaptureImpact" in html
    assert "body.ape_capture_impact" in html


def test_ledger_persistence_matrix_tracks_v2_flows_and_baseline_psa(app_client):
    client, _db_path = app_client

    response = client.get("/api/platform-readiness/ledger-persistence-matrix?scope=full&row_limit=800")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["read_only"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["summary"]["flow_count"] >= 8
    assert payload["summary"]["route_missing_count"] == 0
    assert payload["summary"]["flow_block_count"] == 0
    assert payload["summary"]["fact_block_count"] == 0
    assert payload["summary"]["matrix_status"] in {
        "ready_for_next_layer",
        "needs_hardening",
    }

    flows = {row["flow_key"]: row for row in payload["flow_summary"]}
    assert flows["registration"]["registered"] is True
    assert flows["registration"]["block_count"] == 0
    assert not [
        row
        for row in payload["matrix"]
        if row["flow_key"] == "registration"
        and "fact_without_registration_extractor" in (row.get("warnings") or [])
    ]
    assert flows["profile_v2"]["registered"] is True
    assert flows["decision_today"]["registered"] is True
    assert flows["schedule"]["registered"] is True

    baseline_registration = next(
        row
        for row in payload["matrix"]
        if row["flow_key"] == "registration" and row["fact_key"] == "baseline_psa"
    )
    assert baseline_registration["persistence_status"] == "covered_by_extractor"
    assert baseline_registration["recapture_status"] == "normalized_alias"
    assert baseline_registration["flow_status"] == "pass"

    baseline_profile = next(
        row
        for row in payload["matrix"]
        if row["flow_key"] == "profile_v2" and row["fact_key"] == "baseline_psa"
    )
    assert baseline_profile["route_registered"] is True
    assert baseline_profile["flow_status"] in {"pass", "watch"}


def test_ledger_persistence_matrix_domain_builder_is_read_only():
    matrix = build_ledger_persistence_matrix(ModuleRegistry(), scope="full", row_limit=800)

    assert matrix["available"] is True
    assert matrix["read_only"] is True
    assert matrix["source_clinical_facts_mutated"] is False
    assert matrix["external_order_created"] is False
    assert matrix["model_trained"] is False
    assert matrix["summary"]["flow_count"] >= 8
    assert any(row["flow_key"] == "registration" for row in matrix["flow_summary"])


def test_registration_extracts_ledger_blocking_facts_used_by_persistence_matrix():
    facts = extract_canonical_fact_candidates(
        {
            "m0_crpc_state_confirmed": "true",
            "charlson_score": "5",
            "frailty_status": "prefrail",
            "anesthesia_surgical_fitness": "fit",
            "radiotherapy_feasibility": "feasible",
            "genomic_classifier": "Decipher",
            "genomic_classifier_result": "Alto",
            "albumin_g_dl": "3.9",
            "ldh_u_l": "220",
            "egfr_ml_min": "72",
            "age_current": "68",
            "psa_current_date": "2026-04-15",
            "clinical_tstage": "T2b",
            "num_cores_positive": "4",
            "prior_radiation": "1",
            "prior_prostatectomy": "0",
            "prior_adt": "1",
            "adt_active": "1",
            "castration_resistant": "Pendiente",
            "prior_rt_modality": "IMRT",
            "prior_rt_completion_date": "2024-02-01",
            "on_zoledronate": "0",
            "germline_testing_performed": "true",
            "germline_pathogenic_variant": "BRCA2",
            "visceral_liver": "false",
            "adt_start_date": "2026-01-10",
            "medication_list": "metformina",
        },
        source_type="wizard",
        source_record_type="clinical_assessment",
    )
    by_key = {fact["fact_key"]: fact for fact in facts}

    assert by_key["m0_crpc_state_confirmed"]["value"] is True
    assert by_key["charlson_score"]["value"] == 5
    assert by_key["frailty_status"]["value"] == "prefrail"
    assert by_key["anesthesia_surgical_fitness"]["value"] == "fit"
    assert by_key["radiotherapy_feasibility"]["value"] == "feasible"
    assert by_key["genomic_classifier_type"]["value"] == "Decipher"
    assert by_key["genomic_classifier_result"]["value"] == "Alto"
    assert by_key["albumin_g_dl"]["value"] == 3.9
    assert by_key["ldh_u_l"]["value"] == 220
    assert by_key["egfr_ml_min"]["value"] == 72
    assert by_key["age"]["value"] == 68
    assert by_key["psa_current_date"]["value"] == "2026-04-15"
    assert by_key["clinical_tstage"]["value"] == "T2b"
    assert by_key["num_cores_positive"]["value"] == 4
    assert by_key["prior_radiation"]["value"] is True
    assert by_key["prior_prostatectomy"]["value"] is False
    assert by_key["prior_adt"]["value"] is True
    assert by_key["adt_active"]["value"] is True
    assert by_key["castration_resistant"]["value"] == "Pendiente"
    assert by_key["prior_rt_modality"]["value"] == "IMRT"
    assert by_key["prior_rt_completion_date"]["value"] == "2024-02-01"
    assert by_key["on_zoledronate"]["value"] is False
    assert by_key["germline_testing_performed"]["value"] is True
    assert by_key["germline_pathogenic_variant"]["value"] == "BRCA2"
    assert by_key["visceral_liver"]["value"] is False
    assert by_key["adt_start_date"]["value"] == "2026-01-10"
    assert by_key["medication_list"]["value"] == "metformina"


def test_genomic_classifier_name_is_not_persisted_as_result():
    facts = extract_canonical_fact_candidates(
        {
            "genomic_classifier": "Decipher",
            "genomic_classifier_report_date": "2026-03-01",
        },
        source_type="wizard",
        source_record_type="clinical_assessment",
    )
    by_key = {fact["fact_key"]: fact for fact in facts}

    assert by_key["genomic_classifier_type"]["value"] == "Decipher"
    assert "genomic_classifier_result" not in by_key


def test_wizard_v2_suppresses_duplicate_lab_aliases_but_backend_accepts_canonical_values():
    registry = ModuleRegistry()
    schema = humanize_schema(registry.get_module_schema("m1_crpc"))
    fields_by_name = {field["name"]: field for field in schema["fields"]}

    assert fields_by_name["alkaline_phosphatase_u_l"].get("suppress_in_wizard") is not True
    assert fields_by_name["ldh_u_l"].get("suppress_in_wizard") is not True
    assert fields_by_name["hemoglobin_g_dl"].get("suppress_in_wizard") is not True
    assert fields_by_name["alp"]["suppress_in_wizard"] is True
    assert fields_by_name["ldh"]["suppress_in_wizard"] is True
    assert fields_by_name["hemoglobin"]["suppress_in_wizard"] is True

    normalized = normalize_advanced_support_payload(
        {
            "alkaline_phosphatase_u_l": "190",
            "ldh_u_l": "310",
            "hemoglobin_g_dl": "10.4",
        },
        state="m1_crpc",
    )

    assert normalized["alp"] == "190"
    assert normalized["ldh"] == "310"
    assert normalized["hemoglobin"] == "10.4"


def test_platform_readiness_page_renders(app_client):
    client, _db_path = app_client

    response = client.get("/platform-readiness")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-testid="platform-readiness"' in html
    assert 'data-testid="capture-integrity-readiness"' in html
    assert 'data-testid="capture-integrity-kpi"' in html
    assert 'data-testid="v2-persistence-closure"' in html
    assert 'data-testid="v2-persistence-closure-kpi"' in html
    assert 'data-testid="v2-treatment-value-closure"' in html
    assert 'data-testid="v2-treatment-value-closure-kpi"' in html
    assert 'data-testid="ledger-release-gate"' in html
    assert 'data-testid="ledger-persistence-matrix"' in html
    assert 'data-testid="interoperability-map"' in html
    assert 'data-testid="deidentified-export-contract"' in html
    assert 'data-testid="research-pack-materializer"' in html
    assert 'data-testid="research-pack-freeze-library"' in html
    assert 'data-testid="prospective-pilot-governance"' in html
    assert 'data-testid="nas-pilot-evidence-vault"' in html
    assert 'data-testid="nas-pilot-evidence-form"' in html
    assert 'data-testid="pilot-adoption-command-center"' in html
    assert 'data-testid="prospective-gap-closure-huddle"' in html
    assert 'data-testid="prospective-gap-huddle-close-form"' in html
    assert 'data-testid="ape-longitudinal-completion-sprint"' in html
    assert 'data-testid="ape-longitudinal-completion-sprint-kpi"' in html
    assert 'data-testid="real-world-sample-maturity"' in html
    assert 'data-testid="real-world-sample-maturity-kpi"' in html
    assert 'data-testid="prospective-real-world-completion-queue"' in html
    assert 'data-testid="prospective-real-world-completion-queue-kpi"' in html
    assert 'data-testid="real-world-pilot-packet"' in html
    assert 'data-testid="real-world-pilot-packet-kpi"' in html
    assert 'data-testid="real-world-pilot-execution-log"' in html
    assert 'data-testid="real-world-pilot-execution-log-kpi"' in html
    assert 'data-testid="real-world-first-patient-launch-mode"' in html
    assert 'data-testid="real-world-first-patient-launch-mode-kpi"' in html
    assert 'data-testid="real-world-launch-flow-verifier"' in html
    assert 'data-testid="real-world-launch-flow-verifier-kpi"' in html
    assert 'data-testid="external-validation-worklist"' in html
    assert 'data-testid="external-validation-worklist-kpi"' in html
    assert "Clinical Platform Readiness Audit" in html
    assert "Compuerta de integridad por etapa" in html
    assert "Cierre end-to-end de estadificación inicial" in html
    assert "Cierre de costos, dosis y registro poblacional" in html
    assert "Compuerta de liberacion anti-recaptura" in html
    assert "Matriz de persistencia paciente-a-fact" in html
    assert "Mapa interoperable mCODE / OMOP" in html
    assert "Contrato de export desidentificado" in html
    assert "Pack CSV/JSON congelable" in html
    assert "Biblioteca gobernada de freezes" in html
    assert "Governance pack prospectivo" in html
    assert "Evidence vault operacional" in html
    assert "Torre de adopcion y completitud prospectiva" in html
    assert "Workbench de cierre prospectivo de brechas" in html
    assert "Sprint de completitud APE longitudinal" in html
    assert "Compuerta de madurez de muestra real" in html
    assert "Cola real-only de completitud prospectiva" in html
    assert "Paquete operativo de primer paciente real" in html
    assert "Bitacora operacional del piloto real" in html
    assert "Modo de ejecucion institucional del primer real" in html
    assert "Verificador del flujo V2 del primer real" in html
    assert "Worklist para cerrar la brecha multicentro" in html
    assert "/api/platform-readiness/prospective-pilot-governance" in html
    assert "/api/platform-readiness/nas-pilot-evidence-vault" in html
    assert "/api/platform-readiness/pilot-adoption-command-center" in html
    assert "/api/platform-readiness/prospective-gap-closure-huddle" in html
    assert "/api/platform-readiness/ape-longitudinal-completion-sprint" in html
    assert "/api/platform-readiness/real-world-sample-maturity" in html
    assert "/api/platform-readiness/prospective-real-world-completion-queue" in html
    assert "/api/platform-readiness/real-world-pilot-packet" in html
    assert "/api/platform-readiness/real-world-pilot-execution-log" in html
    assert "/api/platform-readiness/real-world-first-patient-launch-mode" in html
    assert "/api/platform-readiness/real-world-launch-flow-verifier" in html
    assert "/api/platform-readiness/external-validation-worklist" in html
    assert "/api/platform-readiness/capture-integrity" in html
    assert "/api/platform-readiness/v2-persistence-closure" in html
    assert "/api/platform-readiness/v2-treatment-value-closure" in html
    assert "Rutas clinicas criticas" in html
