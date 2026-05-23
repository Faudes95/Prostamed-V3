"""Tests EPIC 46.B — ML Materialization.

Valida los 4 cambios:
1. ml_inference_routes.py es importable + blueprint declarado
2. build_ml_predictions_snapshot() returns shape correcto (available, models{4})
3. Snapshot fail-safe: si patient_id inválido → {available:False, reason:..}
4. View model integration: profile_compass inyecta ml_predictions al bundle
5. UI template tiene data-testid="ml-predictions-panel" + 4 sub-cards data-testid
6. GET endpoint 404 cuando NSS no existe
7. GET endpoint 503 cuando modelo no disponible (no patient/model fail)
8. Helper _explain_unavailable cubre los casos de unavailability

FAUBOT CXXXIII — 2026-05-22.
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────
# Test 1 — Module + blueprint importable
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_ml_inference_routes_importable():
    """El módulo se carga sin errores y expone blueprint + helper."""
    mod = importlib.import_module(
        "prostanet.presentation.ml_inference_routes"
    )
    assert hasattr(mod, "ml_inference_bp"), "ml_inference_bp not exported"
    assert hasattr(mod, "build_ml_predictions_snapshot"), (
        "build_ml_predictions_snapshot helper not exported"
    )
    # Blueprint name correct
    assert mod.ml_inference_bp.name == "ml_inference"


# ─────────────────────────────────────────────────────────────────────
# Test 2 — Snapshot shape (happy path con mock)
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_snapshot_shape_with_mocked_service():
    """build_ml_predictions_snapshot retorna shape esperado:
    {available, models{4 keys}, advisory_only, rule_based_source_of_truth}."""
    from prostanet.presentation.ml_inference_routes import (
        build_ml_predictions_snapshot,
    )

    # Mock cadena: PredictionService → record fetch → 4 model calls
    fake_record = {"id": 999, "baseline_psa": 12.0}
    fake_predict = {
        "expected_response": "responder",
        "confidence": 0.78,
        "model_id": "treatment_response",
        "model_version": "v0.1.0",
        "maturity": "experimental",
        "advisory_only": True,
    }
    fake_service = MagicMock()
    fake_service.predict_treatment_response.return_value = fake_predict
    fake_service.predict_survival.return_value = {
        **fake_predict, "model_id": "deep_surv",
        "median_survival_months": 36.0,
    }
    fake_service.predict_anomalies.return_value = {
        **fake_predict, "model_id": "anomaly_detector",
        "anomaly_score": 0.42, "is_anomaly": False,
    }
    fake_service.predict_state_transition.return_value = {
        **fake_predict, "model_id": "state_transition",
        "next_state": "m1_crpc", "expected_months_to_transition": 18.0,
    }
    fake_registry = MagicMock()
    fake_registry.get_metadata.return_value = {
        "model_version": "v0.1.0",
        "maturity": "experimental",
    }

    with patch(
        "prostanet.presentation.ml_inference_routes._build_prediction_service",
        return_value=(fake_service, fake_registry),
    ), patch(
        "tracking_db.get_patient_full_record", return_value=fake_record,
    ):
        snapshot = build_ml_predictions_snapshot(patient_id=999)

    assert snapshot["available"] is True
    assert snapshot["advisory_only"] is True
    assert snapshot["rule_based_source_of_truth"] is True
    assert set(snapshot["models"].keys()) == {
        "treatment_response", "survival", "anomaly", "state_transition"
    }
    # Cada modelo disponible debe tener prediction + model_version + maturity
    for key in snapshot["models"]:
        m = snapshot["models"][key]
        assert m["available"] is True
        assert "prediction" in m
        assert m["model_version"] == "v0.1.0"
        assert m["maturity"] == "experimental"


# ─────────────────────────────────────────────────────────────────────
# Test 3 — Fail-safe con patient_id inválido
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_snapshot_fail_safe_invalid_patient_id():
    """patient_id <= 0 retorna {available:False, reason:invalid_patient_id}
    sin levantar excepción."""
    from prostanet.presentation.ml_inference_routes import (
        build_ml_predictions_snapshot,
    )

    snapshot = build_ml_predictions_snapshot(patient_id=0)
    assert snapshot["available"] is False
    assert snapshot["reason"] == "invalid_patient_id"
    assert snapshot["models"] == {}

    snapshot_neg = build_ml_predictions_snapshot(patient_id=-1)
    assert snapshot_neg["available"] is False


# ─────────────────────────────────────────────────────────────────────
# Test 4 — View model integration en profile_compass
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_profile_compass_wires_ml_predictions():
    """profile_compass._build_ml_predictions_snapshot_view_model debe
    devolver snapshot fail-safe sin levantar."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_ml_predictions_snapshot_view_model,
    )

    # Patient con identity.id (path canónico)
    patient = {"identity": {"id": 999}, "baseline": {}}
    snapshot = _build_ml_predictions_snapshot_view_model(patient)
    assert "available" in snapshot
    assert "models" in snapshot
    assert "advisory_only" in snapshot
    # advisory_only siempre True (filosofía SaMD)
    assert snapshot["advisory_only"] is True

    # Patient sin id válido → fail-safe
    patient_no_id = {"baseline": {}, "demographics": {}}
    snapshot_no_id = _build_ml_predictions_snapshot_view_model(patient_no_id)
    assert snapshot_no_id["available"] is False
    assert "invalid_patient_id" in snapshot_no_id.get("reason", "")


