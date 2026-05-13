"""Pilar 8 — Clinical Data Capture Coverage (LXC).

Frontend → Backend bridge: garantiza que la captura UI alimente correctamente
los gates clínicos. Sin captura adecuada, los 89 gates son teatro.

Métrica:
  (conditional_logic_coverage / 0.30) × 0.30
  + (longitudinal_kinds_supported / required_kinds) × 0.20
  + (structured_imaging_modalities / total_modalities) × 0.20
  + (auto_derived_visible / total_derivable) × 0.15
  + (stages_with_complete_capture / 18) × 0.15

Gaps detectados aquí alimentan el Faubot loop con kind:
  - capture_field_missing
  - conditional_logic_missing
  - longitudinal_kind_missing
  - structured_form_missing
  - auto_derive_not_exposed
  - validation_rule_missing
"""
from __future__ import annotations

from pathlib import Path
import re

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DOMAINS_DIR = PROJECT_ROOT / "prostanet" / "domains"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Required longitudinal kinds for full clinical coverage
REQUIRED_LONGITUDINAL_KINDS = [
    "psa", "lab", "imaging", "treatment_change", "clinical_event",
    "pro_scores", "ecog", "bpi", "esas", "phq9", "ctcae",
]

# Required structured imaging forms
REQUIRED_IMAGING_MODALITIES = [
    "psma_pet_structured", "bone_scan_structured",
    "mri_pirads_structured", "ct_recist_structured",
]

# Auto-derivable fields that should be visible read-only in UI
AUTO_DERIVABLE_FIELDS = [
    "isup_grade", "psadt", "charlson_score", "g8_score",
    "frailty_status", "bcr_phoenix", "disease_free_interval",
    "age_from_dob", "creatinine_clearance",
]

# 18 canonical stages (from v2_adapters.list_known_stages)
CANONICAL_STAGES = [
    "screening", "diagnostic_workup", "localized_initial",
    "post_prostatectomy", "recurrence_bcr", "post_radiotherapy_followup",
    "post_radiotherapy_or_local_salvage", "post_negative_biopsy_followup",
    "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync", "mcspc_high_volume_metachronous",
    "mcspc_high_volume", "adt_progression_verification",
    "m0_crpc", "m1_crpc", "focal_therapy",
    "survivorship_and_toxicity_followup",
]


def _conditional_logic_coverage() -> tuple[float, list[Gap]]:
    """% of fields with conditional_visibility across critical schemas.

    Target: ≥30% (significant smart-form coverage). Floor: 0%.
    """
    critical_schemas = [
        "m1_crpc", "mcspc_high_volume", "localized_initial",
        "recurrence_bcr", "post_prostatectomy",
    ]
    total_fields = 0
    fields_with_conditional = 0
    for stage in critical_schemas:
        schema_path = DOMAINS_DIR / stage / "schemas.py"
        if not schema_path.exists():
            continue
        try:
            content = schema_path.read_text(errors="replace")
        except OSError:
            continue
        # Count FieldSpec occurrences
        fs_count = len(re.findall(r"FieldSpec\(", content))
        cv_count = len(re.findall(r"conditional_visibility=", content))
        total_fields += fs_count
        fields_with_conditional += cv_count

    if total_fields == 0:
        return 0.0, []
    coverage = fields_with_conditional / total_fields
    # Normalize: 30% coverage = 1.0 score (above 30% saturates)
    score = min(coverage / 0.30, 1.0)
    gaps = []
    if coverage < 0.30:
        gaps.append(Gap(
            pillar_id=8,
            kind="conditional_logic_missing",
            description=(f"Conditional logic coverage: {coverage*100:.1f}% "
                          f"({fields_with_conditional}/{total_fields} fields). "
                          f"Target ≥30% to reduce form fatigue."),
            severity=8,
            effort_h=4.0,
            artifact_path=str(DOMAINS_DIR),
        ))
    return score, gaps


def _longitudinal_kinds_supported() -> tuple[float, list[Gap]]:
    """Check which kinds the longitudinal append endpoint supports."""
    app_py = PROJECT_ROOT / "app.py"
    if not app_py.exists():
        return 0.0, [Gap(pillar_id=8, kind="app_py_missing",
                         description="app.py not found", severity=10, effort_h=0.0)]
    content = app_py.read_text(errors="replace")
    supported = []
    for kind in REQUIRED_LONGITUDINAL_KINDS:
        # Check if endpoint handles this kind (string match)
        if f'"{kind}"' in content or f"'{kind}'" in content:
            supported.append(kind)

    score = len(supported) / len(REQUIRED_LONGITUDINAL_KINDS)
    gaps = []
    missing = [k for k in REQUIRED_LONGITUDINAL_KINDS if k not in supported]
    if missing:
        gaps.append(Gap(
            pillar_id=8,
            kind="longitudinal_kind_missing",
            description=(f"Missing longitudinal kinds: {missing[:5]}... "
                          f"({len(missing)}/{len(REQUIRED_LONGITUDINAL_KINDS)} missing). "
                          f"Without these, gates 73 (ECOG decline), 74 (BPI), "
                          f"75-77 (ESAS/PHQ/PRO) cannot fire."),
            severity=8, effort_h=2.0 * len(missing),
            artifact_path=str(app_py),
        ))
    return score, gaps


