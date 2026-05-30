"""Multi-stage capture guards before expanding clinical logic.

The platform must not seed example clinical facts as patient data, and systemic
gate families must stay behind stage-appropriate disclosure controls.
"""
from __future__ import annotations

import re


NOISE_FIELDS = {
    "rapid_anc_drop_for_docetaxel",
    "rapid_platelet_drop_for_niraparib",
    "bone_marrow_blasts_percent",
    "cumulative_docetaxel_dose_mg_m2",
    "severe_cytopenia_for_parp_inhibitor",
    "cytopenias_corrected_for_radioligand",
    "cytopenias_corrected_for_parp_inhibitor",
    "thrombocytopenia_grade3_for_niraparib",
    "hypertension_grade3_for_niraparib",
    "hypertension_controlled_for_niraparib",
    "mds_or_aml_documented_during_parpi",
    "mds_aml_remission_for_parpi",
    "cytopenia_duration_weeks",
}


def _field_names(schema: dict) -> set[str]:
    return {
        str(field.get("name"))
        for field in schema.get("fields", [])
        if isinstance(field, dict) and field.get("name")
    }


def _router_field_names(router: dict) -> set[str]:
    return {
        field.get("name")
        for group in router.get("group_order") or []
        for field in group.get("fields") or []
        if field.get("name")
    }


def test_all_stage_wizards_do_not_preload_example_clinical_facts(app_client):
    client, _db_path = app_client

    cases = {
        "localized_initial": [
            r'name="psa"[^>]*value="8\.5"',
            r'<option value="T2a" selected>',
            r'name="life_expectancy_years"[^>]*value="15"',
        ],
        "recurrence_bcr": [
            r'name="psa_current"[^>]*value="0\.35"',
            r'name="psa_nadir"[^>]*value="0\.02"',
            r'name="psadt_months"[^>]*value="8"',
            r'<option value="Convencional" selected>',
        ],
        "post_prostatectomy": [
            r'name="psa"[^>]*value="12"',
            r'name="psa_postop"[^>]*value="0\.03"',
            r'<option value="pT2" selected>',
        ],
        "post_radiotherapy_or_local_salvage": [
            r'name="prior_rt_dose"[^>]*value="78"',
            r'name="psa_current"[^>]*value="1\.1"',
            r'name="phoenix_delta"[^>]*value="0\.8"',
            r'<option value="EBRT_IMRT" selected>',
        ],
        "mcspc_high_volume_sync": [
            r'name="gleason_score"[^>]*value="8"',
            r'name="ecog_score"[^>]*value="1"',
            r'name="metastatic_disease_known"[^>]*value="0"',
            r'name="metastasis_site"[^>]*value="M0"',
        ],
        "mcspc_low_volume_sync_oligo": [
            r'name="gleason_score"[^>]*value="7"',
            r'name="ecog_score"[^>]*value="0"',
            r'<option value="Fit" selected>',
        ],
        "mcspc_oligo_metachronous": [
            r'name="gleason_score"[^>]*value="8"',
            r'name="ecog_score"[^>]*value="0"',
            r'<option value="Sí" selected>',
        ],
        "m0_crpc": [
            r'name="psadt_months"[^>]*value="7"',
            r'name="ecog_score"[^>]*value="1"',
            r'<option value="Pendiente" selected>',
        ],
        "m1_crpc": [
            r'<option value="Desconocido" selected>',
            r'<option value="Bone" selected>',
            r'<option value="0" selected>',
        ],
    }

    for module_id, forbidden_patterns in cases.items():
        response = client.get(f"/wizard/{module_id}")
        assert response.status_code == 200, module_id
        html = response.get_data(as_text=True)

        assert 'value="" selected>No documentado</option>' in html
        for pattern in forbidden_patterns:
            assert not re.search(pattern, html), f"{module_id} preloaded {pattern}"


def test_metastatic_widget_is_append_only_until_user_or_hub_prefill_touches_it(app_client):
    client, _db_path = app_client

    response = client.get("/wizard/mcspc_high_volume_sync")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert 'data-metastatic-widget="1"' in html
    assert "isMetastaticWidgetTouched" in html
    assert "clearMetastaticWidgetOutputs" in html
    assert "metastaticTouched" in html
    assert 'name="metastatic_disease_known" value=""' in html
    assert 'name="metastasis_site" value=""' in html
    assert 'name="metastasis_count" value=""' in html
    assert "if (metastaticWidget && !isMetastaticWidgetTouched(metastaticWidget))" in html


