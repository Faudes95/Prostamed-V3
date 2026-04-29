from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClinicalAction:
    action_key: str
    title: str
    rationale: str
    urgency: str = "routine"
    specialty: str = "urologic_oncology"
    required_inputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "present", "positive"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def recommend_next_clinical_action(patient: dict[str, Any]) -> list[ClinicalAction]:
    patient = patient or {}
    actions: list[ClinicalAction] = []
    has_biopsy = _truthy(patient.get("biopsy_confirmed") or patient.get("histology_confirmed"))
    psa = _safe_float(patient.get("psa") or patient.get("psa_value") or patient.get("psa_current"))
    if not has_biopsy and psa is not None and psa >= 3:
        actions.append(
            ClinicalAction(
                action_key="complete_diagnostic_workup",
                title="Completar estudio diagnóstico",
                rationale="PSA elevado sin confirmación histológica; requiere repetir PSA, mpMRI y definir biopsia dirigida/sistemática.",
                urgency="priority",
                specialty="diagnostic_urology",
                required_inputs=["repeat_psa", "prostate_mri", "biopsy_plan"],
            )
        )
    if _truthy(patient.get("castration_resistant")) and not _truthy(patient.get("castrate_testosterone_confirmed")):
        actions.append(
            ClinicalAction(
                action_key="confirm_castrate_testosterone",
                title="Confirmar testosterona en rango de castración",
                rationale="No debe liberarse ruta CRPC sin testosterona compatible con castración.",
                urgency="priority",
                specialty="medical_oncology",
                required_inputs=["testosterone_value", "testosterone_date", "adt_context"],
            )
        )
    if _truthy(patient.get("psma_positive")) and _truthy(patient.get("psma_negative_dominant_lesions")):
        actions.append(
            ClinicalAction(
                action_key="resolve_psma_discordance",
                title="Resolver discordancia PSMA",
                rationale="Lesiones dominantes PSMA-negativas bloquean radioligando hasta aclarar heterogeneidad de enfermedad.",
                urgency="priority",
                specialty="nuclear_medicine",
                required_inputs=["psma_negative_dominant_lesions", "fdg_pet_if_needed"],
            )
        )
    return actions


def recommend_flare_protection(
    tumor_burden: str = "",
    cord_compression_risk: bool = False,
    ecog: int | str | None = None,
) -> list[ClinicalAction]:
    actions: list[ClinicalAction] = []
    high_burden = str(tumor_burden or "").strip().lower() in {"high", "alto", "alto volumen"}
    try:
        ecog_value = int(float(ecog)) if ecog not in (None, "") else None
    except (TypeError, ValueError):
        ecog_value = None
    if high_burden or cord_compression_risk:
        actions.append(
            ClinicalAction(
                action_key="flare_protection",
                title="Proteger contra flare androgénico",
                rationale="Alta carga o riesgo neurológico: evitar flare clínicamente relevante al iniciar ADT.",
                urgency="urgent" if cord_compression_risk else "priority",
                specialty="medical_oncology",
                required_inputs=["adt_agent", "antiandrogen_bridge", "neurologic_status"],
            )
        )
    if ecog_value is not None and ecog_value >= 3:
        actions.append(
            ClinicalAction(
                action_key="functional_status_review",
                title="Revisar estado funcional antes de intensificación",
                rationale="ECOG alto puede cambiar intención terapéutica y tolerancia a tratamiento sistémico.",
                urgency="priority",
                specialty="supportive_care",
                required_inputs=["ecog_driver", "frailty_assessment"],
            )
        )
    return actions


def summarize_subspecialty_recommendations(patient: dict[str, Any]) -> dict[str, Any]:
    actions = recommend_next_clinical_action(patient)
    flare_actions = recommend_flare_protection(
        tumor_burden=str(patient.get("volume_disease") or patient.get("tumor_burden") or ""),
        cord_compression_risk=_truthy(patient.get("cord_compression_risk")),
        ecog=patient.get("ecog_score") or patient.get("ecog"),
    )
    combined = actions + flare_actions
    return {
        "actions": [action.to_dict() for action in combined],
        "action_count": len(combined),
        "has_priority_action": any(action.urgency in {"priority", "urgent"} for action in combined),
    }


__all__ = [
    "ClinicalAction",
    "recommend_next_clinical_action",
    "recommend_flare_protection",
    "summarize_subspecialty_recommendations",
]
