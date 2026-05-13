"""ProstaMed Tumor Board OS.

Deterministic patient-level decision board that compares clinically competing
options without replacing the classifier, readiness tower, gates, trials or
vertical copilots. It is a read model: no treatment, PSA, testosterone, line
or trial eligibility is invented here.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from prostanet.domains.patient_tracking.clinical_readiness_tower import (
    EVIDENCE_ANCHORS,
    FIELD_LABELS,
    build_clinical_readiness_tower,
    build_readiness_gate_contract_matrix,
    summarize_readiness_gate_contracts,
)


TUMOR_BOARD_OPTION_STATUSES = (
    "releaseable",
    "provisional",
    "requires_data",
    "blocked",
    "not_applicable",
)

STATUS_RANK = {
    "releaseable": 0,
    "provisional": 1,
    "requires_data": 2,
    "blocked": 3,
    "not_applicable": 4,
}

OPTION_BLUEPRINTS: dict[str, list[dict[str, Any]]] = {
    "diagnostic": [
        {
            "key": "diagnostic_reassess_risk",
            "label": "Recalibrar riesgo diagnóstico",
            "clinical_role": "diagnostic_workup",
            "lanes": ["diagnostic_biopsy_readiness"],
            "rationale": "Define si la sospecha requiere MRI, biomarcadores o biopsia.",
        },
        {
            "key": "mri_targeted_biopsy",
            "label": "MRI multiparamétrica + biopsia dirigida",
            "clinical_role": "diagnostic_workup",
            "lanes": ["diagnostic_biopsy_readiness"],
            "rationale": "Compite cuando PSA/APE, PSAD, DRE o PI-RADS pueden cambiar conducta.",
        },
        {
            "key": "negative_biopsy_followup",
            "label": "Seguimiento tras biopsia negativa",
            "clinical_role": "diagnostic_followup",
            "lanes": ["diagnostic_biopsy_readiness"],
            "rationale": "Evita rebiopsia automática si faltan señales de riesgo persistente.",
        },
    ],
    "localized": [
        {
            "key": "active_surveillance",
            "label": "Vigilancia activa",
            "clinical_role": "localized_management",
            "lanes": ["localized_treatment_readiness", "active_surveillance_readiness"],
            "rationale": "Compite si riesgo, histología y preferencias permiten evitar tratamiento inmediato.",
        },
        {
            "key": "radical_prostatectomy",
            "label": "Prostatectomía radical",
            "clinical_role": "localized_management",
            "lanes": ["localized_treatment_readiness"],
            "rationale": "Opción local definitiva condicionada por riesgo, expectativa de vida y función basal.",
        },
        {
            "key": "radiotherapy_definitive",
            "label": "Radioterapia definitiva",
            "clinical_role": "localized_management",
            "lanes": ["localized_treatment_readiness"],
            "rationale": "Opción local definitiva que requiere tradeoffs urinarios, sexuales e intestinales.",
        },
        {
            "key": "focal_therapy_selective",
            "label": "Terapia focal selectiva",
            "clinical_role": "localized_management",
            "lanes": ["localized_treatment_readiness"],
            "rationale": "Solo se considera como opción selectiva si la anatomía y el fenotipo lo justifican.",
        },
    ],
    "postlocal_bcr": [
        {
            "key": "bcr_restage_salvage_window",
            "label": "Reestadificar y abrir ventana de salvage",
            "clinical_role": "bcr_salvage",
            "lanes": ["bcr_salvage_readiness"],
            "rationale": "Prioriza confirmar contexto post-RP/post-RT, PSADT, Phoenix/nadir e imagen si cambia conducta.",
        },
        {
            "key": "salvage_local_therapy",
            "label": "Salvage local / RT de rescate",
            "clinical_role": "bcr_salvage",
            "lanes": ["bcr_salvage_readiness"],
            "rationale": "Compite cuando la recurrencia bioquímica mantiene intención potencialmente curativa.",
        },
        {
            "key": "bcr_structured_observation",
            "label": "Observación estructurada BCR",
            "clinical_role": "bcr_followup",
            "lanes": ["bcr_salvage_readiness"],
            "rationale": "Solo es segura si la cinética y el contexto post-local están documentados.",
        },
    ],
    "mhspc": [
        {
            "key": "adt_backbone",
            "label": "ADT como backbone documentado",
            "clinical_role": "mhspc_systemic",
            "lanes": ["mhspc_precision_readiness"],
            "rationale": "Base terapéutica que requiere composición M1, volumen/riesgo y fitness.",
        },
        {
            "key": "arpi_doublet",
            "label": "Doblete ADT + ARPI",
            "clinical_role": "mhspc_systemic",
            "family_code": "arpi_family",
            "lanes": ["mhspc_precision_readiness"],
            "rationale": "Compite frente a ADT sola cuando el estado metastásico y seguridad permiten intensificación.",
        },
        {
            "key": "triplet_docetaxel_arpi",
            "label": "Triplete con docetaxel + ARPI",
            "clinical_role": "mhspc_systemic",
            "family_code": "triplet_family",
            "lanes": ["mhspc_precision_readiness"],
            "rationale": "Se libera solo si volumen/riesgo, ECOG y seguridad sostienen intensificación.",
        },
        {
            "key": "primary_rt_or_mdt",
            "label": "RT a primario / MDT si oligometastásico",
            "clinical_role": "mhspc_local_adjunct",
            "family_code": "local_mdt_family",
            "lanes": ["mhspc_precision_readiness"],
            "rationale": "Adjunto local si bajo volumen, oligometástasis o anatomía lo vuelven relevante.",
        },
    ],
    "adt_progression": [
        {
            "key": "confirm_crpc_first",
            "label": "Confirmar CRPC antes de tratar",
            "clinical_role": "crpc_confirmation",
            "lanes": ["crpc_confirmation_readiness"],
            "rationale": "CRPC no se libera sin progresión, castración e imagen convencional reconciliada.",
        },
        {
            "key": "optimize_adt_restage",
            "label": "Optimizar ADT y reestadificar",
            "clinical_role": "crpc_confirmation",
            "lanes": ["crpc_confirmation_readiness"],
            "rationale": "Evita escalar tratamiento si la castración o M0/M1 aún no están confirmados.",
        },
    ],
    "m0_crpc": [
        {
            "key": "confirm_nmcrpc_contract",
            "label": "Confirmar contrato m0CRPC",
            "clinical_role": "crpc_confirmation",
            "lanes": ["crpc_confirmation_readiness", "m0crpc_arpi_readiness"],
            "rationale": "El estado m0CRPC exige testosterona, PSADT e imagen convencional M0.",
        },
        {
            "key": "m0crpc_arpi",
            "label": "ARPI para m0CRPC",
            "clinical_role": "m0crpc_treatment",
            "family_code": "arpi_family",
            "lanes": ["m0crpc_arpi_readiness"],
            "rationale": "Se libera solo con PSADT, castración, M0 convencional y seguridad ARPI.",
        },
        {
            "key": "m0crpc_monitoring",
            "label": "Monitoreo estrecho sin intensificar aún",
            "clinical_role": "m0crpc_followup",
            "lanes": ["m0crpc_arpi_readiness"],
            "rationale": "Opción provisional si faltan datos decisivos o hay riesgo activo.",
        },
    ],
    "m1_crpc": [
        {
            "key": "mcrpc_sequence",
            "label": "Secuenciación sistémica m1CRPC",
            "clinical_role": "m1crpc_sequence",
            "family_code": "mcrpc_sequence",
            "lanes": ["m1crpc_sequence_readiness"],
            "requires_real_line": True,
            "rationale": "No se puede secuenciar sin línea terapéutica real, progresión y exposiciones previas.",
        },
        {
            "key": "parp_hrr",
            "label": "PARP si HRR/BRCA trazable",
            "clinical_role": "precision_parp",
            "family_code": "parp_family",
            "lanes": ["parp_hrr_readiness"],
            "requires_lane_applicable": "parp_hrr_readiness",
            "rationale": "Solo compite con HRR/BRCA o familia PARP clínicamente documentada.",
        },
        {
            "key": "psma_rlt",
            "label": "PSMA-RLT si PSMA PET y línea lo permiten",
            "clinical_role": "precision_psma_rlt",
            "family_code": "psma_rlt_family",
            "lanes": ["psma_rlt_readiness"],
            "requires_lane_applicable": "psma_rlt_readiness",
            "rationale": "Solo compite si PSMA PET estructurado y secuencia previa lo justifican.",
        },
        {
            "key": "supportive_palliative_concurrent",
            "label": "Soporte/paliación concurrente",
            "clinical_role": "supportive_palliative",
            "lanes": ["supportive_palliative_readiness"],
            "rationale": "Siempre compite como seguridad y objetivos de cuidado cuando hay enfermedad avanzada.",
        },
    ],
}


def build_tumor_board_os(
    patient_record: Mapping[str, Any] | None,
    *,
    longitudinal_bundle: Mapping[str, Any] | None = None,
    state: str = "",
    management_track: str = "",
    patient_ref: str = "",
    hypothetical_changes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the official deterministic Tumor Board OS bundle."""
    patient = deepcopy(dict(patient_record or {}))
    bundle = deepcopy(dict(longitudinal_bundle or {}))
    changes = dict(hypothetical_changes or {})
    if changes:
        _apply_hypothetical_changes(patient, bundle, changes)

    signals = dict(bundle.get("signals") or {})
    effective_state = _first_text(
        state,
        signals.get("effective_state_final"),
        signals.get("effective_state"),
        signals.get("reconciled_state"),
        (patient.get("latest_assessment") or {}).get("state"),
        (patient.get("prior_history") or {}).get("current_state"),
        patient.get("current_state"),
        "diagnostic_workup",
    )
    effective_track = _first_text(
        management_track,
        signals.get("effective_management_track_final"),
        signals.get("effective_management_track"),
        signals.get("reconciled_management_track"),
        patient.get("management_track"),
    )
    resolved_ref = _first_text(
        patient_ref,
        (patient.get("identity") or {}).get("nss"),
        patient.get("nss"),
        patient.get("patient_ref"),
    )

    readiness = dict(bundle.get("clinical_readiness_tower") or {})
    if not readiness:
        readiness = build_clinical_readiness_tower(
            patient,
            longitudinal_bundle=bundle,
            state=effective_state,
            management_track=effective_track,
            patient_ref=resolved_ref,
        )
    lanes = [dict(item) for item in list(readiness.get("lanes") or []) if isinstance(item, Mapping)]
    lane_map = {str(lane.get("key") or ""): lane for lane in lanes}
    readiness_summary = dict(readiness.get("summary") or {})
    option_group = _state_group(effective_state)
    context = {
        "patient": patient,
        "bundle": bundle,
        "state": effective_state,
        "management_track": effective_track,
        "patient_ref": resolved_ref,
        "readiness": readiness,
        "lane_map": lane_map,
        "has_real_treatment_line": bool(readiness_summary.get("has_real_treatment_line")),
        "real_treatment_line_count": int(readiness_summary.get("real_treatment_line_count") or 0),
        "therapeutic": dict(bundle.get("therapeutic_readiness_bundle") or {}),
        "decision_evidence": dict(bundle.get("decision_evidence_currentness_bundle") or {}),
        "decision_input_requirements": dict(bundle.get("decision_input_requirements") or {}),
        "comparative_matrix": dict(
            bundle.get("comparative_eligibility_matrix")
            or (bundle.get("therapeutic_readiness_bundle") or {}).get("comparative_eligibility_matrix")
            or {}
        ),
    }

    options = [
        _build_option(blueprint, context)
        for blueprint in OPTION_BLUEPRINTS.get(option_group, OPTION_BLUEPRINTS["diagnostic"])
    ]
    visible_options = _ensure_option_window(options)
    winner = _select_winner(visible_options)
    recommendation = _build_recommendation(winner, visible_options, readiness)
    capture_plan = _build_capture_plan(readiness, visible_options)
    trial_audit = _build_trial_audit(patient, effective_state)
    gate_summary = summarize_readiness_gate_contracts()

    return {
        "available": True,
        "source": "tumor_board_os",
        "version": "tumor_board_os_v1",
        "patient_ref": resolved_ref,
        "state": effective_state,
        "management_track": effective_track,
        "summary": {
            "board_status": recommendation.get("finality", "blocked"),
            "state_group": option_group,
            "option_count": len(visible_options),
            "releaseable_count": sum(1 for item in visible_options if item.get("status") == "releaseable"),
            "requires_data_count": sum(1 for item in visible_options if item.get("status") == "requires_data"),
            "blocked_count": sum(1 for item in visible_options if item.get("status") == "blocked"),
            "winner_option_key": winner.get("key", ""),
            "winner_option_label": winner.get("label", ""),
            "dominant_blocker": _dominant_blocker(visible_options, readiness),
            "real_treatment_line_count": readiness_summary.get("real_treatment_line_count", 0),
            "has_real_treatment_line": bool(readiness_summary.get("has_real_treatment_line")),
            "safety_note": "No se inventan terapias, APE/PSA, testosterona, líneas ni elegibilidad de trials.",
        },
        "options": visible_options,
        "comparative_matrix": _build_comparative_matrix(visible_options, context),
        "recommendation": recommendation,
        "capture_plan": capture_plan,
        "what_if_contract": {
            "no_db_write": True,
            "endpoint": f"/api/patients/{resolved_ref}/tumor-board-os/what-if" if resolved_ref else "",
            "supported_inputs": _supported_what_if_inputs(capture_plan),
        },
        "tumor_board_note": _build_tumor_board_note(
            state=effective_state,
            recommendation=recommendation,
            winner=winner,
            capture_plan=capture_plan,
        ),
        "audit": {
            "allowed_status_values": list(TUMOR_BOARD_OPTION_STATUSES),
            "readiness_summary": readiness_summary,
            "gate_contract_summary": gate_summary,
            "gate_contract_total": gate_summary.get("total_gates", 0),
            "gate_contract_covered": gate_summary.get("covered_gates", 0),
            "readiness_gate_contract_matrix": build_readiness_gate_contract_matrix(),
            "trial_contract_summary": trial_audit,
            "trials_evaluated": trial_audit.get("total_trials", 0),
            "trial_requires_data_count": trial_audit.get("requires_data_count", 0),
            "trial_eligible_count": trial_audit.get("eligible_count", 0),
            "sources_used": _sources_used(patient, bundle, readiness),
            "evidence_anchors": list(EVIDENCE_ANCHORS),
            "hypothetical": bool(changes),
            "hypothetical_changes": changes,
            "no_fabrication_checks": {
                "uses_real_treatment_lines_only": True,
                "uses_real_psa_testosterone_only": True,
                "trial_positive_requires_evaluable_payload": trial_audit.get("empty_payload_guard_ok", False),
                "no_db_write": bool(changes),
            },
        },
    }


