# -*- coding: utf-8 -*-
"""EPIC 8 — Screening poblacional: schema.

NCCN Early Detection v2.2026 + USPSTF 2018 + EAU 2026 §5.1.

Campos captura:
- Edad, raza/etnicidad, historia familiar (BRCA/Lynch/cáncer próstata temprano)
- PSA basal, tacto rectal, DRE, intervalos previos de screening
- Riesgo hereditario conocido (germline BRCA/HOXB13/MMR)
- Preferencia del paciente sobre screening informado
"""
from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


SCREENING_AGE_GROUP_OPTIONS = [
    "< 40",
    "40-44",
    "45-49",
    "50-54",
    "55-69",
    "70-74",
    "≥ 75",
]

SCREENING_ETHNICITY_OPTIONS = [
    "No declarada",
    "Afroamericano / afrodescendiente",
    "Caucásico",
    "Hispano / latino",
    "Asiático",
    "Otro",
]

FAMILY_HISTORY_CLUSTER_OPTIONS = [
    "Sin historia familiar relevante",
    "1 familiar de primer grado con cáncer de próstata",
    "≥ 2 familiares de primer grado con cáncer de próstata",
    "Familiar con cáncer de próstata metastásico o muerto < 60a",
    "Cluster familiar BRCA / Lynch / cáncer de mama-ovario",
]

GERMLINE_KNOWN_OPTIONS = [
    "Desconocido / no testeado",
    "Negativo",
    "Positivo BRCA1",
    "Positivo BRCA2",
    "Positivo HOXB13",
    "Positivo Lynch (MSH2 / MLH1 / MSH6 / PMS2)",
    "Otro positivo",
]

PRIOR_SCREENING_PATTERN_OPTIONS = [
    "Nunca",
    "Una sola vez",
    "Anual",
    "Cada 2 años",
    "Cada 3-5 años",
    "Irregular",
]

SCREENING_SCHEMA = module_schema(
    "screening",
    "Screening poblacional de cáncer de próstata",
    "Detección temprana informada (NCCN Early Detection v2.2026, USPSTF 2018, EAU 2026) — no aplica a pacientes con diagnóstico confirmado.",
    fields=[
        FieldSpec(
            "age",
            "Edad",
            "number",
            default=55,
            group="Demográficos",
            group_order=1,
            clinical_role="required",
            unit="años",
            evidence_tags=["nccn_early_detection_v2_2026", "uspstf_2018"],
        ),
        FieldSpec(
            "screening_age_group",
            "Grupo etario (agregado)",
            "select",
            options=SCREENING_AGE_GROUP_OPTIONS,
            default="55-69",
            group="Demográficos",
            group_order=1,
            clinical_role="decision_refiner",
            derived_from=["age"],
        ),
        FieldSpec(
            "ethnicity_group",
            "Raza / etnicidad",
            "select",
            options=SCREENING_ETHNICITY_OPTIONS,
            default="No declarada",
            group="Demográficos",
            group_order=1,
            clinical_role="decision_refiner",
            evidence_tags=["nccn_early_detection_v2_2026", "afroamericano_risk"],
        ),
        FieldSpec(
            "life_expectancy_years",
            "Esperanza de vida",
            "number",
            default=20,
            group="Demográficos",
            group_order=1,
            clinical_role="decision_refiner",
            unit="años",
        ),
        FieldSpec(
            "family_history_cluster",
            "Historia familiar",
            "select",
            options=FAMILY_HISTORY_CLUSTER_OPTIONS,
            default="Sin historia familiar relevante",
            group="Riesgo hereditario",
            group_order=2,
            clinical_role="required",
            evidence_tags=["family_history", "nccn_early_detection_v2_2026"],
        ),
        # EPIC 14b smart-form: germline_known_status solo es clínicamente
        # determinante cuando hay family history hereditario (cluster relevante
        # o ≥1 familiar primer grado). Sin family history, el test germinal
        # no se ordena rutinariamente per NCCN PROS-H. Beneficio clínico:
        # reduce captura irrelevante en pacientes screening sin historial
        # familiar, foco en pacientes que sí requieren genetic counseling.
        FieldSpec(
            "germline_known_status",
            "Resultado germinal conocido",
            "select",
            options=GERMLINE_KNOWN_OPTIONS,
            default="Desconocido / no testeado",
            group="Riesgo hereditario",
            group_order=2,
            clinical_role="required",
            evidence_tags=["germline", "nccn_pros_h"],
            conditional_visibility={
                "family_history_cluster": [
                    "1 familiar de primer grado con cáncer de próstata",
                    "≥ 2 familiares de primer grado con cáncer de próstata",
                    "Familiar con cáncer de próstata metastásico o muerto < 60a",
                    "Cluster familiar BRCA / Lynch / cáncer de mama-ovario",
                ],
            },
        ),
        FieldSpec(
            "psa_baseline_ng_ml",
            "PSA basal",
            "number",
            default=1.0,
            group="Biomarcadores",
            group_order=3,
            clinical_role="required",
            unit="ng/mL",
            evidence_tags=["psa", "nccn_early_detection_v2_2026"],
        ),
        FieldSpec(
            "psa_baseline_date",
            "Fecha del PSA basal",
            "date",
            group="Biomarcadores",
            group_order=3,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "dre_baseline_finding",
            "Tacto rectal basal",
            "select",
            options=["No realizado", "Normal", "Sospechoso", "Asimétrico"],
            default="No realizado",
            group="Biomarcadores",
            group_order=3,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "prior_screening_pattern",
            "Patrón de screening previo",
            "select",
            options=PRIOR_SCREENING_PATTERN_OPTIONS,
            default="Nunca",
            group="Antecedente de screening",
            group_order=4,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "last_psa_ng_ml",
            "Último PSA (si distinto del basal)",
            "number",
            default="",
            group="Antecedente de screening",
            group_order=4,
            clinical_role="decision_refiner",
            unit="ng/mL",
        ),
        FieldSpec(
            "last_psa_date",
            "Fecha del último PSA",
            "date",
            group="Antecedente de screening",
            group_order=4,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "informed_decision_ready",
            "Paciente informado sobre beneficios/daños del screening",
            "select",
            options=["0", "1"],
            default="0",
            group="Preferencias del paciente",
            group_order=5,
            clinical_role="decision_refiner",
            evidence_tags=["shared_decision_making", "nccn_pros_a"],
        ),
        FieldSpec(
            "patient_preference_screening",
            "Preferencia del paciente",
            "select",
            options=[
                "No discutido",
                "Quiere hacer screening",
                "No quiere hacer screening",
                "Indeciso — requiere más información",
            ],
            default="No discutido",
            group="Preferencias del paciente",
            group_order=5,
            clinical_role="decision_refiner",
        ),
    ],
)
