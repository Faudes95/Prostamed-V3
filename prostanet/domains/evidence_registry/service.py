from __future__ import annotations

from prostanet.domains.evidence_registry.data import DOCUMENTS, GUIDELINES, MODULES
from prostanet.domains.evidence_registry.private_index import EvidencePrivateIndex


class EvidenceRegistryService:
    def __init__(self) -> None:
        self.private_index = EvidencePrivateIndex()

    def list_modules(self) -> list[dict]:
        return [module.to_dict() for module in MODULES.values()]

    def get_module(self, module_id: str) -> dict:
        module = MODULES[module_id]
        return module.to_dict()

    def get_module_evidence(self, module_id: str) -> dict:
        module = MODULES[module_id]
        private_index = self._private_index_for_sources(module.source_citations)
        return {
            "module": module.module,
            "title": module.title,
            "nccn": GUIDELINES["nccn_2026"].to_dict(),
            "eau": GUIDELINES["eau_2026"].to_dict(),
            "nccn_panels": module.nccn_panels,
            "eau_sections": module.eau_sections,
            "pivotal_trials": module.pivotal_trials,
            "core_questions": module.core_questions,
            "source_citations": self._merge_index_status(module.source_citations, private_index),
            "private_index": private_index,
        }

    def get_module_sources(self, module_id: str) -> list[dict]:
        module = MODULES[module_id]
        private_index = self._private_index_for_sources(module.source_citations)
        return self._merge_index_status(module.source_citations, private_index)

    def get_guidelines_metadata(self) -> dict[str, dict]:
        return {key: metadata.to_dict() for key, metadata in GUIDELINES.items()}

    def get_documents_metadata(self) -> dict[str, dict]:
        return DOCUMENTS

    def ensure_private_index(self, document_ids: list[str] | None = None) -> dict[str, dict]:
        if document_ids:
            documents = [
                DOCUMENTS[document_id]
                for document_id in document_ids
                if document_id in DOCUMENTS
            ]
        else:
            documents = list(DOCUMENTS.values())
        return self.private_index.ensure_documents(documents)

    def _private_index_for_sources(self, sources: list[dict]) -> dict[str, dict]:
        document_ids = [source.get("document_id") for source in sources if source.get("document_id")]
        return {
            document_id: self.private_index.get_status(DOCUMENTS[document_id])
            for document_id in document_ids
            if document_id in DOCUMENTS
        }

    @staticmethod
    def _merge_index_status(sources: list[dict], index_status: dict[str, dict]) -> list[dict]:
        merged = []
        for source in sources:
            item = dict(source)
            document_id = item.get("document_id")
            if document_id in index_status:
                item["private_index"] = index_status[document_id]
            merged.append(item)
        return merged
