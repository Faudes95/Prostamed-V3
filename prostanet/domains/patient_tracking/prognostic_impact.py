from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
from prostanet.domains.patient_tracking.therapy_catalog import (
    normalize_regimen_code,
    regimen_label,
    therapy_catalog_entries,
)


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
POST_RP_STATES = {"post_prostatectomy", "recurrence_bcr"}
LOCALIZED_STATES = {"localized_initial"}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _unique_preserving(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    ordered: list[Any] = []
    for value in values:
        marker = repr(value)
        if value in (None, "", [], {}) or marker in seen:
            continue
        seen.add(marker)
        ordered.append(value)
    return ordered


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        if isinstance(value, str) and value.endswith("%"):
            return float(value.replace("%", "").strip())
        return float(value)
    except (TypeError, ValueError):
        return None


def _tool_map(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("tool_key") or ""): dict(card)
        for card in cards
        if str(card.get("tool_key") or "")
    }


def _result_data(card: dict[str, Any]) -> dict[str, Any]:
    result = card.get("result_data")
    return dict(result) if isinstance(result, dict) else {}


def _risk_group(card: dict[str, Any]) -> str:
    result = _result_data(card)
    if _is_present(result.get("risk_group")):
        return str(result.get("risk_group")).upper()
    primary = str(card.get("primary_result") or "")
    if "·" in primary:
        return primary.split("·", 1)[1].strip().upper()
    return primary.strip().upper()


def _category_value(card: dict[str, Any], *keys: str) -> str:
    result = _result_data(card)
    for key in keys:
        if _is_present(result.get(key)):
            return str(result.get(key)).upper()
    return str(card.get("primary_result") or "").upper()


def _percent_from_card(card: dict[str, Any], key: str) -> float | None:
    result = _result_data(card)
    if _is_present(result.get(key)):
        return _safe_float(result.get(key))
    return _safe_float(str(card.get("primary_result") or ""))


def _therapy_lookup() -> dict[str, dict[str, Any]]:
    return {item["regimen_code"]: item for item in therapy_catalog_entries()}


