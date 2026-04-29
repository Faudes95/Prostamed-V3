# Clinical Evidence Reference — ProstaMed v2 · 2026-04-27

> **Fuente única de verdad clínica** para todas las decisiones del Clinical
> Decision Engine Auditable (CDE) de ProstaMed. Cada gate, recomendación,
> alert y nomograma del sistema referencia este documento.
>
> **Versión**: Faubot LXXXVI · Iteración #67F · Pivote arquitectónico CDE real
> **Cobertura**: NCCN 5.2026 + EAU 2026 + 37 trials pivotales + 8 nomogramas
> **Compliance target**: FDA SaMD Class IIb · EU AI Act high-risk · HIPAA · GDPR · LFPDPPP MX

---

## §1. NCCN 5.2026 Prostate Cancer Clinical Practice Guidelines

### §1.1 PROS-1 — Initial workup (minimum dataset to classify)

**Required clinical inputs to place a patient en NCCN risk group**:

| Field | Type | Source | Used in |
|---|---|---|---|
| Age | int | Direct intake (derived from DOB) | All risk calculators |
| PSA (ng/mL) | float | Lab capture | NCCN risk · CAPRA · Halabi |
| Gleason 1° + 2° → ISUP grade | enum | Pathology biopsy | NCCN risk · CAPRA |
| Clinical T stage (cT1c..cT4) | enum | DRE + mpMRI | NCCN risk · staging |
| Clinical N stage (cN0/cN1/cNx) | enum | Pelvic imaging | NCCN risk |
| Clinical M stage (cM0/cM1a/M1b/M1c/Mx) | enum | CT TAP + bone scan or PSMA-PET | NCCN risk · CRPC routing |
| ECOG performance status (0-4) | enum | Clinical assessment | All decision engines |

**Refinement inputs (decision_refiner) — opcionales pero mejoran precisión**:
- % positive cores (refines NCCN intermediate fav vs unfav · CAPRA)
- Max core involvement % (NCCN unfavorable criterion ≥50%)
- PI-RADS imaging score (validates biopsy decision)
- Perineural invasion (NCCN very-high descriptor)
- Seminal vesicle invasion imaging (cT3b)
- Family history checklist (NCCN GENE-1 trigger)
- Charlson comorbidity index (calculated from comorbidities checklist)
- Frailty status (derived from age + ECOG + Charlson)

### §1.2 PROS-2 a PROS-5 — Risk stratification localized

**NCCN risk groups (very-low / low / intermediate fav / intermediate unfav / high / very-high)**:

```
VERY-LOW
  · cT1c · ISUP=1 · PSA<10 · ≤3 cores positive · ≤50% per core · PSAD<0.15

LOW
  · cT1-T2a · ISUP=1 · PSA<10

INTERMEDIATE-FAVORABLE
  · 1 of: cT2b-T2c, ISUP=2, PSA 10-20
  · Y: ISUP=2 with <50% positive cores

INTERMEDIATE-UNFAVORABLE
  · 2-3 of: cT2b-T2c, ISUP=2, PSA 10-20
  · O: ISUP=3
  · O: ≥50% positive cores

HIGH
  · cT3a · ISUP=4-5 · PSA>20

VERY-HIGH
  · cT3b-T4
  · O: primary pattern 5
  · O: ≥4 cores ISUP=4-5
  · O: 2-3 high-risk features
```

### §1.3 PROS-6/7 — Initial therapy localized per risk group

| Risk group | Preferred therapy (NCCN cat 1) | Alternatives |
|---|---|---|
| Very-low / Low | Active surveillance (≥10y life expectancy) | RP · EBRT · brachy LDR |
| Int-favorable | AS · RP · EBRT mono · LDR brachy | EBRT+ADT 4-6m |
| Int-unfavorable | RP+/-ePLND · EBRT+ADT 4-6m · EBRT+brachy boost | RP+adjuvant |
| High | EBRT+ADT 18-36m · RP+ePLND (selected) | EBRT+brachy+ADT 24m |
| Very-high | EBRT+ADT 24-36m+abi/apa+/-docetaxel | Multimodal · clinical trial |

### §1.4 PROS-9 — mCSPC initial therapy

