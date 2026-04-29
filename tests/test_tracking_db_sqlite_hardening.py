# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import tracking_db


@pytest.fixture()
def isolated_tracking_db(tmp_path: Path):
    original_path = tracking_db.get_db_path()
    db_path = tmp_path / "tracking_hardening.db"
    tracking_db.configure_db_path(str(db_path))
    try:
        yield db_path
    finally:
        tracking_db.configure_db_path(original_path)


class _FailingCursor:
    def execute(self, *args, **kwargs):
        raise RuntimeError("boom")


class _FailingConnection:
    def __init__(self):
        self.closed = False

    def cursor(self):
        return _FailingCursor()

    def commit(self):
        return None

    def close(self):
        self.closed = True


def test_get_db_connection_write_applies_busy_timeout_and_wal(isolated_tracking_db: Path):
    conn = tracking_db.get_db_connection(write=True)
    try:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()

    assert busy_timeout == tracking_db.SQLITE_BUSY_TIMEOUT_MS
    assert foreign_keys == 1
    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1


def test_init_tracking_db_sets_wal_mode(isolated_tracking_db: Path):
    tracking_db.init_tracking_db()

    conn = sqlite3.connect(str(isolated_tracking_db))
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    assert str(journal_mode).lower() == "wal"


def test_create_clinical_assessment_draft_closes_connection_on_failure(monkeypatch):
    failing_conn = _FailingConnection()
    monkeypatch.setattr(tracking_db, "_connect", lambda **kwargs: failing_conn)

    result = tracking_db.create_clinical_assessment_draft(
        "post_prostatectomy",
        "recurrence_bcr",
        {},
        {},
        {},
    )

    assert result is None
    assert failing_conn.closed is True


def test_attach_clinical_assessment_to_patient_closes_connection_on_failure(monkeypatch):
    failing_conn = _FailingConnection()
    monkeypatch.setattr(tracking_db, "_connect", lambda **kwargs: failing_conn)
    monkeypatch.setattr(
        tracking_db,
        "get_clinical_assessment",
        lambda assessment_id: {"id": assessment_id, "state": "recurrence_bcr", "module_id": "post_prostatectomy", "result_snapshot": {}},
    )
    monkeypatch.setattr(tracking_db, "patient_exists", lambda patient_id: True)
    monkeypatch.setattr(tracking_db, "get_patient_full_record", lambda patient_id: {})
    monkeypatch.setattr(
        tracking_db,
        "_assessment_longitudinal_snapshot",
        lambda assessment: {
            "summary": "snapshot",
            "recommendation_family": "salvage",
            "current_state": "recurrence_bcr",
            "transition_reason": "test",
            "objective_progression": {},
            "monitoring_plan": {},
            "care_overlays": {},
            "guideline_snapshot": {},
        },
    )

    success, message = tracking_db.attach_clinical_assessment_to_patient(1, 101)

    assert success is False
    assert "boom" in message
    assert failing_conn.closed is True


def test_register_new_patient_closes_connection_on_failure(monkeypatch):
    failing_conn = _FailingConnection()
    monkeypatch.setattr(tracking_db, "_connect", lambda **kwargs: failing_conn)

    patient_id, message, extras = tracking_db.register_new_patient(
        {
            "nss": "TEST-LOCK-001",
            "full_name": "Paciente de prueba",
            "dob": "1970-01-01",
        }
    )

    assert patient_id is None
    assert "boom" in message
    assert extras == {}
    assert failing_conn.closed is True
