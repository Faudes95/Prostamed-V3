"""EPIC 21 — Clinical Vocabulary Boost for STT (`/voice-ai-engine-development` skill).

Provides domain-specific vocabulary hints that improve faster-whisper STT
recognition accuracy for prostate cancer clinical terms in ES/EN.

Whisper supports an `initial_prompt` parameter that biases recognition toward
the listed terms. This module assembles a prompt covering:
  - Trial acronyms (CHAARTED, VISION, LATITUDE, etc.)
  - Drug names (abiraterona, enzalutamida, [177Lu]Lu-PSMA-617, etc.)
  - Clinical terms (Gleason, PSADT, ECOG, Phoenix criteria, etc.)
  - Anatomy/imaging (PSMA-PET, mpMRI, fossa de prostatectomía, etc.)
  - Lab markers (chromogranin, synaptophysin, NSE, LDH, alkaline phos)
  - HRR/MSI/TMB genomic terms

Integration:
    from prostanet.voice.clinical_vocabulary_boost import get_stt_initial_prompt
    prompt = get_stt_initial_prompt(language="es")
    # Pass to faster-whisper:
    segments, info = model.transcribe(audio, initial_prompt=prompt)

Honest scope: this is a prompt-engineering improvement, NOT model retraining.
For higher accuracy on rare terms (e.g., specific drug names), consider:
  - Custom fine-tuned Whisper model with prostate cancer corpus
  - LLM-based post-processing for term normalization
  - User vocabulary submission UI per institution
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────── Vocabulary registry ───────────────────

# Pivotal trial acronyms (high-frequency in prostate cancer discussions)
PIVOTAL_TRIAL_ACRONYMS = [
    "CHAARTED", "ARASENS", "STAMPEDE", "LATITUDE", "PEACE-1",
    "TITAN", "ENZAMET", "ARCHES", "SPARTAN", "ARAMIS", "PROSPER",
    "AFFIRM", "PREVAIL", "EMBARK", "CARD", "TROPIC", "FIRSTANA",
    "VISION", "TheraP", "PSMAfore",
    "PROfound", "PROpel", "MAGNITUDE", "TALAPRO-2", "TRITON-3",
    "ALSYMPCA",
    "STOMP", "ORIOLE", "RADICALS", "RADICALS-RT",
    "KEYNOTE-365", "KEYNOTE-199",
    "PROMETHEUS", "CARLHA",
    "COU-AA-301", "COU-AA-302",
    "PRIAS", "PROTECT", "ProtecT",
    "ASCENDE-RT", "DART-01-05", "EORTC-22863", "RTOG-8531",
    "GETUG-AFU-17", "GETUG-AFU-18",
]

# Drug names (generic + brand)
DRUG_NAMES_ES = [
    "abiraterona", "abiraterone",
    "enzalutamida", "enzalutamide",
    "apalutamida", "apalutamide",
    "darolutamida", "darolutamide",
    "docetaxel", "Taxotere",
    "cabazitaxel", "Jevtana",
    "olaparib", "Lynparza",
    "rucaparib", "Rubraca",
    "talazoparib", "Talzenna",
    "niraparib", "Zejula",
    "pembrolizumab", "Keytruda",
    "dostarlimab", "Jemperli",
    "atezolizumab", "Tecentriq",
    "nivolumab", "Opdivo",
    "lutetium-177", "lutecio-177", "[177Lu]Lu-PSMA-617", "vipivotide tetraxetan", "Pluvicto",
    "radium-223", "radio-223", "Xofigo",
    "leuprolide", "leuprolide acetato",
    "goserelin", "degarelix",
    "denosumab", "Xgeva", "Prolia",
    "ácido zoledrónico", "zoledronate",
    "carboplatino", "cisplatino", "etopósido", "topotecán",
    "sipuleucel-T", "Provenge",
    "bicalutamida", "flutamida", "nilutamida",
]

# Clinical concepts (NCCN, EAU, pivotal terms)
CLINICAL_TERMS_ES = [
    "Gleason", "Gleason score", "patrón primario", "patrón secundario",
    "PSADT", "PSA doubling time", "tiempo de duplicación PSA",
    "ECOG", "Karnofsky", "performance status",
    "Phoenix criteria", "criterios de Phoenix",
    "recurrencia bioquímica", "BCR", "biochemical recurrence",
    "castration-resistant", "castración resistente", "CRPC",
    "metástasis", "metastasis", "metastatic",
    "alto volumen", "high volume", "CHAARTED criteria",
    "bajo volumen", "low volume",
    "oligometastasis", "oligometástasis", "oligoprogresión",
    "neuroendocrine", "neuroendocrino", "NEPC", "small cell",
    "AR-V7", "splice variant",
    "active surveillance", "vigilancia activa", "AS",
    "prostatectomía radical", "radical prostatectomy", "RP",
    "radioterapia externa", "external beam radiation therapy", "EBRT",
    "braquiterapia", "brachytherapy", "LDR", "HDR",
    "SBRT", "stereotactic body radiotherapy",
    "salvage", "rescate", "salvage RT", "salvage cryoablation",
    "HIFU", "high-intensity focused ultrasound",
    "crioablación", "cryotherapy",
    "ablación focal", "focal therapy",
    "MDT", "metastasis-directed therapy",
    "ADT", "androgen deprivation therapy", "deprivación androgénica",
    "ARSI", "ARPI", "androgen receptor inhibitor",
]

# Imaging terms
IMAGING_TERMS_ES = [
    "PSMA-PET", "PSMA-PET/CT", "Galio-68 PSMA", "F-18 PSMA",
    "mpMRI", "multiparametric MRI", "resonancia multiparamétrica",
    "PI-RADS", "PIRADS", "PI-RADS 4", "PI-RADS 5",
    "bone scan", "gammagrafía ósea", "rastreo óseo",
    "fossa", "fossa de prostatectomía",
    "linfadenopatía", "nodal", "ganglionar",
    "visceral", "hepático", "pulmonar", "cerebral",
    "TNM", "AJCC", "cT1c", "cT2a", "cT2b", "cT2c", "cT3a", "cT3b", "cT4",
    "pT2", "pT3a", "pT3b", "pT4",
    "M1a", "M1b", "M1c", "M0",
    "pN+", "pN0",
]

# Genomic/biomarker terms
GENOMIC_TERMS = [
    "BRCA1", "BRCA2", "ATM", "CHEK2", "PALB2", "CDK12", "RAD51",
    "HRR", "homologous recombination",
    "MSI", "MSI-high", "MSI-stable",
    "dMMR", "deficient mismatch repair",
    "TMB", "tumor mutational burden",
    "HOXB13", "G84E",
    "Lynch syndrome", "MLH1", "MSH2", "MSH6", "PMS2", "EPCAM",
    "germline", "somatic", "línea germinal", "germinal", "somática",
    "chromogranin A", "cromogranina A",
    "synaptophysin", "sinaptofisina",
    "NSE", "neuron-specific enolase", "enolasa neuronal específica",
]

# Lab markers (numeric + qualitative)
LAB_MARKERS = [
    "PSA", "antígeno prostático específico", "antígeno prostático",
    "testosterona", "testosterone",
    "LDH", "lactato deshidrogenasa",
    "alkaline phosphatase", "fosfatasa alcalina",
    "ALP", "FA",
    "creatinina", "creatinine", "GFR", "tasa de filtración glomerular",
    "hemoglobina", "hemoglobin", "Hb",
    "albúmina", "albumin",
    "calcium", "calcio", "vitamina D",
]

# Number-related cues (improves number parsing)
NUMBER_CUES = [
    "punto", "point", "decimal", "coma",
    "ng por mililitro", "ng/mL", "nanogramos por mililitro",
    "miligramos", "miligramo", "mg",
    "gray", "Gy", "centigray",
    "meses", "months", "años", "years",
    "porcentaje", "percent", "por ciento",
]


# ─────────────────── Public API ───────────────────


def get_full_vocabulary() -> list[str]:
    """Return complete sorted list of clinical vocabulary terms."""
    all_terms = set()
    for collection in [
        PIVOTAL_TRIAL_ACRONYMS,
        DRUG_NAMES_ES,
        CLINICAL_TERMS_ES,
        IMAGING_TERMS_ES,
        GENOMIC_TERMS,
        LAB_MARKERS,
        NUMBER_CUES,
    ]:
        all_terms.update(collection)
    return sorted(all_terms)


def get_stt_initial_prompt(
    language: str = "es",
    *,
    max_chars: int = 1024,
    include_categories: list[str] | None = None,
) -> str:
    """Build an initial_prompt for faster-whisper STT.

    Args:
        language: "es" or "en" (currently both vocabularies are bilingual)
        max_chars: cap prompt length (Whisper recommends ≤224 tokens ≈ ~1KB)
        include_categories: optional filter
            ["trials", "drugs", "clinical", "imaging", "genomic", "labs", "numbers"]
            None = include all

    Returns:
        Whisper-friendly prompt string with comma-separated key terms.
    """
    category_map = {
        "trials": PIVOTAL_TRIAL_ACRONYMS,
        "drugs": DRUG_NAMES_ES,
        "clinical": CLINICAL_TERMS_ES,
        "imaging": IMAGING_TERMS_ES,
        "genomic": GENOMIC_TERMS,
        "labs": LAB_MARKERS,
        "numbers": NUMBER_CUES,
    }
    # Priority order (most important for clinical STT first): labs, clinical,
    # imaging, drugs, genomic, trials, numbers. Ensures essential terms
    # (PSA, Gleason, ECOG) survive truncation under Whisper token limits.
    default_priority_order = [
        "labs", "clinical", "imaging", "drugs", "genomic", "trials", "numbers",
    ]
    selected_cats = include_categories or default_priority_order
    terms: list[str] = []
    for cat in selected_cats:
        terms.extend(category_map.get(cat, []))

    # Build a sentence-like prompt to bias model toward clinical terminology
    if language.lower() == "es":
        prefix = (
            "Transcripción clínica de oncología prostática. "
            "Términos esperados: "
        )
    else:
        prefix = (
            "Clinical prostate oncology transcription. "
            "Expected terms: "
        )
    body = ", ".join(terms)
    full = prefix + body + "."

    # Truncate to max_chars while preserving complete terms
    if len(full) > max_chars:
        truncated_body = ""
        cursor = len(prefix)
        for term in terms:
            term_with_sep = term + ", "
            if cursor + len(term_with_sep) > max_chars - 2:
                break
            truncated_body += term_with_sep
            cursor += len(term_with_sep)
        full = prefix + truncated_body.rstrip(", ") + "."

    return full


def get_vocabulary_stats() -> dict[str, Any]:
    """Report vocabulary coverage stats per category."""
    return {
        "categories": {
            "trials": len(PIVOTAL_TRIAL_ACRONYMS),
            "drugs": len(DRUG_NAMES_ES),
            "clinical": len(CLINICAL_TERMS_ES),
            "imaging": len(IMAGING_TERMS_ES),
            "genomic": len(GENOMIC_TERMS),
            "labs": len(LAB_MARKERS),
            "numbers": len(NUMBER_CUES),
        },
        "total_unique_terms": len(get_full_vocabulary()),
        "languages": ["es", "en"],
        "scope": "prostate_cancer_oncology",
    }


__all__ = [
    "PIVOTAL_TRIAL_ACRONYMS",
    "DRUG_NAMES_ES",
    "CLINICAL_TERMS_ES",
    "IMAGING_TERMS_ES",
    "GENOMIC_TERMS",
    "LAB_MARKERS",
    "NUMBER_CUES",
    "get_full_vocabulary",
    "get_stt_initial_prompt",
    "get_vocabulary_stats",
]
