# -*- coding: utf-8 -*-
"""EPIC 7 — Motor de matching a ensayos clínicos (catálogo local curado).

Fase 1 del plan: catálogo estructurado en Python con reglas de
elegibilidad ejecutables. Fase 2 (API ClinicalTrials.gov v2) queda fuera
de alcance — la interfaz ``TrialMatch`` es compatible con una ampliación
dinámica posterior.

Trials incluidos (todos NCCN/EAU-relevantes o pivotales):

- **Localized / BCR / mHSPC:** STAMPEDE-2, EMBARK, PRESTO.
- **mHSPC:** ARASENS, TITAN, ENZAMET, PEACE-1.
- **mCRPC precisión:** PROfound, PROpel, MAGNITUDE, TALAPRO-2,
  TALAPRO-3, AMPLITUDE, TRITON-3, KEYNOTE-158, KEYNOTE-199.
- **mCRPC radioligando:** VISION, PSMAfore.
- **mCRPC secuenciación:** CARD, AFFIRM, COU-AA-301/302, TAX 327,
  TROPIC, ALSYMPCA.
- **Transdiagnóstico:** IPATential150, CAPItello-281, PROPHECY.
- **NEPC:** EP-16 (Aparicio 2013) basalinha platino.

Referencias pivote: véase ``evidence_tags`` por ensayo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from prostanet.shared.advanced_support_normalizer import resolve_docetaxel_fit

logger = logging.getLogger(__name__)


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrialDefinition:
    """Definición curada de un ensayo con reglas de elegibilidad."""

    trial_code: str
    title_short: str
    nct_id: str
    disease_scope: tuple[str, ...]
    eligibility_rule: Callable[[dict[str, Any]], tuple[bool, list[str], list[str]]]
    evidence_tags: tuple[str, ...]
    primary_reference: str
    phase: str = ""
    status_summary: str = ""


@dataclass(frozen=True)
class TrialMatch:
    """Resultado estructurado por ensayo."""

    trial_code: str
    title_short: str
    nct_id: str
    disease_scope: list[str]
    match: bool
    match_reasons: list[str] = field(default_factory=list)
    ineligibility_reasons: list[str] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)
    primary_reference: str = ""
    phase: str = ""
    status_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_code": self.trial_code,
            "title_short": self.title_short,
            "nct_id": self.nct_id,
            "disease_scope": list(self.disease_scope),
            "match": self.match,
            "match_reasons": list(self.match_reasons),
            "ineligibility_reasons": list(self.ineligibility_reasons),
            "evidence_tags": list(self.evidence_tags),
            "primary_reference": self.primary_reference,
            "phase": self.phase,
            "status_summary": self.status_summary,
        }


# ── Helpers de lectura del paciente ────────────────────────────────────


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positive", "positivo", "detected"}


def _first_non_empty(patient: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        raw = patient.get(key)
        if raw not in (None, ""):
            return raw
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ecog(patient: dict[str, Any]) -> int | None:
    raw = _first_non_empty(patient, "ecog_score", "ecog", "performance_status")
    try:
        if raw in (None, ""):
            return None
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _disease_state(patient: dict[str, Any]) -> str:
    return str(_first_non_empty(patient, "state", "disease_state", "phenotype_state", "state_classification") or "").strip().lower()


def _has_hrr_positive(patient: dict[str, Any]) -> bool:
    if _is_truthy(patient.get("hrr_positive")):
        return True
    for key in ("germline_pathogenic_variant", "somatic_pathogenic_variant"):
        variant = str(patient.get(key) or "").strip().upper()
        if variant in {"BRCA1", "BRCA2", "ATM", "PALB2", "CHEK2", "CDK12", "FANCA", "RAD51B", "RAD51C", "RAD51D", "BARD1", "HRR"}:
            return True
    return False


def _has_brca_pathway(patient: dict[str, Any]) -> bool:
    for key in ("germline_pathogenic_variant", "somatic_pathogenic_variant"):
        variant = str(patient.get(key) or "").strip().upper()
        if variant in {"BRCA1", "BRCA2"}:
            return True
    return _is_truthy(patient.get("brca_pathway"))


def _has_msi_high(patient: dict[str, Any]) -> bool:
    return (
        _is_truthy(patient.get("msi_high"))
        or _is_truthy(patient.get("msi_status"))
        or _is_truthy(patient.get("dmmr_high_confidence"))
        or _is_truthy(patient.get("dmmr"))
    )


def _has_tmb_high(patient: dict[str, Any]) -> bool:
    raw = _safe_float(patient.get("tmb_value") or patient.get("tmb_mut_mb"))
    if raw is not None and raw >= 10:
        return True
    return _is_truthy(patient.get("tmb_high"))


def _prior_therapy(patient: dict[str, Any], key: str) -> bool:
    return _is_truthy(patient.get(key) or patient.get(f"prior_{key}"))


def _psma_positive(patient: dict[str, Any]) -> bool:
    if _is_truthy(patient.get("psma_positive")):
        return True
    suvmax = _safe_float(
        patient.get("psma_lesion_suvmax_minimum")
        or patient.get("psma_index_lesion_suvmax")
        or patient.get("psma_suvmax_max")
        or patient.get("psma_suvmax")
    )
    suv_liver = _safe_float(
        patient.get("psma_suvmean_liver")
        or patient.get("psma_liver_suv_reference")
    )
    if suvmax is not None and suv_liver is not None and suvmax >= suv_liver:
        return True
    return False


def _nepc_signal(patient: dict[str, Any]) -> bool:
    return (
        _is_truthy(patient.get("nepc_confirmed_histology"))
        or _is_truthy(patient.get("nepc_confirmed"))
        or _is_truthy(patient.get("nepc_suspected"))
    )


def _arv7_positive(patient: dict[str, Any]) -> bool:
    return _is_truthy(patient.get("ar_v7_positive"))


# ── Definiciones de ensayos ────────────────────────────────────────────


def _rule_stampede2(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state in {"localized_initial", "recurrence_bcr"} and str(patient.get("nccn_risk_group") or "").lower() in {"high", "very_high"}:
        reasons.append("Alto / muy alto riesgo localizado — cohorte de intensificación STAMPEDE-2.")
    if state.startswith("mcspc_"):
        reasons.append("mHSPC — candidato a intensificación con arm experimental.")
    if not reasons:
        issues.append("Requiere cáncer localizado alto riesgo o mHSPC.")
    return bool(reasons), reasons, issues


def _rule_stampede_classic(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """STAMPEDE clásico — plataforma James 2017-2022 brazos M1/M0 abi y doce.

    Cubre: (a) localized high/very-high risk con RT + ADT largo; (b) mHSPC todo
    volumen con ADT + abiraterona o ADT + docetaxel.
    """
    state = _disease_state(patient)
    risk = str(patient.get("nccn_risk_group") or "").lower()
    reasons: list[str] = []
    issues: list[str] = []
    if state == "localized_initial" and risk in {"high", "very_high"}:
        reasons.append("Localized high/very-high risk — STAMPEDE M0 brazo RT + ADT largo (James 2022).")
    if state.startswith("mcspc_"):
        reasons.append("mHSPC — STAMPEDE M1 brazos abiraterona (James NEJM 2017) y docetaxel (James Lancet 2016).")
    if state == "recurrence_bcr" and risk in {"high", "very_high"}:
        reasons.append("BCR alto riesgo elegible para intensificación STAMPEDE (extrapolación M0).")
    if not reasons:
        issues.append("STAMPEDE requiere localized high/very-high risk, BCR alto riesgo o mHSPC.")
    return bool(reasons), reasons, issues


def _rule_embark(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    psadt = _safe_float(patient.get("psa_doubling_time_months"))
    m_stage = str(patient.get("m_stage") or "").strip().upper()
    reasons: list[str] = []
    issues: list[str] = []
    if state != "recurrence_bcr":
        issues.append("EMBARK requiere BCR post-tratamiento local sin metástasis.")
    if m_stage and m_stage != "M0":
        issues.append(f"EMBARK requiere M0 confirmado (paciente: {m_stage}).")
    if psadt is None:
        issues.append("Falta PSA doubling time.")
    elif psadt > 9:
        issues.append("PSADT >9 meses no entra al criterio EMBARK.")
    else:
        reasons.append(f"BCR M0 con PSADT {psadt:.1f} meses (EMBARK ≤9 meses).")
    return bool(reasons) and not issues, reasons, issues


def _rule_arasens(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — `resolve_docetaxel_fit`
    # normaliza: "Apto (fit)" / "1" / "Sí" → True; "No apto" / "Marginal" / "0"
    # → False; "Desconocido" / vacío → False (conservador: no emitir docetaxel
    # sin documentación). Acepta alias legacy `taxane_fitness`, `fit_for_docetaxel`,
    # `chemotherapy_fitness`.
    docetaxel_fit = resolve_docetaxel_fit(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state in {"mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"} and docetaxel_fit:
        reasons.append("mHSPC alto volumen fit para docetaxel — base ARASENS triplete.")
    else:
        if not state.startswith("mcspc_high"):
            issues.append("ARASENS limitado a mHSPC de alto volumen.")
        if not docetaxel_fit:
            issues.append("Falta confirmar fitness para taxano.")
    return bool(reasons), reasons, issues


def _rule_titan(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    if state.startswith("mcspc_"):
        return True, ["mHSPC — TITAN evaluó apalutamida + ADT en todo el espectro."], []
    return False, [], ["TITAN requiere mHSPC."]


def _rule_peace1(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    if state in {"mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"}:
        return True, ["mHSPC alto volumen — PEACE-1 avaló abiraterona + ADT + docetaxel."], []
    return False, [], ["PEACE-1 relevante en mHSPC alto volumen."]


def _rule_profound(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("PROfound evaluó mCRPC post-ARPI.")
    if not _has_hrr_positive(patient):
        issues.append("Requiere alteración HRR confirmada.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("Requiere progresión tras abiraterona o enzalutamida.")
    if not issues:
        reasons.append("mCRPC HRR+ post-ARPI — cohorte PROfound.")
    return bool(reasons), reasons, issues


def _rule_propel(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("PROpel restringido a mCRPC 1L.")
    if _prior_therapy(patient, "prior_arpi") or _prior_therapy(patient, "prior_abiraterone"):
        issues.append("PROpel excluye ARPI previo.")
    if not issues:
        reasons.append("mCRPC 1L sin ARPI previo — candidato PROpel (olaparib + abiraterona).")
    return bool(reasons), reasons, issues


def _rule_magnitude(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("MAGNITUDE limitado a mCRPC 1L.")
    if not _has_brca_pathway(patient):
        issues.append("Requiere BRCA1/2 patogénica.")
    if (
        _prior_therapy(patient, "prior_abiraterone")
        or _prior_therapy(patient, "prior_apalutamide")
        or _prior_therapy(patient, "prior_arpi")
        or _prior_therapy(patient, "prior_enzalutamide")
        or _prior_therapy(patient, "prior_darolutamide")
    ):
        issues.append("MAGNITUDE excluye ARPI previo (abiraterona/apalutamida/enzalutamida/darolutamida) en cohorte 1L.")
    if not issues:
        reasons.append("mCRPC 1L BRCA+ sin ARPI previo — cohorte MAGNITUDE.")
    return bool(reasons), reasons, issues


def _rule_talapro2(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("TALAPRO-2 limitado a mCRPC 1L.")
    if _prior_therapy(patient, "prior_arpi") or _prior_therapy(patient, "prior_enzalutamide"):
        issues.append("TALAPRO-2 excluye enzalutamida previa.")
    if not issues:
        if _has_hrr_positive(patient):
            reasons.append(
                "mCRPC 1L HRR+ sin enzalutamida previa — TALAPRO-2 cohorte HRR+ "
                "(beneficio rPFS robusto con talazoparib + enzalutamida)."
            )
        else:
            reasons.append(
                "mCRPC 1L all-comers sin enzalutamida previa — TALAPRO-2 cohorte 1 "
                "(beneficio menor en HRR-, considerar perfil de toxicidad)."
            )
    return bool(reasons), reasons, issues


def _rule_talapro3(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if not state.startswith("mcspc_"):
        issues.append("TALAPRO-3 evalúa mHSPC.")
    if not _has_hrr_positive(patient):
        issues.append("Requiere HRR+ confirmada.")
    if not issues:
        reasons.append("mHSPC HRR+ — cohorte TALAPRO-3 (talazoparib + enzalutamida + ADT).")
    return bool(reasons), reasons, issues


def _rule_amplitude(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if not state.startswith("mcspc_"):
        issues.append("AMPLITUDE limitado a mHSPC 1L.")
    if not _has_brca_pathway(patient):
        issues.append("AMPLITUDE prioriza BRCA+.")
    if not issues:
        reasons.append("mHSPC 1L BRCA+ — candidato AMPLITUDE (niraparib + abiraterona).")
    return bool(reasons), reasons, issues


def _rule_triton3(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if _disease_state(patient) != "m1_crpc":
        issues.append("TRITON-3 es mCRPC post-ARPI.")
    if not _has_brca_pathway(patient) and not _has_hrr_positive(patient):
        issues.append("Requiere BRCA+ o ATM por IHC/secuenciación.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("Requiere ARPI previo.")
    if not issues:
        reasons.append("mCRPC BRCA/ATM+ post-ARPI — cohorte TRITON-3 (rucaparib).")
    return bool(reasons), reasons, issues


def _rule_keynote158(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if not (_has_msi_high(patient) or _has_tmb_high(patient)):
        issues.append("Requiere MSI-H/dMMR o TMB-H (≥10 mut/Mb).")
    else:
        if _has_msi_high(patient):
            reasons.append("MSI-H/dMMR — pembrolizumab aprobación tumor-agnóstica.")
        if _has_tmb_high(patient):
            reasons.append("TMB-H ≥10 mut/Mb — KEYNOTE-158 all-comer.")
    return bool(reasons), reasons, issues


def _rule_keynote199(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if _has_msi_high(patient) and _disease_state(patient) == "m1_crpc":
        return True, ["mCRPC MSI-H — subgrupo con respuesta en KEYNOTE-199."], []
    return False, [], ["KEYNOTE-199 pivota en mCRPC MSI-H."]


def _rule_vision(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if _disease_state(patient) != "m1_crpc":
        issues.append("VISION es mCRPC post-ARPI + post-taxano.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("Requiere ARPI previo.")
    if not _prior_therapy(patient, "prior_docetaxel") and not _prior_therapy(patient, "prior_taxane"):
        issues.append("Requiere taxano previo.")
    if not _psma_positive(patient):
        issues.append("Requiere enfermedad PSMA-positiva (SUVmax ≥ hígado de referencia).")
    if _is_truthy(
        patient.get("psma_negative_dominant_lesion")
        or patient.get("psma_negative_dominant_lesions")
    ):
        issues.append("VISION excluye lesiones PSMA-negativas dominantes (visceral ≥1 cm o nodal ≥2.5 cm de eje corto).")
    if not issues:
        reasons.append("mCRPC PSMA+ post-ARPI + post-taxano — cohorte VISION (Lu-177 PSMA-617).")
    return bool(reasons), reasons, issues


def _rule_psmafore(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if _disease_state(patient) != "m1_crpc":
        issues.append("PSMAfore evalúa mCRPC pre-taxano.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("Requiere ARPI previo.")
    if _prior_therapy(patient, "prior_docetaxel") or _prior_therapy(patient, "prior_taxane"):
        issues.append("PSMAfore excluye taxano previo (diseño pre-taxano).")
    if not _psma_positive(patient):
        issues.append("Requiere PSMA-positivo.")
    if not issues:
        reasons.append("mCRPC PSMA+ post-ARPI sin taxano — cohorte PSMAfore.")
    return bool(reasons), reasons, issues


def _rule_card(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if _disease_state(patient) != "m1_crpc":
        issues.append("CARD es mCRPC post-ARPI + post-docetaxel.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("Requiere ARPI previo.")
    if not _prior_therapy(patient, "prior_docetaxel"):
        issues.append("Requiere docetaxel previo.")
    if not issues:
        reasons.append("mCRPC post-ARPI+docetaxel — cohorte CARD (cabazitaxel > ARPI switch).")
    return bool(reasons), reasons, issues


def _rule_alsympca(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    reasons: list[str] = []
    issues: list[str] = []
    if _disease_state(patient) != "m1_crpc":
        issues.append("ALSYMPCA es mCRPC sintomático óseo.")
    if not _is_truthy(patient.get("symptomatic_bone_only")):
        issues.append("Requiere enfermedad sintomática óseo-predominante sin viscerales.")
    if not issues:
        reasons.append("mCRPC sintomático óseo-dominante — Ra-223 (ALSYMPCA).")
    return bool(reasons), reasons, issues


def _rule_prophecy(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if _arv7_positive(patient):
        return True, ["AR-V7+ — PROPHECY sugiere taxano sobre ARPI."], []
    return False, [], ["PROPHECY es relevante ante AR-V7+."]


def _rule_ep16_nepc(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if _nepc_signal(patient):
        return True, ["NEPC confirmado / sospechado — régimen platino tipo EP-16 (Aparicio 2013)."], []
    return False, [], ["Requiere señal NEPC (histología IHC o LDH/NSE altos + viscerales)."]


def _rule_ipatential(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if _is_truthy(patient.get("pten_loss")) and _disease_state(patient) == "m1_crpc":
        return True, ["PTEN-loss en mCRPC — IPATential150 (ipatasertib + abiraterona)."], []
    return False, [], ["Requiere PTEN-loss confirmada en mCRPC."]


def _rule_capitello281(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    if _is_truthy(patient.get("pten_loss")) and state.startswith("mcspc_"):
        return True, ["PTEN-loss en mHSPC — CAPItello-281 (capivasertib + abiraterona)."], []
    return False, [], ["Requiere PTEN-loss en mHSPC."]


def _rule_presto(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    state = _disease_state(patient)
    psadt = _safe_float(patient.get("psa_doubling_time_months"))
    m_stage = str(patient.get("m_stage") or "").strip().upper()
    reasons: list[str] = []
    issues: list[str] = []
    if state != "recurrence_bcr":
        issues.append("PRESTO/AFT-19 requiere BCR no metastásico.")
    if m_stage and m_stage != "M0":
        issues.append(f"PRESTO/AFT-19 requiere M0 confirmado (paciente: {m_stage}).")
    if psadt is None:
        issues.append("Falta PSA doubling time.")
    elif psadt > 9:
        issues.append("PRESTO requiere PSADT corto (≤9 meses).")
    if not issues:
        reasons.append(f"BCR M0 con PSADT {psadt:.1f} meses — PRESTO (ADT + apalutamida ± abiraterona).")
    return bool(reasons), reasons, issues


def _rule_enzamet(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if _disease_state(patient).startswith("mcspc_"):
        return True, ["mHSPC — ENZAMET validó enzalutamida + ADT (beneficio OS robusto)."], []
    return False, [], ["ENZAMET relevante en mHSPC."]


# ── Auditoría #14 — 18 reglas adicionales para cobertura insignia ──────


def _bool_field(patient: dict[str, Any], *keys: str) -> bool:
    return any(_is_truthy(patient.get(key)) for key in keys)


def _gleason_total(patient: dict[str, Any]) -> int | None:
    raw = _first_non_empty(patient, "gleason_total", "gleason_score", "isup_grade")
    try:
        if raw in (None, ""):
            return None
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    if value <= 5:
        # ISUP grade group → aproximación a Gleason total agregando 5 (1→6, 2→7, 3→7, 4→8, 5→9-10)
        return {1: 6, 2: 7, 3: 7, 4: 8, 5: 9}.get(value, value + 5)
    return value


def _bone_lesion_count(patient: dict[str, Any]) -> int | None:
    raw = _first_non_empty(
        patient,
        "bone_lesion_count",
        "bone_metastases_count",
        "metastasis_bone_lesion_count",
        "bone_mets_count",
    )
    try:
        if raw in (None, ""):
            return None
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _has_visceral_disease(patient: dict[str, Any]) -> bool:
    if _bool_field(patient, "visceral_disease", "visceral_metastasis", "visceral_metastases"):
        return True
    site = str(patient.get("metastasis_site", "")).lower()
    return any(token in site for token in ("visceral", "liver", "lung", "hígado", "pulmón", "pulmon"))


def _has_bone_only_disease(patient: dict[str, Any]) -> bool:
    if _bool_field(patient, "bone_only_disease", "symptomatic_bone_only", "bone_only"):
        return True
    if _has_visceral_disease(patient):
        return False
    site = str(patient.get("metastasis_site", "")).lower()
    return "bone" in site or "óseo" in site or "oseo" in site or "hueso" in site


def _has_high_volume_chaarted(patient: dict[str, Any]) -> bool:
    if _has_visceral_disease(patient):
        return True
    bone_count = _bone_lesion_count(patient)
    appendicular = _is_truthy(patient.get("bone_lesions_outside_axial"))
    if bone_count is not None and bone_count >= 4 and appendicular:
        return True
    state = _disease_state(patient)
    return state.startswith("mcspc_high")


def _has_latitude_high_risk(patient: dict[str, Any]) -> bool:
    """LATITUDE: ≥2 of (Gleason ≥8, ≥3 bone lesions, visceral mets)."""
    risk_factors = 0
    gleason = _gleason_total(patient)
    if gleason is not None and gleason >= 8:
        risk_factors += 1
    bone_count = _bone_lesion_count(patient)
    if bone_count is not None and bone_count >= 3:
        risk_factors += 1
    if _has_visceral_disease(patient):
        risk_factors += 1
    return risk_factors >= 2


def _seizure_history(patient: dict[str, Any]) -> bool:
    return _bool_field(
        patient,
        "seizure_history",
        "comorbidity_seizure",
        "prior_seizure",
        "history_seizure",
    )


def _life_expectancy_short(patient: dict[str, Any], threshold: float = 10.0) -> bool:
    le = _safe_float(patient.get("life_expectancy_years"))
    return le is not None and le < threshold


def _post_rp_adverse_pathology(patient: dict[str, Any]) -> bool:
    if _bool_field(patient, "adverse_pathology", "pT3", "pT3a", "pT3b", "pT4", "positive_surgical_margins"):
        return True
    pT = str(_first_non_empty(patient, "pT_stage", "pathological_t_stage", "pT", "pathology_t") or "").lower()
    if pT.startswith("pt3") or pT.startswith("pt4"):
        return True
    margins = str(patient.get("surgical_margin_status", "")).lower()
    if "positive" in margins or "r1" in margins or "positiva" in margins:
        return True
    return False


def _rule_radicals_rt(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """RADICALS-RT: post-RP con patología adversa y PSA ondetectable."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state not in {"post_prostatectomy", "recurrence_bcr"}:
        issues.append("RADICALS-RT requiere paciente post-prostatectomía.")
    if not _post_rp_adverse_pathology(patient):
        issues.append("Requiere patología adversa: pT3-4, márgenes positivos o ECE.")
    psa = _safe_float(patient.get("psa") or patient.get("psa_postop") or patient.get("psa_current"))
    if psa is not None and psa >= 0.2 and not _is_truthy(patient.get("early_salvage_window")):
        issues.append("PSA ≥0.2 con ventana de salvage temprana ya superada — RADICALS-RT comparó RT adyuvante vs salvage temprano.")
    if not issues:
        reasons.append("Post-RP con patología adversa — cohorte RADICALS-RT (RT adyuvante vs salvage temprana).")
    return bool(reasons), reasons, issues


