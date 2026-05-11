"""
Clinical Event Tokenizer.

Converts a patient's longitudinal record (as returned by tracking_db
get_patient_full_record()) into a chronologically sorted sequence of
ClinicalTokens suitable for Transformer-based models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from prostanet.ai.tokenizer.vocabulary import (
    ClinicalVocabulary,
    PSA_BINS,
    TESTOSTERONE_BINS,
)


@dataclass
class ClinicalToken:
    """A single clinical event token in the patient timeline."""

    event_type: str  # Vocabulary token for event type (e.g. "EVT_PSA")
    value_token: str  # Vocabulary token for the value (e.g. "PSA_4-10")
    days_from_diagnosis: int  # Days since diagnosis date
    raw_value: float | None = None  # Original numeric value if applicable
    source_table: str = ""  # Which DB table this came from

    def __repr__(self) -> str:
        return f"ClinicalToken({self.event_type}, {self.value_token}, day={self.days_from_diagnosis})"


@dataclass
class TokenizedPatient:
    """A fully tokenized patient sequence ready for model input."""

    patient_id: int
    tokens: list[ClinicalToken] = field(default_factory=list)
    diagnosis_date: str = ""
    current_state: str = ""

    @property
    def length(self) -> int:
        return len(self.tokens)

    def token_ids(self, vocab: ClinicalVocabulary) -> list[int]:
        """Convert tokens to integer IDs."""
        ids = [vocab.cls_id]
        for token in self.tokens:
            ids.append(vocab.token_to_id(token.event_type))
            ids.append(vocab.token_to_id(token.value_token))
        return ids

    def time_positions(self) -> list[float]:
        """Time positions in days for positional encoding."""
        positions = [0.0]  # CLS token at time 0
        for token in self.tokens:
            positions.append(float(token.days_from_diagnosis))
            positions.append(float(token.days_from_diagnosis))
        return positions


# ── Value Binning Helpers ────────────────────────────────────────────────

def _bin_psa(value: float) -> str:
    """Bin PSA value into clinical range token."""
    if value < 0.1:
        return "PSA_<0.1"
    if value < 0.2:
        return "PSA_0.1-0.2"
    if value < 0.5:
        return "PSA_0.2-0.5"
    if value < 1.0:
        return "PSA_0.5-1"
    if value < 4.0:
        return "PSA_1-4"
    if value < 10.0:
        return "PSA_4-10"
    if value < 20.0:
        return "PSA_10-20"
    if value < 50.0:
        return "PSA_20-50"
    if value < 100.0:
        return "PSA_50-100"
    return "PSA_>100"


def _bin_testosterone(value: float) -> str:
    """Bin testosterone value into clinical range token."""
    if value < 20:
        return "TESTO_<20"
    if value < 50:
        return "TESTO_20-50"
    if value < 100:
        return "TESTO_50-100"
    if value < 300:
        return "TESTO_100-300"
    return "TESTO_>300"


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert to float."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse date string in common formats."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(date_str).strip()[:10], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _days_between(start: datetime | None, end: datetime | None) -> int:
    """Days between two dates, 0 if either is None."""
    if not start or not end:
        return 0
    return max(0, (end - start).days)


# ── Main Tokenizer ───────────────────────────────────────────────────────

class ClinicalEventTokenizer:
    """
    Converts a patient's full longitudinal record into a sequence of
    ClinicalTokens, sorted chronologically.

    Input: dict from tracking_db.get_patient_full_record() containing:
        - identity: {diagnosis_date, ...}
        - baseline: {baseline_psa, testosterone_baseline, ecog_score, ...}
        - follow_ups: [{visit_date, psa_current, ecog, testosterone, ...}, ...]
        - treatments: [{drug_scheme, start_date, end_date, ...}, ...]
        - imaging: [{study_date, study_type, findings, ...}, ...]
        - state_timeline: [{state, transition_date, ...}, ...]
        - biomarker_longitudinal: [{biomarker_type, value, recorded_at, ...}, ...]
        - biopsies: [{biopsy_date, gleason_primary, gleason_secondary, ...}, ...]
    """

    def __init__(self, max_length: int = 512) -> None:
        self.max_length = max_length

    def tokenize(self, record: dict[str, Any]) -> TokenizedPatient:
        """Tokenize a full patient record into chronological token sequence."""
        identity = record.get("identity") or {}
        diagnosis_date = _parse_date(
            identity.get("diagnosis_date")
            or identity.get("fecha_diagnostico")
        )
        patient_id = identity.get("id", 0)
        current_state = record.get("reconciled_state", "")

        tokens: list[ClinicalToken] = []

        # Baseline PSA
        baseline_psa = _safe_float(
            record.get("baseline", {}).get("baseline_psa")
        )
        if baseline_psa > 0:
            tokens.append(
                ClinicalToken(
                    event_type="EVT_PSA",
                    value_token=_bin_psa(baseline_psa),
                    days_from_diagnosis=0,
                    raw_value=baseline_psa,
                    source_table="clinical_baseline",
                )
            )

        # Baseline ECOG
        ecog = record.get("baseline", {}).get("ecog_score")
        if ecog is not None and str(ecog) != "":
            ecog_int = int(_safe_float(ecog))
            if 0 <= ecog_int <= 4:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_ECOG",
                        value_token=f"ECOG_{ecog_int}",
                        days_from_diagnosis=0,
                        raw_value=float(ecog_int),
                        source_table="clinical_baseline",
                    )
                )

        # Follow-up visits
        for visit in record.get("follow_ups") or []:
            visit_date = _parse_date(visit.get("visit_date"))
            days = _days_between(diagnosis_date, visit_date)

            psa = _safe_float(visit.get("psa_current") or visit.get("psa"))
            if psa > 0:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_PSA",
                        value_token=_bin_psa(psa),
                        days_from_diagnosis=days,
                        raw_value=psa,
                        source_table="follow_up_visits",
                    )
                )

            testo = _safe_float(visit.get("testosterone"))
            if testo > 0:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_TESTOSTERONE",
                        value_token=_bin_testosterone(testo),
                        days_from_diagnosis=days,
                        raw_value=testo,
                        source_table="follow_up_visits",
                    )
                )

            visit_ecog = visit.get("ecog")
            if visit_ecog is not None and str(visit_ecog) != "":
                ecog_val = int(_safe_float(visit_ecog))
                if 0 <= ecog_val <= 4:
                    tokens.append(
                        ClinicalToken(
                            event_type="EVT_ECOG",
                            value_token=f"ECOG_{ecog_val}",
                            days_from_diagnosis=days,
                            raw_value=float(ecog_val),
                            source_table="follow_up_visits",
                        )
                    )

        # Biomarker longitudinal (PSA, testosterone, ALP, LDH, etc.)
        for bio in record.get("biomarker_longitudinal") or []:
            bio_date = _parse_date(bio.get("recorded_at"))
            days = _days_between(diagnosis_date, bio_date)
            bio_type = str(bio.get("biomarker_type", "")).lower()
            bio_value = _safe_float(bio.get("value"))

            if bio_type == "psa" and bio_value > 0:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_PSA",
                        value_token=_bin_psa(bio_value),
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )
            elif bio_type == "testosterone" and bio_value > 0:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_TESTOSTERONE",
                        value_token=_bin_testosterone(bio_value),
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )
            elif bio_type == "alp":
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_LAB_ALP",
                        value_token="EVT_LAB_ALP",
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )
            elif bio_type == "ldh":
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_LAB_LDH",
                        value_token="EVT_LAB_LDH",
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )
            elif bio_type == "hemoglobin":
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_LAB_HEMOGLOBIN",
                        value_token="EVT_LAB_HEMOGLOBIN",
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )
            elif bio_type == "creatinine":
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_LAB_CREATININE",
                        value_token="EVT_LAB_CREATININE",
                        days_from_diagnosis=days,
                        raw_value=bio_value,
                        source_table="biomarker_longitudinal",
                    )
                )

        # Treatment events
        for tx in record.get("treatments") or []:
            start_date = _parse_date(tx.get("start_date"))
            end_date = _parse_date(tx.get("end_date"))
            days_start = _days_between(diagnosis_date, start_date)
            regimen = str(tx.get("regimen_code") or tx.get("drug_scheme") or "OTHER").upper()
            tx_token = f"TX_{regimen}" if f"TX_{regimen}" != "TX_OTHER" else "TX_OTHER"

            tokens.append(
                ClinicalToken(
                    event_type="EVT_TREATMENT_START",
                    value_token=tx_token,
                    days_from_diagnosis=days_start,
                    source_table="treatment_history",
                )
            )

            if end_date:
                days_end = _days_between(diagnosis_date, end_date)
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_TREATMENT_END",
                        value_token=tx_token,
                        days_from_diagnosis=days_end,
                        source_table="treatment_history",
                    )
                )

        # Imaging events
        for img in record.get("imaging") or record.get("imaging_studies") or []:
            img_date = _parse_date(img.get("study_date"))
            days = _days_between(diagnosis_date, img_date)
            modality = str(img.get("study_type") or "").lower()

            evt_type = "EVT_IMG_CONVENTIONAL"
            if "psma" in modality:
                evt_type = "EVT_IMG_PSMA_PET"
            elif "mri" in modality or "rmn" in modality:
                evt_type = "EVT_IMG_MRI"
            elif "bone" in modality or "gammagra" in modality:
                evt_type = "EVT_IMG_BONE_SCAN"
            elif "ct" in modality or "tac" in modality:
                evt_type = "EVT_IMG_CT"

            tokens.append(
                ClinicalToken(
                    event_type=evt_type,
                    value_token="IMG_STABLE",
                    days_from_diagnosis=days,
                    source_table="imaging_studies",
                )
            )

        # State transitions
        for st in record.get("state_timeline") or []:
            st_date = _parse_date(st.get("transition_date") or st.get("recorded_at"))
            days = _days_between(diagnosis_date, st_date)
            state = str(st.get("state") or st.get("new_state") or "")
            if state:
                tokens.append(
                    ClinicalToken(
                        event_type="EVT_STATE_TRANSITION",
                        value_token=f"STATE_{state}",
                        days_from_diagnosis=days,
                        source_table="patient_state_timeline",
                    )
                )

        # Biopsy events
        for bx in record.get("biopsies") or []:
            bx_date = _parse_date(bx.get("biopsy_date"))
            days = _days_between(diagnosis_date, bx_date)
            gp = int(_safe_float(bx.get("gleason_primary"), 3))
            gs = int(_safe_float(bx.get("gleason_secondary"), 3))
            gs_token = f"GS_{gp}+{gs}"
            if gs_token not in (
                "GS_3+3", "GS_3+4", "GS_4+3", "GS_4+4",
                "GS_4+5", "GS_5+4", "GS_5+5",
            ):
                gs_token = "GS_OTHER"

            tokens.append(
                ClinicalToken(
                    event_type="EVT_BIOPSY",
                    value_token=gs_token,
                    days_from_diagnosis=days,
                    source_table="biopsy_details",
                )
            )

        # Sort chronologically
        tokens.sort(key=lambda t: t.days_from_diagnosis)

        # Truncate to max_length
        if len(tokens) > self.max_length:
            tokens = tokens[-self.max_length :]

        return TokenizedPatient(
            patient_id=patient_id,
            tokens=tokens,
            diagnosis_date=str(diagnosis_date) if diagnosis_date else "",
            current_state=current_state,
        )
