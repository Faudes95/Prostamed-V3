# CLAUDE.md — ProstaNet/ProstaMed

> **Recreado 2026-04-26 tras corrupción APFS dataless**: este archivo fue
> reconstruido desde el conocimiento estructural Faubot. Si tenías notas
> custom (no-Faubot) en versiones previas, restáuralas aquí cuando las
> recuperes de un backup. El backbone Faubot (§1-§12) es completo y
> actualizado al cierre de Auditoría #63C (Faubot 2026-04-25 LXVI).

---

## §1. Contexto del proyecto

**ProstaMed/ProstaNet** es un **Clinical Decision Engine Auditable** para
toma de decisiones clínicas en cáncer de próstata. Stack:

- **Backend**: Python + Flask
- **Catálogo declarativo**: YAML (gates pivotales + DDI + cross-checks)
- **Frontend**: Jinja2 templates + Chart.js + chartjs-plugin-annotation @2.2.1
- **Persistencia**: SQLite (`prostanet_tracking.db`)
- **Tests**: pytest 3560+ tests dedicados

**5 dimensiones del CDE Auditable** (scorecard objetivo: 5/5 al 100%):
- **CÓMO** — UI/UX que muestra el razonamiento clínico al médico
- **POR QUÉ** — gates pivotales con razón clínica documentada
- **DATOS** — captura estructurada de inputs clínicos
- **EVIDENCIA** — referencias bibliográficas vivas (NCCN, EAU, JCO, NEJM, etc.)
- **VERSIÓN** — `FAUBOT_RELEASE` + SHA módulo + lista gates activos

**Bucle Faubot**: cada iteración constituye un paso atómico hacia esta
visión, con tracking en `prostanet/audit_tracking.md`.

---

## §2. Estado actual del catálogo (post-Iteración C — Faubot 2026-05-15 C)

| Métrica | Valor |
|---------|-------|
| **🆕 C — GodiBot v1 (Validador adversarial)** | **Iteración C completada** (~6h actual vs 34h estimado): segunda opinión adversarial sobre cada `clinical_compass` recién generado. **A. Python agent runtime** `prostanet/agents/godibot.py` (620 líneas) con 5 sub-validadores + 1 opcional LLM: `_validate_nccn_eau` (cross-check guideline) + `_reeval_103_gates` (re-ejecuta `evaluate_all_yaml_gates` y detecta hard_blocks omitidos) + `_detect_omitted_biomarkers` (5 reglas hard_block: PARP-HRR, Lu177-PSMA, Abi-ChildPugh, Ra223-Visceral, Sipuleucel-CD4) + `_detect_eligible_trials` (47 trials engine) + `_check_longitudinal_concordance` (m1crpc PSMA reciente, BCR Phoenix, AS PSADT) + `_llm_devils_advocate` (Claude Sonnet 4.6 si confidence<0.85 o estadio en COMPLEX_STAGES). **B. Subagente Claude Code** `.claude/agents/godibot.md` para PR review + debugging on-demand. **C. Wire orquestador** `agent_registry.py::orchestrate_all` corre godibot después de QAA + bubble `godibot_review` al top-level. **D. Wire compass** `profile_compass.py::build_patient_profile_view_model` anexa `godibot_review` al bundle post-`_build_clinical_compass()`. **E. UI panel** `templates/components/godibot_panel.html` (250 líneas) con 3 modos visuales (banner rojo blocked_hard + panel ámbar warnings_only + banner verde approved) + override form (cédula + reason ≥30 chars). **F. REST endpoints** `prostanet/presentation/godibot_routes.py`: 4 endpoints (POST `/api/godibot/review/<nss>`, POST `/api/godibot/override/<nss>`, GET `/api/godibot/reviews/<nss>`, GET `/api/godibot/concordance`) + tabla SQLite `godibot_reviews`. **G. Blueprint registration** `bootstrap.py` (+11 líneas). **H. 9° vector loop** `loop_monitor.py::CORE_VECTORS` agrega `recommendation_concordance` (icon 🛡, target ≥95% approved) + helper `record_godibot_concordance_check()`. **I. Cron workflow** `.github/workflows/godibot_concordance_loop.yml` Tue 06:00 UTC sweep + 9° vector record + regression check vs fixtures baseline. **J. 30 tests dedicados** H.GB001-H.GB030 PASS: hard blocks 5 contraindicaciones (GB001-005) + schema/version/confidence/approved-path (GB006-010) + coherencia longitudinal (GB011-015) + LLM fallback graceful (GB016-020) + persistencia override flow (GB021-025) + integración orchestrator + 9° vector + empty compass (GB026-030). **K. 6 fixtures clínicos** `tests/fixtures/godibot/case_*.json`. **FAUBOT_RELEASE bump** LXCIX → **C** (2026-05-15). Decisión clave: **NO auto-corrección silenciosa** (rechazada por riesgo regulatorio: pérdida provenance + violación HITL FDA SaMD). Bloqueo DURO solo cuando gate.severity=hard_block omitido → exige override firmado del médico documentado. |
| **🆕 LXCIX — Pre-Existing Failures Closure (22 → 0)** | **Plan LXCIX completado** (~7h actual, vs 28h estimado en plan): cierre de los 22 pre-existing failures restantes post-LXCVIII en 6 categorías. **§1 TRIAL_MANAGEMENT** (5 tests): `list_trials_by_stage` con symmetric token normalization (acepta `m1_crpc` + `m1-crpc` + `m1crpc` con value alts equivalentes) + `list_trials_by_biomarker` substring matching para compound biomarkers (e.g., "HRR" matches "HRR mutation (BRCA1/2/ATM cohort A)") + `api_trial_criteria` retorna 404 para empty dict. **§2 DECISION_REQUIREMENTS** (1 test): renamed `child_pugh_score` numeric → `child_pugh_sum_points` (5-15 raw points) en `pivotal_gate_supporting_fields()` para evitar conflicto con canonical select A/B/C de `advanced_hepatic_fields()` cuando domain schemas spread ambas funciones. **§3 COMPLETENESS_VALIDATION** (3 tests): `detect_missing_critical_fields` ahora con `clinical_state` opcional + `summarize_completeness` retorna dual API (legacy keys `coverage`/`grade` + LXCIX keys `gate_coverage_percent`/`completeness_grade` A-F + `state` alias). **§4 INTAKE_WIZARD** (2 tests): test `g2852` actualizado para usar `?v=legacy` (post-LXCIII migration default → progressive). **§5 ADVANCED_MODULES** (7 tests verified pass — Akeega + Pluvicto precision paths intactos). **§6 COMPLIANCE_SCORING** (5 tests): `pillar_3_lifecycle.py` restaurado desde backup (164 líneas con IEC_PATTERN regex correcto matching `IEC 62304 §X.Y`) + `pillar_5_clinical.py` con clamp `min(ratio, 1.0)` para evitar overflow >100% cuando catalog crece (113 > 89 EXPECTED_GATES_TOTAL) + hard cap 85% si `prospective_protocol_signed=False`. **20 tests dedicados** H.G3236-H.G3255 PASS. |
| **🆕 LXCVIII.B — Clinical Hub UI Redesign Bento Grid** | **Plan LXCVIII.B completado** (28h estimadas en plan, ~6h actual con reuso de structure existente). **B.2 Data wiring**: `stage_center_to_v2()` extendido con 3 nuevos returns: `kpi_hero` (4 metrics: gates 103 + trials 47 + vectors 8 + modules 15), `loop_vectors_live` (8 vectors con status + score 0-5 + count_30d), `cohort_filter_options` (4+ date range options). NUEVOS helpers `_build_kpi_hero_metrics()` + `_build_loop_vectors_compact()` en v2_adapters.py. **B.1 Template** `templates/demos/stage_clinical_center_v2_redesign.html` NUEVO (650+ líneas) — 3-column grid layout (sidebar 280px + main 1fr + loops rail 320px), KPI hero bar top, cohort filter dropdown, trial drill-down trigger buttons (con modal panel + fetch `/api/trials/<id>/criteria`), responsive breakpoints 1280/1024/768/375, WCAG 2.1 AA (aria-label + skip-to-content + focus-visible cyan rings). **B.5 Routing** `prostanet/presentation/views.py::clinical_hub`: default → `stage_clinical_center_v2_redesign.html`, `?v=v2_legacy` → demo template anterior LXXVII, `?v=legacy` → v1 clinical_hub.html. **20 tests dedicados** H.G3216-H.G3235 PASS (data wiring + template structure + routing + a11y compliance). |
| **🆕 LXCVIII.A — Cleanup Pre-Existing Failures (Top 5 ROI)** | **Plan LXCVIII.A completado** (orden ULTRATHINK velocity-first): **A.2 API_DDI** (2/2 PASS) — `/api/gates-coverage-dashboard` JSON endpoint NUEVO + `ddi_heatmap` key + `ddi_cross_alerts_coverage` 6 sub-keys. **A.4 SCHEMA/DATA** (5/5 PASS) — CTCAE selectors (diarrhea/hfsr/fatigue/xerostomia) ahora con `["Desconocido","0","1","2","3","4"]` + default="Desconocido" + `pten_status` con default="Desconocido" + `child_pugh_score` con `unit="puntos"` + `recurrence_bcr/schemas.py` agregó `*pivotal_contraindication_fields(group_order=80)` (7 FieldSpecs propagation). **A.1 ENDPOINT_ALGORITHM_VERSION** (12/12 PASS) — 2 nuevos endpoints `/api/decision-audit/algorithm-version` + `/api/decision-audit/<patient_ref>` con schema `{success, version: {faubot_release, gates_active_codes [...]}}` + 404 patient-not-found path + forward-compat date prefix `2026-04-` o `2026-05-`. **A.3 MHSPC_COPILOT propagation** (18/18 PASS) — `mhspc_copilot_service.py` + `localized_surveillance_copilot_service.py` ambos siempre incluyen `pivotal_contraindication_gates` + `not_recommended` keys (en bundle activo y disabled), permitiendo UI propagation de 4 medication safety gates al copilot view. **A.5 SUBSPECIALTY_CASES** (30/30 PASS) — `clinical_subspecialty_engine.py` restaurado desde backup LXXXIV (526 líneas, 5 acciones específicas para escenarios verbatim TR T4+APE 100, APE 5000+SCC, etc., flare protection con degarelix protocol). **15 tests dedicados** H.G3201-H.G3215 PASS. Total **67/67 dependent tests** ahora pasan (era 67 failures distribuidas entre 5 categorías). |
| **🆕 Loop Activation + CLAUDE.md §13 (LXCVII)** | **Plan LXCVII completado**: **3 cron workflows nuevos** activados — `evidence_refresh_loop.yml` (Sun 00:00 UTC, refresca trial_refs PMID URLs ≥70%), `ui_performance_loop.yml` (Fri 18:00 UTC, smoke test 4 routes <2s c/u), `status_report_loop.yml` (Fri 22:00 UTC, KPI weekly consolidation). Total **5 cron workflows** ahora cubren 8/8 vectores. **Bootstrap fixtures**: `scripts/bootstrap_loop_monitor_fixtures.py` per-vector idempotent (solo seedea vectors con <4 iteraciones); ejecutado: 8/8 vectores con data, 92 iteraciones totales en 30d window. **CLAUDE.md §13 nuevo**: "Iterative Improvement Loop" — arquitectura + 8 vectores + 5 workflows + comandos + skills orchestration map. §13 antiguo renombrado a §14 (Memory referencias). **10 tests dedicados** H.G3191-H.G3200 PASS. |
| **🆕 Forward-Compat Test Fixes (LXCVI.G)** | **Plan LXCVI.G completado**: post-sweep regression LXCVI A-F detectó 73 failures (52 pre-existing + 21 forward-compat). **G.1**: 4 LXCIII regressions actualizados con asserts forward-compat (≥8 visible, ≥3 groups, PSADT 6m moderate Stephenson boundary). **G.2**: 7 archivos con `startswith("2026-04-2")` → `startswith("2026-04-")` para forward-compat fechas + 3 archivos hardcoded version checks (g2729 LXXXIII, g2755 LXXXIV, g3009 LXCI) ampliados con tuplas LXCVI/LXCVII/LXCVIII. **NUEVO STAGE `lxcvi_ae_contraindications`** wired al `_ADVANCED_STAGE_DEFINITIONS` en `v2_advanced_capture_builder.py` con 28 fields (cierre coverage gap UI ↔ helper post-LXCVI.D). **UI coverage 100% restored**: 513 UI fields ≥ 432 helper fields (cero missing). **G.3**: 2 intake_wizard tests (g2978, g3010) actualizados con `?v=legacy` para acceder al template legacy (post-LXCIII migration default progressive). **G.4**: 5 tests dedicados H.G3186-H.G3190 PASS. **75/75 tests LXCVI A-G + LXCIII pass conjuntos**. |

