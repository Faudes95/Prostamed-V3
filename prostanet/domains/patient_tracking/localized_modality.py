from __future__ import annotations

from typing import Any

from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.shared.life_expectancy import classify_localized_life_expectancy_band
from prostanet.shared.pcothercause import apply_pcothercause_life_expectancy


CANONICAL_LOCALIZED_PRIORITIES = [
    "maximize_cancer_control",
    "preserve_urinary_function",
    "preserve_sexual_function",
    "avoid_bowel_toxicity",
    "avoid_surgery",
    "avoid_radiation",
    "minimize_treatment_burden",
]

_PRIORITY_SYNONYMS = {
    "maximize_cancer_control": {
        "maximize_cancer_control",
        "curacion",
        "curación",
        "oncologic_control",
        "maximize_control",
        "control oncologico",
        "control oncológico",
    },
    "preserve_urinary_function": {
        "preserve_urinary_function",
        "preservar funcion urinaria",
        "preservar función urinaria",
        "funcion urinaria",
        "función urinaria",
        "evitar incontinencia",
    },
    "preserve_sexual_function": {
        "preserve_sexual_function",
        "preservar funcion sexual",
        "preservar función sexual",
        "funcion sexual",
        "función sexual",
        "sexual function",
    },
    "avoid_bowel_toxicity": {
        "avoid_bowel_toxicity",
        "evitar toxicidad intestinal",
        "preservar funcion intestinal",
        "preservar función intestinal",
        "intestino",
        "bowel",
    },
    "avoid_surgery": {
        "avoid_surgery",
        "evitar cirugia",
        "evitar cirugía",
        "no surgery",
    },
    "avoid_radiation": {
        "avoid_radiation",
        "evitar radiacion",
        "evitar radiación",
        "evitar rt",
        "no radiation",
    },
    "minimize_treatment_burden": {
        "minimize_treatment_burden",
        "minimizar carga",
        "minimizar burden",
        "menos visitas",
        "less visits",
        "menor carga terapeutica",
        "menor carga terapéutica",
    },
}


def _is_present(value: Any) -> bool:
    if value in (
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
    ):
        return False
    if isinstance(value, str) and value.strip().lower() in {
        "pending",
        "pendiente",
        "unknown",
        "desconocido",
        "desconocida",
    }:
        return False
    return True


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_key(value: Any) -> str:
    return _normalized_text(value).lower()


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
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "suspicious", "sospechoso"}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if _normalized_text(item)))


def _localized_epic26_shared_decision_signals(
    *,
    urinary_incontinence_qol: float | None,
    urinary_irritative_qol: float | None,
    bowel_qol: float | None,
    sexual_qol: float | None,
    hormonal_qol: float | None,
    rt_likely_requires_adt: bool,
    priorities: list[str],
) -> list[str]:
    signals: list[str] = []
    if urinary_irritative_qol is not None and urinary_irritative_qol <= 60:
        signals.append(
            "El EPIC-26 urinario irritativo/obstructivo bajo debe usarse para anticipar toxicidad urinaria y comparar la carga funcional esperable de radioterapia, sin desplazar por sí solo la lógica oncológica principal."
        )
    if bowel_qol is not None and bowel_qol <= 60:
        signals.append(
            "El EPIC-26 intestinal bajo obliga a discutir toxicidad intestinal esperable y calidad de vida basal antes de elegir entre cirugía y radioterapia."
        )
    if rt_likely_requires_adt and hormonal_qol is not None and hormonal_qol <= 60:
        signals.append(
            "El EPIC-26 hormonal bajo debe contextualizar el costo funcional de una ruta radioterápica que probablemente requiera ADT, como apoyo de decisión compartida y seguimiento."
        )
    if urinary_incontinence_qol is not None and urinary_incontinence_qol <= 60:
        signals.append(
            "La incontinencia urinaria basal medida por EPIC-26 debe registrarse como línea basal para counseling pretratamiento y recuperación funcional posterior."
        )
    if sexual_qol is not None and sexual_qol >= 70 and "preserve_sexual_function" in priorities:
        signals.append(
            "La función sexual basal preservada por EPIC-26 hace especialmente importante comparar el costo sexual relativo entre estrategias locales en la conversación compartida."
        )
    return _dedupe(signals)


def _localized_epic26_governance_contract() -> dict[str, Any]:
    return {
        "available": True,
        "governance_status": "baseline_tradeoff_followup_quality_only",
        "primary_guideline_driver": "nccn_2026",
        "instrument_role_summary": (
            "EPIC-26 en enfermedad localizada debe usarse como línea basal funcional, comparación de toxicidad esperable, seguimiento de recuperación, detección de deterioro clínicamente relevante, decisión compartida e indicador de calidad asistencial."
        ),
        "allowed_influence_domains": [
            "baseline_functional_capture",
            "toxicity_expectation",
            "shared_decision",
            "functional_recovery_followup",
            "clinically_relevant_deterioration_detection",
            "quality_of_care_metrics",
        ],
        "disallowed_as_primary_driver_for": [
            "dominant_modality",
            "oncologic_risk_stratification",
            "radiotherapy_status",
            "surgery_status",
            "active_surveillance_status",
        ],
        "allowed_to_inform_but_not_override": [
            "rp_vs_rt_tradeoff_explanation",
            "treatment_specific_counseling",
            "rehabilitation_or_supportive_referral",
            "followup_symptom_surveillance",
        ],
        "governance_guardrail": (
            "Los dominios EPIC-26 no deben cambiar por sí solos la modalidad dominante ni degradar una modalidad local cuando el riesgo oncológico, la factibilidad y la aptitud objetiva permanecen favorables."
        ),
    }


