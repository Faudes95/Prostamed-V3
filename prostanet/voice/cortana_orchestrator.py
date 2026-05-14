"""EPIC 21 Phase 2D — Cortana Orchestrator (intent router multi-turn).

Single entry point para Cortana voice. Clasifica intent del transcript y
dispatches a la fase correcta:

  intent: "intake"           → voice_intake_full_orchestrator
  intent: "patient_lookup"   → patient_name_resolver
  intent: "patient_qa"       → patient_qa_grounding o decision_aware_qa
  intent: "population_qa"    → population_query_safe
  intent: "small_talk"       → friendly fallback (no PHI access)

Multi-turn state: persisted en voice_encounter_sessions (existing table)
o en-memory si session no especificada.

Pipeline:
  user voice → STT → transcript → classify_cortana_intent() →
    appropriate handler → tts_response + audit_log

Authorization scope checks delegated to each handler.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ─────────────────── Intent classification ───────────────────


# Patterns ordered by specificity (most specific first)
_INTAKE_PATTERNS = [
    r"\b(?:ay[úu]dame|cortana)\s+(?:a|con)?\s*(?:el\s+)?(?:ingresar|ingreso|capturar|registrar)",
    r"\bnuevo\s+paciente\b",
    r"\bvoy\s+a\s+(?:dictarte|dictarle|registrar)",
    r"\bingreso\s+(?:de\s+)?paciente",
    r"\bhelp\s+me\s+(?:enter|register|onboard)\b",
]

_LOOKUP_PATTERNS = [
    r"\babre\s+(?:el\s+)?(?:paciente|expediente|perfil)",
    r"\bbusca?\s+(?:a\s+|al\s+)?(?:paciente|persona)",
    r"\bencu[eé]ntra(?:me)?\s+(?:al\s+)?paciente",
    r"\bperfil\s+(?:de\s+)?(?:paciente)?",
    r"\bopen\s+(?:patient|profile)\b",
    r"\bfind\s+patient\b",
    r"\bnss\s+\d{4,}",
]

_DECISION_PATTERNS = [
    # "Cuál es/sería la mejor opción"
    r"\bcu[áa]l\b.{0,25}\bmejor\b",
    r"\bcu[áa]l\b.{0,25}\bopci[óo]n\b",
    r"\bqu[eé]\s+(?:tratamiento|terapia|opci[óo]n|hacer)\b",
    r"\brecomendar(?:[ií]as|[ií]a)?\b",
    r"\b(?:siguiente|pr[óo]ximo|next)\s+paso\b",
    r"\bdeber[ií]a\s+(?:operar|tratar|biopsy|radiar)",
    r"\bcandidato\s+(?:a|para)\b",
    r"\bes\s+candidato\b",
    r"\bwhat\s+(?:treatment|option|next|should)\b",
    r"\brecommend(?:ation)?\b",
]

_POPULATION_PATTERNS = [
    r"\bcu[áa]ntos?\s+pacientes\b",
    r"\bcu[áa]ntos\b.{0,30}\b(?:tenemos|hay|son)\b",
    r"\bcu[áa]ntos\b.{0,30}\b(?:operar|operable|biopsy|tratar)\b",
    r"\bcu[áa]ntos\b.{0,30}\b(?:mcrpc|mcspc|localized|localizado|metast|crpc|cspc)\b",
    r"\bhow\s+many\s+patients\b",
    r"\bn[úu]mero\s+(?:de\s+)?pacientes\b",
    r"\blista\s+(?:de\s+)?pacientes\b",
    r"\b(?:audit|auditor[íi]a)\b",
]

_SMALL_TALK_PATTERNS = [
    r"\b(?:hola|hi|hello|buenos\s+d[íi]as|buenas\s+tardes|buen[oa]s)\b",
    r"\b(?:gracias|thanks|thank\s+you)\b",
    r"\bc[óo]mo\s+est[áa]s\b",
]

_INTENT_REGEXES = {
    "intake": [re.compile(p, re.IGNORECASE) for p in _INTAKE_PATTERNS],
    "patient_lookup": [re.compile(p, re.IGNORECASE) for p in _LOOKUP_PATTERNS],
    "decision_recommendation": [re.compile(p, re.IGNORECASE) for p in _DECISION_PATTERNS],
    "population_qa": [re.compile(p, re.IGNORECASE) for p in _POPULATION_PATTERNS],
    "small_talk": [re.compile(p, re.IGNORECASE) for p in _SMALL_TALK_PATTERNS],
}


def classify_cortana_intent(transcript: str) -> str:
    """Classify transcript into one of:
      - intake | patient_lookup | decision_recommendation | population_qa
      - patient_qa (factual lookup about specific patient)
      - small_talk
      - unknown
    """
    if not transcript:
        return "unknown"

    # Order matters: intake/lookup/decision/population first (specific),
    # then small_talk, then default to patient_qa if seems clinical
    for intent_name in ("intake", "population_qa", "decision_recommendation",
                         "patient_lookup", "small_talk"):
        regexes = _INTENT_REGEXES[intent_name]
        for pattern in regexes:
            if pattern.search(transcript):
                return intent_name

    # Heuristic: if mentions clinical terms (PSA, Gleason, etc.) → patient_qa
    clinical_signals = re.search(
        r"\b(?:psa|gleason|metastasis|adt|biopsy|nadir|grade|stage)\b",
        transcript, re.IGNORECASE,
    )
    if clinical_signals:
        return "patient_qa"

    return "unknown"


# ─────────────────── Orchestration result ───────────────────


@dataclass
class CortanaOrchestrationResult:
    """Result of Cortana intent routing + dispatch."""
    available: bool
    intent: str
    transcript: str
    handler: str  # which sub-handler was invoked
    handler_result: dict[str, Any] = field(default_factory=dict)
    tts_response: str = ""
    session_id: str = ""
    multi_turn_state: dict[str, Any] = field(default_factory=dict)
    audit_log_entry: dict[str, Any] = field(default_factory=dict)


# ─────────────────── Main entry point ───────────────────


def orchestrate_cortana(
    transcript: str,
    *,
    patient_nss: str | None = None,
    session_id: str | None = None,
    multi_turn_state: dict[str, Any] | None = None,
    language: str = "es",
) -> CortanaOrchestrationResult:
    """Single entry point for Cortana voice intent routing.

    Args:
        transcript: STT output text
        patient_nss: optional patient context (for QA + decision_recommendation)
        session_id: optional session ID for multi-turn state persistence
        multi_turn_state: optional state from previous turn
        language: TTS language

    Returns:
        CortanaOrchestrationResult with handler invoked + tts_response.
    """
    intent = classify_cortana_intent(transcript)
    result = CortanaOrchestrationResult(
        available=True,
        intent=intent,
        transcript=transcript,
        handler="",
        session_id=session_id or "",
        multi_turn_state=dict(multi_turn_state or {}),
    )

    # Dispatch
    if intent == "intake":
        result = _handle_intake(result, transcript, language)
    elif intent == "patient_lookup":
        result = _handle_patient_lookup(result, transcript, language)
    elif intent == "decision_recommendation":
        if patient_nss:
            result = _handle_decision_aware_qa(result, patient_nss, transcript, language)
        else:
            result.handler = "decision_recommendation_missing_context"
            result.tts_response = (
                "Necesito que primero abras un paciente para darte una recomendación clínica. "
                "Por ejemplo: 'Abre el paciente Juan García'."
                if language == "es" else
                "Please open a patient first before requesting a recommendation."
            )
    elif intent == "patient_qa":
        if patient_nss:
            result = _handle_patient_qa(result, patient_nss, transcript, language)
        else:
            result.handler = "patient_qa_missing_context"
            result.tts_response = (
                "Para responder, primero debo abrir el perfil del paciente. "
                "¿De qué paciente hablamos?"
                if language == "es" else
                "I need to open the patient profile first. Which patient?"
            )
    elif intent == "population_qa":
        result = _handle_population_qa(result, transcript, language)
    elif intent == "small_talk":
        result.handler = "small_talk"
        result.tts_response = (
            "Hola, soy Cortana clínica. Puedo ayudarte con: ingreso de paciente, "
            "búsqueda por nombre, preguntas sobre un paciente abierto, o consultas "
            "de cohorte. ¿En qué te ayudo?"
            if language == "es" else
            "Hello, I'm clinical Cortana. I can help with: patient intake, lookup, "
            "questions about an open patient, or cohort queries."
        )
    else:
        result.handler = "unknown_intent"
        result.tts_response = (
            "No estoy segura qué necesitas. ¿Quieres ingresar un paciente, buscar uno, "
            "preguntar algo clínico, o consultar la cohorte?"
            if language == "es" else
            "I'm not sure what you need. Want to enter a patient, search, ask clinical, or query cohort?"
        )

    result.audit_log_entry = {
        "transcript": transcript,
        "intent": intent,
        "handler": result.handler,
        "patient_nss": patient_nss,
        "tts_response": result.tts_response,
    }
    return result


# ─────────────────── Handlers ───────────────────


def _handle_intake(
    result: CortanaOrchestrationResult,
    transcript: str,
    language: str,
) -> CortanaOrchestrationResult:
    """Dispatch to voice_intake_full_orchestrator."""
    try:
        from prostanet.voice.voice_intake_full_orchestrator import (
            orchestrate_full_intake,
            result_to_dict,
        )
        orchestrator_result = orchestrate_full_intake(
            transcript,
            multi_turn_state=result.multi_turn_state,
            language=language,
        )
        result.handler = "voice_intake_full_orchestrator"
        result.handler_result = result_to_dict(orchestrator_result)
        result.multi_turn_state = orchestrator_result.multi_turn_state
        # Build TTS
        completeness = orchestrator_result.completeness_pct
        count = len(orchestrator_result.candidates)
        result.tts_response = (
            f"Capturé {count} campos. Completitud al {completeness:.0f}%. "
            f"{orchestrator_result.next_dictation_prompt}"
        )
    except Exception as exc:
        logger.error("intake handler failed: %s", exc)
        result.handler = "intake_error"
        result.tts_response = "No pude procesar el dictado. Por favor intenta de nuevo."
    return result


def _handle_patient_lookup(
    result: CortanaOrchestrationResult,
    transcript: str,
    language: str,
) -> CortanaOrchestrationResult:
    """Dispatch to patient_name_resolver."""
    try:
        from prostanet.voice.patient_name_resolver import (
            resolve_patient_by_name,
            candidates_to_response,
        )
        candidates = resolve_patient_by_name(transcript)
        response = candidates_to_response(candidates, transcript)
        result.handler = "patient_name_resolver"
        result.handler_result = response
        result.tts_response = response.get("tts_response", "")
    except Exception as exc:
        logger.error("lookup handler failed: %s", exc)
        result.handler = "lookup_error"
        result.tts_response = "Error buscando paciente. Por favor intenta de nuevo."
    return result


def _handle_patient_qa(
    result: CortanaOrchestrationResult,
    patient_nss: str,
    transcript: str,
    language: str,
) -> CortanaOrchestrationResult:
    """Dispatch to patient_qa_grounding."""
    try:
        import tracking_db
        patient_record = tracking_db.get_patient_full_record(patient_nss)
        if not patient_record:
            result.handler = "patient_qa_record_not_found"
            result.tts_response = f"No encontré record para paciente {patient_nss}."
            return result
        from prostanet.voice.patient_qa_grounding import (
            answer_patient_question,
            grounded_answer_to_dict,
        )
        answer = answer_patient_question(patient_record, transcript)
        result.handler = "patient_qa_grounding"
        result.handler_result = grounded_answer_to_dict(answer)
        result.tts_response = answer.answer_validated
    except Exception as exc:
        logger.error("patient_qa handler failed: %s", exc)
        result.handler = "qa_error"
        result.tts_response = "Error procesando pregunta. Por favor consulta el record manualmente."
    return result


def _handle_decision_aware_qa(
    result: CortanaOrchestrationResult,
    patient_nss: str,
    transcript: str,
    language: str,
) -> CortanaOrchestrationResult:
    """Dispatch to decision_aware_qa (invokes copilots)."""
    try:
        import tracking_db
        patient_record = tracking_db.get_patient_full_record(patient_nss)
        if not patient_record:
            result.handler = "decision_qa_record_not_found"
            result.tts_response = f"No encontré record para paciente {patient_nss}."
            return result
        from prostanet.voice.decision_aware_qa import (
            build_decision_aware_answer,
            decision_answer_to_dict,
        )
        answer = build_decision_aware_answer(patient_record, transcript)
        result.handler = "decision_aware_qa"
        result.handler_result = decision_answer_to_dict(answer)
        result.tts_response = answer.answer_validated
    except Exception as exc:
        logger.error("decision_qa handler failed: %s", exc)
        result.handler = "decision_qa_error"
        result.tts_response = "Error procesando decisión clínica. Consulta el perfil manualmente."
    return result


def _handle_population_qa(
    result: CortanaOrchestrationResult,
    transcript: str,
    language: str,
) -> CortanaOrchestrationResult:
    """Dispatch to population_query_safe."""
    try:
        from prostanet.voice.population_query_safe import (
            answer_population_question,
            cohort_result_to_dict,
        )
        cohort_result = answer_population_question(transcript)
        result.handler = "population_query_safe"
        result.handler_result = cohort_result_to_dict(cohort_result)
        result.tts_response = cohort_result.tts_response
    except Exception as exc:
        logger.error("population_qa handler failed: %s", exc)
        result.handler = "population_qa_error"
        result.tts_response = "Error consultando la cohorte. Por favor intenta de nuevo."
    return result


def orchestration_to_dict(result: CortanaOrchestrationResult) -> dict[str, Any]:
    """Serialize for JSON response."""
    return asdict(result)


__all__ = [
    "CortanaOrchestrationResult",
    "classify_cortana_intent",
    "orchestrate_cortana",
    "orchestration_to_dict",
]
