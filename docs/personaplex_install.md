# PersonaPlex Sidecar Install — EPIC 21 Phase 3

> Guía para instalar NVIDIA PersonaPlex como sidecar para Cortana voice realtime.
> Implementa **capa opcional con safety-aware routing**: PersonaPlex maneja
> LOW/MEDIUM safety; Whisper pipeline maneja HIGH/CRITICAL.

## Arquitectura

```
┌────────────────────────────────┐         HTTP/WebSocket          ┌─────────────────────────────┐
│  ProstaMed Flask (Mac/Linux)   │ ◄────────────────────────────► │  PersonaPlex Sidecar (GPU)  │
│                                │                                  │                              │
│  prostanet/voice/cortana_      │                                  │  /health                     │
│  orchestrator.py               │                                  │  /turn                       │
│    │                           │                                  │                              │
│    ├──► safety routing         │   intent=intake/small_talk      │  NVIDIA CUDA 12              │
│    │    classify_intent_safety │   safety=low/medium             │  PersonaPlex (Moshi-based)   │
│    │                           │   ───────────────────────►       │  HuggingFace weights         │
│    ├──► LOW/MEDIUM             │                                  │                              │
│    │    └──► PersonaPlex       │   intent=qa/decision/pop_qa     │                              │
│    │                           │   safety=high/critical           │  ❌ HIGH/CRITICAL refused   │
│    └──► HIGH/CRITICAL          │   ❌ NEVER routed                │     (no transcript → no fw) │
│         └──► Whisper + fw      │                                  │                              │
└────────────────────────────────┘                                  └─────────────────────────────┘
```

## Requisitos GPU

- NVIDIA GPU con CUDA 12.4+ support (e.g., RTX 3090/4090, A100, H100, Blackwell)
- Minimum VRAM: 16 GB (Moshi base model)
- Recommended: 24 GB+ for batched inference
- NVIDIA Container Toolkit (for Docker GPU access)

## Pre-requisitos

1. **HuggingFace token** con permiso para download de `nvidia/personaplex-base`:
   ```bash
   export HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxx
   ```

2. **Aceptación NVIDIA Open Model License**:
   - Visitar https://huggingface.co/nvidia/personaplex-base
   - Click "Agree to License" antes de download

3. **ProstaMed sidecar auth token** (para evitar acceso público al sidecar):
   ```bash
   export PROSTAMED_PERSONAPLEX_TOKEN=$(openssl rand -hex 32)
   echo $PROSTAMED_PERSONAPLEX_TOKEN > ~/.config/prostamed/personaplex_token
   ```

## Opción 1 — GPU local con Docker (RTX 3090/4090)

```bash
# Desde root del repo ProstaMed
cd /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6

# Build image
docker build -f Dockerfile.personaplex-sidecar -t prostamed/personaplex:1.0 .

# Run sidecar (assumes nvidia-container-toolkit installed)
docker run -d \
  --gpus all \
  -p 8090:8090 \
  -e PERSONAPLEX_AUTH_TOKEN=$PROSTAMED_PERSONAPLEX_TOKEN \
  -e HF_TOKEN=$HUGGINGFACE_TOKEN \
  --name personaplex-sidecar \
  --restart unless-stopped \
  prostamed/personaplex:1.0

# Wait ~120s for first model load
docker logs -f personaplex-sidecar | grep -i "model loaded\|error"

# Verify health
curl -H "Authorization: Bearer $PROSTAMED_PERSONAPLEX_TOKEN" \
  http://localhost:8090/health
```

Expected output:
```json
{
  "available": true,
  "gpu_info": {"available": true, "name": "RTX 4090", "vram_gb": 24.0},
  "model_loaded": true,
  "version": "personaplex_sidecar_1.0"
}
```

## Opción 2 — GPU cloud (RunPod, Lambda Labs, Vast.ai)

1. Provisión instance con NVIDIA GPU + CUDA 12.4
2. SSH al host + install Docker + nvidia-container-toolkit
3. Clone repo ProstaMed (o solo Dockerfile + sidecar_adapter):
   ```bash
   git clone https://github.com/Faudes95/ProstaNet_Model_Fase6.git
   cd ProstaNet_Model_Fase6
   ```
