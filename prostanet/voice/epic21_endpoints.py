"""EPIC 21 — Flask endpoints for voice longitudinal Cortana.

Registered as Blueprint additions to existing voice_bp.

Endpoints:
  POST /api/voice/epic21/intake/<moment>          — Fase 1: micro-form voice extraction
  POST /api/voice/epic21/patient-lookup           — Fase 2: name → NSS resolver
  POST /api/voice/epic21/patient-qa/<nss>         — Fase 3: grounded Q&A

All endpoints require clinical session (phi:read scope) — apply existing
voice_bp authorization middleware upstream.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

epic21_bp = Blueprint("voice_epic21", __name__)


# ─────────────────── Fase 1: Voice intake auto-population ───────────────────


@epic21_bp.route("/api/voice/epic21/intake/<moment>", methods=["POST"])
def voice_intake_micro_form(moment: str) -> Any:
    """Extract voice candidates for a micro-form moment.

    POST body: {"transcript": "PSA actual 4.2 ..."}

    Returns: {moment, total_candidates, auto_populate_count, requires_review_count,
              candidates: [{field_name, value, confidence, auto_populate, ...}, ...]}
    """
    try:
        from prostanet.voice.micro_form_extractor import (
            extract_micro_form_candidates,
            candidates_to_dict,
        )
        from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    if moment not in MOMENT_CAPTURE_SCHEMAS:
        return jsonify({
            "available": False,
            "error": "unknown_moment",
            "valid_moments": list(MOMENT_CAPTURE_SCHEMAS.keys()),
        }), 400

    payload = request.get_json(silent=True) or {}
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"available": False, "error": "transcript_required"}), 400

    candidates = extract_micro_form_candidates(moment, transcript)
    result = candidates_to_dict(candidates)
    result["moment"] = moment
    return jsonify(result), 200


@epic21_bp.route("/api/voice/epic21/intake-moments", methods=["GET"])
def list_intake_moments() -> Any:
    """List available micro-form moments for voice intake."""
    try:
        from prostanet.shared.moment_capture_schemas import MOMENT_CAPTURE_SCHEMAS, get_field_count_reduction
    except ImportError:
        return jsonify({"available": False, "error": "module_unavailable"}), 503

    moments = []
    for moment_name, form in MOMENT_CAPTURE_SCHEMAS.items():
        reduction = get_field_count_reduction(moment_name)
        moments.append({
            "moment": moment_name,
            "description": form.description,
            "trigger_moment": form.trigger_moment,
            "consumer": form.consumer,
            "field_count": len(form.fields),
            "full_schema_fields": reduction.get("full_schema_fields", 0),
            "reduction_pct": reduction.get("reduction_pct", 0),
        })
    return jsonify({"available": True, "moments": moments}), 200


# ─────────────────── Fase 2: Patient lookup by voice ───────────────────


@epic21_bp.route("/api/voice/epic21/patient-lookup", methods=["POST"])
def voice_patient_lookup() -> Any:
    """Resolve spoken name/NSS to patient candidates.

    POST body: {"spoken_input": "abre el paciente Juan García"}

    Returns: {available, candidates, disambiguation_needed, tts_response}
    """
    try:
        from prostanet.voice.patient_name_resolver import (
            resolve_patient_by_name,
            candidates_to_response,
        )
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    spoken = str(payload.get("spoken_input") or "").strip()
    if not spoken:
        return jsonify({"available": False, "error": "spoken_input_required"}), 400

    max_candidates = int(payload.get("max_candidates") or 3)
    min_confidence = float(payload.get("min_confidence") or 0.6)

    candidates = resolve_patient_by_name(
        spoken,
        max_candidates=max_candidates,
        min_confidence=min_confidence,
    )
    response = candidates_to_response(candidates, spoken)
    return jsonify(response), 200


# ─────────────────── Fase 3: Patient-specific Q&A ───────────────────


@epic21_bp.route("/api/voice/epic21/patient-qa/<nss>", methods=["POST"])
def voice_patient_qa(nss: str) -> Any:
    """Answer a patient-specific question with grounding firewall.

    POST body: {"question": "¿cuál es el PSA actual?"}

    Returns: {answer_validated, validation_passed, answer_blocked,
              validation_failure_reasons, audit_log_entry}
    """
    if not nss:
        return jsonify({"available": False, "error": "nss_required"}), 400

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"available": False, "error": "question_required"}), 400

    # Load patient record
    try:
        import tracking_db
        patient_record = tracking_db.get_patient_full_record(nss)
        if not patient_record:
            return jsonify({
                "available": False,
                "error": "patient_not_found",
                "nss": nss,
            }), 404
    except Exception as e:
        logger.error("Patient record load failed: %s", e)
        return jsonify({"available": False, "error": f"record_load_failed: {e}"}), 500

    # Q&A with grounding firewall
    try:
        from prostanet.voice.patient_qa_grounding import (
            answer_patient_question,
            grounded_answer_to_dict,
        )
        answer = answer_patient_question(patient_record, question)
        result = grounded_answer_to_dict(answer)
        result["available"] = True
        result["nss"] = nss
        return jsonify(result), 200
    except Exception as e:
        logger.error("Q&A grounding failed: %s", e)
        return jsonify({
            "available": False,
            "error": f"qa_grounding_failed: {e}",
        }), 500


# ─────────────────── EPIC 21 health/info ───────────────────


@epic21_bp.route("/api/voice/epic21/health", methods=["GET"])
def epic21_health() -> Any:
    """Health check + capabilities for EPIC 21 voice longitudinal."""
    capabilities = {
        "fase_1_voice_intake_dictation": True,
        "fase_2_patient_lookup_by_voice": True,
        "fase_3_patient_qa_grounded": True,
        "fase_4_population_qa": False,  # deferred to EPIC 21b
    }
    # Module health checks
    modules = {}
    for mod_name, mod_path in [
        ("micro_form_extractor", "prostanet.voice.micro_form_extractor"),
        ("patient_name_resolver", "prostanet.voice.patient_name_resolver"),
        ("patient_qa_grounding", "prostanet.voice.patient_qa_grounding"),
        ("anthropic_provider", "prostanet.voice.llm_providers.anthropic_provider"),
    ]:
        try:
            __import__(mod_path)
            modules[mod_name] = "available"
        except ImportError as e:
            modules[mod_name] = f"unavailable: {e}"

    return jsonify({
        "available": True,
        "epic": 21,
        "phase": 1,
        "capabilities": capabilities,
        "modules": modules,
        "scope": "internal_shadow_observational_validation",
    }), 200


def register_epic21_endpoints(app) -> None:
    """Register EPIC 21 blueprint into Flask app."""
    try:
        app.register_blueprint(epic21_bp)
        logger.info("EPIC 21 endpoints registered (voice longitudinal Cortana)")
    except Exception as e:
        logger.error("EPIC 21 blueprint registration failed: %s", e)


__all__ = ["epic21_bp", "register_epic21_endpoints"]
