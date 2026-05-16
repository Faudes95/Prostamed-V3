# Faubot Platform Dossier — Post EPIC 29

> Fecha: 2026-05-16 · Commit: `2215f80` · Pusheado a `origin` + `prostamed-v3`
>
> Este dossier es leído por la skill `/faubot` al inicio de cada auditoría para
> calibrar su entendimiento de la plataforma actual. Resumen autoritativo de
> arquitectura, taxonomía, integraciones críticas y gates post-EPIC 22-29.
>
> **Authority**: `prostanet/ai/config.py`, `prostanet/domains/`, `tracking_db.py`,
> `templates/patient_profile_v2.html`. Este dossier es secundario — la fuente
> primaria es el código. Si discrepan, el código gana y este dossier debe
> actualizarse.

---

## 1. Taxonomía clínica — 54 estados (era 13)

| Categoría | Cantidad | EPIC introductor |
|-----------|----------|-------------------|
| Backbone original (diagnostic/post-RP/BCR/mHSPC/CRPC) | 13 | Pre-EPIC 22 |
| Risk-stratified localized | 6 | EPIC 22c |
| Post-local by modality (LDR, **HDR**, EBRT, SBRT, focal) | 5 | EPIC 22c + 26.4 (HDR) |
| Hereditary carriers (BRCA1/2, ATM, Lynch, HOXB13) | 5 | EPIC 22c |
| Oligomet refinement | 3 | EPIC 22c |
| Special populations (CV/hepatic comorbidity) | 3 | EPIC 22c |
| Survivorship + second primary | 3 | EPIC 22c |
| Pre-diagnostic | 3 | EPIC 22c |
| **post_brachy_hdr** (END of list, VOCAB_VERSION=2) | (1) | EPIC 26.4 → 29.12 |
| **TOTAL** | **54** | |

Critical: `prostanet/ai/config.py` define `CLINICAL_STATES_VOCAB_VERSION=2` y
`post_brachy_hdr` está al final. Reordenar la lista invalida el checkpoint del
Transformer (`IncompatibleCheckpointError` lo detecta y enmascara con UI banner).

## 2. Recommendation Arbiter (EPIC 23 + 25-29)

`prostanet/domains/decision_arbiter/recommendation_arbiter.py` contiene
detectores de conflictos clínicos que comparan output del
`clinical_decision_agent` vs `profile_compass`:

| Detector | EPIC | Severity | Evidence |
|----------|------|----------|----------|
| BRCA2-mCSPC PARP-first timing mismatch | 23 | HIGH | PROfound (PMID 32343890) |
| CV severe + abiraterone+prednisone | 23 | HIGH | NCCN PROS-K + LATITUDE CV warnings |
| Hepatic severe + abiraterone | 25 | HIGH | LFT contraindication |
| HRR+ post-ARSI (PARP eligibility) | 25 | MOD | PROfound subgroup |
| Visceral mets undertreatment | 25/26 | HIGH | ARASENS (PMID 35179323) |
| Lynch + pembrolizumab eligibility | 26 | MOD | KEYNOTE-158 (PMID 31682550) |
| Enzalutamide + seizure (word-boundary, EPIC 29.5) | 26 → 29 | HIGH | AFFIRM label |
| Ra-223 + abi+pred concurrent (ERA-223) | 29.1 | CRIT | ERA-223 (PMID 30853531) |
| M0/M1b conflict | 25 | HIGH | NCCN PROS-J |
| Visceral data gap + castration unknown | 28 | HIGH | tri-state handling |

## 3. Patient Twin OS preferences (EPIC 22e + 23.fix)

`prostanet/domains/patient_tracking/patient_twin_os.py` — `REGIMEN_CATALOG` con
7 regimens base (era 5 pre-EPIC 28): doublete, triplete CHAARTED, triplete
ARASENS, ARSI mono, doublete LATITUDE, **pembrolizumab** (Lynch), **olaparib**
(BRCA2).

**Preferences capture**: form EPIC 22e en `templates/patient_profile_v2.html`
captura `qol_priority`, `oral_preferred`, `injection_aversion`, etc. Persistido
vía `_persist_patient_clinical_facts` con dedup + UNIQUE active row index
(EPIC 29.3 G62). Reading: `_find_fact` filtra `is_active=True` (EPIC 23.fix).

