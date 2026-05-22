"""EPIC 45 FAUBOT CXXX — FactSpec alias audit (Patient Frin bug generalizado).

Cobertura:
  - get_alias_groups() retorna 42 grupos (todos los FACT_SPECS con
    legacy_aliases no vacíos)
  - detect_contradictions_for_patient() detecta correctamente:
      * Frin-style M0/M1b en metastatic_stage_resolved
      * concordant values (todos los facts del mismo grupo con mismo
        valor) → 0 contradictions
      * single fact_key activo → 0 contradictions
      * facts no presentes en ningún alias group → ignorados
  - propose_resolution() aplica reglas:
      * más reciente gana
      * tie-break por source_type (clinician_verified > classifier_derived)
  - apply_resolution() persiste en SQLite (in-memory):
      * losers marcados is_active=0
      * verification_note explicativo
      * superseded_by_fact_id apunta al winner
      * audit entry en clinical_view_audit
  - REST endpoints retornan estructuras esperadas (200, 404, 400)
  - View model integration: _build_data_integrity_snapshot inyecta
    contradictions_detected + needs_clinician_review en el bundle
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — alias group construction
# ─────────────────────────────────────────────────────────────────────────────

def test_get_alias_groups_count():
    """Validates ~42 alias groups in registry (regression guard)."""
    from prostanet.regulatory.clinical.factspec_alias_audit import get_alias_groups
    groups = get_alias_groups()
    assert len(groups) >= 40, (
        f"EPIC 45 regression: esperaba ≥40 alias groups, got {len(groups)}. "
        "Si bajó, alguien removió aliases de FACT_SPECS."
    )


def test_metastatic_stage_alias_group_is_blocking():
    """The bug-root group (Frin) is correctly tagged blocking."""
    from prostanet.regulatory.clinical.factspec_alias_audit import get_alias_groups
    groups = get_alias_groups()
    msr = next(g for g in groups if g.canonical == "metastatic_stage_resolved")
    assert "m_substage_resolved" in msr.members
    assert msr.blocking is True, (
        "metastatic_stage_resolved debe ser blocking — el bug del Frin "
        "bloqueaba el classifier."
    )


def test_canonical_is_in_its_own_members():
    """Cada grupo incluye su canonical en members."""
    from prostanet.regulatory.clinical.factspec_alias_audit import get_alias_groups
    for g in get_alias_groups():
        assert g.canonical in g.members, (
            f"Group canonical={g.canonical} no está en sus members={g.members}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Contradiction detection
# ─────────────────────────────────────────────────────────────────────────────

def _row(fact_id, fact_key, value, source_type="manual_intake",
         updated_at="2026-05-15T10:00:00"):
    return {
        "id": fact_id,
        "fact_key": fact_key,
        "normalized_value_text": value,
        "source_type": source_type,
        "observed_at": updated_at[:10],
        "updated_at": updated_at,
        "is_active": 1,
    }


def test_detects_frin_style_m0_m1b_contradiction():
    """Caso bug-root: M0 + M1b ambos activos → 1 contradiction severity=high."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [
        _row(1, "metastatic_stage_resolved", "M0",
             source_type="classifier_derived", updated_at="2026-04-01T10:00:00"),
        _row(2, "m_substage_resolved", "M1b",
             source_type="clinician_verified", updated_at="2026-05-15T14:00:00"),
    ]
    contradictions = detect_contradictions_for_patient(480, rows)
    assert len(contradictions) == 1
    c = contradictions[0]
    assert c.alias_group_canonical == "metastatic_stage_resolved"
    assert c.severity == "high"
    assert set(c.distinct_values) == {"M0", "M1b"}


def test_concordant_values_no_contradiction():
    """Múltiples fact_keys del mismo grupo con MISMO valor → no contradicción."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [
        _row(1, "baseline_psa", "5.4"),
        _row(2, "psa", "5.4"),
    ]
    assert detect_contradictions_for_patient(99, rows) == []


def test_single_fact_key_no_contradiction():
    """Solo un fact_key del grupo activo → no hay alias collision."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [_row(1, "ecog_score", "1")]
    assert detect_contradictions_for_patient(99, rows) == []


def test_unknown_fact_key_ignored():
    """Fact que no pertenece a ningún alias group → ignorado (no crash)."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [
        _row(1, "not_a_real_fact_key_in_registry", "foo"),
        _row(2, "metastatic_stage_resolved", "M0"),
    ]
    # Solo 1 fact en alias group → no contradiction
    assert detect_contradictions_for_patient(99, rows) == []


def test_case_insensitive_concordance():
    """M1b == m1b (case + whitespace insensitive)."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [
        _row(1, "metastatic_stage_resolved", "M1b"),
        _row(2, "m_substage_resolved", "  m1b  "),
    ]
    assert detect_contradictions_for_patient(99, rows) == []


