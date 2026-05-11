from __future__ import annotations

import re
import unicodedata
from typing import Any

from prostanet.shared.ui_value_normalizer import normalize_field_label


def normalize_oracle_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text.lower())
    return text.strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        normalized = normalize_oracle_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(str(item).strip())
    return deduped


_ACTION_ALIAS_GROUPS = {
    "active surveillance": ["active surveillance", "vigilancia activa"],
    "surveillance": ["surveillance", "vigilancia", "observacion", "observación", "monitorizacion", "monitorización"],
    "rt": ["rt", "radioterapia", "radioterapia externa", "radioterapia definitiva", "radioterapia al primario", "rt al primario"],
    "adt": [
        "adt",
        "terapia de privacion androgenica",
        "terapia de privación androgénica",
        "hormonal",
        "castracion",
        "castración",
        "androgenica",
        "androgénica",
    ],
    "biopsia": ["biopsia", "rebiopsia", "confirmatoria", "biopsia dirigida"],
    "tratamiento": ["tratamiento", "definitivo", "tratamiento local definitivo", "prostatectomia radical", "prostatectomía radical", "radioterapia"],
    "salvage": ["salvage", "rescate", "radioterapia de rescate"],
    "rescate": ["rescate", "salvage"],
    "review": ["review", "revision", "revisión", "uropatologica", "uropatológica", "multidisciplinaria"],
    "estudio": ["estudio", "seguimiento diagnostico", "seguimiento diagnóstico", "mri seriados", "biopsia dirigida"],
    "reabrir": ["reabrir", "biopsia dirigida", "confirmacion histologica", "confirmación histológica"],
    "sist": ["sistemic", "sistemico", "sistémico", "intensificacion", "intensificación", "olaparib", "docetaxel", "cabazitaxel", "darolutamida", "abiraterona", "enzalutamida"],
    "crpc": ["crpc", "resistente a la castracion", "resistente a la castración", "darolutamida", "apalutamida", "enzalutamida", "abiraterona", "olaparib", "cabazitaxel", "docetaxel"],
    "parp": ["parp", "olaparib", "talazoparib", "niraparib"],
    "enzalutamide": ["enzalutamide", "enzalutamida"],
    "enzalutamida": ["enzalutamide", "enzalutamida"],
    "darolutamide": ["darolutamide", "darolutamida"],
    "darolutamida": ["darolutamide", "darolutamida"],
    "metastasis-directed therapy": ["metastasis-directed therapy", "metastasis directed therapy", "mdt", "sbrt"],
    "rt al primario": ["rt al primario", "radioterapia al primario", "radioterapia al tumor primario"],
    "reestadificacion": ["reestadificacion", "reestadificación", "restaging", "reclasificar fuera de nmcrpc"],
    "vigilancia": ["vigilancia", "vigilancia activa", "observacion", "observación", "monitorizacion", "monitorización"],
    "current": ["current", "vigente", "vigente hoy", "lista hoy", "evidencia vigente"],
    "aging": ["aging", "revisar vigencia", "evidencia en revision", "evidencia en revisión", "actualizar evidencia"],
    "stale": ["stale", "evidencia vencida", "bloqueada por evidencia vencida", "bloqueado por evidencia vencida"],
    "ready_to_release": ["ready_to_release", "lista hoy", "lista para liberar", "vigente hoy"],
    "aging_review_needed": ["aging_review_needed", "revisar vigencia", "actualizar evidencia", "evidencia en revisión"],
    "blocked_by_stale_evidence": ["blocked_by_stale_evidence", "bloqueada por evidencia vencida", "bloqueado por evidencia vencida", "evidencia vencida"],
}

