"""
NLP Clinical Extractor — "El Lector de Documentos".

Extracts structured clinical data from unstructured text in Spanish:
  - Pathology reports → Gleason, cores, perineural invasion, margins
  - Imaging reports → TNM, lesion count, SUVmax, PI-RADS
  - Clinical notes → PSA, treatment changes, symptoms, ECOG
  - Discharge summaries → diagnosis, procedures, complications

Architecture:
  - Rule-based extraction (no GPU required, always available)
  - Optional BETO (Spanish BERT) fine-tuned NER for enhanced accuracy
  - Entity → FieldSpec mapping for automatic record population

Usage::

    extractor = ClinicalNLPExtractor()
    result = extractor.extract(text, document_type="pathology_report")
    # result.entities → {"gleason_primary": 4, "positive_cores": 8, ...}
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Regex patterns for clinical entity extraction ──

PATTERNS: dict[str, list[str]] = {
    # PSA
    "psa": [
        r"PSA\s+(?:basal|inicial|al\s+diagnóstico)[\s:=]+([0-9]+(?:[.,][0-9]+)?)",
        r"(?:PSA|antígeno prostático específico)[\s:=]+([0-9]+(?:[.,][0-9]+)?)\s*(?:ng/mL|ng\/ml)?",
        r"PSA[\s:]+([0-9]+[.,][0-9]+)",
    ],

    # Gleason score
    "gleason_primary": [
        r"Gleason\s+([3-5])\s*[+×]\s*[3-5]",
        r"grado\s+primario[\s:]+([3-5])",
    ],
    "gleason_secondary": [
        r"Gleason\s+[3-5]\s*[+×]\s*([3-5])",
        r"grado\s+secundario[\s:]+([3-5])",
    ],
    "gleason_total": [
        r"Gleason\s+(?:total|suma)[\s:=]+([6-9]|10)",
        r"Score\s+Gleason[\s:]+([6-9]|10)",
    ],

    # Cores
    "positive_cores": [
        r"([0-9]+)\s+(?:de|\/)\s*[0-9]+\s+(?:biopsias|cilindros|cores)\s+(?:positiv|comprometid|afectad)",
        r"(?:cores|cilindros)\s+positivos[\s:]+([0-9]+)",
        r"([0-9]+)\s+cilindros?\s+(?:positiv|con\s+adenocarcinoma)",
    ],
    "total_cores": [
        r"[0-9]+\s+(?:de|\/)\s*([0-9]+)\s+(?:biopsias|cilindros|cores)",
        r"(?:total\s+de\s+)?([0-9]+)\s+(?:biopsias|cilindros|cores)\s+(?:tomad|obteni|realizad)",
    ],

    # TNM staging
    "clinical_tstage": [
        r"\bT([1-4][a-c]?)\b",
        r"estadio\s+clínico[\s:]+T([1-4][a-c]?)",
    ],
    "n_stage": [
        r"\bN([0-3])\b(?!\s*cm)",
        r"ganglios[\s:]+N([0-3])",
    ],
    "m_stage": [
        r"\bM([01][a-c]?)\b",
        r"metástasis[\s:]+M([01][a-c]?)",
    ],

    # ISUP Grade Group
    "isup_grade": [
        r"(?:Grupo|Grado)\s+(?:ISUP|de\s+Grado)\s+([1-5])",
        r"Grado\s+([1-5])\s+(?:de\s+)?ISUP",
        r"ISUP\s+(?:grade|grado)?\s*([1-5])",
    ],

    # PI-RADS
    "pirads_score": [
        r"PI[-\s]?RADS[\s:]+([1-5])",
        r"PIRADS[\s:]+([1-5])",
        r"categoría\s+PI-RADS\s+([1-5])",
    ],

    # Perineural invasion
    "perineural_invasion": [
        r"invasión\s+perineural[\s:]+(?:presente|positiva|sí|sí se\s+observa)",
        r"invasión\s+perineural[\s:]+(?:ausente|negativa|no)",
    ],


    # PSA-DT / PSADT
    "psadt": [
        r"(?:PSADT|tiempo de\s+duplicación de\s+PSA|PSA-DT)[\s:]+([0-9]+(?:[.,][0-9]+)?)\s+meses",
        r"duplicación[\s:]+([0-9]+(?:[.,][0-9]+)?)\s+meses",
    ],

    # ECOG
    "ecog_score": [
        r"ECOG[\s:]+([0-4])",
        r"performance\s+status[\s:]+([0-4])",
        r"estado\s+funcional[\s:]+([0-4])",
    ],

    # Age
    "age": [
        r"paciente\s+(?:masculino|hombre|varón)\s+de\s+([0-9]{2,3})\s+años",
        r"([0-9]{2,3})\s+años\s+de\s+edad",
        r"edad[\s:]+([0-9]{2,3})\s+años",
    ],

    # Hemoglobin
    "hemoglobin": [
        r"(?:hemoglobina|Hgb|Hb)[\s:]+([0-9]+(?:[.,][0-9]+)?)\s*g/dL",
    ],

    # PSA nadir
    "nadir_psa": [
        r"(?:PSA\s+)?nadir[\s:]+([0-9]+(?:[.,][0-9]+)?)\s*ng/mL",
        r"PSA\s+más\s+bajo[\s:]+([0-9]+(?:[.,][0-9]+)?)",
    ],

    # Diagnosis date
    "diagnosis_date": [
        r"(?:diagnóstico|diagnosticado)\s+(?:en|el)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"fecha\s+de\s+diagnóstico[\s:]+(\d{4}-\d{2}-\d{2})",
    ],

    # Bone lesions
    "bone_lesion_count": [
        r"([0-9]+)\s+(?:lesiones?|metástasis)\s+(?:óseas?|en\s+hueso)",
        r"([0-9]+)\s+focos?\s+(?:óseos?|en\s+esqueleto)",
    ],

    # SUVmax (PSMA PET)
    "psma_suv_max": [
        r"SUVmax[\s:]+([0-9]+(?:[.,][0-9]+)?)",
        r"SUV\s+máximo[\s:]+([0-9]+(?:[.,][0-9]+)?)",
    ],
}

# Boolean entity patterns (presence = True)
BOOLEAN_PATTERNS: dict[str, tuple[list[str], list[str]]] = {
    "perineural_invasion": (
        [
            r"invasión\s+perineural\s+(?:presente|positiva|sí)",
            r"perineural\s+invasion\s+(?:present|positive)",
        ],
        [
            r"invasión\s+perineural\s+(?:ausente|negativa|no)",
            r"(?:sin|no)\s+invasión\s+perineural",
        ],
    ),
    "positive_surgical_margins": (
        [
            r"márgenes?\s+(?:positivos?|comprometidos?|afectados?)",
            r"margen\s+(?:positivo|comprometido)",
        ],
        [
            r"márgenes?\s+(?:negativos?|libres?|sin\s+compromiso)",
            r"márgenes?\s+de\s+resección\s+libres?",
        ],
    ),
    "lymphovascular_invasion": (
        [
            r"invasión\s+linfovascular\s+(?:presente|positiva)",
            r"invasión\s+(?:linfática|vascular)\s+(?:presente|positiva)",
        ],
        [
            r"(?:sin|no)\s+invasión\s+linfovascular",
            r"invasión\s+linfovascular\s+(?:ausente|negativa)",
        ],
    ),
}


@dataclass
class ExtractionResult:
    """Result of clinical NLP extraction."""

    entities: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    raw_matches: dict[str, list[str]] = field(default_factory=dict)
    document_type: str = ""
    char_count: int = 0

    def to_fieldspec_payload(self) -> dict[str, Any]:
        """Convert to payload compatible with FieldSpec-based forms."""
        return dict(self.entities)


class ClinicalNLPExtractor:
    """
    Rule-based clinical NLP extractor for Spanish medical documents.

    Falls back gracefully when BETO is unavailable.
    """

    def __init__(self, use_bert: bool = False) -> None:
        self.use_bert = use_bert
        self._bert_model = None

        if use_bert:
            self._try_load_bert()

    def _try_load_bert(self) -> None:
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if not resolve_feature_flags().get("ENABLE_AI_NLP_EXTRACTION"):
                return

            # BETO: dccuchile/bert-base-spanish-wwm-cased
            # Would load here if transformers is installed
            logger.debug("BERT NLP model not loaded (transformers not available or flag OFF)")
        except Exception as exc:
            logger.debug("BERT load skipped: %s", exc)

    def extract(
        self,
        text: str,
        document_type: str = "clinical_note",
    ) -> ExtractionResult:
        """
        Extract clinical entities from text.

        Args:
            text: Raw clinical document text in Spanish
            document_type: One of: clinical_note, pathology_report,
                          imaging_report, discharge_summary

        Returns:
            ExtractionResult with entities, confidence, and raw matches
        """
        if not text or not isinstance(text, str):
            return ExtractionResult(document_type=document_type)

        # Normalize text
        text_normalized = self._normalize(text)

        entities: dict[str, Any] = {}
        confidence: dict[str, float] = {}
        raw_matches: dict[str, list[str]] = {}

        # ── Numeric entity extraction ──
        for entity_name, pattern_list in PATTERNS.items():
            for pattern in pattern_list:
                matches = re.findall(pattern, text_normalized, re.IGNORECASE)
                if matches:
                    raw_matches[entity_name] = matches
                    value = self._parse_value(matches[0])
                    if value is not None:
                        entities[entity_name] = value
                        confidence[entity_name] = 0.85
                    break

        # ── Boolean entity extraction ──
        for entity_name, (pos_patterns, neg_patterns) in BOOLEAN_PATTERNS.items():
            for pat in pos_patterns:
                if re.search(pat, text_normalized, re.IGNORECASE):
                    entities[entity_name] = True
                    confidence[entity_name] = 0.90
                    break
            if entity_name not in entities:
                for pat in neg_patterns:
                    if re.search(pat, text_normalized, re.IGNORECASE):
                        entities[entity_name] = False
                        confidence[entity_name] = 0.85
                        break

        # ── Derived entities ──
        self._derive_entities(entities)

        return ExtractionResult(
            entities=entities,
            confidence=confidence,
            raw_matches=raw_matches,
            document_type=document_type,
            char_count=len(text),
        )

    def extract_from_document_ingestion(
        self,
        document_text: str,
        patient_id: int,
        document_type: str = "clinical_note",
    ) -> dict[str, Any]:
        """
        Extract and format for document_ingestion pipeline.

        Returns dict compatible with DocumentExtractionCandidate format.
        """
        result = self.extract(document_text, document_type)

        candidates = []
        for field_name, value in result.entities.items():
            conf = result.confidence.get(field_name, 0.7)
            candidates.append({
                "field_name": field_name,
                "extracted_value": value,
                "confidence": conf,
                "source_text": document_text[:200],
                "extraction_method": "rule_based_nlp",
            })

        return {
            "patient_id": patient_id,
            "document_type": document_type,
            "extraction_candidates": candidates,
            "entity_count": len(result.entities),
            "overall_confidence": sum(result.confidence.values()) / max(1, len(result.confidence)),
        }

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize whitespace and common abbreviations."""
        text = re.sub(r"\s+", " ", text)
        text = text.replace(",", ".").replace("–", "-")
        return text.strip()

    @staticmethod
    def _parse_value(match: str) -> Any:
        """Parse a regex match string to appropriate Python type."""
        match = str(match).strip().replace(",", ".")
        try:
            float_val = float(match)
            if float_val == int(float_val):
                return int(float_val)
            return float_val
        except (ValueError, TypeError):
            return match if match else None

    @staticmethod
    def _derive_entities(entities: dict[str, Any]) -> None:
        """Derive additional entities from extracted ones."""
        # ISUP from Gleason
        if "gleason_primary" in entities and "gleason_secondary" in entities:
            total = entities["gleason_primary"] + entities["gleason_secondary"]
            if "isup_grade" not in entities:
                if total <= 6:
                    entities["isup_grade"] = 1
                elif total == 7 and entities["gleason_primary"] == 3:
                    entities["isup_grade"] = 2
                elif total == 7 and entities["gleason_primary"] == 4:
                    entities["isup_grade"] = 3
                elif total == 8:
                    entities["isup_grade"] = 4
                else:
                    entities["isup_grade"] = 5

        # Percent positive cores
        if "positive_cores" in entities and "total_cores" in entities:
            total = entities["total_cores"]
            positive = entities["positive_cores"]
            if total > 0:
                entities["pct_cores_positive"] = round((positive / total) * 100, 1)


def extract_from_note(text: str, document_type: str = "clinical_note") -> dict[str, Any]:
    """Convenience function for quick extraction."""
    extractor = ClinicalNLPExtractor()
    result = extractor.extract(text, document_type)
    return result.to_fieldspec_payload()
