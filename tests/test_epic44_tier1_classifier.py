"""EPIC 44.B — Tier 1 Clasificador rápido (NCCN strict minimum, <60s).

Cobertura:
  - tier1_classifier_schema() retorna 15 fields anchor con metadata correcta
  - conditional_visibility + display_options + group preserved from quick_classify
  - Required minimum fields (7) son los anchor NCCN absolutos
  - Route GET /intake/tier1 renderiza 15 fields con labels clínicos EPIC 44.A
  - Endpoint POST /api/intake/tier1/classify clasifica correctamente 3 estadios
    canónicos (localized_initial, mcspc_low_vol_sync, m1_crpc) + redirige a Tier 2
  - Missing fields retorna 400 con lista explícita
  - Numeric coercion (PSA/Gleason/ECOG strings → numbers)
  - next_tier_url incluye nss query param cuando provided
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Schema helper tests
# ─────────────────────────────────────────────────────────────────────────────

def test_tier1_schema_has_exactly_15_fields():
    """Tier 1 = 15 fields anchor (no más, no menos — strict minimum NCCN)."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    assert s["total_fields"] == 15, (
        f"Tier 1 debe tener 15 fields strict minimum NCCN — got {s['total_fields']}. "
        "Si subiera, ya no es <60s; si bajara, algún estadio queda inaccesible."
    )
    assert len(s["fields"]) == 15


def test_tier1_schema_missing_from_base_is_empty():
    """Todos los Tier 1 names existen en quick_classify_schema."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    assert s["missing_from_base_schema"] == [], (
        f"Tier 1 referencia fields no presentes en quick_classify_schema: "
        f"{s['missing_from_base_schema']}. Sincronizar nombres."
    )


def test_tier1_required_minimum_is_7_absolute_anchor():
    """El mínimo absoluto requerido (sin conditional_visibility) son los 7 anchor."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    expected_required = {
        "nss", "full_name", "dob", "ecog_score", "known_cancer_diagnosis",
        "clinical_tstage", "metastasis_site",
    }
    assert set(s["required_min_fields"]) == expected_required, (
        f"Required mínimo cambió: esperaba {sorted(expected_required)}, "
        f"got {s['required_min_fields']}"
    )


def test_tier1_fields_marked_as_tier1_anchor():
    """Cada field tiene `tier1_anchor=True` para downstream Tier 2 overlap filtering."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    for f in s["fields"]:
        assert f.get("tier1_anchor") is True, (
            f"Field {f['name']!r} no marcado como tier1_anchor — "
            "Tier 2 no podrá filtrar overlap correctamente."
        )
        assert f.get("tier") == 1


def test_tier1_preserves_display_options_from_epic44a():
    """Tier 1 hereda los display_options enriquecidos de EPIC 44.A."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    fields_by_name = {f["name"]: f for f in s["fields"]}

    # known_cancer_diagnosis debe tener labels ricos de EPIC 44.A
    f = fields_by_name["known_cancer_diagnosis"]
    labels = {opt["label"] for opt in f["display_options"] if isinstance(opt, dict)}
    assert any("biopsia" in l.lower() for l in labels), (
        f"EPIC 44.A label 'Sí, confirmado por biopsia' no propagado a Tier 1: {labels}"
    )

    # visceral_metastasis_present (si presente) también
    if "visceral_metastasis_present" in fields_by_name:
        f = fields_by_name["visceral_metastasis_present"]
        labels = {opt["label"] for opt in f["display_options"] if isinstance(opt, dict)}
        assert any("M ósea" in l for l in labels), (
            f"EPIC 44.A label 'No (M ósea/ganglionar solo)' no propagado: {labels}"
        )


def test_tier1_preserves_conditional_visibility():
    """conditional_visibility del quick_classify_schema se preserva en Tier 1."""
    from prostanet.presentation.v2_adapters import tier1_classifier_schema
    s = tier1_classifier_schema()
    fields_by_name = {f["name"]: f for f in s["fields"]}

    # visceral_metastasis_present visible solo si metastasis_site != M0
    f = fields_by_name["visceral_metastasis_present"]
    cv = f.get("conditional_visibility")
    assert cv is not None, "visceral_metastasis_present perdió conditional_visibility"
    assert "metastasis_site" in cv, f"CV mal formado: {cv}"


# ─────────────────────────────────────────────────────────────────────────────
# Route GET /intake/tier1 tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    """Flask test client con context processors registrados."""
    from app import app, create_app
    create_app()
    return app.test_client()


def test_route_intake_tier1_renders_200(app_client):
    """GET /intake/tier1 → 200 OK."""
    r = app_client.get("/intake/tier1")
    assert r.status_code == 200
    assert b"Tier 1" in r.data
    assert b"Clasificador" in r.data


def test_route_intake_tier1_renders_15_field_inputs(app_client):
    """GET /intake/tier1 → HTML con exactamente 15 data-field-name."""
    import re
    r = app_client.get("/intake/tier1")
    html = r.data.decode("utf-8", errors="ignore")
    field_names = re.findall(r'data-field-name="([^"]+)"', html)
    assert len(field_names) == 15, (
        f"Tier 1 HTML render: esperaba 15 fields, got {len(field_names)}: {field_names}"
    )


