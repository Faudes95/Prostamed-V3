from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
from prostanet.domains.patient_tracking.reconciled_state import (
    build_reconciled_state,
    derive_post_prostatectomy_truth,
)
from prostanet.domains.patient_tracking.response_assessment import ResponseAssessmentService
from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
from prostanet.domains.patient_tracking.therapy_catalog import summarize_trial_backbones
from prostanet.shared.contracts import (
    AdjudicationStatus,
    BenchmarkSnapshot,
    ClinicalFact,
    OutcomeEvent,
    TrialComparableEndpoint,
)


ENGINE_VERSION = "2026.1"
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
ADVANCED_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"} | MHSPC_STATES

TRIAL_FAMILY_PRIORITY = (
    "POST_RP_SALVAGE_like",
    "PSMA_SRT_like",
    "EMBARK_like",
    "ARANOTE_ARASENS_PEACE1_like",
    "TALAPRO2_like",
    "PSMAfore_like",
    "PEACE3_like",
)


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _months_between(start: date | None, end: date | None) -> float | None:
    if not start or not end:
        return None
    return round((end - start).days / 30.44, 1)


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return None


def _normalize_status(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"1", "true", "si", "sí", "positive", "positivo", "yes", "confirmed_castrate", "msi-h"}:
        return "positive"
    if lowered in {"0", "false", "negative", "negativo", "no", "not_castrate", "mss", "estable"}:
        return "negative"
    return lowered


