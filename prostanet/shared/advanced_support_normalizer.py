from __future__ import annotations

from copy import deepcopy
from typing import Any

from prostanet.domains.patient_tracking.score_interpretation_catalog import (
    interpret_bpi_worst_pain,
    interpret_eq5d_vas,
    interpret_fact_p,
)
from prostanet.shared.advanced_support_catalog import (
    REGIMEN_ONCOLOGY_DRUGS,
    STATE_CANDIDATE_REGIMENS,
    derive_pro_band_from_numeric,
    pro_band_numeric_field,
    pro_band_representative_value,
)
from prostanet.shared.ddi_engine import DDIEngine


CANONICAL_LAB_ALIASES = {
    "alkaline_phosphatase_u_l": ("alp", "alkaline_phosphatase", "fosfatasa_alcalina"),
    "ldh_u_l": ("ldh", "serum_ldh", "lactate_dehydrogenase"),
    "hemoglobin_g_dl": ("hemoglobin", "hgb", "hb", "hemoglobina"),
    "creatinine_mg_dl": ("creatinine", "serum_creatinine"),
}


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "si",
        "sí",
        "present",
        "positive",
        "positivo",
        "documented",
        "documentado",
    }


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {}, "Desconocido", "Desconocida", "No documentado", "unknown")


def normalize_canonical_lab_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    """Mirror canonical lab fields and legacy aliases without changing values.

    The wizard should ask a lab only once, but older rules and pivotal gates
    still consume short aliases such as ``alp`` or ``hemoglobin``.  This keeps
    backend compatibility while allowing the V2 UI to suppress duplicate alias
    fields from the visible form.
    """
    data = dict(payload or {})
    for canonical, aliases in CANONICAL_LAB_ALIASES.items():
        canonical_value = data.get(canonical)
        if not _nonempty(canonical_value):
            for alias in aliases:
                if _nonempty(data.get(alias)):
                    canonical_value = data.get(alias)
                    data[canonical] = canonical_value
                    break
        if not _nonempty(canonical_value):
            continue
        for alias in aliases:
            if not _nonempty(data.get(alias)):
                data[alias] = canonical_value
    return data


def parse_medication_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    normalized: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        normalized.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in normalized:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _infer_review_status(data: dict[str, Any], *, meds_present: bool) -> str:
    explicit = str(data.get("ddi_review_status") or "").strip().lower()
    if explicit in {"not_started", "in_progress", "completed"}:
        return explicit
    if _truthy(data.get("drug_interaction_reviewed")):
        return "completed"
    if not meds_present:
        return "completed"
    # EPIC 4.3: medication list capturada estructuradamente → el engine
    # de DDI corre automáticamente (build_ddi_regimen_matrix). La revisión
    # se considera *engine-completed* salvo que el clínico la marque
    # explícitamente como in_progress o not_started.
    return "completed"


def _severity_rank(severity: str) -> int:
    return {
        "none": 0,
        "caution": 1,
        "moderate": 1,
        "major": 2,
        "contraindicated": 3,
    }.get(str(severity or "").strip().lower(), 0)


def _bundle_severity(alerts: list[dict[str, Any]]) -> str:
    max_rank = 0
    for alert in alerts:
        max_rank = max(max_rank, _severity_rank(alert.get("severity") or "none"))
    return {
        0: "none",
        1: "caution",
        2: "major",
        3: "contraindicated",
    }.get(max_rank, "none")


def _candidate_regimens_for_state(state: str) -> list[str]:
    return list(STATE_CANDIDATE_REGIMENS.get(str(state or "").strip(), []))


def _active_oncology_drugs(data: dict[str, Any]) -> list[str]:
    regimen_code = str(data.get("drug_scheme") or "").strip()
    if regimen_code in REGIMEN_ONCOLOGY_DRUGS:
        return list(REGIMEN_ONCOLOGY_DRUGS[regimen_code])
    raw_value = data.get("oncology_drugs") or data.get("current_treatment") or data.get("prior_therapy") or ""
    return [item.lower() for item in parse_medication_list(raw_value)]


def build_ddi_regimen_matrix(
    data: dict[str, Any],
    *,
    state: str = "",
    concomitant_medications: list[str] | None = None,
) -> dict[str, Any]:
    meds = list(concomitant_medications or parse_medication_list(data.get("current_medications")))
    meds_lower = [item.lower() for item in meds]
    seizure_history = _truthy(data.get("comorbidity_seizure")) or _truthy(data.get("seizure_history"))
    matrix: dict[str, Any] = {}
    for regimen_code in _candidate_regimens_for_state(state):
        oncology_drugs = list(REGIMEN_ONCOLOGY_DRUGS.get(regimen_code) or [])
        alerts = [
            alert.to_dict()
            for alert in DDIEngine.check_interactions(oncology_drugs, meds_lower, seizure_history)
        ]
        status = _bundle_severity(alerts)
        matrix[regimen_code] = {
            "oncology_drugs": list(oncology_drugs),
            "status": status,
            "alert_count": len(alerts),
            "major_count": sum(1 for alert in alerts if str(alert.get("severity") or "").lower() == "major"),
            "contraindicated_count": sum(1 for alert in alerts if str(alert.get("severity") or "").lower() == "contraindicated"),
            "alerts": alerts,
        }
    return matrix


