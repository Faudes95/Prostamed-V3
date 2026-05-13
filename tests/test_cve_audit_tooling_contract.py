from __future__ import annotations

from pathlib import Path
import json

from prostanet.agentic.cve_audit import CveAuditStatus, pip_audit_declared


def _requirements_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.strip().lower()] = version.strip()
    return pins


def test_requirements_dev_pins_pip_audit():
    """IEC 62304 §5.1: security audit tooling is declared as pinned SOUP."""
    requirements_dev = Path("requirements-dev.txt")
    assert requirements_dev.exists()
    assert pip_audit_declared(requirements_dev) is True
    assert "pip-audit==2.10.0" in requirements_dev.read_text(encoding="utf-8")


def test_known_vulnerable_runtime_packages_are_pinned_to_cve_fixed_versions():
    """IEC 62304 §5.1: SOUP pins must not remain on locally identified CVE ranges."""
    pins = _requirements_pins(Path("requirements.txt"))
    voice_pins = _requirements_pins(Path("requirements-voice.txt"))

    assert pins["flask"] == "3.1.3"
    assert pins["requests"] == "2.33.0"
    assert pins["cryptography"] == "46.0.7"
    assert pins["torch"] == "2.10.0"
    assert voice_pins["requests"] == "2.33.0"


def test_last_cve_audit_report_has_no_open_vulnerabilities():
    """IEC 62304 §5.7: the checked-in CVE artifact must be clean after remediation."""
    report_path = Path("prostanet/regulatory/security/cve-audit-last.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    vulnerable = [
        item.get("name")
        for item in report.get("dependencies", [])
        if item.get("vulns")
    ]

    assert vulnerable == []


def test_pip_audit_declaration_rejects_unpinned_tool(tmp_path):
    """IEC 62304 §5.1: loose developer tooling pins are not accepted."""
    loose = tmp_path / "requirements-dev.txt"
    loose.write_text("pip-audit>=2.10.0\n", encoding="utf-8")
    assert pip_audit_declared(loose) is False


def test_audit_command_uses_pinned_no_pip_resolution(monkeypatch):
    """IEC 62304 §5.7: audit pinned requirements without Python-version dry-run drift."""
    import prostanet.agentic.cve_audit as cve_audit

    monkeypatch.setattr(cve_audit, "resolve_pip_audit_command", lambda: ("pip-audit",))
    command = cve_audit.audit_command()

    assert "--requirement" in command
    assert "--no-deps" in command
    assert "--disable-pip" in command


def test_pillar_3_declared_tool_no_longer_reports_tool_missing(monkeypatch):
    """IEC 62304 §5.7: declared audit tooling closes the missing-tool gap."""
    import prostanet.agentic.pillars.pillar_3_lifecycle as pillar3

    monkeypatch.setattr(
        pillar3,
        "run_cve_audit",
        lambda timeout_seconds=120: CveAuditStatus(
            status="runtime_unavailable",
            score=0.75,
            tool_declared=True,
            tool_available=False,
            command=(),
            report_path="prostanet/regulatory/security/cve-audit-last.json",
        ),
    )
    score, gaps = pillar3._score_cve_clean()
    kinds = {gap.kind for gap in gaps}

    assert score == 0.75
    assert "cve_scan_tool_missing" not in kinds
    assert "cve_scan_runtime_unavailable" in kinds


def test_pillar_3_still_flags_tool_missing_when_not_declared(monkeypatch):
    """IEC 62304 §5.7: missing declaration remains a compliance gap."""
    import prostanet.agentic.pillars.pillar_3_lifecycle as pillar3

    monkeypatch.setattr(
        pillar3,
        "run_cve_audit",
        lambda timeout_seconds=120: CveAuditStatus(
            status="tool_missing",
            score=0.5,
            tool_declared=False,
            tool_available=False,
            command=(),
        ),
    )
    score, gaps = pillar3._score_cve_clean()
    kinds = {gap.kind for gap in gaps}

    assert score == 0.5
    assert "cve_scan_tool_missing" in kinds


def test_pillar_6_reuses_declared_cve_runtime_gap(monkeypatch):
    """IEC 62304 §5.7: cybersecurity pillar shares the same CVE contract."""
    import prostanet.agentic.pillars.pillar_6_security as pillar6

    monkeypatch.setattr(
        pillar6,
        "run_cve_audit",
        lambda timeout_seconds=60: CveAuditStatus(
            status="runtime_unavailable",
            score=0.75,
            tool_declared=True,
            tool_available=False,
            command=(),
            report_path="prostanet/regulatory/security/cve-audit-last.json",
        ),
    )
    score, gaps = pillar6._score_crit_vulns()
    kinds = {gap.kind for gap in gaps}

    assert score == 0.75
    assert "cve_scan_tool_missing" not in kinds
    assert "cve_scan_runtime_unavailable" in kinds
