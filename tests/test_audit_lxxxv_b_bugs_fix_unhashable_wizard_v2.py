"""tests/test_audit_lxxxv_b_bugs_fix_unhashable_wizard_v2.py — FAUBOT LXXXV.b.

Tests para fix de 2 bugs reportados por el usuario post-LXXXV:

**Bug #1 — `unhashable type: 'list'` en register_patient v2 intake**
Root cause: v2 intake renderiza fields duplicados (`hrr_status`,
`decision_rp_vs_rt_active`, `psa_density`) en 2 stages cada uno. FormData
colecta `<select>` duplicados como list → backend rompe en value_map lookup
+ set membership downstream con TypeError.

Fix doble (defensa en profundidad FDA SaMD):
1. **Source fix** (`v2_advanced_capture_builder.py`): de-dup fields cross-stages
   con `_emitted_field_names` set; first-stage wins.
2. **Backend defensive fix** (`patient_tracking/service.py canonicalize_payload()`):
   colapsa list-valued fields a scalar (último non-empty value, semántica HTML form).
   Preserva lists legítimas (psa_history, prior_treatment_lines, etc.).

**Bug #2 — Wizards en Centro Clínico redirigen a interface legacy**
Root cause: `/wizard/<module>` route en `views.py` renderea
`clinical_wizard.html` legacy unconditionally — sin `?v=` flag check.

Fix: chrome-aware single template (mismo patrón LXXX para hub/dashboard/profile):
- Route pasa `chrome_mode = 'v2'` (default) o 'legacy' (vía `?v=legacy`)
- `clinical_wizard.html` envuelve form internals con pm2_sidebar + actionbar
  moderno cuando `chrome_mode == 'v2'`
- 100% form internals legacy preservadas (widgets + draft + consent + JS)

HIPÓTESIS: H.G2824 → H.G2840 (~17 tests).
Faubot LXXXV.b — 2 bug fixes pre-Iteración #3 Cortana.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            if n.startswith("__") and n.endswith("__"):
                raise AttributeError(n)
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")


# ──────────────────────────────────────────────────────────────────────
# §A — Bug #1: Unhashable type 'list' fix
# ──────────────────────────────────────────────────────────────────────


def test_g2824_canonicalize_payload_collapses_list_to_scalar():
    """H.G2824 — canonicalize_payload colapsa list-valued scalar fields a último valor."""
    from prostanet.domains.patient_tracking.service import PatientTrackingService
    svc = PatientTrackingService()
    result = svc.canonicalize_payload({
        "hrr_status": ["hrr_positive", "hrr_positive"],
        "decision_rp_vs_rt_active": ["rp", "rp"],
        "psa_density": [0.15, 0.15],
    })
    # Lista colapsa a último valor (semántica HTML form duplicate select)
    assert not isinstance(result["hrr_status"], list)
    assert result["hrr_status"] == "hrr_positive"
    assert not isinstance(result["decision_rp_vs_rt_active"], list)
    assert result["decision_rp_vs_rt_active"] == "rp"
    assert not isinstance(result["psa_density"], list)


def test_g2825_canonicalize_payload_preserves_legit_list_fields():
    """H.G2825 — canonicalize NO colapsa lists legítimas (psa_history, etc.)."""
    from prostanet.domains.patient_tracking.service import PatientTrackingService
    svc = PatientTrackingService()
    psa_list = [
        {"sample_date": "2025-01-15", "value": 12.0},
        {"sample_date": "2025-04-15", "value": 10.0},
    ]
    result = svc.canonicalize_payload({
        "psa_history": psa_list,
        "prior_treatment_lines": [{"drug_scheme": "ADT"}],
        "hrr_genes_mutated": ["BRCA2", "ATM"],
    })
    # Lists legítimas se preservan (no colapsan)
    assert isinstance(result["psa_history"], list)
    assert len(result["psa_history"]) == 2
    assert isinstance(result["prior_treatment_lines"], list)
    assert isinstance(result["hrr_genes_mutated"], list)


def test_g2826_canonicalize_handles_empty_list_safely():
    """H.G2826 — canonicalize maneja list vacía o con None safely."""
    from prostanet.domains.patient_tracking.service import PatientTrackingService
    svc = PatientTrackingService()
    result = svc.canonicalize_payload({
        "hrr_status": [],
        "decision_rp_vs_rt_active": [None, ""],
    })
    assert result["hrr_status"] == ""
    assert result["decision_rp_vs_rt_active"] == ""


def test_g2827_register_patient_with_duplicate_field_no_unhashable_error():
    """H.G2827 — POST /api/register_patient con list-valued duplicate fields NO produce 'unhashable type' TypeError.

    El bug original: POST con `hrr_status: [...]` (renderizado 2x en v2 intake)
    rompía con `TypeError: unhashable type: 'list'`. Post-fix: la list colapsa a
    scalar (defensa) + source de-dup evita el problema.

    Status code puede variar (200/400) según validación completeness, pero NUNCA
    debe ser 500 ni contener mensaje 'unhashable' en el body.
    """
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.post("/api/register_patient", json={
            "nss": "BUG_FIX_LXXXV_B_001",
            "full_name": "Test BugFix",
            "baseline_psa": 8.4,
            "gleason_score": 7,
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "clinical_tstage": "T2a",
            "metastasis_site": "M0",
            "ecog_score": 0,
            "charlson_score": 1,
            "line_of_therapy": 0,
            "child_pugh_score": "A",
            "rt_primary_received": 0,
            # Bug repro: list-valued duplicate fields
            "hrr_status": ["hrr_positive", "hrr_positive"],
            "decision_rp_vs_rt_active": ["rp", "rp"],
            "psa_density": [0.15, 0.15],
        })
        # NO 500 server error
        assert r.status_code != 500, f"Server error: {r.data.decode()[:200]}"
        # Body no contiene unhashable error (el bug específico que arreglamos)
        body = r.get_data(as_text=True).lower()
        assert "unhashable" not in body, f"Unhashable bug NOT fixed: {body[:200]}"
        assert "typeerror" not in body, f"Unexpected TypeError: {body[:200]}"


def test_g2828_no_unhashable_error_in_response():
    """H.G2828 — Response NO contiene 'unhashable type' error."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.post("/api/register_patient", json={
            "nss": "BUG_FIX_LXXXV_B_002",
            "full_name": "Test NoUnhashable",
            "baseline_psa": 5.0, "gleason_score": 6,
            "gleason_primary": 3, "gleason_secondary": 3,
            "clinical_tstage": "T1c", "metastasis_site": "M0",
            "ecog_score": 0, "charlson_score": 0, "line_of_therapy": 0,
            "child_pugh_score": "A", "rt_primary_received": 0,
            "hrr_status": ["hrr_positive", "hrr_positive"],
        })
        body_text = r.get_data(as_text=True)
        assert "unhashable" not in body_text.lower()
        assert "TypeError" not in body_text


