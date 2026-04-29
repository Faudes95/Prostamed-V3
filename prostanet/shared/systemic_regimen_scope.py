from __future__ import annotations

from typing import Any


MHSPC_SCOPE_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

SCOPE_LABELS = {
    "not_applicable": "No aplica comparación sistémica de doblete/triplete",
    "mhspc_doublet_triplet": "Competencia sistémica mHSPC",
    "nmcrpc_arpi": "Selección ARPI en nmCRPC",
    "mcrpc_sequence": "Secuencia sistémica en mCRPC",
}


def resolve_systemic_regimen_scope(state: str) -> str:
    normalized = str(state or "").strip()
    if normalized in MHSPC_SCOPE_STATES:
        return "mhspc_doublet_triplet"
    if normalized == "m0_crpc":
        return "nmcrpc_arpi"
    if normalized == "m1_crpc":
        return "mcrpc_sequence"
    return "not_applicable"


def systemic_regimen_scope_label(scope: str) -> str:
    return SCOPE_LABELS.get(str(scope or "").strip(), SCOPE_LABELS["not_applicable"])


def build_systemic_regimen_scope_contract(
    state: str,
    module_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_state = str(state or "").strip()
    result = dict(module_result or {})
    scope = resolve_systemic_regimen_scope(normalized_state)
    competition_classes: list[str] = []
    excluded_classes: list[str] = []
    narrative = ""

    if normalized_state == "mcspc_low_volume_sync_oligo":
        competition_classes = ["mhspc_doublets", "rt_primary_context"]
        excluded_classes = ["mhspc_triplets", "docetaxel_monotherapy_default"]
        narrative = "Bajo volumen sincrónico: compiten dobletes y RT al primario; el triplete no debe liderar."
    elif normalized_state == "mcspc_oligo_metachronous":
        competition_classes = ["mhspc_doublets", "mdt_context"]
        excluded_classes = ["mhspc_triplets", "docetaxel_monotherapy_default"]
        narrative = "Oligometastásico metacrónico: compiten dobletes y discusión MDT; el triplete no debe abrirse por inercia."
    elif normalized_state == "mcspc_high_volume_sync":
        competition_classes = ["mhspc_doublets", "mhspc_triplets"]
        excluded_classes = ["docetaxel_monotherapy_default"]
        narrative = "Alto volumen sincrónico: pueden competir dobletes y tripletes si la elegibilidad a docetaxel está realmente cerrada."
    elif normalized_state in {"mcspc_high_volume_metachronous", "mcspc_high_volume"}:
        competition_classes = ["mhspc_doublets", "mhspc_triplets"]
        excluded_classes = ["docetaxel_monotherapy_default", "peace1_like_leakage"]
        narrative = "Alto volumen metacrónico: la competencia sistémica sigue abierta, pero con trial-fit más estrecho y sin extrapolar escenarios de novo."
    elif normalized_state == "m0_crpc":
        competition_classes = ["nmcrpc_arpi"]
        excluded_classes = ["mhspc_triplets", "docetaxel_monotherapy_default", "mcrpc_sequence"]
        narrative = "nmCRPC: la decisión es entre ARPI y observación estructurada, nunca entre dobletes/tripletes mHSPC."
    elif normalized_state == "m1_crpc":
        competition_classes = ["mcrpc_sequence"]
        excluded_classes = ["mhspc_triplets", "nmcrpc_arpi_frontline", "docetaxel_monotherapy_default"]
        narrative = "mCRPC: la selección es secuencial y biomarcador-dirigida; no debe renderizarse como competencia de triplete."
    elif normalized_state == "adt_progression_verification":
        excluded_classes = ["mhspc_triplets", "nmcrpc_arpi_frontline", "mcrpc_sequence"]
        narrative = "Verificación bajo ADT: no debe intensificarse hasta cerrar castración, progresión válida y reestadificación."
    else:
        excluded_classes = ["mhspc_triplets", "nmcrpc_arpi_frontline", "mcrpc_sequence"]
        narrative = "El escenario actual no debe exponer competencia sistémica de dobletes/tripletes."

    triplet_decision = dict(result.get("triplet_decision") or {})
    preferred_regimen = dict(result.get("preferred_frontline_regimen") or {})
    candidate_regimens = list(result.get("candidate_regimens_under_consideration") or [])
    if not candidate_regimens:
        candidate_regimens = [
            str(item.get("regimen_code") or "")
            for item in list(result.get("eligible_treatments") or [])
            if isinstance(item, dict) and str(item.get("regimen_code") or "")
        ]

    return {
        "scope": scope,
        "scope_label": systemic_regimen_scope_label(scope),
        "state": normalized_state,
        "competition_classes": competition_classes,
        "excluded_classes": excluded_classes,
        "triplet_reasoning_visible": scope == "mhspc_doublet_triplet",
        "triplet_decision_status": str(triplet_decision.get("status") or ""),
        "preferred_regimen_code": str(preferred_regimen.get("regimen_code") or ""),
        "candidate_regimens_under_consideration": candidate_regimens,
        "narrative": narrative,
    }
