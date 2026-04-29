"""clinical_provisional_diagnosis_engine.py — Diagnóstico provisional pre-histología.

NCCN PROS-G v5.2026 + EAU 2026 §6.5.4 + Briganti / ProsTIC nomograms.

Permite declarar diagnóstico clínico altamente probable sin biopsia
confirmatoria para activar workflows downstream (mHSPC empírico,
palliative, emergencies) sin contaminar ``known_cancer_diagnosis``
(reservado para confirmación histológica).

Brecha clínica reportada (2026-04-23): paciente con APE 5000 ng/mL +
cT4 fijo+pétreo sin BTR no tiene mecanismo para activar tratamiento
sistémico pre-histología, aunque la probabilidad pre-test de M1 es
>97% (Briganti) y las guías NCCN PROS-G / EAU §6.5.4 permiten ADT
empírico en esta situación clínica.

Referencias:
  - NCCN Prostate Cancer Guidelines v5.2026 — PROS-G (Empiric ADT)
  - EAU 2026 §6.5.4 — Neoadjuvant ADT in locally advanced disease
  - Briganti A et al. *Eur Urol* 2012;61:480-7
  - Hofman M (ProPSMA) *Lancet* 2020;395:1208
  - James ND (STAMPEDE) *NEJM* 2017;377:338
"""
from __future__ import annotations

from typing import Any

# ── Umbrales codificados (NCCN PROS-G + EAU §6.5.4 + Briganti) ──────────
PSA_HIGH = 100.0
"""Considerado alto; justifica staging M obligatorio."""

PSA_VERY_HIGH = 500.0
"""Probabilidad M1 ~80-90%; provisional probable."""

PSA_EXTREME = 1000.0
"""Probabilidad M1 >93%; provisional altamente probable."""

PSA_VIRTUALLY_CERTAIN = 5000.0
"""Probabilidad M1 >97%; provisional virtualmente cierto."""