def _rule_chaarted(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """CHAARTED: mHSPC alto volumen fit para docetaxel."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if not state.startswith("mcspc_"):
        issues.append("CHAARTED evalúa mHSPC.")
    if not _has_high_volume_chaarted(patient):
        issues.append("Requiere alto volumen CHAARTED (≥4 mets óseos con ≥1 fuera de axial o viscerales).")
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — normalización canónica
    # de docetaxel_fit (incluye aliases `taxane_fitness`, `fit_for_docetaxel`,
    # `chemotherapy_fitness`; Desconocido/Marginal → no apto conservador).
    if not resolve_docetaxel_fit(patient):
        issues.append("Requiere fitness para docetaxel.")
    ecog = _ecog(patient)
    if ecog is not None and ecog > 2:
        issues.append("CHAARTED excluye ECOG >2.")
    if not issues:
        reasons.append("mHSPC alto volumen fit para taxano — CHAARTED (ADT + docetaxel).")
    return bool(reasons), reasons, issues


def _rule_latitude(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """LATITUDE: mHSPC alto riesgo (≥2 de Gleason ≥8 / ≥3 mets óseos / viscerales)."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if not state.startswith("mcspc_"):
        issues.append("LATITUDE evalúa mHSPC.")
    if not _has_latitude_high_risk(patient):
        issues.append("Requiere ≥2 factores LATITUDE: Gleason ≥8, ≥3 mets óseos, viscerales.")
    if not issues:
        reasons.append("mHSPC alto riesgo (LATITUDE) — ADT + abiraterona + prednisona.")
    return bool(reasons), reasons, issues


def _rule_arches(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """ARCHES: mHSPC con o sin docetaxel previo."""
    if _disease_state(patient).startswith("mcspc_"):
        return True, ["mHSPC — ARCHES (ADT + enzalutamida; admite docetaxel previo)."], []
    return False, [], ["ARCHES requiere mHSPC."]


def _rule_aranote(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """ARANOTE: mHSPC con doblete ADT + darolutamida (sin chemo)."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if not state.startswith("mcspc_"):
        issues.append("ARANOTE evalúa mHSPC.")
    # ARANOTE excluyó tratamiento previo extenso pero permitió chemo en arm
    if not issues:
        reasons.append("mHSPC — ARANOTE (ADT + darolutamida; doblete sin chemo).")
    return bool(reasons), reasons, issues


def _rule_spartan(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """SPARTAN: nmCRPC con PSADT ≤10 meses."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m0_crpc":
        issues.append("SPARTAN limitado a M0 CRPC.")
    psadt = _safe_float(patient.get("psa_doubling_time_months") or patient.get("psadt_months"))
    if psadt is None:
        issues.append("Requiere PSA doubling time documentado.")
    elif psadt > 10:
        issues.append("SPARTAN requiere PSADT ≤10 meses.")
    if not issues:
        reasons.append(f"M0 CRPC con PSADT {psadt:.1f}m — SPARTAN (apalutamida).")
    return bool(reasons), reasons, issues


def _rule_prosper(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """PROSPER: nmCRPC con PSADT ≤10 meses."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m0_crpc":
        issues.append("PROSPER limitado a M0 CRPC.")
    psadt = _safe_float(patient.get("psa_doubling_time_months") or patient.get("psadt_months"))
    if psadt is None:
        issues.append("Requiere PSA doubling time documentado.")
    elif psadt > 10:
        issues.append("PROSPER requiere PSADT ≤10 meses.")
    if _seizure_history(patient):
        issues.append("Historia de convulsiones — caution con enzalutamida (PROSPER permitió pero estratificó).")
    if not issues:
        reasons.append(f"M0 CRPC con PSADT {psadt:.1f}m — PROSPER (enzalutamida).")
    return bool(reasons), reasons, issues


def _rule_aramis(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """ARAMIS: nmCRPC con PSADT ≤10 meses (darolutamida — perfil CNS preferido)."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m0_crpc":
        issues.append("ARAMIS limitado a M0 CRPC.")
    psadt = _safe_float(patient.get("psa_doubling_time_months") or patient.get("psadt_months"))
    if psadt is None:
        issues.append("Requiere PSA doubling time documentado.")
    elif psadt > 10:
        issues.append("ARAMIS requiere PSADT ≤10 meses.")
    if not issues:
        reasons.append(f"M0 CRPC con PSADT {psadt:.1f}m — ARAMIS (darolutamida; menor pase BBB).")
    return bool(reasons), reasons, issues


def _rule_tax327(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """TAX-327: mCRPC chemo-naive primera línea de docetaxel."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("TAX-327 evalúa mCRPC.")
    if _prior_therapy(patient, "prior_docetaxel") or _prior_therapy(patient, "prior_taxane"):
        issues.append("TAX-327 requiere chemo-naive (no docetaxel previo).")
    # Auditoría Pacientes Insignia 2026-04-21 (§E.1) — normalización canónica
    # de docetaxel_fit (aliases + Desconocido/Marginal → no apto conservador).
    if not resolve_docetaxel_fit(patient):
        issues.append("Requiere fitness para taxano.")
    ecog = _ecog(patient)
    if ecog is not None and ecog > 2:
        issues.append("TAX-327 excluyó ECOG >2.")
    if not issues:
        reasons.append("mCRPC chemo-naive fit — TAX-327 (docetaxel + prednisona 1L).")
    return bool(reasons), reasons, issues


def _rule_tropic(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """TROPIC: mCRPC progresado bajo o post-docetaxel."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("TROPIC evalúa mCRPC.")
    if not _prior_therapy(patient, "prior_docetaxel"):
        issues.append("Requiere docetaxel previo.")
    ecog = _ecog(patient)
    if ecog is not None and ecog > 2:
        issues.append("TROPIC excluyó ECOG >2.")
    if not issues:
        reasons.append("mCRPC post-docetaxel — TROPIC (cabazitaxel + prednisona).")
    return bool(reasons), reasons, issues


def _rule_cou_aa_301(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """COU-AA-301: mCRPC sintomático post-docetaxel."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("COU-AA-301 evalúa mCRPC.")
    if not _prior_therapy(patient, "prior_docetaxel"):
        issues.append("Requiere docetaxel previo.")
    if not issues:
        reasons.append("mCRPC post-docetaxel — COU-AA-301 (abiraterona + prednisona post-chemo).")
    return bool(reasons), reasons, issues


def _rule_cou_aa_302(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """COU-AA-302: mCRPC chemo-naive asintomático/leve."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("COU-AA-302 evalúa mCRPC.")
    if _prior_therapy(patient, "prior_docetaxel") or _prior_therapy(patient, "prior_taxane"):
        issues.append("COU-AA-302 requiere chemo-naive.")
    pain = str(patient.get("pain_status") or patient.get("symptom_burden") or "").lower()
    if pain in {"severe", "severa", "moderate-severe", "moderada-severa"}:
        issues.append("COU-AA-302 excluyó dolor severo (BPI ≥4).")
    if not issues:
        reasons.append("mCRPC chemo-naive asintomático/leve — COU-AA-302 (abiraterona + prednisona pre-chemo).")
    return bool(reasons), reasons, issues


def _rule_affirm(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """AFFIRM: mCRPC post-docetaxel — enzalutamida (excluye historia de convulsiones)."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("AFFIRM evalúa mCRPC.")
    if not _prior_therapy(patient, "prior_docetaxel"):
        issues.append("Requiere docetaxel previo.")
    if _seizure_history(patient):
        issues.append("AFFIRM excluyó historia de convulsiones.")
    if not issues:
        reasons.append("mCRPC post-docetaxel — AFFIRM (enzalutamida post-chemo).")
    return bool(reasons), reasons, issues


def _rule_prevail(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """PREVAIL: mCRPC chemo-naive — enzalutamida (asintomático/leve)."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("PREVAIL evalúa mCRPC.")
    if _prior_therapy(patient, "prior_docetaxel") or _prior_therapy(patient, "prior_taxane"):
        issues.append("PREVAIL requiere chemo-naive.")
    if _seizure_history(patient):
        issues.append("PREVAIL excluyó historia de convulsiones.")
    pain = str(patient.get("pain_status") or patient.get("symptom_burden") or "").lower()
    if pain in {"severe", "severa", "moderate-severe", "moderada-severa"}:
        issues.append("PREVAIL excluyó dolor severo.")
    if not issues:
        reasons.append("mCRPC chemo-naive asintomático/leve — PREVAIL (enzalutamida pre-chemo).")
    return bool(reasons), reasons, issues


def _rule_therap(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """TheraP: mCRPC PSMA+ post-docetaxel — Lu-PSMA vs cabazitaxel."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("TheraP evalúa mCRPC.")
    if not _prior_therapy(patient, "prior_docetaxel"):
        issues.append("TheraP requiere docetaxel previo.")
    if not _psma_positive(patient):
        issues.append("Requiere PSMA-positivo (SUVmax ≥20 al menos una lesión).")
    suvmax = _safe_float(patient.get("psma_lesion_suvmax_minimum"))
    if suvmax is not None and suvmax < 20:
        issues.append("TheraP exigió SUVmax ≥20 en al menos una lesión índice.")
    if not issues:
        reasons.append("mCRPC PSMA+ post-docetaxel — TheraP (Lu-177 PSMA-617 vs cabazitaxel).")
    return bool(reasons), reasons, issues


def _rule_peace3(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """PEACE-3: mCRPC sintomático/asintomático bone-only — Ra-223 + enzalutamida."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("PEACE-3 evalúa mCRPC.")
    if not _has_bone_only_disease(patient):
        issues.append("Requiere enfermedad ósea sin viscerales.")
    if _has_visceral_disease(patient):
        issues.append("PEACE-3 excluyó viscerales.")
    if _prior_therapy(patient, "prior_arpi") or _prior_therapy(patient, "prior_enzalutamide"):
        issues.append("PEACE-3 limitó a ARPI-naive en mCRPC (admite ARPI previo en mHSPC).")
    if not issues:
        reasons.append("mCRPC bone-only ARPI-naive — PEACE-3 (Ra-223 + enzalutamida con profilaxis ósea).")
    return bool(reasons), reasons, issues


def _rule_impact(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """IMPACT: mCRPC asintomático sin viscerales — sipuleucel-T."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("IMPACT evalúa mCRPC.")
    if _has_visceral_disease(patient):
        issues.append("IMPACT excluyó viscerales.")
    pain = str(patient.get("pain_status") or patient.get("symptom_burden") or "").lower()
    if pain in {"moderate", "severe", "moderada", "severa", "moderate-severe", "moderada-severa"}:
        issues.append("IMPACT requiere asintomático/mínimamente sintomático (no opioides).")
    if not issues:
        reasons.append("mCRPC asintomático sin viscerales — IMPACT (sipuleucel-T inmunoterapia).")
    return bool(reasons), reasons, issues


def _rule_contact02(patient: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """CONTACT-02: mCRPC post-ARPI con viscerales o nodos extra-pélvicos."""
    state = _disease_state(patient)
    reasons: list[str] = []
    issues: list[str] = []
    if state != "m1_crpc":
        issues.append("CONTACT-02 evalúa mCRPC.")
    if not _prior_therapy(patient, "prior_arpi"):
        issues.append("CONTACT-02 requiere ARPI previo.")
    has_visceral = _has_visceral_disease(patient)
    extra_pelvic = _is_truthy(patient.get("extra_pelvic_nodal_metastasis") or patient.get("nodal_extrapelvic"))
    if not (has_visceral or extra_pelvic):
        issues.append("Requiere viscerales o nodos extra-pélvicos (criterio de inclusión CONTACT-02).")
    if _prior_therapy(patient, "prior_docetaxel") and not _is_truthy(patient.get("not_chemotherapy_candidate")):
        issues.append("Diseño priorizó pacientes que rehúsan o no candidatos a chemo (post-ARPI).")
    if not issues:
        reasons.append("mCRPC post-ARPI con viscerales/extra-pélvicos — CONTACT-02 (cabozantinib + atezolizumab).")
    return bool(reasons), reasons, issues


# ── Catálogo ───────────────────────────────────────────────────────────


TRIAL_CATALOG: tuple[TrialDefinition, ...] = (
    TrialDefinition(
        trial_code="STAMPEDE",
        title_short="STAMPEDE: plataforma multi-arm M0/M1 (RT+ADT, ADT+abi, ADT+doce)",
        nct_id="NCT00268476",
        disease_scope=(
            "localized_initial",
            "recurrence_bcr",
            "mcspc_high_volume",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_oligo_metachronous",
        ),
        eligibility_rule=_rule_stampede_classic,
        evidence_tags=("stampede", "james_lancet_2016", "james_nejm_2017", "james_lancet_2022"),
        primary_reference="James ND et al. STAMPEDE platform 2016-2022",
        phase="Phase III",
        status_summary="Brazos cerrados con beneficio OS para abiraterona y docetaxel en M1.",
    ),
    TrialDefinition(
        trial_code="STAMPEDE-2",
        title_short="STAMPEDE-2: intensificación en alto riesgo localizado / mHSPC",
        nct_id="NCT06520007",
        disease_scope=("localized_initial", "recurrence_bcr", "mcspc_high_volume", "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous"),
        eligibility_rule=_rule_stampede2,
        evidence_tags=("stampede2", "multi_arm_platform"),
        primary_reference="James ND et al. platform trial 2024",
        phase="Phase III",
        status_summary="Reclutamiento activo",
    ),
    TrialDefinition(
        trial_code="EMBARK",
        title_short="EMBARK: BCR no-metastático",
        nct_id="NCT02319837",
        disease_scope=("recurrence_bcr",),
        eligibility_rule=_rule_embark,
        evidence_tags=("embark", "freedland_nejm_2023"),
        primary_reference="Freedland SJ et al. NEJM 2023;389:1453",
        phase="Phase III",
        status_summary="Aprobación FDA 11/2023",
    ),
    TrialDefinition(
        trial_code="PRESTO",
        title_short="PRESTO: BCR con PSADT corto",
        nct_id="NCT03009981",
        disease_scope=("recurrence_bcr",),
        eligibility_rule=_rule_presto,
        evidence_tags=("presto", "aggarwal_jco_2022"),
        primary_reference="Aggarwal R et al. JCO 2022;40:3261",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="ARASENS",
        title_short="ARASENS: triplete ADT + docetaxel + darolutamida",
        nct_id="NCT02799602",
        disease_scope=("mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"),
        eligibility_rule=_rule_arasens,
        evidence_tags=("arasens", "smith_nejm_2022"),
        primary_reference="Smith MR et al. NEJM 2022;386:1132",
        phase="Phase III",
        status_summary="Standard of care mHSPC alto volumen",
    ),
    TrialDefinition(
        trial_code="TITAN",
        title_short="TITAN: apalutamida + ADT en mHSPC",
        nct_id="NCT02489318",
        disease_scope=("mcspc_high_volume", "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"),
        eligibility_rule=_rule_titan,
        evidence_tags=("titan", "chi_nejm_2019"),
        primary_reference="Chi KN et al. NEJM 2019;381:13",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="ENZAMET",
        title_short="ENZAMET: enzalutamida + ADT en mHSPC",
        nct_id="NCT02446405",
        disease_scope=("mcspc_high_volume", "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"),
        eligibility_rule=_rule_enzamet,
        evidence_tags=("enzamet", "davis_nejm_2019"),
        primary_reference="Davis ID et al. NEJM 2019;381:121",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="PEACE-1",
        title_short="PEACE-1: triplete abiraterona + ADT + docetaxel",
        nct_id="NCT01957436",
        disease_scope=("mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"),
        eligibility_rule=_rule_peace1,
        evidence_tags=("peace1", "fizazi_lancet_2022"),
        primary_reference="Fizazi K et al. Lancet 2022;399:1695",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="PROfound",
        title_short="PROfound: olaparib HRR+ mCRPC post-ARPI",
        nct_id="NCT02987543",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_profound,
        evidence_tags=("profound", "de_bono_nejm_2020"),
        primary_reference="de Bono J et al. NEJM 2020;382:2091",
        phase="Phase III",
        status_summary="Aprobación FDA 05/2020",
    ),
    TrialDefinition(
        trial_code="PROpel",
        title_short="PROpel: olaparib + abiraterona mCRPC 1L",
        nct_id="NCT03732820",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_propel,
        evidence_tags=("propel", "clarke_lancet_oncol_2022"),
        primary_reference="Clarke NW et al. Lancet Oncol 2022;23:1519",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="MAGNITUDE",
        title_short="MAGNITUDE: niraparib + abiraterona mCRPC BRCA+",
        nct_id="NCT03748641",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_magnitude,
        evidence_tags=("magnitude", "chi_jco_2023"),
        primary_reference="Chi KN et al. JCO 2023;41:3339",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="TALAPRO-2",
        title_short="TALAPRO-2: talazoparib + enzalutamida mCRPC 1L",
        nct_id="NCT03395197",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_talapro2,
        evidence_tags=("talapro2", "agarwal_lancet_2023"),
        primary_reference="Agarwal N et al. Lancet 2023;402:291",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="TALAPRO-3",
        title_short="TALAPRO-3: talazoparib + enzalutamida mHSPC HRR+",
        nct_id="NCT04821622",
        disease_scope=("mcspc_high_volume", "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous"),
        eligibility_rule=_rule_talapro3,
        evidence_tags=("talapro3",),
        primary_reference="TALAPRO-3 protocol 2024",
        phase="Phase III",
        status_summary="Reclutamiento activo",
    ),
    TrialDefinition(
        trial_code="AMPLITUDE",
        title_short="AMPLITUDE: niraparib + abiraterona mHSPC BRCA+",
        nct_id="NCT04497844",
        disease_scope=(
            "mcspc_high_volume",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_oligo_metachronous",
        ),
        eligibility_rule=_rule_amplitude,
        evidence_tags=("amplitude",),
        primary_reference="AMPLITUDE protocol 2024",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="TRITON-3",
        title_short="TRITON-3: rucaparib mCRPC BRCA/ATM+",
        nct_id="NCT02975934",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_triton3,
        evidence_tags=("triton3", "fizazi_nejm_2023"),
        primary_reference="Fizazi K et al. NEJM 2023;388:719",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="KEYNOTE-158",
        title_short="KEYNOTE-158: pembrolizumab MSI-H/dMMR tumor-agnóstico",
        nct_id="NCT02628067",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_keynote158,
        evidence_tags=("keynote158", "marabelle_jco_2020"),
        primary_reference="Marabelle A et al. JCO 2020;38:1",
        phase="Phase II",
    ),
    TrialDefinition(
        trial_code="KEYNOTE-199",
        title_short="KEYNOTE-199: pembrolizumab mCRPC",
        nct_id="NCT02787005",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_keynote199,
        evidence_tags=("keynote199", "antonarakis_jco_2020"),
        primary_reference="Antonarakis ES et al. JCO 2020;38:395",
        phase="Phase II",
    ),
    TrialDefinition(
        trial_code="VISION",
        title_short="VISION: Lu-177 PSMA mCRPC post-ARPI + post-taxano",
        nct_id="NCT03511664",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_vision,
        evidence_tags=("vision", "sartor_nejm_2021"),
        primary_reference="Sartor O et al. NEJM 2021;385:1091",
        phase="Phase III",
        status_summary="Aprobación FDA 03/2022",
    ),
    TrialDefinition(
        trial_code="PSMAfore",
        title_short="PSMAfore: Lu-177 PSMA pre-taxano",
        nct_id="NCT04689828",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_psmafore,
        evidence_tags=("psmafore", "morris_lancet_2024"),
        primary_reference="Morris MJ et al. Lancet 2024;404:1227",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="CARD",
        title_short="CARD: cabazitaxel vs ARPI switch",
        nct_id="NCT02485691",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_card,
        evidence_tags=("card", "de_wit_nejm_2019"),
        primary_reference="de Wit R et al. NEJM 2019;381:2506",
        phase="Phase IV",
    ),
    TrialDefinition(
        trial_code="ALSYMPCA",
        title_short="ALSYMPCA: Ra-223 mCRPC óseo sintomático",
        nct_id="NCT00699751",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_alsympca,
        evidence_tags=("alsympca", "parker_nejm_2013"),
        primary_reference="Parker C et al. NEJM 2013;369:213",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="PROPHECY",
        title_short="PROPHECY: AR-V7+ biomarker study",
        nct_id="NCT02269982",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_prophecy,
        evidence_tags=("prophecy", "armstrong_jama_oncol_2019"),
        primary_reference="Armstrong AJ et al. JAMA Oncol 2019;5:1214",
        phase="Phase II",
    ),
    TrialDefinition(
        trial_code="EP-16-NEPC",
        title_short="EP-16 (Aparicio): platino en NEPC",
        nct_id="NCT00967616",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_ep16_nepc,
        evidence_tags=("aparicio_ccr_2013", "beltran_jco_2014"),
        primary_reference="Aparicio AM et al. CCR 2013;19:3621",
        phase="Phase II",
    ),
    TrialDefinition(
        trial_code="IPATential150",
        title_short="IPATential150: ipatasertib + abiraterona en PTEN-loss",
        nct_id="NCT03072238",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_ipatential,
        evidence_tags=("ipatential150", "sweeney_lancet_2021"),
        primary_reference="Sweeney C et al. Lancet 2021;398:131",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="CAPItello-281",
        title_short="CAPItello-281: capivasertib + abiraterona mHSPC PTEN-loss",
        nct_id="NCT04493853",
        disease_scope=("mcspc_high_volume", "mcspc_low_volume_sync_oligo"),
        eligibility_rule=_rule_capitello281,
        evidence_tags=("capitello281",),
        primary_reference="CAPItello-281 protocol 2024",
        phase="Phase III",
    ),
    # ── Auditoría #14 — 18 ensayos pivotales adicionales ─────────────
    TrialDefinition(
        trial_code="RADICALS-RT",
        title_short="RADICALS-RT: RT adyuvante vs salvage temprano post-RP",
        nct_id="NCT00541047",
        disease_scope=("post_prostatectomy", "recurrence_bcr"),
        eligibility_rule=_rule_radicals_rt,
        evidence_tags=("radicals_rt", "parker_lancet_2020"),
        primary_reference="Parker CC et al. Lancet 2020;396:1413",
        phase="Phase III",
        status_summary="Salvage temprano no inferior a adyuvante en BFS.",
    ),
    TrialDefinition(
        trial_code="CHAARTED",
        title_short="CHAARTED: ADT + docetaxel mHSPC alto volumen",
        nct_id="NCT00309985",
        disease_scope=("mcspc_high_volume", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous"),
        eligibility_rule=_rule_chaarted,
        evidence_tags=("chaarted", "sweeney_nejm_2015"),
        primary_reference="Sweeney CJ et al. NEJM 2015;373:737",
        phase="Phase III",
        status_summary="Beneficio OS 13.6m alto volumen.",
    ),
    TrialDefinition(
        trial_code="LATITUDE",
        title_short="LATITUDE: ADT + abiraterona mHSPC alto riesgo",
        nct_id="NCT01715285",
        disease_scope=(
            "mcspc_high_volume",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_low_volume_sync_oligo",
        ),
        eligibility_rule=_rule_latitude,
        evidence_tags=("latitude", "fizazi_nejm_2017"),
        primary_reference="Fizazi K et al. NEJM 2017;377:352",
        phase="Phase III",
        status_summary="Aprobación FDA mHSPC alto riesgo.",
    ),
    TrialDefinition(
        trial_code="ARCHES",
        title_short="ARCHES: ADT + enzalutamida mHSPC todo volumen",
        nct_id="NCT02677896",
        disease_scope=(
            "mcspc_high_volume",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_oligo_metachronous",
        ),
        eligibility_rule=_rule_arches,
        evidence_tags=("arches", "armstrong_jco_2019"),
        primary_reference="Armstrong AJ et al. JCO 2019;37:2974",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="ARANOTE",
        title_short="ARANOTE: ADT + darolutamida mHSPC sin chemo",
        nct_id="NCT04736199",
        disease_scope=(
            "mcspc_high_volume",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_oligo_metachronous",
        ),
        eligibility_rule=_rule_aranote,
        evidence_tags=("aranote", "saad_jco_2024"),
        primary_reference="Saad F et al. JCO 2024 (ARANOTE)",
        phase="Phase III",
        status_summary="Aprobación FDA 11/2024.",
    ),
    TrialDefinition(
        trial_code="SPARTAN",
        title_short="SPARTAN: apalutamida nmCRPC PSADT ≤10m",
        nct_id="NCT01946204",
        disease_scope=("m0_crpc",),
        eligibility_rule=_rule_spartan,
        evidence_tags=("spartan", "smith_nejm_2018"),
        primary_reference="Smith MR et al. NEJM 2018;378:1408",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="PROSPER",
        title_short="PROSPER: enzalutamida nmCRPC PSADT ≤10m",
        nct_id="NCT02003924",
        disease_scope=("m0_crpc",),
        eligibility_rule=_rule_prosper,
        evidence_tags=("prosper", "hussain_nejm_2018"),
        primary_reference="Hussain M et al. NEJM 2018;378:2465",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="ARAMIS",
        title_short="ARAMIS: darolutamida nmCRPC PSADT ≤10m",
        nct_id="NCT02200614",
        disease_scope=("m0_crpc",),
        eligibility_rule=_rule_aramis,
        evidence_tags=("aramis", "fizazi_nejm_2019"),
        primary_reference="Fizazi K et al. NEJM 2019;380:1235",
        phase="Phase III",
        status_summary="Perfil CNS preferido (menor pase BBB).",
    ),
    TrialDefinition(
        trial_code="TAX-327",
        title_short="TAX-327: docetaxel + prednisona mCRPC 1L",
        nct_id="NCT00134056",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_tax327,
        evidence_tags=("tax327", "tannock_nejm_2004"),
        primary_reference="Tannock IF et al. NEJM 2004;351:1502",
        phase="Phase III",
        status_summary="Fundación de docetaxel en mCRPC.",
    ),
    TrialDefinition(
        trial_code="TROPIC",
        title_short="TROPIC: cabazitaxel + prednisona post-docetaxel",
        nct_id="NCT00417079",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_tropic,
        evidence_tags=("tropic", "de_bono_lancet_2010"),
        primary_reference="de Bono JS et al. Lancet 2010;376:1147",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="COU-AA-301",
        title_short="COU-AA-301: abiraterona post-docetaxel sintomático",
        nct_id="NCT00638690",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_cou_aa_301,
        evidence_tags=("cou_aa_301", "de_bono_nejm_2011"),
        primary_reference="de Bono JS et al. NEJM 2011;364:1995",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="COU-AA-302",
        title_short="COU-AA-302: abiraterona pre-docetaxel asintomático",
        nct_id="NCT00887198",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_cou_aa_302,
        evidence_tags=("cou_aa_302", "ryan_nejm_2013"),
        primary_reference="Ryan CJ et al. NEJM 2013;368:138",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="AFFIRM",
        title_short="AFFIRM: enzalutamida post-docetaxel",
        nct_id="NCT00974311",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_affirm,
        evidence_tags=("affirm", "scher_nejm_2012"),
        primary_reference="Scher HI et al. NEJM 2012;367:1187",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="PREVAIL",
        title_short="PREVAIL: enzalutamida pre-docetaxel asintomático",
        nct_id="NCT01212991",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_prevail,
        evidence_tags=("prevail", "beer_nejm_2014"),
        primary_reference="Beer TM et al. NEJM 2014;371:424",
        phase="Phase III",
    ),
    TrialDefinition(
        trial_code="TheraP",
        title_short="TheraP: Lu-177 PSMA vs cabazitaxel post-docetaxel",
        nct_id="NCT03392428",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_therap,
        evidence_tags=("therap", "hofman_lancet_2021"),
        primary_reference="Hofman MS et al. Lancet 2021;397:797",
        phase="Phase II",
    ),
    TrialDefinition(
        trial_code="PEACE-3",
        title_short="PEACE-3: Ra-223 + enzalutamida mCRPC bone-only",
        nct_id="NCT02194842",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_peace3,
        evidence_tags=("peace3", "gillessen_esmo_2024"),
        primary_reference="Gillessen S et al. ESMO 2024 LBA1",
        phase="Phase III",
        status_summary="Profilaxis ósea obligatoria por señal previa Ra-223+abi.",
    ),
    TrialDefinition(
        trial_code="IMPACT",
        title_short="IMPACT: sipuleucel-T mCRPC asintomático",
        nct_id="NCT00065442",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_impact,
        evidence_tags=("impact", "kantoff_nejm_2010"),
        primary_reference="Kantoff PW et al. NEJM 2010;363:411",
        phase="Phase III",
        status_summary="Aprobación FDA 04/2010 inmunoterapia.",
    ),
    TrialDefinition(
        trial_code="CONTACT-02",
        title_short="CONTACT-02: cabozantinib + atezolizumab mCRPC visceral/extra-pélvico",
        nct_id="NCT04446117",
        disease_scope=("m1_crpc",),
        eligibility_rule=_rule_contact02,
        evidence_tags=("contact02", "agarwal_lancet_oncol_2025"),
        primary_reference="Agarwal N et al. Lancet Oncol 2025 (CONTACT-02)",
        phase="Phase III",
        status_summary="Mejora rPFS en post-ARPI con viscerales/extrapélvicos.",
    ),
)


# ── API pública ────────────────────────────────────────────────────────


def match_patient_to_trials(patient: dict[str, Any], limit: int | None = None) -> list[TrialMatch]:
    """Evalúa el catálogo contra el paciente y retorna la lista de matches.

    Sólo incluye ensayos en el ``disease_scope`` del estado clínico (o todos
    si el estado no está mapeado). Cada ensayo retorna un ``TrialMatch``
    con ``match=True|False`` y razones explícitas en español.

    Args:
        patient: payload clínico normalizado.
        limit: si se especifica, trunca a los primeros N matches
            positivos (útil para UI).
    """

    state = _disease_state(patient)
    results: list[TrialMatch] = []
    for trial in TRIAL_CATALOG:
        if trial.disease_scope and state and state not in trial.disease_scope:
            # Ensayo fuera del scope: no invocamos regla, sólo marcamos.
            results.append(
                TrialMatch(
                    trial_code=trial.trial_code,
                    title_short=trial.title_short,
                    nct_id=trial.nct_id,
                    disease_scope=list(trial.disease_scope),
                    match=False,
                    ineligibility_reasons=[f"Fuera del scope para el estado actual ({state or 'desconocido'})."],
                    evidence_tags=list(trial.evidence_tags),
                    primary_reference=trial.primary_reference,
                    phase=trial.phase,
                    status_summary=trial.status_summary,
                )
            )
            continue
        try:
            is_match, reasons, issues = trial.eligibility_rule(patient)
        except Exception as exc:  # pragma: no cover — aislamos fallos individuales
            logger.exception("Trial rule crashed: %s", trial.trial_code)
            results.append(
                TrialMatch(
                    trial_code=trial.trial_code,
                    title_short=trial.title_short,
                    nct_id=trial.nct_id,
                    disease_scope=list(trial.disease_scope),
                    match=False,
                    ineligibility_reasons=[f"Error interno en regla: {exc!s}"],
                    evidence_tags=list(trial.evidence_tags),
                    primary_reference=trial.primary_reference,
                    phase=trial.phase,
                    status_summary=trial.status_summary,
                )
            )
            continue
        results.append(
            TrialMatch(
                trial_code=trial.trial_code,
                title_short=trial.title_short,
                nct_id=trial.nct_id,
                disease_scope=list(trial.disease_scope),
                match=bool(is_match),
                match_reasons=list(reasons),
                ineligibility_reasons=list(issues) if not is_match else [],
                evidence_tags=list(trial.evidence_tags),
                primary_reference=trial.primary_reference,
                phase=trial.phase,
                status_summary=trial.status_summary,
            )
        )

    if limit is not None and limit > 0:
        positive = [r for r in results if r.match][:limit]
        negative = [r for r in results if not r.match]
        return positive + negative
    return results


def build_trial_matching_bundle(patient: dict[str, Any]) -> dict[str, Any]:
    """Empaqueta los matches para profile_compass / UI."""

    matches = match_patient_to_trials(patient)
    positive = [match.to_dict() for match in matches if match.match]
    negative = [match.to_dict() for match in matches if not match.match]
    return {
        "total_trials_in_catalog": len(TRIAL_CATALOG),
        "positive_match_count": len(positive),
        "matches": positive,
        "ineligible": negative,
        "catalog_source": "local_curated_v1",
        "disclaimer": (
            "Catálogo curado para orientación inicial. Validar elegibilidad completa "
            "con el protocolo vigente del ensayo en ClinicalTrials.gov y con el comité de ensayos."
        ),
    }


__all__ = [
    "TRIAL_CATALOG",
    "TrialDefinition",
    "TrialMatch",
    "build_trial_matching_bundle",
    "match_patient_to_trials",
]
