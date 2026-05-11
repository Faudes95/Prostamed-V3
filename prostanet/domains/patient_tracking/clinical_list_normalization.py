from __future__ import annotations

from typing import Any


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _split_text_list(value: str) -> list[str]:
    normalized = str(value or "").replace("\n", ",").replace(";", ",").replace("|", ",")
    return [chunk.strip() for chunk in normalized.split(",") if chunk.strip()]


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        preferred_keys = (
            "text",
            "value",
            "label",
            "name",
            "title",
            "description",
            "summary",
            "result",
            "findings",
            "conclusion",
            "raw_text",
        )
        parts: list[str] = []
        for key in preferred_keys:
            text = coerce_text(value.get(key))
            if text:
                parts.append(text)
        if parts:
            return " ".join(dict.fromkeys(parts))
        fallback = [coerce_text(item) for item in value.values()]
        return " ".join(part for part in fallback if part).strip()
    if isinstance(value, (list, tuple, set)):
        parts = [coerce_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return str(value).strip()


def normalize_named_entries(
    value: Any,
    *,
    default_name_key: str = "name",
    alias_keys: tuple[str, ...] = ("name", "drug", "medication", "title", "label", "value"),
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]

    if isinstance(value, str):
        return [{default_name_key: item, "raw_text": item} for item in _split_text_list(value)]

    if not isinstance(value, (list, tuple)):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        if isinstance(item, str):
            for token in _split_text_list(item):
                normalized.append({default_name_key: token, "raw_text": token})
            continue
        if _is_present(item):
            text = str(item).strip()
            if text:
                normalized.append({default_name_key: text, "raw_text": text})

    sanitized: list[dict[str, Any]] = []
    for item in normalized:
        resolved = dict(item)
        for key in alias_keys:
            if _is_present(resolved.get(key)):
                resolved.setdefault(default_name_key, resolved.get(key))
                break
        sanitized.append(resolved)
    return sanitized


def normalize_medication_entries(value: Any) -> list[dict[str, Any]]:
    return normalize_named_entries(
        value,
        default_name_key="name",
        alias_keys=("name", "drug", "medication", "title", "label", "value"),
    )


def normalize_imaging_entries(value: Any) -> list[dict[str, Any]]:
    return normalize_named_entries(
        value,
        default_name_key="study_type",
        alias_keys=("study_type", "title", "name", "value"),
    )


def normalize_followup_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
