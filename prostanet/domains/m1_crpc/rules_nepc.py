# -*- coding: utf-8 -*-
"""
NEPC (carcinoma neuroendocrino de próstata) — detección y ruta terapéutica.

Distingue tres rutas:

1. **Sospecha** (lineage plasticity pre-transformación): TP53 + RB1 altered,
   viscerales, LDH ↑, NSE ↑, CgA ↑, PSA discordantemente bajo para carga.
   → biopsia direccionada al sitio viscerales/ganglionar con IHC neuroendocrina.

2. **Confirmación histológica**: IHC positiva para sinaptofisina y/o
   cromogranina A (con o sin pérdida de AR, con o sin Ki-67 alto).
   t-NEPC (post-ADT/ARPI prolongado) vs NEPC de novo.
   → régimen platino-etopósido o platino-docetaxel.

3. **Rescate platino**: post-progresión a primera línea platino;
   re-inducción o cambio a esquema alterno (cisplatin↔carboplatin,
   adición de topotecan o sensibilizantes como auranofin en ensayo).

Referencias principales:
  - Aparicio *Clin Cancer Res* 2013;19:3621 (EP-16 platinum prostate cancer trial)
  - Beltran *JCO* 2014;32:3383 (molecular characterization t-NEPC)
  - Beltran *Nat Med* 2016 (genomic landscape NEPC — TP53, RB1, AURKA, MYCN)
  - Aggarwal *JCO* 2018;36:2492 (clinical trial criteria prospectivos NEPC)
  - Labrecque *J Clin Invest* 2019 (molecular subtypes)
  - NCCN PCa v5.2026 PROS-J (small cell / NEPC variant histology)
  - EAU 2026 §6.13 (histología agresiva)
"""
from __future__ import annotations

from typing import Any

# Umbrales comúnmente usados como anclas clínicas (no son categoría 1 por sí
# solos, pero alimentan el score de sospecha junto con hallazgos moleculares).
NSE_UPPER_LIMIT = 16.3  # μg/L (ng/mL), laboratorios estándar
CHROMOGRANIN_A_UPPER_LIMIT = 100  # ng/mL
LDH_UPPER_LIMIT = 250  # U/L
CEA_UPPER_LIMIT = 5  # ng/mL (no específico, usado como corroboración)

# Scoring Aggarwal 2018 simplificado — no es diagnóstico por sí solo pero
# orienta qué pacientes ameritan biopsia dirigida con IHC neuroendocrina.
AGGARWAL_CRITERIA = {
    "visceral_without_bone_progression": 1,
    "tp53_rb1_altered": 2,   # señal molecular más fuerte
    "bulky_lymphadenopathy": 1,
    "nse_elevated": 1,
    "ldh_elevated": 1,
    "psa_discordant_low": 1,
    "neuroendocrine_features_clinical": 2,
}

# Score ≥3 activa sospecha intensa; score ≥5 justifica biopsia aun sin
# confirmación previa.
SUSPICION_SCORE_THRESHOLD = 3
BIOPSY_TRIGGER_THRESHOLD = 5


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _status_positive(payload: dict, key: str) -> bool:
    val = str(payload.get(key, "Desconocido")).lower()
    return val.startswith("pos") or val in {
        "detected",
        "detectado",
        "mutado",
        "loss",
        "perdida",
        "biallelic",
        "bialélico",
        "altered",
    }


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


