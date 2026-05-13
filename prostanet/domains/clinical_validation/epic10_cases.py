# IEC 62304 §5.7 (System testing)
"""EPIC 10 — Real-world patient validation (catálogo de trayectorias).

10 trayectorias clínicamente representativas de la práctica oncológica
diaria en cáncer de próstata, distribuidas sobre los 18 estadios NCCN.

A diferencia de epic9_hardening (que prueba GAPs específicos) y de las
71 trayectorias del catálogo base (que prueban reglas particulares),
estas 10 son **casos de consulta típica** diseñados para validar que
el motor end-to-end (state classifier + rules NCCN/EAU + trial matcher)
produce las recomendaciones que un urólogo experimentado esperaría.

Cobertura distributiva (10 trayectorias, todas con `scenario_family
="epic10_real_world"`):

  1. Vigilancia activa  (NCCN very-low / low risk, PRECISE)
  2. Localized intermediate-favorable  (ProtecT, EORTC 22991)
  3. Localized very-high risk  (STAMPEDE M0)
  4. Post-RP BCR  (GETUG-AFU 16, RADICALS-RT)
  5. Post-RT BCR Phoenix met  (AUA/ASTRO/SUO 2024)
  6. mHSPC high volume sync (ARASENS, PEACE-1)
  7. mHSPC oligometacrónico  (STAMPEDE-H, STOMP)
  8. m0CRPC high-risk PSADT  (ARAMIS, SPARTAN, PROSPER)
  9. m1CRPC BRCA2+ PSMA-PET+  (PROfound, VISION)
 10. m1CRPC heavily pretreated AR-V7+  (PROPHECY, KEYNOTE-365)

Cada trayectoria documenta:
  - `clinical_oracle.expected_effective_state`  (estado clasificado)
  - `clinical_oracle.expected_action_label` o `expected_action_contains`
  - `clinical_oracle.expected_guideline_basis_any`  (NCCN/EAU section)
  - `clinical_oracle.epic10_evidence`  (trial PMID o guideline ref)
  - `clinical_oracle.epic10_scenario_summary`  (1 línea resumen)

Evidencia (referencias canónicas):
  - NCCN PROS v5.2026
  - EAU Prostate Cancer Guidelines 2026
  - PIVOT (Wilt NEJM 2012, PMID 22808955)
  - ProtecT (Hamdy NEJM 2016/2023, PMID 27626136 / 36912537)
  - STAMPEDE M0 high-risk (James Lancet 2022, PMID 35569466)
  - GETUG-AFU 16 (Carrie Lancet Oncol 2016, PMID 27160474)
  - RADICALS-RT (Parker Lancet 2020, PMID 33002429)
  - AUA/ASTRO/SUO Salvage 2024
  - ARASENS (Smith NEJM 2022, PMID 35179323)
  - PEACE-1 (Fizazi Lancet 2022, PMID 35405085)
  - STAMPEDE-H (Parker Lancet 2018, PMID 30355464)
  - STOMP (Ost JCO 2018, PMID 29240541)
  - ARAMIS (Fizazi NEJM 2020, PMID 32905676)
  - SPARTAN (Smith NEJM 2018, PMID 29420164)
  - PROSPER (Hussain NEJM 2018, PMID 29949494)
  - PROfound (de Bono NEJM 2020, PMID 32343890)
  - VISION (Sartor NEJM 2021, PMID 34161051)
  - PROPHECY (Armstrong JAMA Oncol 2019, PMID 31265030)
  - KEYNOTE-365 (Yu JCO 2023, PMID 37207300)

Nota arquitectónica:
  El catálogo no llama al motor — sólo registra los oráculos esperados.
  El harness (`scenario_harness`) y el endpoint
  `/api/validation/trajectories` consumen estas trayectorias y comparan
  contra la decisión real del motor en tiempo de auditoría.
"""
from __future__ import annotations

from typing import Any

from prostanet.domains.clinical_validation.trajectory_catalog import _trajectory, _visit