def _contains_any(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _derive_line_context(patient: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    treatments = patient.get("treatments") or []
    latest_treatment = _latest(treatments, "start_date")
    previous_treatment = treatments[-2] if len(treatments) >= 2 else {}
    current_start = _parse_date(latest_treatment.get("start_date")) or _parse_date(merged.get("current_line_start_date"))
    next_start = _parse_date(previous_treatment.get("end_date")) if previous_treatment else None
    adt_start = None
    for item in treatments:
        regimen = str(item.get("drug_scheme") or "").upper()
        if "ADT" in regimen:
            adt_start = _parse_date(item.get("start_date"))
            if adt_start:
                break
    if adt_start is None:
        adt_start = current_start
    return {
        "latest_treatment": latest_treatment,
        "previous_treatment": previous_treatment,
        "current_line_start_date": current_start.isoformat() if current_start else "",
        "next_line_start_date": next_start.isoformat() if next_start else "",
        "adt_start_date": adt_start.isoformat() if adt_start else "",
        "line_of_therapy": latest_treatment.get("line_of_therapy") or merged.get("line_of_therapy") or 1,
    }


def _derive_current_psa(patient: dict[str, Any], merged: dict[str, Any]) -> tuple[float | None, str]:
    postlocal_state = str(
        _first_nonempty(
            merged.get("state"),
            (patient.get("latest_assessment") or {}).get("state"),
            (patient.get("prior_history") or {}).get("current_state"),
        )
        or ""
    )
    if postlocal_state in POSTLOCAL_STATES or patient.get("bcr") or patient.get("surgery"):
        post_rp_truth = derive_post_prostatectomy_truth(patient)
        psa_points = list(post_rp_truth.get("psa_points") or [])
        if psa_points:
            latest_point = psa_points[-1]
            return _safe_float(latest_point.get("value")), str(latest_point.get("sample_date") or "")
    psa_series = patient.get("psa_series") or []
    if psa_series:
        latest = sorted(psa_series, key=lambda item: str(item.get("sample_date") or ""))[-1]
        return _safe_float(latest.get("value")), str(latest.get("sample_date") or "")
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    return _safe_float(_first_nonempty(latest_followup.get("psa_current"), latest_followup.get("psa"), patient.get("bcr", {}).get("bcr_psa"), merged.get("psa_current"), merged.get("psa"))), str(
        _first_nonempty(latest_followup.get("visit_date"), patient.get("bcr", {}).get("bcr_date"), patient.get("identity", {}).get("diagnosis_date")) or ""
    )


def _derive_baseline_psa(patient: dict[str, Any], merged: dict[str, Any]) -> float | None:
    captured_baseline = _safe_float(_first_nonempty(merged.get("baseline_psa"), patient.get("baseline", {}).get("baseline_psa")))
    if captured_baseline is not None:
        return captured_baseline
    psa_series = patient.get("psa_series") or []
    if psa_series:
        ordered = sorted(psa_series, key=lambda item: str(item.get("sample_date") or ""))
        for item in ordered:
            value = _safe_float(item.get("value"))
            if value is not None:
                return value
    return None


def _derive_m_substage(patient: dict[str, Any], merged: dict[str, Any]) -> str:
    baseline = patient.get("baseline") or {}
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    return str(
        _first_nonempty(
            latest_followup.get("m_substage_resolved"),
            merged.get("m_substage_resolved"),
            baseline.get("m_substage_resolved"),
            merged.get("metastasis_site"),
        )
        or ""
    )


def _build_clinical_facts(patient: dict[str, Any], merged: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    current_psa, current_psa_date = _derive_current_psa(patient, merged)
    baseline_psa = _derive_baseline_psa(patient, merged)
    facts = [
        ClinicalFact(
            fact_key="current_psa",
            category="biochemical",
            value=current_psa,
            fact_date=current_psa_date,
            source_type="biomarker_longitudinal",
            source_priority="structured_longitudinal",
            verified=False,
            payload={"state": state, "management_track": management_track},
        ).to_dict(),
        ClinicalFact(
            fact_key="baseline_psa",
            category="biochemical",
            value=baseline_psa,
            fact_date=str(patient.get("identity", {}).get("diagnosis_date") or ""),
            source_type="clinical_baseline",
            source_priority="captured_baseline",
            verified=False,
        ).to_dict(),
        ClinicalFact(
            fact_key="castrate_testosterone_status",
            category="systemic_context",
            value=_first_nonempty(
                merged.get("castrate_testosterone_status"),
                latest_followup.get("castrate_testosterone_status"),
            ),
            fact_date=str(latest_followup.get("visit_date") or ""),
            source_type="follow_up_visits",
            source_priority="structured_longitudinal",
            verified=False,
        ).to_dict(),
        ClinicalFact(
            fact_key="m_substage_resolved",
            category="metastatic_context",
            value=_derive_m_substage(patient, merged),
            fact_date=str(latest_followup.get("visit_date") or patient.get("identity", {}).get("diagnosis_date") or ""),
            source_type="clinical_baseline",
            source_priority="captured_baseline",
            verified=False,
        ).to_dict(),
    ]
    return [fact for fact in facts if _is_present(fact.get("value"))]


def _emit_outcome(
    *,
    event_type: str,
    scenario_state: str,
    management_track: str,
    axis: str,
    event_date: str,
    summary: str,
    decision_impact: str,
    provisional: bool = False,
    blocking_fields: list[str] | None = None,
    evidence_basis: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    source_priority: str = "derived",
    adjudication_status: str = "confirmed",
) -> dict[str, Any]:
    resolved_date = event_date or "pending"
    return OutcomeEvent(
        event_key=f"{scenario_state}:{management_track}:{event_type}:{resolved_date}",
        event_type=event_type,
        scenario_state=scenario_state,
        management_track=management_track,
        axis=axis,
        adjudication_status=adjudication_status,
        event_date=event_date,
        source_priority=source_priority,
        decision_impact=decision_impact,
        summary=summary,
        provisional=provisional,
        blocking_fields=list(blocking_fields or []),
        evidence_basis=list(evidence_basis or []),
        payload=dict(payload or {}),
    ).to_dict()


def _pending_status(
    *,
    key: str,
    title: str,
    rationale: str,
    decision_domain: str,
    fields: list[str] | None = None,
    capture_block: str = "",
    severity: str = "warning",
    action_type: str = "capture",
    expected_document_type: str = "",
    linked_outcome_event: str = "",
    recommended_action: str = "",
    evidence_basis: list[str] | None = None,
) -> dict[str, Any]:
    return AdjudicationStatus(
        status_key=key,
        title=title,
        rationale=rationale,
        status="pending",
        severity=severity,
        provisional=True,
        decision_domain=decision_domain,
        capture_block=capture_block,
        action_type=action_type,
        expected_document_type=expected_document_type,
        linked_outcome_event=linked_outcome_event,
        fields_to_capture=list(fields or []),
        recommended_action=recommended_action or title,
        evidence_basis=list(evidence_basis or []),
    ).to_dict()


def _build_response_state(patient: dict[str, Any], state: str, merged: dict[str, Any]) -> dict[str, Any]:
    latest_response = _latest(patient.get("response_assessments") or [], "assessment_date", "id")
    baseline_psa = _derive_baseline_psa(patient, merged)
    current_psa, current_psa_date = _derive_current_psa(patient, merged)
    if latest_response:
        overall = str(latest_response.get("overall_response") or latest_response.get("details", {}).get("overall") or "")
        psa_category = str(latest_response.get("psa_response_category") or latest_response.get("details", {}).get("psa", {}).get("category") or "")
        summary = " / ".join([part for part in [overall, psa_category] if part]) or "Respuesta registrada"
        return {
            "label": summary,
            "overall": overall,
            "psa_category": psa_category,
            "assessment_date": str(latest_response.get("assessment_date") or ""),
            "provisional": False,
        }
    if baseline_psa is not None and current_psa is not None and baseline_psa > 0:
        try:
            derived = ResponseAssessmentService.assess_psa(
                baseline_psa=baseline_psa,
                current_psa=current_psa,
                nadir_psa=current_psa,
                confirmed_at_4_weeks=False,
            )
            return {
                "label": derived.category,
                "overall": "",
                "psa_category": derived.category,
                "assessment_date": current_psa_date,
                "provisional": True,
            }
        except Exception:
            pass
    return {
        "label": "Sin respuesta adjudicada",
        "overall": "",
        "psa_category": "",
        "assessment_date": "",
        "provisional": True,
    }


def _has_radiographic_progression(patient: dict[str, Any], merged: dict[str, Any], response_state: dict[str, Any]) -> tuple[bool, str]:
    latest_response = _latest(patient.get("response_assessments") or [], "assessment_date", "id")
    if str(latest_response.get("overall_response") or "").upper() == "PD":
        return True, str(latest_response.get("assessment_date") or "")
    if str(latest_response.get("recist_category") or "").upper() == "PD":
        return True, str(latest_response.get("assessment_date") or "")
    if str(latest_response.get("pcwg3_bone_status") or "") == "new_confirmed":
        return True, str(latest_response.get("assessment_date") or "")
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    disease_status = str(_first_nonempty(latest_followup.get("disease_status"), merged.get("disease_status")) or "").lower()
    if "radiograf" in disease_status or "progres" in disease_status:
        return True, str(latest_followup.get("visit_date") or "")
    if response_state.get("overall") == "PD":
        return True, str(response_state.get("assessment_date") or "")
    return False, ""


def _has_visceral_progression(patient: dict[str, Any], merged: dict[str, Any]) -> tuple[bool, str]:
    m_substage = _derive_m_substage(patient, merged).upper()
    if m_substage == "M1C":
        latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
        return True, str(latest_followup.get("visit_date") or "")
    imaging = patient.get("imaging") or []
    for study in imaging:
        findings = study.get("findings") if isinstance(study.get("findings"), dict) else {}
        haystack = " ".join(str(item).lower() for item in list(findings.get("ct_locations") or []) + list(findings.get("lesion_locations") or []))
        if any(token in haystack for token in ("pulm", "higad", "visceral", "cerebr", "peritoneo")):
            return True, str(study.get("study_date") or "")
    return False, ""


def _build_sre_profile(patient: dict[str, Any]) -> dict[str, Any]:
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    baseline = patient.get("baseline") or {}
    payload: dict[str, Any] = {}
    payload.update(patient.get("identity") or {})
    payload.update(baseline)
    payload.update(patient.get("prior_history") or {})
    payload.update(latest_followup)
    payload["skeletal_events"] = patient.get("skeletal_events") or patient.get("sre_events") or []
    try:
        return SkeletalEventService.build_sre_profile(payload, str(_first_nonempty(patient.get("latest_assessment", {}).get("state"), patient.get("prior_history", {}).get("current_state")) or "")).to_dict()
    except Exception:
        return {}


def _build_survival_input(patient: dict[str, Any], merged: dict[str, Any], state: str, line_context: dict[str, Any], outcome_events: list[dict[str, Any]]) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    baseline = patient.get("baseline") or {}
    prior_history = patient.get("prior_history") or {}
    bcr = patient.get("bcr") or {}
    surgery = patient.get("surgery") or {}
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    payload: dict[str, Any] = {}
    payload.update(identity)
    payload.update(baseline)
    payload.update(prior_history)
    payload.update(merged)
    payload.update(bcr)
    payload.update(surgery)
    payload["patient_id"] = identity.get("id")
    payload["diagnosis_date"] = identity.get("diagnosis_date")
    payload["last_contact_date"] = str(_first_nonempty(latest_followup.get("visit_date"), identity.get("diagnosis_date"), date.today().isoformat()) or "")
    payload["current_line_start_date"] = line_context.get("current_line_start_date") or ""
    payload["next_line_start_date"] = line_context.get("next_line_start_date") or ""
    payload["adt_start_date"] = line_context.get("adt_start_date") or ""
    payload["line_of_therapy"] = line_context.get("line_of_therapy") or 1
    payload["current_treatment"] = str(_first_nonempty(latest_followup.get("current_treatment"), line_context.get("latest_treatment", {}).get("drug_scheme_label")) or "")
    payload["metastatic_diagnosis_date"] = _first_nonempty(
        merged.get("first_metastasis_date"),
        latest_followup.get("visit_date") if _derive_m_substage(patient, merged).upper().startswith("M1") else "",
    ) or ""
    payload["radiographic_progression_date"] = next(
        (item.get("event_date") for item in outcome_events if item.get("event_type") == "radiographic_progression" and item.get("event_date")),
        "",
    )
    payload["crpc_confirmation_date"] = next(
        (item.get("event_date") for item in outcome_events if item.get("event_type") == "crpc_confirmed" and item.get("event_date")),
        "",
    )
    payload["psa_progression_date"] = _first_nonempty(merged.get("psa_progression_date"), latest_followup.get("visit_date") if "progression" in str(latest_followup.get("disease_status") or "").lower() else "")
    payload["skeletal_events"] = patient.get("skeletal_events") or patient.get("sre_events") or []
    payload["sre_profile"] = _build_sre_profile(patient)
    return payload


def _build_psa_milestones(patient: dict[str, Any], state: str, management_track: str, merged: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    baseline_psa = _derive_baseline_psa(patient, merged)
    current_psa, current_psa_date = _derive_current_psa(patient, merged)
    if baseline_psa is None or current_psa is None or baseline_psa <= 0 or not current_psa_date:
        return events
    change_pct = ((current_psa - baseline_psa) / baseline_psa) * 100
    if change_pct <= -50:
        events.append(
            _emit_outcome(
                event_type="psa50_achieved",
                scenario_state=state,
                management_track=management_track,
                axis="biochemical",
                event_date=current_psa_date,
                summary=f"PSA50 alcanzado ({abs(change_pct):.1f}% de reducción).",
                decision_impact="Confirma respuesta bioquímica temprana comparable con cohortes de intensificación sistémica.",
                evidence_basis=["ARANOTE", "SWOG S1216", "PCWG3 PSA kinetics"],
                payload={"change_from_baseline_pct": round(change_pct, 1), "current_psa": current_psa, "baseline_psa": baseline_psa},
            )
        )
    if change_pct <= -90:
        events.append(
            _emit_outcome(
                event_type="psa90_achieved",
                scenario_state=state,
                management_track=management_track,
                axis="biochemical",
                event_date=current_psa_date,
                summary=f"PSA90 alcanzado ({abs(change_pct):.1f}% de reducción).",
                decision_impact="Sugiere respuesta biológica profunda comparable con ensayos contemporáneos mHSPC.",
                evidence_basis=["ARANOTE", "SWOG S1216"],
                payload={"change_from_baseline_pct": round(change_pct, 1), "current_psa": current_psa, "baseline_psa": baseline_psa},
            )
        )
    if current_psa <= 0.2:
        events.append(
            _emit_outcome(
                event_type="ultralow_psa_milestone",
                scenario_state=state,
                management_track=management_track,
                axis="biochemical",
                event_date=current_psa_date,
                summary=f"PSA ultrabajo alcanzado ({current_psa:.2f} ng/mL).",
                decision_impact="Milestone pronóstico favorable durante terapia sistémica activa.",
                evidence_basis=["SWOG S1216", "PCWG3 PSA kinetics"],
                payload={"current_psa": current_psa},
            )
        )
    return events


def _build_postlocal_outcomes(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    bcr = patient.get("bcr") or {}
    surgery = patient.get("surgery") or {}
    derived_psa, derived_psa_date = _derive_current_psa(patient, merged)
    current_psa = _safe_float(_first_nonempty(bcr.get("bcr_psa"), derived_psa))
    current_psa_date = str(_first_nonempty(bcr.get("bcr_date"), derived_psa_date) or "")
    psadt = _safe_float(_first_nonempty(merged.get("psadt_months"), bcr.get("psadt_at_bcr")))
    bcr_date = str(_first_nonempty(bcr.get("bcr_date"), current_psa_date) or "")
    bcr_detected = bool(_safe_int(bcr.get("bcr_detected")) == 1 or (current_psa is not None and current_psa >= 0.2 and surgery))

    if bcr_detected:
        events.append(
            _emit_outcome(
                event_type="bcr_detected",
                scenario_state=state,
                management_track=management_track,
                axis="biochemical",
                event_date=bcr_date,
                summary=f"Recurrencia bioquímica adjudicada con PSA {current_psa:.2f} ng/mL." if current_psa is not None else "Recurrencia bioquímica adjudicada.",
                decision_impact="Activa estratificación de riesgo, ventana de rescate y comparación tipo EMBARK.",
                evidence_basis=["EMBARK", "NCCN 2026 BCR", "EAU 2026 salvage"],
                payload={"current_psa": current_psa, "psadt_months": psadt, "bcr_definition": bcr.get("bcr_definition")},
                source_priority="structured_longitudinal",
            )
        )
    if psadt is not None:
        if psadt <= 9:
            events.append(
                _emit_outcome(
                    event_type="high_risk_bcr",
                    scenario_state=state,
                    management_track=management_track,
                    axis="biochemical",
                    event_date=bcr_date,
                    summary=f"BCR de alto riesgo por PSADT {psadt:.1f} meses.",
                    decision_impact="Aumenta prioridad de imagen dirigida y deliberación de intensificación o rescate.",
                    evidence_basis=["EMBARK", "EAU 2026 salvage"],
                    payload={"psadt_months": psadt},
                    source_priority="structured_longitudinal",
                )
            )
    elif bcr_detected:
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:psadt_risk",
                title="No se puede adjudicar riesgo BCR sin PSADT",
                rationale="La ventana de rescate y la comparabilidad tipo EMBARK requieren PSADT documentado.",
                decision_domain="salvage_gate",
                fields=["psadt_months"],
                capture_block="psa_monitoring",
                severity="critical",
                recommended_action="Documentar PSADT para clasificar BCR de alto riesgo y priorizar rescate.",
                evidence_basis=["EMBARK", "NCCN 2026 BCR"],
            )
        )

    m_substage = _derive_m_substage(patient, merged).upper()
    if bcr_detected and not m_substage.startswith("M1"):
        current_value = current_psa or 0.0
        window_event = "salvage_window_open" if current_value <= 0.5 else "salvage_window_closing"
        window_label = "Ventana de rescate abierta" if current_value <= 0.5 else "Ventana de rescate estrechándose"
        events.append(
            _emit_outcome(
                event_type=window_event,
                scenario_state=state,
                management_track=management_track,
                axis="management_window",
                event_date=current_psa_date or bcr_date,
                summary=f"{window_label} con PSA {current_value:.2f} ng/mL.",
                decision_impact="Mantiene seguimiento curativo y evita transición errónea a enfermedad metastásica sin imagen.",
                provisional=current_value > 0.5,
                evidence_basis=["PSMA-SRT", "NCCN 2026 salvage"],
                payload={"current_psa": current_value},
                source_priority="derived",
                adjudication_status="provisional" if current_value > 0.5 else "confirmed",
            )
        )

    if bcr_detected and not patient.get("imaging"):
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:salvage_imaging",
                title="No se puede cerrar la ventana de rescate sin imagen dirigida",
                rationale="La recurrencia bioquímica no debe saltar automáticamente a enfermedad metastásica sin reestadificación documentada.",
                decision_domain="restaging",
                fields=["imaging_modality"],
                capture_block="restaging",
                severity="warning",
                recommended_action="Documentar imagen dirigida o PSMA-PET/CT según el contexto postlocal.",
                evidence_basis=["PSMA-SRT", "NCCN 2026 salvage"],
            )
        )

    if bcr.get("salvage_date"):
        salvage_response = str(bcr.get("salvage_response") or "").strip()
        if salvage_response:
            events.append(
                _emit_outcome(
                    event_type="post_salvage_response",
                    scenario_state=state,
                    management_track=management_track,
                    axis="post_salvage",
                    event_date=str(bcr.get("salvage_date") or ""),
                    summary=f"Respuesta post-salvamento documentada: {salvage_response}.",
                    decision_impact="Permite comparar respuesta temprana post-rescate y definir consolidación del plan.",
                    evidence_basis=["PSMA-SRT", "NCCN 2026 salvage"],
                    payload={"salvage_response": salvage_response},
                    source_priority="structured_longitudinal",
                )
            )
    return events, pending


def _build_adt_progression_outcomes(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
    response_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    castrate_status = str(_first_nonempty(merged.get("castrate_testosterone_status"), latest_followup.get("castrate_testosterone_status")) or "")
    current_testosterone = _safe_float(
        _first_nonempty(
            patient.get("latest_testosterone_value"),
            latest_followup.get("testosterone_current"),
            merged.get("testosterone"),
        )
    )
    progression_pattern = str(_first_nonempty(merged.get("progression_pattern"), latest_followup.get("disease_status")) or "").lower()
    radiographic_progression, radiographic_date = _has_radiographic_progression(patient, merged, response_state)

    if _normalize_status(castrate_status) != "positive" and not (current_testosterone is not None and current_testosterone <= 50):
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:crpc_confirmation",
                title="No se puede adjudicar CRPC confirmado",
                rationale="Existe progresión bajo ADT, pero falta testosterona en rango de castración o su verificación estructurada.",
                decision_domain="systemic_sequencing",
                fields=["testosterone", "castrate_testosterone_status", "current_adt_context"],
                capture_block="advanced_sequencing",
                severity="critical",
                recommended_action="Confirmar testosterona y backbone ADT antes de cerrar CRPC.",
                evidence_basis=["NCCN 2026 CRPC", "EAU 2026 progression under ADT"],
            )
        )
        events.append(
            _emit_outcome(
                event_type="crpc_confirmation_pending",
                scenario_state=state,
                management_track=management_track,
                axis="castration_resistance",
                event_date=str(latest_followup.get("visit_date") or ""),
                summary="Adjudicación CRPC pendiente por castración no confirmada.",
                decision_impact="Bloquea transición formal a CRPC y evita escalar secuencia terapéutica sin confirmación.",
                provisional=True,
                blocking_fields=["testosterone", "castrate_testosterone_status", "current_adt_context"],
                evidence_basis=["NCCN 2026 CRPC", "EAU 2026 progression under ADT"],
                payload={"testosterone": current_testosterone, "castrate_testosterone_status": castrate_status},
                adjudication_status="provisional",
            )
        )
    else:
        if radiographic_progression or "progress" in progression_pattern or state in {"m0_crpc", "m1_crpc"}:
            event_type = "crpc_confirmed" if state in {"m0_crpc", "m1_crpc"} else "crpc_confirmation_ready"
            events.append(
                _emit_outcome(
                    event_type=event_type,
                    scenario_state=state,
                    management_track=management_track,
                    axis="castration_resistance",
                    event_date=radiographic_date or str(latest_followup.get("visit_date") or ""),
                    summary="Castración confirmada con progresión compatible con CRPC." if event_type == "crpc_confirmed" else "El caso ya tiene castración confirmada y puede cerrarse como CRPC si se confirma el eje de progresión.",
                    decision_impact="Sostiene la ruta CRPC y la elegibilidad a secuencias avanzadas, restaging y biomarcadores de precisión.",
                    provisional=event_type != "crpc_confirmed",
                    evidence_basis=["NCCN 2026 CRPC", "EAU 2026 CRPC"],
                    payload={"progression_pattern": progression_pattern, "testosterone": current_testosterone},
                    adjudication_status="confirmed" if event_type == "crpc_confirmed" else "provisional",
                )
            )

    if radiographic_progression:
        events.append(
            _emit_outcome(
                event_type="radiographic_progression",
                scenario_state=state,
                management_track=management_track,
                axis="radiographic",
                event_date=radiographic_date,
                summary="Progresión radiográfica adjudicada.",
                decision_impact="Activa restaging protocolizado y redefinición de línea terapéutica.",
                evidence_basis=["RECIST 1.1", "PCWG3", "NCCN 2026 CRPC"],
                payload={"response_state": response_state},
                source_priority="response_assessment",
            )
        )
    else:
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:radiographic_progression",
                title="No se puede adjudicar progresión radiográfica",
                rationale="Falta reestadificación convencional o evaluación objetiva suficiente para clasificar el eje de progresión.",
                decision_domain="restaging",
                fields=["conventional_imaging_status", "imaging_modality"],
                capture_block="restaging",
                severity="warning",
                recommended_action="Completar imagen convencional o PSMA y documentar resultado adjudicable.",
                evidence_basis=["RECIST 1.1", "PCWG3"],
            )
        )
    return events, pending


