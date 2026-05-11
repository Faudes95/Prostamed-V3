from __future__ import annotations

from collections import Counter
from typing import Any


REQUIRED_SCENARIO_IDS = {
    "post_prostatectomy_persistent_psa",
    "adt_progression_non_castrate",
    "m1_crpc_abiraterone_hepatic_safety",
    "active_surveillance_confirmatory_overdue",
    "bcr_post_rp_disseminated_psma",
}


def build_validation_report(seed_payload: dict[str, Any], case_results: list[dict[str, Any]], *, visual_mode: str = "playwright_real") -> dict[str, Any]:
    total = len(case_results)
    passed = sum(1 for item in case_results if item.get("case_status") == "passed")
    failed = total - passed
    critical_failures = sum(1 for item in case_results if item.get("critical_failure"))
    ui_contradictions = sum(len(item.get("ui_contradictions") or []) for item in case_results)
    prompt_accuracy = round(
        100 * sum(float(item.get("missing_input_prompt_accuracy") or 0.0) for item in case_results) / max(total, 1),
        1,
    )
    guideline_concordance = round(
        sum(float(item.get("guideline_concordance_pct") or 0.0) for item in case_results) / max(total, 1),
        1,
    )
    data_accumulation = round(
        100 * sum(1 for item in case_results if item.get("data_accumulation_complete")) / max(total, 1),
        1,
    )
    failing_families = Counter(
        item.get("scenario_family")
        for item in case_results
        if item.get("case_status") != "passed"
    )
    report = {
        "run_id": seed_payload.get("run_id"),
        "cohort_mode": seed_payload.get("cohort_mode", "isolated_temp_db"),
        "base_url": seed_payload.get("base_url", ""),
        "generated_at": seed_payload.get("generated_at", ""),
        "visual_mode": visual_mode,
        "summary": {
            "total_trajectories": total,
            "passed": passed,
            "failed": failed,
            "critical_failures": critical_failures,
            "ui_contradictions": ui_contradictions,
            "missing_input_prompt_accuracy": prompt_accuracy,
            "guideline_concordance_pct": guideline_concordance,
            "data_accumulation_completeness_pct": data_accumulation,
            "top_failing_scenario_families": failing_families.most_common(5),
            "release_gate": {
                "hard_critical_target_pct": 100.0,
                "global_concordance_target_pct": 98.0,
                "ui_contradictions_target": 0,
            },
        },
        "required_cases": [item for item in case_results if item.get("scenario_id") in REQUIRED_SCENARIO_IDS],
        "cases": case_results,
    }
    return report


__all__ = ["build_validation_report"]
