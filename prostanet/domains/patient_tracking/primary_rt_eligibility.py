# -*- coding: utf-8 -*-
"""
EPIC 9 Group D (GAP-6) — RT al primario en mHSPC (STAMPEDE-H / PEACE-1).

Evalúa elegibilidad estructurada para radioterapia al tumor primario en
enfermedad metastásica hormonosensible (mHSPC) sincrónica o metacrónica de
bajo volumen y oligometastásica.

Evidencia pivotal:
  * STAMPEDE Arm H — Parker CC et al. *Lancet* 2018;392:2353–2366
        OS HR 0.68 (95% CI 0.52-0.90) en bajo volumen; neutro en alto volumen.
  * PEACE-1 RT-al-primario — Bossi A et al. *Lancet* 2024;404:1345-1356
        Control locorregional; no mejora OS pero sí PFS clínico en low-volume.
  * NCCN Prostate v5.2026 PROS-14 — RT al primario category 1 en mHSPC de bajo
        volumen.
  * EAU 2026 §6.4 — RT al primario "should be offered" en bajo volumen si
        life_expectancy ≥3 años y ECOG ≤2.

Reglas:
  - Hard-block si volumen = HIGH (STAMPEDE-H mostró ausencia de beneficio en OS).
  - Hard-block si ECOG >2 (fuera de criterios trial).
  - Hard-block si life_expectancy_years <3 (RT no añade valor con expectativa
    corta; AUA/ASTRO/SUO 2024 salvage extrapolación).
  - Caution si metachronous_metastasis=True (STAMPEDE-H enroló ambos; sin
    estratificación prospectiva consolidada, NCCN PROS-14 mantiene offer).
  - Caution si prior prostate RT o RP previa (no recandidato a RT primario).

Patrón canónico heredado de `m1_crpc/rules_radium223.py::evaluate_radium223_eligibility`.
"""
from __future__ import annotations

from typing import Any


_TRUTHY = {"1", "true", "yes", "si", "sí"}


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in _TRUTHY


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


def _canonicalize_volume(payload: dict) -> str:
    """Devuelve 'low' | 'high' | 'oligo' | 'unknown' a partir de payload."""
    explicit = str(payload.get("volume_status") or payload.get("metastatic_burden") or "").strip().lower()
    if explicit in {"low", "bajo", "low_volume", "low-volume"}:
        return "low"
    if explicit in {"high", "alto", "high_volume", "high-volume"}:
        return "high"
    if explicit in {"oligo", "oligometastatic", "oligometastásico", "oligometastasico"}:
        return "oligo"
    # Heurística secundaria: ≥4 lesiones óseas + 1 visceral o ≥3 óseas con
    # carga axial extendida se consideran high volume (criterios CHAARTED).
    bone_count = _safe_int(payload.get("bone_lesion_count") or payload.get("metastasis_count")) or 0
    visceral = _flag(payload, "visceral_metastasis") or _flag(payload, "visceral_metastases")
    if bone_count >= 4 and visceral:
        return "high"
    if bone_count >= 4:
        return "high"
    if 1 <= bone_count <= 3:
        return "oligo"
    return "unknown"


