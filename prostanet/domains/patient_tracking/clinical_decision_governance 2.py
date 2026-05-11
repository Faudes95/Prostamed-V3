from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.localized_initial.rules_nccn import active_surveillance_position
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    _blocking_input_satisfied,
    _field_values as _decision_field_values,
    merge_staging_adjudication_into_requirements,
)
from prostanet.domains.patient_tracking.localized_modality import (
    build_active_surveillance_monitoring_profile,
    build_localized_modality_fitness_bundle,
    build_localized_survival_context_bundle,
    build_localized_tradeoff_bundle,
    build_radical_prostatectomy_candidacy_profile,
    parse_patient_priority_profile,
    should_require_localized_modality_dataset,
)
from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
from prostanet.domains.patient_tracking.score_interpretation_catalog import (
    build_score_interpretation_snapshot,
)
from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.domains.reporting.decision_aids import DecisionAidService
from prostanet.domains.patient_tracking.closure_window_registry import enrich_window_with_registry
from prostanet.domains.patient_tracking.decision_evidence_currentness_builder import (
    build_decision_evidence_currentness_bundle,
)
from prostanet.domains.patient_tracking.post_rp_salvage_intensification_builder import (
    build_post_rp_salvage_intensification_profile,
)
from prostanet.shared.ddi_engine import DDIEngine
from prostanet.shared.metastatic_profile import resolve_metastatic_state_context


LOCALIZED_PRO_FIELDS = [
    "epic26_urinary_incontinence_domain",
    "epic26_urinary_irritative_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
    "epic26_overall_urinary_bother",
    "ipss_total",
    "iief5_score",
    "eq5d_vas",
]

ADVANCED_PRO_FIELDS = [
    "fact_p_total",
    "eortc_qlq_c30_global_health",
    "eortc_qlq_c30_physical",
    "eortc_qlq_c30_role",
    "eortc_qlq_c30_emotional",
    "eortc_qlq_c30_fatigue",
    "eortc_qlq_c30_pain",
    "bpi_worst_pain",
    "facit_fatigue_total",
    "fatigue_score",
    "eq5d_vas",
    "anxiety_score",
]

ICHOM_LOCALIZED_FIELDS = [
    "psa",
    "ipss_total",
    "iief5_score",
    "eq5d_vas",
    "epic26_urinary_incontinence_domain",
    "epic26_urinary_irritative_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
]

ICHOM_ADVANCED_FIELDS = [
    "psa",
    "eq5d_vas",
    "fact_p_total",
    "bpi_worst_pain",
    "fatigue_score",
    "facit_fatigue_total",
    "eortc_qlq_c30_global_health",
    "eortc_qlq_c30_pain",
]

HIGH_IMPACT_TRANSITIONS = {
    ("localized_initial", "m1_crpc"),
    ("localized_initial", "mcspc_oligo_metachronous"),
    ("localized_initial", "mcspc_low_volume_sync_oligo"),
    ("localized_initial", "mcspc_high_volume"),
    ("localized_initial", "mcspc_high_volume_sync"),
    ("localized_initial", "mcspc_high_volume_metachronous"),
    ("post_prostatectomy", "m0_crpc"),
    ("recurrence_bcr", "m0_crpc"),
    ("adt_progression_verification", "m0_crpc"),
    ("adt_progression_verification", "m1_crpc"),
    ("mcspc_oligo_metachronous", "m1_crpc"),
    ("mcspc_low_volume_sync_oligo", "m1_crpc"),
    ("mcspc_high_volume", "m1_crpc"),
    ("mcspc_high_volume_sync", "m1_crpc"),
    ("mcspc_high_volume_metachronous", "m1_crpc"),
}

POSTLOCAL_PRIORITY_STATES = {
    "post_prostatectomy",
    "recurrence_bcr",
    "post_radiotherapy_or_local_salvage",
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
}

LOCALIZED_MINIMUM_DECISIVE_FIELDS = [
    "clinical_risk_group",
    "pirads_score",
    "isup_grade",
    "clinical_tstage",
    "nodal_status",
    "metastasis_site",
    "positive_cores",
    "total_cores",
    "ecog_score",
    "charlson_score",
    "frailty_status",
    "g8_score",
    "anesthesia_surgical_fitness",
]

LOCALIZED_FUNCTIONAL_FIELDS = [
    "ipss_total",
    "epic26_urinary_incontinence_domain",
    "epic26_urinary_irritative_domain",
    "epic26_sexual_domain",
    "epic26_bowel_domain",
    "epic26_hormonal_domain",
    "epic26_overall_urinary_bother",
    "continence_status",
    "iief5_score",
    "patient_priority_profile",
]

LOCALIZED_MODALITY_FIELDS = [
    "radiotherapy_feasibility",
]

MHSPC_MINIMUM_DECISIVE_FIELDS = [
    "metastasis_site",
    "metastasis_count",
    "volume_disease",
    "bone_distribution_documented",
    "ecog",
    "frailty_status",
    "current_adt_context",
    "hrr_status",
]

CRPC_MINIMUM_DECISIVE_FIELDS = [
    "testosterone",
    "current_adt_context",
    "progression_pattern",
    "conventional_imaging_status",
    "line_of_therapy_number",
    "drug_scheme",
    "hrr_status",
]

CRPC_RESTAGING_FIELDS = [
    "conventional_imaging_date",
    "psma_pet_done",
    "psma_rads_score",
    "psma_uptake_pattern",
]

WINDOW_RISK_PRIORITY = {
    "confirmed": 0,
    "possible": 1,
    "none": 2,
}

WINDOW_STATUS_PRIORITY = {
    "overdue": 0,
    "narrowing": 1,
    "open": 2,
    "redirected": 3,
    "closed": 4,
    "not_applicable": 5,
}

WINDOW_OWNER_DOMAIN = {
    "diagnostic_mri_biopsy_window": "diagnostic_workup",
    "active_surveillance_confirmatory_biopsy": "active_surveillance",
    "localized_modality_closure_window": "localized_modality_selection",
    "post_rp_salvage_window": "post_rp_salvage",
    "post_rt_salvage_window": "post_rt_salvage",
    "crpc_verification_window": "crpc_verification",
    "psma_eligibility_window": "molecular_restaging",
    "precision_hrr_testing_window": "precision_oncology",
    "adt_bone_cardiometabolic_bundle": "adt_supportive_care",
    "critical_pro_symptom_window": "pro_supportive_decision",
}

WINDOW_KEYWORDS = {
    "diagnostic_mri_biopsy_window": ["mri", "biops", "pi-rads", "psad", "lesión"],
    "active_surveillance_confirmatory_biopsy": ["biopsia confirmatoria", "confirmatory", "vigilancia activa"],
    "localized_modality_closure_window": ["ipss", "epic-26", "iief-5", "quirúrgica", "radioterapia", "preferencias"],
    "post_rp_salvage_window": ["salvage", "psma", "psadt", "post-rp", "prostatectom"],
    "post_rt_salvage_window": ["salvage", "post-rt", "phoenix", "psma", "reestadificación"],
    "crpc_verification_window": ["testosterona", "restaging", "crpc", "castración", "psma"],
    "psma_eligibility_window": ["psma", "pet/ct", "reestadificación"],
    "precision_hrr_testing_window": ["hrr", "germinal", "somát", "parp", "genét"],
    "adt_bone_cardiometabolic_bundle": ["dxa", "óseo", "cardio", "vitamina d", "metab"],
    "critical_pro_symptom_window": ["pro", "dolor", "calidad de vida", "fatiga", "síntomas"],
}


def _is_present(value: Any) -> bool:
    return value not in (
        None,
        "",
        [],
        {},
        "No aplica",
        "No documentado",
        "No realizado",
        "Desconocido",
        "Desconocida",
        "unknown",
        "UNKNOWN",
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in values if item not in (None, "", [], {})))


def _latest(items: list[dict[str, Any]], *date_keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in date_keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key) or ""), reverse=True)[0]
    return items[0]


def _yes_no_unknown(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1", "si", "sí"}:
        return "yes"
    if text in {"no", "false", "0"}:
        return "no"
    return "unknown"


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "positive", "positivo"}


def _window_priority_tuple(window: dict[str, Any]) -> tuple[int, int, int, str]:
    risk = str(window.get("opportunity_loss_risk") or "none").lower()
    status = str(window.get("window_status") or "open").lower()
    sensitivity = str(window.get("time_sensitivity") or "moderate").lower()
    sensitivity_rank = 0 if sensitivity == "high" else 1 if sensitivity == "moderate" else 2
    return (
        WINDOW_RISK_PRIORITY.get(risk, 3),
        WINDOW_STATUS_PRIORITY.get(status, 6),
        sensitivity_rank,
        str(window.get("window_key") or ""),
    )


def _window_task_template(
    *,
    task_key: str,
    label: str,
    matched_inputs: list[str] | None = None,
    keywords: list[str] | None = None,
    action_type: str = "capture",
) -> dict[str, Any]:
    return {
        "task_key": task_key,
        "label": label,
        "matched_inputs": list(matched_inputs or []),
        "keywords": list(keywords or []),
        "action_type": action_type,
    }


