"""ProstaMed Clinical Memory & Outcomes Learning OS.

Deterministic longitudinal memory layer for decision -> execution -> outcome
learning. This read model does not train, release, or run a predictive model.
It builds auditable decision episodes, observed outcome context, cohort mirrors
and AI-readiness checks from real patient data only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
from statistics import median
from typing import Any, Iterable, Mapping


OUTCOME_STATUSES = (
    "on_track",
    "mixed",
    "off_track",
    "toxicity_limited",
    "insufficient_data",
    "requires_redecision",
)

MIN_SIMILAR_COHORT_SIZE = 5

PROGRESSION_EVENT_TYPES = {
    "biochemical_progression",
    "radiographic_progression",
    "clinical_progression",
    "visceral_progression",
    "skeletal_event",
    "crpc_confirmed",
    "progression",
}

TOXICITY_EVENT_TYPES = {
    "toxicity_limited",
    "treatment_toxicity",
    "grade3_toxicity",
    "adverse_event_grade3_plus",
}


def build_clinical_memory_os(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
    cohort_records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the official Clinical Memory OS bundle for one patient."""
    patient = deepcopy(dict(patient_record or {}))
    bundle = deepcopy(dict(longitudinal_bundle or {}))
    signals = dict(bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    effective_state = _first_text(
        state,
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        signals.get("reconciled_state"),
        (patient.get("latest_assessment") or {}).get("state"),
        (patient.get("prior_history") or {}).get("current_state"),
        "diagnostic_workup",
    )
    effective_track = _first_text(
        management_track,
        signals.get("effective_management_track_final"),
        signals.get("effective_management_track"),
        signals.get("reconciled_management_track"),
        (patient.get("prior_history") or {}).get("management_track"),
        patient.get("management_track"),
    )
    resolved_ref = _first_text(
        patient_ref,
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        (patient.get("identity") or {}).get("id"),
    )

    tumor_board = dict(
        bundle.get("tumor_board_os")
        or patient.get("tumor_board_os")
        or signals.get("tumor_board_os")
        or {}
    )
    care_pathway = dict(
        bundle.get("care_pathway_os")
        or patient.get("care_pathway_os")
        or signals.get("care_pathway_os")
        or {}
    )
    readiness = dict(
        bundle.get("clinical_readiness_tower")
        or patient.get("clinical_readiness_tower")
        or signals.get("clinical_readiness_tower")
        or {}
    )

    observed = _build_expected_vs_observed(patient, bundle, state=effective_state)
    attribution = _build_outcome_attribution(patient, bundle, observed, state=effective_state)
    cohort_mirror = build_similar_cohort_mirror(
        patient,
        cohort_records=cohort_records,
        state=effective_state,
        management_track=effective_track,
    )
    episodes = _build_decision_episodes(
        patient,
        bundle,
        tumor_board=tumor_board,
        care_pathway=care_pathway,
        readiness=readiness,
        observed=observed,
        attribution=attribution,
        state=effective_state,
        management_track=effective_track,
        patient_ref=resolved_ref,
    )
    learning_signals = _build_learning_signals(patient, bundle, episodes, observed, attribution)
    redecision_reasons = _build_redecision_reasons(episodes, observed, attribution, care_pathway)
    model_dataset = _build_model_readiness_dataset(
        patient,
        bundle,
        episodes=episodes,
        observed=observed,
        attribution=attribution,
        state=effective_state,
        management_track=effective_track,
    )
    ai_readiness = _build_ai_readiness(patient, model_dataset, observed, cohort_mirror, episodes)
    summary = _build_summary(
        episodes,
        observed=observed,
        attribution=attribution,
        cohort_mirror=cohort_mirror,
        ai_readiness=ai_readiness,
        state=effective_state,
        management_track=effective_track,
    )

    return {
        "available": True,
        "source": "clinical_memory_os",
        "version": "clinical_memory_os_v1",
        "patient_ref": resolved_ref,
        "state": effective_state,
        "management_track": effective_track,
        "summary": summary,
        "decision_episodes": episodes,
        "expected_vs_observed": observed,
        "outcome_attribution": attribution,
        "similar_cohort_mirror": cohort_mirror,
        "learning_signals": learning_signals,
        "redecision_reasons": redecision_reasons,
        "ai_readiness": ai_readiness,
        "model_readiness_dataset": model_dataset,
        "audit": {
            "deterministic_v1": True,
            "no_ml_model_trained": True,
            "no_prediction_released": True,
            "no_fabricated_treatment": True,
            "no_fabricated_biomarkers": True,
            "cohort_context_is_non_authoritative": True,
            "clinical_authorities": [
                "classifier",
                "clinical_readiness_tower",
                "tumor_board_os",
                "care_pathway_os",
                "gates",
                "trials",
                "evidence_registry",
            ],
            "sources_used": _dedupe(
                [
                    "tumor_board_os" if tumor_board else "",
                    "care_pathway_os" if care_pathway else "",
                    "clinical_readiness_tower" if readiness else "",
                    "longitudinal_truth_snapshot" if (bundle.get("longitudinal_truth_snapshot") or patient.get("longitudinal_truth_snapshot")) else "",
                    "clinical_fact_bundle" if (bundle.get("clinical_fact_bundle") or patient.get("clinical_fact_bundle")) else "",
                    "patient_events" if patient.get("patient_events") else "",
                    "stage_visit_records" if patient.get("stage_visits") else "",
                    "biomarker_longitudinal" if patient.get("biomarker_longitudinal") else "",
                    "treatment_history" if patient.get("treatments") else "",
                    "outcome_events" if (bundle.get("outcome_events") or patient.get("outcome_events")) else "",
                    "treatment_adverse_events" if patient.get("treatment_adverse_events") else "",
                    "pros" if patient.get("pros") else "",
                ]
            ),
        },
    }


def build_similar_cohort_mirror(
    patient_record: Mapping[str, Any] | None,
    *,
    cohort_records: Iterable[Mapping[str, Any]] | None = None,
    state: str = "",
    management_track: str = "",
) -> dict[str, Any]:
    """Build a non-authoritative internal cohort mirror for one patient."""
    patient = dict(patient_record or {})
    patient_identity = dict(patient.get("identity") or {})
    patient_id = _first_text(patient_identity.get("id"), patient.get("id"))
    patient_nss = _first_text(patient_identity.get("nss"), patient.get("nss"))
    target_state = _first_text(
        state,
        (patient.get("latest_assessment") or {}).get("state"),
        (patient.get("prior_history") or {}).get("current_state"),
    )
    target_track = _first_text(management_track, (patient.get("prior_history") or {}).get("management_track"))
    comparable: list[dict[str, Any]] = []
    for raw in list(cohort_records or []):
        if not isinstance(raw, Mapping):
            continue
        record = dict(raw)
        identity = dict(record.get("identity") or {})
        if _first_text(identity.get("id"), record.get("id")) == patient_id:
            continue
        if _first_text(identity.get("nss"), record.get("nss")) == patient_nss:
            continue
        record_state = _first_text(
            (record.get("latest_assessment") or {}).get("state"),
            (record.get("prior_history") or {}).get("current_state"),
            record.get("current_state"),
        )
        if target_state and record_state != target_state:
            continue
        record_track = _first_text((record.get("prior_history") or {}).get("management_track"), record.get("management_track"))
        if target_track and record_track and target_track != record_track:
            # Track mismatch is a soft exclusion only when both are known.
            continue
        features = _patient_learning_features(record, state=record_state, management_track=record_track)
        if not features.get("has_minimum_context"):
            continue
        comparable.append({"record": record, "features": features})

    if len(comparable) < MIN_SIMILAR_COHORT_SIZE:
        return {
            "status": "insufficient_cohort_size",
            "comparable_count": len(comparable),
            "minimum_required": MIN_SIMILAR_COHORT_SIZE,
            "state": target_state,
            "management_track": target_track,
            "summary": "Cohorte interna insuficiente para contexto estadistico confiable.",
            "distributions": {},
            "rates": {},
            "cohort_context_is_non_authoritative": True,
        }

    features = [item["features"] for item in comparable]
    baseline_psa_values = [item.get("baseline_psa") for item in features if item.get("baseline_psa") is not None]
    age_values = [item.get("age") for item in features if item.get("age") is not None]
    response_flags = [item.get("psa_response") for item in features if item.get("psa_response") is not None]
    progression_flags = [item.get("has_progression") for item in features]
    toxicity_flags = [item.get("has_grade3_toxicity") for item in features]
    return {
        "status": "available",
        "comparable_count": len(comparable),
        "minimum_required": MIN_SIMILAR_COHORT_SIZE,
        "state": target_state,
        "management_track": target_track,
        "summary": f"{len(comparable)} pacientes internos comparables; contexto descriptivo, no autoritativo.",
        "distributions": {
            "baseline_psa": _distribution(baseline_psa_values),
            "age": _distribution(age_values),
        },
        "rates": {
            "psa_response_rate": _rate(response_flags),
            "progression_rate": _rate(progression_flags),
            "grade3_toxicity_rate": _rate(toxicity_flags),
        },
        "cohort_context_is_non_authoritative": True,
        "example_patient_refs": [
            _hash_ref(_first_text((item["record"].get("identity") or {}).get("nss"), (item["record"].get("identity") or {}).get("id")))
            for item in comparable[:8]
        ],
    }


def _build_decision_episodes(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    tumor_board: Mapping[str, Any],
    care_pathway: Mapping[str, Any],
    readiness: Mapping[str, Any],
    observed: Mapping[str, Any],
    attribution: Mapping[str, Any],
    state: str,
    management_track: str,
    patient_ref: str,
) -> list[dict[str, Any]]:
    tb_summary = dict((tumor_board or {}).get("summary") or {})
    tb_recommendation = dict((tumor_board or {}).get("recommendation") or {})
    winner_key = _first_text(tb_summary.get("winner_option_key"), tb_recommendation.get("winner_option_key"), "current_decision")
    winner_label = _first_text(tb_summary.get("winner_option_label"), tb_recommendation.get("winner_option_label"), tb_recommendation.get("title"), "Decision actual")
    options = [dict(item) for item in list((tumor_board or {}).get("options") or []) if isinstance(item, Mapping)]
    actions = [dict(item) for item in list((care_pathway or {}).get("pathway_actions") or []) if isinstance(item, Mapping)]
    fields_missing = _dedupe(
        list(((tumor_board or {}).get("capture_plan") or {}).get("tumor_board_missing_fields") or [])
        + list(((readiness or {}).get("capture_plan") or {}).get("missing_fields") or [])
        + [field for action in actions for field in list(action.get("missing_fields") or [])]
    )
    gates = _dedupe([gate for option in options for gate in list(option.get("gates_impacted") or [])] + [gate for action in actions for gate in list(action.get("gates_impacted") or [])])
    trials = _dedupe([trial for option in options for trial in list(option.get("trials_impacted") or [])] + [trial for action in actions for trial in list(action.get("trials_impacted") or [])])
    completed_actions = [item for item in actions if item.get("status") == "completed"]
    blocked_actions = [item for item in actions if item.get("status") in {"blocked", "overdue"}]
    decision_date = _first_text(
        (patient.get("latest_assessment") or {}).get("created_at"),
        (patient.get("identity") or {}).get("diagnosis_date"),
        patient.get("diagnosis_date"),
        date.today().isoformat(),
    )[:10]
    episode_key = _episode_key(patient_ref, state, winner_key, decision_date)
    outcome_status = _text((observed or {}).get("status") or "insufficient_data")
    requires_redecision = outcome_status == "requires_redecision" or bool((attribution or {}).get("requires_redecision"))
    return [
        {
            "episode_key": episode_key,
            "status": "requires_redecision" if requires_redecision else "active",
            "state": state,
            "management_track": management_track,
            "decision_date": decision_date,
            "decision_origin": "tumor_board_os" if tumor_board else "clinical_memory_fallback",
            "board_status": _first_text(tb_summary.get("board_status"), tb_recommendation.get("finality"), "requires_data"),
            "winner_option_key": winner_key,
            "winner_option_label": winner_label,
            "recommendation_title": _first_text(tb_recommendation.get("title"), winner_label),
            "options_considered": [
                {"key": option.get("key"), "label": option.get("label"), "status": option.get("status")}
                for option in options[:6]
            ],
            "fields_missing_at_decision": fields_missing[:24],
            "fields_used_summary": _fields_used_summary(patient, bundle),
            "gates_impacted": gates[:32],
            "trials_impacted": trials[:32],
            "pathway_action_keys": [item.get("action_key") for item in actions[:16]],
            "pathway_completed_count": len(completed_actions),
            "pathway_blocked_count": len(blocked_actions),
            "observed_outcome_status": outcome_status,
            "observed_outcome_label": (observed or {}).get("label", ""),
            "attribution_primary": (attribution or {}).get("primary_cause", ""),
            "requires_redecision": requires_redecision,
            "redecision_reasons": list((attribution or {}).get("reasons") or [])[:8],
            "learning_maturity": _learning_maturity(observed, actions),
        }
    ]


def _build_expected_vs_observed(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    state: str,
) -> dict[str, Any]:
    psa_points = _biomarker_points(patient, "PSA") + _biomarker_points(patient, "APE")
    psa_points = _unique_points(psa_points)
    testosterone_points = _biomarker_points(patient, "TESTOSTERONA") + _biomarker_points(patient, "TESTOSTERONE")
    testosterone_points = _unique_points(testosterone_points)
    treatment_count = len([item for item in list(patient.get("treatments") or []) if isinstance(item, Mapping)])
    outcome_events = _outcome_events(patient, bundle)
    toxicity_events = _toxicity_events(patient, bundle)
    progression_events = [event for event in outcome_events if _event_type(event) in PROGRESSION_EVENT_TYPES]
    grade3_toxicity = [event for event in toxicity_events if _toxicity_grade(event) >= 3 or _event_type(event) in TOXICITY_EVENT_TYPES]
    latest_psa = psa_points[-1] if psa_points else {}
    baseline_psa = _baseline_psa(patient, psa_points)
    latest_testosterone = testosterone_points[-1] if testosterone_points else {}
    psa_delta_pct = None
    if baseline_psa is not None and latest_psa.get("value") is not None:
        try:
            if float(baseline_psa) > 0:
                psa_delta_pct = ((float(latest_psa["value"]) - float(baseline_psa)) / float(baseline_psa)) * 100.0
        except (TypeError, ValueError):
            psa_delta_pct = None

    missing = []
    if not psa_points:
        missing.append("psa_or_ape")
    if not testosterone_points:
        missing.append("testosterone")
    if treatment_count <= 0:
        missing.append("real_treatment_line")

    if progression_events:
        status = "requires_redecision"
        label = "Progresion documentada; requiere nueva decision."
    elif grade3_toxicity:
        status = "toxicity_limited"
        label = "Toxicidad limitante documentada."
    elif missing:
        status = "insufficient_data"
        label = "Faltan datos reales para aprender del episodio."
    elif psa_delta_pct is not None and psa_delta_pct <= -30:
        status = "on_track"
        label = "Respuesta PSA/APE compatible con curso favorable."
    elif psa_delta_pct is not None and psa_delta_pct >= 25:
        status = "off_track"
        label = "APE/PSA aumenta y debe revisarse en contexto clinico."
    else:
        status = "mixed"
        label = "Datos disponibles sin desenlace concluyente."

    return {
        "status": status,
        "label": label,
        "expectations": {
            "psa_or_ape": "APE/PSA longitudinal real para respuesta o progresion.",
            "testosterone": "Testosterona real para memoria endocrina/castracion.",
            "imaging": "Imagen solo si existe o cambia conducta.",
            "toxicity": "Toxicidad CTCAE/clinica real capturada.",
            "pros": "PROs/QoL si estan disponibles.",
        },
        "observed": {
            "psa_point_count": len(psa_points),
            "latest_psa": latest_psa,
            "baseline_psa": baseline_psa,
            "psa_delta_pct": round(psa_delta_pct, 2) if psa_delta_pct is not None else None,
            "testosterone_point_count": len(testosterone_points),
            "latest_testosterone": latest_testosterone,
            "treatment_line_count": treatment_count,
            "outcome_event_count": len(outcome_events),
            "progression_event_count": len(progression_events),
            "toxicity_event_count": len(toxicity_events),
            "grade3_toxicity_count": len(grade3_toxicity),
            "stage_visit_count": len(patient.get("stage_visits") or []),
        },
        "missing_for_learning": missing,
        "last_observation_date": _last_observation_date(psa_points, testosterone_points, outcome_events, toxicity_events, patient),
        "real_data_only": True,
    }


def _build_outcome_attribution(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    state: str,
) -> dict[str, Any]:
    obs = dict((observed or {}).get("observed") or {})
    missing = list((observed or {}).get("missing_for_learning") or [])
    reasons: list[str] = []
    has_treatment = int(obs.get("treatment_line_count") or 0) > 0
    status = _text((observed or {}).get("status") or "insufficient_data")
    latest_testosterone = dict(obs.get("latest_testosterone") or {})
    testosterone_value = _safe_float(latest_testosterone.get("value"))
    if status == "toxicity_limited":
        primary = "toxicity_limited"
        reasons.append("Toxicidad clinica limitante documentada.")
    elif int(obs.get("progression_event_count") or 0) > 0:
        primary = "progression_real"
        reasons.append("Existe evento de progresion adjudicado o inferido.")
    elif "real_treatment_line" in missing:
        primary = "no_real_treatment_line"
        reasons.append("No hay linea terapeutica real; no se atribuye respuesta a tratamiento.")
    elif "psa_or_ape" in missing or "testosterone" in missing:
        primary = "insufficient_data"
        reasons.append("Faltan APE/PSA o testosterona para memoria longitudinal confiable.")
    elif "crpc" in state.lower() and testosterone_value is not None and testosterone_value > 50:
        primary = "castration_insufficient"
        reasons.append("Testosterona por arriba de rango de castracion en contexto CRPC.")
    elif not has_treatment:
        primary = "surveillance_only"
        reasons.append("No hay tratamiento real documentado; episodio se interpreta como vigilancia/diagnostico.")
    else:
        primary = "observed_course"
        reasons.append("Datos reales disponibles sin causa adversa dominante.")
    if int(obs.get("psa_point_count") or 0) < 2:
        reasons.append("APE/PSA seriado insuficiente para cinetica confiable.")
    return {
        "primary_cause": primary,
        "status": status,
        "reasons": _dedupe(reasons),
        "therapeutic_attribution_allowed": bool(has_treatment and primary not in {"no_real_treatment_line", "insufficient_data"}),
        "requires_redecision": primary in {"toxicity_limited", "progression_real", "castration_insufficient"} or status in {"off_track", "requires_redecision", "toxicity_limited"},
        "real_data_only": True,
    }


def _build_learning_signals(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    episodes: list[dict[str, Any]],
    observed: Mapping[str, Any],
    attribution: Mapping[str, Any],
) -> list[dict[str, Any]]:
    episode = episodes[0] if episodes else {}
    obs = dict((observed or {}).get("observed") or {})
    signals = [
        {
            "key": "episode_memory_status",
            "label": "Estado de memoria del episodio",
            "value": episode.get("observed_outcome_status", "insufficient_data"),
            "source": "expected_vs_observed",
        },
        {
            "key": "therapeutic_attribution_allowed",
            "label": "Atribucion terapeutica permitida",
            "value": bool((attribution or {}).get("therapeutic_attribution_allowed")),
            "source": "outcome_attribution",
        },
        {
            "key": "psa_point_count",
            "label": "Puntos APE/PSA reales",
            "value": int(obs.get("psa_point_count") or 0),
            "source": "biomarker_longitudinal",
        },
        {
            "key": "testosterone_point_count",
            "label": "Puntos testosterona reales",
            "value": int(obs.get("testosterone_point_count") or 0),
            "source": "biomarker_longitudinal",
        },
    ]
    return signals


def _build_redecision_reasons(
    episodes: list[dict[str, Any]],
    observed: Mapping[str, Any],
    attribution: Mapping[str, Any],
    care_pathway: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if attribution.get("requires_redecision"):
        reasons.append(
            {
                "key": f"attribution:{attribution.get('primary_cause')}",
                "status": "active",
                "reason": "; ".join(list(attribution.get("reasons") or [])[:2]),
                "source": "outcome_attribution",
                "cta": {"label": "Reabrir Tumor Board", "url": "#pm2TumorBoardOS"},
            }
        )
    for trigger in list((care_pathway or {}).get("redecision_triggers") or [])[:6]:
        if not isinstance(trigger, Mapping):
            continue
        reasons.append(
            {
                "key": _first_text(trigger.get("trigger_key"), trigger.get("reason")),
                "status": _first_text(trigger.get("status"), "pending"),
                "reason": trigger.get("reason", ""),
                "source": "care_pathway_os",
                "cta": dict(trigger.get("cta") or {}),
            }
        )
    return _dedupe_dicts(reasons, "key")[:10]


def _build_model_readiness_dataset(
    patient: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    episodes: list[dict[str, Any]],
    observed: Mapping[str, Any],
    attribution: Mapping[str, Any],
    state: str,
    management_track: str,
) -> dict[str, Any]:
    identity = dict(patient.get("identity") or {})
    obs = dict((observed or {}).get("observed") or {})
    episode = episodes[0] if episodes else {}
    features = _patient_learning_features(patient, state=state, management_track=management_track)
    return {
        "status": "read_only",
        "schema_version": "clinical_memory_dataset_v1",
        "patient_ref_hash": _hash_ref(_first_text(identity.get("nss"), identity.get("id"))),
        "episode_key": episode.get("episode_key", ""),
        "features": features,
        "outcome": {
            "label": observed.get("status", "insufficient_data"),
            "attribution": attribution.get("primary_cause", ""),
            "mature": episode.get("learning_maturity") == "mature",
            "last_observation_date": observed.get("last_observation_date", ""),
        },
        "timestamps": {
            "decision_date": episode.get("decision_date", ""),
            "last_observation_date": observed.get("last_observation_date", ""),
        },
        "quality": {
            "missing_fields": list(observed.get("missing_for_learning") or []),
            "completeness_score": _completeness_score(obs),
            "source_traceability": _source_traceability(patient, bundle),
        },
        "consent": _consent_payload(patient),
        "read_only": True,
    }


def _build_ai_readiness(
    patient: Mapping[str, Any],
    model_dataset: Mapping[str, Any],
    observed: Mapping[str, Any],
    cohort_mirror: Mapping[str, Any],
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers = []
    consent = dict((model_dataset or {}).get("consent") or {})
    quality = dict((model_dataset or {}).get("quality") or {})
    if not consent.get("is_signed"):
        blockers.append("consent_missing")
    if observed.get("status") == "insufficient_data":
        blockers.append("outcome_insufficient_data")
    if quality.get("completeness_score", 0) < 0.65:
        blockers.append("low_data_completeness")
    if not quality.get("source_traceability", {}).get("has_traceable_sources"):
        blockers.append("source_traceability_missing")
    if cohort_mirror.get("status") != "available":
        blockers.append("insufficient_similar_cohort")
    if not episodes or episodes[0].get("learning_maturity") != "mature":
        blockers.append("outcome_not_mature")
    return {
        "status": "blocked" if blockers else "learning_ready",
        "model_release_allowed": False,
        "model_training_allowed_v1": False,
        "dataset_export_allowed": bool(not blockers and consent.get("is_signed")),
        "blockers": blockers,
        "sample_size": int(cohort_mirror.get("comparable_count") or 0),
        "minimum_sample_size": MIN_SIMILAR_COHORT_SIZE,
        "completeness_score": quality.get("completeness_score", 0),
        "missingness": list(observed.get("missing_for_learning") or []),
        "selection_bias": "not_assessable" if cohort_mirror.get("status") != "available" else "descriptive_only",
        "leakage_risk": "low_v1_read_only" if not blockers else "not_evaluable",
        "outcome_maturity": episodes[0].get("learning_maturity") if episodes else "none",
        "consent_status": consent.get("status", "missing"),
    }


def _build_summary(
    episodes: list[dict[str, Any]],
    *,
    observed: Mapping[str, Any],
    attribution: Mapping[str, Any],
    cohort_mirror: Mapping[str, Any],
    ai_readiness: Mapping[str, Any],
    state: str,
    management_track: str,
) -> dict[str, Any]:
    active = episodes[0] if episodes else {}
    return {
        "clinical_state": state,
        "management_track": management_track,
        "active_episode_key": active.get("episode_key", ""),
        "active_episode_label": active.get("winner_option_label", ""),
        "episode_count": len(episodes),
        "outcome_status": observed.get("status", "insufficient_data"),
        "outcome_label": observed.get("label", ""),
        "attribution_primary": attribution.get("primary_cause", ""),
        "requires_redecision": bool(active.get("requires_redecision") or attribution.get("requires_redecision")),
        "similar_cohort_status": cohort_mirror.get("status", "insufficient_cohort_size"),
        "similar_cohort_count": int(cohort_mirror.get("comparable_count") or 0),
        "ai_readiness_status": ai_readiness.get("status", "blocked"),
        "ai_blocker_count": len(ai_readiness.get("blockers") or []),
        "memory_maturity": active.get("learning_maturity", "immature"),
    }


def _patient_learning_features(patient: Mapping[str, Any], *, state: str, management_track: str) -> dict[str, Any]:
    identity = dict(patient.get("identity") or {})
    baseline = dict(patient.get("baseline") or {})
    psa_points = _unique_points(_biomarker_points(patient, "PSA") + _biomarker_points(patient, "APE"))
    testosterone_points = _unique_points(_biomarker_points(patient, "TESTOSTERONA") + _biomarker_points(patient, "TESTOSTERONE"))
    outcome_events = _outcome_events(patient, {})
    toxicity_events = _toxicity_events(patient, {})
    baseline_psa = _baseline_psa(patient, psa_points)
    latest_psa = psa_points[-1]["value"] if psa_points else None
    return {
        "state": state,
        "management_track": management_track,
        "age": _age(identity.get("dob")),
        "baseline_psa": baseline_psa,
        "latest_psa": latest_psa,
        "has_latest_testosterone": bool(testosterone_points),
        "treatment_line_count": len(patient.get("treatments") or []),
        "biomarker_point_count": len(psa_points) + len(testosterone_points),
        "outcome_event_count": len(outcome_events),
        "toxicity_event_count": len(toxicity_events),
        "has_progression": any(_event_type(event) in PROGRESSION_EVENT_TYPES for event in outcome_events),
        "has_grade3_toxicity": any(_toxicity_grade(event) >= 3 for event in toxicity_events),
        "psa_response": _psa_response_flag(baseline_psa, latest_psa),
        "ecog": _safe_float(baseline.get("ecog_score") or patient.get("ecog_score")),
        "has_minimum_context": bool(state and (baseline_psa is not None or psa_points or patient.get("treatments"))),
    }


def _fields_used_summary(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "has_psa": bool(_unique_points(_biomarker_points(patient, "PSA") + _biomarker_points(patient, "APE"))),
        "has_testosterone": bool(_unique_points(_biomarker_points(patient, "TESTOSTERONA") + _biomarker_points(patient, "TESTOSTERONE"))),
        "has_treatment_line": bool(patient.get("treatments")),
        "has_outcome_events": bool(_outcome_events(patient, bundle)),
        "has_toxicity": bool(_toxicity_events(patient, bundle)),
        "has_pros": bool(patient.get("pros")),
        "has_clinical_facts": bool(bundle.get("clinical_fact_bundle") or patient.get("patient_clinical_facts")),
    }


def _learning_maturity(observed: Mapping[str, Any], actions: list[dict[str, Any]]) -> str:
    obs = dict((observed or {}).get("observed") or {})
    if observed.get("status") in {"requires_redecision", "toxicity_limited", "on_track", "off_track"}:
        return "mature"
    if int(obs.get("psa_point_count") or 0) >= 2 and int(obs.get("testosterone_point_count") or 0) >= 1:
        return "emerging"
    if any(item.get("status") == "completed" for item in actions):
        return "emerging"
    return "immature"


def _biomarker_points(patient: Mapping[str, Any], biomarker_type: str) -> list[dict[str, Any]]:
    wanted = biomarker_type.upper()
    points = []
    for row in list(patient.get("biomarker_longitudinal") or []):
        if not isinstance(row, Mapping):
            continue
        raw_type = _text(row.get("biomarker_type") or row.get("type")).upper()
        if raw_type != wanted:
            continue
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        points.append(
            {
                "date": _first_text(row.get("sample_date"), row.get("date")),
                "value": value,
                "source": _first_text(row.get("source"), row.get("entry_origin"), "biomarker_longitudinal"),
            }
        )
    series_key = "psa_series" if wanted in {"PSA", "APE"} else "testosterone_series"
    for row in list(patient.get(series_key) or []):
        if not isinstance(row, Mapping):
            continue
        value = _safe_float(row.get("value"))
        if value is None:
            continue
        points.append(
            {
                "date": _first_text(row.get("sample_date"), row.get("date")),
                "value": value,
                "source": _first_text(row.get("source"), row.get("entry_origin"), series_key),
            }
        )
    return sorted([p for p in points if p.get("date")], key=lambda item: item.get("date", ""))


def _unique_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for point in points:
        key = (point.get("date"), point.get("value"))
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    return sorted(result, key=lambda item: item.get("date", ""))


def _baseline_psa(patient: Mapping[str, Any], psa_points: list[dict[str, Any]]) -> float | None:
    baseline = dict(patient.get("baseline") or {})
    value = _safe_float(
        baseline.get("baseline_psa")
        or baseline.get("psa_baseline")
        or patient.get("baseline_psa")
    )
    if value is not None:
        return value
    return psa_points[0].get("value") if psa_points else None


def _outcome_events(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = []
    for source in (bundle.get("outcome_events"), patient.get("outcome_events"), patient.get("operational_outcomes")):
        for item in _as_list(source):
            if isinstance(item, Mapping):
                events.append(dict(item))
    return _dedupe_dicts(events, "event_key")


def _toxicity_events(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = []
    for source in (patient.get("treatment_adverse_events"), bundle.get("treatment_adverse_events")):
        for item in _as_list(source):
            if isinstance(item, Mapping):
                events.append(dict(item))
    return events


def _event_type(event: Mapping[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("type") or event.get("axis")).lower()


def _toxicity_grade(event: Mapping[str, Any]) -> int:
    for key in ("grade", "ctcae_grade", "max_grade", "severity_grade"):
        value = _safe_float(event.get(key))
        if value is not None:
            return int(value)
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    value = _safe_float(payload.get("grade") if isinstance(payload, Mapping) else None)
    return int(value) if value is not None else 0


def _last_observation_date(
    psa_points: list[dict[str, Any]],
    testosterone_points: list[dict[str, Any]],
    outcome_events: list[dict[str, Any]],
    toxicity_events: list[dict[str, Any]],
    patient: Mapping[str, Any],
) -> str:
    dates = []
    dates.extend([p.get("date") for p in psa_points if p.get("date")])
    dates.extend([p.get("date") for p in testosterone_points if p.get("date")])
    dates.extend([_first_text(e.get("event_date"), e.get("date")) for e in outcome_events])
    dates.extend([_first_text(e.get("event_date"), e.get("date")) for e in toxicity_events])
    dates.extend([_first_text(v.get("visit_date"), v.get("created_at")) for v in list(patient.get("stage_visits") or []) if isinstance(v, Mapping)])
    dates = [str(item)[:10] for item in dates if item]
    return max(dates) if dates else ""


def _source_traceability(patient: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict[str, Any]:
    has_sources = bool(patient.get("source_documents") or patient.get("data_provenance") or patient.get("patient_clinical_facts"))
    has_runtime = bool(bundle.get("clinical_fact_bundle") or bundle.get("longitudinal_truth_snapshot"))
    return {
        "has_traceable_sources": bool(has_sources or has_runtime),
        "source_document_count": len(patient.get("source_documents") or []),
        "data_provenance_count": len(patient.get("data_provenance") or []),
        "clinical_fact_count": len(patient.get("patient_clinical_facts") or []),
    }


def _consent_payload(patient: Mapping[str, Any]) -> dict[str, Any]:
    consent = dict(patient.get("consent_summary") or patient.get("consent") or {})
    status = _first_text(consent.get("status"), "missing")
    return {
        "status": status,
        "is_signed": status == "signed",
        "version": _first_text(consent.get("consent_version_code"), consent.get("version_code"), consent.get("consent_version")),
        "signed_at": _first_text(consent.get("signed_at"), consent.get("created_at")),
        "source": "patient_consents" if consent else "missing",
    }


def _completeness_score(obs: Mapping[str, Any]) -> float:
    checks = [
        int(obs.get("psa_point_count") or 0) > 0,
        int(obs.get("testosterone_point_count") or 0) > 0,
        int(obs.get("treatment_line_count") or 0) > 0,
        int(obs.get("outcome_event_count") or 0) > 0 or int(obs.get("psa_point_count") or 0) >= 2,
        int(obs.get("stage_visit_count") or 0) > 0,
    ]
    return round(sum(1 for item in checks if item) / len(checks), 2)


def _psa_response_flag(baseline_psa: Any, latest_psa: Any) -> bool | None:
    baseline = _safe_float(baseline_psa)
    latest = _safe_float(latest_psa)
    if baseline is None or latest is None or baseline <= 0:
        return None
    return latest <= baseline * 0.7


def _distribution(values: list[Any]) -> dict[str, Any]:
    numbers = sorted([float(value) for value in values if _safe_float(value) is not None])
    if not numbers:
        return {"count": 0}
    return {
        "count": len(numbers),
        "median": round(median(numbers), 2),
        "min": round(numbers[0], 2),
        "max": round(numbers[-1], 2),
        "iqr": [
            round(numbers[len(numbers) // 4], 2),
            round(numbers[(len(numbers) * 3) // 4], 2),
        ],
    }


def _rate(flags: list[Any]) -> dict[str, Any]:
    if not flags:
        return {"count": 0, "rate": None}
    positives = len([item for item in flags if bool(item)])
    return {"count": len(flags), "positive": positives, "rate": round(positives / len(flags), 3)}


def _age(dob: Any) -> int | None:
    text = _text(dob)[:10]
    if not text:
        return None
    try:
        d = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    today = date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def _episode_key(patient_ref: str, state: str, winner_key: str, decision_date: str) -> str:
    raw = f"{patient_ref}|{state}|{winner_key}|{decision_date}"
    return "episode:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _hash_ref(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _dedupe(values: Iterable[Any]) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        if value in (None, "", [], {}):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_dicts(values: Iterable[Mapping[str, Any]], key_name: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for raw in values:
        item = dict(raw or {})
        key = _first_text(item.get(key_name), item.get("id"), item.get("event_type"), item.get("reason"))
        if not key:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, Mapping):
        return [value]
    return [value]


def _safe_float(value: Any) -> float | None:
    if value in (None, "", [], {}):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = ["build_clinical_memory_os", "build_similar_cohort_mirror"]
