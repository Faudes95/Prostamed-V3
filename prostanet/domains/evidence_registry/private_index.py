from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from prostanet.domains.evidence_registry.models import EvidenceChunk, EvidenceDocument


DEFAULT_EVIDENCE_INDEX_ROOT = Path(
    os.environ.get(
        "PROSTANET_EVIDENCE_INDEX",
        Path.cwd() / ".prostanet_private" / "evidence_index",
    )
)


class EvidencePrivateIndex:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_EVIDENCE_INDEX_ROOT)

    def ensure_document(self, document: dict[str, Any]) -> dict[str, Any]:
        document_id = str(document.get("document_id", "")).strip()
        pdf_path_text = str(document.get("local_pdf_path", "")).strip()
        pdf_path = Path(pdf_path_text) if pdf_path_text else Path()
        if not document_id or not pdf_path_text or not pdf_path.exists() or not pdf_path.is_file():
            return {
                "document_id": document_id,
                "indexed": False,
                "reason": "missing_source",
                "source_path": pdf_path_text,
            }

        index_path = self.root / f"{document_id}.json"
        sha256 = self._sha256(pdf_path)
        if index_path.exists():
            payload = self._read_index(index_path)
            if payload.get("sha256") == sha256:
                return self._status_payload(index_path, payload)

        payload = self._build_payload(document, pdf_path, sha256)
        self.root.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._status_payload(index_path, payload)

    def get_status(self, document: dict[str, Any]) -> dict[str, Any]:
        document_id = str(document.get("document_id", "")).strip()
        index_path = self.root / f"{document_id}.json"
        if not index_path.exists():
            return {
                "document_id": document_id,
                "indexed": False,
                "reason": "not_indexed",
                "source_path": str(document.get("local_pdf_path", "")),
            }
        return self._status_payload(index_path, self._read_index(index_path))

    def ensure_documents(self, documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            str(document.get("document_id", "")): self.ensure_document(document)
            for document in documents
            if document.get("document_id")
        }

    def _build_payload(self, document: dict[str, Any], pdf_path: Path, sha256: str) -> dict[str, Any]:
        reader = PdfReader(str(pdf_path))
        chunks: list[EvidenceChunk] = []
        ordinal = 0
        for page_index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            for piece in self._chunk_text(text):
                ordinal += 1
                chunks.append(
                    EvidenceChunk(
                        chunk_id=f"{document['document_id']}::chunk::{ordinal}",
                        document_id=document["document_id"],
                        ordinal=ordinal,
                        page_start=page_index,
                        page_end=page_index,
                        text=piece,
                        tags=[
                            document.get("evidence_role", ""),
                            *document.get("applies_to_modules", []),
                            *document.get("field_implications", []),
                            *document.get("derived_rule_ids", []),
                        ],
                    )
                )

        indexed_at = datetime.now(timezone.utc).isoformat()
        evidence_document = EvidenceDocument(
            document_id=document["document_id"],
            title=document.get("title", document.get("guideline_or_trial", document["document_id"])),
            source_path=str(pdf_path),
            sha256=sha256,
            indexed_at=indexed_at,
            page_count=len(reader.pages),
            license_class=document.get("license_class", ""),
            chunks=chunks,
        )
        return evidence_document.to_dict()

    @staticmethod
    def _chunk_text(text: str, target_size: int = 1800) -> list[str]:
        normalized = " ".join(text.split())
        if len(normalized) <= target_size:
            return [normalized]

        paragraphs = [item.strip() for item in normalized.split(". ") if item.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}. {paragraph}".strip(". ").strip() if current else paragraph
            if len(candidate) > target_size and current:
                chunks.append(current.strip())
                current = paragraph
            else:
                current = candidate
        if current:
            chunks.append(current.strip())
        return chunks

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            for block in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _read_index(index_path: Path) -> dict[str, Any]:
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {
                "document_id": index_path.stem,
                "source_path": "",
                "chunks": [],
                "corrupt_index": True,
            }

    @staticmethod
    def _status_payload(index_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("corrupt_index"):
            return {
                "document_id": payload.get("document_id", index_path.stem),
                "indexed": False,
                "reason": "corrupt_index",
                "source_path": payload.get("source_path", ""),
                "index_path": str(index_path),
                "sha256": "",
                "indexed_at": "",
                "page_count": 0,
                "chunk_count": 0,
                "license_class": "",
            }
        return {
            "document_id": payload.get("document_id", ""),
            "indexed": True,
            "title": payload.get("title", ""),
            "source_path": payload.get("source_path", ""),
            "index_path": str(index_path),
            "sha256": payload.get("sha256", ""),
            "indexed_at": payload.get("indexed_at", ""),
            "page_count": payload.get("page_count", 0),
            "chunk_count": len(payload.get("chunks", [])),
            "license_class": payload.get("license_class", ""),
        }
