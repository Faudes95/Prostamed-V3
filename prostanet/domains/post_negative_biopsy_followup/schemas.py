from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


POST_NEGATIVE_BIOPSY_SCHEMA = module_schema(
    "post_negative_biopsy_followup",
    "Seguimiento después de una biopsia benigna inicial",
    "Estructura el seguimiento de baja intensidad tras biopsia benigna y detecta cuándo debe reabrirse el estudio diagnóstico.",
    fields=[
        FieldSpec("psa", "Antígeno prostático específico (PSA)", "number", required=True, default=4.6, group="Sospecha actual", group_order=1, clinical_role="required", unit="ng/mL", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("psad", "Densidad del antígeno prostático específico (PSAD)", "number", default=0.09, group="Sospecha actual", group_order=1, clinical_role="required", unit="ng/mL/cc", derived_from=["psa", "prostate_volume_ml"], evidence_tags=["psad"]),
        FieldSpec("psa_velocity_ng_ml_year", "Velocidad de PSA", "number", default=0.4, group="Sospecha actual", group_order=1, clinical_role="decision_refiner", unit="ng/mL/año", evidence_tags=["psa_kinetics"]),
        FieldSpec("psa_history_interval_months", "Intervalo de la serie de PSA", "number", default=12, group="Sospecha actual", group_order=1, clinical_role="monitoring", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("pirads_score", "Resultado de resonancia magnética multiparamétrica", "select", options=["0", "2", "3", "4", "5"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("post_biopsy_mri", "Resonancia magnética posterior a biopsia", "select", options=["0", "1"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("persistent_lesion_signal", "Persistencia de lesión sospechosa", "select", options=["0", "1"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("dre_suspicious", "Tacto rectal sospechoso", "select", options=["0", "1"], default="0", group="Exploración clínica", group_order=3, clinical_role="required", evidence_tags=["nccn_primary"]),
        FieldSpec("years_since_negative_biopsy", "Años desde la biopsia benigna", "number", default=1, group="Biopsia previa", group_order=4, clinical_role="required", unit="años", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_date", "Fecha de la biopsia previa", "date", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_type", "Tipo de biopsia previa", "select", options=["Sistemática", "Dirigida", "Fusión", "Desconocida"], default="Sistemática", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_mri_targeted", "Biopsia previa guiada por MRI", "select", options=["0", "1"], default="0", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_count", "Número de biopsias previas", "number", default=1, group="Biopsia previa", group_order=4, clinical_role="decision_refiner", unit="biopsias", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("repeat_biopsy_trigger", "Motivo de rebiopsia", "select", options=["PSA/PSAD", "MRI persistente", "Tacto rectal", "Historia familiar", "Sin criterio"], default="PSA/PSAD", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("family_history_positive", "Historia familiar relevante", "select", options=["0", "1"], default="0", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        # EPIC 9 Group F (GAP-13) — Exposición explícita de los tres campos que
        # ya eran consumidos implícitamente por el scheduling de rebiopsia pero
        # no aparecían en el schema del dominio (se resolvían por fallback en
        # trajectory o por longitudinal_truth cuando se propagaban desde
        # diagnostic_workup). Con estos FieldSpec se cierra el contrato de
        # captura post-biopsia-negativa (EAU 2026 §5.6 + NCCN PROS-D).
        #
        # NOTA sobre `piqual_score`: la guía EAU sugiere reportarlo, pero
        # `rules_nccn.py` actual NO lo consume — se documenta aquí para que
        # no se interprete como omisión; se reevaluará cuando el motor incluya
        # un gate de calidad de mpMRI estricto (fuera de alcance EPIC 9).
        FieldSpec("prostate_volume_ml", "Volumen prostático", "number", default="", group="Imagen actual", group_order=2, clinical_role="decision_refiner", unit="mL", evidence_tags=["psad", "mpmri"]),
        FieldSpec("planned_biopsy_type", "Tipo de biopsia prevista en la reactivación", "select", options=["Dirigida + sistemática", "Dirigida", "Sistemática", "Pendiente"], default="Pendiente", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
        FieldSpec("planned_biopsy_route", "Vía de biopsia prevista", "select", options=["Transperineal", "Transrectal", "No definida"], default="No definida", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
    ],
)
