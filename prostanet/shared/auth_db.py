"""auth_db.py — FAUBOT 2026-04-25 (XXVIII) — Tier 7 G1.5.

DB layer para `clinical_users` + `clinical_audit_log` tables.

Tablas creadas (additive migration, IF NOT EXISTS):
    - clinical_users: usuarios autorizados con role ABAC.
    - clinical_audit_log: log inmutable de cada acceso a endpoint clínico.

Aporte a auditabilidad:
    - **DATOS:** persistencia trazable de TODO acceso PHI/audit
    - **POR QUÉ:** cada respuesta autorizada/denegada queda con razón
    - **VERSIÓN:** auth_backend usado queda registrado por entrada

Diseño:
    - Reusa SQLite via tracking_db._connect (no nueva dependencia).
    - Migración idempotente: `init_auth_db()` puede ejecutarse N veces.
    - Funciones puras (sin global state).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# Schema initialization (idempotent migration)
# ════════════════════════════════════════════════════════════════════


_INIT_DDL = [
    # ── clinical_users ────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS clinical_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT,                  -- nullable for federated backends
        email TEXT,
        role TEXT NOT NULL DEFAULT 'clinician',
        backend TEXT NOT NULL DEFAULT 'local_pbkdf2',
        external_id TEXT,                    -- for federated (Auth0/Keycloak sub)
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_clinical_users_username
        ON clinical_users(username)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_clinical_users_external_id
        ON clinical_users(external_id)
    """,

    # ── clinical_audit_log ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS clinical_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,                     -- nullable (anonymous denials)
        username TEXT,                       -- denormalized for easier query
        endpoint TEXT NOT NULL,              -- e.g., 'decision_audit'
        path TEXT,                           -- e.g., '/api/decision-audit/123'
        method TEXT,                         -- GET/POST/...
        scope TEXT,                          -- 'phi:read' / 'audit:read' / ...
        status TEXT NOT NULL,                -- 'authorized' / 'denied_*' / 'error'
        reason TEXT,                         -- detail (e.g., 'session_expired')
        trace_id TEXT,                       -- UUID4 correlatable to logs
        ip_address TEXT,                     -- request remote_addr (truncated)
        user_agent TEXT,                     -- request UA (truncated 200 chars)
        backend TEXT,                        -- auth backend used
        timestamp TEXT NOT NULL,             -- ISO8601 UTC
        FOREIGN KEY (user_id) REFERENCES clinical_users(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
        ON clinical_audit_log(timestamp)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_user_id
        ON clinical_audit_log(user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_endpoint
        ON clinical_audit_log(endpoint)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_status
        ON clinical_audit_log(status)
    """,
]


def init_auth_db() -> None:
    """Crea tablas clinical_users + clinical_audit_log si no existen.

    Llamado idempotentemente desde `app.py:create_app` tras `init_tracking_db`.
    """
    try:
        from tracking_db import _connect
    except ImportError:
        logger.warning("tracking_db not available; init_auth_db skipped")
        return
    conn = _connect(write=True)
    try:
        cur = conn.cursor()
        for ddl in _INIT_DDL:
            cur.execute(ddl)
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# clinical_users — CRUD
# ════════════════════════════════════════════════════════════════════


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def get_user_by_username(username: str) -> dict | None:
    """Lookup user por username. Retorna dict (incl. password_hash) o None."""
    if not username:
        return None
    try:
        from tracking_db import _connect
    except ImportError:
        return None
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM clinical_users WHERE username = ? AND is_active = 1",
            (username,),
        )
        return _row_to_dict(cur.fetchone())
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_by_id(user_id: int) -> dict | None:
    """Lookup user por id. Retorna dict (sin password_hash) o None."""
    if not user_id:
        return None
    try:
        from tracking_db import _connect
    except ImportError:
        return None
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, username, email, role, backend, external_id,
                      is_active, created_at, updated_at, last_login_at
               FROM clinical_users WHERE id = ? AND is_active = 1""",
            (int(user_id),),
        )
        return _row_to_dict(cur.fetchone())
    finally:
        try:
            conn.close()
        except Exception:
            pass


def create_user_record(
    *,
    username: str,
    password_hash: str = "",
    role: str = "clinician",
    email: str = "",
    backend: str = "local_pbkdf2",
    external_id: str = "",
) -> int:
    """Crea nuevo registro en clinical_users. Retorna user_id.

    Lanza ValueError si username ya existe.
    """
    if not username:
        raise ValueError("username required")
    try:
        from tracking_db import _connect
    except ImportError:
        raise RuntimeError("tracking_db not available")
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(write=True)
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO clinical_users
                   (username, password_hash, email, role, backend,
                    external_id, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    username, password_hash, email, role, backend,
                    external_id, now, now,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"username {username!r} already exists")
        conn.commit()
        return int(cur.lastrowid)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_last_login(user_id: int) -> None:
    """Actualiza last_login_at del usuario."""
    if not user_id:
        return
    try:
        from tracking_db import _connect
    except ImportError:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(write=True)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE clinical_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, int(user_id)),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# clinical_audit_log — Append-only writes + simple queries
# ════════════════════════════════════════════════════════════════════


