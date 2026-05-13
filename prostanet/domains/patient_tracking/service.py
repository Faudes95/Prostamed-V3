from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from tracking_db import get_patient_full_record

from prostanet.domains.patient_tracking.followup_agenda import (
    LINE_OF_THERAPY_CONTEXT_OPTIONS,
    LINE_OF_THERAPY_NUMBER_OPTIONS,
)
from prostanet.domains.patient_tracking.laboratory_intelligence.repository import (
    lab_reference_range,
)
from prostanet.domains.patient_tracking.risk_tools import build_intake_score_requirements
from prostanet.domains.patient_tracking.therapy_catalog import (
    normalize_regimen_code,
    therapy_catalog_entries,
    therapy_select_options,
)
from prostanet.shared.official_diagnosis import (
    CLINICAL_RISK_GROUP_OPTIONS,
    CLINICAL_STAGE_GROUP_OPTIONS,
    CLINICAL_TSTAGE_OPTIONS,
    HISTOLOGY_SUBTYPE_OPTIONS,
    NODAL_STATUS_OPTIONS,
)
from prostanet.shared.contracts import FieldSpec, RegistrationFragment
from prostanet.shared.advanced_support_catalog import MINI_COG_OPTIONS
from prostanet.shared.field_semantics import (
    CAPTURE_LAYER_METADATA,
    build_score_semantics,
    field_capture_layer,
    field_reuse_key,
    field_scale_semantics,
    field_semantics_for,
    field_when_to_ask,
)
from prostanet.shared.gleason_profile import apply_gleason_profile, normalize_gleason_profile
from prostanet.shared.metastatic_profile import (
    BONE_SITE_LABELS,
    NONREGIONAL_NODAL_SITE_LABELS,
    VISCERAL_SITE_LABELS,
    AXIAL_BONE_SITE_KEYS,
    APPENDICULAR_BONE_SITE_KEYS,
    build_metastatic_composition_summary,
)


def _docetaxel_visibility() -> dict[str, list[str]]:
    return {
        "ecog_score": ["", "0", "1", "2"],
        "peripheral_neuropathy_grade": ["", "0", "1", "2"],
        "frailty_status": ["", "Fit", "Vulnerable"],
        "child_pugh_score": ["", "A", "B"],
    }


STATE_SCOPE_MAP = {
    "diagnostic_workup": "diagnostic",
    "post_negative_biopsy_followup": "diagnostic",
    "localized_initial": "localized",
    "post_prostatectomy": "postlocal",
    "recurrence_bcr": "postlocal",
    "post_radiotherapy_or_local_salvage": "postlocal",
    "adt_progression_verification": "advanced",
    "mcspc_oligo_metachronous": "advanced",
    "mcspc_low_volume_sync_oligo": "advanced",
    "mcspc_high_volume_sync": "advanced",
    "mcspc_high_volume_metachronous": "advanced",
    "mcspc_high_volume": "advanced",
    "m0_crpc": "advanced",
    "m1_crpc": "advanced",
}

SCOPE_CONFIG = {
    "diagnostic": {
        "label": "Ruta diagnóstica / biopsia benigna previa",
        "description": "El wizard ya captura la sospecha clínica central. Aquí se agregan identidad, línea basal y longitudinal para persistir sin inventar tratamiento sistémico.",
        "bullets": [
            "Los datos clínicos del asistente se importan y persisten desde la evaluación modular.",
            "No se solicita línea terapéutica ni esquema sistémico.",
            "Se agregan identidad, laboratorios basales, síntomas y cohorte opcional.",
        ],
    },
    "localized": {
        "label": "Ruta localizada inicial",
        "description": "La evaluación modular ya resolvió riesgo, vigilancia activa y refinadores locales. Esta fase completa el longitudinal y los PROs basales.",
        "bullets": [
            "Se preservan los datos clínicos del asistente para seguimiento y benchmarking.",
            "Se suman identidad, PROs funcionales y cohorte opcional.",
            "No se habilita tratamiento sistémico por defecto.",
        ],
    },
    "postlocal": {
        "label": "Ruta poslocal / recurrencia bioquímica",
        "description": "El wizard ya capturó rescate, PSA ultrasensible e imagen. Esta fase completa identidad, historial previo y longitudinal de rescate.",
        "bullets": [
            "Los disparadores de rescate y recurrencia viajan desde la evaluación modular.",
            "Se agrega historia terapéutica previa y cohorte opcional.",
            "Solo se habilita tratamiento sistémico si el estado clínico realmente lo requiere.",
        ],
    },
    "advanced": {
        "label": "Ruta avanzada",
        "description": "El wizard ya capturó biomarcadores, seguridad y secuencia. Esta fase completa identidad, tratamiento longitudinal y cohorte opcional.",
        "bullets": [
            "Los biomarcadores y warnings del asistente se importan y persisten.",
            "Se habilita el bloque de tratamiento e historial terapéutico.",
            "La captura adicional alimenta dashboard, perfil y benchmarking operativo.",
        ],
    },
}

CANONICAL_FIELD_MAP = {
    "comorb_seizure": "comorbidity_seizure",
    "comorb_cardio": "comorbidity_cardio",
    "line_of_therapy": "line_of_therapy_number",
    "molecular_report_date": "molecular_assay_date",
    "molecular_assay_source": "biomarker_source",
    "castrate_testosterone_confirmed": "castrate_testosterone_status",
    "positive_cores": "num_cores_positive",
    "psa_baseline_ng_ml": "baseline_psa",
}

CANONICAL_VALUE_MAPS = {
    "metastasis_site": {
        "Hueso": "Bone",
        "Ganglio": "Node",
        "Óseo": "Bone",
        "Oseo": "Bone",
        "Sin metástasis a distancia (M0)": "M0",
    },
    "pain_symptoms": {
        "Moderado-Severo": "Sintomatico",
        "Moderado/Severo": "Sintomatico",
    },
    "msi_status": {
        "Estable": "estable",
        "Inestable": "inestable",
        "MSS": "estable",
        "MSI-H": "inestable",
    },
}


def _field(name: str, label: str, field_type: str, **kwargs) -> FieldSpec:
    semantics = field_semantics_for(name)
    reference_range = lab_reference_range(name)
    payload = dict(kwargs)
    if reference_range:
        payload.setdefault("reference_range_low", reference_range.get("reference_range_low"))
        payload.setdefault("reference_range_high", reference_range.get("reference_range_high"))
        payload.setdefault("reference_range_unit", reference_range.get("reference_range_unit"))
        payload.setdefault("reference_range_label", reference_range.get("reference_range_label"))
        payload.setdefault("reference_range_source", reference_range.get("reference_range_source"))
    return FieldSpec(
        name=name,
        label=label,
        field_type=field_type,
        reuse_key=payload.pop("reuse_key", semantics["reuse_key"]),
        capture_layer=payload.pop("capture_layer", semantics["capture_layer"]),
        when_to_ask=payload.pop("when_to_ask", semantics["when_to_ask"]),
        scale_descriptor=payload.pop("scale_descriptor", semantics["scale_descriptor"]),
        score_interpretation=payload.pop("score_interpretation", semantics["score_interpretation"]),
        **payload,
    )


def _fragment(
    *,
    capture_layer: str,
    when_to_ask: str,
    collapsed_by_default: bool = False,
    **kwargs,
) -> RegistrationFragment:
    return RegistrationFragment(
        capture_layer=capture_layer,
        when_to_ask=when_to_ask,
        collapsed_by_default=collapsed_by_default,
        **kwargs,
    )


def _layer_label(layer: str) -> str:
    return CAPTURE_LAYER_METADATA.get(layer, {}).get("label", layer)


def _apply_fragment_semantics(fragment: RegistrationFragment) -> RegistrationFragment:
    enriched_fields: list[FieldSpec] = []
    for field in fragment.fields:
        semantics = field_semantics_for(field.name, optional_research=fragment.optional_research)
        scale_semantics = field_scale_semantics(field.name)
        enriched_fields.append(
            replace(
                field,
                reuse_key=field.reuse_key or semantics["reuse_key"],
                capture_layer=field.capture_layer or semantics["capture_layer"],
                when_to_ask=field.when_to_ask or semantics["when_to_ask"] or fragment.when_to_ask,
                scale_descriptor=field.scale_descriptor or scale_semantics.get("scale_descriptor", ""),
                score_interpretation=field.score_interpretation or scale_semantics.get("score_interpretation", ""),
            )
        )
    return replace(
        fragment,
        capture_layer=fragment.capture_layer or field_capture_layer("", optional_research=fragment.optional_research),
        when_to_ask=fragment.when_to_ask,
        collapsed_by_default=fragment.collapsed_by_default or fragment.optional_research,
        fields=enriched_fields,
    )


def _build_capture_layers(fragments: list[RegistrationFragment]) -> list[dict[str, Any]]:
    ordered_layers = ["core_minimum", "scenario_refiners", "safety_eligibility", "research_optional"]
    sections: list[dict[str, Any]] = []
    for layer in ordered_layers:
        layer_fragments = [fragment for fragment in fragments if fragment.capture_layer == layer]
        if not layer_fragments:
            continue
        layer_meta = CAPTURE_LAYER_METADATA.get(layer, {})
        sections.append(
            {
                "id": layer,
                "label": layer_meta.get("label", layer),
                "description": layer_meta.get("description", ""),
                "collapsed_by_default": layer == "research_optional",
                "fragment_ids": [fragment.id for fragment in layer_fragments],
            }
        )
    return sections


