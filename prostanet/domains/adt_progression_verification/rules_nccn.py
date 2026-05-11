from __future__ import annotations


def classify_nccn(payload: dict) -> dict:
    castrate_status = _normalize_castrate_status(payload)
    progression_pattern = str(payload.get("progression_pattern", "biochemical_only") or "biochemical_only")
    imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()
    psadt = float(payload.get("psadt_months", 999) or 999)

    if castrate_status == "not_castrate":
        return {
            "label": "Fracaso de supresión androgénica / castración inadecuada",
            "risk_group": "ADT_FAILURE",
            "classification": "suppression_failure_or_inadequate_castration",
            "reasons": [
                "No existe testosterona en rango de castración pese a progresión bajo ADT.",
                "Debe optimizarse la supresión androgénica antes de etiquetar CRPC.",
            ],
            "recommendation": "Optimizar la terapia de privación androgénica, revisar adherencia y confirmar testosterona en rango de castración antes de intensificar como CRPC.",
        }
    if castrate_status != "confirmed_castrate":
        return {
            "label": "Progresión bajo ADT pendiente de verificación",
            "risk_group": "ADT_VERIFICATION",
            "classification": "biochemical_progression_on_adt_pending_verification",
            "reasons": [
                "Hay progresión bajo ADT, pero la testosterona en rango de castración no está confirmada.",
                "No debe asignarse CRPC hasta completar verificación biológica y reestadificación.",
            ],
            "recommendation": "Solicitar testosterona y reestadificación con imagen convencional antes de catalogar enfermedad resistente a la castración.",
        }
    if imaging_status == "M1":
        return {
            "label": "Candidato confirmado a M1 CRPC",
            "risk_group": "M1_CRPC_CANDIDATE",
            "classification": "confirmed_mcrpc_candidate",
            "reasons": [
                "Existe progresión con testosterona en rango de castración.",
                "La imagen convencional documenta enfermedad metastásica.",
            ],
            "recommendation": "Redirigir a la ruta de enfermedad resistente a la castración con metástasis para secuenciación guiada por biomarcadores y terapias previas.",
        }
    if imaging_status == "M0":
        risk_note = (
            "El tiempo de duplicación del PSA es corto y encaja con un patrón de alto riesgo para enfermedad resistente a la castración sin metástasis."
            if psadt <= 10
            else "El tiempo de duplicación del PSA es más largo y puede sostener una observación estrecha dentro de la ruta M0 CRPC."
        )
        return {
            "label": "Candidato confirmado a M0 CRPC",
            "risk_group": "M0_CRPC_CANDIDATE",
            "classification": "confirmed_nmcrpc_candidate",
            "reasons": [
                "Existe progresión con testosterona en rango de castración.",
                "La imagen convencional permanece sin metástasis a distancia.",
                risk_note,
            ],
            "recommendation": "Redirigir a la ruta de enfermedad resistente a la castración sin metástasis y decidir intensificación según el tiempo de duplicación del PSA y el perfil de seguridad.",
        }
    return {
        "label": "Progresión bajo ADT pendiente de reestadificación",
        "risk_group": "ADT_VERIFICATION",
        "classification": "biochemical_progression_on_adt_pending_verification",
        "reasons": [
            "Existe progresión bajo ADT con testosterona en rango de castración.",
            "La imagen convencional aún no aclara si el escenario es M0 o M1.",
        ],
        "recommendation": "Completar reestadificación convencional antes de etiquetar M0 CRPC o M1 CRPC.",
    }


def _normalize_castrate_status(payload: dict) -> str:
    explicit = str(payload.get("castrate_testosterone_status", "unknown") or "unknown")
    if explicit in {"confirmed_castrate", "not_castrate", "unknown"}:
        return explicit
    if str(payload.get("castrate_testosterone_confirmed", "0")) == "1":
        return "confirmed_castrate"
    testosterone_value = payload.get("testosterone_value")
    if testosterone_value not in (None, ""):
        try:
            return "confirmed_castrate" if float(testosterone_value) <= 50 else "not_castrate"
        except (TypeError, ValueError):
            return "unknown"
    return "unknown"

