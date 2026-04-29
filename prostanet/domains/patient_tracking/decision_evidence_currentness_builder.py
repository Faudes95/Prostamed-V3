from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prostanet.shared.clinical_fact_policies import (
    compute_freshness_status,
    resolve_freshness_policy,
)
from prostanet.shared.ui_value_normalizer import normalize_field_label


MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

ADVANCED_DECISION_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES

_MISSING_SENTINELS = {
    "",
    "none",
    "null",
    "nan",
    "n/a",
    "unknown",
    "desconocido",
    "desconocida",
    "no documentado",
    "no documentada",
    "no aplica",
    "not_restaged",
    "no realizado",
}

_FIELD_ALIASES = {
    "psa": ["current_psa", "psa_current", "baseline_psa", "bcr_psa", "psa_postop"],
    "current_psa": ["psa_current", "psa", "baseline_psa", "bcr_psa"],
    "psa_current": ["current_psa", "psa", "baseline_psa", "bcr_psa"],
    "psa_postop": ["psa", "psa_current", "bcr_psa"],
    "psadt_months": ["psadt_at_bcr", "psa_doubling_time_months"],
    "pirads_score": ["prior_mpmri_pirads_score", "pirads_v21_score"],
    "mri_fact_date": ["mpmri_date"],
    "biopsy_date": ["confirmatory_biopsy_date"],
    "confirmatory_biopsy_done": ["confirmatory_biopsy_status"],
    "genomic_classifier_result": ["genomic_classifier", "decipher_risk"],
    "genomic_classifier_report_date": ["genomic_report_date", "molecular_report_date"],
    "psma_pet_done": ["psma_done"],
    "psma_study_date": ["psma_pet_date"],
    "castrate_testosterone_status": ["castrate_status_resolved"],
    "ddi_review_status": ["drug_interaction_reviewed"],
    "molecular_report_date": ["molecular_assay_date"],
}

_FIELD_DATE_FIELDS = {
    "psa": ["psa_date", "psa_current_date", "lab_date", "visit_date"],
    "current_psa": ["psa_current_date", "psa_date", "lab_date", "visit_date"],
    "psa_current": ["psa_current_date", "psa_date", "lab_date", "visit_date"],
    "psa_postop": ["psa_current_date", "psa_date", "lab_date", "visit_date"],
    "psadt_months": ["psadt_calculated_at", "psa_current_date", "lab_date", "visit_date"],
    "repeat_psa_value": ["repeat_psa_date", "visit_date"],
    "repeat_psa_date": ["repeat_psa_date", "visit_date"],
    "pirads_score": ["mri_fact_date", "mpmri_date", "visit_date"],
    "mri_fact_date": ["mri_fact_date", "mpmri_date"],
    "biopsy_date": ["biopsy_date", "confirmatory_biopsy_date", "visit_date"],
    "confirmatory_biopsy_done": ["confirmatory_biopsy_date", "biopsy_date", "visit_date"],
    "confirmatory_biopsy_date": ["confirmatory_biopsy_date", "biopsy_date"],
    "targeted_biopsy_status": ["biopsy_date", "confirmatory_biopsy_date", "visit_date"],
    "genomic_classifier_result": ["genomic_classifier_report_date", "genomic_report_date", "molecular_report_date"],
    "genomic_classifier_report_date": ["genomic_classifier_report_date", "genomic_report_date", "molecular_report_date"],
    "conventional_imaging_status": ["conventional_imaging_date", "restaging_imaging_date"],
    "conventional_imaging_date": ["conventional_imaging_date", "restaging_imaging_date"],
    "testosterone": ["latest_testosterone_date", "testosterone_date", "visit_date"],
    "castrate_testosterone_status": ["latest_testosterone_date", "testosterone_date", "visit_date"],
    "current_adt_context": ["visit_date", "latest_testosterone_date"],
    "progression_pattern": ["conventional_imaging_date", "restaging_imaging_date", "visit_date"],
    "ecog_score": ["ecog_date", "visit_date"],
    "g8_score": ["g8_date", "visit_date"],
    "mini_cog_score": ["mini_cog_date", "visit_date"],
    "current_medications": ["visit_date"],
    "ddi_review_status": ["ddi_review_date", "visit_date"],
    "cv_risk_documented": ["cv_risk_date", "visit_date"],
    "hemoglobin": ["cbc_date", "visit_date"],
    "creatinine": ["renal_function_date", "chemistry_panel_date", "visit_date"],
    "potassium": ["chemistry_panel_date", "visit_date"],
    "hrr_status": ["molecular_report_date", "molecular_assay_date"],
    "hrr_gene": ["molecular_report_date", "molecular_assay_date"],
    "biomarker_source": ["molecular_report_date", "molecular_assay_date"],
    "molecular_report_date": ["molecular_report_date", "molecular_assay_date"],
    "psma_pet_done": ["psma_study_date", "psma_pet_date"],
    "psma_study_date": ["psma_study_date", "psma_pet_date"],
    "psma_positive": ["psma_study_date", "psma_pet_date"],
    "psma_negative_dominant_lesions": ["psma_study_date", "psma_pet_date"],
    "psa_nadir": ["psa_nadir_date", "visit_date"],
    "psa_nadir_date": ["psa_nadir_date", "visit_date"],
    "phoenix_delta": ["psa_current_date", "psa_nadir_date", "visit_date"],
    "biopsy_proven_local_recurrence": ["biopsy_date", "visit_date"],
    "mpmri_done": ["mpmri_date", "visit_date"],
    "mpmri_localized_recurrence": ["mpmri_date", "visit_date"],
}

