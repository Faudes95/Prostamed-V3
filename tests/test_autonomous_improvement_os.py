from __future__ import annotations
# IEC 62304 §5.7 (software system testing).

from pathlib import Path

import pytest

from prostanet.agentic.autonomous_improvement_os import (
    build_agent_consensus_synthesizer,
    build_agent_implementation_brief,
    build_agent_lane_registry,
    build_agent_proposal_packets,
    build_ai_readiness_dataset_loop,
    build_application_telemetry,
    build_controlled_patch_application,
    build_controlled_pr_implementation,
    build_cortana_loop_interface,
    build_continuous_shadow_operation,
    build_development_autodrive,
    build_clinical_gap_contract_registry,
    build_contradiction_rule_registry,
    build_draft_pr_handoff,
    build_draft_pr_publication_gate,
    build_evidence_refresh_shadow_loop,
    build_human_patch_authorization,
    build_human_review_decision_gate,
    build_mission_control,
    build_patient_twin_readiness_loop,
    build_pr_review_monitor,
    build_proposals,
    build_required_safety_gate_contract,
    build_safety_gate_runner,
    build_shadow_execution_artifacts,
    build_shadow_pr_factory,
    build_shadow_patch_blueprint,
    derive_contradiction_rows,
    derive_contractual_gap_rows,
    escalate_stuck_candidate,
    rank_candidates,
    record_human_patch_authorization_decision,
    record_human_review_gate_decision,
    record_pr_review_monitor_metadata,
    validate_candidate,
    _decision_today_gap_title,
)


def _candidate(**overrides):
    base = {
        "id": "cand-test",
        "lane": "critical_clinical_gap",
        "title": "Close clinical gap",
        "description": "A test-backed clinical gap.",
        "clinical_impact": 8,
        "severity": 8,
        "effort_h": 2.0,
        "risk_avoided": "Avoids incomplete Decision Today.",
        "source": "unit_test",
        "evidence": ["internal contract"],
        "tests_required": ["test_contract"],
        "surfaces": ["decision-today"],
    }
    base.update(overrides)
    return base


def test_mission_control_contract_is_shadow_mode_and_does_not_mutate(monkeypatch):
    monkeypatch.setenv("AGENTIC_AUTO_MERGE", "false")
    gap_bundle = {
        "candidates": [_candidate()],
        "context": {
            "contracts": {
                "gates_total": 103,
                "gates_contract_covered": 103,
                "trials_contract_ok": True,
            },
            "patients": {"evaluated": 0, "decision_state_counts": {}, "errors": []},
            "loop_summary": {},
            "compliance_snapshot": {"aggregate": 80, "scores": {"p6": {"score": 100}, "p5": {"score": 80}}},
            "patient_twin_available": False,
        },
    }
    development = build_development_autodrive(gap_bundle["candidates"])
    mission = build_mission_control(gap_bundle=gap_bundle, development_autodrive=development)

    assert mission["summary"]["mode"] == "shadow"
    assert mission["safety"]["auto_merge_enabled"] is False
    assert mission["safety"]["source_clinical_facts_mutated"] is False
    assert mission["audit"]["no_ml_model_trained"] is True


def test_gap_ranking_prioritizes_clinical_safety_over_ui():
    ui = _candidate(id="ui", lane="ui_workflow_gap", title="UI polish", clinical_impact=3, severity=3, effort_h=1)
    safety = _candidate(
        id="safety",
        lane="safety_security_gap",
        title="PHI safety gap",
        clinical_impact=9,
        severity=9,
        effort_h=1,
    )

    ranked = rank_candidates([ui, safety])

    assert ranked[0]["id"] == "safety"
    assert ranked[0]["score_breakdown"]["safety_security"] > 0
    assert ranked[0]["priority_class"] in {"critical_clinical_gap", "high_today"}


def test_gap_ranking_caps_effort_penalty_for_critical_clinical_gaps():
    clinical = _candidate(
        id="critical-clinical",
        lane="critical_clinical_gap",
        title="Critical clinical gap with larger patch",
        clinical_impact=10,
        severity=10,
        effort_h=6.0,
        patient_scope={"affected_count": 8},
        clinical_contract={"contract_id": "clinical_priority_contract"},
    )
    regulatory = _candidate(
        id="small-regulatory",
        lane="regulatory_traceability_gap",
        title="Small regulatory task",
        clinical_impact=7,
        severity=7,
        effort_h=2.0,
    )

    ranked = rank_candidates([regulatory, clinical])

    assert ranked[0]["id"] == "critical-clinical"
    assert ranked[0]["score_breakdown"]["effort_divisor"] <= 2.5
    assert ranked[0]["score_breakdown"]["effort_penalty_model"] == "capped_clinical_divisor"
    assert ranked[0]["score_breakdown"]["clinical_priority"] > ranked[1]["score_breakdown"]["clinical_priority"]
    assert ranked[0]["score_breakdown"]["execution_fit"] > 0


def test_development_autodrive_exposes_scoring_transparency_contract():
    clinical = _candidate(
        id="critical-clinical",
        lane="critical_clinical_gap",
        title="Critical clinical gap",
        clinical_impact=10,
        severity=10,
        effort_h=6.0,
        patient_scope={"affected_count": 8},
        clinical_contract={"contract_id": "clinical_priority_contract"},
    )
    regulatory = _candidate(
        id="small-regulatory",
        lane="regulatory_traceability_gap",
        title="Small regulatory task",
        clinical_impact=7,
        severity=7,
        effort_h=2.0,
    )

    drive = build_development_autodrive([regulatory, clinical])
    transparency = drive["scoring_transparency"]

    assert transparency["version"] == "scoring_transparency_v1"
    assert transparency["selected_candidate"]["id"] == "critical-clinical"
    assert transparency["selected_candidate"]["clinical_priority"] > 0
    assert transparency["selected_candidate"]["execution_fit"] > 0
    assert transparency["clinical_candidates_open"] == 1
    assert transparency["critical_clinical_below_nonclinical"] is False


def test_phase_3a_development_autodrive_selects_one_actionable_candidate():
    blocked = _candidate(
        id="blocked",
        lane="critical_clinical_gap",
        title="Blocked unsafe candidate",
        clinical_impact=10,
        severity=10,
        evidence=[],
        tests_required=[],
    )
    actionable = _candidate(
        id="actionable",
        lane="data_integrity_gap",
        title="Map missing testosterone to Decision Today",
        clinical_impact=8,
        severity=8,
        effort_h=1.5,
        patient_scope={"affected_count": 4},
        contract_gaps=[{"contract_id": "m0crpc_confirmation_minimum"}],
    )

    drive = build_development_autodrive([blocked, actionable])

    assert drive["phase"] == "3A_development_autodrive"
    assert drive["summary"]["selected_id"] == "actionable"
    assert drive["summary"]["one_change_per_iteration"] is True
    assert drive["selection_guardrails"]["blocked_candidates_never_selected"] is True
    assert drive["selected_iteration"]["clinical_fact_writes_allowed"] is False
    assert drive["selected_iteration"]["auto_merge_allowed"] is False
    assert drive["selected_iteration"]["score_breakdown"]["decision_today_blocking"] > 0
    assert any(item["id"] == "blocked" for item in drive["deferred_queue"])


def test_phase_3b_shadow_pr_factory_builds_reviewable_package_without_git_mutation():
    candidate = _candidate(
        id="actionable",
        lane="data_integrity_gap",
        title="Map missing testosterone to Decision Today",
        clinical_impact=8,
        severity=8,
        effort_h=1.5,
        patient_scope={"affected_count": 4},
        surfaces=["decision-today", "clinical-field-router", "longitudinal-capture"],
        contract_gaps=[{"contract_id": "m0crpc_confirmation_minimum"}],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])

    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    package = shadow["package"]

    assert shadow["phase"] == "3B_shadow_pr_factory"
    assert shadow["summary"]["ready_for_human_review"] is True
    assert package["draft_pr"]["branch_name"].startswith("codex/autodrive-")
    assert package["draft_pr"]["create_branch_now"] is False
    assert package["draft_pr"]["create_pr_now"] is False
    assert package["draft_pr"]["auto_merge_allowed"] is False
    assert package["safety_report"]["source_clinical_facts_mutated"] is False
    assert package["safety_report"]["clinical_fact_writes_allowed"] is False
    assert "No clinical fact writes" in package["draft_pr"]["body"]
    assert any(row["path"] == "prostanet/domains/patient_tracking/clinical_decision_today_fusion_kernel.py" for row in package["implementation_plan"]["file_targets"])
    assert any("tests/test_autonomous_improvement_os.py" in row["cmd"] for row in package["validation_plan"]["test_commands"])


def test_phase_3c_safety_gate_runner_is_plan_only_and_blocks_unsafe_release():
    candidate = _candidate(
        id="actionable",
        lane="data_integrity_gap",
        title="Map missing testosterone to Decision Today",
        clinical_impact=8,
        severity=8,
        effort_h=1.5,
        patient_scope={"affected_count": 4},
        surfaces=["decision-today", "clinical-field-router", "longitudinal-capture"],
        contract_gaps=[{"contract_id": "m0crpc_confirmation_minimum"}],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)

    runner = build_safety_gate_runner(shadow_pr_factory=shadow)
    statuses = {row["gate_id"]: row["status"] for row in runner["gates"]}

    assert runner["phase"] == "3C_safety_gate_runner"
    assert runner["summary"]["release_gate"] == "ready_for_human_review"
    assert runner["summary"]["commands_executed"] is False
    assert runner["summary"]["git_mutated"] is False
    assert runner["summary"]["source_clinical_facts_mutated"] is False
    assert statuses["no_git_mutation"] == "passed"
    assert statuses["no_clinical_fact_mutation"] == "passed"
    assert statuses["anti_fallback_assertions"] == "passed"
    assert statuses["tests_declared"] == "passed"
    assert statuses["core_regression_declared"] == "passed"
    assert runner["required_test_commands"]
    assert runner["required_visual_routes"]


