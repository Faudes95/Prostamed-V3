from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from prostanet.domains.research_intelligence.dynamic_cohorting import (
    get_dynamic_cohort_payload,
)
from prostanet.domains.research_intelligence.research_repository import persist_json_run


DEFAULT_COVARIATES = ["age_at_diagnosis", "baseline_psa", "ecog_score", "high_volume", "metastatic"]


def _load_rows(cohort_id: int) -> tuple[pd.DataFrame, str]:
    cohort = get_dynamic_cohort_payload(cohort_id)
    if not cohort:
        raise ValueError("Cohorte no encontrada.")
    from prostanet.domains.dashboard.dashboard_analytics_service import build_analysis_dataset_payload

    payload = build_analysis_dataset_payload()
    wanted_ids = set(cohort.get("patient_ids", []))
    rows = [row for row in payload.get("analysis_rows", []) if row.get("patient_id") in wanted_ids]
    frame = pd.DataFrame(rows)
    return frame, cohort.get("title") or f"Cohorte {cohort_id}"


def run_propensity_analysis(
    *,
    cohort_id: int,
    treatment_field: str,
    treatment_value: str,
    control_value: str,
    outcome_field: str = "survival_os_event",
    covariates: list[str] | None = None,
    caliper: float = 0.2,
) -> dict[str, Any]:
    covariates = covariates or DEFAULT_COVARIATES
    frame, cohort_label = _load_rows(cohort_id)
    if len(frame) < 20:
        return {
            "eligible": False,
            "reason": "La cohorte es insuficiente para propensity matching robusto.",
            "minimum_recommended_n": 20,
            "cohort_label": cohort_label,
        }
    if treatment_field not in frame.columns:
        return {"eligible": False, "reason": f"No se encontró el campo de tratamiento '{treatment_field}'."}
    study = frame[frame[treatment_field].isin([treatment_value, control_value])].copy()
    if len(study) < 10:
        return {"eligible": False, "reason": "No hay suficientes pacientes expuestos y control para el análisis."}
    study["treated"] = (study[treatment_field] == treatment_value).astype(int)
    if study["treated"].nunique() < 2:
        return {"eligible": False, "reason": "No hay contraste tratamiento-control suficiente."}
    for covariate in covariates:
        if covariate not in study.columns:
            study[covariate] = 0
    X = study[covariates].apply(pd.to_numeric, errors="coerce").fillna(0)
    y = study["treated"].astype(int)
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    study["propensity_score"] = model.predict_proba(X)[:, 1]
    treated = study[study["treated"] == 1].sort_values("propensity_score")
    control = study[study["treated"] == 0].sort_values("propensity_score")
    matched_pairs = []
    used_controls: set[int] = set()
    for _, treated_row in treated.iterrows():
        distances = (control["propensity_score"] - treated_row["propensity_score"]).abs()
        candidates = control.loc[~control.index.isin(used_controls)].copy()
        if candidates.empty:
            continue
        candidates["distance"] = (candidates["propensity_score"] - treated_row["propensity_score"]).abs()
        best = candidates.sort_values("distance").iloc[0]
        if float(best["distance"]) > caliper:
            continue
        used_controls.add(int(best.name))
        matched_pairs.append((treated_row.to_dict(), best.to_dict()))
    balance = []
    for covariate in covariates:
        tx = study.loc[study["treated"] == 1, covariate].astype(float)
        ct = study.loc[study["treated"] == 0, covariate].astype(float)
        pooled_sd = np.sqrt((tx.var(ddof=0) + ct.var(ddof=0)) / 2) if len(tx) and len(ct) else 0
        smd = float((tx.mean() - ct.mean()) / pooled_sd) if pooled_sd else 0.0
        balance.append(
            {
                "covariate": covariate,
                "treated_mean": round(float(tx.mean()) if len(tx) else 0.0, 4),
                "control_mean": round(float(ct.mean()) if len(ct) else 0.0, 4),
                "smd": round(smd, 4),
            }
        )
    outcome_summary = {}
    if outcome_field in study.columns:
        outcome_summary = {
            "treated_rate": round(float(study.loc[study["treated"] == 1, outcome_field].fillna(0).mean()), 4),
            "control_rate": round(float(study.loc[study["treated"] == 0, outcome_field].fillna(0).mean()), 4),
        }
    response = {
        "eligible": True,
        "cohort_key": str(cohort_id),
        "cohort_label": cohort_label,
        "treatment_field": treatment_field,
        "treatment_value": treatment_value,
        "control_value": control_value,
        "covariates": covariates,
        "matched_pairs": len(matched_pairs),
        "balance": balance,
        "outcome_summary": outcome_summary,
        "limitations": [
            "Análisis observacional no aleatorizado.",
            "No sustituye una recomendación terapéutica clínica individual.",
        ],
    }
    persist_json_run("research_propensity_runs", response, run_key=f"psm:{cohort_id}:{treatment_field}:{treatment_value}:{control_value}")
    return response