4. Build + run idéntico a Opción 1
5. Exponer puerto 8090 vía firewall / port forwarding
6. Configurar TLS reverse proxy si es internet-facing

## Opción 3 — Mac CPU dev (degradado)

PersonaPlex no diseñado para Mac CPU. Para dev/testing sin GPU:

```bash
# El sidecar adapter funciona en CPU pero retorna model_loaded=False
# Cortana orchestrator detecta is_available=False → fallback a Whisper

cd /Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6
PERSONAPLEX_AUTH_TOKEN="dev-token-not-for-prod" \
  python3 prostanet/voice/providers/personaplex_sidecar_adapter.py --port 8090

# En otra terminal:
curl -H "Authorization: Bearer dev-token-not-for-prod" \
  http://localhost:8090/health
# → {"available": false, "load_error": "no_gpu_available"}
```

Este modo permite probar el ROUTING + FALLBACK sin ejecutar PersonaPlex real.

## Configuración en ProstaMed

```bash
# .env o variables de entorno del Flask
export PERSONAPLEX_SIDECAR_URL=http://gpu-host.internal:8090
export PERSONAPLEX_AUTH_TOKEN=$PROSTAMED_PERSONAPLEX_TOKEN
export PERSONAPLEX_TIMEOUT_SEC=30

# Reiniciar Flask para pickup
pkill -f "python3 app.py" && cd /path/to/ProstaMed && nohup python3 app.py &
```

Verificar routing live:
```bash
curl http://127.0.0.1:8080/api/voice/epic21/health
# capabilities.fase_personaplex_routing debe ser true si sidecar reachable
```

## Compliance + safety statements

1. **HIPAA**: el sidecar NO persiste PHI. Transcripts/audio se procesan in-memory
   y los audit logs se devuelven a ProstaMed host para storage en
   `voice_encounter_sessions` table (encrypted).

2. **NVIDIA OML**: weights NO redistribuibles. License permite uso interno
   + investigación. Para uso comercial revisar terms específicos.

3. **Safety routing**: la arquitectura GARANTIZA que HIGH/CRITICAL safety
   contexts NUNCA routean a PersonaPlex (refused por `process_turn` y por
   `VoiceProviderRegistry.select_provider`).

4. **Grounding firewall**: solo Whisper pipeline expone transcript intermedio →
   solo Whisper puede ejecutar grounding firewall. PersonaPlex contextos
   son non-factual por diseño (intake support, navegación).

5. **Audit immutable**: cada turn genera audit_log_entry con safety_class +
   provider_used + firewall_applied/blocked. Reviewable post-hoc.

## Troubleshooting

### Sidecar reports `model_loaded=False` after 5 min

```bash
docker logs personaplex-sidecar | tail -100
# Common causes:
#   - HF_TOKEN inválido o sin permiso para nvidia/personaplex-base
#   - NVIDIA OML no aceptada (visitar HuggingFace + click Agree)
#   - VRAM insuficiente (<16GB) → considera otro modelo Moshi smaller
```

### ProstaMed reports `is_available=False`

```bash
# Test sidecar directamente
curl -H "Authorization: Bearer $PROSTAMED_PERSONAPLEX_TOKEN" \
  $PERSONAPLEX_SIDECAR_URL/health

# Si OK from CLI pero ProstaMed dice unavailable → check env vars:
python3 -c "import os; print('URL:', os.environ.get('PERSONAPLEX_SIDECAR_URL'))"
```

### Safety routing forces whisper aunque PersonaPlex available

Esto es **comportamiento esperado** para intents:
- `patient_qa` (HIGH safety) → siempre Whisper
- `decision_recommendation` (CRITICAL) → siempre Whisper
- `population_qa` (CRITICAL) → siempre Whisper

Routing solo elige PersonaPlex para:
- `small_talk` (LOW)
- `intake` (MEDIUM)
- `patient_lookup` (MEDIUM)

Esto es safety-by-design — NO bug.

## Roadmap (futuro)

- [ ] WebSocket streaming end-to-end (no HTTP polling)
- [ ] Voice biometric authentication factor
- [ ] Multi-persona support (specialist sub-personas: oncology, radiology, etc.)
- [ ] On-device inference para hardware con NVIDIA RTX (Mac Studio M-series con eGPU)
- [ ] EPIC 22: Population queries con voice-driven SQL builder
