from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import tempfile
import uuid
from typing import Any, Iterator

import tracking_db

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
from prostanet.domains.patient_tracking.service import PatientTrackingService


DEFAULT_BASE_URL = "http://127.0.0.1:8080"


@contextmanager
def validation_db_context(cohort_mode: str = "isolated_temp_db") -> Iterator[dict[str, Any]]:
    original_db_path = tracking_db.get_db_path()
    temp_dir = None
    db_path = original_db_path
    if cohort_mode == "isolated_temp_db":
        temp_dir = tempfile.TemporaryDirectory(prefix="prostanet_validation_")
        db_path = str(Path(temp_dir.name) / "validation.db")
        tracking_db.configure_db_path(db_path)
        tracking_db.init_tracking_db()
    try:
        yield {"db_path": db_path, "cohort_mode": cohort_mode}
    finally:
        tracking_db.configure_db_path(original_db_path)
        if temp_dir:
            temp_dir.cleanup()


def _register_case_patient(
    trajectory: dict[str, Any],
    *,
    run_id: str,
    case_index: int,
    registry: ModuleRegistry,
    assessment_service: ClinicalAssessmentService,
    tracking_service: PatientTrackingService,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    baseline_payload = tracking_service.canonicalize_payload(dict(trajectory.get("baseline_payload") or {}))
    result = registry.evaluate_module(str(trajectory.get("module_id") or ""), baseline_payload)
    assessment_id = assessment_service.create_draft(
        module_id=str(trajectory.get("module_id") or ""),
        state=result.get("state", str(trajectory.get("module_id") or "")),
        input_snapshot=baseline_payload,
        result_snapshot=result,
        guideline_versions=registry.get_guidelines_metadata(),
    )
    assessment = assessment_service.get_draft(int(assessment_id)) if assessment_id else None
    patient_payload = {
        **baseline_payload,
        "nss": f"VAL-{run_id[:8]}-{case_index:03d}",
        "full_name": f"Paciente Validación {case_index:03d}",
        "dob": f"196{case_index % 10}-01-15",
        "assessment_state": str(trajectory.get("module_id") or ""),
    }
    merged_payload = tracking_service.merge_assessment_payload(assessment, patient_payload) if assessment else tracking_service.canonicalize_payload(patient_payload)
    patient_id, message, _registration_metadata = tracking_db.register_new_patient(merged_payload, assessment=assessment)
    if patient_id is None:
        raise RuntimeError(f"No se pudo registrar el caso {trajectory.get('scenario_id')}: {message}")
    if assessment_id:
        linked, link_message = assessment_service.attach_to_patient(int(assessment_id), int(patient_id))
        if not linked:
            raise RuntimeError(f"No se pudo vincular la evaluación clínica: {link_message}")
    bundle = tracking_db.refresh_longitudinal_intelligence(int(patient_id), force_recompute=True)
    patient_record = tracking_db.get_patient_full_record(int(patient_id)) or {}
    return int(patient_id), bundle, patient_record


def capture_patient_validation_snapshot(patient_id: int, *, base_url: str) -> dict[str, Any]:
    patient = tracking_db.get_patient_full_record(patient_id) or {}
    bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)
    schedule_bundle = tracking_db.sync_scheduled_events(
        patient,
        state=str((bundle.get("signals") or {}).get("effective_state") or (bundle.get("signals") or {}).get("reconciled_state") or ""),
        management_track=str((bundle.get("signals") or {}).get("effective_management_track") or (bundle.get("signals") or {}).get("reconciled_management_track") or ""),
    )
    return {
        "patient_id": patient_id,
        "patient_nss": (patient.get("identity") or {}).get("nss", ""),
        "signals": bundle.get("signals", {}),
        "next_best_action": bundle.get("next_best_action", {}),
        "schedule": schedule_bundle,
        "labs": bundle.get("laboratory_intelligence_profile", {}),
        "decision_trace": bundle.get("decision_recalculation_trace", {}),
        "longitudinal_bundle": bundle,
        "patient_record": patient,
        "urls": {
            "profile": f"{base_url}/patient_profile/{patient_id}",
            "signals": f"{base_url}/api/patients/{patient_id}/signals",
            "schedule": f"{base_url}/api/patients/{patient_id}/schedule",
            "labs_intelligence": f"{base_url}/api/patients/{patient_id}/labs-intelligence",
            "decision_trace": f"{base_url}/api/patients/{patient_id}/decision-trace",
        },
    }


