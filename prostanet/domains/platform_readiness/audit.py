"""Read-only platform readiness audit.

This module inspects schema coverage, canonical fact coverage, aliases,
route registration and lightweight database shape. It deliberately does not
write patient data, create orders, train models or run treatment logic.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

from prostanet.shared.clinical_fact_registry import FACT_SPECS, FactSpec
from prostanet.shared.pivotal_gate_disclosure import (
    PIVOTAL_GATE_GROUP,
    filter_schema_for_wizard,
)
from prostanet.shared.utc_time import utc_now_iso


AUDIT_VERSION = "clinical_platform_readiness_v1"

CRITICAL_ROUTE_CONTRACTS = (
    {"rule": "/clinical-hub", "method": "GET", "surface": "clinical_entry"},
    {"rule": "/patients", "method": "GET", "surface": "cohort"},
    {"rule": "/dashboard", "method": "GET", "surface": "dashboard"},
    {"rule": "/loop-monitor", "method": "GET", "surface": "loop_monitor"},
    {"rule": "/wizard/<module_id>", "method": "GET", "surface": "wizard"},
    {"rule": "/api/modules", "method": "GET", "surface": "schema"},
    {"rule": "/api/modules/<module_id>/schema", "method": "GET", "surface": "schema"},
    {"rule": "/api/modules/<module_id>/evaluate", "method": "POST", "surface": "evaluate"},
    {"rule": "/api/clinical-assessments/draft", "method": "POST", "surface": "draft"},
    {"rule": "/api/register_patient", "method": "POST", "surface": "registration"},
    {"rule": "/patient_profile/<nss>", "method": "GET", "surface": "profile_v2"},
    {"rule": "/api/patients/<patient_ref>/clinical-fact-ledger/summary", "method": "GET", "surface": "clinical_fact_ledger"},
    {"rule": "/api/patients/<patient_ref>/decision-today", "method": "GET", "surface": "decision_today"},
    {"rule": "/api/redecision/today", "method": "GET", "surface": "redecision"},
    {"rule": "/api/population/cohort-dashboard", "method": "GET", "surface": "population"},
    {"rule": "/api/platform-readiness/audit", "method": "GET", "surface": "readiness"},
    {"rule": "/api/platform-readiness/capture-integrity", "method": "GET", "surface": "capture_integrity"},
    {"rule": "/api/platform-readiness/v2-persistence-closure", "method": "GET", "surface": "v2_persistence_closure"},
    {"rule": "/api/platform-readiness/v2-treatment-value-closure", "method": "GET", "surface": "v2_treatment_value_closure"},
    {"rule": "/api/platform-readiness/ledger-release-gate", "method": "GET", "surface": "release_gate"},
    {"rule": "/api/platform-readiness/ledger-persistence-matrix", "method": "GET", "surface": "persistence_matrix"},
    {"rule": "/api/platform-readiness/interoperability-map", "method": "GET", "surface": "interoperability"},
    {"rule": "/api/platform-readiness/deidentified-export-contract", "method": "GET", "surface": "deidentified_export"},
    {"rule": "/api/platform-readiness/research-pack-materializer", "method": "GET", "surface": "research_pack_materializer"},
    {"rule": "/api/platform-readiness/research-pack-materializer/freeze", "method": "POST", "surface": "research_pack_materializer"},
    {"rule": "/api/platform-readiness/research-pack-materializer/freezes", "method": "GET", "surface": "research_pack_governance"},
    {"rule": "/api/platform-readiness/prospective-pilot-governance", "method": "GET", "surface": "prospective_pilot_governance"},
    {"rule": "/api/platform-readiness/nas-pilot-evidence-vault", "method": "GET", "surface": "nas_pilot_evidence_vault"},
    {"rule": "/api/platform-readiness/nas-pilot-evidence-vault/attest", "method": "POST", "surface": "nas_pilot_evidence_vault"},
    {"rule": "/api/platform-readiness/pilot-adoption-command-center", "method": "GET", "surface": "pilot_adoption_command_center"},
    {"rule": "/api/platform-readiness/prospective-gap-closure-huddle", "method": "GET", "surface": "prospective_gap_closure_huddle"},
    {"rule": "/api/platform-readiness/prospective-gap-closure-huddle/close", "method": "POST", "surface": "prospective_gap_closure_huddle"},
    {"rule": "/api/platform-readiness/prospective-gap-closure-huddle/export", "method": "GET", "surface": "prospective_gap_closure_huddle"},
    {"rule": "/api/platform-readiness/ape-longitudinal-completion-sprint", "method": "GET", "surface": "ape_longitudinal_completion_sprint"},
    {"rule": "/api/platform-readiness/ape-longitudinal-completion-sprint/export", "method": "GET", "surface": "ape_longitudinal_completion_sprint"},
    {"rule": "/api/platform-readiness/world-class-benchmark", "method": "GET", "surface": "world_class_benchmark"},
    {"rule": "/api/platform-readiness/real-world-sample-maturity", "method": "GET", "surface": "real_world_sample_maturity"},
    {"rule": "/api/platform-readiness/real-world-sample-maturity/export", "method": "GET", "surface": "real_world_sample_maturity"},
    {"rule": "/api/platform-readiness/prospective-real-world-completion-queue", "method": "GET", "surface": "prospective_real_world_completion_queue"},
    {"rule": "/api/platform-readiness/prospective-real-world-completion-queue/export", "method": "GET", "surface": "prospective_real_world_completion_queue"},
    {"rule": "/api/platform-readiness/real-world-pilot-packet", "method": "GET", "surface": "real_world_pilot_packet"},
    {"rule": "/api/platform-readiness/real-world-pilot-packet/download", "method": "GET", "surface": "real_world_pilot_packet"},
    {"rule": "/api/platform-readiness/real-world-pilot-execution-log", "method": "GET", "surface": "real_world_pilot_execution_log"},
    {"rule": "/api/platform-readiness/real-world-pilot-execution-log/download", "method": "GET", "surface": "real_world_pilot_execution_log"},
    {"rule": "/api/platform-readiness/real-world-first-patient-launch-mode", "method": "GET", "surface": "real_world_first_patient_launch_mode"},
    {"rule": "/api/platform-readiness/real-world-first-patient-launch-mode/download", "method": "GET", "surface": "real_world_first_patient_launch_mode"},
    {"rule": "/api/platform-readiness/real-world-launch-flow-verifier", "method": "GET", "surface": "real_world_launch_flow_verifier"},
    {"rule": "/api/platform-readiness/real-world-launch-flow-verifier/download", "method": "GET", "surface": "real_world_launch_flow_verifier"},
    {"rule": "/api/platform-readiness/external-validation-worklist", "method": "GET", "surface": "external_validation_worklist"},
    {"rule": "/api/platform-readiness/external-validation-worklist/export", "method": "GET", "surface": "external_validation_worklist"},
)

CONTROL_FIELD_PREFIXES = ("show_", "open_", "enable_", "debug_", "_")
COMPOSITE_FIELD_TYPES = {
    "epic26_questionnaire",
    "gleason_profile",
    "metastatic_components",
    "occam_life_expectancy",
}
WIZARD_ALIAS_SUPPRESSION_TARGETS = {
    "alp": "alkaline_phosphatase_u_l",
    "alkaline_phosphatase": "alkaline_phosphatase_u_l",
    "ldh": "ldh_u_l",
    "serum_ldh": "ldh_u_l",
    "hemoglobin": "hemoglobin_g_dl",
    "hgb": "hemoglobin_g_dl",
    "hb": "hemoglobin_g_dl",
    "creatinine": "creatinine_mg_dl",
}
CORE_CLINICAL_ROLES = {
    "required",
    "minimum_decision",
    "decision_refiner",
    "decision_changing",
    "clinical_state",
    "blocking",
}

DOCUMENTED_NON_SCHEMA_FACT_SOURCES = {
    "testosterone": {
        "source": "longitudinal_capture:testosterone_history",
        "surface": "longitudinal_capture",
        "note": "Captured through longitudinal biomarker append and stage visits; aliases include testosterone_value.",
    },
    "testosterone_sample_date": {
        "source": "intake_v2:crpc_verification + longitudinal_capture:testosterone_history",
        "surface": "intake_v2",
        "note": "Captured with CRPC verification and testosterone-history append; used to detect stale castration evidence.",
    },
    "known_cancer_diagnosis": {
        "source": "clinical_hub:state_classifier",
        "surface": "clinical_hub",
        "note": "Captured before module selection to decide diagnostic vs confirmed-cancer route.",
    },
    "metastatic_stage_resolved": {
        "source": "derived:resolve_metastatic_state_context",
        "surface": "state_classifier",
        "note": "Derived from staging/imaging context and stored as a reconciled metastatic fact.",
    },
    "metastatic_detection_basis": {
        "source": "derived:resolve_metastatic_state_context",
        "surface": "state_classifier",
        "note": "Derived from conventional imaging vs PSMA-only detection basis.",
    },
    "metastasis_assessment_date": {
        "source": "longitudinal_capture:metastatic_distribution + followup_agenda",
        "surface": "longitudinal_capture",
        "note": "Captured when metastatic composition or restaging evidence is appended; reused by reconciled state and V2 timelines.",
    },
    "metastasis_document_source": {
        "source": "longitudinal_capture:metastatic_distribution + followup_agenda",
        "surface": "longitudinal_capture",
        "note": "Captures source document/imaging basis for metastatic distribution.",
    },
    "confirmatory_biopsy_done": {
        "source": "active_surveillance_followup + longitudinal_capture:biopsy",
        "surface": "followup_agenda",
        "note": "Captured in active-surveillance and biopsy follow-up workflows rather than the initial module schema.",
    },
    "confirmatory_biopsy_date": {
        "source": "active_surveillance_followup + longitudinal_capture:biopsy",
        "surface": "followup_agenda",
        "note": "Date paired with confirmatory biopsy status for surveillance closure and re-decision.",
    },
    "targeted_biopsy_status": {
        "source": "clinical_field_router:biopsy_detail + intake_v2:biopsy_detail",
        "surface": "intake_v2",
        "note": "Captured as targeted/prior mpMRI-guided biopsy status in progressive biopsy detail flows.",
    },
    "gleason_at_rp": {
        "source": "longitudinal_capture:post_rp_pathology + document_ingestion:surgery_summary",
        "surface": "longitudinal_capture",
        "note": "Post-RP specimen pathology is captured after surgery or parsed from surgical pathology documents.",
    },
    "gleason_primary_pattern_at_rp": {
        "source": "longitudinal_capture:post_rp_pathology + document_ingestion:surgery_summary",
        "surface": "longitudinal_capture",
        "note": "Post-RP primary Gleason pattern is not recaptured in baseline wizard; it belongs to post-operative pathology capture.",
    },
    "gleason_secondary_pattern_at_rp": {
        "source": "longitudinal_capture:post_rp_pathology + document_ingestion:surgery_summary",
        "surface": "longitudinal_capture",
        "note": "Post-RP secondary Gleason pattern is captured with surgical specimen data.",
    },
    "tumor_stage_at_rp": {
        "source": "longitudinal_capture:post_rp_pathology + document_ingestion:surgery_summary",
        "surface": "longitudinal_capture",
        "note": "Pathologic tumor stage is captured from RP pathology and surfaced in profile V2 salvage context.",
    },
    "margin_status": {
        "source": "longitudinal_capture:post_rp_pathology + document_ingestion:surgery_summary",
        "surface": "longitudinal_capture",
        "note": "Surgical margin status is captured after RP or parsed from pathology documents.",
    },
    "percent_positive_cores": {
        "source": "structured_biopsy_sessions + intake_v2:biopsy_detail",
        "surface": "intake_v2",
        "note": "Derived from structured biopsy sessions or captured as biopsy detail when source totals are available.",
    },
    "genomic_classifier_report_date": {
        "source": "intake_v2:genomic_detail + followup_agenda:local_decision",
        "surface": "intake_v2",
        "note": "Captured with genomic classifier result/date and reused for freshness in local decision evidence.",
    },
    "psma_pet_status": {
        "source": "intake_v2:imaging_detail + clinical_field_router:psma",
        "surface": "intake_v2",
        "note": "Granular PSMA status is captured in imaging detail and stage-aware PSMA capture, not as a default wizard field.",
    },
    "psma_study_date": {
        "source": "intake_v2:imaging_detail + longitudinal_capture:psma",
        "surface": "intake_v2",
        "note": "PSMA study date is captured as PSMA-PET date and normalized into psma_study_date.",
    },
    "psma_lesion_count": {
        "source": "intake_v2:imaging_detail + longitudinal_capture:psma",
        "surface": "intake_v2",
        "note": "PSMA-avid lesion count is captured in imaging detail for oligometastatic and RLT readiness.",
    },
    "psma_tracer": {
        "source": "intake_v2:imaging_detail + longitudinal_capture:psma",
        "surface": "intake_v2",
        "note": "Tracer is captured with PSMA-PET details for trial/RLT traceability.",
    },
    "epic26_urinary_incontinence_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived from the EPIC-26 composite questionnaire and hidden derived fields, avoiding manual recapture.",
    },
    "epic26_urinary_irritative_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived from EPIC-26 urinary irritative/obstructive items.",
    },
    "epic26_urinary_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived aggregate urinary domain used as legacy-compatible PRO summary.",
    },
    "epic26_sexual_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived from EPIC-26 sexual items and reused for local modality tradeoff.",
    },
    "epic26_bowel_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived from EPIC-26 bowel items and reused for RT toxicity tradeoff.",
    },
    "epic26_hormonal_domain": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Derived from EPIC-26 hormonal items for ADT/systemic baseline context.",
    },
    "epic26_overall_urinary_bother": {
        "source": "wizard_epic26_questionnaire + intake_v2:pros_baseline",
        "surface": "wizard_v2",
        "note": "Captured as EPIC-26 global urinary bother alongside derived domain scores.",
    },
    "primary_ancestry": {
        "source": "registration_context:cohorte_mexico",
        "surface": "registration",
        "note": "Optional self-reported ancestry captured for evidence calibration and population analytics; never gates treatment access.",
    },
    "psma_pet_local_access": {
        "source": "registration_context:advanced_access_mexico",
        "surface": "registration",
        "note": "Local access field captured for Mexican real-world feasibility and recommendation labeling.",
    },
    "lu_psma_local_access": {
        "source": "registration_context:advanced_access_mexico",
        "surface": "registration",
        "note": "Local Lu-PSMA access field supports feasibility/reranking without hiding clinical options.",
    },
    "arsi_local_access": {
        "source": "registration_context:advanced_access_mexico",
        "surface": "registration",
        "note": "ARSI local access field supports institutional access analytics and recommendation context.",
    },
}


def build_platform_readiness_audit(
    registry: Any | None = None,
    *,
    registered_rules: Iterable[Any] | None = None,
    scope: str = "full",
    field_limit: int = 300,
) -> dict[str, Any]:
    """Build a read-only readiness bundle for clinical platform hardening."""
    if registry is None:
        from prostanet.application.module_registry import ModuleRegistry

        registry = ModuleRegistry()

    scope_key = str(scope or "full").strip().lower()
    include_rows = scope_key != "summary"
    module_ids = _module_ids(registry)
    fact_lookup = _build_fact_lookup(FACT_SPECS)
    schema_inventory = _build_schema_inventory(registry, module_ids, fact_lookup)
    field_matrix, canonical_seen = _build_field_matrix(
        schema_inventory["canonical_appearances"],
        fact_lookup,
        field_limit=field_limit,
    )
    gaps = _build_gaps(schema_inventory, canonical_seen)
    recapture = _build_recapture_aliases(schema_inventory["canonical_appearances"])
    route_contracts = _build_route_contracts(registered_rules or [])
    db_snapshot = _build_db_snapshot()
    summary = _build_summary(
        module_inventory=schema_inventory["modules"],
        fact_matrix=field_matrix,
        gaps=gaps,
        recapture=recapture,
        route_contracts=route_contracts,
    )
    recommendations = _build_recommendations(summary, gaps, recapture, route_contracts)

    payload: dict[str, Any] = {
        "available": True,
        "source": "clinical_platform_readiness_audit",
        "version": AUDIT_VERSION,
        "computed_at": utc_now_iso(),
        "scope": "summary" if scope_key == "summary" else "full",
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "summary": summary,
        "route_contracts": route_contracts,
        "database_snapshot": db_snapshot,
        "recommendations": recommendations,
    }
    if include_rows:
        payload.update(
            {
                "modules": schema_inventory["modules"],
                "field_matrix": field_matrix,
                "gaps": gaps,
                "recapture_aliases": recapture,
                "unregistered_schema_fields": schema_inventory["unregistered_schema_fields"][:field_limit],
            }
        )
    return payload


def _module_ids(registry: Any) -> list[str]:
    ids: list[str] = []
    try:
        ids.extend(str(item.get("module") or "") for item in registry.list_modules())
    except Exception:
        pass
    services = getattr(registry, "services", {}) or {}
    ids.extend(str(module_id) for module_id in services.keys())
    normalized: list[str] = []
    seen: set[str] = set()
    for module_id in ids:
        if not module_id or module_id in seen:
            continue
        seen.add(module_id)
        normalized.append(module_id)
    return normalized


def _build_fact_lookup(specs: Mapping[str, FactSpec]) -> dict[str, Any]:
    by_field: dict[str, set[str]] = defaultdict(set)
    aliases_by_fact: dict[str, set[str]] = {}
    for fact_key, spec in specs.items():
        aliases = {str(alias) for alias in spec.legacy_aliases or () if str(alias).strip()}
        aliases_by_fact[fact_key] = aliases
        by_field[fact_key].add(fact_key)
        for alias in aliases:
            by_field[alias].add(fact_key)
    return {"by_field": {key: sorted(values) for key, values in by_field.items()}, "aliases_by_fact": aliases_by_fact}


def _build_schema_inventory(
    registry: Any,
    module_ids: list[str],
    fact_lookup: Mapping[str, Any],
) -> dict[str, Any]:
    canonical_appearances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unregistered_schema_fields: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    schema_errors: list[dict[str, str]] = []
    by_field = fact_lookup["by_field"]

    for module_id in module_ids:
        try:
            schema = registry.get_module_schema(module_id)
        except Exception as exc:
            schema_errors.append({"module": module_id, "error": str(exc)})
            continue

        fields = [dict(field or {}) for field in schema.get("fields") or []]
        field_names = [str(field.get("name") or "") for field in fields if str(field.get("name") or "")]
        field_name_set = set(field_names)
        duplicate_fields = _duplicate_field_names_requiring_schema_action(fields)
        canonical_count = 0
        alias_count = 0
        unregistered_core_count = 0
        pivotal_count = 0
        required_count = 0
        derived_count = 0

        for field in fields:
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            field_for_appearance = _mark_contextual_alias_if_canonical_present(
                field,
                field_names=field_name_set,
            )
            is_pivotal = str(field.get("group") or "").strip() == PIVOTAL_GATE_GROUP
            pivotal_count += 1 if is_pivotal else 0
            required_count += 1 if bool(field.get("required")) else 0
            derived_count += 1 if field_for_appearance.get("derived_from") else 0
            canonicals = list(by_field.get(name) or [])
            if canonicals:
                canonical_count += 1
                alias_count += 1 if name not in canonicals else 0
                for canonical in canonicals:
                    canonical_appearances[canonical].append(
                        _appearance(module_id, field_for_appearance, canonical=canonical)
                    )
                continue
            if _is_core_schema_field(field):
                unregistered_core_count += 1
                unregistered_schema_fields.append(
                    {
                        "module": module_id,
                        "field_name": name,
                        "label": str(field.get("label") or name),
                        "field_type": str(field.get("field_type") or ""),
                        "clinical_role": str(field.get("clinical_role") or ""),
                        "group": str(field.get("group") or ""),
                        "severity": "moderate" if bool(field.get("required")) else "low",
                    }
                )

        try:
            wizard_schema = filter_schema_for_wizard(schema, module_id)
            wizard_count = len(wizard_schema.get("fields") or [])
        except Exception:
            wizard_count = len(fields)

        modules.append(
            {
                "module": module_id,
                "title": str(schema.get("title") or module_id),
                "fields_count": len(fields),
                "wizard_default_fields_count": wizard_count,
                "advanced_fields_hidden_by_default": max(len(fields) - wizard_count, 0),
                "canonical_mapped_fields_count": canonical_count,
                "legacy_alias_fields_count": alias_count,
                "unregistered_core_fields_count": unregistered_core_count,
                "duplicate_fields": duplicate_fields,
                "duplicate_fields_count": len(duplicate_fields),
                "pivotal_gate_fields_count": pivotal_count,
                "required_fields_count": required_count,
                "derived_fields_count": derived_count,
            }
        )

    return {
        "modules": modules,
        "schema_errors": schema_errors,
        "canonical_appearances": canonical_appearances,
        "unregistered_schema_fields": sorted(
            unregistered_schema_fields,
            key=lambda item: (item["severity"], item["module"], item["field_name"]),
            reverse=True,
        ),
    }


def _mark_contextual_alias_if_canonical_present(
    field: Mapping[str, Any],
    *,
    field_names: set[str],
) -> dict[str, Any]:
    item = dict(field or {})
    name = str(item.get("name") or "")
    canonical = WIZARD_ALIAS_SUPPRESSION_TARGETS.get(name)
    if canonical and canonical in field_names:
        item["suppressed_alias_of_canonical_fact"] = canonical
        item["derived_from"] = list(dict.fromkeys([*(item.get("derived_from") or []), canonical]))
    return item


def _appearance(module_id: str, field: Mapping[str, Any], *, canonical: str) -> dict[str, Any]:
    name = str(field.get("name") or "")
    return {
        "module": module_id,
        "surface": f"wizard:{module_id}",
        "field_name": name,
        "canonical_fact": canonical,
        "is_alias": name != canonical,
        "label": str(field.get("label") or name),
        "field_type": str(field.get("field_type") or ""),
        "required": bool(field.get("required")),
        "clinical_role": str(field.get("clinical_role") or ""),
        "group": str(field.get("group") or ""),
        "derived_from": list(field.get("derived_from") or []),
        "suppressed_alias_of_canonical_fact": str(field.get("suppressed_alias_of_canonical_fact") or ""),
        "pivotal_gate": str(field.get("group") or "").strip() == PIVOTAL_GATE_GROUP,
    }


def _build_field_matrix(
    canonical_appearances: Mapping[str, list[dict[str, Any]]],
    fact_lookup: Mapping[str, Any],
    *,
    field_limit: int,
) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    aliases_by_fact = fact_lookup["aliases_by_fact"]
    canonical_seen = set(canonical_appearances.keys())

    for fact_key, spec in FACT_SPECS.items():
        appearances = list(canonical_appearances.get(fact_key) or [])
        documented_source = dict(DOCUMENTED_NON_SCHEMA_FACT_SOURCES.get(fact_key) or {})
        modules = sorted({item["module"] for item in appearances})
        alias_fields = sorted({item["field_name"] for item in appearances if item.get("is_alias")})
        direct_fields = sorted({item["field_name"] for item in appearances if not item.get("is_alias")})
        rows.append(
            {
                "fact_key": fact_key,
                "domain": spec.domain,
                "value_type": spec.value_type,
                "blocking": bool(spec.blocking),
                "legacy_aliases": sorted(aliases_by_fact.get(fact_key) or []),
                "consumers": list(spec.consumers or []),
                "schema_appearances_count": len(appearances),
                "modules_count": len(modules),
                "modules": modules,
                "direct_schema_fields": direct_fields,
                "legacy_alias_schema_fields": alias_fields,
                "coverage_status": (
                    "captured_or_displayed" if appearances else "not_seen_in_module_schemas"
                    if not documented_source else "documented_non_schema_source"
                ),
                "documented_non_schema_source": documented_source,
                "appearances": appearances[:12],
            }
        )
    rows.sort(
        key=lambda item: (
            0 if item["blocking"] and item["schema_appearances_count"] == 0 else 1,
            item["domain"],
            item["fact_key"],
        )
    )
    return rows[: max(1, int(field_limit or 300))], canonical_seen


def _build_gaps(
    schema_inventory: Mapping[str, Any],
    canonical_seen: set[str],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for fact_key, spec in FACT_SPECS.items():
        if spec.blocking and fact_key not in canonical_seen:
            if fact_key in DOCUMENTED_NON_SCHEMA_FACT_SOURCES:
                continue
            gaps.append(
                {
                    "severity": "high",
                    "category": "blocking_fact_not_in_module_schemas",
                    "field": fact_key,
                    "domain": spec.domain,
                    "message": "Blocking canonical fact has consumers but was not seen in module schemas.",
                    "recommended_action": "Map capture source or document that it is only captured longitudinally.",
                }
            )

    for item in schema_inventory.get("unregistered_schema_fields") or []:
        if item.get("severity") == "moderate":
            gaps.append(
                {
                    "severity": "moderate",
                    "category": "schema_field_without_fact_spec",
                    "field": item["field_name"],
                    "module": item["module"],
                    "message": "Core schema field lacks a canonical FactSpec mapping.",
                    "recommended_action": "Add FactSpec, mark as display/control, or map to an existing alias.",
                }
            )

    for module in schema_inventory.get("modules") or []:
        if module.get("duplicate_fields_count"):
            gaps.append(
                {
                    "severity": "moderate",
                    "category": "duplicate_field_name_in_schema",
                    "module": module["module"],
                    "fields": module.get("duplicate_fields") or [],
                    "message": "Module schema repeats one or more field names.",
                    "recommended_action": "Keep one owner or make the repeated field conditional/read-only.",
                }
            )
    gaps.sort(key=lambda item: _severity_rank(item.get("severity")), reverse=True)
    return gaps


def _build_recapture_aliases(
    canonical_appearances: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fact_key, appearances in canonical_appearances.items():
        if not appearances:
            continue
        by_module: dict[str, set[str]] = defaultdict(set)
        appearances_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in appearances:
            by_module[item["module"]].add(item["field_name"])
            appearances_by_module[item["module"]].append(item)
        same_module = {
            module: active_names
            for module, module_appearances in appearances_by_module.items()
            if len(active_names := _active_recapture_names(module_appearances)) > 1
        }
        contextual_same_module = {
            module: sorted(names)
            for module, names in by_module.items()
            if len(names) > 1 and module not in same_module
        }
        all_names = sorted({item["field_name"] for item in appearances})
        alias_names = sorted({item["field_name"] for item in appearances if item.get("is_alias")})
        if same_module or contextual_same_module or alias_names:
            rows.append(
                {
                    "fact_key": fact_key,
                    "severity": "moderate" if same_module else "low",
                    "field_names_seen": all_names,
                    "alias_field_names_seen": alias_names,
                    "same_module_recapture": same_module,
                    "contextual_same_module_alias": contextual_same_module,
                    "modules": sorted(by_module),
                    "message": (
                        "Canonical fact appears through multiple names in at least one module."
                        if same_module
                        else "Canonical fact has contextual aliases hidden behind derived or pivotal-gate support."
                        if contextual_same_module
                        else "Canonical fact appears through legacy aliases across schemas."
                    ),
                }
            )
    rows.sort(key=lambda item: (_severity_rank(item["severity"]), item["fact_key"]), reverse=True)
    return rows


def _active_recapture_names(appearances: list[dict[str, Any]]) -> list[str]:
    active_names = {
        str(item.get("field_name") or "")
        for item in appearances
        if not item.get("pivotal_gate") and not item.get("derived_from")
    }
    return sorted(name for name in active_names if name)


def _build_route_contracts(registered_rules: Iterable[Any]) -> dict[str, Any]:
    normalized: dict[str, set[str]] = defaultdict(set)
    for raw in registered_rules:
        rule = getattr(raw, "rule", None) or (raw.get("rule") if isinstance(raw, Mapping) else None)
        methods = getattr(raw, "methods", None) or (raw.get("methods") if isinstance(raw, Mapping) else None) or []
        if not rule:
            continue
        for method in methods:
            normalized[str(rule)].add(str(method).upper())

    rows: list[dict[str, Any]] = []
    for contract in CRITICAL_ROUTE_CONTRACTS:
        rule = contract["rule"]
        method = contract["method"]
        available = method in normalized.get(rule, set())
        rows.append({**contract, "registered": available})
    missing = [row for row in rows if not row["registered"]]
    return {
        "critical_route_count": len(rows),
        "registered_count": len(rows) - len(missing),
        "missing_count": len(missing),
        "missing": missing,
        "routes": rows,
    }


def _build_db_snapshot() -> dict[str, Any]:
    try:
        import sqlite3
        import tracking_db

        db_path = tracking_db.get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            counts: dict[str, int | None] = {}
            for table in (
                "patient_identity",
                "patient_clinical_facts",
                "clinical_assessments",
                "prior_clinical_history",
                "patient_events",
                "treatment_courses",
                "treatment_dose_administrations",
            ):
                if table not in tables:
                    counts[table] = None
                    continue
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return {
                "available": True,
                "db_path": db_path,
                "tables_present": sorted(tables),
                "counts": counts,
                "read_only_probe": True,
            }
        finally:
            conn.close()
    except Exception as exc:
        return {"available": False, "error": str(exc), "read_only_probe": True}


def _build_summary(
    *,
    module_inventory: list[dict[str, Any]],
    fact_matrix: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    recapture: list[dict[str, Any]],
    route_contracts: Mapping[str, Any],
) -> dict[str, Any]:
    high_gaps = sum(1 for item in gaps if item.get("severity") == "high")
    moderate_gaps = sum(1 for item in gaps if item.get("severity") == "moderate")
    facts_seen = sum(1 for item in fact_matrix if item.get("schema_appearances_count"))
    total_facts = len(FACT_SPECS)
    route_missing = int(route_contracts.get("missing_count") or 0)
    score = max(0, 100 - (high_gaps * 5) - (moderate_gaps * 2) - (route_missing * 4))
    return {
        "modules_scanned": len(module_inventory),
        "module_fields_total": sum(int(item.get("fields_count") or 0) for item in module_inventory),
        "wizard_default_fields_total": sum(int(item.get("wizard_default_fields_count") or 0) for item in module_inventory),
        "advanced_fields_hidden_by_default_total": sum(
            int(item.get("advanced_fields_hidden_by_default") or 0) for item in module_inventory
        ),
        "fact_specs_total": total_facts,
        "canonical_facts_seen_in_schemas": facts_seen,
        "canonical_schema_coverage_pct": round((facts_seen / total_facts) * 100, 1) if total_facts else 0.0,
        "high_gap_count": high_gaps,
        "moderate_gap_count": moderate_gaps,
        "recapture_alias_count": len(recapture),
        "same_module_recapture_count": sum(1 for item in recapture if item.get("same_module_recapture")),
        "critical_routes_missing_count": route_missing,
        "readiness_score": score,
        "readiness_status": "release_blocked" if high_gaps or route_missing else ("needs_hardening" if moderate_gaps else "ready_for_next_layer"),
    }


def _build_recommendations(
    summary: Mapping[str, Any],
    gaps: list[dict[str, Any]],
    recapture: list[dict[str, Any]],
    route_contracts: Mapping[str, Any],
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if summary.get("high_gap_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Close blocking canonical fact gaps",
                "benefit": "Prevents DECISION HOY from ranking therapy with missing decision-changing data.",
            }
        )
    if route_contracts.get("missing_count"):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Restore critical route registration",
                "benefit": "Keeps backend and UI surfaces connected during normal startup.",
            }
        )
    if summary.get("same_module_recapture_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Resolve same-module recapture aliases",
                "benefit": "Reduces duplicate capture and inconsistent persistence for the same clinical fact.",
            }
        )
    if gaps and not summary.get("high_gap_count"):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Map unregistered core schema fields",
                "benefit": "Makes source, freshness and downstream consumers auditable.",
            }
        )
    if recapture:
        recommendations.append(
            {
                "priority": "P2",
                "title": "Convert alias inventory into a canonical field dictionary",
                "benefit": "Creates the base for mCODE/FHIR/OMOP mapping and research exports.",
            }
        )
    recommendations.append(
        {
            "priority": "P2",
            "title": "Run this audit as a release gate before adding modules",
            "benefit": "Keeps future clinical logic from growing on top of broken persistence or stale UI contracts.",
        }
    )
    return recommendations


def _is_core_schema_field(field: Mapping[str, Any]) -> bool:
    name = str(field.get("name") or "").strip()
    if not name or name.startswith(CONTROL_FIELD_PREFIXES):
        return False
    if str(field.get("group") or "").strip() == PIVOTAL_GATE_GROUP:
        return False
    field_type = str(field.get("field_type") or "").strip().lower()
    if field_type in {"hidden", "section", "display"} | COMPOSITE_FIELD_TYPES:
        return False
    if field.get("derived_from"):
        return False
    role = str(field.get("clinical_role") or "").strip().lower()
    if role in CORE_CLINICAL_ROLES:
        return True
    if bool(field.get("required")):
        return True
    try:
        if float(field.get("group_order") or 0) <= 10 and field.get("evidence_tags"):
            return True
    except Exception:
        pass
    return False


def _duplicate_field_names_requiring_schema_action(fields: Iterable[Mapping[str, Any]]) -> list[str]:
    by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for field in fields:
        name = str(field.get("name") or "").strip()
        if name:
            by_name[name].append(field)

    duplicates: list[str] = []
    for name, appearances in by_name.items():
        if len(appearances) <= 1:
            continue
        active_owners = [
            item
            for item in appearances
            if _is_core_schema_field(item) and not _is_contextual_duplicate_owner(item)
        ]
        if len(active_owners) > 1:
            duplicates.append(name)
    return sorted(duplicates)


def _is_contextual_duplicate_owner(field: Mapping[str, Any]) -> bool:
    if field.get("derived_from") or field.get("conditional_visibility"):
        return True
    group = str(field.get("group") or "").strip()
    if group == PIVOTAL_GATE_GROUP:
        return True
    try:
        return float(field.get("group_order") or 0) >= 80
    except Exception:
        return False


def _severity_rank(value: Any) -> int:
    return {"high": 3, "moderate": 2, "low": 1}.get(str(value or "").lower(), 0)
