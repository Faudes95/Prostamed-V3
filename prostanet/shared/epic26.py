from __future__ import annotations

import json
from typing import Any


EPIC26_INSTRUMENT_ID = "epic26"
EPIC26_INSTRUMENT_LOCALE = "es"
EPIC26_INSTRUMENT_VERSION = "EPIC-26-short-form"
EPIC26_LICENSE_VERSION = "es-licensed-centralized-v1"
EPIC26_MISSINGNESS_THRESHOLD = 0.20

EPIC26_DOMAIN_FIELD_MAP = {
    "urinary_incontinence": "epic26_urinary_incontinence_domain",
    "urinary_irritative_obstructive": "epic26_urinary_irritative_domain",
    "bowel": "epic26_bowel_domain",
    "sexual": "epic26_sexual_domain",
    "hormonal": "epic26_hormonal_domain",
}

EPIC26_STANDALONE_FIELD_MAP = {
    "overall_urinary_bother": "epic26_overall_urinary_bother",
}

EPIC26_LEGACY_ALIAS_FIELD = "epic26_urinary_domain"


def _choice(value: str, label: str, score: float) -> dict[str, Any]:
    return {
        "value": value,
        "label": label,
        "standardized_score": float(score),
    }


PROBLEM_SCALE = [
    _choice("none", "Ningún problema", 100),
    _choice("very_small", "Problema muy pequeño", 75),
    _choice("small", "Problema pequeño", 50),
    _choice("moderate", "Problema moderado", 25),
    _choice("big", "Problema grande", 0),
]

QUALITY_5_SCALE = [
    _choice("very_poor", "Muy mala", 0),
    _choice("poor", "Mala", 25),
    _choice("fair", "Regular", 50),
    _choice("good", "Buena", 75),
    _choice("very_good", "Muy buena", 100),
]

FREQUENCY_5_SCALE = [
    _choice("more_than_once_per_day", "Más de una vez al día", 0),
    _choice("about_once_per_day", "Aproximadamente una vez al día", 25),
    _choice("more_than_once_per_week", "Más de una vez por semana", 50),
    _choice("about_once_per_week", "Aproximadamente una vez por semana", 75),
    _choice("rarely_or_never", "Rara vez o nunca", 100),
]

URINARY_CONTROL_SCALE = [
    _choice("none", "Ningún control urinario", 0),
    _choice("frequent_dribbling", "Goteo frecuente", 33.3),
    _choice("occasional_dribbling", "Goteo ocasional", 66.7),
    _choice("total_control", "Control total", 100),
]

PADS_PER_DAY_SCALE = [
    _choice("three_or_more", "3 o más al día", 0),
    _choice("two_per_day", "2 al día", 33.3),
    _choice("one_per_day", "1 al día", 66.7),
    _choice("none", "Ninguno", 100),
]

SEXUAL_FUNCTION_SCALE = [
    _choice("none", "Ninguna", 0),
    _choice("very_poor", "Muy mala", 25),
    _choice("poor", "Mala", 50),
    _choice("fair", "Regular", 75),
    _choice("good", "Buena", 100),
]

ERECTION_QUALITY_SCALE = [
    _choice("none_at_all", "Ninguna", 0),
    _choice("not_firm_enough", "No lo suficientemente firme para ninguna actividad sexual", 33.3),
    _choice("firm_enough_not_intercourse", "Lo suficientemente firme para masturbación o caricias", 66.7),
    _choice("firm_enough_for_intercourse", "Lo suficientemente firme para el coito", 100),
]

SEXUAL_FREQUENCY_SCALE = [
    _choice("never", "Nunca", 0),
    _choice("a_few_times", "Pocas veces", 25),
    _choice("sometimes", "A veces", 50),
    _choice("most_times", "La mayoría de las veces", 75),
    _choice("whenever_wanted", "Siempre que lo quise", 100),
]


