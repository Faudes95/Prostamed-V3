from __future__ import annotations

from copy import deepcopy
from typing import Any


PRIORITY_LABELS = {
    "preferred": "preferente",
    "eligible": "elegible",
    "selected_candidate": "candidato seleccionado",
    "guideline-consistent": "alineado con las guías",
    "observation_preferred": "observación preferente",
    "not_preferred": "no preferente",
    "not_recommended": "no recomendado",
}


def _clean_list(items: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


def _treatment_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    name = str(item.get("name", "")).strip()
    notes = str(item.get("notes", "")).strip()
    priority = PRIORITY_LABELS.get(str(item.get("priority", "")).strip(), str(item.get("priority", "")).strip())
    if notes and priority:
        return f"{name}: {notes} Prioridad clínica: {priority}."
    if notes:
        return f"{name}: {notes}"
    if priority:
        return f"{name}: prioridad clínica {priority}."
    return name


def _treatment_name(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("name", "")).strip()
    return ""


def enrich_evaluation_result(
    result: dict[str, Any],
    *,
    clinical_title: str,
    case_summary: str,
    recommended_trajectory: str,
    personalized_fundamentals: list[str],
    alternatives: list[str] | None = None,
    shared_decision_message: str = "",
    comparison_message: str | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(result)
    nccn_primary = enriched.setdefault("nccn_primary", {})
    preferred_regimen = dict(enriched.get("preferred_frontline_regimen") or {})
    eligible_treatments = enriched.get("eligible_treatments", [])
    alternative_regimens = list(enriched.get("alternative_regimens") or [])
    derived_alternatives = [_treatment_text(item) for item in (alternative_regimens or eligible_treatments[1:3])]
    not_prioritized = enriched.get("not_recommended", [])
    durations = enriched.get("durations_and_conditions", [])
    missing = enriched.get("missing_critical_inputs", [])
    contraindications = enriched.get("contraindications", [])

    nccn_primary["titulo_clinico"] = clinical_title
    nccn_primary["resumen_del_caso"] = case_summary
    nccn_primary["trayectoria_recomendada"] = recommended_trajectory
    nccn_primary["fundamentos_personalizados"] = _clean_list(personalized_fundamentals)
    nccn_primary["alternativas_razonables"] = _clean_list(alternatives or derived_alternatives)
    nccn_primary["tratamientos_no_priorizados"] = _clean_list(not_prioritized)
    nccn_primary["condiciones_y_duracion"] = _clean_list(durations)
    nccn_primary["advertencias_y_datos_faltantes"] = _clean_list(
        [*missing, *contraindications]
    )
    nccn_primary["mensaje_para_toma_de_decisiones_compartida"] = shared_decision_message.strip()
    primary_treatment = _treatment_name(preferred_regimen)
    if not primary_treatment and eligible_treatments:
        primary_treatment = _treatment_name(eligible_treatments[0])
    nccn_primary["tratamiento_principal"] = primary_treatment

    eau_comparison = enriched.setdefault("eau_comparison", {})
    eau_comparison["explicacion_breve"] = (
        comparison_message
        or eau_comparison.get("comparison", {}).get("summary")
        or eau_comparison.get("recommendation", "")
    )

    report_sections = enriched.setdefault("report_sections", {})
    report_sections["summary"] = case_summary
    report_sections["structured_summary"] = {
        "titulo_clinico": nccn_primary["titulo_clinico"],
        "resumen_del_caso": nccn_primary["resumen_del_caso"],
        "trayectoria_recomendada": nccn_primary["trayectoria_recomendada"],
        "fundamentos_personalizados": nccn_primary["fundamentos_personalizados"],
        "alternativas_razonables": nccn_primary["alternativas_razonables"],
        "tratamientos_no_priorizados": nccn_primary["tratamientos_no_priorizados"],
        "condiciones_y_duracion": nccn_primary["condiciones_y_duracion"],
        "advertencias_y_datos_faltantes": nccn_primary["advertencias_y_datos_faltantes"],
        "mensaje_para_toma_de_decisiones_compartida": nccn_primary["mensaje_para_toma_de_decisiones_compartida"],
    }
    return enriched


def normalize_legacy_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(result)
    nccn_primary = normalized.setdefault("nccn_primary", {})
    report_sections = normalized.setdefault("report_sections", {})
    if "titulo_clinico" in nccn_primary:
        normalized.setdefault("eau_comparison", {}).setdefault(
            "explicacion_breve",
            normalized.get("eau_comparison", {}).get("comparison", {}).get("summary", ""),
        )
        report_sections.setdefault("structured_summary", {
            "titulo_clinico": nccn_primary.get("titulo_clinico", ""),
            "resumen_del_caso": nccn_primary.get("resumen_del_caso", report_sections.get("summary", "")),
            "trayectoria_recomendada": nccn_primary.get("trayectoria_recomendada", nccn_primary.get("recommendation", "")),
            "fundamentos_personalizados": nccn_primary.get("fundamentos_personalizados", []),
            "alternativas_razonables": nccn_primary.get("alternativas_razonables", []),
            "tratamientos_no_priorizados": nccn_primary.get("tratamientos_no_priorizados", []),
            "condiciones_y_duracion": nccn_primary.get("condiciones_y_duracion", []),
            "advertencias_y_datos_faltantes": nccn_primary.get("advertencias_y_datos_faltantes", []),
            "mensaje_para_toma_de_decisiones_compartida": nccn_primary.get("mensaje_para_toma_de_decisiones_compartida", ""),
        })
        return normalized

    eligible_treatments = normalized.get("eligible_treatments", [])
    alternatives = [_treatment_text(item) for item in eligible_treatments[1:3]]
    summary = report_sections.get("summary") or nccn_primary.get("recommendation", "")
    normalized["nccn_primary"] = {
        **nccn_primary,
        "titulo_clinico": f"Ruta clínica priorizada para {nccn_primary.get('label', 'este escenario clínico')}",
        "resumen_del_caso": summary,
        "trayectoria_recomendada": nccn_primary.get("recommendation", ""),
        "fundamentos_personalizados": _clean_list(nccn_primary.get("reasons", []) or [summary]),
        "alternativas_razonables": _clean_list(alternatives),
        "tratamientos_no_priorizados": _clean_list(normalized.get("not_recommended", [])),
        "condiciones_y_duracion": _clean_list(normalized.get("durations_and_conditions", [])),
        "advertencias_y_datos_faltantes": _clean_list(
            [*normalized.get("missing_critical_inputs", []), *normalized.get("contraindications", [])]
        ),
        "mensaje_para_toma_de_decisiones_compartida": "La recomendación debe integrarse con las preferencias del paciente, la reserva funcional y la factibilidad local del tratamiento.",
        "tratamiento_principal": _treatment_name(eligible_treatments[0]) if eligible_treatments else "",
    }
    normalized.setdefault("eau_comparison", {})["explicacion_breve"] = (
        normalized.get("eau_comparison", {}).get("comparison", {}).get("summary")
        or normalized.get("eau_comparison", {}).get("recommendation", "")
    )
    report_sections["summary"] = summary
    report_sections["structured_summary"] = {
        "titulo_clinico": normalized["nccn_primary"]["titulo_clinico"],
        "resumen_del_caso": normalized["nccn_primary"]["resumen_del_caso"],
        "trayectoria_recomendada": normalized["nccn_primary"]["trayectoria_recomendada"],
        "fundamentos_personalizados": normalized["nccn_primary"]["fundamentos_personalizados"],
        "alternativas_razonables": normalized["nccn_primary"]["alternativas_razonables"],
        "tratamientos_no_priorizados": normalized["nccn_primary"]["tratamientos_no_priorizados"],
        "condiciones_y_duracion": normalized["nccn_primary"]["condiciones_y_duracion"],
        "advertencias_y_datos_faltantes": normalized["nccn_primary"]["advertencias_y_datos_faltantes"],
        "mensaje_para_toma_de_decisiones_compartida": normalized["nccn_primary"]["mensaje_para_toma_de_decisiones_compartida"],
    }
    return normalized