def build_hepatic_safety_bundle(data: dict[str, Any]) -> dict[str, Any]:
    child_pugh = str(data.get("child_pugh_score") or "A").strip().upper() or "A"
    liver_panel_date = str(data.get("liver_panel_date") or data.get("lft_date") or "").strip()
    active_liver_disease = _truthy(data.get("active_liver_disease"))
    cirrhosis_or_portal_hypertension = _truthy(data.get("cirrhosis_or_portal_hypertension"))
    active_hepatitis_b_or_c = _truthy(data.get("active_hepatitis_b_or_c"))
    prior_drug_induced_liver_injury = _truthy(data.get("prior_drug_induced_liver_injury"))
    hepatic_risk_present = (
        child_pugh in {"B", "C"}
        or active_liver_disease
        or cirrhosis_or_portal_hypertension
        or active_hepatitis_b_or_c
        or prior_drug_induced_liver_injury
    )
    bilirubin = data.get("bilirubin")
    ast = data.get("ast")
    alt = data.get("alt")
    alp = data.get("alp")
    hepatic_monitoring_ready = all(
        _nonempty(value)
        for value in (liver_panel_date, bilirubin, ast, alt, alp)
    )
    return {
        "child_pugh_score": child_pugh,
        "liver_panel_date": liver_panel_date,
        "bilirubin": bilirubin,
        "ast": ast,
        "alt": alt,
        "alp": alp,
        "active_liver_disease": active_liver_disease,
        "cirrhosis_or_portal_hypertension": cirrhosis_or_portal_hypertension,
        "active_hepatitis_b_or_c": active_hepatitis_b_or_c,
        "prior_drug_induced_liver_injury": prior_drug_induced_liver_injury,
        "hepatic_monitoring_ready": hepatic_monitoring_ready,
        "hepatic_risk_present": hepatic_risk_present,
    }


def build_advanced_pro_bundle(data: dict[str, Any]) -> dict[str, Any]:
    eq5d = _safe_int(data.get("eq5d_vas"))
    fact_p = _safe_int(data.get("fact_p_total"))
    bpi = _safe_int(data.get("bpi_worst_pain"))
    fatigue = _safe_int(data.get("fatigue_score"))
    present_count = sum(value is not None for value in (eq5d, fact_p, bpi, fatigue))
    return {
        "eq5d_vas": eq5d,
        "eq5d_vas_band": str(data.get("eq5d_vas_band") or ""),
        "fact_p_total": fact_p,
        "fact_p_total_band": str(data.get("fact_p_total_band") or ""),
        "bpi_worst_pain": bpi,
        "bpi_worst_pain_band": str(data.get("bpi_worst_pain_band") or ""),
        "fatigue_score": fatigue,
        "fatigue_score_band": str(data.get("fatigue_score_band") or ""),
        "status": "complete" if present_count == 4 else "partial" if present_count else "missing",
        "interpretations": {
            "eq5d_vas": interpret_eq5d_vas(eq5d) if eq5d is not None else {},
            "fact_p_total": interpret_fact_p(fact_p) if fact_p is not None else {},
            "bpi_worst_pain": interpret_bpi_worst_pain(bpi) if bpi is not None else {},
        },
    }


def build_cognitive_screening_bundle(data: dict[str, Any]) -> dict[str, Any]:
    mini_cog = _safe_int(data.get("mini_cog_score"))
    g8_score = _safe_float(data.get("g8_score"))
    frailty_status = str(data.get("frailty_status") or "").strip().lower()
    required_reasons: list[str] = []
    if frailty_status in {"vulnerable", "frail"}:
        required_reasons.append("Fragilidad vulnerable/frail")
    if g8_score is not None and g8_score <= 14:
        required_reasons.append("G8 <= 14")
    if _truthy(data.get("cognitive_risk")):
        required_reasons.append("Riesgo cognitivo explícito")
    if _truthy(data.get("fall_risk")):
        required_reasons.append("Riesgo de caídas")
    if _truthy(data.get("stroke_history")):
        required_reasons.append("Antecedente neurovascular")
    required = bool(required_reasons)
    return {
        "mini_cog_score": mini_cog,
        "mini_cog_date": str(data.get("mini_cog_date") or "").strip(),
        "cognitive_screen_source": str(data.get("cognitive_screen_source") or "").strip(),
        "screen_required": required,
        "screen_required_reasons": required_reasons,
        "screen_status": "captured" if mini_cog is not None else "pending" if required else "optional",
        "needs_extended_assessment": mini_cog is not None and mini_cog <= 2,
    }


