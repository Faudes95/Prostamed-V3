from __future__ import annotations

import re
from typing import Any

from prostanet.shared.gleason_profile import normalize_gleason_profile


OFFICIAL_DIAGNOSIS_FIELDS = [
    "histology_subtype",
    "gleason_primary",
    "gleason_secondary",
    "gleason_tertiary",
    "isup_grade",
    "clinical_tstage",
    "nodal_status",
    "clinical_stage_group",
    "clinical_risk_group",
]

OFFICIAL_DIAGNOSIS_FIELD_LABELS = {
    "histology_subtype": "subtipo histológico",
    "gleason_primary": "Gleason primario",
    "gleason_secondary": "Gleason secundario",
    "gleason_tertiary": "Gleason terciario",
    "isup_grade": "ISUP / Grade Group",
    "clinical_tstage": "T clínico",
    "nodal_status": "N clínico",
    "clinical_stage_group": "etapa clínica",
    "clinical_risk_group": "grupo de riesgo clínico",
}

HISTOLOGY_SUBTYPE_OPTIONS = [
    "",
    "Adenocarcinoma acinar",
    "Adenocarcinoma ductal",
    "Adenocarcinoma mucinoso / coloide",
    "Carcinoma neuroendocrino / células pequeñas",
    "Carcinoma escamoso / adenoescamoso",
    "Carcinoma sarcomatoide",
    "Otro subtipo",
]

CLINICAL_TSTAGE_OPTIONS = [
    "",
    "Tx",
    "T1",
    "T1a",
    "T1b",
    "T1c",
    "T2",
    "T2a",
    "T2b",
    "T2c",
    "T3",
    "T3a",
    "T3b",
    "T4",
]

NODAL_STATUS_OPTIONS = ["", "Nx", "N0", "N1"]

CLINICAL_STAGE_GROUP_OPTIONS = [
    "",
    "I",
    "IIA",
    "IIB",
    "IIC",
    "IIIA",
    "IIIB",
    "IIIC",
    "IVA",
    "IVB",
]

CLINICAL_RISK_GROUP_OPTIONS = [
    "",
    "muy bajo",
    "bajo",
    "intermedio favorable",
    "intermedio desfavorable",
    "alto",
    "muy alto",
]

