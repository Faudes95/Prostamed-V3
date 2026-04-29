# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import logging
from pathlib import Path


def make_patient_payload(nss="AI-TEST-001", full_name="Paciente AI Seguro"):
    return {
        "nss": nss,
        "full_name": full_name,
        "dob": "1964-05-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 9.2,
        "testosterone_baseline": 330,
    }


def _seed_latest_assessment_state(db_path, patient_id, state, module_id=None):
    import json
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO clinical_assessments (
            module_id, state, input_snapshot, result_snapshot, guideline_versions, status, patient_id
        ) VALUES (?, ?, ?, ?, ?, 'linked', ?)
        """,
        (
            module_id or state,
            state,
            json.dumps({}),
            json.dumps({}),
            json.dumps({}),
            patient_id,
        ),
    )
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        (state, patient_id),
    )
    conn.commit()
    conn.close()


def test_ai_models_endpoint_reports_runtime_mode_and_model_maturity(app_client):
    client, _ = app_client

    response = client.get("/api/ai/models")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["rule_based_source_of_truth"] is True
    assert payload["runtime_mode"] in {"shadow", "advisory"}
    assert payload["bootstrap_completed"] is True
    assert payload["loaded_model_count"] == 0
    assert payload["runtime_readiness"] == "not_ready"
    assert "state_transition" in payload["missing_model_ids"]
    assert payload["last_bootstrap_at"]
    assert "state_transition" in payload["models"]

    state_model = payload["models"]["state_transition"]
    assert state_model["maturity"] in {"not_loaded", "experimental", "shadow", "advisory"}
    assert state_model["validation_status"] in {
        "artifact_missing",
        "artifact_only",
        "registered",
        "provenance_ready",
        "validated",
    }


def test_ai_config_and_model_registry_share_default_model_dir():
    from prostanet.ai.config import get_ai_config
    from prostanet.ai.inference.model_registry import ModelRegistry

    config = get_ai_config()
    registry = ModelRegistry()

    assert Path(config.model_dir) == registry.models_dir


def test_confidence_weights_align_with_runtime_components():
    from prostanet.ai.config import CONFIDENCE_WEIGHTS
    from prostanet.engine.confidence_scoring import ConfidenceScorer

    scorer = ConfidenceScorer()
    result = scorer.score(record={})

    assert set(result["components"].keys()) == set(CONFIDENCE_WEIGHTS.keys())
    assert result["weights_used"] == CONFIDENCE_WEIGHTS


def test_state_prediction_endpoint_returns_model_status_when_unavailable(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="AI-TEST-002", full_name="Paciente Modelo Ausente")
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]

    response = client.post(f"/api/ai/predict/state-transition/{patient_id}", json={})
    assert response.status_code == 503

    body = response.get_json()
    assert body["success"] is False
    assert body["advisory_api"] is True
    assert body["rule_based_source_of_truth"] is True
    assert body["model_status"]["model_id"] == "state_transition"
    assert body["model_status"]["bootstrap_completed"] is True
    assert body["model_status"]["runtime_readiness"] == "not_ready"


def test_model_registry_missing_artifact_warns_only_once(tmp_path, caplog):
    from prostanet.ai.inference.model_registry import ModelRegistry

    ModelRegistry.reset_process_log_state()
    caplog.set_level(logging.DEBUG, logger="prostanet.ai.inference.model_registry")

    registry = ModelRegistry(models_dir=tmp_path)
    assert registry.load_model("state_transition") is False
    assert registry.load_model("state_transition") is False

    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "Model artifact not found" in record.message
    ]
    assert len(warnings) == 1


def test_runtime_model_registry_bootstraps_once_per_process(tmp_path, monkeypatch):
    from prostanet.ai.inference.model_registry import ModelRegistry
    from prostanet.ai.inference.runtime_registry import (
        get_runtime_model_registry,
        get_runtime_registry_health,
        reset_runtime_model_registry,
    )

    reset_runtime_model_registry()
    calls: list[str] = []
    original = ModelRegistry.load_all_available

    def tracked(self, device=None):
        calls.append(str(self.models_dir))
        return original(self, device=device)

    monkeypatch.setattr(ModelRegistry, "load_all_available", tracked)

    registry_a = get_runtime_model_registry(models_dir=tmp_path)
    registry_b = get_runtime_model_registry(models_dir=tmp_path)
    health = get_runtime_registry_health(registry=registry_b)

    assert registry_a is registry_b
    assert len(calls) == 1
    assert health["bootstrap_completed"] is True
    assert health["bootstrap_generation"] == 1
    assert health["loaded_model_count"] == 0


def test_runtime_model_registry_rebootstraps_when_artifact_appears(tmp_path, monkeypatch):
    from prostanet.ai.inference.model_registry import ModelRegistry
    from prostanet.ai.inference.runtime_registry import (
        get_runtime_model_registry,
        get_runtime_registry_health,
        reset_runtime_model_registry,
    )

    class FakeModel:
        def load(self, artifact_path, device=None):
            self.artifact_path = artifact_path
            self.device = device

        def eval(self):
            return None

    reset_runtime_model_registry()
    monkeypatch.setattr(
        ModelRegistry,
        "_instantiate_model",
        staticmethod(lambda _model_id: FakeModel()),
    )

    registry = get_runtime_model_registry(models_dir=tmp_path)
    initial_health = get_runtime_registry_health(registry=registry)
    assert initial_health["loaded_model_count"] == 0
    assert initial_health["runtime_readiness"] == "not_ready"

    artifact = tmp_path / "state_transition" / "best.pt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"fake-model")

    registry_after = get_runtime_model_registry(models_dir=tmp_path)
    health_after = get_runtime_registry_health(registry=registry_after)
    state_model = registry_after.get_metadata("state_transition")

    assert registry_after is registry
    assert health_after["bootstrap_generation"] == 2
    assert health_after["loaded_model_count"] >= 1
    assert health_after["runtime_readiness"] == "advisory_ready"
    assert state_model["artifact_exists"] is True
    assert state_model["loaded"] is True


def test_full_assessment_exposes_rule_based_and_ai_overlay_layers(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="AI-TEST-003", full_name="Paciente Overlay AI")
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.post(f"/api/ai/full-assessment/{payload['nss']}", json={})
    assert response.status_code == 200

    body = response.get_json()
    assert body["success"] is True
    assert body["rule_based_source_of_truth"] is True
    assert body["advisory_api"] is True
    assert body["runtime_mode"] in {"shadow", "advisory"}
    assert body["rule_based_recommendation"]["source"] == "rule_based_primary"
    assert "ai_advisory_overlay" in body
    assert "final_presented_recommendation" in body
    if body["runtime_mode"] == "shadow":
        assert body["final_presented_recommendation"]["source"] == "rule_based_primary"
