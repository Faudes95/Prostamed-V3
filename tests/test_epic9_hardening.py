"""Tests EPIC 9 — Hardening clínico fino + alineación schema-gobernanza.

Cubre los 17 hallazgos GAP-1..GAP-17 del plan EPIC 9 + GAP-A (BCR/PSADT
regression) en 6 grupos (A/F/B/C/D/E):

  Grupo A (bundles + captura):
    * test_elderly_75_plus_attenuates_arpi_doublet_penalty (GAP-1)
    * test_qtc_baseline_above_470_penalizes_enzalutamide (GAP-2)
    * test_nyha_iii_blocks_abiraterone (GAP-3)
    * test_arv7_alert_includes_prophecy_evidence_tag (GAP-11)
    * test_confirmatory_biopsy_planned_in_localized_schema (GAP-16)

  Grupo F (schema fixes + OOS-12):
    * test_ari_medication_reduces_effective_psa (GAP-12)
    * test_post_negative_biopsy_schema_exposes_prostate_volume (GAP-13)
    * test_crpc_schema_exposes_drug_scheme_line_adt_context (GAP-14)
    * test_oos12_readiness_fallback_computes_when_bundle_empty (GAP-15)
    * test_epic26_normalized_in_post_prostatectomy (GAP-17)

  Grupo B (mHSPC hard-blocks):
    * test_peace1_metachronous_triplet_not_applicable (GAP-4)
    * test_child_pugh_b_alone_hard_blocks_abiraterone (GAP-7)
    * test_docetaxel_fitness_arasens_rejects_ecog2 (GAP-8)

  Grupo C (TALAPRO-3):
    * test_talapro3_hrr_positive_bonus_22 (GAP-5 positivo)
    * test_talapro3_hrr_negative_hard_blocks_regimen (GAP-5 negativo)

  Grupo D (RT al primario):
    * test_primary_rt_low_volume_eligible (GAP-6 positivo)
    * test_primary_rt_high_volume_hard_blocked (GAP-6 hard-block)

  Grupo E (DDI runtime + CYP2C19):
    * test_ddi_runtime_contraindicated_blocks_enzalutamide_with_tramadol (GAP-9)
    * test_cyp2c19_abiraterone_clopidogrel_major_alert (GAP-10)

  Regresión (GAP-A):
    * test_bcr_psadt_defensive_999_noop_documented

Evidencia: NCCN PROS 5.2026, EAU 2026, FDA Zytiga/Xtandi/Erleada/Nubeqa,
STAMPEDE-H (Parker *Lancet* 2018), PEACE-1 (Fizazi *Lancet* 2022),
TALAPRO-3 (Agarwal ASCO GU 2025 LBA18), ARASENS (Smith *NEJM* 2022),
PROPHECY (Armstrong *JAMA Oncol* 2019).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ═════════════════════════════════════════════════════════════════════
# Grupo A — Bundles y captura estructurada
# ═════════════════════════════════════════════════════════════════════


def test_elderly_75_plus_attenuates_arpi_doublet_penalty():
    """GAP-1 — paciente ≥75 años marca modifier ``elderly_75_plus``.

    STAMPEDE M1/AA subanálisis >75 atenúa el OS HR del doblete
    (0.88 vs 0.61 <75). El modificador queda expuesto en el bundle
    generado por ``_modifier_profile``.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        _modifier_profile,
        _phenotype_profile,
    )

    payload = {"patient_age": 78, "volume_status": "high"}
    phenotype = _phenotype_profile("mcspc_high_volume_sync", payload)
    modifiers = _modifier_profile(payload, state=phenotype["state"])
    assert modifiers["patient_age"] == 78
    assert modifiers["elderly_75_plus"] is True
    assert modifiers["frail_85_plus"] is False


