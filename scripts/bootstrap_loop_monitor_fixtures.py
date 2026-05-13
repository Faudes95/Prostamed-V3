"""scripts/bootstrap_loop_monitor_fixtures.py — FAUBOT LXCVII.2.

Seed `prostanet_loop_monitor.db` con 30 días de datos sintéticos para
que el dashboard `/loop-monitor` muestre historia inicial al usuario.

Per-vector idempotency: solo seedea vectores con <4 iteraciones.

Uso:
    PYTHONPATH=. /opt/homebrew/bin/python3.12 scripts/bootstrap_loop_monitor_fixtures.py
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta


def main() -> None:
    from prostanet.presentation.loop_monitor import (
        record_iteration,
        get_vector_summary,
        CORE_VECTORS,
    )

    summary = get_vector_summary(days=30)
    vectors_to_seed = [
        v for v in CORE_VECTORS.keys()
        if summary.get(v, {}).get("count", 0) < 4
    ]
    if not vectors_to_seed:
        print("⚠️  All 8 vectors already have ≥4 iterations, skipping bootstrap")
        return
    print(f"🌱 Seeding {len(vectors_to_seed)} vectors: {vectors_to_seed}")

    random.seed(42)
    base_date = datetime.utcnow() - timedelta(days=30)
    iterations_added = 0

    # Vector seed templates (frequency, value range, status logic)
    SEED_PLAN = {
        "clinical_coverage": {
            "frequency_days": 1,
            "metric": "gates_loaded",
            "value_range": (98, 103),
            "status_threshold": 89,
            "notes_template": "Daily Faubot 7-fase audit · {value} gates loaded",
        },
        "ui_ergonomy": {
            "frequency_days": 7,
            "metric": "median_capture_time_seconds",
            "value_range": (180, 280),
            "status_threshold": 240,
            "status_inverse": True,  # Lower is better
            "notes_template": "Median capture time per encounter: {value}s",
        },
        "backend_integrity": {
            "frequency_days": 1,
            "metric": "ui_to_backend_field_coverage_pct",
            "value_range": (95, 100),
            "status_threshold": 95,
            "notes_template": "UI fields → backend canonicalize: {value}%",
        },
        "clinical_evidence": {
            "frequency_days": 7,
            "metric": "trial_refs_url_resolution_pct",
            "value_range": (75, 95),
            "status_threshold": 70,
            "notes_template": "Weekly PubMed evidence refresh: {value}% URLs resolved",
        },
        "recommendation_accuracy": {
            "frequency_days": 7,
            "metric": "5_clinical_cases_pass_count",
            "value_range": (4, 5),
            "status_threshold": 5,
            "notes_template": "Weekly drift detection: {value}/5 synthetic cases pass",
        },
        "fda_samd_compliance": {
            "frequency_days": 7,
            "metric": "audit_trail_coverage_pct",
            "value_range": (80, 95),
            "status_threshold": 85,
            "notes_template": "FDA SaMD audit trail + override + versioning: {value}%",
        },
        "performance_a11y": {
            "frequency_days": 7,
            "metric": "lighthouse_score_avg",
            "value_range": (88, 98),
            "status_threshold": 90,
            "notes_template": "Lighthouse + axe-core / 4 critical routes: avg {value}",
        },
        "status_reporting": {
            "frequency_days": 7,
            "metric": "weekly_kpi_report_generated",
            "value_range": (1, 1),
            "status_threshold": 1,
            "notes_template": "Week KPI exec summary generated",
        },
    }

    for vector in vectors_to_seed:
        plan = SEED_PLAN.get(vector)
        if not plan:
            continue
        freq_days = plan["frequency_days"]
        n_iterations = 30 // freq_days

        for i in range(n_iterations):
            ts = base_date + timedelta(days=i * freq_days)
            value = random.randint(*plan["value_range"])
            inverse = plan.get("status_inverse", False)
            if inverse:
                status = "ok" if value <= plan["status_threshold"] else "warning"
            else:
                status = "ok" if value >= plan["status_threshold"] else "warning"

            record_iteration(
                iteration_id=f"{vector}-{ts.date().isoformat()}-bootstrap",
                vector=vector,
                metric=plan["metric"],
                value=float(value),
                status=status,
                notes=plan["notes_template"].format(value=value),
                faubot_release="LXCVI bootstrap",
            )
            iterations_added += 1

    print(f"✅ Bootstrap loop_monitor: +{iterations_added} iteraciones across {len(vectors_to_seed)} vectors")


if __name__ == "__main__":
    main()
