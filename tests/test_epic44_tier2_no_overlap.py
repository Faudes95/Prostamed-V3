"""EPIC 44.C — Tier 2 Asistente por estadio (sin overlap).

Cobertura:
  - stage_specific_intake_schema(exclude_tier1_overlap=True) filtra fields
    cuyo nombre coincide con whitelist Tier 1
  - Fields supervivientes marcados tier=2 + tier2_exclusive=True
  - tier1_captured_codes reporta los nombres filtrados
  - Schema sin exclude_tier1_overlap (default) NO filtra (back-compat)
  - Routes /intake/tier2/<state> y /api/intake/tier2/<state> funcionan
  - POST echo retorna fields_submitted + received_keys + next_action
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Schema filter tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", [
    "localized_initial",
    "mcspc_low_volume_sync_oligo",
    "m1_crpc",
    "post_prostatectomy",
    "recurrence_bcr",
])
def test_exclude_tier1_overlap_filters_anchor_fields(state):
    """En todos los estadios canónicos, filtrar Tier 1 reduce el count.

    EPIC 44.C.2 — el filtro Tier 2 ahora combina tier1_overlap + cross_cutting.
    El delta del total debe igualar la suma de ambos excluded counts.
    """
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema

    full = stage_specific_intake_schema(state, exclude_tier1_overlap=False)
    filtered = stage_specific_intake_schema(state, exclude_tier1_overlap=True)

    assert filtered["total_fields"] <= full["total_fields"], (
        f"State {state}: filtered count {filtered['total_fields']} > full "
        f"{full['total_fields']} — filtro debe reducir o mantener."
    )
    # EPIC 44.C.2 — delta = tier1_overlap + cross_cutting
    expected_delta = (
        filtered["tier1_excluded_count"] + filtered["cross_cutting_excluded_count"]
    )
    assert expected_delta == (full["total_fields"] - filtered["total_fields"]), (
        f"State {state}: tier1_excluded ({filtered['tier1_excluded_count']}) "
        f"+ cross_cutting_excluded ({filtered['cross_cutting_excluded_count']}) "
        f"debe igualar el delta total ({full['total_fields']} - {filtered['total_fields']})"
    )
    assert filtered["tier1_excluded_count"] >= 1, (
        f"State {state}: esperaba al menos 1 overlap con Tier 1 "
        f"(ej. ecog_score o histology_subtype), got 0"
    )


def test_tier2_fields_marked_tier2_exclusive():
    """Cada field superviviente al filtro tiene tier=2 + tier2_exclusive=True."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    s = stage_specific_intake_schema("m1_crpc", exclude_tier1_overlap=True)
    for f in s["fields"]:
        assert f.get("tier") == 2, f"Field {f['name']!r} sin tier=2"
        assert f.get("tier2_exclusive") is True, (
            f"Field {f['name']!r} sin tier2_exclusive=True"
        )


def test_tier1_captured_codes_excludes_tier1_anchor_only():
    """tier1_captured_codes solo contiene nombres del whitelist Tier 1."""
    from prostanet.presentation.v2_adapters import (
        stage_specific_intake_schema,
        _TIER1_FIELD_NAMES_ORDERED,
    )
    tier1_set = set(_TIER1_FIELD_NAMES_ORDERED)
    for state in ["mcspc_low_volume_sync_oligo", "m1_crpc", "localized_initial"]:
        s = stage_specific_intake_schema(state, exclude_tier1_overlap=True)
        for code in s["tier1_captured_codes"]:
            assert code in tier1_set, (
                f"State {state}: tier1_captured_codes contiene {code!r} "
                "que NO está en el whitelist Tier 1 — filtro mal calibrado"
            )


def test_default_behavior_no_filter_preserves_backcompat():
    """Sin exclude_tier1_overlap, el schema NO filtra (back-compat)."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    s = stage_specific_intake_schema("m1_crpc")  # default False
    assert s["tier"] is None  # no tier label cuando no filtra
    assert s["tier1_excluded_count"] == 0
    assert s["tier1_captured_codes"] == []
    # Fields NO marcados como tier2
    for f in s["fields"][:5]:
        assert f.get("tier2_exclusive") is None or f.get("tier2_exclusive") is False


def test_unknown_state_does_not_crash():
    """State inexistente retorna fallback (no rompe)."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    s = stage_specific_intake_schema("not_a_real_state", exclude_tier1_overlap=True)
    assert "fields" in s


