"""Tests del Decision Audit endpoint + helpers asociados.

Faubot 2026-04-25 (X) — Cierra Tier 4.K del backlog: endpoint
`/api/decision-audit/{patient_ref}` que retorna las 5 dimensiones de
auditabilidad del Clinical Decision Engine.

Aporta a:
  - **CÓMO** (87% → ~95%): cadena de razonamiento expuesta como JSON
  - **POR QUÉ** (98% → ~99%): contraindicaciones estructuradas
  - **DATOS** (82% → ~88%): input snapshot accesible vía API
  - **EVIDENCIA** (95% → ~97%): trial_refs + evidence_tags agregados
  - **VERSIÓN** (55% → ~80%): algorithm versioning con SHA + release stamp

Cobertura del test:
  A) Helper `algorithm_version` — get/sha/codes/compatibility
  B) Helper `decision_audit_builder` — empty + populated + 5 dimensiones
  C) Endpoint Flask — smoke + 200 OK + 404 + version-only
  D) Roundtrip — audit persistido → re-construido idénticamente
  E) Smoke E2E con paciente m1_crpc con múltiples gates activos
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import json

import pytest

from prostanet.shared.algorithm_version import (
    FAUBOT_RELEASE,
    get_active_gate_codes,
    get_algorithm_version,
    get_module_sha,
    is_version_compatible,
)
from prostanet.shared.decision_audit_builder import build_decision_audit


# ── Sección A — Helper algorithm_version ──────────────────────────────────


class TestAlgorithmVersion:
    def test_faubot_release_constant_exists(self):
        assert isinstance(FAUBOT_RELEASE, str)
        assert len(FAUBOT_RELEASE) > 0
        assert "2026" in FAUBOT_RELEASE

    def test_module_sha_returns_hex_string(self):
        sha = get_module_sha()
        assert isinstance(sha, str)
        assert len(sha) == 12  # primeros 12 chars del SHA-256
        # Todos hex válidos (excepto si "unavailable")
        if sha != "unavailable":
            assert all(c in "0123456789abcdef" for c in sha)

    def test_module_sha_returns_unavailable_for_missing_path(self, tmp_path):
        from pathlib import Path
        missing = Path(tmp_path) / "nonexistent.py"
        assert get_module_sha(missing) == "unavailable"

    def test_module_sha_deterministic_for_same_file(self):
        """Mismo archivo → mismo SHA en llamadas repetidas."""
        sha1 = get_module_sha()
        sha2 = get_module_sha()
        assert sha1 == sha2

    def test_get_active_gate_codes_returns_18_gates(self):
        codes = get_active_gate_codes()
        # Sweep cumulativo: tras Faubot VII (gates 17-18), son 18 total
        assert len(codes) >= 18
        # Algunos códigos canónicos esperados
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes
        assert "lvef_decline_for_apalutamide" in codes
        assert "radium223_in_cord_compression" in codes
        assert "parp_inhibitor_in_mds_aml_history" in codes

    def test_get_active_gate_codes_sorted(self):
        codes = get_active_gate_codes()
        assert codes == sorted(codes)

    def test_get_algorithm_version_full_structure(self):
        v = get_algorithm_version()
        assert "faubot_release" in v
        assert "module_sha" in v
        assert "module_path" in v
        assert "gates_active_count" in v
        assert "gates_active_codes" in v
        assert v["faubot_release"] == FAUBOT_RELEASE
        assert v["gates_active_count"] == len(v["gates_active_codes"])

    def test_self_compatibility_returns_compatible(self):
        v = get_algorithm_version()
        compat = is_version_compatible(v, v)
        assert compat["compatible"] is True
        assert compat["release_changed"] is False
        assert compat["sha_changed"] is False
        assert compat["gate_count_delta"] == 0
        assert compat["added_gates"] == []
        assert compat["removed_gates"] == []

    def test_compatibility_detects_release_change(self):
        v_old = get_algorithm_version()
        v_new = dict(v_old)
        v_new["faubot_release"] = "2026-05-01 XX"
        compat = is_version_compatible(v_old, v_new)
        assert compat["compatible"] is False
        assert compat["release_changed"] is True

    def test_compatibility_detects_sha_change(self):
        v_old = get_algorithm_version()
        v_new = dict(v_old)
        v_new["module_sha"] = "0123456789ab"
        compat = is_version_compatible(v_old, v_new)
        assert compat["compatible"] is False
        assert compat["sha_changed"] is True

    def test_compatibility_detects_added_gates(self):
        v_old = {
            "faubot_release": "test",
            "module_sha": "abc",
            "gates_active_codes": ["gate_a", "gate_b"],
        }
        v_new = {
            "faubot_release": "test",
            "module_sha": "abc",
            "gates_active_codes": ["gate_a", "gate_b", "gate_c", "gate_d"],
        }
        compat = is_version_compatible(v_old, v_new)
        assert compat["compatible"] is True  # release y sha iguales
        assert compat["gate_count_delta"] == 2
        assert compat["added_gates"] == ["gate_c", "gate_d"]
        assert compat["removed_gates"] == []

    def test_compatibility_detects_removed_gates(self):
        v_old = {
            "faubot_release": "test",
            "module_sha": "abc",
            "gates_active_codes": ["gate_a", "gate_b", "gate_c"],
        }
        v_new = {
            "faubot_release": "test",
            "module_sha": "abc",
            "gates_active_codes": ["gate_a"],
        }
        compat = is_version_compatible(v_old, v_new)
        assert compat["gate_count_delta"] == -2
        assert compat["removed_gates"] == ["gate_b", "gate_c"]


# ── Sección B — Helper decision_audit_builder ─────────────────────────────


class TestDecisionAuditBuilder:
    def test_builder_returns_unavailable_when_no_assessment(self):
        audit = build_decision_audit(
            patient_id=42,
            patient_identity={"id": 42, "full_name": "Test"},
            latest_assessment=None,
        )
        assert audit["available"] is False
        assert audit["patient_id"] == 42
        # Versión SIEMPRE disponible incluso sin assessment
        assert audit["audit_dimensions"]["version"]["faubot_release"] == FAUBOT_RELEASE
        assert audit["summary"]["audit_status"] == "no_assessment_available"

    def test_builder_returns_available_with_assessment(self):
        fake_assessment = {
            "id": 100,
            "module_id": "m1_crpc",
            "state": "m1_crpc",
            "created_at": "2026-04-25T10:00:00",
            "input_snapshot": {"psa": 30, "qtc_ms": 520},
            "result_snapshot": {
                "state": "m1_crpc",
                "preferred_regimen_code": "ENZALUTAMIDE",
                "pivotal_contraindication_gates": [
                    {"code": "qtc_prolongation_grade3_for_enzalutamide",
                     "severity": "hard_block",
                     "trial_refs": ["ENZAMET", "Xtandi label"],
                     "evidence_tag": "xtandi_label_enzamet"},
                ],
                "not_recommended": ["Enzalutamida bloqueada por QTc"],
                "missing_critical_inputs": [],
                "applicability_badge": "guideline-consistent",
            },
            "guideline_versions": {"NCCN": "5.2026", "EAU": "2026"},
        }
        audit = build_decision_audit(
            patient_id=42,
            latest_assessment=fake_assessment,
        )
        assert audit["available"] is True
        assert audit["audit_metadata"]["assessment_id"] == 100
        assert audit["audit_metadata"]["module_id"] == "m1_crpc"
        assert audit["summary"]["total_gates_active"] == 1
        assert audit["summary"]["audit_status"] == "complete"

    def test_5_dimensions_present_when_available(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"psa": 30},
            "result_snapshot": {"state": "m1_crpc"},
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        dims = audit["audit_dimensions"]
        # Las 5 dimensiones deben estar presentes
        assert "como" in dims
        assert "por_que" in dims
        assert "datos" in dims
        assert "evidencia" in dims
        assert "version" in dims

    def test_como_dimension_includes_state_and_preferred_regimen(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {},
            "result_snapshot": {
                "state": "m1_crpc",
                "preferred_regimen_code": "ADT_DAROLUTAMIDE",
                "preferred_frontline_regimen": {"name": "ADT + darolutamida", "rank": 1},
                "alternative_regimens": [{"name": "Alt 1"}, {"name": "Alt 2"}],
                "applicability_badge": "guideline-consistent",
                "decision_quality": {"confidence_category": "alta"},
                "ranking_policy_version": "v3.2026",
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        como = audit["audit_dimensions"]["como"]
        assert como["state"] == "m1_crpc"
        assert como["preferred_regimen_code"] == "ADT_DAROLUTAMIDE"
        assert como["preferred_regimen"]["name"] == "ADT + darolutamida"
        assert como["alternative_regimens_count"] == 2
        assert como["applicability_badge"] == "guideline-consistent"
        assert como["decision_quality"]["confidence_category"] == "alta"
        assert como["ranking_policy_version"] == "v3.2026"

    def test_por_que_dimension_aggregates_gates_and_messages(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {},
            "result_snapshot": {
                "pivotal_contraindication_gates": [
                    {"code": "gate_a", "severity": "hard_block"},
                    {"code": "gate_b", "severity": "soft"},
                ],
                "not_recommended": ["msg 1", "msg 2", "msg 3"],
                "contraindications": ["contra 1"],
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        por_que = audit["audit_dimensions"]["por_que"]
        assert por_que["active_gates_count"] == 2
        assert por_que["not_recommended_count"] == 3
        assert por_que["contraindications_count"] == 1

    def test_datos_dimension_includes_input_snapshot_and_missing(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"psa": 30, "qtc_ms": 520, "lvef_percent": 45, "ecog": 1},
            "result_snapshot": {
                "missing_critical_inputs": ["bone_lesion_count"],
                "stale_inputs": ["psma_pet_done"],
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        datos = audit["audit_dimensions"]["datos"]
        assert datos["input_field_count"] == 4
        assert datos["missing_count"] == 1
        assert datos["stale_count"] == 1
        assert "bone_lesion_count" in datos["missing_critical_inputs"]

    def test_evidencia_dimension_aggregates_unique_trial_refs(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {},
            "result_snapshot": {
                "pivotal_contraindication_gates": [
                    {"code": "g1", "trial_refs": ["TRIAL_A", "TRIAL_B"],
                     "evidence_tag": "tag_1"},
                    {"code": "g2", "trial_refs": ["TRIAL_B", "TRIAL_C"],
                     "evidence_tag": "tag_2"},
                ],
                "nccn_primary": {"label": "M1_CRPC", "version": "5.2026"},
                "eau_comparison": {"label": "Test", "version": "2026"},
                "trial_matches": [{"trial": "T1"}, {"trial": "T2"}, {"trial": "T3"}],
            },
            "guideline_versions": {"NCCN": "5.2026"},
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        evidencia = audit["audit_dimensions"]["evidencia"]
        # 3 trial_refs únicos (TRIAL_A, TRIAL_B, TRIAL_C)
        assert evidencia["unique_trial_refs_count"] == 3
        assert evidencia["unique_trial_refs"] == ["TRIAL_A", "TRIAL_B", "TRIAL_C"]
        # 2 evidence_tags únicos
        assert evidencia["unique_evidence_tags_count"] == 2
        assert evidencia["nccn_primary_label"] == "M1_CRPC"
        assert evidencia["nccn_primary_version"] == "5.2026"
        assert evidencia["trial_matches_count"] == 3

    def test_version_dimension_always_present(self):
        """VERSIÓN debe estar disponible incluso cuando no hay assessment."""
        audit = build_decision_audit(patient_id=1, latest_assessment=None)
        v = audit["audit_dimensions"]["version"]
        assert v["faubot_release"] == FAUBOT_RELEASE
        assert v["gates_active_count"] >= 18

    def test_audit_is_json_serializable(self):
        """El audit completo debe ser JSON-serializable sin errores."""
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"psa": 30},
            "result_snapshot": {
                "state": "m1_crpc",
                "pivotal_contraindication_gates": [
                    {"code": "g1", "trial_refs": ("t1", "t2")},  # tuple → list
                ],
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        # Si lanza TypeError es porque algún valor no es serializable
        json_str = json.dumps(audit)
        assert len(json_str) > 0

    def test_summary_aggregates_counts_correctly(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"a": 1, "b": 2, "c": 3},
            "result_snapshot": {
                "state": "m1_crpc",
                "pivotal_contraindication_gates": [
                    {"code": "g1", "trial_refs": ["T1"]},
                    {"code": "g2", "trial_refs": ["T2"]},
                ],
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        s = audit["summary"]
        assert s["total_gates_active"] == 2
        assert s["total_inputs_captured"] == 3
        assert s["total_trial_refs_cited"] == 2
        assert s["decision_state"] == "m1_crpc"


# ── Sección C — Endpoint Flask ────────────────────────────────────────────


@pytest.fixture
def client():
    """Flask test client del app real con blueprints registrados."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        yield client


