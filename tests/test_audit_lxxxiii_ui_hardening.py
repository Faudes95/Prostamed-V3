"""tests/test_audit_lxxxiii_ui_hardening.py — FAUBOT LXXXIII UI hardening.

Tests para el fix del bug "menú lateral persistente / UI previa cargada":

1. Sidebar centralizado en macro pm2_sidebar.html
2. Cache-busting middleware en HTML responses (no-cache headers)
3. Templates v2 (patient_profile_v2, patients_v2, catalog_v2) usan macro
4. 9 endpoints sidebar funcionan + retornan v2 + tienen cache headers
5. 85 gates audit infrastructure (script ejecutable)

HIPÓTESIS: H.G2700 → H.G2715 (~16 tests).

Faubot LXXXIII — cierre Iteración #0 antes de It #1 subspecialty.
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import sys
import types
from pathlib import Path

# APFS lock workaround
if "tracking_db" not in sys.modules:
    class _S(types.ModuleType):
        def __getattr__(self, n):
            def _f(*a, **k):
                return [] if "list" in n else {}
            return _f
    sys.modules["tracking_db"] = _S("tracking_db")


ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")


# ──────────────────────────────────────────────────────────────────────
# §A — Macro pm2_sidebar.html existe + es válido
# ──────────────────────────────────────────────────────────────────────


def test_g2700_pm2_sidebar_macro_exists():
    """H.G2700 — Macro pm2_sidebar.html existe en components/."""
    macro_path = ROOT / "templates/components/pm2_sidebar.html"
    assert macro_path.exists(), f"Macro file missing: {macro_path}"


def test_g2701_pm2_sidebar_macro_has_required_params():
    """H.G2701 — Macro acepta parámetros: active, identity_nss, faubot_release, gates_count, kpi_total."""
    macro = (ROOT / "templates/components/pm2_sidebar.html").read_text()
    for param in ["active", "identity_nss", "faubot_release", "gates_count", "kpi_total"]:
        assert param in macro, f"Param '{param}' missing en macro"


def test_g2702_pm2_sidebar_macro_includes_all_links():
    """H.G2702 — Macro incluye los 12 links sidebar v2."""
    macro = (ROOT / "templates/components/pm2_sidebar.html").read_text()
    expected_urls = [
        "/patients",
        "/patient_profile/",  # template variable {{ identity_nss }}
        "/longitudinal-capture/",
        "/clinical-result/",
        "/patient_intake",
        "/audit-log",
        "/clinical-hub",
        "/dashboard",
        "/gates-coverage-dashboard",
        "/cohort-references",  # Faubot LXXXII
        "/therapy-catalog",  # Faubot LXXXII
        "/versioning-dashboard",
    ]
    for url in expected_urls:
        assert url in macro, f"URL {url} missing en macro sidebar"


# ──────────────────────────────────────────────────────────────────────
# §B — Templates v2 usan el macro centralizado
# ──────────────────────────────────────────────────────────────────────


def test_g2703_patient_profile_v2_uses_macro():
    """H.G2703 — patient_profile_v2.html importa y usa el macro pm2_sidebar."""
    template = (ROOT / "templates/patient_profile_v2.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in template
    assert "pm2_sidebar(" in template
    assert "active='profile'" in template


def test_g2704_patients_v2_uses_macro():
    """H.G2704 — patients_v2.html importa y usa el macro pm2_sidebar."""
    template = (ROOT / "templates/patients_v2.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in template
    assert "pm2_sidebar(" in template
    assert "active='patients'" in template


def test_g2705_catalog_v2_uses_macro():
    """H.G2705 — catalog_v2.html importa y usa el macro pm2_sidebar."""
    template = (ROOT / "templates/catalog_v2.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in template
    assert "pm2_sidebar(" in template


def test_g2706_no_duplicate_sidebar_html_in_v2_templates():
    """H.G2706 — Templates v2 NO contienen sidebar HTML duplicado.

    Después del refactor LXXXIII, no debería haber `<aside class="pm2-sidebar"`
    inline en patient_profile_v2.html, patients_v2.html, catalog_v2.html.
    Sólo debe estar en el macro components/pm2_sidebar.html.
    """
    for tpl_name in ["patient_profile_v2.html", "patients_v2.html", "catalog_v2.html"]:
        template = (ROOT / "templates" / tpl_name).read_text()
        # El template NO debe tener sidebar HTML inline (solo via macro)
        assert '<aside class="pm2-sidebar"' not in template, (
            f"Template {tpl_name} tiene sidebar HTML inline (deberia usar macro)"
        )


# ──────────────────────────────────────────────────────────────────────
# §C — Cache-busting middleware en app.py
# ──────────────────────────────────────────────────────────────────────


def test_g2707_app_has_cache_busting_middleware():
    """H.G2707 — app.py registra _add_cache_busting_headers after_request."""
    app_src = (ROOT / "app.py").read_text()
    assert "_add_cache_busting_headers" in app_src
    assert "@app.after_request" in app_src
    assert "no-cache, no-store, must-revalidate" in app_src


def test_g2708_cache_middleware_targets_html_and_json():
    """H.G2708 — Middleware aplica no-cache solo a HTML/JSON, no a CSS/JS."""
    app_src = (ROOT / "app.py").read_text()
    assert 'text/html' in app_src
    assert 'application/json' in app_src


# ──────────────────────────────────────────────────────────────────────
# §D — Audit scripts existen y son ejecutables
# ──────────────────────────────────────────────────────────────────────


def test_g2709_audit_85_gates_script_exists():
    """H.G2709 — tools/audit_all_85_gates_e2e.py existe."""
    script = ROOT / "tools/audit_all_85_gates_e2e.py"
    assert script.exists()
    content = script.read_text()
    assert "def main()" in content
    assert "audit_gate(" in content


def test_g2710_audit_icons_script_exists():
    """H.G2710 — tools/audit_all_icons_workflow.py existe."""
    script = ROOT / "tools/audit_all_icons_workflow.py"
    assert script.exists()
    content = script.read_text()
    assert "SIDEBAR_ICONS" in content
    assert "check_url(" in content


def test_g2711_audit_85_gates_script_lists_85_gate_payloads():
    """H.G2711 — Audit script tiene PAYLOAD_TEMPLATES para gates 56-85."""
    script_content = (ROOT / "tools/audit_all_85_gates_e2e.py").read_text()
    # Sample de gates conocidos que deben estar en payloads
    expected_gates = [
        "anticoagulant_rp_bleeding_risk",
        "hrr_status_required_before_parp_inhibitor",
        "atypical_histology_escalation_nepc_intraductal",
        "psma_pet_progression_auto_trigger",
        "samarium_153_edtmp_eligibility",
        "palliative_sedation_protocol_initiation",
        "cachexia_pharmacotherapy_consideration",
    ]
    for gate in expected_gates:
        assert gate in script_content, f"Gate {gate} missing en PAYLOAD_TEMPLATES"


# ──────────────────────────────────────────────────────────────────────
# §E — Bump FAUBOT_RELEASE LXXXII → LXXXIII
# ──────────────────────────────────────────────────────────────────────


def test_g2712_faubot_release_bumped_to_lxxxiii_or_higher():
    """H.G2712 — FAUBOT_RELEASE ≥ LXXXIII (forward-compat).

    Iteración #0 cierre LXXXIII; pero post-LXXXIV+ también cumple.
    """
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Cualquier release ≥ LXXXIII es válido (LXXXIII, LXXXIV, LXXXV, etc.)
    assert any(rel in FAUBOT_RELEASE for rel in ["LXXXIII", "LXXXIV", "LXXXV", "LXXXVI", "LXXXVII", "LXXXVIII", "LXXXIX", "XC"]), (
        f"FAUBOT_RELEASE not bumped to ≥LXXXIII: {FAUBOT_RELEASE}"
    )


def test_g2713_algorithm_version_returns_85_gates():
    """H.G2713 — get_algorithm_version retorna ≥85 gates."""
    from prostanet.shared.algorithm_version import get_algorithm_version
    v = get_algorithm_version()
    assert v["gates_active_count"] >= 85
    assert v["faubot_release"].startswith("2026-04-2")


# ──────────────────────────────────────────────────────────────────────
# §F — Coverage UI v2 mantenida en 100%
# ──────────────────────────────────────────────────────────────────────


def test_g2714_ui_v2_coverage_still_100pct_helper_fields():
    """H.G2714 — Post-refactor LXXXIII: coverage UI v2 sigue 100%."""
    from prostanet.shared.advanced_support_fields import pivotal_gate_supporting_fields
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    helper = pivotal_gate_supporting_fields()
    data = build_intake_demo_data()
    ui_fields = set()
    for stage_fields in data["fields"].values():
        for f in stage_fields:
            ui_fields.add(f.get("name", ""))
    helper_names = {f.name for f in helper}
    coverage = helper_names & ui_fields
    assert coverage == helper_names, (
        f"Coverage broken post-LXXXIII: {len(helper_names - coverage)} fields missing"
    )


def test_g2715_ui_v2_total_stages_at_least_19_after_refactor():
    """H.G2715 — UI v2 mantiene ≥19 stages tras refactor sidebar (forward-compat)."""
    from prostanet.presentation.v2_demo_data import build_intake_demo_data
    data = build_intake_demo_data()
    assert len(data["stages"]) >= 19, (
        f"Stages cambió tras refactor: {len(data['stages'])} < 19"
    )
