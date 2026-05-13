"""
Abstract base class for all ProstaNet AI models.

Every model must implement predict() and explain(), ensuring uniform
interface for the inference service and explanation engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import torch
import torch.nn as nn


@dataclass
class PredictionResult:
    """Standardized prediction output from any ProstaNet model."""

    model_id: str
    model_version: str
    prediction_type: str
    values: dict[str, Any]
    confidence: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prediction_type": self.prediction_type,
            "values": self.values,
            "confidence": self.confidence,
            "feature_importance": self.feature_importance,
            "metadata": self.metadata,
        }


class ProstaNetModel(ABC, nn.Module):
    """
    Abstract base for all ProstaNet neural network models.

    Subclasses must implement:
        - forward(): Standard PyTorch forward pass
        - predict(): High-level prediction returning PredictionResult
        - explain(): Feature importance / attention analysis
    """

    model_id: str = "base"
    model_version: str = "0.1.0"

    @abstractmethod
    def predict(self, patient_data: dict[str, Any]) -> PredictionResult:
        """
        High-level prediction from raw patient data.

        Args:
            patient_data: Patient record dict (from tracking_db or profile_compass)

        Returns:
            PredictionResult with model-specific values
        """
        ...

    @abstractmethod
    def explain(self, patient_data: dict[str, Any]) -> dict[str, Any]:
        """
        Generate explanation for a prediction.

        Returns:
            Dict with feature_importance, attention_weights, reasoning_chain
        """
        ...

    def save(self, path: str) -> None:
        """Save model weights and metadata."""
        torch.save(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "state_dict": self.state_dict(),
            },
            path,
        )

    def load(self, path: str, device: str = "cpu") -> None:
        """Load model weights from path.

        EPIC 16 / pytorch-patterns: weights_only=True bloquea ejecución de
        pickle arbitrario al deserializar checkpoints. Safe porque save()
        guarda solo state_dict (dict[str, Tensor]) + model_version (str).
        """
        checkpoint = torch.load(path, map_location=device, weights_only=True)
        self.load_state_dict(checkpoint["state_dict"])
        self.model_version = checkpoint.get("model_version", self.model_version)
