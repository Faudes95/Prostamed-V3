# EPIC 45 APPLY — Post-mortem y evidencia regulatoria

> **Fecha de aplicación**: 2026-05-22 02:37:33 UTC (initial bulk) + 02:45:58 UTC (re-apply auto-derive trigger)
> **FAUBOT release**: `2026-05-17 CXXX`
> **Operador**: Claude Sonnet 4.7 (asistido por urólogo, paciente Frin context)
> **Branch / commits**: `codex/save-current-prostanet-state-20260429` · pre `4ef67a7` · post (este reporte)

---

## Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Pacientes en cohorte total | **425** |
| Pacientes con contradicciones FactSpec alias antes del apply | **33 (7.8%)** |
| Resoluciones aplicadas | **34** (33 iniciales + 1 re-apply tras render UI) |
| Severidad de todas las resoluciones | **HIGH** (alias_group blocking) |
| Alias group afectado | `metastatic_stage_resolved` ↔ `m_substage_resolved` (bug-root Frin) |
| Contradicciones restantes post-apply (CLI dry-run) | **0** |
| Tiempo total de la operación | ~15 min (incluyendo restart server + UI smoke) |
| Reversibilidad | Completa (backup DB + cada resolución reversible individualmente) |
| Reglas invocadas | `most_recent_wins` (33/34) + 1 re-apply post auto-derive |

**Backup creado**: `prostanet_tracking.db.bak-pre-epic45-apply-20260521-203659` (163 MB)

---

## Contexto del cambio

Acabamos de shippear EPIC 45 (commit `4ef67a7`) que generaliza el fix manual del paciente Frin (M0 vs M1b alias contradiction) a toda la cohorte. El detector + auto-resolver con precedencia auditable identificó **33 pacientes** con el mismo patrón silencioso:

- `metastatic_stage_resolved=M0` + `m_substage_resolved=M1b` (o similar) ambos `is_active=1`
- Consumers downstream (Patient Twin OS lee canonical, Clinical Compass lee alias) → recomendaciones contradictorias
- Decision Fusion EPIC 23 detectaba severity=high pero no auto-resolvía

Esta operación cierra el loop: limpia el estado actual + el panel UI EPIC 45.C ahora muestra el historial de resoluciones aplicadas por cada paciente.

---

## Casos representativos (spot-check post-apply)

### Patient 39 (NSS `97000000001`) — Edge case borderline clínico

| Fact ID | Key | Value | Source | is_active (post-apply) | Notas |
|---|---|---|---|---|---|
| 4693 | `m_substage_resolved` | M1b | clinical_baseline | **0** (loser) | Antiguo (2026-04-22) |
| 27488 | `metastatic_stage_resolved` | M0 | wizard_or_intake | 0 (ya inactivo) | Wizard 2026-05-17 |
| 28455 | `metastatic_stage_resolved` | M0 | quick_capture_ui | **1** (winner) | Más reciente (2026-05-17 01:33) |

**Resolución**: M0 quick_capture_ui gana por `most_recent_wins`. **Caso borderline**: el clínico edited en quick_capture a M0, sobreescribiendo el M1b del clinical_baseline. Mecánicamente correcto, clínicamente requiere validación del urólogo para confirmar que fue intencional.

⚠️ **Recomendación post-mortem**: el clínico debe revisar el panel "Integridad de datos · 2 resoluciones históricas" en el perfil de este paciente. Si M1b era correcto, basta `UPDATE patient_clinical_facts SET is_active=1 WHERE id=4693` (provenance preservado en `verification_note`).

### Patient 86 (NSS `VAL-687e8a23-046`) — Caso ideal

| Fact ID | Key | Value | Source | is_active | Notas |
|---|---|---|---|---|---|
| 28708 | `metastatic_stage_resolved` | M1_unspecified | voice_cortana_dictation_epic40 | **1** (winner) | Más reciente + voice dictation |

**Resolución**: M1_unspecified gana por `most_recent_wins`. ✓ Clinical context preserved: el urólogo dictó vía voice EPIC 40, debe ser la fuente más reciente y autoritativa.

### Patient 273 (NSS `VAL-mcp-matr-012`) — Intake fragmentado

| Fact ID | Key | Value | Source | is_active | Notas |
|---|---|---|---|---|---|
| 643 | `metastatic_stage_resolved` | M1_unspecified | wizard_or_intake | 0 (loser) | 2026-04-10 00:35:09 |
| 647 | `m_substage_resolved` | M0 | clinical_baseline | **1** (winner) | 2026-04-10 00:35:17 (8s después) |

**Resolución**: M0 clinical_baseline gana por `most_recent_wins`. Caso típico de intake fragmentado: el wizard escribió `M1_unspecified`, luego el normalizador `clinical_baseline` consolidó a `M0` 8 segundos después.

---

## Hallazgo crítico: auto-derive recrea contradicciones (EPIC 45.B futuro)

Durante el UI smoke post-apply, navegando al perfil del paciente 39, observé que el panel UI reportaba **1 nueva contradicción detectada** — pese a que el CLI dry-run minutos antes reportó 0.

**Causa raíz**: el pipeline `auto-derive` (invocado al renderizar `/patient_profile/<nss>?v=2`) escribe `m_substage_resolved` desde múltiples writers en `tracking_db.py` (líneas 7999, 8242, 8320, 8642, 14246) sin respetar el modelo de aliases EPIC 45. Cada render del perfil de un paciente puede re-introducir el conflicto.

