"""
Treatment Response Predictor — Multi-task Neural Network.

Predicts treatment outcomes for each candidate regimen:
    - PSA response probability (PSA50, PSA90)
    - rPFS estimate (log-normal months)
    - Toxicity risk profile (8 domains)
    - Response category (CR/PR/SD/PD)

Architecture:
    Patient encoder: MLP [128, 256] with BatchNorm + ResidualBlock
    Treatment encoder: Embedding(50, 64) → Linear(64, 128)
    Prior treatment history: GRU over regimen sequence
    Fusion: Concatenation → MLP [256, 128]
    Output heads: PSA response, rPFS, toxicity, response category
"""

from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from prostanet.ai.config import TreatmentResponseConfig, get_ai_config
from prostanet.ai.models.base import ProstaNetModel, PredictionResult


# ── Feature extraction constants ─────────────────────────────────────────

PATIENT_NUMERIC_FEATURES = [
    "age",
    "psa_current",
    "ecog_score",
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
    "testosterone",
    "creatinine",
    "metastasis_count",
    "line_of_therapy",
    "bmi_current",
    "cci",
]

PATIENT_BINARY_FEATURES = [
    "hrr_positive",
    "brca2_positive",
    "msi_high",
    "tmb_high",
    "arv7_positive",
    "nepc_suspicion",
    "psma_positive",
    "prior_prostatectomy",
    "prior_radiation",
    "prior_docetaxel",
    "visceral_metastasis",
    "liver_metastasis",
    "bone_metastasis",
]

TOTAL_PATIENT_FEATURES = len(PATIENT_NUMERIC_FEATURES) + len(PATIENT_BINARY_FEATURES)

TOXICITY_DOMAINS = [
    "hematologic",
    "hepatic",
    "cardiovascular",
    "fatigue",
    "gastrointestinal",
    "neuropathy",
    "dermatologic",
    "endocrine",
]


class ResidualBlock(nn.Module):
    """Residual MLP block matching existing prostate_cancer_model.py pattern."""

    def __init__(self, dim: int, dropout: float = 0.25) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim),
        )
        self.activation = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.activation(x + self.block(x))


