"""EPIC 20 Fase D — Hereditary Germline Copilot Service.

NCCN 2026 PROS-A — Universal germline testing pathway.

Detecta cuándo germline testing está indicado y guía counseling familiar +
surveillance intensified si carrier identified.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class HereditaryGermlineBundle:
    available: bool
    testing_indicated: bool
    testing_rationale: list[str] = field(default_factory=list)
    testing_status: str = "not_done"  # not_done, pending, completed, declined
    nccn_reference: str = "PROS-A_v2026"
    therapeutic_preferred: str = ""
    triggers_matched: list[str] = field(default_factory=list)
    panel_recommendation: dict[str, Any] = field(default_factory=dict)
    family_counseling_required: bool = False
    surveillance_if_carrier: dict[str, str] = field(default_factory=dict)
    clinical_caveats: list[str] = field(default_factory=list)


def build_hereditary_germline_bundle(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build hereditary germline pathway bundle per NCCN 2026 PROS-A."""
    facts = _extract_germline_facts(patient_record)

    triggers: list[str] = []
    if facts["metastatic"]:
        triggers.append("any_metastatic_prostate_cancer")
    if facts["family_first_degree_lt_60"]:
        triggers.append("family_history_first_degree_pca_lt_60y")
    if facts["family_breast_ovary_pancreas"]:
        triggers.append("family_history_breast_ovary_pancreas")
    if facts["ashkenazi"]:
        triggers.append("ashkenazi_jewish_ancestry")
    if facts["high_risk_or_very_high_risk_localized"]:
        triggers.append("high_or_very_high_risk_localized")

    if not triggers:
        return {"available": False, "reason": "no_germline_testing_triggers"}

    bundle = HereditaryGermlineBundle(
        available=True,
        testing_indicated=True,
        testing_rationale=triggers,
        testing_status="completed" if facts["germline_testing_done"] else "not_done",
        triggers_matched=triggers,
    )

    bundle.therapeutic_preferred = (
        "Germline panel testing + genetic counseling"
        if not facts["germline_testing_done"]
        else "Surveillance intensification per carrier status"
    )

    bundle.panel_recommendation = {
        "minimum_genes": ["BRCA1", "BRCA2", "ATM", "CHEK2", "PALB2", "CDK12", "MLH1", "MSH2", "MSH6", "PMS2", "EPCAM", "HOXB13"],
        "preferred_panel": "Comprehensive multi-gene panel (≥30 genes)",
        "rationale": "NCCN 2026 PROS-A recomienda panel multi-gene en lugar de single-gene BRCA",
    }

    bundle.family_counseling_required = True
    bundle.surveillance_if_carrier = {
        "BRCA2": "PSA q6mo desde 40y + MRI pelvis q2y; cascade testing familiares",
        "BRCA1": "PSA q12mo desde 45y; cascade testing familiares",
        "ATM": "PARP response variable; consider clinical trial enrollment",
        "CHEK2": "Standard surveillance + intensified PSA",
        "Lynch_MLH1_MSH2_MSH6_PMS2": "Pembrolizumab eligibility + colorectal/endometrial surveillance",
        "HOXB13_G84E": "Intensified PSA surveillance",
    }

    bundle.clinical_caveats = [
        "Germline testing requiere consent informado + counseling pre-test.",
        "Positive result = cascade testing first-degree relatives (60% inheritance prob).",
        "Negative result NO descarta somatic mutation — considerar tumor sequencing también.",
        "Insurance + GINA protections: counsel patient sobre implications.",
    ]

    if facts["germline_testing_done"] and facts["germline_panel_result_status"] == "pending":
        bundle.clinical_caveats.append(
            "Resultado germline PENDING — esperar antes de finalizar tratamiento PARP-based."
        )

    return asdict(bundle)


def _extract_germline_facts(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    baseline = patient_record.get("baseline") or {}
    latest = patient_record.get("latest_assessment") or {}

    metastatic = (
        bool(patient_record.get("visceral_metastasis_present"))
        or int(patient_record.get("bone_lesion_count_total") or 0) > 0
        or latest.get("reconciled_state") in ("m0_crpc", "m1_crpc", "mcspc_high_volume", "mcspc_oligo_metachronous")
    )

    return {
        "metastatic": metastatic,
        "family_first_degree_lt_60": bool(
            patient_record.get("family_history_first_degree_prostate_cancer_age_lt_60")
            or baseline.get("family_history_first_degree_prostate_cancer_age_lt_60")
        ),
        "family_breast_ovary_pancreas": bool(
            patient_record.get("family_history_breast_ovary_pancreas")
            or baseline.get("family_history_breast_ovary_pancreas")
        ),
        "ashkenazi": bool(patient_record.get("ashkenazi_ancestry") or baseline.get("ashkenazi_ancestry")),
        "high_risk_or_very_high_risk_localized": (
            (latest.get("reconciled_state") or "") in ("high_risk_localized", "very_high_risk_localized")
        ),
        "germline_testing_done": bool(
            patient_record.get("germline_testing_done")
            or baseline.get("germline_testing_done")
        ),
        "germline_panel_result_status": str(
            patient_record.get("germline_panel_result_status")
            or baseline.get("germline_panel_result_status")
            or "not_done"
        ),
    }


__all__ = ["build_hereditary_germline_bundle", "HereditaryGermlineBundle"]
