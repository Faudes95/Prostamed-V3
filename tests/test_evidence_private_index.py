# IEC 62304 §5.5 (Unit verification)
from __future__ import annotations

from prostanet.domains.evidence_registry.private_index import EvidencePrivateIndex


def test_private_index_tolerates_corrupt_json_without_crashing(tmp_path):
    root = tmp_path / "evidence_index"
    root.mkdir(parents=True, exist_ok=True)
    (root / "bad_doc.json").write_text("", encoding="utf-8")

    index = EvidencePrivateIndex(root=root)
    status = index.get_status({"document_id": "bad_doc", "local_pdf_path": ""})

    assert status["indexed"] is False
    assert status["reason"] == "corrupt_index"
    assert status["document_id"] == "bad_doc"
