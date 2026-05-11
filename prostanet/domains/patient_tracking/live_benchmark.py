from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from prostanet.domains.patient_tracking.survival_analysis import build_survival_curve_payload
from prostanet.domains.patient_tracking.survival_endpoints import PUBLISHED_MEDIANS, SurvivalEndpointService
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label

BENCHMARKABLE_ADVANCED_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}


def _default_benchmark_reliability() -> dict[str, Any]:
    return {
        "cohort_size": 0,
        "percentile_available": False,
        "curve_available": False,
        "published_reference_available": False,
        "confidence_label": "not_available",
        "cohort_tier": "none",
    }


def is_live_benchmark_applicable_state(state: str) -> bool:
    return str(state or "") in BENCHMARKABLE_ADVANCED_STATES


def build_live_benchmark_placeholder(
    *,
    state: str = "",
    management_track: str = "",
    status: str = "deferred",
    show: bool | None = None,
    narrative: str | None = None,
) -> dict[str, Any]:
    applicable = is_live_benchmark_applicable_state(state)
    resolved_status = "not_applicable" if not applicable else status
    resolved_show = bool(applicable) if show is None else bool(show)
    if narrative is None:
        if applicable:
            narrative = "Benchmark Vivo se carga desde snapshots persistidos y puede hidratarse de forma diferida."
        else:
            narrative = "Benchmark Vivo no aplica para este escenario clínico."
    return {
        "status": resolved_status,
        "show": resolved_show and resolved_status != "not_applicable",
        "state": str(state or ""),
        "management_track": str(management_track or ""),
        "primary_endpoint_type": "",
        "primary_endpoint_label": "Comparación longitudinal",
        "patient_endpoint": {},
        "patient_percentile": None,
        "cohort_size": 0,
        "cohort_tier": "none",
        "curve": {},
        "published_reference": {"available": False},
        "flags": ["snapshot_pending"] if applicable else [],
        "narrative": narrative,
        "reliability": _default_benchmark_reliability(),
    }


