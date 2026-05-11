from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SurvivalEndpointRecord:
    endpoint: str
    cohort_size: int
    event_count: int
    median_months: float | None = None
    strata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SurvivalCurvePayload:
    endpoint: str
    timeline: list[dict[str, Any]]
    curve_points: list[dict[str, Any]]
    reliability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CoxModelPayload:
    endpoint: str
    cohort_label: str
    covariates: list[str]
    rows: list[dict[str, Any]]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LogisticModelPayload:
    outcome: str
    cohort_label: str
    covariates: list[str]
    rows: list[dict[str, Any]]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PropensityMatchResult:
    treatment_field: str
    treatment_value: str
    control_value: str
    matched_pairs: int
    balance: list[dict[str, Any]]
    outcome_summary: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperationalOutcomeEvent:
    patient_id: int
    event_type: str
    event_date: str
    severity: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClavienDindoEvent:
    patient_id: int
    surgery_date: str
    grade: str
    event_label: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FunctionalRecoverySnapshot:
    patient_id: int
    snapshot_date: str
    urinary_recovery_status: str = ""
    sexual_recovery_status: str = ""
    continence_pads_per_day: float | None = None
    pde5i_use: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QualityIndicatorDefinition:
    indicator_key: str
    title: str
    clinical_definition: str
    benchmark_target: str = ""
    domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QualityIndicatorResult:
    indicator_key: str
    numerator: int
    denominator: int
    percentage: float
    benchmark_target: str = ""
    trend: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkReference:
    benchmark_key: str
    title: str
    endpoint: str
    source_label: str
    median_months: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkComparison:
    benchmark_key: str
    cohort_label: str
    gap_value: float | None = None
    comparability_tier: str = "limited"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DynamicCohortDefinition:
    cohort_key: str
    title: str
    filters: list[dict[str, Any]]
    description: str = ""
    system_defined: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConsentVersion:
    version_code: str
    title: str
    consent_text: str
    effective_at: str
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConsentEvidence:
    patient_id: int | None
    version_code: str
    signer_name: str
    signed_at: str
    signature_data_url: str
    content_hash: str
    audit_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchExportManifest:
    export_type: str
    schema_version: str
    generated_at: str
    record_count: int
    files: list[dict[str, Any]]
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
