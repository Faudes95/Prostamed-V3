from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.alert_engine import ClinicalAlertEngine
from prostanet.domains.patient_tracking.longitudinal_truth_service import truth_value
from prostanet.shared.contracts import CopilotAlert


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_CATEGORY_ORDER = {
    "decision_blocker": 0,
    "safety": 1,
    "protocol_due": 2,
    "data_quality": 3,
    "documentation": 4,
    "transition": 5,
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No documentado", "No aplica", "Desconocido", "Desconocida")


def _priority_label(items: list[dict[str, Any]], key: str, fallback: str = "") -> str:
    values = [str(item.get(key) or "") for item in items if str(item.get(key) or "")]
    return values[0] if values else fallback


def _unique_preserving(values: list[Any]) -> list[Any]:
    ordered: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = repr(value)
        if value in (None, "", [], {}) or marker in seen:
            continue
        seen.add(marker)
        ordered.append(value)
    return ordered


def _domain_from_targets(targets: list[str]) -> str:
    target_set = {str(item or "") for item in targets}
    if target_set & {"systemic_sequencing", "line_continuation", "castration_status", "disease_control"}:
        return "systemic_sequencing"
    if target_set & {"cv_safety", "arpi_safety", "treatment_tolerability", "bone_safety", "supportive_care"}:
        return "treatment_safety"
    if target_set & {"parp_eligibility", "precision_pathway"}:
        return "precision_therapy"
    if target_set & {"psma_eligibility", "radiographic_restage", "disease_burden"}:
        return "restaging"
    if target_set & {"frailty", "treatment_fitness", "treatment_intensity"}:
        return "fitness"
    if target_set & {"quality_of_life", "symptom_control", "goals_of_care"}:
        return "quality_of_life"
    if target_set & {"official_diagnosis"}:
        return "official_diagnosis"
    return "general_followup"


def _domain_from_checkpoint(checkpoint: dict[str, Any]) -> str:
    key = str(checkpoint.get("key") or "")
    if key in {"biomarker_gate"}:
        return "precision_therapy"
    if key in {"psma_gate"}:
        return "restaging"
    if key in {"arpi_safety", "docetaxel_cbc"}:
        return "treatment_safety"
    if key in {"salvage_gate"}:
        return "salvage_gate"
    if key in {"shared_decision_local", "genomic_localized"}:
        return "local_decision"
    return "general_followup"


def _domain_from_missing(text: str) -> tuple[str, list[str], str]:
    lowered = text.lower()
    if "testosterona" in lowered or "castr" in lowered:
        return "systemic_sequencing", ["testosterone", "castrate_testosterone_status"], "decision_blocker"
    if "molecular" in lowered or "biomarcador" in lowered or "parp" in lowered:
        return "precision_therapy", ["hrr_status", "hrr_gene", "msi_status", "biomarker_source", "molecular_assay_date"], "documentation"
    if "psma" in lowered:
        return "restaging", ["psma_positive", "psma_negative_dominant_lesions", "imaging_modality"], "decision_blocker"
    if "psa" in lowered:
        return "disease_control", ["psa"], "protocol_due"
    if "mri" in lowered or "imagen" in lowered:
        return "restaging", ["imaging_modality"], "protocol_due"
    if "fragilidad" in lowered or "fitness" in lowered:
        return "fitness", ["g8_food_intake", "g8_weight_loss", "low_activity", "slow_gait", "weak_grip"], "data_quality"
    return "general_followup", [], "data_quality"


def _category_from_agenda_item(item: dict[str, Any], domain: str) -> str:
    item_type = str(item.get("item_type") or "")
    status = str(item.get("status") or "")
    if item_type == "pathology_review":
        return "documentation"
    if status in {"overdue", "due", "due_today"}:
        return "protocol_due"
    if status == "blocked":
        return "safety" if domain == "treatment_safety" else "data_quality"
    return "data_quality"


def _capture_block_for_domain(domain: str, category: str) -> str:
    if domain == "systemic_sequencing":
        return "advanced_sequencing"
    if domain in {"precision_therapy", "official_diagnosis"}:
        return "diagnosis_capture" if domain == "official_diagnosis" else "biomarker_eligibility"
    if domain == "restaging":
        return "restaging"
    if domain in {"treatment_safety", "fitness"}:
        return "supportive_care" if domain == "treatment_safety" else "frailty_fitness"
    if domain == "quality_of_life":
        return "pro_assessment"
    if domain == "disease_control":
        return "psa_monitoring"
    if category == "documentation":
        return "documentation"
    return "clinical_completion"


def _expected_document_type(domain: str, category: str, title: str, message: str) -> str:
    haystack = f"{title} {message}".lower()
    if domain == "precision_therapy" or "molecular" in haystack or "genóm" in haystack or "genom" in haystack:
        return "genomic_report"
    if domain == "restaging" or "imagen" in haystack or "psma" in haystack or "mri" in haystack:
        return "imaging_report"
    if domain == "official_diagnosis" or "histolog" in haystack or "biops" in haystack or "gleason" in haystack:
        return "pathology_report"
    if "laboratorio" in haystack or "testosterona" in haystack or "psa" in haystack:
        return "laboratory_bundle"
    return "auto"


def _action_type_for_domain(domain: str, category: str, fields_to_capture: list[str], linked_encounter_keys: list[str]) -> str:
    if category == "documentation" and domain in {"precision_therapy", "documentation"}:
        return "document"
    if linked_encounter_keys:
        return "encounter"
    if fields_to_capture:
        return "capture"
    if category == "documentation":
        return "document"
    return "capture"


def _resolution_mode(action_type: str, fields_to_capture: list[str]) -> str:
    if action_type == "document":
        return "document"
    if fields_to_capture:
        return "mini_capture"
    if action_type == "encounter":
        return "encounter"
    return "review"


def _primary_button_label(action_type: str, fields_to_capture: list[str]) -> str:
    mode = _resolution_mode(action_type, fields_to_capture)
    if mode == "document":
        return "Subir documento requerido"
    if mode == "encounter":
        return "Abrir cita relacionada"
    if mode == "mini_capture":
        return "Completar dato faltante"
    return "Revisar seguimiento"


def _raw_alert_domain(alert: dict[str, Any]) -> str:
    category = str(alert.get("category") or "")
    alert_type = str(alert.get("alert_type") or "")
    if category.startswith("genomic"):
        return "precision_therapy"
    if category in {"ecog", "laboratory"} and alert_type == "castration_not_achieved":
        return "systemic_sequencing"
    if category in {"ecog", "laboratory"}:
        return "treatment_safety"
    if category.startswith("pro_"):
        return "quality_of_life"
    if category in {"psa_kinetics"}:
        return "disease_control"
    return "general_followup"


def _runtime_alert_data(patient: dict[str, Any], management_track: str, raw_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = patient.get("identity", {}) or {}
    baseline = patient.get("baseline", {}) or {}
    prior = patient.get("prior_history", {}) or {}
    followups = patient.get("follow_ups", []) or []
    payload: dict[str, Any] = {}
    payload.update(identity)
    payload.update(baseline)
    payload.update(prior)
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = dict(truth.get("field_values") or {})
    if followups:
        last_fu = followups[-1]
        payload["psa"] = last_fu.get("psa_current")
        payload["hemoglobin"] = last_fu.get("hemoglobin_current")
        payload["ecog"] = last_fu.get("ecog_current")
        payload["testosterone"] = last_fu.get("testosterone_current")
        payload["alp"] = last_fu.get("alp_current")
        payload["ldh"] = last_fu.get("ldh_current")
        payload["creatinine"] = last_fu.get("creatinine_current")
        payload["bilirubin"] = last_fu.get("bilirubin_current")
        payload["ast"] = last_fu.get("ast_current")
        payload["alt"] = last_fu.get("alt_current")
        payload["ggt"] = last_fu.get("ggt_current")
        payload["glucose"] = last_fu.get("glucose_current")
        payload["current_treatment"] = last_fu.get("current_treatment")
        if len(followups) >= 2:
            payload["ecog_previous"] = followups[-2].get("ecog_current")
    for field_name in (
        "psa",
        "hemoglobin",
        "ecog",
        "testosterone",
        "alp",
        "ldh",
        "creatinine",
        "bilirubin",
        "ast",
        "alt",
        "ggt",
        "glucose",
        "current_treatment",
        "current_adt_context",
        "castrate_testosterone_status",
    ):
        value = truth_values.get(field_name)
        if value in (None, ""):
            value = truth_value(patient, field_name, default=None)
        if value not in (None, ""):
            payload[field_name] = value
    payload["management_track"] = management_track
    adt_context = (
        payload.get("current_adt_context")
        or payload.get("adt_context")
        or (raw_assessment or {}).get("input_snapshot", {}).get("current_adt_context")
        or (raw_assessment or {}).get("input_snapshot", {}).get("adt_context")
    )
    if adt_context:
        payload["adt_context"] = adt_context
        payload["current_adt_context"] = adt_context
    genomics = patient.get("genomics") or {}
    if isinstance(genomics, dict):
        payload.update(genomics)
    return payload


def _encounter_map(encounters: list[dict[str, Any]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for encounter in encounters or []:
        encounter_key = str(encounter.get("encounter_key") or "")
        for task in encounter.get("tasks") or []:
            agenda_key = str(task.get("agenda_key") or "")
            if agenda_key:
                mapping.setdefault(agenda_key, []).append(encounter_key)
    return mapping


def build_copilot_alerts(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    signals: dict[str, Any],
    agenda_board: dict[str, Any],
    encounters: list[dict[str, Any]],
    raw_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    encounter_map = _encounter_map(encounters)

    if signals.get("state_conflict_flag"):
        candidates.append(
            {
                "decision_domain": "state_transition",
                "category": "transition",
                "severity": "critical",
                "title": "Estado longitudinal por confirmar",
                "message": str(signals.get("state_conflict_reason") or "La evolución longitudinal contradice el estado persistido."),
                "why_now": "Agenda, evidencia y orientación clínica deben confirmarse sobre el estado reconciliado.",
                "recommended_action": "Confirmar transición clínica y recalcular la ruta activa.",
                "fields_to_capture": [],
                "detail_items": [{"source": "reconciliation"}],
            }
        )

    protocol_trace = agenda_board.get("protocol_trace") or {}
    if protocol_trace.get("anchor_is_fallback"):
        candidates.append(
            {
                "decision_domain": "schedule_anchor",
                "category": "data_quality",
                "severity": "warning",
                "title": "Anclaje de seguimiento débil",
                "message": f"El seguimiento usa fallback en {protocol_trace.get('anchor_source') or 'origen no documentado'}.",
                "why_now": "La cadencia actual puede no reflejar la fecha clínica real del track activo.",
                "recommended_action": "Documentar fecha real de inicio terapéutico o visita válida para fortalecer el protocolo.",
                "fields_to_capture": ["visit_date"],
                "detail_items": [{"source": "protocol_trace"}],
            }
        )

    for checkpoint in agenda_board.get("therapy_checkpoints", []) or []:
        if checkpoint.get("status") != "needs_data":
            continue
        domain = _domain_from_checkpoint(checkpoint)
        candidates.append(
            {
                "decision_domain": domain,
                "category": "safety" if domain == "treatment_safety" else "decision_blocker",
                "severity": "critical" if checkpoint.get("blocking_if_missing") else "warning",
                "title": checkpoint.get("title") or "Checkpoint terapéutico pendiente",
                "message": checkpoint.get("rationale") or "",
                "why_now": checkpoint.get("why_it_matters_now") or "",
                "recommended_action": checkpoint.get("action") or "",
                "fields_to_capture": checkpoint.get("inputs_required") or [],
                "detail_items": [{"source": "therapy_checkpoint", "key": checkpoint.get("key")}],
            }
        )

    for item in agenda_board.get("active_items", []) or []:
        status = str(item.get("status") or "")
        if status not in {"due", "due_today", "overdue", "blocked"}:
            continue
        domain = _domain_from_targets(list(item.get("decision_targets") or []))
        category = _category_from_agenda_item(item, domain)
        candidates.append(
            {
                "decision_domain": domain if domain != "general_followup" else ("documentation" if item.get("item_type") == "pathology_review" else "protocol_followup"),
                "category": category,
                "severity": "critical" if status == "overdue" else "warning",
                "title": item.get("title") or "Item activo de agenda",
                "message": item.get("summary") or "",
                "why_now": f"Estado actual: {status}.",
                "recommended_action": item.get("action_label") or "Completar flujo clínico",
                "fields_to_capture": item.get("required_inputs") or [],
                "linked_agenda_ids": [int(item["id"])] if item.get("id") not in (None, "") else [],
                "linked_agenda_keys": [str(item.get("agenda_key") or "")],
                "linked_encounter_keys": encounter_map.get(str(item.get("agenda_key") or ""), []),
                "can_be_resolved_in_visit": str((item.get("form_scope") or {}).get("mode") or "") in {"item_scoped", "capture_block"},
                "creates_or_links_agenda_item": True,
                "detail_items": [{"source": "agenda", "status": status}],
            }
        )

    for missing in signals.get("critical_missing", []) or []:
        domain, fields, category = _domain_from_missing(str(missing))
        candidates.append(
            {
                "decision_domain": domain,
                "category": category,
                "severity": "critical",
                "title": str(missing),
                "message": str(missing),
                "why_now": "Es un dato que cambia la decisión clínica actual.",
                "recommended_action": "Capturar el dato faltante en la siguiente visita o desde el flujo de completitud.",
                "fields_to_capture": fields,
                "detail_items": [{"source": "critical_missing"}],
            }
        )

    for pending in signals.get("pending_adjudications", []) or []:
        if not isinstance(pending, dict):
            continue
        category = "decision_blocker" if str(pending.get("severity") or "") == "critical" else "data_quality"
        if str(pending.get("action_type") or "") == "document":
            category = "documentation"
        candidates.append(
            {
                "decision_domain": pending.get("decision_domain") or "general_followup",
                "category": category,
                "severity": str(pending.get("severity") or "warning"),
                "title": pending.get("title") or "Adjudicación pendiente",
                "message": pending.get("rationale") or "",
                "why_now": pending.get("rationale") or "",
                "recommended_action": pending.get("recommended_action") or pending.get("title") or "Completar adjudicación clínica",
                "fields_to_capture": list(pending.get("fields_to_capture") or []),
                "linked_agenda_keys": list(pending.get("linked_agenda_keys") or []),
                "linked_encounter_keys": [str(pending.get("linked_encounter_key") or "")] if str(pending.get("linked_encounter_key") or "") else [],
                "detail_items": [{"source": "pending_adjudication", "status_key": pending.get("status_key")}],
            }
        )

    for target in signals.get("prognostic_capture_targets", []) or []:
        if not isinstance(target, dict):
            continue
        action_type = str(target.get("action_type") or "capture")
        fields_to_capture = [str(field) for field in list(target.get("raw_fields") or []) if str(field or "").strip()]
        category = "documentation" if action_type == "document" else "data_quality"
        candidates.append(
            {
                "decision_domain": f"score_completion_{target.get('tool_key') or 'general'}",
                "category": category,
                "severity": "warning",
                "title": target.get("title") or "Completar herramienta pronóstica",
                "message": target.get("rationale") or "",
                "why_now": "El score aplicable aún no puede cerrar su impacto clínico con datos completos.",
                "recommended_action": target.get("action_label") or "Completar dato faltante",
                "fields_to_capture": fields_to_capture,
                "can_be_resolved_in_visit": action_type == "capture",
                "expected_document_type": target.get("expected_document_type") or "",
                "detail_items": [{"source": "prognostic_capture_target", "tool_key": target.get("tool_key")}],
            }
        )

    for safety_item in signals.get("active_safety", []) or []:
        candidates.append(
            {
                "decision_domain": "treatment_safety",
                "category": "safety",
                "severity": "warning",
                "title": "Riesgo activo de seguridad",
                "message": str(safety_item),
                "why_now": "Puede modificar la intensidad o selección del tratamiento activo.",
                "recommended_action": "Revisar el bundle de seguridad y soporte antes de continuar la línea actual.",
                "fields_to_capture": [],
                "detail_items": [{"source": "active_safety"}],
            }
        )

    try:
        runtime_alerts = [item.to_dict() for item in ClinicalAlertEngine.run_all(patient.get("identity", {}).get("id"), _runtime_alert_data(patient, management_track, raw_assessment))]
    except Exception:
        runtime_alerts = []
    for alert in runtime_alerts:
        domain = _raw_alert_domain(alert)
        severity = str(alert.get("severity") or "warning")
        candidates.append(
            {
                "decision_domain": domain,
                "category": "safety" if domain == "treatment_safety" else "decision_blocker" if severity == "critical" else "data_quality",
                "severity": severity,
                "title": alert.get("title") or "Alerta clínica",
                "message": alert.get("message") or "",
                "why_now": alert.get("guideline_reference") or "",
                "recommended_action": alert.get("recommended_action") or "",
                "fields_to_capture": [],
                "detail_items": [{"source": "clinical_alert_engine", "alert_type": alert.get("alert_type")}],
            }
        )

    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        domain = str(candidate.get("decision_domain") or "general_followup")
        groups.setdefault(domain, []).append(candidate)

    fused: list[dict[str, Any]] = []
    for domain, domain_candidates in groups.items():
        domain_candidates.sort(
            key=lambda item: (
                _CATEGORY_ORDER.get(str(item.get("category") or "data_quality"), 99),
                _SEVERITY_ORDER.get(str(item.get("severity") or "warning"), 99),
                str(item.get("title") or ""),
            )
        )
        lead = domain_candidates[0]
        fields_to_capture = _unique_preserving([field for item in domain_candidates for field in list(item.get("fields_to_capture") or [])])
        linked_agenda_ids = _unique_preserving([agenda_id for item in domain_candidates for agenda_id in list(item.get("linked_agenda_ids") or [])])
        linked_agenda_keys = _unique_preserving([agenda_key for item in domain_candidates for agenda_key in list(item.get("linked_agenda_keys") or [])])
        linked_encounter_keys = _unique_preserving([encounter_key for item in domain_candidates for encounter_key in list(item.get("linked_encounter_keys") or [])])
        action_type = _action_type_for_domain(domain, str(lead.get("category") or "data_quality"), fields_to_capture, linked_encounter_keys)
        resolution_mode = _resolution_mode(action_type, fields_to_capture)
        fused.append(
            CopilotAlert(
                alert_key=f"{state}:{management_track}:{domain}",
                category=str(lead.get("category") or "data_quality"),
                decision_domain=domain,
                severity=str(lead.get("severity") or "warning"),
                title=str(lead.get("title") or "Alerta del copiloto"),
                message=str(lead.get("message") or ""),
                why_now=str(lead.get("why_now") or ""),
                recommended_action=str(lead.get("recommended_action") or ""),
                fields_to_capture=fields_to_capture,
                detail_items=[
                    {
                        "title": item.get("title"),
                        "message": item.get("message"),
                        "category": item.get("category"),
                        "severity": item.get("severity"),
                        "why_now": item.get("why_now"),
                        "recommended_action": item.get("recommended_action"),
                        "source": item.get("detail_items", []),
                    }
                    for item in domain_candidates
                ],
                linked_agenda_ids=linked_agenda_ids,
                linked_agenda_keys=linked_agenda_keys,
                linked_encounter_keys=linked_encounter_keys,
                can_be_resolved_in_visit=any(bool(item.get("can_be_resolved_in_visit")) for item in domain_candidates),
                creates_or_links_agenda_item=any(bool(item.get("creates_or_links_agenda_item")) for item in domain_candidates),
                action_type=action_type,
                capture_block=_capture_block_for_domain(domain, str(lead.get("category") or "data_quality")),
                encounter_key=str(linked_encounter_keys[0] if linked_encounter_keys else ""),
                resolves_decision_domain=domain,
                expected_document_type=str(lead.get("expected_document_type") or "") or _expected_document_type(
                    domain,
                    str(lead.get("category") or "data_quality"),
                    str(lead.get("title") or ""),
                    str(lead.get("message") or ""),
                ),
                resolution_mode=resolution_mode,
                focus_fields=fields_to_capture,
                primary_button_label=_primary_button_label(action_type, fields_to_capture),
            ).to_dict()
        )

    fused.sort(key=lambda item: (_CATEGORY_ORDER.get(str(item.get("category") or "data_quality"), 99), _SEVERITY_ORDER.get(str(item.get("severity") or "warning"), 99), str(item.get("title") or "")))
    summary = {
        "total": len(fused),
        "critical": sum(1 for item in fused if item.get("severity") == "critical"),
        "warning": sum(1 for item in fused if item.get("severity") == "warning"),
        "by_category": {
            category: sum(1 for item in fused if item.get("category") == category)
            for category in ["decision_blocker", "protocol_due", "safety", "data_quality", "documentation", "transition"]
        },
    }
    return {"alerts": fused, "summary": summary}
