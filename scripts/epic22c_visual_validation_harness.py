#!/usr/bin/env python3
"""EPIC 22c — Visual Validation Harness (22 new trajectories).

Companion to scripts/epic20_visual_validation_harness.py. For each of
the 22 new EPIC 22c trajectories (pre-diagnostic, post-local modality,
hereditary carriers, oligomet refinement, special populations,
survivorship), generates:

  1. Synthetic patient exemplar with features representative of that state
  2. Static HTML page with classification result + therapeutic alternatives
  3. CHECKLIST.md for clinical reviewer (the user) to mark pass/fail

Reviewer clínico opens each HTML in a browser → verifies:
  - State name correct (matches EPIC 22c registry)
  - Therapeutic alternative coincides with NCCN 2026 v2
  - Rationale is clinically correct
  - Caveats / not_recommended items are present

Usage:
    python3 scripts/epic22c_visual_validation_harness.py
    # Output: output/epic22c_visual_validation/<state>.html (22 archivos)
    #         output/epic22c_visual_validation/CHECKLIST.md

Authorization scope: internal_shadow_observational_validation.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output" / "epic22c_visual_validation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


EXEMPLARS = [
    # ─────────────────── Pre-diagnostic (3) ───────────────────
    {
        "id": "exemplar_01_suspected_low_psa",
        "state_expected": "suspected_low_psa_no_biopsy",
        "demographics": "Hombre 58 años, screening anual",
        "clinical_summary": "PSA 6.8 ng/mL, PIRADS 2 en MRI prostática, sin biopsia previa, DRE normal.",
        "facts": {
            "known_cancer_diagnosis": False,
            "baseline_psa": 6.8,
            "pirads_score": 2,
            "age": 58,
            "dre_suspicious": False,
        },
        "nccn_expected_action": "Repeat PSA q6mo + lifestyle optimization (PROS-1)",
        "clinical_review_focus": "¿Sistema recomienda observación + lifestyle, NO biopsia inmediata?",
    },
    {
        "id": "exemplar_02_elevated_psa_ww",
        "state_expected": "suspected_elevated_psa_watchful_wait",
        "demographics": "Hombre 84 años, frail, ECOG 3",
        "clinical_summary": "PSA 22 ng/mL, ECOG 3, frailty severe, LE estimada <5 años.",
        "facts": {
            "known_cancer_diagnosis": False,
            "baseline_psa": 22.0,
            "ecog": "3",
            "frailty_status": "frail",
            "life_expectancy_years": "lt_5y",
            "age": 84,
        },
        "nccn_expected_action": "Watchful waiting + symptom-directed care (PROS-1)",
        "clinical_review_focus": "¿Sistema NO recomienda biopsia diagnóstica? ¿Palliative ADT solo si síntomas?",
    },
    {
        "id": "exemplar_03_neg_biopsy_age_lt_45",
        "state_expected": "negative_biopsy_age_lt_45",
        "demographics": "Hombre 42 años, padre con PCa a los 55, hermano con CA mama (BRCA2 fam)",
        "clinical_summary": "PSA 4.8, biopsia inicial 12 cores negativa hace 6 meses, family hx +.",
        "facts": {
            "known_cancer_diagnosis": False,
            "baseline_psa": 4.8,
            "age": 42,
            "prior_negative_biopsy": True,
            "first_degree_relative_pca_lt60": True,
            "brca_family_history": True,
        },
        "nccn_expected_action": "Aggressive MRI-targeted re-biopsy + germline testing (PROS-1 + PROS-A)",
        "clinical_review_focus": "¿Sistema recomienda germline testing universal? ¿Re-biopsy con MRI fusion?",
    },
    # ─────────────────── Post-local by modality (4) ───────────────────
    {
        "id": "exemplar_04_post_brachy_ldr",
        "state_expected": "post_brachy_ldr",
        "demographics": "Hombre 67 años, 18 meses post-brachy LDR I-125",
        "clinical_summary": "PSA actual 1.8 ng/mL (rising from nadir 0.6), sin Phoenix breach.",
        "facts": {
            "prior_local_treatment_modality": "brachytherapy_ldr",
            "months_since_local_treatment": 18,
            "nadir_psa_post_rt": 0.6,
            "current_psa": 1.8,
        },
        "nccn_expected_action": "PSA q6mo + bounce awareness 18-36mo (PROS-F)",
        "clinical_review_focus": "¿Sistema reconoce PSA bounce ventana? ¿NO alarma Phoenix en 18mo?",
    },
    {
        "id": "exemplar_05_post_ebrt_alone",
        "state_expected": "post_ebrt_alone",
        "demographics": "Hombre 71 años, post-EBRT 78 Gy IMRT, 36 meses",
        "clinical_summary": "PSA nadir 0.4, actual 1.2, sin Phoenix breach. Late rectal toxicity G2.",
        "facts": {
            "rt_modality": "imrt",
            "months_since_local_treatment": 36,
            "nadir_psa_post_rt": 0.4,
            "current_psa": 1.2,
        },
        "nccn_expected_action": "PSA q6mo + Phoenix monitoring + late toxicity surveillance (PROS-F + Phoenix)",
        "clinical_review_focus": "¿Sistema cita Phoenix criteria explícitamente? ¿Rectal toxicity tracked?",
    },
    {
        "id": "exemplar_06_post_sbrt",
        "state_expected": "post_sbrt",
        "demographics": "Hombre 65 años, post-SBRT 36.25 Gy x5, 8 meses",
        "clinical_summary": "Nadir alcanzado rápido (PSA 0.3 a los 6mo), sin toxicidad notable.",
        "facts": {
            "prior_local_treatment_modality": "sbrt",
            "months_since_local_treatment": 8,
            "nadir_psa_post_rt": 0.3,
            "current_psa": 0.4,
        },
        "nccn_expected_action": "PSA q6mo + faster nadir expected + QoL tracking (PROS-F)",
        "clinical_review_focus": "¿Sistema reconoce que SBRT tiene nadir más rápido? Trials HYPO-RT-PC / PACE-B citados?",
    },
    {
        "id": "exemplar_07_post_focal_therapy",
        "state_expected": "post_focal_therapy",
        "demographics": "Hombre 69 años, post-HIFU focal hemi-prostático, 12 meses",
        "clinical_summary": "PSA 1.5, MRI follow-up sin in-field recurrence.",
        "facts": {
            "prior_local_treatment_modality": "hifu",
            "months_since_local_treatment": 12,
            "nadir_psa_post_rt": 1.0,
            "current_psa": 1.5,
        },
        "nccn_expected_action": "In-field MRI + PSA q3-6mo + out-of-field surveillance (PROS-F)",
        "clinical_review_focus": "¿Sistema distingue in-field vs out-of-field? ¿Biopsy at 12mo routine recomendada?",
    },
    # ─────────────────── Hereditary carriers (5) ───────────────────
    {
        "id": "exemplar_08_brca2_carrier",
        "state_expected": "brca2_carrier",
        "demographics": "Hombre 56 años, mCRPC, germline BRCA2 c.5946delT confirmado",
        "clinical_summary": "Pathogenic BRCA2 documentado, family hx + (madre CA mama joven, hermana BRCA2+).",
        "facts": {
            "germline_testing_performed": True,
            "hrr_gene": "BRCA2",
            "germline_pathogenic_variant": "BRCA2:c.5946delT",
        },
        "nccn_expected_action": "PARP first-line in mCRPC + family counseling (PROS-A + PROS-J)",
        "clinical_review_focus": "¿Sistema cita PROfound / PROpel? ¿Counseling familiar mentioned?",
    },
    {
        "id": "exemplar_09_brca1_carrier",
        "state_expected": "brca1_carrier",
        "demographics": "Hombre 61 años, germline BRCA1 185delAG",
        "clinical_summary": "Pathogenic BRCA1 documentado (rarer than BRCA2 en PCa).",
        "facts": {
            "germline_testing_performed": True,
            "hrr_gene": "BRCA1",
            "germline_pathogenic_variant": "BRCA1:185delAG",
        },
        "nccn_expected_action": "PARP eligible + family counseling + intensified surveillance (PROS-A)",
        "clinical_review_focus": "¿Sistema reconoce BRCA1 ≠ BRCA2 pero similar pathway?",
    },
    {
        "id": "exemplar_10_atm_carrier",
        "state_expected": "atm_carrier",
        "demographics": "Hombre 64 años, germline ATM variant",
        "clinical_summary": "Pathogenic ATM c.7271T>G confirmado.",
        "facts": {
            "germline_testing_performed": True,
            "hrr_gene": "ATM",
            "germline_pathogenic_variant": "ATM:c.7271T>G",
        },
        "nccn_expected_action": "PARP response variable + consider clinical trial (PROS-A)",
        "clinical_review_focus": "¿Sistema reconoce ATM response variable a PARP vs BRCA2?",
    },
    {
        "id": "exemplar_11_lynch_carrier",
        "state_expected": "lynch_carrier",
        "demographics": "Hombre 59 años, germline MSH2, family hx CRC + endometrial",
        "clinical_summary": "Lynch syndrome confirmado (MSH2), padre fallecido por CRC.",
        "facts": {
            "germline_testing_performed": True,
            "hrr_gene": "MSH2",
            "germline_pathogenic_variant": "MSH2:c.1226_1227delAG",
        },
        "nccn_expected_action": "Pembrolizumab + colorectal surveillance (PROS-A + KEYNOTE-158)",
        "clinical_review_focus": "¿Sistema cita KEYNOTE-158? ¿Colorectal + endometrial surveillance?",
    },
    {
        "id": "exemplar_12_hoxb13_carrier",
        "state_expected": "hoxb13_carrier",
        "demographics": "Hombre 52 años, germline HOXB13 G84E",
        "clinical_summary": "HOXB13 G84E confirmado, family hx + PCa.",
        "facts": {
            "germline_testing_performed": True,
            "hrr_gene": "HOXB13",
            "germline_pathogenic_variant": "HOXB13:G84E",
        },
        "nccn_expected_action": "Intensified surveillance from age 40 + family cascade (PROS-A)",
        "clinical_review_focus": "¿Sistema sugiere surveillance intensificado desde 40y?",
    },
    # ─────────────────── Oligomet refinement (3) ───────────────────
    {
        "id": "exemplar_13_oligo_synchronous",
        "state_expected": "oligometastatic_synchronous",
        "demographics": "Hombre 67 años, de novo M1, 3 lesiones óseas",
        "clinical_summary": "PSA 45, Gleason 9, 3 lesiones óseas pélvicas en PSMA-PET.",
        "facts": {
            "metastasis_count": 3,
            "metastatic_timing": "synchronous",
            "metastasis_site": "bone",
        },
        "nccn_expected_action": "SBRT to all lesions + systemic ADT-ARSI intensification (PROS-G)",
        "clinical_review_focus": "¿Sistema cita STOMP/ORIOLE/STAMPEDE-G? ¿MDT mencionado?",
    },
    {
        "id": "exemplar_14_oligo_metach_adt_naive",
        "state_expected": "oligometastatic_metachronous_adt_naive",
        "demographics": "Hombre 70 años, BCR post-RP a los 4y, 2 lesiones nodales pélvicas",
        "clinical_summary": "Metachronous oligo, ADT-naive, MDT anatómicamente factible.",
        "facts": {
            "metastasis_count": 2,
            "metastatic_timing": "metachronous",
            "current_adt_context": "none",
        },
        "nccn_expected_action": "MDT + short-term ADT or ARSI (PROS-G + STOMP)",
        "clinical_review_focus": "¿Sistema prefiere MDT sobre escalation ARSI? ¿Short-term ADT mencionado?",
    },
    {
        "id": "exemplar_15_oligo_recurrent_post_def",
        "state_expected": "oligo_recurrent_post_definitive",
        "demographics": "Hombre 68 años, post-EBRT a los 5y, 1 lesión ósea",
        "clinical_summary": "Solitary bone metastasis 5y post-curative-RT, PSMA-PET +.",
        "facts": {
            "metastasis_count": 1,
            "prior_local_treatment_done": True,
            "metastatic_timing": "metachronous",
        },
        "nccn_expected_action": "MDT to recurrent sites + consider short systemic (PROS-G)",
        "clinical_review_focus": "¿Sistema reconoce post-definitive context? ¿Salvage local mencionado si fossa?",
    },
    # ─────────────────── Special populations (4) ───────────────────
    {
        "id": "exemplar_16_geriatric_frail",
        "state_expected": "geriatric_frail_limited",
        "demographics": "Hombre 82 años, G8=11, fragility documentada",
        "clinical_summary": "mCSPC nuevo dx, G8 11/17 (frail), Charlson 7.",
        "facts": {
            "age": 82,
            "g8_score": 11,
            "frailty_status": "frail",
            "charlson_score": 7,
        },
        "nccn_expected_action": "Treatment de-escalation + supportive care priority (PROS-K)",
        "clinical_review_focus": "¿Sistema NO recomienda chemo intensification? ¿Single-agent ARSI con dose mods?",
    },
    {
        "id": "exemplar_17_young_onset",
        "state_expected": "young_onset_pca",
        "demographics": "Hombre 48 años, recién diagnosticado",
        "clinical_summary": "PSA 12, Gleason 8, cT2c. Age at dx = 48y.",
        "facts": {
            "age_at_diagnosis": 48,
            "baseline_psa": 12.0,
            "gleason_score": 8,
        },
        "nccn_expected_action": "Universal germline + fertility preservation + aggressive biology workup (PROS-A + AYA)",
        "clinical_review_focus": "¿Sistema sugiere fertility preservation ANTES de tratamiento? ¿Germline mandatorio?",
    },
    {
        "id": "exemplar_18_comorbidity_cv",
        "state_expected": "comorbidity_limited_severe_cv",
        "demographics": "Hombre 75 años, IAM hace 8 meses, FE 30%, CABG previa",
        "clinical_summary": "mCRPC progresión, CV high risk band, active cardiac disease.",
        "facts": {
            "severe_cv_disease": True,
            "active_cardiac_disease": True,
            "cv_risk_band": "high",
        },
        "nccn_expected_action": "Enzalutamide / Apalutamide + cardiology co-management (PROS-K)",
        "clinical_review_focus": "¿Sistema EXCLUYE abiraterone+prednisone? ¿Cardiology referral mencionada?",
    },
    {
        "id": "exemplar_19_comorbidity_hepatic",
        "state_expected": "comorbidity_limited_severe_hepatic",
        "demographics": "Hombre 72 años, cirrosis Child B, LFTs 4x ULN",
        "clinical_summary": "ALT 180 U/L, AST 165 U/L, cirrosis documentada.",
        "facts": {
            "active_liver_disease": True,
            "cirrhosis_or_portal_hypertension": True,
            "alt_u_l": 180,
            "ast_u_l": 165,
        },
        "nccn_expected_action": "Enzalutamide / Apalutamide + hepatology monitoring (PROS-K)",
        "clinical_review_focus": "¿Sistema EXCLUYE abiraterone (contraindicado en active liver)?",
    },
    # ─────────────────── Survivorship (3) ───────────────────
    {
        "id": "exemplar_20_survivorship_5y",
        "state_expected": "survivorship_post_curative_5y_plus",
        "demographics": "Hombre 73 años, 7 años post-RP curative, NED",
        "clinical_summary": "PSA undetectable estable, late effects mínimos, QoL preservada.",
        "facts": {
            "years_since_curative_tx": 7,
            "years_NED": 7,
        },
        "nccn_expected_action": "Annual PSA + late effects surveillance + shared care PCP (SURV-1)",
        "clinical_review_focus": "¿Sistema sugiere shared care con primary care? ¿Annual PSA only?",
    },
    {
        "id": "exemplar_21_second_primary",
        "state_expected": "second_primary_surveillance",
        "demographics": "Hombre 78 años, 8 años post-EBRT 78 Gy",
        "clinical_summary": "Post-RT 8y NED, risk MDS/AML + secondary bladder/rectal.",
        "facts": {
            "years_post_rt": 8,
            "prior_pelvic_rt_dose_gy": 78,
        },
        "nccn_expected_action": "MDS/AML + bladder/rectal screening cadence (SURV-2)",
        "clinical_review_focus": "¿Sistema cita post-RT secondary malignancy risk? ¿CBC + colonoscopy mencionados?",
    },
    {
        "id": "exemplar_22_adt_long_term",
        "state_expected": "adt_long_term_complications",
        "demographics": "Hombre 70 años, ADT continuo 4 años por mCSPC",
        "clinical_summary": "ADT 48 meses, density pérdida, lipid panel alterado, fatigue + cognitive concerns.",
        "facts": {
            "adt_total_duration_months": 48,
            "adt_start_date": "2022-05-13",
        },
        "nccn_expected_action": "Multi-organ surveillance bone + CV + metabolic + cognitive (PROS-K + supportive)",
        "clinical_review_focus": "¿Sistema sugiere DXA anual? ¿Lipid panel q6mo? ¿Cognitive screening?",
    },
]


def _classify(facts: dict) -> dict:
    """Run classifier; return dict with state/confidence/rationale/preferred."""
    try:
        from prostanet.domains.state_classifier.clinical_state_classifier import (
            classify_clinical_state,
        )
        result = classify_clinical_state(facts)
        if result is None:
            return {
                "state": "(no_rule_matched)",
                "confidence": 0,
                "rationale": "—",
                "preferred": "—",
                "nccn_reference": "—",
                "discriminators": [],
            }
        return {
            "state": result.state,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "preferred": result.therapeutic_alternative_preferred or "—",
            "nccn_reference": result.evidence_tag,
            "discriminators": list(result.discriminators_matched),
        }
    except Exception as exc:
        return {
            "state": "(classifier_error)",
            "confidence": 0,
            "rationale": str(exc),
            "preferred": "—",
            "nccn_reference": "—",
            "discriminators": [],
        }


def _render_html(ex: dict, classification: dict) -> str:
    match = classification["state"] == ex["state_expected"]
    badge = ("PASS" if match else "REVIEW") if classification["state"] != "(no_rule_matched)" else "MISS"
    badge_color = {"PASS": "#22c55e", "REVIEW": "#f59e0b", "MISS": "#ef4444"}[badge]
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>EPIC 22c · {ex['id']}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 40px auto; max-width: 880px; background: #0f172a; color: #f8fafc; line-height: 1.5; }}
  h1 {{ color: #fbbf24; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 4px; }}
  .badge {{ display: inline-block; background: {badge_color}; color: #0f172a; padding: 4px 12px; border-radius: 12px; font-weight: 800; font-size: .8rem; letter-spacing: .1em; margin-right: 10px; }}
  section {{ margin: 20px 0; padding: 16px 20px; background: rgba(15,23,42,0.7); border: 1px solid rgba(148,163,184,0.25); border-radius: 12px; }}
  section h2 {{ font-size: .85rem; text-transform: uppercase; color: #94a3b8; letter-spacing: .12em; margin: 0 0 10px; }}
  .label {{ color: #94a3b8; font-size: .78rem; }}
  .value {{ color: #f8fafc; font-weight: 600; margin-bottom: 8px; }}
  code {{ background: rgba(0,0,0,0.4); padding: 2px 6px; border-radius: 4px; font-size: .85rem; color: #fbbf24; }}
  ul {{ margin: 0; padding-left: 20px; }}
  .match {{ color: #22c55e; }}
  .mismatch {{ color: #ef4444; }}
</style></head>
<body>
<h1>{ex['id']}</h1>
<div style="margin-bottom: 16px;">
  <span class="badge">{badge}</span>
  <span class="label">Esperado:</span> <code>{ex['state_expected']}</code>
  <span class="label" style="margin-left:14px">Clasificado:</span> <code class="{'match' if match else 'mismatch'}">{classification['state']}</code>
  <span class="label" style="margin-left:14px">Confianza:</span> {classification['confidence']:.2f}
</div>

<section>
  <h2>Paciente (sintético)</h2>
  <div class="label">Demografía</div><div class="value">{ex['demographics']}</div>
  <div class="label">Resumen clínico</div><div class="value">{ex['clinical_summary']}</div>
  <div class="label">Features estructurados</div>
  <pre style="background:#000;padding:10px;border-radius:6px;overflow-x:auto;color:#86efac;font-size:.78rem">{json.dumps(ex['facts'], indent=2, ensure_ascii=False)}</pre>
</section>

<section>
  <h2>Clasificación EPIC 22c</h2>
  <div class="label">Rationale</div><div class="value">{classification['rationale']}</div>
  <div class="label">Referencia NCCN</div><div class="value">{classification['nccn_reference']}</div>
  <div class="label">Discriminators matched</div>
  <ul>
    {''.join(f'<li><code>{d}</code></li>' for d in classification['discriminators']) or '<li>—</li>'}
  </ul>
</section>

<section>
  <h2>Terapia preferida (registry)</h2>
  <div class="value">{classification['preferred']}</div>
</section>

<section>
  <h2>Esperado por NCCN 2026 v2</h2>
  <div class="value">{ex['nccn_expected_action']}</div>
  <div class="label" style="margin-top:12px">Foco de la revisión clínica</div>
  <div class="value">{ex['clinical_review_focus']}</div>
</section>

<footer style="margin-top:30px; font-size:.72rem; color: #64748b;">
  EPIC 22c · Visual validation harness · {datetime.now().isoformat()[:19]}<br>
  Authorization scope: <code>internal_shadow_observational_validation</code>
</footer>
</body></html>
"""


