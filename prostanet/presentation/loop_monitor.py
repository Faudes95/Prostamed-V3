"""Faubot LXCV — Iterative Improvement Loop Monitor.

Backend module + Flask blueprint para `/loop-monitor` dashboard que muestra
los últimos 30 días de iteraciones del bucle de mejora continua.

Vectors monitoreados (8 direcciones del plan):
1. Cobertura clínica (gates evaluables)
2. UI ergonomía (tiempo captura promedio)
3. Backend integrity (UI fields → backend canonicalize)
4. Evidencia clínica (citations live + PMIDs actualizados)
5. Recomendación accuracy (5 casos sintéticos vs esperado)
6. FDA SaMD compliance (audit trail + override + versioning)
7. Performance + a11y (Lighthouse + WCAG)
8. Status reporting (KPIs ejecutivos semanales)

Skills orchestration:
- /faubot (daily 7-fase audit)
- /pubmed-database (weekly evidence refresh)
- /ui-ux-pro-max (weekly Lighthouse + a11y)
- /generate-status-report (weekly KPI)
- /iterative-retrieval (4-fase context refinement)

Storage: KPIs persistidos en `prostanet_loop_monitor.db` SQLite con
schema simple: (timestamp, vector, metric, value, status, notes).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template

loop_monitor_bp = Blueprint("loop_monitor", __name__)


# ──────────────────────────────────────────────────────────────────────
# Storage layer (SQLite)
# ──────────────────────────────────────────────────────────────────────

LOOP_DB_PATH = Path(__file__).parent.parent.parent / "prostanet_loop_monitor.db"


def _get_conn() -> sqlite3.Connection:
    """Get SQLite connection (auto-creates DB + table)."""
    conn = sqlite3.connect(str(LOOP_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS loop_iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            iteration_id TEXT NOT NULL,
            vector TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL,
            status TEXT,
            notes TEXT,
            faubot_release TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON loop_iterations(timestamp DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_vector ON loop_iterations(vector)
    """)
    conn.commit()
    return conn