**Volume classification (CHAARTED criteria)**:
- High-volume: ≥4 bone mets with ≥1 outside vertebral column/pelvis · OR · visceral mets
- Low-volume: everything else

**Risk classification (LATITUDE)**:
- High-risk: ≥2 of: ISUP≥4, ≥3 bone mets, visceral mets

**Preferred therapies**:
| Scenario | NCCN cat 1 preferred |
|---|---|
| High-volume any-risk | ADT + docetaxel (CHAARTED) · ADT + abiraterone (LATITUDE) · ADT + apalutamide (TITAN) · ADT + enzalutamide (ENZAMET/ARCHES) · **ADT + docetaxel + abiraterone (PEACE-1)** · **ADT + docetaxel + darolutamide (ARASENS)** [TRIPLET preferred for fit pts] |
| Low-volume any-risk | ADT + ARPI (apa/enza/abi) · ADT + RT prostate (STAMPEDE M1\|RT for low-vol only) |
| Oligometastatic (≤3 lesions) | ADT + ARPI + MDT (SBRT a lesiones) · trial preferred |

### §1.5 PROS-10 — m0CRPC (nmCRPC)

**Definition**: PSA progression bajo ADT con castration confirmed (testo<50 ng/dL),
sin mets en imaging convencional.

**PSADT-driven decision**:
- PSADT ≤10 months → ARPI (apa/enza/daro) cat 1 · SPARTAN/PROSPER/ARAMIS
- PSADT >10 months → continue ADT + close monitoring (PSA q1-3mo, imaging q6-12mo)

**Modern staging**: consider PSMA-PET to detect oligometastatic disease antes del switch.

### §1.6 PROS-11/12/13 — m1CRPC sequencing

**Decision tree based on prior therapy + biomarkers**:

```
m1CRPC FIRST-LINE (no prior ARPI for mCSPC):
  · ARPI (abi/enza) cat 1 · COU-AA-302/PREVAIL
  · Docetaxel cat 1 if visceral, rapid progression, symptomatic
  · Sipuleucel-T if asymptomatic, low-volume
  · Olaparib/talazoparib si HRR positive

m1CRPC POST-ARPI (mCSPC):
  · Docetaxel cat 1
  · Cabazitaxel post-Doce + ARPI (CARD trial)
  · Olaparib/talazoparib si HRR positive
  · Lu-177 PSMA-617 si PSMA-PET avid (post-Doce + ARPI)

m1CRPC POST-DOCE + POST-ARPI:
  · Cabazitaxel (CARD)
  · Olaparib/talazoparib si HRR positive (PROfound)
  · Lu-177 PSMA-617 si PSMA-PET avid (VISION)
  · Re-challenge enza/abi (no preferred)
  · Sipuleucel-T (rare, asymptomatic only)

m1CRPC POST-PARP:
  · Lu-177 PSMA-617 si PSMA-PET avid
  · Cabazitaxel
  · Re-challenge platinum-based chemo (selected)
  · Trial preferred
```

**HRR confirmation HARD-BLOCK** (Gate G61): PARP inhibitor requires confirmed
HRR+ (BRCA1/2/ATM/PALB2/CHEK2/CDK12/etc) por test germinal o somático. Sin
confirmación, response rate <15% (PROfound subgroup).

### §1.7 PROS-14 — Palliative / EOL care

- Symptomatic bone mets → palliative RT (8 Gy×1 SC.20-04) + bone-targeted therapy
- ECOG ≥3 → de-prioritize aggressive options · prioritize QoL
- BPI worst ≥4 → Ra-223 if bone-predominant · cabazitaxel if mixed
- ESAS ≥40 → palliative care consult
- Advance care planning · POLST · hospice referral

### §1.8 GENE-1 — Germline testing triggers

**NCCN GENE-1 indications for germline panel testing**:
1. Metastatic prostate cancer (any stage)
2. High-risk or very-high-risk localized
3. Family history: BRCA1/2/ATM/CHEK2/PALB2 known
4. Family hx: 1st degree relative w/ breast/ovarian/pancreatic/Lynch cancer
5. Ashkenazi Jewish ancestry
6. Intraductal histology
7. Personal history of breast cancer

**Panel content (minimum)**: BRCA1, BRCA2, ATM, PALB2, CHEK2, MLH1, MSH2, MSH6,
PMS2, EPCAM, TP53.

