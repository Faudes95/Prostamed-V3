from __future__ import annotations

from typing import Any

from clinical_scores import docetaxel_fitness
from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
    select_mhspc_frontline_regimens,
    preferred_non_triplet_regimen_label,
)
from prostanet.domains.patient_tracking.therapy_catalog import trial_backbone
from prostanet.shared.gleason_profile import normalize_gleason_profile


MHSPC_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

VISIBLE_TRIALS_BY_STATE = {
    # EPIC 9 Group C (GAP-5) — TALAPRO-3 visible en los 4 fenotipos mHSPC
    # cuando el paciente es HRR+; la gate por biomarcador se aplica en
    # `build_visible_mhspc_trial_matches` para mantener la visibilidad pero
    # marcar `match=False` si el estatus HRR es negativo o desconocido.
    "mcspc_low_volume_sync_oligo": {"ARANOTE", "ARCHES", "TITAN", "ENZAMET", "STAMPEDE", "TALAPRO-3"},
    "mcspc_oligo_metachronous": {"ARANOTE", "ARCHES", "TITAN", "ENZAMET", "TALAPRO-3"},
    "mcspc_high_volume_sync": {"ARANOTE", "ARASENS", "PEACE-1", "CHAARTED", "LATITUDE", "TALAPRO-3"},
    "mcspc_high_volume_metachronous": {"ARANOTE", "ARASENS", "CHAARTED", "TALAPRO-3"},
}
DOCETAXEL_TRIPLETS = {"ADT_DOCETAXEL_DAROLUTAMIDE", "ADT_DOCETAXEL_ABIRATERONE"}

HIDDEN_TRIALS_BY_STATE = {
    "mcspc_low_volume_sync_oligo": {"ARASENS", "PEACE-1", "CHAARTED", "LATITUDE"},
    "mcspc_oligo_metachronous": {"ARASENS", "PEACE-1", "CHAARTED", "LATITUDE", "STAMPEDE"},
    "mcspc_high_volume_sync": set(),
    "mcspc_high_volume_metachronous": {"PEACE-1", "STAMPEDE"},
}

# EPIC 9 Group C (GAP-5) — mismo conjunto HRR canónico usado por
# `mhspc_regimen_selector.TALAPRO3_HRR_POSITIVE_GENES`. Re-declarado aquí
# para evitar import circular cuando `mhspc_evidence` carga antes que el
# selector durante el bootstrap.
TALAPRO3_HRR_POSITIVE_TOKENS = {
    "brca1", "brca2", "atm", "palb2", "cdk12", "chek2",
    "fanca", "mlh1", "mre11a", "nbn", "rad51b", "rad51c",
    "hrr_other", "other_hrr", "positive", "1", "true", "si", "sí", "yes",
}


