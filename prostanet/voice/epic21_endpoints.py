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
        "unified_extractor": True,  # /voice-update skill
        "clinical_vocabulary_boost": True,  # /voice-ai-engine-development skill
        "tts_phrasing_validator": True,  # /writing-voice skill
        "agents_md_documented": True,  # /voice-agents skill
    }
    # Module health checks
    modules = {}
    for mod_name, mod_path in [
        ("micro_form_extractor", "prostanet.voice.micro_form_extractor"),
        ("patient_name_resolver", "prostanet.voice.patient_name_resolver"),
        ("patient_qa_grounding", "prostanet.voice.patient_qa_grounding"),
        ("unified_extractor", "prostanet.voice.unified_extractor"),
        ("clinical_vocabulary_boost", "prostanet.voice.clinical_vocabulary_boost"),
        ("tts_phrasing", "prostanet.voice.tts_phrasing"),
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
        "skills_applied": [
            "/voice",
            "/voice-agents",
            "/voice-update",
            "/voice-note-ingest",
            "/voice-ai-development",
            "/voice-ai-engine-development",
            "/writing-voice",
        ],
        "scope": "internal_shadow_observational_validation",
    }), 200


# ─────────────────── EPIC 24a — STT health + pre-warm ───────────────────


@epic21_bp.route("/api/voice/stt/health", methods=["GET"])
def voice_stt_health() -> Any:
    """EPIC 24a — Structured STT engine health for UI gating + admin diagnose.

    Resolves the documented "audio cifrado · STT local pendiente" UX gap: the
    UI now reads this endpoint at panel mount and can show specific blockers
    (sidecar missing vs disabled vs decode error) instead of the generic
    warning. Mirrors the diagnose() output of LocalSTTEngine.
    """
    try:
        from prostanet.voice.stt_engine import LocalSTTEngine
        stt = LocalSTTEngine()
        diag = stt.diagnose()
        # Add a `next_steps` array the UI can render verbatim
        next_steps = []
        if not diag["stt_available"]:
            if diag.get("stt_disable_env"):
                next_steps.append("Eliminar VOICE_STT_DISABLE del entorno y reiniciar Flask.")
            elif "sidecar venv no encontrado" in " ".join(diag.get("blockers", [])):
                next_steps.append(
                    "Crear el venv con Python 3.11 y faster-whisper: "
                    "python3.11 -m venv .venv-voice311 && "
                    ".venv-voice311/bin/pip install -r requirements-voice.txt"
                )
            else:
                next_steps.append("Contactar al administrador del sistema.")
        diag["next_steps"] = next_steps
        diag["epic"] = "24a"
        diag["scope"] = "internal_shadow_observational_validation"
        return jsonify(diag), 200
    except Exception as exc:
        return jsonify({
            "stt_available": False,
            "mode": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "epic": "24a",
        }), 500


@epic21_bp.route("/api/voice/stt/prewarm", methods=["POST"])
def voice_stt_prewarm() -> Any:
    """EPIC 24b — Pre-warm the STT model so the first real /audio request
    doesn't pay the 60-120s cold-start cost. Idempotent: subsequent calls
    no-op when model already warm. Returns latency_ms for observability.
    """
    import time as _t
    try:
        from prostanet.voice.stt_engine import LocalSTTEngine
        stt = LocalSTTEngine()
        if not stt.is_available():
            return jsonify({
                "warmed": False,
                "reason": "stt_not_available",
                "epic": "24b",
            }), 503
        t0 = _t.perf_counter()
        # Send 200ms of silence through the pipeline so model loads.
        # 16kHz mono int16 silence = 16000 * 0.2 * 2 = 6400 bytes
        silence_pcm = b"\x00" * 6400
        try:
            stt.transcribe_bytes(silence_pcm, suffix=".pcm", language="es")
        except Exception as inner:
            # Even if transcribe fails on raw PCM, the model is now loaded.
            return jsonify({
                "warmed": True,
                "latency_ms": int((_t.perf_counter() - t0) * 1000),
                "warmup_note": f"silence transcribe failed but model loaded: {type(inner).__name__}",
                "epic": "24b",
            }), 200
        return jsonify({
            "warmed": True,
            "latency_ms": int((_t.perf_counter() - t0) * 1000),
            "epic": "24b",
        }), 200
    except Exception as exc:
        return jsonify({
            "warmed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "epic": "24b",
        }), 500


# ─────────────────── Skills integration endpoints ───────────────────


@epic21_bp.route("/api/voice/epic21/stt-vocabulary-prompt", methods=["GET"])
def epic21_stt_vocabulary_prompt() -> Any:
    """/voice-ai-engine-development — Return clinical vocabulary boost prompt
    for faster-whisper STT initialization. Query params:
      - language (es|en, default es)
      - max_chars (default 1024)
      - categories (comma-separated, optional)
    """
    try:
        from prostanet.voice.clinical_vocabulary_boost import (
            get_stt_initial_prompt,
            get_vocabulary_stats,
        )
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    language = (request.args.get("language") or "es").lower()
    try:
        max_chars = int(request.args.get("max_chars") or 1024)
    except ValueError:
        max_chars = 1024
    cats_str = request.args.get("categories") or ""
    categories = [c.strip() for c in cats_str.split(",") if c.strip()] or None

    prompt = get_stt_initial_prompt(
        language=language,
        max_chars=max_chars,
        include_categories=categories,
    )
    stats = get_vocabulary_stats()
    return jsonify({
        "available": True,
        "prompt": prompt,
        "prompt_length_chars": len(prompt),
        "language": language,
        "vocabulary_stats": stats,
    }), 200


