# Reporte de Simplificación — Helpers Faubot (#23-#36)

**Scope analizado:** 6 archivos / 2173 líneas / 1285+ tests pasando.
**Filosofía:** Solo simplificaciones de **alto impacto / bajo riesgo**, preservando 100% funcionalidad y las 5 dimensiones del CDE Auditable.
**Fecha:** 2026-04-25 (Plan de Adopción AutoSkills, Paso 3.B)

---

## 1. Análisis de duplicación entre módulos

### 1.1 `_truthy_token` y derivados (3 implementaciones casi-idénticas)

| Archivo | Función | Tokens reconocidos | Status |
|---------|---------|-------------------|--------|
| `pivotal_contraindication_gates.py:60-65` | `_truthy_token` | 9 (`"1","true","yes","si","sí","present","positive","positivo","documented","documentado"`) | **Canónico** |
| `pivotal_gates_yaml_loader.py:73-84` | `_truthy_token` | 9 idénticos (set inline) | **Duplicado exacto** |
| `gates_ddi_cross_check.py:128-136` | `_is_truthy` + `_TRUTHY` | **7** (le faltan `"positivo"`, `"documented"`, `"documentado"`) | **🚨 Duplicado divergente — bug latente** |

**Riesgo clínico:** Si en `gates_ddi_cross_check.py` el payload llega con `seizure_history="documentado"` (ES-médica clínicamente válida), el cross-check NO se activará — pero el mismo valor activaría el detector Python. **Inconsistencia silenciosa.**

### 1.2 `_safe_int` / `_safe_float` (2 implementaciones idénticas bit-a-bit)

| Archivo | Funciones | Status |
|---------|-----------|--------|
| `pivotal_contraindication_gates.py:68-83` | `_safe_float`, `_safe_int` | Canónico |
| `pivotal_gates_yaml_loader.py:87-102` | `_safe_int`, `_safe_float` | Duplicado exacto |

### 1.3 `_extract_gates_from_assessment` ↔ `extract_previous_pivotal_gates` (semántica idéntica)

`gates_coverage_aggregator.py:43-48` y `pivotal_gate_delta.py:221-235` extraen lo mismo: `assessment.result_snapshot.pivotal_contraindication_gates` como list[dict].

---

## 2. Top 5 simplificaciones recomendadas (priorizadas por impacto/riesgo)

| # | Refactor | Archivo | Impacto | Riesgo | Líneas ahorradas | Justificación |
|---|----------|---------|---------|--------|------------------|---------------|
| **1** | **R8** — Importar `_truthy_token` canónico en cross_check | `gates_ddi_cross_check.py` | **ALTO (cierra bug latente)** | low-medium | ~10 | Resuelve inconsistencia ES-médica. Riesgo clínico real. |
| **2** | **R5** — Importar `_truthy_token`, `_safe_int`, `_safe_float` en YAML loader | `pivotal_gates_yaml_loader.py` | **ALTO (DRY + paridad garantizada)** | low | ~30 | Elimina 30 líneas duplicadas exactas; garantiza paridad Python/YAML estructuralmente. |
| **3** | **R6** — Dispatch dict en `_evaluate_trigger` | `pivotal_gates_yaml_loader.py` | **ALTO (legibilidad + extensibilidad)** | low | ~50 | Función baja de 180 → ~30 líneas + 10 handlers. Complejidad ciclomática ↓ de ~25 a ~3. |
| **4** | **R3** — Helper `_empty_audit_skeleton` | `decision_audit_builder.py` | medio | low | ~15 | Previene drift entre rama "no assessment" y rama "complete". |
| **5** | **R13** — Dispatch dicts en `_classify_gate_for_message` | `pivotal_gate_delta.py` | medio | low | ~10 | Datos-como-código; visualiza catálogo implícito. |

**Total ahorro estimado top-5:** ~115 líneas (5.3% del scope).

**Orden de ejecución recomendado:** 1 → 2 → 3 → 5 → 4 (cada uno se puede mergear independiente).

---

## 3. Refactors detallados por archivo

(Ver reporte completo en agent output — 14 refactors numerados R1-R14, distribuidos así:)

| Archivo | Refactors propuestos | Líneas |
|---------|----------------------|-------:|
| `algorithm_version.py` | R1 (constante), R2 (helper safe_yaml_call) | 206 |
| `decision_audit_builder.py` | R3 (skeleton), R4 (no tocar dispatch) | 276 |
| `pivotal_gates_yaml_loader.py` | R5 (DRY imports), R6 (dispatch handlers), R7 (resolve_catalog_or_literal) | 569 |
| `gates_ddi_cross_check.py` | R8 (truthy import), R9 (schema validation) | 296 |
| `gates_coverage_aggregator.py` | R10 (split aggregate), R11 (extract dedup), R12 (narrow except) | 569 |
| `pivotal_gate_delta.py` | R13 (classify dispatch), R14 (pluralize_es helper) | 257 |

---

## 4. Lo que NO cambiar (anti-patrones de simplificación)

1. **`_normalize_value` en `decision_audit_builder.py:36-46`** — el if-chain isinstance es **idiomático Python para coercion JSON** y respeta orden (bool antes de int por el bug histórico de `isinstance(True, int) == True`).
2. **`evaluate_pivotal_contraindication_gates` deduplicación por `code`** — la dedup es **esencial** para coexistencia Python+YAML.
3. **Catálogos `REGIMEN_CODES_*` como `frozenset` y `KEYWORDS_*` como `tuple`** — diferencia intencional (set semantics vs ordered substring match).
4. **`get_module_sha` recalculando on-demand sin cache** — comentario en docstring lo justifica.
5. **`_load_yaml_files` cache global mutable** — deliberado para `reset_yaml_cache()` desde tests.
6. **`_GATE_TO_RELATED_DDI_CATEGORIES`, `_GATE_TO_ONCOLOGY_DRUGS`, `_GATE_SUMMARIES`** — 3 dicts paralelos para legibilidad clínica.
7. **`severity_changed` lista de dicts con todos los campos `current_*`** — verbosidad por trazabilidad regulatoria.
8. **`_empty_coverage_dict` con defaults explícitos** — schema vacío DEBE coincidir bit-a-bit con output completo.

---

## 5. Plan de implementación recomendado

**Iteración Faubot dedicada (próxima audit #37 o post-cierre del bucle):**

- **Sprint 1 (low-risk wins):** R8 + R5 + R3 + R13 + R14 — todas low-risk, ~80 líneas ahorradas, **resuelve bug clínico latente (R8)**.
- **Sprint 2 (medium-risk pero alto valor):** R6 (dispatch trigger) — refactor mecánico cubierto por >200 tests.
- **Sprint 3 (futuro lejano):** R10 (split aggregate_gates_coverage) — requiere iteración dedicada con regresión completa.

**Para autorizar implementación:** El usuario debe confirmar cuál Sprint ejecutar. Este reporte es **propuesta**, no implementación automática.

---

*Generado por code-simplifier subagent al cierre del Plan de Adopción AutoSkills, Paso 3.B (Faubot 2026-04-25).*
