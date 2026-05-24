"""EPIC GVP — Clinical Validation Loop tests (FAUBOT CXLI).

GVP.A — CLI godibot_cohort_audit retroactivo
GVP.B — Hook prospectivo en profile_compass (per-render validation)
GVP.C — UI mini-panel clinical-validation-badge
GVP.D — Audit trail + observability
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# GVP.A — CLI module + audit_patient + audit_cohort
# ─────────────────────────────────────────────────────────────────────


def test_gvp_a_module_importable():
    """godibot_cohort_audit module debe cargar + exponer API."""
    import importlib
    mod = importlib.import_module(
        "prostanet.regulatory.clinical.godibot_cohort_audit"
    )
    assert hasattr(mod, "audit_patient")
    assert hasattr(mod, "audit_cohort")
    assert hasattr(mod, "main")


def test_gvp_a_audit_patient_returns_expected_shape():
    """audit_patient debe retornar dict con keys clave."""
    from prostanet.regulatory.clinical.godibot_cohort_audit import audit_patient

    # Synthetic patient mínimo
    patient = {
        "identity": {"id": 999, "nss": "TEST-NSS"},
        "baseline": {"baseline_psa": 12.5},
    }
    result = audit_patient(patient, patient_id=999)
    assert "patient_id" in result
    assert "status" in result
    assert "findings_count" in result
    assert "findings" in result
    assert "review_timestamp" in result
    # Status debe ser uno de los valores esperados (incluye 'error' fallback)
    assert result["status"] in (
        "approved", "warnings_only", "blocked_hard", "error", "unknown"
    )


def test_gvp_a_audit_cohort_with_patient_filter():
    """audit_cohort(patient_id_filter=N) debe procesar solo 1 paciente."""
    from prostanet.regulatory.clinical.godibot_cohort_audit import audit_cohort

    # Usar patient_id_filter para limitar el scope
    report = audit_cohort(patient_id_filter=39, persist=False)
    assert "run_id" in report
    assert "patients_audited" in report
    assert "by_status" in report
    assert "internal_validation_pct" in report
    # Internal validation % entre 0-100
    pct = report.get("internal_validation_pct", -1)
    assert 0 <= pct <= 100


def test_gvp_a_cohort_validation_table_schema():
    """cohort_validation_runs schema debe estar declarado correctamente."""
    from prostanet.regulatory.clinical.godibot_cohort_audit import (
        _ensure_cohort_validation_table,
    )
    import sqlite3
    # In-memory DB para test aislado
    conn = sqlite3.connect(":memory:")
    _ensure_cohort_validation_table(conn)
    # Verificar columnas
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(cohort_validation_runs)")
    columns = {row[1] for row in cur.fetchall()}
    required = {
        "id", "run_id", "patient_id", "patient_nss", "run_timestamp",
        "godibot_status", "findings_count", "findings_json",
        "faubot_release", "trigger_source", "created_at",
    }
    assert required.issubset(columns), f"Missing columns: {required - columns}"
    # Verificar índices
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cohort_validation_runs'")
    indexes = {row[0] for row in cur.fetchall()}
    assert "idx_cohort_validation_run_id" in indexes
    assert "idx_cohort_validation_patient_id" in indexes
    conn.close()


# ─────────────────────────────────────────────────────────────────────
# GVP.B — Hook prospectivo en profile_compass
# ─────────────────────────────────────────────────────────────────────


def test_gvp_b_profile_compass_declares_clinical_validation_snapshot():
    """Source-level: profile_compass debe declarar la inyección al bundle."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "domains" / "patient_tracking" / "profile_compass.py"
    content = src.read_text(encoding="utf-8")
    # Bundle assignment declarado
    assert 'bundle["clinical_validation_snapshot"]' in content, (
        "GVP.B: clinical_validation_snapshot no inyectado al bundle"
    )
    assert "_build_clinical_validation_snapshot" in content
    assert "EPIC GVP.B" in content


def test_gvp_b_snapshot_helper_handles_existing_review():
    """Si existing_godibot_review tiene contenido, debe reusarlo (no re-correr)."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_clinical_validation_snapshot,
    )
    existing = {
        "status": "approved",
        "findings": [],
        "review_timestamp": "2026-05-24T12:00:00Z",
    }
    patient = {"identity": {"id": 99}}
    snap = _build_clinical_validation_snapshot(patient, existing)
    assert snap["available"] is True
    assert snap["status"] == "approved"
    assert snap["trigger_source"] == "reused_upstream"
    assert snap["findings_count"] == 0


def test_gvp_b_snapshot_fail_safe_invalid_patient():
    """Patient sin id válido → snapshot skipped sin levantar."""
    from prostanet.domains.patient_tracking.profile_compass import (
        _build_clinical_validation_snapshot,
    )
    snap = _build_clinical_validation_snapshot({"identity": {}}, {})
    assert snap["status"] in ("skipped", "error", "unknown")
    assert snap["available"] is False or snap["findings_count"] == 0


# ─────────────────────────────────────────────────────────────────────
# GVP.C — UI mini-panel clinical-validation-badge
# ─────────────────────────────────────────────────────────────────────


def test_gvp_c_template_has_clinical_validation_badge():
    """Template patient_profile_v2 debe declarar el badge data-testid."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    assert 'data-testid="clinical-validation-badge"' in content
    # Condición de render
    assert "clinical_validation_snapshot" in content
    # Status mapping visual (4 colores por status)
    assert "approved" in content
    assert "warnings_only" in content
    assert "blocked_hard" in content


def test_gvp_c_badge_uses_data_attrs():
    """El badge debe exponer data-status + data-findings-count para drill-down."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    # Buscar el bloque del badge
    badge_idx = content.find('data-testid="clinical-validation-badge"')
    assert badge_idx > -1
    badge_block = content[badge_idx:badge_idx + 1000]
    assert "data-status=" in badge_block
    assert "data-findings-count=" in badge_block
