"""trajectory_alert_engine.py — EPIC 47.C (FAUBOT CXXXV).

Alert detector clínico que evalúa el trajectory bundle contra thresholds
basados en evidencia NCCN / EAU 2026 + literatura prostate cancer.

Alertas implementadas (priorizadas por valor clínico):

1. **PSA doubling time corto** (PSADT <10m → alto riesgo, NCCN PROS-K):
   - Crítico: PSADT <6m + state=m0_crpc → indicación SPARTAN/PROSPER/ARAMIS
   - Alto: PSADT <10m → considerar ARSI
   - Source: Smith MR JCO 2018 (SPARTAN), Hussain NEJM 2018 (PROSPER)

2. **ALP rise >25% últimos 3 meses sin imagen positiva** (pre-bone-mets
   signal):
   - Alto: ALP +25% en pacientes mHSPC/CRPC bajo ADT → considerar PSMA-PET
     o bone scan adicional ANTES que aparezca lesion radiográfica
   - Source: Sartor Lancet Oncol 2019, ALSYMPCA bone events analysis

3. **PSA progression con régimen ARSI** (resistance signal):
   - Crítico: PSA rise >25% over nadir + currently on ARSI → progression
     según PCWG3 criteria → considerar switch o adición taxano
   - Source: Scher JCO 2016 PCWG3

4. **ECOG decline ≥1 punto** (deterioro funcional):
   - Alto: ECOG sube de 0/1 a 2 → reconsiderar agresividad terapéutica
   - Crítico: ECOG ≥3 → suspender terapia citotóxica, evaluar paliativo
   - Source: NCCN PROS-O paliativo

5. **Testosterone failure to suppress** bajo ADT:
   - Crítico: testosterona >50 ng/dL después de 3+ meses de ADT
   - Source: NCCN PROS-K, EAU 2026

Cada alert incluye:
  - severity (critical / high / moderate / low)
  - alert_id (estable, para deduplicación + audit)
  - clinical_message (texto para UI)
  - evidence (qué métrica disparó)
  - citation (DOI/trial reference)
  - action_suggested (próximo paso clínico)
  - audit_keys (para clinical_view_audit log)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def evaluate_trajectory_alerts(
    trajectory_bundle: dict[str, Any],
    patient_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evalúa el trajectory contra todos los detectors y retorna alerts.

    Args:
        trajectory_bundle: output de build_trajectory_bundle()
        patient_context: opcional, dict con keys clínicos relevantes:
            - state_resolved (str, ej 'm0_crpc', 'mcspc_high_volume')
            - on_arsi (bool)
            - on_adt (bool)
            - last_imaging_status (str, ej 'M0', 'M1')

    Returns:
        Lista de alert dicts ordenada por severity (critical primero).
    """
    if not trajectory_bundle or not trajectory_bundle.get("available"):
        return []

    ctx = patient_context or {}
    detectors = [
        _detect_short_psa_doubling_time,
        _detect_alp_pre_bone_mets_rise,
        _detect_psa_progression_on_arsi,
        _detect_ecog_decline,
        _detect_testosterone_failure_to_suppress,
    ]

    alerts: list[dict[str, Any]] = []
    for det in detectors:
        try:
            a = det(trajectory_bundle, ctx)
            if a:
                alerts.append(a)
        except Exception as exc:
            logger.debug("Alert detector %s failed: %s", det.__name__, exc)

    # Sort by severity desc
    severity_rank = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    alerts.sort(key=lambda x: severity_rank.get(x.get("severity", "low"), 4))
    return alerts


# ─────────────────────────────────────────────────────────────────────
# Detectors (single responsibility each)
# ─────────────────────────────────────────────────────────────────────


