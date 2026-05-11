# -*- coding: utf-8 -*-
"""
Motor de programación automática de seguimiento.

Genera calendarios de eventos clínicos (PSA, imagen, labs, biopsias)
basados en el track de manejo del paciente y guías NCCN/EAU.

Detecta eventos vencidos y genera alertas en smart_alerts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── Protocolos de vigilancia por track de manejo ────────────────────────────

SURVEILLANCE_PROTOCOLS: dict[str, list[dict[str, Any]]] = {
    "active_surveillance": [
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "after_24_months": 6, "guideline": "NCCN 5.2026 / EAU 2026"},
        {"event_type": "dre", "label": "Tacto rectal", "interval_months": 12, "guideline": "NCCN 5.2026"},
        {"event_type": "mri", "label": "mpMRI", "interval_months": 12, "after_24_months": 24, "guideline": "NCCN 5.2026 / EAU 2026"},
        {"event_type": "biopsy", "label": "Biopsia confirmatoria", "at_months": [6, 12], "then_interval_months": 24, "guideline": "NCCN 5.2026"},
    ],
    "post_rp": [
        {"event_type": "psa", "label": "PSA ultrasensible", "first_24_months": 3, "months_24_to_60": 6, "after_60_months": 12, "guideline": "NCCN 5.2026"},
        {"event_type": "dre", "label": "Tacto rectal", "interval_months": 12, "guideline": "NCCN 5.2026"},
        {"event_type": "qol", "label": "Evaluación QoL (IPSS, IIEF-5)", "interval_months": 6, "after_24_months": 12, "guideline": "ICHOM"},
    ],
    "post_rt": [
        {"event_type": "psa", "label": "PSA sérico", "first_60_months": 6, "after_60_months": 12, "guideline": "NCCN 5.2026"},
        {"event_type": "dre", "label": "Tacto rectal", "interval_months": 12, "guideline": "NCCN 5.2026"},
        {"event_type": "qol", "label": "Evaluación QoL", "interval_months": 6, "after_24_months": 12, "guideline": "ICHOM"},
    ],
    "on_arpi": [
        {"event_type": "labs", "label": "Labs (BH, PFH, electrolitos, testosterona)", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "imaging", "label": "Imagen (CT/gammagrama o PSMA-PET)", "interval_months": 3, "after_12_months": 6, "guideline": "NCCN 5.2026"},
        {"event_type": "testosterone", "label": "Testosterona (verificar castración)", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "cv_metabolic", "label": "Evaluación cardiovascular/metabólica", "interval_months": 6, "guideline": "EAU 2026"},
        {"event_type": "dxa", "label": "Densitometría ósea (DXA)", "interval_months": 24, "guideline": "NCCN 5.2026"},
    ],
    "on_docetaxel": [
        {"event_type": "labs", "label": "BH + PFH pre-ciclo", "interval_weeks": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "imaging", "label": "Imagen de re-estadificación", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "toxicity", "label": "Evaluación toxicidad CTCAE", "interval_weeks": 3, "guideline": "CTCAE v5"},
    ],
    "on_parp": [
        {"event_type": "labs", "label": "BH completa (atención a anemia)", "interval_months": 1, "after_6_months": 3, "guideline": "NCCN 5.2026 / PROfound"},
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "imaging", "label": "Imagen de re-estadificación", "interval_months": 3, "guideline": "NCCN 5.2026"},
    ],
    "on_lu177": [
        {"event_type": "labs", "label": "BH + PFR + PFH", "interval_weeks": 2, "guideline": "VISION trial protocol"},
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 1, "guideline": "VISION"},
        {"event_type": "imaging", "label": "PSMA-PET + CT", "interval_months": 3, "guideline": "VISION"},
    ],
    "systemic_surveillance": [
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "labs", "label": "Labs completos", "interval_months": 3, "guideline": "NCCN 5.2026"},
        {"event_type": "imaging", "label": "Imagen de re-estadificación", "interval_months": 3, "after_12_months": 6, "guideline": "NCCN 5.2026"},
        {"event_type": "qol", "label": "PROs (FACT-P, BPI, FACIT-Fatigue)", "interval_months": 3, "guideline": "ICHOM"},
    ],
    "diagnostic_surveillance": [
        {"event_type": "psa", "label": "PSA sérico", "interval_months": 3, "after_12_months": 6, "guideline": "EAU 2026"},
        {"event_type": "mri", "label": "mpMRI", "interval_months": 12, "guideline": "EAU 2026"},
    ],
    "rebiopsy_surveillance": [
        {"event_type": "psa", "label": "PSA sérico + PSAD", "interval_months": 6, "guideline": "EAU 2026"},
        {"event_type": "mri", "label": "mpMRI de control", "interval_months": 12, "guideline": "EAU 2026"},
    ],
}


@dataclass
class ScheduledEvent:
    """Evento programado de seguimiento."""
    patient_id: int
    event_type: str
    label: str
    management_track: str
    due_date: str  # YYYY-MM-DD
    guideline: str = ""
    completed: bool = False
    completed_date: str = ""
    overdue: bool = False
    days_overdue: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OverdueAlert:
    """Alerta de evento vencido."""
    patient_id: int
    event_type: str
    label: str
    due_date: str
    days_overdue: int
    severity: str  # "warning" | "critical"
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _months_since(start_date: date, ref_date: date) -> float:
    """Calcula meses aproximados entre dos fechas."""
    delta = ref_date - start_date
    return delta.days / 30.44


def _get_interval_months(protocol: dict, months_elapsed: float) -> int | None:
    """Determina el intervalo en meses según el tiempo transcurrido."""
    # Intervalos adaptativos según protocolo
    if "at_months" in protocol:
        return None  # eventos fijos, no periódicos

    if "interval_weeks" in protocol:
        weeks = protocol["interval_weeks"]
        return None  # se maneja con intervalo en semanas

    if months_elapsed > 60 and "after_60_months" in protocol:
        return protocol["after_60_months"]
    if months_elapsed > 24 and "after_24_months" in protocol:
        return protocol["after_24_months"]
    if months_elapsed > 12 and "after_12_months" in protocol:
        return protocol["after_12_months"]
    if months_elapsed > 6 and "after_6_months" in protocol:
        return protocol["after_6_months"]

    if "first_60_months" in protocol and months_elapsed <= 60:
        return protocol["first_60_months"]
    if "first_24_months" in protocol and months_elapsed <= 24:
        return protocol["first_24_months"]

    if "months_24_to_60" in protocol and 24 < months_elapsed <= 60:
        return protocol["months_24_to_60"]

    return protocol.get("interval_months")


def generate_schedule(
    patient_id: int,
    management_track: str,
    treatment_start_date: str | date,
    last_visit_date: str | date | None = None,
    horizon_months: int = 12,
) -> list[ScheduledEvent]:
    """
    Genera un calendario de eventos futuros para un paciente.

    Args:
        patient_id: ID del paciente
        management_track: track de manejo (e.g. 'active_surveillance', 'on_arpi')
        treatment_start_date: fecha de inicio de tratamiento o diagnóstico
        last_visit_date: última visita registrada (para calcular próxima)
        horizon_months: cuántos meses hacia adelante generar eventos

    Returns:
        Lista de ScheduledEvent
    """
    protocols = SURVEILLANCE_PROTOCOLS.get(management_track, [])
    if not protocols:
        logger.warning("No hay protocolo de vigilancia para track: %s", management_track)
        return []

    if isinstance(treatment_start_date, str):
        try:
            start = date.fromisoformat(treatment_start_date)
        except (ValueError, TypeError):
            return []
    else:
        start = treatment_start_date

    today = date.today()
    horizon_end = today + timedelta(days=horizon_months * 31)

    if isinstance(last_visit_date, str) and last_visit_date:
        try:
            last_visit = date.fromisoformat(last_visit_date)
        except (ValueError, TypeError):
            last_visit = start
    elif isinstance(last_visit_date, date):
        last_visit = last_visit_date
    else:
        last_visit = start

    events: list[ScheduledEvent] = []

    for protocol in protocols:
        event_type = protocol["event_type"]
        label = protocol["label"]
        guideline = protocol.get("guideline", "")

        # Eventos fijos (at_months)
        if "at_months" in protocol:
            for month_offset in protocol["at_months"]:
                due = start + timedelta(days=int(month_offset * 30.44))
                if due >= today:
                    events.append(ScheduledEvent(
                        patient_id=patient_id,
                        event_type=event_type,
                        label=label,
                        management_track=management_track,
                        due_date=due.isoformat(),
                        guideline=guideline,
                    ))
            # Luego periódicos si aplica
            if "then_interval_months" in protocol:
                last_fixed = max(protocol["at_months"])
                cursor = start + timedelta(days=int(last_fixed * 30.44))
                interval = protocol["then_interval_months"]
                while cursor <= horizon_end:
                    cursor += timedelta(days=int(interval * 30.44))
                    if cursor >= today:
                        events.append(ScheduledEvent(
                            patient_id=patient_id,
                            event_type=event_type,
                            label=label,
                            management_track=management_track,
                            due_date=cursor.isoformat(),
                            guideline=guideline,
                        ))
            continue

        # Eventos con intervalo en semanas
        if "interval_weeks" in protocol:
            weeks = protocol["interval_weeks"]
            cursor = max(last_visit, today - timedelta(days=7))
            while cursor <= horizon_end:
                cursor += timedelta(weeks=weeks)
                if cursor >= today:
                    events.append(ScheduledEvent(
                        patient_id=patient_id,
                        event_type=event_type,
                        label=label,
                        management_track=management_track,
                        due_date=cursor.isoformat(),
                        guideline=guideline,
                    ))
            continue

        # Eventos periódicos con intervalo adaptativo
        months_elapsed = _months_since(start, today)
        interval = _get_interval_months(protocol, months_elapsed)
        if not interval:
            continue

        cursor = max(last_visit, start)
        while cursor <= horizon_end:
            cursor += timedelta(days=int(interval * 30.44))
            if cursor >= today:
                events.append(ScheduledEvent(
                    patient_id=patient_id,
                    event_type=event_type,
                    label=label,
                    management_track=management_track,
                    due_date=cursor.isoformat(),
                    guideline=guideline,
                ))

    events.sort(key=lambda e: e.due_date)
    return events


def check_overdue(
    patient_id: int,
    management_track: str,
    treatment_start_date: str | date,
    completed_events: list[dict[str, Any]] | None = None,
    grace_days: int = 14,
) -> list[OverdueAlert]:
    """
    Revisa si hay eventos vencidos comparando el schedule con eventos completados.

    Args:
        patient_id: ID del paciente
        management_track: track de manejo
        treatment_start_date: fecha de inicio
        completed_events: lista de {'event_type': str, 'completed_date': str}
        grace_days: días de gracia antes de considerar vencido

    Returns:
        Lista de OverdueAlert
    """
    today = date.today()
    schedule = generate_schedule(
        patient_id, management_track, treatment_start_date,
        horizon_months=0,  # solo hacia atrás
    )

    completed_map: dict[str, date] = {}
    for ev in (completed_events or []):
        et = ev.get("event_type", "")
        cd = ev.get("completed_date", "")
        if et and cd:
            try:
                completed_map[et] = max(
                    completed_map.get(et, date.min),
                    date.fromisoformat(cd),
                )
            except (ValueError, TypeError):
                pass

    alerts: list[OverdueAlert] = []

    protocols = SURVEILLANCE_PROTOCOLS.get(management_track, [])
    for protocol in protocols:
        event_type = protocol["event_type"]
        label = protocol["label"]

        last_completed = completed_map.get(event_type)
        if isinstance(treatment_start_date, str):
            try:
                start = date.fromisoformat(treatment_start_date)
            except (ValueError, TypeError):
                continue
        else:
            start = treatment_start_date

        months_elapsed = _months_since(start, today)

        # Determinar intervalo esperado
        if "interval_weeks" in protocol:
            expected_interval_days = protocol["interval_weeks"] * 7
        elif "at_months" in protocol:
            continue  # eventos fijos no generan overdue genérico
        else:
            interval = _get_interval_months(protocol, months_elapsed)
            if not interval:
                continue
            expected_interval_days = int(interval * 30.44)

        # Calcular si está vencido
        reference = last_completed or start
        next_due = reference + timedelta(days=expected_interval_days)
        days_overdue = (today - next_due).days - grace_days

        if days_overdue > 0:
            severity = "critical" if days_overdue > 30 else "warning"
            alerts.append(OverdueAlert(
                patient_id=patient_id,
                event_type=event_type,
                label=label,
                due_date=next_due.isoformat(),
                days_overdue=days_overdue,
                severity=severity,
                message=f"{label} vencido hace {days_overdue} días (último: {reference.isoformat()}). Protocolo: {protocol.get('guideline', '')}",
            ))

    return alerts
