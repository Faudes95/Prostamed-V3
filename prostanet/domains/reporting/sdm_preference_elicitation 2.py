# -*- coding: utf-8 -*-
"""EPIC 7 — Elicitación estructurada de preferencias (SDM).

Complementa ``patient_priority_profile`` con un cuestionario breve tipo
Likert (5 ítems × 5 niveles) que captura los tradeoffs dominantes
respecto a:

1. Supervivencia vs carga de tratamiento.
2. Función urinaria vs certeza oncológica.
3. Función sexual vs certeza oncológica.
4. Quimioterapia vs terapia hormonal prolongada.
5. Ensayos clínicos vs estándar establecido.

Inspiración: Ottawa Decision Support Framework (O'Connor 1995), ICHOM
Standard Set para cáncer de próstata localizado, EPIC-26.

Retorna un mapa a las prioridades canónicas de ``tradeoff_engine`` y
pesos ajustados que alimentan la matriz SDM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Cuestionario canónico ──────────────────────────────────────────────

LIKERT_LEVELS = ("strongly_prefer_a", "prefer_a", "neutral", "prefer_b", "strongly_prefer_b")
LIKERT_LABELS_ES = {
    "strongly_prefer_a": "Definitivamente A",
    "prefer_a": "Prefiero A",
    "neutral": "Neutro",
    "prefer_b": "Prefiero B",
    "strongly_prefer_b": "Definitivamente B",
}
LIKERT_NUMERIC = {
    "strongly_prefer_a": -2,
    "prefer_a": -1,
    "neutral": 0,
    "prefer_b": 1,
    "strongly_prefer_b": 2,
}


ELICITATION_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "item_key": "cancer_control_vs_quality_of_life",
        "prompt_es": "Entre maximizar el control del cáncer (A) y preservar calidad de vida actual (B), ¿cuál refleja mejor su prioridad?",
        "option_a_label": "Control máximo",
        "option_b_label": "Calidad de vida actual",
        "priority_map_a": "maximize_cancer_control",
        "priority_map_b": "minimize_treatment_burden",
        "weight_a": 1.0,
        "weight_b": 1.0,
    },
    {
        "item_key": "urinary_function_vs_cancer_control",
        "prompt_es": "¿Aceptaría un riesgo mayor de incontinencia urinaria (A) a cambio de mejor control oncológico, o priorizaría mantener continencia (B)?",
        "option_a_label": "Acepto riesgo de incontinencia",
        "option_b_label": "Priorizo continencia",
        "priority_map_a": "maximize_cancer_control",
        "priority_map_b": "preserve_urinary_function",
        "weight_a": 0.8,
        "weight_b": 1.0,
    },
    {
        "item_key": "sexual_function_vs_cancer_control",
        "prompt_es": "¿Aceptaría mayor riesgo de disfunción eréctil (A) a cambio de mejor control, o priorizaría preservar la función sexual (B)?",
        "option_a_label": "Acepto riesgo sexual",
        "option_b_label": "Priorizo función sexual",
        "priority_map_a": "maximize_cancer_control",
        "priority_map_b": "preserve_sexual_function",
        "weight_a": 0.7,
        "weight_b": 1.0,
    },
    {
        "item_key": "chemo_vs_hormonal_extended",
        "prompt_es": "Si ambas son opciones: ¿preferiría quimioterapia de 6 meses (A) o terapia hormonal prolongada de 18-36 meses (B)?",
        "option_a_label": "Quimioterapia corta",
        "option_b_label": "Hormonal prolongada",
        "priority_map_a": "avoid_radiation",
        "priority_map_b": "minimize_treatment_burden",
        "weight_a": 0.5,
        "weight_b": 0.6,
    },
    {
        "item_key": "trial_vs_standard",
        "prompt_es": "¿Estaría abierto a participar en un ensayo clínico (A) o prefiere un tratamiento estándar establecido (B)?",
        "option_a_label": "Abierto a ensayo",
        "option_b_label": "Tratamiento estándar",
        "priority_map_a": "maximize_cancer_control",
        "priority_map_b": "minimize_treatment_burden",
        "weight_a": 0.4,
        "weight_b": 0.4,
    },
)


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ElicitationItem:
    item_key: str
    prompt_es: str
    option_a_label: str
    option_b_label: str
    priority_map_a: str
    priority_map_b: str
    levels: tuple[str, ...] = LIKERT_LEVELS
    level_labels_es: dict[str, str] = field(default_factory=lambda: dict(LIKERT_LABELS_ES))


@dataclass(frozen=True)
class ElicitationResult:
    items_evaluated: list[str]
    priority_weights: dict[str, float]
    ranked_priorities: list[str]
    unresolved_items: list[str] = field(default_factory=list)
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items_evaluated": list(self.items_evaluated),
            "priority_weights": dict(self.priority_weights),
            "ranked_priorities": list(self.ranked_priorities),
            "unresolved_items": list(self.unresolved_items),
            "narrative": self.narrative,
        }


# ── API pública ────────────────────────────────────────────────────────


def build_elicitation_form() -> list[dict[str, Any]]:
    """Retorna la lista de preguntas para renderizar en UI."""

    return [
        {
            "item_key": item["item_key"],
            "prompt_es": item["prompt_es"],
            "option_a_label": item["option_a_label"],
            "option_b_label": item["option_b_label"],
            "levels": list(LIKERT_LEVELS),
            "level_labels_es": dict(LIKERT_LABELS_ES),
        }
        for item in ELICITATION_ITEMS
    ]


def _normalize_answer(raw: Any) -> str | None:
    text = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    # aliases numéricos 1..5
    numeric_aliases = {
        "1": "strongly_prefer_a",
        "2": "prefer_a",
        "3": "neutral",
        "4": "prefer_b",
        "5": "strongly_prefer_b",
        "-2": "strongly_prefer_a",
        "-1": "prefer_a",
        "0": "neutral",
    }
    if text in numeric_aliases:
        return numeric_aliases[text]
    if text in LIKERT_LEVELS:
        return text
    # fallbacks suaves
    if text in {"a", "aa"}:
        return "strongly_prefer_a"
    if text in {"b", "bb"}:
        return "strongly_prefer_b"
    return None


def score_elicitation(answers: dict[str, Any]) -> ElicitationResult:
    """Convierte las respuestas Likert en pesos canónicos de prioridad.

    ``answers`` es un dict ``{item_key: nivel}``. Niveles aceptados:
    strongly_prefer_a, prefer_a, neutral, prefer_b, strongly_prefer_b
    (o los equivalentes numéricos 1..5 o -2..+2).
    """

    answers = answers or {}
    weights_accum: dict[str, float] = {}
    items_evaluated: list[str] = []
    unresolved: list[str] = []

    for item in ELICITATION_ITEMS:
        key = item["item_key"]
        level = _normalize_answer(answers.get(key))
        if level is None:
            unresolved.append(key)
            continue
        items_evaluated.append(key)
        numeric = LIKERT_NUMERIC.get(level, 0)
        if numeric < 0:
            priority = item["priority_map_a"]
            weight = abs(numeric) * float(item["weight_a"])
        elif numeric > 0:
            priority = item["priority_map_b"]
            weight = numeric * float(item["weight_b"])
        else:
            continue
        weights_accum[priority] = weights_accum.get(priority, 0.0) + weight

    # Normalizar pesos a [0, 1]
    max_weight = max(weights_accum.values(), default=0.0)
    normalized: dict[str, float] = {}
    if max_weight > 0:
        for priority, weight in weights_accum.items():
            normalized[priority] = round(weight / max_weight, 3)
    ranked = sorted(normalized.keys(), key=lambda p: normalized[p], reverse=True)

    narrative_parts: list[str] = []
    if ranked:
        from prostanet.domains.patient_tracking.tradeoff_engine import CANONICAL_PRIORITIES
        labels = [CANONICAL_PRIORITIES.get(p, p) for p in ranked[:3]]
        narrative_parts.append(
            "Prioridades dominantes elicidadas: " + ", ".join(labels) + "."
        )
    if unresolved:
        narrative_parts.append(
            f"{len(unresolved)} ítem(s) sin respuesta; complete para afinar la matriz SDM."
        )

    return ElicitationResult(
        items_evaluated=items_evaluated,
        priority_weights=normalized,
        ranked_priorities=ranked,
        unresolved_items=unresolved,
        narrative=" ".join(narrative_parts).strip(),
    )


def merge_elicited_with_free_text(
    elicitation: ElicitationResult,
    free_text_priorities: list[str] | None,
) -> list[str]:
    """Combina prioridades Likert con las de texto libre ya existentes.

    Preserva el orden: primero las explícitas de texto, luego las Likert
    no duplicadas. Sirve para retro-alimentar ``patient_priority_profile``
    sin sobre-escribir el input del paciente.
    """

    free_text_priorities = list(free_text_priorities or [])
    seen = set(free_text_priorities)
    combined = list(free_text_priorities)
    for priority in elicitation.ranked_priorities:
        if priority not in seen:
            combined.append(priority)
            seen.add(priority)
    return combined


__all__ = [
    "ELICITATION_ITEMS",
    "ElicitationItem",
    "ElicitationResult",
    "LIKERT_LABELS_ES",
    "LIKERT_LEVELS",
    "LIKERT_NUMERIC",
    "build_elicitation_form",
    "merge_elicited_with_free_text",
    "score_elicitation",
]