def test_phase_3d_shadow_execution_artifacts_record_controlled_evidence_without_mutation():
    candidate = _candidate(
        id="actionable",
        lane="data_integrity_gap",
        title="Map missing testosterone to Decision Today",
        clinical_impact=8,
        severity=8,
        effort_h=1.5,
        patient_scope={"affected_count": 4},
        surfaces=["decision-today", "clinical-field-router", "longitudinal-capture"],
        contract_gaps=[{"contract_id": "m0crpc_confirmation_minimum"}],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety = build_safety_gate_runner(shadow_pr_factory=shadow)
    command_results = [
        {
            "cmd": row["cmd"],
            "purpose": row.get("purpose", ""),
            "exit_code": 0,
            "duration_seconds": 0.1,
            "output_excerpt": "passed 534543534563453",
        }
        for row in safety["required_test_commands"]
    ]
    visual_results = [
        {"route": route, "viewport": "1440x696", "status": "passed", "console_errors": 0}
        for route in safety["required_visual_routes"]
    ]

    artifacts = build_shadow_execution_artifacts(
        safety_gate_runner=safety,
        command_results=command_results,
        visual_results=visual_results,
    )

    assert artifacts["phase"] == "3D_shadow_execution_artifacts"
    assert artifacts["summary"]["artifact_status"] == "verified_pending_human_review"
    assert artifacts["summary"]["commands_executed"] is True
    assert artifacts["summary"]["git_mutated"] is False
    assert artifacts["summary"]["source_clinical_facts_mutated"] is False
    assert artifacts["summary"]["auto_merge_allowed"] is False
    assert artifacts["summary"]["human_review_required"] is True
    assert artifacts["blocking_findings"] == []
    assert all(row["allowed"] is True for row in artifacts["command_results"])
    assert "***" in artifacts["command_results"][0]["output_excerpt"]


def test_phase_3e_human_review_gate_records_decision_without_git_or_clinical_mutation(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="actionable",
        lane="data_integrity_gap",
        title="Map missing testosterone to Decision Today",
        clinical_impact=8,
        severity=8,
        effort_h=1.5,
        patient_scope={"affected_count": 4},
        surfaces=["decision-today", "clinical-field-router", "longitudinal-capture"],
        contract_gaps=[{"contract_id": "m0crpc_confirmation_minimum"}],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety = build_safety_gate_runner(shadow_pr_factory=shadow)
    command_results = [
        {"cmd": row["cmd"], "exit_code": 0, "duration_seconds": 0.1, "output_excerpt": "passed"}
        for row in safety["required_test_commands"]
    ]
    visual_results = [{"route": route, "status": "passed"} for route in safety["required_visual_routes"]]
    artifacts = build_shadow_execution_artifacts(
        safety_gate_runner=safety,
        command_results=command_results,
        visual_results=visual_results,
        persist=True,
    )

    pending = build_human_review_decision_gate(
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    event = record_human_review_gate_decision(
        decision="approve_for_pr",
        reviewer="Dr. QA 123456789",
        note="Aprobado tras artifact 987654321",
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    approved = build_human_review_decision_gate(
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )

    assert pending["phase"] == "3E_human_review_decision_gate"
    assert pending["summary"]["decision_state"] == "pending_human_review"
    assert event["decision"] == "approve_for_pr"
    assert event["git_mutated"] is False
    assert event["source_clinical_facts_mutated"] is False
    assert "***" in event["reviewer"]
    assert "***" in event["note"]
    assert approved["summary"]["decision_state"] == "approved_for_pr_handoff"
    assert approved["summary"]["pr_handoff_allowed"] is True
    assert approved["summary"]["pull_request_created"] is False
    assert approved["summary"]["auto_merge_allowed"] is False
    assert approved["summary"]["source_clinical_facts_mutated"] is False


def test_phase_3f_draft_pr_handoff_requires_approval_and_does_not_mutate_git(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="handoff-ready",
        lane="critical_clinical_gap",
        title="Unify Decision Today handoff",
        clinical_impact=9,
        severity=9,
        effort_h=2.0,
        surfaces=["decision-today", "loop-monitor"],
        tests_required=["test_decision_today_contract", "test_loop_monitor"],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety = build_safety_gate_runner(shadow_pr_factory=shadow)
    command_results = [
        {"cmd": row["cmd"], "exit_code": 0, "duration_seconds": 0.1, "output_excerpt": "passed"}
        for row in safety["required_test_commands"]
    ]
    visual_results = [{"route": route, "status": "passed"} for route in safety["required_visual_routes"]]
    artifacts = build_shadow_execution_artifacts(
        safety_gate_runner=safety,
        command_results=command_results,
        visual_results=visual_results,
        persist=True,
    )
    pending_gate = build_human_review_decision_gate(
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    pending_handoff = build_draft_pr_handoff(
        human_review_decision_gate=pending_gate,
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )

    assert pending_handoff["phase"] == "3F_draft_pr_handoff"
    assert pending_handoff["summary"]["handoff_status"] == "blocked_until_human_approval"
    assert pending_handoff["summary"]["manual_handoff_ready"] is False
    assert pending_handoff["summary"]["branch_created"] is False
    assert pending_handoff["summary"]["pull_request_created"] is False
    assert pending_handoff["summary"]["git_mutated"] is False
    assert pending_handoff["summary"]["source_clinical_facts_mutated"] is False
    assert pending_handoff["blocking_findings"]

    record_human_review_gate_decision(
        decision="approve_for_pr",
        reviewer="Dr. Reviewer 123456789",
        note="Aprobado para handoff 987654321",
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    approved_gate = build_human_review_decision_gate(
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    approved_handoff = build_draft_pr_handoff(
        human_review_decision_gate=approved_gate,
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )

    assert approved_handoff["summary"]["handoff_status"] == "ready_for_manual_pr_creation"
    assert approved_handoff["summary"]["manual_handoff_ready"] is True
    assert approved_handoff["branch_plan"]["branch_name"].startswith("codex/autodrive-")
    assert approved_handoff["summary"]["branch_created"] is False
    assert approved_handoff["summary"]["pull_request_created"] is False
    assert approved_handoff["summary"]["auto_merge_allowed"] is False
    assert approved_handoff["summary"]["git_mutated"] is False
    assert approved_handoff["summary"]["source_clinical_facts_mutated"] is False
    assert any("gh pr create --draft" in row["cmd"] for row in approved_handoff["commands_to_run"])
    assert all(row["execute_now"] is False for row in approved_handoff["commands_to_run"])


def test_phase_3g_pr_review_monitor_tracks_pr_without_git_or_merge(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="pr-monitor",
        lane="safety_security_gap",
        title="Monitor PR safety gates",
        clinical_impact=8,
        severity=8,
        effort_h=1.0,
        surfaces=["loop-monitor", "github-actions"],
        tests_required=["test_pr_review_monitor"],
    )
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety = build_safety_gate_runner(shadow_pr_factory=shadow)
    artifacts = build_shadow_execution_artifacts(
        safety_gate_runner=safety,
        command_results=[
            {"cmd": row["cmd"], "exit_code": 0, "duration_seconds": 0.1, "output_excerpt": "passed"}
            for row in safety["required_test_commands"]
        ],
        visual_results=[{"route": route, "status": "passed"} for route in safety["required_visual_routes"]],
        persist=True,
    )
    pending_handoff = build_draft_pr_handoff(
        human_review_decision_gate=build_human_review_decision_gate(
            shadow_pr_factory=shadow,
            shadow_execution_artifacts=artifacts,
        ),
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    blocked_monitor = build_pr_review_monitor(
        draft_pr_handoff=pending_handoff,
        git_snapshot={"available": True, "branch_present": False, "current_branch": "main", "dirty_file_count": 0},
    )

    assert blocked_monitor["phase"] == "3G_pr_review_monitor"
    assert blocked_monitor["summary"]["monitor_status"] == "blocked_until_handoff_ready"
    assert blocked_monitor["summary"]["merge_performed"] is False
    assert blocked_monitor["summary"]["git_mutated"] is False
    assert blocked_monitor["summary"]["source_clinical_facts_mutated"] is False

    record_human_review_gate_decision(
        decision="approve_for_pr",
        reviewer="Reviewer 123456789",
        note="Ready for PR 987654321",
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    approved_handoff = build_draft_pr_handoff(
        human_review_decision_gate=build_human_review_decision_gate(
            shadow_pr_factory=shadow,
            shadow_execution_artifacts=artifacts,
        ),
        shadow_pr_factory=shadow,
        shadow_execution_artifacts=artifacts,
    )
    no_pr_monitor = build_pr_review_monitor(
        draft_pr_handoff=approved_handoff,
        git_snapshot={"available": True, "branch_present": False, "current_branch": "main", "dirty_file_count": 0},
    )

    assert no_pr_monitor["summary"]["monitor_status"] == "no_pr_yet"
    assert no_pr_monitor["summary"]["pull_request_detected"] is False
    assert no_pr_monitor["summary"]["pull_request_created"] is False

    event = record_pr_review_monitor_metadata(
        branch_name=approved_handoff["branch_plan"]["branch_name"],
        pr_url="https://github.com/example/Prostamed-V3/pull/7",
        pr_number=7,
        ci_status="passed",
        review_status="approved",
        reviewer="QA 123456789",
        note="CI passed 987654321",
    )
    validated_monitor = build_pr_review_monitor(
        draft_pr_handoff=approved_handoff,
        git_snapshot={"available": True, "branch_present": True, "current_branch": approved_handoff["branch_plan"]["branch_name"], "dirty_file_count": 0},
    )

    assert event["git_mutated"] is False
    assert "***" in event["reviewer"]
    assert validated_monitor["summary"]["monitor_status"] == "validated_pending_human_merge"
    assert validated_monitor["summary"]["pull_request_detected"] is True
    assert validated_monitor["summary"]["pull_request_created_by_monitor"] is False
    assert validated_monitor["summary"]["pull_request_created"] is False
    assert validated_monitor["summary"]["merge_performed"] is False
    assert validated_monitor["summary"]["auto_merge_allowed"] is False
    assert validated_monitor["summary"]["next_phase_suggested"] == "4A_agent_lane_registry"


def test_phase_4a_agent_lane_registry_is_shadow_only_and_contractual():
    candidate = _candidate(
        id="agent-routing",
        lane="safety_security_gap",
        agent_lane="security",
        title="Prevent PHI logs",
        clinical_impact=9,
        severity=9,
        tests_required=["test_no_phi_logs"],
    )
    registry = build_agent_lane_registry(
        gap_bundle={"candidates": [candidate]},
        pr_review_monitor={"summary": {"monitor_status": "validated_pending_human_merge"}},
    )

    assert registry["phase"] == "4A_agent_lane_registry"
    assert registry["summary"]["registry_status"] == "shadow_active"
    assert registry["summary"]["agent_count"] == 6
    assert registry["summary"]["mutating_agent_count"] == 0
    assert registry["summary"]["agent_code_execution_allowed"] is False
    assert registry["summary"]["production_mutation_allowed"] is False
    assert registry["summary"]["source_clinical_facts_mutated"] is False
    assert registry["summary"]["git_mutated"] is False
    assert registry["summary"]["auto_merge_allowed"] is False
    assert registry["summary"]["next_phase_suggested"] == "4B_agent_proposal_packets"
    security_lane = next(row for row in registry["lanes"] if row["agent_lane"] == "security")
    assert security_lane["candidate_count"] == 1
    assert security_lane["may_modify"] is False
    assert "rollback" in registry["proposal_packet_contract"]["required_fields"]
    assert "store_phi_in_logs_or_artifacts" in security_lane["forbidden_actions"]


def test_phase_4b_agent_proposal_packets_are_complete_shadow_packets():
    candidate = _candidate(
        id="packet-ready",
        lane="critical_clinical_gap",
        agent_lane="clinical_logic",
        title="Close Decision Today gap",
        description="Decision Today needs a clinical safety synthesis.",
        evidence=["Decision Today contract"],
        tests_required=["test_decision_today_packet"],
        rollback="Revert packet synthesis.",
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )

    assert packets["phase"] == "4B_agent_proposal_packets"
    assert packets["summary"]["packet_count"] == 6
    assert packets["summary"]["proposal_ready_count"] >= 1
    assert packets["summary"]["agent_code_execution_allowed"] is False
    assert packets["summary"]["source_clinical_facts_mutated"] is False
    assert packets["summary"]["git_mutated"] is False
    assert packets["summary"]["auto_merge_allowed"] is False
    assert packets["summary"]["next_phase_suggested"] == "4C_consensus_synthesizer"
    clinical_packet = packets["by_agent"]["clinical_logic"]
    assert clinical_packet["packet_status"] == "proposal_ready"
    assert clinical_packet["quality"]["complete"] is True
    assert "tests_required" in clinical_packet
    assert packets["quality_gate"]["no_production_mutation"] is True


def test_phase_4c_agent_consensus_synthesizer_selects_one_shadow_work_order():
    candidate = _candidate(
        id="consensus-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Close PHI logging gap",
        description="Security agent should prevent PHI artifacts.",
        evidence=["Security scan"],
        tests_required=["test_no_phi_logs"],
        rollback="Revert logging patch.",
        priority_score=81,
        severity=9,
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "consensus-ready"}},
    )

    assert consensus["phase"] == "4C_consensus_synthesizer"
    assert consensus["summary"]["consensus_status"] == "consensus_ready"
    assert consensus["summary"]["selected_candidate_id"] == "consensus-ready"
    assert consensus["summary"]["agreement_score"] > 0
    assert consensus["summary"]["source_clinical_facts_mutated"] is False
    assert consensus["summary"]["git_mutated"] is False
    assert consensus["summary"]["branch_created"] is False
    assert consensus["summary"]["pull_request_created"] is False
    assert consensus["summary"]["merge_performed"] is False
    assert consensus["summary"]["auto_merge_allowed"] is False
    assert consensus["summary"]["next_phase_suggested"] == "4D_implementation_brief"
    assert consensus["quality_gate"]["single_next_iteration_selected"] is True
    assert consensus["work_order_preview"]["available"] is True
    assert consensus["work_order_preview"]["clinical_fact_writes_allowed"] is False
    assert consensus["work_order_preview"]["git_mutation_allowed"] is False
    assert consensus["controls"]["requires_human_review"] is True
    assert any(row["vote"] == "support" for row in consensus["agent_positions"])


def test_phase_4d_implementation_brief_is_read_only_and_reviewable():
    candidate = _candidate(
        id="brief-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Close security header gap",
        description="Security agent should tighten a header contract.",
        evidence=["Security contract"],
        tests_required=["test_security_header_contract"],
        rollback="Revert the header contract patch.",
        priority_score=84,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "brief-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)

    assert brief["phase"] == "4D_implementation_brief"
    assert brief["summary"]["brief_status"] == "brief_ready"
    assert brief["summary"]["commands_executed"] is False
    assert brief["summary"]["source_clinical_facts_mutated"] is False
    assert brief["summary"]["git_mutated"] is False
    assert brief["summary"]["branch_created"] is False
    assert brief["summary"]["pull_request_created"] is False
    assert brief["summary"]["merge_performed"] is False
    assert brief["summary"]["auto_merge_allowed"] is False
    assert brief["summary"]["next_phase_suggested"] == "4E_shadow_patch_blueprint"
    assert brief["quality_gate"]["ready_for_shadow_patch_blueprint"] is True
    assert brief["controls"]["brief_is_read_model_only"] is True
    assert brief["controls"]["code_execution_allowed"] is False
    assert brief["controls"]["git_mutation_allowed"] is False
    assert brief["handoff_packet"]["human_review_required"] is True
    assert brief["handoff_packet"]["branch_suggestion"].startswith("codex/autodrive-")
    assert any(row["path"] == "prostanet/agentic/autonomous_improvement_os.py" for row in brief["file_scope"])
    assert any("pytest -q tests/test_autonomous_improvement_os.py" in row["command"] for row in brief["test_plan"])
    assert brief["rollback_plan"]["clinical_fact_rollback_required"] is False


def test_phase_4e_shadow_patch_blueprint_plans_diff_without_mutation():
    candidate = _candidate(
        id="blueprint-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Close security scan gap",
        description="Security agent should create a patch blueprint only.",
        evidence=["Security contract"],
        tests_required=["test_security_scan_contract"],
        rollback="Discard the planned security scan patch.",
        priority_score=86,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "blueprint-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)

    assert blueprint["phase"] == "4E_shadow_patch_blueprint"
    assert blueprint["summary"]["blueprint_status"] == "blueprint_ready"
    assert blueprint["summary"]["planned_file_count"] >= 1
    assert blueprint["summary"]["planned_hunk_count"] >= 1
    assert blueprint["summary"]["commands_executed"] is False
    assert blueprint["summary"]["files_modified"] is False
    assert blueprint["summary"]["source_clinical_facts_mutated"] is False
    assert blueprint["summary"]["git_mutated"] is False
    assert blueprint["summary"]["branch_created"] is False
    assert blueprint["summary"]["pull_request_created"] is False
    assert blueprint["summary"]["merge_performed"] is False
    assert blueprint["summary"]["auto_merge_allowed"] is False
    assert blueprint["summary"]["next_phase_suggested"] == "4F_human_patch_authorization"
    assert blueprint["quality_gate"]["ready_for_human_patch_authorization"] is True
    assert blueprint["controls"]["blueprint_is_read_model_only"] is True
    assert blueprint["controls"]["code_execution_allowed"] is False
    assert blueprint["controls"]["git_mutation_allowed"] is False
    assert blueprint["review_packet"]["human_review_required"] is True
    assert blueprint["review_packet"]["ready_for_human_authorization"] is True
    assert blueprint["rollback_blueprint"]["clinical_fact_rollback_required"] is False
    assert any(row["planned_hunks"] for row in blueprint["patch_blueprint"]["file_blueprints"])


def test_phase_4f_human_patch_authorization_records_decision_without_mutation(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="authorization-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Authorize controlled patch",
        description="Human reviewer may authorize the planned patch.",
        evidence=["Security contract"],
        tests_required=["test_patch_authorization_contract"],
        rollback="Discard authorized patch before application.",
        priority_score=88,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "authorization-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    event = record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)

    assert pending["phase"] == "4F_human_patch_authorization"
    assert pending["summary"]["authorization_state"] == "pending_human_authorization"
    assert pending["summary"]["patch_application_allowed"] is False
    assert event["decision"] == "authorize_patch"
    assert "***" in event["reviewer"]
    assert "***" in event["note"]
    assert event["commands_executed"] is False
    assert event["files_modified"] is False
    assert event["source_clinical_facts_mutated"] is False
    assert event["git_mutated"] is False
    assert event["auto_merge_allowed"] is False
    assert authorized["summary"]["authorization_state"] == "authorized_for_controlled_patch"
    assert authorized["summary"]["patch_application_allowed"] is True
    assert authorized["summary"]["commands_executed"] is False
    assert authorized["summary"]["files_modified"] is False
    assert authorized["summary"]["source_clinical_facts_mutated"] is False
    assert authorized["summary"]["git_mutated"] is False
    assert authorized["summary"]["branch_created"] is False
    assert authorized["summary"]["pull_request_created"] is False
    assert authorized["summary"]["merge_performed"] is False
    assert authorized["summary"]["auto_merge_allowed"] is False
    assert authorized["summary"]["next_phase_suggested"] == "4G_controlled_patch_application"
    assert authorized["quality_gate"]["ready_for_controlled_patch_application"] is True
    assert authorized["controls"]["authorization_does_not_apply_patch"] is True


def test_phase_4g_controlled_patch_application_requires_4f_and_prepares_phase_5_packet(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="controlled-application-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Prepare controlled patch application",
        description="Phase 4G should prepare the packet but never apply it automatically.",
        evidence=["Controlled application contract"],
        tests_required=["test_controlled_patch_application_contract"],
        rollback="Discard branch before Phase 5 PR handoff.",
        priority_score=91,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "controlled-application-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )

    assert blocked["phase"] == "4G_controlled_patch_application"
    assert blocked["summary"]["application_status"] == "blocked_until_authorization"
    assert blocked["summary"]["ready_for_phase_5"] is False
    assert "human_patch_authorization_missing" in blocked["blockers"]
    assert blocked["summary"]["commands_executed"] is False
    assert blocked["summary"]["files_modified"] is False
    assert blocked["summary"]["git_mutated"] is False

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize controlled patch 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )

    assert application["summary"]["application_status"] == "ready_for_phase_5_controlled_pr"
    assert application["summary"]["ready_for_phase_5"] is True
    assert application["summary"]["next_phase_suggested"] == "5A_controlled_pr_implementation"
    assert application["quality_gate"]["ready_for_phase_5_controlled_pr"] is True
    assert application["application_packet"]["branch_name"].startswith("codex/autodrive-")
    assert application["application_packet"]["files"]
    assert application["application_packet"]["tests"]
    assert application["application_packet"]["rollback"]
    assert all(step["automatic_execution_allowed"] is False for step in application["application_packet"]["execution_steps"])
    assert application["controls"]["automatic_execution_allowed"] is False
    assert application["controls"]["code_execution_allowed"] is False
    assert application["controls"]["git_mutation_allowed"] is False
    assert application["summary"]["commands_executed"] is False
    assert application["summary"]["files_modified"] is False
    assert application["summary"]["source_clinical_facts_mutated"] is False
    assert application["summary"]["branch_created"] is False
    assert application["summary"]["pull_request_created"] is False
    assert application["summary"]["merge_performed"] is False
    assert application["summary"]["auto_merge_allowed"] is False


def test_phase_5a_controlled_pr_implementation_prepares_manual_packet_without_mutation(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="controlled-pr-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Prepare controlled PR implementation",
        description="Phase 5A prepares branch/patch/PR commands but does not run them.",
        evidence=["Controlled PR implementation contract"],
        tests_required=["test_controlled_pr_implementation_contract"],
        rollback="Delete the controlled branch before PR publication.",
        priority_score=92,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "controlled-pr-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )
    blocked_5a = build_controlled_pr_implementation(controlled_patch_application=blocked_4g)

    assert blocked_5a["phase"] == "5A_controlled_pr_implementation"
    assert blocked_5a["summary"]["implementation_status"] == "blocked_until_4g_ready"
    assert blocked_5a["summary"]["ready_for_manual_execution"] is False
    assert "controlled_patch_application_not_ready" in blocked_5a["blockers"]

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize PR implementation 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )
    implementation_5a = build_controlled_pr_implementation(controlled_patch_application=application_4g)

    assert implementation_5a["summary"]["implementation_status"] == "ready_for_manual_branch_patch_and_draft_pr"
    assert implementation_5a["summary"]["ready_for_manual_execution"] is True
    assert implementation_5a["summary"]["next_phase_suggested"] == "5B_draft_pr_publication_gate"
    assert implementation_5a["quality_gate"]["ready_for_5b_draft_pr_publication_gate"] is True
    assert implementation_5a["implementation_packet"]["branch_name"].startswith("codex/autodrive-")
    assert implementation_5a["implementation_packet"]["manual_commands"]
    assert all(row["automatic_execution_allowed"] is False for row in implementation_5a["implementation_packet"]["manual_commands"])
    assert implementation_5a["controls"]["automatic_execution_allowed"] is False
    assert implementation_5a["controls"]["git_mutation_allowed"] is False
    assert implementation_5a["summary"]["commands_executed"] is False
    assert implementation_5a["summary"]["files_modified"] is False
    assert implementation_5a["summary"]["source_clinical_facts_mutated"] is False
    assert implementation_5a["summary"]["branch_created"] is False
    assert implementation_5a["summary"]["pull_request_created"] is False
    assert implementation_5a["summary"]["merge_performed"] is False
    assert implementation_5a["summary"]["auto_merge_allowed"] is False


def test_phase_5b_draft_pr_publication_gate_requires_5a_and_never_creates_pr(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="draft-pr-publication-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Prepare draft PR publication gate",
        description="Phase 5B should prepare a draft PR packet but never create it automatically.",
        evidence=["Draft PR publication contract"],
        tests_required=["test_draft_pr_publication_gate_contract"],
        rollback="Close/delete draft PR before merge if safety gate fails.",
        priority_score=93,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "draft-pr-publication-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )
    blocked_5a = build_controlled_pr_implementation(controlled_patch_application=blocked_4g)
    blocked_5b = build_draft_pr_publication_gate(controlled_pr_implementation=blocked_5a)

    assert blocked_5b["phase"] == "5B_draft_pr_publication_gate"
    assert blocked_5b["summary"]["publication_status"] == "blocked_until_5a_ready"
    assert blocked_5b["summary"]["ready_for_manual_publication"] is False
    assert "controlled_pr_implementation_not_ready" in blocked_5b["blockers"]

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize draft PR publication 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )
    implementation_5a = build_controlled_pr_implementation(controlled_patch_application=application_4g)
    publication_5b = build_draft_pr_publication_gate(controlled_pr_implementation=implementation_5a)

    assert publication_5b["summary"]["publication_status"] == "ready_for_manual_draft_pr_publication"
    assert publication_5b["summary"]["ready_for_manual_publication"] is True
    assert publication_5b["summary"]["publication_allowed"] is True
    assert publication_5b["summary"]["next_phase_suggested"] == "6A_required_safety_gate_contract"
    assert publication_5b["quality_gate"]["ready_for_6a_required_safety_gate_contract"] is True
    assert publication_5b["publication_packet"]["branch_name"].startswith("codex/autodrive-")
    assert publication_5b["publication_packet"]["draft_body_sections"]
    assert publication_5b["publication_packet"]["manual_publication_steps"]
    assert publication_5b["publication_packet"]["merge_policy"]["auto_merge_allowed"] is False
    assert all(row["automatic_execution_allowed"] is False for row in publication_5b["publication_packet"]["manual_publication_steps"])
    assert publication_5b["controls"]["automatic_publication_allowed"] is False
    assert publication_5b["controls"]["git_mutation_allowed"] is False
    assert publication_5b["summary"]["commands_executed"] is False
    assert publication_5b["summary"]["files_modified"] is False
    assert publication_5b["summary"]["source_clinical_facts_mutated"] is False
    assert publication_5b["summary"]["branch_created"] is False
    assert publication_5b["summary"]["pull_request_created"] is False
    assert publication_5b["summary"]["merge_performed"] is False
    assert publication_5b["summary"]["auto_merge_allowed"] is False


def test_phase_6a_required_safety_gate_contract_requires_5b_and_never_executes(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="required-safety-gate-ready",
        lane="safety_security_gap",
        agent_lane="security",
        title="Define required safety gate contract",
        description="Phase 6A should declare required gates but never run them automatically.",
        evidence=["Required safety gate contract"],
        tests_required=["test_required_safety_gate_contract"],
        rollback="Block draft PR publication if a required safety gate fails.",
        priority_score=94,
        severity=9,
        surfaces=["/loop-monitor"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "required-safety-gate-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )
    blocked_5a = build_controlled_pr_implementation(controlled_patch_application=blocked_4g)
    blocked_5b = build_draft_pr_publication_gate(controlled_pr_implementation=blocked_5a)
    blocked_6a = build_required_safety_gate_contract(draft_pr_publication_gate=blocked_5b)

    assert blocked_6a["phase"] == "6A_required_safety_gate_contract"
    assert blocked_6a["summary"]["safety_contract_status"] == "blocked_until_5b_ready"
    assert blocked_6a["summary"]["ready_for_safety_execution"] is False
    assert "draft_pr_publication_gate_not_ready" in blocked_6a["blockers"]

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize safety contract 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )
    implementation_5a = build_controlled_pr_implementation(controlled_patch_application=application_4g)
    publication_5b = build_draft_pr_publication_gate(controlled_pr_implementation=implementation_5a)
    safety_6a = build_required_safety_gate_contract(draft_pr_publication_gate=publication_5b)

    gate_ids = {gate["gate_id"] for gate in safety_6a["required_gates"]}

    assert safety_6a["summary"]["safety_contract_status"] == "ready_for_manual_safety_gate_execution"
    assert safety_6a["summary"]["ready_for_safety_execution"] is True
    assert safety_6a["summary"]["next_phase_suggested"] == "7A_evidence_refresh_shadow_loop"
    assert safety_6a["summary"]["gate_count"] >= 8
    assert {"decision_today_regression", "security_phi_artifact_scan", "anti_fallback_clinical_data"} <= gate_ids
    assert all(gate["automatic_execution_allowed"] is False for gate in safety_6a["required_gates"])
    assert safety_6a["controls"]["automatic_execution_allowed"] is False
    assert safety_6a["controls"]["git_mutation_allowed"] is False
    assert safety_6a["quality_gate"]["ready_for_7a_evidence_refresh_shadow_loop"] is True
    assert safety_6a["summary"]["commands_executed"] is False
    assert safety_6a["summary"]["files_modified"] is False
    assert safety_6a["summary"]["source_clinical_facts_mutated"] is False
    assert safety_6a["summary"]["branch_created"] is False
    assert safety_6a["summary"]["pull_request_created"] is False
    assert safety_6a["summary"]["merge_performed"] is False
    assert safety_6a["summary"]["auto_merge_allowed"] is False


def test_phase_7a_evidence_refresh_shadow_loop_requires_6a_and_never_changes_recommendations(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="evidence-refresh-shadow-ready",
        lane="evidence_gap",
        agent_lane="evidence",
        title="Activate evidence refresh shadow loop",
        description="Phase 7A should watch official evidence sources without mutating clinical logic.",
        evidence=["EAU prostate cancer", "FDA oncology approvals", "ClinicalTrials.gov"],
        tests_required=["test_evidence_refresh_shadow_loop_contract"],
        rollback="Disable evidence candidate display; no clinical logic was changed.",
        priority_score=92,
        severity=8,
        surfaces=["/loop-monitor", "decision-today", "tumor-board-os"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "evidence-refresh-shadow-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )
    blocked_5a = build_controlled_pr_implementation(controlled_patch_application=blocked_4g)
    blocked_5b = build_draft_pr_publication_gate(controlled_pr_implementation=blocked_5a)
    blocked_6a = build_required_safety_gate_contract(draft_pr_publication_gate=blocked_5b)
    blocked_7a = build_evidence_refresh_shadow_loop(required_safety_gate_contract=blocked_6a)

    assert blocked_7a["phase"] == "7A_evidence_refresh_shadow_loop"
    assert blocked_7a["summary"]["evidence_refresh_status"] == "blocked_until_6a_ready"
    assert blocked_7a["summary"]["ready_for_shadow_surveillance"] is False
    assert "required_safety_gate_contract_not_ready" in blocked_7a["blockers"]

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize evidence refresh shadow loop 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )
    implementation_5a = build_controlled_pr_implementation(controlled_patch_application=application_4g)
    publication_5b = build_draft_pr_publication_gate(controlled_pr_implementation=implementation_5a)
    safety_6a = build_required_safety_gate_contract(draft_pr_publication_gate=publication_5b)
    evidence_7a = build_evidence_refresh_shadow_loop(required_safety_gate_contract=safety_6a)

    source_ids = {source["source_id"] for source in evidence_7a["source_registry"]}

    assert evidence_7a["summary"]["evidence_refresh_status"] == "ready_for_shadow_evidence_surveillance"
    assert evidence_7a["summary"]["ready_for_shadow_surveillance"] is True
    assert evidence_7a["summary"]["next_phase_suggested"] == "8A_patient_twin_readiness_loop"
    assert evidence_7a["summary"]["source_count"] >= 5
    assert {"eau_prostate_cancer_guidelines", "fda_oncology_approvals", "clinicaltrials_pivotal_trials"} <= source_ids
    assert evidence_7a["quality_gate"]["ready_for_8a_patient_twin_readiness_loop"] is True
    assert all(row["required_human_review"] is True for row in evidence_7a["review_queue"])
    assert all(row["automatic_application_allowed"] is False for row in evidence_7a["review_queue"])
    assert evidence_7a["controls"]["automatic_evidence_application_allowed"] is False
    assert evidence_7a["controls"]["automatic_recommendation_update_allowed"] is False
    assert evidence_7a["summary"]["evidence_changes_applied"] is False
    assert evidence_7a["summary"]["recommendation_logic_mutated"] is False
    assert evidence_7a["summary"]["trial_logic_mutated"] is False
    assert evidence_7a["summary"]["gate_logic_mutated"] is False
    assert evidence_7a["summary"]["commands_executed"] is False
    assert evidence_7a["summary"]["files_modified"] is False
    assert evidence_7a["summary"]["source_clinical_facts_mutated"] is False
    assert evidence_7a["summary"]["git_mutated"] is False
    assert evidence_7a["summary"]["branch_created"] is False
    assert evidence_7a["summary"]["pull_request_created"] is False
    assert evidence_7a["summary"]["merge_performed"] is False
    assert evidence_7a["summary"]["auto_merge_allowed"] is False


def test_phase_8a_patient_twin_readiness_loop_requires_7a_and_never_releases_predictions(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    candidate = _candidate(
        id="patient-twin-readiness-ready",
        lane="data_integrity_gap",
        agent_lane="data_contract",
        title="Activate Patient Twin readiness loop",
        description="Phase 8A should detect values, PRO, trajectory and redecision gaps without releasing predictions.",
        evidence=["Patient Twin preference and PRO minimum", "FDA PFDD", "NCI PRO-CTCAE"],
        tests_required=["test_phase_8a_patient_twin_readiness_loop_requires_7a"],
        rollback="Remove Patient Twin readiness panel; no clinical facts or predictions were changed.",
        priority_score=93,
        severity=9,
        surfaces=["/loop-monitor", "longitudinal-capture", "decision-today"],
    )
    gaps = {"candidates": [candidate]}
    registry = build_agent_lane_registry(gap_bundle=gaps)
    proposals = build_proposals([candidate])
    packets = build_agent_proposal_packets(
        agent_lane_registry=registry,
        proposals=proposals,
        gap_bundle=gaps,
    )
    consensus = build_agent_consensus_synthesizer(
        agent_proposal_packets=packets,
        development_autodrive={"summary": {"selected_id": "patient-twin-readiness-ready"}},
    )
    brief = build_agent_implementation_brief(agent_consensus_synthesizer=consensus)
    blueprint = build_shadow_patch_blueprint(implementation_brief=brief)
    pending_auth = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    blocked_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=pending_auth,
    )
    blocked_5a = build_controlled_pr_implementation(controlled_patch_application=blocked_4g)
    blocked_5b = build_draft_pr_publication_gate(controlled_pr_implementation=blocked_5a)
    blocked_6a = build_required_safety_gate_contract(draft_pr_publication_gate=blocked_5b)
    blocked_7a = build_evidence_refresh_shadow_loop(required_safety_gate_contract=blocked_6a)
    blocked_8a = build_patient_twin_readiness_loop(
        evidence_refresh_shadow_loop=blocked_7a,
        gap_bundle={
            "context": {
                "patient_scan": {
                    "evaluated": 2,
                    "missing_fields_top": [("patient_values", 2), ("baseline_pro", 1)],
                    "state_counts": {"localized_initial": 2},
                    "sample_ref_hints": ["PM***"],
                },
                "patient_twin_available": False,
            }
        },
    )

    assert blocked_8a["phase"] == "8A_patient_twin_readiness_loop"
    assert blocked_8a["summary"]["patient_twin_readiness_status"] == "blocked_until_7a_ready"
    assert blocked_8a["summary"]["ready_for_shadow_scan"] is False
    assert "evidence_refresh_shadow_loop_not_ready" in blocked_8a["blockers"]

    record_human_patch_authorization_decision(
        decision="authorize_patch",
        reviewer="QA 123456789",
        note="authorize patient twin readiness loop 987654321",
        shadow_patch_blueprint=blueprint,
    )
    authorized = build_human_patch_authorization(shadow_patch_blueprint=blueprint)
    application_4g = build_controlled_patch_application(
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorized,
    )
    implementation_5a = build_controlled_pr_implementation(controlled_patch_application=application_4g)
    publication_5b = build_draft_pr_publication_gate(controlled_pr_implementation=implementation_5a)
    safety_6a = build_required_safety_gate_contract(draft_pr_publication_gate=publication_5b)
    evidence_7a = build_evidence_refresh_shadow_loop(required_safety_gate_contract=safety_6a)
    ready_8a = build_patient_twin_readiness_loop(
        evidence_refresh_shadow_loop=evidence_7a,
        gap_bundle={
            "context": {
                "patient_scan": {
                    "scanned": 3,
                    "evaluated": 3,
                    "missing_fields_top": [
                        ("patient_values", 3),
                        ("baseline_pro", 2),
                        ("psa_series", 1),
                    ],
                    "state_counts": {"localized_initial": 2, "recurrence_bcr": 1},
                    "decision_state_counts": {"requires_data": 3},
                    "sample_ref_hints": ["PM***"],
                    "errors": [],
                },
                "patient_twin_available": False,
            }
        },
    )

    dimension_ids = {row["dimension_id"] for row in ready_8a["readiness_dimensions"]}
    capture_fields = {row["field"] for row in ready_8a["capture_plan"]}

    assert ready_8a["summary"]["patient_twin_readiness_status"] == "ready_for_patient_twin_readiness_shadow_scan"
    assert ready_8a["summary"]["ready_for_shadow_scan"] is True
    assert ready_8a["summary"]["next_phase_suggested"] == "9A_ai_readiness_dataset_loop"
    assert ready_8a["summary"]["dimension_count"] >= 6
    assert {"patient_values", "baseline_pro", "longitudinal_trajectory", "redecision_threshold"} <= dimension_ids
    assert {"patient_values", "baseline_pro"} <= capture_fields
    assert ready_8a["contract"]["forbidden_outputs"] == [
        "treatment_prediction",
        "survival_prediction",
        "recommendation_override",
        "autonomous_model_training",
    ]
    assert ready_8a["controls"]["automatic_simulation_allowed"] is False
    assert ready_8a["controls"]["model_training_allowed"] is False
    assert ready_8a["controls"]["prediction_release_allowed"] is False
    assert ready_8a["controls"]["clinical_fact_writes_allowed"] is False
    assert ready_8a["quality_gate"]["ready_for_9a_ai_readiness_dataset_loop"] is True
    assert ready_8a["summary"]["simulation_release_allowed"] is False
    assert ready_8a["summary"]["patient_twin_models_trained"] is False
    assert ready_8a["summary"]["patient_twin_predictions_released"] is False
    assert ready_8a["summary"]["commands_executed"] is False
    assert ready_8a["summary"]["files_modified"] is False
    assert ready_8a["summary"]["source_clinical_facts_mutated"] is False
    assert ready_8a["summary"]["git_mutated"] is False
    assert ready_8a["summary"]["branch_created"] is False
    assert ready_8a["summary"]["pull_request_created"] is False
    assert ready_8a["summary"]["merge_performed"] is False
    assert ready_8a["summary"]["auto_merge_allowed"] is False


def test_phase_9a_ai_readiness_dataset_loop_requires_8a_and_never_trains_or_exports(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    blocked_8a = build_patient_twin_readiness_loop(
        evidence_refresh_shadow_loop={
            "summary": {"ready_for_shadow_surveillance": False},
        },
        gap_bundle={
            "context": {
                "patient_scan": {"evaluated": 1, "missing_fields_top": [("learning_consent", 1)]},
                "patient_twin_available": False,
            }
        },
    )
    blocked_9a = build_ai_readiness_dataset_loop(
        patient_twin_readiness_loop=blocked_8a,
        gap_bundle={
            "context": {
                "patient_scan": {
                    "evaluated": 1,
                    "missing_fields_top": [("learning_consent", 1)],
                    "state_counts": {"localized_initial": 1},
                }
            }
        },
    )

    assert blocked_9a["phase"] == "9A_ai_readiness_dataset_loop"
    assert blocked_9a["summary"]["ai_readiness_status"] == "blocked_until_8a_ready"
    assert blocked_9a["summary"]["ready_for_shadow_audit"] is False
    assert "patient_twin_readiness_loop_not_ready" in blocked_9a["blockers"]

    ready_8a = {
        "summary": {
            "ready_for_shadow_scan": True,
            "patient_twin_readiness_status": "ready_for_patient_twin_readiness_shadow_scan",
        },
        "patient_scope": {
            "scanned": 4,
            "evaluated": 4,
            "state_counts": {"localized_initial": 2, "m1_crpc": 2},
            "missing_fields_top": [("learning_consent", 4), ("outcome", 3), ("provenance", 2)],
        },
    }
    ready_9a = build_ai_readiness_dataset_loop(
        patient_twin_readiness_loop=ready_8a,
        gap_bundle={
            "context": {
                "patient_scan": {
                    "scanned": 4,
                    "evaluated": 4,
                    "state_counts": {"localized_initial": 2, "m1_crpc": 2},
                    "decision_state_counts": {"requires_data": 4},
                    "missing_fields_top": [
                        ("learning_consent", 4),
                        ("outcome", 3),
                        ("provenance", 2),
                        ("feature_timestamp", 1),
                    ],
                    "sample_ref_hints": ["PM***"],
                    "errors": [],
                }
            }
        },
    )

    gate_ids = {gate["gate_id"] for gate in ready_9a["dataset_gates"]}

    assert ready_9a["summary"]["ai_readiness_status"] == "ready_for_ai_readiness_shadow_audit"
    assert ready_9a["summary"]["ready_for_shadow_audit"] is True
    assert ready_9a["summary"]["next_phase_suggested"] == "10A_cortana_loop_interface"
    assert ready_9a["summary"]["dataset_gate_count"] >= 7
    assert {
        "consent_governance",
        "provenance_traceability",
        "outcome_maturity",
        "missingness_profile",
        "leakage_prevention",
        "selection_bias_review",
    } <= gate_ids
    assert ready_9a["model_readiness_report"]["overall_status"] == "not_trainable_shadow_only"
    assert ready_9a["read_only_dataset_manifest"]["dataset_name"] == "model_readiness_dataset_v1"
    assert ready_9a["contract"]["forbidden_outputs"] == [
        "model_training",
        "treatment_prediction",
        "survival_prediction",
        "recommendation_override",
        "automatic_dataset_export",
    ]
    assert ready_9a["controls"]["dataset_export_allowed"] is False
    assert ready_9a["controls"]["deidentified_dataset_write_allowed"] is False
    assert ready_9a["controls"]["model_training_allowed"] is False
    assert ready_9a["controls"]["prediction_release_allowed"] is False
    assert ready_9a["controls"]["clinical_fact_writes_allowed"] is False
    assert ready_9a["quality_gate"]["ready_for_10a_cortana_loop_interface"] is True
    assert ready_9a["summary"]["dataset_export_written"] is False
    assert ready_9a["summary"]["deidentified_dataset_written"] is False
    assert ready_9a["summary"]["model_training_executed"] is False
    assert ready_9a["summary"]["models_trained"] is False
    assert ready_9a["summary"]["predictions_released"] is False
    assert ready_9a["summary"]["recommendation_logic_mutated"] is False
    assert ready_9a["summary"]["commands_executed"] is False
    assert ready_9a["summary"]["files_modified"] is False
    assert ready_9a["summary"]["source_clinical_facts_mutated"] is False
    assert ready_9a["summary"]["git_mutated"] is False
    assert ready_9a["summary"]["branch_created"] is False
    assert ready_9a["summary"]["pull_request_created"] is False
    assert ready_9a["summary"]["merge_performed"] is False
    assert ready_9a["summary"]["auto_merge_allowed"] is False


def test_phase_10a_cortana_loop_interface_requires_9a_and_is_consultative_only(monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    blocked_9a = build_ai_readiness_dataset_loop(
        patient_twin_readiness_loop={"summary": {"ready_for_shadow_scan": False}},
        gap_bundle={"context": {"patient_scan": {"evaluated": 1}}},
    )
    blocked_10a = build_cortana_loop_interface(
        ai_readiness_dataset_loop=blocked_9a,
        mission_control={"summary": {"clinical_goal_pct": 10, "pipeline_maturity_pct": 90}},
        development_autodrive={"summary": {}},
        gap_bundle={"candidates": [], "context": {}},
        query="que falta para alcanzar el objetivo final",
    )

    assert blocked_10a["phase"] == "10A_cortana_loop_interface"
    assert blocked_10a["summary"]["cortana_loop_status"] == "blocked_until_9a_ready"
    assert blocked_10a["summary"]["ready_for_loop_queries"] is False
    assert "ai_readiness_dataset_loop_not_ready" in blocked_10a["blockers"]

    active_gap_10a = build_cortana_loop_interface(
        ai_readiness_dataset_loop=blocked_9a,
        mission_control={"summary": {"clinical_goal_pct": 66, "pipeline_maturity_pct": 100.0}},
        development_autodrive={"summary": {}},
        gap_bundle={"candidates": [], "context": {}},
        query="que brecha clinica bloquea mas decisiones",
    )

    assert active_gap_10a["summary"]["cortana_loop_status"] == "ready_for_consultative_loop_interface"
    assert active_gap_10a["summary"]["ai_readiness_has_active_gaps"] is True
    assert active_gap_10a["quality_gate"]["technical_roadmap_complete"] is True
    assert active_gap_10a["quality_gate"]["roadmap_cycle_complete"] is True
    assert active_gap_10a["summary"]["code_mutation_allowed"] is False

    ready_9a = {
        "summary": {
            "ready_for_shadow_audit": True,
            "ai_readiness_status": "ready_for_ai_readiness_shadow_audit",
            "model_readiness_score": 25,
            "dominant_dataset_blocker": "consent_governance",
        }
    }
    candidate = _candidate(
        id="cortana-loop-interface-ready",
        lane="ui_workflow_gap",
        title="Expose Cortana autonomous loop interface",
        risk_avoided="Avoids opaque loop status and unsafe autonomous execution.",
        evidence=["Autonomous improvement loop contract"],
        tests_required=["test_phase_10a_cortana_loop_interface_requires_9a"],
        surfaces=["/loop-monitor", "voice-os"],
    )
    ready_10a = build_cortana_loop_interface(
        ai_readiness_dataset_loop=ready_9a,
        mission_control={
            "summary": {
                "mode": "shadow",
                "clinical_goal_pct": 65.56,
                "pipeline_maturity_pct": 95.65,
                "top_gap_title": "Close Patient Twin values gap",
            },
            "safety": {"auto_merge_enabled": False},
        },
        development_autodrive={
            "summary": {
                "selected_improvement": candidate,
                "selected_id": candidate["id"],
            }
        },
        gap_bundle={"candidates": [candidate], "context": {}},
        patient_twin_readiness_loop={
            "summary": {
                "patient_twin_readiness_status": "ready_for_patient_twin_readiness_shadow_scan",
                "dominant_missing_dimension": "patient_values",
            }
        },
        evidence_refresh_shadow_loop={
            "summary": {"evidence_refresh_status": "ready_for_shadow_evidence_surveillance"}
        },
        query="que evidencia respalda este cambio",
    )

    command_ids = {row["command_id"] for row in ready_10a["command_routes"]}
    response_keys = {row["response_key"] for row in ready_10a["response_cards"]}

    assert ready_10a["summary"]["cortana_loop_status"] == "ready_for_consultative_loop_interface"
    assert ready_10a["summary"]["ready_for_loop_queries"] is True
    assert ready_10a["summary"]["next_phase_suggested"] == "continuous_shadow_operation"
    assert ready_10a["summary"]["supported_command_count"] >= 7
    assert {"final_goal_gap", "dominant_clinical_gap", "ai_readiness_status", "patient_twin_status"} <= command_ids
    assert {"mission_gap_summary", "evidence_support", "ai_readiness_status"} <= response_keys
    assert ready_10a["resolved_response"]["matched_command_id"] == "evidence_support"
    assert ready_10a["resolved_response"]["write_allowed"] is False
    assert ready_10a["interface_contract"]["forbidden_outputs"] == [
        "clinical_fact_write",
        "code_mutation",
        "git_branch_creation",
        "pull_request_creation",
        "merge",
        "model_training",
        "dataset_export",
        "recommendation_override",
    ]
    assert ready_10a["controls"]["voice_write_allowed"] is False
    assert ready_10a["controls"]["clinical_fact_writes_allowed"] is False
    assert ready_10a["controls"]["code_mutation_allowed"] is False
    assert ready_10a["controls"]["model_training_allowed"] is False
    assert ready_10a["controls"]["prediction_release_allowed"] is False
    assert ready_10a["quality_gate"]["roadmap_cycle_complete"] is True
    assert ready_10a["summary"]["commands_executed"] is False
    assert ready_10a["summary"]["files_modified"] is False
    assert ready_10a["summary"]["source_clinical_facts_mutated"] is False
    assert ready_10a["summary"]["git_mutated"] is False
    assert ready_10a["summary"]["branch_created"] is False
    assert ready_10a["summary"]["pull_request_created"] is False
    assert ready_10a["summary"]["merge_performed"] is False
    assert ready_10a["summary"]["auto_merge_allowed"] is False


def test_continuous_shadow_operation_packages_one_gap_and_returns_to_human_authorization():
    candidate = validate_candidate(_candidate(
        id="continuous-shadow-gap",
        lane="critical_clinical_gap",
        title="Unify Decision Today blocker",
        description="Close one canonical Decision Today routing gap.",
        risk_avoided="Avoids conflicting clinical actionability.",
        evidence=["Decision Today contract"],
        tests_required=["test_decision_today_fusion_kernel"],
        surfaces=["decision-today", "loop-monitor"],
    ))
    development = build_development_autodrive([candidate])
    proposals = build_proposals([candidate])
    shadow = build_shadow_pr_factory(development_autodrive=development, proposals=proposals)
    safety = {
        "summary": {"release_gate": "ready_for_human_review", "gate_count": 3, "passed": 3, "blocked": 0},
        "required_visual_routes": ["/patient_profile/<nss>?v=2", "/loop-monitor"],
        "required_test_commands": [{"cmd": "pytest -q tests/test_autonomous_improvement_os.py"}],
        "gates": [],
        "anti_fallback": {"clinical_data_fabrication_blocked": True},
    }
    blueprint = {
        "quality_gate": {"ready_for_human_patch_authorization": True},
        "patch_blueprint": {"minimal_change": "single read-model contract"},
        "validation_blueprint": {"tests": [], "visual_validation": []},
        "rollback_blueprint": {"rollback_plan": "Reject the shadow cycle."},
    }
    authorization = {"summary": {"authorization_state": "pending_human_authorization"}}
    ready_10a = {
        "quality_gate": {"roadmap_cycle_complete": True},
        "summary": {"cortana_loop_status": "ready_for_consultative_loop_interface"},
    }

    continuous = build_continuous_shadow_operation(
        cortana_loop_interface=ready_10a,
        mission_control={"summary": {"mode": "shadow"}},
        development_autodrive=development,
        gap_bundle={"candidates": [candidate], "context": {}},
        proposals=proposals,
        shadow_pr_factory=shadow,
        safety_gate_runner=safety,
        shadow_patch_blueprint=blueprint,
        human_patch_authorization=authorization,
        required_safety_gate_contract={"summary": {"safety_contract_status": "ready_for_required_gates"}},
    )

    assert continuous["phase"] == "continuous_shadow_operation"
    assert continuous["summary"]["continuous_status"] == "awaiting_human_authorization"
    assert continuous["summary"]["selected_gap_id"] == candidate["id"]
    assert continuous["summary"]["one_change_per_cycle"] is True
    assert continuous["summary"]["ready_for_human_authorization"] is True
    assert continuous["cycle_packet"]["selected_gap_id"] == candidate["id"]
    assert continuous["visual_validation_plan"]["routes"] == ["/patient_profile/<nss>?v=2", "/loop-monitor"]
    assert continuous["human_authorization_request"]["endpoint"] == "/api/autonomous-improvement/human-patch-authorization/decision"
    assert continuous["controls"]["clinical_fact_writes_allowed"] is False
    assert continuous["summary"]["commands_executed"] is False
    assert continuous["summary"]["files_modified"] is False
    assert continuous["summary"]["source_clinical_facts_mutated"] is False
    assert continuous["summary"]["git_mutated"] is False
    assert continuous["summary"]["branch_created"] is False
    assert continuous["summary"]["pull_request_created"] is False
    assert continuous["summary"]["merge_performed"] is False
    assert continuous["summary"]["auto_merge_allowed"] is False


def test_mission_control_exposes_dynamic_autonomous_loop_maturity_metric():
    mission = build_mission_control(gap_bundle={"candidates": [], "context": {}})
    metrics = {row["key"]: row for row in mission["metrics"]}

    assert "autonomous_loop_maturity" in metrics
    assert metrics["autonomous_loop_maturity"]["value"] > 0
    assert mission["summary"]["pipeline_maturity_pct"] > 0
    assert mission["summary"]["pipeline_total_count"] >= mission["summary"]["pipeline_completed_count"]
    if mission["summary"]["pipeline_total_count"] == mission["summary"]["pipeline_completed_count"]:
        assert mission["summary"]["pipeline_maturity_pct"] == 100.0
    assert mission["progress_diagnostics"]["new_dynamic_metric"] == "autonomous_loop_maturity"
    assert mission["progress_diagnostics"]["clinical_goal_is_not_phase_completion"] is True


def test_candidate_without_evidence_or_tests_is_blocked():
    bad = validate_candidate(_candidate(evidence=[], tests_required=[]))

    assert bad["status"] == "blocked"
    assert "missing_evidence" in bad["blockers"]
    assert "missing_tests" in bad["blockers"]


def test_candidate_that_fabricates_biomarkers_or_treatment_is_rejected():
    bad = validate_candidate(_candidate(description="Inventar PSA y tratamiento por fallback demo."))

    assert bad["status"] == "blocked"
    assert "fabricates_clinical_data" in bad["blockers"]


def test_stuck_gap_escalates_to_human_review_required():
    stuck = escalate_stuck_candidate(_candidate(status="proposal_ready"), consecutive_count=3)

    assert stuck["status"] == "human_review_required"
    assert "stuck_gap_repeated" in stuck["blockers"]


def test_phase_2a_clinical_gap_contract_registry_has_route_persistence_and_tests():
    registry = build_clinical_gap_contract_registry()
    ids = {row["contract_id"] for row in registry}

    assert "m0crpc_confirmation_minimum" in ids
    assert "bcr_salvage_window_minimum" in ids
    assert "patient_twin_preference_pro_minimum" in ids
    for row in registry:
        assert row["required_fields"]
        assert row["capture_surface"]
        assert row["persistence"]
        assert row["consumer"]
        assert row["tests"]


def test_phase_2a_maps_missing_fields_to_contractual_gap_rows():
    rows = derive_contractual_gap_rows({
        "state_counts": {"m0_crpc": 2, "recurrence_bcr": 1},
        "missing_fields_top": [("testosterone", 2), ("psadt", 3), ("real_treatment_line", 1)],
    })
    by_id = {row["contract_id"]: row for row in rows}

    assert "m0crpc_confirmation_minimum" in by_id
    assert "bcr_salvage_window_minimum" in by_id
    assert by_id["m0crpc_confirmation_minimum"]["capture_surface"]
    assert any(item["field"] == "testosterone" for item in by_id["m0crpc_confirmation_minimum"]["matched_missing_fields"])


def test_application_telemetry_separates_closed_software_from_patient_capture_gap():
    patient_summary = {
        "state_counts": {"localized_initial": 2, "recurrence_bcr": 1, "diagnostic_workup": 2},
        "missing_fields_top": [
            ("psa_density", 2),
            ("mri_pirads_score", 2),
            ("biopsy_status", 2),
            ("family_history", 2),
            ("germline_risk", 2),
            ("psa_doubling_time_months", 1),
            ("salvage_context_marker", 1),
            ("psma_pet_status", 1),
            ("patient_values", 3),
            ("baseline_pro", 2),
            ("toxicity_tolerance", 2),
            ("localized_patient_values", 2),
            ("bowel_function_baseline", 2),
        ],
    }
    rows = derive_contractual_gap_rows(patient_summary)
    telemetry = build_application_telemetry(patient_summary=patient_summary, contractual_gap_rows=rows)
    by_id = {row["contract_id"]: row for row in rows}
    implementations = {row["contract_id"]: row for row in telemetry["implementations"]}

    assert by_id["patient_twin_preference_pro_minimum"]["software_gap_closed"] is True
    assert by_id["patient_twin_preference_pro_minimum"]["patient_data_gap_open"] is True
    assert by_id["patient_twin_preference_pro_minimum"]["cycle_telemetry_status"] == "software_closed_patient_capture_monitoring"
    assert by_id["diagnostic_truth_minimum"]["software_gap_closed"] is True
    assert by_id["diagnostic_truth_minimum"]["patient_data_gap_open"] is True
    assert implementations["diagnostic_truth_minimum"]["implementation_status"] == "implemented_validated"
    assert by_id["bcr_salvage_window_minimum"]["software_gap_closed"] is True
    assert by_id["bcr_salvage_window_minimum"]["patient_data_gap_open"] is True
    assert implementations["bcr_salvage_window_minimum"]["implementation_status"] == "implemented_validated"
    assert by_id["localized_function_preference_minimum"]["software_gap_closed"] is True
    assert implementations["localized_function_preference_minimum"]["implementation_status"] == "implemented_validated"
    assert telemetry["summary"]["software_gap_closed_count"] >= 4
    assert telemetry["summary"]["patient_capture_monitoring_count"] >= 4


def test_decision_today_candidate_title_names_dominant_missing_field():
    title = _decision_today_gap_title(["repeat_psa_value"])

    assert title == "Resolve repeat PSA confirmation blocking canonical Decision Today"


def test_validated_application_telemetry_candidates_are_not_reselected_for_autodrive():
    validated = validate_candidate(_candidate(
        id="closed-application-contract",
        status="validated",
        title="Applied contract telemetry",
        evidence=["Application telemetry"],
        tests_required=["test_application_telemetry_separates_closed_software_from_patient_capture_gap"],
    ))
    development = build_development_autodrive([validated])

    assert development["summary"]["actionable_count"] == 0
    assert development["summary"]["selected_id"] == ""
    assert development["summary"]["selected_reason"] == "No actionable improvement candidate is currently available."


def test_phase_2b_contradiction_rule_registry_has_sources_risk_and_tests():
    registry = build_contradiction_rule_registry()
    ids = {row["rule_id"] for row in registry}

    assert "readiness_tumor_board_release_mismatch" in ids
    assert "bcr_cross_state_crpc_activation" in ids
    assert "m1crpc_sequence_without_real_line" in ids
    for row in registry:
        assert row["sources"]
        assert row["risk_avoided"]
        assert row["tests"]


def test_contradiction_readiness_blocks_tumor_board_release():
    rows = derive_contradiction_rows({
        "patient_ref": "PM-123456",
        "state": "m0_crpc",
        "decision_today": {
            "decision_state": "requires_data",
            "unified_missing_fields": [{"field": "testosterone", "capture_surface": "longitudinal"}],
        },
        "clinical_readiness_tower": {
            "summary": {"status": "requires_data", "dominant_blocker": "Falta testosterona"},
            "capture_plan": {"missing_fields": [{"field": "testosterone", "capture_surface": "longitudinal"}]},
        },
        "tumor_board_os": {
            "options": [{"key": "arpi", "label": "ARPI", "status": "releaseable"}],
        },
    })
    ids = {row["rule_id"] for row in rows}

    assert "readiness_tumor_board_release_mismatch" in ids


def test_contradiction_bcr_excludes_crpc_parp_rlt():
    rows = derive_contradiction_rows({
        "patient_ref": "PM-999999",
        "state": "recurrence_bcr",
        "decision_today": {"decision_state": "releaseable", "decision_today": {"title": "Salvage"}},
        "tumor_board_os": {
            "options": [{"key": "parp", "label": "PARP olaparib", "status": "releaseable"}],
        },
    })
    ids = {row["rule_id"] for row in rows}

    assert "bcr_cross_state_crpc_activation" in ids


def test_contradiction_memory_redecision_dominates_decision_today():
    rows = derive_contradiction_rows({
        "patient_ref": "PM-777777",
        "state": "localized_initial",
        "decision_today": {"decision_state": "releaseable", "decision_today": {"title": "Vigilancia activa"}},
        "clinical_autodrive": {"summary": {"dominant_lane": "ready_to_decide"}},
        "clinical_memory_os": {
            "summary": {"requires_redecision": True, "outcome_status": "off_track"},
        },
    })
    ids = {row["rule_id"] for row in rows}

    assert "memory_redecision_not_reflected" in ids


def test_contradiction_m1crpc_sequence_requires_real_line():
    rows = derive_contradiction_rows({
        "patient_ref": "PM-888888",
        "state": "m1_crpc",
        "patient": {"treatment_lines": []},
        "decision_today": {"decision_state": "releaseable", "decision_today": {"title": "Secuencia mCRPC"}},
        "tumor_board_os": {
            "options": [{"key": "psma_rlt_sequence", "label": "PSMA-RLT sequencing", "status": "releaseable"}],
        },
    })
    ids = {row["rule_id"] for row in rows}

    assert "m1crpc_sequence_without_real_line" in ids


def test_contradiction_missing_field_has_capture_route():
    rows = derive_contradiction_rows({
        "patient_ref": "PM-666666",
        "state": "localized_initial",
        "decision_today": {
            "decision_state": "requires_data",
            "unified_missing_fields": [{"field": "bowel_function_baseline"}],
        },
    })
    ids = {row["rule_id"] for row in rows}

    assert "missing_field_without_capture_route" in ids


def test_autonomous_improvement_api_endpoints_and_reviews(app_client, monkeypatch, tmp_path):
    import prostanet.agentic.autonomous_improvement_os as aio

    monkeypatch.setattr(aio, "PERSISTENCE_DIR", tmp_path)
    monkeypatch.setattr(aio, "REVIEW_LOG", tmp_path / "reviews.jsonl")
    client, _db_path = app_client

    mission = client.get("/api/autonomous-improvement/mission-control")
    gaps = client.get("/api/autonomous-improvement/gaps?patient_limit=1")
    application_telemetry = client.get("/api/autonomous-improvement/application-telemetry?patient_limit=1")
    proposals = client.get("/api/autonomous-improvement/proposals?patient_limit=1")
    shadow_pr = client.get("/api/autonomous-improvement/shadow-pr?patient_limit=1")
    safety_gates = client.get("/api/autonomous-improvement/safety-gates?patient_limit=1")
    shadow_execution = client.get("/api/autonomous-improvement/shadow-execution?patient_limit=1")
    human_review_gate = client.get("/api/autonomous-improvement/human-review-gate?patient_limit=1")
    draft_handoff = client.get("/api/autonomous-improvement/draft-pr-handoff?patient_limit=1")
    pr_monitor = client.get("/api/autonomous-improvement/pr-review-monitor?patient_limit=1")
    agent_registry = client.get("/api/autonomous-improvement/agent-lane-registry?patient_limit=1")
    agent_packets = client.get("/api/autonomous-improvement/agent-proposal-packets?patient_limit=1")
    agent_consensus = client.get("/api/autonomous-improvement/agent-consensus-synthesizer?patient_limit=1")
    implementation_brief = client.get("/api/autonomous-improvement/implementation-brief?patient_limit=1")
    shadow_patch_blueprint = client.get("/api/autonomous-improvement/shadow-patch-blueprint?patient_limit=1")
    human_patch_authorization = client.get("/api/autonomous-improvement/human-patch-authorization?patient_limit=1")
    controlled_patch_application = client.get("/api/autonomous-improvement/controlled-patch-application?patient_limit=1")
    controlled_pr_implementation = client.get("/api/autonomous-improvement/controlled-pr-implementation?patient_limit=1")
    draft_pr_publication_gate = client.get("/api/autonomous-improvement/draft-pr-publication-gate?patient_limit=1")
    required_safety_gate_contract = client.get("/api/autonomous-improvement/required-safety-gate-contract?patient_limit=1")
    evidence_refresh_shadow_loop = client.get("/api/autonomous-improvement/evidence-refresh-shadow-loop?patient_limit=1")
    patient_twin_readiness_loop = client.get("/api/autonomous-improvement/patient-twin-readiness-loop?patient_limit=1")
    ai_readiness_dataset_loop = client.get("/api/autonomous-improvement/ai-readiness-dataset-loop?patient_limit=1")
    cortana_loop_interface = client.get(
        "/api/autonomous-improvement/cortana-loop-interface?patient_limit=1&query=que%20falta%20para%20alcanzar%20el%20objetivo%20final"
    )
    continuous_shadow_operation = client.get(
        "/api/autonomous-improvement/continuous-shadow-operation?patient_limit=1"
    )
    patch_authorization_decision = client.post(
        "/api/autonomous-improvement/human-patch-authorization/decision",
        json={
            "decision": "hold",
            "reviewer": "QA 123456789",
            "note": "hold patch 987654321",
            "patient_limit": 1,
        },
    )
    pr_metadata = client.post(
        "/api/autonomous-improvement/pr-review-monitor/metadata",
        json={
            "patient_limit": 1,
            "pr_number": 11,
            "pr_url": "https://github.com/example/Prostamed-V3/pull/11",
            "ci_status": "passed",
            "review_status": "approved",
            "reviewer": "QA 123456789",
            "note": "metadata 987654321",
        },
    )
    human_review_decision = client.post(
        "/api/autonomous-improvement/human-review-gate/decision",
        json={"decision": "hold", "reviewer": "QA 123456789", "note": "hold 987654321", "patient_limit": 1},
    )
    recompute = client.post("/api/autonomous-improvement/recompute", json={"patient_limit": 1})

    assert mission.status_code == 200
    assert mission.get_json()["success"] is True
    assert mission.get_json()["safety"]["source_clinical_facts_mutated"] is False
    assert gaps.status_code == 200
    assert gaps.get_json()["phase"] == "2B_contradiction_intelligence"
    assert "clinical_gap_contracts" in gaps.get_json()
    assert "contractual_gap_rows" in gaps.get_json()
    assert "application_telemetry" in gaps.get_json()
    assert "contradiction_rules" in gaps.get_json()
    assert "contradiction_rows" in gaps.get_json()
    assert application_telemetry.status_code == 200
    assert application_telemetry.get_json()["source_clinical_facts_mutated"] is False
    assert application_telemetry.get_json()["summary"]["software_gap_closed_count"] >= 0
    assert proposals.status_code == 200
    assert "clinical_contract" in (proposals.get_json().get("proposals") or [{}])[0]
    assert "contradictions" in (proposals.get_json().get("proposals") or [{}])[0]
    assert shadow_pr.status_code == 200
    assert shadow_pr.get_json()["phase"] == "3B_shadow_pr_factory"
    assert shadow_pr.get_json()["git_mutated"] is False
    assert shadow_pr.get_json()["pull_request_created"] is False
    assert safety_gates.status_code == 200
    assert safety_gates.get_json()["phase"] == "3C_safety_gate_runner"
    assert safety_gates.get_json()["commands_executed"] is False
    assert safety_gates.get_json()["git_mutated"] is False
    assert safety_gates.get_json()["source_clinical_facts_mutated"] is False
    assert shadow_execution.status_code == 200
    assert shadow_execution.get_json()["phase"] == "3D_shadow_execution_artifacts"
    assert shadow_execution.get_json()["git_mutated"] is False
    assert shadow_execution.get_json()["source_clinical_facts_mutated"] is False
    assert shadow_execution.get_json()["auto_merge_allowed"] is False
    assert human_review_gate.status_code == 200
    assert human_review_gate.get_json()["phase"] == "3E_human_review_decision_gate"
    assert human_review_gate.get_json()["git_mutated"] is False
    assert human_review_gate.get_json()["source_clinical_facts_mutated"] is False
    assert human_review_gate.get_json()["auto_merge_allowed"] is False
    assert draft_handoff.status_code == 200
    assert draft_handoff.get_json()["phase"] == "3F_draft_pr_handoff"
    assert draft_handoff.get_json()["branch_created"] is False
    assert draft_handoff.get_json()["pull_request_created"] is False
    assert draft_handoff.get_json()["git_mutated"] is False
    assert draft_handoff.get_json()["source_clinical_facts_mutated"] is False
    assert draft_handoff.get_json()["auto_merge_allowed"] is False
    assert pr_monitor.status_code == 200
    assert pr_monitor.get_json()["phase"] == "3G_pr_review_monitor"
    assert pr_monitor.get_json()["branch_created"] is False
    assert pr_monitor.get_json()["pull_request_created"] is False
    assert pr_monitor.get_json()["merge_performed"] is False
    assert pr_monitor.get_json()["git_mutated"] is False
    assert pr_monitor.get_json()["source_clinical_facts_mutated"] is False
    assert pr_monitor.get_json()["auto_merge_allowed"] is False
    assert pr_metadata.status_code == 200
    assert pr_metadata.get_json()["metadata"]["ci_status"] == "passed"
    assert pr_metadata.get_json()["merge_performed"] is False
    assert pr_metadata.get_json()["git_mutated"] is False
    assert agent_registry.status_code == 200
    assert agent_registry.get_json()["phase"] == "4A_agent_lane_registry"
    assert agent_registry.get_json()["source_clinical_facts_mutated"] is False
    assert agent_registry.get_json()["git_mutated"] is False
    assert agent_registry.get_json()["auto_merge_allowed"] is False
    assert agent_packets.status_code == 200
    assert agent_packets.get_json()["phase"] == "4B_agent_proposal_packets"
    assert agent_packets.get_json()["source_clinical_facts_mutated"] is False
    assert agent_packets.get_json()["git_mutated"] is False
    assert agent_packets.get_json()["auto_merge_allowed"] is False
    assert agent_consensus.status_code == 200
    assert agent_consensus.get_json()["phase"] == "4C_consensus_synthesizer"
    assert agent_consensus.get_json()["source_clinical_facts_mutated"] is False
    assert agent_consensus.get_json()["git_mutated"] is False
    assert agent_consensus.get_json()["branch_created"] is False
    assert agent_consensus.get_json()["pull_request_created"] is False
    assert agent_consensus.get_json()["merge_performed"] is False
    assert agent_consensus.get_json()["auto_merge_allowed"] is False
    assert implementation_brief.status_code == 200
    assert implementation_brief.get_json()["phase"] == "4D_implementation_brief"
    assert implementation_brief.get_json()["commands_executed"] is False
    assert implementation_brief.get_json()["source_clinical_facts_mutated"] is False
    assert implementation_brief.get_json()["git_mutated"] is False
    assert implementation_brief.get_json()["branch_created"] is False
    assert implementation_brief.get_json()["pull_request_created"] is False
    assert implementation_brief.get_json()["merge_performed"] is False
    assert implementation_brief.get_json()["auto_merge_allowed"] is False
    assert shadow_patch_blueprint.status_code == 200
    assert shadow_patch_blueprint.get_json()["phase"] == "4E_shadow_patch_blueprint"
    assert shadow_patch_blueprint.get_json()["commands_executed"] is False
    assert shadow_patch_blueprint.get_json()["files_modified"] is False
    assert shadow_patch_blueprint.get_json()["source_clinical_facts_mutated"] is False
    assert shadow_patch_blueprint.get_json()["git_mutated"] is False
    assert shadow_patch_blueprint.get_json()["branch_created"] is False
    assert shadow_patch_blueprint.get_json()["pull_request_created"] is False
    assert shadow_patch_blueprint.get_json()["merge_performed"] is False
    assert shadow_patch_blueprint.get_json()["auto_merge_allowed"] is False
    assert human_patch_authorization.status_code == 200
    assert human_patch_authorization.get_json()["phase"] == "4F_human_patch_authorization"
    assert human_patch_authorization.get_json()["commands_executed"] is False
    assert human_patch_authorization.get_json()["files_modified"] is False
    assert human_patch_authorization.get_json()["source_clinical_facts_mutated"] is False
    assert human_patch_authorization.get_json()["git_mutated"] is False
    assert human_patch_authorization.get_json()["branch_created"] is False
    assert human_patch_authorization.get_json()["pull_request_created"] is False
    assert human_patch_authorization.get_json()["merge_performed"] is False
    assert human_patch_authorization.get_json()["auto_merge_allowed"] is False
    assert controlled_patch_application.status_code == 200
    assert controlled_patch_application.get_json()["phase"] == "4G_controlled_patch_application"
    assert controlled_patch_application.get_json()["commands_executed"] is False
    assert controlled_patch_application.get_json()["files_modified"] is False
    assert controlled_patch_application.get_json()["source_clinical_facts_mutated"] is False
    assert controlled_patch_application.get_json()["git_mutated"] is False
    assert controlled_patch_application.get_json()["branch_created"] is False
    assert controlled_patch_application.get_json()["pull_request_created"] is False
    assert controlled_patch_application.get_json()["merge_performed"] is False
    assert controlled_patch_application.get_json()["auto_merge_allowed"] is False
    assert controlled_pr_implementation.status_code == 200
    assert controlled_pr_implementation.get_json()["phase"] == "5A_controlled_pr_implementation"
    assert controlled_pr_implementation.get_json()["commands_executed"] is False
    assert controlled_pr_implementation.get_json()["files_modified"] is False
    assert controlled_pr_implementation.get_json()["source_clinical_facts_mutated"] is False
    assert controlled_pr_implementation.get_json()["git_mutated"] is False
    assert controlled_pr_implementation.get_json()["branch_created"] is False
    assert controlled_pr_implementation.get_json()["pull_request_created"] is False
    assert controlled_pr_implementation.get_json()["merge_performed"] is False
    assert controlled_pr_implementation.get_json()["auto_merge_allowed"] is False
    assert draft_pr_publication_gate.status_code == 200
    assert draft_pr_publication_gate.get_json()["phase"] == "5B_draft_pr_publication_gate"
    assert draft_pr_publication_gate.get_json()["commands_executed"] is False
    assert draft_pr_publication_gate.get_json()["files_modified"] is False
    assert draft_pr_publication_gate.get_json()["source_clinical_facts_mutated"] is False
    assert draft_pr_publication_gate.get_json()["git_mutated"] is False
    assert draft_pr_publication_gate.get_json()["branch_created"] is False
    assert draft_pr_publication_gate.get_json()["pull_request_created"] is False
    assert draft_pr_publication_gate.get_json()["merge_performed"] is False
    assert draft_pr_publication_gate.get_json()["auto_merge_allowed"] is False
    assert required_safety_gate_contract.status_code == 200
    assert required_safety_gate_contract.get_json()["phase"] == "6A_required_safety_gate_contract"
    assert required_safety_gate_contract.get_json()["commands_executed"] is False
    assert required_safety_gate_contract.get_json()["files_modified"] is False
    assert required_safety_gate_contract.get_json()["source_clinical_facts_mutated"] is False
    assert required_safety_gate_contract.get_json()["git_mutated"] is False
    assert required_safety_gate_contract.get_json()["branch_created"] is False
    assert required_safety_gate_contract.get_json()["pull_request_created"] is False
    assert required_safety_gate_contract.get_json()["merge_performed"] is False
    assert required_safety_gate_contract.get_json()["auto_merge_allowed"] is False
    assert evidence_refresh_shadow_loop.status_code == 200
    assert evidence_refresh_shadow_loop.get_json()["phase"] == "7A_evidence_refresh_shadow_loop"
    assert evidence_refresh_shadow_loop.get_json()["evidence_changes_applied"] is False
    assert evidence_refresh_shadow_loop.get_json()["recommendation_logic_mutated"] is False
    assert evidence_refresh_shadow_loop.get_json()["trial_logic_mutated"] is False
    assert evidence_refresh_shadow_loop.get_json()["gate_logic_mutated"] is False
    assert evidence_refresh_shadow_loop.get_json()["commands_executed"] is False
    assert evidence_refresh_shadow_loop.get_json()["files_modified"] is False
    assert evidence_refresh_shadow_loop.get_json()["source_clinical_facts_mutated"] is False
    assert evidence_refresh_shadow_loop.get_json()["git_mutated"] is False
    assert evidence_refresh_shadow_loop.get_json()["branch_created"] is False
    assert evidence_refresh_shadow_loop.get_json()["pull_request_created"] is False
    assert evidence_refresh_shadow_loop.get_json()["merge_performed"] is False
    assert evidence_refresh_shadow_loop.get_json()["auto_merge_allowed"] is False
    assert patient_twin_readiness_loop.status_code == 200
    assert patient_twin_readiness_loop.get_json()["phase"] == "8A_patient_twin_readiness_loop"
    assert patient_twin_readiness_loop.get_json()["simulation_release_allowed"] is False
    assert patient_twin_readiness_loop.get_json()["patient_twin_models_trained"] is False
    assert patient_twin_readiness_loop.get_json()["patient_twin_predictions_released"] is False
    assert patient_twin_readiness_loop.get_json()["commands_executed"] is False
    assert patient_twin_readiness_loop.get_json()["files_modified"] is False
    assert patient_twin_readiness_loop.get_json()["source_clinical_facts_mutated"] is False
    assert patient_twin_readiness_loop.get_json()["git_mutated"] is False
    assert patient_twin_readiness_loop.get_json()["branch_created"] is False
    assert patient_twin_readiness_loop.get_json()["pull_request_created"] is False
    assert patient_twin_readiness_loop.get_json()["merge_performed"] is False
    assert patient_twin_readiness_loop.get_json()["auto_merge_allowed"] is False
    assert ai_readiness_dataset_loop.status_code == 200
    assert ai_readiness_dataset_loop.get_json()["phase"] == "9A_ai_readiness_dataset_loop"
    assert ai_readiness_dataset_loop.get_json()["dataset_export_allowed"] is False
    assert ai_readiness_dataset_loop.get_json()["dataset_export_written"] is False
    assert ai_readiness_dataset_loop.get_json()["deidentified_dataset_written"] is False
    assert ai_readiness_dataset_loop.get_json()["model_training_allowed"] is False
    assert ai_readiness_dataset_loop.get_json()["model_training_executed"] is False
    assert ai_readiness_dataset_loop.get_json()["models_trained"] is False
    assert ai_readiness_dataset_loop.get_json()["prediction_release_allowed"] is False
    assert ai_readiness_dataset_loop.get_json()["predictions_released"] is False
    assert ai_readiness_dataset_loop.get_json()["recommendation_logic_mutated"] is False
    assert ai_readiness_dataset_loop.get_json()["commands_executed"] is False
    assert ai_readiness_dataset_loop.get_json()["files_modified"] is False
    assert ai_readiness_dataset_loop.get_json()["source_clinical_facts_mutated"] is False
    assert ai_readiness_dataset_loop.get_json()["git_mutated"] is False
    assert ai_readiness_dataset_loop.get_json()["branch_created"] is False
    assert ai_readiness_dataset_loop.get_json()["pull_request_created"] is False
    assert ai_readiness_dataset_loop.get_json()["merge_performed"] is False
    assert ai_readiness_dataset_loop.get_json()["auto_merge_allowed"] is False
    assert cortana_loop_interface.status_code == 200
    assert cortana_loop_interface.get_json()["phase"] == "10A_cortana_loop_interface"
    assert cortana_loop_interface.get_json()["voice_write_allowed"] is False
    assert cortana_loop_interface.get_json()["clinical_fact_writes_allowed"] is False
    assert cortana_loop_interface.get_json()["code_mutation_allowed"] is False
    assert cortana_loop_interface.get_json()["model_training_allowed"] is False
    assert cortana_loop_interface.get_json()["prediction_release_allowed"] is False
    assert cortana_loop_interface.get_json()["external_action_allowed"] is False
    assert cortana_loop_interface.get_json()["commands_executed"] is False
    assert cortana_loop_interface.get_json()["files_modified"] is False
    assert cortana_loop_interface.get_json()["source_clinical_facts_mutated"] is False
    assert cortana_loop_interface.get_json()["git_mutated"] is False
    assert cortana_loop_interface.get_json()["branch_created"] is False
    assert cortana_loop_interface.get_json()["pull_request_created"] is False
    assert cortana_loop_interface.get_json()["merge_performed"] is False
    assert cortana_loop_interface.get_json()["auto_merge_allowed"] is False
    assert cortana_loop_interface.get_json()["resolved_response"]["matched_command_id"] == "final_goal_gap"
    assert continuous_shadow_operation.status_code == 200
    assert continuous_shadow_operation.get_json()["phase"] == "continuous_shadow_operation"
    assert continuous_shadow_operation.get_json()["commands_executed"] is False
    assert continuous_shadow_operation.get_json()["files_modified"] is False
    assert continuous_shadow_operation.get_json()["source_clinical_facts_mutated"] is False
    assert continuous_shadow_operation.get_json()["git_mutated"] is False
    assert continuous_shadow_operation.get_json()["branch_created"] is False
    assert continuous_shadow_operation.get_json()["pull_request_created"] is False
    assert continuous_shadow_operation.get_json()["merge_performed"] is False
    assert continuous_shadow_operation.get_json()["auto_merge_allowed"] is False
    assert "human_authorization_request" in continuous_shadow_operation.get_json()
    assert patch_authorization_decision.status_code == 200
    assert patch_authorization_decision.get_json()["decision"]["decision"] == "hold"
    assert patch_authorization_decision.get_json()["commands_executed"] is False
    assert patch_authorization_decision.get_json()["files_modified"] is False
    assert patch_authorization_decision.get_json()["source_clinical_facts_mutated"] is False
    assert patch_authorization_decision.get_json()["git_mutated"] is False
    assert patch_authorization_decision.get_json()["branch_created"] is False
    assert patch_authorization_decision.get_json()["pull_request_created"] is False
    assert patch_authorization_decision.get_json()["merge_performed"] is False
    assert patch_authorization_decision.get_json()["auto_merge_allowed"] is False
    assert human_review_decision.status_code == 200
    assert human_review_decision.get_json()["decision"]["decision"] == "hold"
    assert human_review_decision.get_json()["pull_request_created"] is False
    assert human_review_decision.get_json()["git_mutated"] is False
    assert recompute.status_code == 200
    assert recompute.get_json()["source_clinical_facts_mutated"] is False

    candidate_id = (proposals.get_json().get("proposals") or [{}])[0].get("id") or "manual-test"
    approved = client.post(
        f"/api/autonomous-improvement/proposals/{candidate_id}/approve",
        json={"reviewer": "QA", "note": "ok 123456789"},
    )
    rejected = client.post(
        f"/api/autonomous-improvement/proposals/{candidate_id}/reject",
        json={"reviewer": "QA", "note": "reject 987654321"},
    )

    assert approved.status_code == 200
    assert approved.get_json()["source_clinical_facts_mutated"] is False
    assert rejected.status_code == 200
    assert "***" in (tmp_path / "reviews.jsonl").read_text(encoding="utf-8")


def test_loop_monitor_and_cortana_contracts_expose_autonomous_improvement(app_client):
    client, _db_path = app_client
    snapshot = client.get("/api/loop-monitor/snapshot")
    loop_page = client.get("/loop-monitor")

    assert snapshot.status_code == 200
    snapshot_json = snapshot.get_json()
    assert "mission_control" in snapshot_json
    assert "development_autodrive" in snapshot_json
    assert "scoring_transparency" in snapshot_json["development_autodrive"]
    assert "shadow_pr_factory" in snapshot.get_json()
    assert "safety_gate_runner" in snapshot.get_json()
    assert "shadow_execution_artifacts" in snapshot.get_json()
    assert "human_review_decision_gate" in snapshot.get_json()
    assert "draft_pr_handoff" in snapshot.get_json()
    assert "pr_review_monitor" in snapshot.get_json()
    assert "agent_lane_registry" in snapshot.get_json()
    assert "agent_proposal_packets" in snapshot.get_json()
    assert "agent_consensus_synthesizer" in snapshot.get_json()
    assert "implementation_brief" in snapshot.get_json()
    assert "shadow_patch_blueprint" in snapshot.get_json()
    assert "human_patch_authorization" in snapshot.get_json()
    assert "controlled_patch_application" in snapshot.get_json()
    assert "controlled_pr_implementation" in snapshot.get_json()
    assert "draft_pr_publication_gate" in snapshot.get_json()
    assert "required_safety_gate_contract" in snapshot.get_json()
    assert "evidence_refresh_shadow_loop" in snapshot.get_json()
    assert "patient_twin_readiness_loop" in snapshot.get_json()
    assert "ai_readiness_dataset_loop" in snapshot.get_json()
    assert "cortana_loop_interface" in snapshot.get_json()
    assert "continuous_shadow_operation" in snapshot.get_json()
    html = loop_page.data.decode("utf-8")
    assert "Progreso hacia ProstaMed OS longitudinal" in html
    assert "Development Autodrive" in html
    assert "Transparencia del scoring" in html
    assert "Clinical Priority Transparency" in html
    assert "candidatos clínicos abiertos" in html
    assert "Shadow PR Factory" in html
    assert "Safety Gate Runner" in html
    assert "Shadow Execution Artifacts" in html
    assert "Human Review Decision Gate" in html
    assert "Draft PR Handoff" in html
    assert "PR Review Monitor" in html
    assert "Agent Lane Registry" in html
    assert "Agent Proposal Packets" in html
    assert "Consensus Synthesizer" in html
    assert "Implementation Brief" in html
    assert "Shadow Patch Blueprint" in html
    assert "Human Patch Authorization" in html
    assert "pm2HumanPatchAuthorization" in html
    assert "Controlled Patch Application" in html
    assert "pm2ControlledPatchApplication" in html
    assert "Controlled PR Implementation" in html
    assert "pm2ControlledPrImplementation" in html
    assert "Draft PR Publication Gate" in html
    assert "pm2DraftPrPublicationGate" in html
    assert "Required Safety Gate Contract" in html
    assert "pm2RequiredSafetyGateContract" in html
    assert "Evidence Refresh Shadow Loop" in html
    assert "pm2EvidenceRefreshShadowLoop" in html
    assert "Patient Twin Readiness Loop" in html
    assert "pm2PatientTwinReadinessLoop" in html
    assert "AI Readiness Dataset Loop" in html
    assert "pm2AiReadinessDatasetLoop" in html
    assert "Cortana Loop Interface" in html
    assert "pm2CortanaLoopInterface" in html
    assert "Continuous Shadow Operation" in html
    assert "pm2ContinuousShadowOperation" in html
    assert "pipeline automejora" in html
    assert "objetivo clínico global" in html
    assert "autonomous_loop_maturity" in html
    assert html.count('class="pm2-loop-vector-card"') == 8

    app_source = Path("app.py").read_text(encoding="utf-8")
    dashboard = Path("templates/demos/clinical_dashboard_v2_demo.html").read_text(encoding="utf-8")
    voice_js = Path("static/js/prostamed_voice_os.js").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/autonomous_improvement_shadow_loop.yml").read_text(encoding="utf-8")

    assert "/api/autonomous-improvement/mission-control" in app_source
    assert "/api/autonomous-improvement/draft-pr-handoff" in app_source
    assert "/api/autonomous-improvement/pr-review-monitor" in app_source
    assert "/api/autonomous-improvement/agent-lane-registry" in app_source
    assert "/api/autonomous-improvement/agent-proposal-packets" in app_source
    assert "/api/autonomous-improvement/agent-consensus-synthesizer" in app_source
    assert "/api/autonomous-improvement/implementation-brief" in app_source
    assert "/api/autonomous-improvement/shadow-patch-blueprint" in app_source
    assert "/api/autonomous-improvement/human-patch-authorization" in app_source
    assert "/api/autonomous-improvement/controlled-patch-application" in app_source
    assert "/api/autonomous-improvement/controlled-pr-implementation" in app_source
    assert "/api/autonomous-improvement/draft-pr-publication-gate" in app_source
    assert "/api/autonomous-improvement/required-safety-gate-contract" in app_source
    assert "/api/autonomous-improvement/evidence-refresh-shadow-loop" in app_source
    assert "/api/autonomous-improvement/patient-twin-readiness-loop" in app_source
    assert "/api/autonomous-improvement/ai-readiness-dataset-loop" in app_source
    assert "/api/autonomous-improvement/cortana-loop-interface" in app_source
    assert "/api/autonomous-improvement/continuous-shadow-operation" in app_source
    assert "/api/autonomous-improvement/cortana-loop-interface" in voice_js
    assert "/api/autonomous-improvement/continuous-shadow-operation" in voice_js
    assert "pm2ContinuousShadowOperation" in voice_js
    assert "Camino al objetivo final" in dashboard
    assert "handleAutonomousImprovementCommand" in voice_js
    assert "AGENTIC_AUTO_MERGE: \"false\"" in workflow
    evidence_workflow = Path(".github/workflows/evidence_refresh_loop.yml").read_text(encoding="utf-8")
    assert "PROSTAMED_EVIDENCE_SHADOW_MODE" in evidence_workflow
    assert "test_phase_7a_evidence_refresh_shadow_loop_requires_6a" in evidence_workflow