def test_unknown_value_ignored_as_neutral():
    """value='unknown' / 'null' / '' → tratados como neutrales (no contradice)."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
    )
    rows = [
        _row(1, "metastatic_stage_resolved", "M1b"),
        _row(2, "m_substage_resolved", "unknown"),
    ]
    assert detect_contradictions_for_patient(99, rows) == []


# ─────────────────────────────────────────────────────────────────────────────
# Resolution rules
# ─────────────────────────────────────────────────────────────────────────────

def test_propose_resolution_most_recent_wins():
    """Cuando updated_at difiere, el más reciente gana."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
        propose_resolution,
    )
    rows = [
        _row(1, "metastatic_stage_resolved", "M0",
             updated_at="2026-04-01T10:00:00"),
        _row(2, "m_substage_resolved", "M1b",
             updated_at="2026-05-15T14:00:00"),  # más reciente
    ]
    c = detect_contradictions_for_patient(99, rows)[0]
    r = propose_resolution(c)
    assert r.winner_fact_id == 2
    assert r.winner_value == "M1b"
    assert r.loser_fact_ids == [1]
    assert r.rule_invoked == "most_recent_wins"


def test_propose_resolution_tie_break_clinician_verified_wins():
    """Cuando updated_at idéntico, clinician_verified > classifier_derived."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
        propose_resolution,
    )
    same_ts = "2026-05-15T10:00:00"
    rows = [
        _row(1, "metastatic_stage_resolved", "M0",
             source_type="classifier_derived", updated_at=same_ts),
        _row(2, "m_substage_resolved", "M1b",
             source_type="clinician_verified", updated_at=same_ts),
    ]
    c = detect_contradictions_for_patient(99, rows)[0]
    r = propose_resolution(c)
    assert r.winner_fact_id == 2, (
        "tie-break debe favorecer clinician_verified sobre classifier_derived"
    )
    assert r.rule_invoked == "tie_break_source_type"


def test_propose_resolution_verification_note_explanatory():
    """Verification note debe contener canonical + rule + winner info."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
        propose_resolution,
    )
    rows = [
        _row(1, "metastatic_stage_resolved", "M0"),
        _row(2, "m_substage_resolved", "M1b",
             updated_at="2026-06-01T10:00:00"),
    ]
    c = detect_contradictions_for_patient(99, rows)[0]
    r = propose_resolution(c)
    note = r.verification_note
    assert "auto-corrected via factspec_alias_audit" in note
    assert "metastatic_stage_resolved" in note
    assert "most_recent_wins" in note
    assert "fact_id=2" in note  # winner reference


# ─────────────────────────────────────────────────────────────────────────────
# Apply resolution — persistence layer
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def in_memory_db():
    """SQLite in-memory con schema mínimo para apply_resolution."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE patient_clinical_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            fact_key TEXT NOT NULL,
            normalized_value_text TEXT,
            source_type TEXT,
            observed_at TEXT,
            updated_at TEXT,
            is_active INTEGER DEFAULT 1,
            verification_note TEXT,
            superseded_by_fact_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE clinical_view_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            section_key TEXT,
            action TEXT,
            importance TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    return conn


def test_apply_resolution_inactivates_losers(in_memory_db):
    """apply_resolution() marca losers is_active=0 + verification_note + supersede."""
    from prostanet.regulatory.clinical.factspec_alias_audit import (
        detect_contradictions_for_patient,
        propose_resolution,
        apply_resolution,
    )
    conn = in_memory_db
    conn.execute(
        "INSERT INTO patient_clinical_facts (id, patient_id, fact_key, "
        "normalized_value_text, source_type, updated_at, is_active) "
        "VALUES (1, 480, 'metastatic_stage_resolved', 'M0', 'classifier_derived', "
        "'2026-04-01T10:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO patient_clinical_facts (id, patient_id, fact_key, "
        "normalized_value_text, source_type, updated_at, is_active) "
        "VALUES (2, 480, 'm_substage_resolved', 'M1b', 'clinician_verified', "
        "'2026-05-15T14:00:00', 1)"
    )
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT id, fact_key, normalized_value_text, source_type, "
                "observed_at, updated_at, is_active FROM patient_clinical_facts "
                "WHERE patient_id = 480 AND is_active = 1")
    rows = [dict(r) for r in cur.fetchall()]
    contradictions = detect_contradictions_for_patient(480, rows)
    assert len(contradictions) == 1

    resolution = propose_resolution(contradictions[0])
    apply_resolution(conn, resolution)

    # Verify loser fact 1 is inactive with note
    cur.execute("SELECT is_active, verification_note, superseded_by_fact_id "
                "FROM patient_clinical_facts WHERE id = 1")
    row = dict(cur.fetchone())
    assert row["is_active"] == 0
    assert "auto-corrected via factspec_alias_audit" in row["verification_note"]
    assert row["superseded_by_fact_id"] == 2

    # Verify winner fact 2 untouched
    cur.execute("SELECT is_active FROM patient_clinical_facts WHERE id = 2")
    assert dict(cur.fetchone())["is_active"] == 1

    # Verify audit log entry
    cur.execute("SELECT section_key, action, importance FROM clinical_view_audit "
                "WHERE patient_id = 480")
    audit_row = dict(cur.fetchone())
    assert audit_row["section_key"] == "data_integrity"
    assert "factspec_alias_resolved:metastatic_stage_resolved" in audit_row["action"]
    assert audit_row["importance"] == "high"


# ─────────────────────────────────────────────────────────────────────────────
# View model integration
# ─────────────────────────────────────────────────────────────────────────────

def test_build_data_integrity_snapshot_no_contradictions():
    """Patient sin contradicciones → snapshot indica available + count=0."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_data_integrity_snapshot,
    )
    patient = {
        "id": 99,
        "patient_clinical_facts": [
            _row(1, "ecog_score", "1"),
            _row(2, "baseline_psa", "5.4"),
        ],
    }
    snap = _build_data_integrity_snapshot(patient)
    assert snap["available"] is True
    assert snap["contradictions_count"] == 0
    assert snap["needs_clinician_review"] is False


