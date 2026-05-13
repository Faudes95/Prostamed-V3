# EPIC 10B — Gate Field Coverage Audit Report

> Generado por `scripts/epic10b_audit_gate_coverage.py`.  
> Audita la integridad del contrato entre los gates YAML (`prostanet/shared/pivotal_gates_catalog/`) y los FieldSpecs canónicos declarados en los 17 SCHEMAS del CDE Auditable.

## Resumen ejecutivo

- **Gates YAML cargados (dedup por code):** 103
- **FieldSpecs canónicos (unión 17 SCHEMAS):** 920
- **Fields candidatos referenciados (cualquier alias):** 1216
- **Gates con ≥1 trigger group huérfano:** 0
- **FieldSpecs sin uso (legacy/info):** 461

> **Semántica del audit (correcta):** un trigger group es huérfano si NINGUNO de sus candidate fields (`field` + `alias_fields`) existe en algún schema canónico. El loader dispara el trigger si payload contiene cualquiera del conjunto — por eso basta con UNO presente para ser ejecutable. Esta métrica es la única clínicamente correcta.

### Distribución por severity

- `hard_block`: 69 gates (0 con grupos huérfanos)
- `informational`: 13 gates (0 con grupos huérfanos)
- `soft_warning`: 21 gates (0 con grupos huérfanos)

### Distribución por trigger type

- `all_of`: 3
- `any_of`: 90
- `numeric_below`: 1
- `numeric_threshold`: 4
- `truthy_flag`: 5

## Gates con grupos huérfanos (blockers clínicos silenciosos)

Un gate con grupo huérfano tiene al menos un trigger que **nunca puede disparar** porque ninguno de sus candidate fields existe como FieldSpec capturable. Esto significa que el motor parece evaluar el gate pero la contraindicación jamás se aplica con datos reales. **Cada uno es un riesgo clínico real.**

✅ **Ningún gate tiene grupos huérfanos.** Contract integrity 100%.

## Auditoría de metadatos regulatorios

### Gates sin `evidence_tag`: 0

### Gates sin `trial_refs`: 0

### Hard-blocks sin `nccn_eau_alignment` ni FDA-label fallback: 25
- `abiraterone_adrenal_insufficiency`
- `abiraterone_cirrhosis_baseline_contraindication`
- `atypical_histology_escalation_nepc_intraductal`
- `bone_targeted_osteonecrosis_jaw`
- `checkpoint_inhibitor_endocrinopathy_new_onset`
- `checkpoint_inhibitor_hepatitis_grade3_plus`
- `ct4_requires_histology_confirmation`
- `docetaxel_neuropathy_cumulative_postchemo`
- `hand_foot_syndrome_tkis_grade2_plus`
- `hrr_status_required_before_parp_inhibitor`
- `ibd_active_pelvic_rt_contraindication`
- `ipatasertib_pten_wt_futility_block`
- `lu177_psma_pet_negative_contraindication`
- `lutetium177_in_cord_compression`
- `lutetium177_in_severe_cytopenias`
- `oncologic_emergency_diagnostic_integration`
- `palliative_sedation_protocol_initiation`
- `parp_hrr_negative_futility_block`
- `prior_pelvic_rt_re_irradiation_contraindication`
- `ra223_visceral_metastases_contraindication`
- `radium223_in_cord_compression`
- `radium223_in_hypocalcemia`
- `sipuleucel_t_immunosuppression_baseline`
- `taxane_diarrhea_grade3_plus`
- `turp_brachytherapy_contraindication`

### Gates con `message` < 40 chars: 0

## FieldSpecs sin uso (muestra primeros 50)

Fields declarados en algún SCHEMA pero **ninguno de los 103 gates los referencia**. Pueden ser (a) inputs canónicos para algoritmos sin gate (legítimos), (b) campos legacy candidatos a remover, (c) campos que deberían tener gate pero no se modeló.

- `actinium_225_dose_planned_kbq_kg`
- `active_autoimmune_disease`
- `active_hepatitis_b_or_c`
- `active_inflammatory_bowel_disease`
- `active_liver_disease`
- `acute_urinary_retention`
- `adt_active`
- `adt_duration_months`
- `adt_intent`
- `adt_primary_agent`
- `adt_start_date`
- `adverse_histology_variant_detail`
- `adverse_histology_variant_type`
- `adverse_pathology`
- `age_current`
- `albumin_g_dl`
- `alp`
- `anesthesia_surgical_fitness`
- `anticoagulant_indication`
- `antidepressant_initiated`
- `anxiolytic_initiated`
- `ari_medication_active`
- `armor3_sv_trial_consideration`
- `autoimmune_disease_name`
- `baseline_bp`
- `baseline_obstruction`
- `baseline_qol`
- `baseline_sexual_qol`
- `baseline_urinary_qol`
- `baseline_weight`
- `baseline_weight_kg`
- `bcr2`
- `bcr_detected`
- `biomarker_source`
- `biopsy_contraindicated_reason`
- `biopsy_planned_date`
- `biopsy_proven_local_recurrence`
- `biopsy_status`
- `bladder_cancer_screening`
- `bladder_invasion`
- `bone_health_dxa`
- `bone_lesion_count`
- `bone_lesions_outside_axial`
- `bone_pain`
- `bone_pain_severity`
- `bone_pain_widespread_documented`
- `bone_scan_done`
- `bone_scan_multifoci_positive`
- `bone_scan_result`
- `bounce_suspected`
- ... (411 más)

---

## Próximos pasos sugeridos

✅ **Contract integrity 100%.** Avanzar a EPIC 10C (performance + WCAG accessibility baseline).