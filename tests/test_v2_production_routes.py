"""E2E tests para las 6 rutas v2 de producción + endpoint append.

Faubot 2026-04-26 LXXVIII (#67E).

Requiere servidor Flask corriendo en localhost:8080. Los tests con
@requires_server se saltan si el server no responde.

Run:
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/homebrew/bin/python3.12 -m pytest \
        tests/test_v2_production_routes.py -v --no-header -c /dev/null \
        --rootdir=/tmp -o cache_dir=/tmp/pytest_cache
"""
# IEC 62304 §5.5 (Unit verification)


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import urllib.request
import urllib.error
import json as _json
from datetime import datetime

BASE = "http://127.0.0.1:8080"
TEST_NSS = "97000000001"  # "Paciente MCP Flujo ADT" — paciente real en DB


def _server_alive() -> bool:
    try:
        urllib.request.urlopen(BASE + "/", timeout=1.5)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


requires_server = pytest.mark.skipif(
    not _server_alive(), reason="Flask dev server not running on localhost:8080"
)


def _get(path: str) -> tuple[int, str]:
    try:
        resp = urllib.request.urlopen(BASE + path, timeout=10)
        return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""


def _post_json(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=_json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = _json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload


# ── Las 6 rutas v2 producción → 200 OK ─────────────────────────────────────

@requires_server
def test_route_patient_profile_v2_default():
    """v2 es DEFAULT. Sin ?v=2 ni ?v=legacy → renderiza v2."""
    code, html = _get(f"/patient_profile/{TEST_NSS}")
    assert code == 200
    assert "pm2-app-shell" in html
    assert "DECISIÓN HOY" in html or "decision-hoy-title" in html
    assert html.count('class="pm2-tab') >= 9
    assert "prostamed_logo_official.png" in html

@requires_server
def test_route_patient_profile_v2_explicit():
    """?v=2 explicit también funciona (backward-compat)."""
    code, html = _get(f"/patient_profile/{TEST_NSS}?v=2")
    assert code == 200
    assert "pm2-app-shell" in html

@requires_server
def test_route_patient_profile_legacy_optout():
    """?v=legacy escape hatch al template legacy."""
    code, html = _get(f"/patient_profile/{TEST_NSS}?v=legacy")
    assert code == 200
    assert "pm2-app-shell" not in html  # legacy NO tiene v2 shell

@requires_server
def test_route_clinical_result():
    code, html = _get(f"/clinical-result/{TEST_NSS}")
    assert code == 200
    assert "pm2-decision-hero" in html
    assert "Firma electrónica" in html or "Firma" in html

@requires_server
def test_route_longitudinal_capture():
    code, html = _get(f"/longitudinal-capture/{TEST_NSS}")
    assert code == 200
    assert "pm2-baseline-locked" in html or "baseline-locked" in html
    assert "pm2-append-section" in html

@requires_server
def test_route_dashboard_v2_default():
    """Dashboard v2 ahora es default."""
    code, html = _get("/dashboard")
    assert code == 200
    assert "pm2-kpi-card" in html

@requires_server
def test_route_clinical_hub_v2_default():
    """Centro Clínico v2 ahora es default."""
    code, html = _get("/clinical-hub")
    assert code == 200
    assert "pm2-stage-rail" in html or "stage-rail" in html

@requires_server
def test_route_patients_v2_default():
    """Cohorte v2 ahora es default."""
    code, html = _get("/patients")
    assert code == 200
    assert "pm2-cohort-table" in html

@requires_server
def test_route_patient_intake_v2():
    """Nuevo ingreso redirige al clasificador oficial."""
    code, html = _get("/patient_intake?v=2")
    assert code == 200
    assert "pm2OfficialClassifier" in html


# ── Legacy escape hatch via ?v=legacy ───────────────────────────────────

@requires_server
def test_legacy_dashboard_optout():
    """?v=legacy retorna template legacy."""
    code, html = _get("/dashboard?v=legacy")
    assert code == 200
    assert "pm2-kpi-card" not in html

@requires_server
def test_legacy_clinical_hub_optout():
    code, html = _get("/clinical-hub?v=legacy")
    assert code == 200
    assert "pm2-stage-rail" not in html

@requires_server
def test_legacy_patients_optout():
    code, html = _get("/patients?v=legacy")
    assert code == 200
    assert "pm2-cohort-table" not in html


# ── Compact profile DEPRECATED → 410 Gone ───────────────────────────────

@requires_server
def test_compact_profile_returns_410_gone():
    """Compact removed: returns 410 Gone with use_instead pointer."""
    code, body = _get("/demos/v2/patient_profile")
    assert code == 410


# ── Endpoint append-only API ─────────────────────────────────────────────

@requires_server
def test_append_psa_success():
    """Append PSA único → 200 + persisted_id."""
    today = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    # Use a date in the future to avoid colliding with previous test runs
    code, body = _post_json(
        f"/api/longitudinal/{TEST_NSS}/append",
        {"kind": "psa", "payload": {"date": "2030-01-01", "value": 99.99,
                                     "context": f"e2e_test_{today}"}},
    )
    # Either 200 (first time) or 409 (already exists from prior run)
    assert code in (200, 409)
    if code == 200:
        assert body.get("success") is True
        assert "appended_id" in body
        assert body.get("biomarker_type") == "PSA"
    else:
        assert body.get("error") == "duplicate"

@requires_server
def test_append_duplicate_returns_409():
    """Mismo date → segundo POST debe ser 409."""
    body_payload = {"kind": "psa", "payload": {"date": "2031-01-01", "value": 88.88}}
    # First POST
    code1, body1 = _post_json(f"/api/longitudinal/{TEST_NSS}/append", body_payload)
    assert code1 in (200, 409)  # 200 first time, 409 from prior
    # Second POST (same date) → must be 409
    code2, body2 = _post_json(f"/api/longitudinal/{TEST_NSS}/append", body_payload)
    assert code2 == 409
    assert body2.get("error") == "duplicate"
    assert "existing_id" in body2

@requires_server
def test_append_patient_not_found():
    code, body = _post_json(
        "/api/longitudinal/NSS_DOES_NOT_EXIST/append",
        {"kind": "psa", "payload": {"date": "2026-01-01", "value": 5.0}},
    )
    assert code == 404
    assert body.get("error") == "patient_not_found"

@requires_server
def test_append_missing_kind():
    code, body = _post_json(
        f"/api/longitudinal/{TEST_NSS}/append",
        {"payload": {"value": 5.0}},  # no kind
    )
    assert code == 400
    assert "kind" in body.get("error", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
