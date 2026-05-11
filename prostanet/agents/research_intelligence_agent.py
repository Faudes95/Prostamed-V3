"""
Research Intelligence Agent (RIA) — "El Investigador".

Identifies clinical trial eligibility, finds similar patients in the
institutional cohort, and generates epidemiological insights.

Triggered on: state_transition, visit_recorded (periodic)
"""

from __future__ import annotations

import logging
from typing import Any

from clinical_scores import docetaxel_fitness

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import (
    AgentInput,
    AgentOutput,
    AgentRecommendation,
    AgentAlert,
)

logger = logging.getLogger(__name__)


# Trial eligibility criteria (simplified from pivotal trials)
ACTIVE_TRIALS: list[dict[str, Any]] = [
    {
        "trial_id": "TALAPRO-2",
        "name": "Talazoparib + Enzalutamida",
        "target_states": ["m1_crpc"],
        "required": {"hrr_positive": True},
        "exclusions": {"prior_parp": True},
        "evidence": "TALAPRO-2 Phase III",
    },
    {
        "trial_id": "PSMAfore",
        "name": "177Lu-PSMA-617 pre-taxano",
        "target_states": ["m1_crpc"],
        "required": {"psma_positive": True},
        "exclusions": {"prior_lu177": True},
        "evidence": "PSMAfore Phase III",
    },
    {
        "trial_id": "EMBARK",
        "name": "Enzalutamida + ADT en BCR alto riesgo",
        "target_states": ["recurrence_bcr"],
        "required": {"psadt_under_9": True},
        "exclusions": {},
        "evidence": "EMBARK Phase III",
    },
    {
        "trial_id": "PEACE-V/STORM",
        "name": "SBRT oligometastásico + tratamiento sistémico",
        "target_states": ["mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo"],
        "required": {"metastasis_count_le_5": True},
        "exclusions": {},
        "evidence": "PEACE-V/STORM Phase III",
    },
    {
        "trial_id": "ARASENS-like",
        "name": "Triplete: ADT + Docetaxel + Darolutamida",
        "target_states": ["mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"],
        "required": {"ecog_le_1": True, "fit_for_docetaxel": True},
        "exclusions": {},
        "evidence": "ARASENS Phase III",
    },
]


