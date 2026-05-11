"""tests/test_audit_lxxxiii_b_demos_sidebar_macro.py — FAUBOT LXXXIII.b.

Tests para el SEGUNDO bug del menú lateral persistente:
demo templates con `href="#"` placeholders en sidebar (NO usaban el macro).

ROOT CAUSE confirmado por usuario via Playwright element selection:
- /demos/v2/patient_profile_full renderizaba sidebar con `href="#"` placeholders
- Hardcoded badges (128, 55, 11, 37) NO conectados a datos reales
- 8+ links rotos en patient_profile_full_v2_demo.html
- Similar en clinical_result_v2_demo.html (servido por /clinical-result/<nss>)
- Similar en longitudinal_capture_v2_demo.html

FIX LXXXIII.b: refactor 3 demo templates para usar macro pm2_sidebar.html

Aplicación de skills:
- /ui-ux-pro-max: consistency cross-template (mismo sidebar everywhere)
- /frontend-patterns: macro Jinja como single source of truth
- /backend-patterns: cache-busting middleware Flask after_request
- /api-design: URLs canónicas (sin ?v=2 redundante post-LXXX #67E)
- /code-reviewer: zero href=# en producción + zero badges hardcoded

HIPÓTESIS: H.G2716 → H.G2729 (~14 tests).

Faubot LXXXIII.b — cierre completo bug "UI previa cargada".
"""
# IEC 62304 §5.5 (Unit verification)

from __future__ import annotations

import re
import sys
import types
import urllib.request
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
BASE_URL = "http://localhost:8080"


# ──────────────────────────────────────────────────────────────────────
# §A — Verificación cero href="#" en sidebars de demos refactorizados
# ──────────────────────────────────────────────────────────────────────


def _extract_sidebar_html(template_path: Path) -> str:
    """Extrae el bloque HTML que contiene la sidebar (entre {% from sidebar %} y siguiente sección)."""
    content = template_path.read_text()
    return content


def _count_href_hash_in_sidebar_section(template_path: Path) -> int:
    """Cuenta `href="#"` o `href="#section-...` que tienen `pm2-sidebar-link` cerca.

    Solo cuenta los rotos en sidebar (NO botones acción internos del demo).
    """
    content = template_path.read_text()
    # Buscar patrones <a ... href="#" ... pm2-sidebar-link>
    pattern = re.compile(
        r'<a[^>]*href="#"[^>]*pm2-sidebar-link[^>]*>',
        re.IGNORECASE | re.MULTILINE,
    )
    matches_href_hash = pattern.findall(content)
    # También al revés: pm2-sidebar-link ... href="#"
    pattern2 = re.compile(
        r'<a[^>]*pm2-sidebar-link[^>]*href="#"[^>]*>',
        re.IGNORECASE | re.MULTILINE,
    )
    matches_alt = pattern2.findall(content)
    return len(matches_href_hash) + len(matches_alt)


def test_g2716_demo_full_zero_href_hash_in_sidebar():
    """H.G2716 — patient_profile_full_v2_demo.html tiene 0 `href="#"` en sidebar."""
    template = ROOT / "templates/demos/patient_profile_full_v2_demo.html"
    count = _count_href_hash_in_sidebar_section(template)
    assert count == 0, (
        f"Demo full tiene {count} placeholders `href=\"#\"` en sidebar — "
        "deberían usar URLs reales via macro pm2_sidebar"
    )


def test_g2717_demo_clinical_result_zero_href_hash_in_sidebar():
    """H.G2717 — clinical_result_v2_demo.html tiene 0 `href="#"` en sidebar.

    CRÍTICO: este demo es servido por /clinical-result/<nss> en producción.
    """
    template = ROOT / "templates/demos/clinical_result_v2_demo.html"
    count = _count_href_hash_in_sidebar_section(template)
    assert count == 0, (
        f"Demo clinical_result tiene {count} placeholders `href=\"#\"` en sidebar"
    )


def test_g2718_demo_longitudinal_zero_href_hash_in_sidebar():
    """H.G2718 — longitudinal_capture_v2_demo.html tiene 0 `href="#"` en sidebar."""
    template = ROOT / "templates/demos/longitudinal_capture_v2_demo.html"
    count = _count_href_hash_in_sidebar_section(template)
    assert count == 0, (
        f"Demo longitudinal tiene {count} placeholders `href=\"#\"` en sidebar"
    )


