"""evidence_summary_fallback.py — EPIC 49+.D (FAUBOT CXLVII).

Genera evidence_summary mínimo con citación NCCN/EAU para pacientes nuevos
que aún no tienen latest_assessment poblado por clinical_decision_agent.

Cierra HX4 detectada en validación EXTENSA okarbo:
  6/10 casos sintéticos disparaban `guideline_basis_missing` aunque la
  recomendación clínica sí tiene base en guidelines — el evidence_summary
  builder solo se ejecutaba dentro de result_snapshot del clinical_decision_agent
  que NO corre para pacientes recién registrados.

Filosofía: evidence_summary debe tener guideline_basis SIEMPRE, aún sea
"genérico por estadio". Refinamiento detallado viene cuando decision_agent corre.

Reglas de citación por estadio:
  - localized → NCCN PROS-1 + PROS-2 + EAU §6.1
  - mHSPC → NCCN PROS-7 + CHAARTED + LATITUDE + STAMPEDE + ARASENS + PEACE-1
  - nmCRPC → NCCN PROS-8 + SPARTAN + PROSPER + ARAMIS
  - mCRPC → NCCN PROS-9 + CHAARTED + PROfound + VISION + TALAPRO-2
  - BCR → NCCN PROS-6 + RTOG 9601 + GETUG-AFU 16
"""
from __future__ import annotations

from typing import Any


GUIDELINE_BY_STAGE: dict[str, list[str]] = {
    "localized": [
        "NCCN PROS-1 v5.2026 (initial risk stratification)",
        "NCCN PROS-2 v5.2026 (treatment by risk group)",
        "EAU 2026 §6.1 (clinically localized disease)",
        "RTOG 0815 (intermediate risk RT+ADT)",
        "PROTECT NCT02044172 (active surveillance)",
    ],
    "mhspc": [
        "NCCN PROS-7 v5.2026 (mHSPC systemic therapy)",
        "EAU 2026 §6.4 (mHSPC)",
        "CHAARTED NCT00309985 (docetaxel high volume)",
        "LATITUDE NCT01715285 (abiraterone high risk)",
        "STAMPEDE arm G (abiraterone in M1)",
        "ARASENS NCT02799602 (darolutamide triplet)",
        "PEACE-1 NCT01957436 (abi+docetaxel triplet)",
    ],
    "nmcrpc": [
        "NCCN PROS-8 v5.2026 (M0 CRPC high risk)",
        "EAU 2026 §6.5.1 (non-metastatic CRPC)",
        "SPARTAN NCT01946204 (apalutamide MFS)",
        "PROSPER NCT02003924 (enzalutamide MFS)",
        "ARAMIS NCT02200614 (darolutamide MFS)",
    ],
    "mcrpc": [
        "NCCN PROS-9 v5.2026 (mCRPC by line)",
        "EAU 2026 §6.6 (mCRPC therapy)",
        "PROfound NCT02987543 (olaparib HRR+)",
        "VISION NCT03511664 (lutetium-177-PSMA Pluvicto)",
        "TALAPRO-2 NCT03395197 (talazoparib+enza HRR+)",
        "TROPIC NCT00417079 (cabazitaxel post-docetaxel)",
        "ALSYMPCA (radium-223 in bone-only)",
        "FDA 2017 tumor-agnostic pembrolizumab MSI-H",
    ],
    "bcr": [
        "NCCN PROS-6 v5.2026 (biochemical recurrence)",
        "EAU 2026 §6.7 (BCR after primary)",
        "RTOG 9601 (salvage RT + bicalutamide)",
        "GETUG-AFU 16 (salvage RT + 6m ADT)",
        "EMBARK NCT02319837 (BCR + ARSI)",
    ],
}


def _stage_bucket(patient: dict[str, Any]) -> str:
    """Maps patient stage string to one of: localized | mhspc | nmcrpc | mcrpc | bcr."""
    baseline = patient.get("baseline") or {}
    stage_blob = " ".join(str(
        baseline.get(k) or "") for k in (
        "stage", "tnm_stage", "clinical_stage", "disease_state"
    )).lower()

    # Order matters: nmcrpc primero (contiene 'crpc' substring que matchearía
    # mcrpc check). Idem mhspc antes que mcrpc.
    if any(kw in stage_blob for kw in ("nmcrpc", "m0_crpc", "m0crpc", "non_metastatic_crpc")):
        return "nmcrpc"
    if any(kw in stage_blob for kw in ("mhspc", "mcspc", "m1_castration_sensitive")):
        return "mhspc"
    if any(kw in stage_blob for kw in ("mcrpc", "m1_crpc", "m1crpc",
                                        "castration_resistant")):
        return "mcrpc"
    if any(kw in stage_blob for kw in ("bcr", "recurr", "biochemical")):
        return "bcr"
    if "metast" in stage_blob:
        # Heuristic: metastatic without explicit crpc → mhspc
        return "mhspc"
    return "localized"


def build_evidence_summary_fallback(
    patient: dict[str, Any],
) -> dict[str, Any]:
    """Returns evidence_summary mínimo con guideline_basis poblado siempre.

    Pasarlo al compass via runtime patch o como input a _build_compass_for_godibot:
        compass["evidence_summary"] = build_evidence_summary_fallback(patient)

    Returns:
        {
            "guideline_basis": list[str] (siempre poblado para evitar
                guideline_basis_missing false-positive),
            "stage_bucket": str,
            "is_fallback": True (señal explícita para auditor: este es genérico,
                no específico al paciente),
            "refinement_pending_action": "Run clinical_decision_agent for
                patient-specific evidence_summary",
        }
    """
    bucket = _stage_bucket(patient)
    guidelines = GUIDELINE_BY_STAGE.get(bucket, GUIDELINE_BY_STAGE["localized"])
    return {
        "guideline_basis": list(guidelines),
        "stage_bucket": bucket,
        "is_fallback": True,
        "refinement_pending_action": (
            "Run clinical_decision_agent on patient for patient-specific "
            "evidence_summary (this fallback is stage-generic NCCN/EAU)."
        ),
        "evidence_count": len(guidelines),
    }


__all__ = ["build_evidence_summary_fallback", "GUIDELINE_BY_STAGE"]
