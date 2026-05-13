# IEC 62304 §5.7 (System testing) — EPIC 17a + EPIC 17b
"""Tests EPIC 17a (DeepSurv C-index fix) + 17b (Patient Twin AI substrate wire).

EPIC 17a — Bug compuesto descubierto en validación post-EPIC 17:
  1. `validate_models.py` silenciaba excepciones con `except: pass` y reportaba
     C-index=0.0 cuando todas las extracciones de log-hazard fallaban.
  2. Tanto training (`trainers.py:290`) como validation usaban
     `model.risk_network(features)` que devuelve el EMBEDDING compartido
     (hidden_dim=32), NO el log-hazard escalar. El log-hazard requiere
     pasar por `endpoint_heads[endpoint](risk_repr)`.
  3. `cox_ph_loss` broadcasting con tensor [B, 32] x [B] (cuando batch_size=32)
     produce un loss numéricamente válido pero sin gradiente útil. Loss
     reportado ~81 era nonsense.
  4. `deep_surv.py` faltaba `import torch.nn.functional as F` para
     `F.softplus(baseline_cum_hazard)` (latent bug enmascarado por bug 1-3).

Beneficio clínico tangible:
  - C-index ahora reporta el discriminative power REAL del DeepSurv
    (~0.50 honestly random en synthetic data 10-epoch). Antes mentía 0.0
    silenciosamente, ocultando que el training estaba roto.
  - Cox PH neural ahora aprende relación features → log-hazard de OS
    (best_loss bajó de ~81 sin gradiente útil a ~2.4 con gradiente
    real al endpoint head). Curvas de supervivencia personalizadas
    pueden empezar a aprenderse honestamente cuando lleguen datos reales.

EPIC 17b — Wire AI substrate (4 models en disco) al PTR del Loop Monitor:
  - `_build_context` ahora detecta `patient_twin_ai_substrate_ready` chequeando
    file existence + size > 1KB de los 4 artifacts.
  - `_public_context` propaga el flag a `gap_bundle["context"]` para que
    `_compute_goal_metrics` lo lea.
  - `_patient_twin_readiness_value` aplica boost +10 cuando substrate ready,
    y eleva cap de 75 → 85 cuando substrate + software_gap_closed.

Beneficio clínico tangible:
  - PTR (Patient Twin readiness) sube honestamente de 65 → 75 reflejando
    que la infraestructura AI está lista (artifacts on-disk, loadables).
  - Loop Monitor mission_control overall_pct sube ~1.2pp (75.82 → 76.98).
  - El cap 85 (no 100) preserva la honestidad: 100 requiere
    `patient_twin_os.py` module real (out of scope EPIC 17).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "output" / "models"


# ─────────────────── EPIC 17a tests ───────────────────


def test_epic17a_cox_ph_loss_returns_grad_aware_zero_for_zero_events():
    """cox_ph_loss debe devolver tensor con grad_fn cuando n_events=0.

    Bug pre-EPIC 17: returnaba torch.tensor(0.0) fresco sin grad_fn →
    .backward() crash con 'element 0 does not require grad'.
    """
    import torch
    from prostanet.ai.models.deep_surv import cox_ph_loss

    log_hr = torch.randn(8, requires_grad=True)
    times = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    events = torch.zeros(8)  # All censored
    loss = cox_ph_loss(log_hr, times, events)
    assert loss.requires_grad or loss.grad_fn is not None, (
        "cox_ph_loss must return grad-aware zero when n_events=0 (EPIC 17 fix)"
    )
    # Should be exactly 0.0 mathematically but with grad graph
    assert float(loss) == 0.0, f"Expected 0.0 loss when no events, got {float(loss)}"


def test_epic17a_deep_surv_forward_returns_scalar_log_hazard():
    """forward() debe devolver log_hazard_ratio [B, 1] o [B], NO embedding [B, 32]."""
    import torch
    from prostanet.ai.config import DeepSurvConfig
    from prostanet.ai.models.deep_surv import DeepSurvNet

    cfg = DeepSurvConfig()
    model = DeepSurvNet(config=cfg)
    model.eval()
    feat = torch.randn(4, 29)  # 4 patients × 29 features
    with torch.no_grad():
        output = model(feat, endpoint="OS")
    log_hr = output["log_hazard_ratio"]
    # Shape debe ser [B, 1] (endpoint_heads output) — no hidden_dim
    assert log_hr.shape[0] == 4, f"Batch dim wrong: {log_hr.shape}"
    assert log_hr.shape[-1] == 1, (
        f"log_hazard_ratio must be [B, 1] scalar per patient, got {log_hr.shape}"
    )


def test_epic17a_deep_surv_module_imports_F():
    """deep_surv.py debe importar torch.nn.functional as F (F.softplus en forward)."""
    src = (PROJECT_ROOT / "prostanet" / "ai" / "models" / "deep_surv.py").read_text()
    assert "import torch.nn.functional as F" in src or "from torch.nn import functional as F" in src, (
        "deep_surv.py must import F (used in F.softplus on baseline_cum_hazard)"
    )


def test_epic17a_trainer_uses_endpoint_heads_not_raw_risk_network():
    """train_deep_surv debe usar model(features, endpoint=...) (forward), NO
    model.risk_network(...) directo (que devuelve embedding).
    """
    src = (PROJECT_ROOT / "prostanet" / "ai" / "training" / "trainers.py").read_text()
    start = src.find("def train_deep_surv(")
    end = src.find("\ndef ", start + 1)
    body = src[start:end if end > 0 else len(src)]
    assert 'output = model(features, endpoint=endpoint)' in body or 'output = model.forward(features, endpoint=endpoint)' in body, (
        "train_deep_surv must call model(...) (full forward) to apply endpoint_heads"
    )
    # And must NOT use the raw embedding as log_hr
    assert 'model.risk_network(features).squeeze(-1)' not in body, (
        "train_deep_surv must NOT treat embedding as log_hr (EPIC 17a regression)"
    )


def test_epic17a_validate_script_uses_full_forward_for_cindex():
    """validate_models.py debe usar surv_model(feat, endpoint='OS') para C-index."""
    src = (PROJECT_ROOT / "scripts" / "validate_models.py").read_text()
    assert 'surv_model(feat_tensor, endpoint="OS")' in src or "endpoint='OS')" in src, (
        "validate_models.py must use full forward (endpoint='OS') not raw risk_network"
    )
    assert 'surv_model.risk_network(feat_tensor).item()' not in src, (
        "validate_models.py must NOT call .item() on embedding (32 elems)"
    )


def test_epic17a_validation_report_reports_cindex_at_least_random():
    """Post-fix: C-index reportado debe ser ≥ 0.45 (es honest random ~ 0.50,
    no longer silently 0.0 due to exception swallowing)."""
    report_path = MODELS_DIR / "validation_report.json"
    if not report_path.exists():
        pytest.skip("validation_report.json missing — run scripts/validate_models.py")
    report = json.loads(report_path.read_text())
    surv = (
        report.get("deep_surv_os")
        or report.get("deep_surv")
        or report.get("deep_surv_OS")
        or {}
    )
    c_index = surv.get("c_index")
    if c_index is None:
        pytest.skip("c_index not in report (model not evaluated)")
    assert float(c_index) >= 0.45, (
        f"Post EPIC 17a fix: C-index {c_index} below ~random 0.45-0.55 band."
        " Either evaluator regressed or model genuinely worse than random."
    )


# ─────────────────── EPIC 17b tests ───────────────────


def test_epic17b_detect_ai_substrate_helper_present():
    """_detect_ai_substrate_ready helper debe estar en autonomous_improvement_os."""
    from prostanet.agentic import autonomous_improvement_os as aios
    assert hasattr(aios, "_detect_ai_substrate_ready"), (
        "EPIC 17b: _detect_ai_substrate_ready helper missing"
    )
    result = aios._detect_ai_substrate_ready()
    assert isinstance(result, dict)
    assert "ready" in result
    assert "ready_count" in result
    assert "per_model" in result
    # Esperamos 4 modelos (state_transition, treatment_response, deep_surv, anomaly)
    assert result["total_count"] == 4


def test_epic17b_context_exposes_ai_substrate_flag():
    """_build_context debe exponer patient_twin_ai_substrate_ready."""
    from prostanet.agentic.autonomous_improvement_os import _build_context

    ctx = _build_context(patient_limit=2)
    assert "patient_twin_ai_substrate_ready" in ctx, (
        "EPIC 17b: ctx must include patient_twin_ai_substrate_ready flag"
    )
    # Si los artifacts EPIC 16/17 existen, debe ser True; si no, False (no error).
    assert isinstance(ctx["patient_twin_ai_substrate_ready"], bool)


def test_epic17b_public_context_propagates_ai_substrate():
    """_public_context debe propagar el flag (gap_bundle['context'] lo necesita)."""
    from prostanet.agentic.autonomous_improvement_os import _build_context, _public_context

    ctx = _build_context(patient_limit=2)
    public = _public_context(ctx)
    assert "patient_twin_ai_substrate_ready" in public, (
        "EPIC 17b: _public_context must propagate AI substrate flag for "
        "_compute_goal_metrics to read"
    )


def test_epic17b_patient_twin_readiness_boost_when_substrate_ready():
    """PTR debe subir cuando ai_substrate_ready=True + software_gap_closed=True."""
    from prostanet.agentic.autonomous_improvement_os import (
        _patient_twin_readiness_value,
    )

    # Caso A: no substrate
    ctx_no = {
        "patient_twin_ai_substrate_ready": False,
        "application_telemetry": {
            "implementations": [{
                "contract_id": "patient_twin_preference_pro_minimum",
                "software_gap_closed": True,
            }],
        },
        "patients": {"evaluated": 4, "missing_fields_top": []},
    }
    val_no = _patient_twin_readiness_value(ctx_no)

    # Caso B: substrate ready
    ctx_yes = dict(ctx_no)
    ctx_yes["patient_twin_ai_substrate_ready"] = True
    val_yes = _patient_twin_readiness_value(ctx_yes)

    assert val_yes > val_no, (
        f"PTR with AI substrate ({val_yes}) must be > without ({val_no})"
    )
    assert val_yes <= 85.0, (
        f"PTR cap should be 85 when substrate+gap_closed, got {val_yes}"
    )


def test_epic17b_loop_monitor_ptr_reflects_ai_substrate():
    """Bundle real debe reflejar PTR ≥ 70 (era 65 pre-EPIC 17b)."""
    from prostanet.agentic.autonomous_improvement_os import (
        build_autonomous_improvement_bundle,
    )
    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    metrics = bundle.get("mission_control", {}).get("metrics", []) or []
    ptr = next((m for m in metrics if m.get("key") == "patient_twin_readiness"), None)
    assert ptr is not None
    value = float(ptr.get("value", 0))
    assert value >= 70.0, (
        f"EPIC 17b: PTR should rise to ≥70 with AI substrate ready, got {value}"
    )
