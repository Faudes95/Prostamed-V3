from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from prostanet.ai.inference.model_registry import DEFAULT_MODELS_DIR, ModelRegistry


_RUNTIME_REGISTRY: ModelRegistry | None = None
_RUNTIME_MODELS_DIR: Path | None = None
_RUNTIME_LOCK = Lock()
_LAST_BOOTSTRAP_SIGNATURE: dict[str, Any] = {}
_LAST_BOOTSTRAP_AT = ""
_BOOTSTRAP_COMPLETED = False
_BOOTSTRAP_GENERATION = 0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_models_dir(models_dir: str | Path | None = None) -> Path:
    if models_dir:
        return Path(models_dir)
    try:
        from prostanet.ai.config import get_ai_config

        config = get_ai_config()
        if getattr(config, "model_dir", None):
            return Path(config.model_dir)
    except Exception:
        pass
    return DEFAULT_MODELS_DIR


def _build_registry_signature(registry: ModelRegistry) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    for model_id, metadata in registry.list_models().items():
        artifact_path = Path(str(metadata.get("artifact_path") or ""))
        artifact_exists = artifact_path.exists()
        signature[model_id] = {
            "loaded": bool(metadata.get("loaded")),
            "artifact_path": str(artifact_path),
            "artifact_exists": artifact_exists,
            "artifact_mtime": artifact_path.stat().st_mtime if artifact_exists else None,
            "model_version": str(metadata.get("model_version") or ""),
            "load_error": str(metadata.get("load_error") or ""),
        }
    return signature


def _runtime_readiness(registry: ModelRegistry) -> dict[str, Any]:
    models = registry.list_models()
    loaded_model_ids = [
        model_id for model_id, item in models.items() if item.get("loaded")
    ]
    missing_model_ids = [
        model_id for model_id, item in models.items() if not item.get("loaded")
    ]
    loaded_count = len(loaded_model_ids)
    return {
        "ready": loaded_count > 0,
        "loaded_count": loaded_count,
        "loaded_model_count": loaded_count,
        "loaded_model_ids": loaded_model_ids,
        "missing_model_ids": missing_model_ids,
        "known_count": len(models),
        "runtime_readiness": "advisory_ready" if loaded_count > 0 else "not_ready",
        "models": models,
    }


def _bootstrap_registry(registry: ModelRegistry) -> dict[str, bool]:
    if str(os.environ.get("PROSTANET_LOAD_MODEL") or "").lower() in {"0", "false", "no", "off"}:
        return {}
    try:
        return registry.load_all_available()
    except Exception:
        return {}


def get_runtime_model_registry(
    *,
    force_refresh: bool = False,
    models_dir: str | Path | None = None,
) -> ModelRegistry:
    global _RUNTIME_REGISTRY, _RUNTIME_MODELS_DIR, _LAST_BOOTSTRAP_SIGNATURE
    global _LAST_BOOTSTRAP_AT, _BOOTSTRAP_COMPLETED, _BOOTSTRAP_GENERATION

    resolved_models_dir = _resolve_models_dir(models_dir)
    with _RUNTIME_LOCK:
        models_dir_changed = _RUNTIME_MODELS_DIR is not None and _RUNTIME_MODELS_DIR != resolved_models_dir
        if _RUNTIME_REGISTRY is None or force_refresh or models_dir_changed:
            ModelRegistry.reset_process_log_state()
            _RUNTIME_REGISTRY = ModelRegistry(resolved_models_dir)
            _RUNTIME_MODELS_DIR = resolved_models_dir
            _bootstrap_registry(_RUNTIME_REGISTRY)
            _LAST_BOOTSTRAP_SIGNATURE = _build_registry_signature(_RUNTIME_REGISTRY)
            _LAST_BOOTSTRAP_AT = _utc_timestamp()
            _BOOTSTRAP_COMPLETED = True
            _BOOTSTRAP_GENERATION += 1
        elif _build_registry_signature(_RUNTIME_REGISTRY) != _LAST_BOOTSTRAP_SIGNATURE:
            ModelRegistry.reset_process_log_state()
            _bootstrap_registry(_RUNTIME_REGISTRY)
            _LAST_BOOTSTRAP_SIGNATURE = _build_registry_signature(_RUNTIME_REGISTRY)
            _LAST_BOOTSTRAP_AT = _utc_timestamp()
            _BOOTSTRAP_COMPLETED = True
            _BOOTSTRAP_GENERATION += 1
        return _RUNTIME_REGISTRY


def get_runtime_registry_health(
    *,
    registry: ModelRegistry | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_registry = registry or get_runtime_model_registry(models_dir=models_dir)
    readiness = _runtime_readiness(resolved_registry)
    return {
        **readiness,
        "models_dir": str(getattr(resolved_registry, "models_dir", _resolve_models_dir(models_dir))),
        "bootstrap_completed": _BOOTSTRAP_COMPLETED,
        "bootstrap_generation": _BOOTSTRAP_GENERATION,
        "last_bootstrap_at": _LAST_BOOTSTRAP_AT,
        "last_bootstrap_signature": dict(_LAST_BOOTSTRAP_SIGNATURE),
    }


def get_runtime_model_status(
    model_id: str,
    *,
    registry: ModelRegistry | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_registry = registry or get_runtime_model_registry(models_dir=models_dir)
    metadata = resolved_registry.get_metadata(model_id)
    health = get_runtime_registry_health(registry=resolved_registry)
    return {
        **metadata,
        **health,
        "model_id": model_id,
        "runtime_loaded": bool(resolved_registry.is_loaded(model_id)),
        "runtime_health": health,
    }


def reset_runtime_model_registry() -> None:
    global _RUNTIME_REGISTRY, _RUNTIME_MODELS_DIR, _LAST_BOOTSTRAP_SIGNATURE
    global _LAST_BOOTSTRAP_AT, _BOOTSTRAP_COMPLETED, _BOOTSTRAP_GENERATION
    with _RUNTIME_LOCK:
        _RUNTIME_REGISTRY = None
        _RUNTIME_MODELS_DIR = None
        _LAST_BOOTSTRAP_SIGNATURE = {}
        _LAST_BOOTSTRAP_AT = ""
        _BOOTSTRAP_COMPLETED = False
        _BOOTSTRAP_GENERATION = 0
        ModelRegistry.reset_process_log_state()


__all__ = [
    "get_runtime_model_registry",
    "get_runtime_registry_health",
    "get_runtime_model_status",
    "reset_runtime_model_registry",
]
