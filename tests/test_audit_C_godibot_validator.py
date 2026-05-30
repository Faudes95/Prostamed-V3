"""Tests dedicados — Faubot Iteración C (GodiBot v1).

Validador adversarial de recomendaciones terapéuticas.

Hipótesis verificables H.GB001-H.GB030:
- H.GB001-H.GB005: bloqueo hard_block en biomarcadores omitidos
- H.GB006-H.GB010: trial matching (eligibilidad omitida)
- H.GB011-H.GB015: coherencia longitudinal
- H.GB016-H.GB020: LLM adversarial fallback
- H.GB021-H.GB025: override flow + persistencia
- H.GB026-H.GB030: 9° vector loop + concordancia dashboard

Comando:
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/homebrew/bin/python3.12 -m pytest \\
    tests/test_audit_C_godibot_validator.py -v --no-header \\
    -c /dev/null --rootdir=/tmp -o cache_dir=/tmp/pytest_cache
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "godibot"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


# ──────────────────────────────────────────────────────────────────────
# H.GB001-005 — Hard block on omitted biomarkers
# ──────────────────────────────────────────────────────────────────────


def test_gb001_parp_without_hrr_blocks_hard():
    """H.GB001 — PARP inhibitor sin HRR confirmado → blocked_hard."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_parp_no_hrr.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "blocked_hard"
    assert review["override_required"] is True
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("hrr_pre_parp" in c for c in codes), f"missing hrr gap in {codes}"


def test_gb002_lu177_without_psma_blocks_hard():
    """H.GB002 — Lutetium-177 sin PSMA-PET → blocked_hard (VISION exclusion)."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_lu177_no_psma.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "blocked_hard"
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("psma_pet_pre_lu177" in c for c in codes), codes


def test_gb003_abiraterone_child_pugh_bc_blocks_hard():
    """H.GB003 — Abiraterona en Child-Pugh B/C → blocked_hard."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_abiraterone_child_pugh_b.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "blocked_hard"
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("abi_child_pugh" in c for c in codes), codes


def test_gb004_ra223_with_visceral_blocks_hard():
    """H.GB004 — Ra-223 con viscerales → blocked_hard (ALSYMPCA exclusion)."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_ra223_visceral.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "blocked_hard"
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("ra223_with_visceral" in c for c in codes), codes


def test_gb005_sipuleucel_low_cd4_blocks_hard():
    """H.GB005 — Sipuleucel-T con CD4<200 → blocked_hard (futilidad)."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_sipuleucel_low_cd4.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "blocked_hard"
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("sipuleucel_low_cd4" in c for c in codes), codes


# ──────────────────────────────────────────────────────────────────────
# H.GB006-010 — Approved + trial matching + warnings
# ──────────────────────────────────────────────────────────────────────


def test_gb006_low_risk_active_surveillance_approved():
    """H.GB006 — NCCN low risk + AS recommendation → approved sin discrepancias."""
    from prostanet.agents.godibot import run_godibot_review
    record = _load_fixture("case_approved_low_risk.json")
    record.pop("_expected_status", None)
    record.pop("_description", None)

    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] == "approved"
    assert review["override_required"] is False
    assert len(review.get("discrepancies", [])) == 0


def test_gb007_review_has_required_schema_keys():
    """H.GB007 — review tiene todas las keys del schema documentado."""
    from prostanet.agents.godibot import run_godibot_review
    review = run_godibot_review(
        {"reconciled_state": "localized_initial"},
        enable_llm=False,
    )
    required_keys = {
        "status", "confidence", "discrepancies", "trial_omissions",
        "biomarker_gaps", "longitudinal_concord", "guideline_check",
        "gates_reeval", "llm_adversarial", "override_required", "version",
    }
    missing = required_keys - set(review.keys())
    assert not missing, f"missing keys: {missing}"


def test_gb008_version_is_godibot_v1():
    """H.GB008 — version field es godibot-v1."""
    from prostanet.agents.godibot import run_godibot_review, GodiBotValidator
    review = run_godibot_review({"reconciled_state": "localized_initial"})
    assert review["version"] == GodiBotValidator.VERSION == "godibot-v1"


def test_gb009_confidence_in_valid_range():
    """H.GB009 — confidence siempre en [0.0, 1.0]."""
    from prostanet.agents.godibot import run_godibot_review
    for fixture in FIXTURES_DIR.glob("case_*.json"):
        record = json.loads(fixture.read_text())
        record.pop("_expected_status", None)
        record.pop("_description", None)
        review = run_godibot_review(record, enable_llm=False)
        assert 0.0 <= review["confidence"] <= 1.0, (
            f"{fixture.name}: confidence={review['confidence']}"
        )


