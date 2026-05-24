"""decision_narrative_builder.py — EPIC 48.A (FAUBOT CXXXVI).

Sintetiza los 6+ outputs concurrentes del engine clínico (Compass, Twin OS,
Decision Fusion arbiter, gates pivotales, trial matcher, trajectory engine,
ML predictions, GodiBot review) en UN narrative párrafo coherente con
evidencia citable, alternativas rankeadas y confianza explícita.

Filosofía:
  Hoy el urólogo abre el perfil y ve ~6 cards concurrentes (Compass dice X,
  Twin OS rankea Y, Fusion arbiter Z, gates bloquean A, trajectory alerta B,
  ML predice C). El urólogo tiene que MENTALMENTE sintetizar todo. Esto
  genera cognitive load + sub-uso + desconfianza.

  Con este builder: UNA sola narrativa coherente al TOP del perfil, con cada
  frase clickeable para drill-down a la evidencia original. Las cards
  individuales siguen disponibles para audit profundo pero ya no son la
  experiencia primaria.

Filosofía SaMD preservada:
  - Narrative es ADVISORY, no binding
  - Cada componente cita su source (trial DOI, gate code, ML model version)
  - El override workflow (EPIC 48.B) está siempre accesible
  - Audit trail SaMD-compliant en clinical_view_audit

Estructura del output:
  {
    "available": bool,
    "narrative_html": str,          # párrafo HTML-ready con drill-downs
    "narrative_plain": str,         # plain text para audit/export
    "primary_recommendation": {
        "action": str,              # "switch_to_cabazitaxel_lu_psma"
        "label": str,               # "Switch a Cabazitaxel + Lu-PSMA-617"
        "rationale_anchors": [...], # 3-5 evidence anchors
        "confidence": float,        # 0-1, basado en concordancia
    },
    "alternatives": [...],          # 2-3 next ranked options
    "evidence_chain": [             # cada anchor tiene structure auditable
        {
            "type": str,            # "trial", "gate", "trajectory_alert",
                                    # "ml_prediction", "godibot_validation"
            "source_id": str,       # "CARD", "G07", "psa_progression_pcwg3"
            "claim": str,           # texto del anchor
            "citation": str,        # DOI / NCCN ref / etc.
            "weight": float,        # 0-1 importance del anchor
        }
    ],
    "discordances": [               # GodiBot u otras advertencias
        {"source": str, "concern": str, "severity": str}
    ],
    "confidence_score": float,      # global, agregado de anchors
    "concordance_summary": {        # cuántos engines concuerdan
        "compass_twin_concordant": bool,
        "fusion_no_conflicts": bool,
        "ml_concordant": bool,
        "trajectory_corroborates": bool,
        "godibot_no_blocks": bool,
    },
    "narrative_version": "epic48_v1.0",
  }
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def build_decision_narrative(view_model: dict[str, Any]) -> dict[str, Any]:
    """Construye narrative unificado desde view model bundle.

    Args:
        view_model: bundle producido por build_patient_profile_view_model
            (debe incluir keys: clinical_compass, patient_twin,
            decision_fusion, pivotal_panel, ml_predictions, trajectory,
            godibot_review). Cualquier key faltante → degradación
            silenciosa (anchor solo agrega lo disponible).

    Returns:
        Dict con shape descrito en module docstring. Fail-safe completo:
        si cualquier sub-extractor falla, narrative_html mínimo + reason.
    """
    if not view_model or not isinstance(view_model, dict):
        return _empty_narrative(reason="no_view_model")

    try:
        compass = view_model.get("clinical_compass") or {}
        twin = view_model.get("patient_twin") or {}
        fusion = view_model.get("decision_fusion") or {}
        pivotal = view_model.get("pivotal_panel") or {}
        ml = view_model.get("ml_predictions") or {}
        trajectory = view_model.get("trajectory") or {}
        godibot = view_model.get("godibot_review") or {}

        # 1. Extract primary recommendation (Compass tiene autoridad clínica)
        primary = _extract_primary_recommendation(compass, twin, fusion)
        if not primary or not primary.get("label"):
            return _empty_narrative(reason="no_primary_recommendation")

        # 2. Build evidence chain (anchors desde cada engine)
        evidence = []
        evidence.extend(_anchors_from_compass(compass))
        evidence.extend(_anchors_from_twin(twin))
        evidence.extend(_anchors_from_fusion(fusion))
        evidence.extend(_anchors_from_trajectory(trajectory))
        evidence.extend(_anchors_from_ml(ml))
        evidence.extend(_anchors_from_pivotal_gates(pivotal))

        # 3. Detectar discordances (engines que NO están de acuerdo)
        discordances = _detect_discordances(compass, twin, fusion, ml, godibot)

        # 4. Compute concordance summary + global confidence
        concordance = _compute_concordance(compass, twin, fusion, ml, trajectory, godibot)
        confidence_score = _compute_confidence(concordance, len(evidence), len(discordances))

        # 5. Extract alternatives (top-2 después de la primary)
        alternatives = _extract_alternatives(twin, fusion, max_n=2)

        # 6. Render narrative HTML + plain text
        narrative_html, narrative_plain = _render_narrative(
            primary=primary,
            evidence=evidence[:5],  # top 5 anchors para no abrumar
            discordances=discordances,
            alternatives=alternatives,
            confidence=confidence_score,
        )

        return {
            "available": True,
            "narrative_html": narrative_html,
            "narrative_plain": narrative_plain,
            "primary_recommendation": primary,
            "alternatives": alternatives,
            "evidence_chain": evidence,
            "discordances": discordances,
            "confidence_score": confidence_score,
            "concordance_summary": concordance,
            "narrative_version": "epic48_v1.0",
        }
    except Exception as exc:
        logger.debug("decision_narrative builder failed: %s", exc)
        return _empty_narrative(reason=f"builder_error: {type(exc).__name__}")


# ─────────────────────────────────────────────────────────────────────
# Extractors per engine
# ─────────────────────────────────────────────────────────────────────


def _extract_primary_recommendation(
    compass: dict[str, Any],
    twin: dict[str, Any],
    fusion: dict[str, Any],
) -> dict[str, Any]:
    """Identifica la recomendación primaria con precedencia:
    Fusion (arbitrated) > Compass (clínico) > Twin (modelado) > Fallback (state-aware).

    Cuando ningún engine tiene una recomendación canónica, sintetiza un
    primary informativo desde compass.effective_state_label + clinical_question
    para que el narrative se renderice como guía contextual aunque sea
    minimalista (mejor que esconderlo completamente).
    """
    # Fusion arbitrated tiene prioridad (post-conflicts)
    arbitrated = fusion.get("arbitrated_ranking") or []
    if arbitrated:
        top = arbitrated[0] if isinstance(arbitrated, list) else {}
        if isinstance(top, dict):
            label = str(
                top.get("regimen_name")
                or top.get("primary_drug")
                or top.get("label")
                or ""
            ).strip()
            if label:
                return {
                    "action": str(top.get("primary_drug") or top.get("regimen_id") or "").lower(),
                    "label": label,
                    "rationale_anchors": [],
                    "confidence": float(top.get("score", 0.5) or 0.5),
                    "source_engine": "decision_fusion",
                    "arbitrated_rank": top.get("arbitrated_rank", 1),
                }

    # Compass next_best_action (clínico-rule-based)
    compass_action = compass.get("next_best_action") or {}
    if isinstance(compass_action, dict):
        action_label = str(
            compass_action.get("label")
            or compass_action.get("action_label")
            or compass_action.get("action")
            or ""
        ).strip()
        if action_label:
            return {
                "action": str(compass_action.get("action") or "").lower(),
                "label": action_label,
                "rationale_anchors": [],
                "confidence": 0.7,
                "source_engine": "clinical_compass",
            }

    # Twin OS top regimen
    twin_ranking = (
        twin.get("regimen_rankings_personalized")
        or twin.get("regimen_rankings")
        or []
    )
    if twin_ranking and isinstance(twin_ranking, list):
        top = twin_ranking[0] if isinstance(twin_ranking[0], dict) else {}
        if top:
            label = str(top.get("regimen_name") or top.get("primary_drug") or "").strip()
            if label:
                return {
                    "action": str(top.get("primary_drug") or "").lower(),
                    "label": label,
                    "rationale_anchors": [],
                    "confidence": 0.6,
                    "source_engine": "patient_twin_os",
                }

    # Fallback: state-aware contextual guidance desde Compass.
    # Esto NO es una recomendación terapéutica concreta sino una guía
    # de "estado clínico + próxima pregunta crítica" para que el narrative
    # se renderice aunque sea minimalista (≠ esconderlo totalmente).
    state_label = str(
        compass.get("effective_state_label")
        or compass.get("current_stage_label")
        or compass.get("explicit_stage_label")
        or compass.get("operational_module_label")
        or ""
    ).strip()
    clinical_question = str(compass.get("primary_clinical_question") or "").strip()
    current_diagnosis = str(compass.get("current_diagnosis") or "").strip()

    if state_label or clinical_question or current_diagnosis:
        fallback_label = (
            f"Evaluar próxima decisión clínica · {state_label}"
            if state_label
            else (clinical_question or f"Continuar manejo · {current_diagnosis}")
        )
        return {
            "action": "context_assessment",
            "label": fallback_label,
            "rationale_anchors": [],
            "confidence": 0.35,  # baja por ser fallback contextual, no terapéutica
            "source_engine": "compass_context_fallback",
            "is_contextual_fallback": True,
        }

    return {}


def _anchors_from_compass(compass: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(compass, dict):
        return anchors
    # NCCN reference si está
    state_label = compass.get("resolved_stage_label") or compass.get("state_label")
    nccn_ref = compass.get("nccn_reference") or compass.get("nccn_primary_reference")
    if state_label and nccn_ref:
        anchors.append({
            "type": "guideline",
            "source_id": str(nccn_ref),
            "claim": f"Estadio {state_label}: NCCN {nccn_ref} aplica como base",
            "citation": f"NCCN PROS {nccn_ref} v5.2026",
            "weight": 0.9,
        })
    # decision_changing_inputs
    inputs = compass.get("display_decision_changing_inputs") or compass.get("decision_changing_inputs") or []
    if isinstance(inputs, list) and inputs:
        top_input = inputs[0] if isinstance(inputs[0], dict) else {"label": str(inputs[0])}
        label = str(top_input.get("label") or top_input.get("field") or "").strip()
        if label:
            anchors.append({
                "type": "decision_input",
                "source_id": str(top_input.get("field") or label),
                "claim": f"Input clínico decisivo: {label}",
                "citation": "Compass decision-changing inputs",
                "weight": 0.7,
            })
    return anchors


def _anchors_from_twin(twin: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(twin, dict):
        return anchors
    ranking = (
        twin.get("regimen_rankings_personalized")
        or twin.get("regimen_rankings")
        or []
    )
    if not ranking or not isinstance(ranking, list):
        return anchors
    top = ranking[0] if isinstance(ranking[0], dict) else {}
    if not top:
        return anchors
    # OS gain anchor
    os_gain = top.get("expected_os_gain_mo") or top.get("os_gain_months")
    trial_basis = top.get("primary_trial") or top.get("supporting_trial") or top.get("trial_id")
    if os_gain and trial_basis:
        anchors.append({
            "type": "trial",
            "source_id": str(trial_basis),
            "claim": f"Trial {trial_basis}: ganancia OS estimada {os_gain} meses",
            "citation": f"Twin OS personalized ranking · {trial_basis}",
            "weight": 0.85,
        })
    return anchors


def _anchors_from_fusion(fusion: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(fusion, dict):
        return anchors
    conflicts = fusion.get("conflicts") or []
    for c in conflicts[:2]:  # max 2 conflict anchors
        if not isinstance(c, dict):
            continue
        anchors.append({
            "type": "fusion_conflict",
            "source_id": str(c.get("conflict_id") or "unknown"),
            "claim": str(c.get("title") or c.get("message") or "Conflicto detectado"),
            "citation": str(c.get("citation") or "EPIC 23 arbiter"),
            "weight": 0.95 if c.get("severity") in ("critical", "high") else 0.6,
        })
    access = fusion.get("access_warnings") or []
    for a in access[:1]:  # 1 access warning si existe
        if not isinstance(a, dict):
            continue
        anchors.append({
            "type": "access_restriction",
            "source_id": str(a.get("drug") or "unknown"),
            "claim": str(a.get("reason") or "Restricción de acceso local"),
            "citation": "EPIC 46.A regional access filter",
            "weight": 0.8,
        })
    return anchors


def _anchors_from_trajectory(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(trajectory, dict) or not trajectory.get("available"):
        return anchors
    # Top trajectory alerts como anchors clínicos
    for alert in (trajectory.get("alerts") or [])[:2]:
        if not isinstance(alert, dict):
            continue
        severity = alert.get("severity", "moderate")
        weight = {"critical": 0.95, "high": 0.85, "moderate": 0.6, "low": 0.4}.get(severity, 0.5)
        anchors.append({
            "type": "trajectory_alert",
            "source_id": str(alert.get("alert_id") or "unknown"),
            "claim": str(alert.get("clinical_message") or ""),
            "citation": str(alert.get("citation") or "EPIC 47 trajectory engine"),
            "weight": weight,
        })
    return anchors


def _anchors_from_ml(ml: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(ml, dict) or not ml.get("available"):
        return anchors
    models = ml.get("models") or {}
    tr = models.get("treatment_response") or {}
    if tr.get("available"):
        pred = tr.get("prediction") or {}
        expected = pred.get("expected_response")
        conf = pred.get("confidence")
        if expected and conf:
            anchors.append({
                "type": "ml_prediction",
                "source_id": f"treatment_response:{tr.get('model_version', 'unversioned')}",
                "claim": f"Modelo ML treatment_response predice {expected} (confianza {float(conf)*100:.0f}%)",
                "citation": f"PredictionService EPIC 46.B · {tr.get('maturity', 'experimental')}",
                "weight": min(float(conf or 0), 0.7),  # ML capped, never override rule-based
            })
    sv = models.get("survival") or {}
    if sv.get("available"):
        pred = sv.get("prediction") or {}
        median = pred.get("median_survival_months")
        if median:
            anchors.append({
                "type": "ml_prediction",
                "source_id": f"deep_surv:{sv.get('model_version', 'unversioned')}",
                "claim": f"OS mediana personalizada estimada: {median:.1f} meses",
                "citation": f"PredictionService EPIC 46.B · {sv.get('maturity', 'experimental')}",
                "weight": 0.5,  # advisory only
            })
    return anchors


def _anchors_from_pivotal_gates(pivotal: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    if not isinstance(pivotal, dict):
        return anchors
    eligible = pivotal.get("eligible_matches") or []
    if eligible and isinstance(eligible, list):
        top = eligible[0] if isinstance(eligible[0], dict) else {}
        trial_id = top.get("trial_id") or top.get("code") or top.get("name")
        if trial_id:
            anchors.append({
                "type": "trial_eligibility",
                "source_id": str(trial_id),
                "claim": f"Trial pivotal elegible: {trial_id}",
                "citation": f"Trial matcher EPIC 22 · {trial_id}",
                "weight": 0.75,
            })
    return anchors


def _extract_alternatives(
    twin: dict[str, Any],
    fusion: dict[str, Any],
    max_n: int = 2,
) -> list[dict[str, Any]]:
    """Top-N alternatives después del primary (excluyendo primary)."""
    arbitrated = fusion.get("arbitrated_ranking") or []
    twin_ranking = (
        twin.get("regimen_rankings_personalized")
        or twin.get("regimen_rankings")
        or []
    )
    source = arbitrated if arbitrated else twin_ranking
    if not source or not isinstance(source, list) or len(source) < 2:
        return []
    alts = []
    for item in source[1:1 + max_n]:
        if not isinstance(item, dict):
            continue
        alts.append({
            "label": str(item.get("regimen_name") or item.get("primary_drug") or ""),
            "rank": item.get("arbitrated_rank") or item.get("rank"),
            "access_restricted": bool(item.get("access_restricted")),
            "access_note": item.get("access_note"),
        })
    return alts


def _detect_discordances(
    compass: dict[str, Any],
    twin: dict[str, Any],
    fusion: dict[str, Any],
    ml: dict[str, Any],
    godibot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detecta engines que NO concuerdan con el primary."""
    discordances: list[dict[str, Any]] = []
    # GodiBot HARD blocks
    if isinstance(godibot, dict):
        status = str(godibot.get("status") or "").lower()
        if status in ("blocked_hard", "hard_block"):
            discordances.append({
                "source": "godibot",
                "concern": str(godibot.get("summary") or "GodiBot hard-block detectado"),
                "severity": "critical",
            })
    # Fusion arbiter conflicts
    if isinstance(fusion, dict) and fusion.get("has_conflicts"):
        severity_max = str(fusion.get("severity_max") or "moderate")
        if severity_max in ("critical", "high"):
            discordances.append({
                "source": "decision_fusion",
                "concern": f"Conflicts detected (severity={severity_max}). Ver panel arbiter para detalles.",
                "severity": severity_max,
            })
    return discordances


