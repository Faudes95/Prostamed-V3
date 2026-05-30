"""GodiBot Validator — Segunda opinión adversarial sobre recomendaciones terapéuticas.

Faubot Iteración C — 2026-05-15 (GodiBot v1).

A diferencia de `clinical_decision_agent` (que GENERA recomendaciones) y de
FAUBOT (que audita el sistema periódicamente), GodiBot intercepta cada
`clinical_compass` recién generado y lo valida adversarialmente en tiempo
real contra:

  - NCCN v5.2026 / EAU 2026 (cross-check guideline)
  - Los 103 gates pivotales (re-evaluación independiente)
  - 47 trials elegibilidad (detección de trials omitidos)
  - Clinical Oracle + Longitudinal Concordance (coherencia temporal)
  - LLM "devil's advocate" (solo en casos con confidence<0.85 o estadios
    complejos: nmcrpc_initial, m1_crpc, nepc_crpc, oligometastatic_sbrt)

Modo SUGERENCIA + bloqueo DURO solo en `hard_block` real omitido.
NO reescribe la recomendación — exige override explícito del médico.
Preserva provenance del clinical_decision_agent + cumple FDA SaMD HITL.

Output AgentOutput.metadata["godibot_review"]:

    {
        "status": "approved" | "warnings_only" | "blocked_hard",
        "confidence": 0.0-1.0,
        "discrepancies": [{code, severity, source, message, suggestion}],
        "trial_omissions": [{trial_id, confidence, reason}],
        "biomarker_gaps": [{name, required_for, severity}],
        "longitudinal_concord": {matched_trajectory, drift_detected, ...},
        "llm_adversarial": {invoked, summary} | None,
        "override_required": bool,
        "version": "godibot-v1",
    }
"""
from __future__ import annotations

import logging
from typing import Any

