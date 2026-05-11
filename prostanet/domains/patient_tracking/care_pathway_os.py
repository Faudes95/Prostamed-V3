"""ProstaMed Care Pathway OS.

Deterministic patient-level execution read model for the loop:
decision -> execution -> surveillance -> new decision.

This module does not prescribe, schedule external orders, or invent treatment,
PSA/APE, testosterone, molecular, imaging, line, or trial facts. It translates
the already-audited Tumor Board OS, Clinical Readiness tower, longitudinal truth,
agenda, and scheduled events into an internal, auditable pathway bundle.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from prostanet.domains.patient_tracking.clinical_readiness_tower import FIELD_LABELS


CARE_PATHWAY_ACTION_STATUSES = (
    "pending",
    "ordered",
    "scheduled",
    "completed",
    "overdue",
    "blocked",
    "cancelled",
    "superseded",
)

ACTION_STATUS_RANK = {
    "overdue": 0,
    "blocked": 1,
    "pending": 2,
    "ordered": 3,
    "scheduled": 4,
    "completed": 5,
    "cancelled": 6,
    "superseded": 7,
}

ACTION_FAMILY_LABELS = {
    "diagnostic_biopsy": "Diagnostico / biopsia",
    "imaging": "Imagen",
    "biomarker_labs": "Biomarcadores / labs",
    "localized_treatment": "Tratamiento local",
    "systemic_treatment": "Tratamiento sistemico",
    "precision_molecular_psma": "Precision molecular / PSMA",
    "safety_toxicity": "Seguridad / toxicidad",
    "supportive_palliative": "Soporte / paliativos",
    "sdm_documentation": "SDM / documentacion",
}

LANE_TO_FAMILY = {
    "diagnostic_biopsy_readiness": "diagnostic_biopsy",
    "active_surveillance_readiness": "biomarker_labs",
    "localized_treatment_readiness": "localized_treatment",
    "bcr_salvage_readiness": "localized_treatment",
    "mhspc_precision_readiness": "systemic_treatment",
    "crpc_confirmation_readiness": "biomarker_labs",
    "m0crpc_arpi_readiness": "systemic_treatment",
    "m1crpc_sequence_readiness": "systemic_treatment",
    "parp_hrr_readiness": "precision_molecular_psma",
    "psma_rlt_readiness": "precision_molecular_psma",
    "adt_arpi_safety_readiness": "safety_toxicity",
    "supportive_palliative_readiness": "supportive_palliative",
}

FAMILY_TO_LONGITUDINAL_SECTION = {
    "diagnostic_biopsy": "diagnostic",
    "imaging": "imaging",
    "biomarker_labs": "biomarkers",
    "localized_treatment": "treatment",
    "systemic_treatment": "treatment",
    "precision_molecular_psma": "precision",
    "safety_toxicity": "safety",
    "supportive_palliative": "supportive",
    "sdm_documentation": "documentation",
}

CRITICAL_FAMILIES = {
    "diagnostic_biopsy",
    "biomarker_labs",
    "imaging",
    "systemic_treatment",
    "precision_molecular_psma",
    "safety_toxicity",
}


def build_care_pathway_os(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
) -> dict[str, Any]:
    """Build the official Care Pathway OS bundle for one patient."""
    patient = deepcopy(dict(patient_record or {}))
    bundle = deepcopy(dict(longitudinal_bundle or {}))
    signals = dict(bundle.get("signals") or {})
    latest_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    effective_state = _first_text(
        state,
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        signals.get("reconciled_state"),
        latest_snapshot.get("effective_state_final"),
        latest_snapshot.get("effective_state"),
        (patient.get("latest_assessment") or {}).get("state"),
        (patient.get("prior_history") or {}).get("current_state"),
        patient.get("current_state"),
        "diagnostic_workup",
    )
    effective_track = _first_text(
        management_track,
        signals.get("effective_management_track_final"),
        signals.get("effective_management_track"),
        signals.get("reconciled_management_track"),
        latest_snapshot.get("effective_management_track_final"),
        latest_snapshot.get("effective_management_track"),
        patient.get("management_track"),
        (patient.get("prior_history") or {}).get("management_track"),
    )
    resolved_ref = _first_text(
        patient_ref,
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        (patient.get("identity") or {}).get("id"),
    )

    readiness = dict(
        bundle.get("clinical_readiness_tower")
        or patient.get("clinical_readiness_tower")
        or latest_snapshot.get("clinical_readiness_tower")
        or {}
    )
    tumor_board = dict(
        bundle.get("tumor_board_os")
        or patient.get("tumor_board_os")
        or latest_snapshot.get("tumor_board_os")
        or {}
    )
    if not tumor_board:
        try:
            from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

            tumor_board = build_tumor_board_os(
                patient,
                longitudinal_bundle={**bundle, "clinical_readiness_tower": readiness, "signals": signals},
                state=effective_state,
                management_track=effective_track,
                patient_ref=resolved_ref,
            )
        except Exception:
            tumor_board = {}

    actions: list[dict[str, Any]] = []
    actions.extend(_actions_from_tumor_board(tumor_board, patient_ref=resolved_ref, state=effective_state))
    actions.extend(_actions_from_readiness(readiness, patient_ref=resolved_ref, state=effective_state))
    actions.extend(_actions_from_schedule(patient, bundle, patient_ref=resolved_ref))
    actions.extend(_actions_from_agenda(patient, bundle, patient_ref=resolved_ref))

    actions = _merge_duplicate_actions(actions)
    actions = _apply_manual_status_overrides(actions, patient.get("patient_events") or [])
    actions = _sort_actions(actions)

    summary = _build_summary(
        actions,
        tumor_board=tumor_board,
        readiness=readiness,
        state=effective_state,
        management_track=effective_track,
    )
    redecision_triggers = _build_redecision_triggers(actions, tumor_board, readiness)
    capture_plan = _build_capture_plan(actions, readiness, tumor_board)
    surveillance_plan = _build_surveillance_plan(bundle, actions)

    return {
        "available": True,
        "source": "care_pathway_os",
        "version": "care_pathway_os_v1",
        "patient_ref": resolved_ref,
        "state": effective_state,
        "management_track": effective_track,
        "summary": summary,
        "pathway_actions": actions[:32],
        "execution_timeline": _build_execution_timeline(actions),
        "surveillance_plan": surveillance_plan,
        "redecision_triggers": redecision_triggers,
        "capture_plan": capture_plan,
        "audit": {
            "action_statuses_allowed": list(CARE_PATHWAY_ACTION_STATUSES),
            "action_families_allowed": [
                {"key": key, "label": label} for key, label in ACTION_FAMILY_LABELS.items()
            ],
            "sources_used": _dedupe(
                [
                    "tumor_board_os" if tumor_board else "",
                    "clinical_readiness_tower" if readiness else "",
                    "followup_agenda_items" if _agenda_items(patient, bundle) else "",
                    "scheduled_events" if _scheduled_items(patient, bundle) else "",
                    "longitudinal_truth_snapshot" if (bundle.get("longitudinal_truth_snapshot") or patient.get("longitudinal_truth_snapshot")) else "",
                    "patient_events" if patient.get("patient_events") else "",
                ]
            ),
            "no_external_integrations": True,
            "internal_execution_only": True,
            "anti_fabrication_checks": {
                "no_treatment_line_created": True,
                "no_psa_or_testosterone_created": True,
                "no_external_order_created": True,
                "trials_not_promoted_without_tumor_board": True,
            },
            "write_surfaces": ["followup_agenda_items", "scheduled_events", "patient_events"],
        },
    }


def _actions_from_tumor_board(
    tumor_board: Mapping[str, Any],
    *,
    patient_ref: str,
    state: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    board = dict(tumor_board or {})
    for option in list(board.get("options") or []):
        if not isinstance(option, Mapping):
            continue
        option = dict(option)
        option_status = _text(option.get("status") or "requires_data")
        if option_status == "not_applicable":
            continue
        label = _first_text(option.get("label"), option.get("key"), "Decision comparativa")
        option_key = _text(option.get("key") or label).replace(" ", "_")
        family = _family_for_option(option)
        missing = _as_list(option.get("missing_fields"))
        display_missing = _display_fields(missing, option.get("display_missing_fields"))
        blockers = _as_list(option.get("release_blockers"))
        cta = _normalize_cta(option.get("cta"), patient_ref=patient_ref, state=state, family=family)
        base = {
            "origin": "tumor_board_os",
            "decision_origin": "tumor_board_os",
            "option_key": option_key,
            "option_label": label,
            "family": family,
            "family_label": ACTION_FAMILY_LABELS.get(family, family),
            "reason": _first_text(
                *((option.get("why") or [])[:2] if isinstance(option.get("why"), list) else []),
                option.get("rationale"),
                "Opcion comparativa del Tumor Board OS.",
            ),
            "evidence": list(option.get("evidence") or []),
            "gates_impacted": list(option.get("gates_impacted") or []),
            "trials_impacted": list(option.get("trials_impacted") or []),
            "missing_fields": missing,
            "display_missing_fields": display_missing,
            "blockers": blockers,
            "cta": cta,
        }
        if option_status == "releaseable":
            actions.append(
                {
                    **base,
                    "action_key": f"tb:{option_key}",
                    "title": f"Ejecutar decision interna: {label}",
                    "status": "pending",
                    "priority": "critical" if family in CRITICAL_FAMILIES else "standard",
                    "action_mode": "internal_execution",
                    "due_at": date.today().isoformat(),
                    "ideal_due_at": date.today().isoformat(),
                    "scheduled_due_at": "",
                }
            )
            continue

        if missing:
            actions.append(
                {
                    **base,
                    "action_key": f"tb-data:{option_key}",
                    "title": f"Cerrar datos para: {label}",
                    "status": "blocked" if option_status == "blocked" else "pending",
                    "priority": "critical",
                    "action_mode": "capture",
                    "due_at": date.today().isoformat(),
                    "ideal_due_at": date.today().isoformat(),
                    "scheduled_due_at": "",
                }
            )
        elif option_status in {"blocked", "provisional", "requires_data"}:
            actions.append(
                {
                    **base,
                    "action_key": f"tb-review:{option_key}",
                    "title": f"Revisar bloqueo: {label}",
                    "status": "blocked" if option_status == "blocked" else "pending",
                    "priority": "critical" if option_status == "blocked" else "standard",
                    "action_mode": "documentation",
                    "due_at": date.today().isoformat(),
                    "ideal_due_at": date.today().isoformat(),
                    "scheduled_due_at": "",
                }
            )
    return actions


def _actions_from_readiness(
    readiness: Mapping[str, Any],
    *,
    patient_ref: str,
    state: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for lane in list((readiness or {}).get("lanes") or []):
        if not isinstance(lane, Mapping):
            continue
        lane = dict(lane)
        lane_status = _text(lane.get("status") or "not_applicable")
        if lane_status not in {"requires_data", "overdue", "active_risk"}:
            continue
        lane_key = _text(lane.get("key") or lane.get("lane") or lane.get("label")).replace(" ", "_")
        if not lane_key:
            continue
        family = LANE_TO_FAMILY.get(lane_key, "sdm_documentation")
        missing = _as_list(lane.get("missing_fields"))
        cta = _normalize_cta(
            {"url": lane.get("cta_url"), "label": "Capturar faltantes"},
            patient_ref=patient_ref,
            state=state,
            family=family,
            lane_key=lane_key,
        )
        status = "overdue" if lane_status == "overdue" else "blocked" if lane_status == "active_risk" else "pending"
        actions.append(
            {
                "action_key": f"lane:{lane_key}",
                "origin": "clinical_readiness_tower",
                "decision_origin": "clinical_readiness_tower",
                "title": _readiness_action_title(lane),
                "status": status,
                "priority": "critical" if lane_status in {"overdue", "active_risk"} else "standard",
                "family": family,
                "family_label": ACTION_FAMILY_LABELS.get(family, family),
                "reason": _first_text(lane.get("reason"), "Carril de readiness requiere cierre clinico."),
                "action_mode": "capture" if missing else "review",
                "due_at": date.today().isoformat(),
                "ideal_due_at": date.today().isoformat(),
                "scheduled_due_at": "",
                "missing_fields": missing,
                "display_missing_fields": _display_fields(missing, lane.get("display_missing_fields")),
                "blockers": [] if missing else [_first_text(lane.get("reason"))],
                "gates_impacted": list(lane.get("gates_impacted") or []),
                "trials_impacted": list(lane.get("trials_impacted") or []),
                "cta": cta,
                "readiness_lane": lane_key,
                "readiness_lane_label": lane.get("label") or lane_key,
            }
        )
    return actions


def _actions_from_schedule(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    patient_ref: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in _scheduled_items(patient, bundle):
        key = _first_text(item.get("schedule_key"), item.get("agenda_key"), item.get("id"))
        if not key:
            continue
        family = _family_for_schedule_item(item)
        status = _normalize_action_status(
            item.get("status") or item.get("completion_status"),
            due_at=_first_text(item.get("scheduled_due_at"), item.get("due_date"), item.get("due_at")),
            completed=item.get("completed"),
        )
        actions.append(
            {
                "action_key": f"schedule:{key}",
                "origin": "scheduled_events",
                "decision_origin": _first_text(item.get("generated_from_event"), item.get("source"), "followup_agenda_items"),
                "title": _first_text(item.get("label"), item.get("title"), item.get("event_type"), "Evento programado"),
                "status": status,
                "priority": _priority_from_item(item, family),
                "family": family,
                "family_label": ACTION_FAMILY_LABELS.get(family, family),
                "reason": _first_text(item.get("summary"), item.get("guideline"), "Evento de vigilancia o ejecucion interna."),
                "action_mode": _first_text(item.get("action_mode"), "capture"),
                "due_at": _first_text(item.get("due_at"), item.get("due_date"), item.get("scheduled_due_at")),
                "ideal_due_at": _first_text(item.get("ideal_due_at"), item.get("due_date")),
                "scheduled_due_at": _first_text(item.get("scheduled_due_at"), item.get("due_date")),
                "completed_at": _first_text(item.get("completed_at"), item.get("completed_date"), item.get("performed_date")),
                "completed_visit_id": item.get("completed_visit_id"),
                "missing_fields": _completion_rule_fields(item),
                "display_missing_fields": _display_fields(_completion_rule_fields(item)),
                "blockers": _as_list(item.get("blockers") or item.get("blockers_json")),
                "gates_impacted": _as_list((item.get("evidence_basis") or {}).get("gates") if isinstance(item.get("evidence_basis"), Mapping) else []),
                "trials_impacted": _as_list((item.get("evidence_basis") or {}).get("trials") if isinstance(item.get("evidence_basis"), Mapping) else []),
                "cta": _cta_for_action(
                    patient_ref=patient_ref,
                    family=family,
                    action_mode=_first_text(item.get("action_mode"), "capture"),
                    lane_key=_first_text(item.get("readiness_lane"), ""),
                ),
                "source_record_id": item.get("id"),
                "source_key": key,
            }
        )
    return actions


def _actions_from_agenda(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    patient_ref: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in _agenda_items(patient, bundle):
        key = _first_text(item.get("agenda_key"), item.get("id"))
        if not key:
            continue
        family = _family_for_agenda_item(item)
        status = _normalize_action_status(
            item.get("status"),
            due_at=_first_text(item.get("scheduled_due_at"), item.get("due_at"), item.get("window_end")),
            completed=bool(item.get("completed_at")),
        )
        actions.append(
            {
                "action_key": f"agenda:{key}",
                "origin": "followup_agenda_items",
                "decision_origin": _first_text(item.get("generated_from_event"), "followup_agenda"),
                "title": _first_text(item.get("title"), item.get("item_type"), "Accion de agenda"),
                "status": status,
                "priority": _priority_from_item(item, family),
                "family": family,
                "family_label": ACTION_FAMILY_LABELS.get(family, family),
                "reason": _first_text(item.get("summary"), "Accion decisional de seguimiento."),
                "action_mode": _first_text(item.get("action_mode"), "capture"),
                "due_at": _first_text(item.get("due_at"), item.get("scheduled_due_at")),
                "ideal_due_at": _first_text(item.get("ideal_due_at"), item.get("due_at")),
                "scheduled_due_at": _first_text(item.get("scheduled_due_at"), item.get("due_at")),
                "completed_at": _first_text(item.get("completed_at")),
                "missing_fields": _as_list(item.get("required_inputs")),
                "display_missing_fields": _display_fields(_as_list(item.get("required_inputs"))),
                "blockers": _as_list(item.get("blockers")),
                "gates_impacted": _as_list((item.get("evidence_basis") or {}).get("gates") if isinstance(item.get("evidence_basis"), Mapping) else []),
                "trials_impacted": _as_list((item.get("evidence_basis") or {}).get("trials") if isinstance(item.get("evidence_basis"), Mapping) else []),
                "cta": _cta_for_action(
                    patient_ref=patient_ref,
                    family=family,
                    action_mode=_first_text(item.get("action_mode"), "capture"),
                    lane_key=_first_text(item.get("readiness_lane"), ""),
                ),
                "source_record_id": item.get("id"),
                "source_key": key,
            }
        )
    return actions


def _build_summary(
    actions: list[dict[str, Any]],
    *,
    tumor_board: Mapping[str, Any],
    readiness: Mapping[str, Any],
    state: str,
    management_track: str,
) -> dict[str, Any]:
    counts = {status: 0 for status in CARE_PATHWAY_ACTION_STATUSES}
    for action in actions:
        status = _text(action.get("status") or "pending")
        if status in counts:
            counts[status] += 1
    actionable = [
        action
        for action in actions
        if _text(action.get("status")) not in {"completed", "cancelled", "superseded"}
    ]
    next_action = actionable[0] if actionable else {}
    tb_summary = dict((tumor_board or {}).get("summary") or {})
    tb_recommendation = dict((tumor_board or {}).get("recommendation") or {})
    readiness_summary = dict((readiness or {}).get("summary") or {})
    next_7d = [a for a in actionable if _is_due_within(a, days=7)]
    next_30d = [a for a in actionable if _is_due_within(a, days=30)]
    critical_actions = [
        a
        for a in actionable
        if a.get("priority") == "critical" or a.get("family") in CRITICAL_FAMILIES
    ]
    return {
        "clinical_state": state,
        "management_track": management_track,
        "execution_status": _execution_status(counts, actionable),
        "decision_origin": "tumor_board_os" if tumor_board else "readiness_schedule",
        "winner_option_key": _first_text(tb_summary.get("winner_option_key"), tb_recommendation.get("winner_option_key")),
        "winner_option_label": _first_text(tb_summary.get("winner_option_label"), tb_recommendation.get("winner_option_label")),
        "board_status": _first_text(tb_summary.get("board_status"), tb_recommendation.get("finality"), "requires_data"),
        "dominant_blocker": _first_text(
            tb_summary.get("dominant_blocker"),
            tb_recommendation.get("blocking_summary"),
            readiness_summary.get("dominant_blocker"),
            "Sin bloqueo dominante.",
        ),
        "action_count": len(actions),
        "critical_action_count": len(critical_actions),
        "blocked_count": counts["blocked"],
        "overdue_count": counts["overdue"],
        "completed_count": counts["completed"],
        "pending_count": counts["pending"],
        "scheduled_count": counts["scheduled"],
        "next_action_key": next_action.get("action_key", ""),
        "next_action_label": next_action.get("title", ""),
        "next_due_at": _first_text(next_action.get("scheduled_due_at"), next_action.get("due_at")),
        "next_7d_count": len(next_7d),
        "next_30d_count": len(next_30d),
        "redecision_trigger_count": len(_build_redecision_triggers(actions, tumor_board, readiness)),
        "safety_note": "No hay orden externa ni terapia inventada; acciones internas trazables.",
    }


def _build_execution_timeline(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for action in actions[:20]:
        timeline.append(
            {
                "action_key": action.get("action_key", ""),
                "title": action.get("title", ""),
                "status": action.get("status", ""),
                "family": action.get("family", ""),
                "due_at": _first_text(action.get("scheduled_due_at"), action.get("due_at")),
                "completed_at": action.get("completed_at", ""),
                "origin": action.get("origin", ""),
            }
        )
    return timeline


def _build_surveillance_plan(bundle: Mapping[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    master = dict((bundle or {}).get("master_followup_plan") or {})
    guideline = dict((bundle or {}).get("guideline_followup_plan") or {})
    schedule_actions = [a for a in actions if a.get("origin") == "scheduled_events"]
    active_schedule = [
        a for a in schedule_actions if a.get("status") not in {"completed", "cancelled", "superseded"}
    ]
    return {
        "schedule_primary_intent": _first_text(guideline.get("schedule_primary_intent"), master.get("primary_intent")),
        "protocol_label": _first_text(guideline.get("protocol_label"), master.get("protocol_label")),
        "next_events": [
            {
                "action_key": item.get("action_key", ""),
                "label": item.get("title", ""),
                "status": item.get("status", ""),
                "due_at": _first_text(item.get("scheduled_due_at"), item.get("due_at")),
                "family": item.get("family", ""),
            }
            for item in active_schedule[:6]
        ],
        "next_events_count": len(active_schedule),
        "overdue_count": len([a for a in active_schedule if a.get("status") == "overdue"]),
        "source": "master_followup_plan + guideline_followup_plan + scheduled_events",
    }


def _build_redecision_triggers(
    actions: list[dict[str, Any]],
    tumor_board: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for action in actions:
        status = _text(action.get("status"))
        if status == "overdue":
            triggers.append(
                {
                    "trigger_key": f"overdue:{action.get('action_key')}",
                    "status": "active",
                    "reason": f"Accion vencida: {action.get('title')}",
                    "cta": dict(action.get("cta") or {}),
                    "action_key": action.get("action_key", ""),
                }
            )
        elif status == "completed" and action.get("origin") in {"scheduled_events", "followup_agenda_items"}:
            triggers.append(
                {
                    "trigger_key": f"completed:{action.get('action_key')}",
                    "status": "active",
                    "reason": f"Recalcular decision tras completar: {action.get('title')}",
                    "cta": {"label": "Re-evaluar Tumor Board", "url": "#pm2TumorBoardOS"},
                    "action_key": action.get("action_key", ""),
                }
            )
    tb_summary = dict((tumor_board or {}).get("summary") or {})
    if _text(tb_summary.get("board_status")) in {"blocked", "requires_data", "provisional"}:
        triggers.append(
            {
                "trigger_key": "tumor_board_redecision_after_capture",
                "status": "pending",
                "reason": _first_text(tb_summary.get("dominant_blocker"), "Nueva decision al cerrar datos del Tumor Board."),
                "cta": {"label": "Abrir plan de captura", "url": "#pm2CarePathwayOS"},
            }
        )
    readiness_summary = dict((readiness or {}).get("summary") or {})
    if readiness_summary.get("dominant_blocker"):
        triggers.append(
            {
                "trigger_key": "readiness_redecision_after_blocker",
                "status": "pending",
                "reason": readiness_summary.get("dominant_blocker"),
                "cta": {"label": "Cerrar readiness", "url": "#pm2ReadinessClinico"},
            }
        )
    return _dedupe_triggers(triggers)[:12]


def _build_capture_plan(
    actions: list[dict[str, Any]],
    readiness: Mapping[str, Any],
    tumor_board: Mapping[str, Any],
) -> dict[str, Any]:
    groups = []
    field_set: set[str] = set()
    for action in actions:
        fields = [field for field in _as_list(action.get("missing_fields")) if field]
        if not fields:
            continue
        for field in fields:
            field_set.add(str(field))
        groups.append(
            {
                "action_key": action.get("action_key", ""),
                "title": action.get("title", ""),
                "family": action.get("family", ""),
                "status": action.get("status", ""),
                "cta": dict(action.get("cta") or {}),
                "fields": fields,
                "display_fields": _display_fields(fields, action.get("display_missing_fields")),
            }
        )
    readiness_capture = dict((readiness or {}).get("capture_plan") or {})
    tumor_capture = dict((tumor_board or {}).get("capture_plan") or {})
    return {
        "groups": groups[:12],
        "required_fields": sorted(field_set),
        "display_required_fields": _display_fields(sorted(field_set)),
        "required_field_count": len(field_set),
        "readiness_capture_plan": readiness_capture,
        "tumor_board_capture_plan": tumor_capture,
    }


def _merge_duplicate_actions(actions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in actions:
        item = dict(raw or {})
        key = _text(item.get("action_key"))
        if not key:
            continue
        item["status"] = _safe_status(item.get("status"))
        item["family"] = _text(item.get("family") or "sdm_documentation")
        item["family_label"] = ACTION_FAMILY_LABELS.get(item["family"], item["family"])
        current = merged.get(key)
        if not current:
            merged[key] = item
            continue
        current_status = ACTION_STATUS_RANK.get(_text(current.get("status")), 99)
        item_status = ACTION_STATUS_RANK.get(_text(item.get("status")), 99)
        if item_status < current_status:
            base, extra = item, current
        else:
            base, extra = current, item
        base["missing_fields"] = _dedupe(list(base.get("missing_fields") or []) + list(extra.get("missing_fields") or []))
        base["display_missing_fields"] = _display_fields(base["missing_fields"], base.get("display_missing_fields"))
        base["blockers"] = _dedupe(list(base.get("blockers") or []) + list(extra.get("blockers") or []))
        base["gates_impacted"] = _dedupe(list(base.get("gates_impacted") or []) + list(extra.get("gates_impacted") or []))
        base["trials_impacted"] = _dedupe(list(base.get("trials_impacted") or []) + list(extra.get("trials_impacted") or []))
        merged[key] = base
    return list(merged.values())


def _apply_manual_status_overrides(
    actions: list[dict[str, Any]],
    patient_events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for event in patient_events:
        if not isinstance(event, Mapping):
            continue
        if _text(event.get("event_type")) != "care_pathway_action_status_updated":
            continue
        payload = dict(event.get("payload") or {})
        action_key = _text(payload.get("action_key"))
        status = _safe_status(payload.get("status"))
        if action_key and status:
            overrides[action_key] = {
                "status": status,
                "manual_status_note": _text(payload.get("note")),
                "manual_status_at": _first_text(event.get("created_at"), event.get("event_date")),
                "manual_status_source": _first_text(payload.get("updated_by"), "care_pathway_os"),
            }
    for action in actions:
        override = overrides.get(_text(action.get("action_key")))
        if override:
            action.update(override)
            if override.get("status") == "completed":
                action.setdefault("completed_at", str(date.today()))
    return actions


def _sort_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        actions,
        key=lambda item: (
            ACTION_STATUS_RANK.get(_text(item.get("status")), 99),
            0 if item.get("priority") == "critical" else 1,
            _date_sort_key(_first_text(item.get("scheduled_due_at"), item.get("due_at"))),
            _text(item.get("title")),
        ),
    )


def _scheduled_items(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = [
        bundle.get("scheduled_items"),
        bundle.get("active_schedule"),
        bundle.get("schedule"),
        patient.get("scheduled_events"),
    ]
    return _unique_items_by_key(sources, key_names=("schedule_key", "agenda_key", "id"))


def _agenda_items(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = [
        bundle.get("active_items"),
        bundle.get("agenda_items"),
        bundle.get("items"),
        patient.get("agenda_items"),
    ]
    return _unique_items_by_key(sources, key_names=("agenda_key", "id"))


def _unique_items_by_key(sources: Iterable[Any], *, key_names: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        for raw in _as_list(source):
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            key = ""
            for name in key_names:
                key = _first_text(item.get(name))
                if key:
                    break
            fallback = f"{item.get('event_type') or item.get('item_type') or item.get('title')}:{item.get('due_date') or item.get('due_at')}"
            key = key or fallback
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _normalize_action_status(raw_status: Any, *, due_at: Any = "", completed: Any = None) -> str:
    if _truthy(completed):
        return "completed"
    raw = _text(raw_status).lower()
    if raw in {"completed", "completed_on_time", "completed_late", "done"}:
        return "completed"
    if raw in {"cancelled", "canceled"}:
        return "cancelled"
    if raw in {"superseded", "archived"}:
        return "superseded"
    if raw in {"blocked", "hard_stop"}:
        return "blocked"
    if raw in {"ordered"}:
        return "ordered"
    if raw in {"scheduled"}:
        return "scheduled"
    if raw in {"overdue", "missed", "late"}:
        return "overdue"
    due = _parse_date(due_at)
    if due and due < date.today():
        return "overdue"
    if raw in {"due_today"}:
        return "scheduled"
    return "pending"


def _safe_status(value: Any) -> str:
    status = _text(value).lower()
    return status if status in CARE_PATHWAY_ACTION_STATUSES else "pending"


def _execution_status(counts: Mapping[str, int], actionable: list[dict[str, Any]]) -> str:
    if counts.get("overdue", 0) > 0:
        return "overdue"
    if counts.get("blocked", 0) > 0:
        return "blocked"
    if actionable:
        return "active"
    return "complete"


def _family_for_option(option: Mapping[str, Any]) -> str:
    text = " ".join(
        [
            _text(option.get("key")),
            _text(option.get("label")),
            _text(option.get("clinical_role")),
            _text(option.get("family_code")),
        ]
    ).lower()
    if any(token in text for token in ("biopsy", "diagnostic", "mri_targeted")):
        return "diagnostic_biopsy"
    if any(token in text for token in ("image", "imaging", "restage", "psma pet")):
        return "imaging"
    if any(token in text for token in ("parp", "hrr", "brca", "psma_rlt", "rlt", "molecular")):
        return "precision_molecular_psma"
    if any(token in text for token in ("arpi", "adt", "triplet", "docetaxel", "sequence", "systemic", "mcrpc", "mhspc")):
        return "systemic_treatment"
    if any(token in text for token in ("salvage", "radiotherapy", "prostatectomy", "focal", "mdt")):
        return "localized_treatment"
    if any(token in text for token in ("support", "palliative", "pali")):
        return "supportive_palliative"
    return "sdm_documentation"


def _family_for_schedule_item(item: Mapping[str, Any]) -> str:
    text = " ".join([_text(item.get("event_type")), _text(item.get("label")), _text(item.get("title"))]).lower()
    if any(token in text for token in ("biopsy", "patholog")):
        return "diagnostic_biopsy"
    if any(token in text for token in ("imaging", "mri", "ct", "pet", "psma", "gammagrama")):
        return "imaging"
    if any(token in text for token in ("psa", "ape", "testosterone", "lab", "hba1c", "lipid", "renal", "hepatic")):
        return "biomarker_labs"
    if any(token in text for token in ("tox", "ctcae", "dexa", "bone", "falls", "cardio", "safety")):
        return "safety_toxicity"
    if any(token in text for token in ("palliative", "pain", "esas", "bpi", "support")):
        return "supportive_palliative"
    return "sdm_documentation"


def _family_for_agenda_item(item: Mapping[str, Any]) -> str:
    text = " ".join([_text(item.get("item_type")), _text(item.get("title")), _text(item.get("summary"))]).lower()
    if any(token in text for token in ("psa", "ape", "testosterone", "lab", "biomarker")):
        return "biomarker_labs"
    if any(token in text for token in ("image", "imaging", "mri", "pet", "psma")):
        return "imaging"
    if any(token in text for token in ("biopsy", "diagnostic")):
        return "diagnostic_biopsy"
    if any(token in text for token in ("toxicity", "safety", "dexa", "falls")):
        return "safety_toxicity"
    if any(token in text for token in ("treatment", "therapy", "arpi", "adt", "docetaxel", "salvage")):
        return "systemic_treatment" if any(token in text for token in ("arpi", "adt", "docetaxel", "systemic")) else "localized_treatment"
    if any(token in text for token in ("palliative", "support", "pain")):
        return "supportive_palliative"
    return "sdm_documentation"


def _priority_from_item(item: Mapping[str, Any], family: str) -> str:
    raw = _text(item.get("priority")).lower()
    if raw in {"critical", "high", "urgent"}:
        return "critical"
    if family in CRITICAL_FAMILIES:
        return "critical"
    return "standard"


def _completion_rule_fields(item: Mapping[str, Any]) -> list[str]:
    rule = item.get("completion_rule")
    if not isinstance(rule, Mapping):
        rule = {}
    fields = []
    for key in ("required_fields", "fields", "any_of", "all_of"):
        fields.extend(_as_list(rule.get(key)))
    fields.extend(_as_list(item.get("required_inputs")))
    return _dedupe(fields)


def _normalize_cta(
    cta: Any,
    *,
    patient_ref: str,
    state: str,
    family: str,
    lane_key: str = "",
) -> dict[str, Any]:
    if isinstance(cta, Mapping) and cta.get("url"):
        return {"label": _first_text(cta.get("label"), "Capturar"), "url": _text(cta.get("url"))}
    return _cta_for_action(patient_ref=patient_ref, family=family, action_mode="capture", lane_key=lane_key, state=state)


def _cta_for_action(
    *,
    patient_ref: str,
    family: str,
    action_mode: str,
    lane_key: str = "",
    state: str = "",
) -> dict[str, Any]:
    if _text(action_mode) in {"wizard", "initial_wizard"} or family in {"localized_treatment", "systemic_treatment"} and state:
        if _text(action_mode) in {"wizard", "initial_wizard"}:
            return {"label": "Abrir wizard", "url": f"/wizard/{state}?prefill_source=care_pathway_os"}
    section = FAMILY_TO_LONGITUDINAL_SECTION.get(family, "followup")
    lane_qs = f"?readiness_lane={lane_key}" if lane_key else ""
    return {
        "label": "Captura longitudinal",
        "url": f"/longitudinal-capture/{patient_ref}{lane_qs}#section-{section}",
    }


def _readiness_action_title(lane: Mapping[str, Any]) -> str:
    label = _first_text(lane.get("label"), lane.get("key"), "readiness")
    status = _text(lane.get("status"))
    if status == "active_risk":
        return f"Atender riesgo activo: {label}"
    if status == "overdue":
        return f"Cerrar vencido: {label}"
    return f"Cerrar readiness: {label}"


def _display_fields(fields: Iterable[Any], display_fields: Any = None) -> list[str]:
    provided = [str(item) for item in _as_list(display_fields) if str(item).strip()]
    if provided:
        return provided[:10]
    return [FIELD_LABELS.get(str(field), str(field).replace("_", " ")) for field in _as_list(fields)[:10]]


def _is_due_within(action: Mapping[str, Any], *, days: int) -> bool:
    due = _parse_date(_first_text(action.get("scheduled_due_at"), action.get("due_at")))
    if not due:
        return False
    return date.today() <= due <= date.today() + timedelta(days=days)


def _date_sort_key(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else "9999-12-31"


def _parse_date(value: Any) -> date | None:
    text = _text(value)[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).lower() in {"1", "true", "yes", "si", "completed"}


def _dedupe(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value in (None, "", [], {}):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_triggers(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw in values:
        item = dict(raw or {})
        key = _text(item.get("trigger_key") or item.get("reason"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, Mapping):
        return [value]
    return [value]


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "ACTION_FAMILY_LABELS",
    "CARE_PATHWAY_ACTION_STATUSES",
    "build_care_pathway_os",
]
