from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from prostanet.domains.patient_tracking.capture_surface import display_capture_field_summary
from prostanet.shared.contracts import (
    MasterFollowupPlan,
    ScenarioCadenceRule,
    ScheduleAnchorAssessment,
)
from prostanet.shared.ui_value_normalizer import normalize_field_list


PLAN_VERSION = "2026.1"
DEFAULT_CALENDAR_HORIZON_MONTHS = 12


SCENARIO_FOLLOWUP_MATRIX: dict[str, dict[str, Any]] = {
    "diagnostic_workup": {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026 diagnóstico", "EAU 2026 diagnóstico"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["PSA seriado mientras se completa MRI/biopsia.", "Escalar a biopsia dirigida + sistemática si persiste señal de riesgo."],
        "encounter_templates": ["diagnostic_followup", "diagnostic_workup", "documentation"],
        "required_tasks": ["psa", "mri", "biopsy"],
        "escalation_rules": ["MRI o biopsia vencidas elevan seguimiento diagnóstico prioritario."],
    },
    "post_negative_biopsy_followup": {
        "phase_label": "Fase 2",
        "guideline_basis": ["EAU 2026 repeat biopsy", "NCCN 2026 early detection"],
        "anchor_priority": ["biopsy_details.biopsy_date", "stage_visit_records.visit_date", "latest_assessment.created_at"],
        "cadence_rules": ["PSA/PSAD seriado y mpMRI de control.", "Rebiopsia si persisten triggers anatómicos o bioquímicos."],
        "encounter_templates": ["diagnostic_followup", "diagnostic_workup"],
        "required_tasks": ["psa", "mri", "biopsy"],
        "escalation_rules": ["Persistencia de señal pese a biopsia benigna reabre estudio diagnóstico."],
    },
    "localized_initial": {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026 localized disease", "EAU 2026 localized disease"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Alinear riesgo, histología y preferencias antes de definir manejo local.", "Si vigilancia activa es elegible, protocolizar PSA, MRI y biopsia confirmatoria."],
        "encounter_templates": ["localized_decision", "surveillance_visit", "surveillance_restage"],
        "required_tasks": ["psa", "pro_assessment", "therapy_review"],
        "escalation_rules": ["Riesgo desfavorable o histología adversa desplazan vigilancia activa."],
    },
    "post_prostatectomy": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 post-prostatectomy", "EAU 2026 salvage window"],
        "anchor_priority": ["surgical_details.surgery_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA ultrasensible estrecho durante los primeros 24 meses.", "Vigilar continencia, función sexual y ventana curativa de rescate."],
        "encounter_templates": ["postlocal_followup", "salvage_restage", "documentation"],
        "required_tasks": ["psa", "pro_assessment", "imaging"],
        "escalation_rules": ["Ascenso bioquímico o margen/estadio adverso aceleran reestadificación y rescate."],
    },
    "recurrence_bcr": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 BCR", "EAU 2026 salvage"],
        "anchor_priority": ["biochemical_recurrence.bcr_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA ultrasensible y PSADT sostienen la ventana de rescate.", "Imagen dirigida cuando cambia factibilidad de salvamento o intensificación."],
        "encounter_templates": ["postlocal_followup", "salvage_restage", "documentation"],
        "required_tasks": ["psa", "imaging", "therapy_review"],
        "escalation_rules": ["PSADT rápido o imagen positiva elevan prioridad del salvamento."],
    },
    "adt_progression_verification": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 CRPC workup", "EAU 2026 progression under ADT"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Carril corto de confirmación bajo ADT.", "Verificar testosterona, backbone ADT, línea terapéutica, PSA/labs y reestadificación antes de llamar CRPC."],
        "encounter_templates": ["progression_confirmation", "progression_support", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "imaging", "supportive_care"],
        "escalation_rules": ["Si testosterona no está en castración, no escalar a CRPC.", "Anchor fallback debe generar alerta de fortalecimiento del protocolo."],
    },
    "mcspc_oligo_metachronous": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico con labs, PSA, seguridad y reestadificación.", "Mantener revisión de línea terapéutica y backbone ADT en cada visita."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Cambio de carga tumoral o progresión oligometastásica reabre reestadificación."],
    },
    "mcspc_low_volume_sync_oligo": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA/labs trimestrales y reestadificación protocolizada.", "Monitorear seguridad, soporte óseo y tolerabilidad de intensificación."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Cualquier cambio de línea o progresión radiográfica acelera encounter clínico."],
    },
    "mcspc_high_volume_sync": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC", "ARASENS", "PEACE-1", "ARANOTE"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica, aptitud a docetaxel y tolerancia por línea terapéutica en enfermedad sincrónica / de novo."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación.", "Si docetaxel deja de ser apropiado, reabrir la selección del mejor doblete visible según elegibilidad clínica."],
    },
    "mcspc_high_volume_metachronous": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC", "ARASENS", "ARANOTE"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica y tolerancia por línea evitando sobreextrapolar PEACE-1 como backbone metacrónico principal."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación.", "Si docetaxel deja de ser apropiado, reabrir la selección del mejor doblete visible según elegibilidad clínica."],
    },
    "mcspc_high_volume": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica y tolerancia por línea terapéutica."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación."],
    },
    "m0_crpc": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 nmCRPC", "EAU 2026 CRPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA/labs seriados y verificación de castración sostenida.", "Reestadificar si cinética o clínica sugieren transición metastásica."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care"],
        "escalation_rules": ["PSADT acelerado o nueva imagen positiva escalan a revisión inmediata."],
    },
    "m1_crpc": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mCRPC", "EAU 2026 mCRPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Visita sistémica con labs, seguridad, reestadificación y revisión terapéutica.", "Biomarcadores y PSMA deben mantenerse actualizados por línea activa."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Biomarcador o PSMA faltante bloquean decisiones de precisión."],
    },
}