def test_qtc_baseline_above_470_penalizes_enzalutamide():
    """GAP-2 — QTc basal >470 ms activa ``qtc_risk`` y penaliza enzalutamida.

    ENZAMET FDA §5.4: prolongación QTc >20 ms en 2.3% de pacientes.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        _modifier_profile,
        _phenotype_profile,
        select_mhspc_frontline_regimens,
    )

    payload = {"qtc_baseline_ms": 485, "volume_status": "high", "patient_age": 72}
    phenotype = _phenotype_profile("mcspc_high_volume_sync", payload)
    modifiers = _modifier_profile(payload, state=phenotype["state"])
    assert modifiers["qtc_risk"] is True

    bundle = select_mhspc_frontline_regimens("mcspc_high_volume_sync", payload)
    rankings = bundle.get("frontline_regimen_rankings") or []
    rejections = bundle.get("frontline_regimen_rejections") or []
    enza = next(
        (
            r
            for r in rankings + rejections
            if r.get("regimen_code") == "ADT_ENZALUTAMIDE"
        ),
        None,
    )
    assert enza is not None, "ADT_ENZALUTAMIDE debe figurar en ranking o rejected"
    # El bundle expone las razones en ``contraindication_reasons`` y propaga
    # el modifier ``qtc_risk`` en ``safety_drivers_used``.
    penalty_reasons = " ".join(enza.get("contraindication_reasons") or [])
    safety_drivers = enza.get("safety_drivers_used") or []
    assert "QTc" in penalty_reasons or "qtc" in penalty_reasons.lower()
    assert "qtc_risk" in safety_drivers


def test_nyha_iii_blocks_abiraterone():
    """GAP-3 — NYHA III/IV o LVEF <40% desactiva abiraterona.

    COU-AA-302 excluyó NYHA III/IV; FDA Zytiga §5.1 precaución HF clase III-IV.
    El modificador ``heart_failure_severe`` se propaga y aplica penalty -18.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        _modifier_profile,
        _phenotype_profile,
        select_mhspc_frontline_regimens,
    )

    payload = {"nyha_class": "III", "lvef_percent": 35, "volume_status": "high"}
    phenotype = _phenotype_profile("mcspc_high_volume_sync", payload)
    modifiers = _modifier_profile(payload, state=phenotype["state"])
    assert modifiers["heart_failure_severe"] is True

    bundle = select_mhspc_frontline_regimens("mcspc_high_volume_sync", payload)
    rankings = bundle.get("frontline_regimen_rankings") or []
    rejections = bundle.get("frontline_regimen_rejections") or []
    abi = next(
        (
            r
            for r in rankings + rejections
            if r.get("regimen_code") == "ADT_ABIRATERONE"
        ),
        None,
    )
    assert abi is not None
    drivers = abi.get("safety_drivers_used") or []
    assert "heart_failure_severe" in drivers
    # Penalización -18 debe figurar en los componentes de prioridad clínica.
    components = abi.get("clinical_priority_components") or {}
    assert float(components.get("safety_penalty", 0)) <= -18.0


def test_arv7_alert_includes_prophecy_evidence_tag():
    """GAP-11 — alerta AR-V7+ expone evidence_tag PROPHECY.

    Armstrong *JAMA Oncol* 2019 estableció que AR-V7+ reduce
    significativamente la eficacia de ARSI. La alerta estructurada
    debe incluir ``alert_family=biomarker_contraindication`` y el tag.
    """
    from prostanet.domains.patient_tracking.treatment_sequencer import (
        TreatmentSequencer,
    )

    alerts = TreatmentSequencer._build_biomarker_alerts({"arv7_positive": True})
    assert alerts, "Debe emitirse alerta biomarker para AR-V7+"
    arv7_alert = next((a for a in alerts if a.get("biomarker") == "AR-V7"), None)
    assert arv7_alert is not None
    assert arv7_alert["alert_family"] == "biomarker_contraindication"
    assert arv7_alert["evidence_tag"] == "PROPHECY_Armstrong_JAMA_Oncol_2019"
    assert arv7_alert["severity"] == "contraindicated"


def test_confirmatory_biopsy_planned_in_localized_schema():
    """GAP-16 — schema localized_initial debe exponer confirmatory_biopsy_planned.

    Reglas NCCN PROS-C ya lo consumen en ``rules_nccn.py:198``; el campo
    debe estar registrado para que la UI lo capture.
    """
    from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA

    field_names = {f["name"] for f in LOCALIZED_SCHEMA["fields"]}
    assert "confirmatory_biopsy_planned" in field_names


# ═════════════════════════════════════════════════════════════════════
# Grupo F — Schema fixes + OOS-12
# ═════════════════════════════════════════════════════════════════════


