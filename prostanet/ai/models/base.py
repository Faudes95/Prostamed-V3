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
        # EPIC 28.1 (GodiBot G39 CRIT) — include CLINICAL_STATES_VOCAB_VERSION
        # in the checkpoint so load() can verify compatibility instead of
        # crashing with size_mismatch on next_state_head.
        from prostanet.ai.config import CLINICAL_STATES_VOCAB_VERSION, NUM_STATES
        torch.save(
            {
                "model_id": self.model_id,
                "model_version": self.model_version,
                "vocab_version": CLINICAL_STATES_VOCAB_VERSION,
                "num_states": NUM_STATES,
                "state_dict": self.state_dict(),
            },
            path,
        )

    def load(self, path: str, device: str = "cpu") -> None:
        """Load model weights from path.

        EPIC 16 / pytorch-patterns: weights_only=True bloquea ejecución de
        pickle arbitrario al deserializar checkpoints. Safe porque save()
        guarda solo state_dict (dict[str, Tensor]) + model_version (str).

        EPIC 28.1 (GodiBot G39 CRIT) — validate vocab_version BEFORE
        load_state_dict so a v1 checkpoint loaded against v2 code raises
        IncompatibleCheckpointError early (captured by inference service
        to degrade gracefully to ai_substrate_status.state_transition=False)
        instead of crashing later inside torch.nn.Module.load_state_dict
        with cryptic size_mismatch.
        """
        from prostanet.ai.config import CLINICAL_STATES_VOCAB_VERSION, NUM_STATES
        checkpoint = torch.load(path, map_location=device, weights_only=True)
        ckpt_vocab_v = checkpoint.get("vocab_version")
        ckpt_num_states = checkpoint.get("num_states")
        # Only enforce when checkpoint declares vocab_version (legacy
        # checkpoints pre-EPIC28 didn't write it — accept with warning).
        if ckpt_vocab_v is not None and ckpt_vocab_v != CLINICAL_STATES_VOCAB_VERSION:
            raise IncompatibleCheckpointError(
                f"Checkpoint vocab_version={ckpt_vocab_v} does not match runtime "
                f"CLINICAL_STATES_VOCAB_VERSION={CLINICAL_STATES_VOCAB_VERSION}. "
                f"Retrain model after CLINICAL_STATES change. "
                f"checkpoint_num_states={ckpt_num_states}, runtime={NUM_STATES}."
            )
        if ckpt_num_states is not None and ckpt_num_states != NUM_STATES:
            raise IncompatibleCheckpointError(
                f"Checkpoint num_states={ckpt_num_states} != runtime {NUM_STATES}. "
                "next_state_head size mismatch will occur if loaded."
            )
        self.load_state_dict(checkpoint["state_dict"])
        self.model_version = checkpoint.get("model_version", self.model_version)


class IncompatibleCheckpointError(RuntimeError):
    """EPIC 28.1 — checkpoint vocab version incompatible with runtime.

    Raised by base.load() when CLINICAL_STATES_VOCAB_VERSION differs from
    the version embedded in the checkpoint. Inference service should catch
    this and degrade gracefully (ai_substrate_status[model_id]=False with
    log explaining the mismatch).
    """
