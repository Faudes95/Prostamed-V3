from __future__ import annotations

from datetime import datetime
from typing import Any

from prostanet.domains.patient_tracking.master_followup_plan import SCENARIO_FOLLOWUP_MATRIX
from prostanet.shared.contracts import EncounterPlan, EncounterTask


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}

_STATUS_ORDER = {
    "overdue": 0,
    "due_today": 1,
    "due": 2,
    "blocked": 3,
    "scheduled": 4,
    "partially_satisfied": 5,
    "completed": 6,
    "cancelled": 7,
    "superseded": 8,
}

_PRIORITY_ORDER = {"high": 0, "routine": 1, "low": 2}


def required_task_types_for_state(state: str) -> set[str]:
    raw = SCENARIO_FOLLOWUP_MATRIX.get(state) or {}
    return {str(item) for item in list(raw.get("required_tasks") or []) if str(item or "")}


def is_required_task(task: dict[str, Any], state: str) -> bool:
    required_types = required_task_types_for_state(state)
    if not required_types:
        return True
    return str(task.get("item_type") or "") in required_types


def action_mode_for_task(task: dict[str, Any]) -> str:
    required_inputs = [str(item) for item in list(task.get("required_inputs") or [])]
    completion_rule = dict(task.get("completion_rule") or {})
    if completion_rule.get("requires_document_type") or any(item.startswith("source_document:") for item in required_inputs):
        return "document"
    form_scope_mode = str((task.get("form_scope") or {}).get("mode") or "")
    if form_scope_mode in {"item_scoped", "capture_block", "inline_task"}:
        return "capture"
    if str(task.get("item_type") or "") in {"psa", "testosterone", "lab_panel", "pro_assessment", "toxicity_review", "therapy_review", "imaging", "biopsy", "supportive_care", "goals_of_care"}:
        return "capture"
    return "manual"