def resolve_live_benchmark_from_snapshot(
    record: dict[str, Any] | None,
    *,
    state: str = "",
    management_track: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    patient_record = record or {}
    snapshot_container = dict(
        ((patient_record.get("latest_trial_benchmark_snapshot") or {}).get("benchmark_snapshot") or {})
    )
    live_benchmark = dict(snapshot_container.get("live_benchmark") or {})
    reliability = dict(snapshot_container.get("benchmark_reliability") or {})
    if live_benchmark:
        requested_state = str(state or "")
        snapshot_state = str(live_benchmark.get("state") or "")
        if (
            is_live_benchmark_applicable_state(requested_state)
            and live_benchmark.get("status") == "not_applicable"
            and not is_live_benchmark_applicable_state(snapshot_state)
        ):
            placeholder = build_live_benchmark_placeholder(
                state=requested_state,
                management_track=management_track,
            )
            return placeholder, dict(placeholder.get("reliability") or _default_benchmark_reliability())
        if reliability and not live_benchmark.get("reliability"):
            live_benchmark["reliability"] = dict(reliability)
        live_benchmark.setdefault("status", "ready")
        live_benchmark.setdefault("show", live_benchmark.get("status") != "not_applicable")
        live_benchmark.setdefault("state", str(state or live_benchmark.get("state") or ""))
        live_benchmark.setdefault(
            "management_track",
            str(management_track or live_benchmark.get("management_track") or ""),
        )
        return live_benchmark, dict(live_benchmark.get("reliability") or reliability or _default_benchmark_reliability())
    placeholder = build_live_benchmark_placeholder(
        state=state,
        management_track=management_track,
    )
    return placeholder, dict(placeholder.get("reliability") or _default_benchmark_reliability())


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _reconciled_state(record: dict[str, Any]) -> str:
    return str(
        record.get("reconciled_state")
        or (record.get("latest_assessment") or {}).get("state")
        or (record.get("prior_history") or {}).get("current_state")
        or ""
    )


def _management_track(record: dict[str, Any]) -> str:
    return str(
        (record.get("latest_signal_snapshot") or {}).get("reconciled_management_track")
        or record.get("management_track")
        or ""
    )


def _line_context(record: dict[str, Any]) -> str:
    latest_treatment = _latest(record.get("treatments") or [], "start_date")
    return str(latest_treatment.get("line_of_therapy_context") or "")


def _current_regimen(record: dict[str, Any]) -> str:
    latest_treatment = _latest(record.get("treatments") or [], "start_date")
    return str(latest_treatment.get("drug_scheme") or latest_treatment.get("current_treatment") or "")


def _metastatic_signature(record: dict[str, Any], state: str) -> str:
    baseline = record.get("baseline") or {}
    latest_followup = _latest(record.get("follow_ups") or [], "visit_date")
    site = str(
        latest_followup.get("metastasis_site")
        or baseline.get("metastasis_site")
        or baseline.get("m_substage_resolved")
        or ""
    ).lower()
    if state in {"mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"}:
        return "high_volume"
    if state in {"mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous"}:
        return "low_volume"
    if state == "m1_crpc":
        if any(token in site for token in ("visceral", "m1c")):
            return "visceral"
        if any(token in site for token in ("bone", "hueso", "m1b")):
            return "bone_dominant"
        return "metastatic_other"
    return "default"


def _benchmark_family(record: dict[str, Any]) -> str:
    snapshot = dict((record.get("latest_trial_benchmark_snapshot") or {}).get("current_trial_profile") or {})
    if snapshot:
        return str(snapshot.get("benchmark_family") or "")
    return ""


def _choose_primary_endpoint(state: str) -> dict[str, str]:
    if state == "m0_crpc":
        return {"endpoint_type": "MFS", "label": "Supervivencia libre de metástasis"}
    if state == "m1_crpc":
        return {"endpoint_type": "rPFS", "label": "Supervivencia libre de progresión radiográfica"}
    if state in {
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_high_volume",
    }:
        return {"endpoint_type": "time_to_next_line", "label": "Tiempo a siguiente línea"}
    return {"endpoint_type": "", "label": ""}


def _published_reference(patient: dict[str, Any], state: str) -> dict[str, Any]:
    regimen = _current_regimen(patient).upper()
    key = ""
    if state == "m0_crpc":
        if "ENZALUTAMIDE" in regimen:
            key = "MFS_enzalutamide_m0CRPC"
        elif "APALUTAMIDE" in regimen:
            key = "MFS_apalutamide_m0CRPC"
    elif state == "m1_crpc":
        if "ENZALUTAMIDE" in regimen:
            key = "rPFS_enzalutamide_mCRPC"
        elif "DOCETAXEL" in regimen:
            key = "OS_mCRPC_post_docetaxel"
    elif state in {
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_high_volume",
    }:
        if "DOCETAXEL" in regimen and "DAROLUTAMIDE" in regimen:
            key = "OS_mHSPC_triplet"
        elif "DOCETAXEL" in regimen:
            key = "OS_mHSPC_ADT_docetaxel"
        elif "ADT" in regimen and not any(token in regimen for token in ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE")):
            key = "OS_mHSPC_ADT_alone"
    reference = dict(PUBLISHED_MEDIANS.get(key) or {})
    return {
        "key": key,
        "label": reference.get("reference", ""),
        "median_months": reference.get("median_months"),
        "year": reference.get("year"),
        "available": bool(reference),
        "regimen_label": regimen_label(_current_regimen(patient)),
    }


def _endpoint_for_patient(patient: dict[str, Any], endpoint_type: str, state: str) -> dict[str, Any]:
    status = SurvivalEndpointService.compute_endpoints(patient, state)
    endpoint = next((item.to_dict() for item in status.endpoints if item.endpoint_type == endpoint_type), None)
    if endpoint:
        return endpoint
    return {
        "endpoint_type": endpoint_type,
        "duration_months": None,
        "censored": True,
        "end_event": None,
    }


def _cohort_tiers(patient: dict[str, Any], state: str, management_track: str) -> list[tuple[str, Callable[[dict[str, Any]], bool]]]:
    line_context = _line_context(patient)
    metastatic_signature = _metastatic_signature(patient, state)
    family = _benchmark_family(patient)
    return [
        (
            "exact",
            lambda record: _reconciled_state(record) == state
            and _management_track(record) == management_track
            and _line_context(record) == line_context
            and _metastatic_signature(record, state) == metastatic_signature,
        ),
        (
            "state_track",
            lambda record: _reconciled_state(record) == state and _management_track(record) == management_track,
        ),
        (
            "state_only",
            lambda record: _reconciled_state(record) == state,
        ),
        (
            "family",
            lambda record: bool(family) and _benchmark_family(record) == family,
        ),
    ]


def _find_comparable_cohort(patient: dict[str, Any], records: list[dict[str, Any]], state: str, management_track: str) -> tuple[str, list[dict[str, Any]]]:
    patient_id = (patient.get("identity") or {}).get("id")
    comparable = [record for record in records if record and (record.get("identity") or {}).get("id") != patient_id]
    best_tier = "none"
    best_matches: list[dict[str, Any]] = []
    for tier_name, predicate in _cohort_tiers(patient, state, management_track):
        matches = [record for record in comparable if predicate(record)]
        if len(matches) >= 10:
            return tier_name, matches
        if len(matches) > len(best_matches):
            best_tier = tier_name
            best_matches = matches
    return best_tier, best_matches


def _percentile(duration: float | None, cohort_rows: list[dict[str, Any]]) -> float | None:
    if duration is None or len(cohort_rows) < 10:
        return None
    durations = sorted(float(row["duration_months"]) for row in cohort_rows if row.get("duration_months") is not None)
    if not durations:
        return None
    count = sum(1 for value in durations if value <= duration)
    return round((count / len(durations)) * 100.0, 1)


def _flags_for_benchmark(
    *,
    percentile: float | None,
    cohort_size: int,
    duration: float | None,
) -> list[str]:
    flags: list[str] = []
    if duration is None or duration < 3:
        flags.append("seguimiento_insuficiente")
    if cohort_size < 10:
        flags.append("comparabilidad_limitada")
    elif percentile is not None and percentile < 25:
        flags.append("por_debajo_de_cohorte_similar")
    elif percentile is not None:
        flags.append("dentro_de_rango_esperado")
    return flags


def _narrative_for_benchmark(
    *,
    state: str,
    percentile: float | None,
    cohort_size: int,
    published_reference: dict[str, Any],
    endpoint_label: str,
) -> str:
    if cohort_size < 10:
        if published_reference.get("available"):
            return (
                f"La cohorte institucional similar todavía es pequeña para un percentil confiable; "
                f"se usa como contexto la referencia publicada {published_reference.get('label')}."
            )
        return "La cohorte institucional similar aún es insuficiente para un benchmarking robusto en tiempo real."
    if percentile is not None and percentile < 25:
        return f"El paciente se ubica por debajo del percentil 25 de la cohorte institucional similar para {endpoint_label.lower()}."
    if percentile is not None:
        return f"El paciente se mantiene dentro del rango observado de la cohorte institucional similar para {endpoint_label.lower()}."
    return f"Benchmark institucional disponible para {state}, pero sin percentil individual utilizable todavía."


def build_live_benchmark(
    patient: dict[str, Any],
    cohort_records: list[dict[str, Any]],
    *,
    state: str = "",
    management_track: str = "",
) -> dict[str, Any]:
    resolved_state = str(state or _reconciled_state(patient))
    resolved_track = str(management_track or _management_track(patient))
    if resolved_state == "adt_progression_verification":
        return {
            "status": "not_applicable",
            "show": False,
            "state": resolved_state,
            "narrative": "No se muestra benchmark de outcome duro mientras la progresión bajo ADT sigue pendiente de adjudicación formal.",
            "flags": ["comparabilidad_limitada"],
            "reliability": {
                "cohort_size": 0,
                "percentile_available": False,
                "curve_available": False,
                "published_reference_available": False,
                "confidence_label": "not_applicable",
                "cohort_tier": "none",
            },
        }
    if resolved_state not in BENCHMARKABLE_ADVANCED_STATES:
        return {
            "status": "not_applicable",
            "show": False,
            "state": resolved_state,
            "narrative": "Benchmark Vivo v1 solo está disponible en escenarios avanzados.",
            "flags": [],
            "reliability": {
                "cohort_size": 0,
                "percentile_available": False,
                "curve_available": False,
                "published_reference_available": False,
                "confidence_label": "not_applicable",
                "cohort_tier": "none",
            },
        }

    endpoint_info = _choose_primary_endpoint(resolved_state)
    endpoint_type = endpoint_info["endpoint_type"]
    patient_endpoint = _endpoint_for_patient(patient, endpoint_type, resolved_state)
    cohort_tier, comparable_records = _find_comparable_cohort(patient, cohort_records, resolved_state, resolved_track)
    cohort_curve = build_survival_curve_payload(comparable_records, endpoint_type, state_filter=resolved_state) if comparable_records else {"curve": {}}
    cohort_dataset = list(cohort_curve.get("dataset") or [])
    percentile = _percentile(patient_endpoint.get("duration_months"), cohort_dataset)
    published_reference = _published_reference(patient, resolved_state)
    flags = _flags_for_benchmark(
        percentile=percentile,
        cohort_size=len(comparable_records),
        duration=patient_endpoint.get("duration_months"),
    )
    narrative = _narrative_for_benchmark(
        state=resolved_state,
        percentile=percentile,
        cohort_size=len(comparable_records),
        published_reference=published_reference,
        endpoint_label=endpoint_info["label"],
    )
    confidence_label = "high" if len(comparable_records) >= 25 else "medium" if len(comparable_records) >= 10 else "limited"
    return {
        "status": "ready" if endpoint_type else "not_applicable",
        "show": bool(endpoint_type),
        "state": resolved_state,
        "management_track": resolved_track,
        "primary_endpoint_type": endpoint_type,
        "primary_endpoint_label": endpoint_info["label"],
        "patient_endpoint": patient_endpoint,
        "patient_percentile": percentile,
        "cohort_tier": cohort_tier,
        "cohort_size": len(comparable_records),
        "curve": cohort_curve.get("curve", {}),
        "institutional_curve": cohort_curve.get("curve", {}),
        "cohort_dataset_preview": cohort_dataset[:50],
        "published_reference": published_reference,
        "current_regimen_label": regimen_label(_current_regimen(patient)),
        "flags": flags,
        "narrative": narrative,
        "reliability": {
            "cohort_size": len(comparable_records),
            "percentile_available": percentile is not None,
            "curve_available": bool((cohort_curve.get("curve") or {}).get("times")),
            "published_reference_available": bool(published_reference.get("available")),
            "confidence_label": confidence_label,
            "cohort_tier": cohort_tier,
        },
    }


def build_live_benchmark_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    states = {}
    ready_count = 0
    limited_count = 0
    for record in records:
        benchmark = build_live_benchmark(record, records)
        if benchmark.get("status") == "ready":
            ready_count += 1
        if str((benchmark.get("reliability") or {}).get("confidence_label") or "") == "limited":
            limited_count += 1
        state = str(benchmark.get("state") or _reconciled_state(record) or "unknown")
        bucket = states.setdefault(state, {"ready": 0, "limited": 0})
        bucket["ready"] += int(benchmark.get("status") == "ready")
        bucket["limited"] += int(str((benchmark.get("reliability") or {}).get("confidence_label") or "") == "limited")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ready_count": ready_count,
        "limited_count": limited_count,
        "states": states,
    }
