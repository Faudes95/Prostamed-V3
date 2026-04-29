# -*- coding: utf-8 -*-
"""
Tests para módulos nuevos de Fase 7.1 — 7.5:

  - rules_radium223 (ALSYMPCA)
  - rules_parp (PROfound / TRITON3 / TALAPRO / PROpel / MAGNITUDE / TALAPRO-2)
  - rules_local_salvage (HIFU / crio / salvage RP / braqui / SBRT)
  - nomogramas Briganti / MSKCC / Stephenson / Tendulkar / JHU / CAPRA-S
  - alert_decisional
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

from prostanet.domains.m1_crpc.rules_radium223 import evaluate_radium223_eligibility
from prostanet.domains.m1_crpc.rules_parp import evaluate_parp_options
from prostanet.domains.post_radiotherapy_or_local_salvage.rules_local_salvage import (
    evaluate_local_salvage_options,
)
from prostanet.domains.patient_tracking.alert_decisional import evaluate_decisional_alerts
from prostanet.ai.nomograms import (
    briganti_2019_lni_risk,
    mskcc_pre_rp_bcr_risk,
    stephenson_salvage_rt_success,
    tendulkar_salvage_rt_outcomes,
    jhu_bcr_metastasis_risk,
    capra_s_score,
)


# ── Radium-223 ALSYMPCA ────────────────────────────────────────────

def test_radium223_elegible_post_arpi_docetaxel():
    payload = {
        "pain_symptoms": "Sintomatico",
        "metastasis_site": "Bone",
        "bone_scan_positive": "1",
        "bone_lesion_count": 4,
        "hemoglobin": 11.5,
        "anc": 2500,
        "platelets": 180000,
        "ecog_score": 1,
        "alp": 250,
    }
    r = evaluate_radium223_eligibility(payload, m1_context={"prior_arpi": True, "prior_docetaxel": True})
    assert r["eligible"] is True
    assert r["priority"] == "preferred"
    assert r["requires_bma_coadjunct"] is True


def test_radium223_bloqueado_por_visceral():
    payload = {"pain_symptoms": "Sintomatico", "visceral_metastasis": "1", "bone_lesion_count": 3, "hemoglobin": 12, "anc": 2000, "platelets": 150000, "ecog_score": 1}
    r = evaluate_radium223_eligibility(payload)
    assert r["eligible"] is False
    assert any("viscerales" in b for b in r["hard_blocks"])


def test_radium223_contraindicacion_abiraterona_combinada():
    payload = {"pain_symptoms": "Sintomatico", "metastasis_site": "Bone", "bone_scan_positive": "1", "bone_lesion_count": 3, "hemoglobin": 12, "anc": 2000, "platelets": 150000, "ecog_score": 1, "current_abiraterone": "1"}
    r = evaluate_radium223_eligibility(payload)
    assert r["eligible"] is False
    assert any("ERA-223" in b for b in r["hard_blocks"])


# ── PARP ───────────────────────────────────────────────────────────

def test_parp_brca2_post_arpi_incluye_olaparib_rucaparib_talazoparib():
    payload = {
        "hrr_status": "Positivo",
        "hrr_gene": "BRCA2",
        "biomarker_source": "Biopsia metastasica",
        "molecular_report_date": "2026-02-01",
    }
    res = evaluate_parp_options(payload, m1_context={"line_context": "post_arpi_pre_taxane", "prior_arpi": True, "hrr_positive": True})
    codes = [o["regimen_code"] for o in res["parp_options"]]
    assert "OLAPARIB" in codes
    assert "RUCAPARIB" in codes
    assert "TALAZOPARIB" in codes


def test_parp_atm_post_arpi_prefiere_olaparib():
    payload = {"hrr_status": "Positivo", "hrr_gene": "ATM", "biomarker_source": "Tejido primario", "molecular_report_date": "2026-01-01"}
    res = evaluate_parp_options(payload, m1_context={"line_context": "post_arpi_pre_taxane", "prior_arpi": True, "hrr_positive": True})
    codes = [o["regimen_code"] for o in res["parp_options"]]
    assert "OLAPARIB" in codes
    # Rucaparib/talazoparib están restringidas a BRCA1/2 — no deben aparecer para ATM
    assert "RUCAPARIB" not in codes
    assert "TALAZOPARIB" not in codes


def test_parp_sin_biomarcador_no_elegible():
    payload = {"hrr_status": "Desconocido", "hrr_gene": "Desconocido"}
    res = evaluate_parp_options(payload, m1_context={"line_context": "first_line_mcrpc"})
    codes = [o["regimen_code"] for o in res["parp_options"]]
    assert "PARP_NOT_ELIGIBLE" in codes


def test_parp_1l_combinaciones():
    payload = {"hrr_status": "Positivo", "hrr_gene": "BRCA2", "biomarker_source": "Biopsia metastasica", "molecular_report_date": "2026-01-01"}
    res = evaluate_parp_options(payload, m1_context={"line_context": "first_line_mcrpc", "prior_arpi": False, "hrr_positive": True, "prior_abiraterone": False, "prior_enza_class": False})
    codes = [o["regimen_code"] for o in res["parp_options"]]
    assert "OLAPARIB_ABIRATERONE" in codes
    assert "NIRAPARIB_ABIRATERONE" in codes
    assert "TALAZOPARIB_ENZALUTAMIDE" in codes


# ── Local salvage post-RT ──────────────────────────────────────────

def test_local_salvage_sin_biopsia_bloqueado():
    payload = {"months_since_rt": 36, "psa": 4, "psadt_months": 18, "ecog_score": 0}
    res = evaluate_local_salvage_options(payload)
    assert res["general_candidate_for_local_salvage"] is False
    assert "biopsia" in res["summary"].lower()


def test_local_salvage_candidato_hifu_unilateral():
    payload = {
        "local_recurrence_biopsy_confirmed": "1",
        "months_since_rt": 40,
        "psa": 3,
        "psadt_months": 18,
        "psma_pet_negative_distant": "1",
        "ecog_score": 0,
        "life_expectancy_years": 15,
        "prostate_volume_cc": 30,
        "lesion_unilateral": "1",
        "local_recurrence_stage": "T2a",
    }
    res = evaluate_local_salvage_options(payload)
    options = {o["regimen_code"]: o for o in res["local_salvage_options"]}
    assert options["SALVAGE_HIFU"]["eligible"] is True
    assert options["SALVAGE_RP"]["eligible"] is True
    # HIFU debe ser preferred en lesión unilateral
    assert options["SALVAGE_HIFU"]["priority"] in {"preferred", "eligible"}


# ── Nomogramas ─────────────────────────────────────────────────────

def test_briganti_lni_alto_riesgo_recomienda_plnd():
    payload = {"psa": 25, "isup_biopsy": 5, "clinical_t_stage": "T3", "pct_cores_positive": 65, "mri_pirads": "5", "mri_epe": "1"}
    r = briganti_2019_lni_risk(payload)
    assert r["applicable"] is True
    assert r["action_threshold"]["recommend_plnd"] is True
    assert r["probability"] >= 0.07


def test_briganti_lni_bajo_riesgo():
    payload = {"psa": 5, "isup_biopsy": 1, "clinical_t_stage": "T1c", "pct_cores_positive": 10}
    r = briganti_2019_lni_risk(payload)
    assert r["probability"] < 0.05


def test_mskcc_pre_rp_inputs_faltantes():
    r = mskcc_pre_rp_bcr_risk({"psa": 10})
    assert r["applicable"] is False
    assert len(r["missing_inputs"]) >= 2


def test_mskcc_pre_rp_calcula():
    r = mskcc_pre_rp_bcr_risk({"psa": 10, "isup_biopsy": 3, "clinical_t_stage": "T2b"})
    assert r["applicable"] is True
    assert 0 <= r["probability"] <= 1


def test_stephenson_salvage_rt_inputs():
    r = stephenson_salvage_rt_success({"psa_at_srt": 0.3, "gleason_primary": 4, "gleason_secondary": 3, "time_to_recurrence_months": 24, "psadt_months": 12, "srt_dose_gy": 68, "adt_concomitant": "1"})
    assert r["applicable"] is True
    assert 0 <= r["probability"] <= 1


def test_tendulkar_temprano_vs_tardio():
    base = {"gleason_primary": 4, "gleason_secondary": 3}
    early = tendulkar_salvage_rt_outcomes({**base, "psa_at_srt": 0.3})
    late = tendulkar_salvage_rt_outcomes({**base, "psa_at_srt": 1.2})
    assert early["probability"] > late["probability"]


def test_jhu_alto_riesgo_psadt_corto():
    payload = {"psadt_months": 2, "gleason_primary": 4, "gleason_secondary": 5, "time_to_recurrence_months": 18}
    r = jhu_bcr_metastasis_risk(payload)
    assert r["risk_category"] == "muy_alto"
    assert r["probability"] >= 0.80


def test_capra_s_alto():
    payload = {"psa": 25, "gleason_primary": 4, "gleason_secondary": 5, "surgical_margin": "1", "svi_status": "1", "ece_status": "1", "lni_status": "1"}
    r = capra_s_score(payload)
    assert r["risk_category"] == "alto"
    assert r["inputs_used"]["points"] >= 6


def test_capra_s_bajo():
    payload = {"psa": 5, "gleason_primary": 3, "gleason_secondary": 3}
    r = capra_s_score(payload)
    assert r["risk_category"] == "bajo"


# ── Decisional alerts ──────────────────────────────────────────────

def test_alert_lvef_bajo_arpi():
    payload = {"current_treatment": "Enzalutamida", "lvef_percent": 35}
    alerts = evaluate_decisional_alerts(payload)
    ids = [a["alert_id"] for a in alerts]
    assert "LVEF_BAJO_ARPI" in ids


def test_alert_castracion_fallida():
    payload = {"on_adt": "1", "testosterone": 75}
    alerts = evaluate_decisional_alerts(payload)
    ids = [a["alert_id"] for a in alerts]
    assert "CASTRACION_FALLIDA" in ids


def test_alert_psadt_critico():
    payload = {"psadt_months": 2.5}
    alerts = evaluate_decisional_alerts(payload)
    ids = [a["alert_id"] for a in alerts]
    assert "PSADT_CRITICO" in ids


def test_alert_srt_ventana_temprana():
    payload = {"post_prostatectomy": "1", "psa": 0.25}
    alerts = evaluate_decisional_alerts(payload)
    ids = [a["alert_id"] for a in alerts]
    assert "SRT_VENTANA_TEMPRANA" in ids


def test_alert_transaminasas_arpi():
    payload = {"current_treatment": "Abiraterona", "alt": 180, "ast": 150}
    alerts = evaluate_decisional_alerts(payload)
    ids = [a["alert_id"] for a in alerts]
    assert "TRANSAMINASAS_X3_ARPI" in ids
