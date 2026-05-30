"""tests/test_audit_lxxxiv_b_brechas_64b_55b.py — FAUBOT LXXXIV.b cierre brechas.

Tests para verificar fix de 2 brechas detectadas tras Iteración #1:

1. **Brecha #64B**: `bundle_to_v2_profile_full()` NO exponía 3 keys de #64A
   - psa_forecast_per_line, psa_cohort_reference, psa_combined_timeline
   - Fix: agregadas en v2_adapters.py

2. **Brecha #55B (Imaging modality nmCRPC)**: NO había gate que recomendara
   PSMA-PET sobre CT/bone scan en pacientes nmCRPC con PSA bajo (0.5-2 ng/mL)
   - Fix: nuevo gate 55B (PROMISE Lancet 2020 evidence)

3. **patient_profile_v2.html canvas combined_timeline + cohort overlay**:
   - Fix: agregadas 3 secciones HTML en tab-timeline

HIPÓTESIS: H.G2760 → H.G2773 (~14 tests).
Faubot LXXXIV.b — cierre brechas pre-Iteración #2.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types
from pathlib import Path

try:
    import tracking_db  # noqa: F401
except Exception:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")

ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")


# ──────────────────────────────────────────────────────────────────────
# §A — Gate 55B: PSMA-PET preferred nmCRPC PSA bajo
# ──────────────────────────────────────────────────────────────────────


def test_g2760_gate_55b_loaded_in_yaml():
    """H.G2760 — Gate 55B (PSMA preferred nmCRPC) loaded en catálogo YAML."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    assert "psma_pet_preferred_for_nmcrpc_low_psa" in get_loaded_yaml_codes()


def test_g2761_gate_55b_fires_with_nmcrpc_psa_low_ct_only():
    """H.G2761 — Gate 55B dispara con nmCRPC + PSA 0.5-2 + imaging convencional."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "m0_crpc_state_confirmed": True,
        "psa_value": 1.5,
        "imaging_modality_used_for_m_staging": "CT_plus_bone_scan",
    })
    assert "psma_pet_preferred_for_nmcrpc_low_psa" in [g["code"] for g in fired]


def test_g2762_gate_55b_no_fire_with_psma_pet_already_done():
    """H.G2762 — Gate 55B NO dispara si PSMA-PET ya hecho."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "m0_crpc_state_confirmed": True,
        "psa_value": 1.5,
        "imaging_modality_used_for_m_staging": "PSMA_PET",
    })
    # CT_only/CT_plus_bone_scan/Desconocido están en patterns; PSMA_PET no
    assert "psma_pet_preferred_for_nmcrpc_low_psa" not in [g["code"] for g in fired]


def test_g2763_gate_55b_no_fire_with_psa_above_2():
    """H.G2763 — Gate 55B NO dispara con PSA >2 ng/mL (rango óptimo PSMA es 0.5-2)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "m0_crpc_state_confirmed": True,
        "psa_value": 5.0,
        "imaging_modality_used_for_m_staging": "CT_plus_bone_scan",
    })
    assert "psma_pet_preferred_for_nmcrpc_low_psa" not in [g["code"] for g in fired]


def test_g2764_gate_55b_evidence_refs_present():
    """H.G2764 — Gate 55B incluye trial_refs PROMISE + NCCN + EAU."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    yaml_data = _load_yaml_files(force_reload=True)
    config = next((c for c in yaml_data.values() if c.get("code") == "psma_pet_preferred_for_nmcrpc_low_psa"), None)
    assert config is not None
    refs = config.get("trial_refs", [])
    refs_str = " ".join(refs)
    assert "PROMISE" in refs_str or "Hofman" in refs_str
    assert "NCCN" in refs_str or "EAU" in refs_str


def test_g2765_total_89_gates_loaded():
    """H.G2765 — Total 89 gates loaded (88 LXXXIV + 1 nuevo 55B = 89)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 89


# ──────────────────────────────────────────────────────────────────────
# §B — Brecha #64B: v2_adapters expone 3 keys #64A
# ──────────────────────────────────────────────────────────────────────


def test_g2766_v2_adapter_exposes_psa_forecast_per_line():
    """H.G2766 — bundle_to_v2_profile_full() expone psa_forecast_per_line."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    profile_view = {
        "psa_forecast_per_line": {"per_line_forecasts": {"1": {"regimen_class": "ADT"}}},
    }
    patient = {"full_name": "Test", "nss": "test-001"}
    bundle = bundle_to_v2_profile_full(profile_view, patient)
    assert "psa_forecast_per_line" in bundle
    assert bundle["psa_forecast_per_line"]["per_line_forecasts"]["1"]["regimen_class"] == "ADT"