def build_variant_histology_bundle(data: dict[str, Any]) -> dict[str, Any]:
    adverse_type = str(data.get("adverse_histology_variant_type") or "none").strip() or "none"
    if adverse_type == "none" and _truthy(data.get("rare_histology_variant")):
        adverse_type = "other_aggressive_unspecified"
    rare_present = adverse_type not in {"", "none"}
    neuroendocrine = _truthy(data.get("neuroendocrine_features")) or adverse_type == "small_cell_neuroendocrine"
    return {
        "rare_histology_variant": rare_present,
        "adverse_histology_variant_type": adverse_type,
        "adverse_histology_variant_detail": str(data.get("adverse_histology_variant_detail") or "").strip(),
        "variant_histology_report_date": str(data.get("variant_histology_report_date") or "").strip(),
        "variant_histology_source": str(data.get("variant_histology_source") or "").strip(),
        "neuroendocrine_features": neuroendocrine,
        "requires_expert_review": rare_present or neuroendocrine,
        "hard_redirect": adverse_type == "small_cell_neuroendocrine" or neuroendocrine,
    }


def normalize_advanced_support_payload(payload: dict[str, Any] | None, *, state: str = "") -> dict[str, Any]:
    data = normalize_canonical_lab_aliases(deepcopy(payload or {}))

    if _nonempty(data.get("baseline_qol")) and not _nonempty(data.get("eq5d_vas")):
        data["eq5d_vas"] = data.get("baseline_qol")
    if _nonempty(data.get("fatigue_baseline")) and not _nonempty(data.get("fatigue_score")):
        data["fatigue_score"] = data.get("fatigue_baseline")
    if _nonempty(data.get("neurocognitive_baseline")) and not _nonempty(data.get("mini_cog_score")):
        data["mini_cog_score"] = data.get("neurocognitive_baseline")

    for band_field in ("eq5d_vas_band", "fact_p_total_band", "bpi_worst_pain_band", "fatigue_score_band"):
        numeric_field = pro_band_numeric_field(band_field)
        if not numeric_field:
            continue
        numeric_value = _safe_int(data.get(numeric_field))
        band_value = str(data.get(band_field) or "").strip()
        if numeric_value is not None:
            data[numeric_field] = numeric_value
            data[band_field] = derive_pro_band_from_numeric(band_field, numeric_value)
        elif band_value:
            representative = pro_band_representative_value(band_field, band_value)
            if representative is not None:
                data[numeric_field] = representative
                data[band_field] = band_value

    if _nonempty(data.get("eq5d_vas")):
        data["baseline_qol"] = _safe_int(data.get("eq5d_vas"))
    if _nonempty(data.get("fatigue_score")):
        data["fatigue_baseline"] = _safe_int(data.get("fatigue_score"))
    if _nonempty(data.get("mini_cog_score")):
        data["neurocognitive_baseline"] = _safe_int(data.get("mini_cog_score"))

    hepatic_bundle = build_hepatic_safety_bundle(data)
    data["liver_panel_date"] = hepatic_bundle["liver_panel_date"]
    data["lft_date"] = hepatic_bundle["liver_panel_date"]
    data["hepatic_safety_bundle"] = hepatic_bundle
    data["hepatic_monitoring_ready"] = "1" if hepatic_bundle["hepatic_monitoring_ready"] else "0"
    data["hepatic_risk_factors"] = "1" if hepatic_bundle["hepatic_risk_present"] else "0"

    # EPIC 4.3: priorizar lista estructurada si ya fue provista (cliente /
    # tests); caer en current_medications texto libre como fallback.
    pre_structured = data.get("normalized_medication_list")
    if isinstance(pre_structured, (list, tuple, set)) and pre_structured:
        meds = parse_medication_list(list(pre_structured))
    else:
        meds = parse_medication_list(data.get("current_medications"))
    ddi_review_status = _infer_review_status(data, meds_present=bool(meds))
    active_oncology_drugs = _active_oncology_drugs(data)
    active_alerts = [
        alert.to_dict()
        for alert in DDIEngine.check_interactions(active_oncology_drugs, [item.lower() for item in meds], _truthy(data.get("comorbidity_seizure")) or _truthy(data.get("seizure_history")))
    ]
    ddi_matrix = build_ddi_regimen_matrix(data, state=state, concomitant_medications=meds)
    ddi_bundle = {
        "normalized_medication_list": meds,
        "ddi_review_status": ddi_review_status,
        "ddi_alert_bundle": {
            "status": _bundle_severity(active_alerts),
            "alert_count": len(active_alerts),
            "alerts": active_alerts,
        },
        "ddi_regimen_matrix": ddi_matrix,
        "review_pending": ddi_review_status != "completed",
    }
    data["normalized_medication_list"] = meds
    data["ddi_review_status"] = ddi_review_status
    data["ddi_alert_bundle"] = ddi_bundle["ddi_alert_bundle"]
    data["ddi_regimen_matrix"] = ddi_matrix
    data["ddi_risk_bundle"] = ddi_bundle
    data["drug_interaction_reviewed"] = "1" if ddi_review_status == "completed" else "0"

    advanced_pro_bundle = build_advanced_pro_bundle(data)
    data["advanced_pro_bundle"] = advanced_pro_bundle
    cognitive_bundle = build_cognitive_screening_bundle(data)
    data["cognitive_screening_bundle"] = cognitive_bundle
    histology_bundle = build_variant_histology_bundle(data)
    data["variant_histology_bundle"] = histology_bundle
    data["rare_histology_variant"] = "1" if histology_bundle["rare_histology_variant"] else "0"
    data["adverse_histology_variant_type"] = histology_bundle["adverse_histology_variant_type"]
    if histology_bundle["neuroendocrine_features"]:
        data["neuroendocrine_features"] = "1"

    return data


