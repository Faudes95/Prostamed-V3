"""EPIC 43 — Stage-specific schema coverage tests.

Pre-EPIC 43: 13/54 estados clínicos tenían schema dedicado en
_STAGE_SCHEMA_REGISTRY. 41 estados caían silenciosamente a diagnostic_workup,
perdiendo fidelidad clínica completa.

Post-EPIC 43: INLINE_STAGE_SCHEMAS cubre los 41 estados faltantes (+1 alias
hereditary_germline_pathway_umbrella). Cobertura total: 54/54 CLINICAL_STATES.

Tests:
- Cada uno de los 54 estados clínicos retorna un schema con ≥5 fields y
  título no genérico.
- Cada inline schema tiene module name terminado en `_inline`.
- Clusters específicos: risk-stratified localized, hereditary carriers,
  mCRPC subtypes, etc. — verifican fields decisivos por cluster.
- Regression: stage_specific_intake_schema sigue retornando shape v2.
"""
from __future__ import annotations

import pytest

from prostanet.ai.config import CLINICAL_STATES
from prostanet.presentation.stage_schemas_inline import INLINE_STAGE_SCHEMAS
from prostanet.presentation.v2_adapters import (
    _STAGE_SCHEMA_REGISTRY,
    stage_specific_intake_schema,
)


# ─────────────────── Coverage gates ───────────────────


class TestCoverage:
    def test_all_clinical_states_have_schema(self):
        """EPIC 43 cierra el gap: cada CLINICAL_STATE tiene schema dedicado."""
        all_covered = set(_STAGE_SCHEMA_REGISTRY.keys()) | set(INLINE_STAGE_SCHEMAS.keys())
        uncovered = set(CLINICAL_STATES) - all_covered
        assert not uncovered, (
            f"Estados clínicos SIN schema dedicado: {sorted(uncovered)}. "
            f"Pre-EPIC43 = 41, target post-EPIC43 = 0."
        )

    def test_inline_registry_size_at_least_41(self):
        # 41 estados faltantes + 1 alias palb2 carrier = 42 esperados
        assert len(INLINE_STAGE_SCHEMAS) >= 41

    def test_no_state_returns_empty_schema(self):
        """Ningún CLINICAL_STATE debe retornar fields vacíos."""
        for state in CLINICAL_STATES:
            r = stage_specific_intake_schema(state)
            assert r["total_fields"] > 0, f"State {state} retornó 0 fields"


@pytest.mark.parametrize("state", sorted(INLINE_STAGE_SCHEMAS.keys()))
class TestInlineSchemaQuality:
    def test_schema_builds_without_error(self, state):
        builder = INLINE_STAGE_SCHEMAS[state]
        s = builder()
        assert isinstance(s, dict)
        assert "fields" in s

    def test_schema_has_at_least_5_fields(self, state):
        builder = INLINE_STAGE_SCHEMAS[state]
        s = builder()
        assert len(s["fields"]) >= 5, (
            f"Schema {state} tiene {len(s['fields'])} fields, mínimo 5 para utilidad clínica"
        )

    def test_schema_has_title_and_description(self, state):
        builder = INLINE_STAGE_SCHEMAS[state]
        s = builder()
        assert s.get("title")
        assert s.get("description")
        assert s.get("module", "").endswith("_inline")

    def test_schema_has_at_least_one_required_field(self, state):
        builder = INLINE_STAGE_SCHEMAS[state]
        s = builder()
        required = [f for f in s["fields"] if f.get("required") or f.get("clinical_role") == "required"]
        assert len(required) >= 1, f"Schema {state} no tiene fields required"


# ─────────────────── Per-cluster clinical coverage ───────────────────


class TestRiskStratifiedLocalizedCluster:
    """NCCN PROS-2/3/4/5 v2026 — 6 risk tiers."""

    @pytest.mark.parametrize("state", [
        "very_low_risk_localized", "low_risk_localized",
        "favorable_intermediate_risk_localized",
        "unfavorable_intermediate_risk_localized",
        "high_risk_localized", "very_high_risk_localized",
    ])
    def test_all_6_risk_tiers_have_schema(self, state):
        r = stage_specific_intake_schema(state)
        assert r["total_fields"] >= 10

    def test_very_high_risk_requires_mdt_review(self):
        s = INLINE_STAGE_SCHEMAS["very_high_risk_localized"]()
        names = {f["name"] for f in s["fields"]}
        assert "multidisciplinary_review_completed" in names

    def test_high_risk_requires_germline(self):
        s = INLINE_STAGE_SCHEMAS["high_risk_localized"]()
        names = {f["name"] for f in s["fields"]}
        assert "germline_testing_universal_done" in names

    def test_favorable_intermediate_tracks_pattern_4_percent(self):
        s = INLINE_STAGE_SCHEMAS["favorable_intermediate_risk_localized"]()
        names = {f["name"] for f in s["fields"]}
        assert "percent_pattern_4_confirmed" in names


