from __future__ import annotations

from typing import Any


GUIDELINE_PROVENANCE = {
    "diagnostic_workup": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "diagnostic_workup", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "repeat_biopsy_context", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "post_negative_biopsy_followup": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "repeat_biopsy", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "repeat_biopsy", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "localized_initial": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "localized_disease", "evidence_strength": "primary", "fallback_used": False},
    ],
    "active_surveillance": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "active_surveillance", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "active_surveillance_followup", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "post_prostatectomy": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "post_prostatectomy_followup", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "salvage_window", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "recurrence_bcr": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "bcr_management", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "salvage_window", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "post_radiotherapy_or_local_salvage": [
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "post_rt_salvage", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "bcr_management", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "adt_progression_verification": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "crpc_workup", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "AUA", "guideline_version": "advanced-prostate-cancer", "statement_scope": "castration_confirmation", "evidence_strength": "support", "fallback_used": True},
    ],
    "m0_crpc": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "nmcrpc", "evidence_strength": "primary", "fallback_used": False},
    ],
    "mHSPC": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "mhspc", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "EAU", "guideline_version": "2026", "statement_scope": "mhspc_followup", "evidence_strength": "fallback", "fallback_used": True},
    ],
    "m1_crpc": [
        {"guideline_family": "NCCN", "guideline_version": "5.2026", "statement_scope": "mcrpc", "evidence_strength": "primary", "fallback_used": False},
        {"guideline_family": "FDA/Janssen", "guideline_version": "abiraterone-monitoring", "statement_scope": "drug_safety", "evidence_strength": "support", "fallback_used": True},
    ],
}


HARD_CRITICAL_FAMILIES = {
    "post_prostatectomy",
    "recurrence_bcr",
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
    "active_surveillance",
}


def build_guideline_oracle(trajectory: dict[str, Any]) -> dict[str, Any]:
    family = str(trajectory.get("scenario_family") or "")
    case_oracle = dict(trajectory.get("clinical_oracle") or {})
    provenance = list(GUIDELINE_PROVENANCE.get(family, []))
    return {
        "scenario_family": family,
        "guideline_basis": provenance,
        "hard_critical": bool(case_oracle.get("hard_critical") or family in HARD_CRITICAL_FAMILIES),
        "expected_guideline_basis_any": list(case_oracle.get("expected_guideline_basis_any") or []),
    }


def attach_guideline_oracle(trajectory: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(trajectory)
    enriched["guideline_oracle"] = build_guideline_oracle(trajectory)
    return enriched


def build_guideline_oracle_catalog(trajectories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [attach_guideline_oracle(item) for item in trajectories]


__all__ = [
    "attach_guideline_oracle",
    "build_guideline_oracle",
    "build_guideline_oracle_catalog",
    "HARD_CRITICAL_FAMILIES",
]
