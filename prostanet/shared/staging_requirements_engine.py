"""staging_requirements_engine.py — Gate de estadificación M obligatoria.

Centraliza la lógica clínica derivada de:

* **NCCN PROS-2 v5.2026 (categoría 1)** — staging obligatorio en HIGH/VERY-HIGH
  risk localized prostate cancer.
* **NCCN PROS-3 v5.2026** — contraindicación de prostatectomía radical en cT4
  (invasión a recto, vejiga, elevadores o pared pélvica).
* **EAU 2026 §6.4.1-6.4.3** — investigaciones de extensión imagenológica.
* **EAU 2026 §6.5.1** — RP restringida a cT2-cT3a seleccionado N0.
* **ProPSMA (Hofman, Lancet 2020;395:1208)** — PSMA PET/CT preferente.

Cinco funciones públicas:

1. ``staging_required(payload)`` — ¿el paciente requiere staging M?
2. ``staging_complete(payload)`` — ¿la estadificación está completa?
3. ``staging_modality_recommended(payload, risk_band)`` — modalidad preferente.
4. ``staging_gap_descriptor(payload)`` — descriptor unificado para emisión.
5. ``radical_prostatectomy_contraindicated(payload)`` — Gate B (cT4 / invasión).
"""
from __future__ import annotations

from typing import Any


_TRUTHY = {
    "sí",
    "si",
    "1",
    "yes",
    "true",
    "verdadero",
    "positivo",
}
_FALSY = {
    "no",
    "0",
    "false",
    "negativo",
    "n0",
    "m0",
    "desconocido",
}


def _txt(payload: dict[str, Any], *keys: str) -> str:
    """Devuelve el primer valor no vacío entre las claves dadas, normalizado."""
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip().lower()
    return ""


def _is_yes(payload: dict[str, Any], *keys: str) -> bool:
    return _txt(payload, *keys) in _TRUTHY


def _is_no(payload: dict[str, Any], *keys: str) -> bool:
    return _txt(payload, *keys) in _FALSY


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ── 1) staging_required ────────────────────────────────────────────────
def staging_required(payload: dict[str, Any]) -> dict[str, Any]:
    """Retorna {required, considered, tier, reasons, risk_band, …}.

    Aplica criterios NCCN PROS-2/PROS-3 v5.2026 (cat 1) + EAU 2026 §6.4.1-6.4.3:

    * **Mandatorio** (``tier="mandatory"``):
        - PSA > 20 ng/mL
        - cT2b-T4 (EAU §6.4.1)
        - ISUP grade ≥ 4 (Gleason 8-10)
        - Síntomas óseos o adenopatías palpables (siempre)
    * **Considerado** (``tier="considered"``):
        - PSA 10-20 ng/mL + (cT2c o GG ≥3 o Gleason 4+3)
    * **No requerido** (``tier="not_required"``): bajo riesgo.

    ``risk_band`` ∈ {very_high, high, intermediate_unfavorable, intermediate_or_lower}.
    """
    reasons: list[str] = []
    t_stage = _txt(payload, "clinical_tstage", "clinical_tstage_at_treatment").upper()
    psa = _safe_float(payload.get("psa"))
    isup = _safe_int(payload.get("isup_grade"))
    gleason = _safe_int(payload.get("gleason_total"))
    bone_pain = _is_yes(payload, "bone_pain", "skeletal_symptoms")
    palpable_nodes = _is_yes(payload, "palpable_lymphadenopathy")

    # ── Mandatorio (NCCN PROS-2 v5.2026 cat 1: HIGH/VERY-HIGH risk) ──
    if psa > 20:
        reasons.append(f"PSA {psa:.1f} ng/mL > 20 (NCCN PROS-2 cat 1)")
    if t_stage.startswith(("T3", "T4")):
        reasons.append(f"Tacto rectal {t_stage} (EAU §6.4.1; NCCN PROS-2)")
    if isup >= 4:
        reasons.append(f"ISUP grade group {isup} (Gleason 8-10)")
    elif gleason >= 8:
        reasons.append(f"Gleason total {gleason}")
    if bone_pain:
        reasons.append("Síntomas óseos sospechosos (siempre obligatorio)")
    if palpable_nodes:
        reasons.append("Adenopatías palpables (siempre obligatorio)")

    # ── Considerado (intermedio desfavorable, NCCN PROS-2 cat 2A) ────
    considered_only: list[str] = []
    if not reasons:
        intermediate_unfavorable = (
            (psa > 10 and psa <= 20)
            and (
                t_stage.startswith(("T2B", "T2C"))
                or isup >= 3
                or gleason == 7
            )
        )
        if intermediate_unfavorable:
            considered_only.append(
                f"PSA {psa:.1f} ng/mL con cT2b/c o GG3/Gleason 4+3 — intermedio "
                "desfavorable (considerar staging, NCCN cat 2A)"
            )

    # ── Risk band (NCCN PROS-1) ───────────────────────────────────────
    feature_count = sum(
        [
            t_stage.startswith(("T3", "T4")),
            psa > 20,
            isup >= 4 or gleason >= 8,
        ]
    )
    if (
        t_stage.startswith("T3B")
        or t_stage.startswith("T4")
        or psa > 40
        or feature_count >= 2
    ):
        risk_band = "very_high"
    elif feature_count >= 1:
        risk_band = "high"
    elif considered_only:
        risk_band = "intermediate_unfavorable"
    else:
        risk_band = "intermediate_or_lower"

    if reasons:
        tier = "mandatory"
    elif considered_only:
        tier = "considered"
        reasons = considered_only
    else:
        tier = "not_required"

    return {
        "required": tier == "mandatory",
        "considered": tier == "considered",
        "tier": tier,
        "reasons": reasons,
        "risk_band": risk_band,
        "feature_count": feature_count,
        "psa_value": psa,
        "t_stage": t_stage,
    }


