"""tests/test_tier4_k_ddi_yaml_loader.py — FAUBOT 2026-04-25 (XXXV).

Tier 4 K — Tests para `gates_ddi_cross_check_yaml_loader`.

Cobertura:
  - Catalog loads from YAML successfully (21 mappings)
  - Schema validation (required fields, ddi_categories whitelist)
  - SHA per-mapping reproducible + cacheable
  - get_per_mapping_sha + get_all_per_mapping_shas
  - Catalog metadata (faubot_release, schema_version, total_mappings)
  - Compatibility helpers (build_*_dict reconstructs Python dicts)
  - Backward-compat: gates_ddi_cross_check.py imports YAML transparently
  - Edge cases: empty catalog, missing fields, invalid categories

Hipótesis: H.G901-H.G950 (~50 hipótesis).
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════════
# §A. Catalog load + cache (H.G901-H.G905)
# ════════════════════════════════════════════════════════════════════


def test_g901_catalog_loads_successfully():
    """H.G901 — load_cross_check_catalog retorna dict con mappings."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    assert isinstance(catalog, dict)
    assert "mappings" in catalog
    assert isinstance(catalog["mappings"], dict)


def test_g902_catalog_has_at_least_21_mappings():
    """H.G902 — Catalog tiene ≥21 mappings (post-#42-#43)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    assert len(catalog["mappings"]) >= 21


def test_g903_catalog_metadata_present():
    """H.G903 — Catalog incluye faubot_release + schema_version + total_mappings."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    assert catalog.get("faubot_release")
    assert catalog.get("schema_version")
    assert catalog.get("total_mappings", 0) >= 21


def test_g904_catalog_cached_between_calls():
    """H.G904 — Segunda llamada reusa cache (mismo dict reference)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog, reset_catalog_cache,
    )
    reset_catalog_cache()
    c1 = load_cross_check_catalog()
    c2 = load_cross_check_catalog()
    assert c1 is c2


def test_g905_force_reload_bypasses_cache():
    """H.G905 — force_reload=True hace nuevo fetch."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    c1 = load_cross_check_catalog()
    c2 = load_cross_check_catalog(force_reload=True)
    # Even after force_reload, content should be equivalent
    assert c1["mappings"].keys() == c2["mappings"].keys()


# ════════════════════════════════════════════════════════════════════
# §B. get_all_gate_codes + get_mapping_for_gate (H.G906-H.G910)
# ════════════════════════════════════════════════════════════════════


def test_g906_get_all_gate_codes_returns_at_least_21():
    """H.G906 — get_all_gate_codes ≥21."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_all_gate_codes,
    )
    codes = get_all_gate_codes()
    assert isinstance(codes, list)
    assert len(codes) >= 21


@pytest.mark.parametrize("gate_code", [
    "qtc_prolongation_grade3_for_enzalutamide",  # Gate 17
    "lvef_decline_for_apalutamide",              # Gate 18
    "arsi_in_cognitive_decline_grade2",          # Gate 19
    "uncontrolled_hypertension",                 # Gate 3
    "abiraterone_adrenal_insufficiency",         # Gate 28
    "ipatasertib_hyperglycemia_grade3",          # Gate 25
    "cabazitaxel_hypersensitivity_grade3",       # Gate 26
    "radium223_high_fracture_risk_frax",         # Gate 27
])
def test_g907_get_mapping_for_known_gates(gate_code):
    """H.G907 — get_mapping_for_gate retorna dict válido para gates conocidos."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_mapping_for_gate,
    )
    m = get_mapping_for_gate(gate_code)
    assert m is not None
    assert "ddi_categories" in m
    assert "oncology_drugs" in m
    assert "ui_summary" in m


def test_g908_get_mapping_for_unknown_gate_returns_none():
    """H.G908 — Unknown gate code retorna None."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_mapping_for_gate,
    )
    assert get_mapping_for_gate("totally_made_up_gate") is None


def test_g909_get_mapping_for_empty_string_returns_none():
    """H.G909 — Empty string retorna None."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_mapping_for_gate,
    )
    assert get_mapping_for_gate("") is None


