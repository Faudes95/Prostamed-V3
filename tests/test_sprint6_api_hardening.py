"""Sprint 6 — REST APIs hardening tests (FAUBOT CXLIV).

Cubre CRITICAL + HIGH + MEDIUM findings de la verificación REST APIs.

Áreas:
  S6.A  Auth middleware (api_auth.py + decorators aplicados)
  S6.B  Info-leak fix (str(exc) → internal_error)
  S6.C  Audit trail completeness + HMAC signature + atomic transactions
  S6.D  Performance: cached singleton + single-model GET + try/finally
  S6.E  Validation: ISO-8601 + confidence clamp + free_text sanitize
  S6.F  state_transition UI mitigation (badge re-entrenamiento)
  S6.G  Constants + cleanup
  Foundation: FAUBOT bump CXLIV
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# S6.A — Auth middleware
# ─────────────────────────────────────────────────────────────────────


def test_s6_a_api_auth_module_importable():
    """api_auth.py debe exponer decorators + helpers."""
    from prostanet.shared import api_auth
    assert hasattr(api_auth, "require_clinician")
    assert hasattr(api_auth, "require_admin")
    assert hasattr(api_auth, "current_api_user_id")
    assert hasattr(api_auth, "current_api_user_role")
    assert hasattr(api_auth, "audit_actor")
    assert hasattr(api_auth, "CLINICIAN_ROLES")
    assert hasattr(api_auth, "ADMIN_ROLES")
    # Roles canonical sets
    assert "clinician" in api_auth.CLINICIAN_ROLES
    assert "admin" in api_auth.ADMIN_ROLES
    assert "admin" in api_auth.CLINICIAN_ROLES  # admin puede operar clinically


def test_s6_a_ml_inference_endpoints_have_auth_decorator():
    """Source-level: los 5 endpoints ML deben tener @require_clinician."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "ml_inference_routes.py"
    content = src.read_text(encoding="utf-8")
    # Cada endpoint GET debe tener @require_clinician justo antes de def
    for endpoint_def in (
        "def get_treatment_response_prediction",
        "def get_survival_prediction",
        "def get_anomaly_prediction",
        "def get_state_transition_prediction",
        "def get_all_predictions_bundle",
    ):
        idx = content.find(endpoint_def)
        assert idx > 0, f"endpoint {endpoint_def} not found"
        # Buscar @require_clinician en las 200 chars antes del def
        prev_block = content[max(0, idx - 200):idx]
        assert "@require_clinician" in prev_block, (
            f"endpoint {endpoint_def} missing @require_clinician decorator"
        )


def test_s6_a_trajectory_endpoint_has_auth():
    """trajectory_routes get_trajectory debe tener @require_clinician."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "trajectory_routes.py"
    content = src.read_text(encoding="utf-8")
    idx = content.find("def get_trajectory")
    assert idx > 0
    prev_block = content[max(0, idx - 200):idx]
    assert "@require_clinician" in prev_block


def test_s6_a_decision_override_endpoints_have_auth():
    """POST + GET + stats deben tener decorators correctos."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "decision_override_routes.py"
    content = src.read_text(encoding="utf-8")
    # record_override (POST) → clinician
    rec_idx = content.find("def record_override")
    assert rec_idx > 0
    rec_block = content[max(0, rec_idx - 200):rec_idx]
    assert "@require_clinician" in rec_block

    # get_override_history (GET) → clinician
    hist_idx = content.find("def get_override_history")
    assert hist_idx > 0
    hist_block = content[max(0, hist_idx - 200):hist_idx]
    assert "@require_clinician" in hist_block

    # get_override_stats (poblacional) → admin
    stats_idx = content.find("def get_override_stats")
    assert stats_idx > 0
    stats_block = content[max(0, stats_idx - 200):stats_idx]
    assert "@require_admin" in stats_block


