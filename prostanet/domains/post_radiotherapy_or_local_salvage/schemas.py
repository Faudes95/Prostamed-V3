from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.advanced_support_fields import (
    oncologic_emergency_fields,
    pivotal_gate_supporting_fields,
)


POST_RT_LOCAL_SALVAGE_SCHEMA = module_schema(
    "post_radiotherapy_or_local_salvage",
    "Recurrencia post-radioterapia y salvage local",
    "Confirma fallo bioquímico post-RT con Phoenix o evidencia local equivalente y ordena salvage local, MDT o redirección sistémica.",
    fields=[
        FieldSpec("prior_radiation", "Radioterapia previa", "select", required=True, options=["1"], default="1", group="Contexto post-RT", group_order=1, clinical_role="required"),
        FieldSpec("prior_prostatectomy", "Prostatectomía previa", "select", required=True, options=["0", "1"], default="0", group="Contexto post-RT", group_order=1, clinical_role="required"),
        FieldSpec("local_therapy_date", "Fecha de radioterapia principal", "date", group="Contexto post-RT", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("prior_rt_modality", "Modalidad RT previa", "select", required=True, options=["EBRT_IMRT", "EBRT_VMAT", "SBRT", "LDR_brachy", "HDR_brachy", "combined", "Otro"], default="EBRT_IMRT", group="Contexto post-RT", group_order=1, clinical_role="required"),
        FieldSpec("prior_rt_dose", "Dosis total de RT previa", "number", required=True, default=78, group="Contexto post-RT", group_order=1, clinical_role="decision_refiner", unit="Gy"),
        FieldSpec("prior_rt_fields", "Campos irradiados previamente", "text", required=True, group="Contexto post-RT", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("psa_current", "PSA actual", "number", required=True, default=1.1, group="Confirmación de fallo post-RT", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_nadir", "PSA nadir post-RT", "number", required=True, default=0.3, group="Confirmación de fallo post-RT", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("phoenix_delta", "Incremento Phoenix (PSA actual - nadir)", "number", required=True, default=0.8, group="Confirmación de fallo post-RT", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("biopsy_proven_local_recurrence", "Biopsia confirma recurrencia local", "select", options=["0", "1"], default="0", group="Confirmación de fallo post-RT", group_order=2, clinical_role="required"),
        FieldSpec("biopsy_date", "Fecha de biopsia de rescate", "date", group="Confirmación de fallo post-RT", group_order=2, clinical_role="decision_refiner"),
        FieldSpec("biopsy_grade_group", "Grupo de grado en biopsia de rescate", "select", options=["1", "2", "3", "4", "5"], default="2", group="Confirmación de fallo post-RT", group_order=2, clinical_role="decision_refiner"),
        FieldSpec("mpmri_done", "mpMRI realizada", "select", options=["0", "1"], default="0", group="Reestadificación local", group_order=3, clinical_role="required"),
        FieldSpec("mpmri_date", "Fecha de mpMRI", "date", group="Reestadificación local", group_order=3, clinical_role="decision_refiner"),
        FieldSpec("mpmri_localized_recurrence", "mpMRI sugiere recurrencia localizada", "select", options=["0", "1"], default="0", group="Reestadificación local", group_order=3, clinical_role="required"),
        FieldSpec("local_recurrence_site", "Sitio dominante de recurrencia local", "select", options=["Gland focal", "Hemigland", "Base", "Apex", "Periuretral", "Lecho/vesículas", "Multifocal", "No definido"], default="No definido", group="Reestadificación local", group_order=3, clinical_role="decision_refiner"),
        FieldSpec("psma_pet_done", "PSMA-PET realizada", "select", options=["0", "1"], default="0", group="Reestadificación sistémica", group_order=4, clinical_role="required"),
        FieldSpec("psma_radioligand", "Radioligando PSMA", "select", options=["68Ga-PSMA-11", "18F-DCFPyL", "18F-PSMA-1007", "Otro", "Desconocido"], default="Desconocido", group="Reestadificación sistémica", group_order=4, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_rads_score", "PSMA-RADS", "select", options=["1", "2", "3", "4", "5", "Desconocido"], default="Desconocido", group="Reestadificación sistémica", group_order=4, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_uptake_pattern", "Patrón de captación PSMA", "select", options=["focal", "multifocal", "oligometastatic", "diseminado", "indeterminado"], default="indeterminado", group="Reestadificación sistémica", group_order=4, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_total_lesions", "Número total de lesiones PSMA", "number", default=1, group="Reestadificación sistémica", group_order=4, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("psma_stage_after_psma", "Stage posterior por PSMA", "select", options=["M0", "M1a", "M1b", "M1c"], default="M0", group="Reestadificación sistémica", group_order=4, clinical_role="decision_refiner", conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("urinary_burden", "Carga urinaria basal", "select", options=["Leve", "Moderada", "Grave"], default="Leve", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("incontinence_burden", "Carga de incontinencia", "select", options=["Leve", "Moderada", "Grave"], default="Leve", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("urethral_stricture_history", "Antecedente de estenosis uretral", "select", options=["0", "1"], default="0", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("bowel_burden", "Carga intestinal/rectal basal", "select", options=["Leve", "Moderada", "Grave"], default="Leve", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("rectal_toxicity_grade", "Grado de toxicidad rectal previa", "select", options=["0", "1", "2", "3", "4"], default="0", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("prostate_volume", "Volumen prostático", "number", default=35, group="Factibilidad de salvage local", group_order=5, clinical_role="decision_refiner", unit="mL"),
        FieldSpec("anesthesia_surgical_fitness", "Aptitud quirúrgica/anestésica", "select", options=["Fit", "Vulnerable", "No apto"], default="Fit", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("salvage_expertise_available", "Existe expertise local para salvage complejo", "select", options=["0", "1", "Desconocido"], default="Desconocido", group="Factibilidad de salvage local", group_order=5, clinical_role="required"),
        FieldSpec("ecog_score", "ECOG", "select", options=["0", "1", "2", "3"], default="0", group="Factibilidad de salvage local", group_order=5, clinical_role="decision_refiner"),
        # ── Triaje de emergencias oncológicas (Brecha 2026-04-23) ──────
        # NCCN Oncologic Emergencies v3.2026 + Loblaw 2012 + EAU §6.5.5.
        # Post-RT con fallo Phoenix puede debutar con progresión visceral u
        # ósea sintomática; el triaje permite escalar antes del salvage local.
        *oncologic_emergency_fields(role="decision_refiner", group_order=70),
        # ── Soportes pivotal gates 56-70 (Faubot LXXV/LXXVI/LXXVII #67A/B/C) ──
        # Captura UI: PSA bounce post-RT (gate 54), prior pelvic RT contra
        # re-RT (gate 58), salvage RT consideration (gate 70), atypical (gate 67).
        *pivotal_gate_supporting_fields(role="decision_refiner", group_order=81),
    ],
)
