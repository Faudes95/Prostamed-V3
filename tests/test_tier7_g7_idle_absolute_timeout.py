"""tests/test_tier7_g7_idle_absolute_timeout.py — Faubot 2026-04-25 (XXXIX).

Tests dedicados a Tier 7 G7: Idle vs Absolute timeout differentiation.

Cubre H.G1056 - H.G1085 (30 hipótesis):

§A — Backend helpers (auth_backends)
  H.G1056: SESSION_ABSOLUTE_TIMEOUT_SECONDS y SESSION_IDLE_TIMEOUT_SECONDS leen env
  H.G1057: SESSION_TIMEOUT_SECONDS conserva alias backward-compat
  H.G1058: session_login() inicializa last_activity = login_time
  H.G1059: session_touch_activity() incrementa touch_count + actualiza last_activity
  H.G1060: session_touch_activity() es no-op si no hay user_id
  H.G1061: session_idle_seconds_remaining() retorna ventana correcta tras login
  H.G1062: session_absolute_seconds_remaining() retorna ventana correcta tras login
  H.G1063: session_idle_seconds_remaining() decrece sin actividad y se resetea con touch
  H.G1064: session_absolute_seconds_remaining() NO se resetea con touch (hard cap)
  H.G1065: session_expiry_reason() retorna "valid" tras login
  H.G1066: session_expiry_reason() retorna "expired_idle" cuando solo idle expira
  H.G1067: session_expiry_reason() retorna "expired_absolute" cuando absolute expira
  H.G1068: session_expiry_reason() prioriza absolute sobre idle si ambos vencen
  H.G1069: session_logout() limpia last_activity + touch_count
  H.G1070: session_is_valid() respeta ambos timeouts simultáneamente

§B — Decorator integration (require_clinical_session)
  H.G1071: passive=True NO toca last_activity tras auth check OK
  H.G1072: passive=False (default) SI toca last_activity tras auth check OK
  H.G1073: Sesión expirada por idle → redirect lleva ?reason=idle (HTML)
  H.G1074: Sesión expirada por absolute → redirect lleva ?reason=absolute (HTML)
  H.G1075: Sesión expirada por idle → JSON lleva "reason": "expired_idle" (API)

§C — Endpoint /api/auth/touch
  H.G1076: POST /api/auth/touch sin sesión → 401 con reason=unauthenticated
  H.G1077: POST /api/auth/touch con sesión válida → 200 + touch_count incrementado
  H.G1078: POST /api/auth/touch tras idle expirado → 401 con reason=expired_idle
  H.G1079: POST /api/auth/touch resetea sliding window IDLE en backend

§D — Endpoint /api/auth/session-status (campos G7)
  H.G1080: session-status retorna session_seconds_until_idle_timeout
  H.G1081: session-status retorna session_seconds_until_absolute_timeout
  H.G1082: session-status retorna idle_timeout_sec + absolute_timeout_sec
  H.G1083: session-status retorna expiry_reason consistente
  H.G1084: session-status NO toca last_activity (es endpoint pasivo)

§E — Context processor + config helper
  H.G1085: g.session_indicator_idle_warning_threshold_sec, _touch_url, _touch_debounce_ms,
           _idle_timeout_sec, _absolute_timeout_sec populated in before_request
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clean session-related env vars before each test AND reload
    auth_backends so SESSION_*_TIMEOUT module-level constants reset to
    defaults (8h absolute / 30min idle).
    """
    for var in (
        "PROSTANET_CLINICAL_SESSION_TIMEOUT_SEC",
        "PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC",
        "PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC",
        "PROSTANET_SESSION_INDICATOR_IDLE_WARNING_THRESHOLD_SEC",
        "PROSTANET_SESSION_INDICATOR_TOUCH_DEBOUNCE_MS",
        "PROSTANET_SESSION_INDICATOR_ENABLED",
        "CLINICAL_AUTH_ENABLED",
        "PROSTANET_CLINICAL_AUTH_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)


def _reload_auth_backends_with_env(monkeypatch, *, idle: int | None = None,
                                   absolute: int | None = None):
    """Re-import auth_backends with custom timeout env vars applied.

    Necesario porque SESSION_*_TIMEOUT_SECONDS son module-level constants
    leídas en import-time, no per-call.
    """
    import importlib
    if idle is not None:
        monkeypatch.setenv(
            "PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", str(idle)
        )
    if absolute is not None:
        monkeypatch.setenv(
            "PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", str(absolute)
        )
    import prostanet.shared.auth_backends as ab
    return importlib.reload(ab)


def _build_session(user_id: int = 42, *, login_offset_sec: int = 0,
                   activity_offset_sec: int = 0) -> dict:
    """Build a dict-session with timestamps shifted into the past.

    login_offset_sec: how many seconds ago login_time should be.
    activity_offset_sec: how many seconds ago last_activity should be.
                         If 0, falls back to login_time (initial state).
    """
    now = datetime.now(timezone.utc)
    sess = {
        "_clinical_user_id": user_id,
        "_clinical_login_time": (now - timedelta(seconds=login_offset_sec)).isoformat(),
        "_clinical_backend": "local_pbkdf2",
        "_clinical_touch_count": 0,
    }
    if activity_offset_sec >= 0:
        sess["_clinical_last_activity"] = (
            now - timedelta(seconds=activity_offset_sec)
        ).isoformat()
    return sess


@pytest.fixture
def app():
    """Real Flask app with full middleware stack."""
    from app import create_app
    a = create_app()
    yield a


@pytest.fixture
def authenticated_client(app, monkeypatch):
    """Test client with a valid authenticated session for clinician role."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db

    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username("test_g7_clinician")
    if existing:
        uid = existing["id"]
    else:
        uid = backend.create_user(
            username="test_g7_clinician",
            password="TestPass123!",
            email="g7@test.local",
            role="clinician",
        )

    client = app.test_client()
    now = datetime.now(timezone.utc)
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = uid
        sess["_clinical_login_time"] = now.isoformat()
        sess["_clinical_last_activity"] = now.isoformat()
        sess["_clinical_touch_count"] = 0
        sess["_clinical_backend"] = "local_pbkdf2"

    yield client


@pytest.fixture
def anonymous_client(app):
    """Test client with no auth + no session."""
    return app.test_client()


# ════════════════════════════════════════════════════════════════════
# §A — Backend helpers (auth_backends)
# ════════════════════════════════════════════════════════════════════


def test_g1056_env_timeouts_load_on_import(monkeypatch):
    """SESSION_ABSOLUTE_TIMEOUT_SECONDS y SESSION_IDLE_TIMEOUT_SECONDS leen env."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=900, absolute=14400)
    assert ab.SESSION_IDLE_TIMEOUT_SECONDS == 900
    assert ab.SESSION_ABSOLUTE_TIMEOUT_SECONDS == 14400


def test_g1057_legacy_alias_preserved(monkeypatch):
    """SESSION_TIMEOUT_SECONDS conserva el valor de ABSOLUTE para back-compat."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    assert ab.SESSION_TIMEOUT_SECONDS == ab.SESSION_ABSOLUTE_TIMEOUT_SECONDS == 7200


def test_g1058_session_login_initializes_last_activity():
    """session_login() inicializa last_activity = login_time."""
    from prostanet.shared.auth_backends import (
        session_login, SESSION_LAST_ACTIVITY_KEY, SESSION_LOGIN_TIME_KEY,
        SESSION_TOUCH_COUNT_KEY,
    )
    sess = {}
    session_login(sess, user_id=123, backend_name="local_pbkdf2")
    assert sess[SESSION_LOGIN_TIME_KEY] == sess[SESSION_LAST_ACTIVITY_KEY]
    assert sess[SESSION_TOUCH_COUNT_KEY] == 0


def test_g1059_touch_activity_increments_count_and_updates_timestamp():
    """session_touch_activity() incrementa touch_count + actualiza last_activity."""
    from prostanet.shared.auth_backends import (
        session_login, session_touch_activity, SESSION_LAST_ACTIVITY_KEY,
        SESSION_TOUCH_COUNT_KEY,
    )
    sess = {}
    session_login(sess, user_id=1, backend_name="local")
    initial_activity = sess[SESSION_LAST_ACTIVITY_KEY]
    time.sleep(0.05)
    new_count = session_touch_activity(sess)
    assert new_count == 1
    assert sess[SESSION_TOUCH_COUNT_KEY] == 1
    assert sess[SESSION_LAST_ACTIVITY_KEY] != initial_activity
    new_count2 = session_touch_activity(sess)
    assert new_count2 == 2


def test_g1060_touch_activity_noop_without_user_id():
    """session_touch_activity() es no-op si no hay user_id."""
    from prostanet.shared.auth_backends import (
        session_touch_activity, SESSION_LAST_ACTIVITY_KEY,
    )
    sess = {}  # no user_id
    new_count = session_touch_activity(sess)
    assert new_count == 0
    assert SESSION_LAST_ACTIVITY_KEY not in sess


def test_g1061_idle_remaining_after_login(monkeypatch):
    """session_idle_seconds_remaining() retorna ventana correcta tras login."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    sess = {}
    ab.session_login(sess, user_id=1, backend_name="local")
    remaining = ab.session_idle_seconds_remaining(sess)
    # Debería ser muy cerca de 600 (idle window completa)
    assert 595 <= remaining <= 600


def test_g1062_absolute_remaining_after_login(monkeypatch):
    """session_absolute_seconds_remaining() retorna ventana correcta tras login."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    sess = {}
    ab.session_login(sess, user_id=1, backend_name="local")
    remaining = ab.session_absolute_seconds_remaining(sess)
    assert 7195 <= remaining <= 7200


def test_g1063_idle_resets_on_touch(monkeypatch):
    """idle decrece sin actividad y se resetea con touch."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    # Sesión simulada con last_activity 300s atrás → quedan ~300s de idle
    sess = _build_session(user_id=1, login_offset_sec=400, activity_offset_sec=300)
    remaining_before = ab.session_idle_seconds_remaining(sess)
    assert 295 <= remaining_before <= 305
    # Touch resetea last_activity → idle vuelve a casi 600
    ab.session_touch_activity(sess)
    remaining_after = ab.session_idle_seconds_remaining(sess)
    assert 595 <= remaining_after <= 600


def test_g1064_absolute_NOT_reset_by_touch(monkeypatch):
    """absolute no se resetea con touch (hard cap desde login_time)."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    # Sesión con login_time 1000s atrás → absolute remaining ~6200
    sess = _build_session(user_id=1, login_offset_sec=1000, activity_offset_sec=300)
    remaining_before = ab.session_absolute_seconds_remaining(sess)
    assert 6195 <= remaining_before <= 6205
    ab.session_touch_activity(sess)
    remaining_after = ab.session_absolute_seconds_remaining(sess)
    # absolute NO cambia con touch
    assert remaining_after == remaining_before or abs(remaining_after - remaining_before) <= 1


def test_g1065_expiry_reason_valid_after_login(monkeypatch):
    """session_expiry_reason() retorna 'valid' tras login fresco."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=7200)
    sess = {}
    ab.session_login(sess, user_id=1, backend_name="local")
    assert ab.session_expiry_reason(sess) == ab.SESSION_REASON_VALID


def test_g1066_expiry_reason_idle(monkeypatch):
    """session_expiry_reason() = 'expired_idle' cuando solo idle expira."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=300, absolute=7200)
    # Login hace 600s, last_activity hace 400s (>idle 300) pero <absolute 7200
    sess = _build_session(user_id=1, login_offset_sec=600, activity_offset_sec=400)
    reason = ab.session_expiry_reason(sess)
    assert reason == ab.SESSION_REASON_EXPIRED_IDLE


def test_g1067_expiry_reason_absolute(monkeypatch):
    """session_expiry_reason() = 'expired_absolute' cuando absolute expira."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=600, absolute=300)
    # Login hace 400s (>absolute 300), last_activity hace 100s (<idle 600)
    sess = _build_session(user_id=1, login_offset_sec=400, activity_offset_sec=100)
    reason = ab.session_expiry_reason(sess)
    assert reason == ab.SESSION_REASON_EXPIRED_ABSOLUTE


def test_g1068_expiry_reason_absolute_priority(monkeypatch):
    """Cuando ambos expiran, gana absolute (no se puede extender via touch)."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=300, absolute=300)
    sess = _build_session(user_id=1, login_offset_sec=500, activity_offset_sec=500)
    # Ambos vencidos: prioridad ABSOLUTE
    assert ab.session_expiry_reason(sess) == ab.SESSION_REASON_EXPIRED_ABSOLUTE


def test_g1069_logout_clears_g7_keys():
    """session_logout() limpia last_activity + touch_count."""
    from prostanet.shared.auth_backends import (
        session_login, session_logout, session_touch_activity,
        SESSION_LAST_ACTIVITY_KEY, SESSION_TOUCH_COUNT_KEY,
    )
    sess = {}
    session_login(sess, user_id=1, backend_name="local")
    session_touch_activity(sess)
    assert SESSION_LAST_ACTIVITY_KEY in sess
    assert SESSION_TOUCH_COUNT_KEY in sess
    session_logout(sess)
    assert SESSION_LAST_ACTIVITY_KEY not in sess
    assert SESSION_TOUCH_COUNT_KEY not in sess


def test_g1070_session_is_valid_respects_both_timeouts(monkeypatch):
    """session_is_valid() respeta ambos timeouts simultáneamente."""
    ab = _reload_auth_backends_with_env(monkeypatch, idle=300, absolute=7200)
    # Caso 1: ambos válidos
    sess1 = _build_session(user_id=1, login_offset_sec=100, activity_offset_sec=100)
    assert ab.session_is_valid(sess1)
    # Caso 2: idle expirado (last_activity 400s atrás, idle window 300s)
    sess2 = _build_session(user_id=1, login_offset_sec=500, activity_offset_sec=400)
    assert not ab.session_is_valid(sess2)
    # Caso 3: absolute expirado (login 7300s atrás, absolute 7200)
    sess3 = _build_session(user_id=1, login_offset_sec=7300, activity_offset_sec=10)
    assert not ab.session_is_valid(sess3)


# ════════════════════════════════════════════════════════════════════
# §B — Decorator integration (require_clinical_session)
# ════════════════════════════════════════════════════════════════════


def _ensure_user(username: str = "g7_test_user") -> int:
    """Idempotent helper to provision a clinical user via the local backend."""
    from prostanet.shared.auth_backends import LocalPbkdf2Backend
    from prostanet.shared import auth_db
    auth_db.init_auth_db()
    backend = LocalPbkdf2Backend()
    existing = auth_db.get_user_by_username(username)
    if existing:
        return existing["id"]
    return backend.create_user(
        username=username, password="TestPass123!",
        email=f"{username}@test.local", role="clinician",
    )


def _invoke_decorated(app, decorated_fn, *, session_data: dict,
                      accept: str = "application/json", path: str = "/_t"):
    """Invoca una función decorada con require_clinical_session() dentro de
    un test_request_context, sin registrar rutas en el singleton de Flask
    (que ya está bloqueado tras el primer request).

    Devuelve el (status_code, headers, body) tras la invocación + el dict
    de sesión post-call para inspeccionar side-effects.
    """
    from flask import session as flask_session, make_response
    headers = {"Accept": accept}
    with app.test_request_context(path, method="GET", headers=headers):
        # Populate session state
        for k, v in session_data.items():
            flask_session[k] = v
        # Call decorated function
        result = decorated_fn()
        # Normalize result into Flask Response
        if isinstance(result, tuple):
            body, status = (result + (200,))[:2]
            resp = make_response(body, status)
        else:
            resp = make_response(result)
        # Capture session post-call
        post_session = {k: flask_session[k] for k in flask_session.keys()}
        return resp.status_code, dict(resp.headers), resp.get_data(as_text=True), post_session


def test_g1071_passive_decorator_does_not_touch(app, monkeypatch):
    """passive=True NO toca last_activity tras auth check OK."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.security_helpers import require_clinical_session
    from prostanet.shared.auth_backends import (
        SESSION_LAST_ACTIVITY_KEY, SESSION_TOUCH_COUNT_KEY,
    )
    uid = _ensure_user("g1071_user")

    @require_clinical_session(scope="phi:read", passive=True)
    def passive_endpoint():
        return {"ok": True}

    now = datetime.now(timezone.utc)
    activity_marker = (now - timedelta(seconds=120)).isoformat()
    session_data = {
        "_clinical_user_id": uid,
        "_clinical_login_time": now.isoformat(),
        "_clinical_last_activity": activity_marker,
        "_clinical_touch_count": 5,
        "_clinical_backend": "local_pbkdf2",
    }
    status, _, _, post = _invoke_decorated(app, passive_endpoint, session_data=session_data)
    assert status == 200
    # passive=True → last_activity + touch_count UNCHANGED
    assert post[SESSION_LAST_ACTIVITY_KEY] == activity_marker
    assert post[SESSION_TOUCH_COUNT_KEY] == 5


def test_g1072_active_decorator_touches(app, monkeypatch):
    """passive=False (default) SI toca last_activity tras auth check OK."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")

    from prostanet.shared.security_helpers import require_clinical_session
    from prostanet.shared.auth_backends import (
        SESSION_LAST_ACTIVITY_KEY, SESSION_TOUCH_COUNT_KEY,
    )
    uid = _ensure_user("g1072_user")

    @require_clinical_session(scope="phi:read")  # passive default = False
    def active_endpoint():
        return {"ok": True}

    now = datetime.now(timezone.utc)
    activity_marker = (now - timedelta(seconds=120)).isoformat()
    session_data = {
        "_clinical_user_id": uid,
        "_clinical_login_time": now.isoformat(),
        "_clinical_last_activity": activity_marker,
        "_clinical_touch_count": 5,
        "_clinical_backend": "local_pbkdf2",
    }
    status, _, _, post = _invoke_decorated(app, active_endpoint, session_data=session_data)
    assert status == 200
    # passive=False → last_activity REFRESHED + touch_count INCREMENTED
    assert post[SESSION_LAST_ACTIVITY_KEY] != activity_marker
    assert post[SESSION_TOUCH_COUNT_KEY] == 6


def test_g1073_idle_expiry_redirects_with_reason_idle(app, monkeypatch):
    """Sesión expirada por idle → redirect lleva ?reason=idle (HTML)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", "60")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", "7200")
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)

    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=True)
    def html_endpoint():
        return "OK"

    now = datetime.now(timezone.utc)
    session_data = {
        "_clinical_user_id": 999,
        "_clinical_login_time": (now - timedelta(seconds=600)).isoformat(),
        # IDLE window=60s, activity 300s ago → idle expired
        "_clinical_last_activity": (now - timedelta(seconds=300)).isoformat(),
        "_clinical_backend": "local_pbkdf2",
    }
    status, headers, _, _ = _invoke_decorated(
        app, html_endpoint, session_data=session_data,
        accept="text/html",
    )
    assert status == 302
    assert "reason=idle" in headers.get("Location", "")


