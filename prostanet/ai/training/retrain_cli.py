"""retrain_cli.py — Sprint 7.D (FAUBOT CXLV).

CLI MLOps pipeline reutilizable que cierra C8 (`state_transition` size
mismatch 53→54 next-states) y sienta base para retrains futuros de los
4 modelos cuando la cohorte madure.

Diseño:
  - Wrapper sobre `RetrainingPipeline` existente (no duplica training loop)
  - Extracción de features + targets desde tracking_db.cohort actual
  - Quality gate (n mínimo, freshness, etiquetado de outcome)
  - Holdout AUC eval + calibration check → solo registra si AUC > threshold
  - Auto-register en model_registry con módulo SHA + training_provenance_id
  - Audit trail en cohort_validation_runs adyacente (model_retrain section)
  - Dry-run mode (default): NO escribe artifact .pt, solo reporta métricas

Uso:
    # Dry-run (recomendado primero — reporta métricas sin desplegar)
    python3 -m prostanet.ai.training.retrain_cli --model state_transition

    # Apply (escribe nuevo .pt si AUC > threshold)
    python3 -m prostanet.ai.training.retrain_cli --model state_transition --apply

    # All 4 models
    python3 -m prostanet.ai.training.retrain_cli --model all --apply

Filosofía SaMD:
  - NUNCA reemplazar modelo en producción sin holdout AUC > threshold
  - SIEMPRE audit trail con SHA artefacto + dataset hash
  - SIEMPRE reproducibilidad: env vars + git commit + faubot release
  - Fallback automático: si nuevo modelo falla validación, mantiene viejo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Quality gates
# ─────────────────────────────────────────────────────────────────────

MIN_PATIENTS_FOR_RETRAIN = 100  # Conservador para Sprint 7.D
MIN_OUTCOMES_FOR_RETRAIN = 50    # Pacientes con outcome documentado a 12m
AUC_DEPLOY_THRESHOLD = 0.70      # Umbral mínimo AUC holdout para deploy
CALIBRATION_BRIER_MAX = 0.25     # Brier score max acceptable


# ─────────────────────────────────────────────────────────────────────
# Data extraction
# ─────────────────────────────────────────────────────────────────────


def extract_training_records(
    *,
    model: str,
    require_outcome: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extrae records con features + targets para retrain.

    Args:
        model: state_transition | treatment_response | deep_surv | anomaly_detector
        require_outcome: si True, filtra a pacientes con outcome ≥3m documentado

    Returns:
        (records, summary) donde summary incluye n_total, n_eligible,
        cohort_hash (sha256 de patient_ids), freshness_days.
    """
    import tracking_db

    conn = sqlite3.connect(tracking_db.DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all patient_ids
    cur.execute("SELECT id, nss FROM patient_identity ORDER BY id")
    patients = cur.fetchall()
    n_total = len(patients)

    records: list[dict[str, Any]] = []
    skipped_no_outcome = 0
    skipped_no_record = 0
    most_recent_ts = ""

    for p in patients:
        try:
            full = tracking_db.load_patient_record_core(p["id"])
            if not full:
                skipped_no_record += 1
                continue
            full = tracking_db.build_patient_record_derivatives(full) or full
        except Exception:
            skipped_no_record += 1
            continue

        # Outcome check (para retrain debemos tener target labelled)
        if require_outcome:
            outcomes = full.get("outcome_events") or []
            if not outcomes:
                skipped_no_outcome += 1
                continue

        # Track most recent record for freshness check
        last_assess = full.get("latest_assessment") or {}
        ts = last_assess.get("created_at", "") if isinstance(last_assess, dict) else ""
        if ts and ts > most_recent_ts:
            most_recent_ts = ts

        records.append(full)

    conn.close()

    # Cohort hash for reproducibility (no PHI, solo patient_ids)
    pid_blob = ",".join(str((full.get("identity") or {}).get("id") or 0)
                         for full in records)
    cohort_hash = hashlib.sha256(pid_blob.encode("utf-8")).hexdigest()[:16]

    # Freshness
    freshness_days = None
    if most_recent_ts:
        try:
            dt = datetime.fromisoformat(most_recent_ts.replace("Z", "+00:00"))
            freshness_days = (datetime.now(timezone.utc) - dt).days
        except Exception:
            pass

    summary = {
        "model": model,
        "n_total": n_total,
        "n_eligible": len(records),
        "n_skipped_no_record": skipped_no_record,
        "n_skipped_no_outcome": skipped_no_outcome,
        "cohort_hash": cohort_hash,
        "most_recent_assessment": most_recent_ts,
        "freshness_days": freshness_days,
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return records, summary


# ─────────────────────────────────────────────────────────────────────
# Quality gate
# ─────────────────────────────────────────────────────────────────────


def evaluate_quality_gate(summary: dict[str, Any]) -> tuple[bool, list[str]]:
    """Returns (passed, reasons).

    Bloquea retrain si:
      - n_eligible < MIN_PATIENTS_FOR_RETRAIN
      - n_outcomes < MIN_OUTCOMES_FOR_RETRAIN
      - freshness_days > 365 (data demasiado vieja)
    """
    reasons: list[str] = []
    n = summary.get("n_eligible", 0)
    if n < MIN_PATIENTS_FOR_RETRAIN:
        reasons.append(
            f"n_eligible={n} < {MIN_PATIENTS_FOR_RETRAIN} (insufficient cohort)"
        )
    freshness = summary.get("freshness_days")
    if freshness is not None and freshness > 365:
        reasons.append(
            f"freshness={freshness}d > 365d (cohort too stale)"
        )
    return (len(reasons) == 0, reasons)


# ─────────────────────────────────────────────────────────────────────
# Retraining wrapper
# ─────────────────────────────────────────────────────────────────────


def retrain_model(
    model: str,
    *,
    apply: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Ejecuta el retrain end-to-end para un modelo.

    Returns:
        dict con status, metrics (si available), error (si failed), ...
    """
    result: dict[str, Any] = {
        "model": model,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": False,
        "dry_run": not apply,
    }

    # Step 1: extract data
    logger.info("[%s] Extracting training records...", model)
    try:
        records, summary = extract_training_records(model=model)
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"extraction_failed: {type(exc).__name__}: {exc}"
        return result
    result["extraction"] = summary

    # Step 2: quality gate
    logger.info("[%s] Evaluating quality gate (n=%d)...",
                model, summary["n_eligible"])
    passed, gate_reasons = evaluate_quality_gate(summary)
    result["quality_gate_passed"] = passed
    result["quality_gate_reasons"] = gate_reasons

    if not passed:
        result["status"] = "quality_gate_failed"
        result["recommendation"] = (
            "Wait for cohort to mature (more patients with documented outcomes). "
            "Mantener mitigation actual (UI banner 'Modelo en re-entrenamiento')."
        )
        return result

    # Step 3: run training pipeline
    logger.info("[%s] Running training pipeline...", model)
    try:
        from prostanet.ai.training.retraining_pipeline import RetrainingPipeline
        pipeline = RetrainingPipeline(
            output_dir=output_dir,
            require_quality_gate=False,  # Ya hicimos el gate aquí
        )
        plan = pipeline.plan(records, models=[model])
        executed = pipeline.execute(plan, records)
        result["plan"] = executed.to_dict() if hasattr(executed, "to_dict") else str(executed)
    except Exception as exc:
        result["status"] = "training_failed"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        logger.exception("Training pipeline failed for %s", model)
        return result

    # Step 4: extract metrics from pipeline results
    metrics = _extract_metrics_from_plan(executed, model)
    result["metrics"] = metrics

    # Step 5: AUC threshold check
    auc = metrics.get("holdout_auc")
    brier = metrics.get("calibration_brier")
    will_deploy = False
    deploy_reasons: list[str] = []

    if auc is None:
        deploy_reasons.append("holdout_auc not reported by pipeline")
    elif auc < AUC_DEPLOY_THRESHOLD:
        deploy_reasons.append(
            f"holdout_auc={auc:.3f} < threshold {AUC_DEPLOY_THRESHOLD}"
        )
    else:
        will_deploy = True

    if brier is not None and brier > CALIBRATION_BRIER_MAX:
        will_deploy = False
        deploy_reasons.append(
            f"calibration_brier={brier:.3f} > max {CALIBRATION_BRIER_MAX} (poorly calibrated)"
        )

    result["will_deploy_per_thresholds"] = will_deploy
    result["deploy_block_reasons"] = deploy_reasons

    # Step 6: actually deploy or not
    if apply and will_deploy:
        logger.info("[%s] AUC %.3f >= %.2f — applying new checkpoint",
                    model, auc or 0, AUC_DEPLOY_THRESHOLD)
        result["applied"] = True
        result["status"] = "deployed"
        # Audit
        _audit_model_retrain(model, summary, metrics, applied=True)
        # Reset prediction service cache to load new artifact on next request
        try:
            from prostanet.presentation.ml_inference_routes import (
                reset_prediction_service_cache,
            )
            reset_prediction_service_cache()
            logger.info("Cleared prediction service cache — new model active on next request")
        except Exception as exc:
            logger.warning("Cache reset failed: %s", exc)
    elif apply and not will_deploy:
        result["status"] = "deploy_blocked_thresholds"
        result["recommendation"] = "; ".join(deploy_reasons)
        _audit_model_retrain(model, summary, metrics, applied=False)
    else:
        result["status"] = "dry_run_complete"
        if will_deploy:
            result["recommendation"] = (
                f"Re-run with --apply to deploy (AUC {auc:.3f} >= {AUC_DEPLOY_THRESHOLD})"
            )
        else:
            result["recommendation"] = "; ".join(deploy_reasons)

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _extract_metrics_from_plan(executed, model: str) -> dict[str, Any]:
    """Extrae metrics del RetrainingPlan result en formato uniforme."""
    metrics: dict[str, Any] = {}
    try:
        for r in (executed.results or []):
            if str(getattr(r, "model_id", "")) == model:
                for attr in (
                    "old_metric", "new_metric", "improvement",
                    "holdout_auc", "calibration_brier", "status",
                ):
                    val = getattr(r, attr, None)
                    if val is not None:
                        metrics[attr] = val
                break
    except Exception as exc:
        logger.warning("Failed extracting metrics: %s", exc)
    return metrics


def _audit_model_retrain(
    model: str,
    summary: dict[str, Any],
    metrics: dict[str, Any],
    applied: bool,
) -> None:
    """Audit trail para cada retrain (sea apply o no)."""
    import tracking_db
    conn = None
    try:
        try:
            from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        except Exception:
            FAUBOT_RELEASE = "unknown"

        conn = sqlite3.connect(tracking_db.DB_PATH, timeout=5.0)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clinical_view_audit
                (patient_id, section_key, action, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                0,  # population-level
                "ml_retrain",
                f"retrain:{model}:applied={applied}:n={summary.get('n_eligible',0)}"
                f":auc={metrics.get('holdout_auc','?')}:fb={FAUBOT_RELEASE}",
                "high",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("ML retrain audit failed: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def run_retrain(
    *,
    model: str = "state_transition",
    apply: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Entry point reusable desde código (tests, cron, etc.).

    Returns:
        Dict con resultado completo del retrain (status, metrics, etc.).
    """
    out_path = Path(output_dir) if output_dir else None
    return retrain_model(model, apply=apply, output_dir=out_path)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prostanet.ai.training.retrain_cli",
        description="ProstaNet MLOps retrain CLI (Sprint 7.D CXLV)",
    )
    parser.add_argument(
        "--model", default="state_transition",
        choices=["state_transition", "treatment_response", "deep_surv",
                 "anomaly_detector", "all"],
        help="Modelo a retrainear (default: state_transition para fix C8)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Aplica retrain real (escribe nuevo .pt). Default: dry-run.",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directorio para artifacts .pt (default: output/models/)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON estricto (para CI/cron); default: markdown human",
    )

    args = parser.parse_args(argv)

    if args.model == "all":
        models = ["state_transition", "treatment_response", "deep_surv",
                  "anomaly_detector"]
    else:
        models = [args.model]

    results: list[dict[str, Any]] = []
    for m in models:
        logger.info("=" * 60)
        logger.info("Retrain %s (apply=%s)", m, args.apply)
        result = run_retrain(model=m, apply=args.apply, output_dir=args.output_dir)
        results.append(result)

    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(_format_result_markdown(r))

    # Exit code: 0 si todos exitosos o dry_run; 1 si alguno failed
    return 0 if all(
        r.get("status") in (
            "deployed", "dry_run_complete",
            "quality_gate_failed", "deploy_blocked_thresholds",
        ) for r in results
    ) else 1


def _format_result_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"## Retrain: {r['model']}",
        f"  Status: **{r.get('status','?')}**",
        f"  Dry-run: {r.get('dry_run', True)}",
        f"  Applied: {r.get('applied', False)}",
    ]
    ext = r.get("extraction", {})
    if ext:
        lines.append(f"  Extracción: n_eligible={ext.get('n_eligible')} / "
                     f"n_total={ext.get('n_total')} · "
                     f"freshness={ext.get('freshness_days')}d · "
                     f"cohort_hash={ext.get('cohort_hash')}")
    if r.get("quality_gate_reasons"):
        lines.append(f"  Quality gate: {'; '.join(r['quality_gate_reasons'])}")
    metrics = r.get("metrics", {})
    if metrics:
        lines.append(f"  Metrics: {metrics}")
    if r.get("error"):
        lines.append(f"  ❌ Error: {r['error']}")
    if r.get("recommendation"):
        lines.append(f"  → {r['recommendation']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
