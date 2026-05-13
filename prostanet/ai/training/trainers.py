"""
Training Loops — model-specific training procedures.

Each trainer follows the same pattern:
  1. Build dataset from records
  2. Split train/validation
  3. Train with early stopping
  4. Evaluate on validation set
  5. Save best checkpoint
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("output/models")


def train_state_transition(
    records: list[dict[str, Any]],
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 1e-4,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Train the State Transition Transformer."""
    from prostanet.ai.config import AIConfig, StateTransitionConfig
    from prostanet.ai.models.state_transition import StateTransitionTransformer
    from prostanet.ai.training.data_loaders import StateTransitionDataset

    cfg = StateTransitionConfig()
    ai_cfg = AIConfig()
    device = torch.device(ai_cfg.device)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR) / "state_transition"
    output_path.mkdir(parents=True, exist_ok=True)

    # Dataset
    # EPIC 16: bugfix — StateTransitionConfig declara `max_sequence_length`
    # (no `max_seq_length`). Naming inconsistency pre-EPIC 16 que bloqueaba
    # el training run completo.
    dataset = StateTransitionDataset(records, max_length=cfg.max_sequence_length)
    if len(dataset) < 10:
        return {"error": "Insufficient training data", "samples": len(dataset)}

    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    # Model
    # EPIC 16 bugfix: StateTransitionTransformer signature is (vocab_size, config).
    # Passing cfg positionally falls into vocab_size → TypeError empty().
    # Use kwarg to disambiguate.
    model = StateTransitionTransformer(config=cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    state_criterion = nn.CrossEntropyLoss()
    time_criterion = nn.GaussianNLLLoss()

    best_val_loss = float("inf")
    history: list[dict[str, float]] = []

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for batch in train_loader:
            token_ids = batch["token_ids"].to(device)
            time_pos = batch["time_positions"].to(device)
            mask = batch["attention_mask"].to(device)
            target_state = batch["target_state"].to(device)

            optimizer.zero_grad(set_to_none=True)
            # EPIC 16 bugfix: StateTransitionTransformer.forward returns dict
            # with keys {state_logits, state_probs, time_mu, time_log_sigma,
            # confidence}. Pre-EPIC 16 trainer unpacked a 3-tuple → ValueError.
            output = model(token_ids, time_pos, mask)
            state_logits = output["state_logits"]
            mu = output["time_mu"]
            log_sigma = output["time_log_sigma"]

            loss_state = state_criterion(state_logits, target_state)
            # Time loss with log-normal parameters
            target_time = batch["time_to_transition"].to(device)
            var = torch.exp(2 * log_sigma)
            loss_time = time_criterion(mu, target_time, var)

            loss = loss_state + 0.5 * loss_time
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()

        scheduler.step()

        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for batch in val_loader:
                token_ids = batch["token_ids"].to(device)
                time_pos = batch["time_positions"].to(device)
                mask = batch["attention_mask"].to(device)
                target_state = batch["target_state"].to(device)

                output = model(token_ids, time_pos, mask)
                state_logits = output["state_logits"]
                loss_state = state_criterion(state_logits, target_state)
                val_loss += loss_state.item()

                preds = state_logits.argmax(dim=-1)
                correct += (preds == target_state).sum().item()
                total += target_state.size(0)

        avg_train = train_loss / max(1, len(train_loader))
        avg_val = val_loss / max(1, len(val_loader))
        accuracy = correct / max(1, total)

        history.append({
            "epoch": epoch + 1,
            "train_loss": round(avg_train, 4),
            "val_loss": round(avg_val, 4),
            "val_accuracy": round(accuracy, 4),
        })

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            model.save(str(output_path / "best.pt"))

        if (epoch + 1) % 10 == 0:
            logger.info(
                "Epoch %d/%d — train=%.4f val=%.4f acc=%.2f%%",
                epoch + 1, epochs, avg_train, avg_val, accuracy * 100,
            )

    return {
        "model_path": str(output_path / "best.pt"),
        "epochs": epochs,
        "samples": len(dataset),
        "best_val_loss": round(best_val_loss, 4),
        "final_accuracy": history[-1]["val_accuracy"] if history else 0,
        "history": history,
    }


def train_treatment_response(
    records: list[dict[str, Any]],
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 1e-4,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Train the Treatment Response Predictor."""
    from prostanet.ai.config import TreatmentResponseConfig
    from prostanet.ai.models.treatment_response import TreatmentResponsePredictor
    from prostanet.ai.training.data_loaders import TreatmentResponseDataset
    from prostanet.ai.config import AIConfig

    cfg = TreatmentResponseConfig()
    device = torch.device(AIConfig().device)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR) / "treatment_response"
    output_path.mkdir(parents=True, exist_ok=True)

    dataset = TreatmentResponseDataset(records)
    if len(dataset) < 10:
        return {"error": "Insufficient training data", "samples": len(dataset)}

    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    # EPIC 16 bugfix: drop_last=True evita BatchNorm crash con batch_size=1
    # cuando el último batch tiene un solo sample. Per pytorch-patterns
    # DataLoader idiom: "drop_last=True para consistencia con BatchNorm".
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    model = TreatmentResponsePredictor(cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)

    bce = nn.BCELoss()
    ce = nn.CrossEntropyLoss()
    mse = nn.MSELoss()

    best_val = float("inf")

    for epoch in range(epochs):
        model.train()
        for batch in train_loader:
            features = batch["patient_features"].to(device)
            regimen = batch["regimen_id"].to(device)

            optimizer.zero_grad(set_to_none=True)
            # EPIC 16 bugfix: TreatmentResponsePredictor.forward returns dict
            # with keys {psa_response, rpfs_params, toxicity, response_logits,
            # response_probs}. Pre-EPIC 16 unpacking 4-tuple → ValueError 5 got.
            output = model(features, regimen)
            psa_resp = output["psa_response"]
            resp_logits = output["response_logits"]

            loss_psa = bce(psa_resp[:, 0], batch["psa50"].to(device))
            loss_resp = ce(resp_logits, batch["response_category"].to(device))
            loss = loss_psa + loss_resp
            loss.backward()
            optimizer.step()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                features = batch["patient_features"].to(device)
                regimen = batch["regimen_id"].to(device)
                output = model(features, regimen)
                psa_resp = output["psa_response"]
                loss_psa = bce(psa_resp[:, 0], batch["psa50"].to(device))
                val_loss += loss_psa.item()

        avg_val = val_loss / max(1, len(val_loader))
        if avg_val < best_val:
            best_val = avg_val
            model.save(str(output_path / "best.pt"))

    return {
        "model_path": str(output_path / "best.pt"),
        "epochs": epochs,
        "samples": len(dataset),
        "best_val_loss": round(best_val, 4),
    }


def train_deep_surv(
    records: list[dict[str, Any]],
    endpoint: str = "OS",
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 1e-3,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Train DeepSurv for a specific survival endpoint."""
    from prostanet.ai.config import DeepSurvConfig, AIConfig
    from prostanet.ai.models.deep_surv import DeepSurvNet, cox_ph_loss
    from prostanet.ai.training.data_loaders import SurvivalDataset

    cfg = DeepSurvConfig()
    device = torch.device(AIConfig().device)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR) / f"deep_surv_{endpoint}"
    output_path.mkdir(parents=True, exist_ok=True)

    dataset = SurvivalDataset(records, endpoint=endpoint)
    if len(dataset) < 10:
        return {"error": "Insufficient data", "samples": len(dataset)}

    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    # EPIC 16 bugfix: drop_last=True por consistencia BatchNorm + pytorch-patterns.
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)

    # EPIC 16 bugfix: DeepSurvNet signature is (input_dim, config).
    # Use kwarg config=cfg to avoid positional collision with input_dim.
    model = DeepSurvNet(config=cfg).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    best_loss = float("inf")

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        for batch in train_loader:
            features = batch["features"].to(device)
            time = batch["time"].to(device)
            event = batch["event"].to(device)

            optimizer.zero_grad(set_to_none=True)
            # EPIC 17a bugfix: risk_network es la representación compartida
            # (size hidden_dim=32), NO el log-hazard escalar. Sin pasar por
            # endpoint_heads, la "log_hr" era un embedding 32-dim. cox_ph_loss
            # broadcasts mal cuando batch_size==32 (mismo dim accidental) y
            # produce loss = ~80 sin gradiente útil hacia la cabeza endpoint.
            # Fix: usar model.forward() que aplica endpoint_heads.
            output = model(features, endpoint=endpoint)
            log_hr = output["log_hazard_ratio"].squeeze(-1)
            loss = cox_ph_loss(log_hr, time, event)
            if torch.isnan(loss):
                continue
            # EPIC 17 defense-in-depth: skip si loss no participa en autograd
            # (puede ocurrir si batch tiene 0 events y cox_ph_loss devolvió
            # un cero sin grad_fn pese al fix de deep_surv.py).
            if loss.grad_fn is None and not loss.requires_grad:
                continue
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            epoch_loss += loss.item()

        avg = epoch_loss / max(1, len(train_loader))
        if avg < best_loss:
            best_loss = avg
            model.save(str(output_path / "best.pt"))

    return {
        "model_path": str(output_path / "best.pt"),
        "endpoint": endpoint,
        "epochs": epochs,
        "samples": len(dataset),
        "best_loss": round(best_loss, 4),
    }


