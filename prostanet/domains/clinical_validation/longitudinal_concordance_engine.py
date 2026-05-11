from __future__ import annotations

from typing import Any

from prostanet.domains.clinical_validation.oracle_contracts import (
    build_action_oracle_contract,
    match_action_contract,
)


def _text(value: Any) -> str:
    return str(value or "")


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in str(text or "").lower()


def _contains_any(texts: list[str], needles: list[str]) -> bool:
    haystack = " | ".join(str(item or "") for item in texts).lower()
    return any(str(needle or "").lower() in haystack for needle in needles)


def _schedule_titles(snapshot: dict[str, Any]) -> list[str]:
    schedule = dict(snapshot.get("schedule") or {})
    items = list(schedule.get("active_schedule") or schedule.get("schedule") or [])
    return [str(item.get("label") or item.get("title") or item.get("event_type") or "") for item in items]


def _alert_titles(snapshot: dict[str, Any]) -> list[str]:
    labs = dict(snapshot.get("labs") or {})
    alerts = list(labs.get("active_alerts") or [])
    return [str(item.get("title") or item.get("label") or item.get("description") or "") for item in alerts]


def _guideline_basis(snapshot: dict[str, Any]) -> list[str]:
    schedule = dict(snapshot.get("schedule") or {})
    plan = dict(schedule.get("master_followup_plan") or {})
    basis = list(plan.get("guideline_basis") or [])
    if not basis:
        basis = list((snapshot.get("signals") or {}).get("guideline_basis") or [])
    return [str(item) for item in basis]


def _state(snapshot: dict[str, Any]) -> str:
    signals = dict(snapshot.get("signals") or {})
    return str(signals.get("effective_state") or signals.get("reconciled_state") or signals.get("state") or "")


def _track(snapshot: dict[str, Any]) -> str:
    signals = dict(snapshot.get("signals") or {})
    return str(signals.get("effective_management_track") or signals.get("reconciled_management_track") or signals.get("management_track") or "")


def _blocking_inputs(snapshot: dict[str, Any]) -> list[str]:
    signals = dict(snapshot.get("signals") or {})
    return [str(item) for item in list(signals.get("blocking_inputs") or [])]


def _ui_contradictions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    signals = dict(snapshot.get("signals") or {})
    return list(signals.get("ui_contradiction_flags") or [])


def _data_accumulation_complete(snapshot: dict[str, Any]) -> bool:
    patient = dict(snapshot.get("patient_record") or {})
    truth = dict(patient.get("longitudinal_truth_snapshot") or {})
    labs = dict(snapshot.get("labs") or {})
    return bool(
        truth.get("field_values")
        and patient.get("latest_clinically_decisive_visit")
        and labs.get("coverage", {}).get("series_count", 0) >= 1
    )


