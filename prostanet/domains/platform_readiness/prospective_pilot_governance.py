"""Read-only governance pack for a prospective local ProstaMed pilot.

This layer translates the platform readiness chain into an institutional pilot
packet. It does not mutate clinical facts, place orders, train models or
transfer data. The intent is to make the next deployment step explicit:
clinical data quality plus NAS/local-operation governance.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.platform_readiness.audit import build_platform_readiness_audit
from prostanet.domains.platform_readiness.deidentified_export_contract import (
    build_deidentified_export_contract,
)
from prostanet.domains.platform_readiness.interoperability_map import build_interoperability_map
from prostanet.domains.platform_readiness.ledger_persistence_matrix import (
    build_ledger_persistence_matrix,
)
from prostanet.domains.platform_readiness.ledger_release_gate import build_ledger_release_gate
from prostanet.domains.platform_readiness.nas_pilot_evidence_vault import (
    build_nas_pilot_evidence_vault,
    latest_gate_status_from_vault,
)
from prostanet.domains.platform_readiness.research_pack_governance import (
    build_research_pack_freeze_library,
)
from prostanet.domains.platform_readiness.research_pack_materializer import (
    build_research_pack_materializer,
)
from prostanet.shared.utc_time import utc_now_iso


PROSPECTIVE_PILOT_GOVERNANCE_VERSION = "prospective_pilot_governance_pack_v1"

NAS_VISION_SOURCE = {
    "source_label": "Sistema NAS Urologia.docx",
    "source_path": "/Users/oscaralvarado/Downloads/Sistema NAS Urologia.docx",
    "institutional_frame": "HE CMN La Raza Urology local clinical-data infrastructure",
    "primary_platform": "ProstaMed",
    "future_platform_extension": "Uromed",
}

PILOT_GATE_ORDER = (
    "clinical_fact_ledger",
    "v2_persistence_matrix",
    "no_recapture_contract",
    "interoperability_map",
    "deidentified_export_contract",
    "research_pack_freeze_library",
    "epidemiology_snapshot_reproducibility",
    "clinical_use_boundary",
    "nas_local_operations",
    "backup_restore_drill",
    "access_control_roles",
    "consent_and_data_use",
    "training_and_adoption",
    "incident_response_contingency",
    "prospective_protocol_approval",
)


def build_prospective_pilot_governance_pack(
    registry: ModuleRegistry | None = None,
    *,
    registered_rules: Iterable[Any] | None = None,
    scope: str = "summary",
    limit: int = 80,
    readiness_audit: Mapping[str, Any] | None = None,
    ledger_release_gate: Mapping[str, Any] | None = None,
    ledger_persistence_matrix: Mapping[str, Any] | None = None,
    interoperability_map: Mapping[str, Any] | None = None,
    deidentified_export_contract: Mapping[str, Any] | None = None,
    research_pack_materializer: Mapping[str, Any] | None = None,
    research_pack_freeze_library: Mapping[str, Any] | None = None,
    epidemiology_snapshot_library: Mapping[str, Any] | None = None,
    nas_pilot_evidence_vault: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the read-only pilot-governance readiness packet."""
    registry = registry or ModuleRegistry()
    scope_key = "summary" if str(scope or "").strip().lower() == "summary" else "full"
    safe_limit = max(1, min(int(limit or 80), 500))
    registered_rule_list = list(registered_rules or [])

    audit = dict(
        readiness_audit
        or build_platform_readiness_audit(
            registry,
            registered_rules=registered_rule_list,
            scope="summary",
            field_limit=300,
        )
    )
    ledger_gate = dict(
        ledger_release_gate
        or build_ledger_release_gate(
            registry,
            registered_rules=registered_rule_list,
            scope="summary",
            field_limit=300,
            readiness_audit=audit,
        )
    )
    persistence_matrix = dict(
        ledger_persistence_matrix
        or build_ledger_persistence_matrix(
            registry,
            registered_rules=registered_rule_list,
            scope="summary",
            row_limit=500,
            release_gate=ledger_gate,
        )
    )
    interop = dict(
        interoperability_map
        or build_interoperability_map(scope="summary", field_limit=300)
    )
    export_contract = dict(
        deidentified_export_contract
        or build_deidentified_export_contract(scope="summary", limit=safe_limit)
    )
    materializer = dict(
        research_pack_materializer
        or build_research_pack_materializer(scope="summary", limit=safe_limit)
    )
    freeze_library = dict(
        research_pack_freeze_library
        or build_research_pack_freeze_library(
            limit=25,
            include_payload=False,
            include_current_preview=False,
        )
    )
    snapshot_library = dict(
        epidemiology_snapshot_library
        or _safe_snapshot_library(limit=10, include_payload=False)
    )
    evidence_vault = dict(
        nas_pilot_evidence_vault
        or build_nas_pilot_evidence_vault(scope="summary", limit=100)
    )

    gate_matrix = _build_gate_matrix(
        audit=audit,
        ledger_gate=ledger_gate,
        persistence_matrix=persistence_matrix,
        interop=interop,
        export_contract=export_contract,
        materializer=materializer,
        freeze_library=freeze_library,
        snapshot_library=snapshot_library,
        evidence_vault=evidence_vault,
    )
    summary = _build_summary(gate_matrix, freeze_library, snapshot_library, evidence_vault)
    required_actions = _build_required_actions(gate_matrix)
    manifest = _build_pilot_packet_manifest(freeze_library, snapshot_library)

    payload: dict[str, Any] = {
        "available": True,
        "source": "prostanet_prospective_pilot_governance",
        "version": PROSPECTIVE_PILOT_GOVERNANCE_VERSION,
        "computed_at": utc_now_iso(),
        "scope": scope_key,
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "ready_for_external_deployment": False,
        "nas_vision_source": dict(NAS_VISION_SOURCE),
        "summary": summary,
        "gate_matrix": gate_matrix,
        "required_actions": required_actions,
        "nas_pilot_evidence_vault": evidence_vault,
        "pilot_packet_manifest": manifest,
        "protocol_summary": {
            "pilot_name": "ProstaMed local prospective prostate-cancer data pilot",
            "setting": "Urology service local/NAS deployment",
            "use_boundary": "Clinical decision support, audit and research readiness only; no autonomous orders.",
            "primary_success_metric": "Prospective capture adherence with no-recapture and V2 persistence gates green.",
        },
    }
    if scope_key == "full":
        payload.update(
            {
                "protocol_outline": _build_protocol_outline(),
                "responsibility_matrix": _build_responsibility_matrix(),
                "nas_operational_readiness": _build_nas_operational_readiness(),
                "adoption_milestones": _build_adoption_milestones(),
                "risk_register": _build_risk_register(),
                "training_plan": _build_training_plan(),
                "consent_and_data_use": _build_consent_and_data_use(),
                "evidence_bindings": _build_evidence_bindings(
                    audit,
                    ledger_gate,
                    persistence_matrix,
                    interop,
                    export_contract,
                    materializer,
                    freeze_library,
                    snapshot_library,
                ),
            }
        )
    return payload


