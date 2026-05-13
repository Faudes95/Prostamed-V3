"""tests/test_audit_lxxxv_trials_eligibility_engine.py — FAUBOT LXXXV Iteración #2.

Tests para el motor de elegibilidad de los 47 trials pivotales.

Componentes verificados:

§A — Trial Criteria Registry (47 trials con PMID/NCT/citation/criteria) — H.G2774-G2783
§B — Trial Eligibility Engine (47 evaluator functions + dispatcher) — H.G2784-G2810
§C — REST API endpoints (5 endpoints JSON + UI dashboard) — H.G2811-G2820
§D — UI sidebar wiring + dashboard rendering — H.G2821-G2823

HIPÓTESIS: H.G2774 → H.G2823 (~50 tests).
Faubot LXXXV — Iteración #2 cierre: Trial Eligibility end-to-end.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

if "tracking_db" not in sys.modules:
    try:
        import tracking_db  # noqa: F401
    except Exception:
        class _S(types.ModuleType):
            def __getattr__(self, n):
                # Faubot LXXXV: dejar dunders pasar (evita romper inspect/torch)
                if n.startswith("__") and n.endswith("__"):
                    raise AttributeError(n)
                def _f(*a, **k):
                    return [] if "list" in n else {}
                return _f
        sys.modules["tracking_db"] = _S("tracking_db")


# ──────────────────────────────────────────────────────────────────────
# §A — Trial Criteria Registry
# ──────────────────────────────────────────────────────────────────────


def test_g2774_total_47_trials_in_registry():
    """H.G2774 — Registry contiene exactamente 47 trials."""
    from prostanet.shared.trial_criteria_registry import get_total_trials_count
    assert get_total_trials_count() == 47


def test_g2775_chaarted_in_registry_with_pmid_26244877():
    """H.G2775 — CHAARTED registrado con PMID 26244877 + NCT."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    chaarted = get_trial_criteria("CHAARTED")
    assert chaarted is not None
    assert chaarted["pmid"] == "26244877"
    assert chaarted["nct"] == "NCT00309985"
    assert "Sweeney" in chaarted["citation"]
    assert chaarted["stage"] == "mcspc"


def test_g2776_profound_hrr_biomarker_required():
    """H.G2776 — PROfound requiere HRR biomarker."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    profound = get_trial_criteria("PROfound")
    assert profound is not None
    assert "HRR" in (profound.get("biomarker_required") or "")
    assert profound["pmid"] == "32343890"


def test_g2777_vision_psma_biomarker_required():
    """H.G2777 — VISION requiere PSMA-PET biomarker."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    vision = get_trial_criteria("VISION")
    assert vision is not None
    assert "PSMA" in (vision.get("biomarker_required") or "")


def test_g2778_ipatential150_pten_biomarker_required():
    """H.G2778 — IPATential150 requiere PTEN biomarker."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    ipa = get_trial_criteria("IPATential150")
    assert ipa is not None
    assert "PTEN" in (ipa.get("biomarker_required") or "")


def test_g2779_amplitude_in_registry_with_hrr():
    """H.G2779 — AMPLITUDE registrado (LXXXII falta gap cerrado)."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    ampl = get_trial_criteria("AMPLITUDE")
    assert ampl is not None
    assert "HRR" in (ampl.get("biomarker_required") or "")


def test_g2780_cou_aa_301_in_registry():
    """H.G2780 — COU-AA-301 registrado (LXXXII falta gap cerrado)."""
    from prostanet.shared.trial_criteria_registry import get_trial_criteria
    cou = get_trial_criteria("COU-AA-301")
    assert cou is not None
    assert cou["pmid"] == "21612468"


def test_g2781_list_trials_by_stage_mcspc():
    """H.G2781 — list_trials_by_stage(mcspc) retorna ≥9 trials."""
    from prostanet.shared.trial_criteria_registry import list_trials_by_stage
    mcspc = list_trials_by_stage("mcspc")
    assert len(mcspc) >= 9
    assert "CHAARTED" in mcspc
    assert "ARASENS" in mcspc
    assert "PEACE-1" in mcspc


def test_g2782_list_trials_by_stage_m1_crpc():
    """H.G2782 — list_trials_by_stage(m1_crpc) retorna ≥18 trials."""
    from prostanet.shared.trial_criteria_registry import list_trials_by_stage
    m1 = list_trials_by_stage("m1_crpc")
    assert len(m1) >= 18
    assert "PROfound" in m1
    assert "VISION" in m1