def test_route_intake_tier1_has_clinical_friendly_labels(app_client):
    """GET /intake/tier1 incluye labels clínicos densos de EPIC 44.A en options."""
    r = app_client.get("/intake/tier1")
    html = r.data.decode("utf-8", errors="ignore")
    expected_labels = [
        "Sí, confirmado por biopsia",       # known_cancer_diagnosis
        "No (M ósea/ganglionar solo)",      # visceral_metastasis_present
        "Sin metástasis a distancia (M0)",  # metastasis_site
    ]
    for label in expected_labels:
        assert label in html, (
            f"EPIC 44.A label clínico {label!r} no presente en Tier 1 HTML"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint POST /api/intake/tier1/classify tests
# ─────────────────────────────────────────────────────────────────────────────

def _tier1_payload(**overrides) -> dict:
    """Payload base válido (mCSPC bajo vol sync). Override con kwargs."""
    base = {
        "nss": "TEST-T1",
        "full_name": "Test Tier1",
        "dob": "1958-03-15",
        "ecog_score": "1",
        "known_cancer_diagnosis": "1",
        "histology_subtype": "adenocarcinoma_acinar",
        "psa_baseline_ng_ml": "38.5",
        "gleason_primary": "4",
        "gleason_secondary": "5",
        "clinical_tstage": "cT3b",
        "nodal_status": "N0",
        "metastasis_site": "M1b",
        "prior_local_therapy": "none",
        "current_adt_context": "medical_adt_continuous",
        "visceral_metastasis_present": "0",
    }
    base.update(overrides)
    return base


def test_classify_endpoint_missing_required_returns_400(app_client):
    """POST con payload incompleto → 400 + lista de missing fields."""
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps({"nss": "X"}),
        content_type="application/json",
    )
    assert r.status_code == 400
    body = r.get_json()
    assert body["success"] is False
    assert "missing_fields" in body
    assert len(body["missing_fields"]) >= 5  # 6/7 required missing


def test_classify_endpoint_mcspc_low_volume_sync(app_client):
    """Payload mCSPC bajo vol sincrónico (M1b, no visceral) → state correcto."""
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps(_tier1_payload()),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["tier"] == 1
    assert body["state"] == "mcspc_low_volume_sync_oligo", (
        f"M1b + visceral=0 + ADT activo + no prior local debe clasificar "
        f"como mcspc_low_volume_sync_oligo; got: {body['state']}"
    )
    assert body["next_tier_url"].startswith("/intake/tier2/mcspc_low_volume_sync_oligo")
    assert "nss=TEST-T1" in body["next_tier_url"]
    assert body["tier1_fields_submitted"] == 15


def test_classify_endpoint_localized_initial(app_client):
    """Payload localized de alto riesgo (M0, no ADT) → localized_initial."""
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps(_tier1_payload(
            nss="TEST-T1-LOC",
            ecog_score="0",
            psa_baseline_ng_ml="12",
            gleason_primary="4",
            gleason_secondary="4",
            clinical_tstage="cT2b",
            metastasis_site="M0",
            current_adt_context="none",
            visceral_metastasis_present="",  # n/a
        )),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["state"] == "localized_initial", (
        f"M0 + ADT none + no prior local debe ser localized_initial; got: {body['state']}"
    )


def test_classify_endpoint_m1_crpc(app_client):
    """Payload m1_crpc (M+, castrate confirmado, progresión) → m1_crpc."""
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps(_tier1_payload(
            nss="TEST-T1-CRPC",
            ecog_score="2",
            psa_baseline_ng_ml="85",
            gleason_primary="5",
            gleason_secondary="4",
            clinical_tstage="cT3b",
            nodal_status="N1",
            prior_local_therapy="radiation",
            # extras (no Tier 1 anchor pero el classifier los usa):
            castrate_testosterone_status="confirmed_castrate",
            systemic_progression_context="confirmed_crpc",
        )),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["state"] == "m1_crpc", (
        f"M1b + castrate confirmed + progression confirmed_crpc → m1_crpc; "
        f"got: {body['state']}"
    )


def test_classify_endpoint_numeric_coercion(app_client):
    """PSA y Gleason envíados como strings se coercionan a numéricos."""
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps(_tier1_payload(
            psa_baseline_ng_ml="38.5",  # string with decimal
            gleason_primary="4",        # string int
            gleason_secondary="5",
        )),
        content_type="application/json",
    )
    assert r.status_code == 200, f"Numeric coercion falló: {r.get_json()}"


def test_classify_endpoint_no_nss_omits_query_param(app_client):
    """Si payload no incluye nss, next_tier_url no incluye ?nss=."""
    payload = _tier1_payload()
    payload.pop("nss", None)
    # nss es required, debe fallar primero
    r = app_client.post(
        "/api/intake/tier1/classify",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "nss" in r.get_json()["missing_fields"]


# ─────────────────────────────────────────────────────────────────────────────
# Template artifact tests (regresion guard)
# ─────────────────────────────────────────────────────────────────────────────

def test_template_intake_tier1_exists_and_uses_display_options():
    """templates/intake_tier1.html debe iterar f.display_options (no f.options raw)."""
    p = (Path(__file__).resolve().parent.parent / "templates" / "intake_tier1.html")
    assert p.exists(), f"Template ausente: {p}"
    content = p.read_text(encoding="utf-8")
    # Anti-pattern check (mismo que EPIC 44.A)
    assert "{% for opt in f.options %}" not in content, (
        "intake_tier1.html no debe iterar f.options raw — debe usar f.display_options"
    )
    assert "f.display_options" in content, (
        "intake_tier1.html debe leer f.display_options"
    )
    # Positive check: shell + main + preview rail
    assert "t1-shell" in content
    assert "t1-main" in content
    assert "t1-preview" in content


def test_template_intake_tier1_extends_base_clinical_via_content_block():
    """Template debe usar block 'content' (no 'body') para integrarse al layout."""
    p = (Path(__file__).resolve().parent.parent / "templates" / "intake_tier1.html")
    content = p.read_text(encoding="utf-8")
    assert '{% extends "layouts/base_clinical.html" %}' in content
    assert "{% block content %}" in content, (
        "base_clinical.html expone 'content' (no 'body'); usando block incorrecto "
        "el form no renderiza dentro del chrome"
    )