def _status_from_tasks(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "scheduled"
    return min((_task_status(task) for task in tasks), key=lambda item: _STATUS_ORDER.get(item, 99))


def _task_status(task: dict[str, Any]) -> str:
    status = str(task.get("status") or "scheduled")
    if status in {"cancelled", "superseded"}:
        return status
    if str(task.get("completed_at") or "")[:10]:
        return "completed"
    return status


def _encounter_status(tasks: list[dict[str, Any]], state: str) -> str:
    if not tasks:
        return "scheduled"
    relevant_tasks = [task for task in tasks if bool(task.get("required", True))] or tasks
    if relevant_tasks and all(_task_status(task) == "completed" for task in relevant_tasks):
        return "completed"
    return _status_from_tasks(relevant_tasks)


def _encounter_priority(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "routine"
    return min((str(task.get("priority") or "routine") for task in tasks), key=lambda item: _PRIORITY_ORDER.get(item, 99))


def _encounter_due(tasks: list[dict[str, Any]]) -> str:
    dates = [str(task.get("due_at") or "")[:10] for task in tasks if str(task.get("due_at") or "")[:10]]
    return min(dates) if dates else ""


def _encounter_ideal_due(tasks: list[dict[str, Any]]) -> str:
    dates = [str(task.get("ideal_due_at") or task.get("due_at") or "")[:10] for task in tasks if str(task.get("ideal_due_at") or task.get("due_at") or "")[:10]]
    return min(dates) if dates else ""


def _encounter_scheduled_due(tasks: list[dict[str, Any]]) -> str:
    dates = [str(task.get("scheduled_due_at") or task.get("due_at") or "")[:10] for task in tasks if str(task.get("scheduled_due_at") or task.get("due_at") or "")[:10]]
    return min(dates) if dates else ""


def _encounter_completed_at(tasks: list[dict[str, Any]]) -> str:
    dates = [str(task.get("completed_at") or "")[:10] for task in tasks if str(task.get("completed_at") or "")[:10]]
    return max(dates) if dates else ""


def _delay_days(ideal_due_at: str, scheduled_due_at: str) -> int:
    if not ideal_due_at or not scheduled_due_at:
        return 0
    try:
        ideal = datetime.strptime(ideal_due_at[:10], "%Y-%m-%d").date()
        scheduled = datetime.strptime(scheduled_due_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return max(0, (scheduled - ideal).days)


def _unique_preserving(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _guideline_basis(tasks: list[dict[str, Any]]) -> list[str]:
    return _unique_preserving(
        [
            str(entry)
            for task in tasks
            for entry in list(task.get("evidence_basis") or [])
            if str(entry or "")
        ]
    )


def _completion_progress(tasks: list[dict[str, Any]]) -> tuple[int, int, dict[str, Any]]:
    relevant = [task for task in tasks if bool(task.get("required", True))] or list(tasks)
    required_total = len(relevant)
    completed_required = sum(1 for task in relevant if _task_status(task) == "completed")
    ratio = (completed_required / required_total) if required_total else 0.0
    return required_total, completed_required, {
        "required_total": required_total,
        "completed_required": completed_required,
        "ratio": ratio,
        "label": f"{completed_required}/{required_total}" if required_total else "0/0",
    }


def _encounter_spec(item: dict[str, Any], state: str, management_track: str) -> dict[str, str]:
    item_type = str(item.get("item_type") or "")

    if item_type == "pathology_review":
        return {
            "encounter_type": "documentation",
            "title": "Carga documental clínica",
            "summary": "Documentos fuente verificables que desbloquean decisiones y trazabilidad clínica.",
            "visit_modality": "async",
        }

    if state == "adt_progression_verification":
        if item_type in {"therapy_review", "lab_panel", "imaging"}:
            return {
                "encounter_type": "progression_confirmation",
                "title": "Cita de confirmación de progresión bajo ADT",
                "summary": "Revisar testosterona, backbone ADT, línea terapéutica, reestadificación y contexto de progresión.",
                "visit_modality": "clinic",
            }
        return {
            "encounter_type": "progression_support",
            "title": "Cita de soporte y seguridad bajo ADT",
            "summary": "Completar soporte metabólico, salud ósea, calidad de vida y fragilidad durante la verificación de progresión.",
            "visit_modality": "clinic",
        }

    if state in DIAGNOSTIC_STATES:
        if item_type in {"imaging", "biopsy"}:
            return {
                "encounter_type": "diagnostic_workup",
                "title": "Estudio diagnóstico dirigido",
                "summary": "MRI/biopsia y confirmación anatomo-patológica para cerrar la ruta diagnóstica.",
                "visit_modality": "procedure",
            }
        return {
            "encounter_type": "diagnostic_followup",
            "title": "Cita diagnóstica de seguimiento",
            "summary": "Actualizar PSA, revisar señal de riesgo y decidir si escalar el estudio diagnóstico.",
            "visit_modality": "clinic",
        }

    if management_track == "active_surveillance":
        if item_type in {"imaging", "biopsy"}:
            return {
                "encounter_type": "surveillance_restage",
                "title": "Reevaluación de vigilancia activa",
                "summary": "MRI/biopsia confirmatoria para sostener o abandonar vigilancia activa.",
                "visit_modality": "procedure",
            }
        return {
            "encounter_type": "surveillance_visit",
            "title": "Cita de vigilancia activa",
            "summary": "PSA, PROs y revisión clínica para vigilancia activa segura.",
            "visit_modality": "clinic",
        }

    if state in LOCALIZED_STATES:
        return {
            "encounter_type": "localized_decision",
            "title": "Cita de decisión local",
            "summary": "Alinear riesgo, función y preferencias para definir estrategia local.",
            "visit_modality": "clinic",
        }

    if state in POSTLOCAL_STATES:
        if item_type == "imaging":
            return {
                "encounter_type": "salvage_restage",
                "title": "Reestadificación de rescate",
                "summary": "Imagen dirigida cuando cambia la factibilidad de rescate o intensificación.",
                "visit_modality": "imaging",
            }
        return {
            "encounter_type": "postlocal_followup",
            "title": "Cita post tratamiento local",
            "summary": "PSA ultrasensible y revisión clínica para control bioquímico y ventana de rescate.",
            "visit_modality": "clinic",
        }

    if item_type == "imaging":
        return {
            "encounter_type": "restaging",
            "title": "Reestadificación oncológica",
            "summary": "Imagen estructurada para carga tumoral, elegibilidad PSMA y cambio de conducta.",
            "visit_modality": "imaging",
        }

    return {
        "encounter_type": "systemic_followup",
        "title": "Visita sistémica avanzada",
        "summary": "Revisión terapéutica, laboratorio, toxicidad, soporte y fitness en la misma visita clínica.",
        "visit_modality": "clinic",
    }


def build_encounter_plans(
    items: list[dict[str, Any]],
    state: str,
    management_track: str,
    protocol_trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    protocol_trace = protocol_trace or {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    specs: dict[str, dict[str, str]] = {}

    for item in items or []:
        if str(item.get("status") or "") in {"superseded", "cancelled"}:
            continue
        spec = _encounter_spec(item, state, management_track)
        encounter_key = f"{state}:{management_track}:{spec['encounter_type']}"
        grouped.setdefault(encounter_key, []).append(item)
        specs[encounter_key] = spec

    plans: list[dict[str, Any]] = []
    anchor_strength = "weak" if protocol_trace.get("anchor_is_fallback") else "strong"
    for encounter_key, tasks in grouped.items():
        spec = specs[encounter_key]
        normalized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            current = dict(task)
            current["required"] = bool(task.get("required", is_required_task(task, state)))
            current["action_mode"] = str(task.get("action_mode") or action_mode_for_task(task))
            current["status"] = _task_status(current)
            current["expected_document_type"] = str(
                (task.get("completion_rule") or {}).get("requires_document_type")
                or next(
                    (
                        item.split(":", 1)[1]
                        for item in list(task.get("required_inputs") or [])
                        if str(item).startswith("source_document:")
                    ),
                    "",
                )
            )
            normalized_tasks.append(current)
        tasks = normalized_tasks
        task_models = [
            EncounterTask(
                agenda_id=int(task.get("id")) if task.get("id") not in (None, "") else None,
                agenda_key=str(task.get("agenda_key") or ""),
                title=str(task.get("title") or ""),
                item_type=str(task.get("item_type") or ""),
                status=str(task.get("status") or "scheduled"),
                due_at=str(task.get("scheduled_due_at") or task.get("due_at") or ""),
                ideal_due_at=str(task.get("ideal_due_at") or task.get("due_at") or ""),
                scheduled_due_at=str(task.get("scheduled_due_at") or task.get("due_at") or ""),
                completed_at=str(task.get("completed_at") or ""),
                delay_days=int(task.get("delay_days") or 0),
                action_label=str(task.get("action_label") or ""),
                required=bool(task.get("required", True)),
                action_mode=str(task.get("action_mode") or "capture"),
                expected_document_type=str(task.get("expected_document_type") or ""),
                decision_targets=list(task.get("decision_targets") or []),
            )
            for task in sorted(
                tasks,
                key=lambda current: (
                    str(current.get("ideal_due_at") or current.get("due_at") or ""),
                    str(current.get("scheduled_due_at") or current.get("due_at") or ""),
                    str(current.get("title") or ""),
                ),
            )
        ]
        ideal_due_at = _encounter_ideal_due(tasks)
        scheduled_due_at = _encounter_scheduled_due(tasks)
        plan_key = str(next((task.get("plan_key") for task in tasks if str(task.get("plan_key") or "")), "") or "")
        required_task_count, completed_required_task_count, completion_progress = _completion_progress(tasks)
        plans.append(
            EncounterPlan(
                encounter_key=encounter_key,
                encounter_type=spec["encounter_type"],
                state=state,
                management_track=management_track,
                title=spec["title"],
                summary=spec["summary"],
                due_at=scheduled_due_at or ideal_due_at or _encounter_due(tasks),
                ideal_due_at=ideal_due_at,
                scheduled_due_at=scheduled_due_at,
                completed_at=_encounter_completed_at(tasks),
                delay_days=_delay_days(ideal_due_at, scheduled_due_at),
                plan_key=plan_key,
                status=_encounter_status(tasks, state),
                priority=_encounter_priority(tasks),
                visit_modality=spec["visit_modality"],
                task_count=len(task_models),
                required_task_count=required_task_count,
                completed_required_task_count=completed_required_task_count,
                completion_progress=completion_progress,
                tasks=task_models,
                decision_domains=_unique_preserving(
                    [target for task in tasks for target in list(task.get("decision_targets") or [])]
                ),
                decision_domains_covered=_unique_preserving(
                    [target for task in tasks for target in list(task.get("decision_targets") or [])]
                ),
                guideline_basis=_guideline_basis(tasks),
                anchor_strength=anchor_strength,
                inline_actions_enabled=any(str(task.get("action_mode") or "manual") in {"capture", "document"} for task in tasks),
            ).to_dict()
        )

    plans.sort(
        key=lambda item: (
            str(item.get("ideal_due_at") or item.get("due_at") or ""),
            str(item.get("scheduled_due_at") or item.get("due_at") or ""),
            str(item.get("title") or ""),
        )
    )
    return plans
