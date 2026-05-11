from __future__ import annotations

from typing import Any


LAB_METADATA = {
    "TESTOSTERONA": {"key": "testosterone", "label": "Testosterona", "unit": "ng/dL", "family": "endocrine"},
    "ANC": {"key": "anc", "label": "Neutrófilos absolutos", "unit": "/mm3", "family": "hematologic"},
    "PLAQUETAS": {"key": "platelets", "label": "Plaquetas", "unit": "/mm3", "family": "hematologic"},
    "HEMOGLOBINA": {"key": "hemoglobin", "label": "Hemoglobina", "unit": "g/dL", "family": "hematologic"},
    "ALP": {"key": "alp", "label": "Fosfatasa alcalina", "unit": "UI/L", "family": "bone_burden"},
    "LDH": {"key": "ldh", "label": "LDH", "unit": "UI/L", "family": "bone_burden"},
    "CREATININA": {"key": "creatinine", "label": "Creatinina", "unit": "mg/dL", "family": "renal"},
    "BILIRRUBINA": {"key": "bilirubin", "label": "Bilirrubina", "unit": "mg/dL", "family": "hepatic"},
    "AST": {"key": "ast", "label": "AST", "unit": "UI/L", "family": "hepatic"},
    "ALT": {"key": "alt", "label": "ALT", "unit": "UI/L", "family": "hepatic"},
    "GGT": {"key": "ggt", "label": "GGT", "unit": "UI/L", "family": "hepatic"},
    "GLUCOSA": {"key": "glucose", "label": "Glucosa", "unit": "mg/dL", "family": "metabolic"},
    "HBA1C": {"key": "hba1c", "label": "HbA1c", "unit": "%", "family": "metabolic"},
    "CALCIO": {"key": "calcium_level", "label": "Calcio", "unit": "mg/dL", "family": "bone_support"},
    "VITAMINA_D": {"key": "vitamin_d_level", "label": "Vitamina D", "unit": "ng/mL", "family": "bone_support"},
    "ALBUMINA": {"key": "albumin", "label": "Albúmina", "unit": "g/dL", "family": "hepatic"},
    "CISTATINA_C": {"key": "cystatin_c", "label": "Cistatina C", "unit": "mg/L", "family": "renal"},
}

LAB_REFERENCE_RANGES_BY_FIELD_KEY = {
    "testosterone": {"low": 300, "high": 1000, "unit": "ng/dL"},
    "hemoglobin": {"low": 13.5, "high": 17.5, "unit": "g/dL"},
    "anc": {"low": 1500, "high": 7800, "unit": "/mm3"},
    "platelets": {"low": 150000, "high": 450000, "unit": "/mm3"},
    "creatinine": {"low": 0.7, "high": 1.3, "unit": "mg/dL"},
    "bilirubin": {"low": 0.2, "high": 1.2, "unit": "mg/dL"},
    "ast": {"low": 0, "high": 40, "unit": "U/L"},
    "alt": {"low": 0, "high": 40, "unit": "U/L"},
    "alp": {"low": 44, "high": 120, "unit": "U/L"},
    "ldh": {"low": 135, "high": 225, "unit": "U/L"},
    "albumin": {"low": 3.5, "high": 5.0, "unit": "g/dL"},
    "calcium_level": {"low": 8.5, "high": 10.5, "unit": "mg/dL"},
    "vitamin_d_level": {"low": 30, "high": 100, "unit": "ng/mL"},
    "glucose": {"low": 70, "high": 99, "unit": "mg/dL"},
    "ggt": {"low": 0, "high": 60, "unit": "U/L"},
    "cystatin_c": {"low": 0.6, "high": 1.2, "unit": "mg/L"},
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado")


def lab_reference_range(field_key: str) -> dict[str, Any]:
    raw = LAB_REFERENCE_RANGES_BY_FIELD_KEY.get(str(field_key or ""))
    if not raw:
        return {}
    low = raw.get("low")
    high = raw.get("high")
    unit = str(raw.get("unit") or "")
    if low is None or high is None:
        label = str(raw.get("label") or "").strip()
    else:
        label = f"Rango estándar institucional: {low:g}-{high:g} {unit}".strip()
    return {
        "reference_range_low": low,
        "reference_range_high": high,
        "reference_range_unit": unit,
        "reference_range_label": label,
        "reference_range_source": "institutional",
    }


def build_laboratory_series(patient: dict[str, Any]) -> dict[str, dict[str, Any]]:
    series_map: dict[str, dict[str, Any]] = {}
    for entry in list(patient.get("biomarker_longitudinal") or []):
        biomarker_type = str(entry.get("biomarker_type") or "").upper()
        metadata = LAB_METADATA.get(biomarker_type)
        if not metadata:
            continue
        target = series_map.setdefault(
            metadata["key"],
            {
                "key": metadata["key"],
                "label": metadata["label"],
                "unit": metadata["unit"],
                "family": metadata["family"],
                "points": [],
                "source": "biomarker_longitudinal",
            },
        )
        if _is_present(entry.get("value")) and _is_present(entry.get("sample_date")):
            target["points"].append(
                {
                    "date": str(entry.get("sample_date") or "")[:10],
                    "value": entry.get("value"),
                }
            )

    latest_followup = (patient.get("follow_ups") or [])[-1] if patient.get("follow_ups") else {}
    followup_field_map = {
        "testosterone": "testosterone_current",
        "hemoglobin": "hemoglobin_current",
        "alp": "alp_current",
        "ldh": "ldh_current",
        "creatinine": "creatinine_current",
        "bilirubin": "bilirubin_current",
        "ast": "ast_current",
        "alt": "alt_current",
        "ggt": "ggt_current",
        "glucose": "glucose_current",
        "albumin": "albumin_current",
        "cystatin_c": "cystatin_c_current",
        "hba1c": "hba1c",
        "calcium_level": "calcium_level",
        "vitamin_d_level": "vitamin_d_level",
    }
    followup_date = str(latest_followup.get("visit_date") or "")[:10]
    for metadata in LAB_METADATA.values():
        key = metadata["key"]
        field_name = followup_field_map.get(key)
        if not field_name or not _is_present(latest_followup.get(field_name)) or not followup_date:
            continue
        target = series_map.setdefault(
            key,
            {
                "key": key,
                "label": metadata["label"],
                "unit": metadata["unit"],
                "family": metadata["family"],
                "points": [],
                "source": "follow_up_visits",
            },
        )
        if not any(point.get("date") == followup_date for point in target["points"]):
            target["points"].append({"date": followup_date, "value": latest_followup.get(field_name)})

    for item in series_map.values():
        item["points"] = sorted(item["points"], key=lambda point: str(point.get("date") or ""))
        if item["points"]:
            item["latest_value"] = item["points"][-1]["value"]
            item["latest_date"] = item["points"][-1]["date"]
    return series_map
