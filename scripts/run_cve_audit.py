#!/usr/bin/env python3
"""Run the ProstaMed CVE audit contract without logging PHI.

This script audits the pinned Python requirements and can optionally write the
raw pip-audit JSON report to the regulatory security folder. The report contains
dependency/advisory metadata only; it must never contain patient data.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from prostanet.agentic.cve_audit import CVE_REPORT_PATH, PROJECT_ROOT, audit_command, run_cve_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ProstaMed pip-audit CVE scan.")
    parser.add_argument("--write-report", action="store_true", help="Persist pip-audit JSON to regulatory/security.")
    args = parser.parse_args()

    status = run_cve_audit()
    summary = {
        "status": status.status,
        "score": status.score,
        "tool_declared": status.tool_declared,
        "tool_available": status.tool_available,
        "returncode": status.returncode,
        "report_path": status.report_path,
        "detail": status.detail,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.write_report and status.command:
        proc = subprocess.run(
            list(audit_command()),
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        CVE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CVE_REPORT_PATH.write_text(proc.stdout or "{}", encoding="utf-8")
        return proc.returncode

    return 0 if status.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
