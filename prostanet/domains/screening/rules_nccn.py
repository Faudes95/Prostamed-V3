# -*- coding: utf-8 -*-
"""EPIC 8 — Reglas NCCN Early Detection v2.2026 para screening.

Reglas canónicas:

- **Inicio screening**: 50 años (riesgo promedio), 45 años (afroamericanos,
  historia familiar primer grado), 40 años (BRCA2 germinal o familia
  cáncer temprano).
- **Intervalo por PSA basal**:
  * PSA < 1.0 ng/mL a los 45-49: cada 2-4 años.
  * PSA 1.0-3.0 ng/mL: cada 1-2 años (considerar densidad PSA si DRE normal).
  * PSA > 3.0 ng/mL: workup diagnóstico (mpMRI + densidad + biopsia selectiva).
- **Parar screening**: 75 años en general (USPSTF grado C 55-69, grado D ≥70).
  Si expectativa de vida > 10 años y salud excelente, continuar hasta 80.
- **Derivación a workup diagnóstico**: PSA > 3.0 ng/mL con confirmación,
  DRE sospechoso, o velocidad PSA > 0.75 ng/mL/año.

Categorías NCCN (Early Detection):
- ED-1: hombre < 40a → no screening salvo BRCA2 germinal conocido.
- ED-2: 40-49a con factor de riesgo (BRCA2, familia temprana, afro) → baseline PSA.
- ED-3: 50-74a → screening compartido con PSA + DRE.
- ED-4: ≥ 75a → sólo si expectativa vida > 10a y salud excelente.

Evidencia pivote:
- NCCN Prostate Cancer Early Detection v2.2026
- USPSTF Recommendation Statement. JAMA 2018;319:1901 (Grigorenko)
- Carter HB et al. J Urol 2013 (AUA baseline PSA)
- Pritchard CC et al. NEJM 2016 (BRCA2 risk)
- Nyberg T et al. Eur Urol 2020 (IMPACT study BRCA2)
"""
from __future__ import annotations

from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _ethnicity_is_high_risk(payload: dict) -> bool:
    text = str(payload.get("ethnicity_group") or "").lower()
    return any(token in text for token in ("afroamericano", "afrodescendiente", "negro"))


def _family_history_is_high_risk(payload: dict) -> bool:
    text = str(payload.get("family_history_cluster") or "").lower()
    return any(
        token in text
        for token in ("≥ 2", ">= 2", "metastásico", "brca", "lynch")
    )


def _family_history_is_any(payload: dict) -> bool:
    text = str(payload.get("family_history_cluster") or "").lower()
    return bool(text) and "sin historia familiar" not in text


def _germline_is_brca2(payload: dict) -> bool:
    text = str(payload.get("germline_known_status") or "").lower()
    return "brca2" in text


def _germline_is_positive(payload: dict) -> bool:
    text = str(payload.get("germline_known_status") or "").lower()
    return any(token in text for token in ("positivo", "lynch", "hoxb13"))


def _effective_age(payload: dict) -> float:
    age = _to_float(payload.get("age"))
    if age > 0:
        return age
    group = str(payload.get("screening_age_group") or "")
    if "< 40" in group:
        return 35
    if "40-44" in group:
        return 42
    if "45-49" in group:
        return 47
    if "50-54" in group:
        return 52
    if "55-69" in group:
        return 62
    if "70-74" in group:
        return 72
    if "≥ 75" in group or ">= 75" in group:
        return 77
    return 0.0


def _recommended_start_age(payload: dict) -> tuple[int, list[str]]:
    """Retorna (edad recomendada, razones de ajuste)."""
    reasons: list[str] = []
    start = 50
    if _germline_is_brca2(payload):
        start = 40
        reasons.append("BRCA2 germinal conocido: iniciar a los 40 años (IMPACT Nyberg 2020).")
    elif _germline_is_positive(payload):
        start = 45
        reasons.append("Variante germinal de alto riesgo: iniciar a los 45 años.")
    if _ethnicity_is_high_risk(payload) and start > 45:
        start = 45
        reasons.append("Afrodescendiente: iniciar a los 45 años (NCCN Early Detection v2.2026).")
    if _family_history_is_high_risk(payload) and start > 45:
        start = 45
        reasons.append("Cluster familiar de alto riesgo: iniciar a los 45 años.")
    elif _family_history_is_any(payload) and start > 45:
        start = 45
        reasons.append("Historia familiar primer grado: adelantar inicio a los 45 años.")
    return start, reasons


def _recommended_interval_months(payload: dict, psa: float) -> tuple[int, str]:
    """Retorna (intervalo en meses, narrativa)."""
    if psa >= 3.0:
        return 0, "PSA ≥ 3.0 ng/mL: derivar a workup diagnóstico (no reintervalo de screening)."
    if psa >= 1.0:
        # Más frecuente si alto riesgo
        if _germline_is_brca2(payload) or _family_history_is_high_risk(payload):
            return 12, "PSA 1.0-3.0 ng/mL + alto riesgo: screening anual."
        return 12, "PSA 1.0-3.0 ng/mL: screening anual."
    # PSA < 1.0
    if _germline_is_brca2(payload) or _family_history_is_high_risk(payload):
        return 12, "PSA < 1.0 ng/mL pero alto riesgo basal: screening anual de vigilancia."
    return 24, "PSA < 1.0 ng/mL en adulto medio-riesgo: screening cada 2 años."


