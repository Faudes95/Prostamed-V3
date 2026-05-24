from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


NONREGIONAL_NODAL_SITE_LABELS: dict[str, str] = {
    "retroperitoneal": "Retroperitoneales",
    "mediastinal": "Mediastinales",
    "supraclavicular": "Supraclaviculares",
    "inguinal": "Inguinales",
    "other": "Otro sitio ganglionar",
}

BONE_SITE_LABELS: dict[str, str] = {
    "skull": "Cráneo",
    "cervical_spine": "Columna cervical",
    "thoracic_spine": "Columna torácica",
    "lumbar_spine": "Columna lumbar",
    "ribs_thorax": "Costillas / tórax",
    "pelvis_sacrum": "Pelvis / sacro",
    "humerus": "Húmero",
    "forearm": "Radio / cúbito",
    "femur": "Fémur",
    "tibia_fibula": "Tibia / peroné",
    "hand": "Mano",
    "foot": "Pie",
}

AXIAL_BONE_SITE_KEYS = (
    "skull",
    "cervical_spine",
    "thoracic_spine",
    "lumbar_spine",
    "ribs_thorax",
    "pelvis_sacrum",
)

APPENDICULAR_BONE_SITE_KEYS = (
    "humerus",
    "forearm",
    "femur",
    "tibia_fibula",
    "hand",
    "foot",
)

VISCERAL_SITE_LABELS: dict[str, str] = {
    "lung": "Pulmón",
    "liver": "Hígado",
    "brain": "Cerebro",
    "adrenal": "Suprarrenal",
    "pleura": "Pleura",
    "peritoneum": "Peritoneo",
    "other": "Otro visceral",
}

NONREGIONAL_NODAL_COUNT_FIELDS = tuple(f"nonregional_nodal_{key}_count" for key in NONREGIONAL_NODAL_SITE_LABELS)
BONE_COUNT_FIELDS = tuple(f"bone_{key}_count" for key in BONE_SITE_LABELS)
VISCERAL_COUNT_FIELDS = tuple(f"visceral_{key}_count" for key in VISCERAL_SITE_LABELS)

METASTATIC_PROFILE_FIELD_NAMES = (
    "nonregional_nodal_metastasis_present",
    "nonregional_nodal_count",
    "nonregional_nodal_sites",
    "nonregional_nodal_site_entries",
    "bone_metastasis_present",
    "bone_axial_count",
    "bone_appendicular_count",
    "bone_sites",
    "visceral_metastasis_present",
    "visceral_sites",
    "visceral_lesion_count",
    "metastatic_total_lesion_count",
    "metastasis_assessment_date",
    "metastasis_document_source",
    "metastasis_volume_context",
    "m_substage_resolved",
    "metastatic_profile_json",
    "bone_site_entries",
    "visceral_site_entries",
    "visceral_other_label",
    "nonregional_nodal_other_label",
) + NONREGIONAL_NODAL_COUNT_FIELDS + BONE_COUNT_FIELDS + VISCERAL_COUNT_FIELDS


def _parse_json_blob(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "positivo", "present"}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _normalize_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if _is_present(item)]
    parsed = _parse_json_blob(value, None)
    if isinstance(parsed, list):
        return [item for item in parsed if _is_present(item)]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _summarize_sites(entries: list[dict[str, Any]]) -> str:
    parts = []
    for item in entries:
        count = _safe_int(item.get("lesion_count"), 0)
        if count <= 0:
            continue
        label = str(item.get("label") or item.get("site") or "").strip()
        if not label:
            continue
        parts.append(f"{count} {label}")
    return ", ".join(parts)


def _normalize_site_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_stage_token(value: Any) -> str:
    text = str(value or "").strip().upper().replace("CM", "M")
    if text in {"M0", "M1", "M1A", "M1B", "M1C"}:
        return text
    if text in {"M1A.", "M1B.", "M1C."}:
        return text.rstrip(".")
    return ""