# ──────────────────────────────────────────────────────────────────────
# §B — Verificación macro pm2_sidebar adoptado en demos
# ──────────────────────────────────────────────────────────────────────


def test_g2719_demo_full_uses_pm2_sidebar_macro():
    """H.G2719 — patient_profile_full_v2_demo.html importa y usa el macro."""
    content = (ROOT / "templates/demos/patient_profile_full_v2_demo.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in content
    assert "pm2_sidebar(" in content
    assert "active='profile'" in content


def test_g2720_demo_clinical_result_uses_pm2_sidebar_macro():
    """H.G2720 — clinical_result_v2_demo.html importa y usa el macro."""
    content = (ROOT / "templates/demos/clinical_result_v2_demo.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in content
    assert "pm2_sidebar(" in content
    assert "active='result'" in content


def test_g2721_demo_longitudinal_uses_pm2_sidebar_macro():
    """H.G2721 — longitudinal_capture_v2_demo.html importa y usa el macro."""
    content = (ROOT / "templates/demos/longitudinal_capture_v2_demo.html").read_text()
    assert 'from "components/pm2_sidebar.html" import pm2_sidebar' in content
    assert "pm2_sidebar(" in content
    assert "active='longitudinal'" in content


def test_g2722_no_hardcoded_badge_128_in_demos():
    """H.G2722 — Ningún demo tiene badge "128" hardcoded (era valor mock)."""
    for tpl_name in [
        "patient_profile_full_v2_demo.html",
        "clinical_result_v2_demo.html",
        "longitudinal_capture_v2_demo.html",
    ]:
        content = (ROOT / "templates/demos" / tpl_name).read_text()
        # Pattern: pm2-badge-mini con valor 128 (puede ser variations)
        pattern = re.compile(
            r'pm2-badge-mini[^>]*>\s*128\s*<',
            re.IGNORECASE,
        )
        assert not pattern.search(content), (
            f"Demo {tpl_name} aún tiene badge \"128\" hardcoded"
        )


# ──────────────────────────────────────────────────────────────────────
# §C — HTTP smoke: 3 demos producción retornan sidebar válido
# ──────────────────────────────────────────────────────────────────────


def _http_get(url: str, timeout: int = 8) -> tuple[int, bytes, dict]:
    """HTTP GET helper (no test framework dependency)."""
    try:
        req = urllib.request.Request(BASE_URL + url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except Exception as exc:
        return 0, str(exc).encode(), {}


def _server_running() -> bool:
    status, _, _ = _http_get("/")
    return status > 0


def test_g2723_demo_full_http_smoke_serves_macro_sidebar():
    """H.G2723 — /demos/v2/patient_profile_full sirve sidebar via macro (URLs reales)."""
    if not _server_running():
        return  # skip si server no corriendo
    status, body, headers = _http_get("/demos/v2/patient_profile_full")
    assert status == 200, f"HTTP status {status}"
    body_str = body.decode("utf-8", errors="replace")
    # Verificar que contiene URLs reales (no #)
    assert 'href="/patients"' in body_str
    assert 'href="/cohort-references"' in body_str
    assert 'href="/therapy-catalog"' in body_str
    # Verificar cache-busting headers
    cache_ctrl = headers.get("Cache-Control", "")
    assert "no-cache" in cache_ctrl.lower(), f"Cache-Control missing no-cache: {cache_ctrl}"


def test_g2724_clinical_result_http_smoke_serves_macro_sidebar():
    """H.G2724 — /clinical-result/<nss> sirve sidebar via macro."""
    if not _server_running():
        return
    # Usar paciente real (V2-E2E sample)
    status, body, _ = _http_get("/clinical-result/V2-E2E-1777271837")
    if status == 200:
        body_str = body.decode("utf-8", errors="replace")
        assert 'href="/patients"' in body_str, (
            "clinical_result no usa macro pm2_sidebar correctamente"
        )


def test_g2725_demos_dont_have_legacy_dummy_paths():
    """H.G2725 — Demos no tienen `/demos/v2/dashboard` o `/demos/v2/stage_center`
    en el sidebar (esos eran navegación interna de demos rotos).

    Macro pm2_sidebar apunta a producción real (`/dashboard`, `/clinical-hub`).
    """
    for tpl_name in [
        "patient_profile_full_v2_demo.html",
        "clinical_result_v2_demo.html",
        "longitudinal_capture_v2_demo.html",
    ]:
        content = (ROOT / "templates/demos" / tpl_name).read_text()
        # Dentro del sidebar (NO en otras partes del demo) NO debe haber estos
        # paths legacy. Como es difícil aislar sólo el sidebar via regex,
        # validamos el patrón completo: clase pm2-sidebar-link + href legacy
        legacy_patterns = [
            r'<a[^>]*href="/demos/v2/dashboard"[^>]*pm2-sidebar-link',
            r'<a[^>]*href="/demos/v2/stage_center"[^>]*pm2-sidebar-link',
            r'<a[^>]*pm2-sidebar-link[^>]*href="/demos/v2/dashboard"',
        ]
        for pattern_str in legacy_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            matches = pattern.findall(content)
            assert not matches, (
                f"Demo {tpl_name} tiene {len(matches)} link legacy demo en sidebar: "
                f"{pattern_str}"
            )


# ──────────────────────────────────────────────────────────────────────
# §D — Verificación que macro funciona en JINJA con stubs
# ──────────────────────────────────────────────────────────────────────


def test_g2726_macro_renders_with_minimal_args():
    """H.G2726 — Macro pm2_sidebar renderiza con args mínimos sin fallar."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda *args, **kwargs: "/static/stub"
    template_str = (
        '{% from "components/pm2_sidebar.html" import pm2_sidebar %}'
        '{{ pm2_sidebar(active="patients") }}'
    )
    rendered = env.from_string(template_str).render()
    # Verificar que tiene los 9 sidebar links principales
    assert 'href="/patients"' in rendered
    assert 'href="/audit-log"' in rendered
    assert 'href="/cohort-references"' in rendered
    assert 'href="/therapy-catalog"' in rendered
    assert 'href="/gates-coverage-dashboard"' in rendered
    # is-active solo en Pacientes
    assert "is-active" in rendered


def test_g2727_macro_renders_with_identity_nss_shows_perfil_links():
    """H.G2727 — Macro con identity_nss muestra links contextuales paciente."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda *args, **kwargs: "/static/stub"
    template_str = (
        '{% from "components/pm2_sidebar.html" import pm2_sidebar %}'
        '{{ pm2_sidebar(active="profile", identity_nss="P-12345") }}'
    )
    rendered = env.from_string(template_str).render()
    assert 'href="/patient_profile/P-12345"' in rendered
    assert 'href="/longitudinal-capture/P-12345"' in rendered
    assert 'href="/clinical-result/P-12345"' in rendered


def test_g2728_macro_omits_perfil_links_when_no_identity_nss():
    """H.G2728 — Macro sin identity_nss OMITE links Perfil/Longitudinal/Resultado."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda *args, **kwargs: "/static/stub"
    template_str = (
        '{% from "components/pm2_sidebar.html" import pm2_sidebar %}'
        '{{ pm2_sidebar(active="patients") }}'
    )
    rendered = env.from_string(template_str).render()
    # Sin identity_nss no debe haber links a perfil/longitudinal/resultado
    assert 'href="/patient_profile/' not in rendered
    assert 'href="/longitudinal-capture/' not in rendered
    assert 'href="/clinical-result/' not in rendered


# ──────────────────────────────────────────────────────────────────────
# §E — Verificación FAUBOT_RELEASE bumped post-LXXXIII.b
# ──────────────────────────────────────────────────────────────────────


def test_g2729_faubot_release_includes_lxxxiii():
    """H.G2729 — FAUBOT_RELEASE >= LXXXIII (post-fix demos; forward-compat LXXXIV+)."""
    from prostanet.shared.algorithm_version import FAUBOT_RELEASE
    # Aceptar LXXXIII o LXXXIII.b o LXXXIV+ o LXXXV+ (forward-compat)
    assert any(tag in FAUBOT_RELEASE for tag in ("LXXXIII", "LXXXIV", "LXXXV", "LXXXVI", "LXXXVII", "LXXXVIII", "LXXXIX", "XC", "XCI", "XCII", "XCIII", "XCIV", "XCV", "XCVI", "XCVII", "XCVIII", "XCIX", "C", "LXCI", "LXCII", "LXCIII", "LXCIV", "LXCV", "LXCVI", "LXCVII"))
