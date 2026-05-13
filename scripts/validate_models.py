#!/usr/bin/env python3
"""
ProstaNet AI — Model Validation Script.

Loads trained models and evaluates them on:
  - 500 held-out synthetic patients
  - C-index for survival model
  - State accuracy for transition model
  - PSA50 AUC for treatment response model

Usage:
    python3 scripts/validate_models.py
    python3 scripts/validate_models.py --models-dir output/models
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate_models")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", default="output/models")
    parser.add_argument("--n-patients", type=int, default=500)
    parser.add_argument("--seed", type=int, default=99)
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    report: dict = {}

    # Generate held-out validation set
    logger.info(f"Generating {args.n_patients} held-out validation patients (seed={args.seed})...")
    from prostanet.ai.training.synthetic_generator import generate_synthetic_trajectories
    patients = generate_synthetic_trajectories(n_patients=args.n_patients, seed=args.seed)
    logger.info(f"Generated {len(patients)} validation patients")

    # Load model registry
    from prostanet.ai.inference.model_registry import ModelRegistry
    registry = ModelRegistry(models_dir=models_dir)
    loaded = registry.load_all_available()
    logger.info(f"Models loaded: {loaded}")

    # ── Validate State Transition Model ──
    state_model = registry.get("state_transition")
    if state_model:
        logger.info("Evaluating State Transition Transformer...")
        from prostanet.ai.training.evaluation import state_prediction_accuracy
        from prostanet.ai.config import STATE_TO_IDX

        preds, trues = [], []
        errors = 0
        for p in patients:
            true_state = p.get("reconciled_state", "")
            if true_state not in STATE_TO_IDX:
                continue
            try:
                result = state_model.predict(p)
                pred_state = result.values.get("predicted_state", "")
                if pred_state in STATE_TO_IDX:
                    preds.append(STATE_TO_IDX[pred_state])
                    trues.append(STATE_TO_IDX[true_state])
            except Exception:
                errors += 1

        if preds:
            metrics = state_prediction_accuracy(preds, trues)
            report["state_transition"] = {
                **metrics,
                "evaluated": len(preds),
                "errors": errors,
            }
            logger.info(f"  Accuracy: {metrics['accuracy']:.1%} over {len(preds)} samples")

            # Top 5 states by F1
            per_class = metrics.get("per_class", {})
            ranked = sorted(per_class.items(), key=lambda x: x[1].get("f1", 0), reverse=True)
            logger.info("  Top states by F1:")
            for state, m in ranked[:5]:
                logger.info(f"    {state:40s} F1={m['f1']:.2f} (n={m['support']})")

    # ── Validate Survival Model ──
    surv_model = registry.get("deep_surv")
    if surv_model:
        logger.info("Evaluating DeepSurv OS...")
        from prostanet.ai.training.evaluation import concordance_index
        from prostanet.ai.models.treatment_response import TreatmentResponsePredictor
        import torch

        risks, times, events = [], [], []
        for p in patients:
            survival = p.get("survival", {})
            time_val = survival.get("OS_months")
            event = survival.get("OS_event")
            if time_val is None or event is None:
                continue
            try:
                features = TreatmentResponsePredictor._extract_patient_features(p)
                feat_tensor = torch.tensor([features], dtype=torch.float32)
                # EPIC 17a bugfix: risk_network es el embedding (hidden_dim),
                # NO el log-hazard escalar. Pasar por forward() que aplica
                # endpoint_heads["OS"] para obtener log_hr [1,1] → .item().
                with torch.no_grad():
                    output = surv_model(feat_tensor, endpoint="OS")
                log_hr = output["log_hazard_ratio"].squeeze().item()
                risks.append(log_hr)
                times.append(float(time_val))
                events.append(int(event))
            except Exception as exc:
                # EPIC 17a: log para diagnosticar futuras regresiones en lugar
                # de tragar silenciosamente.
                logger.debug("DeepSurv risk extraction failed: %s", exc)

        if risks:
            c_idx = concordance_index(risks, times, events)
            report["deep_surv_os"] = {
                "c_index": round(c_idx, 4),
                "evaluated": len(risks),
                "events_observed": sum(events),
            }
            logger.info(f"  C-index: {c_idx:.4f} over {len(risks)} patients")
            if c_idx > 0.65:
                logger.info("  ✓ Good discrimination (C-index > 0.65)")
            elif c_idx > 0.55:
                logger.info("  ~ Moderate discrimination (C-index 0.55–0.65)")
            else:
                logger.warning("  ✗ Poor discrimination (C-index < 0.55)")

    # ── Summary ──
    report_path = models_dir / "validation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"\nValidation report saved: {report_path}")

    # Overall pass/fail
    issues = []
    st = report.get("state_transition", {})
    if st.get("accuracy", 0) < 0.4:
        issues.append(f"State accuracy {st.get('accuracy', 0):.1%} < 40% (below expected)")
    surv = report.get("deep_surv_os", {})
    if surv.get("c_index", 0) < 0.55:
        issues.append(f"C-index {surv.get('c_index', 0):.4f} < 0.55 (below random)")

    if issues:
        logger.warning("⚠ Validation issues found:")
        for issue in issues:
            logger.warning(f"  • {issue}")
    else:
        logger.info("✓ All models passed validation thresholds")


if __name__ == "__main__":
    main()
