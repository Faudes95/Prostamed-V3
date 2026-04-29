# -*- coding: utf-8 -*-
"""EPIC 8 — Copilot ligero de terapia focal selectiva.

Wrapper sobre ``FocalTherapyService`` para consumir desde la UI del perfil.
Se activa sólo cuando el estado es ``focal_therapy`` o el paciente está en
``localized_initial`` con perfil compatible (intermedio favorable / bajo
riesgo con lesión unilateral documentada en mpMRI).

Mismo principio de diseño que ``screening_copilot_service.py``: superficie
mínima, delegación al dominio y formato de bundle consumible por el
template sin replicar la maquinaria ML/QA de los copilots CRPC/mHSPC.

Evidencia:
- NCCN PROS-C categoría 2B.
- Stabile A et al. Eur Urol 2019;76:572 (HIFU mid-term).
- Guillaumier S et al. Eur Urol 2018;74:422 (HIFU FFS 5y).
- Ward JF et al. BJU Int 2012;109:1648 (crioablación focal).
- Klotz L et al. J Urol 2021;205:769 (TULSA-Pro).
"""
from __future__ import annotations

from typing import Any

from prostanet.domains.focal_therapy.service import FocalTherapyService


FOCAL_APPLICABLE_STATES = {"focal_therapy", "localized_initial"}


class FocalTherapyCopilotService:
    """Copiloto de terapia focal — activable en focal_therapy y localized_initial."""

    service_id = "focal_therapy_copilot"

    def __init__(self) -> None:
        self.service = FocalTherapyService()

    def evaluate(
        self,
        patient: dict[str, Any],
        *,
        effective_state: str = "",
        latest_assessment: dict[str, Any] | None = None,
        longitudinal_bundle: dict[str, Any] | None = None,
        trigger_event: str = "",
    ) -> dict[str, Any]:
        state = str(
            effective_state
            or (latest_assessment or {}).get("state")
            or (patient.get("prior_history") or {}).get("current_state")
            or ""
        ).strip().lower()
        if state not in FOCAL_APPLICABLE_STATES:
            return self._disabled_bundle(state=state, status="not_applicable")

        payload = self._build_payload(patient, latest_assessment)
        # En localized_initial sólo activar si hay señal explícita de interés
        # focal o lesión unilateral documentada; sino el copilot queda latente.
        if state == "localized_initial" and not self._has_focal_signal(payload):
            return self._disabled_bundle(state=state, status="not_applicable")

        try:
            evaluation = self.service.evaluate(payload)
        except Exception as exc:  # pragma: no cover — defensivo
            return self._disabled_bundle(state=state, status="error", error=str(exc))

        report = evaluation.get("report_sections") or {}
        nccn = evaluation.get("nccn_primary") or {}
        summary_text = str(
            report.get("summary")
            or evaluation.get("case_summary")
            or "Evaluación de candidatura a terapia focal sin resumen disponible."
        )
        recommendation_text = str(
            nccn.get("recommendation") or evaluation.get("recommended_trajectory") or ""
        )
        return {
            "service_id": self.service_id,
            "status": "ok",
            "state": state,
            "summary": summary_text,
            "recommendation": recommendation_text,
            "eligible": bool(report.get("eligibility")),
            "risk_group": nccn.get("risk_group", ""),
            "modality_recommended": report.get("modality_recommended", ""),
            "cautions": list(report.get("cautions") or []),
            "contraindications": list(evaluation.get("contraindications") or []),
            "durations_and_conditions": list(evaluation.get("durations_and_conditions") or []),
            "evaluation": evaluation,
            "trigger_event": trigger_event or "",
        }

    def _build_payload(
        self,
        patient: dict[str, Any],
        latest_assessment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source_assessment = latest_assessment or patient.get("latest_assessment") or {}
        payload_overlay = dict(source_assessment.get("payload") or {})
        payload = {
            "age": patient.get("age") or payload_overlay.get("age"),
            "life_expectancy_years": patient.get("life_expectancy_years")
            or payload_overlay.get("life_expectancy_years"),
            "psa": payload_overlay.get("psa") or patient.get("psa"),
            "gleason_primary": payload_overlay.get("gleason_primary"),
            "gleason_secondary": payload_overlay.get("gleason_secondary"),
            "isup_grade": payload_overlay.get("isup_grade"),
            "nccn_risk_group": payload_overlay.get("nccn_risk_group"),
            "lesion_unilateral": payload_overlay.get("lesion_unilateral"),
            "lesion_maxdim_mm": payload_overlay.get("lesion_maxdim_mm"),
            "mri_psa_density": payload_overlay.get("mri_psa_density"),
            "prostate_volume_ml": payload_overlay.get("prostate_volume_ml"),
            "lesion_location_apical": payload_overlay.get("lesion_location_apical"),
            "urinary_obstructive_symptoms": payload_overlay.get("urinary_obstructive_symptoms"),
            "focal_modality_preferred": payload_overlay.get("focal_modality_preferred"),
            "patient_priority_profile": payload_overlay.get("patient_priority_profile"),
        }
        return {key: value for key, value in payload.items() if value not in (None, "")}

    @staticmethod
    def _has_focal_signal(payload: dict[str, Any]) -> bool:
        """En localized_initial, sólo activar si el paciente muestra señal focal."""
        lesion_text = str(payload.get("lesion_unilateral") or "").lower()
        if "unilateral" in lesion_text:
            return True
        if payload.get("focal_modality_preferred"):
            preferred = str(payload.get("focal_modality_preferred") or "").lower()
            if preferred and preferred not in {"no definida", "no_definida"}:
                return True
        profile = str(payload.get("focal_therapy_candidate_profile") or "").lower()
        if "candidato" in profile:
            return True
        return False

    @staticmethod
    def _disabled_bundle(*, state: str, status: str, error: str = "") -> dict[str, Any]:
        return {
            "service_id": "focal_therapy_copilot",
            "status": status,
            "state": state,
            "summary": "",
            "recommendation": "",
            "eligible": False,
            "risk_group": "",
            "modality_recommended": "",
            "cautions": [],
            "contraindications": [],
            "durations_and_conditions": [],
            "evaluation": {},
            "error": error,
            "trigger_event": "",
        }
