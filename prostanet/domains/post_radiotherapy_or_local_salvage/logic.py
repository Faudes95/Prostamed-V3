from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from math import log
from typing import Any

from prostanet.shared.phoenix import evaluate_phoenix


YES_VALUES = {"1", "true", "yes", "si", "sí", "apto", "fit", "eligible"}
NO_VALUES = {"0", "false", "no", "na", "n/a", "not_available"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _normalize_text(value).lower() in YES_VALUES


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "Desconocido", "No documentado", "No realizado")


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))


def _normalize_history_rows(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _append_psa_point(
    points: list[dict[str, Any]],
    *,
    value: Any,
    sample_date: Any = "",
    source: str = "",
) -> None:
    numeric = _safe_float(value)
    if numeric is None:
        return
    normalized_date = str(sample_date or "").strip()[:10]
    points.append(
        {
            "value": round(numeric, 4),
            "sample_date": normalized_date,
            "source": source or "psa",
        }
    )


def _psa_history_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []

    for row in _normalize_history_rows(payload.get("psa_history")):
        _append_psa_point(
            points,
            value=row.get("value"),
            sample_date=row.get("date") or row.get("sample_date") or row.get("fact_date"),
            source=row.get("source") or row.get("context") or "psa_history",
        )

    longitudinal_bundle = dict(payload.get("psa_longitudinal_bundle") or {})
    for row in _normalize_history_rows(longitudinal_bundle.get("points") or longitudinal_bundle.get("series")):
        _append_psa_point(
            points,
            value=row.get("value") or row.get("psa"),
            sample_date=row.get("date") or row.get("sample_date"),
            source=row.get("source") or "psa_longitudinal_bundle",
        )

    for row in _normalize_history_rows(payload.get("biomarker_longitudinal")):
        biomarker_type = _normalize_text(row.get("biomarker_type")).upper()
        if biomarker_type and biomarker_type != "PSA":
            continue
        _append_psa_point(
            points,
            value=row.get("value"),
            sample_date=row.get("date") or row.get("sample_date") or row.get("fact_date"),
            source=row.get("source") or "biomarker_longitudinal",
        )

    _append_psa_point(
        points,
        value=payload.get("psa_nadir"),
        sample_date=payload.get("psa_nadir_date"),
        source="psa_nadir",
    )
    _append_psa_point(
        points,
        value=payload.get("psa_current", payload.get("psa")),
        sample_date=payload.get("psa_current_date") or payload.get("visit_date"),
        source="psa_current",
    )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str]] = set()
    for item in points:
        key = (
            str(item.get("sample_date") or ""),
            float(item.get("value") or 0.0),
            str(item.get("source") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        sample_date = str(item.get("sample_date") or "")
        return (0 if sample_date else 1, sample_date, str(item.get("source") or ""))

    return sorted(unique, key=_sort_key)


def _derive_psadt_months(points: list[dict[str, Any]]) -> float | None:
    dated_points = [
        item
        for item in points
        if item.get("sample_date") and _safe_float(item.get("value")) not in (None, 0.0)
    ]
    if len(dated_points) < 2:
        return None
    selected = dated_points[-3:] if len(dated_points) >= 3 else dated_points[-2:]
    xs: list[float] = []
    ys: list[float] = []
    anchor = _parse_iso_date(selected[0].get("sample_date"))
    if not anchor:
        return None
    for item in selected:
        sample_date = _parse_iso_date(item.get("sample_date"))
        value = _safe_float(item.get("value"))
        if not sample_date or value is None or value <= 0:
            continue
        xs.append(max((sample_date - anchor).days, 0) / 30.44)
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


def _is_brachy_compatible_modality(value: Any) -> bool:
    normalized = _normalize_text(value).lower()
    return any(token in normalized for token in ("ldr", "hdr", "brachy", "boost"))


def _months_between_dates(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max((end - start).days, 0) / 30.44


def _compute_bounce_suspected(
    payload: dict[str, Any],
    *,
    points: list[dict[str, Any]],
    psa_nadir: float | None,
) -> bool:
    explicit_flag = _is_true(payload.get("bounce_suspected"))
    rt_date = _parse_iso_date(payload.get("local_therapy_date") or payload.get("prior_rt_completion_date"))
    if explicit_flag:
        return True
    if not _is_brachy_compatible_modality(payload.get("prior_rt_modality")) or rt_date is None or psa_nadir is None:
        return False

    window_rises: list[float] = []
    for item in points:
        sample_date = _parse_iso_date(item.get("sample_date"))
        value = _safe_float(item.get("value"))
        months_since_rt = _months_between_dates(rt_date, sample_date)
        if sample_date is None or value is None or months_since_rt is None:
            continue
        if 12 <= months_since_rt <= 36 and value > psa_nadir:
            window_rises.append(value - psa_nadir)
    if not window_rises:
        return False
    return max(window_rises) < 1.0


def _resolve_phoenix_confirmation_status(
    payload: dict[str, Any],
    *,
    points: list[dict[str, Any]],
    phoenix_threshold: float | None,
    phoenix_threshold_reached: bool,
    biopsy_proven: bool,
    radiographic_local: bool,
) -> str:
    if biopsy_proven:
        return "biopsy_confirmed"
    if radiographic_local:
        return "radiographic_localized"
    if _is_true(payload.get("phoenix_failure_confirmed")):
        return "confirmed_explicit"
    if not phoenix_threshold_reached:
        return "not_met"
    if phoenix_threshold is None:
        return "threshold_only_unconfirmed"

    threshold_points = []
    for item in points:
        value = _safe_float(item.get("value"))
        if value is None or value < phoenix_threshold:
            continue
        sample_date = _parse_iso_date(item.get("sample_date"))
        threshold_points.append((sample_date, value))

    if len(threshold_points) < 2:
        return "threshold_only_unconfirmed"

    for index, (first_date, _first_value) in enumerate(threshold_points):
        for second_date, _second_value in threshold_points[index + 1 :]:
            if first_date and second_date and (second_date - first_date).days >= 90:
                return "confirmed_longitudinal"
    return "threshold_only_unconfirmed"


def _burden_level(value: Any) -> str:
    text = _normalize_text(value).lower()
    if text in {"grave", "severo", "severa", "alto", "alta", "high"}:
        return "high"
    if text in {"moderado", "moderada", "medium"}:
        return "moderate"
    if text in {"leve", "bajo", "baja", "low"}:
        return "low"
    return ""


def _fit_for_salvage_surgery(payload: dict[str, Any]) -> bool:
    fitness_text = _normalize_text(payload.get("anesthesia_surgical_fitness")).lower()
    ecog = _safe_int(payload.get("ecog_score"))
    if fitness_text in NO_VALUES:
        return False
    if fitness_text in YES_VALUES:
        return True
    return ecog is None or ecog <= 2


def _prior_rt_modality(payload: dict[str, Any]) -> str:
    return _normalize_text(payload.get("prior_rt_modality")).upper()


def _systemic_psma_pattern(payload: dict[str, Any], psma_impact: dict[str, Any]) -> tuple[str, bool, bool]:
    stage_after = _normalize_text(payload.get("psma_stage_after_psma")).upper()
    uptake = _normalize_text(payload.get("psma_uptake_pattern")).lower()
    pattern = _normalize_text(psma_impact.get("clinical_pattern")).lower() or uptake
    lesion_count = _safe_int(payload.get("psma_total_lesions"))
    disseminated = stage_after in {"M1B", "M1C"} or pattern in {"diseminado", "systemic", "widespread"}
    oligomet = (
        not disseminated
        and (
            stage_after == "M1A"
            or pattern in {"oligometastatic", "multifocal"}
            or (lesion_count is not None and 0 < lesion_count <= 5 and stage_after not in {"", "M0"})
        )
    )
    return pattern or uptake, disseminated, oligomet


def build_post_rt_failure_definition(payload: dict[str, Any]) -> dict[str, Any]:
    points = _psa_history_points(payload)
    derived_nadir = min((_safe_float(item.get("value")) for item in points), default=None)
    derived_nadir_date = ""
    if derived_nadir is not None:
        for item in points:
            if _safe_float(item.get("value")) == derived_nadir:
                derived_nadir_date = str(item.get("sample_date") or "")
                break
    psa_nadir = _safe_float(payload.get("psa_nadir"))
    if psa_nadir is None:
        psa_nadir = derived_nadir
    psa_current = _safe_float(payload.get("psa_current", payload.get("psa")))
    if psa_current is None and points:
        psa_current = _safe_float(points[-1].get("value"))
    # EPIC 1 FIX-NCCN-1-B: consumir helper canónico evaluate_phoenix() para
    # evitar divergencia con recurrence_bcr/rules_nccn y alert_engine.
    phoenix_eval = evaluate_phoenix({
        "psa_nadir": psa_nadir,
        "psa_current": psa_current,
        "phoenix_delta": payload.get("phoenix_delta"),
        "phoenix_threshold": payload.get("phoenix_threshold"),
    })
    phoenix_delta = phoenix_eval.delta
    phoenix_threshold = phoenix_eval.threshold
    phoenix_threshold_reached = phoenix_eval.threshold_reached
    biopsy_proven = _is_true(payload.get("biopsy_proven_local_recurrence"))
    radiographic_local = (
        _is_true(payload.get("mpmri_localized_recurrence"))
        or (
            _is_present(payload.get("local_recurrence_site"))
            and _normalize_text(payload.get("mpmri_done")).lower() in YES_VALUES
        )
    )
    phoenix_confirmation_status = _resolve_phoenix_confirmation_status(
        payload,
        points=points,
        phoenix_threshold=phoenix_threshold,
        phoenix_threshold_reached=phoenix_threshold_reached,
        biopsy_proven=biopsy_proven,
        radiographic_local=radiographic_local,
    )
    bounce_suspected = _compute_bounce_suspected(
        payload,
        points=points,
        psa_nadir=psa_nadir,
    )
    psadt_months = _safe_float(payload.get("psadt_months") or payload.get("psa_doubling_time_months"))
    if psadt_months is None:
        psadt_months = _derive_psadt_months(points)
    if phoenix_delta is None:
        phoenix_status = "not_assessable"
    elif phoenix_threshold_reached:
        phoenix_status = "met"
    else:
        phoenix_status = "not_met"

    if biopsy_proven:
        failure_confirmation_basis = "biopsy_proven_local_failure"
    elif radiographic_local:
        failure_confirmation_basis = "radiographic_local_failure"
    elif phoenix_confirmation_status in {"confirmed_explicit", "confirmed_longitudinal"}:
        failure_confirmation_basis = "phoenix_confirmed"
    elif phoenix_status == "met":
        failure_confirmation_basis = "phoenix_threshold_only"
    elif bounce_suspected:
        failure_confirmation_basis = "bounce_suspected"
    else:
        failure_confirmation_basis = "indeterminate"

    confirmed_local_failure = failure_confirmation_basis in {
        "phoenix_confirmed",
        "biopsy_proven_local_failure",
        "radiographic_local_failure",
    }
    if bounce_suspected and not biopsy_proven:
        confirmed_local_failure = False

    salvage_release_status = "not_ready_missing_failure_definition"
    if failure_confirmation_basis in {"phoenix_confirmed", "biopsy_proven_local_failure", "radiographic_local_failure"}:
        salvage_release_status = "ready_for_restaging_gate"
    elif failure_confirmation_basis == "phoenix_threshold_only":
        salvage_release_status = "pending_longitudinal_confirmation"
    elif bounce_suspected:
        salvage_release_status = "blocked_bounce_suspected"

    required_missing_fields: list[str] = []
    if psa_current is None:
        required_missing_fields.append("psa_current")
    if psa_nadir is None and phoenix_status == "not_assessable":
        required_missing_fields.append("psa_nadir")
    if phoenix_delta is None:
        required_missing_fields.append("phoenix_delta")
    if phoenix_status == "met" and phoenix_confirmation_status == "threshold_only_unconfirmed":
        required_missing_fields.append("psa_history")
    if failure_confirmation_basis == "indeterminate":
        required_missing_fields.extend(
            [
                "biopsy_proven_local_recurrence",
                "mpmri_done",
                "mpmri_localized_recurrence",
            ]
        )

    rationale_parts: list[str] = []
    if phoenix_status == "met":
        rationale_parts.append("El PSA actual alcanzó el umbral Phoenix (nadir + 2 ng/mL).")
    elif phoenix_status == "not_met":
        rationale_parts.append("El incremento de PSA todavía no cumple Phoenix.")
    else:
        rationale_parts.append("No existe información suficiente para cerrar la definición de Phoenix.")
    if phoenix_confirmation_status == "confirmed_longitudinal":
        rationale_parts.append("La serie longitudinal ya confirma el umbral Phoenix en determinaciones separadas.")
    elif phoenix_confirmation_status == "threshold_only_unconfirmed":
        rationale_parts.append("El umbral Phoenix se alcanzó, pero todavía falta soporte longitudinal suficiente para liberar salvage curativo.")
    if bounce_suspected:
        rationale_parts.append("El patrón temporal es compatible con bounce post-braquiterapia y exige cautela antes de rescate curativo.")
    if failure_confirmation_basis == "biopsy_proven_local_failure":
        rationale_parts.append("Existe confirmación histológica de recurrencia local.")
    elif failure_confirmation_basis == "radiographic_local_failure":
        rationale_parts.append("La imagen local documenta recurrencia confinada y utilizable para salvage.")

    return {
        "phoenix_status": phoenix_status,
        "phoenix_threshold": phoenix_threshold,
        "phoenix_delta": phoenix_delta,
        "psa_nadir": psa_nadir,
        "psa_nadir_date": str(payload.get("psa_nadir_date") or derived_nadir_date or ""),
        "psa_current": psa_current,
        "psa_history_points": points,
        "phoenix_threshold_reached": phoenix_threshold_reached,
        "phoenix_confirmation_status": phoenix_confirmation_status,
        "psadt_months": psadt_months,
        "bounce_suspected": bounce_suspected,
        "salvage_release_status": salvage_release_status,
        "failure_confirmation_basis": failure_confirmation_basis,
        "confirmed_local_failure": confirmed_local_failure,
        "required_missing_fields": _dedupe(required_missing_fields),
        "rationale": " ".join(rationale_parts).strip(),
    }


def build_post_rt_local_salvage_ranking(
    payload: dict[str, Any],
    *,
    failure_definition: dict[str, Any],
    psma_impact: dict[str, Any],
) -> dict[str, Any]:
    failure_confirmed = bool(failure_definition.get("confirmed_local_failure"))
    pattern, disseminated, oligomet = _systemic_psma_pattern(payload, psma_impact)
    urinary_burden = _burden_level(payload.get("urinary_burden"))
    incontinence_burden = _burden_level(payload.get("incontinence_burden"))
    bowel_burden = _burden_level(payload.get("bowel_burden"))
    rectal_toxicity_grade = _safe_int(payload.get("rectal_toxicity_grade")) or 0
    prostate_volume = _safe_float(payload.get("prostate_volume"))
    expertise_available = _normalize_text(payload.get("salvage_expertise_available")).lower()
    expertise_known = expertise_available not in {"", "desconocido", "unknown"}
    expertise_positive = expertise_available in YES_VALUES if expertise_known else False
    stricture_history = _is_true(payload.get("urethral_stricture_history"))
    surgery_fit = _fit_for_salvage_surgery(payload)
    psma_done = _normalize_text(payload.get("psma_pet_done")).lower() in YES_VALUES
    conventional_restaging_complete = all(
        _is_present(payload.get(field))
        for field in ["conventional_imaging_modality", "conventional_imaging_date", "psma_downgrade_reason"]
    )
    systemic_restaging_complete = psma_done or conventional_restaging_complete
    local_site = _normalize_text(payload.get("local_recurrence_site")).lower()
    focal_local = _is_true(payload.get("mpmri_localized_recurrence")) or any(
        token in local_site
        for token in {"gland", "focal", "apex", "base", "peripheral", "bed", "anastomosis"}
    )
    salvage_release_status = str(failure_definition.get("salvage_release_status") or "")

    local_required_fields = [
        "prior_rt_modality",
        "prior_rt_dose",
        "prior_rt_fields",
        "biopsy_proven_local_recurrence",
        "biopsy_date",
        "biopsy_grade_group",
        "mpmri_done",
        "mpmri_date",
        "mpmri_localized_recurrence",
        "local_recurrence_site",
        "urinary_burden",
        "incontinence_burden",
        "urethral_stricture_history",
        "bowel_burden",
        "rectal_toxicity_grade",
        "prostate_volume",
        "anesthesia_surgical_fitness",
        "salvage_expertise_available",
        "psma_pet_done",
    ]
    if psma_done:
        local_required_fields.extend(
            [
                "psma_radioligand",
                "psma_rads_score",
                "psma_uptake_pattern",
                "psma_stage_after_psma",
            ]
        )
    else:
        local_required_fields.extend(
            [
                "conventional_imaging_modality",
                "conventional_imaging_date",
                "psma_downgrade_reason",
            ]
        )

    salvage_gate_missing: list[str] = []
    if salvage_release_status == "pending_longitudinal_confirmation":
        salvage_gate_missing.append("psa_history")
    if salvage_release_status == "blocked_bounce_suspected":
        salvage_gate_missing.append("bounce_suspected")
    if not _is_true(payload.get("biopsy_proven_local_recurrence")):
        salvage_gate_missing.append("biopsy_proven_local_recurrence")
    if not _is_present(payload.get("biopsy_date")):
        salvage_gate_missing.append("biopsy_date")
    if not _is_present(payload.get("mpmri_done")):
        salvage_gate_missing.append("mpmri_done")
    if not _is_true(payload.get("mpmri_localized_recurrence")):
        salvage_gate_missing.append("mpmri_localized_recurrence")
    if not _is_present(payload.get("local_recurrence_site")):
        salvage_gate_missing.append("local_recurrence_site")
    if not psma_done and not conventional_restaging_complete:
        salvage_gate_missing.extend(
            [
                "conventional_imaging_modality",
                "conventional_imaging_date",
                "psma_downgrade_reason",
            ]
        )
    if psma_done:
        for field in ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_stage_after_psma"]:
            if not _is_present(payload.get(field)):
                salvage_gate_missing.append(field)

    required_missing_fields = _dedupe(
        list(failure_definition.get("required_missing_fields") or [])
        + salvage_gate_missing
        + [field for field in local_required_fields if not _is_present(payload.get(field))]
    )
    salvage_gate_missing = _dedupe(salvage_gate_missing)
    salvage_gate_reason = ""
    if salvage_gate_missing:
        salvage_gate_reason = (
            "El salvage curativo sigue bloqueado hasta cerrar confirmación longitudinal suficiente, "
            "restadificación anatómica/local y la triada PSMA o downgrade convencional + mpMRI + biopsia transperineal."
        )

    entries = [
        {
            "regimen_code": "SALVAGE_PROSTATECTOMY",
            "name": "Salvage prostatectomy",
            "description": "Rescate quirúrgico después de radioterapia cuando persiste una vía local técnicamente defendible.",
            "dose": "Cirugía de rescate con intención curativa",
            "route": "Cirugía",
            "schedule": "Según board urooncológico y preparación preoperatoria",
            "score": 72.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_CRYOTHERAPY",
            "name": "Cryotherapy de rescate",
            "description": "Ablación focal o glandular en recurrencia localizada post-RT seleccionada.",
            "dose": "Crioterapia focal o hemiablación",
            "route": "Ablación",
            "schedule": "Procedimiento único con control posterior dirigido",
            "score": 68.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_HIFU",
            "name": "HIFU de rescate",
            "description": "Ultrasonido focalizado de alta intensidad como rescate local en lesión confinada.",
            "dose": "HIFU focal/glandular",
            "route": "Ablación",
            "schedule": "Procedimiento único guiado por imagen",
            "score": 66.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_BRACHYTHERAPY",
            "name": "Salvage brachytherapy",
            "description": "Braquiterapia de rescate en recurrencia intraprostática seleccionada con toxicidad rectal aceptable.",
            "dose": "Braquiterapia focal o parcial",
            "route": "Braquiterapia",
            "schedule": "Planeación dosimétrica y tratamiento dirigido",
            "score": 64.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "PSMA_GUIDED_MDT",
            "name": "MDT / SBRT guiada por PSMA",
            "description": "Control dirigido de enfermedad oligorrecurrente cuando el patrón ya no es exclusivamente glandular.",
            "dose": "SBRT 30-35 Gy en 3-5 fracciones o estrategia MDT equivalente",
            "route": "Radioterapia estereotáctica / MDT",
            "schedule": "Tratamiento dirigido tras comité",
            "score": 62.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SYSTEMIC_RESTAGING",
            "name": "Redirección sistémica / reestadificación",
            "description": "La vía local curativa se cierra y la prioridad pasa a reestadificar o secuenciar tratamiento sistémico.",
            "dose": "Restaging sistémico",
            "route": "Imagen / secuenciación",
            "schedule": "Redefinir carril sistémico con comité",
            "score": 40.0,
            "family_code": "observation_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
    ]

    for entry in entries:
        code = entry["regimen_code"]
        if disseminated:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 96.0
                entry["why_this_rank"] = ["El patrón PSMA diseminado o estadio M1b/M1c ya no sostiene salvage local aislado."]
            else:
                entry["hard_blocks"].append("PSMA diseminada o estadio metastásico incompatible con salvage local aislado.")
                entry["score"] -= 60
        elif not failure_confirmed:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 82.0
                entry["caution_flags"].append("Aún no se ha cerrado Phoenix ni confirmación local equivalente.")
                entry["why_this_rank"] = ["Todavía falta confirmar fracaso post-RT antes de fijar salvage curativo."]
            else:
                entry["hard_blocks"].append("No existe definición Phoenix cerrada ni confirmación local equivalente.")
                entry["score"] -= 45
        elif oligomet:
            if code == "PSMA_GUIDED_MDT":
                entry["score"] = 88.0
                entry["why_this_rank"] = ["El patrón oligorrecurrente dirigido por PSMA favorece MDT/SBRT por encima del salvage glandular puro."]
            elif code == "SYSTEMIC_RESTAGING":
                entry["score"] = 55.0
                entry["caution_flags"].append("La vía local no está completamente cerrada, pero la MDT domina primero.")
            else:
                entry["caution_flags"].append("La enfermedad ya no parece puramente glandular; la MDT puede ser más coherente.")
                entry["score"] -= 10
        else:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 35.0
                entry["caution_flags"].append("La vía local sigue abierta y no debe abandonarse sin un redirector explícito.")

        if code != "SYSTEMIC_RESTAGING" and salvage_gate_missing:
            entry["hard_blocks"].append(
                "El salvage curativo sigue bloqueado hasta cerrar PSMA o downgrade convencional, mpMRI localizada y biopsia transperineal documentada."
            )
            entry["score"] -= 24

        if code == "SALVAGE_PROSTATECTOMY":
            if not surgery_fit:
                entry["hard_blocks"].append("La aptitud quirúrgica/anestésica no sostiene salvage prostatectomy.")
                entry["score"] -= 35
            if urinary_burden == "high" or incontinence_burden == "high":
                entry["caution_flags"].append("La carga urinaria o la incontinencia elevan la morbilidad quirúrgica de rescate.")
                entry["score"] -= 14
            if stricture_history:
                entry["caution_flags"].append("El antecedente de estenosis uretral complica la reconstrucción quirúrgica.")
                entry["score"] -= 18
            if rectal_toxicity_grade >= 3:
                entry["hard_blocks"].append("La toxicidad rectal grado alto reduce drásticamente la factibilidad quirúrgica.")
                entry["score"] -= 18
        elif code == "SALVAGE_CRYOTHERAPY":
            if not focal_local:
                entry["caution_flags"].append("La recurrencia no se ve claramente focal; cryo pierde precisión.")
                entry["score"] -= 10
            if urinary_burden == "high" or stricture_history:
                entry["caution_flags"].append("La carga urinaria/estenosis previa limita seguridad funcional de cryotherapy.")
                entry["score"] -= 14
            if not surgery_fit:
                entry["score"] += 4
                entry["why_this_rank"] = list(entry.get("why_this_rank") or []) + ["La ablación puede ser más realista que cirugía mayor si la aptitud quirúrgica es limitada."]
        elif code == "SALVAGE_HIFU":
            if not focal_local:
                entry["caution_flags"].append("HIFU funciona mejor con recurrencia intraprostática bien localizada.")
                entry["score"] -= 12
            if prostate_volume is not None and prostate_volume > 55:
                entry["caution_flags"].append("El volumen prostático grande reduce la eficiencia del HIFU de rescate.")
                entry["score"] -= 10
            if not expertise_positive and expertise_known:
                entry["hard_blocks"].append("No hay experiencia local documentada para HIFU de rescate.")
                entry["score"] -= 20
        elif code == "SALVAGE_BRACHYTHERAPY":
            modality = _prior_rt_modality(payload)
            if modality in {"LDR", "LDR_BRACHY", "HDR", "HDR_BRACHY", "BRACHY"}:
                entry["caution_flags"].append("La reirradiación con braquiterapia tras braquiterapia previa exige cautela extrema.")
                entry["score"] -= 18
            if rectal_toxicity_grade >= 2 or bowel_burden == "high":
                entry["hard_blocks"].append("La toxicidad rectal/bowel previa penaliza fuertemente salvage brachytherapy.")
                entry["score"] -= 24
            if urinary_burden == "high":
                entry["caution_flags"].append("La toxicidad urinaria previa limita braquiterapia de rescate.")
                entry["score"] -= 12
        elif code == "PSMA_GUIDED_MDT":
            if not oligomet:
                entry["hard_blocks"].append("La MDT post-RT requiere patrón oligorrecurrente claramente dirigido.")
                entry["score"] -= 45
        elif code == "SYSTEMIC_RESTAGING":
            if not disseminated and not oligomet and failure_confirmed:
                entry["why_this_rank"] = ["Debe permanecer visible como alternativa si la matriz local se cierra por toxicidad o factibilidad."]

        if expertise_known and not expertise_positive and code != "SYSTEMIC_RESTAGING":
            entry["caution_flags"].append("No existe experiencia local documentada; discutir referencia a centro con expertise.")
            entry["score"] -= 12

        entry["score"] = round(entry["score"], 1)
        entry["eligibility_status"] = "eligible_nonpreferred"
        if entry["hard_blocks"]:
            entry["eligibility_status"] = "ineligible"
        elif entry["caution_flags"]:
            entry["eligibility_status"] = "eligible_with_caution"

    ranked = sorted(entries, key=lambda item: item.get("score", 0), reverse=True)
    top = ranked[0] if ranked else {}
    if top and top["eligibility_status"] != "ineligible":
        top["eligibility_status"] = "preferred"

    dominant_local_option = {}
    if top and top["regimen_code"] != "SYSTEMIC_RESTAGING" and top["eligibility_status"] == "preferred":
        dominant_local_option = deepcopy(top)

    return {
        "ranked_options": ranked,
        "dominant_local_option": dominant_local_option,
        "required_missing_fields": required_missing_fields,
        "salvage_gate_missing_fields": salvage_gate_missing,
        "salvage_gate_reason": salvage_gate_reason,
        "salvage_release_status": salvage_release_status,
        "systemic_restaging_complete": systemic_restaging_complete,
        "pattern": pattern,
        "disseminated": disseminated,
        "oligometastatic": oligomet,
    }


def build_post_rt_transition_bundle(
    payload: dict[str, Any],
    *,
    failure_definition: dict[str, Any],
    local_salvage_ranking: dict[str, Any],
) -> dict[str, Any]:
    ranked = list(local_salvage_ranking.get("ranked_options") or [])
    top = dict(ranked[0] if ranked else {})
    missing = list(local_salvage_ranking.get("required_missing_fields") or [])
    salvage_gate_missing = list(local_salvage_ranking.get("salvage_gate_missing_fields") or [])
    salvage_release_status = str(failure_definition.get("salvage_release_status") or "")
    if salvage_release_status == "blocked_bounce_suspected":
        transition_status = "pending_confirmation"
        reason = "La cinética actual es compatible con bounce post-braquiterapia y no debe liberar salvage curativo todavía."
    elif not failure_definition.get("confirmed_local_failure"):
        transition_status = "pending_confirmation"
        reason = "No debe abrirse salvage post-RT curativo hasta cumplir Phoenix con soporte longitudinal o confirmar falla local equivalente."
    elif local_salvage_ranking.get("disseminated"):
        transition_status = "redirect_systemic"
        reason = "La distribución PSMA ya no sostiene rescate local aislado."
    elif local_salvage_ranking.get("oligometastatic"):
        transition_status = "mdt_candidate"
        reason = "El patrón oligorrecurrente dirigido por PSMA favorece MDT/SBRT o rescate multimodal."
    elif salvage_gate_missing:
        transition_status = "restate_before_decision"
        reason = "La vía post-RT ya detectó una señal real de recurrencia, pero el salvage curativo sigue bloqueado hasta completar restadificación local y sistémica."
    elif top and top.get("eligibility_status") == "preferred" and top.get("regimen_code") != "SYSTEMIC_RESTAGING":
        transition_status = "local_salvage_candidate"
        reason = f"La vía local sigue abierta y la modalidad dominante es {top.get('name') or top.get('regimen_code')}."
    else:
        transition_status = "restate_before_decision"
        reason = "Aún falta cerrar restaging y factibilidad antes de fijar la modalidad de salvage."
    return {
        "transition_status": transition_status,
        "care_goal": "curative_local_control" if transition_status in {"local_salvage_candidate", "mdt_candidate"} else "restate_before_commitment" if transition_status in {"pending_confirmation", "restate_before_decision"} else "systemic_redirection",
        "trigger_reasons": _dedupe([reason, failure_definition.get("rationale")]),
        "required_missing_fields": _dedupe(missing + salvage_gate_missing),
        "salvage_release_status": salvage_release_status,
        "salvage_gate_missing_fields": salvage_gate_missing,
        "dominant_local_option": deepcopy(local_salvage_ranking.get("dominant_local_option") or {}),
    }


def build_post_rt_schedule_overlay(transition_bundle: dict[str, Any]) -> dict[str, Any]:
    status = _normalize_text(transition_bundle.get("transition_status"))
    if status == "redirect_systemic":
        return {
            "schedule_primary_intent": "Cerrar vía local y redirigir a secuencia sistémica",
            "cadence_adjustment_reasons": [
                "Completar reestadificación sistémica",
                "Redefinir siguiente línea con comité multidisciplinario",
            ],
            "recommended_events": ["PET/PSMA estructurado", "Tumor board post-RT", "Secuenciación sistémica"],
        }
    if status == "mdt_candidate":
        return {
            "schedule_primary_intent": "Cerrar ruta oligorrecurrente dirigida",
            "cadence_adjustment_reasons": [
                "Confirmar burden PSMA dirigido",
                "Definir MDT/SBRT o estrategia combinada",
            ],
            "recommended_events": ["Tumor board", "Planeación MDT", "Correlación mpMRI/PSMA"],
        }
    if status == "local_salvage_candidate":
        return {
            "schedule_primary_intent": "Sostener salvage local post-RT",
            "cadence_adjustment_reasons": [
                "Correlacionar anatomía local y toxicidad previa",
                "Elegir modalidad de rescate con mayor plausibilidad curativa",
            ],
            "recommended_events": ["Valoración uro-oncológica", "Planeación de salvage local", "Revisión funcional GU/GI"],
        }
    return {
        "schedule_primary_intent": "Cerrar confirmación de falla post-RT",
        "cadence_adjustment_reasons": [
            "Confirmar Phoenix o evidencia local equivalente",
            "Completar reestadificación antes de decidir salvage",
        ],
        "recommended_events": ["PSA/nadir documentado", "mpMRI/biopsia local", "PSMA estructurado"],
    }
