# -*- coding: utf-8 -*-
"""
Herramientas de decisión compartida para cáncer de próstata.

Genera:
  - Tablas de riesgo-beneficio por tratamiento
  - Resúmenes en lenguaje para paciente (español)
  - Comparaciones pictográficas ("De cada 100 pacientes similares...")
  - Contexto de efectos secundarios principales

Referencia:
  NCCN Patient Guidelines 2026
  ICHOM Standard Set for Localized Prostate Cancer
  Stacey D et al. Cochrane 2017 (Decision aids)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Datos de outcomes por tratamiento ──────────────────────────────────────

TREATMENT_OUTCOMES: dict[str, dict[str, Any]] = {
    "active_surveillance": {
        "name_patient": "Vigilancia activa",
        "description_patient": "Se monitorea el cáncer de cerca con análisis de sangre, resonancias magnéticas y biopsias periódicas. No se realiza tratamiento inmediato. Si el cáncer muestra signos de crecer, se puede pasar a tratamiento activo.",
        "benefits": [
            "Evita efectos secundarios del tratamiento mientras no sea necesario",
            "Preserva la función urinaria y sexual",
            "Calidad de vida mantenida",
            "Se puede pasar a tratamiento activo en cualquier momento",
        ],
        "risks": [
            "Ansiedad por vivir con cáncer sin tratamiento",
            "Riesgo pequeño de que el cáncer avance entre controles",
            "Necesidad de biopsias y resonancias periódicas",
        ],
        "side_effects_100": {
            "incontinencia_urinaria": 0,
            "disfuncion_erectil": 0,
            "problemas_intestinales": 0,
            "ansiedad": 25,
        },
        "cancer_control_5y": {"low": "98-99%", "intermediate_favorable": "95-97%"},
    },
    "radical_prostatectomy": {
        "name_patient": "Cirugía (prostatectomía radical)",
        "description_patient": "Se extirpa la próstata completa junto con las vesículas seminales. Es una cirugía mayor que se puede hacer con robot o de forma abierta. El objetivo es eliminar todo el cáncer.",
        "benefits": [
            "Elimina físicamente el tumor",
            "Permite análisis patológico completo del tumor",
            "PSA debe bajar a indetectable después de la cirugía",
            "Facilita el seguimiento con PSA",
        ],
        "risks": [
            "Riesgo quirúrgico (sangrado, infección, trombosis)",
            "Periodo de recuperación de 4-6 semanas",
            "Posible necesidad de tratamiento adicional si márgenes positivos",
        ],
        "side_effects_100": {
            "incontinencia_urinaria_temporal": 40,
            "incontinencia_urinaria_permanente": 5,
            "disfuncion_erectil": 50,
            "estenosis_uretral": 5,
        },
        "cancer_control_5y": {"low": "99%", "intermediate": "95-97%", "high": "85-90%"},
    },
    "radiation_therapy": {
        "name_patient": "Radioterapia",
        "description_patient": "Se usa radiación dirigida para destruir las células cancerosas. Puede ser externa (IMRT/SBRT, 4-8 semanas) o con semillas radioactivas implantadas (braquiterapia). Frecuentemente se combina con terapia hormonal.",
        "benefits": [
            "No requiere cirugía",
            "Tratamiento ambulatorio",
            "Control del cáncer comparable a la cirugía en muchos casos",
            "Preserva la próstata anatómicamente",
        ],
        "risks": [
            "Efectos urinarios e intestinales que pueden aparecer meses después",
            "Puede requerir terapia hormonal complementaria (6 meses a 2-3 años)",
            "Dificulta el rescate quirúrgico si hay recurrencia",
        ],
        "side_effects_100": {
            "problemas_urinarios_irritativos": 30,
            "disfuncion_erectil": 40,
            "problemas_intestinales": 15,
            "fatiga": 25,
        },
        "cancer_control_5y": {"low": "98-99%", "intermediate": "90-95%", "high": "80-85%"},
    },
    "adt_monotherapy": {
        "name_patient": "Terapia hormonal (ADT)",
        "description_patient": "Se usan medicamentos para reducir la testosterona, que alimenta al cáncer de próstata. Es un tratamiento continuo con inyecciones mensuales o trimestrales.",
        "benefits": [
            "Reduce el PSA y el tamaño del tumor en la mayoría de pacientes",
            "Tratamiento sistémico (actúa en todo el cuerpo)",
            "Puede combinarse con otros tratamientos",
        ],
        "risks": [
            "Bochornos y sudoración",
            "Pérdida de deseo sexual y disfunción eréctil",
            "Aumento de peso y pérdida muscular",
            "Riesgo de osteoporosis y fracturas",
            "Aumento del riesgo cardiovascular y diabetes",
            "Fatiga y cambios de humor",
        ],
        "side_effects_100": {
            "bochornos": 75,
            "disfuncion_erectil": 90,
            "aumento_peso": 50,
            "fatiga": 60,
            "osteoporosis_2_años": 15,
        },
    },
    "adt_plus_arpi": {
        "name_patient": "Terapia hormonal intensificada (ADT + ARPI)",
        "description_patient": "Combina la terapia hormonal estándar con un medicamento adicional (abiraterona, enzalutamida, apalutamida o darolutamida) que bloquea más completamente la señal de testosterona.",
        "benefits": [
            "Mayor control del cáncer que ADT sola",
            "Demostrado prolongar la vida en estudios grandes",
            "Retrasa la progresión de la enfermedad",
        ],
        "risks": [
            "Los efectos secundarios de ADT más posibles efectos adicionales del ARPI",
            "Hipertensión y retención de líquidos (abiraterona)",
            "Fatiga aumentada",
            "Riesgo de caídas (enzalutamida)",
            "Costo del tratamiento",
        ],
    },
    "docetaxel": {
        "name_patient": "Quimioterapia (docetaxel)",
        "description_patient": "Medicamento de quimioterapia que se administra por vía intravenosa cada 3 semanas, generalmente por 6 ciclos (18 semanas). Se usa cuando el cáncer es avanzado o resistente a la terapia hormonal.",
        "benefits": [
            "Demostrado prolongar la vida en enfermedad avanzada",
            "Puede combinarse con terapia hormonal",
            "Tratamiento de duración definida (6 ciclos)",
        ],
        "risks": [
            "Riesgo de infección por baja de defensas",
            "Caída de cabello temporal",
            "Náusea y vómito (controlable con medicamentos)",
            "Neuropatía en manos y pies",
            "Fatiga significativa",
        ],
        "side_effects_100": {
            "neutropenia": 30,
            "fatiga_severa": 35,
            "neuropatia": 20,
            "nausea": 40,
            "alopecia": 60,
        },
    },
}


class DecisionAidService:
    """Servicio de herramientas de decisión compartida."""

    @classmethod
    def generate_comparison(
        cls,
        options: list[str],
        risk_group: str = "",
        patient_priorities: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Genera una comparación de opciones de tratamiento para decisión compartida.

        Args:
            options: Lista de claves de tratamiento (e.g., ["active_surveillance", "radical_prostatectomy"])
            risk_group: Grupo de riesgo del paciente
            patient_priorities: Prioridades del paciente (e.g., ["función sexual", "curación"])
        """
        comparisons: list[dict[str, Any]] = []
        for opt in options:
            data = TREATMENT_OUTCOMES.get(opt)
            if not data:
                continue
            entry: dict[str, Any] = {
                "treatment_key": opt,
                "name": data["name_patient"],
                "description": data["description_patient"],
                "benefits": data["benefits"],
                "risks": data["risks"],
            }
            if "side_effects_100" in data:
                entry["side_effects_pictogram"] = cls._pictogram(data["side_effects_100"])
            if "cancer_control_5y" in data and risk_group:
                control = data["cancer_control_5y"].get(risk_group) or data["cancer_control_5y"].get("intermediate", "")
                entry["cancer_control_5y"] = control
            comparisons.append(entry)

        result: dict[str, Any] = {
            "comparison_type": "treatment_options",
            "risk_group": risk_group,
            "options": comparisons,
            "shared_decision_note": (
                "Esta información es para ayudarle a usted y su médico a tomar una decisión juntos. "
                "Cada paciente es diferente y los resultados pueden variar. "
                "Hable con su equipo médico sobre cuál opción se ajusta mejor a su situación y prioridades."
            ),
        }

        if patient_priorities:
            result["patient_priorities"] = patient_priorities
            result["priority_alignment"] = cls._align_priorities(options, patient_priorities)

        return result

    @classmethod
    def generate_patient_summary(
        cls,
        treatment_key: str,
        patient_name: str = "usted",
    ) -> dict[str, Any]:
        """
        Genera un resumen en lenguaje accesible para el paciente.
        """
        data = TREATMENT_OUTCOMES.get(treatment_key)
        if not data:
            return {"error": f"Tratamiento no encontrado: {treatment_key}"}

        summary_text = (
            f"**{data['name_patient']}**\n\n"
            f"{data['description_patient']}\n\n"
            f"**Lo que puede esperar:**\n"
        )
        for benefit in data["benefits"]:
            summary_text += f"- {benefit}\n"

        summary_text += f"\n**Riesgos a considerar:**\n"
        for risk in data["risks"]:
            summary_text += f"- {risk}\n"

        if "side_effects_100" in data:
            summary_text += f"\n**De cada 100 pacientes similares a {patient_name}:**\n"
            for effect, count in data["side_effects_100"].items():
                label = effect.replace("_", " ").capitalize()
                summary_text += f"- Aproximadamente {count} podrían presentar {label.lower()}\n"

        return {
            "treatment": data["name_patient"],
            "summary_text": summary_text,
            "language": "es",
            "reading_level": "paciente",
        }

    @staticmethod
    def _pictogram(side_effects: dict[str, int]) -> list[dict[str, Any]]:
        """Genera datos para visualización tipo pictograma."""
        result: list[dict[str, Any]] = []
        for effect, count in side_effects.items():
            label = effect.replace("_", " ").capitalize()
            result.append({
                "effect": label,
                "affected_per_100": count,
                "not_affected_per_100": 100 - count,
                "description": f"De cada 100 pacientes, aproximadamente {count} podrían presentar {label.lower()}",
            })
        return result

    @classmethod
    def build_tradeoff_visualization(
        cls,
        patient: dict[str, Any],
        elicitation_answers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """EPIC 7 — Construye visualización SDM integral (tradeoff + trial + elicitación).

        Orquesta los tres nuevos motores:
        - ``tradeoff_engine.build_tradeoff_matrix`` → outcomes × prioridades.
        - ``trial_matching_engine.build_trial_matching_bundle`` → ensayos.
        - ``sdm_preference_elicitation.score_elicitation`` → elicitación Likert.

        Si la elicitación aporta prioridades, se fusionan con las explícitas
        del paciente antes de calcular la matriz (sin mutar el paciente).

        Returns:
            dict con keys: ``tradeoff_matrix``, ``trial_matching_bundle``,
            ``elicitation_result``, ``elicitation_form``.
        """

        from prostanet.domains.patient_tracking.tradeoff_engine import build_tradeoff_matrix
        from prostanet.domains.research_intelligence.trial_matching_engine import (
            build_trial_matching_bundle,
        )
        from prostanet.domains.reporting.sdm_preference_elicitation import (
            build_elicitation_form,
            merge_elicited_with_free_text,
            score_elicitation,
        )

        elicitation_result = score_elicitation(elicitation_answers or {})

        patient_for_matrix = dict(patient or {})
        if elicitation_result.ranked_priorities:
            raw = patient_for_matrix.get("patient_priority_profile") or patient_for_matrix.get("priority_profile") or ""
            if isinstance(raw, list):
                tokens = [str(x).strip() for x in raw if str(x).strip()]
            else:
                tokens = [tok.strip() for tok in str(raw).replace(";", ",").split(",") if tok.strip()]
            merged = merge_elicited_with_free_text(elicitation_result, tokens)
            patient_for_matrix["patient_priority_profile"] = ",".join(merged)

        tradeoff_matrix = build_tradeoff_matrix(patient_for_matrix)
        trial_bundle = build_trial_matching_bundle(patient_for_matrix)

        return {
            "tradeoff_matrix": tradeoff_matrix.to_dict(),
            "trial_matching_bundle": trial_bundle,
            "elicitation_result": elicitation_result.to_dict(),
            "elicitation_form": build_elicitation_form(),
            "source_framework": "Ottawa Decision Support Framework + NCCN PROS-A v5.2026",
        }

    @staticmethod
    def _align_priorities(options: list[str], priorities: list[str]) -> list[dict[str, str]]:
        """Alinea opciones de tratamiento con prioridades del paciente."""
        priority_map: dict[str, dict[str, str]] = {
            "función sexual": {
                "active_surveillance": "Mejor opción — preserva la función sexual completamente",
                "radical_prostatectomy": "Riesgo significativo de disfunción eréctil, mayor con cirugía no nerve-sparing",
                "radiation_therapy": "Riesgo moderado, típicamente aparece gradualmente",
            },
            "curación": {
                "radical_prostatectomy": "Permite análisis patológico completo y seguimiento con PSA claro",
                "radiation_therapy": "Control comparable en muchos escenarios",
                "active_surveillance": "No trata activamente; monitoreo cercano con opción de tratamiento futuro",
            },
            "calidad de vida": {
                "active_surveillance": "Preserva calidad de vida actual completamente",
                "radiation_therapy": "Tratamiento ambulatorio con menor impacto inicial",
                "radical_prostatectomy": "Periodo de recuperación pero resultados a largo plazo frecuentemente buenos",
            },
            "continencia urinaria": {
                "active_surveillance": "Sin riesgo de incontinencia",
                "radiation_therapy": "Bajo riesgo de incontinencia",
                "radical_prostatectomy": "Riesgo de incontinencia temporal (~40%) y permanente (~5%)",
            },
        }

        alignments: list[dict[str, str]] = []
        for priority in priorities:
            p_lower = priority.lower()
            mapping = priority_map.get(p_lower, {})
            for opt in options:
                note = mapping.get(opt, "Consulte con su médico sobre este aspecto")
                alignments.append({
                    "priority": priority,
                    "treatment": opt,
                    "alignment_note": note,
                })

        return alignments