_SEMANTIC_FAMILY_ALIASES = {
    "active_surveillance": ["vigilancia activa", "active surveillance", "surveillance"],
    "definitive_local_therapy": ["tratamiento definitivo", "prostatectomia radical", "prostatectomía radical", "radioterapia definitiva", "radioterapia"],
    "rt_plus_adt": ["radioterapia", "radioterapia externa", "terapia de privacion androgenica", "terapia de privación androgénica", "adt"],
    "arpi_nmcrpc": ["darolutamida", "enzalutamida", "apalutamida", "arpi"],
    "parp_family": ["parp", "olaparib", "niraparib", "talazoparib"],
    "salvage_systemic_redirect": ["enzalutamida", "enzalutamide", "intensificacion sistemica", "intensificación sistémica"],
    "local_primary_rt": ["rt al primario", "radioterapia al primario"],
    "mdt_candidate": ["mdt", "metastasis-directed therapy", "sbrt"],
    "shared_decision_localized": ["vigilancia activa", "prostatectomia radical", "prostatectomía radical", "radioterapia definitiva"],
    "nmcrpc_restaging": ["reestadificacion", "reestadificación", "reclasificar fuera de nmcrpc"],
    "nmcrpc_observation": ["vigilancia", "observacion", "observación", "monitorizacion", "monitorización"],
}

_NORMALIZED_ACTION_ALIASES: dict[str, list[str]] = {}
for key, aliases in _ACTION_ALIAS_GROUPS.items():
    group = _dedupe([key, *aliases])
    for alias in group:
        _NORMALIZED_ACTION_ALIASES[normalize_oracle_text(alias)] = group

_NORMALIZED_FAMILY_ALIASES = {
    normalize_oracle_text(key): _dedupe([*aliases]) for key, aliases in _SEMANTIC_FAMILY_ALIASES.items()
}


def action_aliases_for(term: Any) -> list[str]:
    normalized = normalize_oracle_text(term)
    if not normalized:
        return []
    return list(_NORMALIZED_ACTION_ALIASES.get(normalized) or [str(term).strip()])


def semantic_family_aliases(family: Any) -> list[str]:
    normalized = normalize_oracle_text(family)
    if not normalized:
        return []
    return list(_NORMALIZED_FAMILY_ALIASES.get(normalized) or [])


def build_action_oracle_contract(
    oracle: dict[str, Any] | None,
    *,
    fallback_label: str = "",
) -> dict[str, Any]:
    oracle = dict(oracle or {})
    expected_action_label = str(oracle.get("expected_action_label") or "").strip()
    expected_action_contains = str(oracle.get("expected_action_contains") or "").strip()
    action_semantic_family = str(oracle.get("action_semantic_family") or "").strip()
    visibility_expectation = str(oracle.get("visibility_expectation") or "headline").strip().lower() or "headline"
    specificity_policy = str(oracle.get("specificity_policy") or "").strip() or (
        "generic_or_specific_ok" if expected_action_contains or action_semantic_family else "specific_required"
    )

    headline_terms = list(oracle.get("headline_expected_aliases") or [])
    supporting_terms = list(oracle.get("supporting_expected_aliases") or [])
    base_terms = [expected_action_label, expected_action_contains]
    if not any(base_terms) and fallback_label:
        base_terms = [fallback_label]
    if not headline_terms:
        headline_terms = [term for term in base_terms if term]
    if visibility_expectation == "supporting" and not supporting_terms:
        supporting_terms = list(headline_terms)

    headline_aliases: list[str] = [str(term).strip() for term in headline_terms if str(term or "").strip()]
    supporting_aliases: list[str] = [str(term).strip() for term in supporting_terms if str(term or "").strip()]
    for term in headline_terms + base_terms:
        headline_aliases.extend(action_aliases_for(term))
    for term in supporting_terms + base_terms:
        supporting_aliases.extend(action_aliases_for(term))
    family_aliases = semantic_family_aliases(action_semantic_family)
    if family_aliases:
        headline_aliases.extend(family_aliases)
        supporting_aliases.extend(family_aliases)

    headline_aliases = _dedupe(headline_aliases)
    supporting_aliases = _dedupe(supporting_aliases)
    if visibility_expectation == "supporting" and not supporting_aliases:
        supporting_aliases = list(headline_aliases)

    display_label = (
        expected_action_label
        or expected_action_contains
        or (headline_aliases[0] if headline_aliases else "")
        or fallback_label
    )
    return {
        "display_label": display_label,
        "headline_expected_aliases": headline_aliases,
        "supporting_expected_aliases": supporting_aliases,
        "action_semantic_family": action_semantic_family,
        "visibility_expectation": visibility_expectation,
        "specificity_policy": specificity_policy,
    }


