"""Treatment-course economic impact read models.

These helpers compare the patient treatment-course summary before and after a
V2 longitudinal write. They do not decide therapy, mutate source clinical
facts, create external orders, or train models.
"""
from __future__ import annotations

from typing import Any, Mapping

from prostanet.shared.utc_time import utc_now_iso


TREATMENT_ECONOMIC_CAPTURE_IMPACT_VERSION = "treatment_economic_capture_impact_v1"


def build_patient_treatment_economic_snapshot(patient_ref: str) -> dict[str, Any]:
    """Return a read-only current treatment/cost state for one patient."""
    try:
        import tracking_db

        summary = tracking_db.get_patient_treatment_course_summary(patient_ref)
    except Exception as exc:
        return _unavailable(patient_ref, f"summary_failed: {exc}")
    if not summary.get("success"):
        return _unavailable(patient_ref, summary.get("error") or "patient_not_found")

    current = dict(summary.get("current_course") or {})
    alert = dict(summary.get("dose_alert") or {})
    cost = dict(summary.get("cost_summary") or {})
    regimen_cost = dict(summary.get("regimen_cost_estimate") or {})
    available = bool(summary.get("available"))
    return {
        "available": available,
        "version": TREATMENT_ECONOMIC_CAPTURE_IMPACT_VERSION,
        "computed_at": utc_now_iso(),
        "patient_ref": str(summary.get("nss") or patient_ref or ""),
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "current_course": _course_summary(current),
        "dose_alert": _alert_summary(alert),
        "cost_summary": _cost_summary(cost),
        "regimen_cost_estimate": {
            "regimen_code": regimen_cost.get("regimen_code") or current.get("regimen_code") or "",
            "regimen_label": regimen_cost.get("regimen_label") or current.get("regimen_label") or "",
            "coverage_status": regimen_cost.get("coverage_status") or "",
            "medication_total_coverage_status": regimen_cost.get("medication_total_coverage_status") or "",
            "cost_scope": regimen_cost.get("cost_scope") or "",
            "priced_components": list(regimen_cost.get("priced_components") or []),
            "missing_components": list(regimen_cost.get("missing_components") or []),
            "unpriced_backbone_components": list(regimen_cost.get("unpriced_backbone_components") or []),
        },
        "profile_url": f"/patient_profile/{summary.get('nss') or patient_ref}?v=2",
        "current_course_url": f"/api/patients/{summary.get('nss') or patient_ref}/treatment-course/current",
        "value_registry_url": "/treatment-value-registry-v2",
    }


