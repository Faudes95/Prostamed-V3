from __future__ import annotations

from typing import Any

from .repository import imaging_studies_for_psma_analytics
from .service import build_psma_structured_profile


def build_psma_imaging_analytics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total_patients = len(records or [])
    studies = imaging_studies_for_psma_analytics(records or [])
    radioligands: dict[str, int] = {}
    rads_distribution: dict[str, int] = {}
    pattern_distribution: dict[str, int] = {}
    suv_buckets = {"<6": 0, "6-9": 0, "9-12": 0, ">12": 0}
    upstaged = 0
    management_changed = 0
    structured_profiles = 0
    for record in records or []:
        profile = build_psma_structured_profile(record)
        if not profile.get("available"):
            continue
        structured_profiles += 1
        ligand = str(profile.get("psma_radioligand") or "Desconocido")
        radioligands[ligand] = radioligands.get(ligand, 0) + 1
        rads = str(profile.get("psma_rads_score") or "Desconocido")
        rads_distribution[rads] = rads_distribution.get(rads, 0) + 1
        pattern = str(profile.get("psma_uptake_pattern") or "indeterminado")
        pattern_distribution[pattern] = pattern_distribution.get(pattern, 0) + 1
        suv = profile.get("psma_index_lesion_suvmax")
        if suv is not None:
            if float(suv) < 6:
                suv_buckets["<6"] += 1
            elif float(suv) < 9:
                suv_buckets["6-9"] += 1
            elif float(suv) < 12:
                suv_buckets["9-12"] += 1
            else:
                suv_buckets[">12"] += 1
        if profile.get("psma_upstaged_vs_conventional") is True:
            upstaged += 1
        if profile.get("psma_management_changed") is True:
            management_changed += 1

    return {
        "structured_coverage_count": structured_profiles,
        "structured_coverage_pct": round((structured_profiles / total_patients) * 100.0, 1) if total_patients else 0.0,
        "study_count": len(studies),
        "radioligand_distribution": radioligands,
        "psma_rads_distribution": rads_distribution,
        "uptake_pattern_distribution": pattern_distribution,
        "suvmax_buckets": suv_buckets,
        "upstaging_rate_pct": round((upstaged / structured_profiles) * 100.0, 1) if structured_profiles else 0.0,
        "management_change_rate_pct": round((management_changed / structured_profiles) * 100.0, 1) if structured_profiles else 0.0,
    }
