"""
DeepSurv — Neural Network Cox Proportional Hazards Model.

Implements a deep learning extension of the Cox PH model for
personalized survival curve estimation across 9 PCWG3 endpoints.

Architecture:
    Risk network: Input → [128, 64, 32] with BatchNorm, ReLU, Dropout
    Output: Log-hazard ratio (scalar) per patient
    Loss: Negative partial log-likelihood
    Prediction: Survival curves at [6, 12, 24, 36, 60] months

References:
    - Katzman et al. "DeepSurv: Personalized Treatment Recommender" (2018)
    - Published medians from survival_endpoints.py (CHAARTED, AFFIRM, etc.)
"""

from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn

from prostanet.ai.config import DeepSurvConfig, get_ai_config
from prostanet.ai.models.base import ProstaNetModel, PredictionResult
from prostanet.ai.models.treatment_response import (
    PATIENT_NUMERIC_FEATURES,
    PATIENT_BINARY_FEATURES,
    TOTAL_PATIENT_FEATURES,
)


# Published medians from survival_endpoints.py for context
PUBLISHED_MEDIANS: dict[str, dict[str, Any]] = {
    "OS_m1_crpc": {"median_months": 15.1, "trial": "TROPIC", "agent": "Cabazitaxel"},
    "OS_m1_crpc_post_arpi": {"median_months": 18.4, "trial": "AFFIRM", "agent": "Enzalutamida"},
    "rPFS_m1_crpc": {"median_months": 20.0, "trial": "PREVAIL", "agent": "Enzalutamida"},
    "MFS_m0_crpc": {"median_months": 40.4, "trial": "SPARTAN", "agent": "Apalutamida"},
    "MFS_m0_crpc_daro": {"median_months": 40.4, "trial": "PROSPER", "agent": "Darolutamida"},
    "OS_mcspc_triplet": {"median_months": 48.9, "trial": "ARASENS", "agent": "Triplete (ADT+D+Daro)"},
    "OS_mcspc_high_volume": {"median_months": 49.2, "trial": "CHAARTED", "agent": "ADT+Docetaxel"},
}

ENDPOINT_TYPES = [
    "OS",
    "rPFS",
    "MFS",
    "BCR_FS",
    "TTPP",
    "TTSRE",
    "time_to_crpc",
    "time_to_next_line",
]