def build_treatment_economic_capture_impact(
    patient_ref: str,
    *,
    before_snapshot: Mapping[str, Any] | None = None,
    kind: str = "treatment_dose",
    append_result: Mapping[str, Any] | None = None,
    recompute_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare treatment economics before and after a course/dose write."""
    before = dict(before_snapshot or build_patient_treatment_economic_snapshot(patient_ref))
    after = build_patient_treatment_economic_snapshot(patient_ref)
    before_course = dict(before.get("current_course") or {})
    after_course = dict(after.get("current_course") or {})
    before_cost = dict(before.get("cost_summary") or {})
    after_cost = dict(after.get("cost_summary") or {})
    before_alert = dict(before.get("dose_alert") or {})
    after_alert = dict(after.get("dose_alert") or {})
    recompute = dict(recompute_result or {})
    local_delta = _int(after_course.get("local_dose_count")) - _int(before_course.get("local_dose_count"))
    global_delta = _int(after_course.get("global_dose_count")) - _int(before_course.get("global_dose_count"))
    arpi_cost_delta = _money(after_cost.get("estimated_total_spend_mxn")) - _money(before_cost.get("estimated_total_spend_mxn"))
    medication_cost_delta = _money(after_cost.get("estimated_total_medication_spend_mxn")) - _money(before_cost.get("estimated_total_medication_spend_mxn"))
    alert_changed = str(before_alert.get("severity") or "") != str(after_alert.get("severity") or "")
    regimen_changed = str(before_course.get("regimen_code") or "") != str(after_course.get("regimen_code") or "")
    refreshed_surfaces = [
        "patient_profile_v2_treatment_course",
        "patient_profile_v2_psa_treatment_bands",
        "treatment_value_registry_v2",
        "arpi_spend_analytics",
    ]
    if recompute.get("success"):
        refreshed_surfaces.extend(["decision_today", "patient_autodrive"])
    if recompute.get("arpi_response_windows"):
        refreshed_surfaces.append("arpi_response_windows")
    return {
        "available": bool(after.get("available")),
        "version": TREATMENT_ECONOMIC_CAPTURE_IMPACT_VERSION,
        "computed_at": utc_now_iso(),
        "patient_ref": str(patient_ref or ""),
        "kind_appended": str(kind or ""),
        "read_only_impact_model": True,
        "append_success": bool((append_result or {}).get("success")),
        "appended_id": (append_result or {}).get("dose_id") or (append_result or {}).get("appended_id"),
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "before": {
            "current_course": before_course,
            "dose_alert": before_alert,
            "cost_summary": before_cost,
        },
        "after": {
            "current_course": after_course,
            "dose_alert": after_alert,
            "cost_summary": after_cost,
        },
        "local_dose_delta": local_delta,
        "global_dose_delta": global_delta,
        "arpi_spend_delta_mxn": round(arpi_cost_delta, 2),
        "medication_spend_delta_mxn": round(medication_cost_delta, 2),
        "alert_changed": alert_changed,
        "warning_alert_now": after_alert.get("severity") == "warning",
        "critical_alert_now": after_alert.get("severity") == "critical",
        "regimen_changed": regimen_changed,
        "recompute_success": bool(recompute.get("success")),
        "decision_changed": bool(recompute.get("decision_changed")),
        "alerts_count": int(recompute.get("alerts_count") or 0),
        "arpi_response_windows": dict(recompute.get("arpi_response_windows") or {}),
        "refreshed_surfaces": refreshed_surfaces,
        "next_surfaces": {
            "profile_v2": after.get("profile_url") or f"/patient_profile/{patient_ref}?v=2",
            "current_course": after.get("current_course_url") or f"/api/patients/{patient_ref}/treatment-course/current",
            "value_registry_v2": after.get("value_registry_url") or "/treatment-value-registry-v2",
            "arpi_spend": "/api/analytics/arpi-spend",
        },
        "clinical_message": _impact_message(
            local_delta=local_delta,
            arpi_cost_delta=arpi_cost_delta,
            after_alert=after_alert,
            regimen_changed=regimen_changed,
        ),
    }


def _unavailable(patient_ref: str, error: str) -> dict[str, Any]:
    return {
        "available": False,
        "version": TREATMENT_ECONOMIC_CAPTURE_IMPACT_VERSION,
        "computed_at": utc_now_iso(),
        "patient_ref": str(patient_ref or ""),
        "error": str(error or "unavailable"),
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "current_course": {},
        "dose_alert": {},
        "cost_summary": {},
    }


def _course_summary(current: Mapping[str, Any]) -> dict[str, Any]:
    intensity = dict(current.get("intensity") or {})
    return {
        "treatment_history_id": current.get("treatment_history_id"),
        "line_of_therapy_number": current.get("line_of_therapy_number"),
        "line_of_therapy_context": current.get("line_of_therapy_context") or "",
        "regimen_code": current.get("regimen_code") or "",
        "regimen_label": current.get("regimen_label") or "",
        "intensity": intensity.get("intensity") or "",
        "intensity_label": intensity.get("intensity_label") or "",
        "start_date": current.get("start_date") or "",
        "doses_received_before_unit": _int(current.get("doses_received_before_unit")),
        "local_dose_count": _int(current.get("local_dose_count")),
        "global_dose_count": _int(current.get("global_dose_count")),
        "latest_local_dose_date": current.get("latest_local_dose_date") or "",
        "unit_name": current.get("unit_name") or "",
        "referral_target": current.get("referral_target") or "",
    }


def _alert_summary(alert: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "severity": alert.get("severity") or "none",
        "code": alert.get("code") or "",
        "title": alert.get("title") or "Sin alerta",
        "message": alert.get("message") or "",
        "recommended_action": alert.get("recommended_action") or "",
        "local_dose_count": _int(alert.get("local_dose_count")),
    }


def _cost_summary(cost: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "estimated_total_spend_mxn": round(_money(cost.get("estimated_total_spend_mxn")), 2),
        "estimated_total_medication_spend_mxn": round(_money(cost.get("estimated_total_medication_spend_mxn")), 2),
        "estimated_cost_per_dose_mxn": _nullable_money(cost.get("estimated_cost_per_dose_mxn")),
        "estimated_arpi_cost_per_dose_mxn": _nullable_money(cost.get("estimated_arpi_cost_per_dose_mxn")),
        "priced_doses": _int(cost.get("priced_doses")),
        "dose_count": _int(cost.get("dose_count")),
        "price_coverage_status": cost.get("price_coverage_status") or "",
        "medication_total_coverage_status": cost.get("medication_total_coverage_status") or "",
        "cost_confidence": cost.get("cost_confidence") or "",
        "missing_arpi_components": list(cost.get("missing_arpi_components") or []),
        "missing_non_arpi_components": list(cost.get("missing_non_arpi_components") or []),
        "unpriced_backbone_components": list(cost.get("unpriced_backbone_components") or []),
        "stale_price_components": list(cost.get("stale_price_components") or []),
        "cost_scope": cost.get("cost_scope") or "",
    }


def _impact_message(
    *,
    local_delta: int,
    arpi_cost_delta: float,
    after_alert: Mapping[str, Any],
    regimen_changed: bool,
) -> str:
    severity = str(after_alert.get("severity") or "none")
    if severity == "critical":
        return after_alert.get("message") or "Alerta critica de dosis local activa."
    if severity == "warning":
        return after_alert.get("message") or "Alerta temprana de referencia activa."
    if regimen_changed:
        return "Linea terapeutica actualizada; Perfil V2 y bandas APE-tratamiento deben recalcularse."
    if local_delta > 0:
        return f"Dosis local registrada; gasto ARPI estimado incremento ${arpi_cost_delta:.2f} MXN."
    return "Sin cambio economico-terapeutico relevante detectado."


def _int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _money(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _nullable_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return round(_money(value), 2)


__all__ = [
    "TREATMENT_ECONOMIC_CAPTURE_IMPACT_VERSION",
    "build_patient_treatment_economic_snapshot",
    "build_treatment_economic_capture_impact",
]
