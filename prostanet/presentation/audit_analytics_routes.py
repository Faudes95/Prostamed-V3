"""audit_analytics_routes.py — Sprint 7.A (FAUBOT CXLV).

Dashboard cohort-level que hace visible el efecto de Sprints 5+6 sobre la
operación clínica + research:

  - Cohorte breakdown: n × estadio × etnia × estado actual
  - Blocked_hard SLA: pacientes atascados, días desde último audit
  - Override rate por clínico (señal de divergencia con guideline)
  - Endpoint heatmap (qué se usa más → priorizar perf/cache)
  - GodiBot finding trends week-over-week (% Internal Validation history)

Endpoints (todos @require_admin — IP institucional + agregados clínicos):
  GET /api/audit-analytics/cohort-breakdown
  GET /api/audit-analytics/blocked-hard-pending
  GET /api/audit-analytics/override-stats
  GET /api/audit-analytics/endpoint-usage
  GET /api/audit-analytics/godibot-trends
  GET /audit-analytics-dashboard  (HTML view server-side)

Beneficio clínico tangible:
  - Director médico ve "8% de mCRPC llega a Lu-177 vs benchmark 12% → investigar"
  - Equity surface: blocked_hard rate por etnia revela inequities sistémicas
  - Quality improvement loop: trend semanal de % IV → cierra el "continuous
    learning" del SaMD §820.30 post-market surveillance

Beneficio regulatorio:
  - FDA/COFEPRIS expect cohort-level monitoring continuo (no solo Internal
    Validation report estático)
  - Audit dashboard ES el artifact que demuestra post-market surveillance
  - Foundation para "Bayesian decision support" (visión H3) — aquí se ven
    los shifts de posterior

Filosofía SaMD: este dashboard es READ-ONLY agregado. NO expone PHI individual.
Pacientes referenciados son por patient_id sintetico (no NSS), y demograficos
quedan agregados (cuenta por etnia, no listado).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, render_template

import tracking_db
from prostanet.shared.api_auth import (
    require_admin, current_api_user_id, current_api_user_role,
)

logger = logging.getLogger(__name__)

audit_analytics_bp = Blueprint("audit_analytics", __name__)


# ─────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────

BLOCKED_SLA_DAYS_GREEN = 7   # <7d sin resolver → verde
BLOCKED_SLA_DAYS_YELLOW = 30 # 7-30d → amarillo
                              # >30d → rojo (acción requerida)

TRENDS_WINDOW_WEEKS = 12      # rolling window últimas 12 semanas


def _faubot_release_snapshot() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(tracking_db.DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _audit_dashboard_view(actor_user_id: int | None, view: str) -> None:
    """Auditamos cada acceso al dashboard (es PHI agregada — §820.30)."""
    conn = None
    try:
        conn = sqlite3.connect(str(tracking_db.DB_PATH), timeout=5.0)
        cur = conn.cursor()
        action = f"audit_analytics:view:{view}"
        if actor_user_id:
            action = f"{action}:user_{actor_user_id}"
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (0, "audit_analytics", action, "medium",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("audit_analytics view-log failed: %s: %s",
                       type(exc).__name__, exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────


def _cohort_breakdown(conn: sqlite3.Connection) -> dict[str, Any]:
    """n por estadio (state_timeline.state) × etnia (demographics.etnia)
    × estado actual. Retorna structure agregable en Chart.js stacked bars."""
    cur = conn.cursor()

    # Total cohort + por estadio actual
    cur.execute("SELECT COUNT(DISTINCT id) FROM patient_identity")
    total_patients = cur.fetchone()[0]

    # Estadio actual: último state_timeline per paciente
    cur.execute(
        """
        WITH latest_state AS (
            SELECT patient_id, state,
                   ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY id DESC) AS rn
              FROM patient_state_timeline
             WHERE state IS NOT NULL
        )
        SELECT state, COUNT(*) AS n
          FROM latest_state
         WHERE rn = 1
         GROUP BY state
         ORDER BY n DESC
        """
    )
    by_state = [{"state": r[0] or "no_state", "count": r[1]}
                for r in cur.fetchall()]

    # Etnia breakdown (campo `etnia` en patient_demographics)
    cur.execute(
        """
        SELECT COALESCE(etnia, 'no_declarado') AS etn, COUNT(*) AS n
          FROM patient_demographics
         GROUP BY etn
         ORDER BY n DESC
        """
    )
    by_ethnicity = [{"ethnicity": r[0], "count": r[1]} for r in cur.fetchall()]

    # ECOG distribution (clinical_baseline.ecog_score)
    cur.execute(
        """
        SELECT COALESCE(CAST(ecog_score AS TEXT), 'no_doc') AS ecog, COUNT(*) AS n
          FROM clinical_baseline
         GROUP BY ecog
         ORDER BY ecog
        """
    )
    by_ecog = [{"ecog": r[0], "count": r[1]} for r in cur.fetchall()]

    # HRR documentation status (Sprint 5 follow-through)
    cur.execute(
        """
        SELECT
            CASE
                WHEN hrr_status IS NULL OR hrr_status IN ('Desconocido','unknown','no_hecho','')
                    THEN 'pending'
                ELSE 'documented'
            END AS hrr_doc,
            COUNT(*) AS n
          FROM clinical_baseline
         GROUP BY hrr_doc
        """
    )
    by_hrr = [{"hrr_status": r[0], "count": r[1]} for r in cur.fetchall()]

    return {
        "total_patients": total_patients,
        "by_state": by_state,
        "by_ethnicity": by_ethnicity,
        "by_ecog": by_ecog,
        "by_hrr_documentation": by_hrr,
    }


def _blocked_hard_pending(conn: sqlite3.Connection) -> dict[str, Any]:
    """Pacientes con status=blocked_hard en último cohort audit + días desde
    último audit (SLA). Foundation para "Quién necesita workup AHORA"."""
    cur = conn.cursor()

    # Último run_id de cohort audit (más reciente)
    cur.execute(
        "SELECT run_id, MAX(run_timestamp) FROM cohort_validation_runs"
    )
    row = cur.fetchone()
    last_run_id, last_run_ts = (row[0] if row else None), (row[1] if row else None)

    # Pacientes blocked_hard en último run
    cur.execute(
        """
        SELECT patient_id, patient_nss, findings_count, findings_json, run_timestamp
          FROM cohort_validation_runs
         WHERE godibot_status = 'blocked_hard'
           AND run_id = ?
         ORDER BY findings_count DESC, patient_id
        """,
        (last_run_id,) if last_run_id else ("",),
    )
    rows = cur.fetchall()

    now = datetime.now(timezone.utc)
    pending = []
    sla_buckets = {"green": 0, "yellow": 0, "red": 0}

    for r in rows:
        ts = r[4]
        days_since = 0
        try:
            audit_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            days_since = max(0, (now - audit_dt).days)
        except Exception:
            pass

        if days_since < BLOCKED_SLA_DAYS_GREEN:
            sla = "green"
        elif days_since < BLOCKED_SLA_DAYS_YELLOW:
            sla = "yellow"
        else:
            sla = "red"
        sla_buckets[sla] += 1

        # NO exponemos NSS — sí patient_id sintético + nss SCRUBBED para drill-down
        pending.append({
            "patient_id": r[0],
            "patient_nss_short": (r[1][:4] + "***" if r[1] else "***"),
            "findings_count": r[2],
            "days_since_audit": days_since,
            "sla_bucket": sla,
            "audit_timestamp": ts,
        })

    return {
        "last_audit_run_id": last_run_id,
        "last_audit_timestamp": last_run_ts,
        "blocked_hard_count": len(pending),
        "sla_buckets": sla_buckets,
        "pending_patients": pending[:50],  # cap para payload size
    }


def _override_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Override rate por clínico (actor_user_id). Foundation para identificar
    clínicos con divergencia sistemática vs guideline → coaching opportunity."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM clinical_override_event")
    total_overrides = cur.fetchone()[0]

    # Por clínico (actor_user_id desde Sprint 6 captura session)
    cur.execute(
        """
        SELECT actor_user_id, actor_role,
               COUNT(*) AS n,
               COUNT(DISTINCT patient_id) AS patients,
               MIN(decided_at) AS first_at,
               MAX(decided_at) AS last_at
          FROM clinical_override_event
         WHERE actor_user_id IS NOT NULL
         GROUP BY actor_user_id, actor_role
         ORDER BY n DESC
         LIMIT 20
        """
    )
    by_clinician = [
        {
            "user_id": r[0],
            "role": r[1] or "unknown",
            "override_count": r[2],
            "patients_affected": r[3],
            "first_override_at": r[4],
            "last_override_at": r[5],
        }
        for r in cur.fetchall()
    ]

    # Top razones (normalized table)
    cur.execute(
        """
        SELECT reason_code, COUNT(*) AS n
          FROM clinical_override_event_reason
         GROUP BY reason_code
         ORDER BY n DESC
         LIMIT 10
        """
    )
    top_reasons = [{"reason": r[0], "count": r[1]} for r in cur.fetchall()]

    # Por recommendation_source (qué engine fue overrideado más)
    cur.execute(
        """
        SELECT recommendation_source, COUNT(*) AS n
          FROM clinical_override_event
         GROUP BY recommendation_source
         ORDER BY n DESC
        """
    )
    by_source = [{"source": r[0], "count": r[1]} for r in cur.fetchall()]

    return {
        "total_overrides": total_overrides,
        "by_clinician_top_20": by_clinician,
        "top_reasons": top_reasons,
        "by_recommendation_source": by_source,
    }


def _endpoint_usage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Heatmap de uso por section_key + temporal trend. Foundation para
    capacity planning + perf optimization."""
    cur = conn.cursor()

    # Total events
    cur.execute("SELECT COUNT(*) FROM clinical_view_audit")
    total_events = cur.fetchone()[0]

    # Por section_key
    cur.execute(
        """
        SELECT section_key, COUNT(*) AS n,
               COUNT(DISTINCT patient_id) AS unique_patients,
               MAX(created_at) AS last_seen
          FROM clinical_view_audit
         GROUP BY section_key
         ORDER BY n DESC
         LIMIT 30
        """
    )
    by_section = [
        {
            "section_key": r[0],
            "event_count": r[1],
            "unique_patients": r[2],
            "last_seen": r[3],
        }
        for r in cur.fetchall()
    ]

    # Por importance level
    cur.execute(
        """
        SELECT importance, COUNT(*) AS n
          FROM clinical_view_audit
         GROUP BY importance
         ORDER BY n DESC
        """
    )
    by_importance = [{"importance": r[0] or "unknown", "count": r[1]}
                     for r in cur.fetchall()]

    return {
        "total_events": total_events,
        "by_section_top_30": by_section,
        "by_importance": by_importance,
    }


