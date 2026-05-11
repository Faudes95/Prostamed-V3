"""
Audit Log — persistent logging of every agent execution.

Every recalculation is recorded with full inputs and outputs for
traceability, reproducibility, and clinical governance.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """Persist agent execution records to the agent_audit_log table."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def _get_connection(self):
        import sqlite3
        from tracking_db import DB_PATH

        path = self._db_path or DB_PATH
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def log_execution(
        self,
        patient_id: int,
        agent_id: str,
        trigger_event: str,
        trigger_data: dict[str, Any] | None,
        output: dict[str, Any],
        confidence_score: float | None = None,
        qa_validation: dict[str, Any] | None = None,
        execution_time_ms: int | None = None,
    ) -> int | None:
        """Write a single agent execution to the audit log. Returns row id."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_audit_log
                    (patient_id, agent_id, trigger_event, trigger_data_json,
                     output_json, confidence_score, qa_validation_json,
                     execution_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    patient_id,
                    agent_id,
                    trigger_event,
                    json.dumps(trigger_data, ensure_ascii=False) if trigger_data else None,
                    json.dumps(output, ensure_ascii=False),
                    confidence_score,
                    json.dumps(qa_validation, ensure_ascii=False) if qa_validation else None,
                    execution_time_ms,
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid
            conn.close()
            return row_id
        except Exception as exc:
            logger.debug("Audit log write failed: %s", exc)
            return None

    def get_patient_audit(
        self, patient_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Retrieve audit entries for a patient."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM agent_audit_log
                WHERE patient_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (patient_id, limit),
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            for row in rows:
                if row.get("output_json"):
                    row["output"] = json.loads(row["output_json"])
                if row.get("trigger_data_json"):
                    row["trigger_data"] = json.loads(row["trigger_data_json"])
                if row.get("qa_validation_json"):
                    row["qa_validation"] = json.loads(row["qa_validation_json"])
            return rows
        except Exception as exc:
            logger.debug("Audit log read failed: %s", exc)
            return []

    def get_latest_recommendation(
        self, patient_id: int, agent_id: str = "clinical_decision_agent"
    ) -> dict[str, Any] | None:
        """Get the latest recommendation from a specific agent."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM agent_audit_log
                WHERE patient_id = ? AND agent_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (patient_id, agent_id),
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            result = dict(row)
            if result.get("output_json"):
                result["output"] = json.loads(result["output_json"])
            return result
        except Exception as exc:
            logger.debug("Latest recommendation read failed: %s", exc)
            return None