_POLICY_KEY_BY_FIELD = {
    "psa": "current_psa",
    "current_psa": "current_psa",
    "psa_current": "current_psa",
    "psa_postop": "current_psa",
    "psadt_months": "psa_series",
    "repeat_psa_value": "current_psa",
    "repeat_psa_date": "current_psa",
    "pirads_score": "mri_fact_date",
    "biopsy_date": "biopsy_date",
    "confirmatory_biopsy_done": "confirmatory_biopsy_date",
    "confirmatory_biopsy_date": "confirmatory_biopsy_date",
    "targeted_biopsy_status": "biopsy_date",
    "genomic_classifier_result": "genomic_classifier_report_date",
    "genomic_classifier_report_date": "genomic_classifier_report_date",
    "conventional_imaging_status": "conventional_imaging_date",
    "progression_pattern": "conventional_imaging_date",
    "castrate_testosterone_status": "testosterone",
    "hrr_status": "molecular_report_date",
    "hrr_gene": "molecular_report_date",
    "biomarker_source": "molecular_report_date",
    "psma_pet_done": "psma_study_date",
    "psma_positive": "psma_study_date",
    "psma_negative_dominant_lesions": "psma_study_date",
    "psa_nadir": "current_psa",
    "psa_nadir_date": "current_psa",
    "phoenix_delta": "psa_series",
    "biopsy_proven_local_recurrence": "biopsy_date",
    "mpmri_done": "mri_fact_date",
    "mpmri_localized_recurrence": "mri_fact_date",
}

_TRACEABILITY_FIELDS = {
    "hrr_status",
    "hrr_gene",
    "biomarker_source",
    "molecular_report_date",
    "genomic_classifier_result",
    "genomic_classifier_report_date",
}

_STATE_REFRESH_ACTIONS = {
    "diagnostic_workup": "Actualizar PSA y mpMRI antes de cerrar la decisión diagnóstica",
    "post_negative_biopsy_followup": "Actualizar PSA, mpMRI y soporte histológico antes de sostener el seguimiento post-biopsia negativa",
    "localized_initial": "Actualizar PSA, MRI y soporte confirmatorio antes de sostener la decisión local",
    "post_prostatectomy": "Actualizar PSA ultrasensible y reevaluar la ventana de salvage posprostatectomía",
    "recurrence_bcr": "Actualizar PSA/PSADT y reestadificación antes de cerrar la ruta de rescate",
    "post_radiotherapy_or_local_salvage": "Actualizar PSA, confirmación local y reestadificación antes de decidir salvage post-RT",
    "adt_progression_verification": "Actualizar castración actual y reestadificación antes de consolidar progresión bajo ADT",
    "m0_crpc": "Actualizar castración actual y reestadificación convencional antes de sostener nmCRPC",
    "mhspc": "Actualizar fitness, seguridad y carga metastásica antes de sostener intensificación",
    "m1_crpc": "Actualizar castración, biomarcadores e imagen funcional antes de sostener la siguiente línea",
}

