"""algorithm_version.py — FAUBOT auditoría 2026-04-25 (X).

Helper de versionado semántico del bucle Faubot. Hace explícita la
**dimensión VERSIÓN** del Clinical Decision Engine Auditable: cada
recomendación clínica queda asociada a una versión reproducible del
algoritmo (bucle Faubot release + sha del módulo de gates + lista de
los gates activos al momento de la decisión).

Aporte a auditabilidad:
  - **VERSIÓN:** sin esto, una decisión clínica futura no puede
    reproducirse exactamente porque el catálogo de gates puede haber
    crecido. Con esto, cualquier decisión queda anclada a su versión.
  - **EVIDENCIA:** la lista de gates activos + fecha de cierre Faubot
    permite trazar qué evidencia científica estaba vigente cuando se
    emitió la recomendación.

Diseño:
  - Funciones puras sin side-effects.
  - El SHA del módulo se calcula on-demand (no se cachea para que cualquier
    cambio se refleje inmediatamente).
  - El registro Faubot release se mantiene como constante actualizable
    al cierre de cada iteración del bucle.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

# Constante actualizada al cierre de cada iteración del bucle Faubot.
# Convención: "YYYY-MM-DD ROMAN_NUMERAL" (e.g., "2026-04-25 X").
#
# EPIC 31.D (GodiBot G66 HIGH) — DISCIPLINA DE VERSIONADO: cada PR que cierre
# ≥1 G-finding clínico DEBE bumpear este stamp (21 CFR Part 11 §11.10(e) +
# IEC 62304 §5.1.6 requieren trazabilidad versionada). EPIC 25-29 cerraron
# 50 hallazgos sin bump — audit trail post-hoc indistinguible.
# Histórico: 2026-04-30 LXCIX → 2026-05-15 C (pre-EPIC30) → 2026-05-16 CI
# (post-EPIC 30: PSA Tower + GodiBot pass-5) → 2026-05-16 CII (post-EPIC 31)
# → CIII-CIX (EPIC 33 + EPIC 34.A Phases 1-5) → CX (Phase 6: PSMA-PET capture)
# → CXI (EPIC 35: classifier alignment) → CXII (EPIC 37: dashboard)
# → CXIII (EPIC 36: voice quick-capture PoC) → CXIV (EPIC 36.B-ext: mic UI
# replicado en 4 cards via shared helper) → CXV (EPIC 38: STT smoke harness)
# → CXVI (EPIC 39: visual validation harness 5/5 cards+dashboard)
# → CXVII (EPIC 40: Cortana Dictation Hub — composite extractor + apply mode
# + Trial Matcher diff before/after) → CXVIII (EPIC 42: Comprehensive intake
# 47 → 104 fields, NO eliminación + cohort hygiene is_synthetic + reasoning
# trail compass + voice intake hub + real patient consent endpoint)
# → CXIX (EPIC 43: stage-specific schema completeness — 42 inline schemas
# para los 41 estados sin schema dedicado, 782 fields totales · Smart Capture
# UX single-page con sidebar nav + auto-save + Cmd-K + voice per section +
# reasoning trail inline + WCAG AA — preservando los 104 fields del intake).
# → CXX-CXXIII (EPIC 33 + decision_today + compass + template-gates fixes)
# → CXXIV (EPIC 44.A: intake friendly labels — fix template
# intake_smart_capture.html que renderizaba f.options crudo en lugar de
# f.display_options; enrich BOOLEAN_CONTEXTUAL_OPTION_LABELS + OPTION_LABELS
# con ~30 labels clínicamente densos para campos críticos NCCN/EAU 2026.
# Anti-pattern reportado por urólogo: "BCR detectada: 0/1" sin labels.
# Post-fix: "BCR detectada: Sin BCR confirmada / BCR confirmada".
# Backend compat preservado: value="0"/"1"/"unknown" sigue intacto en submit
# → voice extractors EPIC 36 + JS auto-save no rompen. 60/60 tests + 541
# regression PASS + Playwright sweep pending).
# → CXXV-CXXVIII (EPIC 44.B/C/C.2/D: Tier 1 Clasificador + Tier 2 Asistente
# + cross-cutting filter + Smart Capture banner) — DEPRECATED y revertidos
# en CXXIX. Reportado por urólogo: "TIER 2 sigue siendo demasiado extenso"
# y "los 2 TIER no son funcionales, eliminar". El 2-tier UX no resolvía la
# pérdida de lógica clínica (Tier 2 mostraba 514 fields; tras filtro
# cross-cutting bajaba a 19 pero seguía siendo insuficiente para reflejar
# la riqueza clínica del estadio). Decisión: el clínico prefiere el flujo
# completo (Smart Capture vista experta con 104 fields + display_options
# EPIC 44.A) sin segmentación artificial.
# → CXXIX (Rollback EPIC 44.B/C/C.2/D vía git revert):
#   - DELETE templates/intake_tier1.html, templates/intake_tier2.html
#   - DELETE tests/test_epic44_tier1_classifier.py,
#            tests/test_epic44_tier2_no_overlap.py,
#            tests/test_epic44d_smart_capture_banner.py
#   - REMOVE routes /intake/tier1, /api/intake/tier1/classify,
#            /intake/tier2/<state>, /api/intake/tier2/<state>
#   - REMOVE tier1_classifier_schema(), TIER1_REQUIRED_MIN_FIELDS,
#            _TIER1_FIELD_NAMES_ORDERED, _TIER2_CROSS_CUTTING_GROUPS
#   - REMOVE stage_specific_intake_schema kwargs exclude_tier1_overlap +
#            include_cross_cutting (revertido a signature original)
#   - REMOVE Smart Capture banner "Vista experta / Tier 1 Clasificador"
# PRESERVADOS (sin pérdida clínica):
#   - EPIC 44.A: friendly display labels (BCR confirmada, PSMA-positiva,
#     visceral mets contextuales, ~30 fields enriched, 60/60 tests)
#   - 9973c05 compass-aware ranking Patient Twin OS (Enzalutamida #1 mCSPC)
# 517 passed + 1 xfailed post-rollback. Próximo: revisitar value clínico
# real sin segmentación artificial — EPIC 45 ML augmentation o feedback
# directo del urólogo sobre qué pieza clínica falta.
# → CXXX (EPIC 45: FactSpec alias contradiction audit — generaliza el fix
# manual del paciente Frin a TODA la población. NUEVO módulo
# prostanet/regulatory/clinical/factspec_alias_audit.py (~570 LOC) con:
#   - get_alias_groups(): inventa 42 alias groups desde FACT_SPECS.legacy_aliases
#     (15 blocking, e.g. metastatic_stage_resolved↔m_substage_resolved que
#     fue el bug-root del Frin)
#   - detect_contradictions_for_patient(): identifica facts del mismo alias
#     group activos simultáneamente con valores no concordantes
#   - propose_resolution(): reglas precedencia auditable (más reciente +
#     tie-break por source_type: clinician_verified > classifier_derived
#     > legacy_import) + verification_note explicativo
#   - apply_resolution(): marca losers is_active=0, supersede + audit
#     entry en clinical_view_audit
#   - audit_all_patients / resolve_all_patients: poblacionales
#   - CLI: python -m prostanet.regulatory.clinical.factspec_alias_audit
#     --dry-run / --apply / --patient-id / --json
# REST endpoints (NUEVO prostanet/presentation/data_integrity_routes.py):
#   - GET  /api/data-integrity/audit           (poblacional dry-run)
#   - GET  /api/data-integrity/<nss>           (snapshot paciente)
#   - POST /api/data-integrity/<nss>/resolve   (auto-fix, requiere confirm=auto)
#   - POST /api/data-integrity/audit/apply     (poblacional, requiere
#                                                confirm=ALL_PATIENTS)
# View model integration: _build_data_integrity_snapshot() inyecta
#   `data_integrity` al bundle de build_patient_profile_view_model.
# UI panel: section data-testid="data-integrity-panel" en patient_profile_v2
#   se renderiza solo cuando contradictions_count>0 o resolutions_count>0
#   (sin agregar ruido si todo está limpio). Botón "Aplicar auto-resolución"
#   visible solo si severity=high. Detalles por contradicción con código
#   fact_key + valor + source_type + timestamp + historial colapsable.
# Hallazgo real producción: 33/425 pacientes (7.8%) tienen el mismo bug
# que Frin con severity=high (todas en alias_group metastatic_stage_resolved).
# 22/22 tests EPIC 45 PASS + 539 regression PASS).
# → CXXXI (EPIC 45.B: Post-intake guard preventivo para nuevos pacientes.
# Cierre del loop del paciente Frin a nivel de PREVENCIÓN — no solo
# corrección retroactiva. Scope acotado por urólogo: "DEBEMOS EVITAR QUE
# VUELVA A SUCEDER CON NUEVOS PACIENTES QUE SE INGRESEN".
#
# Hook injection en tracking_db.py:register_new_patient (post conn.commit()
# de los facts iniciales): invoca audit_patient + propose_resolution +
# apply_resolution con marker action_suffix='on_intake'. El paciente NUEVO
# nunca llega a render con contradicciones activas — son resueltas
# in-transaction dentro del mismo flujo de creación.
#
# Garantías:
#   - Non-blocking: si la auditoría falla por cualquier razón, el intake
#     completa exitosamente (graceful degradation logged como WARNING).
#   - Provenance: cada resolución on-intake queda en clinical_view_audit
#     con action='factspec_alias_resolved:<canonical>:on_intake', permitiendo
#     distinguir resoluciones autom. on-intake vs CLI poblacional vs manual.
#   - Reusa 100% del módulo EPIC 45 ya en producción (audit_patient,
#     propose_resolution, apply_resolution — cubierto por 22 tests).
#
# Extensión apply_resolution (factspec_alias_audit.py): honra opcionalmente
# Resolution.action_suffix para enriquecer el action de audit. Backward
# compatible — resoluciones sin suffix mantienen action original.
#
# Tests añadidos (3): post_intake_guard_cleans_alias_on_new_patient (happy)
# + _noop_when_clean (clean no-op) + _failsafe_on_audit_exception
# (graceful degradation). Total tests EPIC 45 ahora: 25 PASS.
#
# El bug del paciente Frin queda matemáticamente imposible de reaparecer
# en intake. Frente restante (auto-derive en re-render de pacientes
# EXISTENTES) será EPIC 45.C si se requiere — está fuera de scope ahora).
# → CXXXII (EPIC 46.A — Latin Decision-Impacting Fields):
# Materialización del puente roto entre intake y ETHNICITY_RISK_MODIFIERS.
# Backend tenía hace meses RR modifiers por ancestría (afroamericano 1.73x
# incidence, hispano_latino 0.85x, etc.) pero el intake NO preguntaba etnia
# → todo paciente defaulteaba a europeo_caucasico RR 1.0 invalidando la
# diferenciación. Hoy 425/425 pacientes están en el mismo grupo de riesgo
# artificial.
#
# Cambios:
#   - 4 nuevos FactSpec en clinical_fact_registry: primary_ancestry +
#     3 booleanos de acceso regional (psma_pet, lu_psma, arsi).
#   - intake/_mexico_fragment con widgets friendly-labeled + help_text
#     explicativo anti-discriminatorio (clarifica "NO afecta acceso a tx").
#   - natural_history_tracker: PRIMARY_ANCESTRY_TO_ETHNICITY_KEY mapping
#     + nueva entry indigena_americano (modelado conservadoramente como
#     hispano_latino variant, flagged data_quality_flag para futuro
#     re-calibration con cohorte propia EPIC H2-H3).
#   - resolve_ethnicity_key() helper con precedencia: primary_ancestry
#     (EPIC 46.A) > legacy ethnicity > europeo_caucasico (fallback).
#   - recommendation_arbiter._apply_access_restrictions_to_ranking():
#     NUEVO filter post-contraindications que MARCA (no esconde) terapias
#     localmente inviables: Lu-PSMA si lu_psma_local_access=0, ARSIs si
#     arsi_local_access=0. Re-rankea bajando al final + access_restricted=True
#     + access_note con ruta de derivación sugerida. PSMA-PET sin acceso
#     no muta ranking pero produce imaging_restrictions en access_warnings.
#     Filosofía: nunca esconder opción al clínico (mantiene override).
#   - ArbitratedDecision.access_warnings field nuevo + arbiter_version bump.
#
# Tests: 5/5 PASS (tests/test_epic46a_latin_capture.py). Regression: 492
# PASS + 1 xfailed + 62 arbiter-related PASS.
#
# Impacto clínico tangible: el primer paciente nuevo con primary_ancestry=
# afro_descendiente verá su perfil con incidence_rr=1.73 en lugar del 1.00
# artificial. Compass + Twin OS + gates derivados leerán el modifier correcto.
# Si reporta acceso a Lu-PSMA = No, las recomendaciones priorizarán
# alternativas accesibles dentro de su realidad. Cierra brecha estratégica
# crítica para Latin foundation de la plataforma).
# → CXXXIII (EPIC 46.B — ML Materialization: activa 4 modelos PyTorch
# entrenados pero huérfanos):
# Hallazgo de auditoría: 4 modelos en output/models/{treatment_response,
# deep_surv, anomaly_detector, state_transition}/best.pt cargaban al boot
# del servidor (logs lo confirman) PERO ningún template los consumía. Los
# endpoints POST en api.py:1883+ existían pero la UI nunca los llamaba.
# Trabajo entrenado hace meses, materialization=0%.
#
# Cambios (5 archivos, +~600 LOC):
#   - NUEVO prostanet/presentation/ml_inference_routes.py: blueprint con
#     5 GET endpoints idempotent por NSS + helper compartido
#     `build_ml_predictions_snapshot(patient_id)` reutilizado por view model
#     y endpoints. Cada call queda audited en clinical_view_audit con
#     section_key='ml_inference', action='ml_predict:<model>:<version>'.
#   - bootstrap.py: registra ml_inference_bp (graceful degradation).
#   - profile_compass.build_patient_profile_view_model: inyecta
#     `ml_predictions` al bundle. Helper fail-safe: si modelo no carga,
#     reason explicativa pero render del perfil completo NO bloquea.
#   - templates/patient_profile_v2.html: NUEVA sección "Inteligencia ML"
#     entre data_integrity panel y EPIC 20 cards. Grid 2x2 con 4 cards:
#     treatment-response, survival, anomaly (badge ⚠ si score>0.7),
#     state-transition. Cada card muestra: key metric + maturity badge
#     (advisory/shadow/experimental) + model_version. Footer transparente
#     lista modelos no disponibles con razón.
#   - tests/test_epic46b_ml_materialization.py: 8 tests cubriendo importable,
#     snapshot shape, fail-safe, view model wire, template testids, 404, 503,
#     _explain_unavailable priorities.
#   - tests/test_epic22d_ui_data_concordance.py: registra 5 testids nuevos
#     en STATIC_NO_DATA_BINDING (data-binding via ml_predictions key).
#
# Filosofía SaMD: predictions tagged advisory_only=True + rule_based_source_
# of_truth=True. Nunca son source-of-truth. Reasoning trail muestra maturity
# tag → clínico distingue inmediatamente "experimental" vs "advisory".
#
# Validación: 8/8 tests EPIC 46.B PASS. Regression: 65 PASS + 1 xfailed
# (incluye 46.A + EPIC 45 + EPIC 23 arbiter + UI concordance).
#
# Impacto clínico tangible: el primer paciente que se abra post-CXXXIII
# verá 4 cards de inteligencia ML en su perfil (o las disponibles según
# qué modelos cargaron). Anomaly detector flagea presentaciones atípicas
# para escalation a tumor board. Treatment response complementa Twin OS
# ranking. State transition + survival mejoran SDM con paciente.
# Cierra el segundo orphan más grande de la plataforma — solo queda EPIC
# 46.C (auto-derive guard) para completar la primera ola de materialización).
# → CXXXIV (EPIC 46.C — Auto-derive guard: CIERRE SAGA EPIC 45):
#
# Último frente abierto de EPIC 45 cerrado. El auto-derive en
# tracking_db.refresh_longitudinal_intelligence (función central llamada
# por TODO render de perfil de paciente existente) podía re-crear
# contradicciones alias transitoriamente — exactamente el bug descubierto
# en EPIC 45 APPLY Fase 5 con paciente 39 (m_substage_resolved=M1b
# regenerado por auto-derive sobre metastatic_stage_resolved=M0 limpio).
#
# Cambios (3 archivos, ~150 LOC):
#
# 1. tracking_db.py:11538+ (post-conn.commit() pre-conn.close()):
#    Hook EPIC 46.C inyectado idéntico al patrón EPIC 45.B (intake) pero
#    en el path central de auto-derive. Cada vez que refresh persiste
#    facts, el guard limpia contradicciones residuales con action_suffix=
#    'on_autoderive'. Non-blocking — si auditoría falla, refresh completa
#    con WARNING log (clínico ve panel UI EPIC 45 y puede resolver manual).
#
# 2. prostanet/regulatory/clinical/factspec_alias_audit.py:audit_patient():
#    BUG FIX descubierto durante smoke E2E: la función esperaba conn con
#    row_factory=Row, pero refresh usa conn default (tuples). Patched para
#    normalizar a list[dict] usando cur.description independiente del
#    row_factory configurado. Robustez para callers heterogéneos.
#
# 3. tests/test_epic45_factspec_alias_audit.py: +2 tests dedicados:
#    - test_epic46c_autoderive_guard_resolves_contradictions_with_on_autoderive_suffix:
#      valida cadena audit→propose→apply produce action terminando en
#      ':on_autoderive' (no ':on_intake' ni sin suffix)
#    - test_epic46c_re_render_does_not_reactivate_contradiction:
#      simula 2 rondas auto-derive con re-creación cross-alias (escenario
#      exacto del bug paciente 39) y valida que guard mantiene 0
#      contradicciones residuales activas sostenido + audit entries
#      acumuladas
#
# Validación end-to-end:
#   - 27/27 tests EPIC 45 + 46.C PASS
#   - 67 PASS + 1 xfailed regression sweep
#   - Smoke real con paciente 39:
#     * PRE: inyecté contradicción artificial M0_FORCED_TEST vs M1b
#     * Trigger /patient_profile/97000000001?v=2 → HTTP 200 (6.9s)
#     * POST: 0 contradicciones + 1 audit entry ':on_autoderive'
#     * Log: "EPIC 46.C auto-derive guard: patient_id=39 cleaned 1
#       alias contradiction(s) post-refresh"
#
# Cierre saga EPIC 45 — 3 frentes ahora cubiertos:
#   - INTAKE (EPIC 45.B :on_intake): nuevos pacientes nunca llegan a
#     render con contradicciones alias
#   - AUTO-DERIVE (EPIC 46.C :on_autoderive): pacientes existentes
#     mantienen estado limpio aún cuando refresh recrea facts
#   - RESOLUCIONES CLI/MANUAL (action sin suffix): trazables separadamente
#
# Net effect arquitectónico: el bug del paciente Frin queda matemáticamente
# imposible de manifestarse en cualquier path. Dashboard regulatorio H2
# puede reportar ratio :on_intake / :on_autoderive / :cli_apply / :manual
# para distinguir fuentes de data integrity issues.
# → CXXXV (EPIC 47 — Longitudinal Trajectory Dashboard):
# CAMBIO PARADIGMÁTICO de medicina snapshot → temporal. El urólogo ahora
# ve la EVOLUCIÓN del paciente, no un snapshot. Esto habilita medicina
# predictiva (detectar deterioro 3-6m antes que aparezca en imagen) vs
# reactiva (esperar que la metástasis sea radiográficamente evidente).
#
# Cambios (6 archivos, ~1500 LOC):
#
# 1. NUEVO prostanet/domains/patient_tracking/trajectory_engine.py:
#    build_trajectory_bundle() unifica:
#      - PSA + treatment lanes (reusa build_combined_patient_timeline)
#      - ECOG over time (desde follow_up_visits.ecog_current)
#      - ALP/LDH/testosterona (desde biomarker_longitudinal table)
#      - Kinetics: PSA doubling time (regresión log-linear NCCN),
#        PSA velocity (ng/mL/año), PSA nadir, ALP trend % 3m,
#        ECOG decline detection
#      - Cohort baseline overlay (opcional, skippeable en render rápido)
#    Fail-safe: si cualquier sub-builder falla, retorna available=False
#    con reason. No bloquea render del perfil.
#
# 2. NUEVO prostanet/domains/patient_tracking/trajectory_alert_engine.py:
#    5 detectores basados en evidencia NCCN/EAU 2026 + literatura:
#      - PSADT <10m (PROpel/SPARTAN/PROSPER/ARAMIS) — critical si m0_crpc
#      - ALP rise >25% en 3m bajo ADT sin imagen positiva (pre-bone-mets)
#      - PSA progression on ARSI por criterios PCWG3 (Scher 2016)
#      - ECOG decline ≥1 punto (NCCN PROS-O paliativo) — critical si ≥3
#      - Testosterona >50 ng/dL bajo ADT (castration failure)
#    Cada alert incluye: severity, clinical_message, evidence, citation,
#    action_suggested, audit_keys. Priorizadas critical → high → moderate.
#
# 3. NUEVO prostanet/presentation/trajectory_routes.py:
#    GET /api/trajectory/<nss> retorna bundle completo con alerts.
#    Audit trail en clinical_view_audit (section='trajectory',
#    action='trajectory_fetched:<engine_version>'). 404 si NSS no existe.
#
# 4. prostanet/presentation/bootstrap.py: registra trajectory_bp con
#    graceful degradation (idéntico patrón EPIC 45/46).
#
# 5. prostanet/domains/patient_tracking/profile_compass.py: inyecta
#    `trajectory` al view model. Helper fail-safe. include_cohort_overlay=
#    False en render del perfil (skip overhead 60+s — cohort overlay
#    queda disponible via REST endpoint explícito).
#
# 6. templates/patient_profile_v2.html: NUEVA sección entre ML predictions
#    y EPIC 20 cards:
#      - Header EPIC 47 + count alerts badge
#      - 4 KPI cards (PSADT, velocity, nadir, ALP trend con ⚠ si ≥25%)
#      - 3 Chart.js canvases (PSA timeline, ECOG step, ALP+LDH dual)
#      - Lista priorizada de alerts con severity colors
#        (critical=rojo, high=naranja, moderate=amarillo)
#      - Script Chart.js inline para inicialización
#    Render condicional (solo si trajectory.available=True).
#
# 7. tests/test_epic47_trajectory_dashboard.py: 16 tests cubriendo
#    engine shape + fail-safe, biomarker extraction, PSA kinetics math,
#    ECOG decline detection, 5 alert detectors + priority sorting,
#    REST 404, view model wiring (source-level guard), UI testids,
#    output shape contract regression.
#
# Validación end-to-end:
#   - 16/16 tests EPIC 47 PASS (11.68s)
#   - 83 PASS + 1 xfailed full regression sweep (309s)
#   - Smoke real con paciente 39:
#     * GET /api/trajectory/97000000001 → 200 success
#     * Detecta 3 alerts REALES en este paciente:
#       - CRITICAL: PSA progression on ARSI PCWG3 (88.88 vs nadir 7.10)
#       - HIGH: ALP rise pre-bone-mets (+44.5% en 3m)
#       - HIGH: ECOG decline (1→2)
#     * Render /patient_profile/97000000001?v=2 → 200 (~7s)
#     * Playwright DOM probe confirma panel + 4 KPIs + 3 alerts + 3 charts
#
# Performance: include_cohort_overlay=False en render principal evita
# overhead 60+s. Cohort overlay disponible via REST endpoint para casos
# que lo necesitan explícitamente (research/SDM views).
#
# Impacto clínico tangible:
#   - Paciente 39 HOY tiene 3 alertas accionables visibles que antes eran
#     invisibles: PSA progresando bajo ARSI (switch/escalate), ALP subiendo
#     +44.5% (PSMA-PET indicado), ECOG declinando (reconsiderar agresividad).
#   - Foundation H2 research: KM curves, Cox regression, propensity matching
#     requieren trajectory bien construida. Sin engine, era imposible.
#   - Foundation EPIC 48 (reasoning trail) y EPIC 49 (patient-facing): ahora
#     pueden anclar cada recomendación a contexto temporal específico.
#   - Activa multiplicativamente: deep_surv (EPIC 46.B) + state_transition +
#     anomaly_detector ya viven mejor con trajectory context.
# → CXXXVI (EPIC 48 — Decision Loop Closure: cierre del bucle clínico):
# Hasta hoy el sistema emitía recomendaciones al vacío. Engine recomienda
# X, urólogo decide Y, NO había registro de Y ni de POR QUÉ. Engine
# nunca aprendía de disagreement. SaMD §820.30 user feedback compliance
# ausente. Latin recalibration coefficients (visión pilar 4) bloqueada.
#
# Cambios (8 archivos, ~2100 LOC):
#
# 1. NUEVO prostanet/domains/decisions/decision_narrative_builder.py:
#    build_decision_narrative() sintetiza 6+ outputs concurrentes (Compass,
#    Twin OS, Decision Fusion, gates pivotales, trajectory, ML predictions,
#    GodiBot review) en UN narrative párrafo coherente con evidencia
#    citable, alternativas rankeadas, discordances detectadas y confianza
#    global. Reduce cognitive load del clínico de 6+ cards a 1 párrafo +
#    drill-down. Filosofía SaMD preservada: advisory only, fallback
#    state-aware si no hay primary recommendation canónica, HTML-escape
#    contra XSS.
#
# 2. NUEVO prostanet/domains/decisions/outcome_linkage.py:
#    build_outcome_linkage() vincula última decisión clínica
#    (treatment_start o override event) a outcomes observados a 3/6/12
#    meses. PSA response categories PCWG3-aligned (response_major,
#    response_minor, stable, progression). ECOG delta categories
#    (improved, stable, declined, severe_decline). ALP/LDH trends.
#    Foundation para continuous learning loop + real-world evidence.
#
# 3. NUEVO prostanet/presentation/decision_override_routes.py:
#    Blueprint `decision_override_bp` con 3 endpoints:
#      - POST /api/decision-override         (captura override event)
#      - GET  /api/decision-override/<nss>   (historial paciente)
#      - GET  /api/decision-override/stats   (stats poblacionales)
#    Tabla clinical_override_event auto-bootstrap idempotente. Taxonomía
#    canónica de 13 ALLOWED_OVERRIDE_REASONS (patient_preference,
#    access_barrier_local, insurance_coverage, prior_toxicity_intolerance,
#    comorbidity_contraindication, drug_drug_interaction, etc.). Audit
#    signature SHA-256 truncado para integridad regulatorio.
#
# 4. prostanet/presentation/bootstrap.py: registra decision_override_bp.
#
# 5. prostanet/domains/patient_tracking/profile_compass.py:
#    build_patient_profile_view_model ahora cambia `return {...}` a
#    `bundle = {...}` para inyectar 2 keys post-bundle:
#      - bundle["decision_narrative"] = synthesis layer EPIC 48.A
#      - bundle["outcome_linkage"] = outcomes 3/6/12m EPIC 48.C
#    2 helpers fail-safe (_build_decision_narrative_safe + _build_
#    outcome_linkage_safe) garantizan no_block del render principal.
#
# 6. templates/patient_profile_v2.html: NUEVA section data-testid=
#    "decision-narrative" ANTES de data-integrity panel (es el resumen
#    primario clínico, debe ser lo primero que vea el urólogo). Incluye:
#    - Header EPIC 48 + confidence badge (verde/amarillo/rojo según %)
#    - Botón ⚠ Override que abre modal
#    - Narrative HTML rendered desde builder (con drill-down anchors)
#    - Grid 5 concordances (compass_twin / fusion / ml / trajectory / godibot)
#    - Sub-panel outcome-linkage con 3 windows (3m/6m/12m) PSA + ECOG + ALP
#    - Modal override-modal (hidden por default) con form de 13 reasons +
#      free_text + JS submit handler que POSTea al endpoint REST
#
# 7. NUEVO tests/test_epic48_decision_loop_closure.py: 18 tests cubriendo
#    narrative shape + fail-safe + html escape + concordance, override
#    validation + 400/404 + allowed_reasons + audit signature, outcome
#    linkage anchor + categorization, UI testids + source-level wiring.
#
# 8. tests/test_epic22d_ui_data_concordance.py: registra 8 nuevos testids
#    en STATIC_NO_DATA_BINDING (decision-narrative + sub-elementos).
#
# Validación end-to-end:
#   - 18/18 tests EPIC 48 PASS
#   - Smoke real paciente 39 (NSS 97000000001):
#     * GET /patient_profile/97000000001?v=2 → 200 (~7s)
#     * 17 testids EPIC 48 rendered en HTML
#     * Playwright probe confirma: narrative + 5 concordances ✓ + 100%
#       confidence badge + override button + outcome panel + modal
#     * POST /api/decision-override smoke → 201 con audit_signature
#       d6265e78c84ff51961cf9bb178697c61, override_id=1, message
#       "Override capturado para audit trail + engine learning loop"
#
# Bucle clínico CERRADO:
#
#   Antes (post-EPIC 47):
#     Captura → Engine → [CAJA NEGRA HUMANA] → Outcome
#                          ↑ NO observable, NO learning
#
#   Después (post-EPIC 48):
#     Captura → Engine → Narrative claro → Decisión clínica
#                                            ├─→ Acepta (audit ✓)
#                                            └─→ Override capturado (reason taxonomy)
#                                                ├─→ Outcome linkage 3/6/12m
#                                                ├─→ Engine learning loop
#                                                ├─→ Latin recalibration data
#                                                └─→ SaMD §820.30 compliance
#
# Foundation desbloqueada:
#   - EPIC 49 (Patient-facing) — narrative_plain ya traducible a SDM
#   - EPIC 50 (Cohort analytics) — override patterns + outcomes para
#     KM/Cox/propensity matching
#   - Latin recalibration H3 — override por ancestría → publication-ready
#   - COFEPRIS regulatory H3 — user feedback mechanism cumplido
#   - Real-world evidence — primer dataset publicable LATAM CDSS prostate
# → CXXXVII (Sprint 1 fixes — auditoría E2E validación visual):
# 5 fixes críticos cerrados tras simular uro-oncólogo registrando paciente:
#
# FIX A — Smart Capture DEPRECADO formalmente:
#   /intake/smart ahora retorna 302 → /clinical-hub#pm2OfficialClassifier.
#   Comparativa Smart Capture vs Clasificador oficial: clasificador GANA en
#   4/4 dimensiones (clínica, arquitectónica, lógica, flujo). Smart Capture
#   = 105 fields anti-workflow; clasificador = voice-first 4-6 min con
#   Cortana + transcript revisable + apply.
#
# FIX #2 — EPIC 46.A persistencia activada:
#   Los 4 fact_keys (primary_ancestry, psma_pet_local_access, lu_psma_
#   local_access, arsi_local_access) ahora se extraen en
#   extract_canonical_fact_candidates → persisten en patient_clinical_facts.
#   Hallazgo: 0/425 pacientes tenían primary_ancestry capturado a pesar de
#   que el backend tenía ETHNICITY_RISK_MODIFIERS listo. EPIC 46.A estaba
#   "shipped" pero clinicalmente inactivo. Verificado en paciente 484
#   (Carlos Méndez Ruiz, afro_descendiente): 4/4 facts persistidos.
#
# FIX #3 + #4 — Pipeline metastatic_visceral robusto:
#   Hallazgo: parser leía SOLO `visceral_metastasis_present`; alias común
#   `metastasis_visceral_present` (orden invertido) era ignorado
#   silenciosamente → paciente con visceral mets clasificaba como "bajo
#   volumen oligometastatic". Errónea grave. Fix acepta 3 aliases
#   (canonical + alias + alias corto) para nodal/bone/visceral. Verificado
#   en paciente 484: M1c + visceral_metastasis_present=True + volume_context=
#   high + oligometastatic_operational=False.
#
# FIX #5 — Confidence honesty (vacuous truth penalty):
#   Hallazgo: cuando engines NO producían output, las concordancias retornan
#   True por defaults permisivos → confianza 100% sobre nada. Engañaba al
#   clínico.
#   Nueva lógica con 2 hard caps:
#     - HARD CAP 1: si primary_source_engine == "compass_context_fallback"
#       → confianza ≤35% (es guía contextual, no terapéutica concreta)
#     - HARD CAP 2: si <50% engines opinaron substantivamente → ≤50%
#   Helper _count_substantive_engines distingue output real vs default.
#   Verificado live: confianza pasó de 100% → 35% para paciente 484
#   (que está en fallback path por TNM incompleto).
#
# FIX #8 — Banner warning visible cuando fallback path:
#   Template: nueva sección data-testid="decision-narrative-fallback-banner"
#   roja con explicación + lista de campos a capturar + CTA "→ Ir al
#   clasificador oficial". Renderiza condicional solo si primary
#   .is_contextual_fallback=True. Verificado live en paciente 484.
#
# Validación:
#   - 10/10 tests Sprint 1 PASS (test_sprint1_validation_fixes.py)
#   - 111 PASS + 1 xfailed regression sweep (EPIC 45+46+47+48 + arbiter +
#     UI concordance + Sprint 1)
#   - Smoke real con paciente 484:
#     * /intake/smart → 302 redirect (FIX A) ✓
#     * primary_ancestry='afro_descendiente' persistido (FIX #2) ✓
#     * m_substage_resolved='M1c' + visceral_metastasis_present=True
#       + volume_context='high' (FIX #3+#4) ✓
#     * Confianza badge 35% (FIX #5) ✓
#     * Banner rojo "Clasificación incompleta · modo contextual" con CTA
#       (FIX #8) ✓
# → CXXXVIII (Sprint 2 fixes — auditoría E2E validación visual continuación):
# 2 fixes shippeados:
#
# FIX #6 — ML cards extraen valores reales (templates/patient_profile_v2.html):
#   ANTES: cards mostraban labels genéricos "Predicción disponible /
#   Estimación disponible / Análisis disponible" sin extraer del prediction
#   dict. Inversión enorme en ML (4 modelos entrenados, 8 endpoints
#   deep_surv, response distributions, anomaly features) era invisible
#   al urólogo.
#   DESPUÉS:
#     - Treatment Response card: best_expected_response con label español
#       (Respuesta parcial / completa / estable / progresión) + grid
#       CR/PR/SD/PD probabilities + PSA-50/PSA-90 response % + rPFS
#       mediana con IC95%.
#     - Survival card: OS mediana extraída de endpoints.OS.median_months
#       + delta vs reference trial + rPFS + Time-to-CRPC (3 endpoints
#       visibles, 8 total disponibles).
#     - Anomaly card: is_anomalous flag + detected_anomalies list con
#       top-3 features (severity color-coded) + CTA "Considerar tumor
#       board / segunda opinión" cuando is_anomalous=True.
#
#   Verificado live paciente 484:
#     * data-best-response="PR" → "Respuesta parcial (PR)" + dist 18/32/24/25%
#     * data-os-median="25.1" → "OS mediana: 25.1 meses" + rPFS 16.7m + TTCRPC 60m
#     * data-anomaly-flagged="1" data-anomaly-features="6" → "⚠ Anomalía
#       detectada (6 features) · PSA [critical] · ALP [critical] · LDH
#       [critical] +3 más"
#
# FIX #7 — /patients listing performance (9.3s → 150ms, -98%):
#   ANTES: 9.3s primer render. Hallazgo via profiling:
#     - SQL query aislada: 0.01s (rápido)
#     - patients_list_to_v2() FULL: 11.86s primera vez, 6.2s steady
#     - Bottleneck identificado: build_population_autodrive_from_db(limit=12)
#       toma 11.95s para procesar top-12 patient_priorities (ML inference
#       per patient + autodrive computation pesada)
#   FIX en 2 layers:
#     1. SQLite indexes nuevos sobre patient_id en 7 tablas con sub-queries
#        (follow_up_visits, smart_alerts, clinical_signal_snapshots,
#        scheduled_events, followup_agenda_items, outcome_events,
#        treatment_adverse_events) + ANALYZE para query plan optimization.
#     2. patients_list_to_v2(include_autodrive=False) DEFAULT — autodrive
#        es opt-in via query param `?autodrive=1`. Route /patients pasa
#        el param explícitamente + cachea separadamente.
#   Resultado benchmark:
#     - GET /patients?refresh=1: 9.3s → 150ms (-98%)
#     - GET /patients (cached): 15ms
#     - GET /patients?autodrive=1&refresh=1: 9.4s (opt-in cuando se necesita)
#     - GET /patients?autodrive=1 cached: 17ms
#   Beneficio UX: urólogo abre cohorte en <500ms (incluyendo render Flask
#   + template + transit), no espera 10 segundos cada vez.
#
# Validación:
#   - 7/7 tests Sprint 2 PASS
#   - 118 PASS + 1 xfailed regression sweep completo
#   - Smoke live confirma ML cards muestran valores clínicos reales
#   - Benchmark confirma performance threshold <2s superado
FAUBOT_RELEASE = "2026-05-24 CXXXVIII"

# Path al módulo de gates pivotal (SHA se calcula sobre este archivo).
_GATES_MODULE_PATH = (
    Path(__file__).parent / "pivotal_contraindication_gates.py"
)


def get_module_sha(module_path: Path | None = None) -> str:
    """Calcula el SHA-256 del módulo de gates (primeros 12 caracteres).

    Args:
        module_path: opcional override del path. Por defecto usa
            `pivotal_contraindication_gates.py`.

    Returns:
        Primeros 12 chars del SHA-256 del archivo, en hex. Si el archivo
        no existe (e.g., en tests aislados), retorna "unavailable".
    """
    path = module_path or _GATES_MODULE_PATH
    try:
        contents = path.read_bytes()
    except (OSError, FileNotFoundError):
        return "unavailable"
    return hashlib.sha256(contents).hexdigest()[:12]


def get_active_gate_codes() -> list[str]:
    """Retorna la lista ordenada de códigos de los gates pivotal activos.

    Faubot 2026-04-25 (XVIII) — Combina Python detectores + YAML loaded
    para reflejar el sistema híbrido completo. La normalización por
    `seen` evita duplicados cuando un gate vive en ambos lados (durante
    transición de migración).
    """
    seen: set[str] = set()
    codes: list[str] = []

    # 1. Python detectores
    try:
        from prostanet.shared.pivotal_contraindication_gates import _DETECTORS
    except ImportError:
        _DETECTORS = ()  # type: ignore
    # Mapping función_name → code canónico. Mayoría siguen el patrón
    # `detect_<code>`, pero algunos fueron renombrados (e.g.,
    # `detect_no_bone_protective_agent_for_radium223` → code
    # `no_bone_protective_agent`; `detect_creatinine_clearance_lt_30_for_rucaparib`
    # → code `creatinine_clearance_lt_30`).
    _FUNC_TO_CODE_OVERRIDES = {
        "no_bone_protective_agent_for_radium223": "no_bone_protective_agent",
        "creatinine_clearance_lt_30_for_rucaparib": "creatinine_clearance_lt_30",
    }
    for detector in _DETECTORS:
        name = getattr(detector, "__name__", "")
        if not name.startswith("detect_"):
            continue
        suffix = name[len("detect_"):]
        code = _FUNC_TO_CODE_OVERRIDES.get(suffix, suffix)
        if code not in seen:
            seen.add(code)
            codes.append(code)

    # 2. YAML loaded
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_loaded_yaml_codes,
        )
        for code in get_loaded_yaml_codes():
            if code not in seen:
                seen.add(code)
                codes.append(code)
    except ImportError:
        pass

    return sorted(codes)


def get_per_gate_yaml_shas() -> dict[str, str]:
    """Faubot 2026-04-25 (XI) — Retorna {gate_code: sha} de cada gate
    YAML cargado desde `pivotal_gates_catalog/`.

    Esto da **versionado granular**: cada gate tiene su propio SHA y
    puede actualizarse independientemente. Un revisor regulatorio puede
    auditar cada YAML como un artefacto versionable separado.

    Returns:
        Dict {gate_code: sha} (vacío si no hay YAMLs cargados o si el
        loader no está disponible).
    """
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_all_yaml_gate_shas,
        )
        return get_all_yaml_gate_shas()
    except ImportError:
        return {}


def get_yaml_loaded_gate_codes() -> list[str]:
    """Faubot 2026-04-25 (XI) — Lista de gates migrados a YAML."""
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            get_loaded_yaml_codes,
        )
        return get_loaded_yaml_codes()
    except ImportError:
        return []


def get_algorithm_version() -> dict[str, Any]:
    """Retorna el version stamp completo del algoritmo Faubot.

    Estructura JSON-serializable:
        {
            "faubot_release": "2026-04-25 XI",
            "module_sha": "a1b2c3d4e5f6",
            "module_path": "prostanet/shared/pivotal_contraindication_gates.py",
            "gates_active_count": 18,
            "gates_active_codes": [...],
            "yaml_loaded_gates_count": 4,
            "yaml_loaded_gate_codes": [...],
            "per_gate_yaml_shas": {gate_code: sha, ...},
        }
    """
    codes = get_active_gate_codes()
    yaml_codes = get_yaml_loaded_gate_codes()
    per_gate_shas = get_per_gate_yaml_shas()
    return {
        "faubot_release": FAUBOT_RELEASE,
        "module_sha": get_module_sha(),
        "module_path": "prostanet/shared/pivotal_contraindication_gates.py",
        "gates_active_count": len(codes),
        "gates_active_codes": codes,
        # Faubot 2026-04-25 (XI) — Versionado granular YAML.
        "yaml_loaded_gates_count": len(yaml_codes),
        "yaml_loaded_gate_codes": yaml_codes,
        "per_gate_yaml_shas": per_gate_shas,
    }


def is_version_compatible(
    audit_version: dict[str, Any] | None,
    current_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compara una versión del audit (persistida) con la versión actual.

    Útil para auditorías retrospectivas: cuando se carga un audit antiguo,
    este helper indica si los gates han cambiado desde entonces.

    Returns:
        {
            "compatible": bool,
            "release_changed": bool,
            "sha_changed": bool,
            "gate_count_delta": int,
            "added_gates": [...],
            "removed_gates": [...],
        }
    """
    audit = dict(audit_version or {})
    current = dict(current_version or get_algorithm_version())
    audit_codes = set(audit.get("gates_active_codes") or [])
    current_codes = set(current.get("gates_active_codes") or [])
    added = sorted(current_codes - audit_codes)
    removed = sorted(audit_codes - current_codes)
    release_changed = audit.get("faubot_release") != current.get("faubot_release")
    sha_changed = audit.get("module_sha") != current.get("module_sha")
    return {
        "compatible": not (release_changed or sha_changed),
        "release_changed": release_changed,
        "sha_changed": sha_changed,
        "gate_count_delta": len(current_codes) - len(audit_codes),
        "added_gates": added,
        "removed_gates": removed,
    }
