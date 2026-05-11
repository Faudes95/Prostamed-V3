from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class LaboratoryAlert:
    key: str
    severity: str
    category: str
    title: str
    message: str
    recommended_action: str = ""
    guideline_reference: str = ""
    biomarker_key: str = ""
    triggering_value: str = ""
    threshold: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LaboratoryTrendSeries:
    key: str
    label: str
    unit: str
    family: str
    points: list[dict[str, Any]] = field(default_factory=list)
    latest_value: Any = None
    latest_date: str = ""
    status: str = "neutral"
    source: str = "longitudinal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