EPIC26_ITEM_CATALOG: list[dict[str, Any]] = [
    {
        "id": "ui1_leak_frequency",
        "group": "urinary_incontinence",
        "prompt": "Durante las últimas 4 semanas, ¿con qué frecuencia ha presentado goteo o escape de orina?",
        "what_it_evaluates": "Frecuencia de incontinencia urinaria.",
        "options": FREQUENCY_5_SCALE,
    },
    {
        "id": "ui2_urinary_control",
        "group": "urinary_incontinence",
        "prompt": "Durante las últimas 4 semanas, ¿cómo describiría su control urinario?",
        "what_it_evaluates": "Control urinario basal.",
        "options": URINARY_CONTROL_SCALE,
    },
    {
        "id": "ui3_pads_per_day",
        "group": "urinary_incontinence",
        "prompt": "Durante las últimas 4 semanas, ¿cuántos protectores o pañales utilizó por día para controlar el goteo o escape de orina?",
        "what_it_evaluates": "Necesidad de protectores por incontinencia.",
        "options": PADS_PER_DAY_SCALE,
    },
    {
        "id": "ui4_leaking_problem",
        "group": "urinary_incontinence",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el goteo o escape de orina?",
        "what_it_evaluates": "Molestia por incontinencia.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "uo1_pain_burning_urination",
        "group": "urinary_irritative_obstructive",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el dolor o ardor al orinar?",
        "what_it_evaluates": "Síntomas irritativos urinarios.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "uo2_bloody_urine",
        "group": "urinary_irritative_obstructive",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted la sangre en la orina?",
        "what_it_evaluates": "Hematuria percibida.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "uo3_weak_stream_incomplete_emptying",
        "group": "urinary_irritative_obstructive",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el chorro urinario débil o la sensación de vaciamiento incompleto?",
        "what_it_evaluates": "Componente obstructivo urinario.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "uo4_daytime_frequency",
        "group": "urinary_irritative_obstructive",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted la necesidad de orinar con frecuencia durante el día?",
        "what_it_evaluates": "Frecuencia urinaria diurna.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "u_overall_bother",
        "group": "overall_urinary_bother",
        "prompt": "En general, en las últimas 4 semanas, ¿qué tanto problema ha sido su función urinaria?",
        "what_it_evaluates": "Molestia urinaria global.",
        "standalone": True,
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b1_urgency",
        "group": "bowel",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted la urgencia para evacuar?",
        "what_it_evaluates": "Urgencia intestinal.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b2_frequency",
        "group": "bowel",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted evacuar con frecuencia?",
        "what_it_evaluates": "Frecuencia intestinal.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b3_losing_control",
        "group": "bowel",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted perder el control de las evacuaciones?",
        "what_it_evaluates": "Control intestinal.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b4_bloody_stools",
        "group": "bowel",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted tener evacuaciones con sangre?",
        "what_it_evaluates": "Sangrado rectal o intestinal percibido.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b5_painful_bowel_movements",
        "group": "bowel",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el dolor al evacuar?",
        "what_it_evaluates": "Dolor asociado a las evacuaciones.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "b6_overall_bowel_problem",
        "group": "bowel",
        "prompt": "En general, en las últimas 4 semanas, ¿qué tanto problema han sido sus hábitos intestinales?",
        "what_it_evaluates": "Molestia intestinal global.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "s1_ability_erection",
        "group": "sexual",
        "prompt": "Durante las últimas 4 semanas, ¿cómo calificaría su capacidad para lograr una erección?",
        "what_it_evaluates": "Capacidad eréctil basal.",
        "options": SEXUAL_FUNCTION_SCALE,
    },
    {
        "id": "s2_ability_orgasm",
        "group": "sexual",
        "prompt": "Durante las últimas 4 semanas, ¿cómo calificaría su capacidad para llegar al orgasmo?",
        "what_it_evaluates": "Capacidad orgásmica basal.",
        "options": SEXUAL_FUNCTION_SCALE,
    },
    {
        "id": "s3_erection_quality",
        "group": "sexual",
        "prompt": "Durante las últimas 4 semanas, ¿cómo describiría la calidad usual de sus erecciones?",
        "what_it_evaluates": "Calidad de la erección.",
        "options": ERECTION_QUALITY_SCALE,
    },
    {
        "id": "s4_erection_frequency",
        "group": "sexual",
        "prompt": "Durante las últimas 4 semanas, ¿con qué frecuencia sus erecciones han sido suficientes para la actividad sexual?",
        "what_it_evaluates": "Frecuencia de erecciones útiles.",
        "options": SEXUAL_FREQUENCY_SCALE,
    },
    {
        "id": "s5_overall_sexual_function",
        "group": "sexual",
        "prompt": "En general, durante las últimas 4 semanas, ¿cómo calificaría su función sexual?",
        "what_it_evaluates": "Función sexual global.",
        "options": QUALITY_5_SCALE,
    },
    {
        "id": "s6_sexual_problem",
        "group": "sexual",
        "prompt": "En general, en las últimas 4 semanas, ¿qué tanto problema ha sido para usted su función sexual?",
        "what_it_evaluates": "Molestia por función sexual.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "h1_hot_flashes",
        "group": "hormonal",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema han sido para usted los bochornos o sofocos?",
        "what_it_evaluates": "Carga hormonal autonómica.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "h2_breast_tenderness",
        "group": "hormonal",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el dolor o sensibilidad mamaria?",
        "what_it_evaluates": "Síntomas mamarios/hormonales.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "h3_feeling_depressed",
        "group": "hormonal",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted sentirse desanimado o deprimido?",
        "what_it_evaluates": "Carga afectiva relacionada con síntomas hormonales.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "h4_lack_of_energy",
        "group": "hormonal",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted la falta de energía?",
        "what_it_evaluates": "Fatiga o vitalidad basal.",
        "options": PROBLEM_SCALE,
    },
    {
        "id": "h5_change_in_body_weight",
        "group": "hormonal",
        "prompt": "En las últimas 4 semanas, ¿qué tanto problema ha sido para usted el cambio en el peso corporal?",
        "what_it_evaluates": "Impacto percibido de cambio ponderal.",
        "options": PROBLEM_SCALE,
    },
]


