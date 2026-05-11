from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


_MODEL_PATH = Path(__file__).resolve().parent / "assets" / "pcothercause_occam_models.json"
_MISSING_TOKENS = {
    "",
    "unknown",
    "desconocido",
    "desconocida",
    "no documentado",
    "not_used",
    "no_usar",
    "no usar",
}
_ESSENTIAL_OCCAM_FIELDS = [
    "age",
    "occam_height_cm",
    "occam_weight_kg",
    "occam_diabetes",
    "occam_hypertension",
    "occam_stroke",
    "occam_smoking_status",
]
_FIELD_LABELS_ES = {
    "age": "edad",
    "occam_height_cm": "talla",
    "occam_weight_kg": "peso",
    "occam_diabetes": "diabetes",
    "occam_hypertension": "hipertensión",
    "occam_stroke": "evento vascular cerebral previo",
    "occam_smoking_status": "tabaquismo",
    "occam_education": "escolaridad",
    "occam_marital_status": "estado civil",
    "ecog_score": "ECOG",
    "charlson_score": "índice de Charlson",
}
_VARIANT_LABELS_ES = {
    "full": "modelo completo",
    "no_education": "modelo sin escolaridad",
    "no_marital": "modelo sin estado civil",
    "reduced": "modelo reducido objetivo",
    "manual_fallback": "contexto manual heredado",
}
_EDUCATION_MAP = {
    "less_than_9th": "educ_lt9",
    "lt9": "educ_lt9",
    "9th_11th": "educ_9_11",
    "9_11": "educ_9_11",
    "9-11": "educ_9_11",
    "hs_graduate": "educ_hs",
    "high_school": "educ_hs",
    "hs": "educ_hs",
    "some_college": "educ_some",
    "college": "educ_college",
    "college_graduate": "educ_college",
}
_MARITAL_MAP = {
    "married": "married",
    "casado": "married",
    "union_libre": "married",
    "unión_libre": "married",
    "separated": "separated",
    "formerly_married": "separated",
    "previamente_casado": "separated",
    "single": "single",
    "never_married": "single",
    "nunca_casado": "single",
}
_SMOKING_MAP = {
    "never": "never",
    "nunca": "never",
    "current": "current",
    "actual": "current",
    "former": "former",
    "previo": "former",
}
_ECOG_FACTORS = {
    0: 1.0,
    1: 1.0,
    2: 0.85,
    3: 0.65,
    4: 0.45,
}


def _normalized_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_present(value: Any) -> bool:
    if value in (None, "", [], {}, "No documentado", "unknown", "UNKNOWN", "desconocido", "Desconocido"):
        return False
    return _normalized_key(value) not in _MISSING_TOKENS


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool_from_value(value: Any) -> bool | None:
    token = _normalized_key(value)
    if token in {"1", "true", "si", "sí", "yes"}:
        return True
    if token in {"0", "false", "no"}:
        return False
    return None


def _normalize_education(value: Any) -> str:
    token = _normalized_key(value).replace(" ", "_")
    if token in _MISSING_TOKENS:
        return ""
    return _EDUCATION_MAP.get(token, "")


def _normalize_marital(value: Any) -> str:
    token = _normalized_key(value).replace(" ", "_")
    if token in _MISSING_TOKENS:
        return ""
    return _MARITAL_MAP.get(token, "")


def _normalize_smoking(value: Any) -> str:
    token = _normalized_key(value).replace(" ", "_")
    return _SMOKING_MAP.get(token, "")


def _charlson_factor(charlson: int | None) -> float:
    if charlson is None:
        return 1.0
    if charlson >= 7:
        return 0.65
    if charlson >= 5:
        return 0.78
    if charlson >= 3:
        return 0.9
    return 1.0


@lru_cache(maxsize=1)
def load_pcothercause_occam_models() -> dict[str, Any]:
    return json.loads(_MODEL_PATH.read_text(encoding="utf-8"))


def pcothercause_widget_config() -> dict[str, Any]:
    config = load_pcothercause_occam_models()
    return {
        "source_repo": config.get("source_repo"),
        "source_model": config.get("source_model"),
        "instrument_locale": "es",
        "age_center": config.get("age_center"),
        "max_display_years": config.get("max_display_years", 15),
        "models": config.get("models", {}),
        "variant_labels_es": _VARIANT_LABELS_ES,
        "missing_field_labels_es": _FIELD_LABELS_ES,
        "ecog_factors": {str(key): value for key, value in _ECOG_FACTORS.items()},
        "charlson_factors": {
            "0_2": 1.0,
            "3_4": 0.9,
            "5_6": 0.78,
            "7_plus": 0.65,
        },
    }


def _survival_at_time(baseline_curve: list[list[float]], exponent: float, months: float) -> float:
    survival = baseline_curve[0][1] if baseline_curve else 1.0
    for time_point, baseline_survival in baseline_curve:
        if time_point > months:
            break
        survival = baseline_survival
    return float(survival) ** exponent


