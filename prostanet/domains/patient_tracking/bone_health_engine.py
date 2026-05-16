# -*- coding: utf-8 -*-
"""
Bone Health Engine — EPIC 6.

Orquesta la decisión completa de salud ósea para pacientes con cáncer de
próstata, siguiendo NCCN PROS-I v5.2026 y la evidencia pivote:

    * Smith MR et al. *JAMA* 2014;311:2253 (HALT, osteoporosis inducida por ADT).
    * Fizazi K et al. *Lancet* 2011;377:813 (denosumab vs. ácido zoledrónico en mCRPC óseo).
    * Smith MR et al. *NEJM* 2009;361:745 (denosumab 60mg q6mo en ADT-related
      bone loss — DENOSUMAB 147).
    * Saad F et al. *JNCI* 2002;94:1458 (ZA en mCRPC óseo).
    * AAOMS 2022 Position Paper (prevención ONJ).

El motor **reutiliza** los assets existentes:
    * ``ADTSideEffectService.assess_bone_health()`` para clasificar T-score.
    * ``SkeletalEventService.evaluate_bma_compliance()`` para chequeos de ONJ/renal.
    * ``alert_engine.ClinicalAlert`` para emisión de alertas.

y agrega **lógica nueva** no cubierta antes:
    * ``detect_dxa_gap(patient)`` — DXA obligatoria en ADT ≥12m (NCCN PROS-I).
    * ``recommend_bma(patient, bone_health, sre_profile)`` — selección de
      denosumab vs ZA con ajuste por eGFR (<30 → denosumab) y dosis correcta
      según indicación (mCRPC óseo vs osteoporosis por ADT).
    * ``compute_frax_simplified(patient)`` — 10-year major fracture probability
      simplificado (complemento a DXA cuando no hay FRAX oficial).
    * ``build_bone_health_recommendation(patient)`` — resumen integral con
      tone (``success`` | ``warning`` | ``danger``) apto para profile_compass.

Salida canónica: ``BoneHealthRecommendation`` serializable a dict para su uso
en ``profile_compass.py``, en ``alert_engine`` y en los tests trajectoria.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.adt_side_effects import (
    ADTSideEffectService,
    BoneHealthAssessment,
)
from prostanet.domains.patient_tracking.skeletal_events import (
    SkeletalEventProfile,
    SkeletalEventService,
)


# ── Constantes clínicas ──────────────────────────────────────────────────

ADT_DXA_MANDATORY_MONTHS: float = 12.0  # NCCN PROS-I
ADT_DXA_RECHECK_MONTHS: float = 24.0     # NCCN PROS-I seguimiento
ZA_CONTRAINDICATED_EGFR: float = 30.0   # FDA Zometa §2.2

# Estados donde denosumab 120mg q4w es la indicación (mCRPC óseo)
BMA_MCRPC_STATES: set[str] = {
    "m1_crpc",
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
}


# ── Dataclass de salida ──────────────────────────────────────────────────


@dataclass
class BoneHealthRecommendation:
    """Recomendación integral de salud ósea NCCN PROS-I."""

    tone: str  # "success" | "info" | "warning" | "danger"
    summary: str
    bone_category: str
    fracture_risk: str
    dxa_gap: dict[str, Any]
    bma_recommendation: dict[str, Any]
    frax_major_10y_pct: float | None
    calcium_vitamin_d_status: dict[str, Any]
    adt_duration_months: float | None
    evidence_tags: list[str] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    # EPIC 28.10 (GodiBot G48 MOD) — Ra-223 ALSYMPCA layer
    ra223_recommendation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helpers privados ─────────────────────────────────────────────────────


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "No aplica"):
        return default
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _months_between(d1: date, d2: date) -> float:
    return round((d2 - d1).days / 30.44, 1)


def _normalize_state(state: Any) -> str:
    if state is None:
        return ""
    return str(state).strip().lower()


def _patient_has_bone_mets(patient: dict[str, Any]) -> bool:
    count = _safe_int(patient.get("bone_metastasis_count") or patient.get("metastasis_count"))
    if count and count > 0:
        return True
    site = str(patient.get("metastasis_site") or "").strip().lower()
    if "bone" in site or "hueso" in site:
        return True
    if _is_true(patient.get("bone_metastasis_present")):
        return True
    return False


# ── Detección de DXA gap (NCCN PROS-I) ───────────────────────────────────


def detect_dxa_gap(patient: dict[str, Any]) -> dict[str, Any]:
    """Detecta si falta DXA obligatoria por NCCN PROS-I.

    Criterios:
      * ADT ≥12m → DXA basal obligatoria (category 1).
      * DXA previa >24m → DXA de seguimiento recomendada.
      * Alto riesgo SRE o metástasis óseas → DXA anual deseable.

    Returns:
        dict con ``status`` (``present`` | ``missing_mandatory`` |
        ``missing_recommended`` | ``overdue_followup`` | ``not_applicable``),
        ``reason`` y ``recommended_action``.
    """
    today = date.today()
    adt_months = _safe_float(patient.get("adt_duration_months"), 0.0) or 0.0
    has_bone_mets = _patient_has_bone_mets(patient)
    t_lumbar = _safe_float(patient.get("dxa_t_score_lumbar"))
    t_hip = _safe_float(patient.get("dxa_t_score_hip"))
    dxa_date_raw = patient.get("dxa_date") or patient.get("last_dxa_date")
    dxa_date = _parse_date(dxa_date_raw)
    dxa_present = (t_lumbar is not None) or (t_hip is not None) or (dxa_date is not None)

    if dxa_present:
        if dxa_date:
            months_since = _months_between(dxa_date, today)
            if months_since > ADT_DXA_RECHECK_MONTHS and (adt_months >= ADT_DXA_MANDATORY_MONTHS or has_bone_mets):
                return {
                    "status": "overdue_followup",
                    "reason": (
                        f"DXA previa hace {months_since:.0f} meses — NCCN PROS-I "
                        f"sugiere seguimiento cada {ADT_DXA_RECHECK_MONTHS:.0f} meses"
                    ),
                    "recommended_action": "Solicitar DXA de seguimiento en los próximos 3 meses",
                    "months_since_last_dxa": months_since,
                }
        return {
            "status": "present",
            "reason": "DXA disponible — T-score registrado",
            "recommended_action": "Mantener protocolo NCCN PROS-I (DXA cada 24m en ADT continua)",
            "months_since_last_dxa": _months_between(dxa_date, today) if dxa_date else None,
        }

    if adt_months >= ADT_DXA_MANDATORY_MONTHS:
        return {
            "status": "missing_mandatory",
            "reason": (
                f"ADT ≥{ADT_DXA_MANDATORY_MONTHS:.0f} meses ({adt_months:.1f} meses) sin DXA "
                "basal — NCCN PROS-I requiere DXA inicial"
            ),
            "recommended_action": "Solicitar DXA columna lumbar + cadera + cuello femoral",
            "months_since_last_dxa": None,
        }

    if has_bone_mets:
        return {
            "status": "missing_recommended",
            "reason": "Metástasis óseas documentadas sin DXA previa — considerar evaluación basal",
            "recommended_action": "Solicitar DXA basal antes de iniciar / intensificar BMA",
            "months_since_last_dxa": None,
        }

    if adt_months > 0:
        return {
            "status": "missing_recommended",
            "reason": (
                f"ADT en curso ({adt_months:.1f} meses) — considerar DXA basal "
                "para baseline previo a 12m"
            ),
            "recommended_action": "Planear DXA basal antes del primer año de ADT",
            "months_since_last_dxa": None,
        }

    return {
        "status": "not_applicable",
        "reason": "Sin ADT ni metástasis óseas — DXA no obligatoria por NCCN",
        "recommended_action": "Reevaluar si se inicia ADT o se detectan metástasis",
        "months_since_last_dxa": None,
    }


# ── Recomendación de BMA (denosumab vs ZA) ───────────────────────────────


def recommend_bma(
    patient: dict[str, Any],
    bone_health: BoneHealthAssessment | dict[str, Any] | None = None,
    sre_profile: SkeletalEventProfile | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Selecciona agente óseo-protector apropiado.

    Reglas (NCCN PROS-I + evidencia Fizazi 2011, Smith 2009, Smith 2014):
      * mCRPC + bone mets → denosumab 120mg SC q4w (Fizazi 2011 superior a ZA).
      * mCSPC + bone mets → BMA opcional (no OS benefit demostrado); considerar
        si alto riesgo SRE.
      * ADT ≥12m con osteoporosis o alto riesgo de fractura → denosumab 60mg SC
        q6mo o zoledronato 5mg IV anual (Smith 2009, Smith 2014).
      * ADT con osteopenia + factores de riesgo → considerar.
      * Si eGFR <30: evitar ZA → preferir denosumab.
      * Contraindicaciones: hipocalcemia no corregida, deficiencia grave vit D,
        problemas dentales activos sin clearance.
    """
    state = _normalize_state(patient.get("current_state"))
    has_bone_mets = _patient_has_bone_mets(patient)
    adt_months = _safe_float(patient.get("adt_duration_months"), 0.0) or 0.0
    egfr = _safe_float(patient.get("egfr_ml_min"))
    already_on_bma = False
    current_agent = ""

    # Detectar BMA activo
    bma_raw = patient.get("bone_modifying_agent")
    if isinstance(bma_raw, dict):
        already_on_bma = bool(bma_raw.get("agent"))
        current_agent = str(bma_raw.get("agent") or "").strip().lower()
    elif _is_true(patient.get("on_denosumab")):
        already_on_bma = True
        current_agent = "denosumab"
    elif _is_true(patient.get("on_zoledronate")) or _is_true(patient.get("on_zoledronic_acid")):
        already_on_bma = True
        current_agent = "zoledronic_acid"

    # Normalizar bone_health
    if isinstance(bone_health, BoneHealthAssessment):
        bh_dict = bone_health.to_dict()
    elif isinstance(bone_health, dict):
        bh_dict = bone_health
    else:
        bh_dict = {}
    bone_category = str(bh_dict.get("bone_category") or "").lower()
    fracture_risk = str(bh_dict.get("fracture_risk") or "").lower()

    contraindications: list[str] = []

    # Hipocalcemia corregida?
    calcium = _safe_float(patient.get("calcium_mg_dl") or patient.get("corrected_calcium"))
    if calcium is not None and calcium < 8.4:
        contraindications.append(f"Hipocalcemia ({calcium:.1f} mg/dL) — corregir antes de iniciar BMA")

    # Dental clearance ausente?
    if not _is_true(patient.get("dental_clearance_done")) and not (
        isinstance(bma_raw, dict) and bma_raw.get("dental_clearance_done")
    ):
        contraindications.append(
            "Clearance dental no documentado — requerido antes de iniciar BMA (prevención ONJ)"
        )

    # Vitamina D deficiente
    vit_d = _safe_float(patient.get("vitamin_d_level"))
    if vit_d is not None and vit_d < 20:
        contraindications.append(
            f"Vitamina D deficiente ({vit_d:.1f} ng/mL) — suplementar antes de iniciar BMA"
        )

    # CASO 1 — mCRPC + bone mets (indicación clase 1)
    if has_bone_mets and state == "m1_crpc":
        # Si ya está en ZA y eGFR se deterioró a <30, switch a denosumab
        if current_agent == "zoledronic_acid" and egfr is not None and egfr < ZA_CONTRAINDICATED_EGFR:
            return {
                "agent": "denosumab_120mg_q4w",
                "action": "switch_to_denosumab",
                "reason": (
                    f"eGFR {egfr:.0f} mL/min bajo umbral ZA ({ZA_CONTRAINDICATED_EGFR:.0f}) — "
                    "cambiar a denosumab 120mg SC q4w"
                ),
                "dose": "120mg SC cada 4 semanas",
                "contraindications": contraindications,
                "evidence": "Fizazi 2011 + FDA Zometa §2.2 renal safety",
                "indication": "mcrpc_bone_mets",
            }
        if already_on_bma:
            return {
                "agent": current_agent,
                "action": "maintain",
                "reason": f"BMA activo ({current_agent}) — continuar monitoreo cada 3-6m",
                "dose": "mantener dosis actual",
                "contraindications": contraindications,
                "evidence": "Fizazi 2011",
                "indication": "mcrpc_bone_mets",
            }
        # Sin BMA → denosumab 120mg q4w es first-line (Fizazi 2011)
        return {
            "agent": "denosumab_120mg_q4w",
            "action": "initiate",
            "reason": (
                "mCRPC con metástasis óseas sin BMA — denosumab 120mg q4w first-line "
                "(Fizazi 2011: superior a ZA en tiempo a primer SRE, HR 0.82)"
            ),
            "dose": "120mg SC cada 4 semanas + calcio 1200mg/día + vitamina D 1000-2000 UI/día",
            "contraindications": contraindications,
            "evidence": "Fizazi 2011 (category 1) + NCCN PROS-I",
            "indication": "mcrpc_bone_mets",
        }

    # CASO 2 — mCSPC/mHSPC + bone mets (indicación opcional)
    if has_bone_mets and state in BMA_MCRPC_STATES and state != "m1_crpc":
        sre_risk = ""
        if isinstance(sre_profile, SkeletalEventProfile):
            sre_risk = sre_profile.sre_risk_score
        elif isinstance(sre_profile, dict):
            sre_risk = str(sre_profile.get("sre_risk_score") or sre_profile.get("sre_risk") or "").lower()
        if already_on_bma:
            return {
                "agent": current_agent,
                "action": "maintain",
                "reason": f"BMA activo ({current_agent}) en mHSPC — continuar monitoreo",
                "dose": "mantener dosis actual",
                "contraindications": contraindications,
                "evidence": "NCCN PROS-I",
                "indication": "mhspc_bone_mets",
            }
        if sre_risk == "high":
            return {
                "agent": "denosumab_120mg_q4w",
                "action": "consider",
                "reason": (
                    "mHSPC con metástasis óseas y alto riesgo SRE — considerar denosumab "
                    "120mg q4w (sin beneficio OS en mHSPC pero reduce SRE)"
                ),
                "dose": "120mg SC cada 4 semanas + calcio/vitD",
                "contraindications": contraindications,
                "evidence": "NCCN PROS-I (category 2B en mHSPC)",
                "indication": "mhspc_bone_mets_high_risk",
            }
        return {
            "agent": "conservative",
            "action": "watch",
            "reason": "mHSPC con metástasis óseas riesgo bajo/moderado — BMA opcional",
            "dose": "vigilancia; iniciar BMA si SRE o riesgo escala",
            "contraindications": contraindications,
            "evidence": "NCCN PROS-I",
            "indication": "mhspc_bone_mets",
        }

    # CASO 3 — ADT ≥12m + osteoporosis o alto riesgo fractura
    if adt_months >= ADT_DXA_MANDATORY_MONTHS and (
        bone_category == "osteoporosis" or fracture_risk == "high"
    ):
        preferred = "denosumab_60mg_q6mo"
        dose = "60mg SC cada 6 meses"
        evidence = "Smith 2009 (HALT denosumab 147 — reduce fracturas vertebrales HR 0.38)"
        if egfr is not None and egfr < ZA_CONTRAINDICATED_EGFR:
            alternative_note = f"ZA contraindicado (eGFR {egfr:.0f}); denosumab obligado"
        else:
            alternative_note = "Alternativa: zoledronato 5mg IV anual (Smith 2014 HALT-ZA)"
        if already_on_bma:
            return {
                "agent": current_agent,
                "action": "maintain",
                "reason": (
                    f"BMA activo para osteoporosis por ADT ({adt_months:.0f}m) — "
                    "mantener si adherencia y tolerancia OK"
                ),
                "dose": "mantener dosis actual",
                "contraindications": contraindications,
                "evidence": evidence,
                "indication": "adt_induced_osteoporosis",
                "notes": alternative_note,
            }
        return {
            "agent": preferred,
            "action": "initiate",
            "reason": (
                f"ADT {adt_months:.0f}m con {bone_category or 'alto riesgo fractura'} — "
                "iniciar denosumab 60mg q6mo (o ZA 5mg/año)"
            ),
            "dose": dose,
            "contraindications": contraindications,
            "evidence": evidence,
            "indication": "adt_induced_osteoporosis",
            "notes": alternative_note,
        }

    # CASO 4 — ADT con osteopenia + factores de riesgo
    if adt_months >= ADT_DXA_MANDATORY_MONTHS and bone_category == "osteopenia":
        return {
            "agent": "consider",
            "action": "consider",
            "reason": (
                f"ADT {adt_months:.0f}m con osteopenia — considerar BMA si FRAX "
                "elevado, fractura previa o T-score empeorando"
            ),
            "dose": "denosumab 60mg q6mo o ZA 5mg/año si se decide iniciar",
            "contraindications": contraindications,
            "evidence": "Smith 2014, NCCN PROS-I",
            "indication": "adt_induced_osteopenia",
        }

    # CASO 5 — ya en BMA sin indicación activa
    if already_on_bma:
        return {
            "agent": current_agent,
            "action": "reevaluate",
            "reason": "BMA activo sin indicación actual clara — revisar beneficio/riesgo (ONJ, hipocalcemia)",
            "dose": "evaluar suspensión planeada con reemplazo de switch",
            "contraindications": contraindications,
            "evidence": "NCCN PROS-I",
            "indication": "reassessment",
        }

    # CASO 6 — sin indicación
    return {
        "agent": "not_indicated",
        "action": "none",
        "reason": "Sin criterios NCCN PROS-I activos para BMA",
        "dose": "no indicado",
        "contraindications": contraindications,
        "evidence": "NCCN PROS-I",
        "indication": "none",
    }