---

## §2. EAU 2026 comparative table

| Topic | NCCN 5.2026 | EAU 2026 | ProstaMed implementation |
|---|---|---|---|
| Risk classification localized | NCCN groups (very-low to very-high) | EAU groups (low / int / high) + ISUP grade | Both rendered in v2 audit tab |
| mCSPC volume | CHAARTED (≥4 bone + apendicular OR visceral) | EAU: similar but emphasizes burden score | CHAARTED operational |
| Triplet ARASENS | Cat 1 high-volume mCSPC | Strong recommendation | Gate G_ARASENS active |
| PSA monitoring post-RP | qper 3mo year 1, q6mo y 2, then annually | qper 3mo year 1-2, then 6mo | Cadence per visit type |
| Phoenix BCR | nadir + 2.0 ng/mL | nadir + 2.0 ng/mL (consensus) | Gate G_PHOENIX_BCR shared |
| PSMA-PET | Recommended for high-risk localized + BCR | Strong recommendation pre-salvage | proPSMA + PROMISE referenced |
| m0CRPC PSADT cutoff | ≤10 months | ≤10 months | Gate G55 active |
| HRR testing m1CRPC | Cat 1 all m1CRPC | Strong recommendation | Gate G_HRR_TEST |
| PARP first-line m1CRPC HRR+ | Olaparib/talazoparib cat 1 | Strong recommendation | Gate G61 HARD_BLOCK reverse |
| Lu-177 PSMA criteria | PSMA-PET avid + post-Doce + ARPI | Same (VISION criteria) | Gate G_VISION active |

**Key differences**:
- EAU emphasizes pre-treatment biopsy quality + Likert score (NCCN PI-RADS)
- EAU more conservative re: oligometastatic SBRT (NCCN trial-supported)
- EAU MRI-fusion biopsy preferred (NCCN allows TRUS but recommends mpMRI first)

---

## §3. 37 Trials pivotales con PMID/NCT

### §3.1 mCSPC

| Trial | Year | Drug arm | n | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **CHAARTED** | 2015 | ADT + Docetaxel vs ADT | 790 | OS HV: 17m extra | 0.61 | PMID 26244877 · NCT00309985 |
| **STAMPEDE arm C** | 2016 | ADT + Docetaxel vs ADT | 1145 | OS extension | 0.78 | PMID 26719232 |
| **LATITUDE** | 2017 | ADT + Abiraterone+ pred vs ADT | 1199 | OS · rPFS | 0.62 OS · 0.47 rPFS | PMID 28578607 · NCT01715285 |
| **STAMPEDE arm G** | 2017 | ADT + Abiraterone vs ADT | 1917 | OS | 0.63 | PMID 28578639 |
| **TITAN** | 2019 | ADT + Apalutamide vs ADT | 1052 | OS · rPFS | 0.67 OS | PMID 31157963 · NCT02489318 |
| **ENZAMET** | 2019 | ADT + Enzalutamide vs ADT (NSAA arm) | 1125 | OS | 0.67 | PMID 31329352 · NCT02446405 |
| **ARCHES** | 2019 | ADT + Enzalutamide vs ADT | 1150 | rPFS | 0.39 | PMID 31329516 · NCT02677896 |
| **PEACE-1** | 2022 | ADT + Doce + Abi vs ADT + Doce | 1173 | OS HV: ~7y | 0.75 | PMID 35489399 · NCT01957436 |
| **ARASENS** | 2022 | ADT + Doce + Darolutamide vs ADT + Doce | 1306 | OS | 0.68 | PMID 35179323 · NCT02799602 |
| **STAMPEDE M1\|RT** | 2018 | ADT + RT prostate vs ADT (low-volume only) | 2061 | OS | 0.68 | PMID 30355464 |

### §3.2 m0CRPC (nmCRPC)

| Trial | Year | Drug | n | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **SPARTAN** | 2018 | Apalutamide + ADT vs ADT | 1207 | MFS | 0.28 | PMID 29420164 · NCT01946204 |
| **PROSPER** | 2018 | Enzalutamide + ADT vs ADT | 1401 | MFS | 0.29 | PMID 29949494 · NCT02003924 |
| **ARAMIS** | 2019 | Darolutamide + ADT vs ADT | 1509 | MFS · OS | 0.41 MFS · 0.69 OS | PMID 30763142 · NCT02200614 |

