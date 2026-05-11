"""
Data Loaders — SQLite → tensors for model training.

Reads patient records from the tracking database, tokenizes them,
and produces PyTorch datasets suitable for training each model type.
"""

from __future__ import annotations

import logging
import random
from typing import Any

import torch
from torch.utils.data import Dataset

logger = logging.getLogger(__name__)


class StateTransitionDataset(Dataset):
    """
    Dataset for the State Transition Transformer.

    Each sample: (token_ids, time_positions, attention_mask, target_state, time_to_transition).
    """

    def __init__(
        self,
        records: list[dict[str, Any]],
        max_length: int = 256,
    ) -> None:
        from prostanet.ai.tokenizer.clinical_tokenizer import ClinicalEventTokenizer
        from prostanet.ai.config import STATE_TO_IDX

        self.tokenizer = ClinicalEventTokenizer(max_length=max_length)
        self.max_length = max_length
        self.samples: list[dict[str, Any]] = []

        for record in records:
            state = record.get("reconciled_state", "")
            if state not in STATE_TO_IDX:
                continue

            tokenized = self.tokenizer.tokenize(record)
            if len(tokenized.tokens) < 2:
                continue

            token_ids = tokenized.token_ids()
            time_pos = tokenized.time_positions()

            # Pad / truncate
            token_ids, time_pos, mask = self._pad(token_ids, time_pos)

            self.samples.append({
                "token_ids": torch.tensor(token_ids, dtype=torch.long),
                "time_positions": torch.tensor(time_pos, dtype=torch.float32),
                "attention_mask": torch.tensor(mask, dtype=torch.bool),
                "target_state": STATE_TO_IDX[state],
                "time_to_transition": record.get("time_to_transition_months", 12.0),
            })

        logger.info("StateTransitionDataset: %d samples", len(self.samples))

    def _pad(
        self, ids: list[int], times: list[float]
    ) -> tuple[list[int], list[float], list[bool]]:
        n = len(ids)
        if n >= self.max_length:
            return ids[: self.max_length], times[: self.max_length], [False] * self.max_length
        pad_n = self.max_length - n
        return (
            ids + [0] * pad_n,
            times + [0.0] * pad_n,
            [False] * n + [True] * pad_n,
        )

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        s = self.samples[idx]
        return {
            "token_ids": s["token_ids"],
            "time_positions": s["time_positions"],
            "attention_mask": s["attention_mask"],
            "target_state": torch.tensor(s["target_state"], dtype=torch.long),
            "time_to_transition": torch.tensor(
                s["time_to_transition"], dtype=torch.float32
            ),
        }


class TreatmentResponseDataset(Dataset):
    """
    Dataset for the Treatment Response Predictor.

    Each sample: (patient_features, regimen_id, treatment_history, targets).
    """

    def __init__(self, records: list[dict[str, Any]]) -> None:
        from prostanet.ai.models.treatment_response import (
            TreatmentResponsePredictor,
        )

        self.samples: list[dict[str, Any]] = []

        for record in records:
            features = TreatmentResponsePredictor._extract_patient_features(record)
            treatments = record.get("treatments") or []

            # Create a sample per treatment in the record
            for tx in treatments:
                regimen_id = tx.get("regimen_id", 0)
                targets = tx.get("outcomes", {})
                if not targets:
                    continue

                self.samples.append({
                    "patient_features": torch.tensor(features, dtype=torch.float32),
                    "regimen_id": regimen_id,
                    "psa50": float(targets.get("psa50", 0)),
                    "psa90": float(targets.get("psa90", 0)),
                    "rpfs_months": float(targets.get("rpfs_months", 12)),
                    "response_category": int(targets.get("response_category", 2)),
                })

        logger.info("TreatmentResponseDataset: %d samples", len(self.samples))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        s = self.samples[idx]
        return {
            "patient_features": s["patient_features"],
            "regimen_id": torch.tensor(s["regimen_id"], dtype=torch.long),
            "psa50": torch.tensor(s["psa50"], dtype=torch.float32),
            "psa90": torch.tensor(s["psa90"], dtype=torch.float32),
            "rpfs_months": torch.tensor(s["rpfs_months"], dtype=torch.float32),
            "response_category": torch.tensor(
                s["response_category"], dtype=torch.long
            ),
        }


class SurvivalDataset(Dataset):
    """
    Dataset for DeepSurv.

    Each sample: (features, time, event_observed) per endpoint.
    """

    def __init__(
        self, records: list[dict[str, Any]], endpoint: str = "OS"
    ) -> None:
        from prostanet.ai.models.treatment_response import (
            TreatmentResponsePredictor,
        )

        self.samples: list[dict[str, Any]] = []

        for record in records:
            survival = record.get("survival", {})
            time_val = survival.get(f"{endpoint}_months")
            event = survival.get(f"{endpoint}_event")
            if time_val is None or event is None:
                continue

            features = TreatmentResponsePredictor._extract_patient_features(record)
            self.samples.append({
                "features": torch.tensor(features, dtype=torch.float32),
                "time": float(time_val),
                "event": int(event),
            })

        logger.info("SurvivalDataset[%s]: %d samples", endpoint, len(self.samples))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        s = self.samples[idx]
        return {
            "features": s["features"],
            "time": torch.tensor(s["time"], dtype=torch.float32),
            "event": torch.tensor(s["event"], dtype=torch.long),
        }


def load_all_patient_records(
    db_path: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Load full patient records from the tracking database."""
    try:
        import sqlite3

        from tracking_db import DB_PATH, get_patient_full_record

        path = db_path or DB_PATH
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT id FROM patient_identity ORDER BY id"
        if limit:
            query += f" LIMIT {int(limit)}"

        cursor.execute(query)
        patient_ids = [row["id"] for row in cursor.fetchall()]
        conn.close()

        records: list[dict[str, Any]] = []
        for pid in patient_ids:
            try:
                rec = get_patient_full_record(pid)
                if rec:
                    records.append(rec)
            except Exception:
                continue

        logger.info("Loaded %d patient records from DB", len(records))
        return records
    except Exception as exc:
        logger.error("Failed to load patient records: %s", exc)
        return []
