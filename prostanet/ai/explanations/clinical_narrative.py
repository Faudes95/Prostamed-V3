"""
Clinical Narrative Generator — AI explanations → Spanish clinical text.

Transforms model outputs and feature importance into structured
clinical narratives suitable for physician review and patient communication.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_clinical_narrative(
    prediction_type: str,
    prediction: dict[str, Any],
    feature_importance: dict[str, float] | None = None,
    record: dict[str, Any] | None = None,
) -> str:
    """
    Generate a clinical narrative in Spanish for a prediction.

    Returns a human-readable string explaining the AI's reasoning.
    """
    if prediction_type == "state_transition":
        return _narrate_state_transition(prediction, feature_importance, record)
    elif prediction_type == "treatment_response":
        return _narrate_treatment_response(prediction, feature_importance)
    elif prediction_type == "survival":
        return _narrate_survival(prediction, feature_importance)
    elif prediction_type == "anomaly":
        return _narrate_anomaly(prediction)
    else:
        return f"Predicción tipo '{prediction_type}' generada por modelo AI."


def _narrate_state_transition(
    pred: dict[str, Any],
    importance: dict[str, float] | None,
    record: dict[str, Any] | None,
) -> str:
    state = pred.get("predicted_state", "desconocido")
    prob = pred.get("predicted_state_probability", 0)
    time_months = pred.get("median_time_months", "?")
    confidence = pred.get("confidence", 0)

    lines = [
        f"El modelo de transición de estado predice evolución a **{state}** "
        f"con una probabilidad del **{prob:.0%}**.",
    ]

    if time_months != "?":
        lines.append(f"Tiempo estimado: **{time_months} meses** (mediana).")

    if pred.get("ci_95_lower") and pred.get("ci_95_upper"):
        lines.append(
            f"Intervalo de confianza 95%: {pred['ci_95_lower']:.1f} – {pred['ci_95_upper']:.1f} meses."
        )

    if confidence:
        lines.append(f"Auto-evaluación de confianza del modelo: {confidence:.0%}.")

    # Top features driving the prediction
    if importance:
        top = list(importance.items())[:5]
        if top:
            lines.append("\nFactores más influyentes en la predicción:")
            for feature, weight in top:
                feature_name = _translate_feature(feature)
                lines.append(f"  • {feature_name}: {weight:.1%}")

    # Clinical context
    if record:
        baseline = record.get("baseline", {}) or {}
        psa = baseline.get("baseline_psa")
        if psa:
            lines.append(f"\nContexto: PSA basal {psa} ng/mL.")

    return "\n".join(lines)


def _narrate_treatment_response(
    pred: dict[str, Any],
    importance: dict[str, float] | None,
) -> str:
    psa50 = pred.get("psa50_probability", 0)
    psa90 = pred.get("psa90_probability", 0)
    rpfs = pred.get("rpfs_median_months")

    lines = [
        "Predicción de respuesta al tratamiento:",
        f"  • Probabilidad de PSA50: **{psa50:.0%}**",
        f"  • Probabilidad de PSA90: **{psa90:.0%}**",
    ]

    if rpfs:
        lines.append(f"  • rPFS mediana estimada: **{rpfs:.1f} meses**")

    toxicity = pred.get("toxicity_profile", {})
    if toxicity:
        high_tox = {k: v for k, v in toxicity.items() if v > 0.2}
        if high_tox:
            lines.append("\nRiesgos de toxicidad significativos (>20%):")
            for domain, risk in sorted(high_tox.items(), key=lambda x: -x[1]):
                lines.append(f"  • {_translate_toxicity(domain)}: {risk:.0%}")

    return "\n".join(lines)


def _narrate_survival(
    pred: dict[str, Any],
    importance: dict[str, float] | None,
) -> str:
    lines = ["Curvas de supervivencia personalizadas:"]

    for endpoint_key, endpoint_data in pred.items():
        if not isinstance(endpoint_data, dict):
            continue
        median = endpoint_data.get("median_months")
        prob_24 = endpoint_data.get("survival_probabilities", {}).get("24")

        if median:
            lines.append(f"  • {endpoint_key}: mediana {median:.1f} meses")
        if prob_24 is not None:
            lines.append(f"    Supervivencia a 2 años: {prob_24:.0%}")

        # Published comparison
        published = endpoint_data.get("published_median")
        if published:
            lines.append(f"    Referencia publicada: {published} meses")

    return "\n".join(lines)


def _narrate_anomaly(pred: dict[str, Any]) -> str:
    is_anomalous = pred.get("is_anomalous", False)
    anomalies = pred.get("detected_anomalies", [])

    if not is_anomalous:
        return "No se detectaron anomalías en las series temporales de laboratorio."

    lines = [
        f"**ALERTA**: Se detectaron {len(anomalies)} anomalía(s) en series de laboratorio:",
    ]

    for a in anomalies:
        feature = _translate_feature(a.get("feature", ""))
        z_score = a.get("z_score", 0)
        severity = a.get("severity", "warning")
        lines.append(
            f"  • {feature}: z-score = {z_score:.1f} [{severity.upper()}]"
        )

    lines.append(
        "\nRecomendación: Evaluar interferencia analítica, "
        "cambio de tratamiento reciente, o progresión oculta."
    )

    return "\n".join(lines)


FEATURE_TRANSLATIONS = {
    "age": "Edad",
    "baseline_psa": "PSA basal",
    "psa": "PSA",
    "ecog_score": "ECOG",
    "gleason_primary": "Gleason primario",
    "gleason_secondary": "Gleason secundario",
    "isup_grade": "Grado ISUP",
    "hemoglobin": "Hemoglobina",
    "testosterone": "Testosterona",
    "alp": "Fosfatasa alcalina",
    "ldh": "LDH",
    "albumin": "Albúmina",
    "creatinine": "Creatinina",
    "hrr_status": "Estado HRR",
    "psma_positive": "PSMA positivo",
    "metastasis_count": "Conteo de metástasis",
    "pain_score": "Escala de dolor",
}


def _translate_feature(feature: str) -> str:
    return FEATURE_TRANSLATIONS.get(feature, feature)


TOXICITY_TRANSLATIONS = {
    "hematologic": "Hematológica",
    "hepatic": "Hepática",
    "cardiovascular": "Cardiovascular",
    "fatigue": "Fatiga",
    "gastrointestinal": "Gastrointestinal",
    "neuropathy": "Neuropatía",
    "dermatologic": "Dermatológica",
    "endocrine": "Endocrina",
}


def _translate_toxicity(domain: str) -> str:
    return TOXICITY_TRANSLATIONS.get(domain, domain)


# ══════════════════════════════════════════════════════════════════════════════
# ClinicalNarrativeEngine — Class interface
# ══════════════════════════════════════════════════════════════════════════════

class ClinicalNarrativeEngine:
    """
    Generates structured clinical narratives in Spanish from AI predictions,
    agent outputs, and patient data.

    Designed for physician-facing output: precise, evidence-based, actionable.

    Usage::
        narrator = ClinicalNarrativeEngine()
        narrative = narrator.generate(patient, recommendation='Olaparib 300mg BID')
        full = narrator.generate_full_summary(patient, agent_outputs)
    """

    def generate(
        self,
        patient: dict[str, Any],
        recommendation: str | None = None,
        prediction_type: str = "general",
        prediction: dict[str, Any] | None = None,
        feature_importance: dict[str, float] | None = None,
    ) -> str:
        """
        Generate a clinical narrative for a patient.

        Args:
            patient:           Full patient record
            recommendation:    Clinical recommendation text (optional)
            prediction_type:   Type of prediction to narrate
            prediction:        Prediction output dict (optional)
            feature_importance: Feature importance scores (optional)

        Returns:
            Spanish clinical narrative string.
        """
        if prediction:
            return generate_clinical_narrative(
                prediction_type=prediction_type,
                prediction=prediction,
                feature_importance=feature_importance,
                record=patient,
            )

        # Generic narrative based on patient data
        return self._build_generic_narrative(patient, recommendation)

    def generate_full_summary(
        self,
        patient: dict[str, Any],
        agent_outputs: list[dict[str, Any]] | None = None,
        recommendations: list[str] | None = None,
    ) -> str:
        """
        Generate a complete clinical summary narrative integrating all agent outputs.

        This is the master narrative shown to the physician after a full
        recalculation cycle.
        """
        lines = ["═══ NARRATIVA CLÍNICA INTEGRADA (ProstaNet AI) ═══", ""]

        # Patient context
        state = patient.get("current_state") or patient.get("state") or "no especificado"
        psa = patient.get("psa") or patient.get("latest_psa")
        ecog = patient.get("ecog")

        lines += [
            f"Estado clínico: {state}",
            f"PSA: {float(psa):.1f} ng/mL" if psa else "PSA: no disponible",
            f"ECOG: {int(float(ecog))}" if ecog is not None else "",
            "",
        ]

        # Key biomarkers
        biomarkers = []
        if patient.get("ar_v7"):
            biomarkers.append("AR-V7 positivo")
        if patient.get("brca2_loss"):
            biomarkers.append("BRCA2 pérdida bialélica")
        if patient.get("hrr_positive"):
            biomarkers.append("HRR positivo")
        if patient.get("msi_h"):
            biomarkers.append("MSI-H")
        if patient.get("ctc_count") is not None:
            ctc = int(patient["ctc_count"])
            biomarkers.append(f"CTC: {ctc}/7.5 mL ({'desfavorable' if ctc >= 5 else 'favorable'})")
        if biomarkers:
            lines += ["Biomarcadores relevantes:", "  " + " | ".join(biomarkers), ""]

        # Agent outputs
        if agent_outputs:
            lines.append("Hallazgos por agente:")
            for out in agent_outputs:
                agent_id = out.get("agent_id", "agente")
                recs = out.get("recommendations") or []
                if recs:
                    lines.append(f"\n  [{agent_id.upper()}]")
                    for rec in recs[:2]:  # Top 2 recommendations per agent
                        text = rec.get("text") or rec.get("recommendation") or str(rec)
                        lines.append(f"    → {text}")

        # Final recommendations
        if recommendations:
            lines += ["", "RECOMENDACIONES PRIORIZADAS:"]
            for i, rec in enumerate(recommendations[:5], 1):
                lines.append(f"  {i}. {rec}")

        lines += ["", "Generado por ProstaNet AI — requiere validación clínica antes de implementar."]
        return "\n".join(line for line in lines if line is not None)

    def _build_generic_narrative(
        self,
        patient: dict[str, Any],
        recommendation: str | None = None,
    ) -> str:
        """Build a generic narrative when no specific prediction type is given."""
        state = patient.get("current_state") or patient.get("state") or "no especificado"
        psa = patient.get("psa") or patient.get("latest_psa")

        parts = [f"Paciente con diagnóstico de cáncer de próstata en estado {state}."]

        if psa:
            parts.append(f"PSA actual: {float(psa):.1f} ng/mL.")

        tx_hist = patient.get("treatment_history") or []
        if tx_hist:
            lines_count = len(tx_hist)
            parts.append(f"Ha recibido {lines_count} línea(s) de tratamiento.")

        if patient.get("brca2_loss") or patient.get("hrr_positive"):
            parts.append("Perfil genómico: HRR positivo — candidato a PARP inhibidores.")

        if patient.get("ar_v7"):
            parts.append("AR-V7 positivo — resistencia esperada a agentes hormonales de nueva generación.")

        if recommendation:
            parts.append(f"\nRecomendación: {recommendation}")

        return " ".join(parts)
