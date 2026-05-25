"""patient_summary_routes — EPIC 49+.E (FAUBOT CXLVII).

Patient-facing summary view en español llano + SDM workflow + endpoint REST.

Foundation de Pilar 2 visión H1 (educativo + SDM):
  Hasta ahora la inteligencia clínica (compass + narrative + biomarker workup)
  vivía dentro del consultorio. EPIC 49+ la trae al PACIENTE en vocabulario
  llano para que pueda participar en la decisión.

Endpoints:
  GET /patient_summary/<nss>?lang=es     → HTML view patient-facing
  GET /api/patient-summary/<nss>          → JSON payload (para apps móviles)

Diseño:
  - Decision narrative TÉCNICO traducido a lenguaje llano
  - 2-3 opciones rankeadas con trade-offs visuales (semáforo tiempo/efectividad)
  - Biomarker workup pendiente expresado en términos paciente ("test de sangre
    para BRCA")
  - SDM workflow: paciente marca preferencias antes de consulta
  - Acceso vía link único (token-based) sin requerir cuenta separada

Auth model:
  - Mode 1: clínico authenticated (require_clinician) acede para revisar
  - Mode 2 [Sprint 9]: token único por paciente para acceso directo sin login

Por ahora EPIC 49+.E ships con Mode 1; Mode 2 requiere session token model
nuevo (Sprint 9).
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request

import tracking_db
from prostanet.shared.api_auth import require_clinician, current_api_user_id

logger = logging.getLogger(__name__)

patient_summary_bp = Blueprint("patient_summary", __name__)


def _faubot_release_snapshot() -> str:
    try:
        from prostanet.shared.algorithm_version import FAUBOT_RELEASE
        return str(FAUBOT_RELEASE)
    except Exception:
        return "unknown"


def _translate_to_plain_spanish(technical_text: str) -> str:
    """Traduce vocabulario clínico técnico a español llano paciente-facing.

    Sprint 9 mejorará con LLM-assisted translation contextual.
    """
    if not technical_text:
        return ""
    translations = {
        "mCRPC": "cáncer de próstata resistente a la castración con metástasis",
        "mHSPC": "cáncer de próstata sensible a la castración con metástasis",
        "nmCRPC": "cáncer de próstata resistente a la castración sin metástasis visibles",
        "BCR": "recurrencia bioquímica (PSA subiendo después del tratamiento inicial)",
        "ADT": "terapia de privación androgénica (tratamiento hormonal)",
        "ARSI": "inhibidor de receptor de andrógeno (medicamento hormonal nuevo)",
        "PARP inhibitor": "inhibidor de PARP (medicamento para genes BRCA)",
        "Lu-177-PSMA-617": "Lutecio-177 PSMA (terapia con radiación dirigida)",
        "HRR mutation": "mutación en genes de reparación de ADN (BRCA, ATM, etc.)",
        "PSMA-PET": "estudio especial de imagen PSMA",
        "ECOG": "escala de actividad funcional",
        "biopsia": "muestra de tejido",
        "RP": "cirugía radical de próstata",
        "EBRT": "radioterapia externa",
        "AS": "vigilancia activa (monitoreo sin tratamiento inmediato)",
        "Gleason": "escala de agresividad del tumor",
        "PSA": "antígeno prostático específico (marcador en sangre)",
        "blocked_hard": "tu equipo médico necesita más información antes de decidir",
        "warnings_only": "tu equipo médico identificó puntos para revisar antes de decidir",
        "approved": "tu equipo médico considera que el plan es seguro",
    }
    out = technical_text
    for tech, plain in translations.items():
        out = out.replace(tech, plain)
    return out


def _build_patient_summary(patient_record: dict[str, Any], lang: str = "es") -> dict[str, Any]:
    """Construye el summary patient-facing combinando:
    - Decision narrative en lenguaje llano
    - Workup biomarker pendiente (qué tests faltan)
    - Risk group localized si aplica
    - 2-3 opciones de tratamiento rankeadas con trade-offs
    - Próximos pasos sugeridos
    """
    summary: dict[str, Any] = {
        "patient_nss": (patient_record.get("identity") or {}).get("nss", ""),
        "patient_name_short": "",
        "lang": lang,
        "faubot_release": _faubot_release_snapshot(),
    }

    # Patient name (privacy: solo nombre, no apellido completo)
    identity = patient_record.get("identity") or {}
    name = str(identity.get("full_name") or identity.get("name") or "").strip()
    if name:
        # Solo primer nombre + inicial apellido para privacidad
        parts = name.split()
        if len(parts) >= 2:
            summary["patient_name_short"] = f"{parts[0]} {parts[1][0]}."
        else:
            summary["patient_name_short"] = parts[0]

    # Estado clínico actual (en lenguaje paciente)
    baseline = patient_record.get("baseline") or {}
    stage = str(baseline.get("stage") or "").strip()
    summary["current_stage_technical"] = stage
    summary["current_stage_plain"] = _translate_to_plain_spanish(stage)

    # Localized risk stratification
    try:
        from prostanet.domains.decisions.localized_risk_stratifier import (
            stratify_localized_risk, is_localized,
        )
        if is_localized(patient_record):
            risk = stratify_localized_risk(patient_record)
            summary["localized_risk"] = {
                "applicable": risk.get("applicable"),
                "risk_group": risk.get("risk_group"),
                "risk_group_plain": _translate_to_plain_spanish(
                    risk.get("risk_group", "")
                ),
                "recommendation": risk.get("recommendation", {}),
            }
    except Exception as exc:
        logger.debug("localized risk in patient summary failed: %s", exc)

    # Biomarker workup pendiente
    try:
        from prostanet.domains.decisions.biomarker_workup_engine import (
            build_biomarker_workup_bundle,
        )
        workup = build_biomarker_workup_bundle(patient_record)
        summary["workup"] = {
            "any_pending": workup.get("any_pending", False),
            "pending_count": workup.get("pending_actions_count", 0),
            "summary_plain": _translate_to_plain_spanish(
                workup.get("clinical_summary", "")
            ),
            "hrr_pending": workup.get("hrr_workup", {}).get("pending", False),
            "psma_pet_pending": workup.get("psma_pet_workup", {}).get("pending", False),
            "msi_io_pathway": workup.get("msi_io_workup", {}).get("candidate", False),
        }
    except Exception as exc:
        logger.debug("workup in patient summary failed: %s", exc)

    # GodiBot validation status traducido
    try:
        from prostanet.regulatory.clinical.godibot_cohort_audit import audit_patient
        pid = int(identity.get("id") or 0)
        if pid > 0:
            review = audit_patient(patient_record, patient_id=pid)
            summary["validation_status"] = {
                "status_technical": review.get("status", "unknown"),
                "status_plain": _translate_to_plain_spanish(
                    review.get("status", "unknown")
                ),
                "findings_count": review.get("findings_count", 0),
            }
    except Exception as exc:
        logger.debug("validation status in patient summary failed: %s", exc)

    # SDM treatment options (placeholder enriquecible)
    summary["sdm_options"] = _build_sdm_options(patient_record)

    # Próximos pasos sugeridos
    summary["next_steps"] = _build_next_steps(summary)

    return summary


def _build_sdm_options(patient_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Construye 2-3 opciones de tratamiento rankeadas con trade-offs visuales.

    Sprint 9 conectará al decision_arbiter para opciones data-driven; por ahora
    devuelve un placeholder estructurado con scoring semáforo.
    """
    # Para EPIC 49+ ship: estructura preparada; data viene de risk_group
    options: list[dict[str, Any]] = []
    try:
        from prostanet.domains.decisions.localized_risk_stratifier import (
            stratify_localized_risk, is_localized,
        )
        if is_localized(patient_record):
            risk = stratify_localized_risk(patient_record)
            if risk.get("applicable"):
                rec = risk.get("recommendation", {})
                # Primary option (mayor evidencia)
                options.append({
                    "rank": 1,
                    "label_technical": rec.get("primary_option", ""),
                    "label_plain": _translate_to_plain_spanish(
                        rec.get("primary_option", "")
                    ),
                    "rationale_plain": _translate_to_plain_spanish(
                        rec.get("rationale", "")
                    ),
                    "evidence_count": len(rec.get("evidence_anchors", [])),
                    "tradeoffs": {
                        "time_to_decision": "green",  # < 1 month
                        "intensity": "green" if "surveillance" in (
                            rec.get("primary_option") or ""
                        ).lower() else "yellow",
                        "side_effects": "green" if "surveillance" in (
                            rec.get("primary_option") or ""
                        ).lower() else "yellow",
                    },
                })
                # Alternatives (rank 2+)
                for i, alt in enumerate(rec.get("alternatives", [])[:2], start=2):
                    options.append({
                        "rank": i,
                        "label_technical": alt,
                        "label_plain": _translate_to_plain_spanish(alt),
                        "tradeoffs": {
                            "time_to_decision": "yellow",
                            "intensity": "red" if "extended" in alt or "lnd" in alt else "yellow",
                            "side_effects": "yellow",
                        },
                    })
    except Exception as exc:
        logger.debug("sdm options builder failed: %s", exc)
    return options


