from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    field_type: str
    required: bool = False
    help_text: str = ""
    options: list[Any] = field(default_factory=list)
    default: Any = None
    group: str = ""
    group_order: int = 0
    clinical_role: str = ""
    unit: str = ""
    conditional_visibility: dict[str, Any] = field(default_factory=dict)
    derived_from: list[str] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)
    benchmark_note: str = ""
    display_options: list[dict[str, Any]] = field(default_factory=list)
    widget_config: dict[str, Any] = field(default_factory=dict)
    scale_descriptor: str = ""
    score_interpretation: str = ""
    reuse_key: str = ""
    capture_layer: str = ""
    when_to_ask: str = ""
    reference_range_low: Any = None
    reference_range_high: Any = None
    reference_range_unit: str = ""
    reference_range_label: str = ""
    reference_range_source: str = ""
    min_value: Any = None
    max_value: Any = None
    allow_negative: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["display_options"] = _build_display_options(
            self.name,
            data.get("options") or [],
            data.get("display_options") or [],
        )
        return data


def _build_display_options(
    field_name: str,
    options: list[Any],
    explicit_display_options: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if explicit_display_options:
        normalized: list[dict[str, Any]] = []
        for option in explicit_display_options:
            if isinstance(option, dict):
                value = option.get("value")
                label = option.get("label", value)
                normalized.append({**option, "value": value, "label": label})
        if normalized:
            return normalized

    try:
        from prostanet.shared.presentation_text import resolve_option_label
    except Exception:
        resolve_option_label = None

    display_options: list[dict[str, Any]] = []
    for option in options or []:
        if isinstance(option, dict):
            value = option.get("value")
            label = option.get("label")
            normalized_option = dict(option)
        elif isinstance(option, (list, tuple)) and len(option) >= 2:
            value = option[0]
            label = option[1]
            normalized_option = {"value": value}
        else:
            value = option
            label = None
            normalized_option = {"value": value}

        if label is None and resolve_option_label is not None:
            label = resolve_option_label(field_name, value, options)
        if label is None:
            label = value
        normalized_option["label"] = label
        display_options.append(normalized_option)
    return display_options


@dataclass(frozen=True)
class RegistrationFragment:
    id: str
    title: str
    applies_to_states: list[str] = field(default_factory=list)
    fields: list[FieldSpec] = field(default_factory=list)
    persist_targets: list[str] = field(default_factory=list)
    clinical_influence: list[str] = field(default_factory=list)
    optional_research: bool = False
    benchmark_only: bool = False
    imported_fields: list[dict[str, Any]] = field(default_factory=list)
    capture_layer: str = ""
    when_to_ask: str = ""
    collapsed_by_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fields"] = [field.to_dict() for field in self.fields]
        return data


@dataclass(frozen=True)
class MedicationEntry:
    """Medicamento concomitante estructurado (EPIC 2 FAUBOT).

    Reemplaza al string libre en `current_medications` para que el motor DDI,
    el score Halabi (opioide basal) y el gate de toxicidad puedan razonar sobre
    el listado. Los campos mínimos son ``name`` + ``status``; ``dose``,
    ``frequency``, ``route``, ``start_date``, ``indication`` y ``prescriber``
    son opcionales pero habilitan auditoría clínica completa.
    """

    name: str
    dose: str = ""
    frequency: str = ""
    route: str = ""
    start_date: str = ""
    end_date: str = ""
    indication: str = ""
    prescriber: str = ""
    status: str = "active"
    atc_code: str = ""
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosticPlanEvent:
    plan_type: str
    status: str = "planificado"
    summary: str = ""
    next_action: str = ""
    management_intent_status: str = "candidate"
    trigger_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MriFact:
    fact_date: str = ""
    quality: str = ""
    decision_usable: bool = False
    pirads_score: int | None = None
    lesion_location: str = ""
    lesion_size_mm: float | None = None
    prostate_volume_ml: float | None = None
    findings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BiopsyTriggerEvent:
    trigger_reason: str
    priority: str = "pendiente"
    planned_type: str = ""
    planned_route: str = ""
    status: str = "pendiente_de_confirmacion"
    management_intent_status: str = "candidate"
    activation_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceCitation:
    citation_id: str
    title: str
    guideline_or_trial: str
    source_tier: str
    effective_date: str = ""
    review_due_date: str = ""
    document_id: str = ""
    evidence_role: str = ""
    license_class: str = ""
    doi_or_url: str = ""
    local_pdf_path: str = ""
    disease_state: str = ""
    line_of_therapy: str = ""
    biomarker_scope: str = ""
    symptom_scope: str = ""
    toxicity_scope: str = ""
    followup_implications: str = ""
    supports_rule_ids: list[str] = field(default_factory=list)
    applies_to_modules: list[str] = field(default_factory=list)
    derived_rule_ids: list[str] = field(default_factory=list)
    field_implications: list[str] = field(default_factory=list)
    eligibility_implications: list[str] = field(default_factory=list)
    required_traceable_fields: list[str] = field(default_factory=list)
    applies_to_surfaces: list[str] = field(default_factory=list)
    ui_surfaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringPlan:
    title: str
    cadence: str
    actions: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateTransition:
    target_state: str
    label: str
    when: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CareOverlay:
    overlay_type: str
    title: str
    status: str
    reasons: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToxicityProfile:
    domain: str
    risks: list[str] = field(default_factory=list)
    monitoring: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromBattery:
    title: str
    instruments: list[str] = field(default_factory=list)
    cadence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgendaItem:
    agenda_key: str
    item_type: str
    title: str
    state: str
    management_track: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    window_start: str = ""
    window_end: str = ""
    delay_days: int = 0
    plan_key: str = ""
    completed_at: str = ""
    status: str = "scheduled"
    priority: str = "routine"
    summary: str = ""
    required_inputs: list[str] = field(default_factory=list)
    capture_fields: list[str] = field(default_factory=list)
    derived_requirements: list[str] = field(default_factory=list)
    required: bool = True
    action_mode: str = "capture"
    completion_rule: dict[str, Any] = field(default_factory=dict)
    evidence_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    generated_from_event: str = ""
    action_label: str = ""
    blockers: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    decision_targets: list[str] = field(default_factory=list)
    panel_targets: list[str] = field(default_factory=list)
    write_targets: list[str] = field(default_factory=list)
    form_scope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageProtocolDefinition:
    state: str
    management_track: str
    title: str
    cadence_summary: str
    purpose: str
    evidence_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    agenda_defaults: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisitBundle:
    state: str
    management_track: str
    visit_type: str = "stage_followup"
    visit_date: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TherapyCheckpoint:
    key: str
    title: str
    status: str
    rationale: str
    action: str = ""
    evidence_basis: list[str] = field(default_factory=list)
    decision_supported: str = ""
    why_it_matters_now: str = ""
    inputs_required: list[str] = field(default_factory=list)
    blocking_if_missing: bool = False
    last_input_source: str = ""
    last_input_date: str = ""
    changes_recommendation_if_resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CopilotAlert:
    alert_key: str
    category: str
    decision_domain: str
    severity: str
    title: str
    message: str
    why_now: str = ""
    recommended_action: str = ""
    fields_to_capture: list[str] = field(default_factory=list)
    detail_items: list[dict[str, Any]] = field(default_factory=list)
    linked_agenda_ids: list[int] = field(default_factory=list)
    linked_agenda_keys: list[str] = field(default_factory=list)
    linked_encounter_keys: list[str] = field(default_factory=list)
    can_be_resolved_in_visit: bool = False
    creates_or_links_agenda_item: bool = False
    action_type: str = "capture"
    capture_block: str = ""
    encounter_key: str = ""
    resolves_decision_domain: str = ""
    expected_document_type: str = ""
    resolution_mode: str = ""
    focus_fields: list[str] = field(default_factory=list)
    primary_button_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterTask:
    agenda_id: int | None
    agenda_key: str
    title: str
    item_type: str
    status: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    completed_at: str = ""
    delay_days: int = 0
    action_label: str = ""
    required: bool = True
    action_mode: str = "capture"
    expected_document_type: str = ""
    decision_targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterPlan:
    encounter_key: str
    encounter_type: str
    state: str
    management_track: str
    title: str
    summary: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    completed_at: str = ""
    delay_days: int = 0
    plan_key: str = ""
    status: str = "scheduled"
    priority: str = "routine"
    visit_modality: str = "clinic"
    task_count: int = 0
    required_task_count: int = 0
    completed_required_task_count: int = 0
    completion_progress: dict[str, Any] = field(default_factory=dict)
    tasks: list[EncounterTask] = field(default_factory=list)
    decision_domains: list[str] = field(default_factory=list)
    decision_domains_covered: list[str] = field(default_factory=list)
    guideline_basis: list[str] = field(default_factory=list)
    alerts_resolved_by_this_encounter: list[str] = field(default_factory=list)
    alert_count: int = 0
    anchor_strength: str = "strong"
    inline_actions_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tasks"] = [task.to_dict() for task in self.tasks]
        return data


@dataclass(frozen=True)
class ScheduleAnchorAssessment:
    anchor_date: str = ""
    anchor_source: str = ""
    strength: str = "strong"
    is_fallback: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlertActionPayload:
    action_type: str = "capture"
    capture_block: str = ""
    fields_to_capture: list[str] = field(default_factory=list)
    encounter_key: str = ""
    linked_agenda_keys: list[str] = field(default_factory=list)
    expected_document_type: str = ""
    resolves_decision_domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioCadenceRule:
    scenario_state: str
    management_track: str
    phase_label: str
    guideline_basis: list[str] = field(default_factory=list)
    anchor_priority: list[str] = field(default_factory=list)
    cadence_rules: list[str] = field(default_factory=list)
    encounter_templates: list[str] = field(default_factory=list)
    required_tasks: list[str] = field(default_factory=list)
    escalation_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MasterFollowupPlan:
    plan_version: str
    plan_key: str
    scenario_state: str
    management_track: str
    title: str
    phase_label: str = ""
    plan_status: str = "active"
    calendar_horizon_months: int = 12
    guideline_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    anchor: dict[str, Any] = field(default_factory=dict)
    scenario_rule: dict[str, Any] = field(default_factory=dict)
    next_encounter: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    encounter_timeline: list[dict[str, Any]] = field(default_factory=list)
    inline_actions_enabled: bool = False
    blocking_alerts: list[dict[str, Any]] = field(default_factory=list)
    overdue_items: list[dict[str, Any]] = field(default_factory=list)
    due_items: list[dict[str, Any]] = field(default_factory=list)
    optional_items: list[dict[str, Any]] = field(default_factory=list)
    highlight_actions: list[str] = field(default_factory=list)
    gaps_to_close: list[str] = field(default_factory=list)
    capture_actions: list[dict[str, Any]] = field(default_factory=list)
    prognostic_rationale: list[dict[str, Any]] = field(default_factory=list)
    cadence_adjusted_by: list[str] = field(default_factory=list)
    backbone_alignment: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClinicalFact:
    fact_key: str
    category: str
    value: Any = None
    fact_date: str = ""
    source_type: str = ""
    source_priority: str = ""
    verified: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeEvent:
    event_key: str
    event_type: str
    scenario_state: str
    management_track: str
    axis: str = ""
    adjudication_status: str = "confirmed"
    event_date: str = ""
    source_priority: str = ""
    decision_impact: str = ""
    summary: str = ""
    provisional: bool = False
    blocking_fields: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdjudicationStatus:
    status_key: str
    title: str
    rationale: str
    status: str = "pending"
    severity: str = "warning"
    provisional: bool = True
    decision_domain: str = ""
    capture_block: str = ""
    action_type: str = "capture"
    expected_document_type: str = ""
    linked_outcome_event: str = ""
    linked_encounter_key: str = ""
    linked_agenda_keys: list[str] = field(default_factory=list)
    fields_to_capture: list[str] = field(default_factory=list)
    recommended_action: str = ""
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PrognosticModifier:
    modifier_key: str
    title: str
    severity: str
    why_it_matters_now: str = ""
    decision_domains_affected: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    followup_impact: list[str] = field(default_factory=list)
    source_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackboneAlignment:
    trial_backbone: list[str] = field(default_factory=list)
    trial_backbone_label: str = ""
    current_regimen: str = ""
    current_regimen_label: str = ""
    alignment_status: str = "unknown"
    clinical_note: str = ""
    matched_trials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrialComparableEndpoint:
    endpoint_key: str
    label: str
    status: str
    value: Any = None
    scenario_state: str = ""
    trial_family: str = ""
    comparable: bool = False
    provisional: bool = False
    details: str = ""
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkSnapshot:
    benchmark_family: str
    scenario_state: str
    management_track: str
    eligibility_status: str
    matched_trials: list[str] = field(default_factory=list)
    endpoint_snapshot: dict[str, Any] = field(default_factory=dict)
    cohort_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    recommended_trial_backbone: list[str] = field(default_factory=list)
    recommended_trial_backbone_label: str = ""
    recommended_trial_backbone_source: str = ""
    recommended_trial_backbone_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstitutionalComparator:
    label: str
    mode: str
    title: str
    cadence_summary: str
    source_label: str = ""
    source_url: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataFreshnessFact:
    label: str
    value: str
    date: str
    freshness_status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProvenanceFact:
    field_name: str
    source_type: str
    source_date: str = ""
    source_document_id: str = ""
    verified_by: str = ""
    entered_manually: bool = False
    stage_context: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PatientEvent:
    patient_id: int
    event_type: str
    event_date: str
    state_context: str = ""
    management_track: str = ""
    source_type: str = ""
    source_record_id: int | None = None
    status: str = "recorded"
    payload: dict[str, Any] = field(default_factory=dict)
    mcode_focus: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClinicalSignalSet:
    state: str
    management_track: str
    ready_to_restage: bool = False
    signals: list[dict[str, Any]] = field(default_factory=list)
    critical_missing: list[str] = field(default_factory=list)
    awaiting_review: list[str] = field(default_factory=list)
    active_safety: list[str] = field(default_factory=list)
    mcode_projection: dict[str, Any] = field(default_factory=dict)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateTransitionProposal:
    proposal_key: str
    from_state: str
    target_state: str
    rationale: str
    from_state_label: str = ""
    target_state_label: str = ""
    from_management_track: str = ""
    target_management_track: str = ""
    priority: str = "routine"
    proposal_status: str = "open"
    requires_confirmation: bool = True
    confirmation_status: str = "pending"
    rejection_reason: str = ""
    requires_more_data_fields: list[str] = field(default_factory=list)
    confirmed_at: str = ""
    confirmed_by: str = ""
    trigger_signals: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NextBestAction:
    title: str
    recommendation_family: str
    rationale: str
    action_title: str = ""
    action_rationale: str = ""
    transition_title: str = ""
    transition_rationale: str = ""
    transition_pending: bool = False
    transition_target_state: str = ""
    immediate_actions: list[str] = field(default_factory=list)
    data_that_could_change_course: list[str] = field(default_factory=list)
    contraindication_modifiers: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationAudit:
    patient_id: int
    recommendation_family: str
    recommended_option: str
    selected_option: str = ""
    discordance_reason: str = ""
    recommended_confidence: str = ""
    clinician_selected_option: str = ""
    clinician_selected_family: str = ""
    followed_system_recommendation: str = "unknown"
    discordance_reason_category: str = ""
    decision_capture_status: str = "inferred_only"
    assessment_id: int | None = None
    event_id: int | None = None
    outcome_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDocument:
    patient_id: int
    document_key: str
    document_type: str
    title: str = ""
    file_name: str = ""
    mime_type: str = ""
    sha256: str = ""
    storage_path: str = ""
    private_index_path: str = ""
    source_date: str = ""
    classification_status: str = "pending"
    extraction_status: str = "pending"
    verification_status: str = "draft"
    preview_excerpt: str = ""
    page_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentExtractionCandidate:
    candidate_key: str
    field_name: str
    fact_group: str
    value: Any
    value_display: str = ""
    target_result_type: str = ""
    confidence: float = 0.0
    status: str = "draft"
    extraction_method: str = ""
    evidence_excerpt: str = ""
    page_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationTask:
    task_key: str
    task_status: str = "open"
    assigned_to: str = ""
    verified_by: str = ""
    verified_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    pending_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerifiedFact:
    field_name: str
    fact_group: str
    value: Any
    value_display: str = ""
    target_result_type: str = ""
    source_date: str = ""
    status: str = "verified"
    correction_note: str = ""
    verified_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerifiedFactBundle:
    verified_by: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    committed_result_types: list[str] = field(default_factory=list)
    what_changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VitalStatusRecord:
    vital_status: str = "alive"
    date_of_death: str | None = None
    cause_of_death: str | None = None
    last_contact_date: str = ""
    last_contact_status: str = ""
    death_source: str = ""
    source_type: str = ""
    source_record_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SurvivalAnchorEvent:
    anchor_type: str
    anchor_date: str = ""
    anchor_source: str = ""
    source_type: str = ""
    source_record_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BiopsyCoreRecord:
    core_id: str
    location_sextant: str
    core_type: str
    core_length_mm: float | None = None
    tumor_length_mm: float | None = None
    involvement_pct: float | None = None
    gleason_primary: int | None = None
    gleason_secondary: int | None = None
    isup_grade: int | None = None
    positive: bool = False
    mri_target_concordance: bool | None = None
    cribriform_pattern: bool = False
    intraductal_carcinoma: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BiopsyTarget:
    target_id: str
    target_label: str = ""
    pirads_score: int | None = None
    lesion_location: str = ""
    positive_core_count: int = 0
    total_core_count: int = 0
    concordance_status: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BiopsySession:
    session_key: str
    biopsy_date: str = ""
    biopsy_type: str = ""
    biopsy_route: str = ""
    biopsy_context: str = ""
    mri_pirads_at_biopsy: int | None = None
    systematic_cores: list[BiopsyCoreRecord] = field(default_factory=list)
    targeted_cores: list[BiopsyCoreRecord] = field(default_factory=list)
    targets: list[BiopsyTarget] = field(default_factory=list)
    complications: list[str] = field(default_factory=list)
    source_type: str = ""
    source_record_id: int | None = None
    legacy_biopsy_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["systematic_cores"] = [item.to_dict() for item in self.systematic_cores]
        data["targeted_cores"] = [item.to_dict() for item in self.targeted_cores]
        data["targets"] = [item.to_dict() for item in self.targets]
        return data


@dataclass(frozen=True)
class ASScheduleRecord:
    item_type: str
    title: str
    due_date: str
    interval_months: int = 0
    status: str = "scheduled"
    completed_date: str = ""
    priority: str = "routine"
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ASTriggerEvent:
    trigger_type: str
    detected_date: str = ""
    detail: str = ""
    severity: str = ""
    recommended_action: str = ""
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkeletalRelatedEventRecord:
    event_type: str
    event_date: str = ""
    site: str = ""
    intervention: str = ""
    surgical_intervention: bool = False
    rt_dose_gy: float | None = None
    rt_fractions: int | None = None
    details: str = ""
    severity: str = "standard"
    resolved: bool = False
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BoneModifyingAgentCourse:
    agent: str = ""
    start_date: str = ""
    end_date: str | None = None
    frequency: str = ""
    dental_clearance_done: bool = False
    dental_clearance_date: str | None = None
    last_dental_evaluation: str | None = None
    onj_monitoring: bool = False
    onj_detected: bool = False
    calcium_vitamin_d_supplementation: bool = False
    renal_function_adequate: bool | None = None
    last_renal_check_date: str | None = None
    doses_administered: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RadiotherapyToxicityRecord:
    domain: str
    phase: str
    grade: int
    details: str = ""
    onset_date: str = ""
    evidence_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RadiotherapyCourseRecord:
    course_key: str
    rt_intent: str = ""
    modality: str = ""
    target_volume: str = ""
    total_dose_gy: float = 0.0
    fractions: int = 0
    dose_per_fraction_gy: float = 0.0
    boost_dose_gy: float | None = None
    boost_technique: str | None = None
    rt_start_date: str = ""
    rt_end_date: str = ""
    concurrent_adt: bool = False
    adt_neoadjuvant_months: float | None = None
    adt_concurrent: bool = False
    adt_adjuvant_months: float | None = None
    adt_total_planned_months: float | None = None
    salvage_psa_at_start: float | None = None
    salvage_pre_imaging: str | None = None
    salvage_nodal_coverage: bool | None = None
    mdt_sites_treated: int | None = None
    mdt_site_details: list[dict[str, Any]] = field(default_factory=list)
    toxicity: list[RadiotherapyToxicityRecord] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["toxicity"] = [item.to_dict() for item in self.toxicity]
        return data


def module_schema(
    module_id: str,
    title: str,
    description: str,
    fields: list[FieldSpec],
) -> dict[str, Any]:
    return {
        "module": module_id,
        "title": title,
        "description": description,
        "fields": [field.to_dict() for field in fields],
    }


def evaluation_result(
    *,
    state: str,
    nccn_primary: dict[str, Any],
    eau_comparison: dict[str, Any],
    eligible_treatments: list[dict[str, Any]] | list[str],
    not_recommended: list[str],
    missing_critical_inputs: list[str],
    contraindications: list[str],
    durations_and_conditions: list[str],
    evidence_trace: list[dict[str, Any]],
    trial_matches: list[dict[str, Any]],
    applicability_badge: str,
    report_sections: dict[str, Any],
    decision_changing_inputs: list[str] | None = None,
    supportive_evidence_context: list[str] | None = None,
    benchmarking_flags: list[dict[str, Any]] | None = None,
    validated_algorithms: list[dict[str, Any]] | None = None,
    decision_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "nccn_primary": nccn_primary,
        "eau_comparison": eau_comparison,
        "eligible_treatments": eligible_treatments,
        "not_recommended": not_recommended,
        "missing_critical_inputs": missing_critical_inputs,
        "contraindications": contraindications,
        "durations_and_conditions": durations_and_conditions,
        "evidence_trace": evidence_trace,
        "trial_matches": trial_matches,
        "applicability_badge": applicability_badge,
        "report_sections": report_sections,
        "decision_changing_inputs": decision_changing_inputs or [],
        "supportive_evidence_context": supportive_evidence_context or [],
        "benchmarking_flags": benchmarking_flags or [],
        "validated_algorithms": validated_algorithms or [],
        "decision_quality": decision_quality or {},
    }
