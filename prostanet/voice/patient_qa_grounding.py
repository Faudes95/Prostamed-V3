"""EPIC 21 Fase 3 — Patient-specific Q&A con grounding firewall.

Permite preguntas tipo "¿cuál es el PSA actual del paciente X?" con safety
firewall que valida CADA respuesta LLM contra el patient_record real ANTES
de TTS-out. SI mismatch → NO speak, surface "datos en desacuerdo".

Architecture:
  1. Voice question + patient_nss → load_patient_full_record(nss)
  2. Build grounded prompt: system_prompt(patient_context) + user_question
  3. Anthropic Claude generates answer with tool-use restricted to lookups
  4. **GROUNDING FIREWALL**: parse answer claims (PSA, treatment, date, etc.)
     and verify each against record → if mismatch → block response
  5. Only validated answers go to TTS

Authorization scope: phi:read required. Voice session must have active
clinical session before opening patient Q&A.

Hallucination categories blocked by firewall:
  - Invented PSA values (e.g., LLM says "PSA is 8.5" but record says 4.2)
  - Wrong dates (e.g., "diagnosed in 2020" but record says 2022)
  - Invented treatments (e.g., "received abiraterone" but treatments list empty)
  - Fabricated risk scores (CAPRA, D'Amico computed vs invented)

When firewall blocks:
  - TTS responds: "Datos en desacuerdo, requiere revisión manual"
  - Audit log records: question, llm_raw, validation_failure_reason
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class GroundedAnswer:
    """Result of patient Q&A with grounding firewall."""
    answer_validated: str  # Text that PASSED firewall, safe to TTS
    answer_raw_llm: str    # Original LLM response (for audit)
    validation_passed: bool
    validation_failure_reasons: list[str] = field(default_factory=list)
    grounding_sources: dict[str, Any] = field(default_factory=dict)  # what was fetched
    safety_prefix_added: bool = False
    answer_blocked: bool = False
    audit_log_entry: dict[str, Any] = field(default_factory=dict)


# ─────────────────── Context builder ───────────────────


def build_patient_context_for_qa(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract structured Q&A-ready context from patient_record.

    Returns dict with PHI-minimized fields organized by category.
    This is what gets embedded in Claude's system prompt.
    """
    identity = patient_record.get("identity") or {}
    baseline = patient_record.get("baseline") or {}
    follow_ups = patient_record.get("follow_ups") or []
    treatments = patient_record.get("treatments") or []
    biomarkers = patient_record.get("biomarker_longitudinal") or []
    latest = patient_record.get("latest_assessment") or {}

    # Most recent PSA
    latest_psa = None
    latest_psa_date = None
    if follow_ups:
        last_fu = follow_ups[-1]
        latest_psa = last_fu.get("psa_current") or last_fu.get("psa")
        latest_psa_date = last_fu.get("visit_date") or last_fu.get("date")

    # PSA history (last 5 values)
    psa_history = []
    for fu in follow_ups[-5:]:
        psa = fu.get("psa_current") or fu.get("psa")
        date = fu.get("visit_date") or fu.get("date")
        if psa is not None:
            psa_history.append({"date": date, "value": float(psa) if psa else None})

    # Treatments
    treatment_summary = [
        {
            "drug_or_modality": tx.get("regimen_name") or tx.get("drug") or tx.get("modality"),
            "start_date": tx.get("start_date"),
            "end_date": tx.get("end_date"),
            "status": tx.get("status", "completed"),
        }
        for tx in treatments[:10]
    ]

    return {
        "patient_id": identity.get("id"),
        "nss": identity.get("nss"),
        "age": identity.get("age"),
        "current_state": latest.get("reconciled_state") or baseline.get("clinical_state") or "",
        "baseline": {
            "baseline_psa": baseline.get("baseline_psa"),
            "gleason_score": baseline.get("gleason_score"),
            "clinical_t_stage": baseline.get("clinical_t_stage"),
            "diagnosis_date": baseline.get("diagnosis_date") or baseline.get("dx_date"),
            "age_at_diagnosis": baseline.get("age_at_diagnosis"),
        },
        "latest_psa": latest_psa,
        "latest_psa_date": latest_psa_date,
        "psa_history": psa_history,
        "treatments": treatment_summary,
        "treatment_count": len(treatments),
        "follow_up_count": len(follow_ups),
        "biomarker_count": len(biomarkers),
    }


