import json

import tracking_db

from prostanet.domains.dashboard.dashboard_cache_repository import (
    ANALYTICS_CACHE_KEY,
    CALIBRATION_CACHE_KEY,
    cache_status,
)


ADVANCED_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}


def _truthy(value):
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


def build_dashboard_summary_payload():
    conn = tracking_db._connect()
    cursor = conn.cursor()

    stats = {}

    cursor.execute("SELECT COUNT(*) as n FROM patient_identity")
    stats["total_patients"] = cursor.fetchone()["n"]

    cursor.execute(
        """
        SELECT COALESCE(cb.metastasis_site, 'M0') as site, COUNT(*) as n
        FROM patient_identity pi
        LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
        GROUP BY site
        """
    )
    stats["metastasis_distribution"] = {row["site"]: row["n"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT COALESCE(cb.volume_disease, 'No registrado') as vol, COUNT(*) as n
        FROM patient_identity pi
        LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
        GROUP BY vol
        """
    )
    stats["volume_distribution"] = {row["vol"]: row["n"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT COALESCE(cb.ecog_score, 0) as ecog, COUNT(*) as n
        FROM patient_identity pi
        LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
        GROUP BY ecog
        """
    )
    stats["ecog_distribution"] = {str(row["ecog"]): row["n"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT CAST(cb.baseline_psa AS REAL) AS baseline_psa
        FROM clinical_baseline cb
        WHERE NULLIF(TRIM(COALESCE(cb.baseline_psa, '')), '') IS NOT NULL
          AND CAST(cb.baseline_psa AS REAL) > 0
        """
    )
    stats["psa_values"] = [row["baseline_psa"] for row in cursor.fetchall()]

    cursor.execute(
        """
        SELECT strftime('%Y-%m', pi.diagnosis_date) as month, COUNT(*) as n
        FROM patient_identity pi
        WHERE pi.diagnosis_date IS NOT NULL
        GROUP BY month ORDER BY month
        """
    )
    stats["enrollment_by_month"] = {row["month"]: row["n"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT alert_type, COUNT(*) as n
        FROM smart_alerts
        WHERE acknowledged = 0 AND COALESCE(active, 1) = 1
        GROUP BY alert_type
        """
    )
    stats["active_alerts_by_type"] = {row["alert_type"]: row["n"] for row in cursor.fetchall()}

    cursor.execute(
        "SELECT COUNT(*) as n FROM smart_alerts WHERE acknowledged = 0 AND COALESCE(active, 1) = 1"
    )
    stats["total_active_alerts"] = cursor.fetchone()["n"]

    simple_tables = {
        "demographics_count": "patient_demographics",
        "genomics_count": "genomic_profile",
        "biopsies_count": "biopsy_details",
        "imaging_count": "imaging_studies",
        "pros_count": "patient_pros",
        "surgeries_count": "surgical_details",
        "total_followups": "follow_up_visits",
    }
    for key, table_name in simple_tables.items():
        cursor.execute(f"SELECT COUNT(*) as n FROM {table_name}")
        stats[key] = cursor.fetchone()["n"]

    cursor.execute("SELECT COUNT(*) as n FROM active_surveillance WHERE exit_date IS NULL")
    stats["active_surveillance_count"] = cursor.fetchone()["n"]

    cursor.execute("PRAGMA table_info(clinical_assessments)")
    assessment_columns = {row["name"] for row in cursor.fetchall()}
    input_snapshot_column = (
        "input_snapshot_json"
        if "input_snapshot_json" in assessment_columns
        else "input_snapshot"
    )

    cursor.execute(
        f"""
        SELECT ca.state, ca.{input_snapshot_column} AS input_snapshot_payload
        FROM clinical_assessments ca
        INNER JOIN prior_clinical_history ph ON ph.latest_assessment_id = ca.id
        """
    )
    assessment_rows = cursor.fetchall()
    stats["latest_assessment_count"] = len(assessment_rows)

    biomarker_complete = 0
    pros_baseline = 0
    ddi_reviewed = 0
    cv_documented = 0
    lft_documented = 0
    psma_documented = 0
    dxa_documented = 0
    bone_protection = 0
    salvage_documented = 0
    line_context_documented = 0
    molecular_reported = 0

    for row in assessment_rows:
        payload = json.loads(row["input_snapshot_payload"] or "{}")
        state = row["state"]
        if (
            state in ADVANCED_STATES
            and payload.get("hrr_gene") not in (None, "", "Desconocido")
            and payload.get("biomarker_source") not in (None, "", "Desconocida")
        ):
            biomarker_complete += 1
        if any(
            payload.get(field) not in (None, "")
            for field in [
                "baseline_qol",
                "baseline_urinary_qol",
                "baseline_sexual_qol",
                "baseline_bowel_qol",
            ]
        ):
            pros_baseline += 1
        if _truthy(payload.get("drug_interaction_reviewed")):
            ddi_reviewed += 1
        if _truthy(payload.get("cv_risk_documented")):
            cv_documented += 1
        if payload.get("child_pugh_score") or _truthy(payload.get("hepatic_risk_factors")):
            lft_documented += 1
        if _truthy(payload.get("psma_positive")) and not _truthy(
            payload.get("psma_negative_dominant_lesions")
        ):
            psma_documented += 1
        if state in MHSPC_STATES and _truthy(payload.get("dxa_baseline_done")):
            dxa_documented += 1
        if state in MHSPC_STATES and (
            _truthy(payload.get("bone_protection_started"))
            or _truthy(payload.get("calcium_vitd_started"))
        ):
            bone_protection += 1
        if state in {"recurrence_bcr", "post_prostatectomy"} and (
            payload.get("salvage_local_feasible") not in (None, "")
            or payload.get("eligible_pelvic_therapy") not in (None, "")
        ):
            salvage_documented += 1
        if state == "m1_crpc" and payload.get("mcrpc_line_context"):
            line_context_documented += 1
        if payload.get("molecular_report_date") or payload.get("molecular_assay_date"):
            molecular_reported += 1

    stats["biomarker_complete_count"] = biomarker_complete
    stats["pros_baseline_count"] = pros_baseline
    stats["ddi_reviewed_count"] = ddi_reviewed
    stats["cv_documented_count"] = cv_documented
    stats["lft_documented_count"] = lft_documented
    stats["psma_eligibility_count"] = psma_documented
    stats["dxa_documented_count"] = dxa_documented
    stats["bone_protection_count"] = bone_protection
    stats["salvage_documented_count"] = salvage_documented
    stats["mcrpc_line_context_count"] = line_context_documented
    stats["molecular_report_count"] = molecular_reported

    cursor.execute(
        f"""
        SELECT COUNT(DISTINCT ph.patient_id) as n
        FROM prior_clinical_history ph
        INNER JOIN treatment_history th ON th.patient_id = ph.patient_id
        WHERE ph.current_state IN ({",".join(["?"] * len(MHSPC_STATES))})
          AND th.drug_scheme IS NOT NULL
          AND th.drug_scheme != ''
          AND th.drug_scheme != 'ADT_MONO'
        """,
        tuple(MHSPC_STATES),
    )
    stats["mhspc_combination_adherence_count"] = cursor.fetchone()["n"]
    conn.close()

    stats["analytics_cache"] = cache_status(ANALYTICS_CACHE_KEY)
    stats["calibration_cache"] = cache_status(CALIBRATION_CACHE_KEY)
    stats["analytics_ready"] = stats["analytics_cache"]["fresh"]
    stats["calibration_ready"] = stats["calibration_cache"]["fresh"]
    return stats

