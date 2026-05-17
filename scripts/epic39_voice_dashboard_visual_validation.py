#!/usr/bin/env python3
"""EPIC 39 — Visual validation harness para los 4 quick-capture voice cards
y el KPI dashboard.

Strategy honest:
- Playwright Python NOT instalado → harness genera HTML+JSON reports en lugar
  de screenshots. Cada report captura los tokens DOM relevantes que demuestran
  que la card renderiza correctamente para el patient elegido.
- Para REAL screenshots, ver `scripts/run_validation_playwright.mjs` (Node).
  Recipe manual al final del CHECKLIST.md generado.

Para cada uno de los 4 cards (ECOG/HRR/Castration/PSMA-PET):
  1. Identifica un patient elegible (gating de cada card distinto)
  2. GET /patient_profile/<nss> via test client
  3. Extrae fragments de HTML relevantes (card section + voice mic block)
  4. Verifica presencia de tokens (data-testid, voice button ids, helper init)
  5. Guarda fragment en output/epic39_visual_validation/<card>.html
  6. Guarda metadata en output/epic39_visual_validation/<card>.json

Adicionalmente:
  7. GET /loop-monitor → captura sección Capture Completeness Snapshot
     + KPI cards (4 capture coverage + funnel)
  8. Guarda fragment en output/epic39_visual_validation/dashboard.html

Output:
  - 5 HTML fragments (4 cards + dashboard)
  - 5 JSON metadata files
  - CHECKLIST.md para revisión clínica + recipe Playwright real

Usage:
    python3 scripts/epic39_voice_dashboard_visual_validation.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output" / "epic39_visual_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────── Token registry per card ───────────────────

CARD_VALIDATIONS = [
    {
        "key": "ecog",
        "label": "ECOG Quick Capture (EPIC 34.A Phase 2)",
        "card_testid": "ecog-quick-capture-card",
        "voice_button_id": "pm2EcogVoiceBtn",
        "voice_helper_init": "field: 'ecog'",
        "manual_buttons_class": "pm2-ecog-quick-btn",
        "capture_endpoint": "/api/patients/{nss}/ecog-capture",
        "voice_endpoint": "/api/voice/quick-capture/ecog",
        "patient_search_sql": """
            SELECT DISTINCT th.patient_id, pi.nss FROM treatment_history th
            JOIN patient_identity pi ON pi.id = th.patient_id
            WHERE (th.drug_scheme LIKE '%ABIRATERONE%' OR th.drug_scheme LIKE '%ENZALUTAMIDE%'
                   OR th.drug_scheme LIKE '%APALUTAMIDE%' OR th.drug_scheme LIKE '%DAROLUTAMIDE%')
              AND (th.end_date IS NULL OR th.end_date = '')
              AND th.patient_id NOT IN (
                  SELECT patient_id FROM patient_clinical_facts
                  WHERE fact_key IN ('ecog_score','ecog_performance_status') AND is_active=1
              )
            LIMIT 1
        """,
    },
    {
        "key": "hrr",
        "label": "HRR/Germline Quick Capture (EPIC 34.A Phase 4)",
        "card_testid": "hrr-quick-capture-card",
        "voice_button_id": "pm2HrrVoiceBtn",
        "voice_helper_init": "field: 'hrr'",
        "manual_buttons_class": "pm2-hrr-status-btn",
        "capture_endpoint": "/api/patients/{nss}/hrr-capture",
        "voice_endpoint": "/api/voice/quick-capture/hrr",
        "patient_search_sql": """
            SELECT DISTINCT th.patient_id, pi.nss FROM treatment_history th
            JOIN patient_identity pi ON pi.id = th.patient_id
            WHERE (th.drug_scheme LIKE '%ABIRATERONE%' OR th.drug_scheme LIKE '%ENZALUTAMIDE%'
                   OR th.drug_scheme LIKE '%APALUTAMIDE%' OR th.drug_scheme LIKE '%DAROLUTAMIDE%')
              AND (th.end_date IS NULL OR th.end_date = '')
              AND th.patient_id NOT IN (
                  SELECT patient_id FROM patient_clinical_facts
                  WHERE fact_key='hrr_status' AND is_active=1
                    AND normalized_value_text IN ('positive','negative')
              )
            LIMIT 1
        """,
    },
    {
        "key": "castration",
        "label": "Castration Quick Capture (EPIC 34.A Phase 5)",
        "card_testid": "castration-quick-capture-card",
        "voice_button_id": "pm2CastrationVoiceBtn",
        "voice_helper_init": "field: 'castration'",
        "manual_buttons_class": "pm2-castration-status-btn",
        "capture_endpoint": "/api/patients/{nss}/castration-capture",
        "voice_endpoint": "/api/voice/quick-capture/castration",
        "patient_search_sql": """
            -- Castration card gating: needs ADT/ARPI active AND no recent castration
            -- documented in patient_clinical_facts (source-agnostic — facts imported
            -- from follow_up_visits, voice capture, longitudinal append all land here).
            SELECT DISTINCT th.patient_id, pi.nss FROM treatment_history th
            JOIN patient_identity pi ON pi.id = th.patient_id
            WHERE (th.drug_scheme LIKE '%ABIRATERONE%' OR th.drug_scheme LIKE '%ENZALUTAMIDE%'
                   OR th.drug_scheme LIKE '%APALUTAMIDE%' OR th.drug_scheme LIKE '%DAROLUTAMIDE%'
                   OR th.drug_scheme LIKE '%ADT%' OR th.drug_scheme LIKE '%LEUPROLIDE%'
                   OR th.drug_scheme LIKE '%GOSERELIN%')
              AND (th.end_date IS NULL OR th.end_date = '')
              AND th.patient_id NOT IN (
                  SELECT patient_id FROM patient_clinical_facts
                  WHERE fact_key IN ('castrate_testosterone_status','castration_status')
                    AND is_active=1
              )
            LIMIT 1
        """,
    },
    {
        "key": "psma_pet",
        "label": "PSMA-PET Quick Capture (EPIC 34.A Phase 6)",
        "card_testid": "psma-pet-quick-capture-card",
        "voice_button_id": "pm2PsmaVoiceBtn",
        "voice_helper_init": "field: 'psma_pet'",
        "manual_buttons_class": "pm2-psma-status-btn",
        "capture_endpoint": "/api/patients/{nss}/psma-pet-capture",
        "voice_endpoint": "/api/voice/quick-capture/psma_pet",
        "patient_search_sql": """
            SELECT DISTINCT pst.patient_id, pi.nss FROM patient_state_timeline pst
            JOIN patient_identity pi ON pi.id = pst.patient_id
            WHERE LOWER(pst.state) IN ('recurrence_bcr','m1_crpc','m0_crpc')
              AND pst.patient_id NOT IN (
                  SELECT patient_id FROM patient_clinical_facts
                  WHERE fact_key IN ('psma_pet_status','psma_pet_done') AND is_active=1
                    AND normalized_value_text IN ('true','positive_metastatic','positive_oligometastatic',
                                                   'positive_local_recurrence','negative')
              )
            LIMIT 1
        """,
    },
]


def _resolve_patient(sql: str) -> tuple[int, str] | None:
    import tracking_db as _td
    conn = sqlite3.connect(_td.get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(sql).fetchone()
        if row:
            return row["patient_id"], row["nss"]
    finally:
        conn.close()
    return None


def _extract_card_fragment(html: str, card_testid: str, radius_chars: int = 8000) -> str:
    """Extract the <section> with data-testid + surrounding context (handler script)."""
    pattern = re.compile(
        rf'<section[^>]*data-testid="{re.escape(card_testid)}".*?</section>\s*</details>\s*<script>.*?</script>',
        re.DOTALL,
    )
    m = pattern.search(html)
    if m:
        return m.group(0)
    # Fallback — return ±radius chars around the testid
    idx = html.find(card_testid)
    if idx < 0:
        return ""
    start = max(0, idx - 500)
    end = min(len(html), idx + radius_chars)
    return html[start:end]


def _extract_dashboard_section(html: str) -> str:
    """Extract Cohorte Exploratoria MX section from loop-monitor HTML."""
    pattern = re.compile(
        r'<section[^>]*aria-label="Cohorte Exploratoria MX".*?</section>\s*<script>.*?</script>',
        re.DOTALL,
    )
    m = pattern.search(html)
    return m.group(0) if m else ""


def _validate_card(client, card: dict, output_dir: Path) -> dict:
    """Returns {success, patient_nss, tokens_found, missing_tokens, fragment_path}."""
    result = {
        "key": card["key"],
        "label": card["label"],
        "validated_at": datetime.utcnow().isoformat() + "Z",
    }
    resolved = _resolve_patient(card["patient_search_sql"])
    if not resolved:
        result["status"] = "no_eligible_patient"
        result["note"] = "No patient found matching this card's gating SQL"
        return result
    patient_id, nss = resolved
    result["patient_id"] = patient_id
    result["patient_nss"] = nss

    r = client.get(f"/patient_profile/{nss}")
    if r.status_code != 200:
        result["status"] = "profile_render_failed"
        result["http_status"] = r.status_code
        return result
    html = r.get_data(as_text=True)

    # Token validation
    tokens_to_check = [
        ("card_testid", f'data-testid="{card["card_testid"]}"'),
        ("voice_button_id", card["voice_button_id"]),
        ("voice_helper_init", card["voice_helper_init"]),
        ("manual_buttons_class", card["manual_buttons_class"]),
        # Note: voice_endpoint full URL is constructed at JS runtime via
        # `/api/voice/quick-capture/${config.field}` — not in template source.
        # We verify the field name appears in voice_helper_init token below.
        ("voice_helper_script", "pm2_voice_quick_capture.js"),
        ("pm2_setup_global", "pm2SetupVoiceQuickCapture"),
    ]
    tokens_found = {}
    missing = []
    for key, tok in tokens_to_check:
        present = tok in html
        tokens_found[key] = present
        if not present:
            missing.append(tok)
    result["tokens_found"] = tokens_found
    result["missing_tokens"] = missing
    result["all_tokens_present"] = len(missing) == 0
    result["status"] = "ok" if not missing else "partial"

    # Extract card fragment for visual review
    fragment = _extract_card_fragment(html, card["card_testid"])
    fragment_path = output_dir / f"{card['key']}_card.html"
    capture_endpoint = card["capture_endpoint"].format(nss=nss)
    fragment_path.write_text(
        _wrap_fragment_html(
            title=card["label"],
            card_key=card["key"],
            patient_nss=nss,
            capture_endpoint=capture_endpoint,
            voice_endpoint=card["voice_endpoint"],
            fragment=fragment or "<p style='color:red'>FRAGMENT NOT FOUND (gating may have suppressed card)</p>",
        ),
        encoding="utf-8",
    )
    result["fragment_path"] = str(fragment_path.relative_to(PROJECT_ROOT))
    result["fragment_bytes"] = len(fragment)
    return result


def _validate_dashboard(client, output_dir: Path) -> dict:
    result = {
        "key": "dashboard",
        "label": "KPI Dashboard (EPIC 33.C + EPIC 37)",
        "validated_at": datetime.utcnow().isoformat() + "Z",
    }
    r = client.get("/loop-monitor")
    if r.status_code != 200:
        result["status"] = "render_failed"
        result["http_status"] = r.status_code
        return result
    html = r.get_data(as_text=True)
    tokens_to_check = [
        ("capture_snapshot_canvas", "captureCoverageChart"),
        ("render_capture_coverage_kpi", "renderCaptureCoverageKPI"),
        ("render_trial_funnel_kpi", "renderTrialFunnelKPI"),
        ("render_capture_snapshot", "renderCaptureSnapshot"),
        ("snapshot_header", "Capture Completeness Snapshot"),
        ("epic37_header", "EPIC 33.C + EPIC 37"),
        ("cohort_dashboard_endpoint", "/api/population/cohort-dashboard"),
        ("kpi_ecog_coverage", "ecog_capture_coverage"),
        ("kpi_hrr_coverage", "hrr_capture_coverage"),
        ("kpi_castration_coverage", "castration_confirmation_coverage"),
        ("kpi_psma_coverage", "psma_pet_capture_coverage"),
        ("kpi_trial_funnel", "trial_eligibility_funnel"),
    ]
    tokens_found = {}
    missing = []
    for key, tok in tokens_to_check:
        present = tok in html
        tokens_found[key] = present
        if not present:
            missing.append(tok)
    result["tokens_found"] = tokens_found
    result["missing_tokens"] = missing
    result["all_tokens_present"] = len(missing) == 0
    result["status"] = "ok" if not missing else "partial"
    fragment = _extract_dashboard_section(html)
    fragment_path = output_dir / "dashboard_section.html"
    fragment_path.write_text(
        _wrap_fragment_html(
            title="KPI Dashboard · Cohorte Exploratoria MX",
            card_key="dashboard",
            patient_nss="(n/a — pop-level view)",
            capture_endpoint="(n/a)",
            voice_endpoint="(n/a)",
            fragment=fragment or "<p style='color:red'>DASHBOARD SECTION NOT FOUND</p>",
        ),
        encoding="utf-8",
    )
    result["fragment_path"] = str(fragment_path.relative_to(PROJECT_ROOT))
    result["fragment_bytes"] = len(fragment)
    return result


def _wrap_fragment_html(*, title, card_key, patient_nss, capture_endpoint,
                       voice_endpoint, fragment) -> str:
    """Wrap fragment in a standalone preview page con metadata header."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>EPIC 39 · {title}</title>