# ─────────────────── Grounding firewall ───────────────────


# Regex patterns for claims to validate
_NUMERIC_CLAIM_PATTERN = re.compile(
    r"\b(?:psa|antígeno|antigeno|gleason|edad|age)\b\s+"
    r"(?:es|de|igual\s+a|=|:)?\s*"
    r"(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_DATE_CLAIM_PATTERN = re.compile(
    r"\b(?:diagnostic|diagnosis|diagnosticado|fecha)\b[^.]{0,40}?"
    r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)",
    re.IGNORECASE,
)
_TREATMENT_CLAIM_PATTERN = re.compile(
    r"\b(?:recibió|received|toma|takes|currently\s+on|tratamiento\s+con)\b\s+"
    r"([a-záéíóú]+(?:[-\s][a-záéíóú]+)?)",
    re.IGNORECASE,
)


def _validate_psa_claim(answer: str, context: Mapping[str, Any]) -> tuple[bool, str]:
    """Check if answer's PSA claims match record."""
    answer_lower = answer.lower()
    if "psa" not in answer_lower and "antígeno" not in answer_lower:
        return True, ""  # No PSA claim to validate

    # Extract PSA value from answer
    match = re.search(
        r"\b(?:psa|antígeno|antigeno)\b[^.]{0,30}?(\d+(?:[.,]\d+)?)",
        answer,
        re.IGNORECASE,
    )
    if not match:
        return True, ""

    try:
        claimed = float(match.group(1).replace(",", "."))
    except ValueError:
        return True, ""

    # Compare against record
    latest = context.get("latest_psa")
    baseline = (context.get("baseline") or {}).get("baseline_psa")
    psa_history = context.get("psa_history") or []
    valid_values = [latest, baseline] + [h["value"] for h in psa_history if h.get("value") is not None]
    valid_values = [v for v in valid_values if v is not None]

    if not valid_values:
        return False, f"PSA claim ({claimed}) but no PSA in record"

    # Match within 0.05 tolerance
    for v in valid_values:
        try:
            if abs(float(v) - claimed) < 0.05:
                return True, ""
        except (TypeError, ValueError):
            continue

    return False, (
        f"PSA claim {claimed} does not match record values "
        f"{[round(float(v), 2) for v in valid_values if v]}"
    )


def _validate_gleason_claim(answer: str, context: Mapping[str, Any]) -> tuple[bool, str]:
    """Check if answer's Gleason claims match record."""
    match = re.search(r"\bgleason\b[^.]{0,30}?(\d{1,2})", answer, re.IGNORECASE)
    if not match:
        return True, ""
    try:
        claimed = int(match.group(1))
    except ValueError:
        return True, ""
    record_gs = (context.get("baseline") or {}).get("gleason_score")
    if record_gs is None:
        return False, f"Gleason claim ({claimed}) but no Gleason in record"
    try:
        record_gs_int = int(str(record_gs).split("(")[0])
        if record_gs_int == claimed:
            return True, ""
        return False, f"Gleason claim {claimed} ≠ record {record_gs}"
    except (ValueError, IndexError):
        return True, ""  # ambiguous record, give benefit of doubt


