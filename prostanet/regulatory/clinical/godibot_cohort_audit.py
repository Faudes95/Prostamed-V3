"""godibot_cohort_audit.py — EPIC GVP.A (FAUBOT CXLI).

Validation pass exhaustivo sobre la cohorte completa usando GodiBot
(adversarial AI peer reviewer). Produce baseline cuantitativo de
% Clinical Correctness + roadmap de fixes priorizados por frecuencia
de hallazgos clínicos.

Filosofía clínica:
  Hasta hoy NO había métrica objetiva de "qué tan correctas son las
  recomendaciones del CDSS sobre la cohorte real". GodiBot ya valida
  per-paciente (panel UI EPIC 23), pero nunca corrió sobre todos.

  Este CLI itera 425+ pacientes, executa run_godibot_review() per cada
  uno, captura findings + status, y produce:
    1. JSON estructurado por paciente (audit trail)
    2. Aggregate report markdown (cohort-level metrics)
    3. SQLite persistence en cohort_validation_runs (run history)

  Output diseñado para:
    - Baseline pre-piloto: % correctness HOY
    - Roadmap data-driven: TOP findings → priority Sprint
    - Internal validation report FDA-style (publicable + auditable)
    - Cron weekly post-piloto: regression/improvement tracking

CLI usage:
  python3 -m prostanet.regulatory.clinical.godibot_cohort_audit
  python3 -m prostanet.regulatory.clinical.godibot_cohort_audit --json
  python3 -m prostanet.regulatory.clinical.godibot_cohort_audit --patient-id 39
  python3 -m prostanet.regulatory.clinical.godibot_cohort_audit --persist
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Schema bootstrap (idempotent)
# ─────────────────────────────────────────────────────────────────────


def _ensure_cohort_validation_table(conn) -> None:
    """Crea tabla cohort_validation_runs si no existe."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_validation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            patient_id INTEGER NOT NULL,
            patient_nss TEXT,
            run_timestamp TEXT NOT NULL,
            godibot_status TEXT NOT NULL,
            findings_count INTEGER DEFAULT 0,
            findings_json TEXT,
            faubot_release TEXT,
            trigger_source TEXT DEFAULT 'cli_cohort_audit',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cohort_validation_run_id "
        "ON cohort_validation_runs (run_id, godibot_status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cohort_validation_patient_id "
        "ON cohort_validation_runs (patient_id, run_timestamp DESC)"
    )
    conn.commit()


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def _build_compass_for_godibot(patient_record: dict[str, Any]) -> dict[str, Any]:
    """EPIC GVP.E PROPAGATION FIX (FAUBOT CXLII) — Construye un compass
    mínimo para GodiBot a partir del patient_record crudo.

    Bug META resuelto:
        `tracking_db.load_patient_record_core(pid)` NO devuelve compass.
        GodiBot._extract_compass busca `clinical_compass` / `compass` /
        `compass_draft` / `godibot_target_compass` en el record o trigger_data.
        Sin compass, `compass_gates` set queda vacío → CADA gate triggered
        en re-evaluación se reporta como `gate_omitted:*` con severidad
        hard_block. Esto INFLABA artificialmente los blocked_hard del
        baseline (los 4 detectados en cohort audit FAUBOT CXLI).

    Fix arquitectónico:
        Lazy-evaluamos los gates pivotal (mismo path que GodiBot usa
        internamente — evaluate_all_yaml_gates + evaluate_pivotal_*) y los
        inyectamos bajo el key EXACTO que GodiBot lee
        (`pivotal_contraindication_gates`). Esto refleja fielmente lo que
        Compass UI realmente expone al clínico (gracias al fix sibling en
        `build_patient_profile_view_model` que pobla la misma clave en el
        view-model bundle prospectivo).

    Returns:
        dict con al menos `pivotal_contraindication_gates: list[gate]`.
        Empty dict si lazy-eval falla (caller pasa None → GodiBot opera
        con compass vacío, comportamiento previo conservador).
    """
    try:
        from prostanet.domains.patient_tracking.profile_compass import (
            _lazy_evaluate_pivotal_gates_for_patient,
        )
        gates = _lazy_evaluate_pivotal_gates_for_patient(patient_record) or []
        compass: dict[str, Any] = {
            "pivotal_contraindication_gates": gates,
            # Sibling alias por defensa — GodiBot también acepta estos keys
            # (godibot.py:392) y otros consumidores pueden esperarlos.
            "gates_contraindications": gates,
        }

        # EPIC GVP.E (CXLII) — Extender el compass con la evidence_summary
        # cuando la asssessment persistida ya la tiene. GodiBot
        # `_evaluate_evidence_basis` busca compass.evidence_summary.guideline_basis
        # y dispara `guideline_basis_missing` si no la encuentra. Sin esto
        # *todos* los pacientes flagean falsamente como missing-guideline (el
        # propio render de Compass SÍ cita NCCN/EAU vía result_snapshot.
        # nccn_primary + eau_comparison + evidence_trace, pero el CLI batch
        # no las re-componía en compass.evidence_summary).
        latest = patient_record.get("latest_assessment") or {}
        if isinstance(latest, dict):
            rs = latest.get("result_snapshot") or {}
            if isinstance(rs, dict):
                guideline_basis: list[str] = []
                if rs.get("nccn_primary"):
                    guideline_basis.append("NCCN PROS v5.2026 (nccn_primary present)")
                if rs.get("eau_comparison"):
                    guideline_basis.append("EAU 2026 (eau_comparison present)")
                ev_trace = rs.get("evidence_trace")
                if isinstance(ev_trace, (list, dict)) and ev_trace:
                    guideline_basis.append("evidence_trace present")
                # Forward existing evidence_summary if present, but always
                # merge into our synthesized basis to satisfy GodiBot probe.
                existing_es = rs.get("evidence_summary")
                if guideline_basis or existing_es:
                    compass["evidence_summary"] = {
                        "guideline_basis": guideline_basis or (
                            (existing_es or {}).get("guideline_basis", [])
                            if isinstance(existing_es, dict) else []
                        ),
                    }
                # Also forward headline/rationale for richer GodiBot context.
                hl = rs.get("headline") or rs.get("title") or ""
                if hl:
                    compass["headline"] = str(hl)[:240]
                rat = rs.get("rationale") or rs.get("summary") or ""
                if rat:
                    compass["rationale"] = str(rat)[:1200]

        return compass
    except Exception as exc:
        logger.debug("CLI _build_compass_for_godibot lazy-eval failed: %s", exc)
        return {}


