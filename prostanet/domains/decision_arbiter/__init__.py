"""EPIC 23 — Clinical Recommendation Arbiter.

Decision fusion layer that detects conflicts between independently-emitted
Cortana cards (CV safety, hepatic safety, BRCA2 pathway, etc.) and the
Patient Twin OS regimen ranking. Applies contraindications, validates
clinical state timing, and emits a unified decision_fusion_summary the
clinician can read at a glance.

Authorization scope: internal_shadow_observational_validation.

Skills applied:
- /api-design (clean adapter contract)
- /backend-patterns (single-responsibility detectors + composable arbiter)
- /clinical-reports (decision fusion summary structure)
- /deep-research (NCCN 2026 v2 evidence for each conflict rule)
- /fda-medtech-compliance-auditor (SaMD audit trail of conflict resolutions)
- /ultrareview (final review pre-commit)
- /ui4 + /ui-ux-pro-max (conflict banner design)
"""

from prostanet.domains.decision_arbiter.recommendation_arbiter import (
    ArbitratedDecision,
    CardRecommendation,
    ClinicalConflict,
    arbitrate_recommendations,
)

__all__ = [
    "ArbitratedDecision",
    "CardRecommendation",
    "ClinicalConflict",
    "arbitrate_recommendations",
]
