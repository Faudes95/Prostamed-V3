"""Faubot Agentic Loop — improvement infrastructure for ProstaMed.

Two iteration tracks:

1. **Generic loop** (LXXXVII): observes patterns in gates_coverage_aggregator +
   decision_audit_history, proposes improvements, validates with safety gates,
   auto-merges if all gates pass, rolls back on production smoke failure.

2. **FDA SaMD Closure Loop** (LXXXVIII+): refactor of (1) where the iterative
   target is reaching 100% in the 7 FDA SaMD compliance pillars (regulatory,
   QMS, IEC 62304, ISO 14971, IMDRF N41, cybersecurity, DHF). See
   `prostanet/agentic/pillars/` (LXXXVIII).

Public API:

    from prostanet.agentic import (
        run_iteration,         # orquestador 8-fase
        SafetyGateReport,      # resultado de validación pre-merge
        IterationResult,       # outcome final con delta
    )

Persistence:
    persistence/proposals_log.jsonl       — cada propuesta + outcome
    persistence/rollback_log.jsonl        — eventos rollback automático
    persistence/compliance_history.jsonl  — solo LXXXVIII+ (snapshots diarios)

Faubot 2026-04-27 LXXXVII bootstrap.
"""
from __future__ import annotations

__version__ = "0.1.0"
__faubot_release__ = "2026-04-27 LXXXVII"

# Lazy imports — modules instantiate heavy deps only when used.
__all__ = [
    "__version__",
    "__faubot_release__",
]
