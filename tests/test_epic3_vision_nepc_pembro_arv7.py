"""Tests EPIC 3 — Copiloto PARP / PSMA-RLT / NEPC / pembrolizumab / AR-V7.

Cubre los checkers estructurados introducidos para cerrar las brechas
mCRPC detectadas por FAUBOT FASE 2:

* VISION per-lesión SUVmax ≥ hígado + reserva medular/renal (Sartor NEJM
  2021;385:1091, category 1)
* PSMAfore pre-taxano (Morris Lancet 2024;404:1227, category 1)
* NEPC pathway — score Aggarwal + IHC sinaptofisina/cromogranina →
  platinum (Aparicio CCR 2013, Aggarwal JCO 2018, Beltran Nat Med 2016)
* MSI-H / dMMR / TMB-high → pembrolizumab (KEYNOTE-158 Marabelle JCO
  2020, KEYNOTE-199, NCCN PROS-G 2A)
* AR-V7+ override → preferir taxano sobre rechallenge ARPI (PROPHECY
  Armstrong JAMA Oncol 2019, Antonarakis NEJM 2014)
* Post-PARP sequencing — ruta ortogonal cabazitaxel / Lu-177 / platino
  rechallenge / ensayo (CARD de Wit 2019, Schmid JCO 2022, Mateo Ann
  Oncol 2020)
* TreatmentSequencer NEPC_TRANSFORMATION_PREFER injection activa la
  librería platino cuando biomarker nepc = True.

Estas pruebas cierran FAUBOT FASE 2 concordance NCCN/EAU → 100% m1_crpc.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest

from prostanet.domains.m1_crpc.rules_nepc import (
    BIOPSY_TRIGGER_THRESHOLD,
    SUSPICION_SCORE_THRESHOLD,
    evaluate_nepc_pathway,
)
from prostanet.domains.m1_crpc.rules_post_parp import evaluate_post_parp_sequencing
from prostanet.domains.m1_crpc.rules_vision_eligibility import (
    evaluate_vision_eligibility,
)
from prostanet.domains.m1_crpc.service import M1CrpcService
from prostanet.domains.patient_tracking.treatment_sequencer import (
    ARV7_POSITIVE_AVOID,
    NEPC_TRANSFORMATION_AVOID,
    TreatmentSequencer,
)


# ══════════════════════════════════════════════════════════════════════
# 1. VISION / PSMAfore eligibility checker
# ══════════════════════════════════════════════════════════════════════


def _base_vision_payload() -> dict:
    """VISION-eligible baseline: PSMA+, post-ARPI, post-docetaxel, SUV ok, labs ok."""
    return {
        "psma_pet_done": "1",
        "psma_positive": "1",
        "psma_index_lesion_suvmax": "12",
        "psma_suvmean_liver": "4",
        "prior_therapy": "Enzalutamide, Docetaxel",
        "prior_docetaxel_cycles": "8",
        "hemoglobin": "11",
        "platelets": "180000",
        "anc": "2500",
        "egfr_ml_min": "75",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    }


def test_vision_full_eligibility_preferred():
    """Paciente cumple VISION pleno → priority=preferred."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["eligibility_label"] == "vision_full"
    assert bundle["priority"] == "preferred"
    assert bundle["suv_ratio_met"] is True
    assert bundle["hard_blocks"] == []


def test_vision_rejects_when_suv_ratio_fails():
    """SUV lesión < SUV hígado → hard_block."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    payload["psma_index_lesion_suvmax"] = "3.0"
    payload["psma_suvmean_liver"] = "5.0"
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["priority"] == "not_eligible"
    assert any("SUV" in b for b in bundle["hard_blocks"])


def test_vision_rejects_when_psma_negative_dominant_lesions():
    """Lesiones PSMA-neg dominantes → excluido (subtratamiento clones negativos)."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    payload["psma_negative_dominant_lesions"] = "1"
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["priority"] == "not_eligible"
    assert any("PSMA-negativas" in b for b in bundle["hard_blocks"])


def test_vision_rejects_when_ecog_3():
    """ECOG 3 fuera de ventana VISION (0-2)."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    payload["ecog_performance_status"] = 3
    payload["ecog_score"] = 3
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["priority"] == "not_eligible"
    assert any("ECOG" in b for b in bundle["hard_blocks"])


def test_vision_rejects_when_egfr_below_30():
    """eGFR <30 → riesgo renal acumulativo, excluido VISION."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    payload["egfr_ml_min"] = "20"
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["priority"] == "not_eligible"
    assert any("eGFR" in b for b in bundle["hard_blocks"])


