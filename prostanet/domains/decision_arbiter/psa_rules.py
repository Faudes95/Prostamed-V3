"""Centralized PSA-related clinical decision rules — EPIC 32.F (Explore EXP-16).

Pre-EPIC32 las reglas PSA estaban dispersas en múltiples módulos:
- `clinical_contradiction_engine.py` — PCWG3 rising check
- `phoenix.py` — Phoenix BCR threshold
- `psa_line_monitor.py` — per-line kinetics classification
- `arpi_benefit_matrix.py` — PSADT max gates
- `post_rp_salvage_copilot_service.py` — BCR 2-PSA window
- Individual gate YAMLs en `pivotal_gates_catalog/`

Este módulo centraliza las reglas con evidencia PCWG3 + AUA-ASTRO 2024 + EAU 2026
para que arbiter, copilots, classifier y forecast usen UNA sola fuente de verdad.

Backward compat: módulos legacy siguen funcionando; estas helpers son nuevos
entry points unificados que pueden adoptarse incrementalmente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


# ────────────────────────────── Constants ──────────────────────────────

# PCWG3 Scher JCO 2016 PMID 26921877
PCWG3_MIN_RISE_PCT = 0.25
PCWG3_MIN_RISE_ABS_NG_ML = 2.0
PCWG3_CONFIRMATORY_WINDOW_DAYS = 21

# AUA-ASTRO 2024 + EAU 2026 §5.2 — BCR post-RP
BCR_POST_RP_PSA_THRESHOLD = 0.2
BCR_CONFIRMATORY_MIN_DAYS = 21
BCR_CONFIRMATORY_MAX_DAYS = 180  # EPIC 29.8 G54

# Phoenix RTOG-ASTRO 2006 — BCR post-RT
PHOENIX_DELTA_NG_ML = 2.0

# m0_crpc PSADT gate — SPARTAN/PROSPER/ARAMIS
M0_CRPC_PSADT_MAX_MONTHS = 10.0

# Stale data thresholds
PSA_STALE_DAYS_DEFAULT = 90
TESTOSTERONE_STALE_DAYS_DEFAULT = 90


# ────────────────────────────── Result classes ──────────────────────────────

@dataclass(frozen=True)
class PsaRuleResult:
    """Result of a PSA-related rule evaluation."""
    passed: bool
    rule_id: str
    rationale: str
    evidence: str = ""
    severity: str = "info"  # info / warning / blocking
    metadata: dict[str, Any] | None = None


# ────────────────────────────── Helpers ──────────────────────────────

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _sorted_psa_history(psa_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort PSA history rows by date ascending; filter invalid entries."""
    cleaned = []
    for p in psa_history or []:
        if not isinstance(p, dict):
            continue
        d = _parse_iso(p.get("date") or p.get("sample_date"))
        v = _safe_float(p.get("value") or p.get("psa_value") or p.get("psa"))
        if d and v is not None and v >= 0:
            cleaned.append({"date": d, "value": v, "_raw": p})
    cleaned.sort(key=lambda x: x["date"])
    return cleaned


# ────────────────────────────── Rules ──────────────────────────────

