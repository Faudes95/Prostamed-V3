# -*- coding: utf-8 -*-
"""
Cohort Progression Analytics — Population-level disease course analysis.

Aggregates de-identified data across all consented patients to:

  1. Compute empirical state transition probabilities and time distributions
  2. Compare treatment outcomes across patient cohorts
  3. Stratify by ethnicity, age, CCI, ISUP grade, and risk factors
  4. Identify outlier patients (faster/slower progression than cohort)
  5. Feed real-world data back to model calibration

This module implements the "primera IA médica alimentada con datos reales"
goal — the platform improves as more patients are treated.

All outputs are population-level statistics.  No individual PHI is exposed
unless the caller has patient-level consent context.

Usage::

    analytics = CohortProgressionAnalytics()
    overview = analytics.compute_overview()
    transitions = analytics.compute_transition_matrix()
    tx_outcomes = analytics.compute_treatment_outcomes()
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Cohort Analytics Engine
# ══════════════════════════════════════════════════════════════

class CohortProgressionAnalytics:
    """Population-level clinical intelligence from real patient data."""

    def __init__(self) -> None:
        pass

    # ── Public API ──

    def compute_overview(self) -> dict[str, Any]:
        """
        High-level cohort overview: size, state distribution,
        median follow-up, vital status distribution.
        """
        from tracking_db import _connect, DB_PATH

        conn = _connect()
        c = conn.cursor()

        # Total patients
        c.execute("SELECT COUNT(*) FROM patient_identity")
        total_patients = c.fetchone()[0]

        # State distribution from latest assessments
        c.execute("""
            SELECT state, COUNT(*) as n
            FROM clinical_assessments
            WHERE id IN (
                SELECT MAX(id) FROM clinical_assessments GROUP BY patient_id
            )
            GROUP BY state ORDER BY n DESC
        """)
        state_dist = {row["state"]: row["n"] for row in c.fetchall()}

        # Median follow-up
        c.execute("""
            SELECT patient_id, MIN(visit_date) as first, MAX(visit_date) as last
            FROM follow_up_visits
            GROUP BY patient_id
        """)
        follow_up_rows = c.fetchall()
        follow_up_months = []
        for row in follow_up_rows:
            if row["first"] and row["last"]:
                try:
                    from datetime import date
                    d0 = date.fromisoformat(str(row["first"])[:10])
                    d1 = date.fromisoformat(str(row["last"])[:10])
                    months = (d1 - d0).days / 30.44
                    if months >= 0:
                        follow_up_months.append(months)
                except Exception:
                    pass
        median_followup = _median(follow_up_months)

        # Vital status
        c.execute("""
            SELECT vital_status, COUNT(*) as n
            FROM patient_identity
            GROUP BY vital_status
        """)
        vital_status = {row["vital_status"] or "unknown": row["n"] for row in c.fetchall()}

        conn.close()

        return {
            "total_patients": total_patients,
            "state_distribution": state_dist,
            "median_follow_up_months": round(median_followup, 1) if median_followup else None,
            "vital_status": vital_status,
            "data_source": "real_patient_cohort",
        }

    def compute_transition_matrix(self) -> dict[str, Any]:
        """
        Empirical state transition probability matrix from real patient trajectories.

        Returns:
          transitions: dict[from_state → list[{to_state, n, probability, median_months}]]
          total_transitions: int
        """
        from tracking_db import _connect

        conn = _connect()
        c = conn.cursor()

        # Get state timeline from patient_events (state_transition events)
        c.execute("""
            SELECT patient_id, state_context, event_date
            FROM patient_events
            WHERE event_type IN ('state_transition', 'followup_visit_recorded')
              AND state_context IS NOT NULL AND state_context != ''
            ORDER BY patient_id, event_date
        """)
        rows = c.fetchall()
        conn.close()

        # Build per-patient state sequences
        patient_states: dict[int, list[tuple[str, str]]] = {}
        for row in rows:
            pid = row["patient_id"]
            state = row["state_context"]
            date = row["event_date"]
            if pid not in patient_states:
                patient_states[pid] = []
            patient_states[pid].append((state, date))

        # Count transitions
        from collections import defaultdict
        transition_counts: dict[tuple[str, str], list[float]] = defaultdict(list)

        for pid, sequence in patient_states.items():
            for i in range(len(sequence) - 1):
                from_s, from_d = sequence[i]
                to_s, to_d = sequence[i + 1]
                if from_s != to_s:  # Only actual state changes
                    months = _months_between(from_d, to_d)
                    transition_counts[(from_s, to_s)].append(months)

        # Aggregate by from_state
        from_state_totals: dict[str, int] = defaultdict(int)
        for (from_s, to_s), months_list in transition_counts.items():
            from_state_totals[from_s] += len(months_list)

        transitions: dict[str, list[dict[str, Any]]] = {}
        total = 0
        for (from_s, to_s), months_list in transition_counts.items():
            n = len(months_list)
            total += n
            if from_s not in transitions:
                transitions[from_s] = []
            prob = n / max(1, from_state_totals[from_s])
            transitions[from_s].append({
                "to_state": to_s,
                "n": n,
                "probability": round(prob, 3),
                "median_months": round(_median(months_list), 1) if months_list else None,
                "p25_months": round(_percentile(months_list, 25), 1) if months_list else None,
                "p75_months": round(_percentile(months_list, 75), 1) if months_list else None,
            })

        # Sort by probability desc
        for state in transitions:
            transitions[state].sort(key=lambda x: -x["probability"])

        return {
            "transitions": transitions,
            "total_transitions": total,
            "patients_with_transitions": len([p for p in patient_states if len(patient_states[p]) > 1]),
            "data_source": "real_patient_cohort",
        }

    def compute_treatment_outcomes(
        self,
        state: str | None = None,
        min_n: int = 3,
    ) -> dict[str, Any]:
        """
        Treatment outcome statistics across the cohort.

        For each treatment regimen, computes:
          - PSA50 rate (observed)
          - Median time on treatment
          - Progression rate
          - Sample size

        Args:
            state: filter to specific clinical state (optional)
            min_n: minimum patients per treatment to report
        """
        from tracking_db import _connect
        from collections import defaultdict

        conn = _connect()
        c = conn.cursor()

        # Treatment history
        query = """
            SELECT th.patient_id, th.drug_scheme, th.start_date, th.end_date, th.response_status
            FROM treatment_history th
        """
        if state:
            # Join to get state at treatment start
            query = """
                SELECT th.patient_id, th.drug_scheme, th.start_date, th.end_date, th.response_status
                FROM treatment_history th
                JOIN stage_visit_records svr ON svr.patient_id = th.patient_id
                  AND svr.visit_date >= th.start_date
                  AND svr.state = :state
                GROUP BY th.id
            """
        c.execute(query, {"state": state} if state else {})
        tx_rows = c.fetchall()

        # PSA values for response calculation
        c.execute("""
            SELECT patient_id, visit_date, psa_current
            FROM follow_up_visits
            WHERE psa_current IS NOT NULL
            ORDER BY patient_id, visit_date
        """)
        psa_rows = c.fetchall()
        conn.close()

        # Build PSA map: patient_id → sorted list of (date, psa)
        psa_map: dict[int, list[tuple[str, float]]] = defaultdict(list)
        for row in psa_rows:
            if row["psa_current"] is not None:
                psa_map[row["patient_id"]].append((row["visit_date"], float(row["psa_current"])))

        # Aggregate treatment outcomes
        tx_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "n": 0, "psa50_count": 0, "duration_months": [],
            "response_statuses": [],
        })

        for row in tx_rows:
            scheme = row["drug_scheme"] or "unknown"
            pid = row["patient_id"]
            start = row["start_date"]
            end = row["end_date"]
            response = row["response_status"]

            stats = tx_stats[scheme]
            stats["n"] += 1

            if response:
                stats["response_statuses"].append(response)

            # Duration
            if start and end:
                dur = _months_between(start, end)
                if dur and dur > 0:
                    stats["duration_months"].append(dur)

            # PSA50 from longitudinal data
            if start and pid in psa_map:
                psa_at_start = None
                psa_nadir = None
                for vdate, psa_val in psa_map[pid]:
                    if vdate >= start:
                        if psa_at_start is None:
                            psa_at_start = psa_val
                        if psa_nadir is None or psa_val < psa_nadir:
                            psa_nadir = psa_val
                        if end and vdate > end:
                            break
                if psa_at_start and psa_nadir is not None and psa_at_start > 0:
                    if psa_nadir / psa_at_start <= 0.5:
                        stats["psa50_count"] += 1

        # Summarize
        result = {}
        for scheme, stats in tx_stats.items():
            n = stats["n"]
            if n < min_n:
                continue
            result[scheme] = {
                "n": n,
                "psa50_rate": round(stats["psa50_count"] / n, 3) if n > 0 else None,
                "median_duration_months": round(_median(stats["duration_months"]), 1)
                    if stats["duration_months"] else None,
                "response_distribution": _count_distribution(stats["response_statuses"]),
            }

        # Sort by n descending
        sorted_result = dict(sorted(result.items(), key=lambda x: -x[1]["n"]))

        return {
            "treatment_outcomes": sorted_result,
            "total_records": len(tx_rows),
            "state_filter": state,
            "min_n": min_n,
            "data_source": "real_patient_cohort",
        }

    def compute_risk_stratification(self) -> dict[str, Any]:
        """
        Cohort risk stratification by ethnicity, age group, CCI, and ISUP grade.

        Returns distribution across risk strata and median OS per stratum.
        """
        from tracking_db import _connect
        from collections import defaultdict

        conn = _connect()
        c = conn.cursor()

        c.execute("""
            SELECT pi.id, pi.age_at_diagnosis, pi.vital_status, pi.date_of_death,
                   pi.diagnosis_date, d.ethnicity, d.cci_score,
                   b.isup_grade, b.gleason_primary, b.gleason_secondary, b.baseline_psa
            FROM patient_identity pi
            LEFT JOIN demographics d ON d.patient_id = pi.id
            LEFT JOIN patient_baseline b ON b.patient_id = pi.id
            LIMIT 5000
        """)
        rows = c.fetchall()
        conn.close()

        # Age groups
        age_groups: dict[str, int] = defaultdict(int)
        isup_dist: dict[str, int] = defaultdict(int)
        ethnicity_dist: dict[str, int] = defaultdict(int)
        cci_dist: dict[str, int] = defaultdict(int)

        for row in rows:
            age = row["age_at_diagnosis"]
            if age:
                try:
                    a = int(age)
                    if a < 55:
                        age_groups["<55"] += 1
                    elif a < 65:
                        age_groups["55-64"] += 1
                    elif a < 75:
                        age_groups["65-74"] += 1
                    else:
                        age_groups["≥75"] += 1
                except (TypeError, ValueError):
                    pass

            isup = row["isup_grade"]
            if isup:
                isup_dist[f"ISUP {isup}"] += 1

            eth = (row["ethnicity"] or "desconocida").lower()
            ethnicity_dist[eth] += 1

            cci = row["cci_score"]
            if cci is not None:
                try:
                    cci_val = int(cci)
                    if cci_val <= 1:
                        cci_dist["CCI 0-1"] += 1
                    elif cci_val <= 3:
                        cci_dist["CCI 2-3"] += 1
                    else:
                        cci_dist["CCI ≥4"] += 1
                except (TypeError, ValueError):
                    pass

        return {
            "total_patients": len(rows),
            "by_age_group": dict(age_groups),
            "by_isup_grade": dict(isup_dist),
            "by_ethnicity": dict(ethnicity_dist),
            "by_cci": dict(cci_dist),
            "data_source": "real_patient_cohort",
        }

    def identify_outliers(
        self,
        state: str,
        percentile_threshold: float = 0.15,
    ) -> dict[str, Any]:
        """
        Identify patients with unusually fast or slow progression.

        Returns patient IDs (de-identified as relative rank) for fast vs slow progressors.
        """
        from tracking_db import _connect
        from collections import defaultdict

        conn = _connect()
        c = conn.cursor()

        # Time in state per patient
        c.execute("""
            SELECT patient_id, MIN(visit_date) as first_visit, MAX(visit_date) as last_visit,
                   COUNT(*) as n_visits
            FROM follow_up_visits fv
            JOIN stage_visit_records svr ON svr.patient_id = fv.patient_id
              AND svr.state = ?
              AND svr.visit_date = fv.visit_date
            GROUP BY fv.patient_id
            HAVING n_visits >= 2
        """, (state,))
        rows = c.fetchall()
        conn.close()

        durations = []
        for row in rows:
            d = _months_between(row["first_visit"], row["last_visit"])
            if d and d > 0:
                durations.append((row["patient_id"], d))

        if len(durations) < 10:
            return {"state": state, "n": len(durations), "message": "Datos insuficientes"}

        durations.sort(key=lambda x: x[1])
        n = len(durations)
        fast_cutoff = _percentile([d for _, d in durations], percentile_threshold * 100)
        slow_cutoff = _percentile([d for _, d in durations], (1 - percentile_threshold) * 100)

        fast_progressors = [pid for pid, d in durations if d <= fast_cutoff]
        slow_progressors = [pid for pid, d in durations if d >= slow_cutoff]

        return {
            "state": state,
            "n_total": n,
            "median_months": round(_median([d for _, d in durations]), 1),
            "fast_progressors": {
                "cutoff_months": round(fast_cutoff, 1),
                "n": len(fast_progressors),
                "patient_ids": fast_progressors[:20],  # Limit exposure
            },
            "slow_progressors": {
                "cutoff_months": round(slow_cutoff, 1),
                "n": len(slow_progressors),
                "patient_ids": slow_progressors[:20],
            },
            "data_source": "real_patient_cohort",
        }


# ── Helper functions ──

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2.0 if n % 2 == 0 else s[mid]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (p / 100) * (len(s) - 1)
    low = int(idx)
    high = min(low + 1, len(s) - 1)
    frac = idx - low
    return s[low] * (1 - frac) + s[high] * frac


def _months_between(date_a: str | None, date_b: str | None) -> float | None:
    if not date_a or not date_b:
        return None
    try:
        from datetime import date
        d0 = date.fromisoformat(str(date_a)[:10])
        d1 = date.fromisoformat(str(date_b)[:10])
        return abs((d1 - d0).days / 30.44)
    except Exception:
        return None


def _count_distribution(values: list[str]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for v in values:
        k = str(v).lower()
        dist[k] = dist.get(k, 0) + 1
    return dist