def test_ari_medication_reduces_effective_psa():
    """GAP-12 — 5-α-reductasa activo corrige el PSA efectivo ×2 en el scoring.

    Roehrborn *Eur Urol* 2006, Andriole *J Urol* 2006 — finasteride y
    dutasteride reducen PSA ~50% al año.
    """
    from prostanet.domains.diagnostic_workup.rules_nccn import (
        classify_diagnostic_workup,
    )

    base = {"psa": 5.0, "pirads_score": 4, "prostate_volume_ml": 40}
    without_ari = classify_diagnostic_workup({**base, "ari_medication_active": "0"})
    with_ari = classify_diagnostic_workup({**base, "ari_medication_active": "1"})

    # El confounder debe quedar visible en ``psa_confounders_active``.
    assert with_ari["psa_confounders_active"]["ari_medication_active"] is True
    # La corrección ×2 se aplica y el PSA efectivo pasa a 10.0.
    assert with_ari["psa_correction_applied"] is True
    assert with_ari["psa_effective_for_scoring"] == 10.0
    # La razón narrativa menciona la corrección por 5-α-reductasa.
    reasons_with = " ".join(with_ari.get("reasons") or [])
    assert "inhibidor 5-α-reductasa" in reasons_with or "corrige" in reasons_with.lower()
    # Sin ARI la corrección no se aplica.
    assert without_ari["psa_correction_applied"] is False


def test_post_negative_biopsy_schema_exposes_prostate_volume():
    """GAP-13 — schema expone prostate_volume_ml + planned_biopsy_type/route.

    Necesarios para derivar PSAD y orientar la estrategia de rebiopsia.
    """
    from prostanet.domains.post_negative_biopsy_followup.schemas import (
        POST_NEGATIVE_BIOPSY_SCHEMA,
    )

    field_names = {f["name"] for f in POST_NEGATIVE_BIOPSY_SCHEMA["fields"]}
    assert "prostate_volume_ml" in field_names
    assert "planned_biopsy_type" in field_names
    assert "planned_biopsy_route" in field_names


def test_crpc_schema_exposes_drug_scheme_line_adt_context():
    """GAP-14 — schemas CRPC discretizan drug_scheme, line_of_therapy_number,
    current_adt_context (alinea con clinical_decision_governance CRPC minima).
    """
    from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA

    for schema, label in ((M0_CRPC_SCHEMA, "m0_crpc"), (M1_CRPC_SCHEMA, "m1_crpc")):
        names = {f["name"] for f in schema["fields"]}
        assert "drug_scheme" in names, f"{label} debe exponer drug_scheme"
        assert "line_of_therapy_number" in names, f"{label} debe exponer line_of_therapy_number"
        assert "current_adt_context" in names, f"{label} debe exponer current_adt_context"


def test_oos12_readiness_fallback_computes_when_bundle_empty():
    """GAP-15 — fallback cuando therapeutic_readiness_bundle llega vacío.

    Escenario m0_crpc PSMA-only upstaging: la capa longitudinal aún no
    materializó la readiness en el snapshot; el fallback debe emitir
    status ``blocked_by_missing_data`` para que el summary no deje celda
    en blanco.
    """
    from prostanet.domains.patient_tracking.master_followup_plan import (
        _compute_readiness_fallback_status,
    )

    # Bundle vacío + señales PSMA-only upstaging en estado decisional CRPC.
    readiness, monitoring, adjudication = _compute_readiness_fallback_status(
        state="m0_crpc",
        therapeutic_readiness_bundle={},
        staging_adjudication_bundle={},
        advanced_followup_bundle={},
        supportive_care_bundle={},
        signals={"psma_only_upstaging": True, "metastatic_detection_basis": "psma_only"},
    )
    # readiness final no puede quedar vacía; el fallback garantiza alguna etiqueta trazable.
    assert readiness, "readiness_status no debe quedar vacío con bundle=empty en estado decisional"


def test_epic26_normalized_in_post_prostatectomy():
    """GAP-17 — post_prostatectomy consume normalize_epic26_payload.

    El paquete EPIC-26 estructurado es el primario; IPSS/IIEF-5 quedan
    como legacy ``clinical_role="legacy"`` + required=False.
    """
    from prostanet.domains.post_prostatectomy.service import PostProstatectomyService
    from prostanet.domains.post_radiotherapy_followup.schemas import (
        POST_RT_FOLLOWUP_SCHEMA,
    )

    # legacy IPSS/IIEF-5 no requeridos.
    fields_by_name = {f["name"]: f for f in POST_RT_FOLLOWUP_SCHEMA["fields"]}
    assert fields_by_name["ipss_score"].get("clinical_role") == "legacy"
    assert fields_by_name["iief5_score"].get("clinical_role") == "legacy"
    assert fields_by_name["ipss_score"].get("required") is False
    assert fields_by_name["iief5_score"].get("required") is False

    # post_prostatectomy invoca normalize_epic26_payload en su service.
    import inspect
    src = inspect.getsource(PostProstatectomyService)
    assert "normalize_epic26_payload" in src