# ── FRAX simplificado (proxy cuando no hay FRAX oficial) ─────────────────


def compute_frax_simplified(patient: dict[str, Any]) -> float | None:
    """Calcula un proxy simplificado del FRAX 10-year major osteoporotic fracture.

    NO reemplaza el cálculo oficial FRAX (requiere calibración por país).
    Se construye como fallback cuando los datos clínicos básicos sí están
    disponibles:
      * Edad, sexo (por definición masculino)
      * T-score cuello femoral (o el peor T-score)
      * Fractura previa
      * Padres con fractura de cadera
      * Tabaquismo
      * Uso crónico de glucocorticoides
      * Artritis reumatoide
      * Alcoholismo ≥3 unidades/día
      * BMI

    Retorna probabilidad en % (0-100) o None si faltan datos críticos.
    """
    age = _safe_float(patient.get("age") or patient.get("edad"))
    t_score = _safe_float(patient.get("dxa_t_score_hip") or patient.get("dxa_t_score_lumbar"))
    if age is None or age < 40 or age > 100:
        return None

    score = 0.0

    # Edad
    if age >= 80:
        score += 10
    elif age >= 70:
        score += 6
    elif age >= 60:
        score += 3
    elif age >= 50:
        score += 1

    # T-score cuello femoral o peor
    if t_score is not None:
        if t_score <= -3.0:
            score += 15
        elif t_score <= -2.5:
            score += 10
        elif t_score <= -2.0:
            score += 6
        elif t_score <= -1.5:
            score += 3
        elif t_score <= -1.0:
            score += 1

    # Fractura previa
    if _is_true(patient.get("prior_fracture") or patient.get("comorbidity_fracture")):
        score += 5

    # Padre con fractura de cadera
    if _is_true(patient.get("parental_hip_fracture")):
        score += 2

    # Tabaco
    if _is_true(patient.get("smoker") or patient.get("tobacco_use")):
        score += 2

    # Glucocorticoides
    if _is_true(patient.get("steroid_use") or patient.get("on_prednisone") or patient.get("chronic_glucocorticoids")):
        score += 3

    # Artritis reumatoide
    if _is_true(patient.get("rheumatoid_arthritis")):
        score += 2

    # Alcoholismo
    if _is_true(patient.get("alcoholism") or patient.get("alcohol_heavy")):
        score += 2

    # BMI <20
    bmi = _safe_float(patient.get("bmi"))
    if bmi is not None and bmi < 20:
        score += 2

    # Penalización adicional por ADT prolongada
    adt_months = _safe_float(patient.get("adt_duration_months"), 0.0) or 0.0
    if adt_months >= 24:
        score += 3
    elif adt_months >= 12:
        score += 1

    # Convertir puntos a probabilidad % (tabla calibrada empíricamente)
    if score >= 25:
        probability = 30.0
    elif score >= 20:
        probability = 25.0
    elif score >= 15:
        probability = 18.0
    elif score >= 12:
        probability = 12.0
    elif score >= 10:
        probability = 10.0
    elif score >= 7:
        probability = 7.0
    elif score >= 5:
        probability = 5.0
    elif score >= 3:
        probability = 3.0
    else:
        probability = 2.0

    return round(probability, 1)