def test_s6_a_data_integrity_endpoints_have_auth():
    """4 endpoints data_integrity deben tener auth apropiado."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "data_integrity_routes.py"
    content = src.read_text(encoding="utf-8")

    # get_population_audit → admin (operación poblacional)
    a_idx = content.find("def get_population_audit")
    assert a_idx > 0
    a_block = content[max(0, a_idx - 200):a_idx]
    assert "@require_admin" in a_block

    # get_patient_data_integrity → clinician
    b_idx = content.find("def get_patient_data_integrity")
    assert b_idx > 0
    b_block = content[max(0, b_idx - 200):b_idx]
    assert "@require_clinician" in b_block

    # post_resolve_patient (MUTACIÓN) → clinician
    c_idx = content.find("def post_resolve_patient")
    assert c_idx > 0
    c_block = content[max(0, c_idx - 200):c_idx]
    assert "@require_clinician" in c_block

    # post_population_apply (MUTACIÓN POBLACIONAL CATASTRÓFICA) → admin
    d_idx = content.find("def post_population_apply")
    assert d_idx > 0
    d_block = content[max(0, d_idx - 200):d_idx]
    assert "@require_admin" in d_block


# ─────────────────────────────────────────────────────────────────────
# S6.B — Info-leak fix (no str(exc) en responses)
# ─────────────────────────────────────────────────────────────────────


def test_s6_b_no_str_exc_in_responses():
    """Los 4 endpoints REST NO deben tener jsonify(...error=str(exc)).

    Solo se permite logger.exception(...) que va al log, no al cliente.
    """
    from pathlib import Path
    src_files = [
        "prostanet/presentation/trajectory_routes.py",
        "prostanet/presentation/decision_override_routes.py",
        "prostanet/presentation/data_integrity_routes.py",
    ]
    bad_patterns = [
        'jsonify({"success": False, "error": str(exc)})',
        'jsonify({"error": str(exc)})',
    ]
    for rel in src_files:
        content = (Path(__file__).parent.parent / rel).read_text(encoding="utf-8")
        for pattern in bad_patterns:
            assert pattern not in content, (
                f"{rel} still leaks str(exc) to client: '{pattern}'"
            )


def test_s6_b_internal_error_pattern_present():
    """Los endpoints deben usar internal_error en lugar de str(exc)."""
    from pathlib import Path
    for rel in (
        "prostanet/presentation/trajectory_routes.py",
        "prostanet/presentation/decision_override_routes.py",
        "prostanet/presentation/data_integrity_routes.py",
    ):
        content = (Path(__file__).parent.parent / rel).read_text(encoding="utf-8")
        assert '"internal_error"' in content or '"audit_failed"' in content or '"resolve_failed"' in content or '"snapshot_failed"' in content


# ─────────────────────────────────────────────────────────────────────
# S6.C — Audit + HMAC + atomic transactions
# ─────────────────────────────────────────────────────────────────────


def test_s6_c_hmac_signature_function_replaced():
    """_compute_audit_signature debe usar HMAC-SHA256 (no plain SHA-256)."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "decision_override_routes.py"
    content = src.read_text(encoding="utf-8")
    # Debe importar hmac
    assert "import hmac" in content
    # Debe llamar hmac.new
    assert "hmac.new(" in content
    # Comentario explicativo Sprint 6 C9
    assert "C9" in content and "HMAC" in content


def test_s6_c_data_integrity_has_audit_trail():
    """data_integrity_routes debe llamar audit log en cada handler."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "data_integrity_routes.py"
    content = src.read_text(encoding="utf-8")
    # Helper de audit debe existir
    assert "_audit_data_integrity_operation" in content
    # Debe insertar en clinical_view_audit
    assert "INSERT INTO clinical_view_audit" in content


def test_s6_c_override_atomic_transaction():
    """decision_override record_override debe usar BEGIN/COMMIT explícito."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "decision_override_routes.py"
    content = src.read_text(encoding="utf-8")
    assert 'cur.execute("BEGIN")' in content
    assert 'cur.execute("COMMIT")' in content
    assert 'ROLLBACK' in content


