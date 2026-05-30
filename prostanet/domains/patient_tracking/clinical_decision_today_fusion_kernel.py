"""Canonical ProstaMed Decision Today Fusion Kernel.

This deterministic read model unifies the already-audited clinical surfaces
into one "DECISION HOY" bundle. It does not prescribe, train ML, execute
external orders, or invent missing PSA, testosterone, treatment lines, imaging,
molecular status, or trial eligibility.
"""
from __future__ import annotations

import logging
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode

# EPIC 29.7 (GodiBot G57 HIGH) — module-level logger. Pre-EPIC29 the 4
# bare `except Exception` blocks silently downgraded sub-builders to {}
# without any log or audit trace. Now exceptions log + accumulate in
# `_upstream_failures` for audit visibility.
logger = logging.getLogger(__name__)


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
    "patient_values": "Valores y prioridades del paciente",
    "localized_patient_values": "Valores para decidir AS/RP/RT",
    "baseline_pro": "PRO basal minimo",
    "toxicity_tolerance": "Tolerancia/toxicidad aceptable",
    "decision_tradeoff": "Tradeoff de decision documentado",
    "redecision_threshold": "Umbral de nueva decision",
    "urinary_function_baseline": "Funcion urinaria basal",
    "sexual_function_baseline": "Funcion sexual basal",
    "bowel_function_baseline": "Funcion intestinal basal",
    "rp_rt_as_tradeoff_documented": "Tradeoff AS/RP/RT documentado",
    "psa": "PSA/APE",
    "psa_value": "PSA/APE real",
    "repeat_psa_value": "PSA repetido",
    "psa_density": "Densidad de PSA",
    "psad": "Densidad de PSA",
    "mri_pirads_score": "PI-RADS de mpMRI",
    "pirads_score": "PI-RADS",
    "prior_mpmri_pirads_score": "PI-RADS previo",
    "dre_suspicious": "Tacto rectal documentado",
    "dre": "Tacto rectal",
    "biopsy_status": "Estado de biopsia",
    "prior_negative_biopsy": "Biopsia negativa previa",
    "planned_biopsy_type": "Tipo de biopsia planeada",
    "planned_biopsy_route": "Via de biopsia planeada",
    "family_history": "Antecedente familiar",
    "family_history_positive": "Antecedente familiar positivo",
    "germline_risk": "Riesgo germinal",
    "germline_risk_mutation": "Mutación germinal",
    "phi_value": "PHI",
    "fourkscore_value": "4Kscore",
    "post_local_context": "Contexto post-local",
    "psa_doubling_time_months": "PSADT",
    "salvage_context_marker": "Criterio BCR/Phoenix",
    "bcr_detected": "BCR confirmada",
    "bcr_date": "Fecha de BCR",
    "bcr_psa": "PSA al BCR",
    "prior_prostatectomy": "Prostatectomía previa",
    "prior_radiation": "Radioterapia previa",
    "time_from_definitive_treatment_months": "Tiempo desde tratamiento local",
    "psa_nadir_post_rt": "PSA nadir post-RT",
    "psa_rise_above_nadir_ng_ml": "Ascenso PSA sobre nadir",
    "phoenix_criteria_met": "Criterio Phoenix",
    "surgical_margins_status": "Márgenes quirúrgicos",
    "pathological_t_stage": "pT patológico",
    "psma_pet_status": "PSMA PET",
    "psma_pet_staging_recent": "PSMA PET reciente",
}

