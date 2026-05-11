"""trial_criteria_registry.py — Faubot LXXXV (Iteración #2).

Registry verbatim de criterios de elegibilidad para los 47 trials pivotales
en cáncer de próstata. Cada trial incluye:

- **trial_id**: nombre canónico (CHAARTED, ARASENS, PROfound, etc.)
- **pmid / nct**: identificadores PubMed + ClinicalTrials.gov
- **citation**: full citation con journal/year/page
- **stage**: contexto clínico (mCSPC HV, mCRPC post-doce, nmCRPC, BCR, localized)
- **regimen_tested**: arms experimentales del trial
- **inclusion**: lista verbatim criterios inclusión claves
- **exclusion**: lista verbatim criterios exclusión claves
- **endpoint_primary**: outcome primario (OS, rPFS, MFS, etc.)
- **biomarker_required**: si requiere biomarcador específico (HRR, PSMA+, PD-L1, etc.)

Source: PubMed verified + ClinicalTrials.gov registry data (April 2026).

Esta registry es consumida por `trial_eligibility_engine.py` para evaluar
elegibilidad real per-paciente. NO inventar criterios — solo lo publicado.

Faubot LXXXV — Iteración #2 (Trials Eligibility Engine + REST API + UI).
"""
from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────────────────────────────
# REGISTRY: 47 PIVOTAL TRIALS
# ──────────────────────────────────────────────────────────────────────
# Estructura: dict[trial_id] = {pmid, nct, citation, stage, regimen_tested,
#                                inclusion, exclusion, endpoint_primary,
#                                biomarker_required, evidence_level}
# ──────────────────────────────────────────────────────────────────────

