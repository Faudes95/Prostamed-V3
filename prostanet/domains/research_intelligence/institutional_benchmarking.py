from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.live_benchmark import build_live_benchmark_summary
from prostanet.domains.research_intelligence.benchmark_repository import (
    list_references,
    persist_comparison,
    seed_reference,
)


DEFAULT_REFERENCES = [
    {
        "benchmark_key": "seer_os_advanced",
        "title": "Supervivencia global en enfermedad avanzada",
        "endpoint": "OS",
        "source_label": "SEER / series publicadas",
        "population_summary": "Pacientes avanzados comparables por estado clínico.",
        "median_months": 36.0,
        "comparability_tier": "contextual",
    },
    {
        "benchmark_key": "ncdb_positive_margin",
        "title": "Márgenes positivos post-RP",
        "endpoint": "positive_margin_rate",
        "source_label": "NCDB / series institucionales",
        "population_summary": "Pacientes post-RP localizados.",
        "median_months": None,
        "comparability_tier": "contextual",
    },
]


def _seed_library() -> None:
    for reference in DEFAULT_REFERENCES:
        seed_reference(reference)


def build_institutional_benchmark_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    _seed_library()
    internal_summary = build_live_benchmark_summary(records)
    references = list_references()
    comparisons = []
    for reference in references:
        comparison = {
            "benchmark_key": reference.get("benchmark_key"),
            "cohort_key": "institutional",
            "title": reference.get("title"),
            "endpoint": reference.get("endpoint"),
            "source_label": reference.get("source_label"),
            "comparability_tier": reference.get("comparability_tier", "limited"),
            "internal_metric": internal_summary.get("published_reference_alignment", {}).get(reference.get("endpoint")),
            "reference_metric": (reference.get("payload") or {}).get("median_months"),
            "gap_label": "Comparación contextual",
        }
        persist_comparison(comparison)
        comparisons.append(comparison)
    return {
        "internal_summary": internal_summary,
        "references": references,
        "comparisons": comparisons,
    }
