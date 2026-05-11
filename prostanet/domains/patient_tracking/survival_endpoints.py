# -*- coding: utf-8 -*-
"""
Módulo de endpoints de supervivencia estandarizados para cáncer de próstata.

Captura y cálculo de endpoints duros (OS, rPFS, MFS, BCR-FS, TTPP,
TTSRE, tiempo a CRPC, tiempo a siguiente línea) para análisis
epidemiológico real, curvas Kaplan-Meier y comparación con datos publicados.

Referencia:
  PCWG3 (Scher HI et al. J Clin Oncol 2016)
  ICECaP Working Group (Sweeney et al. J Clin Oncol 2015)
  NCCN 2026 Prostate Cancer (Endpoints and Follow-up)
  EAU 2026 Follow-up Protocols
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── Constantes ───────────────────────────────────────────────────────────────

ENDPOINT_TYPES = (
    "OS",              # Overall Survival
    "rPFS",            # Radiographic Progression-Free Survival
    "MFS",             # Metastasis-Free Survival (para localizado / m0 CRPC)
    "TTR",             # Time to Recurrence / relapse after local therapy
    "BCR_FS",          # Biochemical Recurrence-Free Survival
    "TTPP",            # Time to PSA Progression
    "TTSRE",           # Time to First Skeletal-Related Event
    "time_to_crpc",    # Time to Castration Resistance
    "time_to_next_line",  # Time to Next Treatment Line
)

CAUSE_OF_DEATH_OPTIONS = (
    "prostate_cancer",
    "other_cancer",
    "cardiovascular",
    "infection",
    "treatment_related",
    "other",
    "unknown",
)

VITAL_STATUS_OPTIONS = ("alive", "deceased", "lost_to_followup")

# Medianas publicadas de referencia para contextualizar
PUBLISHED_MEDIANS = {
    "OS_mCRPC_post_docetaxel": {"median_months": 15.1, "reference": "TROPIC (cabazitaxel)", "year": 2010},
    "OS_mCRPC_enzalutamide": {"median_months": 18.4, "reference": "AFFIRM", "year": 2012},
    "OS_mHSPC_ADT_alone": {"median_months": 44.0, "reference": "CHAARTED (ADT alone)", "year": 2015},
    "OS_mHSPC_ADT_docetaxel": {"median_months": 57.6, "reference": "CHAARTED (high volume)", "year": 2015},
    "OS_mHSPC_triplet": {"median_months": "NR", "reference": "ARASENS (ADT+D+Daro)", "year": 2022},
    "rPFS_enzalutamide_mCRPC": {"median_months": 20.0, "reference": "PREVAIL", "year": 2014},
    "MFS_enzalutamide_m0CRPC": {"median_months": 36.6, "reference": "PROSPER", "year": 2018},
    "MFS_apalutamide_m0CRPC": {"median_months": 40.5, "reference": "SPARTAN", "year": 2018},
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SurvivalEndpoint:
    """Endpoint de supervivencia individual calculado o registrado."""
    endpoint_type: str       # una de ENDPOINT_TYPES
    patient_id: int | None = None
    start_event: str = ""    # "diagnosis", "treatment_start", "adt_start", "metastatic_diagnosis", "line_start"
    start_date: str = ""
    end_event: str | None = None  # "death", "radiographic_progression", "metastasis", "psa_progression", "first_sre", "crpc_confirmed", "next_line_start"
    end_date: str | None = None
    censored: bool = True    # True si el evento no ha ocurrido
    duration_months: float | None = None
    cause_detail: str = ""   # para OS: una de CAUSE_OF_DEATH_OPTIONS
    treatment_context: str = ""  # tratamiento activo al momento del endpoint
    line_of_therapy: int | None = None
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SurvivalStatus:
    """Estado de supervivencia completo de un paciente con todos los endpoints."""
    patient_id: int | None = None
    vital_status: str = "alive"       # una de VITAL_STATUS_OPTIONS
    date_of_death: str | None = None
    cause_of_death: str | None = None  # una de CAUSE_OF_DEATH_OPTIONS
    last_contact_date: str = ""
    last_contact_status: str = ""      # "clinic_visit", "phone", "lab_result", "imaging"
    endpoints: list[SurvivalEndpoint] = field(default_factory=list)
    active_endpoints: dict[str, str] = field(default_factory=dict)  # endpoint_type → status ("ongoing"/"reached"/"censored")
    published_context: dict[str, Any] = field(default_factory=dict)  # medianas publicadas para comparación

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["endpoints"] = [e.to_dict() for e in self.endpoints]
        return d


# ── Funciones auxiliares ─────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _months_between(d1: date, d2: date) -> float:
    return round((d2 - d1).days / 30.44, 1)


def _merge_canonical_survival_context(patient: dict[str, Any]) -> dict[str, Any]:
    merged = dict(patient)
    identity = patient.get("identity") or {}
    bcr = patient.get("bcr") or {}
    surgery = patient.get("surgery") or {}
    radiation = patient.get("radiation") or []
    if isinstance(radiation, dict):
        radiation = [radiation]
    treatments = patient.get("treatments") or []
    latest_treatment = treatments[-1] if treatments else {}
    next_treatment = treatments[1] if len(treatments) > 1 else {}
    for field in ("id", "nss", "diagnosis_date", "vital_status", "date_of_death", "cause_of_death", "last_contact_date", "last_contact_status", "death_source"):
        if identity.get(field) not in (None, ""):
            merged[field if field != "id" else "patient_id"] = identity.get(field)
    if bcr:
        merged.setdefault("bcr_date", bcr.get("bcr_date"))
        merged.setdefault("biochemical_recurrence_date", bcr.get("bcr_date"))
        merged.setdefault("psa_progression_date", bcr.get("bcr_date"))
    if surgery:
        merged.setdefault("surgery_date", surgery.get("surgery_date"))
        merged.setdefault("local_therapy_date", surgery.get("surgery_date"))
    if radiation:
        latest_radiation = radiation[-1]
        merged.setdefault("rt_end_date", latest_radiation.get("rt_end_date") or latest_radiation.get("rt_date") or latest_radiation.get("rt_start_date"))
        merged.setdefault("local_therapy_date", latest_radiation.get("rt_end_date") or latest_radiation.get("rt_date") or latest_radiation.get("rt_start_date"))
    if latest_treatment:
        merged.setdefault("treatment_start_date", latest_treatment.get("start_date"))
        merged.setdefault("current_line_start_date", latest_treatment.get("start_date"))
        merged.setdefault("line_of_therapy", latest_treatment.get("line_of_therapy") or latest_treatment.get("line_of_therapy_number"))
    if next_treatment:
        merged.setdefault("next_line_start_date", next_treatment.get("start_date"))
    status = patient.get("survival_status_detail") or {}
    if isinstance(status, dict):
        for field in ("vital_status", "date_of_death", "cause_of_death", "last_contact_date", "last_contact_status", "death_source"):
            if status.get(field) not in (None, ""):
                merged[field] = status.get(field)
    for anchor in patient.get("survival_anchor_events") or []:
        if not isinstance(anchor, dict):
            continue
        anchor_type = str(anchor.get("anchor_type") or "")
        anchor_date = anchor.get("anchor_date")
        if not anchor_date:
            continue
        if anchor_type == "treatment_start":
            merged.setdefault("treatment_start_date", anchor_date)
            merged.setdefault("current_line_start_date", anchor_date)
        elif anchor_type == "radiographic_progression":
            merged.setdefault("radiographic_progression_date", anchor_date)
        elif anchor_type == "metastasis":
            merged.setdefault("metastatic_diagnosis_date", anchor_date)
            merged.setdefault("first_metastasis_date", anchor_date)
        elif anchor_type == "psa_progression":
            merged.setdefault("psa_progression_date", anchor_date)
            merged.setdefault("biochemical_recurrence_date", anchor_date)
        elif anchor_type == "first_sre":
            merged.setdefault("first_sre_date", anchor_date)
        elif anchor_type == "crpc_confirmed":
            merged.setdefault("crpc_confirmation_date", anchor_date)
        elif anchor_type == "next_line_start":
            merged.setdefault("next_line_start_date", anchor_date)
        elif anchor_type == "death":
            merged.setdefault("date_of_death", anchor_date)
    return merged


# ── Servicio principal ───────────────────────────────────────────────────────

class SurvivalEndpointService:
    """Servicio de endpoints de supervivencia con cálculo automático y generación Kaplan-Meier."""

    @staticmethod
    def compute_os(patient: dict[str, Any]) -> SurvivalEndpoint:
        """Calcula Overall Survival desde diagnóstico."""
        diagnosis_date = _parse_date(patient.get("diagnosis_date"))
        vital_status = patient.get("vital_status", "alive")
        death_date = _parse_date(patient.get("date_of_death"))

        if not diagnosis_date:
            return SurvivalEndpoint(
                endpoint_type="OS",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                censored=True,
                evidence_tags=["PCWG3 Scher 2016"],
            )

        if vital_status == "deceased" and death_date:
            duration = _months_between(diagnosis_date, death_date)
            return SurvivalEndpoint(
                endpoint_type="OS",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="diagnosis",
                start_date=diagnosis_date.isoformat(),
                end_event="death",
                end_date=death_date.isoformat(),
                censored=False,
                duration_months=duration,
                cause_detail=patient.get("cause_of_death", "unknown"),
                evidence_tags=["PCWG3 Scher 2016", "ICECaP"],
            )

        # Censurado: paciente vivo
        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(diagnosis_date, last_contact)
        return SurvivalEndpoint(
            endpoint_type="OS",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="diagnosis",
            start_date=diagnosis_date.isoformat(),
            end_event=None,
            end_date=last_contact.isoformat(),
            censored=True,
            duration_months=duration,
            evidence_tags=["PCWG3 Scher 2016", "ICECaP"],
        )

    @staticmethod
    def compute_rpfs(patient: dict[str, Any], treatment_start_date: str = "") -> SurvivalEndpoint | None:
        """Calcula Radiographic Progression-Free Survival desde inicio de tratamiento."""
        start = _parse_date(treatment_start_date or patient.get("treatment_start_date") or patient.get("current_line_start_date"))
        if not start:
            return None

        # Buscar progresión radiográfica
        progression_date = _parse_date(patient.get("radiographic_progression_date"))
        death_date = _parse_date(patient.get("date_of_death"))

        end_event = None
        end_date = None
        censored = True

        if progression_date:
            end_event = "radiographic_progression"
            end_date = progression_date
            censored = False
        elif death_date:
            end_event = "death"
            end_date = death_date
            censored = False

        if censored:
            end_date = _parse_date(patient.get("last_contact_date")) or date.today()

        duration = _months_between(start, end_date) if end_date else None

        return SurvivalEndpoint(
            endpoint_type="rPFS",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="treatment_start",
            start_date=start.isoformat(),
            end_event=end_event,
            end_date=end_date.isoformat() if end_date else None,
            censored=censored,
            duration_months=duration,
            treatment_context=patient.get("current_treatment", ""),
            evidence_tags=["PCWG3 rPFS definition", "NCCN 2026"],
        )

    @staticmethod
    def compute_mfs(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Calcula Metastasis-Free Survival (para enfermedad localizada / m0 CRPC)."""
        diagnosis_date = _parse_date(patient.get("diagnosis_date"))
        if not diagnosis_date:
            return None

        metastasis_date = _parse_date(patient.get("metastatic_diagnosis_date") or patient.get("first_metastasis_date"))
        death_date = _parse_date(patient.get("date_of_death"))

        end_event = None
        end_date = None
        censored = True

        if metastasis_date:
            end_event = "metastasis"
            end_date = metastasis_date
            censored = False
        elif death_date:
            end_event = "death"
            end_date = death_date
            censored = False

        if censored:
            end_date = _parse_date(patient.get("last_contact_date")) or date.today()

        duration = _months_between(diagnosis_date, end_date) if end_date else None

        return SurvivalEndpoint(
            endpoint_type="MFS",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="diagnosis",
            start_date=diagnosis_date.isoformat(),
            end_event=end_event,
            end_date=end_date.isoformat() if end_date else None,
            censored=censored,
            duration_months=duration,
            evidence_tags=["PROSPER MFS endpoint", "SPARTAN MFS endpoint", "ICECaP"],
        )

    @staticmethod
    def compute_bcr_fs(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Calcula Biochemical Recurrence-Free Survival desde tratamiento local."""
        treatment_date = _parse_date(
            patient.get("surgery_date") or patient.get("rt_end_date") or patient.get("local_therapy_date")
        )
        if not treatment_date:
            return None

        bcr_date = _parse_date(patient.get("bcr_date") or patient.get("biochemical_recurrence_date"))

        if bcr_date:
            duration = _months_between(treatment_date, bcr_date)
            return SurvivalEndpoint(
                endpoint_type="BCR_FS",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="local_treatment",
                start_date=treatment_date.isoformat(),
                end_event="biochemical_recurrence",
                end_date=bcr_date.isoformat(),
                censored=False,
                duration_months=duration,
                evidence_tags=["NCCN 2026 BCR definition", "EAU 2026 BCR"],
            )

        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(treatment_date, last_contact)
        return SurvivalEndpoint(
            endpoint_type="BCR_FS",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="local_treatment",
            start_date=treatment_date.isoformat(),
            end_event=None,
            end_date=last_contact.isoformat(),
            censored=True,
            duration_months=duration,
            evidence_tags=["NCCN 2026 BCR definition"],
        )

    @staticmethod
    def compute_ttr(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Alias clínico explícito de tiempo a recurrencia tras tratamiento local."""
        bcr_fs = SurvivalEndpointService.compute_bcr_fs(patient)
        if not bcr_fs:
            return None
        payload = bcr_fs.to_dict()
        payload["endpoint_type"] = "TTR"
        payload["evidence_tags"] = list(payload.get("evidence_tags") or []) + ["ICECaP surrogate framing"]
        return SurvivalEndpoint(**payload)

    @staticmethod
    def compute_ttpp(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Calcula Time to PSA Progression según PCWG3."""
        start = _parse_date(patient.get("treatment_start_date") or patient.get("current_line_start_date"))
        if not start:
            return None

        psa_progression_date = _parse_date(patient.get("psa_progression_date"))

        if psa_progression_date:
            duration = _months_between(start, psa_progression_date)
            return SurvivalEndpoint(
                endpoint_type="TTPP",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="treatment_start",
                start_date=start.isoformat(),
                end_event="psa_progression",
                end_date=psa_progression_date.isoformat(),
                censored=False,
                duration_months=duration,
                evidence_tags=["PCWG3 PSA progression criteria"],
            )

        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(start, last_contact)
        return SurvivalEndpoint(
            endpoint_type="TTPP",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="treatment_start",
            start_date=start.isoformat(),
            censored=True,
            duration_months=duration,
            end_date=last_contact.isoformat(),
            evidence_tags=["PCWG3 PSA progression criteria"],
        )

    @staticmethod
    def compute_ttsre(patient: dict[str, Any], sre_profile: dict[str, Any] | None = None) -> SurvivalEndpoint | None:
        """Calcula Time to First Skeletal-Related Event."""
        start = _parse_date(patient.get("metastatic_diagnosis_date") or patient.get("diagnosis_date"))
        if not start:
            return None

        first_sre_months = None
        first_sre_date_str = None

        first_sre_date = _parse_date(patient.get("first_sre_date"))
        if first_sre_date:
            first_sre_date_str = first_sre_date.isoformat()
            first_sre_months = _months_between(start, first_sre_date)

        if sre_profile:
            first_sre_months = sre_profile.get("time_to_first_sre_months")
            sre_events = sre_profile.get("sre_events", [])
            if sre_events and isinstance(sre_events, list):
                dates = [_parse_date(e.get("event_date")) if isinstance(e, dict) else None for e in sre_events]
                valid_dates = [d for d in dates if d is not None]
                if valid_dates:
                    first_sre_date = min(valid_dates)
                    first_sre_date_str = first_sre_date.isoformat()
                    first_sre_months = _months_between(start, first_sre_date)

        if first_sre_months is not None and first_sre_date_str:
            return SurvivalEndpoint(
                endpoint_type="TTSRE",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="metastatic_diagnosis",
                start_date=start.isoformat(),
                end_event="first_sre",
                end_date=first_sre_date_str,
                censored=False,
                duration_months=first_sre_months,
                evidence_tags=["Denosumab 103 trial", "Zoledronic acid 039"],
            )

        # Censurado
        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(start, last_contact)
        return SurvivalEndpoint(
            endpoint_type="TTSRE",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="metastatic_diagnosis",
            start_date=start.isoformat(),
            censored=True,
            duration_months=duration,
            end_date=last_contact.isoformat(),
            evidence_tags=["Denosumab 103 trial"],
        )

    @staticmethod
    def compute_time_to_crpc(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Calcula tiempo desde inicio de ADT hasta resistencia a la castración."""
        adt_start = _parse_date(patient.get("adt_start_date"))
        if not adt_start:
            return None

        crpc_date = _parse_date(patient.get("crpc_confirmation_date") or patient.get("castration_resistance_date"))

        if crpc_date:
            duration = _months_between(adt_start, crpc_date)
            return SurvivalEndpoint(
                endpoint_type="time_to_crpc",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="adt_start",
                start_date=adt_start.isoformat(),
                end_event="crpc_confirmed",
                end_date=crpc_date.isoformat(),
                censored=False,
                duration_months=duration,
                evidence_tags=["NCCN 2026 CRPC definition", "EAU 2026 CRPC"],
            )

        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(adt_start, last_contact)
        return SurvivalEndpoint(
            endpoint_type="time_to_crpc",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="adt_start",
            start_date=adt_start.isoformat(),
            censored=True,
            duration_months=duration,
            end_date=last_contact.isoformat(),
            evidence_tags=["NCCN 2026 CRPC definition"],
        )

    @staticmethod
    def compute_time_to_next_line(patient: dict[str, Any]) -> SurvivalEndpoint | None:
        """Calcula tiempo desde inicio de línea actual hasta inicio de siguiente línea."""
        current_start = _parse_date(patient.get("current_line_start_date"))
        next_start = _parse_date(patient.get("next_line_start_date"))

        if not current_start:
            return None

        if next_start:
            duration = _months_between(current_start, next_start)
            return SurvivalEndpoint(
                endpoint_type="time_to_next_line",
                patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
                start_event="line_start",
                start_date=current_start.isoformat(),
                end_event="next_line_start",
                end_date=next_start.isoformat(),
                censored=False,
                duration_months=duration,
                line_of_therapy=_safe_int(patient.get("line_of_therapy")),
                evidence_tags=["NCCN 2026 treatment sequencing"],
            )

        last_contact = _parse_date(patient.get("last_contact_date")) or date.today()
        duration = _months_between(current_start, last_contact)
        return SurvivalEndpoint(
            endpoint_type="time_to_next_line",
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            start_event="line_start",
            start_date=current_start.isoformat(),
            censored=True,
            duration_months=duration,
            end_date=last_contact.isoformat(),
            line_of_therapy=_safe_int(patient.get("line_of_therapy")),
            evidence_tags=["NCCN 2026"],
        )

    @staticmethod
    def compute_endpoints(patient: dict[str, Any], state: str) -> SurvivalStatus:
        """Calcula todos los endpoints aplicables según el estado clínico."""
        patient = _merge_canonical_survival_context(patient)
        endpoints: list[SurvivalEndpoint] = []
        active_endpoints: dict[str, str] = {}

        # OS — siempre aplicable
        os_ep = SurvivalEndpointService.compute_os(patient)
        endpoints.append(os_ep)
        active_endpoints["OS"] = "reached" if not os_ep.censored else "ongoing"

        # BCR-FS — para estados post-tratamiento local
        if state in ("post_prostatectomy", "recurrence_bcr", "localized_initial"):
            ttr_ep = SurvivalEndpointService.compute_ttr(patient)
            if ttr_ep:
                endpoints.append(ttr_ep)
                active_endpoints["TTR"] = "reached" if not ttr_ep.censored else "ongoing"
            bcr_ep = SurvivalEndpointService.compute_bcr_fs(patient)
            if bcr_ep:
                endpoints.append(bcr_ep)
                active_endpoints["BCR_FS"] = "reached" if not bcr_ep.censored else "ongoing"

        # MFS — para enfermedad localizada y m0 CRPC
        if state in ("localized_initial", "post_prostatectomy", "recurrence_bcr", "m0_crpc"):
            mfs_ep = SurvivalEndpointService.compute_mfs(patient)
            if mfs_ep:
                endpoints.append(mfs_ep)
                active_endpoints["MFS"] = "reached" if not mfs_ep.censored else "ongoing"

        # rPFS — para enfermedad avanzada bajo tratamiento
        advanced_states = {
            "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m0_crpc", "m1_crpc",
        }
        if state in advanced_states:
            rpfs_ep = SurvivalEndpointService.compute_rpfs(patient)
            if rpfs_ep:
                endpoints.append(rpfs_ep)
                active_endpoints["rPFS"] = "reached" if not rpfs_ep.censored else "ongoing"

        # TTPP — para enfermedad bajo tratamiento sistémico
        if state in advanced_states:
            ttpp_ep = SurvivalEndpointService.compute_ttpp(patient)
            if ttpp_ep:
                endpoints.append(ttpp_ep)
                active_endpoints["TTPP"] = "reached" if not ttpp_ep.censored else "ongoing"

        # TTSRE — para enfermedad metastásica
        metastatic_states = {
            "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "m1_crpc",
        }
        if state in metastatic_states:
            sre_profile = patient.get("skeletal_event_profile") or patient.get("sre_profile")
            if isinstance(sre_profile, dict):
                ttsre_ep = SurvivalEndpointService.compute_ttsre(patient, sre_profile)
            else:
                ttsre_ep = SurvivalEndpointService.compute_ttsre(patient)
            if ttsre_ep:
                endpoints.append(ttsre_ep)
                active_endpoints["TTSRE"] = "reached" if not ttsre_ep.censored else "ongoing"

        # Tiempo a CRPC — para enfermedad bajo ADT
        adt_states = {
            "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume", "adt_progression_verification",
        }
        if state in adt_states:
            crpc_ep = SurvivalEndpointService.compute_time_to_crpc(patient)
            if crpc_ep:
                endpoints.append(crpc_ep)
                active_endpoints["time_to_crpc"] = "reached" if not crpc_ep.censored else "ongoing"

        # Tiempo a siguiente línea — para enfermedad avanzada
        if state in advanced_states:
            next_line_ep = SurvivalEndpointService.compute_time_to_next_line(patient)
            if next_line_ep:
                endpoints.append(next_line_ep)
                active_endpoints["time_to_next_line"] = "reached" if not next_line_ep.censored else "ongoing"

        # Published context
        published_context = {}
        if state in metastatic_states:
            for key, ref in PUBLISHED_MEDIANS.items():
                published_context[key] = ref

        return SurvivalStatus(
            patient_id=_safe_int(patient.get("patient_id") or patient.get("nss")),
            vital_status=patient.get("vital_status", "alive"),
            date_of_death=patient.get("date_of_death"),
            cause_of_death=patient.get("cause_of_death"),
            last_contact_date=patient.get("last_contact_date", date.today().isoformat()),
            last_contact_status=patient.get("last_contact_status", ""),
            endpoints=endpoints,
            active_endpoints=active_endpoints,
            published_context=published_context,
        )

    @staticmethod
    def generate_kaplan_meier_points(
        endpoint_list: list[dict[str, Any]],
        endpoint_type: str,
    ) -> dict[str, Any]:
        """
        Genera puntos para curva Kaplan-Meier a partir de una lista de endpoints de pacientes.

        Args:
            endpoint_list: Lista de dicts con 'duration_months' y 'censored'
            endpoint_type: Tipo de endpoint para etiqueta

        Returns:
            Dict con times[], survival_probs[], n_at_risk[], events[], censored_times[],
            median_survival, ci_95_lower, ci_95_upper
        """
        # Filtrar endpoints válidos
        valid = [
            e for e in endpoint_list
            if e.get("duration_months") is not None and e["duration_months"] >= 0
        ]
        if not valid:
            return {
                "endpoint_type": endpoint_type,
                "times": [],
                "survival_probs": [],
                "n_at_risk": [],
                "events": [],
                "censored_times": [],
                "median_survival": None,
                "total_patients": 0,
                "total_events": 0,
            }

        # Ordenar por tiempo
        sorted_eps = sorted(valid, key=lambda x: x["duration_months"])
        n = len(sorted_eps)

        times = [0.0]
        survival_probs = [1.0]
        n_at_risk_list = [n]
        events_list: list[int] = [0]
        censored_times: list[float] = []

        current_survival = 1.0
        at_risk = n
        total_events = 0

        i = 0
        while i < len(sorted_eps):
            t = sorted_eps[i]["duration_months"]
            # Contar censuras antes de este tiempo
            # Contar eventos y censuras en este tiempo
            events_at_t = 0
            censored_at_t = 0
            while i < len(sorted_eps) and sorted_eps[i]["duration_months"] == t:
                if sorted_eps[i].get("censored", True):
                    censored_at_t += 1
                    censored_times.append(t)
                else:
                    events_at_t += 1
                i += 1

            if events_at_t > 0 and at_risk > 0:
                current_survival *= (1 - events_at_t / at_risk)
                times.append(t)
                survival_probs.append(round(current_survival, 4))
                n_at_risk_list.append(at_risk)
                events_list.append(events_at_t)
                total_events += events_at_t

            at_risk -= (events_at_t + censored_at_t)

        # Calcular mediana
        median_survival = None
        for j, prob in enumerate(survival_probs):
            if prob <= 0.5:
                median_survival = times[j]
                break

        return {
            "endpoint_type": endpoint_type,
            "times": times,
            "survival_probs": survival_probs,
            "n_at_risk": n_at_risk_list,
            "events": events_list,
            "censored_times": censored_times,
            "median_survival": median_survival,
            "total_patients": n,
            "total_events": total_events,
        }

    @staticmethod
    def evaluate_survival_alerts(
        patient_id: int,
        status: SurvivalStatus,
    ) -> list[dict[str, Any]]:
        """Genera alertas clínicas basadas en endpoints de supervivencia."""
        from prostanet.domains.patient_tracking.alert_engine import ClinicalAlert

        alerts: list[ClinicalAlert] = []

        for endpoint in status.endpoints:
            if endpoint.censored:
                continue

            # rPFS alcanzado
            if endpoint.endpoint_type == "rPFS" and endpoint.end_event == "radiographic_progression":
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_rpfs_reached",
                    severity="critical",
                    category="survival_endpoint",
                    title=f"rPFS alcanzado: {endpoint.duration_months:.1f} meses",
                    message="Progresión radiográfica confirmada. Se requiere re-estadificación y discusión de siguiente línea terapéutica.",
                    recommended_action="1) Re-estadificación completa (PSMA-PET si disponible). 2) Panel molecular si no realizado. 3) Tumor board para siguiente línea.",
                    guideline_reference="PCWG3 rPFS definition; NCCN 2026 next-line",
                    triggering_value=f"{endpoint.duration_months:.1f} meses",
                    threshold="Progresión radiográfica",
                ))

            # TTPP alcanzado
            if endpoint.endpoint_type == "TTPP" and endpoint.end_event == "psa_progression":
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_ttpp_reached",
                    severity="warning",
                    category="survival_endpoint",
                    title=f"Progresión bioquímica PSA: {endpoint.duration_months:.1f} meses",
                    message="Progresión de PSA confirmada según criterios PCWG3. Considerar imagen de re-estadificación.",
                    recommended_action="Solicitar imagen (PSMA-PET preferible) para confirmar/descartar progresión radiográfica.",
                    guideline_reference="PCWG3 PSA progression criteria",
                    triggering_value=f"{endpoint.duration_months:.1f} meses",
                    threshold="PSA progression PCWG3",
                ))

            # BCR-FS < 12 meses
            if endpoint.endpoint_type == "BCR_FS" and endpoint.duration_months is not None and endpoint.duration_months < 12:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_early_bcr",
                    severity="warning",
                    category="survival_endpoint",
                    title=f"Recurrencia bioquímica temprana: {endpoint.duration_months:.1f} meses post-tratamiento",
                    message="BCR dentro de los primeros 12 meses sugiere biología agresiva.",
                    recommended_action="Considerar intensificación de seguimiento. PSMA-PET para re-estadificación. Referir a tumor board.",
                    guideline_reference="NCCN 2026 BCR early recurrence; EAU 2026",
                    triggering_value=f"{endpoint.duration_months:.1f} meses",
                    threshold="<12 meses post-tratamiento",
                ))

            # Tiempo a CRPC < 12 meses
            if endpoint.endpoint_type == "time_to_crpc" and endpoint.duration_months is not None and endpoint.duration_months < 12:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_rapid_crpc",
                    severity="critical",
                    category="survival_endpoint",
                    title=f"Resistencia rápida a castración: {endpoint.duration_months:.1f} meses",
                    message="Progresión a CRPC en <12 meses desde inicio de ADT indica biología primariamente resistente.",
                    recommended_action="Referir urgente a tumor board. Considerar panel molecular (AR-V7, TP53, RB1). Evaluar transformación neuroendocrina.",
                    guideline_reference="NCCN 2026 CRPC; EAU 2026 rapid CRPC",
                    triggering_value=f"{endpoint.duration_months:.1f} meses",
                    threshold="<12 meses desde ADT",
                ))

        # MFS milestone positivo a 24 meses (m0 CRPC)
        for endpoint in status.endpoints:
            if endpoint.endpoint_type == "MFS" and endpoint.censored and endpoint.duration_months and endpoint.duration_months >= 24:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_mfs_milestone",
                    severity="info",
                    category="survival_endpoint",
                    title=f"Milestone MFS: {endpoint.duration_months:.0f} meses sin metástasis",
                    message="Paciente libre de metástasis a >24 meses. Señal pronóstica favorable.",
                    recommended_action="Mantener tratamiento actual. Considerar espaciar imagen si clínicamente estable.",
                    guideline_reference="PROSPER; SPARTAN; ICECaP MFS as surrogate",
                    triggering_value=f"{endpoint.duration_months:.0f} meses",
                    threshold="≥24 meses sin metástasis",
                ))

        # Perdido al seguimiento
        if status.vital_status == "lost_to_followup" or (
            status.last_contact_date
            and _parse_date(status.last_contact_date)
            and _months_between(_parse_date(status.last_contact_date), date.today()) > 6  # type: ignore
        ):
            last = _parse_date(status.last_contact_date)
            months_lost = _months_between(last, date.today()) if last else None
            if months_lost and months_lost > 6:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type="endpoint_lost_followup",
                    severity="warning",
                    category="survival_endpoint",
                    title=f"Perdido al seguimiento: {months_lost:.0f} meses",
                    message=f"Último contacto: {status.last_contact_date}. Sin datos en {months_lost:.0f} meses.",
                    recommended_action="Programar contacto telefónico. Verificar estatus vital en registro civil si aplica.",
                    guideline_reference="Buenas prácticas de seguimiento oncológico",
                    triggering_value=f"{months_lost:.0f} meses",
                    threshold=">6 meses sin contacto",
                ))

        return [a.to_dict() for a in alerts]

    @staticmethod
    def build_survival_summary_for_profile(status: SurvivalStatus) -> dict[str, Any]:
        """Construye resumen de supervivencia para mostrar en el perfil del paciente."""
        endpoint_summaries = []
        for ep in status.endpoints:
            type_labels = {
                "OS": "Supervivencia global (OS)",
                "rPFS": "SLP radiográfica (rPFS)",
                "MFS": "Supervivencia libre de metástasis (MFS)",
                "TTR": "Tiempo a recurrencia (TTR)",
                "BCR_FS": "Supervivencia libre de BCR",
                "TTPP": "Tiempo a progresión PSA",
                "TTSRE": "Tiempo a primer evento esquelético",
                "time_to_crpc": "Tiempo a resistencia a castración",
                "time_to_next_line": "Tiempo a siguiente línea",
            }
            status_label = "Censurado" if ep.censored else "Alcanzado"
            tone = "success" if ep.censored else "danger"

            endpoint_summaries.append({
                "type": ep.endpoint_type,
                "label": type_labels.get(ep.endpoint_type, ep.endpoint_type),
                "duration_months": ep.duration_months,
                "status": status_label,
                "end_event": ep.end_event,
                "tone": tone,
            })

        vital_tone = "success" if status.vital_status == "alive" else "danger" if status.vital_status == "deceased" else "warning"

        return {
            "vital_status": status.vital_status,
            "vital_tone": vital_tone,
            "date_of_death": status.date_of_death,
            "cause_of_death": status.cause_of_death,
            "last_contact_date": status.last_contact_date,
            "endpoints": endpoint_summaries,
            "active_endpoints": status.active_endpoints,
            "total_endpoints": len(status.endpoints),
            "events_reached": sum(1 for ep in status.endpoints if not ep.censored),
            "published_context": status.published_context,
        }
