from __future__ import annotations

import json
import unicodedata
from typing import Any

from prostanet.domains.patient_tracking.clinical_decision_governance import prioritize_items_for_window_worklist
from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board, infer_management_track, longitudinal_item_sort_key
from prostanet.domains.patient_tracking.capture_flows import build_missing_input_capture_bundle
from prostanet.domains.patient_tracking.capture_surface import display_capture_field_summary
from prostanet.domains.patient_tracking.cohort_analytics import (
    build_patient_kpis,
    compute_patient_cohort_completeness,
    compute_patient_endpoint_readiness,
    compute_patient_research_readiness,
)
from prostanet.domains.patient_tracking.master_followup_plan import build_master_followup_plan
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    is_mhspc_state,
    resolve_mhspc_state,
    visible_trials_for_mhspc_state,
)
from prostanet.domains.patient_tracking.profile_read_model_builder import (
    build_profile_support_projection,
    build_surface_consistency_projection,
)
from prostanet.domains.patient_tracking.advanced_followup_builder import (
    build_advanced_followup_bundle,
)
from prostanet.domains.patient_tracking.advanced_therapy_decision_builder import (
    build_advanced_therapy_decision_panel,
)
from prostanet.domains.patient_tracking.epic2_clinical_cards_builder import (
    build_epic2_clinical_cards,
)
from prostanet.domains.patient_tracking.bone_health_engine import (
    build_bone_health_recommendation,
)
from prostanet.domains.patient_tracking.ctcae_capture_engine import (
    capture_ctcae_events,
)
from prostanet.shared.germline_testing_triggers import (
    should_offer_germline_testing,
)
from prostanet.domains.patient_tracking.tradeoff_engine import (
    build_tradeoff_matrix,
)
from prostanet.domains.research_intelligence.trial_matching_engine import (
    build_trial_matching_bundle,
)
from prostanet.domains.reporting.sdm_preference_elicitation import (
    build_elicitation_form,
    score_elicitation,
)
from prostanet.domains.patient_tracking.advanced_release_gate_builder import (
    build_advanced_release_gate,
    merge_advanced_release_gate_into_requirements,
)
from prostanet.domains.patient_tracking.supportive_care_toxicity_readiness_builder import (
    build_supportive_care_toxicity_readiness_bundle,
)
from prostanet.domains.patient_tracking.staging_adjudication_builder import (
    build_staging_adjudication_bundle,
)
from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
    merge_staging_adjudication_into_requirements,
)
from prostanet.domains.patient_tracking.live_benchmark import (
    is_live_benchmark_applicable_state,
    resolve_live_benchmark_from_snapshot,
)
from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
from prostanet.domains.patient_tracking.score_interpretation_catalog import (
    build_score_interpretation_snapshot,
    extract_epic26_domain_scorecards,
)
from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
    build_therapeutic_readiness_bundle,
)
from prostanet.domains.patient_tracking.therapy_catalog import summarize_trial_backbones, trial_backbone
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label, therapy_select_options
from prostanet.domains.patient_tracking.vertical_runtime import (
    derive_display_sequence_summary,
    normalize_text,
    select_primary_vertical_bundle,
)
from prostanet.shared.official_diagnosis import build_official_diagnosis_context, diagnosis_field_label
from prostanet.shared.clinical_fact_resolver import resolve_patient_clinical_facts
from prostanet.shared.presentation_text import resolve_option_label
from prostanet.shared.systemic_regimen_scope import build_systemic_regimen_scope_contract
from prostanet.shared.ui_value_normalizer import (
    normalize_capture_target_label,
    normalize_decision_domain_label,
    normalize_fact_group_label,
    normalize_field_label,
    normalize_field_list,
    normalize_input_fact_list,
    normalize_last_decisive_data,
    normalize_numeric_with_unit,
    normalize_source_label,
    normalize_ui_label,
    normalize_ui_payload,
    normalize_ui_text,
    normalize_ui_value,
)


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}
POST_RP_SALVAGE_TRIALS = {
    "ARTISTIC",
    "EMBARK",
    "EMPIRE-1",
    "GETUG-AFU 16",
    "RADICALS-HD",
    "RADICALS-RT",
    "RAVES",
    "RTOG 9601",
    "SPPORT",
}
POST_RP_CONTEXTUAL_SUPPORT_TRIALS = {
    "ARTISTIC",
    "EMPIRE-1",
    "GETUG-AFU 16",
    "RADICALS-HD",
    "RADICALS-RT",
    "RAVES",
    "RTOG 9601",
    "SPPORT",
}

PRIMARY_QUESTION_MAP = {
    "diagnostic_workup": "¿Debemos confirmar histología, repetir MRI o activar biopsia?",
    "post_negative_biopsy_followup": "¿La señal persistente justifica re-biopsia o seguimiento?",
    "localized_initial": "¿Conviene vigilancia activa, cirugía o radioterapia hoy?",
    "post_prostatectomy": "¿Basta vigilancia o hay que acelerar rescate posoperatorio?",
    "recurrence_bcr": "¿Existe una ventana curativa de rescate o ya hay que intensificar?",
    "post_radiotherapy_or_local_salvage": "¿La recurrencia post-RT cumple Phoenix y qué modalidad de salvage domina hoy?",
    "adt_progression_verification": "¿Es CRPC confirmado o primero hay que verificar castración?",
    "mcspc_oligo_metachronous": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "mcspc_low_volume_sync_oligo": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "mcspc_high_volume_sync": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC de novo de alto volumen?",
    "mcspc_high_volume_metachronous": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC metacrónico de alto volumen?",
    "mcspc_high_volume": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "m0_crpc": "¿Debe intensificarse nmCRPC y con qué prioridad clínica?",
    "m1_crpc": "¿Cuál es la siguiente secuencia sistémica prioritaria según biomarcadores y seguridad?",
}

STATE_DISPLAY_MAP = {
    "diagnostic_workup": "Diagnóstico inicial",
    "post_negative_biopsy_followup": "Seguimiento tras biopsia benigna",
    "localized_initial": "Enfermedad localizada o regional N1M0",
    "post_prostatectomy": "Seguimiento posprostatectomía",
    "recurrence_bcr": "Recurrencia bioquímica",
    "post_radiotherapy_or_local_salvage": "Recurrencia post-RT",
    "adt_progression_verification": "Progresión bajo ADT / verificación",
    "mcspc_oligo_metachronous": "mHSPC oligometastásico metacrónico",
    "mcspc_low_volume_sync_oligo": "mHSPC sincrónico de bajo volumen",
    "mcspc_high_volume_sync": "mHSPC de alto volumen sincrónico",
    "mcspc_high_volume_metachronous": "mHSPC de alto volumen metacrónico",
    "mcspc_high_volume": "mHSPC de alto volumen",
    "m0_crpc": "CRPC sin metástasis",
    "m1_crpc": "CRPC metastásico",
}

GENERIC_CARE_INTENT_PATTERNS = (
    "definir tratamiento local",
    "tratamiento local definitivo",
    "mantener o redefinir la estrategia local",
    "monitorizar recuperación",
    "monitorizar recuperacion",
    "reevaluar secuencia sistémica",
    "reevaluar secuencia sistemica",
    "priorizar radioterapia definitiva",
    "activar tratamiento local intensificado",
    "redefinir estrategia terapéutica",
    "confirm castrate testosterone",
    "optimizar adt",
    "confirmar testosterona en rango de castración",
    "confirmar testosterona en rango de castracion",
)

HARD_CARE_INTENT_OVERRIDE_PATTERNS = (
    "optimizar adt",
    "confirmar testosterona",
    "confirmar castración",
    "confirmar castracion",
    "completar datos críticos",
    "completar datos criticos",
    "confirmar fallo post-rt",
    "reabrir estudio diagnóstico",
    "reabrir estudio diagnostico",
)

SPECIFIC_DECISION_TOKENS = (
    "vigilancia activa",
    "observación clínica",
    "observacion clinica",
    "prostatect",
    "radioterapia",
    "salvage",
    "rescate",
    "cryotherapy",
    "mdt",
    "sbrt",
    "adt",
    "abirater",
    "enzalut",
    "apalut",
    "darolut",
    "olapar",
    "pembrol",
    "docetax",
    "cabazitax",
    "lutec",
    "pluvicto",
    "biopsia",
)

DECISION_COMPARE_STOPWORDS = {
    "de",
    "la",
    "el",
    "y",
    "con",
    "sin",
    "para",
    "del",
    "las",
    "los",
    "hoy",
    "ruta",
    "actual",
    "priorizar",
    "activar",
    "mantener",
    "definir",
    "confirmar",
    "reevaluar",
    "redirigir",
    "continuar",
    "sostener",
}

ALGORITHM_EXPLANATIONS = {
    "capra": {
        "what_score_means": "Resume riesgo clínico pretratamiento en enfermedad localizada combinando PSA, Gleason, T clínico, edad y biopsia.",
        "risk_interpretation": "A mayor CAPRA, mayor probabilidad de recurrencia bioquímica tras tratamiento local.",
        "clinical_decision_supported": "Ayuda a refinar vigilancia activa vs tratamiento local y la intensidad del counseling prequirúrgico.",
    },
    "briganti": {
        "what_score_means": "Estima el riesgo de compromiso ganglionar pélvico antes de cirugía.",
        "risk_interpretation": "Riesgos altos apoyan discutir linfadenectomía extendida y carga ganglionar esperada.",
        "clinical_decision_supported": "Refina la decisión de disección ganglionar en candidatos quirúrgicos.",
    },
    "partin": {
        "what_score_means": "Distribuye la probabilidad entre órgano confinado, extensión extracapsular, invasión seminal y ganglios.",
        "risk_interpretation": "La categoría dominante ayuda a anticipar patología y a modular estrategia local.",
        "clinical_decision_supported": "Apoya counseling preoperatorio y expectativa patológica.",
    },
    "mskcc_preop": {
        "what_score_means": "Estima la probabilidad de enfermedad órgano-confinada y otros desenlaces patológicos preoperatorios.",
        "risk_interpretation": "Mayor probabilidad órgano-confinada sugiere cirugía con expectativa patológica más favorable.",
        "clinical_decision_supported": "Apoya selección y counseling quirúrgico.",
    },
    "capra_s": {
        "what_score_means": "Resume riesgo posprostatectomía usando patología final, márgenes, ganglios y PSA.",
        "risk_interpretation": "A mayor CAPRA-S, mayor riesgo de recurrencia y necesidad de vigilancia/re-evaluación más estrecha.",
        "clinical_decision_supported": "Ayuda a definir seguimiento posoperatorio y ventana de rescate.",
    },
    "predict_prostate": {
        "what_score_means": "Modelo pronóstico de mortalidad específica y beneficio relativo de tratamiento local.",
        "risk_interpretation": "El resultado contextualiza beneficio esperado frente a expectativa de vida y riesgo competitivo.",
        "clinical_decision_supported": "Apoya decisión compartida entre vigilancia, cirugía y radioterapia.",
    },
}

LINE_CONTEXT_LABELS = {
    "mHSPC_initial": "mHSPC inicial",
    "mHSPC_post_docetaxel": "mHSPC post-docetaxel",
    "m0_CRPC_first_line": "m0 CRPC primera línea",
    "mCRPC_first_line": "mCRPC primera línea",
    "mCRPC_post_ARPI_pre_taxane": "mCRPC post-ARPI pre-taxano",
    "mCRPC_post_taxane": "mCRPC post-taxano",
    "mCRPC_post_PARP": "mCRPC post-PARP",
    "mCRPC_post_Lu177": "mCRPC post-Lu177",
    "later_line": "Líneas posteriores",
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "No disponible"
    return f"{number:.1f}%"


def _format_date(value: Any) -> str:
    return str(value or "Sin fecha")


def _text_tone(value: Any, *, good: set[str] | None = None, bad: set[str] | None = None) -> str:
    text = str(value or "").lower()
    if good and text in {item.lower() for item in good}:
        return "success"
    if bad and text in {item.lower() for item in bad}:
        return "danger"
    return "neutral"


def _parse_json_blob(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _latest_item(items: list[dict[str, Any]], *date_keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in date_keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[0]


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positivo", "positive", "realizado", "realizada", "iniciado", "iniciada", "completo", "completa"}


def _yes_no(value: Any) -> str:
    if value in (None, ""):
        return "No documentado"
    return "Sí" if _truthy(value) else "No"


def _source_badge(label: str, date_value: Any = "") -> str:
    if not label:
        return ""
    if date_value:
        return f"Fuente: {label} · {date_value}"
    return f"Fuente: {label}"


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return ""


def _normalize_surface_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    ascii_folded = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    return " ".join(ascii_folded.split())


def _decision_tokens(value: Any) -> set[str]:
    text = _normalize_surface_text(value)
    tokens = {
        token
        for token in "".join(ch if ch.isalnum() else " " for ch in text).split()
        if len(token) >= 4 and token not in DECISION_COMPARE_STOPWORDS
    }
    return tokens


def _decision_titles_aligned(left: Any, right: Any) -> bool:
    left_text = _normalize_surface_text(left)
    right_text = _normalize_surface_text(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    if left_text in right_text or right_text in left_text:
        return True
    left_tokens = _decision_tokens(left_text)
    right_tokens = _decision_tokens(right_text)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap >= min(2, len(left_tokens), len(right_tokens))


def _is_transition_like_headline(value: Any) -> bool:
    return _normalize_surface_text(value).startswith("confirmar transición")


def _is_generic_care_intent_headline(value: Any) -> bool:
    text = _normalize_surface_text(value)
    if not text:
        return False
    return any(pattern in text for pattern in GENERIC_CARE_INTENT_PATTERNS)


def _is_hard_care_intent_override(value: Any) -> bool:
    text = _normalize_surface_text(value)
    if not text:
        return False
    return any(pattern in text for pattern in HARD_CARE_INTENT_OVERRIDE_PATTERNS)


def _decision_specificity_score(value: Any) -> int:
    text = _normalize_surface_text(value)
    if not text:
        return 0
    score = 0
    for token in SPECIFIC_DECISION_TOKENS:
        if token in text:
            score += 2
    if len(text.split()) >= 4:
        score += 1
    return score


def _effective_state_display_label(state: str) -> str:
    if state == "localized_initial":
        return "Enfermedad localizada"
    return str(STATE_DISPLAY_MAP.get(state) or state)


def _should_prefer_resolved_stage_label(*, state: str, module_label: Any, resolved_stage_label: Any) -> bool:
    module_text = _normalize_surface_text(module_label)
    resolved_text = _normalize_surface_text(resolved_stage_label)
    if not resolved_text:
        return False
    if not module_text:
        return True
    if module_text == resolved_text:
        return False
    return state in {"localized_initial", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}


def _canonicalize_surface_headline(
    *,
    state: str,
    headline: Any,
    structured_headline: Any = "",
) -> str:
    structured_title = str(structured_headline or "").strip()
    canonical = str(headline or "").strip()
    if state in ADVANCED_STATES and state != "m0_crpc" and structured_title and not _decision_titles_aligned(canonical, structured_title):
        canonical = structured_title
    normalized = _normalize_surface_text(canonical)
    if state == "post_radiotherapy_or_local_salvage":
        if "confirmar fallo post-rt" in normalized:
            return "Confirmar fallo post-RT antes de salvage"
        if "redirigir a secuencia sistemica y reestadificacion" in normalized:
            return "Redirección sistémica / reestadificación"
    if state == "recurrence_bcr" and (
        "redirigir a intensificacion sistemica" in normalized
        or "staging avanzado" in normalized
    ):
        return "Reestadificación sistémica post-PSMA"
    return canonical


def _structured_decision_candidate(raw_result: dict[str, Any] | None) -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    candidates: list[dict[str, Any]] = []
    preferred = dict(raw_result.get("preferred_frontline_regimen") or {})
    if preferred:
        candidates.append(preferred)
    for item in raw_result.get("eligible_treatments") or []:
        if isinstance(item, dict):
            candidates.append(dict(item))

    seen_names: set[str] = set()
    for candidate in candidates:
        regimen_name = str(
            _first_nonempty(
                candidate.get("name"),
                candidate.get("display_label"),
                candidate.get("regimen_label"),
                candidate.get("molecule_or_backbone"),
            )
            or ""
        ).strip()
        if not regimen_name:
            continue
        normalized_name = _normalize_surface_text(regimen_name)
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        title = regimen_name if regimen_name.lower().startswith(("priorizar ", "activar ", "confirmar ", "mantener ", "sostener ", "redirigir ", "reevaluar ")) else f"Priorizar {regimen_name}"
        notes = str(
            _first_nonempty(
                candidate.get("notes"),
                candidate.get("description"),
                " ".join(_as_list(candidate.get("selection_rationale"))[:2]),
                " ".join(_as_list(candidate.get("why_this_rank"))[:2]),
            )
            or ""
        ).strip()
        family = _first_nonempty(
            candidate.get("family_label"),
            candidate.get("family_code"),
            candidate.get("regimen_code"),
            candidate.get("name"),
        )
        return {
            "headline": title,
            "supporting_text": notes,
            "recommendation_family": family,
            "source": "structured_regimen",
        }
    return {}


def _refresh_runtime_assessment(
    *,
    patient: dict[str, Any],
    raw_assessment: dict[str, Any] | None,
    display_assessment: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    refreshed_raw = dict(raw_assessment or {})
    refreshed_display = dict(display_assessment or {})
    module_id = str(refreshed_raw.get("module_id") or "").strip()
    input_snapshot = dict(refreshed_raw.get("input_snapshot") or {})
    if not module_id or not input_snapshot:
        return refreshed_raw, refreshed_display
    try:
        from prostanet.application.module_registry import ModuleRegistry
        from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
        from prostanet.shared.presentation_text import humanize_assessment

        merged_payload = merge_record_into_assessment_payload(input_snapshot, patient)
        refreshed_result = ModuleRegistry().evaluate_module(module_id, merged_payload)
        refreshed_state = refreshed_result.get("state", refreshed_raw.get("state"))
        original_state = str(refreshed_raw.get("state") or "").strip()
        if original_state in POSTLOCAL_STATES and refreshed_state not in POSTLOCAL_STATES:
            refreshed_state = original_state
            refreshed_result = {
                **dict(refreshed_result or {}),
                "state": refreshed_state,
            }
        refreshed_raw["state"] = refreshed_state
        refreshed_raw["input_snapshot"] = merged_payload
        refreshed_raw["result_snapshot"] = refreshed_result
        refreshed_display = humanize_assessment(refreshed_raw)
    except Exception:
        return dict(raw_assessment or {}), dict(display_assessment or {})
    return refreshed_raw, refreshed_display


def _resolve_decision_copy(
    *,
    state: str,
    action_title: Any,
    action_rationale: Any,
    action_family: Any,
    care_headline: Any,
    care_narrative: Any,
    care_family: Any,
    structured_headline: Any = "",
    structured_supporting_text: Any = "",
    structured_family: Any = "",
) -> dict[str, Any]:
    action_title_text = str(action_title or "").strip()
    care_headline_text = str(care_headline or "").strip()
    care_generic = _is_generic_care_intent_headline(care_headline_text)
    care_transition = _is_transition_like_headline(care_headline_text)
    care_hard_override = _is_hard_care_intent_override(care_headline_text)
    aligned = _decision_titles_aligned(care_headline_text, action_title_text)
    action_more_specific = _decision_specificity_score(action_title_text) > _decision_specificity_score(care_headline_text)
    use_care_intent = bool(
        care_headline_text
        and not care_transition
        and (
            (aligned and not (care_generic and action_more_specific))
            or (care_hard_override and not care_generic)
        )
    )

    flags: list[str] = []
    if care_headline_text and action_title_text and care_generic and state not in DIAGNOSTIC_STATES:
        flags.append("care_intent_generic_for_closed_module")
    if care_headline_text and action_title_text and care_generic and action_more_specific and state not in DIAGNOSTIC_STATES:
        flags.append("decision_copy_masks_next_best_action")

    headline = care_headline_text if use_care_intent else action_title_text
    supporting_text = (
        str(care_narrative or "").strip()
        if use_care_intent and _is_present(care_narrative)
        else str(action_rationale or "").strip()
    )
    recommendation_family = (
        care_family
        if use_care_intent and _is_present(care_family)
        else action_family
    )
    structured_title_text = str(structured_headline or "").strip()
    current_generic = _is_generic_care_intent_headline(headline) or _is_transition_like_headline(headline)
    structured_more_specific = _decision_specificity_score(structured_title_text) > _decision_specificity_score(headline)
    suppress_structured_for_nmcrpc_reclassification = (
        state == "m0_crpc"
        and any(
            marker in _normalize_surface_text(candidate)
            for candidate in (action_title_text, care_headline_text, headline)
            for marker in (
                "reclasificar fuera de nmcrpc",
                "completar reestadificacion",
            )
        )
    )
    prefer_structured_for_advanced_state = (
        state in ADVANCED_STATES
        and state != "m0_crpc"
        and structured_title_text
        and not _decision_titles_aligned(headline, structured_title_text)
    )
    if (
        structured_title_text
        and not suppress_structured_for_nmcrpc_reclassification
        and (not headline or current_generic or structured_more_specific or prefer_structured_for_advanced_state)
    ):
        if not _decision_titles_aligned(headline, structured_title_text) or current_generic or not headline:
            headline = structured_title_text
            supporting_text = str(structured_supporting_text or supporting_text or "").strip()
            recommendation_family = structured_family or recommendation_family
            flags.append("structured_regimen_promoted")
    headline = _canonicalize_surface_headline(
        state=state,
        headline=headline,
        structured_headline=structured_title_text,
    )
    return {
        "headline": headline,
        "supporting_text": supporting_text,
        "recommendation_family": recommendation_family,
        "source": "structured_regimen" if structured_title_text and "structured_regimen_promoted" in flags else ("care_intent_contract" if use_care_intent else "next_best_action"),
        "aligned": aligned,
        "care_intent_generic": care_generic,
        "care_intent_transition_like": care_transition,
        "care_intent_hard_override": care_hard_override,
        "flags": flags,
    }


def _build_family_history_summary(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "Sin antecedente hereditario estructurado."
    parts = []
    for entry in entries[:3]:
        relative = entry.get("relative_type") or "Familiar"
        cancer = entry.get("cancer_type") or "cáncer"
        mutation = entry.get("known_mutation")
        detail = f"{relative}: {cancer}"
        if _is_present(mutation) and mutation != "Desconocido":
            detail += f" ({mutation})"
        parts.append(detail)
    return "; ".join(parts)


def _build_pro_delta_summary(pros: list[dict[str, Any]]) -> list[str]:
    if len(pros) < 2:
        return []
    baseline = pros[0]
    latest = pros[-1]
    bullets = []
    for label, key, reverse_good in (
        ("IPSS", "ipss_total", True),
        ("IIEF-5", "iief5_score", False),
        ("EQ-5D VAS", "eq5d_vas", False),
    ):
        base = _safe_float(baseline.get(key))
        current = _safe_float(latest.get(key))
        if base is None or current is None:
            continue
        delta = current - base
        if abs(delta) < 0.5:
            bullets.append(f"{label} sin cambio clínicamente relevante frente al basal.")
            continue
        direction = "mejoría" if (delta < 0 and reverse_good) or (delta > 0 and not reverse_good) else "deterioro"
        bullets.append(f"{label}: {direction} de {abs(delta):.1f} puntos frente al basal.")
    return bullets


def _module_data_contracts() -> list[dict[str, Any]]:
    return [
        {
            "module": "algorithm_panels",
            "inputs_required": ["validated_algorithms", "raw score inputs", "clinical context"],
            "primary_source": "assessment modular + cálculos estructurados",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "therapy_checkpoints",
            "inputs_required": ["labs", "biomarcadores", "imagen", "toxicidad", "línea terapéutica"],
            "primary_source": "agenda longitudinal + longitudinal intelligence",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "document_board",
            "inputs_required": ["documento fuente", "facts verificados"],
            "primary_source": "source_documents + verified_document_facts",
            "accepted_truth_status": ["verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "evidence_applicability",
            "inputs_required": ["estado reconciliado", "trial matching", "gaps de elegibilidad"],
            "primary_source": "pivotal matches + reconciliación longitudinal",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "psa_observability",
            "inputs_required": ["biomarker_longitudinal", "follow_up_visits", "treatment_history"],
            "primary_source": "serie longitudinal de PSA",
            "accepted_truth_status": ["captured", "derived"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "clinical_journey",
            "inputs_required": ["eventos clínicos", "visitas", "tratamientos", "documentos"],
            "primary_source": "event graph longitudinal",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": False,
        },
        {
            "module": "comorbidity_frailty_fitness",
            "inputs_required": ["CCI", "G8", "Fried", "ECOG", "Child-Pugh"],
            "primary_source": "baseline + follow-up estructurado",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "adt_side_effects",
            "inputs_required": ["perfil CV/metabólico", "salud ósea", "fatiga", "cognición"],
            "primary_source": "seguimiento ADT",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": True,
        },
    ]


def _label_for_field(field_name: str) -> str:
    return normalize_field_label(field_name, default=diagnosis_field_label(field_name))


def _displayize_field_list(values: list[Any] | tuple[Any, ...] | None, *, limit: int | None = None) -> list[str]:
    return normalize_field_list(list(values or []), limit=limit)


def _displayize_input_facts(values: list[Any] | tuple[Any, ...] | None, *, limit: int | None = None) -> list[str]:
    return normalize_input_fact_list(list(values or []), limit=limit)


def _displayize_field_value(field_name: str, value: Any) -> str:
    if not _is_present(value):
        return "No disponible"
    normalized_field_name = str(field_name or "").strip().replace(" ", "_")
    if normalized_field_name in {"drug_scheme", "current_treatment"}:
        regimen = regimen_label(value)
        if regimen:
            return regimen
    return str(normalize_ui_value(resolve_option_label(normalized_field_name, value)))


def _displayize_copy(value: Any, *, default: str = "") -> str:
    text = normalize_ui_text(value, default=default)
    text = _collapse_duplicate_phrase(text)
    return _collapse_duplicate_phrase(text)


def _displayize_recommendation_block_reason(value: Any) -> str:
    text = _displayize_copy(value, default="")
    if not text:
        return ""
    reason_prefixes = (
        "Faltan datos críticos que cambian la conducta clínica:",
        "La recomendación sigue abierta hasta cerrar datos decisionales:",
        "Faltan PROs mínimos para modular intensidad terapéutica y decisión compartida:",
    )
    for prefix in reason_prefixes:
        if not text.startswith(prefix):
            continue
        raw_tail = text[len(prefix):].strip()
        raw_fields = [item.strip() for item in raw_tail.split(",") if item.strip()]
        display_fields = normalize_field_list(raw_fields, limit=12)
        if display_fields:
            return f"{prefix} {', '.join(display_fields)}"
    return text


def _collapse_duplicate_phrase(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    words = text.split()
    if len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    return text


def _decorate_provenance_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for entry in entries or []:
        clone = dict(entry)
        field_name = str(clone.get("field_name") or "").strip()
        clone["display_field_name"] = normalize_field_label(field_name, default=field_name or "Dato clínico")
        clone["display_source_type"] = normalize_source_label(clone.get("source_type"))
        clone["display_value"] = _displayize_field_value(field_name, clone.get("value"))
        decorated.append(clone)
    return decorated


def _displayize_trace_items(items: list[Any] | tuple[Any, ...] | None, *, limit: int | None = None) -> list[str]:
    rendered: list[str] = []
    for item in items or []:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        if ": " in text and "→" in text:
            field_name, detail = text.split(": ", 1)
            text = f"{normalize_field_label(field_name, default=field_name)}: {detail}"
        elif text.endswith("actualizado en la visita longitudinal más reciente"):
            field_name = text.replace("actualizado en la visita longitudinal más reciente", "").strip()
            field_name = field_name.removesuffix(":").strip()
            text = f"{normalize_field_label(field_name, default=field_name)} actualizado en la visita longitudinal más reciente"
        rendered.append(_displayize_copy(text, default=""))
    deduped = list(dict.fromkeys(rendered))
    return deduped[:limit] if limit else deduped


def _decorate_missing_input_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for entry in groups or []:
        clone = dict(entry)
        clone["display_missing_inputs"] = _displayize_field_list(entry.get("missing_inputs") or [], limit=8)
        clone["display_inputs_used"] = _displayize_input_facts(entry.get("inputs_used") or [], limit=8)
        decorated.append(clone)
    return decorated


def _decorate_triplet_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return {}
    clone = dict(decision)
    clone["display_missing_inputs"] = _displayize_field_list(decision.get("missing_inputs") or [], limit=8)
    clone["display_cross_scope_explanation"] = _displayize_copy(decision.get("cross_scope_explanation"), default="")
    clone["display_triplet_vs_global_preference_note"] = _displayize_copy(decision.get("triplet_vs_global_preference_note"), default="")
    return clone


def _decorate_copilot_sections(copilot: dict[str, Any]) -> dict[str, Any]:
    decorated = dict(copilot or {})
    clinical_alerts = []
    for alert in decorated.get("clinical_alerts") or []:
        clone = dict(alert)
        title = _displayize_copy(clone.get("title"), default="")
        message = _displayize_copy(clone.get("message"), default="")
        if title and message and title.lower() == message.lower():
            message = ""
        clone["display_title"] = title or "Alerta clínica"
        clone["display_message"] = message
        clone["display_recommended_action"] = _displayize_copy(clone.get("recommended_action"), default="")
        clone["display_guideline_reference"] = _displayize_copy(clone.get("guideline_reference"), default="")
        clone["display_fields_to_capture"] = display_capture_field_summary(
            clone.get("fields_to_capture") or [],
            limit=8,
        ) or _displayize_field_list(clone.get("fields_to_capture") or [], limit=8)
        clinical_alerts.append(clone)
    if clinical_alerts:
        decorated["clinical_alerts"] = clinical_alerts

    comorbidity_scores = dict(decorated.get("comorbidity_scores") or {})
    for key in ("charlson", "g8"):
        score = dict(comorbidity_scores.get(key) or {})
        if score:
            score["display_missing_inputs"] = _displayize_field_list(score.get("missing_inputs") or [], limit=8)
            comorbidity_scores[key] = score
    if comorbidity_scores:
        decorated["comorbidity_scores"] = comorbidity_scores

    therapeutic_fitness = dict(decorated.get("therapeutic_fitness") or {})
    for key in ("frailty", "fit_score"):
        item = dict(therapeutic_fitness.get(key) or {})
        if item:
            item["display_missing_inputs"] = _displayize_field_list(item.get("missing_inputs") or [], limit=8)
            therapeutic_fitness[key] = item
    if therapeutic_fitness:
        decorated["therapeutic_fitness"] = therapeutic_fitness
    return decorated


def _decorate_patient_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for alert in alerts or []:
        clone = dict(alert)
        title = _displayize_copy(clone.get("title"), default="")
        description = _displayize_copy(clone.get("description"), default="")
        if title and description and title.lower() == description.lower():
            description = ""
        clone["display_title"] = title or "Alerta clínica"
        clone["display_description"] = description
        decorated.append(clone)
    return decorated


def _decorate_agenda_items_for_display(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for item in items or []:
        clone = dict(item)
        raw_required_inputs = list(clone.get("required_inputs") or [])
        clone["display_required_inputs"] = (
            display_capture_field_summary(
                raw_required_inputs,
                required_inputs=raw_required_inputs,
                limit=8,
            )
            or normalize_field_list(raw_required_inputs, limit=8)
        )
        clone["display_fields_summary"] = (
            list(clone.get("display_fields_summary") or [])
            or display_capture_field_summary(
                clone.get("raw_fields") or clone.get("fields") or raw_required_inputs,
                required_inputs=raw_required_inputs,
                limit=8,
            )
        )
        decorated.append(clone)
    return decorated


def _decorate_blocking_input_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for group in groups or []:
        clone = dict(group)
        raw_required_fields = list(clone.get("required_fields") or [])
        clone["display_required_fields"] = (
            display_capture_field_summary(
                raw_required_fields,
                required_inputs=raw_required_fields,
                limit=8,
            )
            or normalize_field_list(raw_required_fields, limit=8)
        )
        decorated.append(clone)
    return decorated


def _merge_longitudinal_runtime_context(
    patient: dict[str, Any],
    longitudinal_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    context = dict(patient or {})
    bundle = dict(longitudinal_bundle or {})
    if not bundle:
        return context
    merged_signals = dict(context.get("latest_signal_snapshot") or {})
    merged_signals.update(dict(bundle.get("signals") or {}))
    for key in (
        "decision_governance_bundle",
        "recommendation_block_status",
        "recommendation_block_reason",
        "allowed_actions_while_blocked",
        "decision_blocking_bundle",
        "diagnostic_certainty_bundle",
        "staging_certainty_bundle",
        "minimum_decisive_dataset_bundle",
        "therapeutic_window_bundle",
        "clinician_decision_capture_bundle",
        "state_transition_confirmation_bundle",
        "adherence_tracking_bundle",
        "tumor_board_outcome_bundle",
        "pro_decision_bundle",
        "shared_decision_bundle",
        "ctdna_refinement_bundle",
        "multimodal_imaging_concordance_bundle",
        "precision_workflow_bundle",
        "registry_core_bundle",
        "endpoint_adjudication_bundle",
        "data_certainty_bundle",
        "ichom_compliance_bundle",
        "treatment_adverse_event_bundle",
        "population_survival_context_bundle",
        "cost_access_context_bundle",
        "score_interpretation_catalog_snapshot",
        "transition_resolution",
        "care_intent_contract",
        "palliative_transition_bundle",
        "palliative_monitoring_package",
        "symptom_burden_profile",
        "advance_care_planning_status",
        "hospice_eligibility",
        "acute_palliative_alerts",
        "recommended_supportive_referrals",
        "guideline_followup_plan",
        "longitudinal_truth_snapshot",
        "decision_recalculation_trace",
        "laboratory_intelligence_profile",
        "latest_clinically_decisive_visit",
        "crpc_copilot_bundle",
        "post_rp_salvage_bundle",
        "mhspc_copilot_bundle",
        "diagnostic_biopsy_bundle",
        "localized_surveillance_bundle",
        "post_rt_salvage_bundle",
        "post_rt_schedule_overlay",
        "advanced_followup_bundle",
        "staging_adjudication_bundle",
        "clinical_kernel_snapshot",
        "effective_state",
        "effective_recommendation_family",
        "surface_consistency_status",
        "surface_consistency_flags",
        "blocking_inputs",
        "hard_blocking_inputs",
        "decision_blocking_inputs",
        "supportive_gaps",
        "required_to_recalculate",
        "optional_context_inputs",
        "decision_domains_blocked",
        "why_these_fields_now",
    ):
        value = bundle.get(key)
        if value not in (None, "", [], {}):
            context[key] = value
            merged_signals[key] = value
    if bundle.get("copilot_alerts") is not None:
        context["alerts"] = list(bundle.get("copilot_alerts") or [])
    context["latest_signal_snapshot"] = merged_signals
    return context


def _build_missing_input_actions(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    missing_inputs_by_panel: dict[str, list[str]],
    therapy_checkpoints: list[dict[str, Any]],
    agenda_items: list[dict[str, Any]],
    copilot: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str]:
    bundle = build_missing_input_capture_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=therapy_checkpoints,
        agenda_items=agenda_items,
        copilot=copilot,
    )
    actions = []
    for task in bundle.get("tasks", []):
        actions.append(
            {
                **task,
                "fields": task.get("display_fields_summary") or [_label_for_field(field) for field in (task.get("raw_fields") or [])[:8]],
                "display_label": task.get("display_label") or task.get("title") or "Completar inputs críticos",
                "display_group": task.get("display_group") or normalize_capture_target_label(task.get("capture_target")),
                "display_cta": task.get("display_cta") or task.get("action_label") or "Completar captura clínica",
                "display_impact": task.get("display_impact") or f"Si se completa hoy, puede recalcular {normalize_decision_domain_label(task.get('decision_affected'))}.",
                "display_why_now": task.get("display_why_now") or task.get("rationale") or "Faltan datos estructurados para sostener una decisión clínica.",
                "display_fields_summary": task.get("display_fields_summary") or [_label_for_field(field) for field in (task.get("raw_fields") or [])[:8]],
                "display_capture_target": task.get("display_capture_target") or normalize_capture_target_label(task.get("capture_target")),
            }
        )
    return actions[:8], bundle.get("intake_capture_target", ""), bundle.get("followup_capture_target", "")


def _build_psa_observability(patient: dict[str, Any], copilot: dict[str, Any]) -> dict[str, Any]:
    monitoring = build_psa_by_treatment_line(patient)
    if monitoring.get("has_data"):
        return monitoring
    trajectory = ((copilot or {}).get("response_visualization") or {}).get("psa_trajectory") or {}
    points = list(trajectory.get("points") or [])
    if not points:
        return {"has_data": False, "points": [], "treatment_bands": [], "line_segments": [], "line_events": [], "metrics": {}, "source": "missing"}
    monitoring["points"] = points
    monitoring["treatment_bands"] = trajectory.get("treatment_bands") or []
    return monitoring


def _normalize_readiness_capture_action(action: dict[str, Any]) -> dict[str, Any]:
    raw_fields = list(action.get("raw_fields") or action.get("fields") or [])
    return {
        **dict(action or {}),
        "raw_fields": raw_fields,
        "fields": raw_fields,
        "display_label": action.get("display_label") or action.get("title") or "Cerrar bloqueo terapéutico",
        "display_group": action.get("display_group") or "Liberación terapéutica",
        "display_cta": action.get("display_cta") or "Completar captura dirigida",
        "display_why_now": action.get("display_why_now") or action.get("summary") or "Faltan datos estructurados para liberar la terapia visible.",
        "display_impact": action.get("display_impact") or "Si se completa hoy, puede recalcular el readiness terapéutico.",
        "display_fields_summary": list(action.get("display_fields_summary") or display_capture_field_summary(raw_fields, limit=24)),
        "display_capture_target": action.get("display_capture_target") or normalize_capture_target_label(action.get("capture_target")),
    }


def _build_rt_toxicity_timeline(patient: dict[str, Any]) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []
    courses = (
        patient.get("radiotherapy_courses_detailed")
        or patient.get("rt_courses")
        or patient.get("radiotherapy_courses")
        or []
    )
    for course in courses:
        if not isinstance(course, dict):
            continue
        for toxicity in course.get("toxicity") or []:
            if not isinstance(toxicity, dict):
                continue
            timeline.append(
                {
                    "date": toxicity.get("onset_date") or course.get("rt_end_date") or course.get("rt_end_date") or course.get("rt_start_date") or "",
                    "domain": str(toxicity.get("domain") or "").upper() or "RT",
                    "phase": str(toxicity.get("phase") or "late"),
                    "grade": toxicity.get("grade"),
                    "details": toxicity.get("details") or "",
                }
            )
    latest_followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    if latest_followup:
        if _is_present(latest_followup.get("late_urinary_grade")):
            timeline.append(
                {
                    "date": latest_followup.get("visit_date") or "",
                    "domain": "GU",
                    "phase": "late",
                    "grade": latest_followup.get("late_urinary_grade"),
                    "details": "Toxicidad urinaria tardía documentada en seguimiento.",
                }
            )
        if _is_present(latest_followup.get("late_bowel_grade")):
            timeline.append(
                {
                    "date": latest_followup.get("visit_date") or "",
                    "domain": "GI",
                    "phase": "late",
                    "grade": latest_followup.get("late_bowel_grade"),
                    "details": "Toxicidad intestinal tardía documentada en seguimiento.",
                }
            )
    timeline = [item for item in timeline if item.get("date") or _is_present(item.get("grade"))]
    timeline = sorted(timeline, key=lambda item: str(item.get("date") or ""), reverse=True)
    return {"available": bool(timeline), "timeline": timeline[:12]}


def _build_survivorship_checklist(patient: dict[str, Any], latest_signal_snapshot: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(patient.get("baseline") or {})
    latest_followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    context = {**baseline, **dict(latest_followup or {}), **dict(latest_signal_snapshot or {})}

    def _status(label: str, *, complete: bool, detail: str = "") -> dict[str, Any]:
        return {
            "label": label,
            "status": "completo" if complete else "pendiente",
            "detail": detail,
            "tone": "success" if complete else "warning",
        }

    lipid_complete = any(_is_present(context.get(field)) for field in ["total_cholesterol", "triglycerides", "hdl_cholesterol", "hba1c"])
    smoking_status = str(context.get("smoking_status") or "").strip()
    items = [
        _status("DXA", complete=_truthy(context.get("dxa_baseline_done")), detail=_format_date(context.get("dxa_date"))),
        _status("Lípidos / metabólico", complete=lipid_complete, detail="Perfil metabólico y/o HbA1c documentados." if lipid_complete else ""),
        _status("Riesgo cardiovascular", complete=_truthy(context.get("cv_risk_documented")), detail="Riesgo CV mayor documentado." if _truthy(context.get("cv_risk_documented")) else ""),
        _status("Cesación tabáquica", complete=smoking_status.lower() not in {"activo", "current", "smoker"}, detail=smoking_status or "No documentado"),
        _status("Calcio + Vitamina D", complete=_truthy(context.get("calcium_vitd_started")), detail="Suplementación activa." if _truthy(context.get("calcium_vitd_started")) else ""),
        _status("Protección ósea", complete=_truthy(context.get("bone_protection_started")), detail="Antiresortivo / protección ósea activa." if _truthy(context.get("bone_protection_started")) else ""),
    ]
    return {"available": True, "items": items}


def _build_post_rt_recurrence_profile(
    *,
    post_rt_failure_definition: dict[str, Any],
    post_rt_transition_bundle: dict[str, Any],
    readiness_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    failure = dict(post_rt_failure_definition or {})
    if not failure:
        return {"available": False}
    points = [
        {
            "date": point.get("sample_date") or point.get("date") or "",
            "value": point.get("value"),
            "source": point.get("source") or "",
        }
        for point in list(failure.get("psa_history_points") or [])
    ]
    post_rt_actions = [
        action
        for action in list(readiness_actions or [])
        if "post_rt" in str(action.get("focus") or "") or "salvage" in str(action.get("focus") or "")
    ]
    return {
        "available": True,
        "psa_points": points[-8:],
        "psa_nadir": failure.get("psa_nadir"),
        "psa_nadir_date": failure.get("psa_nadir_date"),
        "phoenix_threshold": failure.get("phoenix_threshold"),
        "phoenix_threshold_reached": failure.get("phoenix_threshold_reached"),
        "phoenix_confirmation_status": failure.get("phoenix_confirmation_status"),
        "bounce_suspected": failure.get("bounce_suspected"),
        "psadt_months": failure.get("psadt_months"),
        "salvage_release_status": failure.get("salvage_release_status"),
        "transition_status": post_rt_transition_bundle.get("transition_status"),
        "transition_reason": " ".join(post_rt_transition_bundle.get("trigger_reasons") or []),
        "required_missing_fields": list(post_rt_transition_bundle.get("required_missing_fields") or failure.get("required_missing_fields") or []),
        "capture_action": post_rt_actions[0] if post_rt_actions else {},
    }


def _build_clinical_journey_events(patient: dict[str, Any], state: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    identity = patient.get("identity") or {}
    if identity.get("diagnosis_date"):
        events.append({"date": identity.get("diagnosis_date"), "title": "Diagnóstico", "origin": "patient_identity", "decision": STATE_DISPLAY_MAP.get(state, "Ruta clínica actual")})
    for biopsy in patient.get("biopsies") or []:
        events.append({
            "date": biopsy.get("biopsy_date"),
            "title": f"Biopsia / patología GG{biopsy.get('isup_grade')}" if _is_present(biopsy.get("isup_grade")) else "Biopsia / patología",
            "origin": "biopsy_details",
            "decision": biopsy.get("risk_group") or "Confirmación histológica",
        })
    for imaging in patient.get("imaging") or []:
        events.append({
            "date": imaging.get("study_date"),
            "title": imaging.get("study_type") or "Imagen",
            "origin": "imaging_studies",
            "decision": imaging.get("psma_result") or imaging.get("clinical_impact") or "Reestadificación",
        })
    for treatment in patient.get("treatments") or []:
        events.append({
            "date": treatment.get("start_date"),
            "title": regimen_label(treatment.get("drug_scheme")) or "Cambio de tratamiento",
            "origin": "treatment_history",
            "decision": _first_nonempty(
                f"L{treatment.get('line_of_therapy_number')}: {LINE_CONTEXT_LABELS.get(str(treatment.get('line_of_therapy_context') or ''), treatment.get('line_of_therapy_context') or '')}".strip(": "),
                treatment.get("line_of_therapy_context"),
                "Secuenciación sistémica",
            ),
        })
    for visit in patient.get("follow_ups") or []:
        events.append({
            "date": visit.get("visit_date"),
            "title": "Visita de seguimiento",
            "origin": "follow_up_visits",
            "decision": visit.get("disease_status") or visit.get("current_treatment") or "Seguimiento longitudinal",
        })
    for response in patient.get("response_assessments") or []:
        events.append({
            "date": response.get("assessment_date"),
            "title": "Re-evaluación terapéutica",
            "origin": "response_assessments",
            "decision": response.get("response_category") or "Sin categoría documentada",
        })
    for event in patient.get("patient_events") or []:
        if str(event.get("event_type") or "") not in {"therapy_started", "therapy_line_changed"}:
            continue
        payload = event.get("payload") or {}
        events.append({
            "date": event.get("event_date"),
            "title": payload.get("label") or "Cambio de línea terapéutica",
            "origin": "patient_events",
            "decision": payload.get("decision") or "Secuenciación sistémica actualizada",
        })
    for document in (patient.get("source_documents") or [])[:20]:
        if document.get("verification_status") == "verified":
            events.append({
                "date": document.get("updated_at") or document.get("created_at"),
                "title": document.get("title") or document.get("file_name") or "Documento verificado",
                "origin": "source_documents",
                "decision": "Documento con facts comprometidos al longitudinal",
            })
    events = [event for event in events if event.get("date")]
    return sorted(events, key=lambda item: str(item.get("date")), reverse=True)[:20]


def _build_agenda_resolution_trace(archived_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces = []
    for item in archived_items[:10]:
        traces.append(
            {
                "title": item.get("title"),
                "status": item.get("status"),
                "resolved_at": item.get("completed_at") or item.get("updated_at") or item.get("due_at"),
                "summary": item.get("summary"),
            }
        )
    return traces


def _build_data_freshness(patient: dict[str, Any], state: str) -> list[dict[str, Any]]:
    followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    biopsy = _latest_item(patient.get("biopsies", []), "biopsy_date")
    imaging = _latest_item(patient.get("imaging", []), "study_date")
    mri_fact = _latest_item(patient.get("mri_facts", []), "fact_date")
    genomics = patient.get("genomics") or {}
    latest_pro = _latest_item(patient.get("pros", []), "assessment_date")
    entries = [
        {
            "label": "PSA",
            "value": _first_nonempty(followup.get("psa_current"), patient.get("baseline", {}).get("baseline_psa"), "No documentado"),
            "date": _first_nonempty(followup.get("visit_date"), patient.get("identity", {}).get("diagnosis_date"), "Sin fecha"),
        },
        {
            "label": "Patología",
            "value": (
                f"GG{biopsy.get('isup_grade')}"
                if _is_present(biopsy.get("isup_grade"))
                else "Sin confirmación histológica"
            ),
            "date": _first_nonempty(biopsy.get("biopsy_date"), "Sin fecha"),
        },
        {
            "label": "MRI / imagen decisora",
            "value": _first_nonempty(
                mri_fact.get("mpmri_quality"),
                imaging.get("study_type"),
                patient.get("baseline", {}).get("metastasis_site"),
                "No documentada",
            ),
            "date": _first_nonempty(mri_fact.get("fact_date"), imaging.get("study_date"), "Sin fecha"),
        },
        {
            "label": "Biomarcador",
            "value": _first_nonempty(
                genomics.get("test_type"),
                genomics.get("hrr_overall"),
                genomics.get("decipher_risk"),
                "No documentado",
            ),
            "date": _first_nonempty(genomics.get("test_date"), "Sin fecha"),
        },
        {
            "label": "PRO",
            "value": (
                f"IPSS {latest_pro.get('ipss_total')}"
                if _is_present(latest_pro.get("ipss_total"))
                else "Sin PROs recientes"
            ),
            "date": _first_nonempty(latest_pro.get("assessment_date"), "Sin fecha"),
        },
    ]
    if state in ADVANCED_STATES | {"adt_progression_verification"}:
        entries.insert(
            1,
            {
                "label": "Testosterona",
                "value": _first_nonempty(followup.get("testosterone_current"), patient.get("baseline", {}).get("testosterone_baseline"), "No documentada"),
                "date": _first_nonempty(followup.get("visit_date"), patient.get("identity", {}).get("diagnosis_date"), "Sin fecha"),
            },
        )
    return entries


def _build_primary_evidence_anchor(display_result: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = []
    for source in display_result.get("source_citations", [])[:]:
        role = source.get("evidence_role")
        if role == "primary_guideline":
            anchors.append(
                {
                    "label": source.get("guideline_or_trial") or source.get("title"),
                    "title": source.get("title"),
                    "url": source.get("doi_or_url") or "",
                    "local_pdf_path": source.get("local_pdf_path") or "",
                }
            )
    return anchors[:3]


def _build_profile_decision_view_model(
    *,
    clinical_compass: dict[str, Any],
    care_intent_contract: dict[str, Any],
    next_best_action: dict[str, Any],
    management_track: str,
    state: str,
) -> dict[str, Any]:
    resolved_decision = _resolve_decision_copy(
        state=state,
        action_title=_first_nonempty(
            (next_best_action or {}).get("action_title"),
            (next_best_action or {}).get("title"),
            clinical_compass.get("primary_clinical_question"),
            "Sin decisión prioritaria estructurada",
        ),
        action_rationale=_first_nonempty(
            (next_best_action or {}).get("action_rationale"),
            (next_best_action or {}).get("rationale"),
            clinical_compass.get("recommended_direction"),
            "El copiloto no ha emitido una narrativa adicional.",
        ),
        action_family=_first_nonempty(
            (next_best_action or {}).get("recommendation_family"),
            clinical_compass.get("recommendation_family"),
        ),
        care_headline=care_intent_contract.get("headline"),
        care_narrative=care_intent_contract.get("narrative"),
        care_family=care_intent_contract.get("recommendation_family"),
        structured_headline=clinical_compass.get("structured_decision_headline"),
        structured_supporting_text=clinical_compass.get("structured_decision_supporting_text"),
        structured_family=clinical_compass.get("structured_decision_family"),
    )
    canonical_headline = _first_nonempty(
        resolved_decision.get("headline"),
        clinical_compass.get("primary_clinical_question"),
        "Sin decisión prioritaria estructurada",
    )
    canonical_narrative = _first_nonempty(
        resolved_decision.get("supporting_text"),
        clinical_compass.get("recommended_direction"),
        "El copiloto no ha emitido una narrativa adicional.",
    )
    canonical_family = _first_nonempty(
        resolved_decision.get("recommendation_family"),
        resolved_decision.get("headline"),
        canonical_headline,
        clinical_compass.get("recommendation_family"),
        clinical_compass.get("effective_state_label"),
        _effective_state_display_label(state),
        "No documentada",
    )
    last_decisive_data = normalize_last_decisive_data(clinical_compass.get("last_decisive_data"))
    consistency_flags = list(resolved_decision.get("flags") or [])
    if _is_present(clinical_compass.get("primary_clinical_question")) and str(clinical_compass.get("primary_clinical_question")).strip() != str(canonical_headline).strip():
        consistency_flags.append("headline_overridden_by_care_intent")
    if _is_present(clinical_compass.get("recommended_direction")) and str(clinical_compass.get("recommended_direction")).strip() != str(canonical_narrative).strip():
        consistency_flags.append("narrative_overridden_by_care_intent")
    if _is_present(clinical_compass.get("recommendation_family")) and str(clinical_compass.get("recommendation_family")).strip() != str(canonical_family).strip():
        consistency_flags.append("family_overridden_by_care_intent")
    effective_state_label = _first_nonempty(
        clinical_compass.get("effective_state_label"),
        _effective_state_display_label(state),
        state,
    )
    broader_stage_label = _first_nonempty(
        clinical_compass.get("current_stage_label"),
        clinical_compass.get("operational_module_label"),
    )
    if _is_present(broader_stage_label) and _normalize_surface_text(broader_stage_label) != _normalize_surface_text(effective_state_label):
        consistency_flags.append("operational_state_headline_broader_than_effective_state")
    return {
        "headline": normalize_ui_value(canonical_headline),
        "narrative": normalize_ui_value(canonical_narrative),
        "recommendation_family": normalize_ui_value(canonical_family),
        "effective_state": normalize_ui_value(effective_state_label),
        "effective_management_track": normalize_ui_value(management_track or care_intent_contract.get("care_intent_key") or "No documentado"),
        "last_decisive_data": last_decisive_data,
        "consistency_flags": list(dict.fromkeys(flag for flag in consistency_flags if flag)),
        "is_consistent": not consistency_flags,
    }


def _display_payload(
    *,
    headline: Any,
    supporting_text: Any = "",
    status: str = "",
    scope: str = "",
    source: str = "",
    visible: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "headline": normalize_ui_value(headline),
        "supporting_text": normalize_ui_value(supporting_text, default=""),
        "status": normalize_ui_value(status, default=""),
        "scope": normalize_ui_value(scope, default=""),
        "source": normalize_ui_value(source, default=""),
        "visible": bool(visible and _is_present(headline)),
    }
    payload.update(extra)
    return payload


def _build_local_adjuncts_visible(
    *,
    state: str,
    signal_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    signal_snapshot = dict(signal_snapshot or {})
    adjuncts: list[dict[str, str]] = []

    def add_adjunct(label: Any, rationale: Any, priority: str, source: str) -> None:
        label_text = normalize_ui_value(label, default="")
        rationale_text = normalize_ui_value(rationale, default="")
        if not label_text:
            return
        if any(item.get("label") == label_text for item in adjuncts):
            return
        adjuncts.append(
            {
                "label": label_text,
                "rationale": rationale_text,
                "priority": normalize_ui_value(priority, default="candidate"),
                "source": normalize_ui_value(source, default=""),
            }
        )

    mhspc_bundle = dict(signal_snapshot.get("mhspc_copilot_bundle") or {})
    if is_mhspc_state(state):
        if bool(mhspc_bundle.get("rt_primary_candidate")):
            add_adjunct(
                "RT al primario",
                "El fenotipo de bajo volumen mantiene visible el control local del tumor primario como adjunto al backbone sistémico.",
                "candidate",
                "mhspc_copilot_bundle",
            )
        if bool(mhspc_bundle.get("mdt_candidate")):
            add_adjunct(
                "MDT",
                "La terapia dirigida a metástasis sigue visible como adjunto contextual y no reemplaza la intensificación sistémica principal.",
                "candidate",
                "mhspc_copilot_bundle",
            )

    for bundle_key, source_label in (
        ("post_rp_salvage_bundle", "post_rp_salvage_bundle"),
        ("post_rt_salvage_bundle", "post_rt_salvage_bundle"),
    ):
        bundle = dict(signal_snapshot.get(bundle_key) or {})
        local_pathway = dict(bundle.get("local_salvage_pathway") or {})
        if not bool(local_pathway.get("visible")):
            continue
        add_adjunct(
            _first_nonempty(
                local_pathway.get("recommended_path"),
                local_pathway.get("headline"),
                "Ruta local de salvage",
            ),
            _first_nonempty(
                local_pathway.get("rationale"),
                local_pathway.get("supporting_text"),
                local_pathway.get("reason"),
            ),
            "required" if str(local_pathway.get("applicability_badge") or "").strip() == "selected_candidate" else "candidate",
            source_label,
        )

    return adjuncts


def _build_clinical_copy_bundle(
    *,
    state: str,
    clinical_compass: dict[str, Any],
    diagnosis_context: dict[str, Any],
    care_intent_contract: dict[str, Any],
    next_best_action: dict[str, Any],
    triplet_decision: dict[str, Any],
    metastatic_state_bundle: dict[str, Any] | None = None,
    signal_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_action = dict(next_best_action or {})
    diagnosis_context = dict(diagnosis_context or {})
    care_intent_contract = dict(care_intent_contract or {})
    triplet_decision = dict(triplet_decision or {})
    metastatic_state_bundle = dict(metastatic_state_bundle or {})
    signal_snapshot = dict(signal_snapshot or {})

    action_title = _first_nonempty(
        runtime_action.get("action_title"),
        runtime_action.get("title"),
        clinical_compass.get("primary_clinical_question"),
        "Sin decisión prioritaria estructurada",
    )
    action_rationale = _first_nonempty(
        runtime_action.get("action_rationale"),
        runtime_action.get("rationale"),
        clinical_compass.get("recommended_direction"),
        "El copiloto no ha emitido una dirección adicional.",
    )
    transition_pending = bool(runtime_action.get("transition_pending"))
    transition_title = _first_nonempty(runtime_action.get("transition_title"), "")
    transition_rationale = _first_nonempty(runtime_action.get("transition_rationale"), "")
    care_headline = str(care_intent_contract.get("headline") or "").strip()
    care_narrative = str(care_intent_contract.get("narrative") or "").strip()
    resolved_decision = _resolve_decision_copy(
        state=state,
        action_title=action_title,
        action_rationale=action_rationale,
        action_family=runtime_action.get("recommendation_family") or clinical_compass.get("recommendation_family"),
        care_headline=care_headline,
        care_narrative=care_narrative,
        care_family=care_intent_contract.get("recommendation_family"),
        structured_headline=clinical_compass.get("structured_decision_headline"),
        structured_supporting_text=clinical_compass.get("structured_decision_supporting_text"),
        structured_family=clinical_compass.get("structured_decision_family"),
    )

    decision_headline = resolved_decision.get("headline") or action_title
    decision_support = resolved_decision.get("supporting_text") or action_rationale
    official_headline = _first_nonempty(
        diagnosis_context.get("official_diagnosis"),
        diagnosis_context.get("operational_diagnosis"),
        clinical_compass.get("official_diagnosis"),
        "Diagnóstico en consolidación",
    )
    official_status = diagnosis_context.get("official_diagnosis_display_status") or "operational_only"
    effective_state_label = _first_nonempty(
        clinical_compass.get("effective_state_label"),
        _effective_state_display_label(state),
        state,
    )
    broader_state_label = _first_nonempty(
        clinical_compass.get("current_stage_label"),
        clinical_compass.get("operational_module_label"),
        effective_state_label,
    )
    operational_headline = effective_state_label
    operational_support = ""
    if _is_present(broader_state_label) and _normalize_surface_text(broader_state_label) != _normalize_surface_text(operational_headline):
        operational_support = broader_state_label
    elif clinical_compass.get("state_conflict_flag") and _is_present(clinical_compass.get("state_conflict_reason")):
        operational_support = clinical_compass.get("state_conflict_reason")

    consistency_flags: list[str] = list(resolved_decision.get("flags") or [])
    if official_status == "confirmed" and state in DIAGNOSTIC_STATES:
        consistency_flags.append("diagnostic_state_with_confirmed_official_copy")
    if transition_pending and _is_transition_like_headline(decision_headline):
        consistency_flags.append("decision_copy_overridden_by_transition")
    if (
        state == "post_negative_biopsy_followup"
        and "mantener seguimiento" in str(decision_headline).lower()
        and "reabr" in str(action_title).lower()
    ):
        consistency_flags.append("reopen_signal_hidden_by_passive_followup_copy")
    if _is_present(broader_state_label) and _normalize_surface_text(broader_state_label) != _normalize_surface_text(operational_headline):
        consistency_flags.append("operational_state_headline_broader_than_effective_state")

    metastatic_stage_resolved = str(metastatic_state_bundle.get("metastatic_stage_resolved") or "M0").strip()
    metastatic_stage_label = _first_nonempty(
        metastatic_state_bundle.get("metastatic_stage_label"),
        metastatic_stage_resolved,
    )
    metastatic_detection_basis = str(metastatic_state_bundle.get("metastatic_detection_basis") or "").strip()
    metastatic_known = metastatic_stage_resolved not in {"", "M0"}
    detection_basis_label = {
        "conventional": "imagen convencional",
        "psma_only": "PET PSMA",
        "both": "PET PSMA e imagen convencional",
        "unknown": "fuente de detección no documentada",
    }.get(metastatic_detection_basis, "")
    nmcrpc_eligible = metastatic_state_bundle.get("nmcrpc_eligible")
    nmcrpc_ineligibility_reason = str(metastatic_state_bundle.get("nmcrpc_ineligibility_reason") or "").strip()
    state_reclassification_reason = str(metastatic_state_bundle.get("state_reclassification_reason") or "").strip()
    restaging_update_required = bool(metastatic_state_bundle.get("restaging_update_required"))
    restaging_currentness_status = str(metastatic_state_bundle.get("restaging_currentness_status") or "").strip()
    restaging_update_reason = str(metastatic_state_bundle.get("restaging_update_reason") or "").strip()
    progression_verification_required = bool(metastatic_state_bundle.get("progression_verification_required"))
    progression_missing_fields = _displayize_field_list(
        list(metastatic_state_bundle.get("progression_verification_missing_fields") or []),
        limit=8,
    )
    progression_target_if_confirmed = str(
        metastatic_state_bundle.get("progression_verification_target_state_if_confirmed") or ""
    ).strip()
    progression_target_if_not_castrate = str(
        metastatic_state_bundle.get("progression_verification_target_state_if_not_castrate") or ""
    ).strip()

    metastatic_support_bits: list[str] = []
    if detection_basis_label:
        if metastatic_detection_basis == "unknown":
            metastatic_support_bits.append(f"Base de detección: {detection_basis_label}.")
        else:
            metastatic_support_bits.append(f"Documentado por {detection_basis_label}.")
    if state_reclassification_reason:
        metastatic_support_bits.append(state_reclassification_reason)
    if restaging_update_required and restaging_update_reason:
        metastatic_support_bits.append(restaging_update_reason)

    metastatic_state_display = _display_payload(
        headline=metastatic_stage_label if metastatic_known else "",
        supporting_text=" ".join(bit for bit in metastatic_support_bits if bit).strip(),
        status="documented" if metastatic_known else "",
        scope="metastatic_state",
        source="metastatic_state_bundle",
        visible=metastatic_known,
        detection_basis=normalize_ui_value(metastatic_detection_basis, default=""),
    )

    nmcrpc_eligibility_headline = ""
    nmcrpc_eligibility_support = ""
    nmcrpc_eligibility_status = ""
    nmcrpc_eligibility_visible = False
    if metastatic_known:
        nmcrpc_eligibility_headline = "m0 CRPC ya no es elegible"
        nmcrpc_eligibility_support = _first_nonempty(
            nmcrpc_ineligibility_reason,
            state_reclassification_reason,
            "La enfermedad metastásica documentada excluye el carril no metastásico.",
        )
        nmcrpc_eligibility_status = "ineligible"
        nmcrpc_eligibility_visible = True
    elif state in {"m0_crpc", "adt_progression_verification"}:
        nmcrpc_eligibility_visible = True
        if nmcrpc_eligible is True:
            nmcrpc_eligibility_headline = "m0 CRPC sigue siendo elegible"
            nmcrpc_eligibility_support = "Sin metástasis documentadas; el carril nmCRPC puede competir cuando el resto del dataset esté completo."
            nmcrpc_eligibility_status = "eligible"
        else:
            nmcrpc_eligibility_headline = "Elegibilidad nmCRPC pendiente"
            nmcrpc_eligibility_support = _first_nonempty(
                nmcrpc_ineligibility_reason,
                "Aún falta cerrar si el caso sigue siendo no metastásico y resistente a la castración.",
            )
            nmcrpc_eligibility_status = "provisional"

    progression_support_bits: list[str] = []
    if progression_missing_fields:
        progression_support_bits.append("Faltan: " + ", ".join(progression_missing_fields) + ".")
    if progression_target_if_confirmed:
        progression_support_bits.append(f"Si se confirma CRPC: {progression_target_if_confirmed}.")
    if progression_target_if_not_castrate:
        progression_support_bits.append(f"Si no está castrado: {progression_target_if_not_castrate}.")
    if restaging_update_required and restaging_update_reason:
        progression_support_bits.append(restaging_update_reason)
    progression_verification_display = _display_payload(
        headline=(
            "M1 documentado; falta cerrar castración y progresión resistente"
            if metastatic_known
            else "Falta cerrar castración y progresión resistente"
        ),
        supporting_text=" ".join(bit for bit in progression_support_bits if bit).strip(),
        status="required" if progression_verification_required else "",
        scope="progression_verification",
        source="metastatic_state_bundle",
        visible=progression_verification_required,
    )

    restaging_update_display = _display_payload(
        headline=(
            "M1 documentado; requiere restadificación actualizada"
            if metastatic_known
            else "Restadificación actualizada pendiente"
        ),
        supporting_text=_first_nonempty(
            restaging_update_reason,
            "La extensión anatómica vigente necesita actualización antes de redirigir el curso clínico actual.",
        ),
        status=restaging_currentness_status or "required",
        scope="restaging_update",
        source="metastatic_state_bundle",
        visible=restaging_update_required,
    )

    if metastatic_known and state == "m0_crpc":
        consistency_flags.append("m1_documented_in_m0_crpc_lane")
    if metastatic_known and nmcrpc_eligible is True:
        consistency_flags.append("m1_documented_with_nmcrpc_eligibility")

    recommendation_scope_display = _display_payload(
        headline=_first_nonempty(
            triplet_decision.get("overall_preferred_frontline_regimen_label"),
            triplet_decision.get("preferred_frontline_regimen_label"),
        ),
        supporting_text=_first_nonempty(
            triplet_decision.get("display_triplet_vs_global_preference_note"),
            triplet_decision.get("display_cross_scope_explanation"),
        ),
        status=triplet_decision.get("cross_scope_alignment") or "",
        scope="recommendation_scope",
        source="mhspc_triplet_decision",
        visible=is_mhspc_state(state) and any(
            _is_present(
                triplet_decision.get(key)
            )
            for key in (
                "overall_preferred_frontline_regimen_label",
                "preferred_frontline_regimen_label",
                "preferred_triplet_candidate_label",
            )
        ),
        overall_preferred_label=normalize_ui_value(
            _first_nonempty(
                triplet_decision.get("overall_preferred_frontline_regimen_label"),
                triplet_decision.get("preferred_frontline_regimen_label"),
            ),
            default="",
        ),
        preferred_triplet_candidate_label=normalize_ui_value(
            triplet_decision.get("preferred_triplet_candidate_label"),
            default="",
        ),
        preferred_triplet_candidate_caption=normalize_ui_value(
            "Si hoy se reabriera triplete"
            if triplet_decision.get("triplet_candidate_only_if_reopened")
            else "Mejor triplete si compite hoy",
            default="",
        ),
    )
    local_adjuncts_visible = _build_local_adjuncts_visible(
        state=state,
        signal_snapshot=signal_snapshot,
    )
    local_adjuncts_headline = " · ".join(
        item.get("label", "")
        for item in local_adjuncts_visible[:3]
        if _is_present(item.get("label"))
    )
    local_adjuncts_support = " ".join(
        item.get("rationale", "")
        for item in local_adjuncts_visible[:2]
        if _is_present(item.get("rationale"))
    ).strip()

    return {
        "official_diagnosis_display": _display_payload(
            headline=official_headline,
            supporting_text=diagnosis_context.get("official_diagnosis_source_summary"),
            status=official_status,
            scope="official_diagnosis",
            source=diagnosis_context.get("official_diagnosis_source_summary") or "clasificación operativa",
            visible=True,
        ),
        "operational_state_display": _display_payload(
            headline=operational_headline,
            supporting_text=operational_support,
            status="pending_confirmation" if clinical_compass.get("state_conflict_flag") else "reconciled",
            scope="operational_state",
            source="reconciled_state",
            visible=True,
        ),
        "decision_today_display": _display_payload(
            headline=decision_headline,
            supporting_text=decision_support,
            status=clinical_compass.get("management_intent_status") or "",
            scope="decision_today",
            source=resolved_decision.get("source") or "next_best_action",
            visible=True,
        ),
        "next_best_action_display": _display_payload(
            headline=decision_headline,
            supporting_text=decision_support,
            status=resolved_decision.get("recommendation_family") or clinical_compass.get("recommendation_family") or "",
            scope="next_best_action",
            source=resolved_decision.get("source") or "next_best_action",
            visible=True,
        ),
        "transition_display": _display_payload(
            headline=transition_title,
            supporting_text=transition_rationale,
            status="pending" if transition_pending else "",
            scope="transition",
            source="transition_proposal",
            visible=transition_pending,
            target_state=normalize_ui_value(runtime_action.get("transition_target_state"), default=""),
        ),
        "metastatic_state_display": metastatic_state_display,
        "nmcrpc_eligibility_display": _display_payload(
            headline=nmcrpc_eligibility_headline,
            supporting_text=nmcrpc_eligibility_support,
            status=nmcrpc_eligibility_status,
            scope="nmcrpc_eligibility",
            source="metastatic_state_bundle",
            visible=nmcrpc_eligibility_visible,
        ),
        "progression_verification_display": progression_verification_display,
        "restaging_update_display": restaging_update_display,
        "recommendation_scope_display": recommendation_scope_display,
        "local_adjuncts_display": _display_payload(
            headline=local_adjuncts_headline,
            supporting_text=local_adjuncts_support,
            status="visible" if local_adjuncts_visible else "",
            scope="local_adjuncts",
            source="signal_snapshot",
            visible=bool(local_adjuncts_visible),
        ),
        "local_adjuncts_visible": local_adjuncts_visible,
        "copy_consistency_flags": list(dict.fromkeys(flag for flag in consistency_flags if flag)),
    }


def _merge_unique_text(*groups: list[str], limit: int = 6) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if not _is_present(item):
                continue
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged


def _response_tone(label: str) -> str:
    text = str(label or "").strip().lower()
    if text in {"pd", "progressive_disease", "progresion", "progresión", "progression"}:
        return "danger"
    if text in {"cr", "pr", "respuesta", "partial_response", "complete_response"}:
        return "success"
    if text in {"sd", "stable_disease", "estable"}:
        return "neutral"
    return "neutral"


def _build_parallel_modifier_bundle(copilot: dict[str, Any], state: str) -> dict[str, Any]:
    modifiers: list[dict[str, str]] = []
    course_adjusters: list[str] = []
    next_actions: list[str] = []
    safety_modifiers: list[str] = []

    def add_modifier(label: str, detail: Any, tone: str = "neutral") -> None:
        if not _is_present(detail):
            return
        detail_text = str(detail).strip()
        if any(item["label"] == label and item["detail"] == detail_text for item in modifiers):
            return
        modifiers.append({"label": label, "detail": detail_text, "tone": tone})

    def add_course(item: Any) -> None:
        if _is_present(item):
            course_adjusters.append(str(item).strip())

    def add_next(item: Any) -> None:
        if _is_present(item):
            next_actions.append(str(item).strip())

    def add_safety(item: Any) -> None:
        if _is_present(item):
            safety_modifiers.append(str(item).strip())

    alerts = copilot.get("clinical_alerts") or []
    critical_alert = next((item for item in alerts if str(item.get("severity", "")).lower() == "critical"), None)
    if not critical_alert:
        critical_alert = next((item for item in alerts if str(item.get("severity", "")).lower() == "warning"), None)
    if critical_alert:
        add_modifier("Seguridad activa", critical_alert.get("title"), "danger" if str(critical_alert.get("severity", "")).lower() == "critical" else "warning")
        add_course(critical_alert.get("title"))
        add_next(critical_alert.get("recommended_action"))
        add_safety(critical_alert.get("title"))

    fitness = copilot.get("therapeutic_fitness") or {}
    fit_score = fitness.get("fit_score") or {}
    frailty = fitness.get("frailty") or {}
    egfr = fitness.get("egfr") or {}
    child_pugh = fitness.get("child_pugh") or {}
    competing_mortality = fitness.get("competing_mortality") or {}
    fit_category = str(fit_score.get("category") or "")
    frailty_status = str(frailty.get("status") or "")
    fitness_modifier_added = False
    if fit_score.get("is_complete") is False:
        missing_fit_inputs = fit_score.get("missing_inputs") or []
        fit_gap_text = "Faltan inputs para definir intensidad terapéutica"
        if missing_fit_inputs:
            fit_gap_text += f": {', '.join(missing_fit_inputs[:3])}"
        add_modifier("Fitness terapéutica", fit_gap_text, "warning")
        add_course("ajustar intensidad tras completar fitness terapéutica")
        add_next("Completar fitness terapéutica para confirmar intensidad del tratamiento")
        add_safety("La intensidad terapéutica sigue pendiente por datos de fitness incompletos.")
        fitness_modifier_added = True
    elif fit_category and fit_category != "Fit":
        add_modifier("Fitness terapéutica", f"{fit_category}: {fit_score.get('recommended_intensity', 'ajustar intensidad')}", "danger" if fit_category == "Frail" else "warning")
        add_course(fit_score.get("recommended_intensity"))
        add_safety(f"Fitness {fit_category.lower()} para intensificación estándar.")
        fitness_modifier_added = True
    elif frailty_status and frailty_status != "Fit":
        add_modifier("Fragilidad", f"{frailty_status}: {', '.join(frailty.get('clinical_actions', [])[:1]) or 'requiere ajuste de intensidad'}", "warning")
        add_course(", ".join(frailty.get("clinical_actions", [])[:1]))
        fitness_modifier_added = True
    if egfr.get("egfr") is not None and float(egfr.get("egfr") or 0) < 60:
        if not fitness_modifier_added:
            add_modifier("Función renal", f"eGFR {egfr.get('egfr')} mL/min ({egfr.get('stage', 'sin estadio')})", "warning")
        add_next(", ".join(egfr.get("clinical_actions", [])[:1]))
        add_safety(f"Función renal reducida: eGFR {egfr.get('egfr')} mL/min.")
    if str(child_pugh.get("grade") or "") in {"B", "C"}:
        if not fitness_modifier_added:
            add_modifier("Riesgo hepático", f"Child-Pugh {child_pugh.get('grade')}", "danger" if str(child_pugh.get("grade")) == "C" else "warning")
        add_next(", ".join(child_pugh.get("clinical_actions", [])[:1]))
        add_safety(f"Riesgo hepático Child-Pugh {child_pugh.get('grade')}.")
    if (competing_mortality.get("mortality_5yr_pct") or 0) >= 30:
        if not fitness_modifier_added:
            add_modifier("Mortalidad competitiva", f"{competing_mortality.get('mortality_5yr_pct')}% a 5 años", "warning")
        add_course(competing_mortality.get("recommendation"))
        add_safety(competing_mortality.get("recommendation"))

    precision = copilot.get("precision_genomics") or {}
    precision_actions = [
        value.get("clinical_action")
        for value in precision.values()
        if isinstance(value, dict) and _is_present(value.get("clinical_action"))
    ]
    if precision_actions:
        add_modifier("Biología accionable", f"{precision.get('actionable_count', len(precision_actions))} vía(s): {precision_actions[0]}", "success")
        for action in precision_actions[:2]:
            add_course(action)
    nepc = precision.get("nepc_suspicion") or {}
    if nepc.get("suspected"):
        add_modifier("Sospecha NEPC", f"Score {nepc.get('score', 'N/D')} con vigilancia de plasticidad de linaje", "danger")
        add_course("Revalorar biopsia y secuenciación platinum-based si la sospecha neuroendocrina se sostiene.")
        add_safety("Sospecha de transformación neuroendocrina / plasticidad de linaje.")

    ddi = copilot.get("ddi_review") or {}
    interactions = ddi.get("interactions") or []
    contraindicated = [item for item in interactions if str(item.get("severity", "")).lower() == "contraindicated"]
    major = [item for item in interactions if str(item.get("severity", "")).lower() in {"contraindicated", "major"}]
    if major:
        lead = contraindicated[0] if contraindicated else major[0]
        detail = (
            f"{len(contraindicated)} contraindicación(es) y {max(len(major) - len(contraindicated), 0)} interacción(es) mayor(es)."
            if contraindicated else
            f"{len(major)} interacción(es) mayor(es) activas."
        )
        add_modifier("Interacciones / formulario", detail, "danger" if contraindicated else "warning")
        add_next(lead.get("recommended_action"))
        add_safety(lead.get("clinical_impact") or lead.get("mechanism"))

    pro_intelligence = copilot.get("pro_intelligence") or {}
    pro_alerts = pro_intelligence.get("alerts") or []
    lead_pro = next((item for item in pro_alerts if str(item.get("severity", "")).lower() == "critical"), None)
    if not lead_pro:
        lead_pro = next((item for item in pro_alerts if str(item.get("severity", "")).lower() == "warning"), None)
    if lead_pro:
        add_modifier("Resultados reportados por el paciente", lead_pro.get("title"), "danger" if str(lead_pro.get("severity", "")).lower() == "critical" else "warning")
        add_course(lead_pro.get("title"))
        add_next(lead_pro.get("recommended_action"))
        add_safety(lead_pro.get("message"))

    oligo = copilot.get("oligomet_assessment") or {}
    if oligo.get("has_data"):
        mdt = oligo.get("mdt_decision") or {}
        sbrt = oligo.get("sbrt_eligibility") or {}
        decision_code = str(mdt.get("decision") or "")
        if decision_code:
            tone = "success" if decision_code == "mdt_plus_systemic" else "warning" if decision_code in {"confirm_psma", "biopsy_then_decide"} else "neutral"
            add_modifier("Carga oligometastásica", mdt.get("rationale") or f"{oligo.get('lesion_count', 0)} lesiones documentadas", tone)
            add_course(mdt.get("rationale"))
        elif sbrt.get("eligible"):
            add_modifier("SBRT/MDT", "Elegible para discusión MDT/SBRT focal", "success")
            add_next("Discutir MDT/SBRT en tumor board si la imagen funcional y la carga oligometastásica se sostienen.")

    response = copilot.get("latest_response_assessment") or {}
    response_label = _first_nonempty(response.get("overall_response"), response.get("recist_category"), response.get("psa_response_category"))
    if response_label:
        tone = _response_tone(response_label)
        detail = f"{response_label} ({_first_nonempty(response.get('assessment_date'), response.get('created_at'), 'sin fecha')})"
        add_modifier("Respuesta terapéutica", detail, tone)
        if tone == "danger":
            add_course("La progresión objetiva obliga re-evaluación de línea y reestadificación dirigida.")
            add_next("Confirmar progresión y redefinir secuencia terapéutica / imagen de decisión.")
            add_safety("Progresión terapéutica reciente documentada.")

    return {
        "active_modifiers": modifiers[:6],
        "what_could_change_course": _merge_unique_text([], course_adjusters, limit=6),
        "next_actions": _merge_unique_text([], next_actions, limit=6),
        "safety_modifiers": _merge_unique_text([], safety_modifiers, limit=4),
    }


def _build_clinical_compass(
    *,
    patient: dict[str, Any],
    state: str,
    reconciliation: dict[str, Any],
    display_assessment: dict[str, Any],
    raw_assessment: dict[str, Any],
    state_timeline: list[dict[str, Any]],
    diagnosis_context: dict[str, Any],
    copilot_modifiers: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
    decision_recalculation_trace: dict[str, Any] | None = None,
    longitudinal_truth_snapshot: dict[str, Any] | None = None,
    guideline_followup_plan: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    nccn = display_result.get("nccn_primary", {}) if display_result else {}
    latest_event = state_timeline[-1] if state_timeline else {}
    monitoring = display_result.get("monitoring_plan", {}) if display_result else {}
    decision_quality = display_result.get("decision_quality", {}) if display_result else {}
    state_conflict = bool(reconciliation.get("state_conflict_flag"))
    runtime_action = dict(next_best_action or {})
    recalculation_trace = dict(decision_recalculation_trace or {})
    truth_snapshot = dict(longitudinal_truth_snapshot or {})
    truth_values = dict(truth_snapshot.get("field_values") or {})
    guideline_plan = dict(guideline_followup_plan or {})
    care_intent = dict(care_intent_contract or {})
    structured_decision = _structured_decision_candidate(raw_result)
    runtime_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    runtime_post_rt_bundle = dict(
        patient.get("post_rt_salvage_bundle")
        or runtime_signal_snapshot.get("post_rt_salvage_bundle")
        or {}
    )
    runtime_post_rt_transition = dict(runtime_post_rt_bundle.get("post_rt_transition_bundle") or {})
    runtime_post_rt_failure = dict(runtime_post_rt_bundle.get("post_rt_failure_definition") or {})
    freshness = _build_data_freshness(patient, state)
    assessment_state = normalize_text(
        (display_assessment or {}).get("state")
        or (raw_assessment or {}).get("state")
    )
    resolved_stage_label = _first_nonempty(STATE_DISPLAY_MAP.get(state), state)
    assessment_state_mismatch = bool(assessment_state and assessment_state != state)
    last_decisive = (
        recalculation_trace.get("latest_clinically_decisive_visit")
        or truth_snapshot.get("latest_clinically_decisive_visit")
        or (freshness[1] if state in DIAGNOSTIC_STATES and len(freshness) > 1 else freshness[0])
    )
    current_diagnosis = diagnosis_context.get("operational_diagnosis") or _first_nonempty(
        display_assessment.get("module_label"),
        STATE_DISPLAY_MAP.get(state),
        "Diagnóstico en consolidación",
    )
    official_diagnosis = diagnosis_context.get("official_diagnosis") or current_diagnosis
    operational_module_label = (
        resolved_stage_label
        if assessment_state_mismatch
        else (
            resolved_stage_label
            if _should_prefer_resolved_stage_label(
                state=state,
                module_label=display_assessment.get("module_label"),
                resolved_stage_label=resolved_stage_label,
            )
            else _first_nonempty(display_assessment.get("module_label"), resolved_stage_label, state)
        )
    )
    effective_state_label = normalize_ui_value(_effective_state_display_label(state))
    modifier_bundle = copilot_modifiers or {}
    what_could_change_course = _merge_unique_text(
        _as_list(display_result.get("decision_changing_inputs"))[:4] or _as_list(display_result.get("missing_critical_inputs"))[:4],
        recalculation_trace.get("why_changed", []),
        limit=6,
    )
    what_could_change_course = _merge_unique_text(
        what_could_change_course,
        modifier_bundle.get("what_could_change_course", []),
        limit=6,
    )
    next_actions = _merge_unique_text(
        _as_list(runtime_action.get("immediate_actions"))[:4],
        _as_list(monitoring.get("actions"))[:4],
        limit=6,
    )
    next_actions = _merge_unique_text(
        next_actions,
        modifier_bundle.get("next_actions", []),
        limit=6,
    )
    salvage_conflict_override = state in {"recurrence_bcr", "post_radiotherapy_or_local_salvage"} and (
        normalize_text(care_intent.get("recommendation_family")) == "salvage"
        or normalize_text(runtime_action.get("recommendation_family")) in {"salvage", "ruta de rescate", "post_rt_salvage"}
        or "salvage" in _first_nonempty(
            care_intent.get("headline"),
            runtime_action.get("title"),
            care_intent.get("narrative"),
            runtime_action.get("rationale"),
        ).lower()
    )
    resolved_decision = _resolve_decision_copy(
        state=state,
        action_title=_first_nonempty(
            runtime_action.get("action_title"),
            runtime_action.get("title"),
            PRIMARY_QUESTION_MAP.get(state),
        ),
        action_rationale=_first_nonempty(
            runtime_action.get("action_rationale"),
            runtime_action.get("rationale"),
            nccn.get("trayectoria_recomendada"),
            nccn.get("recommendation"),
            "Sin dirección priorizada",
        ),
        action_family=_first_nonempty(
            runtime_action.get("recommendation_family"),
            decision_quality.get("recommendation_family"),
            raw_result.get("recommendation_family"),
        ),
        care_headline=care_intent.get("headline"),
        care_narrative=care_intent.get("narrative"),
        care_family=care_intent.get("recommendation_family"),
        structured_headline=structured_decision.get("headline"),
        structured_supporting_text=structured_decision.get("supporting_text"),
        structured_family=structured_decision.get("recommendation_family"),
    )
    recommended_direction = (
        "La etapa longitudinal reconciliada requiere confirmar transición y reemitir recomendación modular sobre el estado vigente."
        if state_conflict and not salvage_conflict_override
        else _first_nonempty(
            resolved_decision.get("supporting_text"),
            nccn.get("trayectoria_recomendada"),
            nccn.get("recommendation"),
            "Sin dirección priorizada",
        )
    )
    monitoring_cadence = _first_nonempty(
        guideline_plan.get("baseline_guideline_plan", {}).get("cadence_summary"),
        monitoring.get("cadence"),
        guideline_plan.get("course_adjusted_plan", {}).get("title"),
        "Sin cadencia estructurada",
    )
    confidence_category = _first_nonempty(
        runtime_action.get("confidence_label"),
        recalculation_trace.get("visibility_status"),
        decision_quality.get("confidence_category"),
        "No documentada",
    )
    recommendation_family = (
        "Estado reconciliado por confirmar"
        if state_conflict and not salvage_conflict_override
        else _first_nonempty(
            resolved_decision.get("recommendation_family"),
            decision_quality.get("recommendation_family"),
            raw_result.get("recommendation_family"),
            "No documentada",
        )
    )
    if state in {"recurrence_bcr", "post_radiotherapy_or_local_salvage"} and str(recommendation_family or "").strip().lower() in {"ruta de rescate", "post_rt_salvage"}:
        recommendation_family = "salvage"
    why_this_now = _merge_unique_text(
        recalculation_trace.get("what_changed_today", []),
        _as_list(nccn.get("fundamentos_personalizados"))[:3] or _as_list(display_result.get("report_sections", {}).get("risk_features"))[:3],
        limit=6,
    )
    if state == "post_radiotherapy_or_local_salvage":
        runtime_missing = _displayize_field_list(
            runtime_post_rt_transition.get("required_missing_fields")
            or runtime_post_rt_failure.get("required_missing_fields")
            or runtime_action.get("data_that_could_change_course")
            or [],
            limit=6,
        )
        why_this_now = _merge_unique_text(
            runtime_post_rt_transition.get("trigger_reasons", []),
            runtime_post_rt_bundle.get("why_changed_today", []),
            limit=6,
        )
        if not why_this_now:
            why_this_now = _merge_unique_text(
                runtime_action.get("immediate_actions", []),
                recalculation_trace.get("what_changed_today", []),
                limit=6,
            )
        what_could_change_course = _merge_unique_text(
            _displayize_field_list(runtime_action.get("data_that_could_change_course") or [], limit=6),
            runtime_missing,
            limit=6,
        )
        if not what_could_change_course:
            what_could_change_course = _merge_unique_text(
                what_could_change_course,
                _displayize_field_list(_as_list(display_result.get("missing_critical_inputs"))[:4], limit=6),
                limit=6,
            )
    why_not_more_confident = _as_list(decision_quality.get("why_not_more_confident")) or _as_list(display_result.get("why_not_more_confident"))
    if state == "post_radiotherapy_or_local_salvage":
        active_runtime_missing = set(
            str(item).strip().lower()
            for item in (
                runtime_post_rt_transition.get("required_missing_fields")
                or runtime_post_rt_failure.get("required_missing_fields")
                or runtime_action.get("data_that_could_change_course")
                or []
            )
            if str(item).strip()
        )
        if not active_runtime_missing:
            why_not_more_confident = [
                item
                for item in why_not_more_confident
                if not any(
                    token in str(item).lower()
                    for token in ("phoenix", "psma", "modalidad local", "salvage feasible")
                )
            ]
    return {
        "current_diagnosis": normalize_ui_value(current_diagnosis),
        "official_diagnosis": normalize_ui_value(official_diagnosis),
        "official_diagnosis_status": diagnosis_context.get("official_diagnosis_status", "missing"),
        "official_diagnosis_display_status": diagnosis_context.get("official_diagnosis_display_status", "operational_only"),
        "official_diagnosis_missing_fields": diagnosis_context.get("official_diagnosis_missing_fields", []),
        "official_diagnosis_source_summary": normalize_ui_value(diagnosis_context.get("official_diagnosis_source_summary", ""), default=""),
        "operational_module_label": normalize_ui_value(operational_module_label),
        "effective_state_label": effective_state_label,
        "current_stage_label": normalize_ui_value(resolved_stage_label if (state_conflict or assessment_state_mismatch) else operational_module_label),
        "explicit_stage_label": normalize_ui_value(_first_nonempty(STATE_DISPLAY_MAP.get(reconciliation.get("explicit_state")), reconciliation.get("explicit_state")), default=""),
        "state_conflict_flag": state_conflict,
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "management_intent_status": normalize_ui_value(_first_nonempty(latest_event.get("management_intent_status_label"), "Pendiente de confirmación")),
        "event_kind_label": normalize_ui_value(_first_nonempty(latest_event.get("event_kind_label"), "Recomendación generada")),
        "primary_clinical_question": normalize_ui_value(_first_nonempty(resolved_decision.get("headline"), PRIMARY_QUESTION_MAP.get(state), "¿Cuál es la siguiente mejor decisión clínica?")),
        "recommended_direction": normalize_ui_value(recommended_direction),
        "why_this_now": why_this_now,
        "what_could_change_course": what_could_change_course,
        "next_actions": next_actions,
        "monitoring_cadence": monitoring_cadence,
        "data_freshness": freshness,
        "last_decisive_data": normalize_last_decisive_data(last_decisive),
        "evidence_anchor": _build_primary_evidence_anchor(display_result),
        "confidence_category": normalize_ui_label(confidence_category),
        "recommendation_family": normalize_ui_value(recommendation_family),
        "decision_changing_inputs": _as_list(display_result.get("decision_changing_inputs")),
        "why_not_more_confident": why_not_more_confident,
        "active_modifiers": modifier_bundle.get("active_modifiers", []),
        "safety_modifiers": modifier_bundle.get("safety_modifiers", []),
        "longitudinal_truth_summary": truth_values,
        "transition_pending": bool(runtime_action.get("transition_pending")),
        "transition_title": normalize_ui_value(runtime_action.get("transition_title"), default=""),
        "transition_rationale": normalize_ui_value(runtime_action.get("transition_rationale"), default=""),
        "structured_decision_headline": normalize_ui_value(structured_decision.get("headline"), default=""),
        "structured_decision_supporting_text": normalize_ui_value(structured_decision.get("supporting_text"), default=""),
        "structured_decision_family": normalize_ui_value(structured_decision.get("recommendation_family"), default=""),
    }


def _localized_decision_board(raw_result: dict[str, Any]) -> dict[str, Any]:
    options = []
    for item in raw_result.get("eligible_treatments", []):
        options.append(
            {
                "label": item.get("name", "Opción"),
                "value": item.get("priority", "eligible"),
                "tone": "success" if item.get("priority") in {"preferred", "eligible"} else "neutral",
                "detail": item.get("notes", ""),
            }
        )
    not_prioritized = _as_list(raw_result.get("not_recommended"))
    if not_prioritized:
        options.append(
            {
                "label": "No priorizar",
                "value": not_prioritized[0],
                "tone": "warning",
                "detail": "Se mantiene visible para la conversación clínica, pero no como trayectoria principal.",
            }
        )
    return {
        "title": "Decision board local",
        "subtitle": "Qué trayectorias siguen abiertas hoy según la etapa actual.",
        "items": options,
        "bullets": _as_list(raw_result.get("nccn_primary", {}).get("alternativas_razonables"))[:3],
    }


def _localized_context_panel(patient: dict[str, Any], raw_assessment: dict[str, Any]) -> dict[str, Any]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    latest_biopsy = _latest_item(patient.get("biopsies", []), "biopsy_date")
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    items = [
        {"label": "PI-RADS previo", "value": _first_nonempty(payload.get("prior_mpmri_pirads_score"), "No documentado")},
        {"label": "Biopsia dirigida previa", "value": _first_nonempty(payload.get("prior_mpmri_targeted_biopsy_status"), "No documentada")},
        {"label": "PRECISE", "value": _first_nonempty(latest_imaging.get("precise_score"), "No documentado")},
        {"label": "Patrón 4", "value": _first_nonempty(payload.get("percent_pattern_4"), latest_biopsy.get("percent_pattern_4"), "No documentado")},
        {"label": "Cribriforme", "value": "Sí" if _first_nonempty(payload.get("cribriform_pattern"), latest_biopsy.get("patron_cribiforme")) in (1, "1", True) else "No"},
        {"label": "Carcinoma intraductal", "value": "Sí" if _first_nonempty(payload.get("intraductal_carcinoma"), latest_biopsy.get("carcinoma_intraductal")) in (1, "1", True) else "No"},
        {"label": "Variante histológica adversa", "value": _first_nonempty(payload.get("adverse_histology_variant_type"), "No documentada")},
    ]
    bullets = []
    classifier = payload.get("genomic_classifier")
    if _is_present(classifier) and classifier != "No realizado":
        bullets.append(f"{classifier} documentado con resultado {_first_nonempty(payload.get('genomic_classifier_result'), 'sin resultado estructurado')}.")
    family_history = _build_family_history_summary(patient.get("family_history", []))
    if family_history:
        bullets.append(f"Historia familiar / germinal: {family_history}")
    return {
        "title": "Contexto anatómico y patológico",
        "subtitle": "Datos que modulan elegibilidad real de vigilancia activa y decisión local.",
        "items": items,
        "bullets": bullets,
    }


def _localized_shared_decision_panel(patient: dict[str, Any], raw_assessment: dict[str, Any], display_result: dict[str, Any]) -> dict[str, Any]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    pros = patient.get("pros", [])
    baseline_pro = pros[0] if pros else {}
    items = [
        {"label": "IPSS basal", "value": _first_nonempty(payload.get("ipss_score"), baseline_pro.get("ipss_total"), patient.get("demographics", {}).get("ipss_score"), "No documentado")},
        {"label": "IIEF-5 basal", "value": _first_nonempty(payload.get("iief5_score"), baseline_pro.get("iief5_score"), patient.get("demographics", {}).get("iief5_score"), "No documentado")},
        {"label": "EPIC-26 urinario: incontinencia", "value": _first_nonempty(payload.get("epic26_urinary_incontinence_domain"), baseline_pro.get("epic26_urinary_incontinence_domain"), payload.get("epic26_urinary_domain"), baseline_pro.get("epic26_urinary_domain"), "No documentado")},
        {"label": "EPIC-26 urinario: irritativo/obstructivo", "value": _first_nonempty(payload.get("epic26_urinary_irritative_domain"), baseline_pro.get("epic26_urinary_irritative_domain"), payload.get("epic26_urinary_domain"), baseline_pro.get("epic26_urinary_domain"), "No documentado")},
        {"label": "EPIC-26 sexual", "value": _first_nonempty(payload.get("epic26_sexual_domain"), baseline_pro.get("epic26_sexual_domain"), "No documentado")},
        {"label": "EPIC-26 intestinal", "value": _first_nonempty(payload.get("epic26_bowel_domain"), baseline_pro.get("epic26_bowel_domain"), "No documentado")},
        {"label": "EPIC-26 hormonal", "value": _first_nonempty(payload.get("epic26_hormonal_domain"), baseline_pro.get("epic26_hormonal_domain"), "No documentado")},
        {"label": "EPIC-26 molestia urinaria global", "value": _first_nonempty(payload.get("epic26_overall_urinary_bother"), baseline_pro.get("epic26_overall_urinary_bother"), "No documentado")},
    ]
    delta_bullets = _build_pro_delta_summary(pros)
    return {
        "title": "Decisión compartida y funcionalidad basal",
        "subtitle": "Base funcional y de beneficio absoluto antes de definir cirugía, radioterapia o vigilancia.",
        "items": items,
        "bullets": delta_bullets or _as_list(display_result.get("nccn_primary", {}).get("mensaje_para_toma_de_decisiones_compartida")) or _as_list(display_result.get("supportive_evidence_context"))[:2],
    }


def _localized_epic26_panel(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    display_result: dict[str, Any],
    raw_result: dict[str, Any],
) -> dict[str, Any]:
    display_scores = list(display_result.get("epic26_domain_scores") or [])
    if not display_scores:
        payload = dict((raw_assessment or {}).get("input_snapshot") or {})
        pros = list(patient.get("pros") or [])
        baseline_pro = dict(pros[0] or {}) if pros else {}
        merged_scores = dict(baseline_pro)
        merged_scores.update({key: value for key, value in payload.items() if value not in (None, "")})
        display_scores = extract_epic26_domain_scorecards(build_score_interpretation_snapshot(merged_scores))
    items = [
        {
            "label": score.get("score_label_es") or "",
            "value": score.get("score_value", "No documentado"),
            "detail": " · ".join(
                part
                for part in (
                    score.get("score_grade_es"),
                    score.get("clinical_equivalence_es"),
                    f"Rango {score.get('band_range')}" if score.get("band_range") else "",
                )
                if part
            ),
        }
        for score in display_scores
    ]
    localized_bundle = dict(raw_result.get("localized_modality_fitness_bundle") or {})
    bullets = []
    tradeoff_summary = str((raw_result.get("localized_tradeoff_bundle") or {}).get("tradeoff_summary") or "")
    epic26_role_summary = str(localized_bundle.get("epic26_role_summary") or "")
    epic26_guardrail = str(
        (localized_bundle.get("epic26_governance_contract") or {}).get("governance_guardrail") or ""
    )
    if tradeoff_summary:
        bullets.append(tradeoff_summary)
    if epic26_role_summary:
        bullets.append(epic26_role_summary)
    if epic26_guardrail:
        bullets.append(epic26_guardrail)
    bullets.extend(list(localized_bundle.get("epic26_shared_decision_signals") or [])[:4])
    if not items:
        return {}
    return {
        "title": "EPIC-26 basal interpretado",
        "subtitle": "Dominios oficiales del cuestionario licenciado en español usados como línea basal funcional, comparación de toxicidad y apoyo de decisión compartida.",
        "items": items,
        "bullets": list(dict.fromkeys(item for item in bullets if item)),
    }


def _localized_modality_panel(
    localized_modality_fitness_bundle: dict[str, Any],
    localized_tradeoff_bundle: dict[str, Any],
    patient_priority_profile: dict[str, Any],
) -> dict[str, Any]:
    dominant_modality = str(localized_modality_fitness_bundle.get("dominant_modality") or "")
    rp_candidacy_profile = dict(localized_modality_fitness_bundle.get("radical_prostatectomy_candidacy_profile") or {})
    survival_context_bundle = dict(localized_modality_fitness_bundle.get("localized_survival_context_bundle") or {})
    modality_label = {
        "active_surveillance": "Vigilancia activa",
        "surgery": "Cirugía",
        "radiotherapy": "Radioterapia",
        "observation": "Observación clínica",
        "multimodal_local": "Control local multimodal",
    }.get(dominant_modality, "Sin modalidad dominante cerrada")
    items = [
        {"label": "Modalidad dominante hoy", "value": modality_label},
        {"label": "Estado de aptitud", "value": _first_nonempty(localized_modality_fitness_bundle.get("modality_fitness_status"), "No documentado")},
        {"label": "Candidato a RP", "value": _first_nonempty(rp_candidacy_profile.get("candidate_status"), "No documentado")},
        {"label": "Cirugía", "value": _first_nonempty(localized_modality_fitness_bundle.get("surgery_status"), "No documentado")},
        {"label": "Radioterapia", "value": _first_nonempty(localized_modality_fitness_bundle.get("radiotherapy_status"), "No documentado")},
        {"label": "Vigilancia activa", "value": _first_nonempty(localized_modality_fitness_bundle.get("active_surveillance_status"), "No documentado")},
    ]
    bullets = _merge_unique_text(
        [rp_candidacy_profile.get("candidate_summary")],
        list(rp_candidacy_profile.get("oncologic_reasons") or [])[:2],
        list(rp_candidacy_profile.get("fitness_reasons") or [])[:2],
        [survival_context_bundle.get("summary")],
        [localized_modality_fitness_bundle.get("dominance_reason")],
        [localized_tradeoff_bundle.get("tradeoff_summary")],
        [
            "Prioridades del paciente: " + ", ".join(patient_priority_profile.get("priorities") or [])
            if patient_priority_profile.get("available")
            else "Faltan prioridades explícitas del paciente cuando hoy compiten modalidades oncológicamente cercanas."
        ],
        list(localized_modality_fitness_bundle.get("why_not_surgery") or [])[:1],
        list(localized_modality_fitness_bundle.get("why_not_radiotherapy") or [])[:1],
        list(localized_modality_fitness_bundle.get("why_not_active_surveillance") or [])[:1],
        limit=6,
    )
    return {
        "title": "Aptitud por modalidad local",
        "subtitle": "Qué modalidad domina hoy y qué trade-off funcional o preferencial explica la diferencia.",
        "items": items,
        "bullets": bullets,
    }


def _diagnostic_panel(patient: dict[str, Any], raw_assessment: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    latest_plan = _latest_item(patient.get("diagnostic_plans", []), "plan_date")
    latest_mri = _latest_item(patient.get("mri_facts", []), "fact_date")
    latest_trigger = _latest_item(patient.get("biopsy_triggers", []), "trigger_date")
    return [
        {
            "title": "Ruta diagnóstica activa",
            "subtitle": "Qué debe pasar ahora para confirmar o reabrir el diagnóstico.",
            "items": [
                {"label": "Plan actual", "value": _first_nonempty(latest_plan.get("plan_type"), "Ruta diagnóstica")},
                {"label": "Siguiente acción", "value": _first_nonempty(latest_plan.get("next_action"), latest_plan.get("recommended_pathway"), "Pendiente de confirmar")},
                {"label": "PSAD", "value": _first_nonempty(payload.get("psad"), "No documentado")},
                {"label": "PI-RADS", "value": _first_nonempty(latest_mri.get("pirads_score"), payload.get("pirads_score"), "No documentado")},
            ],
            "bullets": _as_list(latest_plan.get("trigger_conditions"))[:3],
        },
        {
            "title": "MRI y disparador de biopsia",
            "subtitle": "Calidad de imagen y condiciones que hoy cambian la conducta.",
            "items": [
                {"label": "Calidad MRI", "value": _first_nonempty(latest_mri.get("mpmri_quality"), "No documentada")},
                {"label": "Lesión índice", "value": _first_nonempty(latest_mri.get("lesion_location"), payload.get("index_lesion_location"), "No especificada")},
                {"label": "Trigger de biopsia", "value": _first_nonempty(latest_trigger.get("trigger_reason"), "No documentado")},
                {"label": "Vía prevista", "value": _first_nonempty(latest_trigger.get("planned_biopsy_route"), payload.get("planned_biopsy_route"), "No definida")},
            ],
            "bullets": _as_list(latest_trigger.get("activation_conditions"))[:3],
        },
        {
            "title": "Riesgo hereditario y re-biopsia",
            "subtitle": "Información familiar y previa que cambia el umbral diagnóstico.",
            "items": [
                {"label": "Historia familiar", "value": _build_family_history_summary(patient.get("family_history", []))},
                {"label": "Estado germinal", "value": _first_nonempty(payload.get("germline_status"), "No documentado")},
                {"label": "Biopsias previas", "value": _first_nonempty(payload.get("prior_biopsy_count"), "No documentado")},
                {"label": "MRI dirigida previa", "value": _first_nonempty(payload.get("prior_biopsy_mri_targeted"), "No documentado")},
            ],
            "bullets": [],
        },
    ]


def _localized_panels(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    display_result: dict[str, Any],
    raw_result: dict[str, Any],
    *,
    localized_modality_fitness_bundle: dict[str, Any] | None = None,
    localized_tradeoff_bundle: dict[str, Any] | None = None,
    patient_priority_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    localized_modality_fitness_bundle = dict(localized_modality_fitness_bundle or {})
    localized_tradeoff_bundle = dict(localized_tradeoff_bundle or {})
    patient_priority_profile = dict(patient_priority_profile or {})
    panels = [
        _localized_decision_board(raw_result),
        _localized_context_panel(patient, raw_assessment),
        _localized_shared_decision_panel(patient, raw_assessment, display_result),
    ]
    epic26_panel = _localized_epic26_panel(patient, raw_assessment, display_result, raw_result)
    if epic26_panel.get("items"):
        panels.insert(2, epic26_panel)
    if localized_modality_fitness_bundle:
        panels.insert(
            1,
            _localized_modality_panel(
                localized_modality_fitness_bundle,
                localized_tradeoff_bundle,
                patient_priority_profile,
            ),
        )
    eligible_names = {item.get("name") for item in raw_result.get("eligible_treatments", [])}
    if "Prostatectomía radical" in eligible_names or "Radical prostatectomy" in eligible_names:
        panels.insert(
            2,
            {
                "title": "Panel prequirúrgico",
                "subtitle": "Nomogramas y riesgo patológico solo porque la cirugía sigue siendo una opción real.",
                "items": [
                    {"label": "Cirugía", "value": "Candidato a prostatectomía radical"},
                    {"label": "Objetivo", "value": "Counseling patológico y riesgo ganglionar"},
                ],
                "bullets": [
                    "CAPRA, Briganti, Partin y MSKCC se muestran abajo como refinadores prequirúrgicos.",
                    "Los resultados genómicos y PROs se integran para la conversación compartida, no para sustituir guías.",
                ],
            },
        )
    return panels


def _postlocal_panels(patient: dict[str, Any], raw_assessment: dict[str, Any], display_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    surgery = patient.get("surgery") or {}
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    items = [
        {
            "title": "Recurrencia y rescate",
            "subtitle": "Variables que determinan si existe todavía una ventana curativa o intensificación temprana.",
            "items": [
                {"label": "PSA ultrasensible", "value": _first_nonempty(payload.get("ultrasensitive_psa_assay"), "No documentado")},
                {"label": "Tiempo a recurrencia", "value": _first_nonempty(payload.get("time_to_recurrence_months"), patient.get("bcr", {}).get("time_to_recurrence_months"), "No documentado")},
                {"label": "Márgenes", "value": _first_nonempty(payload.get("margin_location"), surgery.get("margin_location"), "No documentado")},
                {"label": "Decipher", "value": _first_nonempty(payload.get("decipher_risk"), patient.get("genomics", {}).get("decipher_risk"), "No documentado")},
            ],
            "bullets": _as_list(display_result.get("decision_changing_inputs"))[:3],
        },
        {
            "title": "Imagen y ventana curativa",
            "subtitle": "Qué imagen existe y si todavía hay un rescate local factible.",
            "items": [
                {"label": "Imagen convencional", "value": _first_nonempty(payload.get("conventional_imaging_m0"), payload.get("conventional_imaging_status"), "No documentada")},
                {"label": "PSMA-PET", "value": _first_nonempty(payload.get("psma_pet_result"), latest_imaging.get("psma_result"), "No documentado")},
                {"label": "Rescate local factible", "value": _first_nonempty(payload.get("salvage_local_feasible"), payload.get("local_salvage_candidate"), "No documentado")},
                {"label": "Terapia pélvica elegible", "value": _first_nonempty(payload.get("eligible_pelvic_therapy"), "No documentada")},
            ],
            "bullets": _as_list(display_result.get("supportive_evidence_context"))[:2],
        },
    ]
    return items


def _build_advanced_panel_context(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    raw_result: dict[str, Any],
    display_result: dict[str, Any],
    copilot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    prior_history = patient.get("prior_history") or {}
    baseline = patient.get("baseline") or {}
    genomics = patient.get("genomics") or {}
    latest_followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    latest_treatment = _latest_item(patient.get("treatments", []), "start_date")
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    latest_stage_visit = _latest_item(patient.get("stage_visits", []), "visit_date")
    latest_visit_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {})
    if not latest_visit_payload:
        latest_visit_payload = ((latest_followup.get("visit_bundle") or {}).get("payload") or {})
    precision = (copilot or {}).get("precision_genomics") or {}
    fitness = (copilot or {}).get("therapeutic_fitness") or {}
    adt_effects = (copilot or {}).get("adt_side_effects") or {}
    ddi = (copilot or {}).get("ddi_review") or {}
    verified_facts = patient.get("verified_document_facts") or []
    verified_by_field: dict[str, dict[str, Any]] = {}
    for fact in verified_facts:
        field_name = fact.get("field_name")
        if field_name and field_name not in verified_by_field and _is_present(fact.get("value")):
            verified_by_field[field_name] = fact
    latest_psma = next(
        (
            item
            for item in (patient.get("imaging") or [])
            if "psma" in str(item.get("study_type", "")).lower()
        ),
        {},
    )
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    try:
        from prostanet.domains.patient_tracking.longitudinal_intelligence import build_state_classifier_payload

        inferred_payload = build_state_classifier_payload(patient, raw_assessment)
    except Exception:
        inferred_payload = {}

    def _candidate(value: Any, source_label: str, source_date: Any, evidence_status: str) -> dict[str, Any]:
        return {
            "value": value,
            "source_label": source_label,
            "source_date": str(source_date or ""),
            "evidence_status": evidence_status,
        }

    def _verified_candidate(field_name: str) -> dict[str, Any] | None:
        fact = verified_by_field.get(field_name)
        if not fact:
            return None
        return _candidate(fact.get("value"), "documento verificado", fact.get("source_date"), "verified")

    def _visit_candidate(field_name: str) -> dict[str, Any] | None:
        if _is_present(latest_visit_payload.get(field_name)):
            return _candidate(
                latest_visit_payload.get(field_name),
                "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
                latest_stage_visit.get("visit_date") or latest_followup.get("visit_date"),
                "captured",
            )
        return None

    def _assessment_candidate(field_name: str) -> dict[str, Any] | None:
        if _is_present(payload.get(field_name)):
            return _candidate(payload.get(field_name), "assessment modular", raw_assessment.get("assessment_date"), "captured")
        return None

    def _first_candidate(*candidates: dict[str, Any] | None) -> dict[str, Any]:
        for candidate in candidates:
            if candidate and _is_present(candidate.get("value")):
                return candidate
        return _candidate("", "", "", "missing")

    def _resolved_item(
        *,
        label: str,
        field_name: str,
        candidates: list[dict[str, Any] | None],
        formatter=None,
        default: str = "No documentado",
        drives_eligibility: bool = False,
    ) -> dict[str, Any]:
        chosen = _first_candidate(*candidates)
        raw_value = chosen.get("value")
        if not _is_present(raw_value):
            value = default
        else:
            value = formatter(raw_value) if formatter else raw_value
        status = chosen.get("evidence_status", "missing")
        status_label = {
            "verified": "verificado",
            "captured": "capturado",
            "inferred": "inferido",
            "missing": "faltante",
        }.get(status, status)
        detail = ""
        if chosen.get("source_label"):
            detail = f"{_source_badge(chosen.get('source_label', ''), chosen.get('source_date', ''))} · {status_label}"
        else:
            detail = status_label.capitalize()
        return {
            "label": label,
            "field_name": field_name,
            "value": value,
            "detail": detail,
            "source_label": chosen.get("source_label", ""),
            "source_date": chosen.get("source_date", ""),
            "evidence_status": status,
            "drives_eligibility": drives_eligibility,
        }

    hrr_gene_display = _first_nonempty(
        latest_visit_payload.get("hrr_gene"),
        payload.get("hrr_gene"),
        "documentado",
    )
    hrr_item = _resolved_item(
        label="HRR / BRCA",
        field_name="hrr_status",
        candidates=[
            _verified_candidate("hrr_status"),
            _visit_candidate("hrr_status"),
            _candidate(genomics.get("hrr_overall"), "genomic_profile", genomics.get("test_date"), "captured") if _is_present(genomics.get("hrr_overall")) else None,
            _assessment_candidate("hrr_status"),
            _candidate(baseline.get("hrr_status"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("hrr_status")) else None,
        ],
        formatter=lambda value: f"{value}{f' ({hrr_gene_display})' if _is_present(hrr_gene_display) else ''}",
        drives_eligibility=True,
    )

    msi_item = _resolved_item(
        label="MSI / TMB",
        field_name="msi_status",
        candidates=[
            _verified_candidate("msi_status"),
            _visit_candidate("msi_status"),
            _candidate(genomics.get("msi_status"), "genomic_profile", genomics.get("test_date"), "captured") if _is_present(genomics.get("msi_status")) else None,
            _assessment_candidate("msi_status"),
            _candidate("TMB-high", "stage_visit_records", latest_stage_visit.get("visit_date"), "captured") if _truthy(latest_visit_payload.get("tmb_high")) else None,
            _candidate("TMB-high", "assessment modular", raw_assessment.get("assessment_date"), "captured") if _truthy(payload.get("tmb_high")) else None,
        ],
        drives_eligibility=True,
    )

    psma_value = None
    if _is_present(latest_psma.get("psma_result")):
        psma_value = "Sí" if str(latest_psma.get("psma_result", "")).lower().startswith("pos") else "No"
    psma_item = _resolved_item(
        label="PSMA",
        field_name="psma_positive",
        candidates=[
            _verified_candidate("psma_positive"),
            _visit_candidate("psma_positive"),
            _candidate(psma_value, "imaging_studies", latest_psma.get("study_date"), "captured") if _is_present(psma_value) else None,
            _assessment_candidate("psma_positive"),
        ],
        formatter=lambda value: value if value in {"Sí", "No"} else _yes_no(value),
        drives_eligibility=True,
    )

    psma_negative_item = _resolved_item(
        label="Lesiones dominantes PSMA negativas",
        field_name="psma_negative_dominant_lesions",
        candidates=[
            _verified_candidate("psma_negative_dominant_lesions"),
            _visit_candidate("psma_negative_dominant_lesions"),
            _candidate(
                (latest_psma.get("findings") or {}).get("psma_negative_dominant_lesions"),
                "imaging_studies",
                latest_psma.get("study_date"),
                "captured",
            ) if isinstance(latest_psma.get("findings"), dict) else None,
            _assessment_candidate("psma_negative_dominant_lesions"),
        ],
        formatter=_yes_no,
        drives_eligibility=True,
    )

    sequencing_items = [
        _resolved_item(
            label="Número de línea terapéutica",
            field_name="line_of_therapy_number",
            candidates=[
                _verified_candidate("line_of_therapy_number") or _verified_candidate("line_of_therapy"),
                _visit_candidate("line_of_therapy_number") or _visit_candidate("line_of_therapy"),
                _candidate(
                    latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy"),
                    "treatment_history",
                    latest_treatment.get("start_date"),
                    "captured",
                ) if _is_present(latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy")) else None,
                _assessment_candidate("line_of_therapy_number") or _assessment_candidate("line_of_therapy"),
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Contexto clínico de la línea",
            field_name="line_of_therapy_context",
            candidates=[
                _verified_candidate("line_of_therapy_context"),
                _visit_candidate("line_of_therapy_context"),
                _candidate(
                    LINE_CONTEXT_LABELS.get(str(latest_treatment.get("line_of_therapy_context") or ""), latest_treatment.get("line_of_therapy_context")),
                    "treatment_history",
                    latest_treatment.get("start_date"),
                    "captured",
                ) if _is_present(latest_treatment.get("line_of_therapy_context")) else None,
                _candidate(
                    LINE_CONTEXT_LABELS.get(str(payload.get("line_of_therapy_context") or ""), payload.get("line_of_therapy_context")),
                    "assessment modular",
                    raw_assessment.get("assessment_date"),
                    "captured",
                ) if _is_present(payload.get("line_of_therapy_context")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Esquema actual",
            field_name="drug_scheme",
            candidates=[
                _verified_candidate("drug_scheme"),
                _visit_candidate("drug_scheme"),
                _candidate(latest_treatment.get("drug_scheme"), "treatment_history", latest_treatment.get("start_date"), "captured") if _is_present(latest_treatment.get("drug_scheme")) else None,
                _candidate(latest_followup.get("current_treatment"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("current_treatment")) else None,
                _assessment_candidate("drug_scheme"),
                _candidate(latest_signal_snapshot.get("recommended_option"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(latest_signal_snapshot.get("recommended_option")) else None,
            ],
            formatter=regimen_label,
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Contexto actual de ADT",
            field_name="current_adt_context",
            candidates=[
                _verified_candidate("current_adt_context"),
                _visit_candidate("current_adt_context"),
                _assessment_candidate("current_adt_context"),
                _candidate(inferred_payload.get("current_adt_context"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("current_adt_context")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Estado de castración",
            field_name="castrate_testosterone_status",
            candidates=[
                _verified_candidate("castrate_testosterone_status"),
                _visit_candidate("castrate_testosterone_status"),
                _assessment_candidate("castrate_testosterone_status"),
                _candidate(inferred_payload.get("castrate_testosterone_status"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("castrate_testosterone_status")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Patrón de progresión",
            field_name="progression_pattern",
            candidates=[
                _verified_candidate("progression_pattern"),
                _visit_candidate("progression_pattern"),
                _candidate((patient.get("response_assessments") or [{}])[0].get("response_category"), "response_assessments", (patient.get("response_assessments") or [{}])[0].get("assessment_date"), "captured") if patient.get("response_assessments") else None,
                _assessment_candidate("progression_pattern"),
                _candidate(inferred_payload.get("progression_pattern"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("progression_pattern")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Imagen convencional / PSMA",
            field_name="conventional_imaging_status",
            candidates=[
                _verified_candidate("conventional_imaging_status"),
                _visit_candidate("conventional_imaging_status"),
                _candidate((latest_imaging.get("findings") or {}).get("conventional_imaging_status"), "imaging_studies", latest_imaging.get("study_date"), "captured") if isinstance(latest_imaging.get("findings"), dict) else None,
                _assessment_candidate("conventional_imaging_status"),
                _candidate(inferred_payload.get("conventional_imaging_status"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("conventional_imaging_status")) else None,
            ],
            drives_eligibility=True,
        ),
    ]

    bone_bundle_complete = all(
        _truthy(
            _first_nonempty(
                latest_visit_payload.get(field),
                latest_followup.get(field),
                payload.get(field),
                baseline.get(field),
            )
        )
        for field in ("dxa_baseline_done", "calcium_vitd_started", "bone_protection_started")
    )

    safety_items = [
        _resolved_item(
            label="ECOG",
            field_name="ecog",
            candidates=[
                _verified_candidate("ecog"),
                _visit_candidate("ecog"),
                _candidate(latest_followup.get("ecog_current"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("ecog_current")) else None,
                _candidate(baseline.get("ecog_score"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("ecog_score")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Fragilidad / fitness",
            field_name="frailty_status",
            candidates=[
                _verified_candidate("frailty_status"),
                _visit_candidate("frailty_status"),
                _candidate((fitness.get("frailty") or {}).get("status"), "therapeutic_fitness", latest_followup.get("visit_date"), "captured") if _is_present((fitness.get("frailty") or {}).get("status")) else None,
                _candidate(latest_followup.get("frailty_status"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("frailty_status")) else None,
                _candidate(baseline.get("frailty_status"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("frailty_status")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Child-Pugh / riesgo hepático",
            field_name="child_pugh_score",
            candidates=[
                _verified_candidate("child_pugh_score"),
                _visit_candidate("child_pugh_score"),
                _candidate((fitness.get("child_pugh") or {}).get("grade"), "therapeutic_fitness", latest_followup.get("visit_date"), "captured") if _is_present((fitness.get("child_pugh") or {}).get("grade")) else None,
                _assessment_candidate("child_pugh_score"),
                _candidate(baseline.get("child_pugh_score"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("child_pugh_score")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Riesgo CV documentado",
            field_name="cv_risk_documented",
            candidates=[
                _verified_candidate("cv_risk_documented"),
                _visit_candidate("cv_risk_documented"),
                _candidate(latest_followup.get("cv_risk_status"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("cv_risk_status")) else None,
                _candidate((adt_effects.get("cv_risk") or {}).get("risk_category"), "adt_side_effects", latest_followup.get("visit_date"), "captured") if _is_present((adt_effects.get("cv_risk") or {}).get("risk_category")) else None,
            ],
            formatter=lambda value: value if str(value).lower() in {"alto", "intermedio", "bajo"} else _yes_no(value),
            drives_eligibility=False,
        ),
        # EPIC 9 Group A (GAPs 1,2,3) — exposición oficial del bundle
        # cardiológico/geriátrico que discrimina molécula ARPI en mHSPC/mCRPC:
        # edad (STAMPEDE >75 subanálisis), QTc (ENZAMET FDA §5.4), NYHA y LVEF
        # (COU-AA-302 excluyó NYHA III/IV).
        _resolved_item(
            label="Edad (discriminador ARPI)",
            field_name="patient_age",
            candidates=[
                _verified_candidate("patient_age"),
                _visit_candidate("patient_age"),
                _assessment_candidate("patient_age"),
                _visit_candidate("age"),
                _assessment_candidate("age"),
                _candidate(baseline.get("age"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("age")) else None,
            ],
            formatter=lambda value: f"{_safe_int(value) or value} años" if _is_present(value) else "No documentada",
            drives_eligibility=True,
        ),
        _resolved_item(
            label="QTc basal",
            field_name="qtc_baseline_ms",
            candidates=[
                _verified_candidate("qtc_baseline_ms"),
                _visit_candidate("qtc_baseline_ms"),
                _assessment_candidate("qtc_baseline_ms"),
                _verified_candidate("qtc_ms"),
                _visit_candidate("qtc_ms"),
                _assessment_candidate("qtc_ms"),
            ],
            formatter=lambda value: f"{_safe_float(value):.0f} ms" if _safe_float(value) is not None else str(value),
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Clase funcional NYHA",
            field_name="nyha_class",
            candidates=[
                _verified_candidate("nyha_class"),
                _visit_candidate("nyha_class"),
                _assessment_candidate("nyha_class"),
            ],
            formatter=lambda value: f"NYHA {value}" if value and str(value).upper() in {"I", "II", "III", "IV"} else str(value or ""),
            drives_eligibility=True,
        ),
        _resolved_item(
            label="LVEF basal",
            field_name="lvef_percent",
            candidates=[
                _verified_candidate("lvef_percent"),
                _visit_candidate("lvef_percent"),
                _assessment_candidate("lvef_percent"),
            ],
            formatter=lambda value: f"{_safe_float(value):.0f} %" if _safe_float(value) is not None else str(value),
            drives_eligibility=True,
        ),
        {
            "label": "Bundle óseo",
            "field_name": "bone_bundle",
            "value": "Completo" if bone_bundle_complete else "Incompleto",
            "detail": _source_badge(
                "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
                latest_stage_visit.get("visit_date") or latest_followup.get("visit_date"),
            ) + f" · {'capturado' if bone_bundle_complete else 'faltante'}",
            "source_label": "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
            "source_date": latest_stage_visit.get("visit_date") or latest_followup.get("visit_date") or "",
            "evidence_status": "captured" if bone_bundle_complete else "missing",
            "drives_eligibility": False,
        },
        _resolved_item(
            label="Interacciones y overlays",
            field_name="ddi_review_status",
            candidates=[
                _verified_candidate("ddi_review_status"),
                _visit_candidate("ddi_review_status"),
                _verified_candidate("drug_interaction_reviewed"),
                _visit_candidate("drug_interaction_reviewed"),
                _candidate(
                    f"{len(ddi.get('interactions') or [])} interacciones activas" if ddi.get("has_interactions") else "",
                    "ddi_review",
                    latest_followup.get("visit_date"),
                    "captured",
                ) if ddi else None,
                _candidate((patient.get("care_overlays") or [{}])[0].get("title"), "care_overlays", latest_followup.get("visit_date"), "captured") if patient.get("care_overlays") else None,
            ],
            default="Sin alertas destacadas",
            drives_eligibility=False,
        ),
    ]

    biomarker_items = [
        hrr_item,
        msi_item,
        psma_item,
        psma_negative_item,
        _resolved_item(
            label="Elegibilidad molecular destacada",
            field_name="precision_signal",
            candidates=[
                _candidate((precision.get("ar_v7") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
                _candidate((precision.get("pten") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
                _candidate((precision.get("cdk12") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
            ],
            default="Sin disparador molecular activo",
            drives_eligibility=False,
        ),
    ]

    def _panel_meta(items: list[dict[str, Any]], title: str, bullets: list[str], source_hints: list[str]) -> dict[str, Any]:
        sources = [item.get("source_label") for item in items if item.get("source_label")]
        updated_at = _first_nonempty(*(item.get("source_date") for item in items if item.get("source_date")))
        return {
            "title": title,
            "updated_at": updated_at,
            "sources": list(dict.fromkeys(sources or source_hints)),
            "items": items,
            "bullets": bullets,
        }

    sequencing_missing = [
        item.get("field_name")
        for item in sequencing_items
        if item.get("evidence_status") in {"missing", "inferred"} and item.get("drives_eligibility")
    ]
    biomarker_missing = [
        item.get("field_name")
        for item in biomarker_items
        if item.get("evidence_status") in {"missing", "inferred"} and item.get("drives_eligibility")
    ]
    safety_missing = [
        item.get("field_name")
        for item in safety_items
        if item.get("evidence_status") == "missing" and item.get("field_name")
    ]

    context = {
        "sequencing_context": _panel_meta(
            sequencing_items,
            "Secuenciación sistémica actual",
            [item.get("name") for item in raw_result.get("eligible_treatments", [])[:3]],
            ["stage_visit_records", "treatment_history", "inferencia longitudinal"],
        ),
        "biomarker_context": _panel_meta(
            biomarker_items,
            "Biomarcadores y elegibilidad terapéutica",
            _as_list(display_result.get("decision_changing_inputs"))[:4],
            ["verified_document_facts", "genomic_profile", "imaging_studies"],
        ),
        "safety_support_context": _panel_meta(
            safety_items,
            "Seguridad y soporte concurrente",
            [overlay.get("title") for overlay in patient.get("care_overlays", [])[:3]],
            ["follow_up_visits", "therapeutic_fitness", "adt_side_effects", "ddi_review"],
        ),
    }
    return context, {
        "sequencing_context": sequencing_missing,
        "biomarker_context": biomarker_missing,
        "safety_support_context": safety_missing,
    }


def _advanced_panels(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    raw_result: dict[str, Any],
    display_result: dict[str, Any],
    copilot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    context, missing_inputs = _build_advanced_panel_context(patient, raw_assessment, raw_result, display_result, copilot)
    panels = []
    subtitles = {
        "sequencing_context": "Dónde está parado el paciente hoy y qué trayectorias siguen abiertas.",
        "biomarker_context": "Información accionable que hoy ordena PARP, inmunoterapia, PSMA y secuenciación.",
        "safety_support_context": "Capas que cambian aptitud terapéutica, seguridad y soporte longitudinal.",
    }
    for key in ("sequencing_context", "biomarker_context", "safety_support_context"):
        entry = context.get(key) or {}
        panels.append(
            {
                "title": entry.get("title"),
                "subtitle": subtitles.get(key, ""),
                "items": entry.get("items", []),
                "bullets": entry.get("bullets", []),
                "sources": entry.get("sources", []),
                "updated_at": entry.get("updated_at", ""),
                "missing_inputs": missing_inputs.get(key, []),
                "display_missing_inputs": _displayize_field_list(missing_inputs.get(key, []), limit=8),
            }
        )
    return panels, context, missing_inputs


def _copilot_orientation_panel(copilot_modifiers: dict[str, Any]) -> dict[str, Any] | None:
    modifiers = copilot_modifiers.get("active_modifiers") or []
    if not modifiers:
        return None
    return {
        "title": "Modificadores activos del copilot",
        "subtitle": "Capas paralelas ya integradas que hoy cambian intensidad, seguridad o priorización clínica.",
        "items": [
            {
                "label": item.get("label", "Modificador"),
                "value": item.get("detail", ""),
                "detail": (
                    "Alta prioridad" if item.get("tone") == "danger"
                    else "Vigilancia reforzada" if item.get("tone") == "warning"
                    else "Accionable" if item.get("tone") == "success"
                    else "Contexto clínico"
                ),
            }
            for item in modifiers[:4]
        ],
        "bullets": _merge_unique_text(
            copilot_modifiers.get("what_could_change_course", []),
            copilot_modifiers.get("next_actions", []),
            limit=5,
        ),
    }


def _build_stage_specific_panels(
    *,
    patient: dict[str, Any],
    state: str,
    raw_assessment: dict[str, Any],
    display_assessment: dict[str, Any],
    copilot_modifiers: dict[str, Any] | None = None,
    localized_modality_fitness_bundle: dict[str, Any] | None = None,
    localized_tradeoff_bundle: dict[str, Any] | None = None,
    patient_priority_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    if state in DIAGNOSTIC_STATES:
        panels = _diagnostic_panel(patient, raw_assessment)
    elif state in LOCALIZED_STATES:
        panels = _localized_panels(
            patient,
            raw_assessment,
            display_result,
            raw_result,
            localized_modality_fitness_bundle=localized_modality_fitness_bundle,
            localized_tradeoff_bundle=localized_tradeoff_bundle,
            patient_priority_profile=patient_priority_profile,
        )
    elif state in POSTLOCAL_STATES:
        panels = _postlocal_panels(patient, raw_assessment, display_result)
    elif state in ADVANCED_STATES:
        panels, _, _ = _advanced_panels(patient, raw_assessment, raw_result, display_result)
    else:
        panels = []
    modifier_panel = _copilot_orientation_panel(copilot_modifiers or {})
    if modifier_panel:
        panels.append(modifier_panel)
    return panels


def _segment(label: str, value: Any, tone: str) -> dict[str, Any]:
    number = max(0.0, min(100.0, _safe_float(value) or 0.0))
    return {"label": label, "value": number, "display": f"{number:.1f}%", "tone": tone}


def _algorithm_panel_entry(raw_algorithm: dict[str, Any], display_algorithm: dict[str, Any], stage: str) -> dict[str, Any]:
    key = raw_algorithm.get("key")
    result_snapshot = raw_algorithm.get("result_snapshot", {}) or {}
    algorithm_meta = ALGORITHM_EXPLANATIONS.get(key, {})
    missing_inputs = list(dict.fromkeys((raw_algorithm.get("inputs_missing") or []) + (result_snapshot.get("missing_inputs") or [])))
    inputs_used = result_snapshot.get("inputs_used") or raw_algorithm.get("inputs_used") or []
    if isinstance(inputs_used, dict):
        inputs_used = [f"{field}: {value}" for field, value in inputs_used.items() if _is_present(value)]
    panel = {
        "name": display_algorithm.get("name") or raw_algorithm.get("name"),
        "status": display_algorithm.get("status") or raw_algorithm.get("status"),
        "summary": display_algorithm.get("summary") or raw_algorithm.get("summary"),
        "clinical_use": display_algorithm.get("clinical_use") or raw_algorithm.get("clinical_use"),
        "evidence_note": display_algorithm.get("evidence_note") or raw_algorithm.get("evidence_note"),
        "source_label": raw_algorithm.get("source_label", ""),
        "source_url": raw_algorithm.get("source_url", ""),
        "visual_type": "external_result",
        "primary_metric": None,
        "bars": [],
        "segments": [],
        "threshold": None,
        "details": [],
        "what_score_means": result_snapshot.get("what_score_means") or algorithm_meta.get("what_score_means") or "",
        "risk_interpretation": result_snapshot.get("risk_interpretation") or algorithm_meta.get("risk_interpretation") or "",
        "inputs_used": inputs_used,
        "display_inputs_used": _displayize_input_facts(inputs_used, limit=8),
        "missing_inputs": missing_inputs,
        "display_missing_inputs": _displayize_field_list(missing_inputs, limit=8),
        "data_truth_status": result_snapshot.get("data_truth_status") or ("incomplete" if missing_inputs else "captured"),
        "clinical_decision_supported": result_snapshot.get("clinical_decision_supported") or algorithm_meta.get("clinical_decision_supported") or display_algorithm.get("clinical_use") or "",
    }
    if key == "capra":
        panel["visual_type"] = "score_band"
        panel["primary_metric"] = {
            "label": "CAPRA",
            "value": f"{result_snapshot.get('score', '0')}/{result_snapshot.get('max_score', '10')}",
            "detail": result_snapshot.get("risk_group", "No documentado"),
        }
        panel["bars"] = [
            _segment("Libre de BCR a 3 años", str(result_snapshot.get("bcr_free_3y", "0")).replace("%", ""), "cyan"),
            _segment("Libre de BCR a 5 años", str(result_snapshot.get("bcr_free_5y", "0")).replace("%", ""), "emerald"),
        ]
    elif key == "briganti":
        risk = _safe_float(result_snapshot.get("probabilidad_raw") or str(result_snapshot.get("probabilidad_lni", "0")).replace("%", ""))
        panel["visual_type"] = "gauge"
        panel["primary_metric"] = {
            "label": "Riesgo ganglionar",
            "value": _format_pct(risk),
            "detail": result_snapshot.get("eplnd_texto", ""),
        }
        panel["bars"] = [_segment("LNI estimado", risk, "amber")]
        panel["threshold"] = {"label": result_snapshot.get("umbral", "Umbral clínico"), "value": 5}
    elif key == "partin":
        panel["visual_type"] = "stacked"
        panel["segments"] = [
            _segment("Órgano confinado", result_snapshot.get("oc_prob"), "emerald"),
            _segment("ECE", result_snapshot.get("ece_prob"), "amber"),
            _segment("SVI", result_snapshot.get("svi_prob"), "orange"),
            _segment("LNI", result_snapshot.get("lni_prob"), "rose"),
        ]
    elif key == "mskcc_preop":
        probability = _safe_float(result_snapshot.get("probabilidad_raw") or str(result_snapshot.get("probabilidad_organo_confinado", "0")).replace("%", ""))
        panel["visual_type"] = "gauge"
        panel["primary_metric"] = {
            "label": "Órgano confinado",
            "value": _format_pct(probability),
            "detail": result_snapshot.get("interpretacion", ""),
        }
        panel["bars"] = [_segment("Probabilidad preoperatoria", probability, "cyan")]
    elif key == "capra_s":
        panel["visual_type"] = "score_band"
        panel["primary_metric"] = {
            "label": "CAPRA-S",
            "value": f"{result_snapshot.get('score', '0')}/{result_snapshot.get('max_score', '12')}",
            "detail": result_snapshot.get("risk_group", "No documentado"),
        }
    elif key == "predict_prostate":
        panel["visual_type"] = "readiness"
        panel["details"] = panel["display_missing_inputs"]
    elif raw_algorithm.get("integration_mode") == "external_result":
        panel["visual_type"] = "external_result"
        snapshot = raw_algorithm.get("result_snapshot", {})
        classifier = snapshot.get("classifier") or display_algorithm.get("name") or raw_algorithm.get("name")
        result_text = snapshot.get("result") or snapshot.get("decipher_risk") or display_algorithm.get("status")
        panel["primary_metric"] = {
            "label": classifier,
            "value": result_text,
            "detail": "Resultado externo documentado",
        }
    elif stage in DIAGNOSTIC_STATES:
        panel["visual_type"] = "readiness"
        panel["details"] = panel["display_missing_inputs"]
    return panel


def _build_algorithm_panels(
    *,
    state: str,
    raw_assessment: dict[str, Any],
    display_assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_algorithms = raw_result.get("validated_algorithms", []) or []
    display_algorithms = display_result.get("validated_algorithms", []) or []
    panels = [
        _algorithm_panel_entry(raw_algorithm, display_algorithm, state)
        for raw_algorithm, display_algorithm in zip(raw_algorithms, display_algorithms)
    ]
    if state in ADVANCED_STATES:
        panels = [panel for panel in panels if panel["visual_type"] == "external_result"]
    return panels


def _dedupe_pivotal_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(matches, key=lambda item: (str(item.get("evaluation_date", "")), int(item.get("id", 0))), reverse=True)
    deduped = []
    seen = set()
    for item in ordered:
        study_name = item.get("study_name")
        if not study_name or study_name in seen:
            continue
        seen.add(study_name)
        deduped.append(item)
    return deduped


def _normalize_pivotal_match(match: dict[str, Any]) -> dict[str, Any]:
    details = _parse_json_blob(match.get("eligibility_details"), {})
    normalized = dict(match)
    normalized["eligible"] = bool(match.get("eligible"))
    normalized["match_score"] = _safe_float(details.get("match_score"))
    normalized["criteria_met"] = details.get("criteria_met", [])
    normalized["criteria_failed"] = details.get("criteria_failed", [])
    backbone_bundle = details.get("recommended_trial_backbone") or trial_backbone(match.get("study_name"))
    if isinstance(backbone_bundle, dict):
        normalized.update(
            {
                "recommended_trial_backbone": backbone_bundle.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": backbone_bundle.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_source": backbone_bundle.get("recommended_trial_backbone_source", ""),
                "recommended_trial_backbone_note": backbone_bundle.get("recommended_trial_backbone_note", ""),
                "recommended_trial_backbone_description": backbone_bundle.get("recommended_trial_backbone_description", ""),
                "recommended_trial_backbone_dose": backbone_bundle.get("recommended_trial_backbone_dose", ""),
                "recommended_trial_backbone_route": backbone_bundle.get("recommended_trial_backbone_route", ""),
                "recommended_trial_backbone_schedule": backbone_bundle.get("recommended_trial_backbone_schedule", ""),
                "recommended_trial_backbone_duration": backbone_bundle.get("recommended_trial_backbone_duration", ""),
                "recommended_trial_backbone_total_dose_gy": backbone_bundle.get("recommended_trial_backbone_total_dose_gy", ""),
                "recommended_trial_backbone_fractions": backbone_bundle.get("recommended_trial_backbone_fractions", ""),
            }
        )
    return normalized


def _build_triplet_decision_for_profile(
    *,
    state: str,
    raw_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    if not is_mhspc_state(state):
        return {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    payload = dict((raw_assessment or {}).get("input_snapshot", {}) or {})
    existing = dict(raw_result.get("triplet_decision") or raw_result.get("triplet_decision_card") or {})
    if existing:
        existing_state = resolve_mhspc_state(str(existing.get("state") or state), payload)
        requested_state = resolve_mhspc_state(state, payload)
        if existing_state == requested_state:
            return existing
    if existing:
        payload = {
            **payload,
            "volume_disease": payload.get("volume_disease") or "High" if "high_volume" in state else payload.get("volume_disease"),
        }
    return build_triplet_decision(
        state,
        payload,
        docetaxel_bundle=raw_result.get("docetaxel_fitness"),
    )


# ── Faubot 2026-04-25 (VIII) — UI card pivotal_contraindication_gates ─


def _lazy_evaluate_pivotal_gates_for_patient(
    patient: dict[str, Any],
) -> list[dict[str, Any]]:
    """EPIC GVP.E (FAUBOT CXLII) — Lazy-evaluate gates si raw_assessment
    no los proveyó. Cierra el bug de propagación que provocaba
    gate_omitted:* en GodiBot review.

    Reutiliza el mismo path que GodiBot usa internamente:
        evaluate_all_yaml_gates(payload) + evaluate_pivotal_contraindication_gates

    Args:
        patient: full patient record (con baseline + biomarker + treatments)

    Returns:
        list de gate dicts con shape compatible con result_snapshot
        .pivotal_contraindication_gates (code + severity + message +
        evidence_tag + trial_refs)
    """
    triggered: list[dict[str, Any]] = []

    # Build payload aplanado para gates eval (mismo patrón que GodiBot
    # _build_gates_payload — replicamos aquí para evitar circular import)
    baseline = dict(patient.get("baseline") or {})
    latest_followup = (
        (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {}
    )
    payload = {
        **baseline,
        **(latest_followup or {}),
        "ecog_score": (latest_followup or {}).get("ecog_current")
                       or baseline.get("ecog_score"),
        "hrr_status": baseline.get("hrr_status"),
        "hrr_gene": baseline.get("hrr_gene"),
        "current_medications": (
            patient.get("current_medications")
            or baseline.get("current_medications")
        ),
        "histology_subtype": baseline.get("histology_subtype"),
    }
    # Eliminar None values para evitar interferencia en evaluación
    payload = {k: v for k, v in payload.items() if v is not None}

    # Eval YAML gates (103+ centralizados)
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import evaluate_all_yaml_gates
        triggered.extend(evaluate_all_yaml_gates(payload) or [])
    except Exception as exc:
        logger.debug("evaluate_all_yaml_gates lazy eval failed: %s", exc)

    # Eval Python detectors (los 18 históricos + extensions)
    try:
        from prostanet.shared.pivotal_contraindication_gates import (
            evaluate_pivotal_contraindication_gates,
        )
        triggered.extend(evaluate_pivotal_contraindication_gates(payload) or [])
    except Exception as exc:
        logger.debug("evaluate_pivotal_contraindication_gates lazy eval failed: %s", exc)

    # Dedup por code (lo mismo gate puede venir desde ambos paths)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for g in triggered:
        if not isinstance(g, dict):
            continue
        code = str(g.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(g)
    return unique


def _build_pivotal_contraindication_gates_panel(
    raw_assessment: dict[str, Any] | None,
    patient: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye el panel UI de los gates pivotal disparados por el paciente.

    Faubot 2026-04-25 (VIII) — Hace visible al clínico la cadena de
    razonamiento (CÓMO + POR QUÉ) que hasta ahora vivía oculta en el
    `result_snapshot.pivotal_contraindication_gates`. Replica el patrón
    de `_build_pivotal_panel` pero adaptado al rastro estructurado de
    los 18 gates centralizados.

    Faubot 2026-04-25 (XVII) — Extensión cross-alert badges por gate:
    cada gate ahora se enriquece con su lista de DDI cross-alerts (si
    `current_medications` está poblado en el input_snapshot). Cierra
    100% la dimensión CÓMO al traer el razonamiento cruzado al perfil
    individual del paciente, sin necesidad de consultar el dashboard
    poblacional o el endpoint `/api/decision-audit/`.

    Cada gate viene del backend con: code, severity, message, evidence_tag,
    trial_refs. El panel agrupa por:
      - severity (hard_block, soft, etc.)
      - clase farmacológica deducida del code prefix:
          * radium223_*    → "Radio-223"
          * lutetium177_*  → "Lutetium-177-PSMA"
          * parp_inhibitor_* → "PARP inhibitors"
          * qtc_*, lvef_*, severe_heart_failure_*, uncontrolled_hypertension → "ARPI cardiotox"
          * resto → "Otros"

    Retorna un dict con métricas agregadas + lista enriquecida lista para
    Jinja:
      {
        "has_gates": bool,
        "total": int,
        "hard_block_count": int,
        "by_class": {clase: count, ...},
        "gates": [{code, severity, message, evidence_tag, trial_refs,
                   class_label, severity_color,
                   # Faubot XVII:
                   cross_alerts: [{drug_a, drug_b, severity, category,
                                   action, reference, message, color}],
                   has_cross_alerts: bool,
                   meds_capture_gap: bool,
                   cross_alerts_count: int}, ...],
        "summary_text": str,
        # Faubot XVII — Métricas agregadas:
        "total_cross_alerts": int,
        "gates_with_cross_alerts_count": int,
        "meds_capture_gap_count": int,
        "has_medications_captured": bool,
      }
    """
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    raw_gates = list(raw_result.get("pivotal_contraindication_gates") or [])

    # EPIC GVP.E FIX (FAUBOT CXLII): si raw_assessment no tiene gates
    # (paciente nuevo, snapshot incompleto, o clinical_decision_agent no
    # corrió aún), hacer lazy-eval para que Compass UI muestre el mismo
    # rastro que GodiBot detectaría en re-evaluación. Cierra el bug
    # "gate_omitted:*" de los blocked_hard del baseline 92% Internal Validation.
    if not raw_gates and patient:
        try:
            raw_gates = _lazy_evaluate_pivotal_gates_for_patient(patient)
        except Exception as exc:
            logger.debug("GVP.E lazy-evaluate gates failed: %s", exc)
            raw_gates = []

    if not raw_gates:
        return {
            "has_gates": False,
            "total": 0,
            "hard_block_count": 0,
            "by_class": {},
            "gates": [],
            "summary_text": "Sin contraindicaciones pivote activas.",
            # Faubot XVII — defaults para forward-compat
            "total_cross_alerts": 0,
            "gates_with_cross_alerts_count": 0,
            "meds_capture_gap_count": 0,
            "has_medications_captured": False,
        }

    # Mapping clase farmacológica por prefix de gate code.
    def _classify(code: str) -> str:
        """Faubot 2026-04-25 (XXXVI / XLII) — Auditoría #45 + #45.1: extendido para
        cubrir los 11 gates añadidos en #38-#44 (gates 20-30). Cada gate
        nuevo recibe class_label específico para que el UI panel
        agrupe cards por categoría clínica clara.

        Faubot XLII (Auditoría #45.1) — añade class_labels para gates 29-30
        (olaparib_renal_dysfunction_grade3 + lutetium177_fatigue_grade3) que
        antes caían en class_label genérico (snake_case técnico para gate 29,
        prefix-match "Lu-177-PSMA" indiferenciado para gate 30). Los nuevos
        labels permiten al clínico identificar visualmente la dimensión
        safety afectada (renal vs fatigue) sin abrir devtools.
        """
        c = (code or "").lower()
        # Faubot XXXVI — Specific exact-matches MUST be checked BEFORE prefix matches
        # Gates 19+20 ARSI safety profile (specific differentiated)
        if c == "arsi_in_cognitive_decline_grade2":
            return "ARSI deterioro cognitivo"
        if c == "arsi_in_seizure_history_grade3":
            return "ARSI convulsiones"
        # Faubot XXVI — Gate 21 abiraterona hepatotox
        if c == "abiraterone_hepatotoxicity_grade3":
            return "Hepatotoxicidad abiraterona"
        # Faubot XXXIV — Gate 28 abiraterona adrenal axis
        if c == "abiraterone_adrenal_insufficiency":
            return "Adrenal axis abiraterona"
        # Faubot XXVII — Gate 24 docetaxel longitudinal
        if c == "docetaxel_neuropathy_longitudinal_grade2_post_4_cycles":
            return "Taxanes neuropathy longitudinal"
        # Faubot XXXIII — Gate 25 PI3K/AKT inhibitors
        if c == "ipatasertib_hyperglycemia_grade3":
            return "PI3K/AKT metabólico"
        # Faubot XXXIV — Gate 26 cabazitaxel hipersensibilidad histamine-mediated
        if c == "cabazitaxel_hypersensitivity_grade3":
            return "Hipersensibilidad cabazitaxel"
        # Faubot XXXIV — Gate 27 Ra-223 + FRAX score (BEFORE radium223_ prefix)
        if c == "radium223_high_fracture_risk_frax":
            return "Hueso (FRAX score)"
        # Faubot XLII (#45.1) — Gate 29 olaparib renal G3 (BEFORE general
        # creatinine_clearance_lt_30 que es para rucaparib gate 10)
        if c == "olaparib_renal_dysfunction_grade3":
            return "Renal olaparib (PROfound + Lynparza §2.3)"
        # Faubot XLII (#45.1) — Gate 30 Lu-177 fatigue G3 (BEFORE lutetium177_
        # prefix general, mismo patrón que gate 27 antes de radium223_ prefix)
        if c == "lutetium177_fatigue_grade3":
            return "Fatigue Lu-177 (VISION + Pluvicto §6)"
        # Faubot XLIII (#46) — Gate 31 enzalutamida cognitive elderly
        # (BEFORE qtc_/lvef_ prefixes para ARPI cardiotox; gate 31 NO empieza
        # con esos prefixes pero documentamos el orden defensivo)
        if c == "enzalutamide_cognitive_decline_elderly":
            return "Enzalutamida cognitive elderly (UCSF 2024 + Marcum JAMA Oncol)"
        # Faubot XLIV (#47) — Gate 32 darolutamida hepatotox G3 hepatocelular
        # (distinto del patrón colestásico de gate 21 abiraterona)
        if c == "darolutamide_hepatotoxicity_grade3":
            return "Hepatotox darolutamida (ARANOTE/ARASENS + Nubeqa §6)"
        # Faubot XLVII (#48) — Gate 33 niraparib caída rápida plt longitudinal
        # (BEFORE niraparib_ prefix general gates 22-23; este es signal
        # longitudinal vs gates 22-23 que son baseline absoluto)
        if c == "niraparib_thrombocytopenia_rapid_drop":
            return "Niraparib caída plt longitudinal (MAGNITUDE Chi NEJM 2023)"
        # Faubot XLVIII (#49) — Gate 34 docetaxel caída ANC longitudinal
        if c == "docetaxel_neutropenia_rapid_drop":
            return "Docetaxel caída ANC longitudinal (TAX-327 + STAMPEDE Arm C)"
        # Faubot XLIX (#56) — Gate 35 ARSI/abi VTE risk
        if c == "arsi_abiraterone_vte_risk_high":
            return "TEV ARSI/abiraterona (COU-AA-302 + LATITUDE + Klil-Drori 2019)"
        # Faubot L (#60) — Gate 36 triplete frailty G8
        if c == "triplete_frailty_g8_low":
            return "Triplete + frailty G8 ≤14 (PEACE-1/ARASENS elderly subset)"
        # Faubot LI (#53) — Gates 37+38 Sipuleucel-T immunoterapia
        if c == "sipuleucel_t_severe_irr":
            return "Sipuleucel-T IRR severo (IMPACT + Provenge §5.1)"
        if c == "sipuleucel_t_febrile_neutropenia_post_leukapheresis":
            return "Sipuleucel-T febrile neutropenia (IMPACT + Provenge §5.2)"
        # Faubot LIII (#50) — Gate 39 abiraterona ALP rise longitudinal colestásico
        if c == "abiraterone_alp_rapid_rise_longitudinal":
            return "ALP rise abiraterona longitudinal (LATITUDE + Zytiga §5.1)"
        # Faubot LIV (#51) — Gate 40 Lu-177 Hb drop longitudinal anemia
        # (BEFORE lutetium177_ prefix general gates 13-14)
        if c == "lutetium177_hb_rapid_drop_longitudinal":
            return "Hb drop Lu-177 longitudinal (VISION supplementary + Pluvicto §6)"
        # Faubot LV (#52) — Gate 41 cabazitaxel Hb drop longitudinal anemia
        if c == "cabazitaxel_hb_rapid_drop_longitudinal":
            return "Hb drop cabazitaxel longitudinal (TROPIC + CARD + Jevtana §6)"
        # Faubot LVI (#57) — Gate 42 apalutamida SJS/TEN (PRIMER gate
        # dermatológico del catálogo + PRIMER gate sin override por
        # contraindicación absoluta irreversible per Erleada §5.2)
        if c == "apalutamide_severe_rash_sjs_ten":
            return "SJS/TEN apalutamida (Erleada §5.2 + SPARTAN/TITAN)"
        # Faubot LVII (#54) — Gates 43-46 Checkpoint inhibitors irAE
        # (2da clase IO post Sipuleucel-T, KEYNOTE-365/921 + NCCN IO Toxicity 2024)
        if c == "checkpoint_inhibitor_pneumonitis_grade2_plus":
            return "Pneumonitis IO (KEYNOTE + NCCN §PNEU-1)"
        if c == "checkpoint_inhibitor_hepatitis_grade3_plus":
            return "Hepatitis IO (KEYNOTE/CheckMate + NCCN §HEP-1)"
        if c == "checkpoint_inhibitor_colitis_grade3_plus":
            return "Colitis IO (KEYNOTE/CheckMate + NCCN §GI-1)"
        if c == "checkpoint_inhibitor_endocrinopathy_new_onset":
            return "Endocrinopatías IO (KEYNOTE/Sznol + NCCN §END-1)"
        # Faubot LVIII (#62) — Gate 47 PSA flare ARPI (informacional/soft_warning)
        if c == "psa_flare_arpi_pseudoprogression":
            return "PSA flare ARPI (PCWG3 2016 — anti-misinterpretation)"
        # Faubot LIX (#58) — Gate 48 enzalutamida hyponatremia/SIADH
        # (PRIMER gate electrólitos críticos del catálogo)
        if c == "enzalutamide_hyponatremia_siadh":
            return "Hiponatremia/SIADH enzalutamida (PREVAIL+AFFIRM + Bartter-Schwartz)"
        # Faubot LX (#59) — Gate 49 abiraterona hipokalemia/pseudo-aldosteronismo
        # (SEGUNDO gate electrólitos críticos — completa eje Na+K)
        if c == "abiraterone_hypokalemia_grade3":
            return "Hipokalemia abiraterona (COU-AA-302+LATITUDE + pseudo-aldosteronismo CYP17)"
        # Faubot LXI (#64) — Gate 50 hipocalcemia EXTENDIDA bone-targeted
        # (extiende gate 12 Ra-223 a clase entera: bisfosfonatos+denosumab+Lu-177)
        if c == "bone_targeted_hypocalcemia_extended":
            return "Hipocalcemia bone-targeted EXTENDIDA (ASCO Bone Health 2024 + Henry/Fizazi 2011)"
        # Faubot LXII (#65) — Gate 51 ONJ post-bisfos+denosumab (AAOMS 2022)
        # (2do gate categoría bone-targeted post #64; reusa REGIMEN_CODES_BONE_TARGETED)
        if c == "bone_targeted_osteonecrosis_jaw":
            return "ONJ bone-targeted (AAOMS 2022 + ASCO Bone Health 2024)"
        # Faubot LXIII (#66) — Gate 52 PARP MDS/AML longitudinal emergente
        # (6° gate longitudinal del catálogo; cubre MDS/AML EMERGENTE
        # durante tratamiento PARPi vs gate 16 que cubre history pre-tx)
        if c == "parp_inhibitor_mds_aml_longitudinal":
            return "MDS/AML PARP longitudinal (MAGNITUDE+PROfound + WHO 2022)"
        # Faubot LXIV (#63A) — Gates 53/54/55 PSA Kinetics (post-RP/RT/m0CRPC)
        # 3 gates informacionales/anti-misinterpretation soft_warning
        if c == "psa_velocity_bcr_aggressive":
            return "BCR agresivo post-RP (Stephenson JCO 2009 + RTOG-9601)"
        if c == "psa_bounce_post_rt_pseudoprogression":
            return "PSA bounce post-RT (Crook IJROBP 2010 + Phoenix 2006 — anti-misinterpretation)"
        if c == "psa_doubling_time_progressive":
            return "PSADT progresivo m0CRPC → ARPI (SPARTAN/PROSPER/ARAMIS pivotal)"
        # Now general prefix matches (after specific exact matches above)
        if c.startswith("radium223_"):
            return "Radio-223"
        if c.startswith("lutetium177_"):
            return "Lu-177-PSMA"
        if c.startswith("parp_inhibitor_"):
            return "PARP inhibitors"
        # Faubot XXVI — Gates 22-23 niraparib específico (clase distinta de PARPi general)
        if c.startswith("niraparib_"):
            return "PARPi específico niraparib"
        # Faubot XIII-XIV — Gates 17, 18 ARPI cardiotox prefix-based
        if c.startswith("qtc_") or c.startswith("lvef_"):
            return "ARPI cardiotoxicidad"
        if c == "severe_heart_failure_nyha_iii_iv":
            return "Cardiotoxicidad genérica"
        if c == "uncontrolled_hypertension":
            return "Cardiotoxicidad genérica"
        if c == "uncontrolled_diabetes":
            return "Metabólicas"
        if c == "severe_neuropathy_grade3":
            return "Neurológicas"
        if c == "no_bone_protective_agent":
            return "Hueso"
        if c == "ecog_2_or_more_for_triplets":
            return "Performance status"
        if c == "creatinine_clearance_lt_30":
            return "Renal"
        if c.endswith("_hypersensitivity"):
            return "Hipersensibilidad"
        if c == "prior_arpi_exposure_mhspc":
            return "Exposición previa"
        return "Otros"

    def _severity_color(severity: str) -> str:
        # Tailwind classes para color-coding
        s = (severity or "").lower()
        if s == "hard_block":
            return "rose"  # rojo intenso
        if s == "soft":
            return "amber"
        if s == "high":
            return "orange"
        return "slate"

    # Faubot 2026-04-25 (XVII) — Pre-compute cross-alerts per gate.
    # Re-ejecutamos el cross-check con el input_snapshot para obtener
    # la lista de cross-alerts DDI por cada gate triggered. Si el input
    # no tiene `current_medications`/`concomitant_medications`, el
    # cross-check retorna vacío (sin falsos positivos).
    raw_input = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    cross_alerts_by_gate: dict[str, list[dict[str, Any]]] = {}
    has_meds_captured = False
    try:
        from prostanet.shared.gates_ddi_cross_check import (
            cross_check_gates_with_ddi,
        )
        from prostanet.shared.gates_coverage_aggregator import (
            _has_medications, _MEDICATION_FIELDS,
        )
        # Determinar si hay alguna medicación capturada (cualquiera de
        # los 3 alias `current_medications`/`concomitant_medications`/
        # `medications`).
        input_keys = {
            k for k, v in (raw_input or {}).items()
            if v not in (None, "", [], {})
        }
        has_meds_captured = _has_medications(input_keys, raw_input or {})
        # Ejecutar cross-check para todos los gates a la vez.
        all_cross = cross_check_gates_with_ddi(raw_gates, raw_input or {})
        for alert in all_cross:
            gc = str(alert.get("gate_code") or "")
            if not gc:
                continue
            cross_alerts_by_gate.setdefault(gc, []).append(alert)
    except ImportError:
        # Degradación graciosa: si los helpers no están disponibles,
        # el panel sigue funcionando sin DDI enrichment.
        pass

    def _ddi_severity_color(sev: str) -> str:
        s = (sev or "").lower()
        if s == "contraindicated":
            return "rose"
        if s == "major":
            return "orange"
        if s == "moderate":
            return "amber"
        return "slate"

    def _ddi_severity_label(sev: str) -> str:
        s = (sev or "").lower()
        return {
            "contraindicated": "Contraindicado",
            "major": "Mayor",
            "moderate": "Moderado",
        }.get(s, sev.title() if sev else "—")

    def _format_cross_alert(alert: dict[str, Any]) -> dict[str, Any]:
        """Normaliza un cross_alert para consumo Jinja."""
        ddi = alert.get("ddi_alert") or {}
        sev = str(alert.get("severity") or "")
        return {
            "drug_a": str(ddi.get("drug_a") or "—"),
            "drug_b": str(ddi.get("drug_b") or "—"),
            "category": str(alert.get("category") or "—"),
            "severity": sev,
            "severity_label": _ddi_severity_label(sev),
            "severity_color": _ddi_severity_color(sev),
            "mechanism": str(ddi.get("mechanism") or ""),
            "clinical_impact": str(ddi.get("clinical_impact") or ""),
            "action": str(ddi.get("recommended_action") or ""),
            "alternative": str(ddi.get("alternative") or ""),
            "reference": str(ddi.get("reference") or ""),
            "cross_message": str(alert.get("cross_message") or ""),
        }

    enriched: list[dict[str, Any]] = []
    by_class: dict[str, int] = {}
    hard_block_count = 0
    total_cross_alerts = 0
    gates_with_cross_alerts_count = 0
    meds_capture_gap_count = 0
    for gate in raw_gates:
        code = str(gate.get("code") or "")
        severity = str(gate.get("severity") or "")
        message = str(gate.get("message") or "")
        evidence_tag = str(gate.get("evidence_tag") or "")
        trial_refs = list(gate.get("trial_refs") or [])
        cls = _classify(code)
        by_class[cls] = by_class.get(cls, 0) + 1
        if severity == "hard_block":
            hard_block_count += 1
        # Faubot XVII — cross_alerts per gate
        gate_cross_alerts = [
            _format_cross_alert(a) for a in cross_alerts_by_gate.get(code, [])
        ]
        has_cross = len(gate_cross_alerts) > 0
        if has_cross:
            gates_with_cross_alerts_count += 1
            total_cross_alerts += len(gate_cross_alerts)
        # Meds capture gap: gate triggered + sin medicaciones capturadas
        meds_gap = not has_meds_captured
        if meds_gap:
            meds_capture_gap_count += 1
        # Faubot 2026-04-25 (LXXI) — Auditoría #65B
        # Per-gate evidence drill-down: enriquecer cada gate con URLs live
        # para PMID/NCT/DOI/trial_name + evidence_tag (NCCN/EAU). Reusa
        # _build_per_gate_evidence_drill_down de #65A backend.
        evidence_drill_down: dict[str, Any] = {}
        try:
            from prostanet.shared.decision_audit_builder import (
                _build_per_gate_evidence_drill_down,
            )
            evidence_drill_down = _build_per_gate_evidence_drill_down(gate)
        except Exception:
            # Defensive: si falla helper, no rompe panel UI
            evidence_drill_down = {
                "trial_refs_with_links": [],
                "evidence_tag_link": {},
                "citation_count": 0,
            }

        enriched.append({
            "code": code,
            "severity": severity,
            "severity_label": (
                "Bloqueo absoluto" if severity == "hard_block"
                else "Precaución" if severity == "soft"
                else severity.title() if severity else "—"
            ),
            "severity_color": _severity_color(severity),
            "message": message,
            "evidence_tag": evidence_tag,
            "trial_refs": trial_refs,
            "trial_refs_label": " · ".join(trial_refs) if trial_refs else "—",
            "class_label": cls,
            # Faubot XVII — DDI enrichment per gate
            "cross_alerts": gate_cross_alerts,
            "has_cross_alerts": has_cross,
            "cross_alerts_count": len(gate_cross_alerts),
            "meds_capture_gap": meds_gap,
            # Faubot LXXI #65B — Per-gate evidence drill-down
            "trial_refs_with_links": evidence_drill_down.get("trial_refs_with_links", []),
            "evidence_tag_link": evidence_drill_down.get("evidence_tag_link", {}),
            "citation_count": evidence_drill_down.get("citation_count", 0),
        })

    # Ordenar: hard_block primero, luego por clase
    enriched.sort(
        key=lambda g: (
            0 if g["severity"] == "hard_block" else 1,
            g["class_label"],
            g["code"],
        )
    )

    summary_parts: list[str] = []
    if hard_block_count:
        summary_parts.append(
            f"{hard_block_count} bloqueo{'s' if hard_block_count != 1 else ''} absoluto{'s' if hard_block_count != 1 else ''}"
        )
    other_count = len(enriched) - hard_block_count
    if other_count:
        summary_parts.append(f"{other_count} precaución/otra{'s' if other_count != 1 else ''}")
    # Faubot XVII — Append DDI summary
    if total_cross_alerts:
        summary_parts.append(
            f"{total_cross_alerts} alerta{'s' if total_cross_alerts != 1 else ''} DDI cruzada{'s' if total_cross_alerts != 1 else ''}"
        )
    summary_text = " · ".join(summary_parts) if summary_parts else "Sin contraindicaciones pivote activas."

    return {
        "has_gates": True,
        "total": len(enriched),
        "hard_block_count": hard_block_count,
        "by_class": by_class,
        "gates": enriched,
        "summary_text": summary_text,
        # Faubot XVII — Métricas DDI agregadas
        "total_cross_alerts": total_cross_alerts,
        "gates_with_cross_alerts_count": gates_with_cross_alerts_count,
        "meds_capture_gap_count": meds_capture_gap_count,
        "has_medications_captured": has_meds_captured,
    }


def _build_pivotal_panel(matches: list[dict[str, Any]], *, state: str = "") -> dict[str, Any]:
    normalized = [_normalize_pivotal_match(item) for item in _dedupe_pivotal_matches(matches)]
    hidden_cross_scenario = 0
    if is_mhspc_state(state):
        _, hidden_trials = visible_trials_for_mhspc_state(state, {})
        hidden_cross_scenario = sum(1 for item in normalized if str(item.get("study_name") or "") in hidden_trials)
        normalized = [item for item in normalized if str(item.get("study_name") or "") not in hidden_trials]
    elif state == "recurrence_bcr":
        hidden_cross_scenario = sum(
            1
            for item in normalized
            if str(item.get("study_name") or "") not in POST_RP_SALVAGE_TRIALS
        )
        normalized = [
            item
            for item in normalized
            if str(item.get("study_name") or "") in POST_RP_SALVAGE_TRIALS
        ]
    elif state == "post_radiotherapy_or_local_salvage":
        hidden_cross_scenario = sum(
            1
            for item in normalized
            if str(item.get("study_name") or "") in POST_RP_SALVAGE_TRIALS
        )
        normalized = [
            item
            for item in normalized
            if str(item.get("study_name") or "") not in POST_RP_SALVAGE_TRIALS
        ]
    eligible = [item for item in normalized if item.get("eligible")]
    partial = [item for item in normalized if not item.get("eligible") and (item.get("match_score") or 0) >= 0.7]
    ineligible = [item for item in normalized if item not in eligible and item not in partial]
    last_evaluated_at = _first_nonempty(normalized[0].get("evaluation_date") if normalized else "", "")
    return {
        "eligible_matches": eligible,
        "partial_matches": partial,
        "ineligible_matches": ineligible,
        "hidden_ineligible_count": len(ineligible),
        "eligible_count": len(eligible),
        "partial_count": len(partial),
        "ineligible_count": len(ineligible),
        "hidden_cross_scenario_count": hidden_cross_scenario,
        "last_evaluated_at": last_evaluated_at,
        "has_results": bool(normalized),
    }


def _scenario_for_state(state: str) -> str:
    if state in DIAGNOSTIC_STATES:
        return "localizado"
    if state == "localized_initial":
        return "localizado"
    if state == "post_prostatectomy":
        return "adyuvancia"
    if state == "recurrence_bcr":
        return "rescate"
    if state == "post_radiotherapy_or_local_salvage":
        return "post_rt_salvage"
    if state == "m0_crpc":
        return "nmCRPC"
    if state in {"m1_crpc"}:
        return "mCRPC"
    if state == "adt_progression_verification":
        return "verification"
    if state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"}:
        return "mHSPC"
    return ""


def _build_evidence_applicability(
    *,
    state: str,
    pivotal_panel: dict[str, Any],
    display_assessment: dict[str, Any],
) -> dict[str, Any]:
    scenario = _scenario_for_state(state)
    if state == "recurrence_bcr":
        current_recommendation = _first_nonempty(
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("titulo_clinico"),
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("label"),
            "Activar salvage y reestadificación dirigida",
        )
        all_matches = (
            list(pivotal_panel.get("eligible_matches") or [])
            + list(pivotal_panel.get("partial_matches") or [])
            + list(pivotal_panel.get("ineligible_matches") or [])
        )
        scenario_matches = [
            item for item in all_matches
            if str(item.get("study_name") or "") in POST_RP_SALVAGE_TRIALS
        ]
        supporting_trials = []
        strictly_eligible = []
        contextual_support = []
        not_eligible_for_this_case = []
        for match in scenario_matches:
            study_name = str(match.get("study_name") or "")
            is_eligible = bool(match.get("eligible"))
            criteria_met = (match.get("criteria_met") or [])[:3]
            criteria_failed = (match.get("criteria_failed") or [])[:3]
            if is_eligible:
                group_key = "strictly_eligible"
                status = "Aplicable"
                eligibility_rationale = (
                    f"Elegible porque cumple: {', '.join(criteria_met)}."
                    if criteria_met
                    else "Elegible por concordancia directa con el escenario post-RP de salvage."
                )
                clinical_takeaway = f"Puede respaldar la decisión activa: {current_recommendation}."
            elif study_name in POST_RP_CONTEXTUAL_SUPPORT_TRIALS:
                group_key = "contextual_support"
                status = "Contextual"
                if criteria_failed:
                    eligibility_rationale = (
                        f"Apoyo contextual: el estudio respalda la familia de salvage, aunque hoy no sea estrictamente elegible por {', '.join(criteria_failed)}."
                    )
                else:
                    eligibility_rationale = "Apoyo contextual para rescate temprano o reestadificación dirigida en recurrencia post-RP."
                clinical_takeaway = "Sustenta la estrategia de salvage temprano o la reestadificación dirigida, aunque no siempre equivalga a elegibilidad estricta actual."
            else:
                group_key = "not_eligible_for_this_case"
                status = "No elegible"
                eligibility_rationale = (
                    f"No elegible para este caso por: {', '.join(criteria_failed)}."
                    if criteria_failed
                    else "No elegible para este caso con los datos acumulados actuales."
                )
                clinical_takeaway = "No debe desplazar una ruta curativa local plausible sin justificar el cambio de escenario."
            card = {
                "study_name": study_name or "Estudio",
                "scenario": match.get("scenario", ""),
                "status": status,
                "group_key": group_key,
                "expected_outcome": match.get("expected_outcome") or match.get("key_result") or "",
                "criteria_met": criteria_met,
                "criteria_failed": criteria_failed,
                "match_score": match.get("match_score"),
                "applicability": match.get("applicability") or "",
                "decision_supported": current_recommendation,
                "eligibility_rationale": eligibility_rationale,
                "clinical_takeaway": clinical_takeaway,
                "evidence_strength": "Alta" if is_eligible else ("Contextual" if group_key == "contextual_support" else "No aplicable"),
                "recommended_trial_backbone": match.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": match.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_source": match.get("recommended_trial_backbone_source", ""),
                "recommended_trial_backbone_note": match.get("recommended_trial_backbone_note", ""),
                "recommended_trial_backbone_description": match.get("recommended_trial_backbone_description", ""),
                "recommended_trial_backbone_dose": match.get("recommended_trial_backbone_dose", ""),
                "recommended_trial_backbone_route": match.get("recommended_trial_backbone_route", ""),
                "recommended_trial_backbone_schedule": match.get("recommended_trial_backbone_schedule", ""),
                "recommended_trial_backbone_duration": match.get("recommended_trial_backbone_duration", ""),
                "recommended_trial_backbone_total_dose_gy": match.get("recommended_trial_backbone_total_dose_gy", ""),
                "recommended_trial_backbone_fractions": match.get("recommended_trial_backbone_fractions", ""),
            }
            if group_key == "strictly_eligible":
                strictly_eligible.append(card)
            elif group_key == "contextual_support":
                contextual_support.append(card)
            else:
                not_eligible_for_this_case.append(card)
        supporting_trials = strictly_eligible[:2] + contextual_support[:4]
        return {
            "scenario": scenario,
            "recommendation_label": current_recommendation,
            "eligible_count": len(strictly_eligible),
            "partial_count": len(contextual_support),
            "supporting_trials": supporting_trials,
            "strictly_eligible": strictly_eligible,
            "contextual_support": contextual_support,
            "not_eligible_for_this_case": not_eligible_for_this_case,
            "has_results": bool(scenario_matches),
            "gaps": _merge_unique_text([], [gap for card in supporting_trials for gap in (card.get("criteria_failed") or [])], limit=5),
            "summary": "La evidencia visible se restringe al carril post-RP salvage/BCR y separa elegibilidad estricta, apoyo contextual y estudios no elegibles hoy para este caso.",
        }
    if state == "post_radiotherapy_or_local_salvage":
        current_recommendation = _first_nonempty(
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("titulo_clinico"),
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("label"),
            "Ruta priorizada post-radioterapia / salvage local",
        )
        scenario_matches = (
            list(pivotal_panel.get("eligible_matches") or [])
            + list(pivotal_panel.get("partial_matches") or [])
            + list(pivotal_panel.get("ineligible_matches") or [])
        )
        prioritized = list(pivotal_panel.get("eligible_matches") or []) + list(pivotal_panel.get("partial_matches") or [])
        return {
            "scenario": scenario,
            "recommendation_label": current_recommendation,
            "eligible_count": len(pivotal_panel.get("eligible_matches") or []),
            "partial_count": len(pivotal_panel.get("partial_matches") or []),
            "supporting_trials": prioritized[:6],
            "strictly_eligible": list(pivotal_panel.get("eligible_matches") or []),
            "contextual_support": list(pivotal_panel.get("partial_matches") or []),
            "not_eligible_for_this_case": list(pivotal_panel.get("ineligible_matches") or []),
            "has_results": bool(scenario_matches),
            "gaps": _merge_unique_text([], [gap for item in prioritized for gap in (item.get("criteria_failed") or [])], limit=5),
            "summary": "La evidencia visible para post-RT debe leerse con Phoenix, confirmación local equivalente y reestadificación completa; no debe mezclarse con el carril post-RP salvage.",
        }
    if is_mhspc_state(state):
        current_recommendation = STATE_DISPLAY_MAP.get(state) or state
        scenario_matches = (
            list(pivotal_panel.get("eligible_matches") or [])
            + list(pivotal_panel.get("partial_matches") or [])
            + list(pivotal_panel.get("ineligible_matches") or [])
        )
        prioritized = list(pivotal_panel.get("eligible_matches") or []) + list(pivotal_panel.get("partial_matches") or [])
    else:
        current_recommendation = _first_nonempty(
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("titulo_clinico"),
            ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("label"),
            STATE_DISPLAY_MAP.get(state),
        )
        all_matches = (
            list(pivotal_panel.get("eligible_matches") or [])
            + list(pivotal_panel.get("partial_matches") or [])
            + list(pivotal_panel.get("ineligible_matches") or [])
        )
        scenario_matches = [item for item in all_matches if str(item.get("scenario", "")).lower() == scenario.lower()] if scenario else all_matches
        prioritized = [
            item for item in (list(pivotal_panel.get("eligible_matches") or []) + list(pivotal_panel.get("partial_matches") or []))
            if not scenario or str(item.get("scenario", "")).lower() == scenario.lower()
        ]
    applicability_cards = []
    for match in prioritized[:4]:
        is_eligible = bool(match.get("eligible"))
        criteria_met = (match.get("criteria_met") or [])[:3]
        criteria_failed = (match.get("criteria_failed") or [])[:3]
        decision_supported = current_recommendation
        eligibility_rationale = (
            f"Elegible porque cumple: {', '.join(criteria_met)}."
            if is_eligible and criteria_met
            else "Elegible por concordancia clínica global con el escenario actual."
            if is_eligible
            else f"Parcial porque aún faltan o fallan: {', '.join(criteria_failed)}."
            if criteria_failed
            else "Parcial por concordancia incompleta con el escenario actual."
        )
        applicability_cards.append(
            {
                "study_name": match.get("study_name", "Estudio"),
                "scenario": match.get("scenario", ""),
                "status": "Aplicable" if is_eligible else "Parcial",
                "expected_outcome": match.get("expected_outcome") or match.get("key_result") or "",
                "criteria_met": criteria_met,
                "criteria_failed": criteria_failed,
                "match_score": match.get("match_score"),
                "applicability": match.get("applicability") or "",
                "decision_supported": decision_supported,
                "eligibility_rationale": eligibility_rationale,
                "clinical_takeaway": (
                    f"Puede respaldar la recomendación actual: {decision_supported}."
                    if is_eligible
                    else "Aún no sostiene una decisión definitiva hasta resolver los gaps clínicos."
                ),
                "evidence_strength": "Alta" if is_eligible else "Condicionada",
                "recommended_trial_backbone": match.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": match.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_source": match.get("recommended_trial_backbone_source", ""),
                "recommended_trial_backbone_note": match.get("recommended_trial_backbone_note", ""),
                "recommended_trial_backbone_description": match.get("recommended_trial_backbone_description", ""),
                "recommended_trial_backbone_dose": match.get("recommended_trial_backbone_dose", ""),
                "recommended_trial_backbone_route": match.get("recommended_trial_backbone_route", ""),
                "recommended_trial_backbone_schedule": match.get("recommended_trial_backbone_schedule", ""),
                "recommended_trial_backbone_duration": match.get("recommended_trial_backbone_duration", ""),
                "recommended_trial_backbone_total_dose_gy": match.get("recommended_trial_backbone_total_dose_gy", ""),
                "recommended_trial_backbone_fractions": match.get("recommended_trial_backbone_fractions", ""),
            }
        )
    return {
        "scenario": scenario,
        "recommendation_label": current_recommendation,
        "eligible_count": sum(1 for item in scenario_matches if item.get("eligible")),
        "partial_count": sum(1 for item in scenario_matches if not item.get("eligible") and (item.get("match_score") or 0) >= 0.7),
        "supporting_trials": applicability_cards,
        "has_results": bool(scenario_matches),
        "gaps": _merge_unique_text([], [gap for card in applicability_cards for gap in (card.get("criteria_failed") or [])], limit=5),
        "summary": (
            "La evidencia se mantiene restringida hasta confirmar si el paciente realmente pertenece a mHSPC, nmCRPC o mCRPC."
            if scenario == "verification"
            else
            f"La recomendación actual se está contrastando con estudios pivotales del escenario {scenario}."
            if scenario
            else "La aplicabilidad de evidencia se está contrastando con los estudios pivotales disponibles."
        ),
    }


def _build_document_board(patient: dict[str, Any]) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.document_ingestion import document_label

    documents = list(patient.get("source_documents") or [])
    tasks_by_document = {
        item.get("document_id"): item
        for item in (patient.get("document_verification_tasks") or [])
        if item.get("document_id")
    }
    candidates_by_document: dict[int, list[dict[str, Any]]] = {}
    for candidate in patient.get("document_candidates") or []:
        candidates_by_document.setdefault(candidate.get("document_id"), []).append(candidate)
    verified_today = []
    for fact in (patient.get("verified_document_facts") or [])[:10]:
        clone = dict(fact)
        field_name = str(clone.get("field_name") or "").strip()
        clone["display_field_name"] = normalize_field_label(field_name, default=field_name or "Dato clínico")
        clone["display_fact_group"] = normalize_fact_group_label(clone.get("fact_group"))
        clone["display_value"] = _displayize_field_value(field_name, clone.get("value"))
        verified_today.append(clone)
    pending_documents = [
        {
            **item,
            "document_type_label": document_label(item.get("document_type", "")),
            "candidate_count": len(candidates_by_document.get(item.get("id"), [])),
            "task": tasks_by_document.get(item.get("id"), {}),
        }
        for item in documents
        if item.get("verification_status") != "verified"
    ]
    verified_documents = [
        {
            **item,
            "document_type_label": document_label(item.get("document_type", "")),
            "task": tasks_by_document.get(item.get("id"), {}),
        }
        for item in documents
        if item.get("verification_status") == "verified"
    ]
    latest_changes = []
    for item in verified_documents[:5]:
        summary = (item.get("task") or {}).get("summary", {})
        for change in summary.get("what_changed", [])[:2]:
            latest_changes.append(
                {
                    "document_title": item.get("title") or item.get("file_name"),
                    "change": change,
                    "verified_at": (item.get("task") or {}).get("verified_at") or item.get("updated_at"),
                    "updated_panels": summary.get("updated_panels", []),
                    "updated_decisions": summary.get("updated_decisions", []),
                    "created_or_closed_agenda_items": summary.get("created_or_closed_agenda_items", []),
                    "changed_recommendation": summary.get("changed_recommendation"),
                }
            )
    return {
        "documents": documents,
        "pending_documents": pending_documents,
        "verified_documents": verified_documents[:6],
        "verified_today": verified_today,
        "latest_changes": latest_changes[:6],
        "pending_count": len(pending_documents),
        "verified_count": len(verified_documents),
    }


def _build_longitudinal_sections(patient: dict[str, Any], state: str, display_assessment: dict[str, Any]) -> list[dict[str, Any]]:
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    sections = [
        {"key": "follow_ups", "title": "Visitas de seguimiento", "count": len(patient.get("follow_ups", [])), "default_open": False},
        {"key": "stage_visits", "title": "Bundles de visita por etapa", "count": len(patient.get("stage_visits", [])), "default_open": state in ADVANCED_STATES},
        {"key": "pros", "title": "Resultados reportados por el paciente", "count": len(patient.get("pros", [])), "default_open": False},
        {"key": "diagnostic_assets", "title": "Activos diagnósticos", "count": len(patient.get("diagnostic_plans", [])) + len(patient.get("mri_facts", [])) + len(patient.get("biopsy_triggers", [])), "default_open": state in DIAGNOSTIC_STATES},
        {"key": "biopsies", "title": "Biopsias y patología", "count": len(patient.get("biopsies", [])), "default_open": False},
        {"key": "benchmarking", "title": "Benchmarking", "count": len(display_result.get("benchmarking_flags", [])), "default_open": False},
        {"key": "provenance", "title": "Provenance clínica", "count": len(patient.get("data_provenance", [])), "default_open": False},
        {"key": "demographics", "title": "Demografía y cohorte", "count": len([item for item in (patient.get("demographics") or {}).values() if _is_present(item)]), "default_open": False},
    ]
    return sections


def _build_copilot_sections(patient: dict[str, Any], state: str, management_track: str, raw_assessment: dict[str, Any]) -> dict[str, Any]:
    """Build copilot clinical data: schedule, alerts, comorbidity scores, ADT side effects."""
    import logging
    copilot_logger = logging.getLogger(__name__)
    copilot: dict[str, Any] = {
        "schedule": [],
        "scheduled_encounters": [],
        "next_encounter": {},
        "overdue_alerts": [],
        "clinical_alerts": [],
        "comorbidity_scores": {},
        "adt_side_effects": None,
        "schedule_anchor_date": "",
        "schedule_anchor_source": "",
        "schedule_anchor_strength": "strong",
        "latest_response_assessment": {},
    }

    patient_id = patient.get("identity", {}).get("id")
    if not patient_id:
        return copilot

    identity = patient.get("identity", {})
    baseline = patient.get("baseline", {}) or {}
    prior = patient.get("prior_history", {}) or {}
    followups = patient.get("follow_ups", []) or []

    # ── Schedule ──
    try:
        import tracking_db

        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=management_track,
            horizon_months=12,
        )
        copilot["schedule"] = schedule_bundle.get("schedule", [])[:20]
        copilot["scheduled_encounters"] = schedule_bundle.get("scheduled_encounters", [])[:6]
        copilot["next_encounter"] = schedule_bundle.get("next_encounter", {})
        copilot["schedule_anchor_date"] = schedule_bundle.get("anchor_date", "")
        copilot["schedule_anchor_source"] = schedule_bundle.get("anchor_source", "")
        copilot["schedule_anchor_strength"] = schedule_bundle.get("schedule_anchor_strength", "strong")
        copilot["overdue_alerts"] = [
            item for item in (schedule_bundle.get("schedule") or [])
            if item.get("status") == "overdue" and not item.get("completed")
        ]
    except Exception as exc:
        copilot_logger.debug("Copilot schedule error: %s", exc)

    # ── Clinical alerts ──
    try:
        persisted_alerts = patient.get("alerts") or []
        if persisted_alerts:
            copilot["clinical_alerts"] = [dict(alert) for alert in persisted_alerts]
    except Exception as exc:
        copilot_logger.debug("Copilot alerts error: %s", exc)

    # ── Comorbidity scores (CCI, G8) ──
    try:
        from clinical_scores import charlson_comorbidity_index, g8_geriatric_assessment
        score_data: dict[str, Any] = {}
        score_data.update(identity)
        score_data.update(baseline)
        score_data.update(prior)
        copilot["comorbidity_scores"]["charlson"] = charlson_comorbidity_index(score_data)
        copilot["comorbidity_scores"]["g8"] = g8_geriatric_assessment(score_data)
    except Exception as exc:
        copilot_logger.debug("Copilot comorbidity error: %s", exc)

    # ── Therapeutic fitness (eGFR, Child-Pugh, frailty, fit score) ──
    try:
        from clinical_scores import egfr_ckd_epi_2021, child_pugh_dynamic, fried_frailty_index, competing_mortality_estimate, treatment_fit_score
        fitness_data: dict[str, Any] = {}
        fitness_data.update(identity)
        fitness_data.update(baseline)
        fitness_data.update(prior)
        if followups:
            fitness_data.update(followups[-1])

        fitness: dict[str, Any] = {"has_data": False}

        # eGFR
        creat = fitness_data.get("creatinine_current") or fitness_data.get("creatinine")
        pat_age = None
        try:
            pat_age = int(float(fitness_data.get("age") or fitness_data.get("edad") or 0))
        except (ValueError, TypeError):
            pass
        pat_sex = str(fitness_data.get("sex") or fitness_data.get("sexo") or "M")
        if creat and pat_age:
            try:
                fitness["egfr"] = egfr_ckd_epi_2021(float(creat), pat_age, pat_sex)
                fitness["has_data"] = True
            except (ValueError, TypeError):
                pass

        # Child-Pugh
        bili = fitness_data.get("bilirubin_current") or fitness_data.get("bilirubin")
        alb = fitness_data.get("albumin_current") or fitness_data.get("albumin")
        inr_val = fitness_data.get("inr_current") or fitness_data.get("inr")
        asc = str(fitness_data.get("ascites", "none"))
        enc = str(fitness_data.get("encephalopathy", "none"))
        try:
            cp = child_pugh_dynamic(
                bilirubin=float(bili) if bili else None,
                albumin=float(alb) if alb else None,
                inr=float(inr_val) if inr_val else None,
                ascites=asc, encephalopathy=enc,
            )
            fitness["child_pugh"] = cp
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        # Fried frailty
        wl_pct = fitness_data.get("weight_loss_6m_pct")
        fatigue = fitness_data.get("fatigue_score")
        ecog_val = fitness_data.get("ecog_current") or fitness_data.get("ecog_score")
        low_activity = fitness_data.get("low_activity")
        slow_gait = fitness_data.get("slow_gait")
        weak_grip = fitness_data.get("weak_grip")
        try:
            frailty = fried_frailty_index(
                weight_loss_pct=float(wl_pct) if wl_pct not in (None, "") else None,
                fatigue_score=float(fatigue) if fatigue else None,
                low_activity=_truthy(low_activity) if low_activity not in (None, "") else None,
                slow_gait=_truthy(slow_gait) if slow_gait not in (None, "") else None,
                weak_grip=_truthy(weak_grip) if weak_grip not in (None, "") else None,
                ecog=int(float(ecog_val)) if ecog_val else None,
                age=pat_age,
            )
            fitness["frailty"] = frailty
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        # Competing mortality
        cci_score = None
        cci_data = copilot.get("comorbidity_scores", {}).get("charlson", {})
        if cci_data and cci_data.get("is_complete"):
            cci_score = cci_data.get("adjusted_score") or cci_data.get("raw_score")
        egfr_val = fitness.get("egfr", {}).get("egfr")
        frailty_st = fitness.get("frailty", {}).get("status")
        if pat_age:
            try:
                fitness["competing_mortality"] = competing_mortality_estimate(
                    age=pat_age, cci=int(cci_score) if cci_score is not None else 0,
                    egfr=egfr_val, frailty_status=frailty_st,
                )
                fitness["has_data"] = True
            except (ValueError, TypeError):
                pass

        # Treatment Fit Score
        g8_data = copilot.get("comorbidity_scores", {}).get("g8", {})
        g8_val = g8_data.get("total_score") if g8_data and g8_data.get("is_complete") else None
        cp_grade = fitness.get("child_pugh", {}).get("grade")
        try:
            fitness["fit_score"] = treatment_fit_score(
                ecog=int(float(ecog_val)) if ecog_val else None,
                cci=int(cci_score) if cci_score is not None else None,
                g8=float(g8_val) if g8_val else None,
                egfr=egfr_val,
                child_pugh=cp_grade,
                frailty_status=frailty_st,
                age=pat_age,
            )
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        copilot["therapeutic_fitness"] = fitness
    except Exception as exc:
        copilot_logger.debug("Copilot therapeutic fitness error: %s", exc)
        copilot["therapeutic_fitness"] = {"has_data": False}

    # ── ADT side effects (only if on ADT) ──
    if prior.get("prior_adt") or management_track in ("on_arpi", "systemic_surveillance"):
        try:
            from prostanet.domains.patient_tracking.adt_side_effects import ADTSideEffectService
            adt_data: dict[str, Any] = {}
            adt_data.update(identity)
            adt_data.update(baseline)
            adt_data.update(prior)
            if followups:
                adt_data.update(followups[-1])
            profile = ADTSideEffectService.full_assessment(adt_data)
            copilot["adt_side_effects"] = profile.to_dict()
        except Exception as exc:
            copilot_logger.debug("Copilot ADT side effects error: %s", exc)

    # ── PRO intelligence (Salto 3) ──
    try:
        from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
        pro_data: dict[str, Any] = {}
        pro_data.update(identity)
        pro_data.update(baseline)
        pro_data.update(prior)
        if followups:
            pro_data.update(followups[-1])
        # PRO data from patient_pros table
        pro_record = patient.get("pros") or {}
        if isinstance(pro_record, dict):
            pro_data.update(pro_record)

        pro_alerts = PRODecisionEngine.evaluate_all(patient_id, pro_data)
        copilot["pro_intelligence"] = {
            "alerts": [a.to_dict() for a in pro_alerts],
            "alert_count": len(pro_alerts),
            "critical_count": sum(1 for a in pro_alerts if a.severity == "critical"),
            "has_data": len(pro_alerts) > 0,
        }
    except Exception as exc:
        copilot_logger.debug("Copilot PRO intelligence error: %s", exc)
        copilot["pro_intelligence"] = {"alerts": [], "alert_count": 0, "critical_count": 0, "has_data": False}

    # ── Precision genomics panel ──
    try:
        genomic = patient.get("genomics") or {}
        if not isinstance(genomic, dict):
            genomic = {}
        # Merge genomic fields that may be at patient root level
        for gkey in ("ar_v7_status", "tp53_status", "rb1_status", "pten_loss", "pten_status",
                      "cdk12_status", "ctdna_detected", "ctdna_vaf", "ctdna_rising",
                      "tmb_value", "tmb_mutations_per_mb", "nse", "neuron_specific_enolase",
                      "ldh", "lactate_dehydrogenase", "psa_discordant_low", "neuroendocrine_features"):
            if gkey not in genomic and patient.get(gkey) is not None:
                genomic[gkey] = patient[gkey]

        from prostanet.domains.m1_crpc.rules_nccn import _status_positive
        precision_panel: dict[str, Any] = {
            "ar_v7": {
                "status": str(genomic.get("ar_v7_status", "No evaluado")),
                "positive": _status_positive(genomic, "ar_v7_status"),
                "clinical_action": "Resistencia a ARPI — preferir taxanos" if _status_positive(genomic, "ar_v7_status") else None,
            },
            "tp53_rb1": {
                "tp53": str(genomic.get("tp53_status", "No evaluado")),
                "rb1": str(genomic.get("rb1_status", "No evaluado")),
                "lineage_plasticity": _status_positive(genomic, "tp53_status") and _status_positive(genomic, "rb1_status"),
                "clinical_action": "Vigilancia NEPC activa" if (_status_positive(genomic, "tp53_status") and _status_positive(genomic, "rb1_status")) else None,
            },
            "pten": {
                "status": str(genomic.get("pten_loss", genomic.get("pten_status", "No evaluado"))),
                "loss": _status_positive(genomic, "pten_loss") or _status_positive(genomic, "pten_status"),
                "clinical_action": "Candidato AKT inhibitor" if (_status_positive(genomic, "pten_loss") or _status_positive(genomic, "pten_status")) else None,
            },
            "cdk12": {
                "status": str(genomic.get("cdk12_status", "No evaluado")),
                "biallelic": _status_positive(genomic, "cdk12_status"),
                "clinical_action": "Candidato IO independiente de MSI" if _status_positive(genomic, "cdk12_status") else None,
            },
            "tmb": {
                "value": None,
                "zone": "unknown",
            },
            "ctdna": {
                "detected": str(genomic.get("ctdna_detected", "0")) == "1",
                "vaf": None,
                "rising": str(genomic.get("ctdna_rising", "0")) == "1",
                "clinical_action": "Resistencia emergente — anticipar cambio" if str(genomic.get("ctdna_rising", "0")) == "1" else None,
            },
            "nepc_suspicion": {
                "score": 0,
                "suspected": False,
            },
        }
        # TMB
        try:
            tmb_v = float(genomic.get("tmb_value") or genomic.get("tmb_mutations_per_mb") or 0)
            if tmb_v > 0:
                precision_panel["tmb"]["value"] = tmb_v
                precision_panel["tmb"]["zone"] = "high" if tmb_v > 10 else ("gray" if tmb_v >= 6 else "low")
        except (ValueError, TypeError):
            pass
        # ctDNA VAF
        try:
            vaf = float(genomic.get("ctdna_vaf") or 0)
            if vaf > 0:
                precision_panel["ctdna"]["vaf"] = vaf
        except (ValueError, TypeError):
            pass
        # NEPC score
        nepc_s = 0
        if precision_panel["tp53_rb1"]["lineage_plasticity"]:
            nepc_s += 2
        if str(genomic.get("neuroendocrine_features", "0")) == "1":
            nepc_s += 2
        try:
            nse_v = float(genomic.get("nse") or genomic.get("neuron_specific_enolase") or 0)
            if nse_v > 16.3:
                nepc_s += 1
        except (ValueError, TypeError):
            pass
        try:
            ldh_v = float(genomic.get("ldh") or genomic.get("lactate_dehydrogenase") or 0)
            if ldh_v > 250:
                nepc_s += 1
        except (ValueError, TypeError):
            pass
        if str(genomic.get("psa_discordant_low", "0")) == "1":
            nepc_s += 1
        precision_panel["nepc_suspicion"]["score"] = nepc_s
        precision_panel["nepc_suspicion"]["suspected"] = nepc_s >= 3

        # Count actionable biomarkers
        actionable_count = sum(1 for v in precision_panel.values() if isinstance(v, dict) and v.get("clinical_action"))
        precision_panel["actionable_count"] = actionable_count
        precision_panel["has_data"] = any(
            isinstance(v, dict) and (v.get("positive") or v.get("loss") or v.get("biallelic") or v.get("detected") or v.get("value"))
            for v in precision_panel.values()
        )

        copilot["precision_genomics"] = precision_panel
    except Exception as exc:
        copilot_logger.debug("Copilot precision genomics error: %s", exc)
        copilot["precision_genomics"] = {"has_data": False, "actionable_count": 0}

    # ── Oligometastatic assessment (Salto 4) ──
    try:
        from prostanet.domains.patient_tracking.oligomet_engine import OligometDecisionEngine
        oligo_data: dict[str, Any] = {}
        oligo_data.update(identity)
        oligo_data.update(baseline)
        oligo_data.update(prior)
        if followups:
            oligo_data.update(followups[-1])

        oligo_lesions: list[dict[str, Any]] = []
        for lesion in patient.get("lesion_tracking") or []:
            les: dict[str, Any] = dict(lesion)
            measurements = les.get("measurements") or []
            meas = measurements[-1] if measurements else {}
            if meas:
                les["longest_diameter_mm"] = meas.get("longest_diameter_mm")
                les["suvmax"] = meas.get("suvmax")
            if les.get("suvmax") and float(les["suvmax"] or 0) > 0:
                les["psma_avid"] = "1"
            oligo_lesions.append(les)

        oligo_data["lesions"] = oligo_lesions
        oligo_data["psma_positive"] = "1" if any(
            str(l.get("psma_avid", "0")) == "1" for l in oligo_lesions
        ) else str(oligo_data.get("psma_positive", "0"))

        oligo_result = OligometDecisionEngine.evaluate(oligo_data)
        copilot["oligomet_assessment"] = oligo_result
    except Exception as exc:
        copilot_logger.debug("Copilot oligomet error: %s", exc)
        copilot["oligomet_assessment"] = {"has_data": False}

    # ── DDI + Formulary review (Salto 5) ──
    try:
        from prostanet.shared.ddi_engine import DDIEngine
        ddi_data: dict[str, Any] = {}
        ddi_data.update(identity)
        ddi_data.update(baseline)
        ddi_data.update(prior)
        if followups:
            ddi_data.update(followups[-1])

        # Get institution from patient data
        institution = str(ddi_data.get("institution") or ddi_data.get("institucion") or "privado").lower()

        ddi_data["institution"] = institution
        ddi_raw = DDIEngine.full_review(ddi_data)

        # EPIC 4.5 — agregar families summary + regimen matrix para UI.
        interactions_list = ddi_raw.get("ddi_alerts", []) or []
        families_summary: dict[str, int] = {}
        alerts_by_family: dict[str, list[dict[str, Any]]] = {}
        for interaction in interactions_list:
            family = str(interaction.get("alert_family") or "").strip().lower()
            if not family:
                severity = str(interaction.get("severity") or "").strip().lower()
                family = {
                    "contraindicated": "ddi_critical",
                    "major": "ddi_major",
                    "moderate": "ddi_moderate",
                }.get(severity, "ddi_moderate")
            families_summary[family] = families_summary.get(family, 0) + 1
            alerts_by_family.setdefault(family, []).append(interaction)

        # Matriz por régimen candidato si el normalizador corrió.
        regimen_matrix_raw = ddi_data.get("ddi_regimen_matrix") or {}
        regimen_matrix_summary: list[dict[str, Any]] = []
        if isinstance(regimen_matrix_raw, dict):
            for regimen_code, bundle in regimen_matrix_raw.items():
                if not isinstance(bundle, dict):
                    continue
                regimen_matrix_summary.append({
                    "regimen_code": regimen_code,
                    "status": bundle.get("status", "none"),
                    "alert_count": int(bundle.get("alert_count") or 0),
                    "major_count": int(bundle.get("major_count") or 0),
                    "contraindicated_count": int(bundle.get("contraindicated_count") or 0),
                    "families": list(bundle.get("families") or []),
                })
            # Orden: peor primero (contraindicated > major > caution > none).
            severity_rank_ui = {"contraindicated": 3, "major": 2, "caution": 1, "none": 0}
            regimen_matrix_summary.sort(
                key=lambda row: (-severity_rank_ui.get(str(row.get("status") or "none"), 0), row.get("regimen_code", "")),
            )

        review_status = str(ddi_data.get("ddi_review_status") or "").strip().lower() or (
            "completed" if interactions_list or ddi_data.get("normalized_medication_list") else "not_started"
        )
        review_source = "engine_realtime" if ddi_data.get("normalized_medication_list") else "legacy_full_review"

        copilot["ddi_review"] = {
            "interactions": interactions_list,
            "formulary": ddi_raw.get("formulary", []),
            "has_interactions": ddi_raw.get("ddi_count", 0) > 0,
            "has_formulary": len(ddi_raw.get("formulary", [])) > 0,
            "families_summary": families_summary,
            "alerts_by_family": alerts_by_family,
            "regimen_matrix": regimen_matrix_summary,
            "review_status": review_status,
            "review_source": review_source,
            "contraindicated_count": int(ddi_raw.get("contraindicated_count") or 0),
        }
    except Exception as exc:
        copilot_logger.debug("Copilot DDI review error: %s", exc)
        copilot["ddi_review"] = {
            "interactions": [], "formulary": [], "has_interactions": False, "has_formulary": False,
            "families_summary": {}, "alerts_by_family": {}, "regimen_matrix": [],
            "review_status": "not_started", "review_source": "unavailable", "contraindicated_count": 0,
        }

    # ── Response visualization (waterfall, spider, swimmer) ──
    try:
        from prostanet.domains.reporting.response_visualization import ResponseVisualizationService
        treatments = patient.get("treatments") or []
        psa_series = patient.get("psa_series") or []
        lesion_data = patient.get("lesion_tracking") or []

        diagnosis_date = identity.get("diagnosis_date")
        baseline_psa_val = baseline.get("baseline_psa")

        viz_bundle = ResponseVisualizationService.build_visualization_bundle(
            treatments=treatments,
            lesions=lesion_data,
            psa_series=psa_series,
            baseline_psa=float(baseline_psa_val) if baseline_psa_val else None,
            diagnosis_date=diagnosis_date,
        )
        copilot["response_visualization"] = viz_bundle.to_dict()
    except Exception as exc:
        copilot_logger.debug("Copilot response visualization error: %s", exc)
        copilot["response_visualization"] = {"waterfall": [], "spider": {"has_data": False}, "swimmer": [], "psa_trajectory": {"has_data": False}}

    response_assessments = patient.get("response_assessments") or []
    if response_assessments:
        copilot["latest_response_assessment"] = response_assessments[0]

    # ── TNM Staging ──
    try:
        from prostanet.shared.tnm_engine import TNMEngine
        tnm_data: dict[str, Any] = {}
        tnm_data.update(identity)
        tnm_data.update(baseline)
        tnm_data.update(prior)
        if followups:
            tnm_data.update(followups[-1])
        # Also check the assessment input_snapshot for clinical_tstage
        input_snap = (raw_assessment or {}).get("input_snapshot", {})
        if input_snap:
            for key in ("clinical_tstage", "nodal_status", "metastasis_site", "dre_finding", "dre_suspicious"):
                if input_snap.get(key) and not tnm_data.get(key):
                    tnm_data[key] = input_snap[key]
        copilot["tnm_staging"] = TNMEngine.assemble(tnm_data)
    except Exception as exc:
        copilot_logger.debug("Copilot TNM staging error: %s", exc)
        copilot["tnm_staging"] = {"has_data": False}

    # ── Structured biopsy section ──
    try:
        from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService
        biopsies = patient.get("biopsies") or []
        if biopsies and isinstance(biopsies[-1], dict):
            parsed_biopsy = StructuredBiopsyService.parse_structured_biopsy(biopsies[-1])
            copilot["structured_biopsy"] = StructuredBiopsyService.build_biopsy_summary_for_profile(parsed_biopsy)
        else:
            copilot["structured_biopsy"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot structured biopsy error: %s", exc)
        copilot["structured_biopsy"] = {"has_data": False}

    # ── Active surveillance protocol section ──
    try:
        from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
        from prostanet.domains.patient_tracking.active_surveillance_longitudinal import (
            LongitudinalASService,
        )
        if management_track == "active_surveillance" or state == "localized_initial":
            as_data: dict[str, Any] = {}
            as_data.update(identity)
            as_data.update(baseline)
            as_data.update(prior)
            if followups:
                as_data.update(followups[-1])
            # Inyectar listas longitudinales accesibles al engine serial (fallback
            # por fecha sobre psa_history + biopsies + mri_facts + pro_assessments).
            for key in ("psa_history", "biopsies", "mri_facts", "pro_assessments",
                        "active_surveillance_snapshots"):
                if key not in as_data and patient.get(key):
                    as_data[key] = patient.get(key)
            as_protocol = ActiveSurveillanceService.build_as_protocol(as_data, state)
            as_summary = ActiveSurveillanceService.build_as_summary_for_profile(as_protocol)

            # EPIC 5 — "Vigilancia activa longitudinal": reporte serial sobre
            # ≥2 snapshots. Si no hay historia serial, el reporte llega con
            # `snapshots_evaluated<2` y la UI muestra notas explicativas.
            longitudinal_report = LongitudinalASService.evaluate(as_data)
            as_summary["longitudinal"] = longitudinal_report.to_dict()
            # Elevar tono del card si el engine serial detecta banda alta.
            if longitudinal_report.probability_band == "high" and as_summary.get("tone") == "success":
                as_summary["tone"] = "danger"
            elif longitudinal_report.probability_band == "moderate" and as_summary.get("tone") == "success":
                as_summary["tone"] = "warning"
            copilot["active_surveillance"] = as_summary
        else:
            copilot["active_surveillance"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot active surveillance error: %s", exc)
        copilot["active_surveillance"] = {"has_data": False}

    # ── Radiotherapy detail section ──
    try:
        from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
        rt_courses = patient.get("rt_courses") or patient.get("radiotherapy_courses") or []
        if rt_courses:
            rt_summary = RadiotherapyDetailService.build_rt_history(patient)
            copilot["radiotherapy_detail"] = RadiotherapyDetailService.build_rt_summary_for_profile(rt_summary)
        else:
            copilot["radiotherapy_detail"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot radiotherapy detail error: %s", exc)
        copilot["radiotherapy_detail"] = {"has_data": False}

    # ── Skeletal events section ──
    try:
        from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
        sre_raw = patient.get("skeletal_events") or patient.get("sre_events") or []
        if sre_raw or state in ADVANCED_STATES:
            sre_data: dict[str, Any] = {}
            sre_data.update(identity)
            sre_data.update(baseline)
            sre_data.update(prior)
            if followups:
                sre_data.update(followups[-1])
            sre_data["skeletal_events"] = sre_raw
            sre_profile = SkeletalEventService.build_sre_profile(sre_data, state)
            copilot["skeletal_events"] = SkeletalEventService.build_sre_summary_for_profile(sre_profile)
        else:
            copilot["skeletal_events"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot skeletal events error: %s", exc)
        copilot["skeletal_events"] = {"has_data": False}

    # ── Survival endpoints section ──
    try:
        from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
        survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
        copilot["survival_endpoints"] = SurvivalEndpointService.build_survival_summary_for_profile(survival_status)
    except Exception as exc:
        copilot_logger.debug("Copilot survival endpoints error: %s", exc)
        copilot["survival_endpoints"] = {"has_data": False}

    # ═══════════════════════════════════════════════════════════════
    # AI Engine Enrichments — all gated by feature flags (default OFF)
    # ═══════════════════════════════════════════════════════════════
    from prostanet.shared.feature_flags import resolve_feature_flags
    ai_flags = resolve_feature_flags()

    # ── AI State Transition Prediction ──
    if ai_flags.get("ENABLE_AI_STATE_PREDICTION"):
        try:
            from prostanet.ai.inference.prediction_service import PredictionService
            from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

            reg = get_runtime_model_registry()
            service = PredictionService(model_registry=reg)
            pid = patient.get("identity", {}).get("id", 0)
            transition = service.predict_state_transition(pid, patient)
            copilot["ai_state_prediction"] = transition or {"has_data": False}
        except Exception as exc:
            copilot_logger.debug("AI state prediction error: %s", exc)
            copilot["ai_state_prediction"] = {"has_data": False}

    # ── AI Survival Curves (DeepSurv) ──
    if ai_flags.get("ENABLE_AI_SURVIVAL_MODEL"):
        try:
            from prostanet.ai.inference.prediction_service import PredictionService
            from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

            reg = get_runtime_model_registry()
            service = PredictionService(model_registry=reg)
            pid = patient.get("identity", {}).get("id", 0)
            survival_ai = service.predict_survival(pid, patient)
            copilot["ai_survival_curves"] = survival_ai or {"has_data": False}
        except Exception as exc:
            copilot_logger.debug("AI survival model error: %s", exc)
            copilot["ai_survival_curves"] = {"has_data": False}

    # ── AI Anomaly Detection ──
    if ai_flags.get("ENABLE_AI_ANOMALY_DETECTION"):
        try:
            from prostanet.ai.inference.prediction_service import PredictionService
            from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

            reg = get_runtime_model_registry()
            service = PredictionService(model_registry=reg)
            pid = patient.get("identity", {}).get("id", 0)
            anomalies = service.predict_anomalies(pid, patient)
            copilot["ai_anomaly_detection"] = anomalies or {"has_data": False}
        except Exception as exc:
            copilot_logger.debug("AI anomaly detection error: %s", exc)
            copilot["ai_anomaly_detection"] = {"has_data": False}

    # ── AI Agent Recommendation (CDA) ──
    if ai_flags.get("ENABLE_AGENT_CDA"):
        try:
            from prostanet.engine.audit_log import AuditLogger
            pid = patient.get("identity", {}).get("id", 0)
            audit = AuditLogger()
            latest = audit.get_latest_recommendation(pid)
            if latest and latest.get("output"):
                copilot["ai_recommendation"] = {
                    "has_data": True,
                    "agent_id": latest.get("agent_id"),
                    "confidence_score": latest.get("confidence_score"),
                    "output": latest["output"],
                    "created_at": latest.get("created_at"),
                }
            else:
                copilot["ai_recommendation"] = {"has_data": False}
        except Exception as exc:
            copilot_logger.debug("AI recommendation error: %s", exc)
            copilot["ai_recommendation"] = {"has_data": False}

    # ── AI Treatment Ranking (TOA) ──
    if ai_flags.get("ENABLE_AI_TREATMENT_PREDICTION"):
        try:
            from prostanet.engine.audit_log import AuditLogger
            pid = patient.get("identity", {}).get("id", 0)
            audit = AuditLogger()
            latest = audit.get_latest_recommendation(pid, agent_id="treatment_optimization_agent")
            if latest and latest.get("output"):
                copilot["ai_treatment_ranking"] = {
                    "has_data": True,
                    "output": latest["output"],
                    "created_at": latest.get("created_at"),
                }
            else:
                copilot["ai_treatment_ranking"] = {"has_data": False}
        except Exception as exc:
            copilot_logger.debug("AI treatment ranking error: %s", exc)
            copilot["ai_treatment_ranking"] = {"has_data": False}

    # ── Natural History Tracker — always runs (no GPU required) ──
    try:
        from prostanet.domains.patient_tracking.natural_history_tracker import (
            analyze_natural_history,
        )
        copilot["natural_history"] = analyze_natural_history(patient)
    except Exception as exc:
        copilot_logger.debug("Natural history tracker error: %s", exc)
        copilot["natural_history"] = {"has_data": False}

    return copilot


# ─────────────────────────────────────────────────────────────────────────────
# EPIC 45 — Data Integrity (FactSpec alias contradiction snapshot)
# ─────────────────────────────────────────────────────────────────────────────


def _build_data_integrity_snapshot(patient: dict[str, Any]) -> dict[str, Any]:
    """EPIC 45 FAUBOT CXXX — Snapshot del estado de integridad de datos.

    Detecta contradicciones FactSpec alias (e.g., metastatic_stage_resolved=M0
    + m_substage_resolved=M1b ambos activos) en los facts del paciente actual
    y lista resoluciones históricas aplicadas.

    Operación read-only (advisory) — NO aplica auto-resolución. Para aplicar,
    el clínico debe llamar a POST /api/data-integrity/<nss>/resolve.

    Returns:
        {
          'available': bool,
          'contradictions_detected': [...],
          'contradictions_count': int,
          'severity_summary': {'high': int, 'medium': int},
          'resolutions_history': [...],
          'last_resolution_at': str | None,
        }
    """
    try:
        from prostanet.regulatory.clinical.factspec_alias_audit import (
            detect_contradictions_for_patient,
        )
    except Exception:
        return {"available": False, "reason": "audit_module_unavailable"}

    # patient_id puede vivir en data.id, data.patient_id, o data.identity.id
    # (este último es el path canónico desde build_patient_record_derivatives)
    _identity = patient.get("identity") if isinstance(patient.get("identity"), dict) else {}
    patient_id = int(
        patient.get("id")
        or patient.get("patient_id")
        or (_identity.get("id") if _identity else 0)
        or 0
    )
    facts = patient.get("patient_clinical_facts") or []
    if not isinstance(facts, list):
        facts = []

    # Fall back to DB query when the upstream loader didn't include facts
    # (common in patient_profile_v2 flow where facts are loaded separately).
    if not facts and patient_id > 0:
        try:
            from tracking_db import get_db_connection
            _conn = get_db_connection()
            _cur = _conn.cursor()
            _cur.execute(
                """
                SELECT id, fact_key, normalized_value_text, source_type,
                       observed_at, updated_at, is_active
                  FROM patient_clinical_facts
                 WHERE patient_id = ? AND is_active = 1
                """,
                (patient_id,),
            )
            facts = [dict(r) for r in _cur.fetchall()]
        except Exception:
            facts = []

    contradictions = detect_contradictions_for_patient(patient_id, facts)
    severity_summary = {"high": 0, "medium": 0}
    for c in contradictions:
        severity_summary[c.severity] = severity_summary.get(c.severity, 0) + 1

    # Historical resolutions from audit log
    resolutions_history: list[dict[str, Any]] = []
    last_resolution_at: str | None = None
    try:
        from prostanet.regulatory.clinical.factspec_alias_audit import (
            list_recent_resolutions_for_patient,
        )
        # Correct connection helper name (tracking_db exposes get_db_connection)
        from tracking_db import get_db_connection
        try:
            conn = get_db_connection()
            resolutions_history = list_recent_resolutions_for_patient(
                conn, patient_id, limit=20,
            )
            if resolutions_history:
                last_resolution_at = resolutions_history[0].get("resolved_at")
        except Exception:
            pass
    except Exception:
        pass

    return {
        "available": True,
        "patient_id": patient_id,
        "contradictions_detected": [c.to_dict() for c in contradictions],
        "contradictions_count": len(contradictions),
        "severity_summary": severity_summary,
        "needs_clinician_review": any(c.severity == "high" for c in contradictions),
        "resolutions_history": resolutions_history,
        "resolutions_count": len(resolutions_history),
        "last_resolution_at": last_resolution_at,
    }


def build_patient_profile_view_model(
    *,
    patient: dict[str, Any],
    latest_assessment_raw: dict[str, Any] | None,
    latest_assessment: dict[str, Any] | None,
    state_timeline: list[dict[str, Any]],
    care_overlays: list[dict[str, Any]],
    recommendations: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patient = _merge_longitudinal_runtime_context(patient, longitudinal_bundle)
    raw_assessment = dict(latest_assessment_raw or {})
    assessment = dict(latest_assessment or {})
    raw_assessment, assessment = _refresh_runtime_assessment(
        patient=patient,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
    )
    # Auditoría #21 (cierre OOS-10): cuando el raw_assessment persistido no
    # incluye `state` (p. ej. módulos que sólo emiten `input_snapshot`/`result_snapshot`)
    # pero el display_assessment sí lo trae, hay que retro-popular el state para
    # que `patient["latest_assessment"]` no destruya la etiqueta de estado al
    # pasarla a `build_reconciled_state`. Sin este backfill, el reconciliador
    # cae en `diagnostic_workup` y, con evidencia de metástasis ya
    # documentada (p. ej. `baseline.metastasis_site="Visceral"`), reasigna
    # erróneamente a `localized_initial`, ocultando la elegibilidad mHSPC.
    if raw_assessment and not raw_assessment.get("state") and assessment.get("state"):
        raw_assessment["state"] = assessment["state"]
    if raw_assessment:
        patient = dict(patient)
        patient["latest_assessment"] = raw_assessment
    reconciliation_input = dict(raw_assessment)
    for key, value in assessment.items():
        if value not in (None, "", [], {}):
            reconciliation_input[key] = value
    if raw_assessment.get("input_snapshot") and not reconciliation_input.get("input_snapshot"):
        reconciliation_input["input_snapshot"] = raw_assessment.get("input_snapshot")
    reconciliation = build_reconciled_state(
        patient,
        patient.get("latest_assessment") or reconciliation_input or assessment,
    )
    bundle_signals = dict((longitudinal_bundle or {}).get("signals") or {})
    bundle_transition_resolution = dict(
        (longitudinal_bundle or {}).get("transition_resolution")
        or patient.get("transition_resolution")
        or {}
    )
    auto_transition_target = str(bundle_transition_resolution.get("target_state") or "")
    bundle_postlocal_state = str(
        bundle_signals.get("reconciled_state")
        or bundle_signals.get("effective_state_final")
        or bundle_signals.get("effective_state")
        or ""
    )
    suppress_postlocal_auto_transition = (
        bundle_transition_resolution.get("policy") == "auto_applied"
        and (
            (
                reconciliation.get("reconciled_state") in POSTLOCAL_STATES
                and auto_transition_target not in POSTLOCAL_STATES
            )
            or (
                bundle_postlocal_state in POSTLOCAL_STATES
                and auto_transition_target in POSTLOCAL_STATES
                and auto_transition_target != bundle_postlocal_state
            )
        )
    )
    if bundle_transition_resolution.get("policy") == "auto_applied" and not suppress_postlocal_auto_transition:
        if bundle_transition_resolution.get("target_state"):
            reconciliation["reconciled_state"] = bundle_transition_resolution.get("target_state")
        if bundle_transition_resolution.get("target_management_track"):
            reconciliation["reconciled_management_track"] = bundle_transition_resolution.get("target_management_track")
        reconciliation["state_conflict_flag"] = False
        reconciliation["state_conflict_reason"] = ""
    elif bundle_signals:
        if bundle_signals.get("reconciled_state"):
            reconciliation["reconciled_state"] = bundle_signals.get("reconciled_state")
        if bundle_signals.get("reconciled_management_track"):
            reconciliation["reconciled_management_track"] = bundle_signals.get("reconciled_management_track")
        if bundle_signals.get("state_conflict_flag") is not None:
            reconciliation["state_conflict_flag"] = bundle_signals.get("state_conflict_flag")
        if bundle_signals.get("state_conflict_reason"):
            reconciliation["state_conflict_reason"] = bundle_signals.get("state_conflict_reason")
    state = reconciliation.get("reconciled_state") or assessment.get("state") or patient.get("prior_history", {}).get("current_state") or ""
    diagnostic_state = state in DIAGNOSTIC_STATES
    display_result = assessment.get("display_result", {}) if assessment else {}
    management_track = reconciliation.get("reconciled_management_track") or infer_management_track(patient, state, raw_assessment)
    benchmark_state = str(
        bundle_signals.get("effective_state_final")
        or bundle_signals.get("effective_state")
        or bundle_signals.get("phenotype_state")
        or state
    )
    fallback_benchmark_state = str(
        raw_assessment.get("state")
        or assessment.get("state")
        or patient.get("prior_history", {}).get("current_state")
        or ""
    )
    if not is_live_benchmark_applicable_state(benchmark_state) and is_live_benchmark_applicable_state(fallback_benchmark_state):
        benchmark_state = fallback_benchmark_state
    assessment_state = normalize_text(assessment.get("state") or raw_assessment.get("state") or "")
    resolved_state_label = _first_nonempty(STATE_DISPLAY_MAP.get(state), state)
    operational_module_label = (
        resolved_state_label
        if assessment_state and assessment_state != state
        else (
            resolved_state_label
            if _should_prefer_resolved_stage_label(
                state=state,
                module_label=assessment.get("module_label"),
                resolved_stage_label=resolved_state_label,
            )
            else _first_nonempty(assessment.get("module_label"), resolved_state_label, state)
        )
    )
    diagnosis_context = build_official_diagnosis_context(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
        operational_module_label=operational_module_label,
    )
    risk_tools_bundle = build_risk_tools_panel(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
    )
    risk_tools_bundle["cards"] = _decorate_missing_input_groups(risk_tools_bundle.get("cards", []))
    risk_tools_bundle["missing_inputs"] = _displayize_field_list(risk_tools_bundle.get("missing_inputs") or [], limit=8)
    triplet_decision = _build_triplet_decision_for_profile(
        state=state,
        raw_assessment=raw_assessment,
    )
    triplet_decision = _decorate_triplet_decision(triplet_decision)
    agenda_board = build_agenda_board(
        patient,
        state,
        management_track,
        raw_assessment,
        longitudinal_bundle=longitudinal_bundle,
    )
    persisted_agenda_items = [dict(item) for item in (patient.get("agenda_items") or agenda_board.get("items", []))]
    scheduled_by_key = {
        str(item.get("schedule_key") or ""): item
        for item in (patient.get("scheduled_events") or [])
        if str(item.get("schedule_key") or "")
    }
    for item in persisted_agenda_items:
        scheduled = scheduled_by_key.get(str(item.get("agenda_key") or ""), {})
        item["plan_key"] = scheduled.get("plan_key") or item.get("plan_key") or ""
        item["ideal_due_at"] = scheduled.get("ideal_due_at") or item.get("ideal_due_at") or item.get("due_at") or ""
        item["scheduled_due_at"] = scheduled.get("scheduled_due_at") or item.get("scheduled_due_at") or item.get("due_at") or ""
        item["delay_days"] = int(scheduled.get("delay_days") or item.get("delay_days") or 0)
        item["completed_at"] = scheduled.get("completed_at") or item.get("completed_at") or ""
        item["required"] = bool(scheduled.get("required", item.get("required", True)))
        item["action_mode"] = scheduled.get("action_mode") or item.get("action_mode") or "capture"
        if item["completed_at"] and str(item.get("status") or "") not in {"cancelled", "superseded"}:
            item["status"] = "completed"
    persisted_agenda_items.sort(key=longitudinal_item_sort_key)
    persisted_agenda_items = prioritize_items_for_window_worklist(
        persisted_agenda_items,
        (longitudinal_bundle or {}).get("window_worklist_bundle") or {},
    )
    persisted_agenda_items = _decorate_agenda_items_for_display(persisted_agenda_items)
    active_agenda_items = [item for item in persisted_agenda_items if item.get("status") not in {"completed", "superseded", "cancelled"}]
    archived_agenda_items = [item for item in persisted_agenda_items if item.get("status") in {"completed", "superseded", "cancelled"}]
    next_due_items = [item for item in active_agenda_items if item.get("status") in {"due", "due_today"}][:4]
    overdue_items = [item for item in active_agenda_items if item.get("status") == "overdue"][:4]
    active_recommendations = [item for item in active_agenda_items if item.get("status") in {"due", "due_today", "overdue", "scheduled", "blocked"}][:5]
    agenda_board["items"] = active_agenda_items
    agenda_board["active_items"] = active_agenda_items
    agenda_board["archived_items"] = archived_agenda_items
    agenda_board["next_due_items"] = next_due_items
    agenda_board["overdue_items"] = overdue_items
    agenda_board["active_recommendations"] = active_recommendations
    from prostanet.domains.patient_tracking.encounter_planner import build_encounter_plans

    timeline_agenda_items = sorted(
        [dict(item) for item in [*active_agenda_items, *archived_agenda_items]],
        key=longitudinal_item_sort_key,
    )
    enriched_encounters = build_encounter_plans(
        timeline_agenda_items,
        state=state,
        management_track=management_track,
        protocol_trace=agenda_board.get("protocol_trace") or {},
    )
    actionable_encounters = [
        encounter
        for encounter in enriched_encounters
        if str(encounter.get("status") or "scheduled") not in {"completed", "cancelled", "superseded"}
    ]
    agenda_board["encounters"] = enriched_encounters
    agenda_board["next_encounter"] = next(
        (encounter for encounter in actionable_encounters if str(encounter.get("visit_modality") or "") != "async"),
        actionable_encounters[0] if actionable_encounters else {},
    )
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    latest_signal_snapshot.update(dict((longitudinal_bundle or {}).get("signals") or {}))
    latest_signal_snapshot.update(
        {
            "explicit_state": reconciliation.get("explicit_state"),
            "reconciled_state": reconciliation.get("reconciled_state"),
            "reconciled_management_track": reconciliation.get("reconciled_management_track"),
            "state_conflict_flag": reconciliation.get("state_conflict_flag"),
            "state_conflict_reason": reconciliation.get("state_conflict_reason"),
            "supporting_evidence": reconciliation.get("supporting_evidence", {}),
        }
    )
    latest_signal_snapshot.setdefault("critical_missing", [])
    latest_signal_snapshot.setdefault("awaiting_review", [])
    latest_signal_snapshot.setdefault("active_safety", [])
    latest_signal_snapshot["display_critical_missing"] = normalize_field_list(
        latest_signal_snapshot.get("critical_missing") or []
    )
    latest_signal_snapshot["display_awaiting_review"] = normalize_field_list(
        latest_signal_snapshot.get("awaiting_review") or []
    )
    latest_signal_snapshot["display_active_safety"] = normalize_field_list(
        latest_signal_snapshot.get("active_safety") or []
    )
    if longitudinal_bundle and longitudinal_bundle.get("next_best_action"):
        latest_signal_snapshot["next_best_action"] = dict(longitudinal_bundle.get("next_best_action") or {})
    if longitudinal_bundle and longitudinal_bundle.get("transition_resolution"):
        latest_signal_snapshot["transition_resolution"] = dict(longitudinal_bundle.get("transition_resolution") or {})
    elif patient.get("transition_resolution"):
        latest_signal_snapshot["transition_resolution"] = dict(patient.get("transition_resolution") or {})
    if longitudinal_bundle and longitudinal_bundle.get("care_intent_contract"):
        latest_signal_snapshot["care_intent_contract"] = dict(longitudinal_bundle.get("care_intent_contract") or {})
    elif patient.get("care_intent_contract"):
        latest_signal_snapshot["care_intent_contract"] = dict(patient.get("care_intent_contract") or {})
    if longitudinal_bundle and longitudinal_bundle.get("palliative_transition_bundle"):
        latest_signal_snapshot["palliative_transition_bundle"] = dict(longitudinal_bundle.get("palliative_transition_bundle") or {})
    elif patient.get("palliative_transition_bundle"):
        latest_signal_snapshot["palliative_transition_bundle"] = dict(patient.get("palliative_transition_bundle") or {})
    if longitudinal_bundle and longitudinal_bundle.get("palliative_monitoring_package"):
        latest_signal_snapshot["palliative_monitoring_package"] = dict(longitudinal_bundle.get("palliative_monitoring_package") or {})
    elif patient.get("palliative_monitoring_package"):
        latest_signal_snapshot["palliative_monitoring_package"] = dict(patient.get("palliative_monitoring_package") or {})
    if longitudinal_bundle and longitudinal_bundle.get("survivorship_transition_bundle"):
        latest_signal_snapshot["survivorship_transition_bundle"] = dict(longitudinal_bundle.get("survivorship_transition_bundle") or {})
    elif patient.get("survivorship_transition_bundle"):
        latest_signal_snapshot["survivorship_transition_bundle"] = dict(patient.get("survivorship_transition_bundle") or {})
    if longitudinal_bundle and longitudinal_bundle.get("survivorship_monitoring_package"):
        latest_signal_snapshot["survivorship_monitoring_package"] = dict(longitudinal_bundle.get("survivorship_monitoring_package") or {})
    elif patient.get("survivorship_monitoring_package"):
        latest_signal_snapshot["survivorship_monitoring_package"] = dict(patient.get("survivorship_monitoring_package") or {})
    adjudication_snapshot = dict(patient.get("latest_adjudication_snapshot") or {})
    trial_benchmark_snapshot = dict(patient.get("latest_trial_benchmark_snapshot") or {})
    if not adjudication_snapshot or not trial_benchmark_snapshot:
        from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle

        runtime_outcomes = build_disease_course_bundle(
            patient,
            state=state,
            management_track=management_track,
            latest_assessment=raw_assessment,
        )
        adjudication_snapshot = {
            "current_course_status": runtime_outcomes.get("current_course_status", ""),
            "current_response_state": runtime_outcomes.get("current_response_state", {}),
            "last_adjudicated_event": runtime_outcomes.get("last_adjudicated_event", {}),
            "pending_adjudications": runtime_outcomes.get("pending_adjudications", []),
            "outcome_events_summary": runtime_outcomes.get("outcome_events_summary", {}),
            "milestone_plan": runtime_outcomes.get("milestone_plan", []),
            "outcome_anchor": runtime_outcomes.get("outcome_anchor", {}),
        }
        trial_benchmark_snapshot = {
            "current_trial_profile": runtime_outcomes.get("current_trial_comparable_profile", {}),
            "trial_endpoints": runtime_outcomes.get("trial_comparable_endpoints", []),
            "benchmark_snapshot": {
                "benchmark_snapshots": runtime_outcomes.get("benchmark_snapshots", []),
                "survival_status": runtime_outcomes.get("survival_status", {}),
            },
        }
        patient_outcome_events = runtime_outcomes.get("outcome_events", [])
    else:
        patient_outcome_events = list(patient.get("outcome_events") or [])
    current_trial_profile = dict(trial_benchmark_snapshot.get("current_trial_profile") or {})
    preferred_frontline_regimen = dict(raw_assessment.get("result_snapshot", {}).get("preferred_frontline_regimen") or {})
    frontline_ranking_trace = dict(raw_assessment.get("result_snapshot", {}).get("frontline_ranking_trace") or {})
    if is_mhspc_state(state) and preferred_frontline_regimen:
        rationale = list(preferred_frontline_regimen.get("selection_rationale") or [])
        winner_reason = normalize_text(frontline_ranking_trace.get("winner_reason"))
        current_trial_profile.update(
            {
                "recommended_trial_backbone": [preferred_frontline_regimen.get("regimen_code", "")],
                "recommended_trial_backbone_label": preferred_frontline_regimen.get("regimen_label", ""),
                "recommended_trial_backbone_source": ", ".join((preferred_frontline_regimen.get("pivotal_trial_fit") or {}).get("matched_trials") or []),
                "recommended_trial_backbone_note": winner_reason or " ".join(rationale[:2]) or "Esquema frontline individualizado según elegibilidad clínica, guideline fit y evidencia pivote.",
                "preferred_frontline_regimen": preferred_frontline_regimen,
                "recommended_component_drugs": list(preferred_frontline_regimen.get("component_drugs") or []),
            }
        )
        trial_benchmark_snapshot["current_trial_profile"] = current_trial_profile
    if current_trial_profile and not current_trial_profile.get("recommended_trial_backbone_label"):
        current_trial_profile.update(
            summarize_trial_backbones(list(current_trial_profile.get("matched_trials") or []))
        )
        trial_benchmark_snapshot["current_trial_profile"] = current_trial_profile
    if current_trial_profile:
        current_trial_profile["display_benchmark_family"] = normalize_ui_text(
            current_trial_profile.get("benchmark_family"),
            default="Sin familia comparable priorizada",
        )
        current_trial_profile["display_eligibility_status"] = normalize_ui_text(
            current_trial_profile.get("eligibility_status"),
            default="",
        )
        trial_benchmark_snapshot["current_trial_profile"] = current_trial_profile
    longitudinal_bundle = longitudinal_bundle or {}
    psa_forecast = dict(longitudinal_bundle.get("psa_forecast") or {})
    live_benchmark = dict(longitudinal_bundle.get("live_benchmark") or {})
    longitudinal_truth_snapshot = dict(
        longitudinal_bundle.get("longitudinal_truth_snapshot")
        or patient.get("longitudinal_truth_snapshot")
        or {}
    )
    decision_recalculation_trace = dict(
        longitudinal_bundle.get("decision_recalculation_trace")
        or patient.get("decision_recalculation_trace")
        or {}
    )
    decision_recalculation_trace["what_changed_today"] = _displayize_trace_items(
        decision_recalculation_trace.get("what_changed_today") or [],
        limit=6,
    )
    trace_visit = dict(decision_recalculation_trace.get("latest_clinically_decisive_visit") or {})
    if trace_visit:
        trace_visit["display_changed_fields"] = _displayize_field_list(
            trace_visit.get("changed_fields") or trace_visit.get("fields_changed") or [],
            limit=6,
        )
        trace_visit["display_source_type"] = normalize_source_label(trace_visit.get("source_type"))
        decision_recalculation_trace["latest_clinically_decisive_visit"] = trace_visit
    decision_recalculation_trace["display_changed_fields"] = _displayize_field_list(
        decision_recalculation_trace.get("display_changed_fields")
        or (
            (decision_recalculation_trace.get("latest_clinically_decisive_visit") or {}).get("changed_fields")
            or (decision_recalculation_trace.get("latest_clinically_decisive_visit") or {}).get("fields_changed")
            or []
        ),
        limit=6,
    )
    decision_recalculation_trace["display_visibility_status"] = normalize_ui_label(
        decision_recalculation_trace.get("visibility_status"),
        default="Contextual",
    )
    transition_resolution = dict(
        longitudinal_bundle.get("transition_resolution")
        or patient.get("transition_resolution")
        or {}
    )
    care_intent_contract = dict(
        longitudinal_bundle.get("care_intent_contract")
        or patient.get("care_intent_contract")
        or {}
    )
    decision_governance_bundle = dict(
        longitudinal_bundle.get("decision_governance_bundle")
        or patient.get("decision_governance_bundle")
        or latest_signal_snapshot.get("decision_governance_bundle")
        or {}
    )
    recommendation_block_status = (
        longitudinal_bundle.get("recommendation_block_status")
        or patient.get("recommendation_block_status")
        or latest_signal_snapshot.get("recommendation_block_status")
        or ""
    )
    recommendation_block_reason = (
        longitudinal_bundle.get("recommendation_block_reason")
        or patient.get("recommendation_block_reason")
        or latest_signal_snapshot.get("recommendation_block_reason")
        or ""
    )
    display_recommendation_block_reason = _displayize_recommendation_block_reason(
        recommendation_block_reason
    )
    allowed_actions_while_blocked = list(
        longitudinal_bundle.get("allowed_actions_while_blocked")
        or patient.get("allowed_actions_while_blocked")
        or latest_signal_snapshot.get("allowed_actions_while_blocked")
        or []
    )
    decision_blocking_bundle = dict(
        longitudinal_bundle.get("decision_blocking_bundle")
        or patient.get("decision_blocking_bundle")
        or latest_signal_snapshot.get("decision_blocking_bundle")
        or {}
    )
    diagnostic_certainty_bundle = dict(
        longitudinal_bundle.get("diagnostic_certainty_bundle")
        or patient.get("diagnostic_certainty_bundle")
        or latest_signal_snapshot.get("diagnostic_certainty_bundle")
        or {}
    )
    staging_certainty_bundle = dict(
        longitudinal_bundle.get("staging_certainty_bundle")
        or patient.get("staging_certainty_bundle")
        or latest_signal_snapshot.get("staging_certainty_bundle")
        or {}
    )
    minimum_decisive_dataset_bundle = dict(
        longitudinal_bundle.get("minimum_decisive_dataset_bundle")
        or patient.get("minimum_decisive_dataset_bundle")
        or latest_signal_snapshot.get("minimum_decisive_dataset_bundle")
        or {}
    )
    decision_evidence_currentness_bundle = dict(
        longitudinal_bundle.get("decision_evidence_currentness_bundle")
        or patient.get("decision_evidence_currentness_bundle")
        or latest_signal_snapshot.get("decision_evidence_currentness_bundle")
        or {}
    )
    therapeutic_window_bundle = dict(
        longitudinal_bundle.get("therapeutic_window_bundle")
        or patient.get("therapeutic_window_bundle")
        or latest_signal_snapshot.get("therapeutic_window_bundle")
        or {}
    )
    therapeutic_readiness_bundle = dict(
        longitudinal_bundle.get("therapeutic_readiness_bundle")
        or patient.get("therapeutic_readiness_bundle")
        or latest_signal_snapshot.get("therapeutic_readiness_bundle")
        or {}
    )
    window_worklist_bundle = dict(
        longitudinal_bundle.get("window_worklist_bundle")
        or patient.get("window_worklist_bundle")
        or latest_signal_snapshot.get("window_worklist_bundle")
        or {}
    )
    clinician_decision_capture_bundle = dict(
        longitudinal_bundle.get("clinician_decision_capture_bundle")
        or patient.get("clinician_decision_capture_bundle")
        or latest_signal_snapshot.get("clinician_decision_capture_bundle")
        or {}
    )
    state_transition_confirmation_bundle = dict(
        longitudinal_bundle.get("state_transition_confirmation_bundle")
        or patient.get("state_transition_confirmation_bundle")
        or latest_signal_snapshot.get("state_transition_confirmation_bundle")
        or {}
    )
    adherence_tracking_bundle = dict(
        longitudinal_bundle.get("adherence_tracking_bundle")
        or patient.get("adherence_tracking_bundle")
        or latest_signal_snapshot.get("adherence_tracking_bundle")
        or {}
    )
    tumor_board_outcome_bundle = dict(
        longitudinal_bundle.get("tumor_board_outcome_bundle")
        or patient.get("tumor_board_outcome_bundle")
        or latest_signal_snapshot.get("tumor_board_outcome_bundle")
        or {}
    )
    pro_decision_bundle = dict(
        longitudinal_bundle.get("pro_decision_bundle")
        or patient.get("pro_decision_bundle")
        or latest_signal_snapshot.get("pro_decision_bundle")
        or {}
    )
    shared_decision_bundle = dict(
        longitudinal_bundle.get("shared_decision_bundle")
        or patient.get("shared_decision_bundle")
        or latest_signal_snapshot.get("shared_decision_bundle")
        or {}
    )
    localized_modality_fitness_bundle = dict(
        longitudinal_bundle.get("localized_modality_fitness_bundle")
        or patient.get("localized_modality_fitness_bundle")
        or latest_signal_snapshot.get("localized_modality_fitness_bundle")
        or {}
    )
    localized_tradeoff_bundle = dict(
        longitudinal_bundle.get("localized_tradeoff_bundle")
        or patient.get("localized_tradeoff_bundle")
        or latest_signal_snapshot.get("localized_tradeoff_bundle")
        or {}
    )
    patient_priority_profile = dict(
        longitudinal_bundle.get("patient_priority_profile")
        or patient.get("patient_priority_profile")
        or latest_signal_snapshot.get("patient_priority_profile")
        or {}
    )
    ctdna_refinement_bundle = dict(
        longitudinal_bundle.get("ctdna_refinement_bundle")
        or patient.get("ctdna_refinement_bundle")
        or latest_signal_snapshot.get("ctdna_refinement_bundle")
        or {}
    )
    multimodal_imaging_concordance_bundle = dict(
        longitudinal_bundle.get("multimodal_imaging_concordance_bundle")
        or patient.get("multimodal_imaging_concordance_bundle")
        or latest_signal_snapshot.get("multimodal_imaging_concordance_bundle")
        or {}
    )
    precision_workflow_bundle = dict(
        longitudinal_bundle.get("precision_workflow_bundle")
        or patient.get("precision_workflow_bundle")
        or latest_signal_snapshot.get("precision_workflow_bundle")
        or {}
    )
    registry_core_bundle = dict(
        longitudinal_bundle.get("registry_core_bundle")
        or patient.get("registry_core_bundle")
        or latest_signal_snapshot.get("registry_core_bundle")
        or {}
    )
    endpoint_adjudication_bundle = dict(
        longitudinal_bundle.get("endpoint_adjudication_bundle")
        or patient.get("endpoint_adjudication_bundle")
        or latest_signal_snapshot.get("endpoint_adjudication_bundle")
        or {}
    )
    data_certainty_bundle = dict(
        longitudinal_bundle.get("data_certainty_bundle")
        or patient.get("data_certainty_bundle")
        or latest_signal_snapshot.get("data_certainty_bundle")
        or {}
    )
    ichom_compliance_bundle = dict(
        longitudinal_bundle.get("ichom_compliance_bundle")
        or patient.get("ichom_compliance_bundle")
        or latest_signal_snapshot.get("ichom_compliance_bundle")
        or {}
    )
    treatment_adverse_event_bundle = dict(
        longitudinal_bundle.get("treatment_adverse_event_bundle")
        or patient.get("treatment_adverse_event_bundle")
        or latest_signal_snapshot.get("treatment_adverse_event_bundle")
        or {}
    )
    population_survival_context_bundle = dict(
        longitudinal_bundle.get("population_survival_context_bundle")
        or patient.get("population_survival_context_bundle")
        or latest_signal_snapshot.get("population_survival_context_bundle")
        or {}
    )
    cost_access_context_bundle = dict(
        longitudinal_bundle.get("cost_access_context_bundle")
        or patient.get("cost_access_context_bundle")
        or latest_signal_snapshot.get("cost_access_context_bundle")
        or {}
    )
    score_interpretation_catalog_snapshot = dict(
        longitudinal_bundle.get("score_interpretation_catalog_snapshot")
        or patient.get("score_interpretation_catalog_snapshot")
        or latest_signal_snapshot.get("score_interpretation_catalog_snapshot")
        or {}
    )
    palliative_transition_bundle = dict(
        longitudinal_bundle.get("palliative_transition_bundle")
        or patient.get("palliative_transition_bundle")
        or latest_signal_snapshot.get("palliative_transition_bundle")
        or {}
    )
    palliative_monitoring_package = dict(
        longitudinal_bundle.get("palliative_monitoring_package")
        or patient.get("palliative_monitoring_package")
        or latest_signal_snapshot.get("palliative_monitoring_package")
        or {}
    )
    survivorship_transition_bundle = dict(
        longitudinal_bundle.get("survivorship_transition_bundle")
        or patient.get("survivorship_transition_bundle")
        or latest_signal_snapshot.get("survivorship_transition_bundle")
        or {}
    )
    survivorship_monitoring_package = dict(
        longitudinal_bundle.get("survivorship_monitoring_package")
        or patient.get("survivorship_monitoring_package")
        or latest_signal_snapshot.get("survivorship_monitoring_package")
        or {}
    )
    fallback_decision_input_requirements = dict(
        longitudinal_bundle.get("decision_input_requirements")
        or patient.get("decision_input_requirements")
        or {}
    )
    advanced_followup_bundle = dict(
        longitudinal_bundle.get("advanced_followup_bundle")
        or patient.get("advanced_followup_bundle")
        or latest_signal_snapshot.get("advanced_followup_bundle")
        or {}
    )
    if not advanced_followup_bundle:
        advanced_followup_bundle = build_advanced_followup_bundle(
            patient_record=patient,
            state=state,
            latest_assessment=raw_assessment,
            longitudinal_bundle=longitudinal_bundle,
            decision_input_requirements=fallback_decision_input_requirements,
            signals=latest_signal_snapshot,
        )
    staging_adjudication_bundle = dict(
        longitudinal_bundle.get("staging_adjudication_bundle")
        or patient.get("staging_adjudication_bundle")
        or latest_signal_snapshot.get("staging_adjudication_bundle")
        or {}
    )
    if not staging_adjudication_bundle:
        staging_adjudication_bundle = build_staging_adjudication_bundle(
            patient_record=patient,
            state=state,
            latest_assessment=raw_assessment,
            longitudinal_bundle=longitudinal_bundle,
            therapeutic_readiness_bundle=therapeutic_readiness_bundle,
            decision_input_requirements=fallback_decision_input_requirements,
            signals=latest_signal_snapshot,
        )
    fallback_decision_input_requirements = merge_staging_adjudication_into_requirements(
        fallback_decision_input_requirements,
        staging_adjudication_bundle,
    )
    advanced_release_gate = dict(
        longitudinal_bundle.get("advanced_release_gate")
        or patient.get("advanced_release_gate")
        or {}
    )
    if not advanced_release_gate:
        advanced_release_gate = build_advanced_release_gate(
            state=state,
            next_best_action=dict(latest_signal_snapshot.get("next_best_action") or {}),
            decision_input_requirements=fallback_decision_input_requirements,
            advanced_followup_bundle=advanced_followup_bundle,
            staging_adjudication_bundle=staging_adjudication_bundle,
            signals=dict(latest_signal_snapshot or {}),
        )
    fallback_decision_input_requirements = merge_advanced_release_gate_into_requirements(
        fallback_decision_input_requirements,
        advanced_release_gate,
    )
    supportive_care_toxicity_readiness_bundle = dict(
        longitudinal_bundle.get("supportive_care_toxicity_readiness_bundle")
        or patient.get("supportive_care_toxicity_readiness_bundle")
        or latest_signal_snapshot.get("supportive_care_toxicity_readiness_bundle")
        or {}
    )
    if not supportive_care_toxicity_readiness_bundle:
        supportive_care_toxicity_readiness_bundle = build_supportive_care_toxicity_readiness_bundle(
            patient_record=patient,
            state=state,
            management_track=management_track,
            latest_assessment=raw_assessment,
            clinical_fact_bundle=dict(
                longitudinal_bundle.get("clinical_fact_bundle")
                or patient.get("clinical_fact_bundle")
                or {}
            ),
            decision_input_requirements=fallback_decision_input_requirements,
            palliative_transition_bundle=palliative_transition_bundle,
            palliative_monitoring_package=palliative_monitoring_package,
            survivorship_transition_bundle=survivorship_transition_bundle,
            survivorship_monitoring_package=survivorship_monitoring_package,
        )
    snapshot_therapeutic_readiness_bundle = dict(
        latest_signal_snapshot.get("therapeutic_readiness_bundle") or {}
    )
    if snapshot_therapeutic_readiness_bundle:
        therapeutic_readiness_bundle = snapshot_therapeutic_readiness_bundle
    if not therapeutic_readiness_bundle:
        assessment_result_snapshot = dict((raw_assessment.get("result_snapshot", {}) if raw_assessment else {}) or {})
        clinical_fact_bundle = dict(
            longitudinal_bundle.get("clinical_fact_bundle")
            or patient.get("clinical_fact_bundle")
            or resolve_patient_clinical_facts(patient)
        )
        therapeutic_readiness_bundle = build_therapeutic_readiness_bundle(
            state=state,
            phenotype_state=str(latest_signal_snapshot.get("phenotype_state") or state or ""),
            preferred_regimen=dict(assessment_result_snapshot.get("preferred_frontline_regimen") or {}),
            next_best_action=dict(latest_signal_snapshot.get("next_best_action") or {}),
            decision_input_requirements=fallback_decision_input_requirements,
            comparative_eligibility_matrix=dict(
                patient.get("comparative_eligibility_matrix")
                or assessment_result_snapshot.get("comparative_eligibility_matrix")
                or {}
            ),
            systemic_regimen_scope_contract=dict(
                patient.get("systemic_regimen_scope_contract")
                or assessment_result_snapshot.get("systemic_regimen_scope_contract")
                or {}
            ),
            care_intent_contract=care_intent_contract,
            palliative_transition_bundle=palliative_transition_bundle,
            survivorship_transition_bundle=survivorship_transition_bundle,
            therapeutic_window_bundle=therapeutic_window_bundle,
            active_regimen_monitoring_package=dict(patient.get("active_regimen_monitoring_package") or {}),
            recommendation_block_status=recommendation_block_status,
            recommendation_block_reason=recommendation_block_reason,
            allowed_actions_while_blocked=allowed_actions_while_blocked,
            signals=dict(latest_signal_snapshot or {}),
            advanced_followup_bundle=advanced_followup_bundle,
            staging_adjudication_bundle=staging_adjudication_bundle,
            supportive_care_toxicity_readiness_bundle=supportive_care_toxicity_readiness_bundle,
            advanced_release_gate=advanced_release_gate,
            clinical_fact_bundle=clinical_fact_bundle,
        )
    therapeutic_readiness_bundle["display_required_to_release"] = (
        list(therapeutic_readiness_bundle.get("display_required_to_release") or [])
        or display_capture_field_summary(therapeutic_readiness_bundle.get("required_to_release") or [], limit=24)
        or normalize_field_list(therapeutic_readiness_bundle.get("required_to_release") or [], limit=24)
    )
    therapeutic_readiness_bundle["display_release_blockers"] = list(
        therapeutic_readiness_bundle.get("display_release_blockers")
        or therapeutic_readiness_bundle.get("display_required_to_release")
        or []
    )
    therapeutic_readiness_bundle["display_safety_blockers"] = list(
        therapeutic_readiness_bundle.get("display_safety_blockers")
        or normalize_field_list(
            list(therapeutic_readiness_bundle.get("safety_blockers") or [])
            + list(therapeutic_readiness_bundle.get("safety_watchouts") or []),
            limit=24,
        )
    )
    therapeutic_readiness_bundle["capture_actions"] = [
        _normalize_readiness_capture_action(dict(action or {}))
        for action in list(therapeutic_readiness_bundle.get("capture_actions") or [])
    ]
    therapeutic_readiness_bundle["display_release_actions"] = [
        {
            **dict(action),
            "display_fields_summary": list(action.get("display_fields_summary") or []),
        }
        for action in list(therapeutic_readiness_bundle.get("capture_actions") or [])
    ]
    surface_projection = build_surface_consistency_projection(
        patient,
        longitudinal_bundle,
        latest_assessment=raw_assessment,
        recommendations=recommendations or {},
        therapeutic_readiness_bundle=therapeutic_readiness_bundle,
    )
    clinical_kernel_snapshot = dict(surface_projection.get("clinical_kernel_snapshot") or {})
    effective_state = str(surface_projection.get("effective_state") or state)
    effective_recommendation_family = str(
        surface_projection.get("effective_recommendation_family")
        or therapeutic_readiness_bundle.get("candidate_family")
        or ""
    )
    surface_consistency_status = str(
        surface_projection.get("surface_consistency_status") or "consistent"
    )
    surface_consistency_flags = list(surface_projection.get("surface_consistency_flags") or [])
    legacy_recommendation_panel = dict(
        surface_projection.get("legacy_recommendation_panel") or {}
    )
    decision_blocking_fields = (
        decision_blocking_bundle.get("hard_blocking_inputs")
        or decision_blocking_bundle.get("decision_blocking_inputs")
        or []
    )
    decision_blocking_bundle["display_decision_blocking_inputs"] = (
        display_capture_field_summary(decision_blocking_fields, limit=24)
        or normalize_field_list(decision_blocking_fields, limit=24)
    )
    decision_governance_bundle["display_recommendation_block_reason"] = (
        display_recommendation_block_reason
    )
    palliative_monitoring_package["display_required_visit_fields"] = (
        display_capture_field_summary(palliative_monitoring_package.get("required_visit_fields") or [], limit=40)
        or normalize_field_list(palliative_monitoring_package.get("required_visit_fields") or [], limit=40)
    )
    palliative_monitoring_package["display_missing_inputs"] = normalize_field_list(
        palliative_monitoring_package.get("missing_inputs") or palliative_monitoring_package.get("stale_inputs") or [],
        limit=40,
    )
    survivorship_monitoring_package["display_required_visit_fields"] = (
        display_capture_field_summary(survivorship_monitoring_package.get("required_visit_fields") or [], limit=40)
        or normalize_field_list(survivorship_monitoring_package.get("required_visit_fields") or [], limit=40)
    )
    survivorship_monitoring_package["display_missing_inputs"] = normalize_field_list(
        survivorship_monitoring_package.get("missing_inputs") or survivorship_monitoring_package.get("stale_inputs") or [],
        limit=40,
    )
    rt_toxicity_timeline = _build_rt_toxicity_timeline(patient)
    survivorship_checklist = _build_survivorship_checklist(patient, latest_signal_snapshot)
    top_active_window = dict(window_worklist_bundle.get("top_active_window") or {})
    top_window_missing_fields = list(top_active_window.get("missing_decisive_fields") or [])
    top_active_window["display_missing_decisive_fields"] = (
        display_capture_field_summary(top_window_missing_fields, limit=24)
        or normalize_field_list(top_window_missing_fields, limit=24)
    )
    window_worklist_bundle["top_active_window"] = top_active_window
    window_blocking_fields = list(
        window_worklist_bundle.get("blocking_dataset_fields")
        or top_window_missing_fields
        or []
    )
    window_worklist_bundle["display_blocking_dataset_fields"] = (
        display_capture_field_summary(window_blocking_fields, limit=24)
        or normalize_field_list(window_blocking_fields, limit=24)
    )
    late_effects_profile = dict(
        longitudinal_bundle.get("late_effects_profile")
        or patient.get("late_effects_profile")
        or latest_signal_snapshot.get("late_effects_profile")
        or {}
    )
    functional_recovery_profile = dict(
        longitudinal_bundle.get("functional_recovery_profile")
        or patient.get("functional_recovery_profile")
        or latest_signal_snapshot.get("functional_recovery_profile")
        or {}
    )
    survivorship_schedule_overlay = dict(
        longitudinal_bundle.get("survivorship_schedule_overlay")
        or patient.get("survivorship_schedule_overlay")
        or latest_signal_snapshot.get("survivorship_schedule_overlay")
        or {}
    )
    survivorship_plan = dict(
        longitudinal_bundle.get("survivorship_plan")
        or patient.get("survivorship_plan")
        or latest_signal_snapshot.get("survivorship_plan")
        or {}
    )
    guideline_followup_plan = dict(
        longitudinal_bundle.get("guideline_followup_plan")
        or patient.get("guideline_followup_plan")
        or {}
    )
    crpc_copilot_bundle = dict(
        longitudinal_bundle.get("crpc_copilot_bundle")
        or latest_signal_snapshot.get("crpc_copilot_bundle")
        or {}
    )
    post_rp_salvage_bundle = dict(
        longitudinal_bundle.get("post_rp_salvage_bundle")
        or latest_signal_snapshot.get("post_rp_salvage_bundle")
        or {}
    )
    mhspc_copilot_bundle = dict(
        longitudinal_bundle.get("mhspc_copilot_bundle")
        or latest_signal_snapshot.get("mhspc_copilot_bundle")
        or {}
    )
    if is_mhspc_state(state):
        preferred_frontline_regimen = dict(mhspc_copilot_bundle.get("preferred_frontline_regimen") or {})
        frontline_ranking_trace = dict(mhspc_copilot_bundle.get("frontline_ranking_trace") or {})
        if preferred_frontline_regimen:
            rationale = list(preferred_frontline_regimen.get("selection_rationale") or [])
            winner_reason = normalize_text(frontline_ranking_trace.get("winner_reason"))
            current_trial_profile.update(
                {
                    "recommended_trial_backbone": [preferred_frontline_regimen.get("regimen_code", "")],
                    "recommended_trial_backbone_label": preferred_frontline_regimen.get("regimen_label", ""),
                    "recommended_trial_backbone_source": ", ".join((preferred_frontline_regimen.get("pivotal_trial_fit") or {}).get("matched_trials") or []),
                    "recommended_trial_backbone_note": winner_reason or " ".join(rationale[:2]) or "Esquema frontline individualizado según elegibilidad clínica, guideline fit y evidencia pivote.",
                    "preferred_frontline_regimen": preferred_frontline_regimen,
                    "recommended_component_drugs": list(preferred_frontline_regimen.get("component_drugs") or []),
                }
            )
            trial_benchmark_snapshot["current_trial_profile"] = current_trial_profile
    diagnostic_biopsy_bundle = dict(
        longitudinal_bundle.get("diagnostic_biopsy_bundle")
        or latest_signal_snapshot.get("diagnostic_biopsy_bundle")
        or {}
    )
    localized_surveillance_bundle = dict(
        longitudinal_bundle.get("localized_surveillance_bundle")
        or latest_signal_snapshot.get("localized_surveillance_bundle")
        or {}
    )
    post_rt_salvage_bundle = dict(
        longitudinal_bundle.get("post_rt_salvage_bundle")
        or latest_signal_snapshot.get("post_rt_salvage_bundle")
        or {}
    )
    for vertical_bundle in (
        crpc_copilot_bundle,
        post_rp_salvage_bundle,
        mhspc_copilot_bundle,
        diagnostic_biopsy_bundle,
        localized_surveillance_bundle,
        post_rt_salvage_bundle,
    ):
        if isinstance(vertical_bundle.get("blocking_inputs"), list):
            vertical_bundle["blocking_inputs"] = _decorate_blocking_input_groups(
                vertical_bundle.get("blocking_inputs") or []
            )
    _, active_copilot_bundle = select_primary_vertical_bundle(
        {
            "crpc_copilot_bundle": crpc_copilot_bundle,
            "post_rp_salvage_bundle": post_rp_salvage_bundle,
            "mhspc_copilot_bundle": mhspc_copilot_bundle,
            "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
            "localized_surveillance_bundle": localized_surveillance_bundle,
            "post_rt_salvage_bundle": post_rt_salvage_bundle,
        }
    )
    post_rt_failure_definition = dict(
        post_rt_salvage_bundle.get("post_rt_recurrence_bundle")
        or post_rt_salvage_bundle.get("post_rt_failure_definition")
        or {}
    )
    post_rt_transition_bundle = dict(post_rt_salvage_bundle.get("post_rt_transition_bundle") or {})
    post_rt_recurrence_profile = _build_post_rt_recurrence_profile(
        post_rt_failure_definition=post_rt_failure_definition,
        post_rt_transition_bundle=post_rt_transition_bundle,
        readiness_actions=list(therapeutic_readiness_bundle.get("capture_actions") or []),
    )
    latest_signal_snapshot["post_rt_recurrence_profile"] = post_rt_recurrence_profile
    laboratory_intelligence_profile = dict(
        longitudinal_bundle.get("laboratory_intelligence_profile")
        or patient.get("laboratory_intelligence_profile")
        or {}
    )
    latest_clinically_decisive_visit = dict(
        longitudinal_bundle.get("latest_clinically_decisive_visit")
        or patient.get("latest_clinically_decisive_visit")
        or decision_recalculation_trace.get("latest_clinically_decisive_visit")
        or {}
    )
    latest_clinically_decisive_visit["display_changed_fields"] = _displayize_field_list(
        latest_clinically_decisive_visit.get("changed_fields")
        or latest_clinically_decisive_visit.get("fields_changed")
        or [],
        limit=6,
    )
    latest_clinically_decisive_visit["display_source_type"] = normalize_source_label(
        latest_clinically_decisive_visit.get("source_type")
    )
    if not psa_forecast:
        from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast

        psa_forecast = build_psa_forecast(patient, state=state)

    # Faubot 2026-04-25 (LXIX) — Auditoría #64B
    # Wire backend #64A: forecast per-line + cohort overlay + combined timeline
    # Estos enrichments se exponen al template patient_profile.html para
    # render en drill-down panel #63D + chart overlay + combined timeline UI.
    psa_forecast_per_line: dict = {}
    psa_cohort_reference: dict = {}
    psa_combined_timeline: dict = {}
    try:
        from prostanet.domains.patient_tracking.psa_forecast import (
            build_psa_forecast_per_line,
            build_psa_cohort_reference_overlay,
            build_combined_patient_timeline,
        )
        psa_forecast_per_line = build_psa_forecast_per_line(patient)
        psa_cohort_reference = build_psa_cohort_reference_overlay(patient)
        # Pasar clinical_journey_events si están disponibles para auto-asignación
        # de events a treatment lines en combined timeline.
        # NOTA: clinical_journey_events se construye más abajo en este mismo
        # método; aquí pasamos None porque aún no está construido. El template
        # puede combinar manualmente o usar journey_events del bundle ya
        # entregado. Para una integración 100% E2E del timeline, ver #64C.
        psa_combined_timeline = build_combined_patient_timeline(
            patient,
            clinical_events=None,
        )
    except Exception:
        # Defensive: si falla cualquier helper, no romper el flujo del bundle
        # (estos son enrichments visuales, no bloqueantes para decisiones)
        pass

    if not live_benchmark:
        live_benchmark, snapshot_reliability = resolve_live_benchmark_from_snapshot(
            patient,
            state=benchmark_state,
            management_track=management_track,
        )
        if snapshot_reliability and not live_benchmark.get("reliability"):
            live_benchmark["reliability"] = dict(snapshot_reliability)
    forecast_reliability = dict(psa_forecast.get("reliability") or {})
    forecast_reliability["display_confidence_label"] = normalize_ui_text(
        forecast_reliability.get("confidence_label"),
        default="No disponible",
    )
    benchmark_reliability = dict(live_benchmark.get("reliability") or {})
    benchmark_reliability["display_confidence_label"] = normalize_ui_text(
        benchmark_reliability.get("confidence_label"),
        default="No disponible",
    )
    benchmark_reliability["display_cohort_tier"] = normalize_ui_text(
        benchmark_reliability.get("cohort_tier"),
        default="No disponible",
    )
    prognostic_impact_bundle = build_prognostic_impact_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        raw_assessment=raw_assessment,
        risk_tools_bundle=risk_tools_bundle,
        current_trial_profile=current_trial_profile,
    )
    backbone_alignment = dict(prognostic_impact_bundle.get("backbone_alignment") or {})
    if backbone_alignment:
        backbone_alignment["display_alignment_status"] = normalize_ui_text(
            backbone_alignment.get("alignment_status"),
            default="No disponible",
        )
        prognostic_impact_bundle["backbone_alignment"] = backbone_alignment
    latest_signal_snapshot.update(
        {
            "decision_governance_bundle": decision_governance_bundle,
            "recommendation_block_status": recommendation_block_status,
            "recommendation_block_reason": recommendation_block_reason,
            "display_recommendation_block_reason": display_recommendation_block_reason,
            "allowed_actions_while_blocked": allowed_actions_while_blocked,
            "decision_blocking_bundle": decision_blocking_bundle,
            "diagnostic_certainty_bundle": diagnostic_certainty_bundle,
            "staging_certainty_bundle": staging_certainty_bundle,
            "minimum_decisive_dataset_bundle": minimum_decisive_dataset_bundle,
            "therapeutic_window_bundle": therapeutic_window_bundle,
            "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
            "readiness_status": therapeutic_readiness_bundle.get("readiness_status", ""),
            "release_blockers": therapeutic_readiness_bundle.get("release_blockers", []),
            "safety_blockers": therapeutic_readiness_bundle.get("safety_blockers", []),
            "required_to_release": therapeutic_readiness_bundle.get("required_to_release", []),
            "display_release_actions": therapeutic_readiness_bundle.get("display_release_actions", []),
            "therapeutic_capture_actions": therapeutic_readiness_bundle.get("capture_actions", []),
            "next_best_action_if_not_ready": therapeutic_readiness_bundle.get("next_best_action_if_not_ready", {}),
            "competing_intent": therapeutic_readiness_bundle.get("competing_intent", {}),
            "window_worklist_bundle": window_worklist_bundle,
            "clinician_decision_capture_bundle": clinician_decision_capture_bundle,
            "state_transition_confirmation_bundle": state_transition_confirmation_bundle,
            "adherence_tracking_bundle": adherence_tracking_bundle,
            "tumor_board_outcome_bundle": tumor_board_outcome_bundle,
            "pro_decision_bundle": pro_decision_bundle,
            "shared_decision_bundle": shared_decision_bundle,
            "localized_modality_fitness_bundle": localized_modality_fitness_bundle,
            "localized_tradeoff_bundle": localized_tradeoff_bundle,
            "patient_priority_profile": patient_priority_profile,
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
            "score_interpretation_catalog_snapshot": score_interpretation_catalog_snapshot,
            "outcome_events_summary": adjudication_snapshot.get("outcome_events_summary", {}),
            "pending_adjudications": adjudication_snapshot.get("pending_adjudications", []),
            "current_response_state": adjudication_snapshot.get("current_response_state", {}),
            "current_course_status": adjudication_snapshot.get("current_course_status", ""),
            "last_adjudicated_event": adjudication_snapshot.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": trial_benchmark_snapshot.get("trial_endpoints", []),
            "current_trial_comparable_profile": trial_benchmark_snapshot.get("current_trial_profile", {}),
            "prognostic_modifiers": prognostic_impact_bundle.get("prognostic_modifiers", []),
            "prognostic_recommended_actions": prognostic_impact_bundle.get("recommended_actions", []),
            "prognostic_followup_impact": prognostic_impact_bundle.get("followup_impact", []),
            "prognostic_capture_targets": prognostic_impact_bundle.get("capture_targets", []),
            "backbone_alignment": prognostic_impact_bundle.get("backbone_alignment", {}),
            "cadence_adjusted_by": prognostic_impact_bundle.get("cadence_adjusted_by", []),
            "psa_forecast": psa_forecast,
            "forecast_reliability": forecast_reliability,
            # Faubot 2026-04-25 (LXIX) — Auditoría #64B
            # Wire backend #64A → frontend bundle:
            #   - psa_forecast_per_line: forecasts independientes por treatment line
            #   - psa_cohort_reference: curva de referencia poblacional (medianas pivotales)
            #   - psa_combined_timeline: estructura unificada PSA+treatment+events
            "psa_forecast_per_line": psa_forecast_per_line,
            "psa_cohort_reference": psa_cohort_reference,
            "psa_combined_timeline": psa_combined_timeline,
            "live_benchmark": live_benchmark,
            "benchmark_reliability": benchmark_reliability,
            "palliative_transition_bundle": palliative_transition_bundle,
            "palliative_monitoring_package": palliative_monitoring_package,
            "survivorship_transition_bundle": survivorship_transition_bundle,
            "survivorship_monitoring_package": survivorship_monitoring_package,
            "survivorship_checklist": survivorship_checklist,
            "late_effects_profile": late_effects_profile,
            "functional_recovery_profile": functional_recovery_profile,
            "survivorship_schedule_overlay": survivorship_schedule_overlay,
            "survivorship_plan": survivorship_plan,
            "rt_toxicity_timeline": rt_toxicity_timeline,
            "symptom_burden_profile": longitudinal_bundle.get("symptom_burden_profile") or patient.get("symptom_burden_profile") or {},
            "advance_care_planning_status": longitudinal_bundle.get("advance_care_planning_status") or patient.get("advance_care_planning_status") or {},
            "hospice_eligibility": longitudinal_bundle.get("hospice_eligibility") or patient.get("hospice_eligibility") or {},
            "acute_palliative_alerts": longitudinal_bundle.get("acute_palliative_alerts") or patient.get("acute_palliative_alerts") or [],
            "recommended_supportive_referrals": longitudinal_bundle.get("recommended_supportive_referrals") or patient.get("recommended_supportive_referrals") or [],
        }
    )
    transition_proposals = [
        proposal for proposal in (patient.get("transition_proposals") or [])
        if proposal.get("proposal_status") == "open"
        and transition_resolution.get("policy") == "manual_confirmation_required"
    ]
    document_board = _build_document_board(patient)
    copilot_sections = _decorate_copilot_sections(_build_copilot_sections(patient, state, management_track, raw_assessment))
    psa_observability = _build_psa_observability(patient, copilot_sections)
    psa_observability["display_source"] = normalize_source_label(psa_observability.get("source"))
    master_followup_plan = build_master_followup_plan(
        patient,
        state=state,
        management_track=management_track,
        agenda_board=agenda_board,
        signals=latest_signal_snapshot,
        copilot_alerts=copilot_sections.get("clinical_alerts") or patient.get("alerts") or [],
        next_best_action=latest_signal_snapshot.get("next_best_action") or {},
    )
    agenda_board["master_followup_plan"] = master_followup_plan
    agenda_board["master_followup_summary"] = master_followup_plan.get("summary", {})
    agenda_board["alerts_linked"] = master_followup_plan.get("blocking_alerts", [])
    copilot_modifiers = _build_parallel_modifier_bundle(copilot_sections, state)
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = assessment.get("display_result", {}) if assessment else {}
    advanced_panel_context = {}
    missing_inputs_by_panel = {}
    stage_specific_panels = _build_stage_specific_panels(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
        copilot_modifiers=copilot_modifiers,
        localized_modality_fitness_bundle=localized_modality_fitness_bundle,
        localized_tradeoff_bundle=localized_tradeoff_bundle,
        patient_priority_profile=patient_priority_profile,
    )
    if state in ADVANCED_STATES:
        stage_specific_panels, advanced_panel_context, missing_inputs_by_panel = _advanced_panels(
            patient,
            raw_assessment,
            raw_result,
            display_result,
            copilot_sections,
        )
        modifier_panel = _copilot_orientation_panel(copilot_modifiers or {})
        if modifier_panel:
            stage_specific_panels.append(modifier_panel)
    # EPIC 2 — Tarjetas clínicas universales (renal, Halabi, ADT, viscerales,
    # genomic classifiers, germline/somatic, medicamentos estructurados).
    # Se exponen en una sección dedicada del perfil para no mezclar datos
    # transversales con paneles específicos de etapa.
    epic2_clinical_cards = build_epic2_clinical_cards(patient, state=state)
    # EPIC 6 — Bundles universales (bone health NCCN PROS-I, germline NCCN
    # PROS-H y captura CTCAE v5 estructurada). Se construyen en todas las
    # etapas con defaults tolerantes; tone/summary alimentan tarjetas en UI.
    try:
        _epic6_patient = dict(patient)
        if state and not _epic6_patient.get("current_state"):
            _epic6_patient["current_state"] = state
        bone_health_bundle = build_bone_health_recommendation(_epic6_patient).to_dict()
    except Exception:
        bone_health_bundle = {
            "tone": "info",
            "summary": "Bone health bundle no disponible",
            "alerts": [],
            "missing_inputs": [],
        }
    try:
        germline_recommendation_bundle = should_offer_germline_testing(_epic6_patient).to_dict()
    except Exception:
        germline_recommendation_bundle = {
            "should_offer": False,
            "priority": "not_indicated",
            "reasons": [],
            "triggers_matched": [],
        }
    try:
        ctcae_capture_bundle = capture_ctcae_events(_epic6_patient).to_dict()
    except Exception:
        ctcae_capture_bundle = {
            "events": [],
            "burden": {},
            "narrative": "CTCAE no disponible",
            "tone": "info",
            "alerts": [],
            "legacy_fields_imported": [],
            "validation_errors": [],
        }
    # EPIC 7 — Bundles SDM (tradeoffs × prioridades), trial matching
    # (catálogo curado local) y elicitación Likert de preferencias.
    # Tolerantes a falta de datos: si no hay prioridades, la matriz igual
    # entrega outcomes por 100 pacientes para todas las modalidades
    # aplicables al grupo de riesgo NCCN.
    try:
        _epic7_patient = dict(_epic6_patient)
        if state and not _epic7_patient.get("state"):
            _epic7_patient["state"] = state
        sdm_tradeoff_bundle = build_tradeoff_matrix(_epic7_patient).to_dict()
    except Exception:
        sdm_tradeoff_bundle = {
            "risk_group_applied": "",
            "life_expectancy_band": "unknown",
            "priorities_active": [],
            "priorities_labels": [],
            "rows": [],
            "top_recommendation": "",
            "top_recommendation_reason": "Matriz SDM no disponible",
            "missing_inputs": [],
            "evidence_citations": [],
        }
    try:
        trial_matching_bundle = build_trial_matching_bundle(_epic7_patient)
    except Exception:
        trial_matching_bundle = {
            "total_trials_in_catalog": 0,
            "positive_match_count": 0,
            "matches": [],
            "ineligible": [],
            "catalog_source": "local_curated_v1",
            "disclaimer": "Matching de ensayos no disponible.",
        }
    try:
        _elicitation_answers = dict(patient.get("sdm_elicitation_answers") or {})
        sdm_elicitation_bundle = {
            "form": build_elicitation_form(),
            "result": score_elicitation(_elicitation_answers).to_dict(),
        }
    except Exception:
        sdm_elicitation_bundle = {
            "form": [],
            "result": {
                "items_evaluated": [],
                "priority_weights": {},
                "ranked_priorities": [],
                "unresolved_items": [],
                "narrative": "Elicitación SDM no disponible",
            },
        }
    # EPIC 8 — Bundles de screening poblacional (NCCN Early Detection v2.2026)
    # y terapia focal selectiva (NCCN PROS-C cat 2B). Los copilots se activan
    # sólo cuando el estado clínico corresponde (screening / focal_therapy /
    # localized_initial con señal focal) y devuelven un bundle latente en
    # otros carriles para que el template pueda renderizar placeholders.
    try:
        from prostanet.domains.patient_tracking.screening_copilot_service import (
            ScreeningCopilotService,
        )
        _screening_copilot = ScreeningCopilotService()
        screening_bundle = _screening_copilot.evaluate(
            dict(_epic7_patient),
            effective_state=state,
            latest_assessment=patient.get("latest_assessment"),
        )
    except Exception:
        screening_bundle = {
            "service_id": "screening_copilot",
            "status": "not_applicable",
            "state": state,
            "summary": "",
            "recommendation": "",
            "risk_group": "",
            "category": "",
            "interval_months": None,
            "start_age_recommended": None,
            "derive_to_workup": False,
            "workup_reasons": [],
            "evaluation": {},
        }
    try:
        from prostanet.domains.patient_tracking.focal_therapy_copilot_service import (
            FocalTherapyCopilotService,
        )
        _focal_copilot = FocalTherapyCopilotService()
        focal_therapy_bundle = _focal_copilot.evaluate(
            dict(_epic7_patient),
            effective_state=state,
            latest_assessment=patient.get("latest_assessment"),
        )
    except Exception:
        focal_therapy_bundle = {
            "service_id": "focal_therapy_copilot",
            "status": "not_applicable",
            "state": state,
            "summary": "",
            "recommendation": "",
            "eligible": False,
            "risk_group": "",
            "modality_recommended": "",
            "cautions": [],
            "contraindications": [],
            "durations_and_conditions": [],
            "evaluation": {},
        }
    if diagnosis_context.get("official_diagnosis_missing_fields_raw"):
        missing_inputs_by_panel["official_diagnosis"] = diagnosis_context.get("official_diagnosis_missing_fields_raw", [])
    pivotal_panel = _build_pivotal_panel(patient.get("pivotal_matches", []), state=state)
    evidence_applicability = _build_evidence_applicability(
        state=state,
        pivotal_panel=pivotal_panel,
        display_assessment=assessment,
    )
    cohort_completeness = compute_patient_cohort_completeness(patient, state)
    research_readiness = compute_patient_research_readiness(patient, state)
    endpoint_readiness = compute_patient_endpoint_readiness(patient, state)
    patient_kpis = build_patient_kpis(
        patient,
        state=state,
        management_track=management_track,
        agenda_board=agenda_board,
        signals=latest_signal_snapshot,
    )
    missing_input_actions, intake_capture_target, followup_capture_target = _build_missing_input_actions(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=agenda_board.get("therapy_checkpoints", []),
        agenda_items=active_agenda_items,
        copilot=copilot_sections,
    )
    capture_bundle = build_missing_input_capture_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=agenda_board.get("therapy_checkpoints", []),
        agenda_items=active_agenda_items,
        copilot=copilot_sections,
    )
    current_response_state = dict(adjudication_snapshot.get("current_response_state") or {})
    if current_response_state:
        current_response_state["display_label"] = normalize_ui_text(current_response_state.get("label"), default="")
        adjudication_snapshot["current_response_state"] = current_response_state
    last_adjudicated_event = dict(adjudication_snapshot.get("last_adjudicated_event") or {})
    if last_adjudicated_event:
        last_adjudicated_event["display_summary"] = normalize_ui_text(
            last_adjudicated_event.get("summary"),
            default="Sin evento adjudicado visible",
        )
        last_adjudicated_event["display_axis"] = normalize_ui_text(last_adjudicated_event.get("axis"), default="")
        adjudication_snapshot["last_adjudicated_event"] = last_adjudicated_event
    adjudication_snapshot["current_course_status_display"] = normalize_ui_text(
        adjudication_snapshot.get("current_course_status"),
        default="Sin estado adjudicado aún.",
    )
    psa_observability["forecast"] = psa_forecast
    response_visualization = dict(copilot_sections.get("response_visualization") or {})
    psa_trajectory = dict(response_visualization.get("psa_trajectory") or {})
    derived_waterfall = []
    try:
        from prostanet.domains.reporting.response_visualization import build_waterfall_from_line_segments

        derived_waterfall = build_waterfall_from_line_segments(psa_observability.get("line_segments") or [])
    except Exception:
        derived_waterfall = []
    if psa_observability.get("points") and not psa_trajectory.get("points"):
        psa_trajectory["points"] = list(psa_observability.get("points") or [])
    if psa_observability.get("treatment_bands") and not psa_trajectory.get("treatment_bands"):
        psa_trajectory["treatment_bands"] = list(psa_observability.get("treatment_bands") or [])
    integrated_timeline = dict(psa_trajectory.get("integrated_treatment_timeline") or {})
    axis_dates = set(psa_trajectory.get("axis_dates") or [])
    axis_dates.update(point.get("date") for point in (psa_trajectory.get("points") or []) if point.get("date"))
    psa_trajectory["forecast_curve"] = list(psa_forecast.get("forecast_curve") or [])
    psa_trajectory["forecast_points"] = list(psa_forecast.get("forecast_points") or [])
    psa_trajectory["forecast_status"] = psa_forecast.get("status", "")
    psa_trajectory["forecast_reliability"] = forecast_reliability
    axis_dates.update(point.get("date") for point in (psa_forecast.get("forecast_curve") or []) if point.get("date"))
    if integrated_timeline:
        integrated_axis_dates = set(integrated_timeline.get("axis_dates") or [])
        integrated_axis_dates.update(axis_dates)
        integrated_timeline["axis_dates"] = sorted(date_text for date_text in integrated_axis_dates if date_text)
        psa_trajectory["integrated_treatment_timeline"] = integrated_timeline
    psa_trajectory["axis_dates"] = sorted(date_text for date_text in axis_dates if date_text)
    psa_trajectory["has_data"] = bool(
        psa_trajectory.get("points")
        or (psa_trajectory.get("integrated_treatment_timeline") or {}).get("has_integrated_timeline")
    )
    if derived_waterfall:
        response_visualization["waterfall"] = derived_waterfall
    response_visualization["psa_trajectory"] = psa_trajectory
    copilot_sections["response_visualization"] = response_visualization
    clinical_journey_events = _build_clinical_journey_events(patient, state)
    for line_event in psa_observability.get("line_events") or []:
        if line_event not in clinical_journey_events:
            clinical_journey_events.append(line_event)
    clinical_journey_events = sorted(
        [event for event in clinical_journey_events if event.get("date")],
        key=lambda item: str(item.get("date")),
        reverse=True,
    )[:24]
    agenda_resolution_trace = _build_agenda_resolution_trace(archived_agenda_items)
    clinical_compass = _build_clinical_compass(
        patient=patient,
        state=state,
        reconciliation=reconciliation,
        display_assessment=assessment,
        raw_assessment=raw_assessment,
        state_timeline=state_timeline,
        diagnosis_context=diagnosis_context,
        copilot_modifiers=copilot_modifiers,
        next_best_action=latest_signal_snapshot.get("next_best_action", {}),
        decision_recalculation_trace=decision_recalculation_trace,
        longitudinal_truth_snapshot=longitudinal_truth_snapshot,
        guideline_followup_plan=guideline_followup_plan,
        care_intent_contract=care_intent_contract,
    )
    # Iteración C (GodiBot v1) — segunda opinión adversarial sobre el compass
    # recién construido. Tiempo real, modo sugerencia + bloqueo solo en
    # hard_block real. Fallback graceful si el módulo no está disponible.
    godibot_review: dict[str, Any] = {}
    try:
        from prostanet.agents.godibot import run_godibot_review
        godibot_review = run_godibot_review(
            patient,
            patient_id=int(patient.get("id") or patient.get("patient_id") or 0),
            compass=clinical_compass,
            enable_llm=False,  # LLM disabled en runtime por defecto (latencia)
        )
    except Exception as _godibot_exc:  # pragma: no cover - defensive
        godibot_review = {
            "status": "approved",
            "confidence": 1.0,
            "discrepancies": [],
            "version": "godibot-v1",
            "error": str(_godibot_exc),
        }
    profile_decision_view_model = _build_profile_decision_view_model(
        clinical_compass=clinical_compass,
        care_intent_contract=care_intent_contract,
        next_best_action=latest_signal_snapshot.get("next_best_action", {}),
        management_track=management_track,
        state=state,
    )
    clinical_copy_bundle = _build_clinical_copy_bundle(
        state=state,
        clinical_compass=clinical_compass,
        diagnosis_context=diagnosis_context,
        care_intent_contract=care_intent_contract,
        next_best_action=latest_signal_snapshot.get("next_best_action", {}),
        triplet_decision=triplet_decision,
        metastatic_state_bundle=longitudinal_bundle.get("metastatic_state_bundle", {}),
        signal_snapshot=latest_signal_snapshot,
    )
    advanced_therapy_decision_panel = build_advanced_therapy_decision_panel(
        state=state,
        therapeutic_readiness_bundle=therapeutic_readiness_bundle,
        active_copilot_bundle=active_copilot_bundle,
        local_adjuncts_visible=list(clinical_copy_bundle.get("local_adjuncts_visible") or []),
    )
    decision_evidence_currentness_bundle["display_refresh_actions"] = list(
        decision_evidence_currentness_bundle.get("display_refresh_actions")
        or decision_evidence_currentness_bundle.get("refresh_actions")
        or []
    )
    decision_evidence_currentness_bundle["display_stale_evidence_fields"] = _displayize_field_list(
        decision_evidence_currentness_bundle.get("stale_evidence_fields") or [],
        limit=8,
    )
    decision_evidence_currentness_bundle["display_aging_evidence_fields"] = _displayize_field_list(
        decision_evidence_currentness_bundle.get("aging_evidence_fields") or [],
        limit=8,
    )
    decision_evidence_currentness_bundle["display_traceability_gaps"] = _displayize_field_list(
        decision_evidence_currentness_bundle.get("traceability_gaps") or [],
        limit=8,
    )
    staging_adjudication_bundle["display_discordant_fields"] = _displayize_field_list(
        staging_adjudication_bundle.get("discordant_fields") or [],
        limit=8,
    )
    staging_adjudication_bundle["display_superseded_evidence"] = _displayize_field_list(
        staging_adjudication_bundle.get("superseded_evidence") or [],
        limit=8,
    )
    staging_adjudication_bundle["display_current_context_basis"] = normalize_field_list(
        staging_adjudication_bundle.get("current_context_basis") or [],
        limit=6,
    )
    supportive_care_toxicity_readiness_bundle["display_required_support_actions"] = normalize_field_list(
        supportive_care_toxicity_readiness_bundle.get("required_support_actions") or [],
        limit=8,
    )
    supportive_care_toxicity_readiness_bundle["display_missing_support_inputs"] = _displayize_field_list(
        supportive_care_toxicity_readiness_bundle.get("missing_support_inputs") or [],
        limit=8,
    )
    supportive_care_toxicity_readiness_bundle["display_stale_support_inputs"] = _displayize_field_list(
        supportive_care_toxicity_readiness_bundle.get("stale_support_inputs") or [],
        limit=8,
    )
    latest_signal_snapshot["advanced_therapy_decision_panel"] = advanced_therapy_decision_panel
    latest_signal_snapshot["decision_evidence_currentness_bundle"] = decision_evidence_currentness_bundle
    latest_signal_snapshot["staging_adjudication_bundle"] = staging_adjudication_bundle
    latest_signal_snapshot["supportive_care_toxicity_readiness_bundle"] = supportive_care_toxicity_readiness_bundle
    clinical_readiness_tower = dict(
        longitudinal_bundle.get("clinical_readiness_tower")
        or patient.get("clinical_readiness_tower")
        or latest_signal_snapshot.get("clinical_readiness_tower")
        or {}
    )
    if not clinical_readiness_tower:
        try:
            from prostanet.domains.patient_tracking.clinical_readiness_tower import (
                build_clinical_readiness_tower,
            )

            tower_bundle = {
                **dict(longitudinal_bundle or {}),
                "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
                "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
                "decision_input_requirements": fallback_decision_input_requirements,
                "signals": latest_signal_snapshot,
            }
            clinical_readiness_tower = build_clinical_readiness_tower(
                patient,
                longitudinal_bundle=tower_bundle,
                state=state,
                management_track=management_track,
                patient_ref=str((patient.get("identity") or {}).get("nss") or patient.get("nss") or ""),
            )
        except Exception:
            clinical_readiness_tower = {}
    latest_signal_snapshot["clinical_readiness_tower"] = clinical_readiness_tower
    tumor_board_os = dict(
        longitudinal_bundle.get("tumor_board_os")
        or patient.get("tumor_board_os")
        or latest_signal_snapshot.get("tumor_board_os")
        or {}
    )
    if not tumor_board_os:
        try:
            from prostanet.domains.patient_tracking.tumor_board_os import build_tumor_board_os

            tumor_board_bundle = {
                **dict(longitudinal_bundle or {}),
                "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
                "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
                "decision_input_requirements": fallback_decision_input_requirements,
                "clinical_readiness_tower": clinical_readiness_tower,
                "signals": latest_signal_snapshot,
            }
            tumor_board_os = build_tumor_board_os(
                patient,
                longitudinal_bundle=tumor_board_bundle,
                state=state,
                management_track=management_track,
                patient_ref=str((patient.get("identity") or {}).get("nss") or patient.get("nss") or ""),
            )
        except Exception:
            tumor_board_os = {}
    latest_signal_snapshot["tumor_board_os"] = tumor_board_os
    care_pathway_os = dict(
        longitudinal_bundle.get("care_pathway_os")
        or patient.get("care_pathway_os")
        or latest_signal_snapshot.get("care_pathway_os")
        or {}
    )
    if not care_pathway_os:
        try:
            from prostanet.domains.patient_tracking.care_pathway_os import build_care_pathway_os

            care_pathway_bundle = {
                **dict(longitudinal_bundle or {}),
                "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
                "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
                "decision_input_requirements": fallback_decision_input_requirements,
                "clinical_readiness_tower": clinical_readiness_tower,
                "tumor_board_os": tumor_board_os,
                "signals": latest_signal_snapshot,
            }
            care_pathway_os = build_care_pathway_os(
                patient,
                longitudinal_bundle=care_pathway_bundle,
                state=state,
                management_track=management_track,
                patient_ref=str((patient.get("identity") or {}).get("nss") or patient.get("nss") or ""),
            )
        except Exception:
            care_pathway_os = {}
    latest_signal_snapshot["care_pathway_os"] = care_pathway_os
    clinical_memory_os = dict(
        longitudinal_bundle.get("clinical_memory_os")
        or patient.get("clinical_memory_os")
        or latest_signal_snapshot.get("clinical_memory_os")
        or {}
    )
    if not clinical_memory_os:
        try:
            from prostanet.domains.patient_tracking.clinical_memory_os import build_clinical_memory_os

            clinical_memory_bundle = {
                **dict(longitudinal_bundle or {}),
                "clinical_readiness_tower": clinical_readiness_tower,
                "tumor_board_os": tumor_board_os,
                "care_pathway_os": care_pathway_os,
                "signals": latest_signal_snapshot,
            }
            clinical_memory_os = build_clinical_memory_os(
                patient,
                longitudinal_bundle=clinical_memory_bundle,
                state=state,
                management_track=management_track,
                patient_ref=str((patient.get("identity") or {}).get("nss") or patient.get("nss") or ""),
            )
        except Exception:
            clinical_memory_os = {}
    latest_signal_snapshot["clinical_memory_os"] = clinical_memory_os
    clinical_compass["display_decision_changing_inputs"] = normalize_field_list(
        clinical_compass.get("decision_changing_inputs") or [],
        limit=8,
    )
    surface_consistency_flags = list(
        dict.fromkeys(
            [
                *surface_consistency_flags,
                *list(clinical_copy_bundle.get("copy_consistency_flags") or []),
                *list(profile_decision_view_model.get("consistency_flags") or []),
            ]
        )
    )
    if surface_consistency_flags:
        surface_consistency_status = "requires_review"
    profile_decision_consistency = {
        "is_consistent": bool(profile_decision_view_model.get("is_consistent", True)),
        "flags": list(profile_decision_view_model.get("consistency_flags") or []),
    }
    systemic_regimen_scope_contract = dict(
        longitudinal_bundle.get("systemic_regimen_scope_contract")
        or (raw_assessment.get("result_snapshot", {}) if raw_assessment else {}).get("systemic_regimen_scope_contract")
        or build_systemic_regimen_scope_contract(
            state,
            (raw_assessment.get("result_snapshot", {}) if raw_assessment else {}) or {},
        )
    )
    identity_summary = {
        "baseline_psa_display": normalize_numeric_with_unit(
            patient.get("baseline", {}).get("baseline_psa"),
            "ng/mL",
        ),
    }
    if copilot_sections.get("therapeutic_fitness"):
        therapeutic_fitness = dict(copilot_sections.get("therapeutic_fitness") or {})
        if isinstance(therapeutic_fitness.get("frailty"), dict):
            therapeutic_fitness["frailty"] = {
                **therapeutic_fitness["frailty"],
                "status_label": normalize_ui_label(therapeutic_fitness["frailty"].get("status"), default="No disponible"),
                "display_missing_inputs": _displayize_field_list((therapeutic_fitness["frailty"] or {}).get("missing_inputs") or [], limit=8),
            }
        if isinstance(therapeutic_fitness.get("fit_score"), dict):
            therapeutic_fitness["fit_score"] = {
                **therapeutic_fitness["fit_score"],
                "category_label": normalize_ui_label(therapeutic_fitness["fit_score"].get("category"), default="No disponible"),
                "display_missing_inputs": _displayize_field_list((therapeutic_fitness["fit_score"] or {}).get("missing_inputs") or [], limit=8),
            }
        copilot_sections["therapeutic_fitness"] = therapeutic_fitness
    psa_forecast["status_label"] = normalize_ui_label(psa_forecast.get("status"), default="No disponible")

    # ── SPRINT 5 — Biomarker workup checklist (FAUBOT CXLIII) ───────────
    # Para cada paciente, evaluar si tiene workup HRR + PSMA-PET pendiente
    # (NCCN PROS-2 cat 1, label FDA VISION/PROfound). Cierra los 16
    # blocked_hard del baseline CXLII transformando "blocked sin acción"
    # en "blocked con acción concreta + guideline + unblock criterion".
    try:
        from prostanet.domains.decisions.biomarker_workup_engine import (
            build_biomarker_workup_bundle,
        )
        _biomarker_workup_bundle = build_biomarker_workup_bundle(patient)
    except Exception as _bwexc:
        logger.debug("Sprint5 biomarker_workup_bundle failed: %s", _bwexc)
        _biomarker_workup_bundle = {
            "available": False,
            "reason": f"engine_unavailable: {type(_bwexc).__name__}",
            "pending_actions_count": 0,
            "any_pending": False,
        }

    # ── EPIC GVP.E PROPAGATION FIX (FAUBOT CXLII) ────────────────────────
    # GodiBot adversarial validator reads gates from `compass.pivotal_contraindication_gates`
    # (see `prostanet/agents/godibot.py:392`). When raw_assessment.result_snapshot does NOT
    # carry the gates (paciente nuevo, snapshot incompleto, decision_agent skip), the panel
    # builder lazy-evaluates them but stores the result under a *different* key
    # (`pivotal_contraindication_gates_panel`). That asymmetry was the root cause of the
    # 4 blocked_hard at the baseline cohort audit (92% Internal Validation):
    # GodiBot saw "compass omits gate X" while UI panel actually rendered it.
    #
    # Fix: compute the raw gate list ONCE here, then expose it under the EXACT key GodiBot
    # reads. This closes the bug both retroactively (re-render of existing patients) AND
    # prospectively (every new patient registered after CXLII).
    _raw_result_for_gates = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    _compass_pivotal_gates_raw = list(_raw_result_for_gates.get("pivotal_contraindication_gates") or [])
    if not _compass_pivotal_gates_raw:
        try:
            _compass_pivotal_gates_raw = _lazy_evaluate_pivotal_gates_for_patient(patient)
        except Exception as _gvpe_exc:
            logger.debug("GVP.E gates propagation lazy-eval failed: %s", _gvpe_exc)
            _compass_pivotal_gates_raw = []

    # EPIC 48.A — Cambiamos de `return {...}` a `bundle = {...}` para poder
    # inyectar decision_narrative al final (necesita acceso a todo el bundle
    # ya construido: compass + twin + fusion + gates + trajectory + ml).
    bundle = {
        "diagnostic_state": diagnostic_state,
        "management_track": management_track,
        "reconciled_state": state,
        "reconciled_management_track": management_track,
        "schedule_state": patient.get("schedule_state", state),
        "schedule_management_track": patient.get("schedule_management_track", management_track),
        "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "clinical_compass": clinical_compass,
        "clinical_copy_bundle": clinical_copy_bundle,
        "metastatic_state_bundle": longitudinal_bundle.get("metastatic_state_bundle", {}),
        "metastatic_stage_resolved": longitudinal_bundle.get("metastatic_stage_resolved", ""),
        "metastatic_stage_label": longitudinal_bundle.get("metastatic_stage_label", ""),
        "metastatic_detection_basis": longitudinal_bundle.get("metastatic_detection_basis", ""),
        "nmcrpc_eligible": longitudinal_bundle.get("nmcrpc_eligible"),
        "nmcrpc_ineligibility_reason": longitudinal_bundle.get("nmcrpc_ineligibility_reason", ""),
        "restaging_update_required": longitudinal_bundle.get("restaging_update_required", False),
        "restaging_currentness_status": longitudinal_bundle.get("restaging_currentness_status", ""),
        "restaging_update_reason": longitudinal_bundle.get("restaging_update_reason", ""),
        "progression_verification_required": longitudinal_bundle.get("progression_verification_required", False),
        "progression_verification_missing_fields": longitudinal_bundle.get("progression_verification_missing_fields", []),
        "profile_decision_view_model": profile_decision_view_model,
        "profile_decision_consistency": profile_decision_consistency,
        "systemic_regimen_scope": (
            longitudinal_bundle.get("systemic_regimen_scope")
            or (raw_assessment.get("result_snapshot", {}) if raw_assessment else {}).get("systemic_regimen_scope")
            or systemic_regimen_scope_contract.get("scope")
            or "not_applicable"
        ),
        "systemic_regimen_scope_contract": systemic_regimen_scope_contract,
        "identity_summary": identity_summary,
        "ui_normalized_labels": {
            "psa_forecast_status": psa_forecast.get("status_label", ""),
            "baseline_psa": identity_summary.get("baseline_psa_display", "No disponible"),
        },
        "value_availability_flags": {
            "baseline_psa": identity_summary.get("baseline_psa_display") != "No disponible",
            "last_decisive_data": bool(profile_decision_view_model.get("last_decisive_data", {}).get("source") or profile_decision_view_model.get("last_decisive_data", {}).get("date")),
        },
        "official_diagnosis": diagnosis_context.get("official_diagnosis", ""),
        "official_diagnosis_status": diagnosis_context.get("official_diagnosis_status", "missing"),
        "official_diagnosis_missing_fields": diagnosis_context.get("official_diagnosis_missing_fields", []),
        "official_diagnosis_source_summary": diagnosis_context.get("official_diagnosis_source_summary", ""),
        "operational_module_label": diagnosis_context.get("operational_module_label", operational_module_label),
        "risk_tools_panel": risk_tools_bundle.get("cards", []),
        "upgrade_panel": risk_tools_bundle.get("upgrade_panel", {}),
        "risk_tool_missing_inputs": risk_tools_bundle.get("missing_inputs", []),
        "risk_tool_fidelity_summary": risk_tools_bundle.get("fidelity_summary", {}),
        "prognostic_modifiers": prognostic_impact_bundle.get("prognostic_modifiers", []),
        "prognostic_recommended_actions": prognostic_impact_bundle.get("recommended_actions", []),
        "prognostic_followup_impact": prognostic_impact_bundle.get("followup_impact", []),
        "prognostic_capture_targets": prognostic_impact_bundle.get("capture_targets", []),
        "backbone_alignment": prognostic_impact_bundle.get("backbone_alignment", {}),
        "cadence_adjusted_by": prognostic_impact_bundle.get("cadence_adjusted_by", []),
        "triplet_decision": triplet_decision,
        "triplet_decision_card": triplet_decision,
        "stage_specific_panels": stage_specific_panels,
        "epic2_clinical_cards": epic2_clinical_cards,
        "bone_health_bundle": bone_health_bundle,
        "germline_recommendation_bundle": germline_recommendation_bundle,
        "ctcae_capture_bundle": ctcae_capture_bundle,
        "sdm_tradeoff_bundle": sdm_tradeoff_bundle,
        "trial_matching_bundle": trial_matching_bundle,
        "sdm_elicitation_bundle": sdm_elicitation_bundle,
        "screening_bundle": screening_bundle,
        "focal_therapy_bundle": focal_therapy_bundle,
        "algorithm_panels": _build_algorithm_panels(
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        ),
        "module_data_contracts": _module_data_contracts(),
        "pivotal_panel": pivotal_panel,
        # Faubot 2026-04-25 (VIII) — UI card de gates pivotal disparados.
        # Hace visible al clínico la cadena de razonamiento (CÓMO + POR QUÉ)
        # de los 18 gates centralizados en `pivotal_contraindication_gates.py`.
        # EPIC GVP.E (FAUBOT CXLII): pasamos `patient` para que el builder
        # pueda lazy-evaluate gates si raw_assessment.pivotal_contraindication_
        # gates viene vacío. Esto cierra los 4 blocked_hard del baseline donde
        # GodiBot detectaba gates pero compass no los exponía → bug de
        # propagación arquitectónico.
        "pivotal_contraindication_gates_panel": _build_pivotal_contraindication_gates_panel(
            raw_assessment, patient=patient,
        ),
        # EPIC GVP.E PROPAGATION FIX (FAUBOT CXLII): Sibling raw list bajo el key EXACTO
        # que GodiBot inspecciona (`compass.pivotal_contraindication_gates`, godibot.py:392).
        # Cierra el bug `gate_omitted:*` que disparaba false-positive blocked_hard cuando
        # raw_assessment.result_snapshot venía vacío pero los gates SÍ aplicaban al paciente.
        "pivotal_contraindication_gates": _compass_pivotal_gates_raw,
        # SPRINT 5 (FAUBOT CXLIII): Biomarker workup checklist — convierte cada blocked_hard
        # del baseline CXLII en acción concreta para el clínico (HRR + PSMA-PET pre-PARP/Lu-177).
        # NCCN PROS-2 cat 1 + FDA VISION/PROfound labels.
        "biomarker_workup": _biomarker_workup_bundle,
        "evidence_applicability": evidence_applicability,
        "advanced_panel_context": advanced_panel_context,
        "therapy_catalog_options": therapy_select_options(state=state, management_track=management_track, include_empty=True),
        "missing_inputs_by_panel": missing_inputs_by_panel,
        "missing_input_actions": missing_input_actions,
        "missing_input_capture_tasks": capture_bundle.get("tasks", []),
        "intake_capture_target": intake_capture_target,
        "followup_capture_target": followup_capture_target,
        "intake_completion_block": capture_bundle.get("intake_completion_block", {}),
        "followup_completion_block": capture_bundle.get("followup_completion_block", {}),
        "clinical_journey_events": clinical_journey_events,
        "psa_observability": psa_observability,
        "psa_forecast": psa_forecast,
        "forecast_reliability": forecast_reliability,
        "live_benchmark": live_benchmark,
        "benchmark_reliability": benchmark_reliability,
        "psma_structured_profile": patient.get("psma_structured_profile", {}),
        "psma_decision_impact": patient.get("psma_decision_impact", {}),
        "longitudinal_truth_snapshot": longitudinal_truth_snapshot,
        "decision_recalculation_trace": decision_recalculation_trace,
        "transition_resolution": transition_resolution,
        "decision_governance_bundle": decision_governance_bundle,
        "recommendation_block_status": recommendation_block_status,
        "recommendation_block_reason": recommendation_block_reason,
        "display_recommendation_block_reason": display_recommendation_block_reason,
        "allowed_actions_while_blocked": allowed_actions_while_blocked,
        "decision_blocking_bundle": decision_blocking_bundle,
        "diagnostic_certainty_bundle": diagnostic_certainty_bundle,
        "staging_certainty_bundle": staging_certainty_bundle,
        "minimum_decisive_dataset_bundle": minimum_decisive_dataset_bundle,
        "decision_evidence_currentness_bundle": decision_evidence_currentness_bundle,
        "therapeutic_window_bundle": therapeutic_window_bundle,
        "therapeutic_readiness_bundle": therapeutic_readiness_bundle,
        "clinical_readiness_tower": clinical_readiness_tower,
        "tumor_board_os": tumor_board_os,
        "care_pathway_os": care_pathway_os,
        "clinical_memory_os": clinical_memory_os,
        "advanced_therapy_decision_panel": advanced_therapy_decision_panel,
        "readiness_status": therapeutic_readiness_bundle.get("readiness_status", ""),
        "release_blockers": therapeutic_readiness_bundle.get("release_blockers", []),
        "safety_blockers": therapeutic_readiness_bundle.get("safety_blockers", []),
        "supportive_readiness_status": therapeutic_readiness_bundle.get("supportive_readiness_status", ""),
        "required_support_actions": therapeutic_readiness_bundle.get("required_support_actions", []),
        "hard_support_blockers": therapeutic_readiness_bundle.get("hard_support_blockers", []),
        "required_to_release": therapeutic_readiness_bundle.get("required_to_release", []),
        "therapeutic_capture_actions": therapeutic_readiness_bundle.get("capture_actions", []),
        "next_best_action_if_not_ready": therapeutic_readiness_bundle.get("next_best_action_if_not_ready", {}),
        "competing_intent": therapeutic_readiness_bundle.get("competing_intent", {}),
        "advanced_followup_bundle": advanced_followup_bundle,
        "staging_adjudication_bundle": staging_adjudication_bundle,
        "supportive_care_toxicity_readiness_bundle": supportive_care_toxicity_readiness_bundle,
        "window_worklist_bundle": window_worklist_bundle,
        "localized_modality_fitness_bundle": localized_modality_fitness_bundle,
        "localized_tradeoff_bundle": localized_tradeoff_bundle,
        "patient_priority_profile": patient_priority_profile,
        "clinician_decision_capture_bundle": clinician_decision_capture_bundle,
        "state_transition_confirmation_bundle": state_transition_confirmation_bundle,
        "adherence_tracking_bundle": adherence_tracking_bundle,
        "tumor_board_outcome_bundle": tumor_board_outcome_bundle,
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
        "score_interpretation_catalog_snapshot": score_interpretation_catalog_snapshot,
        **build_profile_support_projection(patient, longitudinal_bundle),
        "profile_read_model_version": surface_projection.get("profile_read_model_version", ""),
        "clinical_kernel_snapshot": clinical_kernel_snapshot,
        "effective_state": effective_state,
        "effective_recommendation_family": effective_recommendation_family,
        "surface_consistency_status": surface_consistency_status,
        "surface_consistency_flags": surface_consistency_flags,
        "legacy_recommendation_panel": legacy_recommendation_panel,
        "care_intent_contract": care_intent_contract,
        "palliative_transition_bundle": palliative_transition_bundle,
        "palliative_monitoring_package": palliative_monitoring_package,
        "survivorship_transition_bundle": survivorship_transition_bundle,
        "survivorship_monitoring_package": survivorship_monitoring_package,
        "survivorship_checklist": survivorship_checklist,
        "late_effects_profile": late_effects_profile,
        "functional_recovery_profile": functional_recovery_profile,
        "survivorship_schedule_overlay": survivorship_schedule_overlay,
        "survivorship_plan": survivorship_plan,
        "rt_toxicity_timeline": rt_toxicity_timeline,
        "symptom_burden_profile": longitudinal_bundle.get("symptom_burden_profile") or patient.get("symptom_burden_profile") or {},
        "advance_care_planning_status": longitudinal_bundle.get("advance_care_planning_status") or patient.get("advance_care_planning_status") or {},
        "hospice_eligibility": longitudinal_bundle.get("hospice_eligibility") or patient.get("hospice_eligibility") or {},
        "acute_palliative_alerts": longitudinal_bundle.get("acute_palliative_alerts") or patient.get("acute_palliative_alerts") or [],
        "recommended_supportive_referrals": longitudinal_bundle.get("recommended_supportive_referrals") or patient.get("recommended_supportive_referrals") or [],
        "guideline_followup_plan": guideline_followup_plan,
        "crpc_copilot_bundle": crpc_copilot_bundle,
        "crpc_copilot_status": crpc_copilot_bundle.get("status", "not_applicable"),
        "post_rp_salvage_bundle": post_rp_salvage_bundle,
        "post_rp_copilot_status": post_rp_salvage_bundle.get("status", "not_applicable"),
        "mhspc_copilot_bundle": mhspc_copilot_bundle,
        "mhspc_copilot_status": mhspc_copilot_bundle.get("status", "not_applicable"),
        "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
        "diagnostic_copilot_status": diagnostic_biopsy_bundle.get("status", "not_applicable"),
        "localized_surveillance_bundle": localized_surveillance_bundle,
        "localized_copilot_status": localized_surveillance_bundle.get("status", "not_applicable"),
        "post_rt_salvage_bundle": post_rt_salvage_bundle,
        "post_rt_failure_definition": post_rt_failure_definition,
        "post_rt_recurrence_bundle": post_rt_failure_definition,
        "post_rt_recurrence_profile": post_rt_recurrence_profile,
        "post_rt_local_salvage_ranking": post_rt_salvage_bundle.get("post_rt_local_salvage_ranking", []),
        "post_rt_transition_bundle": post_rt_transition_bundle,
        "post_rt_copilot_status": post_rt_salvage_bundle.get("status", "not_applicable"),
        "salvage_window_status": post_rp_salvage_bundle.get("salvage_window_status", ""),
        "salvage_window_reason": post_rp_salvage_bundle.get("salvage_window_reason", ""),
        "post_rt_salvage_window_status": post_rt_salvage_bundle.get("post_rt_salvage_window_status", ""),
        "qa_passed": (active_copilot_bundle.get("qa_validation") or {}).get("approved"),
        "sequence_summary": derive_display_sequence_summary(active_copilot_bundle),
        "metastatic_composition_summary": active_copilot_bundle.get("metastatic_composition_summary", {}),
        "histopathology_summary": active_copilot_bundle.get("histopathology_summary", ""),
        "decision_delta_since_last_visit": active_copilot_bundle.get("decision_delta_since_last_visit", {}),
        "blocked_by_overlay": active_copilot_bundle.get("blocked_by_overlay", []),
        "evidence_basis_current_visit": active_copilot_bundle.get("evidence_basis_current_visit", []),
        "crpc_schedule_overlay": crpc_copilot_bundle.get("crpc_schedule_overlay", {}),
        "post_rp_schedule_overlay": post_rp_salvage_bundle.get("post_rp_schedule_overlay", {}),
        "mhspc_schedule_overlay": mhspc_copilot_bundle.get("mhspc_schedule_overlay", {}),
        "diagnostic_schedule_overlay": diagnostic_biopsy_bundle.get("diagnostic_schedule_overlay", {}),
        "localized_schedule_overlay": localized_surveillance_bundle.get("localized_schedule_overlay", {}),
        "post_rt_schedule_overlay": post_rt_salvage_bundle.get("post_rt_schedule_overlay", {}),
        "laboratory_intelligence_profile": laboratory_intelligence_profile,
        "latest_clinically_decisive_visit": latest_clinically_decisive_visit,
        "agenda_resolution_trace": agenda_resolution_trace,
        "longitudinal_sections": _build_longitudinal_sections(patient, state, assessment),
        "supportive_evidence_context": _as_list(display_result.get("supportive_evidence_context"))[:3],
        "source_citations": display_result.get("source_citations", []),
        "care_overlays": care_overlays,
        "patient_alerts": _decorate_patient_alerts(patient.get("alerts") or []),
        "agenda_board": agenda_board,
        "master_followup_plan": master_followup_plan,
        "master_followup_summary": master_followup_plan.get("summary", {}),
        "active_agenda_items": active_agenda_items,
        "archived_agenda_items": archived_agenda_items,
        "encounters": agenda_board.get("encounters", []),
        "next_encounter": agenda_board.get("next_encounter", {}),
        "next_due_items": next_due_items,
        "overdue_items": overdue_items,
        "visit_schema": agenda_board.get("visit_schema", {}),
        "agenda_item_form_context": agenda_board.get("visit_schema", {}).get("agenda_item_context"),
        "therapy_checkpoints": agenda_board.get("therapy_checkpoints", []),
        "protocol_comparators": agenda_board.get("protocol_comparators", []),
        "protocol_trace": agenda_board.get("protocol_trace", {}),
        "data_provenance": _decorate_provenance_entries((patient.get("data_provenance") or [])[:12]),
        "clinical_signals": latest_signal_snapshot,
        "next_best_action": latest_signal_snapshot.get("next_best_action", {}),
        "transition_proposals": transition_proposals,
        "recommendation_audit": (patient.get("recommendation_audit") or [])[:8],
        "outcome_events": patient_outcome_events,
        "outcome_events_summary": adjudication_snapshot.get("outcome_events_summary", {}),
        "pending_adjudications": adjudication_snapshot.get("pending_adjudications", []),
        "current_response_state": adjudication_snapshot.get("current_response_state", {}),
        "current_course_status": adjudication_snapshot.get("current_course_status", ""),
        "current_course_status_display": adjudication_snapshot.get("current_course_status_display", "Sin estado adjudicado aún."),
        "last_adjudicated_event": adjudication_snapshot.get("last_adjudicated_event", {}),
        "trial_comparable_endpoints": trial_benchmark_snapshot.get("trial_endpoints", []),
        "current_trial_comparable_profile": trial_benchmark_snapshot.get("current_trial_profile", {}),
        "preferred_frontline_regimen": raw_result.get("preferred_frontline_regimen", {}),
        "frontline_regimen_rankings": raw_result.get("frontline_regimen_rankings", []),
        "frontline_regimen_rejections": raw_result.get("frontline_regimen_rejections", []),
        "drug_component_metadata": raw_result.get("drug_component_metadata", {}),
        "benchmark_snapshots": (trial_benchmark_snapshot.get("benchmark_snapshot") or {}).get("benchmark_snapshots", []),
        "document_board": document_board,
        "patient_kpis": patient_kpis,
        "cohort_completeness": cohort_completeness,
        "research_readiness": research_readiness,
        "endpoint_readiness": endpoint_readiness,
        "consent_summary": patient.get("consent_summary", {}),
        "consent_evidence": patient.get("consent_evidence", {}),
        "operational_outcomes": patient.get("operational_outcomes", []),
        "clavien_dindo_events": patient.get("clavien_dindo_events", []),
        "functional_recovery_snapshots": patient.get("functional_recovery_snapshots", []),
        "recommendations": recommendations or {},
        "copilot": copilot_sections,
        # Iteración C (GodiBot v1) — segunda opinión adversarial anexada al
        # bundle. UI render: `templates/components/godibot_panel.html`.
        # Si `godibot_review.status == "blocked_hard"`, la presentación debe
        # mostrar banner rojo + exigir override firmado del médico.
        "godibot_review": godibot_review,
        # EPIC 45 FAUBOT CXXX — Data Integrity audit (alias contradictions).
        # Inyecta {contradictions: [...], resolutions_history: [...], stats}.
        # UI render: panel "Integridad de datos" en patient_profile_v2.html.
        # NO bloquea decisiones (advisory only — el clínico decide si aplica
        # auto-resolución vía endpoint /api/data-integrity/<nss>/resolve).
        "data_integrity": _build_data_integrity_snapshot(patient),
        # EPIC 46.B FAUBOT CXXXIII — ML Predictions (4 modelos PyTorch).
        # Materialización de treatment_response + deep_surv + anomaly_detector
        # + state_transition (entrenados hace meses, CERO consumo en UI hasta hoy).
        # Inyecta {available, models{4}, advisory_only=True}. UI render: 4 cards
        # condicionales en patient_profile_v2.html (solo si available). Cada
        # prediction queda con maturity tag (experimental / shadow / advisory) +
        # nunca como source-of-truth — siempre complementa rule-based engine.
        "ml_predictions": _build_ml_predictions_snapshot_view_model(patient),
        # EPIC 47 FAUBOT CXXXV — Longitudinal Trajectory Dashboard.
        # Cambia el paradigma de medicina: snapshot → temporal. Unifica PSA +
        # ECOG + ALP + LDH + treatment lanes + cohort baseline en una sola
        # estructura consumible por Chart.js. Computa kinetics clínicos
        # (PSADT, velocity, ALP trend, ECOG decline) + alerts pre-clínicas
        # (PSA doubling time <10m, ALP rise pre-imaging, testosterone failure
        # to suppress, PSA progression on ARSI PCWG3, ECOG severe decline).
        # UI render: dashboard data-testid="trajectory-dashboard" entre ML
        # cards y EPIC 20 cards. Alertas con severity badges.
        "trajectory": _build_trajectory_snapshot_view_model(patient, state),
    }
    # EPIC 48.A FAUBOT CXXXVI — Decision Narrative (synthesis layer).
    # Inyecta DESPUÉS de construir el bundle completo para tener acceso a
    # todos los engines simultáneamente (compass + twin + fusion + gates +
    # trajectory + ml). Produce ONE narrative coherente que reduce cognitive
    # load del clínico de 6+ cards a 1 párrafo + drill-downs.
    bundle["decision_narrative"] = _build_decision_narrative_safe(bundle)
    # EPIC 48.C FAUBOT CXXXVI — Outcome Linkage (decision → outcomes 3/6/12m).
    # Vincula la última decisión clínica (treatment_start o override event)
    # a outcomes observados. Foundation continuous learning loop + Latin
    # recalibration analytics + SaMD post-market surveillance.
    bundle["outcome_linkage"] = _build_outcome_linkage_safe(patient)
    # EPIC GVP.B FAUBOT CXLI — Clinical Validation Snapshot (prospectivo).
    # Hook que ejecuta GodiBot review automáticamente en cada render del
    # perfil. Garantiza que nuevos pacientes que ingresen TAMBIÉN reciban
    # validation (no solo cohorte retroactiva via CLI).
    # Patrón EPIC 45 aplicado a clinical validation:
    #   - CLI poblacional (godibot_cohort_audit) = retroactivo
    #   - Este hook                              = prospectivo per render
    # Output inyectado al bundle como `clinical_validation_snapshot`.
    # UI render: mini-panel con status badge + count findings + link
    # al detail GodiBot card existente.
    bundle["clinical_validation_snapshot"] = _build_clinical_validation_snapshot(
        patient, bundle.get("godibot_review") or {},
    )
    return bundle


def _build_clinical_validation_snapshot(
    patient: dict[str, Any],
    existing_godibot_review: dict[str, Any],
) -> dict[str, Any]:
    """Fail-safe wrapper que genera validation snapshot para el bundle.

    Estrategia:
      1. Si existing_godibot_review ya tiene contenido (compass ya lo ejecutó
         durante el flow original), reusa su status + findings sin re-correr.
      2. Si no, ejecuta GodiBot lazy + low-LLM (audit-mode rapido).
      3. Persiste audit entry en cohort_validation_runs con
         trigger_source='profile_render' para tracking longitudinal.

    Returns:
        {
            "available": bool,
            "status": "approved" | "warnings_only" | "blocked_hard" | "skipped",
            "findings_count": int,
            "review_timestamp": ISO,
            "trigger_source": str,
            "snapshot_version": "epic_gvp_v1",
        }
    """
    try:
        # Re-use existing godibot_review si fue ejecutado upstream.
        # GVP.E FIX (FAUBOT CXLII): findings reales viven en 'discrepancies'
        # (no 'findings'). Combinamos ambos por backwards-compat.
        if existing_godibot_review:
            status = str(existing_godibot_review.get("status") or "")
            findings = (
                list(existing_godibot_review.get("discrepancies") or [])
                + list(existing_godibot_review.get("findings") or [])
            )
            if status:
                return {
                    "available": True,
                    "status": status,
                    "findings_count": len(findings),
                    "review_timestamp": existing_godibot_review.get(
                        "review_timestamp"
                    ) or _now_iso(),
                    "trigger_source": "reused_upstream",
                    "snapshot_version": "epic_gvp_v1",
                }

        # Lazy run con flag enable_llm=False (rapidez en path de render)
        from prostanet.agents.godibot import run_godibot_review

        identity = patient.get("identity") if isinstance(patient.get("identity"), dict) else {}
        patient_id = int(
            patient.get("id")
            or patient.get("patient_id")
            or (identity.get("id") if identity else 0)
            or 0
        )
        if patient_id <= 0:
            return {
                "available": False,
                "status": "skipped",
                "findings_count": 0,
                "reason": "invalid_patient_id",
                "snapshot_version": "epic_gvp_v1",
            }

        review = run_godibot_review(
            patient,
            patient_id=patient_id,
            trigger_event="profile_render_validation",
            enable_llm=False,  # Path de render: rapidez prioritaria
        )
        status = str(review.get("status") or "unknown")
        findings = review.get("findings") or []
        return {
            "available": True,
            "status": status,
            "findings_count": len(findings),
            "review_timestamp": _now_iso(),
            "trigger_source": "lazy_render",
            "snapshot_version": "epic_gvp_v1",
        }
    except Exception as exc:
        return {
            "available": False,
            "status": "error",
            "findings_count": 0,
            "reason": f"snapshot_builder_error: {type(exc).__name__}",
            "snapshot_version": "epic_gvp_v1",
        }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_outcome_linkage_safe(patient: dict[str, Any]) -> dict[str, Any]:
    """Fail-safe wrapper sobre build_outcome_linkage."""
    try:
        from prostanet.domains.decisions.outcome_linkage import build_outcome_linkage
        return build_outcome_linkage(patient)
    except Exception as exc:
        return {
            "available": False,
            "reason": f"outcome_linkage_error: {type(exc).__name__}",
            "decision_anchor": None,
            "outcomes_3m": {"data_available": False},
            "outcomes_6m": {"data_available": False},
            "outcomes_12m": {"data_available": False},
            "summary": {"any_window_complete": False},
            "linkage_version": "epic48_v1.0",
        }


def _build_decision_narrative_safe(bundle: dict[str, Any]) -> dict[str, Any]:
    """Fail-safe wrapper sobre build_decision_narrative. Si el sintetizador
    falla por cualquier razón, el bundle render del perfil NO se bloquea."""
    try:
        from prostanet.domains.decisions.decision_narrative_builder import (
            build_decision_narrative,
        )
        return build_decision_narrative(bundle)
    except Exception as exc:
        return {
            "available": False,
            "reason": f"narrative_builder_error: {type(exc).__name__}",
            "narrative_html": "",
            "narrative_plain": "",
            "primary_recommendation": {},
            "alternatives": [],
            "evidence_chain": [],
            "discordances": [],
            "confidence_score": 0.0,
            "narrative_version": "epic48_v1.0",
        }


def _build_trajectory_snapshot_view_model(
    patient: dict[str, Any],
    state: str | None = None,
) -> dict[str, Any]:
    """Fail-safe wrapper que invoca build_trajectory_bundle + evaluate_trajectory_alerts.

    Returns bundle con shape:
      {available, summary, series, treatment_lanes, event_markers,
       cohort_overlay, kinetics, alerts}

    Si cualquier cosa falla, retorna {"available": False, "reason": ...}
    sin levantar excepción (no bloquea render del perfil).
    """
    try:
        from prostanet.domains.patient_tracking.trajectory_engine import (
            build_trajectory_bundle,
        )
        from prostanet.domains.patient_tracking.trajectory_alert_engine import (
            evaluate_trajectory_alerts,
        )

        # include_cohort_overlay=False en render del perfil porque
        # build_psa_cohort_reference_overlay() puede iterar toda la cohorte
        # y agregar 60+s de overhead. Cohort overlay queda disponible vía
        # GET /api/trajectory/<nss> (REST endpoint lo activa explícitamente).
        bundle = build_trajectory_bundle(patient, include_cohort_overlay=False)

        # Patient context para alert engine
        baseline = patient.get("baseline") or {}
        latest_treatment = (patient.get("treatments") or [{}])[-1] if patient.get("treatments") else {}
        treatment_class = str(latest_treatment.get("class") or latest_treatment.get("regimen_class") or "").lower()
        treatment_scheme = str(latest_treatment.get("scheme") or latest_treatment.get("drug_scheme") or "").lower()
        on_arsi = any(
            arsi in treatment_class or arsi in treatment_scheme
            for arsi in ("abi", "enza", "apa", "daro", "arsi", "arpi")
        )
        on_adt = any(
            adt in treatment_class or adt in treatment_scheme
            for adt in ("adt", "lhrh", "agonist", "antagonist", "leupr", "goser", "trip", "degar", "relug")
        )

        last_imaging = ""
        imaging_records = patient.get("imaging_studies") or []
        if isinstance(imaging_records, list) and imaging_records:
            last_imaging_record = imaging_records[-1] if isinstance(imaging_records[-1], dict) else {}
            last_imaging = str(
                last_imaging_record.get("conventional_imaging_status")
                or last_imaging_record.get("status")
                or ""
            ).upper()

        ctx = {
            "state_resolved": str(state or "").lower(),
            "on_arsi": on_arsi,
            "on_adt": on_adt,
            "last_imaging_status": last_imaging,
        }

        bundle["alerts"] = evaluate_trajectory_alerts(bundle, ctx) if bundle.get("available") else []
        return bundle
    except Exception as exc:
        return {
            "available": False,
            "reason": f"trajectory_engine_error: {type(exc).__name__}",
            "alerts": [],
            "engine_version": "epic47_v1.0",
        }


def _build_ml_predictions_snapshot_view_model(patient: dict[str, Any]) -> dict[str, Any]:
    """Fail-safe wrapper que invoca build_ml_predictions_snapshot desde la
    capa de presentación. Resuelve patient_id desde el dict del view model
    (path canónico: patient.identity.id). Si cualquier cosa falla, retorna
    `available=False` con reason explicativa — NO levanta excepción que
    bloquee el render del perfil completo."""
    try:
        identity = patient.get("identity") if isinstance(patient.get("identity"), dict) else {}
        patient_id = int(
            patient.get("id")
            or patient.get("patient_id")
            or (identity.get("id") if identity else 0)
            or 0
        )
        if patient_id <= 0:
            return {
                "available": False,
                "models": {},
                "reason": "invalid_patient_id",
                "advisory_only": True,
            }

        from prostanet.presentation.ml_inference_routes import (
            build_ml_predictions_snapshot,
        )
        return build_ml_predictions_snapshot(patient_id)
    except Exception as exc:
        return {
            "available": False,
            "models": {},
            "reason": f"snapshot_builder_error: {type(exc).__name__}",
            "advisory_only": True,
        }
