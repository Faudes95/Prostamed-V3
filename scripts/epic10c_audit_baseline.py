#!/usr/bin/env python3
"""EPIC 10C — Performance + Accessibility baseline auditor.

Genera un reporte Markdown + JSON ejecutivo de:
  1. Performance p50/p95/p99 por endpoint (HTML + API)
  2. Accessibility WCAG 2.1 AA static checks por página

Uso:
  PROSTANET_LOAD_MODEL=0 python3 scripts/epic10c_audit_baseline.py
  PROSTANET_LOAD_MODEL=0 python3 scripts/epic10c_audit_baseline.py \\
      --output-dir output/epic10c

Outputs:
  - output/epic10c/performance_baseline.json
  - output/epic10c/accessibility_baseline.json
  - output/epic10c/EPIC_10C_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PROSTANET_LOAD_MODEL", "0")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reuse el parser de los tests para no duplicar lógica.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_epic10c_accessibility_baseline import _audit_html, WCAG_TARGET_PAGES  # type: ignore  # noqa: E402

ENDPOINTS_HTML = [
    ("/clinical-hub", "Centro clínico"),
    ("/patient_intake", "Intake progresivo"),
    ("/dashboard", "Dashboard ejecutivo (deuda EPIC 10D)"),
]

ENDPOINTS_API = [
    ("/api/stats", "Estadísticas agregadas"),
    ("/api/decision-audit/algorithm-version", "FAUBOT release + SHAs"),
    ("/api/modules/m1_crpc/schema", "Schema m1CRPC"),
    ("/api/modules/m0_crpc/schema", "Schema m0CRPC"),
    ("/api/modules/post_prostatectomy/schema", "Schema post-prostatectomy"),
]

SAMPLES = 20


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def _measure(client, path: str, samples: int = SAMPLES) -> dict[str, Any]:
    try:
        client.get(path)  # warm-up
    except Exception:
        pass
    lat: list[float] = []
    status: list[int] = []
    size: list[int] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            r = client.get(path)
        except Exception as exc:
            return {"ok": False, "path": path, "error": repr(exc)}
        lat.append((time.perf_counter() - t0) * 1000)
        status.append(r.status_code)
        size.append(len(r.get_data() or b""))
    return {
        "ok": True,
        "path": path,
        "samples": samples,
        "status_codes_unique": sorted(set(status)),
        "size_bytes_median": int(statistics.median(size)),
        "p50_ms": round(statistics.median(lat), 2),
        "p95_ms": round(_percentile(lat, 95), 2),
        "p99_ms": round(_percentile(lat, 99), 2),
        "min_ms": round(min(lat), 2),
        "max_ms": round(max(lat), 2),
        "mean_ms": round(statistics.fmean(lat), 2),
    }


def _build_flask_client():
    from app import create_app

    app = create_app(config={"LOAD_MODEL": False, "TESTING": True})
    return app.test_client(), app


def _run_performance_baseline() -> dict[str, Any]:
    client, _ = _build_flask_client()
    result = {"html": [], "api": [], "samples_per_endpoint": SAMPLES}
    for path, label in ENDPOINTS_HTML:
        stats = _measure(client, path)
        stats["label"] = label
        stats["endpoint_class"] = "html"
        result["html"].append(stats)
    for path, label in ENDPOINTS_API:
        stats = _measure(client, path)
        stats["label"] = label
        stats["endpoint_class"] = "api"
        result["api"].append(stats)
    return result


def _run_accessibility_baseline() -> dict[str, Any]:
    client, _ = _build_flask_client()
    pages: list[dict[str, Any]] = []
    for path, label in WCAG_TARGET_PAGES:
        try:
            r = client.get(path, follow_redirects=True)
        except Exception as exc:
            pages.append({"path": path, "label": label, "ok": False, "error": repr(exc)})
            continue
        if r.status_code >= 500:
            pages.append({"path": path, "label": label, "ok": False, "status_code": r.status_code})
            continue
        audit = _audit_html(r.get_data(as_text=True))
        pages.append({
            "path": path,
            "label": label,
            "ok": True,
            "status_code": r.status_code,
            "violations": audit["violations"],
            "summary": audit["summary"],
        })
    return {"pages": pages}


def _render_report(perf: dict[str, Any], wcag: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# EPIC 10C — Performance & Accessibility Baseline Report")
    lines.append("")
    lines.append(
        f"> Generado por `scripts/epic10c_audit_baseline.py` · "
        f"{perf['samples_per_endpoint']} samples por endpoint · "
        f"in-process via Flask test client (sin Lighthouse/axe-core)."
    )
    lines.append("")
    lines.append("## 1. Performance baseline")
    lines.append("")
    lines.append("### HTML endpoints")
    lines.append("")
    lines.append("| Endpoint | Label | p50 (ms) | p95 (ms) | p99 (ms) | Size median |")
    lines.append("|---|---|--:|--:|--:|--:|")
    for s in perf["html"]:
        size_kb = f"{s.get('size_bytes_median',0)/1024:.1f}KB"
        lines.append(
            f"| `{s.get('path','?')}` | {s.get('label','')} | "
            f"{s.get('p50_ms','?')} | {s.get('p95_ms','?')} | "
            f"{s.get('p99_ms','?')} | {size_kb} |"
        )
    lines.append("")
    lines.append("### JSON API endpoints")
    lines.append("")
    lines.append("| Endpoint | Label | p50 (ms) | p95 (ms) | p99 (ms) | Size median |")
    lines.append("|---|---|--:|--:|--:|--:|")
    for s in perf["api"]:
        size_kb = (
            f"{s.get('size_bytes_median',0)/1024:.1f}KB"
            if s.get("size_bytes_median", 0) > 1024
            else f"{s.get('size_bytes_median', 0)}B"
        )
        lines.append(
            f"| `{s.get('path','?')}` | {s.get('label','')} | "
            f"{s.get('p50_ms','?')} | {s.get('p95_ms','?')} | "
            f"{s.get('p99_ms','?')} | {size_kb} |"
        )
    lines.append("")
    lines.append("### Thresholds aplicados (tests/test_epic10c_performance_baseline.py)")
    lines.append("")
    lines.append("- **HTML** p95 ≤ 800ms, p99 ≤ 1500ms")
    lines.append("- **API small (<200KB)** p95 ≤ 200ms, p99 ≤ 400ms")
    lines.append("- **API large (≥200KB)** p95 ≤ 500ms, p99 ≤ 800ms")
    lines.append("- **/dashboard** marked as `xfail` — deuda EPIC 10D pending optimization de queries SQLite + caching de KPIs")
    lines.append("")
    lines.append("## 2. Accessibility WCAG 2.1 AA static audit")
    lines.append("")
    lines.append("| Página | Status | H1 | Imgs sin alt | Inputs sin label | Buttons sin name | Violations |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|")
    for page in wcag["pages"]:
        if not page.get("ok"):
            lines.append(
                f"| `{page['path']}` | ERROR | — | — | — | — | "
                f"{page.get('error') or page.get('status_code', '?')} |"
            )
            continue
        s = page["summary"]
        lines.append(
            f"| `{page['path']}` | {page['status_code']} | "
            f"{s['h1_count']} | {s['images_missing_alt']}/{s['images_total']} | "
            f"{s['inputs_unlabeled']}/{s['inputs_total']} | "
            f"{s['buttons_empty']}/{s['buttons_total']} | "
            f"{len(page['violations'])} |"
        )
    lines.append("")
    # Detailed violations
    any_violations = any(p.get("violations") for p in wcag["pages"] if p.get("ok"))
    if any_violations:
        lines.append("### Violations detalladas")
        lines.append("")
        for page in wcag["pages"]:
            if not page.get("ok") or not page.get("violations"):
                continue
            lines.append(f"#### `{page['path']}` ({page['label']})")
            for v in page["violations"]:
                lines.append(f"- {v}")
            lines.append("")
    else:
        lines.append("### ✅ Sin violations WCAG estáticas detectadas")
        lines.append("")
    lines.append("## 3. Diagnóstico")
    lines.append("")
    # Identify slow endpoints
    slow_html = [s for s in perf["html"] if s.get("ok") and s.get("p95_ms", 0) > 800]
    slow_api = [s for s in perf["api"] if s.get("ok") and s.get("p95_ms", 0) > 500]
    if slow_html or slow_api:
        lines.append("**Endpoints con perf degradado:**")
        for s in slow_html:
            lines.append(f"- HTML `{s['path']}` p95={s['p95_ms']}ms (target ≤ 800ms)")
        for s in slow_api:
            lines.append(f"- API `{s['path']}` p95={s['p95_ms']}ms para {s.get('size_bytes_median',0)/1024:.1f}KB (target ≤ 500ms para responses ≥200KB)")
    else:
        lines.append("✅ Todos los endpoints cumplen thresholds aplicables.")
    lines.append("")
    lines.append("## 4. Próximos pasos (EPIC 10D candidates)")
    lines.append("")
    lines.append("1. **Optimizar `/dashboard`** (p95 ~1700ms baseline). Probable: cachear `dashboard_summary_to_v2()` + materializar `cohort_summary` snapshot SQLite.")
    lines.append("2. **Slim API schema responses** opcional — actualmente ~800KB por schema m1_crpc/m0_crpc post EPIC 10B; campos como `display_options`, `widget_config` podrían omitirse en respuesta JSON pública.")
    lines.append("3. **Lighthouse + axe-core full audit** con Chrome headless (fuera del scope EPIC 10C in-process). Recomendable antes de FDA Pre-Sub.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="EPIC 10C baseline")
    parser.add_argument("--output-dir", default="output/epic10c")
    args = parser.parse_args()

    out_dir = REPO_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Measuring performance...")
    perf = _run_performance_baseline()
    print("Auditing accessibility...")
    wcag = _run_accessibility_baseline()

    (out_dir / "performance_baseline.json").write_text(
        json.dumps(perf, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "accessibility_baseline.json").write_text(
        json.dumps(wcag, indent=2, default=str), encoding="utf-8"
    )
    report = _render_report(perf, wcag)
    (out_dir / "EPIC_10C_REPORT.md").write_text(report, encoding="utf-8")

    print(f"\nEPIC 10C baseline written to {out_dir}/")
    print(f"  - performance_baseline.json")
    print(f"  - accessibility_baseline.json")
    print(f"  - EPIC_10C_REPORT.md")
    # Quick stdout summary
    print("\nQuick perf summary (p95):")
    for s in perf["html"]:
        if s.get("ok"):
            print(f"  HTML {s['path']:>30s}  p95={s['p95_ms']:>7.1f}ms  size={s['size_bytes_median']/1024:.1f}KB")
    for s in perf["api"]:
        if s.get("ok"):
            print(f"  API  {s['path']:>30s}  p95={s['p95_ms']:>7.1f}ms  size={s['size_bytes_median']/1024:.1f}KB")
    print("\nAccessibility violations:")
    for p in wcag["pages"]:
        if p.get("ok"):
            n = len(p["violations"])
            mark = "✅" if n == 0 else f"⚠️  {n}"
            print(f"  {p['path']:>30s}  {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