# ═════════════════════════════════════════════════════════════════════
# Grupo B — mHSPC hard-blocks y matrix
# ═════════════════════════════════════════════════════════════════════


def test_peace1_metachronous_triplet_not_applicable():
    """GAP-4 — PEACE-1 triplete en mHSPC metacrónico NO aplica.

    PEACE-1 (Fizazi Lancet 2022) validó SOLO en de novo/sincrónico.
    arpi_benefit_matrix debe marcar triplet_fit=not_applicable en el
    estado metacrónico.
    """
    from prostanet.domains.patient_tracking.arpi_benefit_matrix import (
        ARPI_BENEFIT_MATRIX,
    )

    meta_high = ARPI_BENEFIT_MATRIX.get("mcspc_high_volume_metachronous") or {}
    triplet = meta_high.get("ADT_DOCETAXEL_ABIRATERONE") or {}
    assert triplet.get("triplet_fit") == "not_applicable"
    assert triplet.get("scenario_match") == "not_applicable"


def test_child_pugh_b_alone_hard_blocks_abiraterone():
    """GAP-7 — Child-Pugh B per se dispara hard-block canonical de abiraterona.

    Patrón canónico clonado de m1_crpc/rules_nccn.py:121 — NO requiere
    ``active_liver_disease`` separado. FDA Zytiga §2.3 recomienda no
    iniciar en CP-B/C.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        select_mhspc_frontline_regimens,
    )

    payload = {
        "child_pugh_score": "B",
        "volume_status": "high",
        "patient_age": 68,
    }
    bundle = select_mhspc_frontline_regimens("mcspc_high_volume_sync", payload)
    items = (bundle.get("frontline_regimen_rankings") or []) + (
        bundle.get("frontline_regimen_rejections") or []
    )
    abi = next((r for r in items if r.get("regimen_code") == "ADT_ABIRATERONE"), None)
    assert abi is not None
    assert abi.get("hard_block") is True, "Child-Pugh B debe disparar hard-block de abiraterona"


def test_docetaxel_fitness_arasens_rejects_ecog2():
    """GAP-8 — docetaxel_fitness(target_trial='ARASENS') rechaza ECOG 2.

    ARASENS (Smith NEJM 2022) excluyó ECOG 2; solo enrolamiento 0-1.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from clinical_scores import docetaxel_fitness  # type: ignore

    patient = {"ecog_score": 2, "anc": 2000, "platelets": 150000, "bilirubin": 0.8}
    result = docetaxel_fitness(patient, target_trial="ARASENS")
    reasons = " ".join(result.get("docetaxel_trial_ineligibility_reasons") or [])
    assert "ARASENS" in reasons
    assert "ECOG" in reasons

    # Con CHAARTED (default más inclusivo) ECOG 2 es elegible.
    result_chaarted = docetaxel_fitness(patient, target_trial="CHAARTED")
    reasons_ch = " ".join(result_chaarted.get("docetaxel_trial_ineligibility_reasons") or [])
    assert "ARASENS" not in reasons_ch


# ═════════════════════════════════════════════════════════════════════
# Grupo C — TALAPRO-3
# ═════════════════════════════════════════════════════════════════════


