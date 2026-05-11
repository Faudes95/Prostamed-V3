from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.laboratory_intelligence.contracts import LaboratoryAlert


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_laboratory_alerts(latest_values: dict[str, Any], *, treatment_text: str = "", adt_context: str = "") -> list[LaboratoryAlert]:
    alerts: list[LaboratoryAlert] = []
    treatment_text_lower = str(treatment_text or "").lower()

    testosterone = _safe_float(latest_values.get("testosterone"))
    if testosterone is not None and (adt_context or "adt" in treatment_text_lower or "leupro" in treatment_text_lower or "degarel" in treatment_text_lower):
        if testosterone > 50:
            alerts.append(
                LaboratoryAlert(
                    key="testosterone_not_castrate",
                    severity="warning",
                    category="endocrine",
                    biomarker_key="testosterone",
                    title="Testosterona > 50 ng/dL bajo ADT",
                    message=f"Testosterona {testosterone:.1f} ng/dL. La castración no está lograda pese a terapia de privación androgénica.",
                    recommended_action="Verificar adherencia y formulación de ADT; repetir testosterona y redefinir la vía antes de etiquetar CRPC.",
                    guideline_reference="NCCN 2026 avanzada",
                    triggering_value=f"{testosterone:.1f} ng/dL",
                    threshold="> 50 ng/dL",
                )
            )

    hemoglobin = _safe_float(latest_values.get("hemoglobin"))
    if hemoglobin is not None:
        if hemoglobin < 8:
            severity = "critical"
            title = "Anemia severa (Hb < 8 g/dL)"
            action = "Evaluar transfusión, sangrado, infiltración medular y adaptar intensidad terapéutica."
            threshold = "< 8 g/dL"
        elif hemoglobin < 10:
            severity = "warning"
            title = "Anemia significativa (Hb < 10 g/dL)"
            action = "Investigar causa, síntomas y necesidad de soporte transfusional o ajuste terapéutico."
            threshold = "< 10 g/dL"
        else:
            severity = ""
        if severity:
            alerts.append(
                LaboratoryAlert(
                    key="hemoglobin_low",
                    severity=severity,
                    category="hematologic",
                    biomarker_key="hemoglobin",
                    title=title,
                    message=f"Hemoglobina {hemoglobin:.1f} g/dL durante seguimiento oncológico.",
                    recommended_action=action,
                    guideline_reference="NCCN Supportive Care / CTCAE v5",
                    triggering_value=f"{hemoglobin:.1f} g/dL",
                    threshold=threshold,
                )
            )

    alp = _safe_float(latest_values.get("alp"))
    if alp is not None and alp > 240:
        alerts.append(
            LaboratoryAlert(
                key="alp_high",
                severity="critical" if alp > 360 else "warning",
                category="bone_burden",
                biomarker_key="alp",
                title="Fosfatasa alcalina elevada",
                message=f"ALP {alp:.0f} UI/L. La elevación puede reflejar progresión ósea o hepatopatía asociada.",
                recommended_action="Correlacionar con síntomas, imagen ósea/PSMA y bundle de salud ósea.",
                guideline_reference="NCCN 2026 avanzada",
                triggering_value=f"{alp:.0f} UI/L",
                threshold="> 240 UI/L",
            )
        )

    ldh = _safe_float(latest_values.get("ldh"))
    if ldh is not None and ldh > 250:
        alerts.append(
            LaboratoryAlert(
                key="ldh_high",
                severity="warning",
                category="tumor_burden",
                biomarker_key="ldh",
                title="LDH elevada",
                message=f"LDH {ldh:.0f} UI/L. Puede acompañar carga tumoral alta o progresión más agresiva.",
                recommended_action="Interpretar junto a imagen, dolor, ALP y curso de PSA antes de decidir secuencia.",
                guideline_reference="NCCN 2026 avanzada",
                triggering_value=f"{ldh:.0f} UI/L",
                threshold="> 250 UI/L",
            )
        )

    creatinine = _safe_float(latest_values.get("creatinine"))
    if creatinine is not None and creatinine >= 1.5:
        alerts.append(
            LaboratoryAlert(
                key="creatinine_high",
                severity="warning",
                category="renal",
                biomarker_key="creatinine",
                title="Deterioro renal relevante",
                message=f"Creatinina {creatinine:.2f} mg/dL. Puede modificar contraste, seguridad sistémica y uso de ácido zoledrónico.",
                recommended_action="Revisar hidratación, obstrucción, necesidad de imagen y fármacos potencialmente nefrotóxicos.",
                guideline_reference="NCCN 2026 / safety renal",
                triggering_value=f"{creatinine:.2f} mg/dL",
                threshold="≥ 1.5 mg/dL",
            )
        )

    ast = _safe_float(latest_values.get("ast"))
    alt = _safe_float(latest_values.get("alt"))
    bilirubin = _safe_float(latest_values.get("bilirubin"))
    if "abirater" in treatment_text_lower:
        if (ast is not None and ast > 120) or (alt is not None and alt > 120) or (bilirubin is not None and bilirubin > 2):
            alerts.append(
                LaboratoryAlert(
                    key="abiraterone_hepatotoxicity",
                    severity="critical",
                    category="hepatic",
                    biomarker_key="ast" if (ast or 0) >= (alt or 0) else "alt",
                    title="Hepatotoxicidad relevante bajo abiraterona",
                    message=(
                        f"AST {ast:.0f} / ALT {alt:.0f} UI/L, bilirrubina {bilirubin:.2f} mg/dL."
                        if ast is not None and alt is not None and bilirubin is not None
                        else "Transaminasas o bilirrubina elevadas durante tratamiento con abiraterona."
                    ),
                    recommended_action="Revisar urgencia de suspensión/retención, repetir panel hepático y revalorar continuidad del ARPI.",
                    guideline_reference="FDA ZYTIGA Prescribing Information / NCCN 2026",
                    triggering_value=f"AST {ast or 'N/D'} · ALT {alt or 'N/D'} · Bil {bilirubin or 'N/D'}",
                    threshold="AST/ALT > 3x ULN o bilirrubina > 2x ULN",
                )
            )

    return alerts
