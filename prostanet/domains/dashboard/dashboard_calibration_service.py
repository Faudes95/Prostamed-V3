from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.scenario_harness import run_scenario_harness
from prostanet.domains.dashboard.dashboard_cache_repository import (
    CALIBRATION_CACHE_KEY,
    CALIBRATION_TTL_SECONDS,
    get_cached_payload,
    set_cache_snapshot,
)


def build_dashboard_calibration_payload():
    calibration = run_scenario_harness(ModuleRegistry())
    return {
        "scenario_harness": {
            "total_cases": calibration["total_cases"],
            "passed_cases": calibration["passed_cases"],
            "failed_cases": calibration["failed_cases"],
            "concordance_pct": calibration["concordance_pct"],
            "module_summary": calibration["module_summary"],
        }
    }


def get_dashboard_calibration_payload(use_cache=True):
    if use_cache:
        cached = get_cached_payload(CALIBRATION_CACHE_KEY)
        if cached:
            return cached
    payload = build_dashboard_calibration_payload()
    if use_cache:
        set_cache_snapshot(CALIBRATION_CACHE_KEY, payload, CALIBRATION_TTL_SECONDS)
    return payload

