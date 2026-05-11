from __future__ import annotations

from typing import Any


TRUTH_PRIORITY = ("stage_visit", "follow_up", "verified_document", "assessment", "baseline")

FOLLOWUP_FIELD_MAP = {
    "psa": "psa_current",
    "testosterone": "testosterone_current",
    "hemoglobin": "hemoglobin_current",
    "creatinine": "creatinine_current",
    "cystatin_c": "cystatin_c_current",
    "alp": "alp_current",
    "ldh": "ldh_current",
    "bilirubin": "bilirubin_current",
    "ast": "ast_current",
    "alt": "alt_current",
    "ggt": "ggt_current",
    "glucose": "glucose_current",
    "ecog": "ecog_current",
    "pain": "pain_score",
    "current_treatment": "current_treatment",
    "disease_status": "disease_status",
    "management_track": "management_track",
    "state": "state_at_visit",
    "hepatic_risk_status": "hepatic_risk_status",
}

TRACKED_FIELDS = (
    "state",
    "management_track",
    "current_treatment",
    "drug_scheme",
    "disease_status",
    "progression_pattern",
    "current_adt_context",
    "castrate_testosterone_status",
    "conventional_imaging_status",
    "psa",
    "testosterone",
    "hemoglobin",
    "creatinine",
    "cystatin_c",
    "alp",
    "ldh",
    "bilirubin",
    "ast",
    "alt",
    "ggt",
    "glucose",
    "hba1c",
    "calcium_level",
    "vitamin_d_level",
    "albumin",
    "ecog",
    "pain",
    "hepatic_risk_status",
)