def evaluate_pcwg3_rising(psa_history: list[dict[str, Any]]) -> PsaRuleResult:
    """PCWG3 Scher JCO 2016 — PSA rising criterion.

    Requires:
    1. Identify nadir = min(psa_history values)
    2. Rise from nadir ≥25% AND ≥2 ng/mL absolute
    3. Confirmatory: 2 PSAs above threshold separated ≥21 días
    """
    rows = _sorted_psa_history(psa_history)
    if len(rows) < 2:
        return PsaRuleResult(
            passed=False, rule_id="pcwg3_rising",
            rationale="Insuficientes mediciones PSA (<2) para evaluar PCWG3.",
            severity="info",
        )
    values = [r["value"] for r in rows]
    nadir = min(values)
    if nadir <= 0:
        return PsaRuleResult(
            passed=False, rule_id="pcwg3_rising",
            rationale="Nadir PSA ≤ 0, PCWG3 no aplicable (probable error de medición).",
            severity="warning",
        )
    threshold = max(nadir * (1 + PCWG3_MIN_RISE_PCT), nadir + PCWG3_MIN_RISE_ABS_NG_ML)
    candidate_rows = [r for r in rows if r["value"] >= threshold]
    if not candidate_rows:
        return PsaRuleResult(
            passed=False, rule_id="pcwg3_rising",
            rationale=(
                f"PSA actual no alcanza umbral PCWG3 (≥{threshold:.2f} ng/mL desde "
                f"nadir {nadir:.2f}). Mantener vigilancia."
            ),
            evidence="Scher JCO 2016 (PMID 26921877)",
            severity="info",
            metadata={"nadir": nadir, "threshold": threshold},
        )
    if len(candidate_rows) < 2:
        return PsaRuleResult(
            passed=False, rule_id="pcwg3_rising",
            rationale=(
                f"Single-spike PSA ≥{threshold:.2f} ng/mL detectado pero SIN "
                f"confirmación. PCWG3 requiere 2 PSAs separadas ≥{PCWG3_CONFIRMATORY_WINDOW_DAYS}d."
            ),
            evidence="Scher JCO 2016 (PMID 26921877)",
            severity="warning",
            metadata={
                "nadir": nadir, "threshold": threshold,
                "candidate_count": 1, "pcwg3_pending_confirmation": True,
            },
        )
    # ≥2 candidates: verify ≥21d separation
    for i, cand in enumerate(candidate_rows):
        for later in candidate_rows[i + 1:]:
            if (later["date"] - cand["date"]).days >= PCWG3_CONFIRMATORY_WINDOW_DAYS:
                return PsaRuleResult(
                    passed=True, rule_id="pcwg3_rising",
                    rationale=(
                        f"PCWG3 progresión bioquímica confirmada: {cand['value']:.2f} "
                        f"({cand['date'].isoformat()}) y {later['value']:.2f} "
                        f"({later['date'].isoformat()}) ambos ≥{threshold:.2f}, "
                        f"separados {(later['date'] - cand['date']).days}d."
                    ),
                    evidence="Scher JCO 2016 (PMID 26921877)",
                    severity="blocking",
                    metadata={
                        "nadir": nadir, "threshold": threshold,
                        "confirmed_dates": [cand['date'].isoformat(), later['date'].isoformat()],
                    },
                )
    return PsaRuleResult(
        passed=False, rule_id="pcwg3_rising",
        rationale=(
            f"{len(candidate_rows)} PSAs ≥{threshold:.2f} pero ninguna pareja "
            f"separada ≥{PCWG3_CONFIRMATORY_WINDOW_DAYS}d. Esperar confirmación."
        ),
        evidence="Scher JCO 2016 (PMID 26921877)",
        severity="warning",
        metadata={"nadir": nadir, "threshold": threshold,
                  "candidate_count": len(candidate_rows),
                  "pcwg3_pending_confirmation": True},
    )