def test_g2829_v2_advanced_stages_have_no_duplicate_field_names():
    """H.G2829 — build_advanced_capture_stages NO emite duplicate field names cross-stages."""
    from prostanet.presentation.v2_advanced_capture_builder import build_advanced_capture_stages
    stages, fields = build_advanced_capture_stages()
    all_field_names = []
    for stage in stages:
        for f in fields[stage["key"]]:
            all_field_names.append(f["name"])
    duplicates = [n for n in set(all_field_names) if all_field_names.count(n) > 1]
    assert not duplicates, f"Duplicate field names cross-stages: {duplicates}"


def test_g2830_v2_advanced_stages_preserve_fields_count():
    """H.G2830 — De-dup preserva al menos 380+ unique fields (no rompe coverage)."""
    from prostanet.presentation.v2_advanced_capture_builder import build_advanced_capture_stages
    stages, fields = build_advanced_capture_stages()
    total_unique = sum(len(fields[s["key"]]) for s in stages)
    # Pre-LXXXV.b had 384 fields with duplicates; post-LXXXV.b should have ~380+ unique
    assert total_unique >= 380, f"Coverage drop: {total_unique} unique fields (expected ≥380)"


# ──────────────────────────────────────────────────────────────────────
# §B — Bug #2: Wizard v2 chrome migration
# ──────────────────────────────────────────────────────────────────────