def train_anomaly_detector(
    records: list[dict[str, Any]],
    *,
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 1e-3,
    kl_weight: float = 0.5,
    window_size: int = 10,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """
    Train the ClinicalSequenceVAE anomaly detector on patient lab sequences.

    The VAE learns the normal distribution of temporal lab/clinical sequences
    so that anomalous patterns (unexpected PSA drops, testosterone escape,
    hepatotoxicity constellations) produce high reconstruction errors at inference.

    Args:
        records:     List of patient dicts from tracking_db
        epochs:      Training epochs
        batch_size:  Batch size
        lr:          Learning rate
        kl_weight:   KL divergence weight in VAE loss (0.1–1.0)
        window_size: Temporal window length (number of visits)
        output_dir:  Output directory for model artifacts

    Returns:
        Training result dict with model_path, epochs, best_loss, samples,
        anomaly_threshold (population mean + 2σ), running stats.
    """
    from prostanet.ai.models.anomaly_detector import ClinicalSequenceVAE, vae_loss, LAB_FEATURES
    from prostanet.ai.config import AnomalyDetectorConfig, AIConfig

    cfg = AnomalyDetectorConfig(window_size=window_size)
    device = torch.device(AIConfig().device)
    output_path = Path(output_dir or DEFAULT_OUTPUT_DIR) / "anomaly_detector"
    output_path.mkdir(parents=True, exist_ok=True)

    # Build temporal sequences dataset
    sequences = _build_lab_sequences(records, window_size=window_size)
    if len(sequences) < 10:
        return {"error": "Insufficient data for VAE training", "samples": len(sequences)}

    x_tensor = torch.tensor(sequences, dtype=torch.float32)

    # Normalize per feature (z-score)
    feat_mean = x_tensor.mean(dim=(0, 1))  # [n_features]
    feat_std  = x_tensor.std(dim=(0, 1)).clamp(min=1e-6)
    x_norm = (x_tensor - feat_mean) / feat_std

    train_size = int(0.85 * len(x_norm))
    val_size = len(x_norm) - train_size
    train_ds, val_ds = torch.utils.data.random_split(
        torch.utils.data.TensorDataset(x_norm),
        [train_size, val_size],
    )
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=False)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False)

    model = ClinicalSequenceVAE(cfg).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)

    best_val_loss = float("inf")
    train_losses: list[float] = []

    for epoch in range(epochs):
        # Training
        model.train()
        epoch_loss = 0.0
        for (batch_x,) in train_loader:
            batch_x = batch_x.to(device)
            optimizer.zero_grad(set_to_none=True)
            output = model(batch_x)
            loss = vae_loss(
                output["reconstructed"], batch_x,
                output["mu"], output["logvar"],
                kl_weight=kl_weight,
            )
            if torch.isnan(loss):
                continue
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            epoch_loss += loss.item()

            # Update running stats for anomaly thresholding
            model.update_running_stats(output["per_feature_mse"].detach())

        scheduler.step()
        avg_train = epoch_loss / max(1, len(train_loader))
        train_losses.append(round(avg_train, 4))

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for (batch_x,) in val_loader:
                batch_x = batch_x.to(device)
                output = model(batch_x)
                val_loss += vae_loss(
                    output["reconstructed"], batch_x,
                    output["mu"], output["logvar"],
                    kl_weight=kl_weight,
                ).item()
        avg_val = val_loss / max(1, len(val_loader))

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            model.save(str(output_path / "best.pt"))

        if epoch % 10 == 0:
            logger.info(
                "VAE epoch %d/%d — train: %.4f, val: %.4f",
                epoch + 1, epochs, avg_train, avg_val,
            )

    # Compute anomaly thresholds from validation set
    model.eval()
    all_mse: list[torch.Tensor] = []
    with torch.no_grad():
        for (batch_x,) in val_loader:
            batch_x = batch_x.to(device)
            out = model(batch_x)
            all_mse.append(out["per_feature_mse"].cpu())
    if all_mse:
        mse_cat = torch.cat(all_mse, dim=0)
        threshold_per_feature = (
            mse_cat.mean(dim=0) + 2.0 * mse_cat.std(dim=0)
        ).tolist()
    else:
        threshold_per_feature = [2.0] * len(LAB_FEATURES)

    # Save normalization stats alongside model
    stats_path = output_path / "normalization_stats.pt"
    torch.save(
        {"feat_mean": feat_mean, "feat_std": feat_std},
        str(stats_path),
    )

    return {
        "model_path": str(output_path / "best.pt"),
        "normalization_stats_path": str(stats_path),
        "epochs": epochs,
        "samples": len(sequences),
        "best_val_loss": round(best_val_loss, 4),
        "threshold_per_feature": {
            feat: round(thr, 4)
            for feat, thr in zip(LAB_FEATURES, threshold_per_feature)
        },
        "train_losses": train_losses[-5:],  # Last 5 epochs
    }


def _build_lab_sequences(
    records: list[dict[str, Any]],
    window_size: int = 10,
) -> list[list[list[float]]]:
    """
    Extract windowed temporal lab sequences from patient records.

    Returns: List of [window_size, n_features] sequences.
    """
    from prostanet.ai.models.anomaly_detector import ClinicalSequenceVAE

    sequences = []
    for rec in records:
        seq = ClinicalSequenceVAE._extract_lab_series(rec, window_size=window_size)
        if len(seq) == window_size:
            sequences.append(seq)
    return sequences
