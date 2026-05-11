"""
ProstaNet AI — Configuration and hyperparameters.

Centralizes device selection, model hyperparameters, and runtime config.
All values can be overridden via environment variables or config dict.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _detect_device() -> str:
    """Detect best available compute device."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


# ── Clinical States (mirrors StateClassifierService) ─────────────────────

CLINICAL_STATES: list[str] = [
    "diagnostic_workup",
    "post_negative_biopsy_followup",
    "localized_initial",
    "post_prostatectomy",
    "recurrence_bcr",
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
]

STATE_TO_IDX: dict[str, int] = {s: i for i, s in enumerate(CLINICAL_STATES)}
IDX_TO_STATE: dict[int, str] = {i: s for i, s in enumerate(CLINICAL_STATES)}
NUM_STATES: int = len(CLINICAL_STATES)

AI_MODEL_IDS: list[str] = [
    "state_transition",
    "treatment_response",
    "deep_surv",
    "anomaly_detector",
    "nlp_extractor",
]

AI_MODEL_MATURITY_STATES: tuple[str, ...] = (
    "not_loaded",
    "experimental",
    "shadow",
    "advisory",
)


# ── Event Types (mirrors tracking_db write operations) ───────────────────

CLINICAL_EVENT_TYPES: list[str] = [
    "visit_recorded",
    "lab_value_updated",
    "imaging_completed",
    "treatment_started",
    "treatment_ended",
    "state_transition",
    "assessment_created",
    "document_uploaded",
    "bcr_detected",
    "response_assessed",
    "vital_status_changed",
]


# ── Hyperparameter Configs ───────────────────────────────────────────────

@dataclass
class StateTransitionConfig:
    """Config for the Transformer-based state transition predictor."""

    d_model: int = 256
    nhead: int = 8
    num_encoder_layers: int = 4
    dim_feedforward: int = 512
    dropout: float = 0.1
    max_sequence_length: int = 512
    learning_rate: float = 1e-4
    weight_decay: float = 1e-5
    batch_size: int = 32
    num_epochs: int = 100
    early_stopping_patience: int = 10


@dataclass
class TreatmentResponseConfig:
    """Config for the multi-task treatment response predictor."""

    patient_encoder_dims: list[int] = field(default_factory=lambda: [128, 256])
    treatment_embed_dim: int = 64
    fusion_dims: list[int] = field(default_factory=lambda: [256, 128])
    num_regimens: int = 50
    num_toxicity_domains: int = 8
    dropout: float = 0.25
    learning_rate: float = 1e-4
    batch_size: int = 32
    num_epochs: int = 80


@dataclass
class DeepSurvConfig:
    """Config for the DeepSurv Cox-nnet survival model."""

    hidden_dims: list[int] = field(default_factory=lambda: [128, 64, 32])
    dropout: float = 0.25
    learning_rate: float = 1e-4
    weight_decay: float = 1e-4
    batch_size: int = 64
    num_epochs: int = 100
    survival_timepoints: list[int] = field(
        default_factory=lambda: [6, 12, 24, 36, 60]
    )


@dataclass
class AnomalyDetectorConfig:
    """Config for the temporal VAE anomaly detector."""

    n_features: int = 9  # 7 lab families + ECOG + pain
    hidden_dim: int = 64
    latent_dim: int = 32
    n_gru_layers: int = 2
    window_size: int = 10  # Number of timepoints per window
    anomaly_threshold: float = 2.0  # Standard deviations above mean reconstruction error
    learning_rate: float = 1e-3
    batch_size: int = 64
    num_epochs: int = 50


@dataclass
class NLPExtractorConfig:
    """Config for the clinical NLP document extractor."""

    base_model: str = "dccuchile/bert-base-spanish-wwm-cased"  # BETO
    max_sequence_length: int = 512
    entity_types: list[str] = field(
        default_factory=lambda: [
            "PSA_VALUE",
            "GLEASON_SCORE",
            "TNM_STAGE",
            "DRUG_NAME",
            "DATE",
            "IMAGING_FINDING",
            "PIRADS_SCORE",
            "PATHOLOGY_FEATURE",
            "ISUP_GRADE",
            "ECOG_SCORE",
        ]
    )
    learning_rate: float = 2e-5
    batch_size: int = 16
    num_epochs: int = 10


# ── Global AI Config ─────────────────────────────────────────────────────

@dataclass
class AIConfig:
    """Master configuration for the ProstaNet AI subsystem."""

    device: str = ""
    model_dir: str = "output/models"
    runtime_mode: str = "shadow"
    require_registered_artifacts: bool = True
    require_training_provenance: bool = True
    require_metrics_for_advisory: bool = True
    state_transition: StateTransitionConfig = field(
        default_factory=StateTransitionConfig
    )
    treatment_response: TreatmentResponseConfig = field(
        default_factory=TreatmentResponseConfig
    )
    deep_surv: DeepSurvConfig = field(default_factory=DeepSurvConfig)
    anomaly_detector: AnomalyDetectorConfig = field(
        default_factory=AnomalyDetectorConfig
    )
    nlp_extractor: NLPExtractorConfig = field(default_factory=NLPExtractorConfig)

    def __post_init__(self) -> None:
        if not self.device:
            self.device = os.environ.get("PROSTANET_AI_DEVICE", _detect_device())
        self.model_dir = os.environ.get("PROSTANET_AI_MODEL_DIR", self.model_dir)
        runtime_mode = os.environ.get("PROSTANET_AI_RUNTIME_MODE", self.runtime_mode)
        runtime_mode = str(runtime_mode or "shadow").strip().lower()
        self.runtime_mode = runtime_mode if runtime_mode in {"shadow", "advisory"} else "shadow"
        self.require_registered_artifacts = os.environ.get(
            "PROSTANET_AI_REQUIRE_REGISTERED_ARTIFACTS",
            str(self.require_registered_artifacts),
        ).lower() in {"1", "true", "yes", "on"}
        self.require_training_provenance = os.environ.get(
            "PROSTANET_AI_REQUIRE_TRAINING_PROVENANCE",
            str(self.require_training_provenance),
        ).lower() in {"1", "true", "yes", "on"}
        self.require_metrics_for_advisory = os.environ.get(
            "PROSTANET_AI_REQUIRE_METRICS_FOR_ADVISORY",
            str(self.require_metrics_for_advisory),
        ).lower() in {"1", "true", "yes", "on"}


# ── Confidence Thresholds ────────────────────────────────────────────────

CONFIDENCE_HIGH: float = 80.0
CONFIDENCE_MODERATE: float = 50.0

CONFIDENCE_WEIGHTS: dict[str, float] = {
    "data_completeness": 0.25,
    "model_agreement": 0.25,
    "guideline_concordance": 0.20,
    "calibration": 0.15,
    "recency": 0.15,
}


# ── Singleton ────────────────────────────────────────────────────────────

_config: AIConfig | None = None


def get_ai_config(overrides: dict[str, Any] | None = None) -> AIConfig:
    """Get or create the global AI configuration."""
    global _config
    if _config is None:
        _config = AIConfig()
    if overrides:
        for key, value in overrides.items():
            if hasattr(_config, key):
                setattr(_config, key, value)
    return _config
