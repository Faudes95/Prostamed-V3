from __future__ import annotations

from typing import Any


WINDOW_REGISTRY: dict[str, dict[str, Any]] = {
    "diagnostic_mri_biopsy_window": {
        "owner_role": "uro_oncology",
        "sla_days": 21,
        "decision_domain_blocked": "diagnostic_confirmation",
        "clinical_consequence_if_delayed": "Se retrasa el cierre diagnóstico y la selección inicial de manejo.",
        "target_state_if_closed": "localized_initial",
        "redirect_state_if_negative": "diagnostic_workup",
    },
    "localized_modality_closure_window": {
        "owner_role": "tumor_board",
        "sla_days": 21,
        "decision_domain_blocked": "local_therapy_selection",
        "clinical_consequence_if_delayed": "La modalidad local preferente permanece provisional y puede desplazar el tratamiento óptimo.",
        "target_state_if_closed": "localized_initial",
        "redirect_state_if_negative": "shared_decision_required",
    },
    "progression_verification_closure_window": {
        "owner_role": "advanced_disease_team",
        "sla_days": 14,
        "decision_domain_blocked": "crpc_restage",
        "clinical_consequence_if_delayed": "No puede cerrarse la ruta entre mHSPC, verificación bajo ADT y CRPC metastásico.",
        "target_state_if_closed": "m1_crpc",
        "redirect_state_if_negative": "mhspc_reclassification",
    },
    "precision_hrr_testing_window": {
        "owner_role": "precision_oncology",
        "sla_days": 28,
        "decision_domain_blocked": "precision_pathway",
        "clinical_consequence_if_delayed": "Se retrasa elegibilidad a PARP y secuencias biomarcadas.",
        "target_state_if_closed": "precision_pathway_ready",
        "redirect_state_if_negative": "precision_pathway_unavailable",
    },
    "psma_eligibility_window": {
        "owner_role": "nuclear_medicine",
        "sla_days": 14,
        "decision_domain_blocked": "restaging",
        "clinical_consequence_if_delayed": "La ruta de restadificación y selección terapéutica permanece incompleta.",
        "target_state_if_closed": "restaging_complete",
        "redirect_state_if_negative": "conventional_restaging_only",
    },
}


def build_window_registry_entry(window_key: str, window: dict[str, Any] | None = None) -> dict[str, Any]:
    window = dict(window or {})
    registry = dict(WINDOW_REGISTRY.get(str(window_key or "").strip(), {}))
    required_inputs = list(window.get("required_inputs") or window.get("missing_decisive_fields") or [])
    return {
        "window_key": str(window_key or "").strip(),
        "window_status": window.get("window_status") or "open",
        "decision_domain_blocked": registry.get("decision_domain_blocked") or "",
        "required_fact_keys": required_inputs,
        "missing_fact_keys": required_inputs,
        "owner_role": registry.get("owner_role") or "clinical_governance",
        "sla_days": int(registry.get("sla_days") or 0),
        "clinical_consequence_if_delayed": registry.get("clinical_consequence_if_delayed")
        or window.get("if_not_closed_clinical_consequence")
        or "",
        "target_state_if_closed": registry.get("target_state_if_closed") or "",
        "redirect_state_if_negative": registry.get("redirect_state_if_negative") or "",
        "what_closes_this_window": window.get("what_closes_this_window") or "",
    }


def enrich_window_with_registry(window: dict[str, Any]) -> dict[str, Any]:
    entry = build_window_registry_entry(str(window.get("window_key") or ""), window)
    enriched = dict(window)
    enriched.update(
        {
            "decision_domain_blocked": entry.get("decision_domain_blocked"),
            "required_fact_keys": entry.get("required_fact_keys"),
            "missing_fact_keys": entry.get("missing_fact_keys"),
            "owner_role": entry.get("owner_role"),
            "sla_days": entry.get("sla_days"),
            "clinical_consequence_if_delayed": entry.get("clinical_consequence_if_delayed"),
            "target_state_if_closed": entry.get("target_state_if_closed"),
            "redirect_state_if_negative": entry.get("redirect_state_if_negative"),
        }
    )
    return enriched
