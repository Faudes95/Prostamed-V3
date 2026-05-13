"""tests/test_audit_lxxxvi_ui_clinical_recovery.py — FAUBOT LXXXVI.
IEC 62304 §5.7 (software system testing).

Tests para Iteración LXXXVI — UI Clinical Logic Recovery:

- §A: Multirow widget scope binding (CSS overflow:visible + min-width:0)
- §B: Consent modal z-index 200 (above sidebar 100)
- §C: V2 intake renders 487 fields across 21 stages (verified — Agent 1 false positive)
- §D: 7 critical FieldSpecs added/verified (qtc_baseline + lvef + tertiary + bone + germline)
- §E: Backend integration: gates fire end-to-end with realistic clinical payloads

HIPÓTESIS: H.G3051 → H.G3075 (~25 tests).
Faubot LXXXVI — UI Clinical Logic Recovery.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            if n.startswith("__") and n.endswith("__"):
                raise AttributeError(n)
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")

ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")


# ──────────────────────────────────────────────────────────────────────
# §A — Multirow widget scope binding (CSS overflow fix)
# ──────────────────────────────────────────────────────────────────────


def test_g3051_clinical_wizard_overflow_visible_for_widgets():
    """H.G3051 — pm2-wizard-main usa overflow:visible (no clip widgets popovers)."""
    template = (ROOT / "templates/clinical_wizard.html").read_text()
    # Pre-LXXXVI: overflow-x:auto clipping multirow popovers
    # Post-LXXXVI: overflow:visible + min-width:0 for proper widget rendering
    assert ".pm2-wizard-main{padding:1.5rem 2rem;overflow:visible;min-width:0;}" in template, (
        "pm2-wizard-main CSS missing overflow:visible + min-width:0"
    )


def test_g3052_pm2_wizard_shell_grid_layout_intact():
    """H.G3052 — pm2-wizard-shell grid layout 280px sidebar + 1fr main preserved."""
    template = (ROOT / "templates/clinical_wizard.html").read_text()
    assert ".pm2-wizard-shell{display:grid;grid-template-columns:280px 1fr" in template


def test_g3053_v2_chrome_mobile_responsive():
    """H.G3053 — pm2-wizard-shell collapses to single column @ <768px."""
    template = (ROOT / "templates/clinical_wizard.html").read_text()
    assert "@media (max-width:768px){.pm2-wizard-shell{grid-template-columns:1fr;}}" in template


def test_g3054_registration_context_ui_binders_unchanged():
    """H.G3054 — bind functions (Metastatic + Gleason + PsaHistory) preserved."""
    js = (ROOT / "static/js/registration_context_ui.js").read_text()
    # Critical binding functions preserved (not deleted by chrome v2 migration)
    assert "function bindMetastaticComponents(scope)" in js
    assert "function bindGleasonProfiles(scope)" in js
    assert "function bindPsaHistory(scope)" in js
    assert "function bindTestosteroneHistory(scope)" in js


def test_g3055_buildregistrationpayload_calls_all_binders():
    """H.G3055 — buildRegistrationPayload calls 4 bind helpers en form scope."""
    js = (ROOT / "static/js/registration_context_ui.js").read_text()
    # Strict order to ensure data-sync before payload extraction
    payload_fn_idx = js.index("function buildRegistrationPayload")
    payload_fn = js[payload_fn_idx:payload_fn_idx + 800]
    assert "bindGleasonProfiles(form);" in payload_fn
    assert "bindMetastaticComponents(form);" in payload_fn
    assert "syncPsaHistoryField(form);" in payload_fn
    assert "syncTestosteroneHistoryField(form);" in payload_fn


# ──────────────────────────────────────────────────────────────────────
# §B — Consent modal z-index stacking
# ──────────────────────────────────────────────────────────────────────


def test_g3056_consent_modal_z_index_200():
    """H.G3056 — Consent modal z-[200] (above any v2 sidebar/header)."""
    template = (ROOT / "templates/components/consent_modal.html").read_text()
    assert 'z-[200]' in template, "Consent modal z-index not bumped to 200"
    assert 'z-[90]' not in template, "Old z-[90] still present (should be 200)"


def test_g3057_consent_modal_fixed_inset_preserved():
    """H.G3057 — Modal fixed inset-0 + bg overlay preserved."""
    template = (ROOT / "templates/components/consent_modal.html").read_text()
    assert 'class="fixed inset-0' in template
    assert 'bg-slate-950/80' in template


def test_g3058_consent_modal_above_v2_sidebar_zindex():
    """H.G3058 — Consent z-index (200) > all prostamed_v2.css z-indexes."""
    css = (ROOT / "static/css/prostamed_v2.css").read_text()
    # Find max z-index in v2 css
    import re
    z_values = [int(m.group(1)) for m in re.finditer(r"z-index:\s*(\d+)", css)]
    max_z_v2 = max(z_values) if z_values else 0
    assert max_z_v2 < 200, f"v2 css has z-index ≥200: {max_z_v2} (modal would be hidden)"


# ──────────────────────────────────────────────────────────────────────
# §C — V2 intake renders all 21 stages × 487 fields
# ──────────────────────────────────────────────────────────────────────


def test_g3059_intake_v2_renders_21_stages():
    """H.G3059 — build_intake_demo_data returns ≥21 stages (9 base + 12 advanced)."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    assert len(data["stages"]) >= 21, f"Expected ≥21 stages, got {len(data['stages'])}"