def classify_screening_nccn(payload: dict) -> dict:
    age = _effective_age(payload)
    psa = _to_float(payload.get("psa_baseline_ng_ml"))
    last_psa = _to_float(payload.get("last_psa_ng_ml"), default=psa)
    life_expectancy = _to_float(payload.get("life_expectancy_years"), default=0.0)
    dre = str(payload.get("dre_baseline_finding") or "").lower()
    dre_suspicious = "sospechoso" in dre or "asimétrico" in dre

    start_age, start_reasons = _recommended_start_age(payload)
    reasons: list[str] = list(start_reasons)
    derive_to_workup = False
    workup_reasons: list[str] = []

    # Categoría NCCN Early Detection
    if age < 40:
        if _germline_is_brca2(payload):
            category = "ED-2"
            label = "Screening temprano indicado por BRCA2 germinal (< 40 a)."
            recommendation = "Iniciar PSA basal a los 40 años por BRCA2; considerar MRI prostática como complemento."
            risk_group = "SCREENING_BRCA2_EARLY"
        else:
            category = "ED-1"
            label = "Screening poblacional no indicado por edad."
            recommendation = "No ofrecer PSA rutinario; reevaluar al acercarse a los 40-45 años según perfil de riesgo."
            risk_group = "SCREENING_NOT_INDICATED"
    elif age < 50:
        # 40-49
        high_risk = (
            _germline_is_brca2(payload)
            or _ethnicity_is_high_risk(payload)
            or _family_history_is_high_risk(payload)
            or _family_history_is_any(payload)
        )
        if high_risk:
            category = "ED-2"
            label = "Screening temprano indicado por factor de riesgo."
            recommendation = (
                f"Iniciar screening basal a los {start_age} años con PSA + DRE. "
                "Discutir beneficios/daños en SDM estructurado."
            )
            risk_group = "SCREENING_HIGH_RISK_EARLY"
        else:
            category = "ED-1-borderline"
            label = "Screening individualizado 40-49 años sin factor de riesgo."
            recommendation = (
                "Discutir baseline PSA como referencia prospectiva; no es mandatorio si no hay factor de riesgo."
            )
            risk_group = "SCREENING_INDIVIDUALIZED"
    elif age < 75:
        category = "ED-3"
        label = "Screening estándar 50-74 años (decisión compartida)."
        recommendation = "Ofrecer PSA + DRE en decisión compartida; intervalo guiado por PSA basal."
        risk_group = "SCREENING_STANDARD"
    else:
        # ≥ 75
        if life_expectancy >= 10:
            category = "ED-4"
            label = "Screening extendido ≥ 75 con expectativa > 10 años y salud excelente."
            recommendation = (
                "Continuar screening sólo si hay expectativa de vida > 10 años y estado clínico excelente. "
                "Documentar decisión compartida (USPSTF grado D)."
            )
            risk_group = "SCREENING_EXTENDED_FRAGILE"
        else:
            category = "ED-5"
            label = "Screening no recomendado (≥ 75 con expectativa < 10 años)."
            recommendation = (
                "Suspender screening; enfocar en síntomas y calidad de vida (USPSTF grado D)."
            )
            risk_group = "SCREENING_STOP"

    # Workup referral gate (PSA, DRE)
    if psa >= 3.0 or last_psa >= 3.0:
        derive_to_workup = True
        workup_reasons.append(
            f"PSA {'basal' if psa >= 3.0 else 'reciente'} {(psa if psa >= 3.0 else last_psa):.2f} ng/mL ≥ 3.0: indicar workup diagnóstico."
        )
    if dre_suspicious:
        derive_to_workup = True
        workup_reasons.append("Tacto rectal sospechoso: indicar workup diagnóstico independientemente del PSA.")

    if not derive_to_workup:
        interval_months, interval_text = _recommended_interval_months(payload, psa)
    else:
        interval_months = 0
        interval_text = "Screening rutinario suspendido; el paciente entra a la ruta diagnóstica."

    if category == "ED-3" and not payload.get("informed_decision_ready"):
        reasons.append(
            "Pendiente discusión informada sobre beneficios/daños del screening antes de indicar PSA."
        )

    if start_age > age and category not in {"ED-1", "ED-2", "ED-1-borderline"}:
        reasons.append(
            f"Edad actual {age:.0f} años < edad recomendada de inicio ({start_age}); reservar screening al cumplir el umbral."
        )

    return {
        "category": category,
        "label": label,
        "recommendation": recommendation,
        "risk_group": risk_group,
        "start_age_recommended": start_age,
        "effective_age": age,
        "psa_baseline": psa,
        "derive_to_diagnostic_workup": derive_to_workup,
        "workup_reasons": workup_reasons,
        "interval_months": interval_months,
        "interval_text": interval_text,
        "reasons": reasons,
    }
