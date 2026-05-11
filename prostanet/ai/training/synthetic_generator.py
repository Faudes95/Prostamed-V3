"""
Synthetic Trajectory Generator — realistic longitudinal patient histories.

Generates 10,000+ synthetic patient trajectories calibrated against
published epidemiological data (SEER, ICECaP, CHAARTED, LATITUDE).

Each trajectory includes: diagnosis → treatment → follow-up → progression →
treatment change → potential further progression → death or censoring.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timedelta
from typing import Any

from prostanet.ai.config import CLINICAL_STATES

logger = logging.getLogger(__name__)

# ── Epidemiological distributions (calibrated to published data) ──

AGE_DISTRIBUTION = {"mean": 68, "std": 8, "min": 45, "max": 95}
PSA_DISTRIBUTION = {"localized": (6.5, 4.0), "metastatic": (45.0, 80.0)}

GLEASON_DISTRIBUTION = [
    (3, 3, 0.15),  # 6
    (3, 4, 0.30),  # 7a
    (4, 3, 0.20),  # 7b
    (4, 4, 0.15),  # 8
    (4, 5, 0.10),  # 9
    (5, 4, 0.05),  # 9
    (5, 5, 0.05),  # 10
]

INITIAL_STATE_DISTRIBUTION = {
    "localized_initial": 0.55,
    "recurrence_bcr": 0.10,
    "mcspc_high_volume_sync": 0.12,
    "mcspc_low_volume_sync_oligo": 0.08,
    "mcspc_oligo_metachronous": 0.05,
    "m0_crpc": 0.04,
    "m1_crpc": 0.06,
}

# State transition probabilities (simplified Markov)
TRANSITION_MATRIX: dict[str, list[tuple[str, float, tuple[float, float]]]] = {
    "localized_initial": [
        ("post_prostatectomy", 0.60, (0.5, 3.0)),
        ("recurrence_bcr", 0.05, (12.0, 36.0)),
    ],
    "post_prostatectomy": [
        ("recurrence_bcr", 0.25, (6.0, 60.0)),
    ],
    "recurrence_bcr": [
        ("m0_crpc", 0.30, (12.0, 48.0)),
        ("mcspc_oligo_metachronous", 0.15, (6.0, 24.0)),
    ],
    "m0_crpc": [
        ("m1_crpc", 0.50, (12.0, 36.0)),
    ],
    "mcspc_high_volume_sync": [
        ("m1_crpc", 0.40, (18.0, 48.0)),
    ],
    "mcspc_low_volume_sync_oligo": [
        ("m1_crpc", 0.25, (24.0, 60.0)),
    ],
    "mcspc_oligo_metachronous": [
        ("m1_crpc", 0.30, (18.0, 48.0)),
    ],
    "m1_crpc": [],  # Terminal state for transitions
}

TREATMENT_BY_STATE: dict[str, list[tuple[str, float]]] = {
    "localized_initial": [
        ("radical_prostatectomy", 0.55),
        ("external_beam_rt", 0.30),
        ("active_surveillance", 0.15),
    ],
    "recurrence_bcr": [
        ("salvage_rt", 0.40),
        ("adt_monotherapy", 0.35),
        ("enzalutamide", 0.25),
    ],
    "mcspc_high_volume_sync": [
        ("adt_docetaxel", 0.35),
        ("adt_abiraterone", 0.30),
        ("adt_darolutamide_docetaxel", 0.20),
        ("adt_enzalutamide", 0.15),
    ],
    "mcspc_low_volume_sync_oligo": [
        ("adt_abiraterone", 0.35),
        ("adt_enzalutamide", 0.30),
        ("adt_rt", 0.20),
        ("adt_monotherapy", 0.15),
    ],
    "mcspc_oligo_metachronous": [
        ("adt_enzalutamide", 0.30),
        ("adt_abiraterone", 0.30),
        ("sbrt_adt", 0.25),
        ("adt_monotherapy", 0.15),
    ],
    "m0_crpc": [
        ("enzalutamide", 0.35),
        ("apalutamide", 0.30),
        ("darolutamide", 0.25),
        ("observation", 0.10),
    ],
    "m1_crpc": [
        ("abiraterone", 0.25),
        ("enzalutamide", 0.20),
        ("docetaxel", 0.20),
        ("cabazitaxel", 0.10),
        ("lu177_psma", 0.10),
        ("olaparib", 0.08),
        ("radium223", 0.07),
    ],
}


def generate_synthetic_trajectories(
    n_patients: int = 10000,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """
    Generate n_patients synthetic longitudinal trajectories.

    Returns list of patient records compatible with get_patient_full_record() format.
    """
    random.seed(seed)
    patients: list[dict[str, Any]] = []

    for i in range(n_patients):
        patient = _generate_single_patient(patient_id=i + 1)
        patients.append(patient)

    logger.info("Generated %d synthetic patient trajectories", len(patients))
    return patients


def _generate_single_patient(patient_id: int) -> dict[str, Any]:
    """Generate a single patient trajectory."""
    # Demographics
    age = max(
        AGE_DISTRIBUTION["min"],
        min(
            AGE_DISTRIBUTION["max"],
            int(random.gauss(AGE_DISTRIBUTION["mean"], AGE_DISTRIBUTION["std"])),
        ),
    )
    diagnosis_date = datetime(2020, 1, 1) + timedelta(
        days=random.randint(0, 1800)
    )

    # Initial state
    initial_state = _weighted_choice(INITIAL_STATE_DISTRIBUTION)

    # Gleason
    gleason_primary, gleason_secondary = _pick_gleason(initial_state)

    # PSA at diagnosis
    if initial_state in ("localized_initial", "post_prostatectomy"):
        psa = max(0.1, random.gauss(*PSA_DISTRIBUTION["localized"]))
    else:
        psa = max(0.5, random.gauss(*PSA_DISTRIBUTION["metastatic"]))

    ecog = random.choices([0, 1, 2, 3], weights=[0.40, 0.35, 0.18, 0.07])[0]

    # Build record
    record: dict[str, Any] = {
        "patient_id": patient_id,
        "identity": {
            "id": patient_id,
            "diagnosis_date": diagnosis_date.strftime("%Y-%m-%d"),
            "age_at_diagnosis": age,
        },
        "baseline": {
            "age": age,
            "baseline_psa": round(psa, 2),
            "ecog_score": ecog,
            "gleason_primary": gleason_primary,
            "gleason_secondary": gleason_secondary,
            "isup_grade": _gleason_to_isup(gleason_primary, gleason_secondary),
            "clinical_tstage": _random_tstage(initial_state),
            "hemoglobin": round(random.gauss(13.5, 1.8), 1),
            "testosterone_baseline": round(random.gauss(350, 120), 0)
            if "crpc" not in initial_state
            else round(random.gauss(15, 8), 0),
            "hrr_positive": random.random() < 0.22,
            "psma_positive": random.random() < 0.85 if "m1" in initial_state else None,
        },
        "reconciled_state": initial_state,
        "follow_ups": [],
        "treatments": [],
        "state_timeline": [],
    }

    # Generate longitudinal trajectory
    _generate_trajectory(record, diagnosis_date, initial_state)

    return record


def _generate_trajectory(
    record: dict, diagnosis_date: datetime, initial_state: str
) -> None:
    """Generate follow-ups, treatments, and state transitions."""
    current_state = initial_state
    current_date = diagnosis_date + timedelta(days=random.randint(7, 60))
    psa = record["baseline"]["baseline_psa"]
    max_years = 8
    end_date = diagnosis_date + timedelta(days=max_years * 365)

    record["state_timeline"].append({
        "state": current_state,
        "date": diagnosis_date.strftime("%Y-%m-%d"),
        "driver": "diagnosis",
    })

    # Assign initial treatment
    tx = _pick_treatment(current_state)
    if tx:
        record["treatments"].append({
            "drug_scheme": tx,
            "start_date": current_date.strftime("%Y-%m-%d"),
            "regimen_id": hash(tx) % 50,
            "outcomes": _generate_treatment_outcomes(tx, record["baseline"]),
        })

    visit_num = 0
    while current_date < end_date and visit_num < 40:
        visit_num += 1
        # PSA evolution
        psa = _evolve_psa(psa, current_state, tx)

        follow_up = {
            "visit_date": current_date.strftime("%Y-%m-%d"),
            "psa_current": round(max(0.01, psa), 2),
            "ecog": min(4, record["baseline"]["ecog_score"] + (1 if visit_num > 20 else 0)),
            "hemoglobin": round(
                max(6, record["baseline"]["hemoglobin"] - visit_num * 0.05 + random.gauss(0, 0.3)),
                1,
            ),
        }
        record["follow_ups"].append(follow_up)

        # Check for state transition
        transitions = TRANSITION_MATRIX.get(current_state, [])
        for next_state, prob, (min_m, max_m) in transitions:
            months_elapsed = (current_date - diagnosis_date).days / 30.44
            if months_elapsed >= min_m and random.random() < prob * 0.05:
                current_state = next_state
                record["reconciled_state"] = current_state
                record["state_timeline"].append({
                    "state": current_state,
                    "date": current_date.strftime("%Y-%m-%d"),
                    "driver": "progression",
                })
                record["time_to_transition_months"] = round(months_elapsed, 1)

                # New treatment for new state
                tx = _pick_treatment(current_state)
                if tx:
                    record["treatments"].append({
                        "drug_scheme": tx,
                        "start_date": current_date.strftime("%Y-%m-%d"),
                        "regimen_id": hash(tx) % 50,
                        "outcomes": _generate_treatment_outcomes(
                            tx, record["baseline"]
                        ),
                    })
                break

        # Next visit interval (3-6 months)
        current_date += timedelta(days=random.randint(60, 180))

    # Survival outcome
    months_total = (current_date - diagnosis_date).days / 30.44
    died = random.random() < (0.02 * months_total / 12)  # ~2% annual mortality base
    if current_state == "m1_crpc":
        died = random.random() < 0.3  # higher for m1_crpc
    record["survival"] = {
        "OS_months": round(months_total, 1),
        "OS_event": 1 if died else 0,
        "rPFS_months": round(months_total * random.uniform(0.4, 0.9), 1),
        "rPFS_event": 1 if random.random() < 0.4 else 0,
    }


def _weighted_choice(dist: dict[str, float]) -> str:
    items = list(dist.items())
    keys = [k for k, _ in items]
    weights = [w for _, w in items]
    return random.choices(keys, weights=weights)[0]


def _pick_gleason(state: str) -> tuple[int, int]:
    weights = [w for _, _, w in GLEASON_DISTRIBUTION]
    if state in ("m1_crpc", "mcspc_high_volume_sync"):
        # Shift toward higher grades
        weights = [w * (0.5 + i * 0.3) for i, (_, _, w) in enumerate(GLEASON_DISTRIBUTION)]
    choice = random.choices(GLEASON_DISTRIBUTION, weights=weights)[0]
    return choice[0], choice[1]


def _gleason_to_isup(primary: int, secondary: int) -> int:
    total = primary + secondary
    if total <= 6:
        return 1
    if total == 7 and primary == 3:
        return 2
    if total == 7 and primary == 4:
        return 3
    if total == 8:
        return 4
    return 5


def _random_tstage(state: str) -> str:
    if state == "localized_initial":
        return random.choice(["T1c", "T2a", "T2b", "T2c", "T3a"])
    return random.choice(["T3a", "T3b", "T4"])


def _pick_treatment(state: str) -> str | None:
    treatments = TREATMENT_BY_STATE.get(state, [])
    if not treatments:
        return None
    names = [t for t, _ in treatments]
    weights = [w for _, w in treatments]
    return random.choices(names, weights=weights)[0]


def _evolve_psa(psa: float, state: str, treatment: str | None) -> float:
    """Simple PSA evolution model."""
    if treatment and treatment not in ("observation", "active_surveillance"):
        # Treatment effect: PSA tends to drop
        change = random.gauss(-0.15, 0.10)
    elif state in ("m1_crpc", "m0_crpc"):
        # Untreated CRPC: rising PSA
        change = random.gauss(0.15, 0.08)
    else:
        change = random.gauss(0.02, 0.05)

    return psa * (1 + change)


def _generate_treatment_outcomes(
    treatment: str, baseline: dict
) -> dict[str, Any]:
    """Generate synthetic treatment outcomes."""
    psa50 = random.uniform(0.3, 0.8)
    psa90 = psa50 * random.uniform(0.3, 0.6)

    if treatment in ("docetaxel", "cabazitaxel"):
        rpfs = random.gauss(12, 4)
    elif treatment in ("enzalutamide", "abiraterone", "apalutamide", "darolutamide"):
        rpfs = random.gauss(18, 6)
    elif treatment in ("lu177_psma",):
        rpfs = random.gauss(9, 3)
    else:
        rpfs = random.gauss(24, 12)

    return {
        "psa50": round(psa50, 2),
        "psa90": round(psa90, 2),
        "rpfs_months": round(max(1, rpfs), 1),
        "response_category": random.choices([0, 1, 2, 3], weights=[0.1, 0.3, 0.35, 0.25])[0],
    }
