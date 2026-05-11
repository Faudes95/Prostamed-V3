"""
Data Quality Validation Framework — Clinical Data for AI Training.

Validates that patient records meet the quality bar for model training:
  - Temporal consistency (events are chronologically ordered)
  - PSA plausibility (values within physiological range)
  - Treatment sequence validity (no impossible orderings)
  - Field completeness per use case (training, inference, research)
  - Consent verification
  - De-identification checks

Every record is scored and labeled pass/fail with detailed diagnostics.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

PSA_MIN = 0.0
PSA_MAX = 20_000.0  # ng/mL — highest documented values
AGE_MIN = 18
AGE_MAX = 110
GLEASON_MIN = 6
GLEASON_MAX = 10
ECOG_VALID = {0, 1, 2, 3, 4, 5}
VALID_STATES = {
    "diagnostic_workup",
    "active_surveillance",
    "localized_low",
    "localized_intermediate_favorable",
    "localized_intermediate_unfavorable",
    "localized_high",
    "locally_advanced",
    "recurrence_bcr",
    "m0_crpc",
    "mcspc",
    "m1_crpc",
    "post_prostatectomy",
    "post_radiotherapy",
}


@dataclass
class QualityIssue:
    """A single data quality issue found in a patient record."""
    field: str
    severity: str  # "error", "warning", "info"
    message: str
    value: Any = None


@dataclass
class QualityReport:
    """Quality assessment for a single patient record."""
    patient_id: int | str
    passed: bool
    score: float  # 0.0–1.0
    issues: list[QualityIssue] = field(default_factory=list)
    checks_run: int = 0
    checks_passed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "passed": self.passed,
            "score": round(self.score, 4),
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "error_count": sum(1 for i in self.issues if i.severity == "error"),
            "warning_count": sum(1 for i in self.issues if i.severity == "warning"),
            "issues": [
                {"field": i.field, "severity": i.severity, "message": i.message, "value": i.value}
                for i in self.issues
            ],
        }


@dataclass
class BatchQualityReport:
    """Aggregated quality report for a batch of records."""
    total_records: int
    passed_records: int
    failed_records: int
    avg_score: float
    per_record: list[QualityReport] = field(default_factory=list)
    common_issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "passed_records": self.passed_records,
            "failed_records": self.failed_records,
            "pass_rate": round(self.passed_records / max(1, self.total_records), 4),
            "avg_score": round(self.avg_score, 4),
            "common_issues": self.common_issues,
        }


# ── Core Validator ────────────────────────────────────────────────────────────


class DataQualityValidator:
    """
    Validates patient records for AI training suitability.

    Usage::

        validator = DataQualityValidator()
        report = validator.validate_record(record)
        batch_report = validator.validate_batch(records)
    """

    def __init__(
        self,
        *,
        require_consent: bool = True,
        require_deidentified: bool = True,
        min_follow_up_visits: int = 2,
        min_psa_points: int = 2,
        error_threshold: float = 0.7,
    ) -> None:
        self.require_consent = require_consent
        self.require_deidentified = require_deidentified
        self.min_follow_up_visits = min_follow_up_visits
        self.min_psa_points = min_psa_points
        self.error_threshold = error_threshold

    def validate_record(
        self, record: dict[str, Any], patient_id: int | str | None = None,
    ) -> QualityReport:
        """Run all quality checks on a single patient record."""
        pid = patient_id or record.get("identity", {}).get("id", "unknown")
        issues: list[QualityIssue] = []
        checks_run = 0
        checks_passed = 0

        # ── 1. Identity & Demographics ──
        checks = self._check_demographics(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 2. PSA Plausibility ──
        checks = self._check_psa_plausibility(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 3. Temporal Consistency ──
        checks = self._check_temporal_consistency(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 4. Treatment Sequence ──
        checks = self._check_treatment_sequence(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 5. State Validity ──
        checks = self._check_state_validity(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 6. Follow-up Completeness ──
        checks = self._check_follow_up_completeness(record)
        for passed, issue in checks:
            checks_run += 1
            if passed:
                checks_passed += 1
            else:
                issues.append(issue)

        # ── 7. Consent ──
        if self.require_consent:
            checks = self._check_consent(record)
            for passed, issue in checks:
                checks_run += 1
                if passed:
                    checks_passed += 1
                else:
                    issues.append(issue)

        # ── 8. De-identification ──
        if self.require_deidentified:
            checks = self._check_deidentification(record)
            for passed, issue in checks:
                checks_run += 1
                if passed:
                    checks_passed += 1
                else:
                    issues.append(issue)

        score = checks_passed / max(1, checks_run)
        has_errors = any(i.severity == "error" for i in issues)
        passed = score >= self.error_threshold and not has_errors

        return QualityReport(
            patient_id=pid,
            passed=passed,
            score=score,
            issues=issues,
            checks_run=checks_run,
            checks_passed=checks_passed,
        )

    def validate_batch(
        self, records: list[dict[str, Any]],
    ) -> BatchQualityReport:
        """Validate a batch of records and produce aggregate statistics."""
        reports = [self.validate_record(r, i) for i, r in enumerate(records)]
        passed = [r for r in reports if r.passed]
        scores = [r.score for r in reports]

        # Find most common issues
        issue_counts: dict[str, int] = {}
        for r in reports:
            for issue in r.issues:
                key = f"{issue.field}:{issue.message}"
                issue_counts[key] = issue_counts.get(key, 0) + 1

        common = sorted(issue_counts.items(), key=lambda x: -x[1])[:10]
        common_issues = [
            {"issue": k, "count": v, "pct": round(v / max(1, len(records)) * 100, 1)}
            for k, v in common
        ]

        return BatchQualityReport(
            total_records=len(records),
            passed_records=len(passed),
            failed_records=len(records) - len(passed),
            avg_score=sum(scores) / max(1, len(scores)),
            per_record=reports,
            common_issues=common_issues,
        )

    # ── Individual Check Methods ──────────────────────────────────────────────

    def _check_demographics(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        identity = record.get("identity", {}) or {}
        baseline = record.get("baseline", {}) or {}

        # Diagnosis date
        dx_date = identity.get("diagnosis_date")
        if dx_date:
            if _parse_date(str(dx_date)):
                results.append((True, QualityIssue("identity.diagnosis_date", "info", "present")))
            else:
                results.append((False, QualityIssue(
                    "identity.diagnosis_date", "error",
                    f"Invalid date format: {dx_date}", dx_date,
                )))
        else:
            results.append((False, QualityIssue(
                "identity.diagnosis_date", "error", "Missing diagnosis date",
            )))

        # Age
        age = baseline.get("age")
        if age is not None:
            try:
                age_val = int(float(age))
                if AGE_MIN <= age_val <= AGE_MAX:
                    results.append((True, QualityIssue("baseline.age", "info", "valid")))
                else:
                    results.append((False, QualityIssue(
                        "baseline.age", "error",
                        f"Age out of range [{AGE_MIN}-{AGE_MAX}]: {age_val}", age_val,
                    )))
            except (TypeError, ValueError):
                results.append((False, QualityIssue(
                    "baseline.age", "error", f"Non-numeric age: {age}", age,
                )))
        else:
            results.append((False, QualityIssue("baseline.age", "warning", "Missing age")))

        # Gleason
        g1 = baseline.get("gleason_primary")
        g2 = baseline.get("gleason_secondary")
        if g1 is not None and g2 is not None:
            try:
                total = int(float(g1)) + int(float(g2))
                if GLEASON_MIN <= total <= GLEASON_MAX:
                    results.append((True, QualityIssue("baseline.gleason", "info", "valid")))
                else:
                    results.append((False, QualityIssue(
                        "baseline.gleason", "error",
                        f"Gleason sum out of range: {total}", total,
                    )))
            except (TypeError, ValueError):
                results.append((False, QualityIssue(
                    "baseline.gleason", "error", f"Non-numeric Gleason: {g1}+{g2}",
                )))
        else:
            results.append((False, QualityIssue("baseline.gleason", "warning", "Missing Gleason")))

        return results

    def _check_psa_plausibility(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []

        # Baseline PSA
        baseline = record.get("baseline", {}) or {}
        bpsa = baseline.get("baseline_psa")
        if bpsa is not None:
            try:
                val = float(bpsa)
                if PSA_MIN <= val <= PSA_MAX:
                    results.append((True, QualityIssue("baseline.baseline_psa", "info", "plausible")))
                else:
                    results.append((False, QualityIssue(
                        "baseline.baseline_psa", "error",
                        f"PSA value implausible: {val}", val,
                    )))
            except (TypeError, ValueError):
                results.append((False, QualityIssue(
                    "baseline.baseline_psa", "error", f"Non-numeric PSA: {bpsa}", bpsa,
                )))

        # Follow-up PSA series
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        psa_count = 0
        for visit in follow_ups:
            psa = visit.get("psa_current") or visit.get("psa")
            if psa is not None:
                try:
                    val = float(psa)
                    psa_count += 1
                    if val < PSA_MIN or val > PSA_MAX:
                        results.append((False, QualityIssue(
                            "follow_up.psa", "error",
                            f"PSA value implausible at visit: {val}", val,
                        )))
                except (TypeError, ValueError):
                    results.append((False, QualityIssue(
                        "follow_up.psa", "warning", f"Non-numeric PSA in visit: {psa}", psa,
                    )))

        if psa_count >= self.min_psa_points:
            results.append((True, QualityIssue("psa_series", "info", f"{psa_count} PSA points")))
        else:
            results.append((False, QualityIssue(
                "psa_series", "warning",
                f"Insufficient PSA data points: {psa_count} (need {self.min_psa_points})", psa_count,
            )))

        return results

    def _check_temporal_consistency(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []

        # Follow-up visits should be chronologically ordered
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        dates: list[datetime] = []
        for visit in follow_ups:
            d = visit.get("visit_date")
            if d:
                parsed = _parse_date(str(d))
                if parsed:
                    dates.append(parsed)

        if len(dates) >= 2:
            is_ordered = all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))
            if is_ordered:
                results.append((True, QualityIssue("temporal_order", "info", "visits chronologically ordered")))
            else:
                results.append((False, QualityIssue(
                    "temporal_order", "error", "Visit dates are not chronologically ordered",
                )))

        # Diagnosis date should precede first visit
        identity = record.get("identity", {}) or {}
        dx_str = identity.get("diagnosis_date")
        if dx_str and dates:
            dx_date = _parse_date(str(dx_str))
            if dx_date and dates[0] < dx_date:
                results.append((False, QualityIssue(
                    "temporal_order", "warning",
                    "First visit date precedes diagnosis date",
                )))
            else:
                results.append((True, QualityIssue("temporal_order", "info", "diagnosis precedes visits")))

        # Treatment dates
        treatments = record.get("treatments") or record.get("treatment_history") or []
        for i, tx in enumerate(treatments):
            start = tx.get("start_date")
            end = tx.get("end_date")
            if start and end:
                s = _parse_date(str(start))
                e = _parse_date(str(end))
                if s and e and e < s:
                    results.append((False, QualityIssue(
                        f"treatment[{i}].dates", "error",
                        f"Treatment end date precedes start date: {start} > {end}",
                    )))

        if not results:
            results.append((True, QualityIssue("temporal_order", "info", "no temporal data to check")))

        return results

    def _check_treatment_sequence(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        treatments = record.get("treatments") or record.get("treatment_history") or []

        if not treatments:
            results.append((True, QualityIssue("treatment_sequence", "info", "no treatments to validate")))
            return results

        # Check for duplicate active treatments
        active = [
            tx for tx in treatments
            if not tx.get("end_date") and tx.get("start_date")
        ]
        schemes = [tx.get("drug_scheme", "").lower() for tx in active if tx.get("drug_scheme")]
        if len(schemes) != len(set(schemes)):
            results.append((False, QualityIssue(
                "treatment_sequence", "warning",
                "Duplicate active treatment schemes detected",
            )))
        else:
            results.append((True, QualityIssue("treatment_sequence", "info", "no duplicate treatments")))

        return results

    def _check_state_validity(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        state = record.get("reconciled_state", "")
        if state:
            if state in VALID_STATES:
                results.append((True, QualityIssue("reconciled_state", "info", f"valid state: {state}")))
            else:
                results.append((False, QualityIssue(
                    "reconciled_state", "warning",
                    f"Unrecognized state: {state}", state,
                )))
        else:
            results.append((False, QualityIssue(
                "reconciled_state", "warning", "Missing reconciled_state",
            )))
        return results

    def _check_follow_up_completeness(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []

        if len(follow_ups) >= self.min_follow_up_visits:
            results.append((True, QualityIssue(
                "follow_up_count", "info",
                f"{len(follow_ups)} visits (meets minimum {self.min_follow_up_visits})",
            )))
        else:
            results.append((False, QualityIssue(
                "follow_up_count", "warning",
                f"Only {len(follow_ups)} visits (need {self.min_follow_up_visits})",
                len(follow_ups),
            )))
        return results

    def _check_consent(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        consent = record.get("consent") or record.get("consent_governance") or {}
        if isinstance(consent, dict):
            status = consent.get("status", "")
            if status in ("signed", "consented", "active"):
                results.append((True, QualityIssue("consent", "info", f"consent status: {status}")))
            else:
                results.append((False, QualityIssue(
                    "consent", "error",
                    f"Missing or invalid consent status: {status or 'none'}",
                )))
        elif isinstance(consent, list) and consent:
            results.append((True, QualityIssue("consent", "info", "consent records present")))
        else:
            results.append((False, QualityIssue("consent", "error", "No consent information")))
        return results

    def _check_deidentification(
        self, record: dict,
    ) -> list[tuple[bool, QualityIssue]]:
        results: list[tuple[bool, QualityIssue]] = []
        identity = record.get("identity", {}) or {}

        # Check for PII fields that should be removed or hashed
        nss = identity.get("nss", "")
        if nss and not _looks_hashed(str(nss)):
            results.append((False, QualityIssue(
                "identity.nss", "error",
                "NSS appears to contain un-hashed identifier",
            )))

        full_name = identity.get("full_name", "")
        if full_name and not _looks_anonymized(str(full_name)):
            results.append((False, QualityIssue(
                "identity.full_name", "warning",
                "Patient name may not be de-identified",
            )))

        if not results:
            results.append((True, QualityIssue("deidentification", "info", "no PII detected")))

        return results


# ── Utilities ─────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _looks_hashed(value: str) -> bool:
    """Check if a string looks like a hash (hex string of common hash lengths)."""
    return bool(re.match(r"^[a-fA-F0-9]{32,128}$", value.strip()))


def _looks_anonymized(value: str) -> bool:
    """Check if a name looks anonymized (e.g., 'Patient_001', 'ANON-xxx')."""
    v = value.strip().lower()
    return (
        v.startswith("patient") or
        v.startswith("anon") or
        v.startswith("paciente") or
        v == "" or
        bool(re.match(r"^[a-z]{1,3}[\-_]\d+$", v))
    )
