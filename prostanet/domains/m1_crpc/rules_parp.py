# -*- coding: utf-8 -*-
"""
PARP inhibitors — evaluación estructurada por agente y contexto de línea.

Centraliza decisiones entre Olaparib, Rucaparib y Talazoparib (monoterapia)
y sus combinaciones 1L con ARPI (PROpel, MAGNITUDE, TALAPRO-2).

Matriz de decisión:
  - Olaparib mono: PROfound (de Bono NEJM 2020). HRR+ post-ARPI. BRCA1/2/ATM (cohorte A)
    rinden más; otros HRR (CDK12/CHEK2/etc.) cohorte B marginal.
  - Rucaparib mono: TRITON3 (Fizazi NEJM 2023). BRCA1/2 mCRPC post-ARPI pre o post-taxano.
  - Talazoparib mono: TALAPRO-1 (de Bono LancetOnc 2021). BRCA1/2 post-ARPI y post-taxano.
  - Olaparib + Abiraterona 1L: PROpel (Clarke Lancet 2022) — HRR+ beneficia más; FDA restringe a BRCA+.
  - Niraparib + Abiraterona 1L: MAGNITUDE (Chi JCO 2023) — HRR+, SG beneficio en BRCA+.
  - Talazoparib + Enzalutamida 1L: TALAPRO-2 (Agarwal Lancet 2023) — HRR+ beneficio rPFS.

Reglas clínicas:
  - Requiere HRR trazable por gen Y fuente molecular (tejido o ctDNA).
  - En 1L (previo a ARPI), preferir combinaciones PARP+ARPI en BRCA+ o HRR+ con acceso.
  - Post-ARPI: monoterapia PARP basada en gen (BRCA>ATM>otros HRR).
  - Contraindicaciones: embarazo/teratogénico, mielosupresión severa, MDS/LAM previos.
  - Monitoreo: CBC basal + mensual × 12 meses, Cr, vigilar SMD/LAM.
"""
from __future__ import annotations

from typing import Any