## 4. Patient Clinical Facts — UNIQUE constraint (EPIC 29.3 G62)

`tracking_db.py`:
- `CREATE UNIQUE INDEX patient_clinical_facts_unique_active ON patient_clinical_facts(patient_id, fact_key) WHERE is_active = 1`
- `_persist_patient_clinical_facts` auto-demote previous active row antes de
  INSERT (no más duplicate-active rows)

## 5. ARPI / Benefit matrix expansion (EPIC 29.6 G58 + 29.10 G59)

`prostanet/domains/patient_tracking/arpi_benefit_matrix.py`:
- **m1_crpc**: 10 regimens con `benefit_score`, `evidence_pmid`,
  `eligibility_gate`: ADT_ABIRATERONE, ADT_ENZALUTAMIDE, OLAPARIB,
  TALAZOPARIB_ENZA, LU177_PSMA_617, CABAZITAXEL, RA223, DOCETAXEL,
  PEMBROLIZUMAB, SIPULEUCEL_T (era 2 pre-EPIC 29)
- **m0_crpc**: 3 regimens con `eligibility_gate.psadt_max_months=10`
  (ARAMIS/PROSPER/SPARTAN evidence boundary)

## 6. PSA pipeline — autoridad y flujo

**Captura**:
- Intake form (`patient_intake.html`) → `app.py /api/register_patient`
- Longitudinal append: `/api/longitudinal/<nss>/append` con `kind in {psa, biopsy, imaging, ...}`
- Voice: `intent_extractor.py` reconoce "psa", "antígeno" → micro-form populated

**Canonicalización** (`prostanet/domains/patient_tracking/clinical_fact_registry.py`):
- Fact keys: `baseline_psa`, `current_psa`, `nadir_psa_post_rt`, `psa_at_castration`,
  `psa_at_progression`
- `FACT_SPECS` define `certainty_tier`, `freshness_status`, normalization

**Persistencia** (`tracking_db.py`):
- Table `psa_records` (raw timeline)
- Table `patient_clinical_facts` (canonical, post-EPIC 29.3 UNIQUE active)

**Por línea terapéutica** (`prostanet/domains/patient_tracking/psa_forecast.py`):
- `build_psa_by_treatment_line(patient)` segmenta PSA por treatment_line
- `_classify_regimen_for_cohort(drug_scheme)` maps a `cohort_class` ∈
  {ADT, ADT_DOCETAXEL, ADT_ARPI, ADT_TRIPLET, DOCETAXEL, ARPI, PARP, LU177}
- `build_psa_cohort_reference_overlay(patient)` overlay con cohort PSA expected

**Cohort references** (post-EPIC 29.9):
- `COHORT_PSA_REFERENCES[state][cohort_class]` con `nadir_pct`, `time_to_nadir_m`,
  `duration_response_m`, `median_label`, **`data_quality_tag`** (13/13 entries),
  **`evidence_pmid`**, **`disclaimer`**

**Contradictions** (`prostanet/domains/patient_tracking/clinical_contradiction_engine.py`):
- PCWG3-correct (EPIC 29.2 G55): nadir + ≥25% + ≥2 ng/mL + confirmatory
- Scher JCO 2016 PMID 26921877

**BCR detection** (`prostanet/domains/patient_tracking/post_rp_salvage_copilot_service.py`):
- AUA-ASTRO 2024 + EAU 2026 §5.2: TWO PSAs ≥0.2 separated **21-180 días** (EPIC 29.8 G54)
- >180d ⇒ `bcr_window_audit.status=psa_window_exceeded` (no auto-promote)

**UI "Torre de vigilancia"**:
- PSA Compass section en `templates/patient_profile_v2.html`
- Adapter en `prostanet/presentation/v2_adapters.py`

## 7. Gates clínicos críticos (post-EPIC 29)