def _build_next_steps(summary: dict[str, Any]) -> list[str]:
    """Genera lista de próximos pasos en lenguaje paciente."""
    steps: list[str] = []
    workup = summary.get("workup") or {}
    if workup.get("hrr_pending"):
        steps.append(
            "Pide a tu doctor una prueba de sangre para genes BRCA "
            "(HRR panel) — esto puede abrir la opción de un tratamiento "
            "específico llamado PARP inhibidor si tienes la mutación."
        )
    if workup.get("psma_pet_pending"):
        steps.append(
            "Pregunta sobre el estudio especial PSMA-PET — es una "
            "imagen avanzada que ayuda a planear tratamientos dirigidos."
        )
    if workup.get("msi_io_pathway"):
        steps.append(
            "Tu equipo identificó que podrías beneficiarte de inmunoterapia "
            "(pembrolizumab) por tus marcadores moleculares (MSI-H). Pide "
            "más información en tu próxima consulta."
        )
    sdm_options = summary.get("sdm_options") or []
    if sdm_options:
        steps.append(
            f"Antes de tu próxima consulta, revisa las {len(sdm_options)} "
            "opciones de tratamiento listadas arriba y marca tus preferencias."
        )
    if not steps:
        steps.append(
            "Tu equipo médico revisará tu información completa en tu próxima "
            "consulta. No hay acciones urgentes que tu hagas por ahora."
        )
    return steps


