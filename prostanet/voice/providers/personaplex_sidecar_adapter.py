"""EPIC 21 Phase 3D — PersonaPlex Sidecar HTTP Adapter.

Runs INSIDE the PersonaPlex Docker container. Exposes HTTP endpoints
that ProstaMed Cortana calls:

  GET  /health   → {available, gpu_info, model_loaded, version}
  POST /turn     → {response_text, response_audio_b64, latency_ms, session_id}

This adapter is the boundary between ProstaMed (calls HTTP) and
PersonaPlex/Moshi (Python lib that needs GPU + model weights loaded).

The adapter LAZY-LOADS PersonaPlex on first /turn (avoids long startup).
Health check returns model_loaded=False until first warm-up.

NOTE: This is a STUB skeleton. To activate, set up GPU host + provide
HuggingFace token + accept NVIDIA Open Model License. See:
  docs/personaplex_install.md

Authorization scope: internal_shadow_observational_validation.
NO PHI persisted in this container (transcripts forwarded back to ProstaMed
host for audit logging there).
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
import time
import uuid
from typing import Any

try:
    from flask import Flask, jsonify, request
    from waitress import serve
except ImportError:
    print("ERROR: flask + waitress required. pip install flask waitress")
    sys.exit(1)

logger = logging.getLogger("personaplex_sidecar")
logging.basicConfig(level=os.environ.get("PERSONAPLEX_LOG_LEVEL", "INFO"))

AUTH_TOKEN_REQUIRED = os.environ.get("PERSONAPLEX_AUTH_TOKEN", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")

app = Flask(__name__)


# ─────────────────── Lazy model loading ───────────────────


class PersonaPlexLazyLoader:
    """Lazy-load PersonaPlex on first request to avoid 60-120s startup."""

    def __init__(self) -> None:
        self.model = None
        self.gpu_info: dict[str, Any] = {}
        self.load_error: str = ""
        self._loading = False

    def is_loaded(self) -> bool:
        return self.model is not None

    def _detect_gpu(self) -> dict[str, Any]:
        info: dict[str, Any] = {"available": False, "name": "none", "vram_gb": 0}
        try:
            import torch
            if torch.cuda.is_available():
                info["available"] = True
                info["name"] = torch.cuda.get_device_name(0)
                info["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
                info["cuda_version"] = torch.version.cuda
        except Exception as exc:
            info["error"] = str(exc)
        return info

    def load(self) -> bool:
        """Load PersonaPlex model. Returns True if loaded successfully."""
        if self.is_loaded() or self._loading:
            return self.is_loaded()
        self._loading = True
        try:
            self.gpu_info = self._detect_gpu()
            if not self.gpu_info.get("available"):
                self.load_error = "no_gpu_available"
                logger.warning("PersonaPlex load skipped — no GPU detected")
                return False

            # NOTE: Actual PersonaPlex import + load happens here when deployed
            # Placeholder for documentation purposes:
            #
            #   from personaplex import PersonaPlexModel
            #   self.model = PersonaPlexModel.from_pretrained(
            #       "nvidia/personaplex-base",
            #       token=HF_TOKEN,
            #       device="cuda",
            #       persona="cortana_clinical_es",
            #   )
            #
            # For sidecar STUB without real install:
            self.model = "STUB_MODEL_NOT_LOADED"  # placeholder; real implementation imports above
            self.load_error = ""
            logger.info("PersonaPlex STUB loaded (replace with real import in production)")
            return True
        except Exception as exc:
            self.load_error = f"load_failed: {exc}"
            logger.error("PersonaPlex load failed: %s", exc)
            return False
        finally:
            self._loading = False


loader = PersonaPlexLazyLoader()


# ─────────────────── HTTP endpoints ───────────────────


def _check_auth(req) -> bool:
    """Verify Authorization header if AUTH_TOKEN_REQUIRED is set."""
    if not AUTH_TOKEN_REQUIRED:
        return True
    header = req.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    return header[7:] == AUTH_TOKEN_REQUIRED


@app.route("/health", methods=["GET"])
def health():
    """Health probe for ProstaMed Cortana."""
    if not _check_auth(request):
        return jsonify({"available": False, "error": "unauthorized"}), 401

    # First-time check loads GPU info (does NOT load model yet)
    if not loader.gpu_info:
        loader.gpu_info = loader._detect_gpu()

    return jsonify({
        "available": loader.gpu_info.get("available", False),
        "gpu_info": loader.gpu_info,
        "model_loaded": loader.is_loaded(),
        "load_error": loader.load_error,
        "version": "personaplex_sidecar_1.0",
        "scope": "internal_shadow_observational_validation",
    }), 200


@app.route("/turn", methods=["POST"])
def turn():
    """Process one voice interaction turn.

    Request: {
      "transcript": "..." (optional, pre-computed STT),
      "audio_b64": "..." (optional, base64 audio bytes),
      "intent": "...",
      "safety_class": "low|medium",  (HIGH/CRITICAL refused by base.py routing)
      "patient_nss": "..." (context only, NOT used for factual claims),
      "persona": "cortana_clinical_es",
      "language": "es"
    }

    Response: {
      "response_text": "...",
      "response_audio_b64": "..." (optional),
      "latency_ms": int,
      "session_id": "..."
    }
    """
    if not _check_auth(request):
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    t0 = time.perf_counter()

    # CRITICAL safety enforcement: refuse HIGH/CRITICAL
    safety = payload.get("safety_class", "low").lower()
    if safety in ("high", "critical"):
        return jsonify({
            "error": "safety_class_unsupported",
            "message": (
                "PersonaPlex refuses HIGH/CRITICAL contexts (no transcript = no firewall). "
                "Route this turn to Whisper pipeline instead."
            ),
            "safety_class": safety,
        }), 400

    # Lazy load model
    if not loader.is_loaded():
        loaded = loader.load()
        if not loaded:
            return jsonify({
                "error": "model_not_loaded",
                "load_error": loader.load_error,
            }), 503

    # STUB inference (replace with real PersonaPlex call in production)
    transcript = str(payload.get("transcript") or "")
    intent = payload.get("intent") or "unknown"

    if intent == "small_talk":
        response_text = (
            "Hola, soy Cortana clínica realtime. Puedo ayudarte con ingreso, "
            "búsqueda, preguntas sobre paciente abierto, o consultas de cohorte."
        )
    elif intent == "intake":
        response_text = "Te escucho. Continúa dictando el caso."
    elif intent == "patient_lookup":
        # Defer to ProstaMed name resolver (this sidecar doesn't access PHI DB)
        response_text = "Buscando paciente. Un momento."
    else:
        response_text = f"Procesando turn intent={intent} en modo realtime."

    # Real implementation would generate audio via PersonaPlex/Moshi here
    response_audio_b64 = None

    latency = int((time.perf_counter() - t0) * 1000)
    return jsonify({
        "response_text": response_text,
        "response_audio_b64": response_audio_b64,
        "latency_ms": latency,
        "session_id": str(uuid.uuid4()),
        "intent_handled": intent,
        "safety_class": safety,
    }), 200


def main() -> int:
    parser = argparse.ArgumentParser(description="PersonaPlex Sidecar HTTP Adapter")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logger.info(
        "PersonaPlex Sidecar starting on %s:%d (auth_required=%s)",
        args.host, args.port, bool(AUTH_TOKEN_REQUIRED),
    )

    # Pre-warm GPU detection (model NOT loaded yet — that happens on first /turn)
    loader.gpu_info = loader._detect_gpu()
    logger.info("GPU info: %s", loader.gpu_info)

    if args.debug:
        app.run(host=args.host, port=args.port, debug=True)
    else:
        serve(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
