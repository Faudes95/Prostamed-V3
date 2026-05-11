from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.capture_surface import (
    display_capture_field_summary,
    enrich_capture_block,
)
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_runtime_payload,
    is_present,
)


ADVANCED_FOLLOWUP_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
    "survivorship_and_toxicity_followup",
    "post_radiotherapy_followup",
    "post_radiotherapy_or_local_salvage",
}

_YES_VALUES = {"1", "true", "yes", "si", "sí", "done", "realizado", "realizada"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _normalize_text(value).lower() in _YES_VALUES


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _status_label(is_complete: bool, is_due: bool = False) -> str:
    if is_complete:
        return "complete"
    return "due" if is_due else "missing"


def _capture_blocks(decision_input_requirements: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    blocks: list[tuple[str, dict[str, Any]]] = []
    for key, value in dict(decision_input_requirements or {}).items():
        if not key.endswith("capture_block") or not isinstance(value, dict):
            continue
        block = enrich_capture_block(value, limit=24)
        if not block.get("fields"):
            continue
        blocks.append((key, block))
    return blocks


def build_capture_actions_for_fields(
    required_fields: list[str] | tuple[str, ...] | None,
    decision_input_requirements: dict[str, Any] | None,
    *,
    default_title: str,
    default_summary: str,
    default_focus: str,
    display_group: str,
    display_impact: str,
) -> list[dict[str, Any]]:
    required_set = {str(field) for field in list(required_fields or []) if _normalize_text(field)}
    if not required_set:
        return []

    actions: list[dict[str, Any]] = []
    for key, block in _capture_blocks(decision_input_requirements or {}):
        raw_fields = [str(field) for field in list(block.get("fields") or []) if _normalize_text(field)]
        relevant = [field for field in raw_fields if field in required_set]
        if not relevant:
            continue
        actions.append(
            {
                "key": key,
                "title": str(block.get("title") or default_title),
                "display_label": str(block.get("title") or default_title),
                "summary": str(block.get("summary") or default_summary),
                "raw_fields": raw_fields,
                "fields": raw_fields,
                "display_fields_summary": list(
                    block.get("display_fields_summary")
                    or display_capture_field_summary(raw_fields, limit=24)
                ),
                "capture_target": str(block.get("capture_target") or "followup"),
                "focus": str(block.get("focus") or default_focus),
                "decision_affected": str(block.get("focus") or default_focus),
                "display_group": display_group,
                "display_cta": "Completar captura dirigida",
                "display_why_now": str(block.get("summary") or default_summary),
                "display_impact": display_impact,
                "form_scope": {
                    "mode": "capture_block",
                    "focus": str(block.get("focus") or default_focus),
                    "capture_fields": raw_fields,
                },
                "agenda_id": block.get("agenda_id"),
                "agenda_key": block.get("agenda_key"),
            }
        )

    if actions:
        return actions

    fallback_fields = list(required_set)
    return [
        {
            "key": f"{default_focus}_fallback",
            "title": default_title,
            "display_label": default_title,
            "summary": default_summary,
            "raw_fields": fallback_fields,
            "fields": fallback_fields,
            "display_fields_summary": display_capture_field_summary(fallback_fields, limit=24),
            "capture_target": "followup",
            "focus": default_focus,
            "decision_affected": default_focus,
            "display_group": display_group,
            "display_cta": "Completar captura dirigida",
            "display_why_now": default_summary,
            "display_impact": display_impact,
            "form_scope": {
                "mode": "capture_block",
                "focus": default_focus,
                "capture_fields": fallback_fields,
            },
            "agenda_id": None,
            "agenda_key": "",
        }
    ]


def _restaging_timeline(payload: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = []
    for key, label in (
        ("conventional_imaging_date", "Imagen convencional"),
        ("psma_imaging_date", "PSMA-PET"),
        ("mpmri_date", "mpMRI"),
        ("biopsy_date", "Biopsia"),
        ("molecular_assay_date", "Biomarcador molecular"),
    ):
        date_value = _normalize_text(payload.get(key))
        if not date_value:
            continue
        timeline.append(
            {
                "label": label,
                "date": date_value,
                "status": "complete",
                "value": _normalize_text(payload.get(key.replace("_date", ""))),
            }
        )
    return timeline


def build_advanced_followup_bundle(
    *,
    patient_record: dict[str, Any],
    state: str,
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    longitudinal_bundle = dict(longitudinal_bundle or {})
    merged_signals = dict(signals or longitudinal_bundle.get("signals") or patient_record.get("latest_signal_snapshot") or {})
    payload = build_runtime_payload(
        patient_record,
        latest_assessment or patient_record.get("latest_assessment"),
        effective_state=state,
    )

    prior_adt = _truthy(payload.get("prior_adt")) or bool(_normalize_text(payload.get("current_adt_context")))
    available = state in ADVANCED_FOLLOWUP_STATES or prior_adt
    if not available:
        return {
            "available": False,
            "state": state,
            "summary": "",
            "missing_inputs": [],
            "display_missing_inputs": [],
            "capture_actions": [],
            "monitoring_checklist": [],
            "testosterone_timeline": [],
            "restaging_timeline": [],
        }

    testosterone_timeline = list(payload.get("testosterone_history") or [])
    restaging_timeline = _restaging_timeline(payload)
    restaging_update_required = bool(
        merged_signals.get("restaging_update_required")
        or payload.get("restaging_update_required")
    )

    testosterone_complete = bool(testosterone_timeline) or is_present(payload.get("testosterone"))
    bone_health_complete = _truthy(payload.get("dxa_baseline_done")) and _truthy(
        payload.get("calcium_vitd_started")
    )
    bone_protection_complete = _truthy(payload.get("bone_protection_started"))
    metabolic_complete = any(
        is_present(payload.get(field))
        for field in ("hba1c", "glucose_or_hba1c", "total_cholesterol", "hdl_cholesterol", "triglycerides")
    )
    renal_complete = is_present(payload.get("creatinine"))
    marrow_complete = is_present(payload.get("hemoglobin"))
    frailty_complete = is_present(payload.get("mini_cog_score")) or is_present(payload.get("g8_score"))
    restaging_complete = bool(
        _normalize_text(payload.get("conventional_imaging_status"))
        or _truthy(payload.get("psma_pet_done"))
        or restaging_timeline
    )

    monitoring_checklist = [
        {
            "key": "testosterone",
            "label": "Testosterona longitudinal",
            "status": _status_label(testosterone_complete, state in ADVANCED_FOLLOWUP_STATES),
            "detail": "Serie longitudinal disponible." if testosterone_complete else "Falta confirmar testosterona o serie longitudinal.",
        },
        {
            "key": "restaging",
            "label": "Imagen / reestadificación",
            "status": _status_label(restaging_complete, restaging_update_required),
            "detail": "Reestadificación documentada." if restaging_complete else "Falta documentar imagen convencional o funcional.",
        },
        {
            "key": "bone_support",
            "label": "Soporte óseo",
            "status": _status_label(bone_health_complete and bone_protection_complete, prior_adt),
            "detail": "DXA, calcio/vitamina D y protección ósea documentados."
            if bone_health_complete and bone_protection_complete
            else "Completar DXA, calcio/vitamina D y protección ósea en ADT prolongada.",
        },
        {
            "key": "metabolic",
            "label": "Cardiometabólico",
            "status": _status_label(metabolic_complete and renal_complete, prior_adt),
            "detail": "HbA1c/lípidos y creatinina visibles."
            if metabolic_complete and renal_complete
            else "Falta bundle cardiometabólico / renal para seguimiento avanzado.",
        },
        {
            "key": "fitness",
            "label": "Fragilidad / cognición",
            "status": _status_label(frailty_complete, state in ADVANCED_FOLLOWUP_STATES),
            "detail": "Mini-Cog o G8 documentados."
            if frailty_complete
            else "Completar Mini-Cog o G8 antes de sostener intensificación.",
        },
        {
            "key": "marrow",
            "label": "Reserva hematológica",
            "status": _status_label(marrow_complete, state in {"m1_crpc", "mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"}),
            "detail": "Hemoglobina documentada."
            if marrow_complete
            else "Falta hemoglobina para seguimiento sistémico o soporte.",
        },
    ]

    missing_inputs = _dedupe(
        []
        + ([] if testosterone_complete else ["testosterone", "testosterone_history"])
        + ([] if restaging_complete else ["conventional_imaging_status", "psma_pet_done"])
        + ([] if bone_health_complete else ["dxa_baseline_done", "calcium_vitd_started"])
        + ([] if bone_protection_complete else ["bone_protection_started"])
        + ([] if metabolic_complete else ["hba1c", "total_cholesterol"])
        + ([] if not prior_adt or renal_complete else ["creatinine"])
        + ([] if frailty_complete else ["mini_cog_score", "g8_score"])
        + ([] if marrow_complete else ["hemoglobin"])
    )
    capture_actions = build_capture_actions_for_fields(
        missing_inputs,
        decision_input_requirements,
        default_title="Completar seguimiento longitudinal avanzado",
        default_summary="Cerrar biomarcadores, imagen, soporte óseo y vigilancia cardiometabólica antes de sostener la ruta clínica.",
        default_focus="advanced_followup",
        display_group="Seguimiento avanzado",
        display_impact="Si se completa hoy, mejora la confianza clínica del seguimiento y la liberación terapéutica visible.",
    )
    return {
        "available": True,
        "state": state,
        "summary": (
            "El seguimiento avanzado ya integra testosterona, restadificación, salud ósea, vigilancia cardiometabólica y fragilidad."
            if not missing_inputs
            else "Aún faltan piezas del seguimiento avanzado; no conviene sostener estabilidad clínica solo con PSA."
        ),
        "confidence_status": "supported" if not missing_inputs else "degraded_by_missing_data",
        "missing_inputs": missing_inputs,
        "display_missing_inputs": display_capture_field_summary(missing_inputs, limit=24),
        "capture_actions": capture_actions,
        "monitoring_checklist": monitoring_checklist,
        "testosterone_timeline": testosterone_timeline,
        "restaging_timeline": restaging_timeline,
        "restaging_update_required": restaging_update_required,
    }
