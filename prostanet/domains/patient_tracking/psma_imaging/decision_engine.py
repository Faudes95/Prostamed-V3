from __future__ import annotations

from typing import Any


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def build_psma_decision_impact(
    profile: dict[str, Any] | None,
    *,
    state: str = "",
    management_track: str = "",
    patient: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = dict(profile or {})
    if not profile.get("available"):
        return {
            "confidence": "unknown",
            "clinical_pattern": "not_available",
            "stage_shift": "unknown",
            "decision_domains_affected": [],
            "recommended_actions": [],
            "rationale": "No hay PSMA-PET estructurado disponible para cambiar la decisión clínica actual.",
            "visibility_status": "insufficient_data",
        }

    rads = str(profile.get("psma_rads_score") or "")
    clinical_pattern = str(profile.get("clinical_pattern") or "")
    uptake_pattern = str(profile.get("psma_uptake_pattern") or "")
    pattern = clinical_pattern or uptake_pattern or "indeterminado"
    stage_after = str(profile.get("psma_stage_after_psma") or "")
    confidence = "medium"
    if rads in {"4", "5"}:
        confidence = "high"
    elif rads == "3":
        confidence = "low"
    elif rads in {"1", "2"}:
        confidence = "low"
    elif not profile.get("structured_complete"):
        confidence = "medium" if profile.get("source_mode") == "legacy" else "low"

    if profile.get("psma_negative_dominant_lesions"):
        confidence = "low"

    decision_domains: list[str] = []
    actions: list[str] = []
    rationale_parts: list[str] = []
    stage_shift = "upstaged" if profile.get("psma_upstaged_vs_conventional") is True else "no_change"
    if profile.get("psma_upstaged_vs_conventional") is False:
        stage_shift = "no_change"
    elif profile.get("psma_upstaged_vs_conventional") is None:
        stage_shift = "unknown"

    if clinical_pattern == "local_pelvic" or uptake_pattern == "focal":
        rationale_parts.append("El patrón focal/local-pélvico favorece una lectura dirigida y potencialmente rescatable.")
        if state in {"recurrence_bcr", "post_radiotherapy_or_local_salvage"}:
            decision_domains.extend(["salvage_rt", "local_rescue"])
            actions.append("Mantener visible la ventana curativa y reforzar rescate local / RT de salvamento si el contexto técnico lo permite.")
    elif clinical_pattern == "oligometastatic" or uptake_pattern == "multifocal":
        rationale_parts.append("La captación multifocal sugiere carga limitada pero no estrictamente local.")
        decision_domains.extend(["mdt", "restaging"])
        actions.append("Considerar MDT/SBRT o rescate multimodal si el burden sigue siendo bajo y la confianza es alta.")
    elif clinical_pattern == "diseminado" or uptake_pattern == "diseminado":
        rationale_parts.append("El patrón diseminado reduce el peso de una estrategia local aislada.")
        decision_domains.extend(["systemic_transition", "restaging"])
        actions.append("Bajar prioridad de rescate local aislado y reforzar transición sistémica o discusión multidisciplinaria.")
    else:
        rationale_parts.append("La estructura PSMA existe, pero el patrón clínico sigue siendo indeterminado.")

    if stage_after in {"M1b", "M1c"}:
        decision_domains.append("advanced_state")
        rationale_parts.append("El estadio posterior por PSMA documenta enfermedad metastásica de mayor peso clínico.")
    elif stage_after == "M1a":
        decision_domains.append("nodal_m1")

    if rads == "3":
        actions.append("Interpretar con cautela y correlacionar con imagen convencional, evolución de PSA y contexto anatómico antes de escalar conducta.")
        rationale_parts.append("PSMA-RADS 3 mantiene incertidumbre diagnóstica y no debe sostener por sí solo una decisión mayor.")
    elif rads in {"1", "2"}:
        actions.append("No escalar conducta mayor con este PSMA aislado; priorizar correlación adicional.")
        rationale_parts.append("PSMA-RADS bajo reduce la confianza para cambiar estrategia terapéutica.")

    radioligand = str(profile.get("psma_radioligand") or "")
    if radioligand == "18F-PSMA-1007":
        actions.append("Mantener cautela con lesiones óseas dudosas bajo 18F-PSMA-1007 y correlacionar si la conducta depende de ellas.")
        rationale_parts.append("El radioligando 18F-PSMA-1007 puede aumentar la incertidumbre en ciertos hallazgos óseos.")

    if profile.get("psma_negative_dominant_lesions"):
        decision_domains.append("radioligand_eligibility")
        actions.append("Degradar la confianza para radioligando o MDT basado solo en PSMA hasta resolver lesiones dominantes PSMA-negativas.")
        rationale_parts.append("La discordancia biológica por lesiones dominantes PSMA-negativas debilita rutas terapéuticas dirigidas.")

    if state == "m1_crpc":
        decision_domains.append("radioligand_eligibility")
        if confidence == "high" and not profile.get("psma_negative_dominant_lesions"):
            actions.append("La elegibilidad a radioligando puede sostenerse con mayor fuerza documental.")
        elif confidence != "high":
            actions.append("La elegibilidad a radioligando debe mostrarse como parcial o con cautela, no plena.")
    if state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo"}:
        decision_domains.append("oligomet_pathway")

    visibility = "actionable" if actions else "contextual"
    if confidence == "unknown":
        visibility = "insufficient_data"

    return {
        "confidence": confidence,
        "clinical_pattern": clinical_pattern or pattern,
        "stage_shift": stage_shift,
        "decision_domains_affected": sorted(set(decision_domains)),
        "recommended_actions": actions,
        "rationale": " ".join(rationale_parts).strip() or "PSMA estructurado disponible sin impacto mayor documentado.",
        "visibility_status": visibility,
    }
