from __future__ import annotations

from typing import Any


PSMA_RADIOLIGAND_OPTIONS = [
    "68Ga-PSMA-11",
    "18F-DCFPyL",
    "18F-PSMA-1007",
    "Otro",
    "Desconocido",
]

PSMA_UPTAKE_PATTERN_OPTIONS = [
    "focal",
    "multifocal",
    "diseminado",
    "indeterminado",
]

PSMA_RADS_OPTIONS = ["1", "2", "3", "4", "5", "Desconocido"]

PSMA_STAGE_OPTIONS = ["No comparable", "M0", "M1a", "M1b", "M1c"]


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def normalize_psma_radioligand(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "68" in lowered and "psma" in lowered:
        return "68Ga-PSMA-11"
    if "dcfpyl" in lowered:
        return "18F-DCFPyL"
    if "1007" in lowered:
        return "18F-PSMA-1007"
    if lowered in {"otro", "other"}:
        return "Otro"
    if lowered in {"desconocido", "unknown"}:
        return "Desconocido"
    return text


def normalize_psma_pattern(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in {"focal", "multifocal", "diseminado", "indeterminado"}:
        return text
    if "local" in text or "focal" in text or "pelv" in text:
        return "focal"
    if "oligo" in text or "multi" in text:
        return "multifocal"
    if "disemin" in text or "extenso" in text or "widespread" in text:
        return "diseminado"
    return "indeterminado"


def normalize_psma_rads(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits in {"1", "2", "3", "4", "5"}:
        return digits
    if text.lower() in {"desconocido", "unknown"}:
        return "Desconocido"
    return text


def normalize_stage_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in {"M0", "M1A", "M1B", "M1C"}:
        return upper.replace("A", "a").replace("B", "b").replace("C", "c")
    lowered = text.lower()
    if lowered in {"no comparable", "not comparable", "incomparable"}:
        return "No comparable"
    return text


def derive_psma_positive(psma_result: Any, total_lesions: Any = None, locations: list[Any] | None = None, suvmax: Any = None) -> bool:
    result_text = str(psma_result or "").strip().lower()
    if result_text.startswith("pos") or result_text in {"local/pélvico", "oligometastásico", "diseminado", "local", "ganglionar", "oseo", "óseo", "visceral"}:
        return True
    if "neg" in result_text:
        return False
    if _is_present(total_lesions) and int(float(total_lesions or 0)) > 0:
        return True
    if locations:
        return True
    try:
        return float(suvmax or 0) > 0
    except (TypeError, ValueError):
        return False