_STATE_DECISION_LABELS = {
    "diagnostic_workup": "Cierre diagnóstico",
    "post_negative_biopsy_followup": "Seguimiento tras biopsia negativa",
    "localized_initial": "Decisión localizada",
    "post_prostatectomy": "Vigilancia y salvage posprostatectomía",
    "recurrence_bcr": "Ruta de rescate en recurrencia bioquímica",
    "post_radiotherapy_or_local_salvage": "Salvage local post-radioterapia",
    "adt_progression_verification": "Verificación de progresión bajo ADT",
    "m0_crpc": "Liberación nmCRPC",
    "m1_crpc": "Secuenciación mCRPC",
}

_STATUS_RANK = {
    "current": 0,
    "aging": 1,
    "unknown": 2,
    "stale": 3,
}


@dataclass(frozen=True)
class EvidenceRule:
    field_name: str
    mode: str = "blocking"
    degrade_on_missing: bool = True
    degrade_on_untraceable: bool = True
    degrade_on_stale: bool = True
    degrade_on_aging: bool = True


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(values: list[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _is_present(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return _normalize_text(value).lower() not in _MISSING_SENTINELS


def _is_traceable(value: Any) -> bool:
    return _is_present(value) and _normalize_text(value).lower() not in {"desconocido", "desconocida", "unknown"}


def _facts_index(clinical_fact_bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("fact_key") or "").strip(): dict(item)
        for item in list(clinical_fact_bundle.get("facts") or [])
        if isinstance(item, dict) and str(item.get("fact_key") or "").strip()
    }


def _merged_field_values(
    *,
    field_values: dict[str, Any],
    clinical_fact_bundle: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(clinical_fact_bundle.get("field_values") or {})
    for key, value in dict(field_values or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _lookup_value(
    field_name: str,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> tuple[Any, str]:
    candidates = [field_name, *_FIELD_ALIASES.get(field_name, [])]
    for candidate in candidates:
        if candidate in field_values and field_values.get(candidate) not in (None, "", [], {}):
            return field_values.get(candidate), candidate
    for candidate in candidates:
        fact = dict(facts_index.get(candidate) or {})
        if fact:
            return fact.get("resolved_value"), candidate
    return None, field_name


def _lookup_date(
    field_name: str,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    for candidate in _FIELD_DATE_FIELDS.get(field_name, []):
        value, _ = _lookup_value(candidate, field_values=field_values, facts_index=facts_index)
        if _is_present(value):
            return _normalize_text(value), candidate
    fact = dict(facts_index.get(field_name) or {})
    if fact and _is_present(fact.get("source_date")):
        return _normalize_text(fact.get("source_date")), "source_date"
    return "", ""


def _field_label(field_name: str) -> str:
    return normalize_field_label(field_name, default=field_name)


def _recommended_family(next_best_action: dict[str, Any]) -> str:
    return _normalize_text(dict(next_best_action or {}).get("recommendation_family")).lower()


def _is_active_surveillance_context(
    *,
    management_track: str,
    next_best_action: dict[str, Any],
) -> bool:
    lowered_track = _normalize_text(management_track).lower()
    lowered_family = _recommended_family(next_best_action)
    lowered_title = _normalize_text((next_best_action or {}).get("title")).lower()
    return (
        lowered_track == "active_surveillance"
        or lowered_family in {"active_surveillance_family", "surveillance_family"}
        or "vigilancia" in lowered_title
    )


def _is_salvage_context(next_best_action: dict[str, Any]) -> bool:
    lowered_family = _recommended_family(next_best_action)
    lowered_title = _normalize_text((next_best_action or {}).get("title")).lower()
    return (
        lowered_family in {"salvage_rt_family", "local_mdt_family", "post_rt_salvage"}
        or "salvage" in lowered_title
        or "rescate" in lowered_title
    )


def _state_group(state: str) -> str:
    if state in MHSPC_STATES:
        return "mhspc"
    return state


def _base_required_rules(minimum_decisive_dataset_bundle: dict[str, Any]) -> list[EvidenceRule]:
    return [EvidenceRule(field_name=str(field)) for field in list(minimum_decisive_dataset_bundle.get("required_fields") or [])]


def _state_specific_rules(
    *,
    state: str,
    management_track: str,
    next_best_action: dict[str, Any],
) -> list[EvidenceRule]:
    family = _recommended_family(next_best_action)
    if state == "diagnostic_workup":
        return [
            EvidenceRule("current_psa"),
            EvidenceRule("mri_fact_date"),
            EvidenceRule("biopsy_date", mode="review", degrade_on_missing=False),
        ]
    if state == "post_negative_biopsy_followup":
        return [
            EvidenceRule("current_psa"),
            EvidenceRule("pirads_score", mode="review", degrade_on_missing=False),
            EvidenceRule("mri_fact_date", mode="review", degrade_on_missing=False),
            EvidenceRule("biopsy_date", mode="review", degrade_on_missing=False),
        ]
    if state == "localized_initial":
        rules = [
            EvidenceRule("current_psa"),
            EvidenceRule("mri_fact_date", mode="review", degrade_on_missing=False),
            EvidenceRule("genomic_classifier_report_date", mode="review", degrade_on_missing=False),
        ]
        if _is_active_surveillance_context(management_track=management_track, next_best_action=next_best_action):
            rules.extend(
                [
                    EvidenceRule("confirmatory_biopsy_done"),
                    EvidenceRule("mri_interval_months"),
                    EvidenceRule("confirmatory_biopsy_date", mode="review", degrade_on_missing=False),
                ]
            )
        return rules
    if state == "post_prostatectomy":
        return [
            EvidenceRule("psa_postop"),
            EvidenceRule("current_psa", mode="review", degrade_on_missing=False),
            EvidenceRule("psma_study_date", mode="review", degrade_on_missing=False),
            EvidenceRule("conventional_imaging_date", mode="review", degrade_on_missing=False),
        ]
    if state == "recurrence_bcr":
        return [
            EvidenceRule("current_psa"),
            EvidenceRule("psadt_months"),
            EvidenceRule("psma_study_date", mode="review", degrade_on_missing=False),
            EvidenceRule("conventional_imaging_date", mode="review", degrade_on_missing=False),
        ]
    if state == "post_radiotherapy_or_local_salvage":
        return [
            EvidenceRule("psa_current"),
            EvidenceRule("psa_nadir"),
            EvidenceRule("phoenix_delta"),
            EvidenceRule("biopsy_date", mode="review", degrade_on_missing=False),
            EvidenceRule("mpmri_date", mode="review", degrade_on_missing=False),
            EvidenceRule("psma_study_date", mode="review", degrade_on_missing=False),
            EvidenceRule("conventional_imaging_date", mode="review", degrade_on_missing=False),
        ]
    if state in {"adt_progression_verification", "m0_crpc"}:
        return [
            EvidenceRule("testosterone"),
            EvidenceRule("castrate_testosterone_status"),
            EvidenceRule("current_adt_context"),
            EvidenceRule("conventional_imaging_status"),
            EvidenceRule("conventional_imaging_date"),
            EvidenceRule("progression_pattern"),
        ]
    if state in MHSPC_STATES:
        rules = [
            EvidenceRule("testosterone"),
            EvidenceRule("castrate_testosterone_status"),
        ]
        if family in {"taxane_family"}:
            rules.extend(
                [
                    EvidenceRule("ecog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("g8_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("mini_cog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("hemoglobin", mode="review", degrade_on_missing=False),
                    EvidenceRule("creatinine", mode="review", degrade_on_missing=False),
                    EvidenceRule("potassium", mode="review", degrade_on_missing=False),
                ]
            )
        else:
            rules.extend(
                [
                    EvidenceRule("ecog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("g8_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("mini_cog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("ddi_review_status", mode="review", degrade_on_missing=False),
                    EvidenceRule("cv_risk_documented", mode="review", degrade_on_missing=False),
                ]
            )
        return rules
    if state == "m1_crpc":
        rules = [
            EvidenceRule("testosterone"),
            EvidenceRule("castrate_testosterone_status"),
            EvidenceRule("current_adt_context"),
        ]
        if family == "parp_family":
            rules.extend(
                [
                    EvidenceRule("hrr_status", mode="review", degrade_on_missing=False),
                    EvidenceRule("hrr_gene", mode="review", degrade_on_missing=False),
                    EvidenceRule("biomarker_source", mode="review", degrade_on_missing=False),
                    EvidenceRule("molecular_report_date", mode="review", degrade_on_missing=False),
                ]
            )
        elif family == "psma_rlt_family":
            rules.extend(
                [
                    EvidenceRule("psma_study_date", mode="review", degrade_on_missing=False),
                    EvidenceRule("psma_positive", mode="review", degrade_on_missing=False),
                    EvidenceRule("psma_negative_dominant_lesions", mode="review", degrade_on_missing=False),
                    EvidenceRule("conventional_imaging_date", mode="review", degrade_on_missing=False),
                ]
            )
        else:
            rules.extend(
                [
                    EvidenceRule("ecog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("g8_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("mini_cog_score", mode="review", degrade_on_missing=False),
                    EvidenceRule("hemoglobin", mode="review", degrade_on_missing=False),
                    EvidenceRule("creatinine", mode="review", degrade_on_missing=False),
                    EvidenceRule("potassium", mode="review", degrade_on_missing=False),
                ]
            )
        return rules
    return []


def _normalize_rules(
    *,
    minimum_decisive_dataset_bundle: dict[str, Any],
    state: str,
    management_track: str,
    next_best_action: dict[str, Any],
) -> list[EvidenceRule]:
    ordered_rules = _base_required_rules(minimum_decisive_dataset_bundle) + _state_specific_rules(
        state=state,
        management_track=management_track,
        next_best_action=next_best_action,
    )
    deduped: dict[str, EvidenceRule] = {}
    for rule in ordered_rules:
        field_name = _normalize_text(rule.field_name)
        if not field_name:
            continue
        # State-specific rules intentionally appear after the base dataset rules and
        # must be able to tighten or relax the release semantics for a field.
        deduped[field_name] = rule
    return list(deduped.values())


def _evaluate_field(
    rule: EvidenceRule,
    *,
    field_values: dict[str, Any],
    facts_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    field_name = rule.field_name
    value, resolved_from = _lookup_value(field_name, field_values=field_values, facts_index=facts_index)
    if not _is_present(value):
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": "missing",
            "mode": rule.mode,
            "degrades_release": bool(rule.degrade_on_missing and rule.mode == "blocking"),
            "date_used": "",
            "resolved_from": resolved_from,
            "traceability_gap": False,
        }

    if field_name in _TRACEABILITY_FIELDS and not _is_traceable(value):
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": "untraceable",
            "mode": rule.mode,
            "degrades_release": bool(rule.degrade_on_untraceable),
            "date_used": "",
            "resolved_from": resolved_from,
            "traceability_gap": True,
        }

    policy_key = _POLICY_KEY_BY_FIELD.get(field_name, field_name)
    date_value, _ = _lookup_date(field_name, field_values=field_values, facts_index=facts_index)
    if date_value:
        freshness_status, freshness_expires_at = compute_freshness_status(policy_key, source_date=date_value)
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": freshness_status,
            "mode": rule.mode,
            "degrades_release": bool(
                (freshness_status == "stale" and rule.degrade_on_stale)
                or (freshness_status == "aging" and rule.degrade_on_aging)
            ),
            "date_used": date_value,
            "freshness_expires_at": freshness_expires_at,
            "resolved_from": resolved_from,
            "traceability_gap": False,
        }

    fact = dict(facts_index.get(field_name) or {})
    fact_status = _normalize_text(fact.get("freshness_status")).lower()
    if fact_status in {"current", "aging", "stale"}:
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": fact_status,
            "mode": rule.mode,
            "degrades_release": bool(
                (fact_status == "stale" and rule.degrade_on_stale)
                or (fact_status == "aging" and rule.degrade_on_aging)
            ),
            "date_used": _normalize_text(fact.get("source_date") or fact.get("observed_at")),
            "freshness_expires_at": fact.get("freshness_expires_at"),
            "resolved_from": resolved_from,
            "traceability_gap": False,
        }

    if not resolve_freshness_policy(policy_key).get("expires"):
        return {
            "field": field_name,
            "label": _field_label(field_name),
            "status": "current",
            "mode": rule.mode,
            "degrades_release": False,
            "date_used": "",
            "resolved_from": resolved_from,
            "traceability_gap": False,
        }

    return {
        "field": field_name,
        "label": _field_label(field_name),
        "status": "unknown",
        "mode": rule.mode,
        "degrades_release": False,
        "date_used": "",
        "resolved_from": resolved_from,
        "traceability_gap": False,
    }


def _overall_status(field_statuses: list[dict[str, Any]]) -> tuple[str, str]:
    blocking = [item for item in field_statuses if item.get("mode") == "blocking"]
    review = [item for item in field_statuses if item.get("mode") == "review"]

    if any(
        str(item.get("status") or "") in {"missing", "untraceable", "stale"}
        and bool(item.get("degrades_release"))
        for item in blocking
    ):
        return "stale", "blocked_by_stale_evidence"
    if any(
        str(item.get("status") or "") == "aging"
        and bool(item.get("degrades_release"))
        for item in blocking
    ):
        return "aging", "aging_review_needed"
    if any(
        str(item.get("status") or "") in {"stale", "untraceable", "aging"}
        and bool(item.get("degrades_release"))
        for item in review
    ):
        return "aging", "aging_review_needed"
    if any(str(item.get("status") or "") == "current" for item in field_statuses):
        return "current", "ready_to_release"
    return "unknown", "ready_to_release"


def _selected_decision_label(state: str, next_best_action: dict[str, Any]) -> str:
    return _normalize_text((next_best_action or {}).get("title")) or _STATE_DECISION_LABELS.get(state, "Decisión clínica actual")


def _decision_summary(*, release_status: str, state: str, refresh_actions: list[str]) -> str:
    refresh_hint = refresh_actions[0] if refresh_actions else _STATE_REFRESH_ACTIONS.get(_state_group(state), "")
    if release_status == "blocked_by_stale_evidence":
        if refresh_hint:
            return f"La decisión visible ya no es clínicamente liberable hoy hasta refrescar evidencia decisiva. {refresh_hint}."
        return "La decisión visible ya no es clínicamente liberable hoy hasta refrescar evidencia decisiva."
    if release_status == "aging_review_needed":
        if refresh_hint:
            return f"La decisión visible sigue siendo plausible, pero su vigencia temporal necesita revisión. {refresh_hint}."
        return "La decisión visible sigue siendo plausible, pero su vigencia temporal necesita revisión."
    return "La evidencia decisional visible sigue clínicamente liberable hoy."


def build_decision_evidence_currentness_bundle(
    *,
    state: str,
    management_track: str = "",
    field_values: dict[str, Any] | None = None,
    clinical_fact_bundle: dict[str, Any] | None = None,
    minimum_decisive_dataset_bundle: dict[str, Any] | None = None,
    decision_input_requirements: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_values = dict(field_values or {})
    clinical_fact_bundle = dict(clinical_fact_bundle or {})
    minimum_decisive_dataset_bundle = dict(minimum_decisive_dataset_bundle or {})
    decision_input_requirements = dict(decision_input_requirements or {})
    next_best_action = dict(next_best_action or {})

    rules = _normalize_rules(
        minimum_decisive_dataset_bundle=minimum_decisive_dataset_bundle,
        state=state,
        management_track=management_track,
        next_best_action=next_best_action,
    )
    if not rules:
        return {
            "available": False,
            "surface_variant": "neutral_decision",
            "selected_decision_label": _selected_decision_label(state, next_best_action),
            "selected_decision_evidence_status": "unknown",
            "selected_decision_release_status": "ready_to_release",
            "field_currentness": {},
            "refresh_actions": [],
            "evidence_dates_used": [],
            "traceability_gaps": [],
            "stale_evidence_fields": [],
            "aging_evidence_fields": [],
            "release_blocked_by_stale_evidence": False,
            "summary": "",
        }

    facts_index = _facts_index(clinical_fact_bundle)
    merged_values = _merged_field_values(field_values=field_values, clinical_fact_bundle=clinical_fact_bundle)
    assessments = [
        _evaluate_field(rule, field_values=merged_values, facts_index=facts_index)
        for rule in rules
    ]
    evidence_status, release_status = _overall_status(assessments)

    stale_fields = [
        item["label"]
        for item in assessments
        if str(item.get("status") or "") in {"stale", "missing", "untraceable"}
        and item.get("mode") == "blocking"
    ]
    aging_fields = [
        item["label"]
        for item in assessments
        if str(item.get("status") or "") == "aging"
        or (
            item.get("mode") == "review"
            and str(item.get("status") or "") in {"stale", "untraceable"}
        )
    ]
    traceability_gaps = [
        item["label"]
        for item in assessments
        if bool(item.get("traceability_gap"))
    ]
    evidence_dates_used = [
        {
            "field": item["field"],
            "label": item["label"],
            "date": item["date_used"],
        }
        for item in assessments
        if _normalize_text(item.get("date_used"))
    ]

    refresh_actions = []
    if release_status != "ready_to_release" or aging_fields:
        refresh_actions.append(_STATE_REFRESH_ACTIONS.get(_state_group(state), "Actualizar evidencia clínica decisiva"))

    return {
        "available": True,
        "state": state,
        "management_track": management_track,
        "surface_variant": "advanced_supporting" if state in ADVANCED_DECISION_STATES else "neutral_decision",
        "selected_decision_label": _selected_decision_label(state, next_best_action),
        "selected_decision_family": _normalize_text(next_best_action.get("recommendation_family")),
        "selected_decision_evidence_status": evidence_status,
        "selected_decision_release_status": release_status,
        "field_currentness": {
            item["field"]: {
                "label": item["label"],
                "status": item["status"],
                "mode": item["mode"],
                "date_used": item.get("date_used", ""),
                "resolved_from": item.get("resolved_from", ""),
                "traceability_gap": bool(item.get("traceability_gap")),
            }
            for item in assessments
        },
        "refresh_actions": _dedupe(refresh_actions),
        "evidence_dates_used": evidence_dates_used,
        "traceability_gaps": _dedupe(traceability_gaps),
        "stale_evidence_fields": _dedupe(stale_fields),
        "aging_evidence_fields": _dedupe(aging_fields),
        "release_blocked_by_stale_evidence": release_status == "blocked_by_stale_evidence",
        "decision_releasing_fields": [rule.field_name for rule in rules if rule.mode == "blocking"],
        "review_fields": [rule.field_name for rule in rules if rule.mode == "review"],
        "minimum_dataset_status": _normalize_text(minimum_decisive_dataset_bundle.get("dataset_status")),
        "summary": _decision_summary(
            release_status=release_status,
            state=state,
            refresh_actions=_dedupe(refresh_actions),
        ),
        "advanced_therapy_surface_preferred": state in ADVANCED_DECISION_STATES,
    }


__all__ = ["build_decision_evidence_currentness_bundle"]
