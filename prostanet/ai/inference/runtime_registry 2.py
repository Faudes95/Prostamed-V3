from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from prostanet.ai.inference.model_registry import DEFAULT_MODELS_DIR, ModelRegistry


_RUNTIME_REGISTRY: ModelRegistry | None = None
_RUNTIME_MODELS_DIR: Path | None = None
_RUNTIME_LOCK = Lock()
_LAST_BOOTSTRAP_SIGNATURE: tuple[tuple[str, str, bool, int | None, str, bool], ...] | None = None
_LAST_BOOTSTRAP_AT: str | None = None
_BOOTSTRAP_COMPLETED = False
_BOOTSTRAP_GENERATION = 0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_models_dir(models_dir: str | Path | None = None) -> Path:
    if models_dir is not None:
        return Path(models_dir)
    from prostanet.ai.config import get_ai_config

    config = get_ai_config()
    return Path(config.model_dir or DEFAULT_MODELS_DIR)


def _build_registry_signature(registry: ModelRegistry) -> tuple[tuple[str, str, bool, int | None, str, bool], ...]:
    signature: list[tuple[str, str, bool, int | None, str, bool]] = []
    for model_id in registry._known_models:
        # Build the signature from fresh status metadata so the provider can detect
        # artifacts appearing on disk even if runtime metadata still reflects an older miss.
        metadata = registry._build_status_metadata(model_id)
        artifact_path = Path(metadata.get("artifact_path") or registry.models_dir / model_id / "best.pt")
        artifact_exists = artifact_path.exists()
        stat_mtime = artifact_path.stat().st_mtime_ns if artifact_exists and artifact_path.exists() else None
        signature.append(
            (
                model_id,
                str(artifact_path),
                artifact_exists,
                stat_mtime,
                str(metadata.get("model_version") or "unregistered"),
                bool(metadata.get("artifact_registered")),
            )
        )
    return tuple(signature)


def _runtime_readiness(registry: ModelRegistry | None) -> str:
    if not _BOOTSTRAP_COMPLETED or registry is None:
        return "not_initialized"
    loaded_count = sum(1 for model_id in registry._known_models if registry.is_loaded(model_id))
    return "advisory_ready" if loaded_count > 0 else "not_ready"


def _bootstrap_registry(registry: ModelRegistry) -> ModelRegistry:
    global _LAST_BOOTSTRAP_SIGNATURE, _LAST_BOOTSTRAP_AT, _BOOTSTRAP_COMPLETED, _BOOTSTRAP_GENERATION

    registry.load_all_available()
    _LAST_BOOTSTRAP_SIGNATURE = _build_registry_signature(registry)
    _LAST_BOOTSTRAP_AT = _utc_timestamp()
    _BOOTSTRAP_COMPLETED = True
    _BOOTSTRAP_GENERATION += 1
    return registry


def get_runtime_model_registry(
    *,
    force_refresh: bool = False,
    models_dir: str | Path | None = None,
) -> ModelRegistry:
    global _RUNTIME_REGISTRY, _RUNTIME_MODELS_DIR

    resolved_models_dir = _resolve_models_dir(models_dir)
    with _RUNTIME_LOCK:
        models_dir_changed = _RUNTIME_MODELS_DIR != resolved_models_dir
        if force_refresh or _RUNTIME_REGISTRY is None or models_dir_changed:
            _RUNTIME_REGISTRY = ModelRegistry(models_dir=resolved_models_dir)
            _RUNTIME_MODELS_DIR = resolved_models_dir
            return _bootstrap_registry(_RUNTIME_REGISTRY)

        current_signature = _build_registry_signature(_RUNTIME_REGISTRY)
        if current_signature != _LAST_BOOTSTRAP_SIGNATURE:
            return _bootstrap_registry(_RUNTIME_REGISTRY)

        return _RUNTIME_REGISTRY


def get_runtime_registry_health(
    *,
    registry: ModelRegistry | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_registry = registry or get_runtime_model_registry(models_dir=models_dir)
    models = resolved_registry.list_models()
    loaded_model_ids = [model_id for model_id, metadata in models.items() if metadata.get("loaded")]
    missing_model_ids = [
        model_id
        for model_id, metadata in models.items()
        if not metadata.get("artifact_exists")
    ]
    return {
        "bootstrap_completed": _BOOTSTRAP_COMPLETED,
        "bootstrap_generation": _BOOTSTRAP_GENERATION,
        "last_bootstrap_at": _LAST_BOOTSTRAP_AT,
        "models_dir": str(resolved_registry.models_dir),
        "loaded_model_count": len(loaded_model_ids),
        "loaded_model_ids": loaded_model_ids,
        "missing_model_ids": missing_model_ids,
        "runtime_readiness": _runtime_readiness(resolved_registry),
    }


def get_runtime_model_status(
    model_id: str,
    *,
    registry: ModelRegistry | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_registry = registry or get_runtime_model_registry(models_dir=models_dir)
    metadata = resolved_registry.get_metadata(model_id)
    return {
        **metadata,
        **get_runtime_registry_health(registry=resolved_registry),
    }


def reset_runtime_model_registry() -> None:
    global _RUNTIME_REGISTRY, _RUNTIME_MODELS_DIR, _LAST_BOOTSTRAP_SIGNATURE, _LAST_BOOTSTRAP_AT, _BOOTSTRAP_COMPLETED, _BOOTSTRAP_GENERATION
    with _RUNTIME_LOCK:
        _RUNTIME_REGISTRY = None
        _RUNTIME_MODELS_DIR = None
        _LAST_BOOTSTRAP_SIGNATURE = None
        _LAST_BOOTSTRAP_AT = None
        _BOOTSTRAP_COMPLETED = False
        _BOOTSTRAP_GENERATION = 0
        ModelRegistry.reset_process_log_state()