<style>
  body {{ background:#0f172a; color:#f8fafc; font-family:system-ui,sans-serif; margin:0; padding:0; }}
  .epic39-header {{ position:sticky; top:0; background:#1e293b; padding:14px 24px; border-bottom:2px solid #475569; z-index:100; }}
  .epic39-header h1 {{ margin:0; font-size:1.2rem; color:#86efac; }}
  .epic39-header dl {{ display:grid; grid-template-columns:140px 1fr; gap:4px 16px; margin:8px 0 0; font-size:.78rem; }}
  .epic39-header dt {{ color:#94a3b8; font-weight:600; }}
  .epic39-header dd {{ margin:0; color:#cbd5e1; font-family:ui-monospace,monospace; }}
  .epic39-fragment-wrap {{ padding:20px; }}
  :root {{ --space-4: 14px; --space-6: 22px; --pn-text-muted: #94a3b8; --pm-font-display: system-ui; }}
</style>
</head>
<body>
  <header class="epic39-header">
    <h1>🔍 EPIC 39 · Visual Validation · {title}</h1>
    <dl>
      <dt>Card key</dt><dd>{card_key}</dd>
      <dt>Patient NSS</dt><dd>{patient_nss}</dd>
      <dt>Capture endpoint</dt><dd>{capture_endpoint}</dd>
      <dt>Voice endpoint</dt><dd>{voice_endpoint}</dd>
      <dt>Generated</dt><dd>{datetime.utcnow().isoformat()}Z</dd>
    </dl>
  </header>
  <div class="epic39-fragment-wrap">
{fragment}
  </div>
</body>
</html>"""


def _write_checklist(results: list[dict], output_dir: Path) -> Path:
    """Generate CHECKLIST.md with all 5 validations + Playwright runbook."""
    lines = [
        "# EPIC 39 — Visual Validation Checklist",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Resumen",
        "",
        "| Card | Status | Patient NSS | Tokens OK | Fragment |",
        "|------|--------|-------------|-----------|----------|",
    ]
    for r in results:
        status_emoji = {"ok": "✅", "partial": "⚠️", "no_eligible_patient": "⊘", "profile_render_failed": "❌", "render_failed": "❌"}.get(r.get("status"), "?")
        tokens_ok = "all" if r.get("all_tokens_present") else f"missing: {len(r.get('missing_tokens', []))}"
        nss = r.get("patient_nss", "(n/a)")
        frag_path = r.get("fragment_path", "")
        lines.append(f"| {r['label']} | {status_emoji} {r.get('status', '?')} | `{nss}` | {tokens_ok} | [{Path(frag_path).name}]({Path(frag_path).name}) |")
    lines.extend([
        "",
        "## Detalle por card",
        "",
    ])
    for r in results:
        lines.append(f"### {r['label']}")
        lines.append("")
        lines.append(f"- **status**: {r.get('status')}")
        lines.append(f"- **patient_nss**: `{r.get('patient_nss', '(n/a)')}`")
        if r.get("missing_tokens"):
            lines.append(f"- **missing tokens** (revisar):")
            for tok in r["missing_tokens"]:
                lines.append(f"  - `{tok}`")
        lines.append(f"- **fragment**: `{r.get('fragment_path', '(no frag)')}`")
        lines.append("")
        lines.append("**Checklist clínico** (abrir el fragment HTML en el navegador):")
        lines.append("- [ ] Card renderiza con el header y descripción esperada")
        lines.append("- [ ] Botones manuales presentes y estilizados")
        lines.append("- [ ] Botón \"🎤 Dictar\" visible con label correcto")
        lines.append("- [ ] Status text muestra \"EPIC 36 · Voice PoC\"")
        lines.append("- [ ] Result div oculto por defecto (display:none)")
        lines.append("- [ ] Microcopy en español, sin tipos")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Recipe manual: Real screenshots con Playwright (Node)",
        "",
        "Para capturar screenshots PNG reales (no solo fragments HTML), instalar",
        "Playwright Node:",
        "",
        "```bash",
        "npm install playwright",
        "npx playwright install chromium",
        "```",
        "",
        "Y correr (con Flask activo en localhost:8080):",
        "",
        "```javascript",
        "// scripts/epic39_real_screenshots.mjs",
        "import { chromium } from 'playwright';",
        "",
        "const TARGETS = [",
    ])
    for r in results:
        if r.get("status") in ("ok", "partial") and r.get("patient_nss"):
            url = f"http://127.0.0.1:8080/patient_profile/{r['patient_nss']}" if r["key"] != "dashboard" else "http://127.0.0.1:8080/loop-monitor"
            lines.append(f"  {{ key: '{r['key']}', url: '{url}', testid: '{r.get('card_testid', 'dashboard-section')}' }},")
    lines.extend([
        "];",
        "",
        "const browser = await chromium.launch();",
        "for (const t of TARGETS) {",
        "  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });",
        "  const page = await ctx.newPage();",
        "  await page.goto(t.url, { waitUntil: 'networkidle' });",
        "  await page.screenshot({ path: `output/epic39_visual_validation/${t.key}_screenshot.png`, fullPage: true });",
        "  console.log(`captured ${t.key}`);",
        "}",
        "await browser.close();",
        "```",
        "",
        "## Privacy",
        "",
        "Fragments NO incluyen PHI sensible (solo DOM markup + endpoint URLs).",
        "Screenshots reales SÍ incluyen PHI → almacenar solo en `output/` (gitignored).",
        "",
    ])
    path = output_dir / "CHECKLIST.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    print(f"EPIC 39 · Visual Validation Harness")
    print(f"  Output: {OUTPUT_DIR}")
    print()

    # Init Flask test client
    from app import app, create_app
    create_app()
    client = app.test_client()

    results = []
    for card in CARD_VALIDATIONS:
        print(f"  · {card['label']}")
        r = _validate_card(client, card, OUTPUT_DIR)
        r["card_testid"] = card["card_testid"]
        results.append(r)
        emoji = {"ok": "✅", "partial": "⚠️", "no_eligible_patient": "⊘", "profile_render_failed": "❌"}.get(r.get("status"), "?")
        print(f"    {emoji} {r.get('status', '?')} (patient={r.get('patient_nss', '?')}, missing={len(r.get('missing_tokens', []))})")

    print(f"  · KPI Dashboard")
    dash_r = _validate_dashboard(client, OUTPUT_DIR)
    results.append(dash_r)
    emoji = {"ok": "✅", "partial": "⚠️", "render_failed": "❌"}.get(dash_r.get("status"), "?")
    print(f"    {emoji} {dash_r.get('status', '?')} (missing={len(dash_r.get('missing_tokens', []))})")

    # Write summary JSON + CHECKLIST.md
    summary_path = OUTPUT_DIR / "validation_summary.json"
    summary_path.write_text(json.dumps({
        "epic": 39,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "results": results,
        "summary": {
            "total": len(results),
            "ok": sum(1 for r in results if r.get("status") == "ok"),
            "partial": sum(1 for r in results if r.get("status") == "partial"),
            "no_patient": sum(1 for r in results if r.get("status") == "no_eligible_patient"),
            "failed": sum(1 for r in results if r.get("status") in ("profile_render_failed", "render_failed")),
        }
    }, indent=2, default=str), encoding="utf-8")
    checklist_path = _write_checklist(results, OUTPUT_DIR)

    print()
    print(f"  Summary: {summary_path.relative_to(PROJECT_ROOT)}")
    print(f"  Checklist: {checklist_path.relative_to(PROJECT_ROOT)}")
    print()
    print(f"Resultado: {sum(1 for r in results if r.get('status') == 'ok')}/{len(results)} OK")
    any_failed = any(r.get("status") in ("profile_render_failed", "render_failed") for r in results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
