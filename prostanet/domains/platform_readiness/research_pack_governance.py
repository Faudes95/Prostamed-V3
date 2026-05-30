"""Governed library for frozen de-identified research packs."""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from prostanet.domains.platform_readiness.research_pack_materializer import (
    REGISTRY_TYPE,
    build_research_pack_materializer,
)
from prostanet.shared.utc_time import utc_now_iso


GOVERNANCE_STATUSES = (
    "exploratory",
    "audit_ready",
    "poster_ready",
    "publication_ready",
    "insufficient_quality",
)


def build_research_pack_freeze_library(
    *,
    limit: int = 25,
    include_payload: bool = False,
    include_current_preview: bool = True,
) -> dict[str, Any]:
    """Return a read-only V2 library of governed de-identified research packs."""
    freezes = _load_research_pack_freezes(limit=limit, include_payload=include_payload)
    items = [_summarize_freeze(freeze, include_payload=include_payload) for freeze in freezes]
    current_pack = (
        build_research_pack_materializer(scope="summary", limit=80)
        if include_current_preview
        else {}
    )
    summary = _build_library_summary(items, current_pack)
    return {
        "available": True,
        "source": "deidentified_research_pack_governance_library",
        "version": "deidentified_research_pack_governance_library_v1",
        "computed_at": utc_now_iso(),
        "read_only": True,
        "source_clinical_facts_mutated": False,
        "external_order_created": False,
        "model_trained": False,
        "external_transfer_performed": False,
        "registry_type": REGISTRY_TYPE,
        "governance_statuses": list(GOVERNANCE_STATUSES),
        "summary": summary,
        "current_materializer_summary": (current_pack.get("summary") or {}),
        "freezes": items,
    }


def summarize_research_pack_freeze(
    freeze: Mapping[str, Any],
    *,
    include_payload: bool = False,
) -> dict[str, Any]:
    """Public adapter used by API detail responses."""
    return _summarize_freeze(freeze, include_payload=include_payload)


