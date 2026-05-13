"""
Model Registry — runtime loading, versioning, and hot-swap of AI models.

Manages the lifecycle of trained models: load from disk, track versions,
switch active model, and provide a unified access interface.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

import torch

logger = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = Path("output/models")


class ModelRegistry:
    """
    Central registry for all ProstaNet AI models.

    Usage::

        registry = ModelRegistry()
        registry.load_model("state_transition", "output/models/state_transition/best.pt")
        model = registry.get("state_transition")
        result = model.predict(patient_record)
    """

    _missing_artifact_warning_keys: set[tuple[str, str]] = set()
    _warning_state_lock = Lock()

    def __init__(self, models_dir: str | Path | None = None) -> None:
        from prostanet.ai.config import AI_MODEL_IDS, get_ai_config

        self._models: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        config = get_ai_config()
        self.models_dir = Path(models_dir) if models_dir else Path(config.model_dir or DEFAULT_MODELS_DIR)
        self._known_models: tuple[str, ...] = tuple(AI_MODEL_IDS)

    def load_model(
        self,
        model_id: str,
        artifact_path: str | Path | None = None,
        device: str | None = None,
    ) -> bool:
        """
        Load a model from disk into the registry.

        If artifact_path is None, looks for default path under models_dir.
        """
        from prostanet.ai.config import AIConfig

        device = device or AIConfig().device
        status = self._build_status_metadata(model_id)

        if artifact_path is None:
            artifact_path = (
                status.get("artifact_path")
                or self.models_dir / model_id / "best.pt"
            )

        artifact_path = Path(artifact_path)
        if not artifact_path.exists():
            self._log_missing_artifact(model_id, artifact_path)
            self._metadata[model_id] = {
                **status,
                "artifact_path": str(artifact_path),
                "artifact_exists": False,
                "loaded": False,
            }
            return False

        try:
            self._clear_missing_artifact_log(model_id, artifact_path)
            model = self._instantiate_model(model_id)
            if model is None:
                return False

            model.load(str(artifact_path), device=device)
            model.eval()
            model_version = (
                status.get("model_version")
                or getattr(model, "model_version", "")
                or "unversioned"
            )
            setattr(model, "model_version", model_version)
            self._models[model_id] = model
            self._metadata[model_id] = {
                **status,
                "model_version": model_version,
                "artifact_path": str(artifact_path),
                "artifact_exists": True,
                "device": device,
                "loaded": True,
            }
            logger.info("Loaded model: %s from %s", model_id, artifact_path)
            return True
        except Exception as exc:
            logger.error("Failed to load model %s: %s", model_id, exc)
            self._metadata[model_id] = {
                **status,
                "artifact_path": str(artifact_path),
                "artifact_exists": True,
                "loaded": False,
                "load_error": str(exc),
            }
            return False

    @classmethod
    def reset_process_log_state(cls) -> None:
        with cls._warning_state_lock:
            cls._missing_artifact_warning_keys.clear()

    def get(self, model_id: str) -> Any | None:
        """Get a loaded model by ID. Returns None if not loaded."""
        return self._models.get(model_id)

    def is_loaded(self, model_id: str) -> bool:
        return model_id in self._models

    def list_models(self) -> dict[str, dict[str, Any]]:
        """List all registered models with metadata."""
        result: dict[str, dict[str, Any]] = {}
        for model_id in self._known_models:
            meta = self.get_metadata(model_id)
            result[model_id] = {
                **meta,
                "loaded": model_id in self._models,
            }
        return result

    def get_metadata(self, model_id: str) -> dict[str, Any]:
        """Return runtime + registry metadata for one model."""
        base = self._build_status_metadata(model_id)
        return {
            **base,
            **self._metadata.get(model_id, {}),
            "loaded": model_id in self._models,
        }

    def unload_model(self, model_id: str) -> bool:
        """Unload a model from memory."""
        if model_id in self._models:
            del self._models[model_id]
            logger.info("Unloaded model: %s", model_id)
            return True
        return False

    def load_all_available(self, device: str | None = None) -> dict[str, bool]:
        """Attempt to load all models found under models_dir."""
        results: dict[str, bool] = {}
        model_ids = [
            "state_transition",
            "treatment_response",
            "deep_surv",
            "anomaly_detector",
        ]
        for model_id in model_ids:
            results[model_id] = self.load_model(model_id, device=device)
        return results

    @staticmethod
    def _instantiate_model(model_id: str) -> Any | None:
        """Create a new (untrained) model instance by ID."""
        try:
            # EPIC 16 bugfix: model constructors tienen primer arg distinto a
            # config (vocab_size, input_dim, etc.). Usar kwarg config=... para
            # disambiguar y evitar `empty() got NoneType` errors.
            if model_id == "state_transition":
                from prostanet.ai.config import StateTransitionConfig
                from prostanet.ai.models.state_transition import (
                    StateTransitionTransformer,
                )
                return StateTransitionTransformer(config=StateTransitionConfig())

            elif model_id == "treatment_response":
                from prostanet.ai.config import TreatmentResponseConfig
                from prostanet.ai.models.treatment_response import (
                    TreatmentResponsePredictor,
                )
                return TreatmentResponsePredictor(config=TreatmentResponseConfig())

            elif model_id == "deep_surv":
                from prostanet.ai.config import DeepSurvConfig
                from prostanet.ai.models.deep_surv import DeepSurvNet
                return DeepSurvNet(config=DeepSurvConfig())

            elif model_id == "anomaly_detector":
                from prostanet.ai.config import AnomalyDetectorConfig
                from prostanet.ai.models.anomaly_detector import (
                    ClinicalSequenceVAE,
                )
                return ClinicalSequenceVAE(AnomalyDetectorConfig())

            else:
                logger.warning("Unknown model_id: %s", model_id)
                return None
        except Exception as exc:
            logger.error("Failed to instantiate %s: %s", model_id, exc)
            return None

    def register_in_db(
        self,
        model_id: str,
        model_version: str,
        model_type: str,
        artifact_path: str,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Register a model version in the ai_model_registry table."""
        try:
            import sqlite3
            from tracking_db import DB_PATH

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO ai_model_registry
                    (model_id, model_version, model_type, artifact_path, metrics_json, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    model_id,
                    model_version,
                    model_type,
                    artifact_path,
                    json.dumps(metrics, ensure_ascii=False) if metrics else None,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("DB registration failed: %s", exc)

    def _build_status_metadata(self, model_id: str) -> dict[str, Any]:
        registration = self._fetch_active_registration(model_id)
        artifact_path = None
        metrics = None
        is_active = False
        model_version = None
        if registration:
            artifact_path = registration.get("artifact_path")
            metrics = self._normalize_metrics(registration.get("metrics_json"))
            is_active = bool(registration.get("is_active"))
            model_version = registration.get("model_version")

        resolved_artifact_path = Path(artifact_path) if artifact_path else (self.models_dir / model_id / "best.pt")
        artifact_exists = resolved_artifact_path.exists()
        training_provenance_present = self._has_training_provenance(model_id, model_version)

        maturity = "not_loaded"
        validation_status = "artifact_missing"
        if artifact_exists:
            maturity = "experimental"
            validation_status = "artifact_only"
            if registration:
                validation_status = "registered"
                if training_provenance_present:
                    maturity = "shadow"
                    validation_status = "provenance_ready"
                if training_provenance_present and metrics:
                    maturity = "advisory"
                    validation_status = "validated"

        return {
            "model_id": model_id,
            "model_version": model_version or "unregistered",
            "artifact_path": str(resolved_artifact_path),
            "artifact_exists": artifact_exists,
            "artifact_registered": bool(registration),
            "training_provenance_present": training_provenance_present,
            "metrics_json": metrics,
            "is_active": is_active,
            "maturity": maturity,
            "validation_status": validation_status,
        }

    @classmethod
    def _log_missing_artifact(cls, model_id: str, artifact_path: Path) -> None:
        key = (model_id, str(artifact_path))
        with cls._warning_state_lock:
            if key in cls._missing_artifact_warning_keys:
                logger.debug("Model artifact still missing: %s", artifact_path)
                return
            cls._missing_artifact_warning_keys.add(key)
        logger.warning("Model artifact not found: %s", artifact_path)

    @classmethod
    def _clear_missing_artifact_log(cls, model_id: str, artifact_path: Path) -> None:
        key = (model_id, str(artifact_path))
        with cls._warning_state_lock:
            if key not in cls._missing_artifact_warning_keys:
                return
            cls._missing_artifact_warning_keys.discard(key)
        logger.info("Model artifact available again: %s", artifact_path)

    @staticmethod
    def _normalize_metrics(metrics_blob: Any) -> dict[str, Any] | None:
        if not metrics_blob:
            return None
        if isinstance(metrics_blob, dict):
            return metrics_blob
        if isinstance(metrics_blob, str):
            try:
                loaded = json.loads(metrics_blob)
                return loaded if isinstance(loaded, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    def _fetch_active_registration(self, model_id: str) -> dict[str, Any] | None:
        try:
            import sqlite3
            from tracking_db import DB_PATH

            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM ai_model_registry
                WHERE model_id = ?
                ORDER BY is_active DESC, created_at DESC, id DESC
                LIMIT 1
                """,
                (model_id,),
            )
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as exc:
            logger.debug("Model registry lookup failed for %s: %s", model_id, exc)
            return None

    def _has_training_provenance(
        self, model_id: str, model_version: str | None
    ) -> bool:
        if not model_version:
            return False
        try:
            import sqlite3
            from tracking_db import DB_PATH

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM training_data_provenance
                WHERE model_id = ? AND model_version = ?
                LIMIT 1
                """,
                (model_id, model_version),
            )
            row = cursor.fetchone()
            conn.close()
            return bool(row)
        except Exception as exc:
            logger.debug("Training provenance lookup failed for %s/%s: %s", model_id, model_version, exc)
            return False