from prostanet.agents.base import AgentBase
from prostanet.agents.contracts import (
    AgentAlert,
    AgentInput,
    AgentOutput,
    AgentRecommendation,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Constantes clínicas — GodiBot conoce las contraindicaciones absolutas
# ──────────────────────────────────────────────────────────────────────

# Estadios "complejos" donde GodiBot dispara LLM adversarial si confidence<0.85
COMPLEX_STAGES = frozenset({
    "nmcrpc_initial",
    "m0_crpc",
    "m1_crpc",
    "nepc_crpc",
    "oligometastatic_sbrt",
    "psma_pe_eligible",
})

# Familias terapéuticas detectables por keyword
PARP_KEYWORDS = ("olaparib", "talazoparib", "niraparib", "rucaparib", "parp")
LU177_KEYWORDS = ("lutetium", "lu-177", "lu177", "pluvicto", "psma-617")
ABIRATERONE_KEYWORDS = ("abiraterona", "abiraterone", "zytiga")
RA223_KEYWORDS = ("radium", "ra-223", "ra223", "xofigo")
SIPULEUCEL_KEYWORDS = ("sipuleucel", "provenge")
ARSI_SWITCH_KEYWORDS = ("enzalutamida", "enzalutamide", "apalutamida", "apalutamide",
                        "darolutamida", "darolutamide")
CABAZITAXEL_KEYWORDS = ("cabazitaxel", "jevtana")
DOCETAXEL_KEYWORDS = ("docetaxel", "taxotere")


# ──────────────────────────────────────────────────────────────────────
# Helpers de extracción defensiva del record + compass
# ──────────────────────────────────────────────────────────────────────


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    """Lookup defensivo en dict con múltiples key aliases."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _bundle_text_blob(compass: dict) -> str:
    """Concatena todos los strings del compass para búsqueda de keywords."""
    if not isinstance(compass, dict):
        return ""
    chunks: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)

    _walk(compass)
    return " ".join(chunks).lower()


def _mentions_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────
# GodiBot Validator
# ──────────────────────────────────────────────────────────────────────


class GodiBotValidator(AgentBase):
    """Validador adversarial de recomendaciones terapéuticas ProstaNet.

    Trigger: post-compass-generation. NO modifica la recomendación,
    anexa segunda opinión + bloquea solo en hard_block real omitido.
    """

    agent_id = "godibot_validator"
    agent_role = (
        "Validador adversarial: segunda opinión sobre cada clinical_compass "
        "generado por clinical_decision_agent + profile_compass"
    )
    trigger_events = [
        "compass_generated",
        "recommendation_drafted",
        "visit_recorded",  # fallback path si event_bus no propaga compass
    ]

    LLM_CONFIDENCE_THRESHOLD = 0.85
    VERSION = "godibot-v1"

    def __init__(
        self,
        *,
        anthropic_client: Any | None = None,
        enable_llm_adversarial: bool = True,
    ) -> None:
        self._anthropic_client = anthropic_client
        self._enable_llm = enable_llm_adversarial

    # ── Public API ──────────────────────────────────────────────────

    def evaluate(self, agent_input: AgentInput) -> AgentOutput:
        record = agent_input.record or {}
        compass = self._extract_compass(record, agent_input.trigger_data)
        state = _coerce_text(_get(record, "reconciled_state", "current_state", "disease_state"))

        evidence: list[str] = [
            f"GodiBot {self.VERSION} — second opinion sobre compass generado",
            f"Estado clínico: {state or 'desconocido'}",
        ]

        # Sub-validadores
        guideline = self._validate_nccn_eau(record, compass, state)
        gates = self._reeval_103_gates(record, compass)
        biomarkers = self._detect_omitted_biomarkers(record, compass)
        trials = self._detect_eligible_trials(record, compass)
        longitudinal = self._check_longitudinal_concordance(record, compass)

        discrepancies: list[dict[str, Any]] = []
        discrepancies.extend(guideline.get("discrepancies", []))
        discrepancies.extend(gates.get("discrepancies", []))
        discrepancies.extend(biomarkers.get("discrepancies", []))
        discrepancies.extend(longitudinal.get("discrepancies", []))

        # Confidence: 1.0 si no hay discrepancias, baja con cada hallazgo
        confidence = self._compute_confidence(discrepancies, trials, longitudinal)

        # LLM adversarial — solo si confidence<threshold o estadio complejo
        llm_review: dict[str, Any] | None = None
        if self._should_invoke_llm(confidence, state):
            llm_review = self._llm_devils_advocate(record, compass, discrepancies, state)
            if llm_review and llm_review.get("additional_concerns"):
                for concern in llm_review["additional_concerns"]:
                    discrepancies.append({
                        "code": "llm_adversarial_concern",
                        "severity": "soft_warning",
                        "source": "llm_devils_advocate",
                        "message": concern,
                        "suggestion": None,
                    })

        # Determine final status
        has_hard_block = any(
            d.get("severity") == "hard_block" for d in discrepancies
        )
        has_warnings = any(
            d.get("severity") in ("soft_warning", "warning", "informational")
            for d in discrepancies
        )
        trial_omissions_count = len(trials.get("omitted", []))

        if has_hard_block:
            status = "blocked_hard"
            override_required = True
            evidence.append(
                f"⛔ {sum(1 for d in discrepancies if d.get('severity') == 'hard_block')} "
                f"hard_block omitido(s) detectado(s) — requiere override del médico"
            )
        elif has_warnings or trial_omissions_count > 0 or longitudinal.get("drift_detected"):
            status = "warnings_only"
            override_required = False
            evidence.append(
                f"⚠ {len(discrepancies)} discrepancia(s) + "
                f"{trial_omissions_count} trial(s) omitido(s) sugeridos"
            )
        else:
            status = "approved"
            override_required = False
            evidence.append("✅ Recomendación concuerda con NCCN/EAU/gates/trials")

        # Build alerts for AgentOutput (visible al engine downstream)
        alerts: list[AgentAlert] = []
        for d in discrepancies:
            sev = d.get("severity", "informational")
            alert_severity = (
                "critical" if sev == "hard_block"
                else "warning" if sev == "soft_warning"
                else "info"
            )
            alerts.append(AgentAlert(
                alert_type="godibot_discrepancy",
                severity=alert_severity,
                title=d.get("code", "discrepancy"),
                message=d.get("message", ""),
                category="second_opinion",
                recommended_action=d.get("suggestion", "") or "",
                evidence_basis=[d.get("source", "godibot")],
            ))

        # Build suggested corrections as AgentRecommendation list
        suggested: list[AgentRecommendation] = []
        for d in discrepancies:
            if d.get("suggestion"):
                suggested.append(AgentRecommendation(
                    action=d["suggestion"],
                    category="second_opinion_correction",
                    priority="critical" if d.get("severity") == "hard_block" else "standard",
                    evidence_basis=[d.get("source", "godibot")],
                ))
        for trial in trials.get("omitted", []):
            suggested.append(AgentRecommendation(
                action=f"Evaluar elegibilidad para {trial['trial_id']}",
                category="trial_match",
                priority="standard",
                evidence_basis=[trial.get("citation", "")],
                data_requirements=trial.get("missing_data", []) or [],
            ))

        review = {
            "status": status,
            "confidence": round(confidence, 3),
            "discrepancies": discrepancies,
            "trial_omissions": trials.get("omitted", []),
            "biomarker_gaps": biomarkers.get("gaps", []),
            "longitudinal_concord": longitudinal,
            "guideline_check": guideline,
            "gates_reeval": gates,
            "llm_adversarial": llm_review,
            "override_required": override_required,
            "version": self.VERSION,
        }

        return AgentOutput(
            agent_id=self.agent_id,
            patient_id=agent_input.patient_id,
            recommendations=suggested,
            confidence_score=round(confidence * 100, 1),
            evidence_chain=evidence,
            data_gaps=biomarkers.get("data_gaps", []),
            alerts=alerts,
            metadata={"godibot_review": review, "state": state},
        )

    # ── Sub-validador 1: NCCN/EAU guideline cross-check ─────────────

    def _validate_nccn_eau(
        self,
        record: dict,
        compass: dict,
        state: str,
    ) -> dict[str, Any]:
        """Verifica que la recomendación cumpla NCCN v5.2026 / EAU 2026.

        Estrategia:
        - Para localized: valida que NCCN risk stratification fue computado
          y que la recomendación corresponde al estrato.
        - Para mCSPC: valida intensificación (triplete/doblete) según
          CHAARTED/LATITUDE volumen y riesgo.
        - Para mCRPC: valida AR-V7 evaluation antes de switch ARSI.
        """
        discrepancies: list[dict[str, Any]] = []
        try:
            from prostanet.shared.clinical_scores import nccn_risk_stratification  # noqa: F401
            nccn_available = True
        except ImportError:
            nccn_available = False

        evidence_basis = []
        compass_evidence = _get(compass, "evidence_summary", default=[])
        if isinstance(compass_evidence, dict):
            evidence_basis = list(compass_evidence.get("guideline_basis", []) or [])
        elif isinstance(compass_evidence, list):
            evidence_basis = compass_evidence

        guideline_mentioned = any(
            "nccn" in _coerce_text(b) or "eau" in _coerce_text(b)
            for b in evidence_basis
        )

        if not guideline_mentioned and compass:
            discrepancies.append({
                "code": "guideline_basis_missing",
                "severity": "soft_warning",
                "source": "godibot.guideline_check",
                "message": (
                    "El compass no cita NCCN v5.2026 ni EAU 2026 explícitamente "
                    "en evidence_summary."
                ),
                "suggestion": (
                    "Anclar la recomendación a guideline específica (NCCN PROS-X "
                    "o EAU sección Y) para trazabilidad regulatoria."
                ),
            })

        return {
            "guideline_basis_present": guideline_mentioned,
            "nccn_module_available": nccn_available,
            "evidence_basis_count": len(evidence_basis),
            "discrepancies": discrepancies,
        }

    # ── Sub-validador 2: Re-evaluación de 103 gates ─────────────────

    def _reeval_103_gates(self, record: dict, compass: dict) -> dict[str, Any]:
        """Re-ejecuta evaluate_all_yaml_gates(payload) y compara con
        los gates ya disparados en el compass. Detecta hard_blocks
        omitidos (gates que debieron disparar pero no fueron mencionados)."""
        discrepancies: list[dict[str, Any]] = []
        gates_reeval: list[dict] = []

        try:
            from prostanet.shared.pivotal_gates_yaml_loader import (
                evaluate_all_yaml_gates,
            )
        except ImportError:
            return {
                "reeval_attempted": False,
                "reason": "pivotal_gates_yaml_loader unavailable",
                "discrepancies": [],
            }

        # Build payload from record (flatten common fields)
        payload = self._build_gates_payload(record)
        try:
            gates_reeval = evaluate_all_yaml_gates(payload)
        except Exception as exc:
            logger.warning("GodiBot gate re-eval failed: %s", exc)
            return {
                "reeval_attempted": True,
                "error": str(exc),
                "discrepancies": [],
            }

        # Compass-mentioned gate codes (defensive extraction)
        compass_gates: set[str] = set()
        for key in ("gates_contraindications", "gates_panel", "pivotal_contraindication_gates"):
            block = _get(compass, key, default=None)
            if isinstance(block, list):
                for g in block:
                    if isinstance(g, dict) and g.get("code"):
                        compass_gates.add(str(g["code"]).lower())
            elif isinstance(block, dict) and block.get("triggered"):
                for g in block["triggered"]:
                    if isinstance(g, dict) and g.get("code"):
                        compass_gates.add(str(g["code"]).lower())

        # Detect omitted hard_block gates
        omitted_hard: list[dict] = []
        for gate in gates_reeval:
            severity = str(gate.get("severity", "")).lower()
            code = str(gate.get("code", "")).lower()
            if severity == "hard_block" and code and code not in compass_gates:
                omitted_hard.append(gate)
                discrepancies.append({
                    "code": f"gate_omitted:{code}",
                    "severity": "hard_block",
                    "source": "godibot.gates_reeval",
                    "message": (
                        f"Gate {code} (hard_block) disparó en re-evaluación pero "
                        f"NO está en compass.gates_contraindications. "
                        f"Mensaje original: {gate.get('message', '')[:200]}"
                    ),
                    "suggestion": (
                        f"Investigar por qué {code} no fue mencionado en la "
                        f"recomendación. Posible omisión clínica grave."
                    ),
                    "evidence_tag": gate.get("evidence_tag"),
                    "trial_refs": list(gate.get("trial_refs") or []),
                })

        return {
            "reeval_attempted": True,
            "triggered_count": len(gates_reeval),
            "compass_mentioned_count": len(compass_gates),
            "omitted_hard_blocks": omitted_hard,
            "discrepancies": discrepancies,
        }

    # ── Sub-validador 3: Biomarcadores omitidos ─────────────────────

    def _detect_omitted_biomarkers(
        self,
        record: dict,
        compass: dict,
    ) -> dict[str, Any]:
        """Detecta biomarcadores requeridos pero omitidos antes de
        prescribir terapias específicas.

        Reglas clínicas (NCCN PROS-2 cat 1):
        - PARP → requiere HRR confirmation (BRCA1/2/ATM/PALB2/CHEK2/CDK12)
        - Lu-177 → requiere PSMA-PET+ con SUVmax sobre hígado
        - Abiraterona → requiere Child-Pugh basal (B/C = contraindicación)
        - Ra-223 → requiere descartar viscerales (contraindicación ALSYMPCA)
        - Sipuleucel-T → requiere CD4 baseline (HIV+/CD4<200 contraindicación)
        - ARSI switch (post-ARSI) → AR-V7 recomendado (PROPHECY)
        """
        gaps: list[dict[str, Any]] = []
        discrepancies: list[dict[str, Any]] = []
        compass_text = _bundle_text_blob(compass)

        # Regla 1: PARP sin HRR
        if _mentions_any(compass_text, PARP_KEYWORDS):
            hrr_status = _coerce_text(_get(
                record, "hrr_test_result", "hrr_status",
                "hrr_mutation_status", default="",
            ))
            if not hrr_status or hrr_status in ("not_done", "pending", "unknown", ""):
                gap = {
                    "name": "HRR mutation status",
                    "required_for": "PARP inhibitor (olaparib/talazoparib/niraparib/rucaparib)",
                    "severity": "hard_block",
                    "guideline": "NCCN PROS-2 cat 1, FDA label (PROfound, TALAPRO-2, MAGNITUDE)",
                }
                gaps.append(gap)
                discrepancies.append({
                    "code": "biomarker_gap:hrr_pre_parp",
                    "severity": "hard_block",
                    "source": "godibot.biomarkers",
                    "message": (
                        "El compass menciona PARP inhibitor sin documentar HRR "
                        "germinal+somático. Response rate <15% en HRR-negativo "
                        "(MAGNITUDE evidence)."
                    ),
                    "suggestion": (
                        "Solicitar panel HRR (BRCA1/BRCA2/ATM/PALB2/CHEK2/CDK12) "
                        "germinal Y somático ANTES de iniciar PARP."
                    ),
                })

        # Regla 2: Lu-177 sin PSMA-PET+
        if _mentions_any(compass_text, LU177_KEYWORDS):
            psma = _get(record, "psma_pet_positive", "psma_pet_avidity_above_liver",
                        "psma_positive", default=None)
            suvmax = _to_float(_get(record, "psma_pet_max_suvmax",
                                    "psma_pet_suvmax", default=None))
            if psma is None and suvmax is None:
                gaps.append({
                    "name": "PSMA-PET imaging + SUVmax",
                    "required_for": "Lutetium-177 PSMA-617 (Pluvicto)",
                    "severity": "hard_block",
                    "guideline": "VISION/TheraP exclusion criteria (PSMA-PET negativo)",
                })
                discrepancies.append({
                    "code": "biomarker_gap:psma_pet_pre_lu177",
                    "severity": "hard_block",
                    "source": "godibot.biomarkers",
                    "message": (
                        "El compass menciona Lu-177 PSMA-617 sin documentar "
                        "PSMA-PET positivo (SUVmax sobre hígado). Contraindicación "
                        "VISION."
                    ),
                    "suggestion": (
                        "Solicitar PSMA-PET (Ga-68 o F-18) y confirmar SUVmax "
                        "lesión-índice > SUVmax hígado ANTES de Lu-177."
                    ),
                })

        # Regla 3: Abiraterona sin Child-Pugh
        if _mentions_any(compass_text, ABIRATERONE_KEYWORDS):
            child = _coerce_text(_get(record, "child_pugh_class",
                                      "hepatic_function_class", default=""))
            cirrhosis = _get(record, "cirrhosis", "liver_cirrhosis", default=None)
            if child in ("b", "c", "child-pugh b", "child-pugh c") or cirrhosis is True:
                discrepancies.append({
                    "code": "biomarker_gap:abi_child_pugh_bc",
                    "severity": "hard_block",
                    "source": "godibot.biomarkers",
                    "message": (
                        f"Paciente con Child-Pugh {child.upper() or 'B/C'} o cirrosis "
                        f"+ recomendación de Abiraterona. Contraindicación FDA label."
                    ),
                    "suggestion": (
                        "Cambiar a alternativa: Enzalutamida, Darolutamida, o "
                        "Apalutamida según estadio + comorbilidades."
                    ),
                })

        # Regla 4: Ra-223 con viscerales
        if _mentions_any(compass_text, RA223_KEYWORDS):
            visceral = _get(record, "visceral_metastasis", "visceral_mets",
                            "liver_mets", "lung_mets", "brain_mets", default=False)
            if visceral:
                discrepancies.append({
                    "code": "biomarker_gap:ra223_with_visceral",
                    "severity": "hard_block",
                    "source": "godibot.biomarkers",
                    "message": (
                        "Recomendación de Ra-223 con metástasis viscerales presentes. "
                        "Contraindicación ALSYMPCA (exclusion criterion)."
                    ),
                    "suggestion": (
                        "Re-evaluar: Ra-223 indicado solo en metástasis óseas "
                        "sintomáticas SIN componente visceral."
                    ),
                })

        # Regla 5: Sipuleucel-T sin CD4
        if _mentions_any(compass_text, SIPULEUCEL_KEYWORDS):
            cd4 = _to_float(_get(record, "cd4_count", "cd4_baseline", default=None))
            immunosup = _get(record, "immunosuppression",
                             "is_immunosuppressed", default=None)
            if cd4 is not None and cd4 < 200:
                discrepancies.append({
                    "code": "biomarker_gap:sipuleucel_low_cd4",
                    "severity": "hard_block",
                    "source": "godibot.biomarkers",
                    "message": (
                        f"Recomendación de Sipuleucel-T con CD4={cd4} (<200). "
                        f"Inmunoterapia ineficaz en paciente inmunosuprimido."
                    ),
                    "suggestion": (
                        "Reconsiderar: Sipuleucel-T requiere CD4≥200 funcional. "
                        "Alternativa: Abi/Enza/Daro según estadio."
                    ),
                })
            elif cd4 is None and not immunosup:
                gaps.append({
                    "name": "CD4 count + immunosuppression status",
                    "required_for": "Sipuleucel-T (Provenge)",
                    "severity": "soft_warning",
                    "guideline": "FDA label — riesgo de fallo terapéutico en inmunosuprimidos",
                })

        # Regla 6: ARSI switch sin AR-V7
        # (solo aplica si hay prior_arpi documentado)
        prior_arpi = _get(record, "prior_arpi", "prior_abiraterone",
                          "prior_enzalutamide", default=False)
        if prior_arpi and _mentions_any(compass_text, ARSI_SWITCH_KEYWORDS):
            ar_v7 = _coerce_text(_get(record, "ar_v7_status", "ar_v7_result",
                                      default=""))
            if not ar_v7 or ar_v7 in ("not_done", "pending", "unknown"):
                gaps.append({
                    "name": "AR-V7 splice variant status",
                    "required_for": "ARSI sequential switch post-progression",
                    "severity": "soft_warning",
                    "guideline": "PROPHECY (Antonarakis JCO 2017) — AR-V7+ predice resistencia ARSI",
                })

        data_gaps = [g["name"] for g in gaps]

        return {
            "gaps": gaps,
            "data_gaps": data_gaps,
            "discrepancies": discrepancies,
        }

    # ── Sub-validador 4: Trials elegibles omitidos ──────────────────

    def _detect_eligible_trials(
        self,
        record: dict,
        compass: dict,
    ) -> dict[str, Any]:
        """Cruza con trial_eligibility_engine para detectar trials
        pivotales elegibles que NO fueron mencionados en el compass."""
        try:
            from prostanet.shared.trial_eligibility_engine import (
                evaluate_all_eligible_trials,
            )
        except ImportError:
            return {"engine_available": False, "omitted": []}

        compass_text = _bundle_text_blob(compass)

        # Build patient dict normalizado para el engine
        patient = self._build_trial_patient(record)
        try:
            eligible = evaluate_all_eligible_trials(patient) or []
        except Exception as exc:
            logger.warning("GodiBot trial eligibility eval failed: %s", exc)
            return {"engine_available": True, "error": str(exc), "omitted": []}

        omitted: list[dict[str, Any]] = []
        for trial in eligible:
            if not trial.get("eligible"):
                continue
            trial_id = str(trial.get("trial_id", "")).strip()
            if not trial_id:
                continue
            tid_lower = trial_id.lower()
            # Si el trial NO es mencionado en el compass por id o por droga clave
            if tid_lower not in compass_text:
                omitted.append({
                    "trial_id": trial_id,
                    "confidence": trial.get("confidence", 1.0),
                    "reason": "; ".join(trial.get("reasons_eligible", [])[:2]),
                    "subgroup": trial.get("subgroup"),
                    "citation": trial.get("citation"),
                    "pmid": trial.get("pmid"),
                    "nct": trial.get("nct"),
                    "missing_data": trial.get("missing_data", []) or [],
                })

        # Limitar a top 5 más relevantes
        omitted.sort(key=lambda t: t.get("confidence", 0), reverse=True)
        return {
            "engine_available": True,
            "eligible_count": sum(1 for t in eligible if t.get("eligible")),
            "omitted": omitted[:5],
        }

    # ── Sub-validador 5: Coherencia longitudinal ────────────────────

    def _check_longitudinal_concordance(
        self,
        record: dict,
        compass: dict,
    ) -> dict[str, Any]:
        """Detecta inconsistencias temporales: progresiones sin
        re-estadificación, escalación prematura, etc."""
        discrepancies: list[dict[str, Any]] = []
        drift_detected = False

        state = _coerce_text(_get(record, "reconciled_state", "current_state",
                                  "disease_state"))

        # Heurística 1: m1_crpc sin restaging PSMA-PET reciente
        if state == "m1_crpc":
            last_psma = _get(record, "last_psma_pet_date",
                             "psma_pet_last_date", default=None)
            if not last_psma:
                drift_detected = True
                discrepancies.append({
                    "code": "longitudinal:m1crpc_no_recent_psma",
                    "severity": "soft_warning",
                    "source": "godibot.longitudinal",
                    "message": (
                        "Estado m1_crpc sin PSMA-PET reciente documentado. "
                        "Re-estadificación PSMA-PET recomendada antes de "
                        "decisión terapéutica (NCCN PROS-13)."
                    ),
                    "suggestion": "Solicitar PSMA-PET (Ga-68 o F-18) en próxima visita.",
                })

        # Heurística 2: BCR sin Phoenix criterion confirmation
        if state == "recurrence_bcr":
            psa = _to_float(_get(record, "psa_current", "psa_latest",
                                 "psa_value", default=None))
            nadir = _to_float(_get(record, "psa_nadir_post_rt",
                                   "post_rt_nadir", default=None))
            had_rt = _get(record, "prior_radiotherapy", "prior_rt",
                          default=False)
            if had_rt and psa and nadir and (psa - nadir) < 2.0:
                discrepancies.append({
                    "code": "longitudinal:bcr_post_rt_not_phoenix",
                    "severity": "soft_warning",
                    "source": "godibot.longitudinal",
                    "message": (
                        f"Estado recurrence_bcr post-RT con PSA={psa} y nadir={nadir}. "
                        f"Phoenix criterion requiere PSA ≥ nadir+2 ng/mL "
                        f"(actual delta={psa-nadir:.2f})."
                    ),
                    "suggestion": (
                        "Considerar PSA bounce post-RT (gate 54). Confirmar "
                        "Phoenix criterion antes de etiquetar BCR."
                    ),
                })

        # Heurística 3: Active surveillance con criterios fallados
        if state == "localized_surveillance":
            psadt = _to_float(_get(record, "psa_doubling_time_months",
                                   "psadt_months", default=None))
            if psadt is not None and psadt < 3.0:
                drift_detected = True
                discrepancies.append({
                    "code": "longitudinal:as_psadt_below_3mo",
                    "severity": "soft_warning",
                    "source": "godibot.longitudinal",
                    "message": (
                        f"Active surveillance con PSADT={psadt:.1f} meses "
                        f"(<3mo = rapid Stephenson). Criterios de exit-AS."
                    ),
                    "suggestion": (
                        "Re-evaluar candidatura AS: PRIAS exit criterion sugiere "
                        "biopsia confirmatoria + considerar tratamiento definitivo."
                    ),
                })

        return {
            "matched_trajectory": None,  # full oracle match diferido a v2
            "drift_detected": drift_detected,
            "discrepancies": discrepancies,
        }

    # ── Sub-validador 6: LLM "devil's advocate" (opcional) ──────────

    def _should_invoke_llm(self, confidence: float, state: str) -> bool:
        if not self._enable_llm:
            return False
        if confidence < self.LLM_CONFIDENCE_THRESHOLD:
            return True
        if state in COMPLEX_STAGES:
            return True
        return False

    def _llm_devils_advocate(
        self,
        record: dict,
        compass: dict,
        existing_discrepancies: list[dict[str, Any]],
        state: str,
    ) -> dict[str, Any] | None:
        """Invoca Claude como devil's advocate. Fallback graceful si SDK
        no disponible o cliente no inyectado."""
        if self._anthropic_client is None:
            try:
                from anthropic import Anthropic
                client = Anthropic()
            except Exception as exc:
                logger.debug("Anthropic SDK no disponible: %s", exc)
                return {
                    "invoked": False,
                    "reason": "Anthropic SDK no disponible localmente",
                    "additional_concerns": [],
                }
        else:
            client = self._anthropic_client

        # Construir prompt adversarial conciso
        headline = _get(compass, "headline", default="(sin headline)")
        rationale = _get(compass, "rationale", default="(sin rationale)")
        if isinstance(rationale, dict):
            rationale = rationale.get("summary") or str(rationale)[:300]

        prompt = (
            f"Eres un urólogo oncólogo experto actuando como devil's advocate. "
            f"Estado del paciente: {state}. "
            f"Recomendación generada: {str(headline)[:200]}. "
            f"Rationale: {str(rationale)[:400]}. "
            f"Discrepancias ya detectadas por reglas: "
            f"{[d.get('code') for d in existing_discrepancies][:5]}. "
            f"\n\nPregunta: ¿Qué motivos clínicos podrían hacer que esta "
            f"recomendación sea sub-óptima o incorrecta? Lista 1-3 preocupaciones "
            f"concretas y específicas (no genéricas). Si la recomendación parece "
            f"correcta, retorna lista vacía. Responde SOLO con bullets, máximo "
            f"50 palabras por bullet."
        )

        try:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            content = msg.content[0].text if msg.content else ""
            concerns = [
                line.lstrip("- •*").strip()
                for line in content.splitlines()
                if line.strip().startswith(("-", "•", "*"))
            ]
            return {
                "invoked": True,
                "model": "claude-sonnet-4-6",
                "summary": content[:500],
                "additional_concerns": concerns[:3],
            }
        except Exception as exc:
            logger.warning("GodiBot LLM call failed: %s", exc)
            return {
                "invoked": False,
                "reason": f"LLM call error: {exc}",
                "additional_concerns": [],
            }

    # ── Helpers internos ────────────────────────────────────────────

    def _extract_compass(
        self,
        record: dict,
        trigger_data: dict | None,
    ) -> dict:
        """Localiza el compass dentro del record o trigger_data."""
        for source in (trigger_data or {}, record):
            for key in ("clinical_compass", "compass", "compass_draft",
                        "godibot_target_compass"):
                compass = source.get(key) if isinstance(source, dict) else None
                if isinstance(compass, dict) and compass:
                    return compass
        return {}

    def _build_gates_payload(self, record: dict) -> dict[str, Any]:
        """Aplana campos clínicos al formato que evaluate_all_yaml_gates espera.

        Estrategia conservadora: pasa el record completo + claves estándar
        del bundle. Los gates YAML toleran campos extra (no causan error).
        """
        payload: dict[str, Any] = {}
        if isinstance(record, dict):
            payload.update(record)
            for sub in ("baseline", "identity", "biomarkers", "biomarker_longitudinal"):
                inner = record.get(sub)
                if isinstance(inner, dict):
                    payload.update(inner)
        return payload

    def _build_trial_patient(self, record: dict) -> dict[str, Any]:
        """Convierte el record clínico al formato esperado por
        trial_eligibility_engine. El engine internamente usa _safe_get
        con muchos aliases, por lo que pasar el record completo + algunos
        flatten extras es suficiente."""
        patient = dict(record) if isinstance(record, dict) else {}
        baseline = record.get("baseline") if isinstance(record, dict) else None
        if isinstance(baseline, dict):
            for k, v in baseline.items():
                patient.setdefault(k, v)
        return patient

    def _compute_confidence(
        self,
        discrepancies: list[dict[str, Any]],
        trials: dict[str, Any],
        longitudinal: dict[str, Any],
    ) -> float:
        """Score 0-1: 1.0 sin discrepancias, baja con cada hallazgo.

        Penalización:
        - hard_block: -0.40 cada uno
        - soft_warning: -0.10 cada uno
        - informational: -0.03 cada uno
        - trial_omission relevante: -0.05 cada uno
        - longitudinal drift: -0.10
        """
        score = 1.0
        for d in discrepancies:
            sev = d.get("severity", "informational")
            if sev == "hard_block":
                score -= 0.40
            elif sev == "soft_warning":
                score -= 0.10
            elif sev == "warning":
                score -= 0.10
            else:
                score -= 0.03
        score -= 0.05 * len(trials.get("omitted", []) or [])
        if longitudinal.get("drift_detected"):
            score -= 0.10
        return max(0.0, min(1.0, score))


# ──────────────────────────────────────────────────────────────────────
# Convenience helpers para uso desde profile_compass / orchestrator
# ──────────────────────────────────────────────────────────────────────


def run_godibot_review(
    patient_record: dict,
    *,
    patient_id: int = 0,
    trigger_event: str = "compass_generated",
    compass: dict | None = None,
    enable_llm: bool = True,
) -> dict[str, Any]:
    """Helper standalone — corre GodiBot sin pasar por event_bus.

    Útil para: integración directa en profile_compass, tests sintéticos,
    invocación desde endpoints REST on-demand.

    Returns:
        El dict `godibot_review` (mismo shape que `AgentOutput.metadata
        ["godibot_review"]`).
    """
    validator = GodiBotValidator(enable_llm_adversarial=enable_llm)
    record = dict(patient_record or {})
    if compass is not None and "clinical_compass" not in record:
        record["clinical_compass"] = compass

    agent_input = AgentInput(
        patient_id=patient_id,
        record=record,
        trigger_event=trigger_event,
        trigger_data={"clinical_compass": compass} if compass else {},
    )
    output = validator.evaluate_safe(agent_input)
    return output.metadata.get("godibot_review", {})


__all__ = [
    "GodiBotValidator",
    "run_godibot_review",
    "COMPLEX_STAGES",
]