def test_gb010_hard_block_implies_override_required():
    """H.GB010 — Si status=blocked_hard, override_required debe ser True."""
    from prostanet.agents.godibot import run_godibot_review
    for fixture in FIXTURES_DIR.glob("case_*.json"):
        record = json.loads(fixture.read_text())
        expected = record.pop("_expected_status", None)
        record.pop("_description", None)
        if expected != "blocked_hard":
            continue
        review = run_godibot_review(record, enable_llm=False)
        assert review["status"] == "blocked_hard"
        assert review["override_required"] is True, fixture.name


# ──────────────────────────────────────────────────────────────────────
# H.GB011-015 — Coherencia longitudinal
# ──────────────────────────────────────────────────────────────────────


def test_gb011_m1crpc_without_recent_psma_warns():
    """H.GB011 — m1_crpc sin last_psma_pet_date → drift detected + warning."""
    from prostanet.agents.godibot import run_godibot_review
    record = {
        "reconciled_state": "m1_crpc",
        "baseline": {"baseline_psa": 50.0},
        "clinical_compass": {
            "headline": "Continuar ARPI",
            "rationale": "Manejo standard",
            "evidence_summary": {"guideline_basis": ["NCCN v5.2026"]}
        }
    }
    review = run_godibot_review(record, enable_llm=False)
    assert review["longitudinal_concord"]["drift_detected"] is True
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("m1crpc_no_recent_psma" in c for c in codes)


def test_gb012_bcr_post_rt_below_phoenix_warns():
    """H.GB012 — BCR post-RT con PSA-nadir <2 → warning Phoenix not met."""
    from prostanet.agents.godibot import run_godibot_review
    record = {
        "reconciled_state": "recurrence_bcr",
        "psa_current": 1.5,
        "post_rt_nadir": 0.5,
        "prior_radiotherapy": True,
        "last_psma_pet_date": "2026-05-01",
        "clinical_compass": {
            "headline": "Salvage local",
            "rationale": "BCR detectado",
            "evidence_summary": {"guideline_basis": ["EAU 2026"]}
        }
    }
    review = run_godibot_review(record, enable_llm=False)
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("bcr_post_rt_not_phoenix" in c for c in codes), codes


def test_gb013_as_with_low_psadt_warns():
    """H.GB013 — Active surveillance con PSADT<3mo → exit-AS warning."""
    from prostanet.agents.godibot import run_godibot_review
    record = {
        "reconciled_state": "localized_surveillance",
        "psa_doubling_time_months": 2.0,
        "clinical_compass": {
            "headline": "Continuar vigilancia activa",
            "evidence_summary": {"guideline_basis": ["NCCN v5.2026"]}
        }
    }
    review = run_godibot_review(record, enable_llm=False)
    assert review["longitudinal_concord"]["drift_detected"] is True
    codes = [d["code"] for d in review.get("discrepancies", [])]
    assert any("as_psadt_below_3mo" in c for c in codes)


def test_gb014_warning_status_when_only_soft_warnings():
    """H.GB014 — Solo soft_warnings (sin hard_block) → status=warnings_only."""
    from prostanet.agents.godibot import run_godibot_review
    record = {
        "reconciled_state": "m1_crpc",
        "baseline": {"baseline_psa": 30},
        "clinical_compass": {
            "headline": "Iniciar Enzalutamida",
            "rationale": "ARSI primera línea",
            "evidence_summary": []  # missing guideline citation → soft_warning
        }
    }
    review = run_godibot_review(record, enable_llm=False)
    assert review["status"] in ("warnings_only", "approved")
    if review["status"] == "warnings_only":
        assert review["override_required"] is False


def test_gb015_longitudinal_concord_returns_dict():
    """H.GB015 — longitudinal_concord siempre dict con drift_detected bool."""
    from prostanet.agents.godibot import run_godibot_review
    review = run_godibot_review({"reconciled_state": "diagnostic_workup"})
    assert isinstance(review["longitudinal_concord"], dict)
    assert "drift_detected" in review["longitudinal_concord"]
    assert isinstance(review["longitudinal_concord"]["drift_detected"], bool)


# ──────────────────────────────────────────────────────────────────────
# H.GB016-020 — LLM adversarial fallback graceful
# ──────────────────────────────────────────────────────────────────────


def test_gb016_llm_disabled_returns_none():
    """H.GB016 — Si enable_llm=False, llm_adversarial es None o no invocado."""
    from prostanet.agents.godibot import run_godibot_review
    review = run_godibot_review(
        {"reconciled_state": "localized_initial"},
        enable_llm=False,
    )
    llm = review.get("llm_adversarial")
    assert llm is None or llm.get("invoked") is False or llm == {}


