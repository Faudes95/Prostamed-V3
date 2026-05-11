from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from prostanet.agents.contracts import AgentOutput, AgentRecommendation
from prostanet.domains.patient_tracking.event_graph import (
    merge_record_into_assessment_payload,
)
from prostanet.shared.gleason_profile import normalize_gleason_profile
from prostanet.shared.metastatic_profile import build_metastatic_composition_summary
from prostanet.shared.presentation_text import state_display_label


MISSING_VALUES = {None, "", "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida"}
YES_VALUES = {"1", "true", "yes", "si", "sí"}
VERTICAL_BUNDLE_PRIORITY = (
    "post_rp_salvage_bundle",
    "post_rt_salvage_bundle",
    "crpc_copilot_bundle",
    "mhspc_copilot_bundle",
    "localized_surveillance_bundle",
    "diagnostic_biopsy_bundle",
)


def is_present(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return value not in MISSING_VALUES


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def coerce_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    if isinstance(value, str):
        return [normalize_text(item) for item in value.split(",") if normalize_text(item)]
    return []


def overlay_present_values(
    payload: dict[str, Any],
    *sources: dict[str, Any],
    keys: set[str],
) -> None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if is_present(value):
                payload[key] = value


def build_runtime_patient(
    patient: dict[str, Any],
    longitudinal_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_patient = dict(patient or {})
    if longitudinal_bundle and longitudinal_bundle.get("longitudinal_truth_snapshot"):
        runtime_patient["longitudinal_truth_snapshot"] = dict(longitudinal_bundle.get("longitudinal_truth_snapshot") or {})
    if not runtime_patient.get("genomic_profile") and runtime_patient.get("genomics"):
        runtime_patient["genomic_profile"] = dict(runtime_patient.get("genomics") or {})
    return runtime_patient


def build_runtime_payload(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    *,
    effective_state: str,
    overlay_keys: set[str] | None = None,
) -> dict[str, Any]:
    assessment_input = dict(((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    payload = merge_record_into_assessment_payload(assessment_input, patient)
    truth_values = dict((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    latest_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    latest_followup = dict((patient.get("follow_ups") or [{}])[-1] or {})
    latest_visit_payload = dict(((latest_followup.get("visit_bundle") or {}).get("payload")) or {})
    latest_treatment = dict((patient.get("treatments") or [{}])[-1] or {})
    latest_biopsy = dict((patient.get("biopsies") or [{}])[-1] or {})
    regimen_json = coerce_dict(latest_treatment.get("regimen_json"))
    baseline = coerce_dict(patient.get("baseline"))
    bcr = coerce_dict(patient.get("bcr"))
    surgery = coerce_dict(patient.get("surgery"))
    radiation = coerce_dict(patient.get("radiation"))
    genomics = coerce_dict(patient.get("genomics") or patient.get("genomic_profile"))
    sources = (
        baseline,
        truth_values,
        latest_snapshot,
        latest_followup,
        latest_visit_payload,
        latest_biopsy,
        latest_treatment,
        regimen_json,
        bcr,
        surgery,
        radiation,
        genomics,
    )
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if is_present(value) and not is_present(payload.get(key)):
                payload[key] = value

    if overlay_keys:
        overlay_present_values(payload, *sources, keys=set(overlay_keys))

    current_treatment = normalize_text(
        payload.get("current_treatment")
        or payload.get("drug_scheme")
        or latest_treatment.get("drug_scheme_label")
        or latest_treatment.get("drug_scheme")
        or regimen_json.get("drug_scheme_label")
    )
    if current_treatment:
        payload["current_treatment"] = current_treatment
    payload["drug_scheme"] = (
        payload.get("drug_scheme")
        or latest_visit_payload.get("drug_scheme")
        or latest_treatment.get("drug_scheme")
        or regimen_json.get("drug_scheme")
    )
    payload["line_of_therapy_number"] = (
        payload.get("line_of_therapy_number")
        or payload.get("line_of_therapy")
        or latest_treatment.get("line_of_therapy")
        or regimen_json.get("line_of_therapy_number")
    )
    prior_therapy = list(dict.fromkeys(coerce_text_list(payload.get("prior_therapy"))))
    current_line = safe_int(payload.get("line_of_therapy_number"))
    for item in list(patient.get("treatments") or []):
        regimen_payload = coerce_dict(item.get("regimen_json"))
        scheme = normalize_text(item.get("drug_scheme") or item.get("drug_scheme_label") or regimen_payload.get("drug_scheme_label"))
        line_number = safe_int(item.get("line_of_therapy") or regimen_payload.get("line_of_therapy_number"))
        ended = bool(item.get("end_date")) or normalize_text(item.get("outcome")).lower() not in {"", "ongoing", "en curso"}
        prior_line = ended or (
            current_line is not None
            and line_number is not None
            and line_number < current_line
        )
        if scheme and prior_line and scheme not in prior_therapy:
            prior_therapy.append(scheme)
    if prior_therapy:
        payload["prior_therapy"] = prior_therapy
    if not is_present(payload.get("prior_prostatectomy")):
        payload["prior_prostatectomy"] = 1 if patient.get("surgery") else 0
    if not is_present(payload.get("prior_radiation")):
        payload["prior_radiation"] = 1 if patient.get("radiation") else 0
    if not is_present(payload.get("radiation_date")) and patient.get("radiation"):
        latest_radiation = patient.get("radiation")[-1]
        payload["radiation_date"] = latest_radiation.get("rt_date") or ""
    if not is_present(payload.get("prior_rt_modality")) and patient.get("radiation"):
        latest_radiation = patient.get("radiation")[-1]
        payload["prior_rt_modality"] = latest_radiation.get("rt_technique") or ""
    if not is_present(payload.get("psa_history")) and patient.get("psa_series"):
        payload["psa_history"] = [
            {
                "value": point.get("value"),
                "date": point.get("sample_date") or "",
                "unit": point.get("unit") or "ng/mL",
                "context": point.get("context") or "",
                "source": point.get("source") or point.get("entry_origin") or "",
                "line_of_therapy_number": point.get("line_of_therapy_number"),
                "line_of_therapy_context": point.get("line_of_therapy_context") or "",
            }
            for point in list(patient.get("psa_series") or [])
            if is_present(point.get("sample_date")) and point.get("value") not in (None, "")
        ]
    if not is_present(payload.get("psa_current")) and payload.get("psa_history"):
        latest_psa_point = list(payload.get("psa_history") or [])[-1]
        if is_present(latest_psa_point.get("value")):
            payload["psa_current"] = latest_psa_point.get("value")
        if not is_present(payload.get("psa_current_date")) and is_present(latest_psa_point.get("date")):
            payload["psa_current_date"] = latest_psa_point.get("date")
    if not is_present(payload.get("testosterone_history")) and patient.get("testosterone_series"):
        payload["testosterone_history"] = [
            {
                "value": point.get("value"),
                "date": point.get("sample_date") or "",
                "unit": point.get("unit") or "ng/dL",
                "context": point.get("context") or "",
                "source": point.get("source") or point.get("entry_origin") or "",
                "line_of_therapy_number": point.get("line_of_therapy_number"),
                "line_of_therapy_context": point.get("line_of_therapy_context") or "",
            }
            for point in list(patient.get("testosterone_series") or [])
            if is_present(point.get("sample_date")) and point.get("value") not in (None, "")
        ]
    if not is_present(payload.get("testosterone")) and payload.get("testosterone_history"):
        latest_testosterone_point = list(payload.get("testosterone_history") or [])[-1]
        if is_present(latest_testosterone_point.get("value")):
            payload["testosterone"] = latest_testosterone_point.get("value")
    payload["effective_state"] = effective_state
    return payload


def guideline_basis_from_result(module_result: dict[str, Any]) -> list[str]:
    basis: list[str] = []
    nccn = dict(module_result.get("nccn_primary") or {})
    eau = dict(module_result.get("eau_comparison") or {})
    if nccn.get("guideline") and nccn.get("version"):
        basis.append(f"{nccn['guideline']} {nccn['version']}: {nccn.get('label') or nccn.get('recommendation') or ''}".strip())
    if eau.get("guideline") and eau.get("version"):
        basis.append(f"{eau['guideline']} {eau['version']}: {eau.get('label') or eau.get('recommendation') or ''}".strip())
    for item in list((module_result.get("report_sections") or {}).get("structured_summary", {}).get("fundamentos_personalizados") or [])[:2]:
        if normalize_text(item):
            basis.append(normalize_text(item))
    return [item for item in basis if normalize_text(item)]


def run_vertical_qa_validation(
    qa_agent: Any,
    patient: dict[str, Any],
    *,
    reconciled_state: str,
    action: str,
    evidence_basis: list[str],
    agent_id: str,
    category: str = "treatment",
    confidence_score: float = 70.0,
) -> dict[str, Any]:
    recommendation = AgentRecommendation(
        action=action,
        category=category,
        priority="high",
        evidence_basis=list(evidence_basis or []),
    )
    qa_record = dict(patient or {})
    qa_record["reconciled_state"] = reconciled_state
    qa_output = AgentOutput(
        agent_id=agent_id,
        patient_id=int((patient.get("identity") or {}).get("id") or 0),
        recommendations=[recommendation],
        confidence_score=confidence_score,
    )
    return qa_agent.validate(qa_output, qa_record).to_dict()


def build_final_presented_recommendation(
    *,
    runtime_mode: str,
    rule_based_recommendation: dict[str, Any],
    ai_overlay: dict[str, Any],
    qa_validation: dict[str, Any],
    blocking_groups: list[dict[str, Any]],
    advisory_source: str,
    rationale: str,
) -> dict[str, Any]:
    has_required_blockers = any(group.get("required_fields") for group in (blocking_groups or []))
    if (
        runtime_mode == "advisory"
        and ai_overlay.get("available")
        and ai_overlay.get("concordance_label") != "discordant"
        and ai_overlay.get("status") != "shadow-blocked"
        and qa_validation.get("approved")
        and not has_required_blockers
    ):
        return {
            "source": advisory_source,
            "recommended_action": ai_overlay.get("recommended_action"),
            "recommendation_family": ai_overlay.get("recommendation_family"),
            "rationale": rationale,
        }
    return dict(rule_based_recommendation)


def resolve_vertical_status(
    *,
    runtime_mode: str,
    qa_validation: dict[str, Any],
    blocking_groups: list[dict[str, Any]],
    ai_overlay: dict[str, Any],
) -> str:
    if not ai_overlay.get("available"):
        return "rule_only"
    if runtime_mode == "shadow":
        return "shadow-blocked" if ai_overlay.get("status") == "shadow-blocked" else "shadow"
    has_required_blockers = any(group.get("required_fields") for group in (blocking_groups or []))
    if qa_validation.get("approved") and not has_required_blockers and ai_overlay.get("concordance_label") != "discordant":
        return "advisory"
    return "shadow-blocked"


def build_model_like_confidence(
    confidence_scorer: Any,
    patient: dict[str, Any],
    *,
    action: str,
    guideline_result: dict[str, Any],
    historical_calibration_score: float = 62.0,
) -> dict[str, Any]:
    model_like_output = {
        "recommendations": [{"action": action}],
        "metadata": {"historical_calibration_score": historical_calibration_score},
    }
    return confidence_scorer.score(
        patient,
        agent_outputs=[model_like_output],
        guideline_result=guideline_result,
    )


def build_blocking_input_groups(requirements: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = list(requirements.get("blocking_input_descriptors") or [])
    grouped: dict[str, dict[str, Any]] = {}
    blocking_names = set(requirements.get("blocking_inputs") or []) | set(requirements.get("supportive_gaps") or [])
    for item in descriptors:
        field_name = str(item.get("field_name") or "")
        bucket = str(item.get("bucket") or "decision_blocking_inputs")
        if field_name not in blocking_names:
            continue
        group_key = str(item.get("display_group") or bucket)
        group = grouped.setdefault(
            group_key,
            {
                "group_key": group_key,
                "group_label": item.get("display_group") or "Captura clínica",
                "fields": [],
                "required_fields": [],
                "why_now": item.get("display_why_now") or item.get("why") or "",
                "impact": item.get("display_impact") or "Completar este grupo puede cambiar la conducta hoy.",
                "capture_target": item.get("display_capture_target") or item.get("capture_target") or "",
            },
        )
        label = item.get("display_label") or item.get("field_name")
        if label and label not in group["fields"]:
            group["fields"].append(label)
        if bucket in {"hard_blocking_inputs", "decision_blocking_inputs"} and label not in group["required_fields"]:
            group["required_fields"].append(label)
    if grouped:
        return list(grouped.values())
    plain_groups = []
    for field_name in requirements.get("blocking_inputs") or []:
        plain_groups.append(
            {
                "group_key": field_name,
                "group_label": "Dato decisivo",
                "fields": [field_name],
                "required_fields": [field_name],
                "why_now": "La decisión clínica actual no se cierra sin este dato.",
                "impact": "Completarlo hoy puede recalcular la conducta.",
                "capture_target": "followup",
            }
        )
    return plain_groups


def select_primary_vertical_bundle(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for key in VERTICAL_BUNDLE_PRIORITY:
        bundle = dict(payload.get(key) or {})
        if bundle.get("available"):
            return key, bundle
    return "", {}


def derive_display_sequence_summary(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": normalize_text(item.get("label") or item.get("drug_label") or item.get("regimen_label")),
            "blocked": bool(item.get("blocked")),
            "blocked_by": list(item.get("blocked_by") or item.get("contraindication_reasons") or []),
            "is_preferred": bool(item.get("is_preferred", False)),
        }
        for item in list(bundle.get("sequence_candidates") or bundle.get("frontline_regimen_rankings") or [])[:3]
    ]


def as_dict_list(items: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if hasattr(item, "to_dict"):
            normalized.append(item.to_dict())
        elif hasattr(item, "__dataclass_fields__"):
            normalized.append(asdict(item))
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def build_shared_metastatic_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    return build_metastatic_composition_summary(data)


def build_histopathology_summary(data: dict[str, Any] | None) -> str:
    profile = normalize_gleason_profile(data or {})
    return normalize_text(profile.get("summary"))


def enrich_recommendation_with_metastatic_summary(
    recommendation: dict[str, Any] | None,
    metastatic_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    enriched = dict(recommendation or {})
    summary = dict(metastatic_summary or {})
    if not summary.get("available"):
        return enriched
    narrative = normalize_text(summary.get("narrative"))
    rationale = normalize_text(enriched.get("rationale"))
    if narrative and narrative not in rationale:
        enriched["rationale"] = f"{rationale} {narrative}".strip()
    enriched["metastatic_composition_summary"] = summary
    return enriched


def prepend_metastatic_context(notes: list[str] | None, metastatic_summary: dict[str, Any] | None) -> list[str]:
    items = [normalize_text(item) for item in list(notes or []) if normalize_text(item)]
    summary = dict(metastatic_summary or {})
    if not summary.get("available"):
        return items
    narrative = normalize_text(summary.get("narrative"))
    if narrative and narrative not in items:
        items.insert(0, narrative)
    return items


def build_blocked_by_overlay(
    *,
    blocking_groups: list[dict[str, Any]] | None = None,
    safety_gates: list[dict[str, Any]] | None = None,
    progression_gate_active: bool = False,
    progression_gate_target: str = "",
    progression_gate_reason: str = "",
) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    if progression_gate_active:
        blocked.append(
            {
                "overlay": "systemic_progression_gate",
                "label": progression_gate_target or "adt_progression_verification",
                "reason": progression_gate_reason or "La decisión final sigue bloqueada hasta cerrar castración y reestadificación.",
            }
        )
    for group in blocking_groups or []:
        required_fields = list(group.get("required_fields") or [])
        if not required_fields:
            continue
        blocked.append(
            {
                "overlay": "required_input_group",
                "label": normalize_text(group.get("group_label") or "Captura clínica"),
                "reason": normalize_text(group.get("why_now") or group.get("impact") or ""),
                "required_fields": required_fields,
            }
        )
    for gate in safety_gates or []:
        status = normalize_text(gate.get("status")).lower()
        should_surface = (
            bool(gate.get("blocked"))
            or bool(gate.get("failure_family"))
            or status in {"blocked", "contraindicated", "missing", "needs_input", "warning", "caution", "pending"}
        )
        if not should_surface:
            continue
        blocked.append(
            {
                "overlay": "safety_gate",
                "label": normalize_text(gate.get("label") or gate.get("gate_key") or "Safety gate"),
                "reason": normalize_text(gate.get("rationale") or gate.get("summary") or status),
                "status": status or "blocked",
            }
        )
    return blocked


def build_decision_delta_since_last_visit(
    patient: dict[str, Any],
    *,
    effective_state: str,
    phenotype_state: str,
    rule_based_recommendation: dict[str, Any] | None,
    final_presented_recommendation: dict[str, Any] | None,
    blocking_groups: list[dict[str, Any]] | None = None,
    blocked_by_overlay: list[dict[str, Any]] | None = None,
    current_pivotal_gates: list[dict[str, Any]] | None = None,
    previous_pivotal_gates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fallback_followup = dict(
        patient.get("latest_follow_up")
        or (list(patient.get("follow_ups") or [])[-1] if list(patient.get("follow_ups") or []) else {})
    )
    decisive_visit = dict(
        patient.get("latest_clinically_decisive_visit")
        or (patient.get("decision_recalculation_trace") or {}).get("latest_clinically_decisive_visit")
        or fallback_followup
        or {}
    )
    changed_fields = [
        normalize_text(item)
        for item in list(decisive_visit.get("changed_fields") or decisive_visit.get("fields_changed") or [])
        if normalize_text(item)
    ]
    if not changed_fields and fallback_followup:
        fallback_candidates = [
            "bone_site_entries",
            "visceral_site_entries",
            "nonregional_nodal_site_entries",
            "metastasis_site",
            "metastasis_count",
            "volume_disease",
            "progression_pattern",
            "disease_status",
            "testosterone",
            "testosterone_value",
            "castrate_testosterone_status",
            "current_treatment",
            "management_track",
        ]
        changed_fields = [
            field
            for field in fallback_candidates
            if fallback_followup.get(field) not in (None, "", [], {})
        ]
    # Faubot 2026-04-25 (IX) — Delta longitudinal de gates pivotal.
    # Incluso cuando no hay decisive_visit (sin cambios clínicos clásicos),
    # PUEDE haber cambios en gates pivotal (override clínico documentado).
    # Por eso el cómputo del delta de gates va ANTES del early return.
    from prostanet.shared.pivotal_gate_delta import (
        compute_pivotal_gates_delta,
        build_pivotal_gates_delta_summary,
    )
    pivotal_gates_delta = compute_pivotal_gates_delta(
        current_pivotal_gates, previous_pivotal_gates
    )
    pivotal_gates_delta_summary = build_pivotal_gates_delta_summary(pivotal_gates_delta)
    has_pivotal_gate_change = (
        pivotal_gates_delta.get("available")
        and pivotal_gates_delta.get("total_change_count", 0) > 0
    )

    if not decisive_visit and not changed_fields and not has_pivotal_gate_change:
        return {
            "available": False,
            "summary": "",
            "change_classification": "stable",
            "changed_fields": [],
            "next_best_action_today": normalize_text((final_presented_recommendation or {}).get("recommended_action")),
            "could_change_with_missing_data": [],
            "blocked_today": bool(blocked_by_overlay),
            "pivotal_gates_delta": pivotal_gates_delta,
            "pivotal_gates_delta_summary": pivotal_gates_delta_summary,
        }

    phenotype_keys = {
        "metastasis_site",
        "bone_site_entries",
        "visceral_site_entries",
        "metastasis_count",
        "volume_disease",
        "m_substage_resolved",
        "conventional_imaging_status",
        "psma_stage_after_psma",
        "metachronous_metastasis",
        "progression_pattern",
        "castrate_testosterone_status",
        "testosterone",
        "testosterone_value",
    }
    if any(field in phenotype_keys for field in changed_fields):
        change_classification = "phenotype_shift_or_restaging"
    elif blocked_by_overlay:
        change_classification = "safety_gate_or_blocker"
    elif changed_fields:
        change_classification = "treatment_intensity_or_tracking"
    else:
        change_classification = "stable"

    changed_label = ", ".join(changed_fields[:4])
    phenotype_label = state_display_label(phenotype_state or effective_state)
    if change_classification == "phenotype_shift_or_restaging":
        summary = f"La consulta actual recalculó el fenotipo/reestratificación hacia {phenotype_label}"
        if changed_label:
            summary = f"{summary} por cambios en {changed_label}"
    elif change_classification == "safety_gate_or_blocker":
        summary = "La consulta actual activó o mantuvo un gate de seguridad clínicamente decisivo."
    elif changed_label:
        summary = f"La consulta actual cambió la decisión longitudinal por nuevas variables en {changed_label}."
    else:
        summary = f"El caso permanece en {phenotype_label} sin un cambio longitudinal dominante adicional."
    summary = summary.rstrip(".") + "."

    # Faubot 2026-04-25 (IX) — Si el delta de gates aporta info adicional,
    # promueve la classification a "safety_gate_or_blocker" o enriquece el
    # summary con el resumen del delta.
    if has_pivotal_gate_change and change_classification == "stable":
        change_classification = "safety_gate_or_blocker"
        summary = (
            f"Cambio en gates pivotal desde la visita previa: "
            f"{pivotal_gates_delta_summary}."
        )

    return {
        "available": True,
        "visit_date": normalize_text(decisive_visit.get("visit_date") or decisive_visit.get("date")),
        "source_type": normalize_text(decisive_visit.get("source_type") or "followup"),
        "changed_fields": changed_fields,
        "change_classification": change_classification,
        "summary": summary,
        "next_best_action_today": normalize_text(
            (final_presented_recommendation or {}).get("recommended_action")
            or (rule_based_recommendation or {}).get("recommended_action")
        ),
        "could_change_with_missing_data": [
            normalize_text(field)
            for group in (blocking_groups or [])[:2]
            for field in list(group.get("required_fields") or [])[:2]
            if normalize_text(field)
        ],
        "blocked_today": bool(blocked_by_overlay),
        # Faubot 2026-04-25 (IX) — Delta longitudinal de gates pivotal.
        "pivotal_gates_delta": pivotal_gates_delta,
        "pivotal_gates_delta_summary": pivotal_gates_delta_summary,
    }


def build_evidence_basis_current_visit(
    guideline_basis: list[str] | None,
    rule_based_recommendation: dict[str, Any] | None,
    decision_delta_since_last_visit: dict[str, Any] | None,
) -> list[str]:
    basis: list[str] = []
    for item in list(guideline_basis or []) + list((rule_based_recommendation or {}).get("guideline_basis") or []):
        text = normalize_text(item)
        if text and text not in basis:
            basis.append(text)
    delta = dict(decision_delta_since_last_visit or {})
    if delta.get("available") and normalize_text(delta.get("summary")):
        basis.append(f"Cambio clínicamente decisivo actual: {normalize_text(delta.get('summary'))}")
    return basis