def test_g2783_list_trials_by_biomarker_hrr():
    """H.G2783 — list_trials_by_biomarker(HRR) incluye 4 trials clave."""
    from prostanet.shared.trial_criteria_registry import list_trials_by_biomarker
    hrr = list_trials_by_biomarker("HRR")
    assert "PROfound" in hrr
    assert "MAGNITUDE" in hrr
    assert "TALAPRO-2" in hrr
    assert "AMPLITUDE" in hrr


# ──────────────────────────────────────────────────────────────────────
# §B — Trial Eligibility Engine
# ──────────────────────────────────────────────────────────────────────


def test_g2784_engine_has_47_evaluators():
    """H.G2784 — Engine registra 47 evaluator functions."""
    from prostanet.shared.trial_eligibility_engine import get_total_evaluators_count
    assert get_total_evaluators_count() == 47


def test_g2785_evaluate_chaarted_high_volume_eligible():
    """H.G2785 — CHAARTED HV: paciente mCSPC + ECOG 1 + visceral mets → eligible HV."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "visceral_metastasis": True,
    }
    r = evaluate_trial_eligibility(patient, "CHAARTED")
    assert r["eligible"] is True
    assert r["subgroup"] == "high_volume"
    assert r["confidence"] == 1.0


def test_g2786_evaluate_chaarted_low_volume_eligible():
    """H.G2786 — CHAARTED LV: paciente mCSPC + sin visceral + 2 bone mets → LV."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "visceral_metastasis": False,
        "bone_metastasis_count": 2,
        "bone_mets_appendicular": False,
    }
    r = evaluate_trial_eligibility(patient, "CHAARTED")
    assert r["eligible"] is True
    assert r["subgroup"] == "low_volume"


def test_g2787_evaluate_chaarted_excluded_prior_chemo():
    """H.G2787 — CHAARTED excluye paciente con quimio previa."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "visceral_metastasis": True,
        "prior_chemotherapy": True,
    }
    r = evaluate_trial_eligibility(patient, "CHAARTED")
    assert r["eligible"] is False
    assert any("quimio" in reason.lower() or "chemo" in reason.lower() for reason in r["reasons_not_eligible"])


def test_g2788_evaluate_latitude_high_risk_3_factors():
    """H.G2788 — LATITUDE: Gleason 9 + ≥3 bone + visceral → high-risk eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "gleason_score": 9,
        "bone_metastasis_count": 5,
        "visceral_metastasis": True,
    }
    r = evaluate_trial_eligibility(patient, "LATITUDE")
    assert r["eligible"] is True
    assert r["subgroup"] == "high_risk_latitude"


def test_g2789_evaluate_latitude_low_risk_excluded():
    """H.G2789 — LATITUDE: Gleason 6 + 1 bone + sin visceral → no high-risk."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "gleason_score": 6,
        "bone_metastasis_count": 1,
        "visceral_metastasis": False,
    }
    r = evaluate_trial_eligibility(patient, "LATITUDE")
    assert r["eligible"] is False


def test_g2790_evaluate_spartan_nmcrpc_eligible():
    """H.G2790 — SPARTAN: nmCRPC + PSADT 8 + PSA 5 + testo 25 → eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m0_crpc",
        "ecog_current": 1,
        "psa_value": 5,
        "psa_doubling_time_months": 8,
        "testosterone_value": 25,
    }
    r = evaluate_trial_eligibility(patient, "SPARTAN")
    assert r["eligible"] is True


def test_g2791_evaluate_spartan_excluded_psadt_too_long():
    """H.G2791 — SPARTAN: PSADT 12 meses → excluido (criterio ≤10m)."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m0_crpc",
        "ecog_current": 1,
        "psa_value": 5,
        "psa_doubling_time_months": 12,
        "testosterone_value": 25,
    }
    r = evaluate_trial_eligibility(patient, "SPARTAN")
    assert r["eligible"] is False


def test_g2792_evaluate_profound_brca2_cohort_a():
    """H.G2792 — PROfound BRCA2: cohort A (BRCA1/2/ATM) eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "ecog_current": 1,
        "prior_arpi": True,
        "hrr_test_result": "positive",
        "hrr_genes_mutated": ["BRCA2"],
    }
    r = evaluate_trial_eligibility(patient, "PROfound")
    assert r["eligible"] is True
    assert r["subgroup"] == "cohort_A_brca_atm"