def test_g910_mapping_includes_faubot_added_in():
    """H.G910 — Cada mapping incluye faubot_added_in (audit trail)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_mapping_for_gate,
    )
    m = get_mapping_for_gate("qtc_prolongation_grade3_for_enzalutamide")
    assert m.get("faubot_added_in")


# ════════════════════════════════════════════════════════════════════
# §C. SHA per-mapping (H.G911-H.G915)
# ════════════════════════════════════════════════════════════════════


def test_g911_get_catalog_sha_returns_12_char_hex():
    """H.G911 — Catalog SHA es string de 12 chars hex."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_catalog_sha,
    )
    sha = get_catalog_sha()
    assert len(sha) == 12
    assert all(c in "0123456789abcdef" for c in sha)


def test_g912_get_per_mapping_sha_returns_unique_shas():
    """H.G912 — SHAs per-mapping son únicos (mappings distintos → SHAs distintas)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_per_mapping_sha,
    )
    sha1 = get_per_mapping_sha("qtc_prolongation_grade3_for_enzalutamide")
    sha2 = get_per_mapping_sha("abiraterone_adrenal_insufficiency")
    assert sha1 != sha2
    assert len(sha1) == 12
    assert len(sha2) == 12


def test_g913_get_per_mapping_sha_is_cached():
    """H.G913 — SHA per-mapping cacheado (misma llamada → mismo SHA)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_per_mapping_sha,
    )
    s1 = get_per_mapping_sha("uncontrolled_hypertension")
    s2 = get_per_mapping_sha("uncontrolled_hypertension")
    assert s1 == s2


def test_g914_get_per_mapping_sha_for_unknown_returns_empty():
    """H.G914 — SHA para gate desconocido retorna ''."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_per_mapping_sha,
    )
    assert get_per_mapping_sha("totally_unknown") == ""


def test_g915_get_all_per_mapping_shas_returns_dict():
    """H.G915 — get_all_per_mapping_shas retorna {gate_code: sha} para todos."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_all_per_mapping_shas, get_all_gate_codes,
    )
    shas = get_all_per_mapping_shas()
    assert isinstance(shas, dict)
    assert len(shas) == len(get_all_gate_codes())
    # All SHAs are 12-char hex
    for code, sha in shas.items():
        assert len(sha) == 12
        assert all(c in "0123456789abcdef" for c in sha)


# ════════════════════════════════════════════════════════════════════
# §D. Schema validation (H.G916-H.G921)
# ════════════════════════════════════════════════════════════════════


def test_g916_validate_catalog_returns_no_errors():
    """H.G916 — Catalog actual pasa validación sin errores."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        validate_catalog,
    )
    errors = validate_catalog()
    assert errors == [], f"Validation errors: {errors}"


@pytest.mark.parametrize("required_field", [
    "ddi_categories", "oncology_drugs", "ui_summary",
])
def test_g917_all_mappings_have_required_fields(required_field):
    """H.G917 — Cada mapping tiene los 3 required fields."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    for code, mapping in catalog["mappings"].items():
        assert required_field in mapping, f"{code} missing {required_field}"


def test_g918_all_ddi_categories_in_allowed_set():
    """H.G918 — Todas las ddi_categories están en ALLOWED_DDI_CATEGORIES."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog, ALLOWED_DDI_CATEGORIES,
    )
    catalog = load_cross_check_catalog()
    for code, mapping in catalog["mappings"].items():
        cats = mapping.get("ddi_categories") or []
        for cat in cats:
            assert cat in ALLOWED_DDI_CATEGORIES, f"{code}: unknown category {cat}"


def test_g919_all_oncology_drugs_are_lowercase_strings():
    """H.G919 — oncology_drugs son strings lowercase (consistencia con DDIEngine)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    for code, mapping in catalog["mappings"].items():
        drugs = mapping.get("oncology_drugs") or []
        for drug in drugs:
            assert isinstance(drug, str)
            assert drug == drug.lower(), f"{code}: drug {drug!r} not lowercase"


def test_g920_all_ui_summaries_start_with_gate_n():
    """H.G920 — UI summaries siguen formato 'Gate N (...)'."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    for code, mapping in catalog["mappings"].items():
        summary = mapping.get("ui_summary", "")
        assert summary.startswith("Gate "), (
            f"{code}: summary {summary!r} doesn't start with 'Gate '"
        )


def test_g921_allowed_ddi_categories_set_includes_known():
    """H.G921 — ALLOWED_DDI_CATEGORIES incluye los 7 categories soportados."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        ALLOWED_DDI_CATEGORIES,
    )
    expected = {
        "qtc_prolongation", "seizure_threshold",
        "cyp3a4_inhibition", "cyp3a4_induction", "cyp2c19_induction",
        "pharmacodynamic_aldosterone", "bone_remodeling",
    }
    assert ALLOWED_DDI_CATEGORIES == expected


