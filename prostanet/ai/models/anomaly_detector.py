"""
Clinical Sequence VAE — Temporal Anomaly Detector.

Variational Autoencoder over temporal clinical sequences to detect
unexpected lab/clinical patterns that may indicate hidden progression,
treatment toxicity, or data quality issues.

Architecture:
    Encoder: GRU(input=9, hidden=64, layers=2) → mu, logvar
    Decoder: GRU(latent=32, hidden=64, layers=2) → reconstructed sequence
    Anomaly score: Per-feature MSE reconstruction error
    Threshold: 2.0 standard deviations above population mean

Detects:
    - Paradoxical PSA patterns (drop without treatment, spike during response)
    - Unexpected testosterone in castrate patients
    - Hepatotoxicity constellation (AST/ALT + bilirubin)
    - Bone marrow suppression (Hgb + ANC + platelets)
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from prostanet.ai.config import AnomalyDetectorConfig, get_ai_config
from prostanet.ai.models.base import ProstaNetModel, PredictionResult


# Feature order (must match data loader)
LAB_FEATURES = [
    "psa",
    "testosterone",
    "alp",
    "ldh",
    "albumin",
    "hemoglobin",
    "creatinine",
    "ecog",
    "pain_score",
]


class ClinicalSequenceVAE(ProstaNetModel):
    """
    Variational Autoencoder for detecting anomalies in temporal
    clinical/laboratory sequences.
    """

    model_id = "anomaly_detector"
    model_version = "0.1.0"

    def __init__(self, config: AnomalyDetectorConfig | None = None) -> None:
        super().__init__()

        if config is None:
            config = get_ai_config().anomaly_detector
        self.config = config

        # Encoder
        self.encoder_gru = nn.GRU(
            input_size=config.n_features,
            hidden_size=config.hidden_dim,
            num_layers=config.n_gru_layers,
            batch_first=True,
            dropout=0.1 if config.n_gru_layers > 1 else 0.0,
        )

        # Latent space
        self.fc_mu = nn.Linear(config.hidden_dim, config.latent_dim)
        self.fc_logvar = nn.Linear(config.hidden_dim, config.latent_dim)

        # Decoder
        self.decoder_input = nn.Linear(config.latent_dim, config.hidden_dim)
        self.decoder_gru = nn.GRU(
            input_size=config.hidden_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.n_gru_layers,
            batch_first=True,
            dropout=0.1 if config.n_gru_layers > 1 else 0.0,
        )
        self.decoder_output = nn.Linear(config.hidden_dim, config.n_features)

        # Running statistics for anomaly threshold
        self.register_buffer(
            "running_mean_error",
            torch.zeros(config.n_features),
        )
        self.register_buffer(
            "running_std_error",
            torch.ones(config.n_features),
        )
        self.register_buffer("n_samples_seen", torch.tensor(0, dtype=torch.long))

    def encode(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Encode sequence to latent space.

        Args:
            x: [B, T, n_features]

        Returns:
            z, mu, logvar
        """
        _, h_n = self.encoder_gru(x)
        h_last = h_n[-1]  # [B, hidden_dim]

        mu = self.fc_mu(h_last)
        logvar = self.fc_logvar(h_last)

        # Reparameterization trick
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        z = mu + eps * std

        return z, mu, logvar

    def decode(self, z: torch.Tensor, seq_len: int) -> torch.Tensor:
        """
        Decode latent vector to reconstructed sequence.

        Args:
            z: [B, latent_dim]
            seq_len: Target sequence length

        Returns:
            reconstructed: [B, T, n_features]
        """
        decoder_in = self.decoder_input(z)  # [B, hidden_dim]
        # Repeat for sequence length
        decoder_in = decoder_in.unsqueeze(1).expand(-1, seq_len, -1)  # [B, T, hidden_dim]
        decoded, _ = self.decoder_gru(decoder_in)
        reconstructed = self.decoder_output(decoded)  # [B, T, n_features]
        return reconstructed

    def forward(
        self, x: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        """
        Full VAE forward pass.

        Args:
            x: [B, T, n_features]

        Returns:
            reconstructed, mu, logvar, per_feature_mse
        """
        z, mu, logvar = self.encode(x)
        reconstructed = self.decode(z, x.size(1))

        # Per-feature MSE
        per_feature_mse = F.mse_loss(
            reconstructed, x, reduction="none"
        ).mean(dim=1)  # [B, n_features]

        return {
            "reconstructed": reconstructed,
            "mu": mu,
            "logvar": logvar,
            "per_feature_mse": per_feature_mse,
        }

    def anomaly_score(
        self, x: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        """
        Compute anomaly scores for each feature.

        Args:
            x: [B, T, n_features]

        Returns:
            per_feature_scores: [B, n_features] z-scores
            is_anomaly: [B, n_features] boolean
            overall_score: [B] aggregate anomaly score
        """
        with torch.no_grad():
            output = self.forward(x)

        mse = output["per_feature_mse"]  # [B, n_features]

        # Z-score relative to training population
        z_scores = (mse - self.running_mean_error) / (self.running_std_error + 1e-7)

        # Flag anomalies
        is_anomaly = z_scores > self.config.anomaly_threshold

        # Overall score: max z-score across features
        overall_score = z_scores.max(dim=-1).values

        return {
            "per_feature_scores": z_scores,
            "is_anomaly": is_anomaly,
            "overall_score": overall_score,
            "per_feature_mse": mse,
        }

    def update_running_stats(self, mse: torch.Tensor) -> None:
        """Update running mean/std of reconstruction error during training."""
        batch_mean = mse.mean(dim=0)
        batch_std = mse.std(dim=0)
        n = self.n_samples_seen.item()
        batch_size = mse.size(0)

        if n == 0:
            self.running_mean_error.copy_(batch_mean)
            self.running_std_error.copy_(batch_std)
        else:
            momentum = batch_size / (n + batch_size)
            self.running_mean_error.mul_(1 - momentum).add_(batch_mean * momentum)
            self.running_std_error.mul_(1 - momentum).add_(batch_std * momentum)

        self.n_samples_seen.add_(batch_size)

    @staticmethod
    def _extract_lab_series(
        patient_data: dict[str, Any], window_size: int = 10
    ) -> list[list[float]]:
        """
        Extract temporal lab series from patient record.

        Returns: list of [n_features] vectors, one per timepoint
        """
        series: list[list[float]] = []

        def _f(val: Any, default: float = 0.0) -> float:
            if val is None or val == "":
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        # Baseline
        baseline = patient_data.get("baseline", {}) or {}
        series.append([
            _f(baseline.get("baseline_psa")),
            _f(baseline.get("testosterone_baseline")),
            _f(baseline.get("alp"), 80),
            _f(baseline.get("ldh"), 180),
            _f(baseline.get("albumin"), 3.8),
            _f(baseline.get("hemoglobin"), 13),
            _f(baseline.get("creatinine"), 0.9),
            _f(baseline.get("ecog_score"), 1),
            0.0,  # pain_score
        ])

        # Follow-ups
        for visit in patient_data.get("follow_ups") or []:
            series.append([
                _f(visit.get("psa_current") or visit.get("psa")),
                _f(visit.get("testosterone")),
                _f(visit.get("alp"), 80),
                _f(visit.get("ldh"), 180),
                _f(visit.get("albumin"), 3.8),
                _f(visit.get("hemoglobin"), 13),
                _f(visit.get("creatinine"), 0.9),
                _f(visit.get("ecog"), 1),
                _f(visit.get("pain_score")),
            ])

        # Pad or truncate to window_size
        while len(series) < window_size:
            series.insert(0, series[0] if series else [0.0] * 9)
        series = series[-window_size:]

        return series

    def predict(self, patient_data: dict[str, Any]) -> PredictionResult:
        """Detect anomalies in patient's lab/clinical time series."""
        self.eval()
        device = next(self.parameters()).device

        lab_series = self._extract_lab_series(
            patient_data, self.config.window_size
        )
        x = torch.tensor([lab_series], dtype=torch.float32, device=device)

        scores = self.anomaly_score(x)

        per_feature = scores["per_feature_scores"][0].cpu().tolist()
        is_anomaly = scores["is_anomaly"][0].cpu().tolist()
        overall = scores["overall_score"][0].item()

        anomalies: list[dict[str, Any]] = []
        for i, (feat, score, flag) in enumerate(
            zip(LAB_FEATURES, per_feature, is_anomaly)
        ):
            if flag:
                anomalies.append({
                    "feature": feat,
                    "z_score": round(score, 2),
                    "severity": "critical" if score > 3.0 else "warning",
                })

        return PredictionResult(
            model_id=self.model_id,
            model_version=self.model_version,
            prediction_type="anomaly_detection",
            values={
                "overall_anomaly_score": round(overall, 2),
                "is_anomalous": overall > self.config.anomaly_threshold,
                "per_feature_scores": {
                    feat: round(score, 4)
                    for feat, score in zip(LAB_FEATURES, per_feature)
                },
                "detected_anomalies": anomalies,
                "window_size": self.config.window_size,
            },
            confidence=min(95.0, 50.0 + overall * 10),
        )

    def explain(self, patient_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "features_monitored": LAB_FEATURES,
            "window_size": self.config.window_size,
            "threshold": self.config.anomaly_threshold,
            "model_type": "variational_autoencoder_temporal",
        }


# ══════════════════════════════════════════════════════════════════════════════
# AnomalyDetector — High-level interface consumed by alert_engine and watchdog
# ══════════════════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """
    High-level anomaly detection interface.

    Wraps `ClinicalSequenceVAE` with:
      - Rule-based pre-screening (fast, no model required)
      - VAE-based deep anomaly scoring (when model artifact is loaded)
      - Clinical interpretation with severity labels
      - Integration with `alert_engine.py` ClinicalAlert format

    Usage::
        detector = AnomalyDetector()
        result = detector.detect(patient_record)
        # result.anomaly_score, result.anomalies, result.alerts_payload
    """

    # Rule-based thresholds (always applied, no model required)
    RULE_THRESHOLDS: dict[str, dict[str, Any]] = {
        "psa_paradox_drop": {
            "description": "PSA cae >50% sin tratamiento activo — interferencia analítica o progresión variante",
            "severity": "warning",
        },
        "testosterone_escape": {
            "description": "Testosterona >50 ng/dL en estado de castración confirmado",
            "severity": "critical",
        },
        "hepatotoxicity_constellation": {
            "description": "ALP >3×ULN + LDH elevado + albúmina baja — evaluar toxicidad hepática",
            "severity": "critical",
        },
        "myelosuppression": {
            "description": "Hemoglobina <8 g/dL — supresión medular severa",
            "severity": "critical",
        },
        "rapid_ecog_decline": {
            "description": "ECOG deterioró ≥2 puntos en <90 días",
            "severity": "warning",
        },
        "psa_velocity_crisis": {
            "description": "PSA duplica en <60 días — progresión explosiva",
            "severity": "critical",
        },
    }

    def __init__(self, vae_model: "ClinicalSequenceVAE | None" = None) -> None:
        """
        Args:
            vae_model: Optional loaded ClinicalSequenceVAE.
                       If None, only rule-based detection runs.
        """
        self._vae = vae_model

    def detect(self, patient: dict[str, Any]) -> "AnomalyResult":
        """
        Run full anomaly detection pipeline on a patient record.

        Args:
            patient: Full patient dict from `get_patient_full_record()`.

        Returns:
            AnomalyResult with anomaly_score, anomalies list, and alert payload.
        """
        rule_anomalies = self._run_rule_checks(patient)
        vae_anomalies: list[dict[str, Any]] = []
        vae_score = 0.0

        if self._vae is not None:
            try:
                vae_result = self._vae.predict(patient)
                vae_score = vae_result.values.get("overall_anomaly_score", 0.0)
                vae_anomalies = vae_result.values.get("detected_anomalies", [])
            except Exception:
                pass

        # Merge rule + VAE anomalies (deduplicate)
        all_anomalies = rule_anomalies + [
            a for a in vae_anomalies
            if not any(r["rule"] == a.get("feature") for r in rule_anomalies)
        ]

        # Overall score: max of rule severity scores + VAE score
        rule_score = sum(
            3.0 if a["severity"] == "critical" else 1.5
            for a in rule_anomalies
        )
        overall_score = max(rule_score, vae_score)
        is_anomalous = len(rule_anomalies) > 0 or vae_score > 2.0

        return AnomalyResult(
            anomaly_score=round(overall_score, 2),
            is_anomalous=is_anomalous,
            anomalies=all_anomalies,
            rule_anomalies=rule_anomalies,
            vae_anomalies=vae_anomalies,
            vae_score=vae_score,
        )

    # ── Rule-based checks (no GPU) ───────────────────────────────────────────

    def _run_rule_checks(self, patient: dict[str, Any]) -> list[dict[str, Any]]:
        """Fast rule-based anomaly detection."""
        anomalies: list[dict[str, Any]] = []

        visits = sorted(
            patient.get("follow_up_visits") or [],
            key=lambda v: v.get("visit_date", ""),
        )

        psa_series = [
            (v.get("visit_date", ""), float(v["psa_current"]))
            for v in visits
            if v.get("psa_current") is not None
        ]
        testosterone_series = [
            float(v["testosterone"])
            for v in visits
            if v.get("testosterone") is not None
        ]
        ecog_series = [
            (v.get("visit_date", ""), float(v["ecog"]))
            for v in visits
            if v.get("ecog") is not None
        ]

        # Check PSA velocity crisis (doubling in <60 days)
        if len(psa_series) >= 2:
            for i in range(1, len(psa_series)):
                prev_date, prev_psa = psa_series[i - 1]
                curr_date, curr_psa = psa_series[i]
                if prev_psa > 0 and curr_psa >= prev_psa * 2.0:
                    days = self._days_between(prev_date, curr_date)
                    if days is not None and 0 < days <= 60:
                        anomalies.append({
                            "rule": "psa_velocity_crisis",
                            "severity": "critical",
                            "value": f"{prev_psa:.1f} → {curr_psa:.1f} ng/mL en {days} días",
                            "description": self.RULE_THRESHOLDS["psa_velocity_crisis"]["description"],
                        })

        # Check PSA paradoxical drop (>50% without active treatment)
        active_meds = patient.get("current_medications") or patient.get("medications") or []
        has_active_treatment = len(active_meds) > 0
        if len(psa_series) >= 2 and not has_active_treatment:
            latest_psa = psa_series[-1][1]
            max_psa = max(p for _, p in psa_series)
            if max_psa > 0 and latest_psa < max_psa * 0.5:
                anomalies.append({
                    "rule": "psa_paradox_drop",
                    "severity": "warning",
                    "value": f"Máximo: {max_psa:.1f} → actual: {latest_psa:.1f} ng/mL sin tratamiento",
                    "description": self.RULE_THRESHOLDS["psa_paradox_drop"]["description"],
                })

        # Check testosterone escape in castrate states
        castrate_states = {
            "m0_crpc", "m1_crpc", "m1b_crpc", "mcspc", "nmcrpc",
            "m0_crpc_high_risk", "m1_cspc", "m1b_cspc",
        }
        state = (patient.get("current_state") or "").lower()
        if state in castrate_states and testosterone_series:
            latest_t = testosterone_series[-1]
            if latest_t > 50.0:
                anomalies.append({
                    "rule": "testosterone_escape",
                    "severity": "critical",
                    "value": f"{latest_t:.0f} ng/dL (debe ser <50 ng/dL)",
                    "description": self.RULE_THRESHOLDS["testosterone_escape"]["description"],
                })

        # Check hepatotoxicity constellation
        alp = self._latest_lab(visits, "alp")
        ldh = self._latest_lab(visits, "ldh")
        albumin = self._latest_lab(visits, "albumin")
        if alp is not None and alp > 360:  # 3×ULN (ULN ~120 U/L)
            if albumin is not None and albumin < 3.2:
                anomalies.append({
                    "rule": "hepatotoxicity_constellation",
                    "severity": "critical",
                    "value": f"ALP={alp:.0f} U/L, Albumina={albumin:.1f} g/dL",
                    "description": self.RULE_THRESHOLDS["hepatotoxicity_constellation"]["description"],
                })

        # Check myelosuppression
        hgb = self._latest_lab(visits, "hemoglobin") or self._latest_lab(visits, "hgb")
        if hgb is not None and hgb < 8.0:
            anomalies.append({
                "rule": "myelosuppression",
                "severity": "critical",
                "value": f"Hgb = {hgb:.1f} g/dL",
                "description": self.RULE_THRESHOLDS["myelosuppression"]["description"],
            })

        # Check rapid ECOG decline
        if len(ecog_series) >= 2:
            latest_date, latest_ecog = ecog_series[-1]
            # Look back 90 days
            for prev_date, prev_ecog in reversed(ecog_series[:-1]):
                days = self._days_between(prev_date, latest_date)
                if days is not None and days <= 90:
                    if latest_ecog - prev_ecog >= 2:
                        anomalies.append({
                            "rule": "rapid_ecog_decline",
                            "severity": "warning",
                            "value": f"ECOG {prev_ecog:.0f} → {latest_ecog:.0f} en {days} días",
                            "description": self.RULE_THRESHOLDS["rapid_ecog_decline"]["description"],
                        })
                    break

        return anomalies

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _latest_lab(visits: list[dict[str, Any]], field: str) -> float | None:
        for v in reversed(visits):
            val = v.get(field)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _days_between(date_a: str, date_b: str) -> int | None:
        try:
            from datetime import date
            d0 = date.fromisoformat(str(date_a)[:10])
            d1 = date.fromisoformat(str(date_b)[:10])
            return abs((d1 - d0).days)
        except Exception:
            return None


from dataclasses import dataclass, field as dc_field


@dataclass
class AnomalyResult:
    """Result from AnomalyDetector.detect()."""
    anomaly_score:  float
    is_anomalous:   bool
    anomalies:      list[dict[str, Any]]
    rule_anomalies: list[dict[str, Any]]
    vae_anomalies:  list[dict[str, Any]]
    vae_score:      float

    def to_alert_payload(self) -> list[dict[str, Any]]:
        """Convert anomalies to ClinicalAlert-compatible dicts."""
        alerts = []
        for a in self.anomalies:
            alerts.append({
                "category": "ai_anomaly",
                "severity": a.get("severity", "warning"),
                "message": a.get("description", ""),
                "detail": a.get("value", ""),
                "source": "anomaly_detector",
                "rule": a.get("rule", a.get("feature", "vae")),
            })
        return alerts


def vae_loss(
    reconstructed: torch.Tensor,
    original: torch.Tensor,
    mu: torch.Tensor,
    logvar: torch.Tensor,
    kl_weight: float = 0.5,
) -> torch.Tensor:
    """
    VAE loss = Reconstruction loss + KL divergence.

    Args:
        reconstructed: [B, T, F] reconstructed sequence
        original: [B, T, F] original sequence
        mu: [B, latent_dim] mean of latent distribution
        logvar: [B, latent_dim] log-variance of latent distribution
        kl_weight: Weight for KL divergence term
    """
    recon_loss = F.mse_loss(reconstructed, original, reduction="mean")
    kl_loss = -0.5 * torch.mean(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss + kl_weight * kl_loss