def _epic10(
    *,
    scenario_id: str,
    title: str,
    module_id: str,
    baseline_payload: dict[str, Any],
    expected_action_label: str | None = None,
    expected_action_contains: str | None = None,
    expected_selected_therapy_aliases: list[str] | None = None,
    guideline_basis: list[str] | None = None,
    evidence: str,
    scenario_summary: str,
    visit_date: str = "2026-05-12",
    visit_payload_overrides: dict[str, Any] | None = None,
    visibility_expectation: str = "mandatory",
    action_semantic_family: str | None = None,
    supporting_expected_aliases: list[str] | None = None,
    hard_critical: bool = False,
) -> dict[str, Any]:
    oracle: dict[str, Any] = {
        "expected_effective_state": module_id,
        "epic10_scenario_summary": scenario_summary,
        "epic10_evidence": evidence,
        "specificity_policy": "generic_or_specific_ok",
        "visibility_expectation": visibility_expectation,
    }
    if expected_action_label:
        oracle["expected_action_label"] = expected_action_label
    if expected_action_contains:
        oracle["expected_action_contains"] = expected_action_contains
    if expected_selected_therapy_aliases:
        oracle["expected_selected_therapy_aliases"] = expected_selected_therapy_aliases
    if guideline_basis:
        oracle["expected_guideline_basis_any"] = guideline_basis
    if action_semantic_family:
        oracle["action_semantic_family"] = action_semantic_family
    if supporting_expected_aliases:
        oracle["supporting_expected_aliases"] = supporting_expected_aliases
    if hard_critical:
        oracle["hard_critical"] = True

    visit_payload = dict(baseline_payload)
    if visit_payload_overrides:
        visit_payload.update(visit_payload_overrides)

    return _trajectory(
        scenario_id=scenario_id,
        title=title,
        scenario_family="epic10_real_world",
        module_id=module_id,
        baseline_payload=baseline_payload,
        baseline_oracle={"expected_effective_state": module_id},
        visits=[
            _visit(
                visit_date,
                f"EPIC 10 — {scenario_summary}",
                visit_payload,
                oracle,
            ),
        ],
        clinical_oracle=oracle,
    )