# ─────────────────────────────────────────────────────────────────────────────
# Routes tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    from app import app, create_app
    create_app()
    return app.test_client()


def test_route_intake_tier2_renders_200(app_client):
    """GET /intake/tier2/<state> → 200 con banner Tier 2."""
    r = app_client.get("/intake/tier2/mcspc_low_volume_sync_oligo?nss=TEST")
    assert r.status_code == 200
    assert b"Tier 2" in r.data
    assert b"Asistente" in r.data
    assert b"mcspc_low_volume_sync_oligo" in r.data


def test_route_intake_tier2_includes_tier1_info_when_overlap_filtered(app_client):
    """Cuando hay overlap, banner muestra "X ya capturados en Tier 1"."""
    r = app_client.get("/intake/tier2/localized_initial?nss=TEST")
    html = r.data.decode("utf-8", errors="ignore")
    # localized_initial tiene 8 fields de overlap (todos los anchor + visceral_mets)
    assert "ya capturados en Tier 1" in html, (
        "Banner debe mostrar contador de fields capturados en Tier 1"
    )


def test_api_tier2_get_returns_filtered_schema(app_client):
    """GET /api/intake/tier2/<state> → JSON con schema filtrado."""
    r = app_client.get("/api/intake/tier2/mcspc_low_volume_sync_oligo?nss=ABC")
    body = r.get_json()
    assert body["success"] is True
    assert body["tier"] == 2
    assert body["state"] == "mcspc_low_volume_sync_oligo"
    assert body["nss"] == "ABC"
    s = body["schema"]
    assert s["tier"] == 2
    assert s["tier1_excluded_count"] >= 1


def test_api_tier2_include_tier1_returns_full_schema(app_client):
    """?include_tier1=1 retorna schema completo sin filtro."""
    r = app_client.get("/api/intake/tier2/mcspc_low_volume_sync_oligo?include_tier1=1")
    body = r.get_json()
    assert body["tier"] is None  # no tier label cuando incluye Tier 1
    assert body["schema"]["tier1_excluded_count"] == 0


def test_api_tier2_post_echoes_payload(app_client):
    """POST /api/intake/tier2/<state> → echo + ack + next_action."""
    payload = {
        "psma_pet_done": "1",
        "bone_protection_started": "1",
        "ddi_review_status": "completed_no_interactions",
    }
    r = app_client.post(
        "/api/intake/tier2/m1_crpc?nss=NSS-X",
        data=json.dumps(payload),
        content_type="application/json",
    )
    body = r.get_json()
    assert body["success"] is True
    assert body["tier"] == 2
    assert body["state"] == "m1_crpc"
    assert body["nss"] == "NSS-X"
    assert body["fields_submitted"] == 3
    assert "psma_pet_done" in body["received_keys"]
    assert body["next_action"] == "/patient/NSS-X?v=2"