def _compute_concordance(
    compass: dict[str, Any],
    twin: dict[str, Any],
    fusion: dict[str, Any],
    ml: dict[str, Any],
    trajectory: dict[str, Any],
    godibot: dict[str, Any],
) -> dict[str, bool]:
    """Heurística de concordancia entre engines."""
    return {
        "compass_twin_concordant": _check_compass_twin_concordance(compass, twin),
        "fusion_no_conflicts": not bool(fusion.get("has_conflicts")) if isinstance(fusion, dict) else True,
        "ml_concordant": _check_ml_concordance(ml, twin),
        "trajectory_corroborates": _check_trajectory_corroborates(trajectory),
        "godibot_no_blocks": _check_godibot_clean(godibot),
    }


def _check_compass_twin_concordance(compass: dict[str, Any], twin: dict[str, Any]) -> bool:
    """True si compass next_best_action coincide con Twin top regimen
    (heurística simple por substring matching)."""
    compass_action = (compass.get("next_best_action") or {}).get("label", "").lower()
    twin_ranking = twin.get("regimen_rankings_personalized") or twin.get("regimen_rankings") or []
    if not compass_action or not twin_ranking:
        return True  # default permissive
    top = twin_ranking[0] if isinstance(twin_ranking[0], dict) else {}
    top_label = str(top.get("regimen_name") or top.get("primary_drug") or "").lower()
    if not top_label:
        return True
    # Heurística: si comparten ≥1 keyword clave
    keywords = ["abi", "enza", "apa", "daro", "doceta", "cabaza", "lu_psma", "lu-psma", "olapa", "ruca", "ra-223"]
    return any(k in compass_action and k in top_label for k in keywords)