def _build_gate_matrix(
    *,
    audit: Mapping[str, Any],
    ledger_gate: Mapping[str, Any],
    persistence_matrix: Mapping[str, Any],
    interop: Mapping[str, Any],
    export_contract: Mapping[str, Any],
    materializer: Mapping[str, Any],
    freeze_library: Mapping[str, Any],
    snapshot_library: Mapping[str, Any],
    evidence_vault: Mapping[str, Any],
) -> list[dict[str, Any]]:
    audit_summary = audit.get("summary") or {}
    ledger_summary = ledger_gate.get("summary") or {}
    matrix_summary = persistence_matrix.get("summary") or {}
    interop_summary = interop.get("summary") or {}
    export_summary = export_contract.get("summary") or {}
    pack_summary = materializer.get("summary") or {}
    freeze_summary = freeze_library.get("summary") or {}
    snapshot_summary = snapshot_library.get("summary") or {}

    clinical_boundary_pass = all(
        _flag_false(payload, key)
        for payload in (
            audit,
            ledger_gate,
            persistence_matrix,
            interop,
            export_contract,
            materializer,
            freeze_library,
            snapshot_library,
        )
        for key in (
            "source_clinical_facts_mutated",
            "external_order_created",
            "model_trained",
            "external_transfer_performed",
        )
    )
    snapshot_freezes = snapshot_library.get("freezes") or []
    approved_snapshot_count = sum(
        1
        for item in snapshot_freezes
        if str(item.get("approval_status") or "").lower()
        in {"human_reviewed", "approved_internal_audit", "approved_research_use"}
    )
    reproduction_ready_count = sum(
        1
        for item in snapshot_freezes
        if item.get("reproduction_pack_download_url")
    )
    nas_local_status = _operational_gate_status(
        evidence_vault,
        "nas_local_operations",
        env_pass=_env_truthy("PROSTANET_NAS_DEPLOYMENT_READY"),
        env_evidence=_nas_env_evidence(),
        fallback_action="Document Docker compose, static IP/firewall boundary, UPS, RAID/SMART health and local health checks.",
    )
    backup_status = _operational_gate_status(
        evidence_vault,
        "backup_restore_drill",
        env_pass=bool(os.environ.get("PROSTANET_BACKUP_RESTORE_DRILL_AT")),
        env_evidence=os.environ.get("PROSTANET_BACKUP_RESTORE_DRILL_AT") or "restore drill date not documented",
        fallback_action="Record the latest successful restore drill and backup target before prospective enrollment.",
    )
    role_status = _operational_gate_status(
        evidence_vault,
        "access_control_roles",
        env_pass=_env_truthy("CLINICAL_AUTH_ENABLED"),
        env_evidence=f"CLINICAL_AUTH_ENABLED={os.environ.get('CLINICAL_AUTH_ENABLED', 'false')}",
        fallback_action="Enable clinical auth and map jefe/adscrito/residente/investigador/auditor roles for pilot use.",
    )
    consent_status = _operational_gate_status(
        evidence_vault,
        "consent_and_data_use",
        env_pass=_env_truthy("PROSTANET_PILOT_CONSENT_APPROVED"),
        env_evidence=f"PROSTANET_PILOT_CONSENT_APPROVED={os.environ.get('PROSTANET_PILOT_CONSENT_APPROVED', 'false')}",
        fallback_action="Attach approved consent/privacy notice and ARCO workflow to the pilot packet.",
    )
    training_status = _operational_gate_status(
        evidence_vault,
        "training_and_adoption",
        env_pass=_env_truthy("PROSTANET_PILOT_TRAINING_COMPLETE"),
        env_evidence=f"PROSTANET_PILOT_TRAINING_COMPLETE={os.environ.get('PROSTANET_PILOT_TRAINING_COMPLETE', 'false')}",
        fallback_action="Schedule training, capture attendance and publish capture-adherence targets.",
    )
    incident_status = _operational_gate_status(
        evidence_vault,
        "incident_response_contingency",
        env_pass=_env_truthy("PROSTANET_INCIDENT_RESPONSE_APPROVED"),
        env_evidence=f"PROSTANET_INCIDENT_RESPONSE_APPROVED={os.environ.get('PROSTANET_INCIDENT_RESPONSE_APPROVED', 'false')}",
        fallback_action="Document incident response, power-loss procedure and fallback downtime capture.",
    )
    protocol_status = _operational_gate_status(
        evidence_vault,
        "prospective_protocol_approval",
        env_pass=_env_truthy("PROSTANET_PROSPECTIVE_PROTOCOL_APPROVED"),
        env_evidence=f"PROSTANET_PROSPECTIVE_PROTOCOL_APPROVED={os.environ.get('PROSTANET_PROSPECTIVE_PROTOCOL_APPROVED', 'false')}",
        fallback_action="Approve protocol with inclusion/exclusion, endpoints, use boundary, success metrics and cadence.",
    )

    gates = [
        _gate(
            "clinical_fact_ledger",
            "Clinical Fact Ledger release gate",
            "clinical_data_quality",
            _pass_if(ledger_summary.get("next_layer_allowed")),
            "Clinical Fact Ledger gate must be green before a prospective pilot.",
            "urology_oncology_data_owner",
            evidence=f"{ledger_summary.get('pass_count', 0)} pass, {ledger_summary.get('watch_count', 0)} watch, {ledger_summary.get('block_count', 0)} block",
            next_action="Close any Ledger block before pilot enrollment.",
            pilot_blocking=True,
        ),
        _gate(
            "v2_persistence_matrix",
            "V2 fact-flow persistence matrix",
            "clinical_data_quality",
            _pass_if(matrix_summary.get("next_layer_allowed")),
            "V2 flows must preserve fact lineage from capture to profile, decision, schedule and cohorts.",
            "platform_quality_owner",
            evidence=f"{matrix_summary.get('flow_pass_count', 0)} flow pass, {matrix_summary.get('flow_block_count', 0)} block",
            next_action="Resolve any fact-flow block in wizard/intake/profile/decision/cohort surfaces.",
            pilot_blocking=True,
        ),
        _gate(
            "no_recapture_contract",
            "No-recapture and alias normalization",
            "clinical_data_quality",
            _status_for_no_recapture(audit_summary, ledger_summary),
            "Facts should be reused through aliases/derivations instead of asking the clinician twice.",
            "clinical_fact_steward",
            evidence=f"same-module recapture {audit_summary.get('same_module_recapture_count', 0)}, recapture watches {ledger_summary.get('recapture_watch_count', 0)}",
            next_action="Normalize any new alias into the Ledger before adding fields.",
            pilot_blocking=True,
        ),
        _gate(
            "interoperability_map",
            "mCODE/OMOP critical fact map",
            "interoperability",
            _pass_if(interop_summary.get("next_layer_allowed")),
            "Critical facts need target semantics before multi-system or multi-site work.",
            "interoperability_owner",
            evidence=f"{interop_summary.get('critical_ready_count', 0)}/{interop_summary.get('critical_fact_count', 0)} critical facts ready",
            next_action="Map or intentionally defer any critical unmapped fact.",
            pilot_blocking=True,
        ),
        _gate(
            "deidentified_export_contract",
            "No-PHI de-identified export contract",
            "research_governance",
            _pass_if(export_summary.get("next_layer_allowed")),
            "Pilot reporting must prove no direct NSS/name/DOB/patient_id leakage in research artifacts.",
            "privacy_data_steward",
            evidence=f"{export_summary.get('direct_identifier_key_count', 0)} identifier keys, {export_summary.get('exact_phi_hit_count', 0)} exact PHI hits",
            next_action="Block downloads/freezes until the no-PHI scan and interop dictionary pass.",
            pilot_blocking=True,
        ),
        _gate(
            "research_pack_freeze_library",
            "Governed de-identified freeze library",
            "research_governance",
            _pass_watch(bool(freeze_summary.get("download_ready_count"))),
            "The pilot should have at least one governed, downloadable baseline pack.",
            "research_governance_owner",
            evidence=f"{freeze_summary.get('freeze_count', 0)} freezes, {freeze_summary.get('download_ready_count', 0)} download-ready",
            next_action="Create a governed baseline dxpack freeze from Platform Readiness.",
            pilot_blocking=False,
        ),
        _gate(
            "epidemiology_snapshot_reproducibility",
            "Snapshot and statistical reproduction pack",
            "research_governance",
            _pass_watch(bool(snapshot_summary.get("freeze_count")) and reproduction_ready_count > 0),
            "The epidemiology dashboard should produce a signed snapshot and local reproduction pack.",
            "biostatistics_owner",
            evidence=f"{snapshot_summary.get('freeze_count', 0)} snapshots, {reproduction_ready_count} reproduction links, {approved_snapshot_count} human-reviewed",
            next_action="Freeze one snapshot with human review and verify reproduction-pack download.",
            pilot_blocking=False,
        ),
        _gate(
            "clinical_use_boundary",
            "Clinical use boundary",
            "safety",
            "pass" if clinical_boundary_pass else "block",
            "The pilot must remain CDS/audit/research readiness; no autonomous orders or model training.",
            "clinical_safety_owner",
            evidence="All readiness packets declare no source mutation, no external orders, no model training and no external transfer.",
            next_action="Keep all pilot endpoints read-only unless a separate signed clinical protocol permits mutation.",
            pilot_blocking=True,
        ),
        _gate(
            "nas_local_operations",
            "NAS/local deployment operations",
            "nas_operations",
            nas_local_status["status"],
            "The NAS proposal requires local operation, Docker readiness, IP/firewall review, UPS and RAID/SMART monitoring.",
            "it_nas_owner",
            evidence=nas_local_status["evidence"],
            next_action=nas_local_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "backup_restore_drill",
            "Backup and restore drill",
            "nas_operations",
            backup_status["status"],
            "RAID 1 is not a backup; the pilot needs daily backup plus restore proof.",
            "it_nas_owner",
            evidence=backup_status["evidence"],
            next_action=backup_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "access_control_roles",
            "Role-based clinical access",
            "security",
            role_status["status"],
            "The NAS proposal requires unique credentials and role-specific permissions.",
            "security_owner",
            evidence=role_status["evidence"],
            next_action=role_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "consent_and_data_use",
            "Consent, privacy notice and data-use boundary",
            "ethics_governance",
            consent_status["status"],
            "The prospective pilot needs documented patient notice/consent path and ARCO response plan.",
            "ethics_privacy_owner",
            evidence=consent_status["evidence"],
            next_action=consent_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "training_and_adoption",
            "Training and adoption plan",
            "operations",
            training_status["status"],
            "The NAS plan expects training for attendings, senior residents and junior residents.",
            "clinical_operations_owner",
            evidence=training_status["evidence"],
            next_action=training_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "incident_response_contingency",
            "Incident response and downtime contingency",
            "security",
            incident_status["status"],
            "A local clinical-data platform needs a documented response to PHI incidents, power loss and NAS failure.",
            "security_owner",
            evidence=incident_status["evidence"],
            next_action=incident_status["next_action"],
            pilot_blocking=False,
        ),
        _gate(
            "prospective_protocol_approval",
            "Prospective protocol approval",
            "ethics_governance",
            protocol_status["status"],
            "The pilot packet should be signed by clinical leadership before prospective use.",
            "principal_investigator",
            evidence=protocol_status["evidence"],
            next_action=protocol_status["next_action"],
            pilot_blocking=False,
        ),
    ]
    order = {key: index for index, key in enumerate(PILOT_GATE_ORDER)}
    return sorted(gates, key=lambda item: order.get(item["gate_key"], 999))