# ── 2) staging_complete ────────────────────────────────────────────────
def staging_complete(payload: dict[str, Any]) -> dict[str, Any]:
    """Retorna {complete, modalities_done, missing}.

    ``complete`` = True si al menos una de:
        - PSMA PET/CT realizado con resultado documentado
        - GGO + (TAC abdomino-pélvico o RM abdomino-pélvica)
    """
    psma_done = _is_yes(payload, "psma_pet_done")
    psma_result_raw = _txt(payload, "psma_pet_result")
    psma_has_result = bool(psma_result_raw) and "desconocido" not in psma_result_raw

    bone_done = _is_yes(payload, "bone_scan_done")
    bone_result_raw = _txt(payload, "bone_scan_result")
    bone_has_result = bool(bone_result_raw) and "desconocido" not in bone_result_raw

    ct_done = _is_yes(payload, "ct_abdomen_pelvis_done")
    mri_done = _is_yes(payload, "mri_abdomen_pelvis_done")
    cross_sectional_done = ct_done or mri_done

    modalities_done: list[str] = []
    if psma_done:
        modalities_done.append("PSMA PET/CT")
    if bone_done:
        modalities_done.append("GGO")
    if ct_done:
        modalities_done.append("TAC abdomino-pélvico")
    if mri_done:
        modalities_done.append("RM abdomino-pélvica")

    psma_path_complete = psma_done and (psma_has_result or _is_yes(payload, "imaging_negative_metastases"))
    conventional_path_complete = bone_done and cross_sectional_done

    complete = psma_path_complete or conventional_path_complete

    missing: list[str] = []
    if not complete:
        if not psma_done and not bone_done:
            missing.append(
                "PSMA PET/CT (preferido) o gammagrafía ósea + TAC/RM (alternativa)"
            )
        else:
            if not psma_path_complete and not bone_done:
                missing.append("Gammagrafía ósea")
            if not psma_path_complete and not cross_sectional_done:
                missing.append("TAC abdomino-pélvico con contraste o RM abdomino-pélvica")
            if psma_done and not psma_has_result:
                missing.append("Resultado integrado del PSMA PET/CT")

    return {
        "complete": complete,
        "modalities_done": modalities_done,
        "missing": missing,
        "psma_path": psma_path_complete,
        "conventional_path": conventional_path_complete,
    }


# ── 3) staging_modality_recommended ────────────────────────────────────
def staging_modality_recommended(
    payload: dict[str, Any], risk_band: str
) -> list[dict[str, Any]]:
    """Recomienda modalidad preferente según risk_band.

    * VERY HIGH (cT4, PSA>40, ≥2 features) → PSMA PET/CT preferente (ProPSMA cat 1).
    * HIGH (1 feature) → PSMA PET/CT o GGO+TAC (ambas NCCN cat 1).
    * INTERMEDIATE_UNFAVORABLE → considerar (cat 2A).
    """
    items: list[dict[str, Any]] = []
    if risk_band == "very_high":
        items.append(
            {
                "name": "PSMA PET/CT (preferente)",
                "priority": "first_line",
                "category": "staging_imaging",
                "rationale": (
                    "Riesgo muy alto (cT4, PSA>40 o ≥2 features). ProPSMA "
                    "(Hofman 2020) muestra sensibilidad 85% vs 38% para "
                    "detección de enfermedad metastásica. NCCN PROS-2 "
                    "v5.2026 categoría 1."
                ),
                "evidence_tag": "propsma_2020",
            }
        )
        items.append(
            {
                "name": (
                    "Alternativa: gammagrafía ósea Tc-99m + TAC abdomino-"
                    "pélvico con contraste"
                ),
                "priority": "alternative",
                "category": "staging_imaging",
                "rationale": "Si PSMA PET/CT no disponible. NCCN PROS-2 cat 1.",
                "evidence_tag": "nccn_pros2_v5_2026",
            }
        )
    elif risk_band == "high":
        items.append(
            {
                "name": "PSMA PET/CT o gammagrafía ósea + TAC abdomino-pélvico",
                "priority": "first_line",
                "category": "staging_imaging",
                "rationale": (
                    "NCCN PROS-2 v5.2026 categoría 1 — ambas modalidades "
                    "aceptadas en riesgo alto."
                ),
                "evidence_tag": "nccn_pros2_v5_2026",
            }
        )
    elif risk_band == "intermediate_unfavorable":
        items.append(
            {
                "name": "Considerar PSMA PET/CT o GGO + TAC abdomino-pélvico",
                "priority": "considered",
                "category": "staging_imaging",
                "rationale": (
                    "Intermedio desfavorable (PSA 10-20 + cT2c/GG3/Gleason "
                    "4+3). NCCN PROS-2 cat 2A — considerar staging según "
                    "juicio clínico."
                ),
                "evidence_tag": "nccn_pros2_v5_2026",
            }
        )
    return items