def record_iteration(
    iteration_id: str,
    vector: str,
    metric: str,
    value: float,
    status: str = "ok",
    notes: str = "",
    faubot_release: str = "",
) -> None:
    """Record one loop iteration KPI to storage.

    Args:
        iteration_id: e.g. "faubot-daily-2026-04-30"
        vector: one of CORE_VECTORS keys
        metric: human-readable metric name
        value: numeric value (e.g. percentage 0-100, count, time_ms)
        status: "ok" | "warning" | "critical"
        notes: free-text context
        faubot_release: e.g. "LXCV"
    """
    if not faubot_release:
        try:
            from prostanet.shared.algorithm_version import FAUBOT_RELEASE
            faubot_release = FAUBOT_RELEASE
        except ImportError:
            faubot_release = "unknown"

    conn = _get_conn()
    conn.execute("""
        INSERT INTO loop_iterations
        (timestamp, iteration_id, vector, metric, value, status, notes, faubot_release)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        iteration_id,
        vector,
        metric,
        value,
        status,
        notes,
        faubot_release,
    ))
    conn.commit()
    conn.close()


def get_recent_iterations(days: int = 30, limit: int = 500) -> list[dict[str, Any]]:
    """Get loop iterations from last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM loop_iterations
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (cutoff, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_vector_summary(days: int = 30) -> dict[str, dict[str, Any]]:
    """Get summary stats per vector for last N days."""
    iterations = get_recent_iterations(days=days, limit=10000)
    summary: dict[str, dict[str, Any]] = {}

    for iter_row in iterations:
        vec = iter_row["vector"]
        if vec not in summary:
            summary[vec] = {
                "count": 0,
                "ok": 0,
                "warning": 0,
                "critical": 0,
                "latest_value": None,
                "latest_metric": None,
                "latest_timestamp": None,
            }
        summary[vec]["count"] += 1
        status = iter_row.get("status", "ok")
        if status in summary[vec]:
            summary[vec][status] += 1

        # Track latest reading
        if summary[vec]["latest_timestamp"] is None or (
            iter_row["timestamp"] > summary[vec]["latest_timestamp"]
        ):
            summary[vec]["latest_timestamp"] = iter_row["timestamp"]
            summary[vec]["latest_value"] = iter_row.get("value")
            summary[vec]["latest_metric"] = iter_row.get("metric")

    return summary


def get_autonomous_improvement_snapshot(*, patient_limit: int = 8) -> dict[str, Any]:
    """Autonomous improvement read model for Loop Monitor.

    Kept lazy and patient-limited so Loop Monitor remains available even if a
    downstream clinical subsystem raises while the shadow loop is being refined.
    """
    try:
        from prostanet.agentic.autonomous_improvement_os import build_autonomous_improvement_bundle

        return build_autonomous_improvement_bundle(patient_limit=patient_limit)
    except Exception as exc:
        return {
            "available": False,
            "source": "autonomous_improvement_os",
            "error": str(exc),
            "mission_control": {
                "available": False,
                "source": "autonomous_improvement_os",
                "error": str(exc),
                "summary": {
                    "overall_pct": 0,
                    "status": "blocked",
                    "mode": "shadow",
                    "top_gap_title": "Mission control unavailable",
                },
                "metrics": [],
                "safety": {
                    "source_clinical_facts_mutated": False,
                    "auto_merge_enabled": False,
                    "human_review_required": True,
                },
            },
            "development_autodrive": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "development_autodrive_unavailable",
                "summary": {
                    "mode": "shadow",
                    "selected_id": "",
                    "selected_reason": "Development Autodrive unavailable.",
                    "one_change_per_iteration": True,
                },
                "selected_iteration": {
                    "available": False,
                    "mode": "shadow",
                    "reason": str(exc),
                },
                "selection_guardrails": {
                    "shadow_mode_only": True,
                    "clinical_fact_writes_allowed": False,
                    "auto_merge_allowed": False,
                },
            },
            "gaps": {
                "available": False,
                "source": "autonomous_improvement_os",
                "application_telemetry": {
                    "available": False,
                    "summary": {
                        "implemented_contract_count": 0,
                        "software_gap_closed_count": 0,
                        "patient_capture_monitoring_count": 0,
                        "source_clinical_facts_mutated": False,
                    },
                    "implementations": [],
                },
                "candidates": [],
                "contractual_gap_rows": [],
            },
            "shadow_pr_factory": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "shadow_pr_factory_unavailable",
                "summary": {
                    "mode": "shadow",
                    "ready_for_human_review": False,
                    "reason": str(exc),
                },
            },
            "safety_gate_runner": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "safety_gate_runner_unavailable",
                "summary": {
                    "mode": "shadow",
                    "release_gate": "blocked",
                    "commands_executed": False,
                    "reason": str(exc),
                },
                "gates": [],
            },
            "shadow_execution_artifacts": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "shadow_execution_artifacts_unavailable",
                "summary": {
                    "mode": "shadow",
                    "artifact_status": "blocked",
                    "commands_executed": False,
                    "reason": str(exc),
                },
                "command_results": [],
                "visual_results": [],
            },
            "human_review_decision_gate": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "human_review_decision_gate_unavailable",
                "summary": {
                    "mode": "shadow",
                    "decision_state": "blocked",
                    "release_gate": "blocked",
                    "reason": str(exc),
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "auto_merge_allowed": False,
                },
            },
            "draft_pr_handoff": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "draft_pr_handoff_unavailable",
                "summary": {
                    "mode": "shadow",
                    "handoff_status": "blocked",
                    "reason": str(exc),
                    "branch_created": False,
                    "pull_request_created": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "auto_merge_allowed": False,
                },
            },
            "pr_review_monitor": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "pr_review_monitor_unavailable",
                "summary": {
                    "mode": "shadow",
                    "monitor_status": "blocked",
                    "reason": str(exc),
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "auto_merge_allowed": False,
                },
            },
            "agent_lane_registry": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "agent_lane_registry_unavailable",
                "summary": {
                    "mode": "shadow",
                    "registry_status": "blocked",
                    "reason": str(exc),
                    "agent_code_execution_allowed": False,
                    "production_mutation_allowed": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "auto_merge_allowed": False,
                },
                "lanes": [],
            },
            "agent_proposal_packets": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "agent_proposal_packets_unavailable",
                "summary": {
                    "mode": "shadow",
                    "packet_status": "blocked",
                    "reason": str(exc),
                    "agent_code_execution_allowed": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "auto_merge_allowed": False,
                },
                "packets": [],
            },
            "agent_consensus_synthesizer": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "agent_consensus_synthesizer_unavailable",
                "summary": {
                    "mode": "shadow",
                    "consensus_status": "blocked",
                    "reason": str(exc),
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "agent_positions": [],
                "conflicts": [],
                "blocking_conditions": [],
            },
            "implementation_brief": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "implementation_brief_unavailable",
                "summary": {
                    "mode": "shadow",
                    "brief_status": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "file_scope": [],
                "test_plan": [],
                "blockers": [],
            },
            "shadow_patch_blueprint": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "shadow_patch_blueprint_unavailable",
                "summary": {
                    "mode": "shadow",
                    "blueprint_status": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "patch_blueprint": {"file_blueprints": []},
                "blockers": [],
            },
            "human_patch_authorization": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "human_patch_authorization_unavailable",
                "summary": {
                    "mode": "shadow",
                    "authorization_state": "blocked_until_blueprint_ready",
                    "authorization_gate": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "allowed_decisions": [],
                "latest_decision": {},
            },
            "controlled_patch_application": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "controlled_patch_application_unavailable",
                "summary": {
                    "mode": "shadow",
                    "application_status": "blocked",
                    "application_gate": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "application_packet": {},
                "blockers": ["snapshot_unavailable"],
            },
            "controlled_pr_implementation": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "controlled_pr_implementation_unavailable",
                "summary": {
                    "mode": "controlled_manual",
                    "implementation_status": "blocked",
                    "implementation_gate": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "implementation_packet": {},
                "blockers": ["snapshot_unavailable"],
            },
            "draft_pr_publication_gate": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "draft_pr_publication_gate_unavailable",
                "summary": {
                    "mode": "controlled_manual",
                    "publication_status": "blocked",
                    "publication_gate": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "publication_packet": {},
                "blockers": ["snapshot_unavailable"],
            },
            "required_safety_gate_contract": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "required_safety_gate_contract_unavailable",
                "summary": {
                    "mode": "controlled_manual",
                    "safety_contract_status": "blocked",
                    "safety_gate": "blocked",
                    "reason": str(exc),
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "required_gates": [],
                "blockers": ["snapshot_unavailable"],
            },
            "evidence_refresh_shadow_loop": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "evidence_refresh_shadow_loop_unavailable",
                "summary": {
                    "mode": "shadow",
                    "evidence_refresh_status": "blocked",
                    "evidence_gate": "blocked",
                    "reason": str(exc),
                    "evidence_changes_applied": False,
                    "recommendation_logic_mutated": False,
                    "trial_logic_mutated": False,
                    "gate_logic_mutated": False,
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "source_registry": [],
                "review_queue": [],
                "blockers": ["snapshot_unavailable"],
            },
            "patient_twin_readiness_loop": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "patient_twin_readiness_loop_unavailable",
                "summary": {
                    "mode": "shadow",
                    "patient_twin_readiness_status": "blocked",
                    "patient_twin_gate": "blocked",
                    "reason": str(exc),
                    "simulation_release_allowed": False,
                    "patient_twin_models_trained": False,
                    "patient_twin_predictions_released": False,
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "readiness_dimensions": [],
                "capture_plan": [],
                "blockers": ["snapshot_unavailable"],
            },
            "ai_readiness_dataset_loop": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "ai_readiness_dataset_loop_unavailable",
                "summary": {
                    "mode": "shadow",
                    "ai_readiness_status": "blocked",
                    "ai_readiness_gate": "blocked",
                    "reason": str(exc),
                    "dataset_export_allowed": False,
                    "dataset_export_written": False,
                    "model_training_allowed": False,
                    "models_trained": False,
                    "prediction_release_allowed": False,
                    "predictions_released": False,
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "dataset_gates": [],
                "model_readiness_report": {},
                "capture_plan": [],
                "blockers": ["snapshot_unavailable"],
            },
            "cortana_loop_interface": {
                "available": False,
                "source": "autonomous_improvement_os",
                "version": "cortana_loop_interface_unavailable",
                "summary": {
                    "mode": "shadow",
                    "cortana_loop_status": "blocked",
                    "cortana_loop_gate": "blocked",
                    "reason": str(exc),
                    "voice_write_allowed": False,
                    "clinical_fact_writes_allowed": False,
                    "code_mutation_allowed": False,
                    "model_training_allowed": False,
                    "prediction_release_allowed": False,
                    "commands_executed": False,
                    "files_modified": False,
                    "source_clinical_facts_mutated": False,
                    "git_mutated": False,
                    "branch_created": False,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "auto_merge_allowed": False,
                },
                "command_routes": [],
                "response_cards": [],
                "resolved_response": {},
                "blockers": ["snapshot_unavailable"],
            },
        }