# EPIC 9 Group F (GAP-15 / OOS-11+OOS-12) — Conjuntos de estados donde el
# `therapeutic_readiness_bundle` puede llegar vacío en `latest_signal_snapshot`
# cuando la reconciliación PSMA/Phoenix aún no materializó el bundle, pero donde
# sí existen señales adyacentes (staging_adjudication_bundle, advanced_followup_bundle,
# supportive_care_toxicity_readiness_bundle) que permiten derivar un status de
# respaldo en lugar de mostrar la celda en blanco en el summary del plan maestro.
_RESTAGING_BLOCK_STATES = {
    "m0_crpc",
    "m1_crpc",
    "adt_progression_verification",
    "recurrence_bcr",
    "post_radiotherapy_or_local_salvage",
    "post_rt_local_salvage",
    "post_prostatectomy",
}

_BLOCKED_STATUSES = {"blocked_by_missing_data", "conditional_pending_closure"}


def _compute_readiness_fallback_status(
    state: str,
    therapeutic_readiness_bundle: dict[str, Any],
    staging_adjudication_bundle: dict[str, Any],
    advanced_followup_bundle: dict[str, Any],
    supportive_care_bundle: dict[str, Any],
    signals: dict[str, Any],
) -> tuple[str, str, str]:
    """EPIC 9 Group F (GAP-15) — Fallback para `therapeutic_readiness_status`.

    Cuando el `therapeutic_readiness_bundle` llega vacío desde `latest_signal_snapshot`
    (p. ej. m0_crpc PSMA-only upstaging antes de que se materialice la adjudicación
    en el snapshot persistido), deriva `readiness_status` / `adjudication_gate_status`
    / `monitoring_gate_status` desde los bundles adyacentes y desde señales de
    `critical_missing`/`awaiting_review`. Cierra OOS-11 (BCR/post-RT) y OOS-12
    (m0_crpc PSMA) sin duplicar la lógica en cada consumidor downstream.

    Contrato defensivo: un bundle **completamente vacío** en un estado de decisión
    implica que la capa longitudinal aún no materializó la readiness — mostrar la
    celda del summary en blanco es peor que documentar `blocked_by_missing_data`
    (el usuario clínico debe saber que falta la decisión, no que "todo está bien").

    Retorna tupla (readiness_status, monitoring_gate_status, adjudication_gate_status).
    """
    readiness = str(therapeutic_readiness_bundle.get("readiness_status") or "")
    monitoring = str(therapeutic_readiness_bundle.get("monitoring_gate_status") or "")
    adjudication = str(therapeutic_readiness_bundle.get("adjudication_gate_status") or "")
    if readiness and adjudication:
        return readiness, monitoring, adjudication

    # Señales adyacentes que, si están pobladas con status bloqueado, propagan
    # directamente al readiness summary.
    adjudication_release = str(
        staging_adjudication_bundle.get("adjudication_release_status") or ""
    )
    advanced_missing = list(advanced_followup_bundle.get("display_missing_inputs") or [])
    advanced_confidence = str(
        advanced_followup_bundle.get("confidence_status") or ""
    )
    supportive_status = str(supportive_care_bundle.get("supportive_readiness_status") or "")

    # Señales de falta de datos materializadas en el snapshot persistido
    # (`latest_signal_snapshot.critical_missing` / `awaiting_review`).
    critical_missing = list(signals.get("critical_missing") or [])
    awaiting_review = list(signals.get("awaiting_review") or [])
    ready_to_restage = signals.get("ready_to_restage")
    restaging_required = bool(signals.get("restaging_update_required"))
    psma_only_upstaging = bool(signals.get("psma_only_upstaging")) or str(
        signals.get("metastatic_detection_basis") or ""
    ) == "psma_only"
    restaging_state_ambiguous = state in _RESTAGING_BLOCK_STATES and (
        restaging_required or psma_only_upstaging or bool(ready_to_restage)
    )

    # Contrato: bundle completamente vacío en estado decisional ⇒ blocked.
    bundle_entirely_empty = not therapeutic_readiness_bundle
    empty_bundle_in_decision_state = bundle_entirely_empty and state in _RESTAGING_BLOCK_STATES

    blocked_conditions = any(
        (
            adjudication_release in _BLOCKED_STATUSES,
            bool(advanced_missing) or advanced_confidence in _BLOCKED_STATUSES,
            supportive_status in _BLOCKED_STATUSES,
            restaging_state_ambiguous,
            bool(critical_missing) and state in _RESTAGING_BLOCK_STATES,
            bool(awaiting_review) and state in _RESTAGING_BLOCK_STATES,
            empty_bundle_in_decision_state,
        )
    )
    if not blocked_conditions:
        return readiness, monitoring, adjudication

    if not readiness:
        readiness = "blocked_by_missing_data"
    if not adjudication:
        adjudication = adjudication_release or "blocked_by_missing_data"
    if not monitoring:
        monitoring = "supported"
    return readiness, monitoring, adjudication