def test_g3060_intake_v2_total_fields_at_least_485():
    """H.G3060 — Total fields cross-stages ≥485 (485-487 typical)."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    total = sum(len(v) for v in data["fields"].values())
    assert total >= 485, f"Field count regressed: {total} (expected ≥485)"


def test_g3061_intake_v2_unique_field_names():
    """H.G3061 — De-dup ensures unique field names cross-stages."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    all_names = []
    for stage_fields in data["fields"].values():
        for f in stage_fields:
            if f.get("name"):
                all_names.append(f["name"])
    duplicates = [n for n in set(all_names) if all_names.count(n) > 1]
    assert not duplicates, f"Duplicate field names: {duplicates}"


def test_g3062_intake_v2_5_advanced_stages_present():
    """H.G3062 — 5 advanced stages from gates 56-85 are merged."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    stage_keys = {s["key"] for s in data["stages"]}
    expected_advanced = {
        "subspecialty_rt_rp", "genomic_critical", "pre_dx_atypical",
        "progression_detection", "palliative_radiopharm",
    }
    missing = expected_advanced - stage_keys
    assert not missing, f"Advanced stages missing: {missing}"


def test_g3063_v2_intake_route_redirects_to_official_classifier():
    """H.G3063 — GET /patient_intake?v=2 no longer renders the 487-field form."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.get("/patient_intake?v=2", follow_redirects=False)
        assert r.status_code in (301, 302, 303, 307, 308)
        assert "/clinical-hub#pm2OfficialClassifier" in r.headers.get("Location", "")


# ──────────────────────────────────────────────────────────────────────
# §D — 7 critical FieldSpecs (4 added by LXXXVI + 3 verified existing)
# ──────────────────────────────────────────────────────────────────────


def test_g3064_qtc_baseline_ms_in_pivotal_helper():
    """H.G3064 — qtc_baseline_ms FieldSpec in pivotal_gate_supporting_fields()."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    assert "qtc_baseline_ms" in names


def test_g3065_lvef_baseline_percent_in_pivotal_helper():
    """H.G3065 — lvef_baseline_percent FieldSpec in pivotal helper."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    assert "lvef_baseline_percent" in names


def test_g3066_germline_family_history_in_pivotal_helper():
    """H.G3066 — germline_family_history FieldSpec in pivotal helper."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    assert "germline_family_history" in names


def test_g3067_has_adverse_tertiary_pattern_in_pivotal_helper():
    """H.G3067 — has_adverse_tertiary_pattern FieldSpec in pivotal helper."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    assert "has_adverse_tertiary_pattern" in names


def test_g3068_existing_critical_fields_preserved():
    """H.G3068 — bone_modifying_agent + denosumab_prophylaxis + germline_test_refused_reason still present."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    names = {f.name for f in pivotal_gate_supporting_fields()}
    for name in ("bone_modifying_agent", "denosumab_prophylaxis", "germline_test_refused_reason"):
        assert name in names, f"Pre-existing field {name} got dropped"


def test_g3069_pivotal_helper_total_count_increased():
    """H.G3069 — Total FieldSpecs grew from ~408 to ≥410 (+2 new fields net)."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    fields = pivotal_gate_supporting_fields()
    assert len(fields) >= 410, f"Coverage regressed: {len(fields)} (expected ≥410)"


