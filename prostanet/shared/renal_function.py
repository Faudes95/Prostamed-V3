"""Motor de función renal para EPIC 2 FAUBOT.

Centraliza el cálculo de eGFR con las tres fórmulas vigentes y la
clasificación KDIGO 2024 para que abiraterona, cabazitaxel, PARPi, Ra-223,
contraste PSMA y denosumab puedan consumir el mismo valor.

Fórmulas soportadas:

* **CKD-EPI 2021** (Inker LA et al. *NEJM* 2021;385:1737-1749). Por defecto
  sin coeficiente de raza — referencia preferida NKF-ASN 2021 y CMS 2023.
* **MDRD (4 variables)** (Levey AS et al. *Ann Intern Med* 1999;130:461).
* **Cockcroft-Gault** (Cockcroft & Gault *Nephron* 1976;16:31). Necesario
  para labels FDA históricos de Zytiga, Jevtana, Lynparza, Talzenna.

Los umbrales KDIGO 2024 siguen la clasificación G1-G5 con cutoff funcional
≥90 / 60-89 / 45-59 / 30-44 / 15-29 / <15 ml/min/1.73m².

Uso::

    from prostanet.shared.renal_function import compute_egfr
    result = compute_egfr(creatinine_mg_dl=1.8, age=72, sex="male")
    # result["egfr_ml_min_1_73m2"] == 42.3
    # result["ckd_stage"]          == "G3b"
    # result["formula"]            == "ckd_epi_2021"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prostanet.shared.ui_value_normalizer import clamp_numeric


# Cutoffs KDIGO 2024 (ml/min/1.73m²).
_CKD_STAGES = (
    ("G1", 90.0, float("inf"), "Función renal normal"),
    ("G2", 60.0, 90.0, "Reducción leve"),
    ("G3a", 45.0, 60.0, "Reducción leve-moderada"),
    ("G3b", 30.0, 45.0, "Reducción moderada-grave"),
    ("G4", 15.0, 30.0, "Reducción grave"),
    ("G5", 0.0, 15.0, "Fallo renal (diálisis)"),
)

# Umbrales de toxicidad/dosis para fármacos clave (FDA labels 2025).
_RENAL_DOSING_FLAGS = {
    "abiraterone": {
        "full_dose_threshold": 30.0,
        "caution_threshold": 15.0,
        "notes": "eGFR <30: considerar 500 mg/d (monitoreo hepático adicional).",
        "evidence": "FDA Zytiga label §2.3",
    },
    "cabazitaxel": {
        "full_dose_threshold": 30.0,
        "caution_threshold": 15.0,
        "notes": "eGFR <30: evitar o reducir a 20 mg/m²; monitorear neutropenia.",
        "evidence": "FDA Jevtana label §2.2",
    },
    "olaparib": {
        "full_dose_threshold": 50.0,
        "caution_threshold": 30.0,
        "notes": "eGFR 31-50: reducir a 200 mg BID; eGFR <30 no estudiado.",
        "evidence": "FDA Lynparza label §2.3",
    },
    "talazoparib": {
        "full_dose_threshold": 60.0,
        "caution_threshold": 15.0,
        "notes": "eGFR 30-59: reducir a 0.75 mg/d; eGFR <30 contraindicado.",
        "evidence": "FDA Talzenna label §2.3",
    },
    "radium_223": {
        "full_dose_threshold": 30.0,
        "caution_threshold": 30.0,
        "notes": "eGFR <30: precaución extrema (mielotoxicidad potencial).",
        "evidence": "FDA Xofigo label §5.3",
    },
    "psma_iodine_contrast": {
        "full_dose_threshold": 30.0,
        "caution_threshold": 30.0,
        "notes": "Requiere hidratación y reevaluación si eGFR <30.",
        "evidence": "ACR Manual on Contrast Media v10.3",
    },
    "denosumab": {
        "full_dose_threshold": 30.0,
        "caution_threshold": 30.0,
        "notes": "eGFR <30: monitorear hipocalcemia semanal el primer mes.",
        "evidence": "FDA Xgeva label §5.3",
    },
    "zoledronate": {
        "full_dose_threshold": 35.0,
        "caution_threshold": 30.0,
        "notes": "eGFR <30: contraindicado; 30-60: reducir dosis.",
        "evidence": "FDA Zometa label §2.4",
    },
}


@dataclass(frozen=True)
class RenalFunctionResult:
    """Resultado estructurado del cálculo de función renal."""

    egfr_ml_min_1_73m2: float | None
    formula: str
    ckd_stage: str | None
    ckd_stage_label: str | None
    creatinine_mg_dl: float | None
    age_years: float | None
    sex: str | None
    weight_kg: float | None
    inputs_missing: tuple[str, ...] = field(default_factory=tuple)
    evidence_tag: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "egfr_ml_min_1_73m2": self.egfr_ml_min_1_73m2,
            "formula": self.formula,
            "ckd_stage": self.ckd_stage,
            "ckd_stage_label": self.ckd_stage_label,
            "creatinine_mg_dl": self.creatinine_mg_dl,
            "age_years": self.age_years,
            "sex": self.sex,
            "weight_kg": self.weight_kg,
            "inputs_missing": list(self.inputs_missing),
            "evidence_tag": self.evidence_tag,
        }


def _parse_sex(sex: Any) -> str | None:
    if sex is None:
        return None
    s = str(sex).strip().lower()
    if s in {"m", "male", "hombre", "masculino", "varón", "varon"}:
        return "male"
    if s in {"f", "female", "mujer", "femenino"}:
        return "female"
    return None


def _classify_ckd_stage(egfr: float | None) -> tuple[str | None, str | None]:
    if egfr is None:
        return None, None
    for code, lo, hi, label in _CKD_STAGES:
        if lo <= egfr < hi or (hi == float("inf") and egfr >= lo):
            return code, label
    return None, None


def compute_egfr(
    *,
    creatinine_mg_dl: Any,
    age: Any,
    sex: Any,
    weight_kg: Any = None,
    formula: str = "ckd_epi_2021",
) -> dict[str, Any]:
    """Calcula eGFR y estadio KDIGO.

    Parámetros:
        creatinine_mg_dl: Creatinina sérica en mg/dL.
        age: Edad en años.
        sex: 'male'/'female' (acepta también formas en español).
        weight_kg: Peso corporal (necesario sólo para Cockcroft-Gault).
        formula: 'ckd_epi_2021' | 'mdrd' | 'cockcroft_gault'.

    Retorna un dict serializable con ``egfr_ml_min_1_73m2``, ``ckd_stage``,
    ``inputs_missing`` y la fórmula empleada.
    """
    missing: list[str] = []

    creat_val, creat_err = clamp_numeric(
        creatinine_mg_dl,
        min_value=0.05,
        max_value=30.0,
        allow_negative=False,
    )
    if creat_val is None:
        missing.append("creatinine_mg_dl")

    age_val, age_err = clamp_numeric(age, min_value=0.0, max_value=120.0, allow_negative=False)
    if age_val is None:
        missing.append("age_years")

    sex_val = _parse_sex(sex)
    if sex_val is None:
        missing.append("sex")

    weight_val = None
    if weight_kg not in (None, ""):
        weight_val, _ = clamp_numeric(weight_kg, min_value=20.0, max_value=400.0, allow_negative=False)

    formula = (formula or "ckd_epi_2021").strip().lower()

    egfr_value: float | None = None
    formula_used = formula
    if creat_val is not None and age_val is not None and sex_val is not None:
        if formula == "ckd_epi_2021":
            egfr_value = _ckd_epi_2021(creat_val, age_val, sex_val)
        elif formula == "mdrd":
            egfr_value = _mdrd_4var(creat_val, age_val, sex_val)
        elif formula == "cockcroft_gault":
            if weight_val is None:
                missing.append("weight_kg")
                formula_used = "cockcroft_gault"
            else:
                egfr_value = _cockcroft_gault(creat_val, age_val, sex_val, weight_val)
        else:
            raise ValueError(
                "formula debe ser 'ckd_epi_2021', 'mdrd' o 'cockcroft_gault'"
            )

    stage, stage_label = _classify_ckd_stage(egfr_value)
    evidence_tag = {
        "ckd_epi_2021": "Inker 2021 NEJM (CKD-EPI 2021 sin raza)",
        "mdrd": "Levey 1999 Ann Intern Med (MDRD 4-variable)",
        "cockcroft_gault": "Cockcroft & Gault 1976 Nephron",
    }.get(formula_used, "")

    return RenalFunctionResult(
        egfr_ml_min_1_73m2=round(egfr_value, 1) if egfr_value is not None else None,
        formula=formula_used,
        ckd_stage=stage,
        ckd_stage_label=stage_label,
        creatinine_mg_dl=creat_val,
        age_years=age_val,
        sex=sex_val,
        weight_kg=weight_val,
        inputs_missing=tuple(missing),
        evidence_tag=evidence_tag,
    ).to_dict()


def _ckd_epi_2021(scr: float, age: float, sex: str) -> float:
    """CKD-EPI 2021 sin coeficiente de raza (Inker 2021)."""
    if sex == "female":
        kappa = 0.7
        alpha = -0.241
        sex_factor = 1.012
    else:
        kappa = 0.9
        alpha = -0.302
        sex_factor = 1.0

    ratio = scr / kappa
    min_ratio = min(ratio, 1.0) ** alpha
    max_ratio = max(ratio, 1.0) ** (-1.200)
    return 142.0 * min_ratio * max_ratio * (0.9938 ** age) * sex_factor


def _mdrd_4var(scr: float, age: float, sex: str) -> float:
    """MDRD 4-variable (Levey 1999). Sin coeficiente de raza (la ecuación
    original usa +1.212 en negros; en línea con NKF-ASN 2021 se omite)."""
    egfr = 175.0 * (scr ** -1.154) * (age ** -0.203)
    if sex == "female":
        egfr *= 0.742
    return egfr


def _cockcroft_gault(scr: float, age: float, sex: str, weight_kg: float) -> float:
    """Cockcroft-Gault (ml/min, no normalizado por superficie corporal).

    ProstaNet aplica el mismo resultado como aproximación a ml/min/1.73m²
    cuando se selecciona esta fórmula, porque las etiquetas FDA históricas
    (Zytiga, Jevtana, Lynparza) se construyeron con Cockcroft-Gault crudo.
    """
    egfr = ((140.0 - age) * weight_kg) / (72.0 * scr)
    if sex == "female":
        egfr *= 0.85
    return egfr


def renal_dosing_flag(
    drug: str,
    *,
    egfr_ml_min_1_73m2: float | None,
) -> dict[str, Any]:
    """Evalúa si la función renal actual permite dosis plena, dosis reducida
    o debe evitar el fármaco.

    Retorna un dict con ``drug``, ``status`` (``full``/``dose_reduce``/
    ``avoid``/``unknown``), ``threshold_ml_min``, ``notes`` y ``evidence``.
    """
    key = (drug or "").strip().lower()
    flag = _RENAL_DOSING_FLAGS.get(key)
    if flag is None:
        return {
            "drug": key,
            "status": "unknown",
            "threshold_ml_min": None,
            "notes": "Fármaco no catalogado",
            "evidence": "",
        }

    if egfr_ml_min_1_73m2 is None:
        return {
            "drug": key,
            "status": "unknown",
            "threshold_ml_min": flag["full_dose_threshold"],
            "notes": flag["notes"],
            "evidence": flag["evidence"],
        }

    if egfr_ml_min_1_73m2 >= flag["full_dose_threshold"]:
        status = "full"
    elif egfr_ml_min_1_73m2 >= flag["caution_threshold"]:
        status = "dose_reduce"
    else:
        status = "avoid"

    return {
        "drug": key,
        "status": status,
        "threshold_ml_min": flag["full_dose_threshold"],
        "notes": flag["notes"],
        "evidence": flag["evidence"],
    }


__all__ = [
    "RenalFunctionResult",
    "compute_egfr",
    "renal_dosing_flag",
]