class TestHereditaryCarriersCluster:
    """7 carriers + umbrella — NCCN PROS-A v2026."""

    @pytest.mark.parametrize("state", [
        "brca2_carrier", "brca1_carrier", "atm_carrier", "palb2_carrier",
        "hoxb13_carrier", "lynch_carrier", "hereditary_germline_pathway_umbrella",
    ])
    def test_all_carriers_have_counseling_fields(self, state):
        s = INLINE_STAGE_SCHEMAS[state]()
        names = {f["name"] for f in s["fields"]}
        assert "genetic_counseling_provided" in names, f"{state} sin counseling field"
        assert "family_cascade_testing_status" in names

    def test_lynch_carrier_includes_msi(self):
        s = INLINE_STAGE_SCHEMAS["lynch_carrier"]()
        names = {f["name"] for f in s["fields"]}
        assert "msi_status_tumor" in names
        assert "pembrolizumab_evaluated" in names

    def test_brca2_includes_parp_eligibility(self):
        s = INLINE_STAGE_SCHEMAS["brca2_carrier"]()
        names = {f["name"] for f in s["fields"]}
        assert "parp_eligibility_evaluated" in names


class TestMCRPCSubtypesCluster:
    """6 mCRPC subtypes — NCCN PROS-J v2026."""

    @pytest.mark.parametrize("state,key_field", [
        ("mcrpc_arsi_naive", "arpi_first_line_choice"),
        ("mcrpc_post_arsi", "next_line_choice"),
        ("mcrpc_hrr_positive_parp_naive", "hrr_gene_specific"),
        ("mcrpc_psma_eligible_lu177", "psma_pet_status"),
        ("mcrpc_msi_h_dmmr", "msi_test_method"),
        ("nepc_differentiation", "nepc_confirmed_histology"),
    ])
    def test_subtype_has_decisive_field(self, state, key_field):
        s = INLINE_STAGE_SCHEMAS[state]()
        names = {f["name"] for f in s["fields"]}
        assert key_field in names

    def test_mcrpc_psma_includes_gfr_safety(self):
        """Lu-177 requires GFR baseline."""
        s = INLINE_STAGE_SCHEMAS["mcrpc_psma_eligible_lu177"]()
        names = {f["name"] for f in s["fields"]}
        assert "gfr_baseline_lu177" in names

    def test_mcrpc_hrr_includes_safety_baseline(self):
        s = INLINE_STAGE_SCHEMAS["mcrpc_hrr_positive_parp_naive"]()
        names = {f["name"] for f in s["fields"]}
        assert "hemoglobin_baseline_parp" in names
        assert "platelet_baseline_parp" in names


class TestPostLocalModalityCluster:
    @pytest.mark.parametrize("state", [
        "post_brachy_ldr", "post_brachy_hdr", "post_ebrt_alone",
        "post_sbrt", "post_focal_therapy",
    ])
    def test_all_modalities_have_psa_followup(self, state):
        s = INLINE_STAGE_SCHEMAS[state]()
        names = {f["name"] for f in s["fields"]}
        assert "current_psa" in names
        assert "current_psa_date" in names

    def test_brachy_tracks_bounce(self):
        s = INLINE_STAGE_SCHEMAS["post_brachy_ldr"]()
        names = {f["name"] for f in s["fields"]}
        assert "psa_bounce_documented" in names

    def test_focal_tracks_in_field_biopsy(self):
        s = INLINE_STAGE_SCHEMAS["post_focal_therapy"]()
        names = {f["name"] for f in s["fields"]}
        assert "in_field_biopsy_done" in names


class TestOligometastaticCluster:
    @pytest.mark.parametrize("state", [
        "oligometastatic_synchronous", "oligometastatic_metachronous_adt_naive",
        "oligo_recurrent_post_definitive", "oligo_progressive_on_therapy",
    ])
    def test_oligo_tracks_lesion_count_and_mdt(self, state):
        s = INLINE_STAGE_SCHEMAS[state]()
        names = {f["name"] for f in s["fields"]}
        assert "oligometastatic_lesion_count" in names
        assert "mdt_metastasis_directed_therapy_planned" in names