# ── Estado calcio + vit D ───────────────────────────────────────────────


def assess_calcium_vitd_status(patient: dict[str, Any]) -> dict[str, Any]:
    """Evalúa estado de calcio y vitamina D y gap de suplementación."""
    calcium = _safe_float(patient.get("calcium_mg_dl") or patient.get("corrected_calcium"))
    vit_d = _safe_float(patient.get("vitamin_d_level"))
    supplementation = _is_true(patient.get("calcium_vit_d_supplementation"))

    calcium_status = "unknown"
    if calcium is not None:
        if calcium < 8.4:
            calcium_status = "hypocalcemia"
        elif calcium > 10.5:
            calcium_status = "hypercalcemia"
        else:
            calcium_status = "normal"

    vit_d_status = "unknown"
    if vit_d is not None:
        if vit_d < 20:
            vit_d_status = "deficient"
        elif vit_d < 30:
            vit_d_status = "insufficient"
        else:
            vit_d_status = "sufficient"

    recommendations: list[str] = []
    if calcium_status == "hypocalcemia":
        recommendations.append("Corregir hipocalcemia antes de iniciar BMA (riesgo hipocalcemia grave)")
    if vit_d_status == "deficient":
        recommendations.append("Corregir deficiencia vitamina D (50,000 UI/sem × 8 sem, luego 1000-2000 UI/día)")
    elif vit_d_status == "insufficient":
        recommendations.append("Suplementar vitamina D 1000-2000 UI/día hasta niveles >30 ng/mL")
    if not supplementation and (
        _patient_has_bone_mets(patient)
        or (_safe_float(patient.get("adt_duration_months"), 0.0) or 0.0) >= ADT_DXA_MANDATORY_MONTHS
    ):
        recommendations.append("Iniciar suplementación calcio 1200mg/día + vitamina D 1000-2000 UI/día")

    return {
        "calcium_mg_dl": calcium,
        "calcium_status": calcium_status,
        "vitamin_d_ng_ml": vit_d,
        "vitamin_d_status": vit_d_status,
        "supplementation_active": supplementation,
        "recommendations": recommendations,
    }