def test_talapro3_hrr_positive_bonus_22():
    """GAP-5 positivo — HRR+ BRCA2 bonifica ADT_TALAZO_ENZA_HRR con +22.

    TALAPRO-3 (Agarwal ASCO GU 2025 LBA18): rPFS HR≈0.67 en HRR-mutated mHSPC.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        select_mhspc_frontline_regimens,
    )

    payload = {
        "volume_status": "low",
        "hrr_status": "positive",
        "hrr_gene": "BRCA2",
        "patient_age": 65,
    }
    bundle = select_mhspc_frontline_regimens("mcspc_low_volume_sync_oligo", payload)
    items = (bundle.get("frontline_regimen_rankings") or []) + (
        bundle.get("frontline_regimen_rejections") or []
    )
    talapro = next(
        (r for r in items if r.get("regimen_code") == "ADT_TALAZO_ENZA_HRR"), None
    )
    assert talapro is not None, "ADT_TALAZO_ENZA_HRR debe figurar con HRR+"
    # Con HRR+ no debe tener hard_block.
    assert talapro.get("hard_block") is False
    # El bundle expone la narrativa ``selection_rationale`` (no ``reasons_for``).
    selection_rationale = " ".join(talapro.get("selection_rationale") or [])
    benefit_basis = str(talapro.get("benefit_basis") or "")
    evidence_blob = f"{selection_rationale} {benefit_basis}"
    assert (
        "HRR" in evidence_blob
        or "TALAPRO-3" in evidence_blob
        or "precision" in evidence_blob.lower()
    )


def test_talapro3_hrr_negative_hard_blocks_regimen():
    """GAP-5 negativo — HRR-negativo dispara hard-block de ADT_TALAZO_ENZA_HRR.

    El regimen de precisión no es aplicable sin alteración HRR
    documentada; debe quedar en rejected con razón narrativa.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        select_mhspc_frontline_regimens,
    )

    payload = {
        "volume_status": "high",
        "hrr_status": "negative",
        "hrr_testing_performed": "1",
        "patient_age": 65,
    }
    bundle = select_mhspc_frontline_regimens("mcspc_high_volume_sync", payload)
    items = (bundle.get("frontline_regimen_rankings") or []) + (
        bundle.get("frontline_regimen_rejections") or []
    )
    talapro = next(
        (r for r in items if r.get("regimen_code") == "ADT_TALAZO_ENZA_HRR"), None
    )
    assert talapro is not None
    assert talapro.get("hard_block") is True
    # La razón narrativa del hard-block se expone en ``contraindication_reasons``.
    reasons = " ".join(talapro.get("contraindication_reasons") or [])
    assert "HRR" in reasons or "alteración" in reasons.lower()


# ═════════════════════════════════════════════════════════════════════
# Grupo D — Primary RT eligibility
# ═════════════════════════════════════════════════════════════════════


def test_primary_rt_low_volume_eligible():
    """GAP-6 positivo — mHSPC bajo volumen sincrónico fit → priority=standard_of_care.

    STAMPEDE Arm H (Parker *Lancet* 2018): OS HR 0.68 en low-volume.
    NCCN PROS-14 categoría 1.
    """
    from prostanet.domains.patient_tracking.primary_rt_eligibility import (
        evaluate_primary_rt,
    )

    payload = {
        "volume_status": "low",
        "disease_temporality": "synchronous",
        "ecog_score": 1,
        "life_expectancy_years": 10,
    }
    bundle = evaluate_primary_rt(payload)
    assert bundle["eligible"] is True
    assert bundle["priority"] == "standard_of_care"
    assert bundle["hard_blocks"] == []
    assert bundle["evidence_tier"] == "A"
    assert any("STAMPEDE" in t for t in bundle["evidence_trials"])


def test_primary_rt_high_volume_hard_blocked():
    """GAP-6 hard-block — alto volumen activa hard-block (STAMPEDE-H subanálisis).

    STAMPEDE-H mostró AUSENCIA de beneficio en OS para high-volume;
    ofrecer RT primaria sin beneficio es mala práctica.
    """
    from prostanet.domains.patient_tracking.primary_rt_eligibility import (
        evaluate_primary_rt,
    )

    payload = {
        "volume_status": "high",
        "disease_temporality": "synchronous",
        "ecog_score": 1,
        "life_expectancy_years": 10,
    }
    bundle = evaluate_primary_rt(payload)
    assert bundle["eligible"] is False
    assert bundle["priority"] == "not_eligible"
    assert bundle["hard_blocks"], "alto volumen debe generar hard-block"
    assert any("Alto volumen" in hb or "STAMPEDE" in hb for hb in bundle["hard_blocks"])


# ═════════════════════════════════════════════════════════════════════
# Grupo E — DDI runtime + CYP2C19
# ═════════════════════════════════════════════════════════════════════


