"""Tests for the post_radiotherapy_followup domain and state-classifier routing."""
# IEC 62304 §5.5 (Unit verification)


from datetime import date, timedelta

import pytest

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.post_radiotherapy_followup.rules_eau import (
    classify_post_rt_followup_eau,
)
from prostanet.domains.post_radiotherapy_followup.rules_nccn import (
    classify_post_rt_followup_nccn,
)
from prostanet.domains.post_radiotherapy_followup.service import (
    PostRadiotherapyFollowupService,
)
from prostanet.domains.patient_tracking.capture_surface import (
    display_capture_field_summary,
)
from prostanet.domains.patient_tracking.post_rt_salvage_copilot_service import (
    PostRTSalvageCopilotService,
)
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
from prostanet.domains.patient_tracking.vertical_runtime import build_runtime_payload
from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)
from prostanet.domains.state_classifier.service import StateClassifierService


@pytest.fixture()
def registry():
    return ModuleRegistry()


def _base_payload(**overrides):
    payload = {
        "prior_radiation": "1",
        "prior_prostatectomy": "0",
        "prior_rt_modality": "IMRT",
        "prior_rt_completion_date": (date.today() - timedelta(days=730)).isoformat(),
        "prior_rt_dose_gy": 78,
        "prior_rt_fractions": 39,
        "prior_rt_intent": "Definitive",
        "concurrent_adt_history": "Corto (4-6m)",
        "adt_duration_months": 6,
        "adt_active": "0",
        "risk_group_at_treatment": "Unfavorable Intermediate",
        "gleason_at_diagnosis": 2,
        "psa_at_diagnosis": 10,
        "clinical_tstage_at_treatment": "T2a",
        "psa_current": 0.4,
        "psa_current_date": date.today().isoformat(),
        "psa_nadir": 0.3,
        "psa_nadir_date": (date.today() - timedelta(days=540)).isoformat(),
        "time_to_nadir_months": 18,
        "phoenix_failure_confirmed": "0",
        "psa_doubling_time_months": 0,
        "bounce_suspected": "0",
        "late_urinary_grade": "0",
        "late_bowel_grade": "0",
        "late_sexual_function": "Preservada",
        "testosterone_value": 350,
        "smoking_status": "Nunca",
        "colorectal_screening_current": "1",
        "dre_finding": "Normal",
        "imaging_negative_metastases": "1",
        "age_current": 68,
        "ecog_score": "0",
        "frailty_status": "Fit",
        "charlson_index": 2,
    }
    payload.update(overrides)
    return payload


def _enable_post_rt_copilot(monkeypatch, *, mode="shadow"):
    monkeypatch.setenv("ENABLE_POST_RT_SALVAGE_COPILOT", "1")
    monkeypatch.setenv("PROSTANET_AI_RUNTIME_MODE", mode)
    import prostanet.ai.config as ai_config_module

    monkeypatch.setattr(ai_config_module, "_config", None, raising=False)


class TestStateClassifierRouting:
    """Verify state classifier sends RT patients to the correct module."""

    def test_prior_radiation_without_recurrence_routes_to_followup(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_radiation": "1",
            "prior_prostatectomy": "0",
            "psa_current": 0.05,
        }
        result = registry.classify_state(payload)
        assert result["state"] == "post_radiotherapy_followup"
        assert "sin señal de recurrencia" in result["classification_reason"]

    def test_prior_radiation_with_phoenix_delta_routes_to_salvage(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_radiation": "1",
            "prior_prostatectomy": "0",
            "psa_current": 3.5,
            "phoenix_delta": 2.5,
        }
        result = registry.classify_state(payload)
        assert result["state"] == "post_radiotherapy_or_local_salvage"
        assert "radioterapia previa" in result["classification_reason"].lower()

    def test_prior_prostatectomy_without_recurrence_routes_to_post_rp(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_radiation": "0",
            "prior_prostatectomy": "1",
            "psa_postop": 0.05,
        }
        result = registry.classify_state(payload)
        assert result["state"] == "post_prostatectomy"

    def test_no_prior_therapy_still_routes_to_localized_initial(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_radiation": "0",
            "prior_prostatectomy": "0",
        }
        result = registry.classify_state(payload)
        assert result["state"] == "localized_initial"

    def test_both_therapies_prioritizes_post_prostatectomy_without_recurrence(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_radiation": "1",
            "prior_prostatectomy": "1",
            "psa_postop": 0.03,
        }
        result = registry.classify_state(payload)
        assert result["state"] == "post_prostatectomy"

    def test_post_rp_detectable_but_subthreshold_psa_stays_on_post_prostatectomy_track(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_prostatectomy": "1",
            "prior_radiation": "0",
            "psa_postop": 0.18,
            "metastasis_site": "M0",
        }
        result = registry.classify_state(payload)
        assert result["state"] == "post_prostatectomy"
        assert "vigilancia reforzada" in result["classification_reason"].lower()

    def test_post_rp_confirmatory_longitudinal_series_opens_bcr_route(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "prior_prostatectomy": "1",
            "prior_radiation": "0",
            "metastasis_site": "M0",
            "psa_postop": 0.24,
            "psa_history": [
                {"value": 0.22, "date": "2026-01-01"},
                {"value": 0.24, "date": "2026-04-15"},
            ],
        }
        result = registry.classify_state(payload)
        assert result["state"] == "recurrence_bcr"

    def test_psma_only_crpc_upstaging_stays_in_verification_lane(self, registry):
        payload = {
            "known_cancer_diagnosis": "1",
            "systemic_progression_context": "confirmed_crpc",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M0",
            "psma_stage_after_psma": "M1b",
            "psma_pet_done": 1,
            "psma_positive": 1,
        }
        result = registry.classify_state(payload)
        assert result["state"] == "adt_progression_verification"
        assert result["psma_only_upstaging"] is True
        assert result["metastatic_detection_basis"] == "psma_only"
        assert result["restaging_update_required"] is True