class ResearchIntelligenceAgent(AgentBase):
    """
    Identifies trial eligibility, similar patients, and
    generates epidemiological insights.
    """

    agent_id = "research_intelligence_agent"
    agent_role = "Inteligencia de investigación: ensayos clínicos, pacientes similares, epidemiología"
    trigger_events = ["state_transition", "visit_recorded"]

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        record = agent_input.record
        state = record.get("reconciled_state", "")
        evidence_chain: list[str] = []
        recommendations: list[AgentRecommendation] = []
        alerts: list[AgentAlert] = []

        # ── 1: Trial Eligibility Matching ──
        eligible_trials = self._match_trials(record, state)
        evidence_chain.append(f"Ensayos clínicos elegibles: {len(eligible_trials)}")

        for trial in eligible_trials:
            recommendations.append(AgentRecommendation(
                action=f"Evaluar elegibilidad: {trial['name']}",
                category="research",
                priority="standard",
                evidence_basis=[trial["evidence"]],
            ))

        # ── 2: Cohort Similarity Search ──
        similar_outcomes = self._find_similar_patients(record, state)
        if similar_outcomes:
            evidence_chain.append(
                f"Pacientes similares encontrados: {similar_outcomes.get('count', 0)}"
            )
            if similar_outcomes.get("median_os_months"):
                evidence_chain.append(
                    f"OS mediana en cohorte similar: {similar_outcomes['median_os_months']} meses"
                )

        # ── 3: Epidemiological Insights ──
        epi_insights = self._generate_epi_insights(record, state)
        if epi_insights:
            evidence_chain.extend(epi_insights)

        # ── 4: Research Readiness Alert ──
        completeness = self._assess_research_readiness(record)
        if completeness < 0.6:
            alerts.append(AgentAlert(
                alert_type="research_readiness",
                severity="info",
                title=f"Completitud de datos: {completeness:.0%}",
                message="Datos insuficientes para análisis de investigación completo.",
                category="data_quality",
                recommended_action="Completar campos faltantes para habilitación de investigación",
            ))

        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
            recommendations=recommendations,
            confidence_score=70.0,
            evidence_chain=evidence_chain,
            alerts=alerts,
            metadata={
                "eligible_trials": eligible_trials,
                "similar_outcomes": similar_outcomes,
                "research_readiness": completeness,
            },
        )

    @staticmethod
    def _match_trials(record: dict, state: str) -> list[dict[str, Any]]:
        """Match patient against active trial eligibility criteria."""
        matched: list[dict[str, Any]] = []
        baseline = record.get("baseline", {}) or {}
        genomic = record.get("genomic_profile", {}) or {}
        latest_followup = record.get("latest_followup", {}) or {}
        trial_context = {**baseline, **latest_followup}
        docetaxel_bundle = docetaxel_fitness(trial_context)

        for trial in ACTIVE_TRIALS:
            if state not in trial["target_states"]:
                continue

            # Check required criteria
            required = trial.get("required", {})
            eligible = True

            if required.get("hrr_positive") and genomic.get("hrr_status") != "positive":
                eligible = False
            if required.get("psma_positive") and not baseline.get("psma_positive"):
                eligible = False
            if required.get("ecog_le_1"):
                ecog = baseline.get("ecog_score")
                if ecog is not None:
                    try:
                        if int(float(ecog)) > 1:
                            eligible = False
                    except (TypeError, ValueError):
                        pass
            if trial.get("trial_id") == "ARASENS-like":
                eligible = eligible and str((docetaxel_bundle.get("docetaxel_trial_fit") or {}).get("arasens_like") or "no") == "matched"
            if required.get("metastasis_count_le_5"):
                count = baseline.get("metastasis_count")
                if count is not None:
                    try:
                        if int(float(count)) > 5:
                            eligible = False
                    except (TypeError, ValueError):
                        pass

            # Check exclusions
            exclusions = trial.get("exclusions", {})
            if exclusions.get("prior_parp"):
                treatments = record.get("treatments") or []
                for tx in treatments:
                    if "parp" in str(tx.get("drug_scheme", "")).lower():
                        eligible = False

            if eligible:
                matched.append(trial)

        return matched

    @staticmethod
    def _find_similar_patients(
        record: dict, state: str
    ) -> dict[str, Any] | None:
        """
        Find similar patients in the institutional cohort using dynamic cohorting
        and compute comparative effectiveness outcomes.
        """
        try:
            from prostanet.domains.research_intelligence.cohort_progression_analytics import (
                CohortProgressionAnalytics,
            )
            analytics = CohortProgressionAnalytics()

            # Get treatment outcomes for this state
            tx_outcomes = analytics.compute_treatment_outcomes(state=state, min_n=1)
            n_treatments = len(tx_outcomes.get("treatment_outcomes", {}))
            total = tx_outcomes.get("total_records", 0)

            # Get cohort overview
            overview = analytics.compute_overview()
            cohort_size = overview.get("total_patients", 0)

            # State-specific patients
            state_dist = overview.get("state_distribution", {})
            n_in_state = state_dist.get(state, 0)

            return {
                "count": n_in_state,
                "total_cohort": cohort_size,
                "treatment_outcomes_available": n_treatments,
                "treatment_records": total,
                "available": True,
                "source": "institutional_cohort",
            }
        except Exception as exc:
            return {"count": 0, "available": False, "error": str(exc)}

    @staticmethod
    def _generate_epi_insights(record: dict, state: str) -> list[str]:
        """Generate epidemiological insights for the patient's context."""
        insights: list[str] = []
        baseline = record.get("baseline", {}) or {}
        age = baseline.get("age")
        if age:
            try:
                age_val = int(float(age))
                if age_val < 55:
                    insights.append(
                        "Paciente joven (<55 años): considerar factores hereditarios (BRCA2, Lynch)"
                    )
                elif age_val > 80:
                    insights.append(
                        "Paciente >80 años: priorizar mortalidad competitiva y calidad de vida"
                    )
            except (TypeError, ValueError):
                pass
        return insights

    @staticmethod
    def _assess_research_readiness(record: dict) -> float:
        """Assess completeness of data for research purposes (0-1)."""
        required_fields = [
            ("identity", "diagnosis_date"),
            ("baseline", "baseline_psa"),
            ("baseline", "ecog_score"),
            ("baseline", "gleason_primary"),
        ]
        present = 0
        for section, field in required_fields:
            val = record.get(section, {})
            if isinstance(val, dict) and val.get(field):
                present += 1
        return present / len(required_fields) if required_fields else 0.0