def _snapshot_field_values(snapshot: dict[str, Any]) -> dict[str, Any]:
    patient = dict(snapshot.get("patient_record") or {})
    truth = dict((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    values = {}
    for source in (
        patient.get("baseline") or {},
        truth,
        dict((patient.get("latest_assessment") or {}).get("input_snapshot") or {}),
        (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {},
        (((patient.get("stage_visits") or [{}])[-1].get("visit_bundle") or {}).get("payload") or {}) if patient.get("stage_visits") else {},
        (patient.get("biopsies") or [{}])[-1] if patient.get("biopsies") else {},
        patient.get("active_surveillance_protocol") or {},
        patient.get("active_surveillance") or {},
        patient.get("psma_structured_profile") or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida"):
                values[key] = value
    return values


def _supporting_action_texts(snapshot: dict[str, Any]) -> list[str]:
    texts = _schedule_titles(snapshot) + _alert_titles(snapshot)
    signals = dict(snapshot.get("signals") or {})
    mhspc_bundle = dict(signals.get("mhspc_copilot_bundle") or {})
    if bool(mhspc_bundle.get("rt_primary_candidate")):
        texts.append("RT al primario")
    if bool(mhspc_bundle.get("mdt_candidate")):
        texts.append("MDT")
    for bundle_key in ("post_rp_salvage_bundle", "post_rt_salvage_bundle"):
        bundle = dict(signals.get(bundle_key) or {})
        local_pathway = dict(bundle.get("local_salvage_pathway") or {})
        if bool(local_pathway.get("visible")):
            texts.append(str(local_pathway.get("recommended_path") or ""))
            texts.append(str(local_pathway.get("rationale") or ""))
    return [item for item in texts if str(item or "").strip()]


def _assertion(key: str, passed: bool, expected: Any, actual: Any, severity: str = "normal") -> dict[str, Any]:
    return {
        "key": key,
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
        "severity": severity,
    }


def evaluate_snapshot_against_oracle(snapshot: dict[str, Any], oracle: dict[str, Any]) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    expected_state = str(oracle.get("expected_effective_state") or "")
    if expected_state:
        actual_state = _state(snapshot)
        assertions.append(
            _assertion(
                "effective_state",
                actual_state == expected_state,
                expected_state,
                actual_state,
                severity="critical" if oracle.get("hard_critical") else "normal",
            )
        )

    expected_track_contains = str(oracle.get("expected_management_track_contains") or "")
    if expected_track_contains:
        actual_track = _track(snapshot)
        assertions.append(
            _assertion(
                "effective_management_track",
                _contains(actual_track, expected_track_contains),
                expected_track_contains,
                actual_track,
            )
        )

    action_contract = build_action_oracle_contract(
        oracle,
        fallback_label=str(oracle.get("expected_action_contains") or ""),
    )
    if action_contract.get("display_label"):
        next_best_action = dict(snapshot.get("next_best_action") or {})
        headline_texts = [
            _text(next_best_action.get("title") or next_best_action.get("headline") or next_best_action.get("recommended_action")),
        ]
        supporting_texts = _supporting_action_texts(snapshot)
        action_match = match_action_contract(
            headline_texts=headline_texts,
            supporting_texts=supporting_texts,
            contract=action_contract,
        )
        assertions.append(
            _assertion(
                "next_best_action",
                bool(action_match.get("matched")),
                action_contract.get("display_label"),
                {
                    "headline": headline_texts[0],
                    "supporting": supporting_texts[:5],
                    "matched_alias": action_match.get("matched_alias"),
                    "matched_visibility_layer": action_match.get("matched_visibility_layer"),
                },
                severity="critical" if oracle.get("hard_critical") else "normal",
            )
        )

    expected_schedule_keywords = [str(item) for item in list(oracle.get("expected_schedule_keywords") or []) if str(item or "").strip()]
    if expected_schedule_keywords:
        titles = _schedule_titles(snapshot)
        assertions.append(
            _assertion(
                "schedule_keywords",
                _contains_any(titles, expected_schedule_keywords),
                expected_schedule_keywords,
                titles,
            )
        )

    expected_missing_inputs = [str(item) for item in list(oracle.get("expected_missing_inputs") or []) if str(item or "").strip()]
    if expected_missing_inputs:
        actual_missing = _blocking_inputs(snapshot)
        available_fields = _snapshot_field_values(snapshot)
        already_present = all(item in available_fields for item in expected_missing_inputs)
        assertions.append(
            _assertion(
                "blocking_inputs",
                any(item in actual_missing for item in expected_missing_inputs) or already_present,
                expected_missing_inputs,
                actual_missing,
            )
        )

    expected_alert_keywords = [str(item) for item in list(oracle.get("expected_alert_keywords") or []) if str(item or "").strip()]
    if expected_alert_keywords:
        titles = _alert_titles(snapshot)
        assertions.append(
            _assertion(
                "alert_keywords",
                _contains_any(titles, expected_alert_keywords),
                expected_alert_keywords,
                titles,
                severity="critical" if oracle.get("hard_critical") else "normal",
            )
        )

    expected_guideline_basis_any = [str(item) for item in list(oracle.get("expected_guideline_basis_any") or []) if str(item or "").strip()]
    if expected_guideline_basis_any:
        basis = _guideline_basis(snapshot)
        assertions.append(
            _assertion(
                "guideline_basis",
                _contains_any(basis, expected_guideline_basis_any),
                expected_guideline_basis_any,
                basis,
                severity="critical" if oracle.get("hard_critical") else "normal",
            )
        )

    return assertions


def evaluate_seeded_case(case_payload: dict[str, Any]) -> dict[str, Any]:
    case_assertions = evaluate_snapshot_against_oracle(case_payload.get("baseline") or {}, case_payload.get("baseline_oracle") or {})
    visit_reports = []
    prompt_scores = []
    for visit in list(case_payload.get("visits") or []):
        snapshot = dict(visit.get("actual") or {})
        oracle = dict(visit.get("oracle") or {})
        visit_assertions = evaluate_snapshot_against_oracle(snapshot, oracle)
        actual_missing = set(_blocking_inputs(snapshot))
        expected_missing = set(str(item) for item in list(oracle.get("expected_missing_inputs") or []))
        if expected_missing:
            prompt_scores.append(len(actual_missing & expected_missing) / max(len(expected_missing), 1))
        visit_reports.append(
            {
                "step_index": visit.get("step_index"),
                "title": visit.get("title"),
                "visit_date": visit.get("visit_date"),
                "assertions": visit_assertions,
                "passed": all(item.get("passed") for item in visit_assertions) if visit_assertions else True,
            }
        )
        case_assertions.extend(visit_assertions)

    final_snapshot = dict(case_payload.get("final") or {})
    final_oracle = dict(case_payload.get("clinical_oracle") or {})
    final_assertions = evaluate_snapshot_against_oracle(final_snapshot, final_oracle)
    case_assertions.extend(final_assertions)
    ui_contradictions = _ui_contradictions(final_snapshot)
    guideline_passes = [item for item in case_assertions if item.get("key") == "guideline_basis"]
    guideline_concordance = (
        round(100 * sum(1 for item in guideline_passes if item.get("passed")) / len(guideline_passes), 1)
        if guideline_passes
        else 100.0
    )
    case_passed = all(item.get("passed") for item in case_assertions)
    critical_failure = any(item.get("severity") == "critical" and not item.get("passed") for item in case_assertions)
    return {
        "case_key": case_payload.get("case_key"),
        "scenario_id": case_payload.get("scenario_id"),
        "scenario_family": case_payload.get("scenario_family"),
        "title": case_payload.get("title"),
        "patient_id": case_payload.get("patient_id"),
        "patient_nss": case_payload.get("patient_nss", ""),
        "expected": {
            "baseline_oracle": case_payload.get("baseline_oracle", {}),
            "clinical_oracle": case_payload.get("clinical_oracle", {}),
            "guideline_oracle": case_payload.get("guideline_oracle", {}),
        },
        "actual": {
            "effective_state": _state(final_snapshot),
            "effective_management_track": _track(final_snapshot),
            "next_best_action": final_snapshot.get("next_best_action", {}),
            "guideline_basis": _guideline_basis(final_snapshot),
            "blocking_inputs": _blocking_inputs(final_snapshot),
            "active_alert_titles": _alert_titles(final_snapshot),
        },
        "assertions": case_assertions,
        "visit_reports": visit_reports,
        "case_status": "passed" if case_passed and not ui_contradictions else "failed",
        "critical_failure": bool(critical_failure),
        "ui_contradictions": ui_contradictions,
        "guideline_concordance_pct": guideline_concordance,
        "missing_input_prompt_accuracy": round(sum(prompt_scores) / len(prompt_scores), 3) if prompt_scores else 1.0,
        "data_accumulation_complete": _data_accumulation_complete(final_snapshot),
        "visual_artifacts": [],
        "profile_url": ((final_snapshot.get("urls") or {}).get("profile") or ""),
        "signals_url": ((final_snapshot.get("urls") or {}).get("signals") or ""),
        "schedule_url": ((final_snapshot.get("urls") or {}).get("schedule") or ""),
        "labs_url": ((final_snapshot.get("urls") or {}).get("labs_intelligence") or ""),
        "decision_trace_url": ((final_snapshot.get("urls") or {}).get("decision_trace") or ""),
    }


def evaluate_validation_seed(seed_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [evaluate_seeded_case(item) for item in list(seed_payload.get("cases") or [])]


__all__ = [
    "evaluate_seeded_case",
    "evaluate_validation_seed",
]
