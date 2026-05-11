# -*- coding: utf-8 -*-
"""EPIC 7 — Motor de tradeoffs para decisión compartida (SDM).

Construye una matriz de *tradeoffs* entre las modalidades de tratamiento
localizado/avanzado, cruzando outcomes pivotales (supervivencia
cáncer-específica, metástasis, incontinencia, función sexual, carga
funcional) con las prioridades del paciente capturadas en
``patient_priority_profile``.

Fuentes pivotales (evidencia de nivel 1 / categoría NCCN 1):

- Hamdy FC et al. *NEJM* 2023;388:1547 — ProtecT 15 años (AS vs RP vs RT).
- Donovan JL et al. *NEJM* 2016;375:1425 — ProtecT patient-reported outcomes.
- Bill-Axelson A et al. *NEJM* 2014;370:932 — SPCG-4 18 años (RP vs WW).
- Wilt TJ et al. *NEJM* 2017;377:132 — PIVOT 19.5 años (RP vs observación).
- NCCN PROS-A v5.2026 — shared decision making framework.
- Klotz L et al. *JCO* 2015 — Canadian AS cohort outcomes.
- Stacey D et al. *Cochrane* 2017 — Decision aids para cáncer localizado.

Reglas de operación:

- Los outcomes se expresan por 100 pacientes a 15 años (ProtecT horizonte
  principal). Se documenta la fuente por cada dato.
- Cuando una modalidad no aplica por perfil clínico (p. ej., RP en
  ECOG≥3), se marca ``applicable=False`` con razón explícita.
- Las prioridades del paciente (canónicas) ponderan cada outcome y
  producen un ``alignment_score`` 0–100 por modalidad.
- Retorna una estructura serializable vía ``to_dict()`` para
  profile_compass + templates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Prioridades canónicas del paciente (compartidas con SDM) ────────────

CANONICAL_PRIORITIES = {
    "maximize_cancer_control": "Maximizar control del cáncer",
    "preserve_urinary_function": "Preservar función urinaria (continencia)",
    "preserve_sexual_function": "Preservar función sexual / eréctil",
    "avoid_bowel_toxicity": "Evitar toxicidad intestinal",
    "avoid_surgery": "Evitar cirugía",
    "avoid_radiation": "Evitar radiación",
    "minimize_treatment_burden": "Minimizar carga de tratamiento",
    "preserve_fertility": "Preservar fertilidad",
    "minimize_financial_toxicity": "Minimizar toxicidad financiera",
}


# ── Outcomes pivotales por modalidad (por 100 pacientes, horizonte 15 años) ──
# Los valores representan incidencia acumulada a 15 años o en el horizonte
# especificado. "urinary_incontinence_pad_use" y "erectile_dysfunction" son
# a 6 años (ProtecT patient-reported, más fiables que 15 años por sesgo
# de envejecimiento).

MODALITY_OUTCOMES: dict[str, dict[str, Any]] = {
    "active_surveillance": {
        "label": "Vigilancia activa",
        "applicable_risk_groups": ["very_low", "low", "favorable_intermediate"],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": 3,
            "metastasis_15y": 9,
            "urinary_incontinence_pad_use_6y": 6,
            "erectile_dysfunction_severe_6y": 15,
            "bowel_urgency_moderate_6y": 5,
            "treatment_related_anxiety_year1": 25,
            "switched_to_active_treatment_15y": 61,
        },
        "evidence_tags": ["protect_15y_hamdy_2023", "protect_pro_donovan_2016"],
        "primary_citation": "Hamdy NEJM 2023",
        "narrative_short": (
            "Mantiene función urinaria y sexual; 61 % pasa a tratamiento activo en 15 años. "
            "Mortalidad cáncer-específica y metástasis no son peores en la media del grupo ProtecT."
        ),
    },
    "radical_prostatectomy": {
        "label": "Prostatectomía radical",
        "applicable_risk_groups": [
            "very_low",
            "low",
            "favorable_intermediate",
            "unfavorable_intermediate",
            "high",
            "very_high",
        ],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": 2,
            "metastasis_15y": 5,
            "urinary_incontinence_pad_use_6y": 17,
            "erectile_dysfunction_severe_6y": 60,
            "bowel_urgency_moderate_6y": 3,
            "perioperative_complication_grade3_plus": 7,
            "salvage_radiation_15y": 22,
        },
        "evidence_tags": [
            "protect_15y_hamdy_2023",
            "spcg4_18y_bill_axelson_2014",
            "pivot_wilt_2017",
            "protect_pro_donovan_2016",
        ],
        "primary_citation": "Hamdy NEJM 2023 + SPCG-4 Bill-Axelson NEJM 2014",
        "narrative_short": (
            "Control patológico directo y PSA indetectable si negativo. Incontinencia y disfunción "
            "eréctil son los costos dominantes a 6 años. SPCG-4: NNT 8 para mortalidad a 18 años."
        ),
    },
    "radiation_therapy": {
        "label": "Radioterapia externa (± ADT)",
        "applicable_risk_groups": [
            "very_low",
            "low",
            "favorable_intermediate",
            "unfavorable_intermediate",
            "high",
            "very_high",
        ],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": 3,
            "metastasis_15y": 5,
            "urinary_incontinence_pad_use_6y": 4,
            "erectile_dysfunction_severe_6y": 55,
            "bowel_urgency_moderate_6y": 12,
            "adt_side_effects_when_combined": 65,
            "second_pelvic_malignancy_15y": 2,
        },
        "evidence_tags": ["protect_15y_hamdy_2023", "protect_pro_donovan_2016"],
        "primary_citation": "Hamdy NEJM 2023",
        "narrative_short": (
            "Ambulatoria; menor incontinencia que cirugía; mayor toxicidad intestinal y dependencia "
            "de ADT cuando se intensifica. Dificulta rescate quirúrgico si hay recurrencia."
        ),
    },
    "brachytherapy_monotherapy": {
        "label": "Braquiterapia (monoterapia LDR/HDR)",
        "applicable_risk_groups": ["very_low", "low", "favorable_intermediate"],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": 3,
            "metastasis_15y": 6,
            "urinary_incontinence_pad_use_6y": 3,
            "erectile_dysfunction_severe_6y": 45,
            "bowel_urgency_moderate_6y": 8,
            "urinary_retention_acute": 10,
        },
        "evidence_tags": ["nccn_pros_c", "ascende_rt_morris_2017"],
        "primary_citation": "NCCN PROS-C v5.2026",
        "narrative_short": (
            "Alternativa ambulatoria en próstatas sin obstrucción severa; menor incontinencia pero "
            "más síntomas urinarios irritativos; retención aguda en ~10 %."
        ),
    },
    "focal_therapy_hifu": {
        "label": "Terapia focal (HIFU / crioablación / TULSA)",
        "applicable_risk_groups": ["favorable_intermediate"],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": None,
            "metastasis_15y": None,
            "urinary_incontinence_pad_use_6y": 2,
            "erectile_dysfunction_severe_6y": 25,
            "bowel_urgency_moderate_6y": 1,
            "salvage_whole_gland_5y": 20,
            "re_focal_5y": 15,
        },
        "evidence_tags": ["stabile_eur_urol_2019", "guillaumier_eur_urol_2018", "klotz_j_urol_2021_tulsa"],
        "primary_citation": "Stabile Eur Urol 2019",
        "narrative_short": (
            "Reservado a intermedio favorable unilateral con lesión índice. Preserva función pero "
            "20 % requiere rescate de glándula entera a 5 años; evidencia aún nivel 2B NCCN."
        ),
    },
    "watchful_waiting_observation": {
        "label": "Observación / watchful waiting",
        "applicable_risk_groups": ["very_low", "low", "favorable_intermediate"],
        "outcomes_per_100": {
            "prostate_cancer_mortality_15y": 7,
            "metastasis_15y": 15,
            "urinary_incontinence_pad_use_6y": 2,
            "erectile_dysfunction_severe_6y": 15,
            "bowel_urgency_moderate_6y": 3,
            "palliative_adt_initiation_10y": 38,
        },
        "evidence_tags": ["pivot_wilt_2017", "spcg4_18y_bill_axelson_2014"],
        "primary_citation": "PIVOT Wilt NEJM 2017",
        "narrative_short": (
            "Apropiado para esperanza de vida ≤10 años o comorbilidad mayor. No requiere biopsias "
            "seriadas ni MRI regular; transición a ADT paliativo en ~38 % a 10 años."
        ),
    },
}


# ── Ponderación prioridad → outcome ────────────────────────────────────

# Cada prioridad canónica mapea a pesos (0-1) sobre los outcomes. El
# ``alignment_score`` es la suma ponderada de (1 - outcome_normalizado)
# cuando el outcome es "peor es mayor" (mortalidad, incontinencia, etc.).

PRIORITY_OUTCOME_WEIGHTS: dict[str, dict[str, float]] = {
    "maximize_cancer_control": {
        "prostate_cancer_mortality_15y": 1.0,
        "metastasis_15y": 0.8,
        "switched_to_active_treatment_15y": 0.3,
    },
    "preserve_urinary_function": {
        "urinary_incontinence_pad_use_6y": 1.0,
    },
    "preserve_sexual_function": {
        "erectile_dysfunction_severe_6y": 1.0,
    },
    "avoid_bowel_toxicity": {
        "bowel_urgency_moderate_6y": 1.0,
    },
    "avoid_surgery": {
        "perioperative_complication_grade3_plus": 1.0,
    },
    "avoid_radiation": {
        "second_pelvic_malignancy_15y": 1.0,
        "bowel_urgency_moderate_6y": 0.5,
    },
    "minimize_treatment_burden": {
        "salvage_radiation_15y": 0.6,
        "switched_to_active_treatment_15y": 0.5,
        "adt_side_effects_when_combined": 0.8,
        "re_focal_5y": 0.6,
        "salvage_whole_gland_5y": 0.6,
    },
}


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TradeoffRow:
    """Fila de tradeoff por modalidad."""

    modality_key: str
    modality_label: str
    applicable: bool
    applicable_reason: str
    outcomes_per_100: dict[str, Any] = field(default_factory=dict)
    alignment_score: float = 0.0
    priority_contribution: dict[str, float] = field(default_factory=dict)
    evidence_tags: list[str] = field(default_factory=list)
    primary_citation: str = ""
    narrative_short: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "modality_key": self.modality_key,
            "modality_label": self.modality_label,
            "applicable": self.applicable,
            "applicable_reason": self.applicable_reason,
            "outcomes_per_100": dict(self.outcomes_per_100),
            "alignment_score": round(self.alignment_score, 1),
            "priority_contribution": {k: round(v, 1) for k, v in self.priority_contribution.items()},
            "evidence_tags": list(self.evidence_tags),
            "primary_citation": self.primary_citation,
            "narrative_short": self.narrative_short,
        }


@dataclass(frozen=True)
class TradeoffMatrix:
    """Matriz completa serializable para UI."""

    risk_group_applied: str
    life_expectancy_band: str
    priorities_active: list[str]
    rows: list[TradeoffRow]
    top_recommendation: str
    top_recommendation_reason: str
    missing_inputs: list[str] = field(default_factory=list)
    evidence_citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_group_applied": self.risk_group_applied,
            "life_expectancy_band": self.life_expectancy_band,
            "priorities_active": list(self.priorities_active),
            "priorities_labels": [CANONICAL_PRIORITIES.get(p, p) for p in self.priorities_active],
            "rows": [row.to_dict() for row in self.rows],
            "top_recommendation": self.top_recommendation,
            "top_recommendation_reason": self.top_recommendation_reason,
            "missing_inputs": list(self.missing_inputs),
            "evidence_citations": list(self.evidence_citations),
        }


# ── Helpers internos ───────────────────────────────────────────────────


def _parse_priorities(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw if str(x).strip()]
    else:
        items = [token.strip().lower() for token in str(raw).replace(";", ",").split(",") if token.strip()]
    # Whitelist canónicas + normalización de sinónimos frecuentes.
    synonyms = {
        "curacion": "maximize_cancer_control",
        "curación": "maximize_cancer_control",
        "cure": "maximize_cancer_control",
        "continencia": "preserve_urinary_function",
        "urinary": "preserve_urinary_function",
        "funcion sexual": "preserve_sexual_function",
        "función sexual": "preserve_sexual_function",
        "sexual": "preserve_sexual_function",
        "intestino": "avoid_bowel_toxicity",
        "cirugia": "avoid_surgery",
        "cirugía": "avoid_surgery",
        "radiacion": "avoid_radiation",
        "radiación": "avoid_radiation",
        "calidad de vida": "minimize_treatment_burden",
        "carga": "minimize_treatment_burden",
    }
    resolved = []
    seen: set[str] = set()
    for token in items:
        canonical = token if token in CANONICAL_PRIORITIES else synonyms.get(token, "")
        if canonical and canonical not in seen:
            resolved.append(canonical)
            seen.add(canonical)
    return resolved


def _resolve_risk_group(patient: dict[str, Any]) -> str:
    for key in ("nccn_risk_group", "risk_group", "risk_stratification"):
        raw = patient.get(key)
        if raw in (None, ""):
            continue
        text = str(raw).strip().lower().replace(" ", "_")
        if "very_high" in text or "muy_alto" in text:
            return "very_high"
        if "high" in text or "alto" in text:
            return "high"
        if "unfavorable" in text or "desfavorable" in text:
            return "unfavorable_intermediate"
        if "favorable_intermediate" in text or "intermedio_favorable" in text or "favorable" in text:
            return "favorable_intermediate"
        if "intermediate" in text or "intermedio" in text:
            return "unfavorable_intermediate"
        if text in {"low", "bajo"}:
            return "low"
        if text in {"very_low", "muy_bajo"}:
            return "very_low"
    # fallback heurístico
    isup = patient.get("isup_grade")
    psa = patient.get("psa")
    try:
        isup_int = int(isup) if isup not in (None, "") else None
    except (TypeError, ValueError):
        isup_int = None
    try:
        psa_f = float(psa) if psa not in (None, "") else None
    except (TypeError, ValueError):
        psa_f = None
    if isup_int == 1 and psa_f is not None and psa_f < 10:
        return "low"
    if isup_int == 2 or (psa_f is not None and 10 <= psa_f <= 20):
        return "favorable_intermediate"
    if isup_int and isup_int >= 4:
        return "high"
    return "favorable_intermediate"


def _life_expectancy_band(patient: dict[str, Any]) -> str:
    try:
        years = float(patient.get("life_expectancy_years") or patient.get("life_expectancy") or 0)
    except (TypeError, ValueError):
        years = 0.0
    if years <= 0:
        return "unknown"
    if years <= 5:
        return "le_5_years"
    if years < 10:
        return "between_5_and_10_years"
    return "gt_10_years"


def _modality_applicable(
    modality_key: str,
    modality_data: dict[str, Any],
    risk_group: str,
    life_band: str,
    patient: dict[str, Any],
) -> tuple[bool, str]:
    applicable_groups = modality_data.get("applicable_risk_groups") or []
    if risk_group not in applicable_groups:
        return False, (
            f"No aplicable al grupo de riesgo NCCN {risk_group} según evidencia pivote."
        )
    ecog = patient.get("ecog_score")
    try:
        ecog_int = int(ecog) if ecog not in (None, "") else None
    except (TypeError, ValueError):
        ecog_int = None
    if modality_key == "radical_prostatectomy" and ecog_int is not None and ecog_int >= 3:
        return False, "ECOG ≥3 contraindica cirugía mayor."
    if modality_key == "radical_prostatectomy" and life_band == "le_5_years":
        return False, "Esperanza de vida ≤5 años favorece observación sobre cirugía radical."
    if modality_key == "focal_therapy_hifu":
        unilateral = str(patient.get("lesion_unilateral") or "").strip().lower()
        if unilateral and unilateral not in {"1", "true", "yes", "si"}:
            return False, "La terapia focal requiere lesión índice unilateral documentada."
    if modality_key == "watchful_waiting_observation" and life_band == "gt_10_years":
        return False, (
            "Observación/watchful waiting se reserva a esperanza de vida ≤10 años "
            "o comorbilidad mayor (NCCN PROS-C); con esperanza >10 años prefiera vigilancia activa."
        )
    return True, ""


def _alignment_score(
    outcomes: dict[str, Any],
    priorities: list[str],
) -> tuple[float, dict[str, float]]:
    """Retorna (score 0-100, contribución por prioridad)."""

    if not priorities:
        return 50.0, {}
    total = 0.0
    contributions: dict[str, float] = {}
    total_weight = 0.0
    for priority in priorities:
        weights = PRIORITY_OUTCOME_WEIGHTS.get(priority, {})
        if not weights:
            contributions[priority] = 0.0
            continue
        subtotal = 0.0
        subweight = 0.0
        for outcome_key, weight in weights.items():
            raw = outcomes.get(outcome_key)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            # Normalizamos a [0, 100]; invertimos porque todos son "peor es mayor".
            value_clamped = max(0.0, min(value, 100.0))
            subtotal += weight * (100.0 - value_clamped)
            subweight += weight
        if subweight > 0:
            partial = subtotal / subweight
            contributions[priority] = partial
            total += partial
            total_weight += 1.0
    score = total / total_weight if total_weight else 50.0
    return max(0.0, min(score, 100.0)), contributions


def _missing_inputs(patient: dict[str, Any], priorities: list[str]) -> list[str]:
    missing: list[str] = []
    if not priorities:
        missing.append("patient_priority_profile")
    for key in ("nccn_risk_group", "risk_group", "isup_grade"):
        if patient.get(key) not in (None, ""):
            break
    else:
        missing.append("nccn_risk_group")
    if patient.get("life_expectancy_years") in (None, ""):
        missing.append("life_expectancy_years")
    return missing


# ── API pública ────────────────────────────────────────────────────────


def build_tradeoff_matrix(patient: dict[str, Any]) -> TradeoffMatrix:
    """Construye la matriz SDM para el paciente.

    No muta la entrada. Si faltan inputs, emite ``missing_inputs`` para
    que ``decision_input_requirements_engine`` la levante en UI.
    """

    priorities = _parse_priorities(
        patient.get("patient_priority_profile")
        or patient.get("priority_profile")
        or patient.get("patient_priorities")
    )
    risk_group = _resolve_risk_group(patient)
    life_band = _life_expectancy_band(patient)

    rows: list[TradeoffRow] = []
    evidence_citations: set[str] = set()
    for modality_key, modality_data in MODALITY_OUTCOMES.items():
        applicable, reason = _modality_applicable(
            modality_key, modality_data, risk_group, life_band, patient
        )
        outcomes = dict(modality_data.get("outcomes_per_100") or {})
        score, contributions = _alignment_score(outcomes, priorities)
        rows.append(
            TradeoffRow(
                modality_key=modality_key,
                modality_label=str(modality_data.get("label") or modality_key),
                applicable=applicable,
                applicable_reason=reason,
                outcomes_per_100=outcomes,
                alignment_score=score if applicable else 0.0,
                priority_contribution=contributions if applicable else {},
                evidence_tags=list(modality_data.get("evidence_tags") or []),
                primary_citation=str(modality_data.get("primary_citation") or ""),
                narrative_short=str(modality_data.get("narrative_short") or ""),
            )
        )
        evidence_citations.update(modality_data.get("evidence_tags") or [])

    applicable_rows = [row for row in rows if row.applicable]
    if applicable_rows:
        top = max(applicable_rows, key=lambda row: row.alignment_score)
        top_key = top.modality_key
        if priorities:
            reason = (
                f"Alinea mejor con prioridades del paciente: {', '.join(CANONICAL_PRIORITIES.get(p, p) for p in priorities)}."
            )
        else:
            reason = (
                "Sin prioridades explícitas; recomendación por defecto basada en menor carga de tratamiento."
            )
    else:
        top_key = ""
        reason = "No hay modalidades aplicables al perfil del paciente."

    return TradeoffMatrix(
        risk_group_applied=risk_group,
        life_expectancy_band=life_band,
        priorities_active=priorities,
        rows=rows,
        top_recommendation=top_key,
        top_recommendation_reason=reason,
        missing_inputs=_missing_inputs(patient, priorities),
        evidence_citations=sorted(evidence_citations),
    )


__all__ = [
    "CANONICAL_PRIORITIES",
    "MODALITY_OUTCOMES",
    "PRIORITY_OUTCOME_WEIGHTS",
    "TradeoffMatrix",
    "TradeoffRow",
    "build_tradeoff_matrix",
]
