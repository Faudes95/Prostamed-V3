from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from prostanet.domains.patient_tracking.therapy_catalog import (
    REGIMEN_LOOKUP,
    normalize_regimen_code,
    regimen_label,
)
from prostanet.shared.utc_time import utc_now_iso


ARPI_AGENT_KEYS = {
    "ABIRATERONA": "ABIRATERONE",
    "ABIRATERONE": "ABIRATERONE",
    "ENZALUTAMIDA": "ENZALUTAMIDE",
    "ENZALUTAMIDE": "ENZALUTAMIDE",
    "APALUTAMIDA": "APALUTAMIDE",
    "APALUTAMIDE": "APALUTAMIDE",
    "DAROLUTAMIDA": "DAROLUTAMIDE",
    "DAROLUTAMIDE": "DAROLUTAMIDE",
}

NON_ARPI_AGENT_KEYS = {
    "DOCETAXEL": "DOCETAXEL",
    "CABAZITAXEL": "CABAZITAXEL",
    "OLAPARIB": "OLAPARIB",
    "TALAZOPARIB": "TALAZOPARIB",
    "NIRAPARIB": "NIRAPARIB",
    "PEMBROLIZUMAB": "PEMBROLIZUMAB",
    "PEMBROLIZUMAB": "PEMBROLIZUMAB",
    "RADIUM-223": "RADIUM_223",
    "RADIUM 223": "RADIUM_223",
    "RA-223": "RADIUM_223",
    "LU-177-PSMA": "LU177_PSMA",
    "LU177-PSMA": "LU177_PSMA",
    "LUTECIO-177-PSMA": "LU177_PSMA",
}

ARPI_PRICE_AGENT_CODES = {"ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE"}
UNRESOLVED_BACKBONE_COMPONENTS = {"ADT", "LHRH", "GNRH", "CASTRATION"}
PRICE_CURRENT_MAX_AGE_DAYS = 540
PRICE_REVIEW_MAX_AGE_DAYS = 730

DOSE_4_ALERT = {
    "severity": "warning",
    "code": "unit_dose_4_referral_planning",
    "title": "Alerta temprana de referencia",
    "message": "Realizar envio a HGZ o HGR para continuar con tratamiento establecido.",
    "recommended_action": "Preparar referencia HGZ/HGR y documentar destino operativo.",
}

DOSE_6_ALERT = {
    "severity": "critical",
    "code": "unit_dose_6_max_local_course",
    "title": "Maximo de dosis otorgadas en esta unidad",
    "message": "Paciente con maximo de dosis otorgadas en esta unidad. Priorizar envio a HGZ o HGR.",
    "recommended_action": "Priorizar envio a HGZ/HGR; si continua en la unidad, documentar justificacion.",
}


def regimen_intensity(regimen_code: Any) -> dict[str, Any]:
    """Classify a regimen as mono/doublet/triplet without changing therapy logic."""
    code = normalize_regimen_code(regimen_code)
    regimen = REGIMEN_LOOKUP.get(code, {})
    agents = [str(agent) for agent in regimen.get("agents") or [] if str(agent or "").strip()]
    component_count = len(agents)
    if component_count >= 3:
        intensity = "triplet"
        label = "Triplete"
    elif component_count == 2:
        intensity = "doublet"
        label = "Doblete"
    elif component_count == 1:
        intensity = "monotherapy"
        label = "Monoterapia"
    else:
        intensity = "unknown"
        label = "No clasificado"
    return {
        "regimen_code": code,
        "regimen_label": regimen_label(code),
        "therapy_class": regimen.get("therapy_class", ""),
        "agents": agents,
        "component_count": component_count,
        "intensity": intensity,
        "intensity_label": label,
        "is_arpi_regimen": any(_agent_price_key(agent) in ARPI_AGENT_KEYS.values() for agent in agents),
    }


def dose_alert_for_local_count(local_dose_count: Any) -> dict[str, Any]:
    count = _safe_int(local_dose_count, 0)
    if count >= 6:
        return {**DOSE_6_ALERT, "local_dose_count": count}
    if count >= 4:
        return {**DOSE_4_ALERT, "local_dose_count": count}
    return {
        "severity": "none",
        "code": "unit_dose_count_in_range",
        "title": "Sin alerta de referencia por dosis",
        "message": "",
        "recommended_action": "",
        "local_dose_count": count,
    }


