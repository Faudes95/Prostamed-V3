"""trajectory_engine.py — EPIC 47.A (FAUBOT CXXXV).

Engine unificado de trayectoria longitudinal para cáncer de próstata.
Orquesta múltiples sources de datos temporales en una estructura coherente
consumible por el UI dashboard de Chart.js + alert engine clínico.

Filosofía clínica:
  El urólogo necesita ver la EVOLUCIÓN del paciente, no un snapshot.
  Hoy: "PSA actual = 4.2" → reactivo.
  Con engine: "PSA 1.8 → 2.3 → 3.4 → 4.2 (doubling time 6.5m, ⚠ <10m
  threshold), ALP +28% últimos 3m sin imagen positiva todavía" → predictivo.

Reusa infraestructura existente (NO duplica):
  - psa_forecast.build_combined_patient_timeline() — PSA + treatment lanes
  - psa_forecast.build_psa_cohort_reference_overlay() — cohort baseline
  - biomarker_longitudinal table — ALP, LDH, AST, ALT, bilirrubina, etc.
  - follow_up_visits.ecog_current — ECOG over time
  - clinical_memory_os.build_clinical_memory_os() — state transitions

Estructura de salida (consumida por Chart.js):
  {
    "available": bool,
    "summary": {n_visits, earliest_date, latest_date, n_treatment_lines},
    "series": {
      "psa": [{date, value, treatment_line}],
      "ecog": [{date, value}],
      "alp": [{date, value, unit}],
      "ldh": [{date, value, unit}],
    },
    "treatment_lanes": [{line_number, label, color, start, end}],
    "event_markers": [{date, label, type}],
    "cohort_overlay": {available, expected_curve: [{months, p50, p25, p75}]},
    "alerts": [{severity, alert_id, message, evidence, citation}],
    "kinetics": {
      "psa_doubling_time_months": float|None,
      "psa_velocity_ng_per_year": float|None,
      "psa_nadir": {value, date},
      "alp_trend_pct_3m": float|None,
      "ecog_decline_detected": bool,
    },
  }
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def build_trajectory_bundle(
    patient: dict[str, Any] | None,
    *,
    include_cohort_overlay: bool = True,
) -> dict[str, Any]:
    """Construye el bundle longitudinal unificado.

    Args:
        patient: dict del paciente (debe incluir biomarker_longitudinal +
            follow_ups + treatments + identity)
        include_cohort_overlay: si True, intenta computar cohort baseline
            (puede ser costoso para cohort grande — desactivable en tests)

    Returns:
        Dict con shape descrito en module docstring. Fail-safe: si cualquier
        sub-builder falla, retorna {"available": False, "reason": ...} en
        lugar de levantar.
    """
    if not patient or not isinstance(patient, dict):
        return _empty_bundle(reason="no_patient_data")

    # 1. PSA + treatment lanes (reusa build_combined_patient_timeline)
    psa_timeline = _safe_build_psa_timeline(patient)

    # 2. Biomarker series (ALP, LDH desde biomarker_longitudinal)
    biomarker_series = _build_biomarker_series(patient)

    # 3. ECOG series (desde follow_up_visits)
    ecog_series = _build_ecog_series(patient)

    # 4. Cohort overlay (opcional, costoso)
    cohort_overlay = (
        _safe_build_cohort_overlay(patient) if include_cohort_overlay
        else {"available": False, "reason": "skipped_by_caller"}
    )

    # 5. Kinetics computation (PSA doubling time, velocity, ALP trend)
    kinetics = _compute_kinetics(
        psa_points=psa_timeline.get("psa_series") or [],
        alp_points=biomarker_series.get("alp") or [],
        ecog_points=ecog_series,
    )

    # Si NO hay nada de PSA y NO hay biomarkers ni ECOG, devolver vacío
    has_any_temporal_data = bool(
        psa_timeline.get("has_data")
        or biomarker_series.get("alp")
        or biomarker_series.get("ldh")
        or ecog_series
    )
    if not has_any_temporal_data:
        return _empty_bundle(reason="no_temporal_observations")

    return {
        "available": True,
        "summary": {
            "n_visits": len(psa_timeline.get("psa_series") or []),
            "earliest_date": psa_timeline.get("summary", {}).get("earliest_date", ""),
            "latest_date": psa_timeline.get("summary", {}).get("latest_date", ""),
            "n_treatment_lines": len(psa_timeline.get("treatment_lanes") or []),
            "n_biomarker_alp": len(biomarker_series.get("alp") or []),
            "n_biomarker_ldh": len(biomarker_series.get("ldh") or []),
            "n_ecog": len(ecog_series),
        },
        "series": {
            "psa": psa_timeline.get("psa_series") or [],
            "ecog": ecog_series,
            "alp": biomarker_series.get("alp") or [],
            "ldh": biomarker_series.get("ldh") or [],
            "testosterone": biomarker_series.get("testosterone") or [],
        },
        "treatment_lanes": psa_timeline.get("treatment_lanes") or [],
        "event_markers": psa_timeline.get("clinical_event_markers") or [],
        "cohort_overlay": cohort_overlay,
        "kinetics": kinetics,
        # Alerts pobladas separadamente por trajectory_alert_engine
        # (mantiene single-responsibility — este engine solo agrega data)
        "alerts": [],
        "engine_version": "epic47_v1.0",
    }


# ─────────────────────────────────────────────────────────────────────
# Sub-builders
# ─────────────────────────────────────────────────────────────────────


def _safe_build_psa_timeline(patient: dict[str, Any]) -> dict[str, Any]:
    """Wrapper fail-safe sobre build_combined_patient_timeline."""
    try:
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_combined_patient_timeline,
        )
        return build_combined_patient_timeline(patient) or {}
    except Exception as exc:
        logger.debug("PSA timeline builder failed: %s", exc)
        return {"has_data": False, "psa_series": [], "treatment_lanes": []}


def _build_biomarker_series(patient: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extrae series temporales de ALP / LDH / testosterona desde
    `patient.biomarker_longitudinal` (poblado por tracking_db._hydrate_
    biomarker_rows).

    Returns dict por biomarker_type (uppercase ALP / LDH / TESTOSTERONA).
    """
    biomarkers = patient.get("biomarker_longitudinal") or []
    if not isinstance(biomarkers, list):
        return {"alp": [], "ldh": [], "testosterone": []}

    series: dict[str, list[dict[str, Any]]] = {
        "alp": [],
        "ldh": [],
        "testosterone": [],
    }
    for b in biomarkers:
        if not isinstance(b, dict):
            continue
        bt = str(b.get("biomarker_type") or "").strip().upper()
        if bt not in {"ALP", "LDH", "TESTOSTERONA", "TESTOSTERONE"}:
            continue
        value = b.get("value")
        date = b.get("sample_date") or b.get("created_at") or ""
        if value is None or not date:
            continue
        try:
            value_float = float(value)
        except (ValueError, TypeError):
            continue
        key = "testosterone" if bt in {"TESTOSTERONA", "TESTOSTERONE"} else bt.lower()
        series[key].append({
            "date": str(date)[:10],  # YYYY-MM-DD slice
            "value": value_float,
            "unit": str(b.get("unit") or "").strip(),
            "lab_source": str(b.get("lab_source") or "").strip(),
        })

    # Sort each series by date asc
    for k in series:
        series[k].sort(key=lambda x: x["date"])

    return series