def _dedupe_registration_fragments(
    fragments: list[RegistrationFragment],
    imported_fields: list[dict[str, Any]],
) -> tuple[list[RegistrationFragment], list[dict[str, Any]]]:
    seen_keys = {field_reuse_key(item.get("reuse_key") or item.get("name", "")) for item in imported_fields}
    deduped_fragments: list[RegistrationFragment] = []
    visible_fields: list[dict[str, Any]] = []

    for fragment in fragments:
        kept_fields: list[FieldSpec] = []
        for field in fragment.fields:
            reuse_key = field.reuse_key or field.name
            if reuse_key in seen_keys:
                continue
            seen_keys.add(reuse_key)
            kept_fields.append(field)
            visible_fields.append(
                {
                    "name": field.name,
                    "label": field.label,
                    "reuse_key": reuse_key,
                    "capture_layer": field.capture_layer,
                    "capture_layer_label": _layer_label(field.capture_layer),
                    "clinical_role": field.clinical_role,
                }
            )
        if kept_fields or fragment.optional_research:
            deduped_fragments.append(replace(fragment, fields=kept_fields))
    return deduped_fragments, visible_fields


def _filter_score_requirements_for_visible_fields(
    score_requirements: dict[str, Any],
    *,
    visible_fields: list[dict[str, Any]],
    imported_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    visible_names = {field.get("name") for field in visible_fields}
    visible_reuse_keys = {field.get("reuse_key") for field in visible_fields}
    imported_names = {field.get("name") for field in imported_fields}
    imported_reuse_keys = {field.get("reuse_key") for field in imported_fields}
    filtered_missing: list[dict[str, Any]] = []
    for item in score_requirements.get("score_missing_inputs", []):
        reuse_key = field_reuse_key(item.get("name", ""))
        if item.get("name") in visible_names or item.get("name") in imported_names:
            continue
        if reuse_key in visible_reuse_keys or reuse_key in imported_reuse_keys:
            continue
        filtered_missing.append(item)
    filtered = deepcopy(score_requirements)
    filtered["score_missing_inputs"] = filtered_missing
    return filtered


def _field_semantics_registry(
    *,
    fragments: list[RegistrationFragment],
    imported_fields: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    semantics: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        for field in fragment.fields:
            semantics[field.name] = field_semantics_for(field.name, optional_research=fragment.optional_research)
    for item in imported_fields:
        semantics[item["name"]] = field_semantics_for(item["name"])
    return semantics


def _metastatic_intake_fields() -> list[FieldSpec]:
    bone_site_groups = [
        {
            "label": "Esqueleto axial",
            "options": [
                {"site_key": key, "label": BONE_SITE_LABELS[key]}
                for key in AXIAL_BONE_SITE_KEYS
                if key in BONE_SITE_LABELS
            ],
        },
        {
            "label": "Esqueleto apendicular",
            "options": [
                {"site_key": key, "label": BONE_SITE_LABELS[key]}
                for key in APPENDICULAR_BONE_SITE_KEYS
                if key in BONE_SITE_LABELS
            ],
        },
    ]
    return [
        _field(
            "metastatic_components_capture",
            "Carga metastásica estructurada",
            "metastatic_components",
            group="Distribución metastásica",
            group_order=4,
            clinical_role="decision_refiner",
            help_text="Reutilice la composición anatómica metastásica ya capturada; si el contexto ya está completo, solo verifique o ajuste el delta documentado.",
            options=[
                {
                    "bone_site_groups": bone_site_groups,
                    "visceral_site_options": [
                        {"site_key": key, "label": label}
                        for key, label in VISCERAL_SITE_LABELS.items()
                    ],
                    "nonregional_nodal_site_options": [
                        {"site_key": key, "label": label}
                        for key, label in NONREGIONAL_NODAL_SITE_LABELS.items()
                    ],
                }
            ],
        ),
        _field("metastasis_assessment_date", "Fecha de evaluación metastásica", "date", group="Distribución metastásica", group_order=4, clinical_role="decision_refiner"),
        _field("metastasis_document_source", "Fuente documental de la distribución metastásica", "text", group="Distribución metastásica", group_order=4, clinical_role="decision_refiner"),
    ]


def _common_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_common_identity_baseline",
        title="Identidad, laboratorios y línea basal",
        capture_layer="core_minimum",
        when_to_ask="Siempre que falten identidad, basal clínico o una serie inicial de APE que cambie la lectura longitudinal.",
        applies_to_states=list(STATE_SCOPE_MAP.keys()),
        persist_targets=["patient_identity", "clinical_baseline"],
        clinical_influence=[
            "Sostiene el longitudinal basal y evita gaps al abrir el perfil del paciente.",
            "La línea basal viaja a analítica, alertas y seguimiento.",
        ],
        fields=[
            _field("full_name", "Nombre completo", "text", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("nss", "Número de seguridad social", "text", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("dob", "Fecha de nacimiento", "date", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("ecog_score", "ECOG basal", "select", options=["", "0", "1", "2", "3", "4"], group="Línea basal clínica", group_order=2, clinical_role="decision_refiner"),
            _field("frailty_status", "Fragilidad basal", "select", options=["", "Fit", "Vulnerable", "Frail"], group="Línea basal clínica", group_order=2, clinical_role="decision_refiner"),
            _field("tobacco_use", "Tabaquismo", "select", options=["", "Nunca", "Exfumador", "Activo"], group="Línea basal clínica", group_order=2, clinical_role="decision_refiner"),
            _field("exercise_status", "Actividad física basal", "select", options=["", "No realiza", "Ligera", "Moderada", "Intensa"], group="Línea basal clínica", group_order=2, clinical_role="decision_refiner"),
            _field("baseline_psa", "Antígeno prostático específico basal (PSA)", "number", group="Laboratorio basal", group_order=2, clinical_role="required", unit="ng/mL"),
            _field(
                "psa_history",
                "Serie longitudinal de APE disponible",
                "psa_history",
                group="Laboratorio basal",
                group_order=2,
                clinical_role="decision_refiner",
                help_text="Agregue cero o más mediciones históricas de APE/PSA si ya existen; el sistema conservará el basal canónico y guardará la serie longitudinal.",
            ),
            _field("testosterone_baseline", "Testosterona basal", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="ng/dL"),
            _field(
                "testosterone_history",
                "Serie longitudinal de testosterona disponible",
                "testosterone_history",
                group="Laboratorio basal",
                group_order=2,
                clinical_role="decision_refiner",
                help_text="Agregue cero o más mediciones históricas de testosterona si ya existen; el sistema conservará el basal canónico y usará la serie para resolver castración y lógica CRPC.",
            ),
            _field("hemoglobin", "Hemoglobina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="g/dL"),
            _field("alp", "Fosfatasa alcalina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="UI/L"),
            _field("ldh", "Lactato deshidrogenasa", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="UI/L"),
            _field("albumin", "Albúmina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="g/dL"),
            _field("dxa_baseline_done", "DXA basal realizada", "select", options=["0", "1"], default="0", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner"),
            _field("weight_kg", "Peso actual", "number", group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner", unit="kg"),
            _field("height_cm", "Estatura actual", "number", group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner", unit="cm"),
            _field("bmi_current", "Índice de masa corporal actual", "number", group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner", unit="kg/m²"),
            _field("weight_loss_6m_kg", "Pérdida de peso en 6 meses", "number", group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner", unit="kg"),
            _field("mini_cog_score", "Mini-Cog basal", "select", options=MINI_COG_OPTIONS, group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("fatigue_score", "Fatiga basal", "number", group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_food_intake", "G8: ingesta de alimentos", "select", options=["", "0", "1", "2"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_weight_loss", "G8: pérdida de peso", "select", options=["", "0", "1", "2", "3"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_mobility", "G8: movilidad", "select", options=["", "0", "1", "2"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_neuropsych", "G8: estado neuropsicológico", "select", options=["", "0", "1", "2"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_bmi", "G8: categoría BMI", "select", options=["", "0", "1", "2", "3"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_medications", "G8: medicamentos diarios", "select", options=["", "0", "1"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("g8_self_health", "G8: percepción de salud", "select", options=["", "0", "0.5", "1", "2"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("low_activity", "Actividad física reducida", "select", options=["", "0", "1"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field("slow_gait", "Marcha lenta", "select", options=["", "0", "1"], group="Fragilidad y fitness", group_order=3, clinical_role="decision_refiner"),
            _field(
                "weak_grip",
                "Fuerza de prensión baja",
                "select",
                options=["", "0", "1"],
                group="Fragilidad y fitness",
                group_order=3,
                clinical_role="decision_refiner",
                help_text="Alimenta el índice de fragilidad de Fried y la lectura de fitness terapéutico.",
            ),
        ],
    )


def _official_diagnosis_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_official_diagnosis",
        title="Diagnóstico oficial y clasificación oncológica",
        capture_layer="core_minimum",
        when_to_ask="Siempre que falte el diagnóstico oncológico formal visible en perfil y analítica.",
        applies_to_states=list(STATE_SCOPE_MAP.keys()),
        persist_targets=["clinical_baseline", "biopsy_details"],
        clinical_influence=[
            "Permite componer el diagnóstico oficial visible del perfil en lugar de usar solo el nombre del módulo clínico.",
            "Los faltantes se pueden completar después desde visita o verificación documental sin romper el flujo inicial.",
        ],
        fields=[
            _field("histology_subtype", "Subtipo histológico", "select", options=HISTOLOGY_SUBTYPE_OPTIONS, group="Diagnóstico oficial", group_order=1, clinical_role="required"),
            _field(
                "gleason_score",
                "Perfil Gleason / ISUP",
                "gleason_profile",
                group="Diagnóstico oficial",
                group_order=1,
                clinical_role="required",
                help_text="Capture Gleason primario, secundario y patrón terciario si existe. El sistema deriva automáticamente Gleason total e ISUP y los integra al diagnóstico principal.",
            ),
            _field("clinical_tstage", "T clínico", "select", options=CLINICAL_TSTAGE_OPTIONS, group="TNM clínico", group_order=2, clinical_role="required"),
            _field("nodal_status", "N clínico", "select", options=NODAL_STATUS_OPTIONS, group="TNM clínico", group_order=2, clinical_role="required"),
            _field("clinical_stage_group", "Etapa clínica", "select", options=CLINICAL_STAGE_GROUP_OPTIONS, group="TNM clínico", group_order=2, clinical_role="decision_refiner"),
            _field("clinical_risk_group", "Grupo de riesgo clínico", "select", options=CLINICAL_RISK_GROUP_OPTIONS, group="TNM clínico", group_order=2, clinical_role="decision_refiner"),
        ],
    )


def _diagnostic_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_diagnostic",
        title="Síntomas y antecedentes familiares longitudinales",
        capture_layer="scenario_refiners",
        when_to_ask="Solo en ruta diagnóstica o biopsia benigna previa cuando refine riesgo o rebiopsia.",
        applies_to_states=["diagnostic_workup", "post_negative_biopsy_followup"],
        persist_targets=["patient_demographics", "family_history_detail"],
        clinical_influence=[
            "Completa la línea basal sintomática y la trazabilidad familiar.",
            "Ayuda a seguimiento diagnóstico y benchmarking de rebiopsia.",
        ],
        fields=[
            _field("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", group="Síntomas basales", group_order=1, clinical_role="monitoring", unit="0-35"),
            _field("family_history_detail", "Detalle estructurado de historia familiar", "text", group="Riesgo hereditario", group_order=2, clinical_role="decision_refiner", help_text="Ej. Padre con cáncer de próstata a los 64 años; BRCA2 en hermana."),
        ],
    )


def _localized_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_localized",
        title="PROs y función basal",
        capture_layer="scenario_refiners",
        when_to_ask="Solo en enfermedad localizada cuando la función basal cambia la conversación entre vigilancia activa, cirugía o radioterapia.",
        applies_to_states=["localized_initial"],
        persist_targets=["patient_demographics", "patient_pros"],
        clinical_influence=[
            "Permite comparar vigilancia activa, cirugía y radioterapia con resultados funcionales basales.",
            "Alimenta el longitudinal de PROs desde el ingreso.",
        ],
        fields=[
            _field("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", group="PROs basales", group_order=1, clinical_role="monitoring", unit="0-35"),
            _field("iief5_score", "Índice internacional de función eréctil de 5 preguntas (IIEF-5)", "number", group="PROs basales", group_order=1, clinical_role="monitoring", unit="5-25"),
        ],
    )


def _postlocal_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_postlocal",
        title="Contexto de imagen y rescate longitudinal",
        capture_layer="scenario_refiners",
        when_to_ask="Solo en contexto poslocal o de recurrencia bioquímica cuando cambia rescate, reestadificación o vigilancia.",
        applies_to_states=["post_prostatectomy", "recurrence_bcr"],
        persist_targets=["imaging_studies", "biochemical_recurrence"],
        clinical_influence=[
            "Completa la trazabilidad de rescate, gammagrama y cronología de recurrencia.",
        ],
        fields=[
            _field("has_bone_scan", "Gammagrama óseo disponible", "select", options=["0", "1"], default="0", group="Imagen complementaria", group_order=1, clinical_role="monitoring"),
            _field("margin_location", "Localización del margen positivo", "select", options=MARGIN_LOCATION_OPTIONS, default="Ápex", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner"),
        ],
    )


def _survival_fragment() -> RegistrationFragment:
    applicable_states = [
        "post_prostatectomy",
        "recurrence_bcr",
        "adt_progression_verification",
        "mcspc_oligo_metachronous",
        "mcspc_low_volume_sync_oligo",
        "mcspc_high_volume_sync",
        "mcspc_high_volume_metachronous",
        "mcspc_high_volume",
        "m0_crpc",
        "m1_crpc",
    ]
    return _fragment(
        id="fragment_survival_status",
        title="Estado vital y anclas de supervivencia",
        capture_layer="scenario_refiners",
        when_to_ask="Solo cuando falten anclas de supervivencia o progresión que afecten seguimiento longitudinal.",
        applies_to_states=applicable_states,
        persist_targets=["survival_status_records", "survival_anchor_events", "patient_identity"],
        clinical_influence=[
            "Cierra la trazabilidad para OS, rPFS, MFS, TTR, TTPP y TTSRE sin romper el longitudinal existente.",
        ],
        fields=[
            _field("registrar_defuncion_en_esta_visita", "Registrar defunción en esta visita", "select", options=["0", "1"], default="0", group="Estado vital", group_order=1, clinical_role="decision_refiner"),
            _field("last_contact_date", "Último contacto documentado", "date", group="Estado vital", group_order=1, clinical_role="required"),
            _field("last_contact_status", "Tipo de último contacto", "select", options=["", "clinic_visit", "phone", "lab_result", "imaging", "document_review"], group="Estado vital", group_order=1, clinical_role="required"),
            _field("vital_status", "Estado vital", "select", options=["", "alive", "deceased", "lost_to_followup"], group="Estado vital", group_order=1, clinical_role="required", conditional_visibility={"registrar_defuncion_en_esta_visita": ["1"]}),
            _field("date_of_death", "Fecha de defunción", "date", group="Estado vital", group_order=1, clinical_role="monitoring", conditional_visibility={"registrar_defuncion_en_esta_visita": ["1"]}),
            _field("cause_of_death", "Causa de muerte", "select", options=["", "prostate_cancer", "other_cancer", "cardiovascular", "infection", "treatment_related", "other", "unknown"], group="Estado vital", group_order=1, clinical_role="monitoring", conditional_visibility={"registrar_defuncion_en_esta_visita": ["1"]}),
            _field("death_source", "Fuente del estado vital", "text", group="Estado vital", group_order=1, clinical_role="monitoring", conditional_visibility={"registrar_defuncion_en_esta_visita": ["1"]}),
            _field("radiographic_progression_date", "Fecha de progresión radiográfica", "date", group="Endpoints", group_order=2, clinical_role="monitoring"),
            _field("psa_progression_date", "Fecha de progresión PSA", "date", group="Endpoints", group_order=2, clinical_role="monitoring"),
            _field("crpc_confirmation_date", "Fecha de confirmación CRPC", "date", group="Endpoints", group_order=2, clinical_role="monitoring"),
            _field("next_line_start_date", "Fecha de inicio de siguiente línea", "date", group="Endpoints", group_order=2, clinical_role="monitoring"),
        ],
    )


def _structured_biopsy_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_structured_biopsy_operational",
        title="Biopsia estructurada y concordancia MRI",
        capture_layer="scenario_refiners",
        when_to_ask="Solo cuando la biopsia o su trazabilidad modifican riesgo, vigilancia o ruta diagnóstica.",
        applies_to_states=["diagnostic_workup", "post_negative_biopsy_followup", "localized_initial"],
        persist_targets=["structured_biopsy", "biopsy_details"],
        clinical_influence=[
            "Permite registrar tipo de biopsia, contexto y mapeo dirigido para vigilancia activa y rebiopsia.",
        ],
        fields=[
            _field("biopsy_date", "Fecha de biopsia", "date", group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
            _field("biopsy_type", "Tipo de biopsia", "select", options=["", "systematic", "mri_targeted", "fusion", "saturation"], group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
            _field("biopsy_route", "Vía de biopsia", "select", options=["", "transperineal", "transrectal"], group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
            _field("biopsy_context", "Contexto de biopsia", "select", options=["", "diagnostic", "confirmatory_as", "followup_as", "rebiopsy"], group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
            _field("mri_pirads_at_biopsy", "PI-RADS al momento de biopsia", "number", group="Biopsia estructurada", group_order=1, clinical_role="decision_refiner"),
            _field("total_cores", "Número total de cilindros", "number", group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
            _field("positive_cores", "Número de cilindros positivos", "number", group="Biopsia estructurada", group_order=1, clinical_role="monitoring"),
        ],
    )


def _active_surveillance_operational_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_active_surveillance_operational",
        title="Operación real de vigilancia activa",
        capture_layer="scenario_refiners",
        when_to_ask="Solo cuando el paciente entra o sale de vigilancia activa y esos datos cambian la trayectoria.",
        applies_to_states=["localized_initial", "post_negative_biopsy_followup"],
        persist_targets=["active_surveillance_update"],
        clinical_influence=[
            "Sostiene elegibilidad, confirmatory biopsy y triggers de salida del protocolo en una tabla operacional.",
        ],
        fields=[
            _field("as_protocol", "Protocolo de vigilancia activa", "select", options=["", "NCCN_very_low", "NCCN_low", "NCCN_favorable_intermediate", "PRIAS", "Royal_Marsden"], group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
            _field("confirmatory_biopsy_planned", "Biopsia confirmatoria planeada", "select", options=["", "0", "1"], group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
            _field("confirmatory_biopsy_done", "Biopsia confirmatoria realizada", "select", options=["", "0", "1"], group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
            _field("confirmatory_biopsy_date", "Fecha de biopsia confirmatoria", "date", group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
            _field("mri_interval_months", "Intervalo de MRI multiparamétrica", "number", group="Vigilancia activa", group_order=1, clinical_role="monitoring", unit="meses"),
            _field("as_exit_reason", "Motivo de salida de vigilancia activa", "select", options=["", "gleason_upgrade", "volume_increase", "mri_progression", "patient_preference", "psa_kinetics"], group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
            _field("as_exit_treatment", "Tratamiento de conversión", "select", options=["", "prostatectomy", "radiation", "focal_therapy", "observation"], group="Vigilancia activa", group_order=1, clinical_role="monitoring"),
        ],
    )


def _skeletal_bone_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_skeletal_bone_operational",
        title="Eventos esqueléticos y salud ósea",
        capture_layer="safety_eligibility",
        when_to_ask="Solo cuando la salud ósea o los SRE cambian seguridad, soporte o tratamiento concomitante.",
        applies_to_states=[
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        ],
        persist_targets=["skeletal_events", "bone_modifying_agent", "bone_health_snapshot"],
        clinical_influence=[
            "Hace capturable el primer SRE, el curso de denosumab/zoledrónico y el monitoreo de ONJ/óseo.",
        ],
        fields=[
            _field("worst_t_score", "Peor T-score documentado", "number", group="Salud ósea", group_order=1, clinical_role="monitoring"),
            _field("frax_major_pct", "FRAX fractura mayor", "number", group="Salud ósea", group_order=1, clinical_role="monitoring", unit="%"),
            _field("frax_hip_pct", "FRAX cadera", "number", group="Salud ósea", group_order=1, clinical_role="monitoring", unit="%"),
            _field("dental_clearance_done", "Clearance dental documentado", "select", options=["", "0", "1"], group="Agente modificador óseo", group_order=2, clinical_role="monitoring"),
            _field("onj_monitoring", "Monitoreo de osteonecrosis mandibular", "select", options=["", "0", "1"], group="Agente modificador óseo", group_order=2, clinical_role="monitoring"),
            _field("bma_agent", "Agente modificador óseo", "select", options=["", "denosumab", "zoledronic_acid"], group="Agente modificador óseo", group_order=2, clinical_role="monitoring"),
            _field("bma_start_date", "Inicio de agente modificador óseo", "date", group="Agente modificador óseo", group_order=2, clinical_role="monitoring"),
        ],
    )


def _radiotherapy_detail_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_radiotherapy_detailed",
        title="Radioterapia detallada",
        capture_layer="scenario_refiners",
        when_to_ask="Solo cuando la radioterapia previa o planeada cambia la elegibilidad, la secuencia o el rescate.",
        applies_to_states=["localized_initial", "post_prostatectomy", "recurrence_bcr", "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m1_crpc"],
        persist_targets=["radiotherapy_course", "radiation_details"],
        clinical_influence=[
            "Diferencia RT definitiva, adyuvante, salvamento y MDT con dosis, fraccionamiento y toxicidad.",
        ],
        fields=[
            _field("received_radiotherapy_this_visit", "Registrar radioterapia en esta visita", "select", options=["0", "1"], default="0", group="Radioterapia", group_order=1, clinical_role="decision_refiner"),
            _field("rt_intent", "Intención de radioterapia", "select", options=["", "definitive", "adjuvant", "salvage", "palliative", "MDT"], group="Radioterapia", group_order=1, clinical_role="monitoring", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
            _field("modality", "Modalidad de radioterapia", "select", options=["", "EBRT_IMRT", "EBRT_VMAT", "SBRT", "LDR_brachy", "HDR_brachy", "protons", "combined"], group="Radioterapia", group_order=1, clinical_role="monitoring", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
            _field("target_volume", "Campo / volumen blanco", "select", options=["", "prostate_only", "prostate_sv", "whole_pelvis", "boost_dominant", "metastasis_directed", "prostate_pelvis_boost"], group="Radioterapia", group_order=1, clinical_role="monitoring", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
            _field("total_dose_gy", "Dosis total", "number", group="Radioterapia", group_order=1, clinical_role="monitoring", unit="Gy", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
            _field("fractions", "Número de fracciones", "number", group="Radioterapia", group_order=1, clinical_role="monitoring", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
            _field("salvage_psa_at_start", "PSA al inicio de RT de salvamento", "number", group="Radioterapia", group_order=1, clinical_role="monitoring", unit="ng/mL", conditional_visibility={"received_radiotherapy_this_visit": ["1"]}),
        ],
    )


def _advanced_current_treatment_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_treatment_history",
        title="Tratamiento actual e historial terapéutico",
        capture_layer="scenario_refiners",
        when_to_ask="Solo en enfermedad avanzada cuando la línea y la exposición previa cambian secuenciación o clasificación.",
        applies_to_states=[
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        ],
        persist_targets=["treatment_history", "prior_clinical_history"],
        clinical_influence=[
            "Alimenta secuenciación terapéutica, perfil longitudinal y benchmarking de adopción.",
        ],
        fields=[
            _field("line_of_therapy_number", "Número de línea terapéutica", "select", options=LINE_OF_THERAPY_NUMBER_OPTIONS, default="", group="Tratamiento actual", group_order=1, clinical_role="required"),
            _field("line_of_therapy_context", "Contexto clínico de la línea", "select", options=LINE_OF_THERAPY_CONTEXT_OPTIONS, default="", group="Tratamiento actual", group_order=1, clinical_role="required"),
            _field(
                "drug_scheme",
                "Esquema farmacológico",
                "select",
                options=therapy_select_options(state="advanced", management_track="systemic_surveillance", include_empty=True),
                default="",
                group="Tratamiento actual",
                group_order=1,
                clinical_role="decision_refiner",
                help_text="Seleccione el esquema canónico activo para que la línea terapéutica y la torre de APE queden alineadas.",
            ),
            _field("current_adt_context", "Contexto actual de ADT", "select", options=["", "none", "medical_adt_continuous", "medical_adt_interrupted", "orchiectomy"], default="", group="Tratamiento actual", group_order=1, clinical_role="required"),
            _field("castrate_testosterone_status", "Estado de castración", "select", options=["", "unknown", "confirmed_castrate", "not_castrate"], default="unknown", group="Tratamiento actual", group_order=1, clinical_role="required"),
            _field("conventional_imaging_status", "Imagen convencional", "select", options=["", "NOT_RESTAGED", "M0", "M1"], default="", group="Tratamiento actual", group_order=1, clinical_role="decision_refiner"),
            _field("rt_primary_received", "Radioterapia primaria previa", "select", options=["0", "1"], default="0", group="Historial previo", group_order=2, clinical_role="monitoring"),
            _field("rt_primary_dose_gy", "Dosis total de radioterapia primaria", "number", group="Historial previo", group_order=2, clinical_role="monitoring", unit="Gy"),
            _field("prior_docetaxel_cycles", "Ciclos previos de docetaxel", "number", default=0, group="Historial previo", group_order=2, clinical_role="decision_refiner", unit="ciclos"),
            _field("prior_arpi_agent", "Inhibidor previo de la vía del receptor androgénico", "select", options=["", "Abiraterona", "Enzalutamida", "Apalutamida", "Darolutamida"], default="", group="Historial previo", group_order=2, clinical_role="decision_refiner"),
            _field("prior_arpi_duration", "Duración del inhibidor previo de la vía del receptor androgénico", "number", default=0, group="Historial previo", group_order=2, clinical_role="decision_refiner", unit="meses"),
            # Faubot 2026-04-25 (LXV) — Auditoría #63B
            # Treatment history timeline al intake: captura líneas terapéuticas
            # previas (no solo la actual) para alimentar correctamente la
            # torre de vigilancia de APE con bandas de tratamiento históricas
            # y permitir cálculo de variación PSA por línea (PSADT por línea,
            # nadir por línea, % cambio nadir, etc.).
            _field("prior_treatment_lines_count", "Número de líneas terapéuticas previas (sistémicas)", "number", default=0, group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", unit="líneas", help_text="Cuente solo líneas SISTÉMICAS previas (ADT mono, ARPI, taxano, PARPi, Lu-177, etc.); excluya RT/cirugía locales."),
            _field("most_recent_prior_line_drug_scheme", "Línea previa más reciente: esquema farmacológico", "select", options=therapy_select_options(state="advanced", management_track="systemic_surveillance", include_empty=True), default="", group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", help_text="Esquema canónico de la línea previa inmediatamente anterior a la actual (alimenta torre de APE con banda histórica)."),
            _field("most_recent_prior_line_start_date", "Línea previa más reciente: fecha de inicio", "date", group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", help_text="Fecha en que se inició la línea previa (banda izquierda en torre APE)."),
            _field("most_recent_prior_line_end_date", "Línea previa más reciente: fecha de fin", "date", group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", help_text="Fecha en que se discontinuó la línea previa (banda derecha en torre APE)."),
            _field("most_recent_prior_line_reason_for_change", "Línea previa más reciente: motivo del cambio", "select", options=["", "progression_psa", "progression_radiographic", "progression_clinical", "toxicity", "completion_planned", "patient_choice", "other"], default="", group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", help_text="Por qué se cambió la línea previa (clave para auditabilidad de secuenciación)."),
            _field("most_recent_prior_line_best_psa_response_pct", "Línea previa más reciente: mejor respuesta PSA (% cambio nadir)", "number", group="Timeline terapéutico previo", group_order=2, clinical_role="decision_refiner", unit="% cambio", help_text="Cambio % del PSA nadir vs basal de la línea previa (negativo = reducción; e.g., -75 = reducción 75%)."),
            # Faubot 2026-04-25 (LXVI) — Auditoría #63C
            # Widget multi-row para captura de N líneas terapéuticas previas
            # (no solo "la más reciente"). Reusa pattern psa_history. Cuando
            # presente, expande treatments[] con N entradas + actual,
            # alimentando torre de vigilancia con bandas históricas completas.
            _field(
                "prior_treatment_lines_history",
                "Historial completo de líneas terapéuticas previas (multi-línea)",
                "prior_lines_history",
                group="Timeline terapéutico previo",
                group_order=2,
                clinical_role="decision_refiner",
                help_text="Agregue múltiples líneas terapéuticas previas con start/end/drug_scheme/reason; el sistema expandirá treatments[] automáticamente y alimentará la torre de APE con bandas históricas completas. Si solo se conoce la línea inmediatamente anterior, use los campos `most_recent_prior_line_*` arriba.",
            ),
        ] + _metastatic_intake_fields(),
    )


def _advanced_biomarker_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_advanced_biomarkers",
        title="Biomarcadores y trazabilidad molecular",
        capture_layer="scenario_refiners",
        when_to_ask="Solo cuando biomarcadores, PSMA o la trazabilidad molecular cambian elegibilidad o prioridad terapéutica.",
        applies_to_states=[
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        ],
        persist_targets=["clinical_baseline", "prior_clinical_history", "imaging_studies"],
        clinical_influence=[
            "Alinea biomarcadores, fuente documental y elegibilidad molecular con la trayectoria clínica activa.",
        ],
        fields=[
            _field("hrr_status", "Estado HRR", "select", options=["", "Positivo", "Negativo", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("hrr_gene", "Gen HRR dominante", "text", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("brca2_status", "BRCA2", "select", options=["", "Positivo", "Negativo", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("msi_status", "MSI", "select", options=["", "Inestable", "Estable", "Desconocido"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("tmb_high", "TMB alto", "select", options=["0", "1"], default="0", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("biomarker_source", "Fuente del biomarcador", "text", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("molecular_assay_date", "Fecha del estudio molecular", "date", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("psma_positive", "PSMA positivo", "select", options=["0", "1"], default="0", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
            _field("psma_negative_dominant_lesions", "Lesiones dominantes PSMA negativas", "select", options=["0", "1"], default="0", group="Biomarcadores", group_order=3, clinical_role="decision_refiner"),
        ],
    )


def _advanced_docetaxel_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_advanced_docetaxel_eligibility",
        title="Elegibilidad a docetaxel",
        capture_layer="safety_eligibility",
        when_to_ask="Solo cuando el paciente sigue siendo candidato real a docetaxel o triplete en enfermedad metastásica sensible a la castración de alto volumen.",
        applies_to_states=[
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
        ],
        persist_targets=["clinical_assessments", "clinical_baseline", "prior_clinical_history"],
        clinical_influence=[
            "Verifica elegibilidad quimioterapéutica actual con biometría, pruebas hepáticas, alergias relevantes y contexto funcional antes de cerrar triplete.",
        ],
        fields=[
            _field("cbc_date", "Fecha de biometría hemática", "date", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            _field("anc", "ANC", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", conditional_visibility=_docetaxel_visibility()),
            _field("platelets", "Plaquetas", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", conditional_visibility=_docetaxel_visibility()),
            _field("liver_panel_date", "Fecha de pruebas hepáticas", "date", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            _field("bilirubin", "Bilirrubina total", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="mg/dL", conditional_visibility=_docetaxel_visibility()),
            _field("ast", "AST (TGO)", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", conditional_visibility=_docetaxel_visibility()),
            _field("alt", "ALT (TGP)", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", conditional_visibility=_docetaxel_visibility()),
            _field("alp", "Fosfatasa alcalina", "number", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", conditional_visibility=_docetaxel_visibility()),
            _field("taxane_hypersensitivity_history", "Hipersensibilidad previa a taxanos", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            _field("polysorbate_hypersensitivity", "Hipersensibilidad a polisorbato 80", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            _field("child_pugh_score", "Child-Pugh", "select", options=["", "A", "B", "C"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            _field("performance_status_driver", "Origen del deterioro funcional", "select", options=["", "mixed_or_unclear", "cancer_related", "comorbidity_or_frailty"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="decision_refiner", conditional_visibility={"ecog_score": ["2"]}),
            _field("bone_pain", "Dolor óseo relacionado con la enfermedad", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="decision_refiner", conditional_visibility={"ecog_score": ["2"]}),
        ],
    )


def _advanced_safety_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_advanced_safety",
        title="Seguridad, fragilidad y elegibilidad terapéutica",
        capture_layer="safety_eligibility",
        when_to_ask="Solo cuando la seguridad, la fragilidad o la reserva funcional cambian elegibilidad y contraindicaciones.",
        applies_to_states=[
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        ],
        persist_targets=["clinical_assessments", "clinical_baseline"],
        clinical_influence=[
            "Convierte comorbilidad, fragilidad y seguridad en modificadores visibles de elegibilidad terapéutica.",
        ],
        fields=[
            _field("seizure_history", "Antecedente convulsivo", "select", options=["0", "1"], default="0", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["", "0", "1", "2", "3", "4"], default="", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("dermatitis_history", "Dermatitis / rash previo", "select", options=["0", "1"], default="0", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("mini_cog_score", "Mini-Cog basal", "select", options=MINI_COG_OPTIONS, group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("fatigue_score", "Brief Fatigue Inventory basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("systolic_bp", "PA sistólica basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="mmHg"),
            _field("total_cholesterol", "Colesterol total basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="mg/dL"),
            _field("hdl_cholesterol", "HDL basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="mg/dL"),
            _field("triglycerides", "Triglicéridos basales", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="mg/dL"),
            _field("glucose", "Glucosa basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="mg/dL"),
            _field("waist_circumference_cm", "Cintura abdominal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="cm"),
            _field("vitamin_d_level", "Vitamina D basal", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="ng/mL"),
            _field("height_cm", "Estatura actual", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="cm"),
            _field("weight_loss_6m_kg", "Pérdida ponderal 6 meses", "number", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner", unit="kg"),
            _field("protein_supplements", "Suplementos proteicos", "select", options=["0", "1"], default="0", group="Seguridad ARPI", group_order=3, clinical_role="decision_refiner"),
            _field("calcium_vitd_started", "Calcio / vitamina D iniciados", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring"),
            _field("bone_protection_started", "Protección ósea iniciada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring"),
        ],
    )


def _mexico_fragment() -> RegistrationFragment:
    return _fragment(
        id="fragment_mexico_cohort_optional",
        title="Perfil demográfico de México para investigación",
        capture_layer="research_optional",
        when_to_ask="Solo si se desea enriquecer la cohorte y el benchmarking institucional.",
        collapsed_by_default=True,
        applies_to_states=list(STATE_SCOPE_MAP.keys()),
        persist_targets=["patient_demographics"],
        clinical_influence=[
            "No cambia la recomendación primaria, pero fortalece cohortes y benchmarking poblacional.",
        ],
        optional_research=True,
        benchmark_only=True,
        fields=[
            _field("estado_residencia", "Estado de residencia", "select", options=[
                "",
                "Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas",
                "Chihuahua", "CDMX", "Coahuila", "Colima", "Durango", "Estado de Mexico",
                "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "Michoacan", "Morelos",
                "Nayarit", "Nuevo Leon", "Oaxaca", "Puebla", "Queretaro", "Quintana Roo",
                "San Luis Potosi", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala",
                "Veracruz", "Yucatan", "Zacatecas",
            ], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("seguridad_social", "Institución de seguridad social", "select", options=["", "IMSS", "ISSSTE", "IMSS-Bienestar", "SEDENA", "Privado", "Sin_seguridad"], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("escolaridad", "Escolaridad", "select", options=["", "Sin_estudios", "Primaria", "Secundaria", "Preparatoria", "Licenciatura", "Posgrado"], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("ocupacion", "Ocupación", "text", group="Cohorte México", group_order=2, clinical_role="optional"),
            _field("estado_civil", "Estado civil", "select", options=["", "Soltero", "Casado", "Union_libre", "Divorciado", "Viudo"], group="Cohorte México", group_order=2, clinical_role="optional"),
            _field("tabaquismo", "Tabaquismo", "select", options=["nunca", "ex_fumador", "activo_leve", "activo_moderado", "activo_severo"], default="nunca", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("paquetes_anio", "Paquetes-año", "number", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("actividad_fisica", "Actividad física", "select", options=["sedentario", "leve", "moderado", "intenso"], default="sedentario", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("diabetes_mellitus", "Diabetes mellitus", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
            _field("hipertension", "Hipertensión", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
            _field("sindrome_metabolico", "Síndrome metabólico", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
        ],
    )


def _persist_targets_for_field(field_name: str, scope: str) -> list[str]:
    mapping = {
        "baseline_psa": ["clinical_baseline"],
        "mpmri_date": ["mri_facts", "imaging_studies"],
        "mpmri_quality": ["mri_facts"],
        "pirads_score": ["mri_facts", "imaging_studies"],
        "index_lesion_location": ["mri_facts", "imaging_studies"],
        "index_lesion_size_mm": ["mri_facts", "imaging_studies"],
        "prostate_volume_ml": ["mri_facts"],
        "prior_mpmri_pirads_score": ["imaging_studies"],
        "prior_mpmri_targeted_biopsy_status": ["imaging_studies", "biopsy_details"],
        "planned_biopsy_type": ["diagnostic_plan", "biopsy_trigger"],
        "planned_biopsy_route": ["diagnostic_plan", "biopsy_trigger"],
        "risk_calculator_pathway": ["diagnostic_plan"],
        "germline_status": ["family_history_detail", "genomic_profile"],
        "percent_pattern_4": ["biopsy_details"],
        "adverse_histology_variant_type": ["biopsy_details"],
        "adverse_histology_variant_detail": ["biopsy_details"],
        "confirmatory_biopsy_planned": ["clinical_assessments"],
        "decipher_risk": ["genomic_profile"],
        "psma_pet_result": ["imaging_studies"],
        "psma_radioligand": ["imaging_studies"],
        "psma_index_lesion_site": ["imaging_studies"],
        "psma_index_lesion_suvmax": ["imaging_studies"],
        "psma_uptake_pattern": ["imaging_studies"],
        "psma_rads_score": ["imaging_studies"],
        "psma_total_lesions": ["imaging_studies"],
        "psma_lesion_locations": ["imaging_studies"],
        "conventional_stage_before_psma": ["imaging_studies"],
        "psma_stage_after_psma": ["imaging_studies"],
        "psma_management_changed": ["imaging_studies"],
        "hrr_gene": ["genomic_profile"],
        "hrr_status": ["genomic_profile", "clinical_baseline"],
        "brca2_status": ["genomic_profile"],
        "tmb_high": ["genomic_profile"],
        "biomarker_source": ["genomic_profile"],
        "molecular_assay_date": ["genomic_profile"],
        "psma_positive": ["imaging_studies", "clinical_assessments"],
        "psma_negative_dominant_lesions": ["imaging_studies", "clinical_assessments"],
        "peripheral_neuropathy_grade": ["clinical_assessments", "clinical_baseline"],
        "cbc_date": ["clinical_assessments", "clinical_baseline"],
        "anc": ["clinical_assessments", "clinical_baseline"],
        "platelets": ["clinical_assessments", "clinical_baseline"],
        "liver_panel_date": ["clinical_assessments", "clinical_baseline"],
        "bilirubin": ["clinical_assessments", "clinical_baseline"],
        "ast": ["clinical_assessments", "clinical_baseline"],
        "alt": ["clinical_assessments", "clinical_baseline"],
        "alp": ["clinical_assessments", "clinical_baseline"],
        "taxane_hypersensitivity_history": ["clinical_assessments", "prior_clinical_history"],
        "polysorbate_hypersensitivity": ["clinical_assessments", "prior_clinical_history"],
        "child_pugh_score": ["clinical_assessments", "clinical_baseline"],
        "performance_status_driver": ["clinical_assessments", "clinical_baseline"],
        "bone_pain": ["clinical_assessments", "clinical_baseline"],
        "mcrpc_line_context": ["prior_clinical_history"],
        "current_adt_context": ["prior_clinical_history", "clinical_assessments"],
        "castrate_testosterone_status": ["clinical_baseline", "clinical_assessments"],
        "conventional_imaging_status": ["imaging_studies", "clinical_assessments"],
        "dxa_baseline_done": ["clinical_assessments"],
        "calcium_vitd_started": ["clinical_assessments"],
        "bone_protection_started": ["clinical_assessments"],
        "margin_location": ["surgical_details", "clinical_assessments"],
        "vital_status": ["survival_status_records", "patient_identity"],
        "date_of_death": ["survival_status_records", "patient_identity"],
        "cause_of_death": ["survival_status_records", "patient_identity"],
        "last_contact_date": ["survival_status_records", "patient_identity"],
        "last_contact_status": ["survival_status_records", "patient_identity"],
        "death_source": ["survival_status_records", "patient_identity"],
        "radiographic_progression_date": ["survival_anchor_events", "clinical_assessments"],
        "psa_progression_date": ["survival_anchor_events", "clinical_assessments"],
        "crpc_confirmation_date": ["survival_anchor_events", "clinical_assessments"],
        "next_line_start_date": ["survival_anchor_events", "treatment_history"],
        "biopsy_route": ["structured_biopsy", "biopsy_details"],
        "biopsy_context": ["structured_biopsy", "biopsy_details"],
        "mri_pirads_at_biopsy": ["structured_biopsy", "mri_facts"],
        "as_protocol": ["active_surveillance_update"],
        "confirmatory_biopsy_planned": ["active_surveillance_update"],
        "confirmatory_biopsy_done": ["active_surveillance_update"],
        "confirmatory_biopsy_date": ["active_surveillance_update"],
        "mri_interval_months": ["active_surveillance_update"],
        "as_exit_reason": ["active_surveillance_update"],
        "as_exit_treatment": ["active_surveillance_update"],
        "worst_t_score": ["bone_health_snapshot"],
        "frax_major_pct": ["bone_health_snapshot"],
        "frax_hip_pct": ["bone_health_snapshot"],
        "dental_clearance_done": ["bone_modifying_agent", "bone_health_snapshot"],
        "onj_monitoring": ["bone_modifying_agent", "bone_health_snapshot"],
        "bma_agent": ["bone_modifying_agent"],
        "bma_start_date": ["bone_modifying_agent"],
        "rt_intent": ["radiotherapy_course", "radiation_details"],
        "modality": ["radiotherapy_course", "radiation_details"],
        "target_volume": ["radiotherapy_course", "radiation_details"],
        "total_dose_gy": ["radiotherapy_course", "radiation_details"],
        "fractions": ["radiotherapy_course", "radiation_details"],
        "salvage_psa_at_start": ["radiotherapy_course"],
        "epic26_response_packet": ["patient_pros", "clinical_assessments"],
        "epic26_urinary_incontinence_domain": ["patient_pros", "clinical_assessments"],
        "epic26_urinary_irritative_domain": ["patient_pros", "clinical_assessments"],
        "epic26_urinary_domain": ["patient_pros", "clinical_assessments"],
        "epic26_sexual_domain": ["patient_pros", "clinical_assessments"],
        "epic26_bowel_domain": ["patient_pros", "clinical_assessments"],
        "epic26_hormonal_domain": ["patient_pros", "clinical_assessments"],
        "epic26_overall_urinary_bother": ["patient_pros", "clinical_assessments"],
    }
    default_targets = {
        "diagnostic": ["clinical_assessments", "diagnostic_plan"],
        "localized": ["clinical_assessments", "biopsy_details"],
        "postlocal": ["clinical_assessments", "biochemical_recurrence"],
        "advanced": ["clinical_assessments", "clinical_baseline", "prior_clinical_history"],
    }
    return mapping.get(field_name, default_targets[scope])


def _is_present(value: Any) -> bool:
    return value not in (None, "")


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positivo", "positive", "confirmed_castrate"}


MARGIN_LOCATION_OPTIONS = ["", "Ápex", "Base", "Posterolateral", "Múltiple", "Otro"]


def _death_documented(data: dict[str, Any]) -> bool:
    vital_status = str(data.get("vital_status") or "").strip().lower()
    return vital_status == "deceased" or _is_present(data.get("date_of_death"))


def _radiotherapy_truth_positive(data: dict[str, Any]) -> bool:
    if any(_truthy(data.get(flag)) for flag in ("rt_primary_received", "prior_radiation", "received_radiotherapy_this_visit")):
        return True
    return any(
        _is_present(data.get(field))
        for field in ("rt_intent", "modality", "target_volume", "total_dose_gy", "fractions", "salvage_psa_at_start")
    )


def _known_cancer_diagnosis(state: str, data: dict[str, Any]) -> bool:
    if _truthy(data.get("known_cancer_diagnosis")):
        return True
    return str(state or "").strip() not in {"diagnostic_workup", "post_negative_biopsy_followup"}


def _has_pathology_detail(data: dict[str, Any]) -> bool:
    pathology_fields = (
        "gleason_primary",
        "gleason_secondary",
        "isup_grade",
        "total_cores",
        "positive_cores",
        "num_cores_positive",
        "structured_biopsy",
        "biopsy_date",
    )
    return any(_is_present(data.get(field)) for field in pathology_fields)


class PatientTrackingService:
    def get_full_record(self, nss: str) -> dict | None:
        return get_patient_full_record(nss)

    def scope_for_state(self, state: str) -> str:
        return STATE_SCOPE_MAP.get(state, "diagnostic")

    def canonicalization_map(self) -> dict[str, Any]:
        return {
            "aliases": deepcopy(CANONICAL_FIELD_MAP),
            "values": deepcopy(CANONICAL_VALUE_MAPS),
        }

    def build_registration_context(
        self,
        *,
        module_schema: dict[str, Any],
        module_id: str,
        state: str,
        assessment_input: dict[str, Any],
        assessment_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self.scope_for_state(state or module_id)
        config = deepcopy(SCOPE_CONFIG[scope])
        known_cancer = _known_cancer_diagnosis(state, assessment_input)
        needs_biopsy_capture = known_cancer and not _has_pathology_detail(assessment_input)
        death_toggle_default = "1" if _death_documented(assessment_input) else str(assessment_input.get("registrar_defuncion_en_esta_visita") or "0" or "0")
        rt_toggle_default = "1" if _radiotherapy_truth_positive(assessment_input) else str(assessment_input.get("received_radiotherapy_this_visit") or "0" or "0")
        fragments = [_common_fragment(), _official_diagnosis_fragment()]
        if scope == "diagnostic":
            fragments.append(_diagnostic_fragment())
        elif scope == "localized":
            fragments.append(_localized_fragment())
            fragments.append(_structured_biopsy_fragment())
            fragments.append(_active_surveillance_operational_fragment())
            fragments.append(_radiotherapy_detail_fragment())
        elif scope == "postlocal":
            fragments.append(_postlocal_fragment())
            fragments.append(_survival_fragment())
            fragments.append(_radiotherapy_detail_fragment())
        else:
            fragments.append(_advanced_current_treatment_fragment())
            fragments.append(_advanced_biomarker_fragment())
            fragments.append(_advanced_safety_fragment())
            if state in {"mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"}:
                fragments.append(_advanced_docetaxel_fragment())
            fragments.append(_survival_fragment())
            fragments.append(_skeletal_bone_fragment())
            fragments.append(_radiotherapy_detail_fragment())
        if scope == "diagnostic":
            fragments.append(_structured_biopsy_fragment())
        if needs_biopsy_capture and not any(fragment.id == "fragment_structured_biopsy_operational" for fragment in fragments):
            fragments.append(_structured_biopsy_fragment())
        fragments.append(_mexico_fragment())
        fragments = [_apply_fragment_semantics(fragment) for fragment in fragments]

        imported_fields = []
        for field in module_schema.get("fields", []):
            value = assessment_input.get(field["name"])
            if not _is_present(value):
                continue
            semantics = field_semantics_for(field["name"])
            value_label = ""
            if field.get("field_type") == "gleason_profile":
                value_label = normalize_gleason_profile(assessment_input).get("summary") or ""
            elif field.get("field_type") == "metastatic_components":
                metastatic_summary = build_metastatic_composition_summary(assessment_input)
                value_label = metastatic_summary.get("narrative") or metastatic_summary.get("summary") or ""
            imported_fields.append(
                {
                    "name": field["name"],
                    "label": field["label"],
                    "value": value,
                    "value_label": value_label,
                    "options": field.get("options", []),
                    "clinical_role": field.get("clinical_role", ""),
                    "persist_targets": _persist_targets_for_field(field["name"], scope),
                    "reuse_key": semantics["reuse_key"],
                    "capture_layer": semantics["capture_layer"],
                    "capture_layer_label": semantics["capture_layer_label"],
                    "when_to_ask": semantics["when_to_ask"],
                }
            )
        fragments, deduped_visible_fields = _dedupe_registration_fragments(fragments, imported_fields)

        gleason_profile = normalize_gleason_profile(assessment_input)
        metastatic_known = str(assessment_input.get("metastatic_disease_known", "")).strip() == "1" or any(
            str(assessment_input.get(key, "")).strip() not in {"", "[]", "null", "None"}
            for key in ("bone_site_entries", "visceral_site_entries", "nonregional_nodal_site_entries")
        )
        defaults = {
            "assessment_state": state,
            "baseline_psa": assessment_input.get("baseline_psa", assessment_input.get("psa", "")),
            "metastasis_site": assessment_input.get("metastasis_site", "M0" if scope != "advanced" else ""),
            "volume_disease": assessment_input.get("volume_disease", "Low" if scope != "advanced" else ""),
            "line_of_therapy_number": assessment_input.get("line_of_therapy_number", assessment_input.get("line_of_therapy", "")),
            "line_of_therapy_context": assessment_input.get("line_of_therapy_context", ""),
            "psa_history": assessment_input.get("psa_history", assessment_input.get("ape_history", [])),
            "testosterone_history": assessment_input.get("testosterone_history", []),
            "registrar_defuncion_en_esta_visita": death_toggle_default,
            "received_radiotherapy_this_visit": rt_toggle_default,
            "vital_status": assessment_input.get("vital_status", "deceased" if death_toggle_default == "1" else ""),
            "margin_location": assessment_input.get("margin_location", "Ápex"),
            "positive_cores": assessment_input.get("positive_cores", assessment_input.get("num_cores_positive", "")),
            "gleason_score": {
                "gleason_primary": gleason_profile.get("gleason_primary") or "",
                "gleason_secondary": gleason_profile.get("gleason_secondary") or "",
                "gleason_tertiary": gleason_profile.get("gleason_tertiary") or "",
                "gleason_score": gleason_profile.get("gleason_score") or "",
                "isup_grade": gleason_profile.get("isup_grade") or "",
            },
            "metastatic_components_capture": {
                "metastatic_disease_known": metastatic_known,
                "bone_site_entries": assessment_input.get("bone_site_entries", []),
                "visceral_site_entries": assessment_input.get("visceral_site_entries", []),
                "nonregional_nodal_site_entries": assessment_input.get("nonregional_nodal_site_entries", []),
                "bone_metastasis_present": assessment_input.get("bone_metastasis_present", "1" if assessment_input.get("bone_site_entries") else "0"),
                "visceral_metastasis_present": assessment_input.get("visceral_metastasis_present", "1" if assessment_input.get("visceral_site_entries") else "0"),
                "nonregional_nodal_metastasis_present": assessment_input.get("nonregional_nodal_metastasis_present", "1" if assessment_input.get("nonregional_nodal_site_entries") else "0"),
                "metastatic_total_lesion_count": assessment_input.get("metastatic_total_lesion_count", assessment_input.get("metastasis_count", "")),
            },
            "weight_loss_6m_kg": assessment_input.get("weight_loss_6m_kg", ""),
            "height_cm": assessment_input.get("height_cm", ""),
        }
        score_requirements = build_intake_score_requirements(
            module_id=module_id,
            state=state,
            assessment_input=assessment_input,
            assessment_result=assessment_result or {},
        )
        score_requirements = _filter_score_requirements_for_visible_fields(
            score_requirements,
            visible_fields=deduped_visible_fields,
            imported_fields=imported_fields,
        )
        field_semantics = _field_semantics_registry(fragments=fragments, imported_fields=imported_fields)
        score_semantics = build_score_semantics([field["name"] for field in deduped_visible_fields])

        return {
            "scope": scope,
            "scope_label": config["label"],
            "scope_description": config["description"],
            "scope_bullets": config["bullets"],
            "registration_fragments": [fragment.to_dict() for fragment in fragments],
            "capture_layers": _build_capture_layers(fragments),
            "registration_defaults": defaults,
            "therapy_catalog_options": therapy_select_options(state="advanced", management_track="systemic_surveillance", include_empty=True),
            "therapy_catalog_entries": therapy_catalog_entries(),
            "canonicalization_map": self.canonicalization_map(),
            "imported_clinical_fields": imported_fields,
            "deduped_visible_fields": deduped_visible_fields,
            "field_semantics": field_semantics,
            "score_semantics": score_semantics,
            "applicable_scores": score_requirements.get("applicable_scores", []),
            "required_fields_by_score": score_requirements.get("required_fields_by_score", {}),
            "score_missing_inputs": score_requirements.get("score_missing_inputs", []),
        }

    def merge_assessment_payload(self, assessment: dict[str, Any], registration_payload: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(assessment.get("input_snapshot", {}) or {})
        merged.update({key: value for key, value in registration_payload.items() if _is_present(value)})
        merged["assessment_id"] = assessment.get("id")
        merged["assessment_state"] = registration_payload.get("assessment_state") or assessment.get("state") or ""
        merged["assessment_module"] = assessment.get("module_id") or merged.get("assessment_state", "")
        nccn_primary = (assessment.get("result_snapshot", {}) or {}).get("nccn_primary", {}) or {}
        if not _is_present(merged.get("baseline_psa")) and _is_present(merged.get("psa")):
            merged["baseline_psa"] = merged.get("psa")
        if not _is_present(merged.get("clinical_risk_group")) and _is_present(nccn_primary.get("risk_group")):
            merged["clinical_risk_group"] = nccn_primary.get("risk_group")
        return self.canonicalize_payload(merged)

    def canonicalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        canonical = {}
        for key, value in payload.items():
            canonical_key = CANONICAL_FIELD_MAP.get(key, key)
            canonical[canonical_key] = value

        # ──────────────────────────────────────────────────────────────────
        # Faubot LXXXV.b — Defensive scalar normalization (FDA SaMD).
        # Bug detectado: v2 intake renderiza algunos fields 2 veces (e.g.,
        # `hrr_status` en stages `genomics` + `genomic_critical`). FormData
        # colecta ambos valores como list, que luego rompe en value_map
        # lookups + set membership downstream con "unhashable type: 'list'".
        # Fix: para fields scalar, colapsar list → último valor non-empty.
        # Preserva semántica HTML form (last duplicated <select> wins).
        # Lists legítimas (psa_history, testosterone_history, prior_treatment_lines)
        # se manejan post-canonicalize separadamente y son listas de dicts.
        # ──────────────────────────────────────────────────────────────────
        _LEGIT_LIST_FIELDS = {
            # PSA + testosterone longitudinal
            "psa_history", "ape_history", "testosterone_history",
            "psa_history_rows", "testosterone_history_rows",
            # Treatment history multirow widgets
            "prior_treatment_lines", "prior_treatment_lines_history",
            "prior_treatment_lines_rows", "prior_lines_history",
            "treatment_history", "treatments",
            "fragment_treatment_history", "prior_clinical_history",
            # Biomarker + clinical event longitudinal
            "biomarker_longitudinal", "clinical_events",
            "skeletal_events", "survival_anchor_events",
            # Toxicity + adverse event histories (skin/seizure/taxane allergy)
            "dermatitis_history", "seizure_history",
            "taxane_hypersensitivity_history",
            # Multi-value clinical lists
            "hrr_genes_mutated", "mdt_providers_present",
            "comorbidity_codes", "active_medications",
            "metastasis_sites_list",
        }
        for k in list(canonical.keys()):
            v = canonical[k]
            if isinstance(v, list) and k not in _LEGIT_LIST_FIELDS:
                # Colapsar lista escalar → último elemento non-empty (semántica form HTML)
                non_empty = [x for x in v if x not in (None, "", [])]
                canonical[k] = non_empty[-1] if non_empty else ""

        for field_name, value_map in CANONICAL_VALUE_MAPS.items():
            if field_name in canonical and canonical[field_name] in value_map:
                canonical[field_name] = value_map[canonical[field_name]]

        if _is_present(canonical.get("castrate_testosterone_status")):
            canonical["castrate_testosterone_status"] = (
                "confirmed_castrate" if _truthy(canonical.get("castrate_testosterone_status"))
                else "not_castrate" if str(canonical.get("castrate_testosterone_status")).strip().lower() in {"0", "false", "no", "not_castrate"}
                else canonical.get("castrate_testosterone_status")
            )

        line_number = canonical.get("line_of_therapy_number")
        if not _is_present(line_number) and _is_present(canonical.get("line_of_therapy")):
            line_number = canonical.get("line_of_therapy")
        if _is_present(line_number):
            canonical["line_of_therapy_number"] = str(line_number)
            canonical["line_of_therapy"] = str(line_number)

        if _is_present(canonical.get("drug_scheme")):
            canonical["drug_scheme"] = normalize_regimen_code(canonical.get("drug_scheme"))

        if canonical.get("genomic_test_done") in (None, "", "0", 0, False):
            genomic_markers = [
                canonical.get("hrr_status"),
                canonical.get("hrr_gene"),
                canonical.get("biomarker_source"),
                canonical.get("molecular_report_date"),
                canonical.get("genomic_classifier"),
                canonical.get("genomic_classifier_result"),
                canonical.get("decipher_risk"),
                canonical.get("brca2_status"),
            ]
            canonical["genomic_test_done"] = "1" if any(_is_present(item) and item not in {"No realizado", "No aplica", "Desconocido", "Desconocida"} for item in genomic_markers) else "0"

        if not _is_present(canonical.get("imaging_modality")):
            canonical["imaging_modality"] = "Ninguna"

        canonical = apply_gleason_profile(canonical)
        if _is_present(canonical.get("psa_history")) and not _is_present(canonical.get("ape_history")):
            canonical["ape_history"] = canonical.get("psa_history")
        if _is_present(canonical.get("testosterone_history")) and not isinstance(canonical.get("testosterone_history"), list):
            canonical["testosterone_history"] = canonical.get("testosterone_history")

        # Faubot 2026-04-25 (LXIV) — Auditoría #63A
        # Auto-baseline PSA point creation: si paciente tiene baseline_psa +
        # diagnosis_date pero psa_history vacío/ausente, auto-crear baseline
        # point para alimentar la torre de vigilancia desde la primera visita.
        # Esto garantiza que gates kinetics 47/53/54/55 reciban PSA history
        # correctamente desde el ingreso (no requiere visita seguimiento).
        existing_history = canonical.get("psa_history")
        history_is_empty = (
            existing_history is None
            or existing_history == ""
            or existing_history == []
            or existing_history == "[]"
        )
        baseline_psa_value = canonical.get("baseline_psa") or canonical.get("psa")
        diagnosis_date = canonical.get("diagnosis_date") or canonical.get("date_of_diagnosis")
        if history_is_empty and _is_present(baseline_psa_value) and _is_present(diagnosis_date):
            try:
                baseline_psa_numeric = float(str(baseline_psa_value).replace(",", "."))
                if baseline_psa_numeric > 0:
                    auto_baseline_point = {
                        "sample_date": str(diagnosis_date),
                        "psa_value": baseline_psa_numeric,
                        "assay_type": "desconocido",
                        "context": "pretratamiento",
                        "source": "auto-baseline (Faubot LXIV #63A)",
                    }
                    canonical["psa_history"] = [auto_baseline_point]
                    canonical["ape_history"] = [auto_baseline_point]
            except (ValueError, TypeError):
                # Si baseline_psa no es numérico válido, no auto-crear
                pass

        # Faubot 2026-04-25 (LXV) — Auditoría #63B
        # Treatment history timeline: si el intake captura
        # `most_recent_prior_line_*` fields, sintetizar entradas en
        # `treatments[]` para alimentar bandas de tratamiento históricas
        # en la torre de vigilancia APE (psa_line_monitor.py).
        # Esto permite drill-down per treatment line en el chart sin
        # requerir captura visita-a-visita previa.
        existing_treatments = canonical.get("treatments")
        treatments_is_empty = (
            existing_treatments is None
            or existing_treatments == ""
            or existing_treatments == []
            or existing_treatments == "[]"
        )
        prior_drug_scheme = canonical.get("most_recent_prior_line_drug_scheme")
        prior_start_date = canonical.get("most_recent_prior_line_start_date")
        prior_end_date = canonical.get("most_recent_prior_line_end_date")
        prior_reason = canonical.get("most_recent_prior_line_reason_for_change")
        prior_best_response = canonical.get("most_recent_prior_line_best_psa_response_pct")
        prior_lines_count = canonical.get("prior_treatment_lines_count")
        synthesized_treatments: list[dict[str, Any]] = []
        if _is_present(prior_drug_scheme) and _is_present(prior_start_date):
            try:
                prior_line_number = int(prior_lines_count) if _is_present(prior_lines_count) else 1
            except (ValueError, TypeError):
                prior_line_number = 1
            prior_entry = {
                "start_date": str(prior_start_date),
                "drug_scheme": normalize_regimen_code(prior_drug_scheme),
                "line_of_therapy_number": str(prior_line_number),
                "source": "auto-treatment-history (Faubot LXV #63B)",
            }
            if _is_present(prior_end_date):
                prior_entry["end_date"] = str(prior_end_date)
            if _is_present(prior_reason):
                prior_entry["reason_for_change"] = str(prior_reason)
            if _is_present(prior_best_response):
                try:
                    prior_entry["best_psa_response_pct"] = float(
                        str(prior_best_response).replace(",", ".")
                    )
                except (ValueError, TypeError):
                    pass
            synthesized_treatments.append(prior_entry)

        # Sintetizar entrada actual si hay drug_scheme + (line_of_therapy_number
        # OR diagnosis_date como fallback de start_date). El extractor de
        # bandas requiere start_date para construir la banda actual.
        current_drug_scheme = canonical.get("drug_scheme")
        current_line_number = canonical.get("line_of_therapy_number")
        if _is_present(current_drug_scheme):
            current_start_candidate = (
                prior_end_date
                or canonical.get("current_treatment_start_date")
                or diagnosis_date
            )
            if _is_present(current_start_candidate):
                try:
                    current_line_int = (
                        int(current_line_number)
                        if _is_present(current_line_number)
                        else (
                            int(prior_lines_count) + 1
                            if _is_present(prior_lines_count)
                            else 1
                        )
                    )
                except (ValueError, TypeError):
                    current_line_int = 1
                current_entry = {
                    "start_date": str(current_start_candidate),
                    "drug_scheme": normalize_regimen_code(current_drug_scheme),
                    "line_of_therapy_number": str(current_line_int),
                    "source": "auto-treatment-current (Faubot LXV #63B)",
                }
                line_context = canonical.get("line_of_therapy_context")
                if _is_present(line_context):
                    current_entry["line_of_therapy_context"] = str(line_context)
                synthesized_treatments.append(current_entry)

        # Solo aplicar si treatments[] está vacío (no sobrescribir captura
        # visita-a-visita previa). Si hay treatments persistidos, ellos
        # tienen prioridad.
        if treatments_is_empty and synthesized_treatments:
            canonical["treatments"] = synthesized_treatments

        # Faubot 2026-04-25 (LXVI) — Auditoría #63C
        # Multi-row prior treatment lines: si el intake usa el widget
        # multi-row (`prior_treatment_lines_history` JSON array), expandir
        # treatments[] con las N líneas previas + la actual. Esto reemplaza
        # la sintetización anterior (que solo capturaba la "más reciente
        # prior line") por una historia completa N líneas.
        prior_lines_history = canonical.get("prior_treatment_lines_history")
        if isinstance(prior_lines_history, str):
            # Widget produce JSON string; parsear si presente
            try:
                import json
                parsed = json.loads(prior_lines_history)
                if isinstance(parsed, list):
                    prior_lines_history = parsed
                else:
                    prior_lines_history = None
            except (ValueError, TypeError):
                prior_lines_history = None

        if (
            isinstance(prior_lines_history, list)
            and prior_lines_history
            and treatments_is_empty
        ):
            multi_synthesized: list[dict[str, Any]] = []
            for idx, line_entry in enumerate(prior_lines_history):
                if not isinstance(line_entry, dict):
                    continue
                if not _is_present(line_entry.get("start_date")):
                    continue
                if not _is_present(line_entry.get("drug_scheme")):
                    continue
                multi_entry = {
                    "start_date": str(line_entry.get("start_date")),
                    "drug_scheme": normalize_regimen_code(line_entry.get("drug_scheme")),
                    "line_of_therapy_number": str(
                        line_entry.get("line_of_therapy_number") or (idx + 1)
                    ),
                    "source": "auto-treatment-multirow (Faubot LXVI #63C)",
                }
                if _is_present(line_entry.get("end_date")):
                    multi_entry["end_date"] = str(line_entry.get("end_date"))
                if _is_present(line_entry.get("line_of_therapy_context")):
                    multi_entry["line_of_therapy_context"] = str(
                        line_entry.get("line_of_therapy_context")
                    )
                if _is_present(line_entry.get("reason_for_change")):
                    multi_entry["reason_for_change"] = str(
                        line_entry.get("reason_for_change")
                    )
                if _is_present(line_entry.get("best_psa_response_pct")):
                    try:
                        multi_entry["best_psa_response_pct"] = float(
                            str(line_entry.get("best_psa_response_pct")).replace(",", ".")
                        )
                    except (ValueError, TypeError):
                        pass
                multi_synthesized.append(multi_entry)

            # Agregar línea actual al final si hay drug_scheme
            if _is_present(canonical.get("drug_scheme")):
                last_end = (
                    multi_synthesized[-1].get("end_date") if multi_synthesized else None
                )
                current_start_candidate = (
                    last_end
                    or canonical.get("current_treatment_start_date")
                    or diagnosis_date
                )
                if _is_present(current_start_candidate):
                    next_line_num = (
                        len(multi_synthesized) + 1
                        if not _is_present(canonical.get("line_of_therapy_number"))
                        else canonical.get("line_of_therapy_number")
                    )
                    multi_current = {
                        "start_date": str(current_start_candidate),
                        "drug_scheme": normalize_regimen_code(canonical.get("drug_scheme")),
                        "line_of_therapy_number": str(next_line_num),
                        "source": "auto-treatment-multirow-current (Faubot LXVI #63C)",
                    }
                    if _is_present(canonical.get("line_of_therapy_context")):
                        multi_current["line_of_therapy_context"] = str(
                            canonical.get("line_of_therapy_context")
                        )
                    multi_synthesized.append(multi_current)

            if multi_synthesized:
                # Multi-row tiene prioridad sobre sintetización single-prior
                # (es más informativa y completa)
                canonical["treatments"] = multi_synthesized

        return canonical
