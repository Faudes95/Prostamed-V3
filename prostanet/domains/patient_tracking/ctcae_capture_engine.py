# -*- coding: utf-8 -*-
"""
CTCAE Capture Engine — EPIC 6.

Orquesta la captura estructurada de eventos adversos CTCAE v5.0, genera
narrativas para profile_compass y emite alertas cuando aparecen eventos
grado ≥3 o patrones de toxicidad que requieren acción.

El motor:
  * Valida eventos contra ``ctcae_v5.PROSTATE_CTCAE_TERMS``.
  * Normaliza tanto eventos nuevos (``ctcae_events`` bundle) como eventos
    heredados (``peripheral_neuropathy_grade``, ``neutropenia_grade``,
    ``fatigue_grade``) para back-compat con EPIC 3.
  * Agrega la carga de toxicidad vía ``aggregate_toxicity_burden``.
  * Emite ``CTCAECaptureResult`` serializable a dict.

Reutiliza:
  * ``ctcae_v5.record_adverse_event``, ``aggregate_toxicity_burden``,
    ``PROSTATE_CTCAE_TERMS``, ``validate_toxicity_event``.
  * ``alert_engine.ClinicalAlert`` para alertas clínicas formales.

Referencia:
  * NCI Common Terminology Criteria for Adverse Events v5.0 (2017)
  * NCCN Prostate v5.2026 — toxicity management en secciones de tratamiento
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from prostanet.shared.ctcae_v5 import (
    PROSTATE_CTCAE_TERMS,
    CTCAEValidationError,
    ToxicityEvent,
    aggregate_toxicity_burden,
    record_adverse_event,
    validate_toxicity_list,
)


# Mapeo de campos grade heredados → término CTCAE canónico
LEGACY_GRADE_FIELDS: dict[str, dict[str, str]] = {
    "peripheral_neuropathy_grade": {
        "term": "peripheral_neuropathy",
        "category": "neurologic",
        "common_agents": "docetaxel, cabazitaxel",
    },
    "neutropenia_grade": {
        "term": "neutropenia",
        "category": "hematologic",
        "common_agents": "docetaxel, cabazitaxel",
    },
    "anemia_grade": {
        "term": "anemia",
        "category": "hematologic",
        "common_agents": "docetaxel, ADT, abiraterona",
    },
    "thrombocytopenia_grade": {
        "term": "thrombocytopenia",
        "category": "hematologic",
        "common_agents": "docetaxel, olaparib, cabazitaxel",
    },
    "fatigue_grade": {
        "term": "fatigue",
        "category": "neurologic",
        "common_agents": "ADT, enzalutamida, abiraterona",
    },
    "diarrhea_grade": {
        "term": "diarrhea",
        "category": "gastrointestinal",
        "common_agents": "abiraterona, docetaxel",
    },
    "rash_grade": {
        "term": "rash",
        "category": "dermatologic",
        "common_agents": "apalutamida, enzalutamida",
    },
    "seizure_grade": {
        "term": "seizure",
        "category": "neurologic",
        "common_agents": "enzalutamida, apalutamida",
    },
    "hypertension_grade": {
        "term": "hypertension",
        "category": "cardiovascular",
        "common_agents": "abiraterona, ADT",
    },
    "alt_elevation_grade": {
        "term": "alt_increased",
        "category": "hepatic",
        "common_agents": "abiraterona, enzalutamida",
    },
    "ast_elevation_grade": {
        "term": "ast_increased",
        "category": "hepatic",
        "common_agents": "abiraterona, enzalutamida",
    },
}


@dataclass
class CTCAECaptureResult:
    """Resultado integral de la captura CTCAE."""

    events: list[dict[str, Any]]
    burden: dict[str, Any]
    narrative: str
    tone: str  # "success" | "info" | "warning" | "danger"
    alerts: list[dict[str, Any]] = field(default_factory=list)
    legacy_fields_imported: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helpers privados ─────────────────────────────────────────────────────


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _infer_agent_from_current_treatment(patient: dict[str, Any]) -> str:
    """Intenta inferir el agente sospechoso a partir del tratamiento activo."""
    treatment = str(patient.get("current_treatment") or patient.get("current_therapy") or "").strip().lower()
    if not treatment:
        return ""
    mapping = {
        "docetaxel": "docetaxel",
        "cabazitaxel": "cabazitaxel",
        "abiraterone": "abiraterona",
        "abiraterona": "abiraterona",
        "enzalutamide": "enzalutamida",
        "enzalutamida": "enzalutamida",
        "apalutamide": "apalutamida",
        "apalutamida": "apalutamida",
        "darolutamide": "darolutamida",
        "darolutamida": "darolutamida",
        "olaparib": "olaparib",
        "talazoparib": "talazoparib",
        "rucaparib": "rucaparib",
        "radium": "Ra-223",
        "ra223": "Ra-223",
        "lutetium": "Lu-177",
        "lu-177": "Lu-177",
        "pembrolizumab": "pembrolizumab",
        "adt": "ADT",
    }
    for key, agent in mapping.items():
        if key in treatment:
            return agent
    return ""


def _import_legacy_grade_fields(patient: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Convierte campos grade heredados en eventos CTCAE normalizados.

    Backward-compat para schemas EPIC 3 (``peripheral_neuropathy_grade`` etc.)
    que todavía almacenan la toxicidad como entero.
    """
    imported: list[dict[str, Any]] = []
    legacy_names: list[str] = []
    inferred_agent = _infer_agent_from_current_treatment(patient)
    for field_name, meta in LEGACY_GRADE_FIELDS.items():
        raw = patient.get(field_name)
        grade = _safe_int(raw)
        if grade is None or grade < 1 or grade > 5:
            continue
        imported.append({
            "term": meta["term"],
            "grade": grade,
            "category": meta["category"],
            "attribution": "possible",
            "agent_suspected": inferred_agent or meta.get("common_agents", "").split(",")[0].strip(),
            "action_taken": "none",
            "notes": f"Importado desde {field_name}={grade}",
        })
        legacy_names.append(field_name)
    return imported, legacy_names


