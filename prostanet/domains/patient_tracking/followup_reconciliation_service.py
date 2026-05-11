from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import regimen_label
from prostanet.shared.presentation_text import resolve_option_label
from prostanet.shared.ui_value_normalizer import normalize_field_label, normalize_ui_value


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _display_value(field_name: str, value: Any) -> str:
    if value in (None, ""):
        return "No disponible"
    normalized_field_name = str(field_name or "").strip().replace(" ", "_")
    if normalized_field_name in {"drug_scheme", "current_treatment"}:
        regimen = regimen_label(value)
        if regimen:
            return regimen
    return str(normalize_ui_value(resolve_option_label(normalized_field_name, value)))


def build_decision_recalculation_trace(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    latest_assessment: dict[str, Any] | None = None,
    longitudinal_truth_snapshot: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    transition_resolution: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = longitudinal_truth_snapshot or patient.get("longitudinal_truth_snapshot") or {}
    superseded_inputs = list(snapshot.get("superseded_inputs") or [])
    decisive_visit = dict(snapshot.get("latest_clinically_decisive_visit") or {})
    assessment_inputs = ((latest_assessment or patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    transition_resolution = dict(transition_resolution or {})
    care_intent_contract = dict(care_intent_contract or {})
    changed_today: list[str] = []
    why_changed: list[str] = []
    display_changed_fields = []

    for item in superseded_inputs[:6]:
        raw_field_name = str(item.get("field_name") or "").strip()
        field_label = normalize_field_label(raw_field_name, default=raw_field_name.replace("_", " "))
        display_changed_fields.append(field_label)
        changed_today.append(
            f"{field_label}: {_display_value(raw_field_name, item.get('previous_value'))} → {_display_value(raw_field_name, item.get('current_value'))}"
        )
    if not changed_today:
        for field_name in list(decisive_visit.get("changed_fields") or decisive_visit.get("fields_changed") or [])[:6]:
            field_label = normalize_field_label(field_name, default=str(field_name).replace("_", " "))
            display_changed_fields.append(field_label)
            changed_today.append(f"{field_label} actualizado en la visita longitudinal más reciente")

    if reconciliation and reconciliation.get("state_conflict_flag"):
        why_changed.append(str(reconciliation.get("state_conflict_reason") or "La evolución longitudinal cambió la etapa reconciliada."))

    castrate_status = str((snapshot.get("field_values") or {}).get("castrate_testosterone_status") or "")
    progression_pattern = str((snapshot.get("field_values") or {}).get("progression_pattern") or "")
    if castrate_status == "confirmed_castrate" and progression_pattern in {"radiographic", "clinical", "mixed"}:
        why_changed.append("La testosterona ya está en rango de castración y la progresión persiste, por lo que la recomendación debe recalcularse sobre el escenario resistente a castración.")
    if _is_present((snapshot.get("field_values") or {}).get("psa")) and _is_present(assessment_inputs.get("psa")):
        if str((snapshot.get("field_values") or {}).get("psa")) != str(assessment_inputs.get("psa")):
            why_changed.append("El PSA más reciente ya no coincide con el valor usado en la evaluación inicial.")

    if not why_changed and changed_today:
        why_changed.append("La nueva visita aportó datos clínicamente suficientes para reemplazar inputs previos del intake.")
    if transition_resolution.get("policy") == "auto_applied":
        why_changed.insert(0, "La transición longitudinal ya era clínicamente dominante y se autoaplicó sin requerir confirmación manual adicional.")

    return {
        "available": bool(decisive_visit),
        "state": state,
        "management_track": management_track,
        "headline": str(care_intent_contract.get("headline") or (next_best_action or {}).get("title") or "Sin recálculo longitudinal visible"),
        "what_changed_today": changed_today[:6],
        "why_changed": why_changed[:4],
        "latest_clinically_decisive_visit": decisive_visit,
        "superseded_inputs": superseded_inputs,
        "display_changed_fields": display_changed_fields[:6],
        "visibility_status": "actionable" if decisive_visit.get("clinically_sufficient") else "contextual",
        "transition_resolution": transition_resolution,
    }