class TreatmentResponsePredictor(ProstaNetModel):
    """
    Multi-task model predicting treatment outcomes.

    For each candidate treatment, predicts PSA response, progression-free
    survival, toxicity risks, and RECIST-like response category.
    """

    model_id = "treatment_response"
    model_version = "0.1.0"

    def __init__(self, config: TreatmentResponseConfig | None = None) -> None:
        super().__init__()

        if config is None:
            config = get_ai_config().treatment_response
        self.config = config

        patient_dim = TOTAL_PATIENT_FEATURES

        # Patient encoder
        layers: list[nn.Module] = []
        in_dim = patient_dim
        for out_dim in config.patient_encoder_dims:
            layers.extend([
                nn.Linear(in_dim, out_dim),
                nn.BatchNorm1d(out_dim),
                nn.GELU(),
                nn.Dropout(config.dropout),
            ])
            in_dim = out_dim
        self.patient_encoder = nn.Sequential(*layers)
        patient_encoded_dim = config.patient_encoder_dims[-1]

        # Residual refinement
        self.patient_residual = ResidualBlock(patient_encoded_dim, config.dropout)

        # Treatment embedding
        self.treatment_embedding = nn.Embedding(
            config.num_regimens, config.treatment_embed_dim
        )
        self.treatment_proj = nn.Linear(config.treatment_embed_dim, 128)

        # Prior treatment history encoder (GRU)
        self.history_gru = nn.GRU(
            input_size=config.treatment_embed_dim,
            hidden_size=64,
            num_layers=1,
            batch_first=True,
        )
        self.history_proj = nn.Linear(64, 64)

        # Fusion
        fusion_input_dim = patient_encoded_dim + 128 + 64
        fusion_layers: list[nn.Module] = []
        in_dim = fusion_input_dim
        for out_dim in config.fusion_dims:
            fusion_layers.extend([
                nn.Linear(in_dim, out_dim),
                nn.BatchNorm1d(out_dim),
                nn.GELU(),
                nn.Dropout(config.dropout),
            ])
            in_dim = out_dim
        self.fusion = nn.Sequential(*fusion_layers)
        fusion_out = config.fusion_dims[-1]

        # ── Output Heads ──

        # PSA response: P(PSA50), P(PSA90)
        self.psa_response_head = nn.Sequential(
            nn.Linear(fusion_out, 32),
            nn.GELU(),
            nn.Linear(32, 2),
            nn.Sigmoid(),
        )

        # rPFS estimate: log-normal (mu, sigma)
        self.rpfs_head = nn.Sequential(
            nn.Linear(fusion_out, 32),
            nn.GELU(),
            nn.Linear(32, 2),
        )

        # Toxicity profile: multi-label sigmoid for 8 domains
        self.toxicity_head = nn.Sequential(
            nn.Linear(fusion_out, 64),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(64, config.num_toxicity_domains),
            nn.Sigmoid(),
        )

        # Response category: CR/PR/SD/PD softmax
        self.response_head = nn.Sequential(
            nn.Linear(fusion_out, 32),
            nn.GELU(),
            nn.Linear(32, 4),
        )

    def forward(
        self,
        patient_features: torch.Tensor,
        treatment_id: torch.Tensor,
        prior_treatment_ids: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            patient_features: [B, TOTAL_PATIENT_FEATURES]
            treatment_id: [B] integer regimen ID
            prior_treatment_ids: [B, max_prior_treatments] integer IDs (0-padded)
        """
        # Encode patient
        p = self.patient_encoder(patient_features)
        p = self.patient_residual(p)

        # Encode proposed treatment
        t = self.treatment_embedding(treatment_id)
        t = self.treatment_proj(t)

        # Encode treatment history
        if prior_treatment_ids is not None and prior_treatment_ids.shape[1] > 0:
            h_emb = self.treatment_embedding(prior_treatment_ids)
            _, h_final = self.history_gru(h_emb)
            h = self.history_proj(h_final.squeeze(0))
        else:
            h = torch.zeros(patient_features.size(0), 64, device=patient_features.device)

        # Fuse
        fused = self.fusion(torch.cat([p, t, h], dim=-1))

        return {
            "psa_response": self.psa_response_head(fused),       # [B, 2]: P(PSA50), P(PSA90)
            "rpfs_params": self.rpfs_head(fused),                 # [B, 2]: mu, log_sigma
            "toxicity": self.toxicity_head(fused),                # [B, 8]
            "response_logits": self.response_head(fused),         # [B, 4]
            "response_probs": F.softmax(self.response_head(fused), dim=-1),
        }

    @staticmethod
    def _extract_patient_features(patient_data: dict[str, Any]) -> list[float]:
        """Extract fixed-size feature vector from patient record."""
        features: list[float] = []

        baseline = patient_data.get("baseline", {}) or {}
        identity = patient_data.get("identity", {}) or {}
        genomic = patient_data.get("genomic_profile", {}) or {}

        def _f(val: Any, default: float = 0.0) -> float:
            if val is None or val == "":
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        # Numeric features
        features.append(_f(identity.get("age") or baseline.get("age"), 65))
        features.append(_f(baseline.get("baseline_psa") or baseline.get("psa_current"), 10))
        features.append(_f(baseline.get("ecog_score"), 1))
        features.append(_f(baseline.get("gleason_primary"), 3))
        features.append(_f(baseline.get("gleason_secondary"), 3))
        features.append(_f(baseline.get("isup_grade"), 1))
        features.append(_f(baseline.get("hemoglobin"), 13))
        features.append(_f(baseline.get("alp"), 80))
        features.append(_f(baseline.get("ldh"), 180))
        features.append(_f(baseline.get("albumin"), 3.8))
        features.append(_f(baseline.get("testosterone_baseline"), 300))
        features.append(_f(baseline.get("creatinine"), 0.9))
        features.append(_f(baseline.get("metastasis_count"), 0))
        features.append(_f(baseline.get("line_of_therapy"), 1))
        features.append(_f(baseline.get("bmi_current"), 25))
        features.append(_f(baseline.get("cci"), 0))

        # Binary features
        features.append(1.0 if genomic.get("hrr_status") == "positive" else 0.0)
        features.append(1.0 if genomic.get("brca2") == "positive" else 0.0)
        features.append(1.0 if genomic.get("msi_status") == "high" else 0.0)
        features.append(1.0 if _f(genomic.get("tmb")) >= 10 else 0.0)
        features.append(1.0 if genomic.get("ar_v7") == "positive" else 0.0)
        features.append(1.0 if baseline.get("nepc_suspicion") else 0.0)
        features.append(1.0 if baseline.get("psma_positive") else 0.0)
        features.append(1.0 if baseline.get("prior_prostatectomy") else 0.0)
        features.append(1.0 if baseline.get("prior_radiation") else 0.0)
        features.append(1.0 if baseline.get("prior_docetaxel") else 0.0)
        features.append(1.0 if str(baseline.get("metastasis_site", "")).lower() == "visceral" else 0.0)
        features.append(1.0 if str(baseline.get("metastasis_site", "")).lower() == "liver" else 0.0)
        features.append(1.0 if str(baseline.get("metastasis_site", "")).lower() in ("bone", "m1b") else 0.0)

        return features

    def predict(self, patient_data: dict[str, Any], regimen_id: int = 0) -> PredictionResult:
        """Predict treatment outcomes for a given patient and regimen."""
        self.eval()
        device = next(self.parameters()).device

        features = self._extract_patient_features(patient_data)
        feat_tensor = torch.tensor([features], dtype=torch.float32, device=device)
        reg_tensor = torch.tensor([regimen_id], dtype=torch.long, device=device)

        with torch.no_grad():
            output = self.forward(feat_tensor, reg_tensor)

        psa = output["psa_response"][0].cpu().tolist()
        rpfs_mu = output["rpfs_params"][0, 0].item()
        rpfs_sigma = math.exp(output["rpfs_params"][0, 1].item())
        tox = output["toxicity"][0].cpu().tolist()
        resp = output["response_probs"][0].cpu().tolist()

        categories = ["CR", "PR", "SD", "PD"]
        best_response_idx = int(torch.argmax(output["response_probs"][0]).item())

        return PredictionResult(
            model_id=self.model_id,
            model_version=self.model_version,
            prediction_type="treatment_response",
            values={
                "psa50_probability": round(psa[0], 4),
                "psa90_probability": round(psa[1], 4),
                "rpfs_median_months": round(math.exp(rpfs_mu), 1),
                "rpfs_ci_lower": round(math.exp(rpfs_mu - 1.96 * rpfs_sigma), 1),
                "rpfs_ci_upper": round(math.exp(rpfs_mu + 1.96 * rpfs_sigma), 1),
                "toxicity_risks": {
                    domain: round(risk, 4)
                    for domain, risk in zip(TOXICITY_DOMAINS, tox)
                },
                "response_probabilities": {
                    cat: round(p, 4) for cat, p in zip(categories, resp)
                },
                "best_expected_response": categories[best_response_idx],
            },
            confidence=round(max(resp) * 100, 1),
        )

    def explain(self, patient_data: dict[str, Any]) -> dict[str, Any]:
        features = self._extract_patient_features(patient_data)
        all_names = PATIENT_NUMERIC_FEATURES + PATIENT_BINARY_FEATURES
        return {
            "input_features": {
                name: val for name, val in zip(all_names, features)
            },
            "feature_count": len(features),
            "model_type": "multi_task_treatment_response",
        }