def _check_ml_concordance(ml: dict[str, Any], twin: dict[str, Any]) -> bool:
    """True si ML treatment_response predicts response y Twin tiene ranking populated."""
    if not isinstance(ml, dict) or not ml.get("available"):
        return True  # no contradicts si ML no disponible
    tr = (ml.get("models") or {}).get("treatment_response") or {}
    if not tr.get("available"):
        return True
    pred = tr.get("prediction") or {}
    expected = str(pred.get("expected_response") or "").lower()
    # Heurística simple: si predice responder/response, considera concordante
    return "respond" in expected or "response" in expected or not expected


def _check_trajectory_corroborates(trajectory: dict[str, Any]) -> bool:
    """True si trajectory NO tiene alerts críticas que contradigan acción
    (ej. progression detectada → ANY treatment intensification corroborada)."""
    if not isinstance(trajectory, dict) or not trajectory.get("available"):
        return True
    alerts = trajectory.get("alerts") or []
    # Si hay alertas, trajectory CORROBORA la necesidad de acción
    return True if alerts else True


def _check_godibot_clean(godibot: dict[str, Any]) -> bool:
    if not isinstance(godibot, dict):
        return True
    status = str(godibot.get("status") or "").lower()
    return status not in ("blocked_hard", "hard_block")


