# IEC 62304 §5.5 (Software unit verification)
"""Tests EPIC 14a — Stage capture coverage hybrid fix.

Approach B (Recommended):
  1. Refactor scorer `_stages_with_complete_capture()` para reconocer schemas
     heredados (mcspc_high_volume_sync, mcspc_high_volume_metachronous heredan
     de mcspc_high_volume/schemas.py via _build_schema factory). Esto resuelve
     2 false-negatives del scorer original sin tocar schemas reales.
  2. Agregar conditional_visibility a 2 schemas con beneficio clínico real:
     - post_negative_biopsy_followup: PIRADS-dependent + biopsy-type-dependent
     - adt_progression_verification: ADT-context-dependent + progression-pattern-dependent

Resultado esperado: 13/18 → 15/18 stages (≥83%) con coverage real
de smart-form logic en flows críticos.

Beneficio clínico documentado:
  - Reduces form fatigue (preguntas se ocultan cuando no aplican clínicamente)
  - Capture quality up (clínicos solo ven preguntas relevantes al paciente)
  - Time-to-decision down (menos campos rellenados con default values incorrectos)
  - Specific flows mejorados: post-biopsy MRI evaluation + ADT progression check
"""
from __future__ import annotations

import pytest


def test_epic14a_scorer_recognizes_inherited_schemas():
    """The scorer must recognize mcspc_high_volume_sync/_metachronous as
    inheriting from mcspc_high_volume/schemas.py (not false-negative
    `schema_missing`).
    """
    from prostanet.agentic.pillars.pillar_8_data_capture import (
        _INHERITED_SCHEMA_FILES,
    )
    assert _INHERITED_SCHEMA_FILES.get("mcspc_high_volume_sync") == "mcspc_high_volume"
    assert _INHERITED_SCHEMA_FILES.get("mcspc_high_volume_metachronous") == "mcspc_high_volume"


def test_epic14a_post_negative_biopsy_has_conditional_visibility():
    """post_negative_biopsy_followup/schemas.py must contain conditional_visibility
    in at least one FieldSpec (EPIC 14a smart-form).
    """
    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "prostanet" / "domains" / "post_negative_biopsy_followup" / "schemas.py"
    content = schema_path.read_text()
    assert "conditional_visibility" in content, (
        "post_negative_biopsy_followup schemas.py must declare conditional_visibility (EPIC 14a)."
    )
    # Should reference pirads_score or prior_biopsy_type as trigger.
    assert ("pirads_score" in content) or ("prior_biopsy_type" in content)


def test_epic14a_adt_progression_has_conditional_visibility():
    """adt_progression_verification/schemas.py must contain conditional_visibility
    (EPIC 14a smart-form for current_adt_context + progression_pattern).
    """
    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "prostanet" / "domains" / "adt_progression_verification" / "schemas.py"
    content = schema_path.read_text()
    assert "conditional_visibility" in content, (
        "adt_progression_verification schemas.py must declare conditional_visibility (EPIC 14a)."
    )


def test_epic14a_pillar8_stage_capture_score_improved():
    """Stage capture score should be ≥15/18 (83%) after EPIC 14a:
    - 11 pre-existing stages with conditional_visibility
    - +2 inherited recognized (mcspc_sync, mcspc_metachronous) = 13
    - +2 new schemas with smart-form (post_negative, adt_verif) = 15
    """
    from prostanet.agentic.pillars.pillar_8_data_capture import (
        _stages_with_complete_capture,
        CANONICAL_STAGES,
    )
    score, gaps = _stages_with_complete_capture()
    expected_min = 15 / len(CANONICAL_STAGES)
    assert score >= expected_min, (
        f"stage_capture score={score:.3f}, expected ≥{expected_min:.3f} "
        f"({int(score*len(CANONICAL_STAGES))}/{len(CANONICAL_STAGES)} vs "
        f"15/{len(CANONICAL_STAGES)} target post-EPIC 14a)."
    )


def test_epic14a_post_negative_biopsy_persistent_lesion_conditional():
    """The persistent_lesion_signal field must be conditional on pirads_score 3-5
    (clinically only relevant when MRI suggests persistent suspicious lesion).
    """
    from prostanet.domains.post_negative_biopsy_followup.schemas import (
        POST_NEGATIVE_BIOPSY_SCHEMA,
    )
    fields = POST_NEGATIVE_BIOPSY_SCHEMA["fields"]
    field = next((f for f in fields if f["name"] == "persistent_lesion_signal"), None)
    assert field is not None, "persistent_lesion_signal missing from schema"
    cv = field.get("conditional_visibility") or {}
    assert "pirads_score" in cv, (
        f"persistent_lesion_signal must be conditional on pirads_score; got cv={cv}"
    )
    assert set(cv["pirads_score"]).issuperset({"3", "4", "5"}), (
        f"pirads_score trigger must include 3, 4, 5; got {cv.get('pirads_score')}"
    )


def test_epic14a_adt_progression_psadt_conditional_on_pattern():
    """psadt_months must be conditional on progression_pattern biochemical_only
    or mixed (PSADT secondary in radiographic/clinical progression).
    """
    from prostanet.domains.adt_progression_verification.schemas import (
        ADT_PROGRESSION_VERIFICATION_SCHEMA,
    )
    fields = ADT_PROGRESSION_VERIFICATION_SCHEMA["fields"]
    field = next((f for f in fields if f["name"] == "psadt_months"), None)
    assert field is not None, "psadt_months missing from schema"
    cv = field.get("conditional_visibility") or {}
    assert "progression_pattern" in cv, (
        f"psadt_months must be conditional on progression_pattern; got {cv}"
    )
    expected_triggers = {"biochemical_only", "mixed"}
    assert set(cv["progression_pattern"]) >= expected_triggers, (
        f"progression_pattern must include {expected_triggers}; got {cv.get('progression_pattern')}"
    )


def test_epic14a_pillar8_no_critical_stage_capture_gap():
    """Pillar 8 should still emit stage_capture_incomplete gap if <18, but with
    severity 7 (existing). Verify it does NOT contain falsely-flagged
    mcspc_high_volume_sync nor mcspc_high_volume_metachronous in description.
    """
    from prostanet.agentic.pillars.pillar_8_data_capture import (
        _stages_with_complete_capture,
    )
    _, gaps = _stages_with_complete_capture()
    if gaps:
        desc = gaps[0].description
        # mcspc_high_volume_sync/_metachronous SHOULD NOT appear as missing
        # because they inherit from mcspc_high_volume.
        assert "mcspc_high_volume_sync (schema_missing)" not in desc
        assert "mcspc_high_volume_metachronous (schema_missing)" not in desc


def test_epic14a_loop_monitor_stage_capture_score_improved():
    """Loop Monitor reflects improved stage capture coverage."""
    from prostanet.agentic.autonomous_improvement_os import (
        build_autonomous_improvement_bundle,
    )
    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    candidates = bundle.get("gaps", {}).get("candidates", []) or []
    sc_cand = next(
        (c for c in candidates
         if isinstance(c, dict) and "stage_capture_incomplete" in c.get("title", "")),
        None,
    )
    if sc_cand is not None:
        # If still present, must have lower effort_h than the pre-EPIC 14a 10.5h
        # (since now only 3 stages missing, not 5+).
        effort = sc_cand.get("effort_h", 999)
        assert effort < 10.5, (
            f"stage_capture_incomplete effort_h={effort}, expected <10.5 "
            "after EPIC 14a (3 remaining missing vs 7 originally)."
        )
