"""PSA Unified Source of Truth (LXC fix B1).

PSA es el marcador por excelencia en cáncer de próstata. Antes de LXC, PSA se
capturaba en 3 lugares con shapes diferentes:
  1. intake (baseline_psa snapshot single)
  2. biomarker_longitudinal (table con history)
  3. clinical_assessments.clinical_summary (text)

Esto causaba:
  - source-of-truth ambigua → recompute con valor stale
  - PSADT cálculo inconsistente
  - gate 53/54/55 disparo intermitente

LXC fix: **biomarker_longitudinal es la ÚNICA fuente autoritativa**.

API:
    timeline = unified_psa_timeline(patient_record) → list[dict]
    latest = latest_psa_value(patient_record) → {value, date, assay, source}
    nadir = psa_nadir(patient_record) → {value, date}
    ensure_baseline_seeded(patient_record) → idempotent: si baseline_psa existe pero
        no está en biomarker_longitudinal, lo agrega como primer punto locked.

Filosofía:
- baseline_psa en intake → auto-seed como punto 0 con source="intake_baseline" + locked=True
- biomarker_longitudinal = autoritativa para queries downstream (PSADT, kinetics, forecast)
- clinical_assessments.clinical_summary = solo display/FYI, NO source
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def unified_psa_timeline(patient_record: dict) -> list[dict[str, Any]]:
    """Return single source-of-truth PSA timeline (sorted by date).

    Semantics:
      - First, ensure baseline_psa is seeded into biomarker_longitudinal (idempotent).
      - Then return all PSA points from biomarker_longitudinal sorted asc.
      - Each point: {date, value, assay, context, source, locked}.

    Si patient_record no tiene biomarker_longitudinal pero sí baseline_psa,
    retorna list con 1 punto seed.
    """
    if not isinstance(patient_record, dict):
        return []

    biomarkers = patient_record.get("biomarker_longitudinal") or []
    psa_points = []

    # Filter PSA points only
    for bm in biomarkers:
        if not isinstance(bm, dict):
            continue
        bm_type = (bm.get("biomarker_type") or "").upper()
        if bm_type != "PSA":
            continue
        psa_points.append({
            "date": bm.get("sample_date") or bm.get("date"),
            "value": _safe_float(bm.get("value") or bm.get("psa_value")),
            "assay": bm.get("assay") or "Beckman_Hybritech_default",
            "context": bm.get("clinical_context") or bm.get("context") or "longitudinal",
            "source": bm.get("source") or "biomarker_longitudinal",
            "locked": bool(bm.get("locked", False)),
        })

    # Seed baseline_psa as point 0 if missing (idempotent)
    baseline = patient_record.get("baseline") or patient_record.get("clinical_baseline") or {}
    base_psa = _safe_float(baseline.get("baseline_psa") or baseline.get("psa"))
    identity = patient_record.get("identity") or {}
    diagnosis_date = identity.get("diagnosis_date") or baseline.get("diagnosis_date")

    if base_psa and base_psa > 0 and diagnosis_date:
        # Check if already in timeline (within 7-day window of diagnosis_date)
        already_seeded = False
        try:
            dx_dt = datetime.fromisoformat(str(diagnosis_date)[:10])
            for p in psa_points:
                if p["value"] == base_psa and p["date"]:
                    try:
                        p_dt = datetime.fromisoformat(str(p["date"])[:10])
                        if abs((p_dt - dx_dt).days) <= 7:
                            already_seeded = True
                            break
                    except (ValueError, TypeError):
                        pass
        except (ValueError, TypeError):
            pass

        if not already_seeded:
            psa_points.insert(0, {
                "date": str(diagnosis_date)[:10],
                "value": base_psa,
                "assay": baseline.get("psa_assay") or "Beckman_Hybritech_default",
                "context": "Basal Dx (intake)",
                "source": "intake_baseline (auto-seed unified)",
                "locked": True,
            })

    # Sort ascending by date
    psa_points.sort(key=lambda p: str(p.get("date") or ""))
    return psa_points


def latest_psa_value(patient_record: dict) -> dict[str, Any] | None:
    """Latest PSA point from unified timeline."""
    timeline = unified_psa_timeline(patient_record)
    if not timeline:
        return None
    valid = [p for p in timeline if p.get("value") is not None and p.get("date")]
    return valid[-1] if valid else None


def unified_testosterone_timeline(patient_record: dict) -> list[dict[str, Any]]:
    """Return testosterone timeline using the same longitudinal rules as PSA.

    Testosterone is decisive for CRPC classification: a rising PSA without a
    castrate testosterone value must remain in verification, not in confirmed
    m0/m1 CRPC. This helper keeps baseline and follow-up values visible to the
    same surveillance surfaces that consume PSA.
    """
    if not isinstance(patient_record, dict):
        return []

    biomarkers = patient_record.get("biomarker_longitudinal") or []
    points: list[dict[str, Any]] = []
    for bm in biomarkers:
        if not isinstance(bm, dict):
            continue
        bm_type = (bm.get("biomarker_type") or "").upper()
        if bm_type not in {"TESTOSTERONA", "TESTOSTERONE"}:
            continue
        points.append({
            "date": bm.get("sample_date") or bm.get("date"),
            "value": _safe_float(bm.get("value") or bm.get("testosterone_value")),
            "unit": bm.get("unit") or "ng/dL",
            "assay": bm.get("assay") or "no_especificado",
            "context": bm.get("clinical_context") or bm.get("context") or "longitudinal",
            "source": bm.get("source") or "biomarker_longitudinal",
            "locked": bool(bm.get("locked", False)),
        })

    baseline = patient_record.get("baseline") or patient_record.get("clinical_baseline") or {}
    base_testosterone = _safe_float(
        baseline.get("testosterone_baseline")
        or baseline.get("baseline_testosterone")
        or baseline.get("testosterone")
    )
    identity = patient_record.get("identity") or {}
    diagnosis_date = identity.get("diagnosis_date") or baseline.get("diagnosis_date")
    if base_testosterone and base_testosterone > 0 and diagnosis_date:
        already_seeded = False
        try:
            dx_dt = datetime.fromisoformat(str(diagnosis_date)[:10])
            for p in points:
                if p["value"] == base_testosterone and p["date"]:
                    try:
                        p_dt = datetime.fromisoformat(str(p["date"])[:10])
                        if abs((p_dt - dx_dt).days) <= 7:
                            already_seeded = True
                            break
                    except (ValueError, TypeError):
                        pass
        except (ValueError, TypeError):
            pass
        if not already_seeded:
            points.insert(0, {
                "date": str(diagnosis_date)[:10],
                "value": base_testosterone,
                "unit": baseline.get("testosterone_unit") or "ng/dL",
                "assay": baseline.get("testosterone_assay") or "no_especificado",
                "context": "Basal Dx (intake)",
                "source": "intake_baseline (auto-seed unified)",
                "locked": True,
            })

    points.sort(key=lambda p: str(p.get("date") or ""))
    return points


def latest_testosterone_value(patient_record: dict) -> dict[str, Any] | None:
    """Latest testosterone point from unified timeline."""
    timeline = unified_testosterone_timeline(patient_record)
    if not timeline:
        return None
    valid = [p for p in timeline if p.get("value") is not None and p.get("date")]
    return valid[-1] if valid else None


def psa_nadir(patient_record: dict, *, since_treatment_start: bool = True) -> dict[str, Any] | None:
    """Lowest PSA value (post-treatment if since_treatment_start=True).

    Used for BCR Phoenix definition (PSA ≥ nadir + 2).
    """
    timeline = unified_psa_timeline(patient_record)
    if not timeline:
        return None

    valid = [p for p in timeline if p.get("value") is not None and p.get("date")]
    if not valid:
        return None

    if since_treatment_start:
        # Find earliest treatment start date
        treatments = patient_record.get("treatments") or []
        earliest_tx = None
        for tx in treatments:
            if isinstance(tx, dict):
                tx_start = tx.get("start_date")
                if tx_start:
                    try:
                        d = datetime.fromisoformat(str(tx_start)[:10])
                        if earliest_tx is None or d < earliest_tx:
                            earliest_tx = d
                    except (ValueError, TypeError):
                        pass
        if earliest_tx:
            valid = [p for p in valid
                     if _try_parse_date(p["date"]) and _try_parse_date(p["date"]) >= earliest_tx]

    if not valid:
        return None
    nadir = min(valid, key=lambda p: p["value"])
    return nadir


def is_psa_increasing(patient_record: dict, *, lookback_points: int = 3) -> bool:
    """Returns True if last N points show monotonic increase (any deviation = False)."""
    timeline = unified_psa_timeline(patient_record)
    valid = [p for p in timeline if p.get("value") is not None]
    if len(valid) < lookback_points:
        return False
    last_n = valid[-lookback_points:]
    for i in range(1, len(last_n)):
        if last_n[i]["value"] <= last_n[i-1]["value"]:
            return False
    return True


def psa_doubling_time_months(patient_record: dict) -> dict[str, Any]:
    """Convenience wrapper: PSADT from unified timeline using auto_derive_helpers.

    Returns same shape as derive_psadt() but uses the unified source.
    """
    from prostanet.shared.auto_derive_helpers import derive_psadt
    timeline = unified_psa_timeline(patient_record)
    # Convert to format expected by derive_psadt
    history = [{"sample_date": p["date"], "value": p["value"]} for p in timeline
               if p.get("date") and p.get("value") is not None]
    result = derive_psadt(history)
    result["source"] = "psa_unified.py · biomarker_longitudinal authoritative"
    result["n_points_unified"] = len(history)
    return result


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _try_parse_date(d: Any) -> datetime | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(str(d)[:10])
    except (ValueError, TypeError):
        return None
