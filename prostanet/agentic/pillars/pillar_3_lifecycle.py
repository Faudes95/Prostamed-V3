"""Pilar 3 — IEC 62304 ciclo de vida de software.

Métrica: `(tests_mapped/total_tests)*0.4 + sbom_pinned*0.3 + cve_clean*0.2 + sdp_present*0.1`

- Tests mapped: tests con `# IEC 62304 §X.Y` comentario o `@iec62304_phase("X.Y")`
- SBOM pinned: requirements.txt con versiones exactas (no `>=`)
- CVE clean: 0 vulnerabilidades CRIT/HIGH (best-effort: skip si pip-audit no instalado)
- SDP present: prostanet/regulatory/regulatory/sdp_software_development_plan.md
"""
from __future__ import annotations

import re
from pathlib import Path

from prostanet.agentic.cve_audit import run_cve_audit
from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REG_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "regulatory"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

# Pattern: detecta phase mapping en comments (e.g. "# IEC 62304 §5.5")
IEC_PATTERN = re.compile(r"IEC[\s_]?62304[\s_]*§?\s*\d+\.\d+", re.IGNORECASE)


def _score_tests_mapped() -> tuple[float, list[Gap]]:
    """% de archivos test/ que mencionan IEC 62304 phase."""
    if not TESTS_DIR.exists():
        return 0.0, [Gap(
            pillar_id=3, kind="tests_dir_missing",
            description="tests/ directory not found",
            severity=10, effort_h=0.0,
        )]
    test_files = list(TESTS_DIR.glob("test_*.py"))
    total = len(test_files)
    if total == 0:
        return 0.0, []
    mapped = 0
    for tf in test_files:
        try:
            content = tf.read_text(errors="replace")
            if IEC_PATTERN.search(content):
                mapped += 1
        except OSError:
            pass
    score = mapped / total
    gaps = []
    if mapped < total:
        gaps.append(Gap(
            pillar_id=3,
            kind="iec62304_test_mapping_incomplete",
            description=f"Tests mapped to IEC 62304 phases: {mapped}/{total} ({(score*100):.0f}%)",
            severity=5,
            effort_h=max(1.0, (total - mapped) * 0.05),  # ~3min/test
            evidence_source=str(TESTS_DIR),
        ))
    return score, gaps


def _score_sbom_pinned() -> tuple[float, list[Gap]]:
    if not REQUIREMENTS.exists():
        return 0.0, [Gap(
            pillar_id=3, kind="requirements_missing",
            description="requirements.txt missing",
            severity=10, effort_h=2.0,
        )]
    lines = [l.strip() for l in REQUIREMENTS.read_text().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return 0.0, [Gap(
            pillar_id=3, kind="requirements_empty",
            description="requirements.txt is empty",
            severity=10, effort_h=2.0,
        )]
    pinned = sum(1 for l in lines if "==" in l)
    score = pinned / len(lines)
    gaps = []
    if score < 1.0:
        unpinned = [l.split("=")[0].split(">")[0].split("~")[0].strip()
                    for l in lines if "==" not in l]
        gaps.append(Gap(
            pillar_id=3,
            kind="sbom_unpinned_dependencies",
            description=f"Unpinned dependencies in requirements.txt: {unpinned[:8]}",
            severity=7,
            effort_h=2.0,
            evidence_source=str(REQUIREMENTS),
        ))
    return score, gaps


def _score_cve_clean() -> tuple[float, list[Gap]]:
    """Score CVE readiness without claiming clean status unless pip-audit ran."""
    status = run_cve_audit(timeout_seconds=120)
    if status.clean:
        return 1.0, []
    if status.status == "runtime_unavailable":
        return status.score, [Gap(
            pillar_id=3,
            kind="cve_scan_runtime_unavailable",
            description=(
                "pip-audit is pinned in requirements-dev.txt but is not installed in this runtime; "
                "run `python3 -m pip install -r requirements-dev.txt` and `python3 scripts/run_cve_audit.py`."
            ),
            severity=3,
            effort_h=0.25,
            evidence_source="requirements-dev.txt",
            artifact_path=status.report_path,
        )]
    if status.status == "tool_missing":
        return status.score, [Gap(
            pillar_id=3,
            kind="cve_scan_tool_missing",
            description="pip-audit is not pinned in requirements-dev.txt; CVE compliance tooling is undefined.",
            severity=4,
            effort_h=0.5,
            artifact_path="requirements-dev.txt",
        )]
    if status.status == "scan_timeout":
        return status.score, [Gap(
            pillar_id=3,
            kind="cve_scan_timeout",
            description="pip-audit timed out; CVE compliance remains unknown.",
            severity=5,
            effort_h=0.5,
            evidence_source="scripts/run_cve_audit.py",
            artifact_path=status.report_path,
        )]
    return status.score, [Gap(
        pillar_id=3,
        kind="cve_critical_open",
        description=f"pip-audit found vulnerabilities or failed with rc={status.returncode}",
        severity=10,
        effort_h=4.0,
        evidence_source="pip-audit output",
        artifact_path="prostanet/regulatory/security/cve-remediation.md",
    )]


def _score_sdp() -> tuple[float, list[Gap]]:
    sdp_path = REG_DIR / "sdp_software_development_plan.md"
    if sdp_path.exists() and sdp_path.stat().st_size > 500:
        return 1.0, []
    return 0.0, [Gap(
        pillar_id=3,
        kind="sdp_missing",
        description="Missing Software Development Plan (IEC 62304 §5.1)",
        severity=8, effort_h=4.0,
        evidence_source=str(sdp_path),
        artifact_path=str(sdp_path),
    )]


class Pillar3Lifecycle:
    pillar_id = 3
    name = "IEC 62304 ciclo de vida"
    weight = 18.0

    def score(self) -> PillarScore:
        tests_score, tests_gaps = _score_tests_mapped()
        sbom_score, sbom_gaps = _score_sbom_pinned()
        cve_score, cve_gaps = _score_cve_clean()
        sdp_score, sdp_gaps = _score_sdp()

        score_pct = (tests_score * 0.4 + sbom_score * 0.3
                     + cve_score * 0.2 + sdp_score * 0.1) * 100.0

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=tests_gaps + sbom_gaps + cve_gaps + sdp_gaps,
            details={
                "tests_mapped_pct": round(tests_score * 100, 1),
                "sbom_pinned_pct": round(sbom_score * 100, 1),
                "cve_clean": cve_score >= 1.0,
                "cve_tool_declared": any(g.kind != "cve_scan_tool_missing" for g in cve_gaps) or cve_score >= 1.0,
                "sdp_present": sdp_score >= 1.0,
            },
        )


PILLAR = Pillar3Lifecycle()