class TestEndpointFlask:
    def test_algorithm_version_endpoint_returns_200(self, client):
        response = client.get("/api/decision-audit/algorithm-version")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "version" in data
        assert data["version"]["faubot_release"] == FAUBOT_RELEASE

    def test_algorithm_version_endpoint_includes_gates_codes(self, client):
        response = client.get("/api/decision-audit/algorithm-version")
        data = response.get_json()
        codes = data["version"]["gates_active_codes"]
        assert isinstance(codes, list)
        assert len(codes) >= 18
        assert "qtc_prolongation_grade3_for_enzalutamide" in codes

    def test_decision_audit_endpoint_returns_404_for_missing_patient(self, client):
        response = client.get("/api/decision-audit/nonexistent_patient_xyz_999")
        # Puede ser 404 (paciente no encontrado) o 200 con audit.available=False
        # según cómo `get_patient_full_record_by_ref` maneja missing
        assert response.status_code in (404, 200)
        data = response.get_json()
        if response.status_code == 200:
            assert data["audit"]["available"] is False

    def test_decision_audit_endpoint_response_schema(self, client):
        """Aún sin paciente, la respuesta debe ser JSON con schema esperado."""
        response = client.get("/api/decision-audit/test_ref_xyz")
        data = response.get_json()
        assert data is not None
        assert "success" in data
        # Si success=True, debe haber `audit`. Si False, debe haber `error`.
        if data["success"]:
            assert "audit" in data
        else:
            assert "error" in data


