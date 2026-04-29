"""Pilar 2 — QMS (Sistema Gestión de Calidad).

Métrica: `(sops_active/4)*0.5 + (roles_assigned/3)*0.2 + (part11_controls/8)*0.3`

SOPs requeridos (4):
- SOP-DCG-001 — Design Control SOP
- SOP-CCG-002 — Change Control SOP
- SOP-CAPA-003 — CAPA SOP
- SOP-RM-004 — Risk Management SOP

Roles (3):
- Quality Lead
- Software Lead
- Clinical Lead

21 CFR Part 11 controls (8):
- electronic_signature, audit_trail, access_control, data_integrity,
- retention_policy, validation, archival_procedures, copies_procedures
"""
from __future__ import annotations

from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SOPS_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "sops"
QMS_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "qms"

REQUIRED_SOPS = [
    ("SOP-DCG-001", "Design Control SOP", "design_control"),
    ("SOP-CCG-002", "Change Control SOP", "change_control"),
    ("SOP-CAPA-003", "CAPA (Corrective and Preventive Action) SOP", "capa"),
    ("SOP-RM-004", "Risk Management SOP", "risk_management"),
]
REQUIRED_ROLES = ["quality_lead", "software_lead", "clinical_lead"]
PART11_CONTROLS = [
    "electronic_signature", "audit_trail", "access_control", "data_integrity",
    "retention_policy", "validation", "archival_procedures", "copies_procedures",
]


def _score_sops() -> tuple[float, list[Gap]]:
    present = 0
    gaps: list[Gap] = []
    for sop_id, title, slug in REQUIRED_SOPS:
        # Acepta .docx, .md, o .pdf con sop_id en filename
        candidates = list(SOPS_DIR.glob(f"{sop_id}*"))
        if any(c.is_file() and c.stat().st_size > 500 for c in candidates):
            present += 1
        else:
            gaps.append(Gap(
                pillar_id=2,
                kind=f"sop_missing:{sop_id}",
                description=f"Missing SOP: {sop_id} — {title}",
                severity=9,
                effort_h=8.0,
                evidence_source=str(SOPS_DIR / f"{sop_id}.docx"),
                artifact_path=str(SOPS_DIR / f"{sop_id}.docx"),
            ))
    return present / 4.0, gaps


def _score_roles() -> tuple[float, list[Gap]]:
    roster_path = QMS_DIR / "roster.yaml"
    if not roster_path.exists():
        return 0.0, [Gap(
            pillar_id=2,
            kind="qms_roster_missing",
            description="Missing QMS roles roster (Quality/Software/Clinical Lead)",
            severity=8,
            effort_h=1.0,
            evidence_source=str(roster_path),
            artifact_path=str(roster_path),
        )]
    try:
        roster = yaml.safe_load(roster_path.read_text()) or {}
    except yaml.YAMLError as e:
        return 0.0, [Gap(
            pillar_id=2, kind="qms_roster_invalid",
            description=f"roster.yaml parse error: {e}",
            severity=7, effort_h=0.5,
        )]
    assigned = sum(1 for r in REQUIRED_ROLES if roster.get(r, {}).get("name"))
    gaps = []
    if assigned < 3:
        missing = [r for r in REQUIRED_ROLES if not roster.get(r, {}).get("name")]
        gaps.append(Gap(
            pillar_id=2,
            kind="qms_roles_unassigned",
            description=f"Missing role assignments: {missing}",
            severity=8,
            effort_h=1.0,
            evidence_source=str(roster_path),
        ))
    return assigned / 3.0, gaps


def _score_part11() -> tuple[float, list[Gap]]:
    checklist_path = QMS_DIR / "part11_checklist.yaml"
    if not checklist_path.exists():
        return 0.0, [Gap(
            pillar_id=2,
            kind="part11_checklist_missing",
            description="Missing 21 CFR Part 11 controls checklist (8 controls)",
            severity=9, effort_h=4.0,
            evidence_source=str(checklist_path),
            artifact_path=str(checklist_path),
        )]
    try:
        cl = yaml.safe_load(checklist_path.read_text()) or {}
    except yaml.YAMLError as e:
        return 0.0, [Gap(
            pillar_id=2, kind="part11_checklist_invalid",
            description=f"part11_checklist.yaml parse error: {e}",
            severity=7, effort_h=0.5,
        )]
    implemented = sum(1 for k in PART11_CONTROLS
                      if cl.get(k, {}).get("implemented"))
    gaps = []
    missing_controls = [k for k in PART11_CONTROLS
                         if not cl.get(k, {}).get("implemented")]
    for control in missing_controls[:5]:  # cap individual gaps to top 5
        gaps.append(Gap(
            pillar_id=2,
            kind=f"part11_control_missing:{control}",
            description=f"21 CFR Part 11 control not implemented: {control}",
            severity=7, effort_h=2.0,
            evidence_source=str(checklist_path),
        ))
    return implemented / 8.0, gaps


class Pillar2QMS:
    pillar_id = 2
    name = "QMS (Sistema Gestión de Calidad)"
    weight = 12.0

    def score(self) -> PillarScore:
        sop_score, sop_gaps = _score_sops()
        role_score, role_gaps = _score_roles()
        part11_score, part11_gaps = _score_part11()

        score_pct = (sop_score * 0.5 + role_score * 0.2 + part11_score * 0.3) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=sop_gaps + role_gaps + part11_gaps,
            details={
                "sops_active": int(sop_score * 4),
                "sops_total": 4,
                "roles_assigned": int(role_score * 3),
                "roles_total": 3,
                "part11_controls_implemented": int(part11_score * 8),
                "part11_controls_total": 8,
            },
        )


PILLAR = Pillar2QMS()
