from __future__ import annotations

from typing import Any

from prostanet.shared.genomic_classifier_scores import classify_genomic_score
from prostanet.shared.life_expectancy import classify_localized_life_expectancy_band


def _resolve_genomic_band(payload: dict[str, Any]) -> tuple[str, str, str]:
    """EPIC 2 FIX-LOCALIZED-GENOMIC: resuelve la banda genómica consumiendo
    el score numérico cuando está disponible, en lugar de depender del
    campo categórico ``genomic_classifier_result``.

    Retorna ``(band, classifier_name, narrative)``. ``band`` ∈
    ``{"low", "intermediate", "high", ""}`` (cadena vacía si no hay datos).
    Si el numérico diverge del categórico, prevalece el numérico (documentado
    en Spratt 2018: HR 1.24 por cada 0.1 punto de Decipher).
    """
    categorical = str(payload.get("genomic_classifier_result") or "").strip().lower()
    mapping = {
        "alto": "high",
        "high": "high",
        "desfavorable": "high",
        "unfavorable": "high",
        "intermedio": "intermediate",
        "intermediate": "intermediate",
        "bajo": "low",
        "low": "low",
        "favorable": "low",
    }
    fallback_band = mapping.get(categorical, "")

    # Determinar qué clasificador tiene score numérico disponible.
    score_candidates = (
        ("decipher", payload.get("decipher_score_numeric") or payload.get("decipher_score")),
        ("prolaris", payload.get("prolaris_ccp_score")),
        ("oncotype", payload.get("oncotype_gps")),
    )
    for classifier, score in score_candidates:
        if score in (None, ""):
            continue
        verdict = classify_genomic_score(
            classifier=classifier,
            score=score,
            categorical_band=categorical or None,
        )
        band = str(verdict.get("band") or "").lower()
        narrative = str(verdict.get("narrative") or "")
        if band:
            return band, classifier, narrative
    return fallback_band, "", ""


def _attach_protocol_ranking(
    payload: dict[str, Any],
    position: dict[str, Any],
    nccn_group: str,
) -> dict[str, Any]:
    """Agrega `recommended_protocol` + `protocol_ranking` al dict de posición.

    Idempotente: si el paciente no es elegible a AS, devuelve position sin tocar.
    Importación perezosa para evitar ciclo con patient_tracking.
    """
    if not position.get("eligible"):
        return position
    try:
        from prostanet.domains.patient_tracking.active_surveillance import (
            rank_recommended_protocols,
            recommended_protocol,
        )
    except ImportError:
        return position

    ranking = rank_recommended_protocols(payload, nccn_group)
    primary = recommended_protocol(payload, nccn_group)
    if ranking:
        position["protocol_ranking"] = ranking
    if primary:
        position["recommended_protocol"] = primary
    return position