| Gate | File | Evidence |
|------|------|----------|
| BCR 2-PSA confirmation (21-180d) | post_rp_salvage_copilot_service.py | AUA-ASTRO 2024 |
| m0_crpc PSADT ≤10mo | arpi_benefit_matrix.py | SPARTAN/PROSPER/ARAMIS |
| CRPC PCWG3 nadir+25%+2ng+confirm | clinical_contradiction_engine.py | Scher JCO 2016 |
| CHAARTED high-volume (≥4 bone+appendicular OR visceral) | various | PMID 26244877 |
| ARASENS triplete visceral | arpi_benefit_matrix.py | PMID 35179323 |
| ERA-223 Ra-223+abi+pred concurrent block | recommendation_arbiter.py | PMID 30853531 |
| CAPRA age REQUIRED | clinical_scores.py | Cooperberg Cancer 2005 |
| Enzalutamide seizure (word-boundary) | recommendation_arbiter.py | AFFIRM label |
| Pembrolizumab Lynch/MSI-H | recommendation_arbiter.py | KEYNOTE-158 |
| PARP HRR+ post-ARSI | recommendation_arbiter.py | PROfound |

## 8. Cortana cards inventory (EPIC 22c/22f)

41+ cards en `templates/patient_profile_v2.html` cada una alimentada por
adapter en `prostanet/presentation/v2_adapters.py`. Test gate
`tests/test_epic22d_ui_data_concordance.py` valida `data-testid` ↔ backend
endpoint binding.

**HDR brachy adapter wired EPIC 29.12 G61** — `_post_brachy_hdr_summary` ya
está en `build_v2_adapter_bundle`.

## 9. Fusion kernel observability (EPIC 29.7 G57)

`prostanet/domains/patient_tracking/clinical_decision_today_fusion_kernel.py`:
- Module-level `logger`
- 4 sub-builders wrapped con `logger.exception()` + `upstream_failures` audit
  trail accumulator
- Surfaceado en `enriched["audit"]["upstream_failures"]` para UI/telemetry

## 10. Model registry — vocab guard (EPIC 28+29.4)

`prostanet/ai/inference/model_registry.py`:
- `IncompatibleCheckpointError` type preserved en metadata
  (`load_error_type`, `incompatible_vocab_version` boolean)
- Banner UI puede diferenciar vocab-mismatch (RETRAIN REQUIRED) vs
  missing-file (artifact path issue)

## 11. Tests autoritativos

- 273/273 EPIC 20-26 sweep
- 73/73 EPIC 22-23 core
- 147/147 wider sweep incluyendo concordance gates
- 1 pre-existing flaky (test_post_rt_copilot_..., OOS-3 documentada línea 6750
  audit_tracking.md) — NO regresión EPIC 29

## 12. Constraint absoluto del usuario

> "NO eliminar lógica clínica ni nada del frontend existente"

Todas las EPIC 22-29 son **append/repair only**. 0 líneas de lógica clínica
eliminadas. Tests pre-existentes que fallan ANTES de EPIC son documentados
como pre-existing, no regresiones nuevas.

## 13. Skills aplicadas (referencia para futuros audits)

- `/anthropic-skills:ultrathink-detective` — investigación profunda
- `/anthropic-skills:pytorch-patterns` + `/pytorch-training` + `/pytorch-lightning`
  — retrain state_transition Transformer NUM_STATES 31→54
- `/voice`, `/voice-update`, `/voice-note-ingest`, `/voice-agents`,
  `/voice-ai-development`, `/voice-ai-engine-development`, `/writing-voice`
- `/faubot` Phase 6 (Data Integrity) — UI-data concordance audit
- `/godibot` — adversarial validation pass 1-5
- `/api-design`, `/backend-patterns`, `/frontend-patterns`, `/ui4`,
  `/ui-component`, `/ui-ux-pro-max`

## 14. Próximos audits sugeridos (no aplicados aún)

- Real GPU PersonaPlex cloud deployment
- Concordance gates escalation WARNING → FAILING
- EHR FHIR integration prep
- Voice-to-arbiter direct extraction (currently 2-step: voice → micro-form → arbiter)
- 22 trayectorias adicionales NCCN 2026 v2 (EPIC 22 mencionó 22 todavía
  pendientes en Phase 2, post-brachy LDR/HDR/EBRT por sub-protocolo, etc.)