def _epic10_real_world_cases() -> list[dict[str, Any]]:
    """10 trayectorias EPIC 10 — real-world representative cases."""
    return [
        # ── #1 Vigilancia activa — NCCN very-low risk ───────────────────
        _epic10(
            scenario_id="epic10_very_low_active_surveillance",
            title="EPIC 10 #1 — VL risk con vigilancia activa PRECISE",
            module_id="localized_initial",
            baseline_payload={
                "psa": 5.8,
                "psad": 0.10,
                "gleason_primary": 3,
                "gleason_secondary": 3,
                "isup_grade": 1,
                "clinical_t_stage": "T1c",
                "clinical_n_stage": "N0",
                "clinical_m_stage": "M0",
                "pirads_score": 2,
                "positive_cores": 1,
                "total_cores": 14,
                "max_core_involvement_pct": 15,
                "prostate_volume_ml": 58,
                "patient_age": 64,
                "ecog": 0,
                "life_expectancy_years": 18,
                "family_history_positive": 0,
                "dre_suspicious": 0,
            },
            expected_action_contains="vigilancia",
            expected_selected_therapy_aliases=["Vigilancia activa", "Active surveillance"],
            guideline_basis=["NCCN 2026 localized very-low risk", "EAU 2026 localized low"],
            evidence="PIVOT (Wilt NEJM 2012, PMID 22808955); ProtecT 15y (Hamdy NEJM 2023, PMID 36912537); PRECISE protocol.",
            scenario_summary="Hombre 64 años, PSA 5.8, Gleason 6, T1c, 1/14 cores 15% — VL risk → AS.",
            action_semantic_family="surveillance",
        ),

        # ── #2 Localized intermediate-favorable — ProtecT / EORTC ──────
        _epic10(
            scenario_id="epic10_intermediate_favorable_definitive_local",
            title="EPIC 10 #2 — IF risk con RP o RT ±ADT corto",
            module_id="localized_initial",
            baseline_payload={
                "psa": 12.0,
                "psad": 0.27,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "clinical_t_stage": "T2a",
                "clinical_n_stage": "N0",
                "clinical_m_stage": "M0",
                "pirads_score": 4,
                "positive_cores": 3,
                "total_cores": 14,
                "max_core_involvement_pct": 40,
                "prostate_volume_ml": 44,
                "patient_age": 66,
                "ecog": 0,
                "life_expectancy_years": 16,
                "briganti_lni_pct": 4.0,
            },
            expected_action_contains="prostatectomía",
            expected_selected_therapy_aliases=[
                "Prostatectomía radical",
                "Radioterapia",
                "RT + ADT 4-6 meses",
            ],
            guideline_basis=["NCCN 2026 localized intermediate-favorable", "EAU 2026 localized intermediate"],
            evidence="ProtecT 15y outcomes (Hamdy NEJM 2023); EORTC 22991 (Bolla Lancet 2010, PMID 20933572).",
            scenario_summary="Hombre 66 años, PSA 12, Gleason 7 (3+4), T2a, Briganti LNI 4% — IF favorable → RP o RT±ADT corto.",
            action_semantic_family="definitive_local",
            hard_critical=True,
        ),

        # ── #3 Localized very-high — STAMPEDE M0 ────────────────────────
        _epic10(
            scenario_id="epic10_very_high_combined_modality",
            title="EPIC 10 #3 — VH risk con RT + LT-ADT 24-36m o RP+LND",
            module_id="localized_initial",
            baseline_payload={
                "psa": 22.0,
                "psad": 0.51,
                "gleason_primary": 4,
                "gleason_secondary": 5,
                "isup_grade": 5,
                "clinical_t_stage": "T3b",
                "clinical_n_stage": "N1",
                "clinical_m_stage": "M0",
                "pirads_score": 5,
                "positive_cores": 8,
                "total_cores": 14,
                "max_core_involvement_pct": 80,
                "prostate_volume_ml": 43,
                "patient_age": 62,
                "ecog": 0,
                "life_expectancy_years": 18,
                "decipher_score": 0.72,
                "psma_pet_done": 1,
                "psma_uptake_pattern": "local_regional",
            },
            expected_action_contains="ADT",
            expected_selected_therapy_aliases=[
                "RT + ADT prolongado",
                "Prostatectomía + linfadenectomía",
                "Terapia combinada",
            ],
            guideline_basis=["NCCN 2026 localized very-high risk", "EAU 2026 high-risk localized"],
            evidence="STAMPEDE M0 high-risk (James Lancet 2022, PMID 35569466); EORTC 22863 (Bolla NEJM 1997).",
            scenario_summary="Hombre 62 años, PSA 22, Gleason 9, T3b N1, Decipher 0.72 — VH risk → RT + LT-ADT 24-36m.",
            action_semantic_family="definitive_local",
            hard_critical=True,
        ),

        # ── #4 Post-RP BCR — GETUG-AFU 16 / RADICALS-RT ─────────────────
        _epic10(
            scenario_id="epic10_post_rp_bcr_salvage_rt_adt",
            title="EPIC 10 #4 — BCR post-RP → salvage RT + ADT",
            module_id="recurrence_bcr",
            baseline_payload={
                "prior_radical_prostatectomy": 1,
                "rp_date": "2025-09-15",
                "psa": 0.8,
                "psa_nadir_post_rp": 0.0,
                "psa_doubling_time_months": 5.2,
                "psa_velocity_ng_ml_year": 1.6,
                "gleason_primary": 4,
                "gleason_secondary": 5,
                "isup_grade": 5,
                "pathologic_t_stage": "pT3a",
                "pathologic_n_stage": "pN0",
                "surgical_margins_positive": 1,
                "extracapsular_extension": 1,
                "seminal_vesicle_invasion": 0,
                "psma_pet_done": 1,
                "psma_uptake_pattern": "local_only",
                "patient_age": 64,
                "ecog": 0,
                "life_expectancy_years": 15,
                "prior_radiation": 0,
            },
            expected_action_contains="salvage",
            expected_selected_therapy_aliases=[
                "Salvage RT + ADT",
                "Radioterapia de salvataje + ADT",
                "RT salvage + ADT 6 meses",
            ],
            guideline_basis=["NCCN 2026 BCR post-RP", "EAU 2026 BCR post-RP"],
            evidence="GETUG-AFU 16 (Carrie Lancet Oncol 2016, PMID 27160474); RADICALS-RT (Parker Lancet 2020, PMID 33002429).",
            scenario_summary="Post-RP pT3a Gleason 9, márgenes+, PSA 0→0.8 con PSADT 5m — Salvage RT + ADT.",
            action_semantic_family="salvage_local",
            hard_critical=True,
        ),

        # ── #5 Post-RT BCR Phoenix met — Salvage prostatectomy ──────────
        _epic10(
            scenario_id="epic10_post_rt_bcr_phoenix_salvage_candidate",
            title="EPIC 10 #5 — BCR post-RT Phoenix met → salvage local",
            module_id="post_radiotherapy_or_local_salvage",
            baseline_payload={
                "prior_radiation": 1,
                "rt_completion_date": "2023-11-20",
                "rt_modality": "External beam IMRT",
                "rt_dose_total_gy": 78,
                "psa_nadir_post_rt": 0.3,
                "psa": 2.5,
                "phoenix_delta": 2.2,
                "psa_doubling_time_months": 6.0,
                "psa_velocity_ng_ml_year": 1.4,
                "gleason_primary": 4,
                "gleason_secondary": 4,
                "isup_grade": 4,
                "biopsy_post_rt_positive": 1,
                "biopsy_post_rt_date": "2026-03-10",
                "patient_age": 68,
                "ecog": 0,
                "life_expectancy_years": 12,
                "psma_pet_done": 1,
                "psma_uptake_pattern": "local_only",
                "conventional_imaging_status": "M0",
                "prior_radical_prostatectomy": 0,
            },
            expected_action_contains="salvage",
            expected_selected_therapy_aliases=[
                "Salvage prostatectomy",
                "Prostatectomía de rescate",
                "Brachytherapy salvage",
                "Salvage local therapy",
            ],
            guideline_basis=["NCCN 2026 BCR post-RT", "EAU 2026 BCR post-RT", "AUA/ASTRO/SUO Salvage 2024"],
            evidence="AUA/ASTRO/SUO Salvage 2024; Phoenix criterion (Roach IJROBP 2006, PMID 16798415); ASTRO Phoenix.",
            scenario_summary="Post-RT IMRT 78Gy, nadir 0.3 → 2.5 (Phoenix met), biopsia + Gleason 8 — Salvage local candidate.",
            action_semantic_family="salvage_local",
            hard_critical=True,
        ),

        # ── #6 mHSPC high volume sync — ARASENS / PEACE-1 ───────────────
        _epic10(
            scenario_id="epic10_mhspc_high_volume_sync_triplet",
            title="EPIC 10 #6 — mHSPC alto volumen sincrónico → triplete",
            module_id="mcspc_high_volume_sync",
            baseline_payload={
                "psa": 185.0,
                "gleason_primary": 4,
                "gleason_secondary": 4,
                "isup_grade": 4,
                "clinical_t_stage": "T4",
                "clinical_n_stage": "N1",
                "clinical_m_stage": "M1b",
                "metastasis_site": "Bone",
                "metastasis_count": 8,
                "bone_axial_count": 4,
                "bone_appendicular_count": 4,
                "visceral_metastasis_present": 1,
                "visceral_metastasis_sites": ["liver"],
                "volume_disease": "High",
                "metachronous_disease": 0,
                "patient_age": 65,
                "ecog": 0,
                "docetaxel_fit": 1,
                "anc": 3200,
                "platelets": 240000,
                "hemoglobin": 13.0,
                "alt": 24,
                "ast": 26,
                "alp": 180,
                "bilirubin": 0.7,
                "performance_status_driver": "cancer_related",
                "drug_interaction_reviewed": 1,
                "peripheral_neuropathy_grade": 0,
                "nyha_class": "I",
                "lvef_percent": 60,
                "qtc_baseline_ms": 420,
                "child_pugh": "A",
                "testosterone": 480,
                "current_adt_context": "none",
            },
            expected_action_contains="Docetaxel",
            expected_selected_therapy_aliases=[
                "ADT + docetaxel + darolutamida",
                "ADT + docetaxel + abiraterona",
                "Triplete",
            ],
            guideline_basis=["NCCN 2026 mHSPC high volume", "EAU 2026 mHSPC"],
            evidence="ARASENS (Smith NEJM 2022, PMID 35179323); PEACE-1 (Fizazi Lancet 2022, PMID 35405085); CHAARTED (Sweeney NEJM 2015, PMID 26244877).",
            scenario_summary="De novo M1b alto volumen (8 bone + visceral), ECOG 0, fit docetaxel — Triplete ARASENS o PEACE-1.",
            action_semantic_family="systemic_intensified",
            hard_critical=True,
        ),

        # ── #7 mHSPC oligometacrónico — STAMPEDE-H / STOMP ──────────────
        _epic10(
            scenario_id="epic10_mhspc_oligometachronous_mdt_sbrt",
            title="EPIC 10 #7 — mHSPC oligometacrónico → MDT/SBRT + ADT+ARPI",
            module_id="mcspc_oligo_metachronous",
            baseline_payload={
                "psa": 12.0,
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "isup_grade": 3,
                "prior_radical_prostatectomy": 1,
                "rp_date": "2023-02-10",
                "metachronous_disease": 1,
                "time_to_metastasis_months": 38,
                "metastasis_site": "Bone",
                "metastasis_count": 3,
                "bone_axial_count": 3,
                "bone_appendicular_count": 0,
                "visceral_metastasis_present": 0,
                "volume_disease": "Low",
                "psma_pet_done": 1,
                "psma_uptake_pattern": "multifocal",
                "psma_rads_score": "4",
                "patient_age": 67,
                "ecog": 0,
                "current_adt_context": "none",
                "testosterone": 510,
            },
            expected_action_contains="ADT",
            expected_selected_therapy_aliases=[
                "ADT + enzalutamida",
                "ADT + apalutamida",
                "Metastasis-directed therapy",
                "SBRT",
                "MDT",
            ],
            supporting_expected_aliases=["Metastasis-directed therapy", "MDT", "SBRT"],
            guideline_basis=["NCCN 2026 mHSPC oligometastatic", "EAU 2026 mHSPC oligo"],
            evidence="STAMPEDE-H RT al primario (Parker Lancet 2018, PMID 30355464); STOMP (Ost JCO 2018, PMID 29240541); ORIOLE (Phillips JAMA Oncol 2020).",
            scenario_summary="Post-RP 38m, oligometacrónico 3 bone axiales — MDT/SBRT + ADT + ARPI.",
            action_semantic_family="mdt_candidate",
            visibility_expectation="supporting",
        ),

        # ── #8 m0CRPC high-risk PSADT — ARAMIS / SPARTAN / PROSPER ─────
        _epic10(
            scenario_id="epic10_m0crpc_high_risk_arpi",
            title="EPIC 10 #8 — m0CRPC PSADT <10m → ARPI",
            module_id="m0_crpc",
            baseline_payload={
                "psa": 4.8,
                "psa_doubling_time_months": 8.2,
                "psa_velocity_ng_ml_year": 6.4,
                "testosterone": 28,
                "current_adt_context": "medical_adt_continuous",
                "adt_start_date": "2023-12-05",
                "imaging_negative": 1,
                "conventional_imaging_status": "M0",
                "conventional_imaging_modality": "TC + gammagrama óseo",
                "progression_pattern": "biochemical_only",
                "prior_radical_prostatectomy": 1,
                "rp_date": "2022-05-10",
                "patient_age": 71,
                "ecog": 0,
                "life_expectancy_years": 12,
                "nyha_class": "I",
                "lvef_percent": 58,
                "qtc_baseline_ms": 430,
                "child_pugh": "A",
                "anc": 3800,
                "platelets": 230000,
                "hemoglobin": 13.2,
            },
            expected_action_contains="Darolutamida",
            expected_selected_therapy_aliases=[
                "Darolutamida",
                "Apalutamida",
                "Enzalutamida",
                "ARPI + ADT",
            ],
            guideline_basis=["NCCN 2026 nmCRPC / m0CRPC", "EAU 2026 nmCRPC"],
            evidence="ARAMIS (Fizazi NEJM 2020, PMID 32905676); SPARTAN (Smith NEJM 2018, PMID 29420164); PROSPER (Hussain NEJM 2018, PMID 29949494).",
            scenario_summary="m0CRPC, ADT 18m, PSADT 8.2m, conventional imaging M0 — Daro/Apa/Enza.",
            action_semantic_family="systemic_arpi",
            hard_critical=True,
        ),

        # ── #9 m1CRPC BRCA2+ PSMA-PET+ — PROfound / VISION ──────────────
        _epic10(
            scenario_id="epic10_m1crpc_brca2_olaparib_or_lu177",
            title="EPIC 10 #9 — m1CRPC BRCA2+ PSMA-PET+ → PARPi o Lu-177",
            module_id="m1_crpc",
            baseline_payload={
                "psa": 65.0,
                "testosterone": 18,
                "current_adt_context": "medical_adt_continuous",
                "prior_adt_arpi": 1,
                "prior_arpi_type": "abiraterone",
                "prior_arpi_duration_months": 18,
                "prior_docetaxel_cycles": 0,
                "line_of_therapy_number": 2,
                "imaging_negative": 0,
                "conventional_imaging_status": "M1",
                "metastasis_site": "Bone",
                "metastasis_count": 6,
                "bone_axial_count": 4,
                "bone_appendicular_count": 2,
                "visceral_metastasis_present": 0,
                "psma_pet_done": 1,
                "psma_uptake_pattern": "diffuse",
                "psma_suvmax_lesion": 18.0,
                "psma_suvmax_liver": 6.0,
                "germline_hrr_positive": 1,
                "brca2_positive": 1,
                "msi_high": 0,
                "patient_age": 67,
                "ecog": 1,
                "life_expectancy_years": 5,
                "nyha_class": "I",
                "lvef_percent": 55,
                "child_pugh": "A",
                "anc": 2200,
                "platelets": 180000,
                "hemoglobin": 11.8,
                "arv7_positive": 0,
            },
            expected_action_contains="Olaparib",
            expected_selected_therapy_aliases=[
                "Olaparib",
                "Lu-177 PSMA-617",
                "Lutecio-177",
                "Talazoparib",
                "Niraparib",
            ],
            guideline_basis=["NCCN 2026 mCRPC HRR+", "EAU 2026 mCRPC genomic"],
            evidence="PROfound (de Bono NEJM 2020, PMID 32343890); VISION (Sartor NEJM 2021, PMID 34161051); PROpel (Saad Lancet Oncol 2023).",
            scenario_summary="m1CRPC post-ADT+abi, BRCA2+, PSMA-PET SUV 18 (>liver 6) — Olaparib o Lu-177.",
            action_semantic_family="systemic_targeted",
            hard_critical=True,
        ),

        # ── #10 m1CRPC heavily pretreated AR-V7+ — PROPHECY ─────────────
        _epic10(
            scenario_id="epic10_m1crpc_endline_arv7_reassessment",
            title="EPIC 10 #10 — m1CRPC heavily pre-treated AR-V7+ → re-evaluación",
            module_id="m1_crpc",
            baseline_payload={
                "psa": 145.0,
                "testosterone": 14,
                "current_adt_context": "medical_adt_continuous",
                "prior_adt_arpi": 1,
                "prior_arpi_type": "enzalutamide",
                "prior_arpi_duration_months": 14,
                "prior_docetaxel_cycles": 8,
                "prior_cabazitaxel_cycles": 6,
                "line_of_therapy_number": 4,
                "imaging_negative": 0,
                "conventional_imaging_status": "M1",
                "metastasis_site": "Bone",
                "metastasis_count": 12,
                "bone_axial_count": 8,
                "bone_appendicular_count": 4,
                "visceral_metastasis_present": 1,
                "visceral_metastasis_sites": ["liver", "lung"],
                "psma_pet_done": 1,
                "psma_uptake_pattern": "heterogeneous",
                "psma_suvmax_lesion": 9.0,
                "psma_suvmax_liver": 5.0,
                "germline_hrr_positive": 0,
                "brca2_positive": 0,
                "msi_high": 0,
                "arv7_positive": 1,
                "ddr_alteration": 0,
                "patient_age": 73,
                "ecog": 2,
                "life_expectancy_years": 2,
                "anc": 1600,
                "platelets": 110000,
                "hemoglobin": 9.8,
                "alp": 420,
                "ldh": 380,
            },
            expected_action_contains="re",
            expected_selected_therapy_aliases=[
                "Re-evaluación multidisciplinaria",
                "Best supportive care",
                "Ensayo clínico",
                "Pembrolizumab + enzalutamida",
                "Reevaluación oncológica",
            ],
            guideline_basis=["NCCN 2026 mCRPC end-line", "EAU 2026 mCRPC late line"],
            evidence="PROPHECY (Armstrong JAMA Oncol 2019, PMID 31265030); KEYNOTE-365 (Yu JCO 2023, PMID 37207300); CARD (de Wit NEJM 2019).",
            scenario_summary="m1CRPC L4, AR-V7+, post-docetaxel+cabazitaxel, ECOG 2, visceral hepatic — re-evaluación / ensayo.",
            action_semantic_family="systemic_late_line",
        ),
    ]


__all__ = [
    "_epic10_real_world_cases",
]