# ── 4) staging_gap_descriptor ──────────────────────────────────────────
def staging_gap_descriptor(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Descriptor unificado para emisión en services y UI.

    Retorna None si no hay gap; dict con descriptor si la estadificación
    está incompleta y el riesgo lo exige.

    Nota: solo bloquea si ``tier="mandatory"``. Si tier="considered", emite
    un descriptor informativo sin requerir bloqueo.
    """
    req = staging_required(payload)
    if req["tier"] == "not_required":
        return None
    comp = staging_complete(payload)
    if comp["complete"] and _is_yes(payload, "imaging_negative_metastases"):
        return None
    return {
        "tier": req["tier"],
        "blocking": req["tier"] == "mandatory",
        "risk_band": req["risk_band"],
        "reasons": req["reasons"],
        "modalities_done": comp["modalities_done"],
        "missing_modalities": comp["missing"],
        "recommended": staging_modality_recommended(payload, req["risk_band"]),
        "imaging_negative_documented": _is_yes(payload, "imaging_negative_metastases"),
    }


# ── 5) radical_prostatectomy_contraindicated ───────────────────────────
def radical_prostatectomy_contraindicated(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Determina si RP+PLND está contraindicada por T-stage o factores locales.

    NCCN PROS-3 v5.2026 + EAU 2026 §6.5.1:

    * **Absoluta** (severity="absolute"):
        - cT4 (invasión a recto, vejiga, elevadores, pared pélvica)
        - Invasión rectal o vesical documentada
        - Fijación pélvica clínica
    * **Relativa** (severity="relative"):
        - cT3b con invasión extensa de vesículas seminales
    * **Sin contraindicación** (severity="none"): cT1-T3a sin factores locales.
    """
    t_stage = _txt(payload, "clinical_tstage", "clinical_tstage_at_treatment").upper()
    fixed_pelvic = _is_yes(payload, "pelvic_fixation", "fixed_to_pelvic_wall")
    extensive_sv = _is_yes(payload, "extensive_seminal_vesicle_invasion")
    rectal_invasion = _is_yes(payload, "rectal_invasion")
    bladder_invasion = _is_yes(payload, "bladder_invasion")

    contraindicated = False
    severity = "none"
    reasons: list[str] = []
    alternatives: list[str] = []

    if (
        t_stage.startswith("T4")
        or rectal_invasion
        or bladder_invasion
        or fixed_pelvic
    ):
        contraindicated = True
        severity = "absolute"
        if t_stage.startswith("T4"):
            reasons.append(
                f"Tacto rectal {t_stage} — invasión a estructuras adyacentes "
                "(recto, vejiga, elevadores o pared pélvica). NCCN PROS-3 "
                "v5.2026 + EAU §6.5.1."
            )
        if rectal_invasion:
            reasons.append("Invasión rectal documentada (tacto/RM/TAC).")
        if bladder_invasion:
            reasons.append("Invasión vesical documentada.")
        if fixed_pelvic:
            reasons.append("Fijación pélvica clínica al examen.")
        alternatives = [
            "EBRT (78-80 Gy) + ADT 1.5-3 años (NCCN PROS-3 cat 1)",
            "EBRT + braquiterapia boost + ADT (cat 1 si elegible)",
            "Considerar abiraterona si M0 alto riesgo (STAMPEDE arm G/H)",
        ]
    elif t_stage.startswith("T3B") and extensive_sv:
        contraindicated = True
        severity = "relative"
        reasons.append(
            "cT3b con invasión extensa de vesículas seminales — RP no "
            "preferente. EAU §6.5.1."
        )
        alternatives = [
            "EBRT + ADT 2-3 años preferente",
            "RP+PLND solo en centros expertos como manejo multimodal",
        ]

    return {
        "contraindicated": contraindicated,
        "severity": severity,
        "reasons": reasons,
        "alternatives": alternatives,
        "t_stage": t_stage,
    }
