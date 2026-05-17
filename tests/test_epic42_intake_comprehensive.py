"""EPIC 42 — Comprehensive intake + cohort hygiene + reasoning trail tests.

Cubre los 3 sub-EPICs:
- 42.A · Data hygiene: is_synthetic flag + mark_patient_as_real consent gating
- 42.B · Comprehensive intake schema (47 → 104 fields, NO eliminación)
- 42.C · Real patient consent endpoint + cohort breakdown

Refuerza el principio del usuario: NO eliminar campos clínicos fundamentales
para reducir captura. UI decongestion + voice manejan abundancia.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client():
    from app import app, create_app
    create_app()
    return app.test_client()


# ─────────────────── EPIC 42.A · Data hygiene ───────────────────


class TestDataHygiene:
    def test_get_cohort_synthetic_breakdown_returns_split(self):
        import tracking_db as _td
        br = _td.get_cohort_synthetic_breakdown()
        assert "total" in br
        assert "real" in br
        assert "synthetic" in br
        assert "ratio_real_pct" in br
        assert br["total"] == br["real"] + br["synthetic"]

    def test_mark_patient_as_real_requires_consent(self):
        import tracking_db as _td
        r = _td.mark_patient_as_real("VAL-687e8a23-049")
        assert r["success"] is False
        assert r["error"] == "consent_signed_at_required"

    def test_mark_patient_as_real_requires_actor(self):
        import tracking_db as _td
        r = _td.mark_patient_as_real("VAL-687e8a23-049",
                                       consent_signed_at="2026-05-17T10:00:00Z")
        assert r["success"] is False
        assert r["error"] == "actor_user_id_required"

    def test_mark_patient_as_real_404_for_unknown_patient(self):
        import tracking_db as _td
        r = _td.mark_patient_as_real("NONEXISTENT99999",
                                       consent_signed_at="2026-05-17T10:00:00Z",
                                       actor_user_id=1)
        assert r["success"] is False
        assert r["error"] == "patient_not_found"

    def test_mark_real_promotes_then_revert(self):
        """Roundtrip: mark real, verify, manually revert (no API revert by design)."""
        import tracking_db as _td
        import sqlite3
        # Pick a synthetic test patient
        nss = "VAL-687e8a23-050"
        r = _td.mark_patient_as_real(nss,
                                      consent_signed_at="2026-05-17T10:00:00Z",
                                      actor_user_id=99)
        assert r["success"] is True
        # Verify in cohort breakdown
        # Cleanup
        c = sqlite3.connect(_td.get_db_path())
        c.execute("UPDATE patient_identity SET is_synthetic=1, "
                  "synthetic_flag_reason='heuristic_nss_prefix', "
                  "real_patient_consent_signed_at=NULL, "
                  "real_patient_consent_actor_user_id=NULL "
                  "WHERE nss=?", (nss,))
        c.commit()
        c.close()


class TestCohortBreakdownEndpoint:
    def test_cohort_breakdown_endpoint(self, client):
        r = client.get("/api/cohort/breakdown")
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert "total" in b
        assert "real" in b
        assert "synthetic" in b

    def test_cohort_real_vs_synthetic_kpi_registered(self):
        from prostanet.domains.population_intelligence.mx_cohort_aggregator import (
            KPI_REGISTRY, compute_kpi,
        )
        assert "cohort_real_vs_synthetic" in KPI_REGISTRY
        r = compute_kpi("cohort_real_vs_synthetic")
        assert r["kpi_id"] == "cohort_real_vs_synthetic"
        assert "synthetic_reason_breakdown" in r
        assert r["min_real_for_inference"] == 30


class TestMarkRealEndpoint:
    def test_endpoint_requires_consent(self, client):
        r = client.post("/api/patients/VAL-687e8a23-046/mark-real", json={})
        assert r.status_code == 400
        assert r.get_json()["error"] == "consent_signed_at_required"

    def test_endpoint_requires_actor(self, client):
        r = client.post("/api/patients/VAL-687e8a23-046/mark-real",
                         json={"consent_signed_at": "2026-05-17T10:00:00Z"})
        assert r.status_code == 400
        assert r.get_json()["error"] == "actor_user_id_required"


# ─────────────────── EPIC 42.B · Comprehensive intake schema ───────────────────


class TestSchemaExpansion:
    """Verifica que el schema NO eliminó campos y agregó los nuevos grupos."""

    @pytest.fixture(scope="class")
    def schema(self):
        from prostanet.presentation.v2_adapters import quick_classify_schema
        return quick_classify_schema()

    def test_schema_has_at_least_100_fields(self, schema):
        assert len(schema["fields"]) >= 100, (
            f"Expansion: 47 → ≥100 (47 originales preservados + ≥53 nuevos). "
            f"Got: {len(schema['fields'])}"
        )

    def test_all_47_original_fields_preserved(self, schema):
        """NO eliminar campos clínicos fundamentales — directiva explícita usuario."""
        original_fields = {
            "full_name", "dob", "nss", "ecog_score", "family_history_cancer",
            "charlson_comorbidity_index", "known_cancer_diagnosis",
            "encounter_type", "screening_context", "prior_negative_biopsy",
            "biopsy_scheduled", "psa", "psad", "pirads_score", "dre_suspicious",
            "repeat_psa_value", "repeat_psa_date", "planned_biopsy_type",
            "planned_biopsy_route", "diagnosis_date", "histology_subtype",
            "psa_baseline_ng_ml", "gleason_primary", "gleason_secondary",
            "gleason_tertiary", "clinical_tstage", "nodal_status",
            "metastasis_site", "clinical_stage_group", "clinical_risk_group",
            "prior_local_therapy", "psa_postop", "bcr_detected", "bcr_psa",
            "bcr_date", "rt_completion_date", "psa_nadir_post_rt",
            "metachronous_metastasis", "visceral_metastasis_present",
            "bone_lesion_count_total", "bone_appendicular_count",
            "conventional_imaging_status", "current_adt_context",
            "castrate_testosterone_status", "testosterone_value",
            "systemic_progression_context", "line_of_therapy_number",
        }
        schema_names = {f["name"] for f in schema["fields"]}
        missing = original_fields - schema_names
        assert not missing, f"REGRESIÓN: campos originales eliminados: {missing}"

    @pytest.mark.parametrize("field_name", [
        # Biopsia detalle (9)
        "total_cores_biopsied", "cores_positive_count", "percent_positive_cores",
        "percent_pattern_4", "perineural_invasion", "biopsy_route",
        "extracapsular_extension_on_biopsy", "prostate_volume_ml", "psa_density",
        # Imaging detalle (10)
        "mpmri_done", "mpmri_date", "mpmri_lesion_count",
        "bone_scan_done", "bone_scan_date", "ct_abdomen_pelvis_done",
        "psma_pet_done", "psma_pet_date", "psma_tracer",
        "psma_positive", "psma_lesion_count", "psma_index_lesion_suvmax",
        # Genética molecular (10)
        "germline_testing_performed", "germline_testing_date", "hrr_status",
        "hrr_gene", "biomarker_source", "msi_status",
        "first_degree_relative_pca_lt60", "first_degree_relative_brca_breast_ovarian",
        "lynch_syndrome_features", "genomic_classifier_result",
        # Fitness geriátrico (6)
        "g8_score", "frailty_status", "mini_cog_score",
        "life_expectancy_years_estimated", "anesthesia_surgical_fitness",
        "radiotherapy_feasibility",
        # Comorbilidades específicas (7)
        "severe_cv_disease", "active_liver_disease", "cognitive_impairment_documented",
        "diabetes_baseline_a1c", "dxa_t_score_lumbar", "dxa_t_score_hip",
        "renal_creatinine_clearance",
        # PROs baseline (5)
        "ipss_total", "iief5_score", "epic26_urinary_domain",
        "epic26_sexual_domain", "epic26_bowel_domain",
        # Preferencias paciente (3)
        "goal_of_care", "patient_priority_profile", "treatment_modality_preference",
        # Medicación (2)
        "current_medications", "ddi_review_status",
        # CRPC verification (1 nuevo)
        "testosterone_sample_date",
    ])
    def test_new_clinical_fields_present(self, schema, field_name):
        names = {f["name"] for f in schema["fields"]}
        assert field_name in names, (
            f"EPIC 42.B field missing: {field_name}. Confirma que la expansión "
            f"de schema sigue intacta (cobertura clínica COMPLETA)."
        )

    def test_new_fields_have_help_text(self, schema):
        """Cada nuevo field debe tener help_text para asistir al clínico."""
        # Sample new fields that MUST have help text (most clinically nuanced)
        critical_new = ["psa_density", "percent_pattern_4", "g8_score", "frailty_status",
                         "germline_testing_performed", "psma_positive"]
        for name in critical_new:
            field = next((f for f in schema["fields"] if f["name"] == name), None)
            assert field is not None
            assert field.get("help_text"), f"{name} requires help_text for clinician context"


class TestNewFactSpecs:
    def test_psa_density_registered(self):
        from prostanet.shared.clinical_fact_registry import FACT_SPECS
        assert "psa_density" in FACT_SPECS
        spec = FACT_SPECS["psa_density"]
        assert spec.blocking is True
        assert spec.domain == "biochemical"

    def test_total_cores_biopsied_registered(self):
        from prostanet.shared.clinical_fact_registry import FACT_SPECS
        assert "total_cores_biopsied" in FACT_SPECS
        assert FACT_SPECS["total_cores_biopsied"].blocking is True

    def test_prostate_volume_ml_registered(self):
        from prostanet.shared.clinical_fact_registry import FACT_SPECS
        assert "prostate_volume_ml" in FACT_SPECS


# ─────────────────── EPIC 42.B.4 + 42.B.5 · Reasoning trail ───────────────────


class TestReasoningTrailEndpoint:
    def test_reasoning_trail_with_partial_data(self, client):
        r = client.post("/api/intake/reasoning-trail", json={
            "baseline_psa": 6.8,
            "gleason_primary": 3, "gleason_secondary": 3,
            "clinical_tstage": "cT1c",
            "known_cancer_diagnosis": "1",
            "metastasis_site": "M0",
        })
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert "current_classification" in b
        assert "missing_blocking_fields" in b
        assert "alternative_paths" in b
        assert b["missing_blocking_count"] > 0  # 22 blocking facts missing
        # Should suggest very_low_risk refinement path (Skeptic's trazabilidad)
        path_ids = [p["path"] for p in b["alternative_paths"]]
        assert "very_low_risk_localized_refinement" in path_ids

    def test_reasoning_trail_surfaces_parp_path_when_hrr_missing(self, client):
        r = client.post("/api/intake/reasoning-trail", json={
            "baseline_psa": 6.8,
            "gleason_primary": 3, "gleason_secondary": 3,
            "metastasis_site": "M0",
            # No hrr_status
        })
        b = r.get_json()
        path_ids = [p["path"] for p in b["alternative_paths"]]
        assert "parp_trial_eligibility" in path_ids

    def test_reasoning_trail_missing_by_domain(self, client):
        r = client.post("/api/intake/reasoning-trail", json={})
        b = r.get_json()
        # Should bucket missing fields by clinical domain (UX prioritization)
        assert isinstance(b["missing_by_domain"], dict)
        assert len(b["missing_by_domain"]) >= 3  # multiple domains

    def test_reasoning_trail_does_NOT_block(self, client):
        """CRÍTICO: el endpoint es informativo, NUNCA debe retornar error si
        faltan campos. NO bloquea captura."""
        r = client.post("/api/intake/reasoning-trail", json={})
        assert r.status_code == 200  # NEVER 400/422 even with empty payload
        assert r.get_json()["success"] is True


# ─────────────────── Concordance gate ───────────────────


class TestConcordanceGateUpdated:
    def test_intake_voice_hub_testid_renders_in_template(self, client):
        """EPIC 42.B.3 — Verify the voice hub data-testid appears in rendered template."""
        # We can't render intake page without auth setup; verify template source has it
        from pathlib import Path
        intake_html = Path(__file__).resolve().parent.parent / "templates" / "intake_stage_aware_v2.html"
        content = intake_html.read_text()
        assert 'data-testid="intake-voice-dictation-hub"' in content
        assert "iw-voice-mic-btn" in content
        assert "/api/voice/quick-capture/" in content  # The endpoint invocation