def _unique_preserving(values: list[Any]) -> list[Any]:
    ordered: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, "", [], {}):
            continue
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(value)
    return ordered


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _timeline_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("ideal_due_at") or item.get("due_at") or ""),
        str(item.get("scheduled_due_at") or item.get("due_at") or ""),
        str(item.get("title") or ""),
    )


def _within_horizon(item: dict[str, Any], anchor_dt: date, horizon_months: int) -> bool:
    reference = _parse_iso_date(item.get("scheduled_due_at") or item.get("ideal_due_at") or item.get("due_at"))
    if reference is None:
        return True
    horizon_days = max(horizon_months, 1) * 31
    return reference <= (anchor_dt + timedelta(days=horizon_days))


def _scenario_rule(state: str, management_track: str) -> dict[str, Any]:
    raw = SCENARIO_FOLLOWUP_MATRIX.get(state) or {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026", "EAU 2026"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Mantener seguimiento reconciliado por estado y track."],
        "encounter_templates": ["systemic_followup"],
        "required_tasks": [],
        "escalation_rules": [],
    }
    return ScenarioCadenceRule(
        scenario_state=state,
        management_track=management_track,
        phase_label=str(raw.get("phase_label") or "Fase 2"),
        guideline_basis=list(raw.get("guideline_basis") or []),
        anchor_priority=list(raw.get("anchor_priority") or []),
        cadence_rules=list(raw.get("cadence_rules") or []),
        encounter_templates=list(raw.get("encounter_templates") or []),
        required_tasks=list(raw.get("required_tasks") or []),
        escalation_rules=list(raw.get("escalation_rules") or []),
    ).to_dict()


def _summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    required_inputs = list(item.get("required_inputs") or [])
    display_required_inputs = display_capture_field_summary(
        required_inputs,
        required_inputs=required_inputs,
        limit=8,
    )
    return {
        "agenda_key": item.get("agenda_key", ""),
        "title": item.get("title", ""),
        "status": item.get("status", ""),
        "due_at": item.get("due_at", ""),
        "item_type": item.get("item_type", ""),
        "summary": item.get("summary", ""),
        "required_inputs": required_inputs,
        "display_required_inputs": display_required_inputs,
        "display_fields_summary": list(item.get("display_fields_summary") or display_required_inputs),
    }


