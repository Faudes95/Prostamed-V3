from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from prostanet.domains.patient_tracking.encounter_planner import (
    action_mode_for_task,
    build_encounter_plans,
    is_required_task,
)
from prostanet.domains.patient_tracking.capture_flows import (
    prepend_capture_block_to_visit_sections,
)
from prostanet.domains.patient_tracking.capture_surface import (
    build_capture_surface_metadata,
    expand_visible_capture_surface,
    visible_required_inputs,
)
from prostanet.domains.patient_tracking.post_rp_salvage_intensification_builder import (
    build_post_rp_salvage_intensification_profile,
)
from prostanet.domains.patient_tracking.palliative_longitudinal import (
    PALLIATIVE_ALIAS_TRACKS,
    build_palliative_monitoring_package,
    build_palliative_transition_bundle,
    resolve_canonical_palliative_track,
)
from prostanet.domains.patient_tracking.survivorship_longitudinal import (
    build_survivorship_monitoring_package,
    build_survivorship_transition_bundle,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.repository import (
    lab_reference_range,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    family_label,
    regimen_family_code,
)
from prostanet.domains.patient_tracking.therapy_catalog import therapy_select_options
from prostanet.shared.advanced_support_catalog import (
    DDI_REVIEW_STATUS_OPTIONS,
    MINI_COG_OPTIONS,
    MINI_COG_OPTION_LABELS,
)
from prostanet.shared.contracts import (
    AgendaItem,
    FieldSpec,
    InstitutionalComparator,
    StageProtocolDefinition,
    TherapyCheckpoint,
    VisitBundle,
)
from prostanet.shared.metastatic_profile import (
    BONE_SITE_LABELS,
    METASTATIC_PROFILE_FIELD_NAMES,
    NONREGIONAL_NODAL_SITE_LABELS,
    VISCERAL_SITE_LABELS,
)
from prostanet.shared.official_diagnosis import (
    CLINICAL_RISK_GROUP_OPTIONS,
    CLINICAL_STAGE_GROUP_OPTIONS,
    CLINICAL_TSTAGE_OPTIONS,
    HISTOLOGY_SUBTYPE_OPTIONS,
    NODAL_STATUS_OPTIONS,
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

MANAGEMENT_TRACK_LABELS = {
    "diagnostic_surveillance": "Ruta diagnóstica activa",
    "rebiopsy_surveillance": "Seguimiento tras biopsia benigna",
    "localized_decision": "Decisión local activa",
    "active_surveillance": "Vigilancia activa",
    "pre_surgery": "Preparación prequirúrgica",
    "post_rp": "Seguimiento post prostatectomía radical",
    "post_rt": "Seguimiento post radioterapia",
    "salvage": "Ruta de rescate",
    "salvage_evaluation": "Evaluación temprana de rescate",
    "on_arpi": "Tratamiento activo con ARPI",
    "on_docetaxel": "Tratamiento activo con quimioterapia",
    "on_parp": "Tratamiento activo con PARP",
    "on_lu177": "Tratamiento activo con Lutecio-177",
    "systemic_surveillance": "Seguimiento sistémico activo",
    "palliative_overlay": "Overlay paliativo concurrente",
    "concurrent_palliative_care": "Cuidados paliativos concurrentes",
    "supportive_only": "Soporte exclusivo",
    "hospice_pathway": "Ruta hospice",
    "survivorship_followup": "Seguimiento de survivorship",
    "toxicity_recovery": "Recuperación de toxicidad",
    "late_effect_intervention": "Intervención de secuelas tardías",
}

COMMON_IMAGING_LOCATIONS = [
    "Lecho prostático",
    "Ganglios pélvicos",
    "Ganglios retroperitoneales",
    "Hueso axial",
    "Hueso apendicular",
    "Pulmón",
    "Hígado",
    "Suprarrenal",
    "Otra visceral",
]

CANONICAL_SCHEDULE_EVENT_TYPES = {
    "lab_panel": "labs",
    "pro_assessment": "qol",
    "toxicity_review": "toxicity",
    "therapy_review": "therapy_review",
    "supportive_care": "supportive_care",
    "goals_of_care": "goals_of_care",
}

LINE_OF_THERAPY_NUMBER_OPTIONS = ["", "1", "2", "3", "4", "5", "6"]
LINE_OF_THERAPY_CONTEXT_OPTIONS = [
    "",
    "mHSPC_initial",
    "mHSPC_post_docetaxel",
    "m0_CRPC_first_line",
    "mCRPC_first_line",
    "mCRPC_post_ARPI_pre_taxane",
    "mCRPC_post_taxane",
    "mCRPC_post_PARP",
    "mCRPC_post_Lu177",
    "later_line",
]


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


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


def _known_cancer_diagnosis(patient: dict[str, Any] | None, state: str) -> bool:
    if state not in DIAGNOSTIC_STATES:
        return True
    patient = patient or {}
    baseline = patient.get("baseline") or {}
    latest_assessment = (patient.get("latest_assessment") or {}).get("input_snapshot", {}) if isinstance(patient.get("latest_assessment"), dict) else {}
    return any(
        _is_present(source.get(field))
        for source in (baseline, latest_assessment)
        for field in ("histology_subtype", "gleason_primary", "gleason_secondary", "isup_grade")
    ) or bool(patient.get("biopsies"))


def _has_sufficient_biopsy_detail(patient: dict[str, Any] | None) -> bool:
    patient = patient or {}
    baseline = patient.get("baseline") or {}
    latest_assessment = (patient.get("latest_assessment") or {}).get("input_snapshot", {}) if isinstance(patient.get("latest_assessment"), dict) else {}
    biopsy_sources = [baseline, latest_assessment]
    biopsies = list(patient.get("biopsies") or [])
    if biopsies:
        ordered = sorted(biopsies, key=lambda item: str(item.get("biopsy_date") or ""), reverse=True)
        biopsy_sources.append(ordered[0])
    for source in biopsy_sources:
        if not isinstance(source, dict):
            continue
        has_gleason = _is_present(source.get("gleason_primary")) and _is_present(source.get("gleason_secondary"))
        has_core_burden = (
            _is_present(source.get("pct_cores_positive"))
            or (
                _is_present(source.get("num_cores_positive", source.get("positive_cores")))
                and _is_present(source.get("total_cores"))
            )
        )
        if has_gleason and has_core_burden:
            return True
    return False


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def longitudinal_item_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    ideal_due_at = str(item.get("ideal_due_at") or item.get("due_at") or "")[:10]
    scheduled_due_at = str(item.get("scheduled_due_at") or item.get("due_at") or "")[:10]
    encounter_type = str(item.get("encounter_type") or item.get("item_type") or "")
    title = str(item.get("title") or "")
    return (ideal_due_at, scheduled_due_at, encounter_type, title)


def _add_months(base: date, months: int) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _latest_by(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _latest_value_snapshot(patient: dict[str, Any], *fields: str) -> tuple[Any, str, str]:
    followups = patient.get("follow_ups") or []
    baseline = patient.get("baseline") or {}
    prior = patient.get("prior_history") or {}
    identity = patient.get("identity") or {}

    latest_followup = _latest_by(followups, "visit_date")
    for field in fields:
        if _is_present(latest_followup.get(field)):
            return latest_followup.get(field), "follow_up_visits", str(latest_followup.get("visit_date") or "")
    for field in fields:
        if _is_present(baseline.get(field)):
            return baseline.get(field), "clinical_baseline", str(identity.get("diagnosis_date") or "")
    for field in fields:
        if _is_present(prior.get(field)):
            return prior.get(field), "prior_clinical_history", str(identity.get("diagnosis_date") or "")
    return "", "", ""


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return ""


def _metastatic_followup_fields() -> list[dict[str, Any]]:
    fields = [
        _field("nonregional_nodal_metastasis_present", "Ganglios no regionales presentes", "checkbox"),
        _field("nonregional_nodal_count", "Número de ganglios no regionales", "number"),
        _field("nonregional_nodal_other_label", "Otro sitio ganglionar no regional", "text"),
    ]
    for key, label in NONREGIONAL_NODAL_SITE_LABELS.items():
        fields.append(_field(f"nonregional_nodal_{key}_count", f"{label}: número de lesiones", "number"))
    fields.extend(
        [
            _field("bone_metastasis_present", "Metástasis óseas presentes", "checkbox"),
            _field("bone_axial_count", "Número de lesiones en esqueleto axial", "number"),
            _field("bone_appendicular_count", "Número de lesiones en esqueleto apendicular", "number"),
        ]
    )
    for key, label in BONE_SITE_LABELS.items():
        fields.append(_field(f"bone_{key}_count", f"{label}: número de lesiones", "number"))
    fields.extend(
        [
            _field("visceral_metastasis_present", "Metástasis viscerales presentes", "checkbox"),
            _field("visceral_lesion_count", "Número total de lesiones viscerales", "number"),
            _field("visceral_other_label", "Otro órgano visceral", "text"),
        ]
    )
    for key, label in VISCERAL_SITE_LABELS.items():
        fields.append(_field(f"visceral_{key}_count", f"{label}: número de lesiones", "number"))
    fields.extend(
        [
            _field("metastatic_total_lesion_count", "Número total de lesiones metastásicas", "number"),
            _field("metastasis_assessment_date", "Fecha de evaluación metastásica", "date"),
            _field("metastasis_document_source", "Fuente documental de la distribución metastásica", "text"),
        ]
    )
    return fields


def _treatment_text(patient: dict[str, Any]) -> str:
    treatments = patient.get("treatments") or []
    if treatments:
        return str((treatments[-1] or {}).get("drug_scheme") or "")
    follow_ups = patient.get("follow_ups") or []
    if follow_ups:
        return str((follow_ups[-1] or {}).get("current_treatment") or "")
    return ""


def _assessment_anchor_date(raw_assessment: dict[str, Any] | None) -> tuple[date | None, str]:
    if not raw_assessment:
        return None, ""
    for key in ("assessment_date", "created_at", "updated_at"):
        parsed = _parse_date(raw_assessment.get(key))
        if parsed:
            return parsed, f"latest_assessment.{key}"
    return None, ""


def _treatment_track_tokens(management_track: str) -> tuple[str, ...]:
    mapping = {
        "on_arpi": ("apalutamide", "apalutamida", "enzalutamide", "enzalutamida", "darolutamide", "darolutamida", "abiraterone", "abiraterona", "bicalutamide", "bicalutamida", "arpi"),
        "on_docetaxel": ("docetaxel", "cabazitaxel", "taxane", "taxano"),
        "on_parp": ("olaparib", "talazoparib", "niraparib", "parp"),
        "on_lu177": ("lutec", "lu177", "177lu", "pluvicto", "radioligand"),
    }
    return mapping.get(management_track, ())


def _latest_treatment_anchor(patient: dict[str, Any], management_track: str) -> tuple[date | None, str]:
    tokens = _treatment_track_tokens(management_track)
    treatments = patient.get("treatments") or []
    for treatment in reversed(treatments):
        start = _parse_date(treatment.get("start_date"))
        if not start:
            continue
        text_parts = [
            treatment.get("drug_scheme"),
            treatment.get("class_exhausted"),
            treatment.get("discontinuation_reason"),
            treatment.get("regimen_json"),
        ]
        haystack = " ".join(str(part or "") for part in text_parts).lower()
        if not tokens or any(token in haystack for token in tokens):
            return start, "treatment_history.start_date"
    return None, ""


def resolve_track_anchor(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    raw_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deriva la fecha real de anclaje del track activo para agenda y cadencia."""
    identity = patient.get("identity") or {}
    prior = patient.get("prior_history") or {}
    active_surveillance = patient.get("active_surveillance") or {}
    surgery = patient.get("surgery") or {}
    bcr = patient.get("bcr") or {}
    radiation = patient.get("radiation") or []
    followups = patient.get("follow_ups") or []

    latest_followup = _latest_by(followups, "visit_date")
    last_visit_date = _parse_date(latest_followup.get("visit_date"))

    anchor: date | None = None
    source = ""

    if management_track == "active_surveillance":
        anchor = _parse_date(active_surveillance.get("enrollment_date"))
        source = "active_surveillance.enrollment_date" if anchor else ""
        if not anchor:
            latest_biopsy = _latest_by(patient.get("biopsies") or [], "biopsy_date")
            anchor = _parse_date(latest_biopsy.get("biopsy_date"))
            source = "biopsy_details.biopsy_date" if anchor else ""
    elif management_track == "pre_surgery":
        anchor, source = _assessment_anchor_date(raw_assessment)
    elif management_track == "post_rp":
        anchor = _parse_date(_first_nonempty(surgery.get("surgery_date"), prior.get("rp_date"), prior.get("prostatectomy_date")))
        source = "surgical_details.surgery_date" if surgery.get("surgery_date") else "prior_clinical_history.rp_date" if anchor else ""
    elif management_track in {"post_rt", "salvage"}:
        latest_rt = _latest_by(radiation, "rt_date")
        anchor = _parse_date(_first_nonempty(latest_rt.get("rt_date"), bcr.get("salvage_date"), prior.get("rt_date"), prior.get("radiation_date")))
        if latest_rt.get("rt_date"):
            source = "radiation_details.rt_date"
        elif bcr.get("salvage_date"):
            source = "biochemical_recurrence.salvage_date"
        elif anchor:
            source = "prior_clinical_history.rt_date"
    elif management_track in {"on_arpi", "on_docetaxel", "on_parp", "on_lu177"}:
        anchor, source = _latest_treatment_anchor(patient, management_track)
    if not anchor:
        anchor, source = _assessment_anchor_date(raw_assessment)
    if not anchor:
        anchor = _parse_date(identity.get("diagnosis_date"))
        source = "identity.diagnosis_date" if anchor else ""
    if not anchor:
        anchor = _parse_date(identity.get("created_at"))
        source = "identity.created_at" if anchor else ""

    return {
        "anchor_date": _fmt_date(anchor),
        "anchor_source": source or "unknown",
        "last_visit_date": _fmt_date(last_visit_date),
    }


def infer_management_track(patient: dict[str, Any], state: str, raw_assessment: dict[str, Any] | None = None) -> str:
    from prostanet.domains.patient_tracking.reconciled_state import derive_post_prostatectomy_course

    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    treatment_text = _treatment_text(patient).lower()
    overlays = patient.get("care_overlays") or []
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    documented_track = str(
        truth_values.get("management_track")
        or latest_followup.get("management_track")
        or ""
    ).strip()
    pain_score = _safe_float(latest_followup.get("pain_score"))
    if any("pali" in str(item.get("title", "")).lower() for item in overlays) or (pain_score is not None and pain_score >= 7):
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="palliative_overlay",
            latest_assessment=raw_assessment,
        )
    if state == "diagnostic_workup":
        return "diagnostic_surveillance"
    if state == "post_negative_biopsy_followup":
        return "rebiopsy_surveillance"
    if state == "localized_initial":
        if documented_track in {"active_surveillance", "pre_surgery", "localized_decision"}:
            return resolve_canonical_palliative_track(
                patient=patient,
                state=state,
                current_track=documented_track,
                latest_assessment=raw_assessment,
            )
        active_surveillance = patient.get("active_surveillance") or {}
        if str(active_surveillance.get("current_status", "")).lower() == "activo":
            return "active_surveillance"
        eligible = ((raw_assessment or {}).get("result_snapshot", {}) or {}).get("eligible_treatments", []) or []
        eligible_names = " ".join(str(item.get("name", "")) for item in eligible if isinstance(item, dict)).lower()
        if any(token in eligible_names for token in ("radiot", "rt", "ebrt", "hormonal", "adt", "braqu")):
            return "localized_decision"
        if "prostatectomy" in eligible_names or "cirug" in eligible_names:
            return "pre_surgery"
        return "localized_decision"
    if state == "post_prostatectomy":
        course = derive_post_prostatectomy_course(patient)
        if course == "persistent_psa":
            return "salvage_evaluation"
        if documented_track in {"post_rp", "salvage", "salvage_evaluation"}:
            return resolve_canonical_palliative_track(
                patient=patient,
                state=state,
                current_track=documented_track,
                latest_assessment=raw_assessment,
            )
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="post_rp",
            latest_assessment=raw_assessment,
        )
    if state == "recurrence_bcr":
        if documented_track in {"salvage", "salvage_evaluation", "post_rt"}:
            return resolve_canonical_palliative_track(
                patient=patient,
                state=state,
                current_track=documented_track,
                latest_assessment=raw_assessment,
            )
        radiation = patient.get("radiation") or []
        if radiation and not patient.get("surgery"):
            return resolve_canonical_palliative_track(
                patient=patient,
                state=state,
                current_track="post_rt",
                latest_assessment=raw_assessment,
            )
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="salvage",
            latest_assessment=raw_assessment,
        )
    if state == "post_radiotherapy_or_local_salvage":
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="post_rt" if documented_track not in {"supportive_only", "hospice_pathway"} else documented_track,
            latest_assessment=raw_assessment,
        )
    if "lutec" in treatment_text or "pluvicto" in treatment_text:
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="on_lu177",
            latest_assessment=raw_assessment,
        )
    if any(token in treatment_text for token in ("olaparib", "talazoparib", "niraparib")):
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="on_parp",
            latest_assessment=raw_assessment,
        )
    if any(token in treatment_text for token in ("docetaxel", "cabazitaxel")):
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="on_docetaxel",
            latest_assessment=raw_assessment,
        )
    if any(token in treatment_text for token in ("apalutamide", "enzalutamide", "darolutamide", "abiraterone", "abiraterona", "bicalutamide", "bicalutamida")):
        return resolve_canonical_palliative_track(
            patient=patient,
            state=state,
            current_track="on_arpi",
            latest_assessment=raw_assessment,
        )
    return resolve_canonical_palliative_track(
        patient=patient,
        state=state,
        current_track="systemic_surveillance",
        latest_assessment=raw_assessment,
    )


def _field(name: str, label: str, field_type: str, **kwargs: Any) -> dict[str, Any]:
    range_metadata = lab_reference_range(name)
    payload = dict(kwargs)
    if range_metadata:
        payload.setdefault("reference_range_low", range_metadata.get("reference_range_low"))
        payload.setdefault("reference_range_high", range_metadata.get("reference_range_high"))
        payload.setdefault("reference_range_unit", range_metadata.get("reference_range_unit"))
        payload.setdefault("reference_range_label", range_metadata.get("reference_range_label"))
        payload.setdefault("reference_range_source", range_metadata.get("reference_range_source"))
    return FieldSpec(name=name, label=label, field_type=field_type, **payload).to_dict()


def _build_visit_sections(state: str, management_track: str, patient: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    therapy_options = therapy_select_options(
        state=state,
        management_track=management_track,
        include_empty=True,
    )
    mini_cog_display_options = [
        {"value": option, "label": MINI_COG_OPTION_LABELS.get(option, option)}
        for option in MINI_COG_OPTIONS
    ]
    weak_grip_options = [
        {"value": "", "label": "--"},
        {"value": "0", "label": "Ausente"},
        {"value": "1", "label": "Presente"},
    ]
    sections = [
        {
            "title": "Contexto de la visita",
            "subtitle": "Hechos mínimos para ubicar esta visita en el longitudinal.",
            "fields": [
                _field("visit_date", "Fecha de visita", "date", required=True),
                _field(
                    "disease_status",
                    "Estado clínico resumido",
                    "select",
                    options=[
                        "Seguimiento estable",
                        "Respuesta",
                        "Progresión bioquímica",
                        "Progresión radiográfica",
                        "Toxicidad limitante",
                        "Pendiente de confirmación",
                    ],
                    required=True,
                    default="Seguimiento estable",
                ),
                _field("current_treatment", "Tratamiento actual", "text"),
                _field("clinician_notes", "Notas clínicas", "textarea"),
            ],
        }
    ]
    sections.append(
        {
            "title": "Diagnóstico oficial y clasificación",
            "subtitle": "Complete o corrija subtipo histológico, Gleason y TNM clínico sin esperar un nuevo ingreso.",
            "fields": [
                _field("histology_subtype", "Subtipo histológico", "select", options=HISTOLOGY_SUBTYPE_OPTIONS),
                _field("gleason_primary", "Gleason primario", "select", options=["", "3", "4", "5"]),
                _field("gleason_secondary", "Gleason secundario", "select", options=["", "3", "4", "5"]),
                _field("isup_grade", "ISUP / Grade Group", "select", options=["", "1", "2", "3", "4", "5"]),
                _field("clinical_tstage", "T clínico", "select", options=CLINICAL_TSTAGE_OPTIONS),
                _field("nodal_status", "N clínico", "select", options=NODAL_STATUS_OPTIONS),
                _field("clinical_stage_group", "Etapa clínica", "select", options=CLINICAL_STAGE_GROUP_OPTIONS),
                _field("clinical_risk_group", "Grupo de riesgo clínico", "select", options=CLINICAL_RISK_GROUP_OPTIONS),
            ],
        }
    )
    if _known_cancer_diagnosis(patient, state) and not _has_sufficient_biopsy_detail(patient):
        sections.append(
            {
                "title": "Biopsia estructurada pendiente",
                "subtitle": "Complete la patología basal mínima para CAPRA, riesgo basal y trazabilidad histopatológica.",
                "fields": [
                    _field("biopsy_date", "Fecha de biopsia", "date"),
                    _field("biopsy_type", "Tipo de biopsia", "select", options=["", "systematic", "mri_targeted", "fusion", "saturation"]),
                    _field("biopsy_route", "Vía de biopsia", "select", options=["", "transperineal", "transrectal"]),
                    _field("biopsy_context", "Contexto de biopsia", "select", options=["", "diagnostic", "confirmatory_as", "followup_as", "rebiopsy"]),
                    _field("mri_pirads_at_biopsy", "PI-RADS al momento de biopsia", "number"),
                    _field("total_cores", "Número total de cilindros", "number"),
                    _field("positive_cores", "Número de cilindros positivos", "number"),
                ],
            }
        )

    if state in DIAGNOSTIC_STATES:
        sections.append(
            {
                "title": "Ruta diagnóstica activa",
                "subtitle": "Captura solo datos que cambian la decisión diagnóstica hoy.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("psad", "Densidad de PSA", "number"),
                    _field("mpmri_quality", "Calidad de MRI multiparamétrica", "select", options=["Adecuada", "Subóptima", "No realizada"]),
                    _field("pirads_score", "PI-RADS", "select", options=["", "2", "3", "4", "5"]),
                    _field("index_lesion_location", "Localización de lesión índice", "text"),
                    _field("index_lesion_size_mm", "Tamaño de lesión índice", "number", unit="mm"),
                    _field("prostate_volume_ml", "Volumen prostático", "number", unit="mL"),
                    _field("planned_biopsy_type", "Tipo de biopsia prevista", "select", options=["", "Sistemática", "Dirigida + sistemática", "Transperineal", "Transrectal"]),
                    _field("planned_biopsy_route", "Vía prevista de biopsia", "select", options=["", "Transperineal", "Transrectal"]),
                    _field("family_history_detail", "Historia familiar / germinal relevante", "textarea"),
                ],
            }
        )
    elif state == "localized_initial":
        localized_fields = [
            _field("psa", "PSA actual", "number", unit="ng/mL"),
            _field("prior_mpmri_pirads_score", "PI-RADS previo", "select", options=["", "2", "3", "4", "5", "desconocido"]),
            _field("prior_mpmri_targeted_biopsy_status", "Biopsia dirigida previa", "select", options=["", "si", "no", "desconocido"]),
            _field("precise_score", "PRECISE", "select", options=["", "1", "2", "3", "4", "5"]),
            _field("percent_pattern_4", "Porcentaje de patrón 4", "number", unit="%"),
            _field("cribriform_pattern", "Patrón cribriforme", "checkbox"),
            _field("intraductal_carcinoma", "Carcinoma intraductal", "checkbox"),
            _field(
                "adverse_histology_variant_type",
                "Variante histológica adversa",
                "select",
                options=[
                    "none",
                    "ductal_predominant",
                    "sarcomatoid",
                    "signet_ring",
                    "adenosquamous_or_squamous",
                    "basal_cell",
                    "mucinous_colloid",
                    "small_cell_neuroendocrine",
                    "mixed_multiple",
                    "other_aggressive",
                ],
                default="none",
            ),
            _field("adverse_histology_variant_detail", "Detalle histológico", "textarea"),
            _field("ipss_total", "IPSS actual", "number"),
            _field("iief5_score", "IIEF-5 actual", "number"),
            _field("eq5d_vas", "EQ-5D VAS", "number"),
            _field("fact_p_total", "FACT-P", "number"),
            _field("genomic_classifier", "Clasificador genómico documentado", "select", options=["", "Decipher", "Oncotype DX Prostate", "Prolaris"]),
            _field("genomic_classifier_result", "Resultado documentado", "text"),
        ]
        sections.append(
            {
                "title": "Decisión local y vigilancia",
                "subtitle": "Variables anatómicas, patológicas y funcionales que definen la ruta local.",
                "fields": localized_fields,
            }
        )
    elif state == "post_prostatectomy":
        sections.append(
            {
                "title": "Seguimiento post prostatectomía radical",
                "subtitle": "PSA ultrasensible, recuperación funcional y datos patológicos si siguen faltando.",
                "fields": [
                    _field("psa", "PSA ultrasensible", "number", unit="ng/mL"),
                    _field("pad_usage", "Pads/día", "number"),
                    _field("continence_status", "Continencia", "select", options=["", "Continente", "Leve", "Moderada", "Severa"]),
                    _field("iief5_score", "IIEF-5 actual", "number"),
                    _field("pde5i_use", "Uso de PDE5i", "checkbox"),
                    _field("surgery_type", "Tipo de cirugía", "text"),
                    _field("surgical_approach", "Abordaje", "select", options=["", "Abierta", "Laparoscópica", "Robótica"]),
                    _field("nerve_sparing", "Preservación nerviosa", "text"),
                    _field("nodes_removed", "Ganglios resecados", "number"),
                    _field("nodes_positive", "Ganglios positivos", "number"),
                    _field("margin_location", "Localización del margen", "select", options=["", "Ápex", "Base", "Posterolateral", "Múltiple", "Otro"], default="Ápex"),
                    _field("capra_s_score", "CAPRA-S", "number"),
                    _field("decipher_risk", "Decipher documentado", "text"),
                ],
            }
        )
    elif management_track == "post_rt" or state == "post_radiotherapy_or_local_salvage":
        sections.append(
            {
                "title": "Seguimiento post radioterapia / rescate",
                "subtitle": "Confirmación Phoenix, restaging, toxicidad GU/GI y factibilidad real de salvage local post-RT.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("psa_nadir", "PSA nadir post-RT", "number", unit="ng/mL"),
                    _field("phoenix_delta", "Delta Phoenix", "number", unit="ng/mL"),
                    _field("rt_context", "Contexto de RT", "select", options=["", "Primaria", "Adyuvante", "Salvamento", "Paliativa"]),
                    _field("prior_rt_modality", "Modalidad RT previa", "select", options=["", "EBRT", "IMRT/VMAT", "SBRT", "LDR brachy", "HDR brachy", "Combinada", "Otra"]),
                    _field("prior_rt_dose", "Dosis previa", "number", unit="Gy"),
                    _field("prior_rt_fields", "Campos irradiados", "text"),
                    _field("fractions", "Número de sesiones", "number"),
                    _field("total_dose_gy", "Dosis total", "number", unit="Gy"),
                    _field("dose_per_fraction_gy", "Dosis por fracción", "number", unit="Gy"),
                    _field("session_duration_minutes", "Duración promedio de sesión", "number", unit="min"),
                    _field("biopsy_proven_local_recurrence", "Biopsia confirma recurrencia local", "checkbox"),
                    _field("biopsy_date", "Fecha de biopsia", "date"),
                    _field("biopsy_grade_group", "Grade Group de biopsia", "number"),
                    _field("mpmri_done", "mpMRI realizada", "checkbox"),
                    _field("mpmri_date", "Fecha de mpMRI", "date"),
                    _field("mpmri_localized_recurrence", "mpMRI sugiere recurrencia localizada", "checkbox"),
                    _field("local_recurrence_site", "Sitio de recurrencia local", "text"),
                    _field("psma_pet_done", "PSMA-PET realizada", "checkbox"),
                    _field("psma_radioligand", "Radioligando PSMA", "text"),
                    _field("psma_rads_score", "PSMA-RADS", "select", options=["", "1", "2", "3A", "3B", "4", "5"]),
                    _field("psma_uptake_pattern", "Patrón de captación PSMA", "select", options=["", "Focal", "Multifocal", "Oligometastatic", "Diseminado"]),
                    _field("psma_stage_after_psma", "Estadio post-PSMA", "select", options=["", "M0", "M1a", "M1b", "M1c"]),
                    _field("urinary_burden", "Carga urinaria", "select", options=["", "Leve", "Moderada", "Severa"]),
                    _field("incontinence_burden", "Carga de incontinencia", "select", options=["", "Leve", "Moderada", "Severa"]),
                    _field("urethral_stricture_history", "Antecedente de estenosis uretral", "checkbox"),
                    _field("bowel_burden", "Carga intestinal", "select", options=["", "Leve", "Moderada", "Severa"]),
                    _field("rectal_toxicity_grade", "Toxicidad rectal", "number"),
                    _field("prostate_volume", "Volumen prostático", "number", unit="cc"),
                    _field("anesthesia_surgical_fitness", "Aptitud anestésica/quirúrgica", "select", options=["", "Apto", "No apto", "Condicional"]),
                    _field("salvage_expertise_available", "Expertise local disponible", "select", options=["", "Sí", "No", "Desconocido"]),
                    _field("hematuria", "Hematuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("dysuria", "Disuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("anemia_rt", "Anemia relacionada", "select", options=["", "No", "Sí"]),
                    _field("gu_toxicity_grade", "Toxicidad GU", "number"),
                    _field("gi_toxicity_grade", "Toxicidad GI", "number"),
                    _field("eq5d_vas", "EQ-5D VAS", "number"),
                ],
            }
        )
    elif management_track == "salvage":
        sections.append(
            {
                "title": "Seguimiento de rescate",
                "subtitle": "PSA ultrasensible, imagen dirigida y recuperación funcional para no perder la ventana curativa.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("psadt_months", "PSADT", "number", unit="meses"),
                    _field("salvage_local_feasible", "Salvage local factible", "checkbox"),
                    _field("psma_pet_done", "PSMA-PET realizada", "checkbox"),
                    _field("psma_radioligand", "Radioligando PSMA", "text"),
                    _field("psma_rads_score", "PSMA-RADS", "select", options=["", "1", "2", "3A", "3B", "4", "5"]),
                    _field("psma_uptake_pattern", "Patrón PSMA", "select", options=["", "Focal", "Multifocal", "Oligometastatic", "Diseminado"]),
                    _field("hematuria", "Hematuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("dysuria", "Disuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("gu_toxicity_grade", "Toxicidad GU", "number"),
                    _field("gi_toxicity_grade", "Toxicidad GI", "number"),
                    _field("eq5d_vas", "EQ-5D VAS", "number"),
                ],
            }
        )
    else:
        sections.append(
            {
                "title": "Seguimiento sistémico",
                "subtitle": "Laboratorio, seguridad y carga tumoral por modalidad activa.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field(
                        "psa_history",
                        "Serie longitudinal de PSA / APE",
                        "psa_history",
                        help_text="Agregue todas las mediciones relevantes de APE/PSA para alimentar la torre de vigilancia y el monitoreo por línea.",
                    ),
                    _field("testosterone", "Testosterona", "number", unit="ng/dL"),
                    _field(
                        "testosterone_history",
                        "Serie longitudinal de testosterona",
                        "testosterone_history",
                        help_text="Registre múltiples mediciones con fecha, unidad, contexto y línea terapéutica para resolver castración con prioridad sobre el valor aislado.",
                    ),
                    _field(
                        "line_of_therapy_number",
                        "Número de línea terapéutica",
                        "select",
                        options=LINE_OF_THERAPY_NUMBER_OPTIONS,
                    ),
                    _field(
                        "line_of_therapy_context",
                        "Contexto clínico de la línea",
                        "select",
                        options=LINE_OF_THERAPY_CONTEXT_OPTIONS,
                    ),
                    _field(
                        "drug_scheme",
                        "Esquema sistémico actual",
                        "select",
                        options=therapy_options,
                        help_text="Seleccione el esquema canónico activo para dejar trazabilidad real del cambio de línea y del APE por esquema.",
                    ),
                    _field(
                        "current_adt_context",
                        "Contexto actual de ADT",
                        "select",
                        options=[
                            "",
                            "none",
                            "medical_adt_continuous",
                            "medical_adt_interrupted",
                            "orchiectomy",
                        ],
                    ),
                    _field(
                        "castrate_testosterone_status",
                        "Estado de castración",
                        "select",
                        options=["", "unknown", "confirmed_castrate", "not_castrate"],
                    ),
                    _field(
                        "progression_pattern",
                        "Patrón de progresión",
                        "select",
                        options=["", "none", "biochemical_only", "radiographic", "clinical", "mixed"],
                    ),
                    _field(
                        "conventional_imaging_status",
                        "Imagen convencional",
                        "select",
                        options=["", "NOT_RESTAGED", "M0", "M1"],
                    ),
                    _field("creatinine", "Creatinina", "number", unit="mg/dL"),
                    _field("cystatin_c", "Cistatina C", "number", unit="mg/L"),
                    _field("alp", "ALP", "number", unit="UI/L"),
                    _field("ldh", "LDH", "number", unit="UI/L"),
                    _field("bilirubin", "Bilirrubina", "number", unit="mg/dL"),
                    _field("ast", "AST", "number", unit="UI/L"),
                    _field("alt", "ALT", "number", unit="UI/L"),
                    _field("ggt", "GGT", "number", unit="UI/L"),
                    _field("glucose", "Glucosa", "number", unit="mg/dL"),
                    _field("hemoglobin", "Hemoglobina", "number", unit="g/dL"),
                    _field("pain", "Dolor", "number", unit="0-10"),
                    _field("ecog", "ECOG", "select", options=["", "0", "1", "2", "3", "4"]),
                    _field("frailty_status", "Fragilidad", "select", options=["", "fit", "vulnerable", "frail"]),
                    _field("systolic_bp", "PA sistólica", "number", unit="mmHg"),
                    _field("diastolic_bp", "PA diastólica", "number", unit="mmHg"),
                    _field("total_cholesterol", "Colesterol total", "number", unit="mg/dL"),
                    _field("hdl_cholesterol", "HDL", "number", unit="mg/dL"),
                    _field("triglycerides", "Triglicéridos", "number", unit="mg/dL"),
                    _field("hba1c", "HbA1c", "number", unit="%"),
                    _field("waist_circumference_cm", "Cintura abdominal", "number", unit="cm"),
                    _field("cv_risk_documented", "Riesgo CV documentado", "checkbox"),
                    _field("ddi_review_status", "Estado de revisión DDI", "select", options=DDI_REVIEW_STATUS_OPTIONS),
                    _field("active_liver_disease", "Hepatopatía activa", "checkbox"),
                    _field("cirrhosis_or_portal_hypertension", "Cirrosis / hipertensión portal", "checkbox"),
                    _field("active_hepatitis_b_or_c", "Hepatitis B/C activa", "checkbox"),
                    _field("prior_drug_induced_liver_injury", "Hepatotoxicidad previa por fármacos", "checkbox"),
                    _field("liver_panel_date", "Fecha PFH", "date"),
                    _field("weight_kg", "Peso", "number", unit="kg"),
                    _field("height_cm", "Estatura", "number", unit="cm"),
                    _field("bmi_current", "BMI", "number", help_text="Se calcula automáticamente a partir de peso y estatura."),
                    _field("weight_loss_6m_kg", "Pérdida ponderal 6 meses", "number", unit="kg"),
                    _field("exercise_status", "Actividad física", "select", options=["", "No realiza", "Ligera", "Moderada", "Intensa"]),
                    _field("nutrition_status", "Estado nutricional", "select", options=["", "Adecuado", "Sobrepeso", "Desnutrición", "Riesgo"]),
                    _field("protein_supplements", "Suplementos proteicos", "checkbox"),
                    _field("mini_cog_score", "Mini-Cog", "select", options=mini_cog_display_options),
                    _field("fatigue_score", "Brief Fatigue Inventory", "number"),
                    _field("seizure_history", "Antecedente convulsivo", "checkbox"),
                    _field("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["", "0", "1", "2", "3", "4"]),
                    _field("dermatitis_history", "Dermatitis / rash previo", "checkbox"),
                    _field("dxa_t_score_lumbar", "DXA T-score lumbar", "number"),
                    _field("dxa_t_score_hip", "DXA T-score cadera", "number"),
                    _field("dxa_baseline_done", "DXA basal realizada", "checkbox"),
                    _field("vitamin_d_level", "Vitamina D", "number", unit="ng/mL"),
                    _field("calcium_vitd_started", "Calcio / vitamina D iniciados", "checkbox"),
                    _field("bone_protection_started", "Protección ósea iniciada", "checkbox"),
                    _field("prior_fragility_fracture", "Fractura previa por fragilidad", "checkbox"),
                    _field("steroid_use", "Uso crónico de esteroides", "checkbox"),
                    _field("opioid_use", "Uso de opioides", "select", options=["", "No", "PRN", "Crónico"]),
                ],
            }
        )
        sections.append(
            {
                "title": "Fragilidad y fitness terapéutica",
                "subtitle": "Completa los inputs mínimos para G8, Fried y aptitud terapéutica sin asumir defaults optimistas.",
                "fields": [
                    _field("g8_food_intake", "G8: ingesta de alimentos", "select", options=["", "0", "1", "2"]),
                    _field("g8_weight_loss", "G8: pérdida de peso", "select", options=["", "0", "1", "2", "3"]),
                    _field("g8_mobility", "G8: movilidad", "select", options=["", "0", "1", "2"]),
                    _field("g8_neuropsych", "G8: estado neuropsicológico", "select", options=["", "0", "1", "2"]),
                    _field("g8_bmi", "G8: categoría BMI", "select", options=["", "0", "1", "2", "3"]),
                    _field("g8_medications", "G8: medicamentos diarios", "select", options=["", "0", "1"]),
                    _field("g8_self_health", "G8: percepción de salud", "select", options=["", "0", "0.5", "1", "2"]),
                    _field("low_activity", "Actividad física reducida", "checkbox"),
                    _field("slow_gait", "Marcha lenta", "checkbox"),
                    _field(
                        "weak_grip",
                        "Fuerza de prensión baja",
                        "select",
                        options=weak_grip_options,
                        help_text="Alimenta el fenotipo de Fried y la aptitud terapéutica global.",
                    ),
                ],
            }
        )
        sections.append(
            {
                "title": "Soporte paliativo y objetivos de cuidado",
                "subtitle": "Capture dolor, carga sintomatica, urgencias oncologicas y planificacion anticipada para que el carril paliativo compita correctamente con la conducta sistemica.",
                "fields": [
                    _field("bpi_worst_pain", "BPI dolor peor", "number", unit="0-10"),
                    _field("bone_pain", "Dolor oseo", "checkbox"),
                    _field("neuropathic_pain", "Componente neuropatico", "checkbox"),
                    _field("current_analgesics", "Analgesicos actuales", "text"),
                    _field("breakthrough_pain", "Dolor irruptivo", "checkbox"),
                    _field("bowel_regimen_started", "Esquema intestinal con opioides", "checkbox"),
                    _field("dyspnea_score", "Disnea", "number", unit="0-10"),
                    _field("nausea_score", "Nausea", "number", unit="0-10"),
                    _field("constipation_score", "Estrenimiento", "number", unit="0-10"),
                    _field("appetite_loss", "Anorexia / perdida de apetito", "number", unit="0-10"),
                    _field("insomnia_score", "Insomnio", "number", unit="0-10"),
                    _field("depression_score", "Depresion", "number", unit="0-10"),
                    _field("anxiety_score", "Ansiedad", "number", unit="0-10"),
                    _field("ecog_delta_3mo", "Cambio ECOG en 3 meses", "number"),
                    _field("albumin", "Albumina", "number", unit="g/dL"),
                    _field("weight_loss_pct", "Perdida ponderal reciente", "number", unit="%"),
                    _field("refractory_pain", "Dolor refractario", "checkbox"),
                    _field("visceral_crisis", "Crisis visceral", "checkbox"),
                    _field("spinal_cord_compression", "Compresion medular", "checkbox"),
                    _field("epidural_compression", "Compresion epidural", "checkbox"),
                    _field("pathological_fracture_risk", "Riesgo de fractura patologica", "checkbox"),
                    _field("obstructive_uropathy", "Obstruccion urinaria / ureteral", "checkbox"),
                    _field("hematuria_severe", "Hematuria severa", "checkbox"),
                    _field("brain_metastasis", "Metastasis cerebrales", "checkbox"),
                    _field("advance_directive_documented", "Voluntades anticipadas documentadas", "checkbox"),
                    _field("goals_of_care_discussed", "Objetivos de cuidado discutidos", "checkbox"),
                    _field("healthcare_surrogate_designated", "Representante de salud designado", "checkbox"),
                    _field("patient_prefers_comfort", "El paciente prioriza confort", "checkbox"),
                    _field("prior_systemic_lines", "Lineas sistemicas previas", "number"),
                ],
            }
        )
        sections.append(
            {
                "title": "Actualización biomolecular / PSMA",
                "subtitle": "Datos que cambian elegibilidad a PARP, inmunoterapia y terapias dirigidas a PSMA.",
                "fields": [
                    _field("hrr_status", "Estado HRR", "select", options=["", "Positivo", "Negativo", "Desconocido"]),
                    _field("hrr_gene", "Gen HRR dominante", "text"),
                    _field("brca2_status", "BRCA2", "select", options=["", "Positivo", "Negativo", "Desconocido"]),
                    _field("msi_status", "MSI", "select", options=["", "Inestable", "Estable", "Desconocido"]),
                    _field("tmb_high", "TMB alto", "checkbox"),
                    _field("biomarker_source", "Fuente del biomarcador", "text"),
                    _field("molecular_assay_date", "Fecha del estudio molecular", "date"),
                    _field("psma_positive", "PSMA positivo", "checkbox"),
                    _field("psma_negative_dominant_lesions", "Lesiones dominantes PSMA negativas", "checkbox"),
                ],
            }
        )
        sections.append(
            {
                "title": "Imagen oncológica opcional de esta visita",
                "subtitle": "Si hoy se revisó imagen, persístela de manera estructurada para volumen y distribución.",
                "fields": [
                    _field("imaging_modality", "Modalidad revisada", "select", options=["", "PSMA-PET", "Gammagrama óseo", "TAC convencional"]),
                    _field("psma_suv_max", "SUV max", "number", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_radioligand", "Radioligando PSMA", "select", options=["", "68Ga-PSMA-11", "18F-DCFPyL", "18F-PSMA-1007", "Otro", "Desconocido"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_index_lesion_site", "Lesión índice PSMA", "text", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_index_lesion_suvmax", "SUVmax lesión índice", "number", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_uptake_pattern", "Patrón de captación", "select", options=["", "focal", "multifocal", "diseminado", "indeterminado"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_rads_score", "PSMA-RADS", "select", options=["", "1", "2", "3", "4", "5", "Desconocido"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_suv_bucket", "Bucket SUV", "select", options=["", "<6", "6-9", "9-12", ">12"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_total_lesions", "Número total de lesiones PSMA", "number", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_lesion_locations", "Ubicación de lesiones PSMA", "multi_select", options=COMMON_IMAGING_LOCATIONS, conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_negative_dominant_lesions", "Lesiones dominantes PSMA negativas", "checkbox", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("conventional_stage_before_psma", "Stage convencional previo", "select", options=["", "No comparable", "M0", "M1a", "M1b", "M1c"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_stage_after_psma", "Stage posterior por PSMA", "select", options=["", "M0", "M1a", "M1b", "M1c"], conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("psma_management_changed", "Cambio de conducta por PSMA", "checkbox", conditional_visibility={"imaging_modality": ["PSMA-PET"]}),
                    _field("bone_lesion_count", "Lesiones positivas en gammagrama", "number", conditional_visibility={"imaging_modality": ["Gammagrama óseo"]}),
                    _field("bone_distribution", "Distribución ósea", "multi_select", options=COMMON_IMAGING_LOCATIONS, conditional_visibility={"imaging_modality": ["Gammagrama óseo"]}),
                    _field("ct_summary", "Resumen TAC", "select", options=["", "Sin lesiones sospechosas", "Ganglios sospechosos", "Metástasis"], conditional_visibility={"imaging_modality": ["TAC convencional"]}),
                    _field("ct_locations", "Ubicación de hallazgos TAC", "multi_select", options=COMMON_IMAGING_LOCATIONS, conditional_visibility={"imaging_modality": ["TAC convencional"]}),
                ],
            }
        )
        sections.append(
            {
                "title": "Distribución metastásica detallada",
                "subtitle": "Subclasifica M1a / M1b / M1c con sitios y número de lesiones reales; el renderer TNM y la epidemiología usan estos datos.",
                "fields": _metastatic_followup_fields(),
            }
        )

    sections.append(
        {
            "title": "Survivorship y toxicidad tardía",
            "subtitle": "Capture secuelas postlocales, toxicidad tardía, salud ósea, recuperación funcional y impacto psicosocial cuando estos dominios dominan la visita.",
            "fields": [
                _field("ipss_score", "IPSS", "number"),
                _field("pad_count", "Pads por día", "number"),
                _field("continence_status", "Estado de continencia", "select", options=["", "Continente", "Leve", "Moderada", "Severa"]),
                _field("leakage_bother", "Molestia por fuga urinaria", "number", unit="0-10"),
                _field("iief5_score", "IIEF-5", "number"),
                _field("nerve_sparing", "Preservación neurovascular", "select", options=["", "No", "Unilateral", "Bilateral", "Desconocido"]),
                _field("pelvic_floor_pt_started", "Fisioterapia de piso pélvico iniciada", "checkbox"),
                _field("rectal_toxicity_grade", "Toxicidad rectal", "select", options=["", "0", "1", "2", "3", "4"]),
                _field("radiation_cystitis", "Cistitis actínica documentada", "checkbox"),
                _field("proctitis", "Proctitis documentada", "checkbox"),
                _field("late_toxicity_json", "Resumen estructurado de toxicidad tardía", "textarea"),
                _field("fall_risk", "Riesgo de caída", "checkbox"),
                _field("cognitive_risk", "Riesgo cognitivo", "checkbox"),
                _field("neuropathy_grade", "Neuropatía", "select", options=["", "0", "1", "2", "3", "4"]),
                _field("functional_decline", "Declive funcional", "checkbox"),
                _field("dental_clearance_done", "Clearance dental realizado", "checkbox"),
                _field("onj_monitoring", "Monitoreo de ONJ", "checkbox"),
                _field("bone_pain", "Dolor óseo", "checkbox"),
                _field("skeletal_events", "Eventos esqueléticos estructurados", "textarea"),
                _field("depression_score", "Depresión", "number", unit="0-10"),
                _field("anxiety_score", "Ansiedad", "number", unit="0-10"),
                _field("sexual_bother", "Carga sexual percibida", "number", unit="0-10"),
                _field("body_image_distress", "Distress por imagen corporal", "number", unit="0-10"),
                _field("return_to_work_status", "Retorno a trabajo / rol", "select", options=["", "Sin impacto", "Ajustado", "No retornó", "Jubilado", "No documentado"]),
            ],
        }
    )

    return sections


def _clone_field(field: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(field)

def _filter_fields(sections: list[dict[str, Any]], field_names: list[str], required_inputs: list[str]) -> list[dict[str, Any]]:
    wanted = {name for name in field_names if name and not str(name).startswith("source_document:")}
    required = {name for name in required_inputs if name and not str(name).startswith("source_document:")}
    filtered_sections: list[dict[str, Any]] = []
    for section in sections:
        fields = []
        for field in section.get("fields", []):
            if field.get("name") not in wanted:
                continue
            cloned = _clone_field(field)
            if cloned.get("name") in required:
                cloned["required"] = True
            fields.append(cloned)
        if fields:
            filtered_sections.append(
                {
                    "title": section.get("title"),
                    "subtitle": section.get("subtitle"),
                    "fields": fields,
                }
            )
    return filtered_sections


def _append_dynamic_capture_fields(sections: list[dict[str, Any]], field_names: list[str]) -> list[dict[str, Any]]:
    wanted = [name for name in field_names if name and not str(name).startswith("source_document:")]
    if not wanted:
        return sections
    present = {
        str(field.get("name") or "")
        for section in sections
        for field in list(section.get("fields") or [])
    }
    missing = [name for name in wanted if name not in present]
    if not missing:
        return sections

    try:
        from prostanet.domains.patient_tracking.risk_tools import FIELD_REGISTRY
    except Exception:
        FIELD_REGISTRY = {}

    dynamic_fields = []
    for field_name in missing:
        meta = dict(FIELD_REGISTRY.get(field_name) or {})
        if not meta:
            continue
        dynamic_fields.append(
            _field(
                field_name,
                meta.get("label") or field_name.replace("_", " "),
                meta.get("field_type") or "text",
                options=meta.get("options", []),
                help_text=meta.get("help_text", ""),
                unit=meta.get("unit", ""),
            )
        )
    if not dynamic_fields:
        return sections

    return sections + [
        {
            "title": "Refinadores pronósticos y datos faltantes",
            "subtitle": "Campos dinámicos añadidos para completar scores aplicables sin abrir otro formulario.",
            "fields": dynamic_fields,
        }
    ]


def _agenda_tool_capture_requirements() -> dict[str, list[str]]:
    try:
        from prostanet.domains.patient_tracking.risk_tools import SCORE_REQUIREMENTS
    except Exception:
        SCORE_REQUIREMENTS = {}
    tool_requirements = {str(key): list(value or []) for key, value in dict(SCORE_REQUIREMENTS or {}).items()}
    tool_requirements.setdefault(
        "briganti",
        ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"],
    )
    return tool_requirements


def resolve_agenda_item_capture_contract(item: dict[str, Any] | None) -> dict[str, list[str]]:
    item = item or {}
    form_scope = dict(item.get("form_scope") or {})
    tool_capture_requirements = _agenda_tool_capture_requirements()
    required_inputs = [
        str(field)
        for field in list(item.get("required_inputs") or [])
        if field and not str(field).startswith("source_document:")
    ]
    explicit_capture_fields = [
        str(field)
        for field in list(item.get("capture_fields") or form_scope.get("capture_fields") or [])
        if field and not str(field).startswith("source_document:")
    ]
    derived_requirements = [
        str(field)
        for field in list(item.get("derived_requirements") or form_scope.get("derived_requirements") or [])
        if field and not str(field).startswith("source_document:")
    ]
    capture_fields: list[str] = []
    for field in required_inputs:
        if field in tool_capture_requirements:
            derived_requirements.append(field)
            continue
        capture_fields.append(field)
    capture_fields = explicit_capture_fields or capture_fields
    for tool_key in list(derived_requirements):
        capture_fields.extend(tool_capture_requirements.get(tool_key, []))
    capture_fields = list(
        dict.fromkeys(
            str(field)
            for field in capture_fields
            if field and not str(field).startswith("source_document:")
        )
    )
    derived_requirements = list(dict.fromkeys(derived_requirements))
    return {
        "required_inputs": required_inputs,
        "capture_fields": capture_fields,
        "derived_requirements": derived_requirements,
    }


def _agenda_item_field_names(item: dict[str, Any]) -> list[str]:
    return resolve_agenda_item_capture_contract(item).get("capture_fields", [])


def _build_agenda_item_form_context(item: dict[str, Any]) -> dict[str, Any]:
    contract = resolve_agenda_item_capture_contract(item)
    return {
        "mode": "item_scoped",
        "title": item.get("title"),
        "summary": item.get("summary"),
        "required_inputs": contract.get("required_inputs", []),
        "capture_fields": contract.get("capture_fields", []),
        "derived_requirements": contract.get("derived_requirements", []),
        "decision_targets": item.get("decision_targets", []),
        "panel_targets": item.get("panel_targets", []),
        "write_targets": item.get("write_targets", []),
        "form_scope": item.get("form_scope", {}),
        "reasoning": item.get("reasoning", []),
        "blockers": item.get("blockers", []),
    }


def build_visit_schema(
    state: str,
    management_track: str,
    patient: dict[str, Any] | None = None,
    agenda_item: dict[str, Any] | None = None,
    field_scope: list[str] | None = None,
    capture_context: dict[str, Any] | None = None,
    presentation: str = "standard",
) -> dict[str, Any]:
    if not field_scope and capture_context:
        form_scope = dict((capture_context or {}).get("form_scope") or {})
        field_scope = list(form_scope.get("fields") or form_scope.get("capture_fields") or [])
    sections = _build_visit_sections(state, management_track, patient=patient)
    agenda_item_context = None
    presentation_mode = "standard"
    focus_fields = list(dict.fromkeys(field_scope or []))
    capture_fields: list[str] = []
    required_inputs: list[str] = []
    schema_scope = "full_track"
    fixed_context = {}
    auto_visit_date = ""
    allow_visit_date_override = False
    if agenda_item:
        contract = resolve_agenda_item_capture_contract(agenda_item)
        inline_task = presentation == "inline_task"
        capture_fields = contract.get("capture_fields", [])
        required_inputs = contract.get("required_inputs", [])
        surface = build_capture_surface_metadata(capture_fields, required_inputs=required_inputs)
        visible_capture_fields = list(surface.get("visible_fields") or [])
        visible_required = list(surface.get("visible_required_inputs") or [])
        # Auditoría #21 (cierre OOS-8): en modo `inline_task` el contrato de UI
        # requiere que el schema refleje EXACTAMENTE los `required_inputs` de
        # la subtarea (sin expansiones como `fatigue_score_band`). Las
        # expansiones (`STRUCTURED_VISIBLE_FIELD_EXPANSIONS`) son útiles en
        # presentación standard/capture_block donde la banda visible asiste la
        # captura, pero rompen el contrato item-scoped donde se valida que
        # `schema.fields == arpi_item.required_inputs`.
        inline_scoped_fields = list(dict.fromkeys(capture_fields))
        scoped_fields = inline_scoped_fields if inline_task else list(visible_capture_fields)
        sections = _append_dynamic_capture_fields(sections, scoped_fields)
        sections = _filter_fields(
            sections,
            scoped_fields if inline_task else ["visit_date", *scoped_fields],
            visible_required,
        )
        agenda_item_context = _build_agenda_item_form_context(agenda_item)
        agenda_item_context["visible_fields"] = (
            inline_scoped_fields if inline_task else visible_capture_fields
        )
        agenda_item_context["visible_required_inputs"] = (
            list(dict.fromkeys(required_inputs)) if inline_task else visible_required
        )
        agenda_item_context["display_fields_summary"] = list(surface.get("display_fields_summary") or [])
        if inline_task:
            agenda_item_context["mode"] = "inline_task"
            presentation_mode = "inline_task"
            focus_fields = list(dict.fromkeys(inline_scoped_fields))
            fixed_context = {
                "title": agenda_item_context.get("title", ""),
                "summary": agenda_item_context.get("summary", ""),
                "why_now": "Completar esta subtarea actualiza el encounter y recalcula el plan maestro.",
                "decision_targets": list(agenda_item_context.get("decision_targets") or []),
                "recommended_action": agenda_item.get("action_label") or "Completar la subtarea seleccionada.",
            }
            auto_visit_date = date.today().isoformat()
            allow_visit_date_override = True
        else:
            focus_fields = list(dict.fromkeys(visible_capture_fields))
        schema_scope = "exact_item"
    elif field_scope:
        alert_capture = bool(capture_context and capture_context.get("alert_key"))
        capture_fields = list(dict.fromkeys(field_scope or []))
        required_inputs = list(capture_fields)
        surface = build_capture_surface_metadata(capture_fields, required_inputs=required_inputs)
        visible_capture_fields = list(surface.get("visible_fields") or [])
        visible_required = list(surface.get("visible_required_inputs") or [])
        scoped_fields = visible_capture_fields if alert_capture else ["visit_date", *visible_capture_fields]
        sections = _append_dynamic_capture_fields(sections, scoped_fields)
        sections = _filter_fields(sections, scoped_fields, visible_required)
        capture_block = dict((capture_context or {}).get("form_scope") or {})
        if capture_block:
            capture_block.setdefault("fields", capture_fields)
            capture_block.setdefault("visible_fields", visible_capture_fields)
            capture_block.setdefault("display_fields_summary", list(surface.get("display_fields_summary") or []))
            capture_block.setdefault("title", (capture_context or {}).get("title") or "Completar datos críticos")
            capture_block.setdefault("summary", (capture_context or {}).get("rationale") or "")
            capture_block.setdefault("capture_target", capture_block.get("focus") or "clinical_completion")
            sections = prepend_capture_block_to_visit_sections(sections, capture_block)
        agenda_item_context = {
            "mode": "mini_capture" if alert_capture else "capture_block",
            "title": capture_context.get("title") if capture_context else "Completar datos críticos",
            "summary": capture_context.get("rationale") if capture_context else "Completa variables críticas del flujo clínico.",
            "required_inputs": required_inputs,
            "capture_fields": capture_fields,
            "derived_requirements": [],
            "decision_targets": [capture_context.get("decision_affected")] if capture_context and capture_context.get("decision_affected") else [],
            "panel_targets": [capture_context.get("module_owner")] if capture_context and capture_context.get("module_owner") else [],
            "write_targets": ["follow_up_visits", "stage_visit_records"],
            "form_scope": capture_context.get("form_scope") if capture_context else {"mode": "capture_block"},
            "reasoning": [capture_context.get("rationale")] if capture_context and capture_context.get("rationale") else [],
            "blockers": [],
            "linked_agenda_ids": list(capture_context.get("linked_agenda_ids") or []) if capture_context else [],
            "linked_agenda_keys": list(capture_context.get("linked_agenda_keys") or []) if capture_context else [],
            "encounter_key": capture_context.get("encounter_key") if capture_context else "",
            "alert_key": capture_context.get("alert_key") if capture_context else "",
            "action_type": capture_context.get("action_type") if capture_context else "capture",
            "expected_document_type": capture_context.get("expected_document_type") if capture_context else "auto",
            "visible_fields": visible_capture_fields,
            "visible_required_inputs": visible_required,
            "display_fields_summary": list(surface.get("display_fields_summary") or []),
        }
        presentation_mode = "mini_capture" if alert_capture else "standard"
        focus_fields = list(dict.fromkeys(visible_capture_fields))
        fixed_context = {
            "title": agenda_item_context.get("title", ""),
            "summary": agenda_item_context.get("summary", ""),
            "why_now": capture_context.get("rationale") if capture_context else "",
            "decision_targets": list(agenda_item_context.get("decision_targets") or []),
            "recommended_action": capture_context.get("recommended_action") if capture_context and capture_context.get("recommended_action") else "Guardar la captura mínima para recalcular alertas, agenda y siguiente mejor acción.",
        }
        auto_visit_date = date.today().isoformat()
        allow_visit_date_override = True
        schema_scope = "exact_capture_block"
    if not focus_fields:
        focus_fields = [
            str(field.get("name") or "")
            for section in sections
            for field in list(section.get("fields") or [])
            if str(field.get("name") or "")
        ]
    return VisitBundle(
        state=state,
        management_track=management_track,
        sections=sections,
    ).to_dict() | {
        "agenda_item_context": agenda_item_context,
        "presentation_mode": presentation_mode,
        "focus_fields": focus_fields,
        "task_scope": {
            "agenda_key": agenda_item.get("agenda_key", "") if agenda_item else "",
            "title": agenda_item.get("title", "") if agenda_item else "",
            "action_mode": agenda_item.get("action_mode", "") if agenda_item else "",
        },
        "fixed_context": fixed_context,
        "auto_visit_date": auto_visit_date,
        "allow_visit_date_override": allow_visit_date_override,
        "encounter_key": agenda_item.get("encounter_key", "") if agenda_item else (capture_context.get("encounter_key", "") if capture_context else ""),
        "plan_key": agenda_item.get("plan_key", "") if agenda_item else "",
        "schema_scope": schema_scope,
        "capture_fields": capture_fields,
        "required_inputs": required_inputs,
        "visible_fields": list((agenda_item_context or {}).get("visible_fields") or []),
        "visible_required_inputs": list((agenda_item_context or {}).get("visible_required_inputs") or []),
        "display_fields_summary": list((agenda_item_context or {}).get("display_fields_summary") or []),
        "decision_targets": list((agenda_item_context or {}).get("decision_targets") or []),
        "write_targets": list((agenda_item_context or {}).get("write_targets") or []),
        "submission_mode": (
            "item_scoped"
            if agenda_item or field_scope or capture_context
            else "full_track"
        ),
    }


def _agenda_item(
    agenda_key: str,
    item_type: str,
    title: str,
    state: str,
    management_track: str,
    base_date: date | None,
    interval_days: int,
    *,
    priority: str = "routine",
    summary: str = "",
    required_inputs: list[str] | None = None,
    completion_rule: dict[str, Any] | None = None,
    evidence_basis: list[str] | None = None,
    comparator_basis: list[str] | None = None,
    generated_from_event: str = "",
    blockers: list[str] | None = None,
    reasoning: list[str] | None = None,
    decision_targets: list[str] | None = None,
    panel_targets: list[str] | None = None,
    write_targets: list[str] | None = None,
    capture_fields: list[str] | None = None,
    derived_requirements: list[str] | None = None,
    form_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = date.today()
    due_at = (base_date or today) + timedelta(days=interval_days)
    window_start = due_at - timedelta(days=14)
    window_end = due_at + timedelta(days=30)
    status = "scheduled"
    if blockers:
        status = "blocked"
    elif due_at == today:
        status = "due_today"
    elif due_at < today:
        status = "overdue"
    elif window_start <= today <= window_end:
        status = "due"
    action_label = "Completar"
    if item_type in {"psa", "testosterone", "lab_panel", "pro_assessment", "toxicity_review", "therapy_review"}:
        action_label = "Registrar visita"
    elif item_type in {"imaging", "biopsy"}:
        action_label = "Registrar estudio"
    normalized_form_scope = dict(form_scope or {"mode": "full_track"})
    if capture_fields:
        normalized_form_scope.setdefault("capture_fields", list(capture_fields))
    if derived_requirements:
        normalized_form_scope.setdefault("derived_requirements", list(derived_requirements))
    return AgendaItem(
        agenda_key=agenda_key,
        item_type=item_type,
        title=title,
        state=state,
        management_track=management_track,
        due_at=_fmt_date(due_at),
        ideal_due_at=_fmt_date(due_at),
        scheduled_due_at=_fmt_date(due_at),
        completed_at="",
        window_start=_fmt_date(window_start),
        window_end=_fmt_date(window_end),
        delay_days=0,
        plan_key="",
        status=status,
        priority=priority,
        summary=summary,
        required_inputs=required_inputs or [],
        capture_fields=capture_fields or [],
        derived_requirements=derived_requirements or [],
        required=is_required_task({"item_type": item_type}, state),
        action_mode=action_mode_for_task(
            {
                "item_type": item_type,
                "required_inputs": required_inputs or [],
                "completion_rule": completion_rule or {},
                "form_scope": normalized_form_scope,
            }
        ),
        completion_rule=completion_rule or {},
        evidence_basis=evidence_basis or [],
        comparator_basis=comparator_basis or [],
        generated_from_event=generated_from_event,
        action_label=action_label,
        blockers=blockers or [],
        reasoning=reasoning or [],
        decision_targets=decision_targets or [],
        panel_targets=panel_targets or [],
        write_targets=write_targets or [],
        form_scope=normalized_form_scope,
    ).to_dict()


def agenda_item_to_scheduled_event(item: dict[str, Any]) -> dict[str, Any]:
    evidence_basis = item.get("evidence_basis") or []
    guideline = " · ".join(str(entry) for entry in evidence_basis[:2]) if evidence_basis else ""
    return {
        "event_type": CANONICAL_SCHEDULE_EVENT_TYPES.get(item.get("item_type"), item.get("item_type")),
        "schedule_key": item.get("agenda_key"),
        "encounter_key": item.get("encounter_key"),
        "label": item.get("title"),
        "management_track": item.get("management_track"),
        "due_date": item.get("due_at"),
        "ideal_due_at": item.get("ideal_due_at") or item.get("due_at"),
        "scheduled_due_at": item.get("scheduled_due_at") or item.get("due_at"),
        "delay_days": int(item.get("delay_days") or 0),
        "plan_key": item.get("plan_key", ""),
        "completed_at": item.get("completed_at", ""),
        "guideline": guideline,
        "agenda_key": item.get("agenda_key"),
        "summary": item.get("summary", ""),
        "priority": item.get("priority", "routine"),
        "required_inputs": item.get("required_inputs", []),
        "capture_fields": item.get("capture_fields", []),
        "derived_requirements": item.get("derived_requirements", []),
        "required": bool(item.get("required", True)),
        "action_mode": item.get("action_mode", action_mode_for_task(item)),
        "status": item.get("status", "scheduled"),
        "title": item.get("title"),
        "decision_targets": item.get("decision_targets", []),
        "panel_targets": item.get("panel_targets", []),
        "write_targets": item.get("write_targets", []),
        "form_scope": item.get("form_scope", {}),
        "action_label": item.get("action_label", ""),
        "reasoning": item.get("reasoning", []),
        "blockers": item.get("blockers", []),
    }


def enrich_agenda_board_with_encounters(
    agenda_board: dict[str, Any],
    state: str,
    management_track: str,
) -> dict[str, Any]:
    items = [dict(item) for item in (agenda_board.get("items") or [])]
    encounters = build_encounter_plans(
        items,
        state=state,
        management_track=management_track,
        protocol_trace=agenda_board.get("protocol_trace") or {},
    )
    encounter_by_agenda_key = {
        str(task.get("agenda_key") or ""): str(encounter.get("encounter_key") or "")
        for encounter in encounters
        for task in (encounter.get("tasks") or [])
        if str(task.get("agenda_key") or "")
    }
    enriched_items = []
    for item in items:
        enriched = dict(item)
        enriched["encounter_key"] = encounter_by_agenda_key.get(str(item.get("agenda_key") or ""), "")
        enriched_items.append(enriched)
    enriched_items.sort(key=longitudinal_item_sort_key)
    actionable_encounters = [
        encounter
        for encounter in encounters
        if str(encounter.get("status") or "scheduled") not in {"completed", "cancelled", "superseded"}
    ]
    preferred_next_encounter = next(
        (encounter for encounter in actionable_encounters if str(encounter.get("visit_modality") or "") != "async"),
        actionable_encounters[0] if actionable_encounters else {},
    )
    agenda_board["items"] = enriched_items
    agenda_board["active_items"] = enriched_items
    agenda_board["encounters"] = encounters
    agenda_board["next_encounter"] = preferred_next_encounter
    return agenda_board


def build_protocol_comparators(state: str, management_track: str) -> list[dict[str, Any]]:
    comparators = [
        InstitutionalComparator(
            label="guideline_primary",
            mode="guideline_primary",
            title="Carril primario de guías",
            cadence_summary="NCCN 2026 + EAU 2026 definen la vigilancia y los disparadores principales.",
            notes=["Nunca se sustituye por benchmarks institucionales o supportive evidence."],
        ).to_dict()
    ]
    if management_track == "active_surveillance":
        comparators.append(
            InstitutionalComparator(
                label="MSK",
                mode="institutional_benchmark",
                title="Benchmark MSK para vigilancia activa",
                cadence_summary="PSA seriado, MRI y biopsia de confirmación/reevaluación en vigilancia activa.",
                source_label="MSK Active Surveillance",
                source_url="https://www.mskcc.org/cancer-care/types/prostate/treatment/active-surveillance",
                notes=["Benchmark visible, pero la agenda primaria sigue siendo guías NCCN/EAU."],
            ).to_dict()
        )
        comparators.append(
            InstitutionalComparator(
                label="Keck_USC",
                mode="institutional_benchmark",
                title="Benchmark Keck/USC",
                cadence_summary="Referencia institucional pública para trayectoria terapéutica y vigilancia local.",
                source_label="Keck/USC",
                source_url="https://www.keckmedicine.org/blog/treatment-options-for-prostate-cancer/",
            ).to_dict()
        )
    if management_track == "post_rp":
        comparators.append(
            InstitutionalComparator(
                label="center_protocol",
                mode="local_center_protocol",
                title="Protocolo local configurable post prostatectomía",
                cadence_summary="4, 8, 12 semanas; 6, 9, 12, 18, 24 y 36 meses, marcado explícitamente como protocolo local.",
                notes=["No desplaza el carril primario guiado por NCCN/EAU."],
            ).to_dict()
        )
    if management_track in {"on_arpi", "on_docetaxel", "on_parp", "on_lu177"}:
        comparators.append(
            InstitutionalComparator(
                label="source_pending",
                mode="source_pending",
                title="Comparadores institucionales avanzados",
                cadence_summary="Cleveland Clinic y Global Robotics permanecen pendientes hasta contar con documento verificable.",
                notes=["No se usan como default mientras no exista fuente pública validada."],
            ).to_dict()
        )
    return comparators


def build_protocol_trace(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    raw_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    anchor = resolve_track_anchor(patient, state, management_track, raw_assessment)
    protocol = build_stage_protocol(state, management_track, patient)
    comparators = build_protocol_comparators(state, management_track)
    benchmarks = [item for item in comparators if item.get("mode") == "institutional_benchmark"]
    local_center = next((item for item in comparators if item.get("mode") == "local_center_protocol"), {})
    return {
        "anchor_date": anchor.get("anchor_date", ""),
        "anchor_source": anchor.get("anchor_source", ""),
        "anchor_is_fallback": anchor.get("anchor_source", "").startswith("latest_assessment") or anchor.get("anchor_source", "") in {"identity.diagnosis_date", "identity.created_at"},
        "last_visit_date": anchor.get("last_visit_date", ""),
        "protocol_label": protocol.get("title", ""),
        "guideline_primary": protocol.get("evidence_basis", []),
        "institutional_benchmark": benchmarks,
        "local_center_protocol": local_center,
    }


def build_stage_protocol(state: str, management_track: str, patient: dict[str, Any]) -> dict[str, Any]:
    if state == "diagnostic_workup":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda diagnóstica",
            cadence_summary="Revisión en 6-12 semanas con PSA/PSAD, MRI y biopsia según riesgo.",
            purpose="Confirmar o descartar histología sin retrasar una lesión clínicamente significativa.",
            evidence_basis=["NCCN 2026", "EAU 2026 diagnóstico", "EAU Follow-up 2026"],
            comparator_basis=[],
        ).to_dict()
    if state == "post_negative_biopsy_followup":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Seguimiento tras biopsia benigna",
            cadence_summary="PSA cada 12-24 meses; MRI/rebiopsia solo si reaparece señal de riesgo.",
            purpose="Evitar rebiopsias innecesarias sin perder cáncer clínicamente significativo.",
            evidence_basis=["NCCN 2026", "EAU 2026 seguimiento", "5.pdf"],
            comparator_basis=[],
        ).to_dict()
    if management_track == "active_surveillance":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda de vigilancia activa",
            cadence_summary="PSA no más frecuente que cada 6 meses; MRI/biopsia según readiness y riesgo.",
            purpose="Sostener vigilancia activa segura con disparadores claros de salida.",
            evidence_basis=["NCCN 2026", "EAU 2026 localized", "EAU Follow-up 2026"],
            comparator_basis=["MSK Active Surveillance", "Keck/USC"],
        ).to_dict()
    if management_track == "pre_surgery":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Preparación prequirúrgica",
            cadence_summary="Counseling preoperatorio, algoritmos prequirúrgicos y PROs antes de definir cirugía.",
            purpose="Alinear riesgo patológico, función basal y decisión compartida antes de prostatectomía.",
            evidence_basis=["NCCN 2026", "EAU 2026 localized"],
            comparator_basis=["MSK pre-op", "Partin", "Briganti"],
        ).to_dict()
    if management_track == "post_rp":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Seguimiento post prostatectomía radical",
            cadence_summary="Primer PSA alrededor de 6-8 semanas; luego cada 6 meses hasta 3 años y anual después.",
            purpose="Detectar persistencia/recurrencia temprana y medir recuperación funcional.",
            evidence_basis=["NCCN 2026", "EAU Follow-up 2026"],
            comparator_basis=["center_protocol"],
        ).to_dict()
    if management_track == "post_rt":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Evaluación post radioterapia / salvage local",
            cadence_summary="PSA/nadir, definición Phoenix, reestadificación y toxicidad GU/GI antes de cerrar salvage local o redirección sistémica.",
            purpose="No abrir rescate post-RT sin confirmar falla bioquímica/local y sin matriz real de factibilidad anatómica y funcional.",
            evidence_basis=["NCCN 2026", "EAU Follow-up 2026", "EAU 2026 recurrencia", "1.pdf"],
            comparator_basis=[],
        ).to_dict()
    if management_track in {"salvage", "salvage_evaluation"}:
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Ruta de rescate" if management_track == "salvage" else "Evaluación temprana de rescate",
            cadence_summary="PSA ultrasensible, PSADT e imagen dirigida para definir ventana curativa o intensificación.",
            purpose="No perder oportunidad de rescate curativo y evitar intensificación prematura.",
            evidence_basis=["NCCN 2026", "EAU 2026 recurrencia", "RAVES", "RADICALS-RT", "GETUG-AFU 16", "RTOG 9601", "EMPIRE-1"],
            comparator_basis=[],
        ).to_dict()
    if state == "adt_progression_verification":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Confirmación de progresión bajo ADT",
            cadence_summary="Confirmación corta con testosterona, backbone ADT, revisión terapéutica e imagen convencional en 2-6 semanas.",
            purpose="Confirmar progresión real bajo castración antes de escalar a una nueva etapa sistémica.",
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "PCWG3"],
            comparator_basis=[],
        ).to_dict()
    if state in ADVANCED_STATES:
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda sistémica avanzada",
            cadence_summary="Labs/síntomas cada 1-3 meses; imagen cada 3-6 meses o antes si hay deterioro clínico.",
            purpose="Secuenciar terapia, vigilar toxicidad y activar soporte concurrente.",
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "36.pdf", "37.pdf", "40.pdf", "41.pdf"],
            comparator_basis=[],
        ).to_dict()
    return StageProtocolDefinition(
        state=state,
        management_track=management_track,
        title="Agenda clínica",
        cadence_summary="Seguimiento estructurado según etapa y eventos longitudinales.",
        purpose="Mantener continuidad, seguridad y datos decisores vigentes.",
        evidence_basis=["NCCN 2026", "EAU 2026"],
        comparator_basis=[],
    ).to_dict()


def _diagnostic_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_mri = _latest_by(patient.get("mri_facts", []), "fact_date")
    latest_trigger = _latest_by(patient.get("biopsy_triggers", []), "trigger_date")
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    reference = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_trigger.get("trigger_date"), identity.get("diagnosis_date"))) or date.today()
    current_psad = _safe_float(_first_nonempty(latest_followup.get("psad"), truth_values.get("psad"), (patient.get("baseline") or {}).get("psad"))) or 0.0
    current_pirads = _safe_int(_first_nonempty(latest_followup.get("pirads_score"), truth_values.get("pirads_score"), latest_mri.get("pirads_score"), (patient.get("baseline") or {}).get("pirads_score"))) or 0
    current_dre_suspicious = str(_first_nonempty(latest_followup.get("dre_suspicious"), truth_values.get("dre_suspicious"), (patient.get("baseline") or {}).get("dre_suspicious"))).strip().lower() in {"1", "true", "yes", "si", "sí"}
    biopsy_trigger_still_active = current_pirads >= 4 or current_psad >= 0.15 or current_dre_suspicious
    items = [
        _agenda_item(
            f"{state}:{track}:psa_review",
            "psa",
            "PSA / PSAD y revisión clínica",
            state,
            track,
            reference,
            42,
            summary="Repetir PSA/PSAD y revisar si la sospecha sigue activa.",
            required_inputs=["psa", "psad"],
            completion_rule={"any_of": ["psa", "psad"]},
            evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
            generated_from_event="recommendation_generated",
        ),
    ]
    if not latest_mri or not _is_present(latest_mri.get("mpmri_quality")):
        items.append(
            _agenda_item(
                f"{state}:{track}:mri_quality",
                "imaging",
                "MRI multiparamétrica de calidad diagnóstica",
                state,
                track,
                reference,
                14,
                priority="high",
                summary="La ruta diagnóstica sigue incompleta sin MRI utilizable o equivalente.",
                required_inputs=["mpmri_quality", "pirads_score"],
                completion_rule={"all_of": ["mpmri_quality"]},
                evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
                generated_from_event="recommendation_generated",
            )
        )
    if latest_trigger and not patient.get("biopsies") and biopsy_trigger_still_active:
        trigger_date = _parse_date(latest_trigger.get("trigger_date")) or reference
        items.append(
            _agenda_item(
                f"{state}:{track}:biopsy",
                "biopsy",
                "Biopsia dirigida + sistemática",
                state,
                track,
                trigger_date,
                30,
                priority="high",
                summary="El trigger de biopsia ya está activo y aún no existe histología confirmada.",
                required_inputs=["planned_biopsy_type", "planned_biopsy_route"],
                completion_rule={"requires_event_target": "biopsy_details"},
                evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
                generated_from_event="biopsy_trigger",
            )
        )
    return items


def _localized_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_pro = _latest_by(patient.get("pros", []), "assessment_date")
    latest_biopsy = _latest_by(patient.get("biopsies", []), "biopsy_date")
    latest_mri = _latest_by(patient.get("imaging", []), "study_date")
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_biopsy.get("biopsy_date"), identity.get("diagnosis_date"))) or date.today()
    items = []
    if track == "active_surveillance":
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa",
                    "psa",
                    "PSA seriado",
                    state,
                    track,
                    base_date,
                    180,
                    summary="El carril guideline-primary de vigilancia activa usa PSA no más frecuente que cada 6 meses.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026", "MSK Active Surveillance"],
                    comparator_basis=["MSK Active Surveillance", "Keck/USC"],
                    generated_from_event="followup_visit_recorded",
                ),
                _agenda_item(
                    f"{state}:{track}:pros",
                    "pro_assessment",
                    "PROs urinarios, sexuales e intestinales",
                    state,
                    track,
                    _parse_date(latest_pro.get("assessment_date")) or base_date,
                    180,
                    summary="Comparar calidad de vida y síntomas contra el basal ayuda a sostener la ruta elegida.",
                    required_inputs=["ipss_total", "iief5_score", "eq5d_vas"],
                    completion_rule={"any_of": ["ipss_total", "iief5_score", "eq5d_vas"]},
                    evidence_basis=["EAU Follow-up 2026", "CEASAR style PRO logic"],
                    generated_from_event="followup_visit_recorded",
                ),
                _agenda_item(
                    f"{state}:{track}:mri_biopsy",
                    "imaging",
                    "MRI / biopsia confirmatoria según readiness",
                    state,
                    track,
                    _parse_date(_first_nonempty(latest_mri.get("study_date"), latest_biopsy.get("biopsy_date"), identity.get("diagnosis_date"))) or date.today(),
                    365,
                    priority="high",
                    summary="Confirmar estabilidad anatómica e histológica antes de sostener vigilancia activa expandida.",
                    required_inputs=["prior_mpmri_pirads_score", "precise_score"],
                    completion_rule={"any_of": ["pirads_score", "precise_score", "biopsy_details"]},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026", "MSK Active Surveillance"],
                    comparator_basis=["MSK Active Surveillance", "Keck/USC"],
                    generated_from_event="management_selected",
                ),
            ]
        )
        # Enrich with AS protocol schedule from active_surveillance module
        try:
            from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
            as_data = {}
            as_data.update(identity)
            as_data.update(patient.get("baseline", {}) or {})
            as_data.update(patient.get("prior_history", {}) or {})
            if patient.get("follow_ups"):
                as_data.update(patient["follow_ups"][-1])
            as_protocol = ActiveSurveillanceService.build_as_protocol(as_data, state)
            if as_protocol and as_protocol.schedule:
                for sched_item in as_protocol.schedule:
                    if sched_item.status == "overdue":
                        items.append(
                            _agenda_item(
                                f"{state}:{track}:as_{sched_item.item_type}_{sched_item.due_date}",
                                sched_item.item_type,
                                f"[VA Protocolo] {sched_item.title}",
                                state,
                                track,
                                _parse_date(sched_item.due_date) or base_date,
                                0,
                                priority="high",
                                summary=f"Item vencido del protocolo de vigilancia activa: {sched_item.title}",
                                required_inputs=[],
                                evidence_basis=sched_item.evidence_basis if hasattr(sched_item, "evidence_basis") else ["NCCN 2026 AS"],
                                generated_from_event="as_protocol_schedule",
                            )
                        )
        except Exception:
            pass
    elif track == "pre_surgery":
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:surgery_board",
                    "therapy_review",
                    "Decision board prequirúrgico",
                    state,
                    track,
                    base_date,
                    14,
                    priority="high",
                    summary="Revisar CAPRA, Briganti, Partin y MSKCC junto con PROs y patología.",
                    required_inputs=["capra", "briganti", "partin", "mskcc_preop"],
                    derived_requirements=["capra", "briganti", "partin", "mskcc_preop"],
                    completion_rule={"note": "Revisión clínica del panel prequirúrgico"},
                    evidence_basis=["NCCN 2026", "EAU 2026", "MSK pre-op"],
                    comparator_basis=["MSK pre-op", "Partin", "Briganti"],
                    generated_from_event="management_selected",
                ),
                _agenda_item(
                    f"{state}:{track}:pros_baseline",
                    "pro_assessment",
                    "Completar PROs basales",
                    state,
                    track,
                    _parse_date(latest_pro.get("assessment_date")) or base_date,
                    14,
                    priority="high",
                    summary="La conversación compartida antes de cirugía requiere línea funcional basal documentada.",
                    required_inputs=["ipss_total", "iief5_score", "eq5d_vas", "fact_p_total"],
                    completion_rule={"any_of": ["ipss_total", "iief5_score", "eq5d_vas"]},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026"],
                    generated_from_event="management_selected",
                ),
            ]
        )
    else:
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa_local_decision",
                    "psa",
                    "PSA y staging para decisión local",
                    state,
                    track,
                    base_date,
                    21,
                    summary="Reconfirmar PSA, extensión clínica e imagen antes de cerrar la trayectoria local definitiva.",
                    required_inputs=["psa", "clinical_tstage"],
                    completion_rule={"any_of": ["psa", "clinical_tstage"]},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026"],
                    generated_from_event="recommendation_generated",
                ),
                _agenda_item(
                    f"{state}:{track}:shared_decision",
                    "therapy_review",
                    "Revisar decisión local y datos faltantes",
                    state,
                    track,
                    base_date,
                    21,
                    summary="Cerrar datos anatómicos, patológicos y funcionales antes de fijar la trayectoria local.",
                    required_inputs=["prior_mpmri_pirads_score", "percent_pattern_4", "ipss_total"],
                    completion_rule={"note": "Documentar datos decisores faltantes"},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026"],
                    generated_from_event="recommendation_generated",
                ),
            ]
        )
    return items


def _postlocal_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    surgery = patient.get("surgery") or {}
    bcr = patient.get("bcr") or {}
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), bcr.get("bcr_date"), surgery.get("surgery_date"), identity.get("diagnosis_date"))) or date.today()
    items = []
    if track == "post_rp":
        surgery_date = _parse_date(surgery.get("surgery_date")) or base_date
        if not latest_followup:
            items.append(
                _agenda_item(
                    f"{state}:{track}:psa_first",
                    "psa",
                    "Primer PSA ultrasensible post prostatectomía",
                    state,
                    track,
                    surgery_date,
                    56,
                    priority="high",
                    summary="El primer PSA alrededor de 6-8 semanas orienta persistencia posoperatoria.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                    comparator_basis=["center_protocol"],
                    generated_from_event="procedure_performed",
                )
            )
        else:
            items.append(
                _agenda_item(
                    f"{state}:{track}:psa_serial",
                    "psa",
                    "PSA ultrasensible seriado",
                    state,
                    track,
                    _parse_date(latest_followup.get("visit_date")) or base_date,
                    180,
                    summary="Luego del primer control, el carril guideline-primary sigue PSA cada 6 meses hasta 3 años.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                    comparator_basis=["center_protocol"],
                    generated_from_event="followup_visit_recorded",
                )
            )
        items.append(
            _agenda_item(
                f"{state}:{track}:functional",
                "pro_assessment",
                "Recuperación funcional urinaria y sexual",
                state,
                track,
                _parse_date(latest_followup.get("visit_date")) or surgery_date,
                90,
                summary="Pads/día, continencia, potencia y uso de PDE5i cambian soporte y rehabilitación.",
                required_inputs=["pad_usage", "iief5_score"],
                completion_rule={"any_of": ["pad_usage", "iief5_score"]},
                evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                generated_from_event="procedure_performed",
            )
        )
    elif track in {"salvage", "salvage_evaluation"}:
        latest_assessment = dict(patient.get("latest_assessment") or {})
        result_snapshot = dict(latest_assessment.get("result_snapshot") or {})
        salvage_monitoring = dict(result_snapshot.get("active_regimen_monitoring_package") or {})
        salvage_sequence = dict(result_snapshot.get("sequence_transition_bundle") or {})
        intensification_profile = dict(
            result_snapshot.get("post_rp_salvage_intensification_profile")
            or build_post_rp_salvage_intensification_profile(latest_assessment.get("input_snapshot") or {})
        )
        salvage_fields = list(salvage_monitoring.get("required_visit_fields") or ["psa", "psadt_months", "salvage_local_feasible"])
        imaging_fields = [field for field in salvage_fields if field in {"restaging_imaging_type", "restaging_imaging_date", "psma_pet_date", "psma_pet_done", "conventional_imaging_status"}] or ["imaging_modality"]
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa_rescue",
                    "psa",
                    "PSA ultrasensible / PSADT",
                    state,
                    track,
                    base_date,
                    90,
                    priority="high",
                    summary=str(
                        salvage_sequence.get("line_change_reason")
                        or salvage_monitoring.get("monitoring_focus")
                        or "La cinética del PSA determina si todavía existe ventana curativa o si ya hay que intensificar."
                    ),
                    required_inputs=salvage_fields,
                    capture_fields=salvage_fields,
                    completion_rule={"any_of": salvage_fields[:3] or ["psa"]},
                    evidence_basis=["EAU 2026 recurrencia", "NCCN 2026", "RAVES", "RADICALS-RT", "GETUG-AFU 16", "RTOG 9601"],
                    generated_from_event="recommendation_generated",
                    form_scope={"mode": "item_scoped", "focus": "salvage_rt_family", "capture_fields": salvage_fields},
                ),
                _agenda_item(
                    f"{state}:{track}:imaging_gate",
                    "imaging",
                    "Imagen dirigida por rescate",
                    state,
                    track,
                    base_date,
                    120,
                    summary="Solo indicar PSMA-PET o imagen adicional si cambia la factibilidad de rescate.",
                    required_inputs=imaging_fields,
                    capture_fields=imaging_fields,
                    completion_rule={"requires_event_target": "imaging_studies"},
                    evidence_basis=["EAU 2026 recurrencia", "NCCN 2026"],
                    generated_from_event="recommendation_generated",
                    form_scope={"mode": "item_scoped", "focus": "restaging", "capture_fields": imaging_fields},
                ),
            ]
        )
        if bool(intensification_profile.get("high_risk_post_rp_salvage")):
            items.extend(
                [
                    _agenda_item(
                        f"{state}:{track}:salvage_intensification",
                        "treatment_plan",
                        "Cerrar intensificación del salvage post-RP",
                        state,
                        track,
                        base_date,
                        21,
                        priority="high",
                        summary="El caso post-RP ya tiene rasgos de alto riesgo; la agenda debe cerrar SRT + ADT en vez de dejar RT sola como salida implícita.",
                        required_inputs=["psa", "psadt_months", "salvage_local_feasible"],
                        capture_fields=["psa", "psadt_months", "salvage_local_feasible"],
                        completion_rule={"any_of": ["psa", "psadt_months"]},
                        evidence_basis=["AUA/ASTRO/SUO 2024", "GETUG-AFU 16", "RTOG 9601", "RADICALS-HD"],
                        generated_from_event="recommendation_generated",
                    ),
                    _agenda_item(
                        f"{state}:{track}:psma_companion",
                        "imaging",
                        "PSMA PET/CT urgente como companion de salvage",
                        state,
                        track,
                        base_date,
                        14,
                        priority="high",
                        summary="La PSMA debe definir lecho versus lecho + pelvis y descartar redirección sistémica, sin retrasar la SRT si sale negativa.",
                        required_inputs=["psma_pet_done"],
                        capture_fields=["psma_pet_done", "psma_pet_date", "psma_stage_after_psma"],
                        completion_rule={"any_of": ["psma_pet_done"]},
                        evidence_basis=["EAU 2026 recurrencia", "AUA/ASTRO/SUO 2024"],
                        generated_from_event="recommendation_generated",
                    ),
                    _agenda_item(
                        f"{state}:{track}:pelvic_field_duration",
                        "treatment_plan",
                        "Definir pelvis electiva y duración de ADT",
                        state,
                        track,
                        base_date,
                        28,
                        priority="medium",
                        summary="Cerrar si corresponde irradiación pélvica electiva y si la ADT será corta o prolongada según riesgo.",
                        required_inputs=["pathologic_stage", "surgical_margin", "psadt_months"],
                        capture_fields=["pathologic_stage", "surgical_margin", "psadt_months", "svi_status", "lni_status"],
                        completion_rule={"any_of": ["pathologic_stage", "psadt_months"]},
                        evidence_basis=["SPPORT", "RTOG 9601", "RADICALS-HD"],
                        generated_from_event="recommendation_generated",
                    ),
                ]
            )
    else:
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa_serial",
                    "psa",
                    "PSA ultrasensible seriado",
                    state,
                    track,
                    base_date,
                    180,
                    summary="La vigilancia postoperatoria estable sigue PSA ultrasensible seriado y recuperación funcional.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                    generated_from_event="followup_visit_recorded",
                ),
            ]
        )
    return items


def _advanced_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    def _active_regimen_agenda_context() -> tuple[dict[str, Any], dict[str, Any]]:
        latest_assessment = dict(patient.get("latest_assessment") or {})
        result_snapshot = dict(latest_assessment.get("result_snapshot") or {})
        preferred_regimen = dict(result_snapshot.get("preferred_frontline_regimen") or {})
        sequence_bundle = dict(result_snapshot.get("sequence_transition_bundle") or {})
        monitoring_package = dict(result_snapshot.get("active_regimen_monitoring_package") or {})
        latest_followup_local = _latest_by(patient.get("follow_ups", []), "visit_date")
        field_values = {}
        if isinstance((latest_followup_local or {}).get("visit_bundle"), dict):
            field_values.update(dict(((latest_followup_local.get("visit_bundle") or {}).get("payload")) or {}))
        if latest_followup_local:
            field_values.update({k: v for k, v in latest_followup_local.items() if v not in (None, "", [], {})})
        if not monitoring_package:
            active_regimen_code = str(
                preferred_regimen.get("regimen_code")
                or field_values.get("drug_scheme")
                or field_values.get("current_treatment")
                or ""
            )
            active_family = str(
                preferred_regimen.get("family_code")
                or sequence_bundle.get("active_family")
                or regimen_family_code(active_regimen_code, fallback="observation_family")
            )
            monitoring_package = build_active_regimen_monitoring_package(
                active_regimen_code,
                family_code=active_family,
                field_values=field_values,
            )
        return monitoring_package, sequence_bundle

    def _monitoring_interval_days(monitoring_package: dict[str, Any], fallback: int) -> int:
        family_code = str(monitoring_package.get("family_code") or "")
        default_by_family = {
            "taxane_family": 21,
            "abiraterone_steroid_family": 28,
            "parp_family": 28,
            "arpi_family": 42,
            "psma_rlt_family": 42,
            "salvage_rt_family": 42,
            "local_mdt_family": 42,
            "radium223_family": 28,
            "surveillance_family": 90,
            "active_surveillance_family": 180,
        }
        return default_by_family.get(family_code, fallback)

    def _subset(fields: list[str], allowed: set[str], fallback: list[str]) -> list[str]:
        selected = [field for field in fields if field in allowed]
        return list(dict.fromkeys(selected or fallback))

    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_imaging = _latest_by(patient.get("imaging", []), "study_date")
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_imaging.get("study_date"), patient.get("identity", {}).get("diagnosis_date"))) or date.today()
    interval_days = 60
    lab_interval_days = 60
    imaging_interval_days = 120
    if state == "adt_progression_verification":
        interval_days = 21
        lab_interval_days = 21
        imaging_interval_days = 42
    if track == "on_docetaxel":
        interval_days = 21
        lab_interval_days = 21
        imaging_interval_days = 84
    elif track == "on_parp":
        interval_days = 28
        lab_interval_days = 28
        imaging_interval_days = 84
    elif track == "on_lu177":
        interval_days = 42
        lab_interval_days = 42
        imaging_interval_days = 84
    elif track == "on_arpi":
        interval_days = 42
        lab_interval_days = 42
        imaging_interval_days = 120
    elif track == "concurrent_palliative_care":
        interval_days = 14
        lab_interval_days = 14
        imaging_interval_days = 21
    elif track == "supportive_only":
        interval_days = 14
        lab_interval_days = 14
        imaging_interval_days = 28
    elif track == "hospice_pathway":
        interval_days = 7
        lab_interval_days = 7
        imaging_interval_days = 14
    active_monitoring_package, sequence_bundle = _active_regimen_agenda_context()
    palliative_transition_bundle = build_palliative_transition_bundle(
        patient,
        state=state,
        management_track=track,
        latest_assessment=patient.get("latest_assessment"),
    )
    palliative_monitoring_package = build_palliative_monitoring_package(
        patient,
        state=state,
        management_track=track,
        latest_assessment=patient.get("latest_assessment"),
        transition_bundle=palliative_transition_bundle,
    )
    monitoring_fields = list(active_monitoring_package.get("required_visit_fields") or [])
    monitoring_interval_days = _monitoring_interval_days(active_monitoring_package, interval_days)
    trigger_status = str(sequence_bundle.get("trigger_status") or "")
    monitoring_focus = str(active_monitoring_package.get("monitoring_focus") or "")
    active_label = str(active_monitoring_package.get("active_regimen_label") or family_label(str(active_monitoring_package.get("family_code") or "")))
    therapy_title = f"Monitorización activa de {active_label}" if active_label else "Revisión terapéutica activa"
    if trigger_status == "hold":
        therapy_title = f"Seguridad y pausa de {active_label}" if active_label else "Seguridad y pausa terapéutica"
    elif trigger_status in {"switch", "redirect_local", "redirect_systemic"}:
        therapy_title = f"Reevaluar transición de {active_label}" if active_label else "Reevaluar transición terapéutica"
    therapy_summary = str(sequence_bundle.get("line_change_reason") or monitoring_focus or "Revisar respuesta, toxicidad, síntomas y continuidad del backbone terapéutico.")
    therapy_fields = monitoring_fields or ["disease_status", "current_treatment", "ecog", "line_of_therapy_number", "line_of_therapy_context", "drug_scheme"]
    lab_fields = _subset(
        therapy_fields,
        {"psa", "testosterone", "cbc_date", "anc", "platelets", "hemoglobin", "ast", "alt", "bilirubin", "alp", "potassium", "glucose", "renal_function"},
        ["psa", "testosterone", "alp", "ldh", "hemoglobin"],
    )
    imaging_fields = _subset(
        therapy_fields,
        {"restaging_imaging_type", "restaging_imaging_date", "psma_pet_date", "psma_pet_done", "conventional_imaging_status"},
        ["imaging_modality"],
    )
    if track in {"supportive_only", "hospice_pathway"}:
        monitoring_interval_days = 7 if track == "hospice_pathway" else 14
        trigger_status = str(palliative_transition_bundle.get("trigger_status") or trigger_status)
        monitoring_focus = str(
            palliative_monitoring_package.get("monitoring_focus")
            or palliative_transition_bundle.get("trigger_status_label")
            or monitoring_focus
        )
        active_label = str(palliative_transition_bundle.get("care_mode_label") or "Soporte paliativo")
        therapy_title = "Seguimiento paliativo dominante" if track == "supportive_only" else "Seguimiento hospice y soporte intensivo"
        therapy_summary = str(
            " · ".join(list(palliative_transition_bundle.get("trigger_reasons") or [])[:3])
            or palliative_monitoring_package.get("monitoring_focus")
            or therapy_summary
        )
        therapy_fields = list(palliative_monitoring_package.get("required_visit_fields") or therapy_fields)
        lab_fields = _subset(
            therapy_fields,
            {"albumin", "weight_loss_6m_kg", "opioid_use", "breakthrough_pain", "bowel_regimen_started"},
            ["albumin", "weight_loss_6m_kg", "opioid_use"],
        )
        imaging_fields = _subset(
            therapy_fields,
            {
                "spinal_cord_compression",
                "epidural_compression",
                "pathological_fracture_risk",
                "obstructive_uropathy",
                "hematuria_severe",
                "brain_metastasis",
            },
            ["spinal_cord_compression", "pathological_fracture_risk", "obstructive_uropathy"],
        )
    items = [
        _agenda_item(
            f"{state}:{track}:therapy_review",
            "therapy_review",
            therapy_title,
            state,
            track,
            base_date,
            monitoring_interval_days,
            priority="high",
            summary=therapy_summary,
            required_inputs=therapy_fields,
            capture_fields=therapy_fields,
            completion_rule={"note": "Revisión clínica y terapéutica"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
            generated_from_event="followup_visit_recorded",
            decision_targets=["disease_control", "line_continuation", "systemic_sequencing"],
            panel_targets=["sequencing_context", "safety_support_context"],
            write_targets=["follow_up_visits", "stage_visit_records", "treatment_history"],
            form_scope={
                "mode": "item_scoped",
                "focus": monitoring_focus or "therapy_review",
                "capture_fields": therapy_fields,
                "trigger_status": trigger_status,
                "recommended_cadence": active_monitoring_package.get("recommended_cadence", ""),
            },
        ),
        _agenda_item(
            f"{state}:{track}:labs",
            "lab_panel",
            "Laboratorio de seguridad y actividad",
            state,
            track,
            base_date,
            lab_interval_days,
            priority="high",
            summary="PSA, testosterona y laboratorio ampliado según terapia activa.",
            required_inputs=lab_fields,
            capture_fields=lab_fields,
            completion_rule={"any_of": lab_fields[:5] or ["psa"]},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
            generated_from_event="followup_visit_recorded",
            decision_targets=["castration_status", "disease_control", "line_continuation"],
            panel_targets=["sequencing_context", "safety_support_context"],
            write_targets=["follow_up_visits", "stage_visit_records", "biomarker_longitudinal"],
            form_scope={"mode": "item_scoped", "focus": "lab_panel", "capture_fields": lab_fields},
        ),
        _agenda_item(
            f"{state}:{track}:imaging",
            "imaging",
            "Imagen oncológica seriada",
            state,
            track,
            _parse_date(latest_imaging.get("study_date")) or base_date,
            imaging_interval_days,
            summary=(
                "Reestadificar cada 3-6 meses o antes si hay deterioro clínico o nuevo dolor."
                if trigger_status not in {"switch", "redirect_local", "redirect_systemic"}
                else "La transición de línea o redirección actual exige imagen/restaging estructurados."
            ),
            required_inputs=imaging_fields,
            capture_fields=imaging_fields,
            completion_rule={"requires_event_target": "imaging_studies"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
            generated_from_event="followup_visit_recorded",
            decision_targets=["radiographic_restage", "psma_eligibility", "disease_burden"],
            panel_targets=["sequencing_context", "biomarker_context"],
            write_targets=["stage_visit_records", "imaging_studies"],
            form_scope={"mode": "item_scoped", "focus": "imaging", "capture_fields": imaging_fields},
        ),
    ]
    if track == "on_arpi":
        arpi_safety_source_fields = list(
            dict.fromkeys(
                list(therapy_fields)
                + [
                    "mini_cog_score",
                    "fatigue_score",
                    "cv_risk_documented",
                    "ddi_review_status",
                    "systolic_bp",
                    "dermatitis_history",
                ]
            )
        )
        arpi_safety_fields = _subset(
            arpi_safety_source_fields,
            {"mini_cog_score", "fatigue_score", "cv_risk_documented", "ddi_review_status", "systolic_bp", "dermatitis_history"},
            ["mini_cog_score", "fatigue_score", "cv_risk_documented", "ddi_review_status"],
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:arpi_safety",
                "toxicity_review",
                "Bundle de seguridad ARPI",
                state,
                track,
                base_date,
                28,
                priority="high",
                summary="Convulsiones, dermatitis, cognición, fatiga, CV/DDI/hepático, nutrición y actividad física.",
                required_inputs=arpi_safety_fields,
                capture_fields=arpi_safety_fields,
                completion_rule={"any_of": arpi_safety_fields[:4] or ["mini_cog_score"]},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["arpi_safety", "supportive_care", "treatment_tolerability"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "data_provenance"],
                form_scope={"mode": "item_scoped", "focus": "arpi_safety", "capture_fields": arpi_safety_fields},
            )
        )
    items.append(
        _agenda_item(
            f"{state}:{track}:bone_support",
            "supportive_care",
            "Salud ósea y soporte",
            state,
            track,
            base_date,
            90,
            summary="Vigilar DXA, calcio/vitamina D, protección ósea, ejercicio y soporte psicosocial.",
            required_inputs=["dxa_baseline_done", "calcium_vitd_started", "bone_protection_started"],
            completion_rule={"note": "Completar bundle óseo y rehabilitación"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "39.pdf"],
            generated_from_event="followup_visit_recorded",
            decision_targets=["bone_safety", "supportive_care"],
            panel_targets=["safety_support_context"],
            write_targets=["follow_up_visits", "stage_visit_records", "clinical_baseline"],
            form_scope={"mode": "item_scoped", "focus": "bone_support"},
        )
    )
    items.append(
        _agenda_item(
            f"{state}:{track}:frailty_fitness",
            "supportive_care",
            "Fragilidad y fitness terapéutica",
            state,
            track,
            base_date,
            90,
            priority="high",
            summary="Completa G8, Fried y estado funcional para evitar clasificar al paciente como fit por ausencia de datos.",
            required_inputs=[
                "ecog",
                "g8_food_intake",
                "g8_weight_loss",
                "g8_mobility",
                "g8_neuropsych",
                "g8_bmi",
                "g8_medications",
                "g8_self_health",
                "weight_loss_6m_kg",
                "fatigue_score",
                "low_activity",
                "slow_gait",
                "weak_grip",
            ],
            completion_rule={"any_of": ["g8_food_intake", "g8_weight_loss", "weight_loss_6m_kg", "fatigue_score", "low_activity", "slow_gait", "weak_grip"]},
            evidence_basis=["EAU 2026 avanzada", "NCCN 2026 survivorship"],
            generated_from_event="missing_critical_inputs",
            decision_targets=["frailty", "treatment_fitness", "treatment_intensity"],
            panel_targets=["safety_support_context"],
            write_targets=["stage_visit_records", "follow_up_visits", "patient_demographics", "data_provenance"],
            form_scope={"mode": "item_scoped", "focus": "frailty_fitness"},
        )
    )
    if track in {"on_arpi", "systemic_surveillance"} or (patient.get("prior_history") or {}).get("prior_adt"):
        cv_value, cv_source, cv_date = _latest_value_snapshot(
            patient,
            "systolic_bp",
            "total_cholesterol",
            "hdl_cholesterol",
            "triglycerides",
            "glucose",
            "hba1c",
            "waist_circumference_cm",
        )
        cv_inputs = [
            "systolic_bp",
            "total_cholesterol",
            "hdl_cholesterol",
            "triglycerides",
            "glucose",
            "waist_circumference_cm",
        ]
        cv_reasoning = []
        if cv_source:
            cv_reasoning.append(f"Último input metabólico desde {cv_source} ({cv_date or 'sin fecha'}).")
        items.append(
            _agenda_item(
                f"{state}:{track}:adt_cv_metabolic",
                "supportive_care",
                "Monitoreo CV y metabólico bajo ADT",
                state,
                track,
                base_date,
                28,
                priority="high",
                summary="Ayuda a prevenir eventos CV/metabólicos, sostener el tratamiento y elegir ARPI con mejor perfil de seguridad.",
                required_inputs=cv_inputs,
                completion_rule={"any_of": cv_inputs},
                evidence_basis=["EAU 2026 avanzada", "NCCN 2026 survivorship"],
                generated_from_event="followup_visit_recorded",
                blockers=[] if cv_value else ["Falta perfil metabólico / PA basal reciente"],
                reasoning=cv_reasoning,
                decision_targets=["cv_safety", "arpi_safety", "supportive_care"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "data_provenance"],
                form_scope={"mode": "item_scoped", "focus": "adt_cv_metabolic"},
            )
        )
        bone_value, bone_source, bone_date = _latest_value_snapshot(
            patient,
            "dxa_t_score_lumbar",
            "dxa_t_score_hip",
            "dxa_baseline_done",
            "vitamin_d_level",
            "bone_protection_started",
        )
        bone_reasoning = []
        if bone_source:
            bone_reasoning.append(f"Último dato óseo desde {bone_source} ({bone_date or 'sin fecha'}).")
        items.append(
            _agenda_item(
                f"{state}:{track}:adt_bone_monitor",
                "supportive_care",
                "Monitoreo óseo y vitamina D bajo ADT",
                state,
                track,
                base_date,
                42,
                priority="high",
                summary="Busca osteoporosis/fractura evitable y completa el bundle óseo durante la exposición a ADT.",
                required_inputs=["dxa_baseline_done", "vitamin_d_level", "bone_protection_started"],
                completion_rule={"any_of": ["dxa_baseline_done", "vitamin_d_level", "bone_protection_started"]},
                evidence_basis=["EAU 2026 avanzada", "NCCN 2026 survivorship", "39.pdf"],
                generated_from_event="followup_visit_recorded",
                blockers=[] if bone_value else ["Falta DXA / vitamina D / protección ósea"],
                reasoning=bone_reasoning,
                decision_targets=["bone_safety", "supportive_care"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "clinical_baseline"],
                form_scope={"mode": "item_scoped", "focus": "adt_bone_monitor"},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:adt_qol_fatigue",
                "pro_assessment",
                "Fatiga, sexualidad y calidad de vida bajo ADT",
                state,
                track,
                base_date,
                42,
                summary="Sirve para detectar toxicidad funcional y cognitiva que modifica adherencia, seguridad y selección terapéutica.",
                required_inputs=["fatigue_score", "iief5_score", "eq5d_vas"],
                completion_rule={"any_of": ["fatigue_score", "iief5_score", "eq5d_vas"]},
                evidence_basis=["NCCN 2026 survivorship", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["quality_of_life", "treatment_tolerability"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "patient_pros"],
                form_scope={"mode": "item_scoped", "focus": "adt_qol_fatigue"},
            )
        )
    palliative_active = bool(palliative_transition_bundle.get("available")) and (
        track in PALLIATIVE_ALIAS_TRACKS or str(palliative_transition_bundle.get("trigger_status") or "") not in {"", "observe"}
    )
    if palliative_active:
        palliative_required_fields = list(palliative_monitoring_package.get("required_visit_fields") or [])
        symptom_fields = _subset(
            palliative_required_fields,
            {
                "pain",
                "bpi_worst_pain",
                "bone_pain",
                "neuropathic_pain",
                "fatigue_score",
                "dyspnea_score",
                "nausea_score",
                "constipation_score",
                "appetite_loss",
                "insomnia_score",
                "ecog",
                "ecog_delta_3mo",
            },
            ["pain", "bpi_worst_pain", "fatigue_score", "dyspnea_score", "ecog"],
        )
        opioid_fields = _subset(
            palliative_required_fields,
            {"current_analgesics", "opioid_use", "breakthrough_pain", "bowel_regimen_started", "constipation_score"},
            ["current_analgesics", "opioid_use", "breakthrough_pain", "bowel_regimen_started"],
        )
        emergency_fields = _subset(
            palliative_required_fields,
            {"spinal_cord_compression", "epidural_compression", "pathological_fracture_risk", "obstructive_uropathy", "hematuria_severe", "brain_metastasis", "visceral_crisis"},
            ["spinal_cord_compression", "pathological_fracture_risk", "obstructive_uropathy"],
        )
        goals_fields = _subset(
            palliative_required_fields,
            {"advance_directive_documented", "goals_of_care_discussed", "healthcare_surrogate_designated", "patient_prefers_comfort"},
            ["advance_directive_documented", "goals_of_care_discussed", "healthcare_surrogate_designated", "patient_prefers_comfort"],
        )
        hospice_fields = _subset(
            palliative_required_fields,
            {"ecog", "weight_loss_6m_kg", "albumin", "patient_prefers_comfort", "prior_systemic_lines", "advance_directive_documented"},
            ["ecog", "weight_loss_6m_kg", "albumin", "patient_prefers_comfort", "prior_systemic_lines"],
        )
        rt_bone_fields = _subset(
            palliative_required_fields,
            {"bone_pain", "pathological_fracture_risk", "spinal_cord_compression", "epidural_compression", "hematuria_severe", "obstructive_uropathy"},
            ["bone_pain", "pathological_fracture_risk", "spinal_cord_compression"],
        )
        caregiver_fields = _subset(
            palliative_required_fields,
            {"depression_score", "anxiety_score", "insomnia_score", "healthcare_surrogate_designated", "goals_of_care_discussed", "patient_prefers_comfort"},
            ["depression_score", "anxiety_score", "healthcare_surrogate_designated", "goals_of_care_discussed"],
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:symptom_control_bundle",
                "supportive_care",
                "Control sintomático paliativo",
                state,
                track,
                base_date,
                14,
                priority="high",
                summary="Dolor, disnea, fatiga, estreñimiento, carga funcional y carga sintomática deben reevaluarse de forma estructurada.",
                required_inputs=symptom_fields,
                capture_fields=symptom_fields,
                completion_rule={"any_of": symptom_fields[:5] or ["pain"]},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["symptom_control", "quality_of_life"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays", "patient_pros"],
                form_scope={"mode": "item_scoped", "focus": "palliative_symptom_control", "capture_fields": symptom_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:opioid_safety_bundle",
                "supportive_care",
                "Seguridad analgésica y opioides",
                state,
                track,
                base_date,
                14,
                priority="high",
                summary="Verifica analgesia basal, dolor irruptivo y prevención de estreñimiento para sostener el alivio sin daño evitable.",
                required_inputs=opioid_fields,
                capture_fields=opioid_fields,
                completion_rule={"any_of": opioid_fields[:4] or ["opioid_use"]},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["symptom_control", "opioid_safety"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": "opioid_safety_bundle", "capture_fields": opioid_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:oncologic_emergency_bundle",
                "supportive_care",
                "Urgencias oncológicas paliativas",
                state,
                track,
                base_date,
                7,
                priority="high",
                summary="Compresión medular, fractura inminente, obstrucción, hematuria severa o crisis visceral deben documentarse y escalarse sin retraso.",
                required_inputs=emergency_fields,
                capture_fields=emergency_fields,
                completion_rule={"any_of": emergency_fields},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["oncologic_emergency", "urgent_local_palliation"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": "oncologic_emergency_bundle", "capture_fields": emergency_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:advance_care_planning_bundle",
                "goals_of_care",
                "Objetivos de cuidado y planeación anticipada",
                state,
                track,
                base_date,
                21,
                priority="high",
                summary="Documenta voluntades anticipadas, representante de salud y preferencia por confort para alinear la conducta visible.",
                required_inputs=goals_fields,
                capture_fields=goals_fields,
                completion_rule={"any_of": goals_fields},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["goals_of_care", "supportive_priority"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": "advance_care_planning_bundle", "capture_fields": goals_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:hospice_readiness_bundle",
                "goals_of_care",
                "Elegibilidad hospice y soporte exclusivo",
                state,
                track,
                base_date,
                14,
                priority="high",
                summary="Evalúa ECOG, pérdida ponderal, albúmina, líneas sistémicas agotadas y preferencia explícita de confort.",
                required_inputs=hospice_fields,
                capture_fields=hospice_fields,
                completion_rule={"any_of": hospice_fields},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["hospice_eligibility", "supportive_only"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": "hospice_readiness_bundle", "capture_fields": hospice_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:palliative_rt_bone_bundle",
                "supportive_care",
                "Paliación local y RT ósea",
                state,
                track,
                base_date,
                14,
                priority="high",
                summary="Alinea dolor óseo, riesgo de fractura o compresión con necesidad de RT paliativa u ortopedia/urología oncológica.",
                required_inputs=rt_bone_fields,
                capture_fields=rt_bone_fields,
                completion_rule={"any_of": rt_bone_fields},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["palliative_rt", "bone_event_risk", "urgent_local_palliation"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "imaging_studies"],
                form_scope={"mode": "item_scoped", "focus": "palliative_rt_bone_bundle", "capture_fields": rt_bone_fields},
            )
        )
        items.append(
            _agenda_item(
                f"{state}:{track}:psychosocial_caregiver_bundle",
                "supportive_care",
                "Soporte psicosocial y cuidador",
                state,
                track,
                base_date,
                21,
                summary="Identifica depresión, ansiedad, insomnio, surrogate y necesidad de soporte familiar/social.",
                required_inputs=caregiver_fields,
                capture_fields=caregiver_fields,
                completion_rule={"any_of": caregiver_fields},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
                decision_targets=["psychosocial_support", "goals_of_care"],
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": "psychosocial_caregiver_bundle", "capture_fields": caregiver_fields},
            )
        )
    return items


def _survivorship_agenda_items(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    transition_bundle = build_survivorship_transition_bundle(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=patient.get("latest_assessment"),
    )
    monitoring_package = build_survivorship_monitoring_package(
        patient,
        state=state,
        management_track=management_track,
        latest_assessment=patient.get("latest_assessment"),
        transition_bundle=transition_bundle,
    )
    if not transition_bundle.get("available"):
        return []

    base_date = _parse_date(_latest_by(patient.get("follow_ups") or [], "visit_date").get("visit_date")) or date.today()
    trigger_status = str(transition_bundle.get("trigger_status") or "observe")
    interval_days = {
        "reenter_oncologic_decision": 21,
        "refer_specialist": 42,
        "refer_rehabilitation": 42,
        "intensify_toxicity_management": 42,
        "monitor_recovery": 90,
        "observe": 180,
    }.get(trigger_status, 90)
    blocks = {
        str(block.get("key") or ""): list(block.get("fields") or [])
        for block in list(transition_bundle.get("late_effect_domain_blocks") or [])
    }

    specs = [
        (
            "post_prostatectomy",
            "urinary_sexual_recovery_bundle",
            "Recuperación urinaria y sexual post-prostatectomía",
            "Secuelas urinarias, pads, IPSS, IIEF-5 y rehabilitación del piso pélvico.",
            ["urinary_recovery", "psychosexual_recovery", "rehabilitation"],
        ),
        (
            "post_radiotherapy",
            "rt_late_toxicity_bundle",
            "Toxicidad tardía post-radioterapia",
            "Cierra toxicidad GU/GI/rectal y secuelas actínicas que hoy pueden dominar la conducta visible.",
            ["late_rt_toxicity", "urologic_toxicity", "gastrointestinal_toxicity"],
        ),
        (
            "adt",
            "adt_cardiometabolic_bone_bundle",
            "Cardiometabólico y hueso bajo ADT",
            "Monitoriza riesgo CV, metabolismo y salud ósea para sostener survivorship y seguridad real.",
            ["cardiometabolic", "bone_health", "secondary_prevention"],
        ),
        (
            "systemic_recovery",
            "systemic_recovery_bundle",
            "Recuperación post-sistémicos",
            "Neuropatía, fatiga, anemia, pérdida ponderal y declive funcional post-taxanos u otros sistémicos.",
            ["toxicity_recovery", "rehabilitation", "functional_recovery"],
        ),
        (
            "bone_agent",
            "bone_agent_safety_bundle",
            "Seguridad de agentes óseos",
            "Clearance dental, ONJ, creatinina y eventos esqueléticos durante denosumab o zoledronato.",
            ["bone_agent_safety", "bone_health"],
        ),
        (
            "psychosocial_sexual",
            "psychosocial_return_to_work_bundle",
            "Psicosocial, sexualidad y retorno al rol",
            "Distress, ansiedad, sexualidad, imagen corporal y retorno a trabajo o rol habitual.",
            ["psychosocial_support", "quality_of_life", "return_to_role"],
        ),
    ]

    items: list[dict[str, Any]] = []
    for block_key, focus_key, title, summary, decision_targets in specs:
        capture_fields = list(blocks.get(block_key) or [])
        if not capture_fields:
            continue
        items.append(
            _agenda_item(
                f"{state}:{management_track}:{focus_key}",
                "supportive_care",
                title,
                state,
                management_track,
                base_date,
                interval_days,
                priority="high" if block_key == transition_bundle.get("dominant_late_effect_domain") else "routine",
                summary=summary,
                required_inputs=capture_fields,
                capture_fields=capture_fields,
                completion_rule={"any_of": capture_fields[:4] or capture_fields},
                evidence_basis=["NCCN 2026 survivorship", "EAU 2026 quality of life / toxicity follow-up"],
                generated_from_event="followup_visit_recorded",
                decision_targets=decision_targets,
                panel_targets=["safety_support_context"],
                write_targets=["follow_up_visits", "stage_visit_records", "patient_pros", "care_overlays"],
                form_scope={"mode": "item_scoped", "focus": focus_key, "capture_fields": capture_fields},
            )
        )

    if items and monitoring_package.get("missing_inputs"):
        items[0].setdefault("blockers", [])
        items[0]["blockers"] = list(
            dict.fromkeys(list(items[0].get("blockers") or []) + list(monitoring_package.get("missing_inputs") or [])[:6])
        )
    return items


def build_agenda_items(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    if state in DIAGNOSTIC_STATES:
        items = _diagnostic_agenda(patient, state, management_track)
    elif state in LOCALIZED_STATES:
        items = _localized_agenda(patient, state, management_track)
    elif state in POSTLOCAL_STATES:
        items = _postlocal_agenda(patient, state, management_track)
    else:
        items = _advanced_agenda(patient, state, management_track)
    items.extend(_survivorship_agenda_items(patient, state, management_track))
    items.extend(_document_agenda_items(patient, state, management_track))
    return sorted(items, key=longitudinal_item_sort_key)


def _document_agenda_items(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    docs = patient.get("source_documents") or []
    verified_types = {
        str(item.get("document_type") or "")
        for item in docs
        if str(item.get("verification_status") or "") == "verified"
    }
    items: list[dict[str, Any]] = []
    base_date = date.today()
    if patient.get("biopsies") and "pathology_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:pathology_source",
                "pathology_review",
                "Falta reporte histopatológico completo",
                state,
                management_track,
                base_date,
                3,
                priority="high",
                summary="La histología estructurada existe, pero falta el reporte fuente verificable para trazabilidad y reestadificación segura.",
                required_inputs=["source_document:pathology_report"],
                completion_rule={"requires_document_type": "pathology_report"},
                evidence_basis=["NCCN 2026", "EAU 2026"],
                generated_from_event="document_missing",
            )
        )
    if state in ADVANCED_STATES and "genomic_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:molecular_source",
                "pathology_review",
                "Falta resultado molecular verificable para PARP / biomarcadores",
                state,
                management_track,
                base_date,
                7,
                priority="high",
                summary="Las rutas PARP, precisión terapéutica y algunos checkpoints avanzados requieren documento molecular verificable.",
                required_inputs=["source_document:genomic_report"],
                completion_rule={"requires_document_type": "genomic_report"},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                generated_from_event="document_missing",
            )
        )
    advanced_psma_context = state in ADVANCED_STATES or management_track == "salvage"
    psma_imaging_exists = any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or []))
    if advanced_psma_context and psma_imaging_exists and "imaging_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:psma_source",
                "imaging",
                "Falta informe PSMA-PET verificable",
                state,
                management_track,
                base_date,
                7,
                priority="high",
                summary="La elegibilidad a rutas PSMA dirigidas y algunas decisiones de rescate requieren informe fuente verificable.",
                required_inputs=["source_document:imaging_report"],
                completion_rule={"requires_document_type": "imaging_report"},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                generated_from_event="document_missing",
            )
        )
    return items


def build_therapy_checkpoints(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    longitudinal_bundle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    baseline = patient.get("baseline") or {}
    genomics = patient.get("genomics") or {}
    followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    runtime_bundle = dict(longitudinal_bundle or {})
    truth_values = (
        (runtime_bundle.get("longitudinal_truth_snapshot") or {}).get("field_values")
        or ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    )
    latest_signal_snapshot = dict(runtime_bundle.get("signals") or patient.get("latest_signal_snapshot") or {})
    latest_assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    post_rt_snapshot_bundle = dict(
        runtime_bundle.get("post_rt_salvage_bundle")
        or patient.get("post_rt_salvage_bundle")
        or latest_signal_snapshot.get("post_rt_salvage_bundle")
        or {}
    )
    post_rt_failure_definition = dict(
        post_rt_snapshot_bundle.get("post_rt_failure_definition")
        or {}
    )
    post_rt_transition_bundle = dict(
        post_rt_snapshot_bundle.get("post_rt_transition_bundle")
        or {}
    )
    post_rt_restaging_strategy = dict(post_rt_snapshot_bundle.get("restaging_strategy") or {})
    post_rt_local_pathway = dict(post_rt_snapshot_bundle.get("local_salvage_pathway") or {})
    treatment_text = _treatment_text(patient).lower()
    checkpoints: list[dict[str, Any]] = []
    if state == "localized_initial":
        genomics_ready = any(_is_present(genomics.get(key)) for key in ("decipher_risk", "prolaris_score", "gps_score"))
        checkpoints.append(
            TherapyCheckpoint(
                key="shared_decision_local",
                title="Decisión local y shared decision making",
                status="ready" if _is_present(followup.get("psa_current")) or patient.get("baseline", {}).get("baseline_psa") else "needs_data",
                rationale="PI-RADS, patología, PROs y algoritmos prequirúrgicos deben alinearse antes de fijar cirugía, RT o vigilancia.",
                action="Completar PROs y revisar panel de algoritmos contextuales.",
                evidence_basis=["NCCN 2026", "EAU 2026 localized"],
                decision_supported="Elección entre vigilancia activa, cirugía o radioterapia.",
                why_it_matters_now="La decisión local cambia la trayectoria completa del paciente y requiere inputs anatómicos y funcionales consistentes.",
                inputs_required=["psa", "pirads_score", "ipss_total", "iief5_score"],
                blocking_if_missing=True,
                last_input_source="follow_up_visits" if _is_present(followup.get("psa_current")) else "",
                last_input_date=followup.get("visit_date", ""),
                changes_recommendation_if_resolved=True,
            ).to_dict()
        )
        checkpoints.append(
            TherapyCheckpoint(
                key="genomic_localized",
                title="Firma tisular documentada",
                status="available" if genomics_ready else "optional",
                rationale="Decipher / Oncotype / Prolaris refinan casos limítrofes, pero no sustituyen la guía.",
                action="Persistir resultado externo si ya existe.",
                evidence_basis=["NCCN 2026", "EAU 2026 localized"],
                decision_supported="Refinar riesgo local en casos limítrofes.",
                why_it_matters_now="Puede reforzar o debilitar la preferencia por vigilancia activa o tratamiento local.",
                inputs_required=["genomic_classifier", "genomic_classifier_result"],
                blocking_if_missing=False,
                last_input_source="genomic_profile" if genomics_ready else "",
                last_input_date=genomics.get("test_date", ""),
                changes_recommendation_if_resolved=False,
            ).to_dict()
        )
        return checkpoints
    if state == "post_radiotherapy_or_local_salvage":
        post_rt_status = str(
            post_rt_transition_bundle.get("transition_status")
            or post_rt_snapshot_bundle.get("post_rt_salvage_window_status")
            or ""
        ).strip()
        failure_basis = str(post_rt_failure_definition.get("failure_confirmation_basis") or "").strip()
        phoenix_ready = (
            post_rt_status in {"local_salvage_candidate", "mdt_candidate", "redirect_systemic"}
            or str(post_rt_failure_definition.get("phoenix_status") or "").strip() == "met"
            or failure_basis in {"phoenix", "biopsy_proven_local_failure", "radiographic_local_failure"}
            or _is_present(truth_values.get("phoenix_delta"))
            or (
                _is_present(truth_values.get("psa_current"))
                and _is_present(truth_values.get("psa_nadir"))
            )
            or _is_present(followup.get("phoenix_delta"))
            or (
                _is_present(followup.get("psa_current"))
                and _is_present(followup.get("psa_nadir"))
            )
        )
        psma_ready = (
            post_rt_status in {"local_salvage_candidate", "mdt_candidate", "redirect_systemic"}
            or bool(post_rt_restaging_strategy.get("structured_complete"))
            or _is_present(truth_values.get("psma_pet_done"))
            or _is_present(followup.get("psma_pet_done"))
            or _is_present(latest_assessment_inputs.get("psma_pet_done"))
        )
        local_matrix_ready = (
            post_rt_status in {"local_salvage_candidate", "mdt_candidate", "redirect_systemic"}
            or bool(post_rt_local_pathway.get("dominant_local_option"))
            or bool(post_rt_local_pathway.get("ranking"))
            or _is_present(truth_values.get("urinary_burden"))
            or _is_present(followup.get("urinary_burden"))
            or _is_present(baseline.get("urinary_burden"))
        )
        checkpoint_source = (
            "longitudinal_runtime"
            if post_rt_status in {"local_salvage_candidate", "mdt_candidate", "redirect_systemic"}
            else "follow_up_visits" if phoenix_ready or psma_ready or local_matrix_ready else ""
        )
        checkpoint_date = (
            str(
                (runtime_bundle.get("latest_clinically_decisive_visit") or {}).get("visit_date")
                or (patient.get("latest_clinically_decisive_visit") or {}).get("visit_date")
                or ""
            )
            or followup.get("visit_date", "")
        )
        checkpoints.extend(
            [
                TherapyCheckpoint(
                    key="post_rt_failure_gate",
                    title="Confirmación de fallo post-RT",
                    status="ready" if phoenix_ready else "needs_data",
                    rationale="Phoenix o una confirmación local equivalente deben cerrarse antes de abrir salvage curativo post-RT.",
                    action="Actualizar PSA actual, nadir y confirmar falla local por biopsia/mpMRI cuando corresponda.",
                    evidence_basis=["NCCN 2026", "EAU 2026 recurrencia"],
                    decision_supported="Abrir o bloquear salvage local post-RT.",
                    why_it_matters_now="Sin Phoenix o confirmación local equivalente la conducta debe quedarse en confirmación/reestadificación, no en salvage definitivo.",
                    inputs_required=["psa_current", "psa_nadir", "phoenix_delta", "biopsy_proven_local_recurrence", "mpmri_localized_recurrence"],
                    blocking_if_missing=True,
                    last_input_source=checkpoint_source if phoenix_ready else "",
                    last_input_date=checkpoint_date if phoenix_ready else "",
                    changes_recommendation_if_resolved=True,
                ).to_dict(),
                TherapyCheckpoint(
                    key="post_rt_restaging_gate",
                    title="Reestadificación post-RT",
                    status="ready" if psma_ready else "needs_data",
                    rationale="La PSMA estructurada distingue salvage glandular puro, MDT oligorrecurrente y redirección sistémica.",
                    action="Completar PSMA estructurada y correlación con mpMRI.",
                    evidence_basis=["NCCN 2026", "EAU 2026 recurrencia"],
                    decision_supported="MDT vs salvage local vs redirección sistémica.",
                    why_it_matters_now="Una PSMA diseminada u oligorrecurrente cambia por completo la ruta post-RT.",
                    inputs_required=["psma_pet_done", "psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_stage_after_psma"],
                    blocking_if_missing=True,
                    last_input_source=checkpoint_source if psma_ready else "",
                    last_input_date=checkpoint_date if psma_ready else "",
                    changes_recommendation_if_resolved=True,
                ).to_dict(),
                TherapyCheckpoint(
                    key="post_rt_local_modality_matrix",
                    title="Matriz de modalidad local",
                    status="ready" if local_matrix_ready else "needs_data",
                    rationale="La modalidad local preferente depende de toxicidad GU/GI previa, volumen prostático, aptitud anestésica y expertise disponible.",
                    action="Completar carga urinaria/intestinal, volumen prostático, aptitud anestésica y expertise local.",
                    evidence_basis=["NCCN 2026", "EAU 2026 recurrencia"],
                    decision_supported="Elegir prostatectomy vs cryotherapy vs HIFU vs brachytherapy de rescate.",
                    why_it_matters_now="Una sola casilla de salvage feasible no es suficiente para escoger la mejor modalidad local post-RT.",
                    inputs_required=["prior_rt_modality", "prior_rt_dose", "prior_rt_fields", "local_recurrence_site", "urinary_burden", "incontinence_burden", "urethral_stricture_history", "bowel_burden", "rectal_toxicity_grade", "prostate_volume", "anesthesia_surgical_fitness", "salvage_expertise_available"],
                    blocking_if_missing=True,
                    last_input_source=checkpoint_source if local_matrix_ready else "",
                    last_input_date=checkpoint_date if local_matrix_ready else "",
                    changes_recommendation_if_resolved=True,
                ).to_dict(),
            ]
        )
        return checkpoints
    if state in {"post_prostatectomy", "recurrence_bcr"}:
        psa_present = _is_present(followup.get("psa_current"))
        checkpoints.append(
            TherapyCheckpoint(
                key="salvage_gate",
                title="Gate de rescate",
                status="ready" if psa_present else "needs_data",
                rationale="PSA ultrasensible, PSADT, márgenes, Decipher e imagen definen la oportunidad de rescate.",
                action="Actualizar PSA e imagen si la trayectoria clínica cambió.",
                evidence_basis=["NCCN 2026", "EAU 2026 recurrencia", "GETUG-AFU 16", "RTOG 9601", "SPPORT", "EMPIRE-1"],
                decision_supported="Ventana de rescate y necesidad de intensificación.",
                why_it_matters_now="La oportunidad de rescate puede perderse si PSA cinético e imagen no están actualizados.",
                inputs_required=["psa", "imaging_modality"],
                blocking_if_missing=True,
                last_input_source="follow_up_visits" if psa_present else "",
                last_input_date=followup.get("visit_date", ""),
                changes_recommendation_if_resolved=True,
            ).to_dict()
        )
        return checkpoints
    if state in ADVANCED_STATES:
        hrr_ready = any(_is_present(genomics.get(key)) for key in ("hrr_overall", "brca2_status", "atm_status"))
        psma_ready = any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or []))
        arpi_safety_ready = all(
            _is_present(followup.get(key))
            for key in ("mini_cog_score", "fatigue_score", "cv_risk_documented", "ddi_review_status")
        )
        checkpoints.extend(
            [
                TherapyCheckpoint(
                    key="biomarker_gate",
                    title="Biomarcadores accionables",
                    status="ready" if hrr_ready else "needs_data",
                    rationale="HRR/BRCA, MSI/TMB y trazabilidad molecular ordenan PARP e inmunoterapia.",
                    action="Documentar fuente y fecha molecular antes de intensificar.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "35.pdf"],
                    decision_supported="PARP, inmunoterapia y pathway de precisión.",
                    why_it_matters_now="Sin biomarcador verificable no debe intensificarse hacia rutas de precisión.",
                    inputs_required=["hrr_status", "hrr_gene", "msi_status", "biomarker_source", "molecular_assay_date"],
                    blocking_if_missing=True,
                    last_input_source="genomic_profile" if hrr_ready else "",
                    last_input_date=genomics.get("test_date", ""),
                    changes_recommendation_if_resolved=True,
                ).to_dict(),
                TherapyCheckpoint(
                    key="psma_gate",
                    title="Elegibilidad PSMA / Lutecio",
                    status="ready" if psma_ready else "needs_data",
                    rationale="Lutecio y rutas PSMA requieren imagen estructurada y descarte de lesiones dominantes PSMA negativas.",
                    action="Registrar PSMA-PET estructurado si la decisión terapéutica depende de ello.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "34.pdf"],
                    decision_supported="Elegibilidad a terapias dirigidas a PSMA / Lu-177.",
                    why_it_matters_now="La elegibilidad PSMA no puede sostenerse con texto libre o inferencias blandas.",
                    inputs_required=["psma_positive", "psma_negative_dominant_lesions", "imaging_modality"],
                    blocking_if_missing=True,
                    last_input_source="imaging_studies" if psma_ready else "",
                    last_input_date=_latest_by(patient.get("imaging", []), "study_date").get("study_date", ""),
                    changes_recommendation_if_resolved=True,
                ).to_dict(),
                TherapyCheckpoint(
                    key="arpi_safety",
                    title="Seguridad ARPI",
                    status="ready" if management_track != "on_arpi" or arpi_safety_ready else "needs_data",
                    rationale="Convulsiones, cognición, rash, CV, interacciones y riesgo hepático cambian el ARPI más seguro.",
                    action="Completar bundle de seguridad específico cuando el paciente use o sea candidato a ARPI.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
                    decision_supported="Selección o continuación segura de ARPI.",
                    why_it_matters_now="La toxicidad prevenible puede obligar suspensión o selección equivocada del agente.",
                    inputs_required=["mini_cog_score", "fatigue_score", "cv_risk_documented", "ddi_review_status"],
                    blocking_if_missing=management_track == "on_arpi",
                    last_input_source="follow_up_visits" if arpi_safety_ready else "",
                    last_input_date=followup.get("visit_date", ""),
                    changes_recommendation_if_resolved=management_track == "on_arpi",
                ).to_dict(),
            ]
        )
        if "docetaxel" in treatment_text and _safe_float(followup.get("hemoglobin_current")) is None:
            checkpoints.append(
                TherapyCheckpoint(
                    key="docetaxel_cbc",
                    title="Toxicidad hematológica en docetaxel",
                    status="needs_data",
                    rationale="CBC y estado funcional deben mantenerse vigentes en quimioterapia activa.",
                    action="Agregar laboratorio y ECOG en la siguiente visita.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                    decision_supported="Continuidad segura de docetaxel.",
                    why_it_matters_now="La toxicidad hematológica no monitorizada puede volver insegura la continuación del ciclo.",
                    inputs_required=["hemoglobin", "ecog"],
                    blocking_if_missing=True,
                    last_input_source="follow_up_visits",
                    last_input_date=followup.get("visit_date", ""),
                    changes_recommendation_if_resolved=True,
                ).to_dict()
            )
    return checkpoints


def build_agenda_board(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    raw_assessment: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = build_agenda_items(patient, state, management_track)
    overdue = [item for item in items if item.get("status") == "overdue"]
    due = [item for item in items if item.get("status") in {"due", "due_today"}]
    protocol = build_stage_protocol(state, management_track, patient)
    therapy_checkpoints = build_therapy_checkpoints(
        patient,
        state,
        management_track,
        longitudinal_bundle=longitudinal_bundle,
    )
    protocol_trace = build_protocol_trace(patient, state, management_track, raw_assessment)
    board = {
        "state": state,
        "management_track": management_track,
        "management_track_label": MANAGEMENT_TRACK_LABELS.get(management_track, management_track),
        "stage_protocol": protocol,
        "protocol_trace": protocol_trace,
        "items": items,
        "active_items": items,
        "archived_items": [],
        "next_due_items": due[:4],
        "overdue_items": overdue[:4],
        "active_recommendations": [item for item in items if item.get("status") in {"due", "due_today", "overdue"}][:5],
        "therapy_checkpoints": therapy_checkpoints,
        "protocol_comparators": build_protocol_comparators(state, management_track),
        "visit_schema": build_visit_schema(state, management_track),
    }
    return enrich_agenda_board_with_encounters(board, state, management_track)