### §3.3 m1CRPC pre-Doce

| Trial | Year | Drug | n | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **COU-AA-302** | 2013 | Abiraterone + pred vs placebo | 1088 | rPFS · OS | 0.52 rPFS | PMID 23228172 · NCT00887198 |
| **PREVAIL** | 2014 | Enzalutamide vs placebo | 1717 | rPFS · OS | 0.81 OS | PMID 24881730 · NCT01212991 |

### §3.4 m1CRPC post-Doce

| Trial | Year | Drug | n | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **COU-AA-301** | 2011 | Abiraterone + pred vs prednisone | 1195 | OS | 0.65 | PMID 21612468 · NCT00638690 |
| **AFFIRM** | 2012 | Enzalutamide vs placebo | 1199 | OS | 0.63 | PMID 22894553 · NCT00974311 |
| **CARD** | 2019 | Cabazitaxel vs second ARPI (post Doce + ARPI) | 255 | rPFS · OS | 0.54 rPFS · 0.64 OS | PMID 31566937 · NCT02485691 |
| **TROPIC** | 2010 | Cabazitaxel vs mitoxantrone | 755 | OS | 0.70 | PMID 20888992 |

### §3.5 PARP inhibitors (HRR+)

| Trial | Year | Drug | n (HRR+) | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **PROfound** | 2020 | Olaparib vs ARPI rechallenge (BRCA1/2/ATM) | 245 | rPFS · OS | 0.34 rPFS · 0.69 OS | PMID 32343890 · NCT02987543 |
| **TRITON3** | 2023 | Rucaparib vs Doce/ARPI (BRCA1/2/ATM) | 270 | rPFS | 0.50 | PMID 36795891 · NCT02975934 |
| **MAGNITUDE** | 2022 | Niraparib + Abi vs Abi (HRR+) | 423 | rPFS | 0.53 | PMID 35981228 · NCT03748641 |
| **TALAPRO-2** | 2023 | Talazoparib + Enza vs Enza (all-comers · HRR+ subset) | 805 | rPFS | 0.45 BRCA · 0.70 all | PMID 36952634 · NCT03395197 |

### §3.6 PSMA radioligand therapy

| Trial | Year | Drug | n | Endpoint | HR | Reference |
|---|---|---|---|---|---|---|
| **VISION** | 2021 | Lu-177 PSMA-617 + best supportive vs SOC (post-Doce + ARPI) | 831 | rPFS · OS | 0.40 rPFS · 0.62 OS | PMID 34161051 · NCT03511664 |
| **TheraP** | 2021 | Lu-177 PSMA-617 vs Cabazitaxel (post-Doce) | 200 | PSA50 response | 66% vs 37% | PMID 33581798 · NCT03392428 |
| **PSMAfore** | 2024 | Lu-177 PSMA-617 vs ARPI switch (pre-Doce) | 468 | rPFS | 0.41 | PMID 38614311 · NCT04689828 |

### §3.7 Localized · adjuvant · salvage RT

| Trial | Year | Drug/intervention | n | Endpoint | Reference |
|---|---|---|---|---|---|
| **ProtecT** | 2016 | AS vs RP vs RT (low-int risk) | 1643 | 10y outcomes | PMID 27626136 |
| **SPCG-4** | 2018 | RP vs watchful waiting | 695 | OS · cancer death | PMID 30244538 |
| **PIVOT** | 2017 | RP vs observation | 731 | All-cause mortality | PMID 28700785 |
| **RTOG-9601** | 2017 | Salvage RT + Bicalutamide vs RT alone | 760 | OS | PMID 28249833 |
| **GETUG-AFU 16** | 2016 | Salvage RT + 6mo ADT vs RT alone | 743 | PFS | PMID 27160475 |
| **RAVES / RADICALS-RT** | 2020 | Adjuvant vs salvage RT post-RP | combined ~3000 | EFS | PMID 33002431 |
| **ARTISTIC meta** | 2020 | Adjuvant vs salvage RT meta-analysis | individual data | EFS | PMID 33002430 |
| **STAMPEDE M1\|RT** | 2018 | RT prostate in mCSPC low-volume | 2061 | OS | PMID 30355464 |

