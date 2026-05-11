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
    return jsonify({
        "vectors": CORE_VECTORS,
        "summary_by_vector": summary,
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