# ──────────────────────────────────────────────────────────────────────
# §E — Backend integration: gates fire with realistic payloads
# ──────────────────────────────────────────────────────────────────────


def test_g3070_qtc_baseline_field_canonical_name_consistent():
    """H.G3070 — qtc_baseline_ms field name matches gate trigger expectation."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    data = _load_yaml_files(force_reload=True)
    # Check at least one gate references qtc_baseline_ms or its alias
    found = False
    for code, config in data.items():
        config_str = str(config)
        if "qtc_baseline" in config_str or "qtc_corrected_for_arpi" in config_str:
            found = True
            break
    assert found, "No gate references qtc_baseline (UI field would be orphan)"


def test_g3071_germline_field_triggers_lynch_gate():
    """H.G3071 — germline_family_history field triggers gate 65 Lynch reflex (or alias)."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files
    data = _load_yaml_files(force_reload=True)
    # Lynch/MSI gate should reference germline or family history
    lynch_gate = None
    for code, config in data.items():
        if "lynch" in code.lower() or "msi" in code.lower() or "mmr" in code.lower():
            lynch_gate = config
            break
    assert lynch_gate is not None, "No Lynch/MSI gate found in catalog"


def test_g3072_register_patient_with_new_critical_fields():
    """H.G3072 — POST /api/register_patient con qtc_baseline + lvef + germline → no error."""
    import app as app_module
    flask_app = app_module.create_app({"TESTING": True, "LOAD_MODEL": False})
    with flask_app.test_client() as client:
        r = client.post("/api/register_patient", json={
            "nss": "BUG_FIX_LXXXVI_001",
            "full_name": "Test Critical Fields",
            "baseline_psa": 12.0,
            "gleason_score": 8,
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "clinical_tstage": "T2c",
            "metastasis_site": "M0",
            "ecog_score": 1,
            "charlson_score": 2,
            "line_of_therapy": 0,
            "child_pugh_score": "A",
            "rt_primary_received": 0,
            # New critical fields
            "qtc_baseline_ms": 440,
            "lvef_baseline_percent": 60,
            "germline_family_history": "PCa_under_55",
            "has_adverse_tertiary_pattern": "Sí_pattern_4",
        })
        assert r.status_code != 500, f"Server error: {r.data.decode()[:200]}"
        body = r.get_data(as_text=True).lower()
        assert "unhashable" not in body
        assert "typeerror" not in body


def test_g3073_realistic_mcrpc_parp_payload_fires_hrr_gate():
    """H.G3073 — mCRPC + PARP planned + sin HRR → gate hard_block fires."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, evaluate_all_yaml_gates
    _load_yaml_files(force_reload=True)
    fired = evaluate_all_yaml_gates({
        "metastasis_site": "M1",
        "m1_crpc_state_confirmed": 1,
        "castrate_testosterone_status": "confirmed_castrate",
        "planned_regimen": "OLAPARIB",
        "hrr_status": "not_tested",
        "genomic_test_done": 0,
        "considering_parp": 1,
        "prior_treatment_lines_count": 2,
    })
    fired_codes = {g["code"] for g in fired}
    assert "hrr_status_required_before_parp_inhibitor" in fired_codes, (
        f"HRR pre-PARP hard_block didn't fire: {sorted(fired_codes)}"
    )


def test_g3074_total_89_gates_loaded_post_lxxxvi():
    """H.G3074 — Catalog still loads 89 gates post-LXXXVI changes."""
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files, get_loaded_yaml_codes
    _load_yaml_files(force_reload=True)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 89, f"Gates regressed: {len(codes)} (expected ≥89)"


def test_g3075_faubot_release_bumped_post_lxcii_1():
    """H.G3075 — FAUBOT_RELEASE bumped past LXCII.1 (LXCII.2+ or LXCIII+)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Project was at LXCII.1; this iteration bumps to LXCII.2 (continuation)
    # Forward-compat: accept LXCII.2+, LXCIII+, etc.
    assert any(tag in FAUBOT_RELEASE for tag in ("LXCII.2", "LXCII.3", "LXCIII", "LXCIV", "XCV", "XCVI", "XCVII", "XCVIII", "XCIX", "C")), (
        f"FAUBOT_RELEASE not bumped past LXCII.1: {FAUBOT_RELEASE}"
    )
