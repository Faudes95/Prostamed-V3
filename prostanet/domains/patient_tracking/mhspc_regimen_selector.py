from __future__ import annotations

from typing import Any

from clinical_scores import docetaxel_fitness

from prostanet.domains.patient_tracking.mhspc_frontline_reference import (
    REGIMEN_PIVOTAL_TRIALS,
    component_metadata,
    get_mhspc_frontline_reference,
)
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_sequence_transition_bundle,
    regimen_family_code,
)
from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload
from prostanet.shared.gleason_profile import normalize_gleason_profile


MHSPC_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

REGIMEN_COMPONENTS = {
    "ADT_DAROLUTAMIDE": ["ADT", "Darolutamida"],
    "ADT_ENZALUTAMIDE": ["ADT", "Enzalutamida"],
    "ADT_APALUTAMIDE": ["ADT", "Apalutamida"],
    "ADT_ABIRATERONE": ["ADT", "Abiraterona"],
    "ADT_DOCETAXEL": ["ADT", "Docetaxel"],
    "ADT_DOCETAXEL_DAROLUTAMIDE": ["ADT", "Docetaxel", "Darolutamida"],
    "ADT_DOCETAXEL_ABIRATERONE": ["ADT", "Docetaxel", "Abiraterona"],
    # EPIC 9 Group C (GAP-5) — TALAPRO-3 combina ADT + talazoparib +
    # enzalutamida en mHSPC HRR-mutado (Agarwal ASCO GU 2025 LBA18). El
    # scoring trata el régimen como precision-ARPI+PARP y solo lo activa
    # cuando `hrr_status` es positiva; en el resto de pacientes queda
    # hard-blocked (evita sugerir PARPi sin indicación biomarker-driven).
    "ADT_TALAZO_ENZA_HRR": ["ADT", "Talazoparib", "Enzalutamida"],
}
DOCETAXEL_TRIPLETS = {
    "ADT_DOCETAXEL_DAROLUTAMIDE",
    "ADT_DOCETAXEL_ABIRATERONE",
}
# EPIC 9 Group C (GAP-5) — genes HRR que disparan bonus TALAPRO-3.
# Lista alineada con TALAPRO-3 protocol (12 genes HRR) + alias canónicos
# usados en ProstaNet (BRCA1/2, ATM, PALB2, CDK12, CHEK2, FANCA, MLH1,
# MRE11A, NBN, RAD51B, RAD51C).
TALAPRO3_HRR_POSITIVE_GENES = {
    "brca1",
    "brca2",
    "atm",
    "palb2",
    "cdk12",
    "chek2",
    "fanca",
    "mlh1",
    "mre11a",
    "nbn",
    "rad51b",
    "rad51c",
    "hrr_other",
    "other_hrr",
}

RANKING_POLICY_VERSION = "mhspc_docetaxel_hierarchical_2026_v2"
INSTITUTIONAL_WEIGHT_POLICY = "tie_breaker_only"


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "documentado"}


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _structured_entry_count(entries: Any) -> int:
    total = 0
    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        count = _safe_int(entry.get("lesion_count"))
        total += count if count is not None and count > 0 else 1
    return total


