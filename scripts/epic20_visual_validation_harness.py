#!/usr/bin/env python3
"""EPIC 20 — Visual Validation Harness.

Para cada una de las 18 nuevas trayectorias EPIC 20, genera:
  1. Synthetic patient exemplar (features representativas de esa trayectoria)
  2. Página HTML con classification result, rationale, therapeutic alternatives
  3. CHECKLIST.md para revisión clínica del especialista

Diseño pragmático: no requiere Flask running ni Playwright global — genera HTML
estáticos que el reviewer abre en navegador para inspección visual rápida.
Si user quiere automation con Playwright, los HTML están listos para screenshot.

Uso:
    python3 scripts/epic20_visual_validation_harness.py
    # Output: output/epic20_visual_validation/<state>.html (18 archivos)
    #         output/epic20_visual_validation/CHECKLIST.md

Reviewer clínico abre cada HTML → verifica:
  - State name correcto
  - Therapeutic alternative coincide con NCCN 2026
  - Rationale es clínicamente correcto
  - Caveats explícitos sobre limitations
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output" / "epic20_visual_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────── 18 Synthetic exemplars (one per new trajectory) ───────────────────

EXEMPLARS = [
    {
        "id": "exemplar_01_very_low_risk",
        "state_expected": "very_low_risk_localized",
        "demographics": "Hombre 62 años, sin comorbilidades relevantes",
        "clinical_summary": "PSA 5.8 ng/mL, biopsia incidental por screening anual. Próstata 45 cc. 2/12 cores con Gleason 6 (<5% involucramiento). cT1c. PSA density 0.13.",
        "facts": {
            "baseline_psa": 5.8,
            "gleason_score": 6,
            "clinical_t_stage": "cT1c",
            "percent_positive_cores": 17,
            "psa_density": 0.13,
            "prostate_volume_cc": 45,
        },
        "nccn_expected_action": "Active surveillance strongly preferred (PROS-3)",
        "clinical_review_focus": "¿Sistema NO recomienda RP/RT como primera opción? ¿AS protocolo PRIAS-style?",
    },
    {
        "id": "exemplar_02_low_risk",
        "state_expected": "low_risk_localized",
        "demographics": "Hombre 65 años",
        "clinical_summary": "PSA 8.2, Gleason 6 en 3/12 cores, cT2a, sin features de very-low (no se tiene psa_density disponible).",
        "facts": {"baseline_psa": 8.2, "gleason_score": 6, "clinical_t_stage": "cT2a"},
        "nccn_expected_action": "AS preferred; RP, EBRT o brachy LDR aceptables (PROS-3)",
        "clinical_review_focus": "¿Sistema reconoce que falta data de very-low? data_insufficient_flags?",
    },
    {
        "id": "exemplar_03_favorable_intermediate",
        "state_expected": "favorable_intermediate_risk_localized",
        "demographics": "Hombre 68 años",
        "clinical_summary": "PSA 8.5, Gleason 3+4=7 en 4/14 cores, cT2a. 1 factor intermedio (GS).",
        "facts": {
            "baseline_psa": 8.5,
            "gleason_score": "7(3+4)",
            "gleason_primary_pattern": 3,
            "clinical_t_stage": "cT2a",
        },
        "nccn_expected_action": "Patient choice — AS o tx (PROS-3)",
        "clinical_review_focus": "¿GS 3+4 + único factor intermedio → favorable? NO unfavorable",
    },
    {
        "id": "exemplar_04_unfavorable_intermediate",
        "state_expected": "unfavorable_intermediate_risk_localized",
        "demographics": "Hombre 70 años",
        "clinical_summary": "PSA 14, Gleason 4+3=7 en 6/12 cores (primary pattern 4), cT2b.",
        "facts": {
            "baseline_psa": 14,
            "gleason_score": "7(4+3)",
            "gleason_primary_pattern": 4,
            "clinical_t_stage": "cT2b",
        },
        "nccn_expected_action": "Tx requerido (PROS-3): RP+ePLND o EBRT+ADT 4-6mo",
        "clinical_review_focus": "¿GS 4+3 = primary pattern 4 → unfavorable? AS NO recomendada",
    },
    {
        "id": "exemplar_05_high_risk",
        "state_expected": "high_risk_localized",
        "demographics": "Hombre 67 años",
        "clinical_summary": "PSA 18, Gleason 8 (4+4) en 8/12 cores, cT2a. 1 high-risk feature (GS 8).",
        "facts": {"baseline_psa": 18, "gleason_score": 8, "clinical_t_stage": "cT2a"},
        "nccn_expected_action": "EBRT+ADT 18-36mo (PROS-4)",
        "clinical_review_focus": "¿1 high-risk feature → high (NO very_high)? Trial DART o EORTC referenciado",
    },
    {
        "id": "exemplar_06_very_high_risk",
        "state_expected": "very_high_risk_localized",
        "demographics": "Hombre 64 años",
        "clinical_summary": "PSA 32, Gleason 9 (5+4) en 10/12 cores, cT3b (semilla seminal+). ≥2 high-risk features.",
        "facts": {
            "baseline_psa": 32,
            "gleason_score": 9,
            "gleason_primary_pattern": 5,
            "clinical_t_stage": "cT3b",
        },
        "nccn_expected_action": "EBRT+brachy boost+ADT 2-3y o triple modality (PROS-5)",
        "clinical_review_focus": "¿cT3b OR primary GS 5 OR ≥2 high features → very_high? ASCENDE-RT/STAMPEDE-G",
    },
    {
        "id": "exemplar_07_post_rt_bcr",
        "state_expected": "post_rt_bcr",
        "demographics": "Hombre 72 años, EBRT hace 4 años para high risk localized",
        "clinical_summary": "Nadir PSA post-RT 0.4 ng/mL (2y ago). PSA actual 2.8 ng/mL. Phoenix met.",
        "facts": {"prior_rt_received": True, "nadir_psa_post_rt": 0.4, "current_psa": 2.8},
        "nccn_expected_action": "Biopsy local + imaging para distinguir local vs distant; salvage cryoablation/HIFU/SBRT si local (PROS-D)",
        "clinical_review_focus": "¿Sistema NO recomienda salvage RT a fossa? ¿Pide biopsy local primero?",
    },
    {
        "id": "exemplar_08_mcspc_latitude",
        "state_expected": "mcspc_latitude_high_risk",
        "demographics": "Hombre 68 años, de novo metastatic",
        "clinical_summary": "PSA 200, Gleason 9, 4 bone mets, no visceral. 2/3 LATITUDE criteria (GS≥8 + bone≥3).",
        "facts": {
            "baseline_psa": 200,
            "gleason_score": 9,
            "bone_lesion_count_total": 4,
            "visceral_metastasis_present": False,
            "castration_resistance_confirmed": False,
        },
        "nccn_expected_action": "ADT+abiraterone 2-3y (LATITUDE)",
        "clinical_review_focus": "¿LATITUDE eligible aunque no sea CHAARTED high volume? Abiraterone preferred",
    },
    {
        "id": "exemplar_09_mcspc_visceral_only",
        "state_expected": "mcspc_visceral_only_m1c",
        "demographics": "Hombre 60 años",
        "clinical_summary": "Metástasis pulmonares múltiples, sin lesiones óseas. ECOG 1.",
        "facts": {
            "visceral_metastasis_present": True,
            "bone_lesion_count_total": 0,
            "visceral_site_entries": ["lung"],
            "castration_resistance_confirmed": False,
        },
        "nccn_expected_action": "ADT+darolutamide+docetaxel (ARASENS triplet)",
        "clinical_review_focus": "¿Visceral-only → arasens triplet preferred? NO arsi monoterapia",
    },
    {
        "id": "exemplar_10_mcspc_psma_only",
        "state_expected": "mcspc_psma_only_metastatic",
        "demographics": "Hombre 66 años, post-RP con BCR",
        "clinical_summary": "CT/bone scan negativos. PSMA-PET muestra 2 ganglios pélvicos. PSA 4.5.",
        "facts": {
            "conventional_imaging_m0": True,
            "psma_pet_positive": True,
            "bone_lesion_count_total": 0,
            "visceral_metastasis_present": False,
            "nonregional_nodal_count": 0,
            "castration_resistance_confirmed": False,
        },
        "nccn_expected_action": "ARSI monoterapia o RT pélvica + ADT (PROMETHEUS)",
        "clinical_review_focus": "¿De-escalation appropriate? NO chemo systemic para PSMA-only nodal",
    },
    {
        "id": "exemplar_11_mcrpc_arsi_naive",
        "state_expected": "mcrpc_arsi_naive",
        "demographics": "Hombre 71 años",
        "clinical_summary": "CRPC confirmado (testosterona <50, PSA progresivo). Bone mets sin ARSI previo en mCSPC (solo ADT).",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 3,
            "prior_arsi_in_mcspc": False,
        },
        "nccn_expected_action": "ARSI first-line: abiraterone o enzalutamide (AFFIRM/PREVAIL)",
        "clinical_review_focus": "¿Sistema reconoce ARSI-naive? Standard first-line ARSI",
    },
    {
        "id": "exemplar_12_mcrpc_post_arsi",
        "state_expected": "mcrpc_post_arsi",
        "demographics": "Hombre 73 años",
        "clinical_summary": "CRPC progresivo. Recibió abiraterone en mCSPC × 14m, ahora progresa.",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 4,
            "prior_arsi_in_mcspc": True,
        },
        "nccn_expected_action": "Cabazitaxel o docetaxel (CARD) — NO segundo ARSI (cross-resistance 80%)",
        "clinical_review_focus": "¿Sistema EVITA recomendar segundo ARSI? Chemo o alternativa MOA",
    },
    {
        "id": "exemplar_13_mcrpc_hrr_parp_naive",
        "state_expected": "mcrpc_hrr_positive_parp_naive",
        "demographics": "Hombre 68 años",
        "clinical_summary": "CRPC + germline BRCA2+. Sin PARP previo.",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 5,
            "hrr_status": "positive",
            "parp_inhibitor_received": False,
        },
        "nccn_expected_action": "Olaparib o rucaparib first (PROfound: +4.4mo rPFS)",
        "clinical_review_focus": "¿PARP-first pathway? NO retraso a olaparib post-chemo",
    },
    {
        "id": "exemplar_14_mcrpc_psma_lu177",
        "state_expected": "mcrpc_psma_eligible_lu177",
        "demographics": "Hombre 70 años, post-docetaxel y post-ARSI",
        "clinical_summary": "PSMA-PET con uptake intenso múltiples sitios. GFR 62. PSA 80.",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 6,
            "psma_pet_positive": True,
            "psma_pet_uptake_intensity": "intense",
            "gfr_baseline": 62,
            "prior_arsi_in_mcspc": True,
        },
        "nccn_expected_action": "[177Lu]Lu-PSMA-617 (VISION: +4mo OS)",
        "clinical_review_focus": "¿Lu-177 preferred over otro ARSI o chemo adicional? GFR ≥50 confirmed",
    },
    {
        "id": "exemplar_15_mcrpc_msi_h",
        "state_expected": "mcrpc_msi_h_dmmr",
        "demographics": "Hombre 65 años",
        "clinical_summary": "CRPC + tumor MSI-high en NGS panel. Bone mets + 1 hepatic met.",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 3,
            "visceral_metastasis_present": True,
            "msi_status": "high",
        },
        "nccn_expected_action": "Pembrolizumab (tumor-agnostic, KEYNOTE-365)",
        "clinical_review_focus": "¿Inmunoterapia identificada antes de chemo? 3-5% hyper-responders",
    },
    {
        "id": "exemplar_16_nepc",
        "state_expected": "nepc_differentiation",
        "demographics": "Hombre 67 años, CRPC con liver mets",
        "clinical_summary": "Biopsia hepática: small cell morphology, synaptophysin+, chromogranin 250 ng/mL (>3x ULN).",
        "facts": {
            "castration_resistance_confirmed": True,
            "bone_lesion_count_total": 2,
            "visceral_metastasis_present": True,
            "small_cell_morphology": True,
            "synaptophysin_biopsy_positive": True,
            "chromogranin_a_value": 250,
        },
        "nccn_expected_action": "Platino + etopósido o platino + taxano (CARLHA, NO ARSI)",
        "clinical_review_focus": "¿NEPC identificado? Platino preferred, NO ARSI sequencing. +OS 8mo→18mo",
    },
    {
        "id": "exemplar_17_hereditary_umbrella",
        "state_expected": "hereditary_germline_pathway_umbrella",
        "demographics": "Hombre 58 años con bone mets de novo",
        "clinical_summary": "mCSPC con padre y hermano con cáncer de mama <50y. Sin germline testing previo.",
        "facts": {
            "bone_lesion_count_total": 3,
            "family_history_breast_ovary_pancreas": True,
            "germline_testing_done": False,
            "gleason_score": 7,  # Avoid LATITUDE trigger
            "visceral_metastasis_present": False,
            "castration_resistance_confirmed": False,
        },
        "nccn_expected_action": "Germline panel testing + genetic counseling (PROS-A, universal en metastatic)",
        "clinical_review_focus": "¿Trigger germline testing? Family hx breast/ovary + metastatic disease",
    },
    {
        "id": "exemplar_18_oligo_progressive",
        "state_expected": "oligo_progressive_on_therapy",
        "demographics": "Hombre 69 años en enzalutamide × 18m",
        "clinical_summary": "PSA stable, pero PSMA-PET muestra 2 lesiones óseas nuevas. Resto de lesiones en respuesta.",
        "facts": {
            "progressing_on_systemic_therapy": True,
            "new_lesion_count_since_last_imaging": 2,
            "response_in_existing_lesions": "continued_response",
            "castration_resistance_confirmed": True,
        },
        "nccn_expected_action": "Continuar enzalutamide + SBRT a 2 lesiones nuevas (STOMP/ORIOLE)",
        "clinical_review_focus": "¿NO cambio de clase? SBRT local + continuar ARSI",
    },
]


# ─────────────────── HTML rendering ───────────────────


def render_exemplar_html(exemplar: dict, classification_result) -> str:
    """Render a single exemplar HTML page with classification + clinical review checklist."""
    state_match = classification_result and classification_result.state == exemplar["state_expected"]
    badge_color = "#22c55e" if state_match else "#ef4444"  # green if match, red if not
    badge_label = "✅ MATCH" if state_match else "❌ MISMATCH"

    actual_state = classification_result.state if classification_result else "(none)"
    actual_conf = f"{classification_result.confidence:.2f}" if classification_result else "0.00"
    actual_rationale = classification_result.rationale if classification_result else "(no classification)"
    actual_therapy = classification_result.therapeutic_alternative_preferred if classification_result else "(none)"
    actual_evidence = classification_result.evidence_tag if classification_result else ""

    facts_html = "\n".join(
        f'    <li><strong>{k}</strong>: {json.dumps(v)}</li>'
        for k, v in exemplar["facts"].items()
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>EPIC 20 — {exemplar['id']} — {exemplar['state_expected']}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 20px auto; padding: 0 20px; color: #1e293b; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; color: #475569; margin-top: 24px; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; color: white; font-weight: bold; font-size: 0.85rem; }}
  .card {{ border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px; margin: 12px 0; background: #f8fafc; }}
  .expected {{ border-left: 4px solid #3b82f6; }}
  .actual {{ border-left: 4px solid {badge_color}; }}
  .review {{ border-left: 4px solid #a855f7; background: #faf5ff; }}
  ul {{ padding-left: 22px; }}
  li {{ margin: 4px 0; }}
  code {{ background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 0.9rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #e2e8f0; }}
  .checklist {{ background: #fef3c7; padding: 10px 16px; border-radius: 6px; border: 1px solid #f59e0b; }}
  .meta {{ color: #64748b; font-size: 0.85rem; }}
</style>
</head>
<body>

<h1>EPIC 20 Visual Validation · {exemplar['id']}</h1>
<p class="meta">Generated {datetime.now().isoformat(timespec='seconds')} · NCCN Prostate Cancer v2026</p>

<div class="card expected">
  <h2>Expected (clínico)</h2>
  <p><strong>State:</strong> <code>{exemplar['state_expected']}</code></p>
  <p><strong>Demographics:</strong> {exemplar['demographics']}</p>
  <p><strong>Clinical summary:</strong> {exemplar['clinical_summary']}</p>
  <p><strong>NCCN expected action:</strong> {exemplar['nccn_expected_action']}</p>
</div>

<div class="card actual">
  <h2>Actual classification (sistema) <span class="badge" style="background:{badge_color}">{badge_label}</span></h2>
  <table>
    <tr><th>State</th><td><code>{actual_state}</code></td></tr>
    <tr><th>Confidence</th><td>{actual_conf}</td></tr>
    <tr><th>Rationale</th><td>{actual_rationale}</td></tr>
    <tr><th>Therapeutic preferred</th><td>{actual_therapy}</td></tr>
    <tr><th>NCCN reference</th><td><code>{actual_evidence}</code></td></tr>
  </table>
</div>

<div class="card review">
  <h2>Clinical review focus</h2>
  <p>{exemplar['clinical_review_focus']}</p>
</div>

<div class="card">
  <h2>Input facts</h2>
  <ul>
{facts_html}
  </ul>
</div>

<div class="checklist">
  <h2 style="margin-top:0;">Clinical reviewer checklist</h2>
  <ul>
    <li>[{('✅' if state_match else '❌')}] State name matches expected</li>
    <li>[ ] Therapeutic alternative is clinically appropriate per NCCN 2026</li>
    <li>[ ] Rationale is clinically sound (no overfit to spurious features)</li>
    <li>[ ] Evidence reference cites correct NCCN section</li>
    <li>[ ] No safety regression (would NOT lead urólogo to inferior decision)</li>
  </ul>
</div>

</body>
</html>
"""


