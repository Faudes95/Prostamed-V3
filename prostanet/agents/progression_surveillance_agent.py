"""
Progression Surveillance Agent (PSA) — "El Vigilante".

Continuously monitors for disease progression signals using PSA kinetics,
lab trend analysis, anomaly detection, and state transition prediction.

Triggered on: lab_value_updated, imaging_completed
"""

from __future__ import annotations

import logging
from typing import Any

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import (
    AgentInput,
    AgentOutput,
    AgentAlert,
)

logger = logging.getLogger(__name__)


class ProgressionSurveillanceAgent(AgentBase):
    """
    Continuous monitoring agent that watches for progression signals —
    the physician who reviews labs at 3am.
    """

    agent_id = "progression_surveillance_agent"
    agent_role = "Vigilancia continua de progresión: cinética de PSA, anomalías de laboratorio, predicción de transición"
    trigger_events = [
        "lab_value_updated",
        "imaging_completed",
        "visit_recorded",
    ]

    def __init__(self, model_registry: Any | None = None) -> None:
        self.model_registry = model_registry

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        record = agent_input.record
        state = record.get("reconciled_state", "")
        evidence_chain: list[str] = []
        alerts: list[AgentAlert] = []

        # ── 1: PSA Kinetics ──
        psa_kinetics = self._compute_psa_kinetics(record)
        if psa_kinetics:
            evidence_chain.append(
                f"Cinética PSA: PSADT={psa_kinetics.get('psadt_months', 'N/A')}m, "
                f"velocidad={psa_kinetics.get('velocity', 'N/A')} ng/mL/año"
            )

            psadt = psa_kinetics.get("psadt_months")
            if psadt is not None and psadt < 3:
                alerts.append(AgentAlert(
                    alert_type="psa_kinetics",
                    severity="critical",
                    title="PSADT < 3 meses — Progresión rápida",
                    message=f"PSADT = {psadt:.1f} meses. Alto riesgo de progresión inminente.",
                    category="decision_blocker",
                    recommended_action="Re-estadificación urgente + discusión de siguiente línea",
                    evidence_basis=["NCCN 2026 M0 CRPC", "Smith et al. JCO 2005"],
                ))
            elif psadt is not None and psadt < 10:
                alerts.append(AgentAlert(
                    alert_type="psa_kinetics",
                    severity="warning",
                    title=f"PSADT {psadt:.1f} meses — Alto riesgo",
                    message=f"PSADT entre 3-10 meses sugiere progresión acelerada.",
                    category="safety",
                    recommended_action="Considerar intensificación terapéutica",
                    evidence_basis=["SPARTAN", "PROSPER", "ARAMIS"],
                ))

            velocity = psa_kinetics.get("velocity")
            if velocity is not None and velocity > 0.75:
                alerts.append(AgentAlert(
                    alert_type="psa_kinetics",
                    severity="warning",
                    title=f"Velocidad PSA {velocity:.2f} ng/mL/año",
                    message="Velocidad de PSA >0.75 ng/mL/año indica riesgo elevado.",
                    category="safety",
                    evidence_basis=["D'Amico et al. NEJM 2004"],
                ))

        # ── 2: BCR Detection ──
        bcr_alert = self._check_bcr_criteria(record, state)
        if bcr_alert:
            alerts.append(bcr_alert)
            evidence_chain.append(f"BCR detectada: {bcr_alert.title}")

        # ── 3: Lab Anomaly Detection (AI) ──
        if self.model_registry:
            try:
                anomaly_model = self.model_registry.get("anomaly_detector")
                if anomaly_model:
                    anomaly_result = anomaly_model.predict(record)
                    if anomaly_result.values.get("is_anomalous"):
                        for anomaly in anomaly_result.values.get("detected_anomalies", []):
                            alerts.append(AgentAlert(
                                alert_type="ai_anomaly",
                                severity=anomaly.get("severity", "warning"),
                                title=f"Anomalía detectada: {anomaly['feature']}",
                                message=f"Patrón inesperado en {anomaly['feature']} (z-score: {anomaly['z_score']:.1f})",
                                category="safety",
                                recommended_action="Evaluar interferencia analítica o progresión oculta",
                            ))
                        evidence_chain.append(
                            f"Anomalías AI detectadas: {len(anomaly_result.values.get('detected_anomalies', []))}"
                        )
            except Exception as exc:
                logger.debug("Anomaly detection failed: %s", exc)

        # ── 4: State Transition Prediction (AI) ──
        if self.model_registry:
            try:
                state_model = self.model_registry.get("state_transition")
                if state_model:
                    pred = state_model.predict(record)
                    prob = pred.values.get("predicted_state_probability", 0)
                    predicted = pred.values.get("predicted_state", "")
                    if prob > 0.6 and predicted != state:
                        evidence_chain.append(
                            f"Predicción transición: {predicted} ({prob:.0%})"
                        )
                        if prob > 0.75:
                            alerts.append(AgentAlert(
                                alert_type="ai_state_prediction",
                                severity="warning",
                                title=f"Alta probabilidad de transición a {predicted}",
                                message=f"Modelo predice {prob:.0%} de transición en {pred.values.get('time_to_transition_months', '?')}m",
                                category="ai_prediction",
                                recommended_action="Recomendar re-estadificación",
                                probability=prob,
                            ))
            except Exception as exc:
                logger.debug("State prediction failed: %s", exc)

        # ── 5: Lab threshold alerts ──
        lab_alerts = self._check_lab_thresholds(record)
        alerts.extend(lab_alerts)

        confidence = 70.0 + (10.0 if psa_kinetics else 0) + (10.0 if self.model_registry else 0)

        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
            confidence_score=min(100.0, confidence),
            evidence_chain=evidence_chain,
            alerts=alerts,
            metadata={"psa_kinetics": psa_kinetics},
        )

    @staticmethod
    def _compute_psa_kinetics(record: dict) -> dict[str, Any] | None:
        """Extract PSA doubling time and velocity from follow-up data."""
        import math
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        psa_points: list[tuple[str, float]] = []

        for visit in follow_ups:
            psa = visit.get("psa_current") or visit.get("psa")
            date = visit.get("visit_date")
            if psa and date:
                try:
                    psa_points.append((str(date), float(psa)))
                except (TypeError, ValueError):
                    pass

        if len(psa_points) < 2:
            return None

        # Sort by date
        psa_points.sort(key=lambda x: x[0])
        first_date, first_psa = psa_points[0]
        last_date, last_psa = psa_points[-1]

        if first_psa <= 0 or last_psa <= 0:
            return None

        # Simple PSADT calculation (log2 method)
        try:
            from datetime import datetime
            d1 = datetime.strptime(first_date[:10], "%Y-%m-%d")
            d2 = datetime.strptime(last_date[:10], "%Y-%m-%d")
            months = max(0.1, (d2 - d1).days / 30.44)
        except (ValueError, TypeError):
            return None

        if last_psa <= first_psa:
            return {"psadt_months": None, "velocity": 0, "trend": "stable_or_declining"}

        psadt = months * math.log(2) / math.log(last_psa / first_psa)
        velocity = (last_psa - first_psa) / (months / 12) if months > 0 else 0

        return {
            "psadt_months": round(psadt, 1),
            "velocity": round(velocity, 2),
            "first_psa": first_psa,
            "last_psa": last_psa,
            "months_interval": round(months, 1),
            "trend": "rising",
        }

    @staticmethod
    def _check_bcr_criteria(record: dict, state: str) -> AgentAlert | None:
        """Check for biochemical recurrence criteria."""
        baseline = record.get("baseline", {}) or {}
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []

        if state == "post_prostatectomy" and follow_ups:
            last_psa = follow_ups[-1].get("psa_current") or follow_ups[-1].get("psa")
            if last_psa:
                try:
                    if float(last_psa) >= 0.2:
                        return AgentAlert(
                            alert_type="bcr_detection",
                            severity="critical",
                            title=f"BCR post-RP detectada — PSA {float(last_psa):.2f}",
                            message="PSA ≥ 0.2 ng/mL post-prostatectomía confirma recurrencia bioquímica.",
                            category="decision_blocker",
                            recommended_action="PSMA-PET + evaluación de radioterapia de rescate",
                            evidence_basis=["AUA/EAU BCR criteria"],
                        )
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _check_lab_thresholds(record: dict) -> list[AgentAlert]:
        """Check laboratory values against safety thresholds."""
        alerts: list[AgentAlert] = []
        follow_ups = record.get("follow_ups") or record.get("follow_up_visits") or []
        if not follow_ups:
            return alerts

        last = follow_ups[-1]

        def _f(val: Any) -> float | None:
            if val is None or val == "":
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        hgb = _f(last.get("hemoglobin"))
        if hgb is not None and hgb < 8:
            alerts.append(AgentAlert(
                alert_type="laboratory",
                severity="critical",
                title=f"Hemoglobina crítica: {hgb:.1f} g/dL",
                message="Hemoglobina <8 g/dL requiere evaluación urgente y posible transfusión.",
                category="safety",
                evidence_basis=["NCCN Supportive Care"],
            ))
        elif hgb is not None and hgb < 10:
            alerts.append(AgentAlert(
                alert_type="laboratory",
                severity="warning",
                title=f"Anemia: Hgb {hgb:.1f} g/dL",
                message="Hemoglobina <10 g/dL. Evaluar causa y considerar ajuste de tratamiento.",
                category="safety",
            ))

        testosterone = _f(last.get("testosterone"))
        baseline = record.get("baseline", {}) or {}
        on_adt = baseline.get("current_adt_context") not in (None, "", "none")
        if testosterone is not None and testosterone > 50 and on_adt:
            alerts.append(AgentAlert(
                alert_type="laboratory",
                severity="warning",
                title=f"Testosterona no castrada: {testosterone:.0f} ng/dL",
                message="Testosterona >50 ng/dL en paciente bajo ADT. Verificar adherencia.",
                category="safety",
                recommended_action="Confirmar nivel de castración, evaluar cambio de ADT",
                evidence_basis=["NCCN 2026", "EAU 2026"],
            ))

        return alerts
