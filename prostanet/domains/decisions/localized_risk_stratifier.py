"""localized_risk_stratifier.py — EPIC 49+.B (FAUBOT CXLVII).

Stratifier para cáncer de próstata LOCALIZADO siguiendo NCCN PROS-1 v5.2026.

Cierra HX2 detectada en validación EXTENSA okarbo:
  Casos K (intermedio favorable mestizo CDMX) y R (alto riesgo joven hereditario)
  NO disparaban NINGÚN gate ni recibían recomendación específica por risk group.
  Sistema asumía mCRPC/mHSPC como default — localized risk stratification estaba ausente.

NCCN risk groups (PROS-1):
  - very_low      : T1c + Gleason ≤6 + PSA <10 + <3 cores + ≤50%/core + PSAD <0.15
  - low           : T1-T2a + Gleason ≤6 + PSA <10
  - favorable_intermediate   : 1 IRF + Gleason 3+4 (ISUP 2) + <50% biopsy cores positive
  - unfavorable_intermediate : 2-3 IRFs OR Gleason 4+3 (ISUP 3) OR ≥50% cores
  - high          : T3a OR Gleason 8 OR PSA >20
  - very_high     : T3b-T4 OR primary Gleason 5 OR >4 cores ISUP 4-5 OR 2+ HR features

Donde IRF (intermediate risk factor):
  - cT2b-T2c
  - Gleason 3+4 (ISUP 2) or 4+3 (ISUP 3)
  - PSA 10-20

Cada risk group tiene recomendaciones de tratamiento NCCN PROS-2 explícitas que
exponemos para que el engine y la UI las muestren coherentemente.

Beneficio clínico tangible:
  - Paciente localized recibe risk_group classificado + recomendación específica
  - Active surveillance correctamente ofrecido a very_low/low/favorable_intermediate
  - High/very_high reciben recomendación de tx multimodal agresivo
  - Cierra brecha de visión "cada paciente recibe recomendación con evidencia"
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Catálogo recomendaciones NCCN PROS-2 ─────────────────────────────────


RECOMMENDATIONS_BY_RISK_GROUP = {
    "very_low": {
        "primary_option": "active_surveillance",
        "alternatives": ["radical_prostatectomy_nerve_sparing", "external_beam_rt", "brachytherapy_low_dose"],
        "rationale": (
            "Active surveillance es estándar (NCCN PROS-2 cat 1): "
            "riesgo muy bajo de progresión a 10-15 años. RP/RT solo si "
            "preferencia del paciente o reclasificación durante AS."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "PROTECT trial (NCT02044172)"],
        "follow_up_interval_months": 6,
    },
    "low": {
        "primary_option": "active_surveillance",
        "alternatives": ["radical_prostatectomy_nerve_sparing", "external_beam_rt", "brachytherapy"],
        "rationale": (
            "Active surveillance preferible si expectativa de vida ≥10 años "
            "y paciente acepta seguimiento. RP o RT como alternativas según "
            "preferencias función eréctil/continencia."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "PROTECT trial"],
        "follow_up_interval_months": 6,
    },
    "favorable_intermediate": {
        "primary_option": "active_surveillance_select_or_definitive",
        "alternatives": ["radical_prostatectomy", "external_beam_rt_short_adt", "brachytherapy_combo"],
        "rationale": (
            "AS posible si Decipher score bajo + paciente bien informado; "
            "definitivo (RP o RT+ADT corto 4-6m) para mayoría. SDM crítico."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "EORTC 22991", "RTOG 9408"],
        "follow_up_interval_months": 6,
    },
    "unfavorable_intermediate": {
        "primary_option": "definitive_treatment_required",
        "alternatives": ["radical_prostatectomy_extended_lnd", "external_beam_rt_long_adt", "brachytherapy_boost_combo"],
        "rationale": (
            "Tx definitivo requerido. RP con linfadenectomía extendida O "
            "RT + ADT 4-6m. Consider Decipher para refinar decisión."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "RTOG 9408", "DART01.05 GICOR"],
        "follow_up_interval_months": 4,
    },
    "high": {
        "primary_option": "multimodal_aggressive",
        "alternatives": ["rp_plus_adjuvant_consideration", "ebrt_plus_adt_18_36_months", "brachytherapy_boost_combo"],
        "rationale": (
            "Tx multimodal recomendado: RP + linfadenectomía extendida con "
            "consideración RT adyuvante si pT3/margins/pN+; O RT + ADT 18-36m. "
            "Brachy boost (HDR/LDR) combinado RT mejora bDFS (RTOG 0539)."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "EORTC 22863", "STAMPEDE-RT", "RTOG 0539"],
        "follow_up_interval_months": 3,
    },
    "very_high": {
        "primary_option": "multimodal_intensive_plus_systemic",
        "alternatives": ["rp_extended_lnd_plus_adjuvant_rt_adt", "ebrt_plus_adt_24_36_months_plus_abiraterone"],
        "rationale": (
            "Tx multimodal INTENSIVO + sistémico. RP/RT + ADT 24-36m + "
            "ABIRATERONA (STAMPEDE: HR mortalidad 0.63 en very high risk). "
            "Considerar reclutamiento ensayo clínico."
        ),
        "evidence_anchors": ["NCCN PROS-2 cat 1", "STAMPEDE arm G (abiraterone)",
                              "PROTEUS NCT03767244 (neoadjuvant apalutamide)"],
        "follow_up_interval_months": 3,
    },
}


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _gleason_isup(gleason: str | None, isup: int | None) -> int:
    """Returns ISUP grade group (1-5) from gleason string or explicit isup."""
    if isup is not None:
        return max(1, min(5, int(isup)))
    if not gleason:
        return 0
    g = str(gleason).strip().lower().replace(" ", "")
    # Parse "3+3=6", "4+3=7", "4+4=8", "4+5=9", "5+5=10"
    if "+" in g:
        primary, secondary = g.split("+", 1)
        try:
            p = int(primary[:1])
            s = int(secondary[:1])
        except (ValueError, IndexError):
            return 0
        total = p + s
        if total <= 6:
            return 1
        if p == 3 and s == 4:
            return 2
        if p == 4 and s == 3:
            return 3
        if total == 8:
            return 4
        if total >= 9:
            return 5
    return 0


def _t_stage_value(stage_str: str | None) -> tuple[str, int]:
    """Returns (T_letter, T_number) — e.g. "cT2b" → ('T2', 2)."""
    if not stage_str:
        return ("T0", 0)
    s = str(stage_str).strip().upper()
    # Look for T[0-4]
    for prefix in ("T4", "T3", "T2", "T1", "T0"):
        if prefix in s:
            # Get optional letter (a/b/c)
            idx = s.find(prefix)
            after = s[idx+2:idx+3]
            num = int(prefix[1])
            return (prefix, num * 10 + (ord(after.lower()) - ord('a') + 1 if after.isalpha() else 0))
    return ("T0", 0)


# ── Public API ────────────────────────────────────────────────────────


def is_localized(patient: dict[str, Any]) -> bool:
    """Determina si el paciente está en disease state LOCALIZADO (M0, no node distant).

    Inspecciona stage + tnm_stage + clinical_stage + disease_state (concatenando)
    para captura robusta del estadio."""
    baseline = patient.get("baseline") or {}
    stage_blob = " ".join(str(
        baseline.get(k) or "") for k in (
        "stage", "tnm_stage", "clinical_stage", "disease_state"
    )).lower()
    # Excluir M1/mCRPC/mHSPC/BCR/recurrence
    if any(kw in stage_blob for kw in ("mcrpc", "mhspc", "metast", "bcr", "recurr", "m1")):
        return False
    return any(kw in stage_blob for kw in (
        "localized", "m0", "ct1", "ct2", "ct3a", "ct3b_high_risk"
    ))


def stratify_localized_risk(patient: dict[str, Any]) -> dict[str, Any]:
    """Clasifica paciente LOCALIZADO según NCCN PROS-1 risk groups.

    Returns:
        {
            "applicable": bool — True si paciente es localized + datos suficientes
            "risk_group": str (very_low|low|favorable_intermediate|unfavorable_intermediate|high|very_high)
            "irf_count": int — número de intermediate risk factors presentes
            "criteria_met": list[str] — criterios que disparan el grupo
            "recommendation": dict — primary + alternatives + rationale + evidence + follow_up
            "missing_data": list[str] — campos faltantes para refinar
        }
    """
    if not is_localized(patient):
        return {
            "applicable": False,
            "reason": "not_localized_stage",
            "patient_stage_inferred": str((patient.get("baseline") or {}).get("stage") or "unknown"),
        }

    baseline = patient.get("baseline") or {}
    psa = _safe_float(baseline.get("baseline_psa") or baseline.get("psa_current")
                       or baseline.get("psa_at_diagnosis"))
    gleason = baseline.get("gleason_score") or baseline.get("gleason_pattern")
    isup_raw = _safe_int(baseline.get("isup_grade") or baseline.get("gleason_isup_at_diagnosis"))
    isup = _gleason_isup(gleason, isup_raw)
    # Priorizar clinical_stage (T-letter explícito) sobre stage (que puede ser
    # descriptor categórico tipo "localized_intermediate_favorable" sin T)
    stage_candidates = [
        baseline.get("clinical_stage"),
        baseline.get("tnm_stage"),
        baseline.get("stage"),
    ]
    t_letter, t_score = "T0", 0
    for cand in stage_candidates:
        if cand:
            t_letter, t_score = _t_stage_value(str(cand))
            if t_score > 0:
                break
    psa_density = _safe_float(baseline.get("psa_density"))
    biopsy_cores_total = _safe_int(baseline.get("biopsy_cores_total"))
    biopsy_cores_positive = _safe_int(baseline.get("biopsy_cores_positive"))
    percent_cores_positive = _safe_float(baseline.get("percent_cores_positive"))
    max_cancer_length = _safe_float(baseline.get("max_cancer_length_per_core_mm"))
    cribriform = bool(baseline.get("cribriform_pattern"))
    intraductal = bool(baseline.get("intraductal_carcinoma"))
    lvi = bool(baseline.get("lvi_on_biopsy"))

    missing: list[str] = []
    if psa is None: missing.append("baseline_psa")
    if isup == 0: missing.append("gleason_score_or_isup")
    if t_score == 0: missing.append("clinical_stage_tnm")
    if biopsy_cores_total is None: missing.append("biopsy_cores_total")
    if biopsy_cores_positive is None: missing.append("biopsy_cores_positive")

    if missing:
        return {
            "applicable": True,
            "risk_group": "insufficient_data",
            "missing_data": missing,
            "recommendation": {
                "primary_option": "complete_workup_required",
                "rationale": (
                    f"Faltan datos clave para risk stratification NCCN PROS-1: "
                    f"{', '.join(missing)}. Completar antes de decisión tx."
                ),
            },
        }

    criteria_met: list[str] = []

    # VERY_HIGH risk
    if (t_letter in ("T3", "T4") and t_score >= 32) or \
       (isup == 5) or \
       (biopsy_cores_positive is not None and biopsy_cores_positive > 4 and isup >= 4) or \
       (cribriform and intraductal) or \
       (cribriform and lvi):
        criteria_met.append(f"T={t_letter} or ISUP 5 or extensive ISUP 4-5 cores")
        return {
            "applicable": True,
            "risk_group": "very_high",
            "criteria_met": criteria_met,
            "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["very_high"],
            "missing_data": [],
        }

    # HIGH risk
    if t_letter == "T3" or isup >= 4 or (psa is not None and psa > 20):
        if t_letter == "T3": criteria_met.append(f"cT3 stage")
        if isup >= 4: criteria_met.append(f"ISUP {isup} (Gleason ≥8)")
        if psa is not None and psa > 20: criteria_met.append(f"PSA={psa:.1f} >20")
        return {
            "applicable": True,
            "risk_group": "high",
            "criteria_met": criteria_met,
            "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["high"],
            "missing_data": [],
        }

    # Determinar IRFs (intermediate risk factors)
    irfs: list[str] = []
    if t_letter == "T2" and t_score >= 22:  # T2b or T2c
        irfs.append(f"clinical_stage={t_letter}")
    if isup in (2, 3):
        irfs.append(f"ISUP_{isup}")
    if psa is not None and 10 <= psa <= 20:
        irfs.append(f"PSA_10_to_20")

    # VERY_LOW (NCCN strict — Epstein criteria)
    if (t_letter == "T1" and t_score >= 13 and  # T1c
        isup == 1 and psa is not None and psa < 10 and
        biopsy_cores_positive is not None and biopsy_cores_positive < 3 and
        (percent_cores_positive is None or percent_cores_positive < 50) and
        (max_cancer_length is None or max_cancer_length <= 50) and
        (psa_density is None or psa_density < 0.15)):
        criteria_met.append("Epstein very low criteria met")
        return {
            "applicable": True,
            "risk_group": "very_low",
            "criteria_met": criteria_met,
            "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["very_low"],
            "missing_data": [],
        }

    # LOW
    if isup == 1 and psa is not None and psa < 10 and t_letter in ("T1", "T2") and t_score <= 21:
        criteria_met.append(f"ISUP 1 + PSA<10 + T1-T2a")
        return {
            "applicable": True,
            "risk_group": "low",
            "criteria_met": criteria_met,
            "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["low"],
            "missing_data": [],
        }

    # INTERMEDIATE — favorable vs unfavorable
    if irfs:
        # UNFAVORABLE: ≥2 IRFs OR ISUP 3 OR ≥50% cores positive
        is_unfavorable = (
            len(irfs) >= 2 or
            isup == 3 or
            (percent_cores_positive is not None and percent_cores_positive >= 50)
        )
        if is_unfavorable:
            criteria_met.extend(irfs)
            criteria_met.append("unfavorable trigger: ≥2 IRFs or ISUP 3 or ≥50% cores")
            return {
                "applicable": True,
                "risk_group": "unfavorable_intermediate",
                "criteria_met": criteria_met,
                "irf_count": len(irfs),
                "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["unfavorable_intermediate"],
                "missing_data": [],
            }
        else:
            # FAVORABLE intermediate
            criteria_met.extend(irfs)
            return {
                "applicable": True,
                "risk_group": "favorable_intermediate",
                "criteria_met": criteria_met,
                "irf_count": len(irfs),
                "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["favorable_intermediate"],
                "missing_data": [],
            }

    # Fallback: low risk (no IRFs, no high)
    return {
        "applicable": True,
        "risk_group": "low",
        "criteria_met": ["no IRFs detected, default to low risk"],
        "recommendation": RECOMMENDATIONS_BY_RISK_GROUP["low"],
        "missing_data": [],
    }


__all__ = [
    "stratify_localized_risk",
    "is_localized",
    "RECOMMENDATIONS_BY_RISK_GROUP",
]
