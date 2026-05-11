from __future__ import annotations

from typing import Any


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}, "No aplica", "No documentado"):
            return value
    return ""


def _item_guideline_source(item: dict[str, Any]) -> str:
    evidence_basis = [str(entry) for entry in list(item.get("evidence_basis") or []) if str(entry).strip()]
    lowered = " ".join(entry.lower() for entry in evidence_basis)
    if "nccn" in lowered:
        return "NCCN"
    if "eau" in lowered:
        return "EAU"
    return "Institucional"


def _action_schedule_consistency(care_intent_contract: dict[str, Any], guideline_items: list[dict[str, Any]]) -> bool:
    headline = str(care_intent_contract.get("headline") or "").lower()
    titles = " | ".join(str(item.get("title") or "").lower() for item in guideline_items[:5])
    if not headline or not titles:
        return True
    if "vigilancia" in headline and any(token in titles for token in ("biopsia", "salvage", "rescate")):
        return False
    if ("rt" in headline or "radioterapia" in headline) and "prequir" in titles:
        return False
    if "salvage" in headline or "rescate" in headline:
        return any(token in titles for token in ("psa", "imagen", "salvage", "rescate"))
    return True


def build_guideline_followup_plan(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    agenda_board: dict[str, Any],
    master_followup_plan: dict[str, Any],
    signals: dict[str, Any],
    care_intent_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    care_intent_contract = dict(care_intent_contract or {})
    stage_protocol = dict(agenda_board.get("stage_protocol") or {})
    timeline = list((master_followup_plan or {}).get("timeline") or [])
    active_items = list(agenda_board.get("active_items") or agenda_board.get("items") or [])
    guideline_items = []
    for item in (timeline or active_items):
        evidence_basis = [str(entry) for entry in list(item.get("evidence_basis") or []) if str(entry).strip()]
        guideline_items.append(
            {
                "agenda_key": item.get("agenda_key") or item.get("schedule_key") or "",
                "title": item.get("title") or "",
                "due_at": item.get("ideal_due_at") or item.get("scheduled_due_at") or item.get("due_at") or "",
                "status": item.get("status") or "",
                "guideline_source": _item_guideline_source(item),
                "evidence_basis": evidence_basis,
                "why_adjusted": list(item.get("decision_targets") or []),
            }
        )
    evidence_basis = []
    for entry in list((master_followup_plan or {}).get("guideline_basis") or []):
        text = str(entry).strip()
        if text and text not in evidence_basis:
            evidence_basis.append(text)
    consistency = _action_schedule_consistency(care_intent_contract, guideline_items)
    return {
        "state": state,
        "management_track": management_track,
        "policy": "NCCN-first with EAU fallback",
        "schedule_primary_intent": care_intent_contract.get("headline") or "",
        "care_intent_key": care_intent_contract.get("intent_key") or "",
        "transition_resolution": dict(care_intent_contract.get("transition_resolution") or {}),
        "action_schedule_consistency": consistency,
        "baseline_guideline_plan": {
            "title": _first_nonempty(stage_protocol.get("title"), (master_followup_plan or {}).get("title")),
            "cadence_summary": _first_nonempty(stage_protocol.get("cadence_summary"), (master_followup_plan or {}).get("summary", {}).get("headline")),
            "purpose": _first_nonempty(stage_protocol.get("purpose"), (master_followup_plan or {}).get("summary", {}).get("subheadline")),
        },
        "course_adjusted_plan": {
            "title": _first_nonempty((master_followup_plan or {}).get("title"), stage_protocol.get("title")),
            "next_encounter": dict((master_followup_plan or {}).get("next_encounter") or {}),
            "highlight_actions": list((master_followup_plan or {}).get("highlight_actions") or []),
        },
        "cadence_adjustment_reasons": list(signals.get("cadence_adjusted_by") or (master_followup_plan or {}).get("cadence_adjusted_by") or []),
        "schedule_evidence_basis": evidence_basis,
        "items": guideline_items[:18],
    }
