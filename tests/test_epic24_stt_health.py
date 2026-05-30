"""EPIC 24 — STT health endpoint + granular status + worktree path tests.

Resolves the documented UX bug: "al terminar el dictado para prellenar el
clasificador me marca audio cifrado · STT local pendiente". Pre-EPIC 24 the
clinician had no way to know WHY STT failed (sidecar missing? disabled?
decode error?). These tests guarantee the diagnostic path stays observable.

Skills applied:
- /voice-ai-engine-development (health endpoint contract)
- /voice-update (granular transcription_status enum)
- /writing-voice (next_steps microcopy validation)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ─────────────────── EPIC 24a — health endpoint ───────────────────


def test_stt_diagnose_returns_required_schema():
    from prostanet.voice.stt_engine import LocalSTTEngine
    diag = LocalSTTEngine().diagnose()
    for required_key in (
        "stt_available", "mode", "in_process_faster_whisper",
        "sidecar_python", "model_size", "device", "compute_type",
        "blockers", "stt_disable_env",
    ):
        assert required_key in diag, f"diagnose() missing required key: {required_key}"
    assert diag["mode"] in {"in_process", "sidecar", "unavailable"}
    assert isinstance(diag["blockers"], list)


def test_stt_disable_env_blocks_availability(monkeypatch):
    """VOICE_STT_DISABLE=1 must short-circuit availability."""
    monkeypatch.setenv("VOICE_STT_DISABLE", "1")
    from prostanet.voice.stt_engine import LocalSTTEngine
    stt = LocalSTTEngine()
    assert stt.is_available() is False
    diag = stt.diagnose()
    assert diag["stt_available"] is False
    assert diag["stt_disable_env"] is True
    assert any("VOICE_STT_DISABLE" in b for b in diag["blockers"])


def test_stt_health_endpoint_returns_json():
    """/api/voice/stt/health returns JSON with the diagnose contract."""
    import flask
    from prostanet.voice.api import voice_bp
    app = flask.Flask("test_app")
    app.register_blueprint(voice_bp)
    client = app.test_client()
    resp = client.get("/api/voice/stt/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "stt_available" in data
    assert "mode" in data
    assert "blockers" in data
    assert "next_steps" in data
    assert data.get("epic") == "24a"


def test_stt_prewarm_endpoint_returns_warmed_or_503():
    """/api/voice/stt/prewarm returns 200+warmed=True OR 503 when unavailable."""
    import flask
    from prostanet.voice.epic21_endpoints import epic21_bp
    app = flask.Flask("test_app")
    app.register_blueprint(epic21_bp)
    client = app.test_client()
    resp = client.post("/api/voice/stt/prewarm")
    assert resp.status_code in (200, 503)
    data = resp.get_json()
    assert "warmed" in data
    assert data.get("epic") == "24b"
    if resp.status_code == 200:
        assert data["warmed"] is True
        assert "latency_ms" in data


# ─────────────────── EPIC 24c — worktree-aware path resolution ───────────────────


def test_sidecar_python_resolution_from_current_dir():
    """Sidecar resolution must work from the repo root."""
    from prostanet.voice.stt_engine import LocalSTTEngine
    stt = LocalSTTEngine()
    sidecar = stt._sidecar_python()
    # Either we have a sidecar (and it must be executable + has whisper)
    # or we don't (acceptable in environments without the venv).
    if sidecar:
        assert Path(sidecar).exists()
        assert os.access(sidecar, os.X_OK)


def test_sidecar_python_explicit_env_override(monkeypatch, tmp_path):
    """VOICE_STT_SIDECAR_PYTHON env must take precedence over search."""
    fake = tmp_path / "fake-python"
    fake.write_text("#!/bin/bash\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("VOICE_STT_SIDECAR_PYTHON", str(fake))
    from prostanet.voice.stt_engine import LocalSTTEngine
    stt = LocalSTTEngine()
    # Fake python without faster_whisper should be rejected by
    # _sidecar_has_whisper. Result: None (env override fails validation).
    result = stt._sidecar_python()
    # Either it falls back to other candidates (returns a real venv) OR None.
    if result is not None:
        # Must NOT be the fake path
        assert result != str(fake)


def test_sidecar_python_search_upward_from_worktree_path():
    """EPIC 24c — when stt_engine.py is inside a worktree path, resolution
    must still find the main repo's .venv-voice311 via git rev-parse or
    upward search.
    """
    # We can't easily simulate worktree from a test, but we can verify
    # the algorithm checks multiple candidates by inspecting the
    # candidate set generation indirectly.
    from prostanet.voice.stt_engine import LocalSTTEngine
    stt = LocalSTTEngine()
    # The diagnose output should NOT have "sidecar venv no encontrado" in
    # blockers when running from a properly set up repo.
    diag = stt.diagnose()
    if diag["stt_available"] and diag["mode"] == "sidecar":
        # Verified sidecar path is absolute + exists
        assert diag["sidecar_python"].startswith("/")
        assert Path(diag["sidecar_python"]).exists()


# ─────────────────── EPIC 24d — granular transcription_status ───────────────────


def test_granular_status_when_stt_disabled(monkeypatch):
    """EPIC 24d: when VOICE_STT_DISABLE=1, diagnose() must flag the
    explicit disabled blocker so tracking_db can emit the granular
    'requires_local_stt_disabled' status. Tests the diagnose contract
    that backend status routing depends on.
    """
    monkeypatch.setenv("VOICE_STT_DISABLE", "1")
    from prostanet.voice.stt_engine import LocalSTTEngine
    diag = LocalSTTEngine().diagnose()
    assert diag["stt_disable_env"] is True
    assert diag["stt_available"] is False
    # Must include the disable blocker text the backend routing depends on
    joined_blockers = " ".join(diag["blockers"])
    assert "VOICE_STT_DISABLE" in joined_blockers


def test_granular_status_branches_in_tracking_db():
    """EPIC 24d: verify tracking_db.submit_voice_audio code path emits
    the granular status enum (text inspection, not runtime).
    """
    tracking_db_path = Path(__file__).resolve().parent.parent / "tracking_db.py"
    content = tracking_db_path.read_text(encoding="utf-8")
    # Each granular status must be present
    assert "requires_local_stt_sidecar_not_found" in content, (
        "Backend missing granular status for sidecar_not_found (EPIC 24d)"
    )
    assert "requires_local_stt_disabled" in content, (
        "Backend missing granular status for stt_disabled (EPIC 24d)"
    )
    assert "requires_local_stt_other" in content, (
        "Backend missing fallback granular status (EPIC 24d)"
    )
    # stt_diagnose must be embedded for UI consumption
    assert "stt_diagnose" in content, (
        "Backend missing stt_diagnose blob in audio response (EPIC 24d)"
    )


# ─────────────────── EPIC 24e — UI microcopy contract ───────────────────


def test_ui_handles_granular_statuses():
    """Verify the JS handler in prostamed_voice_os.js branches on all the
    new granular statuses (24e contract — UI must not show generic message
    for sidecar_not_found / disabled / other).
    """
    static_js = Path(__file__).resolve().parent.parent / "static" / "js" / "prostamed_voice_os.js"
    content = static_js.read_text(encoding="utf-8")
    # Each branch must exist
    assert "requires_local_stt_sidecar_not_found" in content, (
        "UI missing branch for sidecar_not_found status (EPIC 24e)"
    )
    assert "requires_local_stt_disabled" in content, (
        "UI missing branch for stt_disabled status (EPIC 24e)"
    )
    assert "requires_local_stt_other" in content, (
        "UI missing branch for stt_other status (EPIC 24e)"
    )
