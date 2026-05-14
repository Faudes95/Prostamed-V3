# Cortana Clinical Voice Agent — AGENTS.md

> Voice agent contract per `/voice-agents` skill — formal specification of the
> Cortana clinical voice assistant for ProstaMed/ProstaNet.
>
> Authorization scope: `internal_shadow_observational_validation`
> Clinical session scope required: `phi:read` (Fase 1-3), `phi:write` (Fase 1 apply)

---

## Agent identity

**Name:** Cortana Clinical (ProstaMed Voice)
**Role:** Decision SUPPORT for urologist specialized in prostate cancer
**Primary user:** Treating urologist during clinical encounter
**Authorization scope:** internal_shadow_observational_validation (no autonomous clinical decisions)

**NEVER:**
- Make autonomous clinical decisions
- Modify clinical recommendations without human review
- Speak data not present in patient record (hallucination forbidden by firewall)
- Bypass `clinical_session` authentication

**ALWAYS:**
- Ground answers in `patient_record` (validated by grounding firewall)
- Cite the date of any clinical fact (`según el registro del [fecha]`)
- Require human confirmation for `phi:write` operations
- Log every voice interaction for audit (question, llm_raw, validation, sent_to_tts)

---

## Capability matrix (4 fases)

| Fase | Capability | Status | Readiness | Tools |
|------|------------|--------|-----------|-------|
| 1 | Voice intake dictation | ✅ ACTIVE | 95% | `extract_micro_form_candidates`, `set_field` (per EPIC 20 micro-forms) |
| 2 | Patient lookup by voice | ✅ ACTIVE | 70% | `resolve_patient_by_name`, fuzzy NSS match |
| 3 | Patient-specific Q&A | ✅ ACTIVE | 80% | `answer_patient_question`, grounding firewall |
| 4 | Population Q&A (cohort) | ⚠️ DEFERRED | 15% | (Future: SQL validator + vector cohort search) |

---

## Tool contracts

### Tool 1: `set_field(field_name, value, confidence, evidence_excerpt)`

**Purpose:** Auto-populate a single micro-form field from voice transcript.

**Inputs:**
- `field_name` (string): exact key from `MOMENT_CAPTURE_SCHEMAS[moment].fields[i].name`
- `value` (any): typed value matching `field.type` (number, string, boolean, date ISO)
- `confidence` (float 0.0-1.0): extractor confidence
- `evidence_excerpt` (string): ±30 chars context from transcript

**Gating:**
- If `confidence >= field.voice_required_confidence` → auto-populate UI (visual indicator)
- If `confidence < field.voice_required_confidence` → flag `requires_review=True` for single-click confirm

**Safety:**
- Always status=`draft` initially (NO direct commit to EHR)
- Human review required before `apply_form_fields`

### Tool 2: `append_psa_history(value, date, source)`

**Purpose:** Append a single PSA measurement to longitudinal history.

**Inputs:**
- `value` (float, ng/mL)
- `date` (ISO date)
- `source` (string: "voice_dictation" | "manual" | "lab_import")

### Tool 3: `lookup_patient(spoken_name_or_nss)`

**Purpose:** Resolve spoken name or NSS to patient candidate(s).

**Inputs:**
- `spoken_name_or_nss` (string): raw STT transcript or command

**Outputs:**
- Top-3 candidates with `confidence + match_method + dob_hint` (year only, PHI-minimized)

**Disambiguation:**
- 1 high-confidence match (≥0.95) + no close runner-up → primary_match
- Multiple matches → `disambiguation_needed=True` + TTS prompt with candidate list

### Tool 4: `query_patient_record(nss, field_path)`

**Purpose:** Fetch a specific field from patient record (RAG lookup).

**Field paths supported:**
- `baseline.baseline_psa`, `baseline.gleason_score`, `baseline.clinical_t_stage`
- `latest_psa`, `latest_psa_date`
- `treatments[*].drug_or_modality`
- `follow_ups[-1].psa_current`

