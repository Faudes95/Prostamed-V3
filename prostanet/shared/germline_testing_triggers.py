# -*- coding: utf-8 -*-
"""
Germline testing triggers — NCCN PROS-H v5.2026.

Determina si un paciente con cáncer de próstata cumple criterios para
recomendar pruebas germinales BRCA1/2/ATM/PALB2/CHEK2/MSH2/MLH1/MSH6/PMS2.

Salida:
    ``should_offer_germline_testing(patient) -> GermlineTestingRecommendation``
    con campos ``should_offer`` (bool), ``priority`` (``category_2A`` |
    ``consider`` | ``not_indicated``), ``reasons`` (razones NCCN explícitas
    activas), ``triggers_matched`` (lista canónica de triggers con evidencia),
    ``missing_inputs`` (campos que podrían precisar más el gate) y
    ``evidence_tags``.

El motor es **retro-compatible** con los campos ya capturados en EPIC 2:
  * ``germline_testing_performed`` / ``germline_test_date``
  * ``germline_pathogenic_variant`` / ``somatic_pathogenic_variant``
  * ``family_history_cancer``

Si el testing germinal ya fue realizado, emite ``priority="not_indicated"``
con ``reasons=["Testing germinal previamente realizado"]`` para evitar
recomendaciones duplicadas.

Referencias:
  * NCCN Prostate v5.2026 PROS-H (category 2A germline triggers).
  * Giri VN et al. *JCO* 2020;38:2798 (Philadelphia Prostate Cancer Consensus
    — histología intraductal/ductal/cribiforme como trigger).
  * Cheng HH et al. *JCO* 2019;37:11 (family history criteria).
  * NCCN PROS-A general risk assessment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ── Constantes canónicas ─────────────────────────────────────────────────

NCCN_HIGH_RISK_STATES: set[str] = {
    "m1_crpc",
    "m0_crpc",
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "recurrence_bcr",
    "adt_progression_verification",
}

LOCALIZED_ENTRY_STATES: set[str] = {
    "localized_initial",
    "post_prostatectomy",
}

FAMILY_HISTORY_TRIGGERS: set[str] = {
    "prostate_metastatic",
    "prostate_high_risk",
    "breast_male",
    "breast_female_bilateral",
    "breast_lt_50",
    "ovarian",
    "pancreatic",
    "colorectal_lynch",
    "endometrial",
    "urothelial_lynch",
    "multiple_first_degree",
    "ashkenazi_jewish",
}

INTRADUCTAL_HISTOLOGY_MARKERS: set[str] = {
    "intraductal",
    "ductal",
    "cribriform",
    "ductal_cribriform",
    "intraductal_carcinoma",
}

PATHOGENIC_VARIANT_GENES: set[str] = {
    "BRCA2", "BRCA1", "ATM", "PALB2", "CHEK2",
    "MSH2", "MLH1", "MSH6", "PMS2",
}


# ── Dataclass de salida ───────────────────────────────────────────────────


@dataclass
class GermlineTestingRecommendation:
    """Recomendación estructurada de testing germinal NCCN PROS-H."""

    should_offer: bool
    priority: str  # "category_2A" | "consider" | "not_indicated"
    reasons: list[str] = field(default_factory=list)
    triggers_matched: list[dict[str, str]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    already_tested: bool = False
    known_pathogenic_variant: str | None = None
    family_counseling_recommended: bool = False
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helpers privados ──────────────────────────────────────────────────────


def _as_truthy(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "si", "sí", "positivo", "on", "category_2a"}


def _as_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _normalize_state(state: Any) -> str:
    if state is None:
        return ""
    return str(state).strip().lower()


def _normalize_risk_group(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _normalize_histology_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "_")


def _patient_has_metastasis(patient: dict[str, Any]) -> bool:
    metastasis_site = str(patient.get("metastasis_site") or "").strip().lower()
    if metastasis_site in {"bone", "node", "visceral", "m1", "m1a", "m1b", "m1c"}:
        return True
    m_stage = str(patient.get("clinical_m") or patient.get("m_stage") or "").strip().upper()
    if m_stage.startswith("M1"):
        return True
    if _as_truthy(patient.get("metastatic_disease")):
        return True
    bone_met_count = _as_int(patient.get("bone_metastasis_count") or patient.get("metastasis_count"))
    if bone_met_count and bone_met_count > 0:
        return True
    return False


def _has_intraductal_histology(patient: dict[str, Any]) -> bool:
    token_fields = (
        "histology_variant",
        "variant_histology",
        "intraductal_histology",
        "cribriform_histology",
        "ductal_histology",
        "primary_histology",
    )
    for key in token_fields:
        token = _normalize_histology_token(patient.get(key))
        if not token:
            continue
        for marker in INTRADUCTAL_HISTOLOGY_MARKERS:
            if marker in token:
                return True
    # Checkbox explícitos (EPIC 3 advanced_variant_histology_fields)
    for key in (
        "intraductal_carcinoma",
        "cribriform_present",
        "ductal_pattern_present",
        "any_cribriform",
        "any_intraductal",
    ):
        if _as_truthy(patient.get(key)):
            return True
    return False


def _family_history_positive(patient: dict[str, Any]) -> tuple[bool, list[str]]:
    """Evalúa criterios de historia familiar NCCN PROS-H."""
    reasons: list[str] = []
    if _as_truthy(patient.get("family_history_cancer")):
        reasons.append(
            "Historia familiar oncológica relevante declarada (family_history_cancer=1)"
        )
    tokens_raw = patient.get("family_history_conditions") or patient.get("family_history_tokens") or []
    if isinstance(tokens_raw, str):
        tokens = [t.strip().lower().replace(" ", "_") for t in tokens_raw.split(",")]
    elif isinstance(tokens_raw, (list, tuple, set)):
        tokens = [str(t).strip().lower().replace(" ", "_") for t in tokens_raw]
    else:
        tokens = []
    matched: list[str] = []
    for token in tokens:
        if token in FAMILY_HISTORY_TRIGGERS:
            matched.append(token)
    for trigger in matched:
        reasons.append(f"Historia familiar específica: {trigger}")
    return bool(reasons), reasons


def _very_high_risk_localized(patient: dict[str, Any]) -> bool:
    risk_group = _normalize_risk_group(patient.get("nccn_risk_group") or patient.get("risk_group"))
    if "VERY HIGH" in risk_group or risk_group == "VERY_HIGH":
        return True
    gleason = _as_int(patient.get("gleason_score") or patient.get("isup_total"))
    if gleason is not None and gleason >= 10:
        return True
    psa = _as_float(patient.get("psa") or patient.get("latest_psa"))
    if psa is not None and psa > 40:
        return True
    t_stage = str(patient.get("clinical_t") or patient.get("t_stage") or "").strip().upper()
    if t_stage in {"T3B", "T4", "CT3B", "CT4"}:
        return True
    if _as_int(patient.get("positive_cores_count")) and _as_int(patient.get("positive_cores_count")) >= 8:
        # Primary Gleason pattern 5 indirect — NCCN PROS-A
        pattern_primary = _as_int(patient.get("gleason_primary") or patient.get("gleason_pattern_primary"))
        if pattern_primary is not None and pattern_primary >= 5:
            return True
    return False


def _high_risk_localized(patient: dict[str, Any]) -> bool:
    risk_group = _normalize_risk_group(patient.get("nccn_risk_group") or patient.get("risk_group"))
    if "HIGH" in risk_group and "VERY" not in risk_group and "NOT" not in risk_group:
        return True
    gleason = _as_int(patient.get("gleason_score") or patient.get("isup_total"))
    if gleason is not None and gleason in {8, 9}:
        return True
    psa = _as_float(patient.get("psa") or patient.get("latest_psa"))
    if psa is not None and 20 <= psa <= 40:
        return True
    t_stage = str(patient.get("clinical_t") or patient.get("t_stage") or "").strip().upper()
    if t_stage in {"T3A", "CT3A"}:
        return True
    return False


def _age_under_threshold(patient: dict[str, Any], threshold: int = 55) -> bool:
    age = _as_int(patient.get("age") or patient.get("edad") or patient.get("age_at_diagnosis"))
    if age is None:
        return False
    return age < threshold


def _germline_already_tested(patient: dict[str, Any]) -> tuple[bool, str | None]:
    flag = str(patient.get("germline_testing_performed") or "").strip().lower()
    tested = flag in {"1", "true", "yes", "si", "sí", "performed", "done"}
    variant = patient.get("germline_pathogenic_variant")
    variant_clean: str | None = None
    if variant and str(variant).strip().lower() not in {
        "ninguna",
        "negative",
        "none",
        "desconocido",
        "unknown",
        "",
        "0",
    }:
        variant_clean = str(variant).strip()
    return tested, variant_clean


# ── Motor principal ───────────────────────────────────────────────────────


def should_offer_germline_testing(
    patient: dict[str, Any] | None,
) -> GermlineTestingRecommendation:
    """
    Evalúa los criterios NCCN PROS-H v5.2026 para recomendar testing germinal.

    Retorna una ``GermlineTestingRecommendation`` con:
      * ``should_offer=True`` con ``priority="category_2A"`` si el paciente cumple
        ≥1 criterio NCCN categoría 2A obligatorio.
      * ``should_offer=True`` con ``priority="consider"`` si hay señales
        accesorias (edad <55, ancestría Ashkenazi) sin criterio 2A claro.
      * ``should_offer=False`` con ``priority="not_indicated"`` si el testing
        ya se realizó o si no se cumple ningún trigger.
    """
    patient = patient or {}

    already_tested, known_variant = _germline_already_tested(patient)
    family_counseling = False
    triggers_matched: list[dict[str, str]] = []
    reasons: list[str] = []
    missing_inputs: list[str] = []
    evidence_tags: list[str] = ["nccn_pros_h"]

    # Si ya se realizó la prueba, no volver a ordenar; sólo proponer consejería
    # familiar cuando se detectó variante patogénica.
    if already_tested:
        reasons.append("Testing germinal previamente realizado — no requiere nueva orden")
        if known_variant and known_variant.upper() in PATHOGENIC_VARIANT_GENES:
            family_counseling = True
            reasons.append(
                f"Variante patogénica germinal confirmada ({known_variant}) — ofrecer "
                "consejería genética a familiares de primer grado (NCCN PROS-H)"
            )
        elif known_variant:
            reasons.append(
                f"Variante germinal declarada ({known_variant}) — confirmar patogenicidad "
                "clasificada por laboratorio"
            )
        return GermlineTestingRecommendation(
            should_offer=False,
            priority="not_indicated",
            reasons=reasons,
            triggers_matched=[],
            missing_inputs=[],
            already_tested=True,
            known_pathogenic_variant=known_variant,
            family_counseling_recommended=family_counseling,
            evidence_tags=evidence_tags + (["germline_variant_confirmed"] if family_counseling else []),
        )

    state = _normalize_state(patient.get("current_state"))

    # Trigger 1: enfermedad metastásica (category 2A)
    if _patient_has_metastasis(patient) or state in NCCN_HIGH_RISK_STATES:
        trigger = {
            "id": "metastatic_disease",
            "evidence": "NCCN PROS-H: enfermedad metastásica (any M1) exige testing germinal (category 2A).",
            "category": "category_2A",
        }
        triggers_matched.append(trigger)
        reasons.append("Enfermedad metastásica — criterio NCCN PROS-H category 2A")
        evidence_tags.append("metastatic_category_2a")

    # Trigger 2: very high risk localized (category 2A)
    if _very_high_risk_localized(patient):
        trigger = {
            "id": "very_high_risk_localized",
            "evidence": "NCCN PROS-H: riesgo muy alto (Gleason 10 / T3b-T4 / PSA>40) — testing germinal category 2A.",
            "category": "category_2A",
        }
        triggers_matched.append(trigger)
        reasons.append("Riesgo muy alto localizado — criterio NCCN PROS-H category 2A")
        evidence_tags.append("very_high_risk_category_2a")

    # Trigger 3: histología intraductal / ductal / cribiforme (category 2A cuando alto riesgo o peor)
    intraductal = _has_intraductal_histology(patient)
    high_risk = _high_risk_localized(patient)
    if intraductal:
        trigger_category = "category_2A" if (high_risk or _very_high_risk_localized(patient) or _patient_has_metastasis(patient)) else "consider"
        trigger = {
            "id": "intraductal_cribriform_histology",
            "evidence": "Giri VN 2020 Philadelphia Consensus + NCCN PROS-H: histología intraductal/ductal/cribiforme detona testing.",
            "category": trigger_category,
        }
        triggers_matched.append(trigger)
        reasons.append(
            "Histología intraductal/ductal/cribiforme — criterio NCCN PROS-H "
            f"({trigger_category})"
        )
        evidence_tags.append("intraductal_histology_trigger")

    # Trigger 4: historia familiar NCCN PROS-H
    fh_positive, fh_reasons = _family_history_positive(patient)
    if fh_positive:
        trigger = {
            "id": "family_history_nccn_pros_h",
            "evidence": "NCCN PROS-H: historia familiar relevante (próstata metastásica, mama, ovario, páncreas, colorrectal) — category 2A.",
            "category": "category_2A",
        }
        triggers_matched.append(trigger)
        reasons.extend(fh_reasons)
        evidence_tags.append("family_history_category_2a")

    # Trigger 5: somatic pathogenic variant detectada → confirmar germline
    somatic_variant = str(patient.get("somatic_pathogenic_variant") or "").strip()
    if somatic_variant and somatic_variant.upper() in PATHOGENIC_VARIANT_GENES:
        trigger = {
            "id": "somatic_pathogenic_variant_detected",
            "evidence": f"Variante somática patogénica ({somatic_variant}) obliga a confirmar germline (NCCN PROS-H, Pritchard NEJM 2016).",
            "category": "category_2A",
        }
        triggers_matched.append(trigger)
        reasons.append(
            f"Variante somática patogénica detectada ({somatic_variant}) — confirmar germline"
        )
        evidence_tags.append("somatic_variant_confirms_germline")

    # Trigger 6: edad <55 al diagnóstico (considerar)
    if _age_under_threshold(patient, threshold=55):
        trigger = {
            "id": "age_lt_55_at_diagnosis",
            "evidence": "Edad <55 al diagnóstico — considerar testing germinal (NCCN PROS-H nota)",
            "category": "consider",
        }
        triggers_matched.append(trigger)
        reasons.append("Edad <55 al diagnóstico — considerar testing germinal")
        evidence_tags.append("age_lt_55_consider")

    # Trigger 7: ancestría Ashkenazi documentada
    if _as_truthy(patient.get("ashkenazi_jewish_ancestry") or patient.get("ashkenazi_ancestry")):
        trigger = {
            "id": "ashkenazi_jewish_ancestry",
            "evidence": "Ancestría Ashkenazi judía — prevalencia elevada BRCA1/2 — considerar testing (NCCN PROS-H).",
            "category": "consider",
        }
        triggers_matched.append(trigger)
        reasons.append("Ancestría Ashkenazi judía documentada — considerar testing")
        evidence_tags.append("ashkenazi_consider")

    # Missing inputs que podrían refinar la decisión
    if not patient.get("family_history_cancer") and not patient.get("family_history_conditions"):
        missing_inputs.append("family_history_cancer")
    if not patient.get("age") and not patient.get("edad") and not patient.get("age_at_diagnosis"):
        missing_inputs.append("age_at_diagnosis")
    if not patient.get("histology_variant") and not patient.get("primary_histology"):
        missing_inputs.append("histology_variant")

    if not triggers_matched:
        return GermlineTestingRecommendation(
            should_offer=False,
            priority="not_indicated",
            reasons=["Sin criterios NCCN PROS-H activos en los campos disponibles"],
            triggers_matched=[],
            missing_inputs=missing_inputs,
            already_tested=False,
            known_pathogenic_variant=None,
            family_counseling_recommended=False,
            evidence_tags=evidence_tags,
        )

    # Prioridad global: category_2A domina
    any_cat2a = any(t["category"] == "category_2A" for t in triggers_matched)
    priority = "category_2A" if any_cat2a else "consider"

    return GermlineTestingRecommendation(
        should_offer=True,
        priority=priority,
        reasons=reasons,
        triggers_matched=triggers_matched,
        missing_inputs=missing_inputs,
        already_tested=False,
        known_pathogenic_variant=None,
        family_counseling_recommended=False,
        evidence_tags=evidence_tags,
    )


# ── Export ────────────────────────────────────────────────────────────────

__all__ = [
    "GermlineTestingRecommendation",
    "FAMILY_HISTORY_TRIGGERS",
    "INTRADUCTAL_HISTOLOGY_MARKERS",
    "NCCN_HIGH_RISK_STATES",
    "PATHOGENIC_VARIANT_GENES",
    "should_offer_germline_testing",
]