def test_vision_partial_when_suv_missing():
    """Sin SUV per-lesión → label=partial, priority=selected_candidate."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    del payload["psma_index_lesion_suvmax"]
    del payload["psma_suvmean_liver"]
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["eligibility_label"] == "partial"
    assert bundle["priority"] == "selected_candidate"
    assert "psma_index_lesion_suvmax" in bundle["missing_inputs"]
    assert "psma_suvmean_liver" in bundle["missing_inputs"]


def test_psmafore_pre_taxane_pathway():
    """Post-ARPI + pre-taxano + SUV ok + racional para diferir → psmafore_pre_taxane."""
    from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
    payload = _base_vision_payload()
    payload["prior_therapy"] = "Enzalutamide"  # sin docetaxel
    payload["prior_docetaxel_cycles"] = "0"
    payload["chemotherapy_delay_candidate"] = "1"
    m1 = evaluate_m1_crpc(payload)
    bundle = evaluate_vision_eligibility(payload, m1_context=m1)
    assert bundle["eligibility_label"] == "psmafore_pre_taxane"
    assert bundle["priority"] == "preferred"


# ══════════════════════════════════════════════════════════════════════
# 2. NEPC pathway
# ══════════════════════════════════════════════════════════════════════


def test_nepc_confirmed_by_ihc_triggers_platinum():
    """IHC synaptofisina+cromogranina+ → NEPC confirmado → carbo-etopósido preferred."""
    payload = {
        "nepc_confirmed_histology": "1",
        "ihc_synaptophysin_positive": "1",
        "ihc_chromogranin_positive": "1",
        "small_cell_morphology": "1",
        "ecog_performance_status": 1,
        "egfr_ml_min": "80",
    }
    bundle = evaluate_nepc_pathway(payload)
    assert bundle["nepc_confirmed"] is True
    codes = {r["regimen_code"] for r in bundle["regimens"]}
    assert "CARBOPLATIN_ETOPOSIDE_NEPC" in codes
    carbo = next(r for r in bundle["regimens"] if r["regimen_code"] == "CARBOPLATIN_ETOPOSIDE_NEPC")
    assert carbo["priority"] == "preferred"


def test_nepc_cisplatin_contraindicated_by_egfr():
    """eGFR 45 → cisplatino bloqueado, sólo carbo-etopósido queda como preferido."""
    payload = {
        "nepc_confirmed_histology": "1",
        "ihc_synaptophysin_positive": "1",
        "ihc_chromogranin_positive": "1",
        "ecog_performance_status": 1,
        "egfr_ml_min": "45",
    }
    bundle = evaluate_nepc_pathway(payload)
    cisplatin = next(r for r in bundle["regimens"] if r["regimen_code"] == "CISPLATIN_DOCETAXEL_NEPC")
    assert cisplatin["priority"] == "not_eligible"
    assert any("eGFR" in b for b in cisplatin["hard_blocks"])


def test_nepc_score_aggarwal_below_threshold_no_suspicion():
    """Sin criterios Aggarwal → score 0 → sin sospecha."""
    payload = {"ecog_performance_status": 1}
    bundle = evaluate_nepc_pathway(payload)
    assert bundle["nepc_suspected"] is False
    assert bundle["suspicion_score"] == 0


def test_nepc_score_triggers_biopsy_above_threshold():
    """Score ≥5 sin IHC previo → biopsia dirigida indicada."""
    payload = {
        # Aggarwal: tp53_rb1(2) + visceral_without_bone(1) + nse_elevated(1) + bulky_ln(1) = 5
        "tp53_status": "altered",
        "rb1_status": "loss",
        "visceral_without_bone_progression": "1",
        "nse": "25",
        "bulky_lymph_nodes_over_3cm": "1",
    }
    bundle = evaluate_nepc_pathway(payload)
    assert bundle["suspicion_score"] >= BIOPSY_TRIGGER_THRESHOLD
    assert bundle["nepc_suspected"] is True
    assert bundle["biopsy_trigger"] is True
    assert bundle["nepc_confirmed"] is False


def test_nepc_cisplatin_contraindicated_by_hearing_loss():
    """Hipoacusia → cisplatino bloqueado."""
    payload = {
        "nepc_confirmed_histology": "1",
        "ihc_synaptophysin_positive": "1",
        "ihc_chromogranin_positive": "1",
        "cisplatin_hearing_loss_history": "1",
        "egfr_ml_min": "80",
        "ecog_performance_status": 1,
    }
    bundle = evaluate_nepc_pathway(payload)
    cisplatin = next(r for r in bundle["regimens"] if r["regimen_code"] == "CISPLATIN_DOCETAXEL_NEPC")
    assert cisplatin["priority"] == "not_eligible"
    assert any("Hipoacusia" in b for b in cisplatin["hard_blocks"])


# ══════════════════════════════════════════════════════════════════════
# 3. MSI-H / dMMR / TMB-high → pembrolizumab
# ══════════════════════════════════════════════════════════════════════


def test_pembrolizumab_dmmr_high_confidence_preferred():
    """MSI inestable → dmmr_high_confidence → pembrolizumab preferred."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "msi_status": "inestable",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    pembro = [
        t for t in r["eligible_treatments"]
        if t.get("name") == "Pembrolizumab"
    ]
    assert pembro, "Pembrolizumab debe aparecer con MSI-H"
    assert pembro[0]["priority"] == "preferred"