DIAGNOSTIC_LOCALIZED_STATES = {"diagnostic_workup", "post_negative_biopsy_followup", "localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
CRPC_STATES = {"m0_crpc", "m1_crpc"}


def diagnosis_capture_options() -> dict[str, list[str]]:
    return {
        "histology_subtype": HISTOLOGY_SUBTYPE_OPTIONS,
        "clinical_tstage": CLINICAL_TSTAGE_OPTIONS,
        "nodal_status": NODAL_STATUS_OPTIONS,
        "clinical_stage_group": CLINICAL_STAGE_GROUP_OPTIONS,
        "clinical_risk_group": CLINICAL_RISK_GROUP_OPTIONS,
    }


# Guard DX-1 (FAUBOT FASE 6): AJCC 8th edition TNM enumeración canónica.
# Cualquier valor fuera de este catálogo debe generar un warning en backend
# para que el clínico pueda corregir antes de firmar el diagnóstico oficial.
_VALID_T_STAGES = {"Tx", "T1", "T1a", "T1b", "T1c", "T2", "T2a", "T2b", "T2c", "T3", "T3a", "T3b", "T4"}
_VALID_N_STAGES = {"Nx", "N0", "N1"}
_VALID_M_STAGES = {"Mx", "M0", "M1", "M1a", "M1b", "M1c"}


def _check_tnm_value(raw: Any, valid_set: set[str], normalized: str, label: str, *, prefix: str) -> dict[str, Any]:
    raw_text = str(raw or "").strip()
    if not raw_text:
        return {"value": "", "raw": "", "valid": True, "warning": ""}
    # Normalizamos case + prefix clínico (cT/cN/cM) antes de comparar vs AJCC.
    cleaned = raw_text.upper().replace("C" + prefix.upper(), prefix.upper()).strip()
    canonical_match = None
    for candidate in valid_set:
        if candidate.upper() == cleaned:
            canonical_match = candidate
            break
    if canonical_match is not None:
        return {"value": canonical_match, "raw": raw_text, "valid": True, "warning": ""}
    return {
        "value": normalized,
        "raw": raw_text,
        "valid": False,
        "warning": (
            f"{label} '{raw_text}' no coincide con la enumeración AJCC 8ª edición. "
            f"Valores permitidos: {', '.join(sorted(valid_set))}."
        ),
    }


def validate_tnm_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Valida T/N/M contra AJCC 8ª edición y retorna warnings backend (DX-1).

    Se invoca desde `build_official_diagnosis_context` y cualquier ingress
    que firme diagnóstico oficial. Los warnings se exponen al clínico sin
    bloquear la UI, pero impiden marcar el diagnóstico como ``confirmed``.
    """
    source = dict(payload or {})
    t_raw = source.get("clinical_tstage") or ""
    n_raw = source.get("nodal_status") or ""
    m_raw = source.get("m_substage_resolved") or source.get("metastasis_site") or ""
    t_result = _check_tnm_value(t_raw, _VALID_T_STAGES, _normalize_t_stage(t_raw), "T clínico", prefix="T")
    n_result = _check_tnm_value(n_raw, _VALID_N_STAGES, _normalize_n_stage(n_raw), "N clínico", prefix="N")
    m_result = _check_tnm_value(m_raw, _VALID_M_STAGES, _normalize_m_stage(m_raw), "M clínico", prefix="M")
    warnings = [r["warning"] for r in (t_result, n_result, m_result) if not r["valid"]]
    return {
        "clinical_tstage": t_result,
        "nodal_status": n_result,
        "m_substage": m_result,
        "valid": all(r["valid"] for r in (t_result, n_result, m_result)),
        "warnings": warnings,
    }


def diagnosis_field_label(field_name: str) -> str:
    return OFFICIAL_DIAGNOSIS_FIELD_LABELS.get(field_name, field_name.replace("_", " "))


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return ""


def _latest(items: list[dict[str, Any]], *date_keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in date_keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_histology_subtype(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip()
    lower = text.lower()
    mapping = (
        ("acinar", "Adenocarcinoma acinar"),
        ("ductal", "Adenocarcinoma ductal"),
        ("mucin", "Adenocarcinoma mucinoso / coloide"),
        ("coloid", "Adenocarcinoma mucinoso / coloide"),
        ("small cell", "Carcinoma neuroendocrino / células pequeñas"),
        ("neuroendocr", "Carcinoma neuroendocrino / células pequeñas"),
        ("escamos", "Carcinoma escamoso / adenoescamoso"),
        ("adenoesc", "Carcinoma escamoso / adenoescamoso"),
        ("sarcom", "Carcinoma sarcomatoide"),
    )
    for needle, label in mapping:
        if needle in lower:
            return label
    return text


def _histology_phrase(value: Any) -> str:
    label = _normalize_histology_subtype(value)
    if not label:
        return ""
    lower = label.lower()
    if "próstata" in lower or "prostata" in lower:
        return label
    if "adenocarcinoma" in lower or "carcinoma" in lower:
        return f"{label} de próstata"
    return f"Cáncer de próstata {label.lower()}"


def _normalize_t_stage(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip().upper().replace("CT", "T")
    match = re.search(r"T(X|[0-4][ABC]?)", text)
    if not match:
        return ""
    stage = f"T{match.group(1)}"
    return "" if stage == "TX" else stage


def _normalize_n_stage(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip().upper().replace("CN", "N")
    match = re.search(r"N(X|0|1)", text)
    if not match:
        return ""
    stage = f"N{match.group(1)}"
    return "" if stage == "NX" else stage


def _normalize_m_stage(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip().upper().replace("CM", "M")
    match = re.search(r"M(X|0|1[ABC]?)", text)
    if not match:
        return ""
    stage = f"M{match.group(1)}"
    return "" if stage == "MX" else stage[0] + stage[1:].lower()


def _parse_tnm_stage(value: Any) -> tuple[str, str, str]:
    text = str(value or "")
    return _normalize_t_stage(text), _normalize_n_stage(text), _normalize_m_stage(text)


def _normalize_stage_group(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip().upper().replace("ETAPA", "").replace("CLÍNICA", "").replace("CLINICA", "").strip()
    return text


def _normalize_risk_group(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip()
    lower = text.lower()
    mapping = {
        "very low": "muy bajo",
        "low": "bajo",
        "favorable intermediate": "intermedio favorable",
        "unfavorable intermediate": "intermedio desfavorable",
        "high": "alto",
        "very high": "muy alto",
    }
    return mapping.get(lower, lower)


def _normalize_volume_disease(value: Any) -> str:
    if not _is_present(value):
        return ""
    text = str(value).strip().lower()
    if text in {"high", "alto", "high volume", "alto volumen"}:
        return "alto"
    if text in {"low", "bajo", "low volume", "bajo volumen"}:
        return "bajo"
    return text


def _source_summary(patient: dict[str, Any], facts: dict[str, Any], raw_assessment: dict[str, Any], display_assessment: dict[str, Any], baseline: dict[str, Any], latest_biopsy: dict[str, Any]) -> str:
    sources: list[str] = []
    if latest_biopsy and any(_is_present(latest_biopsy.get(key)) for key in ("histology_subtype", "gleason_primary", "gleason_secondary", "gleason_tertiary", "isup_grade")):
        sources.append("patología / biopsia")
    if any(_is_present(baseline.get(key)) for key in ("histology_subtype", "gleason_primary", "gleason_secondary", "gleason_tertiary", "isup_grade", "clinical_tstage", "nodal_status", "clinical_stage_group", "clinical_risk_group")):
        sources.append("ingreso estructurado")
    if any(_is_present(item.get(key)) for item in (patient.get("follow_ups") or [])[-2:] for key in OFFICIAL_DIAGNOSIS_FIELDS):
        sources.append("visita de seguimiento")
    if _is_present(((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("risk_group")):
        sources.append("evaluación modular")
    if not sources and any(_is_present(facts.get(key)) for key in OFFICIAL_DIAGNOSIS_FIELDS):
        sources.append("expediente longitudinal")
    return " · ".join(dict.fromkeys(sources)) or "clasificación operativa"


def _histopathology_summary(facts: dict[str, Any]) -> str:
    profile = normalize_gleason_profile(facts)
    return profile.get("summary") or ""


def _compose_localized_diagnosis(facts: dict[str, Any]) -> str:
    base = _histology_phrase(facts.get("histology_subtype")) or "Cáncer de próstata histológicamente confirmado"
    histopathology = _histopathology_summary(facts)
    if histopathology:
        base = f"{base} {histopathology}"
    extras = []
    risk_group = _normalize_risk_group(facts.get("clinical_risk_group"))
    if risk_group:
        extras.append(f"riesgo {risk_group}")
    stage_group = _normalize_stage_group(facts.get("clinical_stage_group"))
    if stage_group:
        extras.append(f"etapa clínica {stage_group}")
    return ", ".join([base, *extras]) if extras else base


def _compose_postlocal_diagnosis(state: str, patient: dict[str, Any], facts: dict[str, Any]) -> str:
    base = _histology_phrase(facts.get("histology_subtype")) or "Cáncer de próstata"
    histopathology = _histopathology_summary(facts)
    if histopathology:
        base = f"{base} {histopathology}"
    qualifiers = []
    has_surgery = bool(patient.get("surgery")) or state == "post_prostatectomy"
    has_bcr = bool(patient.get("bcr")) or state == "recurrence_bcr"
    if has_surgery:
        qualifiers.append("post prostatectomía radical")
    if has_bcr:
        qualifiers.append("recurrencia bioquímica")
    m_stage = _normalize_m_stage(facts.get("m_substage_resolved"))
    if m_stage == "M0":
        qualifiers.append("sin metástasis a distancia documentada")
    elif m_stage:
        qualifiers.append(f"con enfermedad {m_stage}")
    return ", ".join([base, *qualifiers]) if qualifiers else base


def _compose_mhspc_diagnosis(facts: dict[str, Any]) -> str:
    base = _histology_phrase(facts.get("histology_subtype")) or "Cáncer de próstata"
    diagnosis = f"{base} metastásico sensible a la castración"
    m_stage = _normalize_m_stage(facts.get("m_substage_resolved"))
    if m_stage:
        diagnosis += f" {m_stage}"
    volume = _normalize_volume_disease(facts.get("volume_disease"))
    if volume:
        diagnosis += f" de {volume} volumen"
    histopathology = _histopathology_summary(facts)
    if histopathology:
        diagnosis += f", {histopathology}"
    return diagnosis


def _compose_crpc_diagnosis(state: str, facts: dict[str, Any]) -> str:
    base = _histology_phrase(facts.get("histology_subtype")) or "Cáncer de próstata"
    histopathology = _histopathology_summary(facts)
    if state == "m0_crpc":
        diagnosis = f"{base} resistente a la castración no metastásico (M0)"
        return f"{diagnosis}, {histopathology}" if histopathology else diagnosis
    m_stage = _normalize_m_stage(facts.get("m_substage_resolved")) or "M1"
    diagnosis = f"{base} resistente a la castración metastásico {m_stage}"
    return f"{diagnosis}, {histopathology}" if histopathology else diagnosis


def _compose_verification_diagnosis(facts: dict[str, Any]) -> str:
    base = _histology_phrase(facts.get("histology_subtype")) or "Cáncer de próstata"
    diagnosis = f"{base} con progresión bajo terapia de privación androgénica en verificación"
    m_stage = _normalize_m_stage(facts.get("m_substage_resolved"))
    if m_stage:
        diagnosis += f" ({m_stage})"
    histopathology = _histopathology_summary(facts)
    if histopathology:
        diagnosis += f", {histopathology}"
    return diagnosis


def _has_histology_confirmation(latest_biopsy: dict[str, Any], facts: dict[str, Any]) -> bool:
    positive_cores = _safe_int(
        _first_nonempty(
            latest_biopsy.get("positive_cores"),
            latest_biopsy.get("num_cores_positive"),
            facts.get("positive_cores"),
        )
    ) or 0
    if positive_cores > 0:
        return True
    return any(
        _is_present(
            _first_nonempty(
                latest_biopsy.get(field),
                facts.get(field),
            )
        )
        for field in ("gleason_primary", "gleason_secondary", "isup_grade", "histology_subtype")
    )


def _operational_diagnosis_fallback(state: str, operational_label: str) -> str:
    if state == "diagnostic_workup":
        return "Sospecha de cáncer de próstata en estudio"
    if state == "post_negative_biopsy_followup":
        return "Sospecha persistente tras biopsia benigna inicial"
    return operational_label or "Diagnóstico en consolidación"


def _diagnosis_template_kind(state: str, facts: dict[str, Any], patient: dict[str, Any]) -> str:
    if state in MHSPC_STATES:
        return "mhspc"
    if state in CRPC_STATES:
        return "crpc"
    if state == "adt_progression_verification":
        return "verification"
    if state in POSTLOCAL_STATES or patient.get("surgery") or patient.get("bcr"):
        return "postlocal"
    if any(_is_present(facts.get(key)) for key in ("histology_subtype", "gleason_primary", "gleason_secondary", "isup_grade", "clinical_risk_group", "clinical_stage_group", "clinical_tstage", "nodal_status")):
        return "localized"
    return "operational"


def _required_fields_for_kind(kind: str) -> list[str]:
    if kind == "localized":
        return [
            "histology_subtype",
            "gleason_primary",
            "gleason_secondary",
            "clinical_tstage",
            "nodal_status",
            "clinical_stage_group",
            "clinical_risk_group",
        ]
    if kind == "postlocal":
        return ["histology_subtype", "gleason_primary", "gleason_secondary"]
    if kind == "mhspc":
        return ["histology_subtype", "m_substage_resolved", "volume_disease"]
    if kind == "crpc":
        return ["histology_subtype", "m_substage_resolved"]
    if kind == "verification":
        return ["histology_subtype"]
    return []


def build_official_diagnosis_context(
    *,
    patient: dict[str, Any],
    state: str,
    raw_assessment: dict[str, Any] | None = None,
    display_assessment: dict[str, Any] | None = None,
    operational_module_label: str = "",
) -> dict[str, Any]:
    baseline = dict(patient.get("baseline") or {})
    latest_biopsy = _latest(patient.get("biopsies") or [], "biopsy_date")
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    assessment_input = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    parsed_t, parsed_n, parsed_m = _parse_tnm_stage(_first_nonempty(baseline.get("tnm_stage"), assessment_input.get("tnm_stage")))

    gleason_source = {
        "gleason_primary": _first_nonempty(latest_biopsy.get("gleason_primary"), baseline.get("gleason_primary"), assessment_input.get("gleason_primary")),
        "gleason_secondary": _first_nonempty(latest_biopsy.get("gleason_secondary"), baseline.get("gleason_secondary"), assessment_input.get("gleason_secondary")),
        "gleason_tertiary": _first_nonempty(latest_biopsy.get("gleason_tertiary"), baseline.get("gleason_tertiary"), assessment_input.get("gleason_tertiary")),
        "gleason_score": _first_nonempty(latest_biopsy.get("gleason_score"), baseline.get("gleason_score"), assessment_input.get("gleason_score")),
        "isup_grade": _first_nonempty(latest_biopsy.get("isup_grade"), baseline.get("isup_grade"), assessment_input.get("isup_grade")),
    }
    gleason_profile = normalize_gleason_profile(gleason_source)

    facts = {
        "histology_subtype": _normalize_histology_subtype(
            _first_nonempty(
                latest_biopsy.get("histology_subtype"),
                baseline.get("histology_subtype"),
                assessment_input.get("histology_subtype"),
            )
        ),
        "gleason_primary": gleason_profile.get("gleason_primary"),
        "gleason_secondary": gleason_profile.get("gleason_secondary"),
        "gleason_tertiary": gleason_profile.get("gleason_tertiary"),
        "gleason_score": gleason_profile.get("gleason_score"),
        "isup_grade": gleason_profile.get("isup_grade"),
        "histopathology_summary": gleason_profile.get("summary"),
        "has_adverse_tertiary_pattern": gleason_profile.get("has_adverse_tertiary_pattern"),
        "clinical_tstage": _first_nonempty(
            _normalize_t_stage(baseline.get("clinical_tstage")),
            _normalize_t_stage(assessment_input.get("clinical_tstage")),
            parsed_t,
        ),
        "nodal_status": _first_nonempty(
            _normalize_n_stage(baseline.get("nodal_status")),
            _normalize_n_stage(assessment_input.get("nodal_status")),
            parsed_n,
        ),
        "m_substage_resolved": _first_nonempty(
            _normalize_m_stage(latest_followup.get("m_substage_resolved")),
            _normalize_m_stage(baseline.get("m_substage_resolved")),
            _normalize_m_stage(assessment_input.get("m_substage_resolved")),
            _normalize_m_stage(assessment_input.get("metastasis_site")),
            parsed_m,
        ),
        "clinical_stage_group": _first_nonempty(
            _normalize_stage_group(baseline.get("clinical_stage_group")),
            _normalize_stage_group(assessment_input.get("clinical_stage_group")),
        ),
        "clinical_risk_group": _first_nonempty(
            _normalize_risk_group(baseline.get("clinical_risk_group")),
            _normalize_risk_group(assessment_input.get("clinical_risk_group")),
            _normalize_risk_group((display_result.get("nccn_primary", {}) or {}).get("risk_group")),
            _normalize_risk_group((raw_result.get("nccn_primary", {}) or {}).get("risk_group")),
        ),
        "volume_disease": _first_nonempty(
            _normalize_volume_disease(latest_followup.get("volume_disease")),
            _normalize_volume_disease(baseline.get("volume_disease")),
            _normalize_volume_disease(assessment_input.get("volume_disease")),
        ),
    }

    kind = _diagnosis_template_kind(state, facts, patient)
    operational_label = operational_module_label or "Diagnóstico en consolidación"
    histology_confirmed = _has_histology_confirmation(latest_biopsy, facts)
    provisional_operational_label = _operational_diagnosis_fallback(state, operational_label)
    if kind == "localized":
        official = _compose_localized_diagnosis(facts)
    elif kind == "postlocal":
        official = _compose_postlocal_diagnosis(state, patient, facts)
    elif kind == "mhspc":
        official = _compose_mhspc_diagnosis(facts)
    elif kind == "crpc":
        official = _compose_crpc_diagnosis(state, facts)
    elif kind == "verification":
        official = _compose_verification_diagnosis(facts)
    else:
        official = operational_label

    formal_components_present = any(
        _is_present(facts.get(key))
        for key in ("histology_subtype", "gleason_primary", "gleason_secondary", "isup_grade", "clinical_tstage", "nodal_status", "clinical_stage_group", "clinical_risk_group")
    )
    required_fields = _required_fields_for_kind(kind)
    missing_raw = [field for field in required_fields if not _is_present(facts.get(field))]
    if kind == "operational" or not formal_components_present:
        status = "missing"
        official = provisional_operational_label
    elif not missing_raw:
        status = "complete"
    else:
        status = "partial"

    display_status = "confirmed"
    if state in DIAGNOSTIC_LOCALIZED_STATES and not histology_confirmed:
        official = provisional_operational_label
        display_status = "provisional"
    elif status == "complete":
        display_status = "confirmed"
    elif status == "partial":
        display_status = "incomplete"
    else:
        display_status = "operational_only"

    # Guard DX-1: validación AJCC 8ª edición de TNM ingresado (warnings backend).
    tnm_validation = validate_tnm_payload(
        {
            "clinical_tstage": _first_nonempty(
                baseline.get("clinical_tstage"),
                assessment_input.get("clinical_tstage"),
                parsed_t,
            ),
            "nodal_status": _first_nonempty(
                baseline.get("nodal_status"),
                assessment_input.get("nodal_status"),
                parsed_n,
            ),
            "m_substage_resolved": _first_nonempty(
                latest_followup.get("m_substage_resolved"),
                baseline.get("m_substage_resolved"),
                assessment_input.get("m_substage_resolved"),
                assessment_input.get("metastasis_site"),
                parsed_m,
            ),
        }
    )
    tnm_warnings = list(tnm_validation.get("warnings") or [])
    if tnm_warnings and display_status == "confirmed":
        display_status = "incomplete"

    return {
        "official_diagnosis": official,
        "official_diagnosis_status": status,
        "official_diagnosis_display_status": display_status,
        "official_diagnosis_confirmed": histology_confirmed and not tnm_warnings,
        "operational_diagnosis": provisional_operational_label,
        "official_diagnosis_missing_fields_raw": missing_raw,
        "official_diagnosis_missing_fields": [diagnosis_field_label(field) for field in missing_raw],
        "official_diagnosis_source_summary": _source_summary(patient, facts, raw_assessment or {}, display_assessment or {}, baseline, latest_biopsy),
        "histopathology_summary": facts.get("histopathology_summary", ""),
        "operational_module_label": operational_label,
        "template_kind": kind,
        "facts": facts,
        "tnm_validation": tnm_validation,
        "tnm_validation_warnings": tnm_warnings,
    }