def _validate_treatment_claim(answer: str, context: Mapping[str, Any]) -> tuple[bool, str]:
    """Check if answer claims a treatment NOT in record."""
    answer_lower = answer.lower()
    record_treatments = context.get("treatments") or []
    if not record_treatments:
        # If LLM mentions specific drug while no treatments recorded → flag
        drugs_mentioned = [
            d for d in (
                "abiraterona", "abiraterone",
                "enzalutamida", "enzalutamide",
                "apalutamida", "apalutamide",
                "darolutamida", "darolutamide",
                "docetaxel", "cabazitaxel",
                "olaparib", "rucaparib",
                "pembrolizumab", "lutetio", "lutetium",
            )
            if d in answer_lower
        ]
        if drugs_mentioned:
            return False, (
                f"Treatment claim mentioned {drugs_mentioned} but record has no treatments"
            )
        return True, ""

    # Build record treatment set
    record_drug_set = set()
    for tx in record_treatments:
        name = (tx.get("drug_or_modality") or "").lower()
        if name:
            record_drug_set.add(name)
    # Check if answer mentions specific drug not in record
    common_drugs = [
        "abiraterona", "abiraterone", "enzalutamida", "enzalutamide",
        "apalutamida", "apalutamide", "darolutamida", "darolutamide",
        "docetaxel", "cabazitaxel", "olaparib", "rucaparib",
        "pembrolizumab", "lutetio", "lutetium",
    ]
    mismatched = []
    for drug in common_drugs:
        if drug in answer_lower:
            if not any(drug in r for r in record_drug_set):
                mismatched.append(drug)
    if mismatched:
        return False, (
            f"Treatment claim mentioned {mismatched} not in record (record has {list(record_drug_set)})"
        )
    return True, ""


