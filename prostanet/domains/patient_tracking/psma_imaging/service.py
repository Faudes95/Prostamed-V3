from __future__ import annotations

from typing import Any

from .contracts import (
    derive_psma_positive,
    normalize_psma_pattern,
    normalize_psma_radioligand,
    normalize_psma_rads,
    normalize_stage_label,
)
from .repository import latest_psma_study


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "si", "sí", "yes", "upstaging", "upstaged"}:
        return True
    if lowered in {"0", "false", "no", "sin cambio"}:
        return False
    return None


def _normalize_locations(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _derive_pattern(*, explicit_pattern: Any, total_lesions: Any, locations: list[str], psma_result: Any) -> str:
    normalized = normalize_psma_pattern(explicit_pattern)
    if normalized:
        return normalized
    result_text = str(psma_result or "").lower()
    count = _safe_int(total_lesions) or len(locations)
    if "disemin" in result_text:
        return "diseminado"
    if "oligo" in result_text:
        return "multifocal"
    if "local" in result_text or "pélv" in result_text or "pelv" in result_text:
        return "focal"
    if count <= 0:
        return ""
    if count == 1:
        return "focal"
    if count <= 5:
        return "multifocal"
    return "diseminado"


def _derive_clinical_pattern(pattern: str, result_text: str, stage_after: str) -> str:
    lowered = result_text.lower()
    if stage_after in {"M1b", "M1c"} or pattern == "diseminado":
        return "diseminado"
    if "local" in lowered or "pelv" in lowered:
        return "local_pelvic"
    if "oligo" in lowered or pattern == "multifocal":
        return "oligometastatic"
    if "neg" in lowered:
        return "negative"
    if pattern == "focal":
        return "local_pelvic"
    return "indeterminado"


def _infer_psma_result_from_payload(payload: dict[str, Any]) -> str:
    explicit_result = payload.get("psma_pet_result") or payload.get("psma_result")
    if _is_present(explicit_result):
        return str(explicit_result)

    explicit_positive = payload.get("psma_positive")
    if str(explicit_positive).strip() in {"1", "true", "True"}:
        return "positivo"
    if str(explicit_positive).strip() in {"0", "false", "False"}:
        return "negativo"

    if any(
        _is_present(payload.get(key))
        for key in (
            "psma_index_lesion_site",
            "psma_index_lesion_suvmax",
            "psma_uptake_pattern",
            "psma_rads_score",
            "psma_total_lesions",
            "psma_lesion_locations",
            "psma_stage_after_psma",
        )
    ):
        return "positivo"
    return ""


def normalize_psma_imaging_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
    findings = dict(payload.get("findings") or {})
    psma_result = payload.get("psma_result")
    if not psma_result and payload.get("study_type") and "psma" in str(payload.get("study_type", "")).lower():
        if payload.get("psma_pet_result"):
            psma_result = payload.get("psma_pet_result")
    radioligand = normalize_psma_radioligand(
        payload.get("psma_radioligand")
        or findings.get("psma_radioligand")
        or payload.get("radioligand")
    )
    index_site = payload.get("psma_index_lesion_site") or findings.get("psma_index_lesion_site") or payload.get("index_lesion_location")
    suvmax = _safe_float(
        payload.get("psma_index_lesion_suvmax")
        if _is_present(payload.get("psma_index_lesion_suvmax"))
        else payload.get("psma_suv_max")
    )
    total_lesions = _safe_int(payload.get("psma_total_lesions") if _is_present(payload.get("psma_total_lesions")) else findings.get("psma_total_lesions"))
    locations = _normalize_locations(
        payload.get("psma_lesion_locations")
        if _is_present(payload.get("psma_lesion_locations"))
        else findings.get("lesion_locations")
    )
    pattern = _derive_pattern(
        explicit_pattern=payload.get("psma_uptake_pattern") or findings.get("psma_uptake_pattern"),
        total_lesions=total_lesions,
        locations=locations,
        psma_result=psma_result,
    )
    rads = normalize_psma_rads(payload.get("psma_rads_score") or findings.get("psma_rads_score"))
    conventional_stage = normalize_stage_label(
        payload.get("conventional_stage_before_psma")
        or findings.get("conventional_stage_before_psma")
        or payload.get("conventional_imaging_status")
    )
    psma_stage = normalize_stage_label(
        payload.get("psma_stage_after_psma")
        or findings.get("psma_stage_after_psma")
    )
    management_changed = _normalize_optional_bool(payload.get("psma_management_changed"))
    upstaged = _normalize_optional_bool(payload.get("psma_upstaged_vs_conventional"))
    if upstaged is None and conventional_stage and psma_stage and conventional_stage != "No comparable":
        stage_rank = {"M0": 0, "M1a": 1, "M1b": 2, "M1c": 3}
        if conventional_stage in stage_rank and psma_stage in stage_rank:
            upstaged = stage_rank[psma_stage] > stage_rank[conventional_stage]
    findings.update(
        {
            "psma_radioligand": radioligand or None,
            "psma_index_lesion_site": index_site or None,
            "psma_index_lesion_suvmax": suvmax,
            "psma_uptake_pattern": pattern or None,
            "psma_rads_score": rads or None,
            "lesion_locations": locations,
            "psma_total_lesions": total_lesions,
            "psma_negative_dominant_lesions": bool(
                payload.get("psma_negative_dominant_lesions")
                if payload.get("psma_negative_dominant_lesions") not in (None, "")
                else findings.get("psma_negative_dominant_lesions")
            ),
            "conventional_stage_before_psma": conventional_stage or None,
            "psma_stage_after_psma": psma_stage or None,
            "psma_upstaged_vs_conventional": upstaged,
            "psma_management_changed": management_changed,
            "psma_positive": derive_psma_positive(psma_result, total_lesions, locations, suvmax),
        }
    )
    payload.update(
        {
            "psma_result": psma_result,
            "psma_suv_max": suvmax,
            "psma_radioligand": radioligand or None,
            "psma_index_lesion_site": index_site or None,
            "psma_index_lesion_suvmax": suvmax,
            "psma_uptake_pattern": pattern or None,
            "psma_rads_score": rads or None,
            "conventional_stage_before_psma": conventional_stage or None,
            "psma_stage_after_psma": psma_stage or None,
            "psma_upstaged_vs_conventional": upstaged,
            "psma_management_changed": management_changed,
            "findings": {key: value for key, value in findings.items() if value is not None and value != ""},
        }
    )
    return payload


def build_psma_structured_profile(patient: dict[str, Any]) -> dict[str, Any]:
    latest = latest_psma_study(patient.get("imaging") or [])
    if not latest:
        return {"available": False, "structured_complete": False}
    normalized = normalize_psma_imaging_payload(latest)
    findings = normalized.get("findings") or {}
    total_lesions = _safe_int(findings.get("psma_total_lesions")) or 0
    locations = _normalize_locations(findings.get("lesion_locations"))
    present_core = sum(
        1
        for value in (
            normalized.get("psma_radioligand"),
            normalized.get("psma_index_lesion_suvmax"),
            normalized.get("psma_uptake_pattern"),
            normalized.get("psma_rads_score"),
            normalized.get("conventional_stage_before_psma"),
            normalized.get("psma_stage_after_psma"),
        )
        if _is_present(value)
    )
    source_mode = "structured" if present_core >= 2 else "legacy"
    structured_completeness = round((present_core / 6) * 100.0, 1)
    clinical_pattern = _derive_clinical_pattern(
        str(normalized.get("psma_uptake_pattern") or ""),
        str(normalized.get("psma_result") or ""),
        str(normalized.get("psma_stage_after_psma") or ""),
    )
    return {
        "available": True,
        "study_date": normalized.get("study_date"),
        "study_type": normalized.get("study_type"),
        "psma_radioligand": normalized.get("psma_radioligand") or "",
        "psma_index_lesion_site": normalized.get("psma_index_lesion_site") or "",
        "psma_index_lesion_suvmax": normalized.get("psma_index_lesion_suvmax"),
        "psma_uptake_pattern": normalized.get("psma_uptake_pattern") or "",
        "psma_rads_score": normalized.get("psma_rads_score") or "",
        "psma_total_lesions": total_lesions,
        "psma_lesion_locations": locations,
        "psma_negative_dominant_lesions": bool(findings.get("psma_negative_dominant_lesions")),
        "conventional_stage_before_psma": normalized.get("conventional_stage_before_psma") or "",
        "psma_stage_after_psma": normalized.get("psma_stage_after_psma") or "",
        "psma_upstaged_vs_conventional": normalized.get("psma_upstaged_vs_conventional"),
        "psma_management_changed": normalized.get("psma_management_changed"),
        "psma_positive": bool(findings.get("psma_positive")),
        "psma_result": normalized.get("psma_result") or "",
        "source_mode": source_mode,
        "structured_completeness_pct": structured_completeness,
        "structured_complete": structured_completeness >= 66.0,
        "clinical_pattern": clinical_pattern,
        "findings": findings,
    }


def build_psma_structured_profile_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    imaging_like = normalize_psma_imaging_payload(
        {
            "study_date": payload.get("study_date") or payload.get("visit_date") or payload.get("local_therapy_date"),
            "study_type": "PSMA-PET",
            "psma_result": _infer_psma_result_from_payload(payload),
            "psma_suv_max": payload.get("psma_suv_max"),
            "psma_radioligand": payload.get("psma_radioligand"),
            "psma_index_lesion_site": payload.get("psma_index_lesion_site"),
            "psma_index_lesion_suvmax": payload.get("psma_index_lesion_suvmax"),
            "psma_uptake_pattern": payload.get("psma_uptake_pattern"),
            "psma_rads_score": payload.get("psma_rads_score"),
            "psma_total_lesions": payload.get("psma_total_lesions"),
            "psma_lesion_locations": payload.get("psma_lesion_locations"),
            "psma_negative_dominant_lesions": payload.get("psma_negative_dominant_lesions"),
            "conventional_stage_before_psma": payload.get("conventional_stage_before_psma") or payload.get("conventional_imaging_status"),
            "psma_stage_after_psma": payload.get("psma_stage_after_psma"),
            "psma_upstaged_vs_conventional": payload.get("psma_upstaged_vs_conventional"),
            "psma_management_changed": payload.get("psma_management_changed"),
            "findings": {},
        }
    )
    return build_psma_structured_profile({"imaging": [imaging_like]})