def _median_months(baseline_curve: list[list[float]], exponent: float, max_display_years: float) -> tuple[float, bool]:
    for time_point, baseline_survival in baseline_curve:
        if float(baseline_survival) ** exponent <= 0.5:
            return float(time_point), False
    return float(max_display_years) * 12.0, True


def _variant_for_payload(values: dict[str, Any]) -> str:
    has_education = bool(_normalize_education(values.get("occam_education")))
    has_marital = bool(_normalize_marital(values.get("occam_marital_status")))
    if has_education and has_marital:
        return "full"
    if has_education:
        return "no_marital"
    if has_marital:
        return "no_education"
    return "reduced"


def _build_linear_predictor_inputs(values: dict[str, Any], *, age_center: float, variant: str) -> dict[str, float] | None:
    age = _safe_float(values.get("age"))
    height_cm = _safe_float(values.get("occam_height_cm"))
    weight_kg = _safe_float(values.get("occam_weight_kg"))
    diabetic = _bool_from_value(values.get("occam_diabetes"))
    hypertension = _bool_from_value(values.get("occam_hypertension"))
    stroke = _bool_from_value(values.get("occam_stroke"))
    smoking = _normalize_smoking(values.get("occam_smoking_status"))

    essentials_missing = [
        field for field in _ESSENTIAL_OCCAM_FIELDS
        if not _is_present(values.get(field))
    ]
    if age is None or height_cm is None or weight_kg is None or diabetic is None or hypertension is None or stroke is None or not smoking or essentials_missing:
        return None

    height_m = height_cm / 100.0
    if height_m <= 0:
        return None
    bmi = weight_kg / (height_m ** 2)
    age_ctr = age - age_center
    features = {
        "age_ctr_40": age_ctr,
        "diabetic_yes": 1.0 if diabetic else 0.0,
        "hypertension_yes": 1.0 if hypertension else 0.0,
        "stroke_yes": 1.0 if stroke else 0.0,
        "pc_yes": 1.0,
        "underweight_yes": 1.0 if bmi < 18.5 else 0.0,
        "overweight2_yes": 1.0 if 25 <= bmi < 40 else 0.0,
        "obese2_yes": 1.0 if bmi >= 40 else 0.0,
        "smoker_current": 1.0 if smoking == "current" else 0.0,
        "smoker_former": 1.0 if smoking == "former" else 0.0,
        "age_x_diabetic": age_ctr * (1.0 if diabetic else 0.0),
        "age_x_hypertension": age_ctr * (1.0 if hypertension else 0.0),
        "age_x_stroke": age_ctr * (1.0 if stroke else 0.0),
    }
    education = _normalize_education(values.get("occam_education"))
    if variant in {"full", "no_marital"}:
        features.update(
            {
                "educ_9_11": 1.0 if education == "educ_9_11" else 0.0,
                "educ_hs": 1.0 if education == "educ_hs" else 0.0,
                "educ_some": 1.0 if education == "educ_some" else 0.0,
                "educ_college": 1.0 if education == "educ_college" else 0.0,
                "age_x_educ_9_11": age_ctr * (1.0 if education == "educ_9_11" else 0.0),
                "age_x_educ_hs": age_ctr * (1.0 if education == "educ_hs" else 0.0),
                "age_x_educ_some": age_ctr * (1.0 if education == "educ_some" else 0.0),
                "age_x_educ_college": age_ctr * (1.0 if education == "educ_college" else 0.0),
            }
        )
    marital = _normalize_marital(values.get("occam_marital_status"))
    if variant in {"full", "no_education"}:
        features.update(
            {
                "marital_separated": 1.0 if marital == "separated" else 0.0,
                "marital_single": 1.0 if marital == "single" else 0.0,
            }
        )
    features["occam_bmi"] = bmi
    return features


