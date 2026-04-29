from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalizedPatient:
    age: int
    psa: float
    clinical_tstage: str
    isup_grade: int
    gleason_primary: int
    gleason_secondary: int
    num_cores_positive: int
    total_cores: int
    pct_cores_positive: float
    max_core_involvement: float
    psad: float
    life_expectancy_years: float | None
    ecog_score: int | None
    charlson_score: int | None
    g8_score: float | None
    frailty_status: str
    anesthesia_surgical_fitness: str
    cribriform_pattern: bool
    intraductal_carcinoma: bool
    metastasis_site: str
    nodal_status: str
