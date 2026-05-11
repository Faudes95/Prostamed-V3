import tracking_db

from prostanet.domains.dashboard.dashboard_cache_repository import (
    ANALYTICS_CACHE_KEY,
    ANALYTICS_TTL_SECONDS,
    get_cached_payload,
    set_cache_snapshot,
)
from prostanet.domains.patient_tracking.cohort_analytics import (
    build_analysis_dataset_row,
    compute_patient_cohort_completeness,
    compute_patient_endpoint_readiness,
    compute_patient_research_readiness,
    summarize_cohort,
)
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state


def _reconciled_patient_snapshot(record):
    reconciliation = build_reconciled_state(record, record.get("latest_assessment"))
    return {
        "reconciled_state": reconciliation.get("reconciled_state") or "diagnostic_workup",
        "reconciled_management_track": reconciliation.get("reconciled_management_track")
        or "diagnostic_surveillance",
        "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
    }


def build_analysis_dataset_payload():
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
    patient_ids = [row["id"] for row in cursor.fetchall()]
    conn.close()

    analysis_rows = []
    enriched_records = []
    for patient_id in patient_ids:
        record = tracking_db.get_patient_full_record(patient_id)
        if not record:
            continue
        reconciliation = _reconciled_patient_snapshot(record)
        state = reconciliation["reconciled_state"]
        management_track = reconciliation["reconciled_management_track"]
        latest_signals = dict(record.get("latest_signal_snapshot") or {})
        latest_signals.update(reconciliation)
        record["reconciled_state"] = state
        record["reconciled_management_track"] = management_track
        record["latest_signal_snapshot"] = latest_signals
        analysis_rows.append(
            build_analysis_dataset_row(record, state, management_track, latest_signals)
        )
        enriched_records.append(record)

    summary = summarize_cohort(enriched_records)
    completeness_rows = [
        {
            "patient_uid": row["patient_uid"],
            "nss_hash_hint": row["nss_hash_hint"],
            "reconciled_state": row["reconciled_state"],
            **compute_patient_cohort_completeness(record, record["reconciled_state"]),
        }
        for row, record in zip(analysis_rows, enriched_records)
    ]
    readiness_rows = [
        {
            "patient_uid": row["patient_uid"],
            "nss_hash_hint": row["nss_hash_hint"],
            "reconciled_state": row["reconciled_state"],
            **compute_patient_research_readiness(record, record["reconciled_state"]),
        }
        for row, record in zip(analysis_rows, enriched_records)
    ]
    endpoint_rows = [
        {
            "patient_uid": row["patient_uid"],
            "nss_hash_hint": row["nss_hash_hint"],
            "reconciled_state": row["reconciled_state"],
            **compute_patient_endpoint_readiness(record, record["reconciled_state"]),
        }
        for row, record in zip(analysis_rows, enriched_records)
    ]
    return {
        "analysis_rows": analysis_rows,
        "cohort_completeness_rows": completeness_rows,
        "research_readiness_rows": readiness_rows,
        "endpoint_readiness_rows": endpoint_rows,
        "summary": summary,
    }


def build_dashboard_analytics_payload():
    analysis_payload = build_analysis_dataset_payload()
    summary = analysis_payload["summary"]
    return {
        "cohort_completeness": {
            "average_pct": summary["cohort_average_completeness_pct"],
            "publishable_ready_count": summary["publishable_ready_count"],
            "mexico_core_complete_count": summary["mexico_core_complete_count"],
            "document_verification_coverage_count": summary[
                "document_verification_coverage_count"
            ],
            "survival_status_complete_count": summary.get("survival_status_complete_count", 0),
            "structured_biopsy_session_count": summary.get(
                "structured_biopsy_session_count", 0
            ),
            "active_surveillance_operational_count": summary.get(
                "active_surveillance_operational_count", 0
            ),
            "skeletal_bone_health_count": summary.get("skeletal_bone_health_count", 0),
            "radiotherapy_detail_count": summary.get("radiotherapy_detail_count", 0),
        },
        "research_readiness": {
            "average_pct": summary["cohort_average_research_readiness_pct"],
            "research_ready_count": summary["research_ready_count"],
        },
        "endpoint_readiness": summary["endpoint_ready_distribution"],
        "risk_tool_stats": summary.get("risk_tool_stats", {}),
        "capra_distribution": summary.get("capra_distribution", {}),
        "damico_distribution": summary.get("damico_distribution", {}),
        "capra_s_distribution": summary.get("capra_s_distribution", {}),
        "mskcc_bcr_post_rp_stats": summary.get("mskcc_bcr_post_rp_stats", {}),
        "upgrade_stats": {
            "pathologic_upgrade_count": summary.get("pathologic_upgrade_count", 0),
            "genomic_upclassification_count": summary.get(
                "genomic_upclassification_count", 0
            ),
            "unfavorable_intermediate_behaving_like_high_risk_count": summary.get(
                "unfavorable_intermediate_behaving_like_high_risk_count", 0
            ),
        },
        "prognostic_modifier_stats": summary.get("prognostic_modifier_counts", {}),
        "backbone_alignment_stats": summary.get("backbone_alignment_stats", {}),
        "prognostic_followup_impact_count": summary.get("followup_impact_count", 0),
        "incomplete_prognostic_scores_count": summary.get(
            "incomplete_score_targets_count", 0
        ),
        "high_risk_impact_count": summary.get("high_risk_impact_count", 0),
        "analysis_dataset_size": len(analysis_payload["analysis_rows"]),
        "analysis_dataset_preview": analysis_payload["analysis_rows"][:5],
    }


def get_dashboard_analytics_payload(use_cache=True):
    if use_cache:
        cached = get_cached_payload(ANALYTICS_CACHE_KEY)
        if cached:
            return cached
    payload = build_dashboard_analytics_payload()
    if use_cache:
        set_cache_snapshot(ANALYTICS_CACHE_KEY, payload, ANALYTICS_TTL_SECONDS)
    return payload

