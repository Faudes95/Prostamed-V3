"""ProstaMed Clinical Autodrive Command Center.

Deterministic clinical operations read model for "que debo hacer hoy".

Autodrive does not prescribe, order externally, train ML, or invent treatment,
PSA/APE, testosterone, lines, imaging, molecular facts, or trial eligibility.
It ranks already-audited readiness, Tumor Board, Care Pathway and Clinical
Memory outputs into a daily clinical queue.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import sqlite3
from typing import Any, Iterable, Mapping


AUTODRIVE_PRIORITY_STATUSES = (
    "critical_today",
    "high_today",
    "routine_today",
    "watchlist",
    "not_actionable",
)

AUTODRIVE_LANES = (
    "urgent_today",
    "ready_to_decide",
    "blocked_by_data",
    "overdue_surveillance",
    "redecision_required",
)

LANE_LABELS = {
    "urgent_today": "Urgente hoy",
    "ready_to_decide": "Listo para decidir",
    "blocked_by_data": "Bloqueado por datos",
    "overdue_surveillance": "Seguimiento vencido",
    "redecision_required": "Nueva decision requerida",
}

PRIORITY_RANK = {
    "critical_today": 0,
    "high_today": 1,
    "routine_today": 2,
    "watchlist": 3,
    "not_actionable": 4,
}

STATE_LABELS = {
    "diagnostic_workup": "Diagnostico",
    "screening": "Screening",
    "post_negative_biopsy_followup": "Biopsia negativa",
    "localized_initial": "Localizado",
    "recurrence_bcr": "BCR",
    "post_prostatectomy": "Post-RP",
    "post_radiotherapy_followup": "Post-RT",
    "post_radiotherapy_or_local_salvage": "Post-RT salvage",
    "mcspc_low_volume": "mCSPC bajo volumen",
    "mcspc_high_volume": "mCSPC alto volumen",
    "m0_crpc": "m0CRPC",
    "m1_crpc": "m1CRPC",
    "adt_progression_verification": "Verificacion CRPC",
    "palliative": "Paliativo",
}

CRPC_OPTION_TOKENS = ("crpc", "mcrpc", "parp", "psma_rlt", "rlt", "lutetium", "lu177", "lu-177", "pluvicto")


def build_patient_autodrive(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
) -> dict[str, Any]:
    """Build the official Autodrive bundle for one patient."""
    patient = deepcopy(dict(patient_record or {}))
    bundle = deepcopy(dict(longitudinal_bundle or {}))
    signals = dict(bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    effective_state = _first_text(
        state,
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        signals.get("reconciled_state"),
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
        (patient.get("prior_history") or {}).get("management_track"),
        patient.get("management_track"),
    )
    resolved_ref = _first_text(
        patient_ref,
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        patient.get("patient_ref"),
        (patient.get("identity") or {}).get("id"),
    )

    enriched = _ensure_source_bundles(
        patient,
        bundle,
        state=effective_state,
        management_track=effective_track,
        patient_ref=resolved_ref,
    )
    readiness = dict(enriched.get("clinical_readiness_tower") or {})
    tumor_board = dict(enriched.get("tumor_board_os") or {})
    care_pathway = dict(enriched.get("care_pathway_os") or {})
    clinical_memory = dict(enriched.get("clinical_memory_os") or {})

    queue: list[dict[str, Any]] = []
    queue.extend(_items_from_clinical_memory(clinical_memory, patient, state=effective_state, patient_ref=resolved_ref))
    queue.extend(_items_from_care_pathway(care_pathway, patient, state=effective_state, patient_ref=resolved_ref))
    queue.extend(_items_from_readiness(readiness, patient, state=effective_state, patient_ref=resolved_ref))
    queue.extend(_items_from_tumor_board(tumor_board, patient, state=effective_state, patient_ref=resolved_ref))
    queue.extend(_items_from_alerts(patient, enriched, state=effective_state, patient_ref=resolved_ref))
    queue.extend(_rule_guardrails(patient, enriched, state=effective_state, patient_ref=resolved_ref))

    queue = _merge_queue_items(queue)
    queue = sorted(queue, key=lambda item: (PRIORITY_RANK.get(item.get("priority_status"), 99), -int(item.get("priority_score") or 0), str(item.get("title") or "")))
    decision_today: dict[str, Any] = {}
    try:
        from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
            build_decision_today,
            decision_today_to_autodrive_item,
        )

        preliminary_lanes = _build_lanes(queue)
        preliminary_summary = _build_summary(queue, preliminary_lanes, state=effective_state, management_track=effective_track)
        preliminary_autodrive = {
            "summary": preliminary_summary,
            "today_queue": queue[:12],
            "autodrive_actions": queue[:16],
            "state": effective_state,
            "state_label": STATE_LABELS.get(effective_state, effective_state),
        }
        decision_today = build_decision_today(
            patient,
            longitudinal_bundle={**enriched, "signals": signals},
            clinical_autodrive=preliminary_autodrive,
            state=effective_state,
            management_track=effective_track,
            patient_ref=resolved_ref,
        )
        decision_item = decision_today_to_autodrive_item(decision_today, patient_record=patient)
        if decision_today.get("decision_state") != "not_actionable":
            queue = [decision_item] + [item for item in queue if item.get("action_key") != decision_item.get("action_key")]
            queue = sorted(queue, key=lambda item: (PRIORITY_RANK.get(item.get("priority_status"), 99), -int(item.get("priority_score") or 0), str(item.get("title") or "")))
    except Exception:
        decision_today = {}
    lanes = _build_lanes(queue)
    summary = _build_summary(queue, lanes, state=effective_state, management_track=effective_track)
    contracts = build_autodrive_contract_matrix()
    contract_summary = summarize_autodrive_contracts(contracts)

    return {
        "available": True,
        "source": "clinical_autodrive_command_center",
        "version": "autodrive_command_center_v1",
        "patient_ref": resolved_ref,
        "patient_name": _patient_name(patient),
        "state": effective_state,
        "state_label": STATE_LABELS.get(effective_state, effective_state or "Sin clasificar"),
        "management_track": effective_track,
        "decision_today": decision_today,
        "summary": summary,
        "today_queue": queue[:12],
        "lanes": lanes,
        "patient_priorities": queue[:8],
        "critical_blockers": [item for item in queue if item.get("lane") in {"urgent_today", "blocked_by_data"}][:8],
        "ready_decisions": [item for item in queue if item.get("lane") == "ready_to_decide"][:8],
        "overdue_surveillance": [item for item in queue if item.get("lane") == "overdue_surveillance"][:8],
        "redecision_triggers": [item for item in queue if item.get("lane") == "redecision_required"][:8],
        "autodrive_actions": queue[:16],
        "capture_plan": _build_capture_plan(queue),
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "no_ml_model_trained": True,
            "no_external_orders": True,
            "no_fabricated_treatment": True,
            "no_fabricated_biomarkers": True,
            "priority_statuses_allowed": list(AUTODRIVE_PRIORITY_STATUSES),
            "lanes_allowed": list(AUTODRIVE_LANES),
            "sources_used": _sources_used(enriched, patient),
            "contracts": contract_summary,
            "autodrive_contract_matrix": contracts,
            "trial_empty_payload_contract": _trial_empty_payload_contract(),
        },
    }


def build_population_autodrive(
    patient_records: Iterable[Mapping[str, Any]] | None,
    *,
    longitudinal_bundles: Mapping[str, Mapping[str, Any]] | None = None,
    lane: str = "",
    stage: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """Build the population-level Autodrive queue from patient records."""
    bundles = dict(longitudinal_bundles or {})
    items: list[dict[str, Any]] = []
    patients: list[dict[str, Any]] = []
    for patient in list(patient_records or []):
        if not isinstance(patient, Mapping):
            continue
        ref = _first_text((patient.get("identity") or {}).get("nss"), patient.get("nss"), patient.get("patient_ref"), (patient.get("identity") or {}).get("id"))
        bundle = bundles.get(ref) or bundles.get(str((patient.get("identity") or {}).get("id") or "")) or {}
        autodrive = build_patient_autodrive(patient, longitudinal_bundle=bundle, patient_ref=ref)
        if stage and _stage_key(autodrive.get("state")) != _stage_key(stage) and str(autodrive.get("state") or "") != stage:
            continue
        patient_row = {
            "patient_ref": ref,
            "patient_name": autodrive.get("patient_name"),
            "state": autodrive.get("state"),
            "state_label": autodrive.get("state_label"),
            "priority_status": (autodrive.get("summary") or {}).get("priority_status"),
            "dominant_lane": (autodrive.get("summary") or {}).get("dominant_lane"),
            "dominant_blocker": (autodrive.get("summary") or {}).get("dominant_blocker"),
            "next_action": (autodrive.get("today_queue") or [{}])[0],
            "decision_today": autodrive.get("decision_today") or {},
            "queue_count": len(autodrive.get("today_queue") or []),
        }
        patients.append(patient_row)
        for item in autodrive.get("today_queue") or []:
            if lane and item.get("lane") != lane:
                continue
            items.append(item)

    items = sorted(items, key=lambda item: (PRIORITY_RANK.get(item.get("priority_status"), 99), -int(item.get("priority_score") or 0), str(item.get("patient_ref") or "")))
    if limit:
        items = items[: int(limit)]
    lanes = _build_lanes(items)
    return {
        "available": True,
        "source": "clinical_autodrive_command_center",
        "version": "autodrive_command_center_v1",
        "summary": _build_population_summary(items, patients, lanes),
        "today_queue": items,
        "lanes": lanes,
        "patient_priorities": sorted(
            patients,
            key=lambda row: (PRIORITY_RANK.get(row.get("priority_status"), 99), str(row.get("patient_ref") or "")),
        ),
        "critical_blockers": [item for item in items if item.get("lane") in {"urgent_today", "blocked_by_data"}],
        "ready_decisions": [item for item in items if item.get("lane") == "ready_to_decide"],
        "overdue_surveillance": [item for item in items if item.get("lane") == "overdue_surveillance"],
        "redecision_triggers": [item for item in items if item.get("lane") == "redecision_required"],
        "autodrive_actions": items,
        "capture_plan": _build_capture_plan(items),
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "patient_count_evaluated": len(patients),
            "no_external_orders": True,
            "no_fabricated_treatment": True,
            "no_fabricated_biomarkers": True,
            "contracts": summarize_autodrive_contracts(build_autodrive_contract_matrix()),
            "trial_empty_payload_contract": _trial_empty_payload_contract(),
        },
    }


def build_population_autodrive_from_db(
    *,
    limit: int = 50,
    lane: str = "",
    stage: str = "",
    force_recompute: bool = False,
) -> dict[str, Any]:
    """Load patients from the local tracking DB and build Autodrive."""
    import tracking_db

    max_limit = max(1, min(int(limit or 50), 250))
    conn = sqlite3.connect(tracking_db.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM patient_identity ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?",
        (max_limit,),
    )
    patient_ids = [int(row["id"]) for row in cur.fetchall()]
    conn.close()

    records: list[Mapping[str, Any]] = []
    bundles: dict[str, Mapping[str, Any]] = {}
    for patient_id in patient_ids:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            continue
        bundle = tracking_db.refresh_longitudinal_intelligence(
            patient_id,
            force_recompute=bool(force_recompute),
            record=patient,
            include_live_benchmark=False,
        ) or {}
        ref = _first_text((patient.get("identity") or {}).get("nss"), patient_id)
        records.append(patient)
        bundles[str(ref)] = bundle
        bundles[str(patient_id)] = bundle
    return build_population_autodrive(records, longitudinal_bundles=bundles, lane=lane, stage=stage, limit=max_limit)


def build_autodrive_contract_matrix() -> list[dict[str, Any]]:
    """Stable v1 contract from lane to capture/persistence/consumer."""
    return [
        {
            "autodrive_lane": "urgent_today",
            "clinical_trigger": "active safety, toxicity, progression, emergency, or critical state conflict",
            "required_fields": ["toxicity_grade", "progression_status", "testosterone", "imaging_status"],
            "capture_surface": "longitudinal_capture_or_cortana",
            "persistence": "patient_events + stage_visit_records + biomarker_longitudinal",
            "consumer": "readiness + tumor_board_os + care_pathway_os + clinical_memory_os",
            "test": "test_autodrive_progression_or_toxicity_enters_urgent_today",
        },
        {
            "autodrive_lane": "ready_to_decide",
            "clinical_trigger": "Tumor Board releaseable option with no hard blocker",
            "required_fields": ["state", "readiness_status", "option_status"],
            "capture_surface": "patient_profile_tumor_board",
            "persistence": "patient_events",
            "consumer": "care_pathway_os",
            "test": "test_autodrive_releaseable_action_gets_operational_cta",
        },
        {
            "autodrive_lane": "blocked_by_data",
            "clinical_trigger": "decision cannot be released due to missing decisive fields",
            "required_fields": ["missing_fields", "readiness_lane", "capture_plan"],
            "capture_surface": "longitudinal_capture_with_readiness_lane",
            "persistence": "biomarker_longitudinal + patient_clinical_facts + stage_visit_records",
            "consumer": "readiness + tumor_board_os",
            "test": "test_autodrive_m0crpc_without_testosterone_is_blocked_by_data",
        },
        {
            "autodrive_lane": "overdue_surveillance",
            "clinical_trigger": "scheduled event or agenda item overdue",
            "required_fields": ["due_at", "action_key", "completion_status"],
            "capture_surface": "care_pathway_or_longitudinal",
            "persistence": "scheduled_events + followup_agenda_items + patient_events",
            "consumer": "care_pathway_os + clinical_memory_os",
            "test": "test_autodrive_overdue_schedule_enters_overdue_surveillance",
        },
        {
            "autodrive_lane": "redecision_required",
            "clinical_trigger": "clinical memory or longitudinal truth flags progression, toxicity, or off-track outcome",
            "required_fields": ["outcome_status", "redecision_reason", "source_event"],
            "capture_surface": "patient_profile_memory_or_tumor_board",
            "persistence": "outcome_events + patient_events",
            "consumer": "tumor_board_os + care_pathway_os",
            "test": "test_autodrive_clinical_memory_requires_redecision",
        },
    ]


def summarize_autodrive_contracts(matrix: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(matrix or build_autodrive_contract_matrix())
    covered_lanes = {str(row.get("autodrive_lane") or "") for row in rows if row.get("autodrive_lane")}
    gates = _gate_contract_summary()
    trials = _trial_empty_payload_contract()
    return {
        "lane_contract_count": len(rows),
        "covered_lanes": sorted(covered_lanes),
        "all_lanes_covered": set(AUTODRIVE_LANES).issubset(covered_lanes),
        "gates_total": gates.get("total_gates", 0),
        "gates_contract_covered": gates.get("covered_gates", 0),
        "gates_coverage_ok": bool(gates.get("coverage_ok")),
        "trials_total": trials.get("total_trials", 0),
        "trials_empty_payload_requires_data": trials.get("requires_data_on_empty_payload", 0),
        "trials_contract_ok": bool(trials.get("contract_ok")),
    }


def _ensure_source_bundles(patient: Mapping[str, Any], bundle: Mapping[str, Any], *, state: str, management_track: str, patient_ref: str) -> dict[str, Any]:
    enriched = dict(bundle or {})
    signals = dict(enriched.get("signals") or patient.get("latest_signal_snapshot") or {})
    enriched["signals"] = signals
    readiness = dict(enriched.get("clinical_readiness_tower") or patient.get("clinical_readiness_tower") or signals.get("clinical_readiness_tower") or {})
    if not readiness:
        try:
            from prostanet.domains.patient_tracking.clinical_readiness_tower import build_clinical_readiness_tower

            readiness = build_clinical_readiness_tower(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            readiness = {}
    enriched["clinical_readiness_tower"] = readiness

    tumor_board = dict(enriched.get("tumor_board_os") or patient.get("tumor_board_os") or signals.get("tumor_board_os") or {})
    if not tumor_board:
        try:
            from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

            tumor_board = build_tumor_board_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            tumor_board = {}
    enriched["tumor_board_os"] = tumor_board

    care_pathway = dict(enriched.get("care_pathway_os") or patient.get("care_pathway_os") or signals.get("care_pathway_os") or {})
    if not care_pathway:
        try:
            from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os

            care_pathway = build_care_pathway_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            care_pathway = {}
    enriched["care_pathway_os"] = care_pathway

    memory = dict(enriched.get("clinical_memory_os") or patient.get("clinical_memory_os") or signals.get("clinical_memory_os") or {})
    if not memory:
        try:
            from prostanet.domains.patient_tracking.clinical_memory_os import build_clinical_memory_os

            memory = build_clinical_memory_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            memory = {}
    enriched["clinical_memory_os"] = memory
    return enriched


def _items_from_clinical_memory(memory: Mapping[str, Any], patient: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    summary = dict(memory.get("summary") or {})
    observed = dict(memory.get("expected_vs_observed") or {})
    redecision_reasons = list(memory.get("redecision_reasons") or [])
    outcome_status = _first_text(summary.get("outcome_status"), observed.get("status"))
    if summary.get("requires_redecision") or outcome_status in {"requires_redecision", "off_track", "toxicity_limited"} or redecision_reasons:
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane="redecision_required",
                priority_status="critical_today" if outcome_status in {"requires_redecision", "toxicity_limited"} else "high_today",
                score=92,
                title="Reabrir decision clinica",
                reason=_first_text((redecision_reasons[0] or {}).get("reason") if redecision_reasons and isinstance(redecision_reasons[0], Mapping) else "", summary.get("dominant_redecision_reason"), "Clinical Memory detecta desenlace que exige nueva decision."),
                risk_avoided="Evita continuar una ruta off-track sin reevaluacion.",
                action_key="autodrive:memory_redecision",
                source_bundles=["clinical_memory_os"],
                cta=_cta(patient_ref, "Abrir Tumor Board", f"/patient_profile/{patient_ref}?v=2#pm2TumorBoardOS"),
                trials=summary.get("trials_impacted") or [],
                gates=summary.get("gates_impacted") or [],
            )
        )
    if outcome_status in {"toxicity_limited", "off_track"}:
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane="urgent_today",
                priority_status="critical_today",
                score=94,
                title="Atender riesgo activo del desenlace",
                reason=_first_text(observed.get("reason"), summary.get("dominant_redecision_reason"), "Clinical Memory marca toxicidad o evolucion off-track."),
                risk_avoided="Evita retrasar una intervencion de seguridad clinica.",
                action_key=f"autodrive:memory_urgent:{outcome_status}",
                source_bundles=["clinical_memory_os"],
                cta=_cta(patient_ref, "Abrir Care Pathway", f"/patient_profile/{patient_ref}?v=2#pm2CarePathwayOS"),
                trials=summary.get("trials_impacted") or [],
                gates=summary.get("gates_impacted") or [],
            )
        )
    return items


def _items_from_care_pathway(pathway: Mapping[str, Any], patient: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for action in list(pathway.get("pathway_actions") or [])[:32]:
        if not isinstance(action, Mapping):
            continue
        status = str(action.get("status") or "").lower()
        key = str(action.get("action_key") or "")
        label = _first_text(action.get("label"), action.get("title"), action.get("action_label"), "Accion clinica")
        lane = ""
        priority = "routine_today"
        score = 45
        if status == "overdue":
            lane, priority, score = "overdue_surveillance", "high_today", 78
        elif status == "blocked":
            lane, priority, score = "blocked_by_data", "high_today", 74
        elif status in {"pending", "ordered", "scheduled"} and action.get("critical"):
            lane, priority, score = "urgent_today", "critical_today", 88
        elif status in {"pending", "ordered", "scheduled"}:
            lane, priority, score = "ready_to_decide", "routine_today", 58
        if not lane:
            continue
        readiness_lane = _first_text(action.get("readiness_lane"), action.get("lane_key"))
        href = _first_text(action.get("cta_href"))
        if not href:
            if readiness_lane:
                href = f"/longitudinal-capture/{patient_ref}?readiness_lane={readiness_lane}"
            else:
                href = f"/patient_profile/{patient_ref}?v=2#pm2CarePathwayOS"
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane=lane,
                priority_status=priority,
                score=score,
                title=label,
                reason=_first_text(action.get("reason"), action.get("rationale"), "Care Pathway OS marca accion operativa."),
                risk_avoided="Evita perdida de ventana terapeutica o vigilancia tardia.",
                missing_fields=_missing_fields_from_action(action),
                action_key=key or f"autodrive:care:{len(items)}",
                source_bundles=["care_pathway_os"],
                cta=_cta(patient_ref, _first_text(action.get("cta_label"), "Resolver accion"), href, readiness_lane=readiness_lane),
                trials=action.get("trials_affected") or action.get("trials_impacted") or [],
                gates=action.get("gates_affected") or action.get("gates_impacted") or [],
                due_at=_first_text(action.get("ideal_due_at"), action.get("due_at"), action.get("scheduled_due_at")),
                status=status,
            )
        )
    return items


def _items_from_readiness(readiness: Mapping[str, Any], patient: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for lane in list(readiness.get("lanes") or []):
        if not isinstance(lane, Mapping):
            continue
        lane_key = str(lane.get("key") or "")
        status = str(lane.get("status") or "")
        if status not in {"active_risk", "requires_data", "overdue", "ready"}:
            continue
        if _bcr_state(state) and _contains_crpc_precision(lane_key):
            continue
        ad_lane = "ready_to_decide" if status == "ready" else "urgent_today" if status == "active_risk" else "overdue_surveillance" if status == "overdue" else "blocked_by_data"
        priority = "critical_today" if status == "active_risk" else "high_today" if status in {"requires_data", "overdue"} else "routine_today"
        score = 84 if status == "active_risk" else 72 if status in {"requires_data", "overdue"} else 52
        missing = _missing_fields_from_lane(lane)
        href = f"/longitudinal-capture/{patient_ref}?readiness_lane={lane_key}" if ad_lane != "ready_to_decide" else f"/patient_profile/{patient_ref}?v=2#pm2TumorBoardOS"
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane=ad_lane,
                priority_status=priority,
                score=score,
                title=_first_text(lane.get("label"), "Readiness clinico"),
                reason=_first_text(lane.get("reason"), "Readiness clinico requiere accion."),
                risk_avoided="Evita liberar una decision sin dataset clinico suficiente.",
                missing_fields=missing,
                action_key=f"autodrive:readiness:{lane_key or status}",
                source_bundles=["clinical_readiness_tower"],
                cta=_cta(patient_ref, "Capturar datos" if ad_lane != "ready_to_decide" else "Abrir Tumor Board", href, readiness_lane=lane_key),
                trials=lane.get("trials_affected") or [],
                gates=lane.get("gates_affected") or [],
                status=status,
            )
        )
    return items


def _items_from_tumor_board(board: Mapping[str, Any], patient: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for option in list(board.get("options") or [])[:12]:
        if not isinstance(option, Mapping):
            continue
        if not _option_applicable_to_state(option, state):
            continue
        status = str(option.get("status") or "").lower()
        if status not in {"releaseable", "requires_data", "blocked", "provisional"}:
            continue
        lane = "ready_to_decide" if status == "releaseable" else "blocked_by_data" if status in {"requires_data", "blocked"} else "ready_to_decide"
        priority = "high_today" if status == "releaseable" else "high_today" if status in {"requires_data", "blocked"} else "routine_today"
        score = 76 if status == "releaseable" else 68 if status in {"requires_data", "blocked"} else 54
        label = _first_text(option.get("label"), option.get("title"), "Opcion Tumor Board")
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane=lane,
                priority_status=priority,
                score=score,
                title=label,
                reason=_first_text(option.get("rationale"), option.get("why"), "Tumor Board OS compara esta opcion hoy."),
                risk_avoided="Evita decidir sin comparar opciones competidoras.",
                missing_fields=_missing_fields_from_action(option),
                action_key=f"autodrive:tumor_board:{option.get('key') or label}",
                source_bundles=["tumor_board_os"],
                cta=_cta(patient_ref, "Abrir Tumor Board", f"/patient_profile/{patient_ref}?v=2#pm2TumorBoardOS"),
                trials=option.get("trials_impacted") or option.get("trials_affected") or [],
                gates=option.get("gates_impacted") or option.get("gates_affected") or [],
                status=status,
            )
        )
    return items


def _items_from_alerts(patient: Mapping[str, Any], bundle: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    alerts = list(patient.get("alerts") or []) + list(bundle.get("copilot_alerts") or [])
    items: list[dict[str, Any]] = []
    for idx, alert in enumerate(alerts[:8]):
        if not isinstance(alert, Mapping):
            continue
        severity = str(alert.get("severity") or alert.get("level") or "").lower()
        if severity not in {"critical", "high", "error", "urgent"}:
            continue
        items.append(
            _item(
                patient,
                patient_ref=patient_ref,
                state=state,
                lane="urgent_today",
                priority_status="critical_today",
                score=90,
                title=_first_text(alert.get("title"), alert.get("message"), "Alerta clinica activa"),
                reason=_first_text(alert.get("message"), alert.get("rationale"), "Existe una alerta clinica activa."),
                risk_avoided="Evita ignorar una senal critica activa.",
                action_key=f"autodrive:alert:{alert.get('id') or idx}",
                source_bundles=["signals", "smart_alerts"],
                cta=_cta(patient_ref, "Abrir perfil", f"/patient_profile/{patient_ref}?v=2"),
                status=severity,
            )
        )
    return items


def _rule_guardrails(patient: Mapping[str, Any], bundle: Mapping[str, Any], *, state: str, patient_ref: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    values = _merged_values(patient, bundle)
    if state == "m0_crpc":
        missing = []
        if not values.get("testosterone"):
            missing.append("testosterone")
        if not values.get("psadt"):
            missing.append("psadt")
        if not values.get("conventional_m0"):
            missing.append("conventional_imaging_m0")
        if missing:
            items.append(_guardrail_item(patient, patient_ref, state, "m0CRPC bloqueado por dataset incompleto", missing, "crpc_confirmation_readiness"))
    if state.startswith("mcspc") or state in {"mhspc", "metastatic_cspc"}:
        missing = []
        if not values.get("m1_composition"):
            missing.append("m1_composition")
        if not values.get("volume_risk"):
            missing.append("volume_or_risk")
        if missing:
            items.append(_guardrail_item(patient, patient_ref, state, "mHSPC bloqueado por composicion M1/volumen", missing, "mhspc_precision_readiness"))
    if state == "m1_crpc" and not _real_treatment_lines(patient):
        items.append(_guardrail_item(patient, patient_ref, state, "m1CRPC sin linea terapeutica real", ["real_treatment_line"], "m1crpc_sequence_readiness"))
    return items


def _guardrail_item(patient: Mapping[str, Any], patient_ref: str, state: str, title: str, missing: list[str], readiness_lane: str) -> dict[str, Any]:
    return _item(
        patient,
        patient_ref=patient_ref,
        state=state,
        lane="blocked_by_data",
        priority_status="high_today",
        score=82,
        title=title,
        reason="Regla clinica Autodrive impide liberar la decision sin datos decisivos.",
        risk_avoided="Evita recomendacion insegura por datos criticos faltantes.",
        missing_fields=missing,
        action_key=f"autodrive:guardrail:{readiness_lane}",
        source_bundles=["clinical_autodrive_command_center", "clinical_readiness_tower"],
        cta=_cta(patient_ref, "Capturar datos faltantes", f"/longitudinal-capture/{patient_ref}?readiness_lane={readiness_lane}", readiness_lane=readiness_lane),
    )


def _item(
    patient: Mapping[str, Any],
    *,
    patient_ref: str,
    state: str,
    lane: str,
    priority_status: str,
    score: int,
    title: str,
    reason: str,
    risk_avoided: str,
    action_key: str,
    source_bundles: list[str],
    cta: Mapping[str, Any],
    missing_fields: Iterable[Any] | None = None,
    gates: Iterable[Any] | None = None,
    trials: Iterable[Any] | None = None,
    due_at: str = "",
    status: str = "",
) -> dict[str, Any]:
    return {
        "patient_ref": str(patient_ref or ""),
        "patient_name": _patient_name(patient),
        "state": state,
        "state_label": STATE_LABELS.get(state, state or "Sin clasificar"),
        "stage": _stage_key(state),
        "lane": lane,
        "lane_label": LANE_LABELS.get(lane, lane),
        "priority_status": priority_status if priority_status in AUTODRIVE_PRIORITY_STATUSES else "watchlist",
        "priority_score": int(score or 0),
        "title": str(title or "Accion Autodrive"),
        "reason": str(reason or ""),
        "risk_avoided": str(risk_avoided or ""),
        "missing_fields": _clean_list(missing_fields),
        "source_bundles": _clean_list(source_bundles),
        "gates_affected": _clean_list(gates),
        "trials_affected": _clean_list(trials),
        "cta": dict(cta or {}),
        "action_key": str(action_key or "autodrive:action"),
        "due_at": str(due_at or ""),
        "status": str(status or ""),
        "external_order_created": False,
        "write_requires_review": True,
    }


def _merge_queue_items(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        key = _first_text(item.get("action_key"), item.get("title"))
        if key in merged:
            current = merged[key]
            if int(item.get("priority_score") or 0) > int(current.get("priority_score") or 0):
                merged[key] = item
            else:
                current["missing_fields"] = _clean_list(list(current.get("missing_fields") or []) + list(item.get("missing_fields") or []))
                current["source_bundles"] = _clean_list(list(current.get("source_bundles") or []) + list(item.get("source_bundles") or []))
            continue
        merged[key] = item
    return list(merged.values())


def _build_lanes(queue: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items = list(queue or [])
    lanes = []
    for lane in AUTODRIVE_LANES:
        lane_items = [dict(item) for item in items if item.get("lane") == lane]
        lanes.append(
            {
                "key": lane,
                "label": LANE_LABELS[lane],
                "count": len(lane_items),
                "top_items": lane_items[:5],
                "highest_priority": lane_items[0].get("priority_status") if lane_items else "not_actionable",
                "empty_message": "Sin pacientes en este carril." if not lane_items else "",
            }
        )
    return lanes


def _build_summary(queue: list[Mapping[str, Any]], lanes: list[Mapping[str, Any]], *, state: str, management_track: str) -> dict[str, Any]:
    top = dict(queue[0]) if queue else {}
    status_counts = {status: 0 for status in AUTODRIVE_PRIORITY_STATUSES}
    for item in queue:
        status = str(item.get("priority_status") or "not_actionable")
        status_counts[status] = status_counts.get(status, 0) + 1
    lane_counts = {lane["key"]: lane["count"] for lane in lanes}
    return {
        "queue_count": len(queue),
        "priority_status": top.get("priority_status") or "not_actionable",
        "dominant_lane": top.get("lane") or "",
        "dominant_lane_label": top.get("lane_label") or "",
        "dominant_blocker": top.get("reason") or "Sin accion clinica activa hoy.",
        "top_action_title": top.get("title") or "Sin accion Autodrive hoy",
        "top_action_key": top.get("action_key") or "",
        "top_cta": top.get("cta") or {},
        "risk_avoided": top.get("risk_avoided") or "",
        "state": state,
        "management_track": management_track,
        "status_counts": status_counts,
        "lane_counts": lane_counts,
        "ready_decision_count": lane_counts.get("ready_to_decide", 0),
        "blocked_count": lane_counts.get("blocked_by_data", 0),
        "overdue_count": lane_counts.get("overdue_surveillance", 0),
        "redecision_count": lane_counts.get("redecision_required", 0),
    }


def _build_population_summary(items: list[Mapping[str, Any]], patients: list[Mapping[str, Any]], lanes: list[Mapping[str, Any]]) -> dict[str, Any]:
    base = _build_summary(items, lanes, state="population", management_track="")
    base.update(
        {
            "patient_count": len(patients),
            "critical_patient_count": sum(1 for row in patients if row.get("priority_status") == "critical_today"),
            "actionable_patient_count": sum(1 for row in patients if row.get("priority_status") not in {"watchlist", "not_actionable", ""}),
        }
    )
    return base


def _build_capture_plan(queue: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for item in queue:
        fields = list(item.get("missing_fields") or [])
        if not fields:
            continue
        lane = str(item.get("lane") or "blocked_by_data")
        group = groups.setdefault(
            lane,
            {
                "lane": lane,
                "lane_label": LANE_LABELS.get(lane, lane),
                "fields": [],
                "cta": item.get("cta") or {},
            },
        )
        group["fields"] = _clean_list(list(group.get("fields") or []) + fields)
    return {
        "total_missing_fields": sum(len(group.get("fields") or []) for group in groups.values()),
        "groups": list(groups.values()),
        "empty_message": "No hay datos faltantes Autodrive." if not groups else "",
    }


def _missing_fields_from_lane(lane: Mapping[str, Any]) -> list[str]:
    fields: list[Any] = []
    fields.extend(lane.get("missing_fields") or [])
    fields.extend(lane.get("required_missing_fields") or [])
    cp = lane.get("capture_plan") or {}
    if isinstance(cp, Mapping):
        fields.extend(cp.get("missing_fields") or [])
        for group in cp.get("groups") or []:
            if isinstance(group, Mapping):
                fields.extend(group.get("fields") or [])
    return _clean_list(fields)


def _missing_fields_from_action(action: Mapping[str, Any]) -> list[str]:
    fields: list[Any] = []
    for key in ("missing_fields", "required_fields", "data_that_could_change_course"):
        raw = action.get(key)
        if key == "required_fields" and action.get("status") not in {"requires_data", "blocked"}:
            continue
        fields.extend(raw or [])
    return _clean_list(fields)


def _cta(patient_ref: str, label: str, href: str, *, readiness_lane: str = "") -> dict[str, Any]:
    return {
        "label": label,
        "href": href,
        "action_mode": "capture" if "longitudinal-capture" in href else "review",
        "readiness_lane": readiness_lane,
        "patient_ref": patient_ref,
    }


def _option_applicable_to_state(option: Mapping[str, Any], state: str) -> bool:
    key_text = " ".join(str(option.get(k) or "") for k in ("key", "label", "clinical_role", "family_code")).lower()
    if _bcr_state(state) and any(token in key_text for token in CRPC_OPTION_TOKENS):
        return False
    if state == "m0_crpc" and any(token in key_text for token in ("bcr", "salvage", "post_rp", "post_rt")):
        return False
    if "parp" in key_text or "psma_rlt" in key_text or "rlt" in key_text:
        return state == "m1_crpc"
    return True


def _merged_values(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    baseline = dict(patient.get("baseline") or patient.get("clinical_baseline") or {})
    signals = dict(bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    values = {**baseline, **signals}
    psa_series = list(patient.get("psa_series") or [])
    testo_series = list(patient.get("testosterone_series") or [])
    if testo_series:
        values["testosterone"] = _first_text(testo_series[-1].get("value"), values.get("testosterone"), values.get("testosterone_value"))
    values["psadt"] = _first_text(values.get("psadt"), values.get("psadt_months"), baseline.get("psadt_months"))
    values["conventional_m0"] = bool(_first_text(values.get("conventional_imaging_m0"), values.get("conventional_imaging_status"), values.get("m0_conventional_confirmed")))
    values["m1_composition"] = bool(_first_text(values.get("metastatic_stage_resolved"), baseline.get("metastasis_site"), values.get("m1_sites"), values.get("m1_composition")))
    values["volume_risk"] = bool(_first_text(values.get("volume_disease"), baseline.get("volume_disease"), values.get("chaarted_volume"), values.get("latitude_risk")))
    if psa_series:
        values["psa"] = psa_series[-1].get("value")
    return values


def _real_treatment_lines(patient: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = []
    for tx in patient.get("treatments") or patient.get("treatment_history") or []:
        if not isinstance(tx, Mapping):
            continue
        label = _first_text(tx.get("drug_scheme"), tx.get("regimen"), tx.get("label"), tx.get("treatment_name"))
        if label and label not in {"-", "—", "none", "sin tratamiento"}:
            rows.append(tx)
    return rows


def _stage_key(state: str | None) -> str:
    s = str(state or "").lower()
    if "m1_crpc" in s or "m1crpc" in s:
        return "m1crpc"
    if "m0_crpc" in s or "m0crpc" in s or "nmcrpc" in s:
        return "m0crpc"
    if "mcspc" in s or "mhspc" in s or "cspc" in s:
        return "mcspc"
    if "bcr" in s or "post_prostatectomy" in s or "post_radiotherapy" in s or "localized" in s:
        return "localized"
    if "palliative" in s or "paliativo" in s:
        return "palliative"
    if "nepc" in s:
        return "nepc"
    return "diagnostic"


def _bcr_state(state: str) -> bool:
    s = str(state or "").lower()
    return "bcr" in s or "post_prostatectomy" in s or "post_radiotherapy" in s


def _contains_crpc_precision(text: str) -> bool:
    return any(token in str(text or "").lower() for token in CRPC_OPTION_TOKENS)


def _patient_name(patient: Mapping[str, Any]) -> str:
    identity = dict(patient.get("identity") or {})
    return _first_text(identity.get("full_name"), patient.get("full_name"), patient.get("name"), "Paciente")


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        text = str(value).strip()
        if text and text.lower() not in {"none", "null", "nan", "—", "-"}:
            return text
    return ""


def _clean_list(values: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if isinstance(value, Mapping):
            text = _first_text(value.get("field"), value.get("field_name"), value.get("key"), value.get("label"), value.get("code"), value.get("title"))
        else:
            text = _first_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _sources_used(bundle: Mapping[str, Any], patient: Mapping[str, Any]) -> list[str]:
    sources = []
    for key in ("signals", "clinical_readiness_tower", "tumor_board_os", "care_pathway_os", "clinical_memory_os", "longitudinal_truth_snapshot"):
        if bundle.get(key):
            sources.append(key)
    if patient.get("agenda_items"):
        sources.append("followup_agenda_items")
    if patient.get("scheduled_events"):
        sources.append("scheduled_events")
    if patient.get("patient_events"):
        sources.append("patient_events")
    return sorted(set(sources))


def _gate_contract_summary() -> dict[str, Any]:
    try:
        from prostanet.domains.patient_tracking.clinical_readiness_tower import summarize_readiness_gate_contracts

        summary = summarize_readiness_gate_contracts()
        total = int(summary.get("total_gates") or summary.get("gate_count") or summary.get("total") or 0)
        covered = int(summary.get("covered_gates") or summary.get("covered_gate_count") or total or 0)
        return {"total_gates": total, "covered_gates": covered, "coverage_ok": covered >= total and total > 0}
    except Exception:
        return {"total_gates": 0, "covered_gates": 0, "coverage_ok": False}


def _trial_empty_payload_contract() -> dict[str, Any]:
    try:
        from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
        from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    except Exception:
        return {"total_trials": 0, "requires_data_on_empty_payload": 0, "contract_ok": False, "failures": []}

    failures: list[str] = []
    for trial_id in TRIAL_CRITERIA_REGISTRY:
        try:
            result = evaluate_trial_eligibility({}, trial_id)
        except Exception:
            failures.append(str(trial_id))
            continue
        status = str(result.get("status") or "").lower()
        eligible = bool(result.get("eligible"))
        missing = bool(result.get("missing_data") or result.get("missing_fields"))
        if eligible or (missing and status not in {"requires_data", "indeterminate", "not_evaluable"}):
            failures.append(str(trial_id))
    total = len(TRIAL_CRITERIA_REGISTRY)
    return {
        "total_trials": total,
        "requires_data_on_empty_payload": total - len(failures),
        "contract_ok": not failures and total > 0,
        "failures": failures[:12],
    }