def test_g2767_v2_adapter_exposes_psa_cohort_reference():
    """H.G2767 — bundle_to_v2_profile_full() expone psa_cohort_reference."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    profile_view = {
        "psa_cohort_reference": {"applicable_combos": [{"state": "mcspc", "regimen_class": "ADT_DOCETAXEL"}]},
    }
    patient = {"full_name": "Test", "nss": "test-002"}
    bundle = bundle_to_v2_profile_full(profile_view, patient)
    assert "psa_cohort_reference" in bundle
    assert bundle["psa_cohort_reference"]["applicable_combos"][0]["regimen_class"] == "ADT_DOCETAXEL"


def test_g2768_v2_adapter_exposes_psa_combined_timeline():
    """H.G2768 — bundle_to_v2_profile_full() expone psa_combined_timeline."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    profile_view = {
        "psa_combined_timeline": {
            "psa_series": [{"date": "2025-01-15", "value": 12.0}],
            "summary": {"total_psa_points": 5, "total_treatment_lanes": 2},
        },
    }
    patient = {"full_name": "Test", "nss": "test-003"}
    bundle = bundle_to_v2_profile_full(profile_view, patient)
    assert "psa_combined_timeline" in bundle
    assert bundle["psa_combined_timeline"]["summary"]["total_psa_points"] == 5


def test_g2769_v2_adapter_returns_empty_dict_when_keys_missing():
    """H.G2769 — bundle_to_v2_profile_full() retorna {} si keys missing (no falla)."""
    from prostanet.presentation.v2_adapters import bundle_to_v2_profile_full
    profile_view = {}
    patient = {"full_name": "Test", "nss": "test-004"}
    bundle = bundle_to_v2_profile_full(profile_view, patient)
    # NO debe fallar — defaults a {}
    assert bundle["psa_forecast_per_line"] == {}
    assert bundle["psa_cohort_reference"] == {}
    assert bundle["psa_combined_timeline"] == {}


# ──────────────────────────────────────────────────────────────────────
# §C — patient_profile_v2.html canvas + sections HTML
# ──────────────────────────────────────────────────────────────────────


def test_g2770_patient_profile_v2_has_combined_timeline_canvas():
    """H.G2770 — patient_profile_v2.html incluye canvas psaCombinedTimelineChart."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'id="psaCombinedTimelineChart"' in template, (
        "Canvas combined timeline missing en patient_profile_v2.html"
    )
    assert "function renderCombinedTimeline" in template
    assert "or pm2_psa_points or pm2_treatment_bands" in template
    assert "psa_obs.points + psa_obs.treatment_bands" in template


def test_g2770b_patient_profile_v2_has_psa_treatment_timeline_canvas():
    """V2 debe materializar psaTreatmentTimelineChart; legacy no es criterio."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'id="psaTreatmentTimelineChart"' in template
    assert "function renderTreatmentTimeline" in template
    assert "psaTreatmentTimelineEmpty" in template
    assert "patient_profile.html" not in template


def test_patient_profile_v2_psa_tower_surfaces_current_treatment_line():
    """La torre APE V2 debe exponer mediciones y linea terapeutica actual."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'id="psaMini"' in template
    assert 'id="psaFull"' in template
    assert 'data-testid="v2-psa-current-treatment-line"' in template
    assert "pm2_psa_points|length" in template
    assert "tx_current.regimen_label" in template
    assert "tx_current.line_of_therapy_number" in template
    assert "pm2_current_band" in template


def test_g2770c_patient_profile_v2_surfaces_treatment_value_costs():
    """Costos y estadistica ARPI deben estar visibles en V2."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'data-testid="v2-treatment-value-summary"' in template
    assert 'data-testid="v2-treatment-cost-topline"' in template
    assert "Valor clinico-economico V2" in template
    assert "Tratamiento y costo farmacológico V2" in template
    assert "estimated_total_spend_mxn" in template
    assert "estimated_cost_per_dose_mxn" in template
    assert "priced_components" in template
    assert "priced_doses" in template
    assert "cost_scope" in template
    assert "arpi_response_6mo" in template