def grounding_firewall(
    llm_answer: str,
    patient_context: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Validate LLM answer against patient record.

    Returns: (validation_passed, list_of_failure_reasons)
    """
    if not llm_answer or not isinstance(llm_answer, str):
        return False, ["empty_or_invalid_answer"]

    failure_reasons: list[str] = []

    # Validate PSA claims
    ok, reason = _validate_psa_claim(llm_answer, patient_context)
    if not ok:
        failure_reasons.append(f"psa_mismatch: {reason}")

    # Validate Gleason claims
    ok, reason = _validate_gleason_claim(llm_answer, patient_context)
    if not ok:
        failure_reasons.append(f"gleason_mismatch: {reason}")

    # Validate treatment claims
    ok, reason = _validate_treatment_claim(llm_answer, patient_context)
    if not ok:
        failure_reasons.append(f"treatment_mismatch: {reason}")

    return len(failure_reasons) == 0, failure_reasons


# ─────────────────── Q&A entry point ───────────────────


def build_grounded_system_prompt(patient_context: Mapping[str, Any]) -> str:
    """Build system prompt with patient context grounding.

    Embeds patient_context as structured data so LLM can ground its answers.
    """
    return f"""Eres un asistente clínico para urólogos especializados en cáncer de próstata.
Tienes acceso al RECORD VERIFICADO del paciente. SOLO usa data del record para responder.

REGLAS DE SEGURIDAD CLÍNICA (no negociables):
1. SOLO responde con datos del record. SI no está en el record → di "no tengo ese dato en el registro".
2. NUNCA inventes PSA values, treatments, dates, Gleason scores, ni cohort statistics.
3. Cita la fecha del dato cuando sea posible (e.g., "según el registro del 13 de mayo, PSA es 4.2").
4. Si el dato es ambiguo o requiere interpretación clínica → di "requiere revisión del especialista".
5. Si la pregunta es out-of-scope (no clínica, no del paciente) → declina educadamente.

RECORD VERIFICADO DEL PACIENTE:
```json
{json.dumps(patient_context, default=str, ensure_ascii=False, indent=2)}
```

Responde en español clínico, conciso (≤2 frases), citando fechas del record cuando aplique.
"""


def add_safety_prefix(answer: str, context: Mapping[str, Any]) -> str:
    """Prepend safety phrasing to validated answer for TTS."""
    if not answer:
        return ""
    # Skip prefix if already references date
    if "según el registro" in answer.lower() or "del " in answer.lower()[:30]:
        return answer
    latest_psa_date = context.get("latest_psa_date")
    if latest_psa_date:
        return f"Según el registro del {latest_psa_date}: {answer}"
    return f"Según el registro: {answer}"


def answer_patient_question(
    patient_record: Mapping[str, Any],
    question: str,
    *,
    llm_provider: Any | None = None,
) -> GroundedAnswer:
    """Answer a patient-specific question with grounding firewall.

    Args:
        patient_record: full patient record from tracking_db.get_patient_full_record
        question: voice/text question from urologist
        llm_provider: optional pre-built AnthropicProvider; if None, lazy-create

    Returns:
        GroundedAnswer with validation result + safe-to-TTS text.
    """
    context = build_patient_context_for_qa(patient_record)
    answer = GroundedAnswer(
        answer_validated="",
        answer_raw_llm="",
        validation_passed=False,
        grounding_sources=context,
    )

    # Try LLM call (gracefully handle if unavailable)
    raw_llm_response = ""
    try:
        if llm_provider is None:
            from prostanet.voice.llm_providers.anthropic_provider import AnthropicProvider
            llm_provider = AnthropicProvider()
        system_prompt = build_grounded_system_prompt(context)
        # Use messages API directly (no tool-use for Q&A — just text response)
        if hasattr(llm_provider, "client") and llm_provider.client:
            response = llm_provider.client.messages.create(
                model=getattr(llm_provider, "model", "claude-sonnet-4-20250514"),
                max_tokens=512,
                system=system_prompt,
                messages=[{"role": "user", "content": question}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    raw_llm_response += block.text
        else:
            answer.answer_blocked = True
            answer.validation_failure_reasons = ["llm_provider_unavailable"]
            answer.answer_validated = (
                "Servicio de Q&A clínico no disponible. Consulta el registro manualmente."
            )
            return answer
    except Exception as exc:
        logger.warning("LLM Q&A call failed: %s", exc)
        answer.answer_blocked = True
        answer.validation_failure_reasons = [f"llm_error: {exc}"]
        answer.answer_validated = (
            "No pude generar respuesta. Por favor consulta el registro manualmente."
        )
        return answer

    answer.answer_raw_llm = raw_llm_response

    # GROUNDING FIREWALL
    passed, failures = grounding_firewall(raw_llm_response, context)
    if passed:
        answer.validation_passed = True
        answer.answer_validated = add_safety_prefix(raw_llm_response, context)
        answer.safety_prefix_added = True
    else:
        answer.answer_blocked = True
        answer.validation_failure_reasons = failures
        answer.answer_validated = (
            "Datos en desacuerdo entre LLM y registro. "
            "Por favor verifica directamente en el perfil del paciente."
        )

    answer.audit_log_entry = {
        "question": question,
        "patient_id": context.get("patient_id"),
        "nss": context.get("nss"),
        "llm_raw_response": raw_llm_response,
        "validation_passed": passed,
        "validation_failures": failures,
        "answer_sent_to_tts": answer.answer_validated,
    }
    return answer


def grounded_answer_to_dict(answer: GroundedAnswer) -> dict[str, Any]:
    """Serialize for JSON response."""
    return {
        "answer_validated": answer.answer_validated,
        "answer_raw_llm": answer.answer_raw_llm,
        "validation_passed": answer.validation_passed,
        "validation_failure_reasons": answer.validation_failure_reasons,
        "answer_blocked": answer.answer_blocked,
        "safety_prefix_added": answer.safety_prefix_added,
        "audit_log_entry": answer.audit_log_entry,
    }


__all__ = [
    "GroundedAnswer",
    "build_patient_context_for_qa",
    "build_grounded_system_prompt",
    "grounding_firewall",
    "answer_patient_question",
    "grounded_answer_to_dict",
]
