from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.advanced_followup_builder import (
    build_capture_actions_for_fields,
)
from prostanet.domains.patient_tracking.capture_surface import display_capture_field_summary
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_runtime_payload,
    is_present,
)


_PRECISION_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
    "post_radiotherapy_or_local_salvage",
}
_PRECISION_FAMILIES = {"parp_family", "psma_rlt_family", "salvage_rt_family", "local_mdt_family"}
_YES_VALUES = {"1", "true", "yes", "si", "sí", "positive", "positivo"}


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


def _supports_systemic_pattern(payload: dict[str, Any]) -> bool:
    conventional = _normalize_text(payload.get("conventional_imaging_status")).upper()
    psma_stage = _normalize_text(payload.get("psma_stage_after_psma")).upper()
    metastatic_known = _normalize_text(payload.get("metastatic_stage_resolved")).upper()
    return any(
        value.startswith("M1")
        for value in (conventional, psma_stage, metastatic_known)
        if value
    )


def build_staging_adjudication_bundle(
    *,
    patient_record: dict[str, Any],
    state: str,
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    therapeutic_readiness_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient_record = dict(patient_record or {})
    longitudinal_bundle = dict(longitudinal_bundle or {})
    therapeutic_readiness_bundle = dict(
        therapeutic_readiness_bundle
        or longitudinal_bundle.get("therapeutic_readiness_bundle")
        or patient_record.get("therapeutic_readiness_bundle")
        or {}
    )
    merged_signals = dict(signals or longitudinal_bundle.get("signals") or patient_record.get("latest_signal_snapshot") or {})
    payload = build_runtime_payload(
        patient_record,
        latest_assessment or patient_record.get("latest_assessment"),
        effective_state=state,
    )

    candidate_family = _normalize_text(
        therapeutic_readiness_bundle.get("candidate_family")
        or (merged_signals.get("next_best_action") or {}).get("recommendation_family")
    )
    metastatic_detection_basis = _normalize_text(
        merged_signals.get("metastatic_detection_basis")
        or payload.get("metastatic_detection_basis")
        or "unknown"
    )
    psma_only_upstaging = bool(
        merged_signals.get("psma_only_upstaging")
        or metastatic_detection_basis == "psma_only"
    )
    restaging_update_required = bool(
        merged_signals.get("restaging_update_required")
        or payload.get("restaging_update_required")
    )
    available = state in _PRECISION_STATES or candidate_family in _PRECISION_FAMILIES or psma_only_upstaging

    if not available:
        return {
            "available": False,
            "metastatic_detection_basis": metastatic_detection_basis or "unknown",
            "psma_only_upstaging": psma_only_upstaging,
            "restaging_update_required": restaging_update_required,
            "required_traceable_fields": [],
            "missing_critical_inputs": [],
            "capture_actions": [],
            "traceability_checklist": [],
        }

    requires_salvage_traceability = state == "post_radiotherapy_or_local_salvage" or candidate_family in {
        "salvage_rt_family",
        "local_mdt_family",
    }
    requires_parp_traceability = state == "m1_crpc" or candidate_family == "parp_family"
    requires_psma_traceability = psma_only_upstaging or state in {"m0_crpc", "m1_crpc"} or candidate_family == "psma_rlt_family"
    systemic_pattern_supersedes_salvage = requires_salvage_traceability and _supports_systemic_pattern(payload)
    current_line_context_changed = requires_parp_traceability and bool(
        is_present(payload.get("molecular_assay_date"))
        and str(payload.get("line_of_therapy_number") or "").strip() not in {"", "0", "1"}
    )

    required_traceable_fields = _dedupe(
        []
        + (
            ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"]
            if requires_salvage_traceability
            else []
        )
        + (
            ["hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"]
            if requires_parp_traceability
            else []
        )
        + (
            ["conventional_imaging_status", "psma_positive", "psma_pet_done", "psma_negative_dominant_lesions"]
            if requires_psma_traceability
            else []
        )
    )

    missing_critical_inputs = _dedupe(
        []
        + (
            []
            if (_truthy(payload.get("psma_pet_done")) or is_present(payload.get("psma_imaging_date")))
            else (["psma_pet_done"] if "psma_pet_done" in required_traceable_fields else [])
        )
        + (
            []
            if (_truthy(payload.get("mpmri_done")) or is_present(payload.get("mpmri_date")))
            else (["mpmri_done"] if "mpmri_done" in required_traceable_fields else [])
        )
        + (
            []
            if _truthy(payload.get("biopsy_proven_local_recurrence"))
            else (
                ["biopsy_proven_local_recurrence"]
                if "biopsy_proven_local_recurrence" in required_traceable_fields
                else []
            )
        )
        + (
            []
            if all(is_present(payload.get(field)) for field in ("hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"))
            else [field for field in ("hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date") if field in required_traceable_fields and not is_present(payload.get(field))]
        )
        + (
            []
            if (
                is_present(payload.get("conventional_imaging_status"))
                and (_truthy(payload.get("psma_positive")) or not requires_psma_traceability)
            )
            else [
                field
                for field in ("conventional_imaging_status", "psma_positive")
                if field in required_traceable_fields and not is_present(payload.get(field))
            ]
        )
    )

    discordance_reason_category = ""
    discordant_fields: list[str] = []
    context_change_triggers: list[str] = []
    superseded_evidence: list[str] = []
    recommended_adjudication_actions: list[str] = []
    current_context_basis = _dedupe(
        [
            f"Base metastásica: {metastatic_detection_basis}" if metastatic_detection_basis not in {"", "unknown"} else "",
            f"Línea terapéutica actual: {payload.get('line_of_therapy_number')}" if is_present(payload.get("line_of_therapy_number")) else "",
            f"Patrón de progresión: {payload.get('progression_pattern')}" if is_present(payload.get("progression_pattern")) else "",
            f"Imagen convencional: {payload.get('conventional_imaging_status')}" if is_present(payload.get("conventional_imaging_status")) else "",
            f"PSMA posterior: {payload.get('psma_stage_after_psma')}" if is_present(payload.get("psma_stage_after_psma")) else "",
        ]
    )

    concordance_status = "concordant"
    adjudication_release_status = "ready"

    if missing_critical_inputs:
        concordance_status = "insufficient_concordance"
        adjudication_release_status = "blocked_pending_adjudication"
        discordance_reason_category = "missing_critical_traceability"
        discordant_fields = list(missing_critical_inputs)
        recommended_adjudication_actions.append(
            "Completar trazabilidad estructurada de imagen, salvage o biomarcadores antes de liberar la decisión clínica."
        )
    elif _truthy(payload.get("psma_negative_dominant_lesions")):
        concordance_status = "discordant"
        adjudication_release_status = "blocked_pending_adjudication"
        discordance_reason_category = "psma_biology_discordance"
        discordant_fields = _dedupe(
            [
                "psma_negative_dominant_lesions",
                "psma_positive",
                "conventional_imaging_status",
            ]
        )
        recommended_adjudication_actions.extend(
            [
                "Correlacionar PSMA con imagen convencional y documentar si existe discordancia biológica dominante.",
                "Definir si la ruta terapéutica debe sostenerse, redirigirse o requerir tumor board.",
            ]
        )
    elif psma_only_upstaging:
        concordance_status = "context_changed"
        adjudication_release_status = "review_needed"
        discordance_reason_category = "psma_only_upstaging"
        context_change_triggers.append("psma_only_upstaging")
        superseded_evidence.extend(
            [
                "conventional_imaging_status",
                "metastatic_detection_basis",
            ]
        )
        recommended_adjudication_actions.extend(
            [
                "Reconciliar el upstaging por PSMA con la imagen convencional más reciente.",
                "Reconfirmar el estado efectivo antes de sostener la misma secuencia terapéutica.",
            ]
        )
    elif systemic_pattern_supersedes_salvage:
        concordance_status = "context_changed"
        adjudication_release_status = "blocked_pending_adjudication"
        discordance_reason_category = "systemic_pattern_supersedes_local_salvage"
        context_change_triggers.append("systemic_pattern_supersedes_local_salvage")
        superseded_evidence.extend(
            [
                "salvage_local_feasible",
                "biopsy_proven_local_recurrence",
            ]
        )
        recommended_adjudication_actions.extend(
            [
                "Revisar si el patrón sistémico nuevo desplaza salvage local o MDT como eje principal.",
                "Redefinir el contexto clínico vigente antes de sostener una ruta local en abstracto.",
            ]
        )
    elif current_line_context_changed:
        concordance_status = "context_changed"
        adjudication_release_status = "review_needed"
        discordance_reason_category = "molecular_profile_precedes_current_line"
        context_change_triggers.append("molecular_profile_precedes_current_line")
        superseded_evidence.extend(["molecular_assay_date"])
        recommended_adjudication_actions.extend(
            [
                "Revalidar si el perfil molecular sigue siendo clínicamente representativo para la línea terapéutica actual.",
                "Documentar si el biomarcador histórico sigue liberando la misma ruta de precisión hoy.",
            ]
        )
    elif restaging_update_required:
        concordance_status = "context_changed"
        adjudication_release_status = "review_needed"
        discordance_reason_category = "restaging_update_required"
        context_change_triggers.append("restaging_update_required")
        superseded_evidence.extend(
            [
                "conventional_imaging_status",
                "psma_pet_done",
            ]
        )
        recommended_adjudication_actions.append(
            "Actualizar reestadificación y volver a adjudicar el contexto clínico antes de sostener la misma decisión."
        )

    discordant_fields = _dedupe(discordant_fields)
    context_change_triggers = _dedupe(context_change_triggers)
    superseded_evidence = _dedupe(superseded_evidence)
    recommended_adjudication_actions = _dedupe(recommended_adjudication_actions)

    traceability_checklist = [
        {
            "key": "metastatic_detection_basis",
            "label": "Base de detección metastásica",
            "status": "complete" if metastatic_detection_basis not in {"", "unknown"} else "missing",
            "detail": metastatic_detection_basis or "Sin base adjudicada todavía.",
        },
        {
            "key": "salvage_restaging",
            "label": "Tríada de salvage post-RT",
            "status": "complete" if not requires_salvage_traceability or not any(field in missing_critical_inputs for field in ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"]) else "missing",
            "detail": "PSMA, mpMRI y biopsia local documentadas."
            if not any(field in missing_critical_inputs for field in ["psma_pet_done", "mpmri_done", "biopsy_proven_local_recurrence"])
            else "Falta cerrar PSMA, mpMRI o biopsia antes de liberar salvage.",
        },
        {
            "key": "molecular_traceability",
            "label": "Trazabilidad molecular",
            "status": "complete" if not requires_parp_traceability or not any(field in missing_critical_inputs for field in ["hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"]) else "missing",
            "detail": "Fuente molecular y HRR trazables."
            if not any(field in missing_critical_inputs for field in ["hrr_status", "hrr_gene", "biomarker_source", "molecular_assay_date"])
            else "Falta documentar HRR/fuente molecular con fecha.",
        },
        {
            "key": "functional_imaging_traceability",
            "label": "Imagen funcional / PSMA",
            "status": "complete" if not requires_psma_traceability or not any(field in missing_critical_inputs for field in ["conventional_imaging_status", "psma_positive", "psma_pet_done", "psma_negative_dominant_lesions"]) else "missing",
            "detail": "PSMA y correlación con imagen convencional documentadas."
            if not any(field in missing_critical_inputs for field in ["conventional_imaging_status", "psma_positive", "psma_pet_done", "psma_negative_dominant_lesions"])
            else "Falta correlación entre imagen convencional y PSMA.",
        },
    ]

    capture_actions = build_capture_actions_for_fields(
        missing_critical_inputs,
        decision_input_requirements,
        default_title="Completar adjudicación de estadio y trazabilidad",
        default_summary="Cerrar restadificación, concordancia de imagen y trazabilidad molecular antes de liberar la ruta terapéutica final.",
        default_focus="staging_adjudication",
        display_group="Adjudicación de estadio",
        display_impact="Si se completa hoy, aclara el estado efectivo y evita liberar terapias de precisión o salvage con trazabilidad incompleta.",
    )

    summary = "La adjudicación de estadio y trazabilidad están cerradas para la ruta actual."
    if concordance_status == "discordant":
        summary = "La evidencia actual es discordante y requiere adjudicación clínica antes de sostener la misma ruta."
    elif concordance_status == "context_changed":
        summary = "El contexto clínico vigente cambió frente a la evidencia previa y la decisión debe readjudicarse."
    elif concordance_status == "insufficient_concordance":
        summary = "Aún falta adjudicación estructurada de imagen o biomarcadores antes de cerrar la ruta terapéutica."

    return {
        "available": True,
        "metastatic_detection_basis": metastatic_detection_basis or "unknown",
        "psma_only_upstaging": psma_only_upstaging,
        "restaging_update_required": restaging_update_required,
        "concordance_status": concordance_status,
        "adjudication_release_status": adjudication_release_status,
        "discordance_reason_category": discordance_reason_category,
        "discordant_fields": discordant_fields,
        "display_discordant_fields": display_capture_field_summary(discordant_fields, limit=24),
        "context_change_triggers": context_change_triggers,
        "superseded_evidence": superseded_evidence,
        "display_superseded_evidence": display_capture_field_summary(superseded_evidence, limit=24),
        "recommended_adjudication_actions": recommended_adjudication_actions,
        "current_context_basis": current_context_basis,
        "required_traceable_fields": required_traceable_fields,
        "display_required_traceable_fields": display_capture_field_summary(required_traceable_fields, limit=24),
        "missing_critical_inputs": missing_critical_inputs,
        "display_missing_critical_inputs": display_capture_field_summary(missing_critical_inputs, limit=24),
        "traceability_checklist": traceability_checklist,
        "capture_actions": capture_actions,
        "summary": summary,
    }