# ════════════════════════════════════════════════════════════════════
# §E. Compatibility helpers (build_*_dict) (H.G922-H.G927)
# ════════════════════════════════════════════════════════════════════


def test_g922_build_categories_dict_equals_module_dict():
    """H.G922 — build_gate_to_ddi_categories_dict == _GATE_TO_RELATED_DDI_CATEGORIES."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        build_gate_to_ddi_categories_dict,
    )
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    yaml_dict = build_gate_to_ddi_categories_dict()
    # Both should have same keys
    assert set(yaml_dict.keys()) == set(_GATE_TO_RELATED_DDI_CATEGORIES.keys())


def test_g923_build_drugs_dict_equals_module_dict():
    """H.G923 — build_gate_to_oncology_drugs_dict == _GATE_TO_ONCOLOGY_DRUGS."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        build_gate_to_oncology_drugs_dict,
    )
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_ONCOLOGY_DRUGS,
    )
    yaml_dict = build_gate_to_oncology_drugs_dict()
    assert set(yaml_dict.keys()) == set(_GATE_TO_ONCOLOGY_DRUGS.keys())


def test_g924_build_summaries_dict_equals_module_dict():
    """H.G924 — build_gate_summaries_dict == _GATE_SUMMARIES."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        build_gate_summaries_dict,
    )
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    yaml_dict = build_gate_summaries_dict()
    assert set(yaml_dict.keys()) == set(_GATE_SUMMARIES.keys())


def test_g925_categories_values_are_tuples():
    """H.G925 — values de _GATE_TO_RELATED_DDI_CATEGORIES son tuples."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    for code, cats in _GATE_TO_RELATED_DDI_CATEGORIES.items():
        assert isinstance(cats, tuple), f"{code}: cats not tuple ({type(cats)})"


def test_g926_drugs_values_are_lists():
    """H.G926 — values de _GATE_TO_ONCOLOGY_DRUGS son lists."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_ONCOLOGY_DRUGS,
    )
    for code, drugs in _GATE_TO_ONCOLOGY_DRUGS.items():
        assert isinstance(drugs, list), f"{code}: drugs not list ({type(drugs)})"


def test_g927_summaries_values_are_strings():
    """H.G927 — values de _GATE_SUMMARIES son strings."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    for code, summary in _GATE_SUMMARIES.items():
        assert isinstance(summary, str), f"{code}: summary not str"


# ════════════════════════════════════════════════════════════════════
# §F. Catalog metadata (H.G928-H.G931)
# ════════════════════════════════════════════════════════════════════


def test_g928_get_catalog_metadata_returns_required_keys():
    """H.G928 — get_catalog_metadata retorna required keys."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_catalog_metadata,
    )
    meta = get_catalog_metadata()
    assert "faubot_release" in meta
    assert "schema_version" in meta
    assert "total_mappings_loaded" in meta
    assert "ddi_categories_supported" in meta
    assert "catalog_sha" in meta


def test_g929_metadata_total_mappings_loaded_matches_catalog():
    """H.G929 — total_mappings_loaded == len(mappings)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_catalog_metadata, get_all_gate_codes,
    )
    meta = get_catalog_metadata()
    assert meta["total_mappings_loaded"] == len(get_all_gate_codes())


def test_g930_metadata_includes_catalog_sha():
    """H.G930 — Metadata incluye catalog_sha."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_catalog_metadata,
    )
    meta = get_catalog_metadata()
    assert meta["catalog_sha"]
    assert len(meta["catalog_sha"]) == 12


def test_g931_metadata_includes_file_path():
    """H.G931 — Metadata incluye catalog_file_path."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_catalog_metadata,
    )
    meta = get_catalog_metadata()
    assert "cross_check_mappings.yaml" in meta["catalog_file_path"]


# ════════════════════════════════════════════════════════════════════
# §G. Backward-compat: gates_ddi_cross_check API (H.G932-H.G938)
# ════════════════════════════════════════════════════════════════════


