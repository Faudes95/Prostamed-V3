"""EPIC 0 Validation Foundation fixes tests (FAUBOT CXLVI).

Cubre los 3 fixes aplicados post-validación E2E:
  C1 — pm2_collapsible_persistence.js decodeURIComponent NSS
  H2 — Retrain banner detection extendido (load_error/size mismatch)
  L1 — Dashboard cohort-breakdown pluralization etnia/etnias
"""
from __future__ import annotations
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# C1 — JS decodeURIComponent fix
# ─────────────────────────────────────────────────────────────────────


def test_epic0_c1_js_decode_uri_component():
    """pm2_collapsible_persistence.js debe usar decodeURIComponent en getPatientNss."""
    src = Path(__file__).parent.parent / "static" / "js" / "pm2_collapsible_persistence.js"
    content = src.read_text(encoding="utf-8")
    # El fix debe incluir decodeURIComponent
    assert "decodeURIComponent(match[1])" in content, (
        "C1 fix missing: getPatientNss should decodeURIComponent the URL-extracted NSS"
    )
    # Referencia explícita a EPIC 0.H
    assert "EPIC 0.H fix C1" in content
    # Try-catch para resilient (URI malformado)
    assert "try {" in content


# ─────────────────────────────────────────────────────────────────────
# H2 — Retrain banner detection extendido
# ─────────────────────────────────────────────────────────────────────


def test_epic0_h2_retrain_banner_detects_load_error():
    """Template patient_profile_v2 retrain banner debe detectar load_error
    + size mismatch + incompatible_checkpoint, no solo 'retrain_required' literal."""
    src = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = src.read_text(encoding="utf-8")
    # Debe contener detección extendida
    assert "'size mismatch' in _reason_str" in content
    assert "'load_error' in _reason_str" in content
    assert "'incompatible_checkpoint' in _reason_str" in content
    # Comentario de trazabilidad
    assert "EPIC 0.H fix H2" in content
    # Banner data-testid sigue
    assert 'data-testid="ml-card-retrain-banner"' in content


# ─────────────────────────────────────────────────────────────────────
# L1 — Pluralización etnia/etnias
# ─────────────────────────────────────────────────────────────────────


def test_epic0_l1_dashboard_pluralization_etnia():
    """Dashboard debe usar 'etnia' singular cuando count=1, 'etnias' plural en otro caso."""
    src = Path(__file__).parent.parent / "templates" / "audit_analytics_dashboard.html"
    content = src.read_text(encoding="utf-8")
    # Conditional ternary pluralization
    assert "by_ethnicity.length === 1 ? 'etnia' : 'etnias'" in content


# ─────────────────────────────────────────────────────────────────────
# Foundation — FAUBOT CXLVI
# ─────────────────────────────────────────────────────────────────────


def test_epic0_faubot_release_cxlvi():
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    assert "CXLVI" in FAUBOT_RELEASE, (
        f"FAUBOT_RELEASE should be CXLVI (EPIC 0), got: {FAUBOT_RELEASE}"
    )


# ─────────────────────────────────────────────────────────────────────
# Source-level coverage of EPIC 0 validation report
# ─────────────────────────────────────────────────────────────────────


def test_epic0_validation_findings_report_exists():
    """EPIC_0_FINDINGS.md debe existir como artifact auditable en docs/epic_0/."""
    report = Path(__file__).parent.parent / "docs" / "epic_0" / "EPIC_0_FINDINGS.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "CRITICAL" in content
    assert "C1" in content
    assert "H2" in content
    assert "L1" in content


def test_epic0_validation_pre_check_report_exists():
    """EPIC_0_A_REPORT.md (pre-validation health check) debe existir en docs/epic_0/."""
    report = Path(__file__).parent.parent / "docs" / "epic_0" / "EPIC_0_A_REPORT.md"
    assert report.exists()