def test_g1074_absolute_expiry_redirects_with_reason_absolute(app, monkeypatch):
    """Sesión expirada por absolute → redirect lleva ?reason=absolute (HTML)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", "1800")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", "60")
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)

    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=True)
    def html_abs_endpoint():
        return "OK"

    now = datetime.now(timezone.utc)
    session_data = {
        "_clinical_user_id": 999,
        # ABSOLUTE window=60s, login 300s ago → absolute expired
        "_clinical_login_time": (now - timedelta(seconds=300)).isoformat(),
        "_clinical_last_activity": (now - timedelta(seconds=10)).isoformat(),
        "_clinical_backend": "local_pbkdf2",
    }
    status, headers, _, _ = _invoke_decorated(
        app, html_abs_endpoint, session_data=session_data,
        accept="text/html",
    )
    assert status == 302
    assert "reason=absolute" in headers.get("Location", "")


def test_g1075_idle_expiry_json_returns_reason(app, monkeypatch):
    """Sesión expirada por idle → JSON lleva 'reason': 'expired_idle' (API)."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", "60")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", "7200")
    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)

    from prostanet.shared.security_helpers import require_clinical_session

    @require_clinical_session(scope="phi:read", redirect_to_login=False)
    def json_endpoint():
        return {"ok": True}

    now = datetime.now(timezone.utc)
    session_data = {
        "_clinical_user_id": 999,
        "_clinical_login_time": (now - timedelta(seconds=600)).isoformat(),
        "_clinical_last_activity": (now - timedelta(seconds=300)).isoformat(),
        "_clinical_backend": "local_pbkdf2",
    }
    status, _, body, _ = _invoke_decorated(
        app, json_endpoint, session_data=session_data,
        accept="application/json",
    )
    assert status == 401
    import json
    payload = json.loads(body)
    assert payload["reason"] == "expired_idle"


