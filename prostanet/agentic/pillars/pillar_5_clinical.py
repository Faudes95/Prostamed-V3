"""Pilar 5 — Validación clínica IMDRF SaMD N41.

Métrica: `(gates_with_trial_evidence/89)*0.4 + (gates_with_retro_validation/89)*0.3
        + prospective_protocol_signed*0.15 + prospective_data_collected*0.15`

- gates_with_trial_evidence: gates YAML con `trial_refs` non-empty
- gates_with_retro_validation: filas en retro_validation_results.{xlsx,yaml}
  con AUC/PPV/NPV per gate sobre cohorte SQLite
- prospective_protocol_signed: presence de signed_protocol.md flag
- prospective_data_collected: presence de cohort enrollment ≥50 pts (placeholder)

**Cap automatizado: 85%** (15% requiere protocolo prospectivo human-firmado).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
GATES_DIR = PROJECT_ROOT / "prostanet" / "shared" / "pivotal_gates_catalog"
CLINICAL_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "clinical"

PROTOCOL_PATH = CLINICAL_DIR / "protocol_prospective.md"
PROTOCOL_SIGNED_FLAG = CLINICAL_DIR / "protocol_signed.flag"
RETRO_RESULTS_YAML = CLINICAL_DIR / "retro_validation_results.yaml"
COHORT_STATUS = CLINICAL_DIR / "prospective_cohort_status.yaml"

EXPECTED_GATES_TOTAL = 89


def _count_gates_with_evidence() -> int:
    """Iterate gates_catalog/*.yaml, count those with trial_refs[] non-empty."""
    if not GATES_DIR.exists():
        return 0
    count = 0
    for path in GATES_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data, dict) and data.get("trial_refs"):
                count += 1
        except yaml.YAMLError:
            pass
    return count


def _count_gates_with_retro_validation() -> int:
    """Reads retro_validation_results.yaml — count gates con AUC/PPV/NPV computed."""
    if not RETRO_RESULTS_YAML.exists():
        return 0
    try:
        data = yaml.safe_load(RETRO_RESULTS_YAML.read_text()) or {}
        results = data.get("results", []) if isinstance(data, dict) else []
        return sum(1 for r in results
                   if isinstance(r, dict)
                   and r.get("auc") is not None
                   and r.get("ppv") is not None)
    except yaml.YAMLError:
        return 0


def _is_prospective_protocol_signed() -> bool:
    if not PROTOCOL_SIGNED_FLAG.exists():
        return False
    if not PROTOCOL_PATH.exists():
        return False
    return PROTOCOL_PATH.stat().st_size > 1000


def _prospective_data_collected_score() -> float:
    if not COHORT_STATUS.exists():
        return 0.0
    try:
        data = yaml.safe_load(COHORT_STATUS.read_text()) or {}
        enrolled = int(data.get("enrolled_count", 0) or 0)
        target = int(data.get("target_n", 500) or 500)
        return min(enrolled / target, 1.0)
    except (yaml.YAMLError, ValueError, TypeError):
        return 0.0


class Pillar5Clinical:
    pillar_id = 5
    name = "Validación clínica IMDRF SaMD N41"
    weight = 25.0

    def score(self) -> PillarScore:
        gates_with_evidence = _count_gates_with_evidence()
        gates_with_retro = _count_gates_with_retro_validation()
        prosp_signed = _is_prospective_protocol_signed()
        prosp_data = _prospective_data_collected_score()

        gates_evidence_pct = gates_with_evidence / EXPECTED_GATES_TOTAL
        gates_retro_pct = gates_with_retro / EXPECTED_GATES_TOTAL

        score_pct = (
            gates_evidence_pct * 0.4
            + gates_retro_pct * 0.3
            + (1.0 if prosp_signed else 0.0) * 0.15
            + prosp_data * 0.15
        ) * 100.0

        gaps: list[Gap] = []
        # Trial evidence gaps (top 5 missing)
        if gates_with_evidence < EXPECTED_GATES_TOTAL:
            missing = EXPECTED_GATES_TOTAL - gates_with_evidence
            gaps.append(Gap(
                pillar_id=5,
                kind="trial_evidence_missing",
                description=f"Gates without trial_refs: {missing}/{EXPECTED_GATES_TOTAL} — backfill via PubMed",
                severity=7,
                effort_h=missing * 0.3,  # ~20min/gate via pubmed-database skill
                evidence_source=str(GATES_DIR),
            ))

        # Retro validation gaps
        if gates_with_retro < EXPECTED_GATES_TOTAL:
            missing_retro = EXPECTED_GATES_TOTAL - gates_with_retro
            gaps.append(Gap(
                pillar_id=5,
                kind="retro_validation_missing",
                description=f"Gates without retro AUC/PPV/NPV: {missing_retro}/{EXPECTED_GATES_TOTAL} — compute over SQLite cohort",
                severity=8,
                effort_h=missing_retro * 0.2,
                artifact_path=str(RETRO_RESULTS_YAML),
            ))

        # Prospective protocol
        if not prosp_signed:
            gaps.append(Gap(
                pillar_id=5,
                kind="prospective_protocol_missing",
                description="Prospective validation protocol NOT signed (human-gated; loop produces draft only)",
                severity=9,
                effort_h=12.0,  # loop drafting; signing is out-of-loop
                artifact_path=str(PROTOCOL_PATH),
            ))

        if prosp_data < 1.0 and prosp_signed:
            enrolled = int(prosp_data * 500)
            gaps.append(Gap(
                pillar_id=5,
                kind="prospective_data_incomplete",
                description=f"Prospective cohort: {enrolled}/500 enrolled (out-of-loop; calendar 12mo)",
                severity=9, effort_h=0.0,  # loop cannot accelerate
            ))

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=gaps,
            details={
                "gates_with_trial_evidence": gates_with_evidence,
                "gates_with_retro_validation": gates_with_retro,
                "gates_total_expected": EXPECTED_GATES_TOTAL,
                "prospective_protocol_signed": prosp_signed,
                "prospective_enrollment_pct": round(prosp_data * 100, 1),
                "automated_cap_pct": 85.0,  # cap sin prospectivo
            },
        )


PILLAR = Pillar5Clinical()