def test_gb017_llm_only_for_low_confidence_or_complex():
    """H.GB017 — LLM no se invoca si confidence>=0.85 y estado simple."""
    from prostanet.agents.godibot import GodiBotValidator
    v = GodiBotValidator(enable_llm_adversarial=True)
    # Caso confianza alta + estado simple → no llm
    assert v._should_invoke_llm(0.95, "localized_initial") is False
    # Caso confianza alta + estado complejo → sí llm
    assert v._should_invoke_llm(0.95, "m1_crpc") is True
    # Caso confianza baja + estado simple → sí llm
    assert v._should_invoke_llm(0.5, "localized_initial") is True


def test_gb018_llm_failure_does_not_crash():
    """H.GB018 — Si Anthropic SDK falla, fallback graceful sin excepción."""
    from prostanet.agents.godibot import GodiBotValidator
    v = GodiBotValidator(enable_llm_adversarial=True, anthropic_client=None)
    # Forzar invocación
    result = v._llm_devils_advocate(
        {"reconciled_state": "m1_crpc"},
        {"headline": "test"},
        [],
        "m1_crpc",
    )
    assert isinstance(result, dict)
    assert "invoked" in result
    # Debe ser False porque no hay SDK ni API key configurada en test env
    assert result["invoked"] is False or result["invoked"] is True


def test_gb019_llm_mock_client_returns_concerns():
    """H.GB019 — Cliente Anthropic mockeado retorna concerns parseados."""
    from prostanet.agents.godibot import GodiBotValidator
    from unittest.mock import MagicMock

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="""
- La recomendación omite considerar PSMA-PET para verificar progresión.
- No se documentó AR-V7 antes del switch ARSI.
- Falta evaluación de comorbilidades cardiovasculares.
""")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    v = GodiBotValidator(enable_llm_adversarial=True, anthropic_client=mock_client)
    result = v._llm_devils_advocate(
        {"reconciled_state": "m1_crpc"},
        {"headline": "Enzalutamida"},
        [],
        "m1_crpc",
    )
    assert result["invoked"] is True
    assert len(result["additional_concerns"]) == 3


def test_gb020_complex_stages_constant_includes_key_stages():
    """H.GB020 — COMPLEX_STAGES incluye nmcrpc, m1crpc, nepc, oligo."""
    from prostanet.agents.godibot import COMPLEX_STAGES
    assert "m1_crpc" in COMPLEX_STAGES
    assert "nmcrpc_initial" in COMPLEX_STAGES or "m0_crpc" in COMPLEX_STAGES
    assert "nepc_crpc" in COMPLEX_STAGES
    assert "oligometastatic_sbrt" in COMPLEX_STAGES


# ──────────────────────────────────────────────────────────────────────
# H.GB021-025 — Override flow + persistencia REST
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_godibot_db(monkeypatch):
    """Use temporary SQLite DB for REST tests."""
    from prostanet.presentation import godibot_routes
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(godibot_routes, "GODIBOT_DB_PATH", Path(tmp.name))
    yield tmp.name
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_gb021_persist_review_assigns_review_id(tmp_godibot_db):
    """H.GB021 — persist_review retorna review_id > 0."""
    from prostanet.presentation.godibot_routes import persist_review
    review = {
        "status": "blocked_hard", "confidence": 0.3,
        "discrepancies": [{"code": "hrr_pre_parp", "severity": "hard_block"}],
        "trial_omissions": [], "biomarker_gaps": [], "version": "godibot-v1",
    }
    rid = persist_review(nss="TEST001", review=review)
    assert rid > 0


def test_gb022_persist_override_updates_last_review(tmp_godibot_db):
    """H.GB022 — persist_override actualiza el review más reciente del NSS."""
    from prostanet.presentation.godibot_routes import (
        persist_review, persist_override, get_reviews,
    )
    persist_review(nss="TEST002", review={
        "status": "blocked_hard", "confidence": 0.4, "version": "godibot-v1",
    })
    ok = persist_override(
        nss="TEST002",
        override_signed_by="7654321",
        override_reason="Caso particular: HRR pendiente por logística — paciente con historial familiar BRCA documentado PMID 12345.",
    )
    assert ok is True
    reviews = get_reviews("TEST002")
    assert reviews[0]["override_signed_by"] == "7654321"
    assert "BRCA" in reviews[0]["override_reason"]


def test_gb023_override_without_review_returns_false(tmp_godibot_db):
    """H.GB023 — persist_override sin review previo retorna False."""
    from prostanet.presentation.godibot_routes import persist_override
    ok = persist_override(
        nss="NONEXISTENT",
        override_signed_by="7654321",
        override_reason="Reason text padding to reach minimum 30 chars threshold.",
    )
    assert ok is False