def estimate_regimen_cost(
    regimen_code: Any,
    price_catalog_rows: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    intensity = regimen_intensity(regimen_code)
    prices_by_agent: dict[str, Mapping[str, Any]] = {}
    for row in price_catalog_rows or []:
        agent_key = _agent_price_key(row.get("agent_code") or row.get("agent_name"))
        if agent_key:
            prices_by_agent.setdefault(agent_key, row)

    priced_components: list[dict[str, Any]] = []
    missing_components: list[str] = []
    missing_arpi_components: list[str] = []
    missing_non_arpi_components: list[str] = []
    unpriced_backbone_components: list[str] = []
    total = 0.0
    arpi_total = 0.0
    for agent in intensity["agents"]:
        key = _agent_price_key(agent)
        row = prices_by_agent.get(key)
        if not row:
            if key in ARPI_PRICE_AGENT_CODES:
                missing_arpi_components.append(agent)
                missing_components.append(agent)
            elif _is_unresolved_backbone_component(key):
                unpriced_backbone_components.append(agent)
            else:
                missing_non_arpi_components.append(agent)
                missing_components.append(agent)
            continue
        unit_price = _safe_float(row.get("unit_price_mxn"), None)
        if unit_price is None:
            if key in ARPI_PRICE_AGENT_CODES:
                missing_arpi_components.append(agent)
            else:
                missing_non_arpi_components.append(agent)
            missing_components.append(agent)
            continue
        total += unit_price
        if key in ARPI_PRICE_AGENT_CODES:
            arpi_total += unit_price
        source_freshness = _price_source_freshness(row)
        priced_components.append(
            {
                "agent": agent,
                "agent_code": key,
                "component_scope": "arpi" if key in ARPI_PRICE_AGENT_CODES else "non_arpi",
                "unit_price_mxn": round(unit_price, 2),
                "package_label": row.get("package_label") or row.get("unit_label") or "",
                "source_label": row.get("source_label") or "",
                "source_url": row.get("source_url") or "",
                "source_date": row.get("source_date") or "",
                "confidence": row.get("confidence") or "",
                "source_freshness": source_freshness,
            }
        )

    has_arpi_component = any(_agent_price_key(agent) in ARPI_PRICE_AGENT_CODES for agent in intensity["agents"])
    arpi_priced_components = [
        item for item in priced_components if item.get("component_scope") == "arpi"
    ]
    non_arpi_priced_components = [
        item for item in priced_components if item.get("component_scope") != "arpi"
    ]
    stale_components = [
        item["agent_code"]
        for item in priced_components
        if item.get("source_freshness", {}).get("status") in {"stale", "unknown_date"}
    ]
    stale_arpi_components = [
        item["agent_code"]
        for item in arpi_priced_components
        if item.get("source_freshness", {}).get("status") in {"stale", "unknown_date"}
    ]
    if not has_arpi_component:
        coverage_status = "no_arpi_component"
        confidence = "not_applicable"
    elif not arpi_priced_components:
        coverage_status = "unpriced"
        confidence = "missing_price"
    elif missing_arpi_components:
        coverage_status = "partial"
        confidence = "partial_price"
    elif stale_arpi_components:
        coverage_status = "priced_with_stale_source"
        confidence = "priced_stale_source"
    else:
        coverage_status = "priced_full"
        confidence = "priced_current_source"
    if not priced_components:
        total_coverage_status = "unpriced"
    elif missing_components or unpriced_backbone_components:
        total_coverage_status = "partial"
    elif stale_components:
        total_coverage_status = "priced_with_stale_source"
    else:
        total_coverage_status = "priced_full"
    if non_arpi_priced_components:
        cost_scope = (
            "Auditable medication component spend for priced regimen components; "
            "ADT backbone, labs, infusion, visits and administration costs remain excluded unless individually priced."
        )
        cost_basis = "priced_medication_package_or_cycle_sum_by_component"
    else:
        cost_scope = (
            "ARPI component spend only; ADT, docetaxel, labs, infusion, visits and administration costs "
            "are excluded unless a source-traceable catalog price exists."
        )
        cost_basis = "arpi_package_or_cycle_sum_by_component"
    return {
        "regimen_code": intensity["regimen_code"],
        "regimen_label": intensity["regimen_label"],
        "estimated_cost_mxn": round(total, 2) if priced_components else None,
        "estimated_total_regimen_cost_mxn": round(total, 2) if priced_components else None,
        "estimated_arpi_cost_mxn": round(arpi_total, 2) if arpi_priced_components else None,
        "priced_components": priced_components,
        "priced_arpi_components": arpi_priced_components,
        "priced_non_arpi_components": non_arpi_priced_components,
        "missing_components": missing_components,
        "missing_arpi_components": missing_arpi_components,
        "missing_non_arpi_components": missing_non_arpi_components,
        "unpriced_backbone_components": unpriced_backbone_components,
        "non_arpi_components_excluded": unpriced_backbone_components + missing_non_arpi_components,
        "stale_price_components": stale_components,
        "is_partial": bool(missing_components or unpriced_backbone_components),
        "coverage_status": coverage_status,
        "medication_total_coverage_status": total_coverage_status,
        "cost_confidence": confidence,
        "currency": "MXN",
        "cost_basis": cost_basis,
        "cost_scope": cost_scope,
        "computed_at": utc_now_iso(),
    }


def build_price_catalog_audit(
    price_catalog_rows: Iterable[Mapping[str, Any]] | None,
    *,
    as_of: date | str | None = None,
    required_agents: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Audit ARPI price coverage and source freshness.

    This is a governance layer for operational estimates. It intentionally
    separates "we have a usable estimate" from "this is the current hospital
    procurement price", which requires local purchasing validation.
    """
    required = sorted({_agent_price_key(agent) for agent in (required_agents or ARPI_PRICE_AGENT_CODES)})
    required = [agent for agent in required if agent in ARPI_PRICE_AGENT_CODES]
    rows_by_agent: dict[str, Mapping[str, Any]] = {}
    for row in price_catalog_rows or []:
        agent_key = _agent_price_key(row.get("agent_code") or row.get("agent_name"))
        if agent_key in ARPI_PRICE_AGENT_CODES and agent_key not in rows_by_agent:
            rows_by_agent[agent_key] = row

    audited_rows: list[dict[str, Any]] = []
    missing_agents: list[str] = []
    stale_agents: list[str] = []
    review_agents: list[str] = []
    unknown_date_agents: list[str] = []
    for agent in required:
        row = rows_by_agent.get(agent)
        if not row:
            missing_agents.append(agent)
            continue
        freshness = _price_source_freshness(row, as_of=as_of)
        status = freshness["status"]
        if status == "stale":
            stale_agents.append(agent)
        elif status == "review_soon":
            review_agents.append(agent)
        elif status == "unknown_date":
            unknown_date_agents.append(agent)
        audited_rows.append(
            {
                "agent_code": agent,
                "agent_name": row.get("agent_name") or agent,
                "unit_price_mxn": _safe_float(row.get("unit_price_mxn"), None),
                "package_label": row.get("package_label") or "",
                "source_label": row.get("source_label") or "",
                "source_url": row.get("source_url") or "",
                "source_date": row.get("source_date") or "",
                "effective_start": row.get("effective_start") or "",
                "confidence": row.get("confidence") or "",
                "source_freshness": freshness,
            }
        )

    if missing_agents:
        catalog_status = "incomplete"
    elif stale_agents or unknown_date_agents:
        catalog_status = "complete_with_stale_or_unknown_sources"
    elif review_agents:
        catalog_status = "complete_review_soon"
    else:
        catalog_status = "complete_current"

    warnings: list[str] = []
    if missing_agents:
        warnings.append("Faltan precios ARPI para: " + ", ".join(missing_agents))
    if stale_agents:
        warnings.append("Fuentes de precio vencidas o antiguas para: " + ", ".join(stale_agents))
    if unknown_date_agents:
        warnings.append("Fuentes sin fecha auditable para: " + ", ".join(unknown_date_agents))
    if review_agents:
        warnings.append("Fuentes cercanas a ventana de revision para: " + ", ".join(review_agents))

    return {
        "catalog_status": catalog_status,
        "required_agents": required,
        "priced_agents": sorted(rows_by_agent),
        "missing_agents": missing_agents,
        "stale_agents": stale_agents,
        "review_agents": review_agents,
        "unknown_date_agents": unknown_date_agents,
        "coverage_count": len(required) - len(missing_agents),
        "required_count": len(required),
        "coverage_pct": round(((len(required) - len(missing_agents)) / len(required)) * 100, 2) if required else 100.0,
        "current_max_age_days": PRICE_CURRENT_MAX_AGE_DAYS,
        "review_max_age_days": PRICE_REVIEW_MAX_AGE_DAYS,
        "warnings": warnings,
        "rows": audited_rows,
        "computed_at": utc_now_iso(),
        "audit_note": (
            "Catalogo para gasto operativo estimado. Confirmar contra compra hospitalaria vigente "
            "antes de usarlo como auditoria financiera formal."
        ),
    }


def build_treatment_course_summary(
    patient: Mapping[str, Any],
    *,
    price_catalog_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    treatments = list(patient.get("treatments") or [])
    doses = list(patient.get("treatment_doses") or [])
    current = _latest_active_treatment(treatments)
    if not current:
        return {
            "available": False,
            "reason": "Sin tratamiento sistemico activo documentado.",
            "current_course": {},
            "dose_alert": dose_alert_for_local_count(0),
            "cost_summary": {"estimated_total_spend_mxn": 0.0, "priced_doses": 0},
        }

    treatment_id = current.get("id")
    current_doses = [
        dose for dose in doses
        if str(dose.get("treatment_history_id") or "") == str(treatment_id or "")
        or normalize_regimen_code(dose.get("regimen_code")) == normalize_regimen_code(current.get("drug_scheme"))
    ]
    local_doses = [
        dose for dose in current_doses
        if str(dose.get("administered_in_unit", "1")).lower() not in {"0", "false", "no"}
    ]
    imported_local = _safe_int((current.get("regimen") or {}).get("local_doses_recorded_at_start"), 0)
    prior_external = _safe_int((current.get("regimen") or {}).get("doses_received_before_unit"), 0)
    local_count = max(len(local_doses), imported_local)
    global_count = prior_external + local_count
    latest_dose = sorted(
        local_doses,
        key=lambda item: (str(item.get("dose_date") or ""), int(_safe_int(item.get("id"), 0))),
        reverse=True,
    )
    cost_rows = [
        _safe_float(dose.get("estimated_cost_mxn"), None)
        for dose in current_doses
        if _safe_float(dose.get("estimated_cost_mxn"), None) is not None
    ]
    regimen_cost = estimate_regimen_cost(current.get("drug_scheme"), price_catalog_rows)
    total_medication_rows: list[float] = []
    for dose in current_doses:
        dose_cost = _safe_float(dose.get("estimated_cost_mxn"), None)
        total_from_source = None
        source = dose.get("cost_source") if isinstance(dose.get("cost_source"), Mapping) else None
        if source is None:
            source = dose.get("cost_estimate") if isinstance(dose.get("cost_estimate"), Mapping) else None
        if source is None and dose.get("cost_source_json"):
            try:
                parsed_source = json.loads(str(dose.get("cost_source_json") or "{}"))
                source = parsed_source if isinstance(parsed_source, Mapping) else None
            except (TypeError, ValueError):
                source = None
        if source:
            total_from_source = _safe_float(source.get("estimated_total_regimen_cost_mxn"), None)
        if total_from_source is None and dose_cost is not None:
            total_from_source = _safe_float(regimen_cost.get("estimated_total_regimen_cost_mxn"), None)
        total_medication_rows.append(
            total_from_source if total_from_source is not None else (dose_cost or 0.0)
        )
    current_course = {
        "treatment_history_id": treatment_id,
        "line_of_therapy_number": current.get("line_of_therapy_number") or current.get("line_of_therapy"),
        "line_of_therapy_context": current.get("line_of_therapy_context") or "",
        "regimen_code": normalize_regimen_code(current.get("drug_scheme")),
        "regimen_label": current.get("drug_scheme_label") or regimen_label(current.get("drug_scheme")),
        "start_date": current.get("start_date") or "",
        "outcome": current.get("outcome") or "",
        "intensity": regimen_intensity(current.get("drug_scheme")),
        "doses_received_before_unit": prior_external,
        "local_dose_count": local_count,
        "global_dose_count": global_count,
        "latest_local_dose_date": latest_dose[0].get("dose_date") if latest_dose else "",
        "unit_name": (current.get("regimen") or {}).get("unit_name") or "",
        "referral_target": (current.get("regimen") or {}).get("referral_target") or "",
    }
    return {
        "available": True,
        "current_course": current_course,
        "dose_alert": dose_alert_for_local_count(local_count),
        "regimen_cost_estimate": regimen_cost,
        "cost_summary": {
            "estimated_total_spend_mxn": round(sum(value for value in cost_rows if value is not None), 2),
            "estimated_total_medication_spend_mxn": round(sum(total_medication_rows), 2),
            "estimated_cost_per_dose_mxn": regimen_cost.get("estimated_total_regimen_cost_mxn") or regimen_cost.get("estimated_cost_mxn"),
            "estimated_arpi_cost_per_dose_mxn": regimen_cost.get("estimated_arpi_cost_mxn"),
            "priced_doses": len(cost_rows),
            "dose_count": len(current_doses),
            "is_partial": regimen_cost.get("is_partial", True),
            "price_coverage_status": regimen_cost.get("coverage_status", ""),
            "medication_total_coverage_status": regimen_cost.get("medication_total_coverage_status", ""),
            "cost_confidence": regimen_cost.get("cost_confidence", ""),
            "missing_arpi_components": regimen_cost.get("missing_arpi_components", []),
            "missing_non_arpi_components": regimen_cost.get("missing_non_arpi_components", []),
            "unpriced_backbone_components": regimen_cost.get("unpriced_backbone_components", []),
            "priced_components": regimen_cost.get("priced_components", []),
            "priced_arpi_components": regimen_cost.get("priced_arpi_components", []),
            "priced_non_arpi_components": regimen_cost.get("priced_non_arpi_components", []),
            "stale_price_components": regimen_cost.get("stale_price_components", []),
            "cost_scope": regimen_cost.get("cost_scope", ""),
        },
    }


def _latest_active_treatment(treatments: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not treatments:
        return None
    active = [
        item for item in treatments
        if str(item.get("outcome") or "").strip().lower() in {"", "ongoing", "activo", "curso · activo"}
        and not item.get("end_date")
    ]
    pool = active or treatments
    return sorted(
        pool,
        key=lambda item: (str(item.get("start_date") or ""), int(_safe_int(item.get("id"), 0))),
        reverse=True,
    )[0]


def _agent_price_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = text.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    return ARPI_AGENT_KEYS.get(text) or NON_ARPI_AGENT_KEYS.get(text) or text


def _is_unresolved_backbone_component(value: Any) -> bool:
    return _agent_price_key(value) in UNRESOLVED_BACKBONE_COMPONENTS


def _price_source_freshness(row: Mapping[str, Any], *, as_of: date | str | None = None) -> dict[str, Any]:
    source_date = _parse_date(row.get("source_date")) or _parse_date(row.get("effective_start"))
    as_of_date = _parse_date(as_of) or date.today()
    if source_date is None:
        return {"status": "unknown_date", "age_days": None, "as_of": as_of_date.isoformat()}
    age_days = (as_of_date - source_date).days
    if age_days <= PRICE_CURRENT_MAX_AGE_DAYS:
        status = "current"
    elif age_days <= PRICE_REVIEW_MAX_AGE_DAYS:
        status = "review_soon"
    else:
        status = "stale"
    return {
        "status": status,
        "age_days": age_days,
        "as_of": as_of_date.isoformat(),
        "source_date": source_date.isoformat(),
    }


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            parsed = datetime.strptime(text[:length], fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1)
            if fmt == "%Y-%m":
                return date(parsed.year, parsed.month, 1)
            return parsed.date()
        except ValueError:
            continue
    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
