from __future__ import annotations


def build_patient_clinical_ledger_bundle(patient_record):
    patient_record = dict(patient_record or {})
    return {
        "available": bool(
            patient_record.get("patient_fact_lineage_events")
            or patient_record.get("decision_snapshot_history")
        ),
        "fact_lineage": list(patient_record.get("patient_fact_lineage_events") or [])[:25],
        "fact_conflicts": list(patient_record.get("patient_fact_conflicts") or [])[:10],
        "recent_decision_snapshots": list(patient_record.get("decision_snapshot_history") or [])[:10],
        "recent_state_transitions": list(patient_record.get("state_transition_history") or [])[:10],
        "recent_missing_input_requests": list(patient_record.get("missing_input_history") or [])[:10],
    }


def attach_patient_clinical_ledger_histories(patient_record):
    from prostanet.domains.clinical_validation.repository import get_patient_ledger_histories

    patient_record = dict(patient_record or {})
    identity_id = (patient_record.get("identity") or {}).get("id")
    if identity_id is None:
        return patient_record
    patient_record.update(get_patient_ledger_histories(int(identity_id)))
    patient_record["clinical_ledger_bundle"] = {
        **dict(patient_record.get("clinical_ledger_bundle") or {}),
        "available": True,
        "recent_decision_snapshots": list(patient_record.get("decision_snapshot_history") or [])[:10],
        "recent_state_transitions": list(patient_record.get("state_transition_history") or [])[:10],
        "recent_missing_input_requests": list(patient_record.get("missing_input_history") or [])[:10],
        "validation_annotations": list(patient_record.get("validation_annotations") or [])[:10],
    }
    return patient_record