def _parse_iso_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_progression_signal(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"radiographic", "clinical", "mixed"} else ""


def _stage_label(stage: str) -> str:
    return {
        "M0": "M0",
        "M1_unspecified": "M1 documentado, subtipo anatómico pendiente",
        "M1a": "M1a: ganglios no regionales",
        "M1b": "M1b: metástasis óseas",
        "M1c": "M1c: metástasis viscerales",
    }.get(stage, stage or "M0")


def _normalize_dynamic_site_entries(
    value: Any,
    *,
    labels: dict[str, str],
    source: str = "",
    date: str = "",
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if value in (None, "", []):
        return {}, []
    raw_entries = value
    if isinstance(value, str):
        raw_entries = _parse_json_blob(value, [])
    if not isinstance(raw_entries, list):
        return {}, []

    counts: dict[str, int] = {}
    entry_totals: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        site_key = _normalize_site_key(item.get("site_key") or item.get("site") or item.get("location"))
        if site_key not in labels:
            continue
        lesion_count = _safe_int(item.get("lesion_count"), 0)
        if lesion_count <= 0:
            continue
        counts[site_key] = counts.get(site_key, 0) + lesion_count
        label_override = ""
        if site_key == "other":
            label_override = str(
                item.get("other_label")
                or item.get("label_override")
                or item.get("custom_label")
                or ""
            ).strip()
        label = label_override or labels.get(site_key, site_key)
        entry_key = (site_key, label.lower())
        bucket = entry_totals.setdefault(
            entry_key,
            {
                "site": site_key,
                "label": label,
                "lesion_count": 0,
                "source": source,
                "date": date,
            },
        )
        bucket["lesion_count"] += lesion_count
    return counts, list(entry_totals.values())


def _resolved_count(
    data: dict[str, Any],
    prefix: str,
    key: str,
    *,
    dynamic_counts: dict[str, int] | None = None,
) -> int:
    explicit = _safe_int(data.get(f"{prefix}_{key}_count"), 0)
    if explicit > 0:
        return explicit
    if dynamic_counts:
        return _safe_int(dynamic_counts.get(key), 0)
    return 0


def _site_entries_from_counts(
    data: dict[str, Any],
    prefix: str,
    labels: dict[str, str],
    *,
    other_label_field: str | None = None,
    dynamic_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key, default_label in labels.items():
        count = _resolved_count(data, prefix, key, dynamic_counts=dynamic_counts)
        if count <= 0:
            continue
        label = default_label
        if key == "other" and other_label_field and _is_present(data.get(other_label_field)):
            label = str(data.get(other_label_field)).strip()
        entries.append(
            {
                "site": key,
                "label": label,
                "lesion_count": count,
                "source": data.get("metastasis_document_source") or "",
                "date": data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or "",
            }
        )
    return entries


def _legacy_m_site(data: dict[str, Any]) -> tuple[str, int]:
    raw_site = str(data.get("metastasis_site") or "M0").strip()
    count = _safe_int(data.get("metastasis_count"), 0)
    if raw_site and raw_site not in {"M0", "No aplica"} and count == 0:
        count = 1
    if raw_site in {"Hueso", "Óseo", "Oseo"}:
        raw_site = "Bone"
    elif raw_site in {"Ganglio", "Ganglionar"}:
        raw_site = "Node"
    elif raw_site in {"Visceral"}:
        raw_site = "Visceral"
    return raw_site or "M0", count


def build_metastatic_profile(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    existing = data.get("metastatic_profile")
    if not existing:
        existing = _parse_json_blob(data.get("metastatic_profile_json"), {})
    if not isinstance(existing, dict):
        existing = {}

    bone_site_dynamic_counts, bone_site_dynamic_entries = _normalize_dynamic_site_entries(
        data.get("bone_site_entries"),
        labels=BONE_SITE_LABELS,
        source=str(data.get("metastasis_document_source") or ""),
        date=str(data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or ""),
    )
    visceral_site_dynamic_counts, visceral_site_dynamic_entries = _normalize_dynamic_site_entries(
        data.get("visceral_site_entries"),
        labels=VISCERAL_SITE_LABELS,
        source=str(data.get("metastasis_document_source") or ""),
        date=str(data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or ""),
    )
    nodal_site_dynamic_counts, nodal_site_dynamic_entries = _normalize_dynamic_site_entries(
        data.get("nonregional_nodal_site_entries"),
        labels=NONREGIONAL_NODAL_SITE_LABELS,
        source=str(data.get("metastasis_document_source") or ""),
        date=str(data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or ""),
    )

    nodal_sites = _site_entries_from_counts(
        data,
        "nonregional_nodal",
        NONREGIONAL_NODAL_SITE_LABELS,
        other_label_field="nonregional_nodal_other_label",
        dynamic_counts=nodal_site_dynamic_counts,
    ) or nodal_site_dynamic_entries or list(existing.get("nonregional_nodal_sites") or [])
    bone_sites = _site_entries_from_counts(
        data,
        "bone",
        BONE_SITE_LABELS,
        dynamic_counts=bone_site_dynamic_counts,
    ) or bone_site_dynamic_entries or list(existing.get("bone_sites") or [])
    visceral_sites = _site_entries_from_counts(
        data,
        "visceral",
        VISCERAL_SITE_LABELS,
        other_label_field="visceral_other_label",
        dynamic_counts=visceral_site_dynamic_counts,
    ) or visceral_site_dynamic_entries or list(existing.get("visceral_sites") or [])

    legacy_site, legacy_count = _legacy_m_site(data)

    nonregional_nodal_count = _safe_int(data.get("nonregional_nodal_count"), 0) or sum(
        _safe_int(item.get("lesion_count"), 0) for item in nodal_sites
    )
    bone_axial_count = _safe_int(data.get("bone_axial_count"), 0) or sum(
        _resolved_count(data, "bone", key, dynamic_counts=bone_site_dynamic_counts) for key in AXIAL_BONE_SITE_KEYS
    )
    if bone_axial_count <= 0:
        bone_axial_count = sum(
            _safe_int(item.get("lesion_count"), 0)
            for item in bone_sites
            if item.get("site") in AXIAL_BONE_SITE_KEYS
        )
    bone_appendicular_count = _safe_int(data.get("bone_appendicular_count"), 0) or sum(
        _resolved_count(data, "bone", key, dynamic_counts=bone_site_dynamic_counts) for key in APPENDICULAR_BONE_SITE_KEYS
    )
    if bone_appendicular_count <= 0:
        bone_appendicular_count = sum(
            _safe_int(item.get("lesion_count"), 0)
            for item in bone_sites
            if item.get("site") in APPENDICULAR_BONE_SITE_KEYS
        )
    visceral_lesion_count = _safe_int(data.get("visceral_lesion_count"), 0) or sum(
        _safe_int(item.get("lesion_count"), 0) for item in visceral_sites
    )

    # FIX #4 (Sprint 1 validación E2E): aceptar aliases comunes del payload.
    # Hallazgo: cliente externo (REST POST) puede usar `metastasis_visceral_
    # present` (orden invertido) y el parser lo ignoraba silenciosamente →
    # clasificación errónea como "bajo volumen oligometastatic" cuando había
    # mets viscerales declaradas. Aceptamos ambos órdenes para robustez.
    nonregional_nodal_present = (
        _is_truthy(data.get("nonregional_nodal_metastasis_present"))
        or _is_truthy(data.get("metastasis_nonregional_nodal_present"))
        or _is_truthy(data.get("nodal_metastasis_present"))
        or nonregional_nodal_count > 0
    )
    bone_present = (
        _is_truthy(data.get("bone_metastasis_present"))
        or _is_truthy(data.get("metastasis_bone_present"))
        or bone_axial_count + bone_appendicular_count > 0
    )
    visceral_present = (
        _is_truthy(data.get("visceral_metastasis_present"))
        or _is_truthy(data.get("metastasis_visceral_present"))   # FIX #4 alias
        or _is_truthy(data.get("visceral_mets_present"))          # alias corto
        or visceral_lesion_count > 0
    )

    truth_status = "missing"
    if any(_is_present(data.get(name)) for name in METASTATIC_PROFILE_FIELD_NAMES):
        truth_status = "captured"
    elif existing:
        truth_status = str(existing.get("metastatic_truth_status") or "captured")
    elif legacy_site not in {"", "M0", "No aplica"}:
        truth_status = "derived"

    if not (nonregional_nodal_present or bone_present or visceral_present):
        if legacy_site == "Visceral":
            visceral_present = True
            visceral_lesion_count = max(legacy_count, 1)
        elif legacy_site == "Bone":
            bone_present = True
            bone_axial_count = max(bone_axial_count, legacy_count)
        elif legacy_site == "Node":
            nonregional_nodal_present = True
            nonregional_nodal_count = max(nonregional_nodal_count, legacy_count)

    if visceral_present:
        m_substage = "M1c"
    elif bone_present:
        m_substage = "M1b"
    elif nonregional_nodal_present:
        m_substage = "M1a"
    elif legacy_site not in {"", "M0", "No aplica"}:
        m_substage = "M1"
    else:
        m_substage = "M0"

    total_count = _safe_int(data.get("metastatic_total_lesion_count"), 0)
    if total_count <= 0:
        total_count = max(
            legacy_count,
            nonregional_nodal_count + bone_axial_count + bone_appendicular_count + visceral_lesion_count,
        )
        if m_substage.startswith("M1") and total_count == 0:
            total_count = 1

    if m_substage == "M1c":
        legacy_metastasis_site = "Visceral"
    elif m_substage == "M1b":
        legacy_metastasis_site = "Bone"
    elif m_substage == "M1a":
        legacy_metastasis_site = "Node"
    elif m_substage == "M1":
        legacy_metastasis_site = "M1"
    else:
        legacy_metastasis_site = "M0"

    profile = {
        "m_substage_resolved": m_substage,
        "regional_nodal_metastasis_present": _is_truthy(data.get("regional_nodal_metastasis_present")),
        "nonregional_nodal_metastasis_present": nonregional_nodal_present,
        "nonregional_nodal_sites": nodal_sites,
        "nonregional_nodal_site_entries": nodal_sites,
        "nonregional_nodal_count": nonregional_nodal_count,
        "bone_metastasis_present": bone_present,
        "bone_axial_count": bone_axial_count,
        "bone_appendicular_count": bone_appendicular_count,
        "bone_sites": bone_sites,
        "visceral_metastasis_present": visceral_present,
        "visceral_sites": visceral_sites,
        "visceral_site_entries": visceral_sites,
        "visceral_lesion_count": visceral_lesion_count,
        "metastatic_total_lesion_count": total_count,
        "metastasis_assessment_date": data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or existing.get("metastasis_assessment_date") or "",
        "metastasis_document_source": data.get("metastasis_document_source") or existing.get("metastasis_document_source") or "",
        "bone_site_entries": bone_sites,
        "metastatic_truth_status": truth_status,
        "legacy_metastasis_site": legacy_metastasis_site,
        "legacy_metastasis_count": total_count,
        "metastatic_site_summary": {
            "nonregional_nodes": _summarize_sites(nodal_sites),
            "bone": _summarize_sites(bone_sites),
            "visceral": _summarize_sites(visceral_sites),
        },
    }
    profile["metastatic_components"] = [
        component
        for component, present in (
            ("nodes", nonregional_nodal_present),
            ("bone", bone_present),
            ("visceral", visceral_present),
        )
        if present
    ]
    profile["metastatic_component_count"] = len(profile["metastatic_components"])
    profile["has_mixed_metastatic_sites"] = profile["metastatic_component_count"] > 1
    burden_context = _derive_mhspc_burden_context_from_profile(profile, data)
    profile["metastasis_volume_context"] = burden_context.get("volume_disease", "")
    profile["metastatic_volume_reason"] = burden_context.get("volume_reason", "")
    profile["oligometastatic_operational"] = burden_context.get("oligometastatic_operational", False)
    profile["metastatic_burden_summary"] = summarize_metastatic_profile(profile)
    return profile


def summarize_metastatic_profile(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    if str(profile.get("m_substage_resolved") or "M0") == "M0":
        return "Sin metástasis a distancia documentadas"

    parts: list[str] = []
    nodal_summary = ((profile.get("metastatic_site_summary") or {}).get("nonregional_nodes") or "").strip()
    bone_summary = ((profile.get("metastatic_site_summary") or {}).get("bone") or "").strip()
    visceral_summary = ((profile.get("metastatic_site_summary") or {}).get("visceral") or "").strip()

    if nodal_summary:
        parts.append(f"ganglios no regionales: {nodal_summary}")
    elif profile.get("nonregional_nodal_metastasis_present"):
        parts.append(f"ganglios no regionales: {profile.get('nonregional_nodal_count') or 1}")
    if bone_summary:
        parts.append(f"hueso: {bone_summary}")
    elif profile.get("bone_metastasis_present"):
        parts.append(
            "hueso: "
            f"axial {profile.get('bone_axial_count') or 0}, "
            f"apendicular {profile.get('bone_appendicular_count') or 0}"
        )
    if visceral_summary:
        parts.append(f"víscera: {visceral_summary}")
    elif profile.get("visceral_metastasis_present"):
        parts.append(f"víscera: {profile.get('visceral_lesion_count') or 1}")

    if not parts:
        return "Metástasis a distancia sin subtipo anatómico completo"
    return " · ".join(parts)


def build_metastatic_composition_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    profile = build_metastatic_profile(data)
    burden = _derive_mhspc_burden_context_from_profile(profile, data or {})
    m_substage = str(profile.get("m_substage_resolved") or "M0")
    if m_substage == "M0":
        return {
            "available": False,
            "summary": "",
            "narrative": "",
            "metastatic_profile_summary": "",
            "m_substage_resolved": "M0",
            "volume_disease": "unknown",
            "volume_reason": "",
            "metastatic_components": [],
            "has_mixed_metastatic_sites": False,
            "bone_present": False,
            "visceral_present": False,
            "nonregional_nodal_present": False,
            "bone_distribution_summary": "",
            "visceral_distribution_summary": "",
            "supportive_implications": [],
        }

    summary = str(burden.get("metastatic_profile_summary") or summarize_metastatic_profile(profile))
    mixed = bool(burden.get("has_mixed_metastatic_sites"))
    bone_present = bool(burden.get("bone_present"))
    visceral_present = bool(burden.get("visceral_present"))
    nonregional_nodal_present = bool(burden.get("nonregional_nodal_present"))
    volume_disease = str(burden.get("volume_disease") or "unknown")
    volume_label = {
        "high": "alto volumen",
        "low": "bajo volumen",
        "unknown": "volumen no resuelto",
    }.get(volume_disease, volume_disease or "volumen no resuelto")

    if mixed:
        composition_label = "Enfermedad metastásica mixta"
    elif visceral_present:
        composition_label = "Enfermedad metastásica visceral"
    elif bone_present:
        composition_label = "Enfermedad metastásica ósea"
    elif nonregional_nodal_present:
        composition_label = "Enfermedad metastásica ganglionar no regional"
    else:
        composition_label = "Enfermedad metastásica a distancia"

    supportive_implications: list[str] = []
    if visceral_present:
        supportive_implications.append("El componente visceral mantiene un fenotipo sistémico de alto volumen.")
    if bone_present:
        supportive_implications.append("Mantener bundle óseo visible y vigilancia de eventos esqueléticos.")
    if mixed:
        supportive_implications.append("La composición mixta no debe colapsarse a un único sitio metastásico en la narrativa ni en la decisión clínica.")
    elif nonregional_nodal_present and not (visceral_present or bone_present):
        supportive_implications.append("La enfermedad ganglionar no regional aislada sigue siendo metastásica, pero no cumple por sí sola criterio anatómico de alto volumen.")

    narrative = f"{composition_label} de {volume_label} ({m_substage}) con {summary}."
    volume_reason = str(burden.get("volume_reason") or "").strip()
    if volume_reason:
        narrative = f"{narrative} {volume_reason}"
    if bone_present and visceral_present:
        narrative = f"{narrative} Mantener visibles tanto la intensificación sistémica como el bundle óseo."
    elif bone_present:
        narrative = f"{narrative} Mantener bundle óseo visible durante el seguimiento."

    return {
        "available": True,
        "summary": summary,
        "narrative": narrative.strip(),
        "metastatic_profile_summary": summary,
        "m_substage_resolved": m_substage,
        "volume_disease": volume_disease,
        "volume_reason": volume_reason,
        "metastatic_components": list(burden.get("metastatic_components") or []),
        "has_mixed_metastatic_sites": mixed,
        "bone_present": bone_present,
        "visceral_present": visceral_present,
        "nonregional_nodal_present": nonregional_nodal_present,
        "bone_distribution_summary": str(burden.get("bone_distribution_summary") or ""),
        "visceral_distribution_summary": str(burden.get("visceral_distribution_summary") or ""),
        "supportive_implications": supportive_implications,
    }


def resolve_metastatic_state_context(
    data: dict[str, Any] | None,
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    data = data or {}
    profile = build_metastatic_profile(data)
    profile_stage = str(profile.get("m_substage_resolved") or "M0").upper()
    conventional_stage = _normalize_stage_token(
        data.get("conventional_imaging_status") or data.get("conventional_stage_before_psma")
    )
    psma_stage = _normalize_stage_token(data.get("psma_stage_after_psma"))
    psma_result = str(data.get("psma_result") or "").strip().lower()
    psma_positive = (
        _is_truthy(data.get("psma_positive"))
        or psma_stage.startswith("M1")
        or psma_result in {"positivo", "positive", "metástasis", "metastasis", "diseminado"}
    )
    conventional_positive = conventional_stage.startswith("M1")
    metastatic_known = (
        profile_stage != "M0"
        or conventional_positive
        or psma_positive
        or _is_truthy(data.get("metastatic_disease_known"))
        or (
            _is_present(data.get("metastasis_site"))
            and str(data.get("metastasis_site") or "").strip().upper() not in {"M0", "NO", "NONE"}
        )
    )

    metastatic_stage_resolved = "M0"
    if profile_stage in {"M1A", "M1B", "M1C"}:
        metastatic_stage_resolved = profile_stage[0] + profile_stage[1:].lower()
    elif profile_stage == "M1":
        metastatic_stage_resolved = "M1_unspecified"
    elif psma_stage in {"M1A", "M1B", "M1C"}:
        metastatic_stage_resolved = psma_stage[0] + psma_stage[1:].lower()
    elif psma_stage == "M1":
        metastatic_stage_resolved = "M1_unspecified"
    elif conventional_stage in {"M1A", "M1B", "M1C"}:
        metastatic_stage_resolved = conventional_stage[0] + conventional_stage[1:].lower()
    elif conventional_stage == "M1":
        metastatic_stage_resolved = "M1_unspecified"
    elif metastatic_known:
        metastatic_stage_resolved = "M1_unspecified"

    if psma_positive and conventional_positive:
        metastatic_detection_basis = "both"
    elif conventional_positive:
        metastatic_detection_basis = "conventional"
    elif psma_positive:
        metastatic_detection_basis = "psma_only"
    elif metastatic_stage_resolved != "M0":
        metastatic_detection_basis = "unknown"
    else:
        metastatic_detection_basis = "unknown"

    assessment_date_raw = (
        data.get("metastasis_assessment_date")
        or data.get("psma_study_date")
        or data.get("study_date")
        or data.get("conventional_imaging_date")
        or data.get("visit_date")
        or ""
    )
    assessment_date = _parse_iso_date(assessment_date_raw)
    currentness = "unknown"
    if assessment_date:
        currentness_days = ((reference_date or date.today()) - assessment_date).days
        if currentness_days <= 180:
            currentness = "current"
        elif currentness_days <= 365:
            currentness = "aging"
        else:
            currentness = "stale"

    progression_pattern = _normalize_progression_signal(data.get("progression_pattern"))
    disease_status = str(data.get("disease_status") or "").strip().lower()
    suspected_systemic_progression = (
        _is_truthy(data.get("suspected_systemic_progression"))
        or progression_pattern in {"radiographic", "clinical", "mixed"}
        or any(token in disease_status for token in ("progres", "radiograf", "symptom", "sintom", "clínic", "clinic"))
    )
    restaging_update_required = metastatic_stage_resolved != "M0" and (
        currentness == "stale" or suspected_systemic_progression
    )
    if metastatic_stage_resolved == "M0":
        restaging_update_reason = ""
    elif suspected_systemic_progression:
        restaging_update_reason = "M1 documentado; existe sospecha de progresión sistémica y se requiere nueva restadificación."
    elif currentness == "stale":
        restaging_update_reason = "M1 ya documentado; la imagen metastásica está desactualizada y se requiere restadificación actualizada."
    elif currentness == "aging":
        restaging_update_reason = "M1 documentado con imagen envejecida; mantener vigilancia de actualización si cambia la trayectoria clínica."
    else:
        restaging_update_reason = ""

    return {
        "metastatic_known": metastatic_stage_resolved != "M0",
        "metastatic_stage_resolved": metastatic_stage_resolved,
        "metastatic_stage_label": _stage_label(metastatic_stage_resolved),
        "m_substage_resolved_legacy": profile_stage if profile_stage != "M0" else ("M1" if metastatic_stage_resolved == "M1_unspecified" else "M0"),
        "metastatic_detection_basis": metastatic_detection_basis,
        "metastasis_assessment_date": str(assessment_date_raw or ""),
        "restaging_currentness_status": currentness,
        "restaging_update_required": restaging_update_required,
        "restaging_update_reason": restaging_update_reason,
        "suspected_systemic_progression": suspected_systemic_progression,
    }


def derive_legacy_metastasis(data: dict[str, Any] | None) -> tuple[str, int, str]:
    profile = build_metastatic_profile(data)
    return (
        str(profile.get("legacy_metastasis_site") or "M0"),
        _safe_int(profile.get("legacy_metastasis_count"), 0),
        str(profile.get("m_substage_resolved") or "M0"),
    )


def _derive_mhspc_burden_context_from_profile(profile: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    m_substage = str(profile.get("m_substage_resolved") or "M0").upper()
    legacy_site = str(profile.get("legacy_metastasis_site") or "M0")
    metastatic_total = _safe_int(profile.get("metastatic_total_lesion_count"), 0)
    bone_axial = _safe_int(profile.get("bone_axial_count"), 0)
    bone_appendicular = _safe_int(profile.get("bone_appendicular_count"), 0)
    total_bone = bone_axial + bone_appendicular
    visceral_present = bool(profile.get("visceral_metastasis_present"))
    explicit_volume = str(data.get("volume_disease") or "").strip().lower()
    volume_disease = "unknown"
    volume_reason = ""
    volume_source = "derived"

    if visceral_present or m_substage == "M1C":
        volume_disease = "high"
        volume_reason = "Alto volumen por metástasis viscerales documentadas."
    elif total_bone >= 4 and bone_appendicular >= 1:
        volume_disease = "high"
        volume_reason = f"Alto volumen por {total_bone} lesiones óseas con al menos una en esqueleto apendicular."
    elif total_bone >= 4 and bone_axial >= 4 and bone_appendicular == 0:
        volume_disease = "low"
        volume_reason = f"Bajo volumen porque las {total_bone} lesiones óseas documentadas permanecen confinadas al esqueleto axial."
    elif m_substage in {"M1A", "M1B"} and metastatic_total > 0:
        volume_disease = "low"
        if total_bone > 0:
            volume_reason = f"Bajo volumen por enfermedad ósea sin criterio anatómico de alto volumen ({total_bone} lesiones; apendicular {bone_appendicular})."
        else:
            volume_reason = "Bajo volumen por enfermedad metastásica sin criterio anatómico de alto volumen."
    elif explicit_volume in {"high", "low"}:
        volume_disease = explicit_volume
        volume_source = "legacy_explicit"
        volume_reason = (
            "Se conserva el volumen legado explícito ante distribución anatómica incompleta."
            if metastatic_total > 0
            else "Volumen legado explícito conservado por compatibilidad."
        )
    elif legacy_site == "Visceral":
        volume_disease = "high"
        volume_source = "legacy_coarse"
        volume_reason = "Alto volumen por metástasis viscerales registradas en contexto legado."
    elif legacy_site in {"Bone", "Node", "M1"} and metastatic_total > 0:
        volume_disease = "low"
        volume_source = "legacy_coarse"
        volume_reason = "Carga metastásica registrada sin distribución anatómica completa; se conserva clasificación operativa de bajo volumen."

    return {
        "metastasis_count": metastatic_total,
        "bone_axial_count": bone_axial,
        "bone_appendicular_count": bone_appendicular,
        "m_substage_resolved": m_substage,
        "volume_disease": volume_disease,
        "volume_reason": volume_reason,
        "volume_source": volume_source,
        "oligometastatic_operational": (
            metastatic_total > 0
            and metastatic_total <= 5
            and not visceral_present
            and volume_disease != "high"
        ),
        "legacy_metastasis_site": legacy_site,
        "bone_present": bool(profile.get("bone_metastasis_present")),
        "visceral_present": visceral_present,
        "nonregional_nodal_present": bool(profile.get("nonregional_nodal_metastasis_present")),
        "has_mixed_metastatic_sites": bool(profile.get("has_mixed_metastatic_sites")),
        "metastatic_components": list(profile.get("metastatic_components") or []),
        "metastatic_profile_summary": str(profile.get("metastatic_burden_summary") or summarize_metastatic_profile(profile)),
        "nodal_distribution_summary": str(((profile.get("metastatic_site_summary") or {}).get("nonregional_nodes")) or ""),
        "bone_distribution_summary": str(((profile.get("metastatic_site_summary") or {}).get("bone")) or ""),
        "visceral_distribution_summary": str(((profile.get("metastatic_site_summary") or {}).get("visceral")) or ""),
        "nonregional_nodal_sites": list(profile.get("nonregional_nodal_sites") or []),
        "visceral_sites": list(profile.get("visceral_sites") or []),
    }


def derive_mhspc_burden_context(data: dict[str, Any] | None) -> dict[str, Any]:
    profile = build_metastatic_profile(data)
    return _derive_mhspc_burden_context_from_profile(profile, data or {})


def derive_mhspc_volume_context(data: dict[str, Any] | None) -> str:
    return str(derive_mhspc_burden_context(data).get("volume_disease") or "unknown")


def has_bone_metastatic_component(data: dict[str, Any] | None) -> bool:
    return bool(build_metastatic_profile(data).get("bone_metastasis_present"))


def has_visceral_metastatic_component(data: dict[str, Any] | None) -> bool:
    return bool(build_metastatic_profile(data).get("visceral_metastasis_present"))
