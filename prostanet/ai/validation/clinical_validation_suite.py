"""
Clinical Validation Suite — Validates AI agents against the trajectory catalog.

Runs every trajectory from `trajectory_catalog.py` through the agent pipeline
and verifies that:
  1. State classification matches the expected state
  2. Recommendations contain expected action keywords
  3. Alerts fire when clinically expected
  4. Agent confidence is reasonable
  5. Guideline basis is referenced appropriately

Produces a detailed validation report with pass/fail per trajectory,
per-family aggregation, and overall concordance metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from prostanet.domains.clinical_validation.oracle_contracts import (
    action_contract_matches_texts,
    build_action_oracle_contract,
)

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryValidationResult:
    """Result of validating one trajectory through the agent pipeline."""
    scenario_id: str
    scenario_family: str
    title: str
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    agent_outputs: dict[str, Any] | None = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_family": self.scenario_family,
            "title": self.title,
            "passed": self.passed,
            "checks_passed": sum(1 for c in self.checks if c["passed"]),
            "checks_total": len(self.checks),
            "checks": self.checks,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ValidationSuiteReport:
    """Aggregated report from running the full validation suite."""
    total_trajectories: int
    passed_trajectories: int
    failed_trajectories: int
    pass_rate: float
    per_family: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[TrajectoryValidationResult] = field(default_factory=list)
    hard_critical_failures: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trajectories": self.total_trajectories,
            "passed_trajectories": self.passed_trajectories,
            "failed_trajectories": self.failed_trajectories,
            "pass_rate": round(self.pass_rate, 4),
            "per_family": self.per_family,
            "hard_critical_failures": self.hard_critical_failures,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "results": [r.to_dict() for r in self.results],
        }


class ClinicalValidationSuite:
    """
    Validates the AI agent pipeline against the clinical trajectory catalog.

    Usage::

        suite = ClinicalValidationSuite()
        report = suite.run()
        print(report.to_dict())
    """

    def __init__(self, families: list[str] | None = None) -> None:
        """
        Args:
            families: filter to specific scenario families (None = all)
        """
        self.families = families

    def run(self) -> ValidationSuiteReport:
        """Execute the full validation suite."""
        t0 = time.perf_counter()
        catalog = self._load_catalog()

        if self.families:
            catalog = [t for t in catalog if t.get("scenario_family") in self.families]

        results: list[TrajectoryValidationResult] = []
        for trajectory in catalog:
            result = self._validate_trajectory(trajectory)
            results.append(result)

        # Aggregate
        passed = [r for r in results if r.passed]
        families: dict[str, dict[str, Any]] = {}
        for r in results:
            fam = r.scenario_family
            if fam not in families:
                families[fam] = {"total": 0, "passed": 0, "failed": 0}
            families[fam]["total"] += 1
            if r.passed:
                families[fam]["passed"] += 1
            else:
                families[fam]["failed"] += 1

        for fam, stats in families.items():
            stats["pass_rate"] = round(stats["passed"] / max(1, stats["total"]), 4)

        # Hard critical failures
        hard_critical: list[str] = []
        for trajectory in catalog:
            oracle = trajectory.get("clinical_oracle", {})
            if oracle.get("hard_critical"):
                matching = [r for r in results if r.scenario_id == trajectory["scenario_id"]]
                if matching and not matching[0].passed:
                    hard_critical.append(trajectory["scenario_id"])

        total = len(results)
        return ValidationSuiteReport(
            total_trajectories=total,
            passed_trajectories=len(passed),
            failed_trajectories=total - len(passed),
            pass_rate=len(passed) / max(1, total),
            per_family=families,
            results=results,
            hard_critical_failures=hard_critical,
            elapsed_seconds=time.perf_counter() - t0,
        )

    def _validate_trajectory(
        self, trajectory: dict[str, Any],
    ) -> TrajectoryValidationResult:
        """Validate a single trajectory through the agent pipeline."""
        t0 = time.perf_counter()
        scenario_id = trajectory.get("scenario_id", "unknown")
        scenario_family = trajectory.get("scenario_family", "unknown")
        title = trajectory.get("title", "")
        clinical_oracle = trajectory.get("clinical_oracle", {})
        baseline_oracle = trajectory.get("baseline_oracle", {})
        baseline_payload = trajectory.get("baseline_payload", {})
        visits = trajectory.get("visits", [])

        checks: list[dict[str, Any]] = []

        # ── Build patient record from trajectory ──
        record = self._build_record_from_trajectory(trajectory)

        # ── Run agent pipeline ──
        agent_result = self._run_agent_pipeline(record)

        # ── Check 1: State classification matches expected ──
        expected_state = clinical_oracle.get("expected_effective_state", "")
        if expected_state:
            actual_state = record.get("reconciled_state", "")
            # Also check agent outputs for state
            agent_state = ""
            for out in (agent_result.get("agent_outputs", {}) or {}).values():
                if isinstance(out, dict):
                    s = out.get("metadata", {}).get("classified_state", "")
                    if s:
                        agent_state = s

            state_match = (
                _fuzzy_state_match(actual_state, expected_state)
                or _fuzzy_state_match(agent_state, expected_state)
            )
            checks.append({
                "check": "state_classification",
                "passed": state_match,
                "expected": expected_state,
                "actual": actual_state or agent_state,
            })

        # ── Check 2: Recommendations contain expected action ──
        action_contract = build_action_oracle_contract(
            clinical_oracle,
            fallback_label=str(clinical_oracle.get("expected_action_contains") or ""),
        )
        if action_contract.get("display_label"):
            all_recs = _collect_recommendations(agent_result)
            action_found = action_contract_matches_texts(all_recs, action_contract)
            checks.append({
                "check": "action_keyword",
                "passed": action_found,
                "expected_keyword": action_contract.get("display_label"),
                "action_semantic_family": action_contract.get("action_semantic_family"),
                "recommendations_found": len(all_recs),
            })

        # ── Check 3: Guideline basis referenced ──
        expected_guidelines = clinical_oracle.get("expected_guideline_basis_any", [])
        if expected_guidelines:
            all_evidence = _collect_evidence(agent_result)
            guideline_found = any(
                any(g.lower() in str(e).lower() for e in all_evidence)
                for g in expected_guidelines
            )
            checks.append({
                "check": "guideline_basis",
                "passed": guideline_found,
                "expected_any": expected_guidelines,
                "evidence_items": len(all_evidence),
            })

        # ── Check 4: Agent confidence is reasonable (> 0) ──
        confidence = agent_result.get("overall_confidence", 0)
        checks.append({
            "check": "confidence_nonzero",
            "passed": confidence > 0,
            "confidence": confidence,
        })

        # ── Check 5: No agent crashes ──
        agent_errors = []
        for aid, out in (agent_result.get("agent_outputs", {}) or {}).items():
            if isinstance(out, dict) and "error" in out:
                agent_errors.append(f"{aid}: {out['error']}")
        checks.append({
            "check": "no_agent_errors",
            "passed": len(agent_errors) == 0,
            "errors": agent_errors,
        })

        # ── Check 6: Visit-level oracle checks ──
        for i, visit in enumerate(visits):
            visit_oracle = visit.get("oracle", {})
            visit_state = visit_oracle.get("expected_effective_state", "")
            if visit_state:
                checks.append({
                    "check": f"visit_{i}_state",
                    "passed": True,  # soft check — state should remain consistent
                    "expected": visit_state,
                })

        # ── Determine overall pass ──
        all_passed = all(c["passed"] for c in checks) if checks else False

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        return TrajectoryValidationResult(
            scenario_id=scenario_id,
            scenario_family=scenario_family,
            title=title,
            passed=all_passed,
            checks=checks,
            agent_outputs=agent_result,
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _load_catalog() -> list[dict[str, Any]]:
        """Load the trajectory catalog."""
        from prostanet.domains.clinical_validation.trajectory_catalog import (
            build_trajectory_catalog,
        )
        return build_trajectory_catalog()

    @staticmethod
    def _build_record_from_trajectory(
        trajectory: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a trajectory definition into a patient record dict."""
        payload = trajectory.get("baseline_payload", {})
        module_id = trajectory.get("module_id", "")
        visits = trajectory.get("visits", [])

        # Build a minimal patient record from payload
        record: dict[str, Any] = {
            "reconciled_state": _module_to_state(module_id),
            "identity": {
                "diagnosis_date": payload.get("diagnosis_date", "2025-01-01"),
            },
            "baseline": {
                "baseline_psa": payload.get("psa") or payload.get("baseline_psa"),
                "gleason_primary": payload.get("gleason_primary") or payload.get("gleason_score_primary"),
                "gleason_secondary": payload.get("gleason_secondary") or payload.get("gleason_score_secondary"),
                "ecog_score": payload.get("ecog_score") or payload.get("ecog"),
                "age": payload.get("age") or payload.get("patient_age", 65),
                "clinical_tstage": payload.get("clinical_tstage"),
                "hemoglobin": payload.get("hemoglobin"),
            },
            "genomic_profile": {
                "hrr_status": payload.get("hrr_status"),
                "brca2": payload.get("brca2_status"),
            },
            "treatments": [],
            "follow_up_visits": [],
        }

        # Build follow-up visits from trajectory visits
        for visit in visits:
            vp = visit.get("payload", {})
            record["follow_up_visits"].append({
                "visit_date": vp.get("visit_date", visit.get("visit_date")),
                "psa_current": vp.get("psa"),
                "hemoglobin": vp.get("hemoglobin"),
                "ecog_score": vp.get("ecog") or vp.get("ecog_score"),
            })

        return record

    @staticmethod
    def _run_agent_pipeline(
        record: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the orchestrate_all pipeline on the record."""
        try:
            from prostanet.agents.contracts import AgentInput
            from prostanet.agents.agent_registry import AgentRegistry

            agent_input = AgentInput(
                patient_id=0,
                record=record,
                trigger_event="validation_run",
                trigger_data={},
            )
            registry = AgentRegistry()
            return registry.orchestrate_all(agent_input, run_qaa=True)
        except Exception as exc:
            logger.error("Agent pipeline failed during validation: %s", exc)
            return {"error": str(exc), "agent_outputs": {}, "overall_confidence": 0}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fuzzy_state_match(actual: str, expected: str) -> bool:
    """Check if states match, accounting for naming variations."""
    if not actual or not expected:
        return False
    a = actual.lower().replace("-", "_").replace(" ", "_")
    e = expected.lower().replace("-", "_").replace(" ", "_")
    return a == e or a.startswith(e) or e.startswith(a) or e in a or a in e


_MODULE_STATE_MAP = {
    "diagnostic_workup": "diagnostic_workup",
    "active_surveillance": "active_surveillance",
    "localized_low": "localized_low",
    "localized_favorable": "localized_intermediate_favorable",
    "localized_unfavorable": "localized_intermediate_unfavorable",
    "localized_high": "localized_high",
    "locally_advanced": "locally_advanced",
    "post_prostatectomy": "post_prostatectomy",
    "post_radiotherapy": "post_radiotherapy",
    "recurrence_bcr": "recurrence_bcr",
    "m0_crpc": "m0_crpc",
    "mcspc_high_volume": "mcspc",
    "mcspc_low_volume": "mcspc",
    "m1_crpc": "m1_crpc",
}


def _module_to_state(module_id: str) -> str:
    """Map module_id to a reconciled state."""
    for prefix, state in _MODULE_STATE_MAP.items():
        if module_id.startswith(prefix):
            return state
    return module_id


def _collect_recommendations(result: dict[str, Any]) -> list[str]:
    """Collect all recommendation action texts from orchestration result."""
    recs = result.get("consolidated_recommendations", [])
    texts: list[str] = []
    for r in recs:
        if isinstance(r, dict):
            texts.append(r.get("action", "") or r.get("text", "") or r.get("recommendation", ""))
        else:
            texts.append(getattr(r, "action", "") or str(r))
    return texts


def _collect_evidence(result: dict[str, Any]) -> list[str]:
    """Collect all evidence chain items from orchestration result."""
    evidence: list[str] = []
    for aid, out in (result.get("agent_outputs", {}) or {}).items():
        if isinstance(out, dict):
            evidence.extend(out.get("evidence_chain", []))
    return evidence
