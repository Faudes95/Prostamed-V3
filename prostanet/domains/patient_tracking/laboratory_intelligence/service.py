from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.laboratory_intelligence.alert_engine import (
    build_laboratory_alerts,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.contracts import (
    LaboratoryTrendSeries,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.repository import (
    build_laboratory_series,
)
from prostanet.domains.patient_tracking.longitudinal_truth_service import truth_value


FAMILY_LABELS = {
    "endocrine": "Eje androgénico",
    "hematologic": "Hematología",
    "bone_burden": "Carga ósea / tumoral",
    "renal": "Función renal",
    "hepatic": "Seguridad hepática",
    "metabolic": "Metabolismo",
    "bone_support": "Soporte óseo",
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado")


def _series_status(key: str, latest_value: Any) -> str:
    try:
        if latest_value in (None, ""):
            return "neutral"
        value = float(latest_value)
    except (TypeError, ValueError):
        return "neutral"
    if key == "testosterone":
        return "success" if value <= 50 else "warning"
    if key == "hemoglobin":
        return "danger" if value < 8 else "warning" if value < 10 else "neutral"
    if key == "alp":
        return "danger" if value > 360 else "warning" if value > 240 else "neutral"
    if key == "creatinine":
        return "warning" if value >= 1.5 else "neutral"
    if key in {"ast", "alt"}:
        return "danger" if value > 120 else "warning" if value > 40 else "neutral"
    if key == "bilirubin":
        return "warning" if value > 2 else "neutral"
    return "neutral"


def _family_payload(series_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for series in series_items:
        family = str(series.get("family") or "other")
        bucket = families.setdefault(
            family,
            {
                "key": family,
                "label": FAMILY_LABELS.get(family, family.replace("_", " ").title()),
                "series": [],
            },
        )
        bucket["series"].append(series)
    return list(families.values())


def build_laboratory_payload_for_runtime_alerts(
    patient: dict[str, Any],
    *,
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = patient.get("longitudinal_truth_snapshot") or {}
    field_values = dict(snapshot.get("field_values") or {})
    treatment_text = str(field_values.get("current_treatment") or truth_value(patient, "current_treatment", "drug_scheme", default="") or "")
    return {
        "latest_values": field_values,
        "treatment_text": treatment_text,
        "adt_context": str(field_values.get("current_adt_context") or truth_value(patient, "current_adt_context", default="") or ""),
        "management_track": management_track or str(field_values.get("management_track") or ""),
        "latest_assessment": latest_assessment or patient.get("latest_assessment") or {},
    }


def build_laboratory_intelligence_profile(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    series_map = build_laboratory_series(patient)
    series_items = []
    for item in series_map.values():
        trend = LaboratoryTrendSeries(
            key=item["key"],
            label=item["label"],
            unit=item["unit"],
            family=item["family"],
            points=item.get("points", []),
            latest_value=item.get("latest_value"),
            latest_date=item.get("latest_date", ""),
            status=_series_status(item["key"], item.get("latest_value")),
            source=item.get("source", "longitudinal"),
        ).to_dict()
        series_items.append(trend)
    series_items.sort(key=lambda item: (item.get("family", ""), item.get("label", "")))

    runtime_payload = build_laboratory_payload_for_runtime_alerts(
        patient,
        management_track=management_track,
        latest_assessment=latest_assessment,
    )
    alerts = [
        alert.to_dict()
        for alert in build_laboratory_alerts(
            runtime_payload.get("latest_values", {}),
            treatment_text=runtime_payload.get("treatment_text", ""),
            adt_context=runtime_payload.get("adt_context", ""),
        )
    ]
    latest_values = runtime_payload.get("latest_values", {})
    families = _family_payload(series_items)
    return {
        "available": bool(series_items),
        "state": state,
        "management_track": management_track or runtime_payload.get("management_track", ""),
        "series": series_items,
        "families": families,
        "active_alerts": alerts,
        "latest_values": latest_values,
        "coverage": {
            "series_count": len(series_items),
            "family_count": len(families),
            "has_hepatic_panel": any(item["key"] in {"ast", "alt", "bilirubin"} for item in series_items),
            "has_renal_panel": any(item["key"] in {"creatinine", "cystatin_c"} for item in series_items),
            "has_testosterone": any(item["key"] == "testosterone" for item in series_items),
        },
        "therapy_safety_checkpoints": [
            {
                "title": alert["title"],
                "severity": alert["severity"],
                "recommended_action": alert["recommended_action"],
                "guideline_reference": alert["guideline_reference"],
            }
            for alert in alerts[:6]
        ],
    }
