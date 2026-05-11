# -*- coding: utf-8 -*-
"""
Motor de alertas clínicas para seguimiento activo de Ca. próstata.

Evalúa automáticamente umbrales de seguridad en cinética de PSA,
laboratorios, ECOG y milestones de tratamiento.
Genera alertas que se persisten en smart_alerts.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

from prostanet.domains.patient_tracking.laboratory_intelligence.alert_engine import (
    build_laboratory_alerts,
)
from prostanet.shared.phoenix import evaluate_phoenix

logger = logging.getLogger(__name__)


def _detect_post_rt_context(patient: dict[str, Any]) -> bool:
    """Detecta si el paciente tiene contexto post-RT para evaluar Phoenix.

    Reconoce tokens ES/EN en los campos que indican radioterapia previa como
    tratamiento primario (EBRT, braquiterapia, IMRT, protones, radioterapia).
    """
    management_track = str(patient.get("management_track") or "").strip().lower()
    if management_track in {"post_rt", "post_radiotherapy", "rt_primary"}:
        return True
    prior_radiation = patient.get("prior_radiation") or patient.get("rt_primary_received")
    if str(prior_radiation or "").strip().lower() in {"1", "true", "yes", "si", "sí"}:
        return True
    treatment_tokens = " ".join([
        str(patient.get("current_treatment") or ""),
        str(patient.get("treatment_received") or ""),
        str(patient.get("primary_treatment") or ""),
        str(patient.get("rt_modality") or ""),
    ]).lower()
    rt_tokens = (
        "ebrt", "braqui", "brachytherapy", "imrt", "sbrt", "proton",
        "radioter", "radiotherapy", "rt primary", "rt_primary",
    )
    return any(token in treatment_tokens for token in rt_tokens)


@dataclass
class ClinicalAlert:
    """Alerta clínica generada automáticamente."""
    patient_id: int
    alert_type: str
    severity: str  # "info" | "warning" | "critical"
    category: str  # "psa_kinetics" | "laboratory" | "ecog" | "treatment_milestone" | "safety"
    title: str
    message: str
    recommended_action: str = ""
    guideline_reference: str = ""
    triggering_value: str = ""
    threshold: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClinicalAlertEngine:
    """
    Evalúa condiciones clínicas y genera alertas.
    Diseñado para ejecutarse después de cada visita de seguimiento o evaluación clínica.
    """

    @staticmethod
    def evaluate_psa_kinetics(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa cinética de PSA y genera alertas según umbrales clínicos.

        Umbrales:
            - PSADT <3 meses → CRÍTICO (progresión rápida)
            - PSADT 3-10 meses → WARNING (alto riesgo nmCRPC/progresión)
            - Velocidad PSA >0.75 ng/mL/año en contexto diagnóstico → WARNING
            - PSA >0.2 ng/mL post-RP → WARNING (posible BCR)
            - PSA nadir + 2 ng/mL post-RT → WARNING (criterio Phoenix BCR)
        """
        alerts: list[ClinicalAlert] = []

        psadt = patient.get("psadt_months") or patient.get("psa_doubling_time")
        if psadt is not None:
            try:
                psadt = float(psadt)
                if psadt > 0 and psadt < 3:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psadt_critical",
                        severity="critical",
                        category="psa_kinetics",
                        title="PSADT < 3 meses — Progresión rápida",
                        message=f"Tiempo de duplicación de PSA: {psadt:.1f} meses. Indicativo de enfermedad agresiva con alto riesgo de progresión a metástasis.",
                        recommended_action="Considerar intensificación terapéutica urgente. Re-estadificación con PSMA-PET si disponible.",
                        guideline_reference="NCCN 5.2026: nmCRPC alto riesgo / EAU 2026",
                        triggering_value=f"{psadt:.1f} meses",
                        threshold="< 3 meses",
                    ))
                elif psadt > 0 and psadt <= 10:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psadt_warning",
                        severity="warning",
                        category="psa_kinetics",
                        title="PSADT ≤ 10 meses — Alto riesgo",
                        message=f"Tiempo de duplicación de PSA: {psadt:.1f} meses. Criterio de alto riesgo para nmCRPC.",
                        recommended_action="Considerar ARPI (apalutamida, enzalutamida, darolutamida) si en contexto CRPC. Verificar castración.",
                        guideline_reference="NCCN 5.2026: SPARTAN, PROSPER, ARAMIS",
                        triggering_value=f"{psadt:.1f} meses",
                        threshold="≤ 10 meses",
                    ))
            except (ValueError, TypeError):
                pass

        psa_velocity = patient.get("psa_velocity")
        if psa_velocity is not None:
            try:
                vel = float(psa_velocity)
                if vel > 0.75:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psa_velocity_elevated",
                        severity="warning",
                        category="psa_kinetics",
                        title="Velocidad de PSA > 0.75 ng/mL/año",
                        message=f"Velocidad de PSA: {vel:.2f} ng/mL/año. Valor elevado que sugiere enfermedad clínicamente significativa.",
                        recommended_action="Considerar biopsia si no diagnosticado. En post-tratamiento, evaluar recurrencia.",
                        guideline_reference="Carter HB et al. JAMA 1992 / NCCN 5.2026",
                        triggering_value=f"{vel:.2f} ng/mL/año",
                        threshold="> 0.75 ng/mL/año",
                    ))
            except (ValueError, TypeError):
                pass

        # PSA post-RP detectable
        psa_current = patient.get("psa") or patient.get("psa_current")
        management_track = patient.get("management_track", "")
        if psa_current is not None and management_track == "post_rp":
            try:
                psa_val = float(psa_current)
                if psa_val >= 0.2:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="bcr_post_rp",
                        severity="warning",
                        category="psa_kinetics",
                        title="PSA ≥ 0.2 ng/mL post-prostatectomía",
                        message=f"PSA actual: {psa_val:.2f} ng/mL. Cumple criterio de recurrencia bioquímica post-RP.",
                        recommended_action="Confirmar con segunda determinación. Considerar PSMA-PET para re-estadificación. Evaluar RT de rescate temprana.",
                        guideline_reference="NCCN 5.2026 / EAU 2026: Criterio BCR post-RP",
                        triggering_value=f"{psa_val:.2f} ng/mL",
                        threshold="≥ 0.2 ng/mL",
                    ))
            except (ValueError, TypeError):
                pass

        # EPIC 1 FIX-ALERT-1: Phoenix post-RT (PSA ≥ nadir + 2 ng/mL).
        # Roach IJROBP 2006 / NCCN PROS-10 / EAU 2026 §6.3.2 (category 1).
        # Se evalúa con el helper canónico evaluate_phoenix() para unificar
        # el umbral y el tratamiento de nadir no evaluable.
        if _detect_post_rt_context(patient):
            phoenix_eval = evaluate_phoenix(patient)
            if phoenix_eval.assessable and phoenix_eval.threshold_reached:
                nadir_txt = (
                    f"{phoenix_eval.nadir:.2f}" if phoenix_eval.nadir is not None else "?"
                )
                current_txt = (
                    f"{phoenix_eval.current:.2f}" if phoenix_eval.current is not None else "?"
                )
                threshold_txt = (
                    f"{phoenix_eval.threshold:.2f}"
                    if phoenix_eval.threshold is not None
                    else "?"
                )
                delta_txt = (
                    f"{phoenix_eval.delta:.2f}"
                    if phoenix_eval.delta is not None
                    else "?"
                )
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="phoenix_bcr_post_rt",
                    severity="warning",
                    category="psa_kinetics",
                    title="Phoenix cumplido — recurrencia bioquímica post-RT",
                    message=(
                        f"PSA actual {current_txt} ng/mL ≥ nadir {nadir_txt} + 2.0 = "
                        f"{threshold_txt} ng/mL (delta {delta_txt}). "
                        "Criterio Phoenix RTOG-ASTRO 2006 cumplido."
                    ),
                    recommended_action=(
                        "Confirmar con repetición de PSA. Evaluar re-estadificación "
                        "con PSMA-PET, descartar recurrencia local con mpMRI y "
                        "valorar rescate local (salvage RP o braquiterapia) vs. "
                        "ADT ± ARPI según contexto."
                    ),
                    guideline_reference=(
                        "Roach M IJROBP 2006;65:965 / NCCN PROS-10 v5.2026 cat 1 / "
                        "EAU 2026 §6.3.2"
                    ),
                    triggering_value=f"{current_txt} ng/mL (Δ={delta_txt})",
                    threshold=f"nadir + 2.0 = {threshold_txt} ng/mL",
                ))
            elif _detect_post_rt_context(patient) and not phoenix_eval.assessable:
                # Post-RT con nadir no documentado: info suave para recuperar dato.
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="phoenix_unassessable",
                    severity="info",
                    category="psa_kinetics",
                    title="Phoenix no evaluable — nadir post-RT no documentado",
                    message=(
                        "PSA nadir post-RT ausente: no se puede aplicar el criterio "
                        "Phoenix (nadir + 2.0 ng/mL). Documentar el nadir histórico "
                        "para habilitar vigilancia BCR estandarizada."
                    ),
                    recommended_action=(
                        "Recuperar valor mínimo de PSA post-RT en historia (≥6 meses) "
                        "y registrarlo en psa_nadir."
                    ),
                    guideline_reference="Roach IJROBP 2006 / NCCN PROS-10 v5.2026",
                    triggering_value="psa_nadir: ausente",
                    threshold="dato requerido",
                ))

        return alerts

    @staticmethod
    def evaluate_lab_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa valores de laboratorio contra umbrales de seguridad.

        Umbrales:
            - Hemoglobina <10 g/dL bajo ADT → WARNING
            - AST/ALT >3x ULN bajo abiraterona → CRITICAL
            - ANC <1500 bajo docetaxel → CRITICAL
            - Testosterona >50 ng/dL bajo ADT → WARNING (castración no lograda)
            - ALP >2x ULN → WARNING (posible progresión ósea)
        """
        latest_values = {
            "hemoglobin": patient.get("hemoglobin") or patient.get("hemoglobina"),
            "testosterone": patient.get("testosterone") or patient.get("testosterone_current"),
            "alp": patient.get("alp") or patient.get("alkaline_phosphatase"),
            "ldh": patient.get("ldh"),
            "creatinine": patient.get("creatinine") or patient.get("creatinine_current"),
            "bilirubin": patient.get("bilirubin") or patient.get("bilirubin_current"),
            "ast": patient.get("ast") or patient.get("ast_current"),
            "alt": patient.get("alt") or patient.get("alt_current"),
            "ggt": patient.get("ggt") or patient.get("ggt_current"),
        }
        structured_alerts = build_laboratory_alerts(
            latest_values,
            treatment_text=str(patient.get("current_treatment") or ""),
            adt_context=str(patient.get("adt_context") or patient.get("current_adt_context") or ""),
        )
        return [
            ClinicalAlert(
                patient_id=patient_id,
                alert_type=str(alert.key),
                severity=str(alert.severity),
                category="laboratory",
                title=str(alert.title),
                message=str(alert.message),
                recommended_action=str(alert.recommended_action),
                guideline_reference=str(alert.guideline_reference),
                triggering_value=str(alert.triggering_value),
                threshold=str(alert.threshold),
            )
            for alert in structured_alerts
        ]

    @staticmethod
    def evaluate_ecog_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa cambios en ECOG Performance Status.

        Umbrales:
            - ECOG ≥3 → CRITICAL (reevaluar intensidad terapéutica)
            - Incremento ≥1 punto vs última visita → WARNING
        """
        alerts: list[ClinicalAlert] = []

        ecog = patient.get("ecog") or patient.get("ecog_score")
        if ecog is not None:
            try:
                ecog = int(float(ecog))
                if ecog >= 3:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="ecog_critical",
                        severity="critical",
                        category="ecog",
                        title=f"ECOG {ecog} — Deterioro funcional severo",
                        message=f"ECOG Performance Status: {ecog}. Paciente con limitación significativa para autocuidado.",
                        recommended_action="Reevaluar intensidad terapéutica. Considerar transición a mejor soporte de cuidado o tratamiento adaptado. Evaluación paliativa.",
                        guideline_reference="NCCN 5.2026 / EAU 2026",
                        triggering_value=str(ecog),
                        threshold="≥ 3",
                    ))
            except (ValueError, TypeError):
                pass

        ecog_prev = patient.get("ecog_previous")
        if ecog is not None and ecog_prev is not None:
            try:
                delta = int(float(ecog)) - int(float(ecog_prev))
                if delta >= 1:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="ecog_decline",
                        severity="warning",
                        category="ecog",
                        title=f"Deterioro ECOG: {int(float(ecog_prev))} → {int(float(ecog))}",
                        message=f"Incremento de {delta} punto(s) en ECOG. Evaluar causa (progresión, toxicidad, comorbilidad).",
                        recommended_action="Investigar causa del deterioro. Ajustar plan terapéutico si está relacionado con toxicidad.",
                        guideline_reference="NCCN Supportive Care",
                        triggering_value=f"ECOG {int(float(ecog))}",
                        threshold="Incremento ≥ 1 punto",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @staticmethod
    def evaluate_treatment_milestones(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa milestones de tratamiento que requieren acción.

        - Duración de ADT (6, 12, 18, 24 meses) → info/recordatorio
        - Ciclos de docetaxel completados (6 = estándar)
        - Ventana de re-evaluación ARPI
        """
        alerts: list[ClinicalAlert] = []

        adt_months = patient.get("adt_duration_months")
        if adt_months is not None:
            try:
                months = float(adt_months)
                milestones = [
                    (6, "6 meses de ADT — Reevaluar respuesta y tolerancia"),
                    (12, "12 meses de ADT — Considerar intensificación o modulación"),
                    (18, "18 meses de ADT — Checkpoint de duración"),
                    (24, "24 meses de ADT — Evaluar suspensión vs continuación según riesgo"),
                ]
                for milestone_months, title in milestones:
                    if abs(months - milestone_months) < 1:
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id,
                            alert_type=f"adt_milestone_{milestone_months}m",
                            severity="info",
                            category="treatment_milestone",
                            title=title,
                            message=f"Duración actual de ADT: {months:.0f} meses.",
                            recommended_action="Revisar plan terapéutico, efectos metabólicos/cardiovasculares y QoL.",
                            guideline_reference="NCCN 5.2026 / EAU 2026",
                            triggering_value=f"{months:.0f} meses",
                            threshold=f"{milestone_months} meses",
                        ))
            except (ValueError, TypeError):
                pass

        docetaxel_cycles = patient.get("prior_docetaxel_cycles")
        if docetaxel_cycles is not None:
            try:
                cycles = int(float(docetaxel_cycles))
                if cycles >= 6:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="docetaxel_complete",
                        severity="info",
                        category="treatment_milestone",
                        title=f"Docetaxel: {cycles} ciclos completados",
                        message=f"Se completaron {cycles} ciclos de docetaxel (estándar = 6). Re-evaluar respuesta y plan de continuación.",
                        recommended_action="Re-estadificación con imagen. Evaluar transición a mantenimiento o siguiente línea.",
                        guideline_reference="TAX-327 / CHAARTED",
                        triggering_value=str(cycles),
                        threshold="6 ciclos",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @staticmethod
    def evaluate_genomic_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa biomarcadores genómicos expandidos y genera alertas.

        Reglas:
            - AR-V7 positivo bajo ARPI → CRITICAL (resistencia documentada)
            - ctDNA VAF en ascenso → WARNING (resistencia emergente)
            - Sospecha NEPC (TP53+RB1+NSE/LDH/PSA bajo) → CRITICAL
            - PTEN loss → WARNING (peor pronóstico bajo ARPI)
            - CDK12 biallelic → INFO (candidato IO independiente de MSI)
        """
        alerts: list[ClinicalAlert] = []

        def _is_positive(val: str) -> bool:
            v = val.lower()
            return v.startswith("pos") or v in {"detected", "detectado", "mutado", "loss", "perdida", "biallelic", "bialélico"}

        # ── AR-V7 positivo bajo ARPI ──
        ar_v7 = str(patient.get("ar_v7_status", ""))
        ar_v7_positive = ar_v7 and _is_positive(ar_v7)
        current_tx = str(patient.get("current_treatment", "") or patient.get("prior_therapy", ""))
        on_arpi = any(d in current_tx for d in ["Enzalutamida", "Abiraterona", "Apalutamida", "Darolutamida"])
        if ar_v7_positive and on_arpi:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ar_v7_resistance",
                severity="critical",
                category="genomic",
                title="AR-V7 positivo bajo ARPI — Resistencia documentada",
                message="AR-V7 positivo predice falta de respuesta a enzalutamida/abiraterona. Mediana de respuesta ~3 meses vs ~8 meses con taxanos.",
                recommended_action="Considerar cambio a taxano (docetaxel/cabazitaxel). No secuenciar otro ARPI.",
                guideline_reference="PROPHECY (Armstrong 2019), Antonarakis NEJM 2014",
                triggering_value="AR-V7 positivo",
                threshold="Positivo bajo ARPI activo",
            ))
        elif ar_v7_positive:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ar_v7_detected",
                severity="warning",
                category="genomic",
                title="AR-V7 positivo — Evitar ARPI como siguiente línea",
                message="AR-V7 positivo documentado. Resistencia a ARPI esperada.",
                recommended_action="Preferir taxanos sobre ARPI en la próxima línea terapéutica.",
                guideline_reference="PROPHECY (Armstrong 2019)",
                triggering_value="AR-V7 positivo",
                threshold="Cualquier detección",
            ))

        # ── ctDNA trending (Wyatt 2021, Chi 2022) ──
        ctdna_rising = str(patient.get("ctdna_rising", "0")) == "1"
        ctdna_vaf = patient.get("ctdna_vaf")
        ctdna_vaf_prev = patient.get("ctdna_vaf_previous")
        if ctdna_rising:
            msg = "ctDNA en ascenso documentado — señal de resistencia emergente semanas antes que PSA."
            if ctdna_vaf is not None and ctdna_vaf_prev is not None:
                try:
                    vaf = float(ctdna_vaf)
                    vaf_prev = float(ctdna_vaf_prev)
                    if vaf_prev > 0:
                        pct_change = ((vaf - vaf_prev) / vaf_prev) * 100
                        msg = f"ctDNA VAF subió {pct_change:.0f}% ({vaf_prev:.1f}% → {vaf:.1f}%). Resistencia emergente pre-radiográfica."
                except (ValueError, TypeError):
                    pass
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ctdna_rising",
                severity="warning",
                category="genomic",
                title="ctDNA en ascenso — Resistencia emergente",
                message=msg,
                recommended_action="Considerar cambio de línea anticipado antes de progresión radiográfica. Repetir biopsia líquida en 4-6 semanas.",
                guideline_reference="Wyatt 2021, Chi 2022",
                triggering_value=f"VAF {ctdna_vaf}%" if ctdna_vaf else "Rising",
                threshold="Ascenso entre mediciones",
            ))

        # ── Sospecha NEPC (Beltran 2016) ──
        tp53 = str(patient.get("tp53_status", ""))
        rb1 = str(patient.get("rb1_status", ""))
        tp53_altered = tp53 and _is_positive(tp53)
        rb1_loss = rb1 and _is_positive(rb1)

        nepc_score = 0
        nepc_reasons: list[str] = []
        if tp53_altered and rb1_loss:
            nepc_score += 2
            nepc_reasons.append("TP53 + RB1 loss")
        ne_features = str(patient.get("neuroendocrine_features", "0")) == "1"
        if ne_features:
            nepc_score += 2
            nepc_reasons.append("características neuroendocrinas")
        try:
            nse = float(patient.get("nse") or patient.get("neuron_specific_enolase") or 0)
            if nse > 16.3:
                nepc_score += 1
                nepc_reasons.append(f"NSE elevado ({nse:.1f})")
        except (ValueError, TypeError):
            pass
        try:
            ldh = float(patient.get("ldh") or patient.get("lactate_dehydrogenase") or 0)
            if ldh > 250:
                nepc_score += 1
                nepc_reasons.append(f"LDH elevado ({ldh:.0f})")
        except (ValueError, TypeError):
            pass
        psa_disc = str(patient.get("psa_discordant_low", "0")) == "1"
        if psa_disc:
            nepc_score += 1
            nepc_reasons.append("PSA discordante bajo")

        if nepc_score >= 3:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="nepc_suspicion",
                severity="critical",
                category="genomic",
                title=f"Sospecha NEPC — Score {nepc_score}/7",
                message=f"Algoritmo de sospecha neuroendocrina activado por: {', '.join(nepc_reasons)}. 15-20% de mCRPC desarrollan NEPC.",
                recommended_action="Biopsia de confirmación histológica urgente. Considerar carboplatino + etopósido si se confirma. Suspender ARPI si hay transformación.",
                guideline_reference="Beltran 2016, Aggarwal 2018, NCCN 2026",
                triggering_value=f"Score {nepc_score}/7",
                threshold="≥ 3/7",
            ))
        elif tp53_altered and rb1_loss:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="lineage_plasticity_risk",
                severity="warning",
                category="genomic",
                title="TP53 + RB1 loss — Riesgo de lineage plasticity",
                message="Ambas alteraciones presentes. Riesgo elevado de transformación neuroendocrina futura.",
                recommended_action="Monitorear NSE, LDH, cromogranina A y ratio PSA/volumen tumoral cada 2-3 meses. Considerar biopsia ante progresión atípica.",
                guideline_reference="Beltran 2016, Mu 2017",
                triggering_value="TP53 mutado + RB1 loss",
                threshold="Ambos alterados",
            ))

        # ── PTEN loss ──
        pten = str(patient.get("pten_loss", patient.get("pten_status", "")))
        pten_lost = pten and _is_positive(pten)
        if pten_lost:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="pten_loss",
                severity="warning",
                category="genomic",
                title="PTEN loss — Peor pronóstico bajo ARPI",
                message="PTEN loss activa la vía PI3K/AKT. Asociado a menor duración de respuesta bajo ARPI estándar.",
                recommended_action="Considerar inhibidores AKT (ipatasertib, capivasertib) combinados con abiraterona. Monitoreo más frecuente de respuesta.",
                guideline_reference="IPATential150 (de Bono 2020), Jamaspishvili 2018",
                triggering_value="PTEN loss",
                threshold="Confirmado por IHC o NGS",
            ))

        # ── CDK12 biallelic ──
        cdk12 = str(patient.get("cdk12_status", ""))
        cdk12_bi = cdk12 and cdk12.lower() in {"biallelic", "bialélico", "positivo", "pos", "detected", "detectado"}
        if cdk12_bi:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="cdk12_biallelic",
                severity="info",
                category="genomic",
                title="CDK12 bialélico — Candidato IO independiente de MSI",
                message="CDK12 bialélico genera alta carga neoantigénica. Candidato a inmunoterapia incluso sin MSI-H.",
                recommended_action="Considerar pembrolizumab. Verificar TMB como biomarcador complementario.",
                guideline_reference="Wu 2018, Antonarakis 2020",
                triggering_value="CDK12 bialélico",
                threshold="Inactivación bialélica confirmada",
            ))

        return alerts

    @staticmethod
    def evaluate_ddi_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        EPIC 4.4 — Alertas derivadas del motor DDI.

        Familias emitidas como ``category``:
            * ``ddi_critical``  — interacción contraindicada (severity=critical)
            * ``ddi_major``     — interacción mayor (severity=warning)
            * ``ddi_moderate``  — interacción moderada / caution (severity=info)
            * ``ddi_qtc``       — prolongación QTc (severity según gravedad)
            * ``ddi_seizure``   — umbral convulsivo (severity según gravedad)
            * ``ddi_bone_health`` — remodelación ósea (Ra-223 + zoledronato/denosumab)

        Lee ``ddi_regimen_matrix`` (producido por
        ``advanced_support_normalizer.build_ddi_regimen_matrix`` o
        ``DDIEngine.compute_regimen_ddi_matrix`` en tiempo real) y
        ``ddi_alert_bundle`` (alertas sobre el régimen activo) del payload
        del paciente.

        Alert fatigue guard: deduplica por (drug_a, drug_b, category).
        """
        alerts: list[ClinicalAlert] = []
        severity_rank = {"info": 0, "warning": 1, "critical": 2}

        def _severity_from_ddi(ddi_severity: str) -> str:
            raw = str(ddi_severity or "").strip().lower()
            if raw == "contraindicated":
                return "critical"
            if raw == "major":
                return "warning"
            return "info"

        seen: dict[tuple[str, str, str], ClinicalAlert] = {}

        def _emit(alert_dict: dict[str, Any], *, regimen_code: str = "", regimen_lbl: str = "") -> None:
            drug_a = str(alert_dict.get("drug_a") or "").strip()
            drug_b = str(alert_dict.get("drug_b") or "").strip()
            category = str(alert_dict.get("alert_family") or "").strip().lower()
            if not category:
                # Fallback: si el alert_family no viene seteado, derivar de severity.
                sev = str(alert_dict.get("severity") or "").strip().lower()
                category = {
                    "contraindicated": "ddi_critical",
                    "major": "ddi_major",
                    "moderate": "ddi_moderate",
                }.get(sev, "ddi_moderate")
            severity = _severity_from_ddi(alert_dict.get("severity") or "")
            key = (drug_a.lower(), drug_b.lower(), category)
            # Alert fatigue guard: conservar sólo la de mayor severidad por clave.
            existing = seen.get(key)
            if existing and severity_rank.get(severity, 0) <= severity_rank.get(existing.severity, 0):
                return
            title_prefix = ""
            if regimen_lbl:
                title_prefix = f"[{regimen_lbl}] "
            title = f"{title_prefix}DDI {drug_a} ↔ {drug_b}".strip()
            mechanism = str(alert_dict.get("mechanism") or "").strip()
            impact = str(alert_dict.get("clinical_impact") or alert_dict.get("impact") or "").strip()
            action = str(alert_dict.get("recommended_action") or alert_dict.get("action") or "").strip()
            alternative = str(alert_dict.get("alternative") or "").strip()
            if alternative:
                action = (action + f" Alternativa: {alternative}.").strip()
            reference = str(alert_dict.get("reference") or "").strip()
            message_bits = [bit for bit in (mechanism, impact) if bit]
            message = " — ".join(message_bits) or f"Interacción {drug_a} ↔ {drug_b}."
            alert = ClinicalAlert(
                patient_id=patient_id,
                alert_type=f"ddi_{category.replace('ddi_', '')}".lower() or "ddi_interaction",
                severity=severity,
                category=category,
                title=title,
                message=message,
                recommended_action=action,
                guideline_reference=reference,
                triggering_value=f"{drug_a} + {drug_b}",
                threshold=f"regimen={regimen_code}" if regimen_code else "",
            )
            # Sustituir si ya existía con menor severidad.
            seen[key] = alert

        # 1) Alertas sobre el régimen activo (ddi_alert_bundle.alerts)
        active_bundle = dict(patient.get("ddi_alert_bundle") or {})
        for entry in active_bundle.get("alerts") or []:
            if isinstance(entry, dict):
                _emit(entry)

        # 2) Matriz de candidatos (ddi_regimen_matrix) — alertas por régimen.
        regimen_matrix = dict(patient.get("ddi_regimen_matrix") or {})
        try:
            from prostanet.domains.patient_tracking.therapy_catalog import regimen_label as _regimen_label
        except Exception:  # pragma: no cover
            _regimen_label = lambda code: code  # noqa: E731

        for regimen_code, bundle in regimen_matrix.items():
            if not isinstance(bundle, dict):
                continue
            lbl = ""
            try:
                lbl = _regimen_label(regimen_code) or regimen_code
            except Exception:
                lbl = regimen_code
            for entry in bundle.get("alerts") or []:
                if isinstance(entry, dict):
                    _emit(entry, regimen_code=regimen_code, regimen_lbl=lbl)

        alerts.extend(seen.values())
        # Ordenar por severidad descendente para surface consistente.
        alerts.sort(key=lambda a: (-severity_rank.get(a.severity, 0), a.category, a.title))
        return alerts

    # ── EPIC 6 — Bone health, germline triggers, CTCAE ────────────────────
    # Familias emitidas:
    #   bone_dxa_missing_mandatory, bone_bma_initiate, bone_bma_switch_renal,
    #   bone_hypocalcemia_before_bma  (NCCN PROS-I, Fizazi 2011, Smith 2009/2014)
    #   germline_testing_offer, germline_family_counseling
    #     (NCCN PROS-H, Giri JCO 2020, Pritchard NEJM 2016)
    #   ctcae_grade3_no_action, ctcae_critical, ctcae_agent_overburden
    #     (CTCAE v5.0, NCI 2017)

    @staticmethod
    def evaluate_bone_health_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """EPIC 6 — Salud ósea: DXA, BMA (denosumab/zoledronato), Ca/vit D.

        Reutiliza ``build_bone_health_recommendation`` si el bundle ya fue
        computado por ``profile_compass`` (``bone_health_bundle``); en caso
        contrario lo evalúa bajo demanda con lazy import.
        """
        alerts: list[ClinicalAlert] = []
        bundle = patient.get("bone_health_bundle")
        if bundle is None:
            try:
                from prostanet.domains.patient_tracking.bone_health_engine import (
                    build_bone_health_recommendation,
                )
                bundle = build_bone_health_recommendation(patient).to_dict()
            except Exception:
                logger.exception("bone_health_engine unavailable — omitiendo alertas óseas")
                return alerts

        raw_alerts = (bundle or {}).get("alerts") or []
        evidence = " / ".join((bundle or {}).get("evidence_tags") or []) or (
            "NCCN PROS-I v5.2026; Fizazi Lancet 2011 (denosumab); "
            "Smith JAMA 2014 HALT-ZA; Smith NEJM 2009 HALT"
        )
        for entry in raw_alerts:
            if not isinstance(entry, dict):
                continue
            a_type = str(entry.get("type") or "bone_health_alert").strip()
            severity = str(entry.get("severity") or "info").strip().lower()
            if severity not in {"info", "warning", "critical"}:
                severity = "info"
            message = str(entry.get("message") or "")
            action = str(entry.get("action") or "")
            title_map = {
                "bone_dxa_missing_mandatory": "DXA basal requerido — ADT ≥12 meses sin DXA documentado",
                "bone_bma_initiate": "Iniciar agente óseo (BMA)",
                "bone_bma_switch_renal": "Switch BMA por función renal — zoledronato contraindicado",
                "bone_hypocalcemia_before_bma": "Hipocalcemia — corregir antes de BMA",
            }
            title = title_map.get(a_type, a_type.replace("_", " ").title())
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type=a_type,
                severity=severity,
                category="bone_health",
                title=title,
                message=message,
                recommended_action=action,
                guideline_reference=evidence,
                triggering_value=str((bundle or {}).get("bone_category") or ""),
                threshold=str((bundle or {}).get("fracture_risk") or ""),
            ))
        return alerts

    @staticmethod
    def evaluate_germline_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """EPIC 6 — Germline testing triggers NCCN PROS-H.

        Emite:
            * ``germline_testing_offer`` si ``should_offer=True``.
            * ``germline_family_counseling`` cuando la variante patogénica
              germinal ya está confirmada y obliga a consejería familiar.
        """
        alerts: list[ClinicalAlert] = []
        bundle = patient.get("germline_recommendation_bundle")
        if bundle is None:
            try:
                from prostanet.shared.germline_testing_triggers import (
                    should_offer_germline_testing,
                )
                bundle = should_offer_germline_testing(patient).to_dict()
            except Exception:
                logger.exception("germline_testing_triggers no disponible — omitiendo")
                return alerts

        if not isinstance(bundle, dict):
            return alerts

        evidence = " / ".join(bundle.get("evidence_tags") or []) or (
            "NCCN Prostate v5.2026 PROS-H; Giri VN JCO 2020; Pritchard NEJM 2016"
        )
        priority = str(bundle.get("priority") or "").strip().lower()
        reasons = bundle.get("reasons") or []
        triggers = bundle.get("triggers_matched") or []

        if bundle.get("should_offer"):
            severity = "warning" if priority == "category_2a" else "info"
            trigger_ids = [str(t.get("id")) for t in triggers if isinstance(t, dict)]
            reasons_txt = " · ".join(str(r) for r in reasons)
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="germline_testing_offer",
                severity=severity,
                category="germline_testing",
                title=(
                    "Ofrecer testing germinal — criterio NCCN PROS-H "
                    f"({priority or 'consider'})"
                ),
                message=reasons_txt or "Paciente cumple criterio NCCN PROS-H para testing germinal.",
                recommended_action=(
                    "Derivar a consejería genética. Solicitar panel germinal "
                    "BRCA1/BRCA2/ATM/PALB2/CHEK2 + panel MMR (MSH2/MLH1/MSH6/PMS2)."
                ),
                guideline_reference=evidence,
                triggering_value=", ".join(trigger_ids) or "nccn_pros_h",
                threshold=priority or "category_2A",
            ))

        if bundle.get("family_counseling_recommended"):
            variant = bundle.get("known_pathogenic_variant") or "variante germinal"
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="germline_family_counseling",
                severity="warning",
                category="germline_testing",
                title=f"Consejería familiar — variante patogénica confirmada ({variant})",
                message=(
                    f"Variante patogénica germinal {variant} confirmada. "
                    "Familiares de primer grado deben recibir consejería genética "
                    "y testing cascada."
                ),
                recommended_action=(
                    "Referir a asesoría genética para familiares de primer grado; "
                    "considerar testing cascada en parientes de riesgo."
                ),
                guideline_reference=evidence,
                triggering_value=str(variant),
                threshold="family_counseling",
            ))

        return alerts

    @staticmethod
    def evaluate_ctcae_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """EPIC 6 — Toxicidad estructurada CTCAE v5.0.

        Reutiliza ``capture_ctcae_events`` (bundle ``ctcae_capture_bundle``)
        y convierte alertas raw a ``ClinicalAlert``.
        """
        alerts: list[ClinicalAlert] = []
        bundle = patient.get("ctcae_capture_bundle")
        if bundle is None:
            try:
                from prostanet.domains.patient_tracking.ctcae_capture_engine import (
                    capture_ctcae_events,
                )
                bundle = capture_ctcae_events(patient).to_dict()
            except Exception:
                logger.exception("ctcae_capture_engine no disponible — omitiendo")
                return alerts

        if not isinstance(bundle, dict):
            return alerts

        raw_alerts = bundle.get("alerts") or []
        burden = bundle.get("burden") or {}
        max_grade = burden.get("max_grade")
        for entry in raw_alerts:
            if not isinstance(entry, dict):
                continue
            a_type = str(entry.get("type") or "ctcae_event").strip()
            raw_severity = str(entry.get("severity") or "info").strip().lower()
            severity = "critical" if raw_severity == "critical" else (
                "warning" if raw_severity == "warning" else "info"
            )
            term = str(entry.get("term") or "")
            grade = entry.get("grade")
            agent = str(entry.get("agent") or "")
            count = entry.get("count")
            title_map = {
                "ctcae_grade3_no_action": (
                    f"CTCAE grado {grade} sin modificación — {term or 'toxicidad'}"
                ),
                "ctcae_critical": (
                    f"CTCAE crítico grado {grade} — {term or 'toxicidad'} potencialmente hospitalario"
                ),
                "ctcae_agent_overburden": (
                    f"{agent}: {count} eventos adversos — sobrecarga terapéutica"
                ),
            }
            title = title_map.get(a_type, a_type.replace("_", " ").title())
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type=a_type,
                severity=severity,
                category="ctcae_toxicity",
                title=title,
                message=str(entry.get("message") or ""),
                recommended_action=str(entry.get("recommended_action") or ""),
                guideline_reference="CTCAE v5.0 NCI 2017 / NCCN toxicity management",
                triggering_value=str(term or agent or ""),
                threshold=(
                    f"grade>={grade}" if grade is not None else (
                        f"events>={count}" if count is not None else (
                            f"max_grade={max_grade}" if max_grade is not None else ""
                        )
                    )
                ),
            ))
        return alerts

    @classmethod
    def run_all(cls, patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """Ejecuta todos los evaluadores de alertas y retorna alertas combinadas."""
        alerts: list[ClinicalAlert] = []
        alerts.extend(cls.evaluate_psa_kinetics(patient_id, patient))
        alerts.extend(cls.evaluate_lab_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_ecog_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_treatment_milestones(patient_id, patient))
        alerts.extend(cls.evaluate_genomic_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_ddi_alerts(patient_id, patient))
        # EPIC 6 — bone health, germline triggers, CTCAE
        alerts.extend(cls.evaluate_bone_health_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_germline_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_ctcae_alerts(patient_id, patient))

        # PRO-driven alerts (Salto 3)
        try:
            from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
            pro_alerts = PRODecisionEngine.evaluate_all(patient_id, patient)
            for pa in pro_alerts:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type=pa.alert_type,
                    severity=pa.severity,
                    category=f"pro_{pa.category}",
                    title=pa.title,
                    message=pa.message,
                    recommended_action=pa.recommended_action,
                    guideline_reference=pa.reference,
                    triggering_value=str(pa.current_value) if pa.current_value is not None else "",
                    threshold=pa.threshold,
                ))
        except Exception:
            pass

        # ── Biopsia estructurada alerts ──
        try:
            from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService
            biopsies = patient.get("biopsies") or []
            if biopsies:
                current = biopsies[-1] if isinstance(biopsies[-1], dict) else None
                previous = biopsies[-2] if len(biopsies) >= 2 and isinstance(biopsies[-2], dict) else None
                if current:
                    parsed = StructuredBiopsyService.parse_structured_biopsy(current)
                    biopsy_alerts = StructuredBiopsyService.evaluate_biopsy_alerts(patient_id, parsed, previous)
                    for ba in biopsy_alerts:
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id, alert_type=ba.get("alert_type", ""),
                            severity=ba.get("severity", "info"), category=ba.get("category", "pathology"),
                            title=ba.get("title", ""), message=ba.get("message", ""),
                            recommended_action=ba.get("recommended_action", ""),
                            guideline_reference=ba.get("guideline_reference", ""),
                            triggering_value=ba.get("triggering_value", ""),
                            threshold=ba.get("threshold", ""),
                        ))
        except Exception:
            pass

        # ── Vigilancia activa alerts ──
        try:
            from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
            as_data = patient.get("active_surveillance")
            if as_data or patient.get("management_track") == "active_surveillance":
                state = patient.get("state", patient.get("clinical_state", "localized_initial"))
                as_protocol = ActiveSurveillanceService.build_as_protocol(patient, state)
                as_alerts = ActiveSurveillanceService.evaluate_as_alerts(patient_id, as_protocol)
                for aa in as_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=aa.get("alert_type", ""),
                        severity=aa.get("severity", "info"), category=aa.get("category", "active_surveillance"),
                        title=aa.get("title", ""), message=aa.get("message", ""),
                        recommended_action=aa.get("recommended_action", ""),
                        guideline_reference=aa.get("guideline_reference", ""),
                        triggering_value=aa.get("triggering_value", ""),
                        threshold=aa.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Radioterapia detallada alerts ──
        try:
            from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
            rt_data = patient.get("radiation_details") or patient.get("radiation")
            if rt_data:
                rt_summary = RadiotherapyDetailService.build_rt_history(patient)
                rt_alerts = RadiotherapyDetailService.evaluate_rt_alerts(patient_id, rt_summary, patient)
                for ra in rt_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=ra.get("alert_type", ""),
                        severity=ra.get("severity", "info"), category=ra.get("category", "radiation_therapy"),
                        title=ra.get("title", ""), message=ra.get("message", ""),
                        recommended_action=ra.get("recommended_action", ""),
                        guideline_reference=ra.get("guideline_reference", ""),
                        triggering_value=ra.get("triggering_value", ""),
                        threshold=ra.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Eventos esqueléticos alerts ──
        try:
            from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
            sre_data = patient.get("skeletal_events") or patient.get("bone_modifying_agent")
            bone_mets = patient.get("bone_metastasis_count") or patient.get("metastasis_count")
            if sre_data or bone_mets:
                state = patient.get("state", patient.get("clinical_state", ""))
                sre_profile = SkeletalEventService.build_sre_profile(patient, state)
                sre_alerts = SkeletalEventService.evaluate_sre_alerts(patient_id, sre_profile)
                for sa in sre_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=sa.get("alert_type", ""),
                        severity=sa.get("severity", "info"), category=sa.get("category", "skeletal_event"),
                        title=sa.get("title", ""), message=sa.get("message", ""),
                        recommended_action=sa.get("recommended_action", ""),
                        guideline_reference=sa.get("guideline_reference", ""),
                        triggering_value=sa.get("triggering_value", ""),
                        threshold=sa.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Endpoints de supervivencia alerts ──
        try:
            from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
            state = patient.get("state", patient.get("clinical_state", ""))
            if state:
                survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
                surv_alerts = SurvivalEndpointService.evaluate_survival_alerts(patient_id, survival_status)
                for sv in surv_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=sv.get("alert_type", ""),
                        severity=sv.get("severity", "info"), category=sv.get("category", "survival_endpoint"),
                        title=sv.get("title", ""), message=sv.get("message", ""),
                        recommended_action=sv.get("recommended_action", ""),
                        guideline_reference=sv.get("guideline_reference", ""),
                        triggering_value=sv.get("triggering_value", ""),
                        threshold=sv.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── IA: Detección de anomalías temporales (VAE) ──
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if resolve_feature_flags().get("ENABLE_AI_ANOMALY_DETECTION"):
                from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

                reg = get_runtime_model_registry()
                anomaly_model = reg.get("anomaly_detector")
                if anomaly_model:
                    anomaly_result = anomaly_model.predict(patient)
                    score = anomaly_result.values.get("anomaly_score", 0.0)
                    is_anomaly = anomaly_result.values.get("is_anomaly", False)
                    if is_anomaly:
                        anomalous_features = anomaly_result.values.get("anomalous_features", [])
                        feature_str = ", ".join(anomalous_features[:3]) or "laboratorio"
                        severity = "critical" if score > 0.85 else "warning"
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id,
                            alert_type="ai_temporal_anomaly",
                            severity=severity,
                            category="ai_anomaly",
                            title="Anomalía en serie temporal detectada por IA",
                            message=(
                                f"El modelo VAE detectó un patrón inusual en la evolución clínica "
                                f"(score={score:.2f}). Parámetros afectados: {feature_str}. "
                                "Esto puede indicar progresión atípica o discordancia de datos."
                            ),
                            recommended_action="Revisar la tendencia longitudinal de laboratorios e imágenes recientes.",
                            guideline_reference="ProstaNet AI — Anomaly Detection v1.0",
                            triggering_value=f"anomaly_score={score:.3f}",
                            threshold="score>0.60",
                        ))
        except Exception:
            pass

        return alerts
