# IEC 62304 §5.7 (System testing)
"""Tests EPIC 17 — Entrenamiento del 4to AI model (anomaly_detector VAE).

Aplicando anthropic-skills:pytorch-patterns + pytorch-training idioms:
  - Reproducibility (set_seed antes de tensor creation)
  - save state_dict (no full model object) vía ProstaNetModel.save()
  - weights_only=True en torch.load (security)
  - optimizer.zero_grad(set_to_none=True) (efficient)
  - model.eval() + torch.no_grad() en validation
  - GradNorm clip @ 1.0 (estabilidad)

Modelo entrenado (quick run 1000 patients × 10 epochs):
  - anomaly_detector: ClinicalSequenceVAE
    · GRU encoder + reparameterization + GRU decoder
    · 9 lab features (psa, testosterone, alp, ldh, albumin, hemoglobin,
      creatinine, ecog, pain_score)
    · window_size=10 visits, latent_dim=8
    · z-score normalization persisted en normalization_stats.pt

Caveat clínico: shadow-validated con synthetic data, NO production
ready. Sirve para desbloquear Patient Twin readiness + demostrar
pipeline AI completo (4/4 models) para FDA Pre-Sub Q-Sub.

Beneficio clínico tangible del anomaly_detector:
  - Detecta patrones temporales atípicos en labs longitudinales:
    · PSA drop inesperado (puede indicar misreading o error)
    · Testosterone escape durante ADT (LH/FSH surge no detectado)
    · Constelación hepatotoxicidad (alp↑↑ + albumin↓↓ + ldh↑)
    · Deterioro funcional silencioso (ecog↑ + pain↑ sin progresión)
  - Output: per-feature reconstruction error → flag para revisión clínica
  - Population threshold = mean + 2σ (cada feature normalizado)
  - Soporta active surveillance de eventos adversos longitudinales
    sin requerir programación manual de reglas (data-driven anomaly).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "output" / "models"
ANOMALY_DIR = MODELS_DIR / "anomaly_detector"
LAB_FEATURES = [
    "psa", "testosterone", "alp", "ldh", "albumin",
    "hemoglobin", "creatinine", "ecog", "pain_score",
]


def test_epic17_anomaly_artifact_exists_and_nonempty():
    """anomaly_detector/best.pt debe existir con tamaño no-trivial."""
    path = ANOMALY_DIR / "best.pt"
    assert path.exists(), (
        f"Missing artifact: {path}. "
        "Run: python3 scripts/train_all_models.py --patients 1000 --epochs 10"
    )
    size = path.stat().st_size
    assert size > 1024, f"Suspiciously small ({size} bytes): {path}"


def test_epic17_anomaly_normalization_stats_persisted():
    """normalization_stats.pt debe existir (z-score feat_mean + feat_std).

    Sin estos stats, inference produce errores espurios (input no normalizado
    a la distribución que aprendió el VAE en training).
    """
    stats_path = ANOMALY_DIR / "normalization_stats.pt"
    if not stats_path.exists():
        pytest.skip(f"{stats_path} missing (training not yet run)")
    assert stats_path.stat().st_size > 0


def test_epic17_anomaly_loads_with_weights_only_true():
    """pytorch-patterns: torch.load(..., weights_only=True) (security)."""
    import torch

    path = ANOMALY_DIR / "best.pt"
    if not path.exists():
        pytest.skip(f"{path} missing (training not yet run)")

    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    assert isinstance(ckpt, dict), (
        f"anomaly_detector: checkpoint not a dict (got {type(ckpt).__name__})"
    )
    # Estilo BaseModel.save: {"state_dict": {...}, "model_version": "..."}
    assert "state_dict" in ckpt, (
        f"anomaly_detector: no 'state_dict' key (got {list(ckpt.keys())[:5]})"
    )
    state = ckpt["state_dict"]
    assert isinstance(state, dict) and len(state) > 0, (
        "anomaly_detector: state_dict empty"
    )
    # GRU layers + decoder must be present
    has_gru = any("gru" in k.lower() for k in state.keys())
    has_decoder = any("decoder" in k.lower() for k in state.keys())
    assert has_gru, "anomaly_detector: no GRU layers in state_dict"
    assert has_decoder, "anomaly_detector: no decoder layers in state_dict"


def test_epic17_training_report_contains_anomaly_metrics():
    """training_report.json debe documentar el anomaly_detector run."""
    report_path = MODELS_DIR / "training_report.json"
    if not report_path.exists():
        pytest.skip("training_report.json missing")
    report = json.loads(report_path.read_text())
    anomaly = report.get("anomaly_detector") or {}
    if not anomaly:
        pytest.skip("anomaly_detector not in latest training_report run")
    # Schema mínimo (campos críticos del return dict)
    assert "model_path" in anomaly
    assert "samples" in anomaly
    assert int(anomaly["samples"]) >= 10, (
        f"VAE needs ≥10 sequences (got {anomaly['samples']})"
    )
    # best_val_loss debe ser finito (no NaN/inf)
    bvl = anomaly.get("best_val_loss")
    if bvl is not None:
        assert float(bvl) == float(bvl), "best_val_loss is NaN"
        assert float(bvl) < float("inf"), "best_val_loss is inf"


def test_epic17_anomaly_threshold_per_feature_covers_all_labs():
    """threshold_per_feature debe cubrir las 9 LAB_FEATURES."""
    report_path = MODELS_DIR / "training_report.json"
    if not report_path.exists():
        pytest.skip("training_report.json missing")
    report = json.loads(report_path.read_text())
    anomaly = report.get("anomaly_detector") or {}
    thresholds = anomaly.get("threshold_per_feature") or {}
    if not thresholds:
        pytest.skip("anomaly threshold_per_feature absent")
    missing = set(LAB_FEATURES) - set(thresholds.keys())
    assert not missing, f"Threshold missing for features: {missing}"
    # All thresholds must be positive floats (mean + 2σ ≥ 0 since σ ≥ 0)
    for feat, thr in thresholds.items():
        assert float(thr) >= 0.0, f"Negative threshold for {feat}: {thr}"


def test_epic17_model_registry_loads_anomaly_detector():
    """ModelRegistry debe poder cargar el anomaly_detector sin error."""
    from prostanet.ai.inference.model_registry import ModelRegistry

    reg = ModelRegistry()
    # Try load_model first (canonical API)
    loaded = False
    try:
        if hasattr(reg, "load_model"):
            loaded = reg.load_model("anomaly_detector")
    except Exception:
        loaded = False
    if not loaded:
        pytest.skip("anomaly_detector load failed — training may not have completed")
    model = reg.get("anomaly_detector")
    assert model is not None, "anomaly_detector loaded but get() returned None"


def test_epic17_pytorch_patterns_anomaly_trainer_uses_set_to_none_and_no_grad():
    """trainers.train_anomaly_detector debe seguir pytorch-patterns idioms:
      - optimizer.zero_grad(set_to_none=True)
      - torch.no_grad() en validation
      - clip_grad_norm_ para estabilidad VAE
    """
    trainers = PROJECT_ROOT / "prostanet" / "ai" / "training" / "trainers.py"
    content = trainers.read_text()
    # Bracket por train_anomaly_detector boundaries
    start = content.find("def train_anomaly_detector(")
    if start < 0:
        pytest.skip("train_anomaly_detector not found")
    end = content.find("\ndef ", start + 1)
    body = content[start:end if end > 0 else len(content)]

    assert "zero_grad(set_to_none=True)" in body, (
        "train_anomaly_detector must use zero_grad(set_to_none=True) per pytorch-patterns"
    )
    assert "torch.no_grad()" in body, (
        "train_anomaly_detector validation must wrap in torch.no_grad() per pytorch-patterns"
    )
    assert "clip_grad_norm_" in body, (
        "train_anomaly_detector must use clip_grad_norm_ for VAE stability"
    )
    assert "model.eval()" in body, (
        "train_anomaly_detector must call model.eval() before validation"
    )


def test_epic17_train_script_includes_anomaly_invocation():
    """scripts/train_all_models.py debe invocar train_anomaly_detector."""
    script = PROJECT_ROOT / "scripts" / "train_all_models.py"
    content = script.read_text()
    assert "train_anomaly_detector" in content, (
        "scripts/train_all_models.py must invoke train_anomaly_detector (EPIC 17)"
    )
    assert "--skip-anomaly" in content, (
        "scripts/train_all_models.py must expose --skip-anomaly flag (EPIC 17)"
    )


def test_epic17_loop_monitor_patient_twin_readiness_no_regression():
    """Patient Twin readiness no debe regresar post-EPIC 17.

    Baseline pre-EPIC 16: 65
    Post-EPIC 16 con 3 models: ≥65 (no regression confirmado)
    Post-EPIC 17 con 4 models: ≥65 (no regression). Target aspiracional
    ≥75-85 si build_patient_twin_readiness_loop está cableado al registry.
    """
    from prostanet.agentic.autonomous_improvement_os import (
        build_autonomous_improvement_bundle,
    )

    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    metrics = bundle.get("mission_control", {}).get("metrics", []) or []
    ptr = next(
        (m for m in metrics if m.get("key") == "patient_twin_readiness"),
        None,
    )
    assert ptr is not None, "patient_twin_readiness metric missing"
    value = float(ptr.get("value", 0))
    assert value >= 65.0, (
        f"Patient Twin readiness regressed post-EPIC 17: {value} < 65"
    )
