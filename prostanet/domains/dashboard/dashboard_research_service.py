from prostanet.domains.dashboard.dashboard_cache_repository import (
    RESEARCH_CACHE_KEY,
    RESEARCH_TTL_SECONDS,
    get_cached_payload,
    set_cache_snapshot,
)
from prostanet.domains.research_intelligence.epidemiology_dashboard import (
    build_epidemiology_dashboard_payload,
)


def build_dashboard_research_payload():
    return build_epidemiology_dashboard_payload()


def get_dashboard_research_payload(use_cache=True):
    if use_cache:
        cached = get_cached_payload(RESEARCH_CACHE_KEY)
        if cached:
            return cached
    payload = build_dashboard_research_payload()
    if use_cache:
        set_cache_snapshot(RESEARCH_CACHE_KEY, payload, RESEARCH_TTL_SECONDS)
    return payload
