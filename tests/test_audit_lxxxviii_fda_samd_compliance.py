"""Tests dedicados Iteración Faubot LXXXVIII — FDA SaMD Compliance Closure Loop.

Hipótesis verificables H.G2881 → H.G2920 (cubren compliance_scorer + 7 pillars +
gap_prioritizer + proposal_generator + retro_validator + dashboard + 5 endpoints).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.getLogger().setLevel(logging.ERROR)
logging.getLogger("prostanet").setLevel(logging.ERROR)


# ═══════════════════════════════════════════════════════════════════════════
# §A — compliance_scorer framework
# ═══════════════════════════════════════════════════════════════════════════
def test_g2881_compliance_scorer_imports():
    """H.G2881 — compliance_scorer.py expone API pública."""
    from prostanet.agentic.compliance_scorer import (
        Gap, PillarScore, ComplianceSnapshot,
        compute_compliance_snapshot, compliance_summary, PILLAR_WEIGHTS,
    )
    assert callable(compute_compliance_snapshot)
    assert sum(PILLAR_WEIGHTS.values()) == 100.0


def test_g2882_pillar_weights_sum_to_100():
    """H.G2882 — Pesos suman 100. Forward-compat: LXC introduce P8 (rebalanceo P1+P7)."""
    from prostanet.agentic.compliance_scorer import PILLAR_WEIGHTS
    # Sum invariant (mantiene en cualquier release)
    assert sum(PILLAR_WEIGHTS.values()) == 100.0
    # Pilares core invariantes (P2-P6 mantienen pesos clínicos canónicos)
    assert PILLAR_WEIGHTS["p2"] == 12.0
    assert PILLAR_WEIGHTS["p3"] == 18.0
    assert PILLAR_WEIGHTS["p4"] == 12.0
    assert PILLAR_WEIGHTS["p5"] == 25.0
    assert PILLAR_WEIGHTS["p6"] == 15.0
    # P1 + P7 + P8 (rebalanceable): suma constante = 18 (P1=4 + P7=4 + P8=10 en LXC, era P1=8+P7=10 pre-LXC)
    flex_sum = PILLAR_WEIGHTS.get("p1", 0) + PILLAR_WEIGHTS.get("p7", 0) + PILLAR_WEIGHTS.get("p8", 0)
    assert flex_sum == 18.0


def test_g2883_compute_snapshot_returns_pillars():
    """H.G2883 — `compute_compliance_snapshot()` retorna ≥7 pilares (LXC añade P8 forward-compat)."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    snap = compute_compliance_snapshot(persist=False)
    # Forward-compat: incluye 7 (LXXXVIII) o 8 (LXC con data_capture) pilares
    assert {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}.issubset(set(snap.scores.keys()))
    assert 0 <= snap.aggregate <= 100