def _godibot_trends(conn: sqlite3.Connection) -> dict[str, Any]:
    """% Internal Validation week-over-week (rolling 12 semanas).
    Foundation para SaMD post-market surveillance + research publicación."""
    cur = conn.cursor()

    # Window: últimas 12 semanas
    now = datetime.now(timezone.utc)
    weeks = []
    for week_offset in range(TRENDS_WINDOW_WEEKS - 1, -1, -1):
        week_start = now - timedelta(weeks=week_offset + 1)
        week_end = now - timedelta(weeks=week_offset)
        cur.execute(
            """
            SELECT godibot_status, COUNT(*) AS n
              FROM cohort_validation_runs
             WHERE run_timestamp >= ? AND run_timestamp < ?
             GROUP BY godibot_status
            """,
            (week_start.isoformat(), week_end.isoformat()),
        )
        counts = {r[0]: r[1] for r in cur.fetchall()}
        approved = counts.get("approved", 0)
        warnings = counts.get("warnings_only", 0)
        blocked = counts.get("blocked_hard", 0)
        total = approved + warnings + blocked
        iv_pct = (
            round(((approved + 0.5 * warnings) / total) * 100, 1)
            if total > 0 else None
        )
        weeks.append({
            "week_start": week_start.date().isoformat(),
            "total": total,
            "approved": approved,
            "warnings_only": warnings,
            "blocked_hard": blocked,
            "internal_validation_pct": iv_pct,
        })

    # Latest run stats
    cur.execute(
        """
        SELECT godibot_status, COUNT(*) AS n
          FROM cohort_validation_runs
         WHERE run_id = (SELECT run_id FROM cohort_validation_runs ORDER BY id DESC LIMIT 1)
         GROUP BY godibot_status
        """
    )
    latest = {r[0]: r[1] for r in cur.fetchall()}

    return {
        "weeks_window": TRENDS_WINDOW_WEEKS,
        "weekly_trend": weeks,
        "latest_run_distribution": latest,
    }