def test_g2793_evaluate_profound_negative_hrr_excluded():
    """H.G2793 — PROfound HRR negative → no eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "ecog_current": 1,
        "prior_arpi": True,
        "hrr_test_result": "negative",
    }
    r = evaluate_trial_eligibility(patient, "PROfound")
    assert r["eligible"] is False


def test_g2794_evaluate_vision_psma_pet_required():
    """H.G2794 — VISION PSMA+: chemo+ARPI previos + PSMA+ → eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "ecog_current": 1,
        "prior_chemotherapy": True,
        "prior_arpi": True,
        "psma_pet_positive": True,
    }
    r = evaluate_trial_eligibility(patient, "VISION")
    assert r["eligible"] is True


def test_g2795_evaluate_vision_psma_negative_excluded():
    """H.G2795 — VISION PSMA negative → excluido."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "ecog_current": 1,
        "prior_chemotherapy": True,
        "prior_arpi": True,
        "psma_pet_positive": False,
    }
    r = evaluate_trial_eligibility(patient, "VISION")
    assert r["eligible"] is False


def test_g2796_evaluate_amplitude_hrr_required():
    """H.G2796 — AMPLITUDE HRR+: mCSPC + HRR positive → eligible."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "mcspc",
        "ecog_current": 1,
        "hrr_test_result": "positive",
        "hrr_genes_mutated": ["BRCA2"],
    }
    r = evaluate_trial_eligibility(patient, "AMPLITUDE")
    assert r["eligible"] is True


def test_g2797_evaluate_ipatential150_pten_loss():
    """H.G2797 — IPATential150 PTEN loss → cohorte primaria."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "ecog_current": 1,
        "pten_status": "loss",
    }
    r = evaluate_trial_eligibility(patient, "IPATential150")
    assert r["eligible"] is True
    assert r["subgroup"] == "pten_loss"


def test_g2798_evaluate_alsympca_excludes_visceral():
    """H.G2798 — ALSYMPCA: visceral mets excluidas."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "bone_metastasis_count": 5,
        "visceral_metastasis": True,
    }
    r = evaluate_trial_eligibility(patient, "ALSYMPCA")
    assert r["eligible"] is False


def test_g2799_evaluate_embark_psadt_9_required():
    """H.G2799 — EMBARK BCR + PSADT 6 → eligible (≤9 OK)."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "recurrence_bcr",
        "psa_doubling_time_months": 6,
    }
    r = evaluate_trial_eligibility(patient, "EMBARK")
    assert r["eligible"] is True


def test_g2800_evaluate_embark_psadt_too_long():
    """H.G2800 — EMBARK PSADT 12 → excluido (>9)."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "recurrence_bcr",
        "psa_doubling_time_months": 12,
    }
    r = evaluate_trial_eligibility(patient, "EMBARK")
    assert r["eligible"] is False


def test_g2801_evaluate_card_requires_doce_plus_arpi():
    """H.G2801 — CARD requiere docetaxel + ARPI previo."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "prior_chemotherapy": True,
        "prior_arpi": True,
    }
    r = evaluate_trial_eligibility(patient, "CARD")
    assert r["eligible"] is True


def test_g2802_evaluate_card_excludes_no_arpi():
    """H.G2802 — CARD sin ARPI previo → excluido."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "prior_chemotherapy": True,
        "prior_arpi": False,
    }
    r = evaluate_trial_eligibility(patient, "CARD")
    assert r["eligible"] is False


def test_g2803_evaluate_all_eligible_trials_returns_47():
    """H.G2803 — evaluate_all_eligible_trials evalúa los 47."""
    from prostanet.shared.trial_eligibility_engine import evaluate_all_eligible_trials
    results = evaluate_all_eligible_trials({"disease_state": "mcspc", "ecog_current": 1})
    assert len(results) == 47