def _gate(
    gate_key: str,
    label: str,
    family: str,
    status: str,
    rationale: str,
    owner: str,
    *,
    evidence: str,
    next_action: str,
    pilot_blocking: bool,
) -> dict[str, Any]:
    status_key = status if status in {"pass", "watch", "block"} else "watch"
    return {
        "gate_key": gate_key,
        "label": label,
        "family": family,
        "status": status_key,
        "pilot_blocking": bool(pilot_blocking),
        "rationale": rationale,
        "owner": owner,
        "evidence": evidence,
        "next_action": next_action,
    }


def _build_summary(
    gate_matrix: list[Mapping[str, Any]],
    freeze_library: Mapping[str, Any],
    snapshot_library: Mapping[str, Any],
    evidence_vault: Mapping[str, Any],
) -> dict[str, Any]:
    pass_count = sum(1 for gate in gate_matrix if gate.get("status") == "pass")
    watch_count = sum(1 for gate in gate_matrix if gate.get("status") == "watch")
    block_count = sum(1 for gate in gate_matrix if gate.get("status") == "block")
    pilot_block_count = sum(
        1
        for gate in gate_matrix
        if gate.get("status") == "block" and gate.get("pilot_blocking")
    )
    gate_count = len(gate_matrix)
    score = round((pass_count / gate_count) * 100, 1) if gate_count else 0.0
    pilot_ready = pilot_block_count == 0
    if not pilot_ready:
        pilot_status = "pilot_blocked"
    elif watch_count:
        pilot_status = "ready_for_internal_prospective_pilot_with_watches"
    else:
        pilot_status = "ready_for_internal_prospective_pilot"
    freeze_summary = freeze_library.get("summary") or {}
    snapshot_summary = snapshot_library.get("summary") or {}
    vault_summary = evidence_vault.get("summary") or {}
    return {
        "pilot_status": pilot_status,
        "pilot_gate_score": score,
        "gate_count": gate_count,
        "pass_count": pass_count,
        "watch_count": watch_count,
        "block_count": block_count,
        "pilot_block_count": pilot_block_count,
        "ready_for_internal_prospective_pilot": pilot_ready,
        "ready_for_external_deployment": False,
        "nas_operations_watch_count": sum(
            1
            for gate in gate_matrix
            if gate.get("family") == "nas_operations" and gate.get("status") == "watch"
        ),
        "security_watch_count": sum(
            1
            for gate in gate_matrix
            if gate.get("family") in {"security", "ethics_governance"} and gate.get("status") == "watch"
        ),
        "research_freeze_count": int(freeze_summary.get("freeze_count") or 0),
        "research_download_ready_count": int(freeze_summary.get("download_ready_count") or 0),
        "epidemiology_snapshot_count": int(snapshot_summary.get("freeze_count") or 0),
        "operational_evidence_record_count": int(vault_summary.get("evidence_record_count") or 0),
        "operational_evidence_verified_gate_count": int(vault_summary.get("verified_gate_count") or 0),
        "operational_evidence_completion_pct": float(vault_summary.get("completion_pct") or 0),
        "source_document_integrated": True,
        "clinical_data_chain_ready": pilot_ready,
    }


