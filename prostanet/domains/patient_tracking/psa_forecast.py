from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.shared.phoenix import evaluate_phoenix

ADVANCED_FORECAST_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

FORECAST_HORIZONS = (3, 6, 12)
_MIN_POINTS = 3
_MIN_SPAN_DAYS = 42

# EPIC 31.E (Explore EXP-7 MOD) — permitir short-line forecast con confidence
# baja en lugar de descartarlo completo como insufficient_data. Líneas con
# 2 puntos (≥21d span) son comunes en early-line management; el clínico se
# beneficia de overlay tentativo aunque NO sea estadísticamente robusto.
_LOW_CONF_MIN_POINTS = 2
_LOW_CONF_MIN_SPAN_DAYS = 21
_LINE_STABLE_DAYS = 84
_OUTLIER_Z = 2.5
_EPSILON = 0.01


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _months_between(start: date | None, end: date | None) -> float | None:
    if not start or not end:
        return None
    return round((end - start).days / 30.44, 2)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _current_line_context(patient: dict[str, Any], monitoring: dict[str, Any]) -> dict[str, Any]:
    segments = list(monitoring.get("line_segments") or [])
    if segments:
        return dict(segments[-1])

    treatments = list(patient.get("treatments") or [])
    latest_treatment = treatments[-1] if treatments else {}
    return {
        "start_date": latest_treatment.get("start_date") or "",
        "end_date": latest_treatment.get("end_date") or "",
        "line_of_therapy_number": latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy") or 1,
        "line_of_therapy_context": latest_treatment.get("line_of_therapy_context") or "",
        "drug_scheme": latest_treatment.get("drug_scheme") or latest_treatment.get("current_treatment") or "",
        "label": regimen_label(latest_treatment.get("drug_scheme") or latest_treatment.get("current_treatment")) or "Línea actual",
        "baseline_psa": (monitoring.get("metrics") or {}).get("current_psa"),
        "nadir_psa": (monitoring.get("metrics") or {}).get("nadir_psa"),
        "point_count": len(monitoring.get("points") or []),
    }


def _points_for_current_line(monitoring: dict[str, Any], line_context: dict[str, Any]) -> list[dict[str, Any]]:
    points = list(monitoring.get("points") or [])
    if not points:
        return []
    start_date = _parse_date(line_context.get("start_date"))
    end_date = _parse_date(line_context.get("end_date"))
    filtered: list[dict[str, Any]] = []
    for point in points:
        point_date = _parse_date(point.get("date"))
        if not point_date:
            continue
        if start_date and point_date < start_date:
            continue
        if end_date and point_date > end_date:
            continue
        psa = _safe_float(point.get("psa"))
        if psa is None or psa < 0:
            continue
        filtered.append({"date": point_date.isoformat(), "psa": psa})
    return filtered