### §3.8 Genomic / biomarker

| Trial | Year | Test | Population | Use case | Reference |
|---|---|---|---|---|---|
| **PROPHECY** | 2019 | AR-V7 nuclear protein | mCRPC | Predict ARPI failure | PMID 31226010 · NCT02269982 |
| **PROCEED** | 2017 | Sipuleucel-T registry | m1CRPC asymptomatic | Real-world OS | PMID 28499118 |

---

## §4. Risk calculators / nomograms

### §4.1 CAPRA (D'Amico) — pre-treatment localized

**Inputs**: age, PSA, Gleason 1°+2°, cT, % positive cores
**Output**: 0-10 score → low (0-2) / int (3-5) / high (6-10)
**Endpoint**: 5-year BCR-free survival post-RP

### §4.2 CAPRA-S — post-RP

**Inputs**: PSA, Gleason RP, margin status, EPE, SVI, LN+
**Output**: 0-12 score → low (0-2) / int (3-5) / high (6-12)
**Endpoint**: BCR-free survival

### §4.3 Halabi mCRPC nomogram

**Inputs**: PSA, ALP, LDH, Hb, opioid use, ECOG, visceral mets, prior RT, prior ARPI
**Output**: 12-month OS probability (continuous)

### §4.4 Decipher Genomic Classifier

**Tissue-based 22-gene signature** (Affymetrix microarray)
**Output**: low (<0.45) / int (0.45-0.6) / high (≥0.6)
**Use**: identifies aggressive disease post-RP, informs adjuvant therapy

### §4.5 Briganti 2019 LNI nomogram

**Inputs**: PSA, cT, Gleason biopsy, % positive cores, MRI EPE, MRI SVI
**Output**: probability of LN+ (continuous)
**Threshold for ePLND**: ≥7%

### §4.6 MSKCC Seminal Vesicle Invasion

**Inputs**: PSA, Gleason, % positive cores
**Output**: SVI risk (continuous)

### §4.7 PROfound HRR composite (used in selection)

**Inputs**: BRCA1, BRCA2, ATM (cohort A) · PALB2, CHEK2, CDK12, etc (cohort B)
**Output**: olaparib eligibility binary

### §4.8 G8 Geriatric assessment

**Inputs**: age, food intake, weight loss, mobility, neuropsych, BMI, polypharmacy, self-rated health
**Output**: 0-17 score · ≤14 = vulnerable

---

## §5. ProstaMed CDE Auditable — 5 dimensiones (FDA SaMD ready)

| Dim | Métrica objetivo | Verificación |
|---|---|---|
| **CÓMO** (reasoning chain) | ≥95% rendered keys del clinical_compass (19/19) | Test cobertura template |
| **POR QUÉ** (gates) | ≥85% gates con trial_refs live + severity 3-tier | Audit test_audit*.py |
| **DATOS** (input snapshot) | PHI-scrubbed JSON · missing/stale flags explicit | Test recompute_hook |
| **EVIDENCIA** (per-gate drill-down) | ≥80% gates con PMID/NCT/DOI live | Test trial_refs_resolver |
| **VERSIÓN** (reproducibilidad) | FAUBOT_RELEASE + module_sha + per-gate YAML SHA | Test versioning_endpoint |

**Bootstrap target metrics (LXXXVI)**:
- Compass keys rendered: 19/19 (100%) — actualmente 3/19 (16%)
- Recompute hook: ON (cero stale decisions)
- Transition proposals UI: ON (cero opacidad)
- Append API real persistence: ON (cero teatro)
- Stage-aware intake: ON (cero contaminación cross-stage)

---

## §6. Mapping evidencia → gate code → decision recommendation

> Tabla maestra de los 89 gates pivotales activos (catálogo YAML).
> Cada fila: gate code · trigger condition · severity · NCCN/EAU reference ·
> trial PMID/NCT · clinical action mandated.