CLINICALLY_DECISIVE_FIELDS = {
    "psa",
    "testosterone",
    "current_treatment",
    "drug_scheme",
    "disease_status",
    "progression_pattern",
    "current_adt_context",
    "castrate_testosterone_status",
    "conventional_imaging_status",
    "ecog",
    "hemoglobin",
    "creatinine",
    "alp",
    "ldh",
    "ast",
    "alt",
    "bilirubin",
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positive", "positivo", "confirmed_castrate"}


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _latest_stage_visit_payload(patient: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_visit = _latest(patient.get("stage_visits", []), "visit_date")
    payload = (((stage_visit.get("visit_bundle") or {}).get("payload")) or {}) if stage_visit else {}
    return stage_visit, payload if isinstance(payload, dict) else {}


def _verified_fact_map(patient: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fact_map: dict[str, dict[str, Any]] = {}
    ordered = sorted(
        list(patient.get("verified_document_facts") or []),
        key=lambda item: (str(item.get("source_date") or ""), int(item.get("id") or 0)),
        reverse=True,
    )
    for item in ordered:
        field_name = str(item.get("field_name") or "").strip()
        if not field_name or field_name in fact_map:
            continue
        value = item.get("value")
        if _is_present(value):
            fact_map[field_name] = item
    return fact_map


def _baseline_sources(patient: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(patient.get("baseline") or {})
    baseline.update(patient.get("prior_history") or {})
    baseline.update(patient.get("identity") or {})
    return baseline


def _normalize_stage_visit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    if not _is_present(normalized.get("disease_status")) and _is_present(normalized.get("status")):
        normalized["disease_status"] = normalized.get("status")
    if not _is_present(normalized.get("drug_scheme")) and _is_present(normalized.get("current_treatment")):
        normalized["drug_scheme"] = normalized.get("current_treatment")
    if not _is_present(normalized.get("current_adt_context")) and _is_present(normalized.get("adt_context")):
        normalized["current_adt_context"] = normalized.get("adt_context")
    if not _is_present(normalized.get("castrate_testosterone_status")):
        t_value = _safe_float(normalized.get("testosterone"))
        if t_value is not None:
            normalized["castrate_testosterone_status"] = "confirmed_castrate" if t_value <= 50 else "not_castrate"
    if not _is_present(normalized.get("progression_pattern")):
        disease_status = str(normalized.get("disease_status") or "").lower()
        if "radiograf" in disease_status:
            normalized["progression_pattern"] = "radiographic"
        elif "clinic" in disease_status:
            normalized["progression_pattern"] = "clinical"
        elif "bioqu" in disease_status or "psa" in disease_status:
            normalized["progression_pattern"] = "biochemical_only"
    return normalized


def _choose_value(
    field_name: str,
    *,
    stage_payload: dict[str, Any],
    latest_followup: dict[str, Any],
    verified_facts: dict[str, dict[str, Any]],
    assessment_inputs: dict[str, Any],
    baseline_sources: dict[str, Any],
) -> tuple[Any, str, str]:
    if _is_present(stage_payload.get(field_name)):
        return stage_payload.get(field_name), "stage_visit", str(stage_payload.get("visit_date") or "")

    followup_field = FOLLOWUP_FIELD_MAP.get(field_name, field_name)
    if _is_present(latest_followup.get(followup_field)):
        return latest_followup.get(followup_field), "follow_up", str(latest_followup.get("visit_date") or "")

    fact = verified_facts.get(field_name)
    if fact and _is_present(fact.get("value")):
        return fact.get("value"), "verified_document", str(fact.get("source_date") or "")

    if _is_present(assessment_inputs.get(field_name)):
        return assessment_inputs.get(field_name), "assessment", ""

    if _is_present(baseline_sources.get(field_name)):
        return baseline_sources.get(field_name), "baseline", ""

    return None, "", ""


def build_longitudinal_truth_snapshot(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_stage_visit, stage_payload_raw = _latest_stage_visit_payload(patient)
    stage_payload = _normalize_stage_visit_payload(stage_payload_raw)
    if latest_stage_visit.get("visit_date") and not stage_payload.get("visit_date"):
        stage_payload["visit_date"] = latest_stage_visit.get("visit_date")
    verified_facts = _verified_fact_map(patient)
    assessment_inputs = ((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    baseline_sources = _baseline_sources(patient)
    field_values: dict[str, Any] = {}
    field_sources: dict[str, dict[str, str]] = {}
    superseded_inputs: list[dict[str, Any]] = []

    for field_name in TRACKED_FIELDS:
        value, source_type, source_date = _choose_value(
            field_name,
            stage_payload=stage_payload,
            latest_followup=latest_followup,
            verified_facts=verified_facts,
            assessment_inputs=assessment_inputs,
            baseline_sources=baseline_sources,
        )
        if not _is_present(value):
            continue
        field_values[field_name] = value
        field_sources[field_name] = {
            "source_type": source_type,
            "source_date": source_date,
        }
        prior_value = assessment_inputs.get(field_name)
        if source_type in {"stage_visit", "follow_up", "verified_document"} and _is_present(prior_value) and str(prior_value) != str(value):
            superseded_inputs.append(
                {
                    "field_name": field_name,
                    "previous_value": prior_value,
                    "current_value": value,
                    "source_type": source_type,
                    "source_date": source_date,
                }
            )

    current_treatment = str(field_values.get("current_treatment") or field_values.get("drug_scheme") or "")
    if not _is_present(field_values.get("castrate_testosterone_status")):
        testosterone = _safe_float(field_values.get("testosterone"))
        if testosterone is not None:
            field_values["castrate_testosterone_status"] = "confirmed_castrate" if testosterone <= 50 else "not_castrate"
            field_sources.setdefault("castrate_testosterone_status", field_sources.get("testosterone", {"source_type": "", "source_date": ""}))
    if not _is_present(field_values.get("progression_pattern")):
        disease_status = str(field_values.get("disease_status") or "").lower()
        if "radiograf" in disease_status:
            field_values["progression_pattern"] = "radiographic"
        elif "clinic" in disease_status:
            field_values["progression_pattern"] = "clinical"
        elif "bioqu" in disease_status or "psa" in disease_status:
            field_values["progression_pattern"] = "biochemical_only"
    if not _is_present(field_values.get("current_adt_context")):
        lowered = current_treatment.lower()
        if any(token in lowered for token in ("leupro", "degarel", "goserelin", "triptorelin", "relugolix", "orchiect", "adt")):
            field_values["current_adt_context"] = "medical_adt_continuous"
    if not _is_present(field_values.get("management_track")):
        field_values["management_track"] = latest_followup.get("management_track") or latest_stage_visit.get("management_track") or ""
    if not _is_present(field_values.get("state")):
        field_values["state"] = latest_stage_visit.get("state") or latest_followup.get("state_at_visit") or ""

    decisive_source = "assessment"
    decisive_date = ""
    decisive_payload = {}
    if latest_stage_visit and latest_stage_visit.get("visit_date"):
        decisive_source = "stage_visit"
        decisive_date = str(latest_stage_visit.get("visit_date") or "")
        decisive_payload = stage_payload
    elif latest_followup and latest_followup.get("visit_date"):
        decisive_source = "follow_up"
        decisive_date = str(latest_followup.get("visit_date") or "")
        decisive_payload = latest_followup

    changed_fields = [
        item["field_name"]
        for item in superseded_inputs
        if item.get("field_name") in CLINICALLY_DECISIVE_FIELDS
    ]
    if not changed_fields and decisive_payload:
        changed_fields = [
            field_name
            for field_name in CLINICALLY_DECISIVE_FIELDS
            if _is_present(decisive_payload.get(field_name))
        ][:8]
    clinically_sufficient = bool(changed_fields)
    return {
        "available": bool(field_values),
        "field_values": field_values,
        "field_sources": field_sources,
        "source_priority": list(TRUTH_PRIORITY),
        "superseded_inputs": superseded_inputs,
        "latest_clinically_decisive_visit": {
            "source_type": decisive_source,
            "visit_date": decisive_date,
            "fields_changed": changed_fields,
            "clinically_sufficient": clinically_sufficient,
            "summary": (
                f"Última fuente decisiva: {decisive_source} {decisive_date}".strip()
                if decisive_date
                else "Sin visita decisiva todavía"
            ),
            "payload": decisive_payload,
        },
    }


def truth_value(patient: dict[str, Any], *field_names: str, default: Any = None) -> Any:
    snapshot = patient.get("longitudinal_truth_snapshot") or {}
    values = snapshot.get("field_values") or {}
    for field_name in field_names:
        if _is_present(values.get(field_name)):
            return values.get(field_name)
    return default


def truth_source(patient: dict[str, Any], field_name: str) -> dict[str, str]:
    snapshot = patient.get("longitudinal_truth_snapshot") or {}
    return dict((snapshot.get("field_sources") or {}).get(field_name) or {})
