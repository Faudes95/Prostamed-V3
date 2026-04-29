from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any


def _recent_date(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


SCENARIO_LIBRARY = [
    {
        "scenario_id": "diagnostic_low_surveillance",
        "title": "Estudio diagnostico con sospecha baja y seguimiento corto",
        "module_id": "diagnostic_workup",
        "payload": {
            "age": 61,
            "psa": 4.4,
            "psad": 0.08,
            "dre_suspicious": 0,
            "pirads_score": 2,
            "family_history_positive": 0,
            "germline_risk_mutation": 0,
            "psa_velocity_ng_ml_year": 0.2,
        },
        "expected_state": "diagnostic_workup",
        "expected_label_contains": "baja",
    },
    {
        "scenario_id": "diagnostic_high_biopsy",
        "title": "Estudio diagnostico con biopsia inmediata",
        "module_id": "diagnostic_workup",
        "payload": {
            "age": 67,
            "psa": 10.8,
            "psad": 0.22,
            "dre_suspicious": 1,
            "pirads_score": 4,
            "family_history_positive": 1,
            "germline_risk_mutation": 0,
            "psa_velocity_ng_ml_year": 0.9,
            "planned_biopsy_route": "Transperineal",
        },
        "expected_state": "diagnostic_workup",
        "expected_label_contains": "alta",
        "expected_treatment_contains": "Biopsia dirigida",
    },
    {
        "scenario_id": "benign_followup_low",
        "title": "Seguimiento conservador despues de biopsia benigna",
        "module_id": "post_negative_biopsy_followup",
        "payload": {
            "psa": 4.2,
            "psad": 0.09,
            "pirads_score": 0,
            "dre_suspicious": 0,
            "years_since_negative_biopsy": 2,
            "family_history_positive": 0,
            "prior_biopsy_count": 1,
        },
        "expected_state": "post_negative_biopsy_followup",
        "expected_label_contains": "baja intensidad",
    },
    {
        "scenario_id": "benign_followup_reopen",
        "title": "Reapertura diagnostica despues de biopsia benigna",
        "module_id": "post_negative_biopsy_followup",
        "payload": {
            "psa": 8.9,
            "psad": 0.17,
            "pirads_score": 4,
            "dre_suspicious": 1,
            "years_since_negative_biopsy": 1,
            "post_biopsy_mri": 1,
            "persistent_lesion_signal": 1,
            "prior_biopsy_count": 2,
            "prior_biopsy_mri_targeted": 0,
        },
        "expected_state": "post_negative_biopsy_followup",
        "expected_label_contains": "reapertura",
        "expected_treatment_contains": "Reabrir estudio",
    },
    {
        "scenario_id": "localized_low_as",
        "title": "Enfermedad localizada de bajo riesgo con vigilancia activa",
        "module_id": "localized_initial",
        "payload": {
            "age": 62,
            "life_expectancy_years": 18,
            "psa": 5.1,
            "psad": 0.1,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "percent_pattern_4": 0,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "2",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "nodal_status": "N0",
            "metastasis_site": "M0",
            "baseline_urinary_qol": 88,
            "baseline_sexual_qol": 80,
            "baseline_bowel_qol": 92,
        },
        "expected_state": "localized_initial",
        # Etiqueta oficial en español ("Bajo"); la calibración compara sin acentos.
        "expected_label_contains": "bajo",
        "expected_treatment_contains": "Vigilancia activa",
    },
    {
        "scenario_id": "localized_unfavorable",
        "title": "Enfermedad localizada intermedia desfavorable",
        "module_id": "localized_initial",
        "payload": {
            "age": 68,
            "life_expectancy_years": 14,
            "psa": 9.6,
            "psad": 0.19,
            "clinical_tstage": "T2b",
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "num_cores_positive": 6,
            "total_cores": 12,
            "max_core_involvement": 0.45,
            "percent_pattern_4": 25,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "4",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 0,
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
        "expected_state": "localized_initial",
        # Etiqueta oficial en español: "Intermedio desfavorable".
        "expected_label_contains": "desfavorable",
        "expected_treatment_contains": "Radioterapia",
    },
    {
        "scenario_id": "localized_variant_escalate",
        "title": "Enfermedad localizada con variante agresiva que requiere escalamiento",
        "module_id": "localized_initial",
        "payload": {
            "age": 64,
            "life_expectancy_years": 16,
            "psa": 7.2,
            "psad": 0.13,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "max_core_involvement": 0.3,
            "percent_pattern_4": 15,
            "prior_mpmri": 1,
            "confirmatory_biopsy_planned": 1,
            "adverse_histology_variant_type": "small_cell_neuroendocrine",
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
        "expected_state": "localized_initial",
        "expected_requires_review": True,
    },
    {
        "scenario_id": "adt_progression_pending_verification",
        "title": "Progresión bioquímica bajo ADT sin castración confirmada",
        "module_id": "adt_progression_verification",
        "payload": {
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "not_restaged",
            "psa_current": 1.2,
            "psadt_months": 8,
            "prior_local_therapy_context": "prostatectomy",
        },
        "expected_state": "adt_progression_verification",
        "expected_label_contains": "verificación",
    },
    {
        "scenario_id": "adt_progression_confirmed_m0",
        "title": "Progresión bajo ADT con castración confirmada e imagen M0",
        "module_id": "adt_progression_verification",
        "payload": {
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 17,
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "psa_current": 2.1,
            "psadt_months": 7,
        },
        "expected_state": "adt_progression_verification",
        "expected_treatment_contains": "M0 CRPC",
    },
    {
        "scenario_id": "post_rp_surveillance",
        "title": "Post-prostatectomia sin senales de rescate inmediato",
        "module_id": "post_prostatectomy",
        "payload": {
            "psa": 8.4,
            "psa_postop": 0.02,
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "pathologic_stage": "pT2",
            "surgical_margin": 0,
            "ece_status": 0,
            "svi_status": 0,
            "lni_status": 0,
            "eligible_pelvic_therapy": 1,
            "time_to_recurrence_months": 0,
        },
        "expected_state": "post_prostatectomy",
        # El módulo post_prostatectomy emite `nccn_primary.label` en inglés
        # (p. ej. "Post-RP surveillance", simétrico a "Adverse pathology under
        # surveillance" del escenario post_rp_adverse). La recomendación en
        # español vive en `tratamiento_principal`/`recommendation_family`.
        "expected_label_contains": "surveillance",
    },
    {
        "scenario_id": "post_rp_adverse",
        "title": "Post-prostatectomia con patologia adversa",
        "module_id": "post_prostatectomy",
        "payload": {
            "psa": 13.2,
            "psa_postop": 0.04,
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "pathologic_stage": "pT3a",
            "surgical_margin": 1,
            "ece_status": 1,
            "svi_status": 0,
            "lni_status": 0,
            "decipher_risk": "Alto",
            "eligible_pelvic_therapy": 1,
            "time_to_recurrence_months": 10,
        },
        "expected_state": "post_prostatectomy",
        "expected_label_contains": "adverse",
    },
    {
        "scenario_id": "recurrence_post_rp_salvage",
        "title": "Recurrencia bioquimica posterior a prostatectomia con rescate",
        "module_id": "recurrence_bcr",
        "payload": {
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "bcr2": 0,
            "psa_current": 0.45,
            "psadt_months": 8,
            "conventional_imaging_m0": 1,
            "eligible_pelvic_therapy": 1,
            "salvage_local_feasible": 1,
            "psma_pet_done": 0,
        },
        "expected_state": "recurrence_bcr",
        "expected_label_contains": "post-rp",
        "expected_treatment_contains": "radioterapia de rescate",
    },
    {
        "scenario_id": "recurrence_bcr2_embark",
        "title": "Segunda recurrencia bioquimica tipo EMBARK",
        "module_id": "recurrence_bcr",
        "payload": {
            "prior_prostatectomy": 1,
            "prior_radiation": 0,
            "bcr2": 1,
            "psa_current": 0.7,
            "psadt_months": 7,
            "conventional_imaging_m0": 1,
            "eligible_pelvic_therapy": 0,
            "salvage_local_feasible": 0,
            "local_salvage_candidate": 0,
            "prior_secondary_rt": 1,
        },
        "expected_state": "recurrence_bcr",
        "expected_label_contains": "bcr2",
        "expected_treatment_contains": "Enzalutamida",
    },
    {
        "scenario_id": "mcspc_oligo_metachronous_mdt",
        "title": "mCSPC oligometastasico metacronico con MDT candidata",
        "module_id": "mcspc_oligo_metachronous",
        "payload": {
            "metastasis_site": "Bone",
            "metastasis_count": 2,
            "ecog_score": 0,
            "child_pugh_score": "A",
            "frailty_status": "Fit",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "molecular_assay_source": "Tejido",
            "molecular_assay_date": "2026-02-10",
            "brca2_status": "Negativo",
            "hrr_gene": "ATM",
            "mdt_context": "Discusión multidisciplinaria",
        },
        "expected_state": "mcspc_oligo_metachronous",
        "expected_treatment_contains": "Metastasis-directed therapy",
    },
    {
        "scenario_id": "mcspc_low_volume_sync_rt",
        "title": "mCSPC bajo volumen sincronico con radioterapia al primario",
        "module_id": "mcspc_low_volume_sync_oligo",
        "payload": {
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "ecog_score": 0,
            "child_pugh_score": "A",
            "frailty_status": "Fit",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "primary_local_treatment_done": 0,
            "molecular_assay_source": "Tejido",
            "molecular_assay_date": "2026-02-11",
            "brca2_status": "Negativo",
            "hrr_gene": "BRCA1",
        },
        "expected_state": "mcspc_low_volume_sync_oligo",
        "expected_treatment_contains": "RT al primario",
    },
    {
        "scenario_id": "mcspc_high_volume_triplet_fit",
        "title": "mCSPC alto volumen sincrónico fit para discusión de triplete",
        "module_id": "mcspc_high_volume",
        "payload": {
            "metastasis_site": "Bone",
            "metastasis_count": 7,
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "pelvis_sacrum", "lesion_count": 6},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "performance_status_driver": "cancer_related",
            "child_pugh_score": "A",
            "frailty_status": "Fit",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "anc": 2500,
            "platelets": 220000,
            "hemoglobin": 13.5,
            "alt": 25,
            "ast": 22,
            "alp": 90,
            "bilirubin": 0.8,
            "cbc_date": _recent_date(3),
            "liver_panel_date": _recent_date(3),
            "dxa_baseline_done": 1,
            "calcium_vitd_started": 1,
        },
        "expected_state": "mcspc_high_volume",
        "expected_treatment_contains": "Docetaxel",
    },
    {
        "scenario_id": "mcspc_high_volume_akeega",
        "title": "mCSPC alto volumen BRCA2 trazable",
        "module_id": "mcspc_high_volume",
        "payload": {
            "metastasis_site": "Bone",
            "metastasis_count": 6,
            "volume_disease": "High",
            "bone_site_entries": [
                {"site_key": "pelvis_sacrum", "lesion_count": 5},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "ecog_score": 1,
            # Guard TX-1 (FAUBOT): la fitness para docetaxel debe ser explícita
            # para que el módulo pueda comparar triplete vs AKEEGA en un paciente
            # fit BRCA2+. Sin esta bandera el engine no podía confirmar si el
            # paciente era o no elegible a quimio, y la trayectoria AKEEGA quedaba
            # ambigua (FAUBOT FASE 2 TX-1).
            "docetaxel_fit": 1,
            "performance_status_driver": "cancer_related",
            "peripheral_neuropathy_grade": 0,
            "drug_interaction_reviewed": 1,
            "anc": 2400,
            "platelets": 215000,
            "hemoglobin": 13.1,
            "alt": 24,
            "ast": 21,
            "alp": 88,
            "bilirubin": 0.7,
            "cbc_date": _recent_date(3),
            "liver_panel_date": _recent_date(3),
            "child_pugh_score": "A",
            "frailty_status": "Fit",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "molecular_assay_source": "Tejido",
            "molecular_assay_date": "2026-02-12",
            "brca2_status": "Positivo",
            "hrr_gene": "BRCA2",
            "brca2_origin": "germline",
            "dxa_baseline_done": 1,
            "calcium_vitd_started": 1,
        },
        "expected_state": "mcspc_high_volume",
        "expected_treatment_contains": "Niraparib",
    },
    {
        "scenario_id": "m0_crpc_high_risk",
        "title": "M0 CRPC de alto riesgo con testosterona confirmada",
        "module_id": "m0_crpc",
        "payload": {
            "psadt_months": 6,
            "castrate_testosterone_confirmed": 1,
            "imaging_negative": 1,
            "current_adt_context": "medical_adt_continuous",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "conventional_imaging_modality": "CT + bone scan",
            "conventional_imaging_date": _recent_date(5),
            "comorbidity_seizure": 1,
        },
        "expected_state": "m0_crpc",
        "expected_label_contains": "m0 crpc",
        "expected_treatment_contains": "Darolutamida",
    },
    {
        "scenario_id": "m1_crpc_post_taxane_card_vision",
        "title": "m1 CRPC pos-taxano con CARD y VISION aplicables",
        "module_id": "m1_crpc",
        "payload": {
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "docetaxel_fit": 1,
            "chemotherapy_delay_candidate": 0,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
            "prior_therapy": "Abiraterona, Docetaxel",
            "prior_docetaxel_cycles": 6,
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "molecular_report_date": "2026-02-13",
            "brca2_status": "Positivo",
            "tmb_high": 1,
            "msi_status": "estable",
            "metastasis_site": "Bone",
        },
        "expected_state": "m1_crpc",
        "expected_treatment_contains": "Cabazitaxel",
    },
    {
        "scenario_id": "m1_crpc_escalate_variant",
        "title": "m1 CRPC con rasgos neuroendocrinos que obliga revision humana",
        "module_id": "m1_crpc",
        "payload": {
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "later_line",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
            "prior_therapy": "Enzalutamida",
            "neuroendocrine_features": 1,
            "metastasis_site": "Visceral",
        },
        "expected_state": "m1_crpc",
        "expected_requires_review": True,
    },
]


def scenario_axes() -> dict[str, list[str]]:
    return {
        "diagnostic_workup": [
            "sospecha baja/intermedia/alta",
            "MRI ausente/suboptima/adecuada",
            "PSAD baja/intermedia/alta",
            "biopsia inmediata vs revaloracion",
        ],
        "post_negative_biopsy_followup": [
            "seguimiento pasivo vs reapertura",
            "lesion persistente",
            "biopsia previa dirigida o no",
        ],
        "localized_initial": [
            "vigilancia activa clara/limítrofe/no candidata",
            "riesgo bajo/intermedio desfavorable/alto",
            "variantes agresivas y genómica externa",
        ],
        "post_prostatectomy": [
            "vigilancia rutinaria",
            "patologia adversa",
            "persistencia/recurrencia temprana",
        ],
        "recurrence_bcr": [
            "post-RP",
            "post-RT",
            "BCR2 tipo EMBARK",
        ],
        "adt_progression_verification": [
            "castración no confirmada vs confirmada",
            "fracaso de supresión androgénica",
            "redirección a M0 CRPC o M1 CRPC",
        ],
        "mcspc_oligo_metachronous": ["MDT", "dobletes", "AKEEGA trazable"],
        "mcspc_low_volume_sync_oligo": ["RT al primario", "dobletes", "AKEEGA trazable"],
        "mcspc_high_volume": ["tripletes", "AKEEGA trazable", "salud osea"],
        "m0_crpc": ["castracion confirmada", "PSADT >10 vs <=10", "riesgo convulsivo"],
        "m1_crpc": ["pre-taxano", "post-taxano", "PARP", "PSMA", "inmunoterapia", "escalamiento por variante"],
    }


def _contains_treatment(result: dict[str, Any], needle: str) -> bool:
    lower = needle.lower()
    for item in result.get("eligible_treatments", []) or []:
        if isinstance(item, str) and lower in item.lower():
            return True
        if isinstance(item, dict) and lower in str(item.get("name", "")).lower():
            return True
    return False


def run_scenario_harness(registry: Any) -> dict[str, Any]:
    cases = []
    module_summary: dict[str, dict[str, Any]] = {}
    passed_cases = 0

    for scenario in SCENARIO_LIBRARY:
        payload = deepcopy(scenario["payload"])
        result = registry.evaluate_module(scenario["module_id"], payload)
        issues: list[str] = []
        if result.get("state") != scenario["expected_state"]:
            issues.append(f"Estado esperado {scenario['expected_state']} y recibido {result.get('state')}.")
        expected_label = scenario.get("expected_label_contains")
        if expected_label:
            label = str((result.get("nccn_primary", {}) or {}).get("label", "")).lower()
            if expected_label.lower() not in label:
                issues.append(f"Etiqueta principal inesperada: {label or 'vacia'}.")
        expected_treatment = scenario.get("expected_treatment_contains")
        if expected_treatment and not _contains_treatment(result, expected_treatment):
            issues.append(f"No aparecio el tratamiento esperado: {expected_treatment}.")
        expected_requires_review = scenario.get("expected_requires_review")
        if expected_requires_review is not None:
            actual = bool((result.get("decision_quality", {}) or {}).get("requires_human_review"))
            if actual != expected_requires_review:
                issues.append(f"requires_human_review esperado {expected_requires_review} y recibido {actual}.")

        passed = not issues
        if passed:
            passed_cases += 1

        case_item = {
            "scenario_id": scenario["scenario_id"],
            "title": scenario["title"],
            "module_id": scenario["module_id"],
            "passed": passed,
            "issues": issues,
            "state": result.get("state"),
            "recommendation_family": (result.get("decision_quality", {}) or {}).get("recommendation_family", ""),
            "confidence_category": (result.get("decision_quality", {}) or {}).get("confidence_category", ""),
        }
        cases.append(case_item)

        summary = module_summary.setdefault(
            scenario["module_id"],
            {"module_id": scenario["module_id"], "total": 0, "passed": 0, "failed": 0},
        )
        summary["total"] += 1
        summary["passed"] += 1 if passed else 0
        summary["failed"] += 0 if passed else 1

    total_cases = len(cases)
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "concordance_pct": round((passed_cases / total_cases) * 100, 1) if total_cases else 0.0,
        "target_definition": "100% de concordancia dentro de la biblioteca validada de escenarios soportados.",
        "scenario_axes": scenario_axes(),
        "module_summary": list(module_summary.values()),
        "cases": cases,
    }
