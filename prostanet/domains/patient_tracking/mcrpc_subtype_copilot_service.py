"""EPIC 20 Fase D — mCRPC Subtype Copilot Service.

Maneja los 5 subtipos mCRPC introducidos en EPIC 20:
  - mcrpc_arsi_naive
  - mcrpc_post_arsi
  - mcrpc_hrr_positive_parp_naive
  - mcrpc_psma_eligible_lu177
  - mcrpc_msi_h_dmmr

Construye un decision bundle con:
  - Subtype identificado (vía clinical_state_classifier)
  - Therapeutic alternatives ordered (preferred + acceptable)
  - Evidence references (NCCN 2026 PROS-J + pivotal trials)
  - Clinical caveats (cross-resistance, biomarker requirements)
  - Patient-specific gating (comorbidities, prior therapy)

NCCN 2026 PROS-J + pivotal trials integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class McrpcSubtypeBundle:
    """Decision bundle for mCRPC subtype."""
    available: bool
    subtype_state: str
    confidence: float
    rationale: str
    nccn_reference: str
    therapeutic_preferred: str
    therapeutic_acceptable: list[str] = field(default_factory=list)
    therapeutic_not_recommended: list[str] = field(default_factory=list)
    pivotal_trials_supporting: list[str] = field(default_factory=list)
    clinical_caveats: list[str] = field(default_factory=list)
    biomarker_requirements: dict[str, str] = field(default_factory=dict)
    patient_gating_notes: list[str] = field(default_factory=list)


def build_mcrpc_subtype_bundle(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build decision bundle for mCRPC subtype.

    Returns dict (serializable for UI/JSON):
      - available: True if patient is mCRPC
      - subtype_state, confidence, rationale
      - therapeutic options ordered
      - caveats specific to subtype
    """
    try:
        from prostanet.domains.state_classifier.clinical_state_classifier import (
            classify_clinical_state,
        )
    except ImportError:
        return {"available": False, "reason": "classifier_unavailable"}

    facts = _extract_facts(patient_record)
    if not facts.get("castration_resistance_confirmed"):
        return {"available": False, "reason": "not_crpc"}

    classification = classify_clinical_state(facts)
    if not classification or not classification.state.startswith("mcrpc_"):
        return {"available": False, "reason": "no_mcrpc_subtype_classified"}

    subtype = classification.state
    bundle = McrpcSubtypeBundle(
        available=True,
        subtype_state=subtype,
        confidence=classification.confidence,
        rationale=classification.rationale,
        nccn_reference=classification.evidence_tag,
        therapeutic_preferred=classification.therapeutic_alternative_preferred,
        therapeutic_acceptable=classification.therapeutic_alternatives_acceptable,
        therapeutic_not_recommended=classification.therapeutic_alternatives_not_recommended,
    )

    # Subtype-specific enrichment
    if subtype == "mcrpc_arsi_naive":
        bundle.pivotal_trials_supporting = ["AFFIRM", "PREVAIL", "COU-AA-301", "COU-AA-302"]
        bundle.clinical_caveats = [
            "First-line ARSI: abiraterone+prednisona o enzalutamide.",
            "Sipuleucel-T option si asymptomatic (US only).",
            "Radium-223 si bone-only + symptomatic.",
        ]
        bundle.biomarker_requirements = {
            "testosterone_lt_50": "Confirma castration",
            "psma_pet": "Optional staging",
        }

    elif subtype == "mcrpc_post_arsi":
        bundle.pivotal_trials_supporting = ["CARD", "FIRSTANA", "TROPIC"]
        bundle.clinical_caveats = [
            "Cross-resistance abi↔enza ~80% — segundo ARSI generalmente inefectivo.",
            "Cabazitaxel preferred over second ARSI per CARD trial.",
            "Considerar duración respuesta previa: >12mo → second ARSI puede tener rationale.",
            "Switch a chemo o alternative MOA (PARP si HRR+, Lu-177 si PSMA+).",
        ]
        bundle.biomarker_requirements = {
            "prior_arsi_duration": "Documentar drug + duración respuesta",
            "hrr_test_recommended": "Identifica PARP eligibility como alternativa a chemo",
            "psma_pet_recommended": "Identifica Lu-177 eligibility",
        }

    elif subtype == "mcrpc_hrr_positive_parp_naive":
        bundle.pivotal_trials_supporting = ["PROfound", "TRITON-3", "PROpel", "MAGNITUDE", "TALAPRO-2"]
        bundle.clinical_caveats = [
            "PARP first-line preferred si HRR+ (BRCA1/2, ATM, CDK12, CHEK2, PALB2).",
            "BRCA2 mejor respondedor que ATM/CDK12 — gene-specific outcome differs.",
            "PARP+ARSI combos (PROpel, MAGNITUDE, TALAPRO-2) si patient fit.",
            "Considerar platino-based chemo si BRCA1/2 confirmado y PARP no disponible.",
        ]
        bundle.biomarker_requirements = {
            "hrr_gene_specific": "Documentar gen específico (BRCA1/2 vs ATM/CHEK2/CDK12/PALB2)",
            "germline_vs_somatic": "Germline testing → counseling familiar",
        }
        bundle.patient_gating_notes = [
            "Olaparib: cuidado en anemia, renal dysfunction, MDS history",
            "Rucaparib: cuidado en hepatic dysfunction",
        ]

    elif subtype == "mcrpc_psma_eligible_lu177":
        bundle.pivotal_trials_supporting = ["VISION", "TheraP", "PSMAfore"]
        bundle.clinical_caveats = [
            "[177Lu]Lu-PSMA-617 preferred si PSMA-PET intense uptake + GFR≥50.",
            "VISION criteria: previo docetaxel + previo ARSI requeridos.",
            "PSMAfore: pre-chemotherapy option en development.",
            "Monitor renal (GFR) + salivary toxicity post-treatment.",
        ]
        bundle.biomarker_requirements = {
            "psma_pet_uptake_intensity": "Moderate/intense uptake mandatory",
            "gfr_baseline_ge_50": "VISION renal eligibility cutoff",
            "discordant_lesions": "FDG-PET ratio para exclude AR-null disease",
        }
        bundle.patient_gating_notes = [
            "Xerostomia baseline: documentar pre-treatment",
            "Renal: monitor q-cycle + post-treatment surveillance",
        ]

    elif subtype == "mcrpc_msi_h_dmmr":
        bundle.pivotal_trials_supporting = ["KEYNOTE-365", "KEYNOTE-199"]
        bundle.clinical_caveats = [
            "Pembrolizumab tumor-agnostic indication (FDA approved 2017).",
            "3-5% mCRPC son hyper-respondedores con respuestas durables (>2y).",
            "Identificación temprana CRÍTICA — NO esperar a líneas posteriores.",
            "Lynch syndrome subset (MLH1/MSH2/MSH6/PMS2) → screening colorrectal añadido.",
        ]
        bundle.biomarker_requirements = {
            "msi_or_dmmr_or_tmb": "Cualquiera de los 3 markers califica",
            "tmb_threshold": "≥10 mut/Mb (TMB-H)",
            "lynch_screening": "MMR IHC + germline si dMMR detected",
        }
        bundle.patient_gating_notes = [
            "Immune-related AE management protocol",
            "Endocrine surveillance baseline (TSH, cortisol)",
        ]

    return _bundle_to_dict(bundle)


