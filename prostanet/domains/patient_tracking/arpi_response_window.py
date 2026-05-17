"""ARPI Response Window Builder — EPIC 33.B

Calcula snapshots de respuesta a ARPI a ventanas pivotal (2 meses = 8 semanas,
6 meses = 24 semanas). PSA decline + ECOG change desde baseline de la línea
terapéutica.

Council concessions (Critic):
- NO interpolación lineal de PSA (PSA es log-no-lineal). Usar ventana ±14d
  alrededor del target_date. Si no hay PSA en ventana, reportar
  `evidence_quality='no_data'` con `closest_psa_offset_days` metadata.
- NO fabricar ECOG si missing — explícito en evidence_quality.
- `actual_vs_target_window_days` siempre presente para audit trail.

Council concessions (Pragmatist):
- Reusar `build_psa_by_treatment_line` existente (no reimplementar segmentación).
- Reusar `_fact_lookup` para ECOG history.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
from prostanet.shared.utc_time import parse_iso_to_utc, utc_now_iso, utc_today

logger = logging.getLogger(__name__)

# Ventanas pivotal clínicas
WINDOW_WEEKS_2MONTH = 8
WINDOW_WEEKS_6MONTH = 24
DEFAULT_TOLERANCE_DAYS = 14

# Drugs ARPI (canonical drug_scheme tokens)
ARPI_DRUG_TOKENS = (
    "ABIRATERONE", "ABI",
    "ENZALUTAMIDE", "ENZA",
    "APALUTAMIDE", "APA",
    "DAROLUTAMIDE", "DARO",
)


def _is_arpi_regimen(drug_scheme: str) -> bool:
    """True si drug_scheme contiene un ARPI canonical."""
    s = str(drug_scheme or "").upper()
    return any(token in s for token in ARPI_DRUG_TOKENS)


def _classify_arpi(drug_scheme: str) -> str | None:
    """Returns canonical ARPI name from drug_scheme, or None if no ARPI."""
    s = str(drug_scheme or "").upper()
    if "ABIRATERONE" in s or "ABI" in s:
        return "ABIRATERONE"
    if "ENZALUTAMIDE" in s or "ENZA" in s:
        return "ENZALUTAMIDE"
    if "APALUTAMIDE" in s or "APA" in s:
        return "APALUTAMIDE"
    if "DAROLUTAMIDE" in s or "DARO" in s:
        return "DAROLUTAMIDE"
    return None


def _resolve_ecog_at_date(patient: dict[str, Any], target_date: date,
                          tolerance_days: int) -> tuple[int | None, int | None, str]:
    """Find closest ECOG within ±tolerance_days. Returns (value, offset_days, quality_tag).

    Reads from `patient_clinical_facts` history (NOT just is_active) so ECOG values
    set previously can be found. Falls back to follow_ups[].ecog_performance_status
    if no clinical_fact rows.

    Returns: (ecog_value, offset_days_from_target, quality_tag)
        quality_tag ∈ {'in_window', 'closest_outside_window', 'no_data'}
    """
    candidates: list[tuple[date, int]] = []

    # Source 1: clinical_facts (current active value only — schema limitation)
    facts = patient.get("clinical_facts") or patient.get("patient_clinical_facts") or []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if str(f.get("fact_key") or "") != "ecog_performance_status":
            continue
        # Use observed_at or source_date
        d_str = f.get("observed_at") or f.get("source_date") or f.get("updated_at")
        if not d_str:
            continue
        try:
            d_parsed = date.fromisoformat(str(d_str)[:10])
        except (ValueError, TypeError):
            continue
        try:
            ecog_val = int(float(f.get("normalized_value_text") or f.get("value_json") or 0))
        except (TypeError, ValueError):
            continue
        if 0 <= ecog_val <= 4:
            candidates.append((d_parsed, ecog_val))

    # Source 2: follow_ups[].ecog_performance_status
    for fu in patient.get("follow_ups") or []:
        if not isinstance(fu, dict):
            continue
        ecog_raw = fu.get("ecog_performance_status") or fu.get("ecog")
        d_str = fu.get("visit_date") or fu.get("date")
        if ecog_raw is None or not d_str:
            continue
        try:
            ecog_val = int(float(ecog_raw))
            d_parsed = date.fromisoformat(str(d_str)[:10])
            if 0 <= ecog_val <= 4:
                candidates.append((d_parsed, ecog_val))
        except (TypeError, ValueError):
            continue

    if not candidates:
        return (None, None, "no_data")

    # Find closest
    closest = min(candidates, key=lambda c: abs((c[0] - target_date).days))
    offset = (closest[0] - target_date).days
    quality = "in_window" if abs(offset) <= tolerance_days else "closest_outside_window"
    return (closest[1], offset, quality)


def _resolve_baseline_ecog(patient: dict[str, Any], line_start_date: date,
                            window_back_days: int = 30) -> int | None:
    """ECOG at/before line start (within window_back_days)."""
    candidates: list[tuple[date, int]] = []
    facts = patient.get("clinical_facts") or patient.get("patient_clinical_facts") or []
    for f in facts:
        if not isinstance(f, dict) or str(f.get("fact_key") or "") != "ecog_performance_status":
            continue
        d_str = f.get("observed_at") or f.get("source_date") or f.get("updated_at")
        if not d_str:
            continue
        try:
            d_parsed = date.fromisoformat(str(d_str)[:10])
            ecog_val = int(float(f.get("normalized_value_text") or f.get("value_json") or 0))
            if 0 <= ecog_val <= 4 and d_parsed <= line_start_date and \
               (line_start_date - d_parsed).days <= window_back_days:
                candidates.append((d_parsed, ecog_val))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    closest = max(candidates, key=lambda c: c[0])  # most recent before/at line_start
    return closest[1]


def compute_arpi_response_at_window(
    patient: dict[str, Any],
    weeks: int,
    *,
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
) -> dict[str, Any]:
    """Compute ARPI response snapshot at target window (8 or 24 weeks).

    Returns dict with:
      - available: bool
      - regimen_code, regimen_arpi (canonical name)
      - target_weeks, target_date
      - line_start_date
      - baseline_psa, actual_psa, actual_psa_date
      - psa_decline_pct, psa50_response (≥50%), psa90_response (≥90%)
      - baseline_ecog, actual_ecog, ecog_change_from_baseline
      - window_offset_days (actual PSA date - target date)
      - evidence_quality ∈ {'in_window', 'closest_outside_window', 'no_data', 'no_current_line'}
      - computed_at: ISO timestamp
    """
    monitoring = build_psa_by_treatment_line(patient)
    if not monitoring.get("has_data"):
        return {
            "available": False,
            "evidence_quality": "no_current_line",
            "reason": "No hay PSA timeline ni line_segments documentados.",
            "computed_at": utc_now_iso(),
        }
    line_segments = monitoring.get("line_segments") or []
    if not line_segments:
        return {
            "available": False,
            "evidence_quality": "no_current_line",
            "reason": "Sin treatment lines documentadas.",
            "computed_at": utc_now_iso(),
        }
    # Buscar la última línea ARPI (current_line)
    current_arpi_line = None
    for segment in reversed(line_segments):
        drug_scheme = segment.get("drug_scheme") or segment.get("label") or ""
        if _is_arpi_regimen(drug_scheme):
            current_arpi_line = segment
            break
    if not current_arpi_line:
        return {
            "available": False,
            "evidence_quality": "no_arpi_line",
            "reason": "Paciente no en línea ARPI actual.",
            "computed_at": utc_now_iso(),
        }

    drug_scheme = str(current_arpi_line.get("drug_scheme") or current_arpi_line.get("label") or "")
    regimen_arpi = _classify_arpi(drug_scheme)
    start_date_str = current_arpi_line.get("start_date")
    if not start_date_str:
        return {
            "available": False,
            "evidence_quality": "no_start_date",
            "reason": "Línea ARPI sin start_date documentado.",
            "computed_at": utc_now_iso(),
        }
    try:
        line_start_date = date.fromisoformat(str(start_date_str)[:10])
    except (ValueError, TypeError):
        return {
            "available": False,
            "evidence_quality": "invalid_start_date",
            "reason": f"start_date {start_date_str} no parsable.",
            "computed_at": utc_now_iso(),
        }

    target_date = line_start_date + timedelta(weeks=weeks)
    today = utc_today()
    if target_date > today + timedelta(days=tolerance_days):
        return {
            "available": False,
            "evidence_quality": "target_in_future",
            "reason": f"Target date {target_date.isoformat()} aún no alcanzado.",
            "target_date": target_date.isoformat(),
            "days_until_target": (target_date - today).days,
            "computed_at": utc_now_iso(),
        }

    # Buscar PSA en ventana [target_date ± tolerance_days]
    points_by_line = monitoring.get("points_by_line") or {}
    line_number = current_arpi_line.get("line_of_therapy_number")
    line_points = []
    if line_number is not None:
        line_points = points_by_line.get(str(line_number)) or []
    # Fallback: filter from all points by date range within line
    if not line_points:
        for p in monitoring.get("points") or []:
            if not isinstance(p, dict):
                continue
            p_date_str = p.get("date") or p.get("sample_date")
            if not p_date_str:
                continue
            try:
                p_date = date.fromisoformat(str(p_date_str)[:10])
            except (ValueError, TypeError):
                continue
            if p_date >= line_start_date:
                line_points.append({**p, "_date_obj": p_date})

    # Buscar PSA en ventana
    in_window: list[tuple[date, float]] = []
    closest_outside: tuple[date, float, int] | None = None  # (date, value, offset_days)
    for p in line_points:
        p_date_str = p.get("date") or p.get("sample_date")
        if not p_date_str:
            continue
        try:
            p_date = date.fromisoformat(str(p_date_str)[:10])
            p_psa = float(p.get("psa") or p.get("value") or p.get("psa_value") or 0)
        except (TypeError, ValueError):
            continue
        if p_psa <= 0:
            continue
        offset = (p_date - target_date).days
        if abs(offset) <= tolerance_days:
            in_window.append((p_date, p_psa))
        else:
            if closest_outside is None or abs(offset) < abs(closest_outside[2]):
                closest_outside = (p_date, p_psa, offset)

    if in_window:
        # Take closest to target_date
        actual_psa_date, actual_psa = min(in_window, key=lambda x: abs((x[0] - target_date).days))
        window_offset_days = (actual_psa_date - target_date).days
        evidence_quality = "in_window"
    elif closest_outside is not None:
        actual_psa_date, actual_psa, window_offset_days = closest_outside
        evidence_quality = "closest_outside_window"
    else:
        actual_psa_date = None
        actual_psa = None
        window_offset_days = None
        evidence_quality = "no_data"

    # Baseline PSA = PSA at/around line_start_date
    baseline_psa_raw = current_arpi_line.get("baseline_psa")
    try:
        baseline_psa = float(baseline_psa_raw) if baseline_psa_raw is not None else None
    except (TypeError, ValueError):
        baseline_psa = None

    psa_decline_pct = None
    psa50_response = None
    psa90_response = None
    if baseline_psa is not None and baseline_psa > 0 and actual_psa is not None:
        psa_decline_pct = round((1.0 - actual_psa / baseline_psa) * 100, 2)
        psa50_response = psa_decline_pct >= 50.0
        psa90_response = psa_decline_pct >= 90.0

    # ECOG
    baseline_ecog = _resolve_baseline_ecog(patient, line_start_date)
    actual_ecog, ecog_offset_days, ecog_quality = _resolve_ecog_at_date(
        patient, target_date, tolerance_days,
    )
    ecog_change = None
    if baseline_ecog is not None and actual_ecog is not None:
        ecog_change = actual_ecog - baseline_ecog

    return {
        "available": True,
        "regimen_code": drug_scheme,
        "regimen_arpi": regimen_arpi,
        "target_weeks": weeks,
        "target_date": target_date.isoformat(),
        "line_start_date": line_start_date.isoformat(),
        "line_of_therapy_number": line_number,
        "baseline_psa": baseline_psa,
        "actual_psa": actual_psa,
        "actual_psa_date": actual_psa_date.isoformat() if actual_psa_date else None,
        "psa_decline_pct": psa_decline_pct,
        "psa50_response": psa50_response,
        "psa90_response": psa90_response,
        "baseline_ecog": baseline_ecog,
        "actual_ecog": actual_ecog,
        "ecog_change_from_baseline": ecog_change,
        "ecog_evidence_quality": ecog_quality,
        "ecog_offset_days": ecog_offset_days,
        "window_offset_days": window_offset_days,
        "evidence_quality": evidence_quality,
        "tolerance_days": tolerance_days,
        "computed_at": utc_now_iso(),
    }


__all__ = [
    "compute_arpi_response_at_window",
    "WINDOW_WEEKS_2MONTH",
    "WINDOW_WEEKS_6MONTH",
    "DEFAULT_TOLERANCE_DAYS",
    "_classify_arpi",
    "_is_arpi_regimen",
]
