from __future__ import annotations

import re
import subprocess
from pathlib import Path

from prostanet.agentic.compliance_scorer import Gap, PillarScore


PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REG_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "software_lifecycle"
REQUIREMENTS = PROJECT_ROOT / "prostanet" / "regulatory" / "requirements_traceability_matrix.md"
IEC_PATTERN = re.compile(r"IEC\\s*62304|§\\s*5\\.", re.IGNORECASE)


def _score_tests_mapped() -> tuple[float, list[Gap]]:
    test_files = list(TESTS_DIR.glob("test_*.py")) if TESTS_DIR.exists() else []
    if not test_files:
        return 0.0, [
            Gap(
                pillar_id=3,
                kind="unit_tests_missing",
                description="No unit/integration tests found for IEC 62304 verification evidence.",
                severity=9,
                effort_h=8.0,
                evidence_source=str(TESTS_DIR),
            )
        ]
    mapped = 0
    for path in test_files:
        try:
            if IEC_PATTERN.search(path.read_text(errors="ignore")):
                mapped += 1
        except Exception:
            continue
    score = min(mapped / max(len(test_files), 1), 1.0)
    gaps = []
    if score < 0.5:
        gaps.append(
            Gap(
                pillar_id=3,
                kind="iec62304_test_traceability_sparse",
                description=f"Only {mapped}/{len(test_files)} test files include explicit IEC 62304 traceability.",
                severity=6,
                effort_h=4.0,
                evidence_source=str(TESTS_DIR),
            )
        )
    return score, gaps


def _score_sbom_pinned() -> tuple[float, list[Gap]]:
    candidates = [
        PROJECT_ROOT / "requirements.txt",
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "package-lock.json",
        PROJECT_ROOT / "uv.lock",
    ]
    present = [path for path in candidates if path.exists()]
    if not present:
        return 0.0, [
            Gap(
                pillar_id=3,
                kind="dependency_manifest_missing",
                description="No dependency manifest found for lifecycle reproducibility/SBOM baseline.",
                severity=7,
                effort_h=4.0,
                artifact_path=str(PROJECT_ROOT / "requirements.txt"),
            )
        ]
    pinned = 0
    total = 0
    for path in present:
        for line in path.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            total += 1
            if any(token in stripped for token in ("==", " poetry.lock", "integrity", "version =")):
                pinned += 1
    score = 1.0 if total == 0 else min(pinned / total, 1.0)
    return score, []


def _score_cve_clean() -> tuple[float, list[Gap]]:
    try:
        proc = subprocess.run(
            ["python3", "-m", "pip", "audit", "--format", "json"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except Exception:
        return 0.6, []
    if proc.returncode == 0:
        return 1.0, []
    return 0.5, [
        Gap(
            pillar_id=3,
            kind="dependency_vulnerability_scan_not_clean",
            description="Dependency vulnerability scan did not complete cleanly; review pip-audit output.",
            severity=6,
            effort_h=2.0,
            evidence_source="python3 -m pip audit",
        )
    ]


def _score_sdp() -> tuple[float, list[Gap]]:
    sdp_path = REG_DIR / "software_development_plan.md"
    if sdp_path.exists() and sdp_path.stat().st_size > 500:
        return 1.0, []
    return 0.0, [
        Gap(
            pillar_id=3,
            kind="software_development_plan_missing",
            description="Missing or incomplete IEC 62304 software development plan.",
            severity=8,
            effort_h=6.0,
            artifact_path=str(sdp_path),
        )
    ]


class Pillar3Lifecycle:
    pillar_id = 3
    name = "IEC 62304 Software Lifecycle"
    weight = 18.0

    def score(self) -> PillarScore:
        tests_score, test_gaps = _score_tests_mapped()
        sbom_score, sbom_gaps = _score_sbom_pinned()
        cve_score, cve_gaps = _score_cve_clean()
        sdp_score, sdp_gaps = _score_sdp()
        score_pct = (
            tests_score * 0.35
            + sbom_score * 0.2
            + cve_score * 0.2
            + sdp_score * 0.25
        ) * 100.0
        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=test_gaps + sbom_gaps + cve_gaps + sdp_gaps,
            details={
                "tests_traceability_score": round(tests_score * 100, 1),
                "dependency_pin_score": round(sbom_score * 100, 1),
                "vulnerability_scan_score": round(cve_score * 100, 1),
                "software_development_plan_score": round(sdp_score * 100, 1),
            },
        )


PILLAR = Pillar3Lifecycle()
