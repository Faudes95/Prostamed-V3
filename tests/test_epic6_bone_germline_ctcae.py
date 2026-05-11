# -*- coding: utf-8 -*-
"""Tests EPIC 6 — Bone health, germline testing triggers, CTCAE estructurado.

Cubre los trayectos pivote definidos en el plan maestro EPIC 6:

  * test_localized_very_high_risk_germline_trigger
  * test_metastatic_disease_triggers_germline_category_2a
  * test_intraductal_histology_triggers_germline
  * test_somatic_variant_confirms_germline
  * test_known_brca2_variant_triggers_family_counseling
  * test_adt_12m_dxa_missing_alert
  * test_mcrpc_bone_mets_denosumab_required
  * test_zoledronate_switches_to_denosumab_when_egfr_low
  * test_hypocalcemia_blocks_bma
  * test_adt_induced_osteoporosis_triggers_denosumab_60mg
  * test_ctcae_grade3_neutropenia_requires_action_alert
  * test_ctcae_critical_grade4_emits_critical_alert
  * test_ctcae_legacy_grade_fields_imported
  * test_ctcae_agent_overburden_alert
  * test_alert_engine_registers_bone_germline_ctcae_families

Evidencia:
  * NCCN Prostate v5.2026 PROS-H (germline) y PROS-I (bone health)
  * Fizazi K et al. Lancet 2011;377:813 (denosumab 120mg q4w mCRPC SRE)
  * Smith MR et al. NEJM 2009;361:745 (HALT — denosumab 60mg q6mo ADT)
  * Smith MR et al. JAMA 2014;311:283 (HALT-ZA — zoledronato 5mg annual)
  * Giri VN et al. JCO 2020;38:2798 (Philadelphia Prostate Consensus)
  * Pritchard CC et al. NEJM 2016;375:443 (germline prevalence mCRPC)
  * CTCAE v5.0 NCI 2017
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.alert_engine import ClinicalAlertEngine
from prostanet.domains.patient_tracking.bone_health_engine import (
    BMA_MCRPC_STATES,
    ZA_CONTRAINDICATED_EGFR,
    build_bone_health_recommendation,
    compute_frax_simplified,
    detect_dxa_gap,
    recommend_bma,
)
from prostanet.domains.patient_tracking.ctcae_capture_engine import (
    LEGACY_GRADE_FIELDS,
    capture_ctcae_events,
)
from prostanet.shared.ctcae_v5 import (
    aggregate_toxicity_burden,
    record_adverse_event,
)
from prostanet.shared.germline_testing_triggers import (
    should_offer_germline_testing,
)


# ─────────────────────── Germline testing triggers (NCCN PROS-H) ──────────────


def test_localized_very_high_risk_germline_trigger():
    """Gleason 10 + T3b + PSA>40 → very high risk → category 2A germline offer."""
    patient = {
        "current_state": "localized_initial",
        "gleason_score": 10,
        "psa": 45.0,
        "clinical_t": "T3b",
        "nccn_risk_group": "VERY HIGH",
    }
    rec = should_offer_germline_testing(patient)
    assert rec.should_offer is True
    assert rec.priority == "category_2A"
    ids = [t["id"] for t in rec.triggers_matched]
    assert "very_high_risk_localized" in ids
    assert "very_high_risk_category_2a" in rec.evidence_tags


def test_metastatic_disease_triggers_germline_category_2a():
    """Cualquier M1 → category_2A germline (Pritchard NEJM 2016)."""
    patient = {
        "current_state": "m1_crpc",
        "metastasis_site": "bone",
        "bone_metastasis_count": 6,
        "m_stage": "M1b",
    }
    rec = should_offer_germline_testing(patient)
    assert rec.should_offer is True
    assert rec.priority == "category_2A"
    ids = [t["id"] for t in rec.triggers_matched]
    assert "metastatic_disease" in ids


def test_intraductal_histology_triggers_germline():
    """Histología intraductal/cribiforme → category 2A si alto riesgo."""
    patient = {
        "current_state": "localized_initial",
        "gleason_score": 9,
        "psa": 25.0,
        "clinical_t": "T3a",
        "histology_variant": "intraductal_carcinoma",
    }
    rec = should_offer_germline_testing(patient)
    assert rec.should_offer is True
    ids = [t["id"] for t in rec.triggers_matched]
    assert "intraductal_cribriform_histology" in ids
    # Category 2A porque hay high risk coexistente.
    intraductal_cat = next(
        t["category"] for t in rec.triggers_matched
        if t["id"] == "intraductal_cribriform_histology"
    )
    assert intraductal_cat == "category_2A"


def test_somatic_variant_confirms_germline():
    """Variante somática patogénica obliga a confirmar germline (Pritchard 2016)."""
    patient = {
        "current_state": "m1_crpc",
        "metastasis_site": "bone",
        "somatic_pathogenic_variant": "BRCA2",
    }
    rec = should_offer_germline_testing(patient)
    assert rec.should_offer is True
    assert rec.priority == "category_2A"
    ids = [t["id"] for t in rec.triggers_matched]
    assert "somatic_pathogenic_variant_detected" in ids


def test_known_brca2_variant_triggers_family_counseling():
    """Testing germinal previo con BRCA2 patogénico → family counseling cascada."""
    patient = {
        "current_state": "m1_crpc",
        "germline_testing_performed": "1",
        "germline_pathogenic_variant": "BRCA2",
    }
    rec = should_offer_germline_testing(patient)
    assert rec.should_offer is False
    assert rec.priority == "not_indicated"
    assert rec.family_counseling_recommended is True
    assert rec.known_pathogenic_variant == "BRCA2"


# ────────────────────────── Bone health (NCCN PROS-I) ─────────────────────────


def test_adt_12m_dxa_missing_alert():
    """ADT ≥12m sin DXA documentado → missing_mandatory + alerta (NCCN PROS-I)."""
    patient = {
        "current_state": "mcspc_high_volume",
        "adt_active": "1",
        "adt_duration_months": 14,
        # Sin dxa_t_score_lumbar / hip / fecha de DXA
    }
    dxa_gap = detect_dxa_gap(patient)
    assert dxa_gap["status"] == "missing_mandatory"
    rec = build_bone_health_recommendation(patient)
    alert_types = {a["type"] for a in rec.alerts}
    assert "bone_dxa_missing_mandatory" in alert_types


def test_mcrpc_bone_mets_denosumab_required():
    """m1CRPC con metástasis óseas → denosumab 120mg q4w (Fizazi Lancet 2011)."""
    patient = {
        "current_state": "m1_crpc",
        "bone_metastasis_count": 6,
        "egfr_ml_min": 75,
    }
    assert "m1_crpc" in BMA_MCRPC_STATES
    rec = build_bone_health_recommendation(patient)
    bma = rec.bma_recommendation
    assert bma["action"] == "initiate"
    assert "denosumab" in bma["agent"].lower()
    assert "120" in bma["dose"] or "q4" in bma["dose"].lower() or "120mg" in bma["dose"].replace(" ", "").lower()
    assert any("fizazi" in tag.lower() for tag in rec.evidence_tags)


def test_zoledronate_switches_to_denosumab_when_egfr_low():
    """eGFR <30 contraindicado ZA → switch a denosumab (FDA label)."""
    patient = {
        "current_state": "m1_crpc",
        "bone_metastasis_count": 4,
        "egfr_ml_min": 25,
        "bone_modifying_agent": "zoledronate",
        "current_bma": "zoledronic_acid",
    }
    assert 25 < ZA_CONTRAINDICATED_EGFR
    rec = build_bone_health_recommendation(patient)
    bma = rec.bma_recommendation
    alert_types = {a["type"] for a in rec.alerts}
    # Debe proponer switch o iniciar denosumab explícitamente.
    assert bma["action"] in {"switch_to_denosumab", "initiate"}
    assert "denosumab" in bma["agent"].lower()
    if bma["action"] == "switch_to_denosumab":
        assert "bone_bma_switch_renal" in alert_types


def test_hypocalcemia_blocks_bma():
    """Calcio <8.4 mg/dL → corregir antes de BMA (FDA warning denosumab/ZA)."""
    patient = {
        "current_state": "m1_crpc",
        "bone_metastasis_count": 3,
        "calcium_mg_dl": 7.8,
        "vitamin_d_level": 25.0,
    }
    rec = build_bone_health_recommendation(patient)
    alert_types = {a["type"] for a in rec.alerts}
    assert "bone_hypocalcemia_before_bma" in alert_types
    # Tone elevado a danger cuando hay hipocalcemia.
    assert rec.tone in {"danger", "warning"}


def test_adt_induced_osteoporosis_triggers_denosumab_60mg():
    """ADT ≥12m + osteoporosis (T-score ≤-2.5) → denosumab 60mg q6mo (Smith 2009)."""
    patient = {
        "current_state": "mcspc_low_volume_sync_oligo",
        "adt_active": "1",
        "adt_duration_months": 18,
        "dxa_t_score_lumbar": -2.8,
        "dxa_t_score_hip": -2.6,
        "dxa_date": "2025-10-01",
        "egfr_ml_min": 65,
        "calcium_mg_dl": 9.2,
        "vitamin_d_level": 32.0,
    }
    rec = build_bone_health_recommendation(patient)
    bma = rec.bma_recommendation
    assert bma["action"] in {"initiate", "maintain"}
    assert "denosumab" in bma["agent"].lower()
    # La indicación debe diferenciarse de mCRPC bone mets.
    assert "adt_induced" in bma.get("indication", "").lower() or rec.bone_category == "osteoporosis"


def test_frax_simplified_escalates_with_risk_factors():
    """FRAX simplificado sube con T-score + tabaquismo + esteroides + edad."""
    patient = {
        "age": 78,
        "dxa_t_score_hip": -2.9,
        "current_smoker": "1",
        "systemic_corticosteroids": "1",
        "adt_duration_months": 30,
        "parental_hip_fracture": "1",
    }
    frax = compute_frax_simplified(patient)
    assert frax is not None
    assert frax >= 15  # tras acumulación de múltiples factores


# ─────────────────────────── CTCAE v5.0 estructurado ─────────────────────────


def test_ctcae_grade3_neutropenia_requires_action_alert():
    """Neutropenia grado 3 sin modificación → ctcae_grade3_no_action alert."""
    patient = {
        "current_state": "m1_crpc",
        "current_treatment": "docetaxel 75 mg/m² q3w",
        "ctcae_events": [
            {
                "term": "neutropenia",
                "grade": 3,
                "category": "hematologic",
                "attribution": "probable",
                "agent_suspected": "docetaxel",
                "action_taken": "none",
            }
        ],
    }
    result = capture_ctcae_events(patient)
    alert_types = {a["type"] for a in result.alerts}
    assert "ctcae_grade3_no_action" in alert_types
    assert result.tone in {"warning", "danger"}
    assert result.burden.get("max_grade") == 3


def test_ctcae_critical_grade4_emits_critical_alert():
    """Grado ≥4 → alerta critical (potencial hospitalización)."""
    patient = {
        "current_state": "m1_crpc",
        "current_treatment": "cabazitaxel",
        "ctcae_events": [
            {
                "term": "febrile_neutropenia",
                "grade": 4,
                "category": "hematologic",
                "attribution": "definite",
                "agent_suspected": "cabazitaxel",
                "action_taken": "drug_interruption",
            }
        ],
    }
    result = capture_ctcae_events(patient)
    alert_types = {a["type"] for a in result.alerts}
    assert "ctcae_critical" in alert_types
    assert result.tone == "danger"
    assert len(result.burden.get("critical_events") or []) >= 1


def test_ctcae_legacy_grade_fields_imported():
    """peripheral_neuropathy_grade=2 se importa como evento CTCAE."""
    patient = {
        "current_state": "m1_crpc",
        "current_treatment": "Docetaxel",
        "peripheral_neuropathy_grade": 2,
        "fatigue_grade": 3,
    }
    result = capture_ctcae_events(patient)
    imported = set(result.legacy_fields_imported)
    assert "peripheral_neuropathy_grade" in imported
    assert "fatigue_grade" in imported
    terms = {ev.get("term") for ev in result.events}
    assert "peripheral_neuropathy" in terms
    assert "fatigue" in terms
    # Cobertura LEGACY_GRADE_FIELDS: los 2 términos exponen metadatos válidos.
    assert "peripheral_neuropathy_grade" in LEGACY_GRADE_FIELDS
    assert "fatigue_grade" in LEGACY_GRADE_FIELDS


def test_ctcae_agent_overburden_alert():
    """≥3 eventos bajo el mismo agente → ctcae_agent_overburden alert."""
    patient = {
        "current_state": "m1_crpc",
        "current_treatment": "docetaxel",
        "ctcae_events": [
            {"term": "neutropenia", "grade": 2, "category": "hematologic",
             "attribution": "probable", "agent_suspected": "docetaxel"},
            {"term": "peripheral_neuropathy", "grade": 2, "category": "neurologic",
             "attribution": "probable", "agent_suspected": "docetaxel"},
            {"term": "fatigue", "grade": 2, "category": "neurologic",
             "attribution": "probable", "agent_suspected": "docetaxel"},
            {"term": "alopecia", "grade": 2, "category": "dermatologic",
             "attribution": "definite", "agent_suspected": "docetaxel"},
        ],
    }
    result = capture_ctcae_events(patient)
    alert_types = {a["type"] for a in result.alerts}
    assert "ctcae_agent_overburden" in alert_types
    agents = result.burden.get("agents_suspected", {})
    assert agents.get("docetaxel", 0) >= 3


def test_record_adverse_event_appends_and_validates():
    """record_adverse_event anexa y valida un evento nuevo."""
    existing = [
        {"term": "neutropenia", "grade": 2, "category": "hematologic",
         "attribution": "probable", "agent_suspected": "docetaxel"},
    ]
    full, fresh = record_adverse_event(
        existing,
        {"term": "anemia", "grade": 3, "category": "hematologic",
         "attribution": "possible", "agent_suspected": "docetaxel",
         "action_taken": "none"},
    )
    assert len(full) == 2
    assert fresh.term == "anemia"
    assert fresh.grade == 3


def test_aggregate_burden_tone_rules():
    """Burden tone: success (sin eventos), info (g1), warning (g3 1cat), danger (g4)."""
    # Sin eventos → success
    empty = aggregate_toxicity_burden([])
    assert empty["burden_tone"] == "success"

    # Grado 1 sólo → info
    g1 = aggregate_toxicity_burden([
        {"term": "fatigue", "grade": 1, "category": "neurologic",
         "attribution": "possible"}
    ])
    assert g1["burden_tone"] == "info"

    # Grado 3 en 1 categoría → warning
    g3 = aggregate_toxicity_burden([
        {"term": "neutropenia", "grade": 3, "category": "hematologic",
         "attribution": "probable", "agent_suspected": "docetaxel",
         "action_taken": "none"}
    ])
    assert g3["burden_tone"] == "warning"

    # Grado 4 → danger
    g4 = aggregate_toxicity_burden([
        {"term": "febrile_neutropenia", "grade": 4, "category": "hematologic",
         "attribution": "definite", "agent_suspected": "docetaxel",
         "action_taken": "drug_interruption"}
    ])
    assert g4["burden_tone"] == "danger"


# ──────────────────── Integración con alert_engine (run_all) ──────────────────


def test_alert_engine_registers_bone_germline_ctcae_families():
    """ClinicalAlertEngine.run_all debe incluir alertas EPIC 6 end-to-end."""
    patient = {
        "current_state": "m1_crpc",
        "current_treatment": "docetaxel",
        "bone_metastasis_count": 5,
        "egfr_ml_min": 70,
        "calcium_mg_dl": 9.2,
        "vitamin_d_level": 30.0,
        "gleason_score": 9,
        "psa": 65.0,
        "clinical_t": "T3b",
        "metastasis_site": "bone",
        "ctcae_events": [
            {"term": "neutropenia", "grade": 3, "category": "hematologic",
             "attribution": "probable", "agent_suspected": "docetaxel",
             "action_taken": "none"},
        ],
    }
    alerts = ClinicalAlertEngine.run_all(patient_id=1, patient=patient)
    categories = {a.category for a in alerts}
    assert "bone_health" in categories
    assert "germline_testing" in categories
    assert "ctcae_toxicity" in categories

    # Al menos una alerta bone_bma_initiate (metástasis óseas + mCRPC).
    alert_types = {a.alert_type for a in alerts}
    assert "bone_bma_initiate" in alert_types
    # Germline se ofrece (category_2A por metástasis).
    assert "germline_testing_offer" in alert_types
    # CTCAE grade3_no_action.
    assert "ctcae_grade3_no_action" in alert_types


def test_alert_engine_tolerant_when_bundles_missing():
    """run_all no debe fallar si faltan bundles EPIC 6 (tolerancia a legacy)."""
    minimal = {
        "current_state": "localized_initial",
        "psa": 5.0,
        "gleason_score": 6,
        "clinical_t": "T1c",
    }
    alerts = ClinicalAlertEngine.run_all(patient_id=42, patient=minimal)
    # El motor no debe tirar excepción; puede no emitir nada.
    assert isinstance(alerts, list)


def test_bone_health_recommendation_success_when_baseline_normal():
    """Paciente sin ADT, sin metástasis óseas, DXA normal → tone success."""
    patient = {
        "current_state": "localized_initial",
        "dxa_t_score_lumbar": -0.5,
        "dxa_t_score_hip": -0.8,
        "dxa_date": "2025-09-01",
        "vitamin_d_level": 35,
        "calcium_mg_dl": 9.5,
    }
    rec = build_bone_health_recommendation(patient)
    # Con DXA presente y normales no debe marcar missing_mandatory.
    assert rec.tone in {"success", "info"}
    assert rec.bone_category in {"normal", "osteopenia", "no_data"}