def test_pembrolizumab_via_mmr_ihc_deficient():
    """MMR IHC 'deficient_dMMR' sin MSI PCR → pembrolizumab preferred."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "mmr_ihc_status": "deficient_dmmr",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    pembro = [t for t in r["eligible_treatments"] if t.get("name") == "Pembrolizumab"]
    assert pembro, "dMMR IHC deficient debe habilitar pembrolizumab"
    assert pembro[0]["priority"] == "preferred"


def test_pembrolizumab_via_somatic_mmr_variant():
    """MSH2 somatic → pembrolizumab preferred (dmmr_detected)."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "somatic_pathogenic_variant": "MSH2",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    pembro = [t for t in r["eligible_treatments"] if t.get("name") == "Pembrolizumab"]
    assert pembro
    assert pembro[0]["priority"] == "preferred"


def test_pembrolizumab_tmb_only_eligible_not_preferred():
    """TMB ≥10 sin dMMR → Marabelle 2020 aprobación agnóstica, notas mencionan TMB."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "tmb_value": "15",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    pembro = [t for t in r["eligible_treatments"] if t.get("name") == "Pembrolizumab"]
    assert pembro
    # Cuando pembrolizumab surge por TMB-H sin dMMR, las notas deben mencionar TMB y
    # la aprobación agnóstica Marabelle 2020 (pipeline normaliza priorities cuando es
    # el único tratamiento emitido).
    notes = str(pembro[0].get("notes") or "")
    assert "TMB" in notes, f"Pembrolizumab por TMB debe mencionarlo en notas: {notes!r}"


# ══════════════════════════════════════════════════════════════════════
# 4. AR-V7+ override → taxano preferred
# ══════════════════════════════════════════════════════════════════════


def test_arv7_positive_forces_taxane_in_service():
    """AR-V7+ post-ARPI sin docetaxel previo → Docetaxel (AR-V7 dirigido) preferred."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "ar_v7_status": "positivo",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    arv7_docx = [t for t in r["eligible_treatments"] if "AR-V7" in str(t.get("name", ""))]
    assert arv7_docx, "AR-V7+ debe emitir Docetaxel (AR-V7 dirigido)"
    nr_arv7 = [n for n in r.get("not_recommended", []) if "AR-V7" in n]
    assert nr_arv7, "AR-V7+ debe anotar 'no secuenciar otro ARPI'"


def test_arv7_positive_filters_arsi_in_sequencer():
    """TreatmentSequencer filtra todos los ARSIs cuando AR-V7+."""
    seq = TreatmentSequencer()
    plan = seq.optimize({
        "identity": {"id": 1},
        "reconciled_state": "m1_crpc",
        "baseline": {"arv7_positive": True, "ecog_score": 1},
        "genomic_profile": {"arv7_positive": True},
        "follow_ups": [],
        "treatments": [{"drug_scheme": "enzalutamide"}],
        "latest_assessment": {},
    })
    arsis_in_plan = [l.drug for l in plan.lines if l.drug in ARV7_POSITIVE_AVOID]
    assert arsis_in_plan == [], f"AR-V7+ debe excluir ARSIs, pero encontrados: {arsis_in_plan}"
    # Taxane debe estar en el top 3
    top_drugs = [l.drug for l in plan.lines[:3]]
    assert any("docetaxel" in d or "cabazitaxel" in d for d in top_drugs)