def parse_patient_priority_profile(value: Any) -> list[str]:
    raw_values: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    elif _is_present(value):
        raw_values = str(value).replace("|", ",").replace(";", ",").split(",")
    normalized: list[str] = []
    for item in raw_values:
        token = _normalized_key(item)
        if not token:
            continue
        mapped = next(
            (
                canonical
                for canonical, synonyms in _PRIORITY_SYNONYMS.items()
                if token == canonical or token in synonyms
            ),
            "",
        )
        if mapped:
            normalized.append(mapped)
    return _dedupe(normalized)


def normalized_localized_values(field_values: dict[str, Any]) -> dict[str, Any]:
    values = apply_pcothercause_life_expectancy(normalize_epic26_payload(field_values or {}))
    if not _is_present(values.get("ipss_total")) and _is_present(values.get("ipss_score")):
        values["ipss_total"] = values.get("ipss_score")
    if not _is_present(values.get("pirads_score")) and _is_present(values.get("prior_mpmri_pirads_score")):
        values["pirads_score"] = values.get("prior_mpmri_pirads_score")
    if not _is_present(values.get("ecog_score")) and _is_present(values.get("ecog")):
        values["ecog_score"] = values.get("ecog")
    if not _is_present(values.get("charlson_score")) and _is_present(values.get("charlson_index")):
        values["charlson_score"] = values.get("charlson_index")
    values["patient_priority_profile"] = parse_patient_priority_profile(values.get("patient_priority_profile"))
    return values


def build_localized_survival_context_bundle(field_values: dict[str, Any]) -> dict[str, Any]:
    values = normalized_localized_values(field_values)
    life_expectancy = _safe_float(values.get("life_expectancy_years"))
    life_expectancy_band = classify_localized_life_expectancy_band(life_expectancy)
    ecog = _safe_int(values.get("ecog_score"))
    charlson = _safe_int(values.get("charlson_score"))
    g8 = _safe_float(values.get("g8_score"))
    frailty = _normalized_key(values.get("frailty_status"))
    anesthesia = _normalized_key(values.get("anesthesia_surgical_fitness"))
    occam_bundle = values.get("occam_life_expectancy_bundle") or {}

    reasons: list[str] = []
    benefit_horizon_band = "uncertain"
    prefer_observation = False

    if life_expectancy_band["available"]:
        if life_expectancy_band["band"] == "le_5_years":
            benefit_horizon_band = "limited_benefit"
            prefer_observation = True
            if occam_bundle.get("available") and occam_bundle.get("source") == "pcothercause_public_repo":
                reasons.append("La expectativa de vida derivada por OCCAM y ajustada por ECOG/Charlson cae en el rango ≤5 años y hace muy improbable un beneficio neto de terapia local definitiva.")
            else:
                reasons.append("La expectativa de vida estructurada cae en el rango ≤5 años y hace muy improbable un beneficio neto de terapia local definitiva.")
        elif life_expectancy_band["band"] == "between_5_and_10_years":
            benefit_horizon_band = "limited_benefit"
            prefer_observation = True
            if occam_bundle.get("available") and occam_bundle.get("source") == "pcothercause_public_repo":
                reasons.append("La expectativa de vida derivada por OCCAM y ajustada por ECOG/Charlson cae entre 5 y 10 años y favorece observación sobre intensificación local automática.")
            else:
                reasons.append("La expectativa de vida estructurada cae entre 5 y 10 años y favorece observación sobre intensificación local automática.")
        else:
            benefit_horizon_band = "favorable_local_therapy"
            if occam_bundle.get("available") and occam_bundle.get("source") == "pcothercause_public_repo":
                reasons.append("La expectativa de vida derivada por OCCAM y ajustada por ECOG/Charlson sigue favoreciendo una discusión de terapia local definitiva.")
            else:
                reasons.append("La expectativa de vida estructurada sigue favoreciendo una discusión de terapia local definitiva.")

    if ecog is not None:
        if ecog >= 3:
            benefit_horizon_band = "limited_benefit"
            prefer_observation = True
            reasons.append("ECOG 3-4 reduce de forma importante el beneficio práctico de una terapia local agresiva.")
        elif ecog == 2 and benefit_horizon_band == "uncertain":
            benefit_horizon_band = "uncertain"
            reasons.append("ECOG 2 obliga a matizar la intensidad local con mayor prudencia.")
        elif ecog <= 1 and benefit_horizon_band == "uncertain":
            benefit_horizon_band = "favorable_local_therapy"
            reasons.append("ECOG 0-1 sostiene beneficio potencial de tratamiento local curativo.")

    if anesthesia in {"no apto", "not_fit", "not-fit"}:
        benefit_horizon_band = "limited_benefit"
        prefer_observation = True
        reasons.append("La aptitud anestésico-quirúrgica no permite asumir una terapia local invasiva como trayecto principal.")
    elif anesthesia == "vulnerable":
        reasons.append("La aptitud anestésico-quirúrgica vulnerable obliga a individualizar la modalidad local.")

    if frailty == "frail":
        benefit_horizon_band = "limited_benefit"
        prefer_observation = True
        reasons.append("La fragilidad clínica avanzada reduce el beneficio neto de intensificación local.")
    elif frailty == "vulnerable":
        reasons.append("La vulnerabilidad geriátrica obliga a discutir tratamiento local con soporte y selección más fina.")

    if g8 is not None:
        if g8 <= 14:
            reasons.append("Un G8 <=14 sugiere vulnerabilidad geriátrica relevante.")
            if benefit_horizon_band == "favorable_local_therapy":
                benefit_horizon_band = "uncertain"
        elif g8 > 14 and benefit_horizon_band == "uncertain":
            benefit_horizon_band = "favorable_local_therapy"

    if charlson is not None:
        if charlson >= 5:
            benefit_horizon_band = "limited_benefit"
            prefer_observation = True
            reasons.append("La carga de comorbilidad por Charlson es alta y reduce el rendimiento real de una terapia local agresiva.")
        elif charlson >= 3:
            reasons.append("El índice de Charlson elevado obliga a individualizar cirugía frente a radioterapia.")

    missing_objective_context = [
        field
        for field in ["ecog_score", "charlson_score", "frailty_status", "g8_score", "anesthesia_surgical_fitness"]
        if not _is_present(values.get(field))
    ]
    if benefit_horizon_band == "uncertain" and not reasons:
        reasons.append("Falta estructura objetiva de fitness/comorbilidad para cerrar el horizonte de beneficio local.")

    return {
        "available": True,
        "benefit_horizon_band": benefit_horizon_band,
        "life_expectancy_horizon_band": life_expectancy_band["band"],
        "life_expectancy_horizon_label": life_expectancy_band["band_label_es"],
        "observation_guidance": life_expectancy_band["observation_guidance"],
        "observation_preference_strength": life_expectancy_band["observation_preference_strength"],
        "prefer_observation": prefer_observation,
        "objective_survival_context_missing": missing_objective_context,
        "occam_life_expectancy_bundle": occam_bundle,
        "summary": " ".join(_dedupe(reasons)),
        "reasons": _dedupe(reasons),
    }