**Mitigación inmediata**: re-aplicamos EPIC 45 (1 resolución adicional, paciente 39, timestamp 02:45:58).

**EPIC 45.B propuesto** (futuro, ~3-5h):
- **Opción A — SQLite TRIGGER**: ON INSERT INTO `patient_clinical_facts`, automáticamente deactivar siblings alias del mismo paciente. Invariant a nivel DB, transparente a la aplicación.
- **Opción B — Post-write hook en `_persist_patient_clinical_facts`**: tras cada insert, llamar `factspec_alias_audit` sobre el paciente afectado. Más controlable pero invasivo.
- **Opción C — Patchear auto-derive writers** en `tracking_db.py`: solo escribir el canonical (nunca el alias). Más limpio pero requiere refactorizar 5+ writers.

Recomendación: **Opción A** (TRIGGER SQLite) por menor blast radius + invariant a nivel DB + cero cambios a la lógica de auto-derive.

---

## Audit trail completo

- `audit_trail_full.csv` (34 entries en `clinical_view_audit` section_key=`data_integrity`)
- `audit_log_post_apply.json` (resultado CLI dry-run post-apply, contradicciones=0)

Cada entry contiene: `patient_id`, `action=factspec_alias_resolved:<canonical>`, `importance=high`, `created_at=<UTC ISO>`.

Provenance per-fact en `patient_clinical_facts.verification_note`:
```
[auto-corrected via factspec_alias_audit ts=2026-05-22T02:37:33.374715+00:00] |
  reason: alias_group_canonical=metastatic_stage_resolved |
  rule: most_recent_wins |
  winner fact_id=28455 key=metastatic_stage_resolved value='M0'
  source=quick_capture_ui updated_at=2026-05-17 01:33:00
```

Formato 21 CFR Part 11 §11.10(e) compliant: timestamp ISO + razón + rule invoked + winner reference completo.

---

## Validación end-to-end (logs reales)

```bash
# === FASE 1: PRE-FLIGHT ===
kill 33651                    # ✓ port freed
cp prostanet_tracking.db prostanet_tracking.db.bak-pre-epic45-apply-20260521-203659  # 163M
python3 -m prostanet.regulatory.clinical.factspec_alias_audit
  # → Patients with contradictions: 33

# === FASE 2: APPLY ===
python3 -m prostanet.regulatory.clinical.factspec_alias_audit --apply
  # → Resolutions applied: 33 (APPLIED to DB)

# === FASE 3: POST-APPLY VALIDATION ===
python3 -m prostanet.regulatory.clinical.factspec_alias_audit
  # → Patients with contradictions: 0  ✓
sqlite3 prostanet_tracking.db "SELECT COUNT(*) FROM clinical_view_audit WHERE section_key='data_integrity'"
  # → 33  ✓
sqlite3 prostanet_tracking.db "SELECT COUNT(*) FROM patient_clinical_facts WHERE is_active=0 AND verification_note LIKE '%auto-corrected via factspec_alias_audit%'"
  # → 33  ✓

# === FASE 4: REST VALIDATION ===
curl /api/data-integrity/audit
  # → total_contradictions: 0, by_severity {high:0, medium:0}  ✓
curl /api/data-integrity/97000000001
  # → contradictions_count: 0, resolutions_count: 1+  ✓

# === FASE 5: UI SMOKE (Playwright) ===
# Panel data-testid="data-integrity-panel" renders:
#   contradictions_count: 0
#   needs_review: 0 (no red badge)
#   heading: "✓ Sin contradicciones activas · 2 resoluciones históricas"
#   <details> Historial de resoluciones (2): renders both entries with timestamp + canonical
# → ✓ via Playwright DOM probe + screenshot epic45_apply_data_integrity_panel_resolved.png
```

---

## Próximos pasos recomendados

1. **EPIC 45.B (high priority)** — implementar SQLite TRIGGER para hacer el modelo de aliases invariante a nivel DB (~3h). Sin esto, cada vez que un paciente se renderiza, el auto-derive puede crear nuevas contradicciones que requerirán re-apply.

2. **Revisión clínica del patient 39** — el urólogo debe validar si M0 (quick_capture_ui reciente) o M1b (clinical_baseline antiguo) es el valor correcto. Si M1b era correcto, basta un `UPDATE patient_clinical_facts SET is_active=1 WHERE id=4693`.

3. **Loop monitor integration** — el 9° vector `recommendation_concordance` de GodiBot ya monitorea concordancia agentic. Considerar agregar 10° vector `data_integrity` que reporte `contradictions_count` poblacional como métrica de salud sistémica del catálogo de facts.

4. **Cron weekly audit** — añadir GitHub Action workflow que corra `--apply` semanal y reporte si encuentra contradicciones nuevas. Si EPIC 45.B se implementa, este cron pasa a ser solo verificación (debe siempre encontrar 0).

---

## Files of record

| File | Purpose |
|---|---|
| `prostanet_tracking.db.bak-pre-epic45-apply-20260521-203659` | Backup completo pre-apply (163 MB) |
| `output/epic45_apply_2026-05-22/audit_log_post_apply.json` | CLI dry-run output post-apply (0 contradicciones) |
| `output/epic45_apply_2026-05-22/audit_trail_full.csv` | 34 entries `clinical_view_audit` section_key=`data_integrity` |
| `output/epic45_apply_2026-05-22/REPORT.md` | Este documento |
| `.claude/worktrees/upbeat-wilbur-ee9619/epic45_apply_data_integrity_panel_resolved.png` | Screenshot Playwright del panel post-apply |
