from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.laboratory_intelligence.service import (
    build_laboratory_intelligence_profile,
)


def build_laboratory_dashboard_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = [build_laboratory_intelligence_profile(record) for record in records if record]
    total = len(profiles)
    if total == 0:
        return {
            "record_count": 0,
            "longitudinal_coverage_pct": 0.0,
            "alerts_active_count": 0,
            "castration_documented_count": 0,
            "hepatic_panel_count": 0,
            "renal_panel_count": 0,
        }
    return {
        "record_count": total,
        "longitudinal_coverage_pct": round(
            (sum(1 for profile in profiles if profile.get("available")) / total) * 100,
            1,
        ),
        "alerts_active_count": sum(len(profile.get("active_alerts") or []) for profile in profiles),
        "castration_documented_count": sum(1 for profile in profiles if (profile.get("latest_values") or {}).get("testosterone") not in (None, "")),
        "hepatic_panel_count": sum(1 for profile in profiles if (profile.get("coverage") or {}).get("has_hepatic_panel")),
        "renal_panel_count": sum(1 for profile in profiles if (profile.get("coverage") or {}).get("has_renal_panel")),
    }