def _window_closure_plan(window: dict[str, Any]) -> dict[str, Any]:
    window_key = str(window.get("window_key") or "")
    required_inputs = list(window.get("required_inputs") or [])
    window_status = str(window.get("window_status") or "open").lower()
    if window_key == "diagnostic_mri_biopsy_window":
        return {
            "what_closes_this_window": "Documentar PSA repetido cuando aplique, MRI/PSAD y cerrar un plan de biopsia estructurada o rebiopsia dirigida.",
            "why_this_matters_now": "La sospecha diagnóstica persistente no debe quedarse en observación pasiva cuando PSA repetido, MRI, PSAD o biopsia cambian la conducta.",
            "if_not_closed_clinical_consequence": "Puede retrasarse la confirmación histológica y perderse el momento adecuado para decidir biopsia dirigida o reabrir el estudio.",
            "closure_tasks": [
                _window_task_template(
                    task_key="diagnostic_window_capture",
                    label="Completar PSA repetido cuando corresponda, MRI prebiopsia, PSAD y vía de biopsia dirigida/sistemática.",
                    matched_inputs=required_inputs or ["repeat_psa_value", "repeat_psa_date", "pirads_score", "psad", "planned_biopsy_route"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "active_surveillance_confirmatory_biopsy":
        return {
            "what_closes_this_window": "Completar la biopsia confirmatoria y revalidar continuidad de vigilancia activa.",
            "why_this_matters_now": "La vigilancia activa pierde seguridad si la biopsia confirmatoria se retrasa.",
            "if_not_closed_clinical_consequence": "Puede retrasarse la reclasificación y mantenerse vigilancia activa en un caso que ya cambió de riesgo.",
            "closure_tasks": [
                _window_task_template(
                    task_key="as_confirmatory_biopsy",
                    label="Programar y documentar biopsia confirmatoria en vigilancia activa.",
                    matched_inputs=required_inputs or ["confirmatory_biopsy_done"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "localized_modality_closure_window":
        return {
            "what_closes_this_window": "Completar baseline funcional, aptitud anatómico-técnica y prioridades del paciente para decidir cirugía vs radioterapia vs vigilancia.",
            "why_this_matters_now": "El riesgo oncológico ya está cerrado, pero la modalidad local no debe decidirse sin trade-off funcional, factibilidad real y prioridades explícitas.",
            "if_not_closed_clinical_consequence": "Puede sobrepriorizarse una modalidad por grupo de riesgo y no por aptitud real del paciente.",
            "closure_tasks": [
                _window_task_template(
                    task_key="localized_modality_closure",
                    label="Completar IPSS/IIEF-5/EPIC-26, aptitud quirúrgica/RT y prioridades del paciente antes de cerrar modalidad local.",
                    matched_inputs=required_inputs or LOCALIZED_MODALITY_FIELDS,
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "post_rp_salvage_window":
        return {
            "what_closes_this_window": (
                "Definir PSADT, factibilidad local e imagen molecular para cerrar si el salvage sigue abierto."
                if window_status not in {"closed", "redirected"}
                else "Documentar cierre o redirección de salvage y redefinir el siguiente carril terapéutico."
            ),
            "why_this_matters_now": "En post-RP/BCR la oportunidad terapéutica depende del momento en que se caracteriza la recaída.",
            "if_not_closed_clinical_consequence": "Puede perderse una ventana de salvage potencialmente curativa o redirigirse tarde la secuencia sistémica.",
            "closure_tasks": [
                _window_task_template(
                    task_key="post_rp_salvage_closure",
                    label="Completar PSADT, PSMA y factibilidad local para decidir salvage post-RP.",
                    matched_inputs=required_inputs or ["psadt_months", "salvage_local_feasible", "psma_pet_done"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "post_rt_salvage_window":
        return {
            "what_closes_this_window": "Separar rebote de PSA, fracaso bioquímico real y patrón de recaída para decidir salvage/MDT/redirección.",
            "why_this_matters_now": "En post-RT el valor clínico está en no confundir rebote con recaída local o sistémica.",
            "if_not_closed_clinical_consequence": "Puede abrirse un salvage inapropiado o cerrarse una opción local todavía viable.",
            "closure_tasks": [
                _window_task_template(
                    task_key="post_rt_salvage_closure",
                    label="Completar definición Phoenix, confirmación local y PSMA para decidir rescue post-RT.",
                    matched_inputs=required_inputs or ["phoenix_delta", "biopsy_proven_local_recurrence", "psma_pet_done"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "crpc_verification_window":
        return {
            "what_closes_this_window": "Documentar testosterona en castración y completar restaging antes de consolidar CRPC.",
            "why_this_matters_now": "La transición a CRPC no debe cerrarse sin castración bioquímica y progresión correctamente documentadas.",
            "if_not_closed_clinical_consequence": "Puede etiquetarse mal la transición clínica y abrirse una secuencia sistémica incorrecta.",
            "closure_tasks": [
                _window_task_template(
                    task_key="crpc_verification",
                    label="Tomar testosterona sérica y completar restaging para verificar CRPC.",
                    matched_inputs=required_inputs or ["testosterone", "conventional_imaging_status", "psma_pet_done"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "psma_eligibility_window":
        return {
            "what_closes_this_window": "Realizar PSMA PET/CT y documentar si modifica la conducta.",
            "why_this_matters_now": "PSMA puede separar mejor ruta local, MDT y enfermedad sistémica en BCR, salvage y avanzada.",
            "if_not_closed_clinical_consequence": "Puede mezclarse inapropiadamente una ruta local con una sistémica o retrasarse la reestadificación.",
            "closure_tasks": [
                _window_task_template(
                    task_key="psma_restaging",
                    label="Solicitar y documentar PSMA PET/CT en escenario con impacto conductual.",
                    matched_inputs=required_inputs or ["psma_pet_done"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "precision_hrr_testing_window":
        return {
            "what_closes_this_window": "Completar workflow HRR germinal/somático y dejar trazado su impacto terapéutico.",
            "why_this_matters_now": "Sin HRR testing se pierden rutas de precisión y comparabilidad registral en enfermedad avanzada.",
            "if_not_closed_clinical_consequence": "Puede omitirse elegibilidad para PARP u otra ruta guiada por biología.",
            "closure_tasks": [
                _window_task_template(
                    task_key="precision_hrr_workflow",
                    label="Solicitar o documentar HRR germinal/somático y fecha de ensayo molecular.",
                    matched_inputs=required_inputs or ["hrr_status", "biomarker_source", "molecular_assay_date"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "adt_bone_cardiometabolic_bundle":
        return {
            "what_closes_this_window": "Completar DXA y evaluación cardiometabólica basal bajo ADT.",
            "why_this_matters_now": "La intensificación con ADT sin bundle óseo/cardiometabólico deja una brecha operativa de seguridad.",
            "if_not_closed_clinical_consequence": "Aumenta el riesgo de toxicidad prevenible y reduce calidad del seguimiento longitudinal.",
            "closure_tasks": [
                _window_task_template(
                    task_key="adt_supportive_bundle",
                    label="Completar DXA basal y riesgo cardiometabólico bajo ADT.",
                    matched_inputs=required_inputs or ["dxa_baseline_done", "cv_risk_documented"],
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    if window_key == "critical_pro_symptom_window":
        return {
            "what_closes_this_window": "Capturar PROs críticos y ajustar soporte o intensidad terapéutica visible.",
            "why_this_matters_now": "Los PROs críticos ya cambian la conducta y no deben quedarse solo como monitoreo pasivo.",
            "if_not_closed_clinical_consequence": "Puede mantenerse una intensidad terapéutica desalineada con la carga sintomática real.",
            "closure_tasks": [
                _window_task_template(
                    task_key="critical_pro_capture",
                    label="Completar PROs críticos y documentar ajuste clínico o soporte.",
                    matched_inputs=required_inputs,
                    keywords=WINDOW_KEYWORDS[window_key],
                ),
            ],
        }
    return {
        "what_closes_this_window": "Completar los datos faltantes que cierran la ventana clínica vigente.",
        "why_this_matters_now": window.get("window_reason") or "Existe una ventana clínica activa que debe resolverse.",
        "if_not_closed_clinical_consequence": window.get("opportunity_loss_reason") or "La oportunidad clínica puede deteriorarse si no se actúa.",
        "closure_tasks": [
            _window_task_template(
                task_key=f"{window_key or 'window'}_closure",
                label="Completar datos y redefinir la acción clínica prioritaria.",
                matched_inputs=required_inputs,
                keywords=WINDOW_KEYWORDS.get(window_key, []),
            ),
        ],
    }


def _build_window_worklist_bundle(
    patient: dict[str, Any],
    therapeutic_window_bundle: dict[str, Any],
    minimum_decisive_dataset_bundle: dict[str, Any],
    decision_governance_bundle: dict[str, Any],
    state_transition_confirmation_bundle: dict[str, Any],
    adherence_tracking_bundle: dict[str, Any],
    endpoint_adjudication_bundle: dict[str, Any],
    care_intent_contract: dict[str, Any],
    next_best_action: dict[str, Any],
) -> dict[str, Any]:
    windows = [dict(item) for item in list(therapeutic_window_bundle.get("windows") or [])]
    if not windows:
        return {
            "available": False,
            "top_active_window": {},
            "active_windows_ranked": [],
            "closure_tasks": [],
            "blocking_dataset_fields": list(minimum_decisive_dataset_bundle.get("missing_required_fields") or []),
            "opportunity_loss_summary": {
                "time_to_window_closure": None,
                "critical_windows_open_count": 0,
                "critical_windows_overdue_count": 0,
                "salvage_window_closed_without_action": 0,
                "psma_delayed_when_indicated": 0,
                "hrr_testing_missing_when_indicated": 0,
                "confirmatory_biopsy_missed": 0,
                "crpc_reclassification_delayed": 0,
                "opportunity_loss_confirmed_count": 0,
            },
            "resolved_windows": [],
            "recent_window_events": list(patient.get("therapeutic_window_events") or [])[:6],
        }
    blocking_dataset_fields = _dedupe(
        list(minimum_decisive_dataset_bundle.get("missing_required_fields") or [])
        + list(minimum_decisive_dataset_bundle.get("missing_decision_fields") or [])
    )
    ranked_windows: list[dict[str, Any]] = []
    for window in sorted(windows, key=_window_priority_tuple):
        window = enrich_window_with_registry(window)
        plan = _window_closure_plan(window)
        enriched = dict(window)
        enriched.update(plan)
        enriched["deadline_status"] = str(window.get("window_status") or "open")
        enriched["owner_domain"] = WINDOW_OWNER_DOMAIN.get(str(window.get("window_key") or ""), "clinical_governance")
        enriched["missing_decisive_fields"] = _dedupe(
            list(window.get("required_inputs") or []) + blocking_dataset_fields
        )
        enriched["priority_rank"] = len(ranked_windows) + 1
        if state_transition_confirmation_bundle.get("pending_count"):
            enriched["pending_transition_confirmations"] = int(state_transition_confirmation_bundle.get("pending_count") or 0)
        if adherence_tracking_bundle.get("overdue_or_missed_count"):
            enriched["active_adherence_gap_count"] = int(adherence_tracking_bundle.get("overdue_or_missed_count") or 0)
        if endpoint_adjudication_bundle.get("pending_adjudications"):
            enriched["pending_adjudication_count"] = len(list(endpoint_adjudication_bundle.get("pending_adjudications") or []))
        ranked_windows.append(enriched)
    top_window = dict(ranked_windows[0] if ranked_windows else {})
    recent_events = [dict(item) for item in list(patient.get("therapeutic_window_events") or [])[:6]]
    resolved_windows = [
        dict(item)
        for item in recent_events
        if str(item.get("window_closed_at") or "").strip()
    ]
    closure_deltas = []
    for item in resolved_windows:
        opened = str(item.get("window_opened_at") or "")[:19]
        closed = str(item.get("window_closed_at") or "")[:19]
        if not opened or not closed:
            continue
        try:
            closure_deltas.append(int((datetime.fromisoformat(closed) - datetime.fromisoformat(opened)).days))
        except ValueError:
            continue
    opportunity_loss_summary = {
        "time_to_window_closure": round(sum(closure_deltas) / len(closure_deltas), 1) if closure_deltas else None,
        "critical_windows_open_count": sum(
            1 for item in ranked_windows if str(item.get("opportunity_loss_risk") or "") in {"possible", "confirmed"}
        ),
        "critical_windows_overdue_count": sum(
            1 for item in ranked_windows if str(item.get("window_status") or "") in {"overdue", "closed"}
        ),
        "salvage_window_closed_without_action": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("window_key") or "") in {"post_rp_salvage_window", "post_rt_salvage_window"}
            and str(item.get("closure_type") or item.get("window_status") or "") in {"missed", "closed"}
        ),
        "psma_delayed_when_indicated": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("window_key") or "") == "psma_eligibility_window"
            and str(item.get("opportunity_loss_risk") or "") in {"possible", "confirmed"}
        ),
        "hrr_testing_missing_when_indicated": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("window_key") or "") == "precision_hrr_testing_window"
            and str(item.get("opportunity_loss_risk") or "") in {"possible", "confirmed"}
        ),
        "confirmatory_biopsy_missed": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("window_key") or "") == "active_surveillance_confirmatory_biopsy"
            and str(item.get("opportunity_loss_risk") or "") == "confirmed"
        ),
        "crpc_reclassification_delayed": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("window_key") or "") == "crpc_verification_window"
            and str(item.get("opportunity_loss_risk") or "") in {"possible", "confirmed"}
        ),
        "opportunity_loss_confirmed_count": sum(
            1
            for item in [*ranked_windows, *resolved_windows]
            if str(item.get("opportunity_loss_risk") or "") == "confirmed"
            or str(item.get("opportunity_lost") or "").lower() in {"1", "true", "yes"}
        ),
    }
    return {
        "available": True,
        "top_active_window": top_window,
        "active_windows_ranked": ranked_windows,
        "closure_tasks": list(top_window.get("closure_tasks") or []),
        "blocking_dataset_fields": blocking_dataset_fields,
        "opportunity_loss_risk": top_window.get("opportunity_loss_risk") or "none",
        "opportunity_loss_summary": opportunity_loss_summary,
        "resolved_windows": resolved_windows,
        "recent_window_events": recent_events,
        "care_goal": care_intent_contract.get("care_goal") or "",
        "governance_block_status": decision_governance_bundle.get("recommendation_block_status") or "",
        "current_next_best_action_title": next_best_action.get("title") or "",
    }


def prioritize_items_for_window_worklist(
    items: list[dict[str, Any]],
    window_worklist_bundle: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked = [dict(item) for item in list(items or [])]
    top_window = dict(window_worklist_bundle.get("top_active_window") or {})
    if not ranked or not top_window:
        return ranked
    target_inputs = {str(field).strip() for field in list(top_window.get("required_inputs") or []) if str(field).strip()}
    for task in list(top_window.get("closure_tasks") or []):
        target_inputs.update(str(field).strip() for field in list(task.get("matched_inputs") or []) if str(field).strip())
    keywords = [str(word).lower() for word in WINDOW_KEYWORDS.get(str(top_window.get("window_key") or ""), [])]
    for item in ranked:
        item_inputs = {
            str(field).strip()
            for field in list(item.get("required_inputs") or [])
            if str(field).strip()
        }
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("agenda_key") or ""),
                str(item.get("plan_key") or ""),
            ]
        ).lower()
        matched_inputs = sorted(target_inputs.intersection(item_inputs))
        keyword_match = any(keyword and keyword in haystack for keyword in keywords)
        item["window_closure_priority"] = bool(matched_inputs or keyword_match)
        item["window_matched_inputs"] = matched_inputs
        item["window_priority_rank"] = 0 if item["window_closure_priority"] else 1
    return sorted(
        ranked,
        key=lambda item: (
            int(item.get("window_priority_rank") or 1),
            str(item.get("ideal_due_at") or item.get("due_at") or ""),
            str(item.get("scheduled_due_at") or item.get("due_at") or ""),
            str(item.get("encounter_type") or item.get("item_type") or ""),
            str(item.get("title") or ""),
        ),
    )


def _latest_matching(items: list[dict[str, Any]], predicate, *date_keys: str) -> dict[str, Any]:
    filtered = [dict(item) for item in items if predicate(item)]
    return _latest(filtered, *date_keys)


def _collect_psa_points(patient: dict[str, Any], field_values: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in list(patient.get("biomarker_longitudinal") or []):
        if str(row.get("biomarker_type") or "").upper() != "PSA":
            continue
        value = _safe_float(row.get("value"))
        sample_date = str(row.get("sample_date") or "")[:10]
        if value is None or not sample_date:
            continue
        points.append({"date": sample_date, "value": value, "source": "biomarker_longitudinal"})
    baseline = dict(patient.get("baseline") or {})
    baseline_psa = _safe_float(
        baseline.get("baseline_psa")
        or baseline.get("psa")
        or field_values.get("index_psa_value")
    )
    diagnosis_date = str(
        (patient.get("identity") or {}).get("diagnosis_date")
        or baseline.get("baseline_psa_date")
        or field_values.get("index_psa_date")
        or ""
    )[:10]
    if baseline_psa is not None and diagnosis_date:
        points.append({"date": diagnosis_date, "value": baseline_psa, "source": "baseline"})
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    latest_followup_psa = _safe_float(latest_followup.get("psa_current") or latest_followup.get("psa"))
    latest_followup_date = str(latest_followup.get("visit_date") or "")[:10]
    if latest_followup_psa is not None and latest_followup_date:
        points.append({"date": latest_followup_date, "value": latest_followup_psa, "source": "followup"})
    repeat_psa_value = _safe_float(field_values.get("repeat_psa_value"))
    repeat_psa_date = str(field_values.get("repeat_psa_date") or "")[:10]
    if repeat_psa_value is not None and repeat_psa_date:
        points.append({"date": repeat_psa_date, "value": repeat_psa_value, "source": "repeat_psa"})
    unique = {}
    for point in points:
        unique[(point["date"], point["value"], point["source"])] = point
    return sorted(unique.values(), key=lambda item: (item.get("date") or "", item.get("source") or ""))


def _latest_mpmri_fact(patient: dict[str, Any]) -> dict[str, Any]:
    latest_fact = _latest(patient.get("mri_facts") or [], "fact_date")
    if latest_fact:
        return latest_fact
    return _latest_matching(
        patient.get("imaging_studies") or [],
        lambda item: "mri" in str(item.get("study_type") or "").lower(),
        "study_date",
    )


def _latest_psma_study(patient: dict[str, Any]) -> dict[str, Any]:
    return _latest_matching(
        patient.get("imaging_studies") or [],
        lambda item: "psma" in str(item.get("study_type") or "").lower(),
        "study_date",
    )


def _latest_conventional_staging_study(patient: dict[str, Any]) -> dict[str, Any]:
    return _latest_matching(
        patient.get("imaging_studies") or [],
        lambda item: any(
            token in str(item.get("study_type") or "").lower()
            for token in ("ct", "gammagrama", "bone", "convencional", "pet")
        )
        and "psma" not in str(item.get("study_type") or "").lower(),
        "study_date",
    )


def _latest_structured_biopsy(patient: dict[str, Any]) -> dict[str, Any]:
    session = _latest(patient.get("structured_biopsy_sessions") or [], "biopsy_date", "created_at")
    if session:
        return session
    return _latest(patient.get("biopsies") or [], "biopsy_date", "id")


def _latest_genomic_report(patient: dict[str, Any]) -> dict[str, Any]:
    return _latest(patient.get("genomic_reports") or [], "test_date", "id")


def _map_biopsy_strategy(payload: dict[str, Any]) -> str:
    systematic = list(payload.get("systematic_cores") or [])
    targeted = list(payload.get("targeted_cores") or [])
    biopsy_type = _normalized_text(payload.get("biopsy_type")).lower()
    if systematic and targeted:
        return "combined"
    if targeted or biopsy_type in {"fusion", "mri_targeted", "targeted"}:
        return "targeted"
    if systematic or biopsy_type in {"systematic", "sistematica", "sistematica", "transperineal", "transrectal"}:
        return "systematic"
    if "combin" in biopsy_type:
        return "combined"
    return ""


def _point_count_status(points: list[dict[str, Any]]) -> tuple[str, str]:
    if len(points) >= 2:
        return "repeated", points[-1]["date"]
    if len(points) == 1:
        return "single_available", ""
    return "missing", ""


def _coalesce_stage(*values: Any) -> str:
    for value in values:
        text = _normalized_text(value)
        if text:
            return text
    return ""


def _is_advanced_state(state: str) -> bool:
    return state in {
        "adt_progression_verification",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "m0_crpc",
        "m1_crpc",
    }


def _is_localized_postlocal_state(state: str) -> bool:
    return state in {
        "localized_initial",
        "post_prostatectomy",
        "recurrence_bcr",
        "post_radiotherapy_or_local_salvage",
        "active_surveillance",
    }


def _map_treatment_to_decision_aid_key(name: str) -> str | None:
    text = str(name or "").lower()
    if not text:
        return None
    if "surveillance" in text or "vigilancia" in text:
        return "active_surveillance"
    if "prostatect" in text or "cirug" in text:
        return "radical_prostatectomy"
    if "radiot" in text or "sbrt" in text or "imrt" in text or "brachy" in text:
        return "radiation_therapy"
    if "docetax" in text:
        return "docetaxel"
    if any(token in text for token in ("abirater", "enzalut", "apalut", "darolut")):
        return "adt_plus_arpi"
    if "adt" in text or "castr" in text or "leuprolide" in text or "goserelin" in text:
        return "adt_monotherapy"
    return None


def _merge_score_fields(patient: dict[str, Any], field_values: dict[str, Any]) -> dict[str, Any]:
    merged = dict(field_values or {})
    latest_pro = _latest(patient.get("pros") or [], "assessment_date")
    if latest_pro:
        for key, value in latest_pro.items():
            if _is_present(value) and not _is_present(merged.get(key)):
                merged[key] = value
    latest_biomarker = _latest(patient.get("biomarker_longitudinal") or [], "sample_date")
    if _is_present(latest_biomarker.get("value")) and str(latest_biomarker.get("biomarker_type") or "").upper() == "PSA":
        merged.setdefault("psa", latest_biomarker.get("value"))
    return normalize_epic26_payload(merged)


def _build_recommendation_blocking_bundle(
    decision_input_requirements: dict[str, Any],
) -> tuple[dict[str, Any], str, str, list[str]]:
    hard = list(decision_input_requirements.get("hard_blocking_inputs") or [])
    decision = list(decision_input_requirements.get("decision_blocking_inputs") or [])
    supportive = list(decision_input_requirements.get("supportive_gaps") or [])
    if hard:
        status = "hard_stop"
        reason = (
            "Faltan datos críticos que cambian la conducta clínica: "
            + ", ".join(hard[:6])
        )
        allowed = ["captura_critica", "recoleccion_documental", "revaluacion"]
    elif decision:
        status = "provisional"
        reason = (
            "La recomendación sigue abierta hasta cerrar datos decisionales: "
            + ", ".join(decision[:6])
        )
        allowed = ["captura_dirigida", "discusion_compartida_provisional", "monitorizacion_temporal"]
    else:
        status = "clear"
        reason = "La recomendación tiene los datos mínimos para sostener una conducta visible."
        allowed = ["recomendacion_final", "shared_decision", "planificacion"]
    bundle = {
        "available": True,
        "recommendation_block_status": status,
        "recommendation_block_reason": reason,
        "allowed_actions_while_blocked": allowed,
        "hard_blocking_inputs": hard,
        "decision_blocking_inputs": decision,
        "supportive_gaps": supportive,
        "capture_block": dict(decision_input_requirements.get("capture_block") or {}),
        "blocking_input_descriptors": list(decision_input_requirements.get("blocking_input_descriptors") or []),
    }
    return bundle, status, reason, allowed


def _build_clinician_decision_capture_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
) -> dict[str, Any]:
    captures = list(patient.get("clinical_decision_captures") or [])
    latest_capture = _latest(captures, "decision_finalized_at", "created_at")
    if latest_capture:
        latest_capture = dict(latest_capture)
        latest_capture["available"] = True
        latest_capture["decision_capture_status"] = "captured"
        return latest_capture
    audits = list(patient.get("recommendation_audit") or [])
    latest_audit = _latest(audits, "recorded_at")
    if latest_audit:
        return {
            "available": True,
            "decision_capture_status": latest_audit.get("decision_capture_status") or "inferred_only",
            "recommended_option": latest_audit.get("recommended_option") or next_best_action.get("title") or "",
            "recommended_family": latest_audit.get("recommendation_family") or next_best_action.get("recommendation_family") or "",
            "clinician_selected_option": latest_audit.get("clinician_selected_option") or latest_audit.get("selected_option") or "",
            "clinician_selected_family": latest_audit.get("clinician_selected_family") or "",
            "followed_system_recommendation": latest_audit.get("followed_system_recommendation") or "unknown",
            "discordance_reason_category": latest_audit.get("discordance_reason_category") or "",
            "discordance_reason_free_text": latest_audit.get("discordance_reason") or "",
            "shared_with_patient": False,
            "tumor_board_required": False,
            "state_at_decision": (latest_assessment or {}).get("state") or "",
        }
    return {
        "available": False,
        "decision_capture_status": "missing",
        "recommended_option": next_best_action.get("title") or "",
        "recommended_family": next_best_action.get("recommendation_family") or "",
        "clinician_selected_option": "",
        "followed_system_recommendation": "unknown",
        "discordance_reason_category": "",
        "discordance_reason_free_text": "",
        "state_at_decision": (latest_assessment or {}).get("state") or "",
    }


def _is_high_impact_transition(proposal: dict[str, Any]) -> bool:
    from_state = str(proposal.get("from_state") or "")
    target_state = str(proposal.get("target_state") or "")
    if (from_state, target_state) in HIGH_IMPACT_TRANSITIONS:
        return True
    if target_state in {"supportive_only", "hospice_pathway"}:
        return True
    if "salvage" in target_state or "salvage" in str(proposal.get("proposal_key") or ""):
        return True
    return False


def _build_state_transition_confirmation_bundle(
    patient: dict[str, Any],
    transition_proposals: list[dict[str, Any]],
    decision_input_requirements: dict[str, Any],
) -> dict[str, Any]:
    proposals = [
        dict(proposal)
        for proposal in (transition_proposals or patient.get("transition_proposals") or [])
        if _is_high_impact_transition(proposal)
    ]
    for proposal in proposals:
        proposal.setdefault("confirmation_status", proposal.get("proposal_status") or "pending")
        proposal.setdefault(
            "requires_more_data_fields",
            list(decision_input_requirements.get("hard_blocking_inputs") or []),
        )
    return {
        "available": bool(proposals),
        "pending_count": sum(
            1 for proposal in proposals if str(proposal.get("confirmation_status") or "pending") == "pending"
        ),
        "requires_confirmation": bool(proposals),
        "high_impact_proposals": proposals,
    }


def _build_adherence_tracking_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    items = []
    today_iso = date.today().isoformat()
    for raw in list(patient.get("scheduled_events") or []):
        item = dict(raw)
        completed_at = str(item.get("performed_date") or item.get("completed_date") or item.get("completed_at") or "")[:10]
        due_at = str(item.get("scheduled_due_at") or item.get("due_date") or item.get("due_at") or "")[:10]
        completion_status = str(item.get("completion_status") or "").strip()
        if not completion_status:
            if completed_at and due_at:
                completion_status = "completed_on_time" if completed_at <= due_at else "completed_late"
            elif completed_at:
                completion_status = "completed_on_time"
            elif due_at and due_at < today_iso:
                completion_status = "missed"
            else:
                completion_status = "scheduled"
        days_late = item.get("days_late")
        if days_late in (None, "") and completed_at and due_at and completed_at > due_at:
            days_late = (datetime.fromisoformat(completed_at) - datetime.fromisoformat(due_at)).days
        elif days_late in (None, "") and due_at and due_at < today_iso and not completed_at:
            days_late = (datetime.fromisoformat(today_iso) - datetime.fromisoformat(due_at)).days
        item.update(
            {
                "scheduled_item_id": item.get("id"),
                "expected_action": item.get("label") or item.get("event_type") or "",
                "due_at": due_at,
                "performed_date": completed_at,
                "completion_status": completion_status,
                "completion_source": item.get("completion_source") or ("stage_visit" if item.get("completed_visit_id") else "manual"),
                "days_late": int(days_late or 0),
                "adherence_impact": item.get("adherence_impact") or (
                    "alto" if completion_status in {"missed", "completed_late"} else "controlado"
                ),
                "next_recovery_action": item.get("next_recovery_action") or (
                    "Reprogramar y recapturar evidencia de ejecución." if completion_status == "missed" else ""
                ),
            }
        )
        items.append(item)
    completed_on_time = sum(1 for item in items if item.get("completion_status") == "completed_on_time")
    eligible_items = [item for item in items if item.get("completion_status") in {"completed_on_time", "completed_late", "missed", "superseded"}]
    protocol_adherence_pct = round((completed_on_time / len(eligible_items)) * 100, 1) if eligible_items else 100.0
    guideline_concordance_pct = round((sum(1 for item in items if item.get("completion_status") in {"completed_on_time", "superseded"}) / len(eligible_items)) * 100, 1) if eligible_items else 100.0
    return {
        "available": bool(items),
        "items": items,
        "protocol_adherence_pct": protocol_adherence_pct,
        "guideline_concordance_pct": guideline_concordance_pct,
        "research_endpoint_validity": "robusta" if guideline_concordance_pct >= 80 else "limitada",
        "overdue_or_missed_count": sum(1 for item in items if item.get("completion_status") in {"completed_late", "missed"}),
    }


def _build_tumor_board_outcome_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    outcomes = list(patient.get("tumor_board_outcomes") or [])
    latest_outcome = _latest(outcomes, "discussion_date", "created_at")
    if latest_outcome:
        latest_outcome = dict(latest_outcome)
        latest_outcome["available"] = True
        return latest_outcome
    return {
        "available": False,
        "board_pending": bool(
            (latest_assessment or {}).get("result_snapshot", {}).get("tumor_board_required")
        ),
        "system_recommendation_at_board": "",
        "board_recommendation": "",
        "board_overrode_system": "unknown",
    }


def _build_pro_decision_bundle(
    patient: dict[str, Any],
    state: str,
    decision_input_requirements: dict[str, Any],
    field_values: dict[str, Any],
) -> dict[str, Any]:
    score_fields = _merge_score_fields(patient, field_values)
    score_snapshot = build_score_interpretation_snapshot(score_fields)
    alerts = [alert.to_dict() for alert in PRODecisionEngine.evaluate_all(int((patient.get("identity") or {}).get("id") or 0), score_fields)]
    if _is_advanced_state(state):
        required_fields = ADVANCED_PRO_FIELDS
    elif _is_localized_postlocal_state(state):
        required_fields = LOCALIZED_PRO_FIELDS
    else:
        required_fields = ["eq5d_vas", "ipss_total", "iief5_score"]
    missing_inputs = [field for field in required_fields if not _is_present(score_fields.get(field))]
    if any(alert.get("severity") == "critical" for alert in alerts):
        status = "escalation_trigger"
    elif any(alert.get("category") in {"pain", "qol", "fatigue"} for alert in alerts):
        status = "decision_modifier"
    elif alerts:
        status = "supportive_modifier"
    else:
        status = "none"
    recommended_modifier = ""
    if status == "escalation_trigger":
        recommended_modifier = "priorizar soporte, paliativos o reestadificación antes de intensificar."
    elif status == "decision_modifier":
        recommended_modifier = "recalibrar la intensidad terapéutica con base en calidad de vida y síntomas."
    elif status == "supportive_modifier":
        recommended_modifier = "mantener la recomendación oncológica, pero con mitigación sintomática activa."
    return {
        "available": bool(score_snapshot or alerts),
        "pro_decision_status": status,
        "dominant_pro_domain": (alerts[0].get("category") if alerts else ""),
        "pro_decision_reasons": [alert.get("title") for alert in alerts[:4]],
        "recommended_course_modifier": recommended_modifier,
        "pro_capture_readiness": "complete" if not missing_inputs else "incomplete",
        "required_fields": required_fields,
        "missing_inputs": missing_inputs,
        "alerts": alerts,
        "score_interpretation_catalog_snapshot": score_snapshot,
        "decision_input_overlap": _dedupe(
            list(decision_input_requirements.get("decision_blocking_inputs") or []) + missing_inputs
        ),
    }


def _build_cost_access_context_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
) -> dict[str, Any]:
    institution = str(
        (patient.get("baseline") or {}).get("institution")
        or (patient.get("baseline") or {}).get("institucion")
        or (patient.get("identity") or {}).get("institution")
        or "IMSS"
    )
    preferred = dict(((latest_assessment or {}).get("result_snapshot") or {}).get("preferred_frontline_regimen") or {})
    regimen_label = str(
        preferred.get("regimen_label")
        or preferred.get("regimen_code")
        or next_best_action.get("title")
        or ""
    )
    formulary = DDIEngine.check_formulary(regimen_label, institution) if regimen_label else {}
    return {
        "available": bool(regimen_label),
        "payer_context": institution.upper() if institution else "IMSS",
        "recommended_option": regimen_label,
        "monthly_cost_estimate": formulary.get("monthly_cost_mxn", 0),
        "access_status": "available" if formulary.get("available") else "restricted",
        "formularies_available": [formulary] if formulary else [],
        "cost_access_driver": formulary.get("exception_path", ""),
        "cost_effectiveness_context": (
            "Costo cubierto por formulario institucional." if formulary.get("monthly_cost_mxn", 0) == 0 else "Costo estimado mensual sin sustituir juicio clínico."
        ),
    }


def _build_shared_decision_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    next_best_action: dict[str, Any],
    recommendation_block_status: str,
    pro_decision_bundle: dict[str, Any],
    clinician_decision_capture_bundle: dict[str, Any],
    cost_access_context_bundle: dict[str, Any],
) -> dict[str, Any]:
    assessment = latest_assessment or patient.get("latest_assessment") or {}
    result = dict(assessment.get("result_snapshot") or {})
    eligible = list(result.get("eligible_treatments") or [])
    patient_priorities = []
    structured_priorities = parse_patient_priority_profile(
        (result.get("patient_priority_profile") or {}).get("priorities")
        or result.get("patient_priority_profile")
        or patient.get("patient_priority_profile")
        or (assessment.get("input_snapshot") or {}).get("patient_priority_profile")
    )
    patient_priorities.extend(structured_priorities)
    if clinician_decision_capture_bundle.get("patient_preference_driver"):
        patient_priorities.append(str(clinician_decision_capture_bundle.get("patient_preference_driver")))
    if str((patient.get("baseline") or {}).get("patient_prefers_comfort") or "").lower() in {"1", "true", "yes", "si", "sí"}:
        patient_priorities.append("calidad de vida")
    mapped_options = []
    patient_facing = []
    for option in eligible[:3]:
        option_name = str(option.get("name") if isinstance(option, dict) else option)
        if not option_name:
            continue
        patient_facing.append(option_name)
        mapped = _map_treatment_to_decision_aid_key(option_name)
        if mapped:
            mapped_options.append(mapped)
    if not patient_facing and next_best_action.get("title"):
        patient_facing.append(str(next_best_action.get("title")))
        mapped = _map_treatment_to_decision_aid_key(next_best_action.get("title"))
        if mapped:
            mapped_options.append(mapped)
    patient_priorities = _dedupe(patient_priorities)
    comparison = (
        DecisionAidService.generate_comparison(_dedupe(mapped_options), patient_priorities=patient_priorities)
        if mapped_options and recommendation_block_status != "hard_stop"
        else {}
    )
    readiness = "blocked" if recommendation_block_status == "hard_stop" else "provisional" if recommendation_block_status == "provisional" else "ready"
    qol_tradeoffs = list(pro_decision_bundle.get("pro_decision_reasons") or [])
    if cost_access_context_bundle.get("cost_access_driver"):
        qol_tradeoffs.append(f"Acceso/costo: {cost_access_context_bundle.get('cost_access_driver')}")
    return {
        "available": bool(patient_facing),
        "eligible_options_patient_facing": patient_facing,
        "absolute_benefit_display": comparison.get("options", []),
        "absolute_harm_display": [entry.get("side_effects_pictogram", []) for entry in comparison.get("options", [])],
        "qol_tradeoffs": qol_tradeoffs[:5],
        "patient_priority_alignment": comparison.get("priority_alignment", []),
        "decision_readiness": readiness,
        "second_opinion_printable_summary": comparison.get("shared_decision_note", ""),
    }


def _build_ctdna_refinement_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    detected = _yes_no_unknown(field_values.get("ctdna_detected"))
    vaf = _safe_float(field_values.get("ctdna_vaf"))
    rising = _yes_no_unknown(field_values.get("ctdna_rising"))
    role = "none"
    if rising == "yes":
        role = "escalation_trigger"
    elif detected == "yes" or vaf is not None:
        role = "monitoring_refiner"
    return {
        "available": detected != "unknown" or vaf is not None,
        "ctdna_detected": detected,
        "ctdna_vaf": vaf,
        "ctdna_rising": rising,
        "ctdna_sample_date": field_values.get("ctdna_sample_date") or "",
        "ctdna_platform": field_values.get("ctdna_platform") or "",
        "ctdna_hrr_status": field_values.get("ctdna_hrr_status") or field_values.get("hrr_status") or "",
        "ctdna_resistance_signals": _dedupe(
            [
                field_values.get("ctdna_arpi_resistance"),
                field_values.get("ctdna_psma_resistance"),
            ]
        ),
        "decision_role": role,
    }


def _build_multimodal_imaging_concordance_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    pirads = str(
        field_values.get("pirads_v21_score")
        or field_values.get("pirads_score")
        or field_values.get("prior_mpmri_pirads_score")
        or ""
    ).strip()
    psma_rads = str(field_values.get("psma_rads_score") or "").strip()
    mpmri_available = _yes_no_unknown(field_values.get("mpmri_done")) == "yes" or bool(pirads)
    psma_available = _yes_no_unknown(field_values.get("psma_pet_done")) == "yes" or bool(psma_rads)
    concordance = "insufficient_data"
    implication = ""
    if mpmri_available and psma_available:
        if pirads in {"4", "5"} and psma_rads in {"4", "5"}:
            concordance = "concordant"
            implication = "La lesión dominante es concordante en ambas modalidades."
        elif pirads in {"1", "2"} and psma_rads in {"4", "5"}:
            concordance = "discordant"
            implication = "Discordancia local vs sistémica; considerar correlación dirigida y biopsia."
        elif pirads in {"4", "5"} and psma_rads in {"1", "2", "3A", "3B"}:
            concordance = "partially_concordant"
            implication = "La MRI sugiere lesión significativa sin pleno soporte PSMA; requiere integración clínica."
        else:
            concordance = "partially_concordant"
            implication = "La imagen es incompletamente concordante y debe integrarse con biopsia/PSA."
    return {
        "available": mpmri_available or psma_available,
        "mpmri_available": mpmri_available,
        "pirads_v21_score": pirads,
        "prostate_volume_ml": _safe_float(field_values.get("prostate_volume") or field_values.get("prostate_volume_ml")),
        "psma_available": psma_available,
        "psma_rads_score": psma_rads,
        "uptake_pattern": field_values.get("psma_uptake_pattern") or "",
        "lesion_concordance_status": concordance,
        "discordance_implication": implication,
        "lesion_tracking_ready": bool(
            (field_values.get("index_lesion_location") or field_values.get("local_recurrence_site"))
            and (field_values.get("psma_lesion_locations") or field_values.get("psma_uptake_pattern"))
        ),
    }


def _build_ichom_compliance_bundle(state: str, field_values: dict[str, Any]) -> dict[str, Any]:
    required_fields = ICHOM_ADVANCED_FIELDS if _is_advanced_state(state) else ICHOM_LOCALIZED_FIELDS
    captured_fields = [field for field in required_fields if _is_present(field_values.get(field))]
    missing_fields = [field for field in required_fields if field not in captured_fields]
    compliance_pct = round((len(captured_fields) / len(required_fields)) * 100, 1) if required_fields else 0.0
    return {
        "available": True,
        "set_name": "ICHOM Advanced" if _is_advanced_state(state) else "ICHOM Localized",
        "required_fields": required_fields,
        "captured_fields": captured_fields,
        "missing_fields": missing_fields,
        "compliance_pct": compliance_pct,
        "comparable_export_ready": compliance_pct >= 70,
    }


def _build_treatment_adverse_event_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    adverse_events = list(patient.get("treatment_adverse_events") or [])
    recent = adverse_events[:8]
    grade_ge_3 = [event for event in adverse_events if int(event.get("ctcae_grade") or 0) >= 3]
    return {
        "available": bool(adverse_events),
        "events": recent,
        "grade_ge_3_count": len(grade_ge_3),
        "regimen_codes": _dedupe([event.get("regimen_code") for event in adverse_events]),
        "expected_vs_observed_context": [event.get("expected_vs_observed_context") for event in recent if event.get("expected_vs_observed_context")],
    }


def _build_population_survival_context_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    live_benchmark = dict(patient.get("live_benchmark") or {})
    trial_profile = dict(patient.get("current_trial_comparable_profile") or {})
    benchmark_reliability = dict(patient.get("benchmark_reliability") or {})
    return {
        "available": bool(live_benchmark or trial_profile),
        "seer_reference": live_benchmark.get("external_reference") or "SEER-like contextual reference unavailable",
        "pcbase_reference": live_benchmark.get("population_reference") or "",
        "population_match_quality": benchmark_reliability.get("cohort_tier") or benchmark_reliability.get("display_confidence_label") or "No disponible",
        "individual_vs_population_delta": trial_profile.get("recommended_trial_backbone_note") or "",
        "matched_population_snapshot": live_benchmark.get("matched_population_snapshot") or {},
    }


def _build_diagnostic_certainty_bundle(
    patient: dict[str, Any],
    state: str,
    field_values: dict[str, Any],
) -> dict[str, Any]:
    psa_points = _collect_psa_points(patient, field_values)
    repeat_psa_status, repeat_psa_date = _point_count_status(psa_points)
    latest_mri = _latest_mpmri_fact(patient)
    latest_biopsy = _latest_structured_biopsy(patient)
    latest_diagnostic_plan = _latest(patient.get("diagnostic_plans") or [], "plan_date", "id")
    latest_biopsy_trigger = _latest(patient.get("biopsy_triggers") or [], "trigger_date", "id")
    pirads = _normalized_text(
        latest_mri.get("pirads_score")
        or latest_biopsy.get("mri_pirads_at_biopsy")
        or field_values.get("pirads_v21_score")
        or field_values.get("pirads_score")
        or field_values.get("prior_mpmri_pirads_score")
    )
    prostate_volume_ml = _safe_float(
        latest_mri.get("prostate_volume_ml")
        or field_values.get("prostate_volume_ml")
        or field_values.get("prostate_volume")
    )
    index_psa_value = psa_points[0]["value"] if psa_points else _safe_float(field_values.get("psa"))
    index_psa_date = psa_points[0]["date"] if psa_points else ""
    repeat_psa_reason_not_done = _normalized_text(field_values.get("repeat_psa_reason_not_done"))
    psa_density = _safe_float(field_values.get("psad"))
    if psa_density is None and prostate_volume_ml and index_psa_value is not None and prostate_volume_ml > 0:
        psa_density = round(index_psa_value / prostate_volume_ml, 3)
    positive_cores = (
        latest_biopsy.get("total_positive")
        or latest_biopsy.get("positive_cores")
        or field_values.get("positive_cores")
        or field_values.get("num_cores_positive")
        or 0
    )
    total_cores = (
        latest_biopsy.get("total_cores")
        or field_values.get("total_cores")
        or 0
    )
    systematic_cores = list(latest_biopsy.get("systematic_cores") or [])
    targeted_cores = list(latest_biopsy.get("targeted_cores") or [])
    tumor_length_documented = any(core.get("tumor_length_mm") not in (None, "") for core in systematic_cores + targeted_cores)
    linkage_status = "unknown"
    if latest_biopsy.get("mri_pathology_links"):
        linkage_status = "linked"
    elif latest_biopsy.get("targets") or targeted_cores:
        linkage_status = "partial"
    elif _map_biopsy_strategy(latest_biopsy) == "systematic":
        linkage_status = "not_applicable"
    biopsy_strategy = _map_biopsy_strategy(latest_biopsy)
    biopsy_route = _normalized_text(
        latest_biopsy.get("biopsy_route")
        or field_values.get("planned_biopsy_route")
        or field_values.get("biopsy_route")
    )
    pattern4_pct = _safe_float(
        latest_biopsy.get("porcentaje_patron_4")
        or field_values.get("porcentaje_patron_4")
        or field_values.get("pattern4_pct")
    )
    cribriform_status = (
        "present"
        if _truthy(latest_biopsy.get("any_cribriform") or latest_biopsy.get("patron_cribiforme") or field_values.get("patron_cribiforme"))
        else "absent" if _normalized_text(latest_biopsy.get("patron_cribiforme") or field_values.get("patron_cribiforme")) else "unknown"
    )
    intraductal_status = (
        "present"
        if _truthy(latest_biopsy.get("any_intraductal") or latest_biopsy.get("carcinoma_intraductal") or field_values.get("carcinoma_intraductal"))
        else "absent" if _normalized_text(latest_biopsy.get("carcinoma_intraductal") or field_values.get("carcinoma_intraductal")) else "unknown"
    )
    persistent_suspicion_drivers: list[str] = []
    pirads_num = _safe_float(pirads)
    if pirads_num is not None and pirads_num >= 4:
        persistent_suspicion_drivers.append(f"PI-RADS {int(pirads_num)}")
    if psa_density is not None and psa_density >= 0.15:
        persistent_suspicion_drivers.append(f"PSAD {psa_density:.3f}")
    if _truthy(field_values.get("dre_suspicious")):
        persistent_suspicion_drivers.append("DRE sospechoso")
    if _truthy(field_values.get("persistent_lesion_signal")):
        persistent_suspicion_drivers.append("señal persistente de lesión")
    negative_biopsy_followup_status = ""
    if state == "post_negative_biopsy_followup" or (positive_cores == 0 and int(field_values.get("prior_biopsy_count") or 0) >= 1):
        rebiopsy_planned = bool(latest_biopsy_trigger or latest_diagnostic_plan) or _truthy(field_values.get("confirmatory_biopsy_planned"))
        if persistent_suspicion_drivers and rebiopsy_planned:
            negative_biopsy_followup_status = "rebiopsy_ready"
        elif persistent_suspicion_drivers:
            negative_biopsy_followup_status = "persistent_suspicion_reopen_workup"
        else:
            negative_biopsy_followup_status = "low_suspicion_surveillance"
    diagnosis_certainty = "incomplete"
    histology_confirmed = int(positive_cores or 0) > 0 or _safe_float(field_values.get("isup_grade")) is not None
    repeat_psa_required = (
        state == "diagnostic_workup"
        and index_psa_value is not None
        and 3 <= index_psa_value <= 10
        and not _truthy(field_values.get("dre_suspicious"))
        and not histology_confirmed
    )
    if repeat_psa_required:
        if repeat_psa_status == "missing":
            repeat_psa_status = "exception_documented" if repeat_psa_reason_not_done else "required_not_done"
        elif repeat_psa_status == "single_available":
            repeat_psa_status = "required_not_done"
    if histology_confirmed:
        diagnosis_certainty = "histology_confirmed"
    elif negative_biopsy_followup_status in {"persistent_suspicion_reopen_workup", "rebiopsy_ready"}:
        diagnosis_certainty = "persistent_suspicion_after_negative_biopsy"
    elif any(
        _normalized_text(value)
        for value in (index_psa_value, psa_density, pirads, field_values.get("dre_suspicious"))
    ):
        diagnosis_certainty = "provisional"
    return {
        "available": bool(psa_points or latest_mri or latest_biopsy or field_values),
        "index_psa_value": index_psa_value,
        "index_psa_date": index_psa_date,
        "repeat_psa_status": repeat_psa_status,
        "repeat_psa_date": repeat_psa_date,
        "repeat_psa_required": repeat_psa_required,
        "repeat_psa_reason_not_done": repeat_psa_reason_not_done,
        "dre_status": "sospechoso" if _truthy(field_values.get("dre_suspicious")) else "no sospechoso" if _normalized_text(field_values.get("dre_suspicious")) else "",
        "prostate_volume_ml": prostate_volume_ml,
        "psa_density": psa_density,
        "mpmri_status": "available" if latest_mri else "missing",
        "pirads_v21_score": pirads,
        "mpmri_date": _normalized_text(latest_mri.get("fact_date") or latest_mri.get("study_date")),
        "biopsy_route": biopsy_route,
        "biopsy_strategy": biopsy_strategy,
        "lesion_core_histology_linkage_status": linkage_status,
        "gleason_primary": latest_biopsy.get("gleason_primary") or field_values.get("gleason_primary"),
        "gleason_secondary": latest_biopsy.get("gleason_secondary") or field_values.get("gleason_secondary"),
        "isup_grade": latest_biopsy.get("highest_isup") or latest_biopsy.get("isup_grade") or field_values.get("isup_grade"),
        "pattern4_pct": pattern4_pct,
        "cribriform_status": cribriform_status,
        "intraductal_status": intraductal_status,
        "positive_cores": positive_cores,
        "total_cores": total_cores,
        "tumor_length_per_core_status": "documented" if tumor_length_documented else "not_documented" if latest_biopsy else "unknown",
        "negative_biopsy_followup_status": negative_biopsy_followup_status,
        "persistent_suspicion_drivers": persistent_suspicion_drivers,
        "diagnosis_certainty": diagnosis_certainty,
    }


def _build_staging_certainty_bundle(
    patient: dict[str, Any],
    field_values: dict[str, Any],
    diagnostic_certainty_bundle: dict[str, Any],
) -> dict[str, Any]:
    latest_psma = _latest_psma_study(patient)
    latest_conventional = _latest_conventional_staging_study(patient)
    latest_stage_study = latest_psma or latest_conventional or _latest_mpmri_fact(patient)
    clinical_local_stage = _coalesce_stage(
        field_values.get("clinical_tstage"),
        field_values.get("pathologic_tstage"),
        field_values.get("pathological_stage"),
    )
    nodal_stage = _coalesce_stage(
        field_values.get("nodal_status"),
        field_values.get("clinical_nstage"),
        field_values.get("pathologic_nstage"),
    )
    metastatic_stage = _coalesce_stage(
        latest_psma.get("psma_stage_after_psma"),
        field_values.get("m_substage_resolved"),
        field_values.get("clinical_mstage"),
        field_values.get("conventional_imaging_status"),
    )
    imaging_class = "none"
    if latest_psma and latest_conventional:
        imaging_class = "hybrid"
    elif latest_psma:
        imaging_class = "psma"
    elif latest_stage_study:
        imaging_class = "conventional"
    plan_changed = _truthy(
        latest_psma.get("psma_management_changed")
        or latest_stage_study.get("psma_management_changed")
        or field_values.get("psma_management_changed")
    )
    discrepancy_status = "none_detected"
    if _truthy(latest_psma.get("psma_upstaged_vs_conventional")):
        discrepancy_status = "psma_upstaged_vs_conventional"
    elif (
        diagnostic_certainty_bundle.get("negative_biopsy_followup_status") == "persistent_suspicion_reopen_workup"
        and _normalized_text(diagnostic_certainty_bundle.get("pirads_v21_score")) in {"4", "5"}
    ):
        discrepancy_status = "mri_histology_discrepancy"
    stage_certainty = "low"
    if clinical_local_stage and metastatic_stage and latest_stage_study:
        stage_certainty = "high" if imaging_class in {"psma", "hybrid"} or plan_changed is not None else "moderate"
    elif clinical_local_stage or metastatic_stage or latest_stage_study:
        stage_certainty = "moderate"
    supporting_studies = [
        {
            "study_type": item.get("study_type"),
            "study_date": item.get("study_date"),
        }
        for item in (latest_psma, latest_conventional)
        if item
    ]
    return {
        "available": bool(clinical_local_stage or metastatic_stage or latest_stage_study),
        "clinical_local_stage": clinical_local_stage,
        "nodal_stage": nodal_stage,
        "metastatic_stage": metastatic_stage,
        "staging_method_primary": _normalized_text(latest_stage_study.get("study_type")),
        "staging_image_date": _normalized_text(latest_stage_study.get("study_date") or latest_stage_study.get("fact_date")),
        "imaging_class": imaging_class,
        "plan_changed_by_imaging": plan_changed,
        "stage_certainty": stage_certainty,
        "imaging_pathology_discrepancy_status": discrepancy_status,
        "supporting_studies": supporting_studies,
    }


def _build_minimum_decisive_dataset_bundle(
    state: str,
    decision_input_requirements: dict[str, Any],
    field_values: dict[str, Any],
    diagnostic_certainty_bundle: dict[str, Any],
    *,
    localized_nccn_group: str = "",
    localized_as_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset_key = state
    required_fields: list[str] = []
    supportive_fields: list[str] = []
    if state == "diagnostic_workup":
        dataset_key = "diagnostic_workup"
        required_fields = ["psa", "psad", "pirads_score", "dre_suspicious"]
        if diagnostic_certainty_bundle.get("repeat_psa_required"):
            required_fields.extend(["repeat_psa_value", "repeat_psa_date"])
        supportive_fields = ["prostate_volume_ml", "planned_biopsy_type", "planned_biopsy_route"]
    elif state == "localized_initial":
        dataset_key = "localized_initial"
        required_fields = LOCALIZED_MINIMUM_DECISIVE_FIELDS
        supportive_fields = LOCALIZED_FUNCTIONAL_FIELDS
        if should_require_localized_modality_dataset(
            field_values,
            nccn_group=localized_nccn_group,
            as_position=localized_as_position,
        ):
            required_fields = _dedupe(required_fields + LOCALIZED_MODALITY_FIELDS)
            supportive_fields = _dedupe(supportive_fields + ["baseline_obstruction", "brachy_feasibility", "plnd_likely_indicated"])
    elif state == "post_prostatectomy":
        dataset_key = "post_prostatectomy"
        required_fields = ["psa_postop", "pathologic_stage", "psadt_months", "salvage_local_feasible"]
        supportive_fields = ["psma_pet_done", "decipher_risk"]
    elif state == "recurrence_bcr":
        dataset_key = "recurrence_bcr"
        post_rp_salvage_profile = build_post_rp_salvage_intensification_profile(field_values)
        required_fields = ["psa", "psadt_months", "salvage_local_feasible"]
        supportive_fields = ["psma_rads_score", "psma_uptake_pattern"]
        if str(post_rp_salvage_profile.get("psma_restaging_role") or "") == "urgent_companion":
            supportive_fields = _dedupe(supportive_fields + ["psma_pet_done"])
        else:
            required_fields.append("psma_pet_done")
    elif state == "post_radiotherapy_or_local_salvage":
        dataset_key = "post_radiotherapy_or_local_salvage"
        required_fields = ["psa_current", "psa_nadir", "phoenix_delta", "biopsy_proven_local_recurrence", "psma_pet_done"]
        supportive_fields = ["local_recurrence_site", "prostate_volume", "urinary_burden", "bowel_burden"]
    elif state in {
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
    }:
        dataset_key = "mHSPC"
        required_fields = MHSPC_MINIMUM_DECISIVE_FIELDS
        supportive_fields = ["metachronous_metastasis", "primary_local_treatment_done", "psma_pet_done"]
    elif state in {"adt_progression_verification", "m0_crpc", "m1_crpc"}:
        dataset_key = "CRPC"
        required_fields = CRPC_MINIMUM_DECISIVE_FIELDS
        supportive_fields = CRPC_RESTAGING_FIELDS
    ready_fields = [field for field in required_fields if _blocking_input_satisfied(field, field_values)]
    if diagnostic_certainty_bundle.get("repeat_psa_required") and str(diagnostic_certainty_bundle.get("repeat_psa_status") or "") in {"repeated", "exception_documented"}:
        for field in ("repeat_psa_value", "repeat_psa_date"):
            if field in required_fields and field not in ready_fields:
                ready_fields.append(field)
    missing_required = [field for field in required_fields if field not in ready_fields]
    missing_supportive = [field for field in supportive_fields if not _blocking_input_satisfied(field, field_values)]
    hard_missing = [
        field for field in missing_required
        if field in set(decision_input_requirements.get("hard_blocking_inputs") or [])
    ]
    decision_missing = [
        field for field in missing_required
        if field not in hard_missing
    ]
    dataset_status = "clear"
    if hard_missing:
        dataset_status = "hard_stop"
    elif decision_missing or missing_supportive or str(decision_input_requirements.get("recommendation_block_status") or "") == "provisional":
        dataset_status = "provisional"
    completeness_denominator = len(required_fields) or 1
    completeness_pct = round((len(ready_fields) / completeness_denominator) * 100, 1)
    return {
        "available": bool(required_fields),
        "dataset_key": dataset_key,
        "dataset_status": dataset_status,
        "required_fields": required_fields,
        "supportive_fields": supportive_fields,
        "ready_fields": ready_fields,
        "missing_required_fields": missing_required,
        "missing_hard_fields": hard_missing,
        "missing_decision_fields": decision_missing,
        "missing_supportive_fields": missing_supportive,
        "dataset_completeness_pct": completeness_pct,
        "seam_priority": "high" if state in POSTLOCAL_PRIORITY_STATES else "standard",
        "dataset_rationale": (
            "El caso no debe consolidarse sin dataset mínimo decisional por estado."
            if required_fields
            else "Sin dataset mínimo específico para este estado."
        ),
    }


def _build_therapeutic_window_bundle(
    patient: dict[str, Any],
    state: str,
    field_values: dict[str, Any],
    pro_decision_bundle: dict[str, Any],
    decision_input_requirements: dict[str, Any],
    diagnostic_certainty_bundle: dict[str, Any],
    *,
    localized_nccn_group: str = "",
    localized_as_position: dict[str, Any] | None = None,
    localized_modality_fitness_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    latest_adherence = dict(patient.get("adherence_tracking_bundle") or {})
    pirads = _safe_float(field_values.get("pirads_score") or field_values.get("prior_mpmri_pirads_score"))
    psad = _safe_float(field_values.get("psad"))
    if state in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        diagnostic_missing = [
            field for field in ("pirads_score", "psad", "planned_biopsy_route")
            if not _blocking_input_satisfied(field, field_values)
        ]
        if state == "diagnostic_workup" and diagnostic_certainty_bundle.get("repeat_psa_required") and str(diagnostic_certainty_bundle.get("repeat_psa_status") or "") not in {"repeated", "exception_documented"}:
            diagnostic_missing.extend(
                [
                    field
                    for field in ("repeat_psa_value", "repeat_psa_date")
                    if not _blocking_input_satisfied(field, field_values)
                ]
            )
        suspicion_relevant = (
            (pirads is not None and pirads >= 4)
            or (psad is not None and psad >= 0.15)
            or _truthy(field_values.get("dre_suspicious"))
        )
        if diagnostic_missing or suspicion_relevant:
            windows.append(
                {
                    "window_key": "diagnostic_mri_biopsy_window",
                    "window_status": "open" if suspicion_relevant else "narrowing",
                    "window_reason": "MRI/biopsia pendiente en sospecha clínicamente relevante.",
                    "decision_supported": "diagnostic_confirmation",
                    "required_inputs": diagnostic_missing or ["pirads_score", "psad", "planned_biopsy_route"],
                    "time_sensitivity": "high" if suspicion_relevant else "moderate",
                    "opportunity_loss_risk": "possible" if diagnostic_missing else "none",
                    "opportunity_loss_reason": "Sin MRI/PSAD/plan de biopsia puede retrasarse confirmación diagnóstica.",
                }
            )
    if state == "localized_initial" and should_require_localized_modality_dataset(
        field_values,
        nccn_group=localized_nccn_group,
        as_position=localized_as_position,
    ):
        missing_modality_fields = [
            field for field in LOCALIZED_MODALITY_FIELDS
            if not _blocking_input_satisfied(field, field_values)
        ]
        if missing_modality_fields:
            windows.append(
                {
                    "window_key": "localized_modality_closure_window",
                    "window_status": "narrowing" if diagnostic_certainty_bundle.get("diagnosis_certainty") in {"histology_confirmed", "provisional"} else "open",
                    "window_reason": "El diagnóstico está lo bastante cerrado, pero la decisión local todavía no tiene baseline funcional, factibilidad o prioridades completas.",
                    "decision_supported": "local_therapy_selection",
                    "required_inputs": missing_modality_fields,
                    "time_sensitivity": "moderate",
                    "opportunity_loss_risk": "possible",
                    "opportunity_loss_reason": "Puede sobrepriorizarse una modalidad local por grupo de riesgo y no por aptitud real del paciente.",
                    "dominant_modality": str((localized_modality_fitness_bundle or {}).get("dominant_modality") or ""),
                }
            )
    if state == "active_surveillance":
        confirmatory_due = any(
            item.get("completion_status") in {"missed", "completed_late"}
            and "confirm" in str(item.get("expected_action") or "").lower()
            for item in list((latest_adherence.get("items") or []) + (patient.get("scheduled_events") or []))
        )
        if confirmatory_due:
            windows.append(
                {
                    "window_key": "active_surveillance_confirmatory_biopsy",
                    "window_status": "overdue",
                    "window_reason": "La biopsia confirmatoria de vigilancia activa está vencida.",
                    "decision_supported": "as_reclassification",
                    "required_inputs": ["confirmatory_biopsy_done"],
                    "time_sensitivity": "high",
                    "opportunity_loss_risk": "confirmed",
                    "opportunity_loss_reason": "La omisión puede retrasar reclasificación o salida de vigilancia activa.",
                }
            )
    if state in {"post_prostatectomy", "recurrence_bcr"}:
        salvage_status = _normalized_text(latest_signal_snapshot.get("salvage_window_status")).lower()
        salvage_feasible = _yes_no_unknown(field_values.get("salvage_local_feasible"))
        latest_psa = _safe_float(field_values.get("psa") or field_values.get("psa_postop") or field_values.get("psa_current"))
        post_rp_salvage_profile = build_post_rp_salvage_intensification_profile(field_values)
        urgent_psma_companion = str(post_rp_salvage_profile.get("psma_restaging_role") or "") == "urgent_companion"
        if not salvage_status:
            if salvage_feasible == "yes":
                salvage_status = "open" if latest_psa is not None and latest_psa < 0.5 else "narrowing"
            elif salvage_feasible == "no":
                salvage_status = "redirected"
            else:
                salvage_status = "narrowing"
        windows.append(
            {
                "window_key": "post_rp_salvage_window",
                "window_status": salvage_status if salvage_status in {"open", "narrowing", "redirected", "closed"} else "open",
                "window_reason": "El valor oncológico post-RP/BCR depende de caracterización temprana y salvage oportuno.",
                "decision_supported": "salvage_decision",
                "required_inputs": _dedupe(
                    [
                        field
                        for field in ("psadt_months", "salvage_local_feasible")
                        if not _blocking_input_satisfied(field, field_values)
                    ]
                    + (
                        []
                        if urgent_psma_companion
                        else [
                            field
                            for field in ("psma_pet_done",)
                            if not _blocking_input_satisfied(field, field_values)
                        ]
                    )
                ),
                "time_sensitivity": "high",
                "opportunity_loss_risk": "confirmed" if salvage_status == "closed" else "possible" if salvage_status in {"narrowing", "redirected"} else "none",
                "opportunity_loss_reason": "Una ventana de salvage tardía puede traducirse en pérdida de oportunidad curativa.",
            }
        )
    if state == "post_radiotherapy_or_local_salvage":
        legacy_status = _normalized_text(latest_signal_snapshot.get("post_rt_salvage_window_status")).lower()
        mapped_status = {
            "local_salvage_candidate": "open",
            "mdt_candidate": "open",
            "systemic_redirect": "redirected",
        }.get(legacy_status, "narrowing" if _blocking_input_satisfied("phoenix_delta", field_values) else "open")
        windows.append(
            {
                "window_key": "post_rt_salvage_window",
                "window_status": mapped_status,
                "window_reason": "Post-RT debe distinguir rebote, fallo real, recaída local y redirección sistémica.",
                "decision_supported": "post_rt_local_salvage",
                "required_inputs": _dedupe(
                    [
                        field
                        for field in ("phoenix_delta", "biopsy_proven_local_recurrence", "psma_pet_done")
                        if not _blocking_input_satisfied(field, field_values)
                    ]
                ),
                "time_sensitivity": "high",
                "opportunity_loss_risk": "possible" if mapped_status in {"narrowing", "redirected"} else "none",
                "opportunity_loss_reason": "No separar rebote de recaída real puede cerrar o desviar salvage inapropiadamente.",
                "legacy_window_status": legacy_status,
            }
        )
    # NCCN PROS-H v5.2026 / EAU 2026 §6.10.2: el workflow HRR germinal+somático
    # es requerido en todo espectro avanzado — mHSPC (cualquier volumen), la
    # transición de mHSPC a mCRPC (adt_progression_verification) y toda la
    # enfermedad castración resistente (m0_crpc + m1_crpc). Testing temprano
    # habilita elegibilidad PARP (PROfound, PROpel, MAGNITUDE, TALAPRO-2) y
    # consejería genética familiar cuando aparece patogénica germinal.
    if state in {
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "adt_progression_verification",
        "m0_crpc",
        "m1_crpc",
    } and not _blocking_input_satisfied("hrr_status", field_values):
        windows.append(
            {
                "window_key": "precision_hrr_testing_window",
                "window_status": "open",
                "window_reason": "Falta workflow HRR/germinal-somático en enfermedad avanzada (NCCN PROS-H v5.2026).",
                "decision_supported": "precision_pathway",
                "required_inputs": ["hrr_status", "biomarker_source", "molecular_assay_date"],
                "time_sensitivity": "moderate",
                "opportunity_loss_risk": "possible",
                "opportunity_loss_reason": "Sin HRR testing se pierde elegibilidad de precisión (PARP) y comparabilidad registral.",
            }
        )
    post_rp_salvage_profile = (
        build_post_rp_salvage_intensification_profile(field_values)
        if state == "recurrence_bcr"
        else {}
    )
    urgent_psma_companion = str(post_rp_salvage_profile.get("psma_restaging_role") or "") == "urgent_companion"
    # NCCN PROS-9 / PROS-11: PSMA-PET también debe considerarse en la transición
    # mHSPC→mCRPC (adt_progression_verification) y en nmCRPC (m0_crpc) porque
    # puede detectar enfermedad metastásica oculta y redirigir el carril (cambio
    # de intención a mCRPC) antes de iniciar ARPI frente a progresión CRPC.
    if (
        state in {
            "recurrence_bcr",
            "post_radiotherapy_or_local_salvage",
            "adt_progression_verification",
            "m0_crpc",
            "m1_crpc",
        }
        and not _blocking_input_satisfied("psma_pet_done", field_values)
        and not (state == "recurrence_bcr" and urgent_psma_companion)
    ):
        windows.append(
            {
                "window_key": "psma_eligibility_window",
                "window_status": "open",
                "window_reason": "PSMA elegible no realizado en un escenario donde puede cambiar conducta (NCCN PROS-9/PROS-11).",
                "decision_supported": "restaging",
                "required_inputs": ["psma_pet_done"],
                "time_sensitivity": "moderate",
                "opportunity_loss_risk": "possible",
                "opportunity_loss_reason": "La ausencia de PSMA puede subóptimamente mezclar ruta local y sistémica y retrasar la detección de M1 oculto.",
            }
        )
    if _blocking_input_satisfied("current_adt_context", field_values) and (
        not _blocking_input_satisfied("dxa_baseline_done", field_values)
        or not _blocking_input_satisfied("cv_risk_documented", field_values)
    ):
        windows.append(
            {
                "window_key": "adt_bone_cardiometabolic_bundle",
                "window_status": "open",
                "window_reason": "ADT activa sin bundle óseo/cardiometabólico completo.",
                "decision_supported": "supportive_monitoring",
                "required_inputs": [
                    field
                    for field in ("dxa_baseline_done", "cv_risk_documented")
                    if not _blocking_input_satisfied(field, field_values)
                ],
                "time_sensitivity": "moderate",
                "opportunity_loss_risk": "possible",
                "opportunity_loss_reason": "La omisión de prevención ósea/cardiometabólica reduce impacto clínico y seguridad longitudinal.",
            }
        )
    if str(pro_decision_bundle.get("pro_decision_status") or "") in {"decision_modifier", "escalation_trigger"}:
        windows.append(
            {
                "window_key": "critical_pro_symptom_window",
                "window_status": "open",
                "window_reason": "PROs críticos o carga sintomática relevante requieren ajuste visible.",
                "decision_supported": "shared_decision",
                "required_inputs": list(pro_decision_bundle.get("missing_inputs") or []),
                "time_sensitivity": "high",
                "opportunity_loss_risk": "possible",
                "opportunity_loss_reason": "Sin actuar sobre PROs críticos puede mantenerse una intensidad terapéutica desalineada.",
            }
        )
    if state in {"adt_progression_verification", "m0_crpc", "m1_crpc"}:
        metastatic_state_context = resolve_metastatic_state_context(field_values)
        metastatic_stage_resolved = str(metastatic_state_context.get("metastatic_stage_resolved") or "M0")
        crpc_missing = [
            field
            for field in ("testosterone", "conventional_imaging_status", "psma_pet_done")
            if not _blocking_input_satisfied(field, field_values)
        ]
        if metastatic_stage_resolved != "M0":
            progression_required = [
                "testosterone",
                "testosterone_date",
                "current_adt_context",
                "progression_pattern",
                "psa",
                "conventional_imaging_status",
                "conventional_imaging_modality",
                "conventional_imaging_date",
            ]
            progression_missing = [
                field for field in progression_required if not _blocking_input_satisfied(field, field_values)
            ]
            windows.append(
                {
                    "window_key": "progression_verification_closure_window",
                    "window_status": "narrowing" if progression_missing else "open",
                    "window_reason": "M1 ya documentado; ahora debe cerrarse castración, patrón de progresión y restadificación suficiente para redirigir el curso clínico.",
                    "decision_supported": "crpc_verification",
                    "required_inputs": progression_missing or progression_required,
                    "time_sensitivity": "high",
                    "opportunity_loss_risk": "possible" if progression_missing else "none",
                    "opportunity_loss_reason": "Sin cierre de castración/progresión se puede mantener un carril CRPC incorrecto o retrasar redirección a m1CRPC o mHSPC.",
                    "what_state_will_be_reached_if_closed": "m1_crpc",
                    "what_redirects_the_case_if_not_crpc": "Redirigir a mHSPC metastásico si no se confirma castración resistente.",
                }
            )
        elif crpc_missing or state == "adt_progression_verification":
            windows.append(
                {
                    "window_key": "crpc_verification_window",
                    "window_status": "narrowing" if crpc_missing else "open",
                    "window_reason": "La transición a CRPC requiere castración documentada y restaging suficiente.",
                    "decision_supported": "crpc_verification",
                    "required_inputs": crpc_missing or ["testosterone", "conventional_imaging_status"],
                    "time_sensitivity": "high",
                    "opportunity_loss_risk": "possible" if crpc_missing else "none",
                    "opportunity_loss_reason": "Sin castración bioquímica y reestadificación adecuada puede etiquetarse mal la progresión.",
                }
            )
    highest_risk = next(
        (
            window
            for window in windows
            if window.get("opportunity_loss_risk") == "confirmed"
        ),
        windows[0] if windows else {},
    )
    return {
        "available": bool(windows),
        "windows": windows,
        "active_window_keys": [window.get("window_key") for window in windows],
        "highest_risk_window": highest_risk,
        "opportunity_loss_risk_summary": highest_risk.get("opportunity_loss_risk") or "none",
    }


def _build_precision_workflow_bundle(
    patient: dict[str, Any],
    state: str,
    field_values: dict[str, Any],
    ctdna_refinement_bundle: dict[str, Any],
) -> dict[str, Any]:
    latest_genomic = _latest_genomic_report(patient)
    advanced_state = _is_advanced_state(state) or state in {
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
    }
    germline_indicated = advanced_state or _truthy(field_values.get("family_history_positive")) or _truthy(field_values.get("germline_risk_mutation"))
    germline_status_raw = _normalized_text(field_values.get("germline_status") or latest_genomic.get("known_mutation"))
    somatic_done = bool(latest_genomic) or _truthy(field_values.get("genomic_test_done"))
    hrr_positive = _normalized_text(field_values.get("hrr_status") or latest_genomic.get("hrr_overall")).lower() in {"positivo", "positive", "pathogenic", "mutado", "mutated"}
    brca2_positive = _normalized_text(field_values.get("brca2_status") or latest_genomic.get("brca2_status")).lower() in {"positivo", "positive", "pathogenic", "mutado", "mutated"}
    actionable = hrr_positive or brca2_positive or _normalized_text(field_values.get("msi_status") or latest_genomic.get("msi_status")).lower() in {"msi-h", "positive"}
    if not germline_indicated:
        germline_workflow_status = "not_indicated"
    elif actionable or germline_status_raw:
        germline_workflow_status = "actionable" if actionable else "result_available"
    elif _truthy(field_values.get("germline_ordered")):
        germline_workflow_status = "ordered_pending"
    else:
        germline_workflow_status = "indicated_not_ordered"
    if not advanced_state and not somatic_done and not actionable:
        somatic_workflow_status = "not_indicated"
    elif actionable:
        somatic_workflow_status = "actionable"
    elif somatic_done:
        somatic_workflow_status = "result_available"
    elif _truthy(field_values.get("somatic_ordered")):
        somatic_workflow_status = "ordered_pending"
    else:
        somatic_workflow_status = "indicated_not_ordered" if advanced_state else "not_indicated"
    altered_genes = _dedupe(
        [
            gene.upper()
            for gene, status in {
                "BRCA1": latest_genomic.get("brca1_status"),
                "BRCA2": latest_genomic.get("brca2_status") or field_values.get("brca2_status"),
                "ATM": latest_genomic.get("atm_status"),
                "CHEK2": latest_genomic.get("chek2_status"),
                "PALB2": latest_genomic.get("palb2_status"),
                "CDK12": latest_genomic.get("cdk12_status"),
            }.items()
            if _normalized_text(status)
            and _normalized_text(status).lower() not in {"negativo", "negative", "wild-type", "wt", "desconocido", "unknown", "no testado"}
        ]
    )
    alteration_type = _dedupe([_normalized_text(field_values.get("hrr_status")), _normalized_text(germline_status_raw)])
    therapeutic_impact = []
    if actionable:
        therapeutic_impact.append("precision_therapy")
    if altered_genes:
        therapeutic_impact.append("genetic_counseling" if any(gene in {"BRCA1", "BRCA2", "PALB2", "ATM"} for gene in altered_genes) else "molecular_context")
    if str(ctdna_refinement_bundle.get("decision_role") or "") in {"monitoring_refiner", "escalation_trigger"}:
        therapeutic_impact.append("ctdna_monitoring_refiner")
    return {
        "available": bool(germline_indicated or somatic_done or altered_genes or ctdna_refinement_bundle.get("available")),
        "germline_workflow_status": germline_workflow_status,
        "somatic_workflow_status": somatic_workflow_status,
        "altered_genes": altered_genes,
        "alteration_type": alteration_type,
        "biomarker_source": _normalized_text(field_values.get("biomarker_source") or field_values.get("molecular_assay_source")),
        "molecular_assay_date": _normalized_text(field_values.get("molecular_assay_date") or latest_genomic.get("test_date")),
        "therapeutic_impact": therapeutic_impact,
        "genetic_counseling_needed": any(gene in {"BRCA1", "BRCA2", "PALB2", "ATM"} for gene in altered_genes),
        "precision_eligibility_impact": "parp_candidate" if actionable else "pending_or_not_actionable",
    }


def _build_registry_core_bundle(
    patient: dict[str, Any],
    state: str,
    staging_certainty_bundle: dict[str, Any],
) -> dict[str, Any]:
    identity = dict(patient.get("identity") or {})
    treatments = list(patient.get("treatments") or [])
    adjudication_snapshot = dict(patient.get("latest_adjudication_snapshot") or {})
    outcome_summary = dict(adjudication_snapshot.get("outcome_events_summary") or {})
    first_curative_therapy = next(
        (
            treatment.get("drug_scheme")
            or treatment.get("therapy_name")
            or treatment.get("treatment_name")
            for treatment in treatments
            if _normalized_text(treatment.get("drug_scheme") or treatment.get("therapy_name") or treatment.get("treatment_name"))
        ),
        "",
    )
    denominator_gaps = [
        field
        for field, value in {
            "diagnosis_date": identity.get("diagnosis_date"),
            "stage_at_diagnosis": staging_certainty_bundle.get("clinical_local_stage") or staging_certainty_bundle.get("metastatic_stage"),
            "vital_status": identity.get("vital_status"),
            "last_contact_date": identity.get("last_contact_date"),
        }.items()
        if not _normalized_text(value)
    ]
    metastatic_progression_recorded = bool(
        outcome_summary.get("radiographic_progression")
        or staging_certainty_bundle.get("metastatic_stage")
        or str(state).startswith("mcspc")
        or state == "m1_crpc"
    )
    crpc_progression_recorded = bool(
        outcome_summary.get("crpc_progression")
        or state in {"adt_progression_verification", "m0_crpc", "m1_crpc"}
    )
    return {
        "available": True,
        "incident_case": bool(_normalized_text(identity.get("diagnosis_date"))),
        "diagnosis_date": _normalized_text(identity.get("diagnosis_date")),
        "stage_at_diagnosis": _coalesce_stage(
            identity.get("clinical_stage_group"),
            staging_certainty_bundle.get("clinical_local_stage"),
            staging_certainty_bundle.get("metastatic_stage"),
        ),
        "first_curative_therapy": first_curative_therapy,
        "active_surveillance_used": bool(patient.get("active_surveillance_protocol") or patient.get("localized_surveillance_bundle")),
        "biochemical_recurrence_recorded": bool(patient.get("bcr")),
        "metastatic_progression_recorded": metastatic_progression_recorded,
        "crpc_progression_recorded": crpc_progression_recorded,
        "vital_status": _normalized_text(identity.get("vital_status") or "alive"),
        "last_contact_date": _normalized_text(identity.get("last_contact_date")),
        "last_contact_type": _normalized_text(identity.get("last_contact_status")),
        "denominator_ready": not denominator_gaps,
        "denominator_gaps": denominator_gaps,
    }


def _build_endpoint_adjudication_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    adjudication_snapshot = dict(patient.get("latest_adjudication_snapshot") or {})
    pending = list(adjudication_snapshot.get("pending_adjudications") or [])
    current_response = dict(adjudication_snapshot.get("current_response_state") or {})
    last_event = dict(adjudication_snapshot.get("last_adjudicated_event") or {})
    summary = dict(adjudication_snapshot.get("outcome_events_summary") or {})
    certainty_level = "limited"
    if last_event and not pending:
        certainty_level = "high"
    elif last_event or summary:
        certainty_level = "mixed"
    return {
        "available": bool(adjudication_snapshot),
        "current_course_status": _normalized_text(adjudication_snapshot.get("current_course_status")),
        "current_response_state": current_response,
        "last_adjudicated_event": last_event,
        "pending_adjudications": pending,
        "outcome_events_summary": summary,
        "certainty_level": certainty_level,
    }


def _build_data_certainty_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    verified_facts = list(patient.get("verified_document_facts") or [])
    provenance = list(patient.get("data_provenance") or [])
    pending_tasks = list(patient.get("document_verification_tasks") or [])
    verified_fields = {item.get("field_name") for item in verified_facts if item.get("field_name")}
    documented_fields = {
        item.get("field_name")
        for item in provenance
        if item.get("field_name") and item.get("source_type") != "inferencia longitudinal"
    }
    inferred_fields = {
        item.get("field_name")
        for item in provenance
        if item.get("field_name") and item.get("source_type") == "inferencia longitudinal"
    }
    critical_field_sources = []
    for field_name in ("psa", "clinical_tstage", "isup_grade", "hrr_status", "psma_rads_score", "vital_status"):
        verified = next((item for item in verified_facts if item.get("field_name") == field_name), None)
        documented = next((item for item in provenance if item.get("field_name") == field_name), None)
        source = verified or documented
        if not source:
            continue
        critical_field_sources.append(
            {
                "field_name": field_name,
                "source_type": source.get("source_type") or ("verified_document" if verified else ""),
                "verified_by": source.get("verified_by") or "",
                "documented_vs_inferred": "documented" if field_name in documented_fields or field_name in verified_fields else "inferred",
            }
        )
    if len(verified_fields) >= 4:
        reliability_label = "alta"
    elif verified_fields or documented_fields:
        reliability_label = "intermedia"
    else:
        reliability_label = "baja"
    return {
        "available": bool(verified_facts or provenance or pending_tasks),
        "verified_fact_count": len(verified_facts),
        "documented_field_count": len(documented_fields),
        "inferred_field_count": len(inferred_fields),
        "pending_document_tasks": len(pending_tasks),
        "critical_field_sources": critical_field_sources,
        "reliability_label": reliability_label,
        "traceability_ready": bool(verified_fields or documented_fields),
    }


def apply_governance_to_next_best_action(
    next_best_action: dict[str, Any],
    governance_bundle: dict[str, Any],
) -> dict[str, Any]:
    action = dict(next_best_action or {})
    block_status = str(governance_bundle.get("recommendation_block_status") or "clear")
    block_reason = str(governance_bundle.get("recommendation_block_reason") or "")
    blocking_bundle = dict(governance_bundle.get("decision_blocking_bundle") or {})
    pro_bundle = dict(governance_bundle.get("pro_decision_bundle") or {})
    window_worklist_bundle = dict(governance_bundle.get("window_worklist_bundle") or {})
    top_window = dict(window_worklist_bundle.get("top_active_window") or {})
    top_window_risk = str(top_window.get("opportunity_loss_risk") or "none")
    top_window_title = ""
    top_window_actions = [
        str(item.get("label") or "").strip()
        for item in list(top_window.get("closure_tasks") or [])
        if str(item.get("label") or "").strip()
    ]
    if top_window and top_window_risk != "none":
        top_window_title = str(top_window.get("what_closes_this_window") or "").strip()
    if block_status == "hard_stop":
        capture_block = dict(blocking_bundle.get("capture_block") or {})
        hard_stop_title = (
            top_window_title
            or (top_window_actions[0] if top_window_actions else "")
            or capture_block.get("title")
            or "Completar datos críticos antes de cerrar recomendación"
        )
        action.update(
            {
                "title": hard_stop_title,
                "recommendation_family": "window_closure" if (top_window_title or top_window_actions) else "governance_block",
                "rationale": " ".join(
                    item
                    for item in [
                        top_window.get("why_this_matters_now") if top_window else "",
                        block_reason,
                    ]
                    if item
                ).strip(),
                "immediate_actions": _dedupe(
                    top_window_actions
                    + list(action.get("immediate_actions") or [])
                    + [capture_block.get("summary") or block_reason]
                ),
                "data_that_could_change_course": list(blocking_bundle.get("hard_blocking_inputs") or []),
                "governance_status": block_status,
                "top_active_window": top_window,
            }
        )
        return action
    if block_status == "provisional":
        action["rationale"] = f"{action.get('rationale') or ''} {block_reason}".strip()
        action["governance_status"] = block_status
        action["data_that_could_change_course"] = _dedupe(
            list(action.get("data_that_could_change_course") or [])
            + list(blocking_bundle.get("decision_blocking_inputs") or [])
        )
    if top_window and top_window_risk != "none":
        action["title"] = top_window_title or action.get("title") or "Cerrar ventana terapéutica prioritaria"
        action["recommendation_family"] = "window_closure"
        action["rationale"] = " ".join(
            item
            for item in [
                top_window.get("why_this_matters_now"),
                action.get("rationale") or "",
            ]
            if item
        ).strip()
        action["immediate_actions"] = _dedupe(top_window_actions + list(action.get("immediate_actions") or []))
        action["data_that_could_change_course"] = _dedupe(
            list(action.get("data_that_could_change_course") or [])
            + list(top_window.get("missing_decisive_fields") or [])
        )
        action["top_active_window"] = top_window
    if str(pro_bundle.get("pro_decision_status") or "") in {"decision_modifier", "escalation_trigger"}:
        action["rationale"] = (
            f"{action.get('rationale') or ''} PROs: "
            + "; ".join(list(pro_bundle.get("pro_decision_reasons") or [])[:2])
        ).strip()
        action["immediate_actions"] = _dedupe(
            list(action.get("immediate_actions") or [])
            + ([pro_bundle.get("recommended_course_modifier")] if pro_bundle.get("recommended_course_modifier") else [])
        )
    return action


def build_clinical_decision_governance_bundle(
    patient: dict[str, Any],
    *,
    state: str = "",
    management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
    transition_proposals: list[dict[str, Any]] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
    staging_adjudication_bundle: dict[str, Any] | None = None,
    supportive_care_toxicity_readiness_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or (latest_assessment or {}).get("state") or (patient.get("prior_history") or {}).get("current_state") or "diagnostic_workup"
    management_track = management_track or patient.get("schedule_management_track") or ""
    latest_assessment = latest_assessment or patient.get("latest_assessment") or {}
    next_best_action = dict(next_best_action or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    care_intent_contract = dict(care_intent_contract or {})
    clinical_fact_bundle = dict(clinical_fact_bundle or {})
    staging_adjudication_bundle = dict(staging_adjudication_bundle or {})
    supportive_care_toxicity_readiness_bundle = dict(
        supportive_care_toxicity_readiness_bundle or {}
    )
    decision_input_requirements = merge_staging_adjudication_into_requirements(
        decision_input_requirements,
        staging_adjudication_bundle,
    )
    field_values = _decision_field_values(patient)
    result_snapshot = dict(latest_assessment.get("result_snapshot") or {})
    localized_nccn_group = str(
        ((result_snapshot.get("nccn_primary") or {}).get("risk_group"))
        or field_values.get("clinical_risk_group")
        or field_values.get("risk_group")
        or ""
    )
    localized_as_position = dict(result_snapshot.get("active_surveillance_position") or {})
    if state == "localized_initial" and not localized_as_position:
        localized_as_position = active_surveillance_position(field_values, localized_nccn_group)
    existing_priority_profile = dict(result_snapshot.get("patient_priority_profile") or {})
    patient_priority_profile = {
        "available": bool((existing_priority_profile.get("priorities") or []) or parse_patient_priority_profile(field_values.get("patient_priority_profile"))),
        "priorities": list(existing_priority_profile.get("priorities") or parse_patient_priority_profile(field_values.get("patient_priority_profile"))),
    }
    localized_modality_fitness_bundle = (
        dict(result_snapshot.get("localized_modality_fitness_bundle") or {})
        if state == "localized_initial"
        else {}
    )
    if state == "localized_initial" and not localized_modality_fitness_bundle:
        localized_modality_fitness_bundle = build_localized_modality_fitness_bundle(
            field_values,
            nccn_group=localized_nccn_group,
            as_position=localized_as_position,
        )
    localized_tradeoff_bundle = (
        dict(result_snapshot.get("localized_tradeoff_bundle") or {})
        if state == "localized_initial"
        else {}
    )
    if state == "localized_initial" and not localized_tradeoff_bundle:
        localized_tradeoff_bundle = build_localized_tradeoff_bundle(
            field_values,
            nccn_group=localized_nccn_group,
            modality_bundle=localized_modality_fitness_bundle,
            as_position=localized_as_position,
        )
    radical_prostatectomy_candidacy_profile = (
        dict(result_snapshot.get("radical_prostatectomy_candidacy_profile") or {})
        if state == "localized_initial"
        else {}
    )
    if state == "localized_initial" and not radical_prostatectomy_candidacy_profile:
        radical_prostatectomy_candidacy_profile = build_radical_prostatectomy_candidacy_profile(
            field_values,
            nccn_group=localized_nccn_group,
        )
    localized_survival_context_bundle = (
        dict(result_snapshot.get("localized_survival_context_bundle") or {})
        if state == "localized_initial"
        else {}
    )
    if state == "localized_initial" and not localized_survival_context_bundle:
        localized_survival_context_bundle = build_localized_survival_context_bundle(field_values)
    active_surveillance_monitoring_profile = (
        dict(result_snapshot.get("active_surveillance_monitoring_profile") or {})
        if state == "localized_initial"
        else {}
    )
    if state == "localized_initial" and not active_surveillance_monitoring_profile:
        active_surveillance_monitoring_profile = build_active_surveillance_monitoring_profile(
            field_values,
            as_position=localized_as_position,
        )
    decision_blocking_bundle, block_status, block_reason, allowed_actions = _build_recommendation_blocking_bundle(
        decision_input_requirements
    )
    adjudication_release_status = str(
        staging_adjudication_bundle.get("adjudication_release_status") or ""
    ).strip()
    if adjudication_release_status == "blocked_pending_adjudication":
        block_status = "hard_stop"
        block_reason = (
            "La recomendación queda bloqueada hasta adjudicar la discordancia o el cambio de contexto clínico vigente."
        )
        allowed_actions = [
            "adjudicacion_clinica",
            "captura_dirigida",
            "reestadificacion",
            "tumor_board",
        ]
    elif adjudication_release_status == "review_needed" and block_status != "hard_stop":
        block_status = "provisional"
        block_reason = (
            "La recomendación requiere adjudicación clínica antes de sostenerse de forma definitiva."
        )
        allowed_actions = [
            "adjudicacion_clinica",
            "captura_dirigida",
            "monitorizacion_temporal",
        ]

    supportive_readiness_status = str(
        supportive_care_toxicity_readiness_bundle.get("supportive_readiness_status") or ""
    ).strip()
    if supportive_readiness_status == "blocking_support_gap" and block_status != "hard_stop":
        block_status = "hard_stop"
        block_reason = (
            "La decisión es oncológicamente plausible, pero no es clínicamente sostenible hoy sin cerrar brechas críticas de soporte/toxicidad."
        )
        allowed_actions = [
            "soporte_clinico",
            "captura_dirigida",
            "co_manejo",
            "revaluacion",
        ]
    elif supportive_readiness_status == "co_manage_required" and block_status == "clear":
        block_status = "provisional"
        block_reason = (
            "La decisión requiere soporte o co-manejo explícito para sostenerse con seguridad."
        )
        allowed_actions = [
            "soporte_clinico",
            "captura_dirigida",
            "co_manejo",
            "monitorizacion_temporal",
        ]
    decision_blocking_bundle["recommendation_block_status"] = block_status
    decision_blocking_bundle["recommendation_block_reason"] = block_reason
    decision_blocking_bundle["allowed_actions_while_blocked"] = allowed_actions
    clinician_decision_capture_bundle = _build_clinician_decision_capture_bundle(
        patient,
        latest_assessment,
        next_best_action,
    )
    state_transition_confirmation_bundle = _build_state_transition_confirmation_bundle(
        patient,
        transition_proposals or [],
        decision_input_requirements,
    )
    adherence_tracking_bundle = _build_adherence_tracking_bundle(patient)
    tumor_board_outcome_bundle = _build_tumor_board_outcome_bundle(patient, latest_assessment)
    pro_decision_bundle = _build_pro_decision_bundle(
        patient,
        state,
        decision_input_requirements,
        field_values,
    )
    ctdna_refinement_bundle = _build_ctdna_refinement_bundle(field_values)
    diagnostic_certainty_bundle = _build_diagnostic_certainty_bundle(patient, state, field_values)
    staging_certainty_bundle = _build_staging_certainty_bundle(
        patient,
        field_values,
        diagnostic_certainty_bundle,
    )
    minimum_decisive_dataset_bundle = _build_minimum_decisive_dataset_bundle(
        state,
        decision_input_requirements,
        field_values,
        diagnostic_certainty_bundle,
        localized_nccn_group=localized_nccn_group,
        localized_as_position=localized_as_position,
    )
    decision_evidence_currentness_bundle = build_decision_evidence_currentness_bundle(
        state=state,
        management_track=management_track,
        field_values=field_values,
        clinical_fact_bundle=clinical_fact_bundle,
        minimum_decisive_dataset_bundle=minimum_decisive_dataset_bundle,
        decision_input_requirements=decision_input_requirements,
        next_best_action=next_best_action,
    )
    minimum_decisive_dataset_bundle = {
        **minimum_decisive_dataset_bundle,
        "selected_decision_evidence_status": decision_evidence_currentness_bundle.get("selected_decision_evidence_status") or "",
        "selected_decision_release_status": decision_evidence_currentness_bundle.get("selected_decision_release_status") or "",
        "decision_refresh_actions": list(decision_evidence_currentness_bundle.get("refresh_actions") or []),
        "decision_traceability_gaps": list(decision_evidence_currentness_bundle.get("traceability_gaps") or []),
        "stale_decision_fields": list(decision_evidence_currentness_bundle.get("stale_evidence_fields") or []),
        "aging_decision_fields": list(decision_evidence_currentness_bundle.get("aging_evidence_fields") or []),
        "decision_evidence_summary": str(decision_evidence_currentness_bundle.get("summary") or ""),
    }
    therapeutic_window_bundle = _build_therapeutic_window_bundle(
        patient,
        state,
        field_values,
        pro_decision_bundle,
        decision_input_requirements,
        diagnostic_certainty_bundle,
        localized_nccn_group=localized_nccn_group,
        localized_as_position=localized_as_position,
        localized_modality_fitness_bundle=localized_modality_fitness_bundle,
    )
    multimodal_imaging_concordance_bundle = _build_multimodal_imaging_concordance_bundle(field_values)
    precision_workflow_bundle = _build_precision_workflow_bundle(
        patient,
        state,
        field_values,
        ctdna_refinement_bundle,
    )
    registry_core_bundle = _build_registry_core_bundle(
        patient,
        state,
        staging_certainty_bundle,
    )
    endpoint_adjudication_bundle = _build_endpoint_adjudication_bundle(patient)
    data_certainty_bundle = _build_data_certainty_bundle(patient)
    ichom_compliance_bundle = _build_ichom_compliance_bundle(state, _merge_score_fields(patient, field_values))
    treatment_adverse_event_bundle = _build_treatment_adverse_event_bundle(patient)
    population_survival_context_bundle = _build_population_survival_context_bundle(patient)
    cost_access_context_bundle = _build_cost_access_context_bundle(patient, latest_assessment, next_best_action)
    governance_summary = {
        "available": True,
        "state": state,
        "management_track": management_track,
        "recommendation_block_status": block_status,
        "recommendation_block_reason": block_reason,
        "allowed_actions_while_blocked": allowed_actions,
        "care_goal": care_intent_contract.get("care_goal") or "",
        "supportive_priority": care_intent_contract.get("supportive_priority") or "",
        "palliative_trigger_status": care_intent_contract.get("palliative_trigger_status") or "",
        "diagnosis_certainty": diagnostic_certainty_bundle.get("diagnosis_certainty") or "",
        "stage_certainty": staging_certainty_bundle.get("stage_certainty") or "",
        "minimum_decisive_dataset_status": minimum_decisive_dataset_bundle.get("dataset_status") or "",
        "selected_decision_evidence_status": decision_evidence_currentness_bundle.get("selected_decision_evidence_status") or "",
        "selected_decision_release_status": decision_evidence_currentness_bundle.get("selected_decision_release_status") or "",
        "staging_concordance_status": staging_adjudication_bundle.get("concordance_status") or "",
        "staging_adjudication_release_status": adjudication_release_status,
        "supportive_readiness_status": supportive_readiness_status,
        "supportive_priority": supportive_care_toxicity_readiness_bundle.get("supportive_priority") or "",
        "therapeutic_window_status": therapeutic_window_bundle.get("opportunity_loss_risk_summary") or "none",
        "registry_denominator_ready": bool(registry_core_bundle.get("denominator_ready")),
    }
    window_worklist_bundle = _build_window_worklist_bundle(
        patient,
        therapeutic_window_bundle,
        minimum_decisive_dataset_bundle,
        governance_summary,
        state_transition_confirmation_bundle,
        adherence_tracking_bundle,
        endpoint_adjudication_bundle,
        care_intent_contract,
        next_best_action,
    )
    registry_core_bundle["therapeutic_window_metrics"] = dict(
        window_worklist_bundle.get("opportunity_loss_summary") or {}
    )
    shared_decision_bundle = _build_shared_decision_bundle(
        patient,
        latest_assessment,
        next_best_action,
        block_status,
        pro_decision_bundle,
        clinician_decision_capture_bundle,
        cost_access_context_bundle,
    )
    if state == "localized_initial":
        shared_decision_bundle["patient_priority_profile"] = patient_priority_profile
        shared_decision_bundle["localized_tradeoff_bundle"] = localized_tradeoff_bundle
        shared_decision_bundle["epic26_governance_contract"] = dict(
            (localized_modality_fitness_bundle or {}).get("epic26_governance_contract") or {}
        )
        shared_decision_bundle["epic26_shared_decision_signals"] = list(
            (localized_modality_fitness_bundle or {}).get("epic26_shared_decision_signals") or []
        )
        shared_decision_bundle["epic26_role_summary"] = str(
            (localized_modality_fitness_bundle or {}).get("epic26_role_summary") or ""
        )
        if (
            localized_modality_fitness_bundle.get("shared_decision_required") == "yes"
            and not patient_priority_profile.get("available")
            and shared_decision_bundle.get("decision_readiness") == "ready"
        ):
            shared_decision_bundle["decision_readiness"] = "provisional"
    score_snapshot = dict(pro_decision_bundle.get("score_interpretation_catalog_snapshot") or {})
    governance_summary["top_active_window_key"] = str((window_worklist_bundle.get("top_active_window") or {}).get("window_key") or "")
    governance_summary["critical_windows_open_count"] = int(
        (window_worklist_bundle.get("opportunity_loss_summary") or {}).get("critical_windows_open_count") or 0
    )
    if state == "localized_initial":
        epic26_governance_contract = dict(
            (localized_modality_fitness_bundle or {}).get("epic26_governance_contract") or {}
        )
        governance_summary["epic26_governance_status"] = str(
            epic26_governance_contract.get("governance_status") or ""
        )
        governance_summary["epic26_primary_guideline_driver"] = str(
            epic26_governance_contract.get("primary_guideline_driver") or ""
        )
        governance_summary["epic26_guardrail"] = str(
            epic26_governance_contract.get("governance_guardrail") or ""
        )
    return {
        "decision_governance_bundle": governance_summary,
        "recommendation_block_status": block_status,
        "recommendation_block_reason": block_reason,
        "allowed_actions_while_blocked": allowed_actions,
        "decision_blocking_bundle": decision_blocking_bundle,
        "diagnostic_certainty_bundle": diagnostic_certainty_bundle,
        "staging_certainty_bundle": staging_certainty_bundle,
        "minimum_decisive_dataset_bundle": minimum_decisive_dataset_bundle,
        "decision_evidence_currentness_bundle": decision_evidence_currentness_bundle,
        "therapeutic_window_bundle": therapeutic_window_bundle,
        "window_worklist_bundle": window_worklist_bundle,
        "localized_modality_fitness_bundle": localized_modality_fitness_bundle,
        "localized_tradeoff_bundle": localized_tradeoff_bundle,
        "radical_prostatectomy_candidacy_profile": radical_prostatectomy_candidacy_profile,
        "localized_survival_context_bundle": localized_survival_context_bundle,
        "active_surveillance_monitoring_profile": active_surveillance_monitoring_profile,
        "patient_priority_profile": patient_priority_profile,
        "clinician_decision_capture_bundle": clinician_decision_capture_bundle,
        "state_transition_confirmation_bundle": state_transition_confirmation_bundle,
        "adherence_tracking_bundle": adherence_tracking_bundle,
        "tumor_board_outcome_bundle": tumor_board_outcome_bundle,
        "staging_adjudication_bundle": staging_adjudication_bundle,
        "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
        "pro_decision_bundle": pro_decision_bundle,
        "shared_decision_bundle": shared_decision_bundle,
        "ctdna_refinement_bundle": ctdna_refinement_bundle,
        "multimodal_imaging_concordance_bundle": multimodal_imaging_concordance_bundle,
        "precision_workflow_bundle": precision_workflow_bundle,
        "registry_core_bundle": registry_core_bundle,
        "endpoint_adjudication_bundle": endpoint_adjudication_bundle,
        "data_certainty_bundle": data_certainty_bundle,
        "ichom_compliance_bundle": ichom_compliance_bundle,
        "treatment_adverse_event_bundle": treatment_adverse_event_bundle,
        "population_survival_context_bundle": population_survival_context_bundle,
        "cost_access_context_bundle": cost_access_context_bundle,
        "hepatic_safety_bundle": dict(field_values.get("hepatic_safety_bundle") or {}),
        "ddi_risk_bundle": dict(field_values.get("ddi_risk_bundle") or {}),
        "advanced_pro_bundle": dict(field_values.get("advanced_pro_bundle") or {}),
        "cognitive_screening_bundle": dict(field_values.get("cognitive_screening_bundle") or {}),
        "variant_histology_bundle": dict(field_values.get("variant_histology_bundle") or {}),
        "score_interpretation_catalog_snapshot": score_snapshot,
    }
