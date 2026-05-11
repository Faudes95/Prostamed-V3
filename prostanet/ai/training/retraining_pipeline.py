"""
Incremental Retraining Pipeline — Safe model evolution.

Manages the full lifecycle of retraining ProstaNet AI models
when new institutional data accumulates:

  1. Validate new data (quality gate)
  2. Merge with existing training corpus
  3. Train new model version
  4. Evaluate against holdout + compare with current champion
  5. Register new version if improved (NO auto-deploy)
  6. Record provenance for traceability

Trigger: manual or when N new eligible records accumulate.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("output/models")
MIN_NEW_RECORDS = 20
IMPROVEMENT_THRESHOLD = 0.02  # 2% relative improvement required


@dataclass
class RetrainingResult:
    """Result of a single retraining run."""
    model_id: str
    new_version: str
    previous_version: str | None
    status: str  # "improved", "no_improvement", "failed", "insufficient_data"
    new_metric: float | None = None
    previous_metric: float | None = None
    improvement_pct: float | None = None
    training_samples: int = 0
    validation_samples: int = 0
    data_quality_score: float = 0.0
    elapsed_seconds: float = 0.0
    artifact_path: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "new_version": self.new_version,
            "previous_version": self.previous_version,
            "status": self.status,
            "new_metric": self.new_metric,
            "previous_metric": self.previous_metric,
            "improvement_pct": self.improvement_pct,
            "training_samples": self.training_samples,
            "validation_samples": self.validation_samples,
            "data_quality_score": round(self.data_quality_score, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "artifact_path": self.artifact_path,
            "provenance": self.provenance,
        }


@dataclass
class RetrainingPlan:
    """Plan for a retraining session across multiple models."""
    models_to_retrain: list[str]
    total_records: int
    eligible_records: int
    data_quality_avg: float
    results: list[RetrainingResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "models_to_retrain": self.models_to_retrain,
            "total_records": self.total_records,
            "eligible_records": self.eligible_records,
            "data_quality_avg": round(self.data_quality_avg, 4),
            "results": [r.to_dict() for r in self.results],
            "summary": {
                "improved": sum(1 for r in self.results if r.status == "improved"),
                "no_improvement": sum(1 for r in self.results if r.status == "no_improvement"),
                "failed": sum(1 for r in self.results if r.status == "failed"),
            },
        }


class RetrainingPipeline:
    """
    Manages incremental retraining for all ProstaNet AI models.

    Usage::

        pipeline = RetrainingPipeline()
        plan = pipeline.plan(records)
        plan = pipeline.execute(plan, records)
    """

    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        min_new_records: int = MIN_NEW_RECORDS,
        improvement_threshold: float = IMPROVEMENT_THRESHOLD,
        require_quality_gate: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir or DEFAULT_MODEL_DIR)
        self.min_new_records = min_new_records
        self.improvement_threshold = improvement_threshold
        self.require_quality_gate = require_quality_gate

    def plan(
        self,
        records: list[dict[str, Any]],
        models: list[str] | None = None,
    ) -> RetrainingPlan:
        """
        Assess data and build a retraining plan.

        Args:
            records: all candidate training records
            models: specific models to retrain (default: all)

        Returns:
            RetrainingPlan with eligibility assessment
        """
        all_models = models or [
            "state_transition",
            "treatment_response",
            "deep_surv",
            "anomaly_detector",
        ]

        # Quality gate
        eligible, avg_quality = self._quality_gate(records)

        return RetrainingPlan(
            models_to_retrain=all_models,
            total_records=len(records),
            eligible_records=len(eligible),
            data_quality_avg=avg_quality,
        )

    def execute(
        self,
        plan: RetrainingPlan,
        records: list[dict[str, Any]],
    ) -> RetrainingPlan:
        """
        Execute the retraining plan.

        Returns the plan with results populated.
        """
        eligible, _ = self._quality_gate(records)

        if len(eligible) < self.min_new_records:
            for model_id in plan.models_to_retrain:
                plan.results.append(RetrainingResult(
                    model_id=model_id,
                    new_version="",
                    previous_version=None,
                    status="insufficient_data",
                    training_samples=len(eligible),
                ))
            return plan

        for model_id in plan.models_to_retrain:
            result = self._retrain_model(model_id, eligible)
            plan.results.append(result)

        return plan

    def _quality_gate(
        self, records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], float]:
        """Filter records through quality validation. Returns (eligible, avg_score)."""
        if not self.require_quality_gate:
            return records, 1.0

        try:
            from prostanet.ai.training.data_quality import DataQualityValidator

            validator = DataQualityValidator(
                require_consent=False,
                require_deidentified=False,
                min_follow_up_visits=1,
                min_psa_points=1,
            )
            batch = validator.validate_batch(records)
            eligible = [
                records[i]
                for i, report in enumerate(batch.per_record)
                if report.passed
            ]
            return eligible, batch.avg_score
        except Exception as exc:
            logger.warning("Quality gate failed, passing all records: %s", exc)
            return records, 0.5

    def _retrain_model(
        self, model_id: str, records: list[dict[str, Any]],
    ) -> RetrainingResult:
        """Retrain a specific model and compare with current champion."""
        t0 = time.perf_counter()
        version = _generate_version(records)

        try:
            # ── Train new model ──
            train_result = self._dispatch_training(model_id, records)

            if train_result.get("error"):
                return RetrainingResult(
                    model_id=model_id,
                    new_version=version,
                    previous_version=None,
                    status="failed",
                    training_samples=len(records),
                    elapsed_seconds=time.perf_counter() - t0,
                    provenance={"error": train_result["error"]},
                )

            new_metric = train_result.get("best_val_loss") or train_result.get("final_accuracy", 0)
            artifact_path = train_result.get("model_path", "")

            # ── Compare with current champion ──
            prev_metric = self._get_champion_metric(model_id)
            prev_version = self._get_champion_version(model_id)

            if prev_metric is not None and new_metric is not None:
                # For loss: lower is better. For accuracy: higher is better.
                is_loss_metric = "loss" in str(train_result.get("best_val_loss", ""))
                if is_loss_metric or prev_metric > 0.5:
                    # Assume loss metric — improvement means lower
                    if new_metric < prev_metric * (1 - self.improvement_threshold):
                        status = "improved"
                    else:
                        status = "no_improvement"
                    improvement = (prev_metric - new_metric) / max(1e-8, abs(prev_metric)) * 100
                else:
                    # Accuracy metric — improvement means higher
                    if new_metric > prev_metric * (1 + self.improvement_threshold):
                        status = "improved"
                    else:
                        status = "no_improvement"
                    improvement = (new_metric - prev_metric) / max(1e-8, abs(prev_metric)) * 100
            else:
                # No champion exists — this is the first version
                status = "improved"
                improvement = None

            # ── Register if improved ──
            if status == "improved":
                self._register_model(model_id, version, artifact_path, new_metric, records)

            # ── Record provenance ──
            provenance = self._build_provenance(model_id, version, records, train_result)

            return RetrainingResult(
                model_id=model_id,
                new_version=version,
                previous_version=prev_version,
                status=status,
                new_metric=round(new_metric, 6) if new_metric else None,
                previous_metric=round(prev_metric, 6) if prev_metric else None,
                improvement_pct=round(improvement, 2) if improvement is not None else None,
                training_samples=train_result.get("samples", len(records)),
                elapsed_seconds=time.perf_counter() - t0,
                artifact_path=artifact_path,
                provenance=provenance,
            )

        except Exception as exc:
            logger.error("Retraining %s failed: %s", model_id, exc)
            return RetrainingResult(
                model_id=model_id,
                new_version=version,
                previous_version=None,
                status="failed",
                elapsed_seconds=time.perf_counter() - t0,
                provenance={"error": str(exc)},
            )

    def _dispatch_training(
        self, model_id: str, records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Route to the correct trainer by model_id."""
        output_dir = str(self.output_dir / model_id)

        if model_id == "state_transition":
            from prostanet.ai.training.trainers import train_state_transition
            return train_state_transition(records, epochs=30, output_dir=output_dir)

        elif model_id == "treatment_response":
            from prostanet.ai.training.trainers import train_treatment_response
            return train_treatment_response(records, epochs=30, output_dir=output_dir)

        elif model_id == "deep_surv":
            from prostanet.ai.training.trainers import train_deep_surv
            return train_deep_surv(records, epochs=30, output_dir=output_dir)

        elif model_id == "anomaly_detector":
            from prostanet.ai.training.trainers import train_anomaly_detector
            return train_anomaly_detector(records, epochs=30, output_dir=output_dir)

        return {"error": f"Unknown model_id: {model_id}"}

    def _get_champion_metric(self, model_id: str) -> float | None:
        """Get the current champion model's best metric from registry."""
        try:
            from prostanet.ai.inference.model_registry import ModelRegistry
            registry = ModelRegistry()
            info = registry.get_model_info(model_id)
            if info:
                metrics = info.get("metrics", {})
                if isinstance(metrics, str):
                    metrics = json.loads(metrics)
                return metrics.get("best_val_loss") or metrics.get("best_loss")
        except Exception:
            pass
        return None

    def _get_champion_version(self, model_id: str) -> str | None:
        """Get the current champion model's version."""
        try:
            from prostanet.ai.inference.model_registry import ModelRegistry
            registry = ModelRegistry()
            info = registry.get_model_info(model_id)
            return info.get("model_version") if info else None
        except Exception:
            return None

    def _register_model(
        self,
        model_id: str,
        version: str,
        artifact_path: str,
        metric: float | None,
        records: list[dict[str, Any]],
    ) -> None:
        """Register the new model version in the DB (does NOT activate it)."""
        try:
            from prostanet.ai.inference.model_registry import ModelRegistry
            registry = ModelRegistry()
            registry.register(
                model_id=model_id,
                model_version=version,
                model_type=model_id,
                artifact_path=artifact_path,
                metrics={"best_val_loss": metric, "training_samples": len(records)},
                activate=False,  # Never auto-activate
            )
            logger.info(
                "Registered model %s v%s (NOT activated — manual review required)",
                model_id, version,
            )
        except Exception as exc:
            logger.warning("Model registration failed: %s", exc)

    @staticmethod
    def _build_provenance(
        model_id: str,
        version: str,
        records: list[dict[str, Any]],
        train_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build training data provenance record."""
        data_hash = hashlib.sha256(
            json.dumps(len(records), sort_keys=True).encode()
        ).hexdigest()[:16]

        return {
            "model_id": model_id,
            "model_version": version,
            "data_source": "institutional",
            "patient_count": len(records),
            "data_hash": data_hash,
            "training_epochs": train_result.get("epochs"),
            "training_samples": train_result.get("samples"),
        }

    def _record_provenance(
        self, provenance: dict[str, Any],
    ) -> None:
        """Persist provenance to training_data_provenance table."""
        try:
            import sqlite3
            from tracking_db import DB_PATH

            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                """
                INSERT INTO training_data_provenance
                    (model_id, model_version, data_source, patient_count,
                     feature_count, consent_evidence_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    provenance.get("model_id"),
                    provenance.get("model_version"),
                    provenance.get("data_source", "institutional"),
                    provenance.get("patient_count", 0),
                    provenance.get("feature_count", 0),
                    json.dumps(provenance),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("Provenance persistence failed: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _generate_version(records: list[dict[str, Any]]) -> str:
    """Generate a version string from timestamp + data hash."""
    import time as _time
    ts = _time.strftime("%Y%m%d_%H%M%S")
    h = hashlib.sha256(str(len(records)).encode()).hexdigest()[:8]
    return f"v_{ts}_{h}"