def resolve_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if state != "mcspc_high_volume":
        return state
    explicit = str(payload.get("disease_temporality", "") or "").strip().lower()
    if explicit in {"sync", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "mcspc_high_volume_sync"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "mcspc_high_volume_metachronous"
    if _truthy(payload.get("metachronous_metastasis", "0")):
        return "mcspc_high_volume_metachronous"
    return "mcspc_high_volume_sync"


def is_mhspc_state(state: str) -> bool:
    return state in MHSPC_STATES


def _phenotype_profile(state: str, payload: dict[str, Any]) -> dict[str, Any]:
    exact_state = resolve_mhspc_state(state, payload)
    return {
        "state": exact_state,
        "is_high_volume": "high_volume" in exact_state,
        "is_low_volume": exact_state == "mcspc_low_volume_sync_oligo",
        "is_sync": exact_state in {"mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync"},
        "is_metachronous": exact_state in {"mcspc_oligo_metachronous", "mcspc_high_volume_metachronous"},
        "is_oligometastatic": exact_state == "mcspc_oligo_metachronous",
    }


def _modifier_profile(
    payload: dict[str, Any],
    *,
    state: str = "",
    docetaxel_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    docetaxel = dict(docetaxel_bundle or docetaxel_fitness({**payload, "state": state} if state else payload))
    gleason_profile = normalize_gleason_profile(payload)
    ecog = _safe_int(payload.get("ecog_score", payload.get("ecog")))
    frailty = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    child_pugh = str(payload.get("child_pugh_score", "A") or "A").strip().upper()
    egfr = _safe_float(payload.get("egfr"))
    # EPIC 9 Group A (GAP-1/2/3): geriatric + cardiac discriminators.
    patient_age = _safe_int(payload.get("patient_age") or payload.get("age"))
    qtc_baseline_ms = _safe_float(payload.get("qtc_baseline_ms") or payload.get("qtc_ms"))
    nyha_class = str(payload.get("nyha_class") or "none").strip()
    lvef_percent = _safe_float(payload.get("lvef_percent"))
    # EPIC 9 Group C (GAP-5): HRR biomarker profile para TALAPRO-3.
    # TALAPRO-3 (Agarwal ASCO GU 2025 LBA18) requiere alteración HRR
    # trazable (12 genes). Sin biomarker positivo, el régimen ADT+
    # talazoparib+enzalutamida queda hard-blocked para evitar
    # exposición a PARPi sin indicación precisa.
    hrr_status_raw = str(
        payload.get("hrr_status")
        or payload.get("hrr_result")
        or ""
    ).strip().lower()
    hrr_gene_raw = str(
        payload.get("hrr_gene")
        or payload.get("hrr_gene_altered")
        or payload.get("hrr_genes")
        or ""
    ).strip().lower()
    hrr_positive = False
    if hrr_status_raw in {"positive", "positivo", "mutated", "mutado", "altered", "hrr+"}:
        hrr_positive = True
    if hrr_gene_raw:
        tokens = {t.strip() for t in hrr_gene_raw.replace(";", ",").split(",") if t.strip()}
        if tokens & TALAPRO3_HRR_POSITIVE_GENES:
            hrr_positive = True
    # Flags explícitos por gen (compat con EPIC 2 captura de germline/somatic).
    for gene_flag in (
        "brca1_status",
        "brca2_status",
        "atm_status",
        "palb2_status",
        "cdk12_status",
        "chek2_status",
    ):
        if str(payload.get(gene_flag) or "").strip().lower() in {"positive", "positivo", "mutated", "mutado", "pathogenic", "patogenico", "patogénico"}:
            hrr_positive = True
    hrr_tested = bool(hrr_status_raw) or bool(hrr_gene_raw) or _truthy(payload.get("hrr_testing_performed")) or _truthy(payload.get("germline_testing_performed"))
    structured_metastasis_count = (
        _structured_entry_count(payload.get("bone_site_entries"))
        + _structured_entry_count(payload.get("visceral_site_entries"))
        + _structured_entry_count(payload.get("nonregional_nodal_site_entries"))
    )
    resolved_metastasis_count = _safe_int(payload.get("metastasis_count"))
    visceral_present = bool(payload.get("visceral_site_entries")) or _truthy(payload.get("visceral_metastases")) or str(payload.get("metastasis_site", "")).strip().lower() == "visceral"
    return {
        "docetaxel": docetaxel,
        "fit_for_docetaxel": bool(docetaxel.get("fit_for_docetaxel")),
        "docetaxel_status": str(docetaxel.get("fit_status") or ""),
        "docetaxel_base_eligibility": str(docetaxel.get("docetaxel_base_eligibility") or "not_assessable"),
        "docetaxel_verification_status": str(docetaxel.get("docetaxel_verification_status") or "verified"),
        "docetaxel_block_type": str(docetaxel.get("docetaxel_block_type") or "none"),
        "docetaxel_required_now": bool(docetaxel.get("docetaxel_required_now")),
        "docetaxel_default_intensification": str(docetaxel.get("docetaxel_default_intensification") or "no"),
        "docetaxel_trial_fit": dict(docetaxel.get("docetaxel_trial_fit") or {}),
        "docetaxel_label_safety_reasons": list(docetaxel.get("docetaxel_label_safety_reasons") or []),
        "docetaxel_clinical_safety_reasons": list(docetaxel.get("docetaxel_clinical_safety_reasons") or []),
        "docetaxel_missing_inputs": list(docetaxel.get("docetaxel_missing_inputs") or []),
        "docetaxel_stale_inputs": list(docetaxel.get("docetaxel_stale_inputs") or []),
        "docetaxel_lab_snapshot": dict(docetaxel.get("docetaxel_lab_snapshot") or {}),
        "performance_status_driver": str(docetaxel.get("performance_status_driver") or "mixed_or_unclear"),
        "ecog": ecog,
        "frailty_status": frailty,
        "child_pugh": child_pugh,
        "egfr": egfr,
        "seizure_risk": _truthy(payload.get("comorbidity_seizure")),
        "cardio_risk": _truthy(payload.get("comorbidity_cardio")) or _truthy(payload.get("cv_risk_documented")),
        "hepatic_risk": bool((payload.get("hepatic_safety_bundle") or {}).get("hepatic_risk_present")) or child_pugh in {"B", "C"},
        "active_liver_disease": _truthy(payload.get("active_liver_disease"))
        or bool((payload.get("hepatic_safety_bundle") or {}).get("hepatic_risk_present")),
        "renal_risk_severe": egfr is not None and egfr < 30,
        "ddi_reviewed": str(payload.get("ddi_review_status") or "").strip().lower() == "completed",
        "current_medications_present": bool(payload.get("normalized_medication_list")) or bool(str(payload.get("current_medications") or "").strip()),
        "g8_score": _safe_float(payload.get("g8_score") or docetaxel.get("g8_score")),
        "mini_cog_score": _safe_float(payload.get("mini_cog_score") or payload.get("mini_cog") or docetaxel.get("mini_cog_score")),
        "cognitive_risk": bool(
            docetaxel.get("cognitive_risk")
            or _truthy(payload.get("cognitive_risk"))
            or frailty.lower() == "frail"
        ),
        "cognitive_risk_source": str(
            docetaxel.get("cognitive_risk_source")
            or ("explicit" if _truthy(payload.get("cognitive_risk")) else "frailty_derived" if frailty.lower() == "frail" else "")
        ),
        "geriatric_screen_status": str(docetaxel.get("geriatric_screen_status") or "").strip(),
        "cga_status": str(docetaxel.get("cga_status") or payload.get("cga_status") or "").strip(),
        "fall_risk": _truthy(payload.get("fall_risk")) or frailty.lower() in {"vulnerable", "frail"},
        "rash_history": _truthy(payload.get("history_severe_rash")) or _truthy(payload.get("severe_rash_history")) or _truthy(payload.get("dermatitis_history")),
        "hypothyroidism": _truthy(payload.get("baseline_hypothyroidism")) or _truthy(payload.get("hypothyroidism")),
        "stroke_history": _truthy(payload.get("stroke_history")) or _truthy(payload.get("cva_history")) or _truthy(payload.get("brain_lesion_history")),
        "edema_risk": _truthy(payload.get("edema_risk")) or _truthy(payload.get("edema_prone")),
        "steroid_risk": _truthy(payload.get("diabetes_uncontrolled")) or _truthy(payload.get("steroid_intolerance")),
        "visceral_metastases": visceral_present,
        "metastasis_count": resolved_metastasis_count if resolved_metastasis_count is not None else structured_metastasis_count,
        "gleason_score": gleason_profile.get("gleason_score") or 0,
        "isup_grade": gleason_profile.get("isup_grade") or 0,
        "gleason_summary": gleason_profile.get("summary") or "",
        "has_adverse_tertiary_pattern": bool(gleason_profile.get("has_adverse_tertiary_pattern")),
        "rt_primary_candidate": not _truthy(payload.get("rt_primary_received")),
        "mdt_context": str(payload.get("mdt_context") or ""),
        # EPIC 9 Group A (GAP-1/2/3): geriatric and cardiac modifiers.
        # STAMPEDE M1/AA subanálisis >75yr atenúa beneficio ARPI-doblete
        # (OS HR 0.88 vs 0.61 <75 → penalty adicional al triplete en >=75).
        "patient_age": patient_age,
        "elderly_75_plus": patient_age is not None and patient_age >= 75,
        "frail_85_plus": patient_age is not None and patient_age >= 85,
        # ENZAMET FDA §5.4: enzalutamide prolonga QTc >20 ms en 2.3%; QTc basal
        # >470 ms o riesgo de ΔQTc >500 ms bloquea uso relativo.
        "qtc_baseline_ms": qtc_baseline_ms,
        "qtc_risk": qtc_baseline_ms is not None and qtc_baseline_ms > 470.0,
        # COU-AA-302 excluyó NYHA III/IV; FDA Zytiga §5.1 advierte HF clase III-IV.
        # LVEF <40% indica disfunción moderada-severa independiente de síntomas.
        "nyha_class": nyha_class,
        "lvef_percent": lvef_percent,
        "heart_failure_severe": (
            nyha_class in {"III", "IV"}
            or (lvef_percent is not None and lvef_percent < 40.0)
        ),
        # EPIC 9 Group C (GAP-5): HRR biomarker gate para TALAPRO-3.
        "hrr_positive": hrr_positive,
        "hrr_tested": hrr_tested,
        "hrr_status_raw": hrr_status_raw,
        "hrr_gene_raw": hrr_gene_raw,
    }


def _regimen_profile(regimen_code: str) -> dict[str, Any]:
    return {
        "has_docetaxel": regimen_code.startswith("ADT_DOCETAXEL"),
        "arpi": (
            "darolutamide"
            if "DAROLUTAMIDE" in regimen_code
            else "abiraterone"
            if "ABIRATERONE" in regimen_code
            # EPIC 9 Group C (GAP-5) — TALAPRO-3 incluye enzalutamida
            # como backbone ARPI; clasificar el código antes de
            # `ADT_ENZALUTAMIDE` puro para mantener la semántica
            # precisa del par talazoparib+enzalutamida.
            else "enzalutamide"
            if regimen_code in {"ADT_ENZALUTAMIDE", "ADT_TALAZO_ENZA_HRR"}
            else "apalutamide"
            if regimen_code == "ADT_APALUTAMIDE"
            else "none"
            if regimen_code == "ADT_DOCETAXEL"
            else "unknown"
        ),
        "requires_steroid": "ABIRATERONE" in regimen_code,
        # EPIC 9 Group C (GAP-5) — flag precision-parp para tratamiento
        # diferenciado en surfacing y evidencia TALAPRO-3.
        "has_parp": regimen_code == "ADT_TALAZO_ENZA_HRR",
    }


def _is_docetaxel_triplet(regimen_code: str) -> bool:
    return regimen_code in DOCETAXEL_TRIPLETS


def _neutral_base_score(_regimen_code: str) -> float:
    return 50.0


def _latitude_like(modifiers: dict[str, Any]) -> bool:
    return (
        (modifiers["gleason_score"] >= 8)
        + int(modifiers["isup_grade"] >= 4)
        + int(modifiers["has_adverse_tertiary_pattern"])
        + (modifiers["metastasis_count"] >= 3)
        + int(modifiers["visceral_metastases"])
    ) >= 2


def _abiraterone_override_eligible(phenotype: dict[str, Any], modifiers: dict[str, Any]) -> bool:
    # LATITUDE incluyó pacientes con ≥2 de {Gleason ≥8, ≥3 metástasis óseas,
    # metástasis visceral medible}. Las metástasis viscerales NO eran un
    # criterio obligatorio. Tampoco lo era el riesgo convulsivo (ese gate
    # estaba presente sólo para justificar desplazar a darolutamida en su
    # nicho de seguridad CNS). Para que el override dispare en un perfil
    # LATITUDE clásico (Gleason 9 + ≥3 metástasis óseas + sin comorbilidad
    # hepática/cardio/edema/esteroide + Child-Pugh A + apto + ECOG ≤1) basta
    # con `_latitude_like` y un perfil de seguridad limpio (BUG-06-NEW).
    return bool(
        phenotype["state"] == "mcspc_high_volume_sync"
        and modifiers["docetaxel_default_intensification"] != "yes"
        and _latitude_like(modifiers)
        and modifiers["gleason_score"] >= 8
        and modifiers["child_pugh"] == "A"
        and not modifiers["hepatic_risk"]
        and not modifiers["cardio_risk"]
        and not modifiers["edema_risk"]
        and not modifiers["steroid_risk"]
        and str(modifiers.get("frailty_status") or "").lower() == "fit"
        and modifiers.get("ecog") is not None
        and modifiers["ecog"] <= 1
    )


def _trial_fit(regimen_code: str, phenotype: dict[str, Any], modifiers: dict[str, Any]) -> dict[str, Any]:
    matched_trials = list(REGIMEN_PIVOTAL_TRIALS.get(regimen_code) or [])
    fit = "no"
    rationale = "El subescenario no reproduce completamente la población pivote."
    docetaxel_trial_fit = dict(modifiers.get("docetaxel_trial_fit") or {})
    if regimen_code == "ADT_DOCETAXEL_DAROLUTAMIDE":
        docetaxel_fit = str(docetaxel_trial_fit.get("arasens_like") or "no")
        if phenotype["is_high_volume"] and docetaxel_fit in {"matched", "partial"}:
            # ARASENS enrolled both sincrónico y metacrónico de alto volumen;
            # los subgrupos preespecificados mostraron beneficio en SG
            # consistente con independencia del momento de la metástasis. No
            # debe penalizarse el encaje a "partial" sólo por ser metacrónico
            # cuando la aptitud a docetaxel es plena (BUG-03-NEW).
            fit = "matched" if docetaxel_fit == "matched" else "partial"
            rationale = (
                "ARASENS es trial-like en alto volumen con aptitud a docetaxel, "
                "independientemente de si la enfermedad es sincrónica o metacrónica."
                if fit == "matched"
                else "ARASENS sigue siendo la referencia más cercana en alto volumen apto para docetaxel."
            )
    elif regimen_code == "ADT_DOCETAXEL_ABIRATERONE":
        docetaxel_fit = str(docetaxel_trial_fit.get("peace1_like") or "no")
        if phenotype["state"] == "mcspc_high_volume_sync" and docetaxel_fit in {"matched", "partial"}:
            fit = docetaxel_fit
            rationale = (
                "PEACE-1 es trial-like en enfermedad sincrónica/de novo de alto volumen apta para docetaxel."
                if fit == "matched"
                else "PEACE-1 puede extrapolarse con cautela cuando el ECOG 2 parece cáncer-relacionado / por dolor óseo."
            )
    elif regimen_code == "ADT_DOCETAXEL":
        docetaxel_fit = str(docetaxel_trial_fit.get("chaarted_like") or "no")
        if phenotype["is_high_volume"] and docetaxel_fit in {"matched", "partial"}:
            fit = docetaxel_fit
            rationale = (
                "CHAARTED mantiene respaldo directo para ADT + docetaxel en alto volumen cuando el paciente sigue siendo buen candidato a quimioterapia."
                if fit == "matched"
                else "CHAARTED permite una extrapolación cauta de ADT + docetaxel cuando el ECOG 2 parece impulsado por el cáncer."
            )
    elif regimen_code == "ADT_ABIRATERONE":
        high_risk_latitude = (
            (modifiers["gleason_score"] >= 8)
            + int(modifiers["isup_grade"] >= 4)
            + int(modifiers["has_adverse_tertiary_pattern"])
            + (modifiers["metastasis_count"] >= 3)
            + int(modifiers["visceral_metastases"])
        ) >= 2
        if phenotype["state"] == "mcspc_high_volume_sync" and high_risk_latitude:
            fit = "matched"
            rationale = "LATITUDE es trial-like en mCSPC de novo/sincrónico de alto riesgo."
        else:
            fit = "partial"
            rationale = "Abiraterona sigue siendo guideline-consistent, pero el encaje con LATITUDE depende del perfil de alto riesgo de novo."
    elif regimen_code == "ADT_DAROLUTAMIDE":
        fit = "matched"
        rationale = "ARANOTE mantiene comparabilidad amplia en mHSPC cuando se prioriza intensificación hormonal sin docetaxel."
    elif regimen_code in {"ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"}:
        fit = "matched"
        rationale = "La intensificación con ARPI es trial-like para el subescenario mHSPC actual."
    return {
        "fit": fit,
        "matched_trials": matched_trials,
        "rationale": rationale,
    }


def _trial_fit_weight(trial_fit: dict[str, Any]) -> float:
    fit = str(trial_fit.get("fit") or "")
    if fit == "matched":
        return 6.0
    if fit == "partial":
        return 2.0
    return -4.0


def _evidence_maturity(regimen_code: str, phenotype: dict[str, Any], modifiers: dict[str, Any]) -> dict[str, Any]:
    profile = _regimen_profile(regimen_code)
    latitude_like = _latitude_like(modifiers)
    if regimen_code == "ADT_DOCETAXEL_DAROLUTAMIDE":
        return {
            "level": "high",
            "weight": 8.0,
            "rationale": "ARASENS aporta el backbone pivote más sólido para triplete con darolutamida cuando docetaxel sigue siendo apropiado.",
        }
    if regimen_code == "ADT_DOCETAXEL_ABIRATERONE":
        if phenotype["state"] == "mcspc_high_volume_sync":
            return {
                "level": "high",
                "weight": 8.0,
                "rationale": "PEACE-1 mantiene alta madurez de beneficio para triplete con abiraterona en alto volumen sincrónico/de novo apto para docetaxel.",
            }
        return {
            "level": "limited",
            "weight": 1.0,
            "rationale": "PEACE-1 no debe extrapolarse como backbone preferente fuera del alto volumen sincrónico/de novo.",
        }
    if regimen_code == "ADT_DOCETAXEL":
        return {
            "level": "established",
            "weight": 4.0,
            "rationale": "CHAARTED/STAMPEDE mantienen a ADT + docetaxel como alternativa estructurada, aunque hoy no debe liderar por encima de combinaciones superiores cuando estas son seguras y factibles.",
        }
    if profile["arpi"] == "abiraterone":
        if phenotype["state"] == "mcspc_high_volume_sync" and latitude_like:
            return {
                "level": "high",
                "weight": 9.0,
                "rationale": "LATITUDE aporta madurez robusta de supervivencia global en mHSPC de novo de alto riesgo y mantiene a abiraterona como competidora real.",
            }
        return {
            "level": "established",
            "weight": 5.0,
            "rationale": "Abiraterona sigue siendo guideline-consistent, pero fuera del encaje LATITUDE su fuerza depende más del contexto clínico individual.",
        }
    if profile["arpi"] == "darolutamide":
        if profile["has_docetaxel"]:
            return {
                "level": "high",
                "weight": 8.0,
                "rationale": "ARASENS respalda el triplete con darolutamida cuando el paciente mantiene aptitud a docetaxel.",
            }
        return {
            "level": "moderate",
            "weight": 6.0,
            "rationale": "ARANOTE y la aprobación FDA 2025 respaldan ADT + darolutamida cuando se prioriza intensificación sin docetaxel.",
        }
    if profile["arpi"] == "enzalutamide":
        return {
            "level": "high",
            "weight": 6.0,
            "rationale": "ARCHES/ENZAMET respaldan intensificación con enzalutamida en mHSPC, condicionada por seguridad neurológica.",
        }
    if profile["arpi"] == "apalutamide":
        return {
            "level": "high",
            "weight": 6.0,
            "rationale": "TITAN respalda intensificación con apalutamida en mHSPC, condicionada por tolerabilidad cutánea/endocrina y neurológica.",
        }
    return {
        "level": "limited",
        "weight": 0.0,
        "rationale": "El backbone no tiene una capa de madurez de evidencia diferenciada en este subescenario.",
    }


def _regimen_components(regimen_code: str) -> list[dict[str, Any]]:
    components = []
    for drug_name in REGIMEN_COMPONENTS.get(regimen_code, []):
        components.append(component_metadata(drug_name))
    return components


def _join_component_values(components: list[dict[str, Any]], key: str) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for component in components:
        value = str(component.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return " + ".join(values)


def _join_component_keys(components: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    seen: set[str] = set()
    for component in components:
        value = str(component.get("imss_key") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        keys.append(value)
    return " / ".join(keys)


def _regimen_delivery_summary(components: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "dose": _join_component_values(components, "dose"),
        "route": _join_component_values(components, "route"),
        "schedule": _join_component_values(components, "schedule"),
        "imss_key": _join_component_keys(components),
    }


def _format_component_summary(components: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for component in components:
        label = str(component.get("drug_name") or "")
        dose = str(component.get("dose") or "")
        route = str(component.get("route") or "")
        schedule = str(component.get("schedule") or "")
        imss_key = str(component.get("imss_key") or "")
        metadata_source = str(component.get("metadata_source") or "")
        details = " · ".join(item for item in [dose, route, schedule] if item)
        suffix = f" Clave IMSS: {imss_key}." if imss_key else ""
        source = " Fuente: documento institucional." if metadata_source == "institutional_ingested_document" else " Fuente: catálogo actual." if metadata_source else ""
        if details:
            parts.append(f"{label}: {details}.{suffix}{source}".strip())
        else:
            parts.append(f"{label}.{suffix}{source}".strip())
    return " ".join(parts)


def _regimen_label(regimen_code: str) -> str:
    custom_labels = {
        "ADT_DAROLUTAMIDE": "ADT + darolutamida",
        "ADT_ENZALUTAMIDE": "ADT + enzalutamida",
        "ADT_APALUTAMIDE": "ADT + apalutamida",
        "ADT_ABIRATERONE": "ADT + abiraterona",
        "ADT_DOCETAXEL": "ADT + docetaxel",
        "ADT_DOCETAXEL_DAROLUTAMIDE": "ADT + docetaxel + darolutamida",
        "ADT_DOCETAXEL_ABIRATERONE": "ADT + docetaxel + abiraterona",
    }
    return custom_labels.get(regimen_code, regimen_label(regimen_code))


def _apply_modifiers(
    regimen_code: str,
    phenotype: dict[str, Any],
    modifiers: dict[str, Any],
    *,
    field_values: dict[str, Any],
    arpi_candidates: list[str],
) -> dict[str, Any]:
    profile = _regimen_profile(regimen_code)
    docetaxel_base_eligibility = str(modifiers.get("docetaxel_base_eligibility") or "not_assessable")
    docetaxel_default_intensification = str(modifiers.get("docetaxel_default_intensification") or "no")
    reasons_for: list[str] = []
    reasons_against: list[str] = []
    # BUG ERR-13: keep data-quality (captura incompleta / laboratorios vencidos /
    # revisiones pendientes) fuera de ``reasons_against``. Esa lista debe llevar
    # únicamente razones clínicas duras para que la UI no presente "Falta
    # documentar interacciones" como una contraindicación.
    data_quality_caveats: list[str] = []
    hard_block = False
    safety_modifiers_applied: list[str] = []
    clinical_priority_components = {
        "trial_population_fit": 0.0,
        "survival_maturity_weight": 0.0,
        "safety_penalty": 0.0,
        "toxicity_penalty": 0.0,
        "phenotype_bonus": 0.0,
        "benefit_adjustment": 0.0,
        "capture_completeness_penalty": 0.0,
        "institutional_tie_breaker": 0.0,
    }
    arpi_metadata = {}

    trial_fit = _trial_fit(regimen_code, phenotype, modifiers)
    clinical_priority_components["trial_population_fit"] = _trial_fit_weight(trial_fit)
    if trial_fit["fit"] == "matched":
        reasons_for.append(trial_fit["rationale"])
    else:
        reasons_against.append(trial_fit["rationale"])

    evidence_maturity = _evidence_maturity(regimen_code, phenotype, modifiers)
    clinical_priority_components["survival_maturity_weight"] = float(evidence_maturity.get("weight") or 0.0)
    if evidence_maturity.get("rationale"):
        reasons_for.append(str(evidence_maturity["rationale"]))

    if regimen_code in arpi_candidates:
        arpi_metadata = evaluate_arpi_candidate(
            phenotype["state"],
            field_values,
            regimen_code,
            candidate_regimens=arpi_candidates,
        )
        clinical_priority_components["benefit_adjustment"] += float(arpi_metadata.get("benefit_score") or 0.0)
        if arpi_metadata.get("benefit_basis"):
            reasons_for.append(str(arpi_metadata.get("benefit_basis") or ""))
        if arpi_metadata.get("required_missing_fields") or arpi_metadata.get("stale_inputs"):
            clinical_priority_components["capture_completeness_penalty"] -= 18.0
            # BUG ERR-13: preferencia provisional por captura incompleta es un
            # caveat de calidad de datos, no una contraindicación clínica.
            data_quality_caveats.append(
                "La preferencia molecular ARPI sigue provisional hasta completar: "
                + ", ".join(
                    list(arpi_metadata.get("required_missing_fields") or [])
                    + list(arpi_metadata.get("stale_inputs") or [])
                )
                + "."
            )
            safety_modifiers_applied.append("arpi_profile_incomplete")

    if phenotype["state"] == "mcspc_high_volume_sync":
        if profile["has_docetaxel"]:
            if docetaxel_default_intensification == "yes":
                clinical_priority_components["phenotype_bonus"] += 14.0
                reasons_for.append("El alto volumen sincrónico mantiene una discusión real de triplete cuando docetaxel es clínicamente factible.")
            elif docetaxel_default_intensification == "conditional":
                clinical_priority_components["phenotype_bonus"] += 3.0
                reasons_against.append("El alto volumen sincrónico permite discutir docetaxel, pero hoy solo como intensificación condicional y no como default.")
            else:
                clinical_priority_components["phenotype_bonus"] -= 8.0
                reasons_against.append("Al no existir elegibilidad quimioterapéutica suficiente, el caso deja de ser triplete-first y debe reabrirse la competencia entre dobletes.")
        else:
            clinical_priority_components["phenotype_bonus"] += 9.0 if docetaxel_default_intensification != "yes" else 4.0
            reasons_for.append("El fenotipo de alto volumen sincrónico mantiene visible intensificación hormonal fuerte.")
    elif phenotype["state"] == "mcspc_high_volume_metachronous":
        if profile["has_docetaxel"]:
            if docetaxel_default_intensification == "yes":
                # ARASENS prespecificó tanto sincrónico como metacrónico y los
                # subgrupos mantuvieron beneficio en SG. Por eso el triplete
                # debe competir con el mismo peso fenotípico (+14) que en HV
                # sincrónico cuando la aptitud a docetaxel es plena
                # (BUG-03-NEW).
                clinical_priority_components["phenotype_bonus"] += 14.0
                reasons_for.append("El alto volumen metacrónico mantiene discusión real de triplete cuando docetaxel es clínicamente factible, con ARASENS como respaldo prespecificado.")
            elif docetaxel_default_intensification == "conditional":
                clinical_priority_components["phenotype_bonus"] += 3.0
                reasons_against.append("En alto volumen metacrónico el docetaxel puede ser una intensificación condicional, pero no debe liderar por defecto.")
            else:
                clinical_priority_components["phenotype_bonus"] -= 8.0
                reasons_against.append("En alto volumen metacrónico no apto a docetaxel, el triplete deja de ser la vía principal.")
        else:
            clinical_priority_components["phenotype_bonus"] += 8.0
            reasons_for.append("En alto volumen metacrónico la competencia principal entre dobletes debe resolverse por evidencia y seguridad.")
    elif phenotype["state"] == "mcspc_low_volume_sync_oligo":
        if profile["has_docetaxel"]:
            clinical_priority_components["phenotype_bonus"] -= 26.0
            reasons_against.append("El triplete no es la estrategia visible estándar en bajo volumen sincrónico.")
        else:
            clinical_priority_components["phenotype_bonus"] += 7.0
            reasons_for.append("En bajo volumen sincrónico el backbone principal sigue siendo doblete hormonal individualizado.")
    elif phenotype["state"] == "mcspc_oligo_metachronous":
        if profile["has_docetaxel"]:
            clinical_priority_components["phenotype_bonus"] -= 28.0
            reasons_against.append("El triplete no es la estrategia estándar visible en oligometastásico metacrónico.")
        else:
            clinical_priority_components["phenotype_bonus"] += 7.0
            reasons_for.append("En oligometastásico metacrónico debe priorizarse doblete hormonal y discusión MDT, no triplete por inercia.")

    if profile["has_docetaxel"]:
        if docetaxel_base_eligibility == "contraindicated":
            clinical_priority_components["safety_penalty"] -= 60.0
            hard_block = True
            # Deduplicate: the same hepatic-reason string is pushed to both
            # ``docetaxel_hard_stop_reasons`` and ``docetaxel_label_safety_reasons``
            # in clinical_scores.docetaxel_fitness, so two extends used to
            # produce the same string twice (BUG ERR-07).
            seen_reasons = set(reasons_against)
            for reason in (modifiers["docetaxel"].get("docetaxel_hard_stop_reasons") or ["No apto para docetaxel."]):
                if reason not in seen_reasons:
                    reasons_against.append(reason)
                    seen_reasons.add(reason)
            for reason in (modifiers.get("docetaxel_label_safety_reasons") or []):
                if reason not in seen_reasons:
                    reasons_against.append(reason)
                    seen_reasons.add(reason)
        elif modifiers.get("docetaxel_verification_status") in {"pending_labs", "stale_labs"} and modifiers.get("docetaxel_required_now"):
            penalty = 24.0 if regimen_code != "ADT_DOCETAXEL" else 10.0
            clinical_priority_components["safety_penalty"] -= penalty
            # BUG ERR-13: laboratorios vencidos o pendientes son caveats de
            # calidad de datos — no son contraindicaciones clínicas.
            data_quality_caveats.append(
                "La elegibilidad actual a docetaxel sigue pendiente de validar con laboratorios vigentes; el triplete no debe cerrarse como líder todavía."
                if modifiers.get("docetaxel_verification_status") == "pending_labs"
                else "Los laboratorios de elegibilidad a docetaxel están vencidos; el triplete no debe cerrarse hasta actualizar la verificación."
            )
            data_quality_caveats.extend(modifiers.get("docetaxel_stale_inputs") or modifiers.get("docetaxel_missing_inputs") or [])
        elif docetaxel_default_intensification == "conditional":
            penalty = 18.0 if regimen_code != "ADT_DOCETAXEL" else 8.0
            clinical_priority_components["toxicity_penalty"] -= penalty
            reasons_against.append(
                "Docetaxel sigue siendo posible, pero hoy solo con cautela; el triplete no debe quedar como líder automático."
                if regimen_code != "ADT_DOCETAXEL"
                else "ADT + docetaxel sigue siendo posible con cautela, pero no debe imponerse sobre opciones mejor alineadas."
            )
        # EPIC 9 Group B (GAP-4) — PEACE-1 validó el triplete ADT+docetaxel+
        # abiraterona EXCLUSIVAMENTE en mHSPC de novo/sincrónico de alto volumen
        # (Fizazi *Lancet* 2022;399:1695); extrapolar a metacrónico u
        # oligometastásico no tiene base prospectiva. El matrix ya lo marca
        # `triplet_fit="not_applicable"` en mcspc_high_volume_metachronous
        # (arpi_benefit_matrix.py:164-180); aquí reforzamos con penalty
        # estructural −30 (subido desde −20) para evitar liderazgo por inercia.
        if regimen_code == "ADT_DOCETAXEL_ABIRATERONE" and phenotype["state"] != "mcspc_high_volume_sync":
            clinical_priority_components["phenotype_bonus"] -= 30.0
            reasons_against.append("PEACE-1 solo validó el triplete en mHSPC de novo/sincrónico de alto volumen; no debe extrapolarse a metacrónico ni oligometastásico.")
        if regimen_code == "ADT_DOCETAXEL" and not phenotype["is_high_volume"]:
            clinical_priority_components["phenotype_bonus"] -= 18.0
            reasons_against.append("ADT + docetaxel no debe liderar como backbone visible fuera del alto volumen.")
        # EPIC 9 Group A (GAP-1): STAMPEDE M1/AA subanálisis >75yr atenúa
        # beneficio ARPI-doblete (OS HR 0.88 vs 0.61 <75); en triplete esta
        # atenuación + toxicidad docetaxel justifica penalty adicional. En
        # ≥85yr o frágil, hard-block el triplete.
        if regimen_code in DOCETAXEL_TRIPLETS:
            if modifiers.get("frail_85_plus"):
                clinical_priority_components["safety_penalty"] -= 30.0
                hard_block = True
                reasons_against.append(
                    "Edad ≥85 años (o fragilidad declarada en ese grupo) contraindica el triplete por carga toxicológica acumulada; preferir doblete o ADT solo."
                )
                safety_modifiers_applied.append("frail_85_plus")
            elif modifiers.get("elderly_75_plus"):
                clinical_priority_components["phenotype_bonus"] -= 6.0
                reasons_against.append(
                    "Edad ≥75 años atenúa el beneficio OS del triplete (STAMPEDE M1/AA subanálisis HR 0.88 vs 0.61 <75); validar aptitud geriátrica antes de liderar con triplete."
                )
                safety_modifiers_applied.append("elderly_75_plus")

    # EPIC 9 Group C (GAP-5) — TALAPRO-3 gate biomarker-driven.
    # TALAPRO-3 (Agarwal ASCO GU 2025 LBA18) demostró rPFS HR≈0.67 con
    # talazoparib + enzalutamida + ADT vs placebo + enzalutamida + ADT
    # en mHSPC con alteración HRR (12 genes: BRCA1/2, ATM, PALB2, CDK12,
    # CHEK2, FANCA, MLH1, MRE11A, NBN, RAD51B, RAD51C). El régimen solo
    # entra al scoring activo cuando HRR es positiva y trazable; sin
    # biomarker confirmado queda hard-blocked para evitar PARPi sin
    # indicación precisa. Bonus +22 sobre `phenotype_bonus` lo coloca en
    # cabecera junto a dobletes convencionales en HRR+.
    if regimen_code == "ADT_TALAZO_ENZA_HRR":
        if modifiers.get("hrr_positive"):
            clinical_priority_components["phenotype_bonus"] += 22.0
            reasons_for.append(
                "Alteración HRR confirmada (BRCA1/2/ATM/PALB2/otros HRR) habilita el doblete precision-PARPi+ARPI TALAPRO-3 (Agarwal ASCO GU 2025 LBA18; rPFS HR≈0.67)."
            )
            safety_modifiers_applied.append("hrr_positive")
        else:
            clinical_priority_components["safety_penalty"] -= 50.0
            hard_block = True
            if modifiers.get("hrr_tested"):
                reasons_against.append(
                    "TALAPRO-3 requiere alteración HRR (BRCA1/2/ATM/PALB2/CDK12/CHEK2/FANCA/MLH1/MRE11A/NBN/RAD51B/RAD51C); el resultado HRR negativo/no-HRR bloquea el régimen."
                )
            else:
                reasons_against.append(
                    "TALAPRO-3 requiere test HRR documentado (germline y/o somático). Sin biomarker trazable no se ofrece talazoparib+enzalutamida; priorizar captura de HRR antes de considerar esta ruta de precisión."
                )
            safety_modifiers_applied.append("hrr_negative_or_untested")

    if regimen_code.endswith("DAROLUTAMIDE"):
        if modifiers["seizure_risk"] or modifiers["cognitive_risk"] or modifiers["fall_risk"]:
            bonus = 14.0 if (
                phenotype["state"] == "mcspc_high_volume_sync"
                and docetaxel_default_intensification != "yes"
                and modifiers["seizure_risk"]
            ) else 8.0
            clinical_priority_components["phenotype_bonus"] += bonus
            reasons_for.append(
                "En alto volumen no apto para docetaxel con riesgo convulsivo, darolutamida debe liderar por defecto por su mejor encaje de seguridad CNS."
                if bonus > 10
                else "El perfil neurológico/cognitivo favorece darolutamida."
            )
            safety_modifiers_applied.extend(
                item for item in ["seizure_risk", "cognitive_risk", "fall_risk"] if modifiers.get(item)
            )
        if modifiers["cardio_risk"]:
            clinical_priority_components["phenotype_bonus"] += 4.0
            reasons_for.append("El riesgo cardiovascular favorece evitar ARPI con mayor carga de eventos centrales o esteroides.")
            safety_modifiers_applied.append("cardio_risk")
        if modifiers["renal_risk_severe"]:
            clinical_priority_components["safety_penalty"] -= 22.0
            reasons_against.append("La insuficiencia renal grave desprioriza darolutamida.")
            safety_modifiers_applied.append("renal_risk_severe")
        if modifiers["child_pugh"] in {"B", "C"}:
            # Child-Pugh B/C combinado con hepatopatía activa contraindica
            # darolutamida: el ARPI tiene metabolismo hepático predominante,
            # en paralelo al hard-block que abiraterona ya aplica al perfil
            # hepático equivalente (BUG-04-NEW). Sin hepatopatía activa el
            # Child-Pugh B/C sigue sumando una penalidad fuerte pero no
            # bloquea, dado que el patrón clínico puede aún permitir
            # vigilancia estrecha.
            if modifiers.get("active_liver_disease"):
                clinical_priority_components["safety_penalty"] -= 45.0
                hard_block = True
                reasons_against.append(
                    "Child-Pugh B/C con hepatopatía activa contraindica darolutamida por metabolismo hepático predominante."
                )
                safety_modifiers_applied.append("hepatic_risk")
            else:
                clinical_priority_components["safety_penalty"] -= 22.0
                reasons_against.append("Child-Pugh B/C desprioriza darolutamida.")
                safety_modifiers_applied.append("hepatic_risk")
        if not any([modifiers["seizure_risk"], modifiers["cognitive_risk"], modifiers["fall_risk"], modifiers["cardio_risk"]]):
            reasons_for.append("Darolutamida sigue siendo una opción válida, pero no debe liderar por inercia sin ventajas clínicas concretas.")

    if regimen_code == "ADT_ENZALUTAMIDE":
        if modifiers["seizure_risk"] or modifiers["stroke_history"]:
            clinical_priority_components["safety_penalty"] -= 40.0
            hard_block = hard_block or modifiers["seizure_risk"] or modifiers["stroke_history"]
            reasons_against.append("Riesgo convulsivo o antecedente neurológico mayor desaconsejan enzalutamida.")
            safety_modifiers_applied.extend(
                item for item in ["seizure_risk", "stroke_history"] if modifiers.get(item)
            )
        if modifiers["cognitive_risk"] or modifiers["fall_risk"]:
            clinical_priority_components["toxicity_penalty"] -= 10.0
            reasons_against.append("La vulnerabilidad cognitiva o de caídas desprioriza enzalutamida.")
            safety_modifiers_applied.extend(
                item for item in ["cognitive_risk", "fall_risk"] if modifiers.get(item)
            )
        else:
            clinical_priority_components["phenotype_bonus"] += 4.0
            reasons_for.append("Enzalutamida es guideline-consistent si no existen banderas neurológicas.")
        # EPIC 9 Group A (GAP-2): QTc basal >470 ms despioriza enzalutamida
        # (ENZAMET FDA §5.4: prolongación QTc >20 ms en 2.3% de pacientes).
        if modifiers.get("qtc_risk"):
            clinical_priority_components["safety_penalty"] -= 12.0
            reasons_against.append(
                "QTc basal >470 ms eleva el riesgo de prolongación clínicamente relevante con enzalutamida; considerar darolutamida."
            )
            safety_modifiers_applied.append("qtc_risk")

    if regimen_code == "ADT_APALUTAMIDE":
        if modifiers["seizure_risk"]:
            clinical_priority_components["safety_penalty"] -= 35.0
            hard_block = True
            reasons_against.append("Antecedente convulsivo desaconseja apalutamida.")
            safety_modifiers_applied.append("seizure_risk")
        if modifiers["rash_history"] or modifiers["hypothyroidism"]:
            clinical_priority_components["toxicity_penalty"] -= 14.0
            reasons_against.append("El perfil de rash / hipotiroidismo desprioriza apalutamida.")
            safety_modifiers_applied.extend(
                item for item in ["rash_history", "hypothyroidism"] if modifiers.get(item)
            )
        elif modifiers["frailty_status"].lower() != "frail":
            clinical_priority_components["phenotype_bonus"] += 3.0
            reasons_for.append("Apalutamida sigue siendo una opción sólida si no hay rash severo ni fragilidad marcada.")
        # EPIC 9 Group A (GAP-2): QTc basal >470 ms también afecta apalutamida
        # (FDA Erleada §5.4: prolongación QTc reportada, menor magnitud que
        # enzalutamida pero clínicamente relevante).
        if modifiers.get("qtc_risk"):
            clinical_priority_components["safety_penalty"] -= 8.0
            reasons_against.append(
                "QTc basal >470 ms también restringe apalutamida; darolutamida es preferible en este perfil."
            )
            safety_modifiers_applied.append("qtc_risk")

    if regimen_code in {"ADT_ABIRATERONE", "ADT_DOCETAXEL_ABIRATERONE"}:
        # EPIC 9 Group B (GAP-7) — Child-Pugh B/C dispara hard-block de
        # abiraterona por sí solo, sin requerir `active_liver_disease`. Patrón
        # canónico clonado desde `m1_crpc/rules_nccn.py:121`:
        #     abiraterone_hard_block = hepatic_risk
        # donde `hepatic_risk = hepatic_bundle.hepatic_risk_present OR
        # child_pugh in {"B","C"}`. FDA Zytiga §2.3 recomienda reducción de
        # dosis en CP-B y evitar en CP-C; el sistema adopta postura
        # conservadora (hard-block en CP-B/C) siguiendo NCCN PROS-G que
        # refleja práctica clínica oncológica. El modificador
        # `modifiers["hepatic_risk"]` ya cubre ambos disparadores (line 163);
        # el `or modifiers["child_pugh"] in {"B","C"}` redundante queda
        # explícito como defensa en profundidad por si la normalización del
        # hepatic_safety_bundle fallase.
        if modifiers["hepatic_risk"] or modifiers["child_pugh"] in {"B", "C"}:
            clinical_priority_components["safety_penalty"] -= 45.0
            hard_block = True
            reasons_against.append("Child-Pugh B/C o riesgo hepático clínicamente relevante dispara hard-block de abiraterona (FDA Zytiga §2.3/§5.1; canonical pattern m1_crpc/rules_nccn.py:121).")
            safety_modifiers_applied.append("hepatic_risk")
        # EPIC 9 Group A (GAP-3): insuficiencia cardíaca NYHA III/IV o
        # LVEF <40% despriorizan abiraterona (COU-AA-302 excluyó NYHA III/IV;
        # FDA Zytiga §5.1 advierte precaución en HF clase III-IV).
        if modifiers.get("heart_failure_severe"):
            clinical_priority_components["safety_penalty"] -= 18.0
            reasons_against.append(
                "Insuficiencia cardíaca NYHA III/IV o LVEF <40% desaconseja abiraterona por sobrecarga mineralocorticoide."
            )
            safety_modifiers_applied.append("heart_failure_severe")
        if modifiers["seizure_risk"] or modifiers["cognitive_risk"]:
            penalty = 22.0 if regimen_code == "ADT_DOCETAXEL_ABIRATERONE" else 12.0
            clinical_priority_components["toxicity_penalty"] -= penalty
            reasons_against.append(
                "La vulnerabilidad neurocognitiva/CNS favorece un backbone con darolutamida sobre abiraterona."
                if regimen_code == "ADT_DOCETAXEL_ABIRATERONE"
                else "La vulnerabilidad neurocognitiva/CNS reduce la preferencia por abiraterona."
            )
            safety_modifiers_applied.extend(
                item for item in ["seizure_risk", "cognitive_risk"] if modifiers.get(item)
            )
        if str(modifiers.get("geriatric_screen_status") or "") in {"requires_cga", "unresolved_impairment", "adapted_treatment_required"}:
            penalty = 26.0 if regimen_code == "ADT_DOCETAXEL_ABIRATERONE" else 14.0
            clinical_priority_components["toxicity_penalty"] -= penalty
            reasons_against.append(
                "La evaluación geriátrica/neurocognitiva no resuelta impide que el triplete con abiraterona lidere hoy."
                if regimen_code == "ADT_DOCETAXEL_ABIRATERONE"
                else "La evaluación geriátrica/neurocognitiva no resuelta desprioriza abiraterona."
            )
            safety_modifiers_applied.append("geriatric_screen_status")
        if modifiers["cardio_risk"] or modifiers["edema_risk"] or modifiers["steroid_risk"]:
            clinical_priority_components["safety_penalty"] -= 16.0
            reasons_against.append("El perfil cardiovascular/metabólico y la carga de esteroides despriorizan abiraterona.")
            safety_modifiers_applied.extend(
                item for item in ["cardio_risk", "edema_risk", "steroid_risk"] if modifiers.get(item)
            )
        else:
            clinical_priority_components["phenotype_bonus"] += (
                8.0 if regimen_code == "ADT_DOCETAXEL_ABIRATERONE" and phenotype["state"] == "mcspc_high_volume_sync" else 5.0
            )
            reasons_for.append("Abiraterona es razonable si el perfil hepático y cardiometabólico es favorable.")
        if modifiers["visceral_metastases"] and phenotype["state"] == "mcspc_high_volume_sync":
            clinical_priority_components["phenotype_bonus"] += 3.0
            reasons_for.append("La enfermedad sincrónica de alto volumen con componente visceral mantiene a abiraterona como backbone trial-like competitivo.")
        if regimen_code == "ADT_ABIRATERONE" and phenotype["state"] == "mcspc_high_volume_sync" and docetaxel_default_intensification != "yes":
            if _abiraterone_override_eligible(phenotype, modifiers):
                clinical_priority_components["phenotype_bonus"] += 16.0
                reasons_for.append(
                    "El encaje LATITUDE-like muy robusto y la ausencia de banderas hepáticas, cardiometabólicas y por esteroides permiten que abiraterona supere a darolutamida de forma explícita."
                )
            elif modifiers["seizure_risk"]:
                clinical_priority_components["toxicity_penalty"] -= 8.0
                reasons_against.append(
                    "En alto volumen no apto para docetaxel con riesgo convulsivo, abiraterona no desplaza por defecto a darolutamida si no existe una justificación LATITUDE-like claramente favorable."
                )

    if modifiers["docetaxel_status"] == "fit_with_caution" and regimen_code.startswith("ADT_DOCETAXEL"):
        clinical_priority_components["toxicity_penalty"] -= 6.0 if regimen_code == "ADT_DOCETAXEL" else 8.0
        reasons_against.append("Docetaxel sigue siendo posible, pero con cautela por la reserva clínica actual.")
        safety_modifiers_applied.append("docetaxel_fit_with_caution")

    if not modifiers["ddi_reviewed"]:
        # BUG ERR-13: "Falta documentar interacciones" es un data-quality caveat,
        # no una contraindicación clínica — se mueve fuera de ``reasons_against``.
        major_ddi_context = modifiers.get("current_medications_present")
        if regimen_code == "ADT_ENZALUTAMIDE":
            clinical_priority_components["toxicity_penalty"] -= 12.0 if major_ddi_context else 6.0
            data_quality_caveats.append("Falta documentar revisión de interacciones farmacológicas con un ARPI de mayor carga CYP.")
            safety_modifiers_applied.append("ddi_not_reviewed")
        elif regimen_code == "ADT_APALUTAMIDE":
            clinical_priority_components["toxicity_penalty"] -= 10.0 if major_ddi_context else 5.0
            data_quality_caveats.append("Falta documentar revisión de interacciones farmacológicas antes de apalutamida.")
            safety_modifiers_applied.append("ddi_not_reviewed")
        elif regimen_code in {"ADT_ABIRATERONE", "ADT_DOCETAXEL_ABIRATERONE"}:
            clinical_priority_components["toxicity_penalty"] -= 6.0 if major_ddi_context else 3.0
            data_quality_caveats.append("La revisión DDI pendiente reduce la seguridad operativa de abiraterona.")
            safety_modifiers_applied.append("ddi_not_reviewed")
        elif regimen_code in {"ADT_DAROLUTAMIDE", "ADT_DOCETAXEL_DAROLUTAMIDE"}:
            clinical_priority_components["toxicity_penalty"] -= 4.0 if major_ddi_context else 2.0
            data_quality_caveats.append("Conviene cerrar la revisión de interacciones antes de darolutamida.")
            safety_modifiers_applied.append("ddi_not_reviewed")

    score = _neutral_base_score(regimen_code) + sum(float(value) for value in clinical_priority_components.values())
    if not hard_block and clinical_priority_components["safety_penalty"] <= -45:
        hard_block = True

    return {
        "score": score,
        "hard_block": hard_block,
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "data_quality_caveats": data_quality_caveats,
        "trial_fit": trial_fit,
        "evidence_maturity": evidence_maturity,
        "clinical_priority_components": clinical_priority_components,
        "safety_modifiers_applied": sorted(set(safety_modifiers_applied)),
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "benefit_basis": str(arpi_metadata.get("benefit_basis") or ""),
        "benefit_endpoint_used": str(arpi_metadata.get("benefit_endpoint_used") or ""),
        "benefit_maturity": str(arpi_metadata.get("benefit_maturity") or ""),
        "benefit_support": dict(arpi_metadata.get("benefit_support") or {}),
        "preference_confidence": str(arpi_metadata.get("preference_confidence") or "definitive"),
        "required_missing_fields": list(arpi_metadata.get("required_missing_fields") or []),
        "stale_inputs": list(arpi_metadata.get("stale_inputs") or []),
        "arpi_capture_contract": dict(arpi_metadata.get("arpi_capture_contract") or {}),
        "safety_drivers_used": sorted(
            set(list(evaluation_driver for evaluation_driver in arpi_metadata.get("safety_drivers_used") or []) + list(safety_modifiers_applied))
        ),
    }


def _build_recommendation(regimen_code: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    components = _regimen_components(regimen_code)
    delivery = _regimen_delivery_summary(components)
    description = _format_component_summary(components) or _regimen_label(regimen_code)
    preference_confidence = str(evaluation.get("preference_confidence") or "definitive")
    return {
        "regimen_code": regimen_code,
        "regimen_label": _regimen_label(regimen_code),
        "description": description,
        # ``priority`` and ``is_preferred`` are ranking outcomes, not capture
        # completeness flags. They are seeded as eligible/False here and
        # stamped to preferred/True on the winning regimen after the final
        # sort in :func:`select_mhspc_frontline_regimens`. ``preference_confidence``
        # remains the canonical signal for provisional ARPI captures.
        "priority": "eligible",
        "is_preferred": False,
        "selection_rationale": list(evaluation["reasons_for"]),
        "contraindication_reasons": list(evaluation["reasons_against"]),
        # BUG ERR-13: data quality caveats se exponen aparte para que la UI los
        # muestre como "Pendientes de captura" y no como contraindicaciones.
        "data_quality_caveats": list(evaluation.get("data_quality_caveats") or []),
        "pivotal_trial_fit": dict(evaluation["trial_fit"]),
        "guideline_basis": ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC"],
        "component_drugs": components,
        "dose": delivery["dose"],
        "route": delivery["route"],
        "schedule": delivery["schedule"],
        "imss_key": delivery["imss_key"],
        "score": round(float(evaluation["score"]), 1),
        "ranking_policy_version": evaluation.get("ranking_policy_version", RANKING_POLICY_VERSION),
        "clinical_priority_components": dict(evaluation.get("clinical_priority_components") or {}),
        "evidence_maturity": dict(evaluation.get("evidence_maturity") or {}),
        "safety_modifiers_applied": list(evaluation.get("safety_modifiers_applied") or []),
        "benefit_basis": str(evaluation.get("benefit_basis") or ""),
        "benefit_endpoint_used": str(evaluation.get("benefit_endpoint_used") or ""),
        "benefit_maturity": str(evaluation.get("benefit_maturity") or ""),
        "benefit_support": dict(evaluation.get("benefit_support") or {}),
        "preference_confidence": preference_confidence,
        "required_missing_fields": list(evaluation.get("required_missing_fields") or []),
        "stale_inputs": list(evaluation.get("stale_inputs") or []),
        "safety_drivers_used": list(evaluation.get("safety_drivers_used") or []),
        "institutional_weight": INSTITUTIONAL_WEIGHT_POLICY,
    }


def _eligible_treatment_item(recommendation: dict[str, Any], *, priority: str, notes_prefix: str = "") -> dict[str, Any]:
    components = recommendation.get("component_drugs") or []
    rationale = recommendation.get("selection_rationale") or []
    reasons_against = recommendation.get("contraindication_reasons") or []
    summary_parts = []
    if notes_prefix:
        summary_parts.append(notes_prefix)
    if rationale:
        summary_parts.append("A favor: " + "; ".join(rationale[:2]) + ".")
    if str(recommendation.get("preference_confidence") or "") == "provisional":
        pending = list(recommendation.get("required_missing_fields") or []) + list(recommendation.get("stale_inputs") or [])
        if pending:
            summary_parts.append("Preferencia provisional hasta completar: " + "; ".join(pending[:4]) + ".")
    if reasons_against and priority != "preferred":
        summary_parts.append("Límites: " + "; ".join(reasons_against[:2]) + ".")
    component_summary = _format_component_summary(components)
    if component_summary:
        summary_parts.append(component_summary)
    return {
        "name": recommendation.get("regimen_label", ""),
        # BUG ERR-05: expose ``regimen_label`` as a first-class field so
        # consumers that look it up per-row (wizard, comparative grid) stop
        # falling back to an empty string.
        "regimen_label": recommendation.get("regimen_label", ""),
        "description": recommendation.get("description") or recommendation.get("regimen_label", ""),
        "priority": priority,
        "notes": " ".join(part for part in summary_parts if part).strip(),
        "regimen_code": recommendation.get("regimen_code", ""),
        "component_drugs": components,
        "dose": recommendation.get("dose", ""),
        "route": recommendation.get("route", ""),
        "schedule": recommendation.get("schedule", ""),
        "imss_key": recommendation.get("imss_key", ""),
        "selection_rationale": list(recommendation.get("selection_rationale") or []),
        "contraindication_reasons": list(recommendation.get("contraindication_reasons") or []),
        "data_quality_caveats": list(recommendation.get("data_quality_caveats") or []),
        "pivotal_trial_fit": recommendation.get("pivotal_trial_fit", {}),
        "clinical_priority_components": dict(recommendation.get("clinical_priority_components") or {}),
        "evidence_maturity": dict(recommendation.get("evidence_maturity") or {}),
        "safety_modifiers_applied": list(recommendation.get("safety_modifiers_applied") or []),
        "benefit_basis": recommendation.get("benefit_basis", ""),
        "benefit_endpoint_used": recommendation.get("benefit_endpoint_used", ""),
        "benefit_maturity": recommendation.get("benefit_maturity", ""),
        "benefit_support": dict(recommendation.get("benefit_support") or {}),
        "preference_confidence": recommendation.get("preference_confidence", ""),
        "required_missing_fields": list(recommendation.get("required_missing_fields") or []),
        "stale_inputs": list(recommendation.get("stale_inputs") or []),
        "safety_drivers_used": list(recommendation.get("safety_drivers_used") or []),
        "metadata_source": "institutional_ingested_document",
    }


def _summarize_non_leader(entry: dict[str, Any], *, leader_score: float) -> str:
    if not entry:
        return "No hay datos comparativos disponibles."
    reasons = list(entry.get("contraindication_reasons") or [])
    if not reasons:
        reasons = ["No superó al líder por menor encaje clínico integral."]
    if float(entry.get("score") or 0) != 0:
        reasons.append(f"Puntaje clínico {float(entry.get('score') or 0):.1f} frente a {leader_score:.1f} del régimen líder.")
    return " ".join(reasons[:3]).strip()


def _find_regimen_entry(
    ranked: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    regimen_code: str,
) -> dict[str, Any]:
    for item in ranked + rejected:
        if str(item.get("regimen_code") or "") == regimen_code:
            return item
    return {}


def _build_ranking_trace(
    *,
    preferred: dict[str, Any],
    alternatives: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    modifiers: dict[str, Any],
    fallback_status: str = "normal",
) -> dict[str, Any]:
    if not preferred:
        # BUG ERR-08: when no leader was found we used to return empty strings
        # for winner_reason / why_not_* which left the front-end without any
        # explanation precisely in the hardest cases. Populate an explicit
        # fallback narrative so the UI can show *why* there is no preferred
        # regimen, together with the per-regimen hard_blocks dictionary.
        hard_blocks = {
            item["regimen_code"]: list(item.get("contraindication_reasons") or [])
            for item in rejected
            if item.get("hard_block")
        }
        all_blocked = fallback_status == "no_candidate" or (
            bool(rejected) and len(hard_blocks) == len(rejected)
        )
        fallback_msg = (
            "Ningún régimen supera las contraindicaciones duras actuales — escalar a revisión MDT."
            if all_blocked
            else "Ningún régimen superó el umbral de score clínico — requiere revisión MDT."
        )
        abiraterone_entry = _find_regimen_entry(alternatives, rejected, "ADT_ABIRATERONE")
        darolutamide_entry = _find_regimen_entry(alternatives, rejected, "ADT_DAROLUTAMIDE")
        triplet_candidates = [
            item
            for item in alternatives + rejected
            if _is_docetaxel_triplet(str(item.get("regimen_code") or ""))
        ]
        triplet_entry = max(
            triplet_candidates,
            key=lambda item: float(item.get("score") or 0.0),
            default={},
        )
        return {
            "policy_version": RANKING_POLICY_VERSION,
            "institutional_weight": INSTITUTIONAL_WEIGHT_POLICY,
            "winner_reason": fallback_msg,
            "why_not_abiraterone": _summarize_non_leader(abiraterone_entry, leader_score=0.0),
            "why_not_darolutamide": _summarize_non_leader(darolutamide_entry, leader_score=0.0),
            "why_not_triplet": _summarize_non_leader(triplet_entry, leader_score=0.0) if triplet_entry else "Triplete no viable — ver bloqueos de docetaxel.",
            "hard_blocks": hard_blocks,
            "evidence_basis": [],
            "safety_basis": [],
            "fallback_status": fallback_status or ("no_candidate" if all_blocked else "no_threshold"),
            "docetaxel_base_eligibility": modifiers.get("docetaxel_base_eligibility", ""),
            "docetaxel_verification_status": modifiers.get("docetaxel_verification_status", ""),
            "docetaxel_block_type": modifiers.get("docetaxel_block_type", ""),
            "docetaxel_trial_fit": dict(modifiers.get("docetaxel_trial_fit") or {}),
            "docetaxel_default_intensification": modifiers.get("docetaxel_default_intensification", ""),
            "performance_status_driver": modifiers.get("performance_status_driver", ""),
            "docetaxel_label_safety_reasons": list(modifiers.get("docetaxel_label_safety_reasons") or []),
            "docetaxel_stale_inputs": list(modifiers.get("docetaxel_stale_inputs") or []),
            "docetaxel_missing_inputs": list(modifiers.get("docetaxel_missing_inputs") or []),
        }
    leader_score = float(preferred.get("score") or 0.0)
    abiraterone_entry = _find_regimen_entry(alternatives, rejected, "ADT_ABIRATERONE")
    darolutamide_entry = _find_regimen_entry(alternatives, rejected, "ADT_DAROLUTAMIDE")
    triplet_candidates = [
        item
        for item in alternatives + rejected
        if _is_docetaxel_triplet(str(item.get("regimen_code") or ""))
    ]
    triplet_entry = max(triplet_candidates, key=lambda item: float(item.get("score") or 0.0), default={})
    hard_blocks = {
        item["regimen_code"]: list(item.get("contraindication_reasons") or [])
        for item in rejected
        if item.get("hard_block")
    }
    evidence_basis = list((preferred.get("pivotal_trial_fit") or {}).get("matched_trials") or [])
    evidence_rationale = str((preferred.get("evidence_maturity") or {}).get("rationale") or "").strip()
    if evidence_rationale:
        evidence_basis.append(evidence_rationale)
    return {
        "policy_version": RANKING_POLICY_VERSION,
        "institutional_weight": INSTITUTIONAL_WEIGHT_POLICY,
        "fallback_status": fallback_status or "normal",
        "winner_reason": " ".join(list(preferred.get("selection_rationale") or [])[:3]).strip(),
        "why_not_abiraterone": (
            "Abiraterona es el régimen líder actual."
            if str(preferred.get("regimen_code") or "") == "ADT_ABIRATERONE"
            else _summarize_non_leader(abiraterone_entry, leader_score=leader_score)
        ),
        "why_not_darolutamide": (
            "Darolutamida es el régimen líder actual."
            if str(preferred.get("regimen_code") or "") == "ADT_DAROLUTAMIDE"
            else _summarize_non_leader(darolutamide_entry, leader_score=leader_score)
        ),
        "why_not_triplet": (
            "El líder actual ya es un triplete con docetaxel."
            if _is_docetaxel_triplet(str(preferred.get("regimen_code") or ""))
            else (
                f"{triplet_entry.get('regimen_label') or triplet_entry.get('regimen_code') or 'Triplete con docetaxel'}: {_summarize_non_leader(triplet_entry, leader_score=leader_score)}"
                if triplet_entry
                else _summarize_non_leader(triplet_entry, leader_score=leader_score)
            )
        ),
        "hard_blocks": hard_blocks,
        "evidence_basis": evidence_basis,
        "safety_basis": list(preferred.get("safety_modifiers_applied") or []),
        "docetaxel_base_eligibility": modifiers.get("docetaxel_base_eligibility", ""),
        "docetaxel_verification_status": modifiers.get("docetaxel_verification_status", ""),
        "docetaxel_block_type": modifiers.get("docetaxel_block_type", ""),
        "docetaxel_trial_fit": dict(modifiers.get("docetaxel_trial_fit") or {}),
        "docetaxel_default_intensification": modifiers.get("docetaxel_default_intensification", ""),
        "performance_status_driver": modifiers.get("performance_status_driver", ""),
        "docetaxel_label_safety_reasons": list(modifiers.get("docetaxel_label_safety_reasons") or []),
        "docetaxel_stale_inputs": list(modifiers.get("docetaxel_stale_inputs") or []),
        "docetaxel_missing_inputs": list(modifiers.get("docetaxel_missing_inputs") or []),
        "docetaxel_lab_snapshot": dict(modifiers.get("docetaxel_lab_snapshot") or {}),
    }


def select_mhspc_frontline_regimens(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    docetaxel_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = normalize_advanced_support_payload(payload or {}, state=state)
    get_mhspc_frontline_reference()
    phenotype = _phenotype_profile(state, payload)
    modifiers = _modifier_profile(payload, state=phenotype["state"], docetaxel_bundle=docetaxel_bundle)
    arpi_candidates = candidate_regimens_for_state(phenotype["state"], payload)
    arpi_capture_contract = build_arpi_capture_contract(
        phenotype["state"],
        payload,
        candidate_regimens=arpi_candidates,
    )

    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    patient_modifiers = []

    if modifiers["seizure_risk"]:
        patient_modifiers.append("Riesgo convulsivo activo")
    if modifiers["cardio_risk"]:
        patient_modifiers.append("Riesgo cardiovascular documentado")
    if modifiers["hepatic_risk"]:
        patient_modifiers.append("Riesgo hepático relevante")
    if modifiers["frailty_status"].lower() in {"vulnerable", "frail"}:
        patient_modifiers.append(f"Fragilidad {modifiers['frailty_status']}")
    if modifiers["docetaxel_base_eligibility"] == "contraindicated":
        patient_modifiers.append("Docetaxel contraindicado")
    elif modifiers["docetaxel_verification_status"] == "pending_labs":
        patient_modifiers.append("Elegibilidad a docetaxel pendiente de validar")
    elif modifiers["docetaxel_verification_status"] == "stale_labs":
        patient_modifiers.append("Laboratorios de docetaxel vencidos")
    elif modifiers["docetaxel_default_intensification"] == "conditional":
        patient_modifiers.append("Docetaxel solo condicional")
    if _latitude_like(modifiers):
        patient_modifiers.append("Perfil LATITUDE-like")
    if arpi_capture_contract.get("arpi_profile_completeness") == "partial":
        patient_modifiers.append("Perfil ARPI incompleto")

    for regimen_code in REGIMEN_COMPONENTS:
        evaluation = _apply_modifiers(
            regimen_code,
            phenotype,
            modifiers,
            field_values=payload,
            arpi_candidates=arpi_candidates,
        )
        recommendation = _build_recommendation(regimen_code, evaluation)
        entry = {
            **recommendation,
            "hard_block": evaluation["hard_block"],
        }
        if evaluation["hard_block"] or evaluation["score"] < 48:
            entry["is_preferred"] = False
            entry["priority"] = "not_recommended"
            rejected.append(entry)
        else:
            scored.append(entry)

    scored.sort(key=lambda item: (float(item.get("score") or 0), item.get("regimen_label", "")), reverse=True)
    rejected.sort(key=lambda item: (float(item.get("score") or 0), item.get("regimen_label", "")))

    fallback_status = "normal"
    no_preferred_reason = ""
    if scored:
        # Stamp the winner. ``_build_recommendation`` seeds every regimen as
        # ``eligible``/``False``; the final sort decides who is preferred.
        # ``eligibility_status`` is added so the local ``preferred`` dict
        # matches the shape produced by ``build_global_ranking`` for the
        # comparative bundle, keeping consumers like ``patient_profile.html``
        # consistent regardless of which path populates the field.
        scored[0]["is_preferred"] = True
        scored[0]["priority"] = "preferred"
        scored[0]["eligibility_status"] = "preferred"
        preferred = dict(scored[0])
    else:
        # BUG ERR-01: when every regimen is either hard-blocked or below the
        # safety/score threshold, the selector used to return ``preferred = {}``
        # leaving the UI with an empty recommendation. Recover in two tiers:
        #   1) If at least one rejected regimen is NOT hard-blocked (it only
        #      failed the score threshold) promote the best of that subset as
        #      a ``conditional_fallback`` so the clinician still receives a
        #      candidate, flagged as provisional.
        #   2) If every regimen is hard-blocked, keep ``preferred = {}`` but
        #      populate ``no_preferred_reason`` with the aggregated hard-block
        #      explanations so the front-end explains why there is no leader.
        soft_candidates = [item for item in rejected if not item.get("hard_block")]
        if soft_candidates:
            soft_candidates.sort(
                key=lambda item: (float(item.get("score") or 0), item.get("regimen_label", "")),
                reverse=True,
            )
            fallback = dict(soft_candidates[0])
            fallback["is_preferred"] = True
            fallback["priority"] = "conditional_fallback"
            fallback["eligibility_status"] = "conditional_fallback"
            fallback["preference_confidence"] = "provisional"
            fallback["fallback_reason"] = (
                "Ningún régimen superó el umbral de score clínico — promoción condicional tras revisión MDT."
            )
            preferred = fallback
            fallback_status = "soft_fallback"
            # Remove the promoted candidate from ``rejected`` so it is not
            # counted twice in downstream consumers.
            rejected = [item for item in rejected if item.get("regimen_code") != fallback.get("regimen_code")]
        else:
            preferred = {}
            fallback_status = "no_candidate"
            aggregated_reasons: list[str] = []
            seen_fallback_reasons: set[str] = set()
            for item in rejected:
                for reason in list(item.get("contraindication_reasons") or []):
                    if reason and reason not in seen_fallback_reasons:
                        aggregated_reasons.append(reason)
                        seen_fallback_reasons.add(reason)
            no_preferred_reason = (
                "Ningún régimen supera las contraindicaciones duras actuales — escalar a revisión MDT. "
                + "; ".join(aggregated_reasons[:5])
            ).strip()
    alternatives = [dict(item, is_preferred=False, priority="eligible") for item in scored[1:4]]
    ranking_trace = _build_ranking_trace(
        preferred=preferred,
        alternatives=scored[1:],
        rejected=rejected,
        modifiers=modifiers,
        fallback_status=fallback_status,
    )

    eligible_treatments = []
    if preferred:
        eligible_treatments.append(
            _eligible_treatment_item(
                preferred,
                priority=str(preferred.get("priority") or ("preferred" if preferred.get("is_preferred") else "eligible")),
            )
        )
    for alternative in alternatives:
        eligible_treatments.append(_eligible_treatment_item(alternative, priority="eligible"))

    family_profiles: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    family_order: list[str] = []
    for item in scored:
        family_code = regimen_family_code(item.get("regimen_code"))
        grouped.setdefault(family_code, []).append(
            {
                **_eligible_treatment_item(item, priority="preferred" if item.get("is_preferred") else "eligible"),
                "family_code": family_code,
                "family_label": item.get("therapy_class_label") or family_code,
                "eligibility_status": (
                    "preferred"
                    if item.get("is_preferred")
                    else "eligible_with_caution"
                    if item.get("contraindication_reasons") or str(item.get("preference_confidence") or "") == "provisional"
                    else "eligible_nonpreferred"
                ),
                "why_this_rank": list(item.get("selection_rationale") or []),
                # BUG ERR-13: separar hard_blocks (clínicos) de
                # data_quality_caveats (captura/documentación).
                "hard_blocks": list(item.get("contraindication_reasons") or []),
                "caution_flags": list(item.get("contraindication_reasons") or []),
                "data_quality_caveats": list(item.get("data_quality_caveats") or []),
                "excluded_from_ranking": False,
            }
        )
        if family_code not in family_order:
            family_order.append(family_code)
    # BUG ERR-14: surface rejected regimens in the comparative matrix as well,
    # marked as excluded. Without this, the "all regimens considered" view can
    # be missing any ARPI/triplet that was hard-blocked, making it impossible
    # for the UI to explain why a family is absent.
    for item in rejected:
        family_code = regimen_family_code(item.get("regimen_code"))
        grouped.setdefault(family_code, []).append(
            {
                **_eligible_treatment_item(item, priority=str(item.get("priority") or "not_recommended")),
                "family_code": family_code,
                "family_label": item.get("therapy_class_label") or family_code,
                "eligibility_status": (
                    "hard_blocked" if item.get("hard_block") else "score_below_threshold"
                ),
                "why_this_rank": list(item.get("selection_rationale") or []),
                "hard_blocks": list(item.get("contraindication_reasons") or []),
                "caution_flags": list(item.get("contraindication_reasons") or []),
                "data_quality_caveats": list(item.get("data_quality_caveats") or []),
                "excluded_from_ranking": True,
            }
        )
        if family_code not in family_order:
            family_order.append(family_code)
    for family_code, items in grouped.items():
        family_profiles[family_code] = build_family_profile(
            family_code=family_code,
            ordered_regimens=items,
            context={
                "eligibility_status": "eligible" if items else "not_assessable",
                "caution_drivers": patient_modifiers,
                "missing_inputs": arpi_capture_contract.get("arpi_missing_inputs") if family_code in {"arpi_family", "abiraterone_steroid_family"} else [],
                "stale_inputs": arpi_capture_contract.get("arpi_stale_inputs") if family_code in {"arpi_family", "abiraterone_steroid_family"} else [],
                "winner_reason": f"La familia {family_code} se ordenó con el ranking clínico mHSPC vigente.",
                "why_not_preferred": "Las alternativas siguen visibles cuando no existe bloqueo duro, pero quedan detrás por evidencia, seguridad o encaje fenotípico.",
            },
        )
    comparative_bundle = build_comparative_bundle(
        family_profiles=family_profiles,
        family_order=family_order,
    )
    preferred_regimen_entry = dict(comparative_bundle.get("preferred_regimen") or {})
    sequence_transition_bundle = build_sequence_transition_bundle(
        state=phenotype["state"],
        preferred_regimen=preferred_regimen_entry,
        eligible_treatments=comparative_bundle.get("eligible_treatments") or eligible_treatments,
        current_treatment=payload.get("current_treatment") or "",
        missing_critical_inputs=list(modifiers.get("docetaxel_missing_inputs") or []),
        progression_pattern=str(payload.get("progression_pattern") or ""),
        line_context="mHSPC_initial",
        field_values=payload,
        comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
    )
    active_monitoring_package = build_active_regimen_monitoring_package(
        preferred_regimen_entry.get("regimen_code"),
        family_code=preferred_regimen_entry.get("family_code") or "arpi_family",
        field_values=payload,
    )

    # BUG ERR-06: expose the reasons both as the top-level dict AND as a
    # ``rejection_reasons`` field on each rejected row so consumers that
    # iterate ``frontline_regimen_rejections`` and read
    # ``item.rejection_reasons`` no longer see an empty list.
    for item in rejected:
        item["rejection_reasons"] = list(item.get("contraindication_reasons") or [])
    rejection_reasons = {
        item["regimen_code"]: list(item.get("contraindication_reasons") or [])
        for item in rejected
    }
    eligibility_gates = {
        "phenotype": phenotype,
        "docetaxel_fitness": modifiers["docetaxel"],
        "docetaxel_base_eligibility": modifiers["docetaxel_base_eligibility"],
        "docetaxel_verification_status": modifiers["docetaxel_verification_status"],
        "docetaxel_block_type": modifiers["docetaxel_block_type"],
        "docetaxel_required_now": modifiers["docetaxel_required_now"],
        "docetaxel_default_intensification": modifiers["docetaxel_default_intensification"],
        "docetaxel_trial_fit": dict(modifiers["docetaxel_trial_fit"]),
        "safety_modifiers": {
            "seizure_risk": modifiers["seizure_risk"],
            "cardio_risk": modifiers["cardio_risk"],
            "hepatic_risk": modifiers["hepatic_risk"],
            "renal_risk_severe": modifiers["renal_risk_severe"],
            "frailty_status": modifiers["frailty_status"],
        },
    }
    pivotal_fit = {
        item["regimen_code"]: dict(item.get("pivotal_trial_fit") or {})
        for item in scored + rejected
    }

    return {
        "ranking_policy_version": RANKING_POLICY_VERSION,
        "institutional_weight": INSTITUTIONAL_WEIGHT_POLICY,
        "ranking_trace": ranking_trace,
        "preferred_regimen": preferred,
        "overall_preferred_frontline_regimen": preferred,
        "preferred_frontline_regimen": preferred,
        "fallback_status": fallback_status,
        "no_preferred_reason": no_preferred_reason,
        "alternative_regimens": alternatives,
        "rejected_regimens": rejected,
        "rejection_reasons": rejection_reasons,
        "eligibility_gates": eligibility_gates,
        "pivotal_trial_fit": pivotal_fit,
        "patient_specific_modifiers": patient_modifiers,
        "eligible_treatments": comparative_bundle.get("eligible_treatments") or eligible_treatments,
        "frontline_regimen_rankings": scored,
        "frontline_regimen_rejections": rejected,
        "comparative_eligibility_matrix": comparative_bundle.get("comparative_eligibility_matrix") or {},
        "therapeutic_family_profiles": comparative_bundle.get("comparative_eligibility_matrix") or {},
        "sequence_transition_bundle": sequence_transition_bundle,
        "active_regimen_monitoring_package": active_monitoring_package,
        "drug_component_metadata": {
            item["regimen_code"]: item.get("component_drugs") or []
            for item in scored + rejected
        },
        "arpi_required_fields": list(arpi_capture_contract.get("arpi_required_fields") or []),
        "arpi_decision_required_fields": list(arpi_capture_contract.get("arpi_decision_required_fields") or []),
        "arpi_monitoring_required_fields": list(arpi_capture_contract.get("arpi_monitoring_required_fields") or []),
        "arpi_missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
        "arpi_stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
        "arpi_decision_missing_inputs": list(arpi_capture_contract.get("arpi_decision_missing_inputs") or []),
        "arpi_decision_stale_inputs": list(arpi_capture_contract.get("arpi_decision_stale_inputs") or []),
        "arpi_monitoring_missing_inputs": list(arpi_capture_contract.get("arpi_monitoring_missing_inputs") or []),
        "arpi_monitoring_stale_inputs": list(arpi_capture_contract.get("arpi_monitoring_stale_inputs") or []),
        "arpi_profile_completeness": str(arpi_capture_contract.get("arpi_profile_completeness") or ""),
        "arpi_preference_readiness": str(arpi_capture_contract.get("arpi_preference_readiness") or ""),
        "arpi_selection_contract": arpi_capture_contract,
    }


def preferred_non_triplet_regimen_label(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    selector_bundle: dict[str, Any] | None = None,
) -> str:
    # BUG ERR-15: evitar una segunda pasada completa del selector cuando ya
    # contamos con ``selector_bundle``. Cuando no existe un doblete visible
    # devolvemos "" en lugar del placeholder genérico para que la UI oculte la
    # sección en lugar de mostrar texto de relleno.
    selected = selector_bundle if selector_bundle is not None else select_mhspc_frontline_regimens(state, payload)
    preferred = dict(selected.get("preferred_regimen") or {})
    if preferred and not _is_docetaxel_triplet(str(preferred.get("regimen_code", ""))):
        return str(preferred.get("regimen_label") or "")
    for item in selected.get("alternative_regimens") or []:
        regimen_code = str(item.get("regimen_code") or "")
        if not _is_docetaxel_triplet(regimen_code):
            return str(item.get("regimen_label") or "")
    for item in selected.get("frontline_regimen_rankings") or []:
        regimen_code = str(item.get("regimen_code") or "")
        if not _is_docetaxel_triplet(regimen_code):
            return str(item.get("regimen_label") or "")
    return ""