def _summarize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    display_fields = display_capture_field_summary(alert.get("fields_to_capture") or [], limit=8)
    return {
        "alert_key": alert.get("alert_key", ""),
        "title": alert.get("title", ""),
        "severity": alert.get("severity", ""),
        "category": alert.get("category", ""),
        "decision_domain": alert.get("decision_domain", ""),
        "recommended_action": alert.get("recommended_action", ""),
        "action_type": alert.get("action_type", ""),
        "fields_to_capture": list(alert.get("fields_to_capture") or []),
        "display_fields_to_capture": display_fields,
    }


def link_alerts_to_encounters(encounters: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts_by_encounter: dict[str, list[dict[str, Any]]] = {}
    for alert in alerts or []:
        for encounter_key in alert.get("linked_encounter_keys") or []:
            if encounter_key:
                alerts_by_encounter.setdefault(str(encounter_key), []).append(alert)

    enriched: list[dict[str, Any]] = []
    for encounter in encounters or []:
        current = dict(encounter)
        linked = alerts_by_encounter.get(str(current.get("encounter_key") or ""), [])
        current["alerts_resolved_by_this_encounter"] = _unique_preserving(
            [str(alert.get("title") or "") for alert in linked if str(alert.get("title") or "")]
        )
        current["alert_count"] = len(linked)
        current["guideline_basis"] = _unique_preserving(list(current.get("guideline_basis") or []))
        current["decision_domains_covered"] = _unique_preserving(
            list(current.get("decision_domains_covered") or current.get("decision_domains") or [])
        )
        enriched.append(current)
    return enriched


def build_master_followup_plan(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    agenda_board: dict[str, Any],
    signals: dict[str, Any] | None = None,
    copilot_alerts: list[dict[str, Any]] | None = None,
    next_best_action: dict[str, Any] | None = None,
    plan_key: str = "",
    calendar_horizon_months: int = DEFAULT_CALENDAR_HORIZON_MONTHS,
) -> dict[str, Any]:
    signals = signals or {}
    copilot_alerts = [dict(alert) for alert in (copilot_alerts or []) if isinstance(alert, dict)]
    protocol = dict(agenda_board.get("stage_protocol") or {})
    protocol_trace = dict(agenda_board.get("protocol_trace") or {})
    comparators = list(agenda_board.get("protocol_comparators") or [])
    active_items = [dict(item) for item in (agenda_board.get("active_items") or agenda_board.get("items") or [])]
    overdue_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") == "overdue"]
    due_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") in {"due", "due_today"}]
    optional_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") in {"scheduled", "blocked"}]
    rule = _scenario_rule(state, management_track)

    blocking_alerts = [
        _summarize_alert(alert)
        for alert in copilot_alerts
        if str(alert.get("category") or "") in {"decision_blocker", "safety", "protocol_due"}
    ][:6]
    guideline_basis = _unique_preserving(
        list(rule.get("guideline_basis") or [])
        + list(protocol.get("evidence_basis") or [])
    )
    comparator_basis = _unique_preserving(
        [str(item.get("title") or item.get("label") or "") for item in comparators if str(item.get("title") or item.get("label") or "")]
    )
    prognostic_modifiers = [dict(item) for item in list(signals.get("prognostic_modifiers") or []) if isinstance(item, dict)]
    backbone_alignment = dict(signals.get("backbone_alignment") or {})
    cadence_adjusted_by = [str(item) for item in list(signals.get("cadence_adjusted_by") or []) if str(item or "").strip()]
    palliative_bundle = dict(signals.get("palliative_transition_bundle") or {})
    survivorship_bundle = dict(signals.get("survivorship_transition_bundle") or {})
    decision_evidence_currentness_bundle = dict(signals.get("decision_evidence_currentness_bundle") or {})
    therapeutic_readiness_bundle = dict(signals.get("therapeutic_readiness_bundle") or {})
    advanced_followup_bundle = dict(signals.get("advanced_followup_bundle") or {})
    staging_adjudication_bundle = dict(signals.get("staging_adjudication_bundle") or {})
    supportive_care_toxicity_readiness_bundle = dict(
        signals.get("supportive_care_toxicity_readiness_bundle") or {}
    )
    therapeutic_capture_actions = [dict(item) for item in list(therapeutic_readiness_bundle.get("capture_actions") or []) if isinstance(item, dict)]
    advanced_capture_actions = [
        dict(item)
        for item in list(advanced_followup_bundle.get("capture_actions") or [])
        if isinstance(item, dict)
    ]
    adjudication_capture_actions = [
        dict(item)
        for item in list(staging_adjudication_bundle.get("capture_actions") or [])
        if isinstance(item, dict)
    ]
    prognostic_rationale = [
        {
            "title": str(item.get("title") or item.get("modifier_key") or "Impacto pronóstico"),
            "severity": str(item.get("severity") or "info"),
            "why_it_matters_now": str(item.get("why_it_matters_now") or ""),
            "followup_impact": list(item.get("followup_impact") or []),
            "recommended_actions": list(item.get("recommended_actions") or []),
        }
        for item in prognostic_modifiers[:4]
    ]
    anchor = ScheduleAnchorAssessment(
        anchor_date=str(protocol_trace.get("anchor_date") or ""),
        anchor_source=str(protocol_trace.get("anchor_source") or ""),
        strength="weak" if protocol_trace.get("anchor_is_fallback") else "strong",
        is_fallback=bool(protocol_trace.get("anchor_is_fallback")),
        rationale="Anclaje derivado del mejor origen longitudinal disponible.",
    ).to_dict()
    anchor_dt = _parse_iso_date(anchor.get("anchor_date")) or date.today()
    resolved_plan_key = plan_key or f"{state}:{management_track}:{anchor.get('anchor_date') or anchor_dt.isoformat()}"
    linked_encounters = []
    for encounter in link_alerts_to_encounters(list(agenda_board.get("encounters") or []), copilot_alerts):
        current = dict(encounter)
        current["plan_key"] = str(current.get("plan_key") or resolved_plan_key)
        current["ideal_due_at"] = str(current.get("ideal_due_at") or current.get("due_at") or "")
        current["scheduled_due_at"] = str(current.get("scheduled_due_at") or current.get("due_at") or "")
        current["delay_days"] = int(current.get("delay_days") or 0)
        linked_encounters.append(current)
    linked_encounters.sort(key=_timeline_sort_key)
    timeline = [encounter for encounter in linked_encounters if _within_horizon(encounter, anchor_dt, calendar_horizon_months)]
    actionable_timeline = [
        encounter
        for encounter in timeline
        if str(encounter.get("status") or "scheduled") not in {"completed", "cancelled", "superseded"}
    ]
    next_encounter = dict(
        next(
            (encounter for encounter in actionable_timeline if str(encounter.get("visit_modality") or "") != "async"),
            actionable_timeline[0] if actionable_timeline else {},
        )
    )
    highlight_actions = _unique_preserving(
        list((next_best_action or {}).get("immediate_actions") or [])
        + [str(action) for item in prognostic_modifiers for action in list(item.get("recommended_actions") or [])]
        + [str(alert.get("recommended_action") or "") for alert in blocking_alerts]
        + [str(item.get("recommended_action") or item.get("title") or "") for item in list(signals.get("pending_adjudications") or [])]
        + [str(task.get("title") or "") for task in list((next_encounter or {}).get("tasks") or [])[:3]]
        + [str(item) for item in list(survivorship_bundle.get("recommended_interventions") or [])[:3]]
        + [f"Referencia: {item}" for item in list(survivorship_bundle.get("recommended_referrals") or [])[:3]]
        + [str(item) for item in list(palliative_bundle.get("recommended_interventions") or [])[:3]]
        + [str(item) for item in list(decision_evidence_currentness_bundle.get("refresh_actions") or [])[:2]]
        + [str(item) for item in list(staging_adjudication_bundle.get("recommended_adjudication_actions") or [])[:2]]
        + [str((therapeutic_readiness_bundle.get("next_best_action_if_not_ready") or {}).get("title") or "")]
        + [str(item) for item in list(supportive_care_toxicity_readiness_bundle.get("required_support_actions") or [])[:3]]
        + [str(item.get("display_label") or item.get("title") or "") for item in therapeutic_capture_actions[:3]]
        + [str(item.get("display_label") or item.get("title") or "") for item in advanced_capture_actions[:2]]
        + [str(item.get("display_label") or item.get("title") or "") for item in adjudication_capture_actions[:2]]
    )[:8]
    gaps_to_close = _unique_preserving(
        normalize_field_list(list(signals.get("critical_missing") or []))
        + [
            f"{item.get('title')}: {', '.join(item.get('display_fields_summary') or item.get('visible_fields') or item.get('fields', []) or item.get('raw_fields', []) or [])}"
            for item in list(signals.get("prognostic_capture_targets") or [])
            if list(item.get("display_fields_summary") or item.get("visible_fields") or item.get("fields") or item.get("raw_fields") or [])
        ]
        + [str(item.get("title") or "") for item in list(signals.get("pending_adjudications") or [])]
        + [
            f"{alert.get('title')}: {', '.join(alert.get('display_fields_to_capture') or alert.get('fields_to_capture') or [])}"
            for alert in blocking_alerts
            if list(alert.get("display_fields_to_capture") or alert.get("fields_to_capture") or [])
        ]
        + normalize_field_list(list(survivorship_bundle.get("missing_inputs") or []))
        + [f"Dato vencido de survivorship: {item}" for item in normalize_field_list(list(survivorship_bundle.get("stale_inputs") or []))]
        + [f"Evidencia decisional vencida: {item}" for item in normalize_field_list(list(decision_evidence_currentness_bundle.get("stale_evidence_fields") or []))]
        + [f"Evidencia decisional por revisar: {item}" for item in normalize_field_list(list(decision_evidence_currentness_bundle.get("aging_evidence_fields") or []))]
        + [f"Brecha de trazabilidad: {item}" for item in normalize_field_list(list(decision_evidence_currentness_bundle.get("traceability_gaps") or []))]
        + [f"Discordancia clínica: {item}" for item in normalize_field_list(list(staging_adjudication_bundle.get("discordant_fields") or []))]
        + [f"Evidencia superseded: {item}" for item in normalize_field_list(list(staging_adjudication_bundle.get("superseded_evidence") or []))]
        + [f"Soporte requerido: {item}" for item in normalize_field_list(list(supportive_care_toxicity_readiness_bundle.get("missing_support_inputs") or []))]
        + [f"Soporte por actualizar: {item}" for item in normalize_field_list(list(supportive_care_toxicity_readiness_bundle.get("stale_support_inputs") or []))]
        + list(therapeutic_readiness_bundle.get("display_required_to_release") or [])
        + list(therapeutic_readiness_bundle.get("display_safety_blockers") or [])
        + list(advanced_followup_bundle.get("display_missing_inputs") or [])
        + list(staging_adjudication_bundle.get("display_missing_critical_inputs") or [])
    )[:8]
    survivorship_track = str(survivorship_bundle.get("survivorship_track_label") or survivorship_bundle.get("survivorship_track") or "")
    palliative_mode = str(palliative_bundle.get("care_mode_label") or palliative_bundle.get("care_mode") or "")
    # EPIC 9 Group F (GAP-15 / OOS-11+OOS-12) — Si el bundle terapéutico llega vacío
    # pero los bundles adyacentes (staging adjudication, advanced followup, supportive
    # care) indican que la decisión está bloqueada por datos faltantes, derivamos el
    # status para que `summary.therapeutic_readiness_status` y
    # `summary.adjudication_gate_status` no queden en blanco. Es una lectura defensiva:
    # no altera bundles no vacíos ni cambia las aserciones downstream cuando el bundle
    # ya trae valores.
    readiness_status, monitoring_gate_status, adjudication_gate_status = (
        _compute_readiness_fallback_status(
            state=state,
            therapeutic_readiness_bundle=therapeutic_readiness_bundle,
            staging_adjudication_bundle=staging_adjudication_bundle,
            advanced_followup_bundle=advanced_followup_bundle,
            supportive_care_bundle=supportive_care_toxicity_readiness_bundle,
            signals=signals,
        )
    )
    supportive_readiness_status = str(
        supportive_care_toxicity_readiness_bundle.get("supportive_readiness_status") or ""
    )
    candidate_label = str(
        therapeutic_readiness_bundle.get("candidate_regimen_label")
        or therapeutic_readiness_bundle.get("candidate_family_label")
        or ""
    )
    summary_headline = str(protocol.get("title") or "Plan maestro de seguimiento")
    cadence_summary = str(protocol.get("cadence_summary") or "")
    if readiness_status in {"blocked_by_missing_data", "conditional_pending_closure"} and candidate_label:
        if monitoring_gate_status in {"blocked_by_missing_data", "conditional_pending_closure"} or adjudication_gate_status in {"blocked_by_missing_data", "conditional_pending_closure"}:
            summary_headline = f"{summary_headline} · liberación terapéutica condicionada"
            cadence_bits = [cadence_summary] if cadence_summary else []
            if monitoring_gate_status in {"blocked_by_missing_data", "conditional_pending_closure"}:
                cadence_bits.append("No conviene sostener estabilidad clínica solo por PSA mientras falten testosterona, vigilancia longitudinal o soporte avanzado.")
            if adjudication_gate_status in {"blocked_by_missing_data", "conditional_pending_closure"}:
                cadence_bits.append("La adjudicación de imagen/biomarcadores sigue pesando sobre la liberación terapéutica final.")
            cadence_summary = " ".join(bit for bit in cadence_bits if bit).strip()
    summary = {
        "headline": summary_headline,
        "cadence_summary": cadence_summary,
        "overdue_count": len(overdue_items),
        "due_now_count": len(due_items),
        "optional_count": len(optional_items),
        "blocking_alert_count": len(blocking_alerts),
        "pending_adjudication_count": len(list(signals.get("pending_adjudications") or [])),
        "next_encounter_title": str(next_encounter.get("title") or "Sin encounter priorizado"),
        "next_encounter_due_at": str(next_encounter.get("due_at") or ""),
        "anchor_strength": anchor.get("strength", "strong"),
        "timeline_count": len(timeline),
        "plan_status": "provisional" if anchor.get("is_fallback") else "active",
        "current_course_status": str(signals.get("current_course_status") or ""),
        "last_adjudicated_event": str((signals.get("last_adjudicated_event") or {}).get("summary") or ""),
        "prognostic_modifier_count": len(prognostic_modifiers),
        "cadence_adjusted_count": len(cadence_adjusted_by),
        "survivorship_track": survivorship_track,
        "palliative_care_mode": palliative_mode,
        "therapeutic_readiness_status": readiness_status,
        "therapeutic_candidate_label": candidate_label,
        "advanced_followup_confidence_status": str(
            advanced_followup_bundle.get("confidence_status") or ""
        ),
        "selected_decision_evidence_status": str(
            decision_evidence_currentness_bundle.get("selected_decision_evidence_status") or ""
        ),
        "selected_decision_release_status": str(
            decision_evidence_currentness_bundle.get("selected_decision_release_status") or ""
        ),
        "decision_refresh_action_count": len(
            list(decision_evidence_currentness_bundle.get("refresh_actions") or [])
        ),
        "staging_adjudication_status": str(
            staging_adjudication_bundle.get("concordance_status") or ""
        ),
        "adjudication_release_status": str(
            staging_adjudication_bundle.get("adjudication_release_status") or ""
        ),
        "supportive_readiness_status": supportive_readiness_status,
        "supportive_priority": str(
            supportive_care_toxicity_readiness_bundle.get("supportive_priority") or ""
        ),
        "monitoring_gate_status": monitoring_gate_status,
        "adjudication_gate_status": adjudication_gate_status,
    }
    merged_capture_actions = _unique_preserving(
        therapeutic_capture_actions[:4] + advanced_capture_actions[:2] + adjudication_capture_actions[:2]
    )
    return MasterFollowupPlan(
        plan_version=PLAN_VERSION,
        plan_key=resolved_plan_key,
        scenario_state=state,
        management_track=management_track,
        title=str(protocol.get("title") or "Plan maestro de seguimiento protocolizado"),
        phase_label=str(rule.get("phase_label") or ""),
        plan_status="provisional" if anchor.get("is_fallback") else "active",
        calendar_horizon_months=calendar_horizon_months,
        guideline_basis=guideline_basis,
        comparator_basis=comparator_basis,
        anchor=anchor,
        scenario_rule=rule,
        next_encounter=next_encounter,
        timeline=timeline,
        encounter_timeline=timeline,
        blocking_alerts=blocking_alerts,
        overdue_items=overdue_items[:6],
        due_items=due_items[:6],
        optional_items=optional_items[:6],
        highlight_actions=highlight_actions,
        gaps_to_close=gaps_to_close,
        capture_actions=merged_capture_actions[:6],
        prognostic_rationale=prognostic_rationale,
        cadence_adjusted_by=cadence_adjusted_by,
        backbone_alignment=backbone_alignment,
        summary=summary,
        inline_actions_enabled=any(bool(encounter.get("inline_actions_enabled")) for encounter in timeline),
    ).to_dict()
