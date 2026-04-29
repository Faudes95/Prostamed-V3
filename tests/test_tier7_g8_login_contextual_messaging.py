"""tests/test_tier7_g8_login_contextual_messaging.py — Faubot 2026-04-25 (XL).

Tests dedicados a Tier 7 G8: Login UI contextual messaging.

Cubre H.G1086 - H.G1092 (7 hipótesis):

§A — Helper de decodificación con whitelist
  H.G1086: decode_session_expiry_reason() acepta "idle"/"absolute" + variantes case
  H.G1087: decode_session_expiry_reason() rechaza valores no-whitelist
           (XSS, scope bleed, type errors → fallback seguro)

§B — Render del template login.html
  H.G1088: ?error=session_expired&reason=idle → mensaje "Cerramos su sesión por inactividad"
  H.G1089: ?error=session_expired&reason=absolute → mensaje "Su jornada de trabajo finalizó"
  H.G1090: ?error=session_expired sin reason → fallback "Su sesión expiró"
           (sin mensajes idle/absolute filtrados)

§C — Seguridad / backward-compat
  H.G1091: ?error=session_expired&reason=<XSS> → script NO renderizado
           + fallback genérico aplicado (whitelist enforcement)
  H.G1092: Otros canales `?error=*` (invalid_credentials, missing_credentials,
           csrf_failed, access_denied) NO contaminados por la lógica G8
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def app():
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


# ════════════════════════════════════════════════════════════════════
# §A — Helper decoder
# ════════════════════════════════════════════════════════════════════


def test_g1086_decoder_accepts_whitelist_variants():
    """decode_session_expiry_reason() acepta whitelist + variantes case/whitespace."""
    from prostanet.shared.auth_backends import (
        decode_session_expiry_reason,
        SESSION_REASON_EXPIRED_IDLE, SESSION_REASON_EXPIRED_ABSOLUTE,
    )
    # Forma corta (la que envía require_clinical_session redirect)
    assert decode_session_expiry_reason("idle") == SESSION_REASON_EXPIRED_IDLE
    assert decode_session_expiry_reason("absolute") == SESSION_REASON_EXPIRED_ABSOLUTE
    # Case-insensitive
    assert decode_session_expiry_reason("IDLE") == SESSION_REASON_EXPIRED_IDLE
    assert decode_session_expiry_reason("Absolute") == SESSION_REASON_EXPIRED_ABSOLUTE
    # Whitespace tolerance (qparam puede traer trailing spaces)
    assert decode_session_expiry_reason("  idle  ") == SESSION_REASON_EXPIRED_IDLE
    # Forma canónica completa (alias también aceptado)
    assert decode_session_expiry_reason("expired_idle") == SESSION_REASON_EXPIRED_IDLE
    assert decode_session_expiry_reason("expired_absolute") == SESSION_REASON_EXPIRED_ABSOLUTE


def test_g1087_decoder_rejects_non_whitelist_values():
    """decode_session_expiry_reason() rechaza valores no-whitelist con fallback."""
    from prostanet.shared.auth_backends import (
        decode_session_expiry_reason,
        SESSION_REASON_UNAUTHENTICATED,
    )
    # XSS attempts
    assert decode_session_expiry_reason("<script>alert(1)</script>") == SESSION_REASON_UNAUTHENTICATED
    assert decode_session_expiry_reason("javascript:alert(1)") == SESSION_REASON_UNAUTHENTICATED
    # Privilege escalation attempts
    assert decode_session_expiry_reason("admin") == SESSION_REASON_UNAUTHENTICATED
    assert decode_session_expiry_reason("root") == SESSION_REASON_UNAUTHENTICATED
    # Type errors (no-string)
    assert decode_session_expiry_reason(None) == SESSION_REASON_UNAUTHENTICATED
    assert decode_session_expiry_reason(42) == SESSION_REASON_UNAUTHENTICATED
    assert decode_session_expiry_reason(["idle"]) == SESSION_REASON_UNAUTHENTICATED
    # Empty string
    assert decode_session_expiry_reason("") == SESSION_REASON_UNAUTHENTICATED
    assert decode_session_expiry_reason("   ") == SESSION_REASON_UNAUTHENTICATED


# ════════════════════════════════════════════════════════════════════
# §B — Template rendering
# ════════════════════════════════════════════════════════════════════


def test_g1088_login_render_idle_reason(client):
    """?error=session_expired&reason=idle → mensaje 'Cerramos su sesión por inactividad'."""
    resp = client.get("/login?error=session_expired&reason=idle")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Mensaje primario
    assert "Cerramos su sesión por inactividad" in html
    # Compliance hint visible (HIPAA mencionado en lenguaje claro)
    assert "HIPAA" in html
    assert "automáticamente" in html
    # NO debe mostrar mensaje absolute
    assert "Su jornada de trabajo finalizó" not in html


def test_g1089_login_render_absolute_reason(client):
    """?error=session_expired&reason=absolute → mensaje 'Su jornada de trabajo finalizó'."""
    resp = client.get("/login?error=session_expired&reason=absolute")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Mensaje primario
    assert "Su jornada de trabajo finalizó" in html
    # Detail clarification (NO indica problema con la cuenta)
    assert "re-autenticarse" in html
    assert "NO indica un problema con su cuenta" in html
    # NO debe mostrar mensaje idle
    assert "Cerramos su sesión por inactividad" not in html


def test_g1090_login_render_session_expired_no_reason(client):
    """?error=session_expired sin reason → fallback genérico, sin idle/absolute leaked."""
    resp = client.get("/login?error=session_expired")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Mensaje genérico (preserva backward-compat con clientes pre-G8)
    assert "Su sesión expiró" in html
    assert "inicie sesión nuevamente" in html
    # NO debe filtrar mensajes contextuales sin info real
    assert "Cerramos su sesión por inactividad" not in html
    assert "Su jornada de trabajo finalizó" not in html


# ════════════════════════════════════════════════════════════════════
# §C — Seguridad + backward-compat
# ════════════════════════════════════════════════════════════════════


def test_g1091_login_xss_attempt_in_reason_is_sanitized(client):
    """?error=session_expired&reason=<XSS> → script NO renderizado + fallback genérico."""
    # URL-encoded XSS payload pasado como `reason=`
    resp = client.get(
        "/login?error=session_expired&reason=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Crítico: no se debe renderizar el script
    assert "<script>alert" not in html
    assert "alert(1)" not in html
    # Whitelist enforcement → cae a mensaje genérico (NO idle, NO absolute)
    assert "Su sesión expiró" in html
    assert "Cerramos su sesión por inactividad" not in html
    assert "Su jornada de trabajo finalizó" not in html

    # Variante 2: `reason=admin` (privilege-escalation attempt)
    resp2 = client.get("/login?error=session_expired&reason=admin")
    html2 = resp2.get_data(as_text=True)
    assert "admin" not in html2.lower() or "administrador" in html2.lower()  # ningún rol levantado en mensaje
    assert "Su sesión expiró" in html2  # genérico aplicado


def test_g1092_other_error_channels_unaffected_by_g8(client):
    """Otros `?error=*` codes NO contaminados por la lógica G8 (regression guard)."""
    # invalid_credentials (Tier 7 G2)
    resp = client.get("/login?error=invalid_credentials")
    html = resp.get_data(as_text=True)
    assert "Credenciales inválidas" in html
    assert "Su sesión expiró" not in html  # canal session_expired NO debe activarse
    assert "Cerramos su sesión por inactividad" not in html

    # missing_credentials (Tier 7 G2)
    resp = client.get("/login?error=missing_credentials")
    html = resp.get_data(as_text=True)
    assert "Faltan credenciales" in html
    assert "Su sesión expiró" not in html

    # csrf_failed (Tier 7 G2)
    resp = client.get("/login?error=csrf_failed")
    html = resp.get_data(as_text=True)
    assert "Sesión inválida" in html
    assert "Cerramos su sesión por inactividad" not in html

    # access_denied (Tier 7 G2 — IDP rejection)
    resp = client.get("/login?error=access_denied")
    html = resp.get_data(as_text=True)
    assert "Acceso denegado" in html
    assert "Su jornada de trabajo finalizó" not in html

    # logged_out (success state, no error)
    resp = client.get("/login?logged_out=1")
    html = resp.get_data(as_text=True)
    assert "Sesión cerrada correctamente" in html

    # Sin query → ningún mensaje de alerta
    resp = client.get("/login")
    html = resp.get_data(as_text=True)
    assert "role=\"alert\"" not in html