def test_api_tier2_post_no_nss_falls_back_to_patients(app_client):
    """POST sin nss → next_action = /patients (lista general)."""
    r = app_client.post(
        "/api/intake/tier2/m1_crpc",
        data=json.dumps({"foo": "bar"}),
        content_type="application/json",
    )
    body = r.get_json()
    assert body["next_action"] == "/patients"
    assert body["nss"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Template artifact tests
# ─────────────────────────────────────────────────────────────────────────────

def test_template_intake_tier2_exists_and_uses_display_options():
    """templates/intake_tier2.html usa f.display_options + block content."""
    p = (Path(__file__).resolve().parent.parent / "templates" / "intake_tier2.html")
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "{% for opt in f.options %}" not in content, (
        "intake_tier2.html no debe iterar f.options raw"
    )
    assert "f.display_options" in content
    assert "{% block content %}" in content
    assert 't2-banner' in content
    assert 't2-role-section' in content


# ─────────────────────────────────────────────────────────────────────────────
# EPIC 44.C.2 — Cross-cutting filter tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state,max_focal_fields", [
    ("mcspc_low_volume_sync_oligo", 25),   # promesa "13-25 fields nuevos"
    ("mcspc_high_volume_sync", 40),
    ("m0_crpc", 60),
    ("post_prostatectomy", 60),
])
def test_tier2_focal_count_within_promise(state, max_focal_fields):
    """Tier 2 focal (default) cumple promesa "fields nuevos manejables"."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    s = stage_specific_intake_schema(state, exclude_tier1_overlap=True)
    assert s["total_fields"] <= max_focal_fields, (
        f"State {state}: Tier 2 focal tiene {s['total_fields']} fields, "
        f"supera el límite blando de {max_focal_fields}. Cross-cutting filter "
        "debe agregar más groups al blocklist o el schema debe revisarse."
    )


def test_tier2_cross_cutting_filter_reports_excluded_groups():
    """schema['cross_cutting_excluded_groups'] reporta qué grupos se filtraron."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    s = stage_specific_intake_schema(
        "mcspc_low_volume_sync_oligo", exclude_tier1_overlap=True,
    )
    assert s["cross_cutting_filter_active"] is True
    assert s["cross_cutting_excluded_count"] > 100, (
        f"mcspc_low_vol debería excluir >100 cross-cutting fields, "
        f"got {s['cross_cutting_excluded_count']}"
    )
    assert "Soportes adicionales de gates pivote" in s["cross_cutting_excluded_groups"]


def test_tier2_include_cross_cutting_opt_in_returns_full_schema():
    """include_cross_cutting=True desactiva el filtro (opt-in vista experta)."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    focal = stage_specific_intake_schema(
        "mcspc_low_volume_sync_oligo", exclude_tier1_overlap=True,
    )
    with_cross = stage_specific_intake_schema(
        "mcspc_low_volume_sync_oligo",
        exclude_tier1_overlap=True,
        include_cross_cutting=True,
    )
    assert with_cross["total_fields"] > focal["total_fields"], (
        "include_cross_cutting=True debe retornar más fields que focal"
    )
    assert with_cross["cross_cutting_filter_active"] is False
    assert with_cross["cross_cutting_excluded_count"] == 0


def test_tier2_cross_cutting_filter_off_when_exclude_tier1_off():
    """Si exclude_tier1_overlap=False, el cross-cutting filter NO se activa."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    full = stage_specific_intake_schema(
        "mcspc_low_volume_sync_oligo", exclude_tier1_overlap=False,
    )
    assert full["cross_cutting_filter_active"] is False
    assert full["cross_cutting_excluded_count"] == 0


def test_api_tier2_cross_cutting_query_param_works(app_client):
    """GET /api/intake/tier2/<state>?cross_cutting=1 incluye cross-cutting."""
    r_focal = app_client.get("/api/intake/tier2/mcspc_low_volume_sync_oligo")
    r_full = app_client.get("/api/intake/tier2/mcspc_low_volume_sync_oligo?cross_cutting=1")
    s_focal = r_focal.get_json()["schema"]
    s_full = r_full.get_json()["schema"]
    assert s_full["total_fields"] > s_focal["total_fields"], (
        "?cross_cutting=1 debe incluir más fields que default"
    )
    assert s_focal["cross_cutting_filter_active"] is True
    assert s_full["cross_cutting_filter_active"] is False


def test_route_intake_tier2_banner_shows_cross_cutting_chip(app_client):
    """Banner Tier 2 muestra contador cross-cutting + link a vista experta."""
    r = app_client.get("/intake/tier2/mcspc_low_volume_sync_oligo?nss=TEST")
    html = r.data.decode("utf-8", errors="ignore")
    assert "cross-cutting" in html.lower(), (
        "Banner debe mencionar cross-cutting al usuario"
    )
    # Link al Smart Capture (vista experta) en el tagline
    assert 'href="/intake/smart"' in html, (
        "Banner debe link al Smart Capture para acceso a cross-cutting"
    )
