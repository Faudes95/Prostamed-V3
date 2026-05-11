# -*- coding: utf-8 -*-
"""
Rescate local post-radioterapia — selección entre salvage RP, HIFU, crioterapia,
braquiterapia de rescate y SBRT de rescate.

Evalúa candidacidad según:
  - Biopsia post-RT confirmando recidiva local
  - Intervalo desde RT (>=2 años recomendado)
  - PSA, PSADT (excluye enfermedad diseminada)
  - Localización, volumen y estadío local
  - Comorbilidad, expectativa de vida (≥10 años)
  - Riesgo de morbilidad (incontinencia severa, fístula rectouretral)
  - PSMA-PET con ausencia de metástasis

Referencias:
  NCCN 5.2026 (Local Salvage)
  EAU 2026 Local Salvage after RT
  Chade Eur Urol 2012 (salvage RP outcomes)
  Crouzet Eur Urol 2017 (salvage HIFU)
  Spiess Prostate Cancer 2010 (salvage cryo)
  Crook Brachytherapy 2019 (salvage BT)
"""
from __future__ import annotations

from typing import Any


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def evaluate_local_salvage_options(payload: dict) -> dict[str, Any]:
    biopsy_confirmed = _flag(payload, "local_recurrence_biopsy_confirmed") or _flag(payload, "post_rt_biopsy_positive")
    interval_months = _safe_float(payload.get("months_since_rt") or payload.get("interval_since_rt_months")) or 0
    psa = _safe_float(payload.get("psa"))
    psadt = _safe_float(payload.get("psadt_months"))
    metastasis_ruled_out = _flag(payload, "psma_pet_negative_distant") or str(payload.get("distant_metastasis", "0")) == "0"
    clinical_stage = str(payload.get("local_recurrence_stage") or payload.get("clinical_t_stage") or "").upper()
    prostate_volume = _safe_float(payload.get("prostate_volume_cc"))
    ecog = _safe_int(payload.get("ecog_score") or payload.get("ecog") or 0) or 0
    life_expectancy_years = _safe_float(payload.get("life_expectancy_years")) or 10

    incontinence_risk_high = _flag(payload, "incontinence_high_risk") or _flag(payload, "prior_turp")
    rectal_toxicity_history = _flag(payload, "rectal_toxicity_history") or _flag(payload, "prior_rectal_surgery")
    fistula_high_risk = rectal_toxicity_history or _flag(payload, "severe_radiation_proctitis")
    anticoagulation_active = _flag(payload, "chronic_anticoagulation")
    urinary_stricture = _flag(payload, "urinary_stricture_history")

    lesion_unilateral = _flag(payload, "lesion_unilateral") or str(payload.get("recurrence_laterality", "")).lower() in {"unilateral", "focal"}

    # Candidacy general
    general_candidate = (
        biopsy_confirmed
        and metastasis_ruled_out
        and interval_months >= 24
        and ecog <= 1
        and life_expectancy_years >= 10
        and (psa is None or psa < 10)
        and (psadt is None or psadt > 12)
    )

    options: list[dict[str, Any]] = []

    # ── Salvage RP ─────────────────────────────────────────────────────
    srp_blocks: list[str] = []
    if not general_candidate:
        srp_blocks.append("No cumple candidatura general (biopsia+, intervalo, PSA, sin metástasis, ECOG, expectativa).")
    if fistula_high_risk:
        srp_blocks.append("Alto riesgo de fístula rectouretral — preferir HIFU/crio focal si lesión accesible.")
    if clinical_stage.startswith("T4"):
        srp_blocks.append("Estadío T4 — morbilidad prohibitiva.")
    options.append({
        "regimen_code": "SALVAGE_RP",
        "drug_label": "Prostatectomía de rescate",
        "eligible": not srp_blocks,
        "priority": "preferred" if (not srp_blocks and clinical_stage in {"T1", "T1C", "T2", "T2A", "T2B", "T2C"}) else "eligible",
        "hard_blocks": srp_blocks,
        "expected_outcomes": {
            "cancer_specific_survival_10y": 0.70,
            "incontinence_any": 0.35,
            "erectile_dysfunction": 0.95,
            "rectourethral_fistula": 0.03,
        },
        "evidence_trials": ["Chade EurUrol 2012", "Mandel BJU 2016"],
        "rationale": (
            "Salvage RP es la opción con mejor control oncológico a largo plazo pero con mayor morbilidad "
            "(incontinencia, fístula). Mejores candidatos: joven, T≤2, PSA<10, cirujano experto."
        ),
    })

    # ── Salvage HIFU ───────────────────────────────────────────────────
    hifu_blocks: list[str] = []
    if not biopsy_confirmed:
        hifu_blocks.append("Requiere biopsia post-RT positiva.")
    if prostate_volume is not None and prostate_volume > 40:
        hifu_blocks.append(f"Volumen {prostate_volume:.0f} cc >40 cc — HIFU menos efectivo; considerar resección/TURP previa.")
    if interval_months < 24:
        hifu_blocks.append("Intervalo <24 meses desde RT — riesgo toxicidad aumentado.")
    if clinical_stage.startswith("T3") or clinical_stage.startswith("T4"):
        hifu_blocks.append("Enfermedad extracapsular/T3+ — HIFU no cubre márgenes peri-prostáticos.")
    options.append({
        "regimen_code": "SALVAGE_HIFU",
        "drug_label": "HIFU de rescate (focal o whole-gland)",
        "eligible": not hifu_blocks,
        "priority": "preferred" if (not hifu_blocks and lesion_unilateral) else "eligible",
        "hard_blocks": hifu_blocks,
        "expected_outcomes": {
            "biochemical_disease_free_5y": 0.48,
            "incontinence_any": 0.10,
            "erectile_dysfunction": 0.40,
            "rectourethral_fistula": 0.015,
        },
        "evidence_trials": ["Crouzet EurUrol 2017", "Ahmed LancetOnc 2012"],
        "rationale": (
            "HIFU focal es opción de preservación funcional en recurrencia unilateral o focal. "
            "Menor incontinencia y disfunción que salvage RP; requiere volumen glandular <40 cc."
        ),
    })

    # ── Salvage Crioterapia ────────────────────────────────────────────
    cryo_blocks: list[str] = []
    if not biopsy_confirmed:
        cryo_blocks.append("Requiere biopsia post-RT positiva.")
    if urinary_stricture:
        cryo_blocks.append("Antecedente de estenosis uretral — riesgo aumentado de retención/necrosis.")
    if clinical_stage.startswith("T4"):
        cryo_blocks.append("T4 fuera de ventana.")
    options.append({
        "regimen_code": "SALVAGE_CRYOTHERAPY",
        "drug_label": "Crioterapia de rescate (focal o whole-gland)",
        "eligible": not cryo_blocks,
        "priority": "preferred" if (not cryo_blocks and lesion_unilateral and fistula_high_risk) else "eligible",
        "hard_blocks": cryo_blocks,
        "expected_outcomes": {
            "biochemical_disease_free_5y": 0.55,
            "incontinence_any": 0.12,
            "erectile_dysfunction": 0.70,
            "rectourethral_fistula": 0.025,
        },
        "evidence_trials": ["Spiess Prostate Cancer 2010", "Williams Eur Urol 2011"],
        "rationale": (
            "Crioterapia focal útil en lesiones unilaterales accesibles, con menor riesgo de fístula que RP. "
            "Alta tasa de disfunción eréctil."
        ),
    })

    # ── Braquiterapia de rescate ───────────────────────────────────────
    brach_blocks: list[str] = []
    if not biopsy_confirmed:
        brach_blocks.append("Requiere biopsia post-RT positiva.")
    if interval_months < 30:
        brach_blocks.append("Intervalo <30 meses — toxicidad rectal/urinaria acumulada elevada.")
    if rectal_toxicity_history:
        brach_blocks.append("Toxicidad rectal prior — contraindicación relativa.")
    options.append({
        "regimen_code": "SALVAGE_BRACHYTHERAPY",
        "drug_label": "Braquiterapia de rescate (HDR preferida)",
        "eligible": not brach_blocks,
        "priority": "eligible",
        "hard_blocks": brach_blocks,
        "expected_outcomes": {
            "biochemical_disease_free_5y": 0.51,
            "urinary_grade3_toxicity": 0.13,
            "rectal_grade3_toxicity": 0.06,
        },
        "evidence_trials": ["Crook Brachytherapy 2019 (RTOG 0526)", "Chen IJROBP 2013"],
        "rationale": (
            "HDR salvage preferida sobre LDR por mejor dosimetría en tejido pre-irradiado. "
            "Requiere evaluación de dosis acumulada rectal/vesical."
        ),
    })

    # ── SBRT de rescate ────────────────────────────────────────────────
    sbrt_blocks: list[str] = []
    if not biopsy_confirmed:
        sbrt_blocks.append("Requiere biopsia post-RT positiva.")
    if interval_months < 36:
        sbrt_blocks.append("Intervalo <36 meses — toxicidad acumulada relevante.")
    options.append({
        "regimen_code": "SALVAGE_SBRT",
        "drug_label": "SBRT de rescate",
        "eligible": not sbrt_blocks,
        "priority": "eligible",
        "hard_blocks": sbrt_blocks,
        "expected_outcomes": {"biochemical_disease_free_3y": 0.50, "late_grade3_toxicity": 0.10},
        "evidence_trials": ["Fuller Pract Radiat Oncol 2020"],
        "rationale": "SBRT de rescate focal o whole-gland en centros experimentados; datos aún maduros.",
    })

    ranked = sorted(
        options,
        key=lambda o: (
            0 if o.get("priority") == "preferred" else (1 if o.get("priority") == "eligible" else 2),
            0 if o.get("eligible") else 1,
        ),
    )

    summary_narrative = _build_summary(general_candidate, biopsy_confirmed, interval_months, psa, psadt, metastasis_ruled_out)

    return {
        "local_salvage_options": ranked,
        "general_candidate_for_local_salvage": general_candidate,
        "candidacy_flags": {
            "biopsy_confirmed": biopsy_confirmed,
            "interval_months": interval_months,
            "psa": psa,
            "psadt_months": psadt,
            "metastasis_ruled_out": metastasis_ruled_out,
            "ecog": ecog,
            "life_expectancy_years": life_expectancy_years,
            "fistula_high_risk": fistula_high_risk,
            "incontinence_risk_high": incontinence_risk_high,
            "lesion_unilateral": lesion_unilateral,
        },
        "summary": summary_narrative,
    }


def _build_summary(candidate: bool, biopsy_confirmed: bool, interval: float, psa, psadt, mets_out: bool) -> str:
    if not biopsy_confirmed:
        return "Sin biopsia post-RT positiva no se puede ofrecer rescate local — priorizar re-estadificación (PSMA-PET + biopsia dirigida)."
    if not mets_out:
        return "Con metástasis activa o no descartada, priorizar tratamiento sistémico sobre rescate local."
    if not candidate:
        return "Paciente fuera de ventana de candidacy general — discutir sistémica y/o ensayo clínico."
    return (
        "Candidato a rescate local: comparar salvage RP (mejor control oncológico, mayor morbilidad), "
        "HIFU/crio (preservación funcional en enfermedad unilateral), braquiterapia HDR (opción "
        "selecta con dosimetría favorable), o SBRT de rescate (datos emergentes)."
    )