def _build_required_actions(gate_matrix: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    severity_rank = {"block": 0, "watch": 1, "pass": 2}
    actions = []
    for gate in gate_matrix:
        status = str(gate.get("status") or "watch")
        if status == "pass":
            continue
        actions.append(
            {
                "gate_key": gate.get("gate_key"),
                "priority": "critical" if status == "block" and gate.get("pilot_blocking") else "watch",
                "owner": gate.get("owner"),
                "title": gate.get("label"),
                "why": gate.get("rationale"),
                "action": gate.get("next_action"),
                "status": status,
                "route": _route_for_gate(str(gate.get("gate_key") or "")),
            }
        )
    return sorted(actions, key=lambda item: (severity_rank.get(item["status"], 9), item["gate_key"]))


def _build_pilot_packet_manifest(
    freeze_library: Mapping[str, Any],
    snapshot_library: Mapping[str, Any],
) -> list[dict[str, Any]]:
    freezes = freeze_library.get("freezes") or []
    snapshots = snapshot_library.get("freezes") or []
    latest_freeze = freezes[0] if freezes else {}
    latest_snapshot = snapshots[0] if snapshots else {}
    manifest = [
        {
            "component": "Platform Readiness",
            "kind": "readiness_dashboard",
            "url": "/platform-readiness",
            "required": True,
        },
        {
            "component": "Ledger Release Gate",
            "kind": "json_contract",
            "url": "/api/platform-readiness/ledger-release-gate?scope=full",
            "required": True,
        },
        {
            "component": "V2 Persistence Matrix",
            "kind": "json_contract",
            "url": "/api/platform-readiness/ledger-persistence-matrix?scope=full",
            "required": True,
        },
        {
            "component": "De-identified Export Contract",
            "kind": "json_contract",
            "url": "/api/platform-readiness/deidentified-export-contract?scope=full",
            "required": True,
        },
        {
            "component": "Research Pack Library",
            "kind": "freeze_library",
            "url": "/api/platform-readiness/research-pack-materializer/freezes",
            "required": True,
        },
        {
            "component": "Epidemiology Snapshot Library",
            "kind": "freeze_library",
            "url": "/api/analytics/epidemiology-command-center/snapshot-pack/freezes",
            "required": False,
        },
    ]
    if latest_freeze:
        manifest.append(
            {
                "component": "Latest de-identified dxpack",
                "kind": "download",
                "url": latest_freeze.get("download_url"),
                "freeze_key": latest_freeze.get("freeze_key"),
                "required": False,
            }
        )
    if latest_snapshot:
        manifest.append(
            {
                "component": "Latest epidemiology reproduction pack",
                "kind": "download",
                "url": latest_snapshot.get("reproduction_pack_download_url"),
                "freeze_key": latest_snapshot.get("freeze_key"),
                "required": False,
            }
        )
    return manifest


def _build_protocol_outline() -> dict[str, Any]:
    return {
        "pilot_name": "ProstaMed local prospective prostate-cancer registry and CDS audit pilot",
        "clinical_scope": [
            "Suspected prostate cancer diagnostic workup",
            "Localized or regional initial diagnosis",
            "Post-prostatectomy or post-radiotherapy surveillance",
            "mCSPC, m0 CRPC and m1 CRPC treatment-course tracking",
        ],
        "inclusion_criteria": [
            "Adult male patients evaluated by the urology service with suspected or confirmed prostate cancer.",
            "Patients with longitudinal PSA, staging, pathology, treatment or follow-up data captured during routine care.",
            "Patients whose data use follows the local privacy notice, consent or institutional waiver path.",
        ],
        "exclusion_criteria": [
            "Patients who request exclusion from secondary analysis where applicable.",
            "Records with unresolved direct PHI leakage in research outputs.",
            "Clinical use outside prostate-cancer pilot lanes until Uromed expansion is approved.",
        ],
        "primary_endpoints": [
            "Prospective capture adherence",
            "No-recapture score and V2 persistence pass rate",
            "Time from diagnostic suspicion to histology and treatment decision",
            "NCCN-aligned decision documentation rate",
        ],
        "secondary_endpoints": [
            "PSA50/PSA90 at 12 and 24 weeks",
            "Treatment persistence and discontinuation",
            "ECOG change, grade 3+ toxicity, hospitalizations and skeletal events",
            "ARPI/taxane/PARP/RLT cost-response metrics where data are complete",
            "Academic outputs: thesis, abstract, poster, manuscript and internal report count",
        ],
        "use_boundary": [
            "Decision support and audit only.",
            "No autonomous orders.",
            "No external data transfer by default.",
            "No model training without separate governance.",
            "Human clinician remains responsible for treatment decisions.",
        ],
        "review_cadence": "Weekly data-quality huddle in months 1-3, monthly institutional report after month 3.",
    }


def _build_responsibility_matrix() -> list[dict[str, str]]:
    return [
        {
            "role": "principal_investigator",
            "owner": "uro-oncology clinical lead",
            "responsibility": "Approve protocol, clinical scope, endpoints and safety boundaries.",
        },
        {
            "role": "urology_service_chief",
            "owner": "service leadership",
            "responsibility": "Authorize pilot use, assign staff, review institutional reports.",
        },
        {
            "role": "data_steward",
            "owner": "clinical fact steward",
            "responsibility": "Maintain Ledger dictionary, aliases, provenance and no-recapture contracts.",
        },
        {
            "role": "it_nas_owner",
            "owner": "local IT or delegated NAS administrator",
            "responsibility": "Maintain Docker/NAS, RAID/SMART, UPS, backups, restore drills and firewall boundary.",
        },
        {
            "role": "privacy_security_owner",
            "owner": "privacy/security officer",
            "responsibility": "Maintain access control, audit logs, incident response and data-use boundaries.",
        },
        {
            "role": "research_governance_owner",
            "owner": "research coordinator",
            "responsibility": "Approve freezes, methodology notes, human signatures and publication readiness.",
        },
        {
            "role": "biostatistics_owner",
            "owner": "statistics/research lead",
            "responsibility": "Validate snapshot reproduction, suppression, methodology versions and analysis plans.",
        },
    ]


def _build_nas_operational_readiness() -> dict[str, Any]:
    return {
        "source": dict(NAS_VISION_SOURCE),
        "deployment_target": "Local NAS/Docker inside institutional network",
        "must_have_controls": [
            "RAID 1 configured and monitored",
            "Daily backup to independent media",
            "Periodic restore drill",
            "UPS with ordered shutdown procedure",
            "Static IP and firewall boundary documented",
            "Role-based users with unique credentials",
            "Audit logs retained and exportable",
            "No default external transfer of PHI",
        ],
        "environment_flags": {
            "PROSTANET_NAS_DEPLOYMENT_READY": os.environ.get("PROSTANET_NAS_DEPLOYMENT_READY", "false"),
            "PROSTANET_BACKUP_RESTORE_DRILL_AT": os.environ.get("PROSTANET_BACKUP_RESTORE_DRILL_AT", ""),
            "CLINICAL_AUTH_ENABLED": os.environ.get("CLINICAL_AUTH_ENABLED", "false"),
        },
        "readiness_note": "These controls are operational evidence items; absence is a pilot watch, not a clinical logic failure.",
    }


def _build_adoption_milestones() -> list[dict[str, Any]]:
    return [
        {
            "window": "0-3 months",
            "targets": {
                "platform_operational": True,
                "personnel_trained_pct": 100,
                "prostate_cancer_patients": "80-120",
                "total_patients": "180-270",
                "prospective_capture_adherence_pct": ">=85 by month 3",
                "first_epidemiology_report": True,
            },
        },
        {
            "window": "4-6 months",
            "targets": {
                "prostate_cancer_patients": "180-260",
                "total_patients": "380-560",
                "prospective_capture_adherence_pct": ">=90",
                "median_variables_per_patient": ">=20",
                "active_dashboards": "2-3",
                "active_thesis_protocols": "3-5",
            },
        },
        {
            "window": "7-12 months",
            "targets": {
                "prostate_cancer_patients": "360-500",
                "total_patients": "760-1100",
                "prostamed_on_nas": True,
                "active_dashboards": "4-6",
                "submitted_articles": "2-3",
                "conference_presentations": "4-6",
            },
        },
        {
            "window": "12-24 months",
            "targets": {
                "prostate_cancer_patients": "700-1000",
                "total_patients": "1500-2200",
                "validated_ai_models": "2-4",
                "uromed_operational": "beta_to_mature",
                "national_reference_positioning": True,
            },
        },
    ]


def _build_risk_register() -> list[dict[str, str]]:
    return [
        {
            "risk": "Incomplete or inconsistent capture",
            "impact": "Weakens longitudinal evidence and clinical decision support.",
            "mitigation": "Short V2 forms, Ledger prefill/no-recapture, weekly quality review and capture-completeness tower.",
        },
        {
            "risk": "NAS disk, UPS or power failure",
            "impact": "May interrupt service or corrupt data if backups/UPS are not verified.",
            "mitigation": "RAID 1, SMART alerts, UPS test, daily backup and restore drill documentation.",
        },
        {
            "risk": "Privacy or PHI leakage",
            "impact": "High institutional/legal risk for sensitive health data.",
            "mitigation": "Role-based access, no-PHI export contract, audit logs, incident response and no external transfer by default.",
        },
        {
            "risk": "Misuse as autonomous treatment engine",
            "impact": "Unsafe clinical automation beyond v1 protocol.",
            "mitigation": "Explicit CDS boundary, human approval and no external orders/model training flags.",
        },
        {
            "risk": "Resistance to workflow change",
            "impact": "Low adoption despite strong software capability.",
            "mitigation": "Training, champions, quick feedback, adoption metrics and visible reduction in repeated data entry.",
        },
    ]


def _build_training_plan() -> list[dict[str, str]]:
    return [
        {
            "audience": "attendings",
            "duration": "2 hours",
            "content": "V2 profile, Decision Hoy, redecision closure, audit and research outputs.",
        },
        {
            "audience": "senior_residents",
            "duration": "2 hours",
            "content": "Prospective capture, longitudinal PSA/treatment entry, cohort completeness and freezes.",
        },
        {
            "audience": "junior_residents",
            "duration": "2 hours",
            "content": "Structured intake, no-recapture workflow, missing fields and confidentiality rules.",
        },
        {
            "audience": "research_team",
            "duration": "2 hours",
            "content": "Snapshot governance, reproduction packs, no-PHI exports and methodology notes.",
        },
    ]


def _build_consent_and_data_use() -> dict[str, Any]:
    return {
        "required_items": [
            "Local privacy notice or consent pathway for prospective registry use",
            "ARCO/request response process",
            "Data-use boundary: local care, quality audit and approved research",
            "No external transfer without separate approval",
            "Human approval before publication-ready snapshots",
        ],
        "default_boundary": "Internal clinical care, quality improvement and governed de-identified research readiness.",
        "external_use_policy": "Publication, multicenter sharing or vendor transfer requires separate approval and no-PHI package review.",
    }


def _build_evidence_bindings(*payloads: Mapping[str, Any]) -> list[dict[str, Any]]:
    bindings = []
    for payload in payloads:
        if not payload:
            continue
        bindings.append(
            {
                "source": payload.get("source") or payload.get("registry_type") or payload.get("version"),
                "version": payload.get("version"),
                "computed_at": payload.get("computed_at"),
                "read_only": bool(payload.get("read_only", True)),
                "source_clinical_facts_mutated": bool(payload.get("source_clinical_facts_mutated", False)),
                "external_order_created": bool(payload.get("external_order_created", False)),
                "model_trained": bool(payload.get("model_trained", False)),
                "external_transfer_performed": bool(payload.get("external_transfer_performed", False)),
            }
        )
    return bindings


def _safe_snapshot_library(*, limit: int, include_payload: bool) -> dict[str, Any]:
    try:
        from prostanet.domains.population_intelligence.epidemiology_metric_snapshot import (
            list_epidemiology_metric_snapshot_freezes,
        )

        return list_epidemiology_metric_snapshot_freezes(
            limit=limit,
            include_payload=include_payload,
        )
    except Exception as exc:
        return {
            "available": False,
            "version": "epidemiology_metric_snapshot_freeze_library_v1",
            "summary": {
                "freeze_count": 0,
                "download_ready_count": 0,
                "error": str(exc),
            },
            "freezes": [],
            "read_only": True,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
            "external_transfer_performed": False,
        }


def _status_for_no_recapture(
    audit_summary: Mapping[str, Any],
    ledger_summary: Mapping[str, Any],
) -> str:
    same_module = _safe_int(audit_summary.get("same_module_recapture_count"))
    ledger_watches = _safe_int(ledger_summary.get("recapture_watch_count"))
    if same_module > 0:
        return "block"
    if ledger_watches > 0:
        return "watch"
    return "pass"


def _pass_if(value: Any) -> str:
    return "pass" if bool(value) else "block"


def _pass_watch(value: Any) -> str:
    return "pass" if bool(value) else "watch"


def _operational_gate_status(
    evidence_vault: Mapping[str, Any],
    gate_key: str,
    *,
    env_pass: bool,
    env_evidence: str,
    fallback_action: str,
) -> dict[str, str]:
    vault_status = latest_gate_status_from_vault(evidence_vault, gate_key)
    if vault_status:
        gate_status = str(vault_status.get("gate_status") or "watch")
        if gate_status == "pass":
            return {
                "status": "pass",
                "evidence": (
                    f"vault verified: {vault_status.get('latest_evidence_key')} "
                    f"expires {vault_status.get('expires_at') or 'not documented'}"
                ),
                "next_action": "Mantener evidencia operacional vigente y renovar antes de expiracion.",
            }
        if gate_status == "block":
            return {
                "status": "block",
                "evidence": f"vault blocked: {vault_status.get('latest_evidence_key')}",
                "next_action": fallback_action,
            }
        if vault_status.get("latest_evidence_key"):
            return {
                "status": "watch",
                "evidence": (
                    f"vault watch: {vault_status.get('latest_evidence_key')} "
                    f"status {vault_status.get('latest_status')}"
                ),
                "next_action": fallback_action,
            }
    if env_pass:
        return {
            "status": "pass",
            "evidence": f"environment attestation: {env_evidence}",
            "next_action": "Materializar esta condicion como evidencia del vault antes del piloto formal.",
        }
    return {"status": "watch", "evidence": env_evidence, "next_action": fallback_action}


def _flag_false(payload: Mapping[str, Any], key: str) -> bool:
    return bool(payload.get(key, False)) is False


def _env_truthy(key: str) -> bool:
    return str(os.environ.get(key) or "").strip().lower() in {"1", "true", "yes", "si", "on"}


def _nas_env_evidence() -> str:
    bits = {
        "NAS_READY": os.environ.get("PROSTANET_NAS_DEPLOYMENT_READY", "false"),
        "HOST": os.environ.get("PROSTANET_HOST", ""),
        "PORT": os.environ.get("PROSTANET_PORT", ""),
        "DATALLESS_SAFE_START": os.environ.get("PROSTANET_DATALLESS_SAFE_START", "false"),
    }
    return ", ".join(f"{key}={value}" for key, value in bits.items())


def _route_for_gate(gate_key: str) -> str:
    if gate_key in {"clinical_fact_ledger", "v2_persistence_matrix", "no_recapture_contract"}:
        return "/platform-readiness"
    if gate_key in {
        "nas_local_operations",
        "backup_restore_drill",
        "access_control_roles",
        "consent_and_data_use",
        "training_and_adoption",
        "incident_response_contingency",
        "prospective_protocol_approval",
    }:
        return "/api/platform-readiness/nas-pilot-evidence-vault?scope=full"
    if gate_key == "research_pack_freeze_library":
        return "/platform-readiness"
    if gate_key == "epidemiology_snapshot_reproducibility":
        return "/population/epidemiology-command-center"
    return "/api/platform-readiness/prospective-pilot-governance?scope=full"


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