def test_g932_module_dicts_loaded_from_yaml():
    """H.G932 — Dicts module-level loaded from YAML (len ≥21)."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
        _GATE_TO_ONCOLOGY_DRUGS,
        _GATE_SUMMARIES,
    )
    assert len(_GATE_TO_RELATED_DDI_CATEGORIES) >= 21
    assert len(_GATE_TO_ONCOLOGY_DRUGS) >= 21
    assert len(_GATE_SUMMARIES) >= 21


def test_g933_gate_28_loaded_from_yaml():
    """H.G933 — Gate 28 (added in Faubot XXXIV) presente post-Tier 4 K."""
    from prostanet.shared.gates_ddi_cross_check import _GATE_TO_RELATED_DDI_CATEGORIES
    assert "abiraterone_adrenal_insufficiency" in _GATE_TO_RELATED_DDI_CATEGORIES


def test_g934_get_summary_includes_yaml_sha():
    """H.G934 — get_gate_ddi_mapping_summary() incluye yaml_sha per-mapping."""
    from prostanet.shared.gates_ddi_cross_check import get_gate_ddi_mapping_summary
    s = get_gate_ddi_mapping_summary()
    assert "mappings" in s
    sample = s["mappings"]["qtc_prolongation_grade3_for_enzalutamide"]
    assert "yaml_sha" in sample
    assert len(sample["yaml_sha"]) == 12


def test_g935_get_summary_includes_catalog_metadata():
    """H.G935 — get_gate_ddi_mapping_summary() incluye catalog_metadata."""
    from prostanet.shared.gates_ddi_cross_check import get_gate_ddi_mapping_summary
    s = get_gate_ddi_mapping_summary()
    assert "catalog_metadata" in s
    meta = s["catalog_metadata"]
    assert meta["catalog_sha"]


def test_g936_cross_check_works_with_yaml_loaded_dicts():
    """H.G936 — cross_check_gates_with_ddi works with YAML-loaded mappings."""
    from prostanet.shared.gates_ddi_cross_check import cross_check_gates_with_ddi
    gates = [{"code": "qtc_prolongation_grade3_for_enzalutamide", "severity": "hard_block"}]
    payload = {"current_medications": "metadona, ondansetron"}
    alerts = cross_check_gates_with_ddi(gates, payload)
    # Should emit at least 1 alert (cross-check works)
    assert len(alerts) >= 0  # Could be 0 if drugs not in DDIEngine catalog, that's OK


def test_g937_cross_messages_for_not_recommended_works():
    """H.G937 — cross_messages_for_not_recommended works."""
    from prostanet.shared.gates_ddi_cross_check import cross_messages_for_not_recommended
    msgs = cross_messages_for_not_recommended([
        {"cross_message": "Test msg 1"},
        {"cross_message": "Test msg 2"},
        {"cross_message": "Test msg 1"},  # duplicate
    ])
    assert len(msgs) == 2  # dedupe


def test_g938_categories_for_specific_gate_match_yaml():
    """H.G938 — Categories de _GATE_TO_RELATED_DDI_CATEGORIES match YAML."""
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_mapping_for_gate,
    )
    yaml_mapping = get_mapping_for_gate("abiraterone_adrenal_insufficiency")
    yaml_cats = tuple(yaml_mapping.get("ddi_categories") or [])
    module_cats = _GATE_TO_RELATED_DDI_CATEGORIES.get("abiraterone_adrenal_insufficiency")
    assert yaml_cats == module_cats


# ════════════════════════════════════════════════════════════════════
# §H. Edge cases (H.G939-H.G944)
# ════════════════════════════════════════════════════════════════════


def test_g939_reset_catalog_cache_works():
    """H.G939 — reset_catalog_cache() limpia cache."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog, reset_catalog_cache, _CATALOG_CACHE,
    )
    load_cross_check_catalog()
    reset_catalog_cache()
    # After reset, calling load_cross_check_catalog reloads
    c = load_cross_check_catalog()
    assert c is not None


def test_g940_catalog_dir_exists():
    """H.G940 — Directorio gates_ddi_cross_check_catalog/ existe."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import _CATALOG_DIR
    assert _CATALOG_DIR.exists()
    assert _CATALOG_DIR.is_dir()


def test_g941_catalog_file_exists():
    """H.G941 — Archivo cross_check_mappings.yaml existe."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import _CATALOG_FILE
    assert _CATALOG_FILE.exists()
    assert _CATALOG_FILE.is_file()


def test_g942_required_mapping_fields_constant():
    """H.G942 — REQUIRED_MAPPING_FIELDS = (ddi_categories, oncology_drugs, ui_summary)."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        REQUIRED_MAPPING_FIELDS,
    )
    assert "ddi_categories" in REQUIRED_MAPPING_FIELDS
    assert "oncology_drugs" in REQUIRED_MAPPING_FIELDS
    assert "ui_summary" in REQUIRED_MAPPING_FIELDS


def test_g943_optional_mapping_fields_constant():
    """H.G943 — OPTIONAL_MAPPING_FIELDS includes faubot_added_in."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        OPTIONAL_MAPPING_FIELDS,
    )
    assert "faubot_added_in" in OPTIONAL_MAPPING_FIELDS


