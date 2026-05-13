# IEC 62304 §5.7 (System testing)
"""Tests EPIC 10B-H — UI cardio-cognitive coverage per clinical state.

Verifica que los 17 FieldSpecs cardio-cognitivos + minerales óseos
(añadidos por EPIC 10B paso A+D a 8 schemas) están **expuestos vía API
JSON** en cada estado clínico relevante.

Es el complemento de `test_epic10b_gate_field_coverage.py` (que verifica
integridad de contrato a nivel **catalog**) — este test verifica que la
**API** REST sirve esos fields al frontend para captura. Cierra el loop:

  schema canónico (helper) → schema del módulo → API JSON → render UI

Si falla: el formulario UI del estado correspondiente NO tendrá los
inputs para capturar NYHA/LVEF/QTc/MMSE/MOCA/ionized_calcium, lo que
significa que los hard-blocks pivotales (severe_heart_failure_nyha_iii_iv,
lvef_decline_for_apalutamide, qtc_prolongation_grade3_for_enzalutamide,
arsi_in_cognitive_decline_grade2, radium223_in_hypocalcemia) seguirán
huérfanos en runtime aunque pasen el audit estático.

Endpoint auditado:
  GET /api/modules/<module_id>/schema → {success: true, schema: {fields: [...]}}
"""
from __future__ import annotations

import pytest

# Los 17 fields cardio-cognitivos + mineral óseo que advanced_cardio_fields(16)
# y advanced_bone_turnover_fields(8 totales, 1 relevante) declaran y EPIC 10B
# cableó a los schemas mhspc/CRPC/post-RP.
EPIC10B_TARGET_FIELDS = {
    # advanced_cardio_fields (16)
    "lvef_percent",
    "lvef_date",
    "qtc_ms",
    "qtc_change_ms",
    "qtc_baseline_ms",
    "lvef_baseline_percent",
    "cognitive_disturbance_ctcae_grade",
    "mmse_baseline",
    "mmse_current",
    "moca_baseline",
    "moca_current",
    "cognitive_recovered_for_arpi",
    "troponin_baseline",
    "nt_probnp",
    "heart_failure_history",
    "nyha_class",
    # advanced_bone_turnover_fields (1 relevante para EPIC 10B Ra-223 hypocalcemia)
    "ionized_calcium",
}

# Module IDs expuestos por ModuleRegistry que recibieron el fix EPIC 10B paso A+D.
# Nota: mcspc_high_volume (base, sin sync/metachronous) está implícito en
# mcspc_high_volume_sync — el registry expone _sync y _metachronous.
EPIC10B_TARGET_MODULES = [
    "m0_crpc",
    "m1_crpc",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "post_prostatectomy",
]


def _field_names_from_schema(schema_payload: dict) -> set[str]:
    schema = schema_payload.get("schema") or {}
    fields = schema.get("fields") or []
    return {f.get("name") for f in fields if isinstance(f, dict) and f.get("name")}


@pytest.mark.parametrize("module_id", EPIC10B_TARGET_MODULES)
def test_epic10b_h_module_schema_endpoint_returns_200(app_client, module_id: str):
    """El endpoint canónico de schema debe responder 200 para cada módulo."""
    client, _ = app_client
    response = client.get(f"/api/modules/{module_id}/schema")
    assert response.status_code == 200, (
        f"Module '{module_id}': expected 200, got {response.status_code}. "
        "El registry no expone este module_id o el endpoint está roto."
    )
    payload = response.get_json()
    assert payload.get("success") is True, (
        f"Module '{module_id}': response.success != True. Payload: {payload}"
    )
    assert isinstance(payload.get("schema"), dict), (
        f"Module '{module_id}': response.schema no es dict. Payload: {payload}"
    )


@pytest.mark.parametrize("module_id", EPIC10B_TARGET_MODULES)
def test_epic10b_h_module_schema_exposes_all_cardio_cognitive_fields(
    app_client, module_id: str
):
    """Cada uno de los 7 módulos clínicos debe exponer los 17 fields
    cardio-cognitivos + ionized_calcium vía la API de schema.

    Es la prueba E2E del fix EPIC 10B paso A+D: si pasa, los formularios
    UI van a capturar correctamente NYHA, LVEF, QTc, MMSE, MOCA y
    ionized_calcium, lo que habilita los 7 hard-blocks pivotales (NYHA
    III-IV, LVEF<40%, QTc grade 3, cognitive decline grade 2,
    hypocalcemia for Ra-223, Hb rapid drop) en runtime.
    """
    client, _ = app_client
    response = client.get(f"/api/modules/{module_id}/schema")
    assert response.status_code == 200, f"Module '{module_id}' endpoint failed"

    payload = response.get_json()
    field_names = _field_names_from_schema(payload)

    missing = EPIC10B_TARGET_FIELDS - field_names
    assert not missing, (
        f"Module '{module_id}' API schema NO expone {len(missing)} fields "
        f"cardio-cog/óseos esperados: {sorted(missing)}. "
        "Esto significa que el formulario UI de este estado clínico "
        "no podrá capturarlos y los hard-blocks asociados quedarán "
        "huérfanos en runtime. Verificar que el schema del dominio "
        "invoca advanced_cardio_fields() + advanced_bone_turnover_fields()."
    )


def test_epic10b_h_summary_total_coverage(app_client):
    """Summary: 7 módulos × 17 fields = 119 (module, field) pairs.

    Esperado: 100% coverage tras EPIC 10B paso A+D.
    """
    client, _ = app_client
    coverage: dict[str, set[str]] = {}
    for module_id in EPIC10B_TARGET_MODULES:
        response = client.get(f"/api/modules/{module_id}/schema")
        assert response.status_code == 200
        coverage[module_id] = _field_names_from_schema(response.get_json())

    pairs_total = len(EPIC10B_TARGET_MODULES) * len(EPIC10B_TARGET_FIELDS)
    pairs_covered = sum(
        1
        for module_id in EPIC10B_TARGET_MODULES
        for field in EPIC10B_TARGET_FIELDS
        if field in coverage[module_id]
    )
    coverage_pct = (pairs_covered / pairs_total * 100) if pairs_total else 0
    print(
        f"\nEPIC 10B-H coverage: {pairs_covered}/{pairs_total} pairs "
        f"({coverage_pct:.1f}%)"
    )
    assert pairs_covered == pairs_total, (
        f"EPIC 10B-H coverage gap: {pairs_total - pairs_covered} missing pairs "
        f"out of {pairs_total} expected ({coverage_pct:.1f}% coverage)."
    )


def test_epic10b_h_state_classifier_route_smoke(app_client):
    """Smoke: state_classifier schema sirve la versión canónica y NO incluye
    los cardio-cog fields (este módulo es upstream y no captura comorbilidades).

    Documenta que el fix EPIC 10B no contamina state_classifier (que solo
    debe tener fields de clasificación de estado, no de captura clínica).
    """
    client, _ = app_client
    response = client.get("/api/modules/state-classifier/schema")
    assert response.status_code == 200
    field_names = _field_names_from_schema(response.get_json())
    # state_classifier debe NO tener los cardio-cog (es un módulo de routing)
    leaked_cardio = EPIC10B_TARGET_FIELDS & field_names
    assert not leaked_cardio, (
        f"state_classifier filtra fields cardio-cog que no debería tener "
        f"(es módulo upstream de routing): {sorted(leaked_cardio)}. "
        "Revisar que advanced_cardio_fields no se invocó accidentalmente "
        "en prostanet/domains/state_classifier/schemas.py."
    )