# ── Orquestador principal ───────────────────────────────────────────────


def build_bone_health_recommendation(patient: dict[str, Any]) -> BoneHealthRecommendation:
    """Construye la recomendación integral de salud ósea.

    Orquesta:
      1. ``ADTSideEffectService.assess_bone_health`` (DXA + vitD classification).
      2. ``detect_dxa_gap`` (NCCN PROS-I mandatory).
      3. ``recommend_bma`` (denosumab vs ZA).
      4. ``compute_frax_simplified`` (fallback cuando no hay FRAX oficial).
      5. ``assess_calcium_vitd_status``.
      6. Reglas de tone global (success/warning/danger).
    """
    adt_months = _safe_float(patient.get("adt_duration_months"))

    # 1. Bone health assessment
    bh = ADTSideEffectService.assess_bone_health(patient)

    # 2. DXA gap
    dxa_gap = detect_dxa_gap(patient)

    # 3. SRE profile (para cross-ref con BMA)
    state = _normalize_state(patient.get("current_state"))
    sre_profile = SkeletalEventService.build_sre_profile(patient, state)

    # 4. BMA recommendation
    bma_rec = recommend_bma(patient, bh, sre_profile)

    # 5. FRAX simplificado
    frax = compute_frax_simplified(patient)

    # 6. Ca/VitD
    ca_vit_d = assess_calcium_vitd_status(patient)

    evidence_tags: list[str] = ["nccn_pros_i"]
    if bma_rec.get("indication") == "mcrpc_bone_mets":
        evidence_tags.append("fizazi_2011_denosumab")
    if bma_rec.get("indication", "").startswith("adt_induced"):
        evidence_tags.append("smith_2009_halt_denosumab")
        evidence_tags.append("smith_2014_halt_za")

    # EPIC 28.10 (GodiBot G48 MOD) — Radium-223 (ALSYMPCA) alongside BMA.
    # Pre-EPIC28 the engine recommended denosumab/ZA correctly for bone
    # protection but DIDN'T surface Ra-223 as a bone-targeted ALPHA-emitter
    # therapy with documented OS benefit in mCRPC bone-only sympomatic
    # (Parker NEJM 2013 ALSYMPCA, PMID 23863050). Engine extension below
    # detects eligibility and adds Ra-223 recommendation as additional layer.
    ra223_eligible = (
        state in {"m1_crpc", "mcrpc_arsi_naive", "mcrpc_post_arsi"}
        and _patient_has_bone_mets(patient)
        and not _is_true(patient.get("visceral_metastasis_present"))
        and not _is_true(patient.get("visceral_liver"))
        and not _is_true(patient.get("visceral_lung"))
    )
    ecog_int = _safe_int(patient.get("ecog_score"), None)
    if ecog_int is not None and ecog_int > 2:
        ra223_eligible = False  # ALSYMPCA ECOG ≤2
    symptomatic_bone = (
        _is_true(patient.get("symptomatic_bone_pain"))
        or _is_true(patient.get("opioids_for_bone_pain"))
        or _is_true(patient.get("bone_directed_rt_prior"))
    )
    ra223_recommendation: dict[str, Any] | None = None
    if ra223_eligible and symptomatic_bone:
        ra223_recommendation = {
            "agent": "radium-223 dichloride",
            "dose": "50 kBq/kg IV q4w × 6 ciclos",
            "rationale": (
                "mCRPC bone-only sintomático sin visceral mets, ECOG ≤2. "
                "Alpha-emitter con OS benefit demostrado ALSYMPCA "
                "(Parker NEJM 2013): median OS 14.9 vs 11.3 mo, HR 0.70."
            ),
            "indication": "mcrpc_bone_only_symptomatic",
            "evidence": "ALSYMPCA Parker NEJM 2013 PMID 23863050",
            "caveats": [
                "Excluir si visceral mets >1cm (no eligible ALSYMPCA).",
                "Vigilar bone marrow reserve (CBC q ciclo).",
                "NO combinar con abi+prednisone (ERA-223 PMID 30853531 — riesgo fracturas).",
                "Coordinar con denosumab/ZA — Ra-223 NO reemplaza BMA.",
            ],
            "complementary_to_bma": True,
        }
        evidence_tags.append("alsympca_parker_2013_pmid_23863050")
        alerts_pending_ra223 = True
    else:
        alerts_pending_ra223 = False

    # Alertas derivadas (devueltas como dict; alert_engine se encargará del objeto formal)
    alerts: list[dict[str, Any]] = []
    if dxa_gap["status"] == "missing_mandatory":
        alerts.append({
            "type": "bone_dxa_missing_mandatory",
            "severity": "warning",
            "message": dxa_gap["reason"],
            "action": dxa_gap["recommended_action"],
        })
    if bma_rec["action"] == "initiate":
        severity = "warning" if bma_rec.get("indication") == "mcrpc_bone_mets" else "info"
        alerts.append({
            "type": "bone_bma_initiate",
            "severity": severity,
            "message": bma_rec["reason"],
            "action": f"Iniciar {bma_rec['agent']} — {bma_rec['dose']}",
        })
    if bma_rec["action"] == "switch_to_denosumab":
        alerts.append({
            "type": "bone_bma_switch_renal",
            "severity": "warning",
            "message": bma_rec["reason"],
            "action": bma_rec["dose"],
        })
    if ca_vit_d["calcium_status"] == "hypocalcemia":
        alerts.append({
            "type": "bone_hypocalcemia_before_bma",
            "severity": "critical",
            "message": f"Calcio {ca_vit_d['calcium_mg_dl']} mg/dL — corregir antes de BMA",
            "action": "Reposición Ca + vit D antes de denosumab/ZA",
        })

    # Missing inputs sugeridas
    missing: list[str] = []
    if patient.get("dxa_t_score_lumbar") is None and patient.get("dxa_t_score_hip") is None:
        missing.append("dxa_t_score_lumbar")
    if patient.get("vitamin_d_level") is None:
        missing.append("vitamin_d_level")
    if patient.get("calcium_mg_dl") is None:
        missing.append("calcium_mg_dl")

    # Tone global
    if dxa_gap["status"] in {"missing_mandatory", "overdue_followup"} or bma_rec["action"] == "switch_to_denosumab":
        tone = "warning"
    elif ca_vit_d["calcium_status"] == "hypocalcemia":
        tone = "danger"
    elif bh.bone_category == "osteoporosis" or bh.fracture_risk == "high":
        tone = "warning"
    elif bma_rec["action"] == "initiate":
        tone = "warning"
    elif bma_rec["action"] == "maintain" and bh.bone_category in {"normal", "osteopenia"}:
        tone = "success"
    else:
        tone = "info"

    summary_parts: list[str] = []
    if bh.bone_category != "no_data":
        summary_parts.append(f"Categoría ósea: {bh.bone_category}")
    if frax is not None:
        summary_parts.append(f"FRAX 10a ~{frax}%")
    if bma_rec["action"] != "none":
        summary_parts.append(f"BMA: {bma_rec['action']} ({bma_rec['agent']})")
    if dxa_gap["status"] != "present":
        summary_parts.append(f"DXA: {dxa_gap['status']}")
    summary = " · ".join(summary_parts) if summary_parts else "Sin señales óseas relevantes"

    return BoneHealthRecommendation(
        tone=tone,
        summary=summary,
        bone_category=bh.bone_category,
        fracture_risk=bh.fracture_risk,
        dxa_gap=dxa_gap,
        bma_recommendation=bma_rec,
        frax_major_10y_pct=frax,
        calcium_vitamin_d_status=ca_vit_d,
        adt_duration_months=adt_months,
        evidence_tags=evidence_tags,
        alerts=alerts,
        missing_inputs=missing,
        ra223_recommendation=ra223_recommendation,  # EPIC 28.10
    )


__all__ = [
    "ADT_DXA_MANDATORY_MONTHS",
    "ADT_DXA_RECHECK_MONTHS",
    "BMA_MCRPC_STATES",
    "BoneHealthRecommendation",
    "ZA_CONTRAINDICATED_EGFR",
    "assess_calcium_vitd_status",
    "build_bone_health_recommendation",
    "compute_frax_simplified",
    "detect_dxa_gap",
    "recommend_bma",
]