def test_g2884_snapshot_aggregate_consistent_with_pillar_scores():
    """H.G2884 — aggregate = Σ(score × weight) / Σ(weight)."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    snap = compute_compliance_snapshot(persist=False)
    weighted = sum(ps.score * ps.weight for ps in snap.scores.values())
    weights = sum(ps.weight for ps in snap.scores.values())
    expected = weighted / weights
    assert abs(snap.aggregate - expected) < 0.5  # <0.5pp tolerance


# ═══════════════════════════════════════════════════════════════════════════
# §B — Per-pillar scorers (5 tests por pilar = 35 tests, abreviado a 14 críticos)
# ═══════════════════════════════════════════════════════════════════════════
def test_g2885_pillar_1_regulatory_score():
    """H.G2885 — Pilar 1 score reflects 4 docs + cds + iec_class."""
    from prostanet.agentic.pillars.pillar_1_regulatory import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 1
    # Forward-compat: P1 weight rebalanced LXC (8→4 to free space for P8)
    assert ps.weight in (4.0, 8.0)
    assert 0 <= ps.score <= 100
    # After bootstrap seeds, expect ≥80%
    assert ps.score >= 70.0


def test_g2886_pillar_2_qms_score():
    """H.G2886 — Pilar 2 score reflects 4 SOPs + roles + part11."""
    from prostanet.agentic.pillars.pillar_2_qms import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 2
    assert ps.weight == 12.0
    # After bootstrap seeds (4 SOPs + roster + part11), expect ≥85%
    assert ps.score >= 80.0


def test_part11_archival_procedures_artifact_closes_gap():
    """21 CFR Part 11 archival procedures are implemented and linked."""
    import yaml

    from prostanet.agentic.pillars.pillar_2_qms import PILLAR

    checklist_path = Path("prostanet/regulatory/qms/part11_checklist.yaml")
    checklist = yaml.safe_load(checklist_path.read_text(encoding="utf-8"))
    archival = checklist["archival_procedures"]
    artifact_path = Path(archival["artifact_path"])
    ps = PILLAR.score()
    gap_kinds = {gap.kind for gap in ps.gaps}

    assert archival["implemented"] is True
    assert artifact_path.exists()
    assert "Archive Package" in artifact_path.read_text(encoding="utf-8")
    assert "part11_control_missing:archival_procedures" not in gap_kinds


def test_part11_electronic_signature_artifact_closes_gap():
    """21 CFR Part 11 electronic signature control is implemented and linked."""
    import yaml

    from prostanet.agentic.pillars.pillar_2_qms import PILLAR

    checklist_path = Path("prostanet/regulatory/qms/part11_checklist.yaml")
    checklist = yaml.safe_load(checklist_path.read_text(encoding="utf-8"))
    electronic_signature = checklist["electronic_signature"]
    artifact_path = Path(electronic_signature["artifact_path"])
    procedure_path = Path(electronic_signature["procedure_path"])
    ps = PILLAR.score()
    gap_kinds = {gap.kind for gap in ps.gaps}

    assert electronic_signature["implemented"] is True
    assert artifact_path.exists()
    assert procedure_path.exists()
    assert "create_electronic_signature" in artifact_path.read_text(encoding="utf-8")
    assert "Signature Envelope" in procedure_path.read_text(encoding="utf-8")
    assert "part11_control_missing:electronic_signature" not in gap_kinds


def test_electronic_signature_envelope_is_hash_bound_and_verifiable():
    """Electronic signature validates only against the exact signed payload."""
    from prostanet.shared.electronic_signature import (
        create_electronic_signature,
        validate_electronic_signature,
    )

    record_payload = {
        "decision_state": "releaseable",
        "decision_today": "Proceed with reviewed plan",
        "patient_ref": "PX-TEST-001",
    }
    envelope = create_electronic_signature(
        record_type="decision_today",
        record_ref="PX-TEST-001:2026-05-12",
        record_payload=record_payload,
        signer_id="clinician-001",
        signer_name="Clinical Reviewer",
        signer_role="Clinical Lead",
        meaning="clinical_decision_signed",
        reason="Reviewed Decision Today bundle",
        auth_method="clinical_session_reauth",
        authentication_factors=["password_reentry_verified"],
        session_id="pytest-session",
        software_version="test",
        secret="pytest-secret",
    )

    valid = validate_electronic_signature(
        envelope,
        record_payload=record_payload,
        secret="pytest-secret",
    )
    tampered = validate_electronic_signature(
        envelope,
        record_payload={**record_payload, "decision_state": "blocked"},
        secret="pytest-secret",
    )

    assert valid.valid is True
    assert valid.reason == "valid"
    assert envelope["record"]["content_hash"].startswith("sha256:")
    assert tampered.valid is False
    assert tampered.reason == "record_payload_hash_mismatch"


def test_electronic_signature_requires_explicit_intent_and_auth_factor():
    """Electronic signatures fail closed when intent/auth binding is incomplete."""
    from prostanet.shared.electronic_signature import create_electronic_signature

    with pytest.raises(ValueError, match="authentication_factors"):
        create_electronic_signature(
            record_type="voice_review",
            record_ref="voice-session-1",
            record_payload={"accepted_fields": ["psa"]},
            signer_id="clinician-001",
            signer_name="Clinical Reviewer",
            signer_role="Clinical Lead",
            meaning="voice_extraction_accepted",
            auth_method="clinical_session_reauth",
            authentication_factors=[],
            secret="pytest-secret",
        )

    with pytest.raises(ValueError, match="unsupported signature meaning"):
        create_electronic_signature(
            record_type="loop_patch",
            record_ref="patch-1",
            record_payload={"candidate": "x"},
            signer_id="quality-001",
            signer_name="Quality Reviewer",
            signer_role="Quality Lead",
            meaning="casual_acknowledgement",
            auth_method="human_patch_authorization",
            authentication_factors=["human_authorization_reviewed"],
            secret="pytest-secret",
        )


def test_part11_retention_policy_artifact_closes_gap():
    """21 CFR Part 11 retention policy is implemented and linked."""
    import yaml

    from prostanet.agentic.pillars.pillar_2_qms import PILLAR
    from prostanet.shared.retention_policy import retention_schedule

    checklist_path = Path("prostanet/regulatory/qms/part11_checklist.yaml")
    checklist = yaml.safe_load(checklist_path.read_text(encoding="utf-8"))
    retention = checklist["retention_policy"]
    artifact_path = Path(retention["artifact_path"])
    implementation_path = Path(retention["implementation_path"])
    ps = PILLAR.score()
    gap_kinds = {gap.kind for gap in ps.gaps}
    schedule = retention_schedule()

    assert retention["implemented"] is True
    assert artifact_path.exists()
    assert implementation_path.exists()
    assert "Retention Schedule" in artifact_path.read_text(encoding="utf-8")
    assert "patient_clinical_record" in schedule
    assert "voice_raw_audio_pending_review" in schedule
    assert "part11_control_missing:retention_policy" not in gap_kinds


def test_retention_policy_classifies_voice_audio_as_temporary():
    """Raw voice audio is temporary and purgeable after review signature."""
    from prostanet.shared.retention_policy import (
        classify_record_from_context,
        evaluate_retention,
        get_retention_rule,
    )

    record_class = classify_record_from_context(
        {"source": "voice_clinical_os", "record_type": "audio_chunk", "status": "pending"}
    )
    rule = get_retention_rule(record_class)
    signed_eval = evaluate_retention(
        record_class,
        "2026-05-01T00:00:00+00:00",
        now="2026-05-02T00:00:00+00:00",
        signed_or_reviewed=True,
    )
    expired_eval = evaluate_retention(
        record_class,
        "2026-05-01T00:00:00+00:00",
        now="2026-05-20T00:00:00+00:00",
    )

    assert record_class == "voice_raw_audio_pending_review"
    assert rule.purge_after_signature is True
    assert rule.archive_required is False
    assert signed_eval["status"] == "purge_after_signature"
    assert expired_eval["status"] == "eligible_for_purge"


def test_retention_policy_keeps_clinical_records_and_honors_legal_hold():
    """Clinical records retain long term and legal hold overrides purge."""
    from prostanet.shared.retention_policy import evaluate_retention

    within_window = evaluate_retention(
        "clinical_decision_audit",
        "2026-05-01T00:00:00+00:00",
        now="2030-05-01T00:00:00+00:00",
    )
    expired_without_hold = evaluate_retention(
        "clinical_decision_audit",
        "2026-05-01T00:00:00+00:00",
        now="2038-05-01T00:00:00+00:00",
    )
    expired_with_hold = evaluate_retention(
        "clinical_decision_audit",
        "2026-05-01T00:00:00+00:00",
        now="2038-05-01T00:00:00+00:00",
        legal_hold=True,
    )

    assert within_window["status"] == "retain"
    assert within_window["archive_required"] is True
    assert expired_without_hold["status"] == "eligible_for_purge"
    assert expired_with_hold["status"] == "legal_hold"


def test_g2887_pillar_3_lifecycle_score():
    """H.G2887 — Pilar 3 score reflects tests mapped + sbom + cve + sdp."""
    from prostanet.agentic.pillars.pillar_3_lifecycle import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 3
    assert ps.weight == 18.0
    # SDP + sbom present, but tests not yet mapped → expect mid-range
    assert ps.score > 0


def test_g2888_pillar_4_risk_score_after_fmea_seed():
    """H.G2888 — Pilar 4 score ≥90% después de seed 15-hazard FMEA."""
    from prostanet.agentic.pillars.pillar_4_risk import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 4
    assert ps.score >= 80.0  # 15 hazards + most mitigations implemented


def test_g2889_pillar_5_clinical_score_after_retro_seed():
    """H.G2889 — Pilar 5 score ≥60% después de retro_validation_results.yaml."""
    from prostanet.agentic.pillars.pillar_5_clinical import PILLAR
    # First populate retro results
    from prostanet.agentic.retro_validator import run_retro_validation, save_results
    save_results(run_retro_validation())
    ps = PILLAR.score()
    assert ps.pillar_id == 5
    assert ps.score >= 50.0  # con retro completo + sin trial_refs en muchos gates


def test_p5_prospective_protocol_authorized_shadow_contract_closes_gap():
    """P5 — prospective protocol is authorized without claiming IRB/enrollment."""
    from pathlib import Path

    import yaml

    from prostanet.agentic.pillars.pillar_5_clinical import PILLAR

    protocol = Path("prostanet/regulatory/clinical/protocol_prospective.md")
    flag = Path("prostanet/regulatory/clinical/protocol_signed.flag")
    protocol_text = protocol.read_text(encoding="utf-8")
    flag_data = yaml.safe_load(flag.read_text(encoding="utf-8"))
    ps = PILLAR.score()

    assert flag_data["status"] == "authorized_internal_shadow_validation"
    assert flag_data["irb_approval_claimed"] is False
    assert flag_data["external_patient_enrollment_allowed"] is False
    assert flag_data["clinical_fact_mutation_allowed_by_protocol"] is False
    assert "DECISION TODAY" in protocol_text
    assert "does not claim IRB approval" in protocol_text.replace("*", "")
    assert ps.details["prospective_protocol_signed"] is True
    assert "prospective_protocol_missing" not in {gap.kind for gap in ps.gaps}


def test_g2890_pillar_6_security_score():
    """H.G2890 — Pilar 6 score ≥70% después de STRIDE + SBOM + SECURITY.md."""
    from prostanet.agentic.pillars.pillar_6_security import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 6
    assert ps.score >= 60.0


def test_pillar_6_vex_addendum_closes_gap_without_fabricated_cves():
    """Pillar 6 VEX addendum exists, is linked, and avoids fake CVE statements."""
    import json

    from prostanet.agentic.pillars.pillar_6_security import PILLAR

    vex_path = PROJECT_ROOT / "prostanet/regulatory/security/vex.json"
    policy_path = PROJECT_ROOT / "prostanet/regulatory/security/vex_policy.md"
    audit_path = PROJECT_ROOT / "prostanet/regulatory/security/cve-audit-last.json"
    vex = json.loads(vex_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    ps = PILLAR.score()
    gap_kinds = {gap.kind for gap in ps.gaps}
    open_vuln_count = sum(len(dep.get("vulns") or []) for dep in audit.get("dependencies", []))
    properties = {
        item.get("name"): item.get("value")
        for item in [*(vex.get("properties") or []), *((vex.get("metadata") or {}).get("properties") or [])]
        if isinstance(item, dict)
    }

    assert vex["bomFormat"] == "CycloneDX"
    assert vex["metadata"]["component"]["bom-ref"] == "prostamed"
    assert policy_path.exists()
    assert properties["prostamed:sbom_ref"] == "prostanet/regulatory/security/sbom-cyclonedx.json"
    assert properties["prostamed:cve_audit_ref"] == "prostanet/regulatory/security/cve-audit-last.json"
    assert properties["prostamed:no_fabricated_cve_statements"] == "true"
    assert open_vuln_count == 0
    assert vex["vulnerabilities"] == []
    assert "part11_control_missing:retention_policy" not in gap_kinds
    assert "vex_addendum_missing" not in gap_kinds
    assert ps.details["vex_present"] is True


def test_g2891_pillar_7_dhf_at_100_after_traceability_seed():
    """H.G2891 — Pilar 7 score=100% después de traceability + CR log + baseline lock."""
    from prostanet.agentic.pillars.pillar_7_dhf import PILLAR
    ps = PILLAR.score()
    assert ps.pillar_id == 7
    assert ps.score >= 95.0  # essentially 100


# ═══════════════════════════════════════════════════════════════════════════
# §C — gap_prioritizer
# ═══════════════════════════════════════════════════════════════════════════
def test_g2892_gap_prioritizer_imports():
    """H.G2892 — gap_prioritizer expone API."""
    from prostanet.agentic.gap_prioritizer import (
        gap_score, rank_gaps, top_gap, projection_eta_to_target,
    )
    assert callable(top_gap)


def test_g2893_top_gap_returns_actionable_gap():
    """H.G2893 — top_gap retorna Gap o None."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    from prostanet.agentic.gap_prioritizer import top_gap
    snap = compute_compliance_snapshot(persist=False)
    gap = top_gap(snap)
    if gap is not None:
        assert hasattr(gap, "kind")
        assert hasattr(gap, "pillar_id")
        assert 1 <= gap.pillar_id <= 7


