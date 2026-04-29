from __future__ import annotations

from typing import Any


def classify_eau(payload: dict[str, Any]) -> dict[str, Any]:
    psa = float(payload.get("psa") or 0)
    isup = int(payload.get("isup_grade") or 1)
    tstage = str(payload.get("clinical_tstage") or "T2a").upper()
    nodal_status = str(payload.get("nodal_status") or "N0").upper()
    metastasis_site = str(payload.get("metastasis_site") or "M0").upper()
    pct = float(payload.get("pct_cores_positive", 0) or 0)

    if metastasis_site not in {"M0", "", "NONE"}:
        return {
            "label": "Metastásico",
            "risk_group": "METASTATIC",
            "treatment_intent": "Ruta de tratamiento sistémico.",
        }
    if nodal_status == "N1" or tstage in {"T3A", "T3B", "T4"}:
        return {
            "label": "Localmente avanzado",
            "risk_group": "LOCALLY ADVANCED",
            "treatment_intent": "Ruta de tratamiento multimodal.",
        }
    if psa > 20 or isup >= 4 or tstage == "T2C":
        return {
            "label": "Alto",
            "risk_group": "HIGH",
            "treatment_intent": "Terapia local definitiva con intensificación sistémica prolongada cuando esté indicada.",
        }
    if 10 <= psa <= 20 or isup in {2, 3} or tstage == "T2B":
        subgroup = "Unfavorable" if isup == 3 or pct >= 0.5 else "Favorable"
        return {
            "label": "Intermedio desfavorable" if subgroup == "Unfavorable" else "Intermedio favorable",
            "risk_group": f"INTERMEDIATE ({subgroup.upper()})",
            "treatment_intent": "Decisión compartida entre prostatectomía radical y radioterapia; los casos desfavorables requieren intensificación.",
        }
    return {
        "label": "Bajo",
        "risk_group": "LOW",
        "treatment_intent": "La vigilancia activa es preferente cuando la esperanza de vida lo respalda.",
    }
