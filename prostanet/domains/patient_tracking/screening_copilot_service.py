# -*- coding: utf-8 -*-
"""EPIC 8 — Copilot ligero de screening / detección temprana.

Wrapper delgado sobre ``ScreeningService`` que produce un bundle consumible
por la UI del perfil oficial (profile_compass + patient_profile.html).

Diseño intencional: NO replica la maquinaria de vertical-runtime, QA agents
ni confidence scoring que tienen los copilotos CRPC/mHSPC (1000+ líneas).
Screening es un dominio pre-diagnóstico con decisiones de menor riesgo y
alcance acotado — se mantiene la superficie mínima necesaria para que el
template consuma ``status``, ``summary``, ``evaluation`` y ``recommendation``.

Evidencia:
- NCCN Early Detection v2.2026 (ED-1 a ED-5).
- USPSTF 2018 JAMA 2018;319:1901 (Grade C 55-69, Grade D ≥70).
- Pritchard CC et al. NEJM 2016;375:443 (germline prevalence mCRPC).
- Carter HB et al. J Urol 2013 (AUA baseline PSA).
"""
from __future__ import annotations

from typing import Any

from prostanet.domains.screening.service import ScreeningService


SCREENING_APPLICABLE_STATES = {"screening"}


class ScreeningCopilotService:
    """Copiloto de screening — activable sólo en estado ``screening``."""

    service_id = "screening_copilot"

    def __init__(self) -> None:
        self.service = ScreeningService()

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
        if state not in SCREENING_APPLICABLE_STATES:
            return self._disabled_bundle(state=state, status="not_applicable")

        payload = self._build_payload(patient, latest_assessment)
        try:
            evaluation = self.service.evaluate(payload)
        except Exception as exc:  # pragma: no cover — defensivo
            return self._disabled_bundle(state=state, status="error", error=str(exc))

        nccn = evaluation.get("nccn_primary") or {}
        recommendation_text = str(nccn.get("recommendation") or evaluation.get("recommended_trajectory") or "")
        summary_text = str(
            (evaluation.get("report_sections") or {}).get("summary")
            or evaluation.get("case_summary")
            or "Evaluación de screening sin resumen disponible."
        )
        return {
            "service_id": self.service_id,
            "status": "ok",
            "state": state,
            "summary": summary_text,
            "recommendation": recommendation_text,
            "risk_group": nccn.get("risk_group", ""),
            "category": (evaluation.get("report_sections") or {}).get("category", ""),
            "interval_months": (evaluation.get("report_sections") or {}).get("interval_months"),
            "start_age_recommended": (evaluation.get("report_sections") or {}).get("start_age_recommended"),
            "derive_to_workup": (evaluation.get("report_sections") or {}).get("derive_to_diagnostic_workup", False),
            "workup_reasons": list((evaluation.get("report_sections") or {}).get("workup_reasons") or []),
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
            "screening_age_group": payload_overlay.get("screening_age_group"),
            "ethnicity_group": payload_overlay.get("ethnicity_group") or patient.get("ethnicity_group"),
            "life_expectancy_years": patient.get("life_expectancy_years")
            or payload_overlay.get("life_expectancy_years"),
            "family_history_cluster": payload_overlay.get("family_history_cluster"),
            "germline_known_status": payload_overlay.get("germline_known_status"),
            "psa_baseline_ng_ml": payload_overlay.get("psa_baseline_ng_ml"),
            "psa_baseline_date": payload_overlay.get("psa_baseline_date"),
            "dre_baseline_finding": payload_overlay.get("dre_baseline_finding"),
            "prior_screening_pattern": payload_overlay.get("prior_screening_pattern"),
            "last_psa_ng_ml": payload_overlay.get("last_psa_ng_ml"),
            "last_psa_date": payload_overlay.get("last_psa_date"),
            "informed_decision_ready": payload_overlay.get("informed_decision_ready"),
            "patient_preference_screening": payload_overlay.get("patient_preference_screening"),
        }
        return {key: value for key, value in payload.items() if value not in (None, "")}

    @staticmethod
    def _disabled_bundle(*, state: str, status: str, error: str = "") -> dict[str, Any]:
        return {
            "service_id": "screening_copilot",
            "status": status,
            "state": state,
            "summary": "",
            "recommendation": "",
            "risk_group": "",
            "category": "",
            "interval_months": None,
            "start_age_recommended": None,
            "derive_to_workup": False,
            "workup_reasons": [],
            "evaluation": {},
            "error": error,
            "trigger_event": "",
        }
