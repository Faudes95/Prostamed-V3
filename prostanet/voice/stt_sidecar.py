"""Sidecar entrypoint for local Voice Clinical OS STT.

This module is intentionally tiny and local-only. The Flask app can keep its
current Python runtime while a compatible Python 3.11/3.12 environment runs
faster-whisper and returns structured JSON segments.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ProstaMed local STT sidecar")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", default=os.environ.get("VOICE_STT_MODEL", "small"))
    parser.add_argument("--device", default=os.environ.get("VOICE_STT_DEVICE", "cpu"))
    parser.add_argument("--compute-type", default=os.environ.get("VOICE_STT_COMPUTE_TYPE", "int8"))
    parser.add_argument("--language", default="es")
    args = parser.parse_args(argv)

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        print(json.dumps({"success": False, "error": "faster_whisper_unavailable", "detail": type(exc).__name__}))
        return 2

    try:
        model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
        segments, _info = model.transcribe(args.audio, language=args.language, vad_filter=True)
        payload = []
        for idx, segment in enumerate(segments):
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            payload.append(
                {
                    "index": idx,
                    "text": text,
                    "start_ms": int(float(getattr(segment, "start", 0.0) or 0.0) * 1000),
                    "end_ms": int(float(getattr(segment, "end", 0.0) or 0.0) * 1000),
                    "confidence": 0.0,
                }
            )
        print(json.dumps({"success": True, "segments": payload}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": "stt_transcription_failed", "detail": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
