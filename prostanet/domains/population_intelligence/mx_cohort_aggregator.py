"""MX Cohort Aggregator — EPIC 33.C

Statistical aggregators para cohorte exploratoria poblacional ProstaMed
México. KPI_REGISTRY extensible permite añadir KPIs como tickets atómicos.

Council concessions:
- Critic: SIEMPRE banner "Cohorte exploratoria · NO inferencial"
- Pragmatist: reusar disease_course_outcomes + clinical_facts queries
- DS-Stats: Wilson CI para proporciones, normal CI para medias, suprimir n<5
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from typing import Any, Callable

from prostanet.domains.population_intelligence.suppression import (
    MIN_COHORT_N,
    normal_ci_mean,
    proportion_with_ci,
    suppress_if_below,
)
from prostanet.shared.utc_time import utc_now_iso

logger = logging.getLogger(__name__)

# Canonical ARPI labels used across the platform
ARPI_LABELS = ("ABIRATERONE", "ENZALUTAMIDE", "APALUTAMIDE", "DAROLUTAMIDE")
ARPI_TOKENS_BY_LABEL = {
    "ABIRATERONE": ("ABIRATERONE", "ABI", "ZYTIGA"),
    "ENZALUTAMIDE": ("ENZALUTAMIDE", "ENZA", "XTANDI"),
    "APALUTAMIDE": ("APALUTAMIDE", "APA", "ERLEADA"),
    "DAROLUTAMIDE": ("DAROLUTAMIDE", "DARO", "NUBEQA"),
}


def _db_path() -> str:
    import tracking_db
    return tracking_db.DB_PATH


def _classify_drug_scheme(drug_scheme: str) -> str:
    """Classifies drug_scheme into one of: ARPI label | ADT_ONLY | OTHER."""
    if not drug_scheme:
        return "OTHER"
    s = str(drug_scheme).upper()
    for label, tokens in ARPI_TOKENS_BY_LABEL.items():
        if any(tok in s for tok in tokens):
            return label
    # ADT-only patterns
    if "ADT" in s and not any(
        tok in s for label_toks in ARPI_TOKENS_BY_LABEL.values() for tok in label_toks
    ):
        return "ADT_ONLY"
    return "OTHER"


def _query_active_facts_by_key(fact_key: str) -> list[dict[str, Any]]:
    """Cross-patient query: all active facts with given fact_key."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM patient_clinical_facts WHERE fact_key = ? AND is_active = 1",
            (fact_key,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _total_active_patients() -> int:
    """Total patients with at least 1 record in patient_identity."""
    conn = sqlite3.connect(_db_path())
    try:
        n = conn.execute("SELECT COUNT(*) FROM patient_identity").fetchone()[0]
        return int(n)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# KPI 1: Patients per ARPI (distribution counts)
# ──────────────────────────────────────────────────────────────────────

def aggregate_patients_by_regimen() -> dict[str, Any]:
    """Counts per ARPI + ADT-only + others. Suprime n<5 individual.

    EPIC 34.A (Discovery Phase 1 fix) — fuente primaria: `treatment_history`
    table (existe con 57+ rows). Pre-EPIC34 el aggregator buscaba tabla
    inexistente `treatments` y fact_key `current_treatment_regimen` que NO
    se capturaba → dashboard mostraba 0%.

    Estrategia: per paciente, tomar la línea terapéutica MÁS RECIENTE
    (max start_date) de treatment_history. Si no hay treatment_history,
    fallback a fact `current_adt_context` para detectar ADT_ONLY.
    """
    total_n = _total_active_patients()
    counter: Counter[str] = Counter()
    patients_with_regimen: set[int] = set()

    # PRIMARY SOURCE: treatment_history (EPIC 34.A fix)
    try:
        conn = sqlite3.connect(_db_path())
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT t1.patient_id, t1.drug_scheme
                FROM treatment_history t1
                INNER JOIN (
                    SELECT patient_id, MAX(COALESCE(start_date, '0000-00-00')) AS max_start
                    FROM treatment_history
                    GROUP BY patient_id
                ) t2 ON t1.patient_id = t2.patient_id
                   AND COALESCE(t1.start_date, '0000-00-00') = t2.max_start
                """
            ).fetchall()
            for r in rows:
                d = dict(r)
                drug = d.get("drug_scheme") or ""
                if not drug or drug == "[object Object]":
                    continue
                label = _classify_drug_scheme(drug)
                counter[label] += 1
                patients_with_regimen.add(d["patient_id"])
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"treatment_history scan failed: {exc}")

    # SECONDARY: fact_key='current_treatment_regimen' (if eventually adopted)
    facts = _query_active_facts_by_key("current_treatment_regimen")
    for f in facts:
        pid = f.get("patient_id")
        if pid in patients_with_regimen:
            continue
        label = _classify_drug_scheme(f.get("normalized_value_text") or "")
        counter[label] += 1
        if pid:
            patients_with_regimen.add(pid)

    # TERTIARY: current_adt_context fact for patients without explicit drug_scheme
    adt_facts = _query_active_facts_by_key("current_adt_context")
    for f in adt_facts:
        pid = f.get("patient_id")
        if pid in patients_with_regimen:
            continue
        ctx = (f.get("normalized_value_text") or "").lower()
        if "medical_adt" in ctx or "surgical" in ctx or "adt" in ctx:
            counter["ADT_ONLY"] += 1
            patients_with_regimen.add(pid)

    breakdown = {}
    for label in (*ARPI_LABELS, "ADT_ONLY", "OTHER"):
        count = counter.get(label, 0)
        prop = proportion_with_ci(count, total_n) if total_n > 0 else {"suppressed": True}
        breakdown[label] = {
            "count": count,
            "suppressed": prop.get("suppressed", True),
            "proportion": prop,
        }

    n_with_regimen = sum(counter.values())
    return {
        "kpi_id": "patients_by_regimen",
        "kpi_label": "Pacientes por ARPI",
        "category": "treatment_distribution",
        "total_patients_in_db": total_n,
        "patients_with_regimen_documented": n_with_regimen,
        "coverage_pct": round(100 * n_with_regimen / max(1, total_n), 1),
        "breakdown": breakdown,
        "computed_at": utc_now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# KPI 2-3: PSA response per ARPI at 8/24 weeks
# ──────────────────────────────────────────────────────────────────────

def aggregate_psa_response_by_regimen(*, weeks: int) -> dict[str, Any]:
    """Mean PSA decline % + PSA50 response rate per ARPI at target window.
    Reads from arpi_response_windows table (cached snapshots from EPIC 33.B).
    Suprime n<5 por ARPI.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT regimen_code, psa_decline_pct, psa50_response
            FROM arpi_response_windows
            WHERE target_weeks = ? AND evidence_quality IN ('in_window', 'closest_outside_window')
            """,
            (weeks,),
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[str, list[dict]] = {label: [] for label in ARPI_LABELS}
    for r in rows:
        label = _classify_drug_scheme(r["regimen_code"] or "")
        if label in ARPI_LABELS:
            grouped[label].append({
                "decline_pct": r["psa_decline_pct"],
                "psa50": bool(r["psa50_response"]),
            })

    breakdown = {}
    for label in ARPI_LABELS:
        data = grouped[label]
        n = len(data)
        declines = [d["decline_pct"] for d in data if d["decline_pct"] is not None]
        psa50_count = sum(1 for d in data if d["psa50"])
        if n < MIN_COHORT_N:
            breakdown[label] = {
                "n": n,
                "suppressed": True,
                "display": f"n<{MIN_COHORT_N} suprimido",
                "mean_decline": None,
                "psa50_rate": None,
            }
        else:
            mean_stats = normal_ci_mean(declines) if declines else {"mean": None}
            psa50_prop = proportion_with_ci(psa50_count, n)
            breakdown[label] = {
                "n": n,
                "suppressed": False,
                "mean_decline_pct": mean_stats,
                "psa50_rate": psa50_prop,
            }
    return {
        "kpi_id": f"psa_response_{weeks}wk",
        "kpi_label": f"Respuesta PSA @ {weeks} semanas ({weeks // 4} meses)",
        "category": "efficacy",
        "target_weeks": weeks,
        "breakdown": breakdown,
        "computed_at": utc_now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# KPI 4: ECOG change per ARPI at 24 weeks
# ──────────────────────────────────────────────────────────────────────

def aggregate_ecog_change_by_regimen(*, weeks: int = 24) -> dict[str, Any]:
    """Mean ECOG change baseline → @ window per ARPI.
    Negative = improvement, 0 = stable, positive = decline.
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT regimen_code, ecog_change_from_baseline
            FROM arpi_response_windows
            WHERE target_weeks = ? AND ecog_change_from_baseline IS NOT NULL
            """,
            (weeks,),
        ).fetchall()
    finally:
        conn.close()
    grouped: dict[str, list[int]] = {label: [] for label in ARPI_LABELS}
    for r in rows:
        label = _classify_drug_scheme(r["regimen_code"] or "")
        if label in ARPI_LABELS:
            grouped[label].append(int(r["ecog_change_from_baseline"]))

    breakdown = {}
    for label in ARPI_LABELS:
        changes = grouped[label]
        n = len(changes)
        if n < MIN_COHORT_N:
            breakdown[label] = {"n": n, "suppressed": True,
                                "display": f"n<{MIN_COHORT_N} suprimido"}
        else:
            improved = sum(1 for c in changes if c < 0)
            stable = sum(1 for c in changes if c == 0)
            worsened = sum(1 for c in changes if c > 0)
            breakdown[label] = {
                "n": n,
                "suppressed": False,
                "mean_change": normal_ci_mean([float(c) for c in changes]),
                "improved_pct": proportion_with_ci(improved, n),
                "stable_pct": proportion_with_ci(stable, n),
                "worsened_pct": proportion_with_ci(worsened, n),
            }
    return {
        "kpi_id": f"ecog_change_{weeks}wk",
        "kpi_label": f"Cambio ECOG @ {weeks} semanas",
        "category": "qol",
        "target_weeks": weeks,
        "breakdown": breakdown,
        "computed_at": utc_now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# KPI 5: Distribution by clinical_state
# ──────────────────────────────────────────────────────────────────────

def aggregate_clinical_state_distribution() -> dict[str, Any]:
    """Cuenta pacientes por reconciled_state (54 estados taxonomía EPIC 22c)."""
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        # Try latest_assessment table first
        rows = []
        try:
            rows = conn.execute(
                """
                SELECT la.state, COUNT(DISTINCT la.patient_id) AS n
                FROM latest_assessment la
                WHERE la.state IS NOT NULL AND la.state != ''
                GROUP BY la.state
                ORDER BY n DESC
                """
            ).fetchall()
        except Exception:
            pass
        if not rows:
            # Fallback: clinical_facts.fact_key='reconciled_state'
            facts = _query_active_facts_by_key("reconciled_state")
            counter: Counter[str] = Counter()
            for f in facts:
                state = f.get("normalized_value_text") or ""
                if state:
                    counter[state] += 1
            rows = [{"state": s, "n": n} for s, n in counter.most_common()]
    finally:
        conn.close()

    breakdown = []
    total_classified = 0
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        n = int(d.get("n", 0))
        total_classified += n
        suppressed = n < MIN_COHORT_N
        breakdown.append({
            "state": d.get("state"),
            "n": n if not suppressed else None,
            "display": f"n<{MIN_COHORT_N} suprimido" if suppressed else str(n),
            "suppressed": suppressed,
        })
    total_n = _total_active_patients()
    return {
        "kpi_id": "clinical_state_distribution",
        "kpi_label": "Distribución por estado clínico (54 estados)",
        "category": "epidemiology",
        "total_patients_in_db": total_n,
        "total_classified": total_classified,
        "coverage_pct": round(100 * total_classified / max(1, total_n), 1),
        "states_documented": len(breakdown),
        "breakdown": breakdown[:30],  # top 30 to keep payload sane
        "computed_at": utc_now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────
# KPI_REGISTRY — Framework extensible para añadir KPIs como tickets atómicos
# ──────────────────────────────────────────────────────────────────────

KPI_REGISTRY: dict[str, dict[str, Any]] = {
    "patients_by_regimen": {
        "label": "Pacientes por ARPI",
        "category": "treatment_distribution",
        "builder": aggregate_patients_by_regimen,
        "args": {},
    },
    "psa_response_8wk": {
        "label": "Respuesta PSA @ 2 meses",
        "category": "efficacy",
        "builder": lambda: aggregate_psa_response_by_regimen(weeks=8),
        "args": {"weeks": 8},
    },
    "psa_response_24wk": {
        "label": "Respuesta PSA @ 6 meses",
        "category": "efficacy",
        "builder": lambda: aggregate_psa_response_by_regimen(weeks=24),
        "args": {"weeks": 24},
    },
    "ecog_change_24wk": {
        "label": "Cambio ECOG @ 6 meses por ARPI",
        "category": "qol",
        "builder": lambda: aggregate_ecog_change_by_regimen(weeks=24),
        "args": {"weeks": 24},
    },
    "clinical_state_distribution": {
        "label": "Distribución por estado clínico",
        "category": "epidemiology",
        "builder": aggregate_clinical_state_distribution,
        "args": {},
    },
}


def populate_arpi_response_windows_for_cohort(
    *,
    weeks_list: tuple[int, ...] = (8, 24),
    force_recompute: bool = False,
) -> dict[str, Any]:
    """EPIC 34.A — Pre-compute arpi_response_windows snapshots para toda la
    cohorte con tratamiento ARPI documentado. Sin esto, las KPIs psa_response_*
    leen tabla vacía → suprimidas todas como n<5.

    Por cada (patient, weeks) computa response usando compute_arpi_response_at_window
    + upserta en tabla arpi_response_windows. Returns: stats summary.
    """
    from prostanet.domains.patient_tracking.arpi_response_window import (
        compute_arpi_response_at_window,
    )
    import tracking_db

    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        # Get all patients with ARPI in treatment_history
        arpi_patients = conn.execute(
            """
            SELECT DISTINCT patient_id
            FROM treatment_history
            WHERE drug_scheme IS NOT NULL
              AND drug_scheme != ''
              AND drug_scheme != '[object Object]'
              AND (drug_scheme LIKE '%ABIRATERONE%' OR drug_scheme LIKE '%ENZALUTAMIDE%'
                   OR drug_scheme LIKE '%APALUTAMIDE%' OR drug_scheme LIKE '%DAROLUTAMIDE%')
            """
        ).fetchall()
    finally:
        conn.close()

    stats = {
        "patients_scanned": len(arpi_patients),
        "windows_computed": 0,
        "windows_with_data": 0,
        "errors": 0,
        "per_evidence_quality": {},
    }
    for row in arpi_patients:
        pid = row["patient_id"]
        try:
            patient_data = tracking_db.get_patient_full_record(pid)
            if not patient_data:
                continue
            # Hydrate clinical_facts (need full history for ECOG)
            identity_id = (patient_data.get("identity") or {}).get("id") or pid
            patient_data["clinical_facts"] = tracking_db.get_patient_clinical_facts(
                identity_id, active_only=False,
            )
            for weeks in weeks_list:
                result = compute_arpi_response_at_window(patient_data, weeks=weeks)
                stats["windows_computed"] += 1
                quality = result.get("evidence_quality", "unknown")
                stats["per_evidence_quality"][quality] = (
                    stats["per_evidence_quality"].get(quality, 0) + 1
                )
                if result.get("available"):
                    stats["windows_with_data"] += 1
                    _upsert_arpi_response_window(identity_id, weeks, result)
        except Exception as exc:
            stats["errors"] += 1
            logger.debug(f"populate_arpi_response_windows error pid={pid}: {exc}")
    stats["completed_at"] = utc_now_iso()
    return stats


def _upsert_arpi_response_window(patient_id: int, weeks: int, result: dict) -> None:
    """Upsert one snapshot into arpi_response_windows."""
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute(
            """
            INSERT INTO arpi_response_windows (
                patient_id, regimen_code, target_weeks, target_date,
                line_start_date, baseline_psa, actual_psa, actual_psa_date,
                psa_decline_pct, psa50_response, psa90_response,
                actual_ecog, baseline_ecog, ecog_change_from_baseline,
                window_offset_days, evidence_quality, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id, regimen_code, target_weeks) DO UPDATE SET
                target_date = excluded.target_date,
                baseline_psa = excluded.baseline_psa,
                actual_psa = excluded.actual_psa,
                actual_psa_date = excluded.actual_psa_date,
                psa_decline_pct = excluded.psa_decline_pct,
                psa50_response = excluded.psa50_response,
                psa90_response = excluded.psa90_response,
                actual_ecog = excluded.actual_ecog,
                baseline_ecog = excluded.baseline_ecog,
                ecog_change_from_baseline = excluded.ecog_change_from_baseline,
                window_offset_days = excluded.window_offset_days,
                evidence_quality = excluded.evidence_quality,
                computed_at = excluded.computed_at
            """,
            (
                patient_id,
                str(result.get("regimen_code") or ""),
                weeks,
                str(result.get("target_date") or ""),
                str(result.get("line_start_date") or ""),
                result.get("baseline_psa"),
                result.get("actual_psa"),
                str(result.get("actual_psa_date") or "") if result.get("actual_psa_date") else None,
                result.get("psa_decline_pct"),
                1 if result.get("psa50_response") else 0,
                1 if result.get("psa90_response") else 0,
                result.get("actual_ecog"),
                result.get("baseline_ecog"),
                result.get("ecog_change_from_baseline"),
                result.get("window_offset_days"),
                str(result.get("evidence_quality") or ""),
                str(result.get("computed_at") or utc_now_iso()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def compute_kpi(kpi_id: str) -> dict[str, Any]:
    """Run a registered KPI builder. Returns kpi dict or error."""
    spec = KPI_REGISTRY.get(kpi_id)
    if not spec:
        return {"available": False, "error": f"unknown_kpi:{kpi_id}",
                "registry": list(KPI_REGISTRY.keys())}
    try:
        return spec["builder"]()
    except Exception as exc:
        logger.exception(f"KPI {kpi_id} failed")
        return {"available": False, "error": str(exc), "kpi_id": kpi_id}


def compute_all_kpis(kpi_ids: list[str] | None = None) -> dict[str, Any]:
    """Run all registered KPIs (or subset). Returns dashboard-ready bundle."""
    ids = kpi_ids or list(KPI_REGISTRY.keys())
    bundle: dict[str, Any] = {
        "exploratory_disclaimer": (
            "Cohorte exploratoria · NO evidencia inferencial · n<5 suprimido "
            "(HIPAA Safe Harbor §164.514). Para identificar gaps de captura y "
            "prioridades de investigación, NO usar como evidencia clínica."
        ),
        "computed_at": utc_now_iso(),
        "kpis": {},
        "registry_total": len(KPI_REGISTRY),
        "computed_count": 0,
    }
    for kpi_id in ids:
        bundle["kpis"][kpi_id] = compute_kpi(kpi_id)
        bundle["computed_count"] += 1
    return bundle


__all__ = [
    "KPI_REGISTRY",
    "compute_kpi",
    "compute_all_kpis",
    "aggregate_patients_by_regimen",
    "aggregate_psa_response_by_regimen",
    "aggregate_ecog_change_by_regimen",
    "aggregate_clinical_state_distribution",
    "ARPI_LABELS",
    "_classify_drug_scheme",
]
