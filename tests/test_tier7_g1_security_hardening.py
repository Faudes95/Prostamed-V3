"""tests/test_tier7_g1_security_hardening.py — Tier 7 G1 (Faubot XXV).

Cobertura de los 4 críticos P0 implementados del security review:

  - CRIT-1 (PHI scrubbing): scrub_phi_for_audit + safe_patient_identity
  - CRIT-2 (secret_key + bind): get_secret_key + get_bind_host
  - CRIT-3 (decorator): require_clinical_session placeholder
  - CRIT-4 (error sanitization): error_response_with_trace_id

Hipótesis verificables: H.G346 - H.G375 (30 hipótesis).

Implementado en 2026-04-25 como parte del cierre Tier 7 G1, autorización
del usuario tras Audit #37 (cierre arquitectónico del bucle Faubot).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import json
import os
import re
from unittest import mock

import pytest

from prostanet.shared.security_helpers import (
    error_response_with_trace_id,
    get_bind_host,
    get_secret_key,
    is_clinical_auth_enabled,
    require_clinical_session,
    safe_patient_identity,
    scrub_phi_for_audit,
)


# ════════════════════════════════════════════════════════════════════
# CRIT-1 — PHI scrubbing (10 tests)
# ════════════════════════════════════════════════════════════════════


# H.G346
def test_crit1_scrub_phi_redacts_nss_field():
    """H.G346 — scrub_phi_for_audit redacta `nss` field."""
    out = scrub_phi_for_audit({"nss": "12345678901", "psa": 35})
    assert out["nss"] == "[REDACTED-PHI]"
    assert out["psa"] == 35  # clinical preserved


# H.G347
def test_crit1_scrub_phi_redacts_full_name_field():
    """H.G347 — scrub_phi_for_audit redacta `full_name` field."""
    out = scrub_phi_for_audit({"full_name": "Juan Pérez", "qtc_ms": 510})
    assert out["full_name"] == "[REDACTED-PHI]"
    assert out["qtc_ms"] == 510


# H.G348
@pytest.mark.parametrize("field_name", [
    "nss", "patient_name", "first_name", "last_name", "phone",
    "email", "birth_date", "dob", "curp", "rfc", "address",
])
def test_crit1_scrub_phi_redacts_known_phi_fields(field_name):
    """H.G348 — Todos los campos PHI canónicos quedan redactados."""
    out = scrub_phi_for_audit({field_name: "anything", "psa": 35})
    assert out[field_name] == "[REDACTED-PHI]"


# H.G349
def test_crit1_scrub_phi_recursive_nested_dicts():
    """H.G349 — Redacción recursiva en dicts anidados."""
    sample = {
        "level1": {"nss": "12345678901", "psa": 35, "level2": {"phone": "555"}}
    }
    out = scrub_phi_for_audit(sample)
    assert out["level1"]["nss"] == "[REDACTED-PHI]"
    assert out["level1"]["psa"] == 35
    assert out["level1"]["level2"]["phone"] == "[REDACTED-PHI]"


# H.G350
def test_crit1_scrub_phi_value_pattern_email():
    """H.G350 — Detecta y redacta emails en valores libres."""
    out = scrub_phi_for_audit({"notes": "contacto: juan@example.com"})
    assert out["notes"] == "[REDACTED-PHI]"


# H.G351
def test_crit1_scrub_phi_value_pattern_nss_11_digits():
    """H.G351 — Detecta y redacta NSS de 11 dígitos en valores libres."""
    out = scrub_phi_for_audit({"notes": "NSS 12345678901 verificado"})
    assert out["notes"] == "[REDACTED-PHI]"


# H.G352
def test_crit1_scrub_phi_preserves_clinical_values():
    """H.G352 — Valores clínicos numéricos NUNCA se redactan."""
    sample = {
        "psa": 35, "gleason_primary": 4, "qtc_ms": 510,
        "lvef_percent": 55, "anc": 4500, "platelets": 240000,
        "creatinine_clearance": 90, "age": 70,
    }
    out = scrub_phi_for_audit(sample)
    for k, v in sample.items():
        assert out[k] == v, f"{k} fue mutado: {v} → {out[k]}"


# H.G353
def test_crit1_scrub_phi_preserves_lists():
    """H.G353 — Listas (e.g., medications) preservadas pero recorridas."""
    out = scrub_phi_for_audit({
        "medications": ["lisinopril", "atorvastatina"],
        "trial_refs": ["ENZAMET", "ARCHES"],
    })
    assert out["medications"] == ["lisinopril", "atorvastatina"]
    assert out["trial_refs"] == ["ENZAMET", "ARCHES"]


# H.G354
def test_crit1_scrub_phi_empty_input():
    """H.G354 — Input vacío/None retorna {} (no crash)."""
    assert scrub_phi_for_audit({}) == {}
    assert scrub_phi_for_audit(None) == {}


# H.G355
def test_crit1_safe_patient_identity_default_minimal():
    """H.G355 — safe_patient_identity default redacta NSS + full_name."""
    identity = {"id": 42, "nss": "12345678901", "full_name": "Juan Pérez"}
    out = safe_patient_identity(identity)
    assert "nss" not in out
    assert "full_name" not in out
    assert out["id"] == 42
    assert out["display_label"].startswith("P-")
    assert out["phi_disclosed"] is False


# H.G356
def test_crit1_safe_patient_identity_include_phi_explicit():
    """H.G356 — safe_patient_identity(include_phi=True) expone NSS + name."""
    identity = {"id": 42, "nss": "12345678901", "full_name": "Juan Pérez"}
    out = safe_patient_identity(identity, include_phi=True)
    assert out["nss"] == "12345678901"
    assert out["full_name"] == "Juan Pérez"
    assert out["phi_disclosed"] is True


# H.G357
def test_crit1_safe_patient_identity_none_input():
    """H.G357 — safe_patient_identity(None) retorna estructura segura."""
    out = safe_patient_identity(None)
    assert out["display_label"] == "P-unknown"
    assert out["id"] is None


# H.G358
def test_crit1_decision_audit_endpoint_scrubs_phi():
    """H.G358 — endpoint /api/decision-audit/<ref> aplica PHI scrubbing
    al input_snapshot (sanity check del decision_audit_builder integration)."""
    from prostanet.shared.decision_audit_builder import build_decision_audit
    mock_assessment = {
        "id": 1,
        "module_id": "m1_crpc",
        "state": "m1_crpc",
        "input_snapshot": {
            "nss": "98765432101",       # debe redactar
            "full_name": "Test Patient", # debe redactar
            "psa": 35,                   # NO debe redactar
            "qtc_ms": 510,               # NO
        },
        "result_snapshot": {
            "state": "m1_crpc",
            "pivotal_contraindication_gates": [],
        },
    }
    audit = build_decision_audit(
        patient_id=42,
        patient_identity={"id": 42, "nss": "98765432101"},
        latest_assessment=mock_assessment,
    )
    snapshot = audit["audit_dimensions"]["datos"]["input_snapshot"]
    assert snapshot["nss"] == "[REDACTED-PHI]"
    assert snapshot["full_name"] == "[REDACTED-PHI]"
    assert snapshot["psa"] == 35
    assert snapshot["qtc_ms"] == 510
    # Marker explícito para clientes
    assert audit["audit_dimensions"]["datos"]["input_phi_scrubbed"] is True


# ════════════════════════════════════════════════════════════════════
# CRIT-2 — secret_key + bind hardening (5 tests)
# ════════════════════════════════════════════════════════════════════


# H.G359
def test_crit2_get_secret_key_from_env(monkeypatch):
    """H.G359 — get_secret_key lee PROSTANET_SECRET_KEY env."""
    monkeypatch.setenv("PROSTANET_SECRET_KEY", "explicit-secret-key-xyz")
    assert get_secret_key() == "explicit-secret-key-xyz"


# H.G360
def test_crit2_get_secret_key_testing_fallback(monkeypatch):
    """H.G360 — En TESTING (PYTEST_CURRENT_TEST set), usa key dev."""
    monkeypatch.delenv("PROSTANET_SECRET_KEY", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_x")
    key = get_secret_key()
    assert key == "dev-test-secret-key-not-for-production-faubot-xxv"


# H.G361
def test_crit2_get_secret_key_production_raises(monkeypatch):
    """H.G361 — En FLASK_ENV=production sin secret_key, RAISES."""
    monkeypatch.delenv("PROSTANET_SECRET_KEY", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")
    with pytest.raises(RuntimeError, match="PROSTANET_SECRET_KEY"):
        get_secret_key()


# H.G362
def test_crit2_get_bind_host_default_localhost(monkeypatch):
    """H.G362 — Default bind a 127.0.0.1 (no expone red)."""
    monkeypatch.delenv("PROSTANET_ALLOW_PUBLIC_BIND", raising=False)
    assert get_bind_host() == "127.0.0.1"


# H.G363
def test_crit2_get_bind_host_explicit_public(monkeypatch):
    """H.G363 — Con PROSTANET_ALLOW_PUBLIC_BIND=true, expone 0.0.0.0."""
    monkeypatch.setenv("PROSTANET_ALLOW_PUBLIC_BIND", "true")
    assert get_bind_host() == "0.0.0.0"


# ════════════════════════════════════════════════════════════════════
# CRIT-3 — require_clinical_session placeholder (5 tests)
# ════════════════════════════════════════════════════════════════════


# H.G364
def test_crit3_is_clinical_auth_enabled_default_false(monkeypatch):
    """H.G364 — Default CLINICAL_AUTH_ENABLED es False (modo dormant)."""
    monkeypatch.delenv("CLINICAL_AUTH_ENABLED", raising=False)
    assert is_clinical_auth_enabled() is False


# H.G365
@pytest.mark.parametrize("env_value", ["true", "yes", "1", "TRUE", "Yes"])
def test_crit3_is_clinical_auth_enabled_true_variants(monkeypatch, env_value):
    """H.G365 — CLINICAL_AUTH_ENABLED reconoce variantes truthy."""
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", env_value)
    assert is_clinical_auth_enabled() is True


# H.G366
def test_crit3_decorator_marks_function_as_protected():
    """H.G366 — Decorator marca el endpoint como PHI-protected (introspectable)."""
    @require_clinical_session(scope="phi:read")
    def my_endpoint():
        return "ok"

    assert my_endpoint._clinical_session_required is True
    assert my_endpoint._required_scope == "phi:read"


# H.G367
def test_crit3_decorator_dormant_passes_through(monkeypatch):
    """H.G367 — En modo dormant (default), el decorator NO bloquea."""
    monkeypatch.delenv("CLINICAL_AUTH_ENABLED", raising=False)

    @require_clinical_session(scope="phi:read", audit_log=False)
    def my_endpoint():
        return "executed"

    # Sin Flask context, simulamos invocación directa
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/"):
        result = my_endpoint()
    assert result == "executed"


# H.G368
def test_crit3_decorator_active_returns_401(monkeypatch):
    """H.G368 — Con CLINICAL_AUTH_ENABLED=true + sin sesión, decorator retorna 401.

    Faubot 2026-04-25 (XXVIII) — Tier 7 G1.5: el mensaje cambió de
    "Clinical auth required..." (placeholder) a "Authentication required."
    (real check de sesión via auth_backends.session_user_id).

    Faubot 2026-04-25 (XXXII) — Tier 7 G5: añadido Accept: application/json
    header explícito porque el decorator ahora defaultea a HTML redirect
    (302) sin Accept header. Para preservar G1.5 401 JSON behavior,
    el test debe declarar JSON intent.
    """
    monkeypatch.setenv("CLINICAL_AUTH_ENABLED", "true")

    @require_clinical_session(scope="phi:read", audit_log=False)
    def my_endpoint():
        return "should not reach"

    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "test-secret-key-for-session"
    # G5: explicit JSON Accept preserva G1.5 401 JSON behavior
    with app.test_request_context("/", headers={"Accept": "application/json"}):
        response, status = my_endpoint()
    assert status == 401
    data = json.loads(response.get_data(as_text=True))
    assert data["success"] is False
    # Post-G1.5: mensaje genérico "Authentication required." sin filtrar detalle
    assert "authentication required" in data["error"].lower() or "auth" in data["error"].lower()


# ════════════════════════════════════════════════════════════════════
# CRIT-4 — error_response_with_trace_id (6 tests)
# ════════════════════════════════════════════════════════════════════


# H.G369
def test_crit4_error_response_returns_trace_id():
    """H.G369 — error_response_with_trace_id retorna trace_id en JSON."""
    from flask import Flask
    app = Flask(__name__)
    exc = ValueError("internal database error with /var/data/sensitive_path")
    with app.test_request_context("/"):
        response, status = error_response_with_trace_id(exc)
    assert status == 500
    data = json.loads(response.get_data(as_text=True))
    assert data["success"] is False
    assert "trace_id" in data
    # UUID4 format check
    assert re.match(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
                    data["trace_id"]), f"trace_id mal formado: {data['trace_id']}"


# H.G370
def test_crit4_error_response_does_not_leak_exc_str():
    """H.G370 — error_response_with_trace_id NO devuelve str(exc) al cliente."""
    from flask import Flask
    app = Flask(__name__)
    exc = RuntimeError("FATAL: /etc/passwd permission denied for user 'admin'")
    with app.test_request_context("/"):
        response, status = error_response_with_trace_id(exc)
    data = json.loads(response.get_data(as_text=True))
    body = json.dumps(data)
    # Cero leak de paths/usernames
    assert "/etc/passwd" not in body
    assert "permission denied" not in body
    assert "admin" not in body
    # Solo mensaje genérico + trace_id
    assert data["error"] == "Internal server error."


# H.G371
def test_crit4_error_response_custom_status_code():
    """H.G371 — Acepta status_code custom (e.g., 502, 503)."""
    from flask import Flask
    app = Flask(__name__)
    exc = ConnectionError("upstream gateway timeout")
    with app.test_request_context("/"):
        response, status = error_response_with_trace_id(
            exc, status_code=502, user_message="Upstream service unavailable.",
        )
    assert status == 502
    data = json.loads(response.get_data(as_text=True))
    assert data["error"] == "Upstream service unavailable."


# H.G372
def test_crit4_error_response_log_extra_propagated(caplog):
    """H.G372 — log_extra (e.g., patient_ref) se propaga al log server-side."""
    import logging
    from flask import Flask
    app = Flask(__name__)
    exc = ValueError("test exception")
    with app.test_request_context("/"):
        with caplog.at_level(logging.ERROR, logger="prostanet.shared.security_helpers"):
            error_response_with_trace_id(
                exc, log_extra={"patient_ref": "test-ref-123"},
            )
    log_text = " ".join(r.message for r in caplog.records)
    assert "test-ref-123" in log_text
    assert "trace_id" in log_text


# H.G373
def test_crit4_endpoint_decision_audit_uses_trace_id_on_500():
    """H.G373 — endpoint /api/decision-audit/<ref> retorna trace_id en 500
    cuando hay excepción interna (e.g., DB unreachable)."""
    import app as app_module
    app = app_module.create_app({"TESTING": True})
    # Mock para forzar Exception interna
    with mock.patch(
        "tracking_db.get_patient_full_record_by_ref",
        side_effect=RuntimeError("DB connection lost on /tmp/secret.db"),
    ):
        with app.test_client() as client:
            resp = client.get("/api/decision-audit/some-id")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
    assert "trace_id" in data
    body = json.dumps(data)
    assert "/tmp/secret.db" not in body
    assert "DB connection lost" not in body


# ════════════════════════════════════════════════════════════════════
# Cross-CRIT integration: endpoint completo respeta los 4 críticos
# ════════════════════════════════════════════════════════════════════


# H.G374
def test_crit_integration_endpoint_404_no_trace_id_leak():
    """H.G374 — endpoint con paciente inexistente sigue retornando 404
    limpio (sin trace_id, no es excepción)."""
    import app as app_module
    app = app_module.create_app({"TESTING": True})
    with app.test_client() as client:
        resp = client.get("/api/decision-audit/99999999999")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    # 404 NO debe incluir trace_id (no es excepción interna)
    assert "trace_id" not in data


# H.G375
def test_crit_integration_app_secret_key_set():
    """H.G375 — create_app configura app.secret_key (CRIT-2)."""
    import app as app_module
    app = app_module.create_app({"TESTING": True})
    assert app.secret_key is not None
    assert len(app.secret_key) > 10