def build_radical_prostatectomy_candidacy_profile(
    field_values: dict[str, Any],
    *,
    nccn_group: str = "",
) -> dict[str, Any]:
    values = normalized_localized_values(field_values)
    risk_group = _normalized_key(nccn_group).upper()
    ecog = _safe_int(values.get("ecog_score"))
    charlson = _safe_int(values.get("charlson_score"))
    g8 = _safe_float(values.get("g8_score"))
    frailty = _normalized_key(values.get("frailty_status"))
    anesthesia = _normalized_key(values.get("anesthesia_surgical_fitness"))
    nodal_status = _normalized_text(values.get("nodal_status")).upper()
    metastasis_site = _normalized_text(values.get("metastasis_site")).upper()
    clinical_tstage = _normalized_text(values.get("clinical_tstage")).upper()
    plnd_likely = _normalized_key(values.get("plnd_likely_indicated"))

    missing_candidate_fields = [
        field
        for field in [
            "clinical_tstage",
            "nodal_status",
            "metastasis_site",
            "ecog_score",
            "charlson_score",
            "frailty_status",
            "g8_score",
            "anesthesia_surgical_fitness",
        ]
        if not _is_present(values.get(field))
    ]

    oncologic_reasons: list[str] = []
    fitness_reasons: list[str] = []
    candidate_status = "candidate"

    if metastasis_site and metastasis_site != "M0":
        candidate_status = "not_candidate"
        oncologic_reasons.append("La presencia de metástasis a distancia aleja la prostatectomía radical como estrategia principal.")

    if nodal_status == "N1":
        oncologic_reasons.append("El compromiso ganglionar regional obliga a selección quirúrgica muy cuidadosa y estrategia multimodal.")
        if candidate_status == "candidate":
            candidate_status = "provisional"

    if clinical_tstage == "T4":
        oncologic_reasons.append("cT4 vuelve la cirugía una estrategia altamente seleccionada, no automática.")
        if candidate_status == "candidate":
            candidate_status = "provisional"
    elif clinical_tstage == "T3B":
        oncologic_reasons.append("cT3b exige valorar experiencia del centro y rol multimodal antes de liberar prostatectomía radical.")
        if candidate_status == "candidate":
            candidate_status = "provisional"

    if anesthesia in {"no apto", "not_fit", "not-fit"}:
        candidate_status = "not_candidate"
        fitness_reasons.append("La aptitud anestésico-quirúrgica documenta que hoy no es candidato a cirugía.")
    elif anesthesia == "vulnerable":
        fitness_reasons.append("La aptitud anestésico-quirúrgica es vulnerable y obliga a selección cuidadosa.")
        if candidate_status == "candidate":
            candidate_status = "provisional"

    if ecog is not None:
        if ecog >= 3:
            candidate_status = "not_candidate"
            fitness_reasons.append("ECOG 3-4 desplaza la cirugía fuera de la candidatura razonable.")
        elif ecog == 2:
            fitness_reasons.append("ECOG 2 vuelve la candidatura quirúrgica sólo provisional.")
            if candidate_status == "candidate":
                candidate_status = "provisional"

    if frailty == "frail":
        candidate_status = "not_candidate"
        fitness_reasons.append("La fragilidad clínica avanzada desaconseja prostatectomía radical como opción dominante.")
    elif frailty == "vulnerable":
        fitness_reasons.append("La vulnerabilidad geriátrica hace la candidatura quirúrgica provisional.")
        if candidate_status == "candidate":
            candidate_status = "provisional"

    if g8 is not None:
        if g8 <= 14:
            fitness_reasons.append("G8 <=14 sugiere vulnerabilidad geriátrica relevante.")
            if candidate_status == "candidate":
                candidate_status = "provisional"
        elif g8 > 14 and candidate_status == "candidate":
            fitness_reasons.append("G8 >14 apoya reserva funcional aceptable para discutir cirugía.")

    if charlson is not None:
        if charlson >= 5:
            candidate_status = "not_candidate"
            fitness_reasons.append("El índice de Charlson muy alto reduce demasiado el beneficio neto de cirugía.")
        elif charlson >= 3:
            fitness_reasons.append("El índice de Charlson elevado obliga a cautela antes de liberar cirugía.")
            if candidate_status == "candidate":
                candidate_status = "provisional"

    if missing_candidate_fields and candidate_status == "candidate":
        candidate_status = "provisional"
        fitness_reasons.append("Faltan escalas objetivas de fitness/comorbilidad para cerrar candidatura quirúrgica con trazabilidad.")

    plnd_role = "consider"
    if plnd_likely == "1" or risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"}:
        plnd_role = "preferred"
    elif plnd_likely == "0":
        plnd_role = "not_indicated"

    surgery_status = {
        "candidate": "reasonable",
        "provisional": "provisional",
        "not_candidate": "blocked",
    }[candidate_status]

    summary_parts = oncologic_reasons + fitness_reasons
    if not summary_parts and candidate_status == "candidate":
        summary_parts.append("La candidatura a prostatectomía radical es razonable con los datos objetivos actuales.")

    return {
        "available": True,
        "candidate_status": candidate_status,
        "surgery_status": surgery_status,
        "missing_candidate_fields": missing_candidate_fields,
        "oncologic_reasons": _dedupe(oncologic_reasons),
        "fitness_reasons": _dedupe(fitness_reasons),
        "plnd_role": plnd_role,
        "candidate_summary": " ".join(_dedupe(summary_parts)),
    }