class TestPostRtFollowupSchemas:
    def test_schema_is_exposed_and_has_required_groups(self, registry):
        schema = registry.get_module_schema("post_radiotherapy_followup")
        assert schema["module"] == "post_radiotherapy_followup"
        assert len(schema["fields"]) > 30
        groups = {f.get("group") for f in schema["fields"] if f.get("group")}
        assert "Contexto del tratamiento RT" in groups
        assert "Cinética PSA y nadir" in groups
        assert "Toxicidad tardía urinaria" in groups
        assert "Toxicidad tardía intestinal" in groups

    def test_service_module_id_is_stable(self):
        service = PostRadiotherapyFollowupService()
        assert service.module_id == "post_radiotherapy_followup"


class TestPhoenixLogic:
    def test_no_phoenix_failure_labels_surveillance(self):
        nccn = classify_post_rt_followup_nccn({"psa_current": 0.4, "psa_nadir": 0.3})
        assert "sin recurrencia" in nccn["label"].lower()
        eau = classify_post_rt_followup_eau({"psa_current": 0.4, "psa_nadir": 0.3})
        assert "sin recurrencia" in eau["label"].lower()

    def test_phoenix_failure_labels_biochemical_failure(self):
        nccn = classify_post_rt_followup_nccn({"psa_current": 3.5, "psa_nadir": 0.3})
        assert "phoenix" in nccn["label"].lower() or "fallo" in nccn["label"].lower()
        eau = classify_post_rt_followup_eau({"psa_current": 3.5, "psa_nadir": 0.3})
        assert "recurrencia" in eau["label"].lower()

    def test_bounce_suspected_suppresses_failure_label(self):
        nccn = classify_post_rt_followup_nccn(
            {"psa_current": 1.8, "psa_nadir": 0.3, "bounce_suspected": "1"}
        )
        assert "sin recurrencia" in nccn["label"].lower()

    def test_failure_definition_marks_scalar_phoenix_delta_as_threshold_only_unconfirmed(self):
        payload = {
            "prior_radiation": "1",
            "psa_current": 3.5,
            "phoenix_delta": 2.5,
        }
        failure = build_post_rt_failure_definition(payload)
        assert failure["phoenix_threshold_reached"] is True
        assert failure["phoenix_confirmation_status"] == "threshold_only_unconfirmed"
        assert StateClassifierService._has_post_rt_recurrence_signal(payload) is True

    def test_runtime_payload_backfills_post_rt_context_and_psa_history_from_structured_records(self):
        patient = {
            "radiation": [{"rt_date": "2024-01-10", "rt_technique": "IMRT"}],
            "psa_series": [
                {"sample_date": "2025-12-01", "value": 0.4, "source": "baseline"},
                {"sample_date": "2026-01-01", "value": 2.6, "source": "followup"},
                {"sample_date": "2026-04-15", "value": 2.9, "source": "followup"},
            ],
        }
        payload = build_runtime_payload(
            patient,
            latest_assessment=None,
            effective_state="post_radiotherapy_or_local_salvage",
        )
        assert payload["prior_radiation"] == 1
        assert payload["radiation_date"] == "2024-01-10"
        assert payload["prior_rt_modality"] == "IMRT"
        assert payload["psa_current"] == 2.9
        assert [point["value"] for point in payload["psa_history"]] == [0.4, 2.6, 2.9]

    def test_reconciled_state_rebuilds_post_rt_followup_from_diagnostic_shell_without_phoenix(self):
        patient = {
            "baseline": {
                "prior_radiation": 1,
                "radiation_date": "2024-01-10",
                "prior_rt_modality": "IMRT",
            },
            "latest_assessment": {"state": "diagnostic_workup", "input_snapshot": {}},
            "prior_history": {"current_state": "diagnostic_workup"},
            "radiation": [{"rt_date": "2024-01-10", "rt_technique": "IMRT"}],
            "psa_series": [
                {"sample_date": "2025-12-01", "value": 0.4},
                {"sample_date": "2026-04-15", "value": 1.1},
            ],
        }
        reconciliation = build_reconciled_state(patient, patient["latest_assessment"])
        assert reconciliation["reconciled_state"] == "post_radiotherapy_followup"
        assert "ruta post-rt" in reconciliation["state_conflict_reason"].lower()

    def test_reconciled_state_rebuilds_post_rt_salvage_from_longitudinal_phoenix_series(self):
        patient = {
            "baseline": {
                "prior_radiation": 1,
                "radiation_date": "2024-01-10",
                "prior_rt_modality": "IMRT",
            },
            "latest_assessment": {"state": "diagnostic_workup", "input_snapshot": {}},
            "prior_history": {"current_state": "diagnostic_workup"},
            "radiation": [{"rt_date": "2024-01-10", "rt_technique": "IMRT"}],
            "psa_series": [
                {"sample_date": "2025-12-01", "value": 0.4},
                {"sample_date": "2026-01-01", "value": 2.6},
                {"sample_date": "2026-04-15", "value": 2.9},
            ],
        }
        reconciliation = build_reconciled_state(patient, patient["latest_assessment"])
        assert reconciliation["reconciled_state"] == "post_radiotherapy_or_local_salvage"

    def test_display_capture_field_summary_humanizes_post_rt_release_fields(self):
        labels = display_capture_field_summary(
            [
                "psa_nadir",
                "phoenix_delta",
                "prior_rt_modality",
                "mpmri_done",
                "biopsy_proven_local_recurrence",
            ],
            limit=24,
        )
        assert "Nadir de PSA" in labels
        assert "Delta Phoenix" in labels
        assert "Modalidad de radioterapia previa" in labels
        assert "mpMRI prostática disponible" in labels
        assert "Biopsia confirmatoria de recurrencia local" in labels
        assert "psa_nadir" not in labels
        assert "mpmri_done" not in labels


