"""Pilar 4 — ISO 14971 + AAMI TIR57 (Risk Management).

Métrica: `(hazards_with_full_fmea/15)*0.6 + (mitigations_implemented/planned)*0.3 + tir57_addendum*0.1`

FMEA tabular requerido (mín 15 peligros próstata) en
`prostanet/regulatory/risk/FMEA-prostanet-2026.{xlsx,yaml,csv}`.

Cada peligro debe tener: severity, occurrence, detectability, RPN, mitigation_id,
mitigation_status, control_verification.
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
RISK_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "risk"

REQUIRED_FMEA_FIELDS = [
    "hazard", "severity", "occurrence", "detectability",
    "rpn", "mitigation_id", "mitigation_status",
]
REQUIRED_HAZARDS_MIN = 15
TIR57_PATH_CANDIDATES = [
    RISK_DIR / "tir57_addendum.md",
    RISK_DIR / "TIR57-cybersecurity-addendum.md",
]

# Canonical hazards prostate cancer (LXXXVIII seed):
EXPECTED_HAZARDS = [
    "psa_stale_decision",
    "gate_misclassification",
    "arpi_dose_miscalc",
    "crpc_transition_missed",
    "false_negative_localized_delays_treatment",
    "false_positive_biopsy_overtreatment",
    "gleason_scoring_error",
    "hrr_missing_blocks_parp",
    "ddi_undetected_toxicity",
    "transition_proposal_ignored",
    "trial_eligibility_false_positive",
    "psa_history_data_loss",
    "phi_exposure_unauthorized_access",
    "ml_inference_drift",
    "dose_calculation_unit_mismatch",
]


def _load_fmea() -> tuple[list[dict], list[str]]:
    """Returns (hazards, errors) from FMEA file (yaml/csv preferred)."""
    yaml_path = RISK_DIR / "fmea-prostanet-2026.yaml"
    csv_path = RISK_DIR / "fmea-prostanet-2026.csv"

    if yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text()) or {}
            hazards = data.get("hazards", [])
            return hazards, []
        except yaml.YAMLError as e:
            return [], [f"yaml parse: {e}"]
    if csv_path.exists():
        try:
            with csv_path.open() as f:
                return list(csv.DictReader(f)), []
        except Exception as e:
            return [], [f"csv parse: {e}"]
    return [], ["fmea_file_missing"]


def _hazard_complete(hazard: dict) -> bool:
    return all(hazard.get(f) not in (None, "", "null") for f in REQUIRED_FMEA_FIELDS)


class Pillar4Risk:
    pillar_id = 4
    name = "ISO 14971 + AAMI TIR57 Risk"
    weight = 12.0

    def score(self) -> PillarScore:
        hazards, errors = _load_fmea()
        gaps: list[Gap] = []

        if errors and "fmea_file_missing" in errors:
            return PillarScore(
                pillar_id=self.pillar_id,
                name=self.name,
                score=0.0,
                weight=self.weight,
                gaps=[Gap(
                    pillar_id=4,
                    kind="fmea_file_missing",
                    description="Missing FMEA tabular (15+ hazards required) — fmea-prostanet-2026.yaml or .csv",
                    severity=10, effort_h=20.0,
                    evidence_source=str(RISK_DIR),
                    artifact_path=str(RISK_DIR / "fmea-prostanet-2026.yaml"),
                )],
                details={"hazards_count": 0, "errors": errors},
            )

        complete = sum(1 for h in hazards if _hazard_complete(h))
        hazard_score = min(complete / REQUIRED_HAZARDS_MIN, 1.0)

        # Detect specific missing hazards
        recorded_kinds = {(h.get("hazard") or h.get("kind") or "").lower() for h in hazards}
        missing_canonical = [h for h in EXPECTED_HAZARDS
                             if h.lower() not in recorded_kinds]
        for missing in missing_canonical[:5]:  # cap top 5
            gaps.append(Gap(
                pillar_id=4,
                kind=f"fmea_entry_missing:{missing}",
                description=f"FMEA missing canonical prostate-cancer hazard: {missing}",
                severity=7, effort_h=1.0,
                artifact_path=str(RISK_DIR / "fmea-prostanet-2026.yaml"),
            ))

        # Mitigations implemented
        planned = sum(1 for h in hazards if h.get("mitigation_id"))
        implemented = sum(1 for h in hazards
                          if (h.get("mitigation_status") or "").lower()
                          in {"implemented", "verified", "controlled"})
        mit_score = (implemented / planned) if planned else 0.0
        if planned and implemented < planned:
            gaps.append(Gap(
                pillar_id=4,
                kind="fmea_mitigations_incomplete",
                description=f"FMEA mitigations: {implemented}/{planned} implemented",
                severity=8, effort_h=2.0 * (planned - implemented),
            ))

        # TIR57 addendum
        tir57_present = any(p.exists() and p.stat().st_size > 200
                            for p in TIR57_PATH_CANDIDATES)
        tir57_score = 1.0 if tir57_present else 0.0
        if not tir57_present:
            gaps.append(Gap(
                pillar_id=4,
                kind="tir57_addendum_missing",
                description="Missing AAMI TIR57 cybersecurity-risk addendum",
                severity=6, effort_h=3.0,
                artifact_path=str(TIR57_PATH_CANDIDATES[0]),
            ))

        score_pct = (hazard_score * 0.6 + mit_score * 0.3 + tir57_score * 0.1) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=gaps,
            details={
                "hazards_complete": complete,
                "hazards_min_required": REQUIRED_HAZARDS_MIN,
                "mitigations_implemented": implemented,
                "mitigations_planned": planned,
                "tir57_addendum_present": tir57_present,
            },
        )


PILLAR = Pillar4Risk()