def get_mission_control_snapshot() -> dict[str, Any]:
    """Autonomous improvement mission-control read model."""
    bundle = get_autonomous_improvement_snapshot()
    return dict(bundle.get("mission_control") or {})


def get_development_autodrive_snapshot() -> dict[str, Any]:
    """Shadow-mode Development Autodrive selection for the next safe iteration."""
    bundle = get_autonomous_improvement_snapshot()
    return dict(bundle.get("development_autodrive") or {})


# ──────────────────────────────────────────────────────────────────────
# Loop vector registry
# ──────────────────────────────────────────────────────────────────────

CORE_VECTORS: dict[str, dict[str, Any]] = {
    "clinical_coverage": {
        "label": "Cobertura clínica",
        "icon": "🩺",
        "target_metric": "Gates evaluables vs catálogo",
        "target_value": 89,
        "skill": "/faubot + /gate-validator + /pubmed-database",
    },
    "ui_ergonomy": {
        "label": "UI ergonomía",
        "icon": "🎨",
        "target_metric": "Tiempo captura completa promedio (s)",
        "target_value": 180,  # 3 min target
        "skill": "/ui-ux-pro-max + /frontend-patterns",
    },
    "backend_integrity": {
        "label": "Backend integrity",
        "icon": "🔧",
        "target_metric": "% UI fields que llegan a backend canonicalize sin drop",
        "target_value": 100,
        "skill": "/backend-patterns + /api-design",
    },
    "clinical_evidence": {
        "label": "Evidencia clínica",
        "icon": "📚",
        "target_metric": "Citations PMID actualizados en últimos 7 días",
        "target_value": 89,
        "skill": "/pubmed-database + /clinical-reports",
    },
    "recommendation_accuracy": {
        "label": "Recomendación accuracy",
        "icon": "🎯",
        "target_metric": "5 casos sintéticos retornan exactly esperado",
        "target_value": 5,
        "skill": "/medical-soap-note-creation + /faubot",
    },
    "fda_samd_compliance": {
        "label": "FDA SaMD compliance",
        "icon": "🏛",
        "target_metric": "Audit trail + override + versioning per field (%)",
        "target_value": 100,
        "skill": "/fda-medtech-compliance-auditor",
    },
    "performance_a11y": {
        "label": "Performance + a11y",
        "icon": "♿",
        "target_metric": "Lighthouse score + 0 WCAG violations",
        "target_value": 95,
        "skill": "/ui-ux-pro-max + /frontend-patterns",
    },
    "status_reporting": {
        "label": "Status reporting",
        "icon": "📊",
        "target_metric": "Exec summary semanal con KPIs (count)",
        "target_value": 1,  # 1 weekly report minimum
        "skill": "/generate-status-report",
    },
}