def main() -> int:
    print(f"EPIC 22c visual validation — {len(EXEMPLARS)} exemplars")
    print(f"Output: {OUTPUT_DIR}")
    print()

    pass_count = 0
    review_count = 0
    miss_count = 0
    rows = []
    for ex in EXEMPLARS:
        classification = _classify(ex["facts"])
        html = _render_html(ex, classification)
        out_path = OUTPUT_DIR / f"{ex['id']}.html"
        out_path.write_text(html, encoding="utf-8")

        match = classification["state"] == ex["state_expected"]
        no_rule = classification["state"] == "(no_rule_matched)"
        status = "✅ PASS" if match else ("❌ MISS" if no_rule else "⚠️  REVIEW")
        if match:
            pass_count += 1
        elif no_rule:
            miss_count += 1
        else:
            review_count += 1
        rows.append({
            "id": ex["id"],
            "expected": ex["state_expected"],
            "classified": classification["state"],
            "confidence": classification["confidence"],
            "status": status,
            "review_focus": ex["clinical_review_focus"],
        })
        print(f"  {status}  {ex['id']:42s}  {classification['state']}")

    # CHECKLIST.md
    checklist = OUTPUT_DIR / "CHECKLIST.md"
    md = [
        "# EPIC 22c · Visual Validation Checklist",
        "",
        f"_Generated: {datetime.now().isoformat()[:19]}_",
        "",
        f"**Summary**: {pass_count} pass · {review_count} review · {miss_count} miss · {len(EXEMPLARS)} total",
        "",
        "Open each HTML file in browser and verify clinical correctness:",
        "",
        "| # | Status | Exemplar | Expected | Classified | Conf | Review Focus |",
        "|---|--------|----------|----------|------------|------|---------------|",
    ]
    for i, r in enumerate(rows, 1):
        md.append(
            f"| {i} | {r['status']} | `{r['id']}.html` | `{r['expected']}` | "
            f"`{r['classified']}` | {r['confidence']:.2f} | {r['review_focus']} |"
        )
    md.append("")
    md.append("## Reviewer instructions")
    md.append("")
    md.append("- ✅ **PASS**: classifier produced the expected state. Verify therapeutic alternative + rationale match NCCN 2026.")
    md.append("- ⚠️ **REVIEW**: classifier produced a different state. Check whether the alternative state is clinically defensible.")
    md.append("- ❌ **MISS**: classifier returned no rule match. Add discriminators or relax rule thresholds.")
    md.append("")
    checklist.write_text("\n".join(md), encoding="utf-8")

    print()
    print(f"Summary: {pass_count} PASS · {review_count} REVIEW · {miss_count} MISS · {len(EXEMPLARS)} total")
    print(f"Checklist: {checklist}")
    return 0 if pass_count == len(EXEMPLARS) else 1


if __name__ == "__main__":
    sys.exit(main())