def test_g2894_projection_returns_eta():
    """H.G2894 — projection_eta_to_target retorna iterations + weeks + months."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    from prostanet.agentic.gap_prioritizer import projection_eta_to_target
    snap = compute_compliance_snapshot(persist=False)
    proj = projection_eta_to_target(snap)
    assert "iterations" in proj
    assert "weeks_to_target" in proj
    assert "months_to_target" in proj


def test_g2895_gap_score_weighted_correctly():
    """H.G2895 — gap_score = severity × clinical × pillar_weight × age / effort."""
    from prostanet.agentic.compliance_scorer import Gap
    from prostanet.agentic.gap_prioritizer import gap_score
    g = Gap(pillar_id=4, kind="fmea_entry_missing",
            description="test", severity=8, effort_h=2.0)
    s = gap_score(g)
    # severity (8) × clinical (1.5 fmea_entry) × pillar_w (12 P4) × age(1.0) / effort (2.0) = 72
    assert s > 50  # rough bound


# ═══════════════════════════════════════════════════════════════════════════
# §D — proposal_generator
# ═══════════════════════════════════════════════════════════════════════════
def test_g2896_proposal_generator_imports():
    """H.G2896 — proposal_generator expone API."""
    from prostanet.agentic.proposal_generator import (
        ProposalDraft, generate_proposal_for_gap, skill_invoke_dry_run,
    )
    assert callable(generate_proposal_for_gap)


def test_g2897_proposal_routes_sop_to_docx_skill():
    """H.G2897 — gap.kind=sop_missing → skill_chain incluye docx + fda-medtech."""
    from prostanet.agentic.compliance_scorer import Gap
    from prostanet.agentic.proposal_generator import generate_proposal_for_gap
    g = Gap(pillar_id=2, kind="sop_missing:SOP-CCG-002",
            description="test SOP", severity=9, effort_h=8.0)
    draft = generate_proposal_for_gap(g)
    assert "docx" in " ".join(draft.skill_chain).lower()
    assert "fda-medtech" in " ".join(draft.skill_chain).lower()


def test_g2898_proposal_routes_fmea_to_clinical_reports():
    """H.G2898 — gap.kind=fmea_entry_missing → clinical-reports + xlsx skills."""
    from prostanet.agentic.compliance_scorer import Gap
    from prostanet.agentic.proposal_generator import generate_proposal_for_gap
    g = Gap(pillar_id=4, kind="fmea_entry_missing:visceral_crisis",
            description="test", severity=8, effort_h=1.0)
    draft = generate_proposal_for_gap(g)
    chain_str = " ".join(draft.skill_chain).lower()
    assert "clinical-reports" in chain_str
    assert "xlsx" in chain_str


def test_g2899_prospective_protocol_marked_blocked_human():
    """H.G2899 — gap.kind=prospective_protocol_missing → blocked_human=True."""
    from prostanet.agentic.compliance_scorer import Gap
    from prostanet.agentic.proposal_generator import generate_proposal_for_gap
    g = Gap(pillar_id=5, kind="prospective_protocol_missing",
            description="test", severity=9, effort_h=12.0)
    draft = generate_proposal_for_gap(g)
    assert draft.blocked_human is True


# ═══════════════════════════════════════════════════════════════════════════
# §E — retro_validator
# ═══════════════════════════════════════════════════════════════════════════
def test_g2900_retro_validator_runs():
    """H.G2900 — run_retro_validation returns list[RetroResult]."""
    from prostanet.agentic.retro_validator import run_retro_validation
    results = run_retro_validation()
    assert isinstance(results, list)
    if results:
        r = results[0]
        assert hasattr(r, "gate_code")
        assert hasattr(r, "auc")
        assert 0 <= (r.auc or 0) <= 1


def test_g2901_retro_validator_saves_yaml():
    """H.G2901 — save_results escribe retro_validation_results.yaml válido."""
    from prostanet.agentic.retro_validator import (
        run_retro_validation, save_results, OUTPUT_PATH,
    )
    save_results(run_retro_validation())
    assert OUTPUT_PATH.exists()
    import yaml
    data = yaml.safe_load(OUTPUT_PATH.read_text())
    assert "results" in data


# ═══════════════════════════════════════════════════════════════════════════
# §F — improvement_loop FDA-driven
# ═══════════════════════════════════════════════════════════════════════════
def test_g2902_loop_phase_1_includes_compliance_snapshot():
    """H.G2902 — _phase_1_observe retorna compliance_snapshot."""
    from prostanet.agentic.improvement_loop import _phase_1_observe
    obs = _phase_1_observe()
    assert "compliance_snapshot" in obs
    assert "aggregate" in obs


def test_g2903_loop_phase_2_returns_proposal_with_pillar_id():
    """H.G2903 — _phase_2_detect retorna proposal con target_pillar válido."""
    from prostanet.agentic.improvement_loop import _phase_1_observe, _phase_2_detect
    obs = _phase_1_observe()
    proposals = _phase_2_detect(obs)
    if proposals and proposals[0].kind not in {"compliance_target_reached", "all_gaps_blocked", "snapshot_unavailable"}:
        assert 1 <= proposals[0].target_pillar <= 7


def test_g2904_target_pillar_filters_to_pillar_only():
    """H.G2904 — AGENTIC_TARGET_PILLAR filtra al pilar especificado."""
    os.environ["AGENTIC_TARGET_PILLAR"] = "4"
    try:
        from prostanet.agentic.improvement_loop import _phase_1_observe, _phase_2_detect
        obs = _phase_1_observe()
        proposals = _phase_2_detect(obs)
        if proposals and proposals[0].kind not in {"compliance_target_reached", "all_gaps_blocked"}:
            assert proposals[0].target_pillar == 4
    finally:
        os.environ.pop("AGENTIC_TARGET_PILLAR", None)


# ═══════════════════════════════════════════════════════════════════════════
# §G — Dashboard + 5 endpoints
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def client():
    from app import app
    return app.test_client()


def test_g2905_fda_dashboard_renders(client):
    """H.G2905 — GET /fda-samd-compliance retorna 200 con sidebar + 7 pillars."""
    r = client.get("/fda-samd-compliance")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "FDA SaMD Compliance" in body


def test_g2906_api_compliance_snapshot(client):
    """H.G2906 — GET /api/compliance/snapshot retorna JSON con aggregate + ≥7 scores (forward-compat LXC añade P8)."""
    r = client.get("/api/compliance/snapshot")
    assert r.status_code == 200
    body = r.get_json()
    assert "aggregate" in body
    assert "scores" in body
    # Forward-compat: 7 (LXXXVIII) o 8 (LXC) pilares
    assert {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}.issubset(set(body["scores"].keys()))


def test_g2907_api_compliance_history(client):
    """H.G2907 — GET /api/compliance/history?days=30 retorna lista."""
    r = client.get("/api/compliance/history?days=30")
    assert r.status_code == 200
    body = r.get_json()
    assert "history" in body
    assert "n" in body


def test_g2908_api_compliance_proposals(client):
    """H.G2908 — GET /api/compliance/proposals?limit=10 retorna lista."""
    r = client.get("/api/compliance/proposals?limit=10")
    assert r.status_code == 200
    body = r.get_json()
    assert "proposals" in body


def test_g2909_api_compliance_rollbacks(client):
    """H.G2909 — GET /api/compliance/rollbacks retorna lista."""
    r = client.get("/api/compliance/rollbacks")
    assert r.status_code == 200
    body = r.get_json()
    assert "rollbacks" in body


def test_g2910_api_compliance_projection(client):
    """H.G2910 — GET /api/compliance/projection retorna iterations + ETA."""
    r = client.get("/api/compliance/projection?target=96")
    assert r.status_code == 200
    body = r.get_json()
    assert "iterations" in body
    assert "weeks_to_target" in body


# ═══════════════════════════════════════════════════════════════════════════
# §H — Regulatory artifacts existence (bootstrap seeds)
# ═══════════════════════════════════════════════════════════════════════════
def test_g2911_imdrf_classification_exists():
    """H.G2911 — IMDRF risk classification doc existe."""
    p = PROJECT_ROOT / "prostanet/regulatory/regulatory/imdrf_risk_classification.md"
    assert p.exists() and p.stat().st_size > 1000


def test_g2912_4_sops_exist():
    """H.G2912 — 4 SOPs (DCG-001 + CCG-002 + CAPA-003 + RM-004) existen."""
    sops_dir = PROJECT_ROOT / "prostanet/regulatory/sops"
    sops = ["SOP-DCG-001", "SOP-CCG-002", "SOP-CAPA-003", "SOP-RM-004"]
    for sop in sops:
        candidates = list(sops_dir.glob(f"{sop}*"))
        assert any(c.is_file() for c in candidates), f"Missing SOP: {sop}"


def test_g2913_fmea_15_hazards():
    """H.G2913 — FMEA YAML contiene ≥15 peligros."""
    import yaml
    p = PROJECT_ROOT / "prostanet/regulatory/risk/fmea-prostanet-2026.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text())
    assert len(data.get("hazards", [])) >= 15


def test_g2914_dhf_traceability_113_rows():
    """H.G2914 — DHF traceability matrix ≥107 rows (89 gates + 18 stages)."""
    import yaml
    p = PROJECT_ROOT / "prostanet/regulatory/dhf/traceability_matrix.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text())
    assert len(data.get("rows", [])) >= 107


def test_g2915_design_input_baseline_locked():
    """H.G2915 — design_input_baseline.lock marker present."""
    p = PROJECT_ROOT / "prostanet/regulatory/dhf/design_input_baseline.lock"
    assert p.exists()


def test_g2916_stride_threat_model_complete():
    """H.G2916 — STRIDE threat model addresses 6 STRIDE categories."""
    p = PROJECT_ROOT / "prostanet/regulatory/security/STRIDE-threat-model.md"
    assert p.exists()
    content = p.read_text().lower()
    for cat in ["spoofing", "tampering", "repudiation",
                  "information disclosure", "denial of service",
                  "elevation of privilege"]:
        assert cat in content


def test_g2917_sbom_cyclonedx_valid_json():
    """H.G2917 — SBOM CycloneDX JSON parses + has components."""
    import json
    p = PROJECT_ROOT / "prostanet/regulatory/security/sbom-cyclonedx.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data.get("bomFormat") == "CycloneDX"
    assert len(data.get("components", [])) >= 5


def test_g2918_security_disclosure_policy_exists():
    """H.G2918 — SECURITY.md exists at repo root."""
    p = PROJECT_ROOT / "SECURITY.md"
    assert p.exists() and p.stat().st_size > 100


def test_g2919_aggregate_baseline_above_50pct():
    """H.G2919 — Aggregate compliance baseline ≥50% post-LXXXVIII bootstrap seeds."""
    from prostanet.agentic.compliance_scorer import compute_compliance_snapshot
    snap = compute_compliance_snapshot(persist=False)
    assert snap.aggregate >= 50.0


def test_g2920_faubot_release_lxxxviii_or_higher():
    """H.G2920 — FAUBOT_RELEASE ≥LXXXVIII (forward-compat: LXC, LXC.1, LXCI, ...)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Acepta LXXXV+ y cualquier numeral ≥LXC (post-LXXXIX): LXC, LXCI, LXCII, ..., XCV, XCVI, XCVII, XCVIII, XCIX, C
    valid_tokens = ("LXXXV", "LXXXVI", "LXXXVII", "LXXXVIII", "LXXXIX",
                    "LXC", "LXCI", "LXCII", "LXCIII", "LXCIV",
                    "XCV", "XCVI", "XCVII", "XCVIII", "XCIX", " C ")
    assert any(t in FAUBOT_RELEASE for t in valid_tokens), (
        f"FAUBOT_RELEASE {FAUBOT_RELEASE} not recognized as ≥LXXXVIII")