EPIC26_GROUPS = [
    {
        "id": "urinary_incontinence",
        "label": "Urinario: incontinencia",
        "description": "Captura escapes, control urinario y protectores.",
    },
    {
        "id": "urinary_irritative_obstructive",
        "label": "Urinario: irritativo/obstructivo",
        "description": "Captura ardor, hematuria, chorro débil y frecuencia diurna.",
    },
    {
        "id": "overall_urinary_bother",
        "label": "Molestia urinaria global",
        "description": "Ítem global visible; se captura pero no puntúa como dominio.",
        "standalone": True,
    },
    {
        "id": "bowel",
        "label": "Intestinal",
        "description": "Captura urgencia, frecuencia, control y dolor intestinal.",
    },
    {
        "id": "sexual",
        "label": "Sexual",
        "description": "Captura erección, orgasmo, frecuencia y molestia global.",
    },
    {
        "id": "hormonal",
        "label": "Hormonal",
        "description": "Captura bochornos, mastalgia, energía y síntomas afectivos.",
    },
]


def epic26_widget_config() -> dict[str, Any]:
    return {
        "instrument_id": EPIC26_INSTRUMENT_ID,
        "instrument_locale": EPIC26_INSTRUMENT_LOCALE,
        "instrument_version": EPIC26_INSTRUMENT_VERSION,
        "license_version": EPIC26_LICENSE_VERSION,
        "missingness_threshold": EPIC26_MISSINGNESS_THRESHOLD,
        "groups": EPIC26_GROUPS,
        "items": EPIC26_ITEM_CATALOG,
        "domain_field_map": dict(EPIC26_DOMAIN_FIELD_MAP),
        "standalone_field_map": dict(EPIC26_STANDALONE_FIELD_MAP),
        "legacy_alias_field": EPIC26_LEGACY_ALIAS_FIELD,
    }


