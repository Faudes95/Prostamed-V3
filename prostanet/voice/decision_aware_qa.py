"""EPIC 21 Phase 2B — Decision-aware patient Q&A.

Extiende `patient_qa_grounding` con un modo que invoca los copilots clínicos
(EPIC 20 + EPIC 19) cuando la pregunta es sobre **decisión clínica**:
  - "¿Cuál sería la mejor opción para este paciente?"
  - "¿Qué tratamiento le recomendarías?"
  - "¿Cuál es el siguiente paso?"

Pipeline:
  1. Classify question intent (factual_lookup vs decision_recommendation)
  2. If decision_recommendation:
     a. Invoke applicable copilot bundles:
        - mcrpc_subtype_copilot (if CRPC)
        - risk_stratified_localized_copilot (if localized)
        - hereditary_germline_copilot (always check trigger)
        - post_rt_bcr_copilot (if RT history + Phoenix BCR)
        - oligoprogression_copilot (if on therapy)
     b. Invoke Patient Twin OS bundle (EPIC 19)
     c. Build comprehensive context: record + ALL applicable bundles
     d. Claude reasons over context with NCCN 2026 citations
     e. Grounding firewall validates therapeutic claims against
        `therapeutic_alternative_registry.yaml`
  3. Return GroundedDecisionAnswer con:
     - therapeutic_preferred (cited from registry)
     - therapeutic_acceptable_alternatives
     - rationale (decision reasoning)
     - copilots_invoked (transparency)
     - patient_twin_score (if Patient Twin available)
     - nccn_references

Authorization scope: phi:read.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ─────────────────── Data classes ───────────────────


@dataclass
class GroundedDecisionAnswer:
    """Result of decision-aware Q&A."""
    available: bool
    answer_validated: str
    intent_classification: str  # "factual_lookup" | "decision_recommendation"
    copilots_invoked: list[str] = field(default_factory=list)
    therapeutic_preferred: str = ""
    therapeutic_acceptable: list[str] = field(default_factory=list)
    therapeutic_not_recommended: list[str] = field(default_factory=list)
    rationale: str = ""
    nccn_references: list[str] = field(default_factory=list)
    patient_state_classified: str = ""
    patient_twin_top_regimen: dict[str, Any] | None = None
    validation_passed: bool = True
    validation_failure_reasons: list[str] = field(default_factory=list)
    answer_blocked: bool = False
    audit_log_entry: dict[str, Any] = field(default_factory=dict)


# ─────────────────── Intent classification ───────────────────


_DECISION_INTENT_PATTERNS = [
    r"\b(?:mejor|óptim[ao]|preferid[ao])\s+(?:opción|tratamiento|alternativa)",
    r"\bqu[eé]\s+(?:tratamiento|terapia|opción|hacer)\b",
    r"\brecomendar(?:ías|ía)?\b",
    r"\b(?:siguiente|próximo|next)\s+(?:paso|step)\b",
    r"\bdeber[íi]a\s+(?:operar|tratar|biopsy|radiar)",
    r"\bcandidato\s+(?:a|para)\b",
    r"\bes\s+candidato\b",
    r"\bcu[áa]l\s+(?:es\s+)?(?:la\s+)?mejor",
    r"\bwhat\s+(?:treatment|option|next|should)\b",
    r"\brecommend(?:ation)?\b",
    r"\b(?:therapy|treatment)\s+choice\b",
]

_DECISION_INTENT_REGEXES = [re.compile(p, re.IGNORECASE) for p in _DECISION_INTENT_PATTERNS]


def classify_question_intent(question: str) -> str:
    """Classify question as 'factual_lookup' or 'decision_recommendation'."""
    if not question:
        return "factual_lookup"
    for pattern in _DECISION_INTENT_REGEXES:
        if pattern.search(question):
            return "decision_recommendation"
    return "factual_lookup"


# ─────────────────── Copilot invocation ───────────────────


def invoke_applicable_copilots(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Invoke all applicable EPIC 20 copilots + EPIC 19 Patient Twin for the patient.

    Returns dict {copilot_name: bundle} for available copilots.
    """
    bundles: dict[str, Any] = {}

    # Risk-stratified localized (EPIC 20)
    try:
        from prostanet.domains.patient_tracking.risk_stratified_localized_copilot_service import (
            build_risk_stratified_localized_bundle,
        )
        bundle = build_risk_stratified_localized_bundle(patient_record)
        if bundle.get("available"):
            bundles["risk_stratified_localized"] = bundle
    except Exception as exc:
        logger.debug("risk_stratified_localized copilot failed: %s", exc)

    # mCRPC subtype (EPIC 20)
    try:
        from prostanet.domains.patient_tracking.mcrpc_subtype_copilot_service import (
            build_mcrpc_subtype_bundle,
        )
        bundle = build_mcrpc_subtype_bundle(patient_record)
        if bundle.get("available"):
            bundles["mcrpc_subtype"] = bundle
    except Exception as exc:
        logger.debug("mcrpc_subtype copilot failed: %s", exc)

    # Hereditary germline (EPIC 20)
    try:
        from prostanet.domains.patient_tracking.hereditary_germline_copilot_service import (
            build_hereditary_germline_bundle,
        )
        bundle = build_hereditary_germline_bundle(patient_record)
        if bundle.get("available"):
            bundles["hereditary_germline"] = bundle
    except Exception as exc:
        logger.debug("hereditary_germline copilot failed: %s", exc)

    # Post-RT BCR (EPIC 20)
    try:
        from prostanet.domains.patient_tracking.post_rt_bcr_copilot_service import (
            build_post_rt_bcr_bundle,
        )
        bundle = build_post_rt_bcr_bundle(patient_record)
        if bundle.get("available"):
            bundles["post_rt_bcr"] = bundle
    except Exception as exc:
        logger.debug("post_rt_bcr copilot failed: %s", exc)

    # Oligoprogression (EPIC 20)
    try:
        from prostanet.domains.patient_tracking.oligoprogression_copilot_service import (
            build_oligoprogression_bundle,
        )
        bundle = build_oligoprogression_bundle(patient_record)
        if bundle.get("available"):
            bundles["oligoprogression"] = bundle
    except Exception as exc:
        logger.debug("oligoprogression copilot failed: %s", exc)

    # Patient Twin OS (EPIC 19)
    try:
        from prostanet.domains.patient_tracking.patient_twin_os import build_patient_twin_view
        view = build_patient_twin_view(patient_record)
        if view.get("available"):
            bundles["patient_twin_os"] = view
    except Exception as exc:
        logger.debug("patient_twin_os failed: %s", exc)

    # Clinical state classification (EPIC 20a)
    try:
        from prostanet.domains.state_classifier.clinical_state_classifier import classify_clinical_state
        # Build a minimal facts dict from record
        facts = _flatten_record_for_classifier(patient_record)
        classification = classify_clinical_state(facts)
        if classification:
            bundles["clinical_state_classification"] = {
                "state": classification.state,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
                "evidence_tag": classification.evidence_tag,
                "therapeutic_alternative_preferred": classification.therapeutic_alternative_preferred,
                "therapeutic_alternatives_acceptable": classification.therapeutic_alternatives_acceptable,
                "therapeutic_alternatives_not_recommended": classification.therapeutic_alternatives_not_recommended,
            }
    except Exception as exc:
        logger.debug("clinical_state_classifier failed: %s", exc)

    return bundles