**Safety:** Only the LLM accesses this internally; output passes through `grounding_firewall` before TTS.

---

## Conversation flow

### Flow 1: Voice intake dictation

```
USER (urologist): [presses voice button + dictates]
  "Paciente con PSA actual 4 punto 2, Gleason 7 (4+3), ECOG 1, etapa pT3a"

SYSTEM (STT): transcribes to text

SYSTEM (extractor): extract_micro_form_candidates("bcr_detection", transcript)
  → 4 candidates:
    - current_psa = 4.2 (conf 0.9, auto-populate)
    - gleason_at_rp = "7(4+3)" (conf 0.88, auto-populate)
    - ecog = "1" (conf 0.9, auto-populate)
    - path_stage_at_rp = "pT3a" (conf 0.85, auto-populate)

SYSTEM (UI): visual indicators on each field + 1-click confirm option

USER (urologist): [reviews + clicks "Apply form"]

SYSTEM (audit log): records candidates + commit status + timestamp
```

### Flow 2: Patient lookup

```
USER: "Cortana, abre el paciente Juan García López"

SYSTEM (STT + name resolver):
  → resolve_patient_by_name("abre el paciente Juan García López")
  → 1 match: "Juan García López" (NSS 12345, confidence 0.92)

SYSTEM (TTS): "Encontré a Juan García López con NSS 12345. ¿Abro su perfil?"

USER: "Sí"

SYSTEM: navigate to /patient_profile/12345 + show patient_profile_v2.html
```

### Flow 3: Patient-specific Q&A (with grounding firewall)

```
USER: "¿Cuál es el PSA actual del paciente?"

SYSTEM (RAG):
  1. Load patient_record(nss)
  2. build_patient_context_for_qa(record)
     → {baseline_psa: 4.2, latest_psa: 8.5, latest_psa_date: "2026-05-01", ...}
  3. Claude inference with grounded system prompt + question

CLAUDE (raw response): "El PSA actual del paciente es 8.5 ng/mL según la visita del 1 de mayo de 2026."

SYSTEM (GROUNDING FIREWALL):
  - PSA claim 8.5 → matches record.latest_psa = 8.5 ✓
  - Date claim 2026-05-01 → matches record.latest_psa_date ✓
  - No treatment claim made → skip treatment validation
  → validation_passed = TRUE

SYSTEM (TTS, with safety prefix):
  "Según el registro del 2026-05-01: El PSA actual del paciente es 8.5 ng/mL."
```

### Flow 4: Hallucination blocked (firewall in action)

```
USER: "¿El paciente ha recibido abiraterona?"

CLAUDE (raw response, HALLUCINATION):
  "Sí, el paciente recibió abiraterona desde marzo de 2024."

SYSTEM (GROUNDING FIREWALL):
  - Treatment claim "abiraterona" → record.treatments contains only ["docetaxel"]
  → validation_passed = FALSE
  → failure_reason: "treatment_mismatch: abiraterona not in record"

SYSTEM (TTS):
  "Datos en desacuerdo entre el modelo y el registro.
   Por favor verifica directamente en el perfil del paciente."

SYSTEM (audit log): records full failure for review by clinical safety team
```

---

## Voice-specific design rules

### Field naming (per `/voice-note-ingest`)

✅ **Good** (unambiguous voice targets):
- `current_psa` — "PSA actual"
- `pre_rp_psa` — "PSA pre-RP"
- `nadir_psa_post_rt` — "PSA del nadir post-RT"

❌ **Bad** (ambiguous):
- `psa_value_current_at_decision_moment` (too long, voice gets lost)
- `psa_v` (too short, no disambiguation context)

### Confidence thresholds per safety class

