"""Validadores numéricos centralizados para entradas clínicas (EPIC 1 FAUBOT).

Cubre los hallazgos críticos:
    PSA-1    PSA actual/postop < 0 debe rechazarse.
    G-1      Gleason pattern fuera de [1..5] debe rechazarse.
    GT-1     Gleason total fuera de [6..10] debe rechazarse.
    PSADT-1  PSA doubling-time negativo no debe dispararalertas/BCR.
    C-3      positive_cores > total_cores_obtained debe rechazarse.
    Te-1     Testosterona negativa o > 3000 ng/dL debe rechazarse.
    S-1      SUVmax negativo debe rechazarse.

Las funciones devuelven (valor_normalizado, error | None). El error es una
cadena amigable lista para mostrar al clínico. None como valor señala “dato
no disponible”, compatible con el resto del pipeline (clinical_fact_resolver,
ddi_engine, halabi_nomogram, etc.).
"""

from __future__ import annotations

from typing import Any

from prostanet.shared.gleason_profile import (
    _GLEASON_PATTERN_MAX,
    _GLEASON_PATTERN_MIN,
    _GLEASON_SCORE_MAX,
    _GLEASON_SCORE_MIN,
    safe_int,
)
from prostanet.shared.ui_value_normalizer import clamp_numeric, normalize_numeric_locale

# Rangos clínicos canónicos (NCCN 5.2026, EAU 2026, literatura pivote).
PSA_MAX_NG_ML = 10000.0  # Valores > 10,000 ng/mL son implausibles incluso en bulky mCRPC.
PSADT_MIN_MONTHS = 0.1  # Valores < 0.1m dividen casi por cero en cálculos de riesgo.
PSADT_MAX_MONTHS = 240.0  # 20 años — cortejo de cáncer muy indolente.
TESTOSTERONE_MAX_NG_DL = 3000.0  # Techo fisiológico (incluye tumores productores de andrógenos).
TESTOSTERONE_CASTRATE_NG_DL = 50.0  # NCCN PROS-E2 definición de castración.
CORES_MAX = 40  # Biopsias sistemáticas + targeted rara vez exceden 40 cores.
SUVMAX_MAX = 200.0  # PSMA-PET SUV máximo reportado en literatura (cap conservador).
PSMA_LIVER_SUV_FLOOR = 1.0  # SUV hígado mínimo creíble.


def validate_psa_range(value: Any) -> tuple[float | None, str | None]:
    """Guard PSA-1: PSA ≥ 0, ≤ 10,000 ng/mL.

    Usa ``clamp_numeric`` para coma→punto y rechazo de negativos.
    """
    parsed, error = clamp_numeric(
        value,
        min_value=0.0,
        max_value=PSA_MAX_NG_ML,
        allow_negative=False,
    )
    return parsed, error


def validate_psadt(value: Any) -> tuple[float | None, str | None]:
    """Guard PSADT-1: PSA doubling-time debe ser positivo finito.

    Valores ≤0 indican PSA estable o decreciente; no deben consumirse como
    PSADT en motores de BCR/NCCN.
    """
    parsed, error = clamp_numeric(
        value,
        min_value=PSADT_MIN_MONTHS,
        max_value=PSADT_MAX_MONTHS,
        allow_negative=False,
    )
    if error:
        return parsed, error
    return parsed, None


def validate_testosterone_range(value: Any) -> tuple[float | None, str | None]:
    """Guard Te-1: testosterona total en ng/dL dentro de [0, 3000]."""
    return clamp_numeric(
        value,
        min_value=0.0,
        max_value=TESTOSTERONE_MAX_NG_DL,
        allow_negative=False,
    )


def validate_gleason_pattern(value: Any) -> tuple[int | None, str | None]:
    """Guard G-1: Gleason pattern debe ser entero en [1..5]."""
    if value in (None, "", "No aplica", "No documentado"):
        return None, None
    text = normalize_numeric_locale(value)
    parsed = safe_int(text)
    if parsed is None:
        return None, "Patrón de Gleason no numérico"
    if parsed < _GLEASON_PATTERN_MIN or parsed > _GLEASON_PATTERN_MAX:
        return (
            None,
            f"Patrón de Gleason fuera de rango ISUP "
            f"(permitido {_GLEASON_PATTERN_MIN}..{_GLEASON_PATTERN_MAX})",
        )
    return parsed, None