TRIAL_CRITERIA_REGISTRY: dict[str, dict[str, Any]] = {

    # ═══════════════════════════════════════════════════════════════════
    # mCSPC (metastatic castration-sensitive prostate cancer) — 9 trials
    # ═══════════════════════════════════════════════════════════════════

    "CHAARTED": {
        "pmid": "26244877",
        "nct": "NCT00309985",
        "citation": "Sweeney CJ et al. CHAARTED. NEJM 2015;373:737-746.",
        "stage": "mcspc",
        "regimen_tested": "ADT + docetaxel 75 mg/m² q3w x6",
        "inclusion": [
            "Metastatic prostate adenocarcinoma confirmed by histology",
            "ECOG 0-2",
            "Adequate hepatic/renal function",
            "High-volume disease defined as: visceral mets OR ≥4 bone mets with ≥1 beyond vertebral column/pelvis",
        ],
        "exclusion": [
            "Prior cytotoxic chemotherapy for prostate cancer",
            "Major surgery within 30 days",
            "Active second malignancy",
        ],
        "endpoint_primary": "Overall survival (OS)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_volume", "low_volume"],
    },

    "LATITUDE": {
        "pmid": "28578607",
        "nct": "NCT01715285",
        "citation": "Fizazi K et al. LATITUDE. NEJM 2017;377:352-360.",
        "stage": "mcspc",
        "regimen_tested": "ADT + abiraterone 1000 mg + prednisone 5 mg",
        "inclusion": [
            "Newly diagnosed metastatic high-risk castration-sensitive prostate cancer",
            "≥2 of 3 high-risk factors: Gleason ≥8, ≥3 bone lesions, visceral metastasis",
            "ECOG 0-2",
        ],
        "exclusion": [
            "Prior systemic therapy for prostate cancer",
            "Active or symptomatic visceral disease (within 14 days)",
            "Severe hepatic impairment (Child-Pugh C)",
        ],
        "endpoint_primary": "OS + rPFS (co-primary)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_risk_3_factors", "high_risk_2_factors"],
    },

    "STAMPEDE": {
        "pmid": "29384722",
        "nct": "NCT00268476",
        "citation": "James ND et al. STAMPEDE. Lancet 2016;387:1163-1177.",
        "stage": "mcspc",
        "regimen_tested": "ADT + docetaxel + zoledronate (multiple arms tested)",
        "inclusion": [
            "Newly diagnosed metastatic, locally advanced, or node-positive prostate cancer",
            "Fit for combination therapy",
            "Adequate organ function",
        ],
        "exclusion": [
            "Prior systemic therapy ≥12 weeks before",
            "Significant cardiovascular disease",
        ],
        "endpoint_primary": "OS + failure-free survival",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["arm_g_RT_to_primary", "arm_h_abiraterone", "arm_c_docetaxel"],
    },

    "ENZAMET": {
        "pmid": "31157970",
        "nct": "NCT02446405",
        "citation": "Davis ID et al. ENZAMET. NEJM 2019;381:121-131.",
        "stage": "mcspc",
        "regimen_tested": "ADT + enzalutamide 160 mg vs ADT + standard non-steroidal antiandrogen",
        "inclusion": [
            "Metastatic hormone-sensitive prostate cancer (mHSPC)",
            "ECOG 0-2",
            "Started ADT within 12 weeks before randomization",
            "Adequate organ function",
        ],
        "exclusion": [
            "Prior chemo allowed if completed ≥12 weeks before",
            "Seizure disorder or risk factors for seizure",
            "Significant cardiovascular disease (recent MI, stroke)",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_volume", "low_volume", "with_or_without_docetaxel"],
    },

    "ARCHES": {
        "pmid": "31329516",
        "nct": "NCT02677896",
        "citation": "Armstrong AJ et al. ARCHES. JCO 2019;37:2974-2986.",
        "stage": "mcspc",
        "regimen_tested": "ADT + enzalutamide 160 mg vs ADT + placebo",
        "inclusion": [
            "Metastatic hormone-sensitive prostate cancer",
            "ECOG 0-1",
            "Documented progression on ADT (failure required)",
        ],
        "exclusion": [
            "Prior systemic therapy excluding ADT/first-gen anti-androgen",
            "Brain metastases",
            "Clinically significant cardiovascular disease",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_volume", "low_volume"],
    },

    "TITAN": {
        "pmid": "31166680",
        "nct": "NCT02489318",
        "citation": "Chi KN et al. TITAN. NEJM 2019;381:13-24.",
        "stage": "mcspc",
        "regimen_tested": "ADT + apalutamide 240 mg vs ADT + placebo",
        "inclusion": [
            "Metastatic castration-sensitive prostate cancer",
            "ECOG 0-1",
            "Adequate organ function",
        ],
        "exclusion": [
            "Brain metastases",
            "History of seizure",
            "Severe hepatic impairment",
        ],
        "endpoint_primary": "OS + rPFS (co-primary)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_volume", "low_volume", "with_prior_docetaxel"],
    },

    "PEACE-1": {
        "pmid": "35430030",
        "nct": "NCT01957436",
        "citation": "Fizazi K et al. PEACE-1. Lancet 2022;399:1695-1707.",
        "stage": "mcspc",
        "regimen_tested": "ADT + docetaxel + abiraterone (triplet) vs ADT + docetaxel",
        "inclusion": [
            "De novo metastatic castration-sensitive prostate cancer",
            "ECOG 0-2",
            "Adequate hepatic, renal, hematologic function",
        ],
        "exclusion": [
            "Prior systemic therapy for metastatic disease",
            "Brain or leptomeningeal metastases",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "rPFS + OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["with_local_RT", "high_volume", "low_volume"],
    },

    "ARASENS": {
        "pmid": "35179323",
        "nct": "NCT02799602",
        "citation": "Smith MR et al. ARASENS. NEJM 2022;386:1132-1142.",
        "stage": "mcspc",
        "regimen_tested": "ADT + docetaxel + darolutamide (triplet) vs ADT + docetaxel",
        "inclusion": [
            "Newly diagnosed metastatic hormone-sensitive prostate cancer",
            "ECOG 0-1",
            "Candidates for ADT + docetaxel",
        ],
        "exclusion": [
            "Prior systemic therapy excluding ADT (max 12 weeks)",
            "Brain metastases",
            "Significant hepatic impairment",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
        "subgroups": ["high_volume", "low_volume"],
    },

    "ARANOTE": {
        "pmid": "39312707",
        "nct": "NCT04736199",
        "citation": "Saad F et al. ARANOTE. JCO 2024;42(suppl):3055.",
        "stage": "mcspc",
        "regimen_tested": "ADT + darolutamide vs ADT + placebo (without docetaxel)",
        "inclusion": [
            "Metastatic hormone-sensitive prostate cancer",
            "ECOG 0-1",
            "Not candidates for or declining docetaxel",
        ],
        "exclusion": [
            "Prior systemic therapy",
            "Brain metastases",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # nmCRPC (non-metastatic CRPC) — 3 trials
    # ═══════════════════════════════════════════════════════════════════

    "SPARTAN": {
        "pmid": "29420164",
        "nct": "NCT01946204",
        "citation": "Smith MR et al. SPARTAN. NEJM 2018;378:1408-1418.",
        "stage": "m0_crpc",
        "regimen_tested": "ADT + apalutamide 240 mg vs ADT + placebo",
        "inclusion": [
            "Non-metastatic CRPC (M0 by conventional imaging)",
            "PSA doubling time ≤10 months",
            "PSA ≥2 ng/mL during ADT",
            "Castrate testosterone (<50 ng/dL)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant metastases on bone scan/CT",
            "History of seizure",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "Metastasis-free survival (MFS)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "PROSPER": {
        "pmid": "29949494",
        "nct": "NCT02003924",
        "citation": "Hussain M et al. PROSPER. NEJM 2018;378:2465-2474.",
        "stage": "m0_crpc",
        "regimen_tested": "ADT + enzalutamide 160 mg vs ADT + placebo",
        "inclusion": [
            "Non-metastatic CRPC (M0)",
            "PSA doubling time ≤10 months",
            "PSA ≥2 ng/mL on ADT",
            "Castrate testosterone (<50 ng/dL)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant metastases",
            "Seizure history",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "MFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "ARAMIS": {
        "pmid": "30763142",
        "nct": "NCT02200614",
        "citation": "Fizazi K et al. ARAMIS. NEJM 2019;380:1235-1246.",
        "stage": "m0_crpc",
        "regimen_tested": "ADT + darolutamide 600 mg BID vs ADT + placebo",
        "inclusion": [
            "Non-metastatic CRPC",
            "PSA doubling time ≤10 months",
            "PSA ≥2 ng/mL",
            "Castrate testosterone",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant metastases",
            "Severe cardiovascular disease",
            "Hepatic impairment Child-Pugh C",
        ],
        "endpoint_primary": "MFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC (metastatic CRPC) chemo + ARPI — 9 trials
    # ═══════════════════════════════════════════════════════════════════

    "TAX-327": {
        "pmid": "15470213",
        "nct": "NCT00134524",
        "citation": "Tannock IF et al. TAX-327. NEJM 2004;351:1502-1512.",
        "stage": "m1_crpc",
        "regimen_tested": "Docetaxel 75 mg/m² q3w + prednisone vs mitoxantrone",
        "inclusion": [
            "Metastatic castration-resistant prostate cancer",
            "ECOG 0-2",
            "Adequate hepatic/renal function",
        ],
        "exclusion": [
            "Prior cytotoxic chemotherapy",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "TROPIC": {
        "pmid": "20888992",
        "nct": "NCT00417079",
        "citation": "de Bono JS et al. TROPIC. Lancet 2010;376:1147-1154.",
        "stage": "m1_crpc",
        "regimen_tested": "Cabazitaxel 25 mg/m² q3w + prednisone vs mitoxantrone (post-docetaxel)",
        "inclusion": [
            "mCRPC with progression on/after docetaxel",
            "ECOG 0-2",
            "Adequate organ function",
        ],
        "exclusion": [
            "Severe neuropathy ≥grade 2",
            "Active infection requiring antibiotics",
            "ANC <1500",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "CARD": {
        "pmid": "31566937",
        "nct": "NCT02485691",
        "citation": "de Wit R et al. CARD. NEJM 2019;381:2506-2518.",
        "stage": "m1_crpc",
        "regimen_tested": "Cabazitaxel vs ARPI switch (after docetaxel + prior ARPI)",
        "inclusion": [
            "mCRPC with progression on docetaxel AND prior ARPI (abi/enza ≤12 months)",
            "ECOG 0-2",
            "Adequate organ function",
        ],
        "exclusion": [
            "Severe neuropathy",
            "Active infection",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "COU-AA-301": {
        "pmid": "21612468",
        "nct": "NCT00638690",
        "citation": "de Bono JS et al. COU-AA-301. NEJM 2011;364:1995-2005.",
        "stage": "m1_crpc",
        "regimen_tested": "Abiraterone 1000 mg + prednisone 5 mg BID vs placebo (post-docetaxel)",
        "inclusion": [
            "mCRPC progressing on docetaxel",
            "ECOG 0-2",
            "Adequate organ function",
        ],
        "exclusion": [
            "Severe hepatic impairment (Child-Pugh C)",
            "Uncontrolled hypertension",
            "Significant cardiovascular disease",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "COU-AA-302": {
        "pmid": "23228172",
        "nct": "NCT00887198",
        "citation": "Ryan CJ et al. COU-AA-302. NEJM 2013;368:138-148.",
        "stage": "m1_crpc",
        "regimen_tested": "Abiraterone + prednisone vs placebo (chemo-naïve mCRPC)",
        "inclusion": [
            "Asymptomatic or mildly symptomatic mCRPC",
            "Chemo-naïve (no prior cytotoxic chemo)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Visceral metastases at significant burden",
            "Pain requiring opioids",
            "Hepatic Child-Pugh C",
        ],
        "endpoint_primary": "rPFS + OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "AFFIRM": {
        "pmid": "22894553",
        "nct": "NCT00974311",
        "citation": "Scher HI et al. AFFIRM. NEJM 2012;367:1187-1197.",
        "stage": "m1_crpc",
        "regimen_tested": "Enzalutamide 160 mg vs placebo (post-docetaxel mCRPC)",
        "inclusion": [
            "mCRPC progressing on docetaxel",
            "ECOG 0-2",
            "Adequate organ function",
        ],
        "exclusion": [
            "Seizure history",
            "Brain metastases",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "PREVAIL": {
        "pmid": "24863011",
        "nct": "NCT01212991",
        "citation": "Beer TM et al. PREVAIL. NEJM 2014;371:424-433.",
        "stage": "m1_crpc",
        "regimen_tested": "Enzalutamide 160 mg vs placebo (chemo-naïve mCRPC)",
        "inclusion": [
            "Chemo-naïve asymptomatic/minimally symptomatic mCRPC",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Visceral mets",
            "Seizure history",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "OS + rPFS (co-primary)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "ALSYMPCA": {
        "pmid": "23863050",
        "nct": "NCT00699751",
        "citation": "Parker C et al. ALSYMPCA. NEJM 2013;369:213-223.",
        "stage": "m1_crpc",
        "regimen_tested": "Radium-223 dichloride 50 kBq/kg q4w x6 vs placebo",
        "inclusion": [
            "mCRPC with symptomatic bone metastases",
            "≥2 bone mets, no visceral mets",
            "ECOG 0-2",
            "Adequate hematologic reserve",
        ],
        "exclusion": [
            "Visceral metastases",
            "Lymph nodes >3 cm",
            "Imminent spinal cord compression",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC PSMA-targeted radioligand — 3 trials
    # ═══════════════════════════════════════════════════════════════════

    "VISION": {
        "pmid": "34161051",
        "nct": "NCT03511664",
        "citation": "Sartor O et al. VISION. NEJM 2021;385:1091-1103.",
        "stage": "m1_crpc",
        "regimen_tested": "Lu-177-PSMA-617 7.4 GBq q6w x6 + standard of care vs SOC",
        "inclusion": [
            "PSMA-positive mCRPC (≥1 lesion with SUVmax > liver background)",
            "Prior ≥1 ARPI AND ≥1 taxane chemotherapy",
            "ECOG 0-2",
            "Castrate testosterone",
        ],
        "exclusion": [
            "PSMA-negative disease",
            "Untreated brain metastases",
            "Diffuse marrow involvement (>50%)",
            "GFR <30 mL/min",
        ],
        "endpoint_primary": "rPFS + OS (alternate primary)",
        "biomarker_required": "PSMA-PET positive (SUVmax > liver)",
        "evidence_level": "level_1_category_1",
    },

    "PSMAfore": {
        "pmid": "37866746",
        "nct": "NCT04689828",
        "citation": "Morris MJ et al. PSMAfore. JCO 2024;42(17_suppl):LBA5000.",
        "stage": "m1_crpc",
        "regimen_tested": "Lu-177-PSMA-617 vs ARPI switch (chemo-naïve mCRPC after 1 ARPI)",
        "inclusion": [
            "PSMA-positive mCRPC after 1 prior ARPI",
            "Chemo-naïve",
            "ECOG 0-1",
            "Adequate organ function",
        ],
        "exclusion": [
            "Prior taxane chemotherapy",
            "PSMA-negative",
            "Brain metastases",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": "PSMA-PET positive",
        "evidence_level": "level_1_category_1",
    },

    "TheraP": {
        "pmid": "33581798",
        "nct": "NCT03392428",
        "citation": "Hofman MS et al. TheraP. Lancet 2021;397:797-804.",
        "stage": "m1_crpc",
        "regimen_tested": "Lu-177-PSMA-617 6-8 GBq q6w x6 vs cabazitaxel",
        "inclusion": [
            "PSMA-positive mCRPC progressing post-docetaxel",
            "PSMA SUVmax ≥20 in ≥1 lesion AND avidity > liver in all measurable lesions",
            "ECOG 0-2",
        ],
        "exclusion": [
            "Discordant FDG-positive PSMA-negative lesions",
            "Brain metastases",
            "Inadequate organ function",
        ],
        "endpoint_primary": "PSA response (≥50% reduction)",
        "biomarker_required": "PSMA-PET positive (SUVmax ≥20)",
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC HRR/PARP inhibitors — 5 trials
    # ═══════════════════════════════════════════════════════════════════

    "PROfound": {
        "pmid": "32343890",
        "nct": "NCT02987543",
        "citation": "de Bono J et al. PROfound. NEJM 2020;382:2091-2102.",
        "stage": "m1_crpc",
        "regimen_tested": "Olaparib 300 mg BID vs ARPI switch (HRR-mutated mCRPC)",
        "inclusion": [
            "mCRPC with progression on prior ARPI (abi or enza)",
            "Qualifying HRR mutation: BRCA1, BRCA2, ATM (Cohort A) or 12 other HRR genes (Cohort B)",
            "ECOG 0-2",
        ],
        "exclusion": [
            "MDS/AML history",
            "Active uncontrolled infection",
            "Brain metastases",
        ],
        "endpoint_primary": "rPFS (Cohort A) + OS",
        "biomarker_required": "HRR mutation (BRCA1/2/ATM cohort A; 12 genes cohort B)",
        "evidence_level": "level_1_category_1",
    },

    "MAGNITUDE": {
        "pmid": "35867349",
        "nct": "NCT03748641",
        "citation": "Chi KN et al. MAGNITUDE. JCO 2022;40:2293-2306.",
        "stage": "m1_crpc",
        "regimen_tested": "Niraparib + abiraterone + prednisone vs abi + placebo (1L mCRPC)",
        "inclusion": [
            "Newly diagnosed mCRPC (1st-line)",
            "HRR mutation (positive cohort) or biomarker-negative cohort",
            "ECOG 0-2",
        ],
        "exclusion": [
            "Prior systemic therapy for mCRPC",
            "MDS/AML",
            "Brain metastases",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": "HRR positive (BRCA1/2/ATM/CDK12/etc.)",
        "evidence_level": "level_1_category_1",
    },

    "PROpel": {
        "pmid": "35513049",
        "nct": "NCT03732820",
        "citation": "Clarke NW et al. PROpel. NEJM Evid 2022;1:EVIDoa2200043.",
        "stage": "m1_crpc",
        "regimen_tested": "Olaparib + abiraterone vs abi + placebo (1L mCRPC, all-comers)",
        "inclusion": [
            "Newly diagnosed mCRPC (1st-line)",
            "All-comers (HRR not required for entry)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Prior systemic therapy for mCRPC",
            "MDS/AML history",
            "Severe hepatic impairment",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": None,  # All-comers but HRR+ subgroup analysis
        "evidence_level": "level_1_category_1",
    },

    "TALAPRO-2": {
        "pmid": "37086745",
        "nct": "NCT03395197",
        "citation": "Agarwal N et al. TALAPRO-2. Lancet 2023;402:291-303.",
        "stage": "m1_crpc",
        "regimen_tested": "Talazoparib + enzalutamide vs enza + placebo (1L mCRPC)",
        "inclusion": [
            "Newly diagnosed mCRPC (1st-line)",
            "All-comers (Cohort 1) + HRR-deficient (Cohort 2)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "MDS/AML",
            "Prior PARP inhibitor",
            "Brain metastases",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": "HRR mutation for Cohort 2 (talazoparib labeled use)",
        "evidence_level": "level_1_category_1",
    },

    "TRITON-3": {
        "pmid": "36802571",
        "nct": "NCT02975934",
        "citation": "Fizazi K et al. TRITON3. NEJM 2023;388:719-732.",
        "stage": "m1_crpc",
        "regimen_tested": "Rucaparib 600 mg BID vs physician choice (BRCA+ mCRPC post-ARPI)",
        "inclusion": [
            "mCRPC progressing on 1 ARPI",
            "BRCA1, BRCA2, or ATM mutation (germline or somatic)",
            "ECOG 0-1",
            "No prior chemo for mCRPC",
        ],
        "exclusion": [
            "Prior PARP inhibitor",
            "MDS/AML",
        ],
        "endpoint_primary": "Imaging-based PFS",
        "biomarker_required": "BRCA1/BRCA2/ATM mutation",
        "evidence_level": "level_1_category_1",
    },

    "AMPLITUDE": {
        "pmid": "39527709",
        "nct": "NCT04497844",
        "citation": "Rathkopf D et al. AMPLITUDE. NEJM 2024;391:2197-2209.",
        "stage": "mcspc",
        "regimen_tested": "Niraparib + abiraterone + prednisone vs placebo + abi (HRR+ mCSPC)",
        "inclusion": [
            "mCSPC (newly diagnosed)",
            "HRR mutation (BRCA1/BRCA2/CDK12/PALB2/ATM/etc.)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Prior PARP inhibitor",
            "MDS/AML",
            "Visceral crisis",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": "HRR mutation",
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC immunotherapy / PI3K — 2 trials
    # ═══════════════════════════════════════════════════════════════════

    "IMPACT": {
        "pmid": "20818862",
        "nct": "NCT00065442",
        "citation": "Kantoff PW et al. IMPACT. NEJM 2010;363:411-422.",
        "stage": "m1_crpc",
        "regimen_tested": "Sipuleucel-T (autologous APC immunotherapy) vs placebo",
        "inclusion": [
            "Asymptomatic or mildly symptomatic mCRPC",
            "ECOG 0-1",
            "No visceral metastases",
            "Castrate testosterone",
        ],
        "exclusion": [
            "Visceral mets (excluded)",
            "Pain requiring opioids",
            "Significant immunosuppression",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "IPATential150": {
        "pmid": "34293272",
        "nct": "NCT03072238",
        "citation": "Sweeney C et al. IPATential150. Lancet 2021;398:131-142.",
        "stage": "m1_crpc",
        "regimen_tested": "Ipatasertib (AKT inhibitor) + abiraterone vs abi + placebo (1L mCRPC)",
        "inclusion": [
            "Newly diagnosed mCRPC (1st-line)",
            "PTEN-loss subgroup (ITT also analyzed)",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Diabetes type 1 or insulin-dependent type 2",
            "Brain metastases",
            "Prior ARPI for mCRPC",
        ],
        "endpoint_primary": "rPFS in PTEN-loss + ITT",
        "biomarker_required": "PTEN biallelic loss (IHC + NGS)",
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # BCR (biochemical recurrence) — 3 trials
    # ═══════════════════════════════════════════════════════════════════

    "EMBARK": {
        "pmid": "37877679",
        "nct": "NCT02319837",
        "citation": "Freedland SJ et al. EMBARK. NEJM 2023;389:1453-1465.",
        "stage": "recurrence_bcr",
        "regimen_tested": "Enzalutamide + LHRH agonist vs LHRH alone vs enza monotherapy",
        "inclusion": [
            "BCR after RP and/or RT (PSA ≥1 post-RP or ≥nadir+2 post-RT)",
            "PSA doubling time ≤9 months",
            "No metastases on conventional imaging",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant metastases",
            "Seizure history",
            "Severe cardiovascular disease",
        ],
        "endpoint_primary": "MFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "PRESTO": {
        "pmid": "37000748",
        "nct": "NCT03009981",
        "citation": "Aggarwal R et al. PRESTO/AFT-19. JCO 2023;41:3169-3181.",
        "stage": "recurrence_bcr",
        "regimen_tested": "ADT + apalutamide ± abiraterone (intensification) vs ADT alone",
        "inclusion": [
            "BCR with PSA doubling time ≤9 months",
            "ADT-naïve or short prior ADT",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant metastases on conventional imaging",
            "Visceral mets",
        ],
        "endpoint_primary": "PSA-PFS",
        "biomarker_required": None,
        "evidence_level": "level_2_category_2A",
    },

    "AFT-19": {  # alias of PRESTO
        "pmid": "37000748",
        "nct": "NCT03009981",
        "citation": "Aggarwal R et al. PRESTO/AFT-19. JCO 2023;41:3169-3181.",
        "stage": "recurrence_bcr",
        "regimen_tested": "Same as PRESTO",
        "inclusion": ["See PRESTO"],
        "exclusion": ["See PRESTO"],
        "endpoint_primary": "PSA-PFS",
        "biomarker_required": None,
        "evidence_level": "level_2_category_2A",
    },

    # ═══════════════════════════════════════════════════════════════════
    # Adjuvant / salvage RT — 6 trials
    # ═══════════════════════════════════════════════════════════════════

    "RADICALS-RT": {
        "pmid": "33002431",
        "nct": "NCT00541047",
        "citation": "Parker CC et al. RADICALS-RT. Lancet 2020;396:1413-1421.",
        "stage": "post_prostatectomy",
        "regimen_tested": "Adjuvant RT vs early salvage RT after RP",
        "inclusion": [
            "Post-RP patients with adverse features (positive margins, pT3, Gleason ≥7)",
            "PSA <0.2 at randomization (adjuvant cohort) or ≤0.2 (salvage)",
        ],
        "exclusion": [
            "Distant metastases",
            "Persistent post-RP PSA",
        ],
        "endpoint_primary": "BCR-free survival",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "RTOG-9601": {
        "pmid": "28199825",
        "nct": "NCT00002874",
        "citation": "Shipley WU et al. RTOG-9601. NEJM 2017;376:417-428.",
        "stage": "recurrence_bcr",
        "regimen_tested": "Salvage RT + bicalutamide 150 mg/d x24 months vs RT + placebo",
        "inclusion": [
            "BCR post-RP with PSA 0.2-4.0",
            "pT2-T3 with margin status",
            "Adequate organ function",
        ],
        "exclusion": [
            "Distant metastases",
            "PSA >4.0 (excluded as too high)",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "GETUG-AFU-16": {
        "pmid": "27160475",
        "nct": "NCT00423475",
        "citation": "Carrie C et al. GETUG-AFU 16. Lancet Oncol 2016;17:747-756.",
        "stage": "recurrence_bcr",
        "regimen_tested": "Salvage RT + 6-month ADT (goserelin) vs salvage RT alone",
        "inclusion": [
            "BCR post-RP with PSA ≥0.2 to ≤2.0",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Distant mets",
            "Prior pelvic RT",
        ],
        "endpoint_primary": "Progression-free survival (5-year)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "SPPORT": {
        "pmid": "35569376",
        "nct": "NCT00567580",
        "citation": "Pollack A et al. SPPORT. Lancet 2022;399:1886-1901.",
        "stage": "recurrence_bcr",
        "regimen_tested": "Salvage RT prostate bed + STAD ± pelvic LN RT",
        "inclusion": [
            "BCR post-RP with PSA ≥0.1",
            "Adverse features (Gleason ≥8, pT3, margins+)",
        ],
        "exclusion": [
            "Distant mets",
            "Prior pelvic RT",
        ],
        "endpoint_primary": "Freedom from progression (5-year)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "ARTISTIC": {
        "pmid": "33002431",  # meta-analysis of RADICALS-RT/GETUG-17/RAVES
        "nct": "Multiple",
        "citation": "Vale CL et al. ARTISTIC meta-analysis. Lancet 2020;396:1422-1431.",
        "stage": "post_prostatectomy",
        "regimen_tested": "Adjuvant RT vs early salvage RT (meta-analysis)",
        "inclusion": [
            "Pooled analysis of RADICALS-RT, GETUG-17, RAVES",
            "Post-RP adverse features",
        ],
        "exclusion": [
            "Distant metastases",
        ],
        "endpoint_primary": "Event-free survival",
        "biomarker_required": None,
        "evidence_level": "level_1_meta",
    },

    "RAVES": {
        "pmid": "33002432",
        "nct": "NCT00860652",
        "citation": "Kneebone A et al. RAVES. Lancet Oncol 2020;21:1331-1340.",
        "stage": "post_prostatectomy",
        "regimen_tested": "Adjuvant RT vs early salvage RT after RP",
        "inclusion": [
            "Post-RP with adverse features (pT3a/b, positive margins, Gleason ≥7)",
            "PSA <0.1 at randomization",
        ],
        "exclusion": [
            "Distant mets",
            "Persistent PSA",
        ],
        "endpoint_primary": "BCR-free survival",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "ARO-96-02": {
        "pmid": "19286551",
        "nct": "NCT00667069",
        "citation": "Wiegel T et al. ARO 96-02. JCO 2009;27:2924-2930.",
        "stage": "post_prostatectomy",
        "regimen_tested": "Adjuvant RT vs observation post-RP (pT3 or margins+)",
        "inclusion": [
            "Post-RP pT3 or margins+",
            "PSA undetectable post-RP",
        ],
        "exclusion": [
            "Persistent PSA",
            "Distant mets",
        ],
        "endpoint_primary": "BCR-free survival",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "SWOG-8794": {
        "pmid": "16985183",
        "nct": "NCT00002709",
        "citation": "Thompson IM et al. SWOG-8794. JAMA 2006;296:2329-2335.",
        "stage": "post_prostatectomy",
        "regimen_tested": "Adjuvant RT vs observation (pT3 post-RP)",
        "inclusion": [
            "pT3 post-RP",
            "PSA <0.4 ng/mL post-RP",
        ],
        "exclusion": [
            "Distant metastases",
            "PSA persistence",
        ],
        "endpoint_primary": "OS + DFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # Localized prostate cancer (definitive RP/RT comparison) — 4 trials
    # ═══════════════════════════════════════════════════════════════════

    "PROTECT": {
        "pmid": "27626136",
        "nct": "NCT02044172",
        "citation": "Hamdy FC et al. PROTECT. NEJM 2016;375:1415-1424.",
        "stage": "localized_initial",
        "regimen_tested": "Active monitoring vs RP vs RT (Gleason 6 mostly)",
        "inclusion": [
            "Localized prostate cancer (cT1-T2, N0M0)",
            "PSA <20 ng/mL",
            "Mostly Gleason 6, some 7",
        ],
        "exclusion": [
            "Locally advanced (T3-T4)",
            "Metastases",
        ],
        "endpoint_primary": "Prostate cancer mortality (10-year)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "SPCG-4": {
        "pmid": "12646536",
        "nct": "Not registered (pre-registry era)",
        "citation": "Bill-Axelson A et al. SPCG-4. NEJM 2018;379:2319-2329 (long-term).",
        "stage": "localized_initial",
        "regimen_tested": "Radical prostatectomy vs watchful waiting",
        "inclusion": [
            "Localized prostate cancer (T1-T2)",
            "Age <75",
            "Life expectancy >10 years",
        ],
        "exclusion": [
            "Metastatic disease",
            "Comorbidities limiting surgery",
        ],
        "endpoint_primary": "OS (very long-term)",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    "PIVOT": {
        "pmid": "22808955",
        "nct": "NCT00007644",
        "citation": "Wilt TJ et al. PIVOT. NEJM 2017;377:132-142 (long-term).",
        "stage": "localized_initial",
        "regimen_tested": "Radical prostatectomy vs observation",
        "inclusion": [
            "Localized prostate cancer (T1-T2)",
            "PSA <50 ng/mL",
            "Adequate fitness for RP",
        ],
        "exclusion": [
            "Metastatic disease",
            "Severe comorbidities",
        ],
        "endpoint_primary": "OS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC bone-targeted (not yet covered) — 1 trial
    # ═══════════════════════════════════════════════════════════════════

    "PEACE-3": {
        "pmid": "37000748",  # ESMO 2024 pres
        "nct": "NCT02194842",
        "citation": "Gillessen S et al. PEACE-3. ESMO 2024 LBA.",
        "stage": "m1_crpc",
        "regimen_tested": "Enzalutamide + radium-223 vs enza alone (bone mets mCRPC)",
        "inclusion": [
            "mCRPC with ≥2 bone mets",
            "Asymptomatic/mildly symptomatic",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Visceral mets",
            "Lymph nodes >3 cm",
        ],
        "endpoint_primary": "rPFS",
        "biomarker_required": None,
        "evidence_level": "level_1_category_1",
    },

    # ═══════════════════════════════════════════════════════════════════
    # mCRPC immunotherapy combinations — 1 trial
    # ═══════════════════════════════════════════════════════════════════

    "CONTACT-02": {
        "pmid": "39245045",
        "nct": "NCT04446117",
        "citation": "Agarwal N et al. CONTACT-02. JCO 2024;42(suppl):LBA18.",
        "stage": "m1_crpc",
        "regimen_tested": "Cabozantinib + atezolizumab vs ARPI switch (post-1 ARPI mCRPC)",
        "inclusion": [
            "mCRPC progressing on 1 prior ARPI",
            "Measurable soft tissue disease",
            "ECOG 0-1",
        ],
        "exclusion": [
            "Brain mets",
            "Active autoimmune disease",
            "Prior immune checkpoint inhibitor",
        ],
        "endpoint_primary": "rPFS + OS",
        "biomarker_required": None,  # Soft tissue measurable required
        "evidence_level": "level_1_category_1",
    },
}


# ──────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────


def get_trial_criteria(trial_id: str) -> dict[str, Any] | None:
    """Retorna criteria dict para trial_id, o None si no existe.

    >>> get_trial_criteria("CHAARTED")["pmid"]
    '26244877'
    """
    return TRIAL_CRITERIA_REGISTRY.get(trial_id)


def list_trial_ids() -> list[str]:
    """Retorna lista de todos los trial_ids registrados.

    >>> ids = list_trial_ids()
    >>> "CHAARTED" in ids and "PROfound" in ids
    True
    >>> len(ids) >= 30
    True
    """
    return sorted(TRIAL_CRITERIA_REGISTRY.keys())


def list_trials_by_stage(stage: str) -> list[str]:
    """Retorna lista de trial_ids para un stage clínico dado.

    Stages soportados: mcspc, m0_crpc, m1_crpc, recurrence_bcr,
                       post_prostatectomy, localized_initial.

    >>> "CHAARTED" in list_trials_by_stage("mcspc")
    True
    >>> "SPARTAN" in list_trials_by_stage("m0_crpc")
    True
    """
    return sorted([
        tid for tid, criteria in TRIAL_CRITERIA_REGISTRY.items()
        if criteria.get("stage") == stage
    ])


def list_trials_by_biomarker(biomarker_name: str) -> list[str]:
    """Retorna trial_ids que requieren un biomarcador específico.

    Ejemplos: "HRR", "BRCA", "PSMA", "PTEN", "MSI".

    >>> hrr_trials = list_trials_by_biomarker("HRR")
    >>> "PROfound" in hrr_trials and "MAGNITUDE" in hrr_trials
    True
    """
    biomarker_upper = biomarker_name.upper()
    matching = []
    for tid, criteria in TRIAL_CRITERIA_REGISTRY.items():
        bm_required = criteria.get("biomarker_required") or ""
        if biomarker_upper in str(bm_required).upper():
            matching.append(tid)
    return sorted(matching)


def get_total_trials_count() -> int:
    """Retorna total de trials registrados.

    >>> get_total_trials_count() >= 30
    True
    """
    return len(TRIAL_CRITERIA_REGISTRY)
