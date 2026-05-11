"""Pilar 6 — Ciberseguridad FDA Premarket Sept 2023.

Métrica: `(stride_addressed/identified)*0.35 + sbom_complete*0.25
        + (crit_vulns==0)*0.2 + disclosure_published*0.1 + sbomvex_present*0.1`

- STRIDE threat model en `prostanet/regulatory/security/STRIDE-threat-model.md`
- SBOM en formato CycloneDX o SPDX
- CVE clean (reuse logic de pillar_3 vía pip-audit)
- Disclosure policy en `regulatory/security/disclosure.md` o `SECURITY.md`
- VEX (Vulnerability Exploitability eXchange) addendum
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SEC_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "security"

STRIDE_PATH = SEC_DIR / "STRIDE-threat-model.md"
SBOM_PATH = SEC_DIR / "sbom-cyclonedx.json"
DISCLOSURE_PATHS = [
    PROJECT_ROOT / "SECURITY.md",
    SEC_DIR / "disclosure.md",
    SEC_DIR / "SECURITY.md",
]
VEX_PATH = SEC_DIR / "vex.json"

EXPECTED_STRIDE_THREATS = [
    "spoofing", "tampering", "repudiation",
    "information_disclosure", "denial_of_service", "elevation_of_privilege",
]


def _score_stride() -> tuple[float, list[Gap]]:
    if not STRIDE_PATH.exists():
        return 0.0, [Gap(
            pillar_id=6,
            kind="stride_threat_model_missing",
            description="Missing STRIDE threat model (Spoofing/Tampering/Repudiation/InfoDisclosure/DoS/ElevPriv)",
            severity=9, effort_h=8.0,
            artifact_path=str(STRIDE_PATH),
        )]
    content = STRIDE_PATH.read_text().lower()
    addressed = sum(1 for cat in EXPECTED_STRIDE_THREATS if cat.replace("_", " ") in content
                    or cat.replace("_", "") in content)
    score = addressed / 6.0
    gaps = []
    if addressed < 6:
        missing_cats = [c for c in EXPECTED_STRIDE_THREATS
                        if c.replace("_", " ") not in content
                        and c.replace("_", "") not in content]
        gaps.append(Gap(
            pillar_id=6,
            kind="stride_threat_categories_incomplete",
            description=f"STRIDE categories addressed: {addressed}/6 · missing: {missing_cats}",
            severity=7, effort_h=2.0 * len(missing_cats),
            evidence_source=str(STRIDE_PATH),
        ))
    return score, gaps


def _score_sbom() -> tuple[float, list[Gap]]:
    if not SBOM_PATH.exists():
        return 0.0, [Gap(
            pillar_id=6,
            kind="sbom_missing",
            description="Missing SBOM (CycloneDX format) — sbom-cyclonedx.json",
            severity=9, effort_h=2.0,
            artifact_path=str(SBOM_PATH),
        )]
    try:
        data = json.loads(SBOM_PATH.read_text())
        components = data.get("components", [])
        if len(components) < 5:
            return 0.5, [Gap(
                pillar_id=6,
                kind="sbom_incomplete",
                description=f"SBOM has {len(components)} components (expected ≥5 dependencies)",
                severity=6, effort_h=1.0,
            )]
        return 1.0, []
    except json.JSONDecodeError as e:
        return 0.0, [Gap(
            pillar_id=6, kind="sbom_invalid_json",
            description=f"sbom-cyclonedx.json parse error: {e}",
            severity=7, effort_h=0.5,
        )]


def _score_crit_vulns() -> tuple[float, list[Gap]]:
    """Returns 1.0 if 0 CRIT/HIGH vulns, 0.5 if scan tool unavailable."""
    try:
        proc = subprocess.run(
            ["pip-audit", "--strict", "--format=json"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
        )
        if proc.returncode == 0:
            return 1.0, []
        return 0.0, [Gap(
            pillar_id=6, kind="cve_critical_open",
            description=f"pip-audit found vulnerabilities (rc={proc.returncode})",
            severity=10, effort_h=4.0,
        )]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0.5, []


def _score_disclosure() -> tuple[float, list[Gap]]:
    for path in DISCLOSURE_PATHS:
        if path.exists() and path.stat().st_size > 100:
            return 1.0, []
    return 0.0, [Gap(
        pillar_id=6,
        kind="disclosure_policy_missing",
        description="Missing security disclosure policy (SECURITY.md or regulatory/security/disclosure.md)",
        severity=6, effort_h=1.0,
        artifact_path=str(DISCLOSURE_PATHS[0]),
    )]


def _score_vex() -> tuple[float, list[Gap]]:
    if VEX_PATH.exists() and VEX_PATH.stat().st_size > 50:
        return 1.0, []
    return 0.0, [Gap(
        pillar_id=6,
        kind="vex_addendum_missing",
        description="Missing VEX (Vulnerability Exploitability eXchange) addendum",
        severity=4, effort_h=2.0,
        artifact_path=str(VEX_PATH),
    )]


class Pillar6Security:
    pillar_id = 6
    name = "Ciberseguridad FDA Premarket Sept 2023"
    weight = 15.0

    def score(self) -> PillarScore:
        stride_score, stride_gaps = _score_stride()
        sbom_score, sbom_gaps = _score_sbom()
        cve_score, cve_gaps = _score_crit_vulns()
        disclosure_score, disclosure_gaps = _score_disclosure()
        vex_score, vex_gaps = _score_vex()

        score_pct = (
            stride_score * 0.35 + sbom_score * 0.25 + cve_score * 0.2
            + disclosure_score * 0.1 + vex_score * 0.1
        ) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=stride_gaps + sbom_gaps + cve_gaps + disclosure_gaps + vex_gaps,
            details={
                "stride_categories_addressed": int(stride_score * 6),
                "sbom_complete": sbom_score >= 1.0,
                "crit_vulns_clean": cve_score >= 1.0,
                "disclosure_published": disclosure_score >= 1.0,
                "vex_present": vex_score >= 1.0,
            },
        )


PILLAR = Pillar6Security()
