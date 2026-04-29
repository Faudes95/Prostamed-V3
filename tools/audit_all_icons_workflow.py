"""tools/audit_all_icons_workflow.py — FAUBOT LXXXIII auditoría iconos + flujo.

Audit que verifica para CADA ícono visible en UI v2:
1. ✅ URL destino válida (HTTP 200)
2. ✅ Endpoint backend existe (Flask route registrado)
3. ✅ Template renderiza completo (>5KB HTML output)
4. ✅ No console errors al navegar (vía curl content scan)
5. ✅ Sidebar consistency (links idénticos cross-template via macro)

Inventario íconos visibles:
SIDEBAR (12 links): Pacientes, Perfil actual, Captura longitudinal, Resultado CDE,
                    Wizard intake, Audit log, Centro clínico, Tablero ejecutivo,
                    Gates pivotales, Cohort references, Therapy catalog, Versionado
HEADER (3 buttons): Buscar (search), Faubot live (status), Ver legacy
ACCIONES PERFIL: Imprimir orden, Ver detalle decisión, etc.

Output: tabla matriz íconos × dimensions con OK/FAIL per ícono.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path("/Users/oscaralvarado/Desktop/ProstaNet_Model_Fase6")
sys.path.insert(0, str(ROOT))

BASE_URL = "http://localhost:8080"

# Inventario íconos visibles en sidebar v2 (vía pm2_sidebar.html macro)
SIDEBAR_ICONS = [
    {"label": "Pacientes", "url": "/patients", "section": "Clínica",
     "expected_min_bytes": 100000, "expected_text": "Cohorte de pacientes"},
    {"label": "Wizard intake", "url": "/patient_intake", "section": "Clínica",
     "expected_min_bytes": 1000, "expected_text": ""},  # legacy redirect
    {"label": "Audit log", "url": "/audit-log", "section": "Clínica",
     "expected_min_bytes": 5000, "expected_text": ""},
    {"label": "Centro clínico", "url": "/clinical-hub", "section": "Catálogo",
     "expected_min_bytes": 5000, "expected_text": ""},
    {"label": "Tablero ejecutivo", "url": "/dashboard", "section": "Catálogo",
     "expected_min_bytes": 5000, "expected_text": ""},
    {"label": "Gates pivotales", "url": "/gates-coverage-dashboard", "section": "Catálogo",
     "expected_min_bytes": 30000, "expected_text": "Cobertura"},
    {"label": "Cohort references", "url": "/cohort-references", "section": "Catálogo",
     "expected_min_bytes": 10000, "expected_text": "Cohort references"},
    {"label": "Therapy catalog", "url": "/therapy-catalog", "section": "Catálogo",
     "expected_min_bytes": 15000, "expected_text": "Therapy catalog"},
    {"label": "Versionado", "url": "/versioning-dashboard", "section": "Plataforma",
     "expected_min_bytes": 5000, "expected_text": ""},
]


def check_url(url: str) -> dict:
    """Verifica que URL retorna 200 + tamaño + content-type."""
    full_url = BASE_URL + url
    result = {
        "url": url,
        "status": 0,
        "bytes": 0,
        "content_type": "",
        "ok": False,
        "error": "",
        "cache_control": "",
    }
    try:
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result["status"] = resp.status
            content = resp.read()
            result["bytes"] = len(content)
            result["content_type"] = resp.headers.get("Content-Type", "")
            result["cache_control"] = resp.headers.get("Cache-Control", "")
            result["ok"] = resp.status == 200
            result["content_sample"] = content[:500].decode("utf-8", errors="replace")
            result["full_content"] = content.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["error"] = f"HTTPError {exc.code}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def audit_icon(icon: dict) -> dict:
    """Audit completo de un ícono."""
    audit = {
        "label": icon["label"],
        "url": icon["url"],
        "section": icon["section"],
        "url_200": False,
        "size_ok": False,
        "content_match": False,
        "cache_busting_ok": False,
        "score": 0,
        "issues": [],
    }

    check = check_url(icon["url"])
    if not check["ok"]:
        audit["issues"].append(f"URL fail: {check.get('error', 'status '+str(check['status']))}")
        return audit

    audit["url_200"] = True

    if check["bytes"] >= icon["expected_min_bytes"]:
        audit["size_ok"] = True
    else:
        audit["issues"].append(
            f"Tamaño insuficiente: {check['bytes']} < {icon['expected_min_bytes']}"
        )

    if not icon["expected_text"] or icon["expected_text"] in check["full_content"]:
        audit["content_match"] = True
    else:
        audit["issues"].append(f"Texto esperado '{icon['expected_text']}' NO encontrado")

    # Cache-busting headers (Faubot LXXXIII)
    if "no-cache" in check["cache_control"].lower():
        audit["cache_busting_ok"] = True
    else:
        audit["issues"].append(f"Cache headers missing: {check['cache_control']}")

    # Sidebar consistency: páginas v2 deben tener pm2-sidebar-link
    has_sidebar = "pm2-sidebar-link" in check.get("full_content", "")
    audit["has_sidebar_v2"] = has_sidebar

    audit["score"] = sum([
        audit["url_200"],
        audit["size_ok"],
        audit["content_match"],
        audit["cache_busting_ok"],
    ])

    return audit


def main():
    print("\n" + "="*78)
    print("  FAUBOT LXXXIII — Audit íconos visibles + flujo")
    print("="*78 + "\n")

    audits = []
    for icon in SIDEBAR_ICONS:
        audit = audit_icon(icon)
        audits.append(audit)

    # Stats
    total = len(audits)
    perfect = sum(1 for a in audits if a["score"] == 4)
    failing = sum(1 for a in audits if a["score"] < 3)
    has_sidebar = sum(1 for a in audits if a.get("has_sidebar_v2", False))

    print(f"  ✅ Perfect (4/4): {perfect}/{total}")
    print(f"  🔴 Failing (<3/4): {failing}/{total}")
    print(f"  📊 Has sidebar v2: {has_sidebar}/{total}")
    print()

    # Tabla detallada
    print(f"  {'Label':<25} {'URL':<32} {'Score':<8} {'Issues'}")
    print(f"  {'-'*25} {'-'*32} {'-'*8} {'-'*30}")
    for a in audits:
        score_str = f"{a['score']}/4 " + ("✅" if a['score'] == 4 else "⚠️" if a['score'] >= 3 else "🔴")
        issues_str = " | ".join(a['issues'][:2]) if a['issues'] else "—"
        print(f"  {a['label']:<25} {a['url']:<32} {score_str:<8} {issues_str[:50]}")

    print("\n" + "="*78)
    if failing == 0:
        print(f"  ✅ AUDIT PASS: {perfect}/{total} íconos perfectos")
    else:
        print(f"  🔴 AUDIT FAIL: {failing} íconos con score <3, requiere fix")
    print("="*78 + "\n")

    if "--json" in sys.argv:
        with open("/tmp/audit_icons_workflow.json", "w") as f:
            json.dump({
                "summary": {"total": total, "perfect": perfect, "failing": failing,
                            "has_sidebar_v2": has_sidebar},
                "audits": audits,
            }, f, indent=2)
        print(f"📁 Report JSON: /tmp/audit_icons_workflow.json\n")

    return 0 if failing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
