from __future__ import annotations

from typing import Any

import tracking_db

from prostanet.domains.research_intelligence.comparative_effectiveness import (
    run_propensity_analysis,
)
from prostanet.domains.research_intelligence.consent_governance import (
    build_consent_dashboard_payload,
)
from prostanet.domains.research_intelligence.dynamic_cohorting import (
    list_dynamic_cohort_payload,
)
from prostanet.domains.research_intelligence.institutional_benchmarking import (
    build_institutional_benchmark_payload,
)
from prostanet.domains.research_intelligence.multivariate_analysis import (
    build_cox_payload,
    build_logistic_payload,
)
from prostanet.domains.research_intelligence.operational_outcomes import (
    build_operational_outcomes_payload,
)
from prostanet.domains.research_intelligence.quality_indicators import (
    build_quality_indicator_payload,
)
from prostanet.domains.research_intelligence.research_exports import (
    build_cdisc_mapping_payload,
    build_csv_export_payload,
    build_redcap_export_payload,
)
from prostanet.domains.patient_tracking.psma_imaging.analytics import (
    build_psma_imaging_analytics,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.analytics import (
    build_laboratory_dashboard_metrics,
)
from prostanet.domains.research_intelligence.survival_registry import (
    build_survival_registry_payload,
)
from prostanet.domains.clinical_validation.repository import (
    get_latest_validation_summary,
)


def _all_records() -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
    patient_ids = [int(row["id"]) for row in cursor.fetchall()]
    conn.close()
    records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
    return [record for record in records if record]


def build_epidemiology_dashboard_payload() -> dict[str, Any]:
    records = _all_records()
    dynamic_cohorts = list_dynamic_cohort_payload()
    default_cohort_id = dynamic_cohorts[0]["id"] if dynamic_cohorts else None
    survival = {
        "os": build_survival_registry_payload(endpoint="OS"),
        "rpfs": build_survival_registry_payload(endpoint="rPFS"),
        "mfs": build_survival_registry_payload(endpoint="MFS"),
    }
    multivariate = {
        "cox": build_cox_payload(endpoint="OS"),
        "logistic": build_logistic_payload(outcome="molecular_report_available"),
    }
    comparative = (
        run_propensity_analysis(
            cohort_id=int(default_cohort_id),
            treatment_field="metastatic",
            treatment_value="1",
            control_value="0",
            outcome_field="survival_os_event",
        )
        if default_cohort_id
        else {"eligible": False, "reason": "No hay cohortes dinámicas disponibles."}
    )
    operational = build_operational_outcomes_payload(records)
    quality = build_quality_indicator_payload(records)
    psma_imaging = build_psma_imaging_analytics(records)
    laboratory_intelligence = build_laboratory_dashboard_metrics(records)
    benchmarking = build_institutional_benchmark_payload(records)
    exports = {
        "csv": build_csv_export_payload(),
        "redcap": build_redcap_export_payload(),
        "cdisc": build_cdisc_mapping_payload(),
    }
    consent = build_consent_dashboard_payload(records)
    readiness = {
        "research_ready_patients": sum(1 for record in records if record.get("latest_signal_snapshot")),
        "dynamic_cohort_count": len(dynamic_cohorts),
        "exportable_records": exports["csv"].get("record_count", 0),
        "consent_coverage_pct": consent.get("coverage_pct", 0.0),
    }
    validation = get_latest_validation_summary()
    crpc_copilot = tracking_db.get_crpc_copilot_dashboard_summary()
    post_rp_salvage_copilot = tracking_db.get_post_rp_salvage_dashboard_summary()
    mhspc_copilot = tracking_db.get_mhspc_copilot_dashboard_summary()
    diagnostic_biopsy_copilot = tracking_db.get_diagnostic_biopsy_dashboard_summary()
    localized_surveillance_copilot = tracking_db.get_localized_surveillance_dashboard_summary()
    post_rt_salvage_copilot = tracking_db.get_post_rt_salvage_dashboard_summary()
    return {
        "survival": survival,
        "multivariate": multivariate,
        "comparative_effectiveness": comparative,
        "operational_outcomes": operational,
        "quality_indicators": quality,
        "psma_imaging": psma_imaging,
        "laboratory_intelligence": laboratory_intelligence,
        "benchmarking": benchmarking,
        "dynamic_cohorts": dynamic_cohorts,
        "exports": {
            "csv_manifest": exports["csv"].get("manifest"),
            "redcap_manifest": exports["redcap"].get("manifest"),
            "cdisc_manifest": exports["cdisc"].get("manifest"),
        },
        "consent_governance": consent,
        "research_readiness": readiness,
        "longitudinal_validation": validation,
        "crpc_copilot": crpc_copilot,
        "post_rp_salvage_copilot": post_rp_salvage_copilot,
        "mhspc_copilot": mhspc_copilot,
        "diagnostic_biopsy_copilot": diagnostic_biopsy_copilot,
        "localized_surveillance_copilot": localized_surveillance_copilot,
        "post_rt_salvage_copilot": post_rt_salvage_copilot,
    }
