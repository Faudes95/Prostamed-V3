"""Tests EPIC 48 — Decision Loop Closure.

Cobertura:
  - decision_narrative_builder: synthesis shape + concordance + fail-safe
  - decision_override_routes: validation + 400/404/201 + schema bootstrap
  - outcome_linkage: anchor resolution + window outcomes + PSA categorization
  - UI template testids registrados
  - Concordance + audit signature integrity

FAUBOT CXXXVI — 2026-05-24.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime

import pytest


# ─────────────────────────────────────────────────────────────────────
# Test 1 — Modules importable
# ─────────────────────────────────────────────────────────────────────


def test_epic48_modules_importable():
    """Narrative builder + override routes + outcome linkage cargan."""
    nb = importlib.import_module(
        "prostanet.domains.decisions.decision_narrative_builder"
    )
    assert hasattr(nb, "build_decision_narrative")

    ovr = importlib.import_module(
        "prostanet.presentation.decision_override_routes"
    )
    assert hasattr(ovr, "decision_override_bp")
    assert hasattr(ovr, "ALLOWED_OVERRIDE_REASONS")
    assert ovr.decision_override_bp.name == "decision_override"

    out = importlib.import_module(
        "prostanet.domains.decisions.outcome_linkage"
    )
    assert hasattr(out, "build_outcome_linkage")


# ─────────────────────────────────────────────────────────────────────
# Test 2 — Narrative builder synthesis
# ─────────────────────────────────────────────────────────────────────


def test_epic48_narrative_synthesizes_6_engines():
    """build_decision_narrative debe producir párrafo coherente con anchors
    desde compass + twin + fusion + trajectory + ml + gates."""
    from prostanet.domains.decisions.decision_narrative_builder import (
        build_decision_narrative,
    )
    bundle = {
        "clinical_compass": {
            "next_best_action": {"label": "Switch a Cabazitaxel", "action": "switch_cabazitaxel"},
            "resolved_stage_label": "mCRPC post-ARSI",
            "nccn_reference": "PROS-K",
        },
        "patient_twin": {
            "regimen_rankings_personalized": [
                {"regimen_name": "Cabazitaxel + Lu-PSMA", "primary_drug": "cabazitaxel",
                 "expected_os_gain_mo": 4.0, "primary_trial": "CARD", "rank": 1},
            ],
        },
        "decision_fusion": {
            "has_conflicts": False,
            "arbitrated_ranking": [
                {"regimen_name": "Cabazitaxel + Lu-PSMA", "arbitrated_rank": 1, "score": 0.85},
            ],
        },
        "pivotal_panel": {"eligible_matches": [{"trial_id": "CARD"}]},
        "trajectory": {
            "available": True,
            "alerts": [{
                "severity": "critical",
                "alert_id": "psa_progression_on_arsi_pcwg3",
                "clinical_message": "PSA progression confirmada",
                "citation": "Scher JCO 2016 PCWG3",
            }],
        },
        "ml_predictions": {
            "available": True,
            "models": {
                "treatment_response": {
                    "available": True,
                    "prediction": {"expected_response": "responder", "confidence": 0.72},
                    "model_version": "1.0.0", "maturity": "experimental",
                },
            },
        },
        "godibot_review": {"status": "ok"},
    }
    result = build_decision_narrative(bundle)
    assert result["available"] is True
    assert result["primary_recommendation"]["label"]
    assert len(result["evidence_chain"]) >= 4, "Debe sintetizar ≥4 anchors"
    assert result["confidence_score"] > 0.5
    assert "narrative_html" in result
    assert "<strong" in result["narrative_html"]


def test_epic48_narrative_fail_safe_empty_bundle():
    """Bundle vacío → {available:False, reason:...} sin levantar."""
    from prostanet.domains.decisions.decision_narrative_builder import (
        build_decision_narrative,
    )
    r1 = build_decision_narrative(None)
    assert r1["available"] is False
    r2 = build_decision_narrative({})
    assert r2["available"] is False
    assert "no_primary_recommendation" in r2["reason"] or "no_view_model" in r2["reason"]


def test_epic48_narrative_concordance_detects_godibot_block():
    """GodiBot status=blocked_hard → discordance + concordance.godibot_no_blocks=False."""
    from prostanet.domains.decisions.decision_narrative_builder import (
        build_decision_narrative,
    )
    bundle = {
        "clinical_compass": {"next_best_action": {"label": "Test action"}},
        "patient_twin": {},
        "decision_fusion": {"has_conflicts": False},
        "godibot_review": {"status": "blocked_hard", "summary": "Hard block testing"},
    }
    result = build_decision_narrative(bundle)
    assert result["available"] is True
    assert result["concordance_summary"]["godibot_no_blocks"] is False
    assert any(d.get("source") == "godibot" for d in result["discordances"])


def test_epic48_narrative_html_escapes_correctly():
    """HTML escape para evitar XSS en labels con caracteres especiales."""
    from prostanet.domains.decisions.decision_narrative_builder import (
        build_decision_narrative,
    )
    bundle = {
        "clinical_compass": {"next_best_action": {"label": "Test <script>alert(1)</script>"}},
    }
    result = build_decision_narrative(bundle)
    assert "&lt;script&gt;" in result["narrative_html"]
    assert "<script>" not in result["narrative_html"]


# ─────────────────────────────────────────────────────────────────────
# Test 3 — Override REST endpoint
# ─────────────────────────────────────────────────────────────────────


def test_epic48_override_endpoint_rejects_invalid_payloads():
    """Validation: missing fields + invalid reasons → 400."""
    from flask import Flask
    from prostanet.presentation.decision_override_routes import decision_override_bp

    app = Flask(__name__)
    app.register_blueprint(decision_override_bp)
    client = app.test_client()

    # Missing nss
    r = client.post(
        "/api/decision-override",
        data=json.dumps({"override_label": "X", "override_reasons": ["patient_preference"]}),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "nss" in r.get_json()["error"]

    # Missing override_label
    r = client.post(
        "/api/decision-override",
        data=json.dumps({"nss": "TEST", "override_reasons": ["patient_preference"]}),
        content_type="application/json",
    )
    assert r.status_code == 400

    # Empty reasons
    r = client.post(
        "/api/decision-override",
        data=json.dumps({"nss": "TEST", "override_label": "X", "override_reasons": []}),
        content_type="application/json",
    )
    assert r.status_code == 400

    # Invalid reason code
    r = client.post(
        "/api/decision-override",
        data=json.dumps({
            "nss": "TEST", "override_label": "X",
            "override_reasons": ["totally_invalid_reason"],
        }),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "invalid override_reasons" in r.get_json()["error"]


def test_epic48_override_other_specify_requires_free_text():
    """reason='other_specify' SIN free_text → 400."""
    from flask import Flask
    from prostanet.presentation.decision_override_routes import decision_override_bp

    app = Flask(__name__)
    app.register_blueprint(decision_override_bp)
    client = app.test_client()

    r = client.post(
        "/api/decision-override",
        data=json.dumps({
            "nss": "TEST",
            "override_label": "X",
            "override_reasons": ["other_specify"],
            "free_text": "",
        }),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "free_text" in r.get_json()["error"]


def test_epic48_override_endpoint_404_unknown_nss():
    """NSS desconocido → 404."""
    from flask import Flask
    from prostanet.presentation.decision_override_routes import decision_override_bp

    app = Flask(__name__)
    app.register_blueprint(decision_override_bp)
    client = app.test_client()

    r = client.post(
        "/api/decision-override",
        data=json.dumps({
            "nss": "NSS-DEFINITELY-NOT-EXISTS-99999",
            "override_label": "Test override",
            "override_reasons": ["patient_preference"],
        }),
        content_type="application/json",
    )
    assert r.status_code == 404
    assert "no encontrado" in r.get_json()["error"].lower()


def test_epic48_override_allowed_reasons_complete():
    """ALLOWED_OVERRIDE_REASONS debe tener ≥10 taxonomy entries publicables."""
    from prostanet.presentation.decision_override_routes import (
        ALLOWED_OVERRIDE_REASONS,
    )
    assert len(ALLOWED_OVERRIDE_REASONS) >= 10
    # Reasons clínicamente importantes
    must_have = {
        "patient_preference", "access_barrier_local",
        "comorbidity_contraindication", "other_specify",
    }
    assert must_have.issubset(ALLOWED_OVERRIDE_REASONS)


def test_epic48_override_history_endpoint_404_unknown_nss():
    """GET history → 404 si NSS no existe."""
    from flask import Flask
    from prostanet.presentation.decision_override_routes import decision_override_bp

    app = Flask(__name__)
    app.register_blueprint(decision_override_bp)
    client = app.test_client()

    r = client.get("/api/decision-override/NSS-NOT-EXISTS-XXX")
    assert r.status_code == 404


def test_epic48_override_stats_endpoint_200():
    """GET stats endpoint debe retornar 200 con taxonomy."""
    from flask import Flask
    from prostanet.presentation.decision_override_routes import decision_override_bp

    app = Flask(__name__)
    app.register_blueprint(decision_override_bp)
    client = app.test_client()

    r = client.get("/api/decision-override/stats")
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "total_overrides" in data
    assert "allowed_reasons" in data
    assert len(data["allowed_reasons"]) >= 10


# ─────────────────────────────────────────────────────────────────────
# Test 4 — Outcome linkage
# ─────────────────────────────────────────────────────────────────────


def test_epic48_outcome_linkage_fail_safe_empty():
    """No patient → available=False sin levantar."""
    from prostanet.domains.decisions.outcome_linkage import build_outcome_linkage
    r = build_outcome_linkage(None)
    assert r["available"] is False
    r2 = build_outcome_linkage({"identity": {}})
    assert r2["available"] is False


def test_epic48_outcome_linkage_anchor_from_treatment_event():
    """Si no hay explicit decision_event, anchor desde último treatment."""
    from prostanet.domains.decisions.outcome_linkage import build_outcome_linkage
    patient = {
        "identity": {"id": 1},
        "baseline": {},
        "treatments": [
            {"regimen_name": "Enzalutamida 160mg", "start_date": "2025-06-01"},
            {"regimen_name": "Cabazitaxel + Lu-PSMA", "start_date": "2026-02-15", "scheme": "cabazi_lupsma"},
        ],
        "biomarker_longitudinal": [
            {"biomarker_type": "PSA", "value": 50.0, "sample_date": "2026-02-10"},
            {"biomarker_type": "PSA", "value": 22.0, "sample_date": "2026-04-15"},
            {"biomarker_type": "PSA", "value": 10.0, "sample_date": "2026-05-15"},
        ],
        "follow_ups": [],
    }
    r = build_outcome_linkage(patient)
    assert r["available"] is True
    assert r["decision_anchor"]["decided_at"][:10] == "2026-02-15"
    assert "Cabazitaxel" in r["decision_anchor"]["label"]
    # Outcomes 3m: PSA bajó de 50 a ~10-22 → response
    assert r["outcomes_3m"]["data_available"] is True
    assert r["outcomes_3m"]["psa"]["category"] in ("response_major", "response_minor")
    assert r["outcomes_3m"]["psa"]["change_pct"] < 0


def test_epic48_outcome_linkage_psa_categorization():
    """PCWG3-style categorization."""
    from prostanet.domains.decisions.outcome_linkage import (
        _categorize_psa_response,
    )
    assert _categorize_psa_response(-55) == "response_major"
    assert _categorize_psa_response(-25) == "response_minor"
    assert _categorize_psa_response(0) == "stable"
    assert _categorize_psa_response(15) == "stable"
    assert _categorize_psa_response(30) == "progression"
    assert _categorize_psa_response(None) is None


def test_epic48_outcome_linkage_ecog_categorization():
    """ECOG delta categorization (improved / stable / declined / severe)."""
    from prostanet.domains.decisions.outcome_linkage import (
        _categorize_ecog_change,
    )
    assert _categorize_ecog_change(-1) == "improved"
    assert _categorize_ecog_change(0) == "stable"
    assert _categorize_ecog_change(1) == "declined"
    assert _categorize_ecog_change(2) == "severe_decline"
    assert _categorize_ecog_change(None) is None


# ─────────────────────────────────────────────────────────────────────
# Test 5 — UI template + view model wiring
# ─────────────────────────────────────────────────────────────────────


def test_epic48_template_has_decision_narrative_testids():
    """patient_profile_v2.html debe declarar testids de narrative + override + outcomes."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")

    required = [
        "decision-narrative",
        "decision-narrative-body",
        "decision-narrative-confidence-badge",
        "decision-narrative-override-btn",
        "decision-override-modal",
        "decision-override-form",
        "decision-override-submit-btn",
        "outcome-linkage-panel",
    ]
    for tid in required:
        assert f'data-testid="{tid}"' in content, f"Missing testid: {tid}"
    assert "EPIC 48" in content


