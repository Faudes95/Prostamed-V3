import json
from datetime import UTC, datetime, timedelta

import tracking_db


ANALYTICS_CACHE_KEY = "dashboard_analytics_v1"
CALIBRATION_CACHE_KEY = "dashboard_calibration_v1"
RESEARCH_CACHE_KEY = "dashboard_research_intelligence_v1"
ANALYTICS_TTL_SECONDS = 300
CALIBRATION_TTL_SECONDS = 900
RESEARCH_TTL_SECONDS = 600


def _utcnow():
    return datetime.now(UTC)


def _ensure_cache_table(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_cache_snapshots (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            ttl_seconds INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _parse_generated_at(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def get_cache_snapshot(cache_key):
    conn = tracking_db._connect()
    _ensure_cache_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cache_key, payload_json, generated_at, ttl_seconds
        FROM dashboard_cache_snapshots
        WHERE cache_key = ?
        """,
        (cache_key,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "cache_key": row["cache_key"],
        "payload": payload,
        "generated_at": row["generated_at"],
        "ttl_seconds": int(row["ttl_seconds"] or 0),
    }


def is_snapshot_fresh(snapshot, now=None):
    if not snapshot:
        return False
    generated_at = _parse_generated_at(snapshot.get("generated_at"))
    ttl_seconds = int(snapshot.get("ttl_seconds") or 0)
    if not generated_at or ttl_seconds <= 0:
        return False
    return generated_at + timedelta(seconds=ttl_seconds) > (now or _utcnow())


def get_cached_payload(cache_key):
    snapshot = get_cache_snapshot(cache_key)
    if not is_snapshot_fresh(snapshot):
        return None
    return snapshot["payload"]


def set_cache_snapshot(cache_key, payload, ttl_seconds):
    conn = tracking_db._connect()
    _ensure_cache_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dashboard_cache_snapshots (cache_key, payload_json, generated_at, ttl_seconds)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            generated_at = excluded.generated_at,
            ttl_seconds = excluded.ttl_seconds
        """,
        (
            cache_key,
            json.dumps(payload, ensure_ascii=True, default=str),
            _utcnow().isoformat(timespec="seconds"),
            int(ttl_seconds),
        ),
    )
    conn.commit()
    conn.close()


def cache_status(cache_key):
    snapshot = get_cache_snapshot(cache_key)
    return {
        "available": bool(snapshot),
        "fresh": is_snapshot_fresh(snapshot),
        "generated_at": (snapshot or {}).get("generated_at"),
        "ttl_seconds": (snapshot or {}).get("ttl_seconds"),
    }