class TestEvaluateModule:
    def test_evaluate_without_phoenix_returns_vigilance_family(self, registry):
        result = registry.evaluate_module("post_radiotherapy_followup", _base_payload())
        assert result["state"] == "post_radiotherapy_followup"
        assert result["report_sections"]["phoenix_assessment"]["phoenix_failure"] is False
        assert result["report_sections"]["restaging_plan"] is None
        assert any(
            "Vigilancia" in item.get("name", "")
            for item in result["eligible_treatments"]
        )

    def test_evaluate_with_phoenix_builds_restaging_plan(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(psa_current=3.0, psa_nadir=0.3),
        )
        assert result["report_sections"]["phoenix_assessment"]["phoenix_failure"] is True
        assert result["report_sections"]["restaging_plan"] is not None
        plan = result["report_sections"]["restaging_plan"]
        assert "PSMA" in plan["imaging"]
        assert plan["transition_state"] == "post_radiotherapy_or_local_salvage"

    def test_evaluate_with_confirmed_longitudinal_phoenix_marks_release_gate_ready_for_restaging(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(
                psa_nadir=0.3,
                psa_current=2.7,
                psa_history=[
                    {"value": 2.4, "date": "2026-01-01"},
                    {"value": 2.7, "date": "2026-04-15"},
                ],
            ),
        )
        failure = result["report_sections"]["post_rt_failure_definition"]
        assert failure["phoenix_threshold_reached"] is True
        assert failure["phoenix_confirmation_status"] == "confirmed_longitudinal"
        assert failure["salvage_release_status"] == "ready_for_restaging_gate"

    def test_evaluate_with_brachy_bounce_keeps_salvage_gate_blocked(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(
                prior_rt_modality="LDR brachytherapy",
                prior_rt_completion_date="2024-01-01",
                psa_nadir=0.4,
                psa_current=1.1,
                psa_current_date="2025-06-01",
                psa_history=[
                    {"value": 0.4, "date": "2024-06-01"},
                    {"value": 1.1, "date": "2025-06-01"},
                ],
            ),
        )
        failure = result["report_sections"]["post_rt_failure_definition"]
        assert failure["bounce_suspected"] is True
        assert failure["salvage_release_status"] == "blocked_bounce_suspected"

    def test_urinary_grade_triggers_toxicity_management(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(late_urinary_grade="3"),
        )
        actions = result["report_sections"]["toxicity_management"]
        assert any(a.get("system") == "urinary" for a in actions)

    def test_smoker_adds_cesation_screening(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(smoking_status="Activo"),
        )
        screening = result["report_sections"]["second_primary_screening"]
        assert any("tabáquica" in (s.get("screening", "")) for s in screening)

    def test_active_adt_enables_survivorship_actions(self, registry):
        result = registry.evaluate_module(
            "post_radiotherapy_followup",
            _base_payload(adt_active="1", adt_duration_months=24),
        )
        assert result["report_sections"]["adt_survivorship"]

    def test_missing_inputs_are_reported(self, registry):
        payload = _base_payload()
        payload.pop("psa_nadir", None)
        payload["psa_nadir"] = ""
        result = registry.evaluate_module("post_radiotherapy_followup", payload)
        assert "psa_nadir" in result.get("missing_critical_inputs", [])

    def test_post_rt_copilot_recognizes_radiotherapy_course_context_without_explicit_prior_radiation(
        self,
        monkeypatch,
    ):
        _enable_post_rt_copilot(monkeypatch)
        latest_assessment = {
            "state": "post_radiotherapy_or_local_salvage",
            "input_snapshot": {
                "psa_nadir": 0.4,
                "psa_current": 2.9,
                "psa_history": [
                    {"value": 2.6, "date": "2026-01-01"},
                    {"value": 2.9, "date": "2026-04-15"},
                ],
                "prior_rt_modality": "IMRT",
                "biopsy_proven_local_recurrence": 1,
                "biopsy_date": "2026-03-10",
                "biopsy_grade_group": 3,
                "mpmri_done": 1,
                "mpmri_date": "2026-03-05",
                "mpmri_localized_recurrence": 1,
                "local_recurrence_site": "focal peripheral gland",
                "psma_pet_done": 1,
                "psma_radioligand": "68Ga-PSMA-11",
                "psma_rads_score": "4",
                "psma_uptake_pattern": "focal",
                "psma_stage_after_psma": "M0",
            },
        }
        patient = {
            "latest_assessment": latest_assessment,
            "radiotherapy_courses_detailed": [
                {"rt_start_date": "2024-01-10", "rt_end_date": "2024-03-15", "modality": "IMRT"}
            ],
            "psa_series": [
                {"sample_date": "2025-12-01", "value": 0.4},
                {"sample_date": "2026-01-01", "value": 2.6},
                {"sample_date": "2026-04-15", "value": 2.9},
            ],
        }

        bundle = PostRTSalvageCopilotService().evaluate(
            patient,
            effective_state="post_radiotherapy_or_local_salvage",
            latest_assessment=latest_assessment,
            longitudinal_bundle={"longitudinal_truth_snapshot": {"field_values": {}}},
        )

        assert bundle["available"] is True
        assert bundle["status"] in {"shadow", "shadow-blocked"}
        assert bundle["effective_state"] == "post_radiotherapy_or_local_salvage"
        assert bundle["post_rt_failure_definition"]["phoenix_confirmation_status"] in {
            "confirmed_longitudinal",
            "biopsy_confirmed",
        }


class TestEvidenceRegistryIntegration:
    def test_module_evidence_is_exposed(self, registry):
        evidence = registry.get_module_evidence("post_radiotherapy_followup")
        assert evidence["module"] == "post_radiotherapy_followup"
        assert evidence["nccn"]["version"] == "5.2026"
        assert evidence["eau"]["version"] == "2026"
        assert "PROS-9" in evidence["nccn_panels"]
        assert any("Follow-up" in s for s in evidence["eau_sections"])

    def test_module_appears_in_registry_list(self, registry):
        module_ids = {m["module"] for m in registry.list_modules()}
        assert "post_radiotherapy_followup" in module_ids