PARP_RESPONSIVE_GENES = {
    "BRCA2": {"sensitivity": "high", "cohort": "A", "preferred_mono": ["OLAPARIB", "RUCAPARIB", "TALAZOPARIB"]},
    "BRCA1": {"sensitivity": "high", "cohort": "A", "preferred_mono": ["OLAPARIB", "RUCAPARIB", "TALAZOPARIB"]},
    "ATM":   {"sensitivity": "moderate", "cohort": "A", "preferred_mono": ["OLAPARIB"]},
    "PALB2": {"sensitivity": "moderate", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "CDK12": {"sensitivity": "low", "cohort": "B", "preferred_mono": []},
    "CHEK2": {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "RAD51B": {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "RAD51C": {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "RAD51D": {"sensitivity": "moderate", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "BARD1":  {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "BRIP1":  {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
    "FANCL":  {"sensitivity": "low", "cohort": "B", "preferred_mono": ["OLAPARIB"]},
}


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _biomarker_traceable(payload: dict) -> bool:
    source = str(payload.get("biomarker_source", "")).strip()
    gene = str(payload.get("hrr_gene", "")).strip()
    return source not in {"", "Desconocida", "Desconocido"} and gene not in {"", "Desconocido"}


def evaluate_parp_options(payload: dict, *, m1_context: dict | None = None) -> dict[str, Any]:
    """Devuelve lista rankeada de opciones PARP con rationale por agente."""
    m1 = m1_context or {}
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    gene_profile = PARP_RESPONSIVE_GENES.get(hrr_gene.upper(), None)
    hrr_positive = bool(m1.get("hrr_positive") or str(payload.get("hrr_status", "")).lower().startswith("pos"))
    biomarker_traceable = _biomarker_traceable(payload)
    line_context = str(m1.get("line_context") or "first_line_mcrpc")
    prior_arpi = bool(m1.get("prior_arpi"))
    prior_docetaxel = bool(m1.get("prior_docetaxel"))
    prior_abiraterone = bool(m1.get("prior_abiraterone"))
    prior_enza_class = bool(m1.get("prior_enza_class"))
    prior_parp = _flag(payload, "prior_parp_exposure") or "olapar" in str(payload.get("prior_therapy", "")).lower() \
        or "rucapar" in str(payload.get("prior_therapy", "")).lower() \
        or "talazopar" in str(payload.get("prior_therapy", "")).lower()

    # Safety
    anemia = _flag(payload, "anemia_severe") or ((_safe_float(payload.get("hemoglobin")) or 13) < 9)
    mds_aml_history = _flag(payload, "mds_aml_history")
    pregnancy = _flag(payload, "pregnancy_risk")

    missing: list[str] = []
    if not biomarker_traceable:
        if str(payload.get("biomarker_source", "")).strip() in {"", "Desconocida", "Desconocido"}:
            missing.append("biomarker_source")
        if str(payload.get("hrr_gene", "")).strip() in {"", "Desconocido"}:
            missing.append("hrr_gene")
        if not str(payload.get("molecular_report_date", "")).strip():
            missing.append("molecular_report_date")

    options: list[dict[str, Any]] = []

    # Helpers
    def _safety_blocks() -> list[str]:
        blocks: list[str] = []
        if mds_aml_history:
            blocks.append("SMD/LAM previa — contraindicación PARP.")
        if pregnancy:
            blocks.append("Riesgo teratogénico — requiere anticoncepción estricta.")
        if anemia:
            blocks.append("Anemia severa basal (Hb <9) — estabilizar antes de iniciar.")
        return blocks

    safety_blocks = _safety_blocks()

    # ── MONOTERAPIA POST-ARPI (PROfound / TRITON3 / TALAPRO-1) ─────────
    if prior_arpi and hrr_positive and biomarker_traceable:
        # Olaparib: cohorte A (BRCA1/2/ATM) prioritario, cohorte B opcional
        olap_priority = "preferred" if gene_profile and gene_profile["sensitivity"] in {"high", "moderate"} else "eligible"
        options.append({
            "regimen_code": "OLAPARIB",
            "drug_label": "Olaparib",
            "eligible": not safety_blocks,
            "priority": olap_priority if not safety_blocks else "not_eligible",
            "dose": "300 mg PO BID (tabletas)",
            "evidence_trials": ["PROfound (de Bono NEJM 2020)"],
            "evidence_tier": "A",
            "hard_blocks": list(safety_blocks),
            "rationale": (
                f"HRR+ ({hrr_gene}) trazable post-ARPI. PROfound demostró mejoría en rPFS y SG en cohorte A "
                f"(BRCA1/2/ATM)."
            ),
            "monitoring": ["CBC basal y mensual × 12m", "Creatinina cada 3m", "Vigilar SMD/LAM si >24m exposición"],
        })

        if hrr_gene.upper() in {"BRCA1", "BRCA2"}:
            options.append({
                "regimen_code": "RUCAPARIB",
                "drug_label": "Rucaparib",
                "eligible": not safety_blocks,
                "priority": "preferred" if not prior_parp else "eligible",
                "dose": "600 mg PO BID",
                "evidence_trials": ["TRITON3 (Fizazi NEJM 2023)"],
                "evidence_tier": "A",
                "hard_blocks": list(safety_blocks),
                "rationale": (
                    f"BRCA1/2 ({hrr_gene}) mCRPC post-ARPI pre o post-taxano. TRITON3 mostró mejora en "
                    "rPFS vs fisiico del médico. Monitorizar transaminasas y mielosupresión."
                ),
                "monitoring": ["CBC mensual × 12m", "LFT mensual × 6m luego trimestral", "Cr cada 3m"],
            })
            options.append({
                "regimen_code": "TALAZOPARIB",
                "drug_label": "Talazoparib",
                "eligible": not safety_blocks and not prior_parp,
                "priority": "eligible",
                "dose": "0.5 mg PO QD (ajustar por Cr/CBC)",
                "evidence_trials": ["TALAPRO-1 (de Bono LancetOnc 2021)"],
                "evidence_tier": "B",
                "hard_blocks": list(safety_blocks),
                "rationale": (
                    f"BRCA1/2 ({hrr_gene}) post-ARPI y post-taxano. TALAPRO-1 mostró respuesta PSA sostenida; "
                    "potente inhibidor PARP con mayor mielosupresión — requiere ajuste por función renal."
                ),
                "monitoring": ["CBC semanal × 4s, luego mensual", "Cr basal y cada 3m", "Ajuste dosis si Cr 30-60 ml/min"],
            })

    # ── COMBINACIONES 1L (PROpel / MAGNITUDE / TALAPRO-2) ──────────────
    if line_context == "first_line_mcrpc" and hrr_positive and biomarker_traceable:
        if not prior_abiraterone:
            brca_pathway = hrr_gene.upper() in {"BRCA1", "BRCA2"}
            options.append({
                "regimen_code": "OLAPARIB_ABIRATERONE",
                "drug_label": "Olaparib + Abiraterona/prednisona",
                "eligible": not safety_blocks,
                "priority": "preferred" if brca_pathway else "eligible",
                "dose": "Olaparib 300 mg BID + Abiraterona 1000 mg QD + Pred 5 mg BID",
                "evidence_trials": ["PROpel (Clarke Lancet 2022)"],
                "evidence_tier": "A",
                "hard_blocks": list(safety_blocks),
                "rationale": (
                    "Combinación 1L mCRPC con beneficio en rPFS (PROpel). FDA autoriza en BRCA+; "
                    "en HRR+ no-BRCA el balance riesgo/beneficio es más estrecho."
                ),
                "monitoring": ["CBC mensual", "LFT mensual × 3m", "K+, TA, glucosa cada 3m (esteroide)"],
            })
            options.append({
                "regimen_code": "NIRAPARIB_ABIRATERONE",
                "drug_label": "Niraparib + Abiraterona/prednisona",
                "eligible": not safety_blocks and brca_pathway,
                "priority": "preferred" if brca_pathway else "not_eligible",
                "dose": "Niraparib 200 mg QD + Abiraterona 1000 mg QD + Pred 5 mg BID",
                "evidence_trials": ["MAGNITUDE (Chi JCO 2023)"],
                "evidence_tier": "A",
                "hard_blocks": list(safety_blocks) + ([] if brca_pathway else ["MAGNITUDE mostró beneficio SG solo en BRCA+."]),
                "rationale": (
                    "1L mCRPC BRCA+: MAGNITUDE mostró beneficio en rPFS y SG. Disponible como co-formulación "
                    "(AKEEGA, dual-action tablet)."
                ),
                "monitoring": ["CBC/plaquetas mensual × 12m", "TA y metabolismo trimestral"],
            })
        if not prior_enza_class:
            options.append({
                "regimen_code": "TALAZOPARIB_ENZALUTAMIDE",
                "drug_label": "Talazoparib + Enzalutamida",
                "eligible": not safety_blocks,
                "priority": "preferred" if hrr_gene.upper() in {"BRCA1", "BRCA2"} else "eligible",
                "dose": "Talazoparib 0.5 mg QD + Enzalutamida 160 mg QD",
                "evidence_trials": ["TALAPRO-2 (Agarwal Lancet 2023)"],
                "evidence_tier": "A",
                "hard_blocks": list(safety_blocks),
                "rationale": (
                    "1L mCRPC HRR+: TALAPRO-2 mostró mejoría en rPFS (mediana NR vs 22m). Beneficio mayor en BRCA+."
                ),
                "monitoring": ["CBC cada 2-4s × 16s luego mensual", "Cr cada 3m", "Vigilar fatiga/convulsiones"],
            })

    # ── CONTEXTO SIN HRR POSITIVO ──────────────────────────────────────
    if not hrr_positive or not biomarker_traceable:
        options.append({
            "regimen_code": "PARP_NOT_ELIGIBLE",
            "drug_label": "PARP inhibidor",
            "eligible": False,
            "priority": "not_eligible",
            "hard_blocks": [
                "HRR no trazable o HRR negativo — no priorizar PARP fuera de indicación aprobada.",
            ],
            "missing_inputs": missing,
            "rationale": "Requiere panel HRR con gen, fuente (tejido o ctDNA) y fecha de informe antes de considerar PARP.",
        })

    ranked = sorted(
        options,
        key=lambda o: (
            0 if o.get("priority") == "preferred" else (1 if o.get("priority") == "eligible" else 2),
            0 if o.get("eligible") else 1,
        ),
    )
    return {
        "parp_options": ranked,
        "hrr_gene": hrr_gene,
        "gene_profile": gene_profile,
        "biomarker_traceable": biomarker_traceable,
        "missing_inputs": missing,
    }
