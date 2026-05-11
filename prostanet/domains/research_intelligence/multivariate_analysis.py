from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from prostanet.domains.patient_tracking.survival_analysis import build_cox_analysis_payload
from prostanet.domains.research_intelligence.dynamic_cohorting import (
    get_dynamic_cohort_payload,
)
from prostanet.domains.research_intelligence.research_repository import persist_json_run


DEFAULT_COVARIATES = [
    "age_at_diagnosis",
    "baseline_psa",
    "ecog_score",
    "metastatic",
    "high_volume",
]


def _analysis_rows_for_cohort(cohort_id: int | None = None) -> tuple[list[dict[str, Any]], str]:
    if cohort_id is None:
        from prostanet.domains.dashboard.dashboard_analytics_service import build_analysis_dataset_payload

        payload = build_analysis_dataset_payload()
        return payload.get("analysis_rows", []), "Institucional"
    cohort = get_dynamic_cohort_payload(int(cohort_id))
    if not cohort:
        raise ValueError("Cohorte no encontrada.")
    wanted_ids = set(cohort.get("patient_ids", []))
    from prostanet.domains.dashboard.dashboard_analytics_service import build_analysis_dataset_payload

    payload = build_analysis_dataset_payload()
    rows = [row for row in payload.get("analysis_rows", []) if row.get("patient_id") in wanted_ids]
    return rows, cohort.get("title") or f"Cohorte {cohort_id}"


def build_cox_payload(
    *,
    endpoint: str = "OS",
    cohort_id: int | None = None,
    covariates: list[str] | None = None,
) -> dict[str, Any]:
    rows, cohort_label = _analysis_rows_for_cohort(cohort_id)
    payload = build_cox_analysis_payload(rows, endpoint_type=endpoint)
    response = {
        "analysis_type": "cox",
        "endpoint": endpoint,
        "cohort_key": str(cohort_id or "institutional"),
        "cohort_label": cohort_label,
        "result": payload,
        "requested_covariates": covariates or DEFAULT_COVARIATES,
    }
    persist_json_run("research_multivariate_runs", response, run_key=f"cox:{endpoint}:{cohort_id or 'institutional'}")
    return response


def build_logistic_payload(
    *,
    outcome: str,
    cohort_id: int | None = None,
    covariates: list[str] | None = None,
) -> dict[str, Any]:
    rows, cohort_label = _analysis_rows_for_cohort(cohort_id)
    covariates = covariates or DEFAULT_COVARIATES
    if len(rows) < 20:
        return {
            "analysis_type": "logistic",
            "outcome": outcome,
            "cohort_label": cohort_label,
            "eligible": False,
            "reason": "Cohorte insuficiente para regresión logística multivariada.",
            "minimum_recommended_n": 20,
        }
    frame = pd.DataFrame(rows)
    for covariate in covariates:
        if covariate not in frame.columns:
            frame[covariate] = 0
    if outcome not in frame.columns:
        frame[outcome] = 0
    work = frame[covariates + [outcome]].copy()
    work = work.replace({True: 1, False: 0, "True": 1, "False": 0}).fillna(0)
    y = work[outcome].astype(int)
    if y.nunique() < 2:
        return {
            "analysis_type": "logistic",
            "outcome": outcome,
            "cohort_label": cohort_label,
            "eligible": False,
            "reason": "El outcome no tiene variabilidad suficiente en la cohorte seleccionada.",
        }
    X = work[covariates].apply(pd.to_numeric, errors="coerce").fillna(0)
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)
    proba = model.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, proba) if y.nunique() > 1 else None
    rows_out = []
    for covariate, coef in zip(covariates, model.coef_[0]):
        odds_ratio = math.exp(float(coef))
        rows_out.append(
            {
                "covariate": covariate,
                "coefficient": round(float(coef), 4),
                "odds_ratio": round(odds_ratio, 4),
            }
        )
    response = {
        "analysis_type": "logistic",
        "outcome": outcome,
        "cohort_key": str(cohort_id or "institutional"),
        "cohort_label": cohort_label,
        "eligible": True,
        "covariates": covariates,
        "rows": rows_out,
        "metrics": {
            "auc": round(float(auc), 4) if auc is not None else None,
            "n": int(len(work)),
            "event_count": int(y.sum()),
            "nonevent_count": int((1 - y).sum()),
        },
    }
    persist_json_run("research_multivariate_runs", response, run_key=f"logistic:{outcome}:{cohort_id or 'institutional'}")
    return response
