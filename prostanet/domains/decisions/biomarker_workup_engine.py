"""biomarker_workup_engine.py — Sprint 5 (FAUBOT CXLIII).

Cierra los 16 blocked_hard del baseline CXLII: pacientes que serían
candidatos a PARP inhibitors o Lu-177-PSMA-617 pero no tienen el workup
biomarker previo documentado.

Filosofía clínica:
  GodiBot detecta correctamente la brecha (`biomarker_gap:hrr_pre_parp`,
  `biomarker_gap:psma_pet_pre_lu177`). Sin embargo, hasta hoy el clínico
  recibía una alerta "blocked_hard" SIN una acción concreta. Este engine
  transforma cada gap en un **capture target** accionable:

    - Diagnóstico previo: "HRR mutation status missing"
    - Workup recomendado: "Solicitar panel HRR (BRCA1/BRCA2/ATM/PALB2/
      CHEK2/CDK12) germinal + somático antes de considerar PARP"
    - Guideline anchor: "NCCN PROS-2 cat 1, FDA label PROfound/TALAPRO-2"
    - Routing: dónde solicitar el test (lab molecular más cercano)
    - Unblock criterion: qué dato cierra el blocked_hard automáticamente

Patrón EPIC 45: retroactivo (cohort 425+) + prospectivo (cada nuevo
intake) + observabilidad (audit trail por capture target generado).

Public API:
    build_biomarker_workup_bundle(patient_record) → dict con:
        - parp_candidate: bool
        - lu177_candidate: bool
        - hrr_workup: dict (status, action, citation, unblock_criterion)
        - psma_pet_workup: dict (same shape)
        - total_pending: int
        - cleared_recently: bool (true si pacientes con HRR/PSMA-PET
                                  recién documentados, para celebrate)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── Catálogos de evidencia ──────────────────────────────────────────────


HRR_GENES_PANEL = ("BRCA1", "BRCA2", "ATM", "PALB2", "CHEK2", "CDK12")
"""Genes del panel HRR estándar (NCCN PROS-2 cat 1)."""


PARP_INHIBITORS = (
    "olaparib", "talazoparib", "niraparib", "rucaparib",
)
"""PARP inhibitors aprobados FDA en mCRPC."""


LU177_CANDIDATES = (
    "lutetium-177-psma-617", "lu-177-psma", "lu177psma", "pluvicto",
)
"""Lu-177-PSMA-617 (Pluvicto) — VISION trial regimen."""


# EPIC 49+.C (FAUBOT CXLVII) — HX3 IO pathway
PEMBROLIZUMAB_TUMOR_AGNOSTIC_TERMS = (
    "pembrolizumab", "pembro", "keytruda",
)
"""Pembrolizumab tumor-agnostic FDA-approved (MSI-H/dMMR + Lynch syndrome)."""

LYNCH_SYNDROME_GENES = ("MLH1", "MSH2", "MSH6", "PMS2", "EPCAM")
"""Lynch syndrome germline genes — multi-cancer surveillance trigger."""


# ── Reglas de elegibilidad (basadas en NCCN v5.2026 + EAU 2026) ──────


def _gate_codes_for_patient(patient: dict[str, Any]) -> set[str]:
    """Lazy-evaluate pivotal gates y devuelve el set de códigos triggered.

    Reusa el mismo path que profile_compass + GodiBot (CXLII propagation
    fix) — única fuente de verdad para "qué considera el sistema relevante
    para este paciente".
    """
    try:
        from prostanet.domains.patient_tracking.profile_compass import (
            _lazy_evaluate_pivotal_gates_for_patient,
        )
        gates = _lazy_evaluate_pivotal_gates_for_patient(patient) or []
        return {str(g.get("code") or "").lower() for g in gates if isinstance(g, dict)}
    except Exception as exc:
        logger.debug("biomarker_workup _gate_codes_for_patient failed: %s", exc)
        return set()


def _is_potential_parp_candidate(
    patient: dict[str, Any],
    gate_codes: set[str] | None = None,
) -> tuple[bool, str]:
    """¿Es el paciente potencial candidato a PARP inhibitor?

    Estrategia (consistente con GodiBot.biomarkers + CXLII propagation):
    Es candidato si CUALQUIERA:
    (a) Algún gate pivotal triggered menciona PARP (single source of truth
        — mismo signal que GodiBot usa para disparar `biomarker_gap:hrr_pre_parp`)
    (b) mCRPC + post-ARSI/taxane (NCCN PROS-2 cat 1, label FDA)
    (c) current_medications incluye un PARP inhibitor (urgente — ya recibe sin workup)

    Returns:
        (is_candidate, reason_string)
    """
    baseline = patient.get("baseline") or {}

    if gate_codes is None:
        gate_codes = _gate_codes_for_patient(patient)

    # (a) Gates triggered que mencionan PARP — signal primario
    parp_related_gates = {c for c in gate_codes if "parp" in c or "olaparib" in c or "talazoparib" in c}
    if parp_related_gates:
        return (True, f"pivotal_gate_triggered:{sorted(parp_related_gates)[0]}")

    # (c) Ya está en PARP — escalation urgente
    cur_meds = baseline.get("current_medications") or patient.get("current_medications") or []
    if isinstance(cur_meds, list):
        meds_blob = " ".join(str(m).lower() for m in cur_meds)
    else:
        meds_blob = str(cur_meds).lower()
    if any(parp in meds_blob for parp in PARP_INHIBITORS):
        return (True, "currently_on_parp_inhibitor_without_workup")

    # (b) Estadio + history fallback
    stage = str(baseline.get("stage") or baseline.get("disease_state")
                or baseline.get("tnm_stage") or "").lower()
    is_mcrpc = "mcrpc" in stage or "castration_resistant" in stage or "m1_crpc" in stage

    if not is_mcrpc:
        return (False, "not_mcrpc_and_no_parp_gate")

    treatments = patient.get("treatments") or []
    has_prior_arsi = False
    has_prior_taxane = False
    for tx in treatments:
        regimen = str(tx.get("regimen") or tx.get("treatment_type") or "").lower()
        if any(k in regimen for k in ("abiraterona", "abiraterone", "enzalutamida",
                                       "enzalutamide", "apalutamida", "apalutamide",
                                       "darolutamida", "darolutamide", "arsi")):
            has_prior_arsi = True
        if any(k in regimen for k in ("docetaxel", "cabazitaxel", "taxane")):
            has_prior_taxane = True

    if has_prior_arsi or has_prior_taxane:
        priors = []
        if has_prior_arsi:
            priors.append("ARSI")
        if has_prior_taxane:
            priors.append("taxane")
        return (True, f"mcrpc_post_{'_'.join(priors)}")

    return (True, "mcrpc_naive_arsi_taxane_workup_recommended")


def _is_potential_lu177_candidate(
    patient: dict[str, Any],
    gate_codes: set[str] | None = None,
) -> tuple[bool, str]:
    """¿Potencial candidato a Lu-177-PSMA-617?

    Estrategia (consistente con GodiBot + CXLII):
    Es candidato si CUALQUIERA:
    (a) Algún gate pivotal triggered menciona Lu-177/PSMA — signal primario
    (b) mCRPC progresión post-ARSI Y post-taxane (VISION criteria)
    (c) current_medications incluye Lu-177-PSMA (escalation urgente)

    Returns:
        (is_candidate, reason_string)
    """
    baseline = patient.get("baseline") or {}

    if gate_codes is None:
        gate_codes = _gate_codes_for_patient(patient)

    # (a) Gates triggered relacionados con Lu-177 / PSMA-PET
    lu177_related_gates = {
        c for c in gate_codes
        if "lutetium" in c or "lu_177" in c or "lu177" in c
        or "psma_pet" in c or "pluvicto" in c
    }
    if lu177_related_gates:
        return (True, f"pivotal_gate_triggered:{sorted(lu177_related_gates)[0]}")

    # (c) Ya en Lu-177 — escalation
    cur_meds = baseline.get("current_medications") or patient.get("current_medications") or []
    if isinstance(cur_meds, list):
        meds_blob = " ".join(str(m).lower() for m in cur_meds)
    else:
        meds_blob = str(cur_meds).lower()
    if any(lu in meds_blob for lu in LU177_CANDIDATES):
        return (True, "currently_on_lu177_without_workup")

    # (b) Estadio + post-2L
    stage = str(baseline.get("stage") or baseline.get("disease_state")
                or baseline.get("tnm_stage") or "").lower()
    is_mcrpc = "mcrpc" in stage or "castration_resistant" in stage or "m1_crpc" in stage

    if not is_mcrpc:
        return (False, "not_mcrpc_and_no_lu177_gate")

    # ECOG check (default 1 si no documentado — conservador)
    ecog_raw = baseline.get("ecog_score")
    try:
        ecog = int(ecog_raw) if ecog_raw is not None else 1
    except (ValueError, TypeError):
        ecog = 1
    if ecog > 2:
        return (False, f"ecog_{ecog}_exceeds_vision_label")

    # Check post-ARSI + post-taxane
    treatments = patient.get("treatments") or []
    has_prior_arsi = False
    has_prior_taxane = False
    for tx in treatments:
        regimen = str(tx.get("regimen") or tx.get("treatment_type") or "").lower()
        if any(k in regimen for k in ("abiraterona", "abiraterone", "enzalutamida",
                                       "enzalutamide", "apalutamida", "apalutamide",
                                       "darolutamida", "darolutamide", "arsi")):
            has_prior_arsi = True
        if any(k in regimen for k in ("docetaxel", "cabazitaxel", "taxane")):
            has_prior_taxane = True

    if has_prior_arsi and has_prior_taxane:
        return (True, "mcrpc_post_arsi_and_taxane_vision_label")
    if has_prior_arsi or has_prior_taxane:
        return (True, "mcrpc_post_arsi_or_taxane_consider_workup")

    return (True, "mcrpc_consider_lu177_when_appropriate_lines")


# ── Evaluación de workup status ───────────────────────────────────────


def _hrr_documented(patient: dict[str, Any]) -> bool:
    """¿HRR mutation panel documentado?

    Considera documentado si CUALQUIERA de estas condiciones:
    - hrr_status ∈ {"Completo_Negativo", "Completo_Positivo", "Positive", "Negative"}
    - hrr_gene presente (str non-empty)
    - hrr_test_result presente (str non-empty)
    - cualquier gen del panel HRR_GENES_PANEL con status ∈ {"wildtype", "mutated", "pathogenic"}
    """
    baseline = patient.get("baseline") or {}
    biomarkers = patient.get("biomarkers") or {}

    hrr_status = str(baseline.get("hrr_status") or biomarkers.get("hrr_status") or "").strip()
    if hrr_status and hrr_status.lower() not in ("desconocido", "unknown", "no_hecho",
                                                  "pending", "not_done", "", "null"):
        return True

    if str(baseline.get("hrr_gene") or "").strip():
        return True
    if str(baseline.get("hrr_test_result") or "").strip():
        return True

    # Per-gen check
    for gene in HRR_GENES_PANEL:
        status = str(baseline.get(f"{gene.lower()}_status") or "").strip()
        if status and status.lower() not in ("no_hecho", "pending", "unknown", "not_done"):
            return True

    return False


def _psma_pet_documented(patient: dict[str, Any]) -> bool:
    """¿PSMA-PET imaging + SUVmax documentado?"""
    baseline = patient.get("baseline") or {}
    imaging = patient.get("imaging") or []

    psma_pos = baseline.get("psma_pet_positive")
    suvmax = baseline.get("psma_pet_max_suvmax") or baseline.get("psma_pet_suvmax")
    if psma_pos is not None or suvmax is not None:
        return True

    # Check imaging records for PSMA-PET entry
    if isinstance(imaging, list):
        for img in imaging:
            if not isinstance(img, dict):
                continue
            modality = str(img.get("modality") or img.get("type") or "").lower()
            if "psma" in modality and "pet" in modality:
                return True

    return False


# ── Build workup target ──────────────────────────────────────────────


def _build_hrr_workup_target(
    patient: dict[str, Any],
    is_candidate: bool,
    candidate_reason: str,
) -> dict[str, Any]:
    """Construye capture target HRR con NCCN/FDA citation + unblock criterion."""
    documented = _hrr_documented(patient)
    return {
        "biomarker": "hrr_mutation_panel",
        "candidate_for": "PARP inhibitor (olaparib/talazoparib/niraparib/rucaparib)",
        "candidate": bool(is_candidate),
        "candidate_reason": candidate_reason,
        "documented": documented,
        "pending": bool(is_candidate and not documented),
        "guideline_anchor": "NCCN PROS-2 cat 1; FDA labels PROfound (NCT02987543), TALAPRO-2 (NCT03395197), MAGNITUDE (NCT03748641)",
        "panel_required": list(HRR_GENES_PANEL),
        "specimen_required": "germinal (sangre periférica) + somático (tejido tumoral o ctDNA si disponible)",
        "action_label": "Solicitar panel HRR completo",
        "action_detail": (
            f"Solicitar panel HRR ({', '.join(HRR_GENES_PANEL)}) germinal Y somático. "
            "Mutaciones BRCA1/2/ATM/PALB2 confirman elegibilidad para PARP inhibitor."
        ),
        "unblock_criterion": (
            "Cargar resultados HRR en intake (hrr_status + hrr_gene si positive). "
            "Esto cerrará automáticamente el `biomarker_gap:hrr_pre_parp` en próxima audit."
        ),
        "clinical_impact_if_omitted": (
            "Response rate <15% en HRR-negativo (MAGNITUDE). Sin HRR documentado, "
            "PARP no debe iniciarse — alto riesgo de toxicidad sin beneficio probable."
        ),
        "severity": "hard_block" if (is_candidate and not documented) else "informational",
        "evidence_tag": "NCCN_PROS2_cat1_PROfound_TALAPRO2",
    }


def _build_psma_pet_workup_target(
    patient: dict[str, Any],
    is_candidate: bool,
    candidate_reason: str,
) -> dict[str, Any]:
    """Construye capture target PSMA-PET con VISION citation + unblock criterion."""
    documented = _psma_pet_documented(patient)
    demographics = patient.get("demographics") or {}
    lu177_access = str(demographics.get("lu_psma_local_access") or "").lower()
    has_local_access = lu177_access in ("si", "sí", "yes", "true", "1")

    return {
        "biomarker": "psma_pet_imaging",
        "candidate_for": "Lu-177-PSMA-617 (Pluvicto)",
        "candidate": bool(is_candidate),
        "candidate_reason": candidate_reason,
        "documented": documented,
        "pending": bool(is_candidate and not documented),
        "guideline_anchor": "VISION trial (NCT03511664); FDA label Pluvicto; EAU 2026 §6.3.2",
        "specimen_required": "PSMA-PET con tracer Ga-68-PSMA-11 o F-18-DCFPyL; documentar SUVmax lesión-índice vs hígado",
        "action_label": "Solicitar PSMA-PET con SUVmax",
        "action_detail": (
            "Solicitar PSMA-PET (Ga-68-PSMA-11 o F-18-DCFPyL) y confirmar SUVmax "
            "lesión-índice > SUVmax hígado (criterio VISION). Documentar avidity "
            "above_liver para elegibilidad Pluvicto."
        ),
        "unblock_criterion": (
            "Cargar resultados PSMA-PET en intake (psma_pet_positive + "
            "psma_pet_max_suvmax). Esto cerrará automáticamente el "
            "`biomarker_gap:psma_pet_pre_lu177` en próxima audit."
        ),
        "clinical_impact_if_omitted": (
            "Contraindicación VISION absoluta: pacientes PSMA-PET negativos NO "
            "deben recibir Lu-177-PSMA-617. Sin imaging, beneficio probable nulo."
        ),
        "severity": "hard_block" if (is_candidate and not documented) else "informational",
        "local_access_warning": (
            "Lu-177-PSMA-617 NO disponible localmente — coordinar referencia a "
            "centro con acceso (gestión apartada)" if not has_local_access else None
        ),
        "evidence_tag": "VISION_NCT03511664_Pluvicto_FDA_label",
    }


# ── EPIC 49+.C (HX3) — MSI-H + Lynch IO pathway ─────────────────────


def _is_msi_high_or_dmmr(patient: dict[str, Any]) -> tuple[bool, str]:
    """Detecta MSI-H / dMMR (mismatch repair deficient) — eligibilidad
    pembrolizumab tumor-agnostic FDA approval."""
    baseline = patient.get("baseline") or {}
    biomarkers = patient.get("biomarkers") or {}

    # Direct fields
    msi_status = str(baseline.get("msi_status")
                      or biomarkers.get("msi_status") or "").lower()
    if msi_status in ("msi_high", "msi-h", "high", "msi_high_dmmr"):
        return (True, f"msi_status={msi_status}")

    # MMR IHC pattern (e.g., MSH2 loss + MSH6 loss)
    mmr_ihc = str(baseline.get("mmr_ihc")
                   or biomarkers.get("mmr_ihc") or "").lower()
    if "loss" in mmr_ihc and any(g in mmr_ihc for g in
                                  ("mlh1", "msh2", "msh6", "pms2")):
        return (True, f"mmr_ihc={mmr_ihc[:60]}")

    # HRR status string may include MSI mention
    hrr_status = str(baseline.get("hrr_status") or "").lower()
    if "msi_high" in hrr_status or "msi-h" in hrr_status:
        return (True, "msi_high_in_hrr_status")

    # TMB high (>10 mut/Mb) is FDA-approved tumor-agnostic indication
    tmb = baseline.get("tmb_mut_mb") or biomarkers.get("tmb_mut_mb")
    try:
        if tmb is not None and float(tmb) >= 10:
            return (True, f"tmb_high_{tmb}_mut_mb")
    except (ValueError, TypeError):
        pass

    return (False, "")


def _is_lynch_syndrome(patient: dict[str, Any]) -> tuple[bool, str]:
    """Detecta Lynch syndrome germline confirmado (cascada familiar trigger)."""
    baseline = patient.get("baseline") or {}
    biomarkers = patient.get("biomarkers") or {}

    lynch_flag = baseline.get("lynch_syndrome_confirmed") or \
                  biomarkers.get("lynch_syndrome_confirmed")
    if lynch_flag:
        gene = str(baseline.get("lynch_germline_gene") or "MMR")
        return (True, f"lynch_confirmed_{gene}")

    # Check germline gene mentioned in hrr_status
    hrr_status = str(baseline.get("hrr_status") or "").upper()
    for gene in LYNCH_SYNDROME_GENES:
        if gene in hrr_status and any(kw in hrr_status.lower()
                                       for kw in ("germinal", "germline", "pathogenic")):
            return (True, f"lynch_gene_{gene}_germinal")

    return (False, "")


def _build_msi_io_workup_target(
    patient: dict[str, Any],
) -> dict[str, Any]:
    """Construye target IO (pembrolizumab) si MSI-H detectado."""
    is_msi, msi_reason = _is_msi_high_or_dmmr(patient)
    is_lynch, lynch_reason = _is_lynch_syndrome(patient)

    if not is_msi:
        return {
            "biomarker": "msi_dmmr_status",
            "candidate_for": "Pembrolizumab tumor-agnostic FDA approval (MSI-H/dMMR)",
            "candidate": False,
            "candidate_reason": "msi_status_negative_or_unknown",
            "documented": True,
            "pending": False,
            "guideline_anchor": "FDA approval 2017 + NCCN PROS-3",
        }

    return {
        "biomarker": "io_pembrolizumab_pathway",
        "candidate_for": "Pembrolizumab 200mg c/3sem (TPR robusta MSI-H mCRPC)",
        "candidate": True,
        "candidate_reason": msi_reason,
        "documented": True,
        "pending": False,
        "guideline_anchor": (
            "FDA tumor-agnostic 2017 MSI-H/dMMR; NCCN PROS-3; "
            "KEYNOTE-158 (NCT02628067)"
        ),
        "action_label": "Considerar pembrolizumab + baseline autoimmune screen",
        "action_detail": (
            "MSI-H/dMMR detectado → pembrolizumab 200mg IV c/3sem indicado. "
            "Baseline autoimmune screen: TSH, cortisol matutino, anti-TPO, ANA. "
            "Si autoimmune activa: ver gate `autoimmune_disease_io_contraindication`."
        ),
        "lynch_syndrome_detected": is_lynch,
        "lynch_cascade_required": is_lynch,
        "lynch_cascade_action": (
            f"Cascada familiar URGENTE ({lynch_reason}): hermanos/hijos para "
            f"colonoscopia, endoscopia, US-TV mujeres. "
            f"Screening multi-cáncer paciente: colonoscopia anual."
        ) if is_lynch else None,
        "evidence_tag": "FDA_tumor_agnostic_pembrolizumab_2017_KEYNOTE158",
    }


# ── Public API ────────────────────────────────────────────────────────


def build_biomarker_workup_bundle(patient_record: dict[str, Any]) -> dict[str, Any]:
    """Sprint 5 entry point — construye bundle de workup biomarker.

    Reusa la misma lógica de detección que GodiBot.biomarkers + el catálogo
    NCCN/EAU de gates pivotal. Cada blocked_hard del baseline CXLII tendrá
    aquí una acción concreta para el clínico.

    Args:
        patient_record: full patient record (con baseline + treatments + imaging)

    Returns:
        {
            "available": bool,
            "evaluation_timestamp": ISO8601,
            "parp_candidate": bool,
            "lu177_candidate": bool,
            "hrr_workup": {...},
            "psma_pet_workup": {...},
            "pending_actions_count": int,
            "any_pending": bool,
            "clinical_summary": str (human-readable),
        }
    """
    if not isinstance(patient_record, dict):
        return {
            "available": False,
            "reason": "invalid_patient_record",
            "pending_actions_count": 0,
            "any_pending": False,
        }

    try:
        # Compute gate codes ONCE (lazy eval shares same path as GodiBot + UI)
        gate_codes = _gate_codes_for_patient(patient_record)
        parp_candidate, parp_reason = _is_potential_parp_candidate(patient_record, gate_codes)
        lu177_candidate, lu177_reason = _is_potential_lu177_candidate(patient_record, gate_codes)

        hrr_workup = _build_hrr_workup_target(patient_record, parp_candidate, parp_reason)
        psma_pet_workup = _build_psma_pet_workup_target(patient_record, lu177_candidate, lu177_reason)
        # EPIC 49+.C (HX3): MSI-H/dMMR + Lynch IO pathway
        msi_io_workup = _build_msi_io_workup_target(patient_record)

        pending = sum(1 for t in (hrr_workup, psma_pet_workup) if t.get("pending"))

        # Clinical summary humano para UI badge
        if pending == 0:
            summary = (
                "Workup biomarker completo — no hay acciones pendientes para "
                "evaluar PARP/Lu-177 según NCCN/EAU."
            ) if (parp_candidate or lu177_candidate) else (
                "Paciente no candidato actual a PARP/Lu-177 — workup biomarker "
                "no requerido en este momento."
            )
        elif pending == 1:
            pending_target = "HRR" if hrr_workup.get("pending") else "PSMA-PET"
            summary = (
                f"1 acción pendiente: solicitar {pending_target} para habilitar "
                f"consideración de terapia dependiente de biomarker."
            )
        else:
            summary = (
                "2 acciones pendientes: solicitar panel HRR + PSMA-PET para "
                "habilitar consideración de PARP inhibitor y Lu-177-PSMA-617."
            )

        return {
            "available": True,
            "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
            "parp_candidate": parp_candidate,
            "parp_candidate_reason": parp_reason,
            "lu177_candidate": lu177_candidate,
            "lu177_candidate_reason": lu177_reason,
            "hrr_workup": hrr_workup,
            "psma_pet_workup": psma_pet_workup,
            "msi_io_workup": msi_io_workup,  # EPIC 49+.C HX3
            "pending_actions_count": pending,
            "any_pending": pending > 0,
            "clinical_summary": summary,
            "evidence_anchors": [
                "NCCN PROS v5.2026 PROS-2 cat 1",
                "EAU 2026 §6.3.2",
                "FDA label PROfound NCT02987543",
                "FDA label VISION NCT03511664 (Pluvicto)",
            ],
        }
    except Exception as exc:
        logger.debug("build_biomarker_workup_bundle failed: %s", exc)
        return {
            "available": False,
            "reason": f"engine_error: {type(exc).__name__}: {exc}",
            "pending_actions_count": 0,
            "any_pending": False,
        }


__all__ = [
    "build_biomarker_workup_bundle",
    "HRR_GENES_PANEL",
    "PARP_INHIBITORS",
    "LU177_CANDIDATES",
]
