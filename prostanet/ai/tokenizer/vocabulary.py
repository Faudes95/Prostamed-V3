"""
Clinical vocabulary for tokenizing patient events into model-consumable sequences.

Maps clinical event types, lab codes, drug names, imaging modalities, and
clinical states to integer token IDs. Aligned with existing tracking_db tables.
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Special Tokens ───────────────────────────────────────────────────────

PAD_TOKEN = "[PAD]"
UNK_TOKEN = "[UNK]"
CLS_TOKEN = "[CLS]"
SEP_TOKEN = "[SEP]"
MASK_TOKEN = "[MASK]"

SPECIAL_TOKENS = [PAD_TOKEN, UNK_TOKEN, CLS_TOKEN, SEP_TOKEN, MASK_TOKEN]

# ── Event Type Tokens ────────────────────────────────────────────────────

EVENT_TYPES = [
    # Follow-up visit events
    "EVT_VISIT",
    "EVT_PSA",
    "EVT_TESTOSTERONE",
    "EVT_ECOG",
    # Lab value events (from biomarker_longitudinal)
    "EVT_LAB_ALP",
    "EVT_LAB_LDH",
    "EVT_LAB_ALBUMIN",
    "EVT_LAB_HEMOGLOBIN",
    "EVT_LAB_CREATININE",
    "EVT_LAB_AST",
    "EVT_LAB_ALT",
    "EVT_LAB_ANC",
    # Imaging events
    "EVT_IMG_MRI",
    "EVT_IMG_PSMA_PET",
    "EVT_IMG_BONE_SCAN",
    "EVT_IMG_CT",
    "EVT_IMG_CONVENTIONAL",
    # Treatment events (from treatment_history)
    "EVT_TREATMENT_START",
    "EVT_TREATMENT_END",
    "EVT_TREATMENT_RESPONSE",
    # Pathology events
    "EVT_BIOPSY",
    "EVT_SURGERY",
    "EVT_RADIATION",
    # Progression events
    "EVT_BCR_DETECTED",
    "EVT_PSA_PROGRESSION",
    "EVT_RADIOGRAPHIC_PROGRESSION",
    "EVT_CLINICAL_PROGRESSION",
    # State events
    "EVT_STATE_TRANSITION",
    # Outcome events
    "EVT_SRE",
    "EVT_VITAL_STATUS",
    # Clinical assessment
    "EVT_ASSESSMENT",
    # Document
    "EVT_DOCUMENT",
]

# ── Lab Value Bins ───────────────────────────────────────────────────────

PSA_BINS = [
    "PSA_<0.1",
    "PSA_0.1-0.2",
    "PSA_0.2-0.5",
    "PSA_0.5-1",
    "PSA_1-4",
    "PSA_4-10",
    "PSA_10-20",
    "PSA_20-50",
    "PSA_50-100",
    "PSA_>100",
]

TESTOSTERONE_BINS = [
    "TESTO_<20",
    "TESTO_20-50",
    "TESTO_50-100",
    "TESTO_100-300",
    "TESTO_>300",
]

ECOG_VALUES = ["ECOG_0", "ECOG_1", "ECOG_2", "ECOG_3", "ECOG_4"]

# ── Treatment Tokens (from therapy_catalog.py) ───────────────────────────

TREATMENT_TOKENS = [
    "TX_ADT_MONO",
    "TX_ADT_ABIRATERONE",
    "TX_ADT_ENZALUTAMIDE",
    "TX_ADT_APALUTAMIDE",
    "TX_ADT_DAROLUTAMIDE",
    "TX_ADT_DOCETAXEL",
    "TX_ADT_CABAZITAXEL",
    "TX_TRIPLET_DOCE_ABI",
    "TX_TRIPLET_DOCE_DARO",
    "TX_OLAPARIB",
    "TX_RUCAPARIB",
    "TX_NIRAPARIB_ABI",
    "TX_TALAZOPARIB_ENZA",
    "TX_LU177_PSMA",
    "TX_RADIUM223",
    "TX_PEMBROLIZUMAB",
    "TX_SIPULEUCEL_T",
    "TX_CABOZANTINIB",
    "TX_OTHER",
]

# ── Imaging Result Tokens ────────────────────────────────────────────────

IMAGING_RESULTS = [
    "IMG_NEGATIVE",
    "IMG_LOCAL_ONLY",
    "IMG_LOCAL_PELVIC",
    "IMG_OLIGOMETASTATIC",
    "IMG_DISSEMINATED",
    "IMG_NEW_LESIONS",
    "IMG_STABLE",
    "IMG_RESPONSE",
]

# ── State Tokens ─────────────────────────────────────────────────────────

STATE_TOKENS = [
    "STATE_diagnostic_workup",
    "STATE_post_negative_biopsy_followup",
    "STATE_localized_initial",
    "STATE_post_prostatectomy",
    "STATE_recurrence_bcr",
    "STATE_adt_progression_verification",
    "STATE_mcspc_oligo_metachronous",
    "STATE_mcspc_low_volume_sync_oligo",
    "STATE_mcspc_high_volume_sync",
    "STATE_mcspc_high_volume_metachronous",
    "STATE_mcspc_high_volume",
    "STATE_m0_crpc",
    "STATE_m1_crpc",
]

# ── Response Tokens ──────────────────────────────────────────────────────

RESPONSE_TOKENS = [
    "RESP_CR",
    "RESP_PR",
    "RESP_SD",
    "RESP_PD",
    "RESP_PSA50",
    "RESP_PSA90",
    "RESP_NO_RESPONSE",
]

# ── Gleason / ISUP Tokens ───────────────────────────────────────────────

GLEASON_TOKENS = [
    "GS_3+3",
    "GS_3+4",
    "GS_4+3",
    "GS_4+4",
    "GS_4+5",
    "GS_5+4",
    "GS_5+5",
    "GS_OTHER",
]

ISUP_TOKENS = ["ISUP_1", "ISUP_2", "ISUP_3", "ISUP_4", "ISUP_5"]

# ── Biomarker Tokens ─────────────────────────────────────────────────────

BIOMARKER_TOKENS = [
    "BIO_HRR_POSITIVE",
    "BIO_HRR_NEGATIVE",
    "BIO_BRCA2_POSITIVE",
    "BIO_MSI_HIGH",
    "BIO_TMB_HIGH",
    "BIO_ARV7_POSITIVE",
    "BIO_NEPC_SUSPICION",
    "BIO_PSMA_POSITIVE",
    "BIO_PSMA_NEGATIVE",
]


# ── Vocabulary Class ─────────────────────────────────────────────────────

@dataclass
class ClinicalVocabulary:
    """Manages the complete clinical token vocabulary."""

    _token_to_id: dict[str, int] | None = None
    _id_to_token: dict[int, str] | None = None

    def __post_init__(self) -> None:
        self._build()

    def _build(self) -> None:
        all_tokens: list[str] = []
        all_tokens.extend(SPECIAL_TOKENS)
        all_tokens.extend(EVENT_TYPES)
        all_tokens.extend(PSA_BINS)
        all_tokens.extend(TESTOSTERONE_BINS)
        all_tokens.extend(ECOG_VALUES)
        all_tokens.extend(TREATMENT_TOKENS)
        all_tokens.extend(IMAGING_RESULTS)
        all_tokens.extend(STATE_TOKENS)
        all_tokens.extend(RESPONSE_TOKENS)
        all_tokens.extend(GLEASON_TOKENS)
        all_tokens.extend(ISUP_TOKENS)
        all_tokens.extend(BIOMARKER_TOKENS)
        self._token_to_id = {t: i for i, t in enumerate(all_tokens)}
        self._id_to_token = {i: t for i, t in enumerate(all_tokens)}

    @property
    def size(self) -> int:
        assert self._token_to_id is not None
        return len(self._token_to_id)

    @property
    def pad_id(self) -> int:
        return self.token_to_id(PAD_TOKEN)

    @property
    def unk_id(self) -> int:
        return self.token_to_id(UNK_TOKEN)

    @property
    def cls_id(self) -> int:
        return self.token_to_id(CLS_TOKEN)

    def token_to_id(self, token: str) -> int:
        assert self._token_to_id is not None
        return self._token_to_id.get(token, self._token_to_id[UNK_TOKEN])

    def id_to_token(self, token_id: int) -> str:
        assert self._id_to_token is not None
        return self._id_to_token.get(token_id, UNK_TOKEN)

    def encode(self, tokens: list[str]) -> list[int]:
        return [self.token_to_id(t) for t in tokens]

    def decode(self, ids: list[int]) -> list[str]:
        return [self.id_to_token(i) for i in ids]