# ════════════════════════════════════════════════════════════════════
# §C — Endpoint /api/auth/touch
# ════════════════════════════════════════════════════════════════════


def test_g1076_touch_unauthenticated_returns_401(anonymous_client):
    """POST /api/auth/touch sin sesión → 401 con reason=unauthenticated."""
    resp = anonymous_client.post("/api/auth/touch")
    assert resp.status_code == 401
    payload = resp.get_json()
    assert payload["success"] is False
    assert payload["reason"] == "unauthenticated"


def test_g1077_touch_authenticated_returns_200_and_increments(authenticated_client):
    """POST /api/auth/touch con sesión válida → 200 + touch_count incrementado."""
    resp1 = authenticated_client.post("/api/auth/touch")
    assert resp1.status_code == 200
    payload1 = resp1.get_json()
    assert payload1["success"] is True
    assert payload1["touch_count"] >= 1
    first_count = payload1["touch_count"]
    resp2 = authenticated_client.post("/api/auth/touch")
    assert resp2.status_code == 200
    payload2 = resp2.get_json()
    assert payload2["touch_count"] == first_count + 1


def test_g1078_touch_after_idle_expiry_returns_401(app, monkeypatch):
    """POST /api/auth/touch tras idle expirado → 401 con reason=expired_idle."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_IDLE_TIMEOUT_SEC", "60")
    monkeypatch.setenv("PROSTANET_CLINICAL_SESSION_ABSOLUTE_TIMEOUT_SEC", "7200")

    import importlib
    import prostanet.shared.auth_backends
    importlib.reload(prostanet.shared.auth_backends)

    client = app.test_client()
    now = datetime.now(timezone.utc)
    with client.session_transaction() as sess:
        sess["_clinical_user_id"] = 555
        sess["_clinical_login_time"] = (now - timedelta(seconds=600)).isoformat()
        sess["_clinical_last_activity"] = (now - timedelta(seconds=400)).isoformat()
        sess["_clinical_backend"] = "local_pbkdf2"

    resp = client.post("/api/auth/touch")
    assert resp.status_code == 401
    payload = resp.get_json()
    assert payload["reason"] == "expired_idle"


def test_g1079_touch_resets_idle_window(authenticated_client):
    """POST /api/auth/touch resetea sliding window IDLE en backend."""
    # Stale: simulate old activity
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=120)).isoformat()
    with authenticated_client.session_transaction() as sess:
        sess["_clinical_last_activity"] = stale

    resp = authenticated_client.post("/api/auth/touch")
    assert resp.status_code == 200

    with authenticated_client.session_transaction() as sess_after:
        new_activity = sess_after["_clinical_last_activity"]
        assert new_activity != stale
        # new activity must be more recent than stale (within last few seconds)
        new_dt = datetime.fromisoformat(new_activity)
        assert (datetime.now(timezone.utc) - new_dt).total_seconds() < 5


# ════════════════════════════════════════════════════════════════════
# §D — Endpoint /api/auth/session-status (campos G7)
# ════════════════════════════════════════════════════════════════════


def test_g1080_session_status_returns_idle_remaining(authenticated_client):
    """session-status retorna session_seconds_until_idle_timeout."""
    resp = authenticated_client.get("/api/auth/session-status")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["authenticated"] is True
    assert "session_seconds_until_idle_timeout" in payload
    assert isinstance(payload["session_seconds_until_idle_timeout"], int)
    assert payload["session_seconds_until_idle_timeout"] > 0


def test_g1081_session_status_returns_absolute_remaining(authenticated_client):
    """session-status retorna session_seconds_until_absolute_timeout."""
    resp = authenticated_client.get("/api/auth/session-status")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "session_seconds_until_absolute_timeout" in payload
    assert isinstance(payload["session_seconds_until_absolute_timeout"], int)
    assert payload["session_seconds_until_absolute_timeout"] > 0


def test_g1082_session_status_exposes_timeout_config(authenticated_client):
    """session-status retorna idle_timeout_sec + absolute_timeout_sec."""
    resp = authenticated_client.get("/api/auth/session-status")
    payload = resp.get_json()
    assert "idle_timeout_sec" in payload
    assert "absolute_timeout_sec" in payload
    # Sanity: server-side defaults are 1800 (30min) and 28800 (8h)
    assert payload["idle_timeout_sec"] >= 60
    assert payload["absolute_timeout_sec"] >= 60


def test_g1083_session_status_returns_expiry_reason(authenticated_client):
    """session-status retorna expiry_reason consistente."""
    resp = authenticated_client.get("/api/auth/session-status")
    payload = resp.get_json()
    assert payload.get("expiry_reason") == "valid"


def test_g1084_session_status_does_NOT_touch_activity(authenticated_client):
    """session-status NO toca last_activity (es endpoint pasivo)."""
    # Set a stale activity marker
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=180)).isoformat()
    with authenticated_client.session_transaction() as sess:
        sess["_clinical_last_activity"] = stale
        sess["_clinical_touch_count"] = 7

    resp = authenticated_client.get("/api/auth/session-status")
    assert resp.status_code == 200

    with authenticated_client.session_transaction() as sess_after:
        # session-status is passive: no change to activity or count.
        assert sess_after["_clinical_last_activity"] == stale
        assert sess_after["_clinical_touch_count"] == 7


# ════════════════════════════════════════════════════════════════════
# §E — Context processor + config helper
# ════════════════════════════════════════════════════════════════════


def test_g1085_g_vars_populated_in_before_request(app, monkeypatch):
    """g.session_indicator_idle_warning_threshold_sec, _touch_url,
    _touch_debounce_ms, _idle_timeout_sec, _absolute_timeout_sec populated.

    Triggered via test_client GET to a guaranteed-existing endpoint
    (`/api/auth/whoami`) — `before_request` hooks fire before the route,
    so g is populated regardless of which endpoint we hit.
    """
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")
    captured = {}

    def _capture_before_request():
        from flask import g as flask_g
        captured["enabled"] = getattr(flask_g, "session_indicator_enabled", None)
        captured["idle_warning"] = getattr(
            flask_g, "session_indicator_idle_warning_threshold_sec", None,
        )
        captured["touch_url"] = getattr(
            flask_g, "session_indicator_touch_url", None,
        )
        captured["touch_debounce"] = getattr(
            flask_g, "session_indicator_touch_debounce_ms", None,
        )
        captured["idle_timeout"] = getattr(
            flask_g, "session_indicator_idle_timeout_sec", None,
        )
        captured["absolute_timeout"] = getattr(
            flask_g, "session_indicator_absolute_timeout_sec", None,
        )

    # Use test_request_context: this synthesizes a request and runs all
    # before_request hooks (incl. _populate_auth_g from auth_ui_context),
    # so g is populated without going through routing.
    with app.test_request_context("/api/auth/whoami"):
        # Manually trigger the before_request chain
        app.preprocess_request()
        _capture_before_request()

    assert captured["touch_url"] == "/api/auth/touch"
    assert isinstance(captured["idle_warning"], int)
    assert isinstance(captured["touch_debounce"], int)
    assert isinstance(captured["idle_timeout"], int)
    assert isinstance(captured["absolute_timeout"], int)
    assert captured["idle_warning"] > 0
    assert captured["touch_debounce"] >= 1000