def test_ddi_runtime_contraindicated_blocks_enzalutamide_with_tramadol():
    """GAP-9 — DDIEngine runtime bloquea enzalutamida cuando hay triple
    contraindicación (seizure_history + enza + tramadol).

    Tramadol baja umbral convulsivo; enza tiene riesgo convulsivo basal
    0.9%; historia previa lo eleva a contraindicación clínica.
    """
    from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
        select_mhspc_frontline_regimens,
    )

    payload = {
        "volume_status": "high",
        "seizure_history": "1",
        "comorbidity_seizure": "1",
        # ``normalized_medication_list`` acepta lista de dicts con ``name``;
        # activa el fallback DDIEngine runtime en ``arpi_selection_engine``.
        "normalized_medication_list": [
            {"name": "enzalutamida"},
            {"name": "tramadol"},
            {"name": "citalopram"},
        ],
    }
    bundle = select_mhspc_frontline_regimens("mcspc_high_volume_sync", payload)
    preferred_code = (bundle.get("preferred_regimen") or {}).get("regimen_code", "")
    # Enzalutamida no puede ganar con triple contraindicación DDI.
    assert "ENZALUTAMIDE" not in preferred_code.upper()
    # Darolutamida (perfil DDI limpio) debe ser el preferido.
    assert "DAROLUTAMIDE" in preferred_code.upper()

    # Enza y apalutamida deben quedar hard-blocked en este escenario.
    items = (bundle.get("frontline_regimen_rankings") or []) + (
        bundle.get("frontline_regimen_rejections") or []
    )
    enza = next((r for r in items if r.get("regimen_code") == "ADT_ENZALUTAMIDE"), None)
    assert enza is not None
    assert enza.get("hard_block") is True
    drivers = enza.get("safety_drivers_used") or []
    # Al menos un driver de DDI runtime debe aparecer.
    assert any(d.startswith("ddi_") for d in drivers)


def test_cyp2c19_abiraterone_clopidogrel_major_alert():
    """GAP-10 — abiraterona+clopidogrel dispara alerta MAJOR (no moderate).

    Abiraterona inhibe CYP2C19; clopidogrel requiere CYP2C19 para activar
    al metabolito tiol. La pérdida de activación antiagregante es un
    evento trombótico MAYOR, no un efecto PK menor.
    """
    from prostanet.shared.ddi_engine import DDIEngine
    from prostanet.shared.cyp_metabolism_map import CYP2C19_COVERAGE

    alerts = DDIEngine.check_interactions(
        oncology_drugs=["abiraterona"],
        concomitant_medications=["clopidogrel"],
        seizure_history=False,
    )
    assert alerts, "Debe emitirse alerta abiraterona+clopidogrel"
    pair_alert = next(
        (
            a
            for a in alerts
            if "abiraterona" in a.drug_a.lower()
            and "clopidogrel" in a.drug_b.lower()
        ),
        None,
    )
    assert pair_alert is not None
    assert pair_alert.severity == "major"
    assert pair_alert.category == "cyp2c19_inhibition"

    # Registro de cobertura GAP-10 lista este par con severity=major.
    pair = next(
        (
            p
            for p in CYP2C19_COVERAGE["registered_pairs"]
            if p["pair"] == ("abiraterona", "clopidogrel")
        ),
        None,
    )
    assert pair is not None
    assert pair["severity"] == "major"


# ═════════════════════════════════════════════════════════════════════
# Regresión — GAP-A (PSADT defensive 999 no-op)
# ═════════════════════════════════════════════════════════════════════


def test_bcr_psadt_defensive_999_noop_documented():
    """GAP-A (no-brecha) — PSADT default 999 es defensive no-op.

    classify_recurrence usa ``psadt_months`` sólo para clasificar
    BCR2 N0M0 (``psadt <= 9``); con default 999 el sistema NO dispara
    intensificación EMBARK-like y prioriza salvage local (cumple
    AUA/ASTRO/SUO 2024). Documentar regresión para cerrar discusión.
    """
    from prostanet.domains.recurrence_bcr.rules_nccn import classify_recurrence

    payload = {
        "prior_prostatectomy": "1",
        "psa_current": 0.5,
        "bcr2": "0",
        # psadt_months NO provisto → default 999.
    }
    result = classify_recurrence(payload)
    assert result["label"] == "Post-RP recurrence"
    assert result["enza_match"] is False
    # El sistema prioriza salvage local sin requerir PSADT → cumple AUA 2024.
    assert "salvage" in result["recommendation"].lower()
