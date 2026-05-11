from __future__ import annotations

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
    build_post_rt_local_salvage_ranking,
    build_post_rt_transition_bundle,
)


def classify_post_rt_nccn(payload: dict) -> dict:
    failure_definition = build_post_rt_failure_definition(payload)
    salvage_ranking = build_post_rt_local_salvage_ranking(
        payload,
        failure_definition=failure_definition,
        psma_impact={},
    )
    transition_bundle = build_post_rt_transition_bundle(
        payload,
        failure_definition=failure_definition,
        local_salvage_ranking=salvage_ranking,
    )
    phoenix_status = failure_definition.get("phoenix_status")
    if phoenix_status == "met":
        recommendation = "Fallo bioquímico post-RT confirmado por Phoenix; completar restaging y definir salvage local vs MDT vs redirección sistémica según patrón y toxicidad."
    elif failure_definition.get("failure_confirmation_basis") in {"biopsy_proven_local_failure", "radiographic_local_failure"}:
        recommendation = "La falla local equivalente a Phoenix ya está documentada; usar restaging y factibilidad local para elegir modalidad de salvage."
    else:
        recommendation = "No abrir salvage curativo post-RT sin Phoenix met o confirmación local equivalente; cerrar primero la definición de falla."
    return {
        "label": "Post-RT salvage pathway",
        "recommendation": recommendation,
        "post_rt_failure_definition": failure_definition,
        "post_rt_transition_bundle": transition_bundle,
    }