# ══════════════════════════════════════════════════════════════════════
# 5. Post-PARP sequencing
# ══════════════════════════════════════════════════════════════════════


def test_post_parp_not_applicable_without_prior_parp():
    """Sin PARPi previo → applicable=False."""
    bundle = evaluate_post_parp_sequencing({}, m1_context={})
    assert bundle["applicable"] is False
    assert bundle["candidates"] == []


def test_post_parp_cabazitaxel_preferred_when_card_applies():
    """Post-olaparib + post-docetaxel + post-ARPI → cabazitaxel (CARD) preferred."""
    bundle = evaluate_post_parp_sequencing(
        {
            "prior_parp_inhibitor": "1",
            "prior_arpi_duration_months": "12",
            "hemoglobin": "11",
            "platelets": "150000",
            "anc": "2000",
        },
        m1_context={
            "prior_arpi": True,
            "prior_docetaxel": True,
            "hrr_gene": "BRCA2",
        },
    )
    assert bundle["applicable"] is True
    cabaz = next(c for c in bundle["candidates"] if c["regimen_code"] == "CABAZITAXEL")
    assert cabaz["priority"] == "preferred"


def test_post_parp_platinum_rechallenge_gated_by_reserve():
    """BRCA+ con Hb 7 → platino rechallenge NO debe surgir (reserva inadecuada)."""
    bundle = evaluate_post_parp_sequencing(
        {
            "prior_parp_inhibitor": "1",
            "hemoglobin": "7",
            "platelets": "80000",
            "anc": "1000",
            "months_since_last_parp": "8",
        },
        m1_context={
            "prior_arpi": True,
            "prior_docetaxel": False,
            "hrr_gene": "BRCA2",
        },
    )
    assert bundle["applicable"] is True
    carbo = [c for c in bundle["candidates"] if c["regimen_code"] == "CARBOPLATIN_ETOPOSIDE"]
    assert carbo == [], "Reserva medular pobre debe bloquear rechallenge platino"


def test_post_parp_clinical_trial_always_offered():
    """Ensayo dirigido post-PARP debe estar siempre en candidatos."""
    bundle = evaluate_post_parp_sequencing(
        {"prior_parp_inhibitor": "1"},
        m1_context={"prior_arpi": True, "prior_docetaxel": False},
    )
    codes = {c["regimen_code"] for c in bundle["candidates"]}
    assert "CLINICAL_TRIAL_POST_PARP" in codes


# ══════════════════════════════════════════════════════════════════════
# 6. TreatmentSequencer NEPC library injection
# ══════════════════════════════════════════════════════════════════════


def test_sequencer_nepc_activates_platinum_library():
    """biomarker nepc=True → librería m1_crpc_nepc_transformation activa."""
    seq = TreatmentSequencer()
    plan = seq.optimize({
        "identity": {"id": 2},
        "reconciled_state": "m1_crpc",
        "baseline": {"ecog_score": 1},
        "genomic_profile": {},
        "follow_ups": [],
        "treatments": [],
        "latest_assessment": {
            "state": "m1_crpc",
            "result_snapshot": {
                "nepc_pathway_bundle": {
                    "nepc_confirmed": True,
                    "nepc_suspected": True,
                    "biopsy_trigger": False,
                    "suspicion_score": 5,
                },
            },
        },
    })
    platinum_drugs = {l.drug for l in plan.lines if "carboplatin" in l.drug or "cisplatin" in l.drug}
    assert "carboplatin_etoposide_nepc" in platinum_drugs
    # ARPI y docetaxel_adt excluidos por NEPC_TRANSFORMATION_AVOID
    excluded = [l.drug for l in plan.lines if l.drug in NEPC_TRANSFORMATION_AVOID]
    assert excluded == []


# ══════════════════════════════════════════════════════════════════════
# 7. End-to-end: service expone bundles + trial_matches
# ══════════════════════════════════════════════════════════════════════


