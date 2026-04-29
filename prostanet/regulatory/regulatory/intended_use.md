# Intended Use Statement — ProstaMed/ProstaNet

> **Documento regulatorio FDA 21 CFR §807.92** — Statement de uso pretendido
> para 510(k) submission Class II SaMD.

---

## Intended Use

ProstaMed/ProstaNet is a **Clinical Decision Engine Auditable Software as a
Medical Device (SaMD)** intended to assist board-certified urologists and
medical oncologists in the clinical management of adult male patients
(≥18 years) with **histologically confirmed or clinically suspected prostate
adenocarcinoma**, throughout the disease continuum:

- **Screening / pre-diagnostic** workup
- **Initial diagnosis** (localized, locally advanced, or metastatic)
- **Risk stratification** (NCCN very-low / low / intermediate-favorable /
  intermediate-unfavorable / high / very-high)
- **Initial treatment selection** (active surveillance, radical prostatectomy,
  external beam RT, brachytherapy, focal therapy, ADT-based combinations)
- **Recurrence and biochemical recurrence (BCR)** management
- **Castration-sensitive metastatic (mCSPC)** therapy selection
- **Castration-resistant** disease (m0CRPC, m1CRPC) sequencing
- **Survivorship and palliative** pathway

## Indications for Use

ProstaMed processes structured longitudinal patient data (PSA values, Gleason
scores, staging cT/cN/cM, biomarkers, treatment history, comorbidities,
performance status) and outputs:

1. **Stage classification** per NCCN 5.2026 + EAU 2026 guidelines.
2. **Risk stratification** using validated nomograms (CAPRA, D'Amico, MSKCC,
   Halabi, Decipher, Briganti 2019 LNI).
3. **Treatment recommendations** with mapped evidence to 47 pivotal trials
   (CHAARTED, LATITUDE, ENZAMET, ARCHES, TITAN, STAMPEDE, PEACE-1, ARASENS,
   SPARTAN, PROSPER, ARAMIS, COU-AA-302, PREVAIL, AFFIRM, COU-AA-301, CARD,
   PROfound, TRITON3, MAGNITUDE, TALAPRO-2, VISION, TheraP, PSMAfore,
   PROTECT, ProtecT, SPCG-4, etc.).
4. **89 pivotal contraindication gates** (HARD_BLOCK / SOFT_WARNING / INFORMATIONAL)
   for safety-critical decisions (e.g., G61 HRR confirmation pre-PARP).
5. **Trial eligibility evaluation** for 47 pivotal trials with confidence
   scoring.
6. **Longitudinal monitoring** with PSA kinetics, treatment response
   classification per line, and clinical event timeline.

## Limitations

- ProstaMed **does NOT replace clinical judgment**. All recommendations require
  physician review before action.
- Not validated for **pediatric** patients.
- Not validated for **non-prostate malignancies** with secondary prostate
  involvement.
- **Image analysis** (DICOM raw processing) is NOT performed by ProstaMed —
  imaging interpretations must be entered as structured findings by qualified
  radiologists.
- Recommendations are **NCCN/EAU/IMDRF-aligned** but do not substitute
  multidisciplinary tumor board review for complex cases.

## User Population

**Primary users**: licensed urologists, medical oncologists, radiation
oncologists, and trained urology nurse practitioners working in oncology
referral centers.

**Required training**: 2-hour onboarding covering:
- ProstaMed Reasoning Chain interpretation (19 keys of clinical_compass)
- Override mechanism for 89 gates (with audit log requirements)
- Decision audit drill-down navigation (5 dimensions: CÓMO/POR QUÉ/DATOS/EVIDENCIA/VERSIÓN)

## Patient Population

- Adult males ≥18 years
- Diagnosed or suspected prostate adenocarcinoma
- Any disease stage from screening through palliative
- Includes special populations:
  - Mexican / Latin American (primary cohort, calibration ongoing — Pilar 5)
  - International (NCCN/EAU evidence applicable)
  - Ethnically diverse (germline testing per NCCN PROS-H)

## Use Environment

- Hospital outpatient oncology clinics
- Multidisciplinary tumor board environments
- Telemedicine consults (with secure session — see `cybersecurity.md`)
- NOT for emergency department / ICU (decisions there require real-time
  hardware monitoring out of scope)

## Regulatory Classification

- **FDA**: Class II 510(k) device software function
- **IMDRF**: Category III SaMD (Drive clinical management of serious situation)
- **IEC 62304**: Class B (non-serious injury possible)
- **EU MDR**: Class IIa (likely; pending CE submission analysis)
- **COFEPRIS (México)**: Class II (pending submission)

## Effective Date

This Intended Use applies to FAUBOT_RELEASE 2026-04-27 LXXXVIII and successors,
unless explicitly modified by approved Change Request via SOP-CCG-002.

---

**Versión**: 1.0 · 2026-04-27 (Faubot LXXXVIII bootstrap)
**Aprobado por**: pendiente firma — regulatorio + médico director.
**Última revisión**: 2026-04-27.
**Próxima revisión**: tras FDA Q-sub feedback.
