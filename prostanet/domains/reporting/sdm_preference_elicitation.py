from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)

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


@dataclass(frozen=True)
class ElicitationItem:
    item_key: str
    prompt_es: str
    option_a_label: str
    option_b_label: str
    priority_map_a: str
    priority_map_b: str
    weight_a: float = 1.0
    weight_b: float = 1.0


@dataclass(frozen=True)
class ElicitationResult:
    priority_weights: dict[str, float] = field(default_factory=dict)
    items_evaluated: list[str] = field(default_factory=list)
    ranked_priorities: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    normalized_answers: dict[str, str] = field(default_factory=dict)
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_weights": dict(self.priority_weights),
            "items_evaluated": list(self.items_evaluated),
            "ranked_priorities": list(self.ranked_priorities),
            "unresolved_items": list(self.unresolved_items),
            "normalized_answers": dict(self.normalized_answers),
            "narrative": self.narrative,
        }


def build_elicitation_form() -> list[dict[str, Any]]:
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


def _normalize_answer(raw: Any) -> str:
    text = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
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
    if text in {"a", "aa"}:
        return "strongly_prefer_a"
    if text in {"b", "bb"}:
        return "strongly_prefer_b"
    return text if text in LIKERT_LEVELS else ""


def score_elicitation(answers: dict[str, Any]) -> ElicitationResult:
    weights_accum: dict[str, float] = {}
    normalized_answers: dict[str, str] = {}
    unresolved: list[str] = []
    items_evaluated: list[str] = []
    for item in ELICITATION_ITEMS:
        key = str(item["item_key"])
        answer = _normalize_answer((answers or {}).get(key))
        if not answer:
            unresolved.append(key)
            continue
        normalized_answers[key] = answer
        numeric = LIKERT_NUMERIC[answer]
        if numeric < 0:
            priority = str(item["priority_map_a"])
            weights_accum[priority] = weights_accum.get(priority, 0.0) + abs(numeric) * float(item["weight_a"])
        elif numeric > 0:
            priority = str(item["priority_map_b"])
            weights_accum[priority] = weights_accum.get(priority, 0.0) + abs(numeric) * float(item["weight_b"])
        items_evaluated.append(key)
    max_weight = max(weights_accum.values(), default=0.0)
    if max_weight > 0:
        weights_accum = {
            priority: round(weight / max_weight, 3)
            for priority, weight in weights_accum.items()
        }
    ranked = sorted(weights_accum.keys(), key=lambda priority: (-weights_accum[priority], priority))
    narrative_parts: list[str] = []
    if ranked:
        narrative_parts.append("Prioridades dominantes elicidadas: " + ", ".join(ranked[:3]) + ".")
    if unresolved:
        narrative_parts.append(f"{len(unresolved)} ítem(s) sin respuesta; complete para afinar la matriz SDM.")
    return ElicitationResult(
        priority_weights=weights_accum,
        items_evaluated=items_evaluated,
        ranked_priorities=ranked,
        unresolved_items=unresolved,
        normalized_answers=normalized_answers,
        narrative=" ".join(narrative_parts).strip(),
    )


def merge_elicited_with_free_text(
    elicitation: ElicitationResult | dict[str, Any],
    free_text_priorities: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if isinstance(elicitation, ElicitationResult):
        priority_weights = elicitation.priority_weights
        ranked_priorities = list(elicitation.ranked_priorities)
    else:
        priority_weights = dict(elicitation.get("priority_weights") or {})
        ranked_priorities = list(elicitation.get("ranked_priorities") or [])
    if not ranked_priorities:
        ranked_priorities = [
            key
            for key, _ in sorted(priority_weights.items(), key=lambda item: (-float(item[1]), item[0]))
            if key
        ]
    ordered: list[str] = []
    seen: set[str] = set()
    for priority in free_text_priorities or []:
        text = str(priority or "").strip()
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    for priority in ranked_priorities:
        text = str(priority or "").strip()
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


__all__ = [
    "ElicitationItem",
    "ElicitationResult",
    "build_elicitation_form",
    "score_elicitation",
    "merge_elicited_with_free_text",
]
