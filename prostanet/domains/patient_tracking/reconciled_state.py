from __future__ import annotations

from datetime import datetime
from math import log
from typing import Any

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)
from prostanet.shared.metastatic_profile import (
    derive_legacy_metastasis,
    derive_mhspc_burden_context,
    resolve_metastatic_state_context,
)
from prostanet.shared.systemic_progression import (
    build_progression_gate,
    normalize_castrate_status,
    resolve_systemic_progression_context,
)


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
ADVANCED_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES
CRPC_TRACK_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}

_SYSTEMIC_TOKENS = (
    "abirater",
    "apalut",
    "enzalut",
    "darolut",
    "bicalut",
    "docetax",
    "cabazitax",
    "leupro",
    "degarel",
    "goserelin",
    "triptorelin",
    "relugolix",
    "olapar",
    "talazop",
    "lutec",
    "pluvicto",
    "orchiect",
    "adt",
)

_ADT_TOKENS = (
    "leupro",
    "degarel",
    "goserelin",
    "triptorelin",
    "relugolix",
    "orchiect",
    "castrat",
    "adt",
)

_ARPI_TOKENS = ("abirater", "apalut", "enzalut", "darolut", "bicalut")
_PARP_TOKENS = ("olapar", "talazop", "parp")
_LU177_TOKENS = ("lutec", "pluvicto", "177lu", "lu177", "radiolig")


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí"}


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _assessment_state(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> str:
    return (
        (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )


def _biopsy_confirms_cancer(patient: dict[str, Any]) -> bool:
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    positive_cores = _safe_int(latest_biopsy.get("positive_cores")) or 0
    return any(
        _is_present(latest_biopsy.get(field))
        for field in ("gleason_primary", "gleason_secondary", "isup_grade", "positive_cores")
    ) and positive_cores > 0


def _treatment_text(patient: dict[str, Any]) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    if _is_present(truth_values.get("current_treatment")):
        return str(truth_values.get("current_treatment"))
    if _is_present(truth_values.get("drug_scheme")):
        return str(truth_values.get("drug_scheme"))
    treatments = patient.get("treatments") or []
    if treatments:
        latest_treatment = treatments[-1]
        regimen = latest_treatment.get("regimen_json")
        if isinstance(regimen, dict) and regimen.get("summary"):
            return str(regimen["summary"])
        if isinstance(regimen, str) and regimen.strip():
            return regimen
        if _is_present(latest_treatment.get("drug_scheme")):
            return str(latest_treatment.get("drug_scheme"))
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    return str(latest_followup.get("current_treatment") or "")


def _has_systemic_treatment(patient: dict[str, Any]) -> bool:
    haystack = _treatment_text(patient).lower()
    if any(token in haystack for token in _SYSTEMIC_TOKENS):
        return True
    treatments = patient.get("treatments") or []
    return any(_safe_int(item.get("line_of_therapy")) not in (None, 0) for item in treatments)


def _has_local_treatment(patient: dict[str, Any]) -> bool:
    return bool(patient.get("surgery")) or bool(patient.get("radiation"))


def _has_post_prostatectomy_context(patient: dict[str, Any]) -> bool:
    if patient.get("surgery"):
        return True
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state == "post_prostatectomy":
        return True
    assessment_state = str((patient.get("latest_assessment") or {}).get("state") or "")
    if assessment_state == "post_prostatectomy":
        return True
    bcr = patient.get("bcr") or {}
    primary_treatment = str(bcr.get("primary_treatment") or "").strip().upper()
    if primary_treatment in {"RP", "POST_RP", "RADICAL PROSTATECTOMY", "PROSTATECTOMY"}:
        return True
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    for source in (
        patient.get("baseline") or {},
        truth_values,
        assessment_inputs,
        bcr,
    ):
        if not isinstance(source, dict):
            continue
        if _safe_bool(source.get("prior_prostatectomy")):
            return True
        if _safe_bool(source.get("post_prostatectomy")):
            return True
        if _safe_bool(source.get("prostatectomy_done")):
            return True
        if _is_present(source.get("rp_date")) or _is_present(source.get("prostatectomy_date")):
            return True
        if _is_present(source.get("pathologic_stage")) or _is_present(source.get("pathological_stage")):
            return True
        if _is_present(source.get("surgery_type")) or _is_present(source.get("margin_location")):
            return True
        if _is_present(source.get("surgical_margin")) or _is_present(source.get("surgical_margin_status")):
            return True
    return False


def _has_post_radiotherapy_context(patient: dict[str, Any]) -> bool:
    if patient.get("radiation"):
        return True
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state in {"post_radiotherapy_followup", "post_radiotherapy_or_local_salvage"}:
        return True
    assessment_state = str((patient.get("latest_assessment") or {}).get("state") or "")
    if assessment_state in {"post_radiotherapy_followup", "post_radiotherapy_or_local_salvage"}:
        return True
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    for source in (
        patient.get("baseline") or {},
        truth_values,
        assessment_inputs,
        patient.get("bcr") or {},
    ):
        if not isinstance(source, dict):
            continue
        if _safe_bool(source.get("prior_radiation")):
            return True
        if _safe_bool(source.get("radiotherapy_done")):
            return True
        if _is_present(source.get("radiation_date")) or _is_present(source.get("prior_rt_date")):
            return True
        if _is_present(source.get("prior_rt_modality")) or _is_present(source.get("rt_modality")):
            return True
    return False


def _build_post_rt_recurrence_payload(patient: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    latest_rt_course = _latest(
        patient.get("radiotherapy_courses_detailed", []) or patient.get("radiotherapy_courses", []),
        "rt_start_date",
        "rt_end_date",
        "created_at",
    )
    latest_radiation = _latest(patient.get("radiation", []), "rt_date", "created_at")

    for source in (
        patient.get("baseline") or {},
        truth_values,
        latest_assessment_inputs,
        latest_signal_snapshot,
        latest_followup,
        stage_payload,
        patient.get("bcr") or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}):
                payload[key] = value

    payload["prior_radiation"] = 1 if _has_post_radiotherapy_context(patient) else payload.get("prior_radiation")
    payload["prior_prostatectomy"] = 1 if _has_post_prostatectomy_context(patient) else payload.get("prior_prostatectomy")

    if not _is_present(payload.get("psa_current")):
        psa_series = list(patient.get("psa_series") or [])
        if psa_series:
            payload["psa_current"] = psa_series[-1].get("value")

    if not _is_present(payload.get("psa_history")):
        psa_history = []
        for point in list(patient.get("psa_series") or []):
            value = _safe_float(point.get("value"))
            if value is None:
                continue
            psa_history.append(
                {
                    "value": value,
                    "date": point.get("sample_date") or "",
                    "unit": point.get("unit") or "ng/mL",
                    "context": point.get("context") or "",
                    "source": point.get("source") or point.get("entry_origin") or "",
                    "line_of_therapy_number": point.get("line_of_therapy_number"),
                    "line_of_therapy_context": point.get("line_of_therapy_context") or "",
                }
            )
        if psa_history:
            payload["psa_history"] = psa_history

    if not _is_present(payload.get("prior_rt_modality")):
        payload["prior_rt_modality"] = (
            latest_rt_course.get("modality")
            or latest_radiation.get("rt_technique")
            or payload.get("rt_modality")
            or ""
        )
    if not _is_present(payload.get("radiation_date")):
        payload["radiation_date"] = (
            latest_rt_course.get("rt_start_date")
            or latest_radiation.get("rt_date")
            or payload.get("prior_rt_date")
            or ""
        )
    return payload


def _is_metachronous_mhspc(patient: dict[str, Any]) -> bool:
    baseline = patient.get("baseline") or {}
    explicit = str(baseline.get("metachronous_metastasis", "") or "").strip().lower()
    if explicit in {"1", "true", "yes", "si", "sí"}:
        return True
    return _has_local_treatment(patient)


def _resolved_explicit_mhspc_state(patient: dict[str, Any], explicit_state: str) -> str:
    if explicit_state == "mcspc_high_volume":
        return "mcspc_high_volume_metachronous" if _is_metachronous_mhspc(patient) else "mcspc_high_volume_sync"
    return explicit_state


def _derive_adt_context(patient: dict[str, Any], state: str) -> str:
    haystack = _treatment_text(patient).lower()
    if "orchiect" in haystack:
        return "orchiectomy"
    if any(token in haystack for token in _ADT_TOKENS):
        return "medical_adt_continuous"
    if state in ADVANCED_STATES:
        return "medical_adt_continuous"
    return "none"


def _derive_castrate_status(patient: dict[str, Any], state: str) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    explicit_status = (
        str(truth_values.get("castrate_testosterone_status") or "").strip()
        or str(latest_assessment_inputs.get("castrate_testosterone_status") or "").strip()
        or str(latest_signal_snapshot.get("castrate_testosterone_status") or "").strip()
        or str(stage_payload.get("castrate_testosterone_status") or "").strip()
    )
    latest_testosterone = _safe_float(
        truth_values.get("testosterone")
        or latest_assessment_inputs.get("testosterone_value")
        or latest_assessment_inputs.get("testosterone")
        or latest_signal_snapshot.get("testosterone")
        or stage_payload.get("testosterone_value")
        or stage_payload.get("testosterone")
    )
    if latest_testosterone is None:
        latest_testosterone = _safe_float(patient.get("latest_testosterone_value"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float(latest_followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float((patient.get("baseline") or {}).get("testosterone_baseline"))
    castrate_confirmed_flag = (
        truth_values.get("castrate_testosterone_confirmed")
        if truth_values.get("castrate_testosterone_confirmed") not in (None, "")
        else latest_assessment_inputs.get("castrate_testosterone_confirmed")
    )
    if castrate_confirmed_flag in (None, ""):
        castrate_confirmed_flag = latest_signal_snapshot.get("castrate_testosterone_confirmed")
    if castrate_confirmed_flag in (None, ""):
        castrate_confirmed_flag = stage_payload.get("castrate_testosterone_confirmed")
    return normalize_castrate_status(
        explicit_status,
        testosterone_value=latest_testosterone,
        castrate_confirmed_flag=castrate_confirmed_flag,
    )


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    explicit_pattern = str(truth_values.get("progression_pattern") or "").strip().lower()
    if explicit_pattern in {"radiographic", "clinical", "biochemical_only", "mixed"}:
        return explicit_pattern
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(
        truth_values.get("disease_status")
        or latest_followup.get("disease_status")
        or ""
    ).lower()
    metachronous = _is_metachronous_mhspc(patient)
    if "radiograf" in disease_status:
        return "radiographic"
    if "clinic" in disease_status:
        return "clinical"
    if "bioqu" in disease_status or "psa" in disease_status:
        return "biochemical_only"
    if state in {"m1_crpc"}:
        return "mixed"
    return "biochemical_only"


def _overlay_psma_context(payload: dict[str, Any], patient: dict[str, Any]) -> dict[str, Any]:
    merged = dict(payload or {})
    psma_profile = patient.get("psma_structured_profile") or {}
    if isinstance(psma_profile, dict) and psma_profile.get("available"):
        mapping = {
            "psma_pet_done": "1",
            "psma_positive": "1" if psma_profile.get("psma_positive") else "0",
            "psma_result": psma_profile.get("psma_result"),
            "psma_radioligand": psma_profile.get("psma_radioligand"),
            "psma_rads_score": psma_profile.get("psma_rads_score"),
            "psma_uptake_pattern": psma_profile.get("psma_uptake_pattern"),
            "psma_stage_after_psma": psma_profile.get("psma_stage_after_psma"),
            "conventional_stage_before_psma": psma_profile.get("conventional_stage_before_psma"),
            "psma_total_lesions": psma_profile.get("psma_total_lesions"),
            "psma_lesion_locations": psma_profile.get("psma_lesion_locations"),
            "psma_study_date": psma_profile.get("study_date"),
        }
        for key, value in mapping.items():
            if value not in (None, "", [], {}) and merged.get(key) in (None, "", [], {}):
                merged[key] = value
        if merged.get("conventional_imaging_status") in (None, "", [], {}) and psma_profile.get("conventional_stage_before_psma"):
            merged["conventional_imaging_status"] = psma_profile.get("conventional_stage_before_psma")

    latest_psma = {}
    for study in patient.get("imaging") or []:
        if "psma" in str(study.get("study_type") or "").lower():
            latest_psma = dict(study)
            break
    if latest_psma:
        findings = latest_psma.get("findings") if isinstance(latest_psma.get("findings"), dict) else {}
        for key in (
            "psma_result",
            "psma_radioligand",
            "psma_rads_score",
            "psma_uptake_pattern",
            "conventional_stage_before_psma",
            "psma_stage_after_psma",
        ):
            value = latest_psma.get(key) or findings.get(key)
            if value not in (None, "", [], {}) and merged.get(key) in (None, "", [], {}):
                merged[key] = value
        if merged.get("psma_study_date") in (None, "", [], {}) and latest_psma.get("study_date"):
            merged["psma_study_date"] = latest_psma.get("study_date")
        if merged.get("psma_pet_done") in (None, "", [], {}):
            merged["psma_pet_done"] = "1"
    return merged


def _metastatic_context(patient: dict[str, Any]) -> tuple[str, int, bool]:
    baseline = patient.get("baseline") or {}
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}

    metastatic_payload = dict(baseline)
    for source in (
        truth_values,
        latest_assessment_inputs,
        latest_signal_snapshot,
        latest_followup,
        stage_payload,
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}):
                metastatic_payload[key] = value

    metastatic_payload = _overlay_psma_context(metastatic_payload, patient)
    metastatic_state_context = resolve_metastatic_state_context(metastatic_payload)
    metastasis_site, metastasis_count, _ = derive_legacy_metastasis(metastatic_payload)
    metastatic_evidence = bool(metastatic_state_context.get("metastatic_known"))
    stage_resolved = str(metastatic_state_context.get("metastatic_stage_resolved") or "M0")
    if stage_resolved == "M1a":
        metastasis_site = "Node"
    elif stage_resolved == "M1b":
        metastasis_site = "Bone"
    elif stage_resolved == "M1c":
        metastasis_site = "Visceral"
    elif stage_resolved == "M1_unspecified" and metastasis_site in {"", "M0", "No aplica"}:
        metastasis_site = "M1"
    if metastatic_evidence and metastasis_count in (None, 0):
        metastasis_count = max(_safe_int(metastatic_payload.get("metastasis_count")) or 0, 1)
    return metastasis_site, metastasis_count, metastatic_evidence


def _implicit_confirmed_cancer(patient: dict[str, Any], explicit_state: str) -> bool:
    if _biopsy_confirms_cancer(patient):
        return True
    if explicit_state not in DIAGNOSTIC_STATES:
        return True
    if _has_local_treatment(patient) or bool(patient.get("bcr")):
        return True
    if _has_systemic_treatment(patient):
        return True
    _, _, metastatic_evidence = _metastatic_context(patient)
    return metastatic_evidence


def _post_prostatectomy_date(patient: dict[str, Any]) -> datetime | None:
    surgery = patient.get("surgery") or {}
    bcr = patient.get("bcr") or {}
    prior_history = patient.get("prior_history") or {}
    for candidate in (
        surgery.get("surgery_date"),
        bcr.get("primary_treatment_date"),
        prior_history.get("rp_date"),
        prior_history.get("prostatectomy_date"),
    ):
        parsed = _parse_date(candidate)
        if parsed:
            return parsed
    return None


def _append_post_rp_psa_point(
    points: list[dict[str, Any]],
    *,
    value: Any,
    sample_date: Any,
    source: str,
    rp_date: datetime | None,
) -> None:
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return
    parsed_date = _parse_date(sample_date)
    if rp_date and parsed_date and parsed_date < rp_date:
        return
    point = {
        "value": numeric_value,
        "sample_date": parsed_date.strftime("%Y-%m-%d") if parsed_date else "",
        "source": source,
    }
    if point not in points:
        points.append(point)


def _post_prostatectomy_psa_points(patient: dict[str, Any]) -> list[dict[str, Any]]:
    rp_date = _post_prostatectomy_date(patient)
    points: list[dict[str, Any]] = []
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    bcr = patient.get("bcr") or {}
    latest_assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    followups = list(patient.get("follow_ups", []) or [])
    biomarker_rows = list(patient.get("biomarker_longitudinal") or [])

    for row in biomarker_rows:
        biomarker_type = str(row.get("biomarker_type") or "").upper()
        if biomarker_type != "PSA":
            continue
        _append_post_rp_psa_point(
            points,
            value=row.get("value"),
            sample_date=row.get("sample_date"),
            source="biomarker_longitudinal",
            rp_date=rp_date,
        )

    for followup in followups:
        for key in ("psa_postop", "psa_current", "psa"):
            _append_post_rp_psa_point(
                points,
                value=followup.get(key),
                sample_date=followup.get("visit_date"),
                source=f"follow_up:{key}",
                rp_date=rp_date,
            )

    for key in ("psa_postop", "psa_current"):
        _append_post_rp_psa_point(
            points,
            value=truth_values.get(key),
            sample_date=((patient.get("longitudinal_truth_snapshot") or {}).get("latest_clinically_decisive_visit") or {}).get("visit_date"),
            source=f"truth:{key}",
            rp_date=rp_date,
        )

    for key in ("psa_postop", "psa_current"):
        _append_post_rp_psa_point(
            points,
            value=latest_assessment_inputs.get(key),
            sample_date=(patient.get("latest_assessment") or {}).get("assessment_date"),
            source=f"assessment:{key}",
            rp_date=rp_date,
        )

    _append_post_rp_psa_point(
        points,
        value=bcr.get("bcr_psa"),
        sample_date=bcr.get("bcr_date"),
        source="bcr",
        rp_date=rp_date,
    )

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        sample_date = str(item.get("sample_date") or "")
        return (0 if sample_date else 1, sample_date, str(item.get("source") or ""))

    return sorted(points, key=_sort_key)


def _post_prostatectomy_psa_series(patient: dict[str, Any]) -> list[float]:
    return [float(point["value"]) for point in _post_prostatectomy_psa_points(patient)]


def _derive_post_rp_psadt_months(points: list[dict[str, Any]]) -> float | None:
    dated_points = [item for item in points if item.get("sample_date") and _safe_float(item.get("value")) not in (None, 0.0)]
    if len(dated_points) < 2:
        return None
    selected = dated_points[-3:] if len(dated_points) >= 3 else dated_points[-2:]
    xs: list[float] = []
    ys: list[float] = []
    anchor_date = _parse_date(selected[0].get("sample_date"))
    if not anchor_date:
        return None
    for item in selected:
        sample_date = _parse_date(item.get("sample_date"))
        value = _safe_float(item.get("value"))
        if not sample_date or value is None or value <= 0:
            continue
        xs.append(max((sample_date - anchor_date).days, 0) / 30.44)
        ys.append(log(value))
    if len(xs) < 2 or xs[-1] <= xs[0]:
        return None
    if len(xs) == 2:
        slope = (ys[1] - ys[0]) / max(xs[1] - xs[0], 1e-6)
    else:
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator <= 0:
            return None
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    if slope <= 0:
        return None
    return round(log(2) / slope, 1)


def derive_post_prostatectomy_truth(patient: dict[str, Any]) -> dict[str, Any]:
    bcr = patient.get("bcr") or {}
    psa_points = _post_prostatectomy_psa_points(patient)
    psa_series = [float(point["value"]) for point in psa_points]
    structured_bcr_confirmed = _post_prostatectomy_bcr_confirmed(bcr)
    structured_bcr_inconsistency = bool(bcr) and not _safe_bool(bcr.get("bcr_detected")) and structured_bcr_confirmed
    if structured_bcr_confirmed:
        course = "true_bcr"
    elif not psa_series:
        course = "stable_surveillance"
    else:
        nadir_indetectable = any(value <= 0.1 for value in psa_series)
        latest_value = psa_series[-1]
        earliest_value = psa_series[0]
        postoperative_persistence_flag = _safe_bool(
            ((patient.get("baseline") or {}).get("postoperative_psa_persistent"))
            or ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {}).get("postoperative_psa_persistent")
        )
        if latest_value >= 0.2 and nadir_indetectable:
            course = "true_bcr"
        elif postoperative_persistence_flag:
            course = "persistent_psa"
        elif earliest_value >= 0.1 and not nadir_indetectable:
            course = "persistent_psa"
        elif latest_value >= 0.1 and not nadir_indetectable:
            course = "persistent_psa"
        else:
            course = "stable_surveillance"
    return {
        "course": course,
        "psa_points": psa_points,
        "psa_series": psa_series,
        "psa_current": psa_series[-1] if psa_series else None,
        "psadt_months": _derive_post_rp_psadt_months(psa_points),
        "structured_bcr_confirmed": structured_bcr_confirmed,
        "structured_bcr_inconsistency": structured_bcr_inconsistency,
        "rp_date": _post_prostatectomy_date(patient).strftime("%Y-%m-%d") if _post_prostatectomy_date(patient) else "",
    }


def _post_prostatectomy_bcr_confirmed(bcr: dict[str, Any]) -> bool:
    if not isinstance(bcr, dict):
        return False
    if _safe_bool(bcr.get("bcr_detected")):
        return True
    bcr_psa = _safe_float(bcr.get("bcr_psa"))
    if bcr_psa is not None and bcr_psa >= 0.2:
        if any(_is_present(bcr.get(field)) for field in ("bcr_date", "psadt_at_bcr", "salvage_date")):
            return True
        definition = str(bcr.get("bcr_definition") or "").strip().lower()
        if definition and definition not in {"", "none", "unknown", "pendiente"}:
            return True
    if _is_present(bcr.get("salvage_date")):
        return True
    return False


def derive_post_prostatectomy_course(patient: dict[str, Any]) -> str:
    if not _has_post_prostatectomy_context(patient):
        return ""
    return str(derive_post_prostatectomy_truth(patient).get("course") or "stable_surveillance")


def _has_postlocal_bcr(patient: dict[str, Any]) -> bool:
    bcr = patient.get("bcr") or {}
    post_rp_truth = derive_post_prostatectomy_truth(patient) if _has_post_prostatectomy_context(patient) else {}
    has_post_rt_context = _has_post_radiotherapy_context(patient)
    has_postlocal_context = _has_post_prostatectomy_context(patient) or has_post_rt_context
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state in POSTLOCAL_STATES:
        has_postlocal_context = True
    if has_post_rt_context:
        post_rt_failure = build_post_rt_failure_definition(_build_post_rt_recurrence_payload(patient))
        if bool(post_rt_failure.get("phoenix_threshold_reached")):
            return True
        if str(post_rt_failure.get("failure_confirmation_basis") or "") in {
            "biopsy_proven_local_failure",
            "radiographic_local_failure",
        }:
            return True
        return False
    explicit_bcr_markers = bool(post_rp_truth.get("structured_bcr_confirmed")) or any(
        _is_present(bcr.get(field))
        for field in ("bcr_psa", "psadt_at_bcr", "bcr_definition", "salvage_date", "bcr_date")
    )
    if explicit_bcr_markers and has_postlocal_context:
        return True
    if not has_postlocal_context:
        return False
    if patient.get("surgery"):
        return str(post_rp_truth.get("course") or "") == "true_bcr"
    if any(
        _is_present(bcr.get(field))
        for field in ("bcr_psa", "psadt_at_bcr", "bcr_definition", "salvage_date", "bcr_date")
    ):
        return True
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    psa_value = _safe_float(
        truth_values.get("psa")
        or truth_values.get("psa_postop")
    )
    if psa_value is None:
        latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
        psa_value = _safe_float(
            latest_followup.get("psa_postop")
            or latest_followup.get("psa_current")
        )
    return psa_value is not None and psa_value >= 0.2


def _systemic_target_state(
    patient: dict[str, Any],
    explicit_state: str,
    metastasis_site: str,
    metastasis_count: int,
    metastatic_evidence: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    treatment_text = _treatment_text(patient).lower()
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    burden_payload = dict(patient.get("baseline") or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    for source in (truth_values, latest_assessment_inputs, latest_signal_snapshot, latest_followup, stage_payload):
        if isinstance(source, dict):
            for key, value in source.items():
                if value not in (None, "", [], {}):
                    burden_payload[key] = value
    burden_payload.setdefault("metastasis_site", metastasis_site)
    burden_payload.setdefault("metastasis_count", metastasis_count)
    burden_payload = _overlay_psma_context(burden_payload, patient)
    metastatic_state_context = resolve_metastatic_state_context(burden_payload)
    burden_context = derive_mhspc_burden_context(burden_payload)
    volume_context = str(burden_context.get("volume_disease") or "unknown")
    adt_context = _derive_adt_context(patient, explicit_state)
    castrate_status = _derive_castrate_status(patient, explicit_state)
    progression_pattern = _derive_progression_pattern(patient, explicit_state)
    disease_status = str(latest_followup.get("disease_status") or "").lower()
    explicit_progression = str(truth_values.get("progression_pattern") or "").strip().lower()
    psadt_months = _safe_float(
        truth_values.get("psadt_months")
        or latest_followup.get("psadt_months")
    )
    metachronous = _is_metachronous_mhspc(patient)
    line_of_therapy = (
        _safe_int(truth_values.get("line_of_therapy_number"))
        or _safe_int(truth_values.get("line_of_therapy"))
        or _safe_int(latest_followup.get("line_of_therapy_number"))
        or _safe_int(latest_followup.get("line_of_therapy"))
    )
    explicit_progression_context = (
        truth_values.get("systemic_progression_context")
        or latest_followup.get("systemic_progression_context")
        or ("confirmed_crpc" if explicit_state in {"m0_crpc", "m1_crpc"} else "")
        or ("progression_on_adt_verify_castration" if explicit_state == "adt_progression_verification" else "")
    )
    resolved_systemic_context = resolve_systemic_progression_context(
        explicit_progression_context,
        legacy_crpc_signal=explicit_state in {"m0_crpc", "m1_crpc"},
        line_of_therapy=line_of_therapy,
    )
    biochemical_progression_confirmed = (
        progression_pattern == "biochemical_only"
        and (
            explicit_progression == "biochemical_only"
            or psadt_months is not None
            or any(token in disease_status for token in ("progres", "ascen", "aumento", "bioqu", "psa"))
        )
    )
    phenotype_state = explicit_state
    explicit_mhspc_state = _resolved_explicit_mhspc_state(patient, explicit_state) if explicit_state in MHSPC_STATES else ""
    if explicit_state in MHSPC_STATES and explicit_mhspc_state:
        phenotype_state = explicit_mhspc_state
        # Auditoría #21 (cierre OOS-6): cuando el snapshot explícito quedó como
        # mHSPC de bajo volumen (oligo_metachronous o low_volume_sync_oligo) pero
        # la evidencia actual documenta carga alta CHAARTED (p.ej. metástasis
        # visceral o ≥4 óseas con ≥1 apendicular), el reconciliador debe
        # reclasificar para no permanecer en un estado stale que oculta la
        # elegibilidad a doblete/triplete de alto volumen. La condición de
        # "metacrónico" clínicamente exige tratamiento local previo (RP/RT);
        # sin esa corroboración la carga se interpreta como sincrónica.
        # Se actualiza también `explicit_mhspc_state` para que los bloques
        # posteriores (p. ej. la salvaguarda en líneas 869-873) no reviertan
        # el override volumétrico al estado stale.
        low_volume_explicit_states = {
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
        }
        if explicit_state in low_volume_explicit_states and volume_context == "high":
            reasons.append(
                "Evidencia clínica (carga alta CHAARTED con sitios viscerales o óseos apendiculares) "
                "contradice el último assessment; se reclasifica a alto volumen."
            )
            effective_metachronous = metachronous and _has_local_treatment(patient)
            phenotype_state = (
                "mcspc_high_volume_metachronous" if effective_metachronous else "mcspc_high_volume_sync"
            )
            explicit_mhspc_state = phenotype_state
    elif explicit_state in {"m0_crpc", "m1_crpc"}:
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
    elif metastatic_evidence:
        if volume_context == "high":
            phenotype_state = "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"
        elif burden_context.get("oligometastatic_operational") or volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            phenotype_state = "mcspc_oligo_metachronous" if _has_local_treatment(patient) else "mcspc_low_volume_sync_oligo"
        else:
            phenotype_state = "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"

    if any(token in treatment_text for token in _PARP_TOKENS + _LU177_TOKENS):
        reasons.append("Tratamiento avanzado documentado con PARP / radioligando.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"

    if explicit_state in {"m0_crpc", "m1_crpc"}:
        reasons.append("Último assessment ya documenta CRPC.")
        resolved_systemic_context = "confirmed_crpc"
        if explicit_state == "m0_crpc" and metastatic_evidence:
            reasons.append(
                f"Existe enfermedad metastásica documentada ({metastatic_state_context.get('metastatic_stage_label') or 'M1'}); el caso ya no es compatible con m0 CRPC."
            )

    if castrate_status == "confirmed_castrate" and progression_pattern in {"radiographic", "clinical", "mixed"}:
        reasons.append("Progresión avanzada con testosterona en rango de castración.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"
        return {
            "state": phenotype_state,
            "phenotype_state": phenotype_state,
            "reasons": reasons,
            **build_progression_gate(
                systemic_progression_context=resolved_systemic_context,
                on_adt=adt_context != "none",
                castrate_status=castrate_status,
                progression_pattern=progression_pattern,
                prior_prostatectomy=_has_post_prostatectomy_context(patient),
                prior_radiation=bool(patient.get("radiation")),
                phenotype_state=phenotype_state,
            ),
        }

    if castrate_status == "confirmed_castrate" and biochemical_progression_confirmed:
        if progression_pattern == "biochemical_only":
            reasons.append("Ascenso bioquímico bajo testosterona en rango de castración compatible con carril CRPC.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"
        return {
            "state": phenotype_state,
            "phenotype_state": phenotype_state,
            "reasons": reasons,
            **build_progression_gate(
                systemic_progression_context=resolved_systemic_context,
                on_adt=adt_context != "none",
                castrate_status=castrate_status,
                progression_pattern=progression_pattern,
                prior_prostatectomy=_has_post_prostatectomy_context(patient),
                prior_radiation=bool(patient.get("radiation")),
                phenotype_state=phenotype_state,
            ),
        }

    if metastatic_evidence:
        if volume_context == "high":
            reasons.append(str(burden_context.get("volume_reason") or "Enfermedad sistémica con carga compatible con mCSPC de mayor volumen."))
        elif burden_context.get("oligometastatic_operational") or volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            reasons.append("Carga metastásica baja / oligometastásica documentada.")
        else:
            reasons.append("Enfermedad metastásica documentada sin staging longitudinal completo.")
        if explicit_mhspc_state and explicit_mhspc_state != phenotype_state:
            phenotype_state = explicit_mhspc_state
            reasons.append(
                "El subtipo mHSPC explícito del último assessment prevalece sobre heurísticas longitudinales más débiles mientras no exista evidencia estructurada que lo contradiga."
            )
    elif explicit_state in MHSPC_STATES:
        phenotype_state = _resolved_explicit_mhspc_state(patient, explicit_state)
        reasons.append(
            "Se conserva el fenotipo mHSPC explícito del último assessment mientras no exista nueva evidencia estructurada que lo contradiga."
        )
    elif explicit_state in {"m0_crpc", "m1_crpc"}:
        phenotype_state = explicit_state
        resolved_systemic_context = "confirmed_crpc"
        reasons.append(
            "Se conserva el fenotipo CRPC explícito del último assessment mientras no exista nueva evidencia estructurada que lo contradiga."
        )
    elif adt_context != "none" or any(token in treatment_text for token in _ARPI_TOKENS):
        phenotype_state = "adt_progression_verification"
        reasons.append("ADT/ARPI documentados sin staging longitudinal suficiente para subtipo avanzado definitivo.")
    else:
        phenotype_state = "localized_initial"
        reasons.append("Tratamiento oncológico sistémico documentado sin suficiente staging estructurado.")

    progression_gate = build_progression_gate(
        systemic_progression_context=resolved_systemic_context,
        on_adt=adt_context != "none",
        castrate_status=castrate_status,
        progression_pattern=progression_pattern,
        prior_prostatectomy=_has_post_prostatectomy_context(patient),
        prior_radiation=bool(patient.get("radiation")),
        phenotype_state=phenotype_state if phenotype_state in MHSPC_STATES else "",
    )
    if progression_gate.get("progression_gate_active") and phenotype_state in MHSPC_STATES:
        reasons.append(str(progression_gate.get("progression_gate_reason") or ""))
        resolved_state = phenotype_state
    elif progression_gate.get("progression_gate_active") and explicit_state in {"m0_crpc", "m1_crpc"}:
        reasons.append(str(progression_gate.get("progression_gate_reason") or ""))
        if metastatic_evidence:
            reasons.append("M1 anatómico ya documentado; la ruta correcta es verificar castración/progresión antes de cerrar el estado resistente final.")
        resolved_state = "adt_progression_verification"
    elif progression_gate.get("progression_gate_active"):
        resolved_state = "adt_progression_verification"
    else:
        resolved_state = phenotype_state
    return {
        "state": resolved_state,
        "phenotype_state": phenotype_state,
        "reasons": reasons,
        **progression_gate,
    }


def build_reconciled_state(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_state = _assessment_state(patient, latest_assessment)
    reconciled_state = explicit_state
    phenotype_state = explicit_state
    reasons: list[str] = []
    progression_gate_active = False
    progression_gate_target = ""
    progression_gate_reason = ""
    systemic_progression_context_resolved = "none"

    has_histology = _biopsy_confirms_cancer(patient)
    has_confirmed_cancer = _implicit_confirmed_cancer(patient, explicit_state)
    has_local_treatment = _has_local_treatment(patient)
    has_bcr = _has_postlocal_bcr(patient)
    post_prostatectomy_truth = derive_post_prostatectomy_truth(patient) if _has_post_prostatectomy_context(patient) else {}
    post_prostatectomy_course = str(post_prostatectomy_truth.get("course") or derive_post_prostatectomy_course(patient))
    has_systemic_treatment = _has_systemic_treatment(patient)
    metastasis_site, metastasis_count, metastatic_evidence = _metastatic_context(patient)

    if explicit_state in DIAGNOSTIC_STATES:
        if has_systemic_treatment:
            systemic_resolution = _systemic_target_state(
                patient,
                explicit_state,
                metastasis_site,
                metastasis_count,
                metastatic_evidence,
            )
            reconciled_state = systemic_resolution.get("state") or explicit_state
            phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
            reasons.extend(systemic_resolution.get("reasons") or [])
            progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
            progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
            progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
            systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
        elif has_bcr or has_local_treatment:
            if _has_post_prostatectomy_context(patient):
                reconciled_state = "recurrence_bcr" if has_bcr else "post_prostatectomy"
                phenotype_state = reconciled_state
                reasons.append("El longitudinal ya documenta prostatectomía radical previa y redirige al carril posquirúrgico correspondiente.")
            elif _has_post_radiotherapy_context(patient):
                reconciled_state = "post_radiotherapy_or_local_salvage" if has_bcr else "post_radiotherapy_followup"
                phenotype_state = reconciled_state
                reasons.append(
                    "El longitudinal ya documenta radioterapia previa y reconstruye la ruta post-RT con evaluación específica de Phoenix y salvage."
                )
            else:
                reconciled_state = "recurrence_bcr" if has_bcr else "post_prostatectomy"
                phenotype_state = reconciled_state
                reasons.append("El longitudinal ya documenta tratamiento local previo / recurrencia.")
        elif has_histology or has_confirmed_cancer:
            reconciled_state = "localized_initial"
            phenotype_state = reconciled_state
            reasons.append("Existe evidencia longitudinal de cáncer confirmado fuera del carril diagnóstico.")
    elif explicit_state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr":
        reconciled_state = "recurrence_bcr"
        phenotype_state = reconciled_state
        reasons.append("El PSA longitudinal posprostatectomía ya cumple criterio operativo de recurrencia bioquímica y debe pasar a carril de salvage.")
    elif explicit_state == "localized_initial" and has_systemic_treatment and not metastatic_evidence:
        reconciled_state = explicit_state
        phenotype_state = explicit_state
        reasons.append(
            "La intensificación hormonal o multimodal documentada no saca por sí sola el caso del carril localizado mientras no exista progresión sistémica estructurada."
        )
    elif explicit_state == "localized_initial" and has_systemic_treatment:
        systemic_resolution = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reconciled_state = systemic_resolution.get("state") or explicit_state
        phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
        reasons.extend(systemic_resolution.get("reasons") or [])
        progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
        progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
        progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
        systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
    elif explicit_state in POSTLOCAL_STATES:
        reconciled_state = "recurrence_bcr" if explicit_state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr" else explicit_state
        phenotype_state = reconciled_state
        if has_systemic_treatment:
            reasons.append(
                "La exposición sistémica documentada no reclasifica por sí sola la familia postlocal; el carril operativo sigue siendo post-RP/BCR hasta cerrar un módulo avanzado específico."
            )
        if metastatic_evidence:
            reasons.append(
                "La enfermedad metastásica documentada redirige la conducta terapéutica, pero no convierte automáticamente el caso postlocal en mHSPC/CRPC si la ruta vigente sigue siendo salvage/BCR."
            )
    elif explicit_state in MHSPC_STATES | CRPC_TRACK_STATES:
        systemic_resolution = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reconciled_state = systemic_resolution.get("state") or explicit_state
        phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
        reasons.extend(systemic_resolution.get("reasons") or [])
        progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
        progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
        progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
        systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
    else:
        phenotype_state = reconciled_state

    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    raw_assessment = latest_assessment or patient.get("latest_assessment")
    reconciled_track = infer_management_track(patient, reconciled_state, raw_assessment)
    conflict_flag = reconciled_state != explicit_state
    if conflict_flag and not reasons:
        reasons.append("La evolución longitudinal contradice el último assessment persistido.")

    if conflict_flag and explicit_state in DIAGNOSTIC_STATES and has_systemic_treatment:
        reasons.insert(0, "Hay tratamiento sistémico documentado en follow-up, por lo que el caso no puede permanecer en triage diagnóstico.")

    return {
        "explicit_state": explicit_state,
        "reconciled_state": reconciled_state,
        "phenotype_state": phenotype_state,
        "reconciled_management_track": reconciled_track,
        "state_conflict_flag": conflict_flag,
        "state_conflict_reason": " ".join(dict.fromkeys(reason for reason in reasons if reason)).strip(),
        "progression_gate_active": progression_gate_active,
        "progression_gate_target": progression_gate_target,
        "progression_gate_reason": progression_gate_reason,
        "systemic_progression_context_resolved": systemic_progression_context_resolved,
        "supporting_evidence": {
            "confirmed_cancer": has_confirmed_cancer,
            "histology_confirmed": has_histology,
            "local_treatment_documented": has_local_treatment,
            "systemic_treatment_documented": has_systemic_treatment,
            "metastatic_evidence": metastatic_evidence,
            "metastasis_site": metastasis_site,
            "metastasis_count": metastasis_count,
            "bcr_documented": has_bcr,
            "post_prostatectomy_course": post_prostatectomy_course,
            "post_prostatectomy_psadt_months": post_prostatectomy_truth.get("psadt_months"),
            "post_prostatectomy_psa_current": post_prostatectomy_truth.get("psa_current"),
            "post_prostatectomy_structured_bcr_inconsistency": post_prostatectomy_truth.get("structured_bcr_inconsistency"),
            "phenotype_state": phenotype_state,
            "progression_gate_active": progression_gate_active,
            "progression_gate_reason": progression_gate_reason,
            "systemic_progression_context_resolved": systemic_progression_context_resolved,
        },
    }


__all__ = [
    "ADVANCED_STATES",
    "CRPC_TRACK_STATES",
    "DIAGNOSTIC_STATES",
    "MHSPC_STATES",
    "POSTLOCAL_STATES",
    "build_reconciled_state",
    "derive_post_prostatectomy_truth",
    "derive_post_prostatectomy_course",
]
