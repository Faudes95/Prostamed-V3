"""Privacy + statistical suppression — EPIC 33.C

Cumple HIPAA §164.514 Safe Harbor: cohortes n<5 se suprimen para evitar
re-identificación. IC95% Wilson exact (robusto para n<30, mejor que
normal approximation).

Council concession (Critic): banner permanente "Cohorte exploratoria · NO
evidencia inferencial". Suprimir SIEMPRE y reportar suppression_rate al
clínico para que sepa el dataset es limitado.
"""
from __future__ import annotations

import math
from typing import Any

MIN_COHORT_N = 5  # HIPAA Safe Harbor threshold
DEFAULT_CONF_LEVEL = 0.95


def wilson_ci(successes: int, n: int, conf: float = DEFAULT_CONF_LEVEL) -> tuple[float, float]:
    """Wilson score interval (Wilson 1927). Robust for small n + extreme proportions.

    Returns (low, high) bounds in [0, 1]. Use for proportions / response rates.

    Reference: Brown LD, Cai TT, DasGupta A. Interval Estimation for a
    Binomial Proportion. Statistical Science. 2001;16(2):101-117.
    """
    if n <= 0:
        return (0.0, 0.0)
    if successes < 0 or successes > n:
        return (0.0, 0.0)
    # Z-score for 95% confidence
    z = 1.959963984540054 if abs(conf - 0.95) < 1e-6 else _z_score(conf)
    p_hat = successes / n
    denom = 1.0 + (z * z) / n
    center = (p_hat + (z * z) / (2 * n)) / denom
    half_width = (z * math.sqrt((p_hat * (1 - p_hat) + (z * z) / (4 * n)) / n)) / denom
    low = max(0.0, center - half_width)
    high = min(1.0, center + half_width)
    return (low, high)


def _z_score(conf: float) -> float:
    """Approximate inverse normal CDF for common conf levels."""
    mapping = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}
    return mapping.get(round(conf, 2), 1.9600)


def normal_ci_mean(values: list[float], conf: float = DEFAULT_CONF_LEVEL) -> dict[str, float | None]:
    """Mean + IC95% (normal approximation) for continuous variables.
    Returns {mean, sd, n, ci_low, ci_high, se}. None if n<2.
    """
    n = len(values)
    if n < 2:
        return {"mean": values[0] if n == 1 else None, "sd": None, "n": n,
                "ci_low": None, "ci_high": None, "se": None}
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    sd = math.sqrt(variance)
    se = sd / math.sqrt(n)
    z = _z_score(conf)
    return {
        "mean": round(mean, 3),
        "sd": round(sd, 3),
        "n": n,
        "ci_low": round(mean - z * se, 3),
        "ci_high": round(mean + z * se, 3),
        "se": round(se, 3),
    }


def suppress_if_below(
    count: int,
    threshold: int = MIN_COHORT_N,
    label: str = "",
) -> dict[str, Any]:
    """Returns suppression-aware display dict.

    Examples:
        suppress_if_below(3) → {'value': None, 'display': 'n<5 suprimido',
                                  'suppressed': True, 'n_raw': 3}
        suppress_if_below(12) → {'value': 12, 'display': '12', 'suppressed': False,
                                   'n_raw': 12}
    """
    if count < threshold:
        return {
            "value": None,
            "display": "n<5 suprimido",
            "suppressed": True,
            "n_raw": count,
            "threshold": threshold,
        }
    return {
        "value": count,
        "display": str(count) if not label else f"{count} {label}".strip(),
        "suppressed": False,
        "n_raw": count,
        "threshold": threshold,
    }


def proportion_with_ci(
    successes: int,
    n: int,
    *,
    suppress_below: int = MIN_COHORT_N,
) -> dict[str, Any]:
    """Returns proportion + IC95% Wilson + suppression-aware display.

    Returns: {p_hat, ci_low, ci_high, n, successes, suppressed, display}
    """
    if n < suppress_below:
        return {
            "p_hat": None,
            "ci_low": None,
            "ci_high": None,
            "n": n,
            "successes": successes,
            "suppressed": True,
            "display": f"n<{suppress_below} suprimido",
        }
    if n == 0:
        return {
            "p_hat": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0,
            "successes": 0, "suppressed": False, "display": "0/0",
        }
    p_hat = successes / n
    low, high = wilson_ci(successes, n)
    return {
        "p_hat": round(p_hat, 4),
        "ci_low": round(low, 4),
        "ci_high": round(high, 4),
        "n": n,
        "successes": successes,
        "suppressed": False,
        "display": f"{successes}/{n} ({100*p_hat:.1f}% IC95% {100*low:.1f}–{100*high:.1f}%)",
    }


__all__ = [
    "MIN_COHORT_N",
    "wilson_ci",
    "normal_ci_mean",
    "suppress_if_below",
    "proportion_with_ci",
]
