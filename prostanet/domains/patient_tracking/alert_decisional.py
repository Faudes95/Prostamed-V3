# -*- coding: utf-8 -*-
"""
Alertas decisionales proactivas — Fase 7.5.

Complementa ClinicalAlertEngine con alertas que detectan ventanas de
decisión terapéutica inminente o riesgo farmacológico emergente.

Dominios cubiertos:
  - FEVI basal / caída crítica bajo ARPI (cardio-oncología)
  - PSADT <3m (ventana de intensificación urgente)
  - Transaminasas x3 ULN bajo abiraterona/ARPI
  - Hipopotasemia bajo abiraterona
  - Hipertensión grado 3 bajo abiraterona/enza
  - Caídas recientes bajo enzalutamida
  - Testosterona >50 ng/dL bajo ADT (castración fallida)
  - Hb <10 bajo Ra-223 / quimioterapia
  - ANC <1500 bajo PARP / taxano
  - NSE / cromogranina elevadas (sospecha NEPC)
  - ctDNA rising pre-radiográfico
  - PSMA-PET positivo con PSA<0.5 (ventana SRT temprana)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class DecisionalAlert:
    alert_id: str
    severity: str  # "info" | "warning" | "critical"
    domain: str    # "cardio" | "hepatic" | "renal" | "metabolic" | "neurologic" | "hematologic" | "oncogenic_signal" | "therapeutic_window"
    title: str
    message: str
    triggering_value: str
    threshold: str
    recommended_action: str
    evidence_reference: str
    decision_window_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def evaluate_decisional_alerts(payload: dict) -> list[dict[str, Any]]:
    """Evalúa el payload y devuelve alertas decisionales estructuradas."""
    alerts: list[DecisionalAlert] = []

    # ── CARDIO ───────────────────────────────────────────────────────
    lvef = _safe_float(payload.get("lvef_percent"))
    lvef_baseline = _safe_float(payload.get("lvef_baseline_percent"))
    current_tx = str(payload.get("current_treatment", "")).lower()
    on_arpi = any(t in current_tx for t in ["abirater", "enzalut", "apalut", "darolut"])
    on_abiraterone = "abirater" in current_tx

    if on_arpi and lvef is not None and lvef < 40:
        alerts.append(DecisionalAlert(
            alert_id="LVEF_BAJO_ARPI",
            severity="critical",
            domain="cardio",
            title="FEVI <40% bajo ARPI",
            message="FEVI deteriorada requiere suspender ARPI y consultar cardio-oncología.",
            triggering_value=f"{lvef}%",
            threshold="<40%",
            recommended_action="Suspender ARPI, solicitar eco control + NT-proBNP, derivar cardio-oncología.",
            evidence_reference="ESC Cardio-Oncology Guidelines 2022",
        ))
    elif on_arpi and lvef is not None and lvef_baseline and (lvef_baseline - lvef) >= 10:
        alerts.append(DecisionalAlert(
            alert_id="LVEF_CAIDA_ARPI",
            severity="warning",
            domain="cardio",
            title="Caída FEVI ≥10% bajo ARPI",
            message="Vigilar insuficiencia cardíaca subclínica; considerar NT-proBNP y manejo multidisciplinario.",
            triggering_value=f"{lvef_baseline:.0f}→{lvef:.0f}%",
            threshold="∆≥10%",
            recommended_action="Solicitar NT-proBNP y evaluar ajuste/rotación terapéutica con cardiología.",
            evidence_reference="ESC 2022; FDA ARPI labels",
        ))

    # ── HIPERTENSIÓN / ABIRATERONA ───────────────────────────────────
    sbp = _safe_float(payload.get("systolic_bp") or payload.get("current_systolic_bp"))
    if on_abiraterone and sbp is not None and sbp >= 160:
        alerts.append(DecisionalAlert(
            alert_id="HTA_G3_ABIRATERONA",
            severity="warning",
            domain="cardio",
            title="HTA grado 3 bajo abiraterona",
            message="TAS ≥160 bajo abiraterona — optimizar K+, esteroide y antihipertensivo; revaluar elección.",
            triggering_value=f"{sbp:.0f} mmHg",
            threshold="≥160 mmHg",
            recommended_action="Chequear K+, ajustar prednisona, intensificar antihipertensivo (IECA/ARA-II).",
            evidence_reference="COU-AA-301/302 safety profile",
        ))

    # ── POTASIO / ABIRATERONA ────────────────────────────────────────
    k = _safe_float(payload.get("potassium"))
    if on_abiraterone and k is not None and k < 3.5:
        alerts.append(DecisionalAlert(
            alert_id="HIPOK_ABIRATERONA",
            severity="warning",
            domain="metabolic",
            title="Hipopotasemia bajo abiraterona",
            message="Mineralocorticoide-mediado; corregir y vigilar QTc.",
            triggering_value=f"K+ {k:.2f} mEq/L",
            threshold="<3.5",
            recommended_action="Suplementar K+, revisar diuréticos, aumentar prednisona a 10 mg BID si recurrente.",
            evidence_reference="COU-AA-302",
        ))

    # ── HEPÁTICO ─────────────────────────────────────────────────────
    alt = _safe_float(payload.get("alt"))
    ast = _safe_float(payload.get("ast"))
    uln = 40.0
    if on_arpi and ((alt is not None and alt > 3 * uln) or (ast is not None and ast > 3 * uln)):
        alerts.append(DecisionalAlert(
            alert_id="TRANSAMINASAS_X3_ARPI",
            severity="critical",
            domain="hepatic",
            title="Transaminasas ≥3× ULN bajo ARPI",
            message="Suspender ARPI hasta recuperación; investigar otras causas (viral, colestasis, DILI).",
            triggering_value=f"ALT {alt or 0:.0f} / AST {ast or 0:.0f}",
            threshold=">120 U/L (3×ULN)",
            recommended_action="Suspender ARPI, solicitar panel viral/ecografía, reiniciar a dosis reducida si <ULN.",
            evidence_reference="FDA ARPI labels; CIOMS DILI criteria",
        ))

    # ── NEUROLÓGICO / CAÍDAS ─────────────────────────────────────────
    falls_recent = _flag(payload, "fall_history_recent")
    on_enza = "enzalut" in current_tx
    if on_enza and falls_recent:
        alerts.append(DecisionalAlert(
            alert_id="CAIDAS_ENZALUTAMIDA",
            severity="warning",
            domain="neurologic",
            title="Caídas bajo enzalutamida",
            message="Considerar ajuste dosis (120 mg) o cambio a darolutamida (menos pasaje BHE).",
            triggering_value="Caída(s) en 12 meses",
            threshold=">=1 evento",
            recommended_action="Evaluar G8 + TUG + SPPB; fisioterapia; considerar darolutamida.",
            evidence_reference="ARAMIS (darolutamida con menor neurotoxicidad)",
        ))

    # ── ADT — CASTRACIÓN FALLIDA ─────────────────────────────────────
    testo = _safe_float(payload.get("testosterone") or payload.get("testosterone_current"))
    on_adt = _flag(payload, "on_adt") or "adt" in current_tx or "leuprol" in current_tx or "degarel" in current_tx
    if on_adt and testo is not None and testo > 50:
        alerts.append(DecisionalAlert(
            alert_id="CASTRACION_FALLIDA",
            severity="critical",
            domain="therapeutic_window",
            title="Testosterona >50 ng/dL bajo ADT",
            message="Castración no lograda — no reclasificar como CRPC; revisar adherencia/ruta/agente.",
            triggering_value=f"T {testo:.0f} ng/dL",
            threshold="≤50 ng/dL",
            recommended_action="Confirmar con 2ª medición; considerar cambio a degarelix o orquiectomía.",
            evidence_reference="EAU 2026, NCCN 5.2026 castration definition",
        ))

    # ── HEMATOLOGÍA ──────────────────────────────────────────────────
    hb = _safe_float(payload.get("hemoglobin") or payload.get("hb"))
    anc = _safe_float(payload.get("anc"))
    plt_ = _safe_float(payload.get("platelets"))
    on_ra223 = "radium" in current_tx or "ra-223" in current_tx or "xofigo" in current_tx
    on_parp = any(t in current_tx for t in ["olapar", "rucapar", "talazopar", "nirapar"])
    on_taxane = any(t in current_tx for t in ["docetax", "cabazitax"])

    if on_ra223 and hb is not None and hb < 10:
        alerts.append(DecisionalAlert(
            alert_id="HB_BAJO_RA223",
            severity="critical",
            domain="hematologic",
            title="Hb <10 bajo Ra-223",
            message="Postergar dosis; transfundir si sintomático; reevaluar continuidad del esquema.",
            triggering_value=f"Hb {hb:.1f}",
            threshold="<10 g/dL",
            recommended_action="Suspender dosis, completar estudios, valorar eritropoyetina/transfusión.",
            evidence_reference="ALSYMPCA protocol",
        ))
    if (on_parp or on_taxane) and anc is not None and anc < 1000:
        alerts.append(DecisionalAlert(
            alert_id="NEUTROPENIA_G3",
            severity="critical",
            domain="hematologic",
            title="Neutropenia grado 3-4",
            message="Reducir dosis / diferir ciclo; valorar G-CSF; descartar infección.",
            triggering_value=f"ANC {anc:.0f}",
            threshold="<1000",
            recommended_action="Retrasar quimio/PARP, iniciar G-CSF profiláctico, chequear infección.",
            evidence_reference="CTCAE v5 grading",
        ))
    if on_parp and plt_ is not None and plt_ < 100_000:
        alerts.append(DecisionalAlert(
            alert_id="TROMBOCITOPENIA_PARP",
            severity="warning",
            domain="hematologic",
            title="Plaquetas <100k bajo PARP",
            message="Reducir dosis PARP; evaluar SMD si persistente.",
            triggering_value=f"Plq {plt_:.0f}",
            threshold="<100k",
            recommended_action="Reducir dosis PARP en 50 mg (olaparib) o escalón (talazo/rucaparib).",
            evidence_reference="PROfound / TRITON3 safety",
        ))

    # ── SEÑAL ONCOGÉNICA / NEPC ──────────────────────────────────────
    nse = _safe_float(payload.get("nse") or payload.get("neuron_specific_enolase"))
    cga = _safe_float(payload.get("chromogranin_a"))
    psa_discordant = _flag(payload, "psa_discordant_low")
    if (nse is not None and nse > 16.3) or (cga is not None and cga > 100) or psa_discordant:
        alerts.append(DecisionalAlert(
            alert_id="SOSPECHA_NEPC",
            severity="warning",
            domain="oncogenic_signal",
            title="Señal de transformación neuroendocrina",
            message="Considerar biopsia metastásica; perfilar TP53/RB1/PTEN y FDG-PET; valorar platino-etopósido.",
            triggering_value=f"NSE {nse or 0:.0f} / CgA {cga or 0:.0f} / PSA discordante {int(psa_discordant)}",
            threshold="NSE>16.3, CgA>100 o PSA discordante",
            recommended_action="Biopsia dirigida, IHQ NE (sinaptofisina/cromogranina), panel molecular.",
            evidence_reference="Beltran NatCommun 2016; Aggarwal JCO 2018",
        ))

    # ── ctDNA RISING ─────────────────────────────────────────────────
    if _flag(payload, "ctdna_rising"):
        alerts.append(DecisionalAlert(
            alert_id="CTDNA_RISING",
            severity="warning",
            domain="oncogenic_signal",
            title="ctDNA en ascenso pre-radiográfico",
            message="Anticipar cambio de línea antes de progresión radiográfica.",
            triggering_value="ctDNA rising",
            threshold="VAF creciente",
            recommended_action="Adelantar reevaluación imagenológica; replanear siguiente línea.",
            evidence_reference="Wyatt JCO 2021; Chi EurUrol 2022",
        ))

    # ── VENTANA SRT TEMPRANA ─────────────────────────────────────────
    psa_now = _safe_float(payload.get("psa"))
    post_rp = _flag(payload, "post_prostatectomy") or str(payload.get("current_state", "")).lower() in {"recurrence_bcr", "post_prostatectomy"}
    psma_positive = _flag(payload, "psma_positive")
    if post_rp and psa_now is not None and 0.1 < psa_now < 0.5:
        alerts.append(DecisionalAlert(
            alert_id="SRT_VENTANA_TEMPRANA",
            severity="info",
            domain="therapeutic_window",
            title="Ventana de SRT temprana",
            message="PSA 0.1-0.5 post-RP: máximo beneficio salvage RT — no postergar.",
            triggering_value=f"PSA {psa_now:.2f}",
            threshold="<0.5 ng/mL",
            recommended_action="Solicitar PSMA-PET si no se ha hecho, planificar salvage RT intensificada.",
            evidence_reference="Tendulkar JCO 2016; EMPIRE-1",
            decision_window_days=45,
        ))
    if post_rp and psma_positive and psa_now is not None and psa_now < 1.0:
        alerts.append(DecisionalAlert(
            alert_id="PSMA_POS_PSA_BAJO",
            severity="warning",
            domain="therapeutic_window",
            title="PSMA+ con PSA<1",
            message="Lesión PSMA detectada en ventana oligorecurrente — considerar MDT/SBRT dirigida.",
            triggering_value=f"PSA {psa_now:.2f}",
            threshold="<1.0 ng/mL",
            recommended_action="Discutir MDT/SBRT vs salvage RT pelvis según patrón.",
            evidence_reference="ORIOLE / STOMP / EMPIRE-1",
            decision_window_days=30,
        ))

    # ── PSADT <3m ────────────────────────────────────────────────────
    psadt = _safe_float(payload.get("psadt_months"))
    if psadt is not None and 0 < psadt < 3:
        alerts.append(DecisionalAlert(
            alert_id="PSADT_CRITICO",
            severity="critical",
            domain="therapeutic_window",
            title="PSADT <3 meses",
            message="Cinética agresiva: priorizar estudios de extensión (PSMA-PET) y anticipar cambio de línea.",
            triggering_value=f"PSADT {psadt:.1f}m",
            threshold="<3 meses",
            recommended_action="PSMA-PET urgente, reevaluar escala terapéutica; descartar transformación NEPC.",
            evidence_reference="Freedland JAMA 2005",
            decision_window_days=21,
        ))

    return [a.to_dict() for a in alerts]
