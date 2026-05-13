# IEC 62304 §5.5 (Software unit verification)
"""Tests EPIC 12 — Cierre de candidates emergentes del Loop Monitor tras EPIC 11.

EPIC 12 ataca los dos siguientes candidates priorizados por el bucle
autónomo después de cerrar p5.prospective_data_incomplete en EPIC 11:

  12a. shadow_validation_in_progress (sev 5, score 56.5, 0.5h)
       → Implementa shadow_validation_records.jsonl como source canónico
         de oracle pairs validados contra NCCN/EAU (vs proxy débil de
         total_patients de tracking_db).
       → Bootstrap con 10 oracle pairs derivados de EPIC 10A real-world
         test scenarios.
       → Conteo estricto: solo records con
         record_type=`shadow_validation_oracle_pair` + non-empty
         expected_effective_state.

  12b. fmea_mitigations_incomplete (sev 8, score 13.05, 4h)
       → Promueve 2 mitigations FMEA pendientes (MIT-006, MIT-014) de
         `planned` → `controlled` con evidencia auditable:
         - MIT-006 (false_positive_biopsy_overtreatment): controlled via
           pivotal gates pre_biopsy_risk_calculators_phi_4kscore +
           psa_velocity_pre_biopsy_urgent (EPIC 10B canonical coverage).
         - MIT-014 (ml_inference_drift): controlled mitigated_by_design —
           ML predictivo NO está liberado en producción; CDE rule-based.

Resultado esperado: ambos candidates desaparecen / bajan score
significativamente en el Loop Monitor bundle live.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
SHADOW_JSONL = PROJECT_ROOT / "prostanet" / "regulatory" / "clinical" / "shadow_validation_records.jsonl"
FMEA_YAML = PROJECT_ROOT / "prostanet" / "regulatory" / "risk" / "fmea-prostanet-2026.yaml"


# ──────────────────────────────────────────────────────────────────────
# EPIC 12a — shadow validation oracle pairs
# ──────────────────────────────────────────────────────────────────────


def test_epic12a_shadow_validation_jsonl_exists():
    """The canonical shadow validation records JSONL must exist."""
    assert SHADOW_JSONL.exists(), (
        f"shadow_validation_records.jsonl missing at {SHADOW_JSONL}. "
        "EPIC 12a requires canonical oracle pairs source."
    )


def test_epic12a_shadow_validation_has_at_least_10_records():
    """Bootstrap must include ≥10 oracle pairs from EPIC 10A scenarios."""
    records = []
    with SHADOW_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    assert len(records) >= 10, (
        f"shadow_validation_records.jsonl has {len(records)} records, "
        "expected ≥10 (EPIC 10A bootstrap)."
    )


def test_epic12a_each_record_has_canonical_contract():
    """Each oracle pair must declare the full canonical contract."""
    required_keys = {
        "record_id",
        "record_type",
        "expected_effective_state",
        "expected_guideline_basis_any",
        "epic10_evidence",
        "ground_truth_oracle",
        "no_invented_psa",
        "no_invented_treatment_eligibility",
    }
    with SHADOW_JSONL.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            missing = required_keys - rec.keys()
            assert not missing, (
                f"Line {line_no} ({rec.get('record_id', '?')}): missing keys "
                f"{sorted(missing)}. Required for FDA Pre-Sub oracle pair contract."
            )
            assert rec["record_type"] == "shadow_validation_oracle_pair"
            assert rec["no_invented_psa"] is True
            assert rec["no_invented_treatment_eligibility"] is True


def test_epic12a_pillar5_count_uses_jsonl_not_tracking_db():
    """The strict scorer must read from JSONL (≤10 records bootstrap), NOT
    inflate via tracking_db.total_patients (which would proxy any patient
    registered without NCCN/EAU oracle).
    """
    from prostanet.agentic.pillars.pillar_5_clinical import (
        _shadow_validation_records_count,
    )
    count = _shadow_validation_records_count()
    assert count >= 10, (
        f"shadow records count={count}, expected ≥10 from JSONL bootstrap."
    )
    # Upper sanity bound — if scorer doubles up tracking_db, count would be
    # much higher than the JSONL line count.
    line_count = sum(1 for line in SHADOW_JSONL.open() if line.strip())
    assert count == line_count, (
        f"scorer count ({count}) != JSONL line count ({line_count}). "
        "Scorer must read strictly from JSONL post-EPIC 12a."
    )


# ──────────────────────────────────────────────────────────────────────
# EPIC 12b — FMEA mitigations controlled
# ──────────────────────────────────────────────────────────────────────


def test_epic12b_fmea_yaml_exists():
    assert FMEA_YAML.exists(), f"FMEA YAML missing at {FMEA_YAML}."


def test_epic12b_mit006_promoted_to_controlled():
    """MIT-006 (false_positive_biopsy_overtreatment) must be `controlled`
    with EPIC 10B evidence reference.
    """
    import yaml as yaml_lib
    data = yaml_lib.safe_load(FMEA_YAML.read_text()) or {}
    hazards = data.get("hazards", [])
    mit006 = next(
        (h for h in hazards if h.get("mitigation_id") == "MIT-006"),
        None,
    )
    assert mit006 is not None, "MIT-006 missing from FMEA"
    assert mit006.get("mitigation_status", "").lower() in {"controlled", "implemented", "verified"}, (
        f"MIT-006 status={mit006.get('mitigation_status')!r}, expected "
        "controlled/implemented/verified post-EPIC 12b."
    )
    assert "EPIC 12b" in (mit006.get("epic_closure") or ""), (
        "MIT-006 must reference EPIC 12b closure trail."
    )


def test_epic12b_mit014_promoted_to_controlled():
    """MIT-014 (ml_inference_drift) must be `controlled` (mitigated_by_design
    since ML predictive NOT in production scope).
    """
    import yaml as yaml_lib
    data = yaml_lib.safe_load(FMEA_YAML.read_text()) or {}
    hazards = data.get("hazards", [])
    mit014 = next(
        (h for h in hazards if h.get("mitigation_id") == "MIT-014"),
        None,
    )
    assert mit014 is not None, "MIT-014 missing from FMEA"
    assert mit014.get("mitigation_status", "").lower() in {"controlled", "implemented", "verified"}, (
        f"MIT-014 status={mit014.get('mitigation_status')!r}, expected "
        "controlled post-EPIC 12b (mitigated_by_design)."
    )
    assert "EPIC 12b" in (mit014.get("epic_closure") or ""), (
        "MIT-014 must reference EPIC 12b closure trail."
    )


def test_epic12b_all_mitigations_implemented():
    """After EPIC 12b, all 15 FMEA hazards with mitigation_id must have
    status in {implemented, verified, controlled}.
    """
    import yaml as yaml_lib
    data = yaml_lib.safe_load(FMEA_YAML.read_text()) or {}
    hazards = data.get("hazards", [])
    planned = sum(1 for h in hazards if h.get("mitigation_id"))
    implemented = sum(
        1
        for h in hazards
        if (h.get("mitigation_status") or "").lower() in {"implemented", "verified", "controlled"}
    )
    assert implemented == planned and planned >= 15, (
        f"FMEA mitigations: {implemented}/{planned} implemented "
        "(expected 15/15 controlled post-EPIC 12b)."
    )


def test_epic12b_pillar4_no_longer_emits_fmea_mitigations_incomplete():
    """Pillar 4 score must NOT include `fmea_mitigations_incomplete` gap."""
    from prostanet.agentic.pillars.pillar_4_risk import Pillar4Risk
    pillar = Pillar4Risk()
    result = pillar.score()
    gap_kinds = {g.kind for g in result.gaps}
    assert "fmea_mitigations_incomplete" not in gap_kinds, (
        f"Pillar 4 still emits fmea_mitigations_incomplete. "
        f"Active gap kinds: {gap_kinds}"
    )


# ──────────────────────────────────────────────────────────────────────
# Loop Monitor consolidated verification
# ──────────────────────────────────────────────────────────────────────


def test_epic12_loop_monitor_no_longer_lists_legacy_candidates():
    """Loop Monitor bundle must reflect both 12a + 12b closures."""
    from prostanet.agentic.autonomous_improvement_os import (
        build_autonomous_improvement_bundle,
    )
    bundle = build_autonomous_improvement_bundle(patient_limit=4)
    candidates = bundle.get("gaps", {}).get("candidates", []) or []
    legacy_titles = [
        c.get("title", "")
        for c in candidates
        if isinstance(c, dict)
        and (
            "fmea_mitigations_incomplete" in c.get("title", "")
            or "prospective_data_incomplete" in c.get("title", "")
        )
    ]
    assert not legacy_titles, (
        f"Legacy candidates still in Loop Monitor: {legacy_titles}. "
        "EPIC 11+12 did not close them."
    )
