# -*- coding: utf-8 -*-
"""
Generador de presentación para Tumor Board / Comité Multidisciplinario.

Sintetiza la información clínica de un paciente en un formato estructurado
para discusión en sesión de tumor board, incluyendo:
  - Resumen demográfico y comorbilidades
  - Historia de enfermedad y estadificación
  - Cronología de tratamientos
  - Cinética de PSA y biomarcadores
  - Hallazgos de imagen y patología
  - Perfil genómico
  - Estado actual y preguntas para discusión
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


class TumorBoardPresentation:
    """Genera una presentación estructurada para tumor board."""

    @classmethod
    def generate(cls, patient: dict[str, Any]) -> dict[str, Any]:
        """
        Construye la presentación completa del caso.

        Args:
            patient: Registro completo del paciente (get_patient_full_record).

        Returns:
            Dict con secciones estructuradas para presentación.
        """
        identity = patient.get("identity", {})
        baseline = patient.get("baseline", {}) or {}
        prior = patient.get("prior_history", {}) or {}
        demographics = patient.get("demographics", {}) or {}
        assessment = patient.get("latest_assessment", {}) or {}
        followups = patient.get("follow_ups", []) or []
        genomic = patient.get("genomics", {}) or {}
        psa_series = patient.get("psa_series", []) or []

        # Extended clinical modules for tumor board
        extended_sections: dict[str, Any] = {}
        try:
            from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
            rt_summary = RadiotherapyDetailService.build_rt_history(patient)
            rt_profile = RadiotherapyDetailService.build_rt_summary_for_profile(rt_summary)
            if rt_profile.get("has_data"):
                extended_sections["radiotherapy_detail"] = rt_profile
        except Exception:
            pass
        try:
            from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
            state = assessment.get("state", "")
            sre_data = {}
            sre_data.update(identity)
            sre_data.update(baseline)
            sre_data.update(prior)
            sre_data["skeletal_events"] = patient.get("skeletal_events") or patient.get("sre_events") or []
            sre_profile = SkeletalEventService.build_sre_profile(sre_data, state)
            sre_section = SkeletalEventService.build_sre_summary_for_profile(sre_profile)
            if sre_section.get("has_data"):
                extended_sections["skeletal_events"] = sre_section
        except Exception:
            pass
        try:
            from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
            state = assessment.get("state", "")
            survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
            survival_section = SurvivalEndpointService.build_survival_summary_for_profile(survival_status)
            if survival_section.get("has_data"):
                extended_sections["survival_endpoints"] = survival_section
        except Exception:
            pass
        try:
            from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService
            biopsies = patient.get("biopsies") or []
            if biopsies and isinstance(biopsies[-1], dict):
                parsed_biopsy = StructuredBiopsyService.parse_structured_biopsy(biopsies[-1])
                biopsy_section = StructuredBiopsyService.build_biopsy_summary_for_profile(parsed_biopsy)
                if biopsy_section.get("has_data"):
                    extended_sections["structured_biopsy"] = biopsy_section
        except Exception:
            pass

        return {
            "generated_date": date.today().isoformat(),
            "patient_summary": cls._patient_summary(identity, demographics, baseline, prior),
            "disease_timeline": cls._disease_timeline(identity, baseline, prior, assessment),
            "treatment_history": cls._treatment_history(prior, followups),
            "psa_kinetics": cls._psa_kinetics(baseline, followups, prior, psa_series),
            "pathology": cls._pathology(baseline, prior),
            "imaging": cls._imaging(baseline, prior, followups),
            "genomic_profile": cls._genomic_profile(genomic),
            "current_status": cls._current_status(assessment, followups, prior),
            "discussion_points": cls._discussion_points(assessment, prior, baseline, genomic),
            **extended_sections,
        }

    @classmethod
    def _patient_summary(cls, identity: dict, demographics: dict, baseline: dict, prior: dict) -> dict[str, Any]:
        age = identity.get("age") or identity.get("edad")
        return {
            "age": age,
            "ecog": prior.get("ecog") or baseline.get("ecog_score") or baseline.get("ecog"),
            "comorbidities": prior.get("comorbidities") or baseline.get("comorbidities", ""),
            "charlson_score": demographics.get("charlson_score"),
            "g8_score": demographics.get("g8_score"),
            "frailty_status": demographics.get("frailty_status", ""),
            "relevant_history": prior.get("relevant_medical_history", ""),
        }

    @classmethod
    def _disease_timeline(cls, identity: dict, baseline: dict, prior: dict, assessment: dict) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        dx_date = identity.get("diagnosis_date") or baseline.get("diagnosis_date", "")
        if dx_date:
            events.append({"date": str(dx_date), "event": "Diagnóstico", "details": ""})

        biopsy_date = baseline.get("biopsy_date", "")
        gleason = baseline.get("gleason_score") or baseline.get("isup_grade_group", "")
        if biopsy_date:
            events.append({"date": str(biopsy_date), "event": "Biopsia", "details": f"Gleason/ISUP: {gleason}" if gleason else ""})

        rp_date = prior.get("rp_date") or prior.get("prostatectomy_date", "")
        if rp_date:
            events.append({"date": str(rp_date), "event": "Prostatectomía radical", "details": ""})

        rt_date = prior.get("rt_date") or prior.get("radiation_date", "")
        if rt_date:
            events.append({"date": str(rt_date), "event": "Radioterapia", "details": prior.get("rt_type", "")})

        adt_start = prior.get("adt_start_date", "")
        if adt_start:
            events.append({"date": str(adt_start), "event": "Inicio ADT", "details": prior.get("adt_type", "")})

        castration_date = prior.get("castration_resistance_date", "")
        if castration_date:
            events.append({"date": str(castration_date), "event": "Resistencia a castración", "details": ""})

        metastasis_date = prior.get("metastasis_date", "")
        if metastasis_date:
            events.append({"date": str(metastasis_date), "event": "Detección de metástasis", "details": prior.get("metastasis_sites", "")})

        state = assessment.get("state", "")
        if state:
            events.append({"date": date.today().isoformat(), "event": f"Estado actual: {state}", "details": ""})

        events.sort(key=lambda e: e["date"] or "9999")
        return events

    @classmethod
    def _treatment_history(cls, prior: dict, followups: list) -> list[dict[str, Any]]:
        treatments: list[dict[str, Any]] = []

        if prior.get("prior_rp"):
            treatments.append({
                "type": "Cirugía",
                "name": "Prostatectomía radical",
                "date": prior.get("rp_date", ""),
                "details": prior.get("rp_approach", ""),
                "outcome": f"Márgenes: {prior.get('surgical_margins', 'N/D')}",
            })

        if prior.get("prior_rt"):
            treatments.append({
                "type": "Radioterapia",
                "name": prior.get("rt_type", "RT"),
                "date": prior.get("rt_date", ""),
                "details": f"Dosis: {prior.get('rt_dose', 'N/D')} Gy",
                "outcome": "",
            })

        if prior.get("prior_adt"):
            treatments.append({
                "type": "Hormonal",
                "name": "ADT",
                "date": prior.get("adt_start_date", ""),
                "details": prior.get("adt_type", ""),
                "outcome": f"Duración: {prior.get('adt_duration_months', 'N/D')} meses",
            })

        for arpi in ("abiraterone", "enzalutamide", "apalutamide", "darolutamide"):
            if prior.get(f"prior_{arpi}"):
                treatments.append({
                    "type": "ARPI",
                    "name": arpi.capitalize(),
                    "date": prior.get(f"{arpi}_start_date", ""),
                    "details": "",
                    "outcome": prior.get(f"{arpi}_response", ""),
                })

        if prior.get("prior_docetaxel"):
            treatments.append({
                "type": "Quimioterapia",
                "name": "Docetaxel",
                "date": prior.get("docetaxel_start_date", ""),
                "details": f"{prior.get('prior_docetaxel_cycles', 'N/D')} ciclos",
                "outcome": prior.get("docetaxel_response", ""),
            })

        if prior.get("prior_cabazitaxel"):
            treatments.append({
                "type": "Quimioterapia",
                "name": "Cabazitaxel",
                "date": prior.get("cabazitaxel_start_date", ""),
                "details": "",
                "outcome": "",
            })

        if prior.get("prior_lu177"):
            treatments.append({
                "type": "Radiofármaco",
                "name": "Lu-177 PSMA",
                "date": prior.get("lu177_start_date", ""),
                "details": f"{prior.get('lu177_cycles', 'N/D')} ciclos",
                "outcome": "",
            })

        if prior.get("prior_olaparib") or prior.get("prior_rucaparib"):
            name = "Olaparib" if prior.get("prior_olaparib") else "Rucaparib"
            treatments.append({
                "type": "PARPi",
                "name": name,
                "date": "",
                "details": "",
                "outcome": "",
            })

        return treatments

    @classmethod
    def _psa_kinetics(cls, baseline: dict, followups: list, prior: dict, psa_series_input: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        psa_series: list[dict[str, Any]] = []
        if psa_series_input:
            for entry in psa_series_input:
                value = entry.get("value") or entry.get("psa")
                sample_date = entry.get("sample_date") or entry.get("date")
                if value is not None and sample_date:
                    psa_series.append({"label": str(sample_date), "value": value})
        else:
            psa_dx = baseline.get("psa_at_diagnosis") or baseline.get("psa_diagnosis") or baseline.get("baseline_psa")
            if psa_dx:
                psa_series.append({"label": "Diagnóstico", "value": psa_dx})

            for i, fu in enumerate(followups):
                psa_val = fu.get("psa_current")
                if psa_val is not None:
                    visit_date = fu.get("visit_date", f"Visita {i+1}")
                    psa_series.append({"label": str(visit_date), "value": psa_val})

        return {
            "psa_series": psa_series,
            "psa_current": psa_series[-1]["value"] if psa_series else (followups[-1].get("psa_current") if followups else None),
            "psadt_months": prior.get("psadt_months") or prior.get("psa_doubling_time"),
            "psa_velocity": prior.get("psa_velocity"),
            "psa_nadir": prior.get("psa_nadir"),
        }

    @classmethod
    def _pathology(cls, baseline: dict, prior: dict) -> dict[str, Any]:
        return {
            "gleason_score": baseline.get("gleason_score", ""),
            "isup_grade_group": baseline.get("isup_grade_group", ""),
            "histology": baseline.get("histology", "Adenocarcinoma acinar"),
            "tnm_clinical": f"cT{baseline.get('clinical_t', '?')} cN{baseline.get('clinical_n', '?')} cM{baseline.get('clinical_m', '?')}",
            "tnm_pathological": f"pT{baseline.get('pathological_t', '?')} pN{baseline.get('pathological_n', '?')}" if baseline.get("pathological_t") else "",
            "surgical_margins": prior.get("surgical_margins", ""),
            "perineural_invasion": baseline.get("perineural_invasion", ""),
            "lymphovascular_invasion": baseline.get("lymphovascular_invasion", ""),
            "percent_positive_cores": baseline.get("percent_positive_cores", ""),
            "cribriform_pattern": baseline.get("cribriform_pattern", ""),
            "intraductal_carcinoma": baseline.get("intraductal_carcinoma", ""),
        }

    @classmethod
    def _imaging(cls, baseline: dict, prior: dict, followups: list) -> dict[str, Any]:
        return {
            "psma_pet": prior.get("psma_pet_result") or baseline.get("psma_pet_result", ""),
            "psma_pet_date": prior.get("psma_pet_date", ""),
            "bone_scan": prior.get("bone_scan_result") or baseline.get("bone_scan_result", ""),
            "ct_result": prior.get("ct_result") or baseline.get("ct_result", ""),
            "mri_result": prior.get("mri_result") or baseline.get("prostate_mri_result", ""),
            "mri_pirads": baseline.get("pirads_score", ""),
            "bone_lesion_count": prior.get("bone_lesion_count"),
            "metastasis_sites": prior.get("metastasis_sites", ""),
            "visceral_metastasis": prior.get("visceral_metastasis", False),
        }

    @classmethod
    def _genomic_profile(cls, genomic: dict) -> dict[str, Any]:
        if not genomic:
            return {"available": False}
        return {
            "available": True,
            "brca2": genomic.get("brca2_status", ""),
            "brca1": genomic.get("brca1_status", ""),
            "atm": genomic.get("atm_status", ""),
            "msh2_msh6": genomic.get("mmr_status", ""),
            "cdk12": genomic.get("cdk12_status", ""),
            "pten_loss": genomic.get("pten_loss", ""),
            "tp53": genomic.get("tp53_status", ""),
            "rb1": genomic.get("rb1_status", ""),
            "ar_amplification": genomic.get("ar_amplification", ""),
            "tmb": genomic.get("tmb_score", ""),
            "msi_status": genomic.get("msi_status", ""),
            "ctdna_detected": genomic.get("ctdna_detected", ""),
            "actionable_alterations": cls._identify_actionable(genomic),
        }

    @staticmethod
    def _identify_actionable(genomic: dict) -> list[str]:
        actionable: list[str] = []
        hrr_genes = ["brca2", "brca1", "atm", "palb2", "chek2", "rad51"]
        for gene in hrr_genes:
            status = genomic.get(f"{gene}_status", "")
            if status and "pathogenic" in str(status).lower():
                actionable.append(f"{gene.upper()} → PARPi (olaparib, rucaparib)")

        if str(genomic.get("msi_status") or "").lower() in ("msi-h", "high"):
            actionable.append("MSI-H → Pembrolizumab (KEYNOTE-158)")

        if genomic.get("tmb_score"):
            try:
                if float(genomic["tmb_score"]) >= 10:
                    actionable.append("TMB ≥10 → Pembrolizumab")
            except (ValueError, TypeError):
                pass

        psma = genomic.get("psma_expression", "")
        if psma and "positive" in str(psma).lower():
            actionable.append("PSMA+ → Lu-177 PSMA (VISION)")

        return actionable

    @classmethod
    def _current_status(cls, assessment: dict, followups: list, prior: dict) -> dict[str, Any]:
        last_fu = followups[-1] if followups else {}
        return {
            "clinical_state": assessment.get("state", "No clasificado"),
            "ecog": last_fu.get("ecog_current") or prior.get("ecog"),
            "psa_current": last_fu.get("psa_current"),
            "current_treatment": prior.get("current_treatment", ""),
            "treatment_line": prior.get("treatment_line", 1),
            "testosterone_current": last_fu.get("testosterone_current"),
            "hemoglobin_current": last_fu.get("hemoglobin_current"),
            "ldh_current": last_fu.get("ldh_current"),
            "alp_current": last_fu.get("alp_current"),
            "pain_score": last_fu.get("pain_score"),
        }

    @classmethod
    def _discussion_points(cls, assessment: dict, prior: dict, baseline: dict, genomic: dict) -> list[str]:
        points: list[str] = []
        state = assessment.get("state", "")

        if "diagnostic" in state or "localized" in state:
            points.append("Discusión de opciones de tratamiento primario (RP vs RT vs vigilancia activa)")
            gleason = baseline.get("gleason_score", "")
            if gleason and ("4+3" in str(gleason) or "8" in str(gleason) or "9" in str(gleason) or "10" in str(gleason)):
                points.append("Considerar terapia multimodal dado alto grado histológico")

        if "bcr" in state or "recurrence" in state:
            points.append("Evaluación de rescate: RT de rescate vs terapia sistémica")
            points.append("Indicación de PSMA-PET para re-estadificación")

        if "crpc" in state:
            points.append("Selección de siguiente línea de tratamiento en CRPC")
            if genomic and cls._identify_actionable(genomic):
                points.append("Discusión de opciones de medicina de precisión basadas en perfil genómico")

        if "metastatic" in state or "m1" in state or "mhspc" in state:
            points.append("Evaluación de volumen/extensión de enfermedad metastásica")
            points.append("Estrategia de intensificación (triplete vs doblete)")

        if prior.get("prior_docetaxel") and prior.get("prior_abiraterone") and prior.get("prior_enzalutamide"):
            points.append("Paciente con múltiples líneas previas — opciones restantes limitadas")
            points.append("Considerar ensayos clínicos y/o cuidados paliativos")

        if not points:
            points.append("Revisar plan de seguimiento y manejo actual")

        return points