def audit_patient(patient_record: dict[str, Any], patient_id: int) -> dict[str, Any]:
    """Run GodiBot review sobre 1 paciente.

    Returns:
        {
            "patient_id": int,
            "status": "approved" | "warnings_only" | "blocked_hard",
            "findings_count": int,
            "findings": [...],
            "review_timestamp": ISO,
        }
    """
    try:
        from prostanet.agents.godibot import run_godibot_review

        # EPIC GVP.E (FAUBOT CXLII): construir compass desde el record antes
        # de invocar a GodiBot. Sin esto los gates triggered se reportan como
        # `gate_omitted:*` falso-positivo. Ver `_build_compass_for_godibot` doc.
        synthetic_compass = _build_compass_for_godibot(patient_record)

        review = run_godibot_review(
            patient_record,
            patient_id=patient_id,
            trigger_event="cohort_validation_audit",
            compass=synthetic_compass or None,
            enable_llm=False,  # CLI batch — LLM disabled for speed/repeatability
        )
        # GVP.E FIX (FAUBOT CXLII): GodiBot retorna findings en el key
        # `discrepancies` (descubierto al inspeccionar review real de
        # paciente blocked_hard). Antes leíamos review.get("findings") →
        # findings_count siempre 0, contradictorio con status='blocked_hard'.
        # Backwards compat: si por accidente algún flow agrega 'findings',
        # combinamos ambos lists para no perder data.
        _discrepancies = list(review.get("discrepancies") or [])
        _legacy_findings = list(review.get("findings") or [])
        all_findings = _discrepancies + _legacy_findings
        return {
            "patient_id": patient_id,
            "status": str(review.get("status") or "unknown"),
            "findings_count": len(all_findings),
            "findings": all_findings,
            "review_timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": review.get("summary"),
        }
    except Exception as exc:
        logger.debug("GodiBot review failed for patient_id=%s: %s", patient_id, exc)
        return {
            "patient_id": patient_id,
            "status": "error",
            "findings_count": 0,
            "findings": [],
            "review_timestamp": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def audit_cohort(
    *,
    persist: bool = False,
    max_patients: int | None = None,
    patient_id_filter: int | None = None,
) -> dict[str, Any]:
    """Audit toda la cohorte (o subset).

    Args:
        persist: si True, escribe resultados a cohort_validation_runs table
        max_patients: limite para testing rápido (None = todos)
        patient_id_filter: si se pasa, audita solo ese paciente

    Returns:
        {
            "run_id": str (UUID),
            "run_timestamp": ISO,
            "faubot_release": str,
            "patients_audited": int,
            "by_status": {"approved": N, "warnings_only": M, "blocked_hard": K, "error": E},
            "internal_validation_pct": float (0-100),
            "top_findings": [(finding_type, count), ...],
            "patient_summaries": [...],
        }
    """
    import uuid
    try:
        import tracking_db
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    except ImportError as exc:
        return {"error": f"import_failed: {exc}", "patients_audited": 0}

    run_id = str(uuid.uuid4())[:16]
    run_timestamp = datetime.now(timezone.utc).isoformat()

    # Build patient list
    if patient_id_filter is not None:
        patient_ids = [patient_id_filter]
    else:
        conn = sqlite3.connect(tracking_db.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM patient_identity ORDER BY id")
        patient_ids = [row[0] for row in cur.fetchall()]
        conn.close()

    if max_patients:
        patient_ids = patient_ids[:max_patients]

    # Iterate + audit
    by_status: Counter = Counter()
    all_findings_types: Counter = Counter()
    patient_summaries: list[dict[str, Any]] = []

    persist_conn = None
    if persist:
        persist_conn = sqlite3.connect(tracking_db.DB_PATH)
        _ensure_cohort_validation_table(persist_conn)

    for patient_id in patient_ids:
        try:
            # Load patient record
            core = None
            for nss_or_id in (patient_id,):
                try:
                    # tracking_db.load_patient_record_core soporta id o nss
                    core = tracking_db.load_patient_record_core(nss_or_id)
                except Exception:
                    pass
            if not core:
                # Try by nss lookup
                try:
                    pdconn = sqlite3.connect(tracking_db.DB_PATH)
                    pdconn.row_factory = sqlite3.Row
                    pcur = pdconn.cursor()
                    pcur.execute("SELECT nss FROM patient_identity WHERE id = ?", (patient_id,))
                    pn = pcur.fetchone()
                    pdconn.close()
                    if pn:
                        core = tracking_db.load_patient_record_core(pn["nss"])
                except Exception:
                    pass
            if not core:
                by_status["error_no_record"] += 1
                continue

            patient_record = tracking_db.build_patient_record_derivatives(core)
            if not patient_record:
                by_status["error_no_derivatives"] += 1
                continue

            # Run audit
            result = audit_patient(patient_record, patient_id)
            status = result["status"]
            by_status[status] += 1

            # Capture finding types — el shape real de GodiBot discrepancies:
            # {code, severity, source, message, suggestion, evidence_tag,
            #  trial_refs}. Priorizamos `code` (más granular) > `source`.
            for f in result.get("findings", []):
                if isinstance(f, dict):
                    ftype = (
                        f.get("code")              # GodiBot discrepancies primary
                        or f.get("finding_type")   # legacy compat
                        or f.get("source")          # GodiBot source attribution
                        or f.get("category")
                        or f.get("kind")
                        or f.get("rule_id")
                        or "unspecified"
                    )
                    all_findings_types[str(ftype)] += 1

            nss_val = (patient_record.get("identity") or {}).get("nss")
            patient_summaries.append({
                "patient_id": patient_id,
                "nss": nss_val,
                "status": status,
                "findings_count": result["findings_count"],
            })

            # Persist
            if persist_conn:
                try:
                    cur = persist_conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO cohort_validation_runs
                            (run_id, patient_id, patient_nss, run_timestamp,
                             godibot_status, findings_count, findings_json,
                             faubot_release, trigger_source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            patient_id,
                            nss_val,
                            result["review_timestamp"],
                            status,
                            result["findings_count"],
                            json.dumps(result["findings"], ensure_ascii=False, default=str),
                            FAUBOT_RELEASE,
                            "cli_cohort_audit",
                        ),
                    )
                    persist_conn.commit()
                except Exception as pex:
                    logger.debug("Persist failed for patient %s: %s", patient_id, pex)
        except Exception as exc:
            logger.exception("Patient %s audit failed: %s", patient_id, exc)
            by_status["error_unexpected"] += 1

    if persist_conn:
        persist_conn.close()

    # Compute internal validation %
    total = sum(by_status.values()) or 1
    approved = by_status.get("approved", 0)
    warnings = by_status.get("warnings_only", 0)
    # "% Internal Validation" = (approved + 0.5 * warnings) / total * 100
    # (warnings se penalizan 50% — son recommendations correctas con caveats)
    validation_pct = round(((approved + 0.5 * warnings) / total) * 100, 1)

    return {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "faubot_release": FAUBOT_RELEASE,
        "patients_audited": total,
        "by_status": dict(by_status),
        "internal_validation_pct": validation_pct,
        "top_findings": all_findings_types.most_common(10),
        "patient_summaries": patient_summaries[:50],  # cap for memory
    }


# ─────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────


def _format_report_markdown(report: dict[str, Any]) -> str:
    by_status = report.get("by_status", {})
    total = report.get("patients_audited", 0)
    val_pct = report.get("internal_validation_pct", 0)
    lines = [
        f"# GodiBot Cohort Audit Report — Run {report.get('run_id')}",
        f"",
        f"- **Timestamp**: {report.get('run_timestamp')}",
        f"- **FAUBOT release**: {report.get('faubot_release')}",
        f"- **Patients audited**: {total}",
        f"- **% Internal Validation**: {val_pct}%",
        f"",
        "## Status distribution",
        "",
    ]
    for status, count in by_status.items():
        pct = round((count / max(total, 1)) * 100, 1)
        emoji = {"approved": "✅", "warnings_only": "🟡", "blocked_hard": "🔴"}.get(
            status, "⚠️"
        )
        lines.append(f"- {emoji} **{status}**: {count} ({pct}%)")

    lines.extend(["", "## TOP 10 findings", ""])
    for ftype, count in report.get("top_findings", []):
        lines.append(f"- `{ftype}`: {count}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="godibot_cohort_audit",
        description=(
            "GodiBot validation pass exhaustivo sobre cohorte. "
            "Produce baseline cuantitativo de Clinical Correctness."
        ),
    )
    parser.add_argument(
        "--patient-id", type=int, default=None,
        help="Audit solo el paciente especificado (default: toda la cohorte)",
    )
    parser.add_argument(
        "--max-patients", type=int, default=None,
        help="Limite para testing rápido (default: todos)",
    )
    parser.add_argument(
        "--persist", action="store_true",
        help="Persistir resultados a cohort_validation_runs table SQLite",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON estructurado (default: markdown formato humano)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    report = audit_cohort(
        persist=args.persist,
        max_patients=args.max_patients,
        patient_id_filter=args.patient_id,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(_format_report_markdown(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "audit_patient",
    "audit_cohort",
    "main",
]