FIELD_TO_LANE = {
    "testosterone": "crpc_confirmation_readiness",
    "testosterone_value": "crpc_confirmation_readiness",
    "psadt": "bcr_salvage_readiness",
    "psadt_months": "bcr_salvage_readiness",
    "psa_doubling_time_months": "bcr_salvage_readiness",
    "post_local_context": "bcr_salvage_readiness",
    "salvage_context_marker": "bcr_salvage_readiness",
    "bcr_detected": "bcr_salvage_readiness",
    "bcr_date": "bcr_salvage_readiness",
    "bcr_psa": "bcr_salvage_readiness",
    "prior_prostatectomy": "bcr_salvage_readiness",
    "prior_radiation": "bcr_salvage_readiness",
    "time_from_definitive_treatment_months": "bcr_salvage_readiness",
    "psa_nadir_post_rt": "bcr_salvage_readiness",
    "psa_rise_above_nadir_ng_ml": "bcr_salvage_readiness",
    "phoenix_criteria_met": "bcr_salvage_readiness",
    "surgical_margins_status": "bcr_salvage_readiness",
    "pathological_t_stage": "bcr_salvage_readiness",
    "psma_pet_status": "bcr_salvage_readiness",
    "psma_pet_staging_recent": "bcr_salvage_readiness",
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
    "patient_values": "patient_twin_readiness",
    "baseline_pro": "patient_twin_readiness",
    "toxicity_tolerance": "patient_twin_readiness",
    "decision_tradeoff": "patient_twin_readiness",
    "redecision_threshold": "patient_twin_readiness",
    "localized_patient_values": "localized_treatment_readiness",
    "urinary_function_baseline": "localized_treatment_readiness",
    "sexual_function_baseline": "localized_treatment_readiness",
    "bowel_function_baseline": "localized_treatment_readiness",
    "rp_rt_as_tradeoff_documented": "localized_treatment_readiness",
    "repeat_psa_value": "diagnostic_biopsy_readiness",
    "psa_density": "diagnostic_biopsy_readiness",
    "psad": "diagnostic_biopsy_readiness",
    "mri_pirads_score": "diagnostic_biopsy_readiness",
    "pirads_score": "diagnostic_biopsy_readiness",
    "prior_mpmri_pirads_score": "diagnostic_biopsy_readiness",
    "dre_suspicious": "diagnostic_biopsy_readiness",
    "dre": "diagnostic_biopsy_readiness",
    "biopsy_status": "diagnostic_biopsy_readiness",
    "prior_negative_biopsy": "diagnostic_biopsy_readiness",
    "planned_biopsy_type": "diagnostic_biopsy_readiness",
    "planned_biopsy_route": "diagnostic_biopsy_readiness",
    "family_history": "diagnostic_biopsy_readiness",
    "family_history_positive": "diagnostic_biopsy_readiness",
    "germline_risk": "diagnostic_biopsy_readiness",
    "germline_risk_mutation": "diagnostic_biopsy_readiness",
    "phi_value": "diagnostic_biopsy_readiness",
    "fourkscore_value": "diagnostic_biopsy_readiness",
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

    # BUG FIX 2026-05-17 — Clinical compass structured headline override.
    # El classifier oficial (clinical_compass.structured_decision_headline)
    # YA computa la decisión terapéutica correcta del estadio (ej.
    # "Priorizar ADT + enzalutamida" para mcspc_low_volume_sync_oligo).
    # Pre-fix, el fusion kernel ignoraba este headline y sobreescribía con
    # `top_autodrive.title` que terminaba siendo un refiner ("Biomarcadores
    # accionables"). Post-fix: si el compass tiene structured_decision_headline
    # válido (no genérico) Y no hay safety/redecision/state-block real,
    # úsalo como decision_title autoritativo.
    compass = enriched.get("clinical_compass") or patient.get("clinical_compass") or {}
    compass_headline = ""
    compass_rationale = ""
    if isinstance(compass, Mapping):
        compass_headline = str(compass.get("structured_decision_headline") or "").strip()
        compass_rationale = str(
            compass.get("why_this_now") or compass.get("primary_clinical_question") or ""
        ).strip() if compass else ""
        # If why_this_now is a list, flatten
        wtn = compass.get("why_this_now")
        if isinstance(wtn, (list, tuple)) and wtn:
            compass_rationale = " · ".join(str(x) for x in wtn if x)[:500]
    # Guardia: si el compass headline es genérico/vacío, no úsarlo
    GENERIC_HEADLINES = {"", "—", "sin recomendación", "sin recomendacion",
                          "sin decisión clínica activa", "sin decision clinica activa"}
    compass_override_valid = (
        compass_headline
        and compass_headline.lower() not in GENERIC_HEADLINES
        and len(compass_headline) > 10  # filtrar headlines triviales
    )

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
        # BUG FIX — compass headline preferido sobre "Reabrir decision clinica" genérico.
        # Si el classifier oficial tiene la decisión recomendada del estadio,
        # mostrarla con prefix "Reabrir: " para indicar que requiere reevaluación.
        if compass_override_valid:
            decision_title = f"Reabrir: {compass_headline}"
        else:
            decision_title = "Reabrir decision clinica"
        rationale = _first_text(
            compass_rationale if compass_override_valid else "",
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
        # BUG FIX — preferir clinical_compass.structured_decision_headline antes que
        # tumor_choice.label o top_autodrive.title (que podrían ser refiners).
        decision_title = _first_text(
            compass_headline if compass_override_valid else "",
            tumor_choice.get("label"),
            top_autodrive.get("title"),
            "Completar datos para decidir",
        )
        rationale = _first_text(
            compass_rationale if compass_override_valid else "",
            tumor_choice.get("rationale"),
            top_autodrive.get("reason"),
            "Faltan datos decisivos antes de liberar la recomendacion.",
        )
        risk_avoided = "Evita decidir con criterios incompletos."
    elif tumor_choice.get("status") == "releaseable":
        decision_state = "releaseable"
        # BUG FIX — compass headline también aplica a releaseable (es la decisión correcta del estadio)
        decision_title = _first_text(
            compass_headline if compass_override_valid else "",
            tumor_choice.get("label"),
            "Decision liberable",
        )
        rationale = _first_text(
            compass_rationale if compass_override_valid else "",
            tumor_choice.get("rationale"),
            "Tumor Board OS no detecta bloqueo critico.",
        )
        risk_avoided = _first_text(top_autodrive.get("risk_avoided"), "Evita retrasar una decision clinica lista.")
    elif top_autodrive:
        decision_state = _state_from_autodrive(top_autodrive)
        # BUG FIX — compass headline también aplica a actionable
        decision_title = _first_text(
            compass_headline if compass_override_valid else "",
            top_autodrive.get("title"),
            "Accion clinica hoy",
        )
        rationale = _first_text(
            compass_rationale if compass_override_valid else "",
            top_autodrive.get("reason"),
            "Autodrive prioriza esta accion hoy.",
        )
        risk_avoided = _first_text(top_autodrive.get("risk_avoided"), "Evita perdida de oportunidad clinica.")
    elif compass_override_valid:
        # BUG FIX — si NO hay autodrive items pero el compass tiene structured headline,
        # úsalo como fallback (mejor que "Sin decision clinica accionable hoy").
        decision_state = "actionable"
        decision_title = compass_headline
        rationale = compass_rationale or "Clinical compass tiene recomendación oficial del estadio."
        risk_avoided = ""
    else:
        decision_state = "not_actionable"
        decision_title = "Sin decision clinica accionable hoy"
        rationale = "No hay accion clinica prioritaria documentada con datos actuales."
        risk_avoided = ""

    primary_lane = guardrail_lane or _primary_lane_from_missing(missing) or _first_text(top_autodrive.get("cta", {}).get("readiness_lane"))
    missing_plan = _build_missing_plan(missing, resolved_ref, fallback_lane=primary_lane)
    ledger_quality = _build_ledger_quality_for_decision_today(patient)
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
        ledger_quality=ledger_quality,
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
        "ledger_quality": ledger_quality,
        "next_safe_action": next_action,
        "source_alignment": {
            **source_alignment,
            "clinical_fact_ledger": {
                "status": ledger_quality.get("status"),
                "label": ledger_quality.get("label"),
                "reason": ledger_quality.get("message"),
                "conflict_count": ledger_quality.get("conflict_count"),
                "critical_conflict_count": ledger_quality.get("critical_conflict_count"),
                "resolved_watch_count": ledger_quality.get("resolved_watch_count"),
            },
        },
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
            "ledger_quality": {
                "status": ledger_quality.get("status"),
                "conflict_count": ledger_quality.get("conflict_count"),
                "critical_conflict_count": ledger_quality.get("critical_conflict_count"),
                "resolved_watch_count": ledger_quality.get("resolved_watch_count"),
            },
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
    ledger_quality = dict(decision_today.get("ledger_quality") or {})
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
        "ledger_quality": ledger_quality,
        "cta": dict(action.get("cta") or {}),
        "action_key": "decision_today:fusion_kernel",
        "due_at": str(action.get("due_at") or ""),
        "status": status,
        "external_order_created": False,
        "write_requires_review": True,
    }


def _build_ledger_quality_for_decision_today(patient: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from prostanet.domains.clinical_fact_ledger import build_decision_today_ledger_quality

        return build_decision_today_ledger_quality(dict(patient or {}))
    except Exception as exc:
        return {
            "version": "clinical_fact_ledger_decision_quality_v1",
            "status": "unavailable",
            "severity": "unknown",
            "label": "Ledger no disponible para DECISION HOY",
            "message": str(exc)[:160],
            "conflict_count": 0,
            "critical_conflict_count": 0,
            "resolved_watch_count": 0,
            "decision_conditioned": False,
            "requires_reconciliation": False,
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }


def _ensure_source_bundles(patient: Mapping[str, Any], bundle: Mapping[str, Any], *, state: str, management_track: str, patient_ref: str) -> dict[str, Any]:
    enriched = dict(bundle or {})
    signals = dict(enriched.get("signals") or patient.get("latest_signal_snapshot") or {})
    enriched["signals"] = signals

    # BUG FIX 2026-05-17 — Preservar clinical_compass si viene en bundle o patient.
    # build_decision_today consume compass.structured_decision_headline para
    # override de decision_title genérico. Pre-fix, _ensure_source_bundles
    # ignoraba compass → fallback a "Biomarcadores accionables" / "Reabrir
    # decision clinica" en lugar de "Priorizar ADT + enzalutamida".
    compass = (enriched.get("clinical_compass")
               or patient.get("clinical_compass")
               or signals.get("clinical_compass"))
    if compass:
        enriched["clinical_compass"] = compass

    # EPIC 29.7 (GodiBot G57 HIGH) — instrument 4 sub-builder calls with
    # explicit exception logging + audit upstream_failures collection.
    upstream_failures: list[dict[str, str]] = []

    readiness = dict(enriched.get("clinical_readiness_tower") or patient.get("clinical_readiness_tower") or signals.get("clinical_readiness_tower") or {})
    if not readiness or not readiness.get("lanes"):
        try:
            from prostanet.domains.patient_tracking.clinical_readiness_tower import build_clinical_readiness_tower

            readiness = build_clinical_readiness_tower(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception as exc:
            logger.exception("fusion_kernel: clinical_readiness_tower build failed")
            upstream_failures.append({"builder": "clinical_readiness_tower", "error": f"{type(exc).__name__}: {exc}"})
            readiness = {}
    enriched["clinical_readiness_tower"] = readiness

    tumor_board = dict(enriched.get("tumor_board_os") or patient.get("tumor_board_os") or signals.get("tumor_board_os") or {})
    if not tumor_board:
        try:
            from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

            tumor_board = build_tumor_board_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception as exc:
            logger.exception("fusion_kernel: tumor_board_os build failed")
            upstream_failures.append({"builder": "tumor_board_os", "error": f"{type(exc).__name__}: {exc}"})
            tumor_board = {}
    enriched["tumor_board_os"] = tumor_board

    care = dict(enriched.get("care_pathway_os") or patient.get("care_pathway_os") or signals.get("care_pathway_os") or {})
    if not care:
        try:
            from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os

            care = build_care_pathway_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception as exc:
            logger.exception("fusion_kernel: care_pathway_os build failed")
            upstream_failures.append({"builder": "care_pathway_os", "error": f"{type(exc).__name__}: {exc}"})
            care = {}
    enriched["care_pathway_os"] = care

    memory = dict(enriched.get("clinical_memory_os") or patient.get("clinical_memory_os") or signals.get("clinical_memory_os") or {})
    if not memory:
        try:
            from prostanet.domains.patient_tracking.clinical_memory_os import build_clinical_memory_os

            memory = build_clinical_memory_os(patient, longitudinal_bundle=enriched, state=state, management_track=management_track, patient_ref=patient_ref)
        except Exception as exc:
            logger.exception("fusion_kernel: clinical_memory_os build failed")
            upstream_failures.append({"builder": "clinical_memory_os", "error": f"{type(exc).__name__}: {exc}"})
            memory = {}
    enriched["clinical_memory_os"] = memory

    # EPIC 29.7 — surface audit trail
    if upstream_failures:
        enriched.setdefault("audit", {})["upstream_failures"] = upstream_failures
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
    lane_count = 0
    for lane in readiness.get("lanes") or []:
        if not isinstance(lane, Mapping):
            continue
        lane_count += 1
        if lane.get("status") in {"requires_data", "blocked", "overdue", "active_risk"}:
            out.extend(lane.get("missing_fields") or [])
    if lane_count:
        return _dedupe(out)

    # Older readiness bundles may only expose a capture plan. Newer bundles
    # include optional refiners in capture_plan.groups, so those groups must not
    # become canonical Decision Today blockers.
    capture = readiness.get("capture_plan") or {}
    if isinstance(capture, Mapping):
        out.extend(capture.get("missing_fields") or [])
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


def _is_primary_therapy_item(item: Mapping[str, Any]) -> bool:
    """BUG FIX 2026-05-17 — Distingue THERAPY DECISIONS vs MOLECULAR REFINERS.

    Para que "DECISIÓN HOY" muestre la opción terapéutica primaria del estadio
    (e.g., "Doblete ADT+ARPI" para mCSPC bajo volumen, "Salvage RT" para BCR
    post-RP) y NO un refiner molecular (Biomarcadores accionables / PSMA gate /
    ARPI safety). Los refiners son requisitos pre-decisión, NO la decisión.

    Heurística (signal de orden bajo a alto):
      1. action_key empieza con 'tumor_board:' o 'therapy:' o 'recommendation:'
         o 'pathway:' o contiene 'doublet'/'triplet'/'salvage'/'start_therapy'
      2. category == 'therapy' / 'tumor_board' / 'recommendation'
      3. clinical_role contiene 'systemic' / 'local_therapy' / 'salvage' /
         'primary_treatment' / 'curative'
      4. lane es 'recommendation_today' o termina en '_therapy'
      5. NO es un gate/refiner: key NO debe ser 'biomarker_gate',
         'psma_gate', 'arpi_safety', 'docetaxel_cbc', 'safety_alert',
         'imaging_followup', 'lab_pending'
    """
    if not isinstance(item, Mapping):
        return False
    action_key = str(item.get("action_key") or "").lower()
    key = str(item.get("key") or "").lower()
    category = str(item.get("category") or item.get("type") or "").lower()
    clinical_role = str(item.get("clinical_role") or "").lower()
    lane = str(item.get("lane") or "").lower()

    # Negative signal — refiners / gates / safety, NOT primary therapy
    REFINER_KEYS = {
        "biomarker_gate", "psma_gate", "arpi_safety", "docetaxel_cbc",
        "safety_alert", "imaging_followup", "lab_pending",
        "hrr_capture", "germline_gate", "msi_gate", "consent_pending",
    }
    if key in REFINER_KEYS:
        return False
    REFINER_PATTERNS = ("_gate", "safety", "pending", "missing_data",
                         "biomarker", "imaging_due", "lab_due")
    if any(p in key for p in REFINER_PATTERNS):
        return False

    # Positive signal — primary therapy decision
    THERAPY_ACTION_PREFIXES = ("tumor_board:", "therapy:", "recommendation:",
                                "pathway:", "treatment:", "start_therapy")
    if any(action_key.startswith(p) for p in THERAPY_ACTION_PREFIXES):
        return True
    THERAPY_KEYWORDS = ("doublet", "triplet", "salvage_rt", "salvage_local",
                        "adt_backbone", "arpi", "start_therapy", "intensification",
                        "primary_rt", "mdt", "sbrt", "active_surveillance")
    if any(kw in key for kw in THERAPY_KEYWORDS):
        return True
    if category in ("therapy", "tumor_board", "recommendation", "primary_treatment"):
        return True
    if any(t in clinical_role for t in ("systemic", "local_therapy",
                                         "salvage", "primary_treatment", "curative",
                                         "mhspc_systemic", "mcrpc_systemic")):
        return True
    if lane.endswith("_therapy") or lane == "recommendation_today":
        return True
    return False


def _top_autodrive_item(autodrive: Mapping[str, Any]) -> dict[str, Any]:
    """BUG FIX 2026-05-17 — Prefiere THERAPY DECISIONS sobre refiners moleculares.

    Pre-fix: retornaba el PRIMER item del queue sin filtrar tipo. Resultado:
    "Biomarcadores accionables" (refiner) sobrescribía la decisión terapéutica
    primaria del estadio (e.g., para mcspc_low_volume_sync_oligo debería
    surface "Doblete ADT+ARPI" según STAMPEDE/ENZAMET v2026, no biomarkers).

    Post-fix: dos pasadas:
      Pass 1 — busca primer item que sea decisión terapéutica primaria
               (_is_primary_therapy_item)
      Pass 2 — fallback al primer item no-kernel si no hay therapy decision
               visible (estados pre-diagnóstico, screening, etc.)
    """
    queue = autodrive.get("today_queue") or autodrive.get("autodrive_actions") or []
    # Pass 1 — primary therapy decisions take precedence
    for item in queue:
        if (isinstance(item, Mapping)
                and item.get("action_key") != "decision_today:fusion_kernel"
                and _is_primary_therapy_item(item)):
            return dict(item)
    # Pass 2 — fallback to first non-kernel item (refiners surface only
    # when no therapy decision is visible — pre-diagnostic / screening states)
    for item in queue:
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
    """BUG FIX 2026-05-17 — Active safety SOLO por GENUINE safety triggers:
    toxicidad limitante, off-track real (memoria clínica), o readiness lane con
    `active_risk`. NO disparar por missing-data refiners (biomarker_gate,
    psma_gate, lab_pending) aunque tengan lane=urgent_today + priority=critical_today.

    Pre-fix: cualquier item top con lane=urgent_today+critical_today disparaba
    active_safety → decision_title overridden por top_autodrive.title →
    "Biomarcadores accionables" aparecía como decision today incluso cuando
    el classifier oficial ya tenía 'Priorizar ADT + enzalutamida'.

    Post-fix: el top item solo cuenta si NO es un refiner molecular/lab.
    """
    if memory_status in {"toxicity_limited", "off_track"}:
        return True
    readiness = bundle.get("clinical_readiness_tower") or {}
    if any(isinstance(lane, Mapping) and lane.get("status") == "active_risk" for lane in readiness.get("lanes") or []):
        return True
    top = _top_autodrive_item(autodrive)
    if top.get("lane") == "urgent_today" and top.get("priority_status") == "critical_today":
        # Re-check: el top es genuine safety o un refiner enmascarado de urgente?
        # _top_autodrive_item ahora prefiere therapy items, pero si solo hay refiners
        # cae a primer refiner. NO disparar safety por refiners.
        if _is_primary_therapy_item(top):
            return True
        # Si top es un refiner (biomarker_gate/psma_gate/lab_pending) → NO es safety
    return False


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
        lane = _lane_for_missing_field(field, fallback_lane)
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


def _lane_for_missing_field(field: str, fallback_lane: str = "") -> str:
    if fallback_lane == "localized_treatment_readiness" and field in {
        "patient_values",
        "localized_patient_values",
        "urinary_function_baseline",
        "sexual_function_baseline",
        "bowel_function_baseline",
        "rp_rt_as_tradeoff_documented",
    }:
        return "localized_treatment_readiness"
    return FIELD_TO_LANE.get(field) or fallback_lane or "clinical_data_completion"


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
    ledger_quality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ledger_quality = dict(ledger_quality or {})
    if int(ledger_quality.get("critical_conflict_count") or 0) > 0:
        critical = list(ledger_quality.get("critical_conflicts") or ledger_quality.get("open_conflicts") or [])
        primary_fact = dict(critical[0] or {}) if critical else {}
        cta_href = (
            (ledger_quality.get("reconciliation_cta") or {}).get("href")
            or f"/clinical-fact-reconciliation/{quote(str(patient_ref))}"
        )
        return {
            "label": "Reconciliar conflicto critico Ledger",
            "title": "Resolver conflicto critico antes de DECISION HOY",
            "reason": ledger_quality.get("message") or "Existe un conflicto clinico bloqueante en el Ledger.",
            "risk_avoided": "Evita liberar o ejecutar una decision basada en hechos clinicos contradictorios.",
            "cta": {
                "label": "Reconciliar hechos clinicos",
                "href": cta_href,
                "action_mode": "reconcile_clinical_fact",
                "patient_ref": str(patient_ref),
                "decision_field": primary_fact.get("fact_key") or "",
                "ledger_quality_status": ledger_quality.get("status"),
            },
            "ledger_quality_gate": {
                "status": ledger_quality.get("status"),
                "critical_conflict_count": ledger_quality.get("critical_conflict_count"),
                "conflict_count": ledger_quality.get("conflict_count"),
                "primary_fact_key": primary_fact.get("fact_key") or "",
            },
            "source_bundles": ["clinical_decision_today_fusion_kernel", "clinical_fact_ledger"],
            "due_at": "hoy",
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
        }
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
    if ledger_quality.get("requires_reconciliation"):
        open_conflicts = list(ledger_quality.get("open_conflicts") or [])
        primary_fact = dict(open_conflicts[0] or {}) if open_conflicts else {}
        cta_href = (
            (ledger_quality.get("reconciliation_cta") or {}).get("href")
            or f"/clinical-fact-reconciliation/{quote(str(patient_ref))}"
        )
        return {
            "label": "Revisar contradiccion Ledger",
            "title": _first_text(title, "Revisar contradiccion Ledger"),
            "reason": ledger_quality.get("message") or rationale,
            "risk_avoided": "Evita cerrar una decision con datos discordantes no firmados.",
            "cta": {
                "label": "Reconciliar hechos clinicos",
                "href": cta_href,
                "action_mode": "reconcile_clinical_fact",
                "patient_ref": str(patient_ref),
                "decision_field": primary_fact.get("fact_key") or "",
                "ledger_quality_status": ledger_quality.get("status"),
            },
            "ledger_quality_gate": {
                "status": ledger_quality.get("status"),
                "critical_conflict_count": ledger_quality.get("critical_conflict_count"),
                "conflict_count": ledger_quality.get("conflict_count"),
                "primary_fact_key": primary_fact.get("fact_key") or "",
            },
            "source_bundles": ["clinical_decision_today_fusion_kernel", "clinical_fact_ledger"],
            "due_at": "hoy / segun agenda",
            "source_clinical_facts_mutated": False,
            "external_order_created": False,
            "model_trained": False,
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
