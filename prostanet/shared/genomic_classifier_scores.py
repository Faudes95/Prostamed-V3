"""Motor numérico para clasificadores genómicos en cáncer de próstata localizado.

Hasta EPIC 2 ProstaNet sólo almacenaba la categoría cualitativa
(``genomic_classifier_result = "Desfavorable"``), lo cual pierde información:
un Decipher 0.77 y uno 0.46 son "Alto" pero con implicaciones pronósticas
distintas (Spratt 2018 reporta OR por cada 0.1 punto de incremento en el
score). EPIC 2 añade captura numérica para:

* **Decipher Genomic Classifier** (22-gen, Veracyte) — rango 0.00–1.00.
  Cutoffs validados:
    * Low: < 0.45
    * Intermediate: 0.45 – 0.60
    * High: ≥ 0.60

* **Prolaris CCP score** (31-gen, Myriad) — escala log₂ de expresión,
  rango típico −2.5 a +2.5. Cutoffs derivados de Cuzick 2012/2015:
    * Low: < −1.0
    * Intermediate: −1.0 a +0.9
    * High: ≥ +1.0 (riesgo 10-y PCSM incremental)

* **Oncotype DX Genomic Prostate Score (GPS)** — escala 0–100.
  Cutoffs Cullen 2015 / Klein 2014:
    * Low: < 20
    * Intermediate: 20 – 40
    * High: ≥ 40

La función pública ``classify_genomic_score`` retorna un dict serializable
para el perfil y para el motor de riesgo NCCN-lo-cal-ized. Si el clínico
proporciona score numérico + categoría divergente, el numérico prevalece y
se deja traza de la discordancia en ``narrative``.

Referencias:
  * Spratt DE et al. *JCO* 2018;36:581 — Decipher validación 855 pacientes
    post-RP, HR 1.24 por 0.1 punto.
  * Klein EA et al. *Eur Urol* 2014;66:550 — Oncotype DX GPS desarrollo.
  * Cullen J et al. *Eur Urol* 2015;68:123 — Oncotype DX GPS validación.
  * Cuzick J et al. *Br J Cancer* 2012;106:1095 — Prolaris CCP PCSM.
  * Cuzick J et al. *Eur Urol* 2015;68:204 — Prolaris en post-biopsia.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prostanet.shared.ui_value_normalizer import clamp_numeric


_DECIPHER_BANDS = (
    ("low", 0.0, 0.45, "Decipher bajo (<0.45)", "NCCN favorece vigilancia o monoterapia local."),
    ("intermediate", 0.45, 0.60, "Decipher intermedio (0.45–0.60)", "Evaluar intensificación según otros factores (PSA, Gleason, LVI)."),
    ("high", 0.60, 1.01, "Decipher alto (≥0.60)", "Intensificar: RT + ADT o re-estadificar (Spratt 2018 HR 1.24/0.1 punto)."),
)

_PROLARIS_BANDS = (
    ("low", -3.0, -1.0, "Prolaris bajo (<−1.0)", "Candidato razonable a vigilancia o monoterapia local."),
    ("intermediate", -1.0, 1.0, "Prolaris intermedio (−1.0 a +1.0)", "Decisión orientada por NCCN + expectativa de vida."),
    ("high", 1.0, 3.0, "Prolaris alto (≥+1.0)", "Intensificar (Cuzick 2012: PCSM incremental significativo)."),
)

_ONCOTYPE_BANDS = (
    ("low", 0.0, 20.0, "Oncotype GPS bajo (<20)", "Favorece vigilancia activa en muy-bajo/bajo riesgo NCCN."),
    ("intermediate", 20.0, 40.0, "Oncotype GPS intermedio (20–40)", "Considerar tratamiento definitivo."),
    ("high", 40.0, 100.1, "Oncotype GPS alto (≥40)", "Intensificar manejo (Klein 2014, Cullen 2015)."),
)


_CLASSIFIER_SPECS = {
    "decipher": {
        "bands": _DECIPHER_BANDS,
        "min": 0.0,
        "max": 1.0,
        "unit": "score",
        "evidence_tag": "Spratt 2018 JCO",
        "label": "Decipher Genomic Classifier",
    },
    "prolaris": {
        "bands": _PROLARIS_BANDS,
        "min": -3.0,
        "max": 3.0,
        "unit": "log₂ score",
        "evidence_tag": "Cuzick 2012 BrJCancer",
        "label": "Prolaris CCP",
    },
    "oncotype": {
        "bands": _ONCOTYPE_BANDS,
        "min": 0.0,
        "max": 100.0,
        "unit": "GPS",
        "evidence_tag": "Klein 2014 EurUrol",
        "label": "Oncotype DX GPS",
    },
}


@dataclass(frozen=True)
class GenomicScoreVerdict:
    classifier: str
    score: float | None
    band: str | None
    band_label: str | None
    band_action: str | None
    validation_error: str | None
    evidence_tag: str
    unit: str
    narrative: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "classifier": self.classifier,
            "score": self.score,
            "band": self.band,
            "band_label": self.band_label,
            "band_action": self.band_action,
            "validation_error": self.validation_error,
            "evidence_tag": self.evidence_tag,
            "unit": self.unit,
            "narrative": self.narrative,
        }


def _band_from_score(classifier: str, score: float) -> tuple[str, str, str] | None:
    bands = _CLASSIFIER_SPECS[classifier]["bands"]
    for code, lo, hi, label, action in bands:
        if lo <= score < hi:
            return code, label, action
    last = bands[-1]
    return last[0], last[3], last[4]


def classify_genomic_score(
    *,
    classifier: str,
    score: Any,
    categorical_band: Any = None,
) -> dict[str, Any]:
    """Evalúa un score numérico y devuelve la banda canónica.

    Si se pasa ``categorical_band`` y diverge de la banda numérica, se
    documenta la divergencia en ``narrative`` (la numérica prevalece).
    """
    key = (classifier or "").strip().lower()
    spec = _CLASSIFIER_SPECS.get(key)
    if spec is None:
        return GenomicScoreVerdict(
            classifier=key,
            score=None,
            band=None,
            band_label=None,
            band_action=None,
            validation_error=f"Clasificador no soportado: {classifier}",
            evidence_tag="",
            unit="",
            narrative="",
        ).to_dict()

    score_val, score_err = clamp_numeric(
        score,
        min_value=spec["min"],
        max_value=spec["max"],
        allow_negative=spec["min"] < 0,
    )
    if score_err:
        return GenomicScoreVerdict(
            classifier=key,
            score=score_val,
            band=None,
            band_label=None,
            band_action=None,
            validation_error=score_err,
            evidence_tag=spec["evidence_tag"],
            unit=spec["unit"],
            narrative=f"Score fuera de rango para {spec['label']}: {score_err}.",
        ).to_dict()
    if score_val is None:
        return GenomicScoreVerdict(
            classifier=key,
            score=None,
            band=None,
            band_label=None,
            band_action=None,
            validation_error=None,
            evidence_tag=spec["evidence_tag"],
            unit=spec["unit"],
            narrative=f"Sin score numérico disponible para {spec['label']}.",
        ).to_dict()

    band = _band_from_score(key, score_val)
    band_code, band_label, band_action = band

    narrative_parts = [f"{spec['label']}: {score_val} ({band_label})"]
    if categorical_band:
        cat_clean = str(categorical_band).strip().lower()
        normalized = {
            "low": "low",
            "bajo": "low",
            "favorable": "low",
            "intermediate": "intermediate",
            "intermedio": "intermediate",
            "intermedio favorable": "intermediate",
            "high": "high",
            "alto": "high",
            "desfavorable": "high",
        }.get(cat_clean)
        if normalized and normalized != band_code:
            narrative_parts.append(
                f"Discordancia con categoría reportada '{categorical_band}'. "
                f"Prevalece la banda numérica ({band_label})."
            )

    return GenomicScoreVerdict(
        classifier=key,
        score=score_val,
        band=band_code,
        band_label=band_label,
        band_action=band_action,
        validation_error=None,
        evidence_tag=spec["evidence_tag"],
        unit=spec["unit"],
        narrative=" ".join(narrative_parts),
    ).to_dict()


def resolve_dominant_band(verdicts: list[dict[str, Any]]) -> str | None:
    """Cuando hay múltiples clasificadores, retorna la banda más alta.

    Prioriza high > intermediate > low. Útil para governance que debe
    escoger la decisión más conservadora.
    """
    if not verdicts:
        return None
    priority = {"high": 2, "intermediate": 1, "low": 0}
    current = -1
    best = None
    for verdict in verdicts:
        band = verdict.get("band")
        if band in priority and priority[band] > current:
            current = priority[band]
            best = band
    return best


__all__ = [
    "GenomicScoreVerdict",
    "classify_genomic_score",
    "resolve_dominant_band",
]