def evaluate_nepc_pathway(payload: dict, *, m1_context: dict | None = None) -> dict[str, Any]:
    """Evalúa sospecha, confirmación y régimen platino para NEPC.

    Args:
        payload: payload clínico completo.
        m1_context: contexto ya calculado por evaluate_m1_crpc (opcional).

    Returns:
        dict con sospecha, confirmación IHC, régimen sugerido, y rationale.
    """
    m1 = m1_context or {}

    # ── Moleculares ─────────────────────────────────────────────────
    tp53_altered = bool(m1.get("tp53_altered")) or _status_positive(payload, "tp53_status")
    rb1_loss = bool(m1.get("rb1_loss")) or _status_positive(payload, "rb1_status")
    tp53_rb1 = tp53_altered and rb1_loss

    # ── Clínicos / laboratorio ──────────────────────────────────────
    neuroendocrine_features = bool(m1.get("neuroendocrine_features")) or _flag(
        payload, "neuroendocrine_features"
    )
    visceral_without_bone = _flag(payload, "visceral_without_bone_progression") or (
        _flag(payload, "visceral_metastasis") and not _flag(payload, "bone_progression")
    )
    bulky_ln = _flag(payload, "bulky_lymph_nodes_over_3cm") or _flag(payload, "ln_gt_3cm")

    nse = _safe_float(payload.get("nse") or payload.get("neuron_specific_enolase"))
    cga = _safe_float(payload.get("chromogranin_a") or payload.get("cga"))
    ldh = _safe_float(payload.get("ldh") or payload.get("lactate_dehydrogenase"))
    psa_discordant_low = _flag(payload, "psa_discordant_low")

    # ── IHC confirmatoria ───────────────────────────────────────────
    synaptophysin = (
        _flag(payload, "ihc_synaptophysin_positive")
        or str(payload.get("ihc_synaptophysin", "")).lower().startswith("pos")
    )
    chromogranin_ihc = (
        _flag(payload, "ihc_chromogranin_positive")
        or str(payload.get("ihc_chromogranin", "")).lower().startswith("pos")
    )
    ar_loss_ihc = _flag(payload, "ihc_ar_loss") or str(payload.get("ihc_ar_loss", "")).lower() in {
        "1",
        "loss",
        "perdida",
    }
    ki67 = _safe_float(payload.get("ki67_percent") or payload.get("ki67"))
    small_cell_morphology = _flag(payload, "small_cell_morphology")
    nepc_histology_confirmed = _flag(payload, "nepc_confirmed_histology")
    biopsy_performed = (
        nepc_histology_confirmed
        or synaptophysin
        or chromogranin_ihc
        or small_cell_morphology
        or bool(str(payload.get("neuroendocrine_biopsy_date", "")).strip())
    )

    # ── Score Aggarwal simplificado ─────────────────────────────────
    suspicion_score = 0
    if tp53_rb1:
        suspicion_score += AGGARWAL_CRITERIA["tp53_rb1_altered"]
    if visceral_without_bone:
        suspicion_score += AGGARWAL_CRITERIA["visceral_without_bone_progression"]
    if bulky_ln:
        suspicion_score += AGGARWAL_CRITERIA["bulky_lymphadenopathy"]
    if nse is not None and nse > NSE_UPPER_LIMIT:
        suspicion_score += AGGARWAL_CRITERIA["nse_elevated"]
    if ldh is not None and ldh > LDH_UPPER_LIMIT:
        suspicion_score += AGGARWAL_CRITERIA["ldh_elevated"]
    if psa_discordant_low:
        suspicion_score += AGGARWAL_CRITERIA["psa_discordant_low"]
    if neuroendocrine_features:
        suspicion_score += AGGARWAL_CRITERIA["neuroendocrine_features_clinical"]

    # CgA es un soporte adicional, no contribuye al score primario pero se reporta.
    cga_elevated = cga is not None and cga > CHROMOGRANIN_A_UPPER_LIMIT

    suspected = suspicion_score >= SUSPICION_SCORE_THRESHOLD
    requires_biopsy = suspicion_score >= BIOPSY_TRIGGER_THRESHOLD and not biopsy_performed

    confirmed = bool(
        nepc_histology_confirmed
        or (synaptophysin and chromogranin_ihc)
        or (small_cell_morphology and (synaptophysin or chromogranin_ihc))
    )

    # ── Fitness para esquema platino ────────────────────────────────
    ecog = _safe_int(
        payload.get("ecog_score") or payload.get("ecog_performance_status") or payload.get("ecog")
    ) or 1
    egfr = _safe_float(payload.get("egfr_ml_min") or payload.get("egfr"))
    hearing_loss = _flag(payload, "cisplatin_hearing_loss_history")
    neuropathy_grade = _safe_int(payload.get("peripheral_neuropathy_grade")) or 0

    cisplatin_eligible = True
    cisplatin_blocks: list[str] = []
    if ecog >= 3:
        cisplatin_eligible = False
        cisplatin_blocks.append(f"ECOG {ecog} ≥3 — excluye cisplatino.")
    if egfr is not None and egfr < 60:
        cisplatin_eligible = False
        cisplatin_blocks.append(
            f"eGFR {egfr:.0f} <60 mL/min — evitar cisplatino, preferir carboplatino."
        )
    if hearing_loss:
        cisplatin_eligible = False
        cisplatin_blocks.append("Hipoacusia/ototoxicidad documentada — contraindicación cisplatino.")
    if neuropathy_grade >= 2:
        cisplatin_eligible = False
        cisplatin_blocks.append(
            f"Neuropatía CTCAE G{neuropathy_grade} — evitar cisplatino/docetaxel si ≥G2."
        )

    # ── Régimen propuesto ───────────────────────────────────────────
    regimens: list[dict[str, Any]] = []
    if confirmed or suspected:
        # Primera línea preferida: platino + etopósido (Aparicio 2013).
        carbo_priority = "preferred" if confirmed else "selected_candidate"
        regimens.append(
            {
                "regimen_code": "CARBOPLATIN_ETOPOSIDE_NEPC",
                "drug_label": "Carboplatino + Etopósido (NEPC)",
                "priority": carbo_priority,
                "line_context": "first_line_nepc",
                "dose": "Carboplatino AUC 5 IV día 1 + Etopósido 100 mg/m² IV días 1-3, ciclo cada 21 días × 4-6 ciclos",
                "evidence_trials": [
                    "Aparicio CCR 2013 (EP-16)",
                    "Aggarwal JCO 2018",
                    "Beltran Nat Med 2016",
                ],
                "evidence_tier": "B",
                "hard_blocks": [],
                "rationale": (
                    "Esquema platino-etopósido replica el estándar de tumor de pulmón de células pequeñas; "
                    "respuestas objetivas 33-55% en NEPC confirmado. Preferido cuando cisplatino no es seguro."
                ),
                "monitoring": [
                    "CBC semanal × 4s luego cada ciclo",
                    "Cr + electrolitos cada ciclo",
                    "Audiometría basal si se reservará cisplatino",
                ],
            }
        )
        # Alternativo cuando cisplatino es tolerable: cisplatin + docetaxel (Aparicio 2013).
        cisplatin_priority = "selected_candidate" if cisplatin_eligible else "not_eligible"
        regimens.append(
            {
                "regimen_code": "CISPLATIN_DOCETAXEL_NEPC",
                "drug_label": "Cisplatino + Docetaxel (NEPC)",
                "priority": cisplatin_priority,
                "line_context": "first_line_nepc",
                "dose": "Cisplatino 75 mg/m² + Docetaxel 75 mg/m² IV cada 21 días × 6 ciclos (ajustar por función renal/auditiva)",
                "evidence_trials": ["Aparicio CCR 2013", "Aggarwal JCO 2018"],
                "evidence_tier": "B",
                "hard_blocks": list(cisplatin_blocks),
                "rationale": (
                    "Combinación cisplatino-docetaxel ofrece respuesta similar a carbo-etopósido; se reserva "
                    "cuando función renal/auditiva y neuropatía son compatibles con cisplatino."
                ),
                "monitoring": [
                    "Hidratación pre/post cisplatino",
                    "Electrolitos (Mg, K, Ca) cada ciclo",
                    "Neuropatía CTCAE cada ciclo",
                ],
            }
        )

    # ── Mensajería final ────────────────────────────────────────────
    if confirmed:
        headline = (
            "NEPC confirmado histológicamente: esquema platino es terapia estándar; "
            "suspender ARPI como línea activa."
        )
    elif requires_biopsy:
        headline = (
            f"Score NEPC {suspicion_score}/8 — indicar biopsia dirigida con IHC neuroendocrina "
            "(sinaptofisina/cromogranina, Ki-67, AR) antes de esquema platino."
        )
    elif suspected:
        headline = (
            f"Score NEPC {suspicion_score}/8 — vigilar activamente NSE, LDH, CgA y PSA discordante bajo; "
            "considerar biopsia si aparece progresión viscerales o empeoramiento clínico."
        )
    else:
        headline = "Sin sospecha NEPC actual — continuar secuenciación estándar mCRPC."

    return {
        "nepc_suspected": suspected,
        "nepc_confirmed": confirmed,
        "suspicion_score": suspicion_score,
        "biopsy_trigger": requires_biopsy,
        "biopsy_performed": biopsy_performed,
        "tp53_altered": tp53_altered,
        "rb1_loss": rb1_loss,
        "tp53_rb1_both": tp53_rb1,
        "ihc_synaptophysin_positive": synaptophysin,
        "ihc_chromogranin_positive": chromogranin_ihc,
        "ihc_ar_loss": ar_loss_ihc,
        "ki67_percent": ki67,
        "small_cell_morphology": small_cell_morphology,
        "nse_value": nse,
        "nse_elevated": nse is not None and nse > NSE_UPPER_LIMIT,
        "chromogranin_a_value": cga,
        "chromogranin_a_elevated": cga_elevated,
        "ldh_value": ldh,
        "ldh_elevated": ldh is not None and ldh > LDH_UPPER_LIMIT,
        "psa_discordant_low": psa_discordant_low,
        "visceral_without_bone_progression": visceral_without_bone,
        "bulky_lymphadenopathy": bulky_ln,
        "cisplatin_eligible": cisplatin_eligible,
        "cisplatin_blocks": cisplatin_blocks,
        "regimens": regimens,
        "headline": headline,
        "evidence_refs": [
            "Aparicio CCR 2013",
            "Beltran JCO 2014",
            "Beltran Nat Med 2016",
            "Aggarwal JCO 2018",
            "NCCN PROS-J v5.2026",
        ],
    }


__all__ = [
    "evaluate_nepc_pathway",
    "AGGARWAL_CRITERIA",
    "SUSPICION_SCORE_THRESHOLD",
    "BIOPSY_TRIGGER_THRESHOLD",
]