def _norm(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return str(value).strip().lower()


def _txt(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return _norm(value)
    return ""


def _safe_float(payload: dict, *keys: str) -> float:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


# ── Predicados clínicos ─────────────────────────────────────────────────
def _is_locally_advanced_dre(payload: dict) -> bool:
    """cT3-T4 por DRE o consistencia pétrea + fijación → cT4 clínico."""
    tstage = _txt(
        payload,
        "clinical_tstage_dre_estimate",
        "clinical_tstage",
        "dre_finding",
    )
    tstage_upper = tstage.upper()
    consistency = _txt(payload, "dre_prostate_consistency")
    fixation = _txt(payload, "dre_fixation")
    has_advanced_t = any(tstage_upper.startswith(x) for x in ("T3", "T4"))
    is_petrea = "pétrea" in consistency or "petrea" in consistency
    is_fija = "fija" in fixation
    return has_advanced_t or (is_petrea and is_fija)


def _has_metastatic_imaging_signal(payload: dict) -> bool:
    """PSMA PET/CT positivo o GGO/TAC positiva pre-biopsia."""
    psma_result = _txt(payload, "psma_pet_result")
    bone_result = _txt(payload, "bone_scan_result")
    ct_result = _txt(payload, "ct_abdomen_pelvis_result")
    return (
        ("positivo" in psma_result and "extra-prostático" in psma_result)
        or ("positivo" in psma_result and "m1" in psma_result)
        or ("positivo" in bone_result)
        or ("visceral m1" in ct_result)
        or ("adenopatías sospechosas" in ct_result)
        or ("adenopatias sospechosas" in ct_result)
    )


def _has_histology_pending(payload: dict) -> bool:
    """Biopsia no realizada / programada / en proceso / pendiente resultado."""
    status = _txt(payload, "biopsy_status")
    return any(
        kw in status
        for kw in (
            "no realizada",
            "programada",
            "en proceso",
            "pendiente resultado",
            "contraindicada",
        )
    )


def _has_confirmed_histology(payload: dict) -> bool:
    status = _txt(payload, "biopsy_status")
    return "confirma cáncer" in status or "confirma cancer" in status


# ── API pública ────────────────────────────────────────────────────────
def assess_provisional_diagnosis(payload: dict) -> dict:
    """Evalúa tier de diagnóstico provisional clínico.

    Retorna dict con:
      - tier: none | possible | probable | highly_probable | virtually_certain
      - basis: lista de motivos
      - confidence: 0-1
      - allow_empiric_adt: bool (si justifica ADT pre-histología)
      - biopsy_priority: str ("standard"|"within_2_weeks"|"urgent_within_7d"|"urgent_or_alternative_site")
    """
    if not isinstance(payload, dict):
        return {
            "tier": "none",
            "basis": [],
            "confidence": 0.0,
            "allow_empiric_adt": False,
            "biopsy_priority": "standard",
            "psa_value": 0.0,
            "locally_advanced_dre": False,
            "metastatic_imaging_signal": False,
        }

    psa = _safe_float(payload, "psa")
    locally_advanced = _is_locally_advanced_dre(payload)
    metastatic_imaging = _has_metastatic_imaging_signal(payload)
    bone_pain = _txt(payload, "bone_pain_severity")
    severe_bone_pain = "severo" in bone_pain or "moderado" in bone_pain
    weight_loss = _safe_float(payload, "weight_loss_kg_3mo")
    significant_weight_loss = weight_loss >= 5.0
    histology_pending = _has_histology_pending(payload)
    histology_confirmed = _has_confirmed_histology(payload)

    # Construir basis (motivos clínicos documentables)
    basis: list[str] = []
    if psa >= PSA_VIRTUALLY_CERTAIN:
        basis.append(
            f"APE {psa:.0f} ng/mL (≥{PSA_VIRTUALLY_CERTAIN:.0f} — probabilidad M1 >97%)"
        )
    elif psa >= PSA_EXTREME:
        basis.append(
            f"APE {psa:.0f} ng/mL (≥{PSA_EXTREME:.0f} — probabilidad M1 >93%)"
        )
    elif psa >= PSA_VERY_HIGH:
        basis.append(
            f"APE {psa:.0f} ng/mL (≥{PSA_VERY_HIGH:.0f} — probabilidad M1 ~80-90%)"
        )
    elif psa >= PSA_HIGH:
        basis.append(
            f"APE {psa:.0f} ng/mL (≥{PSA_HIGH:.0f} — probabilidad M1 ~60-75%)"
        )
    if locally_advanced:
        basis.append("DRE: enfermedad localmente avanzada (cT3-T4, pétrea o fija)")
    if metastatic_imaging:
        basis.append("Imagenología con señal metastásica (PSMA/GGO/TAC)")
    if severe_bone_pain:
        basis.append("Dolor óseo clínicamente relevante")
    if significant_weight_loss:
        basis.append(f"Pérdida de peso {weight_loss:.0f} kg en 3 meses")

    # Tier según señales
    if psa >= PSA_VIRTUALLY_CERTAIN and locally_advanced:
        tier = "virtually_certain"
        confidence = 0.97
    elif psa >= PSA_EXTREME and (locally_advanced or metastatic_imaging):
        tier = "highly_probable"
        confidence = 0.93
    elif psa >= PSA_VERY_HIGH and (
        locally_advanced or metastatic_imaging or severe_bone_pain
    ):
        tier = "probable"
        confidence = 0.85
    elif (
        psa >= PSA_HIGH
        and locally_advanced
        and (severe_bone_pain or significant_weight_loss)
    ):
        tier = "possible"
        confidence = 0.65
    else:
        tier = "none"
        confidence = 0.0

    # ADT empírico: NCCN PROS-G — justificable cuando:
    #   - tier ∈ (highly_probable, virtually_certain) AND biopsia diferida
    #   - tier == probable AND (dolor óseo severo O emergencia activa)
    has_cord_compression = _txt(payload, "spinal_cord_compression") in {"sí", "si"}
    has_severe_obstruction = "bilateral con ira" in _txt(
        payload, "obstructive_uropathy_severity"
    )
    active_emergency = has_cord_compression or has_severe_obstruction

    allow_empiric_adt = False
    if not histology_confirmed:
        if tier in ("highly_probable", "virtually_certain") and histology_pending:
            allow_empiric_adt = True
        elif tier == "probable" and (severe_bone_pain or active_emergency):
            allow_empiric_adt = True

    # Prioridad de biopsia
    if tier == "virtually_certain":
        biopsy_priority = "urgent_or_alternative_site"
    elif tier == "highly_probable":
        biopsy_priority = "urgent_within_7d"
    elif tier in ("probable", "possible"):
        biopsy_priority = "within_2_weeks"
    else:
        biopsy_priority = "standard"

    return {
        "tier": tier,
        "basis": basis,
        "confidence": confidence,
        "allow_empiric_adt": allow_empiric_adt,
        "biopsy_priority": biopsy_priority,
        "psa_value": psa,
        "locally_advanced_dre": locally_advanced,
        "metastatic_imaging_signal": metastatic_imaging,
    }


def empiric_adt_protocol(payload: dict, provisional: dict) -> dict | None:
    """Retorna protocolo de ADT empírico recomendado, o ``None`` si no aplica.

    Si hay compresión medular o uropatía obstructiva severa → antagonista
    LHRH (degarelix) preferente por descenso rápido sin flare.
    Caso estándar: agonista LHRH (leuprolide) + bicalutamida 14 d flare protection.
    """
    if not isinstance(provisional, dict) or not provisional.get("allow_empiric_adt"):
        return None

    cord_compression = _txt(payload, "spinal_cord_compression") in {"sí", "si"}
    severe_obstruction = "bilateral con ira" in _txt(
        payload, "obstructive_uropathy_severity"
    )
    needs_rapid_descent = cord_compression or severe_obstruction

    if needs_rapid_descent:
        return {
            "regimen": (
                "Antagonista LHRH (degarelix 240 mg SC dosis única, "
                "luego 80 mg c/28 d)"
            ),
            "rationale": (
                "Descenso rápido de testosterona sin flare. Indicado en "
                "compresión medular o uropatía obstructiva severa donde el "
                "flare puede agravar la emergencia."
            ),
            "alternative": (
                "Relugolix 360 mg VO día 1, luego 120 mg/día (oral, sin flare)"
            ),
            "evidence_tag": "stampede_2017",
            "duration": (
                "Continuo hasta confirmación histológica + planificación definitiva"
            ),
            "monitoring": [
                "Testosterona <50 ng/dL en 2-4 sem",
                "PSA cada 4-6 sem",
                "DEXA basal",
                "Perfil metabólico/lipídico",
            ],
        }

    return {
        "regimen": (
            "Agonista LHRH (leuprolide 7.5 mg SC mensual o 22.5 mg trimestral) "
            "+ bicalutamida 50 mg/d × 14 d (flare protection)"
        ),
        "rationale": (
            "Régimen estándar pre-biopsia cuando histología se demora ≥7 días "
            "o el paciente tiene síntomas que justifican inicio. NCCN PROS-G v5.2026."
        ),
        "alternative": (
            "Antagonista (degarelix/relugolix) si paciente prefiere evitar bicalutamida"
        ),
        "evidence_tag": "nccn_pros_g",
        "duration": (
            "Continuo hasta confirmación histológica + planificación definitiva"
        ),
        "monitoring": [
            "Testosterona <50 ng/dL en 4-8 sem",
            "PSA cada 4-6 sem",
            "DEXA basal",
            "Perfil metabólico/lipídico",
        ],
    }
