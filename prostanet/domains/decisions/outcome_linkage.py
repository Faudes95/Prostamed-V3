"""outcome_linkage.py — EPIC 48.C (FAUBOT CXXXVI).

Vincula `clinical_decision_event` (recomendación o override) a outcomes
observados a 3/6/12 meses. Closure del bucle clínico completo:

  decision → outcome → feedback to engine → recalibration

Reusa el trajectory_engine existente (EPIC 47) para extraer outcomes
observados. NO duplica lógica de PSA/ECOG/ALP/LDH tracking.

Outcomes computados por ventana temporal (3m, 6m, 12m post-decisión):
  - PSA response: % cambio desde valor en decision_date
    Categorías: response (-50%↓), stable (-10% a +25%), progression (>+25%)
  - ECOG: cambio absoluto desde decision_date
    Categorías: improved, stable, declined, severe_decline
  - ALP trend: % cambio
  - Time to next clinical event (visita, alerta crítica)
  - Toxicity events count (CTCAE si capturado)
  - Drug continuation status (still on therapy / discontinued / switched)

Foundation para:
  - Engine learning loop: "decisiones X dieron outcomes Y en N% de casos"
  - Real-world evidence: "validación CHAARTED low-vol en cohorte latina"
  - SaMD post-market surveillance (FDA/COFEPRIS regulatorio)
  - Publications: KM/Cox stratified por decision pattern
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def build_outcome_linkage(
    patient: dict[str, Any] | None,
    decision_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye outcome linkage para una decisión clínica específica.

    Args:
        patient: full patient record (debe incluir biomarker_longitudinal +
            follow_ups + treatments)
        decision_event: optional dict {decided_at, recommended_label,
            override_label, recommendation_source}. Si None, usa el último
            override_event o el último treatment_start_date como anchor.

    Returns:
        {
            "available": bool,
            "decision_anchor": {
                "decided_at": ISO,
                "label": str,
                "source": str,
            },
            "outcomes_3m": {...},
            "outcomes_6m": {...},
            "outcomes_12m": {...},
            "summary": {
                "any_window_complete": bool,
                "best_response_window": "3m" | "6m" | "12m" | null,
                "best_response_category": "response" | "stable" | "progression" | null,
            },
            "linkage_version": "epic48_v1.0",
        }
    """
    if not patient or not isinstance(patient, dict):
        return _empty_linkage(reason="no_patient_data")

    # Resolve decision anchor (decision_event > último override > último treatment)
    anchor = _resolve_decision_anchor(patient, decision_event)
    if not anchor:
        return _empty_linkage(reason="no_decision_anchor")

    decided_at = _parse_date(anchor["decided_at"])
    if not decided_at:
        return _empty_linkage(reason="invalid_decided_at")

    # Build trajectory baseline UP TO decision_date (excluye observaciones POST)
    baseline_state = _capture_baseline_at(patient, decided_at)

    # Compute outcomes for each window
    outcomes_3m = _compute_outcomes_in_window(patient, baseline_state, decided_at, months=3)
    outcomes_6m = _compute_outcomes_in_window(patient, baseline_state, decided_at, months=6)
    outcomes_12m = _compute_outcomes_in_window(patient, baseline_state, decided_at, months=12)

    # Summary
    summary = _build_outcomes_summary(outcomes_3m, outcomes_6m, outcomes_12m)

    return {
        "available": True,
        "decision_anchor": anchor,
        "baseline_at_decision": baseline_state,
        "outcomes_3m": outcomes_3m,
        "outcomes_6m": outcomes_6m,
        "outcomes_12m": outcomes_12m,
        "summary": summary,
        "linkage_version": "epic48_v1.0",
    }


# ─────────────────────────────────────────────────────────────────────
# Anchor resolution
# ─────────────────────────────────────────────────────────────────────


