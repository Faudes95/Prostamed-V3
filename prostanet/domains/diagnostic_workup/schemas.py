from __future__ import annotations

from prostanet.shared.advanced_support_fields import (
    advanced_staging_imaging_fields,
    oncologic_emergency_fields,
    pivotal_gate_supporting_fields,
    pre_biopsy_diagnostic_fields,
    provisional_diagnosis_fields,
)
from prostanet.shared.contracts import FieldSpec, module_schema

INDEX_LESION_LOCATION_OPTIONS = [
    "No especificada",
    "Zona periférica posterior",
    "Zona periférica anterior",
    "Zona de transición",
    "Estroma fibromuscular anterior",
    "Base",
    "Tercio medio",
    "Ápice",
    "Multifocal u otra",
]


DIAGNOSTIC_WORKUP_SCHEMA = module_schema(
    "diagnostic_workup",
    "Estudio diagnóstico antes de confirmar cáncer de próstata",
    "Valora la sospecha de cáncer clínicamente significativo antes de emitir una recomendación terapéutica formal.",
    fields=[
        FieldSpec("age", "Edad", "number", default=62, group="Contexto clínico", group_order=1, clinical_role="decision_refiner", unit="años"),
        FieldSpec("life_expectancy_years", "Esperanza de vida", "number", default=15, group="Contexto clínico", group_order=1, clinical_role="decision_refiner", unit="años", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", default=8, group="Contexto clínico", group_order=1, clinical_role="monitoring", unit="0-35", evidence_tags=["qol"]),
        FieldSpec("psa", "Antígeno prostático específico (PSA)", "number", required=True, default=5.8, group="Sospecha actual", group_order=2, clinical_role="required", unit="ng/mL", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("repeat_psa_value", "PSA repetido", "number", default="", group="Sospecha actual", group_order=2, clinical_role="decision_refiner", unit="ng/mL", evidence_tags=["eau_2026", "psa_confirmation"]),
        FieldSpec("repeat_psa_date", "Fecha de PSA repetido", "date", group="Sospecha actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confirmation"]),
        FieldSpec("repeat_psa_reason_not_done", "Motivo para no repetir PSA", "text", default="", group="Sospecha actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confirmation"]),
        FieldSpec("psad", "Densidad del antígeno prostático específico (PSAD)", "number", default="", group="Sospecha actual", group_order=2, clinical_role="required", unit="ng/mL/cc", derived_from=["psa", "prostate_volume_ml"], evidence_tags=["psad"]),
        FieldSpec("psa_velocity_ng_ml_year", "Velocidad de PSA", "number", default=0.8, group="Sospecha actual", group_order=2, clinical_role="decision_refiner", unit="ng/mL/año", evidence_tags=["psa_kinetics"]),
        FieldSpec("psa_history_interval_months", "Intervalo de la serie de PSA", "number", default=12, group="Sospecha actual", group_order=2, clinical_role="monitoring", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("dre_finding", "Hallazgo al tacto rectal (estadio T)", "select", options=["Normal", "T1 - No palpable (detectado por PSA)", "T2a - Afecta ≤50% de un lóbulo", "T2b - Afecta >50% de un lóbulo", "T2c - Afecta ambos lóbulos", "T3 - Extensión fuera de la cápsula", "T4 - Invade órganos adyacentes"], default="Normal", group="Exploración clínica", group_order=3, clinical_role="required", evidence_tags=["nccn_primary"]),
        FieldSpec("pirads_score", "Resultado de resonancia magnética multiparamétrica", "select", options=["No disponible", "0", "2", "3", "4", "5"], default="No disponible", group="Imagen prostática", group_order=4, clinical_role="required", evidence_tags=["mpmri"], conditional_visibility={'mri_done': ['1', 'yes']}),
        FieldSpec("mpmri_date", "Fecha de resonancia magnética multiparamétrica", "date", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("mpmri_quality", "Calidad de resonancia magnética multiparamétrica", "select", options=["No disponible", "Subóptima", "Adecuada"], default="Adecuada", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("index_lesion_location", "Localización de la lesión índice", "select", options=INDEX_LESION_LOCATION_OPTIONS, default="No especificada", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("index_lesion_size_mm", "Tamaño de la lesión índice", "number", default="", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", unit="mm", evidence_tags=["mpmri"]),
        FieldSpec("prostate_volume_ml", "Volumen prostático", "number", default="", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", unit="mL", evidence_tags=["psad", "mpmri"]),
        FieldSpec("planned_biopsy_type", "Tipo de biopsia prevista", "select", options=["Dirigida + sistemática", "Dirigida", "Sistemática", "Pendiente"], default="Pendiente", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
        FieldSpec("planned_biopsy_route", "Vía de biopsia prevista", "select", options=["Transperineal", "Transrectal", "No definida"], default="No definida", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
        FieldSpec("risk_calculator_pathway", "Calculadora de riesgo o pathway MRI+PSAD", "select", options=["No usado", "EAU MRI + PSAD", "Calculadora externa"], default="No usado", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["benchmark", "eau_2026"], benchmark_note="Permite acercar el producto a pathways MRI + PSAD y calculadoras de riesgo sin sustituir la guía."),
        FieldSpec("family_history_positive", "Historia familiar relevante", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        FieldSpec("family_history_detail", "Detalle de historia familiar", "text", default="", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        FieldSpec("germline_risk_mutation", "Mutación germinal de riesgo conocida", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["germline"]),
        FieldSpec("germline_status", "Sospecha o resultado germinal", "select", options=["Desconocido", "Sospechado", "Conocido"], default="Desconocido", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["germline"]),
        FieldSpec("prior_negative_biopsy", "Biopsia prostática previa benigna", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        # EPIC 9 Group F (GAP-12) — Confundentes del PSA (EAU Diagnostic Evaluation 2026).
        # Todos declarados como `decision_refiner` con default retrocompatible ("0" / "No"),
        # consumidos por `rules_nccn.py` para aplicar corrección PSA×2 (5-ARI) o emitir
        # caveat narrativo (UTI/prostatitis, retención urinaria, eyaculación reciente,
        # asay diferente). No alteran la superficie pública del schema existente.
        FieldSpec("ari_medication_active", "Inhibidor 5-α-reductasa activo (finasteride/dutasteride)", "select", options=["0", "1"], default="0", group="Factores de confusión del PSA", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confounder"]),
        FieldSpec("uti_prostatitis_recent", "ITU o prostatitis aguda en los últimos 3 meses", "select", options=["0", "1"], default="0", group="Factores de confusión del PSA", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confounder"]),
        FieldSpec("urinary_retention_recent", "Retención urinaria o sondaje vesical reciente", "select", options=["0", "1"], default="0", group="Factores de confusión del PSA", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confounder"]),
        FieldSpec("recent_ejaculation_48h", "Eyaculación en las últimas 48 horas del PSA", "select", options=["0", "1"], default="0", group="Factores de confusión del PSA", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confounder"]),
        FieldSpec("psa_same_lab_assay", "PSA comparado con mismo laboratorio y misma técnica", "select", options=["0", "1"], default="1", group="Factores de confusión del PSA", group_order=2, clinical_role="decision_refiner", evidence_tags=["eau_2026", "psa_confirmation"]),
        # ── Imagenología de estadificación M (PSMA / GGO / TAC / RM) ──
        # NCCN PROS-2 v5.2026 cat 1; EAU 2026 §6.4.1-6.4.3.
        # ProPSMA (Hofman 2020) → PSMA PET/CT preferente sobre imagen convencional.
        # En diagnostic_workup el módulo informa qué falta sin bloquear (sin role required).
        *advanced_staging_imaging_fields(
            psma_pet_done_role="decision_refiner",
            bone_scan_done_role="decision_refiner",
            cross_sectional_role="decision_refiner",
            include_local_invasion=False,
        ),
        # ── Triaje pre-biopsia (Brecha 2026-04-23) ─────────────────────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # Detecta compresión medular, hidronefrosis bilateral, hipercalcemia,
        # hematuria severa, retención refractaria, fractura patológica para
        # cualquier paciente — incluso pre-histología.
        *oncologic_emergency_fields(role="decision_refiner"),
        # ── Estado pre-biopsia + características DRE detalladas ─────────
        # NCCN PROS-1 v5.2026 + EAU §6.5.4. Define cT4 fijo+pétreo y vía
        # de biopsia (transperineal preferente si próstata fija).
        *pre_biopsy_diagnostic_fields(role="required"),
        # ── Diagnóstico provisional clínico pre-histología ─────────────
        # NCCN PROS-G v5.2026 + EAU §6.5.4 + Briganti 2012. Permite activar
        # workflows downstream (mHSPC empírico, ADT) sin contaminar
        # `known_cancer_diagnosis`.
        *provisional_diagnosis_fields(),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura crítica en diagnóstico: pre-biopsia calculadores (PHI/4Kscore/
        # PSAv/PSAD gate 69), metastatic biopsy pathway (gate 66), atypical
        # histology (gate 67), oncologic emergencies pre-dx (gate 68).
        *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
    ],
)
