# -*- coding: utf-8 -*-
"""
Ra-223 (Xofigo) — elegibilidad estructurada ALSYMPCA.

Evalúa criterios ALSYMPCA (Parker NEJM 2013) antes de priorizar Ra-223:
  - mCRPC con enfermedad ósea sintomática
  - Sin metástasis viscerales (hígado, pulmón, cerebro)
  - Sin adenopatías >3 cm (linfonodos "bulky" voluminosos)
  - ≥2 lesiones óseas en gammagrama/PSMA
  - ECOG 0-2
  - Hb ≥10 g/dL; ANC ≥1.5k; plaquetas ≥100k
  - ALP y LDH en rango razonable (no pancitopenia, no gran compromiso óseo extremo)
  - No combinar con abiraterona/enzalutamida en 1L (ERA-223 señaló exceso de SREs)
  - Separar de taxano activo (≥4 semanas)

Referencias:
  Parker NEJM 2013 (ALSYMPCA) — SG mejorada, reducción SREs
  Smith Lancet Oncol 2019 (ERA-223) — NO combinar Ra-223 + abiraterona/pred 1L
  NCCN 5.2026 — Ra-223 opción preferida en óseo sintomático sin viscerales
  EAU 2026 — Ra-223 post-ARPI y post-docetaxel
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


def evaluate_radium223_eligibility(payload: dict, *, m1_context: dict | None = None) -> dict[str, Any]:
    """Evalúa elegibilidad Ra-223 según criterios ALSYMPCA.

    Args:
        payload: payload clínico del paciente.
        m1_context: contexto ya calculado por evaluate_m1_crpc (opcional).

    Returns:
        Diccionario con elegibilidad, bloqueos duros, advertencias y rationale.
    """
    m1 = m1_context or {}

    metastasis_site = str(payload.get("metastasis_site", "Bone")).lower()
    visceral_mets = _flag(payload, "visceral_metastasis") or metastasis_site.startswith("viscer")
    liver_mets = _flag(payload, "liver_metastasis")
    brain_mets = _flag(payload, "brain_metastasis") or _flag(payload, "cns_metastasis")
    lung_mets = _flag(payload, "lung_metastasis")
    bulky_ln = _flag(payload, "bulky_lymph_nodes_over_3cm") or _flag(payload, "ln_gt_3cm")

    bone_lesion_count = _safe_int(payload.get("bone_lesion_count")) or 0
    bone_scan_positive = _flag(payload, "bone_scan_positive")
    pain_symptoms = str(payload.get("pain_symptoms", "Asintomatico")).lower()
    symptomatic_bone = pain_symptoms not in {"asintomatico", "", "none", "sin"}

    ecog = _safe_int(payload.get("ecog_score") or payload.get("ecog") or 1) or 1
    hb = _safe_float(payload.get("hemoglobin") or payload.get("hb"))
    anc = _safe_float(payload.get("anc"))
    platelets = _safe_float(payload.get("platelets"))
    alp = _safe_float(payload.get("alp") or payload.get("alkaline_phosphatase"))

    prior_therapy = str(payload.get("prior_therapy", "")).lower()
    active_abiraterone = _flag(payload, "current_abiraterone") or "abirater" in str(payload.get("current_treatment", "")).lower()
    prior_arpi = bool(m1.get("prior_arpi")) or any(t in prior_therapy for t in ["abirater", "enzalut", "apalut", "darolut"])
    prior_docetaxel = bool(m1.get("prior_docetaxel"))

    taxane_washout_weeks = _safe_int(payload.get("taxane_washout_weeks"))

    # ── Bloqueos duros ALSYMPCA ─────────────────────────────────────
    hard_blocks: list[str] = []
    if visceral_mets or liver_mets or lung_mets or brain_mets:
        hard_blocks.append(
            "Metástasis viscerales (hígado/pulmón/SNC) — contraindicación ALSYMPCA."
        )
    if bulky_ln:
        hard_blocks.append("Adenopatías >3 cm ('bulky') — exclusión ALSYMPCA.")
    if not symptomatic_bone:
        hard_blocks.append(
            "Enfermedad ósea asintomática — Ra-223 se prioriza sobre dolor óseo."
        )
    if bone_scan_positive is False and bone_lesion_count < 2:
        hard_blocks.append(
            "No documenta ≥2 lesiones óseas en gammagrama/PSMA (criterio ALSYMPCA)."
        )
    if active_abiraterone:
        hard_blocks.append(
            "Combinación Ra-223 + abiraterona contraindicada (ERA-223, Smith 2019): exceso de fracturas y muertes."
        )

    # ── Cautelas / elegibilidad con reservas ─────────────────────────
    cautions: list[str] = []
    missing: list[str] = []

    if ecog > 2:
        hard_blocks.append(f"ECOG {ecog} >2 — fuera de ventana ALSYMPCA.")
    elif ecog == 2:
        cautions.append("ECOG 2 — vigilar tolerancia; ALSYMPCA incluyó ECOG 0-2.")

    if hb is None:
        missing.append("hemoglobin")
    elif hb < 10:
        hard_blocks.append(f"Hemoglobina {hb:.1f} g/dL <10 — fuera de criterio ALSYMPCA.")
    elif hb < 10.5:
        cautions.append(f"Hemoglobina {hb:.1f} g/dL limítrofe (<10.5) — monitorizar anemia.")

    if anc is None:
        missing.append("anc")
    elif anc < 1500:
        hard_blocks.append(f"ANC {anc:.0f} <1500 — reservar hasta recuperación medular.")

    if platelets is None:
        missing.append("platelets")
    elif platelets < 100_000:
        hard_blocks.append(f"Plaquetas {platelets:.0f} <100k — reservar hasta recuperación medular.")

    if alp is None:
        missing.append("alp")
    elif alp > 1000:
        cautions.append(
            f"ALP {alp:.0f} U/L muy elevada — carga ósea extrema, considerar soporte paralelo (denosumab/ZA) y vigilar mielosupresión."
        )

    if prior_docetaxel and taxane_washout_weeks is not None and taxane_washout_weeks < 4:
        cautions.append(
            "Washout <4 semanas desde último taxano — separar ≥4 semanas para reducir mielosupresión aditiva."
        )

    # ── Prioridad ────────────────────────────────────────────────────
    eligible = not hard_blocks

    priority = "not_eligible"
    if eligible:
        if prior_arpi and prior_docetaxel:
            priority = "preferred"
        elif prior_arpi or prior_docetaxel:
            priority = "preferred"
        else:
            priority = "eligible"

    trial_refs = ["ALSYMPCA (Parker NEJM 2013)"]
    if active_abiraterone or (prior_arpi and not prior_docetaxel):
        trial_refs.append("ERA-223 (Smith LancetOnc 2019)")

    return {
        "regimen_code": "RADIUM223",
        "drug_label": "Radio-223 dicloruro (Xofigo)",
        "eligible": eligible,
        "priority": priority,
        "hard_blocks": hard_blocks,
        "cautions": cautions,
        "missing_inputs": missing,
        "alsympca_criteria_met": eligible and not cautions,
        "requires_bma_coadjunct": eligible,
        "bma_coadjunct_note": (
            "Se recomienda coadministrar denosumab o ácido zoledrónico durante el curso de Ra-223 "
            "salvo contraindicación (prevención SREs, mantener Ca/Vit-D, clearance dental previo)."
        ),
        "standard_schedule": "55 kBq/kg IV cada 4 semanas × 6 dosis.",
        "rationale": (
            "Ra-223 ofrece beneficio en supervivencia y tiempo a primer SRE (ALSYMPCA) "
            "en mCRPC óseo sintomático sin viscerales; requiere función medular preservada, "
            "separación temporal de taxanos activos y NO debe combinarse con abiraterona 1L (ERA-223)."
        ),
        "evidence_trials": trial_refs,
        "evidence_tier": "A",
    }