def write_audit_log_entry(
    *,
    endpoint: str,
    status: str,
    user_id: int | None = None,
    username: str = "",
    path: str = "",
    method: str = "",
    scope: str = "",
    reason: str = "",
    trace_id: str = "",
    ip_address: str = "",
    user_agent: str = "",
    backend: str = "",
) -> int | None:
    """Append-only write al audit log. NEVER raises (best-effort).

    Args:
        endpoint: nombre del endpoint (e.g., 'decision_audit')
        status: 'authorized' | 'denied_no_session' | 'denied_invalid_scope' |
                'denied_user_inactive' | 'error'
        user_id: id del usuario (None si denied_no_session)
        ...

    Returns:
        audit_log id (int) si write exitoso, None si falló silenciosamente.
    """
    try:
        from tracking_db import _connect
    except ImportError:
        return None
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _connect(write=True)
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO clinical_audit_log
                   (user_id, username, endpoint, path, method, scope, status,
                    reason, trace_id, ip_address, user_agent, backend, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id, username[:200] if username else None,
                    endpoint[:100], path[:500], method[:10],
                    scope[:50], status[:50],
                    reason[:500] if reason else None,
                    trace_id[:50] if trace_id else None,
                    ip_address[:50] if ip_address else None,
                    user_agent[:200] if user_agent else None,
                    backend[:50] if backend else None,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        # Audit log writes must NEVER break the request flow
        logger.warning(f"audit_log_write_failed | {type(exc).__name__}: {exc}")
        return None


def get_audit_log_entries(
    *,
    user_id: int | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query audit log con filtros opcionales. Para forense regulatoria."""
    try:
        from tracking_db import _connect
    except ImportError:
        return []
    where_parts = []
    params: list[Any] = []
    if user_id is not None:
        where_parts.append("user_id = ?")
        params.append(int(user_id))
    if endpoint:
        where_parts.append("endpoint = ?")
        params.append(endpoint[:100])
    if status:
        where_parts.append("status = ?")
        params.append(status[:50])
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    params.append(int(limit))
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT * FROM clinical_audit_log {where_clause}
                ORDER BY id DESC LIMIT ?""",
            params,
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# Faubot 2026-04-25 (XLV) — Tier 7 G9: extended audit log query helpers
# para soporte del dashboard endpoint /api/auth/audit-log con filtering +
# pagination + date range. Refuerza compliance HIPAA §164.312(b).
# ════════════════════════════════════════════════════════════════════


def _build_audit_log_where_clause(
    *,
    user_id: int | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    timestamp_from: str | None = None,
    timestamp_to: str | None = None,
) -> tuple[str, list[Any]]:
    """Faubot G9 — Helper interno común a query + count para mantener
    DRY el WHERE clause. Defensive truncation en strings + ISO check
    en timestamps (sin parsing estricto: SQLite acepta lexicographic
    ordering en strings ISO8601 UTC).
    """
    where_parts: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        where_parts.append("user_id = ?")
        params.append(int(user_id))
    if endpoint:
        where_parts.append("endpoint = ?")
        params.append(str(endpoint)[:100])
    if status:
        where_parts.append("status = ?")
        params.append(str(status)[:50])
    if timestamp_from:
        where_parts.append("timestamp >= ?")
        params.append(str(timestamp_from)[:64])
    if timestamp_to:
        where_parts.append("timestamp <= ?")
        params.append(str(timestamp_to)[:64])
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    return where_clause, params


def query_audit_log_entries(
    *,
    user_id: int | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    timestamp_from: str | None = None,
    timestamp_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Faubot 2026-04-25 (XLV) — Tier 7 G9: query extendida del audit log.

    Diferencias con `get_audit_log_entries()` (preservada por back-compat):
      - Soporta `timestamp_from` + `timestamp_to` (ISO8601 UTC strings)
        para date range filtering — crítico para auditorías regulatorias
        de período específico.
      - Soporta `offset` para pagination.
      - Limit default más conservador (50 en vez de 100) por UX dashboard.
      - Cap defensivo de limit a 500 para prevenir queries bogus que
        agoten memoria del servidor.

    Args:
        user_id: filter exact match.
        endpoint: filter exact match (truncado a 100 chars).
        status: filter exact match (truncado a 50 chars).
        timestamp_from: ISO8601 string lower bound (>=).
        timestamp_to: ISO8601 string upper bound (<=).
        limit: max rows to return (default 50, hard cap 500).
        offset: rows to skip (default 0).

    Returns:
        Lista de dicts con todas las columnas de clinical_audit_log,
        ordenados DESC por id (más recientes primero).
    """
    try:
        from tracking_db import _connect
    except ImportError:
        return []

    # Defensive caps
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))

    where_clause, params = _build_audit_log_where_clause(
        user_id=user_id, endpoint=endpoint, status=status,
        timestamp_from=timestamp_from, timestamp_to=timestamp_to,
    )
    params.append(safe_limit)
    params.append(safe_offset)

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT * FROM clinical_audit_log {where_clause}
                ORDER BY id DESC LIMIT ? OFFSET ?""",
            params,
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def count_audit_log_entries_filtered(
    *,
    user_id: int | None = None,
    endpoint: str | None = None,
    status: str | None = None,
    timestamp_from: str | None = None,
    timestamp_to: str | None = None,
) -> int:
    """Faubot 2026-04-25 (XLV) — Tier 7 G9: conteo con MISMO WHERE clause
    que `query_audit_log_entries()`. Necesario para que el dashboard UI
    pueda calcular `has_more` y total de páginas en pagination.

    Returns:
        Conteo total de entries matching los filtros (sin limit/offset).
        0 si la tabla no existe o el conector no está disponible.
    """
    try:
        from tracking_db import _connect
    except ImportError:
        return 0

    where_clause, params = _build_audit_log_where_clause(
        user_id=user_id, endpoint=endpoint, status=status,
        timestamp_from=timestamp_from, timestamp_to=timestamp_to,
    )

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT COUNT(*) FROM clinical_audit_log {where_clause}",
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def count_audit_log_entries() -> int:
    """Conteo total de entradas en audit log (métrica básica)."""
    try:
        from tracking_db import _connect
    except ImportError:
        return 0
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM clinical_audit_log")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
