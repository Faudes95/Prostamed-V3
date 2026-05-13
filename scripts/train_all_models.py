#!/usr/bin/env python3
"""
ProstaNet AI — Master Training Script.

Generates 10,000 synthetic longitudinal patient trajectories and
trains all 3 core models:
  1. StateTransitionTransformer — predicts next clinical state
  2. TreatmentResponsePredictor — predicts PSA50, rPFS, toxicity
  3. DeepSurvNet — personalized survival curves

Usage:
    python3 scripts/train_all_models.py
    python3 scripts/train_all_models.py --patients 1000 --epochs 20
    python3 scripts/train_all_models.py --skip-state --skip-surv

Trained models are saved to output/models/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_all_models")


def set_seed(seed: int) -> None:
    """Full reproducibility setup per anthropic-skills:pytorch-patterns.

    EPIC 16: garantiza que `python3 scripts/train_all_models.py --seed=42`
    es reproducible bit-a-bit entre runs (modulo non-determinism CUDA en
    operaciones no-cudnn-deterministic).
    """
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ProstaNet AI Model Training")
    parser.add_argument("--patients", type=int, default=10000, help="Number of synthetic patients")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs per model")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", type=str, default="output/models", help="Output directory")
    parser.add_argument("--skip-state", action="store_true", help="Skip state transition model")
    parser.add_argument("--skip-treatment", action="store_true", help="Skip treatment response model")
    parser.add_argument("--skip-surv", action="store_true", help="Skip survival model")
    parser.add_argument("--skip-anomaly", action="store_true", help="Skip anomaly detector VAE")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # EPIC 16: set_seed before ANY tensor/dataset creation per pytorch-patterns
    # reproducibility principle. random + numpy + torch seeded uniformly.
    set_seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    results: dict[str, object] = {"config": vars(args)}

    # ── Step 1: Generate synthetic trajectories ──
    logger.info("=" * 60)
    logger.info(f"Generating {args.patients:,} synthetic patient trajectories...")
    logger.info("=" * 60)

    from prostanet.ai.training.synthetic_generator import generate_synthetic_trajectories

    t0 = time.perf_counter()
    patients = generate_synthetic_trajectories(
        n_patients=args.patients,
        seed=args.seed,
    )
    gen_time = time.perf_counter() - t0
    logger.info(f"Generated {len(patients):,} patients in {gen_time:.1f}s")

    # Print state distribution
    from collections import Counter
    state_dist = Counter(p["reconciled_state"] for p in patients)
    logger.info("State distribution:")
    for state, count in state_dist.most_common():
        logger.info(f"  {state:45s} {count:5d} ({count/len(patients):.1%})")

    results["generation"] = {
        "patients": len(patients),
        "time_seconds": round(gen_time, 1),
        "state_distribution": dict(state_dist),
    }

    # ── Step 2: Train State Transition Transformer ──
    if not args.skip_state:
        logger.info("\n" + "=" * 60)
        logger.info("Training State Transition Transformer...")
        logger.info("=" * 60)

        from prostanet.ai.training.trainers import train_state_transition

        t0 = time.perf_counter()
        state_result = train_state_transition(
            records=patients,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            output_dir=output_dir,
        )
        state_time = time.perf_counter() - t0

        if "error" in state_result:
            logger.error(f"State transition training failed: {state_result['error']}")
        else:
            logger.info(
                f"State model trained: {state_result['samples']} samples, "
                f"best_val_loss={state_result.get('best_val_loss', '?')}, "
                f"accuracy={state_result.get('final_accuracy', 0):.1%}, "
                f"time={state_time:.1f}s"
            )
            logger.info(f"Model saved: {state_result.get('model_path', '?')}")

        results["state_transition"] = {**state_result, "training_time_seconds": round(state_time, 1)}

    # ── Step 3: Train Treatment Response Predictor ──
    if not args.skip_treatment:
        logger.info("\n" + "=" * 60)
        logger.info("Training Treatment Response Predictor...")
        logger.info("=" * 60)

        from prostanet.ai.training.trainers import train_treatment_response

        t0 = time.perf_counter()
        tx_result = train_treatment_response(
            records=patients,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            output_dir=output_dir,
        )
        tx_time = time.perf_counter() - t0

        if "error" in tx_result:
            logger.warning(
                f"Treatment response training: {tx_result['error']} "
                f"(need treatments with outcomes in training data)"
            )
        else:
            logger.info(
                f"Treatment model trained: {tx_result['samples']} samples, "
                f"best_val_loss={tx_result.get('best_val_loss', '?')}, "
                f"time={tx_time:.1f}s"
            )

        results["treatment_response"] = {**tx_result, "training_time_seconds": round(tx_time, 1)}

    # ── Step 4: Train DeepSurv for OS ──
    if not args.skip_surv:
        logger.info("\n" + "=" * 60)
        logger.info("Training DeepSurv (OS endpoint)...")
        logger.info("=" * 60)

        from prostanet.ai.training.trainers import train_deep_surv

        t0 = time.perf_counter()
        # EPIC 17a: Cox PH partial likelihood usa el batch como risk set;
        # batch_size grande mejora la estimación. lr=1e-2 también acelera
        # convergencia del log-hazard escalar (post EPIC 17a fix).
        surv_result = train_deep_surv(
            records=patients,
            endpoint="OS",
            epochs=args.epochs,
            batch_size=max(args.batch_size, 64),
            lr=1e-2,
            output_dir=output_dir,
        )
        surv_time = time.perf_counter() - t0

        if "error" in surv_result:
            logger.error(f"Survival training failed: {surv_result['error']}")
        else:
            logger.info(
                f"DeepSurv OS trained: {surv_result['samples']} samples, "
                f"best_loss={surv_result.get('best_loss', '?')}, "
                f"time={surv_time:.1f}s"
            )

        results["deep_surv_os"] = {**surv_result, "training_time_seconds": round(surv_time, 1)}

    # ── Step 5: Train Anomaly Detector VAE (EPIC 17) ──
    if not args.skip_anomaly:
        logger.info("\n" + "=" * 60)
        logger.info("Training Anomaly Detector VAE (EPIC 17)...")
        logger.info("=" * 60)

        from prostanet.ai.training.trainers import train_anomaly_detector

        t0 = time.perf_counter()
        anomaly_result = train_anomaly_detector(
            records=patients,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            output_dir=output_dir,
        )
        anomaly_time = time.perf_counter() - t0

        if "error" in anomaly_result:
            logger.warning(
                f"Anomaly detector training: {anomaly_result['error']} "
                f"(need ≥10 patients with longitudinal lab sequences)"
            )
        else:
            logger.info(
                f"Anomaly detector trained: {anomaly_result['samples']} sequences, "
                f"best_val_loss={anomaly_result.get('best_val_loss', '?')}, "
                f"time={anomaly_time:.1f}s"
            )
            logger.info(f"Model saved: {anomaly_result.get('model_path', '?')}")

        results["anomaly_detector"] = {**anomaly_result, "training_time_seconds": round(anomaly_time, 1)}

    # ── Step 6: Register trained models in DB ──
    _register_models_in_db(output_dir, results)

    # ── Summary ──
    total_time = time.perf_counter() - t_start
    results["total_time_seconds"] = round(total_time, 1)

    logger.info("\n" + "=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info(f"Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    logger.info("=" * 60)

    # Save results report
    report_path = output_dir / "training_report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Report saved: {report_path}")

    # Print model paths
    logger.info("\nTrained model artifacts:")
    for model_dir in sorted(output_dir.glob("*/best.pt")):
        size_mb = model_dir.stat().st_size / 1024 / 1024
        logger.info(f"  {model_dir} ({size_mb:.1f} MB)")


def _register_models_in_db(output_dir: Path, results: dict) -> None:
    """Register trained models in ai_model_registry table."""
    try:
        from prostanet.ai.inference.model_registry import ModelRegistry
        reg = ModelRegistry(models_dir=output_dir)

        model_map = {
            "state_transition": ("state_transition", "StateTransitionTransformer"),
            "treatment_response": ("treatment_response", "TreatmentResponsePredictor"),
            "deep_surv": ("deep_surv_os", "DeepSurvNet"),
            "anomaly_detector": ("anomaly_detector", "ClinicalSequenceVAE"),
        }

        for model_id, (result_key, model_type) in model_map.items():
            artifact_path = output_dir / model_id / "best.pt"
            if not artifact_path.exists():
                # Check alternate path for deep_surv
                if model_id == "deep_surv":
                    artifact_path = output_dir / "deep_surv_OS" / "best.pt"
                if not artifact_path.exists():
                    continue

            metrics = results.get(result_key, {})
            reg.register_in_db(
                model_id=model_id,
                model_version="1.0.0",
                model_type=model_type,
                artifact_path=str(artifact_path),
                metrics=metrics,
            )
            logger.info(f"Registered in DB: {model_id} v1.0.0")
    except Exception as exc:
        logger.warning(f"DB registration skipped: {exc}")


if __name__ == "__main__":
    main()
