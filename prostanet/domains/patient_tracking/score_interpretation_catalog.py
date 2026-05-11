from __future__ import annotations

from typing import Any

EPIC26_VISIBLE_SCORE_KEYS = (
    "epic26_urinary_incontinence_domain",
    "epic26_urinary_irritative_domain",
    "epic26_bowel_domain",
    "epic26_sexual_domain",
    "epic26_hormonal_domain",
    "epic26_overall_urinary_bother",
)


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


def _base_payload(
    score_key: str,
    score_label_es: str,
    score_value: Any,
    *,
    directionality: str,
    score_grade_es: str,
    clinical_equivalence_es: str,
    band_range: str = "",
    score_text_es: str = "",
) -> dict[str, Any]:
    return {
        "score_key": score_key,
        "score_label_es": score_label_es,
        "score_value": score_value,
        "directionality": directionality,
        "score_grade_es": score_grade_es,
        "clinical_equivalence_es": clinical_equivalence_es,
        "band_range": band_range,
        "score_text_es": score_text_es or f"{score_label_es}: {score_grade_es}",
        "available": score_value not in (None, ""),
    }


def interpret_ipss(value: Any) -> dict[str, Any]:
    score = _safe_int(value)
    if score is None:
        return _base_payload("ipss_total", "IPSS", value, directionality="higher_is_worse", score_grade_es="No disponible", clinical_equivalence_es="Sin carga urinaria cuantificable.")
    if score <= 7:
        return _base_payload("ipss_total", "IPSS", score, directionality="higher_is_worse", score_grade_es="Leve", clinical_equivalence_es="Carga urinaria baja.", band_range="0-7")
    if score <= 19:
        return _base_payload("ipss_total", "IPSS", score, directionality="higher_is_worse", score_grade_es="Moderado", clinical_equivalence_es="Carga urinaria intermedia.", band_range="8-19")
    return _base_payload("ipss_total", "IPSS", score, directionality="higher_is_worse", score_grade_es="Severo", clinical_equivalence_es="Carga urinaria alta con impacto clínico importante.", band_range="20-35")


