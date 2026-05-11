"""
Prediction Service — unified inference interface.

Single entry point for all AI predictions, with caching,
feature-flag gating, and automatic result persistence.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PredictionService:
    """
    Unified prediction interface for all AI models.

    Usage::

        service = PredictionService(model_registry)
        result = service.predict_state_transition(patient_id, record)
    """

    def __init__(self, model_registry: Any | None = None) -> None:
        self.model_registry = model_registry
        try:
            from prostanet.ai.config import get_ai_config

            self.runtime_mode = get_ai_config().runtime_mode
        except Exception:
            self.runtime_mode = "shadow"

    def predict_state_transition(
        self, patient_id: int, record: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Predict next clinical state and time to transition."""
        from prostanet.shared.feature_flags import resolve_feature_flags

        if not resolve_feature_flags().get("ENABLE_AI_STATE_PREDICTION"):
            return None

        model_id = "state_transition"
        model = self._get_model(model_id)
        if not model:
            return None

        try:
            result = model.predict(record)
            payload = self._decorate_prediction(model_id, result.values)
            self._persist_prediction(patient_id, model_id, record, payload)
            return payload
        except Exception as exc:
            logger.debug("State transition prediction failed: %s", exc)
            return None

    def predict_treatment_response(
        self,
        patient_id: int,
        record: dict[str, Any],
        regimen_id: int = 0,
    ) -> dict[str, Any] | None:
        """Predict treatment response for a specific regimen."""
        from prostanet.shared.feature_flags import resolve_feature_flags

        if not resolve_feature_flags().get("ENABLE_AI_TREATMENT_PREDICTION"):
            return None

        model_id = "treatment_response"
        model = self._get_model(model_id)
        if not model:
            return None

        try:
            result = model.predict(record, regimen_id=regimen_id)
            payload = self._decorate_prediction(
                model_id,
                result.values,
                extras={"requested_regimen_id": regimen_id},
            )
            self._persist_prediction(patient_id, model_id, record, payload)
            return payload
        except Exception as exc:
            logger.debug("Treatment response prediction failed: %s", exc)
            return None

    def predict_survival(
        self, patient_id: int, record: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Predict personalized survival curves."""
        from prostanet.shared.feature_flags import resolve_feature_flags

        if not resolve_feature_flags().get("ENABLE_AI_SURVIVAL_MODEL"):
            return None

        model_id = "deep_surv"
        model = self._get_model(model_id)
        if not model:
            return None

        try:
            result = model.predict(record)
            payload = self._decorate_prediction(model_id, result.values)
            self._persist_prediction(patient_id, model_id, record, payload)
            return payload
        except Exception as exc:
            logger.debug("Survival prediction failed: %s", exc)
            return None

    def predict_anomalies(
        self, patient_id: int, record: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Detect anomalies in temporal lab series."""
        from prostanet.shared.feature_flags import resolve_feature_flags

        if not resolve_feature_flags().get("ENABLE_AI_ANOMALY_DETECTION"):
            return None

        model_id = "anomaly_detector"
        model = self._get_model(model_id)
        if not model:
            return None

        try:
            result = model.predict(record)
            payload = self._decorate_prediction(model_id, result.values)
            self._persist_prediction(patient_id, model_id, record, payload)
            return payload
        except Exception as exc:
            logger.debug("Anomaly detection failed: %s", exc)
            return None

    def predict_all(
        self, patient_id: int, record: dict[str, Any]
    ) -> dict[str, Any]:
        """Run all available predictions for a patient."""
        results: dict[str, Any] = {}

        state = self.predict_state_transition(patient_id, record)
        if state:
            results["state_transition"] = state

        survival = self.predict_survival(patient_id, record)
        if survival:
            results["survival"] = survival

        anomalies = self.predict_anomalies(patient_id, record)
        if anomalies:
            results["anomalies"] = anomalies

        return results

    def _get_model(self, model_id: str) -> Any | None:
        if not self.model_registry:
            return None
        return self.model_registry.get(model_id)

    def _get_model_status(self, model_id: str) -> dict[str, Any]:
        if not self.model_registry or not hasattr(self.model_registry, "get_metadata"):
            return {
                "model_id": model_id,
                "model_version": "unregistered",
                "maturity": "not_loaded",
                "validation_status": "artifact_missing",
                "artifact_registered": False,
                "training_provenance_present": False,
                "bootstrap_completed": False,
                "loaded_model_count": 0,
                "missing_model_ids": [],
                "runtime_readiness": "not_initialized",
            }
        metadata = self.model_registry.get_metadata(model_id)
        try:
            from prostanet.ai.inference.runtime_registry import get_runtime_registry_health

            return {
                **metadata,
                **get_runtime_registry_health(registry=self.model_registry),
            }
        except Exception:
            return metadata

    def _decorate_prediction(
        self,
        model_id: str,
        prediction: dict[str, Any],
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status = self._get_model_status(model_id)
        payload = dict(prediction)
        payload.update(
            {
                "model_id": model_id,
                "model_version": status.get("model_version") or "unregistered",
                "maturity": status.get("maturity", "not_loaded"),
                "artifact_registered": bool(status.get("artifact_registered")),
                "training_provenance_present": bool(
                    status.get("training_provenance_present")
                ),
                "validation_status": status.get("validation_status", "artifact_missing"),
                "metrics_json": status.get("metrics_json"),
                "runtime_mode": self.runtime_mode,
                "advisory_only": True,
                "rule_based_source_of_truth": True,
                "qa_required": True,
            }
        )
        if extras:
            payload.update(extras)
        return payload

    def _persist_prediction(
        self,
        patient_id: int,
        model_id: str,
        record: dict[str, Any],
        prediction: dict[str, Any],
    ) -> None:
        """Store prediction in ai_predictions table for auditing."""
        try:
            import sqlite3
            from tracking_db import DB_PATH

            model_version = str(prediction.get("model_version") or "unregistered")
            input_hash = self._build_input_hash(
                patient_id=patient_id,
                model_id=model_id,
                model_version=model_version,
                record=record,
            )

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM ai_predictions
                WHERE patient_id = ? AND model_id = ? AND model_version = ? AND input_hash = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (patient_id, model_id, model_version, input_hash),
            )
            if cursor.fetchone():
                conn.close()
                return
            cursor.execute(
                """
                INSERT INTO ai_predictions
                    (patient_id, model_id, model_version, prediction_type,
                     input_hash, prediction_json, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient_id,
                    model_id,
                    model_version,
                    model_id,
                    input_hash,
                    json.dumps(prediction, ensure_ascii=False),
                    prediction.get("confidence") or prediction.get("confidence_score"),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("Prediction persistence failed: %s", exc)

    @classmethod
    def _build_input_hash(
        cls,
        *,
        patient_id: int,
        model_id: str,
        model_version: str,
        record: dict[str, Any],
    ) -> str:
        canonical_payload = {
            "patient_id": patient_id,
            "model_id": model_id,
            "model_version": model_version,
            "record": cls._normalize_for_hash(record),
        }
        encoded = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]

    @classmethod
    def _normalize_for_hash(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key in sorted(value.keys()):
                normalized[str(key)] = cls._normalize_for_hash(value[key])
            return normalized
        if isinstance(value, list):
            return [cls._normalize_for_hash(item) for item in value[:50]]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)
