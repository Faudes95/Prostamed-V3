from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


_UNAVAILABLE_VALUES = {
    "",
    "0",
    "no disponible",
    "no documentado",
    "no documentada",
    "no evaluable",
    "no estadificable",
    "desconocido",
    "desconocida",
    "unknown",
    "pendiente",
    "none",
    "null",
    "n/a",
    "na",
    "-",
    "—",
}

_YES_VALUES = {"1", "true", "yes", "si", "sí", "on", "realizada", "sospechoso", "sospechosa"}
_NO_VALUES = {"0", "false", "no", "off", "normal", "no realizada"}
_TSTAGE_PATTERN = re.compile(r"\bC?T(1C?|2A|2B|2C|3A|3B|3|4)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DreContext:
    is_suspicious: bool
    implied_tstage: str | None
    summary_label: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PsadContext:
    value: float | None
    display: str
    source: str
    calculable: bool
    missing_inputs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MriContext:
    done: bool | None
    pirads: int | None
    display: str
    quality: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_dre_context(payload: dict[str, Any]) -> DreContext:
    """Normaliza TR/DRE desde campos nuevos y legacy sin depender del UI."""

    for source, raw in (
        ("dre_finding", payload.get("dre_finding")),
        ("clinical_tstage_dre_estimate", payload.get("clinical_tstage_dre_estimate")),
    ):
        stage = _extract_tstage(raw)
        if stage:
            suspicious = stage not in {"cT1", "cT1c"}
            return DreContext(
                is_suspicious=suspicious,
                implied_tstage=stage,
                summary_label=(
                    f"sospechoso compatible con {stage}"
                    if suspicious
                    else f"no sospechoso compatible con {stage}"
                ),
                source=source,
            )

    if _is_truthy(payload.get("dre_suspicious")):
        return DreContext(
            is_suspicious=True,
            implied_tstage="cT2a",
            summary_label="sospechoso",
            source="dre_suspicious",
        )

    if _suggests_locally_advanced_dre(payload):
        return DreContext(
            is_suspicious=True,
            implied_tstage="cT3",
            summary_label="sospechoso con datos clínicos de extensión local",
            source="dre_detail",
        )

    return DreContext(
        is_suspicious=False,
        implied_tstage=None,
        summary_label="no sospechoso",
        source="absent_or_normal",
    )


def derive_psad_context(payload: dict[str, Any], *, psa_value: float | None = None) -> PsadContext:
    """Deriva PSAD desde PSA y volumen; no presenta cero como dato clínico."""

    explicit = _first_positive_float(
        payload.get("psad"),
        payload.get("psa_density"),
        payload.get("mri_psa_density"),
    )
    if explicit is not None:
        return PsadContext(
            value=explicit,
            display=f"{explicit:.2f} ng/mL/cc",
            source="explicit",
            calculable=True,
            missing_inputs=[],
        )

    psa = _safe_float(psa_value)
    if psa is None:
        psa = _first_positive_float(payload.get("psa"), payload.get("psa_value"))
    volume = _first_positive_float(payload.get("prostate_volume_ml"), payload.get("mri_prostate_volume_ml"))

    missing: list[str] = []
    if psa is None or psa <= 0:
        missing.append("psa")
    if volume is None or volume <= 0:
        missing.append("prostate_volume_ml")

    if not missing and psa is not None and volume is not None:
        value = psa / volume
        return PsadContext(
            value=value,
            display=f"{value:.2f} ng/mL/cc",
            source="derived_from_psa_and_volume",
            calculable=True,
            missing_inputs=[],
        )

    if missing == ["prostate_volume_ml"]:
        display = "no calculable por falta de volumen prostático"
    elif missing == ["psa"]:
        display = "no calculable por falta de PSA"
    else:
        display = "no calculable por falta de PSA y volumen prostático"

    return PsadContext(
        value=None,
        display=display,
        source="not_calculable",
        calculable=False,
        missing_inputs=missing,
    )


def derive_mri_context(payload: dict[str, Any]) -> MriContext:
    pirads = _parse_pirads(payload.get("pirads_score") or payload.get("mri_pirads_score"))
    mpmri_done = _yes_no_unknown(payload.get("mpmri_done", payload.get("mri_done")))
    quality = _text(payload.get("mpmri_quality")) or "No disponible"

    if pirads is not None:
        return MriContext(
            done=True,
            pirads=pirads,
            display=f"PI-RADS {pirads}",
            quality=quality if quality.lower() not in _UNAVAILABLE_VALUES else "No documentada",
            source="pirads_score",
        )

    if mpmri_done is False:
        return MriContext(
            done=False,
            pirads=None,
            display="no realizada o pendiente",
            quality="No disponible",
            source="mpmri_done",
        )

    if mpmri_done is True:
        return MriContext(
            done=True,
            pirads=None,
            display="realizada con PI-RADS no documentado",
            quality=quality if quality.lower() not in _UNAVAILABLE_VALUES else "No documentada",
            source="mpmri_done",
        )

    return MriContext(
        done=None,
        pirads=None,
        display="pendiente/no documentada",
        quality="No disponible",
        source="absent",
    )


def _extract_tstage(value: Any) -> str | None:
    text = _text(value)
    if not text or text.lower() in _UNAVAILABLE_VALUES or text.lower() == "normal":
        return None
    match = _TSTAGE_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(0).upper().lstrip("C")
    if raw == "T1":
        raw = "T1c"
    return f"cT{raw[1]}{raw[2:].lower()}"


def _parse_pirads(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    pirads = int(numeric)
    return pirads if pirads > 0 else None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = _text(value).replace(",", ".")
    if not text or text.lower() in _UNAVAILABLE_VALUES:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _first_positive_float(*values: Any) -> float | None:
    for value in values:
        numeric = _safe_float(value)
        if numeric is not None and numeric > 0:
            return numeric
    return None


def _yes_no_unknown(value: Any) -> bool | None:
    text = _text(value).lower()
    if text in _YES_VALUES:
        return True
    if text in _NO_VALUES:
        return False
    return None


def _is_truthy(value: Any) -> bool:
    return _text(value).lower() in _YES_VALUES


def _suggests_locally_advanced_dre(payload: dict[str, Any]) -> bool:
    fixation = _text(payload.get("dre_fixation")).lower()
    ece = _text(payload.get("dre_extracapsular_extension_clinical")).lower()
    consistency = _text(payload.get("dre_prostate_consistency")).lower()
    return (
        "fija" in fixation
        or ece in {"sospechosa", "definitiva"}
        or "pétrea" in consistency
        or "petrea" in consistency
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
