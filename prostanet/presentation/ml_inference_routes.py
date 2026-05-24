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
import threading
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, jsonify

from prostanet.shared.api_auth import require_clinician, current_api_user_id

logger = logging.getLogger(__name__)

ml_inference_bp = Blueprint("ml_inference", __name__)


# ─────────────────────────────────────────────────────────────────────
# Constantes (Sprint 6 LOW cleanup)
# ─────────────────────────────────────────────────────────────────────


UNREGISTERED_VERSION = "unregistered"
UNKNOWN_VERSION = "unknown"
ERROR_MATURITY = "error"
ADVISORY_AUDIT_IMPORTANCE = "low"
ADVISORY_AUDIT_IMPORTANCE_SURVIVAL = "medium"  # OS prediction merece tracking más alto


# ─────────────────────────────────────────────────────────────────────
# Sprint 6.D — Cached singleton PredictionService (evita recargar 4 PyTorch
# models en cada request — antes recarga era ~0.5–1.5s por GET)
# ─────────────────────────────────────────────────────────────────────


_PREDICTION_SERVICE_CACHE: dict[str, Any] = {"service": None, "registry": None}
_PREDICTION_SERVICE_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────
# Helper compartido — usado por endpoints + view model
# ─────────────────────────────────────────────────────────────────────


class PatientResolutionError(Exception):
    """Sprint 6 (Finding H ML.HIGH): distingue infrastructure_error (5xx)
    de not_found (404). Antes _resolve_patient_id_from_nss silently
    swallowing all exceptions → cliente veía 404 cuando la DB fallaba."""
    pass


def _resolve_patient_id_from_nss(nss: str) -> int | None:
    """Resuelve NSS → patient_id usando tracking_db.

    Returns None si NSS no existe (legítimo 404).
    Raises PatientResolutionError si hay fallo de infrastructure (DB down,
    schema mismatch, etc.) — caller distingue para retornar 500 apropiado.
    """
    try:
        import tracking_db
        core = tracking_db.load_patient_record_core(nss)
        if not core:
            return None
        identity = core.get("identity") if isinstance(core, dict) else None
        if identity and isinstance(identity, dict):
            return int(identity.get("id") or 0) or None
        return None
    except Exception as exc:
        # Sprint 6: logger.warning (no debug) — fallos de DB deben ser visibles
        logger.warning("DB error resolving NSS %s to patient_id: %s: %s",
                       nss, type(exc).__name__, exc)
        raise PatientResolutionError(str(exc)) from exc


