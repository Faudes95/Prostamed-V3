# -*- coding: utf-8 -*-
"""
Módulo de visualización de respuesta terapéutica.

Genera datos estructurados para gráficos clínicos:
  - Waterfall plot: mejor respuesta PSA por línea de tratamiento
  - Spider plot: cambio longitudinal de lesiones individuales
  - Swimmer plot: duración de tratamientos con anotaciones de respuesta
  - PSA trajectory: trayectoria PSA con overlays de tratamiento

Los datos se retornan como dicts listos para Chart.js en el frontend.

Referencia:
  Gillessen S et al. Eur Urol 2022 — Data visualization in PCa trials
  PCWG3 — Scher HI et al. J Clin Oncol 2016
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WaterfallBar:
    """Barra individual del waterfall plot."""
    label: str  # Nombre del esquema
    line_of_therapy: int
    psa_change_pct: float  # % cambio desde baseline
    nadir_psa: float
    baseline_psa: float
    outcome: str  # Ongoing, Progression, Toxicidad
    color: str  # Hex color según categoría de respuesta


@dataclass
class SpiderPoint:
    """Punto de una línea del spider plot (una lesión en un timepoint)."""
    timepoint_label: str  # e.g., "Baseline", "Sem 12", "Sem 24"
    measurement_date: str
    change_from_baseline_pct: float


@dataclass
class SpiderLine:
    """Una línea del spider plot (una lesión a lo largo del tiempo)."""
    lesion_id: str
    location: str
    category: str  # target, non-target
    points: list[SpiderPoint]
    best_response_pct: float
    color: str


@dataclass
class SwimmerLane:
    """Una barra del swimmer plot (un tratamiento)."""
    label: str
    line_of_therapy: int
    start_month: float  # Meses desde diagnóstico
    duration_months: float
    outcome: str
    color: str
    markers: list[dict[str, Any]] = field(default_factory=list)  # PSA50, PD, etc.


@dataclass
class PSATrajectoryPoint:
    """Punto de la trayectoria PSA."""
    date: str
    psa: float
    treatment_label: str | None = None


@dataclass
class ResponseVisualizationBundle:
    """Bundle completo de datos de visualización."""
    waterfall: list[dict[str, Any]]
    spider: dict[str, Any]
    swimmer: list[dict[str, Any]]
    psa_trajectory: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResponseVisualizationService:
    """Genera datos de visualización de respuesta terapéutica."""

    @classmethod
    def build_visualization_bundle(
        cls,
        treatments: list[dict[str, Any]],
        lesions: list[dict[str, Any]] | None = None,
        psa_series: list[dict[str, Any]] | None = None,
        baseline_psa: float | None = None,
        diagnosis_date: str | None = None,
    ) -> ResponseVisualizationBundle:
        """Genera el bundle completo de datos de visualización."""
        return ResponseVisualizationBundle(
            waterfall=cls.build_waterfall(treatments, baseline_psa),
            spider=cls.build_spider(lesions or []),
            swimmer=cls.build_swimmer(treatments, diagnosis_date),
            psa_trajectory=cls.build_psa_trajectory(psa_series or [], treatments, diagnosis_date),
        )

    @staticmethod
    def build_waterfall(
        treatments: list[dict[str, Any]],
        baseline_psa: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Waterfall plot: mejor respuesta PSA (% cambio) por línea de tratamiento.

        Colores:
          - Verde (#10b981): respuesta profunda (≤-50%)
          - Azul (#3b82f6): respuesta parcial (-50% a -30%)
          - Amarillo (#f59e0b): estabilidad (-30% a 0%)
          - Rojo (#ef4444): progresión (>0%)
        """
        if not baseline_psa or baseline_psa <= 0:
            baseline_psa = _first_valid_float(
                [t.get("baseline_psa") for t in treatments], fallback=10.0
            )

        bars: list[dict[str, Any]] = []
        for tx in treatments:
            nadir = _safe_float(tx.get("nadir_psa"), None)
            if nadir is None:
                continue

            change_pct = ((nadir - baseline_psa) / baseline_psa) * 100 if baseline_psa > 0 else 0

            if change_pct <= -50:
                color = "#10b981"
            elif change_pct <= -30:
                color = "#3b82f6"
            elif change_pct <= 0:
                color = "#f59e0b"
            else:
                color = "#ef4444"

            bars.append(asdict(WaterfallBar(
                label=tx.get("drug_scheme") or f"Línea {tx.get('line_of_therapy', '?')}",
                line_of_therapy=int(tx.get("line_of_therapy") or len(bars) + 1),
                psa_change_pct=round(change_pct, 1),
                nadir_psa=round(nadir, 2),
                baseline_psa=round(baseline_psa, 2),
                outcome=tx.get("outcome") or "Desconocido",
                color=color,
            )))

        # Ordenar por línea de terapia
        bars.sort(key=lambda b: b["line_of_therapy"])
        return bars

    @staticmethod
    def build_spider(lesions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Spider plot: cambio porcentual longitudinal de lesiones individuales.

        Cada lesión es una línea con múltiples timepoints.
        Eje Y: % cambio desde baseline (primera medición).
        Eje X: timepoints cronológicos.

        Input esperado: lista de dicts con:
          - lesion_id, anatomical_location, lesion_category
          - measurements: [{measurement_date, longest_diameter_mm, suvmax, volume_ml}]
        """
        if not lesions:
            return {"lines": [], "timepoints": [], "has_data": False}

        # Paleta de colores para lesiones
        palette = [
            "#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6",
            "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#a855f7",
        ]

        all_timepoints: set[str] = set()
        lines: list[dict[str, Any]] = []

        for idx, lesion in enumerate(lesions):
            measurements = lesion.get("measurements") or []
            if len(measurements) < 2:
                continue

            # Ordenar por fecha
            measurements = sorted(measurements, key=lambda m: m.get("measurement_date") or "")

            baseline_val = _safe_float(measurements[0].get("longest_diameter_mm"), None)
            if not baseline_val or baseline_val <= 0:
                continue

            points: list[dict[str, Any]] = []
            best_response = 0.0

            for i, m in enumerate(measurements):
                val = _safe_float(m.get("longest_diameter_mm"), None)
                if val is None:
                    continue
                date = m.get("measurement_date") or f"T{i}"
                change_pct = ((val - baseline_val) / baseline_val) * 100

                if i == 0:
                    tp_label = "Baseline"
                else:
                    tp_label = date

                all_timepoints.add(date)
                points.append(asdict(SpiderPoint(
                    timepoint_label=tp_label,
                    measurement_date=date,
                    change_from_baseline_pct=round(change_pct, 1),
                )))

                if change_pct < best_response:
                    best_response = change_pct

            color = palette[idx % len(palette)]
            location = lesion.get("anatomical_location") or f"Lesión {idx + 1}"
            category = lesion.get("lesion_category") or "target"

            lines.append(asdict(SpiderLine(
                lesion_id=lesion.get("lesion_id") or str(idx + 1),
                location=location,
                category=category,
                points=points,
                best_response_pct=round(best_response, 1),
                color=color,
            )))

        timepoints_sorted = sorted(all_timepoints)

        return {
            "lines": lines,
            "timepoints": timepoints_sorted,
            "has_data": len(lines) > 0,
            "recist_thresholds": {
                "pr_line": -30,  # RECIST PR threshold
                "pd_line": 20,   # RECIST PD threshold
            },
        }

    @staticmethod
    def build_swimmer(
        treatments: list[dict[str, Any]],
        diagnosis_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Swimmer plot: duración de cada línea terapéutica con marcadores de evento.

        Eje X: meses desde inicio de primera línea (o diagnóstico).
        Cada barra horizontal = un tratamiento con duración y outcome.
        Marcadores: PSA50, PSA90, PD, cambio de línea.
        """
        if not treatments:
            return []

        timeline = _build_treatment_lane_models(
            treatments=treatments,
            diagnosis_date=diagnosis_date,
            cutoff_date=None,
        )
        lanes: list[dict[str, Any]] = []
        for lane in timeline:
            lanes.append(asdict(SwimmerLane(
                label=lane.get("label") or "Desconocido",
                line_of_therapy=int(lane.get("line_of_therapy") or len(lanes) + 1),
                start_month=round(_safe_float(lane.get("start_month"), 0.0) or 0.0, 1),
                duration_months=round(max(_safe_float(lane.get("duration_months"), 0.5) or 0.5, 0.5), 1),
                outcome=lane.get("outcome") or "",
                color=lane.get("color") or "#64748b",
                markers=list(lane.get("markers") or []),
            )))

        lanes.sort(key=lambda l: l["line_of_therapy"])
        return lanes

    @staticmethod
    def build_psa_trajectory(
        psa_series: list[dict[str, Any]],
        treatments: list[dict[str, Any]] | None = None,
        diagnosis_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Trayectoria PSA con cronología terapéutica integrada.

        Genera data para gráfico de línea con fechas ISO absolutas compartidas.
        """
        points: list[dict[str, Any]] = []
        for entry in sorted(psa_series, key=lambda e: e.get("sample_date") or e.get("date") or ""):
            date = entry.get("sample_date") or entry.get("date") or ""
            psa = _safe_float(entry.get("value") or entry.get("psa"), None)
            if psa is not None and date:
                points.append({"date": date, "psa": round(psa, 2)})

        treatment_bands: list[dict[str, Any]] = []
        if treatments:
            band_colors = [
                "rgba(59,130,246,0.15)", "rgba(139,92,246,0.15)",
                "rgba(239,68,68,0.15)", "rgba(20,184,166,0.15)",
                "rgba(249,115,22,0.15)", "rgba(236,72,153,0.15)",
            ]
            for i, tx in enumerate(treatments):
                start = tx.get("start_date")
                if not start:
                    continue
                treatment_bands.append({
                    "label": tx.get("drug_scheme") or f"Línea {i+1}",
                    "start_date": start,
                    "end_date": tx.get("end_date") or "2026-03-15",
                    "color": band_colors[i % len(band_colors)],
                })

        cutoff_date = _resolve_cutoff_date(points, treatments or [])
        timeline = _build_integrated_treatment_timeline(
            points=points,
            treatments=treatments or [],
            diagnosis_date=diagnosis_date,
            cutoff_date=cutoff_date,
        )
        axis_dates = sorted(set(
            [point.get("date") for point in points if point.get("date")] +
            list(timeline.get("axis_dates") or [])
        ))

        return {
            "points": points,
            "treatment_bands": treatment_bands,
            "axis_dates": axis_dates,
            "integrated_treatment_timeline": timeline,
            "has_data": bool(points or timeline.get("has_integrated_timeline")),
        }


def build_waterfall_from_line_segments(line_segments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for index, segment in enumerate(line_segments or []):
        change_pct = _safe_float(segment.get("best_pct_change"), None)
        baseline_psa = _safe_float(segment.get("baseline_psa"), None)
        nadir_psa = _safe_float(segment.get("nadir_psa"), None)
        if change_pct is None or baseline_psa is None or nadir_psa is None:
            continue
        if change_pct <= -50:
            color = "#10b981"
        elif change_pct <= -30:
            color = "#3b82f6"
        elif change_pct <= 0:
            color = "#f59e0b"
        else:
            color = "#ef4444"
        bars.append(
            asdict(
                WaterfallBar(
                    label=segment.get("label") or f"Línea {index + 1}",
                    line_of_therapy=int(segment.get("line_of_therapy_number") or index + 1),
                    psa_change_pct=round(change_pct, 1),
                    nadir_psa=round(nadir_psa, 2),
                    baseline_psa=round(baseline_psa, 2),
                    outcome=segment.get("outcome") or ("PSA50" if change_pct <= -50 else "En seguimiento"),
                    color=color,
                )
            )
        )
    bars.sort(key=lambda item: item.get("line_of_therapy") or 0)
    return bars


# ── Utilidades privadas ────────────────────────────────────────────────────

def _safe_float(val: Any, default: float | None = 0.0) -> float | None:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _first_valid_float(values: list[Any], fallback: float = 10.0) -> float:
    for v in values:
        r = _safe_float(v, None)
        if r is not None and r > 0:
            return r
    return fallback


def _months_between(date1: str, date2: str) -> float:
    """Calcula meses aproximados entre dos fechas ISO."""
    try:
        from datetime import datetime
        d1 = datetime.strptime(str(date1)[:10], "%Y-%m-%d")
        d2 = datetime.strptime(str(date2)[:10], "%Y-%m-%d")
        delta = d2 - d1
        return delta.days / 30.44
    except (ValueError, TypeError):
        return 0.0


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _format_iso_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _shift_date_by_months(base_date: date | None, months: float | None) -> date | None:
    if not base_date or months is None:
        return None
    try:
        return base_date + timedelta(days=max(int(round(float(months) * 30.44)), 0))
    except (TypeError, ValueError):
        return None


def _resolve_reference_date(diagnosis_date: str | None, treatments: list[dict[str, Any]]) -> date:
    reference = _parse_iso_date(diagnosis_date)
    for treatment in treatments:
        start_date = _parse_iso_date(treatment.get("start_date"))
        if start_date and (reference is None or start_date < reference):
            reference = start_date
    return reference or date(2024, 1, 1)


def _resolve_cutoff_date(points: list[dict[str, Any]], treatments: list[dict[str, Any]]) -> date:
    candidates: list[date] = [date.today()]
    for point in points:
        point_date = _parse_iso_date(point.get("date"))
        if point_date:
            candidates.append(point_date)
    for treatment in treatments:
        for field in ("start_date", "end_date"):
            treatment_date = _parse_iso_date(treatment.get(field))
            if treatment_date:
                candidates.append(treatment_date)
    return max(candidates) if candidates else date.today()


def _treatment_color(scheme: Any) -> str:
    drug_colors = {
        "ADT": "#3b82f6",
        "ARPI": "#8b5cf6",
        "DOCETAXEL": "#ef4444",
        "CABAZITAXEL": "#f97316",
        "RADIUM": "#14b8a6",
        "LUTETIUM": "#ec4899",
        "PARP": "#6366f1",
        "PEMBROLIZUMAB": "#a855f7",
    }
    text = str(scheme or "").upper()
    for key, color in drug_colors.items():
        if key in text:
            return color
    return "#64748b"


def _marker_entry(
    *,
    marker_type: str,
    symbol: str,
    color: str,
    month: float | None,
    marker_date: date | None,
    label: str,
) -> dict[str, Any]:
    return {
        "type": marker_type,
        "label": label,
        "symbol": symbol,
        "month": round(month, 1) if month is not None else None,
        "date": _format_iso_date(marker_date),
        "color": color,
    }


def _build_lane_markers(
    *,
    treatment: dict[str, Any],
    start_date: date,
    start_month: float,
    duration_months: float,
    end_date: date,
    next_start_date: date | None,
) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    regimen = treatment.get("regimen") or {}
    outcome = str(treatment.get("outcome") or "")
    nadir_psa = _safe_float(treatment.get("nadir_psa") if treatment.get("nadir_psa") is not None else regimen.get("nadir_psa"), None)
    baseline_psa = _safe_float(treatment.get("baseline_psa") if treatment.get("baseline_psa") is not None else regimen.get("baseline_psa"), None)
    nadir_time = _safe_float(
        treatment.get("time_to_nadir_months") if treatment.get("time_to_nadir_months") is not None else regimen.get("time_to_nadir_months"),
        None,
    )
    if nadir_psa is not None and baseline_psa and baseline_psa > 0:
        change = ((nadir_psa - baseline_psa) / baseline_psa) * 100
        nadir_offset = nadir_time if nadir_time is not None else duration_months * 0.3
        nadir_date = _shift_date_by_months(start_date, nadir_offset)
        absolute_month = start_month + nadir_offset
        if change <= -90:
            markers.append(_marker_entry(
                marker_type="PSA90",
                label="PSA90",
                symbol="▼▼",
                color="#10b981",
                month=absolute_month,
                marker_date=nadir_date,
            ))
        elif change <= -50:
            markers.append(_marker_entry(
                marker_type="PSA50",
                label="PSA50",
                symbol="▼",
                color="#3b82f6",
                month=absolute_month,
                marker_date=nadir_date,
            ))

    end_month = start_month + duration_months
    if "progres" in outcome.lower():
        markers.append(_marker_entry(
            marker_type="PD",
            label="Progresión",
            symbol="✕",
            color="#ef4444",
            month=end_month,
            marker_date=end_date,
        ))

    if next_start_date:
        markers.append(_marker_entry(
            marker_type="LINE_CHANGE",
            label="Cambio de línea",
            symbol="↺",
            color="#f59e0b",
            month=end_month,
            marker_date=next_start_date,
        ))
    elif end_date and "ongoing" not in outcome.lower():
        markers.append(_marker_entry(
            marker_type="LINE_END",
            label="Fin de línea",
            symbol="■",
            color="#94a3b8",
            month=end_month,
            marker_date=end_date,
        ))
    return markers


def _build_treatment_lane_models(
    *,
    treatments: list[dict[str, Any]],
    diagnosis_date: str | None,
    cutoff_date: date | None,
) -> list[dict[str, Any]]:
    if not treatments:
        return []

    sorted_treatments = sorted(
        [treatment for treatment in treatments if treatment.get("start_date")],
        key=lambda item: str(item.get("start_date") or ""),
    )
    if not sorted_treatments:
        return []

    reference_date = _resolve_reference_date(diagnosis_date, sorted_treatments)
    resolved_cutoff = cutoff_date or _resolve_cutoff_date([], sorted_treatments)
    lanes: list[dict[str, Any]] = []

    for index, treatment in enumerate(sorted_treatments):
        regimen = treatment.get("regimen") or {}
        start_date = _parse_iso_date(treatment.get("start_date"))
        if not start_date:
            continue
        explicit_end = _parse_iso_date(treatment.get("end_date"))
        next_start = _parse_iso_date(sorted_treatments[index + 1].get("start_date")) if index + 1 < len(sorted_treatments) else None
        derived_end = explicit_end or next_start or resolved_cutoff
        duration_months = max(_months_between(_format_iso_date(start_date), _format_iso_date(derived_end)), 0.5)
        start_month = _months_between(_format_iso_date(reference_date), _format_iso_date(start_date))
        scheme_label = (
            treatment.get("drug_scheme_label")
            or treatment.get("current_treatment")
            or regimen.get("current_treatment")
            or treatment.get("drug_scheme")
            or regimen.get("drug_scheme")
            or f"Línea {treatment.get('line_of_therapy') or treatment.get('line_of_therapy_number') or index + 1}"
        )
        line_of_therapy = int(
            treatment.get("line_of_therapy")
            or treatment.get("line_of_therapy_number")
            or index + 1
        )
        color = _treatment_color(treatment.get("drug_scheme") or scheme_label)
        ongoing = not explicit_end and next_start is None
        markers = _build_lane_markers(
            treatment=treatment,
            start_date=start_date,
            start_month=start_month,
            duration_months=duration_months,
            end_date=derived_end,
            next_start_date=next_start,
        )
        lanes.append(
            {
                "label": scheme_label,
                "line_of_therapy": line_of_therapy,
                "drug_scheme": treatment.get("drug_scheme") or scheme_label,
                "start_month": round(start_month, 1),
                "duration_months": round(duration_months, 1),
                "start_date": _format_iso_date(start_date),
                "end_date": _format_iso_date(derived_end),
                "ongoing": ongoing,
                "end_status": "ongoing" if ongoing else "completed",
                "outcome": treatment.get("outcome") or "",
                "color": color,
                "markers": markers,
            }
        )
    return lanes


def _build_integrated_treatment_timeline(
    *,
    points: list[dict[str, Any]],
    treatments: list[dict[str, Any]],
    diagnosis_date: str | None,
    cutoff_date: date,
) -> dict[str, Any]:
    treatment_lanes = _build_treatment_lane_models(
        treatments=treatments,
        diagnosis_date=diagnosis_date,
        cutoff_date=cutoff_date,
    )
    axis_dates: set[str] = {point.get("date") for point in points if point.get("date")}
    lane_markers: list[dict[str, Any]] = []
    active_line_windows: list[dict[str, Any]] = []
    line_labels: list[str] = []

    for lane_index, lane in enumerate(treatment_lanes):
        if lane.get("start_date"):
            axis_dates.add(str(lane.get("start_date")))
        if lane.get("end_date"):
            axis_dates.add(str(lane.get("end_date")))
        line_labels.append(str(lane.get("label") or f"Línea {lane_index + 1}"))
        active_line_windows.append(
            {
                "line_of_therapy": lane.get("line_of_therapy"),
                "label": lane.get("label"),
                "start_date": lane.get("start_date"),
                "end_date": lane.get("end_date"),
                "ongoing": lane.get("ongoing", False),
                "outcome": lane.get("outcome") or "",
            }
        )
        for marker in lane.get("markers") or []:
            marker_date = marker.get("date")
            if marker_date:
                axis_dates.add(str(marker_date))
            lane_markers.append(
                {
                    **marker,
                    "lane_index": lane_index,
                    "lane_label": lane.get("label"),
                    "line_of_therapy": lane.get("line_of_therapy"),
                    "drug_scheme": lane.get("drug_scheme"),
                }
            )

    return {
        "axis_dates": sorted(date_text for date_text in axis_dates if date_text),
        "treatment_lanes": treatment_lanes,
        "lane_markers": lane_markers,
        "line_labels": line_labels,
        "active_line_windows": active_line_windows,
        "has_integrated_timeline": len(treatment_lanes) > 0,
    }


# ── Kaplan-Meier visualization (cohort level) ────────────────────────────

@dataclass
class KaplanMeierData:
    """Datos para visualización Kaplan-Meier."""
    endpoint_type: str  # "OS", "rPFS", "MFS", etc.
    times: list[float]  # tiempos en meses
    survival_probs: list[float]  # probabilidades de supervivencia
    n_at_risk: list[int]  # n en riesgo en cada tiempo
    median_survival: float | None  # mediana en meses
    confidence_intervals: list[dict[str, float]] | None = None
    reference_median: float | None = None  # mediana de referencia de ensayos pivotales
    reference_trial: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_type": self.endpoint_type,
            "times": self.times,
            "survival_probs": self.survival_probs,
            "n_at_risk": self.n_at_risk,
            "median_survival": self.median_survival,
            "confidence_intervals": self.confidence_intervals,
            "reference_median": self.reference_median,
            "reference_trial": self.reference_trial,
            "has_data": len(self.times) > 0,
        }


def build_kaplan_meier_chart(
    patients: list[dict[str, Any]],
    endpoint_type: str,
    state_filter: str | None = None,
) -> dict[str, Any]:
    """
    Genera datos Kaplan-Meier para una cohorte de pacientes.
    Delegado al motor de survival_endpoints para el cálculo real.

    Args:
        patients: Lista de registros completos de pacientes.
        endpoint_type: Tipo de endpoint ("OS", "rPFS", "MFS", etc.)
        state_filter: Filtro opcional de estado clínico.

    Returns:
        Dict con datos KM listos para visualización.
    """
    try:
        from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService

        # Compute endpoints for all patients
        all_endpoints = []
        for patient in patients:
            state = (patient.get("latest_assessment") or {}).get("state", "")
            if state_filter and state != state_filter:
                continue
            try:
                status = SurvivalEndpointService.compute_endpoints(patient, state)
                for ep in status.endpoints:
                    if ep.endpoint_type == endpoint_type:
                        all_endpoints.append(ep)
            except Exception:
                continue

        if not all_endpoints:
            return KaplanMeierData(
                endpoint_type=endpoint_type,
                times=[], survival_probs=[], n_at_risk=[],
                median_survival=None,
            ).to_dict()

        # Use the service's built-in KM calculator
        km_data = SurvivalEndpointService.generate_kaplan_meier_points(
            all_endpoints, endpoint_type
        )
        return km_data
    except Exception:
        return KaplanMeierData(
            endpoint_type=endpoint_type,
            times=[], survival_probs=[], n_at_risk=[],
            median_survival=None,
        ).to_dict()
