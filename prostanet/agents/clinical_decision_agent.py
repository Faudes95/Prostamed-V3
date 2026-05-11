"""
Clinical Decision Agent (CDA) — "El Médico Tratante".

The primary decision-making agent that synthesizes all patient data,
clinical calculators, AI model predictions, and guideline evaluations
into actionable clinical recommendations.

Triggered on: visit_recorded, lab_value_updated, imaging_completed, assessment_created
"""

from __future__ import annotations

import logging
from typing import Any

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import (
    AgentInput,
    AgentOutput,
    AgentRecommendation,
    AgentAlert,
)

logger = logging.getLogger(__name__)


class ClinicalDecisionAgent(AgentBase):
    """
    Synthesizes ALL patient information and recommends next clinical action,
    exactly as an oncologic urologist would in consultation.
    """

    agent_id = "clinical_decision_agent"
    agent_role = "Copiloto clínico: sintetiza datos, calculadoras, modelos AI y guías para recomendar la siguiente acción"
    trigger_events = [
        "visit_recorded",
        "lab_value_updated",
        "imaging_completed",
        "assessment_created",
    ]

    def __init__(
        self,
        model_registry: Any | None = None,
        module_registry: Any | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.module_registry = module_registry

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        record = agent_input.record
        state = record.get("reconciled_state", "")
        evidence_chain: list[str] = []
        recommendations: list[AgentRecommendation] = []
        alerts: list[AgentAlert] = []
        data_gaps: list[str] = []
        ai_predictions: dict[str, Any] = {}

        # ── Step 1: Extract key clinical parameters ──
        baseline = record.get("baseline", {}) or {}
        identity = record.get("identity", {}) or {}
        follow_ups = record.get("follow_ups") or []

        psa = self._latest_psa(baseline, follow_ups)
        ecog = self._latest_ecog(baseline, follow_ups)

        evidence_chain.append(
            f"Estado clínico actual: {state}"
        )
        evidence_chain.append(
            f"PSA actual: {psa:.2f} ng/mL, ECOG: {ecog}"
        )

        # ── Step 2: Run clinical calculators (rule-based) ──
        calculator_results = self._run_calculators(record, state)
        if calculator_results:
            evidence_chain.append(
                f"Calculadoras ejecutadas: {', '.join(calculator_results.keys())}"
            )

        # ── Step 3: AI State Transition Prediction ──
        if self.model_registry:
            try:
                state_model = self.model_registry.get("state_transition")
                if state_model:
                    pred = state_model.predict(record)
                    ai_predictions["state_transition"] = pred.values
                    evidence_chain.append(
                        f"Predicción AI transición: {pred.values.get('predicted_state')} "
                        f"({pred.values.get('predicted_state_probability', 0):.0%}) "
                        f"en {pred.values.get('time_to_transition_months', '?')} meses"
                    )

                    # Alert if progression predicted with high probability
                    prob = pred.values.get("predicted_state_probability", 0)
                    predicted = pred.values.get("predicted_state", "")
                    if prob > 0.6 and predicted != state:
                        alerts.append(AgentAlert(
                            alert_type="ai_state_prediction",
                            severity="warning" if prob < 0.8 else "critical",
                            title=f"Predicción de transición a {predicted}",
                            message=(
                                f"El modelo predice transición a {predicted} "
                                f"con {prob:.0%} de probabilidad en "
                                f"{pred.values.get('time_to_transition_months', '?')} meses."
                            ),
                            category="ai_prediction",
                            recommended_action="Considerar re-estadificación anticipada",
                            probability=prob,
                        ))
            except Exception as exc:
                logger.debug("State transition prediction failed: %s", exc)

        # ── Step 4: Guideline-based evaluation ──
        guideline_result: dict[str, Any] = {}
        if self.module_registry and state:
            try:
                payload = self._build_evaluation_payload(record)
                guideline_result = self.module_registry.evaluate_module(state, payload)
                evidence_chain.append(
                    f"Evaluación guideline ({state}): {guideline_result.get('nccn_label', 'N/A')}"
                )
            except Exception as exc:
                logger.debug("Guideline evaluation failed: %s", exc)

        # ── Step 5: Build recommendations ──
        eligible_treatments = guideline_result.get("eligible_treatments", [])
        if eligible_treatments:
            for i, tx in enumerate(eligible_treatments[:3]):
                rec = AgentRecommendation(
                    action=tx.get("label", tx.get("regimen_code", "Tratamiento")),
                    category="treatment",
                    priority="high" if i == 0 else "standard",
                    evidence_basis=tx.get("evidence_tags", []),
                )

                # Enrich with AI prediction if available
                if self.model_registry:
                    try:
                        response_model = self.model_registry.get("treatment_response")
                        if response_model:
                            resp_pred = response_model.predict(record, regimen_id=i)
                            rec.predicted_outcome = resp_pred.values
                    except Exception:
                        pass

                recommendations.append(rec)
        else:
            # Default recommendation based on state
            recommendations.append(AgentRecommendation(
                action=self._default_action(state),
                category="monitoring",
                priority="standard",
                evidence_basis=["NCCN 5.2026", "EAU 2026"],
            ))

        # ── Step 6: Identify data gaps ──
        data_gaps = self._identify_data_gaps(record, state)

        # ── Step 7: Compute confidence ──
        confidence = self._compute_confidence(
            record, guideline_result, ai_predictions, data_gaps
        )

        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
            recommendations=recommendations,
            confidence_score=confidence,
            evidence_chain=evidence_chain,
            data_gaps=data_gaps,
            alerts=alerts,
            metadata={
                "state": state,
                "calculator_results": calculator_results,
                "ai_predictions": ai_predictions,
                "guideline_label": guideline_result.get("nccn_label"),
            },
        )

    @staticmethod
    def _latest_psa(baseline: dict, follow_ups: list) -> float:
        if follow_ups:
            last = follow_ups[-1]
            psa = last.get("psa_current") or last.get("psa")
            if psa:
                try:
                    return float(psa)
                except (TypeError, ValueError):
                    pass
        return float(baseline.get("baseline_psa", 0) or 0)

    @staticmethod
    def _latest_ecog(baseline: dict, follow_ups: list) -> int:
        if follow_ups:
            ecog = follow_ups[-1].get("ecog")
            if ecog is not None:
                try:
                    return int(float(ecog))
                except (TypeError, ValueError):
                    pass
        try:
            return int(float(baseline.get("ecog_score", 1) or 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _run_calculators(record: dict, state: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        try:
            from clinical_scores import capra_score
            baseline = record.get("baseline", {}) or {}
            score = capra_score(
                age=float(baseline.get("age") or 65),
                psa=float(baseline.get("baseline_psa") or 10),
                gleason_primary=int(float(baseline.get("gleason_primary") or 3)),
                gleason_secondary=int(float(baseline.get("gleason_secondary") or 3)),
                clinical_tstage=str(baseline.get("clinical_tstage") or "T1c"),
                pct_cores_positive=float(baseline.get("pct_cores_positive") or 0),
            )
            results["capra"] = score
        except Exception:
            pass
        return results

    @staticmethod
    def _build_evaluation_payload(record: dict) -> dict:
        payload: dict[str, Any] = {}
        payload.update(record.get("identity", {}) or {})
        payload.update(record.get("baseline", {}) or {})
        if record.get("follow_ups"):
            payload.update(record["follow_ups"][-1])
        return payload

    @staticmethod
    def _default_action(state: str) -> str:
        defaults = {
            "diagnostic_workup": "Completar evaluación diagnóstica: biopsia + MRI",
            "localized_initial": "Evaluar opciones: vigilancia activa vs tratamiento local",
            "post_prostatectomy": "Seguimiento PSA cada 3-6 meses",
            "recurrence_bcr": "Re-estadificación con PSMA-PET + evaluación de rescate",
            "adt_progression_verification": "Confirmar testosterona castrada + re-estadificación",
            "m0_crpc": "Evaluar PSADT — si <10m: iniciar ARPI",
            "m1_crpc": "Evaluar biomarcadores: HRR, PSMA, AR-V7 para secuenciación",
        }
        return defaults.get(state, "Continuar seguimiento según protocolo")

    @staticmethod
    def _identify_data_gaps(record: dict, state: str) -> list[str]:
        gaps: list[str] = []
        baseline = record.get("baseline", {}) or {}
        genomic = record.get("genomic_profile", {}) or {}

        if not baseline.get("ecog_score"):
            gaps.append("ECOG score")
        if state in ("m1_crpc", "m0_crpc") and not genomic.get("hrr_status"):
            gaps.append("Perfil genómico HRR")
        if state in ("m1_crpc",) and not baseline.get("psma_positive"):
            gaps.append("PSMA-PET")
        if not baseline.get("hemoglobin"):
            gaps.append("Hemoglobina")
        return gaps

    @staticmethod
    def _compute_confidence(
        record: dict,
        guideline_result: dict,
        ai_predictions: dict,
        data_gaps: list[str],
    ) -> float:
        score = 50.0
        # Data completeness bonus
        score += max(0, 20 - len(data_gaps) * 5)
        # Guideline evaluation exists
        if guideline_result:
            score += 15
        # AI predictions available
        if ai_predictions:
            score += 10
        # Recent follow-up data
        if record.get("follow_ups"):
            score += 5
        return min(100.0, max(0.0, score))