def test_epic48_profile_compass_wires_narrative_outcome_at_source_level():
    """Source-level guard: profile_compass.py debe declarar las 2 injection lines.

    Acepta ambos patterns:
      - bundle["decision_narrative"] = _build_decision_narrative_safe(...)
      - "decision_narrative": _build_decision_narrative_safe(...)   (dict literal)
    """
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "domains" / "patient_tracking" / "profile_compass.py"
    content = src.read_text(encoding="utf-8")
    assert "decision_narrative" in content
    assert "outcome_linkage" in content
    assert "_build_decision_narrative_safe" in content
    assert "_build_outcome_linkage_safe" in content
    # Confirma que está cableado como assignment al bundle (no comentario muerto)
    assert (
        'bundle["decision_narrative"]' in content
        or '"decision_narrative":' in content
    ), "decision_narrative no asignado a bundle/dict"
    assert (
        'bundle["outcome_linkage"]' in content
        or '"outcome_linkage":' in content
    ), "outcome_linkage no asignado a bundle/dict"


# ─────────────────────────────────────────────────────────────────────
# Test 6 — Audit signature integrity
# ─────────────────────────────────────────────────────────────────────


def test_epic48_audit_signature_deterministic():
    """Misma payload → misma signature; payload distinto → distinta signature."""
    from prostanet.presentation.decision_override_routes import (
        _compute_audit_signature,
    )
    payload_a = {
        "patient_id": 99,
        "recommended_label": "X",
        "override_label": "Y",
        "override_reasons": ["patient_preference"],
        "decided_at": "2026-05-24T12:00:00",
    }
    payload_b = dict(payload_a)
    payload_c = dict(payload_a, override_label="DIFFERENT")
    assert _compute_audit_signature(payload_a) == _compute_audit_signature(payload_b)
    assert _compute_audit_signature(payload_a) != _compute_audit_signature(payload_c)
    # Signature debe ser 32-char hex
    sig = _compute_audit_signature(payload_a)
    assert len(sig) == 32
    assert all(c in "0123456789abcdef" for c in sig)
