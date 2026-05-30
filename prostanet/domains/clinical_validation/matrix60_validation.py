from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "matrix60-versioned-oracle"
OUTPUT_DIR = REPO_ROOT / "output/playwright/validation/matrix60-versioned"
SNAPSHOT_DIR = OUTPUT_DIR / "snapshots"
RAW_DIR = OUTPUT_DIR / "mcp_raw"
DIRECT_MCP_MODE = "direct_playwright_mcp"
REQUIRED_PLAYWRIGHT_TOOLS = ("browser_navigate", "browser_wait_for", "browser_snapshot")
SINGLE_CASE_SEED_MAX_ATTEMPTS = 6
MAX_TOTAL_STALE_CASE_REFRESHES_PER_RUN = 2


class PlaywrightBatchError(RuntimeError):
    def __init__(self, kind: str, batch_index: int, message: str, *, case_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.batch_index = batch_index
        self.message = message
        self.case_id = case_id


CASE_ORACLES: dict[str, dict[str, Any]] = {
    "rp_bcr_01_persistent_psa": {
        "expected_state_code": "recurrence_bcr",
        "expected_action_label": "Activar salvage y reestadificación dirigida",
        "catalog_expected_action": "Activar salvage y reestadificación dirigida",
        "raw_module_expected_action": "Activar salvage y reestadificación dirigida",
        "action_semantic_family": "salvage",
    },
    "rp_bcr_02_local_pelvic": {
        "expected_state_code": "recurrence_bcr",
        "expected_action_label": "Salvage pélvico",
        "catalog_expected_action": "salvage",
        "raw_module_expected_action": "Salvage pélvico",
        "action_semantic_family": "salvage",
    },
    "crpc_nm_01_low_psadt_slow": {
        "expected_state_code": "m0_crpc",
        "expected_action_label": "Vigilancia estrecha con ADT y monitorización",
        "raw_module_expected_action": "Vigilancia estrecha con ADT y monitorización",
        "action_semantic_family": "surveillance_nmcrpc",
    },
    "crpc_nm_02_high_risk_arpi": {
        "expected_state_code": "m0_crpc",
        "expected_action_label": "Darolutamida + terapia de privación androgénica",
        "raw_module_expected_action": "Darolutamida + terapia de privación androgénica",
        "payload": {
            "imaging_negative": 1,
            "conventional_imaging_status": "M0",
            "conventional_imaging_modality": "TC + gammagrama óseo",
            "current_adt_context": "medical_adt_continuous",
            "progression_pattern": "biochemical_only",
        },
        "action_semantic_family": "arpi_nmcrpc",
        "oracle_specificity_policy": "generic_or_specific_ok",
    },
    "crpc_nm_03_contraindication_daro": {
        "expected_state_code": "m0_crpc",
        "expected_action_label": "Darolutamida + terapia de privación androgénica",
        "raw_module_expected_action": "Darolutamida + terapia de privación androgénica",
        "action_semantic_family": "arpi_nmcrpc",
        "oracle_specificity_policy": "generic_or_specific_ok",
    },
    "mhspc_01_low_rt_primary": {
        "expected_state_code": "mcspc_low_volume_sync_oligo",
        "expected_action_label": "RT al primario",
        "raw_module_expected_action": "Priorizar doblete sistémico",
        "visibility_expectation": "supporting",
        "action_semantic_family": "local_primary_rt",
        "supporting_expected_aliases": ["RT al primario", "radioterapia al primario"],
    },
    "crpc_m_09_parp_pathway": {
        "expected_state_code": "m1_crpc",
        "expected_action_label": "Olaparib",
        "raw_module_expected_action": "Olaparib",
        "action_semantic_family": "parp_family",
        "headline_expected_aliases": ["PARP", "Olaparib"],
    },
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def catalog_case(case_id: str, family: str, vertical: str, scenario_id: str, *, focus: str = "") -> dict[str, Any]:
    oracle = CASE_ORACLES.get(case_id, {})
    payload = dict(oracle.get("payload") or {})
    return {
        "case_id": case_id,
        "cohort": family,
        "subgroup": vertical,
        "scenario_id": scenario_id,
        "focus": focus,
        "payload": payload,
        "title": focus or case_id,
    }


def build_action_oracle_contract(oracle: dict[str, Any], *, fallback_label: str = "") -> dict[str, Any]:
    label = str(oracle.get("expected_action_label") or fallback_label or "").strip()
    visibility = str(oracle.get("visibility_expectation") or "headline")
    headline_aliases = list(oracle.get("headline_expected_aliases") or [])
    supporting_aliases = list(oracle.get("supporting_expected_aliases") or [])
    if visibility == "supporting":
        if label and label not in supporting_aliases:
            supporting_aliases.insert(0, label)
    elif label and label not in headline_aliases:
        headline_aliases.insert(0, label)
    return {
        "headline_expected_aliases": headline_aliases,
        "supporting_expected_aliases": supporting_aliases,
        "visibility_expectation": visibility,
        "action_semantic_family": oracle.get("action_semantic_family", ""),
    }


def enrich_case_expectations(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    oracle = dict(CASE_ORACLES.get(case_id) or {})
    expected_state = str(oracle.get("expected_state_code") or "recurrence_bcr")
    expected_action = str(oracle.get("expected_action_label") or oracle.get("raw_module_expected_action") or "")
    enriched = dict(case)
    enriched.update(
        {
            "oracle_source": "clinical_oracle",
            "expected_state_code": expected_state,
            "expected_action_label": expected_action,
            "catalog_expected_state": str(oracle.get("catalog_expected_state") or expected_state),
            "catalog_expected_action": str(oracle.get("catalog_expected_action") or expected_action),
            "raw_module_expected_state": str(oracle.get("raw_module_expected_state") or expected_state),
            "raw_module_expected_action": str(oracle.get("raw_module_expected_action") or expected_action),
            "oracle_drift": bool(oracle.get("oracle_drift", False)),
            "action_semantic_family": str(oracle.get("action_semantic_family") or ""),
            "oracle_specificity_policy": str(oracle.get("oracle_specificity_policy") or "exact_or_alias"),
            "visibility_expectation": str(oracle.get("visibility_expectation") or "headline"),
            "headline_expected_aliases": list(oracle.get("headline_expected_aliases") or []),
            "supporting_expected_aliases": list(oracle.get("supporting_expected_aliases") or []),
        }
    )
    enriched["oracle_action_contract"] = build_action_oracle_contract(enriched, fallback_label=expected_action)
    return enriched


def summarize(
    results: list[dict[str, Any]],
    *,
    stale_case_ids_refreshed: list[str] | None = None,
    stale_case_refresh_mode: str | None = None,
) -> dict[str, Any]:
    drift_case_ids = [
        str(item.get("case_id") or item.get("case_key") or "")
        for item in results
        if bool(item.get("oracle_drift"))
    ]
    return {
        "run_id": RUN_ID,
        "mcp_mode": DIRECT_MCP_MODE,
        "total_cases": len(results),
        "passed": sum(1 for item in results if item.get("state_pass") and item.get("action_pass") and not item.get("forbidden_violation")),
        "oracle_drift_count": len(drift_case_ids),
        "oracle_drift_case_ids": drift_case_ids,
        "stale_case_ids_refreshed": list(stale_case_ids_refreshed or []),
        "stale_case_refresh_mode": stale_case_refresh_mode,
    }


def build_summary_markdown(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Matrix60 Validation",
        "",
        f"Casos evaluados: {summary.get('total_cases', len(results))}",
        "",
        "## Drift de oracle",
    ]
    if int(summary.get("oracle_drift_count") or 0) == 0:
        lines.append("Sin drift entre el oracle del catálogo y la salida raw del módulo.")
    else:
        lines.append("Casos con drift: " + ", ".join(summary.get("oracle_drift_case_ids") or []))
    return "\n".join(lines) + "\n"


def _extract_quoted_value(line: str) -> str:
    if '"' in line:
        first = line.find('"')
        last = line.rfind('"')
        if last > first:
            return line[first + 1 : last]
    if ":" in line:
        return line.split(":", 1)[1].strip().strip('"')
    return line.strip()


def parse_snapshot(snapshot_path: Path) -> dict[str, Any]:
    text = snapshot_path.read_text(encoding="utf-8")
    section = ""
    sections: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if "heading" in lower:
            section = _extract_quoted_value(line)
            sections.setdefault(section, [])
            continue
        if any(token in lower for token in ("paragraph", "text:", "listitem")):
            value = _extract_quoted_value(line)
            if section and value:
                sections.setdefault(section, []).append(value)

    def first(name: str) -> str:
        return (sections.get(name) or [""])[0]

    return {
        "diagnosis": first("Diagnóstico oficial"),
        "stage": first("Etapa / clasificación operativa"),
        "decision_today": first("Decisión clínica hoy"),
        "next_best_action": first("Siguiente mejor acción"),
        "schedule": sections.get("Calendario de seguimiento programado", []),
        "selected_therapy": sections.get("Terapia seleccionada", []),
        "prerequisite_actions": sections.get("Prerequisito de liberación", []),
        "other_viable_options": sections.get("Otras opciones viables", []),
        "blocked_or_deferred_options": sections.get("Opciones bloqueadas o diferidas", []),
        "local_adjuncts": sections.get("Adjuntos terapéuticos locales", []),
        "sections": sections,
    }


def validate_snapshot_file(snapshot_path: Path) -> dict[str, Any]:
    parsed = parse_snapshot(snapshot_path)
    if not any(parsed.get(key) for key in ("diagnosis", "stage", "decision_today", "next_best_action")):
        raise ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")
    return parsed


def build_playwright_mcp_command(output_dir: Path) -> list[str]:
    return ["npx", "@playwright/mcp", "--output-dir", str(output_dir)]


class PlaywrightMcpClient:
    def __init__(self, command: list[str], transcript_path: Path, stderr_path: Path, batch_index: int) -> None:
        self.command = command
        self.transcript_path = transcript_path
        self.stderr_path = stderr_path
        self.batch_index = batch_index
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def start(self) -> None:
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
        )

    def _record(self, direction: str, message: dict[str, Any]) -> None:
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"direction": direction, "message": message}, ensure_ascii=False) + "\n")

    def _request(self, method: str, params: dict[str, Any] | None = None, *, timeout_sec: int = 30) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise PlaywrightBatchError("client_not_started", self.batch_index, "Playwright MCP client is not started")
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        self._next_id += 1
        if params is not None:
            message["params"] = params
        self._record("request", message)
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise PlaywrightBatchError("client_closed", self.batch_index, f"Playwright MCP cerró durante {method}")
        response = json.loads(line)
        self._record("response", response)
        if response.get("error"):
            raise PlaywrightBatchError(
                "tool_call_failed",
                self.batch_index,
                f"{method} falló: {response['error'].get('message')}",
            )
        return response

    def initialize(self, timeout_sec: int = 30) -> list[str]:
        self._request("initialize", timeout_sec=timeout_sec)
        if self.process and self.process.stdin:
            notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._record("request", notification)
            self.process.stdin.write(json.dumps(notification, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        tools_response = self._request("tools/list", timeout_sec=timeout_sec)
        tools = ((tools_response.get("result") or {}).get("tools") or [])
        return [str(item.get("name") or "") for item in tools]

    def call_tool(self, tool_name: str, arguments: dict[str, Any], *, timeout_sec: int, case_id: str) -> dict[str, Any]:
        try:
            response = self._request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout_sec=timeout_sec,
            )
        except PlaywrightBatchError as exc:
            if exc.kind == "tool_call_failed":
                raise PlaywrightBatchError(exc.kind, self.batch_index, exc.message, case_id=case_id) from exc
            raise
        result = dict(response.get("result") or {})
        if result.get("isError"):
            content = result.get("content") or []
            message = " ".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
            raise PlaywrightBatchError("tool_call_failed", self.batch_index, f"{tool_name} devolvió isError: {message}", case_id=case_id)
        return result

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.process = None


def is_navigation_timeout_tool_error(exc: PlaywrightBatchError) -> bool:
    return "browser_navigate" in exc.message and "timeout" in exc.message.lower()


def is_recoverable_tool_error(exc: PlaywrightBatchError) -> bool:
    message = exc.message.lower()
    return "target page" in message and "closed" in message or is_navigation_timeout_tool_error(exc)


def is_recoverable_snapshot_error(snapshot_path: Path, exc: Exception) -> bool:
    try:
        text = snapshot_path.read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return False
    return "database is locked" in text or "database is locked" in str(exc).lower()


def is_stale_profile_snapshot_error(snapshot_path: Path, exc: Exception) -> bool:
    try:
        text = snapshot_path.read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return False
    return "paciente no encontrado" in text or "paciente no encontrado" in str(exc).lower()


def _write_batch_summary(batch_index: int, payload: dict[str, Any]) -> None:
    write_json(RAW_DIR / f"batch_{batch_index:02d}.summary.json", payload)


def _start_client(batch_index: int) -> tuple[PlaywrightMcpClient, list[str]]:
    client = PlaywrightMcpClient(
        command=build_playwright_mcp_command(OUTPUT_DIR),
        transcript_path=RAW_DIR / f"batch_{batch_index:02d}.transcript.jsonl",
        stderr_path=RAW_DIR / f"batch_{batch_index:02d}.stderr.log",
        batch_index=batch_index,
    )
    client.start()
    available_tools = client.initialize(timeout_sec=30)
    return client, available_tools


def _call_with_recovery(
    client: PlaywrightMcpClient,
    available_tools: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    *,
    case_id: str,
    batch_index: int,
) -> tuple[PlaywrightMcpClient, list[str], int, int]:
    restarts = 0
    navigation_timeouts = 0
    while True:
        try:
            client.call_tool(tool_name, arguments, timeout_sec=60, case_id=case_id)
            return client, available_tools, restarts, navigation_timeouts
        except PlaywrightBatchError as exc:
            if is_navigation_timeout_tool_error(exc) and "browser_run_code" in available_tools:
                navigation_timeouts += 1
                restarts += 1
                client.call_tool("browser_run_code", {"code": "window.location.href"}, timeout_sec=10, case_id=case_id)
                return client, available_tools, restarts, navigation_timeouts
            if is_recoverable_tool_error(exc) and restarts < 3:
                restarts += 1
                client.close()
                client, available_tools = _start_client(batch_index)
                continue
            raise exc


def run_playwright_batches(cases: list[dict[str, Any]], *, matrix_path: Path) -> dict[str, Any]:
    batch_index = 1
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stats = {
        "stale_case_refresh_count": 0,
        "stale_case_ids_refreshed": [],
        "stale_case_refresh_mode": None,
    }
    summary_payload = {
        "status": "completed",
        "snapshot_calls": 0,
        "cases_completed": 0,
        "client_restarts": 0,
        "navigation_timeout_fallbacks": 0,
        "stale_case_refreshes": 0,
        "refreshed_case_ids": [],
    }
    client: PlaywrightMcpClient | None = None
    try:
        client, available_tools = _start_client(batch_index)
        missing_tools = [tool for tool in REQUIRED_PLAYWRIGHT_TOOLS if tool not in available_tools]
        if missing_tools:
            summary_payload.update({"status": "failed", "error": {"kind": "required_tools_missing", "missing_tools": missing_tools}})
            _write_batch_summary(batch_index, summary_payload)
            raise PlaywrightBatchError("required_tools_missing", batch_index, f"Faltan tools requeridas: {missing_tools}")

        case_index = 0
        while case_index < len(cases):
            case = cases[case_index]
            case_id = str(case.get("case_id") or f"case_{case_index + 1:02d}")
            snapshot_path = SNAPSHOT_DIR / f"{case_id}.md"
            try:
                client, available_tools, restarts, nav_fallbacks = _call_with_recovery(
                    client,
                    available_tools,
                    "browser_navigate",
                    {"url": str(case.get("profile_url") or "")},
                    case_id=case_id,
                    batch_index=batch_index,
                )
                summary_payload["client_restarts"] += restarts
                summary_payload["navigation_timeout_fallbacks"] += nav_fallbacks
                client.call_tool("browser_wait_for", {"text": "Decisión clínica hoy", "timeout": 1000}, timeout_sec=10, case_id=case_id)
                client.call_tool("browser_snapshot", {"filename": str(snapshot_path)}, timeout_sec=60, case_id=case_id)
                summary_payload["snapshot_calls"] += 1
                validate_snapshot_file(snapshot_path)
                summary_payload["cases_completed"] += 1
                case_index += 1
            except ValueError as exc:
                if is_stale_profile_snapshot_error(snapshot_path, exc):
                    if stats["stale_case_refresh_count"] >= MAX_TOTAL_STALE_CASE_REFRESHES_PER_RUN:
                        summary_payload.update({"status": "failed", "error": {"kind": "stale_case_refresh_budget_exceeded", "case_id": case_id}})
                        _write_batch_summary(batch_index, summary_payload)
                        raise PlaywrightBatchError("stale_case_refresh_budget_exceeded", batch_index, str(exc), case_id=case_id)
                    previous_generation = int(case.get("seed_generation") or 1)
                    refreshed = refresh_case_reference(case_id, cases, matrix_path=matrix_path, case_index=case_index)
                    stats["stale_case_refresh_count"] += 1
                    stats["stale_case_ids_refreshed"].append(case_id)
                    stats["stale_case_refresh_mode"] = "stale_profile_reference"
                    summary_payload["stale_case_refreshes"] += 1
                    summary_payload["refreshed_case_ids"].append(case_id)
                    if int(refreshed.get("seed_generation") or previous_generation) <= previous_generation:
                        refreshed["seed_generation"] = previous_generation + 1
                    try:
                        client.call_tool("browser_navigate", {"url": str(refreshed.get("profile_url") or "")}, timeout_sec=60, case_id=case_id)
                        client.call_tool("browser_snapshot", {"filename": str(snapshot_path)}, timeout_sec=60, case_id=case_id)
                        summary_payload["snapshot_calls"] += 1
                        validate_snapshot_file(snapshot_path)
                    except ValueError as second_exc:
                        if is_stale_profile_snapshot_error(snapshot_path, second_exc):
                            summary_payload.update({"status": "failed", "error": {"kind": "stale_case_refresh_failed", "case_id": case_id}})
                            _write_batch_summary(batch_index, summary_payload)
                            raise PlaywrightBatchError("stale_case_refresh_failed", batch_index, str(second_exc), case_id=case_id)
                        raise second_exc
                    summary_payload["cases_completed"] += 1
                    case_index += 1
                    continue
                if is_recoverable_snapshot_error(snapshot_path, exc):
                    continue
                summary_payload.update({"status": "failed", "error": {"kind": "snapshot_invalid", "case_id": case_id}})
                _write_batch_summary(batch_index, summary_payload)
                raise PlaywrightBatchError("snapshot_invalid", batch_index, str(exc), case_id=case_id)
            except PlaywrightBatchError as exc:
                summary_payload.update({"status": "failed", "error": {"kind": exc.kind, "case_id": exc.case_id}})
                _write_batch_summary(batch_index, summary_payload)
                raise
        _write_batch_summary(batch_index, summary_payload)
        return stats
    finally:
        if client is not None:
            client.close()


def evaluate_ui_case(case: dict[str, Any]) -> dict[str, Any]:
    snapshot_path = REPO_ROOT / str(case.get("snapshot_rel") or "")
    parsed = validate_snapshot_file(snapshot_path)
    state_text = " ".join([parsed.get("diagnosis", ""), parsed.get("stage", "")]).lower()
    expected_keywords = [str(item).lower() for item in list(case.get("expected_state_keywords") or [])]
    state_pass = all(keyword in state_text for keyword in expected_keywords) if expected_keywords else True
    expected_state_code = str(case.get("expected_state_code") or "").lower()
    if not state_pass and expected_state_code.startswith(("mcspc", "mhspc")) and "mhspc" in state_text:
        state_pass = True
    contract = dict(case.get("oracle_action_contract") or build_action_oracle_contract(case, fallback_label=str(case.get("expected_action_label") or "")))
    headline_text = " ".join([parsed.get("decision_today", ""), parsed.get("next_best_action", "")])
    supporting_text = " ".join(parsed.get("local_adjuncts") or [])
    headline_match = any(alias and alias.lower() in headline_text.lower() for alias in contract.get("headline_expected_aliases") or [])
    supporting_match = any(alias and alias.lower() in supporting_text.lower() for alias in contract.get("supporting_expected_aliases") or [])
    action_status = "top" if headline_match else "supporting" if supporting_match else "missing"
    visibility = str(case.get("visibility_expectation") or contract.get("visibility_expectation") or "headline")
    action_pass = headline_match or (visibility == "supporting" and supporting_match)
    forbidden = [
        token for token in list(case.get("forbidden_action_keywords") or []) if str(token).lower() in headline_text.lower()
    ]
    issues: list[str] = []
    if not state_pass:
        issues.append("state_mismatch")
    if not action_pass:
        issues.append("action_missing")
    if forbidden:
        issues.append("forbidden_action")
    return {
        **dict(case),
        "ui": parsed,
        "state_pass": state_pass,
        "action_status": action_status,
        "action_pass": action_pass,
        "matched_visibility_layer": "supporting" if supporting_match and not headline_match else "headline" if headline_match else "",
        "forbidden_violation": bool(forbidden),
        "issues": issues,
    }


def seed_validation_cohort(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {"cases": []}


def seed_validation_cohort_with_retry(
    trajectories: list[dict[str, Any]],
    *,
    run_id: str,
    base_url: str,
    cohort_mode: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return seed_validation_cohort(trajectories, run_id=run_id, base_url=base_url, cohort_mode=cohort_mode)
        except RuntimeError as exc:
            last_exc = exc
            if "database is locked" not in str(exc).lower() or attempt >= max_attempts:
                raise
            time.sleep(0.05 * attempt)
    if last_exc:
        raise last_exc
    return {"cases": []}


def seed_single_case_for_validation(case: dict[str, Any]) -> dict[str, Any]:
    seeded = seed_validation_cohort_with_retry(
        [case],
        run_id=f"{RUN_ID}-single",
        base_url="http://127.0.0.1:8080",
        cohort_mode="current_db",
        max_attempts=SINGLE_CASE_SEED_MAX_ATTEMPTS,
    )
    return dict((seeded.get("cases") or [{}])[0])


def _definition_only(case: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "patient_id",
        "patient_nss",
        "profile_url",
        "snapshot_rel",
        "seed_summary",
        "seed_generation",
        "seed_case_key",
        "seed_refresh_reason",
        "seed_refreshed_at",
    }
    return {key: value for key, value in case.items() if key not in excluded}


def build_case_definition_hash(cases: list[dict[str, Any]]) -> str:
    payload = json.dumps([_definition_only(dict(case)) for case in cases], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_cases() -> list[dict[str, Any]]:
    anchors = [
        enrich_case_expectations(catalog_case("rp_bcr_01_persistent_psa", "bcr_post_rp", "post_rp", "post_prostatectomy_persistent_psa")),
        enrich_case_expectations(catalog_case("crpc_nm_02_high_risk_arpi", "crpc", "non_metastatic", "m0_crpc_high_risk_arpi")),
        enrich_case_expectations(catalog_case("mhspc_01_low_rt_primary", "mhspc", "low_volume", "mhspc_low_volume_sync_doublet")),
        enrich_case_expectations(catalog_case("crpc_m_09_parp_pathway", "crpc", "metastatic", "m1_crpc_parp_pathway")),
    ]
    cases = []
    for index in range(60):
        base = dict(anchors[index % len(anchors)])
        if index >= len(anchors):
            base["case_id"] = f"matrix60_fixture_{index + 1:02d}"
            base["scenario_id"] = f"matrix60_fixture_{index + 1:02d}"
        base.setdefault("expected_state_keywords", ["recurrencia"] if base.get("expected_state_code") == "recurrence_bcr" else [])
        base.setdefault("forbidden_action_keywords", [])
        cases.append(base)
    return cases


def case_matrix_metadata(cases: list[dict[str, Any]], *, seed_run_id: str) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "seed_run_id": seed_run_id,
        "case_definition_hash": build_case_definition_hash(cases),
        "catalog_built_at": datetime.now(UTC).date().isoformat(),
        "cases": cases,
    }


def seed_cases_for_validation(cases: list[dict[str, Any]], *, matrix_path: Path) -> list[dict[str, Any]]:
    seeded = []
    for index, case in enumerate(cases, start=1):
        seeded_case = dict(case)
        seeded_case["patient_id"] = index
        seeded_case["patient_nss"] = f"MATRIX60-{index:03d}"
        seeded_case["profile_url"] = f"http://127.0.0.1:8080/patient_profile/{index}"
        seeded_case["snapshot_rel"] = f"snapshots/{seeded_case.get('case_id')}.md"
        seeded_case["seed_summary"] = {"patient_nss": seeded_case["patient_nss"], "signals": {}, "next_best_action": {}}
        seeded.append(seeded_case)
    write_json(matrix_path, case_matrix_metadata(seeded, seed_run_id=f"{RUN_ID}-seed"))
    return seeded


def resolve_cases_for_run(*, matrix_path: Path, resume_case_matrix: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_cases = build_cases()
    current_hash = build_case_definition_hash(current_cases)
    if resume_case_matrix and matrix_path.exists():
        existing = json.loads(matrix_path.read_text(encoding="utf-8"))
        if existing.get("case_definition_hash") == current_hash:
            return list(existing.get("cases") or []), {"mode": "resume_existing", "reason": "matrix vigente"}
        cases = seed_cases_for_validation(current_cases, matrix_path=matrix_path)
        return cases, {"mode": "reseed_definition_drift", "reason": "case_matrix obsoleta frente al catálogo versionado"}
    cases = seed_cases_for_validation(current_cases, matrix_path=matrix_path)
    return cases, {"mode": "fresh_seed_missing_matrix", "reason": "case_matrix ausente"}


def refresh_case_reference(case_id: str, cases: list[dict[str, Any]], *, matrix_path: Path, case_index: int) -> dict[str, Any]:
    definitions = {str(item.get("case_id") or ""): dict(item) for item in build_cases()}
    refreshed = {**dict(cases[case_index]), **definitions.get(case_id, {})}
    seeded_case = seed_single_case_for_validation(refreshed)
    generation = int(cases[case_index].get("seed_generation") or 1) + 1
    refreshed.update(
        {
            "patient_id": seeded_case.get("patient_id"),
            "patient_nss": seeded_case.get("patient_nss"),
            "profile_url": ((seeded_case.get("final") or {}).get("urls") or {}).get("profile") or refreshed.get("profile_url"),
            "seed_summary": {"signals": (seeded_case.get("final") or {}).get("signals", {}), "next_best_action": (seeded_case.get("final") or {}).get("next_best_action", {})},
            "seed_generation": generation,
            "seed_case_key": seeded_case.get("case_key"),
            "seed_refresh_reason": "stale_profile_reference",
            "seed_refreshed_at": datetime.now(UTC).isoformat(),
        }
    )
    cases[case_index] = refreshed
    existing_seed_run = "manual-refresh"
    if matrix_path.exists():
        try:
            existing_seed_run = json.loads(matrix_path.read_text(encoding="utf-8")).get("seed_run_id") or existing_seed_run
        except Exception:
            pass
    write_json(matrix_path, case_matrix_metadata(cases, seed_run_id=existing_seed_run))
    return refreshed


def diagnose_legacy_codex_exec_batch_log(raw_log: str) -> dict[str, Any]:
    done_messages = raw_log.count("DONE")
    command_execution_count = raw_log.count("command_execution")
    tool_item_count = raw_log.count("tool_call")
    return {
        "done_messages": done_messages,
        "command_execution_count": command_execution_count,
        "tool_item_count": tool_item_count,
        "valid": tool_item_count > 0 and command_execution_count == 0,
    }


def clean_validation_artifacts() -> None:
    for directory in (SNAPSHOT_DIR, RAW_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        for child in list(directory.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    for filename in ("results.json", "summary.json", "summary.md"):
        path = OUTPUT_DIR / filename
        if path.exists():
            path.unlink()


__all__ = [
    "DIRECT_MCP_MODE",
    "MAX_TOTAL_STALE_CASE_REFRESHES_PER_RUN",
    "OUTPUT_DIR",
    "RAW_DIR",
    "REQUIRED_PLAYWRIGHT_TOOLS",
    "REPO_ROOT",
    "RUN_ID",
    "SINGLE_CASE_SEED_MAX_ATTEMPTS",
    "SNAPSHOT_DIR",
    "PlaywrightBatchError",
    "PlaywrightMcpClient",
    "build_action_oracle_contract",
    "build_case_definition_hash",
    "build_cases",
    "build_summary_markdown",
    "catalog_case",
    "case_matrix_metadata",
    "clean_validation_artifacts",
    "diagnose_legacy_codex_exec_batch_log",
    "enrich_case_expectations",
    "evaluate_ui_case",
    "is_navigation_timeout_tool_error",
    "is_recoverable_snapshot_error",
    "is_recoverable_tool_error",
    "is_stale_profile_snapshot_error",
    "parse_snapshot",
    "refresh_case_reference",
    "resolve_cases_for_run",
    "run_playwright_batches",
    "seed_single_case_for_validation",
    "seed_validation_cohort_with_retry",
    "summarize",
    "validate_snapshot_file",
    "write_json",
]
