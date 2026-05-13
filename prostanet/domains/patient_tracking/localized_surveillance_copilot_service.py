from __future__ import annotations

from typing import Any

from prostanet.ai.config import get_ai_config
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.domains.localized_initial.service import LocalizedInitialService
from prostanet.domains.patient_tracking.active_surveillance import (
    ActiveSurveillanceService,
)
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.domains.patient_tracking.vertical_runtime import (
    build_blocking_input_groups,
    build_blocked_by_overlay,
    build_decision_delta_since_last_visit,
    build_evidence_basis_current_visit,
    build_final_presented_recommendation,
    build_histopathology_summary,
    build_model_like_confidence,
    build_runtime_patient,
    build_runtime_payload,
    build_shared_metastatic_summary,
    guideline_basis_from_result,
    is_present,
    normalize_text,
    resolve_vertical_status,
    run_vertical_qa_validation,
    safe_float,
    safe_int,
)
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.feature_flags import resolve_feature_flags


LOCALIZED_VERTICAL_STATES = {"localized_initial"}


def _concordance_label(rule_action: str, overlay_action: str) -> str:
    rule_text = normalize_text(rule_action).lower()
    overlay_text = normalize_text(overlay_action).lower()
    if not rule_text or not overlay_text:
        return "rule_only"
    if rule_text == overlay_text:
        return "concordant"
    if "surveillance" in rule_text and "surveillance" in overlay_text:
        return "adjacent"
    if "radi" in rule_text and "radi" in overlay_text:
        return "adjacent"
    if "prostatect" in rule_text and "prostatect" in overlay_text:
        return "adjacent"
    return "discordant"