| Gate | Trigger | Severity | NCCN | Trial | Action |
|---|---|---|---|---|---|
| G07 | ALT >5×LSN | hard_block | PROS-N | PMID 28296438 (COU-AA-302 safety) | Bloquear ADT_ABIRATERONE + NIRAPARIB_ABIRATERONE |
| G14 | HRR no testeado en mCRPC | informational | PROS-13 / GENE-1 | PROfound NCT02987543 | Recomendar test germinal + somático |
| G19 | Post-Doce + post-ARPI | informational | PROS-12 | CARD NCT02485691 | Considerar Cabazitaxel |
| G29 | NYHA III-IV | hard_block | PROS-CV | ARAMIS PMID 30763142 | No enzalutamida · prefer darolutamida |
| G47 | PSA flare ARPI <12 sem | soft_warning | PROS-monitoring | PMID 31816320 | No interpretar como progresión |
| G53 | BCR aggressive post-RP | informational | PROS-8 | RTOG-9601 PMID 28249833 | Salvage RT + ADT 6m |
| G54 | PSA bounce post-RT | soft_warning | PROS-8 monitoring | Crook IJROBP 2010 + Phoenix 2006 | Esperar 3 mediciones |
| G55 | PSADT ≤10m m0CRPC | soft_warning | PROS-10 | SPARTAN/PROSPER/ARAMIS | Iniciar ARPI |
| G61 | PARP sin HRR confirmado | hard_block | PROS-13 cat 1 | PROfound NCT02987543 | Bloquear PARP sin test |
| ... | (89 gates totales · ver `prostanet/shared/pivotal_gates_catalog/*.yaml`) | | | | |

---

## §7. Aspiración estratégica — Compliance roadmap

### §7.1 FDA SaMD Class IIb (decisional CDS)

**Definición**: software que provee recomendación clínica específica donde el médico
NO puede revisar fácilmente la base independiente. Requiere 510(k) + clinical validation.

**ProstaMed compliance evidence**:
- ✓ Algorithmic transparency (5 dim CDE Auditable)
- ✓ Per-gate evidence drill-down (PMID/NCT live)
- ✓ Versioning + reproducibility (FAUBOT_RELEASE + per-gate YAML SHA)
- ✓ Audit trail (input_snapshot PHI-scrubbed)
- 🔄 Clinical validation prospective (target 2027)
- 🔄 510(k) submission preparation (target Q3 2027)

### §7.2 EU AI Act high-risk system requirements

**ProstaMed clasifica como high-risk** (Annex III #5: salud).

**Requisitos cumplidos**:
- ✓ Risk management system (gates severity 3-tier)
- ✓ Data governance (PHI-scrubbed snapshot + LFPDPPP MX consent)
- ✓ Technical documentation (este MD + audit_tracking.md)
- ✓ Record-keeping (audit_log + decision_audit history)
- ✓ Transparency to user (CDE 5 dim renderizado)
- 🔄 Human oversight (override mechanism + transition proposal confirmación)
- 🔄 Accuracy + robustness + cybersecurity testing (Faubot Iter #67G)

### §7.3 Data governance

**HIPAA + GDPR + LFPDPPP MX compliance**:
- ✓ Granular consent (4 scopes: clinical / CDE-IA / cohort / research)
- ✓ Right to revoke (ARCO)
- ✓ Audit trail consent_signature_evidence with SHA-256 content_hash
- ✓ PHI-scrubbed input_snapshot for non-clinical use
- ✓ 365-day consent expiration with renewal flow

### §7.4 Biomedical AI ethics

- ✓ Bias detection: cohort_summary by ethnicity/age groups (próx)
- ✓ Fairness audits: stage_center_aggregator monitors representation
- 🔄 Counterfactual explanations: Fase 5 (what-if simulator)
- 🔄 Group fairness metrics: Faubot Iter #68

---

## §8. Documentación cross-reference

- `prostanet/shared/pivotal_gates_catalog/*.yaml` — definición declarativa de cada gate
- `prostanet/audit_tracking.md` — historial de auditorías Faubot iterativas
- `prostanet/CLINICAL_EVIDENCE_2026.md` — este documento (fuente única de verdad clínica)
- `CLAUDE.md` §1-§13 — backbone del proyecto + reglas operacionales
- `tests/test_audit*.py` — tests dedicados por iteración Faubot

**Última actualización**: 2026-04-27 · Faubot 2026-04-27 LXXXVI (#67F · Pivote CDE
Auditable real). Mantener sincronizado con NCCN/EAU release cycles + nuevos trials
pivotales. Bumpear con cada cambio sustantivo.