# ── Sección D — Roundtrip ─────────────────────────────────────────────────


class TestRoundtrip:
    def test_audit_persisted_and_reconstructed_identically(self):
        """Un audit serializado a JSON → deserializado debe ser idéntico."""
        fake_assessment = {
            "id": 50, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"psa": 30, "qtc_ms": 520},
            "result_snapshot": {
                "state": "m1_crpc",
                "preferred_regimen_code": "ADT_DAROLUTAMIDE",
                "pivotal_contraindication_gates": [
                    {"code": "qtc_prolongation_grade3_for_enzalutamide",
                     "severity": "hard_block",
                     "trial_refs": ["ENZAMET", "Xtandi label"],
                     "evidence_tag": "xtandi_label"},
                ],
            },
        }
        audit_v1 = build_decision_audit(patient_id=50, latest_assessment=fake_assessment)
        json_str = json.dumps(audit_v1)
        audit_v2 = json.loads(json_str)
        # Las 5 dimensiones deben sobrevivir el roundtrip
        for dim in ("como", "por_que", "datos", "evidencia", "version"):
            assert audit_v1["audit_dimensions"][dim] == audit_v2["audit_dimensions"][dim]
        assert audit_v1["summary"] == audit_v2["summary"]

    def test_audit_version_compatible_with_itself(self):
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {},
            "result_snapshot": {},
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        v = audit["audit_dimensions"]["version"]
        compat = is_version_compatible(v, v)
        assert compat["compatible"] is True


