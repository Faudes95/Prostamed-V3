from __future__ import annotations

from typing import Any

from prostanet.ai.config import get_ai_config
from prostanet.agents.quality_assurance_agent import QualityAssuranceAgent
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    build_decision_input_requirements,
)
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.patient_tracking.vertical_runtime import (
    YES_VALUES,
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
    enrich_recommendation_with_metastatic_summary,
    guideline_basis_from_result,
    is_present,
    normalize_text,
    prepend_metastatic_context,
    resolve_vertical_status,
    run_vertical_qa_validation,
    safe_float,
)
from prostanet.domains.post_radiotherapy_or_local_salvage.service import (
    PostRadiotherapyOrLocalSalvageService,
)
from prostanet.engine.confidence_scoring import ConfidenceScorer
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.phoenix import evaluate_phoenix


POST_RT_VERTICAL_STATES = {"recurrence_bcr", "post_radiotherapy_or_local_salvage", "post_radiotherapy_followup"}


def _has_post_rp_context(patient: dict[str, Any]) -> bool:
    if patient.get("surgery"):
        return True
    bcr = patient.get("bcr") or {}
    primary_treatment = normalize_text(bcr.get("primary_treatment")).upper()
    if primary_treatment in {"RP", "POST_RP", "RADICAL PROSTATECTOMY", "PROSTATECTOMY"}:
        return True
    for source in (
        patient.get("baseline") or {},
        (patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {},
        ((patient.get("latest_assessment") or {}).get("input_snapshot") or {}),
    ):
        if not isinstance(source, dict):
            continue
        if normalize_text(source.get("prior_prostatectomy")).lower() in YES_VALUES:
            return True
        if is_present(source.get("rp_date")) or is_present(source.get("prostatectomy_date")):
            return True
    return False


def _has_post_rt_context(patient: dict[str, Any], payload: dict[str, Any]) -> bool:
    if _has_post_rp_context(patient):
        return False
    if patient.get("radiation") or patient.get("radiotherapy_courses") or patient.get("radiotherapy_courses_detailed"):
        return True
    bcr = patient.get("bcr") or {}
    primary_treatment = normalize_text(bcr.get("primary_treatment")).upper()
    if primary_treatment in {"RT", "RADIOTHERAPY", "EBRT", "RT_PRIMARY"}:
        return True
    for source in (
        patient.get("baseline") or {},
        (patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {},
        payload,
        ((patient.get("latest_assessment") or {}).get("input_snapshot") or {}),
    ):
        if not isinstance(source, dict):
            continue
        if normalize_text(source.get("prior_radiation")).lower() in YES_VALUES:
            return True
        if is_present(source.get("radiation_date")) or is_present(source.get("prior_rt_date")):
            return True
    return False


def _concordance_label(rule_action: str, overlay_action: str) -> str:
    rule_text = normalize_text(rule_action).lower()
    overlay_text = normalize_text(overlay_action).lower()
    if not rule_text or not overlay_text:
        return "rule_only"
    if rule_text == overlay_text:
        return "concordant"
    if "salvage" in rule_text and "salvage" in overlay_text:
        return "adjacent"
    if "sist" in rule_text and "sist" in overlay_text:
        return "adjacent"
    if "restag" in rule_text and "restag" in overlay_text:
        return "adjacent"
    return "discordant"


class PostRTSalvageCopilotService:
    service_id = "post_rt_salvage_copilot"

    def __init__(self) -> None:
        self.post_rt_service = PostRadiotherapyOrLocalSalvageService()
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
        resolved_track = effective_management_track or "post_rt"
        latest_state = normalize_text(
            (latest_assessment or {}).get("state")
            or (patient.get("latest_assessment") or {}).get("state")
            or effective_state
            or (patient.get("prior_history") or {}).get("current_state")
        )
        resolved_state = "post_radiotherapy_or_local_salvage"
        runtime_patient = build_runtime_patient(patient, longitudinal_bundle)
        payload = build_runtime_payload(
            runtime_patient,
            latest_assessment,
            effective_state=resolved_state,
            overlay_keys={
                "prior_radiation",
                "salvage_local_feasible",
                "local_salvage_candidate",
                "psa_current",
                "psa",
                "psa_nadir",
                "phoenix_delta",
                "psadt_months",
                "prior_rt_modality",
                "prior_rt_dose",
                "prior_rt_fields",
                "biopsy_proven_local_recurrence",
                "biopsy_date",
                "biopsy_grade_group",
                "mpmri_done",
                "mpmri_date",
                "mpmri_localized_recurrence",
                "local_recurrence_site",
                "urinary_burden",
                "incontinence_burden",
                "urethral_stricture_history",
                "bowel_burden",
                "rectal_toxicity_grade",
                "prostate_volume",
                "anesthesia_surgical_fitness",
                "salvage_expertise_available",
                "psma_pet_done",
                "psma_positive",
                "psma_radioligand",
                "psma_stage_after_psma",
                "psma_uptake_pattern",
                "psma_rads_score",
            },
        )
        if not flags.get("ENABLE_POST_RT_SALVAGE_COPILOT"):
            return self._disabled_bundle(state=resolved_state, runtime_mode=runtime_mode, status="disabled")
        if latest_state not in POST_RT_VERTICAL_STATES or not _has_post_rt_context(runtime_patient, payload):
            return self._disabled_bundle(state=resolved_state, runtime_mode=runtime_mode, status="not_applicable")

        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if any(
                is_present(payload.get(key))
                for key in ("psma_pet_done", "psma_positive", "psma_stage_after_psma", "psma_rads_score", "psma_uptake_pattern")
            )
            else dict(runtime_patient.get("psma_structured_profile") or build_psma_structured_profile(runtime_patient))
        )
        psma_impact = build_psma_decision_impact(
            psma_profile,
            state=resolved_state,
            management_track=resolved_track,
            patient=runtime_patient,
        )
        module_result = self.post_rt_service.evaluate(payload)
        requirements = decision_input_requirements or build_decision_input_requirements(
            runtime_patient,
            effective_state=resolved_state,
            effective_management_track=resolved_track,
            latest_assessment=latest_assessment or patient.get("latest_assessment"),
            next_best_action=(longitudinal_bundle or {}).get("next_best_action") or {},
        )
        blocking_inputs = build_blocking_input_groups(requirements)
        failure_definition = dict(module_result.get("post_rt_failure_definition") or {})
        local_salvage_ranking = list(module_result.get("post_rt_local_salvage_ranking") or [])
        transition_bundle = dict(module_result.get("post_rt_transition_bundle") or {})
        module_schedule_overlay = dict(module_result.get("post_rt_schedule_overlay") or {})
        compatibility_bundle = dict(module_result.get("post_rt_salvage_bundle") or {})
        transition_status = str(transition_bundle.get("transition_status") or compatibility_bundle.get("post_rt_course") or "restate_before_decision")
        transition_reasons = transition_bundle.get("trigger_reasons") or []
        transition_reason = str(
            (
                transition_reasons[0]
                if isinstance(transition_reasons, list) and transition_reasons
                else compatibility_bundle.get("reason")
                or failure_definition.get("rationale")
                or ""
            )
        )

        # Phoenix hard-gate (NCCN PROS-10 cat 1, EAU 2026 §6.3.2). Aun cuando
        # el pipeline longitudinal pudo haber derivado una transición más
        # avanzada, no liberamos ningún carril de salvage si el paciente no
        # cumple nadir + 2 ng/mL, no hay biopsia de recurrencia local, ni
        # confirmación radiográfica local.
        phoenix_gate = evaluate_phoenix(payload)
        biopsy_proven = normalize_text(payload.get("biopsy_proven_local_recurrence")).lower() in YES_VALUES
        radiographic_local = normalize_text(payload.get("mpmri_localized_recurrence")).lower() in YES_VALUES
        phoenix_gate_blocked = (
            not phoenix_gate.threshold_reached
            and not biopsy_proven
            and not radiographic_local
        )
        if phoenix_gate_blocked:
            transition_status = "pending_confirmation"
            transition_reason = (
                "PSA aún no cumple criterio Phoenix (nadir + 2 ng/mL) y no hay "
                "biopsia confirmatoria ni recurrencia local en imagen. No liberar "
                "rescate: mantener PSA cada 3 meses hasta confirmar el umbral."
            )

        course = {
            "post_rt_course": transition_status,
            "window_status": transition_status,
            "reason": transition_reason,
        }
        metastatic_composition_summary = build_shared_metastatic_summary(payload)
        histopathology_summary = build_histopathology_summary(payload)
        guideline_basis = guideline_basis_from_result(module_result)
        rule_action = {
            "pending_confirmation": "Confirmar fallo post-RT y reestadificar antes de salvage",
            "restate_before_decision": "Completar reestadificación post-RT antes de decidir modalidad de rescate",
            "local_salvage_candidate": "Sostener salvage local post-RT",
            "mdt_candidate": "Discutir MDT / SBRT guiada por PSMA o salvage multimodal",
            "redirect_systemic": "Redirigir fuera de salvage local aislado y completar vía sistémica",
        }.get(transition_status, "Reevaluar ruta post-RT")
        rule_based_recommendation = enrich_recommendation_with_metastatic_summary(
            {
                "source": "rule_based_primary",
                "recommended_action": rule_action,
                "recommendation_family": "post_rt_salvage",
                "rationale": " ".join(
                    item for item in [
                        transition_reason,
                        str(module_result.get("nccn_primary", {}).get("recommendation") or "").strip(),
                    ] if item
                ).strip() or "La capa rule-based post-RT sigue siendo la fuente primaria de verdad clínica.",
                "guideline_basis": guideline_basis,
            },
            metastatic_composition_summary,
        )
        ai_advisory_overlay = self._build_ai_overlay(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            course=course,
            blocking_inputs=blocking_inputs,
            psma_impact=psma_impact,
        )
        qa_validation = run_vertical_qa_validation(
            self.qa_agent,
            runtime_patient,
            reconciled_state=resolved_state,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            evidence_basis=guideline_basis,
            agent_id="post_rt_salvage_copilot_overlay",
            confidence_score=70.0 if ai_advisory_overlay.get("available") else 50.0,
        )
        confidence = build_model_like_confidence(
            self.confidence_scorer,
            runtime_patient,
            action=ai_advisory_overlay.get("recommended_action") or rule_based_recommendation.get("recommended_action"),
            guideline_result=module_result,
        )
        final_presented_recommendation = build_final_presented_recommendation(
            runtime_mode=runtime_mode,
            rule_based_recommendation=rule_based_recommendation,
            ai_overlay=ai_advisory_overlay,
            qa_validation=qa_validation,
            blocking_groups=blocking_inputs,
            advisory_source="post_rt_salvage_copilot_advisory",
            rationale="Overlay AI presentado porque pasó QA, no hay blockers duros y la recomendación sigue siendo concordante con la ruta primaria post-RT.",
        )
        final_presented_recommendation = enrich_recommendation_with_metastatic_summary(
            final_presented_recommendation,
            metastatic_composition_summary,
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
            effective_state=resolved_state,
            phenotype_state=resolved_state,
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
        dominant_local_option = dict(
            transition_bundle.get("dominant_local_option")
            or compatibility_bundle.get("dominant_local_option")
            or {}
        )
        local_salvage_pathway = {
            "visible": (
                transition_status in {"local_salvage_candidate", "mdt_candidate"}
                and not phoenix_gate_blocked
            ),
            "status": transition_status,
            "recommended_path": (
                dominant_local_option.get("name")
                or ("MDT / SBRT guiada por PSMA" if transition_status == "mdt_candidate" else "")
            ),
            "rationale": transition_reason,
            "dominant_local_option": dominant_local_option,
            "ranking": local_salvage_ranking[:5],
            "phoenix_gate_blocked": phoenix_gate_blocked,
        }
        restaging_strategy = {
            "status": transition_status,
            "label": {
                "pending_confirmation": "Cerrar Phoenix / confirmación local",
                "restate_before_decision": "Completar reestadificación antes de modalidad local",
                "local_salvage_candidate": "La vía local sigue abierta tras reestadificación",
                "mdt_candidate": "Patrón oligorrecurrente dirigido por PSMA",
                "redirect_systemic": "La PSMA ya cerró la vía local curativa",
            }.get(transition_status, "Ruta post-RT"),
            "psma_available": bool(psma_profile.get("available")),
            "structured_complete": bool(psma_profile.get("structured_complete")),
            "clinical_pattern": normalize_text(psma_impact.get("clinical_pattern")),
            "phoenix_status": failure_definition.get("phoenix_status"),
            "failure_confirmation_basis": failure_definition.get("failure_confirmation_basis"),
            "recommended_action": transition_reason,
        }
        systemic_redirection_status = {
            "redirected": transition_status == "redirect_systemic",
            "reason": transition_reason,
        }
        schedule_overlay = {
            **module_schedule_overlay,
            "post_rt_salvage_window_status": transition_status,
            "cadence_adjustment_reasons": list(module_schedule_overlay.get("cadence_adjustment_reasons") or [])
            + [group.get("group_label") for group in blocking_inputs if group.get("required_fields")][:2],
        }
        return {
            **compatibility_bundle,
            "enabled": True,
            "available": True,
            "show_card": True,
            "service_id": self.service_id,
            "status": status,
            "state_family": resolved_state,
            "raw_state": latest_state,
            "runtime_mode": runtime_mode,
            "rule_based_source_of_truth": True,
            "effective_state": resolved_state,
            "effective_management_track": resolved_track,
            "histopathology_summary": histopathology_summary,
            "post_rt_course": transition_status,
            "post_rt_salvage_window_status": transition_status,
            "phoenix_gate": phoenix_gate.to_dict(),
            "phoenix_gate_blocked": phoenix_gate_blocked,
            "restaging_strategy": restaging_strategy,
            "local_salvage_pathway": local_salvage_pathway,
            "systemic_redirection_status": systemic_redirection_status,
            "metastatic_composition_summary": metastatic_composition_summary,
            "rule_based_recommendation": rule_based_recommendation,
            "ai_advisory_overlay": ai_advisory_overlay,
            "final_presented_recommendation": final_presented_recommendation,
            "blocking_inputs": blocking_inputs,
            "blocked_by_overlay": blocked_by_overlay,
            "qa_validation": qa_validation,
            "guideline_basis": guideline_basis,
            "evidence_basis_current_visit": evidence_basis_current_visit,
            "confidence": confidence,
            "why_changed_today": prepend_metastatic_context(
                self._why_changed_today(payload, course, psma_impact),
                metastatic_composition_summary,
            ),
            "decision_delta_since_last_visit": decision_delta_since_last_visit,
            "post_rt_failure_definition": failure_definition,
            "post_rt_local_salvage_ranking": local_salvage_ranking,
            "post_rt_transition_bundle": transition_bundle,
            "post_rt_schedule_overlay": schedule_overlay,
            "trigger_event": trigger_event or "longitudinal_refresh",
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
            "effective_state": state,
            "effective_management_track": "",
            "histopathology_summary": "",
            "post_rt_course": "",
            "post_rt_salvage_window_status": "",
            "restaging_strategy": {},
            "local_salvage_pathway": {},
            "systemic_redirection_status": {},
            "post_rt_failure_definition": {},
            "post_rt_local_salvage_ranking": [],
            "post_rt_transition_bundle": {},
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
            "post_rt_schedule_overlay": {},
        }

    def _resolve_course(self, payload: dict[str, Any], psma_impact: dict[str, Any]) -> dict[str, str]:
        salvage_feasible = normalize_text(payload.get("salvage_local_feasible")).lower() in YES_VALUES
        pattern = normalize_text(psma_impact.get("clinical_pattern"))
        psadt_raw = payload.get("psadt_months")
        psadt = float(psadt_raw) if psadt_raw not in (None, "", "0") else None
        if pattern == "diseminado" or normalize_text(payload.get("psma_stage_after_psma")) in {"M1a", "M1b", "M1c"}:
            return {
                "post_rt_course": "redirect_systemic",
                "window_status": "redirect_systemic",
                "reason": "El patrón PSMA diseminado desplaza la plausibilidad de rescate local aislado.",
            }
        # PSADT <3 meses: urgencia sistémica independientemente del patrón PSMA (Freedland 2005)
        if psadt is not None and psadt < 3:
            return {
                "post_rt_course": "redirect_systemic",
                "window_status": "urgent_systemic_evaluation",
                "reason": "PSADT <3 meses post-RT indica alta probabilidad de metástasis oculta (>80% a 5 años). Evaluación sistémica urgente recomendada.",
            }
        if pattern == "oligometastatic":
            reason = "La PSMA de bajo burden mantiene una ruta oligometastásica contextual."
            if psadt is not None and psadt < 12:
                reason += f" Nota: PSADT de {psadt:.1f} meses sugiere cinética agresiva — considerar intensificación sistémica concomitante."
            return {
                "post_rt_course": "mdt_candidate",
                "window_status": "mdt_candidate",
                "reason": reason,
            }
        if salvage_feasible and normalize_text(payload.get("psma_pet_done")) in YES_VALUES:
            reason = "La recurrencia post-RT sigue siendo localmente rescatable."
            if psadt is not None and psadt < 6:
                reason += f" Precaución: PSADT de {psadt:.1f} meses — considerar evaluación sistémica complementaria al salvage local."
            return {
                "post_rt_course": "local_salvage_candidate",
                "window_status": "local_salvage_candidate",
                "reason": reason,
            }
        return {
            "post_rt_course": "restate_before_decision",
            "window_status": "restate_before_decision",
            "reason": "Todavía falta reestadificación suficiente antes de cerrar la vía post-RT.",
        }

    def _build_rule_based_recommendation(self, module_result: dict[str, Any], course: dict[str, str], psma_impact: dict[str, Any]) -> dict[str, Any]:
        nccn = dict(module_result.get("nccn_primary") or {})
        structured = dict((module_result.get("report_sections") or {}).get("structured_summary") or {})
        rationale_bits = list(structured.get("fundamentos_personalizados") or [])[:3]
        if course["window_status"] == "redirect_systemic":
            rationale_bits.append("El patrón de imagen ya no sostiene rescate local aislado.")
        elif course["window_status"] == "local_salvage_candidate":
            rationale_bits.append("La ruta de rescate local sigue siendo visible y clínicamente defendible.")
        elif psma_impact.get("clinical_pattern") == "oligometastatic":
            rationale_bits.append("La PSMA de bajo burden permite discutir MDT o salvage multimodal.")
        return {
            "source": "rule_based_primary",
            "recommended_action": normalize_text(nccn.get("recommendation") or structured.get("trayectoria_recomendada")),
            "recommendation_family": "post_rt_salvage",
            "rationale": " ".join(normalize_text(item) for item in rationale_bits if normalize_text(item)) or "La capa rule-based sigue siendo la fuente primaria de verdad clínica.",
            "guideline_basis": guideline_basis_from_result(module_result),
        }

    def _build_ai_overlay(
        self,
        *,
        runtime_mode: str,
        rule_based_recommendation: dict[str, Any],
        course: dict[str, str],
        blocking_inputs: list[dict[str, Any]],
        psma_impact: dict[str, Any],
    ) -> dict[str, Any]:
        if course["window_status"] == "redirect_systemic":
            recommended_action = "Redirigir fuera de salvage local aislado y completar vía sistémica"
        elif course["window_status"] == "mdt_candidate":
            recommended_action = "Discutir MDT / salvage multimodal guiado por PSMA"
        elif course["window_status"] == "local_salvage_candidate":
            recommended_action = "Mantener revisión de salvage local post-RT"
        else:
            recommended_action = "Completar reestadificación post-RT antes de decidir rescate"
        hard_blocked = any(group.get("required_fields") for group in blocking_inputs)
        concordance = _concordance_label(rule_based_recommendation.get("recommended_action"), recommended_action)
        status = "shadow-blocked" if hard_blocked else "advisory_candidate" if runtime_mode == "advisory" and concordance != "discordant" else "shadow"
        reasons = [
            "La recomendación AI permanece en shadow hasta que QA apruebe y no existan blockers duros."
            if runtime_mode == "shadow"
            else "La recomendación AI solo puede presentarse si sigue siendo concordante con la ruta primaria."
        ]
        if psma_impact.get("clinical_pattern") == "diseminado":
            reasons.append("La PSMA diseminada bloquea rescate local aislado.")
        return {
            "available": True,
            "status": status,
            "recommended_action": recommended_action,
            "recommendation_family": "post_rt_salvage",
            "concordance_label": concordance,
            "shadow_reasons": reasons,
        }

    def _restaging_strategy(
        self,
        payload: dict[str, Any],
        psma_profile: dict[str, Any],
        psma_impact: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "psma_available": bool(psma_profile.get("available")),
            "structured_complete": bool(psma_profile.get("structured_complete")),
            "clinical_pattern": normalize_text(psma_impact.get("clinical_pattern")),
            "recommended_action": "Usar PSMA estructurada para distinguir rescate local, MDT o redirección sistémica."
            if psma_profile.get("available")
            else "Completar imagen dirigida o PSMA antes de cerrar la conducta post-RT.",
        }

    def _local_salvage_pathway(self, course: dict[str, str], psma_impact: dict[str, Any]) -> dict[str, Any]:
        visible = course["window_status"] in {"local_salvage_candidate", "mdt_candidate"}
        if course["window_status"] == "mdt_candidate":
            path = "MDT / salvage multimodal guiado por PSMA"
        elif course["window_status"] == "local_salvage_candidate":
            path = "Revisión estructurada de rescate local post-RT"
        else:
            path = ""
        return {
            "visible": visible,
            "recommended_path": path,
            "rationale": course["reason"] or normalize_text(psma_impact.get("rationale")),
        }

    def _why_changed_today(self, payload: dict[str, Any], course: dict[str, str], psma_impact: dict[str, Any]) -> list[str]:
        notes = []
        psa = safe_float(payload.get("psa_current") or payload.get("psa"))
        psadt = safe_float(payload.get("psadt_months"))
        if psa is not None:
            notes.append(f"PSA actual {psa:g} ng/mL.")
        if psadt is not None:
            notes.append(f"PSADT actual {psadt:.1f} meses.")
        if normalize_text(payload.get("psma_stage_after_psma")):
            notes.append(f"PSMA estructurado {payload.get('psma_stage_after_psma')}.")
        notes.append(course["reason"])
        if normalize_text(psma_impact.get("rationale")):
            notes.append(normalize_text(psma_impact.get("rationale")))
        return notes[:5]

    def _schedule_overlay(self, course: dict[str, str], blocking_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        if course["window_status"] == "redirect_systemic":
            cadence = ["Staging sistémico", "Tumor board para redirección terapéutica"]
            primary_intent = "Abandonar rescate local aislado"
        elif course["window_status"] == "local_salvage_candidate":
            cadence = ["Definir salvage local", "Correlación imagen-factibilidad"]
            primary_intent = "Sostener rescate local post-RT"
        elif course["window_status"] == "mdt_candidate":
            cadence = ["Discusión MDT", "PSMA y burden comparables"]
            primary_intent = "Cerrar ruta oligometastásica contextual"
        else:
            cadence = ["Completar reestadificación", "Documentar factibilidad de salvage"]
            primary_intent = "No decidir rescate sin imagen suficiente"
        blockers = [group.get("group_label") for group in blocking_inputs if group.get("required_fields")]
        return {
            "schedule_primary_intent": primary_intent,
            "cadence_adjustment_reasons": cadence + blockers[:2],
            "recommended_events": cadence[:3],
            "post_rt_salvage_window_status": course["window_status"],
        }


def build_post_rt_salvage_bundle(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    trigger_event: str = "",
) -> dict[str, Any]:
    return PostRTSalvageCopilotService().evaluate(
        patient,
        effective_state=effective_state,
        effective_management_track=effective_management_track,
        latest_assessment=latest_assessment,
        longitudinal_bundle=longitudinal_bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )


__all__ = [
    "PostRTSalvageCopilotService",
    "build_post_rt_salvage_bundle",
    "POST_RT_VERTICAL_STATES",
]
