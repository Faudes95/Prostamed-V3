from __future__ import annotations

from tracking_db import (
    attach_clinical_assessment_to_patient,
    create_clinical_assessment_draft,
    get_clinical_assessment,
)


class ClinicalAssessmentService:
    def create_draft(
        self,
        *,
        module_id: str,
        state: str,
        input_snapshot: dict,
        result_snapshot: dict,
        guideline_versions: dict,
    ) -> int | None:
        return create_clinical_assessment_draft(
            module_id,
            state,
            input_snapshot,
            result_snapshot,
            guideline_versions,
        )

    def get_draft(self, assessment_id: int) -> dict | None:
        return get_clinical_assessment(assessment_id)

    def attach_to_patient(self, assessment_id: int, patient_id: int) -> tuple[bool, str]:
        return attach_clinical_assessment_to_patient(assessment_id, patient_id)