def test_s6_c_resolve_atomic_transaction():
    """data_integrity post_resolve_patient debe usar BEGIN/COMMIT."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "data_integrity_routes.py"
    content = src.read_text(encoding="utf-8")
    assert 'conn.execute("BEGIN")' in content
    assert 'conn.execute("COMMIT")' in content
    assert 'ROLLBACK' in content


def test_s6_c_normalized_reasons_table():
    """Schema debe incluir clinical_override_event_reason para SQL aggregation."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "decision_override_routes.py"
    content = src.read_text(encoding="utf-8")
    assert "clinical_override_event_reason" in content
    assert "CREATE INDEX IF NOT EXISTS idx_override_reason_code" in content


# ─────────────────────────────────────────────────────────────────────
# S6.D — Performance + caching
# ─────────────────────────────────────────────────────────────────────


def test_s6_d_prediction_service_cached_singleton():
    """ml_inference_routes debe cachear PredictionService."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "ml_inference_routes.py"
    content = src.read_text(encoding="utf-8")
    assert "_PREDICTION_SERVICE_CACHE" in content
    assert "_PREDICTION_SERVICE_LOCK" in content
    assert "_get_or_build_prediction_service" in content
    assert "reset_prediction_service_cache" in content


def test_s6_d_single_model_get_only_runs_one():
    """build_ml_predictions_snapshot debe aceptar models_to_run filter."""
    from prostanet.presentation.ml_inference_routes import build_ml_predictions_snapshot
    import inspect
    sig = inspect.signature(build_ml_predictions_snapshot)
    assert "models_to_run" in sig.parameters


def test_s6_d_trajectory_uses_drug_class_catalog():
    """trajectory_routes debe usar catálogo canónico, no substring."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "trajectory_routes.py"
    content = src.read_text(encoding="utf-8")
    assert "ARSI_DRUG_CLASS_TOKENS" in content
    assert "ADT_DRUG_CLASS_TOKENS" in content
    # Catálogo debe estar como frozenset (immutable)
    assert "frozenset" in content


def test_s6_d_try_finally_conn_close():
    """Los 3 archivos (ml, trajectory, override) deben usar try/finally."""
    from pathlib import Path
    for rel in (
        "prostanet/presentation/ml_inference_routes.py",
        "prostanet/presentation/trajectory_routes.py",
        "prostanet/presentation/decision_override_routes.py",
    ):
        content = (Path(__file__).parent.parent / rel).read_text(encoding="utf-8")
        # Debe tener try/finally con conn.close()
        assert "finally:" in content and "conn.close()" in content


# ─────────────────────────────────────────────────────────────────────
# S6.E — Validation + sanitization
# ─────────────────────────────────────────────────────────────────────


def test_s6_e_validate_iso8601():
    """_validate_iso8601 debe rechazar timestamps inválidos + futuros lejanos."""
    from prostanet.presentation.decision_override_routes import _validate_iso8601
    # Válido
    assert _validate_iso8601("2026-05-24T20:00:00+00:00") is not None
    assert _validate_iso8601("2026-05-24T20:00:00Z") is not None
    # Inválido
    assert _validate_iso8601("not-a-date") is None
    assert _validate_iso8601("") is None
    assert _validate_iso8601(None) is None
    # Futuro lejano (>24h) → rechazado
    assert _validate_iso8601("2099-01-01T00:00:00Z") is None


def test_s6_e_clamp_confidence():
    """_clamp_confidence debe clamp al rango [0, 1]."""
    from prostanet.presentation.decision_override_routes import _clamp_confidence
    assert _clamp_confidence(0.5) == 0.5
    assert _clamp_confidence(1.5) == 1.0  # clamp upper
    assert _clamp_confidence(-0.2) == 0.0  # clamp lower
    assert _clamp_confidence(None) == 0.0
    assert _clamp_confidence("not_a_number") == 0.0