def _prepare_regression_points(points: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    ordered = sorted(points, key=lambda item: item.get("date") or "")
    base_date = _parse_date(ordered[0]["date"])
    x_values = []
    y_values = []
    kept = []
    for point in ordered:
        point_date = _parse_date(point.get("date"))
        psa = _safe_float(point.get("psa"))
        if not base_date or not point_date or psa is None:
            continue
        months = (point_date - base_date).days / 30.44
        x_values.append(months)
        y_values.append(math.log(max(psa, _EPSILON)))
        kept.append(point)
    return np.asarray(x_values, dtype=float), np.asarray(y_values, dtype=float), kept


def _fit_log_psa_model(points: list[dict[str, Any]]) -> dict[str, Any]:
    x, y, kept_points = _prepare_regression_points(points)
    # EPIC 31.E (Explore EXP-7 MOD) — permitir 2-punto fit con flag tentative
    if len(kept_points) < _LOW_CONF_MIN_POINTS:
        return {"status": "insufficient_data", "reason": "Menos de 2 puntos PSA válidos."}
    if len(kept_points) < _MIN_POINTS:
        # 2-point lineal sin covarianza (no se puede estimar uncertainty)
        try:
            slope, intercept = np.polyfit(x, y, 1)
        except Exception:
            return {"status": "insufficient_data", "reason": "Ajuste 2-punto falló."}
        return {
            "status": "ok",
            "slope": float(slope),
            "intercept": float(intercept),
            "covariance": np.zeros((2, 2)),  # zero placeholder; widen UI intervals
            "r2": None,  # No es válido con 2 puntos
            "x": x,
            "y": y,
            "kept_points": kept_points,
            "outlier_count": 0,
            "tentative_fit": True,  # flag para UI
        }

    weights = np.linspace(1.0, 2.0, len(x))
    try:
        coeffs, covariance = np.polyfit(x, y, 1, w=weights, cov=True)
    except Exception:
        return {"status": "insufficient_data", "reason": "No fue posible ajustar el modelo longitudinal de PSA."}

    slope = float(coeffs[0])
    intercept = float(coeffs[1])
    y_hat = slope * x + intercept
    residuals = y - y_hat
    mad = float(np.median(np.abs(residuals - np.median(residuals)))) if len(residuals) else 0.0

    outlier_indices: list[int] = []
    if mad > 1e-6 and len(x) >= 4:
        for idx, residual in enumerate(residuals):
            robust_z = abs(residual - np.median(residuals)) / (1.4826 * mad)
            if robust_z > _OUTLIER_Z:
                outlier_indices.append(idx)

    if outlier_indices and len(x) - len(outlier_indices) >= _MIN_POINTS:
        mask = np.ones(len(x), dtype=bool)
        mask[outlier_indices] = False
        x = x[mask]
        y = y[mask]
        kept_points = [point for idx, point in enumerate(kept_points) if idx not in outlier_indices]
        weights = np.linspace(1.0, 2.0, len(x))
        coeffs, covariance = np.polyfit(x, y, 1, w=weights, cov=True)
        slope = float(coeffs[0])
        intercept = float(coeffs[1])
        y_hat = slope * x + intercept
        residuals = y - y_hat

    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 1.0
    sigma = math.sqrt(max(ss_res / max(len(x) - 2, 1), 0.0))

    return {
        "status": "ok",
        "points": kept_points,
        "x": x,
        "y": y,
        "slope": slope,
        "intercept": intercept,
        "covariance": covariance,
        "sigma": sigma,
        "r2": max(min(r2, 1.0), -1.0),
        "outlier_count": len(outlier_indices),
    }


def _predict_log_point(model: dict[str, Any], x_months: float) -> dict[str, float]:
    vector = np.asarray([x_months, 1.0], dtype=float)
    covariance = np.asarray(model.get("covariance"))
    sigma = float(model.get("sigma") or 0.0)
    y_hat = float(model["slope"] * x_months + model["intercept"])
    mean_var = float(vector @ covariance @ vector.T) if covariance.size else 0.0
    pred_var = max(mean_var + sigma**2, 1e-9)
    pred_sd = math.sqrt(pred_var)
    lower = math.exp(y_hat - 1.96 * pred_sd)
    upper = math.exp(y_hat + 1.96 * pred_sd)
    expected = math.exp(y_hat)
    return {
        "expected_psa": expected,
        "lower_psa": lower,
        "upper_psa": upper,
        "interval_width": upper - lower,
    }


def _line_reliability(
    *,
    current_points: list[dict[str, Any]],
    line_context: dict[str, Any],
    model: dict[str, Any],
) -> dict[str, Any]:
    first_date = _parse_date(current_points[0]["date"]) if current_points else None
    last_date = _parse_date(current_points[-1]["date"]) if current_points else None
    span_days = (last_date - first_date).days if first_date and last_date else 0
    line_start = _parse_date(line_context.get("start_date")) or first_date
    line_age_days = (last_date - line_start).days if line_start and last_date else 0

    minimum_data_passed = len(current_points) >= _MIN_POINTS and span_days >= _MIN_SPAN_DAYS
    # EPIC 31.E (Explore EXP-7 MOD) — short-line tentative tier
    short_line_passed = (
        len(current_points) >= _LOW_CONF_MIN_POINTS
        and span_days >= _LOW_CONF_MIN_SPAN_DAYS
    )
    line_stability_passed = line_age_days >= _LINE_STABLE_DAYS
    model_fit_quality = _round_or_none(max(float(model.get("r2") or 0.0), 0.0), 3)
    outlier_burden = int(model.get("outlier_count") or 0)

    prediction_interval_width = None
    if model.get("status") == "ok" and current_points:
        x_values = model.get("x")
        last_x = float(x_values[-1]) if x_values is not None and len(x_values) else 0.0
        next_point = _predict_log_point(model, last_x + 6.0)
        prediction_interval_width = _round_or_none(next_point["interval_width"], 2)

    reasons = []
    if not minimum_data_passed and short_line_passed:
        reasons.append(
            "Línea con 2 puntos PSA: forecast tentativo de baja confianza "
            "(EPIC 31.E EXP-7). Recapturar PSA para mejorar precision."
        )
    elif not minimum_data_passed and not short_line_passed:
        reasons.append("Menos de 2 puntos válidos o ventana temporal <21 días dentro de la línea actual.")
    if minimum_data_passed and not line_stability_passed:
        reasons.append("La línea terapéutica actual es demasiado reciente para extrapolar con seguridad.")
    if model_fit_quality is not None and model_fit_quality < 0.4:
        reasons.append("La tendencia longitudinal de PSA es poco estable para una extrapolación numérica robusta.")
    if outlier_burden:
        reasons.append("Se detectaron valores PSA atípicos que ensanchan la incertidumbre del modelo.")

    # EPIC 31.E (EXP-7) — tier "tentative" para líneas cortas
    if not short_line_passed or model.get("status") != "ok":
        confidence = "insufficient_data"
    elif not minimum_data_passed:
        # 2-3 puntos OK + span 21+ días pero menor a _MIN_SPAN_DAYS=42
        confidence = "tentative"
    elif not line_stability_passed or model_fit_quality is not None and model_fit_quality < 0.4:
        confidence = "low"
    elif model_fit_quality is not None and model_fit_quality >= 0.75 and outlier_burden == 0 and line_age_days >= 120:
        confidence = "high"
    else:
        confidence = "medium"

    return {
        "minimum_data_passed": minimum_data_passed,
        "line_stability_passed": line_stability_passed,
        "model_fit_quality": model_fit_quality,
        "outlier_burden": outlier_burden,
        "prediction_interval_width": prediction_interval_width,
        "confidence_label": confidence,
        "reasons": reasons,
        "line_age_days": line_age_days,
        "point_span_days": span_days,
    }


def _projected_psadt_months(slope_per_month: float) -> float | None:
    if slope_per_month <= 1e-6:
        return None
    return round(math.log(2) / slope_per_month, 1)


def _estimate_psadt_crossings(model: dict[str, Any], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    thresholds = (10, 6, 3)
    results: list[dict[str, Any]] = []
    current_psadt = _projected_psadt_months(float(model.get("slope") or 0.0))
    last_date = _parse_date(points[-1]["date"]) if points else None
    x_values = model.get("x")
    y_values = model.get("y")
    x = list(x_values) if x_values is not None else []
    y = list(y_values) if y_values is not None else []
    if not last_date or len(x) < 3:
        return results

    acceleration = None
    if len(x) >= 5:
        split = len(x) // 2
        early_x = np.asarray(x[: split + 1], dtype=float)
        early_y = np.asarray(y[: split + 1], dtype=float)
        late_x = np.asarray(x[split:], dtype=float)
        late_y = np.asarray(y[split:], dtype=float)
        if len(early_x) >= 2 and len(late_x) >= 2:
            early_slope, _ = np.polyfit(early_x, early_y, 1)
            late_slope, _ = np.polyfit(late_x, late_y, 1)
            delta_months = max(float(late_x[-1] - early_x[-1]), 0.5)
            if late_slope > early_slope > 0:
                acceleration = (late_slope - early_slope) / delta_months

    for threshold in thresholds:
        slope_threshold = math.log(2) / threshold
        entry = {
            "threshold_key": f"psadt_lt_{threshold}",
            "label": f"PSADT < {threshold} meses",
            "status": "not_reached",
            "estimated_crossing_date": "",
            "months_until_crossing": None,
            "projected_psadt_months": current_psadt,
        }
        if current_psadt is not None and current_psadt <= threshold:
            entry["status"] = "crossed_now"
            entry["estimated_crossing_date"] = last_date.isoformat()
            entry["months_until_crossing"] = 0.0
        elif acceleration and acceleration > 0:
            current_slope = float(model.get("slope") or 0.0)
            if slope_threshold > current_slope:
                months_until = (slope_threshold - current_slope) / acceleration
                if 0 < months_until <= 12:
                    crossing_date = last_date + timedelta(days=int(months_until * 30.44))
                    entry["status"] = "forecast_crossing"
                    entry["estimated_crossing_date"] = crossing_date.isoformat()
                    entry["months_until_crossing"] = _round_or_none(months_until, 1)
        results.append(entry)
    return results


def _estimate_absolute_thresholds(
    line_context: dict[str, Any],
    forecast_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    thresholds: list[dict[str, Any]] = []
    nadir = _safe_float(line_context.get("nadir_psa"))
    if nadir is None or nadir <= 0:
        return thresholds

    # EPIC 1 FIX-FORECAST-1: delegar umbral Phoenix al helper canónico.
    phoenix_eval = evaluate_phoenix({"psa_nadir": nadir, "psa_current": nadir})
    nadir_plus_2 = phoenix_eval.threshold if phoenix_eval.threshold is not None else nadir + 2.0
    absolute_thresholds = [
        {
            "threshold_key": "nadir_plus_2",
            "label": "Nadir + 2 ng/mL",
            "target_psa": nadir_plus_2,
        },
        {
            "threshold_key": "pcwg3_psa_progression",
            "label": "Aumento ≥25% y ≥2 ng/mL sobre nadir",
            "target_psa": max(nadir * 1.25, nadir_plus_2),
        },
    ]
    for threshold in absolute_thresholds:
        entry = {
            **threshold,
            "status": "not_reached",
            "estimated_crossing_date": "",
            "months_until_crossing": None,
        }
        for point in forecast_curve:
            if (point.get("expected_psa") or 0.0) >= threshold["target_psa"]:
                entry["status"] = "forecast_crossing"
                entry["estimated_crossing_date"] = point["date"]
                entry["months_until_crossing"] = point.get("horizon_months")
                break
        thresholds.append(entry)
    return thresholds


def _build_predictive_alerts(
    reliability: dict[str, Any],
    psadt_thresholds: list[dict[str, Any]],
    absolute_thresholds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    confidence = reliability.get("confidence_label")
    if confidence not in {"high", "medium", "low"}:
        return alerts

    for item in psadt_thresholds:
        if item.get("status") in {"crossed_now", "forecast_crossing"}:
            threshold_key = str(item.get("threshold_key") or "")
            months_until = _safe_float(item.get("months_until_crossing"))
            severity = "warning"
            if threshold_key.endswith("_3"):
                severity = "critical"
            elif threshold_key.endswith("_6"):
                severity = "warning"
            if months_until is None or months_until <= 6:
                alerts.append(
                    {
                        "severity": severity,
                        "title": item.get("label"),
                        "message": (
                            f"La tendencia actual sugiere {item.get('label', '').lower()} "
                            f"{'ya presente' if months_until == 0 else f'en ~{months_until:.1f} meses'}."
                        ),
                        "threshold_key": threshold_key,
                    }
                )

    for item in absolute_thresholds:
        months_until = _safe_float(item.get("months_until_crossing"))
        if item.get("status") == "forecast_crossing" and months_until is not None and months_until <= 6:
            alerts.append(
                {
                    "severity": "warning",
                    "title": item.get("label"),
                    "message": f"Si la tendencia actual persiste, alcanzará {item.get('label')} en ~{months_until:.1f} meses.",
                    "threshold_key": item.get("threshold_key"),
                }
            )
    return alerts[:5]


def build_psa_forecast(
    patient: dict[str, Any],
    *,
    state: str = "",
) -> dict[str, Any]:
    resolved_state = str(state or patient.get("reconciled_state") or (patient.get("latest_assessment") or {}).get("state") or "")
    if resolved_state not in ADVANCED_FORECAST_STATES:
        return {
            "status": "not_applicable",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "reliability": {
                "minimum_data_passed": False,
                "line_stability_passed": False,
                "model_fit_quality": None,
                "outlier_burden": 0,
                "prediction_interval_width": None,
                "confidence_label": "not_applicable",
                "reasons": ["La predicción prospectiva PSA v1 solo aplica a enfermedad avanzada."],
            },
        }

    monitoring = build_psa_by_treatment_line(patient)
    points = list(monitoring.get("points") or [])
    if not points:
        return {
            "status": "insufficient_data",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "reliability": {
                "minimum_data_passed": False,
                "line_stability_passed": False,
                "model_fit_quality": None,
                "outlier_burden": 0,
                "prediction_interval_width": None,
                "confidence_label": "insufficient_data",
                "reasons": ["No hay datos PSA longitudinales suficientes para construir una proyección."],
            },
        }

    line_context = _current_line_context(patient, monitoring)
    current_points = _points_for_current_line(monitoring, line_context)
    if not current_points:
        current_points = points

    model = _fit_log_psa_model(current_points)
    reliability = _line_reliability(current_points=current_points, line_context=line_context, model=model)
    if model.get("status") != "ok":
        reliability["confidence_label"] = "insufficient_data"
        reliability["reasons"] = reliability.get("reasons") or [str(model.get("reason") or "No fue posible ajustar el forecast de PSA.")]
        return {
            "status": "insufficient_data",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "current_line_label": line_context.get("label") or "Línea actual",
            "current_regimen_label": regimen_label(line_context.get("drug_scheme")) or line_context.get("drug_scheme") or "",
            "line_of_therapy_number": line_context.get("line_of_therapy_number"),
            "reliability": reliability,
        }

    prepared_points = list(model.get("points") or current_points)
    first_date = _parse_date(prepared_points[0]["date"]) if prepared_points else None
    last_date = _parse_date(prepared_points[-1]["date"]) if prepared_points else None
    x_values = model.get("x")
    last_x = float(x_values[-1]) if x_values is not None and len(x_values) else 0.0

    forecast_points = []
    forecast_curve = []
    for horizon in FORECAST_HORIZONS:
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_points.append(
            {
                "horizon_months": horizon,
                "date": target_date.isoformat() if target_date else "",
                "expected_psa": _round_or_none(prediction["expected_psa"], 2),
                "lower_psa": _round_or_none(prediction["lower_psa"], 2),
                "upper_psa": _round_or_none(prediction["upper_psa"], 2),
                "interval_width": _round_or_none(prediction["interval_width"], 2),
            }
        )
    for horizon in range(1, 13):
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_curve.append(
            {
                "horizon_months": horizon,
                "date": target_date.isoformat() if target_date else "",
                "expected_psa": _round_or_none(prediction["expected_psa"], 2),
                "lower_psa": _round_or_none(prediction["lower_psa"], 2),
                "upper_psa": _round_or_none(prediction["upper_psa"], 2),
            }
        )

    psadt_thresholds = _estimate_psadt_crossings(model, prepared_points)
    absolute_thresholds = _estimate_absolute_thresholds(line_context, forecast_curve)
    threshold_events = psadt_thresholds + absolute_thresholds
    predictive_alerts = _build_predictive_alerts(reliability, psadt_thresholds, absolute_thresholds)

    projected_psadt = _projected_psadt_months(float(model.get("slope") or 0.0))
    status = "ready"
    show = True
    if reliability["confidence_label"] == "low":
        status = "low_confidence"
    elif reliability["confidence_label"] == "insufficient_data":
        status = "insufficient_data"
        show = False

    return {
        "status": status,
        "show": show,
        "state": resolved_state,
        "current_line_label": line_context.get("label") or "Línea actual",
        "current_regimen_label": regimen_label(line_context.get("drug_scheme")) or line_context.get("drug_scheme") or "",
        "line_of_therapy_number": line_context.get("line_of_therapy_number"),
        "line_of_therapy_context": line_context.get("line_of_therapy_context") or "",
        "current_line_start_date": line_context.get("start_date") or "",
        "last_observed_date": last_date.isoformat() if last_date else "",
        "current_psa": _round_or_none(_safe_float(prepared_points[-1]["psa"]) if prepared_points else None, 2),
        "nadir_psa": _round_or_none(min(_safe_float(point.get("psa")) or 0.0 for point in prepared_points) if prepared_points else None, 2),
        "forecast_points": forecast_points,
        "forecast_curve": forecast_curve,
        "threshold_events": threshold_events,
        "predictive_alerts": predictive_alerts,
        "projected_psadt_months": projected_psadt,
        "trend_summary": (
            "Si la tendencia actual persiste, el PSA continuará en ascenso con señal longitudinal consistente."
            if float(model.get("slope") or 0.0) > 0
            else "La tendencia actual sugiere estabilidad o descenso de PSA dentro de la línea actual."
        ),
        "reliability": reliability,
    }


def _build_forecast_for_segment_points(
    segment_points: list[dict[str, Any]],
    *,
    line_label: str = "",
    line_number: Any = None,
    line_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Faubot 2026-04-25 (LXVIII) — Auditoría #64A.

    Construye forecast log-linear PSA para UN segment de treatment line
    específico (no para el current line global). Reutiliza la misma lógica
    de `build_psa_forecast` pero parametrizada por segment.

    Razón clínica: cada línea terapéutica tiene su propia kinetics PSA
    (response, stable, progression). Forecast global "current line" oculta
    la trayectoria de líneas previas. Per-line forecast permite:
      - Comparar trayectorias entre líneas (¿esta línea está respondiendo
        más rápido/lento que la previa?)
      - Detectar progresión post-nadir POR LÍNEA antes de que el clínico
        cambie régimen
      - Auditar retrospectivamente "¿este cambio de línea fue justificado?"

    Returns:
        Dict con misma estructura que `build_psa_forecast` para una línea:
            status, show, forecast_points (3/6/12m), forecast_curve (1-12m),
            current_psa, nadir_psa, line_label, line_of_therapy_number.
        Si insufficient_data, status="insufficient_data" con reasons.
    """
    if not segment_points or len(segment_points) < _MIN_POINTS:
        return {
            "status": "insufficient_data",
            "show": False,
            "line_of_therapy_number": line_number,
            "line_label": line_label,
            "forecast_points": [],
            "forecast_curve": [],
            "reasons": ["Puntos PSA insuficientes en esta línea para forecast."],
        }

    # Filtrar a structure {date, psa} esperada por _fit_log_psa_model
    filtered_points: list[dict[str, Any]] = []
    for p in segment_points:
        psa = _safe_float(p.get("psa"))
        date_iso = p.get("date")
        if psa is None or not date_iso:
            continue
        filtered_points.append({"date": date_iso, "psa": psa})

    if len(filtered_points) < _MIN_POINTS:
        return {
            "status": "insufficient_data",
            "show": False,
            "line_of_therapy_number": line_number,
            "line_label": line_label,
            "forecast_points": [],
            "forecast_curve": [],
            "reasons": ["Puntos PSA válidos insuficientes en esta línea."],
        }

    model = _fit_log_psa_model(filtered_points)
    if model.get("status") != "ok":
        return {
            "status": "insufficient_data",
            "show": False,
            "line_of_therapy_number": line_number,
            "line_label": line_label,
            "forecast_points": [],
            "forecast_curve": [],
            "reasons": [str(model.get("reason") or "Modelo no ajustable.")],
        }

    prepared = list(model.get("points") or filtered_points)
    last_date = _parse_date(prepared[-1]["date"]) if prepared else None
    x_values = model.get("x")
    last_x = float(x_values[-1]) if x_values is not None and len(x_values) else 0.0

    forecast_points = []
    for horizon in FORECAST_HORIZONS:
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_points.append({
            "horizon_months": horizon,
            "date": target_date.isoformat() if target_date else "",
            "expected_psa": _round_or_none(prediction["expected_psa"], 2),
            "lower_psa": _round_or_none(prediction["lower_psa"], 2),
            "upper_psa": _round_or_none(prediction["upper_psa"], 2),
            "interval_width": _round_or_none(prediction["interval_width"], 2),
        })

    forecast_curve = []
    for horizon in range(1, 13):
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_curve.append({
            "horizon_months": horizon,
            "date": target_date.isoformat() if target_date else "",
            "expected_psa": _round_or_none(prediction["expected_psa"], 2),
            "lower_psa": _round_or_none(prediction["lower_psa"], 2),
            "upper_psa": _round_or_none(prediction["upper_psa"], 2),
        })

    psa_values = [_safe_float(p.get("psa")) or 0.0 for p in prepared]
    return {
        "status": "ready",
        "show": True,
        "line_of_therapy_number": line_number,
        "line_label": line_label,
        "line_of_therapy_context": (line_context or {}).get("line_of_therapy_context", ""),
        "drug_scheme": (line_context or {}).get("drug_scheme", ""),
        "forecast_points": forecast_points,
        "forecast_curve": forecast_curve,
        "last_observed_date": last_date.isoformat() if last_date else "",
        "current_psa": _round_or_none(psa_values[-1] if psa_values else None, 2),
        "nadir_psa": _round_or_none(min(psa_values) if psa_values else None, 2),
        "slope": _round_or_none(model.get("slope"), 4),
        "projected_psadt_months": _projected_psadt_months(float(model.get("slope") or 0.0)),
        "point_count": len(prepared),
    }


# Faubot 2026-04-25 (LXVIII) — Auditoría #64A
# Cohort reference PSA trajectories by (state, regimen_class).
# Basado en literatura pivotal: median time-to-nadir + median nadir % vs baseline
# de ensayos clínicos publicados. Estos valores son "best estimate" para
# comparación visual; NO son cohort data en vivo (eso requiere infraestructura
# adicional de población). Con cohort data real, este dict se reemplaza.
#
# Estructura: {state: {regimen_class: {nadir_pct: float, time_to_nadir_m: int,
#                                      duration_response_m: int, median_label: str}}}
# nadir_pct: % del baseline PSA esperado en nadir (e.g., 0.05 = 5% del baseline)
# time_to_nadir_m: meses esperados a nadir
# duration_response_m: meses esperados de respuesta sostenida (post-nadir hasta progresión)
#
# EPIC 28.12 (GodiBot G50 MOD) — DISCLAIMER:
# Los valores de nadir_pct son APROXIMACIONES derivadas de proporciones de
# pacientes que alcanzan PSA<0.2 ng/mL en los trials pivotales, NO de
# medianas absolutas publicadas. Por ejemplo:
#   - ARASENS PMID 35179323: 70% triplete vs 50% doublete alcanzan PSA<0.2
#   - SPARTAN/PROSPER/ARAMIS: 33-40% sin describir nadir fraccional
# Estos valores sirven como REFERENCIA DE OVERLAY para el PSA Compass,
# no como predicción individual. Cada entrada incluye `data_quality_tag`
# para que la UI muestre disclaimer apropiado.
COHORT_PSA_REFERENCES: dict[str, dict[str, dict[str, Any]]] = {
    "mcspc_high_volume_sync": {
        "ADT": {"nadir_pct": 0.10, "time_to_nadir_m": 6, "duration_response_m": 12,
                "median_label": "Mediana ADT mHSPC alto volumen (CHAARTED control arm)",
                "data_quality_tag": "approximate_no_published_median",
                "evidence_pmid": ["26244877"],
                "disclaimer": "Aproximación de control arm CHAARTED; nadir fraccional no reportado en mediana absoluta"},
        "ADT_DOCETAXEL": {"nadir_pct": 0.05, "time_to_nadir_m": 5, "duration_response_m": 18,
                          "median_label": "Mediana ADT+Docetaxel mHSPC alto volumen (CHAARTED)",
                          "data_quality_tag": "approximate_no_published_median",
                          "evidence_pmid": ["26244877"],
                          "disclaimer": "Derivado de % PSA<0.2 alcanzado en trial, no mediana absoluta"},
        "ADT_ARPI": {"nadir_pct": 0.04, "time_to_nadir_m": 5, "duration_response_m": 24,
                     "median_label": "Mediana ADT+ARPI mHSPC (LATITUDE/ENZAMET/ARCHES)",
                     "data_quality_tag": "approximate_no_published_median",
                     "evidence_pmid": ["28578607", "31157963", "31157964"],
                     "disclaimer": "% PSA<0.2 ~84-91% en LATITUDE/ENZAMET; nadir fraccional aproximado"},
        "ADT_TRIPLET": {"nadir_pct": 0.02, "time_to_nadir_m": 4, "duration_response_m": 30,
                        "median_label": "Mediana ADT+Docetaxel+ARPI triplete (PEACE-1/ARASENS)",
                        "data_quality_tag": "approximate_no_published_median",
                        "evidence_pmid": ["35179323", "35405085"],
                        "disclaimer": "Derivado de % PSA<0.2 en trial, no mediana publicada"},
    },
    "mcspc_high_volume_metachronous": {
        "ADT": {"nadir_pct": 0.10, "time_to_nadir_m": 6, "duration_response_m": 14,
                "median_label": "Mediana ADT mHSPC metacrónico",
                "data_quality_tag": "approximate_no_published_median",
                "evidence_pmid": ["26244877"],
                "disclaimer": "Aproximación derivada de cohortes metacrónicas; no mediana publicada específica"},
        "ADT_DOCETAXEL": {"nadir_pct": 0.06, "time_to_nadir_m": 5, "duration_response_m": 20,
                          "median_label": "Mediana ADT+Docetaxel mHSPC metacrónico",
                          "data_quality_tag": "approximate_no_published_median",
                          "evidence_pmid": ["26244877"],
                          "disclaimer": "Estimado por subanálisis CHAARTED; no mediana metacrónica publicada"},
        "ADT_ARPI": {"nadir_pct": 0.04, "time_to_nadir_m": 5, "duration_response_m": 26,
                     "median_label": "Mediana ADT+ARPI mHSPC metacrónico",
                     "data_quality_tag": "approximate_no_published_median",
                     "evidence_pmid": ["28578607", "31157963"],
                     "disclaimer": "Aproximación basada en subgrupos metacrónicos LATITUDE/ENZAMET"},
    },
    "m0_crpc": {
        "ADT_ARPI": {"nadir_pct": 0.30, "time_to_nadir_m": 4, "duration_response_m": 24,
                     "median_label": "Mediana ARPI m0CRPC (SPARTAN/PROSPER/ARAMIS)",
                     "data_quality_tag": "approximate_no_published_median",
                     "evidence_pmid": ["29420164", "29420827", "30575667"],
                     "disclaimer": "PSA<0.2 ~33-40% en trials; nadir fraccional no reportado"},
        "ADT": {"nadir_pct": 0.80, "time_to_nadir_m": 3, "duration_response_m": 8,
                "median_label": "Mediana ADT solo m0CRPC (control arm)",
                "data_quality_tag": "approximate_no_published_median",
                "evidence_pmid": ["29420164"],
                "disclaimer": "Control arm SPARTAN/PROSPER/ARAMIS; respuesta limitada esperada por castración-resistencia"},
    },
    "m1_crpc": {
        "DOCETAXEL": {"nadir_pct": 0.45, "time_to_nadir_m": 4, "duration_response_m": 9,
                      "median_label": "Mediana Docetaxel mCRPC primera línea (TAX-327)",
                      "data_quality_tag": "approximate_no_published_median",
                      "evidence_pmid": ["15470213"],
                      "disclaimer": "TAX-327 reportó ≥50% PSA decline en ~45%; nadir fraccional aproximado"},
        "ARPI": {"nadir_pct": 0.40, "time_to_nadir_m": 4, "duration_response_m": 12,
                 "median_label": "Mediana ARPI mCRPC primera línea (PREVAIL/COU-AA-302)",
                 "data_quality_tag": "approximate_no_published_median",
                 "evidence_pmid": ["24881730", "23228172"],
                 "disclaimer": "PSA decline ≥50% en 78% PREVAIL / 62% COU-AA-302; nadir aproximado"},
        "PARP": {"nadir_pct": 0.35, "time_to_nadir_m": 5, "duration_response_m": 9,
                 "median_label": "Mediana PARP-i mCRPC HRR+ (PROfound)",
                 "data_quality_tag": "approximate_no_published_median",
                 "evidence_pmid": ["32343890"],
                 "disclaimer": "PROfound reportó PSA decline ≥50% en ~43% BRCA+; nadir aproximado"},
        "LU177": {"nadir_pct": 0.30, "time_to_nadir_m": 5, "duration_response_m": 7,
                  "median_label": "Mediana 177Lu-PSMA-617 mCRPC (VISION)",
                  "data_quality_tag": "approximate_no_published_median",
                  "evidence_pmid": ["34161051"],
                  "disclaimer": "VISION reportó PSA decline ≥50% en 46%; nadir fraccional aproximado"},
        # EPIC 30.5 (GodiBot G70 HIGH) — cohort references para los 4 regimens
        # m1_crpc añadidos en EPIC 29.6 G58. Pre-EPIC30, paciente bajo Ra-223
        # o pembrolizumab veía "Sin curva de referencia poblacional documentada"
        # en la torre de vigilancia — sin contexto pivotal de PSA esperada.
        "CABAZITAXEL": {"nadir_pct": 0.55, "time_to_nadir_m": 3, "duration_response_m": 7,
                        "median_label": "Mediana Cabazitaxel mCRPC post-docetaxel (CARD)",
                        "data_quality_tag": "approximate_no_published_median",
                        "evidence_pmid": ["31566937"],
                        "disclaimer": "CARD reportó PSA50 ~36%; nadir fraccional aproximado en cohorte post-ARSI"},
        "RA223": {"nadir_pct": 1.00, "time_to_nadir_m": 0, "duration_response_m": 12,
                  "median_label": "Ra-223 mCRPC sintomático óseo (ALSYMPCA)",
                  "data_quality_tag": "not_psa_endpoint_trial",
                  "evidence_pmid": ["23863050"],
                  "disclaimer": "Ra-223 NO modula PSA significativamente (target óseo). PSA decline NO es endpoint primario. Monitorizar AlkPhos + dolor en lugar de PSA. Curva nadir_pct=1.0 indica que no se espera reducción APE."},
        "PEMBROLIZUMAB": {"nadir_pct": 0.75, "time_to_nadir_m": 6, "duration_response_m": 9,
                          "median_label": "Pembrolizumab mCRPC MSI-H/dMMR (KEYNOTE-158)",
                          "data_quality_tag": "approximate_no_published_median_rare_responders",
                          "evidence_pmid": ["31682550"],
                          "disclaimer": "PSA50 ~9% en MSI-H mCRPC; respuestas dramáticas en minoría. NO esperar pattern decline poblacional. Vigilancia individualizada por irRECIST."},
        "SIPULEUCEL_T": {"nadir_pct": 1.00, "time_to_nadir_m": 0, "duration_response_m": 18,
                         "median_label": "Sipuleucel-T mCRPC asintomático (IMPACT)",
                         "data_quality_tag": "not_psa_endpoint_trial",
                         "evidence_pmid": ["20818862"],
                         "disclaimer": "Sipuleucel-T NO modula PSA (inmunoterapia celular). PSA puede subir mientras OS mejora. NO usar PSA como signal de respuesta. Curva nadir_pct=1.0 confirma esto."},
    },
}


def _classify_regimen_for_cohort(drug_scheme: str) -> str:
    """Faubot LXVIII #64A — Mapea drug_scheme canónico a clase para cohort lookup.

    EPIC 30.5 (GodiBot G70 HIGH) — extendido con Ra-223, Pembrolizumab, Sip-T y
    Cabazitaxel.

    EPIC 31.A (Explore EXP-8 CRIT) — triplet detection más robusta con aliases
    (DOC, DARO, ENZA, APA, ABI) + soporte para drug_scheme normalized strings
    que omiten "ADT_" prefix explícito (e.g. "DOCETAXEL_DAROLUTAMIDE" como
    triplete ARASENS implícito en mCSPC).
    """
    if not drug_scheme:
        return ""
    s = str(drug_scheme).upper()
    # EPIC 31.A — alias expansion para detección robusta
    docetaxel_tokens = ("DOCETAXEL", "DOC", "TAXANE", "TAXOTERE")
    arpi_tokens = ("ARPI", "ABIRATERONE", "ABI", "ENZALUTAMIDE", "ENZA",
                   "APALUTAMIDE", "APA", "DAROLUTAMIDE", "DARO")
    has_docetaxel = any(tok in s for tok in docetaxel_tokens)
    has_arpi = any(tok in s for tok in arpi_tokens)
    # Triplete: DOCETAXEL + ARPI (con o sin ADT explícito; en mCSPC ADT siempre
    # está presente clínicamente, no es opcional)
    if has_docetaxel and has_arpi:
        return "ADT_TRIPLET"
    # ADT + Docetaxel (sin ARPI)
    if has_docetaxel and ("ADT" in s or "HORMONAL" in s):
        return "ADT_DOCETAXEL"
    if has_docetaxel and not has_arpi:
        # Docetaxel solo (mCRPC primera línea quimio post-castración)
        return "DOCETAXEL"
    # EPIC 30.5: Cabazitaxel BEFORE generic Docetaxel check
    if "CABAZITAXEL" in s or "JEVTANA" in s:
        return "CABAZITAXEL"
    # EPIC 30.5: Ra-223 dichloride
    if "RA223" in s or "RA-223" in s or "RADIO-223" in s or "RADIUM" in s or "XOFIGO" in s:
        return "RA223"
    # EPIC 30.5: Pembrolizumab (Lynch/MSI-H mCRPC)
    if "PEMBROLIZUMAB" in s or "PEMBRO" in s or "KEYTRUDA" in s:
        return "PEMBROLIZUMAB"
    # EPIC 30.5: Sipuleucel-T cell immunotherapy
    if "SIPULEUCEL" in s or "SIP-T" in s or "PROVENGE" in s:
        return "SIPULEUCEL_T"
    # ADT + ARPI (sin docetaxel)
    if any(arpi in s for arpi in ["ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE"]):
        return "ADT_ARPI" if "ADT" in s else "ARPI"
    # PARP
    if any(parp in s for parp in ["OLAPARIB", "RUCAPARIB", "TALAZOPARIB", "NIRAPARIB", "PARP"]):
        return "PARP"
    # Lu-177
    if "LU177" in s or "LUTETIUM" in s or "PSMA-617" in s or "PLUVICTO" in s:
        return "LU177"
    # Solo Docetaxel
    if "DOCETAXEL" in s:
        return "DOCETAXEL"
    # Solo ADT
    if "ADT" in s or "MONO" in s:
        return "ADT"
    return ""


def build_psa_cohort_reference_overlay(patient: dict[str, Any]) -> dict[str, Any]:
    """Faubot 2026-04-25 (LXVIII) — Auditoría #64A.

    Construye curva de referencia PSA esperada para overlay en el chart,
    basada en literatura pivotal por (state, regimen_class).

    NO usa cohort data en vivo — usa medianas publicadas como mejor
    estimación. Cuando cohort data en vivo esté disponible, este helper
    se reemplaza por live_benchmark.curve real.

    Returns:
        {
            "has_data": bool,
            "reference_curve": [{"date": ISO, "expected_psa": float,
                                 "horizon_months": int}],
            "median_label": str,
            "cohort_class": str,
            "anchor_baseline_psa": float,
            "anchor_date": ISO,
            "narrative": str,
        }
    """
    state = str(
        patient.get("reconciled_state")
        or (patient.get("latest_assessment") or {}).get("state")
        or ""
    )
    monitoring = build_psa_by_treatment_line(patient)
    line_context = _current_line_context(patient, monitoring)
    drug_scheme = str(line_context.get("drug_scheme") or "")
    cohort_class = _classify_regimen_for_cohort(drug_scheme)
    state_refs = COHORT_PSA_REFERENCES.get(state, {})
    reference = state_refs.get(cohort_class)
    if not reference:
        return {
            "has_data": False,
            "reference_curve": [],
            "median_label": "",
            "cohort_class": cohort_class,
            "narrative": (
                f"Sin curva de referencia poblacional documentada para "
                f"({state}, {cohort_class}). Forecast individual sigue válido."
            ),
        }

    # Anchor: baseline_psa de la línea actual + start_date de la línea
    anchor_baseline = _safe_float(line_context.get("baseline_psa"))
    if anchor_baseline is None or anchor_baseline <= 0:
        # Fallback: baseline global del paciente
        anchor_baseline = _safe_float(
            (patient.get("baseline") or {}).get("baseline_psa")
            or patient.get("baseline_psa")
        )
    if anchor_baseline is None or anchor_baseline <= 0:
        return {
            "has_data": False,
            "reference_curve": [],
            "median_label": reference.get("median_label", ""),
            "cohort_class": cohort_class,
            "narrative": "Sin baseline_psa documentado para anclar curva de referencia.",
        }

    anchor_date = _parse_date(line_context.get("start_date"))
    if anchor_date is None:
        return {
            "has_data": False,
            "reference_curve": [],
            "median_label": reference.get("median_label", ""),
            "cohort_class": cohort_class,
            "narrative": "Sin start_date de línea actual para anclar curva.",
        }

    # Construir curva: log-linear decay del baseline al nadir esperado
    nadir_pct = float(reference["nadir_pct"])
    time_to_nadir_m = int(reference["time_to_nadir_m"])
    duration_m = int(reference["duration_response_m"])
    expected_nadir = anchor_baseline * nadir_pct

    reference_curve: list[dict[str, Any]] = []
    # Fase de respuesta: log-linear decay desde baseline a nadir
    for month in range(0, time_to_nadir_m + 1):
        if month == 0:
            psa = anchor_baseline
        else:
            # Decay log-linear hasta nadir
            log_decay = math.log(expected_nadir / anchor_baseline) * (month / time_to_nadir_m)
            psa = anchor_baseline * math.exp(log_decay)
        target_date = anchor_date + timedelta(days=int(month * 30.44))
        reference_curve.append({
            "horizon_months": month,
            "date": target_date.isoformat(),
            "expected_psa": _round_or_none(psa, 2),
        })
    # Fase de respuesta sostenida (mantiene nadir)
    for month in range(time_to_nadir_m + 1, time_to_nadir_m + duration_m + 1):
        target_date = anchor_date + timedelta(days=int(month * 30.44))
        reference_curve.append({
            "horizon_months": month,
            "date": target_date.isoformat(),
            "expected_psa": _round_or_none(expected_nadir, 2),
        })

    # EPIC 30.1 (PSA Tower coherence) — surface EPIC 29.9 disclaimers + build
    # `applicable_combos` array that the v2 template expects at line 2231.
    # Pre-EPIC30 los disclaimers (data_quality_tag, evidence_pmid, disclaimer)
    # se quedaban atrapados en COHORT_PSA_REFERENCES y la sección "Cohort ref"
    # en la torre de vigilancia NUNCA renderizaba porque applicable_combos
    # no existía en el bundle return. Resultado clínico: el especialista NO
    # veía la comparación pivotal NI los avisos de calidad de datos.
    applicable_combo = {
        "regimen_class": cohort_class,
        "median_label": reference["median_label"],
        "nadir_pct": _round_or_none(nadir_pct, 3),
        "time_to_nadir_m": time_to_nadir_m,
        "duration_response_m": duration_m,
        "expected_nadir_psa": _round_or_none(expected_nadir, 2),
        # EPIC 29.9 disclaimer fields surfaced
        "data_quality_tag": reference.get("data_quality_tag", ""),
        "disclaimer": reference.get("disclaimer", ""),
        "evidence_pmid": reference.get("evidence_pmid", []),
    }

    return {
        "has_data": True,
        "reference_curve": reference_curve,
        "median_label": reference["median_label"],
        "cohort_class": cohort_class,
        "anchor_baseline_psa": _round_or_none(anchor_baseline, 2),
        "anchor_date": anchor_date.isoformat(),
        "expected_nadir_psa": _round_or_none(expected_nadir, 2),
        "expected_time_to_nadir_months": time_to_nadir_m,
        "expected_duration_response_months": duration_m,
        # EPIC 30.1 — applicable_combos array para template line 2231
        "applicable_combos": [applicable_combo],
        # EPIC 30.1 — data_quality top-level para banner UI
        "data_quality_tag": reference.get("data_quality_tag", ""),
        "data_quality_disclaimer": reference.get("disclaimer", ""),
        "evidence_pmid": reference.get("evidence_pmid", []),
        "narrative": (
            f"{reference['median_label']}. Comparar trayectoria del paciente vs "
            f"mediana esperada (nadir ~{nadir_pct * 100:.0f}% baseline a {time_to_nadir_m}m, "
            f"respuesta sostenida ~{duration_m}m)."
            + (f" ⚠ {reference['disclaimer']}" if reference.get("disclaimer") else "")
        ),
    }


def build_psa_forecast_per_line(patient: dict[str, Any]) -> dict[str, Any]:
    """Faubot 2026-04-25 (LXVIII) — Auditoría #64A.

    Construye forecast log-linear PSA por CADA treatment line del paciente
    (no solo el current). Returns dict {line_number: forecast_dict, ...}
    + summary global con conteo de líneas con forecast disponible.

    Esto es complementario a `build_psa_forecast()` (que solo proyecta
    current line). El frontend puede usar ambos:
      - build_psa_forecast() → forecast principal current line en chart
      - build_psa_forecast_per_line() → forecasts adicionales para drill-down
        per-line + comparación de trayectorias entre líneas

    Returns:
        {
            "has_data": bool,
            "per_line_forecasts": {"1": {...forecast...}, "2": {...}},
            "lines_with_forecast_count": int,
            "lines_insufficient_data_count": int,
            "summary": {
                "total_lines": int,
                "ready_count": int,
                "insufficient_count": int,
            }
        }
    """
    monitoring = build_psa_by_treatment_line(patient)
    points_by_line = monitoring.get("points_by_line") or {}
    line_segments = monitoring.get("line_segments") or []

    # Mapear segments por line_of_therapy_number para metadata
    segments_by_line: dict[str, dict[str, Any]] = {}
    for seg in line_segments:
        ln = str(seg.get("line_of_therapy_number") or "")
        if ln:
            segments_by_line[ln] = seg

    per_line_forecasts: dict[str, dict[str, Any]] = {}
    ready_count = 0
    insufficient_count = 0

    for line_key, line_points in points_by_line.items():
        # line_key es string del line_of_therapy_number, o "pretreatment"/"between_lines"/"no_bands"
        # Solo computar forecast para líneas terapéuticas reales (numéricas)
        if not line_key.isdigit():
            continue
        seg = segments_by_line.get(line_key, {})
        forecast = _build_forecast_for_segment_points(
            line_points,
            line_label=seg.get("label", f"Línea {line_key}"),
            line_number=line_key,
            line_context=seg,
        )
        per_line_forecasts[line_key] = forecast
        if forecast.get("status") == "ready":
            ready_count += 1
        else:
            insufficient_count += 1

    return {
        "has_data": bool(per_line_forecasts),
        "per_line_forecasts": per_line_forecasts,
        "lines_with_forecast_count": ready_count,
        "lines_insufficient_data_count": insufficient_count,
        "summary": {
            "total_lines": len(per_line_forecasts),
            "ready_count": ready_count,
            "insufficient_count": insufficient_count,
        },
    }


def build_combined_patient_timeline(
    patient: dict[str, Any],
    *,
    clinical_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Faubot 2026-04-25 (LXVIII) — Auditoría #64A.

    Construye estructura combined timeline para chart unificado:
      - PSA points (con annotation per-line del #63B)
      - Treatment bands (per-line)
      - Clinical events markers (visitas, decisiones, cambios línea, etc.)

    Esto permite al chart de patient_profile.html renderizar TODO en un
    solo eje temporal sin duplicar dates entre múltiples charts. Antes
    de #64A, PSA chart + treatment timeline chart + clinical events lista
    estaban separados visualmente. Ahora hay UNA estructura combined que
    el frontend consume.

    Args:
        patient: dict del paciente (con biomarker_longitudinal + treatments)
        clinical_events: opcional, lista de eventos pre-construidos
            (e.g., from clinical_journey_events). Si None, se omiten markers.

    Returns:
        {
            "has_data": bool,
            "axis_dates": [ISO date strings],  # eje x unificado ordenado
            "psa_series": [{"date": ISO, "psa": float, "treatment_line": str|None}],
            "treatment_lanes": [{"line_number": str, "label": str, "color": str,
                                  "start_date": ISO, "end_date": ISO|None}],
            "clinical_event_markers": [{"date": ISO, "label": str, "type": str,
                                         "treatment_line": str|None}],
            "summary": {
                "total_psa_points": int,
                "total_treatment_lanes": int,
                "total_event_markers": int,
                "earliest_date": ISO|"",
                "latest_date": ISO|"",
            },
        }
    """
    monitoring = build_psa_by_treatment_line(patient)
    if not monitoring.get("has_data"):
        return {
            "has_data": False,
            "axis_dates": [],
            "psa_series": [],
            "treatment_lanes": [],
            "clinical_event_markers": [],
            "summary": {
                "total_psa_points": 0,
                "total_treatment_lanes": 0,
                "total_event_markers": 0,
                "earliest_date": "",
                "latest_date": "",
            },
        }

    # PSA series con anotación de treatment_line del #63B
    psa_series: list[dict[str, Any]] = []
    for point in monitoring.get("points") or []:
        psa_series.append({
            "date": point.get("date", ""),
            "psa": point.get("psa"),
            "treatment_line": point.get("treatment_line_number"),
            "treatment_line_label": point.get("treatment_line_label"),
            "treatment_color": point.get("treatment_color"),
            "assignment_origin": point.get("treatment_assignment_origin"),
        })

    # Treatment lanes desde bands
    treatment_lanes: list[dict[str, Any]] = []
    for band in monitoring.get("treatment_bands") or []:
        treatment_lanes.append({
            "line_number": str(band.get("line_of_therapy_number") or ""),
            "label": band.get("label", ""),
            "color": band.get("color"),
            "start_date": band.get("start_date", ""),
            "end_date": band.get("end_date") or "",
            "drug_scheme": band.get("drug_scheme"),
            "drug_scheme_label": band.get("drug_scheme_label"),
        })

    # Clinical event markers
    event_markers: list[dict[str, Any]] = []
    for event in clinical_events or []:
        if not isinstance(event, dict):
            continue
        event_date = event.get("date") or ""
        if not event_date:
            continue
        # Asignar treatment_line por fecha (similar pattern al #63B)
        event_parsed = _parse_date(event_date)
        assigned_line = None
        assigned_color = None
        if event_parsed:
            for lane in treatment_lanes:
                lane_start = _parse_date(lane.get("start_date"))
                lane_end = _parse_date(lane.get("end_date")) if lane.get("end_date") else date.today()
                if lane_start and lane_end and lane_start <= event_parsed <= lane_end:
                    assigned_line = lane.get("line_number")
                    assigned_color = lane.get("color")
                    break
        event_markers.append({
            "date": event_date,
            "label": event.get("title") or event.get("label", ""),
            "type": event.get("origin") or event.get("type", "event"),
            "decision": event.get("decision", ""),
            "treatment_line": assigned_line,
            "treatment_color": assigned_color,
        })

    # Eje X unificado: union de todas las dates ordenadas
    all_dates: set[str] = set()
    for p in psa_series:
        if p.get("date"):
            all_dates.add(p["date"])
    for lane in treatment_lanes:
        if lane.get("start_date"):
            all_dates.add(lane["start_date"])
        if lane.get("end_date"):
            all_dates.add(lane["end_date"])
    for m in event_markers:
        if m.get("date"):
            all_dates.add(m["date"])
    axis_dates = sorted(all_dates)

    return {
        "has_data": bool(psa_series),
        "axis_dates": axis_dates,
        "psa_series": psa_series,
        "treatment_lanes": treatment_lanes,
        "clinical_event_markers": event_markers,
        "summary": {
            "total_psa_points": len(psa_series),
            "total_treatment_lanes": len(treatment_lanes),
            "total_event_markers": len(event_markers),
            "earliest_date": axis_dates[0] if axis_dates else "",
            "latest_date": axis_dates[-1] if axis_dates else "",
        },
    }


def _matching_actual_point(
    points: list[dict[str, Any]],
    target_date: date,
    tolerance_days: int,
) -> dict[str, Any] | None:
    matches: list[tuple[int, dict[str, Any]]] = []
    for point in points:
        point_date = _parse_date(point.get("date"))
        if not point_date:
            continue
        delta_days = abs((point_date - target_date).days)
        if delta_days <= tolerance_days:
            matches.append((delta_days, point))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def build_psa_forecast_backtest(patient_records: list[dict[str, Any]]) -> dict[str, Any]:
    horizon_tolerances = {3: 45, 6: 60, 12: 90}
    rows = []
    by_horizon: dict[int, list[dict[str, Any]]] = {3: [], 6: [], 12: []}
    by_state: dict[str, dict[int, list[dict[str, Any]]]] = {}

    for patient in patient_records:
        state = str(patient.get("reconciled_state") or (patient.get("latest_assessment") or {}).get("state") or (patient.get("prior_history") or {}).get("current_state") or "")
        if state not in ADVANCED_FORECAST_STATES:
            continue
        monitoring = build_psa_by_treatment_line(patient)
        line_context = _current_line_context(patient, monitoring)
        points = _points_for_current_line(monitoring, line_context)
        if len(points) < 4:
            continue
        ordered = sorted(points, key=lambda item: item.get("date") or "")
        for index in range(2, len(ordered) - 1):
            history = ordered[: index + 1]
            model = _fit_log_psa_model(history)
            if model.get("status") != "ok":
                continue
            origin_date = _parse_date(history[-1]["date"])
            if not origin_date:
                continue
            for horizon in FORECAST_HORIZONS:
                target_date = origin_date + timedelta(days=int(horizon * 30.44))
                actual = _matching_actual_point(ordered[index + 1 :], target_date, horizon_tolerances[horizon])
                if not actual:
                    continue
                actual_date = _parse_date(actual.get("date"))
                if not actual_date:
                    continue
                history_x, _, _ = _prepare_regression_points(history)
                if len(history_x) == 0:
                    continue
                target_x = float((actual_date - _parse_date(history[0]["date"])).days / 30.44)
                prediction = _predict_log_point(model, target_x)
                actual_psa = _safe_float(actual.get("psa"))
                if actual_psa is None:
                    continue
                row = {
                    "patient_id": (patient.get("identity") or {}).get("id"),
                    "state": state,
                    "horizon_months": horizon,
                    "predicted_psa": _round_or_none(prediction["expected_psa"], 2),
                    "actual_psa": _round_or_none(actual_psa, 2),
                    "abs_error": _round_or_none(abs(prediction["expected_psa"] - actual_psa), 2),
                    "covered_by_interval": bool(prediction["lower_psa"] <= actual_psa <= prediction["upper_psa"]),
                }
                rows.append(row)
                by_horizon[horizon].append(row)
                state_bucket = by_state.setdefault(state, {3: [], 6: [], 12: []})
                state_bucket[horizon].append(row)

    def summarize(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        if not bucket:
            return {"n_predictions": 0, "mae": None, "median_abs_error": None, "coverage_pct": None}
        abs_errors = [float(item["abs_error"]) for item in bucket if item.get("abs_error") is not None]
        coverage = [1 if item.get("covered_by_interval") else 0 for item in bucket]
        return {
            "n_predictions": len(bucket),
            "mae": _round_or_none(sum(abs_errors) / len(abs_errors), 2) if abs_errors else None,
            "median_abs_error": _round_or_none(float(np.median(abs_errors)), 2) if abs_errors else None,
            "coverage_pct": _round_or_none(sum(coverage) / len(coverage) * 100.0, 1) if coverage else None,
        }

    by_state_summary = {
        state: {str(horizon): summarize(bucket) for horizon, bucket in horizon_buckets.items()}
        for state, horizon_buckets in by_state.items()
    }
    return {
        "status": "ok" if rows else "insufficient_data",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "eligible_predictions": len(rows),
        "summary_by_horizon": {str(horizon): summarize(bucket) for horizon, bucket in by_horizon.items()},
        "summary_by_state": by_state_summary,
        "rows": rows[:250],
    }
