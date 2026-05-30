"""GodiBot REST endpoints — Faubot Iteración C (GodiBot v1).

Endpoints expuestos:

  POST /api/godibot/review/<nss>       — Re-ejecuta GodiBot on-demand para un paciente
  POST /api/godibot/override/<nss>     — Persiste un override firmado del médico
  GET  /api/godibot/reviews/<nss>      — Historial de reviews por NSS
  GET  /api/godibot/concordance        — Métricas globales agregadas (para 9° vector loop)

Tabla SQLite persistente: `godibot_reviews` (auto-creada en _get_conn()).

Todos los endpoints retornan JSON. Errores tipados como `{"error": "...", "status": 4xx/5xx}`.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

godibot_bp = Blueprint("godibot", __name__)


# ──────────────────────────────────────────────────────────────────────
# Storage layer (SQLite — reuses prostanet_tracking.db)
# ──────────────────────────────────────────────────────────────────────

GODIBOT_DB_PATH = Path(__file__).parent.parent.parent / "prostanet_tracking.db"


def _get_conn() -> sqlite3.Connection:
    """Get SQLite connection — auto-creates `godibot_reviews` table."""
    conn = sqlite3.connect(str(GODIBOT_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS godibot_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            nss TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            bundle_sha TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL,
            discrepancies_json TEXT,
            trial_omissions_json TEXT,
            biomarker_gaps_json TEXT,
            override_signed_by TEXT,
            override_reason TEXT,
            override_timestamp TEXT,
            faubot_release TEXT,
            godibot_version TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_godibot_nss ON godibot_reviews(nss)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_godibot_timestamp
        ON godibot_reviews(timestamp DESC)
    """)
    conn.commit()
    return conn


def _bundle_sha(payload: dict) -> str:
    """SHA-256 (12 chars) del payload para trazabilidad reproducibilidad."""
    blob = json.dumps(payload, sort_keys=True, default=str)[:50_000]
    return sha256(blob.encode("utf-8")).hexdigest()[:12]