def _item_map() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in EPIC26_ITEM_CATALOG}


def parse_epic26_response_packet(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        packet = dict(raw_value)
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return {}
        try:
            packet = json.loads(text)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    responses = packet.get("responses")
    if not isinstance(responses, dict):
        return {}
    cleaned = {
        "instrument_id": str(packet.get("instrument_id") or EPIC26_INSTRUMENT_ID),
        "instrument_locale": str(packet.get("instrument_locale") or EPIC26_INSTRUMENT_LOCALE),
        "instrument_version": str(packet.get("instrument_version") or EPIC26_INSTRUMENT_VERSION),
        "license_version": str(packet.get("license_version") or EPIC26_LICENSE_VERSION),
        "responses": {
            str(key): str(value)
            for key, value in responses.items()
            if value not in (None, "")
        },
    }
    return cleaned


def _response_score(item_id: str, response_value: Any) -> float | None:
    item = _item_map().get(item_id)
    if not item:
        return None
    raw = str(response_value or "").strip()
    for option in item.get("options") or []:
        if str(option.get("value")) == raw:
            return float(option.get("standardized_score"))
    return None


def _missing_summary(expected_item_ids: list[str], responses: dict[str, Any]) -> tuple[list[str], list[float]]:
    missing: list[str] = []
    scores: list[float] = []
    for item_id in expected_item_ids:
        score = _response_score(item_id, responses.get(item_id))
        if score is None:
            missing.append(item_id)
            continue
        scores.append(score)
    return missing, scores


def score_epic26_response_packet(raw_value: Any) -> dict[str, Any]:
    packet = parse_epic26_response_packet(raw_value)
    responses = dict(packet.get("responses") or {})
    if not responses:
        return {
            "available": False,
            "epic26_response_packet": {},
            "derived_scores": {},
            "completion_status_by_domain": {},
            "missing_items_by_domain": {},
            "scoring_version": EPIC26_INSTRUMENT_VERSION,
            "instrument_locale": EPIC26_INSTRUMENT_LOCALE,
            "instrument_version": EPIC26_INSTRUMENT_VERSION,
            "license_version": EPIC26_LICENSE_VERSION,
        }

    domain_items: dict[str, list[str]] = {
        group["id"]: [item["id"] for item in EPIC26_ITEM_CATALOG if item.get("group") == group["id"]]
        for group in EPIC26_GROUPS
        if not group.get("standalone")
    }
    standalone_items = {
        item["group"]: item["id"]
        for item in EPIC26_ITEM_CATALOG
        if item.get("standalone")
    }

    derived_scores: dict[str, Any] = {}
    completion_status_by_domain: dict[str, str] = {}
    missing_items_by_domain: dict[str, list[str]] = {}

    for domain_id, item_ids in domain_items.items():
        missing_items, scores = _missing_summary(item_ids, responses)
        missing_ratio = (len(missing_items) / len(item_ids)) if item_ids else 1.0
        field_name = EPIC26_DOMAIN_FIELD_MAP[domain_id]
        missing_items_by_domain[domain_id] = missing_items
        if not scores or missing_ratio > EPIC26_MISSINGNESS_THRESHOLD:
            derived_scores[field_name] = None
            completion_status_by_domain[domain_id] = "not_calculable"
            continue
        derived_scores[field_name] = round(sum(scores) / len(scores), 1)
        completion_status_by_domain[domain_id] = "complete" if not missing_items else "partial"

    for standalone_id, item_id in standalone_items.items():
        field_name = EPIC26_STANDALONE_FIELD_MAP[standalone_id]
        derived_scores[field_name] = _response_score(item_id, responses.get(item_id))

    urinary_components = [
        derived_scores.get(EPIC26_DOMAIN_FIELD_MAP["urinary_incontinence"]),
        derived_scores.get(EPIC26_DOMAIN_FIELD_MAP["urinary_irritative_obstructive"]),
    ]
    available_urinary_components = [float(score) for score in urinary_components if score is not None]
    derived_scores[EPIC26_LEGACY_ALIAS_FIELD] = (
        round(sum(available_urinary_components) / len(available_urinary_components), 1)
        if available_urinary_components
        else None
    )

    canonical_packet = {
        "instrument_id": packet.get("instrument_id") or EPIC26_INSTRUMENT_ID,
        "instrument_locale": packet.get("instrument_locale") or EPIC26_INSTRUMENT_LOCALE,
        "instrument_version": packet.get("instrument_version") or EPIC26_INSTRUMENT_VERSION,
        "license_version": packet.get("license_version") or EPIC26_LICENSE_VERSION,
        "responses": responses,
    }
    return {
        "available": True,
        "epic26_response_packet": canonical_packet,
        "derived_scores": derived_scores,
        "completion_status_by_domain": completion_status_by_domain,
        "missing_items_by_domain": missing_items_by_domain,
        "scoring_version": EPIC26_INSTRUMENT_VERSION,
        "instrument_locale": EPIC26_INSTRUMENT_LOCALE,
        "instrument_version": EPIC26_INSTRUMENT_VERSION,
        "license_version": EPIC26_LICENSE_VERSION,
    }


def normalize_epic26_payload(payload: dict[str, Any]) -> dict[str, Any]:
    values = dict(payload or {})
    scored = score_epic26_response_packet(values.get("epic26_response_packet"))
    if scored.get("available"):
        values["epic26_response_packet"] = scored["epic26_response_packet"]
        values.update(scored.get("derived_scores") or {})
        values["epic26_completion_status_by_domain"] = dict(scored.get("completion_status_by_domain") or {})
        values["epic26_missing_items_by_domain"] = dict(scored.get("missing_items_by_domain") or {})
        values["epic26_scoring_version"] = scored.get("scoring_version") or EPIC26_INSTRUMENT_VERSION
        values["epic26_instrument_locale"] = scored.get("instrument_locale") or EPIC26_INSTRUMENT_LOCALE
        values["epic26_instrument_version"] = scored.get("instrument_version") or EPIC26_INSTRUMENT_VERSION
        values["epic26_license_version"] = scored.get("license_version") or EPIC26_LICENSE_VERSION

    legacy_urinary = values.get(EPIC26_LEGACY_ALIAS_FIELD)
    if values.get("epic26_urinary_incontinence_domain") in (None, "") and legacy_urinary not in (None, ""):
        values["epic26_urinary_incontinence_domain"] = legacy_urinary
    if values.get("epic26_urinary_irritative_domain") in (None, "") and legacy_urinary not in (None, ""):
        values["epic26_urinary_irritative_domain"] = legacy_urinary

    urinary_fields = [
        values.get("epic26_urinary_incontinence_domain"),
        values.get("epic26_urinary_irritative_domain"),
    ]
    numeric_urinary_fields: list[float] = []
    for score in urinary_fields:
        try:
            if score not in (None, ""):
                numeric_urinary_fields.append(float(score))
        except (TypeError, ValueError):
            continue
    if numeric_urinary_fields:
        values[EPIC26_LEGACY_ALIAS_FIELD] = round(sum(numeric_urinary_fields) / len(numeric_urinary_fields), 1)

    epic_fields_present = any(
        values.get(field_name) not in (None, "")
        for field_name in [
            "epic26_response_packet",
            "epic26_urinary_incontinence_domain",
            "epic26_urinary_irritative_domain",
            "epic26_bowel_domain",
            "epic26_sexual_domain",
            "epic26_hormonal_domain",
            "epic26_overall_urinary_bother",
            EPIC26_LEGACY_ALIAS_FIELD,
        ]
    )
    if epic_fields_present:
        values.setdefault("epic26_instrument_locale", EPIC26_INSTRUMENT_LOCALE)
        values.setdefault("epic26_instrument_version", EPIC26_INSTRUMENT_VERSION)
        values.setdefault("epic26_license_version", EPIC26_LICENSE_VERSION)
    return values