def _extract_facts(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract facts from patient_record for classification."""
    facts: dict[str, Any] = {}
    baseline = patient_record.get("baseline") or {}
    latest = patient_record.get("latest_assessment") or {}

    # Castration resistance
    facts["castration_resistance_confirmed"] = bool(
        patient_record.get("castration_resistance_confirmed")
        or (latest.get("reconciled_state") in ("m0_crpc", "m1_crpc"))
        or (baseline.get("current_state") in ("m0_crpc", "m1_crpc"))
    )

    # Metastasis
    facts["bone_lesion_count_total"] = int(
        patient_record.get("bone_lesion_count_total")
        or baseline.get("bone_lesion_count_total")
        or 0
    )
    facts["visceral_metastasis_present"] = bool(
        patient_record.get("visceral_metastasis_present")
        or baseline.get("visceral_metastasis_present")
    )
    facts["nonregional_nodal_count"] = int(
        patient_record.get("nonregional_nodal_count")
        or baseline.get("nonregional_nodal_count")
        or 0
    )

    # Biomarkers
    facts["hrr_status"] = patient_record.get("hrr_status") or baseline.get("hrr_status") or ""
    facts["msi_status"] = patient_record.get("msi_status") or baseline.get("msi_status") or ""
    facts["dmmr_status"] = patient_record.get("dmmr_status") or baseline.get("dmmr_status") or ""
    facts["tmb_high"] = bool(patient_record.get("tmb_high") or baseline.get("tmb_high"))

    # PSMA-PET
    facts["psma_pet_positive"] = bool(patient_record.get("psma_pet_positive"))
    facts["psma_pet_uptake_intensity"] = patient_record.get("psma_pet_uptake_intensity") or ""
    facts["gfr_baseline"] = patient_record.get("gfr_baseline") or baseline.get("gfr_baseline")

    # NEPC markers
    facts["chromogranin_a_value"] = patient_record.get("chromogranin_a_value")
    facts["synaptophysin_biopsy_positive"] = patient_record.get("synaptophysin_biopsy_positive")
    facts["small_cell_morphology"] = patient_record.get("small_cell_morphology")
    facts["nse_value"] = patient_record.get("nse_value")

    # Prior therapy
    facts["prior_arsi_in_mcspc"] = bool(patient_record.get("prior_arsi_in_mcspc"))
    facts["parp_inhibitor_received"] = bool(patient_record.get("parp_inhibitor_received"))

    return facts


def _bundle_to_dict(bundle: McrpcSubtypeBundle) -> dict[str, Any]:
    return {
        "available": bundle.available,
        "subtype_state": bundle.subtype_state,
        "confidence": bundle.confidence,
        "rationale": bundle.rationale,
        "nccn_reference": bundle.nccn_reference,
        "therapeutic_preferred": bundle.therapeutic_preferred,
        "therapeutic_acceptable": bundle.therapeutic_acceptable,
        "therapeutic_not_recommended": bundle.therapeutic_not_recommended,
        "pivotal_trials_supporting": bundle.pivotal_trials_supporting,
        "clinical_caveats": bundle.clinical_caveats,
        "biomarker_requirements": bundle.biomarker_requirements,
        "patient_gating_notes": bundle.patient_gating_notes,
    }


__all__ = ["build_mcrpc_subtype_bundle", "McrpcSubtypeBundle"]
