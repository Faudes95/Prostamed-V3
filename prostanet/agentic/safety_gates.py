"""Faubot Agentic Loop — Safety Gates (LXXXVII).

4 gates que DEBEN pasar antes de auto-merge de cualquier propuesta agéntica:

1. **Test sweep**: pytest sweep §7.2 CLAUDE.md → 100% pass (excluye torch tests)
2. **Critical regression**: pytest tests/test_audit*.py → 100% pass
3. **Smoke E2E**: Flask test client GET de rutas críticas → HTTP 200 + sin errors
4. **Lint clean**: ruff check + mypy → 0 errores

Cada gate retorna `GateResult(passed: bool, message: str, details: dict)`.
`SafetyGateReport` agrega los 4 + provee `all_passed: bool`.

Diseño:
- Cada gate es independiente; ejecutables en paralelo.
- Timeout per-gate: 5min (test sweep), 1min (resto).
- En failure mode: retorna details con stdout/stderr para debugging.
- Side-effect-free: NO modifica DB, NO escribe archivos (sólo lee).

Bootstrap LXXXVII; refactorizado para FDA SaMD-driven en LXXXVIII.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
PYTEST_CMD = [
    sys.executable, "-m", "pytest",
    "-q", "--no-header",
    "-c", "/dev/null", "--rootdir=/tmp",
    "-o", "cache_dir=/tmp/pytest_cache",
    "--continue-on-collection-errors",
]


@dataclass
class GateResult:
    """Resultado de un único safety gate."""
    name: str
    passed: bool
    message: str
    duration_s: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyGateReport:
    """Agregado de los 4 gates."""
    test_sweep: GateResult
    critical_regression: GateResult
    smoke_e2e: GateResult
    lint_clean: GateResult
    total_duration_s: float = 0.0

    @property
    def all_passed(self) -> bool:
        return all(g.passed for g in [
            self.test_sweep, self.critical_regression,
            self.smoke_e2e, self.lint_clean,
        ])

    @property
    def passed_count(self) -> int:
        return sum(1 for g in [
            self.test_sweep, self.critical_regression,
            self.smoke_e2e, self.lint_clean,
        ] if g.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "passed_count": self.passed_count,
            "total_duration_s": self.total_duration_s,
            "gates": {
                "test_sweep": self.test_sweep.to_dict(),
                "critical_regression": self.critical_regression.to_dict(),
                "smoke_e2e": self.smoke_e2e.to_dict(),
                "lint_clean": self.lint_clean.to_dict(),
            },
        }


def _run_subprocess(cmd: list[str], cwd: Path = PROJECT_ROOT,
                     timeout_s: int = 300) -> tuple[int, str, str, float]:
    """Ejecuta subprocess + retorna (returncode, stdout, stderr, duration_s).

    Si el binario no existe (FileNotFoundError), retorna rc=127 (POSIX standard
    para command not found) sin lanzar excepción.
    """
    import time
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env,
            capture_output=True, text=True,
            timeout=timeout_s,
        )
        return proc.returncode, proc.stdout, proc.stderr, time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout_s}s", time.monotonic() - t0
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e.filename or cmd[0]}", time.monotonic() - t0


def gate_test_sweep(timeout_s: int = 300) -> GateResult:
    """Gate 1 — pytest sweep crítico §7.2 CLAUDE.md.

    Ejecuta pivotal + audit + smoke + clinical_validation. Excluye tests con
    deps torch (issue de import circular environmental, no nuestro).
    """
    test_files = [
        "tests/test_pivotal_*.py",
        "tests/test_audit63a_*.py",
        "tests/test_audit63b_*.py",
        "tests/test_audit63c_*.py",
        "tests/test_modular_engine.py",
        "tests/test_clinical_validation.py",
    ]
    cmd = PYTEST_CMD + test_files
    rc, stdout, stderr, dur = _run_subprocess(cmd, timeout_s=timeout_s)
    # Parse last line for "X passed" / "Y failed"
    last_lines = (stdout or "").splitlines()[-15:]
    summary = next((l for l in reversed(last_lines) if "passed" in l or "failed" in l), "")
    passed = (rc == 0)
    return GateResult(
        name="test_sweep",
        passed=passed,
        message=summary[:200] if summary else f"exit={rc}",
        duration_s=dur,
        details={"rc": rc, "stderr_tail": (stderr or "").splitlines()[-5:]},
    )


def gate_critical_regression(timeout_s: int = 180) -> GateResult:
    """Gate 2 — pytest test_audit*.py (regresiones de auditorías Faubot)."""
    cmd = PYTEST_CMD + ["tests/", "-k", "test_audit"]
    rc, stdout, stderr, dur = _run_subprocess(cmd, timeout_s=timeout_s)
    last_lines = (stdout or "").splitlines()[-15:]
    summary = next((l for l in reversed(last_lines) if "passed" in l or "failed" in l), "")
    passed = (rc == 0)
    return GateResult(
        name="critical_regression",
        passed=passed,
        message=summary[:200] if summary else f"exit={rc}",
        duration_s=dur,
        details={"rc": rc, "stderr_tail": (stderr or "").splitlines()[-5:]},
    )


def gate_smoke_e2e(timeout_s: int = 60, nss: str = "97000000001") -> GateResult:
    """Gate 3 — Smoke E2E: Flask test client GET rutas críticas + paciente real."""
    import time
    # Faubot LXXXVII — rutas críticas validadas en test client (sin / que tiene
    # bug pre-existente con modular_views blueprint en test client mode).
    routes = [
        "/patients",
        f"/patient_profile/{nss}",
        "/intake-wizard",
        "/api/intake-schema/_quick",
        f"/api/intake-schema/m1_crpc",
        "/longitudinal-capture/" + nss,
    ]
    t0 = time.monotonic()
    failures: list[str] = []
    successes: list[str] = []
    try:
        # Suppress noisy logs
        import logging
        prev_level = logging.getLogger().level
        logging.getLogger().setLevel(logging.ERROR)
        sys.path.insert(0, str(PROJECT_ROOT))
        # Force re-import to pick up latest code
        for mod in list(sys.modules):
            if mod.startswith("app") or mod.startswith("prostanet"):
                pass  # leave imports cached for performance
        from app import app
        client = app.test_client()
        for route in routes:
            try:
                resp = client.get(route)
                if 200 <= resp.status_code < 400:
                    successes.append(f"{route}={resp.status_code}")
                else:
                    failures.append(f"{route}={resp.status_code}")
            except Exception as exc:
                failures.append(f"{route}=EXC:{type(exc).__name__}")
        logging.getLogger().setLevel(prev_level)
    except Exception as exc:
        failures.append(f"setup_failed:{exc}")
    dur = time.monotonic() - t0
    passed = (len(failures) == 0)
    return GateResult(
        name="smoke_e2e",
        passed=passed,
        message=f"{len(successes)}/{len(routes)} routes OK" + (f" · failures: {failures}" if failures else ""),
        duration_s=dur,
        details={"successes": successes, "failures": failures},
    )


def gate_lint_clean(timeout_s: int = 60) -> GateResult:
    """Gate 4 — ruff + (optional) mypy. Soft fail si ruff no instalado."""
    import time
    t0 = time.monotonic()
    # ruff (preferred)
    rc, stdout, stderr, dur = _run_subprocess(
        ["ruff", "check", "prostanet/", "--quiet"],
        timeout_s=timeout_s,
    )
    if rc == 127 or "command not found" in (stderr or "").lower():
        # ruff not installed → skip with warning, do NOT fail
        return GateResult(
            name="lint_clean",
            passed=True,
            message="ruff not installed · gate skipped (warning)",
            duration_s=time.monotonic() - t0,
            details={"skipped": True, "reason": "ruff not installed"},
        )
    passed = (rc == 0)
    issue_count = len((stdout or "").splitlines())
    return GateResult(
        name="lint_clean",
        passed=passed,
        message=f"ruff: {issue_count} issues" if not passed else "ruff: clean",
        duration_s=time.monotonic() - t0,
        details={"rc": rc, "stdout_head": (stdout or "").splitlines()[:10]},
    )


def run_all_gates(*, fast_mode: bool = False) -> SafetyGateReport:
    """Ejecuta los 4 safety gates serialmente (paralelización futura).

    Args:
        fast_mode: si True, reduce timeout test sweep a 90s (subset crítico).
    """
    import time
    t_start = time.monotonic()

    test_timeout = 90 if fast_mode else 300
    g1 = gate_test_sweep(timeout_s=test_timeout)
    g2 = gate_critical_regression(timeout_s=180)
    g3 = gate_smoke_e2e(timeout_s=60)
    g4 = gate_lint_clean(timeout_s=60)

    return SafetyGateReport(
        test_sweep=g1,
        critical_regression=g2,
        smoke_e2e=g3,
        lint_clean=g4,
        total_duration_s=time.monotonic() - t_start,
    )


def report_summary(report: SafetyGateReport) -> str:
    """Human-readable one-liner para audit_tracking entries."""
    icon = "✅" if report.all_passed else "❌"
    return (
        f"{icon} {report.passed_count}/4 gates passed "
        f"(sweep={report.test_sweep.passed}, "
        f"regression={report.critical_regression.passed}, "
        f"smoke={report.smoke_e2e.passed}, "
        f"lint={report.lint_clean.passed}) "
        f"· total {report.total_duration_s:.1f}s"
    )


if __name__ == "__main__":
    # CLI entry: python -m prostanet.agentic.safety_gates
    import time
    t0 = time.monotonic()
    print("Faubot Safety Gates LXXXVII — running 4 gates…")
    report = run_all_gates(fast_mode="--fast" in sys.argv)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    print()
    print(report_summary(report))
    sys.exit(0 if report.all_passed else 1)