def validate_gleason_score(value: Any) -> tuple[int | None, str | None]:
    """Guard GT-1: Gleason total debe ser entero en [6..10]."""
    if value in (None, "", "No aplica", "No documentado"):
        return None, None
    text = normalize_numeric_locale(value)
    parsed = safe_int(text)
    if parsed is None:
        return None, "Gleason total no numérico"
    if parsed < _GLEASON_SCORE_MIN or parsed > _GLEASON_SCORE_MAX:
        return (
            None,
            f"Gleason total fuera de rango oncológico "
            f"(permitido {_GLEASON_SCORE_MIN}..{_GLEASON_SCORE_MAX})",
        )
    return parsed, None


def validate_cores_relationship(
    positive_cores: Any,
    total_cores_obtained: Any,
) -> tuple[tuple[int | None, int | None], str | None]:
    """Guard C-3: positive_cores ≤ total_cores_obtained, ambos en [0..40]."""
    if positive_cores in (None, "") and total_cores_obtained in (None, ""):
        return (None, None), None
    pos_parsed, pos_error = clamp_numeric(
        positive_cores,
        min_value=0,
        max_value=CORES_MAX,
        allow_negative=False,
    )
    total_parsed, total_error = clamp_numeric(
        total_cores_obtained,
        min_value=0,
        max_value=CORES_MAX,
        allow_negative=False,
    )
    pos = int(pos_parsed) if pos_parsed is not None else None
    total = int(total_parsed) if total_parsed is not None else None
    if pos_error:
        return (pos, total), f"Núcleos positivos: {pos_error}"
    if total_error:
        return (pos, total), f"Núcleos totales: {total_error}"
    if pos is not None and total is not None and pos > total:
        return (
            (pos, total),
            "Núcleos positivos no pueden exceder núcleos totales obtenidos",
        )
    return (pos, total), None


def validate_suvmax(value: Any) -> tuple[float | None, str | None]:
    """Guard S-1: SUVmax PSMA-PET debe ser no negativo ≤ 200."""
    return clamp_numeric(
        value,
        min_value=0.0,
        max_value=SUVMAX_MAX,
        allow_negative=False,
    )


def validate_vision_psma_ratio(
    lesion_suvmax: Any,
    liver_suvmean: Any,
) -> tuple[tuple[float | None, float | None], str | None]:
    """Helper para EPIC 3 — VISION/PSMAfore exige SUVmax lesión ≥ SUV hígado."""
    lesion, lesion_error = validate_suvmax(lesion_suvmax)
    liver, liver_error = clamp_numeric(
        liver_suvmean,
        min_value=PSMA_LIVER_SUV_FLOOR,
        max_value=SUVMAX_MAX,
        allow_negative=False,
    )
    if lesion_error:
        return (lesion, liver), f"SUVmax lesión: {lesion_error}"
    if liver_error:
        return (lesion, liver), f"SUV hígado: {liver_error}"
    if lesion is not None and liver is not None and lesion < liver:
        return (
            (lesion, liver),
            "Criterio VISION: SUVmax de lesión índice debe ser ≥ SUV medio hepático",
        )
    return (lesion, liver), None


__all__ = [
    "PSA_MAX_NG_ML",
    "PSADT_MAX_MONTHS",
    "PSADT_MIN_MONTHS",
    "TESTOSTERONE_CASTRATE_NG_DL",
    "TESTOSTERONE_MAX_NG_DL",
    "CORES_MAX",
    "SUVMAX_MAX",
    "validate_cores_relationship",
    "validate_gleason_pattern",
    "validate_gleason_score",
    "validate_psa_range",
    "validate_psadt",
    "validate_suvmax",
    "validate_testosterone_range",
    "validate_vision_psma_ratio",
]