def interpret_iief5(value: Any) -> dict[str, Any]:
    score = _safe_int(value)
    if score is None:
        return _base_payload("iief5_score", "IIEF-5", value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Sin función sexual cuantificada.")
    if score >= 22:
        return _base_payload("iief5_score", "IIEF-5", score, directionality="higher_is_better", score_grade_es="Función eréctil normal", clinical_equivalence_es="Impacto sexual clínicamente bajo.", band_range="22-25")
    if score >= 17:
        return _base_payload("iief5_score", "IIEF-5", score, directionality="higher_is_better", score_grade_es="Disfunción leve", clinical_equivalence_es="Impacto sexual leve.", band_range="17-21")
    if score >= 12:
        return _base_payload("iief5_score", "IIEF-5", score, directionality="higher_is_better", score_grade_es="Disfunción leve a moderada", clinical_equivalence_es="Impacto sexual intermedio.", band_range="12-16")
    if score >= 8:
        return _base_payload("iief5_score", "IIEF-5", score, directionality="higher_is_better", score_grade_es="Disfunción moderada", clinical_equivalence_es="Impacto sexual clínicamente relevante.", band_range="8-11")
    return _base_payload("iief5_score", "IIEF-5", score, directionality="higher_is_better", score_grade_es="Disfunción severa", clinical_equivalence_es="Impacto sexual alto con pérdida funcional importante.", band_range="5-7")


def interpret_bpi_worst_pain(value: Any) -> dict[str, Any]:
    score = _safe_int(value)
    if score is None:
        return _base_payload("bpi_worst_pain", "BPI dolor máximo", value, directionality="higher_is_worse", score_grade_es="No disponible", clinical_equivalence_es="Sin dolor autorreportado cuantificado.")
    if score <= 3:
        return _base_payload("bpi_worst_pain", "BPI dolor máximo", score, directionality="higher_is_worse", score_grade_es="Dolor leve", clinical_equivalence_es="Controlable con analgesia habitual.", band_range="0-3")
    if score <= 6:
        return _base_payload("bpi_worst_pain", "BPI dolor máximo", score, directionality="higher_is_worse", score_grade_es="Dolor moderado", clinical_equivalence_es="Requiere escalamiento analgésico y reevaluación clínica.", band_range="4-6")
    return _base_payload("bpi_worst_pain", "BPI dolor máximo", score, directionality="higher_is_worse", score_grade_es="Dolor severo", clinical_equivalence_es="Sugiere urgencia de control sintomático y búsqueda de progresión o complicación.", band_range="7-10")


def interpret_eq5d_vas(value: Any) -> dict[str, Any]:
    score = _safe_int(value)
    if score is None:
        return _base_payload("eq5d_vas", "EQ-5D VAS", value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Sin calidad de vida global cuantificada.")
    if score >= 80:
        return _base_payload("eq5d_vas", "EQ-5D VAS", score, directionality="higher_is_better", score_grade_es="Calidad de vida alta", clinical_equivalence_es="Tolerancia funcional global alta.", band_range="80-100")
    if score >= 60:
        return _base_payload("eq5d_vas", "EQ-5D VAS", score, directionality="higher_is_better", score_grade_es="Compromiso leve", clinical_equivalence_es="Compromiso funcional leve.", band_range="60-79")
    if score >= 40:
        return _base_payload("eq5d_vas", "EQ-5D VAS", score, directionality="higher_is_better", score_grade_es="Compromiso moderado", clinical_equivalence_es="Compromiso funcional moderado.", band_range="40-59")
    return _base_payload("eq5d_vas", "EQ-5D VAS", score, directionality="higher_is_better", score_grade_es="Calidad de vida muy baja", clinical_equivalence_es="Tolerancia funcional global críticamente comprometida.", band_range="<40")


def interpret_facit_f(value: Any) -> dict[str, Any]:
    score = _safe_float(value)
    if score is None:
        return _base_payload("facit_fatigue_total", "FACIT-F", value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Sin fatiga estructurada cuantificada.")
    if score >= 40:
        return _base_payload("facit_fatigue_total", "FACIT-F", score, directionality="higher_is_better", score_grade_es="Fatiga baja", clinical_equivalence_es="Reserva funcional conservada.", band_range="40-52")
    if score >= 30:
        return _base_payload("facit_fatigue_total", "FACIT-F", score, directionality="higher_is_better", score_grade_es="Fatiga intermedia", clinical_equivalence_es="Reserva funcional parcialmente limitada.", band_range="30-39")
    if score >= 20:
        return _base_payload("facit_fatigue_total", "FACIT-F", score, directionality="higher_is_better", score_grade_es="Fatiga clínicamente relevante", clinical_equivalence_es="La fatiga ya condiciona actividad y tolerancia terapéutica.", band_range="20-29")
    return _base_payload("facit_fatigue_total", "FACIT-F", score, directionality="higher_is_better", score_grade_es="Fatiga incapacitante", clinical_equivalence_es="La reserva funcional está gravemente limitada por fatiga.", band_range="<20")


def interpret_fact_p(value: Any) -> dict[str, Any]:
    score = _safe_float(value)
    if score is None:
        return _base_payload("fact_p_total", "FACT-P", value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Sin calidad de vida específica de enfermedad avanzada cuantificada.")
    if score >= 110:
        return _base_payload("fact_p_total", "FACT-P", score, directionality="higher_is_better", score_grade_es="Bien conservado", clinical_equivalence_es="Carga sintomática y funcional global baja.", band_range=">=110")
    if score >= 90:
        return _base_payload("fact_p_total", "FACT-P", score, directionality="higher_is_better", score_grade_es="Afectación leve", clinical_equivalence_es="Compromiso sintomático leve.", band_range="90-109")
    if score >= 70:
        return _base_payload("fact_p_total", "FACT-P", score, directionality="higher_is_better", score_grade_es="Afectación moderada", clinical_equivalence_es="Carga sintomática y funcional intermedia.", band_range="70-89")
    return _base_payload("fact_p_total", "FACT-P", score, directionality="higher_is_better", score_grade_es="Afectación marcada", clinical_equivalence_es="Carga sintomática y funcional alta de enfermedad avanzada.", band_range="<70")


def interpret_fatigue_score(value: Any) -> dict[str, Any]:
    score = _safe_int(value)
    if score is None:
        return _base_payload("fatigue_score", "Fatiga basal", value, directionality="higher_is_worse", score_grade_es="No disponible", clinical_equivalence_es="Sin fatiga estructurada cuantificada.")
    if score <= 3:
        return _base_payload("fatigue_score", "Fatiga basal", score, directionality="higher_is_worse", score_grade_es="Fatiga leve", clinical_equivalence_es="Actividad global conservada.", band_range="0-3")
    if score <= 6:
        return _base_payload("fatigue_score", "Fatiga basal", score, directionality="higher_is_worse", score_grade_es="Fatiga moderada", clinical_equivalence_es="Limita parcialmente actividad y tolerancia terapéutica.", band_range="4-6")
    return _base_payload("fatigue_score", "Fatiga basal", score, directionality="higher_is_worse", score_grade_es="Fatiga severa", clinical_equivalence_es="Limita de forma importante la actividad y la tolerancia al tratamiento.", band_range="7-10")


def interpret_epic26_domain(domain_key: str, value: Any) -> dict[str, Any]:
    label_map = {
        "epic26_urinary_incontinence_domain": "EPIC-26 urinario: incontinencia",
        "epic26_urinary_irritative_domain": "EPIC-26 urinario: irritativo/obstructivo",
        "epic26_urinary_domain": "EPIC-26 función urinaria",
        "epic26_sexual_domain": "EPIC-26 función sexual",
        "epic26_bowel_domain": "EPIC-26 función intestinal",
        "epic26_hormonal_domain": "EPIC-26 síntomas hormonales",
        "epic26_overall_urinary_bother": "EPIC-26 molestia urinaria global",
    }
    score = _safe_float(value)
    label = label_map.get(domain_key, domain_key)
    if score is None:
        return _base_payload(domain_key, label, value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Dominio EPIC-26 no cuantificado.")
    if score >= 80:
        grade = "Preservada"
        eq = "Función preservada."
        band = "80-100"
    elif score >= 60:
        grade = "Levemente afectada"
        eq = "Impacto funcional leve."
        band = "60-79"
    elif score >= 40:
        grade = "Moderadamente afectada"
        eq = "Impacto funcional clínicamente relevante."
        band = "40-59"
    else:
        grade = "Severamente afectada"
        eq = "Compromiso funcional alto que debe modular decisiones y seguimiento."
        band = "<40"
    return _base_payload(domain_key, label, score, directionality="higher_is_better", score_grade_es=grade, clinical_equivalence_es=eq, band_range=band)


def interpret_eortc_function(label: str, score_key: str, value: Any) -> dict[str, Any]:
    score = _safe_float(value)
    if score is None:
        return _base_payload(score_key, label, value, directionality="higher_is_better", score_grade_es="No disponible", clinical_equivalence_es="Escala funcional no cuantificada.")
    if score >= 80:
        grade, eq, band = "Bien conservada", "Función global preservada.", "80-100"
    elif score >= 60:
        grade, eq, band = "Compromiso leve", "Compromiso funcional leve.", "60-79"
    elif score >= 40:
        grade, eq, band = "Compromiso moderado", "Compromiso funcional moderado.", "40-59"
    else:
        grade, eq, band = "Compromiso severo", "Compromiso funcional alto con impacto clínico importante.", "<40"
    return _base_payload(score_key, label, score, directionality="higher_is_better", score_grade_es=grade, clinical_equivalence_es=eq, band_range=band)


def interpret_eortc_symptom(label: str, score_key: str, value: Any) -> dict[str, Any]:
    score = _safe_float(value)
    if score is None:
        return _base_payload(score_key, label, value, directionality="higher_is_worse", score_grade_es="No disponible", clinical_equivalence_es="Síntoma no cuantificado.")
    if score < 20:
        grade, eq, band = "Bajo", "Carga sintomática baja.", "0-19"
    elif score < 40:
        grade, eq, band = "Leve", "Carga sintomática leve.", "20-39"
    elif score < 60:
        grade, eq, band = "Moderado", "Carga sintomática moderada.", "40-59"
    else:
        grade, eq, band = "Alto", "Carga sintomática alta con impacto clínico relevante.", "60-100"
    return _base_payload(score_key, label, score, directionality="higher_is_worse", score_grade_es=grade, clinical_equivalence_es=eq, band_range=band)


def interpret_pirads(value: Any) -> dict[str, Any]:
    score = str(value or "").strip().upper()
    mapping = {
        "1": ("Muy baja", "Muy baja probabilidad de cáncer clínicamente significativo."),
        "2": ("Baja", "Baja probabilidad de cáncer clínicamente significativo."),
        "3": ("Indeterminada", "Probabilidad intermedia o incierta; suele requerir integración con PSAD y biopsia."),
        "4": ("Alta", "Alta probabilidad de cáncer clínicamente significativo."),
        "5": ("Muy alta", "Muy alta probabilidad de cáncer clínicamente significativo."),
    }
    grade, eq = mapping.get(score, ("No disponible", "Sin categorización PI-RADS válida."))
    return _base_payload("pirads_v21_score", "PI-RADS v2.1", score or value, directionality="higher_is_worse", score_grade_es=grade, clinical_equivalence_es=eq, band_range=score)


def interpret_psma_rads(value: Any) -> dict[str, Any]:
    score = str(value or "").strip().upper()
    mapping = {
        "1": ("Benigno probable", "Hallazgo probablemente benigno."),
        "2": ("Baja sospecha", "Poca probabilidad de enfermedad relevante."),
        "3A": ("Indeterminado local", "Hallazgo indeterminado local; puede requerir correlación adicional."),
        "3B": ("Indeterminado extraprostatico", "Hallazgo indeterminado fuera de la próstata; requiere correlación clínica e imagen."),
        "4": ("Sospechoso", "Alta sospecha de enfermedad por PSMA."),
        "5": ("Altamente sugestivo", "Hallazgo fuertemente sugestivo de enfermedad activa por PSMA."),
    }
    grade, eq = mapping.get(score, ("No disponible", "Sin categorización PSMA-RADS válida."))
    return _base_payload("psma_rads_score", "PSMA-RADS", score or value, directionality="higher_is_worse", score_grade_es=grade, clinical_equivalence_es=eq, band_range=score)


def interpret_ctdna_vaf(value: Any) -> dict[str, Any]:
    score = _safe_float(value)
    if score is None:
        return _base_payload("ctdna_vaf", "ctDNA VAF", value, directionality="higher_is_worse", score_grade_es="No disponible", clinical_equivalence_es="Sin carga molecular cuantificada.")
    if score < 1:
        grade, eq, band = "Carga baja", "Refinador biológico de baja carga.", "<1%"
    elif score < 5:
        grade, eq, band = "Carga intermedia", "Refinador biológico intermedio; integrar con PSA, imagen y clínica.", "1-4.9%"
    else:
        grade, eq, band = "Carga alta", "Sugiere carga biológica relevante, sin confirmar progresión por sí sola.", ">=5%"
    return _base_payload("ctdna_vaf", "ctDNA VAF", score, directionality="higher_is_worse", score_grade_es=grade, clinical_equivalence_es=eq, band_range=band)


def interpret_ctcae(value: Any) -> dict[str, Any]:
    grade = _safe_int(value)
    mapping = {
        1: ("Leve", "Evento adverso leve."),
        2: ("Moderado", "Evento adverso moderado."),
        3: ("Severo", "Evento adverso severo con impacto clínico mayor."),
        4: ("Amenaza vital", "Evento adverso potencialmente mortal."),
        5: ("Muerte relacionada", "Muerte relacionada al evento adverso."),
    }
    score_grade_es, eq = mapping.get(grade, ("No disponible", "Sin graduación CTCAE válida."))
    return _base_payload("ctcae_grade", "CTCAE", grade if grade is not None else value, directionality="higher_is_worse", score_grade_es=score_grade_es, clinical_equivalence_es=eq, band_range=str(grade or ""))


def build_score_interpretation_snapshot(field_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    field_values = dict(field_values or {})
    snapshot: dict[str, dict[str, Any]] = {}
    direct_interpreters = {
        "ipss_total": interpret_ipss,
        "iief5_score": interpret_iief5,
        "bpi_worst_pain": interpret_bpi_worst_pain,
        "eq5d_vas": interpret_eq5d_vas,
        "facit_fatigue_total": interpret_facit_f,
        "fatigue_score": interpret_fatigue_score,
        "fact_p_total": interpret_fact_p,
        "pirads_v21_score": interpret_pirads,
        "pirads_score": interpret_pirads,
        "prior_mpmri_pirads_score": interpret_pirads,
        "psma_rads_score": interpret_psma_rads,
        "ctdna_vaf": interpret_ctdna_vaf,
        "ctcae_grade": interpret_ctcae,
    }
    for key, interpreter in direct_interpreters.items():
        if key in field_values and field_values.get(key) not in (None, ""):
            snapshot[key] = interpreter(field_values.get(key))
    for key in (
        "epic26_urinary_incontinence_domain",
        "epic26_urinary_irritative_domain",
        "epic26_urinary_domain",
        "epic26_sexual_domain",
        "epic26_bowel_domain",
        "epic26_hormonal_domain",
        "epic26_overall_urinary_bother",
    ):
        if field_values.get(key) not in (None, ""):
            snapshot[key] = interpret_epic26_domain(key, field_values.get(key))
    eortc_function_fields = {
        "eortc_qlq_c30_global_health": "EORTC QLQ-C30 salud global",
        "eortc_qlq_c30_physical": "EORTC QLQ-C30 función física",
        "eortc_qlq_c30_role": "EORTC QLQ-C30 función de rol",
        "eortc_qlq_c30_emotional": "EORTC QLQ-C30 función emocional",
    }
    for key, label in eortc_function_fields.items():
        if field_values.get(key) not in (None, ""):
            snapshot[key] = interpret_eortc_function(label, key, field_values.get(key))
    eortc_symptom_fields = {
        "eortc_qlq_c30_fatigue": "EORTC QLQ-C30 fatiga",
        "eortc_qlq_c30_pain": "EORTC QLQ-C30 dolor",
        "eortc_qlq_c30_urinary": "EORTC QLQ-C30 síntomas urinarios",
    }
    for key, label in eortc_symptom_fields.items():
        if field_values.get(key) not in (None, ""):
            snapshot[key] = interpret_eortc_symptom(label, key, field_values.get(key))
    return snapshot


def extract_epic26_domain_scorecards(snapshot: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    snapshot = dict(snapshot or {})
    return [dict(snapshot[key]) for key in EPIC26_VISIBLE_SCORE_KEYS if snapshot.get(key)]