def evaluate_bcr_post_rp(psa_history: list[dict[str, Any]]) -> PsaRuleResult:
    """AUA-ASTRO 2024 + EAU 2026 §5.2 — BCR detection post-prostatectomy.

    2 PSAs ≥0.2 ng/mL separated 21-180 días (EPIC 29.8 G54: upper bound).
    """
    rows = _sorted_psa_history(psa_history)
    elevated = [r for r in rows if r["value"] >= BCR_POST_RP_PSA_THRESHOLD]
    if len(elevated) < 2:
        return PsaRuleResult(
            passed=False, rule_id="bcr_post_rp_confirmation",
            rationale=(
                f"Insuficientes PSAs ≥{BCR_POST_RP_PSA_THRESHOLD} ng/mL "
                f"({len(elevated)} encontradas; se requieren 2)."
            ),
            severity="info",
            metadata={"elevated_count": len(elevated)},
        )
    # Iterar en orden DESC (más reciente primero) para encontrar 2 PSAs
    # confirmatorias dentro de ventana 21-180d
    elevated_desc = sorted(elevated, key=lambda x: x["date"], reverse=True)
    for i, recent in enumerate(elevated_desc):
        for earlier in elevated_desc[i + 1:]:
            gap = (recent["date"] - earlier["date"]).days
            if BCR_CONFIRMATORY_MIN_DAYS <= gap <= BCR_CONFIRMATORY_MAX_DAYS:
                return PsaRuleResult(
                    passed=True, rule_id="bcr_post_rp_confirmation",
                    rationale=(
                        f"BCR confirmada: PSAs {recent['value']:.2f} ({recent['date']}) "
                        f"y {earlier['value']:.2f} ({earlier['date']}) ambos "
                        f"≥{BCR_POST_RP_PSA_THRESHOLD}, separadas {gap}d."
                    ),
                    evidence="AUA-ASTRO 2024 + EAU 2026 §5.2",
                    severity="blocking",
                    metadata={"confirmed_dates": [earlier['date'].isoformat(),
                                                    recent['date'].isoformat()]},
                )
            if gap > BCR_CONFIRMATORY_MAX_DAYS:
                # Persistently elevated > 6mo → trayectoria distinta
                return PsaRuleResult(
                    passed=False, rule_id="bcr_post_rp_confirmation",
                    rationale=(
                        f"2 PSAs ≥{BCR_POST_RP_PSA_THRESHOLD} pero gap {gap}d > {BCR_CONFIRMATORY_MAX_DAYS}d. "
                        f"Sugiere persistencia bioquímica de larga data, no nuevo "
                        f"episodio BCR. Recapturar PSA reciente para confirmar."
                    ),
                    evidence="EPIC 29.8 G54 + AUA-ASTRO 2024",
                    severity="warning",
                    metadata={"gap_days": gap, "max_window_days": BCR_CONFIRMATORY_MAX_DAYS,
                              "recommended_action": "obtain_recent_psa_within_window"},
                )
    return PsaRuleResult(
        passed=False, rule_id="bcr_post_rp_confirmation",
        rationale="PSAs ≥0.2 detectadas pero no en ventana confirmatoria 21-180d.",
        severity="info",
    )


def evaluate_phoenix_bcr_post_rt(
    nadir_psa: float | None,
    current_psa: float | None,
    state_context: str = "",
) -> PsaRuleResult:
    """Phoenix RTOG-ASTRO 2006 — BCR post-RT.

    Cumplido si current_psa ≥ nadir_psa + 2.0 ng/mL.
    Para contexto, ver `prostanet.shared.phoenix.evaluate_phoenix` que añade
    rationale context-aware (post-RT vs CRPC, EPIC 31.F EXP-11).
    """
    if nadir_psa is None or current_psa is None:
        return PsaRuleResult(
            passed=False, rule_id="phoenix_bcr_post_rt",
            rationale="Sin nadir o PSA actual disponible — Phoenix no evaluable.",
            severity="info",
        )
    threshold = nadir_psa + PHOENIX_DELTA_NG_ML
    if current_psa >= threshold:
        return PsaRuleResult(
            passed=True, rule_id="phoenix_bcr_post_rt",
            rationale=(
                f"Phoenix cumplido: PSA {current_psa:.2f} ≥ nadir {nadir_psa:.2f} + 2.0 "
                f"(threshold {threshold:.2f})."
            ),
            evidence="Roach M et al. IJROBP 2006 (Phoenix consensus)",
            severity="blocking",
            metadata={"threshold": threshold, "delta": current_psa - nadir_psa},
        )
    return PsaRuleResult(
        passed=False, rule_id="phoenix_bcr_post_rt",
        rationale=f"PSA {current_psa:.2f} < threshold Phoenix ({threshold:.2f}).",
        severity="info",
        metadata={"threshold": threshold, "delta": current_psa - nadir_psa},
    )