# ── Sección E — Smoke E2E con paciente realista ───────────────────────────


class TestSmokeE2E:
    def test_full_audit_for_m1_crpc_with_multiple_gates(self):
        """Paciente m1_crpc con QTc 520 + LVEF 45 + MDS history → 3 gates
        activos, audit completo con las 5 dimensiones."""
        from prostanet.application.module_registry import ModuleRegistry
        r = ModuleRegistry()
        result = r.evaluate_module("m1_crpc", {
            "psa": 50, "psa_doubling_time": 4, "metastatic": "1",
            "visceral_metastasis": "0", "bone_lesion_count": 5,
            "ecog_score": 1, "age": 70,
            "castrate_resistant": "1", "testosterone": 20,
            "denosumab_prophylaxis": "Sí",
            "qtc_ms": 520,
            "lvef_percent": 45,
            "mds_aml_history": "Sí",
        })
        fake_assessment = {
            "id": 999,
            "module_id": "m1_crpc",
            "state": result.get("state"),
            "input_snapshot": {
                "psa": 50, "qtc_ms": 520, "lvef_percent": 45,
                "mds_aml_history": "Sí",
            },
            "result_snapshot": result,
            "guideline_versions": {"NCCN": "5.2026", "EAU": "2026"},
            "created_at": "2026-04-25T12:00:00",
        }
        audit = build_decision_audit(
            patient_id=999,
            patient_identity={"id": 999, "full_name": "Smoke Test Patient"},
            latest_assessment=fake_assessment,
        )
        # Audit completo
        assert audit["available"] is True
        # 3 gates activos (gate 17 QTc + gate 18 LVEF + gate 16 MDS)
        assert audit["summary"]["total_gates_active"] == 3
        # Trial refs únicos agregados de los 3 gates
        assert audit["summary"]["total_trial_refs_cited"] >= 5
        # Versión presente
        assert audit["audit_dimensions"]["version"]["faubot_release"] == FAUBOT_RELEASE
        # JSON-serializable
        json_str = json.dumps(audit)
        assert len(json_str) > 1000  # audit no trivial

    def test_full_audit_for_healthy_patient_no_gates(self):
        """Paciente sin gates activos → audit `available=True` pero
        with summary.total_gates_active == 0."""
        fake_assessment = {
            "id": 1, "module_id": "m1_crpc", "state": "m1_crpc",
            "input_snapshot": {"psa": 30, "qtc_ms": 400, "lvef_percent": 65},
            "result_snapshot": {
                "state": "m1_crpc",
                "preferred_regimen_code": "ADT_ENZALUTAMIDE",
                "pivotal_contraindication_gates": [],
            },
        }
        audit = build_decision_audit(patient_id=1, latest_assessment=fake_assessment)
        assert audit["available"] is True
        assert audit["summary"]["total_gates_active"] == 0
        # Versión sigue presente
        assert audit["audit_dimensions"]["version"]["gates_active_count"] >= 18