class DeepSurvNet(ProstaNetModel):
    """
    Cox proportional hazards model with neural network risk function.

    Produces personalized survival curves by computing a patient-specific
    log-hazard ratio that modifies a baseline hazard function.
    """

    model_id = "deep_surv"
    model_version = "0.1.0"

    def __init__(
        self,
        input_dim: int = TOTAL_PATIENT_FEATURES,
        config: DeepSurvConfig | None = None,
    ) -> None:
        super().__init__()

        if config is None:
            config = get_ai_config().deep_surv
        self.config = config

        # Risk network
        layers: list[nn.Module] = []
        in_dim = input_dim
        for hidden_dim in config.hidden_dims:
            layers.extend([
                nn.Linear(in_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.ReLU(),
                nn.Dropout(config.dropout),
            ])
            in_dim = hidden_dim
        self.risk_network = nn.Sequential(*layers)

        # Per-endpoint risk heads
        self.endpoint_heads = nn.ModuleDict({
            ep: nn.Linear(config.hidden_dims[-1], 1)
            for ep in ENDPOINT_TYPES
        })

        # Learnable baseline cumulative hazard at standard timepoints
        n_timepoints = len(config.survival_timepoints)
        self.baseline_cum_hazard = nn.ParameterDict({
            ep: nn.Parameter(torch.linspace(0.1, 2.0, n_timepoints))
            for ep in ENDPOINT_TYPES
        })

    def forward(
        self,
        patient_features: torch.Tensor,
        endpoint: str = "OS",
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            patient_features: [B, input_dim]
            endpoint: Which survival endpoint to predict

        Returns:
            log_hazard_ratio: [B, 1]
            survival_curve: [B, n_timepoints]
        """
        # Shared risk representation
        risk_repr = self.risk_network(patient_features)

        # Endpoint-specific log-hazard ratio
        log_hr = self.endpoint_heads[endpoint](risk_repr)  # [B, 1]

        # Survival curve: S(t) = exp(-H0(t) * exp(log_hr))
        baseline_H0 = F.softplus(self.baseline_cum_hazard[endpoint])  # Ensure positive
        hazard = baseline_H0.unsqueeze(0) * torch.exp(log_hr)  # [B, T]
        survival_curve = torch.exp(-hazard)  # [B, T]

        return {
            "log_hazard_ratio": log_hr,
            "survival_curve": survival_curve,
            "baseline_cumulative_hazard": baseline_H0,
        }

    def predict_all_endpoints(
        self,
        patient_features: torch.Tensor,
    ) -> dict[str, dict[str, torch.Tensor]]:
        """Predict survival curves for all endpoints."""
        results = {}
        for endpoint in ENDPOINT_TYPES:
            results[endpoint] = self.forward(patient_features, endpoint)
        return results

    @staticmethod
    def _extract_features(patient_data: dict[str, Any]) -> list[float]:
        """Reuse treatment_response feature extraction."""
        from prostanet.ai.models.treatment_response import TreatmentResponsePredictor
        return TreatmentResponsePredictor._extract_patient_features(patient_data)

    def predict(self, patient_data: dict[str, Any]) -> PredictionResult:
        """Predict personalized survival curves for all endpoints."""
        self.eval()
        device = next(self.parameters()).device

        features = self._extract_features(patient_data)
        feat_tensor = torch.tensor([features], dtype=torch.float32, device=device)
        timepoints = self.config.survival_timepoints

        all_curves: dict[str, Any] = {}

        with torch.no_grad():
            for endpoint in ENDPOINT_TYPES:
                out = self.forward(feat_tensor, endpoint)
                curve = out["survival_curve"][0].cpu().tolist()
                log_hr = out["log_hazard_ratio"][0, 0].item()

                # Estimate median survival (interpolate where S(t) = 0.5)
                median = self._estimate_median(timepoints, curve)

                # Add published context
                context_key = f"{endpoint}_{patient_data.get('reconciled_state', '')}"
                reference = PUBLISHED_MEDIANS.get(context_key, {})

                all_curves[endpoint] = {
                    "survival_probabilities": {
                        f"{t}m": round(s, 4) for t, s in zip(timepoints, curve)
                    },
                    "median_months": median,
                    "log_hazard_ratio": round(log_hr, 4),
                    "reference_median": reference.get("median_months"),
                    "reference_trial": reference.get("trial", ""),
                }

        return PredictionResult(
            model_id=self.model_id,
            model_version=self.model_version,
            prediction_type="survival_curves",
            values={"endpoints": all_curves, "timepoints_months": timepoints},
            confidence=75.0,
        )

    @staticmethod
    def _estimate_median(
        timepoints: list[int], survival_probs: list[float]
    ) -> float | None:
        """Estimate median survival by linear interpolation."""
        for i in range(len(survival_probs) - 1):
            if survival_probs[i] >= 0.5 >= survival_probs[i + 1]:
                t1, t2 = timepoints[i], timepoints[i + 1]
                s1, s2 = survival_probs[i], survival_probs[i + 1]
                if s1 == s2:
                    return float(t1)
                fraction = (s1 - 0.5) / (s1 - s2)
                return round(t1 + fraction * (t2 - t1), 1)
        if survival_probs[-1] > 0.5:
            return None  # Median not reached
        return float(timepoints[-1])

    def explain(self, patient_data: dict[str, Any]) -> dict[str, Any]:
        features = self._extract_features(patient_data)
        all_names = PATIENT_NUMERIC_FEATURES + PATIENT_BINARY_FEATURES
        return {
            "input_features": {
                name: val for name, val in zip(all_names, features)
            },
            "endpoints_predicted": ENDPOINT_TYPES,
            "model_type": "deep_surv_cox_nnet",
        }


def cox_ph_loss(
    log_hazard_ratios: torch.Tensor,
    event_times: torch.Tensor,
    event_indicators: torch.Tensor,
) -> torch.Tensor:
    """
    Negative partial log-likelihood for Cox PH model.

    Args:
        log_hazard_ratios: [N] predicted log-hazard ratios
        event_times: [N] observed times (months)
        event_indicators: [N] 1=event occurred, 0=censored
    """
    # Sort by descending event time
    sorted_indices = torch.argsort(event_times, descending=True)
    sorted_hr = log_hazard_ratios[sorted_indices]
    sorted_events = event_indicators[sorted_indices]

    # Cumulative sum of exp(hr) in risk sets
    cumsum_hr = torch.cumsum(torch.exp(sorted_hr), dim=0)
    log_cumsum = torch.log(cumsum_hr + 1e-7)

    # Partial log-likelihood (only for uncensored)
    pll = sorted_hr - log_cumsum
    pll = pll * sorted_events

    # Negative mean
    n_events = sorted_events.sum()
    if n_events == 0:
        # EPIC 17 bugfix: return grad-aware zero, NOT torch.tensor(0.0).
        # Fresh tensor lacks grad_fn → loss.backward() crashes con
        # "element 0 of tensors does not require grad and does not have
        # a grad_fn". Multiply log_hazard_ratios * 0 preserves graph.
        return (log_hazard_ratios * 0.0).sum()
    return -pll.sum() / n_events