def test_patient_profile_v2_surfaces_clinical_fact_ledger_v1_closure():
    """Clinical Fact Ledger v1 debe ser visible en V2, no solo API."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'data-testid="clinical-fact-ledger-v1-panel"' in template
    assert 'data-testid="clinical-fact-ledger-contract"' in template
    assert 'data-testid="clinical-fact-ledger-priority-facts"' in template
    assert 'data-testid="clinical-fact-ledger-conflict-queue"' in template
    assert 'data-testid="clinical-fact-ledger-recapture-watch"' in template
    assert 'data-testid="decision-today-ledger-quality-banner"' in template
    assert 'data-testid="autodrive-ledger-quality-gate"' in template
    assert 'data-testid="ledger-capture-governance-panel"' in template
    assert 'data-testid="ledger-governed-{{ gate.gate_key }}"' in template
    assert 'data-testid="ledger-reconciliation-v2-link"' in template
    assert 'data-testid="ledger-summary-api-link"' in template
    assert "/clinical-fact-ledger/summary" in template
    assert "/clinical-fact-reconciliation/" in template
    assert "prellenar sin volver a preguntar" in template
    assert "CTAs gobernadas por Ledger" in template
    assert "sin recaptura" in template
    assert "Calidad Ledger de DECISION HOY" in template


def test_wizard_v2_consumes_clinical_fact_ledger_without_recaputure():
    """El wizard V2 usa Ledger para prellenar/ocultar, no para mutar hechos fuente."""
    template = (ROOT / "templates/clinical_wizard.html").read_text()
    assert 'data-testid="wizard-ledger-prefill-panel"' in template
    assert 'data-testid="wizard-ledger-contract"' in template
    assert 'id="wizardClinicalFactLedgerContext"' in template
    assert "applyClinicalFactLedgerWizardContext" in template
    assert "reuse_prefill_hide" in template
    assert "resolve_conflict_before_reuse" in template
    assert 'data-source-clinical-facts-mutated="false"' in template


def test_registration_phase_consumes_clinical_fact_ledger_without_recaputure():
    """El registro longitudinal recibe el contrato Ledger y muestra chips anti-recaptura."""
    wizard_template = (ROOT / "templates/clinical_wizard.html").read_text()
    intake_template = (ROOT / "templates/patient_intake.html").read_text()
    registration_js = (ROOT / "static/js/registration_context_ui.js").read_text()
    assert "clinical_fact_ledger_wizard_context" in wizard_template
    assert "clinical_fact_ledger_registration_context" in wizard_template
    assert "patient_ref: wizardPatientRef" in wizard_template
    assert "ledgerContext: data.clinical_fact_ledger_registration_context || null" in intake_template
    assert 'data-testid="registration-ledger-prefill-panel"' in registration_js
    assert 'data-testid="registration-ledger-contract"' in registration_js
    assert 'data-source-clinical-facts-mutated="' in registration_js
    assert "Ledger reutilizado" in registration_js
    assert "Ledger conflicto" in registration_js


def test_longitudinal_capture_v2_consumes_clinical_fact_ledger_without_recapture():
    """La captura longitudinal V2 aplica Ledger sin bloquear nuevas series APE."""
    template = (ROOT / "templates/demos/longitudinal_capture_v2_demo.html").read_text()
    service = (ROOT / "prostanet/domains/clinical_fact_ledger/service.py").read_text()
    app_py = (ROOT / "app.py").read_text()
    assert 'data-testid="longitudinal-ledger-context-panel"' in template
    assert 'id="longitudinalClinicalFactLedgerContext"' in template
    assert "PM2_LONGITUDINAL_LEDGER_CONTEXT" in template
    assert "applyLongitudinalLedgerContext" in template
    assert "longitudinal-ledger-field-" in template
    assert "ledgerFieldAction" in template
    assert "ledger_context" in template
    assert "ledger_recapture_blocked" in template
    assert "disabledByLedger" in template
    assert "field_decisions" in service
    assert "append_longitudinal_measurement" in service
    assert "append_new_measurement" in service
    assert "build_longitudinal_capture_ledger_context" in service
    assert "build_longitudinal_capture_ledger_context" in app_py
    assert "ledger_recapture_blocked" in app_py


def test_clinical_fact_reconciliation_v2_is_wired_to_ledger_conflicts():
    """La reconciliacion V2 convierte conflicto Ledger en accion auditable."""
    template = (ROOT / "templates/clinical_fact_reconciliation_v2.html").read_text()
    service = (ROOT / "prostanet/domains/clinical_fact_ledger/service.py").read_text()
    app_py = (ROOT / "app.py").read_text()
    tracking_db = (ROOT / "tracking_db.py").read_text()

    assert 'data-testid="clinical-fact-reconciliation-panel"' in template
    assert 'data-testid="ledger-reconciliation-queue"' in template
    assert 'data-testid="ledger-reconciliation-impact-contract"' in template
    assert 'data-testid="ledger-reconciliation-impact-live"' in template
    assert "PM2_RECONCILIATION_IMPACT_KEY" in template
    assert "Gate DECISION HOY" in template
    assert "ledger_gate_cleared" in template
    assert "clinical-fact-ledger/reconcile" in template
    assert "reconciliation_impact" in template
    assert "build_patient_clinical_fact_reconciliation_bundle" in service
    assert "clinical_fact_reconciliation_bundle_v1" in service
    assert "/clinical-fact-reconciliation/<patient_ref>" in app_py
    assert "clinical_fact_reconciliation_decision_refresh_v1" in app_py
    assert "_recompute_after_append" in app_py
    assert "reconcile_patient_clinical_fact" in tracking_db
    assert "clinical_fact_reconciled" in tracking_db
    assert "ledger_reconciliation" in tracking_db


def test_clinical_fact_reconciliation_population_v2_is_wired_to_ledger_queue():
    """La reconciliacion Ledger tiene cola poblacional read-only en V2."""
    template = (ROOT / "templates/clinical_fact_reconciliation_population_v2.html").read_text()
    profile_template = (ROOT / "templates/patient_profile_v2.html").read_text()
    service = (ROOT / "prostanet/domains/clinical_fact_ledger/service.py").read_text()
    app_py = (ROOT / "app.py").read_text()

    assert 'data-testid="ledger-reconciliation-population-panel"' in template
    assert 'data-testid="ledger-reconciliation-population-contract"' in template
    assert "clinical_fact_reconciliation_population_v1" in template
    assert "ledger-reconciliation-population-row-" in template
    assert "source_clinical_facts_mutated=false" in template
    assert "external_order_created=false" in template
    assert "model_trained=false" in template
    assert "build_clinical_fact_reconciliation_population" in service
    assert "clinical_fact_reconciliation_population_v1" in service
    assert "/clinical-fact-reconciliation" in app_py
    assert "/api/clinical-fact-ledger/reconciliation/today" in app_py
    assert 'data-testid="ledger-reconciliation-population-link"' in profile_template


def test_g2771_patient_profile_v2_renders_cohort_reference_overlay():
    """H.G2771 — patient_profile_v2.html renderiza cohort references overlay."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert "Cohort Reference Overlay" in template
    assert "applicable_combos" in template
    # Trials pivotales mencionados
    assert "CHAARTED" in template or "ARASENS" in template or "PROfound" in template


def test_g2772_patient_profile_v2_renders_per_line_forecast():
    """H.G2772 — patient_profile_v2.html renderiza per-line forecast (3m/6m/12m)."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert "Per-line PSA Forecast" in template
    assert "per_line_forecasts" in template
    assert "forecast_3m_value" in template
    assert "forecast_12m_value" in template


def test_g2773_patient_profile_v2_uses_jinja_conditional_for_safety():
    """H.G2773 — Las 3 secciones nuevas usan {% if %} para safety si data missing."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    # Verificar que las 3 secciones tienen guards condicionales
    assert "{% if (psa_combined_timeline" in template
    assert "{% if psa_cohort_reference" in template
    assert "{% if psa_forecast_per_line" in template
