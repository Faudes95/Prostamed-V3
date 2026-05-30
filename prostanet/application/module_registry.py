from __future__ import annotations

from copy import deepcopy

from prostanet.domains.adt_progression_verification.service import AdtProgressionVerificationService
from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.diagnostic_workup.service import DiagnosticWorkupService
from prostanet.domains.focal_therapy.service import FocalTherapyService
from prostanet.domains.localized_initial.service import LocalizedInitialService
from prostanet.domains.m0_crpc.service import M0CrpcService
from prostanet.domains.m1_crpc.service import M1CrpcService
from prostanet.domains.screening.service import ScreeningService
from prostanet.domains.mcspc_high_volume.service import (
    McspcHighVolumeMetachronousService,
    McspcHighVolumeService,
    McspcHighVolumeSyncService,
)
from prostanet.domains.mcspc_low_volume_sync_oligo.service import McspcLowVolumeSyncOligoService
from prostanet.domains.mcspc_oligo_metachronous.service import McspcOligoMetachronousService
from prostanet.domains.post_negative_biopsy_followup.service import PostNegativeBiopsyFollowupService
from prostanet.domains.post_prostatectomy.service import PostProstatectomyService
from prostanet.domains.post_radiotherapy_followup.service import PostRadiotherapyFollowupService
from prostanet.domains.post_radiotherapy_or_local_salvage.service import PostRadiotherapyOrLocalSalvageService
from prostanet.domains.recurrence_bcr.service import RecurrenceBCRService
from prostanet.domains.state_classifier.service import StateClassifierService
from prostanet.domains.state_classifier.schemas import STATE_CLASSIFIER_SCHEMA
from prostanet.domains.survivorship_and_toxicity_followup.service import (
    SurvivorshipAndToxicityFollowupService,
)
from prostanet.shared.decision_quality import build_decision_quality
from prostanet.shared.advanced_support_normalizer import normalize_advanced_support_payload
from prostanet.shared.epic26 import normalize_epic26_payload
from prostanet.shared.gleason_profile import apply_gleason_profile
from prostanet.shared.module_support import apply_support_bundle, support_bundle_for_module
from prostanet.shared.validated_algorithms import build_validated_algorithms


MODULE_ID_ALIASES = {
    "screening": "diagnostic_workup",
}


class ModuleRegistry:
    def __init__(self) -> None:
        self.evidence_registry = EvidenceRegistryService()
        self.state_classifier = StateClassifierService()
        self.services = {
            "screening": ScreeningService(),
            "diagnostic_workup": DiagnosticWorkupService(),
            "post_negative_biopsy_followup": PostNegativeBiopsyFollowupService(),
            "localized_initial": LocalizedInitialService(),
            "focal_therapy": FocalTherapyService(),
            "post_prostatectomy": PostProstatectomyService(),
            "post_radiotherapy_followup": PostRadiotherapyFollowupService(),
            "recurrence_bcr": RecurrenceBCRService(),
            "post_radiotherapy_or_local_salvage": PostRadiotherapyOrLocalSalvageService(),
            "adt_progression_verification": AdtProgressionVerificationService(),
            "mcspc_oligo_metachronous": McspcOligoMetachronousService(),
            "mcspc_low_volume_sync_oligo": McspcLowVolumeSyncOligoService(),
            "mcspc_high_volume_sync": McspcHighVolumeSyncService(),
            "mcspc_high_volume_metachronous": McspcHighVolumeMetachronousService(),
            "mcspc_high_volume": McspcHighVolumeService(),
            "m0_crpc": M0CrpcService(),
            "m1_crpc": M1CrpcService(),
            "survivorship_and_toxicity_followup": SurvivorshipAndToxicityFollowupService(),
        }

    def canonical_module_id(self, module_id: str) -> str:
        raw = str(module_id or "").strip()
        return MODULE_ID_ALIASES.get(raw, raw)

    def list_modules(self) -> list[dict]:
        return [module for module in self.evidence_registry.list_modules() if module.get("module") != "mcspc_high_volume"]

    def get_module_schema(self, module_id: str) -> dict:
        module_id = self.canonical_module_id(module_id)
        return deepcopy(self.services[module_id].schema())

    def get_state_classifier_schema(self) -> dict:
        return deepcopy(STATE_CLASSIFIER_SCHEMA)

    def evaluate_module(self, module_id: str, payload: dict) -> dict:
        module_id = self.canonical_module_id(module_id)
        normalized_payload = normalize_advanced_support_payload(
            apply_gleason_profile(normalize_epic26_payload(payload)),
            state=module_id,
        )
        result = self.services[module_id].evaluate(normalized_payload)
        evidence = self.get_module_evidence(module_id)
        bundle = support_bundle_for_module(module_id, normalized_payload, result, evidence)
        enriched = apply_support_bundle(
            result,
            monitoring=bundle["monitoring"],
            transitions=bundle["transitions"],
            survivorship_risks=bundle["survivorship_risks"],
            palliative_flags=bundle["palliative_flags"],
            care_overlays=bundle["care_overlays"],
            source_citations=bundle["source_citations"],
            evidence_gaps=bundle["evidence_gaps"],
            objective_progression=bundle["objective_progression"],
            decision_changing_inputs=bundle["decision_changing_inputs"],
            supportive_evidence_context=bundle["supportive_evidence_context"],
            benchmarking_flags=bundle["benchmarking_flags"],
        )
        enriched["validated_algorithms"] = build_validated_algorithms(module_id, normalized_payload, enriched)
        enriched["decision_quality"] = build_decision_quality(module_id, normalized_payload, enriched)
        enriched["state_classification"] = enriched["decision_quality"].get("state_classification", enriched.get("state"))
        enriched["recommendation_family"] = enriched["decision_quality"].get("recommendation_family", "")
        enriched["why_not_more_confident"] = enriched["decision_quality"].get("why_not_more_confident", [])
        return enriched

    def classify_state(self, payload: dict) -> dict:
        return self.state_classifier.classify(
            normalize_advanced_support_payload(
                apply_gleason_profile(normalize_epic26_payload(payload)),
                state=str(payload.get("state") or ""),
            )
        )

    def get_module_evidence(self, module_id: str) -> dict:
        module_id = self.canonical_module_id(module_id)
        return self.evidence_registry.get_module_evidence(module_id)

    def get_module_sources(self, module_id: str) -> list[dict]:
        module_id = self.canonical_module_id(module_id)
        return self.evidence_registry.get_module_sources(module_id)

    def get_guidelines_metadata(self) -> dict[str, dict]:
        return self.evidence_registry.get_guidelines_metadata()
