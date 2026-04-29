# IMDRF Risk Classification — ProstaMed/ProstaNet

> **Fuente regulatoria**: IMDRF/SaMD WG/N12FINAL:2014 — *Software as a Medical
> Device (SaMD): Possible Framework for Risk Categorization and Corresponding
> Considerations*. Versión actualizada IMDRF/SaMD WG/N41 FINAL:2017 (Clinical Evaluation).

---

## 1. Determinación SaMD

**ProstaMed** es **Software as a Medical Device (SaMD)** bajo la definición
IMDRF (§3.1):

> "Software intended to be used for one or more medical purposes that perform
> these purposes without being part of a hardware medical device."

**Justificación**:
- Calculadoras de riesgo (NCCN, CAPRA, D'Amico, MSKCC, Halabi, Decipher).
- Interpretación longitudinal de PSA con alertas (47 gates anti-misinterpretation).
- Recomendaciones de tratamiento basadas en estadio + biomarkers (89 gates pivotales).
- Recomendaciones de biopsia, vigilancia activa, y elegibilidad a 47 trials.
- NO es parte de un dispositivo de hardware (puro software web).

## 2. Categorización IMDRF (I-IV)

Eje | Valor ProstaMed | Justificación
----|-----------------|---------------
**State of healthcare situation** | **Serious** (alto) | Cáncer de próstata es enfermedad seria con riesgo de progresión y mortalidad sin manejo apropiado.
**Significance of information provided by SaMD** | **Treat or diagnose** (alto) | El sistema da recomendaciones específicas de tratamiento (ARPI doublet, taxano, PARP inhibitor, observación), no solo informa.

→ **Categoría IMDRF: III** (intersección Serious × Treat-or-diagnose).

| Categoría | Descripción | ProstaMed |
|---|---|---|
| I | Inform clinical management of non-serious | ✗ |
| II | Drive clinical management of non-serious / Inform serious | ✗ |
| **III** | **Drive clinical management of serious situation** | ✅ |
| IV | Diagnose/treat critical condition / Drive treatment of critical | (escala más alta) |

## 3. CDS (Clinical Decision Support) Final Guidance FDA Sept 2022

ProstaMed **NO califica para excepción CDS** (no-device classification). Ver
`cds_criteria.yaml` para análisis detallado de los 4 criterios.

**Criterio crítico**: el clínico **NO puede reproducir mentalmente** desde los
datos crudos las recomendaciones específicas del sistema (e.g., elegibilidad a
PROfound olaparib requiere análisis de 8 genes HRR + status germinal vs somatic +
exposición previa a ARPI + ECOG fitness — esto excede capacidad mental
razonable). Por tanto, ProstaMed es **device software function** y debe seguir
ruta 510(k) con predicado.

## 4. Mapeo a clasificación FDA

- **IMDRF Categoría III** → en EE.UU. típicamente mapea a **Class II FDA**.
- **Ruta de submission**: **510(k)** con predicado (no PMA, no De Novo).
- **Predicados candidatos** (a confirmar via FDA pre-submission):
  - K191354 — *Watson for Oncology* (IBM)
  - DEN180044 — *IDx-DR* (autonomous AI for diabetic retinopathy, sets autonomous-CDS precedent)
  - K231215 — *Lucid Diagnostics EsoGuard* (cancer-related decision support)

## 5. Clasificación de seguridad IEC 62304

Ver `iec62304_class.md`. Asignación: **Class B** (lesión no seria posible si el
software falla — el clínico revisa toda recomendación antes de actuar).
Componentes específicos del motor PARP inhibitor / quimio podrían escalar a
**Class C** durante refinamiento de FMEA (Pilar 4).

## 6. Próximos pasos regulatorios

1. **Pre-submission Q-sub** (FDA): solicitar feedback sobre clasificación + predicado.
2. **Validación clínica IMDRF SaMD N41**: 3 capas (validez científica, performance
   analítico, performance clínico). Ver `prostanet/regulatory/clinical/`.
3. **510(k) submission**: tras cohorte prospectiva validation N=500 firmada.

---

**Versión**: 1.0 · 2026-04-27 (Faubot LXXXVIII bootstrap)
**Aprobado por**: pendiente de firma regulatorio + clínico.
**Próxima revisión**: tras Q-sub feedback FDA.