def classify_nccn(payload: dict[str, Any]) -> dict[str, Any]:
    tstage = str(payload.get("clinical_tstage") or "T2a").upper()
    gg = int(payload.get("isup_grade") or 1)
    psa = float(payload.get("psa") or 0)
    n_pos = int(payload.get("num_cores_positive") or 0)
    total_cores = max(int(payload.get("total_cores") or 12), 1)
    pct = payload.get("pct_cores_positive")
    if pct in (None, ""):
        pct = n_pos / total_cores
    pct = float(pct or 0)
    nodal_status = str(payload.get("nodal_status", "N0")).upper()

    if nodal_status == "N1":
        return {
            "label": "Regional N1M0",
            "risk_group": "REGIONAL N1M0",
            "reasons": ["Regional node-positive non-metastatic disease."],
            "recommendation": "Considerar radioterapia definitiva más terapia de privación androgénica prolongada e intensificación sistémica en pacientes elegibles.",
        }

    high_risk_features = 0
    if tstage in {"T3A", "T3B", "T4"}:
        high_risk_features += 1
    if gg >= 4:
        high_risk_features += 1
    if psa > 20:
        high_risk_features += 1

    very_high_features = 0
    if tstage in {"T3A", "T3B", "T4"}:
        very_high_features += 1
    if gg >= 4:
        very_high_features += 1
    if psa > 40:
        very_high_features += 1
    if very_high_features >= 2:
        return {
            "label": "Muy alto",
            "risk_group": "VERY HIGH",
            "reasons": ["At least two very-high-risk features by NCCN 5.2026."],
            "recommendation": "Radioterapia externa más terapia de privación androgénica prolongada con intensificación sistémica en pacientes elegibles, o prostatectomía radical en candidatos seleccionados.",
        }

    if high_risk_features >= 1:
        return {
            "label": "Alto",
            "risk_group": "HIGH",
            "reasons": ["At least one high-risk feature by NCCN 5.2026."],
            "recommendation": "Radioterapia externa más terapia de privación androgénica prolongada, o prostatectomía radical con disección ganglionar pélvica en pacientes seleccionados.",
        }

    ir_factors = 0
    if tstage in {"T2B", "T2C"}:
        ir_factors += 1
    if gg in {2, 3}:
        ir_factors += 1
    if 10 <= psa <= 20:
        ir_factors += 1

    if gg == 3 or ir_factors >= 2 or pct >= 0.5:
        return {
            "label": "Intermedio desfavorable",
            "risk_group": "UNFAVORABLE INTERMEDIATE",
            "reasons": ["GG3, multiple intermediate-risk factors, or >=50% positive cores."],
            "recommendation": "Radioterapia más terapia de privación androgénica de corta duración, o prostatectomía radical en pacientes elegibles.",
        }

    if ir_factors == 1:
        life_band = classify_localized_life_expectancy_band(payload.get("life_expectancy_years"))
        recommendation = "Observación o terapia local definitiva; la vigilancia activa solo debe plantearse en pacientes cuidadosamente seleccionados con esperanza de vida mayor de 10 años."
        if life_band["band"] == "between_5_and_10_years":
            recommendation = "En pacientes asintomáticos con esperanza de vida entre 5 y 10 años, la observación clínica es preferente; radioterapia o prostatectomía radical quedan como alternativas individualizadas."
        elif life_band["band"] == "le_5_years":
            recommendation = "Con esperanza de vida menor o igual a 5 años, la observación clínica suele desplazar una terapia local definitiva automática en enfermedad intermedia favorable."
        return {
            "label": "Intermedio favorable",
            "risk_group": "FAVORABLE INTERMEDIATE",
            "reasons": ["Single intermediate-risk factor, GG1-2, and <50% positive cores."],
            "recommendation": recommendation,
        }

    life_band = classify_localized_life_expectancy_band(payload.get("life_expectancy_years"))
    low_risk_recommendation = "La vigilancia activa es preferente para la mayoría de los pacientes con esperanza de vida mayor o igual a 10 años; observación si es menor."
    if life_band["band"] == "between_5_and_10_years":
        low_risk_recommendation = "En enfermedad de bajo riesgo y expectativa de vida entre 5 y 10 años, la observación clínica suele ser preferente frente a terapia local definitiva."
    elif life_band["band"] == "le_5_years":
        low_risk_recommendation = "En enfermedad de bajo riesgo y expectativa de vida menor o igual a 5 años, la observación clínica domina claramente sobre una terapia local definitiva automática."
    return {
        "label": "Bajo",
        "risk_group": "LOW",
        "reasons": ["cT1-T2a, GG1, PSA <10 without higher-risk features."],
        "recommendation": low_risk_recommendation,
    }


def active_surveillance_position(payload: dict[str, Any], nccn_group: str) -> dict[str, Any]:
    """Posición de VA + ranking de protocolos recomendados (EPIC 5).

    Wrapper: delega al core NCCN y luego cablea `recommended_protocol` y
    `protocol_ranking` cuando el paciente es elegible a AS.
    """
    position = _active_surveillance_position_core(payload, nccn_group)
    return _attach_protocol_ranking(payload, position, nccn_group)