# ──────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────


@loop_monitor_bp.route("/api/loop-monitor/snapshot", methods=["GET"])
def snapshot():
    """Current loop status snapshot (last 30 days)."""
    summary = get_vector_summary(days=30)
    autonomous_improvement = get_autonomous_improvement_snapshot()
    mission_control = dict(autonomous_improvement.get("mission_control") or {})
    gaps = dict(autonomous_improvement.get("gaps") or {})
    application_telemetry = dict(gaps.get("application_telemetry") or {})
    development_autodrive = dict(autonomous_improvement.get("development_autodrive") or {})
    shadow_pr_factory = dict(autonomous_improvement.get("shadow_pr_factory") or {})
    safety_gate_runner = dict(autonomous_improvement.get("safety_gate_runner") or {})
    shadow_execution_artifacts = dict(autonomous_improvement.get("shadow_execution_artifacts") or {})
    human_review_decision_gate = dict(autonomous_improvement.get("human_review_decision_gate") or {})
    draft_pr_handoff = dict(autonomous_improvement.get("draft_pr_handoff") or {})
    pr_review_monitor = dict(autonomous_improvement.get("pr_review_monitor") or {})
    agent_lane_registry = dict(autonomous_improvement.get("agent_lane_registry") or {})
    agent_proposal_packets = dict(autonomous_improvement.get("agent_proposal_packets") or {})
    agent_consensus_synthesizer = dict(autonomous_improvement.get("agent_consensus_synthesizer") or {})
    implementation_brief = dict(autonomous_improvement.get("implementation_brief") or {})
    shadow_patch_blueprint = dict(autonomous_improvement.get("shadow_patch_blueprint") or {})
    human_patch_authorization = dict(autonomous_improvement.get("human_patch_authorization") or {})
    controlled_patch_application = dict(autonomous_improvement.get("controlled_patch_application") or {})
    controlled_pr_implementation = dict(autonomous_improvement.get("controlled_pr_implementation") or {})
    draft_pr_publication_gate = dict(autonomous_improvement.get("draft_pr_publication_gate") or {})
    required_safety_gate_contract = dict(autonomous_improvement.get("required_safety_gate_contract") or {})
    evidence_refresh_shadow_loop = dict(autonomous_improvement.get("evidence_refresh_shadow_loop") or {})
    patient_twin_readiness_loop = dict(autonomous_improvement.get("patient_twin_readiness_loop") or {})
    ai_readiness_dataset_loop = dict(autonomous_improvement.get("ai_readiness_dataset_loop") or {})
    cortana_loop_interface = dict(autonomous_improvement.get("cortana_loop_interface") or {})
    continuous_shadow_operation = dict(autonomous_improvement.get("continuous_shadow_operation") or {})
    return jsonify({
        "vectors": CORE_VECTORS,
        "summary_by_vector": summary,
        "mission_control": mission_control,
        "application_telemetry": application_telemetry,
        "development_autodrive": development_autodrive,
        "shadow_pr_factory": shadow_pr_factory,
        "safety_gate_runner": safety_gate_runner,
        "shadow_execution_artifacts": shadow_execution_artifacts,
        "human_review_decision_gate": human_review_decision_gate,
        "draft_pr_handoff": draft_pr_handoff,
        "pr_review_monitor": pr_review_monitor,
        "agent_lane_registry": agent_lane_registry,
        "agent_proposal_packets": agent_proposal_packets,
        "agent_consensus_synthesizer": agent_consensus_synthesizer,
        "implementation_brief": implementation_brief,
        "shadow_patch_blueprint": shadow_patch_blueprint,
        "human_patch_authorization": human_patch_authorization,
        "controlled_patch_application": controlled_patch_application,
        "controlled_pr_implementation": controlled_pr_implementation,
        "draft_pr_publication_gate": draft_pr_publication_gate,
        "required_safety_gate_contract": required_safety_gate_contract,
        "evidence_refresh_shadow_loop": evidence_refresh_shadow_loop,
        "patient_twin_readiness_loop": patient_twin_readiness_loop,
        "ai_readiness_dataset_loop": ai_readiness_dataset_loop,
        "cortana_loop_interface": cortana_loop_interface,
        "continuous_shadow_operation": continuous_shadow_operation,
        "total_vectors_monitored": len(CORE_VECTORS),
        "total_iterations_30d": sum(s["count"] for s in summary.values()),
    })


