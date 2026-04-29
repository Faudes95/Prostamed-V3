# -*- coding: utf-8 -*-
"""
Post-PARP progression — sequencing tras fallo a inhibidor PARP.

Hoy no hay estándar categoría 1 después de progresión a PARP; las decisiones
se orientan por:

- Exposición previa a ARPI y taxanos (define si quedan clases activas).
- Estado PSMA+ y VISION/PSMAfore elegibilidad (Lu-177 tras PARP es
  especialmente atractivo porque no comparte mecanismo).
- Reserva medular: la mielotoxicidad acumulada post-PARP reduce tolerancia
  a subsiguiente carboplatino o Ra-223.
- Biomarcador dominante: BRCA2 con alteración ctDNA emergente puede
  reingresar a platino tras 6-12 m desde última PARP.
- Ensayos abiertos: AKT/CDK7/NEPC-targeted.

Orden de preferencia general (pre-taxano post-ARPI, sin NEPC):

  1. Cabazitaxel (CARD, Sartor 2019) si paciente naive a docetaxel y CARD
     criteria met; si ya hubo docetaxel también prevalece sobre ARPI rechallenge.
  2. Lu-177 PSMA-617 si VISION/PSMAfore elegible (PSMA+ confirmado).
  3. Platino (carboplatino ± etopósido) en BRCA2/ATM con resistencia emergente
     y sin mielosupresión limitante.
  4. Ensayo clínico (CDK7, AR degraders, AKT, Bispecifics).
  5. Radio-223 si óseo sintomático sin viscerales y ALSYMPCA-compliant.

Referencias:
  de Wit NEJM 2019 (CARD)
  Sartor NEJM 2021 (VISION)
  Morris Lancet 2024 (PSMAfore)
  Mateo Ann Oncol 2020 (post-PARP sequencing observational)
  Schmid J Clin Oncol 2022 (platinum rechallenge)
  NCCN PROS-11 v5.2026
"""
from __future__ import annotations

from typing import Any


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _prior_parp_exposure(payload: dict, m1: dict) -> bool:
    if _flag(payload, "prior_parp_inhibitor") or _flag(payload, "prior_parp_exposure"):
        return True
    prior = str(payload.get("prior_therapy", "")).lower()
    return any(tok in prior for tok in ["olapar", "rucapar", "talazopar", "nirapar"])