def _load_research_pack_freezes(*, limit: int, include_payload: bool) -> list[dict[str, Any]]:
    import tracking_db

    safe_limit = max(1, min(int(limit or 25), 100))
    conn = tracking_db._connect()
    cursor = conn.cursor()
    try:
        tracking_db._ensure_research_cohort_freeze_table(cursor)
        cursor.execute(
            """
            SELECT *
            FROM research_cohort_freezes
            WHERE registry_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (REGISTRY_TYPE, safe_limit),
        )
        return [
            tracking_db._research_cohort_freeze_from_row(row, include_payload=include_payload)
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def _summarize_freeze(
    freeze: Mapping[str, Any],
    *,
    include_payload: bool,
) -> dict[str, Any]:
    payload = freeze.get("payload") if isinstance(freeze.get("payload"), Mapping) else {}
    summary = dict(payload.get("summary") or freeze.get("registry_summary") or {})
    methods = _best_mapping(freeze.get("methods"), payload.get("bundle", {}).get("methods"))
    governance = _normalize_governance(methods.get("governance") or {}, summary)
    file_manifest = _file_manifest_from_freeze(freeze, payload)
    direct_phi = int(summary.get("direct_identifier_key_count") or 0)
    exact_phi = int(summary.get("exact_phi_hit_count") or 0)
    interop_blocks = int(summary.get("critical_interop_block_count") or 0)
    unmapped = int(summary.get("unmapped_dictionary_count") or 0)
    quality_block_count = direct_phi + exact_phi + interop_blocks + unmapped
    item = {
        "freeze_key": freeze.get("freeze_key"),
        "title": freeze.get("title"),
        "registry_type": freeze.get("registry_type"),
        "created_at": freeze.get("created_at"),
        "created_by": freeze.get("created_by"),
        "status": freeze.get("status"),
        "audit_note": freeze.get("audit_note"),
        "payload_sha256": freeze.get("payload_sha256"),
        "cohort_label": freeze.get("cohort_label") or (payload.get("cohort_manifest") or {}).get("cohort_label"),
        "cohort_subject_count": int(summary.get("cohort_subject_count") or freeze.get("patient_count_primary_window") or 0),
        "total_data_rows": int(summary.get("total_data_rows") or freeze.get("trace_row_count") or 0),
        "file_count": len(file_manifest),
        "direct_identifier_key_count": direct_phi,
        "exact_phi_hit_count": exact_phi,
        "critical_interop_block_count": interop_blocks,
        "unmapped_dictionary_count": unmapped,
        "quality_block_count": quality_block_count,
        "quality_status": "pass" if quality_block_count == 0 else "block",
        "download_allowed": quality_block_count == 0,
        "governance": governance,
        "file_manifest": file_manifest,
        "detail_url": f"/api/platform-readiness/research-pack-materializer/freezes/{freeze.get('freeze_key')}",
        "download_url": f"/api/platform-readiness/research-pack-materializer/freezes/{freeze.get('freeze_key')}/download",
    }
    if include_payload:
        item["payload"] = payload
    return item


def _best_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _file_manifest_from_freeze(
    freeze: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    payload_manifest = payload.get("file_manifest")
    if isinstance(payload_manifest, list):
        return [dict(item) for item in payload_manifest if isinstance(item, Mapping)]
    dataset = freeze.get("dataset")
    if isinstance(dataset, list):
        return [dict(item) for item in dataset if isinstance(item, Mapping)]
    return []


def _normalize_governance(
    governance: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, str]:
    status = str(governance.get("governance_status") or "").strip().lower()
    if status not in GOVERNANCE_STATUSES:
        status = _infer_governance_status(summary)
    return {
        "governance_status": status,
        "clinical_objective": _clean_text(
            governance.get("clinical_objective"),
            "Auditoria institucional desidentificada de cancer de prostata.",
        ),
        "research_question": _clean_text(
            governance.get("research_question"),
            "Que patrones clinicos, longitudinales y economicos emergen en la cohorte congelada?",
        ),
        "methodology_note": _clean_text(
            governance.get("methodology_note"),
            "Pack local desidentificado con lineage Ledger y revision humana requerida antes de uso externo.",
        ),
        "responsible": _clean_text(governance.get("responsible"), "clinician"),
    }


def _infer_governance_status(summary: Mapping[str, Any]) -> str:
    blockers = sum(
        int(summary.get(key) or 0)
        for key in (
            "direct_identifier_key_count",
            "exact_phi_hit_count",
            "critical_interop_block_count",
            "unmapped_dictionary_count",
        )
    )
    if blockers:
        return "insufficient_quality"
    if summary.get("next_layer_allowed") is False:
        return "insufficient_quality"
    if int(summary.get("cohort_subject_count") or 0) >= 1:
        return "audit_ready"
    return "exploratory"


def _build_library_summary(
    items: list[Mapping[str, Any]],
    current_pack: Mapping[str, Any],
) -> dict[str, Any]:
    current_summary = current_pack.get("summary") or {}
    counts = Counter(str(item.get("governance", {}).get("governance_status") or "exploratory") for item in items)
    return {
        "freeze_count": len(items),
        "download_ready_count": sum(1 for item in items if item.get("download_allowed")),
        "quality_block_count": sum(1 for item in items if item.get("quality_status") == "block"),
        "latest_created_at": items[0].get("created_at") if items else None,
        "governance_status_counts": dict(counts),
        "current_freeze_allowed": bool(current_summary.get("freeze_allowed")),
        "current_materializer_status": current_summary.get("materializer_status"),
        "current_total_data_rows": int(current_summary.get("total_data_rows") or 0),
        "current_cohort_subject_count": int(current_summary.get("cohort_subject_count") or 0),
        "next_layer_allowed": bool(current_summary.get("next_layer_allowed", True)),
    }


def _clean_text(value: Any, default: str) -> str:
    text = " ".join(str(value or "").strip().split())
    return text or default