# ─────────────────────────────────────────────────────────────────────
# Test 5 — Template tiene data-testid markers
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_template_has_ml_panel_and_4_cards():
    """patient_profile_v2.html debe declarar el panel ml-predictions-panel
    + las 4 sub-cards con data-testid."""
    from pathlib import Path

    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    assert template.exists(), f"Template no encontrado: {template}"
    content = template.read_text(encoding="utf-8")

    # Panel principal
    assert 'data-testid="ml-predictions-panel"' in content, (
        "Panel principal ml-predictions-panel falta"
    )
    # 4 cards individuales
    for card_id in (
        "ml-card-treatment-response",
        "ml-card-survival",
        "ml-card-anomaly",
        "ml-card-state-transition",
    ):
        assert f'data-testid="{card_id}"' in content, (
            f"Card {card_id} falta en template"
        )
    # Header EPIC 46.B identifiable
    assert "EPIC 46.B" in content


# ─────────────────────────────────────────────────────────────────────
# Test 6 — GET endpoint 404 con NSS desconocido
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_get_endpoint_404_for_unknown_nss():
    """GET /api/ml/treatment-response/<nss> debe retornar 404 si NSS no existe."""
    from flask import Flask
    from prostanet.presentation.ml_inference_routes import ml_inference_bp

    app = Flask(__name__)
    app.register_blueprint(ml_inference_bp)
    client = app.test_client()

    # NSS sintético garantizado a no existir
    response = client.get("/api/ml/treatment-response/NSS-DEFINITELY-NOT-EXISTS-9999")
    assert response.status_code == 404
    data = response.get_json()
    assert data["success"] is False
    assert "no encontrado" in data["error"].lower()


# ─────────────────────────────────────────────────────────────────────
# Test 7 — GET endpoint 503 cuando modelo no disponible
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_get_endpoint_503_when_model_unavailable():
    """Si el modelo está unavailable (PredictionService returns None),
    el endpoint retorna 503 con advisory_api=True para que UI no
    interprete como bug + permite degradación silenciosa."""
    from flask import Flask
    from prostanet.presentation.ml_inference_routes import ml_inference_bp

    app = Flask(__name__)
    app.register_blueprint(ml_inference_bp)
    client = app.test_client()

    # Mock: resolución de NSS exitosa pero modelo no disponible
    with patch(
        "prostanet.presentation.ml_inference_routes._resolve_patient_id_from_nss",
        return_value=42,
    ), patch(
        "prostanet.presentation.ml_inference_routes.build_ml_predictions_snapshot",
        return_value={
            "available": True,
            "models": {
                "treatment_response": {
                    "available": False,
                    "reason": "feature_flag_disabled_or_unknown",
                    "model_version": "unregistered",
                    "maturity": "not_loaded",
                },
                "survival": {"available": False, "reason": "artifact_missing"},
                "anomaly": {"available": False, "reason": "artifact_missing"},
                "state_transition": {"available": False, "reason": "artifact_missing"},
            },
            "advisory_only": True,
        },
    ):
        response = client.get("/api/ml/treatment-response/SOME-NSS")

    assert response.status_code == 503
    data = response.get_json()
    assert data["success"] is False
    assert data["advisory_api"] is True
    assert data["available"] is False
    assert data["reason"] == "feature_flag_disabled_or_unknown"


# ─────────────────────────────────────────────────────────────────────
# Test 8 — Helper _explain_unavailable cubre casos
# ─────────────────────────────────────────────────────────────────────


def test_epic46b_explain_unavailable_covers_cases():
    """_explain_unavailable debe distinguir entre:
    - artifact_missing, incompatible_checkpoint, load_error, not_loaded,
      feature_flag_disabled, no_metadata."""
    from prostanet.presentation.ml_inference_routes import _explain_unavailable

    assert _explain_unavailable({}) == "no_metadata"
    assert _explain_unavailable(None) == "no_metadata"
    assert _explain_unavailable(
        {"incompatible_vocab_version": True}
    ) == "incompatible_checkpoint_retrain_required"
    assert _explain_unavailable(
        {"artifact_exists": False}
    ) == "artifact_missing"
    assert _explain_unavailable(
        {"artifact_exists": True, "loaded": False}
    ) == "not_loaded"
    assert _explain_unavailable(
        {"artifact_exists": True, "loaded": False,
         "load_error": "some torch error"}
    ).startswith("load_error:")
    assert _explain_unavailable(
        {"artifact_exists": True, "loaded": True}
    ) == "feature_flag_disabled_or_unknown"