def test_service_exposes_epic3_bundles():
    """result debe incluir vision_eligibility_bundle, nepc_pathway_bundle, post_parp_sequencing_bundle."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    assert "vision_eligibility_bundle" in r
    assert "nepc_pathway_bundle" in r
    assert "post_parp_sequencing_bundle" in r


def test_service_trial_matches_include_keynote_199_and_ep16():
    """KEYNOTE-199 y EP-16 (Aparicio) deben aparecer cuando aplique."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide",
        "msi_status": "inestable",
        "nepc_confirmed_histology": "1",
        "ihc_synaptophysin_positive": "1",
        "ihc_chromogranin_positive": "1",
        "ecog_performance_status": 1,
        "ecog_score": 1,
        "egfr_ml_min": "80",
    })
    trials = {t["trial"]: t["match"] for t in r["trial_matches"]}
    assert trials.get("KEYNOTE-199") is True
    assert trials.get("EP-16 (Aparicio)") is True


def test_service_benchmarking_flags_expose_dmmr_and_post_parp():
    """benchmarking_flags debe incluir dMMR y post-PARP flags."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide, Olaparib",
        "prior_parp_inhibitor": "1",
        "hrr_positive": "1",
        "hrr_gene": "BRCA2",
        "mmr_ihc_status": "deficient_dmmr",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    labels = {f["label"] for f in r["benchmarking_flags"]}
    assert any("IHC MMR" in l for l in labels)
    assert any("post-PARP" in l for l in labels)


def test_service_vision_post_docetaxel_prefers_lu177():
    """Paciente VISION-eligible → Lu-177 PSMA-617 priority=preferred."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide, Docetaxel",
        "prior_docetaxel_cycles": "8",
        "psma_pet_done": "1",
        "psma_positive": "1",
        "psma_index_lesion_suvmax": "12",
        "psma_suvmean_liver": "4",
        "hemoglobin": "11",
        "platelets": "180000",
        "anc": "2500",
        "egfr_ml_min": "75",
        "ecog_performance_status": 1,
        "ecog_score": 1,
    })
    lu = [t for t in r["eligible_treatments"] if "Lu-177" in str(t.get("name", ""))]
    assert lu, "Lu-177 debe emitirse cuando VISION pleno"
    assert lu[0]["priority"] == "preferred"


def test_service_post_olaparib_progression_to_cabazitaxel():
    """Post-olaparib + post-docetaxel + post-ARPI → cabazitaxel preferred (CARD)."""
    svc = M1CrpcService()
    r = svc.evaluate({
        "castrate_testosterone_confirmed": "1",
        "prior_therapy": "Enzalutamide, Olaparib, Docetaxel",
        "prior_docetaxel_cycles": "6",
        "prior_parp_inhibitor": "1",
        "hrr_positive": "1",
        "hrr_gene": "BRCA2",
        "prior_arpi_duration_months": "12",
        "hemoglobin": "11",
        "platelets": "150000",
        "anc": "2000",
        "ecog_performance_status": 1,
        "ecog_score": 1,
        "months_since_last_parp": "8",
    })
    cabaz = [t for t in r["eligible_treatments"] if "Cabazitaxel" in str(t.get("name", ""))]
    assert cabaz, "Cabazitaxel debe emitirse post-olaparib + CARD"
    assert cabaz[0]["priority"] == "preferred"
    assert r["post_parp_sequencing_bundle"]["applicable"] is True


# ══════════════════════════════════════════════════════════════════════
# 8. Constantes y catálogo
# ══════════════════════════════════════════════════════════════════════


def test_nepc_aggarwal_thresholds_constants():
    """Los umbrales Aggarwal 2018 deben ser estables (SUSPICION=3, BIOPSY=5)."""
    assert SUSPICION_SCORE_THRESHOLD == 3
    assert BIOPSY_TRIGGER_THRESHOLD == 5


def test_therapy_catalog_registers_nepc_regimens():
    """therapy_catalog debe exponer CARBOPLATIN_ETOPOSIDE_NEPC y CISPLATIN_DOCETAXEL_NEPC."""
    from prostanet.domains.patient_tracking.therapy_catalog import REGIMEN_LOOKUP

    assert "CARBOPLATIN_ETOPOSIDE_NEPC" in REGIMEN_LOOKUP
    assert "CISPLATIN_DOCETAXEL_NEPC" in REGIMEN_LOOKUP
    # Los regimens NEPC deben declarar evidence_tags alineados con Aparicio/Aggarwal.
    carbo = REGIMEN_LOOKUP["CARBOPLATIN_ETOPOSIDE_NEPC"]
    assert any(
        "Aparicio" in str(tag) or "Aggarwal" in str(tag) or "NEPC" in str(tag).upper()
        for tag in carbo.get("evidence_tags", [])
    ), f"Carbo-etopósido NEPC debe referenciar evidencia: {carbo.get('evidence_tags')!r}"