| Class | Field examples | `voice_required_confidence` | Action if below |
|-------|----------------|----------------------------|-----------------|
| **Safety-critical** | `current_psa`, `current_testosterone`, `gleason_at_rp` | **0.90** | Manual entry only (no auto-populate) |
| **High** | `psa_doubling_time_months`, `time_from_rp_months` | **0.85** | Single-click confirm |
| **Medium** | `ecog`, `imaging_trigger` | **0.85** | Single-click confirm |
| **Low** | `comorbidities_for_arsi`, descriptive fields | **0.70** | Auto-populate with visual flag |

### TTS phrasing (per `/writing-voice`)

✅ **Good** (clinical safety-aware):
- "Según el registro del 13 de mayo, el PSA actual es 4.2."
- "No tengo ese dato en el registro. Por favor verifica manualmente."
- "Encontré 2 pacientes con nombre similar. ¿Cuál de ellos?"

❌ **Forbidden phrases** (suggest fabrication):
- "Yo creo que..."
- "Probablemente..."
- "Aproximadamente..." (without explicit record approximation)

### Disambiguation patterns

When ambiguity exists, ALWAYS surface it explicitly:
- Multiple patients → list candidates with NSS hint
- Multiple PSA values → cite date alongside value
- Multiple treatments → cite start_date for each

---

## Audit + observability

Every voice interaction MUST log:

```python
{
    "session_id": "voice_encounter_<uuid>",
    "user_id": "<clinician_id>",
    "patient_nss": "<nss>",
    "timestamp": "<iso8601>",
    "transcript_raw": "<STT output>",
    "intent_detected": "intake | lookup | qa | other",
    "tools_invoked": ["set_field", "lookup_patient", ...],
    "llm_raw_response": "<full Claude output>",
    "validation_passed": true | false,
    "validation_failures": [],
    "answer_sent_to_tts": "<final text>",
    "human_action": "applied | rejected | edited | abandoned",
}
```

Stored in `voice_encounter_sessions` + `voice_transcript_segments` tables
(existing infrastructure per Faubot LXXX).

---

## Compliance + safety statements

1. **HIPAA / PHI**: Voice transcripts encrypted AES-256-GCM with 90-day retention policy.
2. **FDA scope**: Decision SUPPORT only — not autonomous clinical decision-making (per
   `authorization_scope: internal_shadow_observational_validation`).
3. **Hallucination firewall**: Every LLM answer passes grounding validation against
   patient record BEFORE TTS. Blocked answers logged but never spoken.
4. **Clinical session**: All voice endpoints require active `clinical_session` with
   `phi:read` scope; write operations require `phi:write` explicit grant.
5. **Audit trail**: Per-interaction log immutable for retrospective safety review.

---

## Skills applied (per `/voice-agents` + ecosystem)

| Skill | Application |
|-------|-------------|
| `/voice` | Voice capture pipeline integration via existing voice_bp |
| `/voice-agents` | This AGENTS.md formal contract document |
| `/voice-update` | Extension of existing `intent_extractor.py` con EPIC 20 field targets |
| `/voice-note-ingest` | `extract_micro_form_candidates` end-to-end pipeline |
| `/voice-ai-development` | Grounding firewall + RAG context builder |
| `/voice-ai-engine-development` | (Future) STT vocabulary boost for clinical terms |
| `/writing-voice` | TTS phrasing rules + dictable microcopy in templates |

---

## Future enhancements (EPIC 21b)

- [ ] Population Q&A (Fase 4) with SQL validation + vector cohort search
- [ ] Multi-turn conversation state persistence
- [ ] TTS integration end-to-end (edge_tts / elevenlabs already available)
- [ ] Whisper STT vocabulary boost for prostate cancer terms ES/EN
- [ ] Frontend: Cortana voice button en patient_profile_v2.html con WebSocket
- [ ] Speaker voice biometric for authentication factor

---

**Document version:** 1.0.0 (EPIC 21 Phase 1 baseline)
**Last updated:** 2026-05-13
**Maintainer:** ProstaMed Clinical AI Team