def test_build_data_integrity_snapshot_with_frin_contradiction():
    """Patient con contradicción Frin → snapshot lo detecta y marca review."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_data_integrity_snapshot,
    )
    patient = {
        "id": 480,
        "patient_clinical_facts": [
            _row(1, "metastatic_stage_resolved", "M0"),
            _row(2, "m_substage_resolved", "M1b",
                 updated_at="2026-06-01T10:00:00"),
        ],
    }
    snap = _build_data_integrity_snapshot(patient)
    assert snap["available"] is True
    assert snap["contradictions_count"] == 1
    assert snap["needs_clinician_review"] is True
    assert snap["severity_summary"]["high"] == 1
    detected = snap["contradictions_detected"][0]
    assert detected["alias_group_canonical"] == "metastatic_stage_resolved"


def test_build_data_integrity_snapshot_missing_facts_field():
    """Patient sin patient_clinical_facts → snapshot fail-safe (no crash).

    Behavior: tratamos lista vacía / ausente como "sin contradicciones a
    reportar" (estado válido para paciente recién registrado), no como
    "audit unavailable". El consumer JS revisa contradictions_count>0
    para decidir si renderiza el panel.
    """
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_data_integrity_snapshot,
    )
    snap = _build_data_integrity_snapshot({"id": 99})
    assert snap["available"] is True
    assert snap["contradictions_count"] == 0
    assert snap["needs_clinician_review"] is False


# ─────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    from app import app, create_app
    create_app()
    return app.test_client()


def test_endpoint_population_audit_returns_200(app_client):
    """GET /api/data-integrity/audit → 200 con summary."""
    r = app_client.get("/api/data-integrity/audit")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert "patients_checked" in body
    assert "total_contradictions" in body
    assert "by_severity" in body


def test_endpoint_404_for_unknown_nss(app_client):
    """GET /api/data-integrity/<nss> con NSS inexistente → 404."""
    r = app_client.get("/api/data-integrity/NSS_DEFINITELY_DOES_NOT_EXIST_12345")
    assert r.status_code == 404
    body = r.get_json()
    assert body["success"] is False
    assert "no encontrado" in body["error"]


def test_endpoint_resolve_requires_confirm_token(app_client):
    """POST /resolve sin confirm=auto → 400."""
    r = app_client.post(
        "/api/data-integrity/X/resolve",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert r.status_code == 400
    body = r.get_json()
    assert "confirm=auto" in body.get("error", "") or "token required" in body.get("error", "")


def test_endpoint_population_apply_requires_admin_token(app_client):
    """POST /api/data-integrity/audit/apply sin token → 400."""
    r = app_client.post(
        "/api/data-integrity/audit/apply",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert r.status_code == 400
    body = r.get_json()
    assert "ALL_PATIENTS" in body.get("error", "")


# ─────────────────────────────────────────────────────────────────────────────
# Template artifact tests (regression guard for UI panel)
# ─────────────────────────────────────────────────────────────────────────────

def test_patient_profile_template_has_data_integrity_panel():
    """patient_profile_v2.html debe incluir el panel data-integrity-panel."""
    p = (Path(__file__).resolve().parent.parent
         / "templates" / "patient_profile_v2.html")
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert 'data-testid="data-integrity-panel"' in content, (
        "EPIC 45.C regression: el panel data-integrity desapareció del template"
    )
    assert "_data_integrity" in content, (
        "Template debe leer profile_view_raw.data_integrity"
    )
    assert "Integridad de datos · EPIC 45" in content


def test_audit_module_is_importable():
    """Sanity: el módulo carga sin errores en import time."""
    import importlib
    mod = importlib.import_module(
        "prostanet.regulatory.clinical.factspec_alias_audit"
    )
    assert hasattr(mod, "get_alias_groups")
    assert hasattr(mod, "detect_contradictions_for_patient")
    assert hasattr(mod, "propose_resolution")
    assert hasattr(mod, "apply_resolution")
    assert hasattr(mod, "audit_all_patients")
    assert hasattr(mod, "resolve_all_patients")
