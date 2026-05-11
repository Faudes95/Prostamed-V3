"""Auto-derive helpers (LXC) — calcula valores derivables y los expone al UI.

Filosofía: el clínico NO debe re-calcular lo que la lógica ya sabe. Cada helper
toma el patient record + retorna un dict con value + computation_basis (string)
para tooltips read-only en UI.

Helpers:
  - derive_isup_grade(gleason_p, gleason_s) → ISUP 1-5
  - derive_psadt(psa_history) → meses (Stephenson method)
  - derive_charlson_score(comorbidities_dict) → score + age_adjusted
  - derive_g8_score(age, ecog, nutrition, polypharmacy, weight_loss, ...)
  - derive_frailty_status(age, ecog, charlson) → robust/pre-frail/frail/incomplete
  - derive_bcr_phoenix(psa_nadir, psa_current) → True if PSA ≥ nadir + 2
  - derive_creatinine_clearance(creat, age, weight, sex) → mL/min Cockcroft
  - derive_disease_free_interval(diagnosis_date, mets_diagnosis_date) → months
  - derive_age(dob) → years
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def derive_isup_grade(gleason_p: int | str | None,
                       gleason_s: int | str | None) -> dict[str, Any]:
    """ISUP grade per WHO/ISUP 2014. Returns {value, basis, valid}."""
    try:
        p = int(gleason_p) if gleason_p is not None else None
        s = int(gleason_s) if gleason_s is not None else None
    except (TypeError, ValueError):
        return {"value": None, "basis": "Invalid Gleason inputs", "valid": False}

    if p is None or s is None:
        return {"value": None, "basis": "Gleason primary + secondary required", "valid": False}
    if p < 3 or s < 3 or p > 5 or s > 5:
        return {"value": None, "basis": f"Gleason {p}+{s}: rejected by ISUP 2014 (only 3-5 valid)", "valid": False}

    total = p + s
    if total <= 6:
        isup = 1
    elif p == 3 and s == 4:
        isup = 2
    elif p == 4 and s == 3:
        isup = 3
    elif total == 8:
        isup = 4
    else:  # 9, 10
        isup = 5
    return {"value": isup, "basis": f"Gleason {p}+{s}={total} → ISUP {isup}", "valid": True}


def derive_psadt(psa_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    """PSA doubling time (Stephenson method, log-linear).

    Returns {value_months, basis, n_points, valid}.
    Need ≥3 PSA points spanning ≥3 months for reliable PSADT.
    """
    if not psa_history or len(psa_history) < 3:
        return {"value_months": None, "basis": "Need ≥3 PSA points",
                "n_points": len(psa_history) if psa_history else 0, "valid": False}

    # Sort by date, get values + dates
    points = []
    for p in psa_history:
        try:
            d_str = p.get("sample_date") or p.get("date")
            d = datetime.fromisoformat(str(d_str)[:10]) if d_str else None
            v = float(p.get("value") or p.get("psa_value") or 0)
            if d and v > 0:
                points.append((d, v))
        except (ValueError, TypeError):
            continue

    if len(points) < 3:
        return {"value_months": None, "basis": "Need ≥3 valid PSA points after filtering",
                "n_points": len(points), "valid": False}

    points.sort(key=lambda x: x[0])
    # Time span in months
    months_span = (points[-1][0] - points[0][0]).days / 30.44
    if months_span < 3.0:
        return {"value_months": None, "basis": f"Time span only {months_span:.1f}m, need ≥3",
                "n_points": len(points), "valid": False}

    # Log-linear regression: log(PSA) vs months
    t0 = points[0][0]
    xs = [(d - t0).days / 30.44 for d, _v in points]
    ys = [math.log(v) for _d, v in points]
    n = len(xs)
    sum_x = sum(xs); sum_y = sum(ys)
    sum_xx = sum(x*x for x in xs); sum_xy = sum(x*y for x, y in zip(xs, ys))
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-9:
        return {"value_months": None, "basis": "Singular regression",
                "n_points": n, "valid": False}
    slope = (n * sum_xy - sum_x * sum_y) / denom  # log(PSA)/month

    if slope <= 0:
        return {"value_months": None,
                "basis": f"PSA decreasing/stable (slope={slope:.4f}); PSADT undefined",
                "n_points": n, "valid": True, "trajectory": "stable_or_decreasing"}

    psadt_months = math.log(2) / slope
    return {
        "value_months": round(psadt_months, 1),
        "basis": f"Stephenson log-linear regression on {n} points over {months_span:.1f}m",
        "n_points": n,
        "valid": True,
        "trajectory": "increasing",
    }


CHARLSON_WEIGHTS = {
    "myocardial_infarction": 1, "congestive_heart_failure": 1,
    "peripheral_vascular_disease": 1, "cerebrovascular_disease": 1,
    "dementia": 1, "chronic_pulmonary_disease": 1,
    "rheumatic_disease": 1, "peptic_ulcer_disease": 1,
    "mild_liver_disease": 1, "diabetes_no_complications": 1,
    "diabetes_with_complications": 2, "hemiplegia_paraplegia": 2,
    "renal_disease": 2, "any_malignancy": 2,
    "moderate_severe_liver_disease": 3, "metastatic_solid_tumor": 6,
    "aids_hiv": 6,
    # Common shorthand (mapped → above):
    "htn": 0, "diabetes": 1, "ihd": 1, "copd": 1, "ckd": 2,
}


def derive_charlson_score(comorbidities: dict[str, Any] | list,
                            age: int | None = None) -> dict[str, Any]:
    """Charlson Comorbidity Index + age adjustment.

    Accepts dict (key→bool/yes) or list of strings.
    """
    if isinstance(comorbidities, list):
        comorb_set = {str(c).lower() for c in comorbidities}
    elif isinstance(comorbidities, dict):
        comorb_set = {k for k, v in comorbidities.items()
                      if v in (1, True, "1", "true", "yes", "Yes")}
    else:
        return {"value": 0, "age_adjusted": 0, "basis": "Invalid comorbidities input", "valid": False}

    base = sum(CHARLSON_WEIGHTS.get(c, 0) for c in comorb_set)
    age_points = 0
    if age and age >= 50:
        age_points = min((age - 40) // 10, 4)  # +1 per decade ≥50 (cap 4)

    return {
        "value": base,
        "age_adjusted": base + age_points,
        "age_points": age_points,
        "basis": f"Charlson = Σ comorbidities ({len(comorb_set)}) + age decades = {base} + {age_points}",
        "valid": True,
    }


def derive_g8_score(*, age: int | None, ecog: int | None,
                     weight_loss_recent: bool = False,
                     bmi: float | None = None,
                     polypharmacy: bool = False,
                     mood_low: bool = False,
                     ate_well: bool = True,
                     mobility_ok: bool = True,
                     cognition_ok: bool = True) -> dict[str, Any]:
    """G8 Geriatric Screening (0-17). ≤14 = positive screen for CGA referral."""
    if age is None:
        return {"value": None, "basis": "Age required", "valid": False}
    score = 0
    # Age scoring: 0 = ≥86, 1 = 80-85, 2 = <80
    score += 0 if age >= 86 else (1 if age >= 80 else 2)
    # Weight loss past 3mo: 0=>3kg, 1=unsure, 2=1-3kg, 3=no loss
    score += 0 if weight_loss_recent else 3
    # BMI: 0=<19, 1=19-21, 2=21-23, 3=≥23
    if bmi is None:
        score += 2
    elif bmi >= 23:
        score += 3
    elif bmi >= 21:
        score += 2
    elif bmi >= 19:
        score += 1
    # Polypharmacy: 0=>3 drugs, 1=≤3
    score += 0 if polypharmacy else 1
    # Mood: 0=apathy, 1=depression, 2=neither
    score += 0 if mood_low else 2
    # Eats well: 0=severe, 1=moderate, 2=normal
    score += 2 if ate_well else 0
    # Mobility: 0=bed/chair, 1=wheelchair, 2=walks
    score += 2 if mobility_ok else 0
    # Cognition: 0=severe, 1=mild, 2=normal
    score += 2 if cognition_ok else 0
    # ECOG: 0=4, 1=3, 2=1-2, 3=0
    if ecog is not None:
        score += 0 if ecog == 4 else (1 if ecog == 3 else (2 if ecog >= 1 else 3))

    # Cap at 17 (standard G8 maximum)
    score = min(score, 17)
    risk = "frail" if score <= 14 else "robust"
    return {
        "value": score,
        "max": 17,
        "risk": risk,
        "basis": f"G8 = {score}/17 → {risk} ({'CGA referral' if risk == 'frail' else 'no CGA'})",
        "valid": True,
    }


def derive_frailty_status(*, age: int | None, ecog: int | None,
                            charlson: int | None) -> dict[str, Any]:
    """Composite frailty: robust / pre-frail / frail / incomplete."""
    if age is None or ecog is None or charlson is None:
        missing = [n for n, v in [("age", age), ("ecog", ecog), ("charlson", charlson)] if v is None]
        return {"status": "incomplete", "basis": f"Missing: {missing}",
                "missing_inputs": missing, "valid": False}

    points = 0
    if age >= 75: points += 1
    if ecog >= 2: points += 2
    if charlson >= 4: points += 1
    if age >= 80: points += 1

    if points == 0:
        status = "robust"
    elif points <= 2:
        status = "pre-frail"
    else:
        status = "frail"

    return {
        "status": status,
        "points": points,
        "basis": f"Frailty composite age={age} ecog={ecog} charlson={charlson} → {status}",
        "valid": True,
    }


def derive_bcr_phoenix(psa_nadir: float | None, psa_current: float | None) -> dict[str, Any]:
    """Phoenix BCR criterion post-RT: PSA ≥ nadir + 2 ng/mL."""
    if psa_nadir is None or psa_current is None:
        return {"is_bcr": None, "basis": "Need nadir + current PSA", "valid": False}
    threshold = psa_nadir + 2.0
    is_bcr = psa_current >= threshold
    return {
        "is_bcr": is_bcr,
        "threshold": round(threshold, 2),
        "delta_above_threshold": round(psa_current - threshold, 2),
        "basis": f"Phoenix: nadir {psa_nadir} + 2 = {threshold:.2f} · current {psa_current} → {'BCR' if is_bcr else 'no BCR'}",
        "valid": True,
    }


def derive_creatinine_clearance(creat_mg_dl: float | None, age: int | None,
                                  weight_kg: float | None,
                                  sex: str = "male") -> dict[str, Any]:
    """Cockcroft-Gault. Required for PARP eligibility (≥30 mL/min)."""
    if not all([creat_mg_dl, age, weight_kg]):
        return {"value_ml_min": None, "basis": "Need creatinine + age + weight", "valid": False}
    if creat_mg_dl <= 0:
        return {"value_ml_min": None, "basis": "Invalid creatinine ≤0", "valid": False}
    factor = (140 - age) * weight_kg / (72 * creat_mg_dl)
    if sex.lower() in {"female", "f", "femenino"}:
        factor *= 0.85
    return {
        "value_ml_min": round(factor, 1),
        "basis": f"Cockcroft-Gault: ({140}-{age})*{weight_kg}/({72}*{creat_mg_dl}) = {factor:.1f}",
        "valid": True,
    }


def derive_age(dob: str | datetime | None) -> dict[str, Any]:
    """Age from date of birth."""
    if dob is None:
        return {"value": None, "basis": "DOB required", "valid": False}
    try:
        if isinstance(dob, str):
            d = datetime.fromisoformat(dob[:10])
        else:
            d = dob
        years = (datetime.now() - d).days // 365
        return {"value": years, "basis": f"Today − {d.strftime('%Y-%m-%d')}", "valid": True}
    except (ValueError, TypeError) as e:
        return {"value": None, "basis": f"Invalid DOB: {e}", "valid": False}


def derive_disease_free_interval(diagnosis_date: str | None,
                                    mets_date: str | None) -> dict[str, Any]:
    """Months between primary diagnosis and metastatic diagnosis (metachronous trigger)."""
    if not diagnosis_date or not mets_date:
        return {"value_months": None, "basis": "Need both dates", "valid": False}
    try:
        d1 = datetime.fromisoformat(str(diagnosis_date)[:10])
        d2 = datetime.fromisoformat(str(mets_date)[:10])
        months = (d2 - d1).days / 30.44
        is_metachronous = months > 12  # CHAARTED definition
        return {
            "value_months": round(months, 1),
            "is_metachronous": is_metachronous,
            "basis": f"{months:.1f}m between dx and mets → {'metachronous' if is_metachronous else 'synchronous'}",
            "valid": True,
        }
    except (ValueError, TypeError) as e:
        return {"value_months": None, "basis": f"Invalid dates: {e}", "valid": False}


def derive_all(patient_record: dict[str, Any]) -> dict[str, Any]:
    """Single-call entry point: derive all fields from patient record."""
    baseline = patient_record.get("baseline") or patient_record.get("clinical_baseline") or {}
    identity = patient_record.get("identity") or {}
    psa_history = patient_record.get("biomarker_longitudinal") or []
    psa_only = [b for b in psa_history if (b.get("biomarker_type") or "").upper() == "PSA"]
    comorbidities = patient_record.get("comorbidities") or {}

    return {
        "isup_grade": derive_isup_grade(
            baseline.get("gleason_primary"), baseline.get("gleason_secondary")),
        "psadt": derive_psadt(psa_only),
        "age": derive_age(identity.get("dob")),
        "charlson_score": derive_charlson_score(
            comorbidities, baseline.get("age") or identity.get("age")),
        "g8_score": derive_g8_score(
            age=baseline.get("age") or identity.get("age"),
            ecog=baseline.get("ecog_score"),
        ),
        "frailty_status": derive_frailty_status(
            age=baseline.get("age") or identity.get("age"),
            ecog=baseline.get("ecog_score"),
            charlson=baseline.get("charlson_comorbidity_index"),
        ),
        "creatinine_clearance": derive_creatinine_clearance(
            baseline.get("creatinine"), baseline.get("age") or identity.get("age"),
            baseline.get("weight_kg"),
            baseline.get("biological_sex") or "male",
        ),
        "bcr_phoenix": derive_bcr_phoenix(
            baseline.get("psa_nadir"), baseline.get("psa_current") or baseline.get("baseline_psa")),
        "disease_free_interval": derive_disease_free_interval(
            identity.get("diagnosis_date"), baseline.get("metastasis_diagnosis_date")),
    }