def build_active_surveillance_monitoring_profile(
    field_values: dict[str, Any],
    *,
    as_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = normalized_localized_values(field_values)
    as_position = dict(as_position or {})
    confirmatory_biopsy_planned = _truthy(values.get("confirmatory_biopsy_planned"))
    eligible = bool(as_position.get("eligible"))
    as_status = _normalized_key(as_position.get("status"))
    monitoring_required = eligible or as_status in {"preferred", "selected_candidate", "observation_preferred"}
    return {
        "available": True,
        "monitoring_scope": "active_surveillance_only",
        "should_surface_in_definitive_flow": False,
        "active_surveillance_relevant": monitoring_required,
        "confirmatory_biopsy_planned": confirmatory_biopsy_planned,
        "status": "monitoring_ready" if monitoring_required and confirmatory_biopsy_planned else "monitoring_incomplete" if monitoring_required else "not_applicable",
        "summary": (
            "Los requisitos de biopsia confirmatoria pertenecen al carril de vigilancia activa y no deben bloquear por sí solos la decisión RP vs RT."
            if monitoring_required
            else "La monitorización tipo vigilancia activa no debe contaminar la decisión local definitiva en este contexto."
        ),
    }


def should_require_localized_modality_dataset(
    field_values: dict[str, Any],
    *,
    nccn_group: str = "",
    as_position: dict[str, Any] | None = None,
) -> bool:
    values = normalized_localized_values(field_values)
    as_position = dict(as_position or {})
    risk_group = _normalized_key(nccn_group).upper()
    pirads = _safe_float(values.get("pirads_score"))
    targeted_status = _normalized_key(values.get("prior_mpmri_targeted_biopsy_status"))
    adverse_histology = _truthy(values.get("cribriform_pattern")) or _truthy(values.get("intraductal_carcinoma"))
    as_status = _normalized_key(as_position.get("status"))
    as_eligible = bool(as_position.get("eligible"))
    survival_context = build_localized_survival_context_bundle(values)
    low_risk_watchful = risk_group == "LOW" and bool(survival_context.get("prefer_observation"))
    clean_low_risk_as = (
        risk_group == "LOW"
        and as_eligible
        and as_status in {"preferred", "selected_candidate"}
        and not adverse_histology
        and not (pirads is not None and pirads >= 4 and targeted_status != "si")
    )
    return not (low_risk_watchful or clean_low_risk_as)


def _modality_priority_alignment(priorities: list[str], modality: str) -> str:
    if not priorities:
        return "neutral"
    if modality == "active_surveillance":
        if (
            "minimize_treatment_burden" in priorities
            or "preserve_urinary_function" in priorities
            or "preserve_sexual_function" in priorities
        ):
            return "high"
        if "maximize_cancer_control" in priorities:
            return "mixed"
    if modality == "surgery":
        if "avoid_surgery" in priorities:
            return "low"
        if "maximize_cancer_control" in priorities or "avoid_radiation" in priorities:
            return "high"
    if modality == "radiotherapy":
        if "avoid_radiation" in priorities:
            return "low"
        if "preserve_sexual_function" in priorities or "avoid_surgery" in priorities:
            return "high"
        if "avoid_bowel_toxicity" in priorities:
            return "mixed"
    if modality == "observation":
        if "minimize_treatment_burden" in priorities:
            return "high"
    if modality == "multimodal_local":
        if "maximize_cancer_control" in priorities:
            return "high"
    return "neutral"


def build_localized_modality_fitness_bundle(
    field_values: dict[str, Any],
    *,
    nccn_group: str = "",
    as_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = normalized_localized_values(field_values)
    as_position = dict(as_position or {})
    risk_group = _normalized_key(nccn_group).upper()
    priorities = list(values.get("patient_priority_profile") or [])
    pirads = _safe_float(values.get("pirads_score"))
    ipss = _safe_float(values.get("ipss_total"))
    iief = _safe_float(values.get("iief5_score"))
    urinary_incontinence_qol = _safe_float(values.get("epic26_urinary_incontinence_domain"))
    urinary_irritative_qol = _safe_float(values.get("epic26_urinary_irritative_domain"))
    sexual_qol = _safe_float(values.get("epic26_sexual_domain"))
    bowel_qol = _safe_float(values.get("epic26_bowel_domain"))
    hormonal_qol = _safe_float(values.get("epic26_hormonal_domain"))
    prostate_volume = _safe_float(values.get("prostate_volume_ml"))
    g8 = _safe_float(values.get("g8_score"))
    frailty = _normalized_key(values.get("frailty_status"))
    anesthesia = _normalized_key(values.get("anesthesia_surgical_fitness"))
    rt_feasibility = _normalized_key(values.get("radiotherapy_feasibility"))
    brachy_feasibility = _normalized_key(values.get("brachy_feasibility"))
    obstruction = _normalized_key(values.get("baseline_obstruction"))
    targeted_status = _normalized_key(values.get("prior_mpmri_targeted_biopsy_status"))
    plnd_likely = _normalized_key(values.get("plnd_likely_indicated"))
    as_status = _normalized_key(as_position.get("status"))
    as_eligible = bool(as_position.get("eligible"))
    adverse_histology = _truthy(values.get("cribriform_pattern")) or _truthy(values.get("intraductal_carcinoma"))

    survival_context_bundle = build_localized_survival_context_bundle(values)
    rp_candidacy_profile = build_radical_prostatectomy_candidacy_profile(values, nccn_group=nccn_group)
    active_surveillance_monitoring_profile = build_active_surveillance_monitoring_profile(values, as_position=as_position)

    missing_modality_fields = [
        field
        for field in [
            "ecog_score",
            "charlson_score",
            "frailty_status",
            "g8_score",
            "anesthesia_surgical_fitness",
            "radiotherapy_feasibility",
            "clinical_tstage",
            "nodal_status",
            "metastasis_site",
        ]
        if not _is_present(values.get(field))
    ]
    modality_tradeoff_gaps = [
        field
        for field in [
            "ipss_total",
            "iief5_score",
            "epic26_urinary_incontinence_domain",
            "epic26_urinary_irritative_domain",
            "epic26_sexual_domain",
            "epic26_bowel_domain",
            "epic26_hormonal_domain",
            "patient_priority_profile",
            "prostate_volume_ml",
            "plnd_likely_indicated",
            "brachy_feasibility",
            "baseline_obstruction",
        ]
        if field == "patient_priority_profile"
        and not priorities
        or field != "patient_priority_profile"
        and not _is_present(values.get(field))
    ]

    as_reasons: list[str] = []
    surgery_reasons = list(rp_candidacy_profile.get("oncologic_reasons") or []) + list(rp_candidacy_profile.get("fitness_reasons") or [])
    rt_reasons: list[str] = []
    epic26_role_summary = (
        "EPIC-26 se usa en localizada como línea basal funcional, comparación de toxicidad esperable, seguimiento de recuperación, detección de deterioro clínicamente relevante, decisión compartida e indicadores de calidad; no sustituye la lógica principal NCCN 2026."
    )
    epic26_governance_contract = _localized_epic26_governance_contract()

    active_surveillance_status = "reasonable"
    if not as_eligible or as_status in {"not_recommended", "not_preferred"} or adverse_histology:
        active_surveillance_status = "blocked"
        as_reasons.append(as_position.get("summary") or "La biología actual ya no sostiene vigilancia activa como trayectoria principal.")
    elif pirads is not None and pirads >= 4 and targeted_status != "si":
        active_surveillance_status = "provisional"
        as_reasons.append("PI-RADS 4-5 sin biopsia dirigida documentada reduce la solidez de vigilancia activa.")
    elif risk_group in {"FAVORABLE INTERMEDIATE"}:
        active_surveillance_status = "provisional"
        as_reasons.append("La vigilancia activa solo compite si la biología y el seguimiento estructurado siguen siendo muy favorables.")
    else:
        as_reasons.append("La biología actual todavía permite vigilancia activa estructurada.")

    surgery_status = str(rp_candidacy_profile.get("surgery_status") or "provisional")

    radiotherapy_status = "reasonable"
    if rt_feasibility in {"not_feasible", "not_feasible_rt", "not_feasible_radiotherapy"}:
        radiotherapy_status = "blocked"
        rt_reasons.append("La factibilidad radioterápica actual no está confirmada como viable.")
    elif rt_feasibility in {"conditional", "unknown", ""}:
        radiotherapy_status = "provisional"
        rt_reasons.append("La factibilidad técnica de radioterapia aún está incompleta.")
    if (ipss is not None and ipss >= 18) or obstruction == "severe" or (prostate_volume is not None and prostate_volume >= 80):
        rt_reasons.append("IPSS alto, obstrucción relevante o volumen prostático grande pueden volver menos limpia la ruta radioterápica/braquiterapia.")
        if radiotherapy_status == "reasonable":
            radiotherapy_status = "provisional"
    rt_likely_requires_adt = risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"}
    epic26_shared_decision_signals = _localized_epic26_shared_decision_signals(
        urinary_incontinence_qol=urinary_incontinence_qol,
        urinary_irritative_qol=urinary_irritative_qol,
        bowel_qol=bowel_qol,
        sexual_qol=sexual_qol,
        hormonal_qol=hormonal_qol,
        rt_likely_requires_adt=rt_likely_requires_adt,
        priorities=priorities,
    )
    if "avoid_radiation" in priorities:
        rt_reasons.append("El paciente prioriza evitar radiación.")
        if radiotherapy_status == "reasonable":
            radiotherapy_status = "provisional"
    if frailty in {"frail", "vulnerable"} or (g8 is not None and g8 <= 14) or anesthesia in {"vulnerable", "no apto", "not_fit"}:
        rt_reasons.append("La fragilidad o la aptitud quirúrgica limitada hacen más visible una ruta no quirúrgica.")

    reasonable_modalities = [
        modality
        for modality, status in {
            "active_surveillance": active_surveillance_status,
            "surgery": surgery_status,
            "radiotherapy": radiotherapy_status,
        }.items()
        if status == "reasonable"
    ]

    dominant_modality = "radiotherapy"
    dominance_reason = "El grupo de riesgo y la aptitud basal siguen favoreciendo radioterapia como trayectoria inicial."
    modality_status = "clear"

    if risk_group in {"LOW", "FAVORABLE INTERMEDIATE"} and survival_context_bundle.get("prefer_observation"):
        dominant_modality = "observation"
        dominance_reason = survival_context_bundle.get("summary") or "El horizonte de beneficio local parece limitado y hace razonable observación."
    elif active_surveillance_status == "reasonable" and risk_group == "LOW":
        dominant_modality = "active_surveillance"
        dominance_reason = "La biología y la estructura de vigilancia aún sostienen vigilancia activa como estrategia dominante."
    elif risk_group in {"VERY HIGH", "REGIONAL N1M0"} and radiotherapy_status != "blocked":
        dominant_modality = "multimodal_local"
        dominance_reason = "El riesgo muy alto/regional suele requerir control local con intensificación sistémica, no una modalidad local aislada."
    else:
        surgery_score = 0
        rt_score = 0
        if risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"}:
            rt_score += 2
        if risk_group in {"FAVORABLE INTERMEDIATE", "UNFAVORABLE INTERMEDIATE", "HIGH"}:
            surgery_score += 1
        if "avoid_radiation" in priorities:
            surgery_score += 2
            rt_score -= 2
        if "avoid_surgery" in priorities:
            surgery_score -= 2
            rt_score += 2
        # EPIC-26 sexual baseline supports shared decision and counseling, but
        # it must not become a primary driver of dominant modality selection.
        if "preserve_sexual_function" in priorities and (iief is not None and iief >= 17):
            rt_score += 1
            surgery_score -= 1
        if (ipss is not None and ipss >= 15) or obstruction in {"moderate", "severe"}:
            surgery_score += 1
            rt_score -= 1
        if surgery_status == "blocked":
            surgery_score -= 5
        elif surgery_status == "provisional":
            surgery_score -= 1
        if radiotherapy_status == "blocked":
            rt_score -= 5
        elif radiotherapy_status == "provisional":
            rt_score -= 1
        if surgery_score > rt_score:
            dominant_modality = "surgery"
            dominance_reason = rp_candidacy_profile.get("candidate_summary") or "La combinación de factibilidad anatómica, fitness y prioridades del paciente favorece cirugía hoy."
        elif rt_score == surgery_score and surgery_status != "blocked" and radiotherapy_status != "blocked":
            dominant_modality = "radiotherapy"
            modality_status = "provisional"
            dominance_reason = "Cirugía y radioterapia son oncológicamente cercanas; hoy la diferencia es funcional o preferencial."
        else:
            dominant_modality = "radiotherapy"
            dominance_reason = "El balance entre riesgo oncológico, aptitud quirúrgica y costo funcional favorece radioterapia hoy."

    if surgery_status == "blocked" and radiotherapy_status == "blocked" and active_surveillance_status != "reasonable":
        modality_status = "blocked"
    elif missing_modality_fields or surgery_status == "provisional" or radiotherapy_status == "provisional":
        modality_status = "provisional"

    tradeoff_real = dominant_modality in {"surgery", "radiotherapy"} and surgery_status != "blocked" and radiotherapy_status != "blocked"
    shared_decision_required = "yes" if tradeoff_real or dominant_modality in {"active_surveillance", "multimodal_local"} else "no"
    if tradeoff_real and not priorities:
        modality_status = "provisional"
        dominance_reason = (
            f"{dominance_reason} Faltan prioridades explícitas del paciente para cerrar el desempate con plena trazabilidad."
        )

    field_that_would_change_answer = missing_modality_fields[0] if missing_modality_fields else ""
    modality_competitors = _dedupe(
        [
            modality
            for modality in [dominant_modality, "surgery", "radiotherapy", "active_surveillance"]
            if modality != dominant_modality
            and {
                "surgery": surgery_status,
                "radiotherapy": radiotherapy_status,
                "active_surveillance": active_surveillance_status,
            }.get(modality)
            in {"reasonable", "provisional"}
        ]
    )
    tradeoff_summary = (
        "Cuando cirugía y radioterapia compiten, las escalas funcionales validadas refinan la conversación compartida y la comparación de toxicidad esperable, sin sustituir la lógica oncológica principal."
        if tradeoff_real
        else "La biología o la aptitud basal ya inclinan claramente la modalidad visible."
    )
    return {
        "available": True,
        "modality_fitness_status": modality_status,
        "dominant_modality": dominant_modality,
        "dominance_reason": dominance_reason,
        "modality_competitors": modality_competitors,
        "why_not_surgery": _dedupe(surgery_reasons) or ["Sin objeciones mayores documentadas contra cirugía."],
        "why_not_radiotherapy": _dedupe(rt_reasons) or ["Sin objeciones mayores documentadas contra radioterapia."],
        "why_not_active_surveillance": _dedupe(as_reasons) or ["La vigilancia activa sigue disponible si la biología se mantiene favorable."],
        "tradeoff_summary": tradeoff_summary,
        "shared_decision_required": shared_decision_required,
        "is_active_surveillance_reasonable_now": active_surveillance_status == "reasonable",
        "is_surgery_reasonable_now": surgery_status == "reasonable",
        "is_radiotherapy_reasonable_now": radiotherapy_status == "reasonable",
        "field_that_would_change_answer": field_that_would_change_answer,
        "surgery_status": surgery_status,
        "radiotherapy_status": radiotherapy_status,
        "active_surveillance_status": active_surveillance_status,
        "missing_modality_fields": missing_modality_fields,
        "modality_tradeoff_gaps": modality_tradeoff_gaps,
        "patient_priority_profile": priorities,
        "plnd_likely_indicated": plnd_likely if plnd_likely in {"0", "1", "unknown"} else "",
        "brachy_feasibility": brachy_feasibility,
        "radical_prostatectomy_candidacy_profile": rp_candidacy_profile,
        "localized_survival_context_bundle": survival_context_bundle,
        "active_surveillance_monitoring_profile": active_surveillance_monitoring_profile,
        "epic26_role_summary": epic26_role_summary,
        "epic26_shared_decision_signals": epic26_shared_decision_signals,
        "epic26_governance_contract": epic26_governance_contract,
    }


def build_localized_tradeoff_bundle(
    field_values: dict[str, Any],
    *,
    nccn_group: str = "",
    modality_bundle: dict[str, Any] | None = None,
    as_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = normalized_localized_values(field_values)
    modality_bundle = dict(modality_bundle or build_localized_modality_fitness_bundle(values, nccn_group=nccn_group, as_position=as_position))
    priorities = list(values.get("patient_priority_profile") or [])
    risk_group = _normalized_key(nccn_group).upper()
    ipss = _safe_float(values.get("ipss_total"))
    urinary_incontinence_qol = _safe_float(values.get("epic26_urinary_incontinence_domain"))
    urinary_irritative_qol = _safe_float(values.get("epic26_urinary_irritative_domain"))
    bowel_qol = _safe_float(values.get("epic26_bowel_domain"))
    iief = _safe_float(values.get("iief5_score"))
    sexual_qol = _safe_float(values.get("epic26_sexual_domain"))
    hormonal_qol = _safe_float(values.get("epic26_hormonal_domain"))
    frailty = _normalized_key(values.get("frailty_status"))
    g8 = _safe_float(values.get("g8_score"))
    prostate_volume = _safe_float(values.get("prostate_volume_ml"))
    obstruction = _normalized_key(values.get("baseline_obstruction"))
    rp_candidacy_profile = dict(modality_bundle.get("radical_prostatectomy_candidacy_profile") or {})
    active_surveillance_monitoring_profile = dict(modality_bundle.get("active_surveillance_monitoring_profile") or {})

    modalities = {
        "active_surveillance": {
            "oncologic_fit": "high" if modality_bundle.get("active_surveillance_status") == "reasonable" else "conditional" if modality_bundle.get("active_surveillance_status") == "provisional" else "low",
            "functional_cost_profile": "low",
            "logistic_burden": "moderate",
            "reversibility": "high",
            "salvage_implications": "retains_curative_window_if_structured",
            "patient_priority_alignment": _modality_priority_alignment(priorities, "active_surveillance"),
            "net_recommendation_status": modality_bundle.get("active_surveillance_status"),
        },
        "surgery": {
            "oncologic_fit": "high" if risk_group in {"FAVORABLE INTERMEDIATE", "UNFAVORABLE INTERMEDIATE", "HIGH"} else "moderate",
            "functional_cost_profile": "high"
            if ("preserve_sexual_function" in priorities and ((iief is not None and iief >= 17) or (sexual_qol is not None and sexual_qol >= 70)))
            else "moderate",
            "logistic_burden": "front_loaded",
            "reversibility": "low",
            "salvage_implications": "enables_psa_followup_and_postop_salvage",
            "patient_priority_alignment": _modality_priority_alignment(priorities, "surgery"),
            "net_recommendation_status": modality_bundle.get("surgery_status"),
        },
        "radiotherapy": {
            "oncologic_fit": "high" if risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"} else "moderate",
            "functional_cost_profile": "high" if bowel_qol is not None and bowel_qol <= 60 else "moderate",
            "logistic_burden": "fractionated" if risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"} else "moderate",
            "reversibility": "low",
            "salvage_implications": "local_salvage_more_complex_if_recurrence",
            "patient_priority_alignment": _modality_priority_alignment(priorities, "radiotherapy"),
            "net_recommendation_status": modality_bundle.get("radiotherapy_status"),
        },
    }
    if (ipss is not None and ipss >= 18) or obstruction in {"severe"} or (prostate_volume is not None and prostate_volume >= 80) or (urinary_irritative_qol is not None and urinary_irritative_qol <= 60):
        modalities["radiotherapy"]["functional_cost_profile"] = "high"
    if urinary_incontinence_qol is not None and urinary_incontinence_qol <= 60 and "preserve_urinary_function" in priorities:
        modalities["surgery"]["functional_cost_profile"] = "high"
    if risk_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"} and hormonal_qol is not None and hormonal_qol <= 60:
        modalities["radiotherapy"]["functional_cost_profile"] = "high"
    if frailty == "frail" or (g8 is not None and g8 <= 14):
        modalities["surgery"]["net_recommendation_status"] = "blocked"
        modalities["radiotherapy"]["patient_priority_alignment"] = (
            "high"
            if modalities["radiotherapy"]["patient_priority_alignment"] == "neutral"
            else modalities["radiotherapy"]["patient_priority_alignment"]
        )
    dominant = str(modality_bundle.get("dominant_modality") or "")
    if dominant == "multimodal_local":
        tradeoff_status = "dominant_control_priority"
        tradeoff_summary = "La biología de riesgo alto desplaza el foco desde una modalidad aislada a una estrategia local intensificada."
    elif dominant == "active_surveillance":
        tradeoff_status = "surveillance_favored"
        tradeoff_summary = "La vigilancia activa sigue siendo razonable porque la biología y el seguimiento estructurado aún sostienen la ventana curativa."
    elif modality_bundle.get("modality_fitness_status") == "provisional":
        tradeoff_status = "needs_shared_decision"
        tradeoff_summary = "Cirugía y radioterapia siguen abiertas; hoy falta cerrar trade-off funcional, factibilidad o prioridades del paciente."
    else:
        tradeoff_status = "dominant_modality_selected"
        tradeoff_summary = modality_bundle.get("tradeoff_summary") or "Una modalidad ya domina tras integrar riesgo, escalas funcionales válidas, factibilidad y preferencias."
    return {
        "available": True,
        "dominant_modality": dominant,
        "tradeoff_status": tradeoff_status,
        "tradeoff_summary": tradeoff_summary,
        "patient_priority_profile": priorities,
        "shared_decision_refiners_missing": list(modality_bundle.get("modality_tradeoff_gaps") or []),
        "epic26_shared_decision_signals": list(modality_bundle.get("epic26_shared_decision_signals") or []),
        "epic26_governance_contract": dict(modality_bundle.get("epic26_governance_contract") or {}),
        "modalities": modalities,
        "radical_prostatectomy_candidacy_profile": rp_candidacy_profile,
        "active_surveillance_monitoring_profile": active_surveillance_monitoring_profile,
    }