def build_tumor_board_what_if_delta(
    *,
    real_board: Mapping[str, Any],
    hypothetical_board: Mapping[str, Any],
    hypothetical_changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a compact no-write delta between two Tumor Board OS bundles."""
    old = dict(real_board or {})
    new = dict(hypothetical_board or {})
    old_summary = dict(old.get("summary") or {})
    new_summary = dict(new.get("summary") or {})
    old_options = {item.get("key"): item for item in list(old.get("options") or []) if isinstance(item, Mapping)}
    new_options = {item.get("key"): item for item in list(new.get("options") or []) if isinstance(item, Mapping)}
    options_changed: list[dict[str, Any]] = []
    for key in sorted(set(old_options) | set(new_options)):
        old_item = dict(old_options.get(key) or {})
        new_item = dict(new_options.get(key) or {})
        if old_item.get("status") == new_item.get("status") and old_item.get("rank") == new_item.get("rank"):
            continue
        options_changed.append(
            {
                "key": key,
                "label": new_item.get("label") or old_item.get("label") or key,
                "old_status": old_item.get("status", "not_applicable"),
                "new_status": new_item.get("status", "not_applicable"),
                "old_rank": old_item.get("rank"),
                "new_rank": new_item.get("rank"),
            }
        )

    old_gates = _option_contract_set(old, "gates_impacted")
    new_gates = _option_contract_set(new, "gates_impacted")
    old_trials = _option_contract_set(old, "trials_impacted")
    new_trials = _option_contract_set(new, "trials_impacted")

    return {
        "success": True,
        "no_db_write": True,
        "hypothetical_changes": dict(hypothetical_changes or {}),
        "decision_changed": (
            old_summary.get("winner_option_key") != new_summary.get("winner_option_key")
            or old_summary.get("board_status") != new_summary.get("board_status")
        ),
        "delta": {
            "old": {
                "board_status": old_summary.get("board_status", ""),
                "winner_option_key": old_summary.get("winner_option_key", ""),
                "winner_option_label": old_summary.get("winner_option_label", ""),
                "dominant_blocker": old_summary.get("dominant_blocker", ""),
            },
            "new": {
                "board_status": new_summary.get("board_status", ""),
                "winner_option_key": new_summary.get("winner_option_key", ""),
                "winner_option_label": new_summary.get("winner_option_label", ""),
                "dominant_blocker": new_summary.get("dominant_blocker", ""),
            },
        },
        "options_changed": options_changed[:12],
        "options_changed_count": len(options_changed),
        "gates_changed": sorted(old_gates ^ new_gates)[:20],
        "gates_changed_count": len(old_gates ^ new_gates),
        "trials_changed": sorted(old_trials ^ new_trials)[:20],
        "trials_changed_count": len(old_trials ^ new_trials),
        "recommendation": dict(new.get("recommendation") or {}),
        "audit_note": "Tumor Board OS what-if · NO DB write",
    }


def _build_option(blueprint: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    option = dict(blueprint)
    lane_map = dict(context.get("lane_map") or {})
    required_lane = str(option.get("requires_lane_applicable") or "")
    if required_lane and str((lane_map.get(required_lane) or {}).get("status") or "") == "not_applicable":
        return {
            **option,
            "status": "not_applicable",
            "rank": None,
            "missing_fields": [],
            "display_missing_fields": [],
            "release_blockers": [],
            "why": [option.get("rationale", ""), "No compite clínicamente en el estado actual."],
            "cta": {},
            "gates_impacted": [],
            "trials_impacted": [],
        }

    lane_keys = [str(item) for item in list(option.get("lanes") or []) if str(item).strip()]
    relevant_lanes = [
        dict(lane_map.get(key) or {})
        for key in lane_keys
        if dict(lane_map.get(key) or {}).get("status") != "not_applicable"
    ]
    missing = _dedupe(
        [
            field
            for lane in relevant_lanes
            for field in list(lane.get("missing_fields") or [])
            if field
        ]
    )
    blockers = _dedupe(
        [
            str(lane.get("reason") or "")
            for lane in relevant_lanes
            if lane.get("status") in {"active_risk", "overdue"}
        ]
    )
    if option.get("requires_real_line") and not context.get("has_real_treatment_line"):
        missing.append("real_treatment_line")

    therapeutic = dict(context.get("therapeutic") or {})
    decision_evidence = dict(context.get("decision_evidence") or {})
    recommendation_block_status = _lower(
        context.get("bundle", {}).get("recommendation_block_status")
        or therapeutic.get("recommendation_block_status")
    )
    recommendation_block_reason = _first_text(
        context.get("bundle", {}).get("recommendation_block_reason"),
        therapeutic.get("recommendation_block_reason"),
    )
    if recommendation_block_status in {"hard_stop", "blocked", "blocked_by_safety"}:
        blockers.append(recommendation_block_reason or "Existe bloqueo de gobernanza clínica.")

    release_status = _lower(therapeutic.get("readiness_status"))
    if option.get("family_code") and release_status in {"blocked_by_safety"}:
        blockers.extend(_as_list(therapeutic.get("safety_blockers")))

    if blockers:
        status = "blocked"
    elif missing:
        status = "requires_data"
    elif _evidence_is_stale(decision_evidence, therapeutic):
        status = "provisional"
    else:
        status = "releaseable"

    cta = _first_lane_cta(relevant_lanes, context)
    gates = _dedupe([g for lane in relevant_lanes for g in list(lane.get("gates_impacted") or [])])
    trials = _dedupe([t for lane in relevant_lanes for t in list(lane.get("trials_impacted") or [])])
    family_profile = _family_profile(option.get("family_code"), context)

    return {
        **option,
        "status": status,
        "rank": None,
        "readiness_lanes": lane_keys,
        "lane_statuses": [
            {
                "key": lane.get("key"),
                "label": lane.get("label"),
                "status": lane.get("status"),
                "reason": lane.get("reason"),
            }
            for lane in relevant_lanes
        ],
        "missing_fields": _dedupe(missing),
        "display_missing_fields": [_field_label(field) for field in _dedupe(missing)[:8]],
        "release_blockers": _dedupe(blockers),
        "why": _dedupe(
            [
                option.get("rationale", ""),
                *[lane.get("reason", "") for lane in relevant_lanes[:2]],
                family_profile.get("summary") or family_profile.get("rationale") or "",
            ]
        )[:5],
        "evidence": _option_evidence(option, family_profile, context),
        "safety": _option_safety(option, family_profile, therapeutic),
        "cta": cta,
        "gates_impacted": gates[:16],
        "trials_impacted": trials[:16],
    }


def _ensure_option_window(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [item for item in options if item.get("status") != "not_applicable"]
    if not active:
        active = options[:2]
    active.sort(key=lambda item: (STATUS_RANK.get(str(item.get("status")), 99), _text(item.get("key"))))
    visible = active[:4]
    for index, option in enumerate(visible, start=1):
        option["rank"] = index
    return visible


def _select_winner(options: list[dict[str, Any]]) -> dict[str, Any]:
    for status in ("releaseable", "provisional", "requires_data", "blocked"):
        for option in options:
            if option.get("status") == status:
                return option
    return {}


def _build_recommendation(
    winner: Mapping[str, Any],
    options: list[dict[str, Any]],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    if not winner:
        return {
            "finality": "blocked",
            "title": "Sin opción comparativa activa",
            "rationale": "No hay una alternativa clínica aplicable con los datos actuales.",
            "allowed_actions": ["Completar clasificación oficial o captura longitudinal."],
            "capture_plan": dict((readiness or {}).get("capture_plan") or {}),
        }
    status = str(winner.get("status") or "blocked")
    if status == "releaseable":
        finality = "released"
        title = f"Liberar: {winner.get('label')}"
    elif status == "provisional":
        finality = "provisional"
        title = f"Ganador provisional: {winner.get('label')}"
    elif status == "requires_data":
        finality = "provisional"
        title = f"Primero completar datos para: {winner.get('label')}"
    else:
        finality = "blocked"
        title = f"Bloqueado: {winner.get('label')}"
    blockers = _dedupe(list(winner.get("release_blockers") or []) + list(winner.get("display_missing_fields") or []))
    return {
        "finality": finality,
        "title": title,
        "rationale": " ".join(_as_list(winner.get("why"))[:2]) or _text(winner.get("rationale")),
        "winner_option_key": winner.get("key", ""),
        "winner_option_label": winner.get("label", ""),
        "allowed_actions": _allowed_actions(winner, options),
        "blocking_summary": "; ".join(blockers[:4]),
        "capture_plan": dict((readiness or {}).get("capture_plan") or {}),
    }


def _build_capture_plan(readiness: Mapping[str, Any], options: list[dict[str, Any]]) -> dict[str, Any]:
    base = deepcopy(dict((readiness or {}).get("capture_plan") or {}))
    option_groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in options:
        if option.get("status") not in {"requires_data", "blocked", "provisional"}:
            continue
        fields = [field for field in list(option.get("missing_fields") or []) if field not in seen]
        if not fields:
            continue
        seen.update(fields)
        option_groups.append(
            {
                "option_key": option.get("key"),
                "option_label": option.get("label"),
                "status": option.get("status"),
                "cta_url": (option.get("cta") or {}).get("url", ""),
                "fields": fields,
                "display_fields": [_field_label(field) for field in fields],
            }
        )
    base["option_groups"] = option_groups
    base["tumor_board_missing_fields"] = sorted(seen)
    base["tumor_board_missing_count"] = len(seen)
    return base


def _build_comparative_matrix(options: list[dict[str, Any]], context: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for option in options:
        rows.append(
            {
                "option_key": option.get("key"),
                "option_label": option.get("label"),
                "status": option.get("status"),
                "benefit": _matrix_cell(option, context, "benefit"),
                "evidence": _matrix_cell(option, context, "evidence"),
                "safety": _matrix_cell(option, context, "safety"),
                "patient_fit": _matrix_cell(option, context, "patient_fit"),
                "feasibility": _matrix_cell(option, context, "feasibility"),
                "monitoring_burden": _matrix_cell(option, context, "monitoring_burden"),
            }
        )
    return {"rows": rows, "source": "tumor_board_os_deterministic_matrix"}


def _matrix_cell(option: Mapping[str, Any], context: Mapping[str, Any], axis: str) -> str:
    status = str(option.get("status") or "")
    profile = _family_profile(option.get("family_code"), context)
    if axis == "evidence":
        return _first_text(
            profile.get("evidence_level"),
            (option.get("evidence") or {}).get("level"),
            "Evidencia integrada pendiente de trazabilidad completa" if status != "releaseable" else "Evidencia trazable",
        )
    if axis == "safety":
        blockers = list((option.get("safety") or {}).get("blockers") or [])
        return "Bloqueos de seguridad" if blockers else "Sin bloqueo de seguridad visible"
    if axis == "patient_fit":
        if status == "requires_data":
            return "No evaluable por datos faltantes"
        if status == "blocked":
            return "No apto hasta resolver bloqueo"
        return "Compatible con datos actuales"
    if axis == "feasibility":
        return "Captura adicional requerida" if option.get("missing_fields") else "Factible con datos actuales"
    if axis == "monitoring_burden":
        return "Alta" if option.get("family_code") in {"triplet_family", "psma_rlt_family", "parp_family"} else "Moderada"
    return _first_text(profile.get("benefit"), profile.get("summary"), "Beneficio dependiente de cierre de datos")


def _build_tumor_board_note(
    *,
    state: str,
    recommendation: Mapping[str, Any],
    winner: Mapping[str, Any],
    capture_plan: Mapping[str, Any],
) -> dict[str, Any]:
    missing = list(capture_plan.get("tumor_board_missing_fields") or [])
    return {
        "clinician_summary": _first_text(
            recommendation.get("title"),
            "Tumor Board OS sin recomendación liberable.",
        ),
        "patient_discussion": (
            f"Estado actual {state}. Se comparan opciones; "
            f"{'faltan datos antes de decidir.' if missing else 'la opción prioritaria tiene datos suficientes.'}"
        ),
        "orders_to_consider": [_field_label(field) for field in missing[:6]],
        "followup_plan": _first_text(
            (winner.get("cta") or {}).get("label"),
            "Continuar captura longitudinal según readiness.",
        ),
    }


def _build_trial_audit(patient: Mapping[str, Any], state: str) -> dict[str, Any]:
    try:
        from prostanet.shared.trial_criteria_registry import TRIAL_CRITERIA_REGISTRY
        from prostanet.shared.trial_eligibility_engine import evaluate_trial_eligibility
    except Exception:
        return {"total_trials": 0, "eligible_count": 0, "requires_data_count": 0, "empty_payload_guard_ok": False}

    payload = _trial_payload(patient, state)
    eligible: list[str] = []
    requires_data: list[str] = []
    ineligible: list[str] = []
    for trial_id in TRIAL_CRITERIA_REGISTRY:
        try:
            result = evaluate_trial_eligibility(payload, trial_id)
        except Exception:
            continue
        if result.get("eligible") is True and result.get("status") == "eligible":
            eligible.append(str(trial_id))
        elif result.get("status") == "requires_data":
            requires_data.append(str(trial_id))
        else:
            ineligible.append(str(trial_id))

    empty_guard_ok = True
    for trial_id in TRIAL_CRITERIA_REGISTRY:
        try:
            empty = evaluate_trial_eligibility({}, trial_id)
        except Exception:
            empty_guard_ok = False
            break
        if empty.get("eligible") is True or empty.get("status") != "requires_data":
            empty_guard_ok = False
            break
    return {
        "total_trials": len(TRIAL_CRITERIA_REGISTRY),
        "eligible_count": len(eligible),
        "requires_data_count": len(requires_data),
        "ineligible_count": len(ineligible),
        "eligible_trials": eligible[:12],
        "requires_data_trials": requires_data[:12],
        "empty_payload_guard_ok": empty_guard_ok,
        "status_contract": "eligible | ineligible | requires_data",
    }


def _trial_payload(patient: Mapping[str, Any], state: str) -> dict[str, Any]:
    values = _flatten_values(patient)
    payload = dict(values)
    payload.setdefault("disease_state", state)
    payload.setdefault("current_state", state)
    if "psa_value" not in payload:
        payload["psa_value"] = _first_value(values, "psa", "baseline_psa", "psa_baseline", "psa_current")
    if "ecog_current" not in payload:
        payload["ecog_current"] = _first_value(values, "ecog_score", "ecog", "performance_status_ecog")
    if "hrr_status" not in payload:
        payload["hrr_status"] = _first_value(values, "hrr_brca_status", "hrr_overall", "brca2_status", "brca1_status")
    return payload


def _apply_hypothetical_changes(
    patient: dict[str, Any],
    bundle: dict[str, Any],
    changes: Mapping[str, Any],
) -> None:
    for namespace in (
        patient.setdefault("baseline", {}),
        patient.setdefault("prior_history", {}),
        patient.setdefault("identity", {}),
        patient.setdefault("latest_assessment", {}),
        (patient.setdefault("latest_assessment", {}).setdefault("input_snapshot", {})),
    ):
        if isinstance(namespace, dict):
            namespace.update(dict(changes))
    signals = bundle.setdefault("signals", {})
    if isinstance(signals, dict):
        signals.update(dict(changes))
    truth = bundle.setdefault("longitudinal_truth_snapshot", {})
    if isinstance(truth, dict):
        values = truth.setdefault("field_values", {})
        if isinstance(values, dict):
            values.update(dict(changes))
    state = _reclassify_state(patient, changes)
    if state:
        patient["current_state"] = state
        patient.setdefault("latest_assessment", {})["state"] = state
        if isinstance(signals, dict):
            signals["effective_state"] = state
            signals["effective_state_final"] = state
            signals["reconciled_state"] = state


def _reclassify_state(patient: Mapping[str, Any], changes: Mapping[str, Any]) -> str:
    try:
        from prostanet.domains.state_classifier.service import StateClassifierService
    except Exception:
        return ""
    payload = {}
    for source in (
        patient.get("baseline") or {},
        patient.get("prior_history") or {},
        patient.get("identity") or {},
        patient.get("latest_assessment") or {},
        changes,
    ):
        if isinstance(source, Mapping):
            payload.update(dict(source))
    try:
        result = StateClassifierService().classify(payload)
    except Exception:
        return ""
    return _text(result.get("state") if isinstance(result, Mapping) else "")


def _state_group(state: str) -> str:
    text = str(state or "").lower()
    if any(token in text for token in ("screening", "diagnostic", "negative_biopsy", "post_negative")):
        return "diagnostic"
    if "localized" in text:
        return "localized"
    if any(token in text for token in ("bcr", "post_prostatectomy", "post_radiotherapy", "salvage")):
        return "postlocal_bcr"
    if "m0_crpc" in text or "m0crpc" in text:
        return "m0_crpc"
    if "m1_crpc" in text or "m1crpc" in text:
        return "m1_crpc"
    if "adt_progression" in text:
        return "adt_progression"
    if "mcspc" in text or "mhspc" in text:
        return "mhspc"
    return "diagnostic"


def _dominant_blocker(options: list[dict[str, Any]], readiness: Mapping[str, Any]) -> str:
    for option in options:
        if option.get("status") in {"blocked", "requires_data"}:
            blockers = list(option.get("release_blockers") or []) + list(option.get("display_missing_fields") or [])
            if blockers:
                return f"{option.get('label')}: {blockers[0]}"
    return _first_text((readiness.get("summary") or {}).get("dominant_blocker"), "Sin bloqueo dominante.")


def _allowed_actions(winner: Mapping[str, Any], options: list[dict[str, Any]]) -> list[str]:
    if winner.get("status") == "releaseable":
        return ["Documentar decisión compartida.", "Abrir orden o wizard correspondiente.", "Programar seguimiento longitudinal."]
    cta_label = (winner.get("cta") or {}).get("label")
    actions = [cta_label] if cta_label else []
    missing = list(winner.get("display_missing_fields") or [])
    actions.extend([f"Capturar {field}" for field in missing[:3]])
    if not actions:
        actions.append("Resolver bloqueo clínico antes de liberar recomendación.")
    return _dedupe(actions)[:5]


def _first_lane_cta(lanes: list[Mapping[str, Any]], context: Mapping[str, Any]) -> dict[str, str]:
    for lane in lanes:
        url = _text(lane.get("cta_url"))
        if url:
            return {"label": f"Capturar {lane.get('label')}", "url": url, "readiness_lane": _text(lane.get("key"))}
    patient_ref = _text(context.get("patient_ref"))
    if patient_ref:
        return {"label": "Captura longitudinal", "url": f"/longitudinal-capture/{patient_ref}"}
    return {"label": "Clasificador oficial", "url": "/clinical-hub#pm2OfficialClassifier"}


def _family_profile(family_code: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    code = _text(family_code)
    if not code:
        return {}
    matrix = dict(context.get("comparative_matrix") or {})
    profile = matrix.get(code) or matrix.get(code.replace("_family", "")) or {}
    return dict(profile) if isinstance(profile, Mapping) else {}


def _option_evidence(
    option: Mapping[str, Any],
    family_profile: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    decision_evidence = dict(context.get("decision_evidence") or {})
    return {
        "level": _first_text(family_profile.get("evidence_level"), family_profile.get("level"), "local_registry"),
        "basis": _dedupe(
            _as_list(family_profile.get("matched_trials"))
            + _as_list(family_profile.get("evidence_basis"))
            + _as_list(option.get("trials_impacted"))
        )[:8],
        "currentness_status": _first_text(
            decision_evidence.get("selected_decision_evidence_status"),
            decision_evidence.get("status"),
            "unknown",
        ),
        "anchors": list(EVIDENCE_ANCHORS),
    }


def _option_safety(
    option: Mapping[str, Any],
    family_profile: Mapping[str, Any],
    therapeutic: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "blockers": _dedupe(
            _as_list(family_profile.get("hard_blocks"))
            + _as_list(family_profile.get("contraindication_reasons"))
            + _as_list(therapeutic.get("safety_blockers"))
        )[:8],
        "watchouts": _dedupe(
            _as_list(family_profile.get("safety_watchouts"))
            + _as_list(therapeutic.get("required_support_actions"))
        )[:8],
    }


def _evidence_is_stale(decision_evidence: Mapping[str, Any], therapeutic: Mapping[str, Any]) -> bool:
    status_text = " ".join(
        _lower(item)
        for item in (
            decision_evidence.get("selected_decision_evidence_status"),
            decision_evidence.get("selected_decision_release_status"),
            therapeutic.get("selected_therapy_evidence_status"),
        )
        if item
    )
    return any(token in status_text for token in ("stale", "expired", "requires_refresh", "review"))


def _supported_what_if_inputs(capture_plan: Mapping[str, Any]) -> list[str]:
    fields = []
    for group in list(capture_plan.get("groups") or []) + list(capture_plan.get("option_groups") or []):
        if isinstance(group, Mapping):
            fields.extend(_as_list(group.get("fields")))
    fields.extend(
        [
            "psa_value",
            "testosterone_value",
            "psa_doubling_time_months",
            "metastasis_site",
            "ecog_score",
            "hrr_status",
            "psma_pet_positive_current",
            "line_of_therapy",
        ]
    )
    return _dedupe(fields)[:20]


def _sources_used(patient: Mapping[str, Any], bundle: Mapping[str, Any], readiness: Mapping[str, Any]) -> list[str]:
    sources = []
    if patient.get("baseline"):
        sources.append("clinical_baseline")
    if patient.get("latest_assessment"):
        sources.append("latest_assessment")
    if patient.get("biomarker_longitudinal"):
        sources.append("biomarker_longitudinal")
    if patient.get("treatments"):
        sources.append("treatment_history")
    for key in (
        "longitudinal_truth_snapshot",
        "decision_input_requirements",
        "therapeutic_readiness_bundle",
        "clinical_readiness_tower",
        "supportive_care_toxicity_readiness_bundle",
        "comparative_eligibility_matrix",
        "decision_evidence_currentness_bundle",
        "signals",
    ):
        if bundle.get(key):
            sources.append(key)
    if readiness:
        sources.append("clinical_readiness_tower")
    return sorted(set(sources))


def _option_contract_set(board: Mapping[str, Any], key: str) -> set[str]:
    result = set()
    for option in list(board.get("options") or []):
        if isinstance(option, Mapping):
            result.update(str(item) for item in list(option.get(key) or []) if str(item).strip())
    return result


def _flatten_values(patient: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}

    def absorb(source: Any) -> None:
        if not isinstance(source, Mapping):
            return
        for key, value in source.items():
            if isinstance(value, (Mapping, list, tuple)):
                continue
            if value is not None and str(value).strip() != "":
                values[str(key)] = value

    for source in (
        patient,
        patient.get("identity") or {},
        patient.get("baseline") or {},
        patient.get("prior_history") or {},
        patient.get("latest_assessment") or {},
        (patient.get("latest_assessment") or {}).get("input_snapshot") or {},
    ):
        absorb(source)
    for item in patient.get("biomarker_longitudinal") or []:
        if not isinstance(item, Mapping):
            continue
        biomarker = str(item.get("biomarker_type") or item.get("type") or "").lower()
        if "psa" in biomarker or "ape" in biomarker:
            values["psa_value"] = item.get("value")
        if "testost" in biomarker:
            values["testosterone_value"] = item.get("value")
    return values


def _first_value(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if values.get(key) not in (None, ""):
            return values.get(key)
    return None


def _field_label(field: str) -> str:
    return FIELD_LABELS.get(str(field), str(field).replace("_", " "))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if value in (None, "", {}):
        return []
    return [value]


def _dedupe(values: Iterable[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


__all__ = [
    "TUMOR_BOARD_OPTION_STATUSES",
    "build_tumor_board_os",
    "build_tumor_board_what_if_delta",
]