def build_pcothercause_life_expectancy_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    values = dict(field_values or {})
    models = load_pcothercause_occam_models()
    max_display_years = float(models.get("max_display_years", 15))
    manual_life_expectancy = _safe_float(values.get("life_expectancy_years"))
    missing_essential = [field for field in _ESSENTIAL_OCCAM_FIELDS if not _is_present(values.get(field))]
    if missing_essential and manual_life_expectancy is not None:
        return {
            "available": True,
            "source": "manual_fallback",
            "variant": "manual_fallback",
            "variant_label": _VARIANT_LABELS_ES["manual_fallback"],
            "life_expectancy_years": round(manual_life_expectancy, 1),
            "base_life_expectancy_years": round(manual_life_expectancy, 1),
            "five_year_other_cause_mortality": None,
            "ten_year_other_cause_mortality": None,
            "truncated_15_plus": False,
            "missing_inputs": missing_essential,
            "summary": "Se conserva la expectativa de vida manual heredada porque faltan entradas estructuradas para OCCAM.",
            "adjustment_reasons": [],
        }

    variant = _variant_for_payload(values)
    features = _build_linear_predictor_inputs(values, age_center=float(models["age_center"]), variant=variant)
    if features is None:
        return {
            "available": False,
            "source": "missing_occam_inputs",
            "variant": variant,
            "variant_label": _VARIANT_LABELS_ES[variant],
            "life_expectancy_years": manual_life_expectancy,
            "base_life_expectancy_years": manual_life_expectancy,
            "five_year_other_cause_mortality": None,
            "ten_year_other_cause_mortality": None,
            "truncated_15_plus": False,
            "missing_inputs": missing_essential,
            "summary": "Faltan variables estructuradas para calcular la expectativa de vida con OCCAM.",
            "adjustment_reasons": [],
        }

    model = models["models"][variant]
    coefficients: dict[str, float] = model["coefficients"]
    baseline_curve = model["baseline_survival"]
    linear_predictor = 0.0
    for feature_name, coefficient in coefficients.items():
        linear_predictor += float(coefficient) * float(features.get(feature_name, 0.0))
    exponent = float(math.exp(linear_predictor))

    five_year_survival = _survival_at_time(baseline_curve, exponent, 60.0)
    ten_year_survival = _survival_at_time(baseline_curve, exponent, 120.0)
    median_months, truncated = _median_months(baseline_curve, exponent, max_display_years)
    base_years = round(median_months / 12.0, 1)

    ecog = _safe_int(values.get("ecog_score"))
    charlson = _safe_int(values.get("charlson_score"))
    ecog_factor = _ECOG_FACTORS.get(ecog, 1.0)
    charlson_factor = _charlson_factor(charlson)
    final_years = round(max(0.5, base_years * ecog_factor * charlson_factor), 1)

    adjustment_reasons: list[str] = []
    if ecog is not None and ecog >= 2:
        adjustment_reasons.append(f"ECOG {ecog} reduce la expectativa pronóstica final frente al OCCAM basal.")
    if charlson is not None and charlson >= 3:
        adjustment_reasons.append(f"Charlson {charlson} reduce la expectativa pronóstica final frente al OCCAM basal.")

    risk5 = round(max(0.0, min(1.0, 1.0 - five_year_survival)), 4)
    risk10 = round(max(0.0, min(1.0, 1.0 - ten_year_survival)), 4)
    summary = (
        f"OCCAM público ({_VARIANT_LABELS_ES[variant]}) estima {base_years:g} años de expectativa de vida "
        f"y mortalidad por otras causas de {round(risk5 * 100):.0f}% a 5 años / {round(risk10 * 100):.0f}% a 10 años. "
        f"El ajuste final por ECOG/Charlson deja {final_years:g} años."
    )
    if truncated:
        summary = (
            f"OCCAM público ({_VARIANT_LABELS_ES[variant]}) supera el horizonte visible de {int(max_display_years)} años; "
            f"para la lógica de producto se registra {base_years:g}+ años y, tras ajustar por ECOG/Charlson, {final_years:g} años."
        )

    return {
        "available": True,
        "source": "pcothercause_public_repo",
        "variant": variant,
        "variant_label": _VARIANT_LABELS_ES[variant],
        "occam_bmi": round(float(features["occam_bmi"]), 1),
        "life_expectancy_years": final_years,
        "base_life_expectancy_years": base_years,
        "five_year_other_cause_mortality": risk5,
        "ten_year_other_cause_mortality": risk10,
        "truncated_15_plus": truncated,
        "missing_inputs": [],
        "summary": summary,
        "adjustment_reasons": adjustment_reasons,
    }


def apply_pcothercause_life_expectancy(field_values: dict[str, Any]) -> dict[str, Any]:
    values = dict(field_values or {})
    bundle = build_pcothercause_life_expectancy_bundle(values)
    values["occam_life_expectancy_bundle"] = bundle
    if bundle.get("available") and bundle.get("life_expectancy_years") is not None:
        values["life_expectancy_years"] = bundle["life_expectancy_years"]
    if bundle.get("base_life_expectancy_years") is not None:
        values["occam_base_life_expectancy_years"] = bundle["base_life_expectancy_years"]
    if bundle.get("five_year_other_cause_mortality") is not None:
        values["occam_5yr_other_cause_mortality"] = bundle["five_year_other_cause_mortality"]
    if bundle.get("ten_year_other_cause_mortality") is not None:
        values["occam_10yr_other_cause_mortality"] = bundle["ten_year_other_cause_mortality"]
    if bundle.get("variant"):
        values["occam_model_variant"] = bundle["variant"]
    values["occam_truncated_15_plus"] = "1" if bundle.get("truncated_15_plus") else "0"
    return values
