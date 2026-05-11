# CDS Final Guidance FDA Sept 2022 — Memo de aplicabilidad ProstaMed

> **Documento regulatorio**: *Clinical Decision Support Software — Final Guidance
> for Industry and FDA Staff*. U.S. Food and Drug Administration, Sept 28 2022.

---

## Resumen ejecutivo

ProstaMed/ProstaNet **NO califica para la excepción CDS** del 21st Century
Cures Act (sección 3060). Por tanto, debe ser tratado como **device software
function** y seguir ruta de submission FDA Class II 510(k).

---

## Análisis de los 4 criterios CDS

Para que un software NO sea device, debe cumplir **TODOS** los siguientes 4
criterios (sección 520(o)(1)(E) FD&C Act, clarificados por Final Guidance Sept 2022):

### Criterio 1 — NOT intended to acquire/process/analyze medical image, signal, or pattern from in vitro diagnostic device

**ProstaMed**: ✓ (mostly true). El sistema NO procesa imágenes raw (DICOM),
señales fisiológicas, ni IVD output directly. Sí ingiere PSA values (texto/numérico),
Gleason scores (texto), y staging cT/cN/cM (categórico) — estos no son "patrones".

**Conclusión Criterio 1**: ✅ **MET** (con caveat que ML predictions
internas — Decipher score, Halabi nomogram outputs — podrían mover esto si
se interpretan como "patterns from IVD").

### Criterio 2 — Intended only to display, analyze, or print medical information about a patient

**ProstaMed**: ✗ **NOT MET**. El sistema NO solo "displays/analyzes/prints" —
ACTIVAMENTE GENERA recomendaciones específicas de tratamiento (ARPI doublet,
taxano, PARP inhibitor, etc.) basadas en algoritmos clínicos.

**Conclusión Criterio 2**: ❌ **NOT MET**.

### Criterio 3 — Intended to support or provide recommendations to a HCP

**ProstaMed**: ✓ Recomendaciones SÍ son para clínicos (no consumidor final).

**Conclusión Criterio 3**: ✅ **MET**.

### Criterio 4 — Intended to enable HCP to independently review the basis for recommendations so that the HCP does not rely primarily on the software

**ProstaMed**: ✗ **NOT MET**. Aunque el sistema expone "Reasoning Chain" con
19 keys del compass + per-gate evidence drill-down + 5 dimensiones CDE Auditable,
las recomendaciones específicas requieren capacidad cognitiva sobrehumana para
"reproducir mentalmente":

- **Elegibilidad PARP**: requiere evaluar 8 genes HRR + germinal vs somatic
  + exposición ARPI previa + ECOG fitness simultáneamente.
- **Cohort comparison overlay**: media poblacional curvas pivotales (CHAARTED,
  LATITUDE, etc.) — clínico no puede reconstruir mentalmente.
- **What-if simulator**: simula cambios en compass keys + diff de 14 keys.
- **PSA forecast log-linear per-line**: regression matemática per treatment line.

El clínico depende del cálculo del software, NO solo lo "valida". Por tanto, el
clínico NO puede revisar independientemente sin re-computar el algoritmo.

**Conclusión Criterio 4**: ❌ **NOT MET**.

---

## Decisión final

| Criterio | Met | Justificación |
|----------|-----|---------------|
| C1 — No image/signal/pattern from IVD | ✅ | No raw imaging, sí PSA texto |
| C2 — Only display/analyze/print | ❌ | Genera recomendaciones específicas |
| C3 — Support HCP (not consumer) | ✅ | Audiencia clínica |
| C4 — HCP can review independently | ❌ | Recomendaciones requieren re-cómputo del algoritmo |

**ProstaMed = device software function** → ruta **510(k)** Class II con predicado.

---

## Implicaciones operativas

1. **Sí aplica QMS** — ISO 13485 + 21 CFR Part 820 (QMSR efectivo Feb 2026).
2. **Sí aplica IEC 62304** — Software Class B mínimo (asignación formal en `iec62304_class.md`).
3. **Sí aplica ISO 14971** — Risk management con FMEA tabular.
4. **Sí aplica IMDRF SaMD N41** — Validación clínica 3 capas (científica/analítica/clínica).
5. **Sí aplica FDA Premarket Cybersecurity Guidance Sept 2023**.
6. **Sí aplica HIPAA** (data PHI) + LFPDPPP en México.

---

**Versión**: 1.0 · 2026-04-27 (Faubot LXXXVIII bootstrap)
**Aprobado por**: pendiente firma regulatorio.
**Próxima revisión**: tras pre-submission Q-sub FDA.
