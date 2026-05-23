"""factspec_alias_audit.py — EPIC 45 FAUBOT 2026-05-17 CXXX

Auditoría sistémica de contradicciones FactSpec alias para ProstaNet.

PROBLEMA QUE RESUELVE (urólogo, paciente Frin):
  El sistema persiste facts clínicos en `patient_clinical_facts` con
  `fact_key` (e.g., "metastatic_stage_resolved"). Cuando un fact tiene
  legacy_aliases (e.g., "m_substage_resolved"), AMBOS pueden estar
  `is_active=1` simultáneamente con valores contradictorios:

    metastatic_stage_resolved = M0   is_active=1 (antiguo, derivado)
    m_substage_resolved       = M1b  is_active=1 (reciente, correcto)

  Consumers downstream (Patient Twin OS, decision_today_fusion_kernel,
  clinical_compass) leen distintos fact_keys → recomendaciones
  contradictorias entre cards. Para el paciente 480 (Frin):
    - Patient Twin OS leyó M0 → rankeó Abiraterona #1 (asumió no-mets)
    - Clinical Compass leyó M1b → recomendó "Priorizar ADT+Enzalutamida"
    - Decision Fusion EPIC 23 detectó la contradicción severity=high

  Lo arreglamos a mano vía SQL para 1 paciente. Este módulo generaliza
  la corrección a TODOS los pacientes vía detector + auto-resolver
  con provenance auditable (21 CFR Part 11 §11.10(e) + IEC 62304 §5.1.6).

ALCANCE:
  - 42 alias groups detectados en FACT_SPECS (15 blocking)
  - Ejecutable como CLI (--dry-run / --apply) o vía REST API
  - Auto-resolution con regla de precedencia auditable:
      1) Más reciente por updated_at gana
      2) Tie-break: classifier-derived > user-entered > legacy_import
  - Cada deactivación queda con verification_note explicativo +
    audit entry en `clinical_view_audit` con FAUBOT release SHA

OUT OF SCOPE (EPIC 45.2 futuro):
  - Auto re-clasificación del paciente tras corrección (delegado a
    build_patient_profile_view_model que ya recomputea on read)
  - Notificación al clínico cuando se aplica un fix (delegado a
    panel data_integrity en patient profile)
  - Resolución de contradicciones entre fact_keys NO-alias (e.g., dos
    PSA values mismo fact_key con valores muy diferentes — eso es
    deduplicación, no contradicción de aliases)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from prostanet.shared.clinical_fact_registry import FACT_SPECS


# ─────────────────────────────────────────────────────────────────────────────
# Precedence rules for auto-resolution
# ─────────────────────────────────────────────────────────────────────────────

# Higher = wins. Source types not in this dict get DEFAULT_SOURCE_PRECEDENCE.
SOURCE_TYPE_PRECEDENCE: dict[str, int] = {
    "clinician_verified": 100,  # explicit clinician confirmation (highest)
    "clinician_correction": 90,
    "voice_dictation": 80,       # urólogo dictó (high trust)
    "manual_intake": 70,         # urólogo capturó en form
    "form_capture": 70,
    "clinical_form": 70,
    "classifier_derived": 60,    # state_classifier outputs (canonical)
    "derived": 55,
    "auto_derived": 55,
    "api_import": 40,
    "csv_import": 30,
    "bulk_import": 25,
    "legacy_import": 20,
    "unknown": 10,
}
DEFAULT_SOURCE_PRECEDENCE = 50

# Severity heuristic: if the alias_group canonical fact is blocking,
# the contradiction blocks downstream gates → severity high.
SEVERITY_BLOCKING = "high"
SEVERITY_NON_BLOCKING = "medium"


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AliasGroup:
    """Grupo de fact_keys equivalentes según FACT_SPECS.legacy_aliases."""
    canonical: str
    members: frozenset[str]
    blocking: bool
    domain: str

    def __contains__(self, fact_key: str) -> bool:
        return fact_key in self.members


@dataclass
class FactRow:
    """Representación normalizada de una fila de patient_clinical_facts."""
    fact_id: int
    fact_key: str
    normalized_value_text: str | None
    source_type: str
    updated_at: str
    observed_at: str | None
    is_active: bool


@dataclass
class Contradiction:
    """Contradicción detectada en un patient_id para un alias_group."""
    patient_id: int
    alias_group_canonical: str
    alias_group_members: tuple[str, ...]
    severity: str
    active_rows: list[FactRow] = field(default_factory=list)
    distinct_values: tuple[str, ...] = field(default_factory=tuple)
    detected_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["alias_group_members"] = list(self.alias_group_members)
        d["distinct_values"] = list(self.distinct_values)
        d["active_rows"] = [asdict(r) for r in self.active_rows]
        return d


@dataclass
class Resolution:
    """Resolución aplicada (o propuesta en dry_run) a una contradicción."""
    contradiction: Contradiction
    winner_fact_id: int
    winner_value: str | None
    loser_fact_ids: list[int]
    rule_invoked: str
    verification_note: str
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction": self.contradiction.to_dict(),
            "winner_fact_id": self.winner_fact_id,
            "winner_value": self.winner_value,
            "loser_fact_ids": self.loser_fact_ids,
            "rule_invoked": self.rule_invoked,
            "verification_note": self.verification_note,
            "applied": self.applied,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Alias group construction
# ─────────────────────────────────────────────────────────────────────────────

def get_alias_groups() -> list[AliasGroup]:
    """Construye AliasGroup por cada FactSpec con legacy_aliases no vacíos.

    Returns:
        Lista ordenada por canonical name. Cada grupo contiene el canonical
        + todos sus legacy_aliases como members.
    """
    groups: list[AliasGroup] = []
    for canonical, spec in FACT_SPECS.items():
        if not spec.legacy_aliases:
            continue
        members = frozenset({canonical} | set(spec.legacy_aliases))
        groups.append(AliasGroup(
            canonical=canonical,
            members=members,
            blocking=spec.blocking,
            domain=spec.domain,
        ))
    groups.sort(key=lambda g: g.canonical)
    return groups


def _build_factkey_to_canonical_index(
    groups: Iterable[AliasGroup],
) -> dict[str, AliasGroup]:
    """Index inverso: fact_key → AliasGroup al que pertenece."""
    index: dict[str, AliasGroup] = {}
    for group in groups:
        for member in group.members:
            # NOTA: algunos legacy_aliases (e.g., "psa") son compartidos por
            # múltiples canonicals (baseline_psa Y current_psa). En ese caso
            # gana el primero alfabético — el resolver real es responsable
            # de no escribir el alias compartido para múltiples canonicals.
            if member not in index:
                index[member] = group
    return index


# ─────────────────────────────────────────────────────────────────────────────
# Contradiction detection
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_fact_row(row: dict[str, Any]) -> FactRow:
    """Coerce SQLite Row / dict a FactRow inmutable."""
    return FactRow(
        fact_id=int(row.get("id") or row.get("fact_id") or 0),
        fact_key=str(row.get("fact_key") or "").strip(),
        normalized_value_text=(
            str(row["normalized_value_text"])
            if row.get("normalized_value_text") is not None
            else None
        ),
        source_type=str(row.get("source_type") or "unknown").strip(),
        updated_at=str(row.get("updated_at") or row.get("created_at") or ""),
        observed_at=(
            str(row["observed_at"])
            if row.get("observed_at") is not None
            else None
        ),
        is_active=bool(row.get("is_active", 1)),
    )


def _values_concordant(values: Sequence[str | None]) -> bool:
    """Considera valores como concordantes si todos los no-nulos son idénticos.

    Reglas:
      - None / "" / "null" → ignorados (presencia parcial es OK)
      - Comparación case-insensitive + trimmed (M1b == m1b == "  M1b  ")
      - Si tras normalizar queda <=1 valor único, son concordantes
    """
    normalized: set[str] = set()
    for v in values:
        if v is None:
            continue
        s = str(v).strip().lower()
        if s in ("", "null", "none", "unknown", "desconocido"):
            continue
        normalized.add(s)
    return len(normalized) <= 1


def detect_contradictions_for_patient(
    patient_id: int,
    active_fact_rows: Iterable[dict[str, Any]],
    groups: Sequence[AliasGroup] | None = None,
) -> list[Contradiction]:
    """Detecta contradicciones entre alias groups para un paciente.

    Args:
        patient_id: ID del paciente.
        active_fact_rows: iterable de dicts con keys de patient_clinical_facts
            (fact_key, normalized_value_text, source_type, updated_at,
             observed_at, is_active, id).
        groups: alias groups precomputados (si None, se llama get_alias_groups()).

    Returns:
        Lista de Contradiction. Vacía si el paciente no tiene contradicciones.
    """
    groups = list(groups or get_alias_groups())
    index = _build_factkey_to_canonical_index(groups)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Agrupa rows activos por alias_group
    rows_by_group: dict[str, list[FactRow]] = {}
    for raw_row in active_fact_rows:
        row = _normalize_fact_row(raw_row)
        if not row.is_active or not row.fact_key:
            continue
        group = index.get(row.fact_key)
        if group is None:
            continue  # fact sin alias_group → no candidato a contradicción
        rows_by_group.setdefault(group.canonical, []).append(row)

    contradictions: list[Contradiction] = []
    for canonical, rows in rows_by_group.items():
        # Necesitamos ≥2 fact_keys distintos del mismo grupo, activos
        distinct_fact_keys = {r.fact_key for r in rows}
        if len(distinct_fact_keys) < 2:
            continue  # solo un fact_key del grupo está activo (no hay alias collision)
        values = [r.normalized_value_text for r in rows]
        if _values_concordant(values):
            continue  # múltiples fact_keys pero todos con mismo valor → OK
        group = next(g for g in groups if g.canonical == canonical)
        distinct_values = tuple(sorted({
            (v or "").strip()
            for v in values
            if v not in (None, "")
        }))
        contradictions.append(Contradiction(
            patient_id=patient_id,
            alias_group_canonical=canonical,
            alias_group_members=tuple(sorted(group.members)),
            severity=SEVERITY_BLOCKING if group.blocking else SEVERITY_NON_BLOCKING,
            active_rows=rows,
            distinct_values=distinct_values,
            detected_at=now_iso,
        ))
    contradictions.sort(key=lambda c: (
        0 if c.severity == SEVERITY_BLOCKING else 1,
        c.alias_group_canonical,
    ))
    return contradictions


# ─────────────────────────────────────────────────────────────────────────────
# Auto-resolution rules
# ─────────────────────────────────────────────────────────────────────────────

def _row_precedence(row: FactRow) -> int:
    """Mayor = gana. Combina source_type + recency."""
    return SOURCE_TYPE_PRECEDENCE.get(row.source_type, DEFAULT_SOURCE_PRECEDENCE)


def _row_recency_key(row: FactRow) -> str:
    """Para sort estable: updated_at descending (más reciente gana)."""
    return row.updated_at or row.observed_at or ""


def propose_resolution(contradiction: Contradiction) -> Resolution:
    """Aplica reglas de precedencia y devuelve la resolución propuesta.

    Regla 1: más reciente por updated_at gana.
    Regla 2 (tie-break <60s): source_type con mayor SOURCE_TYPE_PRECEDENCE gana.
    Regla 3 (tie-break adicional): fact_key canonical gana sobre alias legacy.

    NO modifica nada — solo propone. Aplicación real en apply_resolution().
    """
    rows = sorted(
        contradiction.active_rows,
        key=lambda r: (_row_recency_key(r), _row_precedence(r)),
        reverse=True,
    )
    winner = rows[0]
    losers = rows[1:]

    # Determine rule invoked
    if len(rows) >= 2 and _row_recency_key(winner) == _row_recency_key(rows[1]):
        rule = "tie_break_source_type"
    else:
        rule = "most_recent_wins"

    # Verification note for the loser rows (audit-grade explicit reason)
    canonical = contradiction.alias_group_canonical
    winner_value_repr = (winner.normalized_value_text or "(null)")
    note_lines = [
        f"[auto-corrected via factspec_alias_audit "
        f"ts={datetime.now(timezone.utc).isoformat()}]",
        f"  reason: alias_group_canonical={canonical}",
        f"  rule: {rule}",
        f"  winner fact_id={winner.fact_id} key={winner.fact_key} "
        f"value={winner_value_repr} source={winner.source_type} "
        f"updated_at={winner.updated_at}",
    ]
    verification_note = " | ".join(note_lines)

    return Resolution(
        contradiction=contradiction,
        winner_fact_id=winner.fact_id,
        winner_value=winner.normalized_value_text,
        loser_fact_ids=[r.fact_id for r in losers],
        rule_invoked=rule,
        verification_note=verification_note,
        applied=False,
    )


def apply_resolution(conn, resolution: Resolution) -> Resolution:
    """Persiste la resolución: marca losers is_active=0 + verification_note +
    superseded_by_fact_id apuntando al winner. NO modifica el winner.

    Audit trail en clinical_view_audit con section_key='data_integrity'.
    """
    if not resolution.loser_fact_ids:
        resolution.applied = True
        return resolution

    cur = conn.cursor()
    # Inactiva losers
    placeholders = ",".join("?" * len(resolution.loser_fact_ids))
    cur.execute(
        f"""
        UPDATE patient_clinical_facts
           SET is_active = 0,
               verification_note = ?,
               superseded_by_fact_id = ?,
               updated_at = CURRENT_TIMESTAMP
         WHERE id IN ({placeholders})
        """,
        (resolution.verification_note, resolution.winner_fact_id,
         *resolution.loser_fact_ids),
    )
    # Audit log entry — EPIC 45.B (FAUBOT CXXXI): si Resolution.action_suffix
    # está seteado (ej. "on_intake"), se concatena al action para distinguir
    # el origen de la resolución (on_intake / cli_apply / manual / etc.)
    _action = f"factspec_alias_resolved:{resolution.contradiction.alias_group_canonical}"
    _suffix = getattr(resolution, "action_suffix", None)
    if _suffix:
        _action = f"{_action}:{_suffix}"
    cur.execute(
        """
        INSERT INTO clinical_view_audit
            (patient_id, section_key, action, importance, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            resolution.contradiction.patient_id,
            "data_integrity",
            _action,
            resolution.contradiction.severity,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    resolution.applied = True
    return resolution


# ─────────────────────────────────────────────────────────────────────────────
# Population-level audit
# ─────────────────────────────────────────────────────────────────────────────

def audit_patient(conn, patient_id: int) -> list[Contradiction]:
    """Carga active facts del paciente y detecta contradicciones."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, fact_key, normalized_value_text, source_type,
               observed_at, updated_at, is_active
          FROM patient_clinical_facts
         WHERE patient_id = ? AND is_active = 1
        """,
        (patient_id,),
    )
    rows = [dict(r) if hasattr(r, "keys") else r for r in cur.fetchall()]
    return detect_contradictions_for_patient(patient_id, rows)