def _audit_ml_inference_call(
    patient_id: int,
    model_id: str,
    model_version: str,
    maturity: str,
    importance: str = ADVISORY_AUDIT_IMPORTANCE,
    actor_user_id: int | None = None,
) -> None:
    """Registra en clinical_view_audit cada llamada a ML inference para
    trazabilidad SaMD nivel 2 (reproducibilidad regulatoria).

    Sprint 6 mejoras:
      - try/finally para conn.close() (no más resource leak)
      - logger.warning si falla (no .debug — viola §820.30 si no se ve)
      - importance parametrizable (survival merece 'medium' vs 'low')
      - actor_user_id desde session (no del payload)
    """
    import sqlite3
    from tracking_db import DB_PATH

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
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
                f"ml_predict:{model_id}:{model_version}"
                + (f":user_{actor_user_id}" if actor_user_id else ""),
                importance,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        # Sprint 6 C6: warning (no debug) — audit log failures viola §820.30
        # si no se observan en producción.
        logger.warning(
            "ML inference audit log FAILED (REGULATORY) for patient=%d model=%s: %s: %s",
            patient_id, model_id, type(exc).__name__, exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _get_or_build_prediction_service():
    """Sprint 6.D: cached singleton del PredictionService + ModelRegistry.

    Antes (CXLIII): cada request invocaba `_build_prediction_service()` →
    recargaba los 4 modelos PyTorch desde disco. Latencia 0.3-1.5s/request
    + I/O excesivo + memory churn.

    Ahora: lock-protected dict module-level. Primera request paga el cost
    de carga (1-2s). Subsiguientes reutilizan instancia ya cargada.
    """
    if _PREDICTION_SERVICE_CACHE["service"] is not None:
        return _PREDICTION_SERVICE_CACHE["service"], _PREDICTION_SERVICE_CACHE["registry"]

    with _PREDICTION_SERVICE_LOCK:
        # Double-check después de adquirir lock
        if _PREDICTION_SERVICE_CACHE["service"] is not None:
            return _PREDICTION_SERVICE_CACHE["service"], _PREDICTION_SERVICE_CACHE["registry"]

        service, registry = _build_prediction_service_uncached()
        _PREDICTION_SERVICE_CACHE["service"] = service
        _PREDICTION_SERVICE_CACHE["registry"] = registry
        return service, registry


def reset_prediction_service_cache() -> None:
    """Test helper — fuerza re-load del service en próxima request.
    Útil después de model retrain en runtime."""
    with _PREDICTION_SERVICE_LOCK:
        _PREDICTION_SERVICE_CACHE["service"] = None
        _PREDICTION_SERVICE_CACHE["registry"] = None


def _build_prediction_service_uncached():
    """Construye PredictionService desde cero (sin cache).

    Usado internamente por _get_or_build_prediction_service. NO llamar
    directamente desde handlers — usa el cached wrapper en su lugar.
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
        logger.warning("Failed to build PredictionService: %s: %s",
                       type(exc).__name__, exc)
        return None, None


# Backwards-compat alias para callers existentes (deprecated, use _get_or_build)
def _build_prediction_service():
    """DEPRECATED — use _get_or_build_prediction_service() for caching."""
    return _get_or_build_prediction_service()


def build_ml_predictions_snapshot(
    patient_id: int,
    *,
    models_to_run: list[str] | None = None,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Construye el snapshot de las 4 predicciones para un paciente.

    Sprint 6 mejoras:
      - `models_to_run` parameter — ejecuta solo modelos solicitados (antes
        single-model GET corría los 4 desechando 3). Default None = los 4.
      - `actor_user_id` — viene del session via current_api_user_id()
        para audit trail
      - logger.warning (no debug) en model_error para visibilidad

    Diseñado para ser invocado desde profile_compass.build_patient_profile_view_model
    durante render del perfil. Fail-safe: si cualquier modelo falla,
    retorna `available=False` con razón explicativa en lugar de levantar.
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

    service, registry = _get_or_build_prediction_service()
    if service is None:
        snapshot["reason"] = "prediction_service_unavailable"
        return snapshot

    # Patient record (single fetch, reusado por los modelos a correr)
    try:
        import tracking_db
        record = tracking_db.get_patient_full_record(patient_id)
    except Exception as exc:
        # Sprint 6 C6: no leak exc detail al cliente; solo log
        logger.warning("ML snapshot patient fetch failed for %d: %s: %s",
                       patient_id, type(exc).__name__, exc)
        snapshot["reason"] = "patient_record_fetch_failed"
        return snapshot

    if not record:
        snapshot["reason"] = "patient_not_found"
        return snapshot

    # Invoke each model with fail-safe wrapper
    all_model_calls: list[tuple[str, str, Any, str]] = [
        # (snapshot_key, model_id_for_registry, callable, audit_importance)
        ("treatment_response", "treatment_response", service.predict_treatment_response,
         ADVISORY_AUDIT_IMPORTANCE),
        ("survival", "deep_surv", service.predict_survival,
         ADVISORY_AUDIT_IMPORTANCE_SURVIVAL),  # OS prediction merece tracking más alto
        ("anomaly", "anomaly_detector", service.predict_anomalies,
         ADVISORY_AUDIT_IMPORTANCE),
        ("state_transition", "state_transition", service.predict_state_transition,
         ADVISORY_AUDIT_IMPORTANCE),
    ]

    # Sprint 6.D: filter models si se especifica subset
    if models_to_run is not None:
        models_set = set(models_to_run)
        all_model_calls = [m for m in all_model_calls if m[0] in models_set]

    any_available = False
    for snap_key, model_id, fn, importance in all_model_calls:
        try:
            result = fn(patient_id, record)
            if result is None:
                # Modelo desactivado por flag o no cargado
                meta = registry.get_metadata(model_id) if registry else {}
                snapshot["models"][snap_key] = {
                    "available": False,
                    "reason": _explain_unavailable(meta),
                    "model_version": meta.get("model_version", UNREGISTERED_VERSION),
                    "maturity": meta.get("maturity", "not_loaded"),
                }
                continue

            # Decorar para UI consumption
            model_version = result.get("model_version", UNREGISTERED_VERSION)
            maturity = result.get("maturity", "experimental")
            snapshot["models"][snap_key] = {
                "available": True,
                "prediction": result,
                "model_version": model_version,
                "maturity": maturity,
                "advisory_only": True,
            }
            any_available = True

            # Audit trail (best-effort) — Sprint 6 con importance + actor_user_id
            _audit_ml_inference_call(
                patient_id, model_id, model_version, maturity,
                importance=importance, actor_user_id=actor_user_id,
            )
        except (TypeError, AttributeError, ValueError) as exc:
            # Sprint 6 ML.HIGH: capturar TIPOS específicos esperados.
            # No capturar Exception genérico que oculta bugs de programación.
            logger.warning("ML model %s data/shape error for patient %d: %s: %s",
                           snap_key, patient_id, type(exc).__name__, exc)
            snapshot["models"][snap_key] = {
                "available": False,
                "reason": f"model_data_error: {type(exc).__name__}",
                "model_version": UNKNOWN_VERSION,
                "maturity": ERROR_MATURITY,
            }
        except Exception as exc:
            # Otros errores: log con stack para observabilidad pero no leak al cliente
            logger.exception("ML model %s unexpected error for patient %d: %s",
                             snap_key, patient_id, exc)
            snapshot["models"][snap_key] = {
                "available": False,
                "reason": f"model_error: {type(exc).__name__}",
                "model_version": UNKNOWN_VERSION,
                "maturity": ERROR_MATURITY,
            }

    snapshot["available"] = any_available
    return snapshot


def _faubot_release_snapshot() -> str:
    """Sprint 6: snapshot del FAUBOT_RELEASE para incluir en JSON responses
    (reproducibilidad SaMD §820.30)."""
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


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
    """Resuelve NSS → patient_id, distinguiendo not_found (404) vs infra_error (500).

    Sprint 6 ML.HIGH fix: antes silently swallowing exception → 404 universal.
    """
    try:
        patient_id = _resolve_patient_id_from_nss(nss)
    except PatientResolutionError as exc:
        # Sprint 6 C6: no leak exc detail al cliente
        logger.warning("Patient resolution infrastructure error for nss=%s: %s",
                       nss, exc)
        return None, (jsonify({
            "success": False,
            "error": "patient_resolution_error",
            "message": "Error temporal de infraestructura. Intente de nuevo.",
        }), 500)
    if not patient_id:
        return None, (jsonify({
            "success": False,
            "error": "patient_not_found",
            "message": f"NSS '{nss}' no registrado",
        }), 404)
    return patient_id, None


def _single_model_get(nss: str, snap_key: str):
    """Helper genérico para los 4 endpoints single-model GET.

    Sprint 6.D: Ejecuta SOLO el modelo solicitado (antes corría los 4 y
    desechaba 3). Reducción esperada ~75% en CPU/latencia por GET single.
    """
    patient_id, err = _patient_id_or_404(nss)
    if err is not None:
        return err

    actor_user_id = current_api_user_id()
    snapshot = build_ml_predictions_snapshot(
        patient_id,
        models_to_run=[snap_key],
        actor_user_id=actor_user_id,
    )
    faubot = _faubot_release_snapshot()
    model_data = snapshot["models"].get(snap_key) or {}
    if not model_data.get("available"):
        return jsonify({
            "success": False,
            "advisory_api": True,
            "rule_based_source_of_truth": True,
            "available": False,
            "patient_id": patient_id,  # Sprint 6 MED: shape consistency
            "nss": nss,
            "reason": model_data.get("reason", "unavailable"),
            "model_version": model_data.get("model_version", UNREGISTERED_VERSION),
            "maturity": model_data.get("maturity", "not_loaded"),
            "faubot_release": faubot,  # Sprint 6 HIGH: algorithm_version snapshot
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
        "faubot_release": faubot,  # Sprint 6 HIGH: reproducibility
    })


@ml_inference_bp.route("/api/ml/treatment-response/<nss>", methods=["GET"])
@require_clinician
def get_treatment_response_prediction(nss: str):
    """Top-3 regímenes ranked por probability of response a 6 meses.

    Sprint 6 C1: protected by @require_clinician (HIPAA + SaMD §820.30).
    """
    return _single_model_get(nss, "treatment_response")


@ml_inference_bp.route("/api/ml/survival/<nss>", methods=["GET"])
@require_clinician
def get_survival_prediction(nss: str):
    """OS estimate personalizado (mediana + IC 95% + curva). Auth required."""
    return _single_model_get(nss, "survival")


@ml_inference_bp.route("/api/ml/anomaly/<nss>", methods=["GET"])
@require_clinician
def get_anomaly_prediction(nss: str):
    """Score de 'atypical presentation' + features driving anomaly. Auth required."""
    return _single_model_get(nss, "anomaly")


@ml_inference_bp.route("/api/ml/state-transition/<nss>", methods=["GET"])
@require_clinician
def get_state_transition_prediction(nss: str):
    """Predicción del próximo state clínico + tiempo esperado. Auth required.

    Sprint 6 C8 mitigation: si el modelo falla por size_mismatch, devuelve
    503 con shape estable + reason explícita 'incompatible_checkpoint_retrain_required'.
    UI debe mostrar badge 'Modelo en re-entrenamiento' en lugar de error genérico.
    """
    return _single_model_get(nss, "state_transition")


@ml_inference_bp.route("/api/ml/predictions/<nss>", methods=["GET"])
@require_clinician
def get_all_predictions_bundle(nss: str):
    """Bundle con los 4 modelos en una sola llamada (para render server-side).

    Sprint 6 ML.MED: audit del bundle como tal (antes solo se auditaban
    llamadas individuales). Sprint 6 C1: auth required.
    """
    patient_id, err = _patient_id_or_404(nss)
    if err is not None:
        return err

    actor_user_id = current_api_user_id()
    snapshot = build_ml_predictions_snapshot(patient_id, actor_user_id=actor_user_id)
    faubot = _faubot_release_snapshot()

    # Sprint 6 ML.MED: audit bundle-level llamada
    try:
        _audit_ml_inference_call(
            patient_id, "bundle", faubot, "bundle_view",
            importance=ADVISORY_AUDIT_IMPORTANCE_SURVIVAL,
            actor_user_id=actor_user_id,
        )
    except Exception:
        pass  # ya logged dentro

    return jsonify({
        "success": True,
        "patient_id": patient_id,
        "nss": nss,
        "advisory_api": True,
        "rule_based_source_of_truth": True,
        "ml_predictions": snapshot,
        "faubot_release": faubot,  # Sprint 6 HIGH: reproducibility snapshot
        "any_available": snapshot.get("available", False),  # Sprint 6 ML.MED
    })


__all__ = [
    "ml_inference_bp",
    "build_ml_predictions_snapshot",
]
