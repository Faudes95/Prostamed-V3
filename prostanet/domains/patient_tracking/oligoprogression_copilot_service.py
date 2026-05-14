"""EPIC 20 Fase D — Oligoprogression on Therapy Copilot Service.

NCCN 2026 PROS-G + STOMP/ORIOLE trials.

Detecta paciente en systemic therapy con limited progression pattern (≤3 new lesions)
+ continued response en lesiones existentes → MDT (SBRT) local + continue systemic
vs class switch.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass
class OligoprogressionBundle:
    available: bool
    eligible_for_mdt: bool
    new_lesion_count: int
    nccn_reference: str = "PROS-G_v2026"
    therapeutic_preferred: str = "continue_systemic_+_local_consolidation_sbrt_mdt"
    therapeutic_acceptable: list[str] = field(default_factory=list)
    therapeutic_not_recommended: list[str] = field(default_factory=list)
    pivotal_trials_supporting: list[str] = field(default_factory=list)
    clinical_caveats: list[str] = field(default_factory=list)
    mdt_feasibility_checks: list[str] = field(default_factory=list)


def build_oligoprogression_bundle(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    """Build oligoprogression bundle per NCCN 2026 PROS-G + STOMP/ORIOLE."""
    facts = _extract_oligo_facts(patient_record)

    on_therapy = facts.get("progressing_on_systemic_therapy")
    new_lesions = facts.get("new_lesion_count_since_last_imaging")
    response_existing = (facts.get("response_in_existing_lesions") or "").lower()

    if not on_therapy:
        return {"available": False, "reason": "not_on_systemic_therapy"}
    if new_lesions is None:
        return {"available": False, "reason": "new_lesion_count_missing"}
    try:
        new_lesion_count = int(new_lesions)
    except (TypeError, ValueError):
        return {"available": False, "reason": "invalid_new_lesion_count"}

    if new_lesion_count == 0:
        return {"available": False, "reason": "no_new_lesions"}
    if new_lesion_count > 3:
        return {
            "available": True,
            "eligible_for_mdt": False,
            "new_lesion_count": new_lesion_count,
            "nccn_reference": "PROS-G_v2026",
            "therapeutic_preferred": "class_switch_systemic_therapy_widespread_progression",
            "clinical_caveats": [
                f"{new_lesion_count} new lesions > 3 — NO oligoprogresión per STOMP/ORIOLE criteria.",
                "Class switch (chemo o alternative MOA) preferred over MDT.",
                "Re-stratificar trayectoria post-progression.",
            ],
        }

    # 1-3 new lesions: candidate for oligoprogresión MDT
    is_oligo_candidate = response_existing in ("continued_response", "stable", "continued response", "")

    bundle = OligoprogressionBundle(
        available=True,
        eligible_for_mdt=is_oligo_candidate,
        new_lesion_count=new_lesion_count,
    )

    if is_oligo_candidate:
        bundle.therapeutic_preferred = "continue_systemic_+_SBRT_to_oligo_lesions"
        bundle.therapeutic_acceptable = [
            "Continue current ARSI/ADT + SBRT to new lesions",
            "Add local consolidation surgery if anatomically feasible (oligomet site)",
            "Brief radiotherapy escalation (3-5 fractions per lesion)",
        ]
        bundle.therapeutic_not_recommended = [
            "Class switch for oligo alone (premature switch loses systemic option)",
            "Abandon systemic therapy",
            "Escalate to chemotherapy without attempting MDT first",
        ]
        bundle.pivotal_trials_supporting = ["STOMP", "ORIOLE"]
        bundle.clinical_caveats = [
            "STOMP trial: SBRT + ADT vs ADT alone showed PFS benefit.",
            "ORIOLE trial: SBRT in oligometastatic prostate cancer demonstrated OS signal.",
            "MDT to ALL new lesions ideal; partial MDT acceptable if anatomy permits.",
            "Continue current systemic — DO NOT switch class based on oligo alone.",
            "Re-image at 3 months post-MDT to confirm response durability.",
        ]
        bundle.mdt_feasibility_checks = [
            "Lesion location accessible to SBRT (no critical-organ proximity)",
            "Patient performance status (ECOG 0-2)",
            "Cumulative dose to organs at risk within constraints",
            "Patient preference for local intensification vs class switch",
        ]
    else:
        bundle.therapeutic_preferred = "evaluate_class_switch_mixed_progression"
        bundle.clinical_caveats = [
            f"Existing lesions show {response_existing or 'mixed progression'} — not pure oligoprogresión.",
            "Considerar class switch en lugar de MDT-only approach.",
            "Re-stage completo recomendado antes de decisión final.",
        ]

    return asdict(bundle)


def _extract_oligo_facts(patient_record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "progressing_on_systemic_therapy": bool(
            patient_record.get("progressing_on_systemic_therapy")
        ),
        "new_lesion_count_since_last_imaging": patient_record.get(
            "new_lesion_count_since_last_imaging"
        ),
        "response_in_existing_lesions": patient_record.get(
            "response_in_existing_lesions"
        ),
    }


__all__ = ["build_oligoprogression_bundle", "OligoprogressionBundle"]