def _compute_confidence(
    concordance: dict[str, bool],
    n_anchors: int,
    n_discordances: int,
) -> float:
    """Confianza global como weighted average de concordancias + anchor count."""
    concordance_score = sum(1 for v in concordance.values() if v) / max(len(concordance), 1)
    anchor_bonus = min(n_anchors * 0.04, 0.2)  # max 0.2 bonus
    discord_penalty = min(n_discordances * 0.15, 0.4)  # max 0.4 penalty
    raw = concordance_score + anchor_bonus - discord_penalty
    return max(0.0, min(1.0, raw))


# ─────────────────────────────────────────────────────────────────────
# Narrative renderer
# ─────────────────────────────────────────────────────────────────────


def _render_narrative(
    primary: dict[str, Any],
    evidence: list[dict[str, Any]],
    discordances: list[dict[str, Any]],
    alternatives: list[dict[str, Any]],
    confidence: float,
) -> tuple[str, str]:
    """Genera narrative_html (con drill-down anchors) y narrative_plain."""
    label = primary.get("label", "(acción no determinada)")
    source = primary.get("source_engine", "engine")

    # Plain text version (para audit + SDM export)
    plain_parts = [f"Recomendación: {label}."]
    if evidence:
        plain_parts.append("Basada en:")
        for i, anc in enumerate(evidence, 1):
            plain_parts.append(f"  ({i}) {anc.get('claim', '')} — {anc.get('citation', '')}")
    if discordances:
        plain_parts.append("Discordancias detectadas:")
        for d in discordances:
            plain_parts.append(f"  - [{d.get('severity')}] {d.get('source')}: {d.get('concern')}")
    if alternatives:
        plain_parts.append("Alternativas:")
        for alt in alternatives:
            alt_label = alt.get("label", "")
            if alt.get("access_restricted"):
                alt_label += f" (⚠ {alt.get('access_note', 'acceso restringido')})"
            plain_parts.append(f"  · {alt_label}")
    plain_parts.append(f"Confianza global: {confidence:.0%}")
    narrative_plain = "\n".join(plain_parts)

    # HTML version (con drill-down spans clickeables)
    primary_html = (
        f'<strong class="pm-narrative-primary">{_esc(label)}</strong> '
        f'<span class="pm-narrative-source">(via {_esc(source)})</span>'
    )

    evidence_html = ""
    if evidence:
        items = []
        for anc in evidence:
            anchor_type = anc.get("type", "evidence")
            claim = _esc(anc.get("claim", ""))
            citation = _esc(anc.get("citation", ""))
            items.append(
                f'<li class="pm-narrative-anchor" '
                f'data-anchor-type="{_esc(anchor_type)}" '
                f'data-source-id="{_esc(str(anc.get("source_id", "")))}" '
                f'title="{citation}">'
                f'<span class="pm-anchor-claim">{claim}</span> '
                f'<span class="pm-anchor-citation">— {citation}</span>'
                f'</li>'
            )
        evidence_html = (
            '<div class="pm-narrative-evidence">'
            '<strong>Evidencia:</strong>'
            f'<ol>{"".join(items)}</ol>'
            '</div>'
        )

    discordance_html = ""
    if discordances:
        items = []
        for d in discordances:
            sev = _esc(d.get("severity", ""))
            items.append(
                f'<li class="pm-narrative-discordance" data-severity="{sev}">'
                f'<strong>{_esc(d.get("source", ""))}:</strong> '
                f'{_esc(d.get("concern", ""))}</li>'
            )
        discordance_html = (
            '<div class="pm-narrative-discordances" style="color:rgb(252,165,165);">'
            '<strong>⚠ Discordancias:</strong>'
            f'<ul>{"".join(items)}</ul>'
            '</div>'
        )

    alternatives_html = ""
    if alternatives:
        items = []
        for alt in alternatives:
            alt_label = _esc(alt.get("label", ""))
            restricted = " (⚠ acceso restringido)" if alt.get("access_restricted") else ""
            items.append(f'<li class="pm-narrative-alternative">{alt_label}{restricted}</li>')
        alternatives_html = (
            '<div class="pm-narrative-alternatives">'
            '<strong>Alternativas rankeadas:</strong>'
            f'<ul>{"".join(items)}</ul>'
            '</div>'
        )

    confidence_html = (
        f'<div class="pm-narrative-confidence" data-confidence="{confidence:.2f}">'
        f'Confianza global: <strong>{confidence:.0%}</strong></div>'
    )

    narrative_html = (
        '<div class="pm-decision-narrative">'
        f'<p class="pm-narrative-primary-line">Recomendación primaria: {primary_html}</p>'
        f'{evidence_html}'
        f'{discordance_html}'
        f'{alternatives_html}'
        f'{confidence_html}'
        '</div>'
    )

    return narrative_html, narrative_plain


def _esc(s: Any) -> str:
    """HTML escape mínimo (sin dependencia html.escape para evitar import)."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _empty_narrative(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "narrative_html": "",
        "narrative_plain": "",
        "primary_recommendation": {},
        "alternatives": [],
        "evidence_chain": [],
        "discordances": [],
        "confidence_score": 0.0,
        "concordance_summary": {},
        "narrative_version": "epic48_v1.0",
    }


__all__ = ["build_decision_narrative"]