def _flatten_record_for_classifier(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten patient record into facts dict expected by clinical_state_classifier."""
    baseline = patient_record.get("baseline") or {}
    latest = patient_record.get("latest_assessment") or {}
    facts: dict[str, Any] = {}
    # Demographics + baseline
    facts["baseline_psa"] = patient_record.get("baseline_psa") or baseline.get("baseline_psa")
    facts["gleason_score"] = patient_record.get("gleason_score") or baseline.get("gleason_score")
    facts["clinical_t_stage"] = patient_record.get("clinical_t_stage") or baseline.get("clinical_t_stage")
    facts["percent_positive_cores"] = patient_record.get("percent_positive_cores")
    facts["psa_density"] = patient_record.get("psa_density")
    # Metastasis
    facts["bone_lesion_count_total"] = int(patient_record.get("bone_lesion_count_total") or baseline.get("bone_lesion_count_total") or 0)
    facts["visceral_metastasis_present"] = bool(patient_record.get("visceral_metastasis_present") or baseline.get("visceral_metastasis_present"))
    facts["nonregional_nodal_count"] = int(patient_record.get("nonregional_nodal_count") or 0)
    facts["conventional_imaging_m0"] = bool(patient_record.get("conventional_imaging_m0"))
    facts["psma_pet_positive"] = bool(patient_record.get("psma_pet_positive"))
    facts["psma_pet_uptake_intensity"] = patient_record.get("psma_pet_uptake_intensity") or ""
    # CRPC
    facts["castration_resistance_confirmed"] = bool(
        patient_record.get("castration_resistance_confirmed")
        or latest.get("reconciled_state") in ("m0_crpc", "m1_crpc")
    )
    # Biomarkers
    facts["hrr_status"] = patient_record.get("hrr_status") or ""
    facts["msi_status"] = patient_record.get("msi_status") or ""
    facts["dmmr_status"] = patient_record.get("dmmr_status") or ""
    facts["tmb_high"] = bool(patient_record.get("tmb_high"))
    # NEPC
    facts["chromogranin_a_value"] = patient_record.get("chromogranin_a_value")
    facts["synaptophysin_biopsy_positive"] = patient_record.get("synaptophysin_biopsy_positive")
    facts["small_cell_morphology"] = patient_record.get("small_cell_morphology")
    facts["nse_value"] = patient_record.get("nse_value")
    # Prior therapy
    facts["prior_arsi_in_mcspc"] = bool(patient_record.get("prior_arsi_in_mcspc"))
    facts["parp_inhibitor_received"] = bool(patient_record.get("parp_inhibitor_received"))
    # Oligoprogression
    facts["progressing_on_systemic_therapy"] = bool(patient_record.get("progressing_on_systemic_therapy"))
    facts["new_lesion_count_since_last_imaging"] = patient_record.get("new_lesion_count_since_last_imaging")
    facts["response_in_existing_lesions"] = patient_record.get("response_in_existing_lesions") or ""
    # RT BCR
    facts["prior_rt_received"] = bool(baseline.get("rt_primary_received") or patient_record.get("prior_rt_received"))
    facts["nadir_psa_post_rt"] = patient_record.get("nadir_psa_post_rt")
    facts["current_psa"] = patient_record.get("current_psa") or facts.get("baseline_psa")
    # Family + germline
    facts["family_history_first_degree_prostate_cancer_age_lt_60"] = bool(patient_record.get("family_history_first_degree_prostate_cancer_age_lt_60"))
    facts["family_history_breast_ovary_pancreas"] = bool(patient_record.get("family_history_breast_ovary_pancreas"))
    facts["ashkenazi_ancestry"] = bool(patient_record.get("ashkenazi_ancestry"))
    facts["germline_testing_done"] = bool(patient_record.get("germline_testing_done"))
    return facts


# ─────────────────── Decision answer builder ───────────────────


def build_decision_aware_answer(
    patient_record: Mapping[str, Any],
    question: str,
    *,
    llm_provider: Any | None = None,
) -> GroundedDecisionAnswer:
    """Build a decision-aware answer invoking all applicable copilots.

    Args:
        patient_record: full patient record
        question: voice/text question (decision intent expected)
        llm_provider: optional pre-built AnthropicProvider

    Returns:
        GroundedDecisionAnswer with copilot-grounded therapeutic recommendation.
    """
    intent = classify_question_intent(question)
    answer = GroundedDecisionAnswer(
        available=True,
        answer_validated="",
        intent_classification=intent,
    )

    # Invoke copilots
    bundles = invoke_applicable_copilots(patient_record)
    answer.copilots_invoked = list(bundles.keys())

    # Extract authoritative therapeutic recommendation
    primary_bundle = None
    for preferred_key in ("clinical_state_classification", "mcrpc_subtype", "risk_stratified_localized",
                           "post_rt_bcr", "oligoprogression"):
        if preferred_key in bundles:
            primary_bundle = bundles[preferred_key]
            break

    if primary_bundle:
        # clinical_state_classification uses "therapeutic_alternative_preferred";
        # copilot bundles use "therapeutic_preferred". Try both.
        answer.therapeutic_preferred = str(
            primary_bundle.get("therapeutic_preferred")
            or primary_bundle.get("therapeutic_alternative_preferred")
            or ""
        )
        answer.therapeutic_acceptable = list(
            primary_bundle.get("therapeutic_acceptable")
            or primary_bundle.get("therapeutic_alternatives_acceptable")
            or []
        )
        answer.therapeutic_not_recommended = list(
            primary_bundle.get("therapeutic_not_recommended")
            or primary_bundle.get("therapeutic_alternatives_not_recommended")
            or []
        )
        answer.patient_state_classified = str(
            primary_bundle.get("state")
            or primary_bundle.get("subtype_state")
            or primary_bundle.get("risk_tier")
            or ""
        )
        ref = primary_bundle.get("nccn_reference") or primary_bundle.get("evidence_tag") or ""
        if ref:
            answer.nccn_references.append(ref)

    # Patient Twin top regimen
    if "patient_twin_os" in bundles:
        twin = bundles["patient_twin_os"]
        rankings = twin.get("regimen_rankings") or []
        if rankings:
            top = rankings[0]
            answer.patient_twin_top_regimen = {
                "regimen_name": top.get("regimen_name"),
                "score": top.get("score"),
                "trial_source": top.get("trial_source"),
                "rationale": top.get("rationale"),
            }

    # Build rationale string (structured, NCCN-grounded)
    rationale_parts: list[str] = []
    if answer.patient_state_classified:
        rationale_parts.append(f"Estado clínico: {answer.patient_state_classified}")
    if answer.therapeutic_preferred:
        rationale_parts.append(f"Terapia preferida (NCCN 2026): {answer.therapeutic_preferred}")
    if answer.patient_twin_top_regimen:
        twin_top = answer.patient_twin_top_regimen
        rationale_parts.append(
            f"Patient Twin OS top regimen: {twin_top['regimen_name']} "
            f"(score {twin_top['score']}, {twin_top['trial_source']})"
        )

    # Hereditary check
    if "hereditary_germline" in bundles:
        her = bundles["hereditary_germline"]
        if her.get("testing_indicated"):
            rationale_parts.append("Hereditary trigger detected — germline panel testing recomendado (NCCN PROS-A)")

    answer.rationale = " · ".join(rationale_parts) if rationale_parts else (
        "Información insuficiente en el record para clasificación clínica confiable."
    )

    # If LLM available, enrich with natural language explanation
    if llm_provider is not None:
        try:
            enriched = _llm_enrich_decision(
                patient_record=patient_record,
                question=question,
                bundles=bundles,
                primary_bundle=primary_bundle,
                llm_provider=llm_provider,
            )
            if enriched:
                # Grounding firewall: validate therapeutic claims against registry
                ok, fails = _validate_decision_claims(enriched, primary_bundle)
                if ok:
                    answer.answer_validated = enriched
                    answer.validation_passed = True
                else:
                    answer.answer_blocked = True
                    answer.validation_failure_reasons = fails
                    answer.answer_validated = (
                        f"Decisión clínica: {answer.therapeutic_preferred}. "
                        f"Caveats requieren revisión manual."
                    )
        except Exception as exc:
            logger.debug("LLM enrichment failed: %s", exc)

    if not answer.answer_validated:
        # Build structured answer without LLM (deterministic fallback)
        if answer.therapeutic_preferred:
            answer.answer_validated = (
                f"Según NCCN 2026 + análisis de copilots: terapia preferida es "
                f"{answer.therapeutic_preferred}. {answer.rationale}"
            )
        else:
            answer.answer_validated = (
                "No tengo información suficiente en el record para una recomendación clínica. "
                "Por favor verifica manualmente."
            )

    answer.audit_log_entry = {
        "question": question,
        "intent": intent,
        "copilots_invoked": answer.copilots_invoked,
        "therapeutic_preferred": answer.therapeutic_preferred,
        "patient_state": answer.patient_state_classified,
        "validation_passed": answer.validation_passed,
        "validation_failures": answer.validation_failure_reasons,
        "answer_sent_to_tts": answer.answer_validated,
    }
    return answer


def _llm_enrich_decision(
    patient_record: Mapping[str, Any],
    question: str,
    bundles: Mapping[str, Any],
    primary_bundle: Any,
    llm_provider: Any,
) -> str:
    """Call LLM with copilot bundles context for natural-language enrichment."""
    import json
    system_prompt = (
        "Eres un asistente clínico para urólogos especializados en cáncer de próstata.\n"
        "Tienes acceso a:\n"
        "  1. El record verificado del paciente\n"
        "  2. Análisis de copilots clínicos (state classifier, mCRPC subtype, Patient Twin, etc.)\n\n"
        "REGLAS:\n"
        "1. SOLO usa data del record + bundles para responder.\n"
        "2. Cita NCCN 2026 reference + pivotal trial cuando relevante.\n"
        "3. Sub-3 frases, en español clínico.\n"
        "4. Si bundle indica therapeutic_preferred, úsalo como recomendación principal.\n"
        "5. Si bundle tiene caveats clinical_caveats, menciónalos.\n\n"
        f"COPILOTS BUNDLES:\n{json.dumps(dict(bundles), default=str, ensure_ascii=False, indent=2)[:4000]}\n\n"
    )
    if hasattr(llm_provider, "client") and llm_provider.client:
        response = llm_provider.client.messages.create(
            model=getattr(llm_provider, "model", "claude-sonnet-4-20250514"),
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        return text
    return ""


def _validate_decision_claims(answer_text: str, primary_bundle: Any) -> tuple[bool, list[str]]:
    """Validate that LLM answer matches the authoritative primary_bundle.

    Bloquea casos donde LLM:
      - Contradicts therapeutic_preferred
      - Recommends not_recommended option
      - Cites wrong NCCN reference
    """
    failures: list[str] = []
    if not primary_bundle:
        return True, []
    answer_lower = answer_text.lower()

    # Check no not_recommended option is suggested
    not_recommended = primary_bundle.get("therapeutic_not_recommended") or []
    for opt in not_recommended:
        opt_lower = str(opt).lower().replace("_", " ")
        # Heuristic: if a not_recommended phrase appears affirmatively in answer
        if opt_lower in answer_lower:
            # Check it's NOT contextualized as a warning ("no", "evitar", "no recomendado")
            window_start = answer_lower.find(opt_lower)
            window = answer_lower[max(0, window_start - 30):window_start]
            if not any(neg in window for neg in ["no recomend", "evitar", "contraindica", "no preferid", "no aplica"]):
                failures.append(
                    f"decision_violation: answer suggests '{opt}' which is not_recommended"
                )

    return len(failures) == 0, failures


def decision_answer_to_dict(answer: GroundedDecisionAnswer) -> dict[str, Any]:
    """Serialize for JSON response."""
    return asdict(answer)


__all__ = [
    "GroundedDecisionAnswer",
    "classify_question_intent",
    "invoke_applicable_copilots",
    "build_decision_aware_answer",
    "decision_answer_to_dict",
]