def _canonicalize_temporality(payload: dict) -> str:
    """'synchronous' | 'metachronous' | 'unknown'."""
    explicit = str(payload.get("disease_temporality") or "").strip().lower()
    if explicit in {"sync", "synchronous", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "synchronous"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "metachronous"
    if _flag(payload, "metachronous_metastasis"):
        return "metachronous"
    if _flag(payload, "synchronous_metastasis") or _flag(payload, "de_novo_metastatic"):
        return "synchronous"
    return "unknown"


def evaluate_primary_rt(payload: dict | None = None) -> dict[str, Any]:
    """Evalúa elegibilidad para radioterapia al tumor primario en mHSPC.

    Args:
        payload: payload clínico del paciente (mismo shape que los servicios
            `mcspc_low_volume_sync_oligo` / `mcspc_oligo_metachronous`).

    Returns:
        Diccionario con:
            * regimen_code: "RT_TO_PRIMARY"
            * drug_label: etiqueta clínica
            * eligible: bool
            * priority: "standard_of_care" | "offerable" | "caution" | "not_eligible"
            * hard_blocks: list[str]
            * cautions: list[str]
            * missing_inputs: list[str]
            * evidence_trials: list[str]
            * evidence_tier: "A" (pivotal positive OS) | "B" (extrapolación)
            * rationale: narrativa clínica
            * volume_status: 'low' | 'high' | 'oligo' | 'unknown'
            * temporality: 'synchronous' | 'metachronous' | 'unknown'
    """
    payload = dict(payload or {})

    volume = _canonicalize_volume(payload)
    temporality = _canonicalize_temporality(payload)
    ecog = _safe_int(payload.get("ecog_score") or payload.get("ecog") or 1) or 1
    le_years = _safe_float(payload.get("life_expectancy_years"))
    prior_prostate_rt = _flag(payload, "prior_radiation") or _flag(payload, "rt_primary_received") or _flag(payload, "prior_prostate_rt")
    prior_prostatectomy = _flag(payload, "prior_prostatectomy") or _flag(payload, "rp_received")

    hard_blocks: list[str] = []
    cautions: list[str] = []
    missing: list[str] = []

    # ── Hard-blocks ───────────────────────────────────────────────────
    if volume == "high":
        hard_blocks.append(
            "Alto volumen metastásico (STAMPEDE-H subanálisis 2018): la RT al "
            "primario NO mejora supervivencia global en este subgrupo."
        )
    if ecog > 2:
        hard_blocks.append(
            f"ECOG {ecog} >2 — fuera de criterios STAMPEDE-H / PEACE-1 para RT al primario."
        )
    if le_years is not None and le_years < 3:
        hard_blocks.append(
            f"Expectativa de vida {le_years:.1f} años (<3) — beneficio en PFS/OS se "
            "acumula a lo largo de ≥3 años; no justifica toxicidad de RT primario."
        )
    if prior_prostate_rt:
        hard_blocks.append(
            "RT prostática previa documentada — no re-candidato a RT al primario como "
            "intensificación local inicial en mHSPC."
        )
    if prior_prostatectomy:
        hard_blocks.append(
            "Prostatectomía radical previa — RT al primario ya no aplica como "
            "intensificación local del tumor primario en mHSPC."
        )

    # ── Cautelas ──────────────────────────────────────────────────────
    if volume == "unknown":
        missing.append("volume_status")
        cautions.append(
            "Volumen metastásico no documentado — confirmar clasificación "
            "CHAARTED (alto: ≥4 óseas con ≥1 axial extra-pélvica o viscerales) "
            "antes de asegurar elegibilidad."
        )
    if temporality == "unknown":
        missing.append("disease_temporality")
    elif temporality == "metachronous":
        cautions.append(
            "Enfermedad metacrónica — STAMPEDE-H enroló ambos contextos; "
            "NCCN PROS-14 mantiene oferta pero la fuerza de recomendación es "
            "menor que en sincrónica de novo."
        )
    if le_years is None:
        missing.append("life_expectancy_years")
        cautions.append(
            "Expectativa de vida no documentada — requerida para confirmar "
            "threshold de 3 años (NCCN PROS-14 / EAU 2026 §6.4)."
        )

    # ── Prioridad ─────────────────────────────────────────────────────
    eligible = not hard_blocks
    priority = "not_eligible"
    if eligible:
        if volume == "low" and temporality == "synchronous" and ecog <= 1 and (le_years is None or le_years >= 5):
            # Perfil canónico STAMPEDE-H: bajo volumen + sincrónico + fit → estándar.
            priority = "standard_of_care"
        elif volume in {"low", "oligo"} and temporality in {"synchronous", "unknown"}:
            priority = "offerable"
        elif volume in {"low", "oligo"} and temporality == "metachronous":
            priority = "caution"
        else:
            priority = "caution"

    # ── Evidencia ─────────────────────────────────────────────────────
    evidence_trials = [
        "STAMPEDE-H (Parker Lancet 2018)",
        "PEACE-1 RT-primario (Bossi Lancet 2024)",
        "NCCN 5.2026 PROS-14",
        "EAU 2026 §6.4",
    ]
    evidence_tier = "A" if priority == "standard_of_care" else ("B" if eligible else "N/A")

    # ── Rationale ─────────────────────────────────────────────────────
    if priority == "standard_of_care":
        rationale = (
            "STAMPEDE Arm H demostró beneficio en OS (HR 0.68) con RT al primario "
            "en mHSPC sincrónico de bajo volumen; NCCN 5.2026 (categoría 1) y "
            "EAU 2026 respaldan como estándar en pacientes fit con expectativa ≥3 años."
        )
    elif priority == "offerable":
        rationale = (
            "RT al primario debe ofrecerse como intensificación local; el balance "
            "clínico requiere confirmar volumen/temporalidad y la preferencia del "
            "paciente antes de priorizar frente al doblete sistémico."
        )
    elif priority == "caution":
        rationale = (
            "RT al primario sigue siendo discutible, pero el contexto "
            "(metacrónico / volumen no plenamente claro) reduce la fuerza de la "
            "recomendación respecto a STAMPEDE-H; individualizar con el paciente."
        )
    else:
        rationale = (
            "RT al primario NO aplica como estrategia de intensificación inicial "
            "en este escenario por los bloqueos clínicos documentados."
        )

    return {
        "regimen_code": "RT_TO_PRIMARY",
        "drug_label": "Radioterapia externa al tumor primario",
        "eligible": eligible,
        "priority": priority,
        "hard_blocks": hard_blocks,
        "cautions": cautions,
        "missing_inputs": missing,
        "volume_status": volume,
        "temporality": temporality,
        "ecog": ecog,
        "life_expectancy_years": le_years,
        "evidence_trials": evidence_trials,
        "evidence_tier": evidence_tier,
        "rationale": rationale,
        "standard_dose_note": (
            "Esquema STAMPEDE-H: 55 Gy en 20 fracciones en 4 semanas, o 36 Gy en "
            "6 fracciones semanales (hipofraccionado). Integrar timing con ADT/ARPI."
        ),
    }


__all__ = ["evaluate_primary_rt"]
