# PROSTANET — Análisis Completo del Perfil Multimodal de Riesgo
## Documento Técnico para Revisión por Panel de Expertos
### Fecha: 2026-03-09 | Versión: 3.0

---

## ÍNDICE
1. [Arquitectura General](#1-arquitectura-general)
2. [Los 12 Ejes del Radar](#2-los-12-ejes-del-radar)
3. [Normalización de Cada Eje (0-100)](#3-normalización)
4. [Score Integrado ProstaNet (Ponderaciones)](#4-score-integrado)
5. [Detección de Discordancias](#5-discordancias)
6. [Motor de Recomendaciones](#6-recomendaciones)
7. [Puntos Críticos para Revisión Experta](#7-revisión-experta)
8. [Propuesta de Calibración](#8-propuesta-calibración)

---

## 1. ARQUITECTURA GENERAL

```
                    ┌──────────────────────────────────────┐
                    │         FORMULARIO CLÍNICO           │
                    │  (28 variables + PSA History)        │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │        MOTOR DE CÁLCULO              │
                    │  clinical_scores.py (15 algoritmos)  │
                    │  ML model (PyTorch multi-output)     │
                    └──────────────┬───────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼─────────┐ ┌───────▼────────┐ ┌─────────▼──────────┐
    │  RADAR 12 EJES    │ │ SCORE INTEGRADO│ │ REPORTE NARRATIVO  │
    │  (Visualización)  │ │ ProstaNet 0-100│ │ (15 secciones)     │
    │  Normalización JS │ │ 5 componentes  │ │ report_generator.py│
    └───────────────────┘ └────────────────┘ └────────────────────┘
```

### Flujo de Datos
1. **Entrada**: 28 variables clínicas del formulario + historial PSA
2. **Backend**: `calculate_all_scores()` ejecuta 15 algoritmos en paralelo
3. **Salida triple**:
   - Radar de 12 ejes (normalización 0-100 en JavaScript del frontend)
   - Score Integrado ProstaNet (ponderación 0-100 en backend Python)
   - Reporte narrativo clínico (15 secciones de texto)

---

## 2. LOS 12 EJES DEL RADAR

| # | Eje | Algoritmo | Referencia | Variables de Entrada | Tipo de Salida |
|---|-----|-----------|------------|---------------------|----------------|
| 1 | **NCCN** | Clasificación jerárquica | NCCN v1.2025 | PSA, Gleason/GG, T-stage, cores, PSAD | 6 categorías |
| 2 | **CAPRA** | Score aditivo 0-10 | Cooperberg 2005 | PSA, edad, Gleason, T-stage, %cores+ | Score 0-10 |
| 3 | **D'Amico** | Peor factor | D'Amico JAMA 1998 | PSA, Gleason, T-stage | 3 categorías |
| 4 | **EAU 2024** | Jerárquica + subclasificación | EAU Guidelines 2024 §6.2 | PSA, ISUP, T-stage, %cores+ | 5 categorías |
| 5 | **Briganti LNI** | Regresión logística | Briganti Eur Urol 2012/2017 | PSA, Gleason, T-stage, %cores+ | % (0.1-99%) |
| 6 | **Kattan (inv)** | Regresión logística + RCS | MSK Nomogram 2024 | PSA, edad, GG, T-stage | % org-confinado |
| 7 | **MSKCC BCR** | Regresión logística | Stephenson JCO 2006 | PSA, Gleason, T-stage, %cores+ | % BCR-free |
| 8 | **Cinética PSA** | Regresión lineal/log-lineal | Carter JAMA | ≥2 valores PSA con fechas | vel + PSADT |
| 9 | **ML Risk** | Red neuronal multi-output | ProstaNet v3.0 (interno) | 28 features completas | Prob. riesgo |
| 10 | **PSAD** | Cociente PSA/Volumen | AUA/EAU standard | PSA, volumen prostático | ng/mL/cc |
| 11 | **eGFR (inv)** | CKD-EPI 2021 (sin raza) | Inker LA NEJM 2021 | Creatinina, edad, sexo | mL/min/1.73m² |
| 12 | **PHI** | (p2PSA/fPSA)×√tPSA | Catalona J Urol 2011 | tPSA, fPSA ratio, p2PSA | Score PHI |

---

## 3. NORMALIZACIÓN DE CADA EJE (0-100)

> **CONCEPTO CLAVE**: Todos los ejes están orientados para que **mayor valor = mayor riesgo**.
> Los ejes que miden algo "favorable" (Kattan OC, MSKCC BCR-free, eGFR) se **invierten**.

### EJE 1 — NCCN (Mapeo Ordinal)

```
MUY BAJO ──────────→ 10/100
BAJO ──────────────→ 25/100
INTERMEDIO FAVORABLE → 40/100
INTERMEDIO DESFAV.  → 55/100
ALTO ──────────────→ 80/100
MUY ALTO ──────────→ 100/100
```

**⚠️ OBSERVACIÓN PARA EXPERTOS**: Los intervalos NO son equidistantes.
- Salto BAJO→INT.FAV = 15 puntos
- Salto ALTO→MUY ALTO = 20 puntos
- Salto INT.DESFAV→ALTO = 25 puntos (el mayor)

**¿Es clínicamente correcto que ALTO→MUY ALTO sea solo 20 puntos pero INT.DESFAV→ALTO sea 25?**

### EJE 2 — CAPRA (Lineal)

```
Fórmula: (score / 10) × 100

Score 0  → 0/100
Score 2  → 20/100    (Bajo)
Score 5  → 50/100    (Intermedio)
Score 8  → 80/100    (Alto)
Score 10 → 100/100
```

**DESGLOSE DEL SCORE CAPRA (0-10 puntos)**:

| Variable | Condición | Puntos | Peso Relativo |
|----------|-----------|--------|---------------|
| Edad | ≥50 años | 1 | 10% |
| PSA ≤6 | - | 0 | 0-40% |
| PSA 6.01-10 | - | 1 | |
| PSA 10.01-20 | - | 2 | |
| PSA 20.01-30 | - | 3 | |
| PSA >30 | - | 4 | |
| Gleason primario ≥4 | - | 3 | 10-30% |
| Gleason secundario ≥4 | (si primario <4) | 1 | |
| T-stage T3a+ | - | 1 | 10% |
| %Cores ≥34% | - | 1 | 10% |

**⚠️ OBSERVACIÓN**: El patrón Gleason primario ≥4 vale **3 puntos** (30% del total), haciéndolo el factor dominante. El PSA puede llegar a 4 puntos (40%), pero requiere PSA >30.

### EJE 3 — D'Amico (Ordinal Simple)

```
BAJO ────→ 20/100     (PSA ≤10, Gleason ≤6, ≤T2a: TODO se cumple)
INTERMEDIO → 55/100   (PSA 10-20 O Gleason 7 O T2b)
ALTO ────→ 90/100     (PSA >20 O Gleason ≥8 O ≥T2c)
```

**Lógica**: Clasificación por "peor factor" — un solo factor adverso eleva la categoría.

**⚠️ OBSERVACIÓN**: Solo 3 niveles con saltos de 35 puntos. Baja resolución comparada con NCCN (6 niveles).

### EJE 4 — EAU 2024 (Parsing de Texto)

```
BAJO ─────────────→ 15/100
INT. Favorable ───→ 35/100
INT. Desfavorable → 55/100
ALTO ─────────────→ 75/100
MUY ALTO/AVANZADO → 95/100
```

**Subclasificación Intermedio** (factores desfavorables):
- ISUP 3
- PSA >15
- >50% cores positivos
→ ≥2 factores = "Desfavorable"; <2 = "Favorable"

**⚠️ OBSERVACIÓN**: El parsing usa `.includes()` en strings, lo que es frágil. Un cambio de formato en el backend puede romper la lógica.

### EJE 5 — Briganti LNI (Amplificado ×2.5)

```
Fórmula: min(probabilidad_lni × 2.5, 100)

LNI 0% ───→ 0/100
LNI 5% ───→ 12.5/100   (umbral ePLND)
LNI 20% ──→ 50/100
LNI 40% ──→ 100/100
LNI 60% ──→ 100/100    (saturado)
```

**Algoritmo Backend** (regresión logística aproximada):
```
LP = -5.10 + 0.65×ln(PSA+1) + β_stage + β_gleason + 2.50×%cores
P(LNI) = 1 / (1 + exp(-LP))
```

| Variable | Coeficiente | Peso Relativo en LP |
|----------|-------------|---------------------|
| Intercept | -5.10 | Línea base (protector) |
| ln(PSA+1) | 0.65 | Moderado |
| %Cores positivos | 2.50 | **DOMINANTE** |
| Gleason 4+3 | 1.10 | Alto |
| Gleason 9 | 2.00 | Muy alto |
| T3a | 1.35 | Alto |
| T3b | 1.90 | Muy alto |

**⚠️ OBSERVACIÓN**: El multiplicador ×2.5 amplifica los valores porque la mayoría de pacientes tienen LNI <20%. Pero esto causa **saturación precoz** — pacientes con LNI >40% son indistinguibles en el radar.

### EJE 6 — Kattan (Invertido)

```
Fórmula: 100 - probabilidad_órgano_confinado

OC 95% → 5/100    (excelente, bajo riesgo)
OC 70% → 30/100   (moderado)
OC 50% → 50/100   (intermedio)
OC 20% → 80/100   (alto riesgo ECE/SVI)
OC 5%  → 95/100   (muy alto riesgo)
```

**Algoritmo Backend** (regresión logística + splines cúbicos restringidos):
```
LP = 4.0392 + (-0.0309)×edad + (-0.2325)×PSA
     + 0.00152×spline1(PSA) + (-0.00420)×spline2(PSA)
     + β_GG + β_stage
P(OC) = 1 / (1 + exp(-LP))
```

**Coeficientes Grade Group** (vs GG1=0):
| GG | β | Efecto |
|----|---|--------|
| GG2 | -0.664 | Moderado |
| GG3 | -1.148 | Alto |
| GG4 | -1.205 | Alto |
| GG5 | -2.184 | Muy alto |

**⚠️ OBSERVACIÓN**: El efecto no-lineal del PSA (splines) es la principal fortaleza de este nomograma vs. modelos lineales.

### EJE 7 — MSKCC BCR (Invertido)

```
Fórmula: 100 - BCR_free_5y

BCR-free 90% → 10/100  (bajo riesgo recurrencia)
BCR-free 65% → 35/100  (moderado)
BCR-free 40% → 60/100  (alto)
BCR-free 15% → 85/100  (muy alto riesgo)
```

**Algoritmo Backend**:
```
LP = -1.8 + 0.35×ln(PSA) + β_gleason + β_stage + 0.8×%cores
BCR_prob_5y = 1/(1+exp(-LP))
BCR_free_5y = 1 - BCR_prob_5y
BCR_free_10y = BCR_free_5y^1.6   (extrapolación)
```

**⚠️ OBSERVACIÓN**: La extrapolación a 10 años usa potencia ^1.6, que es una aproximación. La validación clínica sugiere ^1.4-1.8 dependiendo de la cohorte.

### EJE 8 — Cinética PSA (Categórico por Umbrales)

```
Velocidad >2.0 ng/mL/año O PSADT <3 meses  → 95/100
Velocidad >0.75 O PSADT <10 meses           → 70/100
Velocidad >0.35                              → 45/100
Velocidad >0 (ascenso lento)                 → 25/100
Default (estable o descendente)              → 10/100
```

**⚠️ OBSERVACIÓN**: Los umbrales de velocidad están basados en Carter et al. (JAMA) para detección, pero no se han calibrado específicamente para pacientes ya diagnosticados. La velocidad post-diagnóstico tiene diferente significado clínico que la velocidad de screening.

### EJE 9 — ML Risk (Ponderación ALTO + INTERMEDIO)

```
Fórmula: Prob_ALTO(%) + 0.5 × Prob_INTERMEDIO(%)

Ejemplo:
  ALTO=60%, INTERMEDIO=25%, BAJO=15%
  → 60 + 0.5×25 = 72.5/100

  ALTO=5%, INTERMEDIO=30%, BAJO=65%
  → 5 + 0.5×30 = 20/100
```

**⚠️ OBSERVACIÓN**: El peso de 0.5 para INTERMEDIO es **arbitrario**. No se derivó de una curva ROC ni de un análisis de calibración. Un peso de 0.3 o 0.7 cambiaría significativamente el perfil del radar.

### EJE 10 — PSAD (Amplificado ×500)

```
Fórmula: min(PSAD × 500, 100)

PSAD 0.05 → 25/100
PSAD 0.10 → 50/100
PSAD 0.15 → 75/100   (umbral clásico)
PSAD 0.20 → 100/100  (saturado)
PSAD 0.40 → 100/100  (saturado)
```

**⚠️ OBSERVACIÓN**: Saturación a PSAD ≥0.20, pero pacientes con PSAD >0.40 (enfermedad agresiva de bajo volumen) no se diferencian. El multiplicador ×500 fue elegido para que el umbral clínico de 0.15 quede en ~75%.

### EJE 11 — eGFR Invertido

```
Fórmula: max(0, 100 - eGFR)

eGFR 120  → 0/100   (excelente función renal, no impacta)
eGFR 90   → 10/100  (normal)
eGFR 60   → 40/100  (precaución con cisplatino)
eGFR 30   → 70/100  (ajustar dosis, alto riesgo)
eGFR 15   → 85/100  (falla renal)
```

**⚠️ OBSERVACIÓN**: El eGFR NO es un score de riesgo oncológico — es una variable de elegibilidad y seguridad. Su inclusión en el radar puede confundir si se interpreta como "riesgo de cáncer" vs "riesgo de toxicidad".

### EJE 12 — PHI

```
Con p2PSA disponible:
  Fórmula: min((PHI_score / 60) × 100, 100)

  PHI 15 → 25/100
  PHI 27 → 45/100
  PHI 40 → 67/100
  PHI 55 → 92/100
  PHI 60 → 100/100

Sin p2PSA (fallback con %fPSA):
  Fórmula: max(0, 90 - fPSA% × 3.5)

  fPSA 25% → 2.5/100  (bajo riesgo)
  fPSA 15% → 37.5/100 (moderado)
  fPSA 10% → 55/100   (alto)
  fPSA 5%  → 72.5/100 (muy alto)
```

**⚠️ OBSERVACIÓN**: El fallback con %fPSA es una aproximación grosera. El PHI verdadero incorpora p2PSA, que tiene valor predictivo independiente. El fallback podría sobre/subestimar el riesgo en ~20%.

---

## 4. SCORE INTEGRADO PROSTANET (Ponderaciones)

### Componentes y Pesos

```
Score ProstaNet = 0.30 × NCCN_norm + 0.25 × CAPRA_norm
                + 0.15 × Briganti_norm + 0.15 × Kattan_inv
                + 0.15 × Kinetics_risk
```

| Componente | Peso | Justificación | Normalización |
|------------|------|---------------|---------------|
| **NCCN** | **30%** | Mayor adopción clínica, validación multicéntrica | MUY BAJO=5, BAJO=15, INT.FAV=35, INT.DESFAV=55, ALTO=75, MUY ALTO=95 |
| **CAPRA** | **25%** | C-index 0.68-0.80 para BCR, validado en múltiples cohortes | (score/10)×100 |
| **Briganti** | **15%** | Predicción de invasión ganglionar — impacta decisión quirúrgica | % directo (0-100) |
| **Kattan (inv)** | **15%** | Probabilidad de enfermedad órgano-confinada | 100 - prob_OC |
| **Cinética PSA** | **15%** | Agresividad biológica dinámica | Categórico: 10/25/50/80/85 |

### Normalización del Score Integrado vs Radar

⚠️ **DISCREPANCIA IMPORTANTE**: El score integrado usa valores DIFERENTES al radar para NCCN:

| NCCN Grupo | Radar | Score Integrado | Delta |
|------------|-------|-----------------|-------|
| MUY BAJO | 10 | 5 | -5 |
| BAJO | 25 | 15 | -10 |
| INT. FAVORABLE | 40 | 35 | -5 |
| INT. DESFAVORABLE | 55 | 55 | 0 |
| ALTO | 80 | 75 | -5 |
| MUY ALTO | 100 | 95 | -5 |

### Clasificación Final

| Score Integrado | Grupo de Riesgo |
|-----------------|-----------------|
| < 35 | **BAJO** |
| 35-64 | **INTERMEDIO** |
| ≥ 65 | **ALTO** |

### Variables NO incluidas en el Score Integrado

| Variable | En Radar | En Score Integrado | Motivo |
|----------|----------|-------------------|--------|
| D'Amico | ✅ Eje 3 | ❌ | Redundante con NCCN |
| EAU 2024 | ✅ Eje 4 | ❌ | Redundante con NCCN |
| MSKCC BCR | ✅ Eje 7 | ❌ | Parcialmente capturado por CAPRA |
| ML Risk | ✅ Eje 9 | ❌ | Validación externa pendiente |
| PSAD | ✅ Eje 10 | ❌ | Incluido indirectamente en NCCN VLR |
| eGFR | ✅ Eje 11 | ❌ | No es score oncológico |
| PHI | ✅ Eje 12 | ❌ | Disponibilidad limitada |

---

## 5. DETECCIÓN DE DISCORDANCIAS

### Implementación Actual

Solo compara **NCCN vs ML Model**:

```
ML Risk Level:
  ALTO prob >70%   → ML dice "ALTO"
  ALTO prob 30-70% → ML dice "INTERMEDIO"
  ALTO prob <30%   → ML dice "BAJO"

Discordancias detectadas:
  1. NCCN "BAJO" + ML "ALTO" → Alerta: revisar biomarcadores genómicos
  2. NCCN "ALTO" + ML "BAJO" → Alerta: considerar mortalidad competitiva
```

### ⚠️ DISCORDANCIAS NO DETECTADAS ACTUALMENTE

| Comparación | Ejemplo Clínico | Impacto |
|-------------|-----------------|---------|
| D'Amico ALTO + NCCN INT.FAV | Gleason 3+4, PSA 12, T2b → D'Amico ALTO por T2b, NCCN INT por GG2 | Tratamiento diferente |
| CAPRA 7 (ALTO) + NCCN INT.DESFAV | Score aditivo alto pero NCCN categoría intermedia | Sub-clasificación |
| Briganti >5% + NCCN BAJO | PSA 8, GG1, T1c pero cores 45% → Briganti sugiere ePLND | Cirugía más extensiva |
| Kattan OC <40% + NCCN INT.FAV | Impacto negativo de splines no capturado por NCCN | ECE/SVI no anticipado |
| EAU DESFAVORABLE + NCCN FAVORABLE | EAU usa PSA>15 como factor, NCCN no | Diferente intensidad de tratamiento |

---

## 6. MOTOR DE RECOMENDACIONES (report_generator.py)

### Secciones del Reporte Narrativo (15 secciones)

| # | Sección | Umbral/Lógica Principal |
|---|---------|------------------------|
| 1 | Encabezado | Edad, PSA actual |
| 2 | Cinética PSA | Vel >0.75 O PSADT <10m → "PROGRESIÓN RÁPIDA" |
| 3 | Riesgo NCCN | Grupo + factores contribuyentes |
| 4 | Biopsia/Estadificación | T2b/T2c O cores>50% → "riesgo ECE elevado" |
| 5 | Recomendación NCCN | Del campo `recomendacion` del score |
| 6 | Riesgo Adicional | CAPRA + Briganti ≥5% → ePLND obligatoria |
| 7 | CAPRA-S | Solo si datos post-quirúrgicos presentes |
| 8 | Esperanza de Vida | SSA 2020 base × factor CCI; <10a → AS |
| 9 | Partin Tables | OC, ECE, SVI, LNI distribución |
| 10 | Elegibilidad VA | 5 protocolos: NCCN VLR, NCCN Low, NCCN Fav.Int, PRIAS, JHU |
| 11 | Imagen | PI-RADS, PSMA-PET, gammagrama óseo |
| 12 | Genómica | Decipher <0.45 → AS; >0.60 → agresivo; HRR+ → olaparib |
| 13 | Factores de Riesgo | DM2, tabaquismo (>15 cig/d → agresividad), IPSS |
| 14 | Score ProstaNet | Muestra pesos: NCCN 30%, CAPRA 25%, Briganti/Kattan/Kinetics 15% cada uno |
| 15 | PSAD | ≥0.15 → desfavorable; <0.15 → favorable |

### Umbrales Clínicos Clave en Recomendaciones

| Variable | Umbral | Acción Generada |
|----------|--------|-----------------|
| Esperanza de vida | <10 años | Recomendar AS/observación sobre cirugía |
| Briganti LNI | ≥5% | ePLND obligatoria |
| PSAD | ≥0.15 | Excluye NCCN Very Low Risk |
| Decipher | <0.45 | Favorece AS |
| Decipher | >0.60 | "Enfermedad agresiva" |
| HRR mutación | + | Elegible para PARP inhibidores |
| MSI-H | + | Elegible para pembrolizumab |
| PI-RADS 5 | + | "Alta sospecha malignidad clínicamente significativa" |

---

## 7. PUNTOS CRÍTICOS PARA REVISIÓN EXPERTA

### 7.1 Ponderación del Score Integrado

**PREGUNTA 1**: ¿Los pesos 30/25/15/15/15 son clínicamente apropiados?

Argumentos a favor:
- NCCN (30%) es el estándar más usado globalmente
- CAPRA (25%) tiene la mejor evidencia de discriminación (c-index 0.68-0.80)

Argumentos en contra:
- Briganti LNI (15%) tiene impacto directo en decisión quirúrgica (ePLND sí/no)
- La cinética PSA (15%) no ha sido validada como predictor independiente en pacientes ya diagnosticados
- D'Amico, EAU, MSKCC BCR no participan en el score compuesto

**PREGUNTA 2**: ¿Debería el ML Risk entrar al score integrado?
- Pro: Captura patrones no lineales entre las 28 variables
- Contra: Modelo no validado externamente, potencial sobreajuste

### 7.2 Normalización del Radar

**PREGUNTA 3**: ¿El multiplicador ×2.5 para Briganti es apropiado?
- Efectos: LNI 40% = 100 en radar. Esto "infla" visualmente el Briganti.
- Alternativa: Usar transformación logarítmica o empírica basada en percentiles de la cohorte.

**PREGUNTA 4**: ¿PSAD con ×500 satura demasiado rápido?
- PSAD 0.20 ya marca 100. Pacientes con PSAD 0.40+ son indistinguibles.
- El umbral clínico de 0.15 queda en 75, lo cual parece excesivo visualmente.

**PREGUNTA 5**: ¿El peso 0.5 para INTERMEDIO en ML Risk es correcto?
- Actualmente: `ALTO% + 0.5 × INTERMEDIO%`
- Si un paciente tiene 40% INTERMEDIO y 5% ALTO → score = 25
- ¿Debería ser 0.3 (más conservador) o 0.7 (más sensible)?

### 7.3 Ejes del Radar que NO son Riesgo Oncológico

**PREGUNTA 6**: ¿El eGFR debería estar en el radar de riesgo?
- eGFR mide función renal, no riesgo oncológico
- Un paciente con eGFR 30 y NCCN Muy Bajo Risk tendría un "pico" en el radar que podría malinterpretarse
- Alternativa: Panel separado de "Seguridad/Elegibilidad" vs "Riesgo Oncológico"

**PREGUNTA 7**: ¿PHI es apropiado post-diagnóstico?
- PHI fue diseñado para decisión de biopsia (pre-diagnóstico)
- En paciente ya biopsiado con Gleason conocido, el valor agregado es limitado
- Pero en contexto de vigilancia activa, puede tener valor como marcador de reclasificación

### 7.4 Discordancias No Detectadas

**PREGUNTA 8**: ¿Debería implementarse detección cruzada de discordancias?
- Actualmente solo NCCN vs ML
- Propuesta: D'Amico vs NCCN, EAU vs NCCN, CAPRA vs NCCN, Briganti vs NCCN (LNI >5% en riesgo bajo)

### 7.5 Duplicación de Funciones en el Código

**ALERTA TÉCNICA**: Existen funciones duplicadas:
- `calculate_all_scores()`: línea 498 (vieja) y línea 1478 (activa)
- `calculate_capra_s()`: línea 386 y línea 717 — **con diferente puntuación para ECE** (2 puntos vs 1 punto)

---

## 8. PROPUESTA DE CALIBRACIÓN

### 8.1 Calibración por Panel Delphi

Recomiendo que los expertos asignen pesos mediante consenso Delphi modificado:

**Ronda 1**: Cada experto asigna pesos de 1-10 a cada score para su contribución al pronóstico:

| Score | Peso Actual | Experto 1 | Experto 2 | Experto 3 | Consenso |
|-------|-------------|-----------|-----------|-----------|----------|
| NCCN | 30% | ___ | ___ | ___ | ___ |
| CAPRA | 25% | ___ | ___ | ___ | ___ |
| D'Amico | 0% (no incluido) | ___ | ___ | ___ | ___ |
| EAU 2024 | 0% (no incluido) | ___ | ___ | ___ | ___ |
| Briganti | 15% | ___ | ___ | ___ | ___ |
| Kattan | 15% | ___ | ___ | ___ | ___ |
| MSKCC BCR | 0% (no incluido) | ___ | ___ | ___ | ___ |
| Cinética PSA | 15% | ___ | ___ | ___ | ___ |
| ML Risk | 0% (no incluido) | ___ | ___ | ___ | ___ |
| PSAD | 0% (no incluido) | ___ | ___ | ___ | ___ |
| eGFR | 0% (no incluido) | ___ | ___ | ___ | ___ |
| PHI | 0% (no incluido) | ___ | ___ | ___ | ___ |

### 8.2 Calibración por Datos (cuando n ≥ 100)

Con suficientes pacientes con outcomes:
1. Calcular C-index individual de cada score para BCR, metástasis, mortalidad
2. Usar pesos proporcionales al C-index (o mediante elastic net regularization)
3. Validación bootstrap 10-fold para estabilidad de pesos

### 8.3 Normalización Empírica del Radar

En lugar de fórmulas fijas (×2.5, ×500), usar **percentiles de la cohorte**:
```
Radar_value = percentil_en_nuestra_cohorte(valor_crudo) × 100
```
Esto auto-calibra los ejes a la distribución real de nuestros pacientes, eliminando el problema de saturación y amplificación arbitraria.

### 8.4 Propuesta de Radar Bi-Capa

Dividir el radar en dos paneles:

**Panel A — Riesgo Oncológico (8 ejes)**:
NCCN, CAPRA, D'Amico, EAU, Briganti, Kattan, MSKCC BCR, Cinética PSA

**Panel B — Perfil Complementario (4 ejes)**:
ML Risk, PSAD, eGFR (seguridad), PHI (reclasificación)

Esto evita que variables de elegibilidad (eGFR) contaminen visualmente el perfil de riesgo oncológico.

---

## RESUMEN EJECUTIVO PARA EL PANEL

| Aspecto | Estado Actual | Recomendación |
|---------|---------------|---------------|
| Número de ejes radar | 12 | ✅ Adecuado, pero considerar bi-capa |
| Ponderación integrada | 5 componentes (30/25/15/15/15) | 🔶 Revisar con Delphi + C-index |
| Normalización radar | Fórmulas fijas (lineales, categóricas) | 🔶 Migrar a percentiles empíricos |
| Discordancias | Solo NCCN vs ML | ⚠️ Ampliar a cruce multi-score |
| Variables no-oncológicas | eGFR, PHI en mismo radar | 🔶 Panel separado |
| Coeficientes Briganti | Aproximados (no publicados) | ⚠️ Documentar explícitamente |
| BCR 10 años MSKCC | Extrapolación ^1.6 | 🔶 Ajustar a ^1.4-1.8 según cohorte |
| Funciones duplicadas | CAPRA-S con puntuación diferente | 🔴 Corregir urgente |
| ML Risk peso 0.5 | Arbitrario | 🔶 Calibrar con datos |

---

*Documento generado automáticamente por ProstaNet v3.0*
*Para revisión por panel de expertos en uro-oncología*