# ─────────────────── Main ───────────────────


def main() -> int:
    from prostanet.domains.state_classifier.clinical_state_classifier import classify_clinical_state

    print(f"EPIC 20 Visual Validation Harness — generating {len(EXEMPLARS)} exemplars")
    print(f"Output: {OUTPUT_DIR}")
    print()

    results: list[dict] = []
    for exemplar in EXEMPLARS:
        result = classify_clinical_state(exemplar["facts"])
        html = render_exemplar_html(exemplar, result)
        html_path = OUTPUT_DIR / f"{exemplar['id']}.html"
        html_path.write_text(html, encoding="utf-8")

        state_match = result and result.state == exemplar["state_expected"]
        status = "✅ MATCH" if state_match else "❌ MISMATCH"
        actual = result.state if result else "(none)"
        print(f"  {status} {exemplar['id']:35s} expected={exemplar['state_expected']:35s} actual={actual}")
        results.append({
            "exemplar": exemplar,
            "actual_state": actual,
            "match": state_match,
            "html_path": str(html_path),
        })

    # Generate CHECKLIST.md
    checklist_lines = [
        f"# EPIC 20 Visual Validation Checklist",
        f"",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Reference: NCCN Prostate Cancer v2026",
        f"",
        f"## Summary",
        f"",
        f"- Total exemplars: {len(EXEMPLARS)}",
        f"- Classifications matched: {sum(1 for r in results if r['match'])}/{len(results)}",
        f"",
        f"## Per-exemplar review",
        f"",
        "| # | Exemplar | Expected state | Actual state | Match | HTML |",
        "|---|----------|----------------|--------------|-------|------|",
    ]
    for idx, r in enumerate(results, 1):
        ex = r["exemplar"]
        match_icon = "✅" if r["match"] else "❌"
        rel_path = Path(r["html_path"]).name
        checklist_lines.append(
            f"| {idx} | `{ex['id']}` | `{ex['state_expected']}` | `{r['actual_state']}` | {match_icon} | [{rel_path}](./{rel_path}) |"
        )

    checklist_lines.extend([
        "",
        "## Clinical reviewer instructions",
        "",
        "Para cada exemplar:",
        "",
        "1. Abrir el HTML correspondiente en navegador",
        "2. Comparar `Expected` vs `Actual classification`",
        "3. Verificar el checklist clínico de cada página",
        "4. Marcar fail si:",
        "   - State name no coincide (clinical regression)",
        "   - Therapeutic alternative no es clinicamente correcto",
        "   - Rationale tiene errores de lógica clínica",
        "   - Evidence reference es incorrecto o falta",
        "5. Reportar fails al equipo → fix rule → re-run harness → re-review",
        "",
        "## Auto-screenshot (opcional, con Playwright)",
        "",
        "Si querés capturar PNGs de cada HTML:",
        "",
        "```python",
        "from playwright.sync_api import sync_playwright",
        "with sync_playwright() as p:",
        "    browser = p.chromium.launch()",
        "    for html_file in Path('output/epic20_visual_validation').glob('*.html'):",
        "        page = browser.new_page()",
        "        page.goto(f'file://{html_file.absolute()}')",
        "        page.screenshot(path=html_file.with_suffix('.png'))",
        "    browser.close()",
        "```",
    ])

    checklist_path = OUTPUT_DIR / "CHECKLIST.md"
    checklist_path.write_text("\n".join(checklist_lines), encoding="utf-8")

    print()
    print(f"Generated {len(EXEMPLARS)} HTML files + CHECKLIST.md")
    print(f"Reviewer: open {checklist_path}")

    matched = sum(1 for r in results if r["match"])
    if matched < len(results):
        print(f"\nWARNING: {len(results) - matched} exemplars MISMATCH — review required")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