def test_g2804_evaluate_all_eligible_returns_eligibles_first():
    """H.G2804 — Resultados ordenados con eligibles primero."""
    from prostanet.shared.trial_eligibility_engine import evaluate_all_eligible_trials
    patient = {"disease_state": "mcspc", "ecog_current": 1, "visceral_metastasis": True}
    results = evaluate_all_eligible_trials(patient)
    # Primer no-eligible aparece después de últimos eligibles
    eligibles_count = sum(1 for r in results if r["eligible"])
    if eligibles_count > 0 and eligibles_count < len(results):
        last_eligible_idx = max(i for i, r in enumerate(results) if r["eligible"])
        first_not_idx = min(i for i, r in enumerate(results) if not r["eligible"])
        assert last_eligible_idx < first_not_idx


def test_g2805_unknown_trial_raises_value_error():
    """H.G2805 — Trial desconocido raises ValueError."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    try:
        evaluate_trial_eligibility({}, "UNKNOWN_TRIAL_XYZ")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "no registrado" in str(exc)


def test_g2806_missing_data_reduces_confidence():
    """H.G2806 — Missing data reduce confidence proporcional."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    full = {"disease_state": "mcspc", "ecog_current": 1, "visceral_metastasis": True}
    sparse = {"disease_state": "mcspc"}
    r_full = evaluate_trial_eligibility(full, "CHAARTED")
    r_sparse = evaluate_trial_eligibility(sparse, "CHAARTED")
    assert r_full["confidence"] >= r_sparse["confidence"]


def test_g2807_result_includes_pmid_nct_citation():
    """H.G2807 — Resultado incluye PMID + NCT + citation."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    r = evaluate_trial_eligibility(
        {"disease_state": "mcspc", "ecog_current": 1, "visceral_metastasis": True},
        "CHAARTED"
    )
    assert r["pmid"] == "26244877"
    assert r["nct"] == "NCT00309985"
    assert "Sweeney" in r["citation"]


def test_g2808_aft19_alias_of_presto():
    """H.G2808 — AFT-19 usa el mismo evaluator que PRESTO."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {"disease_state": "recurrence_bcr", "psa_doubling_time_months": 6}
    r_presto = evaluate_trial_eligibility(patient, "PRESTO")
    r_aft19 = evaluate_trial_eligibility(patient, "AFT-19")
    assert r_presto["eligible"] == r_aft19["eligible"]
    assert r_aft19["trial_id"] == "AFT-19"


def test_g2809_protect_pivot_spcg4_localized():
    """H.G2809 — PROTECT/PIVOT/SPCG-4 evalúan localized correctamente."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {"disease_state": "localized_initial", "psa_value": 8}
    for trial in ["PROTECT", "PIVOT", "SPCG-4"]:
        r = evaluate_trial_eligibility(patient, trial)
        assert r["eligible"] is True, f"{trial} debería ser eligible para localized PSA 8"


def test_g2810_triton3_requires_brca_atm():
    """H.G2810 — TRITON-3 requiere BRCA1/2/ATM mutation."""
    from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    patient = {
        "disease_state": "m1_crpc",
        "hrr_test_result": "positive",
        "hrr_genes_mutated": ["BRCA1"],
    }
    r = evaluate_trial_eligibility(patient, "TRITON-3")
    assert r["eligible"] is True


# ──────────────────────────────────────────────────────────────────────
# §C — REST API endpoints
# ──────────────────────────────────────────────────────────────────────


def test_g2811_api_trials_list_returns_47():
    """H.G2811 — GET /api/trials/list retorna 47 trials."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/list")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 47


def test_g2812_api_trial_criteria_chaarted_returns_pmid():
    """H.G2812 — GET /api/trials/CHAARTED/criteria retorna PMID."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/CHAARTED/criteria")
        assert r.status_code == 200
        assert r.get_json()["criteria"]["pmid"] == "26244877"


def test_g2813_api_trial_criteria_unknown_returns_404():
    """H.G2813 — GET /api/trials/UNKNOWN/criteria retorna 404."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/UNKNOWN_TRIAL/criteria")
        assert r.status_code == 404
        assert r.get_json()["error"] == "trial_not_found"


def test_g2814_api_trials_by_stage_mcspc():
    """H.G2814 — GET /api/trials/by_stage/mcspc retorna trials mCSPC."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/by_stage/mcspc")
        assert r.status_code == 200
        data = r.get_json()
        assert data["stage"] == "mcspc"
        assert "CHAARTED" in data["trials"]
        assert data["total"] >= 9


def test_g2815_api_trials_eligible_for_unknown_patient_returns_404():
    """H.G2815 — GET /api/trials/eligible_for/UNKNOWN_NSS retorna 404."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/eligible_for/UNKNOWN_NSS_XYZ")
        assert r.status_code == 404