def seed_trajectory_case(
    trajectory: dict[str, Any],
    *,
    run_id: str,
    case_index: int,
    base_url: str = DEFAULT_BASE_URL,
    registry: ModuleRegistry | None = None,
    assessment_service: ClinicalAssessmentService | None = None,
    tracking_service: PatientTrackingService | None = None,
) -> dict[str, Any]:
    registry = registry or ModuleRegistry()
    assessment_service = assessment_service or ClinicalAssessmentService()
    tracking_service = tracking_service or PatientTrackingService()
    patient_id, baseline_bundle, patient_record = _register_case_patient(
        trajectory,
        run_id=run_id,
        case_index=case_index,
        registry=registry,
        assessment_service=assessment_service,
        tracking_service=tracking_service,
    )
    baseline_snapshot = capture_patient_validation_snapshot(patient_id, base_url=base_url)
    visit_reports = []
    for visit_index, visit in enumerate(list(trajectory.get("visits") or []), start=1):
        payload = tracking_service.canonicalize_payload(
            {
                **dict(visit.get("payload") or {}),
                "visit_type": "validation_followup",
                "state": trajectory.get("module_id"),
                "management_track": dict(visit.get("payload") or {}).get("management_track") or "",
                "disease_status": dict(visit.get("payload") or {}).get("disease_status") or "validation_followup",
                "clinician_notes": f"Validation run {run_id} step {visit_index}",
            }
        )
        success, response = tracking_db.save_stage_visit_bundle(patient_id, payload)
        if not success:
            raise RuntimeError(f"No se pudo guardar la visita {visit_index} de {trajectory.get('scenario_id')}: {response}")
        visit_snapshot = capture_patient_validation_snapshot(patient_id, base_url=base_url)
        visit_reports.append(
            {
                "step_index": visit_index,
                "visit_date": visit.get("visit_date"),
                "title": visit.get("title"),
                "payload": payload,
                "oracle": visit.get("oracle", {}),
                "actual": visit_snapshot,
            }
        )
    final_snapshot = visit_reports[-1]["actual"] if visit_reports else baseline_snapshot
    return {
        "run_id": run_id,
        "case_key": f"{run_id}:{trajectory.get('scenario_id')}",
        "scenario_id": trajectory.get("scenario_id"),
        "scenario_family": trajectory.get("scenario_family"),
        "title": trajectory.get("title"),
        "patient_id": patient_id,
        "patient_nss": (final_snapshot.get("patient_nss") or ""),
        "baseline_oracle": trajectory.get("baseline_oracle", {}),
        "clinical_oracle": trajectory.get("clinical_oracle", {}),
        "guideline_oracle": trajectory.get("guideline_oracle", {}),
        "baseline": baseline_snapshot,
        "visits": visit_reports,
        "final": final_snapshot,
    }


def seed_validation_cohort(
    trajectories: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    cohort_mode: str = "isolated_temp_db",
) -> dict[str, Any]:
    run_id = run_id or uuid.uuid4().hex
    seeded_cases: list[dict[str, Any]] = []
    registry = ModuleRegistry()
    assessment_service = ClinicalAssessmentService()
    tracking_service = PatientTrackingService()
    with validation_db_context(cohort_mode=cohort_mode) as context:
        for index, trajectory in enumerate(trajectories, start=1):
            seeded_cases.append(
                seed_trajectory_case(
                    trajectory,
                    run_id=run_id,
                    case_index=index,
                    base_url=base_url,
                    registry=registry,
                    assessment_service=assessment_service,
                    tracking_service=tracking_service,
                )
            )
        return {
            "run_id": run_id,
            "cohort_mode": context["cohort_mode"],
            "db_path": context["db_path"],
            "base_url": base_url,
            "generated_at": date.today().isoformat(),
            "cases": seeded_cases,
        }


__all__ = [
    "DEFAULT_BASE_URL",
    "capture_patient_validation_snapshot",
    "seed_trajectory_case",
    "seed_validation_cohort",
    "validation_db_context",
]
