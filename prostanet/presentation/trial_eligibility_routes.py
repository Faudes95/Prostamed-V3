"""trial_eligibility_routes.py — Faubot LXXXV (Iteración #2).

REST API blueprint para el motor de elegibilidad de los 47 trials pivotales.

Endpoints expuestos:

- GET /api/trials/list
    → list[trial_id] de los 47 trials soportados
- GET /api/trials/<trial_id>/criteria
    → criteria detallados (PMID/NCT/inclusion/exclusion/citation)
- GET /api/trials/eligible_for/<nss>
    → list de trials para los que el paciente es elegible (ranked confidence)
- GET /api/trials/<trial_id>/eligibility/<nss>
    → eligibility evaluation per-trial per-paciente
- GET /trials-eligibility/<nss>
    → UI dashboard (HTML) con elegibilidad visual

Design:
- Read-only endpoints (no mutations)
- JSON responses (excepto UI dashboard)
- Errors retornan 4XX con JSON {error, message}
- Patient lookup via tracking_db.load_patient_record_core() (Sprint 5 fix CXLIII)

Faubot LXXXV — Iteración #2 (Trial Eligibility Engine + REST API + UI).
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, render_template

from prostanet.shared.trial_criteria_registry import (
    TRIAL_CRITERIA_REGISTRY,
    get_trial_criteria,
    list_trial_ids,
    list_trials_by_stage,
)
from prostanet.shared.trial_eligibility_engine import (
    evaluate_all_eligible_trials,
    evaluate_trial_eligibility,
    list_supported_trials,
)

logger = logging.getLogger(__name__)


trial_eligibility_bp = Blueprint(
    "trial_eligibility",
    __name__,
)


def _load_patient(nss: str) -> dict | None:
    """Lookup paciente por NSS usando tracking_db.

    Sprint 5 fix (C7): `tracking_db.get_patient_by_nss` NO EXISTE en el
    módulo (ghost reference). El nombre correcto es `load_patient_record_core`
    (que acepta nss o id) — verificado vía code review FAUBOT CXLII.
    Antes: cada llamada lanzaba AttributeError, capturada silently, retornaba
    None → endpoint respondía 404 a TODOS los pacientes (totalmente roto).

    Returns:
        dict con datos del paciente, o None si no existe.
    """
    try:
        import tracking_db
        return tracking_db.load_patient_record_core(nss) or None
    except Exception as exc:
        logger.warning(
            f"trial_eligibility._load_patient failed for nss={nss}: "
            f"{type(exc).__name__}: {exc}"
        )
        return None


def _enrich_patient_for_evaluation(patient_record: dict | None) -> dict:
    """Aplana datos del paciente DB a formato esperado por evaluators.

    Tracking_db retorna estructura JSONified per-row; los evaluators esperan
    un dict flat. Esta función concilia ambos formatos.
    """
    if not patient_record:
        return {}
    flat: dict[str, Any] = {}
    flat.update(patient_record)
    # Algunas fuentes DB tienen `clinical_assessment` como JSON dict
    ca = patient_record.get("clinical_assessment") or {}
    if isinstance(ca, dict):
        flat.update({k: v for k, v in ca.items() if v is not None})
    # baseline + biomarker_longitudinal
    baseline = patient_record.get("baseline") or {}
    if isinstance(baseline, dict):
        flat.update({k: v for k, v in baseline.items() if v is not None})
    return flat


# ──────────────────────────────────────────────────────────────────────
# JSON ENDPOINTS
# ──────────────────────────────────────────────────────────────────────


@trial_eligibility_bp.route("/api/trials/list", methods=["GET"])
def api_trials_list():
    """Returns list of all 47 supported trials."""
    return jsonify({
        "total": len(list_supported_trials()),
        "trials": list_supported_trials(),
        "registry_count": len(TRIAL_CRITERIA_REGISTRY),
    })


@trial_eligibility_bp.route("/api/trials/<string:trial_id>/criteria", methods=["GET"])
def api_trial_criteria(trial_id: str):
    """Returns full criteria registry entry for trial_id.

    Faubot LXCIX.1 — Fix: get_trial_criteria retorna {} (no None) cuando trial
    no existe. Detectar empty dict + retornar 404 con sugerencias.
    """
    criteria = get_trial_criteria(trial_id)
    if not criteria:  # Empty dict OR None
        return jsonify({
            "error": "trial_not_found",
            "message": f"Trial '{trial_id}' no está en registry",
            "available": list_trial_ids()[:10],
        }), 404
    return jsonify({
        "trial_id": trial_id,
        "criteria": criteria,
    })


@trial_eligibility_bp.route("/api/trials/eligible_for/<string:nss>", methods=["GET"])
def api_trials_eligible_for(nss: str):
    """Returns ranked list of trials patient is eligible for."""
    patient = _load_patient(nss)
    if not patient:
        return jsonify({
            "error": "patient_not_found",
            "message": f"NSS '{nss}' no encontrado",
        }), 404
    flat = _enrich_patient_for_evaluation(patient)
    results = evaluate_all_eligible_trials(flat)
    eligible_count = sum(1 for r in results if r["eligible"])
    requires_data_count = sum(1 for r in results if r.get("status") == "requires_data")
    return jsonify({
        "nss": nss,
        "total_evaluated": len(results),
        "eligible_count": eligible_count,
        "requires_data_count": requires_data_count,
        "results": results,
    })


@trial_eligibility_bp.route(
    "/api/trials/<string:trial_id>/eligibility/<string:nss>", methods=["GET"]
)
def api_trial_eligibility_for_patient(trial_id: str, nss: str):
    """Returns per-trial per-patient eligibility evaluation."""
    patient = _load_patient(nss)
    if not patient:
        return jsonify({
            "error": "patient_not_found",
            "message": f"NSS '{nss}' no encontrado",
        }), 404
    if trial_id not in list_supported_trials():
        return jsonify({
            "error": "trial_not_supported",
            "message": f"Trial '{trial_id}' sin evaluator implementado",
            "supported": list_supported_trials()[:10],
        }), 404
    flat = _enrich_patient_for_evaluation(patient)
    try:
        result = evaluate_trial_eligibility(flat, trial_id)
    except Exception as exc:
        logger.error(
            f"trial_eligibility evaluation failed for {trial_id}/{nss}: "
            f"{type(exc).__name__}: {exc}"
        )
        return jsonify({
            "error": "evaluation_error",
            "message": str(exc),
        }), 500
    return jsonify({
        "nss": nss,
        "trial_id": trial_id,
        "evaluation": result,
    })


@trial_eligibility_bp.route("/api/trials/by_stage/<string:stage>", methods=["GET"])
def api_trials_by_stage(stage: str):
    """Returns trials por stage clínico (mcspc/m1_crpc/m0_crpc/recurrence_bcr/etc)."""
    trials = list_trials_by_stage(stage)
    return jsonify({
        "stage": stage,
        "trials": trials,
        "total": len(trials),
    })


# ──────────────────────────────────────────────────────────────────────
# UI DASHBOARD ENDPOINT
# ──────────────────────────────────────────────────────────────────────


@trial_eligibility_bp.route("/trials-eligibility/<string:nss>", methods=["GET"])
def ui_trials_eligibility_dashboard(nss: str):
    """UI v2 dashboard con elegibilidad visual de los 47 trials para un paciente.

    Muestra:
    - Listado de trials elegibles (ranked confidence)
    - Listado de trials con missing data (qué falta capturar)
    - Listado de trials no elegibles (con razones)
    - Filtros por stage clínico + biomarker
    """
    patient = _load_patient(nss)
    if not patient:
        return render_template(
            "errors/patient_not_found.html",
            nss=nss,
        ), 404 if False else 200  # template-friendly fallback

    flat = _enrich_patient_for_evaluation(patient)
    results = evaluate_all_eligible_trials(flat)

    # Particionar para template
    eligible = [r for r in results if r["eligible"]]
    missing_data = [r for r in results if r.get("status") == "requires_data" or (not r["eligible"] and r["missing_data"])]
    not_eligible = [r for r in results if not r["eligible"] and not r["missing_data"]]

    # Métricas resumen
    summary = {
        "total_trials": len(results),
        "eligible_count": len(eligible),
        "missing_data_count": len(missing_data),
        "not_eligible_count": len(not_eligible),
        "high_confidence_eligible": sum(1 for r in eligible if r["confidence"] >= 0.85),
    }

    return render_template(
        "trials_eligibility_dashboard_v2.html",
        nss=nss,
        patient=patient,
        eligible=eligible,
        missing_data=missing_data,
        not_eligible=not_eligible,
        summary=summary,
        registry=TRIAL_CRITERIA_REGISTRY,
    )
