"""
Quality Assurance Agent (QAA) — "El Oficial de Seguridad".

Validates every recommendation before presentation by cross-checking
against NCCN/EAU guidelines, contraindications, data completeness,
and clinical safety rules.

Triggered on: Every AgentOutput from CDA before presentation
"""

from __future__ import annotations

import logging
from typing import Any

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import (
    AgentInput,
    AgentOutput,
    AgentAlert,
    QAValidation,
)

logger = logging.getLogger(__name__)


class QualityAssuranceAgent(AgentBase):
    """
    Validates every clinical recommendation before it reaches the user.
    Acts as the safety checkpoint — no recommendation bypasses QA.
    """

    agent_id = "quality_assurance_agent"
    agent_role = "Validación de calidad: verifica concordancia con guías, contraindications, completitud"
    trigger_events = []  # Not event-driven — called explicitly by pipeline

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        """Not used directly — use validate() instead."""
        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
        )

    def validate(
        self,
        cda_output: AgentOutput,
        record: dict[str, Any],
    ) -> QAValidation:
        """
        Validate a CDA recommendation against safety and guideline rules.

        Returns QAValidation with approval status and any flags.
        """
        state = record.get("reconciled_state", "")
        flags: list[str] = []
        missing: list[str] = []
        guideline_concordance: dict[str, bool] = {"nccn": True, "eau": True}

        # ── 1: Check data completeness ──
        missing = self._check_data_completeness(record, state)
        if len(missing) > 3:
            flags.append(
                f"Datos insuficientes: {len(missing)} campos críticos faltantes"
            )

        # ── 2: Validate against NCCN ──
        nccn_issues = self._check_nccn_concordance(cda_output, record, state)
        if nccn_issues:
            guideline_concordance["nccn"] = False
            flags.extend(nccn_issues)

        # ── 3: Validate against EAU ──
        eau_issues = self._check_eau_concordance(cda_output, record, state)
        if eau_issues:
            guideline_concordance["eau"] = False
            flags.extend(eau_issues)

        # ── 4: Check contraindications ──
        contra_flags = self._check_contraindications(cda_output, record)
        flags.extend(contra_flags)

        # ── 5: Check for neuroendocrine/rare histology ──
        escalation_needed, escalation_reason = self._check_escalation(record)

        # ── 6: Verify ECOG fitness for recommended treatments ──
        ecog_flags = self._check_ecog_fitness(cda_output, record)
        flags.extend(ecog_flags)

        approved = len(flags) == 0 and not escalation_needed

        return QAValidation(
            approved=approved,
            flags=flags,
            missing_data_alerts=missing,
            guideline_concordance=guideline_concordance,
            escalation_needed=escalation_needed,
            escalation_reason=escalation_reason,
        )

    @staticmethod
    def _check_data_completeness(record: dict, state: str) -> list[str]:
        """Identify missing critical data for the current state."""
        missing: list[str] = []
        baseline = record.get("baseline", {}) or {}

        # Universal requirements
        if not baseline.get("ecog_score") and baseline.get("ecog_score") != 0:
            missing.append("ECOG score")
        if not baseline.get("baseline_psa") and not record.get("follow_ups"):
            missing.append("PSA actual")

        # State-specific requirements
        if state in ("m1_crpc", "m0_crpc"):
            if not baseline.get("testosterone_baseline"):
                missing.append("Testosterona (confirmación castrada)")
            genomic = record.get("genomic_profile", {}) or {}
            if not genomic.get("hrr_status"):
                missing.append("Estado HRR (panel genómico)")

        if state == "m1_crpc":
            if not baseline.get("conventional_imaging_status"):
                missing.append("Re-estadificación con imagen convencional")

        if state == "localized_initial":
            if not baseline.get("gleason_primary"):
                missing.append("Gleason (biopsia)")

        return missing

    @staticmethod
    def _check_nccn_concordance(
        output: AgentOutput, record: dict, state: str
    ) -> list[str]:
        """Check if recommendations align with NCCN 5.2026."""
        issues: list[str] = []

        for rec in output.recommendations:
            action_lower = rec.action.lower()

            # CRPC without castration confirmation
            if state in ("m0_crpc", "m1_crpc"):
                baseline = record.get("baseline", {}) or {}
                testosterone = baseline.get("testosterone_baseline")
                if testosterone:
                    try:
                        if float(testosterone) > 50:
                            issues.append(
                                "NCCN: Tratamiento de CRPC requiere testosterona castrada (<50 ng/dL)"
                            )
                    except (TypeError, ValueError):
                        pass

            # Docetaxel with poor performance status
            if "docetaxel" in action_lower or "cabazitaxel" in action_lower:
                ecog = record.get("baseline", {}).get("ecog_score")
                performance_status_driver = str(record.get("baseline", {}).get("performance_status_driver") or "").strip().lower()
                if ecog is not None:
                    try:
                        ecog_val = int(float(ecog))
                        if ecog_val > 2:
                            issues.append(
                                "NCCN: Quimioterapia con taxano no recomendada para ECOG >2"
                            )
                        elif ecog_val == 2 and performance_status_driver not in {"cancer_related"}:
                            issues.append(
                                "Docetaxel con ECOG 2 requiere documentar que el deterioro funcional es cáncer-relacionado antes de tratarlo como candidato quimioterapéutico."
                            )
                    except (TypeError, ValueError):
                        pass

        return issues

    @staticmethod
    def _check_eau_concordance(
        output: AgentOutput, record: dict, state: str
    ) -> list[str]:
        """Check if recommendations align with EAU 2026."""
        issues: list[str] = []
        # EAU-specific checks
        for rec in output.recommendations:
            if "lu177" in rec.action.lower() or "lutecio" in rec.action.lower():
                genomic = record.get("genomic_profile", {}) or {}
                psma = record.get("baseline", {}).get("psma_positive")
                if not psma:
                    issues.append(
                        "EAU: Lu-177 PSMA requiere confirmación de PSMA-PET positivo (VISION criteria)"
                    )
        return issues

    @staticmethod
    def _check_contraindications(output: AgentOutput, record: dict) -> list[str]:
        """Check for absolute contraindications."""
        flags: list[str] = []
        baseline = record.get("baseline", {}) or {}

        for rec in output.recommendations:
            action_lower = rec.action.lower()

            # Abiraterone + hepatic impairment
            if "abiraterone" in action_lower or "abiraterona" in action_lower:
                ast = baseline.get("ast")
                alt = baseline.get("alt")
                if ast or alt:
                    try:
                        if float(ast or 0) > 120 or float(alt or 0) > 120:
                            flags.append(
                                "CONTRAINDICACIÓN: Abiraterona con AST/ALT >3x ULN"
                            )
                    except (TypeError, ValueError):
                        pass

            # Enzalutamide + seizure history
            if "enzalutamid" in action_lower:
                if baseline.get("seizure_history"):
                    flags.append(
                        "CONTRAINDICACIÓN: Enzalutamida con antecedente de crisis convulsivas"
                    )

        return flags

    @staticmethod
    def _check_escalation(record: dict) -> tuple[bool, str]:
        """Check if case needs specialist escalation."""
        baseline = record.get("baseline", {}) or {}

        # Neuroendocrine features
        if baseline.get("nepc_suspicion") or baseline.get("variant_histology") == "neuroendocrine":
            return True, "Sospecha de diferenciación neuroendocrina — requiere panel tumor board"

        # Very high PSA with discordant clinical picture
        psa = baseline.get("baseline_psa")
        if psa:
            try:
                if float(psa) > 1000:
                    return True, "PSA >1000 ng/mL — evaluación multimodal urgente"
            except (TypeError, ValueError):
                pass

        return False, ""

    @staticmethod
    def _check_ecog_fitness(output: AgentOutput, record: dict) -> list[str]:
        """Verify patient fitness for recommended treatments."""
        flags: list[str] = []
        baseline = record.get("baseline", {}) or {}
        ecog = baseline.get("ecog_score")

        if ecog is None:
            return flags

        try:
            ecog_val = int(float(ecog))
        except (TypeError, ValueError):
            return flags

        for rec in output.recommendations:
            if rec.category == "treatment" and ecog_val >= 3:
                flags.append(
                    f"ECOG {ecog_val}: Considerar cuidados paliativos antes que tratamiento activo ({rec.action})"
                )

        return flags
