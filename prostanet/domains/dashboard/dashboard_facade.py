from prostanet.domains.dashboard.dashboard_analytics_service import (
    build_analysis_dataset_payload,
    get_dashboard_analytics_payload,
)
from prostanet.domains.dashboard.dashboard_calibration_service import (
    get_dashboard_calibration_payload,
)
from prostanet.domains.dashboard.dashboard_research_service import (
    get_dashboard_research_payload,
)
from prostanet.domains.dashboard.dashboard_summary_service import (
    build_dashboard_summary_payload,
)


def get_dashboard_summary_payload():
    return build_dashboard_summary_payload()


def get_dashboard_analytics_bundle():
    return get_dashboard_analytics_payload(use_cache=True)


def get_dashboard_calibration_bundle():
    return get_dashboard_calibration_payload(use_cache=True)


def get_dashboard_research_bundle():
    return get_dashboard_research_payload(use_cache=True)


def get_analysis_dataset_bundle():
    return build_analysis_dataset_payload()