class TestSpecialPopulationsCluster:
    def test_geriatric_tracks_g8_and_falls(self):
        s = INLINE_STAGE_SCHEMAS["geriatric_frail_limited"]()
        names = {f["name"] for f in s["fields"]}
        assert "g8_score_current" in names
        assert "falls_last_6mo" in names

    def test_young_onset_requires_fertility_discussion(self):
        s = INLINE_STAGE_SCHEMAS["young_onset_pca"]()
        names = {f["name"] for f in s["fields"]}
        assert "fertility_preservation_discussed" in names

    def test_cv_comorbidity_tracks_ef(self):
        s = INLINE_STAGE_SCHEMAS["comorbidity_limited_severe_cv"]()
        names = {f["name"] for f in s["fields"]}
        assert "ejection_fraction_baseline" in names
        assert "arpi_choice_cv_safe" in names

    def test_hepatic_comorbidity_tracks_child_pugh(self):
        s = INLINE_STAGE_SCHEMAS["comorbidity_limited_severe_hepatic"]()
        names = {f["name"] for f in s["fields"]}
        assert "child_pugh_class" in names
        assert "arpi_choice_hepatic_safe" in names


class TestSurvivorshipCluster:
    def test_adt_long_term_tracks_metabolic_screen(self):
        s = INLINE_STAGE_SCHEMAS["adt_long_term_complications"]()
        names = {f["name"] for f in s["fields"]}
        assert "adt_total_duration_years" in names
        assert "metabolic_syndrome_screening" in names

    def test_second_primary_tracks_risk_type(self):
        s = INLINE_STAGE_SCHEMAS["second_primary_surveillance"]()
        names = {f["name"] for f in s["fields"]}
        assert "primary_risk_secondary_malignancy" in names


class TestPostRtBcr:
    def test_post_rt_bcr_requires_psma_pet(self):
        s = INLINE_STAGE_SCHEMAS["post_rt_bcr"]()
        names = {f["name"] for f in s["fields"]}
        assert "psma_pet_post_rt_bcr" in names
        assert "salvage_modality_planned" in names


# ─────────────────── Dispatcher integration ───────────────────


class TestDispatcherIntegration:
    """stage_specific_intake_schema dispatch correctamente entre inline +
    module-based registry sin romper shape v2."""

    @pytest.mark.parametrize("state", sorted(INLINE_STAGE_SCHEMAS.keys()))
    def test_inline_state_returns_v2_shape(self, state):
        r = stage_specific_intake_schema(state)
        # Verify v2 shape contract
        for key in ("module", "title", "fields", "field_groups",
                     "by_role", "total_fields", "required_count",
                     "conditional_logic_count"):
            assert key in r, f"Missing v2 key {key} for state {state}"

    @pytest.mark.parametrize("state", sorted(_STAGE_SCHEMA_REGISTRY.keys()))
    def test_module_registry_state_still_works(self, state):
        """Regression: module-based registry sigue funcionando post-EPIC43."""
        r = stage_specific_intake_schema(state)
        assert r["total_fields"] > 0


# ─────────────────── Total field count ───────────────────


class TestTotalFieldCoverage:
    def test_total_field_count_at_least_700(self):
        """Suma de todos los fields de los 42 inline schemas ≥ 700.
        Pre-EPIC43: 41 estados × ~15 fields (diagnostic_workup fallback) = 615
        wrong-context fields. Post: ~782 right-context fields."""
        total = sum(
            len(builder()["fields"])
            for builder in INLINE_STAGE_SCHEMAS.values()
        )
        assert total >= 700, f"Got {total} total fields across 42 schemas"


# ─────────────────── EPIC 43.4 — Smart Capture UX ───────────────────