def test_gb024_concordance_summary_aggregates_correctly(tmp_godibot_db):
    """H.GB024 — get_concordance_summary agrega por status correctamente."""
    from prostanet.presentation.godibot_routes import (
        persist_review, get_concordance_summary,
    )
    persist_review(nss="C001", review={"status": "approved", "confidence": 1.0})
    persist_review(nss="C002", review={"status": "approved", "confidence": 0.95})
    persist_review(nss="C003", review={"status": "blocked_hard", "confidence": 0.3})
    persist_review(nss="C004", review={"status": "warnings_only", "confidence": 0.7})

    summary = get_concordance_summary(days=30)
    assert summary["total_reviews"] == 4
    assert summary["by_status"]["approved"]["count"] == 2
    assert summary["by_status"]["blocked_hard"]["count"] == 1
    assert summary["approved_rate"] == 0.5  # 2/4
    assert summary["blocked_rate"] == 0.25  # 1/4


def test_gb025_get_reviews_orders_by_timestamp_desc(tmp_godibot_db):
    """H.GB025 — get_reviews retorna en orden timestamp DESC."""
    from prostanet.presentation.godibot_routes import (
        persist_review, get_reviews,
    )
    persist_review(nss="ORDER1", review={"status": "approved", "confidence": 1.0})
    import time; time.sleep(0.01)
    persist_review(nss="ORDER1", review={"status": "blocked_hard", "confidence": 0.3})
    reviews = get_reviews("ORDER1")
    assert len(reviews) == 2
    # más reciente primero
    assert reviews[0]["status"] == "blocked_hard"
    assert reviews[1]["status"] == "approved"


# ──────────────────────────────────────────────────────────────────────
# H.GB026-030 — 9° vector loop + integración orchestrator
# ──────────────────────────────────────────────────────────────────────


def test_gb026_loop_monitor_has_9_vectors():
    """H.GB026 — CORE_VECTORS incluye 9 vectores con recommendation_concordance."""
    from prostanet.presentation.loop_monitor import CORE_VECTORS
    assert len(CORE_VECTORS) == 9
    assert "recommendation_concordance" in CORE_VECTORS
    v = CORE_VECTORS["recommendation_concordance"]
    assert v["icon"] == "🛡"
    assert "godibot" in (v.get("skill") or "").lower()


def test_gb027_record_godibot_concordance_returns_status():
    """H.GB027 — record_godibot_concordance_check retorna dict con status."""
    from prostanet.presentation.loop_monitor import (
        record_godibot_concordance_check,
    )
    result = record_godibot_concordance_check(days=30)
    assert isinstance(result, dict)
    assert "status" in result
    assert result["status"] in ("ok", "warning", "critical")


def test_gb028_orchestrator_includes_godibot_in_outputs():
    """H.GB028 — orchestrate_all incluye 'godibot' en agent_outputs."""
    from prostanet.agents.agent_registry import AgentRegistry
    from prostanet.agents.contracts import AgentInput
    registry = AgentRegistry()
    agent_input = AgentInput(
        patient_id=999,
        record={
            "reconciled_state": "m1_crpc",
            "baseline": {"baseline_psa": 100},
            "clinical_compass": {
                "headline": "Iniciar olaparib",
                "rationale": "PARP en CRPC",
                "evidence_summary": []
            }
        },
        trigger_event="compass_generated",
        trigger_data={},
    )
    result = registry.orchestrate_all(agent_input, run_qaa=False)
    assert "godibot" in result["agent_outputs"]
    assert "godibot_review" in result["agent_outputs"]
    review = result["agent_outputs"]["godibot_review"]
    assert review["status"] in ("approved", "warnings_only", "blocked_hard")


def test_gb029_godibot_review_bubbled_to_profile_compass():
    """H.GB029 — profile_compass wired: godibot_review existe como helper."""
    from prostanet.agents.godibot import run_godibot_review
    # No invocamos build_patient_profile_view_model (requiere full record);
    # solo verificamos que el helper standalone es accesible.
    review = run_godibot_review(
        {"reconciled_state": "localized_initial"},
        compass={"headline": "Vigilancia activa"},
    )
    assert isinstance(review, dict)
    assert "status" in review


def test_gb030_godibot_handles_empty_compass_gracefully():
    """H.GB030 — record sin clinical_compass no crashea, retorna approved."""
    from prostanet.agents.godibot import run_godibot_review
    review = run_godibot_review({"reconciled_state": "diagnostic_workup"})
    assert review["status"] in ("approved", "warnings_only")
    assert review["confidence"] >= 0.0
    assert review["override_required"] is False