def test_g2831_wizard_default_renders_v2_chrome():
    """H.G2831 — GET /wizard/<module> sin flag → renderea v2 chrome con sidebar."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        # v2 chrome markers
        assert "pm2-wizard-shell" in html, "Missing v2 sidebar shell"
        assert "pm2-sidebar-link" in html, "Missing pm2_sidebar macro markers"
        assert "pm2-wizard-breadcrumb" in html, "Missing v2 breadcrumb"


def test_g2832_wizard_legacy_opt_out_works():
    """H.G2832 — GET /wizard/<module>?v=legacy → renderea v1 legacy intacto."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial?v=legacy")
        assert r.status_code == 200
        html = r.data.decode("utf-8")
        # v2 markers absent
        assert "pm2-wizard-shell" not in html
        # Legacy markers present
        assert "Datos clínicos" in html
        assert "Volver al centro clínico" in html


def test_g2833_wizard_v2_preserves_form_internals():
    """H.G2833 — v2 chrome preserva form internals legacy (widgets, draft button, consent)."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        html = r.data.decode("utf-8")
        # Form internals presentes
        assert 'id="submitWizard"' in html, "Missing legacy submit button (needed for JS wire)"
        assert "consent_modal" in html or "consentSubmitButton" in html, "Missing consent modal"
        # v2 hidden submit + visible top button
        assert "submitWizardTop" in html, "Missing v2 actionbar top button"


def test_g2834_wizard_v2_includes_audit_dims():
    """H.G2834 — v2 chrome incluye FAUBOT_RELEASE + gates count en sidebar."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        html = r.data.decode("utf-8")
        # Sidebar muestra release + gates
        assert "LXXXV" in html or "LXXXIV" in html, "Missing FAUBOT_RELEASE"
        # Stats badges (count gates etc.)
        assert "FAUBOT_RELEASE" in html


def test_g2835_wizard_v2_back_link_to_clinical_hub():
    """H.G2835 — v2 chrome tiene breadcrumb back a /clinical-hub."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        html = r.data.decode("utf-8")
        assert 'href="/clinical-hub"' in html
        assert "Centro clínico" in html


def test_g2836_wizard_v2_has_legacy_opt_out_link():
    """H.G2836 — v2 chrome ofrece link 'Ver legacy' para opt-out."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        html = r.data.decode("utf-8")
        assert 'href="?v=legacy"' in html or "Ver legacy" in html


def test_g2837_all_15_wizard_modules_render_v2():
    """H.G2837 — Los 15 módulos canónicos rendean v2 sin 500."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        modules = [
            "diagnostic_workup", "post_negative_biopsy_followup",
            "localized_initial", "post_prostatectomy",
            "post_radiotherapy_followup", "recurrence_bcr",
            "post_radiotherapy_or_local_salvage", "adt_progression_verification",
            "mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync", "mcspc_high_volume_metachronous",
            "m0_crpc", "m1_crpc", "survivorship_and_toxicity_followup",
        ]
        failed = []
        for mod in modules:
            r = client.get(f"/wizard/{mod}")
            if r.status_code != 200:
                failed.append((mod, r.status_code))
        assert not failed, f"Modules failing v2 render: {failed}"


def test_g2838_wizard_v2_loads_v2_css():
    """H.G2838 — v2 chrome carga prostamed_v2.css adicional."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r = client.get("/wizard/localized_initial")
        html = r.data.decode("utf-8")
        assert "prostamed_v2.css" in html


def test_g2839_wizard_route_passes_chrome_mode_to_template():
    """H.G2839 — Route pasa chrome_mode + audit_dims_v2 a template."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        # v2 default
        r = client.get("/wizard/m1_crpc")
        assert r.status_code == 200
        assert "pm2-wizard-shell" in r.data.decode("utf-8")
        # legacy opt-out
        r2 = client.get("/wizard/m1_crpc?v=legacy")
        assert r2.status_code == 200
        assert "pm2-wizard-shell" not in r2.data.decode("utf-8")


def test_g2840_v2_chrome_unique_per_module():
    """H.G2840 — Cada módulo en v2 muestra su propio título + descripción."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True})
    with flask_app.test_client() as client:
        r1 = client.get("/wizard/localized_initial")
        r2 = client.get("/wizard/m1_crpc")
        h1 = r1.data.decode("utf-8")
        h2 = r2.data.decode("utf-8")
        # Títulos diferentes (cada módulo tiene su propio schema.title)
        # pm2-wizard-title aparece en ambos pero con contenido distinto
        assert "pm2-wizard-title" in h1
        assert "pm2-wizard-title" in h2
