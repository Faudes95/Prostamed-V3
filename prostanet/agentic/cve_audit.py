"""Deterministic CVE audit tooling contract for the autonomous loop.

The compliance pillars need to distinguish three different states:

1. pip-audit is not declared anywhere in the repository.
2. pip-audit is declared as a controlled developer tool, but the current
   runtime has not installed it yet.
3. pip-audit is available and the pinned requirements were actually audited.

Only state 3 can claim a clean CVE audit. State 2 closes the "tool missing"
gap, but remains non-releaseable until the scan is executed.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.parent
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
DEV_REQUIREMENTS = PROJECT_ROOT / "requirements-dev.txt"
CVE_REPORT_PATH = PROJECT_ROOT / "prostanet" / "regulatory" / "security" / "cve-audit-last.json"
LOCAL_SECURITY_VENV_PIP_AUDIT = PROJECT_ROOT / ".venv-security" / "bin" / "pip-audit"

PIP_AUDIT_PIN = re.compile(r"^pip-audit==(?P<version>[0-9][A-Za-z0-9_.!+-]*)$")


@dataclass(frozen=True)
class CveAuditStatus:
    status: str
    score: float
    tool_declared: bool
    tool_available: bool
    command: tuple[str, ...]
    returncode: int | None = None
    report_path: str = ""
    detail: str = ""

    @property
    def clean(self) -> bool:
        return self.status == "clean"


def pip_audit_declared(requirements_dev: Path = DEV_REQUIREMENTS) -> bool:
    """Return True only when pip-audit is pinned in requirements-dev.txt."""
    try:
        lines = requirements_dev.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(PIP_AUDIT_PIN.match(line.strip()) for line in lines if line.strip() and not line.strip().startswith("#"))


def resolve_pip_audit_command() -> tuple[str, ...]:
    """Resolve pip-audit without importing or logging project data."""
    if LOCAL_SECURITY_VENV_PIP_AUDIT.exists():
        return (str(LOCAL_SECURITY_VENV_PIP_AUDIT),)
    cli = shutil.which("pip-audit")
    if cli:
        return (cli,)
    if importlib.util.find_spec("pip_audit") is not None:
        return (sys.executable, "-m", "pip_audit")
    return ()


def audit_command(requirements: Path = REQUIREMENTS, *, format_json: bool = True) -> tuple[str, ...]:
    base = resolve_pip_audit_command()
    if not base:
        return ()
    command = [*base, "--strict", "--no-deps", "--disable-pip", "--requirement", str(requirements)]
    if format_json:
        command.extend(["--format", "json"])
    return tuple(command)


def run_cve_audit(
    *,
    requirements: Path = REQUIREMENTS,
    requirements_dev: Path = DEV_REQUIREMENTS,
    timeout_seconds: int = 120,
) -> CveAuditStatus:
    declared = pip_audit_declared(requirements_dev)
    command = audit_command(requirements)
    if not command:
        if declared:
            return CveAuditStatus(
                status="runtime_unavailable",
                score=0.75,
                tool_declared=True,
                tool_available=False,
                command=(),
                report_path=str(CVE_REPORT_PATH.relative_to(PROJECT_ROOT)),
                detail="pip-audit is pinned in requirements-dev.txt but is not installed in this runtime.",
            )
        return CveAuditStatus(
            status="tool_missing",
            score=0.5,
            tool_declared=False,
            tool_available=False,
            command=(),
            detail="pip-audit is not declared in requirements-dev.txt and is unavailable in this runtime.",
        )

    try:
        proc = subprocess.run(
            list(command),
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return CveAuditStatus(
            status="scan_timeout",
            score=0.5,
            tool_declared=declared,
            tool_available=True,
            command=command,
            detail="pip-audit timed out before producing a trusted result.",
        )

    if proc.returncode == 0:
        return CveAuditStatus(
            status="clean",
            score=1.0,
            tool_declared=declared,
            tool_available=True,
            command=command,
            returncode=proc.returncode,
            report_path=str(CVE_REPORT_PATH.relative_to(PROJECT_ROOT)),
        )
    return CveAuditStatus(
        status="vulnerabilities_open",
        score=0.0,
        tool_declared=declared,
        tool_available=True,
        command=command,
        returncode=proc.returncode,
        report_path=str(CVE_REPORT_PATH.relative_to(PROJECT_ROOT)),
        detail="pip-audit returned a non-zero status; inspect the local audit report before release.",
    )