class TestSmartCaptureUX:
    """Verifica que la nueva surface Smart Capture (single-page dynamic) renderiza
    correctamente y reusa todos los 104 fields del quick_classify_schema sin
    eliminar ninguno."""

    @pytest.fixture(scope="class")
    def client(self):
        from app import app, create_app
        create_app()
        return app.test_client()

    def test_smart_capture_route_returns_200(self, client):
        r = client.get("/intake/smart")
        assert r.status_code == 200

    def test_smart_defaults_endpoint(self, client):
        r = client.get("/api/intake/smart-defaults")
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert isinstance(b["defaults"], dict)
        # Critical NCCN-derived defaults present
        assert b["defaults"]["ecog_score"] == "0"
        assert b["defaults"]["family_history_cancer"] == "Desconocido"
        assert b["defaults"]["charlson_comorbidity_index"] == 0
        assert b["defaults"]["psma_pet_done"] == "unknown"
        assert b["source"] == "nccn_eau_2026_conservative"

    def test_smart_capture_renders_all_104_fields(self, client):
        """Regression gate: TODOS los 104 fields del schema deben renderizar
        (NO eliminamos ninguno — directiva usuario)."""
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        from prostanet.presentation.v2_adapters import quick_classify_schema
        schema = quick_classify_schema()
        missing_fields = []
        for f in schema["fields"]:
            token = f'data-isc-field="{f["name"]}"'
            if token not in html:
                missing_fields.append(f["name"])
        assert not missing_fields, (
            f"Smart Capture DROPPED {len(missing_fields)} fields del schema: "
            f"{missing_fields[:10]}{'...' if len(missing_fields) > 10 else ''}"
        )

    def test_smart_capture_static_assets_load(self, client):
        css = client.get("/static/css/intake_smart_capture.css")
        js = client.get("/static/js/intake_smart_capture.js")
        assert css.status_code == 200
        assert js.status_code == 200
        assert len(css.get_data()) > 5000
        assert len(js.get_data()) > 10000

    def test_smart_capture_includes_voice_composite_mic(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "iscVoiceCompositeMic" in html
        assert "Dictar caso" in html

    def test_smart_capture_includes_cmdk_overlay(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "iscCmdkOverlay" in html
        assert "iscCmdkInput" in html
        assert "Buscar campo" in html

    def test_smart_capture_includes_section_navigator(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        # At least 15 nav items (matches our 22 groups)
        nav_count = html.count("isc-nav-item")
        assert nav_count >= 15

    def test_smart_capture_includes_progress_bar(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "iscProgressBar" in html
        assert "iscProgressLabel" in html

    def test_smart_capture_includes_submit_and_draft_buttons(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "iscSubmitBtn" in html
        assert "iscSaveDraftBtn" in html
        assert "iscClearDraftBtn" in html

    def test_smart_capture_includes_keyboard_hints(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "isc-keyboard-hints" in html
        assert "⌘" in html or "Ctrl" in html

    def test_smart_capture_sections_match_schema_groups(self, client):
        """Cada grupo del schema = 1 sección renderizada."""
        from prostanet.presentation.v2_adapters import quick_classify_schema
        schema = quick_classify_schema()
        unique_groups = {f.get("group", "Otros") for f in schema["fields"]}
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        # Each group should generate a data-isc-section attr
        section_count = html.count("data-isc-section=")
        # ≥ unique groups (may have synthetic anchors)
        assert section_count >= len(unique_groups), (
            f"Only {section_count} sections rendered, expected ≥ {len(unique_groups)}"
        )

    def test_smart_capture_preserves_conditional_visibility(self, client):
        """Fields with conditional_visibility must carry data-cv attr."""
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert "data-cv=" in html
        # Should have many CV fields (Step 1 schema has ~50 con CV)
        cv_count = html.count("data-cv=")
        assert cv_count >= 30, f"Only {cv_count} conditional_visibility fields preserved"

    def test_smart_capture_preserves_help_text(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        # Help tooltip toggle
        assert "isc-field-help-toggle" in html
        # Should have many help texts (most clinically nuanced fields have them)
        help_count = html.count("isc-field-help-toggle")
        assert help_count >= 30

    def test_smart_capture_required_fields_marked(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        # Required asterisk marker present
        assert "isc-field-required" in html
        # data-isc-required attribute on inputs
        assert 'data-isc-required="1"' in html


class TestSmartCaptureA11y:
    """Accessibility gates: WCAG AA contrast (visual review needed) + ARIA
    labels + keyboard navigation hooks."""

    @pytest.fixture(scope="class")
    def client(self):
        from app import app, create_app
        create_app()
        return app.test_client()

    def test_role_attributes_present(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert 'role="dialog"' in html  # cmdk
        assert 'role="progressbar"' in html  # progress

    def test_aria_labels_present(self, client):
        r = client.get("/intake/smart")
        html = r.get_data(as_text=True)
        assert 'aria-label="Navegador de secciones"' in html
        assert 'aria-live="polite"' in html  # toast host
        assert 'aria-expanded' in html  # collapsible sections

    def test_skip_focus_management_in_css(self):
        """CSS contains focus-visible rules and reduced-motion fallback."""
        from pathlib import Path
        css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "intake_smart_capture.css"
        css = css_path.read_text()
        assert "focus-visible" in css
        assert "prefers-reduced-motion" in css