def test_mcspc_and_m0_default_wizard_defer_parp_rlt_taxane_noise():
    from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA
    from prostanet.domains.mcspc_high_volume.schemas import MCSPC_HIGH_VOLUME_SYNC_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    for module_id, schema in [
        ("mcspc_high_volume_sync", MCSPC_HIGH_VOLUME_SYNC_SCHEMA),
        ("m0_crpc", M0_CRPC_SCHEMA),
    ]:
        base_names = _field_names(filter_schema_for_wizard(schema, module_id))
        assert "qtc_baseline_ms" in base_names
        assert not (NOISE_FIELDS & base_names), module_id

        taxane_names = _field_names(
            filter_schema_for_wizard(schema, module_id, gate_families=["taxane_safety"])
        )
        assert {"rapid_anc_drop_for_docetaxel", "cumulative_docetaxel_dose_mg_m2"} <= taxane_names
        assert "rapid_platelet_drop_for_niraparib" not in taxane_names

        parp_names = _field_names(
            filter_schema_for_wizard(schema, module_id, gate_families=["parp_hrr"])
        )
        assert {
            "rapid_platelet_drop_for_niraparib",
            "bone_marrow_blasts_percent",
            "hypertension_grade3_for_niraparib",
            "cytopenias_corrected_for_parp_inhibitor",
        } <= parp_names
        assert "cytopenias_corrected_for_radioligand" not in parp_names
        assert "rapid_anc_drop_for_docetaxel" not in parp_names

        rlt_names = _field_names(
            filter_schema_for_wizard(schema, module_id, gate_families=["psma_rlt"])
        )
        assert "cytopenias_corrected_for_radioligand" in rlt_names
        assert "cytopenias_corrected_for_parp_inhibitor" not in rlt_names


def test_m1_crpc_default_stays_segmented_until_therapy_family_is_opened():
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    base_names = _field_names(filter_schema_for_wizard(M1_CRPC_SCHEMA, "m1_crpc"))
    assert not (NOISE_FIELDS & base_names)
    assert "hrr_status" in base_names

    taxane_names = _field_names(
        filter_schema_for_wizard(M1_CRPC_SCHEMA, "m1_crpc", gate_families=["taxane_safety"])
    )
    assert "rapid_anc_drop_for_docetaxel" in taxane_names
    assert "rapid_platelet_drop_for_niraparib" not in taxane_names

    parp_names = _field_names(
        filter_schema_for_wizard(M1_CRPC_SCHEMA, "m1_crpc", gate_families=["parp_hrr"])
    )
    assert "rapid_platelet_drop_for_niraparib" in parp_names
    assert "cytopenias_corrected_for_parp_inhibitor" in parp_names
    assert "cytopenias_corrected_for_radioligand" not in parp_names

    rlt_names = _field_names(
        filter_schema_for_wizard(M1_CRPC_SCHEMA, "m1_crpc", gate_families=["psma_rlt"])
    )
    assert "cytopenias_corrected_for_radioligand" in rlt_names
    assert "cytopenias_corrected_for_parp_inhibitor" not in rlt_names


def test_longitudinal_router_matches_stage_specific_followup_surface():
    from prostanet.presentation.clinical_field_router import build_clinical_field_router

    localized_names = _router_field_names(
        build_clinical_field_router("localized_initial", phase="longitudinal_followup")
    )
    assert "psa_value" in localized_names
    assert "testosterone_value" not in localized_names
    assert "ctcae_grade_max" not in localized_names

    bcr_names = _router_field_names(
        build_clinical_field_router("recurrence_bcr", phase="longitudinal_followup")
    )
    assert {"psa_value", "bcr_psa", "psma_pet_staging_recent"} <= bcr_names
    assert "testosterone_value" not in bcr_names
    assert "ctcae_grade_max" not in bcr_names

    mcspc_names = _router_field_names(
        build_clinical_field_router("mcspc_high_volume_sync", phase="longitudinal_followup")
    )
    assert {"psa_value", "testosterone_value", "ecog_score", "ctcae_grade_max"} <= mcspc_names
    assert "bcr_psa" not in mcspc_names

    m0_names = _router_field_names(
        build_clinical_field_router("m0_crpc", phase="longitudinal_followup")
    )
    assert {"psa_value", "testosterone_value", "ecog_score", "ctcae_grade_max"} <= m0_names

    m1_names = _router_field_names(
        build_clinical_field_router("m1_crpc", phase="longitudinal_followup")
    )
    assert {"psa_value", "testosterone_value", "ecog_score", "ctcae_grade_max"} <= m1_names
    assert "bcr_psa" not in m1_names