def _build_mhspc_outcomes(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
    response_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _build_psa_milestones(patient, state, management_track, merged)
    pending: list[dict[str, Any]] = []
    radiographic_progression, radiographic_date = _has_radiographic_progression(patient, merged, response_state)
    if radiographic_progression:
        events.append(
            _emit_outcome(
                event_type="radiographic_progression",
                scenario_state=state,
                management_track=management_track,
                axis="radiographic",
                event_date=radiographic_date,
                summary="Progresión radiográfica adjudicada durante mHSPC.",
                decision_impact="Adelanta revisión de respuesta y eventual transición del curso natural de enfermedad.",
                evidence_basis=["ARANOTE", "ARASENS", "PCWG3"],
                payload={"response_state": response_state},
                source_priority="response_assessment",
            )
        )
    events.append(
        _emit_outcome(
            event_type="time_to_crpc_clock_running",
            scenario_state=state,
            management_track=management_track,
            axis="disease_course",
            event_date=_derive_line_context(patient, merged).get("adt_start_date") or "",
            summary="Reloj de tiempo a CRPC activo desde inicio de backbone ADT.",
            decision_impact="Permite comparar duración de beneficio por línea con cohortes tipo ARANOTE/ARASENS/PEACE-1.",
            provisional=True,
            evidence_basis=["ARANOTE", "ARASENS", "PEACE-1"],
            adjudication_status="provisional",
        )
    )
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    if _safe_int(latest_followup.get("pain_score")) is not None and _safe_int(latest_followup.get("pain_score")) >= 7:
        events.append(
            _emit_outcome(
                event_type="symptomatic_progression",
                scenario_state=state,
                management_track=management_track,
                axis="clinical_symptomatic",
                event_date=str(latest_followup.get("visit_date") or ""),
                summary="Progresión sintomática sugerida por dolor clínicamente relevante.",
                decision_impact="Aumenta urgencia de reestadificación y revisión de soporte/analgesia.",
                provisional=True,
                evidence_basis=["NCCN 2026 mHSPC"],
                payload={"pain_score": _safe_int(latest_followup.get("pain_score"))},
                adjudication_status="provisional",
            )
        )
    return events, pending


def _build_crpc_outcomes(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
    response_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    radiographic_progression, radiographic_date = _has_radiographic_progression(patient, merged, response_state)
    visceral_progression, visceral_date = _has_visceral_progression(patient, merged)
    if state in {"m0_crpc", "m1_crpc"}:
        events.append(
            _emit_outcome(
                event_type="crpc_confirmed",
                scenario_state=state,
                management_track=management_track,
                axis="castration_resistance",
                event_date=str(latest_followup.get("visit_date") or ""),
                summary="CRPC adjudicado en el longitudinal reconciliado.",
                decision_impact="Abre secuenciación específica CRPC y endpoints comparables tipo PSMAfore / TALAPRO-2.",
                evidence_basis=["NCCN 2026 CRPC", "EAU 2026 CRPC"],
                source_priority="state_reconciled",
            )
        )
    if radiographic_progression:
        events.append(
            _emit_outcome(
                event_type="radiographic_progression",
                scenario_state=state,
                management_track=management_track,
                axis="radiographic",
                event_date=radiographic_date,
                summary="rPFS event adjudicado.",
                decision_impact="Permite benchmarking de rPFS y rediseña el siguiente paso terapéutico.",
                evidence_basis=["RECIST 1.1", "PCWG3", "PSMAfore", "TALAPRO-2"],
                payload={"response_state": response_state},
                source_priority="response_assessment",
            )
        )
    if visceral_progression:
        events.append(
            _emit_outcome(
                event_type="visceral_progression",
                scenario_state=state,
                management_track=management_track,
                axis="visceral",
                event_date=visceral_date,
                summary="Progresión visceral adjudicada.",
                decision_impact="Modifica pronóstico, restaging y comparabilidad con cohortes mCRPC de alto riesgo.",
                evidence_basis=["NCCN 2026 mCRPC", "EAU 2026 mCRPC"],
                source_priority="imaging_structured",
            )
        )
    sre_profile = _build_sre_profile(patient)
    if sre_profile.get("total_sre_count"):
        events.append(
            _emit_outcome(
                event_type="skeletal_event",
                scenario_state=state,
                management_track=management_track,
                axis="bone",
                event_date=_first_nonempty(
                    (sre_profile.get("sre_events") or [{}])[0].get("event_date") if sre_profile.get("sre_events") else "",
                    str(latest_followup.get("visit_date") or ""),
                )
                or "",
                summary=f"Evento esquelético adjudicado ({sre_profile.get('total_sre_count')} total).",
                decision_impact="Aumenta prioridad de soporte óseo, radium/PEACE-3-like y vigilancia de SSE.",
                evidence_basis=["PEACE-3", "NCCN 2026 bone health"],
                payload={"sre_profile": sre_profile},
                source_priority="skeletal_events",
            )
        )
    precision_events, precision_pending = _build_crpc_precision_pathway_outcomes(
        patient,
        state,
        management_track,
        merged,
    )
    events.extend(precision_events)
    pending.extend(precision_pending)
    return events, pending


def _build_crpc_precision_pathway_outcomes(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    psma_positive = _normalize_status(_first_nonempty(merged.get("psma_positive"), latest_followup.get("psma_positive")))
    psma_profile = patient.get("psma_structured_profile") or {}
    psma_impact = patient.get("psma_decision_impact") or {}
    if psma_positive == "positive":
        events.append(
            _emit_outcome(
                event_type="psma_positive_pathway",
                scenario_state=state,
                management_track=management_track,
                axis="precision_pathway",
                event_date=str(latest_followup.get("visit_date") or ""),
                summary="Ruta PSMA positiva disponible.",
                decision_impact="Abre elegibilidad comparativa tipo PSMAfore cuando el contexto terapéutico es congruente.",
                evidence_basis=["PSMAfore", "NCCN 2026 radioligand"],
                payload={"psma_positive": True},
            )
        )
        if psma_profile.get("available"):
            events.append(
                _emit_outcome(
                    event_type="psma_structured_pathway",
                    scenario_state=state,
                    management_track=management_track,
                    axis="precision_pathway",
                    event_date=str(psma_profile.get("study_date") or latest_followup.get("visit_date") or ""),
                    summary="PSMA estructurado disponible.",
                    decision_impact=psma_impact.get("rationale") or "La imagen PSMA estructurada refina rescate, MDT o elegibilidad a radioligando.",
                    evidence_basis=["PSMA-RADS", "NCCN 2026 radioligand"],
                    payload={"psma_pattern": psma_profile.get("psma_uptake_pattern"), "psma_rads_score": psma_profile.get("psma_rads_score")},
                )
            )
            if psma_profile.get("psma_upstaged_vs_conventional") is True:
                events.append(
                    _emit_outcome(
                        event_type="psma_upstaging_event",
                        scenario_state=state,
                        management_track=management_track,
                        axis="restaging",
                        event_date=str(psma_profile.get("study_date") or latest_followup.get("visit_date") or ""),
                        summary="PSMA con upstaging frente a imagen convencional.",
                        decision_impact="Cambia la lectura de burden/estado y puede redirigir rescate o transición sistémica.",
                        evidence_basis=["proPSMA", "NCCN 2026 imaging"],
                        payload={"stage_before": psma_profile.get("conventional_stage_before_psma"), "stage_after": psma_profile.get("psma_stage_after_psma")},
                    )
                )
            if psma_impact.get("confidence") == "low":
                events.append(
                    _emit_outcome(
                        event_type="psma_low_confidence_finding",
                        scenario_state=state,
                        management_track=management_track,
                        axis="restaging",
                        event_date=str(psma_profile.get("study_date") or latest_followup.get("visit_date") or ""),
                        summary="PSMA estructurado de baja confianza.",
                        decision_impact="Debe interpretarse con cautela y correlacionarse antes de escalar una conducta mayor.",
                        evidence_basis=["PSMA-RADS"],
                        payload={"psma_rads_score": psma_profile.get("psma_rads_score")},
                    )
                )
    else:
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:psma_pathway",
                title="No se puede adjudicar vía PSMA",
                rationale="Falta PSMA estructurado o su trazabilidad para comparar elegibilidad a radioligando.",
                decision_domain="restaging",
                fields=["psma_positive", "psma_negative_dominant_lesions", "imaging_modality"],
                capture_block="biomarker_eligibility",
                severity="warning",
                recommended_action="Completar PSMA y documentar si existe enfermedad dominante PSMA-negativa.",
                evidence_basis=["PSMAfore", "NCCN 2026 radioligand"],
            )
        )
    hrr_status = _normalize_status(_first_nonempty(merged.get("hrr_status"), patient.get("genomics", {}).get("hrr_overall")))
    brca2_status = _normalize_status(_first_nonempty(merged.get("brca2_status"), patient.get("genomics", {}).get("brca2_status")))
    msi_status = _normalize_status(_first_nonempty(merged.get("msi_status"), patient.get("genomics", {}).get("msi_status")))
    if hrr_status == "positive" or brca2_status == "positive" or msi_status in {"msi-h", "inestable", "positive"}:
        events.append(
            _emit_outcome(
                event_type="precision_therapy_pathway",
                scenario_state=state,
                management_track=management_track,
                axis="precision_pathway",
                event_date=str(_first_nonempty(patient.get("genomics", {}).get("test_date"), latest_followup.get("visit_date")) or ""),
                summary="Ruta de precisión adjudicable por biomarcadores.",
                decision_impact="Sostiene benchmarking tipo TALAPRO-2 y rutas PARP/IO según biomarcadores.",
                evidence_basis=["TALAPRO-2", "NCCN 2026 precision biomarkers"],
                payload={"hrr_status": hrr_status, "brca2_status": brca2_status, "msi_status": msi_status},
                source_priority="genomic_profile",
            )
        )
    else:
        pending.append(
            _pending_status(
                key=f"{state}:{management_track}:precision_pathway",
                title="No se puede adjudicar ruta de precisión",
                rationale="Faltan biomarcadores accionables verificables para clasificar elegibilidad PARP / IO.",
                decision_domain="precision_therapy",
                fields=["hrr_status", "hrr_gene", "brca2_status", "msi_status", "biomarker_source", "molecular_assay_date"],
                capture_block="biomarker_eligibility",
                severity="critical",
                recommended_action="Completar y verificar biomarcadores accionables antes de secuenciar precisión.",
                evidence_basis=["TALAPRO-2", "NCCN 2026 biomarkers"],
            )
        )
    return events, pending


def _build_trial_comparable_endpoints(
    patient: dict[str, Any],
    state: str,
    line_context: dict[str, Any],
    outcome_events: list[dict[str, Any]],
    response_state: dict[str, Any],
    survival_status: dict[str, Any],
    benchmark_snapshots: list[dict[str, Any]],
    merged: dict[str, Any],
) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    current_family = benchmark_snapshots[0]["benchmark_family"] if benchmark_snapshots else ""
    survival_by_type = {item.get("endpoint_type"): item for item in survival_status.get("endpoints", [])}

    def add_endpoint(endpoint_key: str, label: str, status: str, value: Any = None, details: str = "", comparable: bool = False, provisional: bool = False, evidence_basis: list[str] | None = None):
        endpoints.append(
            TrialComparableEndpoint(
                endpoint_key=endpoint_key,
                label=label,
                status=status,
                value=value,
                scenario_state=state,
                trial_family=current_family,
                comparable=comparable,
                provisional=provisional,
                details=details,
                evidence_basis=list(evidence_basis or []),
            ).to_dict()
        )

    time_to_crpc = survival_by_type.get("time_to_crpc")
    if time_to_crpc:
        add_endpoint(
            "time_to_crpc",
            "Tiempo a CRPC",
            "complete" if not time_to_crpc.get("censored", True) else "ongoing",
            value=time_to_crpc.get("duration_months"),
            details="Meses desde inicio de ADT hasta CRPC confirmado o censura.",
            comparable=state in MHSPC_STATES | {"adt_progression_verification"},
            provisional=False,
            evidence_basis=time_to_crpc.get("evidence_tags", []),
        )

    time_to_next_line = survival_by_type.get("time_to_next_line")
    if time_to_next_line:
        add_endpoint(
            "time_to_next_treatment",
            "Tiempo a siguiente tratamiento",
            "complete" if not time_to_next_line.get("censored", True) else "ongoing",
            value=time_to_next_line.get("duration_months"),
            details="Meses desde inicio de línea actual hasta siguiente línea o censura.",
            comparable=state in ADVANCED_STATES,
            evidence_basis=time_to_next_line.get("evidence_tags", []),
        )

    current_start = _parse_date(line_context.get("current_line_start_date"))
    if current_start and state in ADVANCED_STATES:
        add_endpoint(
            "time_on_treatment",
            "Tiempo en tratamiento",
            "ongoing",
            value=_months_between(current_start, date.today()),
            details="Duración actual de la línea terapéutica en meses.",
            comparable=state in ADVANCED_STATES,
            evidence_basis=["NCCN 2026 treatment sequencing"],
        )

    milestone_types = {item.get("event_type") for item in outcome_events}
    if state in MHSPC_STATES | {"m1_crpc"}:
        add_endpoint(
            "psa50",
            "PSA50",
            "complete" if "psa50_achieved" in milestone_types else "missing",
            value="sí" if "psa50_achieved" in milestone_types else "no",
            details="Reducción ≥50% desde baseline.",
            comparable=True,
            provisional=response_state.get("provisional", False),
            evidence_basis=["ARANOTE", "SWOG S1216", "PCWG3 PSA kinetics"],
        )
        add_endpoint(
            "psa90",
            "PSA90",
            "complete" if "psa90_achieved" in milestone_types else "missing",
            value="sí" if "psa90_achieved" in milestone_types else "no",
            details="Reducción ≥90% desde baseline.",
            comparable=True,
            provisional=response_state.get("provisional", False),
            evidence_basis=["ARANOTE", "SWOG S1216"],
        )
        add_endpoint(
            "ultralow_psa_milestone",
            "PSA ultrabajo",
            "complete" if "ultralow_psa_milestone" in milestone_types else "missing",
            value="sí" if "ultralow_psa_milestone" in milestone_types else "no",
            details="Milestone de PSA ≤0.2 ng/mL.",
            comparable=True,
            provisional=response_state.get("provisional", False),
            evidence_basis=["SWOG S1216"],
        )

    mfs = survival_by_type.get("MFS")
    if mfs:
        add_endpoint(
            "metastasis_free_survival_proxy",
            "MFS proxy",
            "complete" if not mfs.get("censored", True) else "ongoing",
            value=mfs.get("duration_months"),
            details="Proxy de MFS derivado del longitudinal reconciliado.",
            comparable=state in POSTLOCAL_STATES | {"localized_initial", "m0_crpc"},
            evidence_basis=mfs.get("evidence_tags", []),
        )
    rpfs = survival_by_type.get("rPFS")
    if rpfs:
        add_endpoint(
            "radiographic_pfs_proxy",
            "rPFS proxy",
            "complete" if not rpfs.get("censored", True) else "ongoing",
            value=rpfs.get("duration_months"),
            details="Proxy de rPFS derivado de restaging/response assessment.",
            comparable=state in ADVANCED_STATES | MHSPC_STATES,
            evidence_basis=rpfs.get("evidence_tags", []),
        )
    ttsre = survival_by_type.get("TTSRE")
    if ttsre:
        add_endpoint(
            "skeletal_event_free_survival",
            "Skeletal event-free survival",
            "complete" if not ttsre.get("censored", True) else "ongoing",
            value=ttsre.get("duration_months"),
            details="Meses a primer evento esquelético o censura.",
            comparable=state in MHSPC_STATES | {"m1_crpc"},
            evidence_basis=ttsre.get("evidence_tags", []),
        )
    add_endpoint(
        "visceral_progression_rate",
        "Progresión visceral",
        "complete",
        value="sí" if any(item.get("event_type") == "visceral_progression" for item in outcome_events) else "no",
        details="Bandera paciente-nivel de progresión visceral adjudicada.",
        comparable=state in {"m1_crpc"},
        evidence_basis=["NCCN 2026 mCRPC"],
    )
    return endpoints


def _build_benchmark_snapshots(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    merged: dict[str, Any],
    outcome_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    bcr = patient.get("bcr") or {}
    treatments = patient.get("treatments") or []
    hrr_status = _normalize_status(_first_nonempty(merged.get("hrr_status"), patient.get("genomics", {}).get("hrr_overall")))
    brca2_status = _normalize_status(_first_nonempty(merged.get("brca2_status"), patient.get("genomics", {}).get("brca2_status")))
    psma_positive = _normalize_status(_first_nonempty(merged.get("psma_positive"), _latest(patient.get("follow_ups") or [], "visit_date").get("psma_positive")))
    m_substage = _derive_m_substage(patient, merged).upper()
    psadt = _safe_float(_first_nonempty(merged.get("psadt_months"), bcr.get("psadt_at_bcr")))
    prior_regimens = " ".join(str(item.get("drug_scheme") or "") for item in treatments).upper()
    prior_arpi = any(token in prior_regimens for token in ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE"))
    prior_docetaxel = any(token in prior_regimens for token in ("DOCETAXEL", "CABAZITAXEL"))
    bone_dominant = m_substage == "M1B" or str(merged.get("metastasis_site") or "").lower() in {"bone", "hueso"} or any(item.get("event_type") == "skeletal_event" for item in outcome_events)

    def add_snapshot(family: str, status: str, matched_trials: list[str], flags: list[str], notes: list[str]):
        backbone_bundle = summarize_trial_backbones(matched_trials)
        snapshots.append(
            BenchmarkSnapshot(
                benchmark_family=family,
                scenario_state=state,
                management_track=management_track,
                eligibility_status=status,
                matched_trials=matched_trials,
                endpoint_snapshot={},
                cohort_flags=flags,
                notes=notes,
                recommended_trial_backbone=list(backbone_bundle.get("recommended_trial_backbone") or []),
                recommended_trial_backbone_label=str(backbone_bundle.get("recommended_trial_backbone_label") or ""),
                recommended_trial_backbone_source=str(backbone_bundle.get("recommended_trial_backbone_source") or ""),
                recommended_trial_backbone_note=str(backbone_bundle.get("recommended_trial_backbone_note") or ""),
            ).to_dict()
        )

    if state == "recurrence_bcr" and (patient.get("surgery") or patient.get("radiation")):
        salvage_local_flag = _normalize_status(
            _first_nonempty(
                merged.get("salvage_local_feasible"),
                merged.get("local_salvage_candidate"),
                _latest(patient.get("follow_ups") or [], "visit_date").get("salvage_local_feasible"),
            )
        )
        systemic_redirect = m_substage in {"M1", "M1A", "M1B", "M1C"}
        salvage_local_plausible = not systemic_redirect and salvage_local_flag != "negative"
        if salvage_local_plausible:
            snapshots.append(
                BenchmarkSnapshot(
                    benchmark_family="POST_RP_SALVAGE_like",
                    scenario_state=state,
                    management_track=management_track,
                    eligibility_status="matched" if patient.get("surgery") else "partial",
                    matched_trials=["RAVES", "RADICALS-RT", "ARTISTIC", "GETUG-AFU 16", "RTOG 9601", "SPPORT", "EMPIRE-1"],
                    endpoint_snapshot={},
                    cohort_flags=["BCR post tratamiento local", "Ruta de rescate todavía plausible"],
                    notes=[
                        "La familia dominante del caso sigue siendo salvage post-RP hasta que una imagen/documentación redirija la conducta fuera de rescate local.",
                    ],
                    recommended_trial_backbone=["SALVAGE_RT_CONTEXTUAL_ADT"],
                    recommended_trial_backbone_label="RT de salvage temprana +/- ADT corta/prolongada",
                    recommended_trial_backbone_source="RAVES, RADICALS-RT, ARTISTIC, GETUG-AFU 16, RTOG 9601, SPPORT, EMPIRE-1",
                    recommended_trial_backbone_note="La evidencia comparable favorece activar rescate y reestadificación dirigida antes de pivotar a intensificación sistémica tipo EMBARK.",
                ).to_dict()
            )
        if psadt is not None and psadt <= 9:
            add_snapshot(
                "EMBARK_like",
                "matched",
                ["EMBARK"],
                [f"PSADT {psadt:.1f} meses", "BCR post tratamiento local"],
                [
                    "Cohorte de BCR de alto riesgo comparable para análisis observacional."
                    if not salvage_local_plausible
                    else "Aunque existe BCR de alto riesgo tipo EMBARK, la ruta de salvage local sigue siendo clínicamente plausible y domina la comparación actual."
                ],
            )
        else:
            add_snapshot(
                "EMBARK_like",
                "partial",
                ["EMBARK"],
                ["BCR post tratamiento local"],
                [
                    "Falta PSADT rápido o riesgo estructurado para matching más estricto."
                    if not salvage_local_plausible
                    else "Se mantiene como soporte contextual; no desplaza la familia salvage mientras el rescate local siga plausible."
                ],
            )
        add_snapshot(
            "PSMA_SRT_like",
            "matched" if patient.get("imaging") else "partial",
            ["PSMA-SRT"],
            ["Escenario post-RP/BCR", "Ruta de rescate"],
            ["La comparabilidad mejora cuando existe imagen dirigida/documentada."],
        )

    if state in MHSPC_STATES:
        matched_trials = ["ARANOTE"]
        notes = ["Cohorte mHSPC comparable por intensificación hormonal y duración del beneficio."]
        if state in {"mcspc_high_volume_sync", "mcspc_high_volume"}:
            matched_trials = ["ARANOTE", "ARASENS", "PEACE-1"]
            notes = ["Cohorte mHSPC de alto volumen sincrónica comparable por intensificación y backbone trial-like."]
        elif state == "mcspc_high_volume_metachronous":
            matched_trials = ["ARANOTE", "ARASENS"]
            notes = ["Cohorte mHSPC de alto volumen metacrónica comparable; PEACE-1 no se prioriza como backbone principal."]
        add_snapshot(
            "ARANOTE_ARASENS_PEACE1_like",
            "matched",
            matched_trials,
            [state, management_track],
            notes,
        )

    if state == "m1_crpc":
        if hrr_status == "positive" or brca2_status == "positive":
            add_snapshot(
                "TALAPRO2_like",
                "matched",
                ["TALAPRO-2"],
                ["HRR/BRCA pathway positive", "m1CRPC"],
                ["Perfil biomarcado comparable con vía PARP + ARPI."],
            )
        if psma_positive == "positive" and prior_arpi and not prior_docetaxel:
            add_snapshot(
                "PSMAfore_like",
                "matched",
                ["PSMAfore"],
                ["PSMA positivo", "post-ARPI", "pre-taxano"],
                ["El longitudinal sugiere comparabilidad con radioligando post-ARPI pre-taxano."],
            )
        if bone_dominant:
            add_snapshot(
                "PEACE3_like",
                "matched",
                ["PEACE-3"],
                ["Enfermedad ósea dominante"],
                ["La cohorte es comparable para endpoints óseos y SSE."],
            )
    snapshots.sort(key=lambda item: TRIAL_FAMILY_PRIORITY.index(item["benchmark_family"]) if item["benchmark_family"] in TRIAL_FAMILY_PRIORITY else 99)
    return snapshots


def _summarize_current_course(state: str, outcome_events: list[dict[str, Any]], pending: list[dict[str, Any]], response_state: dict[str, Any]) -> str:
    event_types = {item.get("event_type") for item in outcome_events}
    if any(item.get("status_key", "").endswith("crpc_confirmation") for item in pending):
        if "radiographic_progression" in event_types:
            return "Progresión radiográfica bajo ADT con adjudicación formal de CRPC pendiente."
        return "Progresión bajo ADT pendiente de adjudicación formal de CRPC."
    if "visceral_progression" in event_types:
        return "Curso de enfermedad con progresión visceral adjudicada."
    if "radiographic_progression" in event_types:
        return "Curso de enfermedad con progresión radiográfica adjudicada."
    if "high_risk_bcr" in event_types:
        return "Recurrencia bioquímica de alto riesgo en ventana de rescate."
    if "salvage_window_open" in event_types:
        return "Escenario postlocal con ventana de rescate abierta."
    if "psa90_achieved" in event_types:
        return "Respuesta bioquímica profunda durante terapia sistémica."
    if "psa50_achieved" in event_types:
        return "Respuesta bioquímica temprana en curso."
    if response_state.get("label") and response_state.get("label") != "Sin respuesta adjudicada":
        return f"Respuesta actual: {response_state.get('label')}."
    return f"Curso de enfermedad bajo seguimiento adjudicable para {state}."


def _last_adjudicated_event(outcome_events: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        [item for item in outcome_events if item.get("event_date")],
        key=lambda item: str(item.get("event_date") or ""),
        reverse=True,
    )
    return ordered[0] if ordered else {}


def _outcome_summary(outcome_events: list[dict[str, Any]]) -> dict[str, Any]:
    by_axis: dict[str, int] = {}
    provisional = 0
    for item in outcome_events:
        axis = str(item.get("axis") or "general")
        by_axis[axis] = by_axis.get(axis, 0) + 1
        if item.get("provisional"):
            provisional += 1
    return {
        "total": len(outcome_events),
        "provisional": provisional,
        "confirmed": len(outcome_events) - provisional,
        "by_axis": by_axis,
    }


def _milestone_plan(outcome_events: list[dict[str, Any]], pending: list[dict[str, Any]], state: str, management_track: str) -> list[dict[str, Any]]:
    milestones = [
        {
            "milestone_key": item.get("event_key"),
            "title": item.get("summary"),
            "event_type": item.get("event_type"),
            "event_date": item.get("event_date"),
            "status": "provisional" if item.get("provisional") else "confirmed",
            "axis": item.get("axis"),
            "decision_impact": item.get("decision_impact"),
        }
        for item in outcome_events
    ]
    milestones.extend(
        {
            "milestone_key": item.get("status_key"),
            "title": item.get("title"),
            "event_type": "pending_adjudication",
            "event_date": "",
            "status": "pending",
            "axis": item.get("decision_domain"),
            "decision_impact": item.get("rationale"),
        }
        for item in pending
    )
    milestones.sort(key=lambda item: (str(item.get("event_date") or "9999-12-31"), str(item.get("title") or "")))
    return milestones


def _pending_to_tasks(pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_key": item.get("status_key"),
            "title": item.get("title"),
            "summary": item.get("rationale"),
            "status": item.get("status", "pending"),
            "required": True,
            "action_mode": item.get("action_type", "capture"),
            "fields_to_capture": list(item.get("fields_to_capture") or []),
            "capture_block": item.get("capture_block", ""),
            "decision_domain": item.get("decision_domain", ""),
            "expected_document_type": item.get("expected_document_type", ""),
            "recommended_action": item.get("recommended_action", ""),
        }
        for item in pending
    ]


def build_disease_course_bundle(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not patient or not patient.get("identity"):
        return {}

    latest_assessment = latest_assessment or patient.get("latest_assessment") or {}
    reconciliation = build_reconciled_state(patient, latest_assessment)
    operational_state = state or latest_assessment.get("state") or patient.get("prior_history", {}).get("current_state") or ""
    resolved_state = state or reconciliation.get("reconciled_state") or latest_assessment.get("state") or patient.get("prior_history", {}).get("current_state") or "diagnostic_workup"
    resolved_track = management_track or reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
    assessment_input = dict(latest_assessment.get("input_snapshot") or {})
    merged = merge_record_into_assessment_payload(assessment_input, patient)
    clinical_facts = _build_clinical_facts(patient, merged, resolved_state, resolved_track)
    response_state = _build_response_state(patient, resolved_state, merged)
    outcome_events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    if resolved_state in POSTLOCAL_STATES:
        postlocal_events, postlocal_pending = _build_postlocal_outcomes(patient, resolved_state, resolved_track, merged)
        outcome_events.extend(postlocal_events)
        pending.extend(postlocal_pending)
    if resolved_state == "adt_progression_verification":
        adt_events, adt_pending = _build_adt_progression_outcomes(patient, resolved_state, resolved_track, merged, response_state)
        outcome_events.extend(adt_events)
        pending.extend(adt_pending)
    if resolved_state in MHSPC_STATES:
        mhspc_events, mhspc_pending = _build_mhspc_outcomes(patient, resolved_state, resolved_track, merged, response_state)
        outcome_events.extend(mhspc_events)
        pending.extend(mhspc_pending)
    if resolved_state in {"m0_crpc", "m1_crpc"}:
        crpc_events, crpc_pending = _build_crpc_outcomes(patient, resolved_state, resolved_track, merged, response_state)
        outcome_events.extend(crpc_events)
        pending.extend(crpc_pending)
    benchmark_state = resolved_state
    if resolved_state == "adt_progression_verification" and operational_state == "m1_crpc":
        benchmark_state = "m1_crpc"
        supplemental_events, supplemental_pending = _build_crpc_precision_pathway_outcomes(
            patient,
            benchmark_state,
            resolved_track,
            merged,
        )
        existing_event_types = {str(item.get("event_type") or "") for item in outcome_events}
        for item in supplemental_events:
            if str(item.get("event_type") or "") not in existing_event_types:
                outcome_events.append(item)
        existing_pending_keys = {str(item.get("status_key") or "") for item in pending}
        for item in supplemental_pending:
            if str(item.get("status_key") or "") not in existing_pending_keys:
                pending.append(item)

    outcome_events = sorted(
        outcome_events,
        key=lambda item: (str(item.get("event_date") or ""), str(item.get("event_type") or "")),
        reverse=True,
    )
    line_context = _derive_line_context(patient, merged)
    survival_input = _build_survival_input(patient, merged, resolved_state, line_context, outcome_events)
    try:
        survival_status = SurvivalEndpointService.compute_endpoints(survival_input, benchmark_state).to_dict()
    except Exception:
        survival_status = {"endpoints": [], "active_endpoints": {}, "published_context": {}}
    benchmark_snapshots = _build_benchmark_snapshots(patient, benchmark_state, resolved_track, merged, outcome_events)
    trial_comparable_endpoints = _build_trial_comparable_endpoints(
        patient,
        benchmark_state,
        line_context,
        outcome_events,
        response_state,
        survival_status,
        benchmark_snapshots,
        merged,
    )
    current_profile = benchmark_snapshots[0] if benchmark_snapshots else {}
    last_event = _last_adjudicated_event(outcome_events)
    pending = sorted(pending, key=lambda item: (str(item.get("severity") or ""), str(item.get("title") or "")))
    summary = _outcome_summary(outcome_events)
    return {
        "engine_version": ENGINE_VERSION,
        "state": resolved_state,
        "management_track": resolved_track,
        "clinical_facts": clinical_facts,
        "outcome_events": outcome_events,
        "outcome_events_summary": summary,
        "pending_adjudications": pending,
        "pending_adjudication_tasks": _pending_to_tasks(pending),
        "current_response_state": response_state,
        "current_course_status": _summarize_current_course(resolved_state, outcome_events, pending, response_state),
        "last_adjudicated_event": last_event,
        "trial_comparable_endpoints": trial_comparable_endpoints,
        "benchmark_snapshots": benchmark_snapshots,
        "current_trial_comparable_profile": current_profile,
        "milestone_plan": _milestone_plan(outcome_events, pending, resolved_state, resolved_track),
        "outcome_anchor": {
            "event_key": last_event.get("event_key", ""),
            "event_type": last_event.get("event_type", ""),
            "event_date": last_event.get("event_date", ""),
            "source_priority": last_event.get("source_priority", ""),
        },
        "survival_status": survival_status,
    }


def build_cohort_benchmark_aggregate(patient_records: list[dict[str, Any]]) -> dict[str, Any]:
    bundles = [
        build_disease_course_bundle(
            patient,
            state=str((patient.get("latest_assessment") or {}).get("state") or ""),
        )
        for patient in patient_records
        if patient and patient.get("identity")
    ]
    family_summary: dict[str, dict[str, Any]] = {}
    endpoint_availability: dict[str, dict[str, int]] = {}
    for bundle in bundles:
        for snapshot in bundle.get("benchmark_snapshots", []):
            family = str(snapshot.get("benchmark_family") or "unknown")
            summary = family_summary.setdefault(
                family,
                {"matched": 0, "partial": 0, "not_comparable": 0, "states": {}, "trials": set()},
            )
            status = str(snapshot.get("eligibility_status") or "not_comparable")
            summary[status] = summary.get(status, 0) + 1
            state = str(snapshot.get("scenario_state") or "")
            if state:
                summary["states"][state] = summary["states"].get(state, 0) + 1
            for trial in snapshot.get("matched_trials", []) or []:
                summary["trials"].add(trial)
        for endpoint in bundle.get("trial_comparable_endpoints", []):
            endpoint_key = str(endpoint.get("endpoint_key") or "")
            if not endpoint_key:
                continue
            status_summary = endpoint_availability.setdefault(endpoint_key, {"complete": 0, "ongoing": 0, "missing": 0})
            status = str(endpoint.get("status") or "missing")
            status_summary[status] = status_summary.get(status, 0) + 1

    normalized_family_summary = {}
    for family, summary in family_summary.items():
        normalized_family_summary[family] = {
            "matched": summary.get("matched", 0),
            "partial": summary.get("partial", 0),
            "not_comparable": summary.get("not_comparable", 0),
            "states": summary.get("states", {}),
            "matched_trials": sorted(summary.get("trials", set())),
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine_version": ENGINE_VERSION,
        "total_patients": len(bundles),
        "benchmark_families": normalized_family_summary,
        "endpoint_availability": endpoint_availability,
    }
