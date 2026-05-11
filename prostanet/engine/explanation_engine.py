"""
Explanation Engine — clinical reasoning chains in Spanish.

Transforms agent outputs, model predictions, and guideline evaluations
into human-readable clinical narratives suitable for physician review.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExplanationEngine:
    """Build clinical reasoning narratives from agent outputs."""

    def explain_recommendation(
        self,
        record: dict[str, Any],
        agent_outputs: list[dict[str, Any]],
        confidence: dict[str, Any] | None = None,
        guideline_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Produce a structured clinical explanation.

        Returns dict with:
          narrative: str — full text explanation in Spanish
          sections: list[dict] — structured sections
          data_gaps: list[str] — fields that would improve confidence
        """
        sections: list[dict[str, Any]] = []

        # ── 1: Patient Context ──
        sections.append(self._build_context_section(record))

        # ── 2: Evidence Chain ──
        all_evidence: list[str] = []
        for out in agent_outputs:
            all_evidence.extend(out.get("evidence_chain", []))
        if all_evidence:
            sections.append({
                "title": "Evidencia consultada",
                "items": all_evidence,
            })

        # ── 3: AI Predictions ──
        ai_section = self._build_ai_section(agent_outputs)
        if ai_section:
            sections.append(ai_section)

        # ── 4: Guideline Alignment ──
        if guideline_result:
            sections.append({
                "title": "Alineación con guías",
                "items": [
                    f"NCCN 5.2026: {guideline_result.get('nccn_label', 'No evaluado')}",
                    f"EAU 2026: {'Concordante' if guideline_result.get('eau_concordant') else 'No evaluado'}",
                ],
            })

        # ── 5: Recommendations ──
        rec_section = self._build_recommendation_section(agent_outputs)
        if rec_section:
            sections.append(rec_section)

        # ── 6: Confidence ──
        if confidence:
            sections.append({
                "title": "Confianza",
                "items": [
                    f"Score compuesto: {confidence.get('composite_score', 0)}/100",
                    f"Nivel de acción: {confidence.get('action_label', '')}",
                ],
            })

        # ── 7: Data Gaps ──
        all_gaps: list[str] = []
        for out in agent_outputs:
            all_gaps.extend(out.get("data_gaps", []))
        all_gaps = list(dict.fromkeys(all_gaps))  # deduplicate

        # ── 8: Alerts ──
        all_alerts: list[str] = []
        for out in agent_outputs:
            for alert in out.get("alerts", []):
                if isinstance(alert, dict):
                    all_alerts.append(
                        f"[{alert.get('severity', 'info').upper()}] {alert.get('title', '')}"
                    )
        if all_alerts:
            sections.append({
                "title": "Alertas clínicas",
                "items": all_alerts,
            })

        # Build full narrative
        narrative = self._sections_to_narrative(sections, all_gaps, confidence)

        return {
            "narrative": narrative,
            "sections": sections,
            "data_gaps": all_gaps,
        }

    @staticmethod
    def _build_context_section(record: dict) -> dict[str, Any]:
        baseline = record.get("baseline", {}) or {}
        identity = record.get("identity", {}) or {}
        state = record.get("reconciled_state", "")
        follow_ups = record.get("follow_ups") or []

        items = [f"Estado clínico: {state}"]

        psa = None
        if follow_ups:
            psa = follow_ups[-1].get("psa_current") or follow_ups[-1].get("psa")
        if not psa:
            psa = baseline.get("baseline_psa")
        if psa:
            items.append(f"PSA actual: {psa} ng/mL")

        ecog = baseline.get("ecog_score")
        if ecog is not None:
            items.append(f"ECOG: {ecog}")

        age = baseline.get("age")
        if age:
            items.append(f"Edad: {age} años")

        return {"title": "Contexto del paciente", "items": items}

    @staticmethod
    def _build_ai_section(outputs: list[dict]) -> dict[str, Any] | None:
        items: list[str] = []
        for out in outputs:
            meta = out.get("metadata", {}) or {}

            # State transition prediction
            ai_preds = meta.get("ai_predictions", {})
            if ai_preds.get("state_transition"):
                st = ai_preds["state_transition"]
                items.append(
                    f"Predicción transición: {st.get('predicted_state', '?')} "
                    f"({st.get('predicted_state_probability', 0):.0%}) "
                    f"en {st.get('time_to_transition_months', '?')} meses"
                )

            # PSA kinetics
            psa_k = meta.get("psa_kinetics")
            if psa_k and psa_k.get("psadt_months") is not None:
                items.append(
                    f"PSADT: {psa_k['psadt_months']} meses, "
                    f"velocidad: {psa_k.get('velocity', 0)} ng/mL/año"
                )

            # Treatment ranking
            ranked = meta.get("ranked_treatments")
            if ranked and len(ranked) > 0:
                top = ranked[0]
                items.append(
                    f"Tratamiento top: {top.get('regimen_code', '?')} "
                    f"(score {top.get('composite_score', 0):.0f}/100)"
                )

        if not items:
            return None
        return {"title": "Modelos AI consultados", "items": items}

    @staticmethod
    def _build_recommendation_section(outputs: list[dict]) -> dict[str, Any] | None:
        items: list[str] = []
        for out in outputs:
            for i, rec in enumerate(out.get("recommendations", [])):
                if not isinstance(rec, dict):
                    continue
                action = rec.get("action", "")
                priority = rec.get("priority", "standard")
                evidence = rec.get("evidence_basis", [])
                label = f"{'→ ' if i == 0 else '  '}{action}"
                if priority == "high":
                    label += " [PRIORIDAD ALTA]"
                if evidence:
                    label += f" (evidencia: {', '.join(evidence[:2])})"
                items.append(label)
        if not items:
            return None
        return {"title": "Recomendaciones", "items": items}

    @staticmethod
    def _sections_to_narrative(
        sections: list[dict],
        data_gaps: list[str],
        confidence: dict | None,
    ) -> str:
        lines: list[str] = []
        lines.append("Basado en:")
        for section in sections:
            lines.append(f"\n── {section['title']} ──")
            for item in section.get("items", []):
                lines.append(f"  → {item}")

        if data_gaps:
            lines.append("\nPara mejorar confianza:")
            for gap in data_gaps:
                lines.append(f"  • Solicitar: {gap}")

        if confidence:
            lines.append(
                f"\nConfianza: {confidence.get('composite_score', 0)}/100 — "
                f"{confidence.get('action_label', '')}"
            )

        return "\n".join(lines)