# ──────────────────────────────────────────────────────────────────────────
# Auditoría Pacientes Insignia 2026-04-21 (§E.1) — docetaxel_fit canónico.
# Helpers de normalización publicados para evitar que rules_nccn, el trial
# matching engine y los copilots fragmenten la lógica de elegibilidad a
# docetaxel. `resolve_docetaxel_fit` devuelve bool (None→False para gates
# conservadores); `resolve_docetaxel_fit_override` devuelve Optional[bool]
# para callers que necesitan distinguir "Desconocido" y delegar en otra
# fuente (e.g. clinical_scores.docetaxel_fitness en m1_crpc/rules_nccn).
# ──────────────────────────────────────────────────────────────────────────


def resolve_docetaxel_fit_override(payload: dict[str, Any]) -> bool | None:
    """Devuelve el override explícito del clínico.

    True  → paciente apto (`"Apto (fit)"`, `"1"`, `"Sí"`, etc.)
    False → paciente NO apto (`"No apto"`, `"Marginal"`, `"0"`, etc.)
    None  → desconocido / sin documentar (el caller debe decidir fallback)

    Reconoce alias legacy `taxane_fitness`, `fit_for_docetaxel`,
    `chemotherapy_fitness`.
    """
    raw = payload.get("docetaxel_fit")
    if raw in (None, ""):
        raw = (
            payload.get("taxane_fitness")
            or payload.get("fit_for_docetaxel")
            or payload.get("chemotherapy_fitness")
        )
    txt = str(raw or "").strip().lower()
    if not txt or txt in {"desconocido", "desconocida", "unknown"}:
        return None
    if txt in {"1", "sí", "si", "yes", "true", "apto", "apto (fit)", "fit"}:
        return True
    if txt in {"0", "no", "false", "no apto", "unfit"}:
        return False
    if "marginal" in txt:
        # Conservador: marginal → no apto para gates de emisión docetaxel.
        return False
    return None


def resolve_docetaxel_fit(payload: dict[str, Any]) -> bool:
    """Wrapper seguro de `resolve_docetaxel_fit_override`: Desconocido→False.

    Úselo en gates donde ausencia de documentación implica NO emitir docetaxel
    (trial_matching_engine, mhspc_copilot_service). Si el caller necesita
    distinguir "no decidido", use `resolve_docetaxel_fit_override`.
    """
    override = resolve_docetaxel_fit_override(payload)
    return bool(override) if override is not None else False


def resolve_child_pugh_bc(payload: dict[str, Any]) -> bool:
    """Normaliza la señal `child_pugh_b_or_c` (bool) → equivalente a B/C.

    Usado por el gate de abiraterona. Canónico es `child_pugh_score` ∈ {A,B,C};
    los perfiles insignia de pacientes hardcodean `child_pugh_b_or_c` boolean.
    Devuelve True si:
      - `child_pugh_score` ∈ {B, C}, O
      - `child_pugh_b_or_c` o `child_pugh_class` truthy (perfil legacy)
    """
    score = str(payload.get("child_pugh_score") or "").upper().strip()
    if score in {"B", "C"}:
        return True
    boolean_alias = (
        payload.get("child_pugh_b_or_c")
        or payload.get("child_pugh_class")
    )
    return _truthy(boolean_alias)
