# -*- coding: utf-8 -*-
"""
Autonomous SOAP Note Generator — "El Escribano Clínico".

Generates a complete, structured, physician-grade clinical note from
patient data with zero human input. This is the core of the
"eliminate first-contact physician" functionality.

SOAP structure:
  S — Subjective: symptoms, PROs, functional status
  O — Objective: labs, imaging, ECOG, vitals, PSA kinetics
  A — Assessment: clinical state, risk classification, AI predictions,
                  guideline concordance, disease course
  P — Plan: treatment recommendation, monitoring agenda, alerts,
            clinical trial eligibility, referral triggers

All output is in medical Spanish, formatted for EHR integration.

Usage::

    generator = SOAPNoteGenerator()
    note = generator.generate(patient_record)
    print(note.full_text)  # Complete formatted note
    note.to_dict()         # Machine-readable structured version
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# ── State labels in medical Spanish ──
STATE_LABELS = {
    "diagnostic_workup": "Evaluación diagnóstica inicial",
    "post_negative_biopsy_followup": "Seguimiento post-biopsia negativa",
    "localized_initial": "Cáncer de próstata localizado",
    "post_prostatectomy": "Post-prostatectomía radical",
    "recurrence_bcr": "Recurrencia bioquímica",
    "adt_progression_verification": "Verificación de progresión bajo TDA",
    "mcspc_oligo_metachronous": "CPHSm — oligo-metastásico metacrónico",
    "mcspc_low_volume_sync_oligo": "CPHSm — bajo volumen sincrónico (oligo)",
    "mcspc_high_volume_sync": "CPHSm — alto volumen sincrónico",
    "mcspc_high_volume_metachronous": "CPHSm — alto volumen metacrónico",
    "mcspc_high_volume": "CPHSm — alto volumen",
    "m0_crpc": "CPRC no metastásico (M0-CPRC)",
    "m1_crpc": "CPRC metastásico (M1-CPRC)",
}

RISK_LABELS = {
    "very_low": "Muy bajo riesgo",
    "low": "Bajo riesgo",
    "intermediate_favorable": "Riesgo intermedio favorable",
    "intermediate_unfavorable": "Riesgo intermedio desfavorable",
    "high": "Alto riesgo",
    "very_high": "Muy alto riesgo",
    "regional": "Enfermedad regional",
    "metastatic": "Enfermedad metastásica",
}


@dataclass
class SOAPNote:
    """Structured SOAP clinical note."""
    patient_id: int
    note_date: str
    state: str

    # Sections
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""

    # Structured sub-sections
    problem_list: list[str] = field(default_factory=list)
    active_medications: list[str] = field(default_factory=list)
    alerts_fired: list[str] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    guideline_reference: str = ""
    ai_confidence: float = 0.0

    @property
    def full_text(self) -> str:
        """Full formatted note text."""
        separator = "\n" + "─" * 60 + "\n"
        sections = [
            f"NOTA CLÍNICA — ProstaNet AI  [{self.note_date}]",
            f"Paciente ID: {self.patient_id}  |  Estado: {STATE_LABELS.get(self.state, self.state)}",
            separator,
            "SUBJETIVO (S)",
            self.subjective or "(Sin datos subjetivos registrados)",
            separator,
            "OBJETIVO (O)",
            self.objective or "(Sin datos objetivos recientes)",
            separator,
            "EVALUACIÓN (A)",
            self.assessment or "(Evaluación pendiente)",
            separator,
            "PLAN (P)",
            self.plan or "(Plan pendiente de datos adicionales)",
        ]
        if self.alerts_fired:
            sections += [separator, "ALERTAS ACTIVAS", "\n".join(f"  ⚠ {a}" for a in self.alerts_fired)]
        if self.data_gaps:
            sections += ["\nDATA GAPS (calidad clínica reducida):", "\n".join(f"  • {g}" for g in self.data_gaps)]
        if self.guideline_reference:
            sections += [f"\n[{self.guideline_reference}]"]
        if self.ai_confidence:
            sections += [f"[Confianza IA: {self.ai_confidence:.0%}]"]
        return "\n".join(sections)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SOAPNoteGenerator:
    """
    Generates a complete SOAP note from a patient record.

    No GPU required — combines clinical scores, guideline rules,
    PSA kinetics, natural history, and AI agent outputs.
    """

    def generate(self, patient: dict[str, Any]) -> SOAPNote:
        """Generate a complete SOAP note for a patient."""
        identity = patient.get("identity", {}) or {}
        baseline = patient.get("baseline", {}) or {}
        follow_ups = patient.get("follow_ups", []) or []
        latest_fu = follow_ups[-1] if follow_ups else {}
        state = (
            patient.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or "diagnostic_workup"
        )
        patient_id = int(identity.get("id", 0))

        note = SOAPNote(
            patient_id=patient_id,
            note_date=date.today().isoformat(),
            state=state,
        )

        note.subjective = self._build_subjective(patient, baseline, latest_fu)
        note.objective = self._build_objective(patient, baseline, latest_fu, follow_ups)
        note.assessment = self._build_assessment(patient, baseline, state, follow_ups)
        note.plan = self._build_plan(patient, state, baseline)
        note.problem_list = self._build_problem_list(patient, state, baseline)
        note.active_medications = self._build_medications(patient)
        note.alerts_fired = self._build_alerts(patient, state, follow_ups)
        note.data_gaps = self._build_data_gaps(patient, state)
        note.next_steps = self._build_next_steps(patient, state)
        note.guideline_reference = "NCCN Prostate Cancer v5.2026 | EAU 2026"
        note.ai_confidence = self._compute_note_confidence(patient)

        return note

    # ── Section builders ──

    def _build_subjective(
        self,
        patient: dict,
        baseline: dict,
        latest_fu: dict,
    ) -> str:
        lines = []

        # Demographics
        age = baseline.get("age") or (patient.get("identity") or {}).get("age_at_diagnosis")
        dx_date = (patient.get("identity") or {}).get("diagnosis_date", "")
        ethnicity = (patient.get("demographics") or {}).get("ethnicity", "")
        lines.append(
            f"Paciente masculino de {age} años"
            + (f", {ethnicity}" if ethnicity else "")
            + f", con diagnóstico de adenocarcinoma de próstata desde {dx_date}."
        )

        # Family history
        fh = patient.get("family_history", []) or []
        if fh:
            fh_str = "; ".join(
                f"{r.get('relation','')} con {r.get('cancer_type','Ca.')}" for r in fh[:3]
            )
            lines.append(f"Antecedentes familiares: {fh_str}.")

        # Functional status
        ecog = latest_fu.get("ecog_current") or latest_fu.get("ecog") or baseline.get("ecog_score")
        if ecog is not None:
            ecog_labels = {0: "asintomático", 1: "síntomas leves, ambulatorio", 2: "en cama <50% del día", 3: "en cama >50% del día", 4: "totalmente dependiente"}
            lines.append(f"Estado funcional ECOG {ecog}: {ecog_labels.get(int(ecog), '')}.")

        # Pain
        pain = latest_fu.get("pain_score")
        if pain is not None:
            pain_label = "sin dolor" if int(pain) == 0 else f"dolor {pain}/10"
            lines.append(f"Escala de dolor: {pain_label}.")

        # PRO data
        pro = patient.get("pro_assessments") or []
        if pro:
            latest_pro = pro[-1] if isinstance(pro[-1], dict) else {}
            if latest_pro.get("urinary_score") is not None:
                lines.append(f"Síntomas urinarios (EPIC): {latest_pro.get('urinary_score')}/100.")
            if latest_pro.get("sexual_score") is not None:
                lines.append(f"Función sexual (EPIC): {latest_pro.get('sexual_score')}/100.")
            if latest_pro.get("bowel_score") is not None:
                lines.append(f"Síntomas intestinales (EPIC): {latest_pro.get('bowel_score')}/100.")

        # Opioid use
        opioid = latest_fu.get("opioid_use")
        if opioid:
            lines.append(f"Uso de opioides: {opioid}.")

        # Weight / nutritional
        weight = latest_fu.get("weight_kg")
        bmi = latest_fu.get("bmi_current")
        if weight:
            lines.append(f"Peso actual: {weight} kg" + (f", IMC {bmi:.1f}" if bmi else "") + ".")

        return "\n".join(lines) if lines else "Sin datos subjetivos estructurados disponibles."

    def _build_objective(
        self,
        patient: dict,
        baseline: dict,
        latest_fu: dict,
        follow_ups: list,
    ) -> str:
        lines = []

        # PSA (current + trend)
        psa = latest_fu.get("psa_current")
        if psa is not None:
            psa_date = latest_fu.get("visit_date", "")
            # Compare to prior
            prior_psa = None
            if len(follow_ups) >= 2:
                prior = follow_ups[-2]
                prior_psa = prior.get("psa_current")
            psa_trend = ""
            if prior_psa and float(prior_psa) > 0:
                ratio = float(psa) / float(prior_psa)
                if ratio > 1.25:
                    psa_trend = " ↑ (progresión bioquímica)"
                elif ratio < 0.5:
                    psa_trend = " ↓↓ (respuesta significativa)"
                elif ratio < 0.75:
                    psa_trend = " ↓ (descenso)"
                else:
                    psa_trend = " → (estable)"
            lines.append(f"PSA: {psa} ng/mL [{psa_date}]{psa_trend}.")

        # Testosterone
        testo = latest_fu.get("testosterone_current")
        if testo is not None:
            castrate = "(castración médica confirmada)" if float(testo) < 50 else f"(⚠ >50 ng/dL: revisar castración)"
            lines.append(f"Testosterona: {testo} ng/dL {castrate}.")

        # PSADT
        from prostanet.domains.patient_tracking.natural_history_tracker import NaturalHistoryTracker
        psadt = NaturalHistoryTracker._compute_psadt(follow_ups)
        if psadt:
            urgency = "corto (agresivo)" if psadt < 6 else "moderado" if psadt < 12 else "largo"
            lines.append(f"PSADT: {psadt} meses ({urgency}).")

        # Labs
        lab_fields = [
            ("hemoglobin", "Hemoglobina", "g/dL"),
            ("alp_current", "Fosfatasa alcalina", "U/L"),
            ("ldh_current", "LDH", "U/L"),
            ("albumin_current", "Albúmina", "g/dL"),
            ("creatinine_current", "Creatinina", "mg/dL"),
        ]
        lab_lines = []
        for field_key, label, unit in lab_fields:
            val = latest_fu.get(field_key) or baseline.get(field_key.replace("_current", ""))
            if val is not None:
                lab_lines.append(f"{label}: {val} {unit}")
        if lab_lines:
            lines.append("Laboratorios: " + " | ".join(lab_lines) + ".")

        # Latest imaging
        imaging = patient.get("imaging_studies") or []
        if imaging:
            latest_img = imaging[-1] if isinstance(imaging[-1], dict) else {}
            study_type = latest_img.get("study_type", "Imagen")
            study_date = latest_img.get("study_date", "")
            pirads = latest_img.get("pirads_score")
            psma = latest_img.get("psma_result")
            if pirads:
                lines.append(f"RM Próstata [{study_date}]: PI-RADS {pirads}.")
            elif psma:
                suv = latest_img.get("psma_suv_max", "")
                lines.append(f"PSMA PET [{study_date}]: {psma}" + (f", SUVmax {suv}" if suv else "") + ".")
            elif study_type:
                lines.append(f"Imagen ({study_type}) [{study_date}]: documentada.")

        # Metastasis
        mets = latest_fu.get("metastasis_count") or (patient.get("prior_history") or {}).get("metastasis_count")
        met_site = latest_fu.get("metastasis_site") or (patient.get("prior_history") or {}).get("metastasis_site")
        if mets:
            lines.append(f"Metástasis: {mets} lesiones" + (f" ({met_site})" if met_site else "") + ".")

        # Genomics
        genomic = patient.get("genomic_profile") or {}
        genomic_items = []
        if genomic.get("hrr_status") or baseline.get("hrr_positive"):
            genomic_items.append("HRR+")
        if genomic.get("brca2_mutation"):
            genomic_items.append("BRCA2 mutado")
        if genomic.get("msi_status") == "MSI-H":
            genomic_items.append("MSI-H")
        if genomic.get("arv7_positive") or baseline.get("arv7_positive"):
            genomic_items.append("AR-V7+")
        if genomic.get("psma_positive") or baseline.get("psma_positive"):
            genomic_items.append("PSMA+")
        if genomic_items:
            lines.append(f"Perfil molecular: {', '.join(genomic_items)}.")

        return "\n".join(lines) if lines else "Sin datos objetivos recientes documentados."

    def _build_assessment(
        self,
        patient: dict,
        baseline: dict,
        state: str,
        follow_ups: list,
    ) -> str:
        lines = []

        # 1. Diagnosis summary
        state_label = STATE_LABELS.get(state, state)
        dx_date = (patient.get("identity") or {}).get("diagnosis_date", "")
        gleason_p = baseline.get("gleason_primary", 0)
        gleason_s = baseline.get("gleason_secondary", 0)
        isup = baseline.get("isup_grade")
        psa_bl = baseline.get("baseline_psa")
        tstage = baseline.get("clinical_tstage", "")

        diag_parts = [f"Adenocarcinoma de próstata ({dx_date})"]
        if gleason_p and gleason_s:
            diag_parts.append(f"Gleason {gleason_p}+{gleason_s}={gleason_p+gleason_s}")
        if isup:
            diag_parts.append(f"ISUP {isup}")
        if psa_bl:
            diag_parts.append(f"PSA basal {psa_bl} ng/mL")
        if tstage:
            diag_parts.append(f"cT{tstage}")
        lines.append(f"1. Diagnóstico: {', '.join(diag_parts)}.")
        lines.append(f"2. Estado clínico actual: **{state_label}**.")

        # 2. NCCN/D'Amico risk group
        try:
            from clinical_scores import nccn_risk_group, damico_classification
            risk_input = {
                "psa": psa_bl,
                "gleason_primary": gleason_p,
                "gleason_secondary": gleason_s,
                "isup_grade": isup,
                "clinical_tstage": tstage,
            }
            nccn_result = nccn_risk_group(risk_input)
            risk_group = nccn_result.get("risk_group", "")
            if risk_group:
                risk_label = RISK_LABELS.get(risk_group, risk_group)
                lines.append(f"3. Clasificación de riesgo NCCN: **{risk_label}**.")
        except Exception:
            pass

        # 3. Clinical scores
        try:
            from clinical_scores import capra_score, calculate_capra_s
            capra = capra_score({
                "psa": psa_bl, "gleason_primary": gleason_p, "gleason_secondary": gleason_s,
                "clinical_tstage": tstage,
                "age": baseline.get("age"),
                "positive_cores_pct": baseline.get("pct_cores_positive"),
            })
            capra_val = capra.get("score")
            capra_risk = capra.get("risk_group", "")
            if capra_val is not None:
                lines.append(f"4. CAPRA Score: {capra_val} ({capra_risk}).")
        except Exception:
            pass

        # 4. Disease course summary
        try:
            from prostanet.domains.patient_tracking.natural_history_tracker import NaturalHistoryTracker
            tracker = NaturalHistoryTracker()
            history = tracker.analyze(patient)
            if history.adjusted_os_months:
                lines.append(
                    f"5. Supervivencia global estimada ajustada: ~{history.adjusted_os_months:.0f} meses "
                    f"(OS publicada para {state}: {history.expected_os_months} meses; "
                    f"modificador comorbilidad/etnia: {history.os_modifier:.2f})."
                )
            if history.predicted_next_state:
                lines.append(
                    f"6. Próxima transición predicha: **{history.predicted_next_state}** "
                    f"en ~{history.predicted_time_to_transition_months:.0f} meses."
                )
            if history.flags:
                lines.append("7. Alertas del curso natural: " + " | ".join(history.flags[:3]))
        except Exception:
            pass

        # 5. Guideline concordance
        try:
            latest_assessment = patient.get("latest_assessment") or {}
            nccn_rec = latest_assessment.get("nccn_recommendation") or {}
            if nccn_rec.get("recommendation"):
                lines.append(f"8. Recomendación NCCN vigente: {nccn_rec['recommendation'][:200]}.")
        except Exception:
            pass

        return "\n".join(lines) if lines else "Evaluación clínica pendiente de datos adicionales."

    def _build_plan(
        self,
        patient: dict,
        state: str,
        baseline: dict,
    ) -> str:
        lines = []

        # Treatment recommendation
        try:
            latest_assessment = patient.get("latest_assessment") or {}
            nccn = latest_assessment.get("nccn_recommendation") or {}
            eau = latest_assessment.get("eau_recommendation") or {}

            if nccn.get("recommendation"):
                lines.append(f"a) Tratamiento (NCCN v5.2026): {nccn['recommendation'][:300]}.")
            if eau.get("recommendation") and eau["recommendation"] != nccn.get("recommendation"):
                lines.append(f"   EAU 2026 coincide: {eau['recommendation'][:150]}.")
        except Exception:
            pass

        # Active treatments
        treatments = patient.get("treatments") or []
        active_tx = [t for t in treatments if not t.get("end_date")]
        if active_tx:
            tx_str = ", ".join(t.get("drug_scheme", "") for t in active_tx[:3])
            lines.append(f"b) Tratamiento activo actual: {tx_str}.")

        # Monitoring schedule
        try:
            from prostanet.domains.patient_tracking.guideline_schedule_engine import (
                GuidelineScheduleEngine,
            )
            schedule = GuidelineScheduleEngine.get_schedule(state, patient)
            if schedule and isinstance(schedule, dict):
                psa_interval = schedule.get("psa_interval_months")
                imaging_interval = schedule.get("imaging_interval_months")
                if psa_interval:
                    lines.append(f"c) Monitoreo PSA: cada {psa_interval} meses.")
                if imaging_interval:
                    lines.append(f"   Imagen: cada {imaging_interval} meses (según respuesta).")
        except Exception:
            # Fallback schedule by state
            schedules = {
                "localized_initial": "PSA cada 6-12 meses",
                "post_prostatectomy": "PSA cada 3-6 meses (primeros 2 años)",
                "recurrence_bcr": "PSA cada 3 meses + imagen si PSADT <6m",
                "m0_crpc": "PSA cada 3 meses + imagen cada 6 meses",
                "m1_crpc": "PSA cada 3 meses + imagen cada 3-6 meses",
            }
            if state in schedules:
                lines.append(f"c) Monitoreo: {schedules[state]}.")

        # DDI review
        try:
            copilot = patient.get("copilot") or {}
            ddi = copilot.get("ddi_review") or {}
            if ddi.get("critical_interactions"):
                critical = ddi["critical_interactions"][:2]
                ddi_str = "; ".join(
                    f"{i.get('drug_a','?')}/{i.get('drug_b','?')} ({i.get('severity','?')})"
                    for i in critical
                )
                lines.append(f"d) ⚠ DDI crítico detectado: {ddi_str}. Revisar farmacología.")
        except Exception:
            pass

        # Clinical trial eligibility
        try:
            copilot = patient.get("copilot") or {}
            trials = copilot.get("clinical_trials") or {}
            eligible = trials.get("eligible_trials") or []
            if eligible:
                trial_names = [t.get("trial_name", t.get("nct_id", "")) for t in eligible[:2]]
                lines.append(f"e) Ensayos clínicos potencialmente elegibles: {', '.join(trial_names)}.")
        except Exception:
            pass

        # Genomic action items
        genomic = patient.get("genomic_profile") or baseline
        if genomic.get("hrr_positive") or genomic.get("hrr_status") == "positive":
            if state in ("m1_crpc",):
                lines.append("f) HRR+: considerar PARP inhibidor (olaparib/rucaparib) según PROfound.")
        if genomic.get("brca2_mutation"):
            lines.append("f) BRCA2: consultar oncología genética. Evaluar PARP inhibidor.")

        # Referrals
        referrals = self._determine_referrals(patient, state, baseline)
        if referrals:
            lines.append("g) Interconsultas recomendadas: " + ", ".join(referrals) + ".")

        return "\n".join(lines) if lines else "Plan pendiente de evaluación clínica completa."

    def _build_problem_list(self, patient: dict, state: str, baseline: dict) -> list[str]:
        problems = [f"Adenocarcinoma de próstata — {STATE_LABELS.get(state, state)}"]

        demographics = patient.get("demographics") or {}
        comorbidities = {
            "diabetes": "Diabetes mellitus",
            "dm_type2": "Diabetes mellitus tipo 2",
            "hypertension": "Hipertensión arterial",
            "heart_failure": "Insuficiencia cardíaca",
            "chronic_kidney_disease": "Enfermedad renal crónica",
            "copd": "EPOC",
            "osteoporosis": "Osteoporosis",
        }
        for key, label in comorbidities.items():
            if demographics.get(key) or baseline.get(key):
                problems.append(label)

        follow_ups = patient.get("follow_ups") or []
        latest_fu = follow_ups[-1] if follow_ups else {}
        if latest_fu.get("pain_score") and int(latest_fu["pain_score"]) >= 4:
            problems.append("Dolor crónico relacionado con cáncer")
        if latest_fu.get("hemoglobin") and float(latest_fu["hemoglobin"]) < 10:
            problems.append("Anemia (relacionada con TDA o infiltración medular)")

        return problems

    def _build_medications(self, patient: dict) -> list[str]:
        treatments = patient.get("treatments") or []
        active = [t for t in treatments if not t.get("end_date")]
        meds = []
        for tx in active[:5]:
            scheme = tx.get("drug_scheme", "")
            start = tx.get("start_date", "")
            if scheme:
                meds.append(f"{scheme} (inicio: {start})")
        return meds

    def _build_alerts(self, patient: dict, state: str, follow_ups: list) -> list[str]:
        alerts = []

        # PSA progression
        if len(follow_ups) >= 2:
            p1 = follow_ups[-1].get("psa_current")
            p0 = follow_ups[-2].get("psa_current")
            if p1 and p0 and float(p0) > 0 and float(p1) / float(p0) > 1.25:
                alerts.append(f"PSA en ascenso: {p0} → {p1} ng/mL (+{(float(p1)/float(p0)-1):.0%})")

        # Testosterone on ADT
        latest_fu = follow_ups[-1] if follow_ups else {}
        testo = latest_fu.get("testosterone_current")
        if testo and state in ("m0_crpc", "m1_crpc", "recurrence_bcr") and float(testo) > 50:
            alerts.append(f"Testosterona {testo} ng/dL > 50: castración no confirmada")

        # Hemoglobin
        hgb = latest_fu.get("hemoglobin_current") or latest_fu.get("hemoglobin")
        if hgb and float(hgb) < 8:
            alerts.append(f"Hemoglobina {hgb} g/dL — anemia severa")

        # ECOG deterioration
        ecog_vals = [int(fu.get("ecog_current") or fu.get("ecog", 0)) for fu in follow_ups[-4:] if fu.get("ecog_current") or fu.get("ecog")]
        if len(ecog_vals) >= 2 and ecog_vals[-1] > ecog_vals[0]:
            alerts.append(f"ECOG en deterioro: {ecog_vals[0]} → {ecog_vals[-1]}")

        return alerts

    def _build_data_gaps(self, patient: dict, state: str) -> list[str]:
        gaps = []
        baseline = patient.get("baseline") or {}
        follow_ups = patient.get("follow_ups") or []
        latest_fu = follow_ups[-1] if follow_ups else {}

        if not baseline.get("gleason_primary"):
            gaps.append("Biopsia/Gleason no documentado")
        if not baseline.get("isup_grade"):
            gaps.append("Grado ISUP no documentado")
        if state in ("m0_crpc", "m1_crpc") and not (patient.get("genomic_profile") or {}).get("hrr_status"):
            gaps.append("Perfil HRR/BRCA no evaluado (requerido para PARP inhibidores)")
        if state in ("m1_crpc",) and not baseline.get("psma_positive") and not (patient.get("imaging_studies") or []):
            gaps.append("PSMA-PET no documentado (requerido para Lu-177)")
        if state in ("m0_crpc", "m1_crpc") and not latest_fu.get("testosterone_current"):
            gaps.append("Testosterona actual no documentada — confirmar castración")
        if not follow_ups:
            gaps.append("Sin visitas de seguimiento registradas")

        return gaps

    def _build_next_steps(self, patient: dict, state: str) -> list[str]:
        steps = []
        state_steps = {
            "localized_initial": [
                "Confirmar evaluación multidisciplinaria (urología, radio-oncología)",
                "Discutir opciones: cirugía vs radioterapia vs vigilancia activa",
                "Considerar estudio PSMA-PET si riesgo intermedio-alto",
            ],
            "recurrence_bcr": [
                "PSMA-PET para estadificación si PSADT <6 meses o PSA >0.5",
                "Evaluar TDA + enzalutamida (EMBARK) vs radioterapia de rescate",
                "Confirmar testosterona <50 ng/dL",
            ],
            "m0_crpc": [
                "PSMA-PET para detección de M1 ocultas",
                "Iniciar ARSI (enzalutamida/apalutamida/darolutamida) según PROSPER/SPARTAN/ARAMIS",
                "Monitoreo imagen cada 6 meses",
            ],
            "m1_crpc": [
                "Evaluar biomarkers: HRR, MSI, PSMA",
                "Considerar secuencia: ARSI → taxano → Lu-177 (si PSMA+/HRR+: PARP)",
                "Referir a cuidados paliativos si ECOG ≥2",
                "Bisfosfonato/denosumab para protección ósea",
            ],
            "mcspc_high_volume_sync": [
                "Iniciar ADT + doblete/triplete (ARSI ± docetaxel): ARASENS/PEACE-1",
                "Estadificación completa con PSMA-PET",
                "Monitoreo PSA cada 3 meses",
            ],
        }
        steps.extend(state_steps.get(state, [
            "Continuar seguimiento según protocolo actual",
            "Actualizar perfil de riesgo con próxima visita",
        ]))
        return steps

    @staticmethod
    def _determine_referrals(patient: dict, state: str, baseline: dict) -> list[str]:
        referrals = []
        follow_ups = patient.get("follow_ups") or []
        latest_fu = follow_ups[-1] if follow_ups else {}

        ecog = latest_fu.get("ecog_current") or latest_fu.get("ecog") or baseline.get("ecog_score", 0)
        if state == "m1_crpc" or (ecog and int(ecog) >= 2):
            referrals.append("Cuidados paliativos")
        if baseline.get("hrr_positive") or (patient.get("genomic_profile") or {}).get("hrr_status"):
            referrals.append("Oncología genética")

        latest_assessment = patient.get("latest_assessment") or {}
        if latest_assessment.get("state") in ("localized_initial",):
            referrals.append("Radio-oncología (evaluación multidisciplinaria)")

        bone_mets = latest_fu.get("metastasis_site") or ""
        if "bone" in str(bone_mets).lower() or "ósea" in str(bone_mets).lower():
            referrals.append("Oncología de medicina nuclear (Lu-177 si PSMA+)")

        return referrals

    @staticmethod
    def _compute_note_confidence(patient: dict) -> float:
        """Estimate note quality based on data completeness."""
        score = 0.0
        checks = [
            ("baseline", "baseline_psa"),
            ("baseline", "gleason_primary"),
            ("baseline", "isup_grade"),
            ("follow_ups", None),
            ("treatments", None),
            ("latest_assessment", None),
            ("genomic_profile", None),
            ("imaging_studies", None),
        ]
        for section, field_key in checks:
            data = patient.get(section)
            if data:
                if field_key:
                    if isinstance(data, dict) and data.get(field_key):
                        score += 1
                elif isinstance(data, (list, dict)) and data:
                    score += 1
                else:
                    score += 0.5
            score = round(min(score, 8) / 8, 2)
        return score