@loop_monitor_bp.route("/api/loop-monitor/iterations", methods=["GET"])
def iterations():
    """Recent iterations (last 30 days, max 500)."""
    return jsonify({
        "iterations": get_recent_iterations(days=30),
        "vectors": CORE_VECTORS,
    })


@loop_monitor_bp.route("/loop-monitor", methods=["GET"])
def dashboard():
    """Loop monitor dashboard UI."""
    summary = get_vector_summary(days=30)
    iterations_list = get_recent_iterations(days=30, limit=50)
    autonomous_improvement = get_autonomous_improvement_snapshot()
    mission_control = dict(autonomous_improvement.get("mission_control") or {})
    gaps = dict(autonomous_improvement.get("gaps") or {})
    application_telemetry = dict(gaps.get("application_telemetry") or {})
    development_autodrive = dict(autonomous_improvement.get("development_autodrive") or {})
    shadow_pr_factory = dict(autonomous_improvement.get("shadow_pr_factory") or {})
    safety_gate_runner = dict(autonomous_improvement.get("safety_gate_runner") or {})
    shadow_execution_artifacts = dict(autonomous_improvement.get("shadow_execution_artifacts") or {})
    human_review_decision_gate = dict(autonomous_improvement.get("human_review_decision_gate") or {})
    draft_pr_handoff = dict(autonomous_improvement.get("draft_pr_handoff") or {})
    pr_review_monitor = dict(autonomous_improvement.get("pr_review_monitor") or {})
    agent_lane_registry = dict(autonomous_improvement.get("agent_lane_registry") or {})
    agent_proposal_packets = dict(autonomous_improvement.get("agent_proposal_packets") or {})
    agent_consensus_synthesizer = dict(autonomous_improvement.get("agent_consensus_synthesizer") or {})
    implementation_brief = dict(autonomous_improvement.get("implementation_brief") or {})
    shadow_patch_blueprint = dict(autonomous_improvement.get("shadow_patch_blueprint") or {})
    human_patch_authorization = dict(autonomous_improvement.get("human_patch_authorization") or {})
    controlled_patch_application = dict(autonomous_improvement.get("controlled_patch_application") or {})
    controlled_pr_implementation = dict(autonomous_improvement.get("controlled_pr_implementation") or {})
    draft_pr_publication_gate = dict(autonomous_improvement.get("draft_pr_publication_gate") or {})
    required_safety_gate_contract = dict(autonomous_improvement.get("required_safety_gate_contract") or {})
    evidence_refresh_shadow_loop = dict(autonomous_improvement.get("evidence_refresh_shadow_loop") or {})
    patient_twin_readiness_loop = dict(autonomous_improvement.get("patient_twin_readiness_loop") or {})
    ai_readiness_dataset_loop = dict(autonomous_improvement.get("ai_readiness_dataset_loop") or {})
    cortana_loop_interface = dict(autonomous_improvement.get("cortana_loop_interface") or {})
    continuous_shadow_operation = dict(autonomous_improvement.get("continuous_shadow_operation") or {})
    # Build minimal page_chrome required by base_clinical.html layout
    page_chrome = {
        "title": "Loop Monitor — Iterative Improvement",
        "subtitle": "8 vectores monitoreados · últimos 30 días",
        "show_page_header": False,
        "content_width_class": "max-w-none px-0 py-0 sm:px-0 lg:px-0",
        "footer_text": "ProstaNet — Faubot Iterative Loop Monitor",
        "requires_charts": False,
    }
    return render_template(
        "loop_monitor_dashboard.html",
        vectors=CORE_VECTORS,
        summary=summary,
        mission_control=mission_control,
        application_telemetry=application_telemetry,
        development_autodrive=development_autodrive,
        shadow_pr_factory=shadow_pr_factory,
        safety_gate_runner=safety_gate_runner,
        shadow_execution_artifacts=shadow_execution_artifacts,
        human_review_decision_gate=human_review_decision_gate,
        draft_pr_handoff=draft_pr_handoff,
        pr_review_monitor=pr_review_monitor,
        agent_lane_registry=agent_lane_registry,
        agent_proposal_packets=agent_proposal_packets,
        agent_consensus_synthesizer=agent_consensus_synthesizer,
        implementation_brief=implementation_brief,
        shadow_patch_blueprint=shadow_patch_blueprint,
        human_patch_authorization=human_patch_authorization,
        controlled_patch_application=controlled_patch_application,
        controlled_pr_implementation=controlled_pr_implementation,
        draft_pr_publication_gate=draft_pr_publication_gate,
        required_safety_gate_contract=required_safety_gate_contract,
        evidence_refresh_shadow_loop=evidence_refresh_shadow_loop,
        patient_twin_readiness_loop=patient_twin_readiness_loop,
        ai_readiness_dataset_loop=ai_readiness_dataset_loop,
        cortana_loop_interface=cortana_loop_interface,
        continuous_shadow_operation=continuous_shadow_operation,
        iterations=iterations_list,
        total_iterations=sum(s["count"] for s in summary.values()),
        page_chrome=page_chrome,
    )


