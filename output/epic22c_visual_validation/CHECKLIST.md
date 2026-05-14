# EPIC 22c · Visual Validation Checklist

_Generated: 2026-05-13T21:29:49_

**Summary**: 22 pass · 0 review · 0 miss · 22 total

Open each HTML file in browser and verify clinical correctness:

| # | Status | Exemplar | Expected | Classified | Conf | Review Focus |
|---|--------|----------|----------|------------|------|---------------|
| 1 | ✅ PASS | `exemplar_01_suspected_low_psa.html` | `suspected_low_psa_no_biopsy` | `suspected_low_psa_no_biopsy` | 0.78 | ¿Sistema recomienda observación + lifestyle, NO biopsia inmediata? |
| 2 | ✅ PASS | `exemplar_02_elevated_psa_ww.html` | `suspected_elevated_psa_watchful_wait` | `suspected_elevated_psa_watchful_wait` | 0.85 | ¿Sistema NO recomienda biopsia diagnóstica? ¿Palliative ADT solo si síntomas? |
| 3 | ✅ PASS | `exemplar_03_neg_biopsy_age_lt_45.html` | `negative_biopsy_age_lt_45` | `negative_biopsy_age_lt_45` | 0.82 | ¿Sistema recomienda germline testing universal? ¿Re-biopsy con MRI fusion? |
| 4 | ✅ PASS | `exemplar_04_post_brachy_ldr.html` | `post_brachy_ldr` | `post_brachy_ldr` | 0.88 | ¿Sistema reconoce PSA bounce ventana? ¿NO alarma Phoenix en 18mo? |
| 5 | ✅ PASS | `exemplar_05_post_ebrt_alone.html` | `post_ebrt_alone` | `post_ebrt_alone` | 0.85 | ¿Sistema cita Phoenix criteria explícitamente? ¿Rectal toxicity tracked? |
| 6 | ✅ PASS | `exemplar_06_post_sbrt.html` | `post_sbrt` | `post_sbrt` | 0.86 | ¿Sistema reconoce que SBRT tiene nadir más rápido? Trials HYPO-RT-PC / PACE-B citados? |
| 7 | ✅ PASS | `exemplar_07_post_focal_therapy.html` | `post_focal_therapy` | `post_focal_therapy` | 0.82 | ¿Sistema distingue in-field vs out-of-field? ¿Biopsy at 12mo routine recomendada? |
| 8 | ✅ PASS | `exemplar_08_brca2_carrier.html` | `brca2_carrier` | `brca2_carrier` | 0.95 | ¿Sistema cita PROfound / PROpel? ¿Counseling familiar mentioned? |
| 9 | ✅ PASS | `exemplar_09_brca1_carrier.html` | `brca1_carrier` | `brca1_carrier` | 0.95 | ¿Sistema reconoce BRCA1 ≠ BRCA2 pero similar pathway? |
| 10 | ✅ PASS | `exemplar_10_atm_carrier.html` | `atm_carrier` | `atm_carrier` | 0.90 | ¿Sistema reconoce ATM response variable a PARP vs BRCA2? |
| 11 | ✅ PASS | `exemplar_11_lynch_carrier.html` | `lynch_carrier` | `lynch_carrier` | 0.92 | ¿Sistema cita KEYNOTE-158? ¿Colorectal + endometrial surveillance? |
| 12 | ✅ PASS | `exemplar_12_hoxb13_carrier.html` | `hoxb13_carrier` | `hoxb13_carrier` | 0.88 | ¿Sistema sugiere surveillance intensificado desde 40y? |
| 13 | ✅ PASS | `exemplar_13_oligo_synchronous.html` | `oligometastatic_synchronous` | `oligometastatic_synchronous` | 0.86 | ¿Sistema cita STOMP/ORIOLE/STAMPEDE-G? ¿MDT mencionado? |
| 14 | ✅ PASS | `exemplar_14_oligo_metach_adt_naive.html` | `oligometastatic_metachronous_adt_naive` | `oligometastatic_metachronous_adt_naive` | 0.83 | ¿Sistema prefiere MDT sobre escalation ARSI? ¿Short-term ADT mencionado? |
| 15 | ✅ PASS | `exemplar_15_oligo_recurrent_post_def.html` | `oligo_recurrent_post_definitive` | `oligo_recurrent_post_definitive` | 0.85 | ¿Sistema reconoce post-definitive context? ¿Salvage local mencionado si fossa? |
| 16 | ✅ PASS | `exemplar_16_geriatric_frail.html` | `geriatric_frail_limited` | `geriatric_frail_limited` | 0.92 | ¿Sistema NO recomienda chemo intensification? ¿Single-agent ARSI con dose mods? |
| 17 | ✅ PASS | `exemplar_17_young_onset.html` | `young_onset_pca` | `young_onset_pca` | 0.90 | ¿Sistema sugiere fertility preservation ANTES de tratamiento? ¿Germline mandatorio? |
| 18 | ✅ PASS | `exemplar_18_comorbidity_cv.html` | `comorbidity_limited_severe_cv` | `comorbidity_limited_severe_cv` | 0.85 | ¿Sistema EXCLUYE abiraterone+prednisone? ¿Cardiology referral mencionada? |
| 19 | ✅ PASS | `exemplar_19_comorbidity_hepatic.html` | `comorbidity_limited_severe_hepatic` | `comorbidity_limited_severe_hepatic` | 0.85 | ¿Sistema EXCLUYE abiraterone (contraindicado en active liver)? |
| 20 | ✅ PASS | `exemplar_20_survivorship_5y.html` | `survivorship_post_curative_5y_plus` | `survivorship_post_curative_5y_plus` | 0.85 | ¿Sistema sugiere shared care con primary care? ¿Annual PSA only? |
| 21 | ✅ PASS | `exemplar_21_second_primary.html` | `second_primary_surveillance` | `second_primary_surveillance` | 0.82 | ¿Sistema cita post-RT secondary malignancy risk? ¿CBC + colonoscopy mencionados? |
| 22 | ✅ PASS | `exemplar_22_adt_long_term.html` | `adt_long_term_complications` | `adt_long_term_complications` | 0.88 | ¿Sistema sugiere DXA anual? ¿Lipid panel q6mo? ¿Cognitive screening? |

## Reviewer instructions

- ✅ **PASS**: classifier produced the expected state. Verify therapeutic alternative + rationale match NCCN 2026.
- ⚠️ **REVIEW**: classifier produced a different state. Check whether the alternative state is clinically defensible.
- ❌ **MISS**: classifier returned no rule match. Add discriminators or relax rule thresholds.