def test_s6_e_sanitize_free_text():
    """_sanitize_free_text debe truncar + strip control chars."""
    from prostanet.presentation.decision_override_routes import (
        _sanitize_free_text, MAX_FREE_TEXT_LENGTH,
    )
    # Truncación
    long_text = "A" * (MAX_FREE_TEXT_LENGTH + 500)
    assert len(_sanitize_free_text(long_text)) == MAX_FREE_TEXT_LENGTH
    # Control chars filtrados (excepto \n, \t)
    text_with_control = "Normal text\x00\x07\x1b\nWith newline\tand tab"
    out = _sanitize_free_text(text_with_control)
    assert "\x00" not in out
    assert "\x07" not in out
    assert "\n" in out
    assert "\t" in out


# ─────────────────────────────────────────────────────────────────────
# S6.F — state_transition mitigation UI
# ─────────────────────────────────────────────────────────────────────


def test_s6_f_template_has_retrain_banner():
    """Template debe tener banner de re-entrenamiento para modelos incompatibles."""
    from pathlib import Path
    template = Path(__file__).parent.parent / "templates" / "patient_profile_v2.html"
    content = template.read_text(encoding="utf-8")
    assert 'data-testid="ml-card-retrain-banner"' in content
    assert "retrain_required" in content
    assert "Modelo en re-entrenamiento" in content


# ─────────────────────────────────────────────────────────────────────
# S6.G — Constants + LOW cleanup
# ─────────────────────────────────────────────────────────────────────


def test_s6_g_constants_defined():
    """Magic strings extraídos a constantes module-level."""
    from prostanet.presentation.ml_inference_routes import (
        UNREGISTERED_VERSION, UNKNOWN_VERSION, ERROR_MATURITY,
    )
    assert UNREGISTERED_VERSION == "unregistered"
    assert UNKNOWN_VERSION == "unknown"
    assert ERROR_MATURITY == "error"

    from prostanet.presentation.decision_override_routes import (
        MAX_FREE_TEXT_LENGTH, DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT,
    )
    assert MAX_FREE_TEXT_LENGTH == 4000
    assert DEFAULT_HISTORY_LIMIT == 50
    assert MAX_HISTORY_LIMIT == 500


def test_s6_g_db_path_consistency():
    """data_integrity_routes debe usar tracking_db.DB_PATH (no path local)."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "prostanet" / "presentation" / "data_integrity_routes.py"
    content = src.read_text(encoding="utf-8")
    # No debe calcular su propio DB_PATH
    assert "DB_PATH = Path(__file__).parent.parent.parent" not in content
    # Debe usar tracking_db.DB_PATH
    assert "tracking_db.DB_PATH" in content


# ─────────────────────────────────────────────────────────────────────
# Foundation — FAUBOT version bump
# ─────────────────────────────────────────────────────────────────────


def test_s6_faubot_release_bumped_to_cxliv():
    """algorithm_version debe ser al menos CXLIV (release Sprint 6).
    Sprint 7+ bumps a CXLV+ son válidos también."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    valid_releases = ("CXLIV", "CXLV", "CXLVI", "CXLVII", "CXLVIII", "CXLIX", "CL")
    assert any(rel in FAUBOT_RELEASE for rel in valid_releases), (
        f"FAUBOT_RELEASE should be ≥CXLIV, got: {FAUBOT_RELEASE}"
    )


# ─────────────────────────────────────────────────────────────────────
# Smoke functional: auth decorators bypass-mode for test
# ─────────────────────────────────────────────────────────────────────


def test_s6_auth_test_bypass_works():
    """En env PROSTANET_API_AUTH_BYPASS=1, decorator debe permitir paso."""
    import os
    os.environ["PROSTANET_API_AUTH_BYPASS"] = "1"
    try:
        from prostanet.shared.api_auth import require_clinician

        @require_clinician
        def dummy_handler():
            return {"ok": True}

        # Llamar fuera de Flask context — debe funcionar via bypass
        result = dummy_handler()
        assert result == {"ok": True}
    finally:
        os.environ.pop("PROSTANET_API_AUTH_BYPASS", None)
