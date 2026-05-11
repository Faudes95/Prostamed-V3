from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from clinical_scores import (
    calculate_capra_s,
    capra_score,
    damico_classification,
    erspc_risk_calculator,
    kattan_organ_confined,
    mskcc_bcr_post_rp,
    partin_tables,
)

from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
from prostanet.shared.advanced_support_catalog import (
    MINI_COG_OPTION_LABELS,
    MINI_COG_OPTIONS,
    PRO_BAND_OPTIONS,
    pro_band_label_map,
)


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POST_RP_STATES = {"post_prostatectomy", "recurrence_bcr"}

FIELDTYPE_NUMBER = "number"
FIELDTYPE_SELECT = "select"

FIELD_REGISTRY: dict[str, dict[str, Any]] = {
    "dre_suspicious": {
        "label": "Tacto rectal sospechoso",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "help_text": "0 = no sospechoso, 1 = sospechoso.",
        "required_by_context": "diagnostic",
        "intake_priority": 1,
    },
    "prior_biopsy_count": {
        "label": "Número de biopsias previas",
        "field_type": FIELDTYPE_NUMBER,
        "required_by_context": "diagnostic",
        "intake_priority": 1,
    },
    "life_expectancy_years": {
        "label": "Esperanza de vida",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "años",
        "required_by_context": "localized",
        "intake_priority": 1,
    },
    "num_cores_positive": {
        "label": "Cilindros positivos",
        "field_type": FIELDTYPE_NUMBER,
        "required_by_context": "localized",
        "intake_priority": 2,
    },
    "confirmatory_biopsy_done": {
        "label": "Biopsia confirmatoria realizada",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "help_text": "0 = no realizada, 1 = realizada.",
        "required_by_context": "localized",
        "intake_priority": 2,
    },
    "mri_interval_months": {
        "label": "Intervalo de MRI multiparamétrica",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "meses",
        "required_by_context": "localized",
        "intake_priority": 2,
    },
    "total_cores": {
        "label": "Cilindros totales",
        "field_type": FIELDTYPE_NUMBER,
        "required_by_context": "localized",
        "intake_priority": 2,
    },
    "local_treatment_consideration": {
        "label": "Tratamiento local considerado",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "both", "radical_prostatectomy", "radical_radiotherapy", "active_surveillance", "undecided"],
        "help_text": "Define si la prostatectomía radical realmente está en consideración para mostrar nomogramas quirúrgicos.",
        "required_by_context": "localized",
        "intake_priority": 2,
    },
    "psa": {
        "label": "PSA",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "ng/mL",
        "required_by_context": "all",
        "intake_priority": 1,
    },
    "psa_history": {
        "label": "Serie longitudinal de PSA / APE",
        "field_type": "psa_history",
        "help_text": "Capture mediciones múltiples con fecha, contexto y línea terapéutica cuando aplique.",
        "required_by_context": "all",
        "intake_priority": 1,
    },
    "testosterone": {
        "label": "Testosterona",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "ng/dL",
        "required_by_context": "advanced",
        "intake_priority": 1,
    },
    "testosterone_history": {
        "label": "Serie longitudinal de testosterona",
        "field_type": "testosterone_history",
        "help_text": "Capture mediciones múltiples con fecha, unidad, contexto y línea terapéutica cuando aplique.",
        "required_by_context": "advanced",
        "intake_priority": 1,
    },
    "weight_kg": {
        "label": "Peso",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "kg",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "height_cm": {
        "label": "Estatura",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "cm",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "bmi_current": {
        "label": "BMI",
        "field_type": FIELDTYPE_NUMBER,
        "help_text": "Se calcula automáticamente a partir de peso y estatura.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "weight_loss_6m_kg": {
        "label": "Pérdida ponderal 6 meses",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "kg",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "weight_loss_6m_pct": {
        "label": "Pérdida ponderal 6 meses",
        "field_type": FIELDTYPE_NUMBER,
        "unit": "%",
        "help_text": "Campo legacy; el UI longitudinal nuevo prioriza captura en kg y deriva este porcentaje automáticamente.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "calcium_vitd_started": {
        "label": "Calcio / vitamina D iniciados",
        "field_type": FIELDTYPE_SELECT,
        "options": ["0", "1"],
        "help_text": "0 = no iniciados, 1 = iniciados.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "bone_protection_started": {
        "label": "Protección ósea iniciada",
        "field_type": FIELDTYPE_SELECT,
        "options": ["0", "1"],
        "help_text": "0 = no iniciada, 1 = iniciada.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "mini_cog_score": {
        "label": "Mini-Cog",
        "field_type": FIELDTYPE_SELECT,
        "options": [{"value": option, "label": MINI_COG_OPTION_LABELS.get(option, option)} for option in MINI_COG_OPTIONS],
        "help_text": "Seleccione el score total de Mini-Cog con su interpretación clínica.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "eq5d_vas_band": {
        "label": "EQ-5D VAS basal",
        "field_type": FIELDTYPE_SELECT,
        "options": [{"value": option, "label": pro_band_label_map("eq5d_vas_band").get(option, option)} for option in PRO_BAND_OPTIONS["eq5d_vas_band"]],
        "help_text": "Seleccione la banda clínica del EQ-5D; el valor numérico representativo se deriva automáticamente si no se captura uno exacto.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "eq5d_vas": {
        "label": "EQ-5D VAS",
        "field_type": FIELDTYPE_NUMBER,
        "help_text": "Valor canónico de EQ-5D VAS. Si se selecciona una banda, este valor puede derivarse automáticamente.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "fact_p_total_band": {
        "label": "FACT-P basal",
        "field_type": FIELDTYPE_SELECT,
        "options": [{"value": option, "label": pro_band_label_map("fact_p_total_band").get(option, option)} for option in PRO_BAND_OPTIONS["fact_p_total_band"]],
        "help_text": "Seleccione la banda clínica del FACT-P; el valor numérico representativo se deriva automáticamente si no se captura uno exacto.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "fact_p_total": {
        "label": "FACT-P total",
        "field_type": FIELDTYPE_NUMBER,
        "help_text": "Valor canónico de FACT-P. Si se selecciona una banda, este valor puede derivarse automáticamente.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "bpi_worst_pain_band": {
        "label": "BPI dolor peor basal",
        "field_type": FIELDTYPE_SELECT,
        "options": [{"value": option, "label": pro_band_label_map("bpi_worst_pain_band").get(option, option)} for option in PRO_BAND_OPTIONS["bpi_worst_pain_band"]],
        "help_text": "Seleccione la severidad clínica del dolor peor basal; el valor numérico representativo se deriva automáticamente si no se captura uno exacto.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "bpi_worst_pain": {
        "label": "BPI peor dolor",
        "field_type": FIELDTYPE_NUMBER,
        "help_text": "Valor canónico de BPI peor dolor. Si se selecciona una banda, este valor puede derivarse automáticamente.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "fatigue_score_band": {
        "label": "Fatiga basal",
        "field_type": FIELDTYPE_SELECT,
        "options": [{"value": option, "label": pro_band_label_map("fatigue_score_band").get(option, option)} for option in PRO_BAND_OPTIONS["fatigue_score_band"]],
        "help_text": "Seleccione la banda clínica de fatiga; el valor numérico representativo se deriva automáticamente si no se captura uno exacto.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "fatigue_score": {
        "label": "Fatiga basal",
        "field_type": FIELDTYPE_NUMBER,
        "help_text": "Valor canónico de fatiga. Si se selecciona una banda, este valor puede derivarse automáticamente.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "weak_grip": {
        "label": "Fuerza de prensión baja",
        "field_type": FIELDTYPE_SELECT,
        "options": [
            {"value": "", "label": "--"},
            {"value": "0", "label": "Ausente"},
            {"value": "1", "label": "Presente"},
        ],
        "help_text": "Alimenta el fenotipo de Fried y la aptitud terapéutica global.",
        "required_by_context": "advanced",
        "intake_priority": 2,
    },
    "clinical_tstage": {
        "label": "T clínico",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "T1c", "T2a", "T2b", "T2c", "T3a", "T3b", "T4"],
        "required_by_context": "localized",
        "intake_priority": 1,
    },
    "gleason_primary": {
        "label": "Gleason primario",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "3", "4", "5"],
        "required_by_context": "localized",
        "intake_priority": 1,
    },
    "gleason_secondary": {
        "label": "Gleason secundario",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "3", "4", "5"],
        "required_by_context": "localized",
        "intake_priority": 1,
    },
    "isup_grade": {
        "label": "ISUP / Grade Group",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "1", "2", "3", "4", "5"],
        "required_by_context": "localized",
        "intake_priority": 1,
    },
    "pathology_gleason_primary": {
        "label": "Gleason patológico primario",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "3", "4", "5"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "pathology_gleason_secondary": {
        "label": "Gleason patológico secundario",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "3", "4", "5"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "pathologic_stage": {
        "label": "Estadio patológico",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "pT2", "pT3a", "pT3b", "pT4", "pN1"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "surgical_margin": {
        "label": "Márgenes quirúrgicos",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "ece_status": {
        "label": "Extensión extracapsular",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "svi_status": {
        "label": "Invasión de vesículas seminales",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
    "lni_status": {
        "label": "Invasión ganglionar",
        "field_type": FIELDTYPE_SELECT,
        "options": ["", "0", "1"],
        "required_by_context": "post_rp",
        "intake_priority": 1,
    },
}

SCORE_REQUIREMENTS = {
    "erspc": ["psa", "dre_suspicious"],
    "capra": ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"],
    "briganti": ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"],
    "damico": ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary"],
    "predict_prostate": ["psa", "clinical_tstage", "isup_grade", "life_expectancy_years"],
    "mskcc_preop": ["psa", "clinical_tstage", "isup_grade"],
    "partin": ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary"],
    "capra_s": ["psa", "gleason_primary", "gleason_secondary", "pathologic_stage", "surgical_margin", "ece_status", "svi_status", "lni_status"],
    "mskcc_bcr_post_rp": ["psa", "pathology_gleason_primary", "pathology_gleason_secondary", "surgical_margin", "ece_status", "svi_status", "lni_status"],
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


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


def _normalize_bool_like(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positive", "positivo"}


def _parse_date(value: Any) -> datetime | None:
    if not _is_present(value):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _calculate_age_from_dob(dob: str | None) -> int | None:
    if not dob or len(str(dob)) < 10:
        return None
    try:
        year = int(str(dob)[0:4])
        month = int(str(dob)[5:7])
        day = int(str(dob)[8:10])
    except ValueError:
        return None
    from datetime import date

    today = date.today()
    age = today.year - year - ((today.month, today.day) < (month, day))
    return age if age >= 0 else None


def _tool_card(
    *,
    tool_key: str,
    title: str,
    clinical_scope: str,
    status: str,
    fidelity: str,
    primary_result: str,
    meaning: str,
    clinical_relation: str,
    inputs_used: list[str] | None = None,
    missing_inputs: list[str] | None = None,
    required_at_intake: bool = False,
    source_summary: str = "",
    badge: str = "",
    missing_input_keys: list[str] | None = None,
    result_data: dict[str, Any] | None = None,
    group_key: str = "",
) -> dict[str, Any]:
    return {
        "tool_key": tool_key,
        "title": title,
        "clinical_scope": clinical_scope,
        "status": status,
        "fidelity": fidelity,
        "primary_result": primary_result,
        "meaning": meaning,
        "clinical_relation": clinical_relation,
        "inputs_used": inputs_used or [],
        "missing_inputs": missing_inputs or [],
        "required_at_intake": required_at_intake,
        "source_summary": source_summary,
        "badge": badge or fidelity,
        "missing_input_keys": missing_input_keys or [],
        "result_data": result_data or {},
        "group_key": group_key,
    }


def _field_label(field_name: str) -> str:
    if field_name == "psa":
        return "PSA"
    return (FIELD_REGISTRY.get(field_name) or {}).get("label", field_name.replace("_", " "))


def _stringify_inputs(payload: dict[str, Any], fields: list[str]) -> list[str]:
    items = []
    for field in fields:
        value = payload.get(field)
        if not _is_present(value):
            continue
        items.append(f"{_field_label(field)}: {value}")
    return items


def _score_missing_inputs(payload: dict[str, Any], score_key: str) -> list[str]:
    missing: list[str] = []
    for field in SCORE_REQUIREMENTS.get(score_key, []):
        if field == "psa" and _is_present(payload.get("baseline_psa")):
            continue
        if field == "num_cores_positive" and _is_present(payload.get("positive_cores")):
            continue
        if field in {"gleason_primary", "gleason_secondary"} and _is_present(payload.get(f"pathology_{field}")):
            continue
        if score_key == "damico" and field in {"gleason_primary", "gleason_secondary"} and _is_present(payload.get("isup_grade")):
            continue
        if field == "age" and (_is_present(payload.get("age")) or _is_present(payload.get("dob"))):
            continue
        if not _is_present(payload.get(field)):
            missing.append(field)
    if score_key == "capra":
        positive = _safe_int(payload.get("num_cores_positive"))
        total = _safe_int(payload.get("total_cores"))
        if not _is_present(payload.get("pct_cores_positive")) and (positive is None or total is None or total <= 0):
            if "num_cores_positive" not in missing:
                missing.append("num_cores_positive")
            if "total_cores" not in missing:
                missing.append("total_cores")
    return missing


def _normalize_payload(
    *,
    patient: dict[str, Any] | None = None,
    raw_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assessment_input = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    merged = merge_record_into_assessment_payload(assessment_input, patient or {})
    baseline = (patient or {}).get("baseline") or {}
    surgery = (patient or {}).get("surgery") or {}
    identity = (patient or {}).get("identity") or {}

    if not _is_present(merged.get("psa")):
        merged["psa"] = merged.get("baseline_psa") or baseline.get("baseline_psa")
    if not _is_present(merged.get("num_cores_positive")) and _is_present(merged.get("positive_cores")):
        merged["num_cores_positive"] = merged.get("positive_cores")
    if not _is_present(merged.get("age")):
        merged["age"] = _calculate_age_from_dob(identity.get("dob")) or _calculate_age_from_dob(merged.get("dob"))
    if not _is_present(merged.get("pct_cores_positive")):
        positive = _safe_int(merged.get("num_cores_positive"))
        total = _safe_int(merged.get("total_cores"))
        if positive is not None and total not in (None, 0):
            merged["pct_cores_positive"] = positive / total
    if not _is_present(merged.get("pathology_gleason_primary")) and _is_present(surgery.get("pathological_gleason_primary")):
        merged["pathology_gleason_primary"] = surgery.get("pathological_gleason_primary")
    if not _is_present(merged.get("pathology_gleason_secondary")) and _is_present(surgery.get("pathological_gleason_secondary")):
        merged["pathology_gleason_secondary"] = surgery.get("pathological_gleason_secondary")
    if not _is_present(merged.get("pathologic_stage")) and _is_present(surgery.get("pathological_stage")):
        merged["pathologic_stage"] = surgery.get("pathological_stage")
    if not _is_present(merged.get("surgical_margin")) and _is_present(surgery.get("surgical_margin_status")):
        merged["surgical_margin"] = int(bool(surgery.get("surgical_margin_status")))
    if not _is_present(merged.get("ece_status")) and _is_present(surgery.get("ece_pathological")):
        merged["ece_status"] = int(bool(surgery.get("ece_pathological")))
    if not _is_present(merged.get("svi_status")) and _is_present(surgery.get("svi_pathological")):
        merged["svi_status"] = int(bool(surgery.get("svi_pathological")))
    if not _is_present(merged.get("lni_status")) and _is_present(surgery.get("lni_pathological")):
        merged["lni_status"] = int(bool(surgery.get("lni_pathological")))
    pathologic_stage = str(merged.get("pathologic_stage") or "").upper()
    if pathologic_stage.startswith("PT3A") and not _is_present(merged.get("ece_status")):
        merged["ece_status"] = 1
    if pathologic_stage.startswith("PT3B") and not _is_present(merged.get("svi_status")):
        merged["svi_status"] = 1
    if pathologic_stage == "PN1" and not _is_present(merged.get("lni_status")):
        merged["lni_status"] = 1
    if not _is_present(merged.get("prior_biopsy_count")) and patient:
        merged["prior_biopsy_count"] = len((patient.get("biopsies") or []))
    return merged


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return None


def _treatment_consideration(payload: dict[str, Any], assessment_result: dict[str, Any] | None = None) -> dict[str, Any]:
    explicit = str(payload.get("local_treatment_consideration") or "").strip()
    if explicit == "radical_prostatectomy":
        return {"rp": True, "rt": False, "known": True}
    if explicit == "radical_radiotherapy":
        return {"rp": False, "rt": True, "known": True}
    if explicit == "both":
        return {"rp": True, "rt": True, "known": True}
    if explicit in {"active_surveillance", "undecided"}:
        return {"rp": False, "rt": False, "known": True}

    names = []
    for item in (assessment_result or {}).get("eligible_treatments", []) or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(str(item.get("name") or ""))
    lowered = " | ".join(names).lower()
    rp = any(token in lowered for token in ("prostatect", "prostatectom", "rp "))
    rt = any(token in lowered for token in ("radiot", "ebrt", "braqui", "sbrt"))
    return {"rp": rp, "rt": rt, "known": bool(names)}


def _has_definitive_local_treatment(patient: dict[str, Any] | None, state: str) -> bool:
    if state in POST_RP_STATES:
        return True
    if not patient:
        return False
    return bool((patient.get("surgery") or {}).get("surgery_date") or (patient.get("radiation") or []))


def _is_metastatic(payload: dict[str, Any], state: str) -> bool:
    if state not in DIAGNOSTIC_STATES | LOCALIZED_STATES | POST_RP_STATES:
        return True
    m_stage = str(payload.get("m_substage_resolved") or payload.get("metastasis_site") or "").upper()
    return bool(m_stage and m_stage not in {"M0", "TX", "MX", "NO APLICA"})


def _latest_biopsy(patient: dict[str, Any]) -> dict[str, Any]:
    biopsies = patient.get("biopsies") or []
    if not biopsies:
        return {}
    ordered = sorted(biopsies, key=lambda item: str(item.get("biopsy_date") or ""), reverse=True)
    return ordered[0]


def _first_biopsy(patient: dict[str, Any]) -> dict[str, Any]:
    biopsies = patient.get("biopsies") or []
    if not biopsies:
        return {}
    ordered = sorted(biopsies, key=lambda item: str(item.get("biopsy_date") or ""))
    return ordered[0]


def _genomic_reports(patient: dict[str, Any]) -> list[dict[str, Any]]:
    reports = [dict(item) for item in (patient.get("genomic_reports") or []) if isinstance(item, dict)]
    if reports:
        return reports
    genomics = patient.get("genomics") or {}
    return [dict(genomics)] if genomics else []


def _find_genomic_report(patient: dict[str, Any], test_type: str) -> dict[str, Any]:
    for report in _genomic_reports(patient):
        report_type = str(report.get("test_type") or "").lower()
        if test_type.lower() in report_type:
            return report
    return {}


def _classifier_result_from_assessment(raw_assessment: dict[str, Any] | None, classifier: str) -> str:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    if str(payload.get("genomic_classifier") or "").lower().startswith(classifier.lower()):
        return str(payload.get("genomic_classifier_result") or "").strip()
    return ""


def _capra_meaning(risk_group: str) -> str:
    mapping = {
        "BAJO": "Riesgo bajo de recurrencia bioquímica después de tratamiento radical.",
        "INTERMEDIO": "Riesgo intermedio de recurrencia bioquímica después de tratamiento radical.",
        "ALTO": "Riesgo alto de recurrencia bioquímica después de tratamiento radical.",
    }
    return mapping.get(str(risk_group or "").upper(), "Estratifica riesgo de recurrencia bioquímica en enfermedad localizada.")


def _damico_meaning(risk_group: str) -> str:
    mapping = {
        "BAJO": "Se relaciona con riesgo bajo de recurrencia bioquímica y enfermedad órgano-confinada más probable.",
        "INTERMEDIO": "Se relaciona con riesgo intermedio de recurrencia bioquímica y heterogeneidad biológica que exige refinadores adicionales.",
        "ALTO": "Se relaciona con riesgo alto de recurrencia bioquímica y mayor probabilidad de enfermedad biológicamente agresiva.",
    }
    return mapping.get(str(risk_group or "").upper(), "Clasificación pronóstica basal para enfermedad localizada.")


def _capra_s_meaning(risk_group: str) -> str:
    mapping = {
        "BAJO": "Riesgo bajo de recurrencia bioquímica posprostatectomía.",
        "INTERMEDIO": "Riesgo intermedio de recurrencia bioquímica posprostatectomía.",
        "ALTO": "Riesgo alto de recurrencia bioquímica posprostatectomía.",
    }
    return mapping.get(str(risk_group or "").upper(), "Refina riesgo posoperatorio y necesidad de vigilancia o rescate temprano.")


def _erspc_card(payload: dict[str, Any], *, rebiopsy: bool) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "erspc")
    if rebiopsy and "prior_biopsy_count" not in missing and not _is_present(payload.get("prior_biopsy_count")):
        missing.append("prior_biopsy_count")
    if missing:
        return _tool_card(
            tool_key="erspc",
            title="ERSPC Risk Calculator",
            clinical_scope="Sospecha diagnóstica / rebiopsia",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="Faltan datos para correr ERSPC",
            meaning="Estima riesgo de cáncer y de cáncer clínicamente significativo en biopsia.",
            clinical_relation="Se relaciona con probabilidad de detección y de cáncer de alto grado antes de confirmar diagnóstico.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            source_summary="Calculadora diagnóstica contextual; si se completa, el perfil muestra el riesgo estimado y su significado.",
            group_key="diagnostic_risk",
        )
    result = erspc_risk_calculator(
        {
            "age": payload.get("age"),
            "psa": payload.get("psa") or payload.get("baseline_psa"),
            "dre_abnormal": _normalize_bool_like(payload.get("dre_suspicious")),
            "prostate_volume_ml": payload.get("prostate_volume_ml"),
            "prior_biopsy": _safe_int(payload.get("prior_biopsy_count")) not in (None, 0),
            "family_history": bool(payload.get("family_history_detail")),
        }
    )
    return _tool_card(
        tool_key="erspc",
        title="ERSPC Risk Calculator",
        clinical_scope="Sospecha diagnóstica / rebiopsia",
        status="calculated",
        fidelity="proxy_estimate",
        primary_result=f"{result.get('any_cancer_probability_pct')}% cáncer / {result.get('high_grade_probability_pct')}% alto grado",
        meaning=result.get("recommendation") or "Estimación referencial de riesgo prebiopsia.",
        clinical_relation="Se relaciona con decisión de biopsia o rebiopsia y con riesgo de cáncer clínicamente significativo.",
        inputs_used=_stringify_inputs(payload, ["psa", "dre_suspicious", "prior_biopsy_count", "prostate_volume_ml"]),
        source_summary="Estimación referencial local basada en modelo ERSPC/PCPT simplificado; úsela como apoyo y no como sustituto de guías.",
        badge="Estimación referencial",
        result_data=result,
        group_key="diagnostic_risk",
    )


def _capra_card(payload: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "capra")
    if missing:
        return _tool_card(
            tool_key="capra",
            title="CAPRA" if not historical else "CAPRA basal",
            clinical_scope="Enfermedad localizada candidata a tratamiento radical",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="CAPRA no calculable aún",
            meaning="Estratifica riesgo biológico pretratamiento.",
            clinical_relation="Se relaciona con riesgo de recurrencia bioquímica tras tratamiento radical primario.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            group_key="baseline_risk",
        )
    result = capra_score(payload)
    if result.get("score") is None:
        missing = list(dict.fromkeys(result.get("missing_inputs") or missing))
        return _tool_card(
            tool_key="capra",
            title="CAPRA" if not historical else "CAPRA basal",
            clinical_scope="Enfermedad localizada candidata a tratamiento radical",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="CAPRA pendiente de biopsia estructurada",
            meaning="Requiere patología basal suficiente antes de estratificar riesgo.",
            clinical_relation="No debe calcularse con Gleason implícito o carga de cilindros no documentada.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            group_key="baseline_risk",
        )
    return _tool_card(
        tool_key="capra",
        title="CAPRA" if not historical else "CAPRA basal",
        clinical_scope="Enfermedad localizada candidata a tratamiento radical",
        status="calculated",
        fidelity="calculated",
        primary_result=f"{result.get('score')}/10 · {result.get('risk_group')}",
        meaning=_capra_meaning(result.get("risk_group")),
        clinical_relation=f"Libre de recurrencia bioquímica estimada a 3 años: {result.get('bcr_free_3y')}; a 5 años: {result.get('bcr_free_5y')}.",
        inputs_used=_stringify_inputs(payload, ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"]),
        source_summary="Calculado localmente con datos estructurados del caso.",
        badge="Calculado",
        result_data=result,
        group_key="baseline_risk",
    )


def _damico_card(payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "damico")
    if missing:
        return _tool_card(
            tool_key="damico",
            title="D'Amico",
            clinical_scope="Enfermedad localizada no tratada",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="D'Amico no calculable aún",
            meaning="Clasifica riesgo clínico basal en localizado antes de tratamiento definitivo.",
            clinical_relation="Se relaciona con riesgo basal de recurrencia bioquímica y con cohortes clásicas de localizado.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            source_summary="Clasificador clínico basal integrado localmente con PSA, estadio T y Gleason/ISUP.",
            group_key="baseline_risk",
        )
    result = damico_classification(payload)
    return _tool_card(
        tool_key="damico",
        title="D'Amico",
        clinical_scope="Enfermedad localizada no tratada",
        status="calculated",
        fidelity="calculated",
        primary_result=str(result.get("risk_group") or ""),
        meaning=_damico_meaning(str(result.get("risk_group") or "")),
        clinical_relation=f"Libre de recurrencia bioquímica estimada a 5 años: {result.get('bcr_free_5y')}; a 10 años: {result.get('bcr_free_10y')}.",
        inputs_used=_stringify_inputs(payload, ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "isup_grade"]),
        source_summary="Calculado localmente con datos estructurados del caso.",
        badge="Calculado",
        result_data=result,
        group_key="baseline_risk",
    )


def _predict_card(payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "predict_prostate")
    if missing:
        return _tool_card(
            tool_key="predict_prostate",
            title="PREDICT Prostate",
            clinical_scope="Cáncer no metastásico antes de tratamiento definitivo",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="Aún faltan entradas para PREDICT Prostate",
            meaning="Estima supervivencia y beneficio absoluto del tratamiento en enfermedad no metastásica.",
            clinical_relation="Se relaciona con counseling de beneficio absoluto entre observación, vigilancia activa y tratamiento local.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            source_summary="No se calcula localmente en esta versión; se prepara el caso para correr la calculadora externa con trazabilidad.",
            group_key="baseline_risk",
        )
    return _tool_card(
        tool_key="predict_prostate",
        title="PREDICT Prostate",
        clinical_scope="Cáncer no metastásico antes de tratamiento definitivo",
        status="ready",
        fidelity="ready_missing_inputs",
        primary_result="Listo para correrse con las entradas actuales",
        meaning="Permite cuantificar supervivencia estimada y beneficio absoluto del tratamiento definitivo.",
        clinical_relation="Se relaciona con decisión compartida pretratamiento en enfermedad localizada o regional no metastásica.",
        inputs_used=_stringify_inputs(payload, ["psa", "clinical_tstage", "isup_grade", "life_expectancy_years"]),
        source_summary="Herramienta externa preparada con datos estructurados suficientes.",
        badge="Listo",
        result_data={"ready": True},
        group_key="baseline_risk",
    )


def _mskcc_card(payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "mskcc_preop")
    if missing:
        return _tool_card(
            tool_key="mskcc_preop",
            title="MSKCC pre-radical prostatectomy",
            clinical_scope="Counseling preoperatorio",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="Nomograma MSKCC preoperatorio incompleto",
            meaning="Estima probabilidad de enfermedad órgano-confinada antes de prostatectomía radical.",
            clinical_relation="Se relaciona con counseling quirúrgico preoperatorio.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            group_key="preop_nomogram",
        )
    result = kattan_organ_confined(payload)
    return _tool_card(
        tool_key="mskcc_preop",
        title="MSKCC pre-radical prostatectomy",
        clinical_scope="Counseling preoperatorio",
        status="calculated",
        fidelity="calculated",
        primary_result=result.get("probabilidad_organo_confinado", "N/D"),
        meaning=result.get("interpretacion", "Probabilidad preoperatoria de órgano confinado."),
        clinical_relation="Se relaciona con expectativa de organo-confinamiento antes de prostatectomía radical.",
        inputs_used=_stringify_inputs(payload, ["psa", "clinical_tstage", "isup_grade"]),
        source_summary="Nomograma preoperatorio integrado como cálculo local de apoyo.",
        badge="Calculado",
        result_data=result,
        group_key="preop_nomogram",
    )


def _partin_card(payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "partin")
    if missing:
        return _tool_card(
            tool_key="partin",
            title="Tablas de Partin",
            clinical_scope="Counseling quirúrgico preoperatorio",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="Partin aún no calculable",
            meaning="Estima órgano confinado, extensión extracapsular, SVI y riesgo ganglionar.",
            clinical_relation="Se relaciona con expectativa patológica preoperatoria cuando la prostatectomía radical está en consideración.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            group_key="preop_nomogram",
        )
    result = partin_tables(payload)
    return _tool_card(
        tool_key="partin",
        title="Tablas de Partin",
        clinical_scope="Counseling quirúrgico preoperatorio",
        status="calculated",
        fidelity="proxy_estimate",
        primary_result=f"Órgano confinado {result.get('oc_prob')}%",
        meaning=f"ECE {result.get('ece_prob')}% · SVI {result.get('svi_prob')}% · LNI {result.get('lni_prob')}%.",
        clinical_relation="Se relaciona con patología final esperada antes de cirugía.",
        inputs_used=_stringify_inputs(payload, ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary"]),
        source_summary="Se muestra como estimación referencial porque la implementación local es aproximada.",
        badge="Estimación referencial",
        result_data=result,
        group_key="preop_nomogram",
    )


def _capra_s_card(payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "capra_s")
    if missing:
        return _tool_card(
            tool_key="capra_s",
            title="CAPRA-S",
            clinical_scope="Post-prostatectomía radical",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="CAPRA-S incompleto",
            meaning="Estratifica riesgo de recurrencia bioquímica posprostatectomía.",
            clinical_relation="Se relaciona con vigilancia estrecha, rescate y riesgo posoperatorio.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            group_key="postop_prognosis",
        )
    capra_payload = dict(payload)
    if _is_present(payload.get("pathology_gleason_primary")):
        capra_payload["gleason_primary"] = payload.get("pathology_gleason_primary")
    if _is_present(payload.get("pathology_gleason_secondary")):
        capra_payload["gleason_secondary"] = payload.get("pathology_gleason_secondary")
    result = calculate_capra_s(capra_payload)
    return _tool_card(
        tool_key="capra_s",
        title="CAPRA-S",
        clinical_scope="Post-prostatectomía radical",
        status="calculated",
        fidelity="calculated",
        primary_result=f"{result.get('score')}/12 · {result.get('risk_group')}",
        meaning=_capra_s_meaning(result.get("risk_group")),
        clinical_relation="Se relaciona con riesgo de recurrencia bioquímica posoperatoria y urgencia de rescate temprano.",
        inputs_used=_stringify_inputs(payload, ["psa", "pathologic_stage", "surgical_margin", "ece_status", "svi_status", "lni_status"]),
        source_summary="Calculado localmente con patología posprostatectomía.",
        badge="Calculado",
        result_data=result,
        group_key="postop_prognosis",
    )


def _post_rp_mskcc_allowed(patient: dict[str, Any], payload: dict[str, Any]) -> bool:
    surgery = patient.get("surgery") or {}
    surgery_date = _parse_date(_first_nonempty(surgery.get("surgery_date"), payload.get("surgery_date")))
    if not surgery_date:
        return False

    for item in patient.get("radiation") or []:
        start_date = _parse_date(item.get("start_date") or item.get("radiation_start_date"))
        if start_date and start_date < surgery_date:
            return False

    for item in patient.get("treatments") or []:
        start_date = _parse_date(item.get("start_date"))
        if not start_date or start_date >= surgery_date:
            continue
        regimen = str(item.get("drug_scheme") or "").lower()
        if any(token in regimen for token in ("adt", "abirater", "enzalut", "apalut", "darolut", "lupron", "goserelin", "leuprolide", "docetaxel", "cabazitaxel", "horm")):
            return False
    return True


def _mskcc_post_rp_card(patient: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    missing = _score_missing_inputs(payload, "mskcc_bcr_post_rp")
    if missing:
        return _tool_card(
            tool_key="mskcc_bcr_post_rp",
            title="MSKCC BCR post-RP",
            clinical_scope="Pronóstico postquirúrgico",
            status="ready_missing_inputs",
            fidelity="ready_missing_inputs",
            primary_result="Nomograma MSKCC posoperatorio incompleto",
            meaning="Estima libertad de recurrencia bioquímica después de prostatectomía radical.",
            clinical_relation="Se relaciona con riesgo de recurrencia bioquímica y con intensidad de vigilancia o rescate.",
            missing_inputs=[_field_label(item) for item in missing],
            missing_input_keys=missing,
            required_at_intake=True,
            source_summary="Preparado para cálculo oficial posoperatorio con coeficientes MSKCC.",
            group_key="postop_prognosis",
        )
    result = mskcc_bcr_post_rp(
        {
            "age": payload.get("age"),
            "psa_preop": _first_nonempty(payload.get("baseline_psa"), payload.get("psa_preop"), payload.get("psa")),
            "pathology_gleason_primary": payload.get("pathology_gleason_primary"),
            "pathology_gleason_secondary": payload.get("pathology_gleason_secondary"),
            "pathologic_isup": payload.get("pathologic_isup", payload.get("pathological_isup")),
            "surgical_margin": payload.get("surgical_margin"),
            "ece_status": payload.get("ece_status"),
            "svi_status": payload.get("svi_status"),
            "lni_status": payload.get("lni_status"),
        }
    )
    return _tool_card(
        tool_key="mskcc_bcr_post_rp",
        title="MSKCC BCR post-RP",
        clinical_scope="Pronóstico postquirúrgico",
        status="calculated",
        fidelity="calculated",
        primary_result=f"Libre de BCR a 5 años {result.get('bcr_free_5y')} · a 10 años {result.get('bcr_free_10y')}",
        meaning=result.get("interpretation") or "Nomograma posoperatorio para libertad de recurrencia bioquímica.",
        clinical_relation=f"2 años {result.get('bcr_free_2y')} · 7 años {result.get('bcr_free_7y')}.",
        inputs_used=_stringify_inputs(payload, ["psa", "pathology_gleason_primary", "pathology_gleason_secondary", "surgical_margin", "ece_status", "svi_status", "lni_status"]),
        source_summary="Calculado localmente con los coeficientes oficiales publicados por MSKCC para el nomograma postoperatorio.",
        badge="Calculado",
        result_data=result,
        group_key="postop_prognosis",
    )


def _decipher_card(report: dict[str, Any]) -> dict[str, Any]:
    risk = report.get("decipher_risk")
    score = report.get("decipher_score")
    primary = f"{score} · {risk}" if _is_present(score) and _is_present(risk) else str(risk or score or "Resultado documentado")
    meaning = {
        "Bajo": "Sugiere biología menos agresiva y menor riesgo de metástasis o recaída temprana.",
        "Intermedio": "Sugiere riesgo genómico intermedio y puede matizar vigilancia o rescate.",
        "Alto": "Sugiere biología agresiva y mayor riesgo de recurrencia o metástasis.",
    }.get(str(risk or ""), "Resultado genómico documentado en reporte externo.")
    return _tool_card(
        tool_key="decipher",
        title="Decipher",
        clinical_scope="Interpretación genómica documentada",
        status="interpreted",
        fidelity="interpreted_from_report",
        primary_result=primary,
        meaning=meaning,
        clinical_relation="Se relaciona con riesgo biológico, vigilancia y discusión de adyuvancia o rescate según contexto.",
        inputs_used=[f"Fecha del reporte: {report.get('test_date')}" if _is_present(report.get("test_date")) else "Reporte externo documentado"],
        source_summary="Interpretado desde resultado documentado; no se calcula localmente.",
        badge="Interpretado desde reporte",
        result_data={"decipher_score": score, "decipher_risk": risk},
        group_key="documented_genomics",
    )


def _external_classifier_card(*, tool_key: str, title: str, score: Any, category: str, relation: str) -> dict[str, Any]:
    primary = str(score if _is_present(score) else category or "Resultado documentado")
    meaning = (
        "Clasificador genómico documentado con señal biológica adversa."
        if str(category).lower() == "alto"
        else "Clasificador genómico documentado."
    )
    return _tool_card(
        tool_key=tool_key,
        title=title,
        clinical_scope="Interpretación genómica documentada",
        status="interpreted",
        fidelity="interpreted_from_report",
        primary_result=primary,
        meaning=meaning,
        clinical_relation=relation,
        inputs_used=["Resultado externo documentado"],
        source_summary="Interpretado desde reporte; no se calcula localmente.",
        badge="Interpretado desde reporte",
        result_data={"score": score, "category": category},
        group_key="documented_genomics",
    )


def _build_upgrade_panel(patient: dict[str, Any], payload: dict[str, Any], raw_assessment: dict[str, Any] | None) -> dict[str, Any]:
    first_biopsy = _first_biopsy(patient)
    latest_biopsy = _latest_biopsy(patient)
    surgery = patient.get("surgery") or {}
    genomics = _find_genomic_report(patient, "Decipher")
    assessment_input = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    baseline_risk = str(
        payload.get("clinical_risk_group")
        or assessment_input.get("clinical_risk_group")
        or ""
    ).lower()

    pathologic_upgrade = {
        "active": False,
        "label": "Sin upgrade histopatológico mayor documentado",
        "detail": "",
    }
    previous_isup = _safe_int(first_biopsy.get("isup_grade"))
    latest_isup = _safe_int(latest_biopsy.get("isup_grade"))
    pathologic_isup = _safe_int(surgery.get("pathological_isup"))
    if latest_biopsy and latest_biopsy.get("upgrade_from_previous"):
        pathologic_upgrade = {
            "active": True,
            "label": "Upgrade histopatológico documentado",
            "detail": f"Biopsia previa ISUP {first_biopsy.get('previous_isup') or previous_isup or 'N/D'} → biopsia actual ISUP {latest_isup or 'N/D'}.",
        }
    elif previous_isup is not None and latest_isup is not None and latest_isup > previous_isup:
        pathologic_upgrade = {
            "active": True,
            "label": "Upgrade histopatológico documentado",
            "detail": f"ISUP de {previous_isup} a {latest_isup} entre biopsias estructuradas.",
        }
    elif previous_isup is not None and pathologic_isup is not None and pathologic_isup > previous_isup:
        pathologic_upgrade = {
            "active": True,
            "label": "Upgrade histopatológico documentado",
            "detail": f"ISUP de biopsia {previous_isup} a patología final {pathologic_isup}.",
        }

    genomic_category = ""
    if _is_present(genomics.get("decipher_risk")):
        genomic_category = str(genomics.get("decipher_risk"))
    else:
        genomic_category = _classifier_result_from_assessment(raw_assessment, "Decipher") or _classifier_result_from_assessment(raw_assessment, "Oncotype") or _classifier_result_from_assessment(raw_assessment, "Prolaris")

    genomic_upclassification = {
        "active": str(genomic_category).lower() == "alto",
        "label": "Reclasificación genómica documentada" if str(genomic_category).lower() == "alto" else "Sin reclasificación genómica documentada",
        "detail": f"Resultado genómico documentado como {genomic_category}." if genomic_category else "",
    }

    adverse_pathology = any(
        (
            pathologic_isup is not None and pathologic_isup >= 4,
            str(surgery.get("pathological_stage") or "").upper().startswith("PT3"),
            bool(surgery.get("lni_pathological")),
            bool(surgery.get("surgical_margin_status")),
        )
    )
    behaves_like_high = "intermedio desfavorable" in baseline_risk and (
        pathologic_upgrade["active"] or adverse_pathology or str(genomic_category).lower() == "alto"
    )

    return {
        "pathologic_upgrade": pathologic_upgrade,
        "genomic_upclassification": genomic_upclassification,
        "unfavorable_intermediate_behaving_like_high_risk": {
            "active": behaves_like_high,
            "label": "Intermedio desfavorable que se comportó como alto riesgo" if behaves_like_high else "Sin evidencia de comportamiento tipo alto riesgo",
            "detail": (
                "El caso inició como intermedio desfavorable y después mostró datos histopatológicos o genómicos de mayor agresividad."
                if behaves_like_high
                else ""
            ),
        },
        "has_any_flag": pathologic_upgrade["active"] or genomic_upclassification["active"] or behaves_like_high,
    }


def build_risk_tools_panel(
    *,
    patient: dict[str, Any],
    state: str,
    raw_assessment: dict[str, Any] | None = None,
    display_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _normalize_payload(patient=patient, raw_assessment=raw_assessment)
    assessment_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    diagnosed = state not in DIAGNOSTIC_STATES
    metastatic = _is_metastatic(payload, state)
    definitive_local_treatment = _has_definitive_local_treatment(patient, state)
    treatment_consideration = _treatment_consideration(payload, assessment_result)
    rp_considered = treatment_consideration["rp"]
    rt_considered = treatment_consideration["rt"]

    cards: list[dict[str, Any]] = []

    if state in DIAGNOSTIC_STATES and not diagnosed:
        cards.append(_erspc_card(payload, rebiopsy=state == "post_negative_biopsy_followup"))

    if state in LOCALIZED_STATES and diagnosed and not metastatic and not definitive_local_treatment:
        cards.append(_capra_card(payload))
        cards.append(_damico_card(payload))
        cards.append(_predict_card(payload))
        if rp_considered:
            cards.append(_mskcc_card(payload))
            cards.append(_partin_card(payload))

    if state in POST_RP_STATES or (patient.get("surgery") or {}).get("surgery_date"):
        cards.append(_capra_s_card(payload))
        if _post_rp_mskcc_allowed(patient, payload):
            cards.append(_mskcc_post_rp_card(patient, payload))
        historical_capra = _capra_card(payload, historical=True)
        if historical_capra.get("status") == "calculated":
            cards.append(historical_capra)

    decipher_report = _find_genomic_report(patient, "Decipher")
    if decipher_report and (_is_present(decipher_report.get("decipher_score")) or _is_present(decipher_report.get("decipher_risk"))):
        cards.append(_decipher_card(decipher_report))

    oncotype_report = _find_genomic_report(patient, "Oncotype")
    oncotype_category = _classifier_result_from_assessment(raw_assessment, "Oncotype")
    if oncotype_report and _is_present(oncotype_report.get("gps_score")):
        cards.append(
            _external_classifier_card(
                tool_key="oncotype_dx_gps",
                title="Oncotype DX GPS",
                score=f"GPS {oncotype_report.get('gps_score')}",
                category=oncotype_category,
                relation="Se relaciona con agresividad biológica y refinamiento del counseling en enfermedad localizada.",
            )
        )
    elif oncotype_category:
        cards.append(
            _external_classifier_card(
                tool_key="oncotype_dx_gps",
                title="Oncotype DX GPS",
                score=oncotype_category,
                category=oncotype_category,
                relation="Se relaciona con agresividad biológica y refinamiento del counseling en enfermedad localizada.",
            )
        )

    prolaris_report = _find_genomic_report(patient, "Prolaris")
    prolaris_category = _classifier_result_from_assessment(raw_assessment, "Prolaris")
    if prolaris_report and _is_present(prolaris_report.get("prolaris_score")):
        cards.append(
            _external_classifier_card(
                tool_key="prolaris",
                title="Prolaris / CCP Score",
                score=f"CCP {prolaris_report.get('prolaris_score')}",
                category=prolaris_category,
                relation="Se relaciona con agresividad biológica y riesgo de progresión o recurrencia según reporte documentado.",
            )
        )
    elif prolaris_category:
        cards.append(
            _external_classifier_card(
                tool_key="prolaris",
                title="Prolaris / CCP Score",
                score=prolaris_category,
                category=prolaris_category,
                relation="Se relaciona con agresividad biológica y riesgo de progresión o recurrencia según reporte documentado.",
            )
        )

    upgrade_panel = _build_upgrade_panel(patient, payload, raw_assessment)
    missing_inputs = []
    for card in cards:
        for field in card.get("missing_inputs", []):
            if field not in missing_inputs:
                missing_inputs.append(field)
    fidelity_summary: dict[str, int] = {}
    for card in cards:
        fidelity = str(card.get("fidelity") or "unknown")
        fidelity_summary[fidelity] = fidelity_summary.get(fidelity, 0) + 1

    return {
        "cards": cards,
        "missing_inputs": missing_inputs,
        "fidelity_summary": fidelity_summary,
        "upgrade_panel": upgrade_panel,
        "context": {
            "diagnosed": diagnosed,
            "metastatic": metastatic,
            "rp_considered": rp_considered,
            "rt_considered": rt_considered,
            "definitive_local_treatment": definitive_local_treatment,
        },
    }


def build_intake_score_requirements(
    *,
    module_id: str,
    state: str,
    assessment_input: dict[str, Any],
    assessment_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = deepcopy(assessment_input or {})
    if _is_present(payload.get("psa")) and not _is_present(payload.get("baseline_psa")):
        payload["baseline_psa"] = payload.get("psa")
    consideration = _treatment_consideration(payload, assessment_result)
    applicable_scores: list[str] = []
    if state in DIAGNOSTIC_STATES:
        applicable_scores = ["erspc"]
    elif state in LOCALIZED_STATES:
        applicable_scores = ["capra", "damico", "predict_prostate"]
        if consideration["rp"]:
            applicable_scores.extend(["mskcc_preop", "partin"])
        elif not consideration["known"]:
            applicable_scores.extend(["mskcc_preop", "partin"])
            payload["__missing_rp_context__"] = True
    elif state in POST_RP_STATES:
        applicable_scores = ["capra_s", "mskcc_bcr_post_rp"]

    required_fields_by_score: dict[str, list[dict[str, Any]]] = {}
    missing_fields: list[dict[str, Any]] = []
    seen: set[str] = set()

    for score in applicable_scores:
        score_fields = []
        missing = _score_missing_inputs(payload, score)
        if score == "erspc" and state == "post_negative_biopsy_followup" and not _is_present(payload.get("prior_biopsy_count")):
            missing.append("prior_biopsy_count")
        if score in {"mskcc_preop", "partin"} and payload.get("__missing_rp_context__"):
            missing.append("local_treatment_consideration")
        for field_name in dict.fromkeys(SCORE_REQUIREMENTS.get(score, []) + missing):
            meta = deepcopy(FIELD_REGISTRY.get(field_name, {"label": _field_label(field_name), "field_type": FIELDTYPE_NUMBER}))
            meta["name"] = field_name
            meta["required_by_scores"] = [score]
            score_fields.append(meta)
            if field_name in missing and field_name not in seen:
                missing_entry = deepcopy(meta)
                missing_entry["score_key"] = score
                missing_fields.append(missing_entry)
                seen.add(field_name)
        required_fields_by_score[score] = score_fields

    missing_fields.sort(key=lambda item: (int(item.get("intake_priority", 99)), item.get("label", "")))

    return {
        "applicable_scores": applicable_scores,
        "required_fields_by_score": required_fields_by_score,
        "score_missing_inputs": missing_fields,
    }


def summarize_risk_tools_for_cohort(records: list[dict[str, Any]]) -> dict[str, Any]:
    tool_status: dict[str, dict[str, int]] = {}
    capra_distribution = {"BAJO": 0, "INTERMEDIO": 0, "ALTO": 0}
    damico_distribution = {"BAJO": 0, "INTERMEDIO": 0, "ALTO": 0}
    capra_s_distribution = {"BAJO": 0, "INTERMEDIO": 0, "ALTO": 0}
    upgrade_stats = {
        "pathologic_upgrade_count": 0,
        "genomic_upclassification_count": 0,
        "unfavorable_intermediate_behaving_like_high_risk_count": 0,
    }

    for record in records:
        assessment = record.get("latest_assessment") or {}
        state = assessment.get("state") or (record.get("prior_history") or {}).get("current_state") or ""
        bundle = build_risk_tools_panel(
            patient=record,
            state=state,
            raw_assessment=assessment,
            display_assessment={},
        )
        for card in bundle.get("cards", []):
            key = str(card.get("tool_key") or "")
            bucket = tool_status.setdefault(key, {"calculated": 0, "interpreted": 0, "proxy": 0, "ready_missing_inputs": 0, "not_applicable": 0})
            if card.get("fidelity") == "calculated":
                bucket["calculated"] += 1
            elif card.get("fidelity") == "interpreted_from_report":
                bucket["interpreted"] += 1
            elif card.get("fidelity") == "proxy_estimate":
                bucket["proxy"] += 1
            elif card.get("status") == "ready_missing_inputs" or card.get("fidelity") == "ready_missing_inputs":
                bucket["ready_missing_inputs"] += 1
            else:
                bucket["not_applicable"] += 1
            if key == "capra" and "·" in str(card.get("primary_result") or ""):
                risk = str(card["primary_result"]).split("·", 1)[1].strip().upper()
                if risk in capra_distribution:
                    capra_distribution[risk] += 1
            if key == "damico":
                risk = str(card.get("primary_result") or "").strip().upper()
                if risk in damico_distribution:
                    damico_distribution[risk] += 1
            if key == "capra_s" and "·" in str(card.get("primary_result") or ""):
                risk = str(card["primary_result"]).split("·", 1)[1].strip().upper()
                if risk in capra_s_distribution:
                    capra_s_distribution[risk] += 1
        upgrade_panel = bundle.get("upgrade_panel", {})
        if (upgrade_panel.get("pathologic_upgrade") or {}).get("active"):
            upgrade_stats["pathologic_upgrade_count"] += 1
        if (upgrade_panel.get("genomic_upclassification") or {}).get("active"):
            upgrade_stats["genomic_upclassification_count"] += 1
        if (upgrade_panel.get("unfavorable_intermediate_behaving_like_high_risk") or {}).get("active"):
            upgrade_stats["unfavorable_intermediate_behaving_like_high_risk_count"] += 1

    return {
        "tool_status": tool_status,
        "capra_distribution": capra_distribution,
        "damico_distribution": damico_distribution,
        "capra_s_distribution": capra_s_distribution,
        "mskcc_bcr_post_rp_stats": tool_status.get(
            "mskcc_bcr_post_rp",
            {"calculated": 0, "interpreted": 0, "proxy": 0, "ready_missing_inputs": 0, "not_applicable": 0},
        ),
        **upgrade_stats,
    }
