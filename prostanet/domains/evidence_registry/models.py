from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class GuidelineMetadata:
    guideline: str
    version: str
    effective_date: str
    source_type: str
    source_ref: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModuleEvidence:
    module: str
    title: str
    nccn_panels: list[str]
    eau_sections: list[str]
    pivotal_trials: list[str] = field(default_factory=list)
    core_questions: list[str] = field(default_factory=list)
    source_citations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    document_id: str
    ordinal: int
    page_start: int
    page_end: int
    text: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceDocument:
    document_id: str
    title: str
    source_path: str
    sha256: str
    indexed_at: str
    page_count: int
    license_class: str
    chunks: list[EvidenceChunk] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["chunks"] = [chunk.to_dict() for chunk in self.chunks]
        return data
