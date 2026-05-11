from __future__ import annotations

from typing import Any


def latest_psma_study(imaging: list[dict[str, Any]] | None) -> dict[str, Any]:
    studies = []
    for item in imaging or []:
        if "psma" in str(item.get("study_type", "")).lower():
            studies.append(item)
    if not studies:
        return {}
    studies.sort(key=lambda row: (str(row.get("study_date") or ""), int(row.get("id") or 0)), reverse=True)
    return dict(studies[0])


def imaging_studies_for_psma_analytics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    studies: list[dict[str, Any]] = []
    for record in records or []:
        patient_id = ((record.get("identity") or {}).get("id"))
        for study in record.get("imaging") or []:
            if "psma" not in str(study.get("study_type", "")).lower():
                continue
            item = dict(study)
            item["patient_id"] = patient_id
            studies.append(item)
    return studies
