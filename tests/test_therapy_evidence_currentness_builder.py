# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from datetime import date, timedelta

from prostanet.domains.patient_tracking.therapy_evidence_currentness_builder import (
    build_therapy_evidence_currentness_bundle,
)


def _entry(*, key: str, label: str, family: str, release_status: str = "ready_to_release") -> dict[str, object]:
    return {
        "therapy_key": key,
        "therapy_label": label,
        "family_code": family,
        "family_label": family,
        "decision_role": "selected",
        "eligibility_status": "preferred",
        "release_status": release_status,
    }


def test_currentness_builder_marks_m0_arpi_current_when_castration_and_m0_are_recent():
    today = date.today().isoformat()
    bundle = build_therapy_evidence_currentness_bundle(
        state="m0_crpc",
        clinical_fact_bundle={},
        therapeutic_readiness_bundle={
            "readiness_status": "ready_to_release",
            "therapy_rationale_entries": [_entry(key="ADT_DAROLUTAMIDE", label="Darolutamida + ADT", family="arpi_family")],
            "release_status_by_therapy": {"ADT_DAROLUTAMIDE": {"release_status": "ready_to_release"}},
        },
        signals={
            "testosterone": 18,
            "latest_testosterone_date": today,
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": today,
            "progression_pattern": "biochemical_only",
        },
        decision_input_requirements={},
        staging_adjudication_bundle={},
    )

    assert bundle["selected_therapy_evidence_status"] == "current"
    assert bundle["selected_therapy_release_status"] == "ready_to_release"
    assert bundle["release_blocked_by_stale_evidence"] is False


def test_currentness_builder_marks_m0_arpi_aging_when_restaging_is_old_but_not_expired():
    imaging_date = (date.today() - timedelta(days=120)).isoformat()
    bundle = build_therapy_evidence_currentness_bundle(
        state="m0_crpc",
        therapeutic_readiness_bundle={
            "readiness_status": "ready_to_release",
            "therapy_rationale_entries": [_entry(key="ADT_DAROLUTAMIDE", label="Darolutamida + ADT", family="arpi_family")],
            "release_status_by_therapy": {"ADT_DAROLUTAMIDE": {"release_status": "ready_to_release"}},
        },
        signals={
            "testosterone": 18,
            "latest_testosterone_date": date.today().isoformat(),
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "medical_adt_continuous",
            "conventional_imaging_status": "M0",
            "conventional_imaging_date": imaging_date,
            "progression_pattern": "biochemical_only",
        },
    )

    therapy = bundle["evidence_currentness_by_therapy"]["ADT_DAROLUTAMIDE"]
    assert bundle["selected_therapy_evidence_status"] == "aging"
    assert bundle["selected_therapy_release_status"] == "aging_review_needed"
    assert therapy["refresh_action_needed"] == "Actualizar reestadificación convencional y confirmar castración actual"
    assert "Fecha de imagen convencional" in therapy["aging_evidence_fields"]


def test_currentness_builder_blocks_parp_when_molecular_report_is_stale():
    report_date = (date.today() - timedelta(days=900)).isoformat()
    bundle = build_therapy_evidence_currentness_bundle(
        state="m1_crpc",
        therapeutic_readiness_bundle={
            "readiness_status": "ready_to_release",
            "therapy_rationale_entries": [_entry(key="OLAPARIB", label="Olaparib", family="parp_family")],
            "release_status_by_therapy": {"OLAPARIB": {"release_status": "ready_to_release"}},
        },
        signals={
            "testosterone": 14,
            "latest_testosterone_date": date.today().isoformat(),
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "ADT continua",
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "molecular_report_date": report_date,
        },
    )

    therapy = bundle["evidence_currentness_by_therapy"]["OLAPARIB"]
    assert bundle["selected_therapy_evidence_status"] == "stale"
    assert bundle["selected_therapy_release_status"] == "blocked_by_stale_evidence"
    assert therapy["refresh_action_needed"] == "Actualizar trazabilidad molecular HRR antes de liberar PARP"
    assert "Fecha del estudio molecular" in therapy["stale_evidence_fields"]


def test_currentness_builder_treats_untraceable_hrr_as_blocking_precision_release():
    bundle = build_therapy_evidence_currentness_bundle(
        state="m1_crpc",
        therapeutic_readiness_bundle={
            "readiness_status": "conditional_pending_closure",
            "therapy_rationale_entries": [_entry(key="OLAPARIB", label="Olaparib", family="parp_family", release_status="conditional_pending_closure")],
            "release_status_by_therapy": {"OLAPARIB": {"release_status": "conditional_pending_closure"}},
        },
        signals={
            "testosterone": 14,
            "latest_testosterone_date": date.today().isoformat(),
            "castrate_testosterone_status": "confirmed_castrate",
            "current_adt_context": "ADT continua",
            "hrr_status": "Positivo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "",
            "molecular_report_date": date.today().isoformat(),
        },
    )

    therapy = bundle["evidence_currentness_by_therapy"]["OLAPARIB"]
    assert therapy["release_status"] == "blocked_by_stale_evidence"
    assert "Gen HRR alterado" in therapy["traceability_gaps"]
    assert "Fuente del biomarcador" in therapy["traceability_gaps"]