def evaluate_psadt_aggressive(psadt_months: float | None) -> PsaRuleResult:
    """PSADT ≤10 meses = enfermedad agresiva (SPARTAN/PROSPER/ARAMIS criterion)."""
    if psadt_months is None:
        return PsaRuleResult(
            passed=False, rule_id="psadt_aggressive",
            rationale="PSADT no calculable — capturar ≥2 PSAs adicionales.",
            severity="info",
        )
    if psadt_months <= M0_CRPC_PSADT_MAX_MONTHS:
        return PsaRuleResult(
            passed=True, rule_id="psadt_aggressive",
            rationale=(
                f"PSADT {psadt_months:.1f}mo ≤ {M0_CRPC_PSADT_MAX_MONTHS}mo. "
                f"Cinética agresiva — elegible ARPI nmCRPC."
            ),
            evidence="SPARTAN (29420164) / PROSPER (29949494) / ARAMIS (30763142)",
            severity="warning",
            metadata={"psadt_months": psadt_months,
                      "threshold": M0_CRPC_PSADT_MAX_MONTHS},
        )
    return PsaRuleResult(
        passed=False, rule_id="psadt_aggressive",
        rationale=(
            f"PSADT {psadt_months:.1f}mo > {M0_CRPC_PSADT_MAX_MONTHS}mo. "
            f"Cinética indolente — beneficio ARPI nmCRPC no demostrado en trials."
        ),
        evidence="SPARTAN/PROSPER/ARAMIS inclusion criterion",
        severity="info",
        metadata={"psadt_months": psadt_months,
                  "threshold": M0_CRPC_PSADT_MAX_MONTHS},
    )


def evaluate_psa_staleness(
    last_psa_date: Any,
    max_age_days: int = PSA_STALE_DAYS_DEFAULT,
) -> PsaRuleResult:
    """¿Está stale la última PSA (>max_age_days)?"""
    d = _parse_iso(last_psa_date)
    if d is None:
        return PsaRuleResult(
            passed=False, rule_id="psa_staleness",
            rationale="Sin fecha de última PSA documentada (treated as stale).",
            severity="warning",
        )
    age = (date.today() - d).days
    if age > max_age_days:
        return PsaRuleResult(
            passed=False, rule_id="psa_staleness",
            rationale=(
                f"Última PSA hace {age} días (>{max_age_days}d threshold). "
                f"Recapturar antes de tomar decisión terapéutica."
            ),
            severity="warning",
            metadata={"age_days": age, "threshold_days": max_age_days},
        )
    return PsaRuleResult(
        passed=True, rule_id="psa_staleness",
        rationale=f"PSA fresca ({age}d desde última medición).",
        severity="info",
        metadata={"age_days": age},
    )


# ────────────────────────────── Convenience aggregator ──────────────────────────────

def evaluate_all_psa_rules(
    *,
    psa_history: list[dict[str, Any]],
    state_context: str = "",
    nadir_psa: float | None = None,
    current_psa: float | None = None,
    psadt_months: float | None = None,
    last_psa_date: Any = None,
) -> dict[str, PsaRuleResult]:
    """Evaluate all relevant PSA rules in one call.

    Returns dict keyed by rule_id with PsaRuleResult values. Caller can
    inspect specific rules or iterate over `.passed`/`.severity` for
    aggregate decision logic.
    """
    results: dict[str, PsaRuleResult] = {}
    results["pcwg3_rising"] = evaluate_pcwg3_rising(psa_history)
    results["bcr_post_rp_confirmation"] = evaluate_bcr_post_rp(psa_history)
    if nadir_psa is not None and current_psa is not None:
        results["phoenix_bcr_post_rt"] = evaluate_phoenix_bcr_post_rt(
            nadir_psa, current_psa, state_context
        )
    if psadt_months is not None:
        results["psadt_aggressive"] = evaluate_psadt_aggressive(psadt_months)
    if last_psa_date is not None:
        results["psa_staleness"] = evaluate_psa_staleness(last_psa_date)
    return results


__all__ = [
    "PsaRuleResult",
    "evaluate_pcwg3_rising",
    "evaluate_bcr_post_rp",
    "evaluate_phoenix_bcr_post_rt",
    "evaluate_psadt_aggressive",
    "evaluate_psa_staleness",
    "evaluate_all_psa_rules",
    "PCWG3_MIN_RISE_PCT",
    "PCWG3_MIN_RISE_ABS_NG_ML",
    "PCWG3_CONFIRMATORY_WINDOW_DAYS",
    "BCR_POST_RP_PSA_THRESHOLD",
    "BCR_CONFIRMATORY_MIN_DAYS",
    "BCR_CONFIRMATORY_MAX_DAYS",
    "PHOENIX_DELTA_NG_ML",
    "M0_CRPC_PSADT_MAX_MONTHS",
    "PSA_STALE_DAYS_DEFAULT",
    "TESTOSTERONE_STALE_DAYS_DEFAULT",
]