def _active_surveillance_position_core(payload: dict[str, Any], nccn_group: str) -> dict[str, Any]:
    gg = int(payload.get("isup_grade") or 1)
    psad = float(payload.get("psad") or 0)
    pct = float(payload.get("pct_cores_positive") or 0)
    max_inv = float(payload.get("max_core_involvement", 0) or 0)
    life_expectancy = float(payload.get("life_expectancy_years", 15) or 15)
    percent_pattern_4 = float(payload.get("percent_pattern_4", 0) or 0)
    cribriform = str(payload.get("cribriform_pattern", "0")) == "1"
    intraductal = str(payload.get("intraductal_carcinoma", "0")) == "1"
    prior_mpmri = str(payload.get("prior_mpmri", "0")) == "1"
    confirmatory_biopsy_planned = str(payload.get("confirmatory_biopsy_planned", "0")) == "1"
    pirads_score = _normalize_pirads(payload.get("prior_mpmri_pirads_score"))
    targeted_biopsy_status = str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido") or "desconocido")
    genomic_result = str(payload.get("genomic_classifier_result", "No aplica"))
    # EPIC 2 FIX-LOCALIZED-GENOMIC: el numérico prevalece sobre el categórico.
    genomic_band, genomic_source_classifier, genomic_narrative = _resolve_genomic_band(payload)
    brca2_family_risk = str(payload.get("brca2_family_risk", "0")) == "1"
    micro_us_available = str(payload.get("micro_us_available", "0")) == "1"
    adverse_variant_type = _normalized_adverse_variant(payload)
    neuroendocrine_features = str(payload.get("neuroendocrine_features", "0")) == "1"
    risk_pathway = str(payload.get("risk_calculator_pathway", "No usado"))
    life_band = classify_localized_life_expectancy_band(life_expectancy)
    severe_variant = adverse_variant_type in {"small_cell_neuroendocrine", "sarcomatoid", "signet_ring", "mixed_multiple", "other_aggressive", "other_aggressive_unspecified"}
    any_adverse_variant = adverse_variant_type not in {"", "none"}

    if severe_variant or neuroendocrine_features:
        return {
            "eligible": False,
            "status": "not_recommended",
            "summary": "La vigilancia activa no es apropiada porque existe una variante histológica adversa de muy alto riesgo o rasgos neuroendocrinos emergentes.",
            "requires_escalation": True,
            "adverse_variant_type": adverse_variant_type,
        }
    if cribriform or intraductal or any_adverse_variant:
        return {
            "eligible": False,
            "status": "not_recommended",
            "summary": "La vigilancia activa no se favorece porque existe histología adversa, incluida variante específica, patrón cribiforme o carcinoma intraductal.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }
    if brca2_family_risk:
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": "La vigilancia activa pierde prioridad cuando existe una señal hereditaria tipo BRCA2 que eleva el riesgo biológico infravalorado.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }
    if genomic_band == "high":
        # EPIC 2 FIX-LOCALIZED-GENOMIC: resuelto por score numérico > categórico.
        source_label = (
            f"Clasificador {genomic_source_classifier} con score numérico"
            if genomic_source_classifier
            else "Clasificador genómico categórico"
        )
        summary = (
            "La vigilancia activa pierde prioridad cuando el clasificador genómico sugiere alto riesgo biológico. "
            f"{source_label} ubica al paciente en banda alta."
        )
        if genomic_narrative:
            summary = f"{summary} {genomic_narrative}"
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": summary,
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
            "genomic_band": genomic_band,
            "genomic_source_classifier": genomic_source_classifier,
        }
    if prior_mpmri and pirads_score is None:
        return {
            "eligible": True,
            "status": "selected_candidate",
            "summary": "La vigilancia activa puede seguir sobre la mesa, pero no debe priorizarse hasta documentar el PI-RADS de la resonancia magnética previa.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    if nccn_group == "LOW":
        if not prior_mpmri or not confirmatory_biopsy_planned:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "La vigilancia activa sigue siendo razonable, pero la preparación al estilo 2026 requiere resonancia magnética previa y biopsia confirmatoria planificada.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score is not None and pirads_score >= 4 and targeted_biopsy_status != "si":
            return {
                "eligible": False,
                "status": "not_preferred",
                "summary": "Con PI-RADS 4 o 5 sin biopsia dirigida documentada, la vigilancia activa no debe sostenerse como opción preferente hasta completar confirmación dirigida.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score is not None and pirads_score >= 4:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "Incluso con histología favorable, un PI-RADS 4 o 5 no permite mantener vigilancia activa como preferente; como máximo queda como candidato seleccionado con seguimiento reforzado.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score == 3:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "Con PI-RADS 3, PSAD baja y estrategia confirmatoria estructurada, la vigilancia activa puede mantenerse como candidato seleccionado, no como preferente automática.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if life_expectancy >= 10:
            return {
                "eligible": True,
                "status": "preferred",
                "summary": (
                    "La vigilancia activa es preferente en enfermedad de bajo riesgo con una esperanza de vida mayor o igual a 10 años."
                    if risk_pathway == "No usado" and not micro_us_available
                    else "La vigilancia activa es preferente en enfermedad de bajo riesgo con una esperanza de vida mayor o igual a 10 años y gana robustez cuando existen pathways MRI + PSAD o micro-US."
                ),
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        observation_summary = "La observación suele ser preferente cuando la esperanza de vida es menor de 10 años."
        if life_band["band"] == "between_5_and_10_years":
            observation_summary = "Entre 5 y 10 años de expectativa de vida, la observación clínica suele ser preferente frente a vigilancia activa protocolizada en enfermedad de bajo riesgo."
        elif life_band["band"] == "le_5_years":
            observation_summary = "Con expectativa de vida menor o igual a 5 años, la observación clínica desplaza con más fuerza la utilidad de vigilancia activa protocolizada en enfermedad de bajo riesgo."
        return {
            "eligible": True,
            "status": "observation_preferred",
            "summary": observation_summary,
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    if nccn_group == "FAVORABLE INTERMEDIATE":
        selected = (
            gg <= 2
            and psad < 0.15
            and pct < 0.34
            and max_inv <= 0.5
            and percent_pattern_4 <= 10
            and life_expectancy > 10
            and prior_mpmri
            and confirmatory_biopsy_planned
            and genomic_band != "high"  # EPIC 2 FIX-LOCALIZED-GENOMIC: respeta score numérico
            and pirads_score in {None, 2, 3}
            and not (pirads_score and pirads_score >= 4)
            and targeted_biopsy_status in {"si", "desconocido"}
        )
        if pirads_score is not None and pirads_score >= 4 and targeted_biopsy_status != "si":
            selected = False
        summary = "En este contexto se favorece la terapia local definitiva por encima de la vigilancia activa."
        if life_band["band"] == "between_5_and_10_years":
            summary = "En intermedio favorable con expectativa de vida entre 5 y 10 años, la observación clínica suele pesar más que una vigilancia activa protocolizada; la terapia local definitiva se individualiza."
        elif life_band["band"] == "le_5_years":
            summary = "En intermedio favorable con expectativa de vida menor o igual a 5 años, la observación clínica pesa claramente más que una vigilancia activa protocolizada o una terapia local automática."
        return {
            "eligible": selected,
            "status": "selected_candidate" if selected else "not_preferred",
            "summary": (
                "La vigilancia activa solo puede considerarse en casos intermedios favorables seleccionados, con resonancia magnética previa, plan de biopsia confirmatoria y sin histología adversa."
                if selected
                else summary
            ),
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    return {
        "eligible": False,
        "status": "not_recommended",
        "summary": "Este grupo de riesgo de la Red Nacional Integral del Cáncer (NCCN) 2026 no es apropiado para vigilancia activa como estrategia principal de manejo.",
        "requires_escalation": False,
        "adverse_variant_type": adverse_variant_type,
    }


def _normalize_pirads(value: Any) -> int | None:
    if value in (None, "", "desconocido"):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed in {2, 3, 4, 5} else None


def _normalized_adverse_variant(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("adverse_histology_variant_type", "none") or "none").strip()
    if explicit and explicit != "none":
        return explicit
    if str(payload.get("rare_histology_variant", "0")) == "1":
        return "other_aggressive_unspecified"
    return "none"


def focal_therapy_eligibility(payload: dict[str, Any], nccn_group: str = "") -> dict[str, Any]:
    """EPIC 8 — Evalúa candidatura a terapia focal selectiva (NCCN PROS-C 2B).

    Consume el payload localized y mapea los campos disponibles hacia el
    dominio ``focal_therapy`` (importación perezosa para evitar ciclos).
    Devuelve el mismo dict que ``classify_focal_therapy_nccn`` más campos
    ``offered`` y ``offer_reasons`` que indican si debe mostrarse el bundle
    focal al paciente en la UI del carril localized_initial.

    ``nccn_group`` es opcional; cuando se proporciona permite acelerar la
    decisión sin re-ejecutar ``classify_nccn``.
    """
    try:
        from prostanet.domains.focal_therapy.rules_nccn import (
            classify_focal_therapy_nccn,
        )
    except Exception:
        return {
            "eligible": False,
            "label": "Terapia focal no disponible (módulo no cargado)",
            "offered": False,
            "offer_reasons": [],
        }

    risk_group = (nccn_group or str(payload.get("nccn_risk_group") or "")).strip().upper()
    if not risk_group:
        try:
            risk_group = str(classify_nccn(payload).get("risk_group") or "").upper()
        except Exception:
            risk_group = ""

    # Mapeo localized → focal: homologar nombres y valores.
    focal_payload = {
        "age": payload.get("age"),
        "life_expectancy_years": payload.get("life_expectancy_years"),
        "psa": payload.get("psa"),
        "gleason_primary": payload.get("gleason_primary"),
        "gleason_secondary": payload.get("gleason_secondary"),
        "isup_grade": payload.get("isup_grade"),
        "nccn_risk_group": risk_group.replace(" ", "_").lower() if risk_group else "",
        "lesion_unilateral": payload.get("lesion_unilateral"),
        "lesion_maxdim_mm": payload.get("lesion_maxdim_mm"),
        "mri_psa_density": payload.get("mri_psa_density"),
        "prostate_volume_ml": payload.get("prostate_volume_ml"),
        "lesion_location_apical": payload.get("lesion_location_apical"),
        "urinary_obstructive_symptoms": payload.get("urinary_obstructive_symptoms"),
        "focal_modality_preferred": payload.get("focal_modality_preferred"),
        "patient_priority_profile": payload.get("patient_priority_profile"),
    }
    verdict = classify_focal_therapy_nccn(focal_payload)

    # "offered" = mostrar el bundle focal en UI: aplica sólo a riesgos
    # compatibles con PROS-C cat 2B (favorable intermediate / low).
    offered = risk_group in {
        "FAVORABLE INTERMEDIATE",
        "LOW",
        "VERY LOW",
    }
    reasons: list[str] = []
    if offered:
        reasons.append(
            f"Grupo NCCN {risk_group.title()} admite discutir terapia focal selectiva como alternativa a AS / RP / RT."
        )
        if verdict.get("eligible"):
            reasons.append("Criterios PROS-C cat 2B cumplidos: lesión unilateral + volumen adecuado + sin apical anterior.")
        else:
            reasons.extend(list(verdict.get("exclusion_reasons") or []))
    verdict["offered"] = bool(offered)
    verdict["offer_reasons"] = reasons
    return verdict
