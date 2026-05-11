"""
Treatment Optimization Agent (TOA) — "El Farmacólogo".

Optimizes treatment selection considering efficacy predictions,
safety profile, drug interactions, formulary availability, and cost.

Triggered on: state_transition, assessment_created
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


class TreatmentOptimizationAgent(AgentBase):
    """
    Optimizes treatment selection by ranking options across efficacy,
    safety, availability, and cost dimensions.
    """

    agent_id = "treatment_optimization_agent"
    agent_role = "Optimización de tratamiento: eficacia, seguridad, DDI, formulario, costo"
    trigger_events = ["state_transition", "assessment_created"]

    def __init__(self, model_registry: Any | None = None) -> None:
        self.model_registry = model_registry

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        record = agent_input.record
        state = record.get("reconciled_state", "")
        evidence_chain: list[str] = []
        recommendations: list[AgentRecommendation] = []
        alerts: list[AgentAlert] = []

        evidence_chain.append(f"Optimización de tratamiento para estado: {state}")

        # ── 1: Get eligible treatments from guideline engine ──
        eligible = self._get_eligible_treatments(state, record)
        evidence_chain.append(f"Tratamientos elegibles: {len(eligible)}")

        # ── 2: DDI Check ──
        concomitant_meds = record.get("baseline", {}).get("concomitant_medications", []) or []
        ddi_results: dict[str, list[dict]] = {}
        try:
            from prostanet.shared.ddi_engine import check_interactions
            for tx in eligible:
                regimen = tx.get("regimen_code", "")
                ddi_alerts = check_interactions(
                    [regimen], concomitant_meds, seizure_history=False
                )
                ddi_results[regimen] = [
                    {"severity": a.severity, "drug_pair": f"{a.drug_a}+{a.drug_b}", "action": a.recommended_action}
                    for a in ddi_alerts
                ]
        except Exception as exc:
            logger.debug("DDI check failed: %s", exc)

        # ── 3: Formulary availability ──
        institution = record.get("identity", {}).get("institution", "imss")
        formulary: dict[str, dict] = {}
        try:
            from prostanet.shared.ddi_engine import check_formulary
            for tx in eligible:
                regimen = tx.get("regimen_code", "")
                formulary[regimen] = check_formulary(regimen, institution)
        except Exception:
            pass

        # ── 4: AI predictions per treatment ──
        ai_outcomes: dict[str, dict] = {}
        if self.model_registry:
            try:
                response_model = self.model_registry.get("treatment_response")
                surv_model = self.model_registry.get("deep_surv")
                for i, tx in enumerate(eligible):
                    regimen = tx.get("regimen_code", "")
                    outcomes: dict[str, Any] = {}
                    if response_model:
                        pred = response_model.predict(record, regimen_id=i)
                        outcomes["response"] = pred.values
                    if surv_model:
                        surv = surv_model.predict(record)
                        outcomes["survival"] = surv.values
                    ai_outcomes[regimen] = outcomes
            except Exception as exc:
                logger.debug("AI treatment prediction failed: %s", exc)

        # ── 5: Rank treatments ──
        ranked = self._rank_treatments(
            eligible, ddi_results, formulary, ai_outcomes, record
        )

        for i, item in enumerate(ranked[:5]):
            regimen = item["regimen_code"]
            rec = AgentRecommendation(
                action=item.get("label", regimen),
                category="treatment",
                priority="high" if i == 0 else "standard",
                evidence_basis=item.get("evidence_tags", []),
                predicted_outcome=item.get("predicted_outcome", {}),
            )
            recommendations.append(rec)

            evidence_chain.append(
                f"#{i+1} {regimen}: score={item.get('composite_score', 0):.0f}/100"
            )

            # DDI alerts
            for ddi in ddi_results.get(regimen, []):
                if ddi["severity"] == "contraindicated":
                    alerts.append(AgentAlert(
                        alert_type="ddi",
                        severity="critical",
                        title=f"Contraindicación DDI: {ddi['drug_pair']}",
                        message=ddi["action"],
                        category="safety",
                    ))

        confidence = 60.0 + (15.0 if ai_outcomes else 0) + (10.0 if formulary else 0)

        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
            recommendations=recommendations,
            confidence_score=min(100.0, confidence),
            evidence_chain=evidence_chain,
            alerts=alerts,
            metadata={
                "ranked_treatments": ranked,
                "ddi_results": ddi_results,
                "formulary": formulary,
            },
        )

    @staticmethod
    def _get_eligible_treatments(state: str, record: dict) -> list[dict[str, Any]]:
        """Get eligible treatments from therapy catalog."""
        try:
            from prostanet.domains.patient_tracking.therapy_catalog import (
                THERAPY_REGIMENS,
                ADVANCED_STATE_SCOPE,
            )
            eligible = []
            for regimen in THERAPY_REGIMENS:
                scope = regimen.get("state_scope", [])
                if state in scope or "advanced" in scope:
                    eligible.append(regimen)
            return eligible
        except Exception:
            return []

    @staticmethod
    def _rank_treatments(
        eligible: list[dict],
        ddi_results: dict[str, list],
        formulary: dict[str, dict],
        ai_outcomes: dict[str, dict],
        record: dict,
    ) -> list[dict[str, Any]]:
        """Rank treatments by composite score: efficacy x safety x availability."""
        ranked = []
        for tx in eligible:
            regimen = tx.get("regimen_code", "")
            score = 50.0

            # DDI penalty
            ddis = ddi_results.get(regimen, [])
            contraindicated = any(d["severity"] == "contraindicated" for d in ddis)
            if contraindicated:
                score -= 50
            score -= len(ddis) * 5

            # Formulary bonus
            form = formulary.get(regimen, {})
            if form.get("available"):
                score += 15
                if form.get("cuadro_basico"):
                    score += 10

            # AI efficacy bonus
            outcomes = ai_outcomes.get(regimen, {})
            response = outcomes.get("response", {})
            psa50 = response.get("psa50_probability", 0)
            if psa50 > 0:
                score += psa50 * 30  # Up to +30 for 100% PSA50

            ranked.append({
                **tx,
                "composite_score": max(0, min(100, score)),
                "ddi_count": len(ddis),
                "contraindicated": contraindicated,
                "formulary_available": form.get("available", False),
                "predicted_outcome": response,
            })

        ranked.sort(key=lambda x: x["composite_score"], reverse=True)
        return ranked
