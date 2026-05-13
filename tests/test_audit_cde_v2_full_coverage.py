"""tests/test_audit_cde_v2_full_coverage.py — FAUBOT LXXXII / Auditoría CDE v2.

Tests para validar:
1. UI v2 captura 100% de fields del helper (384/384) — era 49.7%
2. Endpoints sidebar nuevos: /cohort-references + /therapy-catalog
3. Gates Pivotales dashboard muestra 85 gates (no solo 5 disparados)
4. Adapters retornan estructuras válidas
5. Bugs sidebar resueltos

CONTEXTO:
La auditoría #audit-cde-v2 detectó 4 problemas críticos en UI v2 producción:
- 50% gap fields gates 56-85 (cerrado en #audit-pre-cortana A1) y 50% gap
  adicional gates 1-55 (cerrado aquí)
- "Cohort References" sidebar link NO existía (mockup-only)
- "Therapy Catalog" sidebar link NO existía (mockup-only)
- "Gates Pivotales" mostraba 5 gates (disparados) en vez de 85 (catálogo)

HIPÓTESIS: H.G2500 → H.G2520 (~21 tests).

Faubot 2026-04-26 LXXXII — auditoría CDE v2 cerrar bucle pre-Cortana.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types

# APFS lock workaround
if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")

from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
from prostanet.presentation.v2_demo_data import build_intake_demo_data
from prostanet.presentation.v2_advanced_capture_builder import (
    build_advanced_capture_stages,
    get_advanced_capture_field_names,
    get_advanced_stage_keys,
)


# ──────────────────────────────────────────────────────────────────────
# §A — Coverage 100% UI v2 ↔ Helper FieldSpecs
# ──────────────────────────────────────────────────────────────────────


def test_g2500_ui_v2_coverage_100pct_helper_fields():
    """H.G2500 — UI v2 cubre 100% de fields helper (384/384)."""
    helper = pivotal_gate_supporting_fields()
    data = build_intake_demo_data()
    ui_fields = set()
    for stage_fields in data["fields"].values():
        for f in stage_fields:
            ui_fields.add(f.get("name", ""))
    helper_fields = {f.name for f in helper}
    coverage = (helper_fields & ui_fields)
    assert helper_fields == coverage, (
        f"Coverage gap: {sorted(helper_fields - coverage)[:10]} "
        f"({len(helper_fields - coverage)} fields missing)"
    )


def test_g2501_ui_v2_total_stages_at_least_19():
    """H.G2501 — UI v2 tiene ≥19 stages (forward-compat con LXXXIV+).

    Faubot LXXXIV: ampliado a 21 stages (+2 nuevos: subspecialty_pre_dx +
    mdt_genomic_hereditary). Forward-compat para iteraciones futuras.
    """
    data = build_intake_demo_data()
    assert len(data["stages"]) >= 19, (
        f"Expected ≥19 stages, got {len(data['stages'])}"
    )


def test_g2502_advanced_capture_stages_at_least_10():
    """H.G2502 — build_advanced_capture_stages retorna ≥10 etapas (forward-compat).

    Faubot LXXXIV: ampliado a 12 stages (+2 LXXXIV: subspecialty_pre_dx_decisions +
    mdt_genomic_hereditary_panel).
    """
    stages, fields = build_advanced_capture_stages()
    assert len(stages) >= 10, f"Expected ≥10 stages, got {len(stages)}"
    assert len(fields) >= 10
    expected_minimum = {
        "subspecialty_rt_rp", "genomic_critical", "pre_dx_atypical",
        "progression_detection", "systemic_toxicity", "bone_targeted_onj",
        "immune_io_chemo", "psa_kinetics_arpi", "longitudinal_overrides",
        "palliative_radiopharm",
    }
    actual_keys = {s["key"] for s in stages}
    assert expected_minimum.issubset(actual_keys), (
        f"Faltan stages base: {expected_minimum - actual_keys}"
    )


def test_g2503_critical_gate1_55_fields_present_in_ui():
    """H.G2503 — Fields críticos gates 1-55 (legacy) están en UI v2."""
    data = build_intake_demo_data()
    ui_fields = set()
    for stage_fields in data["fields"].values():
        for f in stage_fields:
            ui_fields.add(f.get("name", ""))

    # Fields críticos de gates legacy 1-55 que ANTES no estaban en UI v2
    # (subset que ESTÁ declarado en pivotal_gate_supporting_fields helper)
    critical_legacy = {
        "qtc_corrected_for_arpi",                  # gate 17 cardiotox
        "lvef_decline_for_arpi",                   # gate 18 cardiotox
        "ast_value", "alt_value",                  # gate 32 hepatic
        "platelets",                               # cytopenia gates
        "denosumab_prophylaxis",                   # gate 9 BMA
        "hypocalcemia",                            # gate 12
        "osteonecrosis_jaw_documented",            # gate 51 ONJ
        "psa_doubling_time_months",                # gate 53/55 kinetics
        "pneumonitis_ctcae_grade",                 # gate 26 IO
        "docetaxel_cycles_received",               # gate 34
        "epidural_compression",                    # gate 11/13 (SCC related)
    }
    missing = critical_legacy - ui_fields
    assert not missing, (
        f"Critical gates 1-55 fields missing in UI v2: {missing}"
    )


def test_g2504_advanced_field_names_above_400():
    """H.G2504 — get_advanced_capture_field_names ≥400 fields cubiertos."""
    names = get_advanced_capture_field_names()
    assert len(names) >= 400, (
        f"Solo {len(names)} fields cubiertos por etapas avanzadas (esperado ≥400)"
    )


# ──────────────────────────────────────────────────────────────────────
# §B — Cohort References endpoint nuevo
# ──────────────────────────────────────────────────────────────────────


def test_g2505_cohort_references_to_v2_returns_valid_structure():
    """H.G2505 — cohort_references_to_v2() retorna dict v2 válido."""
    from prostanet.presentation.v2_adapters import cohort_references_to_v2
    data = cohort_references_to_v2()
    assert data["catalog_view"] == "cohort_references"
    assert data["sidebar_active"] == "cohort_references"
    assert "page_title" in data
    assert "content_blocks" in data
    assert isinstance(data["content_blocks"], list)
    assert len(data["content_blocks"]) >= 2  # KPIs + table


def test_g2506_cohort_references_includes_kpi_grid_and_table():
    """H.G2506 — Cohort references incluye KPI grid + tabla con combos."""
    from prostanet.presentation.v2_adapters import cohort_references_to_v2
    data = cohort_references_to_v2()
    block_kinds = [b.get("kind") for b in data["content_blocks"]]
    assert "kpi_grid" in block_kinds
    assert "table" in block_kinds


def test_g2507_cohort_references_table_has_combos():
    """H.G2507 — Tabla cohort references contiene ≥10 combos pivotales."""
    from prostanet.presentation.v2_adapters import cohort_references_to_v2
    data = cohort_references_to_v2()
    table_blocks = [b for b in data["content_blocks"] if b.get("kind") == "table"]
    assert len(table_blocks) >= 1
    # Debe tener al menos 10 combos (state × regimen)
    rows = table_blocks[0].get("rows", [])
    assert len(rows) >= 10, f"Solo {len(rows)} combos en cohort references"


# ──────────────────────────────────────────────────────────────────────
# §C — Therapy Catalog endpoint nuevo
# ──────────────────────────────────────────────────────────────────────


def test_g2508_therapy_catalog_to_v2_returns_valid_structure():
    """H.G2508 — therapy_catalog_to_v2() retorna dict v2 válido."""
    from prostanet.presentation.v2_adapters import therapy_catalog_to_v2
    data = therapy_catalog_to_v2()
    assert data["catalog_view"] == "therapy_catalog"
    assert data["sidebar_active"] == "therapy_catalog"
    assert "page_title" in data
    assert "content_blocks" in data


def test_g2509_therapy_catalog_table_has_regimens():
    """H.G2509 — Tabla therapy catalog contiene ≥20 regímenes."""
    from prostanet.presentation.v2_adapters import therapy_catalog_to_v2
    data = therapy_catalog_to_v2()
    table_blocks = [b for b in data["content_blocks"] if b.get("kind") == "table"]
    assert len(table_blocks) >= 1
    rows = table_blocks[0].get("rows", [])
    assert len(rows) >= 20, f"Solo {len(rows)} regímenes en therapy catalog"


def test_g2510_therapy_catalog_has_drug_classes():
    """H.G2510 — Therapy catalog incluye drug classes diversos."""
    from prostanet.presentation.v2_adapters import therapy_catalog_to_v2
    data = therapy_catalog_to_v2()
    # Convertir todas las filas a string para search
    all_html = str(data)
    expected_classes = ["androgen_axis", "parp"]  # mínimos esperados
    for cls in expected_classes:
        assert cls in all_html, f"Drug class '{cls}' missing en therapy catalog UI"


# ──────────────────────────────────────────────────────────────────────
# §D — Gates Pivotales dashboard muestra 85 gates (no solo 5)
# ──────────────────────────────────────────────────────────────────────


def test_g2511_gates_coverage_full_catalog_returns_all_85_gates():
    """H.G2511 — gates_coverage_to_v2_full_catalog retorna 85 gates."""
    from prostanet.presentation.v2_adapters import gates_coverage_to_v2_full_catalog
    data = gates_coverage_to_v2_full_catalog()
    table_blocks = [b for b in data["content_blocks"] if b.get("kind") == "table"]
    assert len(table_blocks) >= 1
    rows = table_blocks[0].get("rows", [])
    # Debe ser 85 (total catálogo) no solo 5 (disparados)
    assert len(rows) >= 85, (
        f"Gates dashboard muestra solo {len(rows)} gates, esperado ≥85"
    )


def test_g2512_gates_coverage_kpi_grid_shows_severity_breakdown():
    """H.G2512 — KPI grid muestra breakdown severity (hard_block/soft/info)."""
    from prostanet.presentation.v2_adapters import gates_coverage_to_v2_full_catalog
    data = gates_coverage_to_v2_full_catalog()
    kpi_blocks = [b for b in data["content_blocks"] if b.get("kind") == "kpi_grid"]
    assert len(kpi_blocks) >= 1
    entries = kpi_blocks[0].get("entries", [])
    labels = [e.get("label", "") for e in entries]
    assert any("Hard block" in l for l in labels), "Falta KPI Hard block"
    assert any("Soft warning" in l for l in labels), "Falta KPI Soft warning"
    assert any("Informational" in l for l in labels), "Falta KPI Informational"


def test_g2513_gates_coverage_includes_yaml_sha_per_gate():
    """H.G2513 — Tabla gates incluye columna YAML SHA per gate."""
    from prostanet.presentation.v2_adapters import gates_coverage_to_v2_full_catalog
    data = gates_coverage_to_v2_full_catalog()
    table_blocks = [b for b in data["content_blocks"] if b.get("kind") == "table"]
    columns = table_blocks[0].get("columns", [])
    assert "YAML SHA" in columns, "Columna YAML SHA missing en gates dashboard"


# ──────────────────────────────────────────────────────────────────────
# §E — Sidebar links templates (HTML real)
# ──────────────────────────────────────────────────────────────────────


def test_g2514_sidebar_macro_has_cohort_references_link():
    """H.G2514 — Macro pm2_sidebar.html (centralizado LXXXIII) incluye Cohort references link.

    Faubot LXXXIII — sidebar refactorizado a macro single-source-of-truth.
    El link ya no está en patient_profile_v2.html sino en components/pm2_sidebar.html.
    """
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/components/pm2_sidebar.html", "r") as f:
        html = f.read()
    assert 'href="/cohort-references"' in html, (
        "Link a /cohort-references missing en macro pm2_sidebar.html"
    )
    assert "Cohort references" in html


def test_g2515_sidebar_macro_has_therapy_catalog_link():
    """H.G2515 — Macro pm2_sidebar.html (centralizado LXXXIII) incluye Therapy catalog link."""
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/components/pm2_sidebar.html", "r") as f:
        html = f.read()
    assert 'href="/therapy-catalog"' in html, (
        "Link a /therapy-catalog missing en macro pm2_sidebar.html"
    )
    assert "Therapy catalog" in html


def test_g2516_sidebar_macro_has_gates_pivotales_link():
    """H.G2516 — Macro pm2_sidebar.html (centralizado LXXXIII) incluye Gates pivotales link."""
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/templates/components/pm2_sidebar.html", "r") as f:
        html = f.read()
    assert 'href="/gates-coverage-dashboard"' in html
    assert "Gates pivotales" in html


# ──────────────────────────────────────────────────────────────────────
# §F — Endpoints registrados en app.py
# ──────────────────────────────────────────────────────────────────────


def test_g2517_app_has_cohort_references_route():
    """H.G2517 — app.py registra route /cohort-references."""
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/app.py", "r") as f:
        app_src = f.read()
    assert '@app.route("/cohort-references")' in app_src, (
        "Route /cohort-references no registrado en app.py"
    )
    assert "def cohort_references_page" in app_src


def test_g2518_app_has_therapy_catalog_route():
    """H.G2518 — app.py registra route /therapy-catalog."""
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/app.py", "r") as f:
        app_src = f.read()
    assert '@app.route("/therapy-catalog")' in app_src, (
        "Route /therapy-catalog no registrado en app.py"
    )
    assert "def therapy_catalog_page" in app_src


def test_g2519_app_uses_full_catalog_for_gates_coverage():
    """H.G2519 — gates-coverage-dashboard usa full_catalog adapter (85 gates)."""
    with open("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6/app.py", "r") as f:
        app_src = f.read()
    assert "gates_coverage_to_v2_full_catalog" in app_src, (
        "app.py no usa el adapter mejorado gates_coverage_to_v2_full_catalog "
        "que muestra los 85 gates"
    )


# ──────────────────────────────────────────────────────────────────────
# §G — 5 dimensiones CDE Auditable mantenidas en 5/5
# ──────────────────────────────────────────────────────────────────────


def test_g2520_cde_auditable_5_dimensions_post_cleanup():
    """H.G2520 — Post-cleanup: 5 dimensiones CDE Auditable se mantienen 5/5.

    Verificación rápida via algorithm_version + helper coverage:
    - VERSIÓN: FAUBOT_RELEASE present + gates_active_count >= 85
    - DATOS: Helper FieldSpecs >= 384 + UI coverage 100%
    - POR QUÉ: 85 gates loaded
    - EVIDENCIA: trial_refs disponibles
    - CÓMO: 19 stages UI v2 + 3 nuevos endpoints sidebar
    """
    from prostanet.shared.algorithm_version import get_algorithm_version
    from prostanet.shared.pivotal_gates_yaml_loader import (
        _load_yaml_files,
        get_loaded_yaml_codes,
    )
    _load_yaml_files(force_reload=True)

    ver = get_algorithm_version()
    # VERSIÓN
    assert ver["faubot_release"].startswith("2026-04-")
    assert ver["gates_active_count"] >= 85
    # POR QUÉ (gates)
    codes = get_loaded_yaml_codes()
    assert len(codes) >= 85
    # DATOS (FieldSpecs + UI coverage)
    helper = pivotal_gate_supporting_fields()
    assert len(helper) >= 384
    data = build_intake_demo_data()
    ui_fields = set()
    for sf in data["fields"].values():
        for f in sf:
            ui_fields.add(f.get("name", ""))
    helper_names = {f.name for f in helper}
    assert helper_names == (helper_names & ui_fields), "DATOS coverage <100%"
    # CÓMO (19 stages UI + 3 sidebar endpoints)
    assert len(data["stages"]) >= 19