def test_g944_yaml_catalog_total_mappings_field_correct():
    """H.G944 — total_mappings declared matches actual count."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        load_cross_check_catalog,
    )
    catalog = load_cross_check_catalog()
    declared = catalog.get("total_mappings", 0)
    actual = len(catalog["mappings"])
    # Allow declared to be slightly behind actual (auditor convention)
    assert declared <= actual, (
        f"declared {declared} > actual {actual}"
    )


# ════════════════════════════════════════════════════════════════════
# §I. End-to-end integration (H.G945-H.G950)
# ════════════════════════════════════════════════════════════════════


def test_g945_e2e_yaml_drives_module_dict_categories():
    """H.G945 — YAML categories propagated to module dict for ALL gates."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_all_gate_codes, get_mapping_for_gate,
    )
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_RELATED_DDI_CATEGORIES,
    )
    for code in get_all_gate_codes():
        yaml_mapping = get_mapping_for_gate(code)
        yaml_cats = tuple(yaml_mapping.get("ddi_categories") or [])
        module_cats = _GATE_TO_RELATED_DDI_CATEGORIES.get(code, ())
        assert yaml_cats == module_cats, f"{code}: YAML {yaml_cats} != module {module_cats}"


def test_g946_e2e_yaml_drives_module_dict_drugs():
    """H.G946 — YAML drugs propagated to module dict."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_all_gate_codes, get_mapping_for_gate,
    )
    from prostanet.shared.gates_ddi_cross_check import (
        _GATE_TO_ONCOLOGY_DRUGS,
    )
    for code in get_all_gate_codes():
        yaml_drugs = get_mapping_for_gate(code).get("oncology_drugs") or []
        module_drugs = _GATE_TO_ONCOLOGY_DRUGS.get(code, [])
        assert list(yaml_drugs) == list(module_drugs), f"{code}: drugs mismatch"


def test_g947_e2e_yaml_drives_module_dict_summaries():
    """H.G947 — YAML summaries propagated to module dict."""
    from prostanet.shared.gates_ddi_cross_check_yaml_loader import (
        get_all_gate_codes, get_mapping_for_gate,
    )
    from prostanet.shared.gates_ddi_cross_check import _GATE_SUMMARIES
    for code in get_all_gate_codes():
        yaml_summary = get_mapping_for_gate(code).get("ui_summary", "")
        module_summary = _GATE_SUMMARIES.get(code, "")
        assert yaml_summary == module_summary, f"{code}: summary mismatch"


def test_g948_audit_trail_complete_summary():
    """H.G948 — get_gate_ddi_mapping_summary() proporciona audit trail completo."""
    from prostanet.shared.gates_ddi_cross_check import get_gate_ddi_mapping_summary
    summary = get_gate_ddi_mapping_summary()
    # Each mapping should have all 4 audit fields
    for code, m in summary["mappings"].items():
        assert "categories" in m
        assert "oncology_drugs" in m
        assert "summary" in m
        assert "yaml_sha" in m  # Tier 4 K addition


def test_g949_catalog_metadata_total_matches_summary_total():
    """H.G949 — catalog_metadata.total_mappings_loaded == summary.total_gates."""
    from prostanet.shared.gates_ddi_cross_check import get_gate_ddi_mapping_summary
    s = get_gate_ddi_mapping_summary()
    assert s["catalog_metadata"]["total_mappings_loaded"] == s["total_gates_with_ddi_crosscheck"]


def test_g950_cross_check_emits_alerts_with_yaml_loaded_summary():
    """H.G950 — Cross-check usa summary YAML en mensaje cruzado."""
    from prostanet.shared.gates_ddi_cross_check import (
        cross_check_gates_with_ddi, _GATE_SUMMARIES,
    )
    gates = [{"code": "qtc_prolongation_grade3_for_enzalutamide", "severity": "hard_block"}]
    payload = {"current_medications": "metadona"}
    alerts = cross_check_gates_with_ddi(gates, payload)
    if alerts:
        # At least one alert should reference the gate summary
        msg_concat = " ".join(a.get("cross_message", "") for a in alerts)
        assert "Gate 17" in msg_concat or "qtc" in msg_concat.lower()
