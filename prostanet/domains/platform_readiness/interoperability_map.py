"""Read-only interoperability readiness map for canonical clinical facts.

This layer does not export patient data. It answers whether the Clinical Fact
Ledger has enough semantic mapping to be safely projected later into mCODE/FHIR
or OMOP Oncology research datasets.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from prostanet.domains.platform_readiness.ledger_release_gate import DOMAIN_OWNERS
from prostanet.shared.clinical_fact_registry import FACT_SPECS, FactSpec
from prostanet.shared.utc_time import utc_now_iso


INTEROPERABILITY_MAP_VERSION = "clinical_fact_interoperability_readiness_v1"

SOURCE_STANDARDS = {
    "mcode": {
        "label": "HL7 mCODE Implementation Guide",
        "version": "4.0.0",
        "url": "https://hl7.org/fhir/us/mcode/",
    },
    "omop_oncology": {
        "label": "OMOP CDM Oncology Extension",
        "version": "CDM v6.1 proposal",
        "url": "https://ohdsi.github.io/CommonDataModel/oncology.html",
    },
}

DOMAIN_DEFAULTS: dict[str, dict[str, str]] = {
    "biochemical": {
        "fhir_target": "Observation",
        "mcode_profile": "mCODE TumorMarkerTest / Observation",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/SNOMED CT",
        "cardinality": "0..* longitudinal",
        "mapping_status": "partial",
        "note": "Biomarcador longitudinal; requiere codigo LOINC especifico por analito y unidad.",
    },
    "diagnostic": {
        "fhir_target": "Observation / DiagnosticReport",
        "mcode_profile": "mCODE DiseaseCharacterization",
        "omop_target": "OBSERVATION / MEASUREMENT",
        "vocabulary": "SNOMED CT/LOINC",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Dato diagnostico; requiere preservar fuente y fecha.",
    },
    "pathology": {
        "fhir_target": "DiagnosticReport / Observation",
        "mcode_profile": "mCODE CancerRelatedDiagnosticReport",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "SNOMED CT/LOINC",
        "cardinality": "0..* por muestra",
        "mapping_status": "partial",
        "note": "Patologia estructurada; idealmente debe apuntar a muestra/core.",
    },
    "staging": {
        "fhir_target": "Observation",
        "mcode_profile": "mCODE TNMStageGroup / TNMCategory",
        "omop_target": "EPISODE / MEASUREMENT",
        "vocabulary": "AJCC/SNOMED CT",
        "cardinality": "0..* versionado por fecha",
        "mapping_status": "partial",
        "note": "Estadificacion clinica o radiologica; requiere version y base documental.",
    },
    "precision": {
        "fhir_target": "MolecularSequence / Observation / DiagnosticReport",
        "mcode_profile": "mCODE GenomicsReport / GenomicVariant",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "HGNC/ClinVar/LOINC/SNOMED CT",
        "cardinality": "0..* por reporte",
        "mapping_status": "partial",
        "note": "Precision oncology; v1 define destino semantico, no ingiere reportes externos.",
    },
    "systemic_context": {
        "fhir_target": "MedicationStatement / Observation",
        "mcode_profile": "mCODE CancerRelatedMedicationStatement / DiseaseStatus",
        "omop_target": "DRUG_EXPOSURE / EPISODE / OBSERVATION",
        "vocabulary": "RxNorm/SNOMED CT",
        "cardinality": "0..* longitudinal",
        "mapping_status": "partial",
        "note": "Contexto de tratamiento sistemico o estado terapeutico.",
    },
    "metastatic_context": {
        "fhir_target": "Observation / Condition",
        "mcode_profile": "mCODE CancerDiseaseStatus / SecondaryCancerCondition",
        "omop_target": "EPISODE / CONDITION_OCCURRENCE / MEASUREMENT",
        "vocabulary": "SNOMED CT/AJCC",
        "cardinality": "0..* por evaluacion",
        "mapping_status": "partial",
        "note": "Distribucion metastasica y base de deteccion; requiere fuente de imagen.",
    },
    "fitness": {
        "fhir_target": "Observation",
        "mcode_profile": "mCODE PerformanceStatus",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "LOINC/SNOMED CT",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Fitness o comorbilidad; requiere escala y fecha.",
    },
    "frailty": {
        "fhir_target": "Observation",
        "mcode_profile": "FHIR Observation",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "LOINC/SNOMED CT",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Fragilidad geriatrica; mapear escala usada.",
    },
    "pros": {
        "fhir_target": "QuestionnaireResponse / Observation",
        "mcode_profile": "FHIR QuestionnaireResponse",
        "omop_target": "SURVEY_CONDUCT / OBSERVATION",
        "vocabulary": "LOINC/Instrument-specific",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "PROs; conservar instrumento, dominio y fecha.",
    },
    "supportive": {
        "fhir_target": "MedicationStatement / Observation",
        "mcode_profile": "FHIR MedicationStatement / Observation",
        "omop_target": "DRUG_EXPOSURE / OBSERVATION",
        "vocabulary": "RxNorm/SNOMED CT/LOINC",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Soporte y seguridad; algunos flags no son exportables como outcome v1.",
    },
    "renal": {
        "fhir_target": "Observation",
        "mcode_profile": "FHIR Laboratory Observation",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/UCUM",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Funcion renal/laboratorio; requiere unidad UCUM.",
    },
    "laboratory": {
        "fhir_target": "Observation",
        "mcode_profile": "FHIR Laboratory Observation",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/UCUM",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Laboratorio pronostico o de seguridad; requiere codigo y unidad.",
    },
    "salvage": {
        "fhir_target": "Procedure / Observation",
        "mcode_profile": "mCODE CancerRelatedSurgicalProcedure / RadiotherapyCourseSummary",
        "omop_target": "PROCEDURE_OCCURRENCE / EPISODE / OBSERVATION",
        "vocabulary": "SNOMED CT/CPT/HCPCS",
        "cardinality": "0..*",
        "mapping_status": "partial",
        "note": "Contexto local/salvage; requiere anclar a tratamiento previo.",
    },
    "preferences": {
        "fhir_target": "Goal / Observation",
        "mcode_profile": "FHIR Goal / Observation",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT/local",
        "cardinality": "0..*",
        "mapping_status": "documented_not_exported_v1",
        "note": "Preferencias clinicas se documentan para decision compartida; no se exportan en v1.",
    },
}

FACT_OVERRIDES: dict[str, dict[str, str]] = {
    "baseline_psa": {
        "mcode_profile": "mCODE TumorMarkerTest: PSA",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC PSA + UCUM ng/mL",
        "cardinality": "0..* longitudinal; baseline flag por contexto",
        "mapping_status": "mapped",
        "note": "APE/PSA basal exportable como medicion longitudinal con contexto basal.",
    },
    "current_psa": {
        "mcode_profile": "mCODE TumorMarkerTest: PSA",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC PSA + UCUM ng/mL",
        "cardinality": "0..* longitudinal",
        "mapping_status": "mapped",
        "note": "APE/PSA actual exportable como ultima observacion vigente.",
    },
    "psa_current_date": {
        "mapping_status": "mapped",
        "fhir_target": "Observation.effectiveDateTime",
        "omop_target": "MEASUREMENT.measurement_date",
        "vocabulary": "FHIR dateTime / OMOP date",
        "note": "Fecha del APE/PSA actual; acompana la medicion, no se duplica como medicion independiente.",
    },
    "psa_postop": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE TumorMarkerTest: PSA",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC PSA + UCUM ng/mL",
        "note": "APE postoperatorio exportable como PSA con contexto post-RP.",
    },
    "psadt_months": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation derived",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "SNOMED/LOINC local derived + UCUM month",
        "note": "PSADT es derivado; requiere lineage a serie PSA.",
    },
    "testosterone": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Laboratory Observation",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC testosterone + UCUM",
        "note": "Testosterona usada para confirmar castracion.",
    },
    "castrate_testosterone_status": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation interpretation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT/local threshold",
        "note": "Estado derivado de testosterona; exportar con umbral y fuente.",
    },
    "castration_resistant": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE CancerDiseaseStatus",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "EPISODE / OBSERVATION",
        "vocabulary": "SNOMED CT/local phenotype",
        "note": "Fenotipo CRPC; requiere PSA/progresion + castracion.",
    },
    "m0_crpc_state_confirmed": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE CancerDiseaseStatus",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "EPISODE",
        "vocabulary": "SNOMED CT/AJCC/local phenotype",
        "note": "Estado m0CRPC confirmado como episodio fenotipico.",
    },
    "known_cancer_diagnosis": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE PrimaryCancerCondition",
        "fhir_target": "Condition",
        "omop_target": "CONDITION_OCCURRENCE",
        "vocabulary": "ICD-O/SNOMED CT",
        "note": "Diagnostico conocido o sospecha confirmada; no sustituye histologia.",
    },
    "pirads_score": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR ImagingStudy/Observation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "PI-RADS v2.1 local code",
        "note": "PI-RADS exportable como resultado de imagen.",
    },
    "dre_suspicious": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueBoolean",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT physical finding",
        "note": "TR sospechoso exportable como hallazgo fisico.",
    },
    "clinical_tstage": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE TNMClinicalPrimaryTumorCategory",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "MEASUREMENT / EPISODE_EVENT",
        "vocabulary": "AJCC TNM",
        "note": "T clinico versionado por fecha y fuente.",
    },
    "conventional_imaging_status": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR ImagingStudy/Observation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT/local imaging status",
        "note": "Estado de imagen convencional para M0/M1.",
    },
    "progression_pattern": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE CancerDiseaseStatus",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "EPISODE / OBSERVATION",
        "vocabulary": "SNOMED CT/local progression pattern",
        "note": "Patron de progresion usado para decision y redecision.",
    },
    "histology_subtype": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE CancerHistologyMorphologyBehavior",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "MEASUREMENT / OBSERVATION",
        "vocabulary": "ICD-O-3/SNOMED CT",
        "note": "Histologia exportable como morfologia tumoral.",
    },
    "gleason_primary": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE GleasonGradeGroup / Observation component",
        "fhir_target": "Observation.component",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/SNOMED CT",
        "note": "Patron primario Gleason.",
    },
    "gleason_secondary": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE GleasonGradeGroup / Observation component",
        "fhir_target": "Observation.component",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/SNOMED CT",
        "note": "Patron secundario Gleason.",
    },
    "isup_grade": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE GleasonGradeGroup",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "ISUP grade group",
        "note": "Grupo ISUP/Gleason Grade Group.",
    },
    "psa_density": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation derived",
        "fhir_target": "Observation.valueQuantity",
        "omop_target": "MEASUREMENT",
        "vocabulary": "local derived + ng/mL/mL",
        "note": "PSAD derivada; requiere PSA y volumen prostático como lineage.",
    },
    "num_cores_positive": {
        "mapping_status": "mapped",
        "mcode_profile": "CancerRelatedDiagnosticReport / Observation",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/SNOMED CT/local pathology",
        "note": "Cores positivos exportables como medicion de patologia.",
    },
    "total_cores_biopsied": {
        "mapping_status": "mapped",
        "mcode_profile": "CancerRelatedDiagnosticReport / Observation",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "LOINC/SNOMED CT/local pathology",
        "note": "Total de cores biopsiados.",
    },
    "metastatic_stage_resolved": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE TNMDistantMetastasesCategory / CancerDiseaseStatus",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "EPISODE / MEASUREMENT",
        "vocabulary": "AJCC/SNOMED CT",
        "note": "Estado M resuelto con base convencional/PSMA.",
    },
    "metastatic_detection_basis": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "OBSERVATION",
        "vocabulary": "local imaging basis",
        "note": "Base de deteccion metastasica; clave para no mezclar PSMA-only con M1 convencional.",
    },
    "ecog_score": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE ECOGPerformanceStatus",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "ECOG performance status",
        "note": "ECOG exportable para ajuste basal y outcomes.",
    },
    "charlson_score": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "Charlson Comorbidity Index",
        "note": "Comorbilidad basal para ajuste de riesgo.",
    },
    "frailty_status": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT/local frailty status",
        "note": "Estado de fragilidad.",
    },
    "g8_score": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueInteger",
        "omop_target": "MEASUREMENT",
        "vocabulary": "G8 geriatric screening",
        "note": "Cribado G8 para oncogeriatria.",
    },
    "anesthesia_surgical_fitness": {
        "mapping_status": "mapped",
        "mcode_profile": "FHIR Observation",
        "fhir_target": "Observation.valueCodeableConcept",
        "omop_target": "OBSERVATION",
        "vocabulary": "SNOMED CT/local surgical fitness",
        "note": "Aptitud quirurgica/anestesica para modalidad local.",
    },
    "current_adt_context": {
        "mapping_status": "mapped",
        "mcode_profile": "mCODE CancerRelatedMedicationStatement",
        "fhir_target": "MedicationStatement / Observation",
        "omop_target": "DRUG_EXPOSURE / EPISODE",
        "vocabulary": "RxNorm/SNOMED CT",
        "note": "Contexto ADT vigente como exposicion/episodio.",
    },
}


def build_interoperability_map(
    *,
    scope: str = "full",
    field_limit: int = 300,
) -> dict[str, Any]:
    """Build the read-only fact-to-standard mapping readiness payload."""
    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    row_limit = max(25, min(int(field_limit or 300), 2000))

    rows = [_build_row(fact_key, spec) for fact_key, spec in FACT_SPECS.items()]
    rows.sort(key=_row_sort_key)
    summary = _build_summary(rows)
    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_fact_interoperability_map",
        "version": INTEROPERABILITY_MAP_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "source_standards": SOURCE_STANDARDS,
        "summary": summary,
        "domain_summary": _build_domain_summary(rows),
        "top_blockers": [row for row in rows if row["interoperability_status"] == "block"][:10],
        "top_watches": [row for row in rows if row["interoperability_status"] == "watch"][:10],
        "recommendations": _build_recommendations(summary),
    }
    if include_rows:
        payload["mapping"] = rows[:row_limit]
    return payload


def _build_row(fact_key: str, spec: FactSpec) -> dict[str, Any]:
    base = dict(DOMAIN_DEFAULTS.get(spec.domain) or {})
    override = dict(FACT_OVERRIDES.get(fact_key) or {})
    merged = {**base, **override}
    mapping_status = str(merged.get("mapping_status") or "unmapped")
    blockers: list[str] = []
    warnings: list[str] = []

    if spec.blocking and mapping_status not in {"mapped", "documented_not_exported_v1"}:
        blockers.append("critical_fact_without_export_decision")
    if not merged.get("fhir_target") or not merged.get("omop_target"):
        if spec.blocking:
            blockers.append("critical_fact_missing_fhir_or_omop_target")
        else:
            warnings.append("missing_fhir_or_omop_target")
    if mapping_status == "partial":
        warnings.append("needs_code_system_binding")
    if mapping_status == "documented_not_exported_v1":
        warnings.append("documented_not_exported_v1")

    interoperability_status = "block" if blockers else ("watch" if warnings else "pass")
    return {
        "fact_key": fact_key,
        "domain": spec.domain,
        "owner": DOMAIN_OWNERS.get(spec.domain, f"{spec.domain}_owner"),
        "value_type": spec.value_type,
        "blocking": bool(spec.blocking),
        "consumers": list(spec.consumers or []),
        "legacy_aliases": list(spec.legacy_aliases or ()),
        "fhir_target": merged.get("fhir_target", ""),
        "mcode_profile": merged.get("mcode_profile", ""),
        "omop_target": merged.get("omop_target", ""),
        "vocabulary": merged.get("vocabulary", ""),
        "cardinality": merged.get("cardinality", ""),
        "mapping_status": mapping_status,
        "clinical_note": merged.get("note", ""),
        "interoperability_status": interoperability_status,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
    }


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(row["interoperability_status"] for row in rows)
    mapping_counts = Counter(row["mapping_status"] for row in rows)
    critical_rows = [row for row in rows if row["blocking"]]
    critical_blocks = [row for row in critical_rows if row["interoperability_status"] == "block"]
    critical_ready = [
        row
        for row in critical_rows
        if row["mapping_status"] in {"mapped", "documented_not_exported_v1"}
    ]
    status = (
        "interop_blocked"
        if critical_blocks
        else "ready_for_initial_interop"
        if len(critical_ready) == len(critical_rows)
        else "needs_mapping_hardening"
    )
    return {
        "facts_total": len(rows),
        "critical_fact_count": len(critical_rows),
        "critical_ready_count": len(critical_ready),
        "critical_block_count": len(critical_blocks),
        "pass_count": int(status_counts.get("pass") or 0),
        "watch_count": int(status_counts.get("watch") or 0),
        "block_count": int(status_counts.get("block") or 0),
        "mapped_count": int(mapping_counts.get("mapped") or 0),
        "partial_count": int(mapping_counts.get("partial") or 0),
        "documented_not_exported_count": int(mapping_counts.get("documented_not_exported_v1") or 0),
        "unmapped_count": int(mapping_counts.get("unmapped") or 0),
        "critical_mapping_coverage_pct": round((len(critical_ready) / len(critical_rows)) * 100, 1)
        if critical_rows
        else 100.0,
        "overall_mapping_coverage_pct": round((int(mapping_counts.get("mapped") or 0) / len(rows)) * 100, 1)
        if rows
        else 0.0,
        "interoperability_status": status,
        "next_layer_allowed": status == "ready_for_initial_interop",
    }


def _build_domain_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["domain"], []).append(row)
    out = []
    for domain, items in sorted(grouped.items()):
        status_counts = Counter(item["interoperability_status"] for item in items)
        mapping_counts = Counter(item["mapping_status"] for item in items)
        out.append(
            {
                "domain": domain,
                "owner": DOMAIN_OWNERS.get(domain, f"{domain}_owner"),
                "facts_total": len(items),
                "mapped_count": int(mapping_counts.get("mapped") or 0),
                "partial_count": int(mapping_counts.get("partial") or 0),
                "documented_not_exported_count": int(mapping_counts.get("documented_not_exported_v1") or 0),
                "pass_count": int(status_counts.get("pass") or 0),
                "watch_count": int(status_counts.get("watch") or 0),
                "block_count": int(status_counts.get("block") or 0),
            }
        )
    return out


def _build_recommendations(summary: Mapping[str, Any]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if summary.get("critical_block_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Mapear facts criticos antes de exportar",
                "benefit": "Evita enviar a FHIR/OMOP hechos que cambian conducta sin semantica clara.",
            }
        )
    if summary.get("partial_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Asignar codigos LOINC/SNOMED/RxNorm especificos",
                "benefit": "Convierte el mapa inicial en export interoperable y reproducible.",
            }
        )
    recommendations.append(
        {
            "priority": "P2",
            "title": "Mantener el mapa como gate de cada nuevo FactSpec",
            "benefit": "Impide que el Ledger crezca con hechos no exportables o ambiguos.",
        }
    )
    return recommendations


def _row_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str, str]:
    status_rank = {"block": 0, "watch": 1, "pass": 2}
    return (
        status_rank.get(str(row.get("interoperability_status") or ""), 3),
        0 if row.get("blocking") else 1,
        str(row.get("domain") or ""),
        str(row.get("fact_key") or ""),
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
