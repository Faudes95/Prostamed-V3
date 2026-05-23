"""ml_inference_routes — EPIC 46.B (FAUBOT CXXXIII).

Materialización de los 4 modelos PyTorch entrenados que viven en
`output/models/{treatment_response, deep_surv, anomaly_detector,
state_transition}/best.pt` pero hasta hoy NO se mostraban al clínico.

Provee 2 capas:

1. **GET endpoints idempotentes por NSS** (este blueprint) — la UI los
   consume para render server-side o AJAX fetch:
   - GET /api/ml/treatment-response/<nss>
   - GET /api/ml/survival/<nss>
   - GET /api/ml/anomaly/<nss>
   - GET /api/ml/state-transition/<nss>
   - GET /api/ml/predictions/<nss>  → bundle con los 4 modelos

   Cada endpoint envuelve `PredictionService.predict_*()` (pre-existente
   en `prostanet/ai/inference/prediction_service.py`) + agrega audit
   trail en `clinical_view_audit` (section_key='ml_inference', action=
   'ml_predict:<model>:<model_version>') para reproducibilidad SaMD.

2. **Helper compartido `build_ml_predictions_snapshot(patient_id)`**:
   reutilizado por el view model (profile_compass) para inyectar
   `ml_predictions` al bundle de patient_profile sin duplicar la lógica
   de orquestación.

Endpoints POST originales en `prostanet/presentation/api.py:1883+` se
mantienen para workflows que necesitan trigger explícito con regimen_id
custom (workflow "what-if" del clínico). Los GET aquí son advisory y
no-block para render.

Filosofía SaMD: cada prediction queda decorada con `advisory_only=True`,
`rule_based_source_of_truth=True`, `qa_required=True` (ya hecho por
PredictionService._decorate_prediction). El clínico NUNCA debe ver una
ML prediction como source-of-truth — siempre como segunda opinión
complementaria al árbol de decisiones rule-based.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

ml_inference_bp = Blueprint("ml_inference", __name__)


# ─────────────────────────────────────────────────────────────────────
# Helper compartido — usado por endpoints + view model
# ─────────────────────────────────────────────────────────────────────


def _resolve_patient_id_from_nss(nss: str) -> int | None:
    """Resuelve NSS → patient_id usando tracking_db. Returns None si NSS no existe."""
    try:
        import tracking_db
        core = tracking_db.load_patient_record_core(nss)
        if not core:
            return None
        identity = core.get("identity") if isinstance(core, dict) else None
        if identity and isinstance(identity, dict):
            return int(identity.get("id") or 0) or None
    except Exception as exc:
        logger.debug("Failed to resolve NSS %s to patient_id: %s", nss, exc)
    return None


def _audit_ml_inference_call(
    patient_id: int,
    model_id: str,
    model_version: str,
    maturity: str,
) -> None:
    """Registra en clinical_view_audit cada llamada a ML inference para
    trazabilidad SaMD nivel 2 (reproducibilidad regulatoria)."""
    try:
        import sqlite3
        from tracking_db import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                "ml_inference",
                f"ml_predict:{model_id}:{model_version}",
                "low",  # advisory, no es decisión binding
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("ML inference audit log failed: %s", exc)


def _build_prediction_service():
    """Lazy-construct PredictionService con registry compartido.

    Returns (service, registry) tuple. Si construcción falla, returns
    (None, None) para que callers degraden gracefully.
    """
    try:
        from prostanet.ai.inference.prediction_service import PredictionService

        # Reuse helper de api.py si existe, sino construir registry standalone
        try:
            from prostanet.presentation.api import _build_ai_registry
            reg = _build_ai_registry()
        except Exception:
            from prostanet.ai.inference.model_registry import ModelRegistry
            reg = ModelRegistry()
            reg.load_all_available()

        return PredictionService(model_registry=reg), reg
    except Exception as exc:
        logger.debug("Failed to build PredictionService: %s", exc)
        return None, None


def build_ml_predictions_snapshot(patient_id: int) -> dict[str, Any]:
    """Construye el snapshot de las 4 predicciones para un paciente.

    Diseñado para ser invocado desde profile_compass.build_patient_profile_view_model
    durante render del perfil. Fail-safe: si cualquier modelo falla,
    retorna `available=False` con razón explicativa en lugar de levantar.

    Returns:
        {
            "available": bool (True si al menos 1 modelo respondió),
            "models": {
                "treatment_response": {available, prediction, model_version, maturity, reason?},
                "survival":           {...},
                "anomaly":            {...},
                "state_transition":   {...},
            },
            "advisory_only": True,
            "rule_based_source_of_truth": True,
        }
    """
    snapshot: dict[str, Any] = {
        "available": False,
        "models": {},
        "advisory_only": True,
        "rule_based_source_of_truth": True,
    }

    if not patient_id or patient_id <= 0:
        snapshot["reason"] = "invalid_patient_id"
        return snapshot

    service, registry = _build_prediction_service()
    if service is None:
        snapshot["reason"] = "prediction_service_unavailable"
        return snapshot

    # Patient record (single fetch, reusado por los 4 modelos)
    try:
        import tracking_db
        record = tracking_db.get_patient_full_record(patient_id)
    except Exception as exc:
        snapshot["reason"] = f"patient_record_fetch_failed: {exc}"
        return snapshot

    if not record:
        snapshot["reason"] = "patient_not_found"
        return snapshot

    # Invoke each model with fail-safe wrapper
    model_calls: list[tuple[str, str, Any]] = [
        # (snapshot_key, model_id_for_registry, callable)
        ("treatment_response", "treatment_response", service.predict_treatment_response),
        ("survival", "deep_surv", service.predict_survival),
        ("anomaly", "anomaly_detector", service.predict_anomalies),
        ("state_transition", "state_transition", service.predict_state_transition),
    ]

    any_available = False
    for snap_key, model_id, fn in model_calls:
        try:
            result = fn(patient_id, record)
            if result is None:
                # Modelo desactivado por flag o no cargado
                meta = registry.get_metadata(model_id) if registry else {}
                snapshot["models"][snap_key] = {
                    "available": False,
                    "reason": _explain_unavailable(meta),
                    "model_version": meta.get("model_version", "unregistered"),
                    "maturity": meta.get("maturity", "not_loaded"),
                }
                continue

            # Decorar para UI consumption
            model_version = result.get("model_version", "unregistered")
            maturity = result.get("maturity", "experimental")
            snapshot["models"][snap_key] = {
                "available": True,
                "prediction": result,
                "model_version": model_version,
                "maturity": maturity,
                "advisory_only": True,
            }
            any_available = True

            # Audit trail (best-effort)
            _audit_ml_inference_call(patient_id, model_id, model_version, maturity)
        except Exception as exc:
            logger.debug("ML model %s failed for patient %d: %s", snap_key, patient_id, exc)
            snapshot["models"][snap_key] = {
                "available": False,
                "reason": f"model_error: {type(exc).__name__}",
                "model_version": "unknown",
                "maturity": "error",
            }

    snapshot["available"] = any_available
    return snapshot


def _explain_unavailable(metadata: dict[str, Any]) -> str:
    """Genera razón human-readable de por qué un modelo no respondió.

    Orden de prioridad (más específico primero):
      1. incompatible_checkpoint (retrain required, requiere acción explícita)
      2. load_error (información técnica útil para debug)
      3. artifact_missing (instalación incompleta)
      4. not_loaded (artifact existe, registry no lo cargó)
      5. feature_flag_disabled (default fallback si todo OK pero predict returned None)
    """
    if not metadata:
        return "no_metadata"
    if metadata.get("incompatible_vocab_version"):
        return "incompatible_checkpoint_retrain_required"
    # load_error tiene precedencia sobre 'not_loaded' porque es más informativo
    if metadata.get("load_error"):
        return f"load_error: {metadata['load_error'][:80]}"
    if not metadata.get("artifact_exists"):
        return "artifact_missing"
    if not metadata.get("loaded"):
        return "not_loaded"
    return "feature_flag_disabled_or_unknown"


# ─────────────────────────────────────────────────────────────────────
# GET endpoints por NSS (idempotent, server-friendly)
# ─────────────────────────────────────────────────────────────────────


def _patient_id_or_404(nss: str):
    patient_id = _resolve_patient_id_from_nss(nss)
    if not patient_id:
        return None, (jsonify({
            "success": False,
            "error": f"Paciente con NSS '{nss}' no encontrado",
        }), 404)
    return patient_id, None


def _single_model_get(nss: str, snap_key: str):
    """Helper genérico para los 4 endpoints single-model GET."""
    patient_id, err = _patient_id_or_404(nss)
    if err is not None:
        return err

    snapshot = build_ml_predictions_snapshot(patient_id)
    model_data = snapshot["models"].get(snap_key) or {}
    if not model_data.get("available"):
        return jsonify({
            "success": False,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "available": False,
            "reason": model_data.get("reason", "unavailable"),
            "model_version": model_data.get("model_version"),
            "maturity": model_data.get("maturity"),
        }), 503

    return jsonify({
        "success": True,
        "advisory_api": True,
        "rule_based_source_of_truth": True,
        "patient_id": patient_id,
        "nss": nss,
        "prediction": model_data["prediction"],
        "model_version": model_data["model_version"],
        "maturity": model_data["maturity"],
    })


@ml_inference_bp.route("/api/ml/treatment-response/<nss>", methods=["GET"])
def get_treatment_response_prediction(nss: str):
    """Top-3 regímenes ranked por probability of response a 6 meses."""
    return _single_model_get(nss, "treatment_response")


@ml_inference_bp.route("/api/ml/survival/<nss>", methods=["GET"])
def get_survival_prediction(nss: str):
    """OS estimate personalizado (mediana + IC 95% + curva)."""
    return _single_model_get(nss, "survival")


@ml_inference_bp.route("/api/ml/anomaly/<nss>", methods=["GET"])
def get_anomaly_prediction(nss: str):
    """Score de 'atypical presentation' + features driving anomaly."""
    return _single_model_get(nss, "anomaly")


@ml_inference_bp.route("/api/ml/state-transition/<nss>", methods=["GET"])
def get_state_transition_prediction(nss: str):
    """Predicción del próximo state clínico + tiempo esperado."""
    return _single_model_get(nss, "state_transition")


@ml_inference_bp.route("/api/ml/predictions/<nss>", methods=["GET"])
def get_all_predictions_bundle(nss: str):
    """Bundle con los 4 modelos en una sola llamada (para render server-side)."""
    patient_id, err = _patient_id_or_404(nss)
    if err is not None:
        return err

    snapshot = build_ml_predictions_snapshot(patient_id)
    return jsonify({
        "success": True,
        "patient_id": patient_id,
        "nss": nss,
        "advisory_api": True,
        "rule_based_source_of_truth": True,
        "ml_predictions": snapshot,
    })


__all__ = [
    "ml_inference_bp",
    "build_ml_predictions_snapshot",
]
