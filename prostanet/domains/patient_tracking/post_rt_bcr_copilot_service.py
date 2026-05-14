"""EPIC 20 Fase D — Post-RT BCR Copilot Service.

NCCN 2026 PROS-D — Phoenix-defined BCR post-RT.

Distinct from post-RP BCR: post-RT BCR requires biopsy local + decisión salvage
cryoablation/HIFU/SBRT vs ADT (NO salvage RT a fossa).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class PostRtBcrBundle:
    available: bool
    phoenix_criteria_met: bool
    nadir_psa: float | None
    current_psa: float | None
    psa_above_nadir_plus_2: bool
    nccn_reference: str = "PROS-D_v2026"
    therapeutic_preferred: str = "depends_on_local_vs_distant_failure_pattern"
    workup_required: list[str] = field(default_factory=list)
    therapeutic_local_failure: list[str] = field(default_factory=list)
    therapeutic_distant_failure: list[str] = field(default_factory=list)
    therapeutic_not_recommended: list[str] = field(default_factory=list)
    pivotal_trials_supporting: list[str] = field(default_factory=list)
    clinical_caveats: list[str] = field(default_factory=list)


def build_post_rt_bcr_bundle(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build post-RT BCR decision bundle per NCCN 2026 PROS-D."""
    facts = _extract_rt_bcr_facts(patient_record)
    if not facts["prior_rt_received"]:
        return {"available": False, "reason": "no_prior_rt"}

    nadir = facts.get("nadir_psa_post_rt")
    current = facts.get("current_psa")
    phoenix_met = False
    if nadir is not None and current is not None:
        try:
            phoenix_met = float(current) >= float(nadir) + 2.0
        except (TypeError, ValueError):
            pass

    if not phoenix_met:
        return {"available": False, "reason": "phoenix_criteria_not_met"}

    bundle = PostRtBcrBundle(
        available=True,
        phoenix_criteria_met=True,
        nadir_psa=float(nadir) if nadir is not None else None,
        current_psa=float(current) if current is not None else None,
        psa_above_nadir_plus_2=True,
    )

    bundle.workup_required = [
        "PSMA-PET or choline-PET (distinguir local vs distant failure)",
        "MRI prostate (evaluar local recurrence anatomical detail)",
        "Fossa biopsy si imaging sospecha local-only recurrence",
        "Bone scan + CT abd-pelvis si PSMA-PET no disponible",
    ]

    bundle.therapeutic_local_failure = [
        "Salvage cryoablation (NCCN PROS-D, depending anatomic feasibility)",
        "Salvage HIFU (high-intensity focused ultrasound)",
        "Salvage SBRT (stereotactic body radiation therapy)",
        "Salvage brachytherapy si pre-RT received EBRT alone",
        "ADT systemic si local salvage no factible o paciente prefiere",
    ]

    bundle.therapeutic_distant_failure = [
        "ADT + ARSI intensification per metastatic burden",
        "Considerar trayectoria mcspc o mcrpc según volumen + castration status",
    ]

    bundle.therapeutic_not_recommended = [
        "Salvage RT a fossa post-RT (no aplica como post-RP BCR)",
        "Repeat full-dose RT a próstata (rectal/bladder dose constraints excedidos)",
        "Observación sin workup (>50% local salvage opportunity perdida)",
    ]

    bundle.pivotal_trials_supporting = ["RADICALS-RT"]

    bundle.clinical_caveats = [
        "Phoenix BCR ≠ post-RP BCR — manejo DISTINTO.",
        "Local failure puede ser curable con salvage ablation; distant requiere systemic.",
        "Biopsy local debe preceder a cryoablation/HIFU para confirmar viable tumor.",
        "Time-from-RT-to-BCR <3y = adverse prognosis vs ≥3y favorable.",
        "Patient preference: curative salvage local agresivo vs ADT systemic más tolerable.",
    ]

    return asdict(bundle)


def _extract_rt_bcr_facts(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    baseline = patient_record.get("baseline") or {}
    return {
        "prior_rt_received": bool(
            patient_record.get("prior_rt_received")
            or baseline.get("rt_primary_received")
            or baseline.get("prior_rt_received")
        ),
        "nadir_psa_post_rt": patient_record.get("nadir_psa_post_rt") or baseline.get("nadir_psa_post_rt"),
        "current_psa": (
            patient_record.get("current_psa")
            or patient_record.get("baseline_psa")
            or baseline.get("psa_current")
            or baseline.get("baseline_psa")
        ),
    }


__all__ = ["build_post_rt_bcr_bundle", "PostRtBcrBundle"]