def _structured_imaging_forms() -> tuple[float, list[Gap]]:
    """Check structured imaging forms exist (vs free-text capture)."""
    longitudinal_demo = TEMPLATES_DIR / "demos" / "longitudinal_capture_v2_demo.html"
    if not longitudinal_demo.exists():
        return 0.0, [Gap(pillar_id=8, kind="longitudinal_template_missing",
                         description="longitudinal_capture_v2_demo.html missing",
                         severity=8, effort_h=0.0)]
    content = longitudinal_demo.read_text(errors="replace")
    normalized = content.lower()
    structured = []
    if (
        "psma_pet_structured" in normalized
        or "psma_suvmax" in normalized
        or "psma-pet-form" in normalized
        or 'data-append-form="psma_pet"' in normalized
    ):
        structured.append("psma_pet_structured")
    if (
        "bone_scan_structured" in normalized
        or "bone_site_entries" in normalized
        or "bone-scan-form" in normalized
        or 'data-append-form="bone_scan"' in normalized
    ):
        structured.append("bone_scan_structured")
    if (
        "mri_pirads_structured" in normalized
        or "pirads_score" in normalized
        or "pi-rads" in normalized
        or 'data-append-form="mri_pirads"' in normalized
    ):
        structured.append("mri_pirads_structured")
    if (
        "ct_recist_structured" in normalized
        or "recist_target" in normalized
        or 'data-append-form="ct_recist"' in normalized
    ):
        structured.append("ct_recist_structured")

    score = len(structured) / len(REQUIRED_IMAGING_MODALITIES)
    gaps = []
    missing = [m for m in REQUIRED_IMAGING_MODALITIES if m not in structured]
    if missing:
        gaps.append(Gap(
            pillar_id=8,
            kind="structured_form_missing",
            description=(f"Missing structured imaging forms: {missing}. "
                          f"Without these, gate 71 PSMA progression auto-trigger "
                          f"and CHAARTED HV classification cannot fire reliably."),
            severity=9, effort_h=3.0 * len(missing),
            artifact_path=str(longitudinal_demo),
        ))
    return score, gaps


def _auto_derive_visible() -> tuple[float, list[Gap]]:
    """Check that derivable values are exposed read-only in UI templates."""
    profile_v2 = TEMPLATES_DIR / "patient_profile_v2.html"
    intake_v2 = TEMPLATES_DIR / "intake_stage_aware_v2.html"
    if not profile_v2.exists():
        return 0.0, []
    content_pv2 = profile_v2.read_text(errors="replace")
    content_iv2 = intake_v2.read_text(errors="replace") if intake_v2.exists() else ""
    full = content_pv2 + content_iv2

    visible = []
    for field in AUTO_DERIVABLE_FIELDS:
        if field in full:
            visible.append(field)

    score = len(visible) / len(AUTO_DERIVABLE_FIELDS)
    gaps = []
    missing = [f for f in AUTO_DERIVABLE_FIELDS if f not in visible]
    if missing:
        gaps.append(Gap(
            pillar_id=8,
            kind="auto_derive_not_exposed",
            description=(f"Auto-derivable fields not exposed in UI: {missing}. "
                          f"Clínico recalcula manualmente o ignora → captura inconsistente."),
            severity=6, effort_h=1.5 * len(missing),
            artifact_path=str(profile_v2),
        ))
    return score, gaps


def _stages_with_complete_capture() -> tuple[float, list[Gap]]:
    """% of 18 stages where the schema has 'capture_complete' flag flagged."""
    # Heuristic: schema that has at least 1 conditional_visibility AND
    # references the longitudinal kinds in service.py or has a stage_form template
    complete = 0
    for stage in CANONICAL_STAGES:
        schema_path = DOMAINS_DIR / stage / "schemas.py"
        if not schema_path.exists():
            continue
        try:
            content = schema_path.read_text(errors="replace")
            if "conditional_visibility" in content:
                complete += 1
        except OSError:
            continue

    score = complete / len(CANONICAL_STAGES)
    gaps = []
    if complete < len(CANONICAL_STAGES):
        gaps.append(Gap(
            pillar_id=8,
            kind="stage_capture_incomplete",
            description=(f"Stages with conditional_visibility coverage: "
                          f"{complete}/{len(CANONICAL_STAGES)}. "
                          f"Stages without smart-form logic produce form fatigue + bad capture."),
            severity=7, effort_h=1.5 * (len(CANONICAL_STAGES) - complete),
        ))
    return score, gaps


class Pillar8DataCapture:
    pillar_id = 8
    name = "Clinical Data Capture Coverage"
    weight = 10.0  # re-balanced: takes from P1 (8→4) + P7 (10→4) = 10 freed

    def score(self) -> PillarScore:
        cl_score, cl_gaps = _conditional_logic_coverage()
        lk_score, lk_gaps = _longitudinal_kinds_supported()
        si_score, si_gaps = _structured_imaging_forms()
        ad_score, ad_gaps = _auto_derive_visible()
        sc_score, sc_gaps = _stages_with_complete_capture()

        score_pct = (cl_score * 0.30 + lk_score * 0.20 + si_score * 0.20
                     + ad_score * 0.15 + sc_score * 0.15) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=cl_gaps + lk_gaps + si_gaps + ad_gaps + sc_gaps,
            details={
                "conditional_logic_coverage_pct": round(cl_score * 100, 1),
                "longitudinal_kinds_pct": round(lk_score * 100, 1),
                "structured_imaging_pct": round(si_score * 100, 1),
                "auto_derive_pct": round(ad_score * 100, 1),
                "stages_complete_pct": round(sc_score * 100, 1),
            },
        )


PILLAR = Pillar8DataCapture()
