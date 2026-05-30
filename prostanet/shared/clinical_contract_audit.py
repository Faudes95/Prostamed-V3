"""Clinical contract audit for gates, capture surfaces and trial evaluators.

This module is intentionally read-only. It does not decide treatment. It
answers whether each pivotal gate has a documented path from trigger fields to
one of the productive capture layers introduced by the official classifier:

- classifier
- initial state wizard
- longitudinal follow-up

The goal is to keep the official classifier compact while proving that safety,
biomarker, toxicity, imaging and treatment-line refiners still have an
appropriate home in wizard or longitudinal capture.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping


CONTRACT_STATES = (
    "screening",
    "diagnostic_workup",
    "post_negative_biopsy_followup",
    "localized_initial",
    "post_prostatectomy",
    "recurrence_bcr",
    "post_radiotherapy_followup",
    "post_radiotherapy_or_local_salvage",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
    "focal_therapy",
    "survivorship_and_toxicity_followup",
)


FIELD_ALIAS_FAMILIES: dict[str, set[str]] = {
    "psa_value": {
        "psa_value",
        "psa",
        "psa_current",
        "psa_baseline",
        "baseline_psa",
        "psa_baseline_ng_ml",
        "bcr_psa",
        "psa_postop",
    },
    "testosterone_value": {
        "testosterone_value",
        "testosterone_current",
        "testosterone",
        "testosterone_baseline",
        "castrate_testosterone_status",
        "castrate_testosterone_status_confirmed",
    },
    "creatinine_clearance": {
        "creatinine_clearance",
        "creatinine_clearance_ml_min",
        "crcl_ml_min",
        "cockcroft_gault_crcl",
        "egfr",
        "egfr_ml_min",
        "egfr_ml_min_1_73m2",
        "gfr_ml_min",
    },
    "peripheral_neuropathy_grade": {
        "peripheral_neuropathy_grade",
        "neuropathy_grade",
        "neuropathy_ctcae_grade",
        "taxane_neuropathy_grade",
    },
    "polysorbate_hypersensitivity": {
        "polysorbate_hypersensitivity",
        "polysorbate_hypersensitivity_history",
        "hypersensitivity_polysorbate",
    },
    "cognitive": {
        "cognitive_disturbance_ctcae_grade",
        "cognitive_decline_grade2_documented",
        "cognitive_decline_documented",
        "cognitive_concerns_documented",
        "cognitive_concerns_baseline",
        "geriatric_cognitive_concerns",
        "mmse_baseline",
        "mmse_baseline_score",
        "mmse_current",
        "moca_baseline",
        "moca_baseline_score",
        "moca_current",
        "cognitive_recovered_for_arpi",
        "cognitive_baseline_normalized_for_arsi_elderly",
    },
    "ecog": {
        "ecog_score",
        "ecog",
        "ecog_current",
        "ecog_status",
        "performance_status_ecog",
    },
    "metastatic": {
        "metastasis_site",
        "metastatic_site",
        "bone_metastasis_count",
        "bone_mets_count",
        "bone_lesion_count_total",
        "bone_appendicular_count",
        "visceral_metastasis",
        "visceral_mets",
        "visceral_metastasis_present",
        "nonregional_nodal_count",
    },
}


PERSISTED_BASELINE_OR_FOLLOWUP_FIELDS = {
    "peripheral_neuropathy_grade",
    "egfr",
    "egfr_ml_min",
    "creatinine_clearance",
    "creatinine_clearance_ml_min",
    "testosterone_value",
    "testosterone_current",
    "psa_value",
    "psa_current",
    "baseline_psa",
    "psa_baseline_ng_ml",
    "polysorbate_hypersensitivity",
    "polysorbate_hypersensitivity_history",
    "cognitive_disturbance_ctcae_grade",
    "mmse_baseline",
    "mmse_current",
    "moca_baseline",
    "moca_current",
    "ecog_score",
    "ecog_current",
}


@dataclass(frozen=True)
class GateContractRow:
    gate_code: str
    trigger_fields: list[str]
    coverage_status: str
    capture_phase: str
    classifier_fields: list[str]
    initial_wizard_fields: list[str]
    longitudinal_followup_fields: list[str]
    support_field_specs: list[str]
    persisted_fields: list[str]
    service_consumers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_gate_contract_matrix(*, force_reload: bool = False) -> list[GateContractRow]:
    """Build one contract row per YAML pivotal gate."""
    if force_reload:
        return list(_build_gate_contract_matrix_uncached(force_reload=True))
    return list(_build_gate_contract_matrix_cached())


@lru_cache(maxsize=1)
def _build_gate_contract_matrix_cached() -> tuple[GateContractRow, ...]:
    return tuple(_build_gate_contract_matrix_uncached(force_reload=False))


def _build_gate_contract_matrix_uncached(*, force_reload: bool) -> list[GateContractRow]:
    from prostanet.shared.pivotal_gates_yaml_loader import _load_yaml_files

    registry = _capture_registry()
    rows: list[GateContractRow] = []
    for gate_code, config in sorted(_load_yaml_files(force_reload=force_reload).items()):
        trigger_fields = sorted(_extract_gate_fields(config))
        classifier = _covered_members(trigger_fields, registry["classifier"])
        initial = _covered_members(trigger_fields, registry["initial_wizard"])
        longitudinal = _covered_members(trigger_fields, registry["longitudinal_followup"])
        support = _covered_members(trigger_fields, registry["field_specs"])
        persisted = _covered_members(trigger_fields, registry["persistence"])

        if classifier:
            phase = "covered_at_classifier"
        elif initial or support:
            phase = "covered_at_initial_wizard"
        elif longitudinal or persisted:
            phase = "covered_at_longitudinal_followup"
        else:
            phase = "uncovered"

        rows.append(
            GateContractRow(
                gate_code=gate_code,
                trigger_fields=trigger_fields,
                coverage_status="covered" if phase != "uncovered" else "uncovered",
                capture_phase=phase,
                classifier_fields=classifier,
                initial_wizard_fields=initial,
                longitudinal_followup_fields=longitudinal,
                support_field_specs=support,
                persisted_fields=persisted,
                service_consumers=["pivotal_gates_yaml_loader"],
            )
        )
    return rows


def summarize_gate_contract_matrix() -> dict[str, Any]:
    rows = build_gate_contract_matrix()
    phase_counts: dict[str, int] = {}
    for row in rows:
        phase_counts[row.capture_phase] = phase_counts.get(row.capture_phase, 0) + 1
    uncovered = [row.to_dict() for row in rows if row.coverage_status != "covered"]
    return {
        "total_gates": len(rows),
        "covered_gates": len(rows) - len(uncovered),
        "uncovered_gates": uncovered,
        "phase_counts": phase_counts,
        "matrix": [row.to_dict() for row in rows],
    }


@lru_cache(maxsize=1)
def _capture_registry() -> dict[str, set[str]]:
    return {
        "classifier": _classifier_fields(),
        "initial_wizard": _router_fields("initial_wizard"),
        "longitudinal_followup": _router_fields("longitudinal_followup"),
        "field_specs": _support_field_specs(),
        "persistence": _expand_aliases(PERSISTED_BASELINE_OR_FOLLOWUP_FIELDS),
    }


@lru_cache(maxsize=1)
def _classifier_fields() -> set[str]:
    try:
        from prostanet.presentation.v2_adapters import quick_classify_schema

        return _expand_aliases(
            field.get("name")
            for field in quick_classify_schema().get("fields", [])
            if isinstance(field, Mapping)
        )
    except Exception:
        return set()


@lru_cache(maxsize=8)
def _router_fields(phase: str) -> set[str]:
    try:
        from prostanet.presentation.clinical_field_router import build_clinical_field_router
    except Exception:
        return set()

    names: set[str] = set()
    for state in CONTRACT_STATES:
        try:
            routed = build_clinical_field_router(state, phase=phase)
        except Exception:
            continue
        for group in routed.get("group_order", []):
            if not isinstance(group, Mapping):
                continue
            for field in group.get("fields", []):
                if isinstance(field, Mapping) and field.get("name"):
                    names.add(str(field["name"]))
    return _expand_aliases(names)


@lru_cache(maxsize=1)
def _support_field_specs() -> set[str]:
    names: set[str] = set()
    try:
        from prostanet.shared.advanced_support_fields import (
            advanced_cognitive_fields,
            advanced_laboratory_baseline_fields,
            advanced_renal_function_fields,
            pivotal_contraindication_fields,
            pivotal_gate_supporting_fields,
        )

        builders = (
            lambda: pivotal_contraindication_fields(),
            lambda: pivotal_gate_supporting_fields(),
            lambda: advanced_renal_function_fields(),
            lambda: advanced_laboratory_baseline_fields(),
            lambda: advanced_cognitive_fields(group="Cognición", group_order=80),
        )
        for builder in builders:
            try:
                for field in builder():
                    name = getattr(field, "name", "")
                    if name:
                        names.add(str(name))
            except Exception:
                continue
    except Exception:
        pass
    return _expand_aliases(names)


def _extract_gate_fields(config: Mapping[str, Any]) -> set[str]:
    fields: set[str] = set()
    _collect_trigger_fields(config.get("trigger"), fields)
    _collect_trigger_fields(config.get("override"), fields)
    return {field for field in fields if field}


def _collect_trigger_fields(node: Any, fields: set[str]) -> None:
    if not node:
        return
    if isinstance(node, Mapping):
        for key in ("field", "baseline_field", "current_field"):
            value = node.get(key)
            if value:
                fields.add(str(value))
        for alias in node.get("alias_fields") or []:
            if alias:
                fields.add(str(alias))
        for item in node.get("fields") or []:
            if isinstance(item, Mapping) and item.get("field"):
                fields.add(str(item["field"]))
        for child in node.get("triggers") or []:
            _collect_trigger_fields(child, fields)
    elif isinstance(node, Iterable) and not isinstance(node, (str, bytes)):
        for child in node:
            _collect_trigger_fields(child, fields)


def _covered_members(trigger_fields: Iterable[str], registry_fields: set[str]) -> list[str]:
    covered: set[str] = set()
    for field in trigger_fields:
        family = _field_family(field)
        if family & registry_fields:
            covered.add(field)
    return sorted(covered)


def _expand_aliases(fields: Iterable[str | None]) -> set[str]:
    expanded: set[str] = set()
    for raw in fields:
        if not raw:
            continue
        field = str(raw)
        expanded.add(field)
        expanded.update(_field_family(field))
    return expanded


def _field_family(field: str) -> set[str]:
    for members in FIELD_ALIAS_FAMILIES.values():
        if field in members:
            return set(members)
    return {field}