# ──────────────────────────────────────────────────────────────────────
# Self-recording helpers (called from cron jobs / tests)
# ──────────────────────────────────────────────────────────────────────


def record_clinical_coverage_check() -> dict[str, Any]:
    """Self-check: how many gates load + fire infrastructure works."""
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            _load_yaml_files, get_loaded_yaml_codes
        )
        _load_yaml_files(force_reload=True)
        codes = get_loaded_yaml_codes()
        gate_count = len(codes)
        status = "ok" if gate_count >= 89 else "warning"
        record_iteration(
            iteration_id=f"clinical-coverage-{datetime.utcnow().date().isoformat()}",
            vector="clinical_coverage",
            metric="gates_loaded",
            value=gate_count,
            status=status,
            notes=f"{gate_count} gates loaded from YAML catalog",
        )
        return {"gate_count": gate_count, "status": status}
    except Exception as exc:
        record_iteration(
            iteration_id=f"clinical-coverage-{datetime.utcnow().date().isoformat()}",
            vector="clinical_coverage",
            metric="gates_loaded",
            value=0,
            status="critical",
            notes=f"Error loading gates: {exc}",
        )
        return {"error": str(exc), "status": "critical"}


def record_backend_integrity_check() -> dict[str, Any]:
    """Self-check: progressive_capture_builder retorna estructura válida."""
    try:
        from prostanet.presentation.progressive_capture_builder import (
            build_stage_aware_capture,
        )
        result = build_stage_aware_capture("localized_initial", {
            "psa_value": 25, "gleason_score": 9, "clinical_t_stage": "T3b"
        })
        ok = (
            "always_visible" in result
            and "expandable_groups" in result
            and len(result.get("expandable_groups", [])) == 3
        )
        status = "ok" if ok else "warning"
        record_iteration(
            iteration_id=f"backend-integrity-{datetime.utcnow().date().isoformat()}",
            vector="backend_integrity",
            metric="progressive_builder_returns_complete_structure",
            value=100.0 if ok else 50.0,
            status=status,
            notes=f"localized_initial: {len(result.get('always_visible', []))} visible + 3 groups",
        )
        return {"ok": ok, "status": status}
    except Exception as exc:
        record_iteration(
            iteration_id=f"backend-integrity-{datetime.utcnow().date().isoformat()}",
            vector="backend_integrity",
            metric="progressive_builder_returns_complete_structure",
            value=0.0,
            status="critical",
            notes=f"Error: {exc}",
        )
        return {"error": str(exc), "status": "critical"}
