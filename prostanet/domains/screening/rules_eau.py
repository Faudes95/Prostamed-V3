# -*- coding: utf-8 -*-
"""EPIC 8 — Reglas EAU 2026 §5 para screening.

Alinea con NCCN Early Detection v2.2026 pero con algunos matices:
- EAU recomienda baseline PSA a los 45 años en hombres con riesgo estándar
  para establecer una base prospectiva (velocidad/doubling time).
- Para PSA < 1.0 ng/mL a los 45 años, el intervalo puede extenderse a 5
  años (8-year ERSPC cohort baseline).
- BRCA2 germinal o historia familiar de primer grado: PSA anual desde 40 años.

Evidencia:
- EAU 2026 Prostate Cancer Guidelines §5.1 Early detection
- Schroeder et al. NEJM 2009 (ERSPC 9-year)
- Carlsson S et al. J Urol 2015 (ERSPC cohort)
"""
from __future__ import annotations

from typing import Any

from prostanet.domains.screening.rules_nccn import (
    _effective_age,
    _ethnicity_is_high_risk,
    _family_history_is_high_risk,
    _family_history_is_any,
    _germline_is_brca2,
    _germline_is_positive,
    _to_float,
)


def classify_screening_eau(payload: dict) -> dict:
    age = _effective_age(payload)
    psa = _to_float(payload.get("psa_baseline_ng_ml"))
    last_psa = _to_float(payload.get("last_psa_ng_ml"), default=psa)
    life_expectancy = _to_float(payload.get("life_expectancy_years"), default=0.0)
    dre = str(payload.get("dre_baseline_finding") or "").lower()
    dre_suspicious = "sospechoso" in dre or "asimétrico" in dre

    reasons: list[str] = []
    derive_to_workup = False

    if _germline_is_brca2(payload):
        start_age = 40
        reasons.append(
            "EAU 2026 §5.1.1: BRCA2 — PSA anual desde los 40 años (IMPACT Nyberg 2020)."
        )
    elif _family_history_is_high_risk(payload) or _family_history_is_any(payload):
        start_age = 40
        reasons.append(
            "EAU 2026 §5.1.1: historia familiar primer grado — PSA anual desde los 40-45 años."
        )
    elif _ethnicity_is_high_risk(payload):
        start_age = 45
        reasons.append(
            "EAU 2026 §5.1.1: afrodescendiente — baseline PSA a los 45 años."
        )
    elif _germline_is_positive(payload):
        start_age = 45
        reasons.append(
            "EAU 2026 §5.1.1: variante germinal de riesgo (HOXB13/Lynch) — baseline a los 45 años."
        )
    else:
        start_age = 45
        reasons.append(
            "EAU 2026 §5.1.2: hombre de riesgo estándar — baseline PSA a los 45 años como referencia prospectiva (Schroeder NEJM 2009)."
        )

    # Determinar label y recommendation
    if age < start_age:
        label = f"Screening aún no indicado (edad objetivo EAU: {start_age} años)."
        recommendation = (
            f"Reevaluar a los {start_age} años. Educar al paciente sobre cuándo iniciar screening."
        )
        risk_group = "SCREENING_PRE_AGE_EAU"
    elif age < 70:
        label = "Screening EAU activo con decisión compartida."
        recommendation = (
            "Ofrecer PSA periódico con DRE opcional; intervalo personalizado según PSA basal y perfil de riesgo."
        )
        risk_group = "SCREENING_ACTIVE_EAU"
    elif age < 75 and life_expectancy >= 10:
        label = "Screening EAU individualizado en 70-74 años."
        recommendation = (
            "Considerar continuar sólo si hay expectativa de vida > 10 años y salud óptima; discutir explícitamente."
        )
        risk_group = "SCREENING_INDIVIDUALIZED_EAU"
    else:
        label = "EAU recomienda suspender screening."
        recommendation = (
            "No ofrecer PSA rutinario; enfocar en síntomas y calidad de vida."
        )
        risk_group = "SCREENING_STOP_EAU"

    # Intervalo según PSA basal
    if psa >= 3.0 or last_psa >= 3.0:
        interval_months = 0
        interval_text = "PSA ≥ 3.0 ng/mL: derivar a ruta diagnóstica."
        derive_to_workup = True
    elif psa >= 1.0:
        interval_months = 24 if not _family_history_is_high_risk(payload) else 12
        interval_text = f"PSA 1.0-3.0: screening cada {interval_months // 12}-2 años."
    else:
        if _germline_is_brca2(payload):
            interval_months = 12
            interval_text = "BRCA2 + PSA < 1.0: screening anual."
        else:
            interval_months = 48
            interval_text = "PSA < 1.0: screening cada 4-8 años (EAU Schroeder NEJM 2009)."

    if dre_suspicious:
        derive_to_workup = True
        reasons.append("DRE sospechoso: derivar a workup independientemente del PSA (EAU 2026 §5.2.3).")

    return {
        "label": label,
        "recommendation": recommendation,
        "risk_group": risk_group,
        "start_age_recommended": start_age,
        "effective_age": age,
        "interval_months": interval_months,
        "interval_text": interval_text,
        "derive_to_diagnostic_workup": derive_to_workup,
        "reasons": reasons,
    }