def _current_regimen(patient: dict[str, Any], raw_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_input = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    candidates = [
        raw_input.get("drug_scheme"),
        raw_input.get("current_treatment"),
    ]
    followups = sorted(patient.get("follow_ups") or [], key=lambda item: str(item.get("visit_date") or ""), reverse=True)
    if followups:
        candidates.extend([followups[0].get("drug_scheme"), followups[0].get("current_treatment")])
    treatments = sorted(patient.get("treatments") or [], key=lambda item: str(item.get("start_date") or ""), reverse=True)
    if treatments:
        candidates.extend([treatments[0].get("drug_scheme"), treatments[0].get("regimen_code"), treatments[0].get("treatment_name")])

    lookup = _therapy_lookup()
    for candidate in candidates:
        normalized = normalize_regimen_code(candidate)
        if not normalized:
            continue
        meta = dict(lookup.get(normalized) or {})
        return {
            "regimen_code": normalized,
            "label": regimen_label(normalized),
            "therapy_class": meta.get("therapy_class", ""),
            "agents": list(meta.get("agents") or []),
        }
    return {
        "regimen_code": "",
        "label": "",
        "therapy_class": "",
        "agents": [],
    }


def _backbone_codes(profile: dict[str, Any]) -> list[str]:
    backbone = profile.get("recommended_trial_backbone")
    if isinstance(backbone, list):
        return [str(item) for item in backbone if str(item or "").strip()]
    if _is_present(backbone):
        return [str(backbone)]
    return []


def _alignment_note(status: str, current_label: str, trial_label: str, matched_trials: list[str]) -> str:
    trial_text = ", ".join(matched_trials) if matched_trials else "el estudio comparable"
    if status == "aligned":
        return f"El esquema actual ({current_label}) coincide con el backbone de {trial_text}: {trial_label}."
    if status == "adjacent":
        return f"El esquema actual ({current_label}) se parece al backbone de {trial_text}, pero no es idéntico a {trial_label}."
    if status == "divergent":
        return f"El esquema actual ({current_label}) se aparta del backbone de {trial_text} ({trial_label}); conviene documentar por qué."
    if trial_label:
        return f"Existe backbone trial-like aplicable ({trial_label}), pero aún no hay esquema actual suficiente para compararlo."
    return "Aún no existe backbone trial-like suficiente para comparar el tratamiento actual."


def _build_backbone_alignment(
    *,
    patient: dict[str, Any],
    raw_assessment: dict[str, Any] | None,
    current_trial_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = dict(current_trial_profile or {})
    backbone_codes = _backbone_codes(profile)
    trial_label = str(profile.get("recommended_trial_backbone_label") or "")
    current = _current_regimen(patient, raw_assessment)
    current_code = str(current.get("regimen_code") or "")
    current_label = str(current.get("label") or "")
    if not backbone_codes:
        return {}

    lookup = _therapy_lookup()
    backbone_meta = [dict(lookup.get(code) or {"regimen_code": code, "label_clinico": regimen_label(code), "therapy_class": "", "agents": []}) for code in backbone_codes]
    alignment_status = "unknown"
    if current_code:
        if current_code in backbone_codes:
            alignment_status = "aligned"
        else:
            current_agents = {str(item).lower() for item in current.get("agents") or []}
            current_class = str(current.get("therapy_class") or "")
            adjacent = False
            for meta in backbone_meta:
                backbone_agents = {str(item).lower() for item in meta.get("agents") or []}
                backbone_class = str(meta.get("therapy_class") or "")
                if current_class and current_class == backbone_class:
                    adjacent = True
                    break
                if current_agents and backbone_agents and current_agents.intersection(backbone_agents):
                    adjacent = True
                    break
            alignment_status = "adjacent" if adjacent else "divergent"

    return {
        "trial_backbone": backbone_codes,
        "trial_backbone_label": trial_label,
        "current_regimen": current_code,
        "current_regimen_label": current_label,
        "alignment_status": alignment_status,
        "matched_trials": list(profile.get("matched_trials") or []),
        "clinical_note": _alignment_note(alignment_status, current_label or "sin esquema documentado", trial_label, list(profile.get("matched_trials") or [])),
    }


def _modifier(
    *,
    modifier_key: str,
    title: str,
    severity: str,
    why_it_matters_now: str,
    decision_domains_affected: list[str],
    recommended_actions: list[str],
    followup_impact: list[str],
    source_tools: list[str],
) -> dict[str, Any]:
    return {
        "modifier_key": modifier_key,
        "title": title,
        "severity": severity,
        "why_it_matters_now": why_it_matters_now,
        "decision_domains_affected": list(decision_domains_affected or []),
        "recommended_actions": list(recommended_actions or []),
        "followup_impact": list(followup_impact or []),
        "source_tools": list(source_tools or []),
    }


def _build_capture_targets(
    *,
    patient: dict[str, Any],
    state: str,
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for card in cards:
        raw_fields = [str(field) for field in (card.get("missing_input_keys") or []) if str(field or "").strip()]
        if str(card.get("status") or "") not in {"ready_missing_inputs", "missing_inputs"} or not raw_fields:
            continue
        title = str(card.get("title") or card.get("tool_key") or "herramienta pronóstica")
        targets.append(
            {
                "tool_key": str(card.get("tool_key") or ""),
                "title": f"Completar inputs de {title}",
                "action_label": f"Completar inputs de {title}",
                "primary_button_label": f"Completar inputs de {title}",
                "action_type": "capture",
                "expected_document_type": "",
                "raw_fields": raw_fields,
                "fields": list(card.get("missing_inputs") or []),
                "rationale": str(card.get("meaning") or card.get("clinical_relation") or "Completa los datos faltantes para refinar el riesgo pronóstico."),
                "decision_affected": str(card.get("tool_key") or ""),
                "module_owner": "risk_tools",
                "capture_group": "risk_tool_completion",
            }
        )

    has_decipher = any(str(card.get("tool_key") or "") == "decipher" for card in cards)
    if state in POST_RP_STATES and not has_decipher:
        targets.append(
            {
                "tool_key": "decipher",
                "title": "Subir resultado Decipher",
                "action_label": "Subir resultado Decipher",
                "primary_button_label": "Subir resultado Decipher",
                "action_type": "document",
                "expected_document_type": "genomic_report",
                "raw_fields": [],
                "fields": ["Reporte genómico Decipher"],
                "rationale": "El resultado Decipher puede reclasificar el riesgo biológico postquirúrgico y cambiar la conversación de rescate.",
                "decision_affected": "genomic_risk_refinement",
                "module_owner": "risk_tools",
                "capture_group": "genomic_report",
            }
        )

    targets.sort(key=lambda item: (0 if item.get("action_type") == "capture" else 1, str(item.get("title") or "")))
    return targets


def build_prognostic_impact_bundle(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    raw_assessment: dict[str, Any] | None = None,
    risk_tools_bundle: dict[str, Any] | None = None,
    current_trial_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk_tools_bundle = risk_tools_bundle or build_risk_tools_panel(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment={},
    )
    cards = [dict(card) for card in (risk_tools_bundle.get("cards") or []) if isinstance(card, dict)]
    upgrade_panel = dict(risk_tools_bundle.get("upgrade_panel") or {})
    card_by_key = _tool_map(cards)
    modifiers: list[dict[str, Any]] = []

    capra = card_by_key.get("capra", {})
    damico = card_by_key.get("damico", {})
    mskcc_preop = card_by_key.get("mskcc_preop", {})
    partin = card_by_key.get("partin", {})
    capra_s = card_by_key.get("capra_s", {})
    mskcc_post = card_by_key.get("mskcc_bcr_post_rp", {})
    decipher = card_by_key.get("decipher", {})
    oncotype = card_by_key.get("oncotype_dx_gps", {})
    prolaris = card_by_key.get("prolaris", {})

    if state in LOCALIZED_STATES:
        capra_risk = _risk_group(capra)
        damico_risk = _risk_group(damico)
        behaves_like_high = bool((upgrade_panel.get("unfavorable_intermediate_behaving_like_high_risk") or {}).get("active"))
        if capra_risk == "ALTO" or damico_risk == "ALTO" or behaves_like_high:
            severe_now = "critical" if sum(item == "ALTO" for item in [capra_risk, damico_risk]) >= 2 or behaves_like_high else "warning"
            modifiers.append(
                _modifier(
                    modifier_key="localized_unfavorable_biology",
                    title="Biología localizada desfavorable",
                    severity=severe_now,
                    why_it_matters_now="CAPRA/D'Amico y la reclasificación actual sugieren un caso localizado con mayor agresividad de la que aparenta el riesgo basal.",
                    decision_domains_affected=["localized_strategy", "multimodal_counseling"],
                    recommended_actions=[
                        "Priorizar discusión multimodal antes del tratamiento definitivo.",
                        "Evitar resumir el caso como favorable si los refinadores clínicos ya son adversos.",
                    ],
                    followup_impact=[
                        "Acelerar staging y deliberación definitiva sin demoras innecesarias.",
                        "Completar nomogramas quirúrgicos y genómica si cambian la conversación clínica.",
                    ],
                    source_tools=["capra", "damico"] + (["upgrade_panel"] if behaves_like_high else []),
                )
            )

        organ_confined = _percent_from_card(mskcc_preop, "probabilidad_raw")
        lni_prob = _percent_from_card(partin, "lni_prob")
        ece_prob = _percent_from_card(partin, "ece_prob")
        adverse_nomogram = any(
            value is not None
            for value in [
                organ_confined if organ_confined is not None and organ_confined < 60 else None,
                lni_prob if lni_prob is not None and lni_prob >= 5 else None,
                ece_prob if ece_prob is not None and ece_prob >= 20 else None,
            ]
        )
        if adverse_nomogram:
            modifiers.append(
                _modifier(
                    modifier_key="localized_surgical_staging_risk",
                    title="Nomogramas quirúrgicos adversos",
                    severity="warning",
                    why_it_matters_now="Los nomogramas preoperatorios sugieren menor probabilidad de órgano confinado o mayor riesgo patológico adverso.",
                    decision_domains_affected=["surgical_planning", "localized_strategy"],
                    recommended_actions=[
                        "Explicar riesgo de patología adversa antes de decidir tratamiento radical.",
                        "Documentar explícitamente si se contempla disección ganglionar o intensificación local.",
                    ],
                    followup_impact=[
                        "No simplificar el counseling preoperatorio como riesgo localizado bajo.",
                    ],
                    source_tools=["mskcc_preop", "partin"],
                )
            )

    if state in POST_RP_STATES or (patient.get("surgery") or {}).get("surgery_date"):
        capra_s_risk = _risk_group(capra_s)
        mskcc_risk = _category_value(mskcc_post, "risk_category")
        mskcc_5y = _percent_from_card(mskcc_post, "bcr_free_5y")
        if capra_s_risk == "ALTO" or mskcc_risk == "DESFAVORABLE" or (mskcc_5y is not None and mskcc_5y < 65):
            severity = "critical" if capra_s_risk == "ALTO" and (mskcc_risk == "DESFAVORABLE" or (mskcc_5y is not None and mskcc_5y < 65)) else "warning"
            modifiers.append(
                _modifier(
                    modifier_key="post_rp_high_bcr_risk",
                    title="Riesgo alto de BCR post-RP",
                    severity=severity,
                    why_it_matters_now="CAPRA-S y/o el nomograma MSKCC post-RP sugieren mayor probabilidad de recurrencia bioquímica temprana.",
                    decision_domains_affected=["post_rp_surveillance", "salvage_discussion"],
                    recommended_actions=[
                        "Priorizar PSA ultrasensible y documentar ventana de rescate.",
                        "Abrir explícitamente la discusión de adyuvancia/rescate si la trayectoria clínica lo amerita.",
                    ],
                    followup_impact=[
                        "Intensificar la vigilancia de PSA ultrasensible.",
                        "Mantener una narrativa visible de ventana de rescate temprana.",
                    ],
                    source_tools=["capra_s", "mskcc_bcr_post_rp"],
                )
            )

        surgery = patient.get("surgery") or {}
        adverse_pathology = any(
            (
                bool((upgrade_panel.get("pathologic_upgrade") or {}).get("active")),
                str(surgery.get("pathological_stage") or "").upper().startswith("PT3"),
                bool(surgery.get("lni_pathological")),
                bool(surgery.get("surgical_margin_status")),
            )
        )
        if adverse_pathology:
            modifiers.append(
                _modifier(
                    modifier_key="surgical_pathology_adverse",
                    title="Patología quirúrgica adversa",
                    severity="warning",
                    why_it_matters_now="La patología posquirúrgica muestra señales de mayor agresividad o upgrade estructurado.",
                    decision_domains_affected=["post_rp_surveillance", "salvage_discussion"],
                    recommended_actions=[
                        "Mantener visible la patología adversa en cada revisión postoperatoria.",
                    ],
                    followup_impact=[
                        "Evitar espaciar seguimiento si aún no se ha aclarado la ventana de rescate.",
                    ],
                    source_tools=["upgrade_panel", "surgery"],
                )
            )

    genomic_high = any(
        "ALTO" in _category_value(card, "decipher_risk", "category")
        for card in [decipher, oncotype, prolaris]
        if card
    ) or bool((upgrade_panel.get("genomic_upclassification") or {}).get("active"))
    if genomic_high:
        modifiers.append(
            _modifier(
                modifier_key="genomic_high_risk_refinement",
                title="Refinamiento genómico de alto riesgo",
                severity="warning",
                why_it_matters_now="La genómica documentada sugiere una biología más agresiva que la esperada por riesgo clínico basal.",
                decision_domains_affected=["genomic_refinement", "followup_intensity"],
                recommended_actions=[
                    "Usar el resultado genómico para matizar el riesgo basal y la urgencia del seguimiento.",
                ],
                followup_impact=[
                    "Mostrar el caso como biológicamente más agresivo en el plan maestro y en el copiloto.",
                ],
                source_tools=[
                    tool
                    for tool, card in [("decipher", decipher), ("oncotype_dx_gps", oncotype), ("prolaris", prolaris)]
                    if card
                ] + (["upgrade_panel"] if bool((upgrade_panel.get("genomic_upclassification") or {}).get("active")) else []),
            )
        )

    if bool((upgrade_panel.get("unfavorable_intermediate_behaving_like_high_risk") or {}).get("active")):
        modifiers.append(
            _modifier(
                modifier_key="unfavorable_intermediate_behaving_like_high_risk",
                title="Intermedio desfavorable con comportamiento de alto riesgo",
                severity="critical",
                why_it_matters_now="El caso comenzó como intermedio desfavorable, pero ahora muestra evidencia histopatológica o genómica de mayor agresividad.",
                decision_domains_affected=["risk_refinement", "followup_intensity"],
                recommended_actions=[
                    "Escalar la narrativa clínica a comportamiento de alto riesgo y reflejarlo en seguimiento y counseling.",
                ],
                followup_impact=[
                    "Evitar cadencias complacientes propias de un intermedio convencional.",
                ],
                source_tools=["upgrade_panel"],
            )
        )

    modifiers.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity") or "info"), 99),
            str(item.get("title") or ""),
        )
    )
    capture_targets = _build_capture_targets(patient=patient, state=state, cards=cards)
    backbone_alignment = _build_backbone_alignment(
        patient=patient,
        raw_assessment=raw_assessment,
        current_trial_profile=current_trial_profile,
    )
    recommended_actions = _unique_preserving(
        [
            action
            for item in modifiers
            for action in list(item.get("recommended_actions") or [])
        ]
        + [
            str(item.get("action_label") or "")
            for item in capture_targets
            if str(item.get("action_label") or "")
        ]
    )[:8]
    followup_impact = _unique_preserving(
        [impact for item in modifiers for impact in list(item.get("followup_impact") or [])]
    )[:8]
    cadence_adjusted_by = [str(item.get("modifier_key") or "") for item in modifiers if item.get("followup_impact")]

    return {
        "prognostic_modifiers": modifiers,
        "recommended_actions": recommended_actions,
        "followup_impact": followup_impact,
        "capture_targets": capture_targets,
        "backbone_alignment": backbone_alignment,
        "cadence_adjusted_by": cadence_adjusted_by,
        "summary": {
            "modifier_count": len(modifiers),
            "critical_modifier_count": sum(1 for item in modifiers if item.get("severity") == "critical"),
            "capture_target_count": len(capture_targets),
            "backbone_alignment_status": backbone_alignment.get("alignment_status", "unknown"),
        },
        "state": state,
        "management_track": management_track,
    }


def summarize_prognostic_impact_for_cohort(records: list[dict[str, Any]]) -> dict[str, Any]:
    modifier_counts: dict[str, int] = {}
    alignment_stats = {"aligned": 0, "adjacent": 0, "divergent": 0, "unknown": 0}
    followup_impact_count = 0
    incomplete_scores_count = 0
    high_risk_impact_count = 0

    for record in records:
        if not record or not record.get("identity"):
            continue
        assessment = record.get("latest_assessment") or {}
        state = assessment.get("state") or (record.get("prior_history") or {}).get("current_state") or ""
        management_track = (record.get("latest_signal_snapshot") or {}).get("reconciled_management_track") or ""
        current_trial_profile = (record.get("latest_trial_benchmark_snapshot") or {}).get("current_trial_profile") or {}
        bundle = build_prognostic_impact_bundle(
            patient=record,
            state=state,
            management_track=management_track,
            raw_assessment=assessment,
            current_trial_profile=current_trial_profile,
        )
        for modifier in bundle.get("prognostic_modifiers", []):
            key = str(modifier.get("modifier_key") or "")
            if not key:
                continue
            modifier_counts[key] = modifier_counts.get(key, 0) + 1
        if bundle.get("cadence_adjusted_by"):
            followup_impact_count += 1
        if bundle.get("capture_targets"):
            incomplete_scores_count += 1
        if any(str(item.get("severity") or "") == "critical" for item in bundle.get("prognostic_modifiers", [])):
            high_risk_impact_count += 1
        alignment = str((bundle.get("backbone_alignment") or {}).get("alignment_status") or "unknown")
        alignment_stats[alignment] = alignment_stats.get(alignment, 0) + 1

    return {
        "modifier_counts": modifier_counts,
        "alignment_stats": alignment_stats,
        "followup_impact_count": followup_impact_count,
        "incomplete_scores_count": incomplete_scores_count,
        "high_risk_impact_count": high_risk_impact_count,
    }