def _boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "si", "sí", "yes"}


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def resolve_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if state != "mcspc_high_volume":
        return state
    explicit = str(payload.get("disease_temporality", "") or "").strip().lower()
    if explicit in {"sync", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "mcspc_high_volume_sync"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "mcspc_high_volume_metachronous"
    if _boolish(payload.get("metachronous_metastasis", "0")):
        return "mcspc_high_volume_metachronous"
    return "mcspc_high_volume_sync"


def is_mhspc_state(state: str) -> bool:
    return state in MHSPC_STATES


def _state_label(state: str) -> str:
    labels = {
        "mcspc_low_volume_sync_oligo": "mHSPC sincrónico de bajo volumen",
        "mcspc_oligo_metachronous": "mHSPC oligometastásico metacrónico",
        "mcspc_high_volume_sync": "mHSPC sincrónico de alto volumen",
        "mcspc_high_volume_metachronous": "mHSPC metacrónico de alto volumen",
    }
    return labels.get(state, "mHSPC")


def _preferred_non_triplet_label(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    selector_bundle: dict[str, Any] | None = None,
) -> str:
    return preferred_non_triplet_regimen_label(state, payload or {}, selector_bundle=selector_bundle)


def build_triplet_decision(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    docetaxel_bundle: dict[str, Any] | None = None,
    selector_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    exact_state = resolve_mhspc_state(state, payload)
    if exact_state not in VISIBLE_TRIALS_BY_STATE:
        return {}

    docetaxel = dict(docetaxel_bundle or docetaxel_fitness({**payload, "state": exact_state}))
    fit_for_docetaxel = bool(docetaxel.get("fit_for_docetaxel"))
    docetaxel_base_eligibility = str(docetaxel.get("docetaxel_base_eligibility") or "not_assessable")
    docetaxel_verification_status = str(docetaxel.get("docetaxel_verification_status") or "verified")
    docetaxel_block_type = str(docetaxel.get("docetaxel_block_type") or "none")
    docetaxel_required_now = bool(docetaxel.get("docetaxel_required_now"))
    docetaxel_default_intensification = str(docetaxel.get("docetaxel_default_intensification") or "no")
    docetaxel_trial_fit = dict(docetaxel.get("docetaxel_trial_fit") or {})
    hard_stops = list(docetaxel.get("docetaxel_hard_stop_reasons") or [])
    cautions = list(docetaxel.get("docetaxel_caution_reasons") or [])
    fit_summary = str(docetaxel.get("docetaxel_fit_summary") or "").strip()
    missing_inputs = list(docetaxel.get("missing_inputs") or [])
    stale_inputs = list(docetaxel.get("docetaxel_stale_inputs") or [])
    lab_snapshot = dict(docetaxel.get("docetaxel_lab_snapshot") or {})

    status = "not_applicable"
    primary_reason = ""
    why_yes: list[str] = []
    why_no: list[str] = []
    preferred_triplet = ""
    preferred_triplet_code = ""
    supported_triplets: list[str] = []
    evidence_basis: list[str] = []
    selection_bundle = selector_bundle or select_mhspc_frontline_regimens(
        exact_state,
        payload,
        docetaxel_bundle=docetaxel,
    )
    ranking_trace = dict(selection_bundle.get("ranking_trace") or {})
    triplet_rankings = [
        item for item in (selection_bundle.get("frontline_regimen_rankings") or [])
        if str(item.get("regimen_code") or "") in DOCETAXEL_TRIPLETS
    ]
    overall_preferred = dict(selection_bundle.get("preferred_regimen") or {})
    overall_preferred_code = str(overall_preferred.get("regimen_code") or "")
    overall_preferred_label = str(overall_preferred.get("regimen_label") or "")
    if triplet_rankings:
        preferred_triplet = str(triplet_rankings[0].get("regimen_label") or "")
        preferred_triplet_code = str(triplet_rankings[0].get("regimen_code") or "")

    if exact_state == "mcspc_high_volume_sync":
        supported_triplets = ["ARASENS", "PEACE-1"]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARASENS", "PEACE-1"]
        if docetaxel_required_now and docetaxel_verification_status in {"pending_labs", "stale_labs"} and docetaxel_base_eligibility != "contraindicated":
            status = "pending_validation"
            primary_reason = "El escenario sigue siendo candidato a triplete, pero falta validar elegibilidad actual a docetaxel."
            why_yes = [
                "El alto volumen sincrónico mantiene al triplete en discusión clínica real.",
                "ARASENS y PEACE-1 siguen siendo backbones visibles una vez que la elegibilidad a docetaxel quede documentada.",
            ]
            why_no = [
                "No debe declararse contraindicación mientras falte CBC o perfil hepático vigente."
                if docetaxel_verification_status == "pending_labs"
                else "La verificación actual está vencida y debe actualizarse antes de cerrar triplete."
            ]
        elif docetaxel_base_eligibility == "contraindicated":
            status = "contraindicated"
            primary_reason = "El escenario es de alto volumen, pero el paciente tiene contraindicación actual a docetaxel."
            why_no = hard_stops or cautions or ["Las banderas de seguridad actuales bloquean el triplete con docetaxel."]
        elif docetaxel_default_intensification == "yes":
            status = "recommended"
            primary_reason = "El escenario es mHSPC sincrónico de alto volumen y el paciente es apto para docetaxel."
            why_yes = [
                "La discusión triplete sí corresponde en enfermedad de novo/sincrónica de alto volumen.",
                "ARASENS respalda triplete con darolutamida sobre backbone ADT + docetaxel cuando el perfil de seguridad lo favorece.",
                "PEACE-1 puede respaldar triplete con abiraterona en contexto sincrónico/de novo si el balance cardiometabólico y hepático es favorable.",
            ]
        elif docetaxel_default_intensification == "conditional":
            status = "conditional"
            primary_reason = "El escenario permite discutir triplete, pero solo como intensificación condicional por la reserva clínica actual."
            why_yes = [
                "El alto volumen sincrónico mantiene el triplete visible, pero no como default.",
                "La elegibilidad a docetaxel es parcial o con cautela, por lo que la evidencia debe leerse como extrapolación controlada.",
            ]
            why_no = cautions or ["El triplete no debe liderar automáticamente mientras docetaxel siga en estatus condicional."]
        else:
            status = "not_prioritized"
            primary_reason = "El escenario es de alto volumen, pero el paciente no es buen candidato actual a triplete con docetaxel."
            why_no = hard_stops or cautions or ["Faltan datos clínicos para declarar aptitud plena a docetaxel."]
    elif exact_state == "mcspc_high_volume_metachronous":
        supported_triplets = ["ARASENS"]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARASENS"]
        if docetaxel_required_now and docetaxel_verification_status in {"pending_labs", "stale_labs"} and docetaxel_base_eligibility != "contraindicated":
            status = "pending_validation"
            primary_reason = "El escenario mantiene docetaxel en discusión, pero falta validar elegibilidad actual antes de cerrar triplete."
            why_yes = [
                "El alto volumen metacrónico todavía permite intensificación con docetaxel si la elegibilidad se confirma.",
                "ARASENS sigue siendo el backbone trial-like visible cuando la quimioelegibilidad queda documentada.",
            ]
            why_no = [
                "No debe declararse inelegibilidad por laboratorio si la biometría o el panel hepático faltan."
                if docetaxel_verification_status == "pending_labs"
                else "La verificación laboratorial de docetaxel ya no está vigente y debe actualizarse."
            ]
        elif docetaxel_base_eligibility == "contraindicated":
            status = "contraindicated"
            primary_reason = "El escenario es de alto volumen metacrónico, pero existe contraindicación actual a docetaxel."
            why_no = hard_stops or cautions or ["Las banderas de seguridad actuales bloquean el triplete con docetaxel."]
        elif docetaxel_default_intensification == "yes":
            status = "eligible"
            primary_reason = "El escenario es mHSPC metacrónico de alto volumen y el paciente es apto para docetaxel."
            why_yes = [
                "La intensificación fuerte sigue siendo apropiada en alto volumen.",
                "ARASENS es el backbone trial-like preferido en este escenario.",
                "PEACE-1 no debe priorizarse como backbone principal fuera del contexto de novo/sincrónico.",
            ]
        elif docetaxel_default_intensification == "conditional":
            status = "conditional"
            primary_reason = "El escenario mantiene docetaxel como intensificación condicional, pero no como default."
            why_yes = [
                "El alto volumen metacrónico permite reabrir docetaxel si el caso es quimio-elegible con cautela.",
                "La decisión debe explicitar que el encaje trial-like es parcial y que el triplete no es la vía principal visible.",
            ]
            why_no = cautions or ["Docetaxel no tiene hoy un perfil suficientemente robusto para dominar como triplete."]
        else:
            status = "not_prioritized"
            primary_reason = "El escenario es de alto volumen, pero hoy el triplete no se prioriza porque docetaxel no es adecuado o no está suficientemente respaldado."
            why_no = hard_stops or cautions or ["Se requiere completar fitness para docetaxel antes de considerar triplete."]
    elif exact_state == "mcspc_low_volume_sync_oligo":
        preferred_triplet = ""
        supported_triplets = []
        status = "not_applicable"
        primary_reason = "El escenario actual es mHSPC sincrónico de bajo volumen, donde la vía principal es doblete sistémico y consideración de RT al primario."
        why_no = [
            "El triplete no es el backbone principal en bajo volumen sincrónico.",
            "La evidencia visible debe priorizar RT al primario y dobletes con ARPI.",
            "PEACE-1 no debe mostrarse como estudio elegible principal para esta conducta.",
        ]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "STAMPEDE", "ARANOTE", "ARCHES", "TITAN"]
    elif exact_state == "mcspc_oligo_metachronous":
        preferred_triplet = ""
        supported_triplets = []
        status = "not_applicable"
        primary_reason = "El escenario actual es mHSPC oligometastásico metacrónico, donde la vía principal es doblete sistémico y discusión estructurada de MDT."
        why_no = [
            "El triplete no es la estrategia estándar visible en oligometastásico metacrónico.",
            "La evidencia principal favorece intensificación hormonal; docetaxel añade toxicidad sin rol principal aquí.",
            "La discusión clínica debe centrarse en doblete hormonal y MDT en contexto multidisciplinario.",
        ]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARANOTE", "ARCHES", "TITAN", "ENZAMET"]

    if (missing_inputs or stale_inputs) and status in {"recommended", "eligible", "contraindicated", "not_prioritized", "pending_validation"}:
        why_no = list(why_no)
        if missing_inputs:
            why_no.append(f"Datos faltantes que condicionan la decisión: {', '.join(missing_inputs)}.")
        if stale_inputs:
            why_no.append(f"Datos vencidos que deben actualizarse: {', '.join(stale_inputs)}.")

    status_label_map = {
        "recommended": "Sí triplete",
        "eligible": "Triplete elegible",
        "conditional": "Triplete condicional",
        "pending_validation": "Pendiente validar",
        "not_prioritized": "No triplete por ahora",
        "not_applicable": "No aplica triplete",
        "contraindicated": "No triplete",
    }
    tone_map = {
        "recommended": "emerald",
        "eligible": "cyan",
        "conditional": "amber",
        "pending_validation": "amber",
        "not_prioritized": "amber",
        "not_applicable": "slate",
        "contraindicated": "rose",
    }
    preferred_backbone_key = "ARANOTE"
    if preferred_triplet_code == "ADT_DOCETAXEL_ABIRATERONE":
        preferred_backbone_key = "PEACE-1"
    elif preferred_triplet_code == "ADT_DOCETAXEL_DAROLUTAMIDE":
        preferred_backbone_key = "ARASENS"
    elif "ARASENS" in supported_triplets:
        preferred_backbone_key = "ARASENS"
    elif "PEACE-1" in supported_triplets:
        preferred_backbone_key = "PEACE-1"
    preferred_backbone_bundle = trial_backbone(preferred_backbone_key)
    triplet_candidate_status = "none"
    triplet_candidate_only_if_reopened = False
    cross_scope_alignment = "aligned"
    cross_scope_explanation = ""
    triplet_vs_global_preference_note = ""
    if preferred_triplet_code:
        if status in {"recommended", "eligible", "conditional", "pending_validation"}:
            triplet_candidate_status = "active_candidate"
        else:
            triplet_candidate_status = "candidate_only_if_reopened"
            triplet_candidate_only_if_reopened = True
        if overall_preferred_code and overall_preferred_code != preferred_triplet_code:
            cross_scope_alignment = (
                "contradictory_semantics"
                if triplet_candidate_only_if_reopened
                else "subset_divergent"
            )
            cross_scope_explanation = (
                f"El mejor triplete posible sería {preferred_triplet}, pero el tratamiento global preferente hoy es {overall_preferred_label or overall_preferred_code}."
            )
            triplet_vs_global_preference_note = (
                f"Hoy el triplete no lidera globalmente; {preferred_triplet} solo reabre liderazgo si mejora la elegibilidad a triplete o cambia el balance de seguridad."
                if triplet_candidate_only_if_reopened
                else f"El subranking de tripletes favorece {preferred_triplet}, pero el ranking global favorece {overall_preferred_label or overall_preferred_code} por mejor balance clínico."
            )
        elif overall_preferred_code == preferred_triplet_code:
            triplet_vs_global_preference_note = "El mejor triplete coincide con el tratamiento global preferente."

    return {
        "show": True,
        "state": exact_state,
        "state_label": _state_label(exact_state),
        "ranking_policy_version": selection_bundle.get("ranking_policy_version", ""),
        "status": status,
        "status_label": status_label_map.get(status, status),
        "decision": status_label_map.get(status, status),
        "tone": tone_map.get(status, "slate"),
        "is_triplet_candidate": status in {"recommended", "eligible", "conditional", "pending_validation"},
        "primary_reason": primary_reason,
        "summary": primary_reason or ranking_trace.get("why_not_triplet", ""),
        "why_yes": why_yes,
        "why_no": why_no,
        "docetaxel_fitness_summary": fit_summary,
        "docetaxel_base_eligibility": docetaxel_base_eligibility,
        "docetaxel_verification_status": docetaxel_verification_status,
        "docetaxel_block_type": docetaxel_block_type,
        "docetaxel_required_now": docetaxel_required_now,
        "docetaxel_default_intensification": docetaxel_default_intensification,
        "docetaxel_trial_fit": docetaxel_trial_fit,
        "hard_stop_reasons": hard_stops,
        "caution_reasons": cautions,
        "missing_inputs": missing_inputs,
        "stale_inputs": stale_inputs,
        "docetaxel_lab_snapshot": lab_snapshot,
        "preferred_triplet_regimen_code": preferred_triplet_code,
        "preferred_triplet_candidate_regimen_code": preferred_triplet_code,
        "preferred_triplet_candidate_label": preferred_triplet or "",
        "preferred_triplet_backbone": preferred_backbone_bundle.get("recommended_trial_backbone", "") if preferred_triplet else "",
        "preferred_triplet_backbone_label": preferred_triplet or "",
        "supported_triplet_backbones": supported_triplets,
        "preferred_non_triplet_backbone_label": _preferred_non_triplet_label(exact_state, payload, selector_bundle=selection_bundle),
        "overall_preferred_frontline_regimen": overall_preferred,
        "overall_preferred_frontline_regimen_code": overall_preferred_code,
        "overall_preferred_frontline_regimen_label": overall_preferred_label,
        "ranking_scope": "triplet_subset",
        "triplet_candidate_status": triplet_candidate_status,
        "triplet_candidate_only_if_reopened": triplet_candidate_only_if_reopened,
        "cross_scope_alignment": cross_scope_alignment,
        "cross_scope_explanation": cross_scope_explanation,
        "triplet_vs_global_preference_note": triplet_vs_global_preference_note,
        "evidence_basis": evidence_basis,
        "ranking_trace": ranking_trace,
        "why_not_triplet": ranking_trace.get("why_not_triplet", ""),
        "hard_blocks": dict(ranking_trace.get("hard_blocks") or {}),
    }


def visible_trials_for_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> tuple[set[str], set[str]]:
    exact_state = resolve_mhspc_state(state, payload or {})
    return (
        set(VISIBLE_TRIALS_BY_STATE.get(exact_state, set())),
        set(HIDDEN_TRIALS_BY_STATE.get(exact_state, set())),
    )


def build_visible_mhspc_trial_matches(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    triplet_decision: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    payload = payload or {}
    exact_state = resolve_mhspc_state(state, payload)
    if exact_state not in VISIBLE_TRIALS_BY_STATE:
        return [], 0
    visible, hidden = visible_trials_for_mhspc_state(exact_state, payload)
    gleason_profile = normalize_gleason_profile(payload)
    triplet = triplet_decision or build_triplet_decision(exact_state, payload)
    fit_for_docetaxel = bool(triplet.get("is_triplet_candidate"))
    matches: list[dict[str, Any]] = []
    for trial in sorted(visible):
        match = True
        reason = "Estudio concordante con el escenario clínico actual."
        if trial == "ARASENS":
            match = fit_for_docetaxel
            reason = (
                "Triplete respaldado por ARASENS porque el caso es de alto volumen y es apto para docetaxel."
                if match
                else "ARASENS no aplica hoy porque el triplete con docetaxel no está indicado o no es seguro."
            )
        elif trial == "PEACE-1":
            match = exact_state == "mcspc_high_volume_sync" and fit_for_docetaxel
            reason = (
                "PEACE-1 se correlaciona con enfermedad de novo/sincrónica de alto volumen apta para docetaxel."
                if match
                else "PEACE-1 no debe presentarse como backbone principal fuera del contexto sincrónico de alto volumen."
            )
        elif trial == "STAMPEDE":
            reason = "STAMPEDE respalda el uso de RT al primario en enfermedad metastásica de bajo volumen sincrónica."
        elif trial == "ARANOTE":
            reason = "ARANOTE respalda doblete con darolutamida en mHSPC, incluyendo subgrupos de alto y bajo volumen."
        elif trial in {"ARCHES", "TITAN", "ENZAMET"}:
            reason = "Ensayo concordante con intensificación hormonal en mHSPC."
        elif trial == "CHAARTED":
            match = "high_volume" in exact_state and fit_for_docetaxel
            reason = (
                "CHAARTED es más concordante con alto volumen y aptitud a docetaxel."
                if match
                else "CHAARTED no se prioriza en este subescenario porque la intensificación con docetaxel no es la vía principal."
            )
        elif trial == "LATITUDE":
            high_risk_latitude = (
                ((gleason_profile.get("gleason_score") or 0) >= 8)
                + int((gleason_profile.get("isup_grade") or 0) >= 4)
                + int(bool(gleason_profile.get("has_adverse_tertiary_pattern")))
                + (_safe_int(payload.get("metastasis_count") or 0) >= 3)
                + int(_boolish(payload.get("visceral_metastases")) or str(payload.get("metastasis_site", "")).lower() == "visceral")
            ) >= 2
            match = exact_state == "mcspc_high_volume_sync" and high_risk_latitude
            reason = (
                "LATITUDE es concordante con mHSPC de novo de alto riesgo."
                if match
                else "LATITUDE no se prioriza porque este caso no reproduce el marco de alto riesgo de novo del ensayo."
            )
        elif trial == "TALAPRO-3":
            # EPIC 9 Group C (GAP-5) — gate estricto por biomarcador HRR.
            # Acepta tokens canónicos de `hrr_status`, `hrr_gene`, o flags
            # específicos BRCA1/2/ATM/PALB2. Cualquier otro valor (incluido
            # "not_tested", "negative", "unknown", o vacío) resulta en
            # match=False con razón explícita.
            hrr_tokens = {
                str(payload.get("hrr_status", "") or "").strip().lower(),
                str(payload.get("hrr_gene", "") or "").strip().lower(),
                str(payload.get("brca1_status", "") or "").strip().lower(),
                str(payload.get("brca2_status", "") or "").strip().lower(),
                str(payload.get("atm_status", "") or "").strip().lower(),
                str(payload.get("palb2_status", "") or "").strip().lower(),
                str(payload.get("cdk12_status", "") or "").strip().lower(),
            }
            hrr_positive = any(token in TALAPRO3_HRR_POSITIVE_TOKENS for token in hrr_tokens if token)
            match = hrr_positive
            reason = (
                "TALAPRO-3 respalda el doblete de precisión talazoparib + enzalutamida + ADT en mHSPC HRR-mutado (rPFS HR≈0.67, pivotal abstract ASCO GU 2025)."
                if match
                else "TALAPRO-3 no aplica: requiere alteración HRR (BRCA1/2, ATM, PALB2, CDK12, CHEK2, FANCA, MLH1, MRE11A, NBN, RAD51B, RAD51C) documentada; sin HRR+ el régimen queda bloqueado."
            )
        backbone_bundle = trial_backbone(trial)
        matches.append(
            {
                "trial": trial,
                "study_name": trial,
                "match": match,
                "eligible": match,
                "visible": True,
                "reason": reason,
                "status": "aplica" if match else "no_aplica",
                "recommended_trial_backbone": backbone_bundle.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": backbone_bundle.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_note": backbone_bundle.get("recommended_trial_backbone_note", ""),
            }
        )
    return matches, len(hidden)
