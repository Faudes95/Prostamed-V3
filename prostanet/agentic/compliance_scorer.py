"""Faubot Agentic Loop — FDA SaMD Compliance Scorer (LXXXVIII).

Calcula compliance score per-pilar (0-100%) + agregado ponderado.

7 pilares FDA SaMD (per `prostanet/CLINICAL_EVIDENCE_2026.md`):

    P1 — Determinación regulatoria & clasificación   (peso 8)
    P2 — QMS (Sistema Gestión de Calidad)             (peso 12)
    P3 — IEC 62304 ciclo de vida                       (peso 18)
    P4 — ISO 14971 + AAMI TIR57 riesgos               (peso 12)
    P5 — Validación clínica IMDRF SaMD N41             (peso 25)
    P6 — Ciberseguridad FDA Premarket Sept 2023        (peso 15)
    P7 — Design History File (DHF) trazable            (peso 10)

Σ pesos = 100 → aggregate ∈ [0, 100].

API pública:

    snapshot = compute_compliance_snapshot()
    print(snapshot.aggregate)             # float 0-100
    print(snapshot.scores["p4"])          # PillarScore para Pilar 4
    print(snapshot.scores["p4"].gaps)     # list[Gap] del pilar
    snapshot.persist()                    # append a compliance_history.jsonl

Cada pilar implementa `Pillar.score(snapshot_ctx) -> PillarScore` y expone
una lista de `Gap` con `kind`, `severity`, `effort_h`, `description`,
`pillar_id`, `evidence_source`.

LXXXVIII bootstrap; refinable durante operación del loop (heuristics ajustables
sin breaking change).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).parent.parent.parent
HISTORY_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "compliance_history.jsonl"


@dataclass
class Gap:
    """Brecha detectada en un pilar — input para gap_prioritizer."""
    pillar_id: int  # 1-7
    kind: str  # e.g., "sop_missing", "fmea_entry_missing", "trial_evidence_missing"
    description: str
    severity: int = 5  # 1-10 (10 = block 510(k) submission)
    effort_h: float = 1.0
    evidence_source: str = ""  # path to file or function reference
    artifact_path: str = ""    # where the fix would be persisted

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PillarScore:
    """Score per pilar."""
    pillar_id: int
    name: str
    score: float  # 0-100
    weight: float
    gaps: list[Gap] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    last_progress_ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar_id": self.pillar_id,
            "name": self.name,
            "score": round(self.score, 2),
            "weight": self.weight,
            "gaps": [g.to_dict() for g in self.gaps[:50]],  # cap for log size
            "gap_count": len(self.gaps),
            "details": self.details,
            "last_progress_ts": self.last_progress_ts,
        }


@dataclass
class ComplianceSnapshot:
    """Snapshot completo en un momento dado."""
    ts: str
    faubot_release: str
    scores: dict[str, PillarScore]  # key = "p1".."p7"
    aggregate: float
    prev_aggregate: float = 0.0
    delta: float = 0.0
    gap_top: str = ""

    @property
    def all_pillars_at_100(self) -> bool:
        return all(p.score >= 100.0 for p in self.scores.values())

    @property
    def total_gaps(self) -> int:
        return sum(len(p.gaps) for p in self.scores.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "faubot_release": self.faubot_release,
            "aggregate": round(self.aggregate, 2),
            "prev_aggregate": round(self.prev_aggregate, 2),
            "delta": round(self.delta, 2),
            "gap_top": self.gap_top,
            "total_gaps": self.total_gaps,
            "all_pillars_at_100": self.all_pillars_at_100,
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
        }

    def persist(self) -> None:
        """Append snapshot a compliance_history.jsonl."""
        HISTORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_LOG.open("a") as f:
            f.write(json.dumps(self.to_dict(), default=str) + "\n")


class Pillar(Protocol):
    """Interface that each pillar module must implement."""
    pillar_id: int
    name: str
    weight: float

    def score(self) -> PillarScore: ...


# Pesos canónicos (suman 100). LXC: re-balanceo P1=8→4, P7=10→4, +P8=10.
# Frontend captura es ahora citizen de primera clase (Pilar 8).
PILLAR_WEIGHTS: dict[str, float] = {
    "p1": 4.0,
    "p2": 12.0,
    "p3": 18.0,
    "p4": 12.0,
    "p5": 25.0,
    "p6": 15.0,
    "p7": 4.0,
    "p8": 10.0,  # Clinical Data Capture Coverage (LXC)
}
# Sanity: 4+12+18+12+25+15+4+10 = 100 ✓


def _load_pillars() -> dict[str, Pillar]:
    """Lazy-import los 8 pillar modules (LXC: +P8 data_capture)."""
    from prostanet.agentic.pillars import (
        pillar_1_regulatory,
        pillar_2_qms,
        pillar_3_lifecycle,
        pillar_4_risk,
        pillar_5_clinical,
        pillar_6_security,
        pillar_7_dhf,
        pillar_8_data_capture,
    )
    return {
        "p1": pillar_1_regulatory.PILLAR,
        "p2": pillar_2_qms.PILLAR,
        "p3": pillar_3_lifecycle.PILLAR,
        "p4": pillar_4_risk.PILLAR,
        "p5": pillar_5_clinical.PILLAR,
        "p6": pillar_6_security.PILLAR,
        "p7": pillar_7_dhf.PILLAR,
        "p8": pillar_8_data_capture.PILLAR,
    }


def _last_snapshot_aggregate() -> float:
    """Reads last entry from compliance_history.jsonl to compute delta."""
    if not HISTORY_LOG.exists() or HISTORY_LOG.stat().st_size == 0:
        return 0.0
    last_line = ""
    with HISTORY_LOG.open() as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        return 0.0
    try:
        return float(json.loads(last_line).get("aggregate", 0.0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0.0


def compute_compliance_snapshot(*, persist: bool = False) -> ComplianceSnapshot:
    """Computa snapshot completo: ejecuta los 7 pillar scorers + agrega.

    Args:
        persist: si True, append a compliance_history.jsonl.

    Returns:
        ComplianceSnapshot con scores per-pilar + aggregate ponderado.
    """
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE

    pillars = _load_pillars()
    scores: dict[str, PillarScore] = {}

    weighted_sum = 0.0
    weight_total = 0.0
    for key, pillar in pillars.items():
        try:
            ps = pillar.score()
        except Exception as exc:
            ps = PillarScore(
                pillar_id=getattr(pillar, "pillar_id", 0),
                name=getattr(pillar, "name", key),
                score=0.0,
                weight=PILLAR_WEIGHTS.get(key, 0.0),
                gaps=[Gap(
                    pillar_id=getattr(pillar, "pillar_id", 0),
                    kind="scorer_failure",
                    description=f"Pillar scorer raised exception: {exc}",
                    severity=10,
                    effort_h=2.0,
                )],
                details={"error": str(exc)},
            )
        scores[key] = ps
        weighted_sum += ps.score * ps.weight
        weight_total += ps.weight

    aggregate = (weighted_sum / weight_total) if weight_total else 0.0
    prev_aggregate = _last_snapshot_aggregate()
    delta = aggregate - prev_aggregate

    # gap_top = pillar.kind del primer gap del pilar con score más bajo
    sorted_pillars = sorted(scores.values(), key=lambda p: p.score)
    gap_top = ""
    for ps in sorted_pillars:
        if ps.gaps:
            gap_top = f"p{ps.pillar_id}.{ps.gaps[0].kind}"
            break

    snapshot = ComplianceSnapshot(
        ts=datetime.now().isoformat(),
        faubot_release=FAUBOT_RELEASE,
        scores=scores,
        aggregate=aggregate,
        prev_aggregate=prev_aggregate,
        delta=delta,
        gap_top=gap_top,
    )
    if persist:
        snapshot.persist()
    return snapshot


def compliance_summary(snapshot: ComplianceSnapshot) -> str:
    """Human-readable one-liner para audit_tracking."""
    icon = "🏆" if snapshot.all_pillars_at_100 else ("📈" if snapshot.delta > 0 else "📊")
    delta_str = f"({snapshot.delta:+.2f}pp)" if snapshot.prev_aggregate else ""
    return (
        f"{icon} Aggregate {snapshot.aggregate:.1f}% {delta_str} · "
        f"{snapshot.total_gaps} gaps · top: {snapshot.gap_top or 'none'} · "
        f"release {snapshot.faubot_release}"
    )


if __name__ == "__main__":
    # CLI: python -m prostanet.agentic.compliance_scorer [--persist]
    import sys
    persist = "--persist" in sys.argv
    print("Faubot Compliance Scorer LXXXVIII — computing snapshot...")
    snap = compute_compliance_snapshot(persist=persist)
    print(json.dumps(snap.to_dict(), indent=2, default=str))
    print()
    print(compliance_summary(snap))