def evaluate_post_parp_sequencing(
    payload: dict,
    *,
    m1_context: dict | None = None,
    vision_bundle: dict | None = None,
    nepc_bundle: dict | None = None,
) -> dict[str, Any]:
    """Propone secuencia post-PARP priorizando mecanismos ortogonales.

    Args:
        payload: payload clínico completo.
        m1_context: contexto ya calculado por evaluate_m1_crpc (opcional).
        vision_bundle: salida de evaluate_vision_eligibility (opcional).
        nepc_bundle: salida de evaluate_nepc_pathway (opcional).

    Returns:
        dict con lista ordenada de candidatos + rationale + missing inputs.
    """
    m1 = m1_context or {}
    vision = vision_bundle or {}
    nepc = nepc_bundle or {}

    prior_parp = _prior_parp_exposure(payload, m1)
    if not prior_parp:
        return {
            "applicable": False,
            "prior_parp": False,
            "candidates": [],
            "rationale": "Sin exposición previa a PARPi — no aplica secuenciación post-PARP.",
        }

    prior_docetaxel = bool(m1.get("prior_docetaxel"))
    prior_abiraterone = bool(m1.get("prior_abiraterone"))
    prior_arpi = bool(m1.get("prior_arpi"))
    card_applicable = prior_arpi and prior_docetaxel
    hrr_gene = str(m1.get("hrr_gene") or payload.get("hrr_gene", "")).strip().upper()

    psa = _safe_float(payload.get("psa_current") or payload.get("psa"))
    hb = _safe_float(payload.get("hemoglobin") or payload.get("hb"))
    platelets = _safe_float(payload.get("platelets"))
    anc = _safe_float(payload.get("anc"))
    platinum_rechallenge_tolerable = (
        (hb is None or hb >= 9.0)
        and (platelets is None or platelets >= 100_000)
        and (anc is None or anc >= 1500)
    )

    symptomatic_bone_only = bool(m1.get("symptomatic_bone_only"))
    visceral_mets = _flag(payload, "visceral_metastasis") or str(
        payload.get("metastasis_site", "")
    ).lower().startswith("viscer")

    # Tiempo desde última exposición PARP (si se reporta)
    months_since_parp = _safe_float(payload.get("months_since_last_parp"))

    candidates: list[dict[str, Any]] = []
    missing: list[str] = []

    # ── 1. Cabazitaxel (CARD) ────────────────────────────────────────
    if card_applicable:
        note_parts = [
            "CARD (de Wit NEJM 2019) — cabazitaxel superó intercambio ARPI-ARPI tras docetaxel y ARPI previo; "
            "tras PARP es la ruta con mejor evidencia mecanísticamente ortogonal."
        ]
        prior_arpi_duration = _safe_float(payload.get("prior_arpi_duration_months"))
        if prior_arpi_duration is None:
            note_parts.append("Duración de ARPI previo no documentada — verificar ≥6 meses.")
            missing.append("prior_arpi_duration_months")
        elif prior_arpi_duration < 6:
            note_parts.append(
                f"Duración ARPI previo {prior_arpi_duration:.0f} meses <6 — CARD requería ≥6 meses."
            )
        candidates.append(
            {
                "regimen_code": "CABAZITAXEL",
                "drug_label": "Cabazitaxel",
                "priority": "preferred",
                "rank_reason": "Mecánica ortogonal al PARP tras docetaxel + ARPI previo.",
                "notes": " ".join(note_parts),
                "evidence_trials": ["CARD (de Wit NEJM 2019)", "TROPIC (de Bono Lancet 2010)"],
                "evidence_tier": "A",
            }
        )
    elif not prior_docetaxel:
        candidates.append(
            {
                "regimen_code": "DOCETAXEL",
                "drug_label": "Docetaxel",
                "priority": "preferred" if prior_arpi else "eligible",
                "rank_reason": "Taxano aún disponible tras PARP — clase activa con evidencia robusta en mCRPC.",
                "notes": (
                    "Tras PARP la prioridad se mueve a taxano si el paciente sigue naïve a quimioterapia; "
                    "verificar CBC/LFT/neuropatía antes de iniciar."
                ),
                "evidence_trials": ["TAX 327 (Tannock NEJM 2004)"],
                "evidence_tier": "A",
            }
        )

    # ── 2. Lu-177 PSMA-617 (VISION/PSMAfore) ─────────────────────────
    vision_priority = str(vision.get("priority") or "")
    if vision_priority == "preferred":
        candidates.append(
            {
                "regimen_code": "LU177_PSMA617",
                "drug_label": "Lutecio-177 PSMA-617 (Pluvicto)",
                "priority": "preferred",
                "rank_reason": "Radioligando con mecanismo ortogonal al PARP y elegibilidad VISION/PSMAfore plena.",
                "notes": (
                    "Tras progresión a PARP, Lu-177 PSMA-617 mantiene beneficio independiente del estado HRR; "
                    "vigilar xerostomía, nefrotoxicidad y mielotoxicidad acumulativa post-PARP."
                ),
                "evidence_trials": vision.get("trial_refs") or ["VISION (Sartor NEJM 2021)"],
                "evidence_tier": "A",
            }
        )
    elif vision_priority == "selected_candidate":
        candidates.append(
            {
                "regimen_code": "LU177_PSMA617",
                "drug_label": "Lutecio-177 PSMA-617 (Pluvicto)",
                "priority": "selected_candidate",
                "rank_reason": "Elegibilidad PSMA parcial — requiere completar SUV per-lesión e hígado antes de priorizar.",
                "notes": (
                    "Post-PARP el radioligando sigue siendo atractivo por mecanismo ortogonal; completar "
                    "documentación PSMA estructurada antes de confirmar la ruta."
                ),
                "evidence_trials": ["VISION (Sartor NEJM 2021)", "PSMAfore (Morris Lancet 2024)"],
                "evidence_tier": "B",
                "missing_inputs": list(vision.get("missing_inputs") or []),
            }
        )
        missing.extend(list(vision.get("missing_inputs") or []))

    # ── 3. Platino ± etopósido (BRCA2/ATM rechallenge o NEPC confirmado) ─
    eligible_platinum_rechallenge = (
        platinum_rechallenge_tolerable
        and hrr_gene in {"BRCA1", "BRCA2", "ATM", "PALB2"}
        and (months_since_parp is None or months_since_parp >= 6)
    )
    if nepc.get("nepc_confirmed") or nepc.get("nepc_suspected"):
        priority = "preferred" if nepc.get("nepc_confirmed") else "selected_candidate"
        candidates.append(
            {
                "regimen_code": "CARBOPLATIN_ETOPOSIDE_NEPC",
                "drug_label": "Carboplatino + Etopósido (NEPC post-PARP)",
                "priority": priority,
                "rank_reason": "Transformación neuroendocrina sospechada/confirmada — platino es estándar por mecanismo independiente de AR.",
                "notes": (
                    "Post-PARP en NEPC la mielotoxicidad acumulada exige carboplatino a AUC 5 y CBC semanal "
                    "durante los primeros 2 ciclos."
                ),
                "evidence_trials": ["Aparicio CCR 2013", "Aggarwal JCO 2018"],
                "evidence_tier": "B",
            }
        )
    elif eligible_platinum_rechallenge:
        candidates.append(
            {
                "regimen_code": "CARBOPLATIN_ETOPOSIDE",
                "drug_label": "Carboplatino ± Etopósido (rechallenge HRR)",
                "priority": "selected_candidate",
                "rank_reason": "BRCA/HRR+ con reserva medular preservada — platino rechallenge puede ser activo.",
                "notes": (
                    "Schmid JCO 2022 documentó respuestas parciales en mCRPC BRCA+ tras PARP con carboplatino; "
                    "evidencia observacional, priorizar ensayo si está disponible."
                ),
                "evidence_trials": ["Schmid JCO 2022 (observacional)", "Mateo Ann Oncol 2020"],
                "evidence_tier": "C",
            }
        )
    elif hrr_gene in {"BRCA1", "BRCA2", "ATM", "PALB2"} and not platinum_rechallenge_tolerable:
        if hb is None:
            missing.append("hemoglobin")
        if platelets is None:
            missing.append("platelets")
        if anc is None:
            missing.append("anc")

    # ── 4. Ra-223 si óseo sintomático aislado ────────────────────────
    if symptomatic_bone_only and not visceral_mets:
        candidates.append(
            {
                "regimen_code": "RADIUM223",
                "drug_label": "Radio-223 dicloruro (Xofigo)",
                "priority": "eligible",
                "rank_reason": "Óseo sintomático aislado — alternativa en post-PARP con ALSYMPCA criteria.",
                "notes": (
                    "Separar ≥4 semanas de quimioterapia activa; no combinar con abiraterona 1L; vigilar "
                    "mielotoxicidad acumulada post-PARP."
                ),
                "evidence_trials": ["ALSYMPCA (Parker NEJM 2013)"],
                "evidence_tier": "A",
            }
        )

    # ── 5. Ensayo clínico siempre disponible como línea ──────────────
    candidates.append(
        {
            "regimen_code": "CLINICAL_TRIAL_POST_PARP",
            "drug_label": "Ensayo clínico dirigido post-PARP",
            "priority": "eligible",
            "rank_reason": "Sin estándar categoría 1 post-PARP — ensayos AKT/CDK7/AR degraders/bispecifics son opción prioritaria.",
            "notes": (
                "Consultar matching ClinicalTrials.gov (PROfound-like, CAPItello, RADAR ensayos activos). "
                "Priorizar cuando existe biomarcador accionable sin fármaco aprobado."
            ),
            "evidence_trials": ["NCCN PROS-11 v5.2026"],
            "evidence_tier": "D",
        }
    )

    # Ranking final — priority → orden de lista → drug_label
    priority_weight = {"preferred": 0, "selected_candidate": 1, "eligible": 2, "not_eligible": 3}
    candidates.sort(key=lambda c: (priority_weight.get(c.get("priority", "eligible"), 4),))

    return {
        "applicable": True,
        "prior_parp": True,
        "card_applicable": card_applicable,
        "platinum_rechallenge_tolerable": platinum_rechallenge_tolerable,
        "months_since_last_parp": months_since_parp,
        "candidates": candidates,
        "missing_inputs": list(dict.fromkeys(missing)),
        "rationale": (
            "Post-PARP la prioridad es mecanismo ortogonal: cabazitaxel (CARD), Lu-177 PSMA-617 "
            "(VISION/PSMAfore) y rechallenge platino en BRCA/HRR+ con reserva medular; Ra-223 reservado "
            "para óseo aislado y ensayo clínico como ruta transversal."
        ),
    }


__all__ = ["evaluate_post_parp_sequencing"]
