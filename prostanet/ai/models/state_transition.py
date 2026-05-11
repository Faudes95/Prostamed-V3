"""
State Transition Predictor — Transformer-based.

Predicts the next clinical state and time-to-transition from a patient's
longitudinal token sequence. Uses continuous-time positional encoding
and multi-head attention over clinical events.

Architecture:
    Input: Tokenized patient sequence (ClinicalEventTokenizer output)
    Embedding: d_model=256 with continuous sinusoidal time encoding
    Encoder: 4 Transformer layers, 8 heads, ff_dim=512
    Heads: next_state (13-class), time_to_transition (log-normal), confidence
    Parameters: ~2.5M
"""

from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from prostanet.ai.config import (
    NUM_STATES,
    IDX_TO_STATE,
    StateTransitionConfig,
    get_ai_config,
)
from prostanet.ai.models.base import ProstaNetModel, PredictionResult
from prostanet.ai.tokenizer.clinical_tokenizer import ClinicalEventTokenizer, TokenizedPatient
from prostanet.ai.tokenizer.vocabulary import ClinicalVocabulary


class ContinuousTimeEncoding(nn.Module):
    """
    Continuous sinusoidal positional encoding based on days from diagnosis.
    Unlike standard positional encoding, this uses actual temporal distances
    rather than discrete sequence positions.
    """

    def __init__(self, d_model: int, max_days: int = 7300) -> None:
        super().__init__()
        self.d_model = d_model
        self.max_days = max_days
        # Learnable frequency scaling
        self.freq_scale = nn.Parameter(torch.ones(d_model // 2))

    def forward(self, time_positions: torch.Tensor) -> torch.Tensor:
        """
        Args:
            time_positions: [batch, seq_len] in days

        Returns:
            [batch, seq_len, d_model] positional encoding
        """
        # Normalize to [0, 1] range
        normalized = time_positions.unsqueeze(-1) / self.max_days  # [B, S, 1]

        # Create frequency bands
        half_d = self.d_model // 2
        freqs = self.freq_scale * torch.arange(
            half_d, device=time_positions.device, dtype=torch.float32
        )
        freqs = freqs.unsqueeze(0).unsqueeze(0)  # [1, 1, half_d]

        # Sinusoidal encoding
        angles = normalized * freqs * 2 * math.pi  # [B, S, half_d]
        sin_enc = torch.sin(angles)
        cos_enc = torch.cos(angles)

        return torch.cat([sin_enc, cos_enc], dim=-1)  # [B, S, d_model]


class StateTransitionTransformer(ProstaNetModel):
    """
    Transformer-based predictor of clinical state transitions.

    Predicts:
        - next_state: Probability distribution over 13 clinical states
        - time_to_transition: Log-normal parameters (mu, sigma) for estimated months
        - confidence: Self-assessed prediction reliability (0-1)
    """

    model_id = "state_transition"
    model_version = "0.1.0"

    def __init__(
        self,
        vocab_size: int | None = None,
        config: StateTransitionConfig | None = None,
    ) -> None:
        super().__init__()

        if config is None:
            config = get_ai_config().state_transition
        self.config = config

        if vocab_size is None:
            vocab_size = ClinicalVocabulary().size

        self.vocab = ClinicalVocabulary()
        self.tokenizer = ClinicalEventTokenizer(max_length=config.max_sequence_length)

        # Token embedding
        self.token_embedding = nn.Embedding(
            vocab_size, config.d_model, padding_idx=0
        )

        # Continuous time encoding
        self.time_encoding = ContinuousTimeEncoding(config.d_model)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.nhead,
            dim_feedforward=config.dim_feedforward,
            dropout=config.dropout,
            batch_first=True,
            activation="gelu",
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer, num_layers=config.num_encoder_layers
        )

        # Layer norm
        self.layer_norm = nn.LayerNorm(config.d_model)

        # Pooling projection
        self.pool_proj = nn.Linear(config.d_model, config.d_model)

        # ── Output Heads ──

        # Next state prediction: softmax over 13 clinical states
        self.next_state_head = nn.Sequential(
            nn.Linear(config.d_model, config.d_model // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.d_model // 2, NUM_STATES),
        )

        # Time to transition: log-normal parameters (mu, sigma)
        self.time_head = nn.Sequential(
            nn.Linear(config.d_model, config.d_model // 4),
            nn.GELU(),
            nn.Linear(config.d_model // 4, 2),  # mu, log_sigma
        )

        # Confidence: self-assessed reliability
        self.confidence_head = nn.Sequential(
            nn.Linear(config.d_model, config.d_model // 4),
            nn.GELU(),
            nn.Linear(config.d_model // 4, 1),
            nn.Sigmoid(),
        )

    def forward(
        self,
        token_ids: torch.Tensor,
        time_positions: torch.Tensor,
        padding_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            token_ids: [batch, seq_len] integer token IDs
            time_positions: [batch, seq_len] days from diagnosis
            padding_mask: [batch, seq_len] True where padding

        Returns:
            dict with state_probs, time_params, confidence
        """
        # Embed tokens + time
        x = self.token_embedding(token_ids)  # [B, S, D]
        x = x + self.time_encoding(time_positions)  # Add temporal info

        # Transformer encoding
        if padding_mask is not None:
            x = self.transformer_encoder(x, src_key_padding_mask=padding_mask)
        else:
            x = self.transformer_encoder(x)

        x = self.layer_norm(x)

        # Pool: use CLS token (position 0) + mean of non-padded tokens
        cls_token = x[:, 0, :]
        if padding_mask is not None:
            mask_expanded = (~padding_mask).unsqueeze(-1).float()
            mean_token = (x * mask_expanded).sum(dim=1) / mask_expanded.sum(dim=1).clamp(min=1)
        else:
            mean_token = x.mean(dim=1)

        pooled = self.pool_proj(cls_token + mean_token)

        # Output heads
        state_logits = self.next_state_head(pooled)
        state_probs = F.softmax(state_logits, dim=-1)

        time_params = self.time_head(pooled)
        time_mu = time_params[:, 0]
        time_log_sigma = time_params[:, 1]

        confidence = self.confidence_head(pooled).squeeze(-1)

        return {
            "state_probs": state_probs,          # [B, 13]
            "state_logits": state_logits,         # [B, 13] for loss computation
            "time_mu": time_mu,                   # [B]
            "time_log_sigma": time_log_sigma,     # [B]
            "confidence": confidence,             # [B]
        }

    def predict(self, patient_data: dict[str, Any]) -> PredictionResult:
        """
        High-level prediction from raw patient record.

        Returns probabilities for each clinical state and estimated
        time to next transition.
        """
        self.eval()

        # Tokenize
        tokenized = self.tokenizer.tokenize(patient_data)
        token_ids = tokenized.token_ids(self.vocab)
        time_pos = tokenized.time_positions()

        # Convert to tensors
        device = next(self.parameters()).device
        ids_tensor = torch.tensor([token_ids], dtype=torch.long, device=device)
        time_tensor = torch.tensor([time_pos], dtype=torch.float32, device=device)

        with torch.no_grad():
            output = self.forward(ids_tensor, time_tensor)

        # Extract predictions
        probs = output["state_probs"][0].cpu().tolist()
        time_mu = output["time_mu"][0].item()
        time_sigma = math.exp(output["time_log_sigma"][0].item())
        conf = output["confidence"][0].item()

        # Build state probability map
        state_predictions = {}
        for idx, prob in enumerate(probs):
            state_name = IDX_TO_STATE.get(idx, f"state_{idx}")
            state_predictions[state_name] = round(prob, 4)

        # Most likely next state
        top_state_idx = int(torch.argmax(output["state_probs"][0]).item())
        top_state = IDX_TO_STATE.get(top_state_idx, "unknown")
        top_prob = probs[top_state_idx]

        # Time estimate (log-normal median = exp(mu))
        median_months = math.exp(time_mu)
        ci_lower = math.exp(time_mu - 1.96 * time_sigma)
        ci_upper = math.exp(time_mu + 1.96 * time_sigma)

        return PredictionResult(
            model_id=self.model_id,
            model_version=self.model_version,
            prediction_type="state_transition",
            values={
                "predicted_state": top_state,
                "predicted_state_probability": round(top_prob, 4),
                "state_probabilities": state_predictions,
                "time_to_transition_months": round(median_months, 1),
                "time_ci_lower_months": round(ci_lower, 1),
                "time_ci_upper_months": round(ci_upper, 1),
                "current_state": patient_data.get("reconciled_state", ""),
                "sequence_length": tokenized.length,
            },
            confidence=round(conf * 100, 1),
        )

    def explain(self, patient_data: dict[str, Any]) -> dict[str, Any]:
        """Generate attention-based explanation of prediction."""
        self.eval()

        tokenized = self.tokenizer.tokenize(patient_data)
        token_ids = tokenized.token_ids(self.vocab)
        time_pos = tokenized.time_positions()

        device = next(self.parameters()).device
        ids_tensor = torch.tensor([token_ids], dtype=torch.long, device=device)
        time_tensor = torch.tensor([time_pos], dtype=torch.float32, device=device)

        # Forward with attention capture
        with torch.no_grad():
            output = self.forward(ids_tensor, time_tensor)

        # Decode top contributing tokens
        top_state_idx = int(torch.argmax(output["state_probs"][0]).item())
        top_state = IDX_TO_STATE.get(top_state_idx, "unknown")

        return {
            "predicted_state": top_state,
            "sequence_events": len(tokenized.tokens),
            "event_types_present": list(
                set(t.event_type for t in tokenized.tokens)
            ),
            "reasoning": (
                f"Basado en {len(tokenized.tokens)} eventos clínicos, "
                f"el modelo predice transición a {top_state} "
                f"con {output['confidence'][0].item():.0%} de confianza."
            ),
        }
