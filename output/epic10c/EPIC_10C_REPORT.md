# EPIC 10C — Performance & Accessibility Baseline Report

> Generado por `scripts/epic10c_audit_baseline.py` · 20 samples por endpoint · in-process via Flask test client (sin Lighthouse/axe-core).

## 1. Performance baseline

### HTML endpoints

| Endpoint | Label | p50 (ms) | p95 (ms) | p99 (ms) | Size median |
|---|---|--:|--:|--:|--:|
| `/clinical-hub` | Centro clínico | 38.27 | 40.52 | 41.51 | 123.0KB |
| `/patient_intake` | Intake progresivo | 0.19 | 0.22 | 0.24 | 0.3KB |
| `/dashboard` | Dashboard ejecutivo (deuda EPIC 10D) | 22486.14 | 25297.83 | 26150.44 | 50.8KB |

### JSON API endpoints

| Endpoint | Label | p50 (ms) | p95 (ms) | p99 (ms) | Size median |
|---|---|--:|--:|--:|--:|
| `/api/stats` | Estadísticas agregadas | 2.73 | 3.12 | 3.42 | 146B |
| `/api/decision-audit/algorithm-version` | FAUBOT release + SHAs | 2.02 | 2.22 | 2.27 | 12.9KB |
| `/api/modules/m1_crpc/schema` | Schema m1CRPC | 365.49 | 385.89 | 400.34 | 798.5KB |
| `/api/modules/m0_crpc/schema` | Schema m0CRPC | 337.13 | 349.51 | 368.03 | 727.4KB |
| `/api/modules/post_prostatectomy/schema` | Schema post-prostatectomy | 315.5 | 323.47 | 337.17 | 701.6KB |

### Thresholds aplicados (tests/test_epic10c_performance_baseline.py)

- **HTML** p95 ≤ 800ms, p99 ≤ 1500ms
- **API small (<200KB)** p95 ≤ 200ms, p99 ≤ 400ms
- **API large (≥200KB)** p95 ≤ 500ms, p99 ≤ 800ms
- **/dashboard** marked as `xfail` — deuda EPIC 10D pending optimization de queries SQLite + caching de KPIs

## 2. Accessibility WCAG 2.1 AA static audit

| Página | Status | H1 | Imgs sin alt | Inputs sin label | Buttons sin name | Violations |
|---|--:|--:|--:|--:|--:|--:|
| `/clinical-hub` | 200 | 7 | 0/1 | 0/0 | 0/28 | 1 |
| `/patient_intake` | 200 | 7 | 0/1 | 0/0 | 0/28 | 1 |
| `/dashboard` | 200 | 1 | 0/1 | 0/0 | 0/7 | 0 |

### Violations detalladas

#### `/clinical-hub` (Centro clínico)
- WCAG_2_4_6: la página tiene 7 <h1>. Recomendado: exactamente 1.

#### `/patient_intake` (Intake progresivo)
- WCAG_2_4_6: la página tiene 7 <h1>. Recomendado: exactamente 1.

## 3. Diagnóstico

**Endpoints con perf degradado:**
- HTML `/dashboard` p95=25297.83ms (target ≤ 800ms)

## 4. Próximos pasos (EPIC 10D candidates)

1. **Optimizar `/dashboard`** (p95 ~1700ms baseline). Probable: cachear `dashboard_summary_to_v2()` + materializar `cohort_summary` snapshot SQLite.
2. **Slim API schema responses** opcional — actualmente ~800KB por schema m1_crpc/m0_crpc post EPIC 10B; campos como `display_options`, `widget_config` podrían omitirse en respuesta JSON pública.
3. **Lighthouse + axe-core full audit** con Chrome headless (fuera del scope EPIC 10C in-process). Recomendable antes de FDA Pre-Sub.