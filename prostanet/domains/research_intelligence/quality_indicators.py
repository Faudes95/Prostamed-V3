from __future__ import annotations

from typing import Any

from prostanet.domains.research_intelligence.quality_indicator_repository import (
    list_results,
    replace_results,
    upsert_definition,
)


QI_DEFINITIONS = [
    {
        "indicator_key": "positive_margin_rate",
        "title": "Tasa de márgenes positivos post-RP",
        "clinical_definition": "Pacientes operados con margen positivo entre todos los pacientes sometidos a RP.",
        "benchmark_target": "<= 25%",
        "domain": "outcomes_operativos",
    },
    {
        "indicator_key": "time_to_treatment_documented",
        "title": "Tiempo a tratamiento documentado",
        "clinical_definition": "Pacientes con fecha diagnóstica y fecha de inicio de tratamiento trazables.",
        "benchmark_target": ">= 90%",
        "domain": "flujo_clinico",
    },
    {
        "indicator_key": "confirmatory_biopsy_as",
        "title": "Biopsia confirmatoria en vigilancia activa",
        "clinical_definition": "Pacientes en AS con biopsia confirmatoria documentada o agenda activa estructurada.",
        "benchmark_target": ">= 80%",
        "domain": "vigilancia_activa",
    },
    {
        "indicator_key": "advanced_biomarker_coverage",
        "title": "Cobertura de biomarcadores en avanzada",
        "clinical_definition": "Pacientes avanzados con biomarcadores moleculares trazables.",
        "benchmark_target": ">= 70%",
        "domain": "medicina_precision",
    },
    {
        "indicator_key": "bone_health_bundle",
        "title": "Bundle de salud ósea en elegibles",
        "clinical_definition": "Pacientes elegibles con DXA o protección ósea documentada.",
        "benchmark_target": ">= 75%",
        "domain": "salud_osea",
    },
    {
        "indicator_key": "salvage_rt_documented",
        "title": "Documentación de RT de salvamento cuando aplica",
        "clinical_definition": "Pacientes postlocales con ventana de rescate documentada.",
        "benchmark_target": ">= 80%",
        "domain": "radioterapia",
    },
]


def _pct(num: int, den: int) -> float:
    return round((num / den) * 100, 1) if den else 0.0


def build_quality_indicator_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    for definition in QI_DEFINITIONS:
        upsert_definition(definition)

    surgery_records = [record for record in records if record.get("surgery")]
    positive_margin_num = 0
    for record in surgery_records:
        surgery = record.get("surgery") or {}
        margin = str(surgery.get("margin_status") or surgery.get("surgical_margin") or "").lower()
        if margin in {"positive", "1", "positivo"}:
            positive_margin_num += 1

    timed_records = 0
    for record in records:
        if (record.get("identity") or {}).get("diagnosis_date") and (record.get("treatments") or []):
            first_tx = (record.get("treatments") or [{}])[0]
            if first_tx.get("start_date"):
                timed_records += 1

    as_records = [record for record in records if record.get("active_surveillance_protocol")]
    confirmatory_num = 0
    for record in as_records:
        protocol = record.get("active_surveillance_protocol") or {}
        if protocol.get("confirmatory_biopsy_done") or protocol.get("confirmatory_biopsy_due"):
            confirmatory_num += 1

    advanced_records = [
        record for record in records
        if (record.get("reconciled_state") or record.get("prior_history", {}).get("current_state")) in {
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "m0_crpc",
            "m1_crpc",
        }
    ]
    biomarker_num = 0
    for record in advanced_records:
        genomics = record.get("genomics") or {}
        if genomics.get("test_type") or genomics.get("hrr_overall") or (record.get("genomic_reports") or []):
            biomarker_num += 1

    bone_eligible = advanced_records
    bone_bundle_num = 0
    for record in bone_eligible:
        if record.get("bone_health") or record.get("bone_modifying_agent"):
            bone_bundle_num += 1

    salvage_candidates = [
        record for record in records
        if (record.get("reconciled_state") or record.get("prior_history", {}).get("current_state")) in {"recurrence_bcr", "post_prostatectomy"}
    ]
    salvage_num = 0
    for record in salvage_candidates:
        for course in record.get("radiotherapy_courses_detailed") or []:
            if str(course.get("rt_intent") or "").lower() in {"salvage", "salvamento"}:
                salvage_num += 1
                break

    results = [
        {
            "indicator_key": "positive_margin_rate",
            "numerator": positive_margin_num,
            "denominator": len(surgery_records),
            "percentage": _pct(positive_margin_num, len(surgery_records)),
            "trend": {},
        },
        {
            "indicator_key": "time_to_treatment_documented",
            "numerator": timed_records,
            "denominator": len(records),
            "percentage": _pct(timed_records, len(records)),
            "trend": {},
        },
        {
            "indicator_key": "confirmatory_biopsy_as",
            "numerator": confirmatory_num,
            "denominator": len(as_records),
            "percentage": _pct(confirmatory_num, len(as_records)),
            "trend": {},
        },
        {
            "indicator_key": "advanced_biomarker_coverage",
            "numerator": biomarker_num,
            "denominator": len(advanced_records),
            "percentage": _pct(biomarker_num, len(advanced_records)),
            "trend": {},
        },
        {
            "indicator_key": "bone_health_bundle",
            "numerator": bone_bundle_num,
            "denominator": len(bone_eligible),
            "percentage": _pct(bone_bundle_num, len(bone_eligible)),
            "trend": {},
        },
        {
            "indicator_key": "salvage_rt_documented",
            "numerator": salvage_num,
            "denominator": len(salvage_candidates),
            "percentage": _pct(salvage_num, len(salvage_candidates)),
            "trend": {},
        },
    ]
    replace_results(results)
    return {
        "definitions": QI_DEFINITIONS,
        "results": list_results(),
    }
