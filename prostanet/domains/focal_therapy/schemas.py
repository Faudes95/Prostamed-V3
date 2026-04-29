# -*- coding: utf-8 -*-
"""EPIC 8 — Terapia focal (HIFU, crioablación, TULSA).

Schema ligero: reusa mucho de ``localized_initial`` (PSA, Gleason, MRI)
y añade campos específicos para lesión índice unilateral.

Indicaciones NCCN PROS-C (categoría 2B):
- Intermedio favorable unilateral con lesión índice documentada.
- Próstata no > 50-60 mL (HIFU), sin obstrucción severa (retención urinaria).
- Preferencia del paciente por preservación funcional.
- Contraindica lesión apical anterior profunda (HIFU) o lesión > 15 mm (variable).

Modalidades:
- HIFU: Stabile Eur Urol 2019; Guillaumier Eur Urol 2018.
- Crioablación: Ward BJU Int 2012.
- TULSA: Klotz J Urol 2021.

Resultados publicados:
- Failure-free survival 5y: ~75-85% (Stabile, Guillaumier).
- Re-focal o salvage 5y: ~20-30%.
- Incontinencia: ~2%; ED: ~25% (Donovan-like PRO).
"""
from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


FOCAL_MODALITY_OPTIONS = [
    "No definida",
    "HIFU (high-intensity focused ultrasound)",
    "Crioablación",
    "TULSA-Pro (transurethral ultrasound)",
    "Electroporación irreversible (Nanoknife)",
    "Láser intersticial (FLA)",
]


LESION_UNILATERAL_OPTIONS = [
    "Desconocido",
    "Unilateral (afecta un solo lóbulo)",
    "Bilateral",
]


FOCAL_THERAPY_SCHEMA = module_schema(
    "focal_therapy",
    "Terapia focal selectiva (HIFU / Crio / TULSA)",
    "Alternativa ambulatoria en intermedio favorable unilateral con preservación funcional (NCCN PROS-C cat 2B).",
    fields=[
        FieldSpec("age", "Edad", "number", default=65, group="Contexto clínico", group_order=1, clinical_role="decision_refiner", unit="años"),
        FieldSpec(
            "life_expectancy_years",
            "Esperanza de vida",
            "number",
            default=18,
            group="Contexto clínico",
            group_order=1,
            clinical_role="decision_refiner",
            unit="años",
        ),
        FieldSpec(
            "psa",
            "PSA",
            "number",
            required=True,
            default=6.0,
            group="Biomarcadores",
            group_order=2,
            clinical_role="required",
            unit="ng/mL",
        ),
        FieldSpec(
            "gleason_primary",
            "Gleason primario",
            "number",
            required=True,
            default=3,
            group="Biomarcadores",
            group_order=2,
            clinical_role="required",
        ),
        FieldSpec(
            "gleason_secondary",
            "Gleason secundario",
            "number",
            required=True,
            default=4,
            group="Biomarcadores",
            group_order=2,
            clinical_role="required",
        ),
        FieldSpec(
            "isup_grade",
            "Grupo ISUP",
            "number",
            default=2,
            group="Biomarcadores",
            group_order=2,
            clinical_role="required",
        ),
        FieldSpec(
            "nccn_risk_group",
            "Grupo NCCN",
            "select",
            options=[
                "Desconocido",
                "Very low",
                "Low",
                "Favorable intermediate",
                "Unfavorable intermediate",
                "High",
                "Very high",
            ],
            default="Favorable intermediate",
            group="Biomarcadores",
            group_order=2,
            clinical_role="required",
        ),
        FieldSpec(
            "lesion_unilateral",
            "Lateralidad de la lesión índice",
            "select",
            options=LESION_UNILATERAL_OPTIONS,
            default="Desconocido",
            group="Imagen prostática",
            group_order=3,
            clinical_role="required",
            evidence_tags=["mpmri", "focal_eligibility"],
        ),
        FieldSpec(
            "lesion_maxdim_mm",
            "Diámetro máximo de la lesión índice",
            "number",
            default=10,
            group="Imagen prostática",
            group_order=3,
            clinical_role="required",
            unit="mm",
            evidence_tags=["mpmri", "focal_eligibility"],
        ),
        FieldSpec(
            "mri_psa_density",
            "Densidad PSA derivada de MRI",
            "number",
            default=0.12,
            group="Imagen prostática",
            group_order=3,
            clinical_role="decision_refiner",
            unit="ng/mL/cc",
            derived_from=["psa", "prostate_volume_ml"],
        ),
        FieldSpec(
            "prostate_volume_ml",
            "Volumen prostático",
            "number",
            default=45,
            group="Imagen prostática",
            group_order=3,
            clinical_role="required",
            unit="mL",
        ),
        FieldSpec(
            "lesion_location_apical",
            "Lesión con extensión apical anterior profunda",
            "select",
            options=["0", "1"],
            default="0",
            group="Imagen prostática",
            group_order=3,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "urinary_obstructive_symptoms",
            "Síntomas obstructivos urinarios significativos",
            "select",
            options=["0", "1"],
            default="0",
            group="Síntomas basales",
            group_order=4,
            clinical_role="decision_refiner",
            evidence_tags=["ipss"],
        ),
        FieldSpec(
            "focal_modality_preferred",
            "Modalidad focal preferida",
            "select",
            options=FOCAL_MODALITY_OPTIONS,
            default="No definida",
            group="Plan focal",
            group_order=5,
            clinical_role="decision_refiner",
        ),
        FieldSpec(
            "patient_priority_profile",
            "Perfil de prioridades del paciente",
            "text",
            default="preserve_urinary_function, preserve_sexual_function",
            group="Preferencias del paciente",
            group_order=6,
            clinical_role="decision_refiner",
            evidence_tags=["sdm", "patient_priority_profile"],
        ),
    ],
)
