"""Faubot Agentic Loop — Gap Prioritizer (LXXXVIII).

Prioriza gaps con weighted score:

    gap_score = (severity × clinical_impact_factor × pillar_weight × backlog_age_factor) / max(effort_h, 0.1)

- severity: 1-10 (10 = bloquea 510(k))
- clinical_impact_factor: heurística per gap.kind (1.0 default, 1.5 si afecta clínico directo)
- pillar_weight: del compliance_scorer (P1=8, P2=12, ..., P5=25)
- backlog_age_factor: días desde primera detección / 14 (cap 3.0) — escala gap "atorado"
- effort_h: horas estimadas de fix

API:
    top = top_gap(snapshot, history_log_path=None)  # → Gap o None
    ranked = rank_gaps(snapshot)                     # → list[(score, Gap)]
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from prostanet.agentic.compliance_scorer import (
    ComplianceSnapshot, Gap, PILLAR_WEIGHTS, HISTORY_LOG,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROPOSALS_LOG = PROJECT_ROOT / "prostanet" / "agentic" / "persistence" / "proposals_log.jsonl"

# Heurística clínica per-kind (factor 1.0-2.0)
CLINICAL_IMPACT_FACTORS = {
    # Pilar 1 — regulatorio
    "regulatory_doc_missing": 1.2,
    "cds_criteria_incomplete": 1.5,  # if CDS fails, ProstaMed IS device → impact alto
    "iec62304_class_unassigned": 1.3,
    # Pilar 2 — QMS
    "sop_missing": 1.4,
    "qms_roles_unassigned": 1.0,
    "part11_control_missing": 1.4,
    # Pilar 3 — lifecycle
    "iec62304_test_mapping_incomplete": 1.0,
    "sbom_unpinned_dependencies": 1.5,  # CVE risk
    "cve_critical_open": 2.0,
    # Pilar 4 — risk
    "fmea_file_missing": 1.8,
    "fmea_entry_missing": 1.5,  # cada peligro identificado matters clínico
    "fmea_mitigations_incomplete": 1.7,
    # Pilar 5 — clinical
    "trial_evidence_missing": 1.5,
    "retro_validation_missing": 1.6,
    "prospective_protocol_missing": 1.0,  # blocked_human anyway
    "prospective_data_incomplete": 0.5,   # out-of-loop
    # Pilar 6 — security
    "stride_threat_model_missing": 1.5,
    "sbom_missing": 1.5,
    "disclosure_policy_missing": 1.0,
    # Pilar 7 — DHF
    "traceability_matrix_missing": 1.7,
    "traceability_row_missing": 1.4,
    "cr_log_missing": 1.0,
}


def _gap_first_seen(gap: Gap, history_log: Path = HISTORY_LOG) -> datetime | None:
    """Read history to find first appearance of this gap.kind in pillar."""
    if not history_log.exists():
        return None
    target = f"p{gap.pillar_id}.{gap.kind}"
    earliest = None
    try:
        with history_log.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if snap.get("gap_top", "").startswith(f"p{gap.pillar_id}."):
                    if (earliest is None and target in snap.get("gap_top", "")):
                        try:
                            earliest = datetime.fromisoformat(snap["ts"])
                        except (ValueError, TypeError):
                            pass
    except OSError:
        return None
    return earliest


def _backlog_age_factor(gap: Gap, history_log: Path = HISTORY_LOG) -> float:
    """1.0 if new, scales linearly to 3.0 max (gap >42 days old)."""
    first_seen = _gap_first_seen(gap, history_log)
    if first_seen is None:
        return 1.0
    days_old = (datetime.now() - first_seen).days
    return min(1.0 + (days_old / 14.0), 3.0)


def _gap_consecutive_iterations(gap: Gap, *,
                                  proposals_log: Path = PROPOSALS_LOG,
                                  threshold: int = 3) -> int:
    """Count cuántas iteraciones consecutivas el mismo kind apareció sin progreso.

    Si ≥ threshold → loop debe escalar `human_intervention_required`.
    """
    if not proposals_log.exists():
        return 0
    target = f"p{gap.pillar_id}.{gap.kind}"
    consecutive = 0
    try:
        with proposals_log.open() as f:
            for line in reversed(list(f)):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                p = entry.get("proposal") or {}
                p_kind = p.get("kind", "")
                # match per-pillar kind prefix
                if p_kind == gap.kind or p_kind.endswith(f":{gap.kind.split(':')[-1]}"):
                    consecutive += 1
                else:
                    break  # streak broken
    except OSError:
        return 0
    return consecutive


def gap_score(gap: Gap, *, history_log: Path | None = None) -> float:
    """Weighted score for a single gap. Higher = más prioritario."""
    pillar_w = PILLAR_WEIGHTS.get(f"p{gap.pillar_id}", 1.0)
    clinical = CLINICAL_IMPACT_FACTORS.get(gap.kind.split(":")[0], 1.0)
    age = _backlog_age_factor(gap, history_log or HISTORY_LOG)
    return (gap.severity * clinical * pillar_w * age) / max(gap.effort_h, 0.1)


def rank_gaps(snapshot: ComplianceSnapshot) -> list[tuple[float, Gap]]:
    """Returns list de (score, Gap) ordenado descendentemente."""
    all_gaps = []
    for ps in snapshot.scores.values():
        all_gaps.extend(ps.gaps)
    scored = [(gap_score(g), g) for g in all_gaps]
    return sorted(scored, key=lambda x: -x[0])


def top_gap(snapshot: ComplianceSnapshot, *,
              skip_blocked: bool = True,
              skip_human_intervention_threshold: int = 3) -> Gap | None:
    """Pick top gap to address.

    Args:
        skip_blocked: skip gaps con kind containing 'blocked_human' o 'prospective_data_incomplete'
        skip_human_intervention_threshold: skip gaps que aparecieron ≥N iteraciones consecutivas
    """
    ranked = rank_gaps(snapshot)
    for score, gap in ranked:
        # Skip blocked-by-human
        if skip_blocked and any(s in gap.kind for s in ["blocked_human",
                                                         "prospective_data_incomplete"]):
            continue
        # Skip stuck gaps
        if _gap_consecutive_iterations(gap) >= skip_human_intervention_threshold:
            continue
        return gap
    return None


def projection_eta_to_target(snapshot: ComplianceSnapshot, *,
                                target_pct: float = 96.0,
                                mean_delta_per_iter: float = 0.4) -> dict[str, Any]:
    """Estima días + iteraciones para alcanzar target_pct."""
    current = snapshot.aggregate
    if current >= target_pct:
        return {"days_to_target": 0, "iterations": 0, "target_reached": True}
    delta_needed = target_pct - current
    iterations = int(delta_needed / max(mean_delta_per_iter, 0.01)) + 1
    return {
        "current_pct": round(current, 2),
        "target_pct": target_pct,
        "delta_needed_pp": round(delta_needed, 2),
        "iterations": iterations,
        "days_to_target": iterations,  # 1 iter/day default
        "weeks_to_target": round(iterations / 7.0, 1),
        "months_to_target": round(iterations / 30.0, 1),
        "target_reached": False,
    }
