# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

# FAUBOT 2026-04-23 — toda esta suite es E2E sobre el runner Playwright/MCP
# y excede 5 min de wall-clock. Se excluye del ciclo rápido por defecto.
# Ejecutar con: `pytest tests/test_matrix60_playwright_mcp_runner.py -m "slow or not slow"`
pytestmark = pytest.mark.slow

def _load_matrix60_module():
    from prostanet.domains.clinical_validation import matrix60_validation

    return matrix60_validation


def _write_fake_mcp_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fake_playwright_mcp.py"
    server_path.write_text(
        """
from __future__ import annotations

import json
from pathlib import Path
import sys


CONFIG = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
TOOLS = [{"name": name} for name in CONFIG.get("tools", [])]


def write_message(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def build_snapshot(filename: str) -> None:
    behavior = CONFIG.get("snapshot_behavior", "valid")
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    if behavior == "missing":
        return
    if behavior == "empty":
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "\\n".join(
            [
                '- heading "Diagnóstico oficial"',
                '- paragraph: "Recurrencia bioquímica"',
                '- heading "Etapa / clasificación operativa"',
                '- paragraph: "Recurrencia bioquímica"',
                '- heading "Decisión clínica hoy"',
                '- paragraph: "Activar salvage y reestadificación dirigida"',
                '- heading "Siguiente mejor acción"',
                '- paragraph: "Activar salvage y reestadificación dirigida"',
                '- heading "Calendario de seguimiento programado"',
                '- paragraph: "Salvage y reestadificación dirigida"',
            ]
        )
        + "\\n",
        encoding="utf-8",
    )


def should_emit_transient_error(tool_name: str) -> bool:
    transient_tool = CONFIG.get("transient_error_tool")
    if tool_name != transient_tool:
        return False
    marker_path = CONFIG.get("transient_error_marker")
    if not marker_path:
        return False
    path = Path(marker_path)
    if path.exists():
        try:
            current = int(path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            current = 0
    else:
        current = 0
    transient_count = int(CONFIG.get("transient_error_count", 1) or 1)
    if current >= transient_count:
        return False
    path.write_text(str(current + 1), encoding="utf-8")
    return True


for raw_line in sys.stdin:
    line = raw_line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        write_message(
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "fake-playwright-mcp", "version": "0.1"},
                },
            }
        )
        continue
    if method == "tools/list":
        write_message({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": TOOLS}})
        continue
    if method == "tools/call":
        params = message.get("params", {})
        tool_name = params.get("name")
        if should_emit_transient_error(str(tool_name or "")):
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": "### Error\\nError: browserBackend.callTool: Target page, context or browser has been closed",
                            }
                        ],
                        "isError": True,
                    },
                }
            )
            continue
        if tool_name == CONFIG.get("error_tool"):
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32000, "message": f"{tool_name} failed intentionally"},
                }
            )
            continue
        if tool_name == CONFIG.get("result_error_tool"):
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "content": [{"type": "text", "text": f"### Error\\nError: {tool_name} failed via isError"}],
                        "isError": True,
                    },
                }
            )
            continue
        if tool_name == "browser_snapshot":
            build_snapshot(str((params.get("arguments") or {}).get("filename") or ""))
        write_message(
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"content": [{"type": "text", "text": f"{tool_name} ok"}], "isError": False},
            }
        )
        continue
    write_message(
        {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32601, "message": f"Unsupported method: {method}"},
        }
    )
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return server_path


def _configure_fake_runner(module, monkeypatch, tmp_path: Path, config: dict[str, object]) -> Path:
    config_path = tmp_path / "fake_playwright_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    server_path = _write_fake_mcp_server(tmp_path)
    snapshot_dir = tmp_path / "snapshots"
    raw_dir = tmp_path / "mcp_raw"

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(module, "SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(
        module,
        "build_playwright_mcp_command",
        lambda output_dir: [sys.executable, "-u", str(server_path), str(config_path)],
    )
    return snapshot_dir


def _single_case(snapshot_rel: str, *, case_id: str = "runner_case_01", patient_id: int = 101) -> dict[str, object]:
    return {
        "case_id": case_id,
        "patient_id": patient_id,
        "profile_url": f"https://example.com/patient/{case_id}",
        "snapshot_rel": snapshot_rel,
        "payload": {},
        "expected_state_code": "recurrence_bcr",
        "expected_state_keywords": ["recurrencia"],
        "expected_action_label": "Activar salvage y reestadificación dirigida",
        "forbidden_action_keywords": [],
        "cohort": "bcr_post_rp",
        "subgroup": "post_rp",
        "module_id": "post_prostatectomy",
        "title": "Caso sintético para runner MCP",
        "oracle_drift": False,
        "catalog_expected_state": "recurrence_bcr",
        "catalog_expected_action": "Activar salvage y reestadificación dirigida",
        "raw_module_expected_state": "recurrence_bcr",
        "raw_module_expected_action": "Activar salvage y reestadificación dirigida",
        "oracle_source": "clinical_oracle",
        "seed_generation": 1,
        "seed_case_key": f"seed:{case_id}",
    }


def test_direct_playwright_mcp_client_handshake_records_transcript(tmp_path):
    module = _load_matrix60_module()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
                "snapshot_behavior": "valid",
            }
        ),
        encoding="utf-8",
    )
    server_path = _write_fake_mcp_server(tmp_path)
    transcript_path = tmp_path / "batch_01.transcript.jsonl"
    stderr_path = tmp_path / "batch_01.stderr.log"
    client = module.PlaywrightMcpClient(
        command=[sys.executable, "-u", str(server_path), str(config_path)],
        transcript_path=transcript_path,
        stderr_path=stderr_path,
        batch_index=1,
    )

    client.start()
    try:
        available_tools = client.initialize(timeout_sec=5)
    finally:
        client.close()

    assert set(module.REQUIRED_PLAYWRIGHT_TOOLS).issubset(set(available_tools))
    transcript_records = [
        json.loads(line)
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(record["direction"] == "request" and record["message"].get("method") == "initialize" for record in transcript_records)
    assert any(record["direction"] == "response" and "result" in record["message"] for record in transcript_records)


def test_run_playwright_batches_fails_when_tools_missing(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {"tools": ["browser_navigate", "browser_wait_for"], "snapshot_behavior": "valid"},
    )
    case = _single_case("snapshots/runner_case_01.md")

    try:
        module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")
        assert False, "Se esperaba PlaywrightBatchError por tools faltantes"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "required_tools_missing"

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "failed"
    assert batch_summary["error"]["kind"] == "required_tools_missing"


def test_run_playwright_batches_fails_when_tool_call_errors(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
            "error_tool": "browser_snapshot",
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    try:
        module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")
        assert False, "Se esperaba PlaywrightBatchError por error de tool_call"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "tool_call_failed"
        assert exc.case_id == "runner_case_01"

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "failed"
    assert batch_summary["error"]["kind"] == "tool_call_failed"


def test_run_playwright_batches_fails_when_tool_result_has_is_error(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
            "result_error_tool": "browser_snapshot",
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    try:
        module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")
        assert False, "Se esperaba PlaywrightBatchError por isError en el result"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "tool_call_failed"
        assert "iserror" in exc.message.lower()


def test_run_playwright_batches_fails_when_snapshot_is_invalid(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "empty",
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    try:
        module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")
        assert False, "Se esperaba PlaywrightBatchError por snapshot inválido"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "snapshot_invalid"
        assert exc.case_id == "runner_case_01"


def test_run_playwright_batches_restarts_client_once_for_recoverable_browser_close(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    marker_path = tmp_path / "recoverable_error_once.marker"
    snapshot_dir = _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
            "transient_error_tool": "browser_navigate",
            "transient_error_marker": str(marker_path),
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "completed"
    assert batch_summary["client_restarts"] == 1
    assert batch_summary["cases_completed"] == 1
    assert (snapshot_dir / "runner_case_01.md").exists()


def test_run_playwright_batches_restarts_client_twice_for_consecutive_recoverable_errors(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    marker_path = tmp_path / "recoverable_error_twice.marker"
    snapshot_dir = _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
            "transient_error_tool": "browser_navigate",
            "transient_error_marker": str(marker_path),
            "transient_error_count": 2,
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "completed"
    assert batch_summary["client_restarts"] == 2
    assert batch_summary["cases_completed"] == 1
    assert (snapshot_dir / "runner_case_01.md").exists()


def test_run_playwright_batches_uses_browser_run_code_fallback_for_slow_navigation(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    snapshot_dir = tmp_path / "snapshots"
    raw_dir = tmp_path / "mcp_raw"
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(module, "SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(module, "RAW_DIR", raw_dir)
    monkeypatch.setattr(module, "build_playwright_mcp_command", lambda output_dir: ["fake"])

    class FakeSlowNavigateClient:
        def __init__(self, command, transcript_path, stderr_path, batch_index):
            self.batch_index = batch_index
            self.calls = []

        def start(self):
            return None

        def initialize(self, timeout_sec):
            return ["browser_navigate", "browser_wait_for", "browser_snapshot", "browser_run_code"]

        def close(self):
            return None

        def call_tool(self, tool_name, arguments, *, timeout_sec, case_id):
            self.calls.append((tool_name, case_id))
            if tool_name == "browser_navigate":
                raise module.PlaywrightBatchError(
                    "tool_call_failed",
                    self.batch_index,
                    'browser_navigate devolvió isError: ### Error TimeoutError: browserBackend.callTool: Timeout 60000ms exceeded.',
                    case_id=case_id,
                )
            if tool_name == "browser_snapshot":
                Path(arguments["filename"]).write_text(
                    "\n".join(
                        [
                            '- heading "Diagnóstico oficial"',
                            '- paragraph: "Recurrencia bioquímica"',
                            '- heading "Etapa / clasificación operativa"',
                            '- paragraph: "Recurrencia bioquímica"',
                            '- heading "Decisión clínica hoy"',
                            '- paragraph: "Activar salvage y reestadificación dirigida"',
                            '- heading "Siguiente mejor acción"',
                            '- paragraph: "Activar salvage y reestadificación dirigida"',
                            '- heading "Calendario de seguimiento programado"',
                            '- paragraph: "Salvage y reestadificación dirigida"',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return {}

    monkeypatch.setattr(module, "PlaywrightMcpClient", FakeSlowNavigateClient)
    case = _single_case("snapshots/runner_case_01.md")

    module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "completed"
    assert batch_summary["cases_completed"] == 1
    assert batch_summary["client_restarts"] == 1
    assert batch_summary["navigation_timeout_fallbacks"] == 1
    assert (snapshot_dir / "runner_case_01.md").exists()


def test_timeout_navigation_error_is_classified_as_recoverable():
    module = _load_matrix60_module()
    exc = module.PlaywrightBatchError(
        "tool_call_failed",
        5,
        'browser_navigate devolvió isError: ### Error TimeoutError: browserBackend.callTool: Timeout 60000ms exceeded.',
        case_id="mhspc_12_high_risk_cardio_daro",
    )

    assert module.is_recoverable_tool_error(exc) is True


def test_timeout_navigation_error_is_classified_as_slow_navigation_timeout():
    module = _load_matrix60_module()
    exc = module.PlaywrightBatchError(
        "tool_call_failed",
        5,
        'browser_navigate devolvió isError: ### Error TimeoutError: browserBackend.callTool: Timeout 60000ms exceeded.',
        case_id="mhspc_12_high_risk_cardio_daro",
    )

    assert module.is_navigation_timeout_tool_error(exc) is True


def test_database_locked_snapshot_is_classified_as_recoverable(tmp_path):
    module = _load_matrix60_module()
    snapshot_path = tmp_path / "locked.md"
    snapshot_path.write_text('- generic [active] [ref=e1]: "Error interno: database is locked"\n', encoding="utf-8")
    exc = ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")

    assert module.is_recoverable_snapshot_error(snapshot_path, exc) is True


def test_paciente_no_encontrado_snapshot_is_classified_as_stale_profile(tmp_path):
    module = _load_matrix60_module()
    snapshot_path = tmp_path / "missing_patient.md"
    snapshot_path.write_text("- generic [active] [ref=e1]: Paciente no encontrado\n", encoding="utf-8")
    exc = ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")

    assert module.is_stale_profile_snapshot_error(snapshot_path, exc) is True


def test_refresh_case_reference_updates_only_target_case_and_persists_metadata(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    matrix_path = tmp_path / "case_matrix.json"
    cases = [
        _single_case("snapshots/runner_case_01.md", case_id="runner_case_01", patient_id=101),
        _single_case("snapshots/runner_case_02.md", case_id="runner_case_02", patient_id=202),
    ]
    cases[0].pop("seed_generation")
    cases[0].pop("seed_case_key")
    module.write_json(
        matrix_path,
        {
            "run_id": module.RUN_ID,
            "seed_run_id": "existing-seed",
            "cases": cases,
        },
    )

    monkeypatch.setattr(
        module,
        "build_cases",
        lambda: [
            _single_case("snapshots/runner_case_01.md", case_id="runner_case_01", patient_id=0),
            _single_case("snapshots/runner_case_02.md", case_id="runner_case_02", patient_id=0),
        ],
    )
    monkeypatch.setattr(
        module,
        "seed_single_case_for_validation",
        lambda case: {
            "case_key": f"fresh:{case['case_id']}",
            "patient_id": 999,
            "patient_nss": "NSS-999",
            "final": {
                "urls": {"profile": "http://127.0.0.1:8080/patient_profile/999"},
                "signals": {},
                "next_best_action": {},
            },
        },
    )

    refreshed = module.refresh_case_reference(
        "runner_case_01",
        cases,
        matrix_path=matrix_path,
        case_index=0,
    )

    assert refreshed["patient_id"] == 999
    assert refreshed["profile_url"] == "http://127.0.0.1:8080/patient_profile/999"
    assert refreshed["seed_generation"] == 2
    assert refreshed["seed_case_key"] == "fresh:runner_case_01"
    assert refreshed["seed_refresh_reason"] == "stale_profile_reference"
    assert cases[1]["patient_id"] == 202

    persisted = json.loads(matrix_path.read_text(encoding="utf-8"))
    persisted_case = next(item for item in persisted["cases"] if item["case_id"] == "runner_case_01")
    assert persisted_case["seed_generation"] == 2
    assert persisted_case["seed_case_key"] == "fresh:runner_case_01"
    assert persisted_case["seed_refresh_reason"] == "stale_profile_reference"


def test_run_playwright_batches_refreshes_stale_case_and_completes(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    snapshot_dir = _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
        },
    )
    matrix_path = tmp_path / "case_matrix.json"
    cases = [_single_case("snapshots/runner_case_01.md")]
    module.write_json(matrix_path, module.case_matrix_metadata(cases, seed_run_id="seed-existing"))

    original_validate_snapshot_file = module.validate_snapshot_file
    stale_once = {"count": 0}

    def fake_validate_snapshot_file(snapshot_path):
        if stale_once["count"] == 0:
            stale_once["count"] += 1
            snapshot_path.write_text("- generic [active] [ref=e1]: Paciente no encontrado\n", encoding="utf-8")
            raise ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")
        return original_validate_snapshot_file(snapshot_path)

    def fake_refresh_case_reference(case_id, cases, *, matrix_path, case_index):
        refreshed = dict(cases[case_index])
        refreshed["patient_id"] = 999
        refreshed["profile_url"] = "https://example.com/patient/refreshed-runner-case-01"
        refreshed["seed_generation"] = int(refreshed.get("seed_generation") or 1) + 1
        refreshed["seed_case_key"] = "fresh:runner_case_01"
        refreshed["seed_refresh_reason"] = "stale_profile_reference"
        refreshed["seed_refreshed_at"] = "2026-04-11T12:00:00"
        cases[case_index] = refreshed
        module.write_json(matrix_path, module.case_matrix_metadata(cases, seed_run_id="seed-existing"))
        return refreshed

    monkeypatch.setattr(module, "validate_snapshot_file", fake_validate_snapshot_file)
    monkeypatch.setattr(module, "refresh_case_reference", fake_refresh_case_reference)

    run_stats = module.run_playwright_batches(cases, matrix_path=matrix_path)

    assert run_stats["stale_case_refresh_count"] == 1
    assert run_stats["stale_case_ids_refreshed"] == ["runner_case_01"]
    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "completed"
    assert batch_summary["stale_case_refreshes"] == 1
    assert batch_summary["refreshed_case_ids"] == ["runner_case_01"]
    assert cases[0]["patient_id"] == 999
    assert (snapshot_dir / "runner_case_01.md").exists()


def test_run_playwright_batches_fails_when_case_stays_stale_after_refresh(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
        },
    )
    matrix_path = tmp_path / "case_matrix.json"
    cases = [_single_case("snapshots/runner_case_01.md")]
    module.write_json(matrix_path, module.case_matrix_metadata(cases, seed_run_id="seed-existing"))

    def always_stale(snapshot_path):
        snapshot_path.write_text("- generic [active] [ref=e1]: Paciente no encontrado\n", encoding="utf-8")
        raise ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")

    def fake_refresh_case_reference(case_id, cases, *, matrix_path, case_index):
        refreshed = dict(cases[case_index])
        refreshed["profile_url"] = "https://example.com/patient/runner-case-01-refreshed"
        refreshed["seed_generation"] = int(refreshed.get("seed_generation") or 1) + 1
        cases[case_index] = refreshed
        return refreshed

    monkeypatch.setattr(module, "validate_snapshot_file", always_stale)
    monkeypatch.setattr(module, "refresh_case_reference", fake_refresh_case_reference)

    try:
        module.run_playwright_batches(cases, matrix_path=matrix_path)
        assert False, "Se esperaba PlaywrightBatchError cuando el caso sigue stale tras el refresh"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "stale_case_refresh_failed"
        assert exc.case_id == "runner_case_01"


def test_run_playwright_batches_fails_when_stale_refresh_budget_is_exceeded(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
        },
    )
    matrix_path = tmp_path / "case_matrix.json"
    cases = [
        _single_case("snapshots/runner_case_01.md", case_id="runner_case_01", patient_id=101),
        _single_case("snapshots/runner_case_02.md", case_id="runner_case_02", patient_id=202),
    ]
    module.write_json(matrix_path, module.case_matrix_metadata(cases, seed_run_id="seed-existing"))
    monkeypatch.setattr(module, "MAX_TOTAL_STALE_CASE_REFRESHES_PER_RUN", 1)

    original_validate_snapshot_file = module.validate_snapshot_file
    stale_once_per_case: dict[str, int] = {}

    def stale_then_valid(snapshot_path):
        if stale_once_per_case.get(snapshot_path.name, 0) == 0:
            stale_once_per_case[snapshot_path.name] = 1
            snapshot_path.write_text("- generic [active] [ref=e1]: Paciente no encontrado\n", encoding="utf-8")
            raise ValueError(f"Snapshot sin estructura clínica parseable: {snapshot_path}")
        return original_validate_snapshot_file(snapshot_path)

    def fake_refresh_case_reference(case_id, cases, *, matrix_path, case_index):
        refreshed = dict(cases[case_index])
        refreshed["profile_url"] = f"https://example.com/patient/{case_id}-refreshed"
        refreshed["seed_generation"] = int(refreshed.get("seed_generation") or 1) + 1
        cases[case_index] = refreshed
        return refreshed

    monkeypatch.setattr(module, "validate_snapshot_file", stale_then_valid)
    monkeypatch.setattr(module, "refresh_case_reference", fake_refresh_case_reference)

    try:
        module.run_playwright_batches(cases, matrix_path=matrix_path)
        assert False, "Se esperaba PlaywrightBatchError al exceder el budget global de stale refresh"
    except module.PlaywrightBatchError as exc:
        assert exc.kind == "stale_case_refresh_budget_exceeded"
        assert exc.case_id == "runner_case_02"


def test_seed_validation_cohort_retries_database_lock(monkeypatch):
    module = _load_matrix60_module()
    calls = {"count": 0}

    def fake_seed_validation_cohort(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("database is locked")
        return {"cases": []}

    monkeypatch.setattr(module, "seed_validation_cohort", fake_seed_validation_cohort)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    seeded = module.seed_validation_cohort_with_retry(
        [],
        run_id="retry-test",
        base_url="http://127.0.0.1:8080",
        cohort_mode="current_db",
    )

    assert seeded == {"cases": []}
    assert calls["count"] == 3


def test_seed_single_case_for_validation_uses_extended_retry_budget(monkeypatch):
    module = _load_matrix60_module()
    calls = {"count": 0}

    def fake_seed_validation_cohort(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < module.SINGLE_CASE_SEED_MAX_ATTEMPTS:
            raise RuntimeError("database is locked")
        return {
            "cases": [
                {
                    "case_key": "single-case",
                    "patient_id": 999,
                    "patient_nss": "NSS-999",
                    "final": {"urls": {"profile": "http://127.0.0.1:8080/patient_profile/999"}, "signals": {}, "next_best_action": {}},
                }
            ]
        }

    monkeypatch.setattr(module, "seed_validation_cohort", fake_seed_validation_cohort)
    monkeypatch.setattr(module.time, "sleep", lambda *_args, **_kwargs: None)

    seeded_case = module.seed_single_case_for_validation(_single_case("snapshots/runner_case_01.md"))

    assert seeded_case["patient_id"] == 999
    assert calls["count"] == module.SINGLE_CASE_SEED_MAX_ATTEMPTS


def test_build_case_definition_hash_changes_when_case_payload_changes():
    module = _load_matrix60_module()
    cases = module.build_cases()
    original_hash = module.build_case_definition_hash(cases)

    mutated_cases = json.loads(json.dumps(cases))
    target = next(item for item in mutated_cases if item["case_id"] == "crpc_nm_02_high_risk_arpi")
    target["payload"]["conventional_imaging_status"] = "NOT_RESTAGED"

    assert module.build_case_definition_hash(mutated_cases) != original_hash


def test_resolve_cases_for_run_reseeds_when_case_matrix_hash_is_stale(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    matrix_path = tmp_path / "case_matrix.json"

    fresh_cases = module.build_cases()
    stale_cases = json.loads(json.dumps(fresh_cases))
    stale_target = next(item for item in stale_cases if item["case_id"] == "crpc_nm_02_high_risk_arpi")
    stale_target["payload"]["conventional_imaging_status"] = "NOT_RESTAGED"
    stale_target["patient_id"] = 999
    stale_target["profile_url"] = "http://127.0.0.1:8080/patient_profile/999"
    stale_target["snapshot_rel"] = "snapshots/stale.md"
    stale_target["seed_summary"] = {"patient_nss": "STALE", "signals": {}, "next_best_action": {}}
    module.write_json(
        matrix_path,
        {
            "run_id": module.RUN_ID,
            "seed_run_id": "stale-seed",
            "case_definition_hash": "obsolete-hash",
            "catalog_built_at": "2026-04-10",
            "cases": stale_cases,
        },
    )

    def fake_seed_cases_for_validation(cases, *, matrix_path):
        seeded_cases = json.loads(json.dumps(cases))
        for index, case in enumerate(seeded_cases, start=1):
            case["patient_id"] = index
            case["profile_url"] = f"http://127.0.0.1:8080/patient_profile/{index}"
            case["snapshot_rel"] = f"snapshots/{case['case_id']}.md"
            case["seed_summary"] = {"patient_nss": f"NSS-{index}", "signals": {}, "next_best_action": {}}
        module.write_json(matrix_path, module.case_matrix_metadata(seeded_cases, seed_run_id="fresh-seed"))
        return seeded_cases

    monkeypatch.setattr(module, "seed_cases_for_validation", fake_seed_cases_for_validation)

    cases, refresh = module.resolve_cases_for_run(
        matrix_path=matrix_path,
        resume_case_matrix=True,
    )

    assert refresh["mode"] == "reseed_definition_drift"
    assert "obsoleta" in refresh["reason"]
    assert next(item for item in cases if item["case_id"] == "crpc_nm_02_high_risk_arpi")["payload"]["conventional_imaging_status"] == "M0"
    persisted = json.loads(matrix_path.read_text(encoding="utf-8"))
    assert persisted["case_definition_hash"] == module.build_case_definition_hash(cases)


def test_resolve_cases_for_run_reuses_existing_case_matrix_when_hash_matches(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    matrix_path = tmp_path / "case_matrix.json"
    cases = module.build_cases()
    seeded_cases = json.loads(json.dumps(cases))
    for index, case in enumerate(seeded_cases, start=1):
        case["patient_id"] = index
        case["profile_url"] = f"http://127.0.0.1:8080/patient_profile/{index}"
        case["snapshot_rel"] = f"snapshots/{case['case_id']}.md"
        case["seed_summary"] = {"patient_nss": f"NSS-{index}", "signals": {}, "next_best_action": {}}
    module.write_json(matrix_path, module.case_matrix_metadata(seeded_cases, seed_run_id="existing-seed"))

    called = {"count": 0}

    def fail_if_seeded(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("No debería resembrar una matrix vigente")

    monkeypatch.setattr(module, "seed_cases_for_validation", fail_if_seeded)

    resumed_cases, refresh = module.resolve_cases_for_run(
        matrix_path=matrix_path,
        resume_case_matrix=True,
    )

    assert refresh["mode"] == "resume_existing"
    assert called["count"] == 0
    assert len(resumed_cases) == len(seeded_cases)


def test_resolve_cases_for_run_seeds_when_matrix_file_is_missing(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    matrix_path = tmp_path / "case_matrix.json"

    def fake_seed_cases_for_validation(cases, *, matrix_path):
        seeded_cases = json.loads(json.dumps(cases))
        module.write_json(matrix_path, module.case_matrix_metadata(seeded_cases, seed_run_id="missing-seed"))
        return seeded_cases

    monkeypatch.setattr(module, "seed_cases_for_validation", fake_seed_cases_for_validation)

    cases, refresh = module.resolve_cases_for_run(
        matrix_path=matrix_path,
        resume_case_matrix=True,
    )

    assert refresh["mode"] == "fresh_seed_missing_matrix"
    assert matrix_path.exists()
    assert len(cases) == 60


def test_legacy_batch_log_is_rejected_even_when_done_is_present():
    module = _load_matrix60_module()
    raw_log = "\n".join(
        [
            json.dumps({"item": {"type": "command_execution", "command": "codex exec ..."}}),
            json.dumps({"item": {"type": "command_execution", "command": "codex exec ..."}}),
            json.dumps({"item": {"type": "agent_message", "text": "DONE"}}),
        ]
    )

    diagnosis = module.diagnose_legacy_codex_exec_batch_log(raw_log)

    assert diagnosis["done_messages"] == 1
    assert diagnosis["command_execution_count"] > 0
    assert diagnosis["tool_item_count"] == 0
    assert diagnosis["valid"] is False


def test_run_playwright_batches_with_fake_server_generates_snapshot_and_reports(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    snapshot_dir = _configure_fake_runner(
        module,
        monkeypatch,
        tmp_path,
        {
            "tools": ["browser_navigate", "browser_wait_for", "browser_snapshot"],
            "snapshot_behavior": "valid",
        },
    )
    case = _single_case("snapshots/runner_case_01.md")

    run_stats = module.run_playwright_batches([case], matrix_path=tmp_path / "case_matrix.json")

    snapshot_path = snapshot_dir / "runner_case_01.md"
    assert snapshot_path.exists()
    parsed = module.parse_snapshot(snapshot_path)
    assert parsed["decision_today"] == "Activar salvage y reestadificación dirigida"

    result = module.evaluate_ui_case(case)
    summary = module.summarize(
        [result],
        stale_case_ids_refreshed=list(run_stats.get("stale_case_ids_refreshed") or []),
        stale_case_refresh_mode=run_stats.get("stale_case_refresh_mode"),
    )
    module.write_json(tmp_path / "results.json", [result])
    module.write_json(tmp_path / "summary.json", summary)

    batch_summary = json.loads((tmp_path / "mcp_raw" / "batch_01.summary.json").read_text(encoding="utf-8"))
    assert batch_summary["status"] == "completed"
    assert batch_summary["snapshot_calls"] == 1
    assert batch_summary["cases_completed"] == 1
    assert result["action_status"] == "top"
    assert summary["mcp_mode"] == module.DIRECT_MCP_MODE
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "summary.json").exists()


def test_evaluate_ui_case_accepts_supporting_visibility_for_local_adjunct(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot_path = snapshot_dir / "runner_case_01.md"
    snapshot_path.write_text(
        "\n".join(
            [
                '- heading "Diagnóstico oficial"',
                '- paragraph: "mHSPC oligometastásico metacrónico"',
                '- heading "Etapa / clasificación operativa"',
                '- paragraph: "mHSPC oligometastásico metacrónico"',
                '- heading "Decisión clínica hoy"',
                '- paragraph: "Priorizar ADT + enzalutamida"',
                '- heading "Siguiente mejor acción"',
                '- paragraph: "Priorizar ADT + enzalutamida"',
                '- heading "Adjuntos terapéuticos locales"',
                '- listitem: "MDT"',
                '- paragraph: "La MDT sigue visible como adjunto contextual."',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    case = {
        **_single_case("snapshots/runner_case_01.md"),
        "expected_state_code": "mcspc_oligo_metachronous",
        "expected_state_keywords": ["metast", "hormono"],
        "expected_action_label": "MDT",
        "oracle_action_contract": module.build_action_oracle_contract(
            {
                "expected_action_label": "MDT",
                "supporting_expected_aliases": ["MDT", "Metastasis-directed therapy"],
                "visibility_expectation": "supporting",
                "action_semantic_family": "mdt_candidate",
            },
            fallback_label="MDT",
        ),
        "action_semantic_family": "mdt_candidate",
        "oracle_specificity_policy": "generic_or_specific_ok",
        "visibility_expectation": "supporting",
    }

    result = module.evaluate_ui_case(case)

    assert result["action_status"] == "supporting"
    assert result["action_pass"] is True
    assert result["matched_visibility_layer"] == "supporting"
    assert result["issues"] == []


def test_clean_validation_artifacts_removes_old_and_new_outputs(tmp_path, monkeypatch):
    module = _load_matrix60_module()
    snapshot_dir = tmp_path / "snapshots"
    raw_dir = tmp_path / "mcp_raw"
    snapshot_dir.mkdir()
    raw_dir.mkdir()
    (snapshot_dir / "runner_case_01.md").write_text("snapshot", encoding="utf-8")
    (raw_dir / "batch_01.log").write_text("legacy", encoding="utf-8")
    (raw_dir / "batch_01.transcript.jsonl").write_text("{}", encoding="utf-8")
    (raw_dir / "batch_01.summary.json").write_text("{}", encoding="utf-8")
    (raw_dir / "batch_01.stderr.log").write_text("stderr", encoding="utf-8")
    server_dir = raw_dir / "batch_01_server"
    server_dir.mkdir()
    (server_dir / "artifact.txt").write_text("server", encoding="utf-8")
    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "summary.md").write_text("# summary", encoding="utf-8")

    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(module, "SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(module, "RAW_DIR", raw_dir)

    module.clean_validation_artifacts()

    assert list(snapshot_dir.iterdir()) == []
    assert list(raw_dir.iterdir()) == []
    assert not (tmp_path / "results.json").exists()
    assert not (tmp_path / "summary.json").exists()
    assert not (tmp_path / "summary.md").exists()
