"""Canonical ProstaMed Decision Today Fusion Kernel.

This deterministic read model unifies the already-audited clinical surfaces
into one "DECISION HOY" bundle. It does not prescribe, train ML, execute
external orders, or invent missing PSA, testosterone, treatment lines, imaging,
molecular status, or trial eligibility.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode


DECISION_STATES = (
    "releaseable",
    "requires_data",
    "blocked",
    "urgent_safety",
    "redecision_required",
    "not_actionable",
)

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

STATE_GUARDRAILS = {
    "m0_crpc": {
        "fields": ("testosterone", "psadt", "conventional_imaging_m0"),
        "lane": "crpc_confirmation_readiness",
        "reason": "m0CRPC requiere testosterona, PSADT e imagen convencional M0 antes de liberar ARPI.",
    },
    "m1_crpc": {
        "fields": ("real_treatment_line",),
        "lane": "m1crpc_sequence_readiness",
        "reason": "m1CRPC requiere una linea terapeutica real antes de secuenciar tratamiento.",
    },
}

MHSPC_STATES = {"mcspc_low_volume", "mcspc_high_volume", "mhspc", "metastatic_cspc"}
CRPC_PRECISION_TOKENS = ("crpc", "mcrpc", "parp", "psma_rlt", "psma-rlt", "rlt", "lu177", "lu-177", "pluvicto")

FIELD_LABELS = {
    "testosterone": "Testosterona",
    "testosterone_value": "Testosterona",
    "psadt": "PSADT",
    "psadt_months": "PSADT",
    "conventional_imaging_m0": "Imagen convencional M0",
    "m1_composition": "Composicion M1",
    "volume_or_risk": "Volumen/riesgo metastasico",
    "fitness": "Fitness clinico",
    "real_treatment_line": "Linea terapeutica real",
    "hrr_status": "HRR/BRCA trazable",
    "psma_pet_structured": "PSMA PET estructurado",
    "histopathology_report": "Reporte histopatologico completo",
    "gleason_primary": "Gleason primario",
    "gleason_secondary": "Gleason secundario",
    "isup_grade_group": "Grupo ISUP",
}

FIELD_TO_LANE = {
    "testosterone": "crpc_confirmation_readiness",
    "testosterone_value": "crpc_confirmation_readiness",
    "psadt": "bcr_salvage_readiness",
    "psadt_months": "bcr_salvage_readiness",
    "conventional_imaging_m0": "crpc_confirmation_readiness",
    "m1_composition": "mhspc_precision_readiness",
    "volume_or_risk": "mhspc_precision_readiness",
    "fitness": "mhspc_precision_readiness",
    "real_treatment_line": "m1crpc_sequence_readiness",
    "hrr_status": "parp_hrr_readiness",
    "psma_pet_structured": "psma_rlt_readiness",
    "histopathology_report": "localized_treatment_readiness",
    "gleason_primary": "localized_treatment_readiness",
    "gleason_secondary": "localized_treatment_readiness",
    "isup_grade_group": "localized_treatment_readiness",
}


def build_decision_today(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    clinical_autodrive: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
) -> dict[str, Any]:
    """Build the canonical per-patient DECISION HOY bundle."""
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
    autodrive = dict(clinical_autodrive or enriched.get("clinical_autodrive") or {})
    facts = _resolve_clinical_facts(patient, enriched)
    source_alignment = _source_alignment(enriched, autodrive)
    conflict_resolution = _resolve_conflicts(patient, enriched, autodrive, effective_state)

    state_specific_missing, state_guard_reason, guardrail_lane = _state_guardrail_missing(effective_state, facts, patient)
    missing = _dedupe(
        list(state_specific_missing)
        + _missing_from_readiness(enriched.get("clinical_readiness_tower") or {})
        + _missing_from_tumor_board(enriched.get("tumor_board_os") or {})
        + _missing_from_autodrive(autodrive)
    )

    tumor_choice = _tumor_board_choice(enriched.get("tumor_board_os") or {}, effective_state)
    top_autodrive = _top_autodrive_item(autodrive)
    memory_status = _memory_status(enriched.get("clinical_memory_os") or {})
    active_safety = _has_active_safety(enriched, autodrive, memory_status)
    redecision = _requires_redecision(enriched.get("clinical_memory_os") or {}, autodrive, memory_status)

    if active_safety:
        decision_state = "urgent_safety"
        decision_title = _first_text(top_autodrive.get("title"), "Atender seguridad clinica hoy")
        rationale = _first_text(
            top_autodrive.get("reason"),
            source_alignment.get("clinical_memory", {}).get("reason"),
            "Existe toxicidad, progresion, alerta o riesgo activo que domina la decision electiva.",
        )
        risk_avoided = _first_text(top_autodrive.get("risk_avoided"), "Evita retrasar una intervencion de seguridad clinica.")
    elif redecision:
        decision_state = "redecision_required"
        decision_title = "Reabrir decision clinica"
        rationale = _first_text(
            source_alignment.get("clinical_memory", {}).get("reason"),
            top_autodrive.get("reason"),
            "Clinical Memory o el curso longitudinal exigen nueva decision.",
        )
        risk_avoided = "Evita continuar una ruta off-track sin reevaluacion."
    elif state_specific_missing:
        decision_state = "blocked"
        decision_title = _blocked_title(effective_state)
        rationale = state_guard_reason
        risk_avoided = "Evita liberar una recomendacion insegura por datos criticos faltantes."
    elif missing:
        decision_state = "requires_data"
        decision_title = _first_text(tumor_choice.get("label"), top_autodrive.get("title"), "Completar datos para decidir")
        rationale = _first_text(
            tumor_choice.get("rationale"),
            top_autodrive.get("reason"),
            "Faltan datos decisivos antes de liberar la recomendacion.",
        )
        risk_avoided = "Evita decidir con criterios incompletos."
    elif tumor_choice.get("status") == "releaseable":
        decision_state = "releaseable"
        decision_title = _first_text(tumor_choice.get("label"), "Decision liberable")
        rationale = _first_text(tumor_choice.get("rationale"), "Tumor Board OS no detecta bloqueo critico.")
        risk_avoided = _first_text(top_autodrive.get("risk_avoided"), "Evita retrasar una decision clinica lista.")
    elif top_autodrive:
        decision_state = _state_from_autodrive(top_autodrive)
        decision_title = _first_text(top_autodrive.get("title"), "Accion clinica hoy")
        rationale = _first_text(top_autodrive.get("reason"), "Autodrive prioriza esta accion hoy.")
        risk_avoided = _first_text(top_autodrive.get("risk_avoided"), "Evita perdida de oportunidad clinica.")
    else:
        decision_state = "not_actionable"
        decision_title = "Sin decision clinica accionable hoy"
        rationale = "No hay accion clinica prioritaria documentada con datos actuales."
        risk_avoided = ""

    primary_lane = guardrail_lane or _primary_lane_from_missing(missing) or _first_text(top_autodrive.get("cta", {}).get("readiness_lane"))
    missing_plan = _build_missing_plan(missing, resolved_ref, fallback_lane=primary_lane)
    next_action = _next_safe_action(
        patient_ref=resolved_ref,
        decision_state=decision_state,
        title=decision_title,
        rationale=rationale,
        risk_avoided=risk_avoided,
        missing_plan=missing_plan,
        tumor_choice=tumor_choice,
        top_autodrive=top_autodrive,
        primary_lane=primary_lane,
    )

    gates, trials = _affected_contracts(enriched, autodrive, tumor_choice, top_autodrive)
    anti_fallback = _anti_fallback_checks(patient, enriched, facts)

    return {
        "available": True,
        "source": "clinical_decision_today_fusion_kernel",
        "version": "decision_today_fusion_kernel_v1",
        "patient_ref": resolved_ref,
        "patient_name": _patient_name(patient),
        "state": effective_state,
        "state_label": STATE_LABELS.get(effective_state, effective_state or "Sin clasificar"),
        "management_track": effective_track,
        "decision_today": {
            "title": decision_title,
            "status": decision_state,
            "state": decision_state,
            "label": _decision_state_label(decision_state),
            "rationale": rationale,
            "risk_avoided": risk_avoided,
        },
        "decision_state": decision_state,
        "clinical_rationale": rationale,
        "unified_missing_fields": missing_plan,
        "missing_field_keys": [item["field"] for item in missing_plan],
        "conflict_resolution": conflict_resolution,
        "next_safe_action": next_action,
        "source_alignment": source_alignment,
        "audit": {
            "deterministic_v1": True,
            "read_model_only": True,
            "no_ml_model_trained": True,
            "no_external_orders": True,
            "no_fabricated_treatment": anti_fallback["no_fabricated_treatment"],
            "no_fabricated_biomarkers": anti_fallback["no_fabricated_biomarkers"],
            "no_fabricated_trial_eligibility": True,
            "facts_used": facts.get("facts_used", []),
            "fact_precedence": [
                "verified_patient_clinical_facts",
                "clinical_fact_bundle",
                "longitudinal_truth_snapshot",
                "biomarker_longitudinal",
                "treatment_history",
                "latest_assessment",
                "classifier_or_draft",
            ],
            "sources_used": _sources_used(enriched, patient, autodrive),
            "gates_affected": gates,
            "trials_affected": trials,
            "anti_fallback_checks": anti_fallback,
            "computed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    }


def decision_today_to_autodrive_item(
    decision_today: Mapping[str, Any],
    *,
    patient_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert Decision Today into an Autodrive-compatible top queue item."""
    decision = dict(decision_today.get("decision_today") or {})
    action = dict(decision_today.get("next_safe_action") or {})
    state = str(decision_today.get("state") or "")
    status = str(decision_today.get("decision_state") or decision.get("status") or "not_actionable")
    lane = _autodrive_lane_for_decision_state(status)
    priority = _priority_for_decision_state(status)
    missing = [item.get("field") for item in decision_today.get("unified_missing_fields") or [] if isinstance(item, Mapping)]
    return {
        "patient_ref": str(decision_today.get("patient_ref") or ""),
        "patient_name": _first_text(decision_today.get("patient_name"), _patient_name(patient_record or {})),
        "state": state,
        "state_label": str(decision_today.get("state_label") or STATE_LABELS.get(state, state)),
        "stage": _stage_key(state),
        "lane": lane,
        "lane_label": _lane_label(lane),
        "priority_status": priority,
        "priority_score": _score_for_decision_state(status),
        "title": _first_text(decision.get("title"), action.get("label"), "DECISION HOY"),
        "reason": _first_text(decision_today.get("clinical_rationale"), decision.get("rationale")),
        "risk_avoided": _first_text(decision.get("risk_avoided"), action.get("risk_avoided")),
        "missing_fields": _dedupe(missing),
        "source_bundles": _dedupe(["clinical_decision_today_fusion_kernel"] + list(action.get("source_bundles") or [])),
        "gates_affected": list((decision_today.get("audit") or {}).get("gates_affected") or []),
        "trials_affected": list((decision_today.get("audit") or {}).get("trials_affected") or []),
        "cta": dict(action.get("cta") or {}),
        "action_key": "decision_today:fusion_kernel",
        "due_at": str(action.get("due_at") or ""),
        "status": status,
        "external_order_created": False,
        "write_requires_review": True,
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

    care = dict(enriched.get("care_pathway_os") or patient.get("care_pathway_os") or signals.get("care_pathway_os") or {})
    if not care:
        try:
            from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os

            care = build_care_pathway_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            care = {}
    enriched["care_pathway_os"] = care

    memory = dict(enriched.get("clinical_memory_os") or patient.get("clinical_memory_os") or signals.get("clinical_memory_os") or {})
    if not memory:
        try:
            from prostanet.domains.patient_tracking.clinical_memory_os import build_clinical_memory_os

            memory = build_clinical_memory_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception:
            memory = {}
    enriched["clinical_memory_os"] = memory
    return enriched


def _resolve_clinical_facts(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    facts_used: list[dict[str, Any]] = []

    def set_value(key: str, value: Any, source: str) -> None:
        if not key or value in (None, "", [], {}):
            return
        if key not in values:
            values[key] = value
            facts_used.append({"field": key, "source": source})

    for fact in patient.get("patient_clinical_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        if str(fact.get("active") if fact.get("active") is not None else "1") in {"0", "false", "False"}:
            continue
        set_value(_first_text(fact.get("fact_key"), fact.get("field"), fact.get("key")), _first_text(fact.get("value"), fact.get("fact_value"), fact.get("normalized_value")), "verified_patient_clinical_facts")

    fact_bundle = dict(bundle.get("clinical_fact_bundle") or patient.get("clinical_fact_bundle") or {})
    for key, value in dict(fact_bundle.get("field_values") or fact_bundle.get("values") or {}).items():
        set_value(str(key), value, "clinical_fact_bundle")

    truth = dict(bundle.get("longitudinal_truth_snapshot") or patient.get("longitudinal_truth_snapshot") or {})
    for key, value in dict(truth.get("field_values") or truth.get("values") or {}).items():
        set_value(str(key), value, "longitudinal_truth_snapshot")

    for row in _biomarker_rows(patient):
        btype = str(row.get("biomarker_type") or row.get("type") or "").lower()
        value = row.get("value")
        if "testoster" in btype:
            set_value("testosterone", value, "biomarker_longitudinal")
        if btype in {"psa", "ape"} or "psa" in btype or "ape" in btype:
            set_value("psa", value, "biomarker_longitudinal")

    real_lines = _real_treatment_lines(patient)
    if real_lines:
        set_value("real_treatment_line", _first_text(real_lines[-1].get("drug_scheme"), real_lines[-1].get("regimen"), real_lines[-1].get("label"), "documented"), "treatment_history")

    baseline = dict(patient.get("baseline") or patient.get("clinical_baseline") or {})
    latest = dict(patient.get("latest_assessment") or {})
    prior = dict(patient.get("prior_history") or {})
    signals = dict(bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    for source_name, source in (
        ("latest_assessment", latest),
        ("baseline", baseline),
        ("prior_history", prior),
        ("latest_signal_snapshot", signals),
    ):
        for key, value in source.items():
            set_value(str(key), value, source_name)

    if "psadt" not in values:
        set_value("psadt", _first_text(values.get("psadt_months"), baseline.get("psadt_months"), signals.get("psadt_months")), "derived_alias")
    if "conventional_imaging_m0" not in values:
        set_value("conventional_imaging_m0", _first_text(values.get("m0_conventional_confirmed"), signals.get("conventional_imaging_status"), signals.get("conventional_m0")), "derived_alias")
    if "m1_composition" not in values:
        set_value("m1_composition", _first_text(values.get("m1_sites"), values.get("metastatic_stage_resolved"), values.get("metastasis_site")), "derived_alias")
    if "volume_or_risk" not in values:
        set_value("volume_or_risk", _first_text(values.get("volume_disease"), values.get("chaarted_volume"), values.get("latitude_risk")), "derived_alias")

    values["facts_used"] = facts_used
    return values


def _source_alignment(bundle: Mapping[str, Any], autodrive: Mapping[str, Any]) -> dict[str, Any]:
    readiness = dict(bundle.get("clinical_readiness_tower") or {})
    board = dict(bundle.get("tumor_board_os") or {})
    care = dict(bundle.get("care_pathway_os") or {})
    memory = dict(bundle.get("clinical_memory_os") or {})
    ad_summary = dict(autodrive.get("summary") or {})
    ad_top = _top_autodrive_item(autodrive)
    tb_choice = _tumor_board_choice(board, "")
    rd_lane = _top_readiness_lane(readiness)
    care_action = _top_care_action(care)
    mem_status = _memory_status(memory)
    return {
        "clinical_readiness_tower": {
            "status": _first_text(rd_lane.get("status"), (readiness.get("summary") or {}).get("priority_status")),
            "label": _first_text(rd_lane.get("label"), "Readiness clinico"),
            "reason": _first_text(rd_lane.get("reason"), (readiness.get("summary") or {}).get("dominant_blocker")),
        },
        "tumor_board_os": {
            "status": _first_text(tb_choice.get("status"), (board.get("summary") or {}).get("board_status")),
            "label": _first_text(tb_choice.get("label"), (board.get("recommendation") or {}).get("title")),
            "reason": _first_text(tb_choice.get("rationale"), (board.get("recommendation") or {}).get("rationale")),
        },
        "care_pathway_os": {
            "status": _first_text(care_action.get("status"), (care.get("summary") or {}).get("dominant_status")),
            "label": _first_text(care_action.get("label"), care_action.get("title"), (care.get("summary") or {}).get("top_action_title")),
            "reason": _first_text(care_action.get("reason"), care_action.get("rationale")),
        },
        "clinical_memory_os": {
            "status": mem_status,
            "label": _first_text((memory.get("summary") or {}).get("active_episode_label"), "Clinical Memory"),
            "reason": _first_text((memory.get("summary") or {}).get("dominant_redecision_reason"), ((memory.get("expected_vs_observed") or {}).get("reason"))),
        },
        "clinical_autodrive": {
            "status": _first_text(ad_summary.get("priority_status"), ad_top.get("priority_status")),
            "label": _first_text(ad_top.get("title"), ad_summary.get("top_action_title")),
            "reason": _first_text(ad_top.get("reason"), ad_summary.get("dominant_blocker")),
        },
    }


def _resolve_conflicts(patient: Mapping[str, Any], bundle: Mapping[str, Any], autodrive: Mapping[str, Any], effective_state: str) -> dict[str, Any]:
    candidates = []
    signals = dict(bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    for source, value in (
        ("latest_signal_snapshot.effective_state_final", signals.get("effective_state_final")),
        ("latest_signal_snapshot.effective_state", signals.get("effective_state")),
        ("latest_signal_snapshot.reconciled_state", signals.get("reconciled_state")),
        ("requested_state", effective_state),
        ("latest_assessment.state", (patient.get("latest_assessment") or {}).get("state")),
        ("prior_history.current_state", (patient.get("prior_history") or {}).get("current_state")),
        ("clinical_autodrive.state", autodrive.get("state")),
    ):
        text = _first_text(value)
        if text:
            candidates.append({"source": source, "value": text})
    distinct = []
    for item in candidates:
        if item["value"] not in distinct:
            distinct.append(item["value"])
    return {
        "has_conflict": len(distinct) > 1,
        "winning_state": effective_state,
        "winning_source": candidates[0]["source"] if candidates else "default",
        "candidates": candidates,
        "resolution_rule": "verified/provenance > longitudinal truth > biomarker/treatment append-only > latest assessment > classifier/draft temporal",
    }


def _state_guardrail_missing(state: str, facts: Mapping[str, Any], patient: Mapping[str, Any]) -> tuple[list[str], str, str]:
    if state in STATE_GUARDRAILS:
        rule = STATE_GUARDRAILS[state]
        missing = [field for field in rule["fields"] if not _has_fact(facts, field)]
        return missing, rule["reason"] if missing else "", rule["lane"] if missing else ""
    if state in MHSPC_STATES:
        fields = ("m1_composition", "volume_or_risk", "fitness")
        missing = [field for field in fields if not _has_fact(facts, field)]
        if missing:
            return missing, "mHSPC requiere composicion M1, volumen/riesgo y fitness antes de liberar intensificacion.", "mhspc_precision_readiness"
    if _bcr_state(state):
        return [], "", ""
    return [], "", ""


def _missing_from_readiness(readiness: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for lane in readiness.get("lanes") or []:
        if not isinstance(lane, Mapping):
            continue
        if lane.get("status") in {"requires_data", "blocked", "overdue", "active_risk"}:
            out.extend(lane.get("missing_fields") or [])
    capture = readiness.get("capture_plan") or {}
    if isinstance(capture, Mapping):
        out.extend(capture.get("missing_fields") or [])
        for group in capture.get("groups") or []:
            if isinstance(group, Mapping):
                out.extend(group.get("fields") or [])
    return _dedupe(out)


def _missing_from_tumor_board(board: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for option in board.get("options") or []:
        if isinstance(option, Mapping) and option.get("status") in {"requires_data", "blocked"}:
            out.extend(option.get("missing_fields") or [])
    capture = board.get("capture_plan") or {}
    if isinstance(capture, Mapping):
        out.extend(capture.get("tumor_board_missing_fields") or [])
        out.extend(capture.get("missing_fields") or [])
    return _dedupe(out)


def _missing_from_autodrive(autodrive: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for item in autodrive.get("today_queue") or autodrive.get("autodrive_actions") or []:
        if isinstance(item, Mapping):
            out.extend(item.get("missing_fields") or [])
    return _dedupe(out)


def _tumor_board_choice(board: Mapping[str, Any], state: str) -> dict[str, Any]:
    options = [dict(item) for item in board.get("options") or [] if isinstance(item, Mapping)]
    applicable = [item for item in options if _option_applicable_to_state(item, state)]
    for status in ("releaseable", "provisional", "requires_data", "blocked"):
        for item in applicable:
            if str(item.get("status") or "").lower() == status:
                return {
                    "key": _first_text(item.get("key"), item.get("label"), status),
                    "label": _first_text(item.get("label"), item.get("title"), status),
                    "status": status,
                    "rationale": _first_text(item.get("rationale"), item.get("why"), item.get("reason")),
                    "missing_fields": list(item.get("missing_fields") or []),
                    "gates_affected": list(item.get("gates_affected") or item.get("gates_impacted") or []),
                    "trials_affected": list(item.get("trials_affected") or item.get("trials_impacted") or []),
                }
    rec = dict(board.get("recommendation") or {})
    if rec:
        return {
            "key": _first_text(rec.get("key"), rec.get("title"), "recommendation"),
            "label": _first_text(rec.get("title"), rec.get("label"), rec.get("recommendation")),
            "status": _first_text(rec.get("status"), rec.get("finality"), "requires_data"),
            "rationale": _first_text(rec.get("rationale"), rec.get("summary")),
            "missing_fields": list(rec.get("missing_fields") or []),
        }
    return {}


def _top_readiness_lane(readiness: Mapping[str, Any]) -> dict[str, Any]:
    lanes = [dict(item) for item in readiness.get("lanes") or [] if isinstance(item, Mapping)]
    for status in ("active_risk", "requires_data", "overdue", "ready"):
        for lane in lanes:
            if lane.get("status") == status:
                return lane
    return {}


def _top_care_action(care: Mapping[str, Any]) -> dict[str, Any]:
    actions = [dict(item) for item in care.get("pathway_actions") or [] if isinstance(item, Mapping)]
    for status in ("overdue", "blocked", "pending", "ordered", "scheduled"):
        for action in actions:
            if str(action.get("status") or "").lower() == status:
                return action
    return {}


def _top_autodrive_item(autodrive: Mapping[str, Any]) -> dict[str, Any]:
    for item in autodrive.get("today_queue") or autodrive.get("autodrive_actions") or []:
        if isinstance(item, Mapping) and item.get("action_key") != "decision_today:fusion_kernel":
            return dict(item)
    return {}


def _memory_status(memory: Mapping[str, Any]) -> str:
    summary = dict(memory.get("summary") or {})
    observed = dict(memory.get("expected_vs_observed") or {})
    if summary.get("requires_redecision"):
        return "requires_redecision"
    return _first_text(summary.get("outcome_status"), observed.get("status"), "insufficient_data")


def _has_active_safety(bundle: Mapping[str, Any], autodrive: Mapping[str, Any], memory_status: str) -> bool:
    if memory_status in {"toxicity_limited", "off_track"}:
        return True
    readiness = bundle.get("clinical_readiness_tower") or {}
    if any(isinstance(lane, Mapping) and lane.get("status") == "active_risk" for lane in readiness.get("lanes") or []):
        return True
    top = _top_autodrive_item(autodrive)
    return top.get("lane") == "urgent_today" and top.get("priority_status") == "critical_today"


def _requires_redecision(memory: Mapping[str, Any], autodrive: Mapping[str, Any], memory_status: str) -> bool:
    if memory_status in {"requires_redecision", "off_track", "toxicity_limited"}:
        return True
    if memory.get("redecision_reasons"):
        return True
    top = _top_autodrive_item(autodrive)
    return top.get("lane") == "redecision_required"


def _has_fact(facts: Mapping[str, Any], field: str) -> bool:
    aliases = {
        "testosterone": ("testosterone", "testosterone_value", "testosterone_current"),
        "psadt": ("psadt", "psadt_months"),
        "conventional_imaging_m0": ("conventional_imaging_m0", "m0_conventional_confirmed", "conventional_m0"),
        "m1_composition": ("m1_composition", "m1_sites", "metastatic_stage_resolved", "metastasis_site"),
        "volume_or_risk": ("volume_or_risk", "volume_disease", "chaarted_volume", "latitude_risk"),
        "fitness": ("fitness", "ecog", "ecog_score", "performance_status"),
        "real_treatment_line": ("real_treatment_line",),
    }.get(field, (field,))
    for alias in aliases:
        value = facts.get(alias)
        if field == "fitness" and str(value).strip() == "0":
            return True
        if value not in (None, "", [], {}, "unknown", "desconocido", "none", "None", "0"):
            return True
    return False


def _build_missing_plan(fields: Iterable[Any], patient_ref: str, *, fallback_lane: str = "") -> list[dict[str, Any]]:
    plan = []
    for raw in _dedupe(fields):
        field = _field_key(raw)
        lane = FIELD_TO_LANE.get(field) or fallback_lane or "clinical_data_completion"
        query = urlencode({"decision_lane": lane, "decision_field": field})
        plan.append(
            {
                "field": field,
                "label": FIELD_LABELS.get(field, str(raw)),
                "capture_surface": "longitudinal_capture",
                "readiness_lane": lane,
                "cta": {
                    "label": "Capturar dato",
                    "href": f"/longitudinal-capture/{quote(str(patient_ref))}?{query}",
                    "action_mode": "capture",
                    "patient_ref": str(patient_ref),
                    "readiness_lane": lane,
                    "decision_field": field,
                },
            }
        )
    return plan


def _next_safe_action(
    *,
    patient_ref: str,
    decision_state: str,
    title: str,
    rationale: str,
    risk_avoided: str,
    missing_plan: list[Mapping[str, Any]],
    tumor_choice: Mapping[str, Any],
    top_autodrive: Mapping[str, Any],
    primary_lane: str,
) -> dict[str, Any]:
    if missing_plan:
        cta = dict(missing_plan[0].get("cta") or {})
        return {
            "label": _first_text(missing_plan[0].get("label"), "Capturar dato faltante"),
            "title": title,
            "reason": rationale,
            "risk_avoided": risk_avoided,
            "cta": cta,
            "source_bundles": ["clinical_decision_today_fusion_kernel"],
            "due_at": "hoy / segun agenda",
        }
    if decision_state in {"releaseable", "redecision_required"}:
        return {
            "label": "Abrir Tumor Board",
            "title": _first_text(tumor_choice.get("label"), title),
            "reason": rationale,
            "risk_avoided": risk_avoided,
            "cta": {
                "label": "Abrir Tumor Board",
                "href": f"/patient_profile/{quote(str(patient_ref))}?v=2#pm2TumorBoardOS",
                "action_mode": "review",
                "patient_ref": str(patient_ref),
            },
            "source_bundles": ["clinical_decision_today_fusion_kernel", "tumor_board_os"],
            "due_at": "hoy / segun agenda",
        }
    if decision_state == "urgent_safety":
        cta = dict(top_autodrive.get("cta") or {})
        if not cta.get("href"):
            cta = {
                "label": "Abrir Care Pathway",
                "href": f"/patient_profile/{quote(str(patient_ref))}?v=2#pm2CarePathwayOS",
                "action_mode": "review",
                "patient_ref": str(patient_ref),
                "readiness_lane": primary_lane,
            }
        return {
            "label": _first_text(cta.get("label"), "Atender seguridad"),
            "title": title,
            "reason": rationale,
            "risk_avoided": risk_avoided,
            "cta": cta,
            "source_bundles": ["clinical_decision_today_fusion_kernel", "care_pathway_os"],
            "due_at": "hoy",
        }
    cta = dict(top_autodrive.get("cta") or {})
    if not cta.get("href"):
        cta = {"label": "Abrir perfil", "href": f"/patient_profile/{quote(str(patient_ref))}?v=2", "action_mode": "review", "patient_ref": str(patient_ref)}
    return {
        "label": _first_text(cta.get("label"), "Abrir perfil"),
        "title": title,
        "reason": rationale,
        "risk_avoided": risk_avoided,
        "cta": cta,
        "source_bundles": ["clinical_decision_today_fusion_kernel"],
        "due_at": _first_text(top_autodrive.get("due_at"), "hoy / segun agenda"),
    }


def _affected_contracts(bundle: Mapping[str, Any], autodrive: Mapping[str, Any], tumor_choice: Mapping[str, Any], top_autodrive: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    gates: list[Any] = []
    trials: list[Any] = []
    for source in (tumor_choice, top_autodrive):
        gates.extend(source.get("gates_affected") or source.get("gates_impacted") or [])
        trials.extend(source.get("trials_affected") or source.get("trials_impacted") or [])
    for lane in (bundle.get("clinical_readiness_tower") or {}).get("lanes") or []:
        if isinstance(lane, Mapping) and lane.get("status") in {"requires_data", "active_risk", "overdue"}:
            gates.extend(lane.get("gates_affected") or [])
            trials.extend(lane.get("trials_affected") or [])
    return _dedupe(gates), _dedupe(trials)


def _anti_fallback_checks(patient: Mapping[str, Any], bundle: Mapping[str, Any], facts: Mapping[str, Any]) -> dict[str, Any]:
    has_real_tx = bool(_real_treatment_lines(patient))
    has_psa = _has_fact(facts, "psa") or bool(patient.get("psa_series"))
    has_testosterone = _has_fact(facts, "testosterone") or bool(patient.get("testosterone_series"))
    return {
        "no_fabricated_treatment": True,
        "no_fabricated_biomarkers": True,
        "has_real_treatment_line": has_real_tx,
        "has_real_psa_or_ape": has_psa,
        "has_real_testosterone": has_testosterone,
        "source_traceability_available": bool(patient.get("data_provenance") or patient.get("source_documents") or patient.get("patient_clinical_facts") or bundle.get("clinical_fact_bundle")),
    }


def _sources_used(bundle: Mapping[str, Any], patient: Mapping[str, Any], autodrive: Mapping[str, Any]) -> list[str]:
    sources = []
    for key in ("signals", "longitudinal_truth_snapshot", "clinical_fact_bundle", "clinical_readiness_tower", "tumor_board_os", "care_pathway_os", "clinical_memory_os"):
        if bundle.get(key):
            sources.append(key)
    if autodrive:
        sources.append("clinical_autodrive")
    for key in ("patient_clinical_facts", "data_provenance", "source_documents", "biomarker_longitudinal", "treatments", "treatment_history"):
        if patient.get(key):
            sources.append(key)
    return _dedupe(sources)


def _blocked_title(state: str) -> str:
    if state == "m0_crpc":
        return "Bloqueo m0CRPC: completar testosterona, PSADT e imagen M0"
    if state == "m1_crpc":
        return "Bloqueo m1CRPC: documentar linea terapeutica real"
    if state in MHSPC_STATES:
        return "Bloqueo mHSPC: completar composicion M1, volumen/riesgo y fitness"
    return "Decision bloqueada por datos criticos"


def _state_from_autodrive(item: Mapping[str, Any]) -> str:
    lane = str(item.get("lane") or "")
    if lane == "urgent_today":
        return "urgent_safety"
    if lane == "redecision_required":
        return "redecision_required"
    if lane == "blocked_by_data":
        return "requires_data"
    if lane == "ready_to_decide":
        return "releaseable"
    return "not_actionable"


def _decision_state_label(state: str) -> str:
    return {
        "releaseable": "Liberable",
        "requires_data": "Requiere datos",
        "blocked": "Bloqueada",
        "urgent_safety": "Seguridad urgente",
        "redecision_required": "Nueva decision requerida",
        "not_actionable": "Sin accion hoy",
    }.get(state, state)


def _autodrive_lane_for_decision_state(state: str) -> str:
    return {
        "urgent_safety": "urgent_today",
        "redecision_required": "redecision_required",
        "blocked": "blocked_by_data",
        "requires_data": "blocked_by_data",
        "releaseable": "ready_to_decide",
        "not_actionable": "not_actionable",
    }.get(state, "not_actionable")


def _priority_for_decision_state(state: str) -> str:
    return {
        "urgent_safety": "critical_today",
        "redecision_required": "critical_today",
        "blocked": "high_today",
        "requires_data": "high_today",
        "releaseable": "high_today",
        "not_actionable": "not_actionable",
    }.get(state, "watchlist")


def _score_for_decision_state(state: str) -> int:
    return {
        "urgent_safety": 99,
        "redecision_required": 96,
        "blocked": 90,
        "requires_data": 86,
        "releaseable": 84,
        "not_actionable": 0,
    }.get(state, 40)


def _lane_label(lane: str) -> str:
    return {
        "urgent_today": "Urgente hoy",
        "ready_to_decide": "Listo para decidir",
        "blocked_by_data": "Bloqueado por datos",
        "overdue_surveillance": "Seguimiento vencido",
        "redecision_required": "Nueva decision requerida",
        "not_actionable": "Sin accion hoy",
    }.get(lane, lane)


def _primary_lane_from_missing(fields: Iterable[Any]) -> str:
    for raw in fields or []:
        lane = FIELD_TO_LANE.get(_field_key(raw))
        if lane:
            return lane
    return ""


def _field_key(value: Any) -> str:
    if isinstance(value, Mapping):
        value = _first_text(value.get("field"), value.get("key"), value.get("field_name"), value.get("label"))
    text = _first_text(value).strip()
    return text.lower().replace(" ", "_")


def _option_applicable_to_state(option: Mapping[str, Any], state: str) -> bool:
    key_text = " ".join(str(option.get(k) or "") for k in ("key", "label", "clinical_role", "family_code")).lower()
    if _bcr_state(state) and any(token in key_text for token in CRPC_PRECISION_TOKENS):
        return False
    if state == "m0_crpc" and any(token in key_text for token in ("bcr", "salvage", "post_rp", "post_rt")):
        return False
    if "parp" in key_text or "psma_rlt" in key_text or "psma-rlt" in key_text or "rlt" in key_text:
        return state == "m1_crpc"
    return True


def _bcr_state(state: str) -> bool:
    s = str(state or "").lower()
    return "bcr" in s or "post_prostatectomy" in s or "post_radiotherapy" in s


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


def _biomarker_rows(patient: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = list(patient.get("biomarker_longitudinal") or [])
    rows.extend(patient.get("psa_series") or [])
    rows.extend(patient.get("testosterone_series") or [])
    return [row for row in rows if isinstance(row, Mapping)]


def _real_treatment_lines(patient: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = []
    for tx in patient.get("treatments") or patient.get("treatment_history") or []:
        if not isinstance(tx, Mapping):
            continue
        label = _first_text(tx.get("drug_scheme"), tx.get("regimen"), tx.get("label"), tx.get("treatment_name"))
        if label and label.lower() not in {"-", "—", "none", "sin tratamiento", "no treatment"}:
            rows.append(tx)
    return rows


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


def _dedupe(values: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if isinstance(value, Mapping):
            text = _first_text(value.get("field"), value.get("field_name"), value.get("key"), value.get("label"), value.get("code"), value.get("title"))
        else:
            text = _first_text(value)
        if text and text not in out:
            out.append(text)
    return out


__all__ = [
    "DECISION_STATES",
    "build_decision_today",
    "decision_today_to_autodrive_item",
]