class LocalizedSurveillanceCopilotService:
    service_id = "localized_surveillance_copilot"

    def __init__(self) -> None:
        self.localized_service = LocalizedInitialService()
        self.qa_agent = QualityAssuranceAgent()
        self.confidence_scorer = ConfidenceScorer()

    def evaluate(
        self,
        patient: dict[str, Any],
        *,
        effective_state: str = "",
        effective_management_track: str = "",
        latest_assessment: dict[str, Any] | None = None,
        longitudinal_bundle: dict[str, Any] | None = None,
        decision_input_requirements: dict[str, Any] | None = None,
        trigger_event: str = "",
    ) -> dict[str, Any]:
        flags = resolve_feature_flags()
        runtime_mode = get_ai_config().runtime_mode
        latest_state = normalize_text(
            (latest_assessment or {}).get("state")
            or (patient.get("latest_assessment") or {}).get("state")
            or effective_state
            or (patient.get("prior_history") or {}).get("current_state")
        )
        if not flags.get("ENABLE_LOCALIZED_SURVEILLANCE_COPILOT"):
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="disabled")
        applicable = latest_state in LOCALIZED_VERTICAL_STATES or normalize_text(effective_management_track) == "active_surveillance"
        if not applicable:
            return self._disabled_bundle(state=latest_state, runtime_mode=runtime_mode, status="not_applicable")

        runtime_patient = build_runtime_patient(patient, longitudinal_bundle)
        payload = build_runtime_payload(
            runtime_patient,
            latest_assessment,
            effective_state="localized_initial",
            overlay_keys={
                "psa",
                "clinical_tstage",
                "isup_grade",
                "num_cores_positive",
                "total_cores",
                "life_expectancy_years",
                "prior_mpmri_pirads_score",
                "genomic_classifier_result",
                "cribriform_pattern",
                "intraductal_carcinoma",
                "baseline_urinary_qol",
                "baseline_sexual_qol",
                "baseline_bowel_qol",
                "psadt_months",
                "max_core_involvement",
            },
        )
        module_result = self.localized_service.evaluate(payload)
        histopathology_summary = build_histopathology_summary(payload)
        as_patient = {**runtime_patient, **payload, "patient_id": (runtime_patient.get("identity") or {}).get("id")}
        as_context = dict(as_patient.get("active_surveillance") or {})
        management_track_text = normalize_text(payload.get("management_track") or effective_management_track).lower()
        if management_track_text == "active_surveillance" or any(
            is_present(payload.get(key))
            for key in ("confirmatory_biopsy_done", "confirmatory_biopsy_date", "upgrade_detected", "mri_interval_months")
        ):
            as_context.setdefault(
                "enrollment_date",
                normalize_text(payload.get("diagnosis_date") or payload.get("first_positive_biopsy_date") or "2026-01-01"),
            )
            if is_present(payload.get("confirmatory_biopsy_done")):
                as_context["confirmatory_biopsy_done"] = normalize_text(payload.get("confirmatory_biopsy_done")).lower() in {"1", "true", "yes", "si", "sí"}
            if is_present(payload.get("confirmatory_biopsy_date")):
                as_context["confirmatory_biopsy_date"] = payload.get("confirmatory_biopsy_date")
            as_patient["active_surveillance"] = as_context
            if not as_patient.get("mri_facts") and safe_int(payload.get("pirads_score")):
                as_patient["mri_facts"] = [{"pirads_score": safe_int(payload.get("pirads_score"))}]
            if not as_patient.get("biopsies"):
                baseline_isup = safe_int((runtime_patient.get("baseline") or {}).get("isup_grade")) or 1
                current_isup = safe_int(payload.get("isup_grade")) or baseline_isup
                total_cores = safe_int(payload.get("total_cores")) or 12
                positive_cores = safe_int(payload.get("num_cores_positive")) or 0
                percent_positive = (positive_cores / total_cores * 100.0) if total_cores else None
                max_involvement = safe_float(payload.get("max_core_involvement"))
                if max_involvement is not None and max_involvement <= 1.0:
                    max_involvement *= 100.0
                biopsies = [
                    {
                        "biopsy_context": "baseline",
                        "isup_grade": baseline_isup,
                        "highest_isup": baseline_isup,
                    }
                ]
                if as_context.get("confirmatory_biopsy_done") or is_present(payload.get("upgrade_detected")) or positive_cores:
                    biopsies.append(
                        {
                            "biopsy_context": "confirmatory_as",
                            "isup_grade": current_isup,
                            "highest_isup": current_isup,
                            "percent_positive_cores": percent_positive,
                            "max_involvement_pct": max_involvement,
                            "any_cribriform": normalize_text(payload.get("cribriform_pattern")).lower() in {"1", "true", "yes", "si", "sí"},
                            "any_intraductal": normalize_text(payload.get("intraductal_carcinoma")).lower() in {"1", "true", "yes", "si", "sí"},
                        }
                    )
                as_patient["biopsies"] = biopsies
        as_protocol = ActiveSurveillanceService.build_as_protocol(as_patient, "localized_initial")
        as_summary = ActiveSurveillanceService.build_as_summary_for_profile(as_protocol)
        requirements = decision_input_requirements or build_decision_input_requirements(
            runtime_patient,
            effective_state="localized_initial",
            effective_management_track=effective_management_track or ("active_surveillance" if as_summary.get("has_data") else "localized_decision"),
            latest_assessment=latest_assessment or patient.get("latest_assessment"),
            next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
        )
        blocking_inputs = build_blocking_input_groups(requirements)
        localized_track = self._localized_track(module_result, as_summary, payload)
        guideline_basis = guideline_basis_from_result(module_result)
        rule_based_recommendation = self._build_rule_based_recommendation(module_result, localized_track, as_summary)
        ai_advisory_overlay = self._build_ai_overlay(
            runtime_mode=runtime_mode,
            module_result=module_result,
            localized_track=localized_track,
            as_summary=as_summary,
            blocking_inputs=blocking_inputs,
        )
        qa_validation = run_vertical_qa_validation(
            self.qa_agent,
            runtime_patient,
            reconciled_state="localized_initial",
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            evidence_basis=guideline_basis,
            agent_id="localized_surveillance_copilot_overlay",
            category="treatment",
            confidence_score=70.0 if ai_advisory_overlay.get("available") else 50.0,
        )
        confidence = build_model_like_confidence(
            self.confidence_scorer,
            runtime_patient,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            guideline_result=module_result,
            historical_calibration_score=61.0,
        )
        final_presented_recommendation = build_final_presented_recommendation(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            ai_overlay=ai_advisory_overlay,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            advisory_source="localized_surveillance_copilot_advisory",
            rationale="Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta localizada primaria.",
        )
        status = resolve_vertical_status(
            runtime_mode=runtime_mode,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            ai_overlay=ai_advisory_overlay,
        )
        blocked_by_overlay = build_blocked_by_overlay(blocking_groups=blocking_inputs)
        decision_delta_since_last_visit = build_decision_delta_since_last_visit(
            runtime_patient,
            effective_state="localized_initial",
            phenotype_state="localized_initial",
            rule_based_recommendation=rule_based_recommendation,
            final_presented_recommendation=final_presented_recommendation,
            blocking_groups=blocking_inputs,
            blocked_by_overlay=blocked_by_overlay,
        )
        evidence_basis_current_visit = build_evidence_basis_current_visit(
            guideline_basis,
            rule_based_recommendation,
            decision_delta_since_last_visit,
        )
        return {
            "enabled": True,
            "available": True,
            "show_card": True,
            "service_id": self.service_id,
            "status": status,
            "state_family": "localized_initial",
            "raw_state": latest_state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_state": "localized_initial",
            "effective_management_track": effective_management_track or ("active_surveillance" if as_summary.get("has_data") else "localized_decision"),
            "histopathology_summary": histopathology_summary,
            "localized_track": localized_track,
            "active_surveillance_eligibility": list((module_result.get("nccn_primary") or {}).get("multi_protocol_eligible", []) or []),
            "active_surveillance_course": as_summary,
            "upgrade_triggers": list(as_summary.get("active_triggers") or []),
            "nomogram_snapshot": dict((module_result.get("report_sections") or {}).get("nomograms") or {}),
            "preferred_local_strategy": self._preferred_local_strategy(module_result, localized_track),
            "functional_tradeoff_summary": self._functional_tradeoff_summary(payload),
            "metastatic_composition_summary": build_shared_metastatic_summary(payload),
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "blocking_inputs": blocking_inputs,
            "blocked_by_overlay": blocked_by_overlay,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": self._why_changed_today(payload, localized_track, as_summary),
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "localized_schedule_overlay": self._schedule_overlay(localized_track, as_summary, blocking_inputs),
            "trigger_event": trigger_event or "longitudinal_refresh",
            # Faubot LXCVIII.A.3 — propagation keys siempre presentes (test contract)
            "pivotal_contraindication_gates": list(
                module_result.get("pivotal_contraindication_gates") or []
            ),
            "not_recommended": list(module_result.get("not_recommended") or []),
        }

    def _disabled_bundle(self, *, state: str, runtime_mode: str, status: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "available": False,
            "show_card": False,
            "status": status,
            "state_family": state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_management_track": "",
            "histopathology_summary": "",
            "localized_track": "",
            "active_surveillance_eligibility": [],
            "active_surveillance_course": {},
            "upgrade_triggers": [],
            "nomogram_snapshot": {},
            "preferred_local_strategy": {},
            "functional_tradeoff_summary": {},
            "metastatic_composition_summary": {"available": False},
            "rule_based_recommendation": {},
            "ai_advisory_overlay": {"available": False, "status": status},
            "final_presented_recommendation": {},
            "blocking_inputs": [],
            "blocked_by_overlay": [],
            "qa_validation": {"approved": False, "flags": [], "missing_data_alerts": []},
            "guideline_basis": [],
            "evidence_basis_current_visit": [],
            "confidence": {"composite_score": 0.0, "components": {}, "weights_used": {}},
            "why_changed_today": [],
            "decision_delta_since_last_visit": {"available": False},
            "localized_schedule_overlay": {},
            # Faubot LXCVIII.A.3 — propagation keys siempre presentes (test contract)
            "pivotal_contraindication_gates": [],
            "not_recommended": [],
        }

    def _localized_track(self, module_result: dict[str, Any], as_summary: dict[str, Any], payload: dict[str, Any]) -> str:
        upgrade_detected = normalize_text(payload.get("upgrade_detected")).lower() in {"1", "true", "yes", "si", "sí"}
        active_triggers = list(as_summary.get("active_triggers") or [])
        if (
            upgrade_detected
            or as_summary.get("status") == "reclassified"
            or any(str(item.get("trigger_type") or "") == "gleason_upgrade" for item in active_triggers)
            or any(str(item.get("severity") or "") == "reclassification" for item in active_triggers)
        ):
            return "as_exit_due_to_upgrade"
        if as_summary.get("has_data") and any(str(item.get("severity") or "") == "monitoring_intensification" for item in active_triggers):
            return "as_reconfirm"
        if as_summary.get("has_data") and as_summary.get("status") == "active":
            return "stable_active_surveillance"
        life_expectancy = safe_float(payload.get("life_expectancy_years")) or 15.0
        primary = normalize_text((module_result.get("nccn_primary") or {}).get("treatment_principal") or (module_result.get("nccn_primary") or {}).get("tratamiento_principal"))
        if life_expectancy < 10 and "observación" in primary.lower():
            return "observation_limited_life_expectancy"
        return "definitive_local_therapy"

    def _build_rule_based_recommendation(self, module_result: dict[str, Any], localized_track: str, as_summary: dict[str, Any]) -> dict[str, Any]:
        nccn = dict(module_result.get("nccn_primary") or {})
        structured = dict((module_result.get("report_sections") or {}).get("structured_summary") or {})
        rationale_bits = list(structured.get("fundamentos_personalizados") or [])[:3]
        if localized_track == "as_exit_due_to_upgrade":
            rationale_bits.append("El caso ya no debe permanecer en vigilancia activa como conducta principal.")
        if as_summary.get("overdue_count"):
            rationale_bits.append(f"Hay {as_summary.get('overdue_count')} hitos protocolarios vencidos en vigilancia activa.")
        return {
            "source": "rule_based_primary",
            "recommended_action": normalize_text(nccn.get("recommendation") or structured.get("trayectoria_recomendada")),
            "recommendation_family": "localized_management",
            "rationale": " ".join(normalize_text(item) for item in rationale_bits if normalize_text(item)) or "La capa rule-based sigue siendo la fuente primaria de verdad clínica.",
            "guideline_basis": guideline_basis_from_result(module_result),
        }

    def _build_ai_overlay(
        self,
        *,
        runtime_mode: str,
        module_result: dict[str, Any],
        localized_track: str,
        as_summary: dict[str, Any],
        blocking_inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        preferred = self._preferred_local_strategy(module_result, localized_track)
        recommended_action = normalize_text(preferred.get("label") or preferred.get("name"))
        if not recommended_action:
            return {
                "available": False,
                "status": "unavailable",
                "recommended_action": "",
                "concordance_label": "rule_only",
                "shadow_reasons": ["No hay estrategia localizada preferente visible todavía."],
            }
        if localized_track == "as_exit_due_to_upgrade":
            recommended_action = f"Salir de vigilancia activa y discutir {recommended_action}"
        elif localized_track == "as_reconfirm":
            recommended_action = "Mantener vigilancia activa con reconfirmación protocolizada cercana"
        hard_blocked = any(group.get("required_fields") for group in blocking_inputs)
        concordance = _concordance_label(
            normalize_text((module_result.get("nccn_primary") or {}).get("recommendation")),
            recommended_action,
        )
        reasons = [
            "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
            if runtime_mode == "shadow"
            else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
        ]
        if as_summary.get("trigger_count"):
            reasons.append("Existen triggers de vigilancia activa que cambian la intensidad del seguimiento o la necesidad de salida.")
        status = "shadow-blocked" if hard_blocked else "advisory_candidate" if runtime_mode == "advisory" and concordance != "discordant" else "shadow"
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": "localized_management",
            "concordance_label": concordance,
            "shadow_reasons": reasons,
        }

    def _preferred_local_strategy(self, module_result: dict[str, Any], localized_track: str) -> dict[str, Any]:
        treatments = list(module_result.get("eligible_treatments") or [])
        if localized_track in {"stable_active_surveillance", "as_reconfirm"}:
            active = next((item for item in treatments if "active surveillance" in normalize_text(item.get("name")).lower()), None)
            if active:
                return dict(active)
        if localized_track == "as_exit_due_to_upgrade":
            non_as = next((item for item in treatments if "active surveillance" not in normalize_text(item.get("name")).lower()), None)
            if non_as:
                return dict(non_as)
        if localized_track == "observation_limited_life_expectancy":
            observation = next((item for item in treatments if "observation" in normalize_text(item.get("name")).lower()), None)
            if observation:
                return dict(observation)
        return dict(treatments[0] if treatments else {})

    def _functional_tradeoff_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "urinary_qol": safe_float(payload.get("baseline_urinary_qol")),
            "sexual_qol": safe_float(payload.get("baseline_sexual_qol")),
            "bowel_qol": safe_float(payload.get("baseline_bowel_qol")),
            "genomic_classifier_result": normalize_text(payload.get("genomic_classifier_result")),
        }

    def _why_changed_today(self, payload: dict[str, Any], localized_track: str, as_summary: dict[str, Any]) -> list[str]:
        notes = []
        psa = safe_float(payload.get("psa"))
        if psa is not None:
            notes.append(f"PSA actual {psa:g} ng/mL.")
        if normalize_text(payload.get("clinical_tstage")):
            notes.append(f"Estadio clínico {payload.get('clinical_tstage')}.")
        if normalize_text(payload.get("isup_grade")):
            notes.append(f"ISUP {payload.get('isup_grade')}.")
        if as_summary.get("trigger_count"):
            notes.append(f"Triggers de VA activos: {as_summary.get('trigger_count')}.")
        notes.append(f"Track localizado: {localized_track}.")
        return notes[:5]

    def _schedule_overlay(self, localized_track: str, as_summary: dict[str, Any], blocking_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        if localized_track == "stable_active_surveillance":
            cadence = ["PSA seriado", "MRI y biopsia confirmatoria según protocolo"]
            primary_intent = "Sostener vigilancia activa segura"
        elif localized_track == "as_exit_due_to_upgrade":
            cadence = ["Tumor board localizado", "Definir terapia local definitiva"]
            primary_intent = "Salir de vigilancia activa por upgrade o disparador fuerte"
        elif localized_track == "observation_limited_life_expectancy":
            cadence = ["Seguimiento clínico prudente", "Control sintomático y counseling"]
            primary_intent = "Observación estructurada por beneficio local limitado"
        else:
            cadence = ["Definir estrategia local", "Completar inputs pronósticos / funcionales"]
            primary_intent = "Cerrar estrategia localizada"
        blockers = [group.get("group_label") for group in blocking_inputs if group.get("required_fields")]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blockers[:2],
            "recommended_events": cadence[:3],
            "overdue_protocol_items": as_summary.get("overdue_count", 0),
        }


def build_localized_surveillance_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    return LocalizedSurveillanceCopilotService().evaluate(
        patient,
        effective_state=effective_state,
        effective_management_track=effective_management_track,
        latest_assessment=latest_assessment,
        longitudinal_bundle=longitudinal_bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )


__all__ = [
    "LocalizedSurveillanceCopilotService",
    "build_localized_surveillance_bundle",
    "LOCALIZED_VERTICAL_STATES",
]