def audit_all_patients(conn) -> dict[str, Any]:
    """Recorre todos los pacientes en patient_identity y reporta.

    Returns:
        {
          'audit_timestamp': iso,
          'faubot_release': str,
          'patients_checked': int,
          'patients_with_contradictions': int,
          'total_contradictions': int,
          'by_severity': {'high': int, 'medium': int},
          'by_alias_group': {canonical: count, ...},
          'patient_summaries': [
              {patient_id, contradiction_count, severities_present, groups_affected},
              ...
          ],
        }
    """
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    cur = conn.cursor()
    cur.execute("SELECT id FROM patient_identity ORDER BY id")
    patient_ids = [int(r[0]) for r in cur.fetchall()]

    summary: dict[str, Any] = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "faubot_release": FAUBOT_RELEASE,
        "patients_checked": len(patient_ids),
        "patients_with_contradictions": 0,
        "total_contradictions": 0,
        "by_severity": {SEVERITY_BLOCKING: 0, SEVERITY_NON_BLOCKING: 0},
        "by_alias_group": {},
        "patient_summaries": [],
    }
    for pid in patient_ids:
        contradictions = audit_patient(conn, pid)
        if not contradictions:
            continue
        summary["patients_with_contradictions"] += 1
        summary["total_contradictions"] += len(contradictions)
        for c in contradictions:
            summary["by_severity"][c.severity] = summary["by_severity"].get(c.severity, 0) + 1
            summary["by_alias_group"][c.alias_group_canonical] = (
                summary["by_alias_group"].get(c.alias_group_canonical, 0) + 1
            )
        summary["patient_summaries"].append({
            "patient_id": pid,
            "contradiction_count": len(contradictions),
            "severities_present": sorted({c.severity for c in contradictions}),
            "groups_affected": sorted({c.alias_group_canonical for c in contradictions}),
        })
    return summary