def _detect_short_psa_doubling_time(
    bundle: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """PSADT <10m → ARSI consideration. PSADT <6m + m0_crpc → critical."""
    psadt = (bundle.get("kinetics") or {}).get("psa_doubling_time_months")
    if psadt is None or psadt >= 10:
        return None

    state = str(ctx.get("state_resolved") or "").lower()
    is_m0_crpc = "m0_crpc" in state or state == "m0_crpc"

    if psadt < 6 and is_m0_crpc:
        return {
            "severity": "critical",
            "alert_id": "psa_doubling_time_short_m0crpc",
            "clinical_message": (
                f"PSADT muy corto ({psadt:.1f} meses) en m0CRPC — indicación "
                f"NCCN PROS-K para apalutamida (SPARTAN), enzalutamida (PROSPER) "
                f"o darolutamida (ARAMIS)."
            ),
            "evidence": {
                "psa_doubling_time_months": psadt,
                "threshold_critical_months": 6,
                "state_context": state,
            },
            "citation": (
                "SPARTAN (Smith MR JCO 2018), PROSPER (Hussain NEJM 2018), "
                "ARAMIS (Fizazi NEJM 2019), NCCN PROS-K v5.2026."
            ),
            "action_suggested": "Iniciar ARSI de elección + bone protection si elegible.",
            "audit_keys": ["psa_doubling_time", "m0_crpc_short_psadt"],
        }

    if psadt < 10:
        return {
            "severity": "high",
            "alert_id": "psa_doubling_time_short",
            "clinical_message": (
                f"PSADT corto ({psadt:.1f} meses) — considerar escalación "
                f"o ARSI según contexto clínico."
            ),
            "evidence": {
                "psa_doubling_time_months": psadt,
                "threshold_high_months": 10,
            },
            "citation": "NCCN PROS-K v5.2026, EAU 2026.",
            "action_suggested": "Revisar régimen actual, evaluar ARSI add-on.",
            "audit_keys": ["psa_doubling_time"],
        }
    return None


def _detect_alp_pre_bone_mets_rise(
    bundle: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """ALP rise >25% últimos 3 meses + paciente bajo ADT sin imagen
    positiva = signal temprano de bone mets antes que aparezca radiografía.
    """
    alp_trend = (bundle.get("kinetics") or {}).get("alp_trend_pct_3m")
    if alp_trend is None or alp_trend < 25:
        return None

    on_adt = bool(ctx.get("on_adt"))
    last_imaging = str(ctx.get("last_imaging_status") or "").upper()
    no_radiographic_progression = last_imaging in {"", "M0", "STABLE"}

    if alp_trend >= 25 and on_adt and no_radiographic_progression:
        return {
            "severity": "high",
            "alert_id": "alp_pre_bone_mets_rise",
            "clinical_message": (
                f"ALP +{alp_trend:.1f}% últimos 3 meses bajo ADT, sin progresión "
                f"radiográfica documentada — signal pre-clínico de bone mets. "
                f"Considerar PSMA-PET o gammagrama óseo de re-estadificación."
            ),
            "evidence": {
                "alp_trend_pct_3m": alp_trend,
                "threshold_pct": 25,
                "last_imaging_status": last_imaging or "not_documented",
                "on_adt": True,
            },
            "citation": "Sartor Lancet Oncol 2019, NCCN PROS-N v5.2026.",
            "action_suggested": "Re-estadificar con PSMA-PET (preferido) o TAC + gammagrama óseo.",
            "audit_keys": ["alp_rise", "pre_bone_mets_signal"],
        }
    return None


def _detect_psa_progression_on_arsi(
    bundle: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """PSA rise >25% sobre nadir bajo ARSI → progression según PCWG3."""
    kinetics = bundle.get("kinetics") or {}
    nadir_info = kinetics.get("psa_nadir")
    last_psa = kinetics.get("psa_last_value")
    on_arsi = bool(ctx.get("on_arsi"))

    if not nadir_info or last_psa is None or not on_arsi:
        return None

    nadir_value = nadir_info.get("value")
    if not nadir_value or nadir_value <= 0:
        return None

    # PCWG3 criterion: ≥25% increase + absolute increase ≥2 ng/mL
    pct_increase = ((last_psa - nadir_value) / nadir_value) * 100
    abs_increase = last_psa - nadir_value

    if pct_increase >= 25 and abs_increase >= 2:
        return {
            "severity": "critical",
            "alert_id": "psa_progression_on_arsi_pcwg3",
            "clinical_message": (
                f"Progresión bioquímica bajo ARSI según PCWG3: PSA {last_psa:.2f} "
                f"vs nadir {nadir_value:.2f} ({pct_increase:.1f}%, "
                f"Δ {abs_increase:.2f} ng/mL). Considerar switch de terapia "
                f"o adición de taxano."
            ),
            "evidence": {
                "psa_last_value": last_psa,
                "psa_nadir_value": nadir_value,
                "pct_increase": round(pct_increase, 1),
                "absolute_increase_ng_ml": round(abs_increase, 2),
                "pcwg3_threshold_pct": 25,
                "pcwg3_threshold_abs_ng_ml": 2,
            },
            "citation": "Scher HI JCO 2016 (PCWG3), NCCN PROS-K v5.2026.",
            "action_suggested": (
                "Evaluar switch de ARSI (Abi↔Enza/Apa/Daro), agregar docetaxel "
                "si elegible, o considerar Lu-PSMA si PSMA-positivo."
            ),
            "audit_keys": ["psa_progression_pcwg3", "arsi_resistance"],
        }
    return None


def _detect_ecog_decline(
    bundle: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """ECOG decline ≥1 punto → reconsiderar agresividad. ECOG ≥3 → critical."""
    kinetics = bundle.get("kinetics") or {}
    ecog_first = kinetics.get("ecog_first")
    ecog_last = kinetics.get("ecog_last")
    declined = kinetics.get("ecog_decline_detected")

    if not declined or ecog_first is None or ecog_last is None:
        return None

    delta = ecog_last - ecog_first

    if ecog_last >= 3:
        return {
            "severity": "critical",
            "alert_id": "ecog_severe_decline",
            "clinical_message": (
                f"ECOG actual {ecog_last} (vs {ecog_first} previo, Δ +{delta}) — "
                f"performance status severamente comprometido. Suspender terapia "
                f"citotóxica, considerar manejo paliativo y evaluación de "
                f"goals-of-care con paciente y familia."
            ),
            "evidence": {
                "ecog_first": ecog_first,
                "ecog_last": ecog_last,
                "delta": delta,
            },
            "citation": "NCCN PROS-O Paliativo v5.2026, EAU 2026 supportive care.",
            "action_suggested": "Suspender citotóxicos, derivar a paliativo, conversación goals-of-care.",
            "audit_keys": ["ecog_decline", "performance_status_critical"],
        }

    if delta >= 1:
        return {
            "severity": "high",
            "alert_id": "ecog_decline",
            "clinical_message": (
                f"Deterioro ECOG de {ecog_first} a {ecog_last} (Δ +{delta}) — "
                f"reconsiderar agresividad de régimen actual. Si ECOG=2, "
                f"evaluar dosis-modificación ARSI o switch a esquema menos tóxico."
            ),
            "evidence": {
                "ecog_first": ecog_first,
                "ecog_last": ecog_last,
                "delta": delta,
            },
            "citation": "NCCN PROS-O v5.2026.",
            "action_suggested": "Ajuste de dosis ARSI o switch terapéutico según contexto.",
            "audit_keys": ["ecog_decline"],
        }
    return None


def _detect_testosterone_failure_to_suppress(
    bundle: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Testosterona >50 ng/dL bajo ADT activo = fracaso de castración."""
    if not bool(ctx.get("on_adt")):
        return None

    testo_series = (bundle.get("series") or {}).get("testosterone") or []
    if not testo_series:
        return None

    last = testo_series[-1]
    last_value = last.get("value")
    if last_value is None or last_value <= 50:
        return None

    # Threshold castración: <50 ng/dL (1.7 nmol/L)
    return {
        "severity": "critical",
        "alert_id": "testosterone_failure_to_suppress",
        "clinical_message": (
            f"Testosterona {last_value:.0f} ng/dL bajo ADT activo — "
            f"fracaso de castración (umbral <50 ng/dL). Verificar adherencia, "
            f"cambiar LHRH agonist a antagonist (degarelix/relugolix) o "
            f"considerar orquiectomía bilateral."
        ),
        "evidence": {
            "testosterone_last_value_ng_dl": last_value,
            "castration_threshold_ng_dl": 50,
            "sample_date": last.get("date"),
        },
        "citation": "NCCN PROS-K v5.2026, Klotz JCO 2015 (degarelix).",
        "action_suggested": (
            "Verificar adherencia ADT; si confirmada, cambiar LHRH agonist→antagonist "
            "o evaluar orquiectomía bilateral. Re-testosterone en 4 semanas."
        ),
        "audit_keys": ["castration_failure", "testosterone_above_threshold"],
    }


__all__ = [
    "evaluate_trajectory_alerts",
]
