from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.risk_tools import (
    build_risk_tools_panel,
    summarize_risk_tools_for_cohort,
)
from prostanet.domains.patient_tracking.prognostic_impact import summarize_prognostic_impact_for_cohort
from prostanet.domains.patient_tracking.palliative_longitudinal import PALLIATIVE_TRACKS


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

_MEXICO_CORE_FIELDS = (
    "estado_residencia",
    "seguridad_social",
    "escolaridad",
    "actividad_fisica",
    "diabetes_mellitus",
    "hipertension",
)


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _rate(present: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((present / total) * 100.0, 1)


def _tone_from_pct(value: float) -> str:
    if value >= 80:
        return "good"
    if value >= 55:
        return "warning"
    return "danger"


def compute_patient_cohort_completeness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    demographics = patient.get("demographics") or {}
    genomics = patient.get("genomics") or {}
    followups = patient.get("follow_ups") or []
    biomarker_longitudinal = patient.get("biomarker_longitudinal") or []
    verified_documents = [
        item for item in (patient.get("source_documents") or [])
        if str(item.get("verification_status") or "") == "verified"
    ]
    structured_biopsy_sessions = patient.get("structured_biopsy_sessions") or []
    active_surveillance_protocol = patient.get("active_surveillance_protocol") or {}
    survival_status = patient.get("survival_status_detail") or {}
    skeletal_profile = patient.get("skeletal_event_profile") or {}
    radiotherapy_courses = patient.get("radiotherapy_courses_detailed") or []

    sections = {
        "identity": _rate(sum(1 for field in ("nss", "full_name", "dob", "diagnosis_date") if _is_present(identity.get(field))), 4),
        "mexico_core": _rate(sum(1 for field in _MEXICO_CORE_FIELDS if _is_present(demographics.get(field))), len(_MEXICO_CORE_FIELDS)),
        "pathology": 100.0 if patient.get("biopsies") or structured_biopsy_sessions else 0.0,
        "imaging": 100.0 if patient.get("imaging") else 0.0,
        "treatment": 100.0 if patient.get("treatments") or patient.get("surgery") or patient.get("radiation") or radiotherapy_courses else 0.0,
        "follow_up": 100.0 if followups else 0.0,
        "biomarkers": _rate(len({item.get("biomarker_type") for item in biomarker_longitudinal if item.get("biomarker_type")}), 8),
        "pros": 100.0 if patient.get("pros") else 0.0,
        "provenance": 100.0 if patient.get("data_provenance") else 0.0,
        "documents": _rate(len(verified_documents), max(len(patient.get("source_documents") or []), 1)),
        "genomics": 100.0 if any(_is_present(genomics.get(field)) for field in ("hrr_overall", "brca2_status", "msi_status", "decipher_risk")) else 0.0,
        "survival_status": 100.0 if _is_present(survival_status.get("vital_status")) and _is_present(survival_status.get("last_contact_date")) else 0.0,
        "structured_biopsy": 100.0 if structured_biopsy_sessions else 0.0,
        "active_surveillance_operational": 100.0 if active_surveillance_protocol.get("schedule") or active_surveillance_protocol.get("reclassification_triggers") else 0.0,
        "skeletal_bone_health": 100.0 if skeletal_profile.get("sre_events") or patient.get("bone_modifying_agent_courses") or patient.get("bone_health_snapshots") else 0.0,
        "radiotherapy_detail": 100.0 if radiotherapy_courses else 0.0,
    }
    overall_pct = round(sum(sections.values()) / len(sections), 1)
    missing_sections = [key for key, value in sections.items() if value < 50.0]
    return {
        "overall_pct": overall_pct,
        "tone": _tone_from_pct(overall_pct),
        "sections": sections,
        "missing_sections": missing_sections,
        "verified_documents": len(verified_documents),
        "followup_density": len(followups),
        "state": state,
    }


def compute_patient_endpoint_readiness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    followups = patient.get("follow_ups") or []
    treatments = patient.get("treatments") or []
    biopsies = patient.get("biopsies") or []
    imaging = patient.get("imaging") or []
    biomarker_longitudinal = patient.get("biomarker_longitudinal") or []
    latest_followup = _latest(followups, "visit_date")
    survival_status = patient.get("survival_status_detail") or {}
    active_surveillance_protocol = patient.get("active_surveillance_protocol") or {}
    structured_biopsy_sessions = patient.get("structured_biopsy_sessions") or []
    skeletal_events = patient.get("skeletal_events") or []

    endpoints = {
        "time_to_histology": bool(identity.get("diagnosis_date") and biopsies),
        "time_to_treatment": bool(identity.get("diagnosis_date") and (treatments or patient.get("surgery") or patient.get("radiation"))),
        "active_surveillance_exit": bool(patient.get("active_surveillance")) or bool(active_surveillance_protocol.get("exit_reason")),
        "biochemical_recurrence": bool(patient.get("bcr")),
        "time_to_adt": any("adt" in str(item.get("drug_scheme", "")).lower() for item in treatments) or "adt" in str(latest_followup.get("current_treatment", "")).lower(),
        "time_to_crpc": state in {"m0_crpc", "m1_crpc"},
        "line_duration": any(_is_present(item.get("start_date")) and _is_present(item.get("end_date")) for item in treatments) or len(treatments) > 0,
        "psa_kinetics": sum(1 for item in biomarker_longitudinal if item.get("biomarker_type") == "PSA") >= 2 or sum(1 for item in followups if _is_present(item.get("psa_current"))) >= 2,
        "radiographic_progression": bool(imaging and latest_followup.get("disease_status")),
        # ── Endpoints de supervivencia (Fase 6.1) ──
        "overall_survival": bool(identity.get("diagnosis_date")) and (_is_present(patient.get("vital_status")) or _is_present(survival_status.get("vital_status"))),
        "rpfs": bool(treatments) and state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m0_crpc", "m1_crpc"},
        "mfs": bool(identity.get("diagnosis_date")) and state in {"localized_initial", "post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage", "m0_crpc"},
        "ttr": bool(patient.get("bcr")) and state in {"localized_initial", "post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"},
        "ttsre": bool(skeletal_events) or (state in {"mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m1_crpc"} and bool(imaging)),
        # ── Vigilancia activa KPIs (Fase 6.1) ──
        "as_conversion_rate": bool(active_surveillance_protocol.get("exit_reason") or (patient.get("active_surveillance") and patient.get("active_surveillance", {}).get("exit_reason") if isinstance(patient.get("active_surveillance"), dict) else False)),
        "as_time_on_protocol": bool((patient.get("active_surveillance") or active_surveillance_protocol) and identity.get("diagnosis_date")),
        "as_confirmatory_biopsy": bool(active_surveillance_protocol.get("confirmatory_biopsy_done") or active_surveillance_protocol.get("confirmatory_biopsy_due")),
        # ── Biopsia estructurada (Fase 6.1) ──
        "structured_biopsy_available": any(isinstance(b, dict) and b.get("systematic_cores") for b in biopsies) if biopsies else bool(structured_biopsy_sessions),
        "radiotherapy_detail": bool(patient.get("radiotherapy_courses_detailed")),
    }
    ready_count = sum(1 for value in endpoints.values() if value)
    return {
        "ready_count": ready_count,
        "total": len(endpoints),
        "overall_pct": _rate(ready_count, len(endpoints)),
        "items": endpoints,
    }


def compute_patient_research_readiness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    completeness = compute_patient_cohort_completeness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    critical_missing = latest_signal_snapshot.get("critical_missing") or []
    score = round((completeness["overall_pct"] * 0.65) + (endpoints["overall_pct"] * 0.35), 1)
    status = "ready" if score >= 80 and not critical_missing else "partial" if score >= 55 else "not_ready"
    return {
        "score": score,
        "status": status,
        "critical_missing": critical_missing[:5],
        "missing_sections": completeness["missing_sections"],
        "endpoint_gaps": [key for key, value in endpoints["items"].items() if not value],
    }


def build_patient_kpis(
    patient: dict[str, Any],
    *,
    state: str,
    management_track: str,
    agenda_board: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    completeness = compute_patient_cohort_completeness(patient, state)
    research = compute_patient_research_readiness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)

    active_items = agenda_board.get("active_items", agenda_board.get("items", [])) or []
    due_now = sum(1 for item in active_items if item.get("status") in {"due", "overdue"})
    overdue = sum(1 for item in active_items if item.get("status") == "overdue")
    protocol_pct = _rate(sum(1 for item in active_items if item.get("status") not in {"overdue", "blocked"}), max(len(active_items), 1))

    if state in DIAGNOSTIC_STATES:
        control_label = "Completitud diagnóstica"
        control_value = f"{max(0, 100 - (len(signals.get('critical_missing') or []) * 20))}%"
        control_detail = "MRI, trigger de biopsia y PSA/PSAD determinan si el diagnóstico ya puede cerrarse."
    elif state == "localized_initial":
        control_label = "Ruta localizada"
        control_value = str(_latest(patient.get("biopsies") or [], "biopsy_date").get("isup_grade") or "ISUP N/D")
        control_detail = "Se prioriza estabilidad histológica, MRI y PROs para sostener o cambiar estrategia local."
    elif state in POSTLOCAL_STATES:
        control_label = "Control bioquímico"
        psa_value = latest_followup.get("psa_current")
        control_value = f"PSA {psa_value}" if _is_present(psa_value) else "PSA pendiente"
        control_detail = "PSA ultrasensible y PSADT definen ventana de rescate o intensificación."
    else:
        control_label = "Control de enfermedad"
        testosterone = latest_followup.get("testosterone_current")
        control_value = (
            f"Testosterona {testosterone} ng/dL"
            if _is_present(testosterone)
            else "Castración no documentada"
        )
        control_detail = "La secuencia sistémica depende de castración, biomarcadores y respuesta longitudinal."

    safety_alerts = len(signals.get("active_safety") or [])
    safety_detail = f"{safety_alerts} alerta(s) activa(s)" if safety_alerts else "Sin alertas estructuradas activas"
    if management_track in {"on_arpi", "systemic_surveillance", "palliative_overlay"} | PALLIATIVE_TRACKS:
        safety_detail += " · bundle ADT / soporte concurrente"

    return [
        {
            "label": control_label,
            "value": control_value,
            "detail": control_detail,
            "tone": "good" if not signals.get("state_conflict_flag") else "warning",
        },
        {
            "label": "Adherencia a protocolo",
            "value": f"{protocol_pct:.1f}%",
            "detail": f"{due_now} pendiente(s) activas, {overdue} vencida(s).",
            "tone": _tone_from_pct(protocol_pct if not overdue else max(protocol_pct - 20, 0)),
        },
        {
            "label": "Calidad de datos",
            "value": f"{completeness['overall_pct']:.1f}%",
            "detail": "Patología, imagen, follow-up, PROs, biomarcadores y provenance estructurados.",
            "tone": completeness["tone"],
        },
        {
            "label": "Seguridad / soporte",
            "value": safety_detail,
            "detail": "Resume riesgo activo, salud ósea, soporte y toxicidad relevante para la decisión.",
            "tone": "warning" if safety_alerts else "good",
        },
        {
            "label": "Research readiness",
            "value": f"{research['score']:.1f}%",
            "detail": f"Endpoint readiness {endpoints['overall_pct']:.1f}% · cohort core {completeness['overall_pct']:.1f}%",
            "tone": _tone_from_pct(research["score"]),
        },
    ]


def build_analysis_dataset_row(patient: dict[str, Any], state: str, management_track: str, signals: dict[str, Any]) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    latest_biopsy = _latest(patient.get("biopsies") or [], "biopsy_date")
    latest_imaging = _latest(patient.get("imaging") or [], "study_date")
    psma_profile = patient.get("psma_structured_profile") or {}
    latest_genomic = patient.get("genomics") or {}
    completeness = compute_patient_cohort_completeness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)
    risk_bundle = build_risk_tools_panel(
        patient=patient,
        state=state,
        raw_assessment=patient.get("latest_assessment") or {},
        display_assessment={},
    )
    return {
        "patient_id": identity.get("id"),
        "patient_uid": f"PT-{identity.get('id', '')}",
        "nss_hash_hint": str(identity.get("nss", ""))[-4:],
        "age_at_diagnosis": _safe_float(patient.get("demographics", {}).get("age_at_diagnosis")) or _safe_float(identity.get("age")),
        "diagnosis_date": identity.get("diagnosis_date"),
        "reconciled_state": state,
        "management_track": management_track,
        "baseline_psa": _safe_float((patient.get("baseline") or {}).get("baseline_psa")),
        "ecog_score": _safe_float((patient.get("baseline") or {}).get("ecog_score")),
        "metastatic": 0 if str((patient.get("baseline") or {}).get("metastasis_site") or "M0") == "M0" else 1,
        "high_volume": 1 if str((patient.get("baseline") or {}).get("volume_disease") or "").lower() in {"high", "alto", "high volume"} else 0,
        "latest_psa": latest_followup.get("psa_current"),
        "latest_testosterone": latest_followup.get("testosterone_current"),
        "latest_biopsy_isup": latest_biopsy.get("isup_grade"),
        "latest_pirads": latest_imaging.get("pirads_score"),
        "latest_imaging_type": latest_imaging.get("study_type"),
        "psma_radioligand": psma_profile.get("psma_radioligand"),
        "psma_rads_score": psma_profile.get("psma_rads_score"),
        "psma_uptake_pattern": psma_profile.get("psma_uptake_pattern"),
        "psma_structured_complete": bool(psma_profile.get("structured_complete")),
        "psma_upstaged_vs_conventional": bool(psma_profile.get("psma_upstaged_vs_conventional")),
        "psma_management_changed": bool(psma_profile.get("psma_management_changed")),
        "current_treatment": latest_followup.get("current_treatment"),
        "current_regimen_code": _latest(patient.get("treatments") or [], "start_date").get("drug_scheme"),
        "line_of_therapy": _latest(patient.get("treatments") or [], "start_date").get("line_of_therapy"),
        "hrr_status": latest_genomic.get("hrr_overall"),
        "brca2_status": latest_genomic.get("brca2_status"),
        "msi_status": latest_genomic.get("msi_status"),
        "molecular_report_available": bool(latest_genomic.get("test_type") or patient.get("genomic_reports")),
        "as_protocol_active": bool(patient.get("active_surveillance_protocol")),
        "risk_tools": {
            item.get("tool_key"): {
                "status": item.get("status"),
                "fidelity": item.get("fidelity"),
                "primary_result": item.get("primary_result"),
            }
            for item in (risk_bundle.get("cards") or [])
            if item.get("tool_key")
        },
        "pathologic_upgrade": bool((risk_bundle.get("upgrade_panel") or {}).get("pathologic_upgrade", {}).get("active")),
        "genomic_upclassification": bool((risk_bundle.get("upgrade_panel") or {}).get("genomic_upclassification", {}).get("active")),
        "unfavorable_intermediate_behaving_like_high_risk": bool((risk_bundle.get("upgrade_panel") or {}).get("unfavorable_intermediate_behaving_like_high_risk", {}).get("active")),
        "pros_available": bool(patient.get("pros")),
        "followup_count": len(patient.get("follow_ups") or []),
        "verified_document_count": completeness["verified_documents"],
        "cohort_completeness_pct": completeness["overall_pct"],
        "endpoint_readiness_pct": endpoints["overall_pct"],
        "state_conflict_flag": bool(signals.get("state_conflict_flag")),
        "prognostic_modifiers": [item.get("modifier_key") for item in (signals.get("prognostic_modifiers") or []) if item.get("modifier_key")],
        "backbone_alignment_status": str((signals.get("backbone_alignment") or {}).get("alignment_status") or "unknown"),
        "prognostic_followup_adjusted": bool(signals.get("cadence_adjusted_by")),
        "prognostic_capture_target_count": len(signals.get("prognostic_capture_targets") or []),
        "survival_os_event": 1 if str(patient.get("vital_status") or "").lower() == "dead" else 0,
        "survival_os_months": _safe_float(((signals.get("trial_endpoints") or {}).get("OS") or {}).get("duration_months")),
    }


