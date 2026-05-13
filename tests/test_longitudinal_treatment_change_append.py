from __future__ import annotations
# IEC 62304 §5.7 (software system testing).

import sqlite3


def test_treatment_change_append_persists_line_and_closes_previous(tmp_path):
    import tracking_db

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date)
                VALUES (?, ?, ?, ?)
                """,
                ("TX-LINE-001", "Paciente Linea Terapia", "1960-01-01", "2024-01-01"),
            )
            patient_id = cursor.lastrowid
            conn.commit()

        first = tracking_db.append_treatment_line_update(
            "TX-LINE-001",
            {
                "tx_line": 1,
                "tx_regimen": "ADT_LHRH_AGONIST",
                "line_of_therapy_context": "mHSPC_initial",
                "tx_start": "2024-01-10",
                "tx_status": "Curso · activo",
            },
        )
        assert first["success"] is True
        assert first["line_type"] == "adt_solo"

        second = tracking_db.append_treatment_line_update(
            "TX-LINE-001",
            {
                "tx_line": 2,
                "tx_regimen": "ADT_DAROLUTAMIDE_DOCETAXEL",
                "line_of_therapy_context": "mHSPC_initial",
                "tx_start": "2024-04-01",
                "tx_status": "Curso · activo",
            },
        )
        assert second["success"] is True
        assert second["line_type"] == "triplete"

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT line_of_therapy, drug_scheme, start_date, end_date, outcome, regimen_json
                FROM treatment_history
                WHERE patient_id = ?
                ORDER BY start_date ASC
                """,
                (patient_id,),
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["drug_scheme"] == "ADT_LHRH_AGONIST"
        assert rows[0]["end_date"] == "2024-04-01"
        assert rows[0]["outcome"] == "Changed"
        assert rows[1]["drug_scheme"] == "ADT_DAROLUTAMIDE_DOCETAXEL"
        assert rows[1]["outcome"] == "Ongoing"
        assert "triplete" in rows[1]["regimen_json"]
    finally:
        tracking_db.configure_db_path(original)
