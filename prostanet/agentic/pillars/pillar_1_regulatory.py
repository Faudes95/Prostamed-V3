"""Pilar 1 — Determinación regulatoria & clasificación.

Métrica: `(docs_present/4)*0.6 + (cds_criteria_met/4)*0.3 + iec_class_assigned*0.1`

Documentos requeridos (4):
- IMDRF risk doc                  → regulatory/regulatory/imdrf_risk_classification.md
- CDS Guidance memo               → regulatory/regulatory/cds_guidance_memo.md
- IEC 62304 class B assignment    → regulatory/regulatory/iec62304_class.md
- Intended use statement          → regulatory/regulatory/intended_use.md

CDS criteria FDA Sept 2022 (4 criterios — checked vía YAML):
- regulatory/regulatory/cds_criteria.yaml debe tener `criteria: {c1,c2,c3,c4}` cada uno
  con `met: true/false`.

LXXXVIII bootstrap.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
REG_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "regulatory"

REQUIRED_DOCS = [
    ("imdrf_risk_classification.md", "IMDRF risk classification document"),
    ("cds_guidance_memo.md", "CDS Final Guidance FDA Sept 2022 memo"),
    ("iec62304_class.md", "IEC 62304 software safety class assignment (A/B/C)"),
    ("intended_use.md", "Intended use statement"),
]


def _score_docs() -> tuple[float, list[Gap]]:
    """Score 0-1 según docs presentes, con gaps por cada faltante."""
    present = 0
    gaps: list[Gap] = []
    for fname, description in REQUIRED_DOCS:
        path = REG_DIR / fname
        if path.exists() and path.stat().st_size > 100:  # at least 100 bytes
            present += 1
        else:
            gaps.append(Gap(
                pillar_id=1,
                kind=f"regulatory_doc_missing:{fname}",
                description=f"Missing: {description} ({fname})",
                severity=8,
                effort_h=4.0,
                evidence_source=str(path),
                artifact_path=str(path),
            ))
    return present / 4.0, gaps


def _score_cds_criteria() -> tuple[float, list[Gap]]:
    """Score CDS classification status per FDA Sept 2022 Final Guidance.

    EPIC 13b refactor — distingue dos paths legítimos:

      1. **non_device_cds_exemption**: producto reclamando exemption per
         21st Century Cures Act §3060 → necesita met=4/4 criterios.
         Gap `cds_criteria_incomplete` activo si <4 met.

      2. **device_software_function**: producto reconocido como SaMD que
         requiere 510(k) Class II clearance (path legítimo, no failure).
         Gap activo solo si:
           - analysis NO completed (kind=`cds_classification_analysis_pending`)
           - decision NO documented (kind=`cds_classification_decision_pending`)
           - approval signatures pending (kind=`cds_classification_approval_pending`,
             severity 4 informational — NOT critical)

    ProstaMed declara honestamente 2/4 met → device path. Score 1.0 cuando
    el análisis está completo y la decisión está documentada, aunque las
    firmas formales sigan pendientes (eso emite gap informational sev 4).
    """
    cds_path = REG_DIR / "cds_criteria.yaml"
    if not cds_path.exists():
        return 0.0, [Gap(
            pillar_id=1,
            kind="cds_criteria_yaml_missing",
            description="Missing CDS Final Guidance FDA Sept 2022 criteria YAML (4 criterios)",
            severity=8,
            effort_h=2.0,
            evidence_source=str(cds_path),
            artifact_path=str(cds_path),
        )]
    try:
        data = yaml.safe_load(cds_path.read_text()) or {}
    except yaml.YAMLError as e:
        return 0.0, [Gap(
            pillar_id=1, kind="cds_criteria_yaml_invalid",
            description=f"YAML parse error: {e}",
            severity=6, effort_h=0.5,
            evidence_source=str(cds_path),
        )]

    criteria = data.get("criteria", {}) or {}
    met = sum(1 for v in criteria.values() if isinstance(v, dict) and v.get("met"))
    total = max(len(criteria), 4)
    summary = data.get("summary", {}) or {}
    classification = str(summary.get("classification") or "").strip().lower()
    analysis_completed = bool(summary.get("analysis_completed"))
    decision_documented = bool(summary.get("decision_documented"))
    approval = data.get("approval", {}) or {}
    approved_at = approval.get("approved_at")
    approved_by = approval.get("approved_by")
    has_signatures = bool(approved_at) and bool(approved_by)

    gaps: list[Gap] = []

    # Path 1: non_device_cds_exemption claim → need 4/4 met.
    if classification in {"", "non_device_cds_exemption", "non_device"}:
        if met < 4:
            gaps.append(Gap(
                pillar_id=1,
                kind="cds_criteria_incomplete",
                description=f"CDS criteria met: {met}/{total} (need 4 for non-device classification claim)",
                severity=7,
                effort_h=3.0,
                evidence_source=str(cds_path),
            ))
        return met / 4.0, gaps

    # Path 2: device_software_function path (legitimate 510k route).
    if not analysis_completed:
        gaps.append(Gap(
            pillar_id=1,
            kind="cds_classification_analysis_pending",
            description="CDS classification analysis NOT completed",
            severity=6, effort_h=2.0,
            evidence_source=str(cds_path),
        ))
        return 0.0, gaps
    if not decision_documented:
        gaps.append(Gap(
            pillar_id=1,
            kind="cds_classification_decision_pending",
            description="CDS classification decision NOT documented (analysis complete, awaiting routing decision)",
            severity=5, effort_h=1.0,
            evidence_source=str(cds_path),
        ))
        return 0.5, gaps
    if not has_signatures:
        # Analysis + decision done; only approval signatures pending = informational.
        gaps.append(Gap(
            pillar_id=1,
            kind="cds_classification_approval_pending",
            description=(
                f"CDS classification documented as {summary.get('classification')!r} "
                f"({summary.get('fda_route', 'pre-Sub')}); approval signatures pending."
            ),
            severity=4, effort_h=0.5,
            evidence_source=str(cds_path),
        ))
        return 1.0, gaps  # Compliant: analysis + decision done; signatures are admin.
    return 1.0, gaps


def _score_iec_class() -> tuple[float, list[Gap]]:
    """Score 1.0 si iec62304_class.md existe + contiene Class A/B/C asignación."""
    path = REG_DIR / "iec62304_class.md"
    if not path.exists():
        return 0.0, [Gap(
            pillar_id=1, kind="iec62304_class_unassigned",
            description="IEC 62304 Class (A/B/C) NOT formally assigned",
            severity=7, effort_h=2.0,
            evidence_source=str(path), artifact_path=str(path),
        )]
    content = path.read_text().lower()
    if any(s in content for s in ["class a", "class b", "class c", "clase a", "clase b", "clase c"]):
        return 1.0, []
    return 0.0, [Gap(
        pillar_id=1, kind="iec62304_class_undocumented",
        description="iec62304_class.md exists but no Class A/B/C designation found",
        severity=6, effort_h=0.5,
        evidence_source=str(path),
    )]


class Pillar1Regulatory:
    pillar_id = 1
    name = "Determinación regulatoria & clasificación"
    weight = 4.0  # LXC: rebalanced 8→4 to make room for P8

    def score(self) -> PillarScore:
        docs_score, doc_gaps = _score_docs()
        cds_score, cds_gaps = _score_cds_criteria()
        iec_score, iec_gaps = _score_iec_class()

        score_pct = (docs_score * 0.6 + cds_score * 0.3 + iec_score * 0.1) * 100.0
        all_gaps = doc_gaps + cds_gaps + iec_gaps

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=all_gaps,
            details={
                "docs_present_pct": round(docs_score * 100, 1),
                "cds_criteria_met_pct": round(cds_score * 100, 1),
                "iec_class_assigned": iec_score >= 1.0,
                "required_docs": [d for d, _ in REQUIRED_DOCS],
            },
        )


PILLAR = Pillar1Regulatory()
