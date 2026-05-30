from __future__ import annotations


LOCALIZED_SYSTEMIC_NOISE = {
    "rapid_anc_drop_for_docetaxel",
    "rapid_platelet_drop_for_niraparib",
    "bone_marrow_blasts_percent",
    "cumulative_docetaxel_dose_mg_m2",
}

LOCALIZED_SYSTEMIC_PIVOTAL_CONTRAINDICATIONS = {
    "prior_arpi_exposure_mhspc",
    "darolutamide_hypersensitivity",
    "uncontrolled_hypertension",
    "severe_heart_failure_nyha_iii_iv",
    "uncontrolled_diabetes",
    "no_bone_protective_agent",
    "radium223_candidate",
}


def _field_names(schema: dict) -> set[str]:
    return {
        str(field.get("name"))
        for field in schema.get("fields", [])
        if isinstance(field, dict)
    }


def _field_by_name(schema: dict, name: str) -> dict:
    return next(
        field
        for field in schema.get("fields", [])
        if isinstance(field, dict) and field.get("name") == name
    )


def test_localized_wizard_hides_systemic_pivotal_noise_by_default():
    from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    filtered = filter_schema_for_wizard(LOCALIZED_SCHEMA, "localized_initial")
    names = _field_names(filtered)

    assert "psa" in names
    assert "clinical_tstage" in names
    assert not (LOCALIZED_SYSTEMIC_NOISE & names)
    assert not any(
        field.get("group") == "Soportes adicionales de gates pivote"
        for field in filtered.get("fields", [])
        if isinstance(field, dict)
    )


def test_localized_systemic_trial_contraindications_require_explicit_disclosure():
    from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    filtered = filter_schema_for_wizard(LOCALIZED_SCHEMA, "localized_initial")
    names = _field_names(filtered)

    assert "show_systemic_pivotal_contraindications" in names
    assert LOCALIZED_SYSTEMIC_PIVOTAL_CONTRAINDICATIONS <= names
    for name in LOCALIZED_SYSTEMIC_PIVOTAL_CONTRAINDICATIONS:
        field = _field_by_name(filtered, name)
        assert field.get("group") == "Contraindicaciones de ensayos pivote"
        assert field.get("conditional_visibility") == {
            "show_systemic_pivotal_contraindications": ["1"]
        }


def test_taxane_family_opens_taxane_fields_without_parp_noise():
    from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    filtered = filter_schema_for_wizard(
        LOCALIZED_SCHEMA,
        "localized_initial",
        gate_families=["taxane_safety"],
    )
    names = _field_names(filtered)

    assert "rapid_anc_drop_for_docetaxel" in names
    assert "cumulative_docetaxel_dose_mg_m2" in names
    assert "rapid_platelet_drop_for_niraparib" not in names
    assert _field_by_name(filtered, "rapid_anc_drop_for_docetaxel")["group"] == "Gate pivote - taxano"


def test_m0_crpc_opens_arpi_safety_but_not_taxane_or_parp_by_default():
    from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    filtered = filter_schema_for_wizard(M0_CRPC_SCHEMA, "m0_crpc")
    names = _field_names(filtered)
    field_name_list = [field.get("name") for field in filtered.get("fields", [])]

    assert "qtc_baseline_ms" in names
    assert "lvef_baseline_percent" in names
    assert "planned_systemic_regimen" not in names
    assert "rapid_anc_drop_for_docetaxel" not in names
    assert "parp_inhibitor_consideration_active" not in names
    assert len(field_name_list) == len(set(field_name_list))


def test_mcspc_defaults_keep_arpi_but_defer_later_line_pivotal_families():
    from prostanet.domains.mcspc_high_volume.schemas import MCSPC_HIGH_VOLUME_SYNC_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    base = filter_schema_for_wizard(MCSPC_HIGH_VOLUME_SYNC_SCHEMA, "mcspc_high_volume_sync")
    base_names = _field_names(base)

    assert "qtc_baseline_ms" in base_names
    assert "rapid_anc_drop_for_docetaxel" not in base_names
    assert "cumulative_docetaxel_dose_mg_m2" not in base_names
    assert "considering_radium223" not in base_names
    assert "planned_systemic_regimen" not in base_names
    assert "rapid_platelet_drop_for_niraparib" not in base_names

    taxane = filter_schema_for_wizard(
        MCSPC_HIGH_VOLUME_SYNC_SCHEMA,
        "mcspc_high_volume_sync",
        gate_families=["taxane_safety"],
    )
    assert "rapid_anc_drop_for_docetaxel" in _field_names(taxane)
    assert "planned_systemic_regimen" not in _field_names(taxane)

    radium = filter_schema_for_wizard(
        MCSPC_HIGH_VOLUME_SYNC_SCHEMA,
        "mcspc_high_volume_sync",
        gate_families=["radium_bone"],
    )
    radium_names = _field_names(radium)
    assert "considering_radium223" in radium_names
    assert "planned_systemic_regimen" in radium_names


def test_m1_crpc_families_are_segmented_by_therapy_context():
    from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
    from prostanet.shared.pivotal_gate_disclosure import filter_schema_for_wizard

    base = filter_schema_for_wizard(M1_CRPC_SCHEMA, "m1_crpc")
    assert "rapid_anc_drop_for_docetaxel" not in _field_names(base)

    taxane = filter_schema_for_wizard(
        M1_CRPC_SCHEMA,
        "m1_crpc",
        gate_families=["taxane_safety"],
    )
    assert "rapid_anc_drop_for_docetaxel" in _field_names(taxane)
    assert "rapid_platelet_drop_for_niraparib" not in _field_names(taxane)

    parp = filter_schema_for_wizard(
        M1_CRPC_SCHEMA,
        "m1_crpc",
        gate_families=["parp_hrr"],
    )
    parp_names = _field_names(parp)
    assert "rapid_platelet_drop_for_niraparib" in parp_names
    assert "bone_marrow_blasts_percent" in parp_names


def test_schema_api_keeps_full_contract_and_exposes_wizard_surface(app_client):
    client, _ = app_client

    full = client.get("/api/modules/localized_initial/schema")
    assert full.status_code == 200
    full_names = _field_names(full.get_json()["schema"])
    assert "rapid_anc_drop_for_docetaxel" in full_names

    wizard = client.get("/api/modules/localized_initial/schema?surface=wizard")
    assert wizard.status_code == 200
    wizard_names = _field_names(wizard.get_json()["schema"])
    assert "rapid_anc_drop_for_docetaxel" not in wizard_names

    taxane = client.get(
        "/api/modules/localized_initial/schema?surface=wizard&gate_family=taxane_safety"
    )
    assert taxane.status_code == 200
    taxane_names = _field_names(taxane.get_json()["schema"])
    assert "rapid_anc_drop_for_docetaxel" in taxane_names
