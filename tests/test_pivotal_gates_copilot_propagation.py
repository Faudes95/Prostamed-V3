"""Tests de propagación de `pivotal_contraindication_gates` y `not_recommended`
desde los servicios canónicos hasta los copilots de seguimiento.

Faubot 2026-04-24 (III) — Cierra la brecha B-1 detectada en la auditoría:
- Los 5 servicios mhspc/mcrpc + los 2 servicios localized/recurrence ya filtran
  `eligible_treatments` con `apply_pivotal_contraindication_gates`, pero solo
  `localized_initial` y `recurrence_bcr` exponen el rastro estructurado
  `pivotal_contraindication_gates` en el resultado.
- Los 4 copilots que consumen módulos con gates (mhspc, crpc, post_rp_salvage,
  localized_surveillance) silenciosamente caían `pivotal_contraindication_gates`
  y `not_recommended` al construir su bundle, dejando a la UI / auditoría sin
  trazabilidad sobre QUÉ régimen fue filtrado y POR QUÉ.

Estos tests cubren:
  1) Los 5 servicios mhspc/mcrpc exponen `pivotal_contraindication_gates` cuando
     un gate se dispara.
  2) Los 4 copilots propagan `pivotal_contraindication_gates` y `not_recommended`
     desde el `module_result` a su bundle final.
  3) Backward compatibility: pacientes sanos no producen entradas espurias
     ni alteran el contrato del bundle (claves siempre presentes con `[]`).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.mcspc_high_volume.service import (
    McspcHighVolumeService,
    McspcHighVolumeSyncService,
)
from prostanet.domains.mcspc_low_volume_sync_oligo.service import (
    McspcLowVolumeSyncOligoService,
)
from prostanet.domains.mcspc_oligo_metachronous.service import (
    McspcOligoMetachronousService,
)
from prostanet.domains.m1_crpc.service import M1CrpcService
from prostanet.domains.m0_crpc.service import M0CrpcService
from prostanet.domains.patient_tracking.crpc_copilot_service import (
    CRPCCopilotService,
)
from prostanet.domains.patient_tracking.localized_surveillance_copilot_service import (
    LocalizedSurveillanceCopilotService,
)
from prostanet.domains.patient_tracking.mhspc_copilot_service import (
    MhspcCopilotService,
)
from prostanet.domains.patient_tracking.post_rp_salvage_copilot_service import (
    PostRPSalvageCopilotService,
)


# ── Sección A — Exposición del rastro de gates en los 5 servicios mHSPC/mCRPC ──


def _hv_payload_nyha_iii(**overrides):
    base = {
        "psa": 50,
        "gleason_total": 9,
        "gleason_primary": 5,
        "gleason_secondary": 4,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 5,
        "metastatic_temporality": "synchronous",
        "volume_disease": "high",
        "nyha_class": "III",  # bloquea abiraterona
        "docetaxel_fit": "Yes",
        "ecog_score": 1,
        "age": 65,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "service_class",
    [
        McspcHighVolumeService,
        McspcHighVolumeSyncService,
    ],
)
def test_high_volume_services_expose_pivotal_gates_trace(service_class):
    svc = service_class()
    res = svc.evaluate(_hv_payload_nyha_iii())
    gates = res.get("pivotal_contraindication_gates") or []
    assert gates, f"{service_class.__name__} no expuso gates con NYHA III"
    codes = {g.get("code") for g in gates}
    assert "severe_heart_failure_nyha_iii_iv" in codes
    # Estructura completa del rastro
    g = next(g for g in gates if g.get("code") == "severe_heart_failure_nyha_iii_iv")
    for key in ("severity", "message", "evidence_tag", "trial_refs"):
        assert key in g, f"Falta clave {key} en rastro de gate"
    assert g["severity"] == "hard_block"
    assert "LATITUDE" in g["trial_refs"]


def test_low_volume_service_exposes_pivotal_gates_trace():
    svc = McspcLowVolumeSyncOligoService()
    payload = _hv_payload_nyha_iii(volume_disease="low", bone_lesion_count=1)
    res = svc.evaluate(payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert any(g.get("code") == "severe_heart_failure_nyha_iii_iv" for g in gates)


def test_oligo_metachronous_service_exposes_pivotal_gates_trace():
    svc = McspcOligoMetachronousService()
    payload = _hv_payload_nyha_iii(
        volume_disease="low",
        bone_lesion_count=2,
        metastatic_temporality="metachronous",
    )
    res = svc.evaluate(payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert any(g.get("code") == "severe_heart_failure_nyha_iii_iv" for g in gates)


def test_m1_crpc_service_exposes_pivotal_gates_trace():
    svc = M1CrpcService()
    payload = {
        "psa": 30,
        "psa_doubling_time": 5,
        "metastatic": "1",
        "visceral_metastasis": "0",
        "bone_lesion_count": 3,
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1",
        "testosterone": 20,
        "nyha_class": "IV",  # bloquea abiraterona en mCRPC también
    }
    res = svc.evaluate(payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert any(g.get("code") == "severe_heart_failure_nyha_iii_iv" for g in gates)


def test_m0_crpc_service_exposes_pivotal_gates_trace():
    svc = M0CrpcService()
    payload = {
        "psa": 5,
        "psa_doubling_time": 6,
        "metastatic": "0",
        "ecog_score": 1,
        "age": 72,
        "castrate_resistant": "1",
        "testosterone": 30,
        "darolutamide_hypersensitivity": "Sí",  # bloquea darolutamida
    }
    res = svc.evaluate(payload)
    gates = res.get("pivotal_contraindication_gates") or []
    assert any(g.get("code") == "darolutamide_hypersensitivity" for g in gates)


# ── Sección B — Propagación copilot (bundle activo) ───────────────────────────


def _emr_record_nyha_iii(**overrides):
    """Estructura EMR realista (no flat dict) que el copilot consume vía
    `merge_record_into_assessment_payload` → `build_runtime_payload`."""
    base = {
        "state": "mcspc_high_volume",
        "baseline": {
            "psa": 50,
            "gleason_total": 9,
            "gleason_primary": 5,
            "gleason_secondary": 4,
            "metastatic": "1",
            "visceral_metastasis": "0",
            "bone_lesion_count": 5,
            "metastatic_temporality": "synchronous",
            "volume_disease": "high",
            "nyha_class": "III",
            "docetaxel_fit": "Yes",
            "ecog_score": 1,
            "age": 65,
        },
        "longitudinal_truth_snapshot": {
            "field_values": {"nyha_class": "III"},
        },
    }
    base.update(overrides)
    return base


def test_mhspc_copilot_propagates_pivotal_gates_from_module():
    svc = MhspcCopilotService()
    bundle = svc.evaluate(_emr_record_nyha_iii(), effective_state="mcspc_high_volume")
    assert bundle.get("enabled") is True
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle
    gates = bundle["pivotal_contraindication_gates"]
    assert gates, "mhspc copilot no propagó gates"
    assert any(g.get("code") == "severe_heart_failure_nyha_iii_iv" for g in gates)
    nr_blob = " ".join(bundle["not_recommended"]).lower()
    assert "abirater" in nr_blob and "nyha" in nr_blob


def test_crpc_copilot_propagates_pivotal_gates_from_module():
    svc = CRPCCopilotService()
    record = {
        "state": "m1_crpc",
        "baseline": {
            "psa": 30,
            "psa_doubling_time": 5,
            "metastatic": "1",
            "visceral_metastasis": "0",
            "bone_lesion_count": 3,
            "ecog_score": 1,
            "age": 70,
            "castrate_resistant": "1",
            "testosterone": 20,
            "nyha_class": "III",
        },
        "longitudinal_truth_snapshot": {
            "field_values": {"nyha_class": "III"},
        },
    }
    bundle = svc.evaluate(record, effective_state="m1_crpc")
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


def test_post_rp_salvage_copilot_includes_propagation_keys():
    """post_rp_salvage_copilot consume recurrence_bcr — donde la propagación
    ya estaba activa. El bundle debe incluir las claves (al menos vacías)."""
    svc = PostRPSalvageCopilotService()
    record = {
        "state": "post_prostatectomy",
        "baseline": {
            "psa": 0.05,
            "psa_postop": 0.05,
            "gleason_total": 7,
            "pathologic_stage": "pT2c",
            "ecog_score": 0,
            "age": 65,
        },
    }
    bundle = svc.evaluate(record, effective_state="post_prostatectomy")
    # Las claves deben estar siempre presentes, aun cuando estén vacías
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


def test_localized_surveillance_copilot_includes_propagation_keys():
    """localized_surveillance_copilot consume localized_initial — donde la
    propagación ya estaba activa. El bundle debe incluir las claves."""
    svc = LocalizedSurveillanceCopilotService()
    record = {
        "state": "localized_initial",
        "baseline": {
            "psa": 6,
            "gleason_total": 6,
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "clinical_stage_t": "T1c",
            "ecog_score": 0,
            "age": 65,
        },
    }
    bundle = svc.evaluate(record, effective_state="localized_initial")
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


# ── Sección C — Backward compatibility en copilots disabled/healthy ──────────


def test_mhspc_copilot_disabled_bundle_has_propagation_keys():
    """Bundle desactivado debe incluir las claves vacías para uniformidad."""
    svc = MhspcCopilotService()
    # Estado fuera de MHSPC_VERTICAL_STATES → _disabled_bundle
    bundle = svc.evaluate(
        {"state": "localized_initial", "baseline": {"psa": 6}},
        effective_state="localized_initial",
    )
    assert bundle.get("enabled") is False
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle
    assert bundle["pivotal_contraindication_gates"] == []
    assert bundle["not_recommended"] == []


def test_crpc_copilot_disabled_bundle_has_propagation_keys():
    svc = CRPCCopilotService()
    bundle = svc.evaluate(
        {"state": "localized_initial", "baseline": {"psa": 6}},
        effective_state="localized_initial",
    )
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


def test_post_rp_salvage_copilot_disabled_bundle_has_propagation_keys():
    svc = PostRPSalvageCopilotService()
    bundle = svc.evaluate(
        {"state": "diagnostic_workup", "baseline": {"psa": 4}},
        effective_state="diagnostic_workup",
    )
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


def test_localized_surveillance_copilot_disabled_bundle_has_propagation_keys():
    svc = LocalizedSurveillanceCopilotService()
    bundle = svc.evaluate(
        {"state": "diagnostic_workup", "baseline": {"psa": 4}},
        effective_state="diagnostic_workup",
    )
    assert "pivotal_contraindication_gates" in bundle
    assert "not_recommended" in bundle


def test_healthy_payload_does_not_create_spurious_gates_in_high_volume_service():
    svc = McspcHighVolumeService()
    payload = _hv_payload_nyha_iii(nyha_class="I")  # sin contraindicación
    res = svc.evaluate(payload)
    gates = res.get("pivotal_contraindication_gates") or []
    # NYHA I no debe disparar el gate cardíaco
    assert not any(g.get("code") == "severe_heart_failure_nyha_iii_iv" for g in gates)


# ── Sección D — Smoke test end-to-end vía ModuleRegistry ─────────────────────


@pytest.fixture(scope="module")
def registry():
    return ModuleRegistry()


@pytest.mark.parametrize(
    "module_id,extra_payload,expected_code",
    [
        (
            "mcspc_high_volume",
            {"nyha_class": "III"},
            "severe_heart_failure_nyha_iii_iv",
        ),
        (
            "mcspc_high_volume_sync",
            {"nyha_class": "IV"},
            "severe_heart_failure_nyha_iii_iv",
        ),
        (
            "m0_crpc",
            {"darolutamide_hypersensitivity": "Sí"},
            "darolutamide_hypersensitivity",
        ),
    ],
)
def test_registry_evaluate_module_exposes_pivotal_gates(
    registry, module_id, extra_payload, expected_code
):
    base = {
        "psa": 30,
        "gleason_total": 9,
        "gleason_primary": 5,
        "gleason_secondary": 4,
        "metastatic": "1" if "crpc" not in module_id or module_id == "m1_crpc" else "0",
        "visceral_metastasis": "0",
        "bone_lesion_count": 3,
        "volume_disease": "high",
        "metastatic_temporality": "synchronous",
        "ecog_score": 1,
        "age": 70,
        "castrate_resistant": "1" if "crpc" in module_id else "0",
        "testosterone": 20 if "crpc" in module_id else 350,
        "psa_doubling_time": 5,
        "docetaxel_fit": "Yes",
    }
    base.update(extra_payload)
    res = registry.evaluate_module(module_id, base)
    gates = res.get("pivotal_contraindication_gates") or []
    codes = {g.get("code") for g in gates}
    assert expected_code in codes, (
        f"{module_id} no expuso gate {expected_code}; codes={codes}"
    )