def persist_review(
    *,
    nss: str,
    review: dict[str, Any],
    bundle_sha: str = "",
    faubot_release: str = "",
) -> int:
    """Persiste un review GodiBot. Retorna review_id."""
    if not faubot_release:
        try:
            from prostanet.shared.algorithm_version import FAUBOT_RELEASE
            faubot_release = FAUBOT_RELEASE
        except ImportError:
            faubot_release = "unknown"

    conn = _get_conn()
    cur = conn.execute("""
        INSERT INTO godibot_reviews
        (nss, timestamp, bundle_sha, status, confidence,
         discrepancies_json, trial_omissions_json, biomarker_gaps_json,
         faubot_release, godibot_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(nss),
        datetime.utcnow().isoformat(),
        bundle_sha or _bundle_sha(review),
        str(review.get("status", "unknown")),
        float(review.get("confidence") or 0.0),
        json.dumps(review.get("discrepancies", []), default=str),
        json.dumps(review.get("trial_omissions", []), default=str),
        json.dumps(review.get("biomarker_gaps", []), default=str),
        faubot_release,
        str(review.get("version", "godibot-v1")),
    ))
    conn.commit()
    review_id = cur.lastrowid or 0
    conn.close()
    return review_id


def persist_override(
    *,
    nss: str,
    override_signed_by: str,
    override_reason: str,
    review_id: int | None = None,
) -> bool:
    """Persiste un override firmado por el médico. Si review_id se provee,
    actualiza el review existente; si no, busca el review más reciente
    del paciente."""
    conn = _get_conn()
    if review_id:
        conn.execute("""
            UPDATE godibot_reviews
            SET override_signed_by = ?, override_reason = ?, override_timestamp = ?
            WHERE review_id = ?
        """, (
            override_signed_by, override_reason,
            datetime.utcnow().isoformat(), review_id,
        ))
    else:
        conn.execute("""
            UPDATE godibot_reviews
            SET override_signed_by = ?, override_reason = ?, override_timestamp = ?
            WHERE review_id = (
                SELECT review_id FROM godibot_reviews
                WHERE nss = ? AND override_signed_by IS NULL
                ORDER BY timestamp DESC LIMIT 1
            )
        """, (
            override_signed_by, override_reason,
            datetime.utcnow().isoformat(), str(nss),
        ))
    affected = conn.total_changes
    conn.commit()
    conn.close()
    return affected > 0


def get_reviews(nss: str, limit: int = 20) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT * FROM godibot_reviews
        WHERE nss = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (str(nss), limit)).fetchall()
    conn.close()
    result = []
    for r in rows:
        row = dict(r)
        for k in ("discrepancies_json", "trial_omissions_json", "biomarker_gaps_json"):
            try:
                row[k.replace("_json", "")] = json.loads(row.pop(k) or "[]")
            except (json.JSONDecodeError, TypeError):
                row[k.replace("_json", "")] = []
        result.append(row)
    return result


def get_concordance_summary(days: int = 30) -> dict[str, Any]:
    """Métricas agregadas para el 9° vector recommendation_concordance."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = conn.execute("""
        SELECT status, COUNT(*) as n,
               AVG(confidence) as avg_conf,
               SUM(CASE WHEN override_signed_by IS NOT NULL THEN 1 ELSE 0 END) as overrides
        FROM godibot_reviews
        WHERE timestamp >= ?
        GROUP BY status
    """, (cutoff,)).fetchall()

    total = 0
    by_status: dict[str, dict[str, Any]] = {}
    total_overrides = 0
    weighted_conf = 0.0

    for r in rows:
        n = int(r["n"] or 0)
        total += n
        total_overrides += int(r["overrides"] or 0)
        weighted_conf += (r["avg_conf"] or 0) * n
        by_status[r["status"]] = {
            "count": n,
            "avg_confidence": round(r["avg_conf"] or 0, 3),
            "overrides": int(r["overrides"] or 0),
        }

    conn.close()
    return {
        "days": days,
        "total_reviews": total,
        "total_overrides": total_overrides,
        "override_rate": round(total_overrides / total, 3) if total else 0.0,
        "weighted_avg_confidence": round(weighted_conf / total, 3) if total else 0.0,
        "by_status": by_status,
        "approved_rate": round(
            (by_status.get("approved", {}).get("count", 0)) / total, 3
        ) if total else 0.0,
        "blocked_rate": round(
            (by_status.get("blocked_hard", {}).get("count", 0)) / total, 3
        ) if total else 0.0,
    }


# ──────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────


def _fetch_patient_record(nss: str) -> dict[str, Any] | None:
    """Best-effort fetch del record completo del paciente. Falla silenciosa
    si tracking_db.get_patient_full_record() no está disponible o el NSS
    no existe."""
    try:
        from tracking_db import get_patient_full_record  # type: ignore
        return get_patient_full_record(nss=nss)
    except Exception as exc:
        logger.debug("Could not fetch record for nss=%s: %s", nss, exc)
        return None


@godibot_bp.route("/api/godibot/review/<nss>", methods=["POST"])
def review_patient(nss: str):
    """Re-ejecuta GodiBot on-demand para un paciente.

    Body (opcional):
        {
          "compass": {...},        # Si se omite, se construye desde DB
          "enable_llm": false,     # Default false (latencia)
          "persist": true          # Default true (guarda en godibot_reviews)
        }
    """
    body = request.get_json(silent=True) or {}
    compass = body.get("compass")
    enable_llm = bool(body.get("enable_llm", False))
    persist = body.get("persist", True)

    record = _fetch_patient_record(nss)
    if record is None and compass is None:
        return jsonify({
            "error": "Patient record not found and no compass provided in body.",
        }), 404

    record = record or {}

    try:
        from prostanet.agents.godibot import run_godibot_review
    except ImportError as exc:
        return jsonify({"error": f"GodiBot not available: {exc}"}), 500

    review = run_godibot_review(
        record,
        patient_id=int(record.get("patient_id") or 0),
        compass=compass,
        enable_llm=enable_llm,
    )

    review_id = None
    if persist:
        try:
            review_id = persist_review(nss=nss, review=review)
        except Exception as exc:
            logger.warning("persist_review failed for nss=%s: %s", nss, exc)

    return jsonify({
        "nss": nss,
        "review": review,
        "review_id": review_id,
        "persisted": review_id is not None,
    })


@godibot_bp.route("/api/godibot/override/<nss>", methods=["POST"])
def override_review(nss: str):
    """Persiste un override firmado del médico.

    Body (form-urlencoded o JSON):
        {
          "override_signed_by": "7654321",      # cédula profesional
          "override_reason": "Razón clínica...",  # min 30 caracteres
          "review_id": 42                        # opcional, si se omite usa último
        }
    """
    body = request.get_json(silent=True) or request.form.to_dict() or {}
    signer = str(body.get("override_signed_by", "")).strip()
    reason = str(body.get("override_reason", "")).strip()
    review_id = body.get("review_id")

    if not signer or len(signer) < 6:
        return jsonify({
            "error": "override_signed_by required (cédula profesional 6-12 chars)",
        }), 400
    if not reason or len(reason) < 30:
        return jsonify({
            "error": "override_reason required (min 30 characters with clinical justification)",
        }), 400

    try:
        review_id_int = int(review_id) if review_id else None
    except (TypeError, ValueError):
        review_id_int = None

    success = persist_override(
        nss=nss,
        override_signed_by=signer,
        override_reason=reason,
        review_id=review_id_int,
    )
    if not success:
        return jsonify({
            "error": "No pending GodiBot review found for this patient.",
        }), 404

    return jsonify({
        "nss": nss,
        "override_signed_by": signer,
        "override_recorded": True,
        "timestamp": datetime.utcnow().isoformat(),
    })


@godibot_bp.route("/api/godibot/reviews/<nss>", methods=["GET"])
def list_reviews(nss: str):
    """Lista los últimos N reviews del paciente (default 20)."""
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    reviews = get_reviews(nss, limit=max(1, min(100, limit)))
    return jsonify({"nss": nss, "count": len(reviews), "reviews": reviews})


@godibot_bp.route("/api/godibot/concordance", methods=["GET"])
def concordance_summary():
    """Métricas globales de concordancia (alimenta 9° vector loop)."""
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    summary = get_concordance_summary(days=max(1, min(365, days)))
    return jsonify(summary)


__all__ = [
    "godibot_bp",
    "persist_review",
    "persist_override",
    "get_reviews",
    "get_concordance_summary",
]