def _resolve_decision_anchor(
    patient: dict[str, Any],
    decision_event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Identifica el evento de decisión que ancla los outcomes."""
    # Explicit decision_event prevalece
    if decision_event and isinstance(decision_event, dict):
        decided_at = decision_event.get("decided_at")
        label = (
            decision_event.get("override_label")
            or decision_event.get("recommended_label")
            or decision_event.get("label")
        )
        if decided_at and label:
            return {
                "decided_at": str(decided_at),
                "label": str(label),
                "source": str(decision_event.get("recommendation_source") or "explicit"),
                "is_override": bool(decision_event.get("override_label")),
            }

    # Fallback: último treatment_start_date
    treatments = patient.get("treatments") or []
    if isinstance(treatments, list) and treatments:
        valid = [
            t for t in treatments
            if isinstance(t, dict) and t.get("start_date")
        ]
        if valid:
            latest = max(valid, key=lambda t: str(t.get("start_date", "")))
            label = str(
                latest.get("regimen_name")
                or latest.get("scheme")
                or latest.get("class")
                or "tratamiento"
            )
            return {
                "decided_at": str(latest.get("start_date")),
                "label": label,
                "source": "latest_treatment_event",
                "is_override": False,
            }
    return None


def _parse_date(date_str: Any) -> datetime | None:
    if not date_str:
        return None
    try:
        s = str(date_str)[:10]
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        try:
            # ISO with timestamp
            return datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────────────────────────────
# Baseline + window outcomes
# ─────────────────────────────────────────────────────────────────────


def _capture_baseline_at(
    patient: dict[str, Any],
    anchor_date: datetime,
) -> dict[str, Any]:
    """Captura valores PSA / ECOG / ALP / LDH en o antes del anchor_date.
    Usa la última observación previa o igual al anchor."""
    biomarkers = patient.get("biomarker_longitudinal") or []
    visits = patient.get("follow_ups") or patient.get("follow_up_visits") or []

    psa_baseline = _last_value_before(biomarkers, "PSA", anchor_date)
    alp_baseline = _last_value_before(biomarkers, "ALP", anchor_date)
    ldh_baseline = _last_value_before(biomarkers, "LDH", anchor_date)
    ecog_baseline = _last_ecog_before(visits, anchor_date) or _baseline_ecog(patient)

    return {
        "psa": psa_baseline,
        "ecog": ecog_baseline,
        "alp": alp_baseline,
        "ldh": ldh_baseline,
        "anchor_date_iso": anchor_date.isoformat()[:10],
    }


def _last_value_before(
    biomarkers: list,
    biomarker_type: str,
    anchor_date: datetime,
) -> dict[str, Any] | None:
    if not isinstance(biomarkers, list):
        return None
    candidates = []
    for b in biomarkers:
        if not isinstance(b, dict):
            continue
        if str(b.get("biomarker_type") or "").upper() != biomarker_type.upper():
            continue
        bd = _parse_date(b.get("sample_date") or b.get("created_at"))
        if bd is None or bd > anchor_date:
            continue
        try:
            value = float(b.get("value"))
        except (ValueError, TypeError):
            continue
        candidates.append((bd, value))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    last_date, last_value = candidates[-1]
    return {"value": last_value, "date": last_date.isoformat()[:10]}


def _last_ecog_before(visits: list, anchor_date: datetime) -> dict[str, Any] | None:
    if not isinstance(visits, list):
        return None
    candidates = []
    for v in visits:
        if not isinstance(v, dict):
            continue
        ecog = v.get("ecog_current") or v.get("ecog")
        if ecog is None:
            continue
        vd = _parse_date(v.get("visit_date") or v.get("date"))
        if vd is None or vd > anchor_date:
            continue
        try:
            candidates.append((vd, int(ecog)))
        except (ValueError, TypeError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    last_date, last_value = candidates[-1]
    return {"value": last_value, "date": last_date.isoformat()[:10]}


def _baseline_ecog(patient: dict[str, Any]) -> dict[str, Any] | None:
    baseline = patient.get("baseline") or {}
    if not isinstance(baseline, dict):
        return None
    ecog = baseline.get("ecog") or baseline.get("ecog_score")
    if ecog is None:
        return None
    try:
        return {"value": int(ecog), "date": str(baseline.get("diagnosis_date") or "")[:10]}
    except (ValueError, TypeError):
        return None


def _compute_outcomes_in_window(
    patient: dict[str, Any],
    baseline: dict[str, Any],
    anchor_date: datetime,
    months: int,
) -> dict[str, Any]:
    """Computa outcomes observed dentro de la ventana [anchor, anchor+months]."""
    window_end = anchor_date + timedelta(days=int(months * 30.4375))
    biomarkers = patient.get("biomarker_longitudinal") or []
    visits = patient.get("follow_ups") or patient.get("follow_up_visits") or []

    # Latest observations within window
    psa_latest = _latest_in_window(biomarkers, "PSA", anchor_date, window_end)
    alp_latest = _latest_in_window(biomarkers, "ALP", anchor_date, window_end)
    ldh_latest = _latest_in_window(biomarkers, "LDH", anchor_date, window_end)
    ecog_latest = _latest_ecog_in_window(visits, anchor_date, window_end)

    # Compute changes vs baseline
    psa_change_pct = _pct_change(baseline.get("psa"), psa_latest)
    alp_change_pct = _pct_change(baseline.get("alp"), alp_latest)
    ldh_change_pct = _pct_change(baseline.get("ldh"), ldh_latest)
    ecog_delta = _ecog_delta(baseline.get("ecog"), ecog_latest)

    # Categorize PSA response
    psa_category = _categorize_psa_response(psa_change_pct)
    ecog_category = _categorize_ecog_change(ecog_delta)

    # Window data availability
    data_available = bool(psa_latest or alp_latest or ldh_latest or ecog_latest)

    return {
        "window_months": months,
        "window_end_iso": window_end.isoformat()[:10],
        "data_available": data_available,
        "psa": {
            "baseline": (baseline.get("psa") or {}).get("value") if baseline.get("psa") else None,
            "latest": psa_latest["value"] if psa_latest else None,
            "latest_date": psa_latest["date"] if psa_latest else None,
            "change_pct": psa_change_pct,
            "category": psa_category,
        },
        "ecog": {
            "baseline": (baseline.get("ecog") or {}).get("value") if baseline.get("ecog") else None,
            "latest": ecog_latest["value"] if ecog_latest else None,
            "latest_date": ecog_latest["date"] if ecog_latest else None,
            "delta": ecog_delta,
            "category": ecog_category,
        },
        "alp": {
            "baseline": (baseline.get("alp") or {}).get("value") if baseline.get("alp") else None,
            "latest": alp_latest["value"] if alp_latest else None,
            "change_pct": alp_change_pct,
        },
        "ldh": {
            "baseline": (baseline.get("ldh") or {}).get("value") if baseline.get("ldh") else None,
            "latest": ldh_latest["value"] if ldh_latest else None,
            "change_pct": ldh_change_pct,
        },
    }


def _latest_in_window(
    biomarkers: list,
    biomarker_type: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    if not isinstance(biomarkers, list):
        return None
    candidates = []
    for b in biomarkers:
        if not isinstance(b, dict):
            continue
        if str(b.get("biomarker_type") or "").upper() != biomarker_type.upper():
            continue
        bd = _parse_date(b.get("sample_date") or b.get("created_at"))
        if bd is None or bd <= start or bd > end:
            continue
        try:
            candidates.append((bd, float(b.get("value"))))
        except (ValueError, TypeError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    last_date, last_value = candidates[-1]
    return {"value": last_value, "date": last_date.isoformat()[:10]}


def _latest_ecog_in_window(
    visits: list,
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    if not isinstance(visits, list):
        return None
    candidates = []
    for v in visits:
        if not isinstance(v, dict):
            continue
        ecog = v.get("ecog_current") or v.get("ecog")
        if ecog is None:
            continue
        vd = _parse_date(v.get("visit_date") or v.get("date"))
        if vd is None or vd <= start or vd > end:
            continue
        try:
            candidates.append((vd, int(ecog)))
        except (ValueError, TypeError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    last_date, last_value = candidates[-1]
    return {"value": last_value, "date": last_date.isoformat()[:10]}


def _pct_change(baseline: dict[str, Any] | None, latest: dict[str, Any] | None) -> float | None:
    if not baseline or not latest:
        return None
    b = baseline.get("value")
    l = latest.get("value") if isinstance(latest, dict) else None
    if b is None or l is None or b == 0:
        return None
    return round(((l - b) / b) * 100, 1)


def _ecog_delta(baseline: dict[str, Any] | None, latest: dict[str, Any] | None) -> int | None:
    if not baseline or not latest:
        return None
    b = baseline.get("value")
    l = latest.get("value") if isinstance(latest, dict) else None
    if b is None or l is None:
        return None
    return int(l) - int(b)


def _categorize_psa_response(pct: float | None) -> str | None:
    """PCWG3-aligned categories simplified."""
    if pct is None:
        return None
    if pct <= -50:
        return "response_major"        # ≥50% reduction = major response
    if pct <= -10:
        return "response_minor"
    if pct <= 25:
        return "stable"
    return "progression"               # >25% increase = PCWG3 progression criterion


def _categorize_ecog_change(delta: int | None) -> str | None:
    if delta is None:
        return None
    if delta <= -1:
        return "improved"
    if delta == 0:
        return "stable"
    if delta == 1:
        return "declined"
    return "severe_decline"            # delta >=2


def _build_outcomes_summary(
    o3: dict[str, Any],
    o6: dict[str, Any],
    o12: dict[str, Any],
) -> dict[str, Any]:
    """Identifica best response window + categoría agregada."""
    windows = [("3m", o3), ("6m", o6), ("12m", o12)]
    # Find best PSA response across windows
    best_response: dict[str, Any] | None = None
    response_priority = {
        "response_major": 4, "response_minor": 3,
        "stable": 2, "progression": 1, None: 0,
    }
    for label, w in windows:
        if not w.get("data_available"):
            continue
        cat = (w.get("psa") or {}).get("category")
        prio = response_priority.get(cat, 0)
        if best_response is None or prio > best_response["prio"]:
            best_response = {"window": label, "category": cat, "prio": prio}

    return {
        "any_window_complete": any(w.get("data_available") for _, w in windows),
        "best_response_window": (best_response or {}).get("window"),
        "best_response_category": (best_response or {}).get("category"),
    }


def _empty_linkage(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "decision_anchor": None,
        "outcomes_3m": {"data_available": False},
        "outcomes_6m": {"data_available": False},
        "outcomes_12m": {"data_available": False},
        "summary": {"any_window_complete": False},
        "linkage_version": "epic48_v1.0",
    }


__all__ = ["build_outcome_linkage"]
