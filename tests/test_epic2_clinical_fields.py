"""Tests EPIC 2 — Campos clínicos mínimos ausentes.

Cubre los helpers y flujos introducidos para cerrar las brechas de
captura que hoy impiden decisiones NCCN/EAU completas:

* Función renal (CKD-EPI 2021 → gates abiraterona/olaparib/Ra-223)
* Marcadores Halabi (albumin/ldh/hgb/alp) + `labs_missing_flags`
* Clasificadores genómicos numéricos (Decipher/Prolaris/Oncotype)
* Germline vs somático (NCCN PROS-H trigger, PARP elegibilidad)
* Medication list estructurada + DDI engine expandido
* Visceral sites discriminados
* EPIC 2 clinical cards en ``profile_compass`` view model

Referencias pivote:
  * Inker LA et al. NEJM 2021 (CKD-EPI 2021).
  * Halabi S et al. JCO 2014;32:671 (IPS mCRPC category 1).
  * Spratt DE et al. JCO 2018;36:581 (Decipher HR 1.24/0.1 punto).
  * Smith MR et al. Lancet Oncol 2019 (ERA-223 Ra-223 + abiraterona).
  * NCCN PROS-H v5.2026 (germline trigger).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.epic2_clinical_cards_builder import (
    build_epic2_clinical_cards,
)
from prostanet.domains.patient_tracking.halabi_nomogram import (
    predict_mcrpc_prognosis,
)
from prostanet.shared.ddi_engine import DDIEngine
from prostanet.shared.genomic_classifier_scores import classify_genomic_score
from prostanet.shared.medication_list import normalize_medication_list
from prostanet.shared.renal_function import compute_egfr, renal_dosing_flag


# ──────────────────────────────────────────────────────────────────────
# 1. Función renal — CKD-EPI 2021 + gate abiraterona/olaparib/Ra-223
# ──────────────────────────────────────────────────────────────────────


def test_egfr_ckd_epi_2021_classifies_kdigo_stage():
    """Inker 2021 NEJM: varón 68y, creat 1.4 → eGFR ≈ 55 (KDIGO G3a)."""
    result = compute_egfr(creatinine_mg_dl=1.4, age=68, sex="male", formula="ckd_epi_2021")
    assert result["egfr_ml_min_1_73m2"] is not None
    assert 50 <= result["egfr_ml_min_1_73m2"] <= 60
    assert result["ckd_stage"] == "G3a"
    assert result["formula"] == "ckd_epi_2021"


def test_egfr_below_30_avoids_olaparib_full_dose():
    """eGFR <30 → olaparib debe entrar en 'avoid' / 'dose_reduce'."""
    flag = renal_dosing_flag("olaparib", egfr_ml_min_1_73m2=25.0)
    assert flag["status"] in {"avoid", "dose_reduce"}


def test_egfr_normal_allows_abiraterona_full_dose():
    flag = renal_dosing_flag("abiraterone", egfr_ml_min_1_73m2=85.0)
    assert flag["status"] == "full"


def test_egfr_missing_inputs_returns_missing_flags():
    result = compute_egfr(creatinine_mg_dl=None, age=70, sex="male")
    assert "creatinine_mg_dl" in result["inputs_missing"]
    assert result["egfr_ml_min_1_73m2"] is None


# ──────────────────────────────────────────────────────────────────────
# 2. Halabi — albumin/ldh/hgb/alp + labs_missing_flags
# ──────────────────────────────────────────────────────────────────────


def test_halabi_consumes_epic2_canonical_fields():
    """`albumin_g_dl`, `ldh_u_l`, `hemoglobin_g_dl` deben cablearse al IPS."""
    patient = {
        "current_state": "m1_crpc",
        "albumin_g_dl": 2.8,
        "ldh_u_l": 310,
        "hemoglobin_g_dl": 10.1,
        "alkaline_phosphatase_u_l": 185,
        "latest_psa": 45,
        "ecog": 1,
        "bone_metastasis_count": 8,
    }
    result = predict_mcrpc_prognosis(patient)
    assert result["input_values"]["albumin"] == pytest.approx(2.8)
    assert result["input_values"]["ldh"] == pytest.approx(310.0)
    assert result["input_values"]["hemoglobin"] == pytest.approx(10.1)
    flags = result["labs_missing_flags"]
    assert flags["albumin_missing"] is False
    assert flags["any_halabi_lab_missing"] is False
    assert flags["halabi_lab_completeness"] == 1.0


def test_halabi_flags_missing_labs_when_not_captured():
    """Sin albumin ni LDH el IPS debe marcar flags explícitos para governance."""
    patient = {
        "current_state": "m1_crpc",
        "hemoglobin_g_dl": 11.5,
        "latest_psa": 10,
    }
    result = predict_mcrpc_prognosis(patient)
    flags = result["labs_missing_flags"]
    assert flags["albumin_missing"] is True
    assert flags["ldh_missing"] is True
    assert flags["any_halabi_lab_missing"] is True
    assert flags["halabi_lab_completeness"] < 0.5


def test_halabi_backward_compat_with_legacy_albumin_key():
    """El alias legacy `albumin` sigue funcionando (no rompe schemas antiguos)."""
    patient = {"current_state": "m1_crpc", "albumin": 3.9, "latest_psa": 20}
    result = predict_mcrpc_prognosis(patient)
    assert result["input_values"]["albumin"] == pytest.approx(3.9)
    assert result["labs_missing_flags"]["albumin_missing"] is False


# ──────────────────────────────────────────────────────────────────────
# 3. Genomic classifiers numeric → bandas canónicas
# ──────────────────────────────────────────────────────────────────────


def test_decipher_077_classified_high_risk():
    """Spratt 2018: Decipher ≥0.60 = alto riesgo → salvage RT + ADT."""
    v = classify_genomic_score(classifier="decipher", score=0.77)
    assert v["band"] == "high"
    # Banda alta debe traducirse en acción de intensificación
    action = (v["band_action"] or "").lower()
    assert any(keyword in action for keyword in ("rt", "adt", "intensificar", "re-estadificar"))


def test_decipher_numeric_overrides_categorical_when_discordant():
    """Si reporte dice 'favorable' pero score 0.77, la banda numérica prevalece."""
    v = classify_genomic_score(classifier="decipher", score=0.77, categorical_band="favorable")
    assert v["band"] == "high"
    assert "discord" in v["narrative"].lower() or "prevalece" in v["narrative"].lower()


def test_oncotype_band_thresholds():
    """Klein 2014: GPS <20 low, 20-40 intermediate, ≥40 high."""
    assert classify_genomic_score(classifier="oncotype", score=15)["band"] == "low"
    assert classify_genomic_score(classifier="oncotype", score=30)["band"] == "intermediate"
    assert classify_genomic_score(classifier="oncotype", score=55)["band"] == "high"


def test_unknown_classifier_returns_validation_error():
    v = classify_genomic_score(classifier="foobar", score=0.5)
    assert v["validation_error"]
    assert v["band"] is None


# ──────────────────────────────────────────────────────────────────────
# 4. Germline vs somático — NCCN PROS-H trigger
# ──────────────────────────────────────────────────────────────────────


def test_germline_brca2_surfaces_parp_eligibility_card():
    """BRCA2 germinal debe aparecer en la tarjeta con tono warning + PARP hint."""
    patient = {
        "age": 70, "sex": "male", "current_state": "m1_crpc",
        "germline_testing_performed": "1",
        "germline_pathogenic_variant": "BRCA2",
        "germline_test_date": "2025-11-10",
    }
    cards = build_epic2_clinical_cards(patient, state="m1_crpc")
    germ = next((c for c in cards if c["key"] == "epic2_germline_somatic"), None)
    assert germ is not None
    assert germ["tone"] == "warning"
    text = " ".join(germ.get("bullets", []))
    assert "olaparib" in text.lower() or "parp" in text.lower()


def test_germline_vs_somatic_distinct_fields():
    """Germinal heredable vs somático tumoral deben capturarse por separado."""
    patient = {
        "current_state": "m1_crpc",
        "germline_pathogenic_variant": "ninguna",
        "somatic_pathogenic_variant": "BRCA2",
    }
    cards = build_epic2_clinical_cards(patient, state="m1_crpc")
    germ = next((c for c in cards if c["key"] == "epic2_germline_somatic"), None)
    assert germ is not None
    items_by_label = {it["label"]: it for it in germ["items"]}
    assert items_by_label["Variante germinal"]["value"].lower() in {"ninguna", ""}
    assert items_by_label["Variante somática"]["value"].upper() == "BRCA2"


# ──────────────────────────────────────────────────────────────────────
# 5. Medication list + DDI engine expandido
# ──────────────────────────────────────────────────────────────────────


def test_normalize_medication_list_resolves_aliases():
    """`lexapro` → escitalopram canónico; `zytiga` → abiraterona."""
    meds = normalize_medication_list([
        {"name": "lexapro", "dose": "20 mg"},
        {"name": "zytiga", "dose": "1000 mg"},
    ])
    names = [m.name for m in meds]
    assert "escitalopram" in names
    assert "abiraterona" in names


def test_ddi_engine_flags_citalopram_plus_enzalutamida_major():
    """CYP2C19 induction → enzalutamida baja nivel citalopram (major)."""
    meds = normalize_medication_list([{"name": "citalopram"}, {"name": "enzalutamida"}])
    alerts = DDIEngine.check_medication_list(meds, therapy_candidate=None)
    severities = {getattr(a, "severity", None) for a in alerts}
    assert any(s in {"major", "contraindicated"} for s in severities)


def test_ddi_engine_contraindicates_ra223_plus_abiraterona():
    """ERA-223: Ra-223 + abiraterona → fracturas + mortalidad (contraindicated)."""
    meds = normalize_medication_list([{"name": "radium_223"}, {"name": "abiraterona"}])
    alerts = DDIEngine.check_medication_list(meds, therapy_candidate=None)
    assert any(getattr(a, "severity", "") == "contraindicated" for a in alerts)


def test_medication_list_card_reports_cyp_catalog_and_ddi_count():
    """La tarjeta expone total, catalogados y alertas detectadas."""
    patient = {
        "current_state": "m1_crpc",
        "medication_list": [
            {"name": "metoprolol"},
            {"name": "citalopram"},
            {"name": "enzalutamide"},
        ],
    }
    cards = build_epic2_clinical_cards(patient, state="m1_crpc")
    med_card = next((c for c in cards if c["key"] == "epic2_medication_list"), None)
    assert med_card is not None
    labels = {it["label"] for it in med_card["items"]}
    assert "Total medicamentos" in labels
    assert "Alertas DDI potenciales" in labels


# ──────────────────────────────────────────────────────────────────────
# 6. Visceral sites discriminados (Halabi HR diferenciado)
# ──────────────────────────────────────────────────────────────────────


def test_visceral_liver_triggers_critical_tone():
    """Hígado HR 2.09 (Halabi) → tarjeta visceral en tono critical."""
    patient = {
        "current_state": "m1_crpc",
        "visceral_liver": "1",
        "visceral_lung": "0",
    }
    cards = build_epic2_clinical_cards(patient, state="m1_crpc")
    visc = next((c for c in cards if c["key"] == "epic2_visceral_sites"), None)
    assert visc is not None
    assert visc["tone"] == "critical"


def test_visceral_lung_only_uses_warning_tone():
    """Pulmón HR 1.41 → warning (no crítico como hígado)."""
    patient = {
        "current_state": "m1_crpc",
        "visceral_liver": "0",
        "visceral_lung": "1",
    }
    cards = build_epic2_clinical_cards(patient, state="m1_crpc")
    visc = next((c for c in cards if c["key"] == "epic2_visceral_sites"), None)
    assert visc is not None
    assert visc["tone"] == "warning"


# ──────────────────────────────────────────────────────────────────────
# 7. EPIC 2 clinical cards — surface en profile_compass view model
# ──────────────────────────────────────────────────────────────────────


def test_epic2_cards_surface_in_profile_view_model():
    """El view model oficial debe exponer `epic2_clinical_cards` como key."""
    from prostanet.domains.patient_tracking.profile_compass import (
        build_patient_profile_view_model,
    )

    patient = {
        "id": "epic2-test",
        "age": 72, "sex": "male",
        "current_state": "m1_crpc",
        "baseline": {"baseline_psa": 25.0},
        "creatinine_mg_dl": 1.9,
        "albumin_g_dl": 2.8,
        "ldh_u_l": 310,
        "adt_start_date": "2024-06-15",
        "germline_pathogenic_variant": "BRCA2",
    }
    vm = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=None,
        latest_assessment=None,
        state_timeline=[],
        care_overlays=[],
    )
    assert "epic2_clinical_cards" in vm
    cards = vm["epic2_clinical_cards"]
    assert isinstance(cards, list)
    keys = {c.get("key") for c in cards}
    assert {"epic2_renal_function", "epic2_halabi_markers", "epic2_adt_timeline"} <= keys


def test_epic2_cards_empty_when_no_fields_captured():
    """Sin ningún campo EPIC 2 capturado, la lista debe ser vacía."""
    cards = build_epic2_clinical_cards(
        {"age": 60, "sex": "male", "current_state": "diagnostic_workup"},
        state="diagnostic_workup",
    )
    assert cards == []
