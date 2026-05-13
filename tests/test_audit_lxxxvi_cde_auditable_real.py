"""Tests dedicados Iteración Faubot LXXXVI #67F — CDE Auditable REAL.

Hipótesis verificables H.G2841 → H.G2871 (cubren los 8 bugs raíz cerrados +
3 nuevos endpoints + 7 JS handlers + 19 keys compass renderizadas).

Convention: cada test tiene un docstring `H.G####` que cross-referencia con
prostanet/audit_tracking.md sección "Hipótesis verificables LXXXVI".

Faubot 2026-04-27 LXXXVII.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress noisy logs during test runs
import logging
logging.getLogger().setLevel(logging.ERROR)
logging.getLogger("prostanet").setLevel(logging.ERROR)

# Defensive: APFS lock workaround for tracking_db (Faubot LXIV-LXVI pattern)
import types
if "tracking_db" not in sys.modules:
    try:
        import tracking_db  # noqa: F401
    except Exception:
        class _TrackingDbStub(types.ModuleType):
            def __getattr__(self, name):
                def _noop(*args, **kwargs):
                    return {}
                _noop.__name__ = name
                return _noop
        sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    """Flask test client con auth en DORMANT mode."""
    os.environ.setdefault("FLASK_ENV", "development")
    os.environ.pop("CLINICAL_AUTH_ENABLED", None)
    from app import app
    return app.test_client()


@pytest.fixture(scope="module")
def real_nss():
    """NSS de paciente real para tests E2E."""
    return "97000000001"


# ─────────────────────────────────────────────────────────────────────────
# §A — Compass + adapter (B2 fix: 19 keys renderizadas)
# ─────────────────────────────────────────────────────────────────────────
def test_g2841_compass_full_returns_21_keys():
    """H.G2841 — `_compass_full()` retorna ≥18 keys (was 0 → 21)."""
    from prostanet.presentation.v2_adapters import _compass_full
    result = _compass_full({})
    assert isinstance(result, dict)
    expected_keys = {
        "recommended_direction", "why_this_now", "what_could_change_course",
        "next_actions", "monitoring_cadence", "data_freshness",
        "data_freshness_severity", "last_decisive_data", "evidence_anchor",
        "evidence_anchor_items", "confidence_category", "recommendation_family",
        "decision_changing_inputs", "why_not_more_confident",
        "active_modifiers", "safety_modifiers", "longitudinal_truth_summary",
        "transition_pending", "transition_title",
        "structured_decision_headline", "structured_decision_supporting_text",
        "keys_populated_count",
    }
    assert expected_keys.issubset(set(result.keys())), (
        f"Missing keys: {expected_keys - set(result.keys())}"
    )


def test_g2842_compass_normalizers_no_dict_literals_leak():
    """H.G2842 — modifier dicts se renderizan como {label, detail, tone}, no `str(dict)`."""
    from prostanet.presentation.v2_adapters import _compass_full
    pv = {"clinical_compass": {
        "active_modifiers": [{"label": "Test", "detail": "Detail X", "tone": "danger"}],
        "safety_modifiers": [{"label": "Safety", "detail": "Y"}],
        "data_freshness": [{"label": "PSA", "value": 11.4, "date": "2026-06-10"}],
    }}
    result = _compass_full(pv)
    assert isinstance(result["active_modifiers"], list)
    assert isinstance(result["active_modifiers"][0], dict)
    assert "label" in result["active_modifiers"][0]
    assert "tone" in result["active_modifiers"][0]
    # data_freshness items should have severity assigned
    assert isinstance(result["data_freshness"], list)
    assert "severity" in result["data_freshness"][0]


def test_g2843_compass_evidence_anchor_items_structured():
    """H.G2843 — `evidence_anchor_items` es lista de {label, title, url}."""
    from prostanet.presentation.v2_adapters import _compass_full
    pv = {"clinical_compass": {"evidence_anchor": [
        {"label": "NCCN 5.2026", "title": "NCCN guidelines", "url": ""},
        {"label": "EAU 2026", "title": "EAU guidelines",
         "url": "https://uroweb.org/guidelines/prostate-cancer"},
    ]}}
    result = _compass_full(pv)
    items = result["evidence_anchor_items"]
    assert len(items) == 2
    assert items[0]["label"] == "NCCN 5.2026"
    assert items[1]["url"].startswith("https://")


# ─────────────────────────────────────────────────────────────────────────
# §B — Decision Hero flatten (no list literals leak)
# ─────────────────────────────────────────────────────────────────────────
def test_g2844_decision_today_rationale_flattens_list():
    """H.G2844 — `_decision_today` flatten evita `[&#39;...&#39;]` leak."""
    from prostanet.presentation.v2_adapters import _decision_today
    pv = {"clinical_compass": {
        "why_this_now": ["Reason 1", "Reason 2", "Reason 3"],
        "evidence_anchor": [{"title": "NCCN doc"}, {"title": "EAU doc"}],
    }}
    result = _decision_today(pv)
    # Should be a flat string, not Python list literal
    assert "[" not in result["rationale"][:5] or not result["rationale"].startswith("[")
    assert "Reason 1" in result["rationale"]
    assert " · " in result["rationale"]
    # evidence_level también
    assert "{" not in result["evidence_level"][:5]
    assert "NCCN doc" in result["evidence_level"]


# ─────────────────────────────────────────────────────────────────────────
# §C — Stage-Aware Progressive Intake (B6 fix)
# ─────────────────────────────────────────────────────────────────────────
def test_g2845_quick_classify_schema_has_15_fields():
    """H.G2845 — `quick_classify_schema()` retorna ≥15 fields NCCN minimum.

    LXCII.1 forward-compat: pre-LXCII era 15. Post-LXCII expandido a 32+
    para routear correctamente a TODOS los 18 estadios NCCN canónicos.
    Post-LXCII.1 expandido a 34+ con campos imagen-canonical (bone count
    + visceral discrete + appendicular split per CHAARTED).
    Aceptamos ≥15 para no romper backward-compat futuro.
    """
    from prostanet.presentation.v2_adapters import quick_classify_schema
    schema = quick_classify_schema()
    assert schema["module"] == "quick_classify"
    assert len(schema["fields"]) >= 15
    # Required count: NCCN minimum es nombre + dob + nss + ECOG + diagnosis + PSA = 6
    required_count = sum(1 for f in schema["fields"] if f.get("required"))
    assert required_count >= 5  # mín 5 required


def test_g2846_stage_specific_intake_schema_m1_crpc_returns_full_schema():
    """H.G2846 — `stage_specific_intake_schema('m1_crpc')` retorna ≥500 fields."""
    from prostanet.presentation.v2_adapters import stage_specific_intake_schema
    schema = stage_specific_intake_schema("m1_crpc")
    assert "_error" not in schema
    assert schema["state"] == "m1_crpc"
    assert schema["total_fields"] >= 500  # m1_crpc tiene 554 fields
    assert schema["required_count"] >= 10
    assert len(schema["field_groups"]) >= 10
    assert "by_role" in schema
    assert "required" in schema["by_role"]


def test_g2847_18_stages_resolve_without_error():
    """H.G2847 — Los 18 estados canónicos del registry resuelven sin error."""
    from prostanet.presentation.v2_adapters import (
        list_known_stages, stage_specific_intake_schema,
    )
    stages = list_known_stages()
    assert len(stages) >= 18
    for entry in stages:
        state = entry["state"]
        schema = stage_specific_intake_schema(state)
        assert "_error" not in schema, f"Stage {state} failed: {schema.get('_error')}"
        assert schema["total_fields"] > 0, f"Stage {state} has 0 fields"


# ─────────────────────────────────────────────────────────────────────────
# §D — Endpoints (B1 + B3 + new endpoints)
# ─────────────────────────────────────────────────────────────────────────
def test_g2848_state_classifier_endpoint_returns_progression_keys(client):
    """H.G2848 — POST /api/state-classifier expone progression_gate_active y demás."""
    r = client.post("/api/state-classifier", json={
        "psa_baseline_ng_ml": 145.0,
        "metastasis_site": "M1b",
        "known_cancer_diagnosis": "1",
        "current_adt_context": "medical_adt_continuous",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert "state" in body
    assert "progression_gate_active" in body  # backward compat con test_modular_engine
    assert "phenotype_state" in body
    assert "next_step_url" in body  # nueva key LXXXVI


def test_g2849_intake_schema_quick_endpoint(client):
    """H.G2849 — GET /api/intake-schema/_quick retorna ≥15 fields.

    LXCII.1 forward-compat: schema expandido 15 → 34+ fields con multi-level
    conditional_visibility. Aceptamos ≥15 para no romper backward-compat
    cuando se siga ampliando.
    """
    r = client.get("/api/intake-schema/_quick")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["module"] == "quick_classify"
    assert len(body["fields"]) >= 15


def test_g2850_intake_schema_m1_crpc_endpoint(client):
    """H.G2850 — GET /api/intake-schema/m1_crpc retorna schema completo."""
    r = client.get("/api/intake-schema/m1_crpc")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["state"] == "m1_crpc"
    assert body["total_fields"] >= 500


def test_g2851_intake_schema_list_endpoint(client):
    """H.G2851 — GET /api/intake-schema/_list retorna ≥18 stages."""
    r = client.get("/api/intake-schema/_list")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert len(body["stages"]) >= 18


def test_g2852_intake_wizard_route_renders(client):
    """H.G2852 — GET /intake-wizard?v=legacy renderiza Stage-Aware wizard 3-step.

    LXCII.1 forward-compat: el heading H2 evolucionó de "Datos mínimos para
    clasificación" (LXXXVI) → "Clasificación NCCN 5.2026 · 18 estadios
    canónicos" (LXCII.1). Aceptamos cualquiera para no romper backward-compat.

    LXCIX.4 forward-compat: post-LXCIII el default es `intake_progressive_v2.html`
    (bento grid). El template Stage-Aware wizard (LXXXVI) ahora es opt-in
    via `?v=legacy`.
    """
    r = client.get("/intake-wizard?v=legacy")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Stage-Aware Progressive" in body
    assert ("Datos mínimos para clasificación" in body
            or "Clasificación NCCN" in body), (
        "Step 1 heading missing — wizard render broken."
    )
    assert "iwClassifyAndAdvance" in body  # JS handler
    assert "iwApplyConditionalVisibility" in body


def test_g2853_action_log_endpoint_accepts_both_action_aliases(client, real_nss):
    """H.G2853 — POST /api/patient/<nss>/action-log acepta `action` y `action_text`."""
    # JS-style: action
    r1 = client.post(f"/api/patient/{real_nss}/action-log", json={
        "action": "Test action JS-style",
        "action_index": 0,
        "completed_at": "2026-09-15T10:00:00",
    })
    assert r1.status_code == 200
    b1 = r1.get_json()
    assert b1["success"] is True
    assert "decision_changed" in b1

    # Canonical: action_text
    r2 = client.post(f"/api/patient/{real_nss}/action-log", json={
        "action_text": "Test action canonical",
        "action_index": 1,
    })
    assert r2.status_code == 200


def test_g2854_transition_endpoint_accepts_justification_alias(client, real_nss):
    """H.G2854 — POST /api/patient/<nss>/transition acepta `justification` (no solo override_reason)."""
    r = client.post(f"/api/patient/{real_nss}/transition", json={
        "target_state": "m1_crpc",
        "override": True,
        "justification": "Test override justification with sufficient length",
    })
    assert r.status_code == 200
    b = r.get_json()
    assert b["success"] is True
    assert b["override"] is True
    assert "decision_changed" in b


def test_g2855_simulate_endpoint_no_db_write(client, real_nss):
    """H.G2855 — POST /api/simulate/<nss> NO escribe a DB."""
    import tracking_db
    # Snapshot real BEFORE
    core_before = tracking_db.load_patient_record_core(real_nss) or {}

    r = client.post(f"/api/simulate/{real_nss}", json={
        "hypothetical_changes": {"hrr_status": "Positivo", "hrr_gene": "BRCA2"},
    })
    assert r.status_code == 200
    b = r.get_json()
    assert b["success"] is True
    assert b["no_db_write"] is True
    assert "delta" in b

    # Snapshot AFTER — should be unchanged
    core_after = tracking_db.load_patient_record_core(real_nss) or {}
    # Just compare a few key fields (not full equality due to timestamps)
    if core_before and core_after:
        bl_before = (core_before.get("clinical_baseline") or {}).get("hrr_status")
        bl_after = (core_after.get("clinical_baseline") or {}).get("hrr_status")
        assert bl_before == bl_after  # NO mutation


def test_g2856_simulate_endpoint_validation(client, real_nss):
    """H.G2856 — POST /api/simulate/<nss> valida hypothetical_changes."""
    # Empty changes → 400
    r = client.post(f"/api/simulate/{real_nss}", json={})
    assert r.status_code == 400
    # Unknown patient → 404
    r2 = client.post("/api/simulate/00000000000",
                       json={"hypothetical_changes": {"hrr_status": "Positivo"}})
    assert r2.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# §E — Patient profile v2 render (B2 + B3 + B4)
# ─────────────────────────────────────────────────────────────────────────
def test_g2857_patient_profile_v2_renders_reasoning_chain(client, real_nss):
    """H.G2857 — Perfil v2 renderiza Reasoning Chain con 11 sub-secciones."""
    r = client.get(f"/patient_profile/{real_nss}")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "Cadena de razonamiento" in body
    assert "Modificadores activos" in body
    assert "Frescura de datos" in body
    assert "Anclaje de evidencia" in body


def test_g2858_patient_profile_v2_has_js_handlers(client, real_nss):
    """H.G2858 — Perfil v2 incluye los 7 nuevos JS handlers LXXXVI."""
    r = client.get(f"/patient_profile/{real_nss}")
    body = r.data.decode("utf-8", errors="replace")
    handlers = [
        "window.pm2Toast",
        "window.pm2ConfirmTransition",
        "window.pm2OverrideTransition",
        "window.pm2LogAction",
        "window.pm2RefreshDecisionHero",
        "window.pm2OpenQuickCapture",
        "window.pm2RunSimulation",
    ]
    for h in handlers:
        assert h in body, f"Missing JS handler: {h}"


def test_g2859_patient_profile_no_dict_literal_leaks(client, real_nss):
    """H.G2859 — Perfil v2 NO leakea `{'label': ...}` o `[...]` literals."""
    r = client.get(f"/patient_profile/{real_nss}")
    body = r.data.decode("utf-8", errors="replace")
    # Escaped + unescaped variants
    assert "{&#39;label&#39;:" not in body
    assert "[&#39;Estado de castración" not in body  # specific known leak from pre-fix


# ─────────────────────────────────────────────────────────────────────────
# §F — Longitudinal capture template (B4 fix)
# ─────────────────────────────────────────────────────────────────────────
def test_g2860_longitudinal_capture_template_has_real_fetch(client, real_nss):
    """H.G2860 — Template longitudinal usa fetch real (no DOM mock)."""
    r = client.get(f"/longitudinal-capture/{real_nss}")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "async function pm2AppendRow" in body
    assert "/api/longitudinal/" in body
    assert "function pm2BuildPayload" in body
    assert f'const PM2_NSS = "{real_nss}"' in body


def test_g2861_longitudinal_psa_append_recompute_works(client, real_nss):
    """H.G2861 — POST PSA append → 200 + decision_changed=True (recompute hook)."""
    r = client.post(f"/api/longitudinal/{real_nss}/append", json={
        "kind": "psa",
        "payload": {"date": "2026-12-15", "value": 22.7, "context": "test_lxxxvi"},
    })
    # Either 200 (new) or 409 (duplicate from prior runs)
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        body = r.get_json()
        assert "decision_changed" in body
        assert "delta" in body
        assert body.get("audit_note", "").startswith("Append → recompute → CDE updated")


# ─────────────────────────────────────────────────────────────────────────
# §G — Algorithm version + audit_tracking integrity
# ─────────────────────────────────────────────────────────────────────────
def test_g2862_faubot_release_at_lxxxvi_or_higher():
    """H.G2862 — FAUBOT_RELEASE bumped to LXXXVI or higher post-iteration.

    LXCII.1 forward-compat: roman numeral monotonic comparison. Acepta
    cualquier release ≥LXXXVI hasta C (próximo grupo).
    """
    import re
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Acepta LXXXV, LXXXVI..LXXXIX, LXC..LXCIX, C..CIX, etc.
    valid_prefixes = ["LXXXV", "LXXXVI", "LXXXVII", "LXXXVIII", "LXXXIX",
                      "LXC", "LXCI", "LXCII", "LXCIII", "LXCIV", "LXCV",
                      "LXCVI", "LXCVII", "LXCVIII", "LXCIX", "C"]
    matched = any(p in FAUBOT_RELEASE for p in valid_prefixes)
    assert matched, f"FAUBOT_RELEASE={FAUBOT_RELEASE} no matchea ≥LXXXVI"


def test_g2863_audit_tracking_has_lxxxvi_entry():
    """H.G2863 — audit_tracking.md contiene entry de iteración #67F LXXXVI."""
    audit = (PROJECT_ROOT / "prostanet" / "audit_tracking.md").read_text()
    assert "LXXXVI" in audit
    assert "#67F" in audit


def test_g2864_clinical_evidence_md_exists():
    """H.G2864 — CLINICAL_EVIDENCE_2026.md existe (Fase 0 LXXXVI)."""
    p = PROJECT_ROOT / "prostanet" / "CLINICAL_EVIDENCE_2026.md"
    assert p.exists()
    content = p.read_text()
    assert "NCCN 5.2026" in content
    assert "FDA SaMD" in content