def _match_alias(texts: list[str], aliases: list[str]) -> str:
    haystack = " | ".join(normalize_oracle_text(item) for item in texts if item)
    if not haystack:
        return ""
    for alias in aliases:
        normalized = normalize_oracle_text(alias)
        if normalized and normalized in haystack:
            return alias
    return ""


def match_action_contract(
    *,
    headline_texts: list[str],
    supporting_texts: list[str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    headline_alias = _match_alias(headline_texts, list(contract.get("headline_expected_aliases") or []))
    supporting_alias = _match_alias(
        supporting_texts,
        list(contract.get("supporting_expected_aliases") or contract.get("headline_expected_aliases") or []),
    )
    visibility_expectation = str(contract.get("visibility_expectation") or "headline").strip().lower() or "headline"
    if headline_alias:
        return {"matched": True, "matched_alias": headline_alias, "matched_visibility_layer": "headline"}
    if supporting_alias:
        layer = "supporting" if visibility_expectation == "supporting" else "page"
        return {"matched": True, "matched_alias": supporting_alias, "matched_visibility_layer": layer}
    return {"matched": False, "matched_alias": "", "matched_visibility_layer": "miss"}


def action_contract_matches_texts(
    texts: list[str],
    contract: dict[str, Any],
) -> bool:
    return bool(
        _match_alias(texts, list(contract.get("headline_expected_aliases") or []))
        or _match_alias(texts, list(contract.get("supporting_expected_aliases") or []))
    )


def _build_alias_group(
    aliases: list[str],
    *,
    semantic_family: str = "",
) -> list[str]:
    resolved: list[str] = []
    for alias in aliases:
        if not str(alias or "").strip():
            continue
        resolved.extend(action_aliases_for(alias))
    if semantic_family:
        resolved.extend(semantic_family_aliases(semantic_family))
    return _dedupe(resolved)


def _build_field_alias_group(fields: list[str]) -> list[str]:
    aliases: list[str] = []
    for field in fields:
        text = str(field or "").strip()
        if not text:
            continue
        aliases.append(text)
        aliases.append(text.replace("_", " "))
        aliases.append(normalize_field_label(text, default=text))
    return _dedupe(aliases)


def build_advanced_therapy_oracle_contract(
    oracle: dict[str, Any] | None,
) -> dict[str, Any]:
    oracle = dict(oracle or {})
    selected_family = str(oracle.get("expected_selected_therapy_family") or "").strip()
    selected_aliases = _build_alias_group(
        list(oracle.get("expected_selected_therapy_aliases") or []),
        semantic_family=selected_family,
    )
    blocked_aliases = _build_alias_group(list(oracle.get("expected_blocked_therapy_aliases") or []))
    deprioritized_aliases = _build_alias_group(
        list(oracle.get("expected_deprioritized_therapy_aliases") or [])
    )
    prerequisite_aliases = _build_alias_group(
        list(oracle.get("expected_prerequisite_actions") or [])
    )
    local_adjunct_aliases = _build_alias_group(
        list(oracle.get("expected_local_adjuncts") or [])
    )
    selected_evidence_status_aliases = _build_alias_group(
        [str(oracle.get("expected_selected_evidence_status") or "").strip()]
    )
    release_status_aliases = _build_alias_group(
        [str(oracle.get("expected_release_status") or "").strip()]
    )
    refresh_action_aliases = _build_alias_group(
        list(oracle.get("expected_refresh_actions") or [])
    )
    stale_block_field_aliases = _build_field_alias_group(
        list(oracle.get("expected_stale_block_fields") or [])
    )
    return {
        "expected_selected_therapy_family": selected_family,
        "selected_therapy_aliases": selected_aliases,
        "blocked_therapy_aliases": blocked_aliases,
        "deprioritized_therapy_aliases": deprioritized_aliases,
        "prerequisite_action_aliases": prerequisite_aliases,
        "local_adjunct_aliases": local_adjunct_aliases,
        "selected_evidence_status_aliases": selected_evidence_status_aliases,
        "release_status_aliases": release_status_aliases,
        "refresh_action_aliases": refresh_action_aliases,
        "stale_block_field_aliases": stale_block_field_aliases,
    }


def match_advanced_therapy_panel(
    *,
    selected_texts: list[str],
    viable_texts: list[str],
    blocked_texts: list[str],
    prerequisite_texts: list[str],
    local_adjunct_texts: list[str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    selected_alias = _match_alias(selected_texts, list(contract.get("selected_therapy_aliases") or []))
    blocked_alias = _match_alias(blocked_texts, list(contract.get("blocked_therapy_aliases") or []))
    deprioritized_alias = _match_alias(
        viable_texts + blocked_texts,
        list(contract.get("deprioritized_therapy_aliases") or []),
    )
    prerequisite_alias = _match_alias(
        prerequisite_texts + blocked_texts + selected_texts,
        list(contract.get("prerequisite_action_aliases") or []),
    )
    local_adjunct_alias = _match_alias(
        local_adjunct_texts + viable_texts,
        list(contract.get("local_adjunct_aliases") or []),
    )
    selected_evidence_alias = _match_alias(
        selected_texts,
        list(contract.get("selected_evidence_status_aliases") or []),
    )
    release_status_alias = _match_alias(
        selected_texts + blocked_texts,
        list(contract.get("release_status_aliases") or []),
    )
    refresh_action_alias = _match_alias(
        selected_texts + blocked_texts + prerequisite_texts,
        list(contract.get("refresh_action_aliases") or []),
    )
    stale_block_field_alias = _match_alias(
        blocked_texts + prerequisite_texts + selected_texts,
        list(contract.get("stale_block_field_aliases") or []),
    )
    return {
        "selected_matched": bool(selected_alias or not list(contract.get("selected_therapy_aliases") or [])),
        "selected_alias": selected_alias,
        "blocked_matched": bool(blocked_alias or not list(contract.get("blocked_therapy_aliases") or [])),
        "blocked_alias": blocked_alias,
        "deprioritized_matched": bool(
            deprioritized_alias or not list(contract.get("deprioritized_therapy_aliases") or [])
        ),
        "deprioritized_alias": deprioritized_alias,
        "prerequisite_matched": bool(
            prerequisite_alias or not list(contract.get("prerequisite_action_aliases") or [])
        ),
        "prerequisite_alias": prerequisite_alias,
        "local_adjunct_matched": bool(
            local_adjunct_alias or not list(contract.get("local_adjunct_aliases") or [])
        ),
        "local_adjunct_alias": local_adjunct_alias,
        "selected_evidence_status_matched": bool(
            selected_evidence_alias or not list(contract.get("selected_evidence_status_aliases") or [])
        ),
        "selected_evidence_status_alias": selected_evidence_alias,
        "release_status_matched": bool(
            release_status_alias or not list(contract.get("release_status_aliases") or [])
        ),
        "release_status_alias": release_status_alias,
        "refresh_action_matched": bool(
            refresh_action_alias or not list(contract.get("refresh_action_aliases") or [])
        ),
        "refresh_action_alias": refresh_action_alias,
        "stale_block_fields_matched": bool(
            stale_block_field_alias or not list(contract.get("stale_block_field_aliases") or [])
        ),
        "stale_block_field_alias": stale_block_field_alias,
    }


__all__ = [
    "action_aliases_for",
    "action_contract_matches_texts",
    "build_advanced_therapy_oracle_contract",
    "build_action_oracle_contract",
    "match_action_contract",
    "match_advanced_therapy_panel",
    "normalize_oracle_text",
    "semantic_family_aliases",
]