def _merge_events(
    structured: list[dict[str, Any]],
    legacy: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evita duplicar el mismo término si ya existe un evento estructurado.

    Si un término ya aparece en ``structured`` (mismo valor normalizado),
    se omite el legacy para no duplicar la señal.
    """
    known_terms: set[str] = set()
    for ev in structured:
        term = str(ev.get("term") or "").strip().lower()
        if term:
            known_terms.add(term)
    merged = list(structured)
    for ev in legacy:
        term = str(ev.get("term") or "").strip().lower()
        if term in known_terms:
            continue
        merged.append(ev)
        known_terms.add(term)
    return merged


# ── API pública ──────────────────────────────────────────────────────────


def capture_ctcae_events(patient: dict[str, Any]) -> CTCAECaptureResult:
    """Captura todos los eventos CTCAE de un paciente.

    Ingresa:
      * ``ctcae_events``: lista estructurada (nuevo formato EPIC 6).
      * Campos legacy (``*_grade``): se auto-importan como CTCAE events.

    Devuelve:
      ``CTCAECaptureResult`` con la lista unificada, carga agregada y
      alertas derivadas.
    """
    raw_events = patient.get("ctcae_events") or []
    if not isinstance(raw_events, list):
        raw_events = []

    validation_errors: list[str] = []
    structured_dicts: list[dict[str, Any]] = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            validation_errors.append(f"Evento ignorado (no es dict): {type(ev).__name__}")
            continue
        try:
            validated = validate_toxicity_list([ev])[0]
            structured_dicts.append(validated.to_dict())
        except CTCAEValidationError as exc:
            validation_errors.append(f"Evento inválido ({ev.get('term')}): {exc}")

    legacy_events, legacy_fields = _import_legacy_grade_fields(patient)
    merged = _merge_events(structured_dicts, legacy_events)

    burden = aggregate_toxicity_burden(merged)

    tone = burden.get("burden_tone", "info")
    narrative = burden.get("narrative", "")

    alerts: list[dict[str, Any]] = []

    # Alertas por evento grado ≥3 sin acción registrada
    for event in burden.get("events_requiring_action", []):
        term = event.get("term", "")
        es_label = PROSTATE_CTCAE_TERMS.get(term, {}).get("es", term.title())
        alerts.append({
            "type": "ctcae_grade3_no_action",
            "severity": "warning",
            "term": term,
            "grade": event.get("grade"),
            "category": event.get("category"),
            "message": (
                f"{es_label} grado {event.get('grade')} sin modificación de dosis "
                f"registrada — agente sospechoso: {event.get('agent_suspected') or 'no especificado'}"
            ),
            "recommended_action": "Valorar reducción / pausa de dosis y evaluar criterios de soporte",
        })

    # Alertas por eventos críticos (grado ≥4)
    for event in burden.get("critical_events", []):
        term = event.get("term", "")
        es_label = PROSTATE_CTCAE_TERMS.get(term, {}).get("es", term.title())
        alerts.append({
            "type": "ctcae_critical",
            "severity": "critical",
            "term": term,
            "grade": event.get("grade"),
            "category": event.get("category"),
            "message": (
                f"{es_label} grado {event.get('grade')} — evento crítico que puede "
                "requerir hospitalización / suspensión definitiva"
            ),
            "recommended_action": (
                "Evaluar hospitalización; manejo por oncología + especialidad afectada; "
                "considerar suspensión definitiva del agente"
            ),
        })

    # Alertas por agentes repetidamente implicados (≥3 eventos)
    agents = burden.get("agents_suspected", {})
    for agent, count in agents.items():
        if count >= 3:
            alerts.append({
                "type": "ctcae_agent_overburden",
                "severity": "warning",
                "agent": agent,
                "count": count,
                "message": (
                    f"{agent} implicado en {count} eventos adversos — considerar cambio "
                    "de línea o ajuste profiláctico"
                ),
                "recommended_action": "Revisar balance beneficio/toxicidad y alternativas de línea",
            })

    return CTCAECaptureResult(
        events=merged,
        burden=burden,
        narrative=narrative,
        tone=tone,
        alerts=alerts,
        legacy_fields_imported=legacy_fields,
        validation_errors=validation_errors,
    )


def add_ctcae_event(
    patient: dict[str, Any],
    event: dict[str, Any],
) -> tuple[list[dict[str, Any]], ToxicityEvent]:
    """Agrega un evento CTCAE validado a la lista del paciente.

    Retorna:
      * ``events``: lista serializada de eventos validados (incluyendo el nuevo).
      * ``new_event``: el ``ToxicityEvent`` recién agregado.

    No persiste; el caller se encarga de guardar en el paciente.
    """
    existing = patient.get("ctcae_events") or []
    full_list, fresh = record_adverse_event(existing, event)
    serialized = [ev.to_dict() for ev in full_list]
    return serialized, fresh


__all__ = [
    "CTCAECaptureResult",
    "LEGACY_GRADE_FIELDS",
    "add_ctcae_event",
    "capture_ctcae_events",
]
