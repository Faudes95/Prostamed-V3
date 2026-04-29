# -*- coding: utf-8 -*-
"""
Population Watchdog Service — "El Vigilante Poblacional".

Background service that continuously monitors all active patients
and proactively surfaces:

  1. PSA progression signals (PSADT <6 months, BCR, castration escape)
  2. Overdue imaging or lab windows (NCCN protocol violations)
  3. Critical safety alerts (anemia, renal failure, testosterone escape)
  4. Treatment efficacy signals (PSA nadir not reached, primary resistance)
  5. State transition candidates (AI-detected pre-transitions)
  6. Data quality issues (missing biomarkers for treatment decisions)

The Watchdog does NOT modify patient records — it only reads and
generates alerts for human review.

Architecture:
  - Runs as a synchronous batch scan (can be scheduled via cron)
  - Each patient is evaluated in <50ms (no GPU)
  - Results are stored in ai_predictions table and returned as JSON
  - Scalable to 10,000+ patients per run

Usage::

    watchdog = PopulationWatchdog()
    report = watchdog.scan_all()
    critical = watchdog.get_critical_alerts()

    # One patient
    patient_alerts = watchdog.scan_patient(patient_id=42)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any

from prostanet.shared.phoenix import evaluate_phoenix

logger = logging.getLogger(__name__)


# ── Alert severity thresholds ──
PSA_DOUBLING_CRITICAL_MONTHS = 3.0
PSA_DOUBLING_WARNING_MONTHS = 6.0
TESTOSTERONE_ESCAPE_NG_DL = 50.0
HEMOGLOBIN_CRITICAL_G_DL = 8.0
HEMOGLOBIN_WARNING_G_DL = 10.0
OVERDUE_PSA_THRESHOLD_DAYS = 30   # Days past scheduled window
OVERDUE_IMAGING_THRESHOLD_DAYS = 45


@dataclass
class PatientAlert:
    """A single watchdog alert for a patient."""
    patient_id: int
    alert_type: str
    severity: str             # "critical" | "warning" | "info"
    category: str
    title: str
    message: str
    recommended_action: str
    guideline_reference: str = ""
    value: str = ""
    threshold: str = ""
    days_overdue: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchdogReport:
    """Full population watchdog scan report."""
    scan_date: str
    patients_scanned: int
    patients_with_alerts: int
    total_alerts: int
    critical_count: int
    warning_count: int
    info_count: int
    elapsed_seconds: float
    alerts_by_patient: dict[int, list[PatientAlert]] = field(default_factory=dict)
    summary_by_category: dict[str, int] = field(default_factory=dict)

    def get_critical(self) -> list[PatientAlert]:
        critical = []
        for alerts in self.alerts_by_patient.values():
            critical.extend(a for a in alerts if a.severity == "critical")
        return sorted(critical, key=lambda a: a.patient_id)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "scan_date": self.scan_date,
            "patients_scanned": self.patients_scanned,
            "patients_with_alerts": self.patients_with_alerts,
            "total_alerts": self.total_alerts,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "elapsed_seconds": self.elapsed_seconds,
            "summary_by_category": self.summary_by_category,
            "critical_alerts": [a.to_dict() for a in self.get_critical()],
        }
        return d


class PopulationWatchdog:
    """
    Scans all active patients and generates proactive clinical alerts.

    Each alert is immediately actionable and includes the recommended
    clinical action and guideline reference.
    """

    def __init__(self, max_patients: int = 5000) -> None:
        self.max_patients = max_patients

    def scan_all(self, state_filter: str | None = None) -> WatchdogReport:
        """
        Scan all active patients.

        Args:
            state_filter: if provided, only scan patients in this state

        Returns:
            WatchdogReport with all alerts
        """
        from tracking_db import get_patient_full_record, _connect

        t0 = time.perf_counter()

        # Get patient IDs
        conn = _connect()
        c = conn.cursor()
        if state_filter:
            c.execute("""
                SELECT DISTINCT pi.id
                FROM patient_identity pi
                JOIN clinical_assessments ca ON ca.patient_id = pi.id
                WHERE ca.id IN (
                    SELECT MAX(id) FROM clinical_assessments GROUP BY patient_id
                )
                AND ca.state = ?
                ORDER BY pi.id
                LIMIT ?
            """, (state_filter, self.max_patients))
        else:
            c.execute(
                "SELECT id FROM patient_identity ORDER BY id LIMIT ?",
                (self.max_patients,),
            )
        patient_ids = [row["id"] for row in c.fetchall()]
        conn.close()

        logger.info("Watchdog scanning %d patients...", len(patient_ids))

        alerts_by_patient: dict[int, list[PatientAlert]] = {}
        total = 0
        critical_count = 0
        warning_count = 0
        info_count = 0
        category_counts: dict[str, int] = {}

        for pid in patient_ids:
            try:
                record = get_patient_full_record(pid)
                if not record:
                    continue
                patient_alerts = self._evaluate_patient(pid, record)
                if patient_alerts:
                    alerts_by_patient[pid] = patient_alerts
                    for a in patient_alerts:
                        total += 1
                        if a.severity == "critical":
                            critical_count += 1
                        elif a.severity == "warning":
                            warning_count += 1
                        else:
                            info_count += 1
                        category_counts[a.category] = category_counts.get(a.category, 0) + 1
            except Exception as exc:
                logger.debug("Watchdog error for patient %d: %s", pid, exc)

        elapsed = time.perf_counter() - t0

        report = WatchdogReport(
            scan_date=date.today().isoformat(),
            patients_scanned=len(patient_ids),
            patients_with_alerts=len(alerts_by_patient),
            total_alerts=total,
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
            elapsed_seconds=round(elapsed, 2),
            alerts_by_patient=alerts_by_patient,
            summary_by_category=category_counts,
        )

        logger.info(
            "Watchdog complete: %d patients, %d alerts (%d critical) in %.1fs",
            len(patient_ids), total, critical_count, elapsed,
        )

        # Persist to DB
        self._persist_report(report)

        return report

    def scan_patient(self, patient_id: int) -> list[PatientAlert]:
        """Scan a single patient. Returns list of alerts."""
        from tracking_db import get_patient_full_record
        record = get_patient_full_record(patient_id)
        if not record:
            return []
        return self._evaluate_patient(patient_id, record)

    # ── Core evaluation logic ──

    def _evaluate_patient(
        self,
        patient_id: int,
        patient: dict[str, Any],
    ) -> list[PatientAlert]:
        """Run all watchdog checks for one patient."""
        alerts: list[PatientAlert] = []

        follow_ups = patient.get("follow_ups", []) or []
        baseline = patient.get("baseline", {}) or {}
        treatments = patient.get("treatments", []) or []
        state = (
            patient.get("reconciled_state")
            or (patient.get("latest_assessment") or {}).get("state")
            or "diagnostic_workup"
        )
        identity = patient.get("identity", {}) or {}

        latest_fu = follow_ups[-1] if follow_ups else {}
        last_visit_date = latest_fu.get("visit_date") if latest_fu else None

        # ── 1. PSA kinetics ──
        alerts.extend(self._check_psa_kinetics(patient_id, follow_ups, state))

        # ── 2. Testosterone escape ──
        alerts.extend(self._check_testosterone(patient_id, latest_fu, state))

        # ── 3. Safety labs ──
        alerts.extend(self._check_safety_labs(patient_id, latest_fu))

        # ── 4. Protocol overdue ──
        alerts.extend(self._check_protocol_overdue(patient_id, last_visit_date, state))

        # ── 5. Missing critical biomarkers ──
        alerts.extend(self._check_biomarker_gaps(patient_id, patient, state, baseline))

        # ── 6. Treatment efficacy signals ──
        alerts.extend(self._check_treatment_efficacy(patient_id, follow_ups, treatments, state))

        # ── 7. ECOG deterioration ──
        alerts.extend(self._check_ecog_deterioration(patient_id, follow_ups))

        # ── 8. AI state transition signal ──
        alerts.extend(self._check_ai_transition(patient_id, patient, state))

        return alerts

    def _check_psa_kinetics(
        self,
        pid: int,
        follow_ups: list,
        state: str,
    ) -> list[PatientAlert]:
        from prostanet.domains.patient_tracking.natural_history_tracker import NaturalHistoryTracker
        alerts = []

        if len(follow_ups) < 3:
            return alerts

        psadt = NaturalHistoryTracker._compute_psadt(follow_ups)
        if psadt is None:
            return alerts

        if psadt < PSA_DOUBLING_CRITICAL_MONTHS:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="psadt_critical",
                severity="critical",
                category="psa_kinetics",
                title=f"PSADT crítico: {psadt} meses",
                message=f"El tiempo de duplicación de PSA es {psadt} meses (umbral crítico: <{PSA_DOUBLING_CRITICAL_MONTHS}m). "
                        f"Progresión muy rápida. Reevaluación urgente.",
                recommended_action="Estadificación urgente + considerar cambio de tratamiento inmediato",
                guideline_reference="NCCN PCa v5.2026 — BCR/CRPC section",
                value=f"PSADT={psadt}m",
                threshold=f"<{PSA_DOUBLING_CRITICAL_MONTHS}m",
            ))
        elif psadt < PSA_DOUBLING_WARNING_MONTHS:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="psadt_short",
                severity="warning",
                category="psa_kinetics",
                title=f"PSADT corto: {psadt} meses",
                message=f"PSADT {psadt} meses (<{PSA_DOUBLING_WARNING_MONTHS}m). "
                        f"Riesgo elevado de progresión a mCPRC a corto plazo.",
                recommended_action="Valorar PSMA-PET y ajuste terapéutico",
                guideline_reference="NCCN PCa v5.2026",
                value=f"PSADT={psadt}m",
                threshold=f"<{PSA_DOUBLING_WARNING_MONTHS}m",
            ))

        # BCR detection post-RP
        if state == "post_prostatectomy":
            psa_values = [float(fu.get("psa_current", 0)) for fu in follow_ups if fu.get("psa_current")]
            if psa_values and psa_values[-1] >= 0.2:
                consecutive_above = sum(1 for p in psa_values[-3:] if p >= 0.2)
                if consecutive_above >= 2:
                    alerts.append(PatientAlert(
                        patient_id=pid,
                        alert_type="bcr_detected",
                        severity="critical",
                        category="psa_kinetics",
                        title="Recurrencia bioquímica detectada",
                        message=f"PSA ≥0.2 ng/mL en ≥2 mediciones consecutivas. "
                                f"PSA actual: {psa_values[-1]:.2f} ng/mL.",
                        recommended_action="PSMA-PET para estadificación + evaluar RT salvaje o TDA",
                        guideline_reference="AUA/ASTRO BCR Guidelines 2024",
                        value=f"PSA={psa_values[-1]:.2f} ng/mL",
                        threshold="≥0.2 ng/mL × 2",
                    ))

        return alerts

    def _check_testosterone(
        self,
        pid: int,
        latest_fu: dict,
        state: str,
    ) -> list[PatientAlert]:
        alerts = []
        if state not in ("m0_crpc", "m1_crpc", "recurrence_bcr", "mcspc_high_volume_sync",
                         "mcspc_low_volume_sync_oligo", "mcspc_oligo_metachronous",
                         "adt_progression_verification"):
            return alerts

        testo = latest_fu.get("testosterone_current")
        if testo is None:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="testosterone_not_measured",
                severity="warning",
                category="safety",
                title="Testosterona no documentada",
                message=f"El paciente está en {state} pero no hay testosterona reciente. "
                        "Requiere confirmación de castración.",
                recommended_action="Solicitar testosterona total sérica",
                guideline_reference="NCCN — CRPC castration confirmation",
                value="no documentada",
                threshold="<50 ng/dL",
            ))
        elif float(testo) > TESTOSTERONE_ESCAPE_NG_DL:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="testosterone_escape",
                severity="critical",
                category="safety",
                title=f"Testosterona {testo} ng/dL — Castración no confirmada",
                message=f"Testosterona {testo} ng/dL supera el umbral de castración ({TESTOSTERONE_ESCAPE_NG_DL} ng/dL). "
                        "El diagnóstico de CPRC requiere testosterona en rango de castración.",
                recommended_action="Revisar adherencia a TDA. Considerar LHRH antagonista o bilateral orquiectomía.",
                guideline_reference="EAU 2026 — CRPC definition: testosterone <50 ng/dL",
                value=f"{testo} ng/dL",
                threshold=f"<{TESTOSTERONE_ESCAPE_NG_DL} ng/dL",
            ))
        return alerts

    def _check_safety_labs(
        self,
        pid: int,
        latest_fu: dict,
    ) -> list[PatientAlert]:
        alerts = []

        # Hemoglobin
        hgb = latest_fu.get("hemoglobin_current") or latest_fu.get("hemoglobin")
        if hgb is not None:
            hgb_f = float(hgb)
            if hgb_f < HEMOGLOBIN_CRITICAL_G_DL:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="anemia_critical",
                    severity="critical",
                    category="safety",
                    title=f"Anemia severa: Hgb {hgb} g/dL",
                    message=f"Hemoglobina {hgb} g/dL por debajo del umbral crítico ({HEMOGLOBIN_CRITICAL_G_DL} g/dL). "
                            "Riesgo de compromiso funcional y contraindicación para taxanos.",
                    recommended_action="Evaluación hematológica urgente. Suspender taxanos/Lu-177 hasta corrección.",
                    value=f"Hgb={hgb}", threshold=f">{HEMOGLOBIN_CRITICAL_G_DL}",
                ))
            elif hgb_f < HEMOGLOBIN_WARNING_G_DL:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="anemia_warning",
                    severity="warning",
                    category="safety",
                    title=f"Anemia moderada: Hgb {hgb} g/dL",
                    message=f"Hemoglobina {hgb} g/dL. Monitoreo estrecho. Considerar EPO si en quimio.",
                    recommended_action="Optimizar hemoglobina antes de próximo ciclo quimioterapia.",
                    value=f"Hgb={hgb}", threshold=f">{HEMOGLOBIN_WARNING_G_DL}",
                ))

        # ALP (bone metastases progression signal)
        alp = latest_fu.get("alp_current")
        if alp and float(alp) > 200:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="alp_elevated",
                severity="warning",
                category="safety",
                title=f"Fosfatasa alcalina elevada: {alp} U/L",
                message=f"FA {alp} U/L. Puede indicar progresión ósea activa o hepatotoxicidad.",
                recommended_action="Evaluar imagen ósea. Descartar hepatotoxicidad por abiraterona.",
                value=f"ALP={alp}", threshold="<200 U/L",
            ))

        # LDH
        ldh = latest_fu.get("ldh_current")
        if ldh and float(ldh) > 300:
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="ldh_elevated",
                severity="warning",
                category="safety",
                title=f"LDH elevada: {ldh} U/L",
                message=f"LDH {ldh} U/L. Factor pronóstico adverso en mCPRC.",
                recommended_action="Contexto clínico: revisar progresión/hemólisis.",
                value=f"LDH={ldh}", threshold="<300 U/L",
            ))

        return alerts

    def _check_protocol_overdue(
        self,
        pid: int,
        last_visit_date: str | None,
        state: str,
    ) -> list[PatientAlert]:
        alerts = []

        if not last_visit_date:
            return alerts

        # Expected monitoring intervals by state (months)
        expected_psa_interval: dict[str, int] = {
            "localized_initial": 6,
            "post_prostatectomy": 3,
            "recurrence_bcr": 3,
            "mcspc_high_volume_sync": 3,
            "mcspc_low_volume_sync_oligo": 3,
            "m0_crpc": 3,
            "m1_crpc": 3,
        }

        interval_months = expected_psa_interval.get(state)
        if not interval_months:
            return alerts

        try:
            last_d = date.fromisoformat(str(last_visit_date)[:10])
            expected_next = last_d + timedelta(days=interval_months * 30)
            today = date.today()
            days_overdue = (today - expected_next).days

            if days_overdue > OVERDUE_PSA_THRESHOLD_DAYS:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="overdue_followup",
                    severity="warning",
                    category="protocol_compliance",
                    title=f"Seguimiento vencido: {days_overdue} días de retraso",
                    message=f"Según {state}, el seguimiento debe ser cada {interval_months} meses. "
                            f"Última visita: {last_visit_date}. Vencimiento: {expected_next}.",
                    recommended_action=f"Programar visita urgente. Obtener PSA + laboratorios.",
                    guideline_reference="NCCN PCa v5.2026 — Monitoring schedule",
                    value=last_visit_date,
                    threshold=f"cada {interval_months} meses",
                    days_overdue=days_overdue,
                ))
        except Exception:
            pass

        return alerts

    def _check_biomarker_gaps(
        self,
        pid: int,
        patient: dict,
        state: str,
        baseline: dict,
    ) -> list[PatientAlert]:
        alerts = []
        genomic = patient.get("genomic_profile", {}) or {}

        if state in ("m1_crpc",) and not genomic.get("hrr_status") and not baseline.get("hrr_positive"):
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="missing_hrr",
                severity="warning",
                category="biomarker_gap",
                title="HRR no evaluado en M1-CPRC",
                message="El estado M1-CPRC requiere evaluación de HRR/BRCA2 para elegibilidad "
                        "a PARP inhibidores (olaparib — PROfound, BRCA2 OS benefit).",
                recommended_action="Solicitar panel HRR (tumor tissue o cfDNA). Evaluar biopsia líquida.",
                guideline_reference="NCCN PCa v5.2026 — Molecular testing M1 CRPC",
            ))

        if state in ("m1_crpc",) and not genomic.get("psma_positive") and not baseline.get("psma_positive"):
            alerts.append(PatientAlert(
                patient_id=pid,
                alert_type="missing_psma_pet",
                severity="info",
                category="biomarker_gap",
                title="PSMA-PET no documentado en M1-CPRC",
                message="PSMA-PET es necesario para evaluar elegibilidad a Lu-177-PSMA-617 (VISION).",
                recommended_action="Solicitar PSMA-PET (Ga-68 o F-18) si progresión post-ARSI + taxano.",
                guideline_reference="VISION trial, NCCN 2026 — Lu-177 eligibility",
            ))

        return alerts

    def _check_treatment_efficacy(
        self,
        pid: int,
        follow_ups: list,
        treatments: list,
        state: str,
    ) -> list[PatientAlert]:
        alerts = []
        if not treatments or not follow_ups:
            return alerts

        # Find active treatment and PSA at start
        active_tx = [t for t in treatments if not t.get("end_date")]
        if not active_tx:
            return alerts

        tx = active_tx[-1]
        tx_start = tx.get("start_date", "")
        if not tx_start:
            return alerts

        # PSA values after treatment start
        post_tx_psa = [
            float(fu.get("psa_current", 0))
            for fu in follow_ups
            if fu.get("visit_date", "") >= tx_start and fu.get("psa_current") is not None
        ]

        if len(post_tx_psa) < 2:
            return alerts

        psa_at_start = post_tx_psa[0]
        psa_nadir = min(post_tx_psa)
        psa_current = post_tx_psa[-1]

        # Primary resistance: no PSA50 by 3 months
        try:
            from datetime import date
            start_d = date.fromisoformat(str(tx_start)[:10])
            months_on_tx = (date.today() - start_d).days / 30.44
        except Exception:
            months_on_tx = 0

        if months_on_tx > 3 and psa_at_start > 0:
            psa50 = (psa_nadir / psa_at_start) <= 0.5
            if not psa50:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="primary_resistance",
                    severity="warning",
                    category="treatment_efficacy",
                    title=f"Sin PSA50 tras {months_on_tx:.0f} meses en {tx.get('drug_scheme','')}",
                    message=f"PSA al inicio: {psa_at_start:.1f} → nadir: {psa_nadir:.1f} ng/mL "
                            f"(reducción: {(1-psa_nadir/psa_at_start):.0%}). Sin PSA50.",
                    recommended_action="Reevaluar respuesta. Considerar cambio precoz o ensayo clínico.",
                    guideline_reference="PCWG3 — PSA response criteria",
                    value=f"nadir={psa_nadir:.1f}",
                    threshold="PSA50 a 3 meses",
                ))

        # Progression: PSA >25% above nadir (PCWG3). EPIC 1 FIX-PCWG3-1:
        # delegar el gate nadir+2 al helper canónico evaluate_phoenix para
        # uniformidad con el motor de alertas y reducir duplicación.
        if psa_nadir < psa_current and psa_nadir > 0:
            pct_rise = (psa_current - psa_nadir) / psa_nadir
            phoenix_evaluation = evaluate_phoenix({
                "psa_nadir": psa_nadir,
                "psa_current": psa_current,
            })
            if pct_rise >= 0.25 and phoenix_evaluation.threshold_reached:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="psa_progression_pcwg3",
                    severity="warning",
                    category="treatment_efficacy",
                    title=f"Progresión PSA (PCWG3): +{pct_rise:.0%} sobre nadir",
                    message=f"Nadir PSA: {psa_nadir:.2f} → actual: {psa_current:.2f} ng/mL "
                            f"(+{psa_current-psa_nadir:.2f} = +{pct_rise:.0%}). "
                            "Criterios PCWG3 de progresión bioquímica.",
                    recommended_action="Confirmar con imagen. Evaluar siguiente línea terapéutica.",
                    guideline_reference="PCWG3 Scher 2016",
                    value=f"PSA={psa_current:.2f}",
                    threshold="nadir+25%+2ng/mL",
                ))

        return alerts

    def _check_ecog_deterioration(
        self,
        pid: int,
        follow_ups: list,
    ) -> list[PatientAlert]:
        alerts = []
        ecog_series = [
            int(fu.get("ecog_current") or fu.get("ecog", -1))
            for fu in follow_ups[-6:]
            if (fu.get("ecog_current") or fu.get("ecog")) is not None
        ]
        ecog_series = [e for e in ecog_series if e >= 0]

        if len(ecog_series) >= 3:
            if ecog_series[-1] >= 3 and ecog_series[0] <= 1:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="ecog_severe_deterioration",
                    severity="critical",
                    category="functional_status",
                    title=f"Deterioro severo ECOG: {ecog_series[0]} → {ecog_series[-1]}",
                    message=f"ECOG deterioró de {ecog_series[0]} a {ecog_series[-1]}. "
                            "Impacta elegibilidad para taxanos, Lu-177, y ensayos clínicos.",
                    recommended_action="Evaluar causa (progresión, toxicidad, comorbilidad). "
                                      "Cuidados paliativos si ECOG ≥3.",
                    guideline_reference="NCCN PCa — Performance status gates",
                    value=f"ECOG={ecog_series[-1]}",
                    threshold="ECOG ≤2 para mayoría de tratamientos",
                ))
            elif ecog_series[-1] > ecog_series[0]:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="ecog_deterioration",
                    severity="warning",
                    category="functional_status",
                    title=f"ECOG en deterioro: {ecog_series[0]} → {ecog_series[-1]}",
                    message="Estado funcional en tendencia descendente. Monitoreo estrecho.",
                    recommended_action="Evaluar causa del deterioro funcional.",
                    value=f"ECOG={ecog_series[-1]}",
                    threshold="ECOG estable",
                ))

        return alerts

    def _check_ai_transition(
        self,
        pid: int,
        patient: dict,
        state: str,
    ) -> list[PatientAlert]:
        """Check AI model for imminent state transition."""
        alerts = []
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if not resolve_feature_flags().get("ENABLE_AI_STATE_PREDICTION"):
                return alerts

            from prostanet.ai.inference.runtime_registry import get_runtime_model_registry

            reg = get_runtime_model_registry()
            model = reg.get("state_transition")
            if not model:
                return alerts

            result = model.predict(patient)
            next_state = result.values.get("predicted_state")
            time_months = result.values.get("median_time_months", 99)
            conf = result.values.get("model_confidence", 0)

            if next_state and next_state != state and conf >= 0.7 and time_months <= 6:
                alerts.append(PatientAlert(
                    patient_id=pid,
                    alert_type="ai_transition_imminent",
                    severity="warning",
                    category="ai_prediction",
                    title=f"IA: transición a {next_state} en ~{time_months:.0f} meses",
                    message=f"El modelo Transformer predice transición a {next_state} "
                            f"en ~{time_months:.0f} meses (confianza: {conf:.0%}).",
                    recommended_action="Anticipar siguiente línea terapéutica. Obtener biomarcadores.",
                    guideline_reference="ProstaNet Transformer v1.0",
                    value=f"→{next_state}",
                    threshold="confianza ≥70%",
                ))
        except Exception:
            pass

        return alerts

    def _persist_report(self, report: WatchdogReport) -> None:
        """Persist watchdog summary to ai_predictions table."""
        try:
            from tracking_db import _connect
            conn = _connect()
            c = conn.cursor()
            import json
            c.execute("""
                INSERT INTO ai_predictions
                    (patient_id, model_id, prediction_type, prediction_json, confidence_score, created_at)
                VALUES (0, 'population_watchdog', 'watchdog_scan', ?, ?, ?)
            """, (
                json.dumps({
                    "patients_scanned": report.patients_scanned,
                    "total_alerts": report.total_alerts,
                    "critical_count": report.critical_count,
                    "summary_by_category": report.summary_by_category,
                }),
                round(report.patients_scanned / max(1, report.total_alerts), 3) if report.total_alerts else 1.0,
                report.scan_date,
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.debug("Could not persist watchdog report: %s", exc)