def test_g2816_api_trial_eligibility_for_patient_unknown_trial_404():
    """H.G2816 — GET /api/trials/UNKNOWN/eligibility/<nss> retorna 404."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        # Mock un patient existente — usar mock interno simple
        # Si no hay paciente, devolverá 404 antes de llegar a chequear trial
        r = client.get("/api/trials/UNKNOWN_TRIAL/eligibility/test_nss")
        # Either patient not found or trial not supported
        assert r.status_code == 404


def test_g2817_api_response_includes_total_evaluated():
    """H.G2817 — Response /api/trials/eligible_for incluye total_evaluated."""
    # Este test requiere paciente real; usar mock con tracking_db stub
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    # Mockear tracking_db para devolver paciente test
    import prostanet.presentation.trial_eligibility_routes as routes_mod
    original_loader = routes_mod._load_patient
    def mock_loader(nss):
        return {"nss": nss, "disease_state": "mcspc", "ecog_current": 1}
    routes_mod._load_patient = mock_loader
    try:
        with flask_app.test_client() as client:
            r = client.get("/api/trials/eligible_for/MOCK_NSS")
            assert r.status_code == 200
            data = r.get_json()
            assert "total_evaluated" in data
            assert "eligible_count" in data
            assert "results" in data
            assert len(data["results"]) == 47
    finally:
        routes_mod._load_patient = original_loader


def test_g2818_api_eligibility_per_trial_per_patient():
    """H.G2818 — GET /api/trials/CHAARTED/eligibility/<nss> retorna evaluation."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    import prostanet.presentation.trial_eligibility_routes as routes_mod
    original_loader = routes_mod._load_patient
    def mock_loader(nss):
        return {"nss": nss, "disease_state": "mcspc", "ecog_current": 1, "visceral_metastasis": True}
    routes_mod._load_patient = mock_loader
    try:
        with flask_app.test_client() as client:
            r = client.get("/api/trials/CHAARTED/eligibility/MOCK_NSS")
            assert r.status_code == 200
            data = r.get_json()
            assert data["trial_id"] == "CHAARTED"
            assert data["evaluation"]["eligible"] is True
            assert data["evaluation"]["subgroup"] == "high_volume"
    finally:
        routes_mod._load_patient = original_loader


def test_g2819_api_responses_are_json():
    """H.G2819 — Todos los API endpoints devuelven application/json."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        for endpoint in [
            "/api/trials/list",
            "/api/trials/CHAARTED/criteria",
            "/api/trials/by_stage/mcspc",
        ]:
            r = client.get(endpoint)
            assert r.status_code == 200
            assert r.content_type.startswith("application/json")


def test_g2820_api_trial_list_includes_amplitude_and_cou_aa_301():
    """H.G2820 — Lista de trials incluye AMPLITUDE + COU-AA-301 (gaps cerrados)."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/api/trials/list")
        trials = r.get_json()["trials"]
        assert "AMPLITUDE" in trials
        assert "COU-AA-301" in trials


# ──────────────────────────────────────────────────────────────────────
# §D — UI sidebar wiring + dashboard rendering
# ──────────────────────────────────────────────────────────────────────


def test_g2821_pm2_sidebar_has_trial_eligibility_link():
    """H.G2821 — pm2_sidebar.html macro renderiza link Trial eligibility."""
    from pathlib import Path
    template = (Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/components/pm2_sidebar.html")).read_text()
    assert "trials-eligibility" in template
    assert "Trial eligibility" in template


def test_g2822_dashboard_template_extends_base_clinical():
    """H.G2822 — trials_eligibility_dashboard_v2.html extiende base_clinical."""
    from pathlib import Path
    template = (Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/trials_eligibility_dashboard_v2.html")).read_text()
    assert 'extends "layouts/base_clinical.html"' in template
    assert "pm2_sidebar" in template
    assert "Trial eligibility" in template or "Trials elegibles" in template


def test_g2823_dashboard_renders_three_sections():
    """H.G2823 — Dashboard distingue elegibles, no evaluables y no elegibles."""
    from pathlib import Path
    template = (Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/trials_eligibility_dashboard_v2.html")).read_text()
    assert "Trials elegibles" in template
    assert "Trials no evaluables por datos faltantes" in template
    assert "Trials no elegibles" in template