def summarize_cohort(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "publishable_ready_count": 0,
            "research_ready_count": 0,
            "mexico_core_complete_count": 0,
            "document_verification_coverage_count": 0,
            "endpoint_ready_distribution": {},
            "cohort_average_completeness_pct": 0.0,
            "cohort_average_research_readiness_pct": 0.0,
            "risk_tool_stats": {},
            "capra_distribution": {},
            "damico_distribution": {},
            "capra_s_distribution": {},
            "mskcc_bcr_post_rp_stats": {},
            "pathologic_upgrade_count": 0,
            "genomic_upclassification_count": 0,
            "unfavorable_intermediate_behaving_like_high_risk_count": 0,
            "survival_status_complete_count": 0,
            "structured_biopsy_session_count": 0,
            "active_surveillance_operational_count": 0,
            "skeletal_bone_health_count": 0,
            "radiotherapy_detail_count": 0,
        }

    completeness_values = []
    readiness_values = []
    publishable_ready = 0
    research_ready = 0
    mexico_core = 0
    document_ready = 0
    endpoint_distribution: dict[str, int] = {}
    survival_status_complete = 0
    structured_biopsy_count = 0
    active_surveillance_operational_count = 0
    skeletal_bone_health_count = 0
    radiotherapy_detail_count = 0

    for record in records:
        state = str(record.get("reconciled_state") or record.get("latest_assessment", {}).get("state") or record.get("prior_history", {}).get("current_state") or "diagnostic_workup")
        completeness = compute_patient_cohort_completeness(record, state)
        readiness = compute_patient_research_readiness(record, state)
        endpoints = compute_patient_endpoint_readiness(record, state)
        completeness_values.append(completeness["overall_pct"])
        readiness_values.append(readiness["score"])
        if completeness["overall_pct"] >= 80 and endpoints["overall_pct"] >= 60:
            publishable_ready += 1
        if readiness["status"] != "not_ready":
            research_ready += 1
        if completeness["sections"]["mexico_core"] >= 80:
            mexico_core += 1
        if completeness["verified_documents"] > 0:
            document_ready += 1
        survival_status_complete += int(completeness["sections"].get("survival_status", 0) >= 100)
        structured_biopsy_count += int(completeness["sections"].get("structured_biopsy", 0) >= 100)
        active_surveillance_operational_count += int(completeness["sections"].get("active_surveillance_operational", 0) >= 100)
        skeletal_bone_health_count += int(completeness["sections"].get("skeletal_bone_health", 0) >= 100)
        radiotherapy_detail_count += int(completeness["sections"].get("radiotherapy_detail", 0) >= 100)
        for key, value in endpoints["items"].items():
            endpoint_distribution.setdefault(key, 0)
            if value:
                endpoint_distribution[key] += 1

    risk_stats = summarize_risk_tools_for_cohort(records)
    prognostic_stats = summarize_prognostic_impact_for_cohort(records)

    return {
        "publishable_ready_count": publishable_ready,
        "research_ready_count": research_ready,
        "mexico_core_complete_count": mexico_core,
        "document_verification_coverage_count": document_ready,
        "endpoint_ready_distribution": endpoint_distribution,
        "cohort_average_completeness_pct": round(sum(completeness_values) / total, 1),
        "cohort_average_research_readiness_pct": round(sum(readiness_values) / total, 1),
        "risk_tool_stats": risk_stats.get("tool_status", {}),
        "capra_distribution": risk_stats.get("capra_distribution", {}),
        "damico_distribution": risk_stats.get("damico_distribution", {}),
        "capra_s_distribution": risk_stats.get("capra_s_distribution", {}),
        "mskcc_bcr_post_rp_stats": risk_stats.get("mskcc_bcr_post_rp_stats", {}),
        "pathologic_upgrade_count": risk_stats.get("pathologic_upgrade_count", 0),
        "genomic_upclassification_count": risk_stats.get("genomic_upclassification_count", 0),
        "unfavorable_intermediate_behaving_like_high_risk_count": risk_stats.get("unfavorable_intermediate_behaving_like_high_risk_count", 0),
        "survival_status_complete_count": survival_status_complete,
        "structured_biopsy_session_count": structured_biopsy_count,
        "active_surveillance_operational_count": active_surveillance_operational_count,
        "skeletal_bone_health_count": skeletal_bone_health_count,
        "radiotherapy_detail_count": radiotherapy_detail_count,
        "prognostic_modifier_counts": prognostic_stats.get("modifier_counts", {}),
        "backbone_alignment_stats": prognostic_stats.get("alignment_stats", {}),
        "followup_impact_count": prognostic_stats.get("followup_impact_count", 0),
        "incomplete_score_targets_count": prognostic_stats.get("incomplete_scores_count", 0),
        "high_risk_impact_count": prognostic_stats.get("high_risk_impact_count", 0),
    }
