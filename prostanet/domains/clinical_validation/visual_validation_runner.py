from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PLAYWRIGHT_OUTPUT_DIR = REPO_ROOT / "output" / "playwright" / "validation"
PLAYWRIGHT_SCRIPT = REPO_ROOT / "scripts" / "run_validation_playwright.mjs"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in str(text or "").lower()


def _fallback_artifacts(case_result: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_text = "\n".join(
        [
            f"Estado: {case_result.get('actual', {}).get('effective_state', '')}",
            f"Track: {case_result.get('actual', {}).get('effective_management_track', '')}",
            f"Acción: {(case_result.get('actual', {}).get('next_best_action') or {}).get('title', '')}",
            f"Guidelines: {', '.join(case_result.get('actual', {}).get('guideline_basis', []))}",
            f"Blocking inputs: {', '.join(case_result.get('actual', {}).get('blocking_inputs', []))}",
        ]
    )
    return [
        {
            "artifact_type": "profile_url",
            "artifact_path": case_result.get("profile_url", ""),
            "artifact_text": artifact_text,
            "assertion_key": "profile_snapshot",
            "status": "generated",
        }
    ]


def _visual_case_map(visual_seed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    case_map: dict[str, dict[str, Any]] = {}
    for case in list((visual_seed or {}).get("cases") or []):
        case_map[str(case.get("case_key") or "")] = dict(case)
    return case_map


def _run_playwright_capture(case_results: list[dict[str, Any]], visual_case_map: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    PLAYWRIGHT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_payload = {
        "cases": [
            {
                "case_key": case.get("case_key"),
                "profile_url": (
                    (visual_case_map.get(str(case.get("case_key") or ""), {}).get("final") or {}).get("urls", {})
                ).get("profile")
                or case.get("profile_url", ""),
            }
            for case in case_results
        ],
        "output_dir": str(PLAYWRIGHT_OUTPUT_DIR),
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=str(PLAYWRIGHT_OUTPUT_DIR)) as input_file:
        json.dump(input_payload, input_file)
        input_path = Path(input_file.name)
    output_path = PLAYWRIGHT_OUTPUT_DIR / f"playwright-artifacts-{input_path.stem}.json"
    cmd = [
        "npx",
        "-y",
        "-p",
        "playwright",
        "node",
        str(PLAYWRIGHT_SCRIPT),
        str(input_path),
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return {
            "__error__": {
                "message": str(exc),
            }
        }
    try:
        payload = json.loads(output_path.read_text())
    except Exception:
        payload = {"cases": []}
    result_map: dict[str, dict[str, Any]] = {str(item.get("case_key") or ""): dict(item) for item in list(payload.get("cases") or [])}
    if completed.stderr.strip():
        result_map["__stderr__"] = {"message": completed.stderr.strip()}
    return result_map


def _dom_assertions(case_result: dict[str, Any], capture: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dom = dict(capture.get("dom_snapshot") or {})
    actual = dict(case_result.get("actual") or {})
    assertions: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []

    dom_state = _text(dom.get("effective_state_raw"))
    actual_state = _text(actual.get("effective_state"))
    state_passed = not actual_state or dom_state == actual_state
    assertions.append({"key": "dom_effective_state", "passed": state_passed, "expected": actual_state, "actual": dom_state})
    if not state_passed:
        contradictions.append(
            {
                "key": "dom_effective_state_mismatch",
                "severity": "critical",
                "title": "El estado visible no coincide con el estado efectivo real",
                "details": f"DOM={dom_state} vs actual={actual_state}",
            }
        )

    dom_track = _text(dom.get("effective_track_raw"))
    actual_track = _text(actual.get("effective_management_track"))
    track_passed = not actual_track or dom_track == actual_track
    assertions.append({"key": "dom_effective_track", "passed": track_passed, "expected": actual_track, "actual": dom_track})

    dom_action = _text(dom.get("next_best_action"))
    actual_action = _text((actual.get("next_best_action") or {}).get("title"))
    action_passed = not actual_action or _contains(dom_action, actual_action) or _contains(actual_action, dom_action)
    assertions.append({"key": "dom_next_best_action", "passed": action_passed, "expected": actual_action, "actual": dom_action})
    if not action_passed:
        contradictions.append(
            {
                "key": "dom_action_mismatch",
                "severity": "critical",
                "title": "La acción visible no coincide con la acción efectiva",
                "details": f"DOM={dom_action} vs actual={actual_action}",
            }
        )

    transition_policy = _text(dom.get("transition_policy"))
    transition_card_present = str(dom.get("transition_card_present") or "").lower() in {"1", "true", "yes"}
    transition_passed = not (transition_policy == "auto_applied" and transition_card_present)
    assertions.append({"key": "dom_transition_card", "passed": transition_passed, "expected": transition_policy, "actual": transition_card_present})
    if not transition_passed:
        contradictions.append(
            {
                "key": "dom_transition_card_visible",
                "severity": "critical",
                "title": "La UI sigue mostrando confirmar transición pese a auto-aplicación",
                "details": "Existe tarjeta de transición visible aunque la política es auto_applied.",
            }
        )

    consistency_flag = _text(dom.get("action_schedule_consistency"))
    consistency_passed = consistency_flag != "false"
    assertions.append({"key": "dom_action_schedule_consistency", "passed": consistency_passed, "expected": "true", "actual": consistency_flag or "unknown"})
    if not consistency_passed:
        contradictions.append(
            {
                "key": "dom_action_schedule_inconsistent",
                "severity": "critical",
                "title": "La agenda visible no sigue la intención clínica",
                "details": "El perfil expone action_schedule_consistency=false.",
            }
        )

    return assertions, contradictions


def attach_visual_artifacts(
    case_results: list[dict[str, Any]],
    *,
    visual_mode: str = "playwright_real",
    visual_seed: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    visual_case_map = _visual_case_map(visual_seed)
    if visual_mode != "playwright_real":
        return [{**dict(case), "visual_artifacts": _fallback_artifacts(case), "dom_assertions": []} for case in case_results]

    captures = _run_playwright_capture(case_results, visual_case_map)
    if "__error__" in captures:
        return [
            {
                **dict(case),
                "visual_artifacts": _fallback_artifacts(case)
                + [
                    {
                        "artifact_type": "playwright_error",
                        "artifact_path": "",
                        "artifact_text": captures["__error__"].get("message", ""),
                        "assertion_key": "playwright_run",
                        "status": "failed",
                    }
                ],
                "dom_assertions": [],
            }
            for case in case_results
        ]

    payload = []
    for case_result in case_results:
        case_key = str(case_result.get("case_key") or "")
        capture = dict(captures.get(case_key) or {})
        artifacts = []
        dom_assertions: list[dict[str, Any]] = []
        ui_contradictions = list(case_result.get("ui_contradictions") or [])
        if capture:
            screenshot_path = _text(capture.get("screenshot_path"))
            dom_snapshot = dict(capture.get("dom_snapshot") or {})
            console_path = _text(capture.get("console_log_path"))
            artifacts.extend(
                [
                    {
                        "artifact_type": "profile_screenshot",
                        "artifact_path": screenshot_path,
                        "artifact_text": json.dumps(dom_snapshot, ensure_ascii=True),
                        "assertion_key": "dom_profile",
                        "status": "generated" if screenshot_path else "missing",
                    },
                    {
                        "artifact_type": "console_log",
                        "artifact_path": console_path,
                        "artifact_text": "\n".join(list(capture.get("console_messages") or [])),
                        "assertion_key": "browser_console",
                        "status": "generated" if console_path else "missing",
                    },
                ]
            )
            dom_assertions, dom_contradictions = _dom_assertions(case_result, capture)
            ui_contradictions.extend(dom_contradictions)
        else:
            artifacts.extend(_fallback_artifacts(case_result))
        enriched = dict(case_result)
        enriched["visual_artifacts"] = artifacts or _fallback_artifacts(case_result)
        enriched["dom_assertions"] = dom_assertions
        enriched["ui_contradictions"] = ui_contradictions
        if ui_contradictions:
            enriched["case_status"] = "failed"
        payload.append(enriched)
    return payload


__all__ = ["attach_visual_artifacts"]
