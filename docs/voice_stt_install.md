# Voice STT Install Guide (EPIC 24)

ProstaMed Voice Clinical OS uses **faster-whisper 1.0.3** for local
speech-to-text. The library requires Python 3.10–3.12 (PyAV/CTranslate2
wheels are not yet published for Python 3.13+).

## Diagnose current state

```bash
curl -s http://localhost:8080/api/voice/stt/health | jq
```

Expected response when STT is healthy:
```json
{
  "stt_available": true,
  "mode": "sidecar",
  "sidecar_python": "/path/to/.venv-voice311/bin/python",
  "sidecar_faster_whisper_version": "1.0.3",
  "blockers": []
}
```

## Install modes

| Mode | When to use | How |
|------|-------------|-----|
| **in_process** | Flask runs on Python 3.10–3.12 | `pip install -r requirements-voice.txt` |
| **sidecar** | Flask runs on Python 3.13+ (e.g., Mac dev) | See "Sidecar setup" below |
| **unavailable** | STT disabled OR neither path works | UI shows "STT no configurado" CTA |

## Sidecar setup (recommended for Mac dev)

```bash
# From repo root:
python3.11 -m venv .venv-voice311
.venv-voice311/bin/pip install --upgrade pip
.venv-voice311/bin/pip install -r requirements-voice.txt
```

Verify:
```bash
.venv-voice311/bin/python -c "import faster_whisper; print(faster_whisper.__version__)"
# → 1.0.3
```

Flask auto-discovers the venv at the following paths (in order):
1. `$VOICE_STT_SIDECAR_PYTHON` env var (explicit override)
2. `$(pwd)/.venv-voice311/bin/python`
3. Output of `git rev-parse --show-toplevel` + `.venv-voice311/bin/python`
   (resolves through git worktrees)
4. Upward search from `prostanet/voice/stt_engine.py`
5. `$HOME/.venv-voice311/bin/python`
6. `python3.11` / `python3.12` on `$PATH` (last resort)

## Env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `VOICE_STT_DISABLE` | unset | If "1"/"true"/"yes": disables STT entirely (audio stays encrypted, never transcribed) |
| `VOICE_STT_MODEL` | `small` | faster-whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `VOICE_STT_DEVICE` | `cpu` | `cpu` or `cuda` |
| `VOICE_STT_COMPUTE_TYPE` | `int8` | `int8`, `int8_float16`, `float16`, `float32` |
| `VOICE_STT_PREWARM` | `1` | If "0"/"false": skip startup pre-warm (default loads model at boot) |
| `VOICE_STT_TIMEOUT_SECONDS` | `120` | Max time for sidecar transcription before declaring timeout |
| `VOICE_STT_SIDECAR_PYTHON` | unset | Absolute path to Python that has `faster_whisper` installed |

## UI status reference (EPIC 24d/24e)

The UI surface (`prostamed_voice_os.js`) branches on `transcription_status`
returned by `POST /encounter/<nss>/<session>/audio`:

| Status | UI message | Clinician action |
|--------|-----------|------------------|
| `transcribed` | "audio transcrito · revisión pendiente" or "voz aplicada al clasificador" | Review / approve |
| `partial_audio_buffering` | "buffer parcial · esperando más audio" | Continue speaking |
| `empty_transcript` | "audio recibido · sin voz detectable" | Speak louder / closer |
| `requires_local_stt_sidecar_not_found` | "STT no configurado · contactar admin" | Ask admin to set up `.venv-voice311` |
| `requires_local_stt_disabled` | "STT deshabilitado por admin" | Ask admin to unset `VOICE_STT_DISABLE` |
| `requires_local_stt_other` | "audio cifrado · STT local pendiente" (with blocker detail) | See diagnose output |
| `stt_error` | "error real de STT · <detail>" | Inspect Flask logs |
| `not_requested` | "audio cifrado recibido" | (intermediate state) |

## Pre-warm (EPIC 24b)

Cold-start of the `small` model is ~60-120s. To avoid this latency on the
first real audio request, Flask spawns a daemon thread at boot that calls
`LocalSTTEngine().transcribe_bytes(silence)` to load the model into RAM.

Manual trigger (idempotent):
```bash
curl -X POST http://localhost:8080/api/voice/stt/prewarm
# → {"warmed": true, "latency_ms": 1800, "epic": "24b"}
```

Subsequent transcribe calls hit the warm model and respond in 2–5s.

## Troubleshooting

- **404 on `/api/voice/stt/health`**: Flask was started from a directory
  without the `prostanet/voice/` package (e.g., a sparse git worktree).
  Restart from the repo root or materialize the package files.

- **"sidecar venv no encontrado" blocker**: Run the sidecar setup above.

- **"silence transcribe failed but model loaded"**: Expected — the pre-warm
  sends raw PCM that the model can't decode, but the side effect of
  loading the model into RAM completes successfully.

- **Sidecar timeout**: Increase `VOICE_STT_TIMEOUT_SECONDS=240` for slower
  Macs or larger models.