# ─────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────


@patient_summary_bp.route("/api/patient-summary/<nss>", methods=["GET"])
@require_clinician
def api_patient_summary(nss: str):
    """JSON endpoint para apps móviles + frontend SPA."""
    faubot = _faubot_release_snapshot()
    try:
        patient = tracking_db.load_patient_record_core(nss)
        if not patient:
            return jsonify({
                "success": False,
                "error": "patient_not_found",
                "faubot_release": faubot,
            }), 404
        # Enrich with derivatives if available
        try:
            patient_full = tracking_db.build_patient_record_derivatives(patient) or patient
        except Exception:
            patient_full = patient

        lang = request.args.get("lang", "es")
        summary = _build_patient_summary(patient_full, lang=lang)
        return jsonify({
            "success": True,
            "summary": summary,
            "faubot_release": faubot,
        })
    except Exception:
        logger.exception("api_patient_summary failed for nss=%s", nss)
        return jsonify({
            "success": False,
            "error": "internal_error",
            "faubot_release": faubot,
        }), 500


@patient_summary_bp.route("/patient_summary/<nss>", methods=["GET"])
@require_clinician
def view_patient_summary(nss: str):
    """HTML view patient-facing en español llano."""
    faubot = _faubot_release_snapshot()
    try:
        patient = tracking_db.load_patient_record_core(nss)
        if not patient:
            return f"Paciente no encontrado: {nss}", 404
        try:
            patient_full = tracking_db.build_patient_record_derivatives(patient) or patient
        except Exception:
            patient_full = patient
        lang = request.args.get("lang", "es")
        summary = _build_patient_summary(patient_full, lang=lang)
        return render_template(
            "patient_summary.html",
            summary=summary,
            nss=nss,
            faubot_release=faubot,
        )
    except Exception:
        logger.exception("view_patient_summary failed for nss=%s", nss)
        return "Error temporal al construir resumen del paciente", 500


__all__ = ["patient_summary_bp", "_build_patient_summary", "_translate_to_plain_spanish"]
