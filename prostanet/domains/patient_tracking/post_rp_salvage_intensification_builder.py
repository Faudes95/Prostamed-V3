from __future__ import annotations

from typing import Any


YES_VALUES = {"1", "true", "yes", "si", "sí", "positive", "positivo"}
NO_VALUES = {"0", "false", "no", "negative", "negativo"}
VERY_HIGH_STAGE_TOKENS = {"pt4", "pt4a", "pt4b", "pn1"}
HIGH_STAGE_TOKENS = {"pt3a", "pt3b", "pt3c", "pt4", "pt4a", "pt4b"}
SEMINAL_VESICLE_TOKENS = {"1", "true", "yes", "si", "sí", "positive", "positivo", "present", "presente"}
EXTRAPROSTATIC_TOKENS = {"1", "true", "yes", "si", "sí", "positive", "positivo", "present", "presente"}
LOCAL_PELVIC_PATTERNS = {"local_pelvic", "local/pélvico", "local/pelvico", "local pélvico", "local pelvico"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _normalize_text(value).lower() in YES_VALUES


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_post_rp_context(payload: dict[str, Any]) -> bool:
    if _truthy(payload.get("prior_prostatectomy")):
        return True
    if _normalize_text(payload.get("primary_treatment")).upper() in {
        "RP",
        "POST_RP",
        "PROSTATECTOMY",
        "RADICAL PROSTATECTOMY",
    }:
        return True
    return any(
        _normalize_text(payload.get(field))
        for field in (
            "rp_date",
            "prostatectomy_date",
            "pathologic_stage",
            "pathological_stage",
            "surgical_margin",
            "surgical_margin_status",
        )
    )


def _extract_grade_group(payload: dict[str, Any]) -> int | None:
    for key in ("grade_group", "isup_grade", "pathological_isup", "biopsy_grade_group"):
        value = _safe_float(payload.get(key))
        if value is not None:
            return int(value)
    gleason_text = _normalize_text(payload.get("gleason_score") or payload.get("pathologic_gleason"))
    if not gleason_text:
        return None
    if "5+" in gleason_text or gleason_text.startswith("9") or gleason_text.startswith("10"):
        return 5
    if "4+4" in gleason_text or "4+5" in gleason_text or "5+4" in gleason_text or gleason_text.startswith("8"):
        return 4
    if "4+3" in gleason_text:
        return 3
    if "3+4" in gleason_text:
        return 2
    if "3+3" in gleason_text or gleason_text.startswith("6"):
        return 1
    return None


def _positive_margin(payload: dict[str, Any]) -> bool:
    margin = _normalize_text(payload.get("surgical_margin") or payload.get("surgical_margin_status")).lower()
    if margin in YES_VALUES or margin in {"r1", "positive_margin", "positivo_extenso", "positive"}:
        return True
    margin_extent = _normalize_text(payload.get("positive_margin_extent") or payload.get("margin_extent")).lower()
    return any(token in margin_extent for token in ("extens", "multifocal", "long", "wide"))


def _pathologic_stage(payload: dict[str, Any]) -> str:
    return _normalize_text(payload.get("pathologic_stage") or payload.get("pathological_stage")).lower()


def _is_stage_high_risk(stage_text: str) -> bool:
    normalized = stage_text.replace(" ", "")
    return any(token in normalized for token in HIGH_STAGE_TOKENS)


def _is_stage_very_high(stage_text: str) -> bool:
    normalized = stage_text.replace(" ", "")
    return any(token in normalized for token in VERY_HIGH_STAGE_TOKENS)


def _has_local_pelvic_pattern(payload: dict[str, Any], psma_impact: dict[str, Any]) -> bool:
    psma_pattern = _normalize_text(psma_impact.get("clinical_pattern") or payload.get("psma_pet_result")).lower()
    if psma_pattern in LOCAL_PELVIC_PATTERNS:
        return True
    lesion_locations = str(payload.get("psma_lesion_locations") or "").lower()
    index_site = str(payload.get("psma_index_lesion_site") or "").lower()
    return "pelv" in lesion_locations or "pelv" in index_site


def _has_disseminated_pattern(payload: dict[str, Any], psma_impact: dict[str, Any]) -> bool:
    psma_pattern = _normalize_text(psma_impact.get("clinical_pattern") or payload.get("psma_pet_result")).lower()
    if psma_pattern in {"diseminado", "systemic"}:
        return True
    stage = _normalize_text(payload.get("psma_stage_after_psma") or payload.get("conventional_imaging_status")).upper()
    return stage in {"M1", "M1A", "M1B", "M1C"}


def build_post_rp_salvage_intensification_profile(
    payload: dict[str, Any] | None,
    *,
    psma_impact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    psma_impact = dict(psma_impact or {})
    available = _has_post_rp_context(payload)
    defaults = {
        "available": available,
        "risk_tier": "low",
        "high_risk_post_rp_salvage": False,
        "very_high_risk_post_rp_salvage": False,
        "high_risk_features_present": False,
        "high_risk_feature_keys": [],
        "salvage_intensification_preference": "rt_alone",
        "pelvic_rt_role": "not_indicated",
        "adt_duration_band": "none",
        "psma_restaging_role": "optional",
        "negative_psma_should_not_delay_salvage": False,
        "historical_trial_templates_applicable": [],
        "guideline_rationale": [],
        "companion_actions_required_for_preferred_regimen": [],
        "local_salvage_scope": "prostate_bed_only",
    }
    if not available:
        return defaults

    psa = _safe_float(payload.get("psa_current") or payload.get("psa") or payload.get("psa_postop"))
    psadt = _safe_float(payload.get("psadt_months"))
    time_to_recurrence = _safe_float(payload.get("time_to_recurrence_months"))
    post_rp_truth = dict(payload.get("post_rp_bcr_truth") or {})
    post_rp_course = _normalize_text(
        payload.get("post_prostatectomy_course")
        or payload.get("post_rp_course")
        or post_rp_truth.get("course")
    ).lower()
    salvage_feasible = _truthy(payload.get("salvage_local_feasible") or payload.get("eligible_pelvic_therapy"))
    conventional_stage = _normalize_text(
        payload.get("conventional_imaging_status")
        or ("M0" if _truthy(payload.get("conventional_imaging_m0") or payload.get("imaging_negative")) else "")
    ).upper()
    psma_done = _truthy(payload.get("psma_pet_done"))
    local_pelvic_pattern = _has_local_pelvic_pattern(payload, psma_impact)
    disseminated_pattern = _has_disseminated_pattern(payload, psma_impact)
    stage_text = _pathologic_stage(payload)
    grade_group = _extract_grade_group(payload)
    margin_positive = _positive_margin(payload)
    svi_positive = _normalize_text(payload.get("svi_status") or payload.get("seminal_vesicle_invasion")).lower() in SEMINAL_VESICLE_TOKENS
    ece_positive = _normalize_text(payload.get("ece_status") or payload.get("extraprostatic_extension")).lower() in EXTRAPROSTATIC_TOKENS
    lni_positive = _normalize_text(payload.get("lni_status") or payload.get("pn_status") or payload.get("node_status")).lower() in SEMINAL_VESICLE_TOKENS or "pn1" in stage_text
    eligible_pelvic = (
        _truthy(payload.get("eligible_pelvic_therapy"))
        or local_pelvic_pattern
        or lni_positive
        or svi_positive
    )

    high_risk_feature_keys: list[str] = []
    if psa is not None and psa >= 0.7:
        high_risk_feature_keys.append("psa_post_rp_ge_0_7")
    if post_rp_course == "persistent_psa" or _truthy(payload.get("postoperative_psa_persistent")):
        high_risk_feature_keys.append("persistent_psa")
    if time_to_recurrence is not None and time_to_recurrence <= 6:
        high_risk_feature_keys.append("time_to_recurrence_le_6m")
    if psadt is not None and psadt <= 6:
        high_risk_feature_keys.append("psadt_le_6m")
    if _is_stage_high_risk(stage_text):
        high_risk_feature_keys.append("pathologic_stage_ge_pt3")
    if svi_positive:
        high_risk_feature_keys.append("seminal_vesicle_invasion")
    if ece_positive:
        high_risk_feature_keys.append("extraprostatic_extension")
    if margin_positive:
        high_risk_feature_keys.append("positive_margin")
    if grade_group is not None and grade_group >= 4:
        high_risk_feature_keys.append("grade_group_4_5")
    if lni_positive:
        high_risk_feature_keys.append("node_positive")

    very_high_risk = any(
        key in high_risk_feature_keys
        for key in ("node_positive", "seminal_vesicle_invasion")
    ) or _is_stage_very_high(stage_text) or len(high_risk_feature_keys) >= 4
    high_risk = bool(high_risk_feature_keys)

    if disseminated_pattern or not salvage_feasible:
        defaults.update(
            {
                "risk_tier": "very_high" if very_high_risk else "high" if high_risk else "low",
                "high_risk_post_rp_salvage": high_risk,
                "very_high_risk_post_rp_salvage": very_high_risk,
                "high_risk_features_present": high_risk,
                "high_risk_feature_keys": high_risk_feature_keys,
                "guideline_rationale": [
                    "La intensificación local solo tiene sentido mientras la vía de salvage curativo siga siendo plausible.",
                ],
            }
        )
        return defaults

    risk_tier = "very_high" if very_high_risk else "high" if high_risk else "low"
    pelvic_rt_role = "not_indicated"
    if high_risk and eligible_pelvic:
        pelvic_rt_role = "preferred" if local_pelvic_pattern or any(
            key in high_risk_feature_keys for key in ("node_positive", "seminal_vesicle_invasion")
        ) else "consider"

    adt_duration_band = "none"
    if high_risk:
        adt_duration_band = "4_6_months"
    if very_high_risk or len(high_risk_feature_keys) >= 3 or (psa is not None and psa >= 1.0):
        adt_duration_band = "discuss_6_24_months"
    if any(key in high_risk_feature_keys for key in ("node_positive",)) or _is_stage_very_high(stage_text):
        adt_duration_band = "18_24_months"

    if risk_tier == "low":
        preference = "rt_alone"
    elif pelvic_rt_role == "preferred":
        preference = "rt_pelvic_short_adt"
    elif adt_duration_band == "18_24_months":
        preference = "rt_extended_adt"
    else:
        preference = "rt_short_adt"

    psma_restaging_role = (
        "already_completed"
        if psma_done
        else "urgent_companion"
        if high_risk and conventional_stage in {"", "M0", "NEGATIVE", "NOT_RESTAGED"}
        else "optional"
    )
    companion_actions: list[str] = []
    if psma_restaging_role == "urgent_companion":
        companion_actions.append(
            "Solicitar PSMA PET/CT urgente para definir lecho solo versus lecho + pelvis y descartar redirección sistémica."
        )
    if high_risk and any(key not in payload or payload.get(key) in (None, "") for key in ("pathologic_stage", "surgical_margin", "psadt_months")):
        companion_actions.append(
            "Revisar patología de alto riesgo y cinética (PSADT) para cerrar intensidad y duración de ADT."
        )
    if high_risk:
        companion_actions.append("Definir duración de ADT según perfil de alto riesgo dentro del rango de 4-24 meses.")
    if pelvic_rt_role in {"consider", "preferred"}:
        companion_actions.append("Decidir si incluir pelvis electiva durante la SRT según riesgo nodal e imagen.")

    guideline_rationale = [
        "La ventana curativa post-RP sigue siendo prioritaria, pero los rasgos de alto riesgo ya no justifican RT sola por defecto.",
    ]
    if high_risk:
        guideline_rationale.append(
            "Los high-risk features post-RP favorecen añadir ADT concomitante a la radioterapia de rescate."
        )
    if pelvic_rt_role in {"consider", "preferred"}:
        guideline_rationale.append(
            "El beneficio pélvico debe discutirse cuando la biología o la imagen sugieren riesgo nodal relevante."
        )
    if psma_restaging_role == "urgent_companion":
        guideline_rationale.append(
            "PSMA PET/CT debe modelarse como companion urgente que cambia alcance/campo, no como excusa para retrasar salvage si sigue siendo curativo."
        )

    trial_templates: list[str] = []
    if high_risk:
        trial_templates.append("GETUG-AFU 16")
    if pelvic_rt_role in {"consider", "preferred"}:
        trial_templates.append("SPPORT")
    if adt_duration_band in {"discuss_6_24_months", "18_24_months"}:
        trial_templates.extend(["RTOG 9601", "RADICALS-HD"])

    return {
        "available": True,
        "risk_tier": risk_tier,
        "high_risk_post_rp_salvage": high_risk,
        "very_high_risk_post_rp_salvage": very_high_risk,
        "high_risk_features_present": high_risk,
        "high_risk_feature_keys": high_risk_feature_keys,
        "salvage_intensification_preference": preference,
        "pelvic_rt_role": pelvic_rt_role,
        "adt_duration_band": adt_duration_band,
        "psma_restaging_role": psma_restaging_role,
        "negative_psma_should_not_delay_salvage": psma_restaging_role == "urgent_companion",
        "historical_trial_templates_applicable": trial_templates,
        "guideline_rationale": guideline_rationale,
        "companion_actions_required_for_preferred_regimen": companion_actions,
        "local_salvage_scope": "prostate_bed_plus_pelvis"
        if pelvic_rt_role == "preferred"
        else "prostate_bed_favored_with_pelvic_consideration"
        if pelvic_rt_role == "consider"
        else "prostate_bed_only",
        "clinical_context_basis": {
            "psa_current": psa,
            "psadt_months": psadt,
            "time_to_recurrence_months": time_to_recurrence,
            "post_prostatectomy_course": post_rp_course,
            "conventional_imaging_status": conventional_stage or "NOT_RESTAGED",
            "psma_done": psma_done,
            "local_pelvic_pattern": local_pelvic_pattern,
        },
    }