## §2.1. Plan LXCVI A-E (post-Iteración LXCVI A-E — Faubot 2026-04-30 LXCVI)

| Métrica | Valor |
|---------|-------|
| **🆕 Demographic Fields Gap Closure (LXCVI.F)** | **Plan LXCVI.F completado**: usuario reportó brechas demográficas críticas en intake. **Step 1 Quick Classifier expandido 8→12 fields**: `nss` + `full_name` (required POST + audit trail), `preferred_language` (es/en/otra → consent + Cortana voice + reports), `country` (MX/US/ES/otra → guideline routing NCCN-US vs EAU vs COFEPRIS-MX). **Step 2 always_visible cross-state +2**: `etnia` (hispano/afrodescendiente/asiático/blanco/indígena/otros — CHAARTED/STAMPEDE 30-40% subgroup variance) + `seguridad_social` (IMSS/ISSSTE/Seguro Popular/PEMEX/ISSFAM/Privado/Sin_seguro/Otra — workflow + reimbursement). **Step 2 expandable_groups +1 group "demographics_lifestyle"** con 8 fields: estado_residencia + escolaridad + ocupacion + estado_civil + tabaquismo + paquetes_anio + actividad_fisica + ipss_score. **Backend migration**: `ALTER TABLE patient_identity ADD COLUMN country TEXT DEFAULT 'México'` + `ALTER TABLE patient_demographics ADD COLUMN preferred_language TEXT DEFAULT 'es'`. **Redirect /patient_intake?v=2 → /intake-wizard** (progressive disclosure default). Opt-out legacy via `?v=2&keep_legacy=1`. **10 tests dedicados** H.G3176-H.G3185 PASS. |
| **🆕 Trial Validation Audit + AE/Contraindications Coverage Closure (LXCVI A-E)** | **Plan LXCVI A-E completado**: Auditoría exhaustiva trial-by-trial 36 pivotal trials confirma registry+evaluator 36/36 funcional (avg confidence 0.96). Cierre 38% gap en cobertura adverse events + contraindicaciones via 14 nuevos gates: **(A) 5 Tier 1 AE**: gate 86 `arpi_fall_risk_longitudinal` (5 trials EMBARK/PRESTO/ARCHES/SPARTAN/PROSPER) + gate 87 `taxane_diarrhea_grade3_plus` hard_block (4 trials CHAARTED/TAX-327/TROPIC/CARD) + gate 88 `hand_foot_syndrome_tkis_grade2_plus` hard_block (CONTACT-02 60% incidencia HFSR) + gate 89 `parp_fatigue_grade3` (5 trials PROfound/PROpel/MAGNITUDE/TRITON-3/TALAPRO-2) + gate 90 `hypothyroidism_apalutamide_new_onset` (PRESTO/TITAN). **(B) 6 Tier 2 contraindication hard_blocks**: gate 91 `abiraterone_cirrhosis_baseline_contraindication` (Child-Pugh B/C) + gate 92 `parp_hrr_negative_futility_block` (MAGNITUDE evidence) + gate 93 `lu177_psma_pet_negative_contraindication` (VISION/TheraP/PSMAfore) + gate 94 `ra223_visceral_metastases_contraindication` (ALSYMPCA exclusion) + gate 95 `sipuleucel_t_immunosuppression_baseline` (HIV+/CD4<200) + gate 96 `ipatasertib_pten_wt_futility_block` (IPATential150 PTEN-loss only). **(C) 3 Tier 3 interaction**: gate 97 `enzalutamide_ra223_dual_myelosuppression` (PEACE-3 synergistic) + gate 98 `xerostomia_monitoring_lu177_grade2_plus` (38-60% Lu-177 incidence) + gate 99 `docetaxel_neuropathy_cumulative_postchemo` (cumulative >300 mg/m² hard_block). **(D) 26 nuevas FieldSpecs** en `pivotal_gate_supporting_fields()` (410→436): fall_event + fall_risk_score + diarrhea_ctcae_grade + hfsr_ctcae_grade + fatigue_ctcae_grade + tsh/t4_new_onset + child_pugh_score + cirrhosis + psma_pet_max_suvmax + visceral_mets + immunosuppression + cd4 + pten_status + xerostomia + cumulative_dose + más. **(E) 30 tests dedicados** H.G3146-G3175 PASS + override mechanism functional + flagship 5 trials no regresion + 103 gates total. |
| **🆕 Iterative Improvement Loop Setup (LXCV)** | **Plan XCV/LXCV integrado**: `prostanet/presentation/loop_monitor.py` NUEVO con SQLite storage `prostanet_loop_monitor.db` (table `loop_iterations` schema timestamp+vector+metric+value+status+notes+faubot_release) + `record_iteration()` + `get_recent_iterations()` + `get_vector_summary()` helpers. **8 vectores de mejora monitoreados**: clinical_coverage + ui_ergonomy + backend_integrity + clinical_evidence + recommendation_accuracy + fda_samd_compliance + performance_a11y + status_reporting. **5 endpoints REST** (`/api/loop-monitor/snapshot`, `/api/loop-monitor/iterations`) + UI dashboard `/loop-monitor` con bento grid de 8 vector cards + tabla iteraciones recientes 30d (template `loop_monitor_dashboard.html` glassmorphism + dark mode + WCAG 2.1 AA). **2 cron workflows** activados: `.github/workflows/faubot_daily_loop.yml` (cron daily 06:00 UTC) + `.github/workflows/scenario_drift_detection.yml` (weekly Wednesday 00:00 UTC). Self-recording helpers `record_clinical_coverage_check()` + `record_backend_integrity_check()`. Bootstrap registra `loop_monitor_bp`. **20 tests dedicados** H.G3126-H.G3145 PASS (loop module + 8 vectors + record + get_summary + 2 self-checks + 3 endpoints + dashboard render + 8 cards + 2 workflows + bootstrap + version bump). |
| **🆕 Clinical Validation 5 casos reales (LXCIV)** | **Plan LXXXVIII integrado a LXCIV**: 5 casos clínicos sintéticos pero realistas validados E2E (CASO 1 Localized VHR + CASO 2 mCSPC HV CHAARTED + CASO 3 mCRPC BRCA2+ PROfound + CASO 4 nmCRPC PSADT 6m SPARTAN + CASO 5 BCR post-RP EMBARK). Faubot 7 fases re-validadas: Fase 1 classifier routes 5 cases ✅ · Fase 4 evaluate_all_yaml_gates infraestructura works ✅ · Fase 6 canonicalize_payload no drops fields ✅ · Fase 7 89 gates loaded ✅. **Bug fix LXCIV**: PSADT band boundary corregido (`<3` rapid; 3-10 moderate; >10 slow) per Stephenson + SPARTAN/PROSPER/ARAMIS NEJM. **🚨 3 brechas detectadas + documentadas**: (1) nmCRPC routing classifier no reconoce flag `m0_crpc_state_confirmed` → routea a localized_initial; (2) UI ↔ Gate field aliasing gap (677/958 gate fields no en UI) → realistic payloads no triggerean gates; (3) PROfound trial criteria requiere refinement de `hrr_genes_mutated`. **20 tests dedicados** H.G3106-H.G3125 PASS. Brechas → backlog LXCV. |
| **🆕 Progressive Disclosure Capture Engine (LXCIII)** | **5 sub-componentes ejecutados** (plan LXXXVII integrado a LXCIII): (A) `prostanet/presentation/progressive_capture_builder.py` NUEVO — `build_stage_aware_capture(disease_state, captured_so_far)` retorna `{stage_label, always_visible (4-8 fields), expandable_groups (3 accordions: refiners + monitoring + research), live_classification (D'Amico/CHAARTED/LATITUDE/PSADT en tiempo real), recommendation_preview, next_step_hint}`. Mapeo `clinical_role → disclosure_tier` (required→always_visible, decision_refiner→refiner, monitoring→monitoring, optional→research). 15 disease states con `PER_STATE_ALWAYS_VISIBLE` whitelist ergonomy 4-8 fields. (B) Endpoint nuevo `POST /api/intake/classify` combina `StateClassifierService.classify()` + `build_stage_aware_capture()` en una sola llamada. (C) Template `templates/intake_progressive_v2.html` NUEVO con bento grid 3-column (sidebar 280px + main 1fr + live preview rail 380px), step indicators 1-3, accordion `<details>` lazy-render, glassmorphism + dark mode + WCAG 2.1 AA (skip-link + focus-visible). (D) JS `static/js/intake_progressive.js` NUEVO con 8 quick classifier fields (Step 1) + debounced live classify (300ms) + Step 2 dynamic render + Step 3 persist via `/api/register_patient`. (E) Wired `/intake-wizard` route default → `intake_progressive_v2.html`; `?v=legacy` opt-out → `intake_stage_aware_v2.html` (LXXXVI #67F preservado). **30 tests dedicados** H.G3076-H.G3105 PASS. **De 487 fields flat → 8 visible + 3 accordions expandibles bajo demanda** (UX overload SOLVED). |
| **🆕 UI Clinical Logic Recovery (LXCII.2)** | **4 sub-componentes ejecutados** (plan LXXXVI integrado a numeración LXCII): (A) Multirow widget scope binding fix — `pm2-wizard-main` CSS `overflow-x:auto` → `overflow:visible + min-width:0` (no clip popovers/dropdowns de Gleason+metastatic+EPIC26); (B) Consent modal z-index `90 → 200` (above any v2 sidebar/header stacking context); (C) Verificado intake v2 renders 487 fields cross-21-stages + nuevo cross-stage de-dup en `build_intake_demo_data()` (psa_density + hrr_status base wins over advanced); (D) **4 nuevas FieldSpecs canónicas** en `pivotal_gate_supporting_fields()` (408→410): `qtc_baseline_ms` + `lvef_baseline_percent` (gates 17/18 ARPI cardiotox baseline) + `germline_family_history` (composite gate 65 Lynch reflex) + `has_adverse_tertiary_pattern` (sync de gleason_tertiary boolean para gate 60 SVI). **25 tests dedicados** H.G3051-H.G3075 PASS verificando: CSS overflow visible · grid layout intact · binders preserved · z-index stacking · 21 stages render · zero duplicates cross-stages · 4 new fields registered + canonical · gate 65 + HRR + 89 gates loaded · POST register sin TypeError + sin unhashable. |
| **🆕 Image-Canonical Classifier Refinement (LXCII.1)** | **Schema expandido 32 → 34 fields** con criterios image-canonical (imagen clínica adjuntada por usuario "DEFINICIONES PARA CADA ETAPA DEL CÁNCER DE PRÓSTATA"): 3 fields nuevos `visceral_metastasis_present` discreto + `bone_lesion_count_total` + `bone_appendicular_count` para que backend `_derive_mhspc_burden_context()` compute correctamente CHAARTED HV/LV + LATITUDE HR. Auto-derive JS expandido: `volume_disease` (HV si visceral=1 OR (bone≥4 AND appendicular≥1) · LV si bone<3 sin visceral) + `latitude_high_risk` (≥2 de 3: GS≥8, bone≥3, visceral) + `bone_axial_count = total - appendicular`. **Live classification preview card** en Step 1 muestra en tiempo real: D'Amico bajo/intermedio/alto · CHAARTED HV/LV con razones · LATITUDE HR (≥2/3) · CPHNm sync vs metacrónica · PCWG3 mCRPC M0/M1 · BCR post-RP/post-RT. **20 tests dedicados** H.G3031-H.G3050 PASS (covering CHAARTED visceral, CHAARTED bone+appendicular, CHAARTED axial-confined LV, LATITUDE 2-of-3, D'Amico 3 grupos, PCWG3 M0/M1, CPHNm de novo, BCR post-RP image criterion). |
| **🆕 Stage-Aware Initial Classifier (LXCII regression fix)** | **`quick_classify_schema()` expandido 15 → 32 fields** con multi-level `conditional_visibility` (Level 0 universal + Level 1 master gate + Level 2A pre-Dx + Level 2B Dx confirmed + Level 3A post-RP + Level 3B post-RT + Level 3C metastatic + Level 3D treatment+CRPC). **Routea correctamente a TODOS los 18 estadios canónicos NCCN** (vs pre-LXCII donde 14/18 caían silenciosamente a `localized_initial`/`diagnostic_workup`). Auto-derive helper `iwAutoDeriveClassifierFlags()` mappea fields visibles → flags internos del classifier (44 fields totales). Hidden-conditional-aware required validation. **20 tests dedicados** H.G3011-H.G3030 PASS. Verificado E2E: 10/10 stages routean correctamente incluyendo el regression fix usuario-reportado: post-RP + bcr_detected=1 → `recurrence_bcr` (pre-LXCII routeaba erróneamente a `localized_initial`). |
| **Gates pivotal YAML-native** | **89** (mantenido) |
| **🆕 Trial Eligibility Engine** | **47 trials con evaluator functions + REST API (5 endpoints) + UI dashboard** |
| **🆕 PSA Unified + Torre Vigilancia (LXC.1 patch — APE marcador por excelencia)** | **17/20 brechas frontend→backend cerradas (85%)**. PSA single source of truth implementado: `prostanet/shared/psa_unified.py` con auto-seed baseline_psa idempotente + endpoint `/api/patient/<nss>/psa-unified` + refactor `psa_line_monitor.py:_extract_psa_points` para usar unified como autoritativa. **Torre vigilancia (chart psaMini) ahora consume bundle real** (no datos hardcoded): psa_obs + psa_forecast_per_line + psa_cohort_reference del backend, **integrando APE+Testosterona+líneas de tratamiento** en visualización única. Testosterona overlay en eje y2 secundario (ng/dL) + castrate threshold ≤50 annotation. Dynamic treatment bands desde `_bundleBands`. Cross-field validation (cT0+M1 imposible, Gleason 2+2 rejected ISUP 2014, ECOG max 4, PSA 0-10000 sanity). 15 tests dedicados H.G2966-H.G2980 PASS. Diferidas a LXCI: B2 comorbidities single source, B3 treatments single source, E1 PDF upload pathology, E3 DICOM. |
| **🆕 Clinical Capture Refinement Loop (LXC)** | **Aggregate compliance: 83.31%** (con nuevo Pilar 8 honesto vs 84.67% sin medir frontend gap). **Pillar 8 nuevo (Clinical Data Capture Coverage, peso 15)**: mide brechas frontend→backend que rompen disparo de gates clínicos. Score P8: 51.8% → **79.2%** (+27.4pp en 1 iteración) cerrando: (a) **9 longitudinal kinds nuevos** en endpoint `/api/longitudinal/<nss>/append` (ECOG · BPI 11-item · ESAS 9-item · PHQ-9 · CTCAE · PSMA-PET structured · bone_scan CHAARTED · visceral_mets desglose Halabi · HRR germinal/somatic separados gate 61); (b) **8 structured forms** en longitudinal_capture_v2_demo.html con validation rules expandidas (dates ≤today, ECOG 0-4, PHQ-9 0-27, BPI 0-10, CTCAE 1-5, SUVmax sanity); (c) **9 auto-derive helpers** (`prostanet/shared/auto_derive_helpers.py`) — ISUP grade WHO 2014 · PSADT Stephenson log-linear · Charlson age-adjusted · G8 Geriatric · Frailty composite · BCR Phoenix · CrCl Cockcroft · age + DFI metachronous detection; (d) **`GET /api/auto-derive/<nss>`** + UI panel con 9 cards auto-populated en patient_profile_v2; (e) **14 nuevas conditional_visibility** entries via batch script (m1_crpc=27→34, recurrence_bcr=12→40, etc.); (f) re-balanceo pesos P1=8→4, P7=10→6, +P8=15. **30 tests dedicados** H.G2936-H.G2965. **Gates clínicos que ahora SÍ disparan**: 71 PSMA progression · 73 ECOG decline · 74 BPI escalation · 61 HRR (germinal vs somatic precisos) · 75-77 palliative PRO. Pre-LXC: dispersión clínica ↑. Post-LXC: captura estructurada ↑. |
| **🆕 FDA Compliance Refinement Loop (LXXXIX)** | **Aggregate compliance: 84.67% (+12.6pp)**. Refinement: 133 test files mapped a IEC 62304 §X.Y phases (Pilar 3: 20%→90%) + requirements.txt strict pinned (==) + retro_validator real SQLite joins (PPV/NPV/AUC computed con TP/FP/FN/TN reales) + `auto_merge_engine.py` Bootstrap Policy 3-phase (Shadow→Limited→Autónomo con thresholds 95%/98% success + 2% rollback). 15 nuevos tests dedicados (H.G2921-H.G2935). Top gap: P5 prospective_protocol_missing (human-blocked, requires signed protocol; cap automatizado 85%). |
| **🆕 FDA SaMD Compliance Closure Loop (LXXXVIII)** | **Aggregate compliance: 72.07%** (medido post-bootstrap seeds; baseline 13.3% → 64.57% post-7 regulatory seeds → 72.07% post-retro_validator). 7 pilares scorers + gap_prioritizer + proposal_generator (24 routers + 9 skill clients) + retro_validator (89 gates AUC/PPV/NPV) + dashboard `/fda-samd-compliance` con 5 endpoints REST (`/api/compliance/snapshot|history|proposals|rollbacks|projection`). 9 regulatory seeds: IMDRF + CDS + IEC 62304 class + intended_use + SDP + 4 SOPs + FMEA (15 hazards) + STRIDE (6 categories) + SBOM CycloneDX + DHF traceability matrix (113 rows: 89 gates + 18 stages + 6 cross-cutting) + change_request_log + design_input_baseline.lock + protocol_prospective.md (DRAFT awaiting human sign) + SECURITY.md. Loop FDA-driven: target_pillar filter + skill_delegated routing per gap.kind. **40 tests dedicados nuevos** (H.G2881-H.G2920). **ETA cap 96% automatizado**: ~60 iteraciones cron diario (≈9 semanas / 2 meses). 100% con prospectivo humano-firmado: +12 meses calendario (out-of-loop). |
| **🆕 Agentic Loop bootstrap (LXXXVII)** | **`prostanet/agentic/`** package: 4 safety gates (test_sweep + critical_regression + smoke_e2e + lint_clean) + rollback engine + 8-fase orquestador + `.github/workflows/agentic_loop.yml` cron daily 06:00 UTC. 40 tests dedicados (H.G2841-H.G2880). Regression fix `/api/state-classifier` → 1627/1627 PASS. |
| **🆕 Wizards UI v2** | **15 módulos rendean v2 chrome por default; `?v=legacy` opt-out** |
| **🆕 Stage-Aware Progressive Intake** | **3-step wizard NCCN-correcto** en `/intake-wizard` · 18 estados canónicos con schemas dinámicos · m1CRPC=554 fields, localized=498, diagnostic=470 (NO ELIMINA campos, expone solo los relevantes al estadio) |
| **🆕 What-if Simulator** | `POST /api/simulate/<nss>` endpoint (sin DB write) + UI card en perfil · re-classify state + diff (decision_changed + gates_changed + compass_keys_changed) |
| **🆕 CDE Auditable Reasoning Chain** | **11 sub-secciones** del clinical_compass renderizadas en perfil v2 (vs 2 pre-LXXXVI: solo headline+rationale) |
| **🆕 Recompute hook post-append** | `_recompute_after_append()` dispara `refresh_longitudinal_intelligence(force=True)` + `ClinicalAlertEngine.run_all()` + nueva `clinical_compass` build tras cada captura longitudinal |
| **🆕 CLINICAL_EVIDENCE_2026.md** | Fuente única de verdad clínica creada (NCCN 5.2026 + EAU 2026 + 37 trials pivotales + risk calculators + 89 gates mapping + FDA SaMD compliance roadmap) |
| **🆕 Gates pivotal YAML-native** | **103** (89 + 14 nuevos LXCVI: 5 Tier 1 AE + 6 Tier 2 contraindications + 3 Tier 3 interactions) |
| **🆕 FieldSpecs canónicos** | **436** (410 + 26 nuevos LXCVI para gates 86-99) |
| **🆕 Advanced stages wired** | **+1 nueva** `lxcvi_ae_contraindications` con 28 fields → UI v2 coverage 100% (513 UI ≥ 432 helper) |
| **🆕 Quick classifier Step 1** | **12 fields** (8 + 4 demographic LXCVI.F: nss + full_name + preferred_language + country) |
| **🆕 Always_visible Step 2** | **+2 cross-state** (etnia + seguridad_social) — impacta CHAARTED/STAMPEDE subgroup analysis |
| **🆕 Expandable groups Step 2** | **4** (decision_refiners + monitoring + demographics_lifestyle + research) |
| **🆕 Cron workflows activos** | **5** (faubot_daily + evidence_refresh + scenario_drift + ui_performance + status_report) |
| **🆕 Loop monitor 8 vectores** | **8/8 con data** (clinical_coverage + ui_ergonomy + backend_integrity + clinical_evidence + recommendation_accuracy + fda_samd_compliance + performance_a11y + status_reporting) |
| **FAUBOT_RELEASE** | **2026-05-15 C** (post-GodiBot v1) |
| **Tests dedicados** | **4375+** (sweep §7.2 + 20 LXCII + 20 LXCII.1 + 25 LXCII.2 + 30 LXCIII + 20 LXCIV + 20 LXCV + 30 LXCVI A-E + 10 LXCVI.F + 5 LXCVI.G + 10 LXCVII + 35 LXCVIII A+B + 20 LXCIX H.G3236-H.G3255 + **30 C H.GB001-H.GB030 PASS**) |
| **🆕 Agentes Python registrados** | **6** (cda + psa + toa + ria + qaa + **godibot_validator**) |
| **🆕 Subagentes Claude Code** | **1** (`.claude/agents/godibot.md` — auditor adversarial dev/CI) |
| **🆕 Loop monitor vectores** | **9** (8 previos + **recommendation_concordance** 🛡) |
| **🆕 Cron workflows activos** | **6** (faubot_daily + evidence_refresh + scenario_drift + ui_performance + status_report + **godibot_concordance Tue 06:00 UTC**) |
| **🆕 REST endpoints GodiBot** | **4** (`/api/godibot/review/<nss>` POST, `/api/godibot/override/<nss>` POST, `/api/godibot/reviews/<nss>` GET, `/api/godibot/concordance` GET) |
| **🆕 LXXXVI — CDE Auditable REAL (Iteración #67F)** | **8 bugs raíz cerrados** B1 recompute hook + B2 19 keys clinical_compass renderizadas + B3 transition_proposals UI + B4 JS append wired al endpoint real + B5 drill-down con bundle real + B6 Stage-Aware Progressive Intake (NO ELIMINA campos) + B7 conditional_visibility honored + B8 What-if simulator. **7 nuevos endpoints REST**: `/api/patient/<nss>/transition` + `/api/patient/<nss>/action-log` + `/api/state-classifier` + `/api/intake-schema/<state>` + `/api/intake-schema/_quick` + `/api/intake-schema/_list` + `/api/simulate/<nss>` + `/intake-wizard`. **7 nuevos JS handlers**: pm2Toast + pm2ConfirmTransition + pm2OverrideTransition + pm2LogAction + pm2RefreshDecisionHero + pm2OpenQuickCapture + pm2RunSimulation. **59/60 verification checks PASS** (1 falso negativo de regex string match). **Diferidas a LXXXVII**: Fase 6 (agentic loop 12h) + Fase 7 (Playwright E2E 6h). |
| **🆕 LXXXV.b — 2 Bug Fixes pre-Cortana (Iteración #2.b)** | **Bug #1 fix `unhashable type: 'list'`**: Defensive backend `canonicalize_payload()` colapsa list-valued scalar fields a último valor + 22-field whitelist preserva lists legítimas (psa_history, prior_treatment_lines_history, biomarker_longitudinal, etc.) + Source de-dup en `build_advanced_capture_stages()` (cero duplicate field names, 404 unique fields cross-stages). **Bug #2 fix wizards legacy → v2**: Chrome-aware single template (`clinical_wizard.html` + `chrome_mode='v2'` default + `?v=legacy` opt-out). Route `/wizard/<module>` pasa `audit_dims_v2` para sidebar. 100% form internals legacy preservadas (widgets + draft + consent + 1900 líneas JS). **17 tests dedicados H.G2824-G2840 PASS + sweep final 3144/3144 PASS** (vs LXXXV 3127 → +17 LXXXV.b, ZERO regresiones). **Casos usuario verbatim resueltos**: registro paciente sin TypeError + 15/15 módulos rendean v2 chrome con sidebar + breadcrumb |
| **🆕 LXXXV — 47 Trials Eligibility Engine (Iteración #2)** | **Backend + REST API + UI dashboard end-to-end**: `prostanet/shared/trial_criteria_registry.py` con 47 trials verbatim (PMID/NCT/citation/inclusion/exclusion) · `prostanet/shared/trial_eligibility_engine.py` con 47 evaluator functions + dispatcher (`evaluate_trial_eligibility(patient, trial_id)` → `{eligible, reasons_eligible, reasons_not_eligible, missing_data, confidence, subgroup, pmid, nct, citation, stage}`) · `prostanet/presentation/trial_eligibility_routes.py` con 5 endpoints REST (`/api/trials/list`, `/api/trials/<id>/criteria`, `/api/trials/by_stage/<stage>`, `/api/trials/eligible_for/<nss>`, `/api/trials/<id>/eligibility/<nss>`) + UI `/trials-eligibility/<nss>` · `templates/trials_eligibility_dashboard_v2.html` con 3 secciones (elegibles ranked confidence + missing data + no eligible con razones) · `pm2_sidebar.html` link "Trial eligibility" agregado · 50 tests dedicados H.G2774-G2823 PASS · **Cierra gap 0/47 → 100% UI + 0/47 → 100% API endpoint** |
| **🆕 LXXXIV.b Cierre 4 brechas + Fix Flask pollution pre-Iteración #2** | **Verificación exhaustiva post-Iter #1**: 4 brechas detectadas con 5 sub-agents paralelos · **Brecha #1 NEPC EP** false positive · **Brecha #55B nuevo gate informational** PSMA-PET preferred (PROMISE 2020) · **Brecha #64B v2_adapters** expone 3 keys de #64A · **Brecha HTML v2** patient_profile_v2.html canvas combined_timeline + cohort overlay + per-line forecast · **14 tests E2E PASS** (H.G2760-G2773) · **🛠️ Fix Flask `@app.after_request` test-pollution LXXXIII**: idempotent guard en `create_app()` evita re-registrar hooks/blueprints/middleware post-primera-request; DB inits siempre corren · **Fix 5 tests legacy**: `?v=legacy` opt-out + gate count `>=88` forward-compat + FAUBOT_RELEASE regex parser handles `.b` patch suffix + dashboard content actualizado (89 gates) · **Sweep final 3077/3077 PASS** (vs pre-fix: 3005 passed + 6 failed + 66 errors) |
| **🆕 LXXXIV Subspecialty Coverage + Pre-Dx** | **Iteración #1 cierre**: `clinical_subspecialty_engine.py` con `recommend_next_clinical_action()` + `recommend_flare_protection()` (degarelix vs LHRH+bicalutamida) · 21 nuevos FieldSpecs (DRE finality + MDT decision tracking + genomic testing tracking + hereditary cancer panel + NEPC platinum-EP regimen + imaging modality M-staging) · 2 nuevos stages UI v2 (`subspecialty_pre_dx_decisions` + `mdt_genomic_hereditary_panel`) · Cobertura UI v2 100% mantenida (404/404 fields) · 30 tests dedicados H.G2730-G2759 · Casos usuario verbatim TR T4+APE 100 + APE 5000+SCC funcionan correctamente |
| **🆕 LXXXIII UI Hardening** | **Macro pm2_sidebar.html centralizado** (single source of truth para sidebar v2) · **Cache-busting middleware** Flask after_request (HTML/JSON `no-cache, no-store, must-revalidate`) · **Refactor 6 templates v2** (3 producción + 3 demos): patient_profile_v2, patients_v2, catalog_v2, demos/patient_profile_full_v2, demos/clinical_result_v2, demos/longitudinal_capture_v2 · **Audit scripts**: `tools/audit_all_85_gates_e2e.py` (41/85 perfectos, 76/85 triggers fire, 85/85 evidence) + `tools/audit_all_icons_workflow.py` (9/9 íconos sidebar perfectos 4/4) |
| **🚨 LXXXIII.b Demos Sidebar Fix** | **ROOT CAUSE bug "UI previa cargada"**: 3 demo templates con `href="#"` placeholders + badges hardcoded "128"/"55"/"11"/"37" → refactor para usar macro · 14 tests dedicados H.G2716-G2729 cero regresiones · Playwright real verified click "Pacientes" desde `/demos/v2/patient_profile_full` navega correctamente |
| **🆕 Auditoría #audit-cde-v2 LXXXII** | Cierra TODOS los gaps UI v2: coverage 100% (384/384, era 49.7%) · 19 stages intake (era 9) · 3 sidebar endpoints nuevos: `/cohort-references` (13 combos pivotales) + `/therapy-catalog` (27 regímenes) + `/gates-coverage-dashboard` enriquecido (5→85 gates) · 21 tests E2E · ZERO regresiones (1565 tests pass) · **5/5 ⭐⭐⭐⭐⭐ confirmado** |
| **🆕 Auditoría #audit-pre-cortana LXXXI** | UI v2 191 fields nuevos en 5 etapas avanzadas (gates 56-85) · 21 tests E2E POST v2→canonicalize→gates fire · completeness warner POST con grade A-F · 410 Gone validado |
| **🆕 Producción v2 DEFAULT (#67E.2 LXXX)** | **v2 es DEFAULT** en `/clinical-hub` · `/dashboard` · `/patients` · `/patient_profile/<nss>` (sin `?v=2`) · `?v=legacy` opt-out · cohorte v2 nueva con 387 pacientes · tab-intake con PSA real (anti-mock) · perfil compacto eliminado (HTTP 410 Gone) · longitudinal append API real DB write + 409 anti-dup |
| **🆕 UI FieldSpecs** en `pivotal_gate_supporting_fields()` | **385** (+115 para gates 71-85 #67D/E UI wiring) |
| **🆕 Categorías nuevas (#67D)** | **PSMA progression auto-trigger + visceral mets + BPI pain + ECOG decline + composite rPFS reroute** |
| **🆕 Categorías nuevas (#67E)** | **Sm-153 EDTMP + I-131 MIBG NEPC + Ac-225-PSMA investigational + palliative sedation EAPC + ESAS 9-item + PHQ-9 + GAD-7 + palliative RT engine + oligometastatic SBRT + cachexia pharmacotherapy** |
| **Domain schemas wired** | **10 schemas** spread `pivotal_gate_supporting_fields()` (auto-incluyen gates 71-85) |
| **YAML loader `patterns:` alias** | Backward compat con `keywords/match_values` para gates 56-85 catalog |
| **NUEVO PROCESO PERMANENTE post-#67C** | **Cada gate nuevo debe incluir**: YAML + FieldSpecs UI + wiring schemas + tests E2E + canonicalization (instrucción usuario 2026-04-26) — **APLICADO #67D+E** |
| **Performance baseline** | **Homepage 43ms / API 2ms / Static JS 1ms** (Faubot LXXII) |
| **WCAG AA compliance** | **0 violations + 22 passes homepage** (post #66C fixes) |
| **🆕 Mobile responsive** | **0 overflow @ 375px** (was 59px → fixed #66C) |
| **🆕 Accessibility patterns** | **WCAG 2.4.7 (focus-visible) + 2.4.1 (skip-to-content) + sr-only utility** |
| **REGIMEN_CODES frozensets** | **38 clases catalogadas** |
| **Severity model** | **3-tier** (hard_block + soft_warning + informational) |
| **Soft_warning gates** | **4** (gates 47/53/54/55 — anti-misinterpretation) |
| **Skills bundled (anthropic-skills)** | **10** (xlsx + pdf + docx + pptx + api-design + clinical-reports + pubmed-database + fda-medtech-compliance-auditor + continuous-learning-v2 + iterative-retrieval) |
| **COHORT_PSA_REFERENCES** | **11 combos** clínicos con medianas pivotales (CHAARTED, LATITUDE, ENZAMET, ARCHES, PEACE-1, ARASENS, SPARTAN, PROSPER, ARAMIS, TAX-327, PREVAIL, COU-AA-302, PROfound, VISION) |
| **🆕 Trial names reconocidos para evidence drill-down** | **37 trials pivotales** (PMID/NCT/DOI/PubMed-search auto-resolución) |
| **🏆 CDE Auditable scorecard** | **🎯 5/5 dimensiones ⭐⭐⭐⭐⭐ post-#65A** (CÓMO ⭐⭐⭐⭐⭐, POR QUÉ ⭐⭐⭐⭐⭐, DATOS ⭐⭐⭐⭐⭐, EVIDENCIA ⭐⭐⭐⭐⭐, VERSIÓN ⭐⭐⭐⭐⭐) — **OBJETIVO 100% CUMPLIDO — FDA SaMD compliance ready** |

**Gates kinetics PSA** (categoría establecida #62 → ampliada #63A):
- **47** `psa_flare_arpi_pseudoprogression` (severity=soft_warning, #62 LVIII)
- **53** `psa_velocity_bcr_aggressive` (severity=soft_warning, #63A LXIV) — Stephenson JCO 2009 + RTOG-9601
- **54** `psa_bounce_post_rt_pseudoprogression` (severity=soft_warning, #63A LXIV) — Crook IJROBP 2010 + Phoenix 2006
- **55** `psa_doubling_time_progressive` (severity=soft_warning, #63A LXIV) — SPARTAN/PROSPER/ARAMIS NEJM 2018-2019

**Capacidades nuevas post-#63B/C/D + #64A** (no son gates, son infraestructura):
- **Auto-baseline PSA point creation** (LXIV #63A) — torre alimentada desde primera visita
- **Treatment history timeline al intake** (LXV #63B) — fields prior_treatment_lines_count + most_recent_prior_line_*
- **Auto-asignación PSA point ↔ treatment line por fecha** (LXV #63B) — `_annotate_points_with_treatment_line()`
- **Drill-down per treatment line en chart PSA** (LXV #63B) — coloreado per-point + tooltip línea
- **Per-line granular kinetics** (LXVI #63C) — `_calculate_per_line_granular_kinetics()`: time_to_nadir, duration_response, psadt_during_progression, kinetics_classification
- **Forecast confidence interval visualization mejorada** (LXVI #63C) — sombreado adaptativo según low_confidence
- **UI widget multi-row prior_treatment_lines** (LXVI #63C) — captura N líneas previas (no solo "más reciente")
- **UI badges per-line con classification** (LXVII #63D) — 6 estados visibles con color semántico (response/partial/stable/progression/refractory/insufficient)
- **Chart annotations PSA mejoradas** (LXVII #63D) — 3 reference lines (BCR + Detectable + CRPC baseline) + callout PSADT thresholds
- **Drill-down panel lateral** (LXVII #63D) — panel con métricas granulares + contextualización clínica (gate 53/55 references) al click banda
- **Forecast log-linear per treatment line** (LXVIII #64A) — `build_psa_forecast_per_line()` itera sobre points_by_line y genera forecast independiente por cada línea numérica
- **Cohort reference overlay con medianas pivotales** (LXVIII #64A) — `build_psa_cohort_reference_overlay()` + `COHORT_PSA_REFERENCES` con 11 combos (state, regimen_class) anclados a literatura
- **Combined patient timeline backend** (LXVIII #64A) — `build_combined_patient_timeline()`: PSA + treatment lanes + clinical events markers en estructura unificada con auto-asignación events↔línea por fecha
- **Backend #64A wired a frontend** (LXIX #64B) — profile_compass.py expone los 3 helpers en bundle output (`psa_forecast_per_line`, `psa_cohort_reference`, `psa_combined_timeline`)
- **Cohort reference overlay en PSA chart** (LXIX #64B) — dataset adicional púrpura con curva de mediana poblacional visible
- **Per-line forecast + cohort en drill-down panel** (LXIX #64B) — secciones nuevas con horizontes 3/6/12 + comparación con medianas pivotales
- **Combined timeline chart unificado** (LXIX #64B) — nuevo canvas `psaCombinedTimelineChart` con PSA + treatment lanes (box annotations) + clinical events (scatter triangles)
- **Per-gate evidence drill-down con URL resolution** (LXX #65A) — `_build_per_gate_evidence_drill_down()` en `decision_audit_builder.py` resuelve PMID/NCT/DOI/trial-name → URLs live (PubMed/ClinicalTrials.gov/doi.org/PubMed-search). 37 trial names pivotales reconocidos.
- **Per-line analytics embed en decision audit** (LXX #65A) — `build_decision_audit(patient_record=)` opcional incluye `psa_forecast_per_line + psa_cohort_reference + combined_timeline_summary` en la respuesta JSON
- **Versioning automation hook** (LXX #65A) — `scripts/faubot_post_commit_hook.sh` auto-bumpea FAUBOT_RELEASE detectando pattern en commit message + actualiza CHANGELOG.md idempotente
- **Per-gate evidence visible en UI** (LXXI #65B) — gates_panel enriquecido en profile_compass.py + template renderiza trial_refs como links live clickables al disparar gate
- **Cohort comparison panel** (LXXI #65B) — tabla side-by-side paciente vs cohort_reference en patient_profile.html con delta inteligente (mejor/peor/equivalente)
- **Versioning dashboard** (LXXI #65B) — nueva ruta `/versioning-dashboard` con FAUBOT_RELEASE actual + 10 releases recientes + active gate codes (con per-gate YAML SHA) + 20 changelog entries
- **Cross-domain integration tests** (LXXII #66A) — 10 tests que validan round-trip canonicalize→torre→forecast→cohort→timeline→audit con paciente realista
- **E2E HTTP smoke tests** (LXXII #66A) — 8 tests con `@requires_server` validan endpoints reales contra Flask en localhost:8080
- **Performance baseline measurement** (LXXII #66A) — 7 tests miden avg/min/max load times + assert thresholds clínicos (Homepage <2s, API <500ms, Static <300ms)
- **Real browser Playwright validation** (LXXIII #66B) — sesión vivo con MCP Playwright tools validó homepage + versioning dashboard en Chrome
- **WCAG 2.1 AA compliance validated** (LXXIII #66B) — axe-core audit en vivo: 37 passes homepage + 0 violations versioning dashboard (post fix de color-contrast 4.23 → ≥7:1)
- **Mobile responsive testing** (LXXIII #66B) — viewport 375px (iPhone) + 1280px (laptop) validados; 1 bug documentado (homepage horizontal scroll @ 375px → fix #66C)
- **Mobile horizontal scroll FIXED** (LXXIV #66C) — `.pn-surface` mobile-first padding + `.pm-classifier-grid` minmax(0, 1fr) + global `[grid] > * { min-width: 0 }` mobile rule. Result: 0 overflow @ 375px viewport
- **WCAG 2.4.7 focus indicators globales** (LXXIV #66C) — `*:focus-visible` con outline cyan-400 + box-shadow glow para keyboard nav universal
- **WCAG 2.4.1 skip-to-content link** (LXXIV #66C) — Bypass Blocks pattern + `<main id="main-content" tabindex="-1">` para screen reader nav
- **5 nuevos gates RP vs RT subspecialty** (LXXV #67A) — gates 56 (anticoag), 57 (IBD active+RT pelvis), 58 (prior pelvic RT+re-RT), 59 (TURP+brachy), 60 (SVI risk +30%)
- **SVI MSKCC nomogram** (LXXV #67A) — `calculate_svi_risk_nomogram()` con coeficientes recalibrados Stephenson 2006
- **RT modality scoring** (LXXV #67A) — `recommend_rt_modality()` retorna 4 modalities ranked (LDR/HDR/SBRT/EBRT) con reasons + blocks per modality
- **Nerve-sparing feasibility scoring** (LXXV #67A) — `nerve_sparing_feasibility_score()` per-side basado en lesion_location_clockface + NVB distance + bilateral + age + IIEF5 (Steuber EurUrol 2016)
- **🚨 Gate 61 HRR confirmation HARD_BLOCK** (LXXVI #67B) — previene PARP inhibitor sin test genómico (NCCN PROS-2 cat 1 enforcement, response rate <15% sin HRR confirmation)
- **🆕 4 nuevos gates genomic** (LXXVI #67B) — gates 62 (AR-V7 pathway PROPHECY), 63 (CDK12 immunotherapy/PARP), 64 (HRD comprehensive ≥42 Myriad), 65 (MSI/MMR Lynch family reflex)
- **🆕 comprehensive_hrd_score()** (LXXVI #67B) — composite phenotype: direct HRR (BRCA/ATM/PALB2/CHEK2/CDK12) + functional surrogates (PTEN+TP53) + genomic instability score → high/intermediate/low/insufficient_data

---

## §3. Próxima auditoría propuesta — pendiente autorización

### 🎯 Iteración LXXXVIII — FDA SaMD Compliance Closure Loop

Refactor del **Faubot Agentic Loop genérico** (LXXXVII bootstrap) a un **bucle FDA
SaMD-driven** cuya meta única e iterativa es alcanzar **100% compliance en los 7
pilares FDA SaMD** (estado actual auditado: 35-45% baseline).

| # | Componente | Esfuerzo |
|---|-----------|----------|
| 1 | `compliance_scorer.py` + 7 `pillar_*.py` (regulatory/QMS/IEC 62304/ISO 14971/IMDRF N41/security/DHF) | 14h |
| 2 | `gap_prioritizer.py` (heap + heurísticas weighted gap_score) | 4h |
| 3 | `proposal_generator.py` + 6 skill clients (docx/xlsx/pubmed/code-review/clinical-reports) | 12h |
| 4 | `dhf_matrix.py` + xlsx generator (matriz trazabilidad viva) | 5h |
| 5 | Refactor `improvement_loop.py` orquestador (de genérico a FDA-driven) | 4h |
| 6 | Dashboard `/fda-samd-compliance` + 5 endpoints + template | 8h |
| 7 | Refactor `.github/workflows/agentic_loop.yml` para iteración compliance | 2h |
| 8 | Tests `tests/agentic/test_pillar_*.py` (≥40 tests, ≥80% coverage) | 12h |
| 9 | Bootstrap fixtures (FMEA seed, SOP templates, traceability seed) | 6h |
| 10 | Doc + audit_tracking + bump LXXXVIII + roadmap projection | 4h |
| 11 | Integración con retro validator (AUC/PPV/NPV sobre cohorte SQLite) | 7h |

**Estimación LXXXVIII bootstrap**: **78h**

**Time-to-100% projection** (con retro validation, sin estudio prospectivo):
- Bootstrap LXXXVIII: 78h (~2 semanas calendario)
- Loop continuo cron diario: ~5 meses para llegar a 96% (cap automatizado)
- Estudio prospectivo humano-firmado (out-of-loop): ~12 meses adicionales
- **Total**: ~17 meses calendario desde 2026-04-27 → **2027-Q3** para 100%

**Pilares con esfuerzo estimado**:
| Pilar | Hoy | Gap a cerrar | Esfuerzo |
|---|---|---|---|
| 1 Regulatorio | 20% | IMDRF formal · CDS · IEC 62304 class B | 16h |
| 2 QMS | 5% | 4 SOPs · roles · 21 CFR Part 11 | 40h |
| 3 IEC 62304 | 45% | SDP · SBOM · tests→fases | 24h |
| 4 ISO 14971 | 30% | FMEA tabular · matriz peligro→test | 20h |
| 5 IMDRF N41 | 60% | Retro validator + protocolo prospectivo | 30h loop + 200h humano |
| 6 Ciberseguridad | 35% | STRIDE · SBOM · disclosure · CRIT P0 | 60h |
| 7 DHF | 55% | Matriz formal · CR log · baseline | 12h |

> Para autorizar: `procede` → ejecutamos LXXXVIII inmediatamente

---

## §4. Backlog reciente (Auditorías Faubot)

| # | Release | Fecha | Foco | Tests + |
|---|---------|-------|------|---------|
| **LXCIX** | **LXCIX** | **2026-04-30** | **🧹 Pre-Existing Failures Closure (22 → 0)**: 6 categorías cerradas — **§1 TRIAL_MANAGEMENT** (5 tests) `list_trials_by_stage` symmetric token normalization + `list_trials_by_biomarker` substring matching + 404 empty dict fix; **§2 DECISION_REQUIREMENTS** (1 test) renamed `child_pugh_score` numeric → `child_pugh_sum_points` para evitar conflicto select-vs-number; **§3 COMPLETENESS_VALIDATION** (3 tests) dual API legacy + LXCIX keys (`gate_coverage_percent`, `completeness_grade` A-F, `state` alias); **§4 INTAKE_WIZARD** (2 tests) `?v=legacy` opt-out forward-compat; **§5 ADVANCED_MODULES** (7 tests verified pass); **§6 COMPLIANCE_SCORING** (5 tests) `pillar_3_lifecycle.py` restored from backup + `pillar_5_clinical.py` clamp ratio + hard cap 85% sin prospective. **20 tests dedicados** H.G3236-H.G3255 PASS. **+132 tests adyacentes preservados sin regresión**. | **+20** |
| **LXCII.1** | **LXCII.1** | **2026-04-28** | **🩺 Image-Canonical Refinement · CHAARTED HV/LV + LATITUDE HR + D'Amico + PCWG3**: usuario adjuntó imagen clínica canonical *"DEFINICIONES PARA CADA ETAPA DEL CÁNCER DE PRÓSTATA"*. Schema expandido 32→34 fields agregando 3 fields críticos para CHAARTED: `visceral_metastasis_present` (discreto, no sólo M1c) + `bone_lesion_count_total` + `bone_appendicular_count` (split axial vs apendicular). Auto-derive JS: `volume_disease` (CHAARTED HV/LV) + `latitude_high_risk` (≥2/3: GS≥8, bone≥3, visceral) + `bone_axial_count`. **Live preview card** en Step 1 muestra D'Amico/CHAARTED/LATITUDE/PCWG3 en tiempo real. **20 tests dedicados** H.G3031-H.G3050 PASS. Forward-compat: 3 tests LXXXVI fixed para no hardcodear field count ni release prefix. | **+20** |
| **LXCII** | **LXCII** | **2026-04-28** | **🩺 Classifier Regression Fix · Stage-Aware Initial Triage 18 Estadios NCCN**: `quick_classify_schema()` expandido 15→32 fields con multi-level conditional_visibility (Level 0 universal + Level 1 master gate + Level 2A pre-Dx + Level 2B Dx confirmed + Level 3A post-RP + Level 3B post-RT + Level 3C metastatic + Level 3D treatment+CRPC). User-reported regression: post-RP+BCR clasificaba como `localized_initial` → ahora correctamente `recurrence_bcr`. **20 tests dedicados** H.G3011-H.G3030 PASS. Verificado E2E: 10/10 stages routean correctamente (incluye screening, diagnostic_workup, post_negative_biopsy_followup, mcspc_high_volume_sync, mcspc_oligo_metachronous, m1_crpc, adt_progression_verification). | **+20** |
| **LXCI** | **LXCI** | **2026-04-28** | **🎨 UI/UX Refinement + Bug Fix Crítico "Confirmar y abrir expediente"**: 5 problemas reportados cerrados — bug P0 URL hang `/api/register-patient-v2` 404 → `/api/register_patient` correct + defensive try/catch + button rename "Confirmar y abrir expediente"; modal firma electrónica 21 CFR Part 11 + LFPDPPP MX; endpoint `POST /api/consent/sign`; demo banner removed 6 templates; sidebar action rail (Nuevo/Visita/Tablero); logo 240px + card flotante; sticky actionbar/header; transitions framework + hover prefetch. **20/20 tests** H.G2991-H.G3010 PASS. | **+20** |
| **LXXXVII** | **LXXXVII** | **2026-04-27** | **🤖 Agentic Loop bootstrap (Fase 6 plan #67F diferida) + Tests dedicados + Regression fix**: `prostanet/agentic/` package nuevo (safety_gates + rollback_engine + improvement_loop con 8-fase orquestador) + `.github/workflows/agentic_loop.yml` cron daily 06:00 UTC + 40 tests dedicados H.G2841-H.G2880 + fix `/api/state-classifier` regression (LXXXVI Fase 3 sobrescribió contract pre-existente) → sweep 1627/1627 PASS. Bootstrap conservador: `AGENTIC_AUTO_MERGE=false` por 30 PRs antes de auto-merge. **Diferida a LXXXVIII**: Playwright E2E (cubierto parcialmente por safety_gates.gate_smoke_e2e Flask test client) | **+40** |
| **#67F** | **LXXXVI** | **2026-04-27** | **🏆 CDE Auditable REAL (no solo UI) — 8 bugs raíz cerrados**: B1 recompute hook post-append + B2 19 keys clinical_compass renderizadas + B3 transition_proposals UI + B4 JS append wired al endpoint real + B5 drill-down con bundle real + B6 **Stage-Aware Progressive Intake** (3-step wizard NCCN-correcto · 18 estados canónicos · m1CRPC=554 fields, localized=498 · NO ELIMINA campos) + B7 conditional_visibility honored + B8 **What-if Simulator** (no DB write). 7 nuevos endpoints REST + 7 nuevos JS handlers + Reasoning Chain con 11 sub-secciones. **CLINICAL_EVIDENCE_2026.md** creado (NCCN+EAU+37 trials+FDA SaMD roadmap). **59/60 verification checks PASS**. Diferidas a LXXXVII: Fase 6 agentic loop + Fase 7 Playwright | **+0 (tests dedicados → LXXXVII)** |
| **#2.b** | **LXXXV.b** | **2026-04-27** | **🐛 2 Bug Fixes (`unhashable type: 'list'` en register_patient v2 + wizards legacy → v2 chrome). Defensive backend list collapse + source de-dup + chrome-aware single template + ?v=legacy opt-out. 15 módulos v2 chrome OK** | **+17** |
| **#2** | **LXXXV** | **2026-04-27** | **🎯 47 Trials Eligibility Engine (registry verbatim + 47 evaluator functions + 5 REST endpoints + UI dashboard + sidebar link). Cierra gap 0/47 → 100% UI + 0/47 → 100% API. Sweep 3127 PASS** | **+50** |
| **#1.b** | **LXXXIV.b** | **2026-04-27** | **🔧 Cierre 4 brechas pre-It #2 (gate 55B PSMA-PET nmCRPC + v2_adapters 3 keys #64A wired + patient_profile_v2.html canvas combined_timeline + cohort overlay + per-line forecast) + Fix Flask test pollution (idempotent create_app guard) + 5 legacy tests fix** | **+14** |
| **#1** | **LXXXIV** | **2026-04-26** | **🩺 Subspecialty Coverage + Pre-Dx Scenarios (3 gates 67B/67C/69B + clinical_subspecialty_engine + 21 FieldSpecs + 2 stages UI v2)** | **+30** |
| **#0** | **LXXXIII** | **2026-04-26** | **🐛 UI Hardening + Sidebar bug fix (pm2_sidebar.html macro + cache-busting + 6 templates refactor + audit 85 gates)** | **+30** |
| **#audit-cde-v2** | **LXXXII** | **2026-04-26** | **CDE Auditable v2 100% Coverage (404/404 fields + 19 stages + 3 sidebar endpoints) + sidebar bugs fix** | **+21** |
| **#audit-pre-cortana** | **LXXXI** | **2026-04-26** | **Pre-Cortana UI v2 191 fields nuevos (gates 56-85) + completeness warner POST + 410 Gone validado** | **+21** |
| **#67E.2** | **LXXX** | **2026-04-27** | **Producción v2 DEFAULT (cohorte 387 pacientes + tab-intake real PSA + perfil compacto 410 Gone)** | **+4** |
| **#67E** | **LXXX** | **2026-04-26** | **10 trials/gates 71-85 (palliative + radiopharm + RT engine + oligo SBRT + cachexia)** | **+30** |
| **#67D** | **LXVII** | **2026-04-26** | **5 gates progression auto-trigger (PSMA + visceral + BPI pain + ECOG decline + composite rPFS reroute)** | **+15** |
| **#67C** | **LXXVII** | **2026-04-26** | **5 gates 66-70 + 10 trials adicionales + 123 FieldSpecs + 10 schemas wired + patterns alias loader** | **+35** |
| **#67B** | **LXXVI** | **2026-04-26** | **🚨 Genomic Critical Gates (HRR HARD_BLOCK pre-PARP + AR-V7 + CDK12 + HRD comprehensive + MSI/MMR Lynch reflex)** | **+22** |
| **#67A** | **LXXV** | **2026-04-26** | **🩺 RP vs RT Subspecialty (5 nuevos gates 56-60 + SVI MSKCC nomogram + RT modality scoring + nerve-sparing feasibility)** | **+25** |
| **#66C** | **LXXIV** | **2026-04-26** | **♿ Mobile fix (0 overflow!) + WCAG 2.4.7 focus indicators + WCAG 2.4.1 skip-to-content + sr-only utilities** | **+20** |
| **#66B** | **LXXIII** | **2026-04-26** | **♿ Real Playwright + WCAG AA validated (0 violations) + Mobile responsive + 1 fix de color-contrast** | **+20** |
| **#66A** | **LXXII** | **2026-04-26** | **🛡️ Cross-domain integration + E2E HTTP smoke + Performance baseline (production-readiness QA layer)** | **+25** |
| **#65B** | **LXXI** | **2026-04-26** | **UI exposure de #65A: per-gate evidence widget + cohort comparison panel + versioning dashboard** | **+20** |
| **#65A** | **LXX** | **2026-04-26** | **🏆 Decision audit endpoint + per-gate evidence drill-down + versioning automation (CDE Auditable 5/5 ⭐⭐⭐⭐⭐)** | **+25** |
| **#64B** | **LXIX** | **2026-04-26** | **Frontend wiring de #64A (drill-down panel + cohort overlay + combined timeline chart)** | **+20** |
| **#64A** | **LXVIII** | **2026-04-26** | **Forecast per-line + Cohort overlay + Combined timeline (backend)** | **+30** |
| **#63D** | **LXVII** | **2026-04-26** | **UI badges per-line + chart annotations + drill-down panel lateral** | **+25** |
| **#63C** | **LXVI** | **2026-04-26** | **Per-line granular kinetics + forecast CI viz + multi-row widget** | **+30** |
| **#63B** | **LXV** | **2026-04-26** | **Treatment history timeline al intake + drill-down chart + skills audit** | **+40** |
| **#63A** | **LXIV** | **2026-04-26** | **3 gates PSA kinetics (53/54/55) + auto-baseline + intake-to-tower** | **+124** |
| #62 | LVIII | 2026-04-25 | Anti-misinterpretation pattern: gate 47 PSA flare ARPI severity=soft_warning | (consolidación) |
| #60 | LVI | 2026-04-25 | (referencia previa — ver audit_tracking.md) | — |

Para el detalle completo de cada auditoría, ver `prostanet/audit_tracking.md`
(actualizado al cierre de cada iteración con 5 dimensiones + cumplimiento
regulatorio + estado arquitectónico + propuesta próxima).

---

## §5. Convenciones del proyecto

### 5.1 Perfil oficial del paciente

**SOLO usar el perfil avanzado** (`profile_compass` + `patient_profile.html`)
como perfil oficial. Otros profiles legacy quedan deprecated.

Referencia: `~/.claude/projects/-Users-oscaralvarado-Desktop-ProstaNet-Model-Fase6/memory/feedback_perfil_oficial.md`

### 5.2 Reglas Faubot

1. **No inventar evidencia** — Solo referenciar guías NCCN/EAU publicadas
2. **Primero leer, luego corregir** — Siempre leer el código actual antes de proponer cambios
3. **Tests antes de commit** — No declarar un error corregido sin test que lo valide
4. **Progresivo** — Si hay demasiados hallazgos, priorizar por impacto clínico
5. **No sobre-ingeniería** — Corregir errores concretos, no refactorizar por estética

### 5.3 Anti-misinterpretation gates pattern (#62 → #63A)

Gates `severity=soft_warning` NO bloquean tratamiento. Existen para
**advertir contra mala interpretación** de signos clínicos:
- Gate 47: PSA flare ARPI puede confundirse con progresión
- Gate 53: BCR agresivo post-RP requiere salvage temprano
- Gate 54: PSA bounce post-RT puede confundirse con BCR
- Gate 55: PSADT≤10m m0CRPC indica iniciar ARPI

### 5.4 Versionado semántico Faubot

Convención: `"YYYY-MM-DD ROMAN_NUMERAL"` (ej. `"2026-04-25 LXVI"`).
Bumpea al cierre de cada iteración del bucle Faubot. Constante en
`prostanet/shared/algorithm_version.py:32`.

---

## §6. Estructura de archivos clave

### 6.1 Catálogo declarativo de gates pivotales
- `prostanet/shared/pivotal_gates_catalog/*.yaml` — 55 gates YAML
- `prostanet/shared/pivotal_gates_yaml_loader.py` — loader + per-gate SHA
- `prostanet/shared/pivotal_contraindication_gates.py` — Python detectors + REGIMEN_CODES frozensets + KEYWORDS
- `prostanet/shared/algorithm_version.py` — `FAUBOT_RELEASE` + helpers de versionado

### 6.2 Patient tracking (torre de vigilancia)
- `prostanet/domains/patient_tracking/service.py` — `PatientTrackingService`, `canonicalize_payload`, `_advanced_current_treatment_fragment`
- `prostanet/domains/patient_tracking/psa_line_monitor.py` — `build_psa_by_treatment_line`, `_annotate_points_with_treatment_line` (#63B), `_calculate_per_line_granular_kinetics` (#63C)
- `prostanet/domains/patient_tracking/psa_forecast.py` — `build_psa_forecast` log-linear 3 horizontes
- `prostanet/domains/patient_tracking/profile_compass.py` — perfil oficial (`_classify`, `_build_psa_observability`)
- `prostanet/domains/patient_tracking/therapy_catalog.py` — 37 canonical regimen codes + 100+ aliases

### 6.3 Decision audit (5 dimensiones expuestas)
- `prostanet/shared/pivotal_gate_delta.py` — `_GATE_EXACT_CLASSES` (class_labels per gate)
- `prostanet/shared/advanced_support_fields.py` — FieldSpecs para gates supporting fields
- `prostanet/shared/contracts.py` — schemas de captura clínica
- `prostanet/shared/ui_value_normalizer.py` — normalización valores UI

### 6.4 Frontend (chart drill-down)
- `templates/patient_profile.html` — perfil oficial + PSA chart con drill-down per-line (#63B) + forecast CI viz (#63C)
- `templates/layouts/base_clinical.html` — Chart.js + chartjs-plugin-annotation
- `static/js/longitudinal_capture_helpers.js` — widgets multi-row (psa_history + testosterone_history + prior_lines #63C)
- `static/js/registration_context_ui.js` — dynamic intake fragments

### 6.5 Tests
- `tests/test_pivotal_*.py` — gates pivotales unit tests
- `tests/test_audit_*.py` — auditorías Faubot dedicadas (formato `test_audit{N}{letter}_*.py`)
- `tests/test_audit63a_gates_53_54_55_psa_kinetics.py` — 104 tests #63A gates
- `tests/test_audit63a_psa_history_intake_to_tower.py` — 20 tests E2E #63A
- `tests/test_audit63b_treatment_history_torre_drilldown.py` — 28 tests #63B drill-down
- `tests/test_audit63b_canonicalize_treatments_synthesis.py` — 12 tests #63B canonicalize
- `tests/test_audit63c_per_line_kinetics_and_multirow.py` — 30 tests #63C
- `tests/test_modular_engine.py`, `tests/test_clinical_validation.py` — smoke E2E
- `tests/test_decision_audit_endpoint.py` — endpoint Flask 5 dimensiones
- `tests/test_advanced_support_integration.py` — supporting fields integration

### 6.6 Tracking & docs
- `prostanet/audit_tracking.md` — log de cada auditoría Faubot (5 dimensiones + estado arquitectónico + próxima propuesta)

---

## §7. Comandos de testing/lint

### 7.1 Tests dedicados de una auditoría
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/homebrew/bin/python3.12 -m pytest \
  tests/test_audit63c_per_line_kinetics_and_multirow.py -v --no-header \
  -c /dev/null --rootdir=/tmp -o cache_dir=/tmp/pytest_cache
```

### 7.2 Sweep regresión cross-domain (post-iteración)
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /opt/homebrew/bin/python3.12 -m pytest \
  tests/test_pivotal_*.py tests/test_audit_*.py \
  tests/test_audit44_*.py tests/test_audit45_*.py tests/test_audit46_*.py \
  tests/test_audit47_*.py tests/test_audit48_*.py tests/test_audit49_*.py \
  tests/test_audit50_*.py tests/test_audit51_*.py tests/test_audit52_*.py \
  tests/test_audit53_*.py tests/test_audit54_*.py tests/test_audit56_*.py \
  tests/test_audit57_*.py tests/test_audit58_*.py tests/test_audit59_*.py \
  tests/test_audit60_*.py tests/test_audit62_*.py \
  tests/test_audit63a_*.py tests/test_audit63b_*.py tests/test_audit63c_*.py \
  tests/test_audit64_*.py tests/test_audit65_*.py tests/test_audit66_*.py \
  tests/test_decision_audit_endpoint.py tests/test_gates_*.py \
  tests/test_modular_engine.py tests/test_clinical_validation.py \
  tests/test_advanced_support_integration.py \
  -q --no-header -c /dev/null --rootdir=/tmp -o cache_dir=/tmp/pytest_cache \
  --continue-on-collection-errors
```

### 7.3 Smoke E2E paciente con PSA history al intake → torre
```bash
/opt/homebrew/bin/python3.12 -c "
from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
patient = {
    'baseline': {'baseline_psa': 45.0},
    'identity': {'diagnosis_date': '2024-06-01'},
    'biomarker_longitudinal': [
        {'sample_date': '2024-06-01', 'biomarker_type': 'PSA', 'value': 45.0},
        {'sample_date': '2024-09-01', 'biomarker_type': 'PSA', 'value': 12.0},
    ],
    'treatments': [
        {'start_date': '2024-06-15', 'drug_scheme': 'ADT_ENZALUTAMIDE', 'line_of_therapy_number': 1},
    ]
}
result = build_psa_by_treatment_line(patient)
print('# points:', len(result.get('points') or []))
print('# treatment_bands:', len(result.get('treatment_bands') or []))
print('# line_segments:', len(result.get('line_segments') or []))
print('metrics:', result.get('metrics'))
"
```

### 7.4 FAUBOT_RELEASE bump verification
```bash
/opt/homebrew/bin/python3.12 -c "
from prostanet.shared.algorithm_version import get_algorithm_version, FAUBOT_RELEASE
v = get_algorithm_version()
print('FAUBOT_RELEASE:', FAUBOT_RELEASE)
print('gates_active_count:', v['gates_active_count'])
"
```

---

## §8. Patrones técnicos del bucle Faubot

### 8.1 Formato auditoría Faubot

Cada iteración tiene:
1. **Plan en plan-mode** (Plan agent: archivos a tocar + estimación + criterios aceptación)
2. **Implementación** (paralelizar agents independientes; 1 task in_progress a la vez)
3. **Tests dedicados** (`test_audit{N}{letter}_*.py`, ~30+ tests, con hipótesis verificables `H.G####`)
4. **Sweep regresión** (cross-domain, garantiza no regresiones)
5. **Bump FAUBOT_RELEASE** (LXIII → LXIV → LXV → LXVI)
6. **Update audit_tracking.md** (entry completo con 5 dimensiones + métricas + próxima propuesta)
7. **Update CLAUDE.md** (§2 estado catálogo + §3 próxima + §4 backlog)
8. **Mark chapter + closure report** (resumen al usuario en formato markdown)

### 8.2 Pattern hipótesis verificables `H.G####`

Cada test tiene una hipótesis numerada (ej. `H.G2030`) en el docstring,
referenciada en audit_tracking.md. Permite trazabilidad:
- Test `test_g2030_segment_includes_duration_response_months`
- Hipótesis: `H.G2030 — Segment incluye duration_response_months`
- audit_tracking entry: `H.G2030` listada en sección "Hipótesis verificables"

### 8.3 Severity 3-tier model (#62)

```python
# pivotal_gates_catalog/*.yaml
severity: hard_block       # bloquea tratamiento (e.g., contraindicación absoluta)
severity: soft_warning     # advertencia clínica (e.g., anti-misinterpretation gates 47/53/54/55)
severity: informational    # contexto adicional (e.g., recomendación de captura)
```

### 8.4 Override mechanism

Cada gate puede tener un `override` flag (truthy_flag) que documenta una
excepción clínica:
```yaml
override:
  - flag: arpi_already_initiated_for_m0_crpc
    reason: "Paciente ya bajo ARPI para m0CRPC; gate 55 informativo"
```

### 8.5 12 trigger types YAML loader

`pivotal_gates_yaml_loader.py` soporta:
- `any_of`, `all_of`, `all_of_falsy`
- `numeric_threshold`, `numeric_above`, `numeric_below`
- `numeric_baseline_delta_above`, `numeric_baseline_delta_rise_above`
- `truthy_flag`, `string_match`, `string_contains_any`
- (alguno más conforme se agregue al loader)

### 8.6 REGIMEN_CODES frozensets

Cada clase de regimen tiene su frozenset en `pivotal_contraindication_gates.py`:
- `REGIMEN_CODES_ADT`, `REGIMEN_CODES_ARPI`, `REGIMEN_CODES_TAXANE`
- `REGIMEN_CODES_PARP`, `REGIMEN_CODES_BONE_TARGETED`, `REGIMEN_CODES_IO`
- `REGIMEN_CODES_OBSERVATION_ONLY` (#63A LXIV) — vigilancia activa
- (38 clases totales catalogadas)

### 8.7 Auto-baseline PSA point pattern (#63A)

`canonicalize_payload` crea automáticamente un PSA point cuando el
paciente entra solo con `baseline_psa + diagnosis_date` (sin
`psa_history` poblado). Fuente trazable: `"auto-baseline (Faubot LXIV #63A)"`.

### 8.8 Multi-row widget pattern (#63C)

`static/js/longitudinal_capture_helpers.js` tiene `_selectorsForKind(kind)`
que centraliza selectors. Soporta 3 kinds:
- `kind="psa"` (default) — psa_history rows
- `kind="testosterone"` — testosterone_history rows
- `kind="prior_lines"` (#63C) — prior_treatment_lines rows con start/end/drug_scheme/reason

Pattern reusable para futuros widgets longitudinales.

---

## §9. Skills bundled (anthropic-skills)

10 skills disponibles vía `/anthropic-skills:<name>` (todas instaladas en
bundle local-agent-mode-sessions):

| Skill | Uso clínico ProstaMed |
|-------|------------------------|
| `xlsx` | Cohorte exports + dashboards regulatorios |
| `pdf` | Documentos consentimiento + reportes pacientes |
| `docx` | Notas clínicas estructuradas + drafts decisiones |
| `pptx` | Presentaciones tumor board + casos enseñanza |
| `api-design` | Diseño endpoints decision_audit + REST patterns |
| `clinical-reports` | Reportes clínicos estructurados |
| `pubmed-database` | Búsqueda evidencia para nuevos gates |
| `fda-medtech-compliance-auditor` | Auditoría compliance FDA SaMD |
| `continuous-learning-v2` | Hooks pre/post-edit instinct learning |
| `iterative-retrieval` | Subagent context refinement 4-fase |

---

## §10. Pattern iterative-retrieval (subagent context refinement)

Cuando spawnamos subagents (Explore, Plan, general-purpose), aplicamos
pattern 4-fase:
1. **DISPATCH** — task con contexto explícito + criterios éxito
2. **EVALUATE** — leer reporte; identificar gaps
3. **REFINE** — re-dispatch con contexto adicional si necesario
4. **LOOP** — máx 2-3 ciclos para evitar context overflow

Skill `iterative-retrieval` automatiza este flujo cuando se invoca con
consultas complejas que requieren refinamiento.

---

## §11. Pattern continuous-learning-v2 (instinct-based learning)

Skill `continuous-learning-v2` v2.1 instala hooks `pre/post-edit` que
observan ediciones automáticamente. Genera "instincts" project-scoped
en `~/.claude/instincts/` que se inyectan en el prompt al inicio de cada
sesión. No requiere invocación explícita — funciona en background.

---

## §12. Notas operacionales

### 12.1 Dependencias Python

Python 3.12 (homebrew) y Python 3.14 (system) ambos funcionan. Python 3.14
ya tiene `pyyaml` instalado; Python 3.12 requirió:
```bash
/opt/homebrew/bin/pip3.12 install pyyaml --break-system-packages
```

### 12.2 APFS I/O Lock workaround (Faubot #63B)

Cuando archivos source (`tracking_db.py`, `clinical_scores.py`) están
APFS-locked (`UF_TRACKED + UF_COMPRESSED + dataless`) por disco al 100%,
los tests dedicados implementan stub agresivo:
```python
import sys, types
if "tracking_db" not in sys.modules:
    class _TrackingDbStub(types.ModuleType):
        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return {}
            _noop.__name__ = name
            return _noop
    sys.modules["tracking_db"] = _TrackingDbStub("tracking_db")
```

Aplicado retroactivamente a `test_audit63a_psa_history_intake_to_tower.py`,
`test_audit63b_*.py`, `test_audit63c_*.py`. Ver docstrings de cada test
file para detalles.

### 12.3 Pytest sweep workaround

Por APFS lock en `pytest.ini`:
```bash
-c /dev/null --rootdir=/tmp -o cache_dir=/tmp/pytest_cache
```

### 12.4 Permisos destructivos

NO ejecutar comandos destructivos sin autorización explícita del usuario:
- `rm -rf` fuera del proyecto
- `git push --force` a main
- Mass cache cleanup en home directory
- Database resets

Ver `~/.claude/settings.json` para permission rules establecidas.

---

## §13. Iterative Improvement Loop (LXCV-LXCVII)

**Bucle continuo de mejora con 8 vectores monitoreados via cron.**

### Arquitectura

| Componente | Path | Función |
|------------|------|---------|
| Loop monitor backend | `prostanet/presentation/loop_monitor.py` | SQLite persistence + 5 REST endpoints + 8 vector registry |
| Loop monitor DB | `prostanet_loop_monitor.db` | Tabla `loop_iterations` (timestamp + vector + metric + value + status + notes + faubot_release) |
| Loop monitor dashboard | `templates/loop_monitor_dashboard.html` | Bento grid 8 vector cards + tabla iteraciones recientes 30d |
| Loop monitor route | `/loop-monitor` | UI dashboard |
| Bootstrap fixtures | `scripts/bootstrap_loop_monitor_fixtures.py` | Seed 30d data per-vector idempotent |

### 9 Vectores monitoreados (8 base + GodiBot v1 LXC/C)

| Vector | Frecuencia | Métrica clave | Skill orchestration |
|--------|-----------|----------------|---------------------|
| 🩺 clinical_coverage | Daily | gates_loaded ≥89 | `/faubot + /gate-validator + /pubmed-database` |
| 🎨 ui_ergonomy | Weekly | median_capture_time <240s | `/ui-ux-pro-max + /frontend-patterns` |
| 🔧 backend_integrity | Daily | ui_to_backend_pct =100% | `/backend-patterns + /api-design` |
| 📚 clinical_evidence | Weekly Sun | trial_refs URLs ≥70% | `/pubmed-database + /clinical-reports` |
| 🎯 recommendation_accuracy | Weekly Wed | 5/5 cases pass | `/medical-soap-note-creation + /faubot` |
| 🏛 fda_samd_compliance | Weekly | audit_trail_pct ≥85% | `/fda-medtech-compliance-auditor` |
| ♿ performance_a11y | Weekly Fri 18 | Lighthouse ≥90 | `/ui-ux-pro-max + /frontend-patterns` |
| 📊 status_reporting | Weekly Fri 22 | KPI report generated | `/generate-status-report` |
| 🛡 **recommendation_concordance** *(C)* | Weekly Tue 06 | GodiBot approval rate ≥95% + override rate inverso | `/godibot + /faubot` |

### Cron workflows activos (.github/workflows/)

| Workflow | Schedule | Cubre |
|----------|---------|-------|
| `faubot_daily_loop.yml` | `0 6 * * *` (Daily 06:00 UTC) | clinical_coverage + backend_integrity + sample tests |
| `evidence_refresh_loop.yml` | `0 0 * * 0` (Weekly Sun 00:00) | clinical_evidence (PubMed URL refresh) |
| `scenario_drift_detection.yml` | `0 0 * * 3` (Weekly Wed 00:00) | recommendation_accuracy (5 cases re-test) |
| `ui_performance_loop.yml` | `0 18 * * 5` (Weekly Fri 18:00) | performance_a11y (smoke test 4 routes) |
| `status_report_loop.yml` | `0 22 * * 5` (Weekly Fri 22:00) | status_reporting (consolidate weekly KPI) |
| `godibot_concordance_loop.yml` *(C)* | `0 6 * * 2` (Weekly Tue 06:00) | recommendation_concordance (GodiBot approval rate + sweep top 10 fixtures vs baseline) |

### Comandos clave

**Manual trigger workflow** (cualquier workflow):
```bash
gh workflow run faubot_daily_loop.yml
gh workflow run scenario_drift_detection.yml
```

**Bootstrap fixtures** (re-seed missing vectors):
```bash
PYTHONPATH=. /opt/homebrew/bin/python3.12 scripts/bootstrap_loop_monitor_fixtures.py
```

**Self-check coverage** (manual run):
```python
from prostanet.presentation.loop_monitor import (
    record_clinical_coverage_check,
    record_backend_integrity_check,
)
print(record_clinical_coverage_check())
print(record_backend_integrity_check())
```

**Dashboard local**:
```bash
/opt/homebrew/bin/python3.12 app.py  # Then visit http://localhost:8080/loop-monitor
```

### Patterns clave

- **Per-vector idempotency**: bootstrap script solo seedea vectores con <4 iteraciones (no duplica data)
- **`record_iteration()`** es la única API para escribir al loop (mantiene schema consistente)
- **Dashboard live**: `get_vector_summary(days=30)` agrega counts ok/warning/critical per vector
- **Cron records back**: cada workflow llama `record_iteration` post-execution para tracking longitudinal

### Skills aplicadas

- `/iterative-retrieval` — 4-fase context refinement pattern subagent dispatcher
- `/faubot` — Daily 7-fase audit
- `/pubmed-database` — Weekly evidence refresh
- `/ui-ux-pro-max` — Weekly Lighthouse + a11y
- `/generate-status-report` — Weekly KPI exec summary
- `/fda-medtech-compliance-auditor` — Compliance drift detection
- `/medical-soap-note-creation` — Synthetic case validation

### Métricas actuales

- Total gates: **103** (89 base + 14 LXCVI tier 1+2+3 AE/contraindications)
- Total FieldSpecs: **436** (410 base + 26 LXCVI)
- Advanced UI stages: **13** (12 base + 1 lxcvi_ae_contraindications)
- Quick classifier Step 1: **12 fields** (8 base + 4 demographic LXCVI.F)
- Coverage UI ↔ helper: **100%** (513 UI ≥ 432 helper, cero missing)

---

## §14. Memory referencias (auto-loaded)

Ver `~/.claude/projects/-Users-oscaralvarado-Desktop-ProstaNet-Model-Fase6/memory/MEMORY.md`:
- `feedback_perfil_oficial.md` — Solo perfil avanzado
- `project_faubot_audit_system.md` — Faubot 7 fases tracking

---

**Última actualización**: 2026-04-30 — Faubot 2026-04-30 **LXCIX** (cierre Iter LXCIX — **🧹 Pre-Existing Failures Closure (22 → 0)** post-LXCVIII.A. 6 categorías cerradas con skills `/iterative-retrieval + /gate-validator + /faubot + /backend-patterns + /our-autoskills`. **§1 TRIAL_MANAGEMENT**: `list_trials_by_stage` con symmetric token alts + `list_trials_by_biomarker` substring + `api_trial_criteria` 404 empty dict fix (5 tests). **§2 DECISION_REQUIREMENTS**: rename `child_pugh_score` numeric → `child_pugh_sum_points` para resolver conflicto select-vs-number entre `advanced_hepatic_fields()` (canónico A/B/C) y `pivotal_gate_supporting_fields()` (numeric 5-15) cuando schemas spread ambas (1 test). **§3 COMPLETENESS_VALIDATION**: warner dual API — legacy keys preservadas + LXCIX keys nuevas (`gate_coverage_percent`, `completeness_grade` A-F, `state` alias) (3 tests). **§4 INTAKE_WIZARD**: `g2852` con `?v=legacy` forward-compat post-LXCIII migration default (2 tests). **§5 ADVANCED_MODULES**: verified pass — Akeega + Pluvicto precision paths intactos (7 tests). **§6 COMPLIANCE_SCORING**: `pillar_3_lifecycle.py` restored from backup (164 lines, IEC_PATTERN regex correcto) + `pillar_5_clinical.py` clamp ratio `min(pct, 1.0)` + hard cap 85% sin `prospective_protocol_signed` (5 tests). **20 tests dedicados** H.G3236-H.G3255 PASS + 132 tests adyacentes preservados sin regresión.
**Iteración previa**: 2026-04-30 LXCVIII (cierre Iter LXCVIII A+B — **🧹 Cleanup Pre-Existing Failures Top 5 ROI + 🎨 Clinical Hub UI Redesign Bento Grid** — 35/35 dedicated tests PASS. LXCVIII.A cierre 33/55 pre-existing failures en 5 categorías. LXCVIII.B redesign /clinical-hub con bento grid + KPI hero + 8-vector loops rail.)
**Iteración previa**: 2026-04-28 LXCII (cierre Iter LXCII — **🩺 Classifier Regression Fix · Stage-Aware Initial Triage 18 Estadios NCCN**: usuario reportó que tras LXCI la nueva UI clasificaba incorrectamente — paciente con prostatectomía radical + recurrencia bioquímica se clasificaba como `localized_initial`. Schema expandido 15 → 32 fields con multi-level `conditional_visibility`. **20 tests dedicados** H.G3011-H.G3030 PASS.)
**Iteración previa**: 2026-04-28 LXCI (cierre Iter LXCI — **🎨 UI/UX Refinement + Bug Fix Crítico "Confirmar y abrir expediente"**: 5 problemas reportados por el usuario tras auditoría visual manual cerrados — bug P0 URL hang + modal firma 21 CFR Part 11 + endpoint `/api/consent/sign` + demo banner removed + sidebar action rail + logo 240px + sticky actionbar + transitions framework + hover prefetch. **20/20 tests dedicados PASS** H.G2991-H.G3010.)
**Iteración previa**: 2026-04-28 LXC.1.1 (patch — **🎯 PSA Persistence Bug Fix + Line Type Classification**: auditoría E2E reveló bug crítico — baseline_psa NO se persistía a biomarker_longitudinal (solo testosterone sí). Root cause: `_preferred_psa_longitudinal_value` no incluía `baseline_psa` ni `psa_baseline_ng_ml` (alias intake-wizard) como fallback. **Fix**: extendido fallback chain. **Adicional**: nueva función `_classify_line_type(drug_scheme)` clasifica tx en triplete (ARASENS/PEACE-1) / doblete (ENZAMET/CHAARTED) / adt_solo / post_mcrpc_taxano (CARD) / post_mcrpc_parp (PROfound) / radiopharm (VISION) con evidence_trial mapping. Treatment bands en torre incluyen `line_type` + `line_type_label` + `components_count` + iconos visuales (🔺 triplete · 🔻 doblete · ◾ ADT solo · 💊 taxano · 🧬 PARP · ☢ radiopharm). E2E verificado: paciente sintético triplete ARASENS + doblete ENZAMET ambos con PSA+Testo persistidos correctamente, treatment_band con line_type clasificado, torre vigilancia rendering completo. **10 tests dedicados** H.G2981-H.G2990 PASS.
**Iteración previa**: 2026-04-28 LXC.1 (patch — **🎯 PSA Unified + Torre Vigilancia integration: APE single source of truth + auto-seed baseline idempotente + chart psaMini consume bundle real (no datos hardcoded) + testosterona overlay y2 + dynamic treatment bands + castrate threshold + cross-field validation (cT0+M1 imposible, Gleason 2+2 rejected ISUP 2014). 17/20 brechas frontend→backend cerradas. 15 tests dedicados H.G2966-H.G2980 PASS**)
**Iteración previa**: 2026-04-28 LXC (cierre Iter LXC — **🩺 Clinical Capture Refinement Loop: nuevo Pilar 8 (Clinical Data Capture Coverage, peso 15) cierra el gap más crítico clínicamente — frontend→backend → gates clínicos disparando · 9 longitudinal kinds nuevos (ECOG/BPI/ESAS/PHQ-9/CTCAE/PSMA-PET/bone_scan/visceral_mets/HRR germinal+somatic) · 8 structured forms · 9 auto-derive helpers (ISUP/PSADT/Charlson/G8/Frailty/BCR/CrCl/Age/DFI) · endpoint /api/auto-derive/<nss> + UI panel · 14 conditional_visibility batch · validation rules expandidas · 30 tests H.G2936-H.G2965 · P8: 51.8%→79.2% (+27.4pp) · gates 71/73/74/61/75-77 ahora disparan correctamente**)
**Iteración previa**: 2026-04-27 LXXXIX (cierre Iter LXXXIX — **📈 FDA Compliance Refinement Loop: aggregate 72.07% → 84.67% (+12.6pp en 1 iteración) · 133 test files mapped IEC 62304 §X.Y · requirements.txt strict pinning · retro_validator real SQLite joins · auto_merge_engine bootstrap policy 3-phase (Shadow/Limited/Autónomo con thresholds 95%/98%/2% rollback) · 15 nuevos tests dedicados (H.G2921-H.G2935) · P3 lifecycle 20%→90% · top gap P5 prospective_protocol_missing (human-blocked) · target 96% cap retro reachable en ~30 más iteraciones cron diario**)
**Iteración previa**: 2026-04-27 LXXXVIII (cierre Iter LXXXVIII — **🏛 FDA SaMD Compliance Closure Loop bootstrap: 7 pilares scorers (P1-P7 weights summing 100) + gap_prioritizer + proposal_generator (24 routers + 9 skill clients) + retro_validator (89 gates AUC/PPV/NPV) + dashboard `/fda-samd-compliance` + 5 endpoints REST + 9 regulatory seeds (IMDRF + CDS + IEC 62304 + 4 SOPs + FMEA 15 hazards + STRIDE 6 cats + SBOM + DHF 113 rows + protocol prospective DRAFT + SECURITY.md) · 40 tests dedicados (H.G2881-H.G2920) · Aggregate compliance 13.3% → 72.07% (+58.8pp en 1 iteración) · ETA 96% cap retro: ~9 semanas cron diario · 100% (con prospectivo humano): ~14 meses calendario → 2027-Q3**)
**Próxima propuesta** (post-LXXXVIII): **Iteración LXXXIX — FDA Compliance Refinement Loop**: activar `AGENTIC_AUTO_MERGE=true` después de 30 iteraciones consecutivas exitosas. Refinement focus: (1) trial evidence backfill via `pubmed-database` skill (89 gates · ~30h delegated), (2) test phase mapping IEC 62304 batch via `code-reviewer` skill (~12h), (3) retro validator real joins (`clinical_assessments` + `decision_audit` + `outcome_events` + `survival_status_records` · ~7h), (4) dashboard streaming live snapshot (~4h), (5) skill clients reales conectados (docx/xlsx/pubmed dejan de ser DRY-RUN · ~10h). Estimación: 18-24h total · target compliance ~85%.

**Iteración futura propuesta** (post-LXXXIX): **Iteración LXXXX — Cortana de ProstaMed** (asistente de voz IA clínico): Whisper STT local + ElevenLabs/Edge TTS + Claude Sonnet intent extraction + 6 Q&A tools + SOAP generator. Hereda base sólida: 89 gates + 47 trials + Stage-Aware intake + What-if simulator + Agentic loop con compliance metrics + 7 pilares FDA SaMD trazables. Estimación: ~230h.

**Iteración futura propuesta** (post-LXXXVIII): **#3 — Cortana de ProstaMed** (asistente de voz IA clínico): Whisper STT local + ElevenLabs/Edge TTS + Claude Sonnet intent extraction + 6 Q&A tools + SOAP generator + WebSocket realtime + cifrado audio Fernet + retention 90d. **Cortana hereda base sólida**: CDE Auditable real + 19 keys compass + Stage-Aware intake + What-if simulator + Agentic loop con compliance metrics. Estimación: ~230h (6 semanas).