def resolve_all_patients(conn, dry_run: bool = True) -> dict[str, Any]:
    """Corre detector + propone resolución para todos. Si dry_run=False, aplica.

    Returns:
        {
          'audit_summary': <audit_all_patients output>,
          'resolutions': [Resolution.to_dict(), ...],
          'applied_count': int,
          'dry_run': bool,
        }
    """
    audit_summary = audit_all_patients(conn)
    resolutions: list[Resolution] = []

    cur = conn.cursor()
    cur.execute("SELECT id FROM patient_identity ORDER BY id")
    for (pid,) in cur.fetchall():
        contradictions = audit_patient(conn, int(pid))
        for c in contradictions:
            resolution = propose_resolution(c)
            if not dry_run:
                apply_resolution(conn, resolution)
            resolutions.append(resolution)

    return {
        "audit_summary": audit_summary,
        "resolutions": [r.to_dict() for r in resolutions],
        "applied_count": sum(1 for r in resolutions if r.applied),
        "dry_run": dry_run,
    }


# ─────────────────────────────────────────────────────────────────────────────
# View model integration helpers (consumed by patient_profile_v2)
# ─────────────────────────────────────────────────────────────────────────────

def list_recent_resolutions_for_patient(
    conn, patient_id: int, limit: int = 50,
) -> list[dict[str, Any]]:
    """Lista las correcciones de data_integrity aplicadas a un paciente.

    Lee clinical_view_audit donde section_key='data_integrity'. Útil para
    el panel "Integridad de datos" en patient_profile_v2.html.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at, action, importance
          FROM clinical_view_audit
         WHERE patient_id = ? AND section_key = 'data_integrity'
         ORDER BY created_at DESC
         LIMIT ?
        """,
        (patient_id, limit),
    )
    out = []
    for row in cur.fetchall():
        created_at = row[0] if isinstance(row, tuple) else row["created_at"]
        action = row[1] if isinstance(row, tuple) else row["action"]
        importance = row[2] if isinstance(row, tuple) else row["importance"]
        # action format: "factspec_alias_resolved:<canonical>"
        canonical = (
            action.split(":", 1)[1]
            if ":" in str(action) else str(action)
        )
        out.append({
            "resolved_at": created_at,
            "alias_group_canonical": canonical,
            "severity": importance,
            "action": action,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _format_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"=== FactSpec Alias Audit · FAUBOT {summary['faubot_release']} ===",
        f"Audit timestamp: {summary['audit_timestamp']}",
        f"Patients checked: {summary['patients_checked']}",
        f"Patients with contradictions: {summary['patients_with_contradictions']}",
        f"Total contradictions: {summary['total_contradictions']}",
        "",
        "By severity:",
    ]
    for sev, count in sorted(summary["by_severity"].items()):
        lines.append(f"  {sev}: {count}")
    if summary["by_alias_group"]:
        lines.append("")
        lines.append("By alias group (most frequent):")
        for group, count in sorted(
            summary["by_alias_group"].items(),
            key=lambda kv: -kv[1],
        )[:10]:
            lines.append(f"  {group}: {count} patient(s)")
    return "\n".join(lines)


def _cli_main() -> int:
    import argparse
    import sqlite3
    import sys

    parser = argparse.ArgumentParser(
        description="EPIC 45 — Auditoría FactSpec alias contradictions",
    )
    parser.add_argument(
        "--db", default="prostanet_tracking.db",
        help="Path al sqlite db (default: prostanet_tracking.db)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Aplica auto-resolution. Sin este flag corre en dry-run (solo reporta).",
    )
    parser.add_argument(
        "--patient-id", type=int, default=None,
        help="Limita audit a un paciente. Sin esto, recorre toda la población.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON en lugar de tabla legible.",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.patient_id is not None:
        contradictions = audit_patient(conn, args.patient_id)
        if args.apply:
            for c in contradictions:
                apply_resolution(conn, propose_resolution(c))
        if args.json:
            import json
            print(json.dumps(
                [c.to_dict() for c in contradictions],
                indent=2, ensure_ascii=False, default=str,
            ))
        else:
            print(f"Patient {args.patient_id}: {len(contradictions)} contradicciones")
            for c in contradictions:
                print(f"  [{c.severity}] {c.alias_group_canonical}: "
                      f"values={list(c.distinct_values)} "
                      f"facts={[r.fact_key + '=' + (r.normalized_value_text or 'null') for r in c.active_rows]}")
        return 0

    # Population audit
    result = resolve_all_patients(conn, dry_run=not args.apply)
    if args.json:
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(_format_summary(result["audit_summary"]))
        print(f"\nResolutions proposed: {len(result['resolutions'])}")
        print(f"Resolutions applied: {result['applied_count']} "
              f"({'dry-run, NOT applied' if result['dry_run'] else 'APPLIED to DB'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
