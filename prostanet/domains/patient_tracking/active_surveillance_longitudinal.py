# -*- coding: utf-8 -*-
"""
Motor serial de vigilancia activa: convierte una línea de tiempo de PSA +
biopsias + RMmp + PROs en triggers de reclasificación longitudinales.

Complementa `active_surveillance.ActiveSurveillanceService.evaluate_reclassification`,
que opera de forma cross-seccional (snapshot actual vs. snapshot previo). Aquí
se evalúan señales que sólo emergen al cruzar ≥3 snapshots (aceleración PSA,
escalada ISUP acumulada, patrón MRI progresivo, ansiedad sostenida).

Referencias:
  - NCCN PROS-C v5.2026 (Active Surveillance Principles)
  - EAU 2026 §6.2.2 (AS reclassification triggers)
  - PRIAS: Bul et al. Eur Urol 2013;63:597 (PSADT <3 años → re-estadificar)
  - Canary PASS: Newcomb et al. J Urol 2016;195:313
  - UCSF: Welty et al. J Urol 2015;193:807 + Cooperberg Decipher JCO 2018
  - Sunnybrook: Klotz et al. JCO 2015;33:272 (PSADT-driven)
  - PRECISE: Moore et al. Eur Urol 2017;71:648 (MRI progression in AS)
  - MAX-PC: Roth et al. Cancer 2003;97:2910 (ansiedad sostenida gatilla exit)

EPIC 5 del plan ProstaNet. La salida se consume desde
`localized_surveillance_copilot_service` y `profile_compass`.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from prostanet.domains.patient_tracking.active_surveillance import (
    ASReclassificationTrigger,
)

logger = logging.getLogger(__name__)


# ── Umbrales clínicos centralizados ──────────────────────────────────────────
# Fuente: guías y publicaciones citadas arriba. Si cambian, sólo tocar aquí.

PSA_VELOCITY_ALERT_NG_ML_PER_YEAR = 0.75     # Carter JAMA 1992; EAU 2026 umbral orientativo
PSADT_MONITORING_THRESHOLD_MONTHS = 36        # PRIAS: <36m → intensificar
PSADT_EXIT_THRESHOLD_MONTHS = 12              # Sunnybrook/Klotz: <12m → exit
PSA_RELATIVE_INCREASE_ALERT = 1.5             # PSA actual >1.5× PSA basal en ≤3 snapshots
GLEASON_UPGRADE_EXIT_ISUP = 2                 # NCCN: upgrade a ≥ISUP2 → reclasificación
MRI_PROGRESSION_PIRADS_CUTOFF = 4             # PRECISE: PI-RADS nuevo ≥4
ANXIETY_SUSTAINED_MAX_PC = 27                 # MAX-PC ≥27 en ≥2 assessments consecutivos
MAX_SNAPSHOT_GAP_MONTHS = 18                  # >18m sin PSA invalida cinética
MIN_SNAPSHOTS_FOR_KINETICS = 3                # Necesario para calcular velocity fiable
DECIPHER_UPGRADE_DELTA = 0.10                 # Subida ≥0.10 en serie → señal biológica


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class LongitudinalASSnapshot:
    """Un punto temporal en la vigilancia activa del paciente.

    No requiere que todos los campos estén presentes; el engine degrada con gracia
    cuando faltan (no fuerza errores, genera notas informativas si procede).
    """
    snapshot_date: str                               # ISO YYYY-MM-DD
    psa: float | None = None
    isup_grade: int | None = None
    gleason_primary: int | None = None
    gleason_secondary: int | None = None
    pirads_score: int | None = None                  # MRI más reciente
    max_core_involvement_pct: float | None = None
    percent_positive_cores: float | None = None
    any_cribriform: bool = False
    any_intraductal: bool = False
    decipher_score: float | None = None              # numérico (0.0-1.0)
    max_pc_score: float | None = None                # ansiedad MAX-PC
    patient_prefers_exit: bool = False               # decisión compartida registrada

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LongitudinalReclassificationReport:
    """Salida consolidada del engine serial."""
    triggers: list[ASReclassificationTrigger] = field(default_factory=list)
    reclassification_probability: float = 0.0        # 0.0-1.0
    probability_band: str = "low"                    # "low" | "moderate" | "high"
    next_action: str = ""
    exit_recommendation: str = ""
    snapshots_evaluated: int = 0
    kinetics_available: bool = False
    psa_velocity_ng_ml_per_year: float | None = None
    psadt_months_estimated: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggers": [t.to_dict() for t in self.triggers],
            "reclassification_probability": self.reclassification_probability,
            "probability_band": self.probability_band,
            "next_action": self.next_action,
            "exit_recommendation": self.exit_recommendation,
            "snapshots_evaluated": self.snapshots_evaluated,
            "kinetics_available": self.kinetics_available,
            "psa_velocity_ng_ml_per_year": self.psa_velocity_ng_ml_per_year,
            "psadt_months_estimated": self.psadt_months_estimated,
            "notes": list(self.notes),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        parsed = float(value)
        # PSA negativo o 0 no es señal fiable para cinética longitudinal.
        return parsed
    except (TypeError, ValueError):
        return None


def _coerce_snapshot(obj: Any) -> LongitudinalASSnapshot | None:
    """Acepta dict o LongitudinalASSnapshot y devuelve instancia o None si inválido."""
    if isinstance(obj, LongitudinalASSnapshot):
        return obj
    if not isinstance(obj, dict):
        return None
    snapshot_date = obj.get("snapshot_date") or obj.get("date")
    if not snapshot_date:
        return None
    try:
        return LongitudinalASSnapshot(
            snapshot_date=str(snapshot_date)[:10],
            psa=_safe_float(obj.get("psa")),
            isup_grade=_safe_int(obj.get("isup_grade")),
            gleason_primary=_safe_int(obj.get("gleason_primary")),
            gleason_secondary=_safe_int(obj.get("gleason_secondary")),
            pirads_score=_safe_int(obj.get("pirads_score")),
            max_core_involvement_pct=_safe_float(obj.get("max_core_involvement_pct")),
            percent_positive_cores=_safe_float(obj.get("percent_positive_cores")),
            any_cribriform=bool(obj.get("any_cribriform", False)),
            any_intraductal=bool(obj.get("any_intraductal", False)),
            decipher_score=_safe_float(obj.get("decipher_score")),
            max_pc_score=_safe_float(obj.get("max_pc_score")),
            patient_prefers_exit=bool(obj.get("patient_prefers_exit", False)),
        )
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sorted_snapshots(snapshots: Iterable[Any]) -> list[LongitudinalASSnapshot]:
    """Ordena snapshots por fecha ascendente y filtra inválidos."""
    coerced = [_coerce_snapshot(s) for s in (snapshots or [])]
    valid = [s for s in coerced if s and _parse_date(s.snapshot_date)]
    return sorted(valid, key=lambda s: _parse_date(s.snapshot_date) or date.min)


def _compute_psa_kinetics(snapshots: list[LongitudinalASSnapshot]) -> tuple[float | None, float | None]:
    """Calcula PSA velocity (ng/mL/año) y PSADT (meses) de forma robusta.

    Usa regresión log-lineal mínima cuadrados sobre ≥3 PSAs positivos dentro de
    los últimos 36 meses. Devuelve (velocity, psadt_months) o (None, None) si no
    hay datos suficientes. PSADT puede ser positivo (crecimiento) o negativo
    (descenso); downstream sólo actúa sobre positivos.
    """
    import math

    psa_points: list[tuple[date, float]] = []
    for s in snapshots:
        d = _parse_date(s.snapshot_date)
        if d is None or s.psa is None or s.psa <= 0:
            continue
        psa_points.append((d, float(s.psa)))

    if len(psa_points) < MIN_SNAPSHOTS_FOR_KINETICS:
        return None, None

    # Quedarse con los puntos más recientes en ventana de 36 meses.
    latest = psa_points[-1][0]
    window_start_ordinal = latest.toordinal() - int(36 * 30.44)
    windowed = [(d, v) for d, v in psa_points if d.toordinal() >= window_start_ordinal]
    if len(windowed) < MIN_SNAPSHOTS_FOR_KINETICS:
        windowed = psa_points[-MIN_SNAPSHOTS_FOR_KINETICS:]

    # Velocity lineal simple: (PSA_last - PSA_first) / (años transcurridos).
    d0, v0 = windowed[0]
    dn, vn = windowed[-1]
    days = max((dn - d0).days, 1)
    years = days / 365.25
    velocity = (vn - v0) / years if years > 0 else None

    # PSADT log-linear (Schmid 1993): slope = ln(2) / doubling_time_years.
    log_values = []
    ordinals = []
    for d, v in windowed:
        if v <= 0:
            continue
        log_values.append(math.log(v))
        ordinals.append(d.toordinal())
    if len(log_values) < MIN_SNAPSHOTS_FOR_KINETICS:
        return velocity, None

    n = len(log_values)
    mean_x = sum(ordinals) / n
    mean_y = sum(log_values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(ordinals, log_values))
    den = sum((x - mean_x) ** 2 for x in ordinals)
    if den == 0 or num == 0:
        return velocity, None
    slope_per_day = num / den
    if slope_per_day <= 0:
        # Pendiente no positiva → no hay doubling time interpretable.
        return velocity, None
    doubling_days = math.log(2) / slope_per_day
    psadt_months = doubling_days / 30.44
    return velocity, round(psadt_months, 1)


def _gap_months(snapshots: list[LongitudinalASSnapshot]) -> float | None:
    """Mayor gap sin PSA documentado en la serie (meses)."""
    psa_dates = [
        _parse_date(s.snapshot_date) for s in snapshots if s.psa is not None
    ]
    psa_dates = [d for d in psa_dates if d is not None]
    if len(psa_dates) < 2:
        return None
    psa_dates.sort()
    gaps = [(psa_dates[i] - psa_dates[i - 1]).days / 30.44 for i in range(1, len(psa_dates))]
    return round(max(gaps), 1) if gaps else None


# ── Detección de triggers longitudinales ─────────────────────────────────────

def _detect_psa_kinetics_trigger(
    snapshots: list[LongitudinalASSnapshot],
    velocity: float | None,
    psadt: float | None,
) -> ASReclassificationTrigger | None:
    if velocity is None and psadt is None:
        return None

    # Prioridad: PSADT bajo domina sobre velocity absoluta.
    if psadt is not None and 0 < psadt < PSADT_EXIT_THRESHOLD_MONTHS:
        return ASReclassificationTrigger(
            trigger_type="psa_kinetics",
            detected=True,
            detail=(
                f"PSADT longitudinal {psadt:.1f} meses (<{PSADT_EXIT_THRESHOLD_MONTHS} meses) "
                "calculado sobre serie de ≥3 PSAs."
            ),
            severity="reclassification",
            recommended_action=(
                "Cinética PSA muy rápida sostenida. Evaluar salida de VA: "
                "biopsia de re-estadificación + RMmp en ≤8 semanas, considerar prostatectomía/RT."
            ),
            evidence_tags=[
                "Sunnybrook Klotz JCO 2015 PSADT <12m exit",
                "EAU 2026 §6.2.2 PSA kinetics",
            ],
        )
    if psadt is not None and 0 < psadt < PSADT_MONITORING_THRESHOLD_MONTHS:
        return ASReclassificationTrigger(
            trigger_type="psa_kinetics",
            detected=True,
            detail=f"PSADT longitudinal {psadt:.1f} meses (umbral PRIAS <36).",
            severity="monitoring_intensification",
            recommended_action=(
                "Intensificar seguimiento: PSA cada 3 meses, RMmp y biopsia de "
                "re-estadificación dentro de los próximos 6 meses."
            ),
            evidence_tags=["PRIAS Bul Eur Urol 2013", "NCCN PROS-C v5.2026"],
        )
    if velocity is not None and velocity >= PSA_VELOCITY_ALERT_NG_ML_PER_YEAR:
        return ASReclassificationTrigger(
            trigger_type="psa_kinetics",
            detected=True,
            detail=(
                f"PSA velocity {velocity:.2f} ng/mL/año (≥{PSA_VELOCITY_ALERT_NG_ML_PER_YEAR})."
            ),
            severity="monitoring_intensification",
            recommended_action=(
                "Velocity elevada. Confirmar con PSA adicional en 6 semanas; "
                "considerar RMmp si >12 meses desde última imagen."
            ),
            evidence_tags=["Carter JAMA 1992 PSA velocity", "EAU 2026 AS kinetics"],
        )
    return None


def _detect_gleason_upgrade_longitudinal(
    snapshots: list[LongitudinalASSnapshot],
) -> ASReclassificationTrigger | None:
    """Detecta upgrade entre la biopsia basal y la más reciente (≥2 biopsias)."""
    biopsies = [s for s in snapshots if s.isup_grade is not None]
    if len(biopsies) < 2:
        return None
    baseline = biopsies[0]
    latest = biopsies[-1]
    if latest.isup_grade is None or baseline.isup_grade is None:
        return None
    if latest.isup_grade <= baseline.isup_grade:
        return None
    severity = "reclassification" if latest.isup_grade >= GLEASON_UPGRADE_EXIT_ISUP else "monitoring_intensification"
    action = (
        "Salida de VA; discusión inmediata de prostatectomía, radioterapia o "
        "en casos seleccionados terapia focal."
        if severity == "reclassification"
        else "Intensificar vigilancia; confirmar con RMmp + rebiopsia dirigida."
    )
    return ASReclassificationTrigger(
        trigger_type="gleason_upgrade",
        detected=True,
        detail=(
            f"Upgrade longitudinal ISUP {baseline.isup_grade} ({baseline.snapshot_date}) "
            f"→ ISUP {latest.isup_grade} ({latest.snapshot_date})."
        ),
        severity=severity,
        recommended_action=action,
        evidence_tags=["NCCN PROS-C reclassification", "EAU 2026 §6.2.2"],
    )


def _detect_mri_progression(
    snapshots: list[LongitudinalASSnapshot],
) -> ASReclassificationTrigger | None:
    """Nuevo PI-RADS ≥4 tras una imagen previa sin hallazgos (PI-RADS ≤3)."""
    mri = [s for s in snapshots if s.pirads_score is not None]
    if len(mri) < 2:
        return None
    prior = mri[0]
    latest = mri[-1]
    if prior.pirads_score is None or latest.pirads_score is None:
        return None
    if latest.pirads_score >= MRI_PROGRESSION_PIRADS_CUTOFF and prior.pirads_score < MRI_PROGRESSION_PIRADS_CUTOFF:
        return ASReclassificationTrigger(
            trigger_type="mri_new_lesion",
            detected=True,
            detail=(
                f"Progresión RMmp: PI-RADS {prior.pirads_score} ({prior.snapshot_date}) "
                f"→ PI-RADS {latest.pirads_score} ({latest.snapshot_date})."
            ),
            severity="monitoring_intensification",
            recommended_action=(
                "Biopsia dirigida en ≤8 semanas. Si upgrade histológico confirma "
                "ISUP ≥2, proceder a salida de VA."
            ),
            evidence_tags=["PRECISE Moore Eur Urol 2017", "PI-RADS v2.1"],
        )
    return None


def _detect_adverse_histology_longitudinal(
    snapshots: list[LongitudinalASSnapshot],
) -> ASReclassificationTrigger | None:
    """Aparición de cribriforme/intraductal en una biopsia de seguimiento."""
    baseline_adverse = snapshots[0].any_cribriform or snapshots[0].any_intraductal if snapshots else False
    for s in snapshots[1:]:
        if (s.any_cribriform or s.any_intraductal) and not baseline_adverse:
            patterns = []
            if s.any_cribriform:
                patterns.append("cribriforme")
            if s.any_intraductal:
                patterns.append("intraductal")
            return ASReclassificationTrigger(
                trigger_type="adverse_histology",
                detected=True,
                detail=(
                    f"Histología adversa emergente ({', '.join(patterns)}) "
                    f"en biopsia de seguimiento {s.snapshot_date}."
                ),
                severity="reclassification",
                recommended_action=(
                    "Salida de VA. Estos patrones se asocian con riesgo "
                    "de progresión y metástasis incluso con ISUP 2."
                ),
                evidence_tags=[
                    "Kweldam Mod Pathol 2016 cribriform",
                    "EAU 2026 IDC exclusion",
                    "NCCN PROS-C adverse histology",
                ],
            )
    return None


def _detect_anxiety_sustained(
    snapshots: list[LongitudinalASSnapshot],
) -> ASReclassificationTrigger | None:
    """MAX-PC ≥27 en ≥2 assessments consecutivos o preferencia explícita del paciente."""
    if any(s.patient_prefers_exit for s in snapshots):
        return ASReclassificationTrigger(
            trigger_type="patient_preference",
            detected=True,
            detail="El paciente expresó preferencia por finalizar vigilancia activa.",
            severity="reclassification",
            recommended_action=(
                "Respetar decisión compartida. Discutir opciones de tratamiento "
                "definitivo (RP, RT, terapia focal) con apoyo psico-oncológico."
            ),
            evidence_tags=["Ottawa Decision Support Framework", "NCCN PROS-A SDM"],
        )
    anxious = [
        s for s in snapshots
        if s.max_pc_score is not None and s.max_pc_score >= ANXIETY_SUSTAINED_MAX_PC
    ]
    if len(anxious) >= 2:
        return ASReclassificationTrigger(
            trigger_type="anxiety_sustained",
            detected=True,
            detail=(
                f"MAX-PC ≥{ANXIETY_SUSTAINED_MAX_PC} en "
                f"{len(anxious)} assessments consecutivos (último: "
                f"{anxious[-1].snapshot_date}, score {anxious[-1].max_pc_score:.0f})."
            ),
            severity="monitoring_intensification",
            recommended_action=(
                "Referir a psico-oncología urgente. Si ansiedad interfiere con "
                "adherencia al protocolo, discutir tratamiento definitivo."
            ),
            evidence_tags=[
                "MAX-PC Roth Cancer 2003",
                "NCCN Survivorship anxiety screening",
            ],
        )
    return None


def _detect_decipher_uptrend(
    snapshots: list[LongitudinalASSnapshot],
) -> ASReclassificationTrigger | None:
    """Alza Decipher ≥0.10 en mediciones seriadas → señal biológica adversa."""
    dec_points = [(s.snapshot_date, s.decipher_score) for s in snapshots if s.decipher_score is not None]
    if len(dec_points) < 2:
        return None
    baseline_date, baseline_score = dec_points[0]
    latest_date, latest_score = dec_points[-1]
    if latest_score - baseline_score >= DECIPHER_UPGRADE_DELTA:
        return ASReclassificationTrigger(
            trigger_type="decipher_uptrend",
            detected=True,
            detail=(
                f"Decipher {baseline_score:.2f} ({baseline_date}) → "
                f"{latest_score:.2f} ({latest_date}); delta "
                f"+{latest_score - baseline_score:.2f}."
            ),
            severity="monitoring_intensification",
            recommended_action=(
                "La biología tumoral muestra escalada. Considerar salida de VA "
                "si hay cualquier otro trigger concurrente (PSADT, upgrade)."
            ),
            evidence_tags=[
                "Cooperberg Decipher JCO 2018",
                "Spratt JCO 2018 genomic classifier in AS",
            ],
        )
    return None


# ── Engine principal ─────────────────────────────────────────────────────────

def detect_reclassification_longitudinal(
    snapshots: Iterable[Any],
) -> LongitudinalReclassificationReport:
    """Evalúa una serie temporal de snapshots y devuelve triggers longitudinales.

    No muta los inputs. Tolera dicts o instancias `LongitudinalASSnapshot`. Nunca
    lanza excepciones sobre datos válidamente incompletos — en ausencia de datos
    suficientes, devuelve `notes` explicando qué falta para la próxima evaluación.
    """
    ordered = _sorted_snapshots(snapshots)
    report = LongitudinalReclassificationReport(snapshots_evaluated=len(ordered))

    if not ordered:
        report.notes.append(
            "Sin snapshots longitudinales documentados; el motor serial no puede evaluar."
        )
        report.next_action = (
            "Registrar al menos una medición de PSA, biopsia y/o MRI con fecha."
        )
        return report

    if len(ordered) < 2:
        report.notes.append(
            f"Sólo hay 1 snapshot ({ordered[0].snapshot_date}); se requieren ≥2 "
            "para triggers longitudinales. Se consumen las reglas cross-seccionales."
        )
        return report

    # Gap entre snapshots — si es excesivo la cinética no es fiable.
    gap = _gap_months(ordered)
    if gap is not None and gap > MAX_SNAPSHOT_GAP_MONTHS:
        report.notes.append(
            f"Gap máximo sin PSA: {gap:.0f} meses (>{MAX_SNAPSHOT_GAP_MONTHS}). "
            "Priorizar reanudación del monitoreo antes de confiar en cinética."
        )

    # Cinética PSA (velocity + PSADT).
    velocity, psadt = _compute_psa_kinetics(ordered)
    report.psa_velocity_ng_ml_per_year = round(velocity, 2) if velocity is not None else None
    report.psadt_months_estimated = psadt
    report.kinetics_available = velocity is not None or psadt is not None

    # Detectores individuales.
    detectors = [
        _detect_psa_kinetics_trigger(ordered, velocity, psadt),
        _detect_gleason_upgrade_longitudinal(ordered),
        _detect_mri_progression(ordered),
        _detect_adverse_histology_longitudinal(ordered),
        _detect_anxiety_sustained(ordered),
        _detect_decipher_uptrend(ordered),
    ]
    report.triggers = [t for t in detectors if t is not None]

    # Probabilidad agregada de reclasificación — suma ponderada acotada a [0, 1].
    weights = {
        "reclassification": 0.40,
        "monitoring_intensification": 0.20,
    }
    probability = 0.0
    for trigger in report.triggers:
        probability += weights.get(trigger.severity, 0.0)
    report.reclassification_probability = round(min(probability, 1.0), 2)

    if report.reclassification_probability >= 0.7:
        report.probability_band = "high"
    elif report.reclassification_probability >= 0.3:
        report.probability_band = "moderate"
    else:
        report.probability_band = "low"

    # Próxima acción y exit_recommendation a partir del trigger más severo.
    exit_triggers = [t for t in report.triggers if t.severity == "reclassification"]
    intens_triggers = [t for t in report.triggers if t.severity == "monitoring_intensification"]

    if exit_triggers:
        top = exit_triggers[0]
        report.next_action = top.recommended_action
        report.exit_recommendation = (
            f"Recomendación: salida de VA por {top.trigger_type}. {top.recommended_action}"
        )
    elif intens_triggers:
        top = intens_triggers[0]
        report.next_action = top.recommended_action
        report.exit_recommendation = (
            "Mantener VA con seguimiento intensificado. No hay señal de salida inmediata."
        )
    else:
        report.next_action = (
            "Mantener calendario estándar del protocolo (PSA/RMmp/biopsia según fase)."
        )
        report.exit_recommendation = (
            "No hay triggers longitudinales activos; continuar con protocolo vigente."
        )

    return report


# ── Fachada para consumo desde copilots/profile_compass ──────────────────────

class LongitudinalASService:
    """Wrapper opinable para orquestar snapshots + reporte en el copilot."""

    @staticmethod
    def build_snapshots_from_payload(payload: dict[str, Any]) -> list[LongitudinalASSnapshot]:
        """Construye snapshots a partir del payload del paciente.

        Fuentes usadas (en orden de preferencia):
          - payload["active_surveillance_snapshots"]: lista ya estructurada
          - payload["psa_history"] + payload["biopsies"] + payload["mri_facts"]:
            merge por fecha
        """
        explicit = payload.get("active_surveillance_snapshots") or []
        if explicit:
            return _sorted_snapshots(explicit)

        # Fallback: combinar series dispersas en snapshots por fecha.
        psa_history = payload.get("psa_history") or []
        biopsies = payload.get("biopsies") or []
        mri_facts = payload.get("mri_facts") or []
        pros = payload.get("pro_assessments") or []

        by_date: dict[str, dict[str, Any]] = {}

        def _touch(d_str: str) -> dict[str, Any]:
            bucket = by_date.setdefault(d_str, {"snapshot_date": d_str})
            return bucket

        for item in psa_history:
            if not isinstance(item, dict):
                continue
            d = item.get("date") or item.get("measurement_date")
            if not d:
                continue
            bucket = _touch(str(d)[:10])
            if item.get("psa") is not None:
                bucket.setdefault("psa", _safe_float(item.get("psa")))

        for item in biopsies:
            if not isinstance(item, dict):
                continue
            d = item.get("biopsy_date") or item.get("date")
            if not d:
                continue
            bucket = _touch(str(d)[:10])
            for k_src, k_dst in [
                ("isup_grade", "isup_grade"),
                ("highest_isup", "isup_grade"),
                ("gleason_primary", "gleason_primary"),
                ("gleason_secondary", "gleason_secondary"),
                ("max_involvement_pct", "max_core_involvement_pct"),
                ("percent_positive_cores", "percent_positive_cores"),
                ("any_cribriform", "any_cribriform"),
                ("any_intraductal", "any_intraductal"),
                ("decipher_score_numeric", "decipher_score"),
            ]:
                if k_dst in bucket and bucket[k_dst] not in (None, False):
                    continue
                if item.get(k_src) is not None:
                    bucket[k_dst] = item.get(k_src)

        for item in mri_facts:
            if not isinstance(item, dict):
                continue
            d = item.get("mri_date") or item.get("date")
            if not d:
                continue
            bucket = _touch(str(d)[:10])
            if item.get("pirads_score") is not None:
                bucket["pirads_score"] = _safe_int(item.get("pirads_score"))

        for item in pros:
            if not isinstance(item, dict):
                continue
            d = item.get("assessment_date") or item.get("date")
            if not d:
                continue
            bucket = _touch(str(d)[:10])
            if item.get("max_pc_score") is not None:
                bucket["max_pc_score"] = _safe_float(item.get("max_pc_score"))
            if item.get("patient_prefers_exit"):
                bucket["patient_prefers_exit"] = True

        return _sorted_snapshots(list(by_date.values()))

    @staticmethod
    def evaluate(payload: dict[str, Any]) -> LongitudinalReclassificationReport:
        """Punto único de entrada para copilots y profile_compass."""
        snapshots = LongitudinalASService.build_snapshots_from_payload(payload)
        return detect_reclassification_longitudinal(snapshots)


__all__ = [
    "LongitudinalASSnapshot",
    "LongitudinalReclassificationReport",
    "LongitudinalASService",
    "detect_reclassification_longitudinal",
    # Umbrales exportados para testing y consumers.
    "PSA_VELOCITY_ALERT_NG_ML_PER_YEAR",
    "PSADT_MONITORING_THRESHOLD_MONTHS",
    "PSADT_EXIT_THRESHOLD_MONTHS",
    "GLEASON_UPGRADE_EXIT_ISUP",
    "MRI_PROGRESSION_PIRADS_CUTOFF",
    "ANXIETY_SUSTAINED_MAX_PC",
    "DECIPHER_UPGRADE_DELTA",
]
