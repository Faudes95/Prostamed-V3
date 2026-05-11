from __future__ import annotations

from prostanet.domains.clinical_validation.guideline_oracle import (
    build_guideline_oracle_catalog,
)
from prostanet.domains.clinical_validation.longitudinal_concordance_engine import (
    evaluate_validation_seed,
)
from prostanet.domains.clinical_validation.trajectory_catalog import (
    build_trajectory_catalog,
    list_trajectory_summaries,
)
from prostanet.domains.clinical_validation.trajectory_seed_service import (
    DEFAULT_BASE_URL,
    seed_validation_cohort,
)
from prostanet.domains.clinical_validation.validation_report_builder import (
    build_validation_report,
)
from prostanet.domains.clinical_validation.vertical_verification import (
    run_vertical_verification,
)
from prostanet.domains.clinical_validation.visual_validation_runner import (
    attach_visual_artifacts,
)


def run_longitudinal_validation(
    *,
    base_url: str = DEFAULT_BASE_URL,
    cohort_mode: str = "isolated_temp_db",
    visual_mode: str = "playwright_real",
) -> dict:
    trajectories = build_guideline_oracle_catalog(build_trajectory_catalog())
    seeded = seed_validation_cohort(
        trajectories,
        base_url=base_url,
        cohort_mode=cohort_mode,
    )
    visual_seed = seeded
    if visual_mode == "playwright_real" and cohort_mode == "isolated_temp_db":
        visual_seed = seed_validation_cohort(
            trajectories,
            run_id=str(seeded.get("run_id") or ""),
            base_url=base_url,
            cohort_mode="current_db",
        )
    case_results = attach_visual_artifacts(
        evaluate_validation_seed(seeded),
        visual_mode=visual_mode,
        visual_seed=visual_seed,
    )
    return build_validation_report(seeded, case_results, visual_mode=visual_mode)


__all__ = [
    "DEFAULT_BASE_URL",
    "build_trajectory_catalog",
    "list_trajectory_summaries",
    "run_longitudinal_validation",
    "run_vertical_verification",
]