def _build_ecog_series(patient: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae ECOG over time desde follow_up_visits + baseline.

    Returns list ordenada por date asc: [{date, value, source}].
    """
    series: list[dict[str, Any]] = []

    # Baseline ECOG (visit inicial)
    baseline = patient.get("baseline") or {}
    if isinstance(baseline, dict):
        ecog_baseline = baseline.get("ecog") or baseline.get("ecog_score")
        baseline_date = baseline.get("diagnosis_date") or baseline.get("baseline_date")
        if ecog_baseline is not None and baseline_date:
            try:
                series.append({
                    "date": str(baseline_date)[:10],
                    "value": int(ecog_baseline),
                    "source": "baseline",
                })
            except (ValueError, TypeError):
                pass

    # Follow-up visits (campo ecog_current)
    visits = patient.get("follow_ups") or patient.get("follow_up_visits") or []
    if isinstance(visits, list):
        for v in visits:
            if not isinstance(v, dict):
                continue
            ecog = v.get("ecog_current") or v.get("ecog")
            visit_date = v.get("visit_date") or v.get("date")
            if ecog is None or not visit_date:
                continue
            try:
                series.append({
                    "date": str(visit_date)[:10],
                    "value": int(ecog),
                    "source": "follow_up_visit",
                    "visit_id": v.get("id"),
                })
            except (ValueError, TypeError):
                continue

    # Dedup por date (keep last), sort asc
    by_date: dict[str, dict[str, Any]] = {}
    for s in series:
        by_date[s["date"]] = s
    sorted_series = sorted(by_date.values(), key=lambda x: x["date"])
    return sorted_series


def _safe_build_cohort_overlay(patient: dict[str, Any]) -> dict[str, Any]:
    """Wrapper fail-safe sobre build_psa_cohort_reference_overlay."""
    try:
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_cohort_reference_overlay,
        )
        overlay = build_psa_cohort_reference_overlay(patient) or {}
        # Normalizar shape: nuestro contrato usa {available, expected_curve}
        if overlay.get("has_data") or overlay.get("cohort_size"):
            return {
                "available": True,
                "cohort_size": overlay.get("cohort_size", 0),
                "expected_curve": overlay.get("series") or overlay.get("expected_curve") or [],
                "stratification": overlay.get("stratification") or overlay.get("filter_criteria") or {},
            }
        return {"available": False, "reason": "no_cohort_match"}
    except Exception as exc:
        logger.debug("Cohort overlay builder failed: %s", exc)
        return {"available": False, "reason": f"builder_error: {type(exc).__name__}"}


# ─────────────────────────────────────────────────────────────────────
# Kinetics computation
# ─────────────────────────────────────────────────────────────────────


def _compute_kinetics(
    *,
    psa_points: list[dict[str, Any]],
    alp_points: list[dict[str, Any]],
    ecog_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Computa métricas clínicas derivadas del trajectory.

    PSA doubling time: regresión lineal en log(PSA) vs tiempo (meses).
    Formula NCCN: PSADT = ln(2) / slope, donde slope viene de regresión
    log(PSA) sobre tiempo en meses.

    ALP trend: % cambio últimos 3 meses (predictor temprano bone mets).

    ECOG decline: bool si último ECOG > primer ECOG en últimos 6 meses.
    """
    kinetics: dict[str, Any] = {
        "psa_doubling_time_months": None,
        "psa_velocity_ng_per_year": None,
        "psa_nadir": None,
        "psa_last_value": None,
        "alp_trend_pct_3m": None,
        "ecog_decline_detected": False,
        "ecog_first": None,
        "ecog_last": None,
    }

    # PSA kinetics
    psa_valid = [
        (_parse_date(p.get("date")), float(p["psa"]) if p.get("psa") not in (None, "") else None)
        for p in psa_points
    ]
    psa_valid = [(d, v) for d, v in psa_valid if d is not None and v is not None and v > 0]
    if len(psa_valid) >= 2:
        kinetics["psa_doubling_time_months"] = _psa_doubling_time(psa_valid)
        kinetics["psa_velocity_ng_per_year"] = _psa_velocity(psa_valid)
        # Nadir = mínimo PSA observado
        nadir_d, nadir_v = min(psa_valid, key=lambda x: x[1])
        kinetics["psa_nadir"] = {"value": nadir_v, "date": nadir_d.isoformat()}
        kinetics["psa_last_value"] = psa_valid[-1][1]

    # ALP trend (% últimos 3 meses)
    if len(alp_points) >= 2:
        kinetics["alp_trend_pct_3m"] = _trend_pct_window(alp_points, window_months=3)

    # ECOG decline
    if len(ecog_points) >= 2:
        first = ecog_points[0]
        last = ecog_points[-1]
        kinetics["ecog_first"] = first["value"]
        kinetics["ecog_last"] = last["value"]
        kinetics["ecog_decline_detected"] = bool(last["value"] > first["value"])

    return kinetics


def _parse_date(date_str: Any) -> datetime | None:
    if not date_str:
        return None
    try:
        s = str(date_str)[:10]
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _psa_doubling_time(points: list[tuple[datetime, float]]) -> float | None:
    """PSADT por regresión log-linear. Formula: PSADT = ln(2) / slope.

    Solo retorna valor si slope > 0 (PSA rising). Sino None.
    """
    import math
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(p[0] - t0).days / 30.4375 for p in points]  # meses
    ys = [math.log(p[1]) for p in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den  # ln(PSA) por mes
    if slope <= 0:
        return None  # PSA bajando → no aplica doubling time
    return round(math.log(2) / slope, 2)


def _psa_velocity(points: list[tuple[datetime, float]]) -> float | None:
    """Velocity = ng/mL ganados por año (regresión lineal directa)."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(p[0] - t0).days / 365.25 for p in points]  # años
    ys = [p[1] for p in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return round(slope, 3)


def _trend_pct_window(
    points: list[dict[str, Any]],
    window_months: int,
) -> float | None:
    """% cambio entre el promedio inicial vs últimos N meses."""
    if len(points) < 2:
        return None
    last_date = _parse_date(points[-1].get("date"))
    if last_date is None:
        return None
    window_start_days = window_months * 30.4375
    last_value = float(points[-1]["value"])
    # Encuentra el valor más antiguo que cae fuera de la ventana
    earliest_outside = None
    for p in points:
        p_date = _parse_date(p.get("date"))
        if p_date is None:
            continue
        delta_days = (last_date - p_date).days
        if delta_days >= window_start_days:
            earliest_outside = float(p["value"])
            break
    if earliest_outside is None or earliest_outside == 0:
        # Si no hay punto fuera de ventana, usar primero del rango
        earliest_outside = float(points[0]["value"])
        if earliest_outside == 0:
            return None
    return round(((last_value - earliest_outside) / earliest_outside) * 100, 1)


# ─────────────────────────────────────────────────────────────────────
# Empty bundle helper
# ─────────────────────────────────────────────────────────────────────


def _empty_bundle(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "summary": {
            "n_visits": 0,
            "earliest_date": "",
            "latest_date": "",
            "n_treatment_lines": 0,
            "n_biomarker_alp": 0,
            "n_biomarker_ldh": 0,
            "n_ecog": 0,
        },
        "series": {"psa": [], "ecog": [], "alp": [], "ldh": [], "testosterone": []},
        "treatment_lanes": [],
        "event_markers": [],
        "cohort_overlay": {"available": False, "reason": reason},
        "kinetics": {
            "psa_doubling_time_months": None,
            "psa_velocity_ng_per_year": None,
            "psa_nadir": None,
            "alp_trend_pct_3m": None,
            "ecog_decline_detected": False,
        },
        "alerts": [],
        "engine_version": "epic47_v1.0",
    }


__all__ = [
    "build_trajectory_bundle",
]