# ─────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────


@audit_analytics_bp.route("/api/audit-analytics/cohort-breakdown", methods=["GET"])
@require_admin
def api_cohort_breakdown():
    """Distribución cohorte por state × ethnicity × ECOG × HRR doc status."""
    faubot = _faubot_release_snapshot()
    actor = current_api_user_id()
    _audit_dashboard_view(actor, "cohort_breakdown")
    conn = _get_conn()
    try:
        data = _cohort_breakdown(conn)
        return jsonify({"success": True, "data": data, "faubot_release": faubot})
    except Exception:
        logger.exception("cohort_breakdown failed")
        return jsonify({
            "success": False, "error": "internal_error",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@audit_analytics_bp.route("/api/audit-analytics/blocked-hard-pending", methods=["GET"])
@require_admin
def api_blocked_hard_pending():
    """Pacientes blocked_hard del último run + SLA buckets."""
    faubot = _faubot_release_snapshot()
    actor = current_api_user_id()
    _audit_dashboard_view(actor, "blocked_hard_pending")
    conn = _get_conn()
    try:
        data = _blocked_hard_pending(conn)
        return jsonify({"success": True, "data": data, "faubot_release": faubot})
    except Exception:
        logger.exception("blocked_hard_pending failed")
        return jsonify({
            "success": False, "error": "internal_error",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@audit_analytics_bp.route("/api/audit-analytics/override-stats", methods=["GET"])
@require_admin
def api_override_stats():
    """Stats override por clínico + reasons + sources."""
    faubot = _faubot_release_snapshot()
    actor = current_api_user_id()
    _audit_dashboard_view(actor, "override_stats")
    conn = _get_conn()
    try:
        data = _override_stats(conn)
        return jsonify({"success": True, "data": data, "faubot_release": faubot})
    except Exception:
        logger.exception("override_stats failed")
        return jsonify({
            "success": False, "error": "internal_error",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@audit_analytics_bp.route("/api/audit-analytics/endpoint-usage", methods=["GET"])
@require_admin
def api_endpoint_usage():
    """Heatmap de uso por section_key + importance."""
    faubot = _faubot_release_snapshot()
    actor = current_api_user_id()
    _audit_dashboard_view(actor, "endpoint_usage")
    conn = _get_conn()
    try:
        data = _endpoint_usage(conn)
        return jsonify({"success": True, "data": data, "faubot_release": faubot})
    except Exception:
        logger.exception("endpoint_usage failed")
        return jsonify({
            "success": False, "error": "internal_error",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@audit_analytics_bp.route("/api/audit-analytics/godibot-trends", methods=["GET"])
@require_admin
def api_godibot_trends():
    """% Internal Validation week-over-week (rolling 12 semanas)."""
    faubot = _faubot_release_snapshot()
    actor = current_api_user_id()
    _audit_dashboard_view(actor, "godibot_trends")
    conn = _get_conn()
    try:
        data = _godibot_trends(conn)
        return jsonify({"success": True, "data": data, "faubot_release": faubot})
    except Exception:
        logger.exception("godibot_trends failed")
        return jsonify({
            "success": False, "error": "internal_error",
            "faubot_release": faubot,
        }), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


@audit_analytics_bp.route("/audit-analytics-dashboard", methods=["GET"])
@require_admin
def view_dashboard():
    """HTML dashboard server-side rendered con Chart.js (no SPA)."""
    actor = current_api_user_id()
    role = current_api_user_role()
    _audit_dashboard_view(actor, "dashboard_html")
    faubot = _faubot_release_snapshot()
    return render_template(
        "audit_analytics_dashboard.html",
        faubot_release=faubot,
        actor_user_id=actor,
        actor_role=role,
    )


__all__ = ["audit_analytics_bp"]
