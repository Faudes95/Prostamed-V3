"""Pilar 7 — Design History File (DHF) trazable.

Métrica: `(reqs_with_full_chain/total_reqs)*0.7 + cr_log_present*0.15 + design_input_baseline_locked*0.15`

- Trazabilidad matrix: prostanet/regulatory/dhf/traceability_matrix.{xlsx,yaml,csv}
  cada fila debe tener req_id, code_path, test_id, mitigation_id (las 4 columnas).
- CR log: change_request_log.{xlsx,yaml,csv}
- Design input baseline: design_input_baseline.lock (tag-like marker)
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DHF_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "dhf"

REQUIRED_TRACE_COLS = ["req_id", "code_path", "test_id", "mitigation_id"]


def _load_traceability() -> tuple[list[dict], list[str]]:
    yaml_path = DHF_DIR / "traceability_matrix.yaml"
    csv_path = DHF_DIR / "traceability_matrix.csv"
    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text()) or {}
            return data.get("rows", []), []
        except yaml.YAMLError as e:
            return [], [f"yaml_parse: {e}"]
    if csv_path.exists():
        try:
            with csv_path.open() as f:
                return list(csv.DictReader(f)), []
        except Exception as e:
            return [], [f"csv_parse: {e}"]
    return [], ["traceability_file_missing"]


def _row_complete(row: dict) -> bool:
    return all(row.get(c) not in (None, "", "null") for c in REQUIRED_TRACE_COLS)


class Pillar7DHF:
    pillar_id = 7
    name = "Design History File (DHF) trazable"
    weight = 4.0  # LXC: rebalanced 10→4 to make room for P8

    def score(self) -> PillarScore:
        rows, errors = _load_traceability()
        gaps: list[Gap] = []

        if "traceability_file_missing" in errors:
            return PillarScore(
                pillar_id=self.pillar_id,
                name=self.name,
                score=0.0,
                weight=self.weight,
                gaps=[Gap(
                    pillar_id=7,
                    kind="traceability_matrix_missing",
                    description="Missing DHF traceability matrix (traceability_matrix.yaml/csv)",
                    severity=10, effort_h=12.0,
                    artifact_path=str(DHF_DIR / "traceability_matrix.yaml"),
                )],
                details={"rows_complete": 0, "rows_total": 0, "errors": errors},
            )

        complete = sum(1 for r in rows if _row_complete(r))
        total = max(len(rows), 1)
        # Baseline: cuando exista trazabilidad, esperamos al menos cubrir
        # 89 gates + 18 stages = ~107 requirements minimum.
        EXPECTED_REQS_MIN = 107
        chain_score = min(complete / EXPECTED_REQS_MIN, 1.0)

        if complete < EXPECTED_REQS_MIN:
            missing = EXPECTED_REQS_MIN - complete
            gaps.append(Gap(
                pillar_id=7,
                kind="traceability_row_missing",
                description=f"DHF traceability rows complete: {complete}/{EXPECTED_REQS_MIN} expected",
                severity=8, effort_h=missing * 0.1,  # ~6min/row via xlsx skill
                artifact_path=str(DHF_DIR / "traceability_matrix.yaml"),
            ))

        # CR log
        cr_log_path = DHF_DIR / "change_request_log.yaml"
        cr_log_present = cr_log_path.exists() and cr_log_path.stat().st_size > 50
        cr_score = 1.0 if cr_log_present else 0.0
        if not cr_log_present:
            gaps.append(Gap(
                pillar_id=7,
                kind="cr_log_missing",
                description="Missing Change Request log (change_request_log.yaml)",
                severity=7, effort_h=2.0,
                artifact_path=str(cr_log_path),
            ))

        # Design input baseline
        baseline_path = DHF_DIR / "design_input_baseline.lock"
        baseline_locked = baseline_path.exists()
        baseline_score = 1.0 if baseline_locked else 0.0
        if not baseline_locked:
            gaps.append(Gap(
                pillar_id=7,
                kind="design_input_baseline_unlocked",
                description="Design input baseline not locked (no design_input_baseline.lock marker)",
                severity=7, effort_h=1.0,
                artifact_path=str(baseline_path),
            ))

        score_pct = (chain_score * 0.7 + cr_score * 0.15 + baseline_score * 0.15) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=gaps,
            details={
                "rows_complete": complete,
                "rows_total": total,
                "expected_reqs_min": EXPECTED_REQS_MIN,
                "cr_log_present": cr_log_present,
                "design_input_baseline_locked": baseline_locked,
            },
        )


PILLAR = Pillar7DHF()