@epic21_bp.route("/api/voice/epic21/unified-extract", methods=["POST"])
def epic21_unified_extract() -> Any:
    """/voice-update — Unified extraction combining legacy + EPIC 20 micro-forms.

    POST body: {"transcript": "...", "moment": "bcr_detection" (optional)}
    """
    try:
        from prostanet.voice.unified_extractor import (
            extract_all_candidates,
            get_extractor_capabilities,
        )
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    transcript = str(payload.get("transcript") or "").strip()
    moment = payload.get("moment")
    if not transcript:
        return jsonify({"available": False, "error": "transcript_required"}), 400

    candidates = extract_all_candidates(transcript, moment=moment)
    return jsonify({
        "available": True,
        "moment": moment,
        "total_candidates": len(candidates),
        "legacy_source_count": sum(1 for c in candidates if c.get("source") == "legacy"),
        "micro_form_source_count": sum(1 for c in candidates if c.get("source") == "micro_form"),
        "candidates": candidates,
        "capabilities": get_extractor_capabilities(),
    }), 200


@epic21_bp.route("/api/voice/epic21/cortana", methods=["POST"])
def epic21_cortana_orchestrator() -> Any:
    """Phase 2D — Cortana single entry point (intent routing).

    POST body: {
      "transcript": "...",
      "patient_nss": "..." (optional),
      "session_id": "..." (optional),
      "multi_turn_state": {...} (optional),
      "language": "es" (default)
    }
    """
    try:
        from prostanet.voice.cortana_orchestrator import (
            orchestrate_cortana, orchestration_to_dict,
        )
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"available": False, "error": "transcript_required"}), 400

    result = orchestrate_cortana(
        transcript,
        patient_nss=payload.get("patient_nss"),
        session_id=payload.get("session_id"),
        multi_turn_state=payload.get("multi_turn_state"),
        language=payload.get("language", "es"),
        preferred_provider=payload.get("preferred_provider"),
    )
    return jsonify(orchestration_to_dict(result)), 200


@epic21_bp.route("/api/voice/epic21/intake-full", methods=["POST"])
def epic21_intake_full() -> Any:
    """Phase 2A — Full intake orchestrator (chronological dictation).

    POST body: {"transcript": "...", "multi_turn_state": {...} (optional)}
    """
    try:
        from prostanet.voice.voice_intake_full_orchestrator import (
            orchestrate_full_intake, result_to_dict,
        )
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        return jsonify({"available": False, "error": "transcript_required"}), 400

    result = orchestrate_full_intake(
        transcript,
        multi_turn_state=payload.get("multi_turn_state"),
        language=payload.get("language", "es"),
    )
    return jsonify(result_to_dict(result)), 200


@epic21_bp.route("/api/voice/epic21/decision-qa/<nss>", methods=["POST"])
def epic21_decision_qa(nss: str) -> Any:
    """Phase 2B — Decision-aware patient Q&A (invokes copilots + Patient Twin).

    POST body: {"question": "¿Cuál sería la mejor opción?"}
    """
    if not nss:
        return jsonify({"available": False, "error": "nss_required"}), 400

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"available": False, "error": "question_required"}), 400

    try:
        import tracking_db
        record = tracking_db.get_patient_full_record(nss)
        if not record:
            return jsonify({"available": False, "error": "patient_not_found", "nss": nss}), 404
    except Exception as e:
        return jsonify({"available": False, "error": f"record_load_failed: {e}"}), 500

    try:
        from prostanet.voice.decision_aware_qa import (
            build_decision_aware_answer, decision_answer_to_dict,
        )
        answer = build_decision_aware_answer(record, question)
        result = decision_answer_to_dict(answer)
        result["available"] = True
        result["nss"] = nss
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"available": False, "error": f"decision_qa_failed: {e}"}), 500


@epic21_bp.route("/api/voice/epic21/population-qa", methods=["POST"])
def epic21_population_qa() -> Any:
    """Phase 2C — Population Q&A + cohort audits with safe SQL.

    POST body: {"question": "¿Cuántos mCRPC?"}
    """
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return jsonify({"available": False, "error": "question_required"}), 400

    try:
        from prostanet.voice.population_query_safe import (
            answer_population_question, cohort_result_to_dict,
        )
        cohort = answer_population_question(question)
        return jsonify(cohort_result_to_dict(cohort)), 200
    except Exception as e:
        return jsonify({"available": False, "error": f"population_qa_failed: {e}"}), 500


@epic21_bp.route("/api/voice/epic21/tts-validate", methods=["POST"])
def epic21_tts_validate() -> Any:
    """/writing-voice — Validate TTS text against safety phrasing rules.

    POST body: {"text": "...", "max_sentences": 2 (optional)}
    """
    try:
        from prostanet.voice.tts_phrasing import validate_tts_text
    except ImportError as e:
        return jsonify({"available": False, "error": f"module_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "")
    max_sentences = int(payload.get("max_sentences") or 2)
    result = validate_tts_text(text, max_sentences=max_sentences)
    return jsonify({"available": True, **result}), 200


def register_epic21_endpoints(app) -> None:
    """Register EPIC 21 blueprint into Flask app."""
    try:
        app.register_blueprint(epic21_bp)
        logger.info("EPIC 21 endpoints registered (voice longitudinal Cortana)")
    except Exception as e:
        logger.error("EPIC 21 blueprint registration failed: %s", e)


__all__ = ["epic21_bp", "register_epic21_endpoints"]
