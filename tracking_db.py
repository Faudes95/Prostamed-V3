import sqlite3
import json
import os
import shutil
import re
import hashlib
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, date
import logging
from pathlib import Path

from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile,
    normalize_psma_imaging_payload,
)
from prostanet.domains.patient_tracking.closure_window_registry import enrich_window_with_registry
from prostanet.domains.patient_tracking.therapy_catalog import normalize_regimen_code, regimen_label
from prostanet.shared.clinical_fact_policies import certainty_rank, compute_freshness_status
from prostanet.shared.clinical_fact_registry import extract_canonical_fact_candidates
from prostanet.shared.converters import safe_bool
from prostanet.shared.gleason_profile import apply_gleason_profile, normalize_gleason_profile
from prostanet.shared.metastatic_profile import build_metastatic_profile, derive_legacy_metastasis

DEFAULT_DB_PATH = "prostanet_tracking.db"
DB_PATH = os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SQLITE_CONNECT_TIMEOUT_SEC = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30000
SQLITE_WRITE_JOURNAL_MODE = "WAL"
SQLITE_WRITE_SYNCHRONOUS = "NORMAL"


_RUNTIME_DERIVED_RECORD_KEYS = {
    "latest_signal_snapshot",
    "master_followup_plan",
    "master_followup_summary",
    "therapeutic_readiness_bundle",
    "advanced_followup_bundle",
    "staging_adjudication_bundle",
    "advanced_release_gate",
    "care_intent_contract",
    "decision_input_requirements",
    "clinical_memory_os",
    "clinical_kernel_snapshot",
    "profile_read_model",
    "schedule_read_model",
    "governance_read_model",
    "window_worklist_bundle",
    "live_benchmark",
}


def _document_store():
    from prostanet.domains.patient_tracking.document_ingestion import PatientDocumentPrivateStore

    root = Path(DB_PATH).resolve().parent / ".prostanet_private" / "patient_documents"
    return PatientDocumentPrivateStore(root=root)


def configure_db_path(path=None):
    """Permite inyectar una base SQLite distinta, útil para tests."""
    global DB_PATH
    DB_PATH = path or os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)
    return DB_PATH


def get_db_path():
    return DB_PATH


def _build_runtime_neutral_patient_record(record):
    if not record:
        return {}
    neutral = deepcopy(record)
    for key in _RUNTIME_DERIVED_RECORD_KEYS:
        neutral.pop(key, None)
    return neutral


def _publish_clinical_event(
    patient_id: int,
    event_type: str,
    event_data: dict | None = None,
) -> None:
    """
    Publish a clinical event to the AI event bus.

    Completely silent — any failure is swallowed. Only fires when
    ENABLE_EVENT_BUS feature flag is ON (default OFF).
    """
    try:
        from prostanet.shared.feature_flags import resolve_feature_flags
        if not resolve_feature_flags().get("ENABLE_EVENT_BUS"):
            return
        from prostanet.agents.event_bus import get_event_bus
        bus = get_event_bus()
        bus.publish(event_type, {"patient_id": patient_id, **(event_data or {})})
    except Exception:
        pass  # Event bus is never-fail


def _connect(*, write=False, timeout=SQLITE_CONNECT_TIMEOUT_SEC):
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    if write:
        conn.execute(f"PRAGMA journal_mode = {SQLITE_WRITE_JOURNAL_MODE}")
        conn.execute(f"PRAGMA synchronous = {SQLITE_WRITE_SYNCHRONOUS}")
    return conn


def _close_connection_quietly(conn):
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def get_db_connection(*, write=False):
    return _connect(write=write)


def get_full_record(nss_or_id):
    return get_patient_full_record(nss_or_id)


def _is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


def _is_present(value):
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _row_to_dict(row, columns=None):
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if columns:
        try:
            return {column: row[idx] for idx, column in enumerate(columns)}
        except (TypeError, IndexError):
            pass
    return dict(row)


def _canonical_value_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _canonical_value_text(value):
    if isinstance(value, (dict, list)):
        return _canonical_value_json(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _parse_iso_date(value):
    if value in (None, "", "None"):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _fact_row_priority(row):
    return (
        certainty_rank(row.get("certainty_tier")),
        _parse_iso_date(row.get("source_date")) or datetime.min,
        _parse_iso_date(row.get("observed_at")) or datetime.min,
        int(row.get("id") or 0),
    )


def _append_patient_fact_lineage_event(
    cursor,
    patient_id,
    fact_key,
    event_type,
    *,
    source_fact_id=None,
    target_fact_id=None,
    event_note="",
    payload=None,
):
    cursor.execute(
        '''
        INSERT INTO patient_fact_lineage_events (
            patient_id, fact_key, event_type, source_fact_id, target_fact_id, event_note, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            fact_key,
            event_type,
            source_fact_id,
            target_fact_id,
            event_note or "",
            _json_blob(payload or {}),
        ),
    )


def _record_patient_fact_conflict(
    cursor,
    patient_id,
    fact_key,
    existing_fact,
    candidate_fact,
    *,
    severity="moderate",
    resolution_status="open",
    resolution_reason="",
):
    cursor.execute(
        '''
        INSERT INTO patient_fact_conflicts (
            patient_id, fact_key, existing_fact_id, candidate_fact_id, existing_value_text, candidate_value_text,
            severity, resolution_status, resolution_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            fact_key,
            existing_fact.get("id"),
            candidate_fact.get("id"),
            existing_fact.get("normalized_value_text") or "",
            candidate_fact.get("normalized_value_text") or "",
            severity,
            resolution_status,
            resolution_reason or "",
        ),
    )


# EPIC 22b.7 — Patient Twin OS recompute triggers.
# Fact keys that materially change personalized regimen rankings, AS eligibility,
# or salvage decision. When ANY of these is persisted (created or superseded),
# we emit a `twin_recompute_triggered` lineage event AND bump the in-memory
# marker so build_patient_profile_view_model can short-circuit cached entries
# and force a fresh patient_twin_os build on the next render.
TWIN_RECOMPUTE_TRIGGER_KEYS: frozenset[str] = frozenset({
    # Precision pathway (drives PARP / immunotherapy ranking)
    "hrr_status", "hrr_gene", "msi_status",
    "germline_pathogenic_variant", "somatic_pathogenic_variant",
    # SDM preferences (drives regimen ranking weights)
    "goal_of_care", "decision_tradeoff",
    # PRO baseline (drives toxicity tolerance ranking)
    "baseline_pro", "epic26_urinary_domain", "epic26_sexual_domain",
    "epic26_bowel_domain", "epic26_hormonal_domain",
    # Post-RP pathology (drives salvage timing)
    "gleason_at_rp", "margin_status", "tumor_stage_at_rp",
    # Risk stratification discriminators (drives 6-tier localized routing)
    "percent_positive_cores", "percent_pattern_4",
    # NEPC differentiation (drives platinum vs ARSI routing)
    "small_cell_morphology", "synaptophysin_biopsy_positive",
    "chromogranin_a_value",
})

# Module-level in-memory marker keyed by patient_id → last critical fact mtime
# (epoch seconds). Patient Twin OS readers can compare this against their
# cached view's build timestamp and force rebuild if stale.
# NOT cross-process (single Flask worker) — safe degradation: if marker
# missing, downstream rebuilds anyway on each render.
_PATIENT_TWIN_RECOMPUTE_MARKERS: dict[int, float] = {}


def get_patient_twin_recompute_marker(patient_id: int) -> float:
    """EPIC 22b.7 — return last twin recompute trigger timestamp for patient.

    Returns 0.0 if never triggered. Patient Twin OS uses this to invalidate
    cached regimen rankings when a critical clinical fact arrives.
    """
    try:
        return float(_PATIENT_TWIN_RECOMPUTE_MARKERS.get(int(patient_id), 0.0))
    except (TypeError, ValueError):
        return 0.0


def _persist_patient_clinical_facts(cursor, patient_id, fact_candidates):
    persisted = []
    # EPIC 22b.7 — track if any critical key was persisted in this batch
    # so we emit a single twin_recompute_triggered event at the end (avoids
    # event spam when a multi-field intake form persists 20+ facts at once).
    critical_keys_persisted: list[str] = []
    for candidate in list(fact_candidates or []):
        fact_key = str(candidate.get("fact_key") or "").strip()
        if not fact_key:
            continue
        normalized_value_text = _canonical_value_text(candidate.get("value"))
        value_json = _canonical_value_json(candidate.get("value"))
        candidate_row = {
            "patient_id": int(patient_id),
            "fact_key": fact_key,
            "value_json": value_json,
            "normalized_value_text": normalized_value_text,
            "source_type": candidate.get("source_type") or "derived",
            "source_record_type": candidate.get("source_record_type") or "",
            "source_record_id": candidate.get("source_record_id"),
            "source_date": str(candidate.get("source_date") or ""),
            "observed_at": str(candidate.get("observed_at") or candidate.get("source_date") or ""),
            "state_context": str(candidate.get("state_context") or ""),
            "management_track": str(candidate.get("management_track") or ""),
            "certainty_tier": str(candidate.get("certainty_tier") or "derived"),
            "freshness_status": str(candidate.get("freshness_status") or ""),
            "freshness_expires_at": candidate.get("freshness_expires_at"),
            "clinician_verified": 1 if candidate.get("clinician_verified") else 0,
            "verification_note": str(candidate.get("verification_note") or ""),
        }
        if not candidate_row["freshness_status"]:
            freshness_status, freshness_expires_at = compute_freshness_status(
                fact_key,
                source_date=candidate_row["source_date"],
                observed_at=candidate_row["observed_at"],
            )
            candidate_row["freshness_status"] = freshness_status
            candidate_row["freshness_expires_at"] = freshness_expires_at

        cursor.execute(
            '''
            SELECT * FROM patient_clinical_facts
            WHERE patient_id = ? AND fact_key = ? AND is_active = 1
            ORDER BY updated_at DESC, id DESC
            ''',
            (patient_id, fact_key),
        )
        columns = [column[0] for column in (cursor.description or [])]
        active_rows = [_row_to_dict(row, columns) for row in cursor.fetchall()]
        best_existing = max(active_rows, key=_fact_row_priority) if active_rows else None

        if best_existing and (
            best_existing.get("normalized_value_text") == normalized_value_text
            and str(best_existing.get("certainty_tier") or "") == candidate_row["certainty_tier"]
            and str(best_existing.get("source_date") or "") == candidate_row["source_date"]
            and str(best_existing.get("source_record_type") or "") == candidate_row["source_record_type"]
            and str(best_existing.get("source_record_id") or "") == str(candidate_row["source_record_id"] or "")
        ):
            continue

        incoming_priority = _fact_row_priority(candidate_row)
        existing_priority = _fact_row_priority(best_existing) if best_existing else None
        incoming_is_active = best_existing is None or incoming_priority >= existing_priority

        cursor.execute(
            '''
            INSERT INTO patient_clinical_facts (
                patient_id, fact_key, value_json, normalized_value_text, source_type, source_record_type,
                source_record_id, source_date, observed_at, state_context, management_track, certainty_tier,
                freshness_status, freshness_expires_at, clinician_verified, verification_note, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                fact_key,
                value_json,
                normalized_value_text,
                candidate_row["source_type"],
                candidate_row["source_record_type"],
                candidate_row["source_record_id"],
                candidate_row["source_date"],
                candidate_row["observed_at"],
                candidate_row["state_context"],
                candidate_row["management_track"],
                candidate_row["certainty_tier"],
                candidate_row["freshness_status"],
                candidate_row["freshness_expires_at"],
                candidate_row["clinician_verified"],
                candidate_row["verification_note"],
                1 if incoming_is_active else 0,
            ),
        )
        candidate_row["id"] = cursor.lastrowid
        candidate_row["is_active"] = 1 if incoming_is_active else 0
        persisted.append(candidate_row)
        _append_patient_fact_lineage_event(
            cursor,
            patient_id,
            fact_key,
            "created" if incoming_is_active else "shadowed",
            source_fact_id=candidate_row["id"],
            event_note="Fact canónico persistido desde captura estructurada.",
            payload={"source_type": candidate_row["source_type"], "source_record_type": candidate_row["source_record_type"]},
        )

        if best_existing and best_existing.get("normalized_value_text") != normalized_value_text:
            severity = "critical" if fact_key in {
                "metastatic_stage_resolved",
                "known_cancer_diagnosis",
                "castrate_testosterone_status",
                "gleason_primary",
                "gleason_secondary",
                "isup_grade",
            } else "moderate"
            _record_patient_fact_conflict(
                cursor,
                patient_id,
                fact_key,
                best_existing,
                candidate_row,
                severity=severity,
                resolution_status="resolved" if incoming_is_active else "open",
                resolution_reason="Incoming fact superseded active fact." if incoming_is_active else "Incoming fact quedó en shadow hasta conciliación clínica.",
            )
            _append_patient_fact_lineage_event(
                cursor,
                patient_id,
                fact_key,
                "conflict_detected",
                source_fact_id=best_existing.get("id"),
                target_fact_id=candidate_row["id"],
                event_note="Se detectó colisión entre dos versiones activas del mismo hecho.",
                payload={"existing_value": best_existing.get("normalized_value_text"), "candidate_value": normalized_value_text},
            )

        if incoming_is_active and active_rows:
            for existing in active_rows:
                if existing.get("id") == candidate_row["id"]:
                    continue
                cursor.execute(
                    '''
                    UPDATE patient_clinical_facts
                    SET is_active = 0, superseded_by_fact_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    ''',
                    (candidate_row["id"], existing.get("id")),
                )
                _append_patient_fact_lineage_event(
                    cursor,
                    patient_id,
                    fact_key,
                    "superseded",
                    source_fact_id=existing.get("id"),
                    target_fact_id=candidate_row["id"],
                    event_note="El nuevo fact canónico desplazó la versión previa.",
                )

        # EPIC 22b.7 — accumulate Patient Twin recompute trigger
        if incoming_is_active and fact_key in TWIN_RECOMPUTE_TRIGGER_KEYS:
            critical_keys_persisted.append(fact_key)

    # EPIC 22b.7 — emit a single twin_recompute_triggered event + bump marker
    # after the full batch finishes. Allows Patient Twin OS to detect that
    # personalized regimen rankings need rebuild on next render.
    if critical_keys_persisted:
        try:
            _append_patient_fact_lineage_event(
                cursor,
                patient_id,
                fact_key=",".join(sorted(set(critical_keys_persisted))),
                event_type="twin_recompute_triggered",
                event_note=(
                    "Critical clinical fact(s) persisted → Patient Twin OS "
                    "regimen ranking + AS eligibility + salvage decision recompute."
                ),
                payload={
                    "critical_keys": sorted(set(critical_keys_persisted)),
                    "count": len(set(critical_keys_persisted)),
                },
            )
        except Exception as exc:
            logger.debug("twin_recompute_triggered lineage event failed: %s", exc)
        # Bump in-memory marker for the patient. Patient Twin OS readers
        # can compare against their cached view's build_at to invalidate.
        try:
            import time as _t22
            _PATIENT_TWIN_RECOMPUTE_MARKERS[int(patient_id)] = _t22.time()
        except Exception:
            pass

    return persisted


def _persist_canonical_facts_from_payload(
    cursor,
    patient_id,
    payload,
    *,
    source_type,
    source_record_type,
    source_record_id=None,
    source_date="",
    observed_at="",
    state_context="",
    management_track="",
    certainty_tier="wizard_or_intake",
    clinician_verified=False,
    verification_note="",
):
    fact_candidates = extract_canonical_fact_candidates(
        payload,
        source_type=source_type,
        source_record_type=source_record_type,
        source_record_id=source_record_id,
        source_date=source_date,
        observed_at=observed_at,
        state_context=state_context,
        management_track=management_track,
        certainty_tier=certainty_tier,
        clinician_verified=clinician_verified,
        verification_note=verification_note,
    )
    return _persist_patient_clinical_facts(cursor, patient_id, fact_candidates)


def _persist_verified_document_facts_to_canonical(
    cursor,
    patient_id,
    document_id,
    facts,
    *,
    state_context="",
    management_track="",
    verified_by="clinico",
):
    payload = {}
    source_date = ""
    for item in list(facts or []):
        fact_key = str(item.get("fact_key") or "").strip()
        field_name = str(item.get("field_name") or "").strip()
        payload[fact_key] = item.get("value")
        if field_name:
            payload[field_name] = item.get("value")
        if not source_date:
            source_date = str(item.get("source_date") or "")
    return _persist_canonical_facts_from_payload(
        cursor,
        patient_id,
        payload,
        source_type="source_document",
        source_record_type="verified_document",
        source_record_id=document_id,
        source_date=source_date,
        observed_at=source_date,
        state_context=state_context,
        management_track=management_track,
        certainty_tier="document_verified",
        clinician_verified=True,
        verification_note=f"Documento verificado por {verified_by}",
    )


def get_patient_clinical_facts(patient_id, *, active_only=True):
    conn = _connect()
    cursor = conn.cursor()
    query = "SELECT * FROM patient_clinical_facts WHERE patient_id = ?"
    params = [int(patient_id)]
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY fact_key ASC, updated_at DESC, id DESC"
    cursor.execute(query, params)
    rows = []
    for row in cursor.fetchall():
        item = dict(row)
        item["value"] = _parse_json_blob(item.get("value_json"), None)
        item["clinician_verified"] = bool(item.get("clinician_verified"))
        item["is_active"] = bool(item.get("is_active"))
        rows.append(item)
    conn.close()
    return rows


def get_patient_fact_conflicts(patient_id, *, unresolved_only=False):
    conn = _connect()
    cursor = conn.cursor()
    query = "SELECT * FROM patient_fact_conflicts WHERE patient_id = ?"
    params = [int(patient_id)]
    if unresolved_only:
        query += " AND COALESCE(resolution_status, 'open') NOT IN ('resolved', 'dismissed')"
    query += " ORDER BY updated_at DESC, created_at DESC, id DESC"
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def patient_exists(patient_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM patient_identity WHERE id = ? LIMIT 1", (patient_id,))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        logger.error(f"Error checking patient existence: {e}")
        return False


def resolve_patient_ref(patient_ref):
    try:
        conn = _connect()
        cursor = conn.cursor()
        identity = _resolve_identity_row(cursor, patient_ref)
        conn.close()
        if not identity:
            return None
        return {
            "patient_id": int(identity["id"]),
            "nss": str(identity["nss"] or "").strip(),
            "identity": dict(identity),
            "patient_ref": str(patient_ref),
        }
    except Exception as exc:
        logger.error(f"Error resolving patient reference {patient_ref}: {exc}")
        return None


def patient_exists_ref(patient_ref):
    return resolve_patient_ref(patient_ref) is not None


def get_patient_full_record_by_ref(patient_ref):
    resolved = resolve_patient_ref(patient_ref)
    if not resolved:
        return None
    return get_patient_full_record(resolved["patient_id"])


def delete_patient_profile(nss_or_id):
    conn = _connect()
    cursor = conn.cursor()
    identity = _resolve_identity_row(cursor, nss_or_id)
    if not identity:
        conn.close()
        return False, "Paciente no encontrado"

    patient_id = int(identity["id"])
    nss = str(identity["nss"] or "").strip()
    full_name = str(identity["full_name"] or "").strip()

    # Auditoría #21 (cierre OOS-7): la eliminación de un paciente recorre todas las
    # tablas con columna `patient_id` en orden alfabético, pero algunas tablas
    # hijas (p. ej. `document_extraction_candidates → source_documents`) tienen
    # claves foráneas a filas específicas, no al paciente. Desactivar las FK
    # durante el borrado es el patrón canónico de SQLite para cascadas
    # multi-tabla sin declarar ON DELETE CASCADE en cada esquema. Se reactiva
    # antes de cerrar la conexión para preservar invariantes de futuras
    # operaciones en el mismo pool.
    cursor.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor.execute("SELECT id FROM source_documents WHERE patient_id = ?", (patient_id,))
        document_ids = [int(row["id"]) for row in cursor.fetchall()]
        if document_ids:
            placeholders = ",".join(["?"] * len(document_ids))
            cursor.execute(f"DELETE FROM document_extraction_candidates WHERE document_id IN ({placeholders})", document_ids)
            cursor.execute(f"DELETE FROM document_verification_tasks WHERE document_id IN ({placeholders})", document_ids)
            cursor.execute(f"DELETE FROM verified_document_facts WHERE document_id IN ({placeholders})", document_ids)

        table_names = [
            row["name"]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for table_name in table_names:
            if table_name == "patient_identity":
                continue
            columns = [column["name"] for column in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
            if "patient_id" in columns:
                cursor.execute(f"DELETE FROM {table_name} WHERE patient_id = ?", (patient_id,))

        cursor.execute("DELETE FROM patient_identity WHERE id = ?", (patient_id,))
        conn.commit()
    finally:
        cursor.execute("PRAGMA foreign_keys = ON")
    conn.close()

    patient_dir = _document_store().root / f"patient_{patient_id}"
    if patient_dir.exists():
        shutil.rmtree(patient_dir, ignore_errors=True)

    return True, {
        "patient_id": patient_id,
        "nss": nss,
        "full_name": full_name,
    }


def _parse_json_blob(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _json_blob(value):
    return json.dumps(value, ensure_ascii=False)


_GENERIC_RECOMMENDATION_FAMILIES = {
    "",
    "observation_family",
    "observación / backbone",
    "observacion / backbone",
    "post_rt_salvage",
    "ruta de rescate",
    "salvage",
    "control local / mdt",
    "local_mdt_family",
    "ruta post-rt",
    "confirmación post-rt",
    "confirmacion post-rt",
}


def _normalize_recommendation_family_text(value):
    return str(value or "").strip().lower()


def _is_generic_recommendation_family(value):
    return _normalize_recommendation_family_text(value) in _GENERIC_RECOMMENDATION_FAMILIES


def _should_backfill_recommendation_family(existing_value, candidate_value):
    existing = str(existing_value or "").strip()
    candidate = str(candidate_value or "").strip()
    if not candidate:
        return False
    if not existing:
        return True
    if existing == candidate:
        return False
    if _is_generic_recommendation_family(existing) and not _is_generic_recommendation_family(candidate):
        return True
    return False


def _resolve_identity_row(cursor, nss_or_id):
    cursor.execute("SELECT * FROM patient_identity WHERE nss = ?", (str(nss_or_id),))
    identity = cursor.fetchone()
    if identity:
        return identity
    try:
        patient_id = int(nss_or_id)
    except (TypeError, ValueError):
        return None
    cursor.execute("SELECT * FROM patient_identity WHERE id = ?", (patient_id,))
    return cursor.fetchone()


def _ensure_prior_history_row(cursor, patient_id):
    cursor.execute("SELECT 1 FROM prior_clinical_history WHERE patient_id = ? LIMIT 1", (patient_id,))
    if cursor.fetchone():
        return
    cursor.execute(
        '''
        INSERT INTO prior_clinical_history (
            patient_id, rt_primary_received, rt_primary_dose_gy, rt_metastasis_history,
            prior_docetaxel_cycles, prior_arpi_agent, prior_arpi_duration
        ) VALUES (?, 0, 0, '[]', 0, NULL, 0)
        ''',
        (patient_id,),
    )


def _assessment_longitudinal_snapshot(assessment):
    result = assessment.get("result_snapshot", {}) if assessment else {}
    nccn = result.get("nccn_primary", {})
    report_sections = result.get("report_sections", {})
    structured = report_sections.get("structured_summary", {})
    decision_quality = result.get("decision_quality", {}) or {}
    return {
        "summary": nccn.get("resumen_del_caso") or structured.get("resumen_del_caso") or report_sections.get("summary", ""),
        "current_state": assessment.get("state"),
        "transition_reason": nccn.get("trayectoria_recomendada") or structured.get("trayectoria_recomendada") or report_sections.get("summary", ""),
        "objective_progression": result.get("objective_progression", {}),
        "monitoring_plan": result.get("monitoring_plan", {}),
        "care_overlays": result.get("care_overlays", []),
        "guideline_snapshot": assessment.get("guideline_versions", {}),
        "recommendation_family": decision_quality.get("recommendation_family") or result.get("recommendation_family", ""),
        "state_classification": decision_quality.get("state_classification") or result.get("state") or assessment.get("state"),
        "decision_quality": result.get("decision_quality", {}),
        "validated_algorithms": result.get("validated_algorithms", []),
    }


def _record_patient_state_transition(
    cursor,
    patient_id,
    assessment_id,
    state,
    event_kind,
    management_intent_status,
    transition_reason,
    objective_progression,
    monitoring_plan,
    care_overlays,
    latest_guideline_snapshot,
):
    cursor.execute(
        '''
        INSERT INTO patient_state_timeline (
            patient_id, assessment_id, state, event_kind, management_intent_status, transition_reason,
            objective_progression_json, monitoring_plan_json, care_overlays_json,
            latest_guideline_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            assessment_id,
            state,
            event_kind,
            management_intent_status,
            transition_reason,
            _json_blob(objective_progression or {}),
            _json_blob(monitoring_plan or {}),
            _json_blob(care_overlays or []),
            _json_blob(latest_guideline_snapshot or {}),
        ),
    )


def _hydrate_timeline_rows(rows):
    timeline = []
    for row in rows:
        item = dict(row)
        item["objective_progression"] = _parse_json_blob(item.pop("objective_progression_json", None), {})
        item["monitoring_plan"] = _parse_json_blob(item.pop("monitoring_plan_json", None), {})
        item["care_overlays"] = _parse_json_blob(item.pop("care_overlays_json", None), [])
        item["latest_guideline_snapshot"] = _parse_json_blob(item.pop("latest_guideline_snapshot_json", None), {})
        item["event_kind"] = item.get("event_kind") or "recommendation_generated"
        item["management_intent_status"] = item.get("management_intent_status") or "candidate"
        timeline.append(item)
    return timeline


def _decorate_prior_history(prior_history):
    history = dict(prior_history) if prior_history else {}
    if not history:
        return {}
    history["rt_metastasis_history"] = _parse_json_blob(history.get("rt_metastasis_history"), [])
    history["objective_progression"] = _parse_json_blob(history.get("objective_progression_json"), {})
    history["monitoring_plan"] = _parse_json_blob(history.get("monitoring_plan_json"), {})
    history["care_overlays"] = _parse_json_blob(history.get("care_overlays_json"), [])
    history["latest_guideline_snapshot"] = _parse_json_blob(history.get("latest_guideline_snapshot_json"), {})
    history["management_intent_status"] = history.get("management_intent_status") or "candidate"
    return history


def _hydrate_followup_rows(rows):
    visits = []
    for row in rows:
        item = dict(row)
        item["toxicity"] = _parse_json_blob(item.pop("toxicity_events", None), {})
        item["metabolic"] = _parse_json_blob(item.pop("metabolic_panel", None), {})
        item["skeletal"] = _parse_json_blob(item.pop("skeletal_events", None), {})
        item["visit_bundle"] = _parse_json_blob(item.pop("visit_bundle_json", None), {})
        item["agenda_context"] = _parse_json_blob(item.pop("agenda_context_json", None), {})
        item["metastatic_profile"] = _parse_json_blob(item.get("metastatic_profile_json"), {})
        visits.append(item)
    return visits


def _hydrate_treatment_rows(rows):
    treatments = []
    for row in rows:
        item = dict(row)
        regimen = _parse_json_blob(item.get("regimen_json"), {})
        item["regimen"] = regimen
        if not _is_present(item.get("line_of_therapy")) and _is_present(regimen.get("line_of_therapy_number")):
            item["line_of_therapy"] = regimen.get("line_of_therapy_number")
        item["line_of_therapy_number"] = item.get("line_of_therapy")
        item["line_of_therapy_context"] = (
            item.get("line_of_therapy_context")
            or regimen.get("line_of_therapy_context")
            or regimen.get("mcrpc_line_context")
            or ""
        )
        item["drug_scheme"] = normalize_regimen_code(item.get("drug_scheme"))
        hydrated_label = str(regimen.get("drug_scheme_label") or "").strip()
        if hydrated_label in {"[object Object]", "[object object]"}:
            hydrated_label = ""
        item["drug_scheme_label"] = hydrated_label or regimen_label(item.get("drug_scheme"))
        treatments.append(item)
    return treatments


def _hydrate_agenda_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["required_inputs"] = _parse_json_blob(item.pop("required_inputs_json", None), [])
        item["completion_rule"] = _parse_json_blob(item.pop("completion_rule_json", None), {})
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        item["comparator_basis"] = _parse_json_blob(item.pop("comparator_basis_json", None), [])
        item["blockers"] = _parse_json_blob(item.pop("blockers_json", None), [])
        item["reasoning"] = _parse_json_blob(item.pop("reasoning_json", None), [])
        item["decision_targets"] = _parse_json_blob(item.pop("decision_targets_json", None), [])
        item["panel_targets"] = _parse_json_blob(item.pop("panel_targets_json", None), [])
        item["write_targets"] = _parse_json_blob(item.pop("write_targets_json", None), [])
        item["form_scope"] = _parse_json_blob(item.pop("form_scope_json", None), {})
        try:
            from prostanet.domains.patient_tracking.followup_agenda import resolve_agenda_item_capture_contract

            contract = resolve_agenda_item_capture_contract(item)
        except Exception:
            contract = {}
        item["capture_fields"] = list(contract.get("capture_fields") or item.get("capture_fields") or [])
        item["derived_requirements"] = list(contract.get("derived_requirements") or item.get("derived_requirements") or [])
        items.append(item)
    return items


def _hydrate_scheduled_event_rows(rows):
    events = []
    today_iso = date.today().isoformat()
    for row in rows:
        item = dict(row)
        item["completed"] = bool(item.get("completed"))
        item["overdue_alert_sent"] = bool(item.get("overdue_alert_sent"))
        item["plan_key"] = item.get("plan_key") or ""
        item["ideal_due_at"] = str(item.get("ideal_due_at") or item.get("due_date") or "")[:10]
        item["scheduled_due_at"] = str(item.get("scheduled_due_at") or item.get("due_date") or "")[:10]
        item["delay_days"] = int(item.get("delay_days") or 0)
        item["completed_at"] = str(item.get("completed_date") or item.get("performed_date") or "")[:10]
        due_date = str(item.get("scheduled_due_at") or item.get("due_date") or "")[:10]
        completion_status = str(item.get("completion_status") or "").strip()
        if not completion_status:
            if item["completed_at"] and due_date:
                completion_status = "completed_on_time" if item["completed_at"] <= due_date else "completed_late"
            elif item["completed_at"]:
                completion_status = "completed_on_time"
            elif due_date == today_iso:
                completion_status = "due_today"
            elif due_date and due_date < today_iso:
                completion_status = "missed"
            else:
                completion_status = "scheduled"
        item["completion_status"] = completion_status
        item["completion_source"] = item.get("completion_source") or ("stage_visit" if item.get("completed_visit_id") else "")
        if item.get("days_late") in (None, ""):
            if item["completed_at"] and due_date and item["completed_at"] > due_date:
                item["days_late"] = (datetime.fromisoformat(item["completed_at"]) - datetime.fromisoformat(due_date)).days
            elif completion_status == "missed" and due_date:
                item["days_late"] = (datetime.fromisoformat(today_iso) - datetime.fromisoformat(due_date)).days
            else:
                item["days_late"] = 0
        if completion_status in {"completed_on_time", "completed_late"}:
            item["status"] = "completed"
        elif completion_status == "missed":
            item["status"] = "overdue"
        elif completion_status == "due_today":
            item["status"] = "due_today"
        else:
            item["status"] = "scheduled"
        events.append(item)
    return events


def _hydrate_alert_rows(rows):
    alerts = []
    for row in rows:
        item = dict(row)
        payload = _parse_json_blob(item.get("data_json"), {})
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key not in {"id", "patient_id"}:
                    item[key] = value
        item["message"] = item.get("message") or item.get("description") or ""
        item["category"] = item.get("category") or item.get("alert_type") or ""
        if not item.get("decision_domain") and isinstance(payload, dict):
            item["decision_domain"] = payload.get("decision_domain", "")
        item["detail_items"] = item.get("detail_items") or (payload.get("detail_items", []) if isinstance(payload, dict) else [])
        alerts.append(item)
    return alerts


def _hydrate_response_assessment_rows(rows):
    assessments = []
    for row in rows:
        item = dict(row)
        item["clinical_benefit"] = bool(item.get("clinical_benefit"))
        item["details"] = _parse_json_blob(item.pop("details_json", None), {})
        assessments.append(item)
    return assessments


def _parse_biomarker_lab_source(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    if text.startswith("intake:"):
        parts = text.split(":", 3)
        return {
            "entry_origin": "intake_registration",
            "context": parts[1] if len(parts) > 1 else "",
            "assay_type": parts[2] if len(parts) > 2 else "",
            "source": parts[3] if len(parts) > 3 else "ingreso_inicial",
        }
    if text == "follow_up_visit":
        return {
            "entry_origin": "follow_up_visit",
            "source": "seguimiento_clinico",
        }
    return {"source": text}


def _hydrate_biomarker_rows(rows):
    hydrated = []
    for row in rows:
        item = dict(row)
        metadata = _parse_biomarker_lab_source(item.get("lab_source"))
        item["source_metadata"] = metadata
        item["source"] = metadata.get("source") or item.get("lab_source") or ""
        item["entry_origin"] = metadata.get("entry_origin") or ""
        item["assay_type"] = metadata.get("assay_type") or ""
        item["context"] = metadata.get("context") or ""
        item["unit"] = item.get("unit") or metadata.get("unit") or ""
        item["line_of_therapy_number"] = metadata.get("line_of_therapy_number")
        item["line_of_therapy_context"] = metadata.get("line_of_therapy_context") or ""
        hydrated.append(item)
    return hydrated


def _hydrate_lesion_rows(tracking_rows, measurement_rows):
    measurements_by_lesion = {}
    flat_measurements = []
    for row in measurement_rows:
        item = dict(row)
        measurements_by_lesion.setdefault(item.get("lesion_id"), []).append(item)
        flat_measurements.append(item)
    lesions = []
    for row in tracking_rows:
        lesion = dict(row)
        lesion["measurements"] = measurements_by_lesion.get(lesion.get("id"), [])
        lesions.append(lesion)
    return lesions, flat_measurements


def _derive_psa_series(biomarker_rows, follow_ups, baseline, identity):
    psa_rows = [row for row in biomarker_rows if str(row.get("biomarker_type", "")).upper() == "PSA"]
    if psa_rows:
        return [
            {
                "sample_date": row.get("sample_date"),
                "value": row.get("value"),
                "source": row.get("source"),
                "entry_origin": row.get("entry_origin"),
                "context": row.get("context"),
                "assay_type": row.get("assay_type"),
                "line_of_therapy_number": row.get("line_of_therapy_number"),
                "line_of_therapy_context": row.get("line_of_therapy_context"),
            }
            for row in psa_rows
            if _is_present(row.get("sample_date")) and row.get("value") is not None
        ]
    followup_points = [
        {"sample_date": visit.get("visit_date"), "value": visit.get("psa_current")}
        for visit in follow_ups
        if _is_present(visit.get("visit_date")) and visit.get("psa_current") is not None
    ]
    if followup_points:
        return followup_points
    diagnosis_date = (identity or {}).get("diagnosis_date")
    baseline_psa = (baseline or {}).get("baseline_psa")
    if _is_present(diagnosis_date) and baseline_psa is not None:
        return [{"sample_date": diagnosis_date, "value": baseline_psa}]
    return []


def _derive_testosterone_series(biomarker_rows, follow_ups, baseline, identity):
    testosterone_rows = [
        row
        for row in biomarker_rows
        if str(row.get("biomarker_type", "")).upper() == "TESTOSTERONA"
    ]
    if testosterone_rows:
        return [
            {
                "sample_date": row.get("sample_date"),
                "value": row.get("value"),
                "source": row.get("source"),
                "entry_origin": row.get("entry_origin"),
                "context": row.get("context"),
                "unit": row.get("unit") or "ng/dL",
                "line_of_therapy_number": row.get("line_of_therapy_number"),
                "line_of_therapy_context": row.get("line_of_therapy_context"),
            }
            for row in testosterone_rows
            if _is_present(row.get("sample_date")) and row.get("value") is not None
        ]
    followup_points = [
        {
            "sample_date": visit.get("visit_date"),
            "value": visit.get("testosterone_current"),
            "source": "seguimiento_clinico",
            "entry_origin": "follow_up_visit",
            "context": str(visit.get("management_track") or visit.get("state_at_visit") or "seguimiento"),
            "unit": "ng/dL",
        }
        for visit in follow_ups
        if _is_present(visit.get("visit_date")) and visit.get("testosterone_current") is not None
    ]
    if followup_points:
        return followup_points
    diagnosis_date = (identity or {}).get("diagnosis_date")
    baseline_testosterone = (baseline or {}).get("testosterone_baseline")
    if _is_present(diagnosis_date) and baseline_testosterone is not None:
        return [
            {
                "sample_date": diagnosis_date,
                "value": baseline_testosterone,
                "source": "baseline",
                "entry_origin": "baseline",
                "context": "baseline",
                "unit": "ng/dL",
            }
        ]
    return []


def _normalize_line_of_therapy_number(data):
    for key in ("line_of_therapy_number", "line_of_therapy"):
        value = data.get(key)
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _normalize_line_of_therapy_context(data):
    return (
        data.get("line_of_therapy_context")
        or data.get("mcrpc_line_context")
        or ""
    )


def _hydrate_stage_visit_rows(rows):
    visits = []
    for row in rows:
        item = dict(row)
        item["visit_bundle"] = _parse_json_blob(item.pop("visit_bundle_json", None), {})
        visits.append(item)
    return visits


def _hydrate_provenance_rows(rows):
    provenance = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        provenance.append(item)
    return provenance


def _hydrate_event_rows(rows):
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        item["mcode_focus"] = _parse_json_blob(item.pop("mcode_focus_json", None), {})
        events.append(item)
    return events


def _hydrate_signal_rows(rows):
    signals = []
    for row in rows:
        item = dict(row)
        item["signals"] = _parse_json_blob(item.pop("signals_json", None), [])
        item["critical_missing"] = _parse_json_blob(item.pop("critical_missing_json", None), [])
        item["awaiting_review"] = _parse_json_blob(item.pop("awaiting_review_json", None), [])
        item["active_safety"] = _parse_json_blob(item.pop("active_safety_json", None), [])
        item["next_best_action"] = _parse_json_blob(item.pop("next_best_action_json", None), {})
        item["mcode_projection"] = _parse_json_blob(item.pop("mcode_projection_json", None), {})
        signals.append(item)
    return signals


def _hydrate_outcome_rows(rows):
    outcomes = []
    for row in rows:
        item = dict(row)
        item["provisional"] = bool(item.get("provisional"))
        item["active"] = bool(item.get("active", 1))
        item["blocking_fields"] = _parse_json_blob(item.pop("blocking_fields_json", None), [])
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        outcomes.append(item)
    return outcomes


def _hydrate_adjudication_snapshot_rows(rows):
    snapshots = []
    for row in rows:
        item = dict(row)
        item["current_response_state"] = _parse_json_blob(item.pop("current_response_state_json", None), {})
        item["last_adjudicated_event"] = _parse_json_blob(item.pop("last_adjudicated_event_json", None), {})
        item["pending_adjudications"] = _parse_json_blob(item.pop("pending_adjudications_json", None), [])
        item["outcome_events_summary"] = _parse_json_blob(item.pop("outcome_events_summary_json", None), {})
        item["milestone_plan"] = _parse_json_blob(item.pop("milestone_plan_json", None), [])
        item["outcome_anchor"] = _parse_json_blob(item.pop("outcome_anchor_json", None), {})
        snapshots.append(item)
    return snapshots


def _hydrate_trial_benchmark_snapshot_rows(rows):
    snapshots = []
    for row in rows:
        item = dict(row)
        item["current_trial_profile"] = _parse_json_blob(item.pop("current_trial_profile_json", None), {})
        item["trial_endpoints"] = _parse_json_blob(item.pop("trial_endpoints_json", None), [])
        item["benchmark_snapshot"] = _parse_json_blob(item.pop("benchmark_snapshot_json", None), {})
        snapshots.append(item)
    return snapshots


def _hydrate_transition_rows(rows):
    proposals = []
    for row in rows:
        item = dict(row)
        item["trigger_signals"] = _parse_json_blob(item.pop("trigger_signals_json", None), [])
        item["next_actions"] = _parse_json_blob(item.pop("next_actions_json", None), [])
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        item["requires_more_data_fields"] = _parse_json_blob(item.pop("requires_more_data_fields_json", None), [])
        item["confirmation_status"] = item.get("confirmation_status") or item.get("proposal_status") or "pending"
        proposals.append(item)
    return proposals


def _hydrate_recommendation_audit_rows(rows):
    audits = []
    for row in rows:
        item = dict(row)
        item["outcome_snapshot"] = _parse_json_blob(item.pop("outcome_snapshot_json", None), {})
        audits.append(item)
    return audits


def _hydrate_clinical_decision_capture_rows(rows):
    captures = []
    for row in rows:
        item = dict(row)
        item["tumor_board_required"] = bool(item.get("tumor_board_required"))
        item["shared_with_patient"] = bool(item.get("shared_with_patient"))
        captures.append(item)
    return captures


def _hydrate_tumor_board_outcome_rows(rows):
    outcomes = []
    for row in rows:
        item = dict(row)
        item["required_followup_actions"] = _parse_json_blob(item.pop("required_followup_actions_json", None), [])
        outcomes.append(item)
    return outcomes


def _hydrate_treatment_adverse_event_rows(rows):
    events = []
    for row in rows:
        item = dict(row)
        item["hospitalization"] = bool(item.get("hospitalization"))
        item["dose_modification_triggered"] = bool(item.get("dose_modification_triggered"))
        events.append(item)
    return events


def _hydrate_therapeutic_window_event_rows(rows):
    events = []
    for row in rows:
        item = dict(row)
        item["evidence_used"] = _parse_json_blob(item.pop("evidence_used_json", None), {})
        item["required_fact_keys"] = _parse_json_blob(item.pop("required_fact_keys_json", None), [])
        item["missing_fact_keys"] = _parse_json_blob(item.pop("missing_fact_keys_json", None), [])
        item["opportunity_lost"] = bool(item.get("opportunity_lost"))
        events.append(item)
    return events


def _hydrate_patient_clinical_fact_rows(rows):
    facts = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.get("value_json"), None)
        item["clinician_verified"] = bool(item.get("clinician_verified"))
        item["is_active"] = bool(item.get("is_active"))
        facts.append(item)
    return facts


def _hydrate_patient_fact_lineage_rows(rows):
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        events.append(item)
    return events


def _hydrate_source_document_rows(rows):
    documents = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
        documents.append(item)
    return documents


def _hydrate_document_candidate_rows(rows):
    candidates = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        candidates.append(item)
    return candidates


def _hydrate_document_task_rows(rows):
    tasks = []
    for row in rows:
        item = dict(row)
        item["summary"] = _parse_json_blob(item.pop("summary_json", None), {})
        tasks.append(item)
    return tasks


def _hydrate_voice_session_rows(rows):
    sessions = []
    for row in rows:
        item = dict(row)
        item["session_context"] = _parse_json_blob(item.pop("session_context_json", None), {})
        item["review_payload"] = _parse_json_blob(item.pop("review_payload_json", None), {})
        item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
        sessions.append(item)
    return sessions


def _hydrate_voice_segment_rows(rows):
    segments = []
    for row in rows:
        item = dict(row)
        item["transcript_envelope"] = _parse_json_blob(item.pop("transcript_envelope_json", None), {})
        item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
        segments.append(item)
    return segments


def _hydrate_verified_fact_rows(rows):
    facts = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        facts.append(item)
    return facts


def _coerce_bool(value):
    if value in (None, "", "No aplica"):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "positive", "positivo"}


def _first_nonempty(*values):
    for value in values:
        if _is_present(value):
            return value
    return None


def _domain_source_metadata(source_type="", source_record_id=None):
    return {
        "source_type": source_type or "stage_visit",
        "source_record_id": _safe_int(source_record_id, None),
    }


def _make_session_key(prefix, patient_id, event_date, *parts):
    normalized_parts = [
        re.sub(r"[^a-z0-9]+", "_", str(part or "").strip().lower()).strip("_")
        for part in parts
        if _is_present(part)
    ]
    date_part = str(event_date or "undated")[:10]
    tail = "_".join(part for part in normalized_parts if part)
    return f"{prefix}_{patient_id}_{date_part}" + (f"_{tail}" if tail else "")


def _hydrate_survival_status_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        items.append(item)
    return items


def _hydrate_survival_anchor_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        item["active"] = bool(item.get("active", 1))
        items.append(item)
    return items


def _hydrate_biopsy_session_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["complications"] = _parse_json_blob(item.pop("complications_json", None), [])
        items.append(item)
    return items


def _hydrate_biopsy_core_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["positive"] = bool(item.get("positive", 0))
        if item.get("mri_target_concordance") is not None:
            item["mri_target_concordance"] = bool(item.get("mri_target_concordance"))
        item["cribriform_pattern"] = bool(item.get("cribriform_pattern", 0))
        item["intraductal_carcinoma"] = bool(item.get("intraductal_carcinoma", 0))
        items.append(item)
    return items


def _hydrate_biopsy_target_rows(rows):
    return [dict(row) for row in rows]


def _hydrate_biopsy_link_rows(rows):
    return [dict(row) for row in rows]


def _hydrate_as_enrollment_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["criteria_met"] = _parse_json_blob(item.pop("criteria_met_json", None), {})
        items.append(item)
    return items


def _hydrate_as_schedule_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        items.append(item)
    return items


def _hydrate_as_trigger_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        items.append(item)
    return items


def _hydrate_sre_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["surgical_intervention"] = bool(item.get("surgical_intervention", 0))
        item["resolved"] = bool(item.get("resolved", 0))
        item["evidence_tags"] = _parse_json_blob(item.pop("evidence_tags_json", None), [])
        items.append(item)
    return items


def _hydrate_bma_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        for key in (
            "dental_clearance_done",
            "onj_monitoring",
            "onj_detected",
            "calcium_vitamin_d_supplementation",
        ):
            item[key] = bool(item.get(key, 0))
        if item.get("renal_function_adequate") is not None:
            item["renal_function_adequate"] = bool(item.get("renal_function_adequate"))
        items.append(item)
    return items


def _hydrate_bone_health_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        item["dxa_performed"] = bool(item.get("dxa_performed", 0))
        item["dental_clearance_done"] = bool(item.get("dental_clearance_done", 0))
        item["onj_monitoring"] = bool(item.get("onj_monitoring", 0))
        items.append(item)
    return items


def _hydrate_rt_course_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["concurrent_adt"] = bool(item.get("concurrent_adt", 0))
        item["adt_concurrent"] = bool(item.get("adt_concurrent", 0))
        if item.get("salvage_nodal_coverage") is not None:
            item["salvage_nodal_coverage"] = bool(item.get("salvage_nodal_coverage"))
        item["evidence_tags"] = _parse_json_blob(item.pop("evidence_tags_json", None), [])
        items.append(item)
    return items


def _hydrate_rt_site_rows(rows):
    return [dict(row) for row in rows]


def _hydrate_rt_toxicity_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["evidence_tags"] = _parse_json_blob(item.pop("evidence_tags_json", None), [])
        items.append(item)
    return items


def _build_biopsy_session_summary(session, cores, targets, links):
    systematic = [dict(item) for item in cores if str(item.get("core_type") or "") == "systematic"]
    targeted = [dict(item) for item in cores if str(item.get("core_type") or "") == "targeted"]
    summary = dict(session)
    summary["systematic_cores"] = systematic
    summary["targeted_cores"] = targeted
    summary["targets"] = [dict(item) for item in targets]
    summary["mri_pathology_links"] = [dict(item) for item in links]
    return summary


def _build_active_surveillance_protocol_block(enrollment, schedule_items, trigger_events, conversion_events):
    if not enrollment:
        return {}
    protocol = dict(enrollment)
    protocol["schedule"] = [dict(item) for item in schedule_items]
    protocol["reclassification_triggers"] = [dict(item) for item in trigger_events]
    protocol["conversion_events"] = [dict(item) for item in conversion_events]
    protocol["exit_reason"] = (
        enrollment.get("exit_reason")
        or (conversion_events[-1].get("exit_reason") if conversion_events else None)
    )
    protocol["exit_date"] = (
        enrollment.get("exit_date")
        or (conversion_events[-1].get("conversion_date") if conversion_events else None)
    )
    protocol["exit_treatment"] = (
        enrollment.get("exit_treatment")
        or (conversion_events[-1].get("exit_treatment") if conversion_events else None)
    )
    protocol["confirmatory_biopsy_done"] = any(
        str(item.get("item_type") or "") == "rebiopsy"
        and "confirm" in str(item.get("title") or "").lower()
        and str(item.get("status") or "") == "completed"
        for item in schedule_items
    )
    protocol["confirmatory_biopsy_date"] = next(
        (
            item.get("completed_date")
            for item in schedule_items
            if str(item.get("item_type") or "") == "rebiopsy"
            and "confirm" in str(item.get("title") or "").lower()
            and item.get("completed_date")
        ),
        None,
    )
    protocol["confirmatory_biopsy_due"] = next(
        (
            item.get("due_date")
            for item in schedule_items
            if str(item.get("item_type") or "") == "rebiopsy"
            and "confirm" in str(item.get("title") or "").lower()
        ),
        None,
    )
    return protocol


def _build_skeletal_event_profile_block(sre_events, bma_courses, bone_health_snapshots):
    latest_bma = bma_courses[-1] if bma_courses else {}
    latest_bone = bone_health_snapshots[-1] if bone_health_snapshots else {}
    return {
        "sre_events": [dict(item) for item in sre_events],
        "bone_modifying_agent": dict(latest_bma) if latest_bma else {},
        "bone_health_latest": dict(latest_bone) if latest_bone else {},
        "bone_health_snapshots": [dict(item) for item in bone_health_snapshots],
    }


def _nest_radiotherapy_courses(courses, sites, toxicities):
    site_map = {}
    for site in sites:
        site_map.setdefault(site.get("course_id"), []).append(dict(site))
    toxicity_map = {}
    for toxicity in toxicities:
        toxicity_map.setdefault(toxicity.get("course_id"), []).append(dict(toxicity))
    nested = []
    for course in courses:
        item = dict(course)
        item["mdt_site_details"] = site_map.get(item.get("id"), [])
        item["toxicity"] = toxicity_map.get(item.get("id"), [])
        nested.append(item)
    return nested


def _upsert_patient_identity_survival_fields(cursor, patient_id, status):
    if not status:
        return
    cursor.execute(
        """
        UPDATE patient_identity
        SET vital_status = COALESCE(?, vital_status),
            date_of_death = COALESCE(?, date_of_death),
            cause_of_death = COALESCE(?, cause_of_death),
            last_contact_date = COALESCE(?, last_contact_date),
            last_contact_status = COALESCE(?, last_contact_status),
            death_source = COALESCE(?, death_source)
        WHERE id = ?
        """,
        (
            status.get("vital_status"),
            status.get("date_of_death"),
            status.get("cause_of_death"),
            status.get("last_contact_date"),
            status.get("last_contact_status"),
            status.get("death_source"),
            patient_id,
        ),
    )


def _save_survival_status_update(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, dict) or not any(
        _is_present(data.get(field))
        for field in ("vital_status", "date_of_death", "cause_of_death", "last_contact_date", "last_contact_status", "death_source")
    ):
        return None
    cursor.execute(
        """
        INSERT INTO survival_status_records (
            patient_id, vital_status, date_of_death, cause_of_death, last_contact_date,
            last_contact_status, death_source, source_type, source_record_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            data.get("vital_status") or "alive",
            data.get("date_of_death"),
            data.get("cause_of_death"),
            data.get("last_contact_date"),
            data.get("last_contact_status"),
            data.get("death_source"),
            source_type,
            _safe_int(source_record_id, None),
        ),
    )
    _upsert_patient_identity_survival_fields(cursor, patient_id, data)
    return cursor.lastrowid


def _save_survival_anchor_events(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, list):
        return []
    saved_ids = []
    for event in data:
        if not isinstance(event, dict):
            continue
        anchor_type = str(event.get("anchor_type") or "").strip()
        anchor_date = str(event.get("anchor_date") or "")[:10]
        if not anchor_type or not anchor_date:
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO survival_anchor_events (
                patient_id, anchor_type, anchor_date, anchor_source, source_type, source_record_id, payload_json, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                anchor_type,
                anchor_date,
                event.get("anchor_source") or "",
                source_type,
                _safe_int(source_record_id, None),
                _json_blob(event.get("payload") or {}),
                1 if _coerce_bool(event.get("active", True)) is not False else 0,
            ),
        )
        saved_ids.append(cursor.lastrowid)
    return saved_ids


def _save_structured_biopsy_session(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None, legacy_biopsy_id=None):
    if not isinstance(data, dict):
        return None
    biopsy_date = str(data.get("biopsy_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    biopsy_type = data.get("biopsy_type") or "systematic"
    biopsy_context = data.get("biopsy_context") or "diagnostic"
    session_key = data.get("session_key") or _make_session_key("bx", patient_id, biopsy_date, biopsy_type, biopsy_context)
    systematic_cores = list(data.get("systematic_cores") or [])
    targeted_cores = list(data.get("targeted_cores") or [])
    if not systematic_cores and not targeted_cores and (
        _is_present(data.get("total_cores")) or _is_present(data.get("positive_cores"))
    ):
        total_cores = _safe_int(data.get("total_cores"), 0)
        positive_cores = _safe_int(data.get("positive_cores"), 0)
        for index in range(total_cores):
            systematic_cores.append(
                {
                    "core_id": f"S{index + 1}",
                    "location_sextant": "",
                    "core_type": "systematic",
                    "positive": index < positive_cores,
                    "involvement_pct": data.get("max_core_involvement_pct") if index == 0 and positive_cores > 0 else None,
                    "gleason_primary": data.get("gleason_primary"),
                    "gleason_secondary": data.get("gleason_secondary"),
                    "isup_grade": data.get("isup_grade"),
                    "cribriform_pattern": bool(data.get("patron_cribiforme", 0)),
                    "intraductal_carcinoma": bool(data.get("carcinoma_intraductal", 0)),
                }
            )
    all_cores = [item for item in systematic_cores + targeted_cores if isinstance(item, dict)]
    total_positive = sum(1 for item in all_cores if _coerce_bool(item.get("positive")))
    max_involvement = max(
        (_safe_float(item.get("involvement_pct"), None) for item in all_cores if _safe_float(item.get("involvement_pct"), None) is not None),
        default=None,
    )
    highest_isup = max(
        (_safe_int(item.get("isup_grade"), None) for item in all_cores if _safe_int(item.get("isup_grade"), None) is not None),
        default=None,
    )
    concordant = [
        item for item in targeted_cores
        if isinstance(item, dict) and item.get("mri_target_concordance") is not None
    ]
    targeted_concordance_rate = None
    if concordant:
        targeted_concordance_rate = round(
            sum(1 for item in concordant if _coerce_bool(item.get("mri_target_concordance"))) / len(concordant) * 100,
            1,
        )
    cursor.execute(
        """
        INSERT OR REPLACE INTO biopsy_sessions (
            patient_id, session_key, biopsy_date, biopsy_type, biopsy_route, biopsy_context,
            mri_pirads_at_biopsy, complications_json, total_cores, total_positive,
            highest_isup, max_involvement_pct, targeted_concordance_rate,
            source_type, source_record_id, legacy_biopsy_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            session_key,
            biopsy_date,
            biopsy_type,
            data.get("biopsy_route") or "",
            biopsy_context,
            _safe_int(data.get("mri_pirads_at_biopsy"), None),
            _json_blob(data.get("complications") or []),
            len(all_cores),
            total_positive,
            highest_isup,
            max_involvement,
            targeted_concordance_rate,
            source_type,
            _safe_int(source_record_id, None),
            legacy_biopsy_id,
        ),
    )
    cursor.execute("SELECT id FROM biopsy_sessions WHERE session_key = ?", (session_key,))
    session_row = cursor.fetchone()
    if not session_row:
        return None
    session_id = session_row[0]
    cursor.execute("DELETE FROM biopsy_cores WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM biopsy_targets WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM biopsy_mri_pathology_links WHERE session_id = ?", (session_id,))
    for collection_name, collection in (("systematic", systematic_cores), ("targeted", targeted_cores)):
        for index, core in enumerate(collection or []):
            if not isinstance(core, dict):
                continue
            cursor.execute(
                """
                INSERT INTO biopsy_cores (
                    session_id, core_id, location_sextant, core_type, core_length_mm, tumor_length_mm,
                    involvement_pct, gleason_primary, gleason_secondary, isup_grade,
                    positive, mri_target_concordance, cribriform_pattern, intraductal_carcinoma
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    core.get("core_id") or f"{collection_name[:1].upper()}{index + 1}",
                    core.get("location_sextant") or core.get("location") or "",
                    core.get("core_type") or collection_name,
                    _safe_float(core.get("core_length_mm"), None),
                    _safe_float(core.get("tumor_length_mm"), None),
                    _safe_float(core.get("involvement_pct"), None),
                    _safe_int(core.get("gleason_primary"), None),
                    _safe_int(core.get("gleason_secondary"), None),
                    _safe_int(core.get("isup_grade"), None),
                    1 if _coerce_bool(core.get("positive")) else 0,
                    (
                        None
                        if core.get("mri_target_concordance") is None
                        else (1 if _coerce_bool(core.get("mri_target_concordance")) else 0)
                    ),
                    1 if _coerce_bool(core.get("cribriform_pattern")) else 0,
                    1 if _coerce_bool(core.get("intraductal_carcinoma")) else 0,
                ),
            )
    targets = data.get("targets") or []
    if not targets and targeted_cores:
        grouped = {}
        for core in targeted_cores:
            if not isinstance(core, dict):
                continue
            target_id = core.get("target_id") or core.get("location_sextant") or core.get("core_id") or "target_1"
            grouped.setdefault(target_id, []).append(core)
        targets = []
        for target_id, target_cores in grouped.items():
            concordant_items = [item for item in target_cores if item.get("mri_target_concordance") is not None]
            positive_count = sum(1 for item in target_cores if _coerce_bool(item.get("positive")))
            targets.append(
                {
                    "target_id": target_id,
                    "target_label": target_id,
                    "lesion_location": target_cores[0].get("location_sextant") or target_id,
                    "positive_core_count": positive_count,
                    "total_core_count": len(target_cores),
                    "concordance_status": (
                        "concordant"
                        if concordant_items and any(_coerce_bool(item.get("mri_target_concordance")) for item in concordant_items)
                        else "discordant" if concordant_items else ""
                    ),
                }
            )
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = target.get("target_id") or target.get("target_label") or target.get("lesion_location") or ""
        if not target_id:
            continue
        cursor.execute(
            """
            INSERT INTO biopsy_targets (
                session_id, target_id, target_label, pirads_score, lesion_location,
                positive_core_count, total_core_count, concordance_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                target_id,
                target.get("target_label") or target_id,
                _safe_int(target.get("pirads_score"), None),
                target.get("lesion_location") or "",
                _safe_int(target.get("positive_core_count"), 0),
                _safe_int(target.get("total_core_count"), 0),
                target.get("concordance_status") or "",
                target.get("notes") or "",
            ),
        )
    for link in data.get("mri_pathology_links") or []:
        if not isinstance(link, dict):
            continue
        cursor.execute(
            """
            INSERT INTO biopsy_mri_pathology_links (
                session_id, target_id, lesion_location, pathology_location, concordance_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                link.get("target_id") or "",
                link.get("lesion_location") or "",
                link.get("pathology_location") or "",
                link.get("concordance_status") or "",
                link.get("notes") or "",
            ),
        )
    return session_id


def _save_active_surveillance_update(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, dict):
        return None
    enrollment_date = str(data.get("enrollment_date") or data.get("protocol_start_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    protocol = data.get("protocol") or data.get("enrollment_protocol") or "NCCN_very_low"
    cursor.execute(
        """
        SELECT id FROM as_enrollments
        WHERE patient_id = ? AND current_status = 'active'
        ORDER BY enrollment_date DESC, id DESC LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    enrollment_id = row[0] if row else None
    if enrollment_id is None:
        cursor.execute(
            """
            INSERT INTO as_enrollments (
                patient_id, enrollment_date, enrollment_protocol, baseline_biopsy_ref,
                criteria_met_json, current_status, source_type, source_record_id,
                exit_date, exit_reason, exit_treatment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                enrollment_date,
                protocol,
                _safe_int(data.get("baseline_biopsy_ref"), None),
                _json_blob(data.get("criteria_met") or {}),
                data.get("current_status") or data.get("status") or "active",
                source_type,
                _safe_int(source_record_id, None),
                data.get("exit_date"),
                data.get("exit_reason"),
                data.get("exit_treatment"),
            ),
        )
        enrollment_id = cursor.lastrowid
    else:
        cursor.execute(
            """
            UPDATE as_enrollments
            SET enrollment_protocol = COALESCE(?, enrollment_protocol),
                baseline_biopsy_ref = COALESCE(?, baseline_biopsy_ref),
                criteria_met_json = COALESCE(?, criteria_met_json),
                current_status = COALESCE(?, current_status),
                exit_date = COALESCE(?, exit_date),
                exit_reason = COALESCE(?, exit_reason),
                exit_treatment = COALESCE(?, exit_treatment),
                source_type = COALESCE(?, source_type),
                source_record_id = COALESCE(?, source_record_id)
            WHERE id = ?
            """,
            (
                data.get("protocol") or data.get("enrollment_protocol"),
                _safe_int(data.get("baseline_biopsy_ref"), None),
                _json_blob(data.get("criteria_met") or {}) if data.get("criteria_met") else None,
                data.get("current_status") or data.get("status"),
                data.get("exit_date"),
                data.get("exit_reason"),
                data.get("exit_treatment"),
                source_type,
                _safe_int(source_record_id, None),
                enrollment_id,
            ),
        )
    for item in data.get("schedule_items") or data.get("schedule") or []:
        if not isinstance(item, dict):
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO as_schedule_items (
                patient_id, enrollment_id, item_type, title, due_date, interval_months,
                status, completed_date, priority, evidence_basis_json, source_type, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                enrollment_id,
                item.get("item_type") or "",
                item.get("title") or item.get("item_type") or "AS follow-up",
                item.get("due_date") or "",
                _safe_int(item.get("interval_months"), 0),
                item.get("status") or "scheduled",
                item.get("completed_date") or "",
                item.get("priority") or "routine",
                _json_blob(item.get("evidence_basis") or []),
                source_type,
                _safe_int(source_record_id, None),
            ),
        )
    for trigger in data.get("trigger_events") or data.get("reclassification_triggers") or []:
        if not isinstance(trigger, dict):
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO as_trigger_events (
                patient_id, enrollment_id, trigger_type, detected_date, detail,
                severity, recommended_action, evidence_basis_json, source_type, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                enrollment_id,
                trigger.get("trigger_type") or "",
                trigger.get("detected_date") or trigger.get("trigger_date") or enrollment_date,
                trigger.get("detail") or "",
                trigger.get("severity") or "",
                trigger.get("recommended_action") or "",
                _json_blob(trigger.get("evidence_basis") or trigger.get("evidence_tags") or []),
                source_type,
                _safe_int(source_record_id, None),
            ),
        )
    conversion_events = data.get("conversion_events") or []
    if data.get("exit_reason") or data.get("exit_treatment"):
        conversion_events = [
            {
                "conversion_date": data.get("exit_date") or enrollment_date,
                "exit_reason": data.get("exit_reason"),
                "exit_treatment": data.get("exit_treatment"),
            },
            *conversion_events,
        ]
    for event in conversion_events:
        if not isinstance(event, dict):
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO as_conversion_events (
                patient_id, enrollment_id, conversion_date, exit_reason, exit_treatment, source_type, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                enrollment_id,
                event.get("conversion_date") or enrollment_date,
                event.get("exit_reason") or "",
                event.get("exit_treatment") or "",
                source_type,
                _safe_int(source_record_id, None),
            ),
        )
    return enrollment_id


def _save_skeletal_events_structured(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, (list, dict)):
        return []
    events = data.get("events") if isinstance(data, dict) else data
    saved_ids = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "").strip()
        event_date = str(event.get("event_date") or "")[:10]
        if not event_type or not event_date:
            continue
        cursor.execute(
            """
            INSERT OR REPLACE INTO skeletal_related_events (
                patient_id, event_type, event_date, site, intervention, surgical_intervention,
                rt_dose_gy, rt_fractions, details, severity, resolved, evidence_tags_json,
                source_type, source_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                event_type,
                event_date,
                event.get("site") or "",
                event.get("intervention") or "",
                1 if _coerce_bool(event.get("surgical_intervention")) else 0,
                _safe_float(event.get("rt_dose_gy"), None),
                _safe_int(event.get("rt_fractions"), None),
                event.get("details") or "",
                event.get("severity") or "standard",
                1 if _coerce_bool(event.get("resolved")) else 0,
                _json_blob(event.get("evidence_tags") or []),
                source_type,
                _safe_int(source_record_id, None),
            ),
        )
        saved_ids.append(cursor.lastrowid)
    return saved_ids


def _save_bone_modifying_agent_course(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, dict) or not _is_present(data.get("agent")):
        return None
    cursor.execute(
        """
        INSERT INTO bone_modifying_agent_courses (
            patient_id, agent, start_date, end_date, frequency, dental_clearance_done,
            dental_clearance_date, last_dental_evaluation, onj_monitoring, onj_detected,
            calcium_vitamin_d_supplementation, renal_function_adequate, last_renal_check_date,
            doses_administered, notes, source_type, source_record_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            data.get("agent"),
            data.get("start_date") or "",
            data.get("end_date"),
            data.get("frequency") or "",
            1 if _coerce_bool(data.get("dental_clearance_done")) else 0,
            data.get("dental_clearance_date"),
            data.get("last_dental_evaluation"),
            1 if _coerce_bool(data.get("onj_monitoring")) else 0,
            1 if _coerce_bool(data.get("onj_detected")) else 0,
            1 if _coerce_bool(data.get("calcium_vitamin_d_supplementation")) else 0,
            None if data.get("renal_function_adequate") is None else (1 if _coerce_bool(data.get("renal_function_adequate")) else 0),
            data.get("last_renal_check_date"),
            _safe_int(data.get("doses_administered"), 0),
            data.get("notes") or "",
            source_type,
            _safe_int(source_record_id, None),
        ),
    )
    return cursor.lastrowid


def _save_bone_health_snapshot(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None):
    if not isinstance(data, dict) or not any(
        _is_present(data.get(field))
        for field in ("snapshot_date", "worst_t_score", "frax_major_pct", "frax_hip_pct", "vitamin_d_level", "calcium_level")
    ):
        return None
    cursor.execute(
        """
        INSERT INTO bone_health_snapshots (
            patient_id, snapshot_date, dxa_performed, worst_t_score, frax_major_pct, frax_hip_pct,
            vitamin_d_level, calcium_level, creatinine, dental_clearance_done, onj_monitoring,
            payload_json, source_type, source_record_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            data.get("snapshot_date") or datetime.now().strftime("%Y-%m-%d"),
            1 if _coerce_bool(data.get("dxa_performed")) else 0,
            _safe_float(data.get("worst_t_score"), None),
            _safe_float(data.get("frax_major_pct"), None),
            _safe_float(data.get("frax_hip_pct"), None),
            _safe_float(data.get("vitamin_d_level"), None),
            _safe_float(data.get("calcium_level"), None),
            _safe_float(data.get("creatinine"), None),
            1 if _coerce_bool(data.get("dental_clearance_done")) else 0,
            1 if _coerce_bool(data.get("onj_monitoring")) else 0,
            _json_blob(data),
            source_type,
            _safe_int(source_record_id, None),
        ),
    )
    return cursor.lastrowid


def _save_radiotherapy_course_detailed(cursor, patient_id, data, *, source_type="stage_visit", source_record_id=None, legacy_radiation_id=None):
    if not isinstance(data, dict):
        return None
    start_date = str(data.get("rt_start_date") or data.get("rt_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    course_key = data.get("course_key") or _make_session_key("rt", patient_id, start_date, data.get("rt_intent"), data.get("modality"))
    cursor.execute(
        """
        INSERT OR REPLACE INTO radiotherapy_courses (
            patient_id, course_key, rt_intent, modality, target_volume, total_dose_gy, fractions,
            dose_per_fraction_gy, boost_dose_gy, boost_technique, rt_start_date, rt_end_date,
            concurrent_adt, adt_neoadjuvant_months, adt_concurrent, adt_adjuvant_months, adt_total_planned_months,
            salvage_psa_at_start, salvage_pre_imaging, salvage_nodal_coverage, mdt_sites_treated,
            notes, evidence_tags_json, source_type, source_record_id, legacy_radiation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            course_key,
            data.get("rt_intent") or data.get("rt_context") or "",
            data.get("modality") or data.get("rt_technique") or "",
            data.get("target_volume") or data.get("target") or "",
            _safe_float(data.get("total_dose_gy"), None),
            _safe_int(data.get("fractions"), None),
            _safe_float(data.get("dose_per_fraction_gy"), None),
            _safe_float(data.get("boost_dose_gy"), None),
            data.get("boost_technique"),
            start_date,
            data.get("rt_end_date") or data.get("rt_date"),
            1 if _coerce_bool(data.get("concurrent_adt")) else 0,
            _safe_float(data.get("adt_neoadjuvant_months"), None),
            1 if _coerce_bool(data.get("adt_concurrent")) else 0,
            _safe_float(data.get("adt_adjuvant_months"), None),
            _safe_float(data.get("adt_total_planned_months"), None),
            _safe_float(data.get("salvage_psa_at_start"), None),
            data.get("salvage_pre_imaging"),
            None if data.get("salvage_nodal_coverage") is None else (1 if _coerce_bool(data.get("salvage_nodal_coverage")) else 0),
            _safe_int(data.get("mdt_sites_treated"), None),
            data.get("notes") or "",
            _json_blob(data.get("evidence_tags") or []),
            source_type,
            _safe_int(source_record_id, None),
            legacy_radiation_id,
        ),
    )
    cursor.execute("SELECT id FROM radiotherapy_courses WHERE course_key = ?", (course_key,))
    row = cursor.fetchone()
    if not row:
        return None
    course_id = row[0]
    cursor.execute("DELETE FROM radiotherapy_mdt_sites WHERE course_id = ?", (course_id,))
    cursor.execute("DELETE FROM radiotherapy_toxicities WHERE course_id = ?", (course_id,))
    for site in data.get("mdt_site_details") or []:
        if not isinstance(site, dict):
            continue
        cursor.execute(
            """
            INSERT INTO radiotherapy_mdt_sites (
                course_id, site_location, modality, dose_gy, fractions, dose_per_fraction_gy
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                site.get("site_location") or "",
                site.get("modality") or "",
                _safe_float(site.get("dose_gy"), 0.0),
                _safe_int(site.get("fractions"), 0),
                _safe_float(site.get("dose_per_fraction_gy"), 0.0),
            ),
        )
    for toxicity in data.get("toxicity") or []:
        if not isinstance(toxicity, dict):
            continue
        cursor.execute(
            """
            INSERT INTO radiotherapy_toxicities (
                course_id, domain, phase, grade, details, onset_date, evidence_tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                toxicity.get("domain") or "",
                toxicity.get("phase") or "",
                _safe_int(toxicity.get("grade"), 0),
                toxicity.get("details") or "",
                toxicity.get("onset_date") or "",
                _json_blob(toxicity.get("evidence_tags") or []),
            ),
        )
    return course_id

def init_tracking_db():
    conn = _connect(write=True)
    c = conn.cursor()

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS dashboard_cache_snapshots (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            ttl_seconds INTEGER NOT NULL
        )
        '''
    )
    
    # ── 1. IDENTIDAD Y DEMOGRÁFICOS (NSS) ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nss TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            dob DATE,
            diagnosis_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    for ddl in (
        "ALTER TABLE patient_identity ADD COLUMN vital_status TEXT",
        "ALTER TABLE patient_identity ADD COLUMN date_of_death DATE",
        "ALTER TABLE patient_identity ADD COLUMN cause_of_death TEXT",
        "ALTER TABLE patient_identity ADD COLUMN last_contact_date DATE",
        "ALTER TABLE patient_identity ADD COLUMN last_contact_status TEXT",
        "ALTER TABLE patient_identity ADD COLUMN death_source TEXT",
        # Faubot LXCVI.F.4 — Demographic fields gap closure
        "ALTER TABLE patient_identity ADD COLUMN country TEXT DEFAULT 'México'",
        "ALTER TABLE patient_demographics ADD COLUMN preferred_language TEXT DEFAULT 'es'",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 2. PERFIL CLÍNICO BASAL (Investigación) ──────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS clinical_baseline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            
            -- Biomarcadores Básicos
            baseline_psa REAL,
            testosterone_baseline REAL,
            hemoglobin REAL,
            alp REAL, -- Fosfatasa Alcalina
            ldh REAL,
            albumin REAL,
            
            -- Estadificación
            tnm_stage TEXT,
            gleason_score INTEGER,
            gleason_primary INTEGER,
            gleason_secondary INTEGER,
            gleason_tertiary INTEGER,
            isup_grade INTEGER,
            histology_subtype TEXT,
            clinical_tstage TEXT,
            nodal_status TEXT,
            clinical_stage_group TEXT,
            clinical_risk_group TEXT,
            life_expectancy_years REAL,
            dre_suspicious BOOLEAN DEFAULT 0,
            prior_biopsy_count INTEGER DEFAULT 0,
            local_treatment_consideration TEXT,
            metastasis_site TEXT, -- 'Hueso', 'Visceral', 'Ganglio', 'M0'
            metastasis_count INTEGER,
            m_substage_resolved TEXT,
            metastatic_profile_json TEXT,
            metastasis_assessment_date DATE,
            metastasis_document_source TEXT,
            volume_disease TEXT,  -- 'High' (CHAARTED) vs 'Low'
            ecog_score INTEGER,
            peripheral_neuropathy_grade INTEGER,
            
            -- [NUEVO] Medicina de Precisión & Función Orgánica (Fase 3.1)
            genomic_test_done BOOLEAN DEFAULT 0,
            hrr_status TEXT,        -- 'Positivo', 'Negativo', 'Desconocido'
            msi_status TEXT,        -- 'Estable', 'Inestable'
            child_pugh_score TEXT,  -- 'A', 'B', 'C'
            pain_symptoms TEXT,     -- 'Asintomatico', 'Leve', 'Moderado-Severo'
            
            comorbidities_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE clinical_baseline ADD COLUMN life_expectancy_years REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN dre_suspicious BOOLEAN DEFAULT 0",
        "ALTER TABLE clinical_baseline ADD COLUMN prior_biopsy_count INTEGER DEFAULT 0",
        "ALTER TABLE clinical_baseline ADD COLUMN local_treatment_consideration TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN peripheral_neuropathy_grade INTEGER",
        "ALTER TABLE clinical_baseline ADD COLUMN gleason_primary INTEGER",
        "ALTER TABLE clinical_baseline ADD COLUMN gleason_secondary INTEGER",
        "ALTER TABLE clinical_baseline ADD COLUMN gleason_tertiary INTEGER",
        "ALTER TABLE clinical_baseline ADD COLUMN isup_grade INTEGER",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS follow_up_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            visit_date DATE DEFAULT (DATE('now')),
            
            -- Biomarcadores Evolutivos
            psa_current REAL,
            testosterone_current REAL,
            alp_current REAL,       -- Fosfatasa Alcalina (Nuevo Fase 5)
            ldh_current REAL,       -- Lactato Deshidrogenasa (Nuevo Fase 5)
            albumin_current REAL,   -- Albúmina (Nuevo Fase 5)
            hemoglobin_current REAL,-- Hemoglobina (Nuevo Fase 5)
            
            -- Estado Clínico y PROMs
            ecog_current INTEGER,
            pain_score INTEGER,     -- Escala 0-10 (BPI-SF Item 3)
            
            -- Farmacovigilancia & Toxicidad (CTCAE)
            toxicity_events TEXT,   -- JSON
            metabolic_panel TEXT,   -- JSON
            skeletal_events TEXT,   -- JSON: {'fracture': 0, 'radiation': 0} (Nuevo Fase 5)
            peripheral_neuropathy_grade INTEGER,
            
            -- Tratamiento Actual
            current_treatment TEXT,
            dose_adjustment TEXT,
            
            -- Status
            disease_status TEXT, 
            metastasis_site TEXT,
            metastasis_count INTEGER,
            m_substage_resolved TEXT,
            metastatic_profile_json TEXT,
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    
    # Migration for existing DBs (Idempotent check)
    try:
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN alp_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN ldh_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN albumin_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN hemoglobin_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN ecog_current INTEGER")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN pain_score INTEGER")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN skeletal_events TEXT")
    except sqlite3.OperationalError:
        pass # Columns likely exist or table just created
    for ddl in (
        "ALTER TABLE follow_up_visits ADD COLUMN creatinine_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN cystatin_c_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN bilirubin_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN ast_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN alt_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN ggt_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN glucose_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN opioid_use TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN fatigue_score INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN mini_cog_score INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN weight_kg REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN height_cm REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN bmi_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN weight_loss_6m_kg REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN weight_loss_6m_pct REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN prior_weight_6m_kg REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN exercise_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN nutrition_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN protein_supplements INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN seizure_history INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN dermatitis_history INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN peripheral_neuropathy_grade INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN cv_risk_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN ddi_reviewed INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN hepatic_risk_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN visit_bundle_json TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN visit_type TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN state_at_visit TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN management_track TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN agenda_context_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 3. HISTORIAL TERAPÉUTICO (Longitudinal) ──────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS treatment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            line_of_therapy INTEGER, -- 1, 2, 3...
            
            drug_scheme TEXT, 
            -- Enum: 'ADT_MONO', 'ADT_DOCETAXEL', 'ADT_ENZALUTAMIDE', 'ADT_APALUTAMIDE', etc.
            
            start_date DATE,
            end_date DATE,
            outcome TEXT, -- 'Ongoing', 'Progression', 'Toxicidad'
            
            nadir_psa REAL,
            time_to_nadir_months INTEGER,
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE treatment_history ADD COLUMN regimen_json TEXT",
        "ALTER TABLE treatment_history ADD COLUMN class_exhausted TEXT",
        "ALTER TABLE treatment_history ADD COLUMN discontinuation_reason TEXT",
        "ALTER TABLE treatment_history ADD COLUMN line_of_therapy_context TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── Legacy Table (Mantener compatibilidad) ───────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            source_type TEXT NOT NULL,
            age REAL, psa REAL, gleason_primary INTEGER, gleason_secondary INTEGER,
            clinical_tstage TEXT, num_cores_positive INTEGER, total_cores INTEGER,
            surgical_margin INTEGER, ece_status INTEGER, svi_status INTEGER, lni_status INTEGER,
            ml_prediction TEXT, clinical_scores TEXT, clinical_summary TEXT,
            discordance_alert BOOLEAN, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ── 4. HISTORIAL CLÍNICO PREVIO (Fase 6) ─────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS prior_clinical_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            
            -- Radioterapia
            rt_primary_received BOOLEAN DEFAULT 0,
            rt_primary_dose_gy REAL,
            rt_metastasis_history TEXT, -- JSON [{'site': 'Bone', 'technique': 'SBRT'}]
            
            -- Sistémico Previo
            prior_docetaxel_cycles INTEGER DEFAULT 0,
            prior_arpi_agent TEXT,       -- 'Abiraterona', 'Enzalutamida', etc.
            prior_arpi_duration INTEGER, -- Meses
            latest_assessment_id INTEGER,
            assessment_source TEXT,
            assessment_module TEXT,
            assessment_state TEXT,
            assessment_summary TEXT,
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN latest_assessment_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_source TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_module TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_state TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_summary TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN current_state TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN transition_reason TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN objective_progression_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN monitoring_plan_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN care_overlays_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN latest_guideline_snapshot_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN management_intent_status TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN recommendation_family TEXT")
    except sqlite3.OperationalError:
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # ══  FASE B & C — NUEVAS TABLAS (Expediente Longitudinal + Investigación)
    # ══════════════════════════════════════════════════════════════════════════

    # ── 5. DEMOGRÁFICOS MÉXICO ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_demographics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER UNIQUE,
            estado_residencia TEXT,          -- Estado de la República Mexicana
            seguridad_social TEXT,           -- 'IMSS', 'ISSSTE', 'Seguro Popular', 'Privado'
            escolaridad TEXT,               -- 'Primaria', 'Secundaria', 'Preparatoria', 'Licenciatura', 'Posgrado'
            ocupacion TEXT,
            estado_civil TEXT,
            etnia TEXT DEFAULT 'hispano',
            tabaquismo TEXT DEFAULT 'nunca', -- 'nunca', 'ex_fumador', 'activo_leve', 'activo_moderado', 'activo_severo'
            paquetes_anio REAL DEFAULT 0,
            diabetes_mellitus BOOLEAN DEFAULT 0,
            hipertension BOOLEAN DEFAULT 0,
            sindrome_metabolico BOOLEAN DEFAULT 0,
            actividad_fisica TEXT DEFAULT 'sedentario', -- 'sedentario', 'leve', 'moderado', 'intenso'
            ipss_score INTEGER DEFAULT 0,
            iief5_score INTEGER DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 6. HISTORIA FAMILIAR DETALLADA ──────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS family_history_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            relative_type TEXT,              -- 'Padre', 'Hermano', 'Tío paterno', 'Abuelo', 'Hijo'
            cancer_type TEXT,                -- 'Próstata', 'Mama', 'Ovario', 'Páncreas', 'Colorrectal'
            age_at_diagnosis INTEGER,
            known_mutation TEXT,             -- 'BRCA1', 'BRCA2', 'ATM', 'CHEK2', 'Desconocido'
            deceased BOOLEAN DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 7. ESTUDIOS DE IMAGEN ───────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS imaging_studies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            study_date DATE,
            study_type TEXT,                 -- 'mpMRI', 'PSMA-PET', 'CT', 'Gammagrama', 'US_transrectal'
            -- MRI specific
            pirads_score INTEGER,
            pirads_location TEXT,            -- Zona (PZ, TZ, CZ) y sector
            lesion_size_mm REAL,
            ece_suspicion BOOLEAN DEFAULT 0,
            svi_suspicion BOOLEAN DEFAULT 0,
            precise_score INTEGER,           -- 1-5 para seguimiento en VA
            -- PSMA-PET specific
            psma_result TEXT,                -- 'negativo', 'local', 'ganglionar', 'oseo', 'visceral'
            psma_suv_max REAL,
            psma_radioligand TEXT,
            psma_index_lesion_site TEXT,
            psma_index_lesion_suvmax REAL,
            psma_uptake_pattern TEXT,
            psma_rads_score TEXT,
            conventional_stage_before_psma TEXT,
            psma_stage_after_psma TEXT,
            psma_upstaged_vs_conventional BOOLEAN,
            psma_management_changed BOOLEAN,
            -- Bone scan specific
            bone_scan_result TEXT,            -- 'negativo', 'sospechoso', 'positivo_limitado', 'positivo_extenso'
            bone_lesion_count INTEGER,
            -- General
            findings_json TEXT,              -- JSON libre para hallazgos detallados
            radiologist_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE imaging_studies ADD COLUMN psma_radioligand TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN psma_index_lesion_site TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN psma_index_lesion_suvmax REAL",
        "ALTER TABLE imaging_studies ADD COLUMN psma_uptake_pattern TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN psma_rads_score TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN conventional_stage_before_psma TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN psma_stage_after_psma TEXT",
        "ALTER TABLE imaging_studies ADD COLUMN psma_upstaged_vs_conventional BOOLEAN",
        "ALTER TABLE imaging_studies ADD COLUMN psma_management_changed BOOLEAN",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS mri_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            fact_date DATE,
            mpmri_quality TEXT,
            decision_usable BOOLEAN DEFAULT 0,
            pirads_score INTEGER,
            lesion_location TEXT,
            lesion_size_mm REAL,
            prostate_volume_ml REAL,
            findings_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS diagnostic_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            plan_date DATE DEFAULT (DATE('now')),
            source_state TEXT,
            plan_type TEXT,
            plan_status TEXT,
            management_intent_status TEXT DEFAULT 'candidate',
            plan_summary TEXT,
            recommended_pathway TEXT,
            next_action TEXT,
            risk_calculator_pathway TEXT,
            trigger_conditions_json TEXT,
            evidence_context_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS biopsy_trigger_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            trigger_date DATE DEFAULT (DATE('now')),
            source_state TEXT,
            trigger_reason TEXT,
            priority TEXT,
            planned_biopsy_type TEXT,
            planned_biopsy_route TEXT,
            trigger_status TEXT,
            management_intent_status TEXT DEFAULT 'candidate',
            activation_conditions_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    # ── 8. PERFIL GENÓMICO ──────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS genomic_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            test_date DATE,
            test_type TEXT,                  -- 'Decipher', 'Prolaris', 'OncotypeDX_GPS', 'FoundationOne', 'Panel_HRR'
            -- Decipher
            decipher_score REAL,             -- 0.0 - 1.0
            decipher_risk TEXT,              -- 'Bajo', 'Intermedio', 'Alto'
            -- Prolaris
            prolaris_score REAL,
            -- Oncotype GPS
            gps_score REAL,                  -- 0-100
            -- HRR detallado
            brca1_status TEXT,               -- 'Wild-type', 'Mutado', 'VUS', 'No testado'
            brca2_status TEXT,
            atm_status TEXT,
            chek2_status TEXT,
            palb2_status TEXT,
            cdk12_status TEXT,
            -- Otros biomarcadores
            msi_status TEXT,                 -- 'MSS', 'MSI-H'
            tmb_score REAL,                  -- Mutations/Mb
            ar_v7_status TEXT,               -- 'Positivo', 'Negativo', 'No testado'
            pten_loss BOOLEAN DEFAULT 0,
            tp53_status TEXT,
            -- Resultado general
            hrr_overall TEXT,                -- 'Positivo', 'Negativo', 'Desconocido'
            actionable_findings TEXT,        -- JSON de hallazgos accionables
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 9. DETALLE DE BIOPSIAS ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS biopsy_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            biopsy_date DATE,
            biopsy_type TEXT,                -- 'sistematica', 'fusion', 'combinada', 'transperineal'
            biopsy_context TEXT,             -- 'diagnostica', 'confirmatoria_va', 'seguimiento_va', 'rebiopsia'
            total_cores INTEGER DEFAULT 12,
            positive_cores INTEGER DEFAULT 0,
            max_core_involvement_pct REAL,   -- 0-100
            histology_subtype TEXT,
            -- Gleason
            gleason_primary INTEGER,
            gleason_secondary INTEGER,
            gleason_tertiary INTEGER,
            isup_grade INTEGER,
            -- Patología especial
            patron_cribiforme BOOLEAN DEFAULT 0,
            carcinoma_intraductal BOOLEAN DEFAULT 0,
            perineural_invasion BOOLEAN DEFAULT 0,
            lymphovascular_invasion BOOLEAN DEFAULT 0,
            porcentaje_patron_4 REAL,        -- 0-100
            porcentaje_patron_5 REAL,
            -- Comparación con biopsia previa
            upgrade_from_previous BOOLEAN DEFAULT 0,
            previous_isup INTEGER,
            adverse_histology_variant_type TEXT,
            adverse_histology_variant_detail TEXT,
            pathologist_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE biopsy_details ADD COLUMN adverse_histology_variant_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE biopsy_details ADD COLUMN adverse_histology_variant_detail TEXT")
    except sqlite3.OperationalError:
        pass

    # ── 10. VIGILANCIA ACTIVA (AS) ──────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS active_surveillance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            enrollment_date DATE,
            enrollment_protocol TEXT,        -- 'NCCN_VL', 'NCCN_L', 'PRIAS', 'JHU', 'Custom'
            enrollment_criteria_met TEXT,    -- JSON de criterios cumplidos
            current_status TEXT DEFAULT 'activo', -- 'activo', 'salida_upgrade', 'salida_preferencia', 'salida_progresion', 'salida_ansiedad'
            exit_date DATE,
            exit_reason TEXT,
            exit_treatment TEXT,             -- 'RP', 'RT', 'Focal', 'Otro'
            -- Métricas de seguimiento
            total_biopsies_in_as INTEGER DEFAULT 0,
            total_mri_in_as INTEGER DEFAULT 0,
            months_in_as INTEGER DEFAULT 0,
            last_psa REAL,
            last_psadt_months REAL,
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 11. RECURRENCIA BIOQUÍMICA (BCR) ────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS biochemical_recurrence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            primary_treatment TEXT,          -- 'RP', 'RT', 'Focal'
            primary_treatment_date DATE,
            nadir_psa REAL,
            nadir_date DATE,
            -- BCR detection
            bcr_detected BOOLEAN DEFAULT 0,
            bcr_date DATE,
            bcr_psa REAL,
            bcr_definition TEXT,             -- 'AUA_0.2', 'ASTRO_Phoenix', 'EAU'
            psadt_at_bcr REAL,               -- Meses
            time_to_bcr_months INTEGER,
            -- Salvage treatment
            salvage_treatment TEXT,           -- 'sRT', 'sRT_ADT', 'ADT_only', 'observation'
            salvage_date DATE,
            salvage_response TEXT,            -- 'Completa', 'Parcial', 'Progresion'
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 12. DETALLE QUIRÚRGICO ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS surgical_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            surgery_date DATE,
            surgery_type TEXT,               -- 'RP_abierta', 'RP_laparoscopica', 'RP_robotica', 'focal_HIFU', 'focal_crioterapia'
            nerve_sparing TEXT,              -- 'bilateral', 'unilateral', 'ninguno'
            plnd_performed BOOLEAN DEFAULT 0,
            plnd_type TEXT,                  -- 'limitada', 'extendida', 'superextendida'
            nodes_removed INTEGER DEFAULT 0,
            nodes_positive INTEGER DEFAULT 0,
            -- Patología post-RP
            pathological_gleason_primary INTEGER,
            pathological_gleason_secondary INTEGER,
            pathological_isup INTEGER,
            pathological_stage TEXT,          -- pT2a, pT2b, pT2c, pT3a, pT3b, pT4
            surgical_margin_status BOOLEAN DEFAULT 0,
            margin_location TEXT,            -- 'apex', 'posterolateral', 'base', 'multiple'
            ece_pathological BOOLEAN DEFAULT 0,
            svi_pathological BOOLEAN DEFAULT 0,
            lni_pathological BOOLEAN DEFAULT 0,
            specimen_weight_grams REAL,
            tumor_volume_pct REAL,
            capra_s_score INTEGER,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE surgical_details ADD COLUMN surgical_approach TEXT",
        "ALTER TABLE surgical_details ADD COLUMN continence_status TEXT",
        "ALTER TABLE surgical_details ADD COLUMN potency_status TEXT",
        "ALTER TABLE surgical_details ADD COLUMN pde5i_use INTEGER",
        "ALTER TABLE surgical_details ADD COLUMN pads_per_day INTEGER",
        "ALTER TABLE surgical_details ADD COLUMN recovery_notes TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 13. DETALLE DE RADIOTERAPIA ─────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS radiation_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            rt_date DATE,
            rt_context TEXT,                 -- 'definitiva', 'adyuvante', 'salvamento', 'paliativa', 'SBRT_met'
            rt_technique TEXT,               -- 'IMRT', 'VMAT', 'SBRT', 'Braquiterapia_LDR', 'Braquiterapia_HDR', 'Protones'
            target TEXT,                     -- 'prostata', 'lecho', 'pelvis', 'hueso', 'ganglio'
            total_dose_gy REAL,
            fractions INTEGER,
            dose_per_fraction_gy REAL,
            -- ADT concurrente
            concurrent_adt BOOLEAN DEFAULT 0,
            adt_duration_months INTEGER,
            adt_agent TEXT,                  -- 'LHRH_agonista', 'LHRH_antagonista', 'ARPI'
            -- Toxicidad aguda
            gu_toxicity_grade INTEGER DEFAULT 0,  -- CTCAE 0-4
            gi_toxicity_grade INTEGER DEFAULT 0,
            -- Notas
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE radiation_details ADD COLUMN session_duration_minutes INTEGER",
        "ALTER TABLE radiation_details ADD COLUMN total_duration_days INTEGER",
        "ALTER TABLE radiation_details ADD COLUMN hematuria TEXT",
        "ALTER TABLE radiation_details ADD COLUMN dysuria TEXT",
        "ALTER TABLE radiation_details ADD COLUMN anemia_related TEXT",
        "ALTER TABLE radiation_details ADD COLUMN late_toxicity_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 13B. DOMINIOS CANÓNICOS NORMALIZADOS ───────────────────────────────
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS survival_status_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            vital_status TEXT,
            date_of_death DATE,
            cause_of_death TEXT,
            last_contact_date DATE,
            last_contact_status TEXT,
            death_source TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS survival_anchor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            anchor_type TEXT NOT NULL,
            anchor_date DATE NOT NULL,
            anchor_source TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            payload_json TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, anchor_type, anchor_date, anchor_source)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS biopsy_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            session_key TEXT UNIQUE NOT NULL,
            biopsy_date DATE,
            biopsy_type TEXT,
            biopsy_route TEXT,
            biopsy_context TEXT,
            mri_pirads_at_biopsy INTEGER,
            complications_json TEXT,
            total_cores INTEGER DEFAULT 0,
            total_positive INTEGER DEFAULT 0,
            highest_isup INTEGER,
            max_involvement_pct REAL,
            targeted_concordance_rate REAL,
            source_type TEXT,
            source_record_id INTEGER,
            legacy_biopsy_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS biopsy_cores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            core_id TEXT NOT NULL,
            location_sextant TEXT,
            core_type TEXT,
            core_length_mm REAL,
            tumor_length_mm REAL,
            involvement_pct REAL,
            gleason_primary INTEGER,
            gleason_secondary INTEGER,
            isup_grade INTEGER,
            positive INTEGER DEFAULT 0,
            mri_target_concordance INTEGER,
            cribriform_pattern INTEGER DEFAULT 0,
            intraductal_carcinoma INTEGER DEFAULT 0,
            UNIQUE(session_id, core_id),
            FOREIGN KEY(session_id) REFERENCES biopsy_sessions(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS biopsy_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            target_id TEXT NOT NULL,
            target_label TEXT,
            pirads_score INTEGER,
            lesion_location TEXT,
            positive_core_count INTEGER DEFAULT 0,
            total_core_count INTEGER DEFAULT 0,
            concordance_status TEXT,
            notes TEXT,
            UNIQUE(session_id, target_id),
            FOREIGN KEY(session_id) REFERENCES biopsy_sessions(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS biopsy_mri_pathology_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            target_id TEXT,
            lesion_location TEXT,
            pathology_location TEXT,
            concordance_status TEXT,
            notes TEXT,
            FOREIGN KEY(session_id) REFERENCES biopsy_sessions(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS as_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            enrollment_date DATE,
            enrollment_protocol TEXT,
            baseline_biopsy_ref INTEGER,
            criteria_met_json TEXT,
            current_status TEXT DEFAULT 'active',
            exit_date DATE,
            exit_reason TEXT,
            exit_treatment TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS as_schedule_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            title TEXT,
            due_date DATE,
            interval_months INTEGER DEFAULT 0,
            status TEXT DEFAULT 'scheduled',
            completed_date DATE,
            priority TEXT DEFAULT 'routine',
            evidence_basis_json TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(enrollment_id, item_type, title, due_date),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(enrollment_id) REFERENCES as_enrollments(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS as_trigger_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            trigger_type TEXT NOT NULL,
            detected_date DATE,
            detail TEXT,
            severity TEXT,
            recommended_action TEXT,
            evidence_basis_json TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(enrollment_id, trigger_type, detected_date, detail),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(enrollment_id) REFERENCES as_enrollments(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS as_conversion_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            conversion_date DATE,
            exit_reason TEXT,
            exit_treatment TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(enrollment_id, conversion_date, exit_reason, exit_treatment),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(enrollment_id) REFERENCES as_enrollments(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS skeletal_related_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date DATE NOT NULL,
            site TEXT,
            intervention TEXT,
            surgical_intervention INTEGER DEFAULT 0,
            rt_dose_gy REAL,
            rt_fractions INTEGER,
            details TEXT,
            severity TEXT DEFAULT 'standard',
            resolved INTEGER DEFAULT 0,
            evidence_tags_json TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(patient_id, event_type, event_date, site, intervention),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS bone_modifying_agent_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            agent TEXT NOT NULL,
            start_date DATE,
            end_date DATE,
            frequency TEXT,
            dental_clearance_done INTEGER DEFAULT 0,
            dental_clearance_date DATE,
            last_dental_evaluation DATE,
            onj_monitoring INTEGER DEFAULT 0,
            onj_detected INTEGER DEFAULT 0,
            calcium_vitamin_d_supplementation INTEGER DEFAULT 0,
            renal_function_adequate INTEGER,
            last_renal_check_date DATE,
            doses_administered INTEGER DEFAULT 0,
            notes TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(patient_id, agent, start_date, frequency),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS bone_health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            snapshot_date DATE NOT NULL,
            dxa_performed INTEGER DEFAULT 0,
            worst_t_score REAL,
            frax_major_pct REAL,
            frax_hip_pct REAL,
            vitamin_d_level REAL,
            calcium_level REAL,
            creatinine REAL,
            dental_clearance_done INTEGER DEFAULT 0,
            onj_monitoring INTEGER DEFAULT 0,
            payload_json TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            UNIQUE(patient_id, snapshot_date, worst_t_score, frax_major_pct, frax_hip_pct),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS radiotherapy_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            course_key TEXT UNIQUE NOT NULL,
            rt_intent TEXT,
            modality TEXT,
            target_volume TEXT,
            total_dose_gy REAL,
            fractions INTEGER,
            dose_per_fraction_gy REAL,
            boost_dose_gy REAL,
            boost_technique TEXT,
            rt_start_date DATE,
            rt_end_date DATE,
            concurrent_adt INTEGER DEFAULT 0,
            adt_neoadjuvant_months REAL,
            adt_concurrent INTEGER DEFAULT 0,
            adt_adjuvant_months REAL,
            adt_total_planned_months REAL,
            salvage_psa_at_start REAL,
            salvage_pre_imaging TEXT,
            salvage_nodal_coverage INTEGER,
            mdt_sites_treated INTEGER,
            notes TEXT,
            evidence_tags_json TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            legacy_radiation_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS radiotherapy_mdt_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            site_location TEXT,
            modality TEXT,
            dose_gy REAL,
            fractions INTEGER,
            dose_per_fraction_gy REAL,
            FOREIGN KEY(course_id) REFERENCES radiotherapy_courses(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS radiotherapy_toxicities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            domain TEXT,
            phase TEXT,
            grade INTEGER DEFAULT 0,
            details TEXT,
            onset_date DATE,
            evidence_tags_json TEXT,
            FOREIGN KEY(course_id) REFERENCES radiotherapy_courses(id)
        )
        '''
    )

    # ── 14. PROs (Patient-Reported Outcomes) ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_pros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            assessment_date DATE DEFAULT (DATE('now')),
            -- Urinary
            ipss_total INTEGER,              -- 0-35
            ipss_qol INTEGER,                -- 0-6
            pad_usage INTEGER DEFAULT 0,     -- Pads/día para incontinencia
            -- Sexual
            iief5_score INTEGER,             -- 5-25
            erection_sufficient BOOLEAN DEFAULT 0,
            pde5i_use BOOLEAN DEFAULT 0,
            -- Pain & QoL
            bpi_worst_pain INTEGER,          -- 0-10 (BPI-SF Item 3)
            bpi_average_pain INTEGER,        -- 0-10
            bpi_interference REAL,           -- 0-10 promedio de 7 ítems
            eq5d_index REAL,                 -- -0.5 a 1.0
            eq5d_vas INTEGER,                -- 0-100
            -- Prostate-specific QoL
            fact_p_total REAL,               -- FACT-P score
            fact_p_physical REAL,
            fact_p_social REAL,
            fact_p_emotional REAL,
            fact_p_functional REAL,
            fact_p_prostate REAL,
            facit_fatigue_total INTEGER,
            epic26_urinary_domain REAL,
            epic26_sexual_domain REAL,
            epic26_bowel_domain REAL,
            epic26_hormonal_domain REAL,
            eortc_qlq_c30_global_health REAL,
            eortc_qlq_c30_physical REAL,
            eortc_qlq_c30_role REAL,
            eortc_qlq_c30_emotional REAL,
            eortc_qlq_c30_fatigue REAL,
            eortc_qlq_c30_pain REAL,
            -- Anxiety (AS patients)
            max_acs_score REAL,              -- Memorial Anxiety Scale for Prostate Cancer
            anxiety_score REAL,
            g8_total INTEGER,
            -- Notes
            continence_status TEXT,
            time_to_continence_months INTEGER,
            sexual_recovery_status TEXT,
            time_to_erection_months INTEGER,
            clinician_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 15. MATCHING CON ESTUDIOS PIVOTALES ─────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS pivotal_study_matching (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            evaluation_date DATE DEFAULT (DATE('now')),
            study_name TEXT,
            eligible BOOLEAN,
            eligibility_details TEXT,        -- JSON con criterios cumplidos/no cumplidos
            study_arm TEXT,                  -- 'experimental', 'control'
            expected_outcome TEXT,           -- Resultado esperado basado en el estudio
            applicability_to_patient TEXT,   -- Nota sobre aplicabilidad
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 16. ALERTAS INTELIGENTES ────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS smart_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            alert_key TEXT,
            alert_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT,                 -- 'psa_rising', 'psadt_critical', 'upgrade_biopsy', 'ecog_decline', 'bcr_detected', 'as_exit', 'overdue_visit'
            decision_domain TEXT,
            severity TEXT,                   -- 'info', 'warning', 'critical'
            title TEXT,
            description TEXT,
            data_json TEXT,                  -- JSON con datos relevantes
            source_snapshot_id INTEGER,
            active BOOLEAN DEFAULT 1,
            acknowledged BOOLEAN DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_date TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE smart_alerts ADD COLUMN alert_key TEXT",
        "ALTER TABLE smart_alerts ADD COLUMN decision_domain TEXT",
        "ALTER TABLE smart_alerts ADD COLUMN source_snapshot_id INTEGER",
        "ALTER TABLE smart_alerts ADD COLUMN active BOOLEAN DEFAULT 1",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 17. EVALUACIONES CLÍNICAS MODULARES ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS clinical_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id TEXT NOT NULL,
            state TEXT NOT NULL,
            input_snapshot TEXT NOT NULL,
            result_snapshot TEXT NOT NULL,
            guideline_versions TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            patient_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_state_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            state TEXT NOT NULL,
            event_kind TEXT DEFAULT 'recommendation_generated',
            management_intent_status TEXT DEFAULT 'candidate',
            transition_reason TEXT,
            objective_progression_json TEXT,
            monitoring_plan_json TEXT,
            care_overlays_json TEXT,
            latest_guideline_snapshot_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE patient_state_timeline ADD COLUMN event_kind TEXT DEFAULT 'recommendation_generated'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE patient_state_timeline ADD COLUMN management_intent_status TEXT DEFAULT 'candidate'")
    except sqlite3.OperationalError:
        pass

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS followup_agenda_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            agenda_key TEXT NOT NULL,
            state TEXT NOT NULL,
            management_track TEXT,
            item_type TEXT,
            title TEXT,
            status TEXT,
            priority TEXT,
            due_at DATE,
            window_start DATE,
            window_end DATE,
            required_inputs_json TEXT,
            completion_rule_json TEXT,
            evidence_basis_json TEXT,
            comparator_basis_json TEXT,
            generated_from_event TEXT,
            summary TEXT,
            blockers_json TEXT,
            reasoning_json TEXT,
            decision_targets_json TEXT,
            panel_targets_json TEXT,
            write_targets_json TEXT,
            form_scope_json TEXT,
            completed_at TIMESTAMP,
            visit_record_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, agenda_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    for ddl in (
        "ALTER TABLE followup_agenda_items ADD COLUMN decision_targets_json TEXT",
        "ALTER TABLE followup_agenda_items ADD COLUMN panel_targets_json TEXT",
        "ALTER TABLE followup_agenda_items ADD COLUMN write_targets_json TEXT",
        "ALTER TABLE followup_agenda_items ADD COLUMN form_scope_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS stage_visit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            visit_date DATE DEFAULT (DATE('now')),
            state TEXT NOT NULL,
            management_track TEXT,
            visit_type TEXT,
            visit_bundle_json TEXT,
            derived_followup_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS data_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            visit_record_id INTEGER,
            field_name TEXT NOT NULL,
            value_json TEXT,
            source_type TEXT,
            source_document_id TEXT,
            source_date DATE,
            verified_by TEXT,
            entered_manually BOOLEAN DEFAULT 1,
            stage_context TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(visit_record_id) REFERENCES stage_visit_records(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date DATE DEFAULT (DATE('now')),
            state_context TEXT,
            management_track TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            status TEXT DEFAULT 'recorded',
            payload_json TEXT,
            mcode_focus_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS clinical_signal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL UNIQUE,
            event_id INTEGER,
            state TEXT NOT NULL,
            management_track TEXT,
            ready_to_restage BOOLEAN DEFAULT 0,
            signals_json TEXT,
            critical_missing_json TEXT,
            awaiting_review_json TEXT,
            active_safety_json TEXT,
            next_best_action_json TEXT,
            mcode_projection_json TEXT,
            evidence_basis_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS state_transition_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            proposal_key TEXT NOT NULL,
            event_id INTEGER,
            from_state TEXT NOT NULL,
            from_management_track TEXT,
            target_state TEXT NOT NULL,
            target_management_track TEXT,
            proposal_status TEXT DEFAULT 'open',
            priority TEXT,
            requires_confirmation BOOLEAN DEFAULT 1,
            rationale TEXT,
            trigger_signals_json TEXT,
            next_actions_json TEXT,
            evidence_basis_json TEXT,
            resulting_assessment_id INTEGER,
            confirmation_status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            requires_more_data_fields_json TEXT,
            confirmed_at TIMESTAMP,
            confirmed_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, proposal_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id),
            FOREIGN KEY(resulting_assessment_id) REFERENCES clinical_assessments(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS recommendation_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            event_id INTEGER,
            recommendation_family TEXT,
            recommended_option TEXT,
            selected_option TEXT,
            recommended_confidence TEXT,
            clinician_selected_option TEXT,
            clinician_selected_family TEXT,
            followed_system_recommendation TEXT,
            discordance_reason_category TEXT,
            decision_capture_status TEXT,
            discordance_reason TEXT,
            outcome_snapshot_json TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS clinical_decision_captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            event_id INTEGER,
            state_at_decision TEXT,
            recommended_option TEXT,
            recommended_family TEXT,
            recommended_confidence TEXT,
            clinician_selected_option TEXT,
            clinician_selected_family TEXT,
            followed_system_recommendation TEXT,
            discordance_reason_category TEXT,
            discordance_reason_free_text TEXT,
            patient_preference_driver TEXT,
            cost_access_driver TEXT,
            toxicity_driver TEXT,
            tumor_board_required INTEGER DEFAULT 0,
            shared_with_patient INTEGER DEFAULT 0,
            decided_by TEXT,
            decision_finalized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS tumor_board_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            discussion_date DATE,
            trigger_reason TEXT,
            system_recommendation_at_board TEXT,
            board_recommendation TEXT,
            board_recommendation_family TEXT,
            board_consensus_level TEXT,
            board_reasoning_structured TEXT,
            required_followup_actions_json TEXT,
            board_overrode_system TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS therapeutic_window_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            window_key TEXT NOT NULL,
            window_opened_at TIMESTAMP,
            window_status TEXT,
            window_closed_at TIMESTAMP,
            closure_type TEXT,
            closure_reason TEXT,
            evidence_used_json TEXT,
            closed_by TEXT,
            opportunity_lost INTEGER DEFAULT 0,
            opportunity_loss_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    for ddl in (
        "ALTER TABLE therapeutic_window_events ADD COLUMN decision_domain_blocked TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN required_fact_keys_json TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN missing_fact_keys_json TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN owner_role TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN sla_days INTEGER DEFAULT 0",
        "ALTER TABLE therapeutic_window_events ADD COLUMN clinical_consequence_if_delayed TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN target_state_if_closed TEXT",
        "ALTER TABLE therapeutic_window_events ADD COLUMN redirect_state_if_negative TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS treatment_adverse_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            treatment_id INTEGER,
            regimen_code TEXT,
            cycle_number INTEGER,
            ctcae_term TEXT,
            ctcae_grade INTEGER,
            attribution TEXT,
            seriousness TEXT,
            hospitalization INTEGER DEFAULT 0,
            dose_modification_triggered INTEGER DEFAULT 0,
            event_date DATE,
            expected_vs_observed_context TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(treatment_id) REFERENCES treatment_history(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_key TEXT NOT NULL UNIQUE,
            document_type TEXT NOT NULL,
            title TEXT,
            file_name TEXT,
            mime_type TEXT,
            sha256 TEXT NOT NULL,
            storage_path TEXT,
            private_index_path TEXT,
            source_date DATE,
            classification_status TEXT DEFAULT 'pending',
            extraction_status TEXT DEFAULT 'pending',
            verification_status TEXT DEFAULT 'draft',
            uploaded_by TEXT,
            preview_excerpt TEXT,
            page_count INTEGER DEFAULT 0,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS document_extraction_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            candidate_key TEXT NOT NULL,
            field_name TEXT NOT NULL,
            fact_group TEXT,
            target_result_type TEXT,
            value_json TEXT,
            value_display TEXT,
            confidence REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            extraction_method TEXT,
            evidence_excerpt TEXT,
            page_ref TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, candidate_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS document_verification_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL UNIQUE,
            task_key TEXT NOT NULL,
            task_status TEXT DEFAULT 'open',
            assigned_to TEXT,
            verified_by TEXT,
            verified_at TIMESTAMP,
            summary_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS verified_document_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            task_id INTEGER,
            fact_key TEXT,
            field_name TEXT NOT NULL,
            fact_group TEXT,
            target_result_type TEXT,
            value_json TEXT,
            value_display TEXT,
            source_date DATE,
            status TEXT DEFAULT 'verified',
            correction_note TEXT,
            verified_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id),
            FOREIGN KEY(task_id) REFERENCES document_verification_tasks(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS voice_encounter_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            session_key TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'created',
            consent_status TEXT DEFAULT 'missing',
            consent_id INTEGER,
            source_document_id INTEGER,
            retention_policy TEXT DEFAULT 'delete_audio_after_review',
            stt_provider TEXT DEFAULT 'local-first',
            extractor_version TEXT,
            transcript_hash TEXT,
            audio_sha256 TEXT,
            encrypted_audio_path TEXT,
            raw_audio_deleted_at TIMESTAMP,
            session_context_json TEXT,
            review_payload_json TEXT,
            created_by TEXT,
            reviewed_by TEXT,
            committed_by TEXT,
            discarded_by TEXT,
            signed_at TIMESTAMP,
            discarded_at TIMESTAMP,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(consent_id) REFERENCES patient_consents(id),
            FOREIGN KEY(source_document_id) REFERENCES source_documents(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS voice_transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            segment_index INTEGER NOT NULL,
            start_ms INTEGER DEFAULT 0,
            end_ms INTEGER DEFAULT 0,
            transcript_envelope_json TEXT NOT NULL,
            transcript_sha256 TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            stt_provider TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES voice_encounter_sessions(id),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            UNIQUE(session_id, segment_index)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_clinical_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            fact_key TEXT NOT NULL,
            value_json TEXT,
            normalized_value_text TEXT,
            source_type TEXT,
            source_record_type TEXT,
            source_record_id INTEGER,
            source_date DATE,
            observed_at DATE,
            state_context TEXT,
            management_track TEXT,
            certainty_tier TEXT,
            freshness_status TEXT,
            freshness_expires_at DATE,
            clinician_verified INTEGER DEFAULT 0,
            verification_note TEXT,
            superseded_by_fact_id INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(superseded_by_fact_id) REFERENCES patient_clinical_facts(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_fact_lineage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            fact_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source_fact_id INTEGER,
            target_fact_id INTEGER,
            event_note TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(source_fact_id) REFERENCES patient_clinical_facts(id),
            FOREIGN KEY(target_fact_id) REFERENCES patient_clinical_facts(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_fact_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            fact_key TEXT NOT NULL,
            existing_fact_id INTEGER,
            candidate_fact_id INTEGER,
            existing_value_text TEXT,
            candidate_value_text TEXT,
            severity TEXT DEFAULT 'moderate',
            resolution_status TEXT DEFAULT 'open',
            resolution_reason TEXT,
            resolved_by TEXT,
            resolved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(existing_fact_id) REFERENCES patient_clinical_facts(id),
            FOREIGN KEY(candidate_fact_id) REFERENCES patient_clinical_facts(id)
        )
        '''
    )

    # ── NUEVAS TABLAS: Copiloto Clínico (v4) ──────────────────────────────

    # Eventos programados de seguimiento (schedule_engine)
    c.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            schedule_key TEXT,
            encounter_key TEXT,
            plan_key TEXT,
            event_type TEXT NOT NULL,
            label TEXT,
            management_track TEXT,
            due_date DATE NOT NULL,
            ideal_due_at DATE,
            scheduled_due_at DATE,
            delay_days INTEGER DEFAULT 0,
            guideline TEXT,
            completed INTEGER DEFAULT 0,
            completed_date DATE,
            completion_status TEXT,
            completion_source TEXT,
            performed_date DATE,
            days_late INTEGER DEFAULT 0,
            adherence_impact TEXT,
            next_recovery_action TEXT,
            completed_visit_id INTEGER,
            overdue_alert_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE scheduled_events ADD COLUMN schedule_key TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN encounter_key TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN plan_key TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN ideal_due_at DATE",
        "ALTER TABLE scheduled_events ADD COLUMN scheduled_due_at DATE",
        "ALTER TABLE scheduled_events ADD COLUMN delay_days INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_events ADD COLUMN completion_status TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN completion_source TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN performed_date DATE",
        "ALTER TABLE scheduled_events ADD COLUMN days_late INTEGER DEFAULT 0",
        "ALTER TABLE scheduled_events ADD COLUMN adherence_impact TEXT",
        "ALTER TABLE scheduled_events ADD COLUMN next_recovery_action TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # Evaluaciones de respuesta terapéutica (RECIST/PCWG3/PSA)
    c.execute('''
        CREATE TABLE IF NOT EXISTS response_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_date DATE,
            treatment_id INTEGER,
            recist_category TEXT,
            sum_target_diameters REAL,
            baseline_sum_diameters REAL,
            nadir_sum_diameters REAL,
            pcwg3_bone_status TEXT,
            new_bone_lesion_count INTEGER,
            psa_response_category TEXT,
            psa_baseline REAL,
            psa_current REAL,
            psa_nadir REAL,
            psa_change_from_baseline_pct REAL,
            overall_response TEXT,
            clinical_benefit INTEGER,
            details_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS outcome_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            event_key TEXT,
            event_type TEXT NOT NULL,
            scenario_state TEXT,
            management_track TEXT,
            axis TEXT,
            adjudication_status TEXT,
            event_date DATE,
            source_priority TEXT,
            decision_impact TEXT,
            summary TEXT,
            provisional INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            blocking_fields_json TEXT,
            evidence_basis_json TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, event_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE outcome_events ADD COLUMN event_key TEXT",
        "ALTER TABLE outcome_events ADD COLUMN scenario_state TEXT",
        "ALTER TABLE outcome_events ADD COLUMN management_track TEXT",
        "ALTER TABLE outcome_events ADD COLUMN axis TEXT",
        "ALTER TABLE outcome_events ADD COLUMN adjudication_status TEXT",
        "ALTER TABLE outcome_events ADD COLUMN source_priority TEXT",
        "ALTER TABLE outcome_events ADD COLUMN decision_impact TEXT",
        "ALTER TABLE outcome_events ADD COLUMN summary TEXT",
        "ALTER TABLE outcome_events ADD COLUMN provisional INTEGER DEFAULT 0",
        "ALTER TABLE outcome_events ADD COLUMN active INTEGER DEFAULT 1",
        "ALTER TABLE outcome_events ADD COLUMN blocking_fields_json TEXT",
        "ALTER TABLE outcome_events ADD COLUMN evidence_basis_json TEXT",
        "ALTER TABLE outcome_events ADD COLUMN payload_json TEXT",
        "ALTER TABLE outcome_events ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS adjudication_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL UNIQUE,
            state TEXT,
            management_track TEXT,
            engine_version TEXT,
            current_course_status TEXT,
            current_response_state_json TEXT,
            last_adjudicated_event_json TEXT,
            pending_adjudications_json TEXT,
            outcome_events_summary_json TEXT,
            milestone_plan_json TEXT,
            outcome_anchor_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE adjudication_snapshots ADD COLUMN state TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN management_track TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN engine_version TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN current_course_status TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN current_response_state_json TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN last_adjudicated_event_json TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN pending_adjudications_json TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN outcome_events_summary_json TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN milestone_plan_json TEXT",
        "ALTER TABLE adjudication_snapshots ADD COLUMN outcome_anchor_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS trial_benchmark_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL UNIQUE,
            state TEXT,
            management_track TEXT,
            engine_version TEXT,
            current_trial_profile_json TEXT,
            trial_endpoints_json TEXT,
            benchmark_snapshot_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN state TEXT",
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN management_track TEXT",
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN engine_version TEXT",
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN current_trial_profile_json TEXT",
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN trial_endpoints_json TEXT",
        "ALTER TABLE trial_benchmark_snapshots ADD COLUMN benchmark_snapshot_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # Tracking de lesiones individuales
    c.execute('''
        CREATE TABLE IF NOT EXISTS lesion_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            lesion_id TEXT,
            first_detected_date DATE,
            first_detected_study_id INTEGER,
            anatomical_location TEXT,
            lesion_category TEXT,
            current_status TEXT DEFAULT 'present',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # Mediciones longitudinales de lesiones
    c.execute('''
        CREATE TABLE IF NOT EXISTS lesion_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesion_id INTEGER NOT NULL,
            study_id INTEGER,
            measurement_date DATE,
            longest_diameter_mm REAL,
            suvmax REAL,
            volume_ml REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lesion_id) REFERENCES lesion_tracking(id)
        )
    ''')

    # Biomarcadores longitudinales (ctDNA, PSA serie, etc.)
    c.execute('''
        CREATE TABLE IF NOT EXISTS biomarker_longitudinal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            biomarker_type TEXT NOT NULL,
            value REAL,
            unit TEXT,
            sample_date DATE,
            lab_source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── MIGRACIONES: Nuevas columnas en tablas existentes ────────────────

    # patient_demographics: Charlson Comorbidity Index
    for ddl in (
        "ALTER TABLE patient_demographics ADD COLUMN charlson_score INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN charlson_details_json TEXT",
        "ALTER TABLE patient_demographics ADD COLUMN g8_score REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_details_json TEXT",
        "ALTER TABLE patient_demographics ADD COLUMN frailty_status TEXT",
        "ALTER TABLE patient_demographics ADD COLUMN g8_food_intake REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_weight_loss REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_mobility REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_neuropsych REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_bmi REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_medications REAL",
        "ALTER TABLE patient_demographics ADD COLUMN g8_self_health REAL",
        "ALTER TABLE patient_demographics ADD COLUMN mini_cog_score INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN fatigue_score INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN weight_kg REAL",
        "ALTER TABLE patient_demographics ADD COLUMN height_cm REAL",
        "ALTER TABLE patient_demographics ADD COLUMN bmi_current REAL",
        "ALTER TABLE patient_demographics ADD COLUMN weight_loss_6m_kg REAL",
        "ALTER TABLE patient_demographics ADD COLUMN weight_loss_6m_pct REAL",
        "ALTER TABLE patient_demographics ADD COLUMN prior_weight_6m_kg REAL",
        "ALTER TABLE patient_demographics ADD COLUMN low_activity INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN slow_gait INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN weak_grip INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN line_of_therapy_number INTEGER",
        "ALTER TABLE patient_demographics ADD COLUMN line_of_therapy_context TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # patient_pros: PROs extendidos
    for ddl in (
        "ALTER TABLE patient_pros ADD COLUMN g8_total INTEGER",
        "ALTER TABLE patient_pros ADD COLUMN facit_fatigue_total INTEGER",
        "ALTER TABLE patient_pros ADD COLUMN fact_p_physical REAL",
        "ALTER TABLE patient_pros ADD COLUMN fact_p_social REAL",
        "ALTER TABLE patient_pros ADD COLUMN fact_p_emotional REAL",
        "ALTER TABLE patient_pros ADD COLUMN fact_p_functional REAL",
        "ALTER TABLE patient_pros ADD COLUMN fact_p_prostate REAL",
        "ALTER TABLE patient_pros ADD COLUMN continence_status TEXT",
        "ALTER TABLE patient_pros ADD COLUMN time_to_continence_months INTEGER",
        "ALTER TABLE patient_pros ADD COLUMN sexual_recovery_status TEXT",
        "ALTER TABLE patient_pros ADD COLUMN time_to_erection_months INTEGER",
        "ALTER TABLE patient_pros ADD COLUMN epic26_urinary_domain REAL",
        "ALTER TABLE patient_pros ADD COLUMN epic26_sexual_domain REAL",
        "ALTER TABLE patient_pros ADD COLUMN epic26_bowel_domain REAL",
        "ALTER TABLE patient_pros ADD COLUMN epic26_hormonal_domain REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_global_health REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_physical REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_role REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_emotional REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_fatigue REAL",
        "ALTER TABLE patient_pros ADD COLUMN eortc_qlq_c30_pain REAL",
        "ALTER TABLE patient_pros ADD COLUMN anxiety_score REAL",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    for ddl in (
        "ALTER TABLE state_transition_proposals ADD COLUMN confirmation_status TEXT DEFAULT 'pending'",
        "ALTER TABLE state_transition_proposals ADD COLUMN rejection_reason TEXT",
        "ALTER TABLE state_transition_proposals ADD COLUMN requires_more_data_fields_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    for ddl in (
        "ALTER TABLE recommendation_audit ADD COLUMN recommended_confidence TEXT",
        "ALTER TABLE recommendation_audit ADD COLUMN clinician_selected_option TEXT",
        "ALTER TABLE recommendation_audit ADD COLUMN clinician_selected_family TEXT",
        "ALTER TABLE recommendation_audit ADD COLUMN followed_system_recommendation TEXT",
        "ALTER TABLE recommendation_audit ADD COLUMN discordance_reason_category TEXT",
        "ALTER TABLE recommendation_audit ADD COLUMN decision_capture_status TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # follow_up_visits: Monitoreo CV/metabólico bajo ADT
    for ddl in (
        "ALTER TABLE follow_up_visits ADD COLUMN dxa_t_score_lumbar REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN dxa_t_score_hip REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN total_cholesterol REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN hdl_cholesterol REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN triglycerides REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN systolic_bp INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN diastolic_bp INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN waist_circumference_cm REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN hba1c REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN vitamin_d_level REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN calcium_level REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN toxicity_structured_json TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN metastasis_site TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN metastasis_count INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN m_substage_resolved TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN metastatic_profile_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # clinical_baseline: Biomarcadores diagnósticos avanzados
    for ddl in (
        "ALTER TABLE clinical_baseline ADD COLUMN free_psa REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN p2psa REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN intact_psa REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN hk2 REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN phi_score REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN four_k_probability REAL",
        "ALTER TABLE clinical_baseline ADD COLUMN selectmdx_result TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN exodx_result TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN m_substage_resolved TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN metastatic_profile_json TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN metastasis_assessment_date DATE",
        "ALTER TABLE clinical_baseline ADD COLUMN metastasis_document_source TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN histology_subtype TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN clinical_tstage TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN nodal_status TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN clinical_stage_group TEXT",
        "ALTER TABLE clinical_baseline ADD COLUMN clinical_risk_group TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE biopsy_details ADD COLUMN histology_subtype TEXT")
    except sqlite3.OperationalError:
        pass

    # genomic_profile: Biomarcadores emergentes
    for ddl in (
        "ALTER TABLE genomic_profile ADD COLUMN ctdna_detected INTEGER",
        "ALTER TABLE genomic_profile ADD COLUMN ctdna_vaf REAL",
        "ALTER TABLE genomic_profile ADD COLUMN ctdna_date DATE",
        "ALTER TABLE genomic_profile ADD COLUMN tmb_score REAL",
        "ALTER TABLE genomic_profile ADD COLUMN pdl1_expression TEXT",
        "ALTER TABLE genomic_profile ADD COLUMN ntrk_fusion TEXT",
        "ALTER TABLE genomic_profile ADD COLUMN ret_alteration TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── Research Intelligence + Consent Governance ────────────────────────
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS research_survival_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key TEXT UNIQUE,
            endpoint TEXT,
            cohort_key TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS research_multivariate_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT UNIQUE,
            analysis_type TEXT,
            cohort_key TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS research_propensity_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT UNIQUE,
            cohort_key TEXT,
            treatment_field TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS operational_outcome_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date DATE,
            severity TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS clavien_dindo_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            surgery_date DATE,
            grade TEXT,
            event_label TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS functional_recovery_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            snapshot_date DATE,
            urinary_recovery_status TEXT,
            sexual_recovery_status TEXT,
            continence_pads_per_day REAL,
            pde5i_use TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS quality_indicator_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator_key TEXT NOT NULL UNIQUE,
            title TEXT,
            clinical_definition TEXT,
            benchmark_target TEXT,
            domain TEXT,
            metadata_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS quality_indicator_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indicator_key TEXT NOT NULL,
            numerator INTEGER DEFAULT 0,
            denominator INTEGER DEFAULT 0,
            percentage REAL DEFAULT 0,
            trend_json TEXT,
            result_payload_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(indicator_key) REFERENCES quality_indicator_definitions(indicator_key)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS benchmark_reference_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_key TEXT NOT NULL UNIQUE,
            title TEXT,
            endpoint TEXT,
            source_label TEXT,
            population_summary TEXT,
            reference_payload_json TEXT,
            comparability_tier TEXT DEFAULT 'limited',
            effective_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS benchmark_comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_key TEXT,
            cohort_key TEXT,
            comparison_payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS dynamic_cohorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_key TEXT,
            title TEXT NOT NULL,
            description TEXT,
            filters_json TEXT,
            system_defined BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS dynamic_cohort_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cohort_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(cohort_id) REFERENCES dynamic_cohorts(id),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS consent_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            consent_text TEXT NOT NULL,
            html_snapshot TEXT,
            effective_at TIMESTAMP NOT NULL,
            active BOOLEAN DEFAULT 1
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_consents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            consent_version_code TEXT NOT NULL,
            status TEXT DEFAULT 'signed',
            signer_name TEXT,
            signed_at TIMESTAMP,
            content_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(consent_version_code) REFERENCES consent_versions(version_code)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS consent_signature_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            consent_id INTEGER NOT NULL,
            signature_data_url TEXT,
            evidence_html TEXT,
            audit_metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(consent_id) REFERENCES patient_consents(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_intake_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_context TEXT,
            nss TEXT,
            full_name TEXT,
            assessment_id INTEGER,
            payload_json TEXT,
            signature_json TEXT,
            status TEXT DEFAULT 'draft',
            consent_version_code TEXT,
            patient_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finalized_at TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(consent_version_code) REFERENCES consent_versions(version_code)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS research_export_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            export_type TEXT,
            cohort_key TEXT,
            status TEXT DEFAULT 'completed',
            manifest_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS research_export_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            file_name TEXT,
            file_kind TEXT,
            file_payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES research_export_jobs(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS decision_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key TEXT NOT NULL UNIQUE,
            patient_id INTEGER NOT NULL,
            event_id INTEGER,
            state TEXT,
            management_track TEXT,
            headline TEXT,
            snapshot_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS guideline_plan_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key TEXT NOT NULL UNIQUE,
            patient_id INTEGER NOT NULL,
            event_id INTEGER,
            state TEXT,
            management_track TEXT,
            guideline_basis_json TEXT,
            snapshot_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS state_transition_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_key TEXT NOT NULL UNIQUE,
            patient_id INTEGER NOT NULL,
            event_id INTEGER,
            from_state TEXT,
            to_state TEXT,
            management_track TEXT,
            reason TEXT,
            snapshot_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS missing_input_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_key TEXT NOT NULL UNIQUE,
            patient_id INTEGER NOT NULL,
            event_id INTEGER,
            state TEXT,
            management_track TEXT,
            blocking_inputs_json TEXT,
            required_to_recalculate_json TEXT,
            optional_context_inputs_json TEXT,
            decision_domains_blocked_json TEXT,
            rationale_json TEXT,
            snapshot_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS validation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            cohort_mode TEXT,
            base_url TEXT,
            total_trajectories INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            critical_failures INTEGER DEFAULT 0,
            ui_contradictions INTEGER DEFAULT 0,
            missing_input_prompt_accuracy REAL DEFAULT 0,
            guideline_concordance_pct REAL DEFAULT 0,
            data_accumulation_completeness_pct REAL DEFAULT 0,
            top_failing_scenario_families_json TEXT,
            report_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS validation_run_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            case_key TEXT NOT NULL,
            scenario_id TEXT NOT NULL,
            scenario_family TEXT NOT NULL,
            patient_id INTEGER,
            patient_nss TEXT,
            case_status TEXT,
            critical_failure INTEGER DEFAULT 0,
            ui_contradictions_json TEXT,
            expected_json TEXT,
            actual_json TEXT,
            assertions_json TEXT,
            report_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, case_key)
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS validation_visual_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            case_key TEXT NOT NULL,
            patient_id INTEGER,
            artifact_type TEXT,
            artifact_path TEXT,
            artifact_text TEXT,
            assertion_key TEXT,
            status TEXT DEFAULT 'generated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    # ── AI Engine Tables ──

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS ai_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            prediction_type TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            prediction_json TEXT NOT NULL,
            confidence_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS agent_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            trigger_event TEXT NOT NULL,
            trigger_data_json TEXT,
            output_json TEXT NOT NULL,
            confidence_score REAL,
            qa_validation_json TEXT,
            execution_time_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS ai_model_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            model_type TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            training_data_hash TEXT,
            metrics_json TEXT,
            is_active BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(model_id, model_version)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS training_data_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            data_source TEXT NOT NULL,
            patient_count INTEGER,
            feature_count INTEGER,
            consent_evidence_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS crpc_copilot_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_crpc_copilot_snapshots_patient_created
        ON crpc_copilot_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS post_rp_salvage_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            post_prostatectomy_course TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_post_rp_salvage_snapshots_patient_created
        ON post_rp_salvage_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS mhspc_copilot_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_mhspc_copilot_snapshots_patient_created
        ON mhspc_copilot_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS diagnostic_biopsy_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_diagnostic_biopsy_snapshots_patient_created
        ON diagnostic_biopsy_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS localized_surveillance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_localized_surveillance_snapshots_patient_created
        ON localized_surveillance_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS post_rt_salvage_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            trigger_event TEXT NOT NULL,
            post_rt_course TEXT NOT NULL,
            effective_state TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            qa_json TEXT,
            final_presented_recommendation_json TEXT,
            concordance_label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )
    c.execute(
        '''
        CREATE INDEX IF NOT EXISTS idx_post_rt_salvage_snapshots_patient_created
        ON post_rt_salvage_snapshots (patient_id, created_at DESC, id DESC)
        '''
    )

    conn.commit()
    conn.close()
    try:
        _backfill_normalized_tracking_domains()
    except Exception as exc:
        logger.warning("Normalized domain backfill skipped: %s", exc)
    logger.info("Tracking DB initialized (v5 — AI Engine + Agents + Recalculation).")


def _backfill_normalized_tracking_domains():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, diagnosis_date, vital_status, date_of_death, cause_of_death, last_contact_date, last_contact_status, death_source FROM patient_identity ORDER BY id ASC")
    identities = [dict(row) for row in cursor.fetchall()]
    for identity in identities:
        patient_id = int(identity["id"])
        cursor.execute("SELECT 1 FROM survival_status_records WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None and any(_is_present(identity.get(field)) for field in ("vital_status", "date_of_death", "cause_of_death", "last_contact_date", "last_contact_status", "death_source")):
            if not identity.get("last_contact_date"):
                cursor.execute("SELECT visit_date FROM follow_up_visits WHERE patient_id = ? ORDER BY visit_date DESC, id DESC LIMIT 1", (patient_id,))
                followup_row = cursor.fetchone()
                if followup_row:
                    identity["last_contact_date"] = followup_row["visit_date"]
                    identity["last_contact_status"] = identity.get("last_contact_status") or "clinic_visit"
            _save_survival_status_update(cursor, patient_id, identity, source_type="legacy_summary_backfill")

        cursor.execute("SELECT 1 FROM survival_anchor_events WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None:
            anchor_events = []
            if identity.get("diagnosis_date"):
                anchor_events.append({"anchor_type": "diagnosis", "anchor_date": identity.get("diagnosis_date"), "anchor_source": "patient_identity"})
            cursor.execute("SELECT start_date FROM treatment_history WHERE patient_id = ? AND start_date IS NOT NULL ORDER BY start_date ASC, id ASC LIMIT 1", (patient_id,))
            treatment_row = cursor.fetchone()
            if treatment_row:
                anchor_events.append({"anchor_type": "treatment_start", "anchor_date": treatment_row["start_date"], "anchor_source": "treatment_history"})
            cursor.execute("SELECT bcr_date FROM biochemical_recurrence WHERE patient_id = ? AND bcr_date IS NOT NULL ORDER BY bcr_date ASC, id ASC LIMIT 1", (patient_id,))
            bcr_row = cursor.fetchone()
            if bcr_row:
                anchor_events.append({"anchor_type": "psa_progression", "anchor_date": bcr_row["bcr_date"], "anchor_source": "biochemical_recurrence"})
            cursor.execute("SELECT surgery_date FROM surgical_details WHERE patient_id = ? AND surgery_date IS NOT NULL ORDER BY surgery_date ASC, id ASC LIMIT 1", (patient_id,))
            surgery_row = cursor.fetchone()
            if surgery_row:
                anchor_events.append({"anchor_type": "surgery", "anchor_date": surgery_row["surgery_date"], "anchor_source": "surgical_details"})
            cursor.execute("SELECT rt_date FROM radiation_details WHERE patient_id = ? AND rt_date IS NOT NULL ORDER BY rt_date ASC, id ASC LIMIT 1", (patient_id,))
            rt_row = cursor.fetchone()
            if rt_row:
                anchor_events.append({"anchor_type": "radiotherapy", "anchor_date": rt_row["rt_date"], "anchor_source": "radiation_details"})
            if identity.get("date_of_death"):
                anchor_events.append({"anchor_type": "death", "anchor_date": identity.get("date_of_death"), "anchor_source": identity.get("death_source") or "patient_identity"})
            _save_survival_anchor_events(cursor, patient_id, anchor_events, source_type="legacy_summary_backfill")

        cursor.execute("SELECT 1 FROM biopsy_sessions WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None:
            cursor.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC, id ASC", (patient_id,))
            for biopsy in [dict(row) for row in cursor.fetchall()]:
                total_cores = _safe_int(biopsy.get("total_cores"), 0)
                positive_cores = _safe_int(biopsy.get("positive_cores"), 0)
                systematic_cores = []
                for index in range(total_cores):
                    systematic_cores.append(
                        {
                            "core_id": f"S{index + 1}",
                            "location_sextant": "",
                            "core_type": "systematic",
                            "positive": index < positive_cores,
                            "involvement_pct": biopsy.get("max_core_involvement_pct") if index == 0 and positive_cores > 0 else None,
                            "gleason_primary": biopsy.get("gleason_primary"),
                            "gleason_secondary": biopsy.get("gleason_secondary"),
                            "isup_grade": biopsy.get("isup_grade"),
                            "cribriform_pattern": bool(biopsy.get("patron_cribiforme", 0)),
                            "intraductal_carcinoma": bool(biopsy.get("carcinoma_intraductal", 0)),
                        }
                    )
                _save_structured_biopsy_session(
                    cursor,
                    patient_id,
                    {
                        "session_key": f"legacy_biopsy_{biopsy.get('id')}",
                        "biopsy_date": biopsy.get("biopsy_date"),
                        "biopsy_type": biopsy.get("biopsy_type"),
                        "biopsy_context": biopsy.get("biopsy_context"),
                        "systematic_cores": systematic_cores,
                        "complications": [],
                    },
                    source_type="legacy_summary_backfill",
                    source_record_id=biopsy.get("id"),
                    legacy_biopsy_id=biopsy.get("id"),
                )

        cursor.execute("SELECT 1 FROM as_enrollments WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None:
            cursor.execute("SELECT * FROM active_surveillance WHERE patient_id = ? ORDER BY enrollment_date DESC, id DESC LIMIT 1", (patient_id,))
            as_row = cursor.fetchone()
            if as_row:
                as_data = dict(as_row)
                _save_active_surveillance_update(
                    cursor,
                    patient_id,
                    {
                        "enrollment_date": as_data.get("enrollment_date"),
                        "protocol": as_data.get("enrollment_protocol"),
                        "criteria_met": _parse_json_blob(as_data.get("enrollment_criteria_met"), {}),
                        "current_status": as_data.get("current_status"),
                        "exit_date": as_data.get("exit_date"),
                        "exit_reason": as_data.get("exit_reason"),
                        "exit_treatment": as_data.get("exit_treatment"),
                    },
                    source_type="legacy_summary_backfill",
                    source_record_id=as_data.get("id"),
                )

        cursor.execute("SELECT 1 FROM skeletal_related_events WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None:
            cursor.execute("SELECT id, visit_date, skeletal_events FROM follow_up_visits WHERE patient_id = ? ORDER BY visit_date ASC, id ASC", (patient_id,))
            for visit in [dict(row) for row in cursor.fetchall()]:
                skeletal = _parse_json_blob(visit.get("skeletal_events"), {})
                if not isinstance(skeletal, dict):
                    continue
                events = []
                for key, enabled in skeletal.items():
                    if _coerce_bool(enabled):
                        events.append(
                            {
                                "event_type": key,
                                "event_date": visit.get("visit_date"),
                                "details": "Backfill desde follow_up_visits.skeletal_events",
                            }
                        )
                _save_skeletal_events_structured(
                    cursor,
                    patient_id,
                    events,
                    source_type="legacy_summary_backfill",
                    source_record_id=visit.get("id"),
                )

        cursor.execute("SELECT 1 FROM radiotherapy_courses WHERE patient_id = ? LIMIT 1", (patient_id,))
        if cursor.fetchone() is None:
            cursor.execute("SELECT * FROM radiation_details WHERE patient_id = ? ORDER BY rt_date ASC, id ASC", (patient_id,))
            for row in [dict(item) for item in cursor.fetchall()]:
                _save_radiotherapy_course_detailed(
                    cursor,
                    patient_id,
                    {
                        "course_key": f"legacy_rt_{row.get('id')}",
                        "rt_intent": row.get("rt_context"),
                        "modality": row.get("rt_technique"),
                        "target_volume": row.get("target"),
                        "total_dose_gy": row.get("total_dose_gy"),
                        "fractions": row.get("fractions"),
                        "dose_per_fraction_gy": row.get("dose_per_fraction_gy"),
                        "rt_start_date": row.get("rt_date"),
                        "rt_end_date": row.get("rt_date"),
                        "concurrent_adt": row.get("concurrent_adt"),
                        "toxicity": [
                            {"domain": "GU", "phase": "acute", "grade": _safe_int(row.get("gu_toxicity_grade"), 0)},
                            {"domain": "GI", "phase": "acute", "grade": _safe_int(row.get("gi_toxicity_grade"), 0)},
                        ],
                        "notes": row.get("notes"),
                    },
                    source_type="legacy_summary_backfill",
                    source_record_id=row.get("id"),
                    legacy_radiation_id=row.get("id"),
                )
    conn.commit()
    conn.close()


def create_clinical_assessment_draft(module_id, state, input_snapshot, result_snapshot, guideline_versions):
    conn = None
    try:
        conn = _connect(write=True)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO clinical_assessments (
                module_id, state, input_snapshot, result_snapshot, guideline_versions, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                module_id,
                state,
                json.dumps(input_snapshot, ensure_ascii=False),
                json.dumps(result_snapshot, ensure_ascii=False),
                json.dumps(guideline_versions, ensure_ascii=False),
                "draft",
            ),
        )
        assessment_id = c.lastrowid
        conn.commit()
        return assessment_id
    except Exception as e:
        logger.error(f"Error creating clinical assessment draft: {e}")
        return None
    finally:
        _close_connection_quietly(conn)


def get_clinical_assessment(assessment_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM clinical_assessments WHERE id = ?", (assessment_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        assessment = dict(row)
        assessment["input_snapshot"] = _parse_json_blob(assessment.get("input_snapshot"), {})
        assessment["result_snapshot"] = _parse_json_blob(assessment.get("result_snapshot"), {})
        assessment["guideline_versions"] = _parse_json_blob(assessment.get("guideline_versions"), {})
        return assessment
    except Exception as e:
        logger.error(f"Error getting clinical assessment: {e}")
        return None


def attach_clinical_assessment_to_patient(assessment_id, patient_id):
    conn = None
    try:
        assessment = get_clinical_assessment(assessment_id)
        if not assessment:
            return False, "Evaluación clínica no encontrada"
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"

        snapshot = _assessment_longitudinal_snapshot(assessment)
        from prostanet.domains.patient_tracking.event_graph import (
            derive_management_intent_status,
            derive_timeline_event_kind,
        )
        record = get_patient_full_record(patient_id) or {}
        management_intent_status = derive_management_intent_status(assessment.get("state"), assessment.get("result_snapshot", {}), record)
        event_kind = derive_timeline_event_kind(assessment.get("state"), assessment.get("result_snapshot", {}), record)

        conn = _connect(write=True)
        c = conn.cursor()
        _ensure_prior_history_row(c, patient_id)
        c.execute(
            '''
            UPDATE clinical_assessments
            SET patient_id = ?, status = ?
            WHERE id = ?
            ''',
            (patient_id, "linked", assessment_id),
        )
        c.execute(
            '''
            UPDATE prior_clinical_history
            SET latest_assessment_id = ?,
                assessment_source = ?,
                assessment_module = ?,
                assessment_state = ?,
                assessment_summary = ?,
                recommendation_family = ?,
                management_intent_status = ?,
                current_state = ?,
                transition_reason = ?,
                objective_progression_json = ?,
                monitoring_plan_json = ?,
                care_overlays_json = ?,
                latest_guideline_snapshot_json = ?
            WHERE patient_id = ?
            ''',
            (
                assessment_id,
                "clinical_wizard",
                assessment.get("module_id"),
                assessment.get("state"),
                snapshot["summary"],
                snapshot.get("recommendation_family", ""),
                management_intent_status,
                snapshot["current_state"],
                snapshot["transition_reason"],
                _json_blob(snapshot["objective_progression"]),
                _json_blob(snapshot["monitoring_plan"]),
                _json_blob(snapshot["care_overlays"]),
                _json_blob(snapshot["guideline_snapshot"]),
                patient_id,
            ),
        )
        _record_patient_state_transition(
            c,
            patient_id,
            assessment_id,
            assessment.get("state"),
            event_kind,
            management_intent_status,
            snapshot["transition_reason"],
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            {
                **snapshot["guideline_snapshot"],
                "decision_quality": snapshot.get("decision_quality", {}),
                "validated_algorithms": snapshot.get("validated_algorithms", []),
            },
        )
        conn.commit()
        return True, "Evaluación clínica vinculada"
    except Exception as e:
        logger.error(f"Error attaching clinical assessment: {e}")
        return False, str(e)
    finally:
        _close_connection_quietly(conn)


def _fetch_latest_clinical_assessment(cursor, patient_id):
    cursor.execute(
        """
        SELECT * FROM clinical_assessments
        WHERE patient_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {}

    assessment = dict(row)
    assessment["input_snapshot"] = _parse_json_blob(assessment.get("input_snapshot"), {})
    assessment["result_snapshot"] = _parse_json_blob(assessment.get("result_snapshot"), {})
    assessment["guideline_versions"] = _parse_json_blob(assessment.get("guideline_versions"), {})
    return assessment

def save_patient_result(patient_data, ml_result, scores, summary):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if new columns exist, if not add them (Migration logic for existing DB)
        try:
            c.execute("SELECT surgical_margin FROM patients LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating DB: Adding post-op columns...")
            c.execute("ALTER TABLE patients ADD COLUMN surgical_margin INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN ece_status INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN svi_status INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN lni_status INTEGER")

        c.execute('''
            INSERT INTO patients (
                source_id, source_type, age, psa, 
                gleason_primary, gleason_secondary, clinical_tstage,
                num_cores_positive, total_cores,
                surgical_margin, ece_status, svi_status, lni_status,
                ml_prediction, clinical_scores, clinical_summary, discordance_alert
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_data.get('source_id'),
            patient_data.get('source_type', 'manual'),
            patient_data.get('age'),
            patient_data.get('psa'),
            patient_data.get('gleason_primary'),
            patient_data.get('gleason_secondary'),
            patient_data.get('clinical_tstage'),
            patient_data.get('num_cores_positive'),
            patient_data.get('total_cores'),
            patient_data.get('surgical_margin'),
            patient_data.get('ece_status'),
            patient_data.get('svi_status'),
            patient_data.get('lni_status'),

            json.dumps(ml_result),
            json.dumps(scores),
            json.dumps(summary),
            bool(summary.get('discordance_alert'))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save patient: {e}")
        return False


def _has_any_value(data, field_names):
    return any(data.get(field) not in (None, "") for field in field_names)


def _build_family_history_relatives(data):
    detail = str(data.get("family_history_detail", "")).strip()
    if not detail and not _is_truthy(data.get("family_history_positive")):
        return []
    return [
        {
            "relative_type": "No especificado",
            "cancer_type": "Próstata",
            "age_at_diagnosis": 0,
            "known_mutation": str(data.get("germline_status") or data.get("hrr_gene") or "Desconocido"),
            "deceased": 0,
            "notes": detail,
        }
    ]


def _build_imaging_payloads(data):
    payloads = []
    localized_prior_mri = (
        str(data.get("assessment_state") or "").strip() == "localized_initial"
        and _is_truthy(data.get("prior_mpmri"))
    )
    pirads_score = data.get("pirads_score")
    if pirads_score in (None, "", 0, "0") and localized_prior_mri:
        pirads_score = data.get("prior_mpmri_pirads_score")
    lesion_location = data.get("index_lesion_location")
    lesion_size_mm = data.get("index_lesion_size_mm")
    if _has_any_value(
        data,
        [
            "mpmri_date",
            "pirads_score",
            "prior_mpmri_pirads_score",
            "index_lesion_location",
            "index_lesion_size_mm",
            "mpmri_quality",
        ],
    ) or localized_prior_mri:
        payloads.append(
            {
                "study_date": data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "mpMRI",
                "pirads_score": _safe_int(pirads_score, None),
                "pirads_location": lesion_location,
                "lesion_size_mm": _safe_float(lesion_size_mm, 0),
                "precise_score": data.get("precise_score"),
                "findings": {
                    "mpmri_quality": data.get("mpmri_quality"),
                    "planned_biopsy_type": data.get("planned_biopsy_type"),
                    "planned_biopsy_route": data.get("planned_biopsy_route"),
                    "risk_calculator_pathway": data.get("risk_calculator_pathway"),
                    "post_biopsy_mri": _is_truthy(data.get("post_biopsy_mri")),
                    "persistent_lesion_signal": _is_truthy(data.get("persistent_lesion_signal")),
                    "prior_mpmri_targeted_biopsy_status": data.get("prior_mpmri_targeted_biopsy_status"),
                },
                "radiologist_notes": str(data.get("family_history_detail", ""))[:500] or None,
            }
        )
    if _is_truthy(data.get("psma_pet_done")) or str(data.get("imaging_modality", "")) == "PSMA-PET":
        payloads.append(
            normalize_psma_imaging_payload(
                {
                    "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                    "study_type": "PSMA-PET",
                    "psma_result": data.get("psma_pet_result") or ("positivo" if _is_truthy(data.get("psma_positive")) else "negativo"),
                    "psma_suv_max": data.get("psma_suv_max"),
                    "psma_radioligand": data.get("psma_radioligand"),
                    "psma_index_lesion_site": data.get("psma_index_lesion_site"),
                    "psma_index_lesion_suvmax": data.get("psma_index_lesion_suvmax"),
                    "psma_uptake_pattern": data.get("psma_uptake_pattern"),
                    "psma_rads_score": data.get("psma_rads_score"),
                    "psma_total_lesions": data.get("psma_total_lesions"),
                    "psma_lesion_locations": data.get("psma_lesion_locations"),
                    "psma_negative_dominant_lesions": _is_truthy(data.get("psma_negative_dominant_lesions")),
                    "conventional_stage_before_psma": data.get("conventional_stage_before_psma") or data.get("conventional_imaging_status"),
                    "psma_stage_after_psma": data.get("psma_stage_after_psma"),
                    "psma_upstaged_vs_conventional": data.get("psma_upstaged_vs_conventional"),
                    "psma_management_changed": data.get("psma_management_changed"),
                    "findings": {
                        "conventional_imaging_m0": _is_truthy(data.get("conventional_imaging_m0")),
                    },
                }
            )
        )
    if (
        str(data.get("imaging_modality", "")) == "Convencional"
        or _is_truthy(data.get("conventional_imaging_m0"))
        or str(data.get("conventional_imaging_status", "not_restaged") or "not_restaged") in {"M0", "M1"}
    ):
        conventional_status = str(data.get("conventional_imaging_status", "") or "").upper()
        payloads.append(
            {
                "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "Convencional",
                "findings": {
                    "conventional_imaging_m0": _is_truthy(data.get("conventional_imaging_m0")) or conventional_status == "M0",
                    "conventional_imaging_status": conventional_status or ("M0" if _is_truthy(data.get("conventional_imaging_m0")) else ""),
                    "salvage_local_feasible": _is_truthy(data.get("salvage_local_feasible")),
                    "local_salvage_candidate": _is_truthy(data.get("local_salvage_candidate")),
                    "progression_pattern": data.get("progression_pattern"),
                    "castrate_testosterone_status": data.get("castrate_testosterone_status"),
                },
                "radiologist_notes": data.get("psma_pet_result"),
            }
        )
    if _is_truthy(data.get("has_bone_scan")):
        payloads.append(
            {
                "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "Gammagrama",
                "bone_scan_result": "positivo_limitado" if str(data.get("metastasis_site", "M0")) == "Bone" else "negativo",
                "bone_lesion_count": _safe_int(data.get("metastasis_count"), 0),
            }
        )
    return payloads


def _build_mri_fact_payload(data):
    if data.get("assessment_state") not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    if not _has_any_value(
        data,
        [
            "mpmri_date",
            "mpmri_quality",
            "pirads_score",
            "index_lesion_location",
            "index_lesion_size_mm",
            "prostate_volume_ml",
        ],
    ):
        return None
    quality = data.get("mpmri_quality") or "No disponible"
    return {
        "fact_date": data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
        "mpmri_quality": quality,
        "decision_usable": 1 if quality == "Adecuada" else 0,
        "pirads_score": _safe_int(data.get("pirads_score"), None),
        "lesion_location": data.get("index_lesion_location"),
        "lesion_size_mm": _safe_float(data.get("index_lesion_size_mm"), None),
        "prostate_volume_ml": _safe_float(data.get("prostate_volume_ml"), None),
        "findings": {
            "psad": _safe_float(data.get("psad"), None),
            "psa_velocity_ng_ml_year": _safe_float(data.get("psa_velocity_ng_ml_year"), None),
            "risk_calculator_pathway": data.get("risk_calculator_pathway"),
        },
    }


def _build_diagnostic_plan_payload(data, assessment=None):
    state = str(data.get("assessment_state") or "").strip()
    if state not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    result = (assessment or {}).get("result_snapshot", {}) if assessment else {}
    primary = result.get("nccn_primary", {}) or {}
    treatments = result.get("eligible_treatments", []) or []
    recommended_pathway = primary.get("trayectoria_recomendada") or primary.get("recommendation") or ""
    summary = primary.get("resumen_del_caso") or (result.get("report_sections", {}) or {}).get("summary", "")
    next_action = ""
    if str(data.get("mpmri_quality", "")) == "Subóptima":
        next_action = "Repetir resonancia magnética multiparamétrica de alta calidad"
    elif str(data.get("planned_biopsy_type", "")) not in {"", "Pendiente"}:
        next_action = f"{data.get('planned_biopsy_type')} por vía {data.get('planned_biopsy_route') or 'no definida'}"
    elif recommended_pathway:
        next_action = recommended_pathway
    if not summary and not next_action and not treatments:
        return None
    trigger_conditions = []
    if _safe_int(data.get("pirads_score"), 0) >= 4:
        trigger_conditions.append("Lesión PI-RADS 4-5")
    if _safe_float(data.get("psad"), 0) >= 0.15:
        trigger_conditions.append("Densidad del antígeno prostático específico elevada")
    if _is_truthy(data.get("dre_suspicious")):
        trigger_conditions.append("Tacto rectal sospechoso")
    if _safe_float(data.get("psa_velocity_ng_ml_year"), 0) >= 0.75:
        trigger_conditions.append("Cinética de antígeno prostático específico en ascenso")
    if state == "post_negative_biopsy_followup" and _is_truthy(data.get("persistent_lesion_signal")):
        trigger_conditions.append("Persistencia de lesión sospechosa tras biopsia benigna")
    if not trigger_conditions:
        trigger_conditions.append("Reevaluación estructurada según la Red Nacional Integral del Cáncer (NCCN) y la Asociación Europea de Urología (EAU)")
    return {
        "source_state": state,
        "plan_type": "reactivacion_diagnostica" if state == "post_negative_biopsy_followup" else "confirmacion_histologica",
        "plan_status": "planificado",
        "management_intent_status": "candidate",
        "plan_summary": summary,
        "recommended_pathway": recommended_pathway or next_action,
        "next_action": next_action or recommended_pathway,
        "risk_calculator_pathway": data.get("risk_calculator_pathway"),
        "trigger_conditions": trigger_conditions,
        "evidence_context": [
            "La recomendación principal sigue anclada en la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
            "El plan diagnóstico se persiste como hecho temprano y no como confirmación histológica.",
        ],
    }


def _build_biopsy_trigger_payload(data, assessment=None):
    state = str(data.get("assessment_state") or "").strip()
    if state not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    result = (assessment or {}).get("result_snapshot", {}) if assessment else {}
    primary = result.get("nccn_primary", {}) or {}
    treatments = result.get("eligible_treatments", []) or []
    biopsy_recommended = any("biops" in str((item if isinstance(item, str) else item.get("name", ""))).lower() for item in treatments)
    trigger_reason = data.get("repeat_biopsy_trigger") if state == "post_negative_biopsy_followup" else None
    if not trigger_reason:
        if biopsy_recommended:
            trigger_reason = "Sospecha clínica suficiente para confirmación histológica"
        else:
            trigger_reason = "Mantener trigger estructurado si cambian densidad, MRI o cinética del antígeno prostático específico"
    activation_conditions = []
    if _safe_int(data.get("pirads_score"), 0) >= 4:
        activation_conditions.append("Lesión PI-RADS 4-5")
    if _safe_float(data.get("psad"), 0) >= 0.15:
        activation_conditions.append("PSAD >= 0.15")
    if _is_truthy(data.get("dre_suspicious")):
        activation_conditions.append("Tacto rectal sospechoso")
    if state == "post_negative_biopsy_followup" and _is_truthy(data.get("persistent_lesion_signal")):
        activation_conditions.append("Lesión persistente tras biopsia benigna")
    if not activation_conditions:
        activation_conditions.append(primary.get("recommendation") or "Reevaluación diagnóstica con control seriado")
    return {
        "source_state": state,
        "trigger_reason": trigger_reason,
        "priority": "alta" if biopsy_recommended else "vigilada",
        "planned_biopsy_type": (data.get("planned_biopsy_type") or data.get("prior_biopsy_type") or "Pendiente") if biopsy_recommended else "Pendiente",
        "planned_biopsy_route": (data.get("planned_biopsy_route") or "No definida") if biopsy_recommended else "No definida",
        "trigger_status": "pendiente_de_confirmacion",
        "management_intent_status": "candidate",
        "activation_conditions": activation_conditions,
    }


def _build_genomic_payload(data):
    if not _has_any_value(
        data,
        [
            "genomic_classifier",
            "genomic_classifier_result",
            "decipher_score",
            "decipher_risk",
            "prolaris_score",
            "gps_score",
            "hrr_status",
            "hrr_gene",
            "brca2_status",
            "msi_status",
            "molecular_report_date",
            "molecular_assay_date",
        ],
    ):
        return None

    test_type = "Panel_HRR"
    if str(data.get("genomic_classifier", "No realizado")) != "No realizado":
        classifier = str(data.get("genomic_classifier"))
        if classifier == "Oncotype":
            test_type = "OncotypeDX_GPS"
        else:
            test_type = classifier
    elif str(data.get("decipher_risk", "No realizado")) != "No realizado":
        test_type = "Decipher"
    elif _is_present(data.get("gps_score")):
        test_type = "OncotypeDX_GPS"
    elif _is_present(data.get("prolaris_score")):
        test_type = "Prolaris"

    actionable_findings = []
    if str(data.get("hrr_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append(f"HRR {data.get('hrr_gene') or 'documentado'}")
    if str(data.get("brca2_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append("BRCA2")
    if _is_truthy(data.get("tmb_high")):
        actionable_findings.append("TMB-high")
    if str(data.get("genomic_classifier_result", "No aplica")) not in {"", "No aplica"}:
        actionable_findings.append(
            f"{test_type}:{data.get('genomic_classifier_result')}"
        )
    if _present_text := str(data.get("biomarker_source") or data.get("molecular_assay_source") or "").strip():
        actionable_findings.append(f"Fuente:{_present_text}")

    return {
        "test_date": data.get("molecular_report_date") or data.get("molecular_assay_date") or datetime.now().strftime("%Y-%m-%d"),
        "test_type": test_type,
        "decipher_score": _safe_float(data.get("decipher_score"), None),
        "decipher_risk": None if str(data.get("decipher_risk", "No realizado")) == "No realizado" else data.get("decipher_risk"),
        "prolaris_score": _safe_float(data.get("prolaris_score"), None),
        "gps_score": _safe_float(data.get("gps_score"), None),
        "brca2_status": data.get("brca2_status"),
        "msi_status": data.get("msi_status"),
        "hrr_overall": data.get("hrr_status", "Desconocido"),
        "tmb_score": 10 if _is_truthy(data.get("tmb_high")) else None,
        "actionable_findings": actionable_findings,
        "brca1_status": "Desconocido",
        "atm_status": "Mutado" if str(data.get("hrr_gene")) == "ATM" else "Desconocido",
        "chek2_status": "Mutado" if str(data.get("hrr_gene")) == "CHEK2" else "Desconocido",
        "palb2_status": "Mutado" if str(data.get("hrr_gene")) == "PALB2" else "Desconocido",
        "cdk12_status": "Mutado" if str(data.get("hrr_gene")) == "CDK12" else "Desconocido",
    }


def _build_biopsy_payload(data):
    assessment_state = str(data.get("assessment_state") or "").strip()
    has_histology = _has_any_value(
        data,
        [
            "gleason_primary",
            "gleason_secondary",
            "isup_grade",
            "positive_cores",
            "num_cores_positive",
            "total_cores",
            "percent_pattern_4",
            "cribriform_pattern",
            "intraductal_carcinoma",
        ],
    )
    if assessment_state in {"diagnostic_workup", "post_negative_biopsy_followup"} or not has_histology:
        return None
    adverse_histology_variant_type = str(data.get("adverse_histology_variant_type", "none") or "none").strip()
    if adverse_histology_variant_type == "none" and _is_truthy(data.get("rare_histology_variant")):
        adverse_histology_variant_type = "other_aggressive_unspecified"
    adverse_histology_variant_detail = str(data.get("adverse_histology_variant_detail", "") or "").strip()
    positive_cores = _safe_int(data.get("num_cores_positive"), None)
    if positive_cores is None:
        positive_cores = _safe_int(data.get("positive_cores"), 0)
    return {
        "biopsy_date": data.get("biopsy_date") or data.get("prior_biopsy_date") or data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
        "biopsy_type": data.get("biopsy_type") or data.get("prior_biopsy_type") or data.get("planned_biopsy_type") or "sistematica",
        "biopsy_context": "rebiopsia" if data.get("assessment_state") == "post_negative_biopsy_followup" else "diagnostica",
        "total_cores": _safe_int(data.get("total_cores"), 12),
        "positive_cores": positive_cores,
        "gleason_primary": _safe_int(data.get("gleason_primary"), None),
        "gleason_secondary": _safe_int(data.get("gleason_secondary"), None),
        "isup_grade": _safe_int(data.get("isup_grade"), None),
        "porcentaje_patron_4": _safe_float(data.get("percent_pattern_4"), 0),
        "max_core_involvement_pct": _safe_float(data.get("max_core_involvement"), 0) * 100,
        "patron_cribiforme": 1 if _is_truthy(data.get("cribriform_pattern")) else 0,
        "carcinoma_intraductal": 1 if _is_truthy(data.get("intraductal_carcinoma")) else 0,
        "adverse_histology_variant_type": adverse_histology_variant_type,
        "adverse_histology_variant_detail": adverse_histology_variant_detail,
        "pathologist_notes": " | ".join(
            item
            for item in [
                str(data.get("repeat_biopsy_trigger") or "").strip(),
                "MRI-targeted previa" if _is_truthy(data.get("prior_biopsy_mri_targeted")) else "",
                f"Variante adversa: {adverse_histology_variant_type}" if adverse_histology_variant_type not in {"", "none"} else "",
                adverse_histology_variant_detail,
            ]
            if item
        ),
    }


def _build_pro_payload(data):
    if not _has_any_value(
        data,
        [
            "ipss_score",
            "ipss_total",
            "iief5_score",
            "bpi_worst_pain",
            "bpi_average_pain",
            "bpi_interference",
            "baseline_qol",
            "eq5d_vas",
            "fact_p_total",
            "facit_fatigue_total",
            "baseline_urinary_qol",
            "baseline_sexual_qol",
            "baseline_bowel_qol",
            "epic26_urinary_domain",
            "epic26_sexual_domain",
            "epic26_bowel_domain",
            "epic26_hormonal_domain",
            "eortc_qlq_c30_global_health",
            "eortc_qlq_c30_physical",
            "eortc_qlq_c30_role",
            "eortc_qlq_c30_emotional",
            "eortc_qlq_c30_fatigue",
            "eortc_qlq_c30_pain",
            "anxiety_score",
            "g8_total",
            "continence_status",
            "time_to_continence_months",
            "sexual_recovery_status",
            "time_to_erection_months",
        ],
    ):
        return None
    notes = []
    if data.get("baseline_urinary_qol") not in (None, ""):
        notes.append(f"Función urinaria basal 0-100: {data.get('baseline_urinary_qol')}")
    if data.get("baseline_sexual_qol") not in (None, ""):
        notes.append(f"Función sexual basal 0-100: {data.get('baseline_sexual_qol')}")
    if data.get("baseline_bowel_qol") not in (None, ""):
        notes.append(f"Función intestinal basal 0-100: {data.get('baseline_bowel_qol')}")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ipss_total": _safe_int(_first_nonempty(data.get("ipss_total"), data.get("ipss_score")), None),
        "iief5_score": _safe_int(data.get("iief5_score"), None),
        "bpi_worst_pain": _safe_int(data.get("bpi_worst_pain"), None),
        "bpi_average_pain": _safe_int(data.get("bpi_average_pain"), None),
        "bpi_interference": _safe_int(data.get("bpi_interference"), None),
        "eq5d_vas": _safe_int(_first_nonempty(data.get("eq5d_vas"), data.get("baseline_qol")), None),
        "fact_p_total": _safe_float(data.get("fact_p_total"), None),
        "facit_fatigue_total": _safe_float(data.get("facit_fatigue_total"), None),
        "g8_total": _safe_int(data.get("g8_total"), None),
        "continence_status": data.get("continence_status"),
        "time_to_continence_months": _safe_int(data.get("time_to_continence_months"), None),
        "sexual_recovery_status": data.get("sexual_recovery_status"),
        "time_to_erection_months": _safe_int(data.get("time_to_erection_months"), None),
        "epic26_urinary_domain": _safe_float(_first_nonempty(data.get("epic26_urinary_domain"), data.get("baseline_urinary_qol")), None),
        "epic26_sexual_domain": _safe_float(_first_nonempty(data.get("epic26_sexual_domain"), data.get("baseline_sexual_qol")), None),
        "epic26_bowel_domain": _safe_float(_first_nonempty(data.get("epic26_bowel_domain"), data.get("baseline_bowel_qol")), None),
        "epic26_hormonal_domain": _safe_float(data.get("epic26_hormonal_domain"), None),
        "eortc_qlq_c30_global_health": _safe_float(data.get("eortc_qlq_c30_global_health"), None),
        "eortc_qlq_c30_physical": _safe_float(data.get("eortc_qlq_c30_physical"), None),
        "eortc_qlq_c30_role": _safe_float(data.get("eortc_qlq_c30_role"), None),
        "eortc_qlq_c30_emotional": _safe_float(data.get("eortc_qlq_c30_emotional"), None),
        "eortc_qlq_c30_fatigue": _safe_float(data.get("eortc_qlq_c30_fatigue"), None),
        "eortc_qlq_c30_pain": _safe_float(data.get("eortc_qlq_c30_pain"), None),
        "anxiety_score": _safe_float(data.get("anxiety_score"), None),
        "clinician_notes": " | ".join(notes) if notes else None,
    }


def _should_enroll_as(data):
    return (
        data.get("assessment_state") == "localized_initial"
        and str(data.get("management_intent_status") or "").strip() in {"chosen", "delivered", "completed"}
        and str(data.get("selected_management") or "").strip() == "active_surveillance"
    )


def _build_bcr_payload(data):
    if data.get("assessment_state") not in {"post_prostatectomy", "recurrence_bcr"}:
        return None
    if not _has_any_value(data, ["time_to_recurrence_months", "local_therapy_date", "salvage_local_feasible", "local_salvage_candidate"]):
        return None
    primary_treatment = "RP" if _is_truthy(data.get("prior_prostatectomy")) or data.get("assessment_state") == "post_prostatectomy" else "RT"
    salvage_treatment = "observation"
    if _is_truthy(data.get("salvage_local_feasible")) or _is_truthy(data.get("local_salvage_candidate")):
        salvage_treatment = "sRT"
    bcr_psa = _safe_float(
        _first_nonempty(
            data.get("psa_current"),
            data.get("psa_postop"),
            data.get("psa"),
        ),
        None,
    )
    bcr_definition = "BCR2" if _is_truthy(data.get("bcr2")) else "BCR"
    bcr_detected = 1 if (
        data.get("assessment_state") == "recurrence_bcr"
        or bcr_definition == "BCR2"
        or (bcr_psa is not None and bcr_psa >= 0.2)
    ) else 0
    return {
        "primary_treatment": primary_treatment,
        "primary_treatment_date": data.get("local_therapy_date"),
        "bcr_detected": bcr_detected,
        "bcr_date": datetime.now().strftime("%Y-%m-%d"),
        "bcr_psa": bcr_psa,
        "bcr_definition": bcr_definition,
        "psadt_at_bcr": data.get("psadt_months"),
        "time_to_bcr_months": data.get("time_to_recurrence_months"),
        "salvage_treatment": salvage_treatment,
        "salvage_response": "pendiente",
    }


def _build_surgery_payload(data):
    if data.get("assessment_state") != "post_prostatectomy" and not _has_any_value(data, ["pathologic_stage", "margin_location", "surgical_margin"]):
        return None
    capra_s_score = None
    try:
        from clinical_scores import calculate_capra_s

        capra_s_score = calculate_capra_s(data).get("score")
    except Exception:
        capra_s_score = None
    return {
        "surgery_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
        "surgery_type": "RP_robotica",
        "pathological_gleason_primary": _safe_int(data.get("gleason_primary"), None),
        "pathological_gleason_secondary": _safe_int(data.get("gleason_secondary"), None),
        "pathological_isup": _safe_int(data.get("isup_grade"), None),
        "pathological_stage": data.get("pathologic_stage"),
        "surgical_margin_status": 1 if _is_truthy(data.get("surgical_margin")) else 0,
        "margin_location": data.get("margin_location"),
        "ece_pathological": 1 if _is_truthy(data.get("ece_status")) else 0,
        "svi_pathological": 1 if _is_truthy(data.get("svi_status")) else 0,
        "lni_pathological": 1 if _is_truthy(data.get("lni_status")) else 0,
        "capra_s_score": capra_s_score,
    }


def _build_radiation_payload(data):
    if not (_is_truthy(data.get("rt_primary_received")) or _is_truthy(data.get("prior_radiation"))):
        return None
    return {
        "rt_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
        "rt_context": "definitiva" if _is_truthy(data.get("rt_primary_received")) else "salvamento",
        "rt_technique": "IMRT",
        "target": "prostata" if _is_truthy(data.get("rt_primary_received")) else "lecho",
        "total_dose_gy": _safe_float(data.get("rt_primary_dose_gy"), 0),
        "fractions": None,
        "dose_per_fraction_gy": None,
    }


def _normalize_psa_history_points(
    raw_history,
    *,
    default_source="ingreso_inicial",
    default_entry_origin="intake_registration",
    default_sample_date="",
    default_context="otro",
    default_line_of_therapy_number=None,
    default_line_of_therapy_context="",
):
    if isinstance(raw_history, str):
        try:
            raw_history = json.loads(raw_history)
        except json.JSONDecodeError:
            raw_history = []
    if not isinstance(raw_history, list):
        return []
    normalized_history = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        sample_date = str(item.get("sample_date") or "")[:10]
        try:
            datetime.strptime(sample_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            sample_date = str(default_sample_date or "")[:10]
            try:
                datetime.strptime(sample_date, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
        psa_value = _safe_float(
            item.get("psa_value", item.get("value", item.get("psa"))),
            None,
        )
        if psa_value is None:
            continue
        assay_type = str(item.get("assay_type") or "desconocido").strip().lower()
        if assay_type not in {"estándar", "estandar", "ultrasensible", "desconocido"}:
            assay_type = "desconocido"
        context = str(item.get("context") or default_context or "otro").strip().lower()
        source = str(item.get("source") or item.get("lab_source") or default_source).strip()
        normalized_history.append(
            {
                "sample_date": sample_date,
                "psa_value": psa_value,
                "assay_type": "estándar" if assay_type == "estandar" else assay_type,
                "context": context or "otro",
                "source": source or default_source,
                "entry_origin": str(item.get("entry_origin") or default_entry_origin or "").strip() or default_entry_origin,
                "line_of_therapy_number": _safe_int(item.get("line_of_therapy_number", default_line_of_therapy_number), None),
                "line_of_therapy_context": str(item.get("line_of_therapy_context") or default_line_of_therapy_context or "").strip(),
            }
        )
    normalized_history.sort(key=lambda item: (item["sample_date"], item["psa_value"]))
    return normalized_history


def _normalize_testosterone_history_points(
    raw_history,
    *,
    default_source="ingreso_inicial",
    default_entry_origin="intake_registration",
    default_sample_date="",
    default_context="otro",
    default_line_of_therapy_number=None,
    default_line_of_therapy_context="",
    default_unit="ng/dL",
):
    if isinstance(raw_history, str):
        try:
            raw_history = json.loads(raw_history)
        except json.JSONDecodeError:
            raw_history = []
    if not isinstance(raw_history, list):
        return []
    normalized_history = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        sample_date = str(item.get("sample_date") or "")[:10]
        try:
            datetime.strptime(sample_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            sample_date = str(default_sample_date or "")[:10]
            try:
                datetime.strptime(sample_date, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
        testosterone_value = _safe_float(
            item.get("testosterone_value", item.get("value", item.get("testosterone"))),
            None,
        )
        if testosterone_value is None:
            continue
        context = str(item.get("context") or default_context or "otro").strip().lower()
        source = str(item.get("source") or item.get("lab_source") or default_source).strip()
        unit = str(item.get("unit") or default_unit or "ng/dL").strip() or "ng/dL"
        normalized_history.append(
            {
                "sample_date": sample_date,
                "testosterone_value": testosterone_value,
                "unit": unit,
                "context": context or "otro",
                "source": source or default_source,
                "entry_origin": str(item.get("entry_origin") or default_entry_origin or "").strip() or default_entry_origin,
                "line_of_therapy_number": _safe_int(item.get("line_of_therapy_number", default_line_of_therapy_number), None),
                "line_of_therapy_context": str(item.get("line_of_therapy_context") or default_line_of_therapy_context or "").strip(),
            }
        )
    normalized_history.sort(key=lambda item: (item["sample_date"], item["testosterone_value"]))
    return normalized_history


def _parse_intake_psa_history(data):
    raw_history = data.get("psa_history")
    if raw_history in (None, "", []):
        raw_history = data.get("ape_history")
    return _normalize_psa_history_points(
        raw_history,
        default_source="ingreso_inicial",
        default_entry_origin="intake_registration",
        default_context="otro",
    )


def _parse_intake_testosterone_history(data):
    return _normalize_testosterone_history_points(
        data.get("testosterone_history"),
        default_source="ingreso_inicial",
        default_entry_origin="intake_registration",
        default_context="otro",
    )


def _preferred_psa_longitudinal_value(data):
    """LXC.1 fix B1: incluye baseline_psa como fallback para auto-persist al register.

    PSA es el marcador por excelencia. Si el clínico captura solo `baseline_psa` en
    intake (sin psa_history array), debe persistirse igualmente a biomarker_longitudinal
    para que la torre de vigilancia lo refleje desde DB (no solo via auto-seed virtual).
    """
    value = _safe_float(
        _first_nonempty(
            data.get("psa_current"),
            data.get("psa_postop"),
            data.get("psa"),
            data.get("baseline_psa"),  # LXC.1 fix B1
            data.get("psa_baseline_ng_ml"),  # alias del intake-wizard quick classify
        ),
        None,
    )
    if value is None:
        return None, ""
    if _is_present(data.get("psa_current")):
        return value, "psa_current"
    if _is_present(data.get("psa_postop")):
        return value, "psa_postop"
    if _is_present(data.get("psa")):
        return value, "psa"
    if _is_present(data.get("baseline_psa")):
        return value, "baseline_psa"
    return value, "psa_baseline_ng_ml"


def _preferred_testosterone_longitudinal_value(data):
    value = _safe_float(
        _first_nonempty(
            data.get("testosterone_current"),
            data.get("testosterone_value"),
            data.get("testosterone"),
            data.get("testosterone_baseline"),
        ),
        None,
    )
    if value is None:
        return None, ""
    if _is_present(data.get("testosterone_current")):
        return value, "testosterone_current"
    if _is_present(data.get("testosterone_value")):
        return value, "testosterone_value"
    if _is_present(data.get("testosterone")):
        return value, "testosterone"
    return value, "testosterone_baseline"


def _preferred_psa_longitudinal_points(
    data,
    *,
    sample_date,
    default_source,
    default_entry_origin,
    default_context,
):
    value, source_field = _preferred_psa_longitudinal_value(data)
    if value is None:
        return []
    return _normalize_psa_history_points(
        [
            {
                "sample_date": sample_date,
                "psa_value": value,
                "assay_type": data.get("assay_type") or "desconocido",
                "context": data.get("assessment_context") or data.get("management_track") or data.get("assessment_state") or default_context,
                "source": default_source,
                "entry_origin": default_entry_origin,
                "line_of_therapy_number": data.get("line_of_therapy_number"),
                "line_of_therapy_context": data.get("line_of_therapy_context"),
                "source_field": source_field,
            }
        ],
        default_source=default_source,
        default_entry_origin=default_entry_origin,
        default_sample_date=sample_date,
        default_context=default_context,
        default_line_of_therapy_number=_safe_int(data.get("line_of_therapy_number"), None),
        default_line_of_therapy_context=str(data.get("line_of_therapy_context") or "").strip(),
    )


# Faubot LXXVII #67E — Public append-only API for v2 longitudinal capture.
# Estas funciones son thin wrappers sobre _persist_*_series_points existentes
# que aceptan NSS (no patient_id) y devuelven {success, appended_id, source}
# o {success:false, error:"duplicate", existing_id} si la fecha+valor existe.

def append_biomarker_longitudinal(nss_or_id, biomarker_type, sample_date,
                                   value, unit=None, context=None,
                                   assay=None, source="longitudinal_v2",
                                   extra_data=None):
    """Append-only insert a biomarker_longitudinal con check anti-duplicación.

    Args:
        nss_or_id: NSS o patient_id (resuelto vía _resolve_identity_row)
        biomarker_type: PSA / TESTOSTERONA / HEMOGLOBINA / ALP / LDH / etc.
        sample_date: ISO date string
        value: numeric
        unit: opcional
        context: opcional (clinical_context)
        assay: opcional
        source: opcional (default longitudinal_v2)
        extra_data: payload estructurado adicional preservado en lab_source

    Returns:
        {success, appended_id, source} o {success:false, error, existing_id}
    """
    import json as _json
    biomarker_upper = (biomarker_type or "").upper().strip()
    if not biomarker_upper:
        return {"success": False, "error": "missing_biomarker_type"}
    if not sample_date:
        return {"success": False, "error": "missing_sample_date"}
    if value is None:
        return {"success": False, "error": "missing_value"}

    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return {"success": False, "error": "patient_not_found", "nss": nss_or_id}
        patient_id = identity["id"] if hasattr(identity, "__getitem__") else identity[0]

        # Anti-duplicación: misma fecha + biomarker → 409
        cursor.execute(
            """
            SELECT id FROM biomarker_longitudinal
            WHERE patient_id = ? AND biomarker_type = ? AND sample_date = ?
            LIMIT 1
            """,
            (patient_id, biomarker_upper, sample_date),
        )
        existing = cursor.fetchone()
        if existing:
            existing_id = existing["id"] if hasattr(existing, "__getitem__") else existing[0]
            return {"success": False, "error": "duplicate", "existing_id": existing_id}

        extra_payload = extra_data if isinstance(extra_data, dict) else {}
        lab_source_blob = _json_blob({
            "context": context or "longitudinal_append",
            "assay_type": assay or "no_especificado",
            "source": source,
            "captured_via": "v2_longitudinal_capture_api",
            "line_of_therapy_number": extra_payload.get("line_of_therapy_number"),
            "line_of_therapy_context": extra_payload.get("line_of_therapy_context"),
            "drug_scheme": extra_payload.get("drug_scheme"),
            "extra_data": extra_payload,
        })
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal
            (patient_id, biomarker_type, value, unit, sample_date, lab_source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, biomarker_upper, value, unit, sample_date, lab_source_blob),
        )
        conn.commit()
        return {"success": True, "appended_id": cursor.lastrowid,
                "source": source, "biomarker_type": biomarker_upper}
    finally:
        conn.close()


def append_treatment_line_update(nss_or_id, payload):
    """Persist a longitudinal treatment-line change from the v2 append UI.

    This is the public write path for `kind=treatment_change`. It writes to
    `treatment_history`, closes the previous active systemic line when a new
    line starts, and emits a patient event so the PSA tower can bind PSA
    kinetics to ADT alone, doublet, triplet, or later-line therapy bands.
    """
    data = dict(payload or {})
    line_number = _safe_int(
        data.get("line_of_therapy_number")
        or data.get("line_of_therapy")
        or data.get("tx_line"),
        None,
    )
    line_context = str(
        data.get("line_of_therapy_context")
        or data.get("tx_context")
        or data.get("context")
        or ""
    ).strip()
    scheme = normalize_regimen_code(
        data.get("drug_scheme")
        or data.get("regimen_code")
        or data.get("tx_regimen")
        or data.get("current_treatment")
    )
    start_date = str(data.get("start_date") or data.get("tx_start") or data.get("date") or "")[:10]
    end_date = str(data.get("end_date") or data.get("tx_end") or "")[:10]

    if line_number is None:
        return {"success": False, "error": "missing_line_of_therapy_number"}
    if not _is_present(scheme):
        return {"success": False, "error": "missing_drug_scheme"}
    if not start_date:
        return {"success": False, "error": "missing_start_date"}
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return {"success": False, "error": "invalid_start_date"}
    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return {"success": False, "error": "invalid_end_date"}
        if end_date < start_date:
            return {"success": False, "error": "end_date_before_start_date"}

    raw_outcome = str(data.get("outcome") or data.get("tx_status") or data.get("status") or "").strip()
    raw_outcome_lower = raw_outcome.lower()
    if any(token in raw_outcome_lower for token in ("progres", "progress")):
        outcome = "Progression"
    elif any(token in raw_outcome_lower for token in ("toxic", "toxicidad")):
        outcome = "Toxicity"
    elif any(token in raw_outcome_lower for token in ("discontinu", "paciente")):
        outcome = "Discontinued"
    elif any(token in raw_outcome_lower for token in ("complet", "completed")):
        outcome = "Completed"
    elif end_date:
        outcome = "Completed"
    else:
        outcome = "Ongoing"

    try:
        from prostanet.domains.patient_tracking.psa_line_monitor import _classify_line_type

        line_type = _classify_line_type(scheme)
    except Exception:
        line_type = {"category": "", "label": "", "components_count": None}

    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return {"success": False, "error": "patient_not_found", "nss": nss_or_id}
        patient_id = identity["id"] if hasattr(identity, "__getitem__") else identity[0]

        cursor.execute(
            """
            SELECT id FROM treatment_history
            WHERE patient_id = ?
              AND line_of_therapy = ?
              AND drug_scheme = ?
              AND start_date = ?
            LIMIT 1
            """,
            (patient_id, line_number, scheme, start_date),
        )
        existing = cursor.fetchone()
        if existing:
            existing_id = existing["id"] if hasattr(existing, "__getitem__") else existing[0]
            return {"success": False, "error": "duplicate", "existing_id": existing_id}

        cursor.execute(
            """
            SELECT id, line_of_therapy, line_of_therapy_context, drug_scheme, start_date, outcome
            FROM treatment_history
            WHERE patient_id = ?
            ORDER BY start_date DESC, id DESC
            LIMIT 1
            """,
            (patient_id,),
        )
        latest = cursor.fetchone()
        previous = dict(latest) if latest else {}
        previous_is_active = str(previous.get("outcome") or "").lower() in {"", "ongoing", "activo"}
        previous_same_line = (
            previous
            and _safe_int(previous.get("line_of_therapy"), None) == line_number
            and normalize_regimen_code(previous.get("drug_scheme")) == scheme
            and (not line_context or line_context == str(previous.get("line_of_therapy_context") or ""))
        )
        if latest and previous_is_active and not previous_same_line:
            cursor.execute(
                """
                UPDATE treatment_history
                SET end_date = COALESCE(end_date, ?),
                    outcome = CASE
                        WHEN outcome IS NULL OR outcome = '' OR lower(outcome) IN ('ongoing', 'activo')
                        THEN 'Changed'
                        ELSE outcome
                    END
                WHERE id = ?
                """,
                (start_date, previous.get("id")),
            )

        regimen_payload = {
            "line_of_therapy_number": line_number,
            "line_of_therapy_context": line_context,
            "drug_scheme": scheme,
            "drug_scheme_label": regimen_label(scheme),
            "current_treatment": regimen_label(scheme),
            "current_adt_context": data.get("current_adt_context"),
            "castrate_testosterone_status": data.get("castrate_testosterone_status"),
            "line_type": line_type.get("category"),
            "line_type_label": line_type.get("label"),
            "components_count": line_type.get("components_count"),
            "captured_via": "longitudinal_v2_treatment_change",
            "reason_for_change": data.get("reason_for_change") or data.get("tx_reason"),
        }
        cursor.execute(
            """
            INSERT INTO treatment_history (
                patient_id, line_of_therapy, line_of_therapy_context, drug_scheme,
                start_date, end_date, outcome, regimen_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                line_number,
                line_context,
                scheme,
                start_date,
                end_date or None,
                outcome,
                _json_blob({k: v for k, v in regimen_payload.items() if _is_present(v)}),
            ),
        )
        inserted_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    event_id = record_patient_event(
        patient_id,
        event_type="therapy_line_changed" if previous else "therapy_started",
        event_date=start_date,
        source_type="longitudinal_v2_treatment_change",
        source_record_id=inserted_id,
        payload={
            "line_of_therapy_number": line_number,
            "line_of_therapy_context": line_context,
            "drug_scheme": scheme,
            "drug_scheme_label": regimen_label(scheme),
            "line_type": line_type.get("category"),
            "line_type_label": line_type.get("label"),
            "outcome": outcome,
            "start_date": start_date,
            "end_date": end_date,
            "previous_line_of_therapy_number": previous.get("line_of_therapy"),
            "previous_drug_scheme": previous.get("drug_scheme"),
            "decision": "Cambio de línea terapéutica confirmado para torre de APE por línea",
        },
        mcode_focus={
            "line_of_therapy_number": line_number,
            "line_of_therapy_context": line_context,
            "drug_scheme": scheme,
        },
    )
    return {
        "success": True,
        "appended_id": inserted_id,
        "event_id": event_id,
        "source": "longitudinal_v2_treatment_change",
        "line_of_therapy_number": line_number,
        "line_of_therapy_context": line_context,
        "drug_scheme": scheme,
        "drug_scheme_label": regimen_label(scheme),
        "line_type": line_type.get("category"),
        "line_type_label": line_type.get("label"),
        "outcome": outcome,
        "start_date": start_date,
        "end_date": end_date,
    }


# EPIC 22b — Structured biopsy longitudinal append (histopath capture gap fix)
def append_structured_biopsy_session(nss_or_id, payload):
    """Persist a structured biopsy session from the v2 longitudinal append UI.

    Public write path for `kind=biopsy` on /api/longitudinal/<nss>/append.

    Reuses `_save_structured_biopsy_session` (the canonical writer used by
    intake + stage visits) so all biopsy sessions land in `biopsy_sessions`
    table and feed `structured_biopsy_sessions` in patient_record derivatives.

    Also canonicalizes biopsy facts via `_persist_canonical_facts_from_payload`
    so downstream consumers (clinical_state_classifier, post_rp_salvage_copilot,
    risk_stratified_localized_copilot) read the new facts immediately without
    relying on legacy intake snapshots.

    Args:
        nss_or_id: patient NSS or patient_id
        payload: {
            biopsy_date (required, ISO date),
            biopsy_type ("systematic" | "mri_targeted" | "fusion" | "saturation"),
            biopsy_route ("transperineal" | "transrectal"),
            biopsy_context ("diagnostic" | "confirmatory_as" | "followup_as" | "rebiopsy"),
            gleason_primary (1-5), gleason_secondary (1-5), isup_grade (1-5),
            total_cores (int), positive_cores (int),
            percent_pattern_4 (0-100),
            margin_status ("negative" | "positive_focal" | "positive_extensive"),
            perineural_invasion (bool),
            mri_pirads_at_biopsy (1-5),
            systematic_cores (list[BiopsyCore]) — optional, computed from
                total/positive if absent,
            targeted_cores (list[BiopsyCore]) — optional,
            complications (list[str]),
            ...
        }

    Returns:
        {success:true, biopsy_session_id, biopsy_date, facts_persisted}
        or {success:false, error:"<...>"}
    """
    data = dict(payload or {})
    biopsy_date = str(data.get("biopsy_date") or data.get("date") or "")[:10]
    if not biopsy_date:
        return {"success": False, "error": "missing_biopsy_date"}
    try:
        datetime.strptime(biopsy_date, "%Y-%m-%d")
    except ValueError:
        return {"success": False, "error": "invalid_biopsy_date"}

    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return {"success": False, "error": "patient_not_found", "nss": nss_or_id}
        patient_id = identity["id"] if hasattr(identity, "__getitem__") else identity[0]

        # Anti-duplicación: misma fecha + biopsy_type → 409 (returns existing_id)
        biopsy_type_norm = (data.get("biopsy_type") or "systematic").strip()
        biopsy_context_norm = (data.get("biopsy_context") or "diagnostic").strip()
        session_key_candidate = _make_session_key(
            "bx", patient_id, biopsy_date, biopsy_type_norm, biopsy_context_norm
        )
        cursor.execute(
            "SELECT id FROM biopsy_sessions WHERE session_key = ? LIMIT 1",
            (session_key_candidate,),
        )
        existing = cursor.fetchone()
        if existing:
            existing_id = existing["id"] if hasattr(existing, "__getitem__") else existing[0]
            return {
                "success": False,
                "error": "duplicate",
                "existing_id": existing_id,
                "session_key": session_key_candidate,
            }

        # Persist biopsy_sessions + biopsy_cores rows (reuses canonical writer)
        session_id = _save_structured_biopsy_session(
            cursor,
            patient_id,
            data,
            source_type="longitudinal_capture_v2",
            source_record_id=None,
        )

        # Canonicalize biopsy facts so classifiers + copilots read them.
        # `extract_canonical_fact_candidates` already knows about:
        #   gleason_primary, gleason_secondary, isup_grade, biopsy_date,
        #   histology_subtype, confirmatory_biopsy_done, ...
        # EPIC 22b.5 adds gleason_at_rp, margin_status, percent_pattern_4,
        # perineural_invasion, etc. into FACT_SPECS so they also persist here.
        facts_payload = {
            **data,
            "biopsy_date": biopsy_date,
        }
        # If post-RP context, also normalize the "gleason at RP" alias so
        # FactSpec("gleason_at_rp") picks it up (EPIC 22b.5).
        if biopsy_context_norm in ("rp_specimen", "post_rp"):
            if data.get("gleason_primary") and data.get("gleason_secondary"):
                facts_payload.setdefault(
                    "gleason_at_rp",
                    f"{int(data['gleason_primary']) + int(data['gleason_secondary'])}"
                    f"({data['gleason_primary']}+{data['gleason_secondary']})",
                )

        facts_persisted = _persist_canonical_facts_from_payload(
            cursor,
            patient_id,
            facts_payload,
            source_type="wizard_or_intake",
            source_record_type="biopsy_session_v2",
            source_record_id=session_id,
            source_date=biopsy_date,
            observed_at=biopsy_date,
            state_context="biopsy_capture",
            management_track=str(data.get("management_track") or ""),
            certainty_tier="wizard_or_intake",
        )

        conn.commit()
        return {
            "success": True,
            "biopsy_session_id": session_id,
            "biopsy_date": biopsy_date,
            "facts_persisted": int(facts_persisted or 0),
            "session_key": session_key_candidate,
        }
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": f"persist_failed: {exc}"}
    finally:
        conn.close()


def _persist_psa_series_points(cursor, patient_id, points):
    persisted_points = 0
    for point in points:
        cursor.execute(
            """
            SELECT id FROM biomarker_longitudinal
            WHERE patient_id = ? AND biomarker_type = ? AND sample_date = ? AND value = ?
            LIMIT 1
            """,
            (patient_id, "PSA", point["sample_date"], point["psa_value"]),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                "PSA",
                point["psa_value"],
                "ng/mL",
                point["sample_date"],
                _json_blob(
                    {
                        "entry_origin": point.get("entry_origin") or "intake_registration",
                        "context": point.get("context") or "otro",
                        "assay_type": point.get("assay_type") or "desconocido",
                        "source": point.get("source") or "ingreso_inicial",
                        "line_of_therapy_number": point.get("line_of_therapy_number"),
                        "line_of_therapy_context": point.get("line_of_therapy_context") or "",
                    }
                ),
            ),
        )
        persisted_points += 1
    return persisted_points


def _persist_testosterone_series_points(cursor, patient_id, points):
    persisted_points = 0
    for point in points:
        cursor.execute(
            """
            SELECT id FROM biomarker_longitudinal
            WHERE patient_id = ? AND biomarker_type = ? AND sample_date = ? AND value = ?
            LIMIT 1
            """,
            (patient_id, "TESTOSTERONA", point["sample_date"], point["testosterone_value"]),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                "TESTOSTERONA",
                point["testosterone_value"],
                point.get("unit") or "ng/dL",
                point["sample_date"],
                _json_blob(
                    {
                        "entry_origin": point.get("entry_origin") or "intake_registration",
                        "context": point.get("context") or "otro",
                        "source": point.get("source") or "ingreso_inicial",
                        "unit": point.get("unit") or "ng/dL",
                        "line_of_therapy_number": point.get("line_of_therapy_number"),
                        "line_of_therapy_context": point.get("line_of_therapy_context") or "",
                    }
                ),
            ),
        )
        persisted_points += 1
    return persisted_points


def _derive_baseline_psa_from_history(data, psa_history):
    explicit_baseline = _safe_float(data.get("baseline_psa"), None)
    if explicit_baseline is not None:
        return explicit_baseline, None
    pretreatment_points = [
        item
        for item in psa_history
        if item.get("context") in {"pretratamiento", "pretreatment", "baseline", "diagnostic"}
    ]
    if not pretreatment_points:
        return None, None
    selected_point = max(pretreatment_points, key=lambda item: item.get("sample_date", ""))
    return selected_point.get("psa_value"), selected_point


def _preferred_testosterone_longitudinal_points(
    data,
    *,
    sample_date,
    default_source,
    default_entry_origin,
    default_context,
):
    value, _source_field = _preferred_testosterone_longitudinal_value(data)
    if value is None:
        return []
    return _normalize_testosterone_history_points(
        [
            {
                "sample_date": sample_date,
                "testosterone_value": value,
                "unit": data.get("testosterone_unit") or "ng/dL",
                "context": data.get("assessment_context") or data.get("management_track") or data.get("assessment_state") or default_context,
                "source": default_source,
                "entry_origin": default_entry_origin,
                "line_of_therapy_number": data.get("line_of_therapy_number"),
                "line_of_therapy_context": data.get("line_of_therapy_context"),
            }
        ],
        default_source=default_source,
        default_entry_origin=default_entry_origin,
        default_sample_date=sample_date,
        default_context=default_context,
        default_line_of_therapy_number=_safe_int(data.get("line_of_therapy_number"), None),
        default_line_of_therapy_context=str(data.get("line_of_therapy_context") or "").strip(),
        default_unit=str(data.get("testosterone_unit") or "ng/dL"),
    )


def _derive_baseline_testosterone_from_history(data, testosterone_history):
    explicit_baseline = _safe_float(data.get("testosterone_baseline"), None)
    if explicit_baseline is not None:
        return explicit_baseline, None
    pretreatment_points = [
        item
        for item in testosterone_history
        if item.get("context") in {"pretratamiento", "pretreatment", "baseline", "diagnostic"}
    ]
    if not pretreatment_points:
        return None, None
    selected_point = max(pretreatment_points, key=lambda item: item.get("sample_date", ""))
    return selected_point.get("testosterone_value"), selected_point


def _derive_bmi_from_weight_height(weight_kg, height_cm):
    weight = _safe_float(weight_kg, None)
    height = _safe_float(height_cm, None)
    if weight is None or height is None or weight <= 0 or height <= 0:
        return None
    height_m = height / 100.0
    if height_m <= 0:
        return None
    return round(weight / (height_m * height_m), 1)


def _derive_weight_loss_percent(weight_kg, weight_loss_kg):
    current_weight = _safe_float(weight_kg, None)
    loss_kg = _safe_float(weight_loss_kg, None)
    if current_weight is None or loss_kg is None or current_weight <= 0 or loss_kg < 0:
        return None, None
    prior_weight = current_weight + loss_kg
    if prior_weight <= 0:
        return None, None
    return round((loss_kg / prior_weight) * 100, 1), round(prior_weight, 1)


def _apply_anthropometric_derivations(data):
    if not isinstance(data, dict):
        return data
    weight_kg = _safe_float(data.get("weight_kg"), None)
    height_cm = _safe_float(data.get("height_cm"), None)
    derived_bmi = _derive_bmi_from_weight_height(weight_kg, height_cm)
    if derived_bmi is not None:
        data["bmi_current"] = derived_bmi
    elif _is_present(data.get("bmi_current")):
        data["bmi_current"] = _safe_float(data.get("bmi_current"), None)

    weight_loss_kg = _safe_float(data.get("weight_loss_6m_kg"), None)
    derived_pct, prior_weight = _derive_weight_loss_percent(weight_kg, weight_loss_kg)
    if weight_loss_kg is not None:
        data["weight_loss_6m_kg"] = weight_loss_kg
    if derived_pct is not None:
        data["weight_loss_6m_pct"] = derived_pct
    elif _is_present(data.get("weight_loss_6m_pct")):
        data["weight_loss_6m_pct"] = _safe_float(data.get("weight_loss_6m_pct"), None)
    if prior_weight is not None:
        data["prior_weight_6m_kg"] = prior_weight
    if height_cm is not None:
        data["height_cm"] = height_cm
    return data


def _persist_intake_biomarker_series(cursor, patient_id, diagnosis_date, data):
    psa_history = _parse_intake_psa_history(data)
    testosterone_history = _parse_intake_testosterone_history(data)
    baseline_was_explicit = _is_present(data.get("baseline_psa"))
    baseline_psa_value, selected_baseline_point = _derive_baseline_psa_from_history(data, psa_history)
    if baseline_psa_value is not None and not baseline_was_explicit:
        data["baseline_psa"] = baseline_psa_value
    testosterone_baseline_was_explicit = _is_present(data.get("testosterone_baseline"))
    baseline_testosterone_value, selected_testosterone_baseline_point = _derive_baseline_testosterone_from_history(data, testosterone_history)
    if baseline_testosterone_value is not None and not testosterone_baseline_was_explicit:
        data["testosterone_baseline"] = baseline_testosterone_value

    persisted_points = _persist_psa_series_points(cursor, patient_id, psa_history)
    persisted_testosterone_points = _persist_testosterone_series_points(cursor, patient_id, testosterone_history)
    scalar_psa_points = []
    if not (selected_baseline_point and not baseline_was_explicit):
        scalar_psa_points = _preferred_psa_longitudinal_points(
            data,
            sample_date=data.get("local_therapy_date") or diagnosis_date,
            default_source="ingreso_inicial",
            default_entry_origin="intake_registration",
            default_context="otro",
        )
    if scalar_psa_points:
        persisted_points += _persist_psa_series_points(cursor, patient_id, scalar_psa_points)
    scalar_testosterone_points = _preferred_testosterone_longitudinal_points(
        data,
        sample_date=data.get("local_therapy_date") or diagnosis_date,
        default_source="ingreso_inicial",
        default_entry_origin="intake_registration",
        default_context="otro",
    )
    if scalar_testosterone_points:
        persisted_testosterone_points += _persist_testosterone_series_points(cursor, patient_id, scalar_testosterone_points)
    baseline_point = dict(selected_baseline_point) if selected_baseline_point else None
    testosterone_baseline_point = dict(selected_testosterone_baseline_point) if selected_testosterone_baseline_point else None

    explicit_baseline = _safe_float(data.get("baseline_psa"), None)
    if baseline_point is None and explicit_baseline is not None:
        baseline_point = {
            "sample_date": "",
            "psa_value": explicit_baseline,
            "context": "baseline",
            "assay_type": "desconocido",
            "source": "campo_baseline_psa",
        }
    explicit_testosterone_baseline = _safe_float(data.get("testosterone_baseline"), None)
    if testosterone_baseline_point is None and explicit_testosterone_baseline is not None:
        testosterone_baseline_point = {
            "sample_date": "",
            "testosterone_value": explicit_testosterone_baseline,
            "context": "baseline",
            "unit": str(data.get("testosterone_unit") or "ng/dL"),
            "source": "campo_testosterone_baseline",
        }

    return {
        "points_received": len(psa_history),
        "points_persisted": persisted_points,
        "baseline_psa": explicit_baseline if explicit_baseline is not None else baseline_psa_value,
        "baseline_source": "explicit_field" if baseline_was_explicit and selected_baseline_point is None else "derived_from_history" if selected_baseline_point else "not_available",
        "baseline_point": baseline_point,
        "series_only_points": max(len(psa_history) - (1 if baseline_point and selected_baseline_point else 0), 0),
        "testosterone_points_received": len(testosterone_history),
        "testosterone_points_persisted": persisted_testosterone_points,
        "baseline_testosterone": explicit_testosterone_baseline if explicit_testosterone_baseline is not None else baseline_testosterone_value,
        "baseline_testosterone_source": "explicit_field" if testosterone_baseline_was_explicit and selected_testosterone_baseline_point is None else "derived_from_history" if selected_testosterone_baseline_point else "not_available",
        "baseline_testosterone_point": testosterone_baseline_point,
    }

def register_new_patient(data, assessment=None):
    """
    Registra un nuevo paciente y su línea base clínica + tratamiento inicial.
    Retorna (success: bool, message: str)
    """
    conn = None
    try:
        data = apply_gleason_profile(dict(data or {}))
        data = _apply_anthropometric_derivations(data)
        assessment_state = str(data.get("assessment_state") or "").strip()
        advanced_states = {
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        }
        conn = _connect(write=True)
        c = conn.cursor()
        
        # 1. Identidad
        diagnosis_date = datetime.now().strftime("%Y-%m-%d")
        try:
            c.execute('''
                INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date)
                VALUES (?, ?, ?, DATE('now'))
            ''', (data.get('nss'), data.get('full_name'), data.get('dob')))
            patient_id = c.lastrowid
        except sqlite3.IntegrityError:
            return None, f"El paciente con NSS {data.get('nss')} ya existe.", {}

        # 2. Perfil Clínico Basal
        comorbilidades = json.dumps({
            'seizure': _is_truthy(data.get('comorbidity_seizure')),
            'cardio': _is_truthy(data.get('comorbidity_cardio'))
        })
        metastatic = _derive_metastatic_payload(data)
        metastasis_site = metastatic["metastasis_site"] or 'M0'
        metastatic_count = _safe_int(metastatic["metastasis_count"], 0)
        if metastasis_site != 'M0' and metastatic_count == 0:
            metastatic_count = 1
        genomic_done = 1 if _is_truthy(data.get('genomic_test_done')) else 0
        if not genomic_done and _has_any_value(data, ['hrr_status', 'hrr_gene', 'biomarker_source', 'molecular_report_date', 'genomic_classifier', 'decipher_risk']):
            genomic_done = 1
        psa_history_summary = _persist_intake_biomarker_series(c, patient_id, diagnosis_date, data)
        
        c.execute('''
            INSERT INTO clinical_baseline (
                patient_id, baseline_psa, testosterone_baseline, hemoglobin, alp, ldh, albumin,
                tnm_stage, gleason_score, gleason_primary, gleason_secondary, gleason_tertiary, isup_grade,
                histology_subtype, clinical_tstage, nodal_status, clinical_stage_group, clinical_risk_group,
                life_expectancy_years, dre_suspicious, prior_biopsy_count, local_treatment_consideration,
                metastasis_site, metastasis_count, m_substage_resolved,
                metastatic_profile_json, metastasis_assessment_date, metastasis_document_source, volume_disease,
                ecog_score, peripheral_neuropathy_grade,
                genomic_test_done, hrr_status, msi_status, child_pugh_score, pain_symptoms,
                comorbidities_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            data.get('baseline_psa'), data.get('testosterone_baseline'),
            data.get('hemoglobin'), data.get('alp'), data.get('ldh'), data.get('albumin'),
            'TxNxMx', # Placeholder o derivado
            _safe_int(data.get('gleason_score'), None),
            _safe_int(data.get('gleason_primary'), None),
            _safe_int(data.get('gleason_secondary'), None),
            _safe_int(data.get('gleason_tertiary'), None),
            _safe_int(data.get('isup_grade'), None),
            data.get('histology_subtype'),
            data.get('clinical_tstage'),
            data.get('nodal_status'),
            data.get('clinical_stage_group'),
            data.get('clinical_risk_group'),
            _safe_float(data.get('life_expectancy_years'), None),
            1 if _is_truthy(data.get('dre_suspicious')) else 0,
            _safe_int(data.get('prior_biopsy_count'), 0),
            data.get('local_treatment_consideration'),
            metastasis_site,
            metastatic_count,
            metastatic["m_substage_resolved"],
            metastatic["metastatic_profile_json"],
            metastatic["metastasis_assessment_date"],
            metastatic["metastasis_document_source"],
            metastatic["volume_disease"],
            _safe_int(data.get('ecog_score'), None),
            _safe_int(data.get("peripheral_neuropathy_grade"), None),
            genomic_done,
            data.get('hrr_status'),
            data.get('msi_status'),
            data.get('child_pugh_score'),
            data.get('pain_symptoms'),
            comorbilidades
        ))
        _persist_official_diagnosis_fields(c, patient_id, data)

        # 3. Historial Terapéutico Inicial
        normalized_scheme = normalize_regimen_code(data.get("drug_scheme"))
        should_persist_treatment = bool(normalized_scheme) and (not assessment_state or assessment_state in advanced_states)
        if should_persist_treatment:
            line_number = _normalize_line_of_therapy_number(data)
            line_context = _normalize_line_of_therapy_context(data)
            c.execute('''
                INSERT INTO treatment_history (
                    patient_id, line_of_therapy, line_of_therapy_context, drug_scheme, start_date, outcome, regimen_json
                ) VALUES (?, ?, ?, ?, DATE('now'), 'Ongoing', ?)
            ''', (
                patient_id,
                line_number,
                line_context,
                normalized_scheme,
                _json_blob(
                    {
                        "line_of_therapy_number": line_number,
                        "line_of_therapy_context": line_context,
                        "current_treatment": regimen_label(normalized_scheme),
                        "drug_scheme": normalized_scheme,
                        "drug_scheme_label": regimen_label(normalized_scheme),
                        "current_adt_context": data.get("current_adt_context"),
                        "castrate_testosterone_status": data.get("castrate_testosterone_status"),
                    }
                ),
            ))

        # 4. Historial Clínico Previo (Fase 6)
        c.execute('''
            INSERT INTO prior_clinical_history (
                patient_id,
                rt_primary_received, rt_primary_dose_gy, rt_metastasis_history,
                prior_docetaxel_cycles, prior_arpi_agent, prior_arpi_duration,
                assessment_source, assessment_module, assessment_state,
                assessment_summary, current_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            1 if _is_truthy(data.get('rt_primary_received')) else 0,
            _safe_float(data.get('rt_primary_dose_gy'), 0),
            data.get('rt_metastasis_history', '[]'), # JSON string expected
            _safe_int(data.get('prior_docetaxel_cycles'), 0),
            data.get('prior_arpi_agent'),
            _safe_int(data.get('prior_arpi_duration'), 0),
            data.get("assessment_source") or ("intake_stage_aware_v2" if data.get("_classified_state") else "manual_registration"),
            data.get("assessment_module") or assessment_state or "",
            assessment_state or "",
            data.get("classification_reason") or data.get("_classification_reason") or "",
            assessment_state or "diagnostic_workup",
        ))
        _persist_canonical_facts_from_payload(
            c,
            patient_id,
            {
                **data,
                "metastasis_site": metastasis_site,
                "metastasis_count": metastatic_count,
                "m_substage_resolved": metastatic["m_substage_resolved"],
                "metastasis_assessment_date": metastatic["metastasis_assessment_date"],
                "metastasis_document_source": metastatic["metastasis_document_source"],
            },
            source_type="wizard_or_intake",
            source_record_type="patient_registration",
            source_record_id=patient_id,
            source_date=diagnosis_date,
            observed_at=diagnosis_date,
            state_context=assessment_state or "diagnostic_workup",
            management_track=str(data.get("management_track") or ""),
            certainty_tier="wizard_or_intake",
        )

        conn.commit()

        if _has_any_value(data, [
            'estado_residencia', 'seguridad_social', 'escolaridad', 'tabaquismo', 'ipss_score', 'iief5_score',
            'g8_food_intake', 'g8_weight_loss', 'g8_mobility', 'g8_neuropsych', 'g8_bmi', 'g8_medications',
            'g8_self_health', 'mini_cog_score', 'fatigue_score', 'weight_kg', 'height_cm', 'bmi_current',
            'weight_loss_6m_kg', 'weight_loss_6m_pct', 'low_activity', 'slow_gait', 'weak_grip', 'line_of_therapy_number',
            'line_of_therapy_context',
        ]):
            save_demographics(
                patient_id,
                {
                    **data,
                    'diabetes_mellitus': 1 if _is_truthy(data.get('diabetes_mellitus')) else 0,
                    'hipertension': 1 if _is_truthy(data.get('hipertension')) else 0,
                    'sindrome_metabolico': 1 if _is_truthy(data.get('sindrome_metabolico')) else 0,
                },
            )

        relatives = _build_family_history_relatives(data)
        if relatives:
            save_family_history(patient_id, relatives)

        for imaging_payload in _build_imaging_payloads(data):
            save_imaging_study(patient_id, imaging_payload)

        mri_fact_payload = _build_mri_fact_payload(data)
        if mri_fact_payload:
            save_mri_fact(
                patient_id,
                {
                    **mri_fact_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        diagnostic_plan_payload = _build_diagnostic_plan_payload(data, assessment)
        if diagnostic_plan_payload:
            save_diagnostic_plan(
                patient_id,
                {
                    **diagnostic_plan_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        biopsy_trigger_payload = _build_biopsy_trigger_payload(data, assessment)
        if biopsy_trigger_payload:
            save_biopsy_trigger(
                patient_id,
                {
                    **biopsy_trigger_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        genomic_payload = _build_genomic_payload(data)
        if genomic_payload:
            save_genomic_profile(patient_id, genomic_payload)

        biopsy_payload = _build_biopsy_payload(data)
        if biopsy_payload:
            save_biopsy(patient_id, biopsy_payload)

        pro_payload = _build_pro_payload(data)
        if pro_payload:
            save_pro_assessment(patient_id, pro_payload)

        if _should_enroll_as(data):
            enroll_in_as(
                patient_id,
                {
                    "protocol": "NCCN_VL",
                    "criteria_met": {
                        "confirmatory_biopsy_planned": _is_truthy(data.get("confirmatory_biopsy_planned")),
                        "prior_mpmri": _is_truthy(data.get("prior_mpmri")),
                    },
                },
            )

        bcr_payload = _build_bcr_payload(data)
        if bcr_payload:
            save_bcr(patient_id, bcr_payload)

        surgery_payload = _build_surgery_payload(data)
        if surgery_payload:
            save_surgical_details(patient_id, surgery_payload)

        radiation_payload = _build_radiation_payload(data)
        if radiation_payload:
            save_radiation_details(patient_id, radiation_payload)

        logger.info(f"Paciente {data.get('nss')} registrado con éxito (ID: {patient_id})")
        return patient_id, "Registro exitoso", {"psa_history_summary": psa_history_summary}

    except Exception as e:
        logger.error(f"Error registering patient: {e}")
        return None, str(e), {}
    finally:
        _close_connection_quietly(conn)

def get_patient_history(nss_or_id):
    return get_patient_full_record(nss_or_id)

def add_followup_visit(data):
    """
    Registra una visita de seguimiento.
    data: {patient_id, psa, testosterone, toxicity, metabolic, treatment, status}
    """
    return save_stage_visit_bundle(int(data.get("patient_id")), data)


def _normalize_list_value(value):
    if isinstance(value, list):
        return [item for item in value if _is_present(item)]
    if value in (None, ""):
        return []
    return [value]


def _derive_metastatic_payload(data):
    profile = build_metastatic_profile(data)
    legacy_site, legacy_count, m_substage = derive_legacy_metastasis(data)
    return {
        "metastatic_profile": profile,
        "metastatic_profile_json": _json_blob(profile),
        "metastasis_site": legacy_site,
        "metastasis_count": legacy_count,
        "m_substage_resolved": m_substage,
        "metastasis_assessment_date": profile.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date"),
        "metastasis_document_source": profile.get("metastasis_document_source") or "",
        "volume_disease": data.get("volume_disease") or profile.get("metastasis_volume_context") or "",
    }


def _merged_metastatic_context(record, data):
    merged = {}
    truth_values = ((record or {}).get("longitudinal_truth_snapshot") or {}).get("field_values") or {}
    latest_assessment_inputs = (((record or {}).get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = (record or {}).get("latest_signal_snapshot") or {}
    latest_stage_visit = ((record or {}).get("stage_visits") or [{}])[-1] if (record or {}).get("stage_visits") else {}
    latest_stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    latest_followup = ((record or {}).get("follow_ups") or [{}])[-1] if (record or {}).get("follow_ups") else {}

    for source in (
        (record or {}).get("baseline") or {},
        truth_values,
        latest_assessment_inputs,
        latest_signal_snapshot,
        latest_stage_payload,
        latest_followup,
        data or {},
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}):
                merged[key] = value
    return merged


def _normalize_stage_component(value, prefix):
    if not _is_present(value):
        return ""
    text = str(value).strip().upper()
    text = text.replace(f"C{prefix}", prefix)
    match = None
    if prefix == "T":
        match = re.search(r"T(X|[0-4][ABC]?)", text)
    elif prefix == "N":
        match = re.search(r"N(X|0|1)", text)
    elif prefix == "M":
        match = re.search(r"M(X|0|1[ABC]?)", text)
    if not match:
        return ""
    stage = f"{prefix}{match.group(1)}"
    if stage in {"TX", "NX", "MX"}:
        return ""
    return stage[0] + stage[1:].lower() if prefix == "M" else stage


def _parse_tnm_stage(value):
    text = str(value or "")
    return (
        _normalize_stage_component(text, "T"),
        _normalize_stage_component(text, "N"),
        _normalize_stage_component(text, "M"),
    )


def _official_diagnosis_values(data, existing=None):
    existing = existing or {}
    merged = dict(existing)
    merged.update(dict(data or {}))
    merged = apply_gleason_profile(merged)
    metastatic = _derive_metastatic_payload(data)
    existing_t, existing_n, existing_m = _parse_tnm_stage(existing.get("tnm_stage"))
    clinical_tstage = _normalize_stage_component(
        data.get("clinical_tstage") or existing.get("clinical_tstage") or existing_t,
        "T",
    )
    nodal_status = _normalize_stage_component(
        data.get("nodal_status") or existing.get("nodal_status") or existing_n,
        "N",
    )
    m_substage = _normalize_stage_component(
        metastatic.get("m_substage_resolved") or existing.get("m_substage_resolved") or existing_m,
        "M",
    )
    tnm_stage = ""
    if clinical_tstage or nodal_status or m_substage:
        tnm_stage = f"{clinical_tstage or 'Tx'}{nodal_status or 'Nx'}{m_substage or 'Mx'}"
    gleason_primary = _safe_int(merged.get("gleason_primary"), None)
    gleason_secondary = _safe_int(merged.get("gleason_secondary"), None)
    gleason_tertiary = _safe_int(merged.get("gleason_tertiary"), None)
    gleason_profile = normalize_gleason_profile(merged)
    gleason_score = gleason_profile.get("gleason_score")
    isup_grade = gleason_profile.get("isup_grade")
    histology_subtype = str(data.get("histology_subtype") or "").strip() or None
    clinical_stage_group = str(data.get("clinical_stage_group") or "").strip() or None
    clinical_risk_group = str(data.get("clinical_risk_group") or "").strip() or None
    return {
        "histology_subtype": histology_subtype,
        "clinical_tstage": clinical_tstage or None,
        "nodal_status": nodal_status or None,
        "clinical_stage_group": clinical_stage_group,
        "clinical_risk_group": clinical_risk_group,
        "tnm_stage": tnm_stage or None,
        "gleason_primary": gleason_primary,
        "gleason_secondary": gleason_secondary,
        "gleason_tertiary": gleason_tertiary,
        "isup_grade": isup_grade,
        "gleason_score": gleason_score,
    }


def _persist_official_diagnosis_fields(cursor, patient_id, data):
    cursor.execute(
        """
        SELECT id, tnm_stage, histology_subtype, clinical_tstage, nodal_status, clinical_stage_group, clinical_risk_group,
               gleason_score, gleason_primary, gleason_secondary, gleason_tertiary, isup_grade
        FROM clinical_baseline
        WHERE patient_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    existing = {
        "tnm_stage": row[1],
        "histology_subtype": row[2],
        "clinical_tstage": row[3],
        "nodal_status": row[4],
        "clinical_stage_group": row[5],
        "clinical_risk_group": row[6],
        "gleason_score": row[7],
        "gleason_primary": row[8],
        "gleason_secondary": row[9],
        "gleason_tertiary": row[10],
        "isup_grade": row[11],
    }
    values = _official_diagnosis_values(data, existing=existing)
    if not any(_is_present(value) for value in values.values()):
        return
    cursor.execute(
        """
        UPDATE clinical_baseline
        SET histology_subtype = COALESCE(?, histology_subtype),
            clinical_tstage = COALESCE(?, clinical_tstage),
            nodal_status = COALESCE(?, nodal_status),
            clinical_stage_group = COALESCE(?, clinical_stage_group),
            clinical_risk_group = COALESCE(?, clinical_risk_group),
            tnm_stage = COALESCE(?, tnm_stage),
            gleason_primary = COALESCE(?, gleason_primary),
            gleason_secondary = COALESCE(?, gleason_secondary),
            gleason_tertiary = COALESCE(?, gleason_tertiary),
            isup_grade = COALESCE(?, isup_grade),
            gleason_score = COALESCE(?, gleason_score)
        WHERE id = ?
        """,
        (
            values.get("histology_subtype"),
            values.get("clinical_tstage"),
            values.get("nodal_status"),
            values.get("clinical_stage_group"),
            values.get("clinical_risk_group"),
            values.get("tnm_stage"),
            values.get("gleason_primary"),
            values.get("gleason_secondary"),
            values.get("gleason_tertiary"),
            values.get("isup_grade"),
            values.get("gleason_score"),
            row[0],
        ),
    )


def _build_imaging_payload_from_visit(data):
    modality = data.get("imaging_modality")
    if not _is_present(modality):
        return None
    findings = {}
    if modality == "PSMA-PET":
        findings = {
            "psma_suv_bucket": data.get("psma_suv_bucket"),
        }
        return normalize_psma_imaging_payload(
            {
                "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
                "study_type": "PSMA-PET",
                "psma_result": "Positivo" if _normalize_list_value(data.get("psma_lesion_locations")) or _safe_float(data.get("psma_suv_max")) else "Negativo/indeterminado",
                "psma_suv_max": _safe_float(data.get("psma_suv_max"), None),
                "psma_radioligand": data.get("psma_radioligand"),
                "psma_index_lesion_site": data.get("psma_index_lesion_site"),
                "psma_index_lesion_suvmax": _safe_float(data.get("psma_index_lesion_suvmax"), None),
                "psma_uptake_pattern": data.get("psma_uptake_pattern"),
                "psma_rads_score": data.get("psma_rads_score"),
                "psma_total_lesions": _safe_int(data.get("psma_total_lesions"), 0),
                "psma_lesion_locations": _normalize_list_value(data.get("psma_lesion_locations")),
                "psma_negative_dominant_lesions": _is_truthy(data.get("psma_negative_dominant_lesions")),
                "conventional_stage_before_psma": data.get("conventional_stage_before_psma") or data.get("conventional_imaging_status"),
                "psma_stage_after_psma": data.get("psma_stage_after_psma"),
                "psma_upstaged_vs_conventional": data.get("psma_upstaged_vs_conventional"),
                "psma_management_changed": data.get("psma_management_changed"),
                "findings": findings,
            }
        )
    if modality == "Gammagrama óseo":
        findings = {
            "distribution": _normalize_list_value(data.get("bone_distribution")),
            "bone_lesion_count": _safe_int(data.get("bone_lesion_count"), 0),
        }
        return {
            "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
            "study_type": "Gammagrama óseo",
            "bone_scan_result": "Positivo" if findings["bone_lesion_count"] else "Negativo/indeterminado",
            "bone_lesion_count": findings["bone_lesion_count"],
            "findings": findings,
        }
    if modality == "TAC convencional":
        findings = {
            "ct_summary": data.get("ct_summary"),
            "ct_locations": _normalize_list_value(data.get("ct_locations")),
            "conventional_imaging_status": "M1" if data.get("ct_summary") == "Metástasis" else "M0" if data.get("ct_summary") in {"Sin lesiones sospechosas", "Ganglios sospechosos"} else "",
        }
        return {
            "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
            "study_type": "TAC convencional",
            "findings": findings,
            "radiologist_notes": data.get("clinician_notes"),
        }
    return None


def _build_genomic_payload_from_visit(data):
    genomic_fields = (
        "hrr_status",
        "hrr_gene",
        "brca2_status",
        "msi_status",
        "tmb_high",
        "biomarker_source",
        "molecular_assay_date",
        "molecular_report_date",
        "genomic_classifier",
        "genomic_classifier_result",
        "decipher_score",
        "decipher_risk",
        "prolaris_score",
        "gps_score",
    )
    if not any(_is_present(data.get(field)) for field in genomic_fields):
        return None
    return _build_genomic_payload(data)


def _upsert_treatment_history_from_visit(cursor, patient_id, visit_date, data):
    if not any(_is_present(data.get(field)) for field in ("line_of_therapy_number", "line_of_therapy", "line_of_therapy_context", "drug_scheme", "current_treatment", "current_adt_context")):
        return {}
    line = _normalize_line_of_therapy_number(data)
    line_context = _normalize_line_of_therapy_context(data)
    scheme = normalize_regimen_code(data.get("drug_scheme") or data.get("current_treatment"))
    scheme_label = regimen_label(scheme) if _is_present(scheme) else ""
    current_treatment_value = data.get("current_treatment")
    if isinstance(current_treatment_value, dict):
        current_treatment_value = (
            current_treatment_value.get("label_clinico")
            or current_treatment_value.get("drug_scheme_label")
            or current_treatment_value.get("current_treatment")
            or current_treatment_value.get("drug_scheme")
            or ""
        )
    current_treatment_text = str(current_treatment_value or "").strip()
    if current_treatment_text in {"[object Object]", "[object object]"}:
        current_treatment_text = ""
    regimen = {
        "line_of_therapy_number": line,
        "line_of_therapy_context": line_context,
        "current_treatment": current_treatment_text or scheme_label,
        "drug_scheme": scheme,
        "drug_scheme_label": scheme_label,
        "current_adt_context": data.get("current_adt_context"),
        "castrate_testosterone_status": data.get("castrate_testosterone_status"),
    }
    cursor.execute(
        '''
        SELECT id, line_of_therapy, line_of_therapy_context, drug_scheme, start_date, outcome, regimen_json
        FROM treatment_history
        WHERE patient_id = ?
        ORDER BY start_date DESC, id DESC
        LIMIT 1
        ''',
        (patient_id,),
    )
    latest = cursor.fetchone()
    if latest:
        latest_regimen = _parse_json_blob(latest[6], {})
        latest_scheme = normalize_regimen_code(latest[3] or latest_regimen.get("drug_scheme") or latest_regimen.get("current_treatment"))
        if (
            (line is None or line == _safe_int(latest[1], None))
            and (not line_context or line_context == (latest[2] or latest_regimen.get("line_of_therapy_context")))
            and (not scheme or scheme == latest_scheme)
            and str(latest[5] or "").lower() in {"", "ongoing", "activo"}
        ):
            cursor.execute(
                '''
                UPDATE treatment_history
                SET line_of_therapy = COALESCE(?, line_of_therapy),
                    line_of_therapy_context = COALESCE(?, line_of_therapy_context),
                    drug_scheme = COALESCE(?, drug_scheme),
                    regimen_json = ?,
                    outcome = 'Ongoing'
                WHERE id = ?
                ''',
                (
                    line,
                    line_context,
                    scheme,
                    _json_blob({**latest_regimen, **{k: v for k, v in regimen.items() if _is_present(v)}}),
                    latest[0],
                ),
            )
            return {
                "changed": False,
                "action": "updated_current_line",
                "line_of_therapy_number": line or _safe_int(latest[1], None),
                "line_of_therapy_context": line_context or latest[2] or latest_regimen.get("line_of_therapy_context"),
                "drug_scheme": scheme or latest_scheme,
                "drug_scheme_label": regimen_label(scheme or latest_scheme),
            }
        if str(latest[5] or "").lower() in {"", "ongoing", "activo"}:
            cursor.execute(
                '''
                UPDATE treatment_history
                SET end_date = COALESCE(?, end_date),
                    outcome = CASE
                        WHEN outcome IS NULL OR outcome = '' OR lower(outcome) IN ('ongoing', 'activo')
                        THEN 'Changed'
                        ELSE outcome
                    END
                WHERE id = ?
                ''',
                (visit_date, latest[0]),
            )
    cursor.execute(
        '''
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, line_of_therapy_context, drug_scheme, start_date, outcome, regimen_json
        ) VALUES (?, ?, ?, ?, ?, 'Ongoing', ?)
        ''',
        (
            patient_id,
            line,
            line_context,
            scheme,
            visit_date,
            _json_blob({k: v for k, v in regimen.items() if _is_present(v)}),
        ),
    )
    return {
        "changed": True,
        "action": "therapy_line_changed" if latest else "therapy_started",
        "line_of_therapy_number": line,
        "line_of_therapy_context": line_context,
        "drug_scheme": scheme,
        "drug_scheme_label": scheme_label,
        "visit_date": visit_date,
        "previous_line_of_therapy_number": _safe_int(latest[1], None) if latest else None,
        "previous_line_of_therapy_context": latest[2] if latest else "",
        "previous_drug_scheme": latest[3] if latest else "",
    }


def _update_structural_baseline_from_visit(cursor, patient_id, data):
    data = apply_gleason_profile(dict(data or {}))
    metastatic = _derive_metastatic_payload(data)
    diagnosis_fields = (
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "gleason_tertiary",
        "isup_grade",
        "clinical_tstage",
        "nodal_status",
        "clinical_stage_group",
        "clinical_risk_group",
    )
    if not any(
        _is_present(data.get(field))
        for field in ("child_pugh_score", "hrr_status", "metastasis_site", "metastasis_count", "m_substage_resolved", *diagnosis_fields)
    ) and str(metastatic.get("m_substage_resolved") or "M0") == "M0":
        return
    cursor.execute("SELECT id, hrr_status, child_pugh_score FROM clinical_baseline WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute(
            '''
            UPDATE clinical_baseline
            SET hrr_status = COALESCE(?, hrr_status),
                child_pugh_score = COALESCE(?, child_pugh_score),
                metastasis_site = COALESCE(?, metastasis_site),
                metastasis_count = CASE
                    WHEN ? IS NOT NULL AND ? > 0 THEN ?
                    ELSE metastasis_count
                END,
                m_substage_resolved = COALESCE(?, m_substage_resolved),
                metastatic_profile_json = COALESCE(?, metastatic_profile_json),
                metastasis_assessment_date = COALESCE(?, metastasis_assessment_date),
                metastasis_document_source = COALESCE(?, metastasis_document_source),
                volume_disease = COALESCE(?, volume_disease)
            WHERE id = ?
            ''',
            (
                data.get("hrr_status"),
                data.get("child_pugh_score"),
                metastatic.get("metastasis_site"),
                metastatic.get("metastasis_count"),
                metastatic.get("metastasis_count"),
                metastatic.get("metastasis_count"),
                metastatic.get("m_substage_resolved"),
                metastatic.get("metastatic_profile_json"),
                metastatic.get("metastasis_assessment_date"),
                metastatic.get("metastasis_document_source"),
                metastatic.get("volume_disease"),
                row[0],
            ),
        )
        _persist_official_diagnosis_fields(cursor, patient_id, data)


def _build_pro_payload_from_visit(data):
    keys = (
        "ipss_total",
        "iief5_score",
        "eq5d_vas",
        "fact_p_total",
        "facit_fatigue_total",
        "pad_usage",
        "bpi_worst_pain",
        "bpi_average_pain",
        "epic26_urinary_domain",
        "epic26_sexual_domain",
        "epic26_bowel_domain",
        "epic26_hormonal_domain",
        "eortc_qlq_c30_global_health",
        "eortc_qlq_c30_physical",
        "eortc_qlq_c30_role",
        "eortc_qlq_c30_emotional",
        "eortc_qlq_c30_fatigue",
        "eortc_qlq_c30_pain",
        "anxiety_score",
    )
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "ipss_total": _safe_int(data.get("ipss_total"), None),
        "ipss_qol": _safe_int(data.get("ipss_qol"), None),
        "pad_usage": _safe_int(data.get("pad_usage"), 0),
        "iief5_score": _safe_int(data.get("iief5_score"), None),
        "pde5i_use": _safe_int(data.get("pde5i_use", 0), 0),
        "bpi_worst_pain": _safe_int(data.get("bpi_worst_pain"), None),
        "bpi_average_pain": _safe_int(data.get("bpi_average_pain"), None),
        "eq5d_vas": _safe_int(data.get("eq5d_vas"), None),
        "fact_p_total": _safe_float(data.get("fact_p_total"), None),
        "facit_fatigue_total": _safe_int(data.get("facit_fatigue_total"), None),
        "epic26_urinary_domain": _safe_float(data.get("epic26_urinary_domain"), None),
        "epic26_sexual_domain": _safe_float(data.get("epic26_sexual_domain"), None),
        "epic26_bowel_domain": _safe_float(data.get("epic26_bowel_domain"), None),
        "epic26_hormonal_domain": _safe_float(data.get("epic26_hormonal_domain"), None),
        "eortc_qlq_c30_global_health": _safe_float(data.get("eortc_qlq_c30_global_health"), None),
        "eortc_qlq_c30_physical": _safe_float(data.get("eortc_qlq_c30_physical"), None),
        "eortc_qlq_c30_role": _safe_float(data.get("eortc_qlq_c30_role"), None),
        "eortc_qlq_c30_emotional": _safe_float(data.get("eortc_qlq_c30_emotional"), None),
        "eortc_qlq_c30_fatigue": _safe_float(data.get("eortc_qlq_c30_fatigue"), None),
        "eortc_qlq_c30_pain": _safe_float(data.get("eortc_qlq_c30_pain"), None),
        "anxiety_score": _safe_float(data.get("anxiety_score"), None),
        "clinician_notes": data.get("clinician_notes"),
    }


def _build_surgery_payload_from_visit(data):
    keys = (
        "surgery_type",
        "surgical_approach",
        "nerve_sparing",
        "nodes_removed",
        "nodes_positive",
        "margin_location",
        "capra_s_score",
        "continence_status",
        "potency_status",
        "pads_per_day",
        "pde5i_use",
    )
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "surgery_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "surgery_type": data.get("surgery_type"),
        "surgical_approach": data.get("surgical_approach"),
        "nerve_sparing": data.get("nerve_sparing"),
        "nodes_removed": _safe_int(data.get("nodes_removed"), 0),
        "nodes_positive": _safe_int(data.get("nodes_positive"), 0),
        "margin_location": data.get("margin_location"),
        "capra_s_score": _safe_int(data.get("capra_s_score"), None),
        "continence_status": data.get("continence_status"),
        "potency_status": data.get("potency_status"),
        "pads_per_day": _safe_int(data.get("pads_per_day"), 0),
        "pde5i_use": _safe_int(data.get("pde5i_use", 0), 0),
        "recovery_notes": data.get("clinician_notes"),
        "pathological_stage": data.get("pathological_stage"),
        "pathological_isup": _safe_int(data.get("pathological_isup"), None),
        "surgical_margin_status": _safe_int(data.get("surgical_margin_status"), 0),
    }


def _build_radiation_payload_from_visit(data):
    keys = (
        "rt_context",
        "fractions",
        "total_dose_gy",
        "dose_per_fraction_gy",
        "session_duration_minutes",
        "hematuria",
        "dysuria",
        "gu_toxicity_grade",
        "gi_toxicity_grade",
    )
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "rt_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "rt_context": data.get("rt_context"),
        "rt_technique": data.get("rt_technique"),
        "target": data.get("target"),
        "total_dose_gy": _safe_float(data.get("total_dose_gy"), None),
        "fractions": _safe_int(data.get("fractions"), None),
        "dose_per_fraction_gy": _safe_float(data.get("dose_per_fraction_gy"), None),
        "session_duration_minutes": _safe_int(data.get("session_duration_minutes"), None),
        "hematuria": data.get("hematuria"),
        "dysuria": data.get("dysuria"),
        "anemia_related": data.get("anemia_rt"),
        "gu_toxicity_grade": _safe_int(data.get("gu_toxicity_grade"), 0),
        "gi_toxicity_grade": _safe_int(data.get("gi_toxicity_grade"), 0),
        "notes": data.get("clinician_notes"),
        "late_toxicity_json": {
            "hematuria": data.get("hematuria"),
            "dysuria": data.get("dysuria"),
            "anemia_related": data.get("anemia_rt"),
        },
    }


def _normalize_schedule_anchor(anchor):
    if isinstance(anchor, dict):
        return {
            "anchor_date": anchor.get("anchor_date", ""),
            "anchor_source": anchor.get("anchor_source", ""),
            "last_visit_date": anchor.get("last_visit_date", ""),
        }
    return {"anchor_date": "", "anchor_source": "", "last_visit_date": ""}


def _schedule_event_key(item):
    schedule_key = str(item.get("schedule_key") or item.get("agenda_key") or "").strip()
    if schedule_key:
        return schedule_key
    return "::".join(
        [
            str(item.get("event_type") or ""),
            str(item.get("management_track") or ""),
            str(item.get("due_date") or ""),
            str(item.get("label") or ""),
        ]
    )


def _schedule_sort_key(item):
    return (
        str(item.get("ideal_due_at") or item.get("scheduled_due_at") or item.get("due_date") or ""),
        str(item.get("scheduled_due_at") or item.get("due_date") or ""),
        str(item.get("encounter_key") or item.get("event_type") or ""),
        str(item.get("title") or item.get("label") or ""),
    )


def _upsert_scheduled_events(cursor, patient_id, management_track, items):
    cursor.execute(
        '''
        DELETE FROM scheduled_events
        WHERE patient_id = ?
          AND management_track <> ?
          AND completed = 0
        ''',
        (patient_id, management_track),
    )
    existing = {}
    duplicate_ids = []
    cursor.execute(
        '''
        SELECT id, schedule_key, encounter_key, event_type, label, management_track, due_date,
               plan_key, ideal_due_at, scheduled_due_at, delay_days,
               completed, completed_date, completed_visit_id, overdue_alert_sent
        FROM scheduled_events
        WHERE patient_id = ? AND management_track = ?
        ''',
        (patient_id, management_track),
    )
    for row in cursor.fetchall():
        current = dict(row)
        key = str(current.get("schedule_key") or "").strip()
        if not key:
            key = "::".join(
                [
                    str(current.get("event_type") or ""),
                    str(current.get("management_track") or ""),
                    str(current.get("due_date") or ""),
                    str(current.get("label") or ""),
                ]
            )
            current["schedule_key"] = key
        if key in existing:
            chosen = existing[key]
            keep_current = bool(current.get("completed")) and not bool(chosen.get("completed"))
            if keep_current:
                duplicate_ids.append(chosen["id"])
                existing[key] = current
            else:
                duplicate_ids.append(current["id"])
            continue
        existing[key] = current
    if duplicate_ids:
        cursor.execute(
            f"DELETE FROM scheduled_events WHERE id IN ({','.join(['?'] * len(duplicate_ids))})",
            tuple(duplicate_ids),
        )

    active_keys = set()
    for item in items:
        key = _schedule_event_key(item)
        active_keys.add(key)
        previous = existing.get(key, {})
        if previous:
            cursor.execute(
                '''
                UPDATE scheduled_events
                SET schedule_key = ?,
                    encounter_key = ?,
                    plan_key = ?,
                    label = ?,
                    due_date = ?,
                    ideal_due_at = ?,
                    scheduled_due_at = ?,
                    delay_days = ?,
                    guideline = ?,
                    completed = ?,
                    completed_date = ?,
                    completed_visit_id = ?,
                    overdue_alert_sent = ?
                WHERE id = ?
                ''',
                (
                    key,
                    item.get("encounter_key"),
                    item.get("plan_key"),
                    item.get("label"),
                    item.get("scheduled_due_at") or item.get("due_date"),
                    item.get("ideal_due_at") or item.get("due_date"),
                    item.get("scheduled_due_at") or item.get("due_date"),
                    int(item.get("delay_days") or 0),
                    item.get("guideline", ""),
                    1 if previous.get("completed") else 0,
                    previous.get("completed_date"),
                    previous.get("completed_visit_id"),
                    1 if previous.get("overdue_alert_sent") else 0,
                    previous.get("id"),
                ),
            )
        else:
            cursor.execute(
                '''
                INSERT INTO scheduled_events (
                    patient_id, schedule_key, encounter_key, plan_key, event_type, label, management_track, due_date,
                    ideal_due_at, scheduled_due_at, delay_days, guideline,
                    completed, completed_date, completed_visit_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    patient_id,
                    key,
                    item.get("encounter_key"),
                    item.get("plan_key"),
                    item.get("event_type"),
                    item.get("label"),
                    item.get("management_track"),
                    item.get("scheduled_due_at") or item.get("due_date"),
                    item.get("ideal_due_at") or item.get("due_date"),
                    item.get("scheduled_due_at") or item.get("due_date"),
                    int(item.get("delay_days") or 0),
                    item.get("guideline", ""),
                    0,
                    None,
                    None,
                ),
            )

    stale_ids = [
        row["id"]
        for key, row in existing.items()
        if key not in active_keys and not row.get("completed")
    ]
    if stale_ids:
        cursor.execute(
            f"DELETE FROM scheduled_events WHERE id IN ({','.join(['?'] * len(stale_ids))})",
            tuple(stale_ids),
        )


def _infer_completed_scheduled_event_types(data):
    completed = set()
    if _is_present(data.get("psa")):
        completed.add("psa")
    if _is_present(data.get("testosterone")):
        completed.add("testosterone")
    if any(
        _is_present(data.get(field))
        for field in ("alp", "ldh", "albumin", "hemoglobin", "creatinine", "cystatin_c", "bilirubin", "ast", "alt", "ggt", "glucose")
    ):
        completed.add("labs")
    if any(_is_present(data.get(field)) for field in ("ipss_total", "iief5_score", "eq5d_vas", "fact_p_total", "pad_usage", "bpi_worst_pain", "bpi_average_pain")):
        completed.add("qol")
    if any(_is_present(data.get(field)) for field in ("toxicity", "gu_toxicity_grade", "gi_toxicity_grade", "hematuria", "dysuria")):
        completed.add("toxicity")
    if any(_is_present(data.get(field)) for field in ("imaging_modality", "psma_suv_max", "bone_lesion_count", "ct_summary", "psma_lesion_locations", "ct_locations")):
        completed.add("imaging")
    if any(_is_present(data.get(field)) for field in ("mpmri_quality", "pirads_score", "prior_mpmri_pirads_score")):
        completed.add("mri")
    if any(_is_present(data.get(field)) for field in ("cv_risk_documented", "drug_interaction_reviewed")):
        completed.add("cv_metabolic")
    return completed


def _complete_scheduled_events_for_visit(cursor, patient_id, visit_date, data, visit_record_id=None):
    completed_types = _infer_completed_scheduled_event_types(data)
    if not completed_types and not data.get("scheduled_event_ids") and not data.get("agenda_ids"):
        return

    visit_iso = str(visit_date)[:10]
    try:
        visit_dt = datetime.strptime(visit_iso, "%Y-%m-%d")
    except ValueError:
        visit_dt = datetime.now()
    max_due = (visit_dt + timedelta(days=30)).date().isoformat()

    scheduled_ids = [int(item) for item in (data.get("scheduled_event_ids") or []) if _is_present(item)]
    if scheduled_ids:
        cursor.execute(
            f'''
            UPDATE scheduled_events
            SET completed = 1,
                completed_date = ?,
                completed_visit_id = COALESCE(?, completed_visit_id)
            WHERE patient_id = ? AND id IN ({",".join(["?"] * len(scheduled_ids))})
            ''',
            (visit_iso, visit_record_id, patient_id, *scheduled_ids),
        )

    agenda_ids = [int(item) for item in (data.get("agenda_ids") or []) if _is_present(item)]
    if agenda_ids:
        cursor.execute(
            f'''
            SELECT agenda_key FROM followup_agenda_items
            WHERE patient_id = ? AND id IN ({",".join(["?"] * len(agenda_ids))})
            ''',
            (patient_id, *agenda_ids),
        )
        schedule_keys = [str(row[0]) for row in cursor.fetchall() if str(row[0] or "")]
        if schedule_keys:
            cursor.execute(
                f'''
                UPDATE scheduled_events
                SET completed = 1,
                    completed_date = ?,
                    completed_visit_id = COALESCE(?, completed_visit_id)
                WHERE patient_id = ? AND schedule_key IN ({",".join(["?"] * len(schedule_keys))})
                ''',
                (visit_iso, visit_record_id, patient_id, *schedule_keys),
            )

    encounter_key = str(data.get("encounter_key") or "").strip()
    if encounter_key:
        cursor.execute(
            '''
            UPDATE scheduled_events
            SET completed = 1,
                completed_date = ?,
                completed_visit_id = COALESCE(?, completed_visit_id)
            WHERE patient_id = ?
              AND encounter_key = ?
              AND completed = 0
              AND COALESCE(scheduled_due_at, due_date) <= ?
            ''',
            (visit_iso, visit_record_id, patient_id, encounter_key, max_due),
        )

    for event_type in completed_types:
        cursor.execute(
            '''
            SELECT id FROM scheduled_events
            WHERE patient_id = ?
              AND event_type = ?
              AND completed = 0
              AND COALESCE(scheduled_due_at, due_date) <= ?
            ORDER BY COALESCE(scheduled_due_at, due_date) ASC, id ASC
            LIMIT 1
            ''',
            (patient_id, event_type, max_due),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                '''
                UPDATE scheduled_events
                SET completed = 1,
                    completed_date = ?,
                    completed_visit_id = COALESCE(?, completed_visit_id)
                WHERE id = ?
                ''',
                (visit_iso, visit_record_id, row[0]),
            )
            continue
        try:
            from prostanet.domains.patient_tracking.schedule_engine import SURVEILLANCE_PROTOCOLS

            management_track = data.get("management_track") or ""
            protocol = next(
                (item for item in SURVEILLANCE_PROTOCOLS.get(management_track, []) if item.get("event_type") == event_type),
                {},
            )
            cursor.execute(
                '''
                INSERT INTO scheduled_events (
                    patient_id, event_type, label, management_track, due_date, guideline,
                    completed, completed_date, completed_visit_id
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ''',
                (
                    patient_id,
                    event_type,
                    protocol.get("label") or event_type.upper(),
                    management_track,
                    visit_iso,
                    protocol.get("guideline", ""),
                    visit_iso,
                    visit_record_id,
                ),
            )
        except Exception:
            continue


def _mirror_biomarkers_to_longitudinal(cursor, patient_id, visit_date, data):
    psa_history = _normalize_psa_history_points(
        data.get("psa_history") if data.get("psa_history") not in (None, "", []) else data.get("ape_history"),
        default_source="seguimiento_clinico",
        default_entry_origin="follow_up_visit",
        default_sample_date=visit_date,
        default_context=str(data.get("assessment_context") or data.get("management_track") or "seguimiento").strip(),
        default_line_of_therapy_number=_safe_int(data.get("line_of_therapy_number"), None),
        default_line_of_therapy_context=str(data.get("line_of_therapy_context") or "").strip(),
    )
    if psa_history:
        _persist_psa_series_points(cursor, patient_id, psa_history)
    preferred_psa_points = _preferred_psa_longitudinal_points(
        data,
        sample_date=visit_date,
        default_source="seguimiento_clinico",
        default_entry_origin="follow_up_visit",
        default_context=str(data.get("assessment_context") or data.get("management_track") or "seguimiento").strip(),
    )
    if preferred_psa_points:
        _persist_psa_series_points(cursor, patient_id, preferred_psa_points)

    testosterone_history = _normalize_testosterone_history_points(
        data.get("testosterone_history"),
        default_source="seguimiento_clinico",
        default_entry_origin="follow_up_visit",
        default_sample_date=visit_date,
        default_context=str(data.get("assessment_context") or data.get("management_track") or "seguimiento").strip(),
        default_line_of_therapy_number=_safe_int(data.get("line_of_therapy_number"), None),
        default_line_of_therapy_context=str(data.get("line_of_therapy_context") or "").strip(),
        default_unit=str(data.get("testosterone_unit") or "ng/dL"),
    )
    if testosterone_history:
        _persist_testosterone_series_points(cursor, patient_id, testosterone_history)
    preferred_testosterone_points = _preferred_testosterone_longitudinal_points(
        data,
        sample_date=visit_date,
        default_source="seguimiento_clinico",
        default_entry_origin="follow_up_visit",
        default_context=str(data.get("assessment_context") or data.get("management_track") or "seguimiento").strip(),
    )
    if preferred_testosterone_points:
        _persist_testosterone_series_points(cursor, patient_id, preferred_testosterone_points)

    biomarker_specs = (
        ("HEMOGLOBINA", "hemoglobin", "g/dL"),
        ("CREATININA", "creatinine", "mg/dL"),
        ("CISTATINA_C", "cystatin_c", "mg/L"),
        ("LDH", "ldh", "U/L"),
        ("ALP", "alp", "U/L"),
        ("BILIRRUBINA", "bilirubin", "mg/dL"),
        ("AST", "ast", "U/L"),
        ("ALT", "alt", "U/L"),
        ("GGT", "ggt", "U/L"),
        ("GLUCOSA", "glucose", "mg/dL"),
        ("HBA1C", "hba1c", "%"),
        ("CALCIO", "calcium_level", "mg/dL"),
        ("VITAMINA_D", "vitamin_d_level", "ng/mL"),
        ("ALBUMINA", "albumin", "g/dL"),
    )
    sample_date = str(visit_date)[:10]
    for biomarker_type, field_name, unit in biomarker_specs:
        value = _safe_float(data.get(field_name), None)
        if value is None:
            continue
        cursor.execute(
            '''
            SELECT id FROM biomarker_longitudinal
            WHERE patient_id = ? AND biomarker_type = ? AND sample_date = ? AND value = ?
            LIMIT 1
            ''',
            (patient_id, biomarker_type, sample_date, value),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            '''
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                biomarker_type,
                value,
                unit,
                sample_date,
                _json_blob(
                    {
                        "entry_origin": "follow_up_visit",
                        "source": "seguimiento_clinico",
                        "context": str(data.get("assessment_context") or data.get("management_track") or "seguimiento").strip(),
                        "line_of_therapy_number": _safe_int(data.get("line_of_therapy_number"), None),
                        "line_of_therapy_context": str(data.get("line_of_therapy_context") or "").strip(),
                    }
                ),
            ),
        )


def sync_scheduled_events(patient_record, state=None, management_track=None, horizon_months=12, longitudinal_bundle=None):
    from prostanet.domains.patient_tracking.encounter_planner import build_encounter_plans
    from prostanet.domains.patient_tracking.followup_agenda import (
        agenda_item_to_scheduled_event,
        build_agenda_board,
        infer_management_track,
        resolve_track_anchor,
    )
    from prostanet.domains.patient_tracking.guideline_schedule_engine import (
        build_guideline_followup_plan,
    )
    from prostanet.domains.patient_tracking.copilot_alerts import build_copilot_alerts
    from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle
    from prostanet.domains.patient_tracking.master_followup_plan import build_master_followup_plan
    from prostanet.domains.patient_tracking.longitudinal_intelligence import (
        resolve_followup_runtime_context,
    )
    from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
    from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel

    if not patient_record or not patient_record.get("identity"):
        return {
            "schedule": [],
            "scheduled_items": [],
            "active_schedule": [],
            "archived_schedule": [],
            "scheduled_encounters": [],
            "encounters": [],
            "next_encounter": {},
            "master_followup_plan": {},
            "master_followup_summary": {},
            "anchor_date": "",
            "anchor_source": "",
            "state": "",
            "management_track": "",
            "protocol_trace": {},
            "protocol_label": "",
            "schedule_anchor_strength": "strong",
            "milestone_plan": [],
            "outcome_anchor": {},
            "pending_adjudication_tasks": [],
            "outcome_events_summary": {},
            "pending_adjudications": [],
            "current_response_state": {},
            "current_course_status": "",
            "last_adjudicated_event": {},
            "trial_comparable_endpoints": [],
            "current_trial_comparable_profile": {},
        }

    patient_record = _merge_longitudinal_runtime_record_context(
        patient_record,
        longitudinal_bundle=longitudinal_bundle,
    )
    reconciliation = build_reconciled_state(patient_record, patient_record.get("latest_assessment"))
    state = state or reconciliation.get("reconciled_state") or (patient_record.get("latest_assessment") or {}).get("state") or (patient_record.get("prior_history") or {}).get("current_state") or "diagnostic_workup"
    management_track = management_track or reconciliation.get("reconciled_management_track") or infer_management_track(patient_record, state, patient_record.get("latest_assessment"))
    followup_runtime = resolve_followup_runtime_context(
        patient_record,
        state=state,
        management_track=management_track,
        latest_assessment=patient_record.get("latest_assessment"),
    )
    schedule_state = str(followup_runtime.get("state") or state)
    schedule_management_track = str(followup_runtime.get("management_track") or management_track)
    schedule_override_reason = str(followup_runtime.get("override_reason") or "")
    anchor = _normalize_schedule_anchor(resolve_track_anchor(patient_record, schedule_state, schedule_management_track, patient_record.get("latest_assessment")))
    anchor_date = anchor.get("anchor_date")
    if not anchor_date:
        return {
            "schedule": [],
            "scheduled_items": [],
            "active_schedule": [],
            "archived_schedule": [],
            "scheduled_encounters": [],
            "encounters": [],
            "next_encounter": {},
            "master_followup_plan": {},
            "master_followup_summary": {},
            "anchor_date": "",
            "anchor_source": anchor.get("anchor_source", ""),
            "state": state,
            "management_track": management_track,
            "protocol_trace": {},
            "protocol_label": "",
            "schedule_anchor_strength": "strong",
            "milestone_plan": [],
            "outcome_anchor": {},
            "pending_adjudication_tasks": [],
            "outcome_events_summary": {},
            "pending_adjudications": [],
            "current_response_state": {},
            "current_course_status": "",
            "last_adjudicated_event": {},
            "trial_comparable_endpoints": [],
            "current_trial_comparable_profile": {},
        }

    agenda_board = build_agenda_board(
        patient_record,
        state=schedule_state,
        management_track=schedule_management_track,
        raw_assessment=patient_record.get("latest_assessment"),
        longitudinal_bundle=longitudinal_bundle,
    )
    schedule_seed = [agenda_item_to_scheduled_event(item) for item in (agenda_board.get("items") or [])]
    plan_key = f"{schedule_state}:{schedule_management_track}:{anchor_date}"
    for item in schedule_seed:
        ideal_due_at = str(item.get("ideal_due_at") or item.get("due_date") or "")[:10]
        scheduled_due_at = str(item.get("scheduled_due_at") or item.get("due_date") or ideal_due_at)[:10]
        item["plan_key"] = plan_key
        item["ideal_due_at"] = ideal_due_at
        item["scheduled_due_at"] = scheduled_due_at
        item["delay_days"] = int(item.get("delay_days") or 0)
    orchestration_signals = dict(patient_record.get("latest_signal_snapshot") or {})
    orchestration_signals.update(
        {
            "explicit_state": reconciliation.get("explicit_state"),
            "reconciled_state": reconciliation.get("reconciled_state"),
            "reconciled_management_track": reconciliation.get("reconciled_management_track"),
            "state_conflict_flag": reconciliation.get("state_conflict_flag"),
            "state_conflict_reason": reconciliation.get("state_conflict_reason"),
            "supporting_evidence": reconciliation.get("supporting_evidence", {}),
        }
    )
    if schedule_override_reason:
        cadence_adjusted = [str(item) for item in list(orchestration_signals.get("cadence_adjusted_by") or []) if str(item).strip()]
        if schedule_override_reason not in cadence_adjusted:
            cadence_adjusted.append(schedule_override_reason)
        orchestration_signals["cadence_adjusted_by"] = cadence_adjusted
    outcome_bundle = build_disease_course_bundle(
        patient_record,
        latest_assessment=patient_record.get("latest_assessment"),
    )
    risk_tools_bundle = build_risk_tools_panel(
        patient=patient_record,
        state=state,
        raw_assessment=patient_record.get("latest_assessment"),
        display_assessment={},
    )
    prognostic_bundle = build_prognostic_impact_bundle(
        patient=patient_record,
        state=schedule_state,
        management_track=schedule_management_track,
        raw_assessment=patient_record.get("latest_assessment"),
        risk_tools_bundle=risk_tools_bundle,
        current_trial_profile=outcome_bundle.get("current_trial_comparable_profile", {}),
    )
    orchestration_signals.update(
        {
            "outcome_events_summary": outcome_bundle.get("outcome_events_summary", {}),
            "pending_adjudications": outcome_bundle.get("pending_adjudications", []),
            "current_response_state": outcome_bundle.get("current_response_state", {}),
            "current_course_status": outcome_bundle.get("current_course_status", ""),
            "last_adjudicated_event": outcome_bundle.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": outcome_bundle.get("trial_comparable_endpoints", []),
            "current_trial_comparable_profile": outcome_bundle.get("current_trial_comparable_profile", {}),
            "prognostic_modifiers": prognostic_bundle.get("prognostic_modifiers", []),
            "prognostic_recommended_actions": prognostic_bundle.get("recommended_actions", []),
            "prognostic_followup_impact": prognostic_bundle.get("followup_impact", []),
            "prognostic_capture_targets": prognostic_bundle.get("capture_targets", []),
            "backbone_alignment": prognostic_bundle.get("backbone_alignment", {}),
            "cadence_adjusted_by": prognostic_bundle.get("cadence_adjusted_by", []),
        }
    )
    copilot_bundle = build_copilot_alerts(
        patient_record,
        state=schedule_state,
        management_track=schedule_management_track,
        signals=orchestration_signals,
        agenda_board=agenda_board,
        encounters=agenda_board.get("encounters", []),
        raw_assessment=patient_record.get("latest_assessment"),
    )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    _upsert_scheduled_events(c, patient_record["identity"]["id"], schedule_management_track, schedule_seed)
    conn.commit()
    c.execute(
        '''
        SELECT * FROM scheduled_events
        WHERE patient_id = ? AND management_track = ?
        ORDER BY due_date ASC, id ASC
        ''',
        (patient_record["identity"]["id"], schedule_management_track),
    )
    persisted = _hydrate_scheduled_event_rows(c.fetchall())
    conn.close()
    persisted_by_key = {str(row.get("schedule_key") or ""): row for row in persisted if str(row.get("schedule_key") or "")}
    merged_schedule = []
    for seed in schedule_seed:
        key = _schedule_event_key(seed)
        persisted_row = persisted_by_key.get(key, {})
        merged_item = dict(seed)
        merged_item.update(
            {
                "id": persisted_row.get("id"),
                "schedule_key": persisted_row.get("schedule_key") or seed.get("schedule_key") or seed.get("agenda_key"),
                "encounter_key": persisted_row.get("encounter_key") or seed.get("encounter_key"),
                "plan_key": persisted_row.get("plan_key") or seed.get("plan_key") or plan_key,
                "ideal_due_at": str(persisted_row.get("ideal_due_at") or seed.get("ideal_due_at") or seed.get("due_date") or "")[:10],
                "scheduled_due_at": str(persisted_row.get("scheduled_due_at") or seed.get("scheduled_due_at") or seed.get("due_date") or "")[:10],
                "delay_days": int(persisted_row.get("delay_days") or seed.get("delay_days") or 0),
                "completed": bool(persisted_row.get("completed")),
                "completed_date": persisted_row.get("completed_date", ""),
                "completed_at": str(persisted_row.get("completed_date") or seed.get("completed_at") or "")[:10],
                "completed_visit_id": persisted_row.get("completed_visit_id"),
                "overdue_alert_sent": bool(persisted_row.get("overdue_alert_sent")),
                "required": bool(seed.get("required", True)),
                "action_mode": seed.get("action_mode", "capture"),
                "completion_rule": dict(seed.get("completion_rule") or {}),
            }
        )
        if merged_item.get("completed"):
            merged_item["status"] = "completed"
        elif str(merged_item.get("scheduled_due_at") or merged_item.get("due_date") or merged_item.get("due_at") or "")[:10] == date.today().isoformat():
            merged_item["status"] = "due_today"
        merged_schedule.append(merged_item)
    merged_schedule.sort(key=_schedule_sort_key)
    active_schedule = [item for item in merged_schedule if item.get("status") not in {"completed", "cancelled", "superseded"}]
    archived_schedule = [item for item in merged_schedule if item.get("status") in {"completed", "cancelled", "superseded"}]
    schedule_by_key = {str(item.get("schedule_key") or ""): item for item in merged_schedule if str(item.get("schedule_key") or "")}
    persisted_agenda_by_key = {
        str(item.get("agenda_key") or ""): item
        for item in list(patient_record.get("agenda_items") or [])
        if str(item.get("agenda_key") or "")
    }
    enriched_agenda_items = []
    for item in list(agenda_board.get("items") or []):
        current = dict(item)
        persisted_agenda = persisted_agenda_by_key.get(str(current.get("agenda_key") or ""), {})
        scheduled = schedule_by_key.get(str(current.get("agenda_key") or ""), {})
        current["id"] = persisted_agenda.get("id", current.get("id"))
        current["plan_key"] = scheduled.get("plan_key") or plan_key
        current["ideal_due_at"] = scheduled.get("ideal_due_at") or current.get("ideal_due_at") or current.get("due_at") or ""
        current["scheduled_due_at"] = scheduled.get("scheduled_due_at") or current.get("scheduled_due_at") or current.get("due_at") or ""
        current["delay_days"] = int(scheduled.get("delay_days") or current.get("delay_days") or 0)
        current["completed_at"] = scheduled.get("completed_at") or persisted_agenda.get("completed_at") or current.get("completed_at") or ""
        current["required"] = bool(scheduled.get("required", current.get("required", True)))
        current["action_mode"] = scheduled.get("action_mode") or current.get("action_mode") or "capture"
        enriched_agenda_items.append(current)
    enriched_agenda_items.sort(key=lambda item: _schedule_sort_key(item))
    enriched_encounters = build_encounter_plans(
        enriched_agenda_items,
        state=schedule_state,
        management_track=schedule_management_track,
        protocol_trace=agenda_board.get("protocol_trace") or {},
    )
    enriched_encounters.sort(key=lambda item: _schedule_sort_key(item))
    actionable_encounters = [item for item in enriched_encounters if str(item.get("status") or "") not in {"completed", "cancelled", "superseded"}]
    next_encounter = next(
        (encounter for encounter in actionable_encounters if str(encounter.get("visit_modality") or "") != "async"),
        actionable_encounters[0] if actionable_encounters else {},
    )
    agenda_board["items"] = enriched_agenda_items
    agenda_board["active_items"] = [item for item in enriched_agenda_items if item.get("status") not in {"completed", "cancelled", "superseded"}]
    agenda_board["encounters"] = enriched_encounters
    agenda_board["next_encounter"] = next_encounter
    master_followup_plan = build_master_followup_plan(
        patient_record,
        state=schedule_state,
        management_track=schedule_management_track,
        agenda_board=agenda_board,
        signals=orchestration_signals,
        copilot_alerts=copilot_bundle.get("alerts", []),
        next_best_action=orchestration_signals.get("next_best_action") or {},
        plan_key=plan_key,
        calendar_horizon_months=horizon_months,
    )
    guideline_followup_plan = build_guideline_followup_plan(
        patient=patient_record,
        state=schedule_state,
        management_track=schedule_management_track,
        agenda_board=agenda_board,
        master_followup_plan=master_followup_plan,
        signals=orchestration_signals,
        care_intent_contract=orchestration_signals.get("care_intent_contract") or {},
    )
    return {
        "state": state,
        "management_track": management_track,
        "schedule_state": schedule_state,
        "schedule_management_track": schedule_management_track,
        "schedule_override_reason": schedule_override_reason,
        "anchor_date": anchor_date,
        "anchor_source": anchor.get("anchor_source", ""),
        "schedule": active_schedule,
        "scheduled_items": merged_schedule,
        "active_schedule": active_schedule,
        "archived_schedule": archived_schedule,
        "protocol_trace": agenda_board.get("protocol_trace", {}),
        "protocol_label": (agenda_board.get("stage_protocol") or {}).get("title", ""),
        "scheduled_encounters": enriched_encounters,
        "encounters": enriched_encounters,
        "next_encounter": next_encounter,
        "master_followup_plan": master_followup_plan,
        "master_followup_summary": master_followup_plan.get("summary", {}),
        "guideline_followup_plan": guideline_followup_plan,
        "schedule_anchor_strength": "weak" if (agenda_board.get("protocol_trace") or {}).get("anchor_is_fallback") else "strong",
        "milestone_plan": outcome_bundle.get("milestone_plan", []),
        "outcome_anchor": outcome_bundle.get("outcome_anchor", {}),
        "pending_adjudication_tasks": outcome_bundle.get("pending_adjudication_tasks", []),
        "outcome_events_summary": outcome_bundle.get("outcome_events_summary", {}),
        "pending_adjudications": outcome_bundle.get("pending_adjudications", []),
        "current_response_state": outcome_bundle.get("current_response_state", {}),
        "current_course_status": outcome_bundle.get("current_course_status", ""),
        "last_adjudicated_event": outcome_bundle.get("last_adjudicated_event", {}),
        "trial_comparable_endpoints": outcome_bundle.get("trial_comparable_endpoints", []),
        "current_trial_comparable_profile": outcome_bundle.get("current_trial_comparable_profile", {}),
        "prognostic_modifiers": prognostic_bundle.get("prognostic_modifiers", []),
        "prognostic_recommended_actions": prognostic_bundle.get("recommended_actions", []),
        "prognostic_followup_impact": prognostic_bundle.get("followup_impact", []),
        "prognostic_capture_targets": prognostic_bundle.get("capture_targets", []),
        "backbone_alignment": prognostic_bundle.get("backbone_alignment", {}),
        "cadence_adjusted_by": prognostic_bundle.get("cadence_adjusted_by", []),
        "prognostic_rationale": (master_followup_plan.get("prognostic_rationale") or []),
    }


def _upsert_agenda_items(cursor, patient_id, items):
    existing = {}
    # Auditoría #21 (cierre OOS-9): cuando una visita cierra un item en un
    # estado A (p.ej. `adt_progression_verification:on_arpi:therapy_review`)
    # y la reconciliación posterior transita el paciente al estado B
    # (p.ej. `mcspc_low_volume_sync_oligo:on_arpi:therapy_review`), el
    # agenda_key cambia pero la tarea clínica es la misma subtarea de la
    # misma track. Capturamos un fallback indexado por (management_track,
    # item_type) para propagar `partially_satisfied`/`completed` al nuevo
    # item cuando el `agenda_key` antiguo ya no está activo.
    existing_by_track_type = {}
    cursor.execute(
        "SELECT agenda_key, status, due_at, completed_at, visit_record_id, management_track, item_type "
        "FROM followup_agenda_items WHERE patient_id = ?",
        (patient_id,),
    )
    for row in cursor.fetchall():
        entry = {
            "status": row[1],
            "due_at": row[2],
            "completed_at": row[3],
            "visit_record_id": row[4],
        }
        existing[row[0]] = entry
        track_key = (row[5] or "", row[6] or "")
        if row[1] in ("partially_satisfied", "completed") and track_key not in existing_by_track_type:
            existing_by_track_type[track_key] = entry
    active_keys = {item["agenda_key"] for item in items if item.get("agenda_key")}
    if active_keys:
        cursor.execute(
            f"""
            UPDATE followup_agenda_items
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
              AND agenda_key NOT IN ({",".join(["?"] * len(active_keys))})
              AND status NOT IN ('completed', 'superseded', 'cancelled')
            """,
            (patient_id, *active_keys),
        )
    else:
        cursor.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND status NOT IN ('completed', 'superseded', 'cancelled')
            ''',
            (patient_id,),
        )
    for item in items:
        previous = existing.get(item["agenda_key"], {})
        # Auditoría #21 (cierre OOS-9): fallback cross-state por (track, item_type).
        # Aplica cuando el previous directo por agenda_key no está en un estado
        # de satisfacción (overdue/due/scheduled), pero existe un item
        # superseded de la misma track e item_type que SÍ fue satisfecho en un
        # estado previo. En ese caso propagamos el status de satisfacción al
        # nuevo item para no perder la actualización cross-transición.
        if previous.get("status") not in ("partially_satisfied", "completed"):
            track_fallback = existing_by_track_type.get(
                (item.get("management_track") or "", item.get("item_type") or "")
            )
            if track_fallback:
                previous = track_fallback
        status = item.get("status")
        completed_at = None
        visit_record_id = None
        if previous.get("status") == "completed" and previous.get("due_at") == item.get("due_at"):
            status = "completed"
            completed_at = previous.get("completed_at")
            visit_record_id = previous.get("visit_record_id")
        elif previous.get("status") == "partially_satisfied":
            status = "partially_satisfied"
            completed_at = previous.get("completed_at")
            visit_record_id = previous.get("visit_record_id")
        cursor.execute(
            '''
            INSERT INTO followup_agenda_items (
                patient_id, agenda_key, state, management_track, item_type, title, status, priority,
                due_at, window_start, window_end, required_inputs_json, completion_rule_json,
                evidence_basis_json, comparator_basis_json, generated_from_event, summary,
                blockers_json, reasoning_json, decision_targets_json, panel_targets_json,
                write_targets_json, form_scope_json, completed_at, visit_record_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(patient_id, agenda_key) DO UPDATE SET
                state=excluded.state,
                management_track=excluded.management_track,
                item_type=excluded.item_type,
                title=excluded.title,
                status=excluded.status,
                priority=excluded.priority,
                due_at=excluded.due_at,
                window_start=excluded.window_start,
                window_end=excluded.window_end,
                required_inputs_json=excluded.required_inputs_json,
                completion_rule_json=excluded.completion_rule_json,
                evidence_basis_json=excluded.evidence_basis_json,
                comparator_basis_json=excluded.comparator_basis_json,
                generated_from_event=excluded.generated_from_event,
                summary=excluded.summary,
                blockers_json=excluded.blockers_json,
                reasoning_json=excluded.reasoning_json,
                decision_targets_json=excluded.decision_targets_json,
                panel_targets_json=excluded.panel_targets_json,
                write_targets_json=excluded.write_targets_json,
                form_scope_json=excluded.form_scope_json,
                completed_at=excluded.completed_at,
                visit_record_id=excluded.visit_record_id,
                updated_at=CURRENT_TIMESTAMP
            ''',
            (
                patient_id,
                item.get("agenda_key"),
                item.get("state"),
                item.get("management_track"),
                item.get("item_type"),
                item.get("title"),
                status,
                item.get("priority"),
                item.get("due_at"),
                item.get("window_start"),
                item.get("window_end"),
                _json_blob(item.get("required_inputs", [])),
                _json_blob(item.get("completion_rule", {})),
                _json_blob(item.get("evidence_basis", [])),
                _json_blob(item.get("comparator_basis", [])),
                item.get("generated_from_event"),
                item.get("summary"),
                _json_blob(item.get("blockers", [])),
                _json_blob(item.get("reasoning", [])),
                _json_blob(item.get("decision_targets", [])),
                _json_blob(item.get("panel_targets", [])),
                _json_blob(item.get("write_targets", [])),
                _json_blob(item.get("form_scope", {})),
                completed_at,
                visit_record_id,
            ),
        )


def _record_visit_provenance(cursor, patient_id, visit_record_id, state, visit_date, bundle_payload):
    tracked_fields = (
        "psa", "psad", "testosterone", "alp", "ldh", "albumin", "hemoglobin", "creatinine",
        "cystatin_c", "bilirubin", "ast", "alt", "ggt", "glucose", "ecog", "pain",
        "pirads_score", "precise_score", "psma_suv_max", "bone_lesion_count", "ct_summary",
        "mini_cog_score", "fatigue_score", "weight_kg", "bmi_current", "weight_loss_6m_pct",
        "cv_risk_documented", "drug_interaction_reviewed", "exercise_status", "nutrition_status",
        "peripheral_neuropathy_grade",
        "g8_food_intake", "g8_weight_loss", "g8_mobility", "g8_neuropsych", "g8_bmi",
        "g8_medications", "g8_self_health", "low_activity", "slow_gait", "weak_grip",
        "genomic_classifier", "genomic_classifier_result", "decipher_risk",
        "line_of_therapy", "line_of_therapy_number", "line_of_therapy_context", "drug_scheme",
        "current_adt_context", "castrate_testosterone_status",
        "progression_pattern", "conventional_imaging_status", "hrr_status", "hrr_gene",
        "brca2_status", "msi_status", "tmb_high", "biomarker_source", "molecular_assay_date",
        "psma_positive", "psma_negative_dominant_lesions", "dxa_baseline_done",
        "calcium_vitd_started", "bone_protection_started", "vitamin_d_level",
    )
    for field_name in tracked_fields:
        value = bundle_payload.get(field_name)
        if not _is_present(value):
            continue
        cursor.execute(
            '''
            INSERT INTO data_provenance (
                patient_id, visit_record_id, field_name, value_json, source_type, source_date,
                entered_manually, stage_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_record_id,
                field_name,
                _json_blob(value),
                "visit_bundle",
                visit_date,
                1,
                state,
            ),
        )


def _record_document_provenance(cursor, patient_id, document_id, document_key, state, source_date, facts, verified_by):
    for fact in facts:
        field_name = fact.get("field_name")
        if not field_name or not _is_present(fact.get("value")):
            continue
        cursor.execute(
            '''
            INSERT INTO data_provenance (
                patient_id, visit_record_id, field_name, value_json, source_type, source_document_id,
                source_date, verified_by, entered_manually, stage_context
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                field_name,
                _json_blob(fact.get("value")),
                "source_document",
                document_key,
                source_date,
                verified_by,
                0,
                state,
            ),
        )


def record_patient_event(
    patient_id,
    *,
    event_type,
    event_date=None,
    state_context="",
    management_track="",
    source_type="system",
    source_record_id=None,
    status="recorded",
    payload=None,
    mcode_focus=None,
):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO patient_events (
                patient_id, event_type, event_date, state_context, management_track,
                source_type, source_record_id, status, payload_json, mcode_focus_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                event_type,
                event_date or datetime.now().strftime("%Y-%m-%d"),
                state_context,
                management_track,
                source_type,
                source_record_id,
                status,
                _json_blob(payload or {}),
                _json_blob(mcode_focus or {}),
            ),
        )
        event_id = c.lastrowid
        conn.commit()
        conn.close()
        return event_id
    except Exception as e:
        logger.error(f"Error recording patient event: {e}")
        return None


def update_care_pathway_action_status(
    nss_or_id,
    action_key,
    status,
    *,
    note="",
    updated_by="clinician",
):
    """Update internal Care Pathway OS action status and write audit event.

    This is intentionally scoped to internal operational status. It does not
    create external orders, prescriptions, treatment facts, PSA, testosterone,
    imaging, molecular results, or trial eligibility.
    """
    from prostanet.domains.patient_tracking.care_pathway_os import CARE_PATHWAY_ACTION_STATUSES

    action_key = str(action_key or "").strip()
    normalized_status = str(status or "").strip().lower()
    if not action_key:
        return False, "action_key requerido", {}
    if normalized_status not in CARE_PATHWAY_ACTION_STATUSES:
        return False, f"Estado invalido: {status}", {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    identity = _resolve_identity_row(c, nss_or_id)
    if not identity:
        conn.close()
        return False, "Paciente no encontrado", {}
    patient_id = int(identity["id"])
    today = datetime.now().strftime("%Y-%m-%d")
    updated_targets = []
    source_record_id = None

    try:
        if action_key.startswith("schedule:"):
            source_key = action_key.split(":", 1)[1]
            c.execute(
                '''
                SELECT id FROM scheduled_events
                WHERE patient_id = ?
                  AND (schedule_key = ? OR CAST(id AS TEXT) = ?)
                ORDER BY id DESC
                LIMIT 1
                ''',
                (patient_id, source_key, source_key),
            )
            row = c.fetchone()
            if not row:
                conn.close()
                return False, "Accion programada no encontrada para este paciente", {}
            source_record_id = int(row["id"])
            if normalized_status == "completed":
                c.execute(
                    '''
                    UPDATE scheduled_events
                    SET completed = 1,
                        completed_date = COALESCE(completed_date, ?),
                        performed_date = COALESCE(performed_date, ?),
                        completion_status = 'completed_manual',
                        completion_source = 'care_pathway_os_manual',
                        next_recovery_action = COALESCE(?, next_recovery_action)
                    WHERE id = ? AND patient_id = ?
                    ''',
                    (today, today, note, source_record_id, patient_id),
                )
            else:
                c.execute(
                    '''
                    UPDATE scheduled_events
                    SET completed = 0,
                        completion_status = ?,
                        completion_source = 'care_pathway_os_manual',
                        next_recovery_action = COALESCE(?, next_recovery_action)
                    WHERE id = ? AND patient_id = ?
                    ''',
                    (normalized_status, note, source_record_id, patient_id),
                )
            updated_targets.append("scheduled_events")
        elif action_key.startswith("agenda:"):
            source_key = action_key.split(":", 1)[1]
            c.execute(
                '''
                SELECT id, agenda_key FROM followup_agenda_items
                WHERE patient_id = ?
                  AND (agenda_key = ? OR CAST(id AS TEXT) = ?)
                ORDER BY id DESC
                LIMIT 1
                ''',
                (patient_id, source_key, source_key),
            )
            row = c.fetchone()
            if not row:
                conn.close()
                return False, "Accion de agenda no encontrada para este paciente", {}
            source_record_id = int(row["id"])
            completed_at_sql = "CURRENT_TIMESTAMP" if normalized_status == "completed" else "completed_at"
            c.execute(
                f'''
                UPDATE followup_agenda_items
                SET status = ?,
                    completed_at = {completed_at_sql},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND patient_id = ?
                ''',
                (normalized_status, source_record_id, patient_id),
            )
            agenda_key = str(row["agenda_key"] or "")
            if agenda_key:
                if normalized_status == "completed":
                    c.execute(
                        '''
                        UPDATE scheduled_events
                        SET completed = 1,
                            completed_date = COALESCE(completed_date, DATE('now')),
                            performed_date = COALESCE(performed_date, DATE('now')),
                            completion_status = 'completed_manual',
                            completion_source = 'care_pathway_os_manual'
                        WHERE patient_id = ? AND schedule_key = ?
                        ''',
                        (patient_id, agenda_key),
                    )
                else:
                    c.execute(
                        '''
                        UPDATE scheduled_events
                        SET completion_status = ?,
                            completion_source = 'care_pathway_os_manual'
                        WHERE patient_id = ? AND schedule_key = ?
                        ''',
                        (normalized_status, patient_id, agenda_key),
                    )
            updated_targets.extend(["followup_agenda_items", "scheduled_events"])
        else:
            # Synthetic Tumor Board/readiness actions have no source table in v1.
            # They are still auditable through patient_events and reflected by the
            # Care Pathway OS override layer.
            updated_targets.append("patient_events")

        conn.commit()
        conn.close()
    except Exception as exc:
        conn.rollback()
        conn.close()
        logger.error(f"Error updating Care Pathway OS action status: {exc}")
        return False, str(exc), {}

    event_id = record_patient_event(
        patient_id,
        event_type="care_pathway_action_status_updated",
        source_type="care_pathway_os",
        source_record_id=source_record_id,
        status="recorded",
        payload={
            "action_key": action_key,
            "status": normalized_status,
            "note": str(note or ""),
            "updated_by": str(updated_by or "clinician"),
            "updated_targets": updated_targets,
            "external_order_created": False,
        },
    )
    refreshed = refresh_longitudinal_intelligence(
        patient_id,
        event_id=event_id,
        force_recompute=True,
        include_live_benchmark=False,
    )
    return True, "Estado Care Pathway OS actualizado", {
        "event_id": event_id,
        "updated_targets": updated_targets,
        "care_pathway_os": (refreshed or {}).get("care_pathway_os", {}),
    }


def _persist_signal_snapshot(cursor, patient_id, event_id, bundle):
    signals = bundle.get("signals", {})
    next_best_action = bundle.get("next_best_action", {})
    published_state = (
        signals.get("effective_state_final")
        or signals.get("effective_state")
        or signals.get("reconciled_state")
        or signals.get("state")
    )
    published_track = signals.get("reconciled_management_track") or signals.get("management_track")
    cursor.execute(
        '''
        INSERT INTO clinical_signal_snapshots (
            patient_id, event_id, state, management_track, ready_to_restage,
            signals_json, critical_missing_json, awaiting_review_json, active_safety_json,
            next_best_action_json, mcode_projection_json, evidence_basis_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(patient_id) DO UPDATE SET
            event_id=excluded.event_id,
            state=excluded.state,
            management_track=excluded.management_track,
            ready_to_restage=excluded.ready_to_restage,
            signals_json=excluded.signals_json,
            critical_missing_json=excluded.critical_missing_json,
            awaiting_review_json=excluded.awaiting_review_json,
            active_safety_json=excluded.active_safety_json,
            next_best_action_json=excluded.next_best_action_json,
            mcode_projection_json=excluded.mcode_projection_json,
            evidence_basis_json=excluded.evidence_basis_json,
            updated_at=CURRENT_TIMESTAMP
        ''',
        (
            patient_id,
            event_id,
            published_state,
            published_track,
            1 if signals.get("ready_to_restage") else 0,
            _json_blob(signals.get("signals", [])),
            _json_blob(signals.get("critical_missing", [])),
            _json_blob(signals.get("awaiting_review", [])),
            _json_blob(signals.get("active_safety", [])),
            _json_blob(next_best_action),
            _json_blob(signals.get("mcode_projection", {})),
            _json_blob(signals.get("evidence_basis", [])),
        ),
    )


def _bundle_can_override_recommendation(bundle):
    status = str((bundle or {}).get("status") or "").strip().lower()
    return status not in {"", "shadow", "shadow-blocked", "unavailable", "not_applicable", "advisory_candidate"}


def _persist_transition_proposals(cursor, patient_id, event_id, proposals):
    active_keys = {proposal.get("proposal_key") for proposal in proposals if proposal.get("proposal_key")}
    if active_keys:
        cursor.execute(
            f"""
            UPDATE state_transition_proposals
            SET proposal_status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
              AND proposal_status = 'open'
              AND proposal_key NOT IN ({",".join(["?"] * len(active_keys))})
            """,
            (patient_id, *active_keys),
        )
    else:
        cursor.execute(
            '''
            UPDATE state_transition_proposals
            SET proposal_status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND proposal_status = 'open'
            ''',
            (patient_id,),
        )
    for proposal in proposals:
        cursor.execute(
            '''
            INSERT INTO state_transition_proposals (
                patient_id, proposal_key, event_id, from_state, from_management_track,
                target_state, target_management_track, proposal_status, priority,
                requires_confirmation, rationale, trigger_signals_json, next_actions_json,
                evidence_basis_json, confirmation_status, requires_more_data_fields_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(patient_id, proposal_key) DO UPDATE SET
                event_id=excluded.event_id,
                from_state=excluded.from_state,
                from_management_track=excluded.from_management_track,
                target_state=excluded.target_state,
                target_management_track=excluded.target_management_track,
                proposal_status=CASE
                    WHEN state_transition_proposals.confirmation_status IN ('confirmed', 'rejected', 'deferred')
                        THEN state_transition_proposals.proposal_status
                    ELSE excluded.proposal_status
                END,
                priority=excluded.priority,
                requires_confirmation=excluded.requires_confirmation,
                rationale=excluded.rationale,
                trigger_signals_json=excluded.trigger_signals_json,
                next_actions_json=excluded.next_actions_json,
                evidence_basis_json=excluded.evidence_basis_json,
                confirmation_status=CASE
                    WHEN state_transition_proposals.confirmation_status IN ('confirmed', 'rejected', 'deferred')
                        THEN state_transition_proposals.confirmation_status
                    ELSE excluded.confirmation_status
                END,
                requires_more_data_fields_json=excluded.requires_more_data_fields_json,
                updated_at=CURRENT_TIMESTAMP
            ''',
            (
                patient_id,
                proposal.get("proposal_key"),
                event_id,
                proposal.get("from_state"),
                proposal.get("from_management_track"),
                proposal.get("target_state"),
                proposal.get("target_management_track"),
                proposal.get("proposal_status", "open"),
                proposal.get("priority"),
                1 if proposal.get("requires_confirmation", True) else 0,
                proposal.get("rationale"),
                _json_blob(proposal.get("trigger_signals", [])),
                _json_blob(proposal.get("next_actions", [])),
                _json_blob(proposal.get("evidence_basis", [])),
                proposal.get("confirmation_status", "pending"),
                _json_blob(proposal.get("requires_more_data_fields", [])),
            ),
        )


def _persist_therapeutic_window_events(cursor, patient_id, window_worklist_bundle):
    active_windows = [
        enrich_window_with_registry(dict(item))
        for item in list(window_worklist_bundle.get("active_windows_ranked") or [])
        if str(item.get("window_key") or "").strip()
    ]
    current_by_key = {str(item.get("window_key") or ""): item for item in active_windows}
    cursor.execute(
        """
        SELECT * FROM therapeutic_window_events
        WHERE patient_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (patient_id,),
    )
    column_names = [description[0] for description in (cursor.description or [])]
    existing_rows = []
    for row in cursor.fetchall():
        if isinstance(row, dict):
            existing_rows.append(dict(row))
            continue
        if hasattr(row, "keys"):
            existing_rows.append({key: row[key] for key in row.keys()})
            continue
        if column_names:
            existing_rows.append(dict(zip(column_names, row)))
    open_by_key = {}
    for row in existing_rows:
        key = str(row.get("window_key") or "")
        if key and not row.get("window_closed_at") and key not in open_by_key:
            open_by_key[key] = row
    now_iso = datetime.now().isoformat(timespec="seconds")

    def _closure_metadata(window):
        status = str(window.get("window_status") or "").lower()
        risk = str(window.get("opportunity_loss_risk") or "").lower()
        if status == "redirected":
            return now_iso, "redirected", "La ventana se cerró por redirección clínica.", 1 if risk == "confirmed" else 0
        if status == "closed":
            closure_type = "missed" if risk == "confirmed" else "completed"
            reason = "La ventana terapéutica se considera cerrada en el recálculo longitudinal."
            return now_iso, closure_type, reason, 1 if risk == "confirmed" else 0
        return None, "", "", 0

    for window_key, window in current_by_key.items():
        open_row = open_by_key.get(window_key)
        closed_at, closure_type, closure_reason, opportunity_lost = _closure_metadata(window)
        evidence_used = {
            "required_inputs": list(window.get("required_inputs") or []),
            "missing_decisive_fields": list(window.get("missing_decisive_fields") or []),
            "closure_tasks": list(window.get("closure_tasks") or []),
            "why_this_matters_now": window.get("why_this_matters_now") or "",
            "if_not_closed_clinical_consequence": window.get("if_not_closed_clinical_consequence") or "",
        }
        if open_row:
            cursor.execute(
                """
                UPDATE therapeutic_window_events
                SET window_status = ?, window_closed_at = COALESCE(?, window_closed_at),
                    closure_type = CASE WHEN ? != '' THEN ? ELSE closure_type END,
                    closure_reason = CASE WHEN ? != '' THEN ? ELSE closure_reason END,
                    evidence_used_json = ?, closed_by = CASE WHEN ? IS NOT NULL THEN 'system' ELSE closed_by END,
                    decision_domain_blocked = ?, required_fact_keys_json = ?, missing_fact_keys_json = ?,
                    owner_role = ?, sla_days = ?, clinical_consequence_if_delayed = ?,
                    target_state_if_closed = ?, redirect_state_if_negative = ?,
                    opportunity_lost = CASE WHEN ? THEN 1 ELSE opportunity_lost END,
                    opportunity_loss_reason = CASE
                        WHEN ? THEN ?
                        ELSE opportunity_loss_reason
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    window.get("window_status"),
                    closed_at,
                    closure_type,
                    closure_type,
                    closure_reason,
                    closure_reason,
                    _json_blob(evidence_used),
                    closed_at,
                    window.get("decision_domain_blocked"),
                    _json_blob(window.get("required_fact_keys") or []),
                    _json_blob(window.get("missing_fact_keys") or []),
                    window.get("owner_role"),
                    _safe_int(window.get("sla_days"), 0),
                    window.get("clinical_consequence_if_delayed"),
                    window.get("target_state_if_closed"),
                    window.get("redirect_state_if_negative"),
                    opportunity_lost,
                    opportunity_lost,
                    window.get("opportunity_loss_reason") or "",
                    open_row.get("id"),
                ),
            )
            continue
        cursor.execute(
            """
            INSERT INTO therapeutic_window_events (
                patient_id, window_key, window_opened_at, window_status, window_closed_at,
                closure_type, closure_reason, evidence_used_json, closed_by,
                decision_domain_blocked, required_fact_keys_json, missing_fact_keys_json,
                owner_role, sla_days, clinical_consequence_if_delayed,
                target_state_if_closed, redirect_state_if_negative,
                opportunity_lost, opportunity_loss_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                window_key,
                now_iso,
                window.get("window_status"),
                closed_at,
                closure_type or None,
                closure_reason or None,
                _json_blob(evidence_used),
                "system" if closed_at else None,
                window.get("decision_domain_blocked"),
                _json_blob(window.get("required_fact_keys") or []),
                _json_blob(window.get("missing_fact_keys") or []),
                window.get("owner_role"),
                _safe_int(window.get("sla_days"), 0),
                window.get("clinical_consequence_if_delayed"),
                window.get("target_state_if_closed"),
                window.get("redirect_state_if_negative"),
                opportunity_lost,
                window.get("opportunity_loss_reason") if opportunity_lost else None,
            ),
        )

    for window_key, open_row in open_by_key.items():
        if window_key in current_by_key:
            continue
        cursor.execute(
            """
            UPDATE therapeutic_window_events
            SET window_status = 'closed',
                window_closed_at = COALESCE(window_closed_at, ?),
                closure_type = COALESCE(closure_type, 'completed'),
                closure_reason = COALESCE(closure_reason, 'La ventana dejó de estar activa tras el recálculo longitudinal.'),
                closed_by = COALESCE(closed_by, 'system'),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (now_iso, open_row.get("id")),
        )


def _persist_recommendation_audit(cursor, audit):
    if not audit:
        return
    cursor.execute(
        '''
        INSERT INTO recommendation_audit (
            patient_id, assessment_id, event_id, recommendation_family, recommended_option,
            selected_option, recommended_confidence, clinician_selected_option,
            clinician_selected_family, followed_system_recommendation,
            discordance_reason_category, decision_capture_status,
            discordance_reason, outcome_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            audit.get("patient_id"),
            audit.get("assessment_id"),
            audit.get("event_id"),
            audit.get("recommendation_family"),
            audit.get("recommended_option"),
            audit.get("selected_option"),
            audit.get("recommended_confidence"),
            audit.get("clinician_selected_option"),
            audit.get("clinician_selected_family"),
            audit.get("followed_system_recommendation"),
            audit.get("discordance_reason_category"),
            audit.get("decision_capture_status"),
            audit.get("discordance_reason"),
            _json_blob(audit.get("outcome_snapshot", {})),
        ),
    )


def _persist_copilot_alerts(cursor, patient_id, alerts, source_snapshot_id=None):
    alert_models = [dict(alert) for alert in (alerts or []) if isinstance(alert, dict)]
    alert_keys = {str(alert.get("alert_key") or "").strip() for alert in alert_models if str(alert.get("alert_key") or "").strip()}

    if alert_keys:
        cursor.execute(
            f"""
            UPDATE smart_alerts
            SET active = 0
            WHERE patient_id = ?
              AND COALESCE(active, 1) = 1
              AND COALESCE(alert_key, '') NOT IN ({",".join(["?"] * len(alert_keys))})
            """,
            (patient_id, *alert_keys),
        )
    else:
        cursor.execute(
            '''
            UPDATE smart_alerts
            SET active = 0
            WHERE patient_id = ? AND COALESCE(active, 1) = 1
            ''',
            (patient_id,),
        )

    existing_by_key = {}
    cursor.execute(
        '''
        SELECT id, alert_key, acknowledged
        FROM smart_alerts
        WHERE patient_id = ? AND COALESCE(active, 1) = 1
        ''',
        (patient_id,),
    )
    for row in cursor.fetchall():
        existing_by_key[str(row[1] or "")] = {"id": row[0], "acknowledged": row[2]}

    for alert in alert_models:
        alert_key = str(alert.get("alert_key") or "").strip()
        if not alert_key:
            continue
        payload = dict(alert)
        previous = existing_by_key.get(alert_key)
        if previous:
            cursor.execute(
                '''
                UPDATE smart_alerts
                SET alert_date = CURRENT_TIMESTAMP,
                    alert_type = ?,
                    decision_domain = ?,
                    severity = ?,
                    title = ?,
                    description = ?,
                    data_json = ?,
                    source_snapshot_id = ?,
                    active = 1
                WHERE id = ?
                ''',
                (
                    alert.get("category"),
                    alert.get("decision_domain"),
                    alert.get("severity"),
                    alert.get("title"),
                    alert.get("message"),
                    _json_blob(payload),
                    source_snapshot_id,
                    previous["id"],
                ),
            )
            continue
        cursor.execute(
            '''
            INSERT INTO smart_alerts (
                patient_id, alert_key, alert_type, decision_domain, severity, title,
                description, data_json, source_snapshot_id, active, acknowledged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
            ''',
            (
                patient_id,
                alert_key,
                alert.get("category"),
                alert.get("decision_domain"),
                alert.get("severity"),
                alert.get("title"),
                alert.get("message"),
                _json_blob(payload),
                source_snapshot_id,
            ),
        )


def _persist_outcome_events(cursor, patient_id, events):
    models = [dict(event) for event in (events or []) if isinstance(event, dict)]
    event_keys = {str(item.get("event_key") or "").strip() for item in models if str(item.get("event_key") or "").strip()}

    if event_keys:
        cursor.execute(
            f"""
            UPDATE outcome_events
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
              AND COALESCE(active, 1) = 1
              AND COALESCE(event_key, '') NOT IN ({",".join(["?"] * len(event_keys))})
            """,
            (patient_id, *event_keys),
        )
    else:
        cursor.execute(
            """
            UPDATE outcome_events
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND COALESCE(active, 1) = 1
            """,
            (patient_id,),
        )

    existing_by_key = {}
    cursor.execute(
        """
        SELECT id, event_key
        FROM outcome_events
        WHERE patient_id = ?
        """,
        (patient_id,),
    )
    for row in cursor.fetchall():
        existing_by_key[str(row[1] or "")] = row[0]

    for event in models:
        event_key = str(event.get("event_key") or "").strip()
        if not event_key:
            continue
        blocking_fields = list(event.get("blocking_fields") or [])
        evidence_basis = list(event.get("evidence_basis") or [])
        payload = dict(event.get("payload") or {})
        existing_id = existing_by_key.get(event_key)
        values = (
            event_key,
            event.get("event_type"),
            event.get("scenario_state"),
            event.get("management_track"),
            event.get("axis"),
            event.get("adjudication_status"),
            event.get("event_date"),
            event.get("source_priority"),
            event.get("decision_impact"),
            event.get("summary"),
            1 if event.get("provisional") else 0,
            1,
            _json_blob(blocking_fields),
            _json_blob(evidence_basis),
            _json_blob(payload),
        )
        if existing_id:
            cursor.execute(
                """
                UPDATE outcome_events
                SET event_key = ?,
                    event_type = ?,
                    scenario_state = ?,
                    management_track = ?,
                    axis = ?,
                    adjudication_status = ?,
                    event_date = ?,
                    source_priority = ?,
                    decision_impact = ?,
                    summary = ?,
                    provisional = ?,
                    active = ?,
                    blocking_fields_json = ?,
                    evidence_basis_json = ?,
                    payload_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, existing_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO outcome_events (
                    patient_id, event_key, event_type, scenario_state, management_track, axis,
                    adjudication_status, event_date, source_priority, decision_impact, summary,
                    provisional, active, blocking_fields_json, evidence_basis_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (patient_id, *values),
            )


def _persist_adjudication_snapshot(cursor, patient_id, bundle):
    cursor.execute(
        """
        INSERT INTO adjudication_snapshots (
            patient_id, state, management_track, engine_version, current_course_status,
            current_response_state_json, last_adjudicated_event_json, pending_adjudications_json,
            outcome_events_summary_json, milestone_plan_json, outcome_anchor_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(patient_id) DO UPDATE SET
            state=excluded.state,
            management_track=excluded.management_track,
            engine_version=excluded.engine_version,
            current_course_status=excluded.current_course_status,
            current_response_state_json=excluded.current_response_state_json,
            last_adjudicated_event_json=excluded.last_adjudicated_event_json,
            pending_adjudications_json=excluded.pending_adjudications_json,
            outcome_events_summary_json=excluded.outcome_events_summary_json,
            milestone_plan_json=excluded.milestone_plan_json,
            outcome_anchor_json=excluded.outcome_anchor_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            patient_id,
            bundle.get("state"),
            bundle.get("management_track"),
            bundle.get("engine_version"),
            bundle.get("current_course_status"),
            _json_blob(bundle.get("current_response_state") or {}),
            _json_blob(bundle.get("last_adjudicated_event") or {}),
            _json_blob(bundle.get("pending_adjudications") or []),
            _json_blob(bundle.get("outcome_events_summary") or {}),
            _json_blob(bundle.get("milestone_plan") or []),
            _json_blob(bundle.get("outcome_anchor") or {}),
        ),
    )


def _persist_trial_benchmark_snapshot(cursor, patient_id, bundle):
    benchmark_snapshot = {
        "benchmark_snapshots": list(bundle.get("benchmark_snapshots") or []),
        "survival_status": dict(bundle.get("survival_status") or {}),
        "live_benchmark": dict(bundle.get("live_benchmark") or {}),
        "benchmark_reliability": dict(bundle.get("benchmark_reliability") or {}),
    }
    cursor.execute(
        """
        INSERT INTO trial_benchmark_snapshots (
            patient_id, state, management_track, engine_version,
            current_trial_profile_json, trial_endpoints_json, benchmark_snapshot_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(patient_id) DO UPDATE SET
            state=excluded.state,
            management_track=excluded.management_track,
            engine_version=excluded.engine_version,
            current_trial_profile_json=excluded.current_trial_profile_json,
            trial_endpoints_json=excluded.trial_endpoints_json,
            benchmark_snapshot_json=excluded.benchmark_snapshot_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            patient_id,
            bundle.get("state"),
            bundle.get("management_track"),
            bundle.get("engine_version"),
            _json_blob(bundle.get("current_trial_comparable_profile") or {}),
            _json_blob(bundle.get("trial_comparable_endpoints") or []),
            _json_blob(benchmark_snapshot),
        ),
    )


def _persist_crpc_copilot_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO crpc_copilot_snapshots (
            patient_id, trigger_event, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json,
            concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _persist_post_rp_salvage_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO post_rp_salvage_snapshots (
            patient_id, trigger_event, post_prostatectomy_course, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json, concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("post_prostatectomy_course") or "",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _persist_mhspc_copilot_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO mhspc_copilot_snapshots (
            patient_id, trigger_event, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json,
            concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _persist_diagnostic_biopsy_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO diagnostic_biopsy_snapshots (
            patient_id, trigger_event, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json,
            concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _persist_localized_surveillance_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO localized_surveillance_snapshots (
            patient_id, trigger_event, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json,
            concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _persist_post_rt_salvage_snapshot(cursor, patient_id, bundle, trigger_event):
    if not bundle or not bundle.get("enabled") or not bundle.get("available"):
        return
    cursor.execute(
        """
        INSERT INTO post_rt_salvage_snapshots (
            patient_id, trigger_event, post_rt_course, effective_state, runtime_mode,
            bundle_json, qa_json, final_presented_recommendation_json, concordance_label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            patient_id,
            trigger_event or "longitudinal_refresh",
            bundle.get("post_rt_course") or "",
            bundle.get("effective_state") or bundle.get("state_family") or "",
            bundle.get("runtime_mode") or "shadow",
            _json_blob(bundle),
            _json_blob(bundle.get("qa_validation") or {}),
            _json_blob(bundle.get("final_presented_recommendation") or {}),
            (bundle.get("ai_advisory_overlay") or {}).get("concordance_label", ""),
        ),
    )


def _build_copilot_orchestration(patient_record, signals=None, longitudinal_bundle=None):
    from prostanet.domains.patient_tracking.copilot_alerts import build_copilot_alerts
    from prostanet.domains.patient_tracking.followup_agenda import enrich_agenda_board_with_encounters
    from prostanet.domains.patient_tracking.master_followup_plan import build_master_followup_plan
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    if not patient_record or not patient_record.get("identity"):
        return {}

    patient_record = _merge_longitudinal_runtime_record_context(
        patient_record,
        longitudinal_bundle=longitudinal_bundle,
        signals=signals,
    )
    reconciliation = build_reconciled_state(patient_record, patient_record.get("latest_assessment"))
    state = (
        reconciliation.get("reconciled_state")
        or (patient_record.get("latest_assessment") or {}).get("state")
        or (patient_record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    management_track = reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
    agenda_board = refresh_followup_agenda(patient_record, longitudinal_bundle=longitudinal_bundle)
    refreshed = load_patient_record_core(patient_record["identity"]["id"], include_ledger=False) or dict(patient_record)
    refreshed = _merge_longitudinal_runtime_record_context(
        refreshed,
        longitudinal_bundle=longitudinal_bundle,
        signals=signals,
    )
    persisted_items = refreshed.get("agenda_items", [])
    active_items = [item for item in persisted_items if item.get("status") not in {"completed", "superseded", "cancelled"}]
    archived_items = [item for item in persisted_items if item.get("status") in {"completed", "superseded", "cancelled"}]
    agenda_board["items"] = active_items
    agenda_board["active_items"] = active_items
    agenda_board["archived_items"] = archived_items
    agenda_board["next_due_items"] = [item for item in active_items if item.get("status") in {"due", "due_today"}][:4]
    agenda_board["overdue_items"] = [item for item in active_items if item.get("status") == "overdue"][:4]
    agenda_board["active_recommendations"] = [item for item in active_items if item.get("status") in {"due", "due_today", "overdue", "scheduled", "blocked"}][:5]
    agenda_board = enrich_agenda_board_with_encounters(agenda_board, state, management_track)
    sync_scheduled_events(
        refreshed,
        state=state,
        management_track=management_track,
        longitudinal_bundle=longitudinal_bundle,
    )

    orchestration_signals = dict(signals or refreshed.get("latest_signal_snapshot") or {})
    orchestration_signals.update(
        {
            "explicit_state": reconciliation.get("explicit_state"),
            "reconciled_state": reconciliation.get("reconciled_state"),
            "reconciled_management_track": reconciliation.get("reconciled_management_track"),
            "state_conflict_flag": reconciliation.get("state_conflict_flag"),
            "state_conflict_reason": reconciliation.get("state_conflict_reason"),
            "supporting_evidence": reconciliation.get("supporting_evidence", {}),
        }
    )
    copilot_bundle = build_copilot_alerts(
        refreshed,
        state=state,
        management_track=management_track,
        signals=orchestration_signals,
        agenda_board=agenda_board,
        encounters=agenda_board.get("encounters", []),
        raw_assessment=refreshed.get("latest_assessment"),
    )
    master_followup_plan = build_master_followup_plan(
        refreshed,
        state=state,
        management_track=management_track,
        agenda_board=agenda_board,
        signals=orchestration_signals,
        copilot_alerts=copilot_bundle.get("alerts", []),
        next_best_action=orchestration_signals.get("next_best_action") or {},
    )
    return {
        "state": state,
        "management_track": management_track,
        "signals": orchestration_signals,
        "agenda_board": agenda_board,
        "encounters": agenda_board.get("encounters", []),
        "copilot_alerts": copilot_bundle.get("alerts", []),
        "alert_summary": copilot_bundle.get("summary", {}),
        "master_followup_plan": master_followup_plan,
        "master_followup_summary": master_followup_plan.get("summary", {}),
        "schedule_anchor_strength": "weak" if (agenda_board.get("protocol_trace") or {}).get("anchor_is_fallback") else "strong",
    }


def _build_signal_snapshot_view(bundle):
    signals = dict(bundle.get("signals") or {})
    published_state = (
        signals.get("effective_state_final")
        or signals.get("effective_state")
        or signals.get("reconciled_state")
        or signals.get("state")
        or ""
    )
    published_track = (
        signals.get("reconciled_management_track")
        or signals.get("management_track")
        or ""
    )
    return {
        "state": published_state,
        "management_track": published_track,
        "ready_to_restage": bool(signals.get("ready_to_restage")),
        "signals": list(signals.get("signals") or []),
        "critical_missing": list(signals.get("critical_missing") or []),
        "awaiting_review": list(signals.get("awaiting_review") or []),
        "active_safety": list(signals.get("active_safety") or []),
        "next_best_action": dict(bundle.get("next_best_action") or {}),
        "decision_governance_bundle": dict(bundle.get("decision_governance_bundle") or {}),
        "diagnostic_certainty_bundle": dict(bundle.get("diagnostic_certainty_bundle") or {}),
        "staging_certainty_bundle": dict(bundle.get("staging_certainty_bundle") or {}),
        "minimum_decisive_dataset_bundle": dict(bundle.get("minimum_decisive_dataset_bundle") or {}),
        "therapeutic_window_bundle": dict(bundle.get("therapeutic_window_bundle") or {}),
        "window_worklist_bundle": dict(bundle.get("window_worklist_bundle") or {}),
        "pro_decision_bundle": dict(bundle.get("pro_decision_bundle") or {}),
        "shared_decision_bundle": dict(bundle.get("shared_decision_bundle") or {}),
        "palliative_transition_bundle": dict(bundle.get("palliative_transition_bundle") or {}),
        "palliative_monitoring_package": dict(bundle.get("palliative_monitoring_package") or {}),
        "survivorship_transition_bundle": dict(bundle.get("survivorship_transition_bundle") or {}),
        "survivorship_monitoring_package": dict(bundle.get("survivorship_monitoring_package") or {}),
        "score_interpretation_catalog_snapshot": dict(bundle.get("score_interpretation_catalog_snapshot") or {}),
        "precision_workflow_bundle": dict(bundle.get("precision_workflow_bundle") or {}),
        "registry_core_bundle": dict(bundle.get("registry_core_bundle") or {}),
        "endpoint_adjudication_bundle": dict(bundle.get("endpoint_adjudication_bundle") or {}),
        "data_certainty_bundle": dict(bundle.get("data_certainty_bundle") or {}),
        "mcode_projection": dict(signals.get("mcode_projection") or {}),
        "evidence_basis": list(signals.get("evidence_basis") or []),
    }


def _merge_longitudinal_runtime_record_context(patient_record, longitudinal_bundle=None, signals=None):
    context = dict(patient_record or {})
    bundle = dict(longitudinal_bundle or {})
    merged_signals = dict(context.get("latest_signal_snapshot") or {})
    merged_signals.update(dict(signals or bundle.get("signals") or {}))
    for key in (
        "transition_resolution",
        "care_intent_contract",
        "decision_governance_bundle",
        "decision_blocking_bundle",
        "diagnostic_certainty_bundle",
        "staging_certainty_bundle",
        "minimum_decisive_dataset_bundle",
        "therapeutic_window_bundle",
        "window_worklist_bundle",
        "clinician_decision_capture_bundle",
        "state_transition_confirmation_bundle",
        "adherence_tracking_bundle",
        "tumor_board_outcome_bundle",
        "pro_decision_bundle",
        "shared_decision_bundle",
        "ctdna_refinement_bundle",
        "multimodal_imaging_concordance_bundle",
        "precision_workflow_bundle",
        "registry_core_bundle",
        "endpoint_adjudication_bundle",
        "data_certainty_bundle",
        "ichom_compliance_bundle",
        "treatment_adverse_event_bundle",
        "population_survival_context_bundle",
        "cost_access_context_bundle",
        "score_interpretation_catalog_snapshot",
        "palliative_transition_bundle",
        "palliative_monitoring_package",
        "survivorship_transition_bundle",
        "survivorship_monitoring_package",
        "late_effects_profile",
        "functional_recovery_profile",
        "survivorship_schedule_overlay",
        "survivorship_plan",
        "symptom_burden_profile",
        "advance_care_planning_status",
        "hospice_eligibility",
        "acute_palliative_alerts",
        "recommended_supportive_referrals",
        "guideline_followup_plan",
        "longitudinal_truth_snapshot",
        "decision_recalculation_trace",
        "laboratory_intelligence_profile",
        "latest_clinically_decisive_visit",
        "crpc_copilot_bundle",
        "post_rp_salvage_bundle",
        "mhspc_copilot_bundle",
        "diagnostic_biopsy_bundle",
        "localized_surveillance_bundle",
        "post_rt_salvage_bundle",
        "post_rt_schedule_overlay",
        "advanced_followup_bundle",
        "staging_adjudication_bundle",
        "advanced_release_gate",
        "supportive_care_toxicity_readiness_bundle",
        "therapeutic_readiness_bundle",
        "clinical_kernel_snapshot",
        "effective_state",
        "effective_recommendation_family",
        "surface_consistency_status",
        "surface_consistency_flags",
        "clinical_fact_bundle",
        "fact_freshness_summary",
        "fact_conflict_summary",
        "contradiction_resolution_bundle",
        "state_reclassification_bundle",
        "clinical_ledger_bundle",
    ):
        value = bundle.get(key)
        if value not in (None, "", [], {}):
            context[key] = value
            merged_signals[key] = value
    if bundle.get("copilot_alerts") is not None:
        context["alerts"] = list(bundle.get("copilot_alerts") or [])
    context["latest_signal_snapshot"] = merged_signals
    return context


def refresh_longitudinal_intelligence(
    nss_or_id,
    event_id=None,
    force_recompute=False,
    record=None,
    include_live_benchmark=True,
):
    from prostanet.domains.patient_tracking.longitudinal_intelligence import (
        build_longitudinal_intelligence_bundle,
        build_recommendation_audit,
    )
    from prostanet.domains.patient_tracking.decision_input_requirements_engine import (
        build_decision_input_requirements,
        detect_ui_contradiction_flags,
        merge_staging_adjudication_into_requirements,
    )
    from prostanet.domains.patient_tracking.crpc_copilot_service import (
        build_crpc_copilot_bundle,
    )
    from prostanet.domains.patient_tracking.post_rp_salvage_copilot_service import (
        build_post_rp_salvage_bundle,
    )
    from prostanet.domains.patient_tracking.mhspc_copilot_service import (
        build_mhspc_copilot_bundle,
    )
    from prostanet.domains.patient_tracking.diagnostic_biopsy_copilot_service import (
        build_diagnostic_biopsy_bundle,
    )
    from prostanet.domains.patient_tracking.localized_surveillance_copilot_service import (
        build_localized_surveillance_bundle,
    )
    from prostanet.domains.patient_tracking.post_rt_salvage_copilot_service import (
        build_post_rt_salvage_bundle,
    )
    from prostanet.domains.patient_tracking.vertical_runtime import (
        derive_display_sequence_summary,
        select_primary_vertical_bundle,
    )
    from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle
    from prostanet.domains.patient_tracking.live_benchmark import (
        build_live_benchmark,
        is_live_benchmark_applicable_state,
        resolve_live_benchmark_from_snapshot,
    )
    from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
    from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast
    from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
    from prostanet.domains.patient_tracking.advanced_followup_builder import (
        build_advanced_followup_bundle,
    )
    from prostanet.domains.patient_tracking.clinical_kernel_snapshot_builder import (
        build_runtime_kernel_shadow_context,
    )
    from prostanet.domains.patient_tracking.clinical_ledger_builder import (
        build_patient_clinical_ledger_bundle,
    )
    from prostanet.domains.patient_tracking.staging_adjudication_builder import (
        build_staging_adjudication_bundle,
    )
    from prostanet.domains.patient_tracking.advanced_release_gate_builder import (
        build_advanced_release_gate,
        merge_advanced_release_gate_into_requirements,
    )
    from prostanet.domains.patient_tracking.supportive_care_toxicity_readiness_builder import (
        build_supportive_care_toxicity_readiness_bundle,
    )
    from prostanet.domains.patient_tracking.therapeutic_readiness_builder import (
        build_therapeutic_readiness_bundle,
    )
    from prostanet.domains.patient_tracking.clinical_readiness_tower import (
        build_clinical_readiness_tower,
    )
    from prostanet.domains.patient_tracking.tumor_board_os import (
        build_tumor_board_os,
    )
    from prostanet.domains.patient_tracking.care_pathway_os import (
        build_care_pathway_os,
    )
    from prostanet.domains.patient_tracking.clinical_memory_os import (
        build_clinical_memory_os,
    )
    from prostanet.domains.patient_tracking.runtime_publication_builder import (
        build_runtime_publication_payload,
        prepare_runtime_publication_state,
    )
    from prostanet.domains.patient_tracking.runtime_signal_snapshot_builder import (
        build_runtime_signal_snapshot,
    )
    from prostanet.domains.clinical_validation.repository import persist_patient_clinical_ledger

    if force_recompute:
        recompute_patient_care_plan(nss_or_id)
        record = None
    record = record or load_patient_record_core(nss_or_id, include_ledger=False)
    if not record:
        return {}
    bundle = build_longitudinal_intelligence_bundle(record, record.get("latest_assessment"))
    audit = build_recommendation_audit(record["identity"]["id"], record, record.get("latest_assessment"), event_id=event_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    _persist_signal_snapshot(c, record["identity"]["id"], event_id, bundle)
    _persist_transition_proposals(c, record["identity"]["id"], event_id, bundle.get("transition_proposals", []))
    if event_id is not None or force_recompute:
        _persist_recommendation_audit(c, audit)
    conn.commit()
    conn.close()
    refreshed = load_patient_record_core(nss_or_id, include_ledger=False) or dict(record)
    latest_snapshot = dict(refreshed.get("latest_signal_snapshot") or {})
    if not latest_snapshot:
        latest_snapshot = _build_signal_snapshot_view(bundle)
    fresh_next_best_action = dict(bundle.get("next_best_action") or {})
    if fresh_next_best_action:
        latest_snapshot["next_best_action"] = fresh_next_best_action
    outcome_bundle = build_disease_course_bundle(
        refreshed,
        latest_assessment=refreshed.get("latest_assessment"),
    )
    risk_tools_bundle = build_risk_tools_panel(
        patient=refreshed,
        state=bundle.get("signals", {}).get("reconciled_state") or bundle.get("signals", {}).get("state") or "",
        raw_assessment=refreshed.get("latest_assessment"),
        display_assessment={},
    )
    prognostic_bundle = build_prognostic_impact_bundle(
        patient=refreshed,
        state=bundle.get("signals", {}).get("reconciled_state") or bundle.get("signals", {}).get("state") or "",
        management_track=bundle.get("signals", {}).get("reconciled_management_track") or bundle.get("signals", {}).get("management_track") or "",
        raw_assessment=refreshed.get("latest_assessment"),
        risk_tools_bundle=risk_tools_bundle,
        current_trial_profile=outcome_bundle.get("current_trial_comparable_profile", {}),
    )
    current_state = (
        bundle.get("signals", {}).get("reconciled_state")
        or bundle.get("signals", {}).get("state")
        or (refreshed.get("latest_assessment") or {}).get("state")
        or (refreshed.get("prior_history") or {}).get("current_state")
        or ""
    )
    current_track = (
        bundle.get("signals", {}).get("reconciled_management_track")
        or bundle.get("signals", {}).get("management_track")
        or refreshed.get("management_track")
        or (refreshed.get("prior_history") or {}).get("management_track")
        or ""
    )
    benchmark_state = str(
        bundle.get("signals", {}).get("effective_state_final")
        or bundle.get("signals", {}).get("effective_state")
        or bundle.get("signals", {}).get("phenotype_state")
        or current_state
    )
    fallback_benchmark_state = str(
        (refreshed.get("latest_assessment") or {}).get("state")
        or (refreshed.get("prior_history") or {}).get("current_state")
        or ""
    )
    if not is_live_benchmark_applicable_state(benchmark_state) and is_live_benchmark_applicable_state(fallback_benchmark_state):
        benchmark_state = fallback_benchmark_state
    psa_forecast_bundle = build_psa_forecast(
        refreshed,
        state=current_state,
    )
    if include_live_benchmark:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        cohort_patient_ids = [int(row["id"]) for row in c.fetchall()]
        conn.close()
        cohort_records = []
        for patient_id in cohort_patient_ids:
            cohort_record = get_patient_full_record(patient_id)
            if cohort_record:
                cohort_records.append(cohort_record)
        live_benchmark_bundle = build_live_benchmark(
            refreshed,
            cohort_records,
            state=benchmark_state,
            management_track=current_track,
        )
    else:
        live_benchmark_bundle, _ = resolve_live_benchmark_from_snapshot(
            refreshed,
            state=benchmark_state,
            management_track=current_track,
        )
    outcome_bundle["live_benchmark"] = live_benchmark_bundle
    outcome_bundle["benchmark_reliability"] = live_benchmark_bundle.get("reliability", {})
    decision_input_requirements = bundle.get("decision_input_requirements") or build_decision_input_requirements(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        next_best_action=bundle.get("next_best_action", {}),
    )
    trigger_event = "manual_recalculation" if force_recompute else "event_refresh" if event_id is not None else "longitudinal_refresh"
    crpc_copilot_bundle = build_crpc_copilot_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    post_rp_salvage_bundle = build_post_rp_salvage_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    mhspc_copilot_bundle = build_mhspc_copilot_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    diagnostic_biopsy_bundle = build_diagnostic_biopsy_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    localized_surveillance_bundle = build_localized_surveillance_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    post_rt_salvage_bundle = build_post_rt_salvage_bundle(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        trigger_event=trigger_event,
    )
    vertical_bundles = {
        "crpc_copilot_bundle": crpc_copilot_bundle,
        "post_rp_salvage_bundle": post_rp_salvage_bundle,
        "mhspc_copilot_bundle": mhspc_copilot_bundle,
        "diagnostic_biopsy_bundle": diagnostic_biopsy_bundle,
        "localized_surveillance_bundle": localized_surveillance_bundle,
        "post_rt_salvage_bundle": post_rt_salvage_bundle,
        "current_state": current_state,
        "current_track": current_track,
    }
    active_bundle_key, active_copilot_bundle = select_primary_vertical_bundle(vertical_bundles)
    vertical_bundles["active_copilot_bundle"] = active_copilot_bundle
    qa_passed = (
        (active_copilot_bundle.get("qa_validation") or {}).get("approved")
        if active_copilot_bundle
        else None
    )
    sequence_summary = derive_display_sequence_summary(active_copilot_bundle)
    ui_contradiction_flags = detect_ui_contradiction_flags(
        refreshed,
        effective_state=current_state,
        effective_management_track=current_track,
        decision_trace=bundle.get("decision_recalculation_trace", {}),
        schedule_bundle={
            "schedule_state": refreshed.get("schedule_state") or current_state,
            "schedule_management_track": refreshed.get("schedule_management_track") or current_track,
            "schedule_override_reason": refreshed.get("schedule_override_reason") or "",
            "schedule_primary_intent": (bundle.get("guideline_followup_plan") or {}).get("schedule_primary_intent", ""),
            "action_schedule_consistency": (bundle.get("guideline_followup_plan") or {}).get("action_schedule_consistency"),
        },
        transition_resolution=bundle.get("transition_resolution", {}),
        care_intent_contract=bundle.get("care_intent_contract", {}),
    )
    derived_fact_candidates = []
    for fact in list(outcome_bundle.get("clinical_facts") or []):
        fact_key = str(fact.get("fact_key") or "").strip()
        if not fact_key or not _is_present(fact.get("value")):
            continue
        freshness_status, freshness_expires_at = compute_freshness_status(
            fact_key,
            source_date=fact.get("fact_date"),
            observed_at=fact.get("fact_date"),
        )
        derived_fact_candidates.append(
            {
                "fact_key": fact_key,
                "value": fact.get("value"),
                "normalized_value_text": _canonical_value_text(fact.get("value")),
                "source_type": fact.get("source_type") or "derived",
                "source_record_type": "longitudinal_outcome_bundle",
                "source_record_id": event_id,
                "source_date": fact.get("fact_date") or "",
                "observed_at": fact.get("fact_date") or "",
                "state_context": current_state,
                "management_track": current_track,
                "certainty_tier": "derived",
                "freshness_status": freshness_status,
                "freshness_expires_at": freshness_expires_at,
                "clinician_verified": False,
                "verification_note": "",
                "is_active": 1,
            }
        )
    runtime_kernel_context = build_runtime_kernel_shadow_context(
        refreshed,
        latest_assessment=refreshed.get("latest_assessment"),
        derived_fact_candidates=derived_fact_candidates,
    )
    bundle["clinical_kernel_snapshot"] = dict(
        runtime_kernel_context.get("clinical_kernel_snapshot") or {}
    )
    bundle["effective_state"] = str(
        runtime_kernel_context.get("effective_state")
        or current_state
        or ""
    )
    bundle["effective_recommendation_family"] = str(
        runtime_kernel_context.get("effective_recommendation_family")
        or (bundle.get("therapeutic_readiness_bundle") or {}).get("candidate_family")
        or ""
    )
    bundle["surface_consistency_status"] = str(
        runtime_kernel_context.get("surface_consistency_status") or "consistent"
    )
    bundle["surface_consistency_flags"] = list(
        runtime_kernel_context.get("surface_consistency_flags") or []
    )
    bundle["advanced_followup_bundle"] = build_advanced_followup_bundle(
        patient_record=refreshed,
        state=current_state,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        decision_input_requirements=decision_input_requirements,
        signals=latest_snapshot,
    )
    bundle["staging_adjudication_bundle"] = build_staging_adjudication_bundle(
        patient_record=refreshed,
        state=current_state,
        latest_assessment=refreshed.get("latest_assessment"),
        longitudinal_bundle=bundle,
        therapeutic_readiness_bundle=bundle.get("therapeutic_readiness_bundle") or {},
        decision_input_requirements=decision_input_requirements,
        signals=latest_snapshot,
    )
    decision_input_requirements = merge_staging_adjudication_into_requirements(
        decision_input_requirements,
        bundle.get("staging_adjudication_bundle") or {},
    )
    bundle["advanced_release_gate"] = build_advanced_release_gate(
        state=current_state,
        next_best_action=dict(latest_snapshot.get("next_best_action") or bundle.get("next_best_action") or {}),
        decision_input_requirements=decision_input_requirements,
        advanced_followup_bundle=bundle.get("advanced_followup_bundle") or {},
        staging_adjudication_bundle=bundle.get("staging_adjudication_bundle") or {},
        signals=latest_snapshot,
        candidate_family=str(
            (latest_snapshot.get("next_best_action") or {}).get("recommendation_family")
            or (bundle.get("therapeutic_readiness_bundle") or {}).get("candidate_family")
            or ""
        ),
    )
    decision_input_requirements = merge_advanced_release_gate_into_requirements(
        decision_input_requirements,
        bundle.get("advanced_release_gate") or {},
    )
    clinical_fact_bundle = dict(
        runtime_kernel_context.get("clinical_fact_bundle")
        or bundle.get("clinical_fact_bundle")
        or {}
    )
    bundle["supportive_care_toxicity_readiness_bundle"] = build_supportive_care_toxicity_readiness_bundle(
        patient_record=refreshed,
        state=current_state,
        management_track=current_track,
        latest_assessment=refreshed.get("latest_assessment"),
        clinical_fact_bundle=clinical_fact_bundle,
        decision_input_requirements=decision_input_requirements,
        palliative_transition_bundle=bundle.get("palliative_transition_bundle") or {},
        palliative_monitoring_package=bundle.get("palliative_monitoring_package") or {},
        survivorship_transition_bundle=bundle.get("survivorship_transition_bundle") or {},
        survivorship_monitoring_package=bundle.get("survivorship_monitoring_package") or {},
    )
    assessment_result_snapshot = dict(
        ((refreshed.get("latest_assessment") or {}).get("result_snapshot") or {})
    )
    if not bundle.get("therapeutic_readiness_bundle"):
        bundle["therapeutic_readiness_bundle"] = build_therapeutic_readiness_bundle(
            state=current_state,
            phenotype_state=str(latest_snapshot.get("phenotype_state") or current_state or ""),
            preferred_regimen=dict(assessment_result_snapshot.get("preferred_frontline_regimen") or {}),
            next_best_action=dict(latest_snapshot.get("next_best_action") or bundle.get("next_best_action") or {}),
            decision_input_requirements=decision_input_requirements,
            comparative_eligibility_matrix=dict(
                bundle.get("comparative_eligibility_matrix")
                or assessment_result_snapshot.get("comparative_eligibility_matrix")
                or {}
            ),
            systemic_regimen_scope_contract=dict(
                bundle.get("systemic_regimen_scope_contract")
                or assessment_result_snapshot.get("systemic_regimen_scope_contract")
                or {}
            ),
            care_intent_contract=dict(bundle.get("care_intent_contract") or {}),
            palliative_transition_bundle=dict(bundle.get("palliative_transition_bundle") or {}),
            survivorship_transition_bundle=dict(bundle.get("survivorship_transition_bundle") or {}),
            therapeutic_window_bundle=dict(bundle.get("therapeutic_window_bundle") or {}),
            active_regimen_monitoring_package=dict(
                bundle.get("active_regimen_monitoring_package")
                or assessment_result_snapshot.get("active_regimen_monitoring_package")
                or {}
            ),
            recommendation_block_status=str(
                bundle.get("recommendation_block_status")
                or latest_snapshot.get("recommendation_block_status")
                or ""
            ),
            recommendation_block_reason=str(
                bundle.get("recommendation_block_reason")
                or latest_snapshot.get("recommendation_block_reason")
                or ""
            ),
            allowed_actions_while_blocked=list(
                bundle.get("allowed_actions_while_blocked")
                or latest_snapshot.get("allowed_actions_while_blocked")
                or []
            ),
            signals=dict(latest_snapshot or {}),
            advanced_followup_bundle=dict(bundle.get("advanced_followup_bundle") or {}),
            staging_adjudication_bundle=dict(bundle.get("staging_adjudication_bundle") or {}),
            supportive_care_toxicity_readiness_bundle=dict(
                bundle.get("supportive_care_toxicity_readiness_bundle") or {}
            ),
            advanced_release_gate=dict(bundle.get("advanced_release_gate") or {}),
            clinical_fact_bundle=clinical_fact_bundle,
        )
    bundle["clinical_readiness_tower"] = build_clinical_readiness_tower(
        refreshed,
        longitudinal_bundle=bundle,
        state=current_state,
        management_track=current_track,
        patient_ref=str((refreshed.get("identity") or {}).get("nss") or nss_or_id or ""),
    )
    bundle["tumor_board_os"] = build_tumor_board_os(
        refreshed,
        longitudinal_bundle=bundle,
        state=current_state,
        management_track=current_track,
        patient_ref=str((refreshed.get("identity") or {}).get("nss") or nss_or_id or ""),
    )
    latest_snapshot["clinical_readiness_tower"] = bundle["clinical_readiness_tower"]
    latest_snapshot["tumor_board_os"] = bundle["tumor_board_os"]
    runtime_signal_projection = build_runtime_signal_snapshot(
        patient_record=refreshed,
        bundle=bundle,
        latest_snapshot=latest_snapshot,
        decision_input_requirements=decision_input_requirements,
        outcome_bundle=outcome_bundle,
        prognostic_bundle=prognostic_bundle,
        psa_forecast_bundle=psa_forecast_bundle,
        live_benchmark_bundle=live_benchmark_bundle,
        vertical_bundles=vertical_bundles,
        kernel_bundles=runtime_kernel_context,
        qa_passed=qa_passed,
        sequence_summary=sequence_summary,
        ui_contradiction_flags=ui_contradiction_flags,
    )
    latest_snapshot = runtime_signal_projection.get("signals") or {}
    runtime_bundle = runtime_signal_projection.get("runtime_bundle") or dict(bundle)
    published_recommendation = runtime_signal_projection.get("published_recommendation") or {}
    prepublication = prepare_runtime_publication_state(
        patient_record=refreshed,
        bundle=runtime_bundle,
        signals=latest_snapshot,
        decision_input_requirements=decision_input_requirements,
        vertical_bundles={
            **vertical_bundles,
            "published_recommendation": published_recommendation,
        },
    )
    latest_snapshot = prepublication.get("signals") or latest_snapshot
    runtime_context_bundle = prepublication.get("runtime_context_bundle") or {}
    orchestration = _build_copilot_orchestration(
        refreshed,
        signals=latest_snapshot,
        longitudinal_bundle=runtime_context_bundle,
    )
    care_pathway_bundle = {
        **dict(runtime_bundle or {}),
        **dict(runtime_context_bundle or {}),
        "signals": latest_snapshot,
        "clinical_readiness_tower": runtime_bundle.get("clinical_readiness_tower")
        or bundle.get("clinical_readiness_tower")
        or latest_snapshot.get("clinical_readiness_tower")
        or {},
        "tumor_board_os": runtime_bundle.get("tumor_board_os")
        or bundle.get("tumor_board_os")
        or latest_snapshot.get("tumor_board_os")
        or {},
        "master_followup_plan": orchestration.get("master_followup_plan")
        or runtime_bundle.get("master_followup_plan")
        or {},
        "guideline_followup_plan": orchestration.get("guideline_followup_plan")
        or runtime_bundle.get("guideline_followup_plan")
        or {},
        "scheduled_items": orchestration.get("scheduled_items")
        or orchestration.get("schedule")
        or runtime_bundle.get("scheduled_items")
        or [],
        "active_schedule": orchestration.get("active_schedule")
        or runtime_bundle.get("active_schedule")
        or [],
        "encounters": orchestration.get("encounters")
        or runtime_bundle.get("encounters")
        or [],
    }
    care_pathway_os = build_care_pathway_os(
        refreshed,
        longitudinal_bundle=care_pathway_bundle,
        state=current_state,
        management_track=current_track,
        patient_ref=str((refreshed.get("identity") or {}).get("nss") or nss_or_id or ""),
    )
    bundle["care_pathway_os"] = care_pathway_os
    runtime_bundle["care_pathway_os"] = care_pathway_os
    latest_snapshot["care_pathway_os"] = care_pathway_os
    clinical_memory_bundle = {
        **dict(runtime_bundle or {}),
        **dict(runtime_context_bundle or {}),
        "signals": latest_snapshot,
        "clinical_readiness_tower": runtime_bundle.get("clinical_readiness_tower")
        or bundle.get("clinical_readiness_tower")
        or latest_snapshot.get("clinical_readiness_tower")
        or {},
        "tumor_board_os": runtime_bundle.get("tumor_board_os")
        or bundle.get("tumor_board_os")
        or latest_snapshot.get("tumor_board_os")
        or {},
        "care_pathway_os": care_pathway_os,
        "outcome_events": outcome_bundle.get("outcome_events", []),
        "outcome_events_summary": outcome_bundle.get("outcome_events_summary", {}),
        "current_response_state": outcome_bundle.get("current_response_state", {}),
        "current_course_status": outcome_bundle.get("current_course_status", ""),
        "last_adjudicated_event": outcome_bundle.get("last_adjudicated_event", {}),
        "clinical_fact_bundle": runtime_kernel_context.get("clinical_fact_bundle", {}),
    }
    clinical_memory_os = build_clinical_memory_os(
        refreshed,
        longitudinal_bundle=clinical_memory_bundle,
        state=current_state,
        management_track=current_track,
        patient_ref=str((refreshed.get("identity") or {}).get("nss") or nss_or_id or ""),
    )
    bundle["clinical_memory_os"] = clinical_memory_os
    runtime_bundle["clinical_memory_os"] = clinical_memory_os
    latest_snapshot["clinical_memory_os"] = clinical_memory_os
    clinical_ledger_bundle = build_patient_clinical_ledger_bundle(refreshed)
    publication_projection = build_runtime_publication_payload(
        patient_record=refreshed,
        bundle=runtime_bundle,
        signals=latest_snapshot,
        orchestration=orchestration,
        decision_input_requirements=decision_input_requirements,
        outcome_bundle=outcome_bundle,
        prognostic_bundle=prognostic_bundle,
        psa_forecast_bundle=psa_forecast_bundle,
        live_benchmark_bundle=live_benchmark_bundle,
        vertical_bundles={
            **vertical_bundles,
            "published_recommendation": published_recommendation,
        },
        kernel_bundles=runtime_kernel_context,
        qa_passed=qa_passed,
        sequence_summary=sequence_summary,
        clinical_ledger_bundle=clinical_ledger_bundle,
        copilot_alerts=[],
        transition_proposals=refreshed.get("transition_proposals") or [],
        recommendation_audit=refreshed.get("recommendation_audit") or [],
    )
    latest_snapshot = publication_projection.get("signals") or latest_snapshot
    runtime_context_bundle = publication_projection.get("runtime_context_bundle") or runtime_context_bundle
    signals_to_persist = publication_projection.get("signals_to_persist") or {
        "signals": latest_snapshot,
        "next_best_action": latest_snapshot.get("next_best_action", {}),
    }
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    signal_snapshot_id = (refreshed.get("latest_signal_snapshot") or {}).get("id")
    _persist_signal_snapshot(
        c,
        refreshed["identity"]["id"],
        event_id,
        signals_to_persist,
    )
    _persist_patient_clinical_facts(c, refreshed["identity"]["id"], derived_fact_candidates)
    _persist_therapeutic_window_events(c, refreshed["identity"]["id"], runtime_bundle.get("window_worklist_bundle") or {})
    _persist_copilot_alerts(c, refreshed["identity"]["id"], orchestration.get("copilot_alerts", []), source_snapshot_id=signal_snapshot_id)
    _persist_outcome_events(c, refreshed["identity"]["id"], outcome_bundle.get("outcome_events", []))
    _persist_adjudication_snapshot(c, refreshed["identity"]["id"], outcome_bundle)
    if include_live_benchmark:
        _persist_trial_benchmark_snapshot(c, refreshed["identity"]["id"], outcome_bundle)
    if event_id is not None or force_recompute:
        _persist_crpc_copilot_snapshot(c, refreshed["identity"]["id"], crpc_copilot_bundle, trigger_event)
        _persist_post_rp_salvage_snapshot(c, refreshed["identity"]["id"], post_rp_salvage_bundle, trigger_event)
        _persist_mhspc_copilot_snapshot(c, refreshed["identity"]["id"], mhspc_copilot_bundle, trigger_event)
        _persist_diagnostic_biopsy_snapshot(c, refreshed["identity"]["id"], diagnostic_biopsy_bundle, trigger_event)
        _persist_localized_surveillance_snapshot(c, refreshed["identity"]["id"], localized_surveillance_bundle, trigger_event)
        _persist_post_rt_salvage_snapshot(c, refreshed["identity"]["id"], post_rt_salvage_bundle, trigger_event)
    conn.commit()
    conn.close()
    published_alerts = get_patient_alerts(refreshed["identity"]["id"])
    persist_patient_clinical_ledger(
        int(refreshed["identity"]["id"]),
        decision_trace=runtime_bundle.get("decision_recalculation_trace", {}),
        guideline_plan=runtime_bundle.get("guideline_followup_plan", {}),
        signals=latest_snapshot,
        missing_input_requirements=decision_input_requirements,
        latest_clinically_decisive_visit=runtime_bundle.get("latest_clinically_decisive_visit", {}),
        event_id=event_id,
    )
    publication_projection = {
        **publication_projection,
        "public_payload": {
            **dict(publication_projection.get("public_payload") or {}),
            "copilot_alerts": list(published_alerts or []),
        },
    }
    return publication_projection.get("public_payload") or {}


def refresh_followup_agenda(patient_record, longitudinal_bundle=None):
    from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    if not patient_record:
        return {}
    patient_record = _merge_longitudinal_runtime_record_context(
        patient_record,
        longitudinal_bundle=longitudinal_bundle,
    )
    reconciliation = build_reconciled_state(patient_record, patient_record.get("latest_assessment"))
    state = reconciliation.get("reconciled_state") or (
        (patient_record.get("latest_assessment") or {}).get("state")
        or (patient_record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    management_track = reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
    agenda_board = build_agenda_board(
        patient_record,
        state,
        management_track,
        patient_record.get("latest_assessment"),
        longitudinal_bundle=longitudinal_bundle,
    )
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    _upsert_agenda_items(c, patient_record["identity"]["id"], agenda_board.get("items", []))
    conn.commit()
    conn.close()
    return agenda_board


def get_patient_agenda(nss_or_id):
    from prostanet.domains.patient_tracking.clinical_decision_governance import prioritize_items_for_window_worklist
    from prostanet.domains.patient_tracking.followup_agenda import enrich_agenda_board_with_encounters, longitudinal_item_sort_key

    record = get_patient_full_record(nss_or_id)
    if not record:
        return None
    longitudinal_bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False, record=record)
    agenda_board = refresh_followup_agenda(record, longitudinal_bundle=longitudinal_bundle)
    refreshed = get_patient_full_record(nss_or_id)
    persisted_items = refreshed.get("agenda_items", [])
    active_items = [item for item in persisted_items if item.get("status") not in {"completed", "superseded", "cancelled"}]
    archived_items = [item for item in persisted_items if item.get("status") in {"completed", "superseded", "cancelled"}]
    agenda_board["items"] = active_items
    agenda_board["active_items"] = active_items
    agenda_board["archived_items"] = archived_items
    agenda_board["next_due_items"] = [item for item in active_items if item.get("status") in {"due", "due_today"}][:4]
    agenda_board["overdue_items"] = [item for item in active_items if item.get("status") == "overdue"][:4]
    agenda_board["active_recommendations"] = [item for item in active_items if item.get("status") in {"due", "overdue", "scheduled", "blocked"}][:5]
    agenda_board = enrich_agenda_board_with_encounters(
        agenda_board,
        agenda_board.get("state") or agenda_board.get("protocol_trace", {}).get("state") or agenda_board.get("stage_protocol", {}).get("state") or "",
        agenda_board.get("management_track") or "",
    )
    schedule_bundle = sync_scheduled_events(
        refreshed,
        state=agenda_board.get("state") or "",
        management_track=agenda_board.get("management_track") or "",
        longitudinal_bundle=longitudinal_bundle,
    )
    schedule_by_key = {
        str(item.get("schedule_key") or ""): item
        for item in (schedule_bundle.get("scheduled_items") or [])
        if str(item.get("schedule_key") or "")
    }
    merged_active_items = []
    for item in list(agenda_board.get("active_items") or []):
        current = dict(item)
        scheduled = schedule_by_key.get(str(current.get("agenda_key") or ""), {})
        current["plan_key"] = scheduled.get("plan_key") or current.get("plan_key") or (schedule_bundle.get("master_followup_plan") or {}).get("plan_key", "")
        current["ideal_due_at"] = scheduled.get("ideal_due_at") or current.get("ideal_due_at") or current.get("due_at") or ""
        current["scheduled_due_at"] = scheduled.get("scheduled_due_at") or current.get("scheduled_due_at") or current.get("due_at") or ""
        current["delay_days"] = int(scheduled.get("delay_days") or current.get("delay_days") or 0)
        current["completed_at"] = scheduled.get("completed_at") or current.get("completed_at") or ""
        current["required"] = bool(scheduled.get("required", current.get("required", True)))
        current["action_mode"] = scheduled.get("action_mode") or current.get("action_mode") or "capture"
        merged_active_items.append(current)
    merged_active_items.sort(key=longitudinal_item_sort_key)
    merged_active_items = prioritize_items_for_window_worklist(
        merged_active_items,
        longitudinal_bundle.get("window_worklist_bundle") or {},
    )
    agenda_board["items"] = merged_active_items
    agenda_board["active_items"] = merged_active_items
    agenda_board["next_due_items"] = [item for item in merged_active_items if item.get("status") in {"due", "due_today"}][:4]
    agenda_board["overdue_items"] = [item for item in merged_active_items if item.get("status") == "overdue"][:4]
    agenda_board["active_recommendations"] = [
        item
        for item in merged_active_items
        if item.get("status") in {"due", "overdue", "scheduled", "blocked", "due_today"}
    ][:5]
    agenda_board["master_followup_plan"] = schedule_bundle.get("master_followup_plan", {})
    agenda_board["master_followup_summary"] = schedule_bundle.get("master_followup_summary", {})
    agenda_board["alerts_linked"] = (schedule_bundle.get("master_followup_plan") or {}).get("blocking_alerts", [])
    agenda_board["encounter_tasks"] = [
        task
        for encounter in (agenda_board.get("encounters") or [])
        for task in list(encounter.get("tasks") or [])
    ]
    agenda_board["followup_tasks"] = list(agenda_board.get("encounter_tasks") or [])
    agenda_board["adjudication_tasks"] = schedule_bundle.get("pending_adjudication_tasks", [])
    agenda_board["milestone_plan"] = schedule_bundle.get("milestone_plan", [])
    agenda_board["outcome_anchor"] = schedule_bundle.get("outcome_anchor", {})
    agenda_board["outcome_events_summary"] = schedule_bundle.get("outcome_events_summary", {})
    agenda_board["pending_adjudications"] = schedule_bundle.get("pending_adjudications", [])
    agenda_board["current_response_state"] = schedule_bundle.get("current_response_state", {})
    agenda_board["current_course_status"] = schedule_bundle.get("current_course_status", "")
    agenda_board["last_adjudicated_event"] = schedule_bundle.get("last_adjudicated_event", {})
    agenda_board["trial_comparable_endpoints"] = schedule_bundle.get("trial_comparable_endpoints", [])
    agenda_board["current_trial_comparable_profile"] = schedule_bundle.get("current_trial_comparable_profile", {})
    agenda_board["window_worklist_bundle"] = longitudinal_bundle.get("window_worklist_bundle", {})
    return agenda_board


def get_patient_signals(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("signals", {})


def get_patient_crpc_copilot(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("crpc_copilot_bundle", {})


def get_patient_post_rp_salvage(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("post_rp_salvage_bundle", {})


def get_patient_mhspc_copilot(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("mhspc_copilot_bundle", {})


def get_patient_diagnostic_biopsy_copilot(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("diagnostic_biopsy_bundle", {})


def get_patient_localized_surveillance_copilot(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("localized_surveillance_bundle", {})


def get_patient_post_rt_salvage(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("post_rt_salvage_bundle", {})


def get_crpc_copilot_dashboard_summary():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*
        FROM crpc_copilot_snapshots s
        JOIN (
            SELECT patient_id, MAX(id) AS latest_id
            FROM crpc_copilot_snapshots
            GROUP BY patient_id
        ) latest ON latest.latest_id = s.id
        ORDER BY s.created_at DESC, s.id DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "strict_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "blocked_by_safety_pct": 0.0,
            "top_failure_families": [],
            "runtime_modes": {},
            "state_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }

    def _blob_to_obj(value, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default

    total = len(rows)
    aligned = 0
    strict = 0
    qa_pass = 0
    blocked_missing = 0
    blocked_safety = 0
    runtime_modes: dict[str, int] = {}
    state_distribution: dict[str, int] = {}
    failure_families: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []

    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        blocking_inputs = list(bundle.get("blocking_inputs") or [])
        safety_gates = list(bundle.get("safety_gates") or [])
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        runtime_mode = str(row["runtime_mode"] or bundle.get("runtime_mode") or "shadow")
        state = str(row["effective_state"] or bundle.get("effective_state") or bundle.get("state_family") or "")

        runtime_modes[runtime_mode] = runtime_modes.get(runtime_mode, 0) + 1
        state_distribution[state] = state_distribution.get(state, 0) + 1
        if concordance in {"concordant", "adjacent"}:
            aligned += 1
        if concordance == "concordant":
            strict += 1
        if bool(qa.get("approved")):
            qa_pass += 1
        if any(group.get("required_fields") for group in blocking_inputs):
            blocked_missing += 1
        blocked_gate_rows = [gate for gate in safety_gates if str(gate.get("status") or "").lower() == "blocked"]
        if blocked_gate_rows:
            blocked_safety += 1
        for gate in blocked_gate_rows:
            family = str(gate.get("failure_family") or "").strip()
            if family:
                failure_families[family] = failure_families.get(family, 0) + 1

        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "effective_state": state,
                "runtime_mode": runtime_mode,
                "status": str(bundle.get("status") or ""),
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
            }
        )

    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "strict_concordance_pct": round((strict / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "blocked_by_safety_pct": round((blocked_safety / total) * 100, 1),
        "top_failure_families": sorted(
            failure_families.items(),
            key=lambda item: (-item[1], item[0]),
        )[:6],
        "runtime_modes": runtime_modes,
        "state_distribution": state_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def get_post_rp_salvage_dashboard_summary():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*
        FROM post_rp_salvage_snapshots s
        JOIN (
            SELECT patient_id, MAX(id) AS latest_id
            FROM post_rp_salvage_snapshots
            GROUP BY patient_id
        ) latest ON latest.latest_id = s.id
        ORDER BY s.created_at DESC, s.id DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "salvage_window_open_pct": 0.0,
            "redirect_systemic_pct": 0.0,
            "top_failure_families": [],
            "runtime_modes": {},
            "course_distribution": {},
            "salvage_window_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }

    def _blob_to_obj(value, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default

    total = len(rows)
    aligned = 0
    qa_pass = 0
    blocked_missing = 0
    salvage_open = 0
    redirect_systemic = 0
    runtime_modes: dict[str, int] = {}
    course_distribution: dict[str, int] = {}
    salvage_window_distribution: dict[str, int] = {}
    failure_families: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []

    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        blocking_inputs = list(bundle.get("blocking_inputs") or [])
        safety_gates = list(bundle.get("safety_gates") or [])
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        runtime_mode = str(row["runtime_mode"] or bundle.get("runtime_mode") or "shadow")
        course = str(row["post_prostatectomy_course"] or bundle.get("post_prostatectomy_course") or "")
        window_status = str(bundle.get("salvage_window_status") or "")

        runtime_modes[runtime_mode] = runtime_modes.get(runtime_mode, 0) + 1
        course_distribution[course] = course_distribution.get(course, 0) + 1
        salvage_window_distribution[window_status] = salvage_window_distribution.get(window_status, 0) + 1
        if concordance in {"concordant", "adjacent"}:
            aligned += 1
        if bool(qa.get("approved")):
            qa_pass += 1
        if any(group.get("required_fields") for group in blocking_inputs):
            blocked_missing += 1
        if window_status in {"open", "open_pending_restaging"}:
            salvage_open += 1
        if window_status == "redirect_systemic":
            redirect_systemic += 1
        for gate in safety_gates:
            family = str(gate.get("failure_family") or "").strip()
            if gate.get("status") == "blocked" and family:
                failure_families[family] = failure_families.get(family, 0) + 1

        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "effective_state": str(row["effective_state"] or bundle.get("effective_state") or ""),
                "post_prostatectomy_course": course,
                "salvage_window_status": window_status,
                "runtime_mode": runtime_mode,
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
            }
        )

    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "salvage_window_open_pct": round((salvage_open / total) * 100, 1),
        "redirect_systemic_pct": round((redirect_systemic / total) * 100, 1),
        "top_failure_families": sorted(
            failure_families.items(),
            key=lambda item: (-item[1], item[0]),
        )[:6],
        "runtime_modes": runtime_modes,
        "course_distribution": course_distribution,
        "salvage_window_distribution": salvage_window_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def _latest_vertical_snapshot_rows(table_name: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT s.*
        FROM {table_name} s
        JOIN (
            SELECT patient_id, MAX(id) AS latest_id
            FROM {table_name}
            GROUP BY patient_id
        ) latest ON latest.latest_id = s.id
        ORDER BY s.created_at DESC, s.id DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def _blob_to_obj(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def get_mhspc_copilot_dashboard_summary():
    rows = _latest_vertical_snapshot_rows("mhspc_copilot_snapshots")
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "triplet_visible_pct": 0.0,
            "rt_primary_visible_pct": 0.0,
            "mdt_visible_pct": 0.0,
            "runtime_modes": {},
            "phenotype_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }
    total = len(rows)
    aligned = qa_pass = blocked_missing = triplet_visible = rt_visible = mdt_visible = 0
    runtime_modes: dict[str, int] = {}
    phenotype_distribution: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []
    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        phenotype = dict(bundle.get("phenotype_summary") or {})
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        runtime_mode = str(row["runtime_mode"] or bundle.get("runtime_mode") or "shadow")
        state = str(row["effective_state"] or bundle.get("effective_state") or "")
        phenotype_key = f"{state}:{phenotype.get('temporality', '')}:{phenotype.get('volume_disease', '')}"
        runtime_modes[runtime_mode] = runtime_modes.get(runtime_mode, 0) + 1
        phenotype_distribution[phenotype_key] = phenotype_distribution.get(phenotype_key, 0) + 1
        aligned += int(concordance in {"concordant", "adjacent"})
        qa_pass += int(bool(qa.get("approved")))
        blocked_missing += int(any(group.get("required_fields") for group in list(bundle.get("blocking_inputs") or [])))
        triplet_visible += int(bool((bundle.get("triplet_decision") or {}).get("triplet_visible") or (bundle.get("triplet_decision") or {}).get("preferred_triplet")))
        rt_visible += int(bool(phenotype.get("rt_primary_candidate")))
        mdt_visible += int(bool(phenotype.get("mdt_candidate")))
        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "effective_state": state,
                "runtime_mode": runtime_mode,
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
                "preferred_regimen": ((bundle.get("preferred_frontline_regimen") or {}).get("regimen_label") or ""),
            }
        )
    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "triplet_visible_pct": round((triplet_visible / total) * 100, 1),
        "rt_primary_visible_pct": round((rt_visible / total) * 100, 1),
        "mdt_visible_pct": round((mdt_visible / total) * 100, 1),
        "runtime_modes": runtime_modes,
        "phenotype_distribution": phenotype_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def get_diagnostic_biopsy_dashboard_summary():
    rows = _latest_vertical_snapshot_rows("diagnostic_biopsy_snapshots")
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "biopsy_ready_pct": 0.0,
            "reopen_after_negative_pct": 0.0,
            "track_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }
    total = len(rows)
    aligned = qa_pass = blocked_missing = biopsy_ready = reopen = 0
    track_distribution: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []
    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        track = str(bundle.get("diagnostic_track") or "")
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        track_distribution[track] = track_distribution.get(track, 0) + 1
        aligned += int(concordance in {"concordant", "adjacent"})
        qa_pass += int(bool(qa.get("approved")))
        blocked_missing += int(any(group.get("required_fields") for group in list(bundle.get("blocking_inputs") or [])))
        biopsy_ready += int(bool((bundle.get("biopsy_readiness") or {}).get("ready")))
        reopen += int(bool(bundle.get("reopen_signal_after_negative_biopsy")))
        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "diagnostic_track": track,
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
            }
        )
    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "biopsy_ready_pct": round((biopsy_ready / total) * 100, 1),
        "reopen_after_negative_pct": round((reopen / total) * 100, 1),
        "track_distribution": track_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def get_localized_surveillance_dashboard_summary():
    rows = _latest_vertical_snapshot_rows("localized_surveillance_snapshots")
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "active_surveillance_visible_pct": 0.0,
            "upgrade_exit_pct": 0.0,
            "track_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }
    total = len(rows)
    aligned = qa_pass = blocked_missing = as_visible = upgrade_exit = 0
    track_distribution: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []
    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        track = str(bundle.get("localized_track") or "")
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        track_distribution[track] = track_distribution.get(track, 0) + 1
        aligned += int(concordance in {"concordant", "adjacent"})
        qa_pass += int(bool(qa.get("approved")))
        blocked_missing += int(any(group.get("required_fields") for group in list(bundle.get("blocking_inputs") or [])))
        as_visible += int(bool((bundle.get("active_surveillance_course") or {}).get("has_data")))
        upgrade_exit += int(track == "as_exit_due_to_upgrade")
        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "localized_track": track,
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
            }
        )
    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "active_surveillance_visible_pct": round((as_visible / total) * 100, 1),
        "upgrade_exit_pct": round((upgrade_exit / total) * 100, 1),
        "track_distribution": track_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def get_post_rt_salvage_dashboard_summary():
    rows = _latest_vertical_snapshot_rows("post_rt_salvage_snapshots")
    if not rows:
        return {
            "available": False,
            "total_patients": 0,
            "shadow_rule_concordance_pct": 0.0,
            "qa_pass_pct": 0.0,
            "blocked_by_missing_data_pct": 0.0,
            "local_salvage_candidate_pct": 0.0,
            "redirect_systemic_pct": 0.0,
            "course_distribution": {},
            "recent_cases": [],
            "latest_created_at": "",
        }
    total = len(rows)
    aligned = qa_pass = blocked_missing = local_candidate = redirect = 0
    course_distribution: dict[str, int] = {}
    recent_cases: list[dict[str, Any]] = []
    for row in rows:
        bundle = _blob_to_obj(row["bundle_json"], {})
        qa = _blob_to_obj(row["qa_json"], {})
        overlay = dict(bundle.get("ai_advisory_overlay") or {})
        course = str(row["post_rt_course"] or bundle.get("post_rt_course") or "")
        concordance = str(row["concordance_label"] or overlay.get("concordance_label") or "")
        course_distribution[course] = course_distribution.get(course, 0) + 1
        aligned += int(concordance in {"concordant", "adjacent"})
        qa_pass += int(bool(qa.get("approved")))
        blocked_missing += int(any(group.get("required_fields") for group in list(bundle.get("blocking_inputs") or [])))
        local_candidate += int(course == "local_salvage_candidate")
        redirect += int(course == "redirect_systemic")
        recent_cases.append(
            {
                "patient_id": int(row["patient_id"]),
                "post_rt_course": course,
                "window_status": bundle.get("post_rt_salvage_window_status", ""),
                "concordance_label": concordance or "rule_only",
                "qa_passed": bool(qa.get("approved")),
            }
        )
    return {
        "available": True,
        "total_patients": total,
        "shadow_rule_concordance_pct": round((aligned / total) * 100, 1),
        "qa_pass_pct": round((qa_pass / total) * 100, 1),
        "blocked_by_missing_data_pct": round((blocked_missing / total) * 100, 1),
        "local_salvage_candidate_pct": round((local_candidate / total) * 100, 1),
        "redirect_systemic_pct": round((redirect / total) * 100, 1),
        "course_distribution": course_distribution,
        "recent_cases": recent_cases[:5],
        "latest_created_at": rows[0]["created_at"] or "",
    }


def get_patient_outcomes(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return {
        "outcome_events": bundle.get("outcome_events", []),
        "outcome_events_summary": bundle.get("outcome_events_summary", {}),
        "pending_adjudications": bundle.get("pending_adjudications", []),
        "current_response_state": bundle.get("current_response_state", {}),
        "current_course_status": bundle.get("current_course_status", ""),
        "last_adjudicated_event": bundle.get("last_adjudicated_event", {}),
        "trial_comparable_endpoints": bundle.get("trial_comparable_endpoints", []),
        "current_trial_comparable_profile": bundle.get("current_trial_comparable_profile", {}),
        "psa_forecast": bundle.get("psa_forecast", {}),
        "forecast_reliability": bundle.get("forecast_reliability", {}),
        "live_benchmark": bundle.get("live_benchmark", {}),
        "benchmark_reliability": bundle.get("benchmark_reliability", {}),
    }


def get_cohort_benchmarks():
    from prostanet.domains.patient_tracking.disease_course_outcomes import build_cohort_benchmark_aggregate
    from prostanet.domains.patient_tracking.live_benchmark import build_live_benchmark_summary
    from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast_backtest

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id FROM patient_identity ORDER BY id ASC")
    patient_ids = [int(row["id"]) for row in c.fetchall()]
    conn.close()

    patient_records = []
    for patient_id in patient_ids:
        refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        record = get_patient_full_record(patient_id)
        if record:
            patient_records.append(record)
    aggregate = build_cohort_benchmark_aggregate(patient_records)
    aggregate["live_benchmark_summary"] = build_live_benchmark_summary(patient_records)
    aggregate["psa_forecast_summary"] = build_psa_forecast_backtest(patient_records)
    return aggregate


def get_patient_next_best_action(nss_or_id):
    record = get_patient_full_record(nss_or_id)
    bundle = refresh_longitudinal_intelligence(
        nss_or_id,
        force_recompute=True,
        record=record,
        include_live_benchmark=False,
    )
    if not bundle:
        return None
    action = dict((bundle.get("signals") or {}).get("next_best_action") or bundle.get("next_best_action") or {})
    if str(action.get("action_title") or "").strip():
        action["title"] = str(action.get("action_title") or "").strip()
    if str(action.get("action_rationale") or "").strip():
        action["rationale"] = str(action.get("action_rationale") or "").strip()
    if any(token in str(action.get("title") or "").lower() for token in ("salvage", "rescate")):
        action["recommendation_family"] = "salvage"
    return action


def get_patient_labs_intelligence(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("laboratory_intelligence_profile", {})


def get_patient_decision_trace(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("decision_recalculation_trace", {})


def _agenda_input_present(data, field_name):
    if not field_name or str(field_name).startswith("source_document:"):
        return False
    if field_name == "psa" and _is_present(data.get("baseline_psa")):
        return True
    if field_name == "num_cores_positive" and _is_present(data.get("positive_cores")):
        return True
    if field_name in {"gleason_primary", "gleason_secondary"} and _is_present(data.get(f"pathology_{field_name}")):
        return True
    if field_name == "age" and (_is_present(data.get("age")) or _is_present(data.get("dob"))):
        return True
    return _is_present(data.get(field_name))


def _agenda_document_present(patient_record, document_type):
    if not document_type or not patient_record:
        return False
    return any(
        str(document.get("document_type") or "") == str(document_type)
        for document in (patient_record.get("source_documents") or [])
    )


def _agenda_event_target_satisfied(event_target, data, patient_record=None):
    if event_target == "imaging_studies":
        return _is_present(data.get("imaging_modality")) or bool((patient_record or {}).get("imaging_studies"))
    if event_target in {"structured_biopsy_sessions", "biopsy_sessions"}:
        return bool((patient_record or {}).get("structured_biopsy_sessions"))
    return False


def _agenda_tool_capture_requirements():
    try:
        from prostanet.domains.patient_tracking.risk_tools import SCORE_REQUIREMENTS
    except Exception:
        SCORE_REQUIREMENTS = {}
    tool_requirements = {str(key): list(value or []) for key, value in dict(SCORE_REQUIREMENTS or {}).items()}
    tool_requirements.setdefault(
        "briganti",
        ["psa", "clinical_tstage", "gleason_primary", "gleason_secondary", "num_cores_positive", "total_cores"],
    )
    return tool_requirements


def _agenda_score_requirement_met(score_key, data):
    missing = []
    for field_name in _agenda_tool_capture_requirements().get(score_key, []):
        if field_name in {"num_cores_positive", "total_cores"} and _is_present(data.get("pct_cores_positive")):
            continue
        if not _agenda_input_present(data, field_name):
            missing.append(field_name)
    return not missing


def _agenda_requirement_satisfied(requirement, data, patient_record=None):
    requirement = str(requirement or "")
    if not requirement:
        return False
    if requirement.startswith("source_document:"):
        return _agenda_document_present(patient_record, requirement.split(":", 1)[1])
    if requirement in _agenda_tool_capture_requirements():
        return _agenda_score_requirement_met(requirement, data)
    return _agenda_input_present(data, requirement)


def _agenda_resolution_payload_from_record(patient_record, submitted_data):
    try:
        from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
    except Exception:
        merge_record_into_assessment_payload = None

    merged = {}
    if patient_record and merge_record_into_assessment_payload is not None:
        latest_assessment = patient_record.get("latest_assessment") or {}
        assessment_input = dict(latest_assessment.get("input_snapshot") or {})
        merged = merge_record_into_assessment_payload(assessment_input, patient_record) or {}
    merged.update(dict(submitted_data or {}))
    return merged


def _agenda_completion_state(agenda_item, data, *, evaluation_payload=None, patient_record=None):
    payload = evaluation_payload or data or {}
    required_inputs = [field for field in (agenda_item.get("required_inputs") or []) if field]
    completion_rule = agenda_item.get("completion_rule") or {}
    present_required = [field for field in required_inputs if _agenda_requirement_satisfied(field, payload, patient_record)]
    any_of = [field for field in (completion_rule.get("any_of") or []) if field]
    if any_of:
        satisfied = any(_agenda_requirement_satisfied(field, payload, patient_record) for field in any_of)
    elif completion_rule.get("requires_event_target"):
        satisfied = _agenda_event_target_satisfied(completion_rule.get("requires_event_target"), payload, patient_record)
    elif required_inputs:
        satisfied = len(present_required) == len(required_inputs)
    else:
        satisfied = any(
            _is_present(value)
            for key, value in payload.items()
            if key not in {"agenda_ids", "agenda_submission_mode"}
        )
    if satisfied:
        return "completed"
    if present_required or any(
        _is_present(value)
        for key, value in (data or {}).items()
        if key not in {"agenda_ids", "agenda_submission_mode"}
    ):
        return "partially_satisfied"
    return "scheduled"


def _resolve_followup_agenda_item(
    cursor,
    patient_id,
    agenda_id,
    data,
    visit_record_id=None,
    *,
    evaluation_payload=None,
    patient_record=None,
):
    cursor.execute(
        '''
        SELECT agenda_key, item_type, due_at, required_inputs_json, completion_rule_json
        FROM followup_agenda_items
        WHERE id = ? AND patient_id = ?
        ''',
        (agenda_id, patient_id),
    )
    row = cursor.fetchone()
    if not row:
        return False
    agenda_item = {
        "agenda_key": row[0],
        "item_type": row[1],
        "due_at": row[2],
        "required_inputs": _parse_json_blob(row[3], []),
        "completion_rule": _parse_json_blob(row[4], {}),
    }
    status = _agenda_completion_state(
        agenda_item,
        data,
        evaluation_payload=evaluation_payload,
        patient_record=patient_record,
    )
    if status == "completed":
        cursor.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                visit_record_id = COALESCE(?, visit_record_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (visit_record_id, agenda_id, patient_id),
        )
        if agenda_item.get("agenda_key"):
            cursor.execute(
                '''
                UPDATE scheduled_events
                SET completed = 1,
                    completed_date = DATE('now'),
                    completed_visit_id = COALESCE(?, completed_visit_id)
                WHERE patient_id = ?
                  AND schedule_key = ?
                ''',
                (visit_record_id, patient_id, agenda_item["agenda_key"]),
            )
        return cursor.rowcount >= 0
    if status == "partially_satisfied":
        cursor.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'partially_satisfied',
                visit_record_id = COALESCE(?, visit_record_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (visit_record_id, agenda_id, patient_id),
        )
        return cursor.rowcount > 0
    return False


def _confirm_transition_assessment(patient_id, proposal):
    from prostanet.application.module_registry import ModuleRegistry
    from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
    from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload

    record = get_patient_full_record(patient_id)
    if not record:
        return None, "Paciente no encontrado"
    registry = ModuleRegistry()
    assessment_service = ClinicalAssessmentService()
    latest_assessment = record.get("latest_assessment") or {}
    base_payload = dict((latest_assessment or {}).get("input_snapshot", {}) or {})
    payload = merge_record_into_assessment_payload(
        base_payload,
        _build_runtime_neutral_patient_record(record),
    )
    target_state = proposal.get("target_state")
    result = registry.evaluate_module(target_state, payload)
    assessment_id = assessment_service.create_draft(
        module_id=target_state,
        state=result.get("state", target_state),
        input_snapshot=payload,
        result_snapshot=result,
        guideline_versions=registry.get_guidelines_metadata(),
    )
    if assessment_id is None:
        return None, "No se pudo crear la nueva evaluación clínica"
    linked, message = assessment_service.attach_to_patient(assessment_id, patient_id)
    if not linked:
        return None, message
    return assessment_id, "Evaluación clínica creada y vinculada"


def confirm_state_transition_proposal(patient_id, proposal_id, confirmed_by="system"):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            '''
            SELECT * FROM state_transition_proposals
            WHERE id = ? AND patient_id = ? AND proposal_status = 'open'
            ''',
            (proposal_id, patient_id),
        )
        proposal = c.fetchone()
        if not proposal:
            conn.close()
            return False, "Propuesta no encontrada o ya resuelta"
        proposal = dict(proposal)
        proposal["trigger_signals"] = _parse_json_blob(proposal.get("trigger_signals_json"), [])
        proposal["next_actions"] = _parse_json_blob(proposal.get("next_actions_json"), [])
        proposal["evidence_basis"] = _parse_json_blob(proposal.get("evidence_basis_json"), [])
        conn.close()

        assessment_id, message = _confirm_transition_assessment(patient_id, proposal)
        if assessment_id is None:
            return False, message

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE state_transition_proposals
            SET proposal_status = 'confirmed',
                confirmation_status = 'confirmed',
                resulting_assessment_id = ?,
                confirmed_at = CURRENT_TIMESTAMP,
                confirmed_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (assessment_id, confirmed_by, proposal_id, patient_id),
        )
        conn.commit()
        conn.close()

        event_id = record_patient_event(
            patient_id,
            event_type="state_transition_confirmed",
            state_context=proposal.get("target_state"),
            management_track=proposal.get("target_management_track") or "",
            source_type="transition_proposal",
            source_record_id=proposal_id,
            payload={"proposal_key": proposal.get("proposal_key"), "resulting_assessment_id": assessment_id},
            mcode_focus={"condition": proposal.get("target_state")},
        )
        bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        record = get_patient_full_record(patient_id)
        agenda = refresh_followup_agenda(record)
        return True, {"assessment_id": assessment_id, "agenda": agenda, **bundle}
    except Exception as e:
        logger.error(f"Error confirming transition proposal: {e}")
        return False, str(e)


def resolve_state_transition_proposal(
    patient_id,
    proposal_id,
    *,
    confirmation_status="confirmed",
    confirmed_by="system",
    rejection_reason="",
    requires_more_data_fields=None,
):
    status = str(confirmation_status or "pending").strip().lower()
    if status == "confirmed":
        return confirm_state_transition_proposal(patient_id, proposal_id, confirmed_by=confirmed_by)
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT * FROM state_transition_proposals
            WHERE id = ? AND patient_id = ?
            """,
            (proposal_id, patient_id),
        )
        proposal = c.fetchone()
        if not proposal:
            conn.close()
            return False, "Propuesta no encontrada"
        proposal = dict(proposal)
        proposal_status = "rejected" if status == "rejected" else "deferred"
        c.execute(
            """
            UPDATE state_transition_proposals
            SET proposal_status = ?,
                confirmation_status = ?,
                rejection_reason = ?,
                requires_more_data_fields_json = ?,
                confirmed_at = CURRENT_TIMESTAMP,
                confirmed_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            """,
            (
                proposal_status,
                status,
                rejection_reason,
                _json_blob(list(requires_more_data_fields or [])),
                confirmed_by,
                proposal_id,
                patient_id,
            ),
        )
        conn.commit()
        conn.close()
        event_id = record_patient_event(
            patient_id,
            event_type="state_transition_reviewed",
            state_context=proposal.get("target_state"),
            management_track=proposal.get("target_management_track") or "",
            source_type="transition_proposal",
            source_record_id=proposal_id,
            payload={
                "proposal_key": proposal.get("proposal_key"),
                "confirmation_status": status,
                "rejection_reason": rejection_reason,
                "requires_more_data_fields": list(requires_more_data_fields or []),
            },
            mcode_focus={"condition": proposal.get("target_state")},
        )
        bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        return True, bundle
    except Exception as e:
        logger.error(f"Error resolving transition proposal: {e}")
        return False, str(e)


def save_clinical_decision_capture(patient_id, data):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO clinical_decision_captures (
                patient_id, assessment_id, event_id, state_at_decision, recommended_option,
                recommended_family, recommended_confidence, clinician_selected_option,
                clinician_selected_family, followed_system_recommendation,
                discordance_reason_category, discordance_reason_free_text,
                patient_preference_driver, cost_access_driver, toxicity_driver,
                tumor_board_required, shared_with_patient, decided_by, decision_finalized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                data.get("assessment_id"),
                data.get("event_id"),
                data.get("state_at_decision"),
                data.get("recommended_option"),
                data.get("recommended_family"),
                data.get("recommended_confidence"),
                data.get("clinician_selected_option"),
                data.get("clinician_selected_family"),
                data.get("followed_system_recommendation"),
                data.get("discordance_reason_category"),
                data.get("discordance_reason_free_text"),
                data.get("patient_preference_driver"),
                data.get("cost_access_driver"),
                data.get("toxicity_driver"),
                1 if safe_bool(data.get("tumor_board_required"), default=False) else 0,
                1 if safe_bool(data.get("shared_with_patient"), default=False) else 0,
                data.get("decided_by") or "system",
                data.get("decision_finalized_at") or datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()
        event_id = record_patient_event(
            patient_id,
            event_type="clinical_decision_captured",
            event_date=str(data.get("decision_finalized_at") or datetime.now().strftime("%Y-%m-%d"))[:10],
            state_context=data.get("state_at_decision") or (get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_type="clinical_decision_capture",
            payload=dict(data),
            mcode_focus={"decision_capture": True},
        )
        bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        return True, bundle
    except Exception as e:
        logger.error(f"Error saving clinical decision capture: {e}")
        return False, str(e)


def save_tumor_board_outcome(patient_id, data):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO tumor_board_outcomes (
                patient_id, assessment_id, discussion_date, trigger_reason,
                system_recommendation_at_board, board_recommendation,
                board_recommendation_family, board_consensus_level,
                board_reasoning_structured, required_followup_actions_json,
                board_overrode_system
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                data.get("assessment_id"),
                data.get("discussion_date") or datetime.now().strftime("%Y-%m-%d"),
                data.get("trigger_reason"),
                data.get("system_recommendation_at_board"),
                data.get("board_recommendation"),
                data.get("board_recommendation_family"),
                data.get("board_consensus_level"),
                data.get("board_reasoning_structured"),
                _json_blob(list(data.get("required_followup_actions") or [])),
                data.get("board_overrode_system"),
            ),
        )
        conn.commit()
        conn.close()
        event_id = record_patient_event(
            patient_id,
            event_type="tumor_board_outcome_recorded",
            event_date=data.get("discussion_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context=(get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_type="tumor_board",
            payload=dict(data),
            mcode_focus={"tumor_board": True},
        )
        bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        return True, bundle
    except Exception as e:
        logger.error(f"Error saving tumor board outcome: {e}")
        return False, str(e)


def complete_followup_agenda_item(patient_id, agenda_id, visit_record_id=None):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT agenda_key, item_type, due_at FROM followup_agenda_items WHERE id = ? AND patient_id = ?",
            (agenda_id, patient_id),
        )
        agenda_row = c.fetchone()
        c.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                visit_record_id = COALESCE(?, visit_record_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (visit_record_id, agenda_id, patient_id),
        )
        updated = c.rowcount
        if updated and agenda_row:
            if agenda_row[0]:
                c.execute(
                    '''
                    UPDATE scheduled_events
                    SET completed = 1,
                        completed_date = DATE('now'),
                        completed_visit_id = COALESCE(?, completed_visit_id)
                    WHERE patient_id = ?
                      AND schedule_key = ?
                    ''',
                    (visit_record_id, patient_id, agenda_row[0]),
                )
        conn.commit()
        conn.close()
        return updated > 0
    except Exception as e:
        logger.error(f"Error completing agenda item: {e}")
        return False


def _coerce_document_value(value):
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return ""
        if text.startswith("[") or text.startswith("{"):
            try:
                return json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return text
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return text
    return value


def _load_source_document(patient_id, document_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM source_documents WHERE id = ? AND patient_id = ?",
        (document_id, patient_id),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
    return item


def _replace_document_candidates(cursor, patient_id, document_id, candidates):
    cursor.execute("DELETE FROM document_extraction_candidates WHERE document_id = ?", (document_id,))
    for candidate in candidates:
        cursor.execute(
            '''
            INSERT INTO document_extraction_candidates (
                patient_id, document_id, candidate_key, field_name, fact_group, target_result_type,
                value_json, value_display, confidence, status, extraction_method, evidence_excerpt,
                page_ref, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''',
            (
                patient_id,
                document_id,
                candidate.get("candidate_key"),
                candidate.get("field_name"),
                candidate.get("fact_group"),
                candidate.get("target_result_type"),
                _json_blob(candidate.get("value")),
                candidate.get("value_display"),
                candidate.get("confidence", 0),
                candidate.get("status", "draft"),
                candidate.get("extraction_method"),
                candidate.get("evidence_excerpt"),
                candidate.get("page_ref"),
            ),
        )


def _upsert_document_verification_task(cursor, patient_id, document_id, task_payload, verified_by=""):
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if task_payload.get("task_status") == "verified" else None
    cursor.execute(
        '''
        INSERT INTO document_verification_tasks (
            patient_id, document_id, task_key, task_status, assigned_to, verified_by,
            verified_at, summary_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(document_id) DO UPDATE SET
            task_key=excluded.task_key,
            task_status=excluded.task_status,
            assigned_to=excluded.assigned_to,
            verified_by=excluded.verified_by,
            verified_at=excluded.verified_at,
            summary_json=excluded.summary_json,
            updated_at=CURRENT_TIMESTAMP
        ''',
        (
            patient_id,
            document_id,
            task_payload.get("task_key"),
            task_payload.get("task_status", "open"),
            task_payload.get("assigned_to", ""),
            verified_by or task_payload.get("verified_by", ""),
            verified_at or task_payload.get("verified_at"),
            _json_blob(task_payload.get("summary", {})),
        ),
    )
    cursor.execute("SELECT id FROM document_verification_tasks WHERE document_id = ?", (document_id,))
    task_row = cursor.fetchone()
    return task_row[0] if task_row else None


def _replace_verified_document_facts(cursor, patient_id, document_id, task_id, facts, verified_by):
    cursor.execute("DELETE FROM verified_document_facts WHERE document_id = ?", (document_id,))
    for fact in facts:
        cursor.execute(
            '''
            INSERT INTO verified_document_facts (
                patient_id, document_id, task_id, fact_key, field_name, fact_group, target_result_type,
                value_json, value_display, source_date, status, correction_note, verified_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''',
            (
                patient_id,
                document_id,
                task_id,
                fact.get("fact_key") or f"{fact.get('fact_group', '')}:{fact.get('field_name', '')}",
                fact.get("field_name"),
                fact.get("fact_group"),
                fact.get("target_result_type"),
                _json_blob(fact.get("value")),
                fact.get("value_display"),
                fact.get("source_date"),
                fact.get("status", "verified"),
                fact.get("correction_note", ""),
                verified_by,
            ),
        )


def _serialize_document_bundle(patient_id, document_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM source_documents WHERE id = ? AND patient_id = ?", (document_id, patient_id))
    document_rows = _hydrate_source_document_rows(c.fetchall())
    c.execute("SELECT * FROM document_extraction_candidates WHERE document_id = ? ORDER BY id ASC", (document_id,))
    candidates = _hydrate_document_candidate_rows(c.fetchall())
    c.execute("SELECT * FROM document_verification_tasks WHERE document_id = ?", (document_id,))
    tasks = _hydrate_document_task_rows(c.fetchall())
    c.execute("SELECT * FROM verified_document_facts WHERE document_id = ? ORDER BY id ASC", (document_id,))
    verified_facts = _hydrate_verified_fact_rows(c.fetchall())
    conn.close()
    document = document_rows[0] if document_rows else None
    if not document:
        return None
    preview_excerpt = _document_store().build_preview(document.get("private_index_path", ""))
    from prostanet.domains.patient_tracking.document_ingestion import get_manual_template

    return {
        "document": document,
        "candidates": candidates,
        "verification_task": tasks[0] if tasks else {},
        "verified_facts": verified_facts,
        "preview_excerpt": preview_excerpt,
        "manual_template": get_manual_template(document.get("document_type", "")),
    }


def save_source_document(patient_id, file_storage, data):
    from prostanet.domains.patient_tracking.document_ingestion import classify_document

    try:
        patient_id = int(patient_id)
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"
        if not file_storage or not getattr(file_storage, "filename", ""):
            return False, "Se requiere un archivo clínico"

        file_name = os.path.basename(file_storage.filename)
        content = file_storage.read()
        if not content:
            return False, "El archivo clínico está vacío"

        stored = _document_store().store_upload(
            patient_id=patient_id,
            file_name=file_name,
            content=content,
            mime_type=getattr(file_storage, "mimetype", "") or "",
        )
        private_payload = _document_store().get_private_payload(stored["private_index_path"])
        classification = classify_document(
            file_name=file_name,
            private_payload=private_payload,
            declared_type=str(data.get("document_type") or "auto"),
        )

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id FROM source_documents WHERE patient_id = ? AND sha256 = ?",
            (patient_id, stored["sha256"]),
        )
        existing = c.fetchone()
        if existing:
            document_id = existing["id"]
            c.execute(
                '''
                UPDATE source_documents
                SET document_type = ?, title = ?, file_name = ?, mime_type = ?, storage_path = ?,
                    private_index_path = ?, source_date = ?, classification_status = ?, preview_excerpt = ?,
                    page_count = ?, metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND patient_id = ?
                ''',
                (
                    classification.get("document_type"),
                    data.get("title") or file_name,
                    file_name,
                    stored["mime_type"],
                    stored["storage_path"],
                    stored["private_index_path"],
                    data.get("source_date"),
                    classification.get("classification_status"),
                    stored.get("preview_excerpt", ""),
                    stored.get("page_count", 0),
                    _json_blob(stored.get("metadata", {})),
                    document_id,
                    patient_id,
                ),
            )
        else:
            c.execute(
                '''
                INSERT INTO source_documents (
                    patient_id, document_key, document_type, title, file_name, mime_type, sha256,
                    storage_path, private_index_path, source_date, classification_status,
                    extraction_status, verification_status, uploaded_by, preview_excerpt, page_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    patient_id,
                    stored["document_key"],
                    classification.get("document_type"),
                    data.get("title") or file_name,
                    file_name,
                    stored["mime_type"],
                    stored["sha256"],
                    stored["storage_path"],
                    stored["private_index_path"],
                    data.get("source_date"),
                    classification.get("classification_status"),
                    "pending",
                    "draft",
                    data.get("uploaded_by", "clinico"),
                    stored.get("preview_excerpt", ""),
                    stored.get("page_count", 0),
                    _json_blob(stored.get("metadata", {})),
                ),
            )
            document_id = c.lastrowid
        conn.commit()
        conn.close()

        record_patient_event(
            patient_id,
            event_type="document_attached",
            event_date=data.get("source_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context=(get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_type="source_document",
            source_record_id=document_id,
            payload={"document_type": classification.get("document_type"), "title": data.get("title") or file_name},
            mcode_focus={"document_type": classification.get("document_type")},
        )
        return True, {"document": _serialize_document_bundle(patient_id, document_id)["document"]}
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        logger.error(f"Error saving source document: {e}")
        return False, str(e)


def list_source_documents(nss_or_id):
    record = get_patient_full_record(nss_or_id)
    if not record:
        return None
    return record.get("source_documents", [])


def extract_source_document(patient_id, document_id, document_type=""):
    from prostanet.domains.patient_tracking.document_ingestion import (
        build_verification_task,
        classify_document,
        extract_candidates_for_document,
    )

    try:
        patient_id = int(patient_id)
        document = _load_source_document(patient_id, document_id)
        if not document:
            return False, "Documento no encontrado"

        private_payload = _document_store().get_private_payload(document.get("private_index_path", ""))
        classification = classify_document(
            file_name=document.get("file_name", ""),
            private_payload=private_payload,
            declared_type=document_type or document.get("document_type", ""),
        )
        candidates = extract_candidates_for_document(
            document_type=classification.get("document_type"),
            file_name=document.get("file_name", ""),
            private_payload=private_payload,
        )
        task = build_verification_task(document_key=document.get("document_key", ""), candidates=candidates)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE source_documents
            SET document_type = ?, classification_status = ?, extraction_status = ?,
                preview_excerpt = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (
                classification.get("document_type"),
                classification.get("classification_status"),
                "extracted" if candidates else "needs_manual_review",
                private_payload.get("preview_excerpt", "")[:1800],
                document_id,
                patient_id,
            ),
        )
        _replace_document_candidates(c, patient_id, document_id, candidates)
        _upsert_document_verification_task(c, patient_id, document_id, task)
        conn.commit()
        conn.close()
        return True, _serialize_document_bundle(patient_id, document_id)
    except Exception as e:
        logger.error(f"Error extracting source document: {e}")
        return False, str(e)


def get_document_facts(patient_id, document_id):
    try:
        patient_id = int(patient_id)
        bundle = _serialize_document_bundle(patient_id, document_id)
        if not bundle:
            return None
        return bundle
    except Exception as e:
        logger.error(f"Error fetching document facts: {e}")
        return None


def _voice_crypto():
    from prostanet.voice.encryption import get_voice_crypto

    return get_voice_crypto(testing=bool(os.environ.get("PYTEST_CURRENT_TEST")), db_path=DB_PATH)


def _ensure_voice_consent_version(cursor):
    from prostanet.voice.consent import VOICE_CONSENT_TEXT, VOICE_CONSENT_TITLE, VOICE_CONSENT_VERSION

    cursor.execute(
        """
        INSERT INTO consent_versions (version_code, title, consent_text, html_snapshot, effective_at, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(version_code) DO UPDATE SET
            title=excluded.title,
            consent_text=excluded.consent_text,
            html_snapshot=excluded.html_snapshot,
            active=1
        """,
        (
            VOICE_CONSENT_VERSION,
            VOICE_CONSENT_TITLE,
            VOICE_CONSENT_TEXT,
            VOICE_CONSENT_TEXT.replace("\n", "<br>"),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return VOICE_CONSENT_VERSION


def _load_voice_session(cursor, patient_id, session_key):
    cursor.execute(
        "SELECT * FROM voice_encounter_sessions WHERE patient_id = ? AND session_key = ?",
        (patient_id, str(session_key or "").strip()),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _voice_transcript_text(session_id):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM voice_transcript_segments
        WHERE session_id = ?
        ORDER BY segment_index ASC, id ASC
        """,
        (int(session_id),),
    )
    rows = _hydrate_voice_segment_rows(cursor.fetchall())
    conn.close()
    crypto = _voice_crypto()
    texts = []
    for row in rows:
        try:
            texts.append(crypto.decrypt_text(row.get("transcript_envelope")))
        except Exception:
            texts.append("")
    return "\n".join(text for text in texts if text).strip()


def _serialize_voice_session_bundle(patient_id, session_key):
    conn = _connect()
    cursor = conn.cursor()
    session = _load_voice_session(cursor, patient_id, session_key)
    if not session:
        conn.close()
        return None
    session_id = int(session["id"])
    session_payload = _hydrate_voice_session_rows([session])[0]
    cursor.execute(
        """
        SELECT * FROM voice_transcript_segments
        WHERE session_id = ?
        ORDER BY segment_index ASC, id ASC
        """,
        (session_id,),
    )
    segment_rows = _hydrate_voice_segment_rows(cursor.fetchall())
    transcript_text = ""
    try:
        crypto = _voice_crypto()
        transcript_text = "\n".join(
            crypto.decrypt_text(row.get("transcript_envelope")) for row in segment_rows
        ).strip()
    except Exception:
        transcript_text = ""

    candidates = []
    document = None
    if session_payload.get("source_document_id"):
        document_bundle = _serialize_document_bundle(patient_id, int(session_payload["source_document_id"]))
        if document_bundle:
            document = document_bundle.get("document")
            candidates = document_bundle.get("candidates") or []
    conn.close()
    return {
        "session": session_payload,
        "transcript": {
            "text": transcript_text,
            "segment_count": len(segment_rows),
            "sha256": session_payload.get("transcript_hash") or hashlib.sha256(transcript_text.encode("utf-8")).hexdigest() if transcript_text else "",
        },
        "source_document": document,
        "candidates": candidates,
        "audit_note": "Voice Clinical OS · transcript is untrusted until clinician review",
    }


def _ensure_voice_source_document(cursor, patient_id, session, transcript_text):
    session_key = session["session_key"]
    document_key = f"voice:{session_key}"
    sha = hashlib.sha256(str(transcript_text or "").encode("utf-8")).hexdigest()
    title = f"Cortana clínica · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    metadata = {
        "voice_session_key": session_key,
        "source": "voice_clinical_os",
        "transcript_hash": sha,
        "local_first": True,
        "human_review_required": True,
    }
    cursor.execute(
        "SELECT id FROM source_documents WHERE patient_id = ? AND document_key = ?",
        (patient_id, document_key),
    )
    row = cursor.fetchone()
    if row:
        document_id = row["id"]
        cursor.execute(
            """
            UPDATE source_documents
            SET sha256 = ?, title = ?, preview_excerpt = ?, extraction_status = ?,
                verification_status = CASE WHEN verification_status = 'verified' THEN verification_status ELSE 'draft' END,
                metadata_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            """,
            (
                sha,
                title,
                str(transcript_text or "")[:1800],
                "extracted",
                _json_blob(metadata),
                document_id,
                patient_id,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO source_documents (
                patient_id, document_key, document_type, title, file_name, mime_type, sha256,
                storage_path, private_index_path, source_date, classification_status,
                extraction_status, verification_status, uploaded_by, preview_excerpt, page_count, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                document_key,
                "voice_encounter",
                title,
                f"{session_key}.voice",
                "text/plain+voice-transcript",
                sha,
                "",
                "",
                datetime.now().strftime("%Y-%m-%d"),
                "voice_transcript",
                "extracted",
                "draft",
                session.get("created_by") or "clinico",
                str(transcript_text or "")[:1800],
                1,
                _json_blob(metadata),
            ),
        )
        document_id = cursor.lastrowid
    cursor.execute(
        "UPDATE voice_encounter_sessions SET source_document_id = ?, transcript_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (document_id, sha, session["id"]),
    )
    return document_id


def create_voice_encounter_session(nss_or_id, data=None):
    data = dict(data or {})
    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session_key = str(data.get("session_key") or f"voice-{uuid.uuid4().hex[:18]}")
        cursor.execute(
            """
            INSERT INTO voice_encounter_sessions (
                patient_id, session_key, status, consent_status, retention_policy, stt_provider,
                extractor_version, session_context_json, created_by, metadata_json
            ) VALUES (?, ?, 'created', 'missing', ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                session_key,
                data.get("retention_policy") or "delete_audio_after_review",
                data.get("stt_provider") or "local-first:faster-whisper",
                "voice-deterministic-v1.0",
                _json_blob(data.get("context") or {}),
                data.get("created_by") or "clinico",
                _json_blob({"ui_surface": data.get("ui_surface") or "patient_profile_v2", "local_first": True}),
            ),
        )
        session_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    record_patient_event(
        patient_id,
        event_type="voice_encounter_created",
        source_type="voice_clinical_os",
        source_record_id=session_id,
        status="created",
        payload={"session_key": session_key, "local_first": True},
    )
    return True, _serialize_voice_session_bundle(patient_id, session_key)


def get_voice_encounter_session(nss_or_id, session_key):
    resolved = resolve_patient_ref(nss_or_id)
    if not resolved:
        return None
    return _serialize_voice_session_bundle(resolved["patient_id"], session_key)


def record_voice_consent(nss_or_id, session_key, data=None):
    from prostanet.voice.consent import (
        VOICE_CONSENT_TEXT,
        build_consent_metadata,
        build_voice_consent_hash,
        is_affirmative_verbal_consent,
        now_iso,
    )

    data = dict(data or {})
    spoken_text = str(data.get("spoken_text") or "").strip()
    if not is_affirmative_verbal_consent(spoken_text):
        return False, "verbal_consent_not_affirmative"
    signed_at = data.get("signed_at") or now_iso()
    signer_name = data.get("signer_name") or "Consentimiento verbal"

    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session = _load_voice_session(cursor, patient_id, session_key)
        if not session:
            return False, "voice_session_not_found"
        version_code = _ensure_voice_consent_version(cursor)
        content_hash = build_voice_consent_hash(
            patient_ref=str(identity["nss"]),
            session_key=str(session_key),
            spoken_text=spoken_text,
            signed_at=signed_at,
        )
        cursor.execute(
            """
            INSERT INTO patient_consents (
                patient_id, consent_version_code, status, signer_name, signed_at, content_hash
            ) VALUES (?, ?, 'signed', ?, ?, ?)
            """,
            (patient_id, version_code, signer_name, signed_at, content_hash),
        )
        consent_id = cursor.lastrowid
        metadata = build_consent_metadata(
            patient_ref=str(identity["nss"]),
            session_key=str(session_key),
            spoken_text=spoken_text,
            signed_at=signed_at,
        )
        cursor.execute(
            """
            INSERT INTO consent_signature_evidence (
                patient_id, consent_id, signature_data_url, evidence_html, audit_metadata_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                consent_id,
                "",
                f"<p>{VOICE_CONSENT_TEXT}</p><p>Consentimiento verbal registrado {signed_at}</p>",
                _json_blob(metadata),
            ),
        )
        cursor.execute(
            """
            UPDATE voice_encounter_sessions
            SET consent_status = 'signed', consent_id = ?, status = 'consented',
                signed_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (consent_id, signed_at, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    record_patient_event(
        patient_id,
        event_type="voice_consent_signed",
        event_date=signed_at[:10],
        source_type="voice_clinical_os",
        source_record_id=session["id"],
        status="signed",
        payload={"session_key": session_key, "consent_id": consent_id, "content_hash": content_hash},
    )
    return True, {"consent_id": consent_id, "content_hash": content_hash, **_serialize_voice_session_bundle(patient_id, session_key)}


def _append_voice_transcript_segment(cursor, patient_id, session, text, *, confidence=1.0, stt_provider="text-review"):
    text = str(text or "").strip()
    if not text:
        return None
    cursor.execute("SELECT COALESCE(MAX(segment_index), -1) + 1 FROM voice_transcript_segments WHERE session_id = ?", (session["id"],))
    segment_index = int(cursor.fetchone()[0] or 0)
    aad = f"voice:{session['session_key']}:{segment_index}"
    envelope = _voice_crypto().encrypt_text(text, aad=aad)
    cursor.execute(
        """
        INSERT INTO voice_transcript_segments (
            session_id, patient_id, segment_index, start_ms, end_ms, transcript_envelope_json,
            transcript_sha256, confidence, stt_provider, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["id"],
            patient_id,
            segment_index,
            0,
            max(len(text) * 40, 800),
            _json_blob(envelope),
            envelope["sha256"],
            confidence,
            stt_provider,
            _json_blob({"source": "voice_review_payload", "encrypted": True}),
        ),
    )
    return cursor.lastrowid


def _voice_audio_suffix(mime_type="", file_name=""):
    suffix = Path(str(file_name or "")).suffix.lower()
    if suffix in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".opus"}:
        return suffix
    mime = str(mime_type or "").lower()
    if "wav" in mime:
        return ".wav"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "ogg" in mime:
        return ".ogg"
    if "opus" in mime:
        return ".opus"
    if "mp4" in mime or "m4a" in mime:
        return ".m4a"
    return ".webm"


def _voice_audio_store_path(patient_id, session_key, audio_sha):
    root = Path(DB_PATH).resolve().parent / ".prostanet_private" / "voice_audio" / f"patient_{int(patient_id)}"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{session_key}-{str(audio_sha)[:16]}.json"


def store_voice_audio_chunk(nss_or_id, session_key, audio_bytes, *, mime_type="", file_name="", transcribe=True):
    """Store raw voice audio encrypted, then optionally transcribe locally.

    No cloud fallback exists here. If faster-whisper is not installed, the audio
    is still encrypted and retained temporarily for later local transcription,
    but no clinical candidates are generated.
    """

    if not audio_bytes:
        return False, "audio_required"
    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session = _load_voice_session(cursor, patient_id, session_key)
        if not session:
            return False, "voice_session_not_found"
        if session.get("consent_status") != "signed":
            return False, "voice_consent_required"
        if session.get("status") in {"signed", "discarded"}:
            return False, f"voice_session_already_{session.get('status')}"

        audio_sha = hashlib.sha256(audio_bytes).hexdigest()
        aad = f"voice-audio:{session_key}:{audio_sha}"
        envelope = _voice_crypto().encrypt_bytes(audio_bytes, aad=aad)
        encrypted_path = _voice_audio_store_path(patient_id, session_key, audio_sha)
        encrypted_path.write_text(
            _json_blob(
                {
                    "envelope": envelope,
                    "mime_type": mime_type or "audio/webm",
                    "file_name": file_name or "voice.webm",
                    "session_key": session_key,
                    "patient_id": patient_id,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "retention_policy": session.get("retention_policy") or "delete_audio_after_review",
                    "local_first": True,
                }
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(encrypted_path, 0o600)
        except OSError:
            pass
        cursor.execute(
            """
            UPDATE voice_encounter_sessions
            SET status = ?, audio_sha256 = ?, encrypted_audio_path = ?,
                metadata_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "audio_received",
                audio_sha,
                str(encrypted_path),
                _json_blob({
                    "mime_type": mime_type or "audio/webm",
                    "file_name": file_name or "voice.webm",
                    "audio_bytes": len(audio_bytes),
                    "audio_encrypted": True,
                    "local_first": True,
                }),
                session["id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    record_patient_event(
        patient_id,
        event_type="voice_audio_received",
        source_type="voice_clinical_os",
        source_record_id=session["id"],
        status="encrypted",
        payload={
            "session_key": session_key,
            "audio_sha256": audio_sha,
            "mime_type": mime_type or "audio/webm",
            "audio_bytes": len(audio_bytes),
            "transcribe_requested": bool(transcribe),
        },
    )

    if not transcribe:
        bundle = _serialize_voice_session_bundle(patient_id, session_key) or {}
        return True, {
            **bundle,
            "audio": {"stored": True, "encrypted": True, "sha256": audio_sha, "transcription_status": "not_requested"},
        }

    from prostanet.voice.stt_engine import LocalSTTEngine

    stt = LocalSTTEngine()
    if not stt.is_available():
        # EPIC 24d — granular transcription_status so the UI can show a
        # specific blocker (sidecar_not_found vs disabled vs other) instead
        # of the generic "audio cifrado · STT local pendiente" microcopy.
        diag = stt.diagnose()
        if diag.get("stt_disable_env"):
            granular = "requires_local_stt_disabled"
        elif diag.get("blockers"):
            blockers_blob = " ".join(diag["blockers"]).lower()
            if "sidecar venv no encontrado" in blockers_blob:
                granular = "requires_local_stt_sidecar_not_found"
            else:
                granular = "requires_local_stt_other"
        else:
            granular = "requires_local_stt"
        bundle = _serialize_voice_session_bundle(patient_id, session_key) or {}
        return True, {
            **bundle,
            "audio": {
                "stored": True,
                "encrypted": True,
                "sha256": audio_sha,
                # Legacy key preserved for backward-compat (older UI still
                # branches on "requires_local_stt").
                "transcription_status": granular,
                "transcription_status_legacy": "requires_local_stt",
                "local_stt_available": False,
                "stt_diagnose": {
                    "mode": diag.get("mode"),
                    "blockers": diag.get("blockers", []),
                    "next_steps": diag.get("next_steps", []),
                },
            },
        }

    try:
        segments = stt.transcribe_bytes(
            audio_bytes,
            suffix=_voice_audio_suffix(mime_type=mime_type, file_name=file_name),
            language="es",
        )
        transcript_text = " ".join(segment.text for segment in segments if segment.text).strip()
    except Exception as exc:
        bundle = _serialize_voice_session_bundle(patient_id, session_key) or {}
        return True, {
            **bundle,
            "audio": {
                "stored": True,
                "encrypted": True,
                "sha256": audio_sha,
                "transcription_status": "stt_error",
                "stt_error": type(exc).__name__,
            },
        }

    if not transcript_text:
        bundle = _serialize_voice_session_bundle(patient_id, session_key) or {}
        return True, {
            **bundle,
            "audio": {"stored": True, "encrypted": True, "sha256": audio_sha, "transcription_status": "empty_transcript"},
        }
    ok, result = review_voice_encounter(
        nss_or_id,
        session_key,
        {"transcript_text": transcript_text, "audio_sha256": audio_sha},
    )
    if not ok:
        return False, result
    result["audio"] = {
        "stored": True,
        "encrypted": True,
        "sha256": audio_sha,
        "transcription_status": "transcribed",
        "local_stt_available": True,
    }
    return True, result


def review_voice_encounter(nss_or_id, session_key, data=None):
    from prostanet.voice.intent_extractor import extract_voice_candidates

    data = dict(data or {})
    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session = _load_voice_session(cursor, patient_id, session_key)
        if not session:
            return False, "voice_session_not_found"
        if session.get("consent_status") != "signed":
            return False, "voice_consent_required"
        transcript_text = str(data.get("transcript_text") or "").strip()
        if transcript_text:
            _append_voice_transcript_segment(cursor, patient_id, session, transcript_text, confidence=1.0)
            conn.commit()
            session = _load_voice_session(cursor, patient_id, session_key)
        else:
            transcript_text = _voice_transcript_text(session["id"])
        if not transcript_text:
            return False, "transcript_required"

        document_id = _ensure_voice_source_document(cursor, patient_id, session, transcript_text)
        record = get_patient_full_record(patient_id) or {}
        state = ((record.get("latest_assessment") or {}).get("state") or (record.get("prior_history") or {}).get("current_state") or "diagnostic_workup")
        field_specs = []
        try:
            from prostanet.presentation.clinical_field_router import build_clinical_field_router

            router = build_clinical_field_router(state, phase="longitudinal_followup")
            for group in (router.get("group_order") or []):
                field_specs.extend(group.get("fields") or [])
        except Exception:
            field_specs = []
        candidates = extract_voice_candidates(
            transcript_text,
            session_key=str(session_key),
            patient=record,
            field_specs=field_specs,
        )
        _replace_document_candidates(cursor, patient_id, document_id, candidates)

        reviewed = data.get("reviewed_candidates") or []
        if reviewed:
            for item in reviewed:
                status = "accepted" if item.get("accepted") else "rejected"
                cursor.execute(
                    """
                    UPDATE document_extraction_candidates
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE patient_id = ? AND document_id = ? AND candidate_key = ?
                    """,
                    (status, patient_id, document_id, item.get("candidate_key")),
                )
        cursor.execute(
            """
            UPDATE voice_encounter_sessions
            SET status = 'review_pending', review_payload_json = ?, source_document_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (_json_blob({"candidate_count": len(candidates), "reviewed_count": len(reviewed)}), document_id, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    record_patient_event(
        patient_id,
        event_type="voice_transcript_reviewed",
        source_type="voice_clinical_os",
        source_record_id=session["id"],
        status="review_pending",
        payload={"session_key": session_key, "candidate_count": len(candidates)},
    )
    return True, _serialize_voice_session_bundle(patient_id, session_key)


def _candidate_to_verified_fact(candidate, verified_by, source_date):
    value = candidate.get("value")
    return {
        "fact_key": candidate.get("candidate_key"),
        "field_name": candidate.get("field_name"),
        "fact_group": candidate.get("fact_group"),
        "target_result_type": candidate.get("target_result_type"),
        "value": value,
        "value_display": candidate.get("value_display"),
        "source_date": source_date,
        "status": "verified",
        "correction_note": "",
        "verified_by": verified_by,
    }


def _record_voice_provenance(cursor, patient_id, document_key, state, source_date, facts, verified_by):
    for fact in facts:
        field_name = fact.get("field_name")
        if not field_name or not _is_present(fact.get("value")):
            continue
        cursor.execute(
            """
            INSERT INTO data_provenance (
                patient_id, visit_record_id, field_name, value_json, source_type, source_document_id,
                source_date, verified_by, entered_manually, stage_context
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                field_name,
                _json_blob(fact.get("value")),
                "voice_encounter",
                document_key,
                source_date,
                verified_by,
                0,
                state,
            ),
        )


def commit_voice_encounter(nss_or_id, session_key, data=None):
    data = dict(data or {})
    verified_by = data.get("verified_by") or "clinico"
    accepted_keys = {str(key) for key in (data.get("accepted_candidate_keys") or []) if str(key).strip()}
    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session = _load_voice_session(cursor, patient_id, session_key)
        if not session:
            return False, "voice_session_not_found"
        if session.get("consent_status") != "signed":
            return False, "voice_consent_required"
        if session.get("status") in {"signed", "discarded"}:
            return False, f"voice_session_already_{session.get('status')}"
        document_id = session.get("source_document_id")
        if not document_id:
            return False, "voice_review_required"
        cursor.execute("SELECT * FROM source_documents WHERE id = ? AND patient_id = ?", (document_id, patient_id))
        document_row = cursor.fetchone()
        if not document_row:
            return False, "voice_source_document_missing"
        document = dict(document_row)
        cursor.execute(
            "SELECT * FROM document_extraction_candidates WHERE patient_id = ? AND document_id = ? ORDER BY id ASC",
            (patient_id, document_id),
        )
        candidates = _hydrate_document_candidate_rows(cursor.fetchall())
        selected = []
        for candidate in candidates:
            if accepted_keys and candidate.get("candidate_key") not in accepted_keys:
                continue
            if not accepted_keys and candidate.get("status") != "accepted":
                continue
            selected.append(candidate)
        if not selected:
            return False, "accepted_candidates_required"

        source_date = datetime.now().strftime("%Y-%m-%d")
        state = ((get_patient_full_record(patient_id) or {}).get("prior_history") or {}).get("current_state") or ""
        verified_facts = [_candidate_to_verified_fact(item, verified_by, source_date) for item in selected]
        task_id = _upsert_document_verification_task(
            cursor,
            patient_id,
            int(document_id),
            {
                "task_key": f"{document.get('document_key')}:voice-review",
                "task_status": "verified",
                "verified_by": verified_by,
                "summary": {"fact_count": len(verified_facts), "source": "voice_clinical_os"},
            },
            verified_by=verified_by,
        )
        _replace_verified_document_facts(cursor, patient_id, int(document_id), task_id, verified_facts, verified_by)
        _record_voice_provenance(cursor, patient_id, document.get("document_key"), state, source_date, verified_facts, verified_by)
        _persist_patient_clinical_facts(
            cursor,
            patient_id,
            [
                {
                    "fact_key": fact.get("fact_key"),
                    "value": fact.get("value"),
                    "source_type": "voice_encounter",
                    "source_record_type": "verified_voice_fact",
                    "source_record_id": document_id,
                    "source_date": fact.get("source_date") or source_date,
                    "observed_at": fact.get("source_date") or source_date,
                    "state_context": state,
                    "certainty_tier": "clinician_verified_voice",
                    "clinician_verified": True,
                    "verification_note": f"Voz revisada por {verified_by}",
                }
                for fact in verified_facts
                if fact.get("target_result_type") not in {"longitudinal_biomarker", "treatment_change"}
            ],
        )
        cursor.execute(
            """
            UPDATE document_extraction_candidates
            SET status = CASE WHEN candidate_key IN ({placeholders}) THEN 'accepted' ELSE 'rejected' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND document_id = ?
            """.format(placeholders=",".join(["?"] * len(selected))),
            [item["candidate_key"] for item in selected] + [patient_id, document_id],
        )
        cursor.execute(
            """
            UPDATE source_documents
            SET verification_status = 'verified', extraction_status = 'verified', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            """,
            (document_id, patient_id),
        )
        cursor.execute(
            """
            UPDATE voice_encounter_sessions
            SET status = 'signed', reviewed_by = ?, committed_by = ?, raw_audio_deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (verified_by, verified_by, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    write_results = []
    for candidate in selected:
        target = candidate.get("target_result_type")
        value = candidate.get("value") if isinstance(candidate.get("value"), dict) else {}
        if target == "longitudinal_biomarker":
            kind = value.get("kind") or candidate.get("field_name")
            biomarker_map = {
                "psa": "PSA",
                "testosterone": "TESTOSTERONA",
                "hb": "HEMOGLOBINA",
                "hemoglobin": "HEMOGLOBINA",
                "alp": "FOSFATASA_ALCALINA",
                "ldh": "LDH",
                "ecog": "ECOG_PERFORMANCE",
                "ctcae": "CTCAE_TOXICITY",
            }
            biomarker_type = biomarker_map.get(str(kind).lower())
            if biomarker_type:
                res = append_biomarker_longitudinal(
                    nss_or_id=nss_or_id,
                    biomarker_type=biomarker_type,
                    sample_date=value.get("date") or source_date,
                    value=value.get("value") if value.get("value") is not None else value.get("grade"),
                    unit=value.get("unit"),
                    context="voice_reviewed",
                    source="voice_clinical_os",
                    extra_data={"candidate_key": candidate.get("candidate_key"), "evidence_excerpt": candidate.get("evidence_excerpt")},
                )
                write_results.append({"candidate_key": candidate.get("candidate_key"), "target": target, **res})
        elif target == "treatment_change":
            res = append_treatment_line_update(nss_or_id, value)
            write_results.append({"candidate_key": candidate.get("candidate_key"), "target": target, **res})

    event_id = record_patient_event(
        patient_id,
        event_type="voice_encounter_committed",
        event_date=source_date,
        state_context=state,
        source_type="voice_clinical_os",
        source_record_id=session["id"],
        status="signed",
        payload={
            "session_key": session_key,
            "accepted_candidate_count": len(selected),
            "write_results": write_results,
            "raw_audio_deleted": True,
        },
        mcode_focus={"voice_reviewed_fields": [item.get("field_name") for item in selected]},
    )
    recompute = {}
    agenda = {}
    try:
        recompute = refresh_longitudinal_intelligence(nss_or_id, event_id=event_id, force_recompute=True)
        agenda = refresh_followup_agenda(get_patient_full_record(nss_or_id), longitudinal_bundle=recompute)
    except Exception as exc:
        recompute = {"success": False, "recompute_error": str(exc)}
    bundle = _serialize_voice_session_bundle(patient_id, session_key)
    return True, {
        **(bundle or {}),
        "write_results": write_results,
        "recompute": recompute,
        "agenda": agenda,
        "event_id": event_id,
        "audit_note": "Voice encounter committed after clinician review; raw audio marked deleted.",
    }


def discard_voice_encounter(nss_or_id, session_key, data=None):
    data = dict(data or {})
    conn = _connect(write=True)
    cursor = conn.cursor()
    try:
        identity = _resolve_identity_row(cursor, nss_or_id)
        if not identity:
            return False, "patient_not_found"
        patient_id = int(identity["id"])
        session = _load_voice_session(cursor, patient_id, session_key)
        if not session:
            return False, "voice_session_not_found"
        cursor.execute(
            """
            UPDATE voice_encounter_sessions
            SET status = 'discarded', discarded_by = ?, discarded_at = CURRENT_TIMESTAMP,
                raw_audio_deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (data.get("discarded_by") or "clinico", session["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    record_patient_event(
        patient_id,
        event_type="voice_encounter_discarded",
        source_type="voice_clinical_os",
        source_record_id=session["id"],
        status="discarded",
        payload={"session_key": session_key, "reason": data.get("reason") or ""},
    )
    return True, _serialize_voice_session_bundle(patient_id, session_key)


def _commit_verified_document(patient_id, document, facts, verified_by):
    from prostanet.domains.patient_tracking.document_ingestion import build_document_payload_from_facts

    result_type, payload = build_document_payload_from_facts(
        document_type=document.get("document_type", ""),
        facts=facts,
    )
    record = get_patient_full_record(patient_id) or {}
    state = (
        (record.get("latest_assessment") or {}).get("state")
        or (record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    management_track = (
        (record.get("latest_signal_snapshot") or {}).get("management_track")
        or (record.get("stage_visits") or [{}])[0].get("management_track", "")
    )
    if result_type in {"pathology", "imaging", "genomic"}:
        return save_structured_result(patient_id, {"result_type": result_type, "payload": payload}), [result_type]
    if result_type == "lab_panel":
        payload.update(
            {
                "state": state,
                "management_track": management_track,
                "visit_type": "document_result",
                "disease_status": "Resultado de laboratorio verificado",
                "clinician_notes": f"Resultado verificado desde documento {document.get('title') or document.get('file_name')}",
            }
        )
        return save_stage_visit_bundle(patient_id, payload), [result_type]
    if result_type == "surgery_summary":
        success = save_surgical_details(patient_id, payload)
        if not success:
            return (False, "No fue posible persistir el resumen quirúrgico"), []
        event_id = record_patient_event(
            patient_id,
            event_type="procedure_performed",
            event_date=payload.get("surgery_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context="post_prostatectomy",
            management_track="post_rp",
            source_type="source_document",
            source_record_id=document.get("id"),
            payload=payload,
            mcode_focus={"procedure": "surgery_summary"},
        )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = refresh_followup_agenda(get_patient_full_record(patient_id))
        return (True, {"event_id": event_id, "agenda": agenda, **intelligence}), [result_type]
    if result_type == "radiotherapy_summary":
        success = save_radiation_details(patient_id, payload)
        if not success:
            return (False, "No fue posible persistir el resumen de radioterapia"), []
        event_id = record_patient_event(
            patient_id,
            event_type="procedure_performed",
            event_date=payload.get("rt_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context=state,
            management_track="post_rt",
            source_type="source_document",
            source_record_id=document.get("id"),
            payload=payload,
            mcode_focus={"procedure": "radiotherapy_summary"},
        )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = refresh_followup_agenda(get_patient_full_record(patient_id))
        return (True, {"event_id": event_id, "agenda": agenda, **intelligence}), [result_type]
    return (False, "Tipo de documento no soportado para commit clínico"), []


def verify_source_document(patient_id, document_id, data):
    from prostanet.domains.patient_tracking.document_ingestion import build_verified_fact_bundle, serialize_verified_facts

    try:
        patient_id = int(patient_id)
        document = _load_source_document(patient_id, document_id)
        if not document:
            return False, "Documento no encontrado"
        verified_by = data.get("verified_by", "clinico")
        source_date = data.get("source_date") or document.get("source_date") or datetime.now().strftime("%Y-%m-%d")

        facts = []
        for item in data.get("facts", []):
            value = _coerce_document_value(item.get("value"))
            if not _is_present(value):
                continue
            value_display = item.get("value_display")
            if not value_display:
                value_display = _json_blob(value) if isinstance(value, (dict, list)) else str(value)
            facts.append(
                {
                    "fact_key": item.get("fact_key") or f"{item.get('fact_group', '')}:{item.get('field_name', '')}",
                    "field_name": item.get("field_name"),
                    "fact_group": item.get("fact_group"),
                    "target_result_type": item.get("target_result_type"),
                    "value": value,
                    "value_display": value_display,
                    "source_date": item.get("source_date") or source_date,
                    "status": item.get("status", "verified"),
                    "correction_note": item.get("correction_note", ""),
                    "verified_by": verified_by,
                }
            )
        if not facts:
            return False, "Se requiere al menos un fact verificado"

        serialized_facts = serialize_verified_facts(facts)
        commit_result, committed_types = _commit_verified_document(patient_id, document, serialized_facts, verified_by)
        if not commit_result[0]:
            return False, commit_result[1]

        bundle_summary = build_verified_fact_bundle(
            verified_by=verified_by,
            facts=serialized_facts,
            committed_result_types=committed_types,
        )
        impact_map = {
            "pathology": {
                "updated_panels": ["biopsies", "clinical_journey"],
                "updated_decisions": ["diagnostic_confirmation", "stage_assignment"],
            },
            "imaging": {
                "updated_panels": ["sequencing_context", "biomarker_context", "clinical_journey"],
                "updated_decisions": ["radiographic_restage", "psma_eligibility"],
            },
            "genomic": {
                "updated_panels": ["biomarker_context", "therapy_checkpoints", "evidence_applicability"],
                "updated_decisions": ["precision_pathway", "parp_eligibility"],
            },
            "lab_panel": {
                "updated_panels": ["psa_observability", "sequencing_context", "safety_support_context"],
                "updated_decisions": ["disease_control", "castration_status"],
            },
            "surgery_summary": {
                "updated_panels": ["clinical_journey", "postlocal_followup"],
                "updated_decisions": ["state_reconciliation", "post_rp_followup"],
            },
            "radiotherapy_summary": {
                "updated_panels": ["clinical_journey", "postlocal_followup"],
                "updated_decisions": ["state_reconciliation", "post_rt_followup"],
            },
        }
        updated_panels: list[str] = []
        updated_decisions: list[str] = []
        for committed_type in committed_types:
            updated_panels.extend(impact_map.get(committed_type, {}).get("updated_panels", []))
            updated_decisions.extend(impact_map.get(committed_type, {}).get("updated_decisions", []))
        updated_panels = list(dict.fromkeys(updated_panels))
        updated_decisions = list(dict.fromkeys(updated_decisions))

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        task_payload = {
            "task_key": f"{document.get('document_key')}:verify",
            "task_status": "verified",
            "verified_by": verified_by,
            "summary": {
                "fact_count": len(serialized_facts),
                "committed_result_types": committed_types,
                "what_changed": bundle_summary.get("what_changed", []),
                "updated_panels": updated_panels,
                "updated_decisions": updated_decisions,
                "created_or_closed_agenda_items": ["agenda_refresh"],
                "changed_recommendation": bool((commit_result[1] or {}).get("next_best_action")),
            },
        }
        task_id = _upsert_document_verification_task(c, patient_id, document_id, task_payload, verified_by=verified_by)
        _replace_verified_document_facts(c, patient_id, document_id, task_id, serialized_facts, verified_by)
        _record_document_provenance(
            c,
            patient_id,
            document_id,
            document.get("document_key"),
            (get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_date,
            serialized_facts,
            verified_by,
        )
        record_snapshot = get_patient_full_record(patient_id) or {}
        _persist_verified_document_facts_to_canonical(
            c,
            patient_id,
            document_id,
            serialized_facts,
            state_context=(record_snapshot.get("prior_history") or {}).get("current_state") or "",
            management_track=(record_snapshot.get("prior_history") or {}).get("management_track") or "",
            verified_by=verified_by,
        )
        c.execute(
            '''
            UPDATE source_documents
            SET verification_status = 'verified',
                extraction_status = CASE WHEN extraction_status = 'pending' THEN 'verified' ELSE extraction_status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (document_id, patient_id),
        )
        conn.commit()
        conn.close()

        response_payload = commit_result[1] if isinstance(commit_result[1], dict) else {}
        response_payload["document_bundle"] = _serialize_document_bundle(patient_id, document_id)
        response_payload["verified_fact_bundle"] = {
            **bundle_summary,
            "updated_panels": updated_panels,
            "updated_decisions": updated_decisions,
            "created_or_closed_agenda_items": ["agenda_refresh"],
            "changed_recommendation": bool(response_payload.get("next_best_action")),
        }
        return True, response_payload
    except Exception as e:
        logger.error(f"Error verifying source document: {e}")
        return False, str(e)


def save_stage_visit_bundle(patient_id, data):
    """
    Registra una visita de seguimiento por etapa y mantiene compatibilidad con follow_up_visits.
    """
    try:
        data = apply_gleason_profile(dict(data or {}))
        data = _apply_anthropometric_derivations(data)
        patient_id = int(patient_id)
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        record = get_patient_full_record(patient_id)
        line_number = _normalize_line_of_therapy_number(data)
        if line_number is not None:
            data["line_of_therapy"] = line_number
            data["line_of_therapy_number"] = line_number
        line_context = _normalize_line_of_therapy_context(data)
        if line_context:
            data["line_of_therapy_context"] = line_context

        state = (
            data.get("state")
            or (record.get("latest_assessment") or {}).get("state")
            or (record.get("prior_history") or {}).get("current_state")
            or "diagnostic_workup"
        )
        management_track = data.get("management_track") or ""
        if not management_track:
            from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

            management_track = infer_management_track(record, state, record.get("latest_assessment"))
        visit_date = data.get("visit_date", datetime.now().strftime("%Y-%m-%d"))
        selected_regimen_code = normalize_regimen_code(data.get("drug_scheme") or data.get("current_treatment"))
        current_treatment_label = data.get("current_treatment") or data.get("treatment") or regimen_label(selected_regimen_code)
        if isinstance(current_treatment_label, dict):
            current_treatment_label = (
                current_treatment_label.get("label_clinico")
                or current_treatment_label.get("drug_scheme_label")
                or current_treatment_label.get("current_treatment")
                or current_treatment_label.get("drug_scheme")
                or ""
            )
        if str(current_treatment_label or "").strip() in {"[object Object]", "[object object]"}:
            current_treatment_label = regimen_label(selected_regimen_code)
        if selected_regimen_code:
            data["drug_scheme"] = selected_regimen_code
        if current_treatment_label:
            data["current_treatment"] = current_treatment_label
        visit_psa_current, _ = _preferred_psa_longitudinal_value(data)
        metastatic = _derive_metastatic_payload(_merged_metastatic_context(record, data))
        data["metastasis_site"] = metastatic["metastasis_site"]
        data["metastasis_count"] = metastatic["metastasis_count"]
        data["m_substage_resolved"] = metastatic["m_substage_resolved"]
        bundle = {
            "state": state,
            "management_track": management_track,
            "visit_date": visit_date,
            "visit_type": data.get("visit_type", "stage_followup"),
            "agenda_submission_mode": data.get("agenda_submission_mode", "full_track"),
            "encounter_key": data.get("encounter_key", ""),
            "plan_key": data.get("plan_key", ""),
            "alert_keys_resolved": list(data.get("alert_keys_resolved") or []),
            "milestone_event_context": data.get("milestone_event_context", {}),
            "adjudication_targets": list(data.get("adjudication_targets") or []),
            "payload": dict(data),
        }

        c.execute(
            '''
            INSERT INTO follow_up_visits (
                patient_id, visit_date, psa_current, testosterone_current,
                alp_current, ldh_current, albumin_current, hemoglobin_current,
                ecog_current, pain_score, toxicity_events, metabolic_panel, skeletal_events,
                current_treatment, dose_adjustment, disease_status, creatinine_current,
                cystatin_c_current, bilirubin_current, ast_current, alt_current, ggt_current,
                glucose_current, opioid_use, fatigue_score, mini_cog_score, weight_kg,
                height_cm, bmi_current, weight_loss_6m_kg, weight_loss_6m_pct, prior_weight_6m_kg, exercise_status, nutrition_status,
                protein_supplements, seizure_history, dermatitis_history, peripheral_neuropathy_grade, cv_risk_status,
                ddi_reviewed, hepatic_risk_status, metastasis_site, metastasis_count,
                m_substage_resolved, metastatic_profile_json, visit_bundle_json, visit_type,
                state_at_visit, management_track, agenda_context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_date,
                visit_psa_current,
                _safe_float(data.get("testosterone"), None),
                _safe_float(data.get("alp"), None),
                _safe_float(data.get("ldh"), None),
                _safe_float(data.get("albumin"), None),
                _safe_float(data.get("hemoglobin"), None),
                _safe_int(data.get("ecog"), None),
                _safe_int(data.get("pain"), None),
                _json_blob(data.get("toxicity", {})),
                _json_blob(data.get("metabolic", {})),
                _json_blob(data.get("skeletal", {})),
                current_treatment_label,
                data.get("dose"),
                data.get("disease_status") or data.get("status"),
                _safe_float(data.get("creatinine"), None),
                _safe_float(data.get("cystatin_c"), None),
                _safe_float(data.get("bilirubin"), None),
                _safe_float(data.get("ast"), None),
                _safe_float(data.get("alt"), None),
                _safe_float(data.get("ggt"), None),
                _safe_float(data.get("glucose"), None),
                data.get("opioid_use"),
                _safe_int(data.get("fatigue_score"), None),
                _safe_int(data.get("mini_cog_score"), None),
                _safe_float(data.get("weight_kg"), None),
                _safe_float(data.get("height_cm"), None),
                _safe_float(data.get("bmi_current"), None),
                _safe_float(data.get("weight_loss_6m_kg"), None),
                _safe_float(data.get("weight_loss_6m_pct"), None),
                _safe_float(data.get("prior_weight_6m_kg"), None),
                data.get("exercise_status"),
                data.get("nutrition_status"),
                _safe_int(data.get("protein_supplements", 0), 0),
                _safe_int(data.get("seizure_history", 0), 0),
                _safe_int(data.get("dermatitis_history", 0), 0),
                _safe_int(data.get("peripheral_neuropathy_grade"), None),
                "documentado" if _is_truthy(data.get("cv_risk_documented")) else "",
                _safe_int(data.get("drug_interaction_reviewed", 0), 0),
                data.get("hepatic_risk_factors"),
                metastatic["metastasis_site"],
                metastatic["metastasis_count"],
                metastatic["m_substage_resolved"],
                metastatic["metastatic_profile_json"],
                _json_blob(bundle),
                data.get("visit_type", "stage_followup"),
                state,
                management_track,
                _json_blob(
                    {
                        "agenda_ids": data.get("agenda_ids", []),
                        "agenda_submission_mode": data.get("agenda_submission_mode", "full_track"),
                        "encounter_key": data.get("encounter_key", ""),
                        "plan_key": data.get("plan_key", ""),
                        "alert_keys_resolved": list(data.get("alert_keys_resolved") or []),
                    }
                ),
            ),
        )
        followup_id = c.lastrowid

        c.execute(
            '''
            INSERT INTO stage_visit_records (
                patient_id, visit_date, state, management_track, visit_type, visit_bundle_json, derived_followup_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_date,
                state,
                management_track,
                data.get("visit_type", "stage_followup"),
                _json_blob(bundle),
                followup_id,
            ),
        )
        visit_record_id = c.lastrowid

        _record_visit_provenance(c, patient_id, visit_record_id, state, visit_date, data)
        _mirror_biomarkers_to_longitudinal(c, patient_id, visit_date, data)
        _complete_scheduled_events_for_visit(c, patient_id, visit_date, data, visit_record_id=visit_record_id)
        treatment_update = _upsert_treatment_history_from_visit(c, patient_id, visit_date, data)
        _update_structural_baseline_from_visit(c, patient_id, data)

        survival_fields = ("vital_status", "date_of_death", "cause_of_death", "last_contact_date", "last_contact_status", "death_source")
        survival_status_payload = dict(data.get("survival_status_update") or {})
        for field in survival_fields:
            if field not in survival_status_payload and _is_present(data.get(field)):
                survival_status_payload[field] = data.get(field)
        register_death_now = _is_truthy(data.get("registrar_defuncion_en_esta_visita"))
        if register_death_now and not _is_present(survival_status_payload.get("vital_status")):
            survival_status_payload["vital_status"] = "deceased"
        should_save_survival = register_death_now or any(
            _is_present(survival_status_payload.get(field))
            for field in survival_fields
        )
        if should_save_survival:
            if not survival_status_payload.get("last_contact_date"):
                survival_status_payload["last_contact_date"] = visit_date
            if not survival_status_payload.get("last_contact_status") and any(
                _is_present(survival_status_payload.get(field))
                for field in ("vital_status", "date_of_death", "cause_of_death")
            ):
                survival_status_payload["last_contact_status"] = data.get("visit_type", "clinic_visit")
            _save_survival_status_update(
                c,
                patient_id,
                survival_status_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        survival_anchor_events = list(data.get("survival_anchor_events") or [])
        if _is_present(data.get("radiographic_progression_date")):
            survival_anchor_events.append(
                {
                    "anchor_type": "radiographic_progression",
                    "anchor_date": data.get("radiographic_progression_date"),
                    "anchor_source": data.get("radiographic_progression_source") or "visit_capture",
                    "payload": {"state": state, "management_track": management_track},
                }
            )
        if _is_present(data.get("metastatic_diagnosis_date")) or _is_present(data.get("first_metastasis_date")):
            survival_anchor_events.append(
                {
                    "anchor_type": "metastasis",
                    "anchor_date": data.get("metastatic_diagnosis_date") or data.get("first_metastasis_date"),
                    "anchor_source": data.get("metastasis_document_source") or "visit_capture",
                    "payload": {"metastasis_site": data.get("metastasis_site"), "metastasis_count": data.get("metastasis_count")},
                }
            )
        if _is_present(data.get("psa_progression_date")):
            survival_anchor_events.append(
                {
                    "anchor_type": "psa_progression",
                    "anchor_date": data.get("psa_progression_date"),
                    "anchor_source": "visit_capture",
                    "payload": {"psa": visit_psa_current, "state": state},
                }
            )
        _save_survival_anchor_events(
            c,
            patient_id,
            survival_anchor_events,
            source_type="stage_visit",
            source_record_id=visit_record_id,
        )

        structured_biopsy_payload = data.get("structured_biopsy")
        if not isinstance(structured_biopsy_payload, dict) and any(
            _is_present(data.get(field))
            for field in (
                "biopsy_date",
                "biopsy_type",
                "biopsy_route",
                "biopsy_context",
                "mri_pirads_at_biopsy",
                "total_cores",
                "positive_cores",
                "gleason_primary",
                "gleason_secondary",
                "isup_grade",
            )
        ):
            structured_biopsy_payload = {
                "biopsy_date": data.get("biopsy_date"),
                "biopsy_type": data.get("biopsy_type"),
                "biopsy_route": data.get("biopsy_route"),
                "biopsy_context": data.get("biopsy_context"),
                "mri_pirads_at_biopsy": data.get("mri_pirads_at_biopsy"),
                "total_cores": data.get("total_cores"),
                "positive_cores": data.get("positive_cores", data.get("num_cores_positive")),
                "gleason_primary": data.get("gleason_primary"),
                "gleason_secondary": data.get("gleason_secondary"),
                "isup_grade": data.get("isup_grade"),
            }
        if isinstance(structured_biopsy_payload, dict):
            _save_structured_biopsy_session(
                c,
                patient_id,
                structured_biopsy_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        active_surveillance_payload = data.get("active_surveillance_update")
        if not isinstance(active_surveillance_payload, dict) and any(
            _is_present(data.get(field))
            for field in ("as_protocol", "confirmatory_biopsy_planned", "confirmatory_biopsy_date", "as_exit_reason", "as_exit_treatment")
        ):
            active_surveillance_payload = {
                "protocol": data.get("as_protocol"),
                "schedule_items": (
                    [
                        {
                            "item_type": "rebiopsy",
                            "title": "Biopsia confirmatoria",
                            "due_date": data.get("confirmatory_biopsy_date"),
                            "status": "completed" if _coerce_bool(data.get("confirmatory_biopsy_planned")) and _is_present(data.get("confirmatory_biopsy_date")) else "scheduled",
                            "completed_date": data.get("confirmatory_biopsy_date") if _is_present(data.get("confirmatory_biopsy_date")) else "",
                            "priority": "mandatory",
                        }
                    ]
                    if _coerce_bool(data.get("confirmatory_biopsy_planned")) or _is_present(data.get("confirmatory_biopsy_date"))
                    else []
                ),
                "exit_reason": data.get("as_exit_reason"),
                "exit_treatment": data.get("as_exit_treatment"),
                "exit_date": visit_date if _is_present(data.get("as_exit_reason")) else "",
            }
        if isinstance(active_surveillance_payload, dict):
            _save_active_surveillance_update(
                c,
                patient_id,
                active_surveillance_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        skeletal_payload = data.get("skeletal_events")
        if not skeletal_payload and isinstance(data.get("skeletal"), dict):
            skeletal_map = data.get("skeletal") or {}
            derived_events = []
            for event_type, enabled in skeletal_map.items():
                if _coerce_bool(enabled):
                    derived_events.append(
                        {
                            "event_type": event_type,
                            "event_date": visit_date,
                            "details": "Capturado desde visita estructurada",
                        }
                    )
            skeletal_payload = derived_events
        _save_skeletal_events_structured(
            c,
            patient_id,
            skeletal_payload or [],
            source_type="stage_visit",
            source_record_id=visit_record_id,
        )

        bone_modifying_agent_payload = data.get("bone_modifying_agent")
        if not isinstance(bone_modifying_agent_payload, dict) and any(
            _is_present(data.get(field))
            for field in ("bma_agent", "bma_start_date", "dental_clearance_done", "onj_monitoring")
        ):
            bone_modifying_agent_payload = {
                "agent": data.get("bma_agent"),
                "start_date": data.get("bma_start_date"),
                "dental_clearance_done": data.get("dental_clearance_done"),
                "onj_monitoring": data.get("onj_monitoring"),
            }
        if isinstance(bone_modifying_agent_payload, dict):
            _save_bone_modifying_agent_course(
                c,
                patient_id,
                bone_modifying_agent_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        bone_health_payload = data.get("bone_health_snapshot")
        if not isinstance(bone_health_payload, dict):
            inferred_bone_health = {
                "snapshot_date": visit_date,
                "worst_t_score": data.get("worst_t_score"),
                "frax_major_pct": data.get("frax_major_pct"),
                "frax_hip_pct": data.get("frax_hip_pct"),
                "vitamin_d_level": data.get("vitamin_d_level"),
                "calcium_level": data.get("calcium_level"),
                "creatinine": data.get("creatinine"),
                "dxa_performed": data.get("dxa_performed"),
                "dental_clearance_done": data.get("dental_clearance_done"),
                "onj_monitoring": data.get("onj_monitoring"),
            }
            if any(_is_present(inferred_bone_health.get(field)) for field in ("worst_t_score", "frax_major_pct", "frax_hip_pct", "vitamin_d_level", "calcium_level", "creatinine", "dxa_performed", "dental_clearance_done", "onj_monitoring")):
                bone_health_payload = inferred_bone_health
        if isinstance(bone_health_payload, dict):
            _save_bone_health_snapshot(
                c,
                patient_id,
                bone_health_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        radiotherapy_course_payload = data.get("radiotherapy_course")
        if not isinstance(radiotherapy_course_payload, dict):
            inferred_rt_payload = _build_radiation_payload_from_visit(data)
            if inferred_rt_payload:
                radiotherapy_course_payload = {
                    **inferred_rt_payload,
                    "rt_intent": inferred_rt_payload.get("rt_context"),
                    "modality": inferred_rt_payload.get("rt_technique"),
                    "target_volume": inferred_rt_payload.get("target"),
                    "rt_start_date": inferred_rt_payload.get("rt_date"),
                    "rt_end_date": inferred_rt_payload.get("rt_end_date") or inferred_rt_payload.get("rt_date"),
                }
        if not isinstance(radiotherapy_course_payload, dict) and any(
            _is_present(data.get(field))
            for field in ("rt_intent", "modality", "target_volume", "total_dose_gy", "fractions", "salvage_psa_at_start")
        ):
            radiotherapy_course_payload = {
                "rt_intent": data.get("rt_intent"),
                "modality": data.get("modality"),
                "target_volume": data.get("target_volume"),
                "total_dose_gy": data.get("total_dose_gy"),
                "fractions": data.get("fractions"),
                "dose_per_fraction_gy": data.get("dose_per_fraction_gy"),
                "salvage_psa_at_start": data.get("salvage_psa_at_start"),
                "rt_start_date": data.get("rt_start_date") or visit_date,
                "rt_end_date": data.get("rt_end_date") or data.get("rt_start_date") or visit_date,
            }
        if isinstance(radiotherapy_course_payload, dict):
            _save_radiotherapy_course_detailed(
                c,
                patient_id,
                radiotherapy_course_payload,
                source_type="stage_visit",
                source_record_id=visit_record_id,
            )

        _persist_canonical_facts_from_payload(
            c,
            patient_id,
            {
                **data,
                "current_psa": visit_psa_current,
                "metastasis_assessment_date": metastatic.get("metastasis_assessment_date"),
                "metastasis_document_source": metastatic.get("metastasis_document_source"),
            },
            source_type="structured_result",
            source_record_type="stage_visit",
            source_record_id=visit_record_id,
            source_date=visit_date,
            observed_at=visit_date,
            state_context=state,
            management_track=management_track,
            certainty_tier="structured_result",
        )

        conn.commit()
        conn.close()

        if _has_any_value(
            data,
            (
                "g8_food_intake",
                "g8_weight_loss",
                "g8_mobility",
                "g8_neuropsych",
                "g8_bmi",
                "g8_medications",
                "g8_self_health",
                "mini_cog_score",
                "fatigue_score",
                "weight_kg",
                "height_cm",
                "bmi_current",
                "weight_loss_6m_kg",
                "weight_loss_6m_pct",
                "low_activity",
                "slow_gait",
                "weak_grip",
                "line_of_therapy_number",
                "line_of_therapy_context",
            ),
        ):
            save_demographics(patient_id, data)

        pro_payload = _build_pro_payload_from_visit(data)
        if pro_payload:
            save_pro_assessment(patient_id, pro_payload)

        imaging_payload = _build_imaging_payload_from_visit(data)
        if imaging_payload:
            save_imaging_study(patient_id, imaging_payload)

        genomic_payload = _build_genomic_payload_from_visit(data)
        if genomic_payload:
            save_genomic_profile(patient_id, genomic_payload)

        surgery_payload = _build_surgery_payload_from_visit(data)
        if surgery_payload and state == "post_prostatectomy":
            save_surgical_details(patient_id, surgery_payload)

        radiation_payload = _build_radiation_payload_from_visit(data)
        if radiation_payload and management_track in {"post_rt", "salvage"}:
            save_radiation_details(patient_id, radiation_payload)

        event_id = record_patient_event(
            patient_id,
            event_type="followup_visit_recorded",
            event_date=visit_date,
            state_context=state,
            management_track=management_track,
            source_type="stage_visit",
            source_record_id=visit_record_id,
            payload=bundle,
            mcode_focus={"visit_type": data.get("visit_type", "stage_followup"), "state": state},
        )
        if treatment_update.get("action") in {"therapy_started", "therapy_line_changed"}:
            record_patient_event(
                patient_id,
                event_type=treatment_update.get("action"),
                event_date=visit_date,
                state_context=state,
                management_track=management_track,
                source_type="stage_visit",
                source_record_id=visit_record_id,
                payload={
                    **treatment_update,
                    "label": f"L{treatment_update.get('line_of_therapy_number') or '?'} · {treatment_update.get('drug_scheme_label') or regimen_label(treatment_update.get('drug_scheme')) or 'Cambio terapéutico'}",
                    "decision": "Cambio de línea terapéutica confirmado para seguimiento del APE por línea",
                },
                mcode_focus={
                    "line_of_therapy_number": treatment_update.get("line_of_therapy_number"),
                    "line_of_therapy_context": treatment_update.get("line_of_therapy_context"),
                    "drug_scheme": treatment_update.get("drug_scheme"),
                },
            )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        refreshed = get_patient_full_record(patient_id)
        refresh_followup_agenda(refreshed)

        if data.get("agenda_ids"):
            resolution_payload = _agenda_resolution_payload_from_record(refreshed, data)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            for agenda_id in data.get("agenda_ids", []):
                try:
                    _resolve_followup_agenda_item(
                        c,
                        patient_id,
                        int(agenda_id),
                        data,
                        visit_record_id=visit_record_id,
                        evaluation_payload=resolution_payload,
                        patient_record=refreshed,
                    )
                except (TypeError, ValueError):
                    continue
            conn.commit()
            conn.close()
            refreshed = get_patient_full_record(patient_id)

        agenda = refresh_followup_agenda(refreshed)
        refreshed = get_patient_full_record(patient_id)
        sync_scheduled_events(refreshed, state=state, management_track=management_track)

        # ── AI Event Bus — publish visit_recorded ──
        _publish_clinical_event(patient_id, "visit_recorded", {
            "visit_date": visit_date,
            "state": state,
            "followup_id": followup_id,
            "psa": data.get("psa"),
            "ecog": data.get("ecog"),
        })

        return True, {
            "followup_id": followup_id,
            "visit_record_id": visit_record_id,
            "agenda": agenda,
            "intelligence": intelligence,
            "resolved_alert_keys": list(data.get("alert_keys_resolved") or []),
            "encounter_key": data.get("encounter_key", ""),
            "plan_key": data.get("plan_key", ""),
            "master_followup_plan": intelligence.get("master_followup_plan", {}),
        }
    except Exception as e:
        import traceback as _tb
        logger.error(f"Error adding follow-up: {e}\n{''.join(_tb.format_exception(e))}")
        return False, str(e)

def get_stats():
    """
    Returns aggregated statistics for the dashboard.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Total Patients
        c.execute("SELECT COUNT(*) as count FROM patients")
        total = c.fetchone()['count']
        
        # Risk Distribution (NCCN)
        # We need to parse JSON or store risk separately. Parsing JSON in SQLite is hard without JSON1 extension.
        # But we can do Python-side aggregation for small datasets.
        # Or alter table to store 'risk_group' column.
        
        # Let's fetch all and aggregate in Python for flexibility and speed (assuming <10k rows)
        c.execute("SELECT clinical_scores, discordance_alert FROM patients")
        rows = c.fetchall()
        
        risk_counts = {'BAJO': 0, 'INTERMEDIO': 0, 'ALTO': 0, 'MUY ALTO': 0, 'OTRO': 0}
        discordance_count = 0
        
        for row in rows:
            if row['discordance_alert']:
                discordance_count += 1
            
            try:
                scores = json.loads(row['clinical_scores'])
                risk = scores.get('nccn', {}).get('risk_group', 'OTRO')
                # Normalizar keys
                if 'BAJO' in risk: risk_counts['BAJO'] += 1
                elif 'INTERMEDIO' in risk: risk_counts['INTERMEDIO'] += 1
                elif 'ALTO' in risk: risk_counts['ALTO'] += 1 # Catch ALTO and MUY ALTO if needed
                if 'MUY ALTO' in risk: risk_counts['MUY ALTO'] += 1 # Overlap correction needed?
                # Actually, simpler logic:
                best_key = 'OTRO'
                for k in risk_counts.keys():
                    if k in risk:
                        best_key = k
                        break
                risk_counts[best_key] += 1
            except:
                pass
                
        conn.close()
        
        return {
            'total_patients': total,
            'risk_distribution': risk_counts,
            'discordance_rate': round((discordance_count / total * 100), 1) if total > 0 else 0,
            'discordance_count': discordance_count
        }
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {}

# ══════════════════════════════════════════════════════════════════════════════
# ══  FUNCIONES CRUD — FASE B & C (Expediente Longitudinal + Investigación)
# ══════════════════════════════════════════════════════════════════════════════

def save_demographics(patient_id, data):
    """Guarda o actualiza datos demográficos del paciente."""
    try:
        data = _apply_anthropometric_derivations(dict(data or {}))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO patient_demographics (
                patient_id, estado_residencia, seguridad_social, escolaridad,
                ocupacion, estado_civil, etnia, tabaquismo, paquetes_anio,
                diabetes_mellitus, hipertension, sindrome_metabolico,
                actividad_fisica, ipss_score, iief5_score,
                g8_food_intake, g8_weight_loss, g8_mobility, g8_neuropsych,
                g8_bmi, g8_medications, g8_self_health,
                mini_cog_score, fatigue_score, weight_kg, height_cm, bmi_current,
                weight_loss_6m_kg, weight_loss_6m_pct, prior_weight_6m_kg, low_activity, slow_gait, weak_grip,
                line_of_therapy_number, line_of_therapy_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            data.get('estado_residencia'), data.get('seguridad_social'),
            data.get('escolaridad'), data.get('ocupacion'), data.get('estado_civil'),
            data.get('etnia', 'hispano'), data.get('tabaquismo', 'nunca'),
            _safe_float(data.get('paquetes_anio', 0), 0),
            _safe_int(data.get('diabetes_mellitus', 0), 0), _safe_int(data.get('hipertension', 0), 0),
            _safe_int(data.get('sindrome_metabolico', 0), 0),
            data.get('actividad_fisica', 'sedentario'),
            _safe_int(data.get('ipss_score', 0), 0), _safe_int(data.get('iief5_score', 0), 0),
            _safe_float(data.get('g8_food_intake'), None),
            _safe_float(data.get('g8_weight_loss'), None),
            _safe_float(data.get('g8_mobility'), None),
            _safe_float(data.get('g8_neuropsych'), None),
            _safe_float(data.get('g8_bmi'), None),
            _safe_float(data.get('g8_medications'), None),
            _safe_float(data.get('g8_self_health'), None),
            _safe_int(data.get('mini_cog_score'), None),
            _safe_int(data.get('fatigue_score'), None),
            _safe_float(data.get('weight_kg'), None),
            _safe_float(data.get('height_cm'), None),
            _safe_float(data.get('bmi_current'), None),
            _safe_float(data.get('weight_loss_6m_kg'), None),
            _safe_float(data.get('weight_loss_6m_pct'), None),
            _safe_float(data.get('prior_weight_6m_kg'), None),
            _safe_int(data.get('low_activity'), None),
            _safe_int(data.get('slow_gait'), None),
            _safe_int(data.get('weak_grip'), None),
            _normalize_line_of_therapy_number(data),
            _normalize_line_of_therapy_context(data),
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving demographics: {e}")
        return False


def save_family_history(patient_id, relatives):
    """Guarda historia familiar detallada. relatives: lista de dicts."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Limpiar registros anteriores
        c.execute("DELETE FROM family_history_detail WHERE patient_id = ?", (patient_id,))
        for rel in relatives:
            c.execute('''
                INSERT INTO family_history_detail (
                    patient_id, relative_type, cancer_type, age_at_diagnosis,
                    known_mutation, deceased
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                patient_id, rel.get('relative_type'), rel.get('cancer_type'),
                _safe_int(rel.get('age_at_diagnosis', 0), 0), rel.get('known_mutation', 'Desconocido'),
                _safe_int(rel.get('deceased', 0), 0)
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving family history: {e}")
        return False


def save_imaging_study(patient_id, data):
    """Registra un estudio de imagen."""
    try:
        payload = normalize_psma_imaging_payload(data) if "psma" in str(data.get("study_type", "")).lower() else dict(data)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO imaging_studies (
                patient_id, study_date, study_type,
                pirads_score, pirads_location, lesion_size_mm,
                ece_suspicion, svi_suspicion, precise_score,
                psma_result, psma_suv_max, psma_radioligand, psma_index_lesion_site,
                psma_index_lesion_suvmax, psma_uptake_pattern, psma_rads_score,
                conventional_stage_before_psma, psma_stage_after_psma,
                psma_upstaged_vs_conventional, psma_management_changed,
                bone_scan_result, bone_lesion_count,
                findings_json, radiologist_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, payload.get('study_date', datetime.now().strftime('%Y-%m-%d')),
            payload.get('study_type'),
            payload.get('pirads_score'), payload.get('pirads_location'),
            payload.get('lesion_size_mm'),
            _safe_int(payload.get('ece_suspicion', 0), 0), _safe_int(payload.get('svi_suspicion', 0), 0),
            payload.get('precise_score'),
            payload.get('psma_result'), payload.get('psma_suv_max'),
            payload.get('psma_radioligand'), payload.get('psma_index_lesion_site'),
            payload.get('psma_index_lesion_suvmax'), payload.get('psma_uptake_pattern'), payload.get('psma_rads_score'),
            payload.get('conventional_stage_before_psma'), payload.get('psma_stage_after_psma'),
            payload.get('psma_upstaged_vs_conventional'), payload.get('psma_management_changed'),
            payload.get('bone_scan_result'), payload.get('bone_lesion_count'),
            json.dumps(payload.get('findings', {})),
            payload.get('radiologist_notes')
        ))
        conn.commit()
        conn.close()
        # ── AI Event Bus — publish imaging_completed ──
        _publish_clinical_event(int(patient_id), "imaging_completed", {
            "study_type": payload.get("study_type"),
            "study_date": payload.get("study_date"),
        })
        return True
    except Exception as e:
        logger.error(f"Error saving imaging study: {e}")
        return False


def save_mri_fact(patient_id, data):
    """Guarda hechos tempranos de resonancia magnética multiparamétrica para seguimiento diagnóstico."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO mri_facts (
                patient_id, assessment_id, fact_date, mpmri_quality, decision_usable,
                pirads_score, lesion_location, lesion_size_mm, prostate_volume_ml, findings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("fact_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("mpmri_quality"),
                _safe_int(data.get("decision_usable"), 0),
                data.get("pirads_score"),
                data.get("lesion_location"),
                data.get("lesion_size_mm"),
                data.get("prostate_volume_ml"),
                json.dumps(data.get("findings", {}), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving MRI fact: {e}")
        return False


def save_diagnostic_plan(patient_id, data):
    """Guarda el plan diagnóstico temprano sin convertirlo en confirmación histológica."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO diagnostic_plans (
                patient_id, assessment_id, plan_date, source_state, plan_type, plan_status,
                management_intent_status, plan_summary, recommended_pathway, next_action,
                risk_calculator_pathway, trigger_conditions_json, evidence_context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("plan_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("source_state"),
                data.get("plan_type"),
                data.get("plan_status", "planificado"),
                data.get("management_intent_status", "candidate"),
                data.get("plan_summary"),
                data.get("recommended_pathway"),
                data.get("next_action"),
                data.get("risk_calculator_pathway"),
                json.dumps(data.get("trigger_conditions", []), ensure_ascii=False),
                json.dumps(data.get("evidence_context", []), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving diagnostic plan: {e}")
        return False


def save_biopsy_trigger(patient_id, data):
    """Guarda un trigger de biopsia como hecho temprano pendiente de confirmación."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO biopsy_trigger_events (
                patient_id, assessment_id, trigger_date, source_state, trigger_reason,
                priority, planned_biopsy_type, planned_biopsy_route, trigger_status,
                management_intent_status, activation_conditions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("trigger_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("source_state"),
                data.get("trigger_reason"),
                data.get("priority"),
                data.get("planned_biopsy_type"),
                data.get("planned_biopsy_route"),
                data.get("trigger_status", "pendiente_de_confirmacion"),
                data.get("management_intent_status", "candidate"),
                json.dumps(data.get("activation_conditions", []), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving biopsy trigger: {e}")
        return False


def save_genomic_profile(patient_id, data):
    """Guarda perfil genómico del paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO genomic_profile (
                patient_id, test_date, test_type,
                decipher_score, decipher_risk, prolaris_score, gps_score,
                brca1_status, brca2_status, atm_status, chek2_status, palb2_status, cdk12_status,
                msi_status, tmb_score, ar_v7_status, pten_loss, tp53_status,
                hrr_overall, actionable_findings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('test_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('test_type'),
            data.get('decipher_score'), data.get('decipher_risk'),
            data.get('prolaris_score'), data.get('gps_score'),
            data.get('brca1_status'), data.get('brca2_status'),
            data.get('atm_status'), data.get('chek2_status'),
            data.get('palb2_status'), data.get('cdk12_status'),
            data.get('msi_status'), data.get('tmb_score'),
            data.get('ar_v7_status'), _safe_int(data.get('pten_loss', 0), 0),
            data.get('tp53_status'), data.get('hrr_overall', 'Desconocido'),
            json.dumps(data.get('actionable_findings', []))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving genomic profile: {e}")
        return False


def save_biopsy(patient_id, data):
    """Registra una biopsia detallada."""
    try:
        data = apply_gleason_profile(dict(data or {}))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO biopsy_details (
                patient_id, biopsy_date, biopsy_type, biopsy_context,
                total_cores, positive_cores, max_core_involvement_pct, histology_subtype,
                gleason_primary, gleason_secondary, gleason_tertiary, isup_grade,
                patron_cribiforme, carcinoma_intraductal,
                perineural_invasion, lymphovascular_invasion,
                porcentaje_patron_4, porcentaje_patron_5,
                upgrade_from_previous, previous_isup, adverse_histology_variant_type,
                adverse_histology_variant_detail, pathologist_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('biopsy_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('biopsy_type', 'sistematica'), data.get('biopsy_context', 'diagnostica'),
            _safe_int(data.get('total_cores', 12), 12), _safe_int(data.get('positive_cores', 0), 0),
            _safe_float(data.get('max_core_involvement_pct', 0), 0),
            data.get('histology_subtype'),
            _safe_int(data.get('gleason_primary'), None), _safe_int(data.get('gleason_secondary'), None),
            data.get('gleason_tertiary'), _safe_int(data.get('isup_grade'), None),
            _safe_int(data.get('patron_cribiforme', 0), 0), _safe_int(data.get('carcinoma_intraductal', 0), 0),
            _safe_int(data.get('perineural_invasion', 0), 0), _safe_int(data.get('lymphovascular_invasion', 0), 0),
            _safe_float(data.get('porcentaje_patron_4', 0), 0), _safe_float(data.get('porcentaje_patron_5', 0), 0),
            _safe_int(data.get('upgrade_from_previous', 0), 0), data.get('previous_isup'),
            data.get('adverse_histology_variant_type'), data.get('adverse_histology_variant_detail'),
            data.get('pathologist_notes')
        ))
        legacy_biopsy_id = c.lastrowid
        structured_payload = dict(data)
        if not structured_payload.get("systematic_cores") and not structured_payload.get("targeted_cores"):
            total_cores = _safe_int(data.get("total_cores"), 0)
            positive_cores = _safe_int(data.get("positive_cores"), 0)
            systematic_cores = []
            for index in range(total_cores):
                systematic_cores.append(
                    {
                        "core_id": f"S{index + 1}",
                        "location_sextant": "",
                        "core_type": "systematic",
                        "positive": index < positive_cores,
                        "involvement_pct": data.get("max_core_involvement_pct") if index == 0 and positive_cores > 0 else None,
                        "gleason_primary": data.get("gleason_primary"),
                        "gleason_secondary": data.get("gleason_secondary"),
                        "isup_grade": data.get("isup_grade"),
                        "cribriform_pattern": bool(data.get("patron_cribiforme", 0)),
                        "intraductal_carcinoma": bool(data.get("carcinoma_intraductal", 0)),
                    }
                )
            structured_payload.update(
                {
                    "biopsy_type": data.get("biopsy_type", "systematic"),
                    "biopsy_context": data.get("biopsy_context", "diagnostic"),
                    "biopsy_route": data.get("biopsy_route", ""),
                    "systematic_cores": systematic_cores,
                }
            )
        _save_structured_biopsy_session(
            c,
            patient_id,
            structured_payload,
            source_type="legacy_biopsy",
            source_record_id=legacy_biopsy_id,
            legacy_biopsy_id=legacy_biopsy_id,
        )
        _persist_official_diagnosis_fields(c, patient_id, data)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving biopsy: {e}")
        return False


def enroll_in_as(patient_id, data):
    """Inscribe paciente en programa de Vigilancia Activa."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO active_surveillance (
                patient_id, enrollment_date, enrollment_protocol,
                enrollment_criteria_met, current_status
            ) VALUES (?, ?, ?, ?, 'activo')
        ''', (
            patient_id, data.get('enrollment_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('protocol', 'NCCN_VL'),
            json.dumps(data.get('criteria_met', {}))
        ))
        _save_active_surveillance_update(
            c,
            patient_id,
            {
                "enrollment_date": data.get('enrollment_date', datetime.now().strftime('%Y-%m-%d')),
                "protocol": data.get('protocol', 'NCCN_VL'),
                "criteria_met": data.get('criteria_met', {}),
                "current_status": data.get("current_status", "active"),
                "schedule_items": data.get("schedule_items") or data.get("schedule") or [],
                "trigger_events": data.get("trigger_events") or [],
                "conversion_events": data.get("conversion_events") or [],
            },
            source_type="legacy_active_surveillance",
            source_record_id=c.lastrowid,
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error enrolling in AS: {e}")
        return False


def exit_as(patient_id, data):
    """Registra salida de Vigilancia Activa."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE active_surveillance SET
                current_status = ?, exit_date = ?, exit_reason = ?, exit_treatment = ?
            WHERE patient_id = ? AND current_status = 'activo'
        ''', (
            data.get('status', 'salida_upgrade'),
            data.get('exit_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('exit_reason'),
            data.get('exit_treatment'),
            patient_id
        ))
        _save_active_surveillance_update(
            c,
            patient_id,
            {
                "current_status": data.get("status", "exited"),
                "exit_date": data.get('exit_date', datetime.now().strftime('%Y-%m-%d')),
                "exit_reason": data.get('exit_reason'),
                "exit_treatment": data.get('exit_treatment'),
                "conversion_events": [
                    {
                        "conversion_date": data.get('exit_date', datetime.now().strftime('%Y-%m-%d')),
                        "exit_reason": data.get('exit_reason'),
                        "exit_treatment": data.get('exit_treatment'),
                    }
                ],
            },
            source_type="legacy_active_surveillance_exit",
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error exiting AS: {e}")
        return False


def save_surgical_details(patient_id, data):
    """Registra detalles de la cirugía (prostatectomía radical)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO surgical_details (
                patient_id, surgery_date, surgery_type, nerve_sparing,
                plnd_performed, plnd_type, nodes_removed, nodes_positive,
                pathological_gleason_primary, pathological_gleason_secondary, pathological_isup,
                pathological_stage, surgical_margin_status, margin_location,
                ece_pathological, svi_pathological, lni_pathological,
                specimen_weight_grams, tumor_volume_pct, capra_s_score, surgical_approach,
                continence_status, potency_status, pde5i_use, pads_per_day, recovery_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get('surgery_date'),
                data.get('surgery_type'),
                data.get('nerve_sparing'),
                _safe_int(data.get('plnd_performed', 0), 0),
                data.get('plnd_type'),
                _safe_int(data.get('nodes_removed', 0), 0),
                _safe_int(data.get('nodes_positive', 0), 0),
                data.get('pathological_gleason_primary'),
                data.get('pathological_gleason_secondary'),
                data.get('pathological_isup'),
                data.get('pathological_stage'),
                _safe_int(data.get('surgical_margin_status', 0), 0),
                data.get('margin_location'),
                _safe_int(data.get('ece_pathological', 0), 0),
                _safe_int(data.get('svi_pathological', 0), 0),
                _safe_int(data.get('lni_pathological', 0), 0),
                data.get('specimen_weight_grams'),
                data.get('tumor_volume_pct'),
                data.get('capra_s_score'),
                data.get('surgical_approach'),
                data.get('continence_status'),
                data.get('potency_status'),
                _safe_int(data.get('pde5i_use', 0), 0),
                _safe_int(data.get('pads_per_day', 0), 0),
                data.get('recovery_notes'),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving surgical details: {e}")
        return False


def save_radiation_details(patient_id, data):
    """Registra detalles de radioterapia."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO radiation_details (
                patient_id, rt_date, rt_context, rt_technique, target,
                total_dose_gy, fractions, dose_per_fraction_gy,
                concurrent_adt, adt_duration_months, adt_agent,
                gu_toxicity_grade, gi_toxicity_grade, notes, session_duration_minutes,
                total_duration_days, hematuria, dysuria, anemia_related, late_toxicity_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get('rt_date'),
                data.get('rt_context'),
                data.get('rt_technique'),
                data.get('target'),
                data.get('total_dose_gy'),
                data.get('fractions'),
                data.get('dose_per_fraction_gy'),
                _safe_int(data.get('concurrent_adt', 0), 0),
                data.get('adt_duration_months'),
                data.get('adt_agent'),
                _safe_int(data.get('gu_toxicity_grade', 0), 0),
                _safe_int(data.get('gi_toxicity_grade', 0), 0),
                data.get('notes'),
                _safe_int(data.get('session_duration_minutes'), None),
                _safe_int(data.get('total_duration_days'), None),
                data.get('hematuria'),
                data.get('dysuria'),
                data.get('anemia_related'),
                _json_blob(data.get('late_toxicity_json', {})),
            ),
        )
        legacy_radiation_id = c.lastrowid
        detailed_payload = dict(data)
        detailed_payload.setdefault("rt_intent", data.get("rt_context"))
        detailed_payload.setdefault("modality", data.get("rt_technique"))
        detailed_payload.setdefault("target_volume", data.get("target"))
        detailed_payload.setdefault("rt_start_date", data.get("rt_date"))
        detailed_payload.setdefault("rt_end_date", data.get("rt_end_date") or data.get("rt_date"))
        if not detailed_payload.get("toxicity"):
            toxicity = []
            if _safe_int(data.get("gu_toxicity_grade"), 0) > 0:
                toxicity.append({"domain": "GU", "phase": "acute", "grade": _safe_int(data.get("gu_toxicity_grade"), 0)})
            if _safe_int(data.get("gi_toxicity_grade"), 0) > 0:
                toxicity.append({"domain": "GI", "phase": "acute", "grade": _safe_int(data.get("gi_toxicity_grade"), 0)})
            late_payload = _parse_json_blob(data.get("late_toxicity_json"), {})
            if isinstance(late_payload, dict):
                for domain in ("GU", "GI"):
                    grade = _safe_int(late_payload.get(f"{domain.lower()}_grade"), None)
                    if grade is not None:
                        toxicity.append({"domain": domain, "phase": "late", "grade": grade, "details": late_payload.get(f"{domain.lower()}_details", "")})
            detailed_payload["toxicity"] = toxicity
        _save_radiotherapy_course_detailed(
            c,
            patient_id,
            detailed_payload,
            source_type="legacy_radiotherapy",
            source_record_id=legacy_radiation_id,
            legacy_radiation_id=legacy_radiation_id,
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving radiation details: {e}")
        return False


def save_pro_assessment(patient_id, data):
    """Guarda evaluación de PROs (Patient-Reported Outcomes)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO patient_pros (
                patient_id, assessment_date,
                ipss_total, ipss_qol, pad_usage,
                iief5_score, erection_sufficient, pde5i_use,
                bpi_worst_pain, bpi_average_pain, bpi_interference,
                eq5d_index, eq5d_vas, fact_p_total, max_acs_score,
                facit_fatigue_total, fact_p_physical, fact_p_social, fact_p_emotional,
                fact_p_functional, fact_p_prostate, continence_status, time_to_continence_months,
                sexual_recovery_status, time_to_erection_months, g8_total,
                epic26_urinary_domain, epic26_sexual_domain, epic26_bowel_domain, epic26_hormonal_domain,
                eortc_qlq_c30_global_health, eortc_qlq_c30_physical, eortc_qlq_c30_role,
                eortc_qlq_c30_emotional, eortc_qlq_c30_fatigue, eortc_qlq_c30_pain,
                anxiety_score, clinician_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('date', datetime.now().strftime('%Y-%m-%d')),
            data.get('ipss_total'), data.get('ipss_qol'), _safe_int(data.get('pad_usage', 0), 0),
            data.get('iief5_score'), _safe_int(data.get('erection_sufficient', 0), 0),
            _safe_int(data.get('pde5i_use', 0), 0),
            data.get('bpi_worst_pain'), data.get('bpi_average_pain'),
            data.get('bpi_interference'),
            data.get('eq5d_index'), data.get('eq5d_vas'),
            data.get('fact_p_total'), data.get('max_acs_score'),
            data.get('facit_fatigue_total'), data.get('fact_p_physical'), data.get('fact_p_social'),
            data.get('fact_p_emotional'), data.get('fact_p_functional'), data.get('fact_p_prostate'),
            data.get('continence_status'), data.get('time_to_continence_months'),
            data.get('sexual_recovery_status'), data.get('time_to_erection_months'), data.get('g8_total'),
            data.get('epic26_urinary_domain'), data.get('epic26_sexual_domain'),
            data.get('epic26_bowel_domain'), data.get('epic26_hormonal_domain'),
            data.get('eortc_qlq_c30_global_health'), data.get('eortc_qlq_c30_physical'),
            data.get('eortc_qlq_c30_role'), data.get('eortc_qlq_c30_emotional'),
            data.get('eortc_qlq_c30_fatigue'), data.get('eortc_qlq_c30_pain'),
            data.get('anxiety_score'),
            data.get('clinician_notes')
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving PRO assessment: {e}")
        return False


def save_bcr(patient_id, data):
    """Registra recurrencia bioquímica."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO biochemical_recurrence (
                patient_id, primary_treatment, primary_treatment_date,
                nadir_psa, nadir_date,
                bcr_detected, bcr_date, bcr_psa, bcr_definition,
                psadt_at_bcr, time_to_bcr_months,
                salvage_treatment, salvage_date, salvage_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('primary_treatment'), data.get('primary_treatment_date'),
            data.get('nadir_psa'), data.get('nadir_date'),
            _safe_int(data.get('bcr_detected', 0), 0), data.get('bcr_date'),
            data.get('bcr_psa'), data.get('bcr_definition'),
            data.get('psadt_at_bcr'), data.get('time_to_bcr_months'),
            data.get('salvage_treatment'), data.get('salvage_date'),
            data.get('salvage_response')
        ))
        bcr_points = _normalize_psa_history_points(
            [
                {
                    "sample_date": data.get("bcr_date"),
                    "psa_value": data.get("bcr_psa"),
                    "context": "postlocal",
                    "assay_type": "desconocido",
                    "source": "biochemical_recurrence",
                    "entry_origin": "bcr_registry",
                }
            ],
            default_source="biochemical_recurrence",
            default_entry_origin="bcr_registry",
            default_sample_date=data.get("bcr_date"),
            default_context="postlocal",
        )
        if bcr_points:
            _persist_psa_series_points(c, int(patient_id), bcr_points)
        conn.commit()
        conn.close()
        # ── AI Event Bus — publish bcr_detected ──
        if _safe_int(data.get('bcr_detected', 0), 0):
            _publish_clinical_event(int(patient_id), "bcr_detected", {
                "bcr_date": data.get("bcr_date"),
                "bcr_psa": data.get("bcr_psa"),
                "psadt_at_bcr": data.get("psadt_at_bcr"),
            })
        return True
    except Exception as e:
        logger.error(f"Error saving BCR: {e}")
        return False


def save_structured_result(patient_id, data):
    result_type = str(data.get("result_type") or "").strip().lower()
    payload = dict(data.get("payload") or {})
    if not result_type:
        return False, "Se requiere result_type"
    if result_type == "pathology":
        success = save_biopsy(patient_id, payload)
        event_type = "pathology_verified"
    elif result_type == "genomic":
        success = save_genomic_profile(patient_id, payload)
        event_type = "genomic_result_verified"
    elif result_type == "imaging":
        success = save_imaging_study(patient_id, payload)
        event_type = "study_resulted"
    elif result_type == "goals_of_care":
        success = True
        event_type = "goals_of_care_updated"
    elif result_type == "surgery_summary":
        success = save_surgical_details(patient_id, payload)
        event_type = "procedure_performed"
    elif result_type == "radiotherapy_summary":
        success = save_radiation_details(patient_id, payload)
        event_type = "procedure_performed"
    else:
        return False, "Tipo de resultado no soportado"
    if not success:
        return False, "No fue posible persistir el resultado estructurado"
    if any(
        _is_present(payload.get(field))
        for field in (
            "histology_subtype",
            "gleason_primary",
            "gleason_secondary",
            "isup_grade",
            "clinical_tstage",
            "nodal_status",
            "clinical_stage_group",
            "clinical_risk_group",
        )
    ):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        _persist_official_diagnosis_fields(cursor, patient_id, payload)
        conn.commit()
        conn.close()
    record_snapshot = get_patient_full_record(patient_id) or {}
    source_date = (
        payload.get("study_date")
        or payload.get("biopsy_date")
        or payload.get("test_date")
        or payload.get("surgery_date")
        or payload.get("rt_date")
        or datetime.now().strftime("%Y-%m-%d")
    )
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    _persist_canonical_facts_from_payload(
        cursor,
        patient_id,
        payload,
        source_type="structured_result",
        source_record_type=result_type,
        source_record_id=None,
        source_date=source_date,
        observed_at=source_date,
        state_context=(record_snapshot.get("prior_history") or {}).get("current_state") or "",
        management_track=(record_snapshot.get("prior_history") or {}).get("management_track") or "",
        certainty_tier="structured_result",
    )
    conn.commit()
    conn.close()
    event_id = record_patient_event(
        patient_id,
        event_type=event_type,
        event_date=source_date,
        state_context=(record_snapshot.get("prior_history") or {}).get("current_state", ""),
        source_type="structured_result",
        payload={"result_type": result_type, **payload},
        mcode_focus={"result_type": result_type},
    )
    bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
    refreshed = get_patient_full_record(patient_id)
    agenda = refresh_followup_agenda(refreshed)
    return True, {"event_id": event_id, "agenda": agenda, **bundle}


def create_smart_alert(patient_id, alert_type, severity, title, description, data_dict=None):
    """Crea una alerta inteligente para un paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO smart_alerts (
                patient_id, alert_type, severity, title, description, data_json, active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (
            patient_id, alert_type, severity, title, description,
            json.dumps(data_dict) if data_dict else None
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        return False


def get_patient_alerts(patient_id, unacknowledged_only=True):
    """Obtiene alertas de un paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT * FROM smart_alerts WHERE patient_id = ?"
        if unacknowledged_only:
            query += " AND acknowledged = 0"
        query += " AND COALESCE(active, 1) = 1"
        query += " ORDER BY alert_date DESC"
        c.execute(query, (patient_id,))
        alerts = _hydrate_alert_rows(c.fetchall())
        conn.close()
        return alerts
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return []


def acknowledge_alert(alert_id, user='system'):
    """Marca una alerta como vista/reconocida."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE smart_alerts SET
                acknowledged = 1, acknowledged_by = ?, acknowledged_date = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (user, alert_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return False


def get_patient_full_record(nss_or_id, *, include_derivatives=True, include_ledger=True):
    """
    Recupera el expediente COMPLETO del paciente (Fase B).
    Incluye todas las tablas nuevas para el perfil longitudinal.
    Acepta NSS (texto) o ID numérico como identificador.
    """
    try:
        import sqlite3 as _sqlite3

        globals()["sqlite3"] = _sqlite3
        conn = _sqlite3.connect(DB_PATH)
        conn.row_factory = _sqlite3.Row
        c = conn.cursor()

        # 1. Identity — buscar primero por NSS, luego por ID numérico
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return None
        patient_id = identity['id']

        # 2. Baseline
        c.execute("SELECT * FROM clinical_baseline WHERE patient_id = ?", (patient_id,))
        baseline = c.fetchone()
        baseline_dict = dict(baseline) if baseline else {}
        if baseline_dict:
            baseline_dict["metastatic_profile"] = _parse_json_blob(baseline_dict.get("metastatic_profile_json"), {})

        # 3. Demographics
        c.execute("SELECT * FROM patient_demographics WHERE patient_id = ?", (patient_id,))
        demographics = c.fetchone()

        # 4. Family History
        c.execute("SELECT * FROM family_history_detail WHERE patient_id = ?", (patient_id,))
        family_history = [dict(row) for row in c.fetchall()]

        # 5. Imaging Studies
        c.execute("SELECT * FROM imaging_studies WHERE patient_id = ? ORDER BY study_date DESC", (patient_id,))
        imaging = [dict(row) for row in c.fetchall()]
        for item in imaging:
            item["findings"] = _parse_json_blob(item.pop("findings_json", None), {})
        psma_structured_profile = build_psma_structured_profile({"imaging": imaging})

        c.execute("SELECT * FROM mri_facts WHERE patient_id = ? ORDER BY fact_date DESC, id DESC", (patient_id,))
        mri_facts = [dict(row) for row in c.fetchall()]
        for item in mri_facts:
            item["findings"] = _parse_json_blob(item.pop("findings_json", None), {})

        # 6. Genomic Profile
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC LIMIT 1", (patient_id,))
        genomics = c.fetchone()
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC, id DESC", (patient_id,))
        genomic_reports = [dict(row) for row in c.fetchall()]

        # 7. Biopsies
        c.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC", (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]

        c.execute("SELECT * FROM diagnostic_plans WHERE patient_id = ? ORDER BY plan_date DESC, id DESC", (patient_id,))
        diagnostic_plans = [dict(row) for row in c.fetchall()]
        for item in diagnostic_plans:
            item["trigger_conditions"] = _parse_json_blob(item.pop("trigger_conditions_json", None), [])
            item["evidence_context"] = _parse_json_blob(item.pop("evidence_context_json", None), [])

        c.execute("SELECT * FROM biopsy_trigger_events WHERE patient_id = ? ORDER BY trigger_date DESC, id DESC", (patient_id,))
        biopsy_triggers = [dict(row) for row in c.fetchall()]
        for item in biopsy_triggers:
            item["activation_conditions"] = _parse_json_blob(item.pop("activation_conditions_json", None), [])

        # 8. Active Surveillance
        c.execute("SELECT * FROM active_surveillance WHERE patient_id = ? ORDER BY enrollment_date DESC LIMIT 1", (patient_id,))
        as_record = c.fetchone()

        # 9. BCR
        c.execute("SELECT * FROM biochemical_recurrence WHERE patient_id = ?", (patient_id,))
        bcr = c.fetchone()

        # 10. Surgical Details
        c.execute("SELECT * FROM surgical_details WHERE patient_id = ?", (patient_id,))
        surgery = c.fetchone()

        # 11. Radiation Details
        c.execute("SELECT * FROM radiation_details WHERE patient_id = ? ORDER BY rt_date ASC", (patient_id,))
        radiation = [dict(row) for row in c.fetchall()]

        c.execute(
            "SELECT * FROM survival_status_records WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC",
            (patient_id,),
        )
        survival_status_rows = _hydrate_survival_status_rows(c.fetchall())
        c.execute(
            "SELECT * FROM survival_anchor_events WHERE patient_id = ? AND COALESCE(active, 1) = 1 ORDER BY anchor_date ASC, id ASC",
            (patient_id,),
        )
        survival_anchor_events = _hydrate_survival_anchor_rows(c.fetchall())

        c.execute(
            "SELECT * FROM biopsy_sessions WHERE patient_id = ? ORDER BY biopsy_date ASC, id ASC",
            (patient_id,),
        )
        biopsy_sessions = _hydrate_biopsy_session_rows(c.fetchall())
        biopsy_session_ids = [item.get("id") for item in biopsy_sessions if item.get("id")]
        structured_biopsy_sessions = []
        if biopsy_session_ids:
            placeholders = ",".join(["?"] * len(biopsy_session_ids))
            c.execute(
                f"SELECT * FROM biopsy_cores WHERE session_id IN ({placeholders}) ORDER BY id ASC",
                biopsy_session_ids,
            )
            biopsy_cores = _hydrate_biopsy_core_rows(c.fetchall())
            c.execute(
                f"SELECT * FROM biopsy_targets WHERE session_id IN ({placeholders}) ORDER BY id ASC",
                biopsy_session_ids,
            )
            biopsy_targets = _hydrate_biopsy_target_rows(c.fetchall())
            c.execute(
                f"SELECT * FROM biopsy_mri_pathology_links WHERE session_id IN ({placeholders}) ORDER BY id ASC",
                biopsy_session_ids,
            )
            biopsy_links = _hydrate_biopsy_link_rows(c.fetchall())
            core_map = {}
            for item in biopsy_cores:
                core_map.setdefault(item.get("session_id"), []).append(item)
            target_map = {}
            for item in biopsy_targets:
                target_map.setdefault(item.get("session_id"), []).append(item)
            link_map = {}
            for item in biopsy_links:
                link_map.setdefault(item.get("session_id"), []).append(item)
            structured_biopsy_sessions = [
                _build_biopsy_session_summary(
                    session,
                    core_map.get(session.get("id"), []),
                    target_map.get(session.get("id"), []),
                    link_map.get(session.get("id"), []),
                )
                for session in biopsy_sessions
            ]

        c.execute(
            "SELECT * FROM as_enrollments WHERE patient_id = ? ORDER BY enrollment_date DESC, id DESC",
            (patient_id,),
        )
        as_enrollments = _hydrate_as_enrollment_rows(c.fetchall())
        current_as_enrollment = as_enrollments[0] if as_enrollments else {}
        as_schedule_items = []
        as_trigger_events = []
        as_conversion_events = []
        active_surveillance_protocol = {}
        if current_as_enrollment:
            enrollment_id = current_as_enrollment.get("id")
            c.execute(
                "SELECT * FROM as_schedule_items WHERE enrollment_id = ? ORDER BY due_date ASC, id ASC",
                (enrollment_id,),
            )
            as_schedule_items = _hydrate_as_schedule_rows(c.fetchall())
            c.execute(
                "SELECT * FROM as_trigger_events WHERE enrollment_id = ? ORDER BY detected_date DESC, id DESC",
                (enrollment_id,),
            )
            as_trigger_events = _hydrate_as_trigger_rows(c.fetchall())
            c.execute(
                "SELECT * FROM as_conversion_events WHERE enrollment_id = ? ORDER BY conversion_date DESC, id DESC",
                (enrollment_id,),
            )
            as_conversion_events = [dict(row) for row in c.fetchall()]
            active_surveillance_protocol = _build_active_surveillance_protocol_block(
                current_as_enrollment,
                as_schedule_items,
                as_trigger_events,
                as_conversion_events,
            )

        c.execute(
            "SELECT * FROM skeletal_related_events WHERE patient_id = ? ORDER BY event_date ASC, id ASC",
            (patient_id,),
        )
        structured_skeletal_events = _hydrate_sre_rows(c.fetchall())
        c.execute(
            "SELECT * FROM bone_modifying_agent_courses WHERE patient_id = ? ORDER BY start_date ASC, id ASC",
            (patient_id,),
        )
        bone_modifying_agent_courses = _hydrate_bma_rows(c.fetchall())
        c.execute(
            "SELECT * FROM bone_health_snapshots WHERE patient_id = ? ORDER BY snapshot_date ASC, id ASC",
            (patient_id,),
        )
        bone_health_snapshots = _hydrate_bone_health_rows(c.fetchall())
        skeletal_event_profile = _build_skeletal_event_profile_block(
            structured_skeletal_events,
            bone_modifying_agent_courses,
            bone_health_snapshots,
        )

        c.execute(
            "SELECT * FROM radiotherapy_courses WHERE patient_id = ? ORDER BY rt_start_date ASC, id ASC",
            (patient_id,),
        )
        radiotherapy_course_rows = _hydrate_rt_course_rows(c.fetchall())
        radiotherapy_course_ids = [item.get("id") for item in radiotherapy_course_rows if item.get("id")]
        radiotherapy_courses_detailed = []
        if radiotherapy_course_ids:
            placeholders = ",".join(["?"] * len(radiotherapy_course_ids))
            c.execute(
                f"SELECT * FROM radiotherapy_mdt_sites WHERE course_id IN ({placeholders}) ORDER BY id ASC",
                radiotherapy_course_ids,
            )
            rt_sites = _hydrate_rt_site_rows(c.fetchall())
            c.execute(
                f"SELECT * FROM radiotherapy_toxicities WHERE course_id IN ({placeholders}) ORDER BY id ASC",
                radiotherapy_course_ids,
            )
            rt_toxicities = _hydrate_rt_toxicity_rows(c.fetchall())
            radiotherapy_courses_detailed = _nest_radiotherapy_courses(
                radiotherapy_course_rows,
                rt_sites,
                rt_toxicities,
            )

        # 12. PROs
        c.execute("SELECT * FROM patient_pros WHERE patient_id = ? ORDER BY assessment_date ASC", (patient_id,))
        pros = [dict(row) for row in c.fetchall()]

        # 13. Follow-ups
        c.execute("SELECT * FROM follow_up_visits WHERE patient_id = ? ORDER BY visit_date ASC", (patient_id,))
        follow_ups = _hydrate_followup_rows(c.fetchall())

        # 14. Treatment History
        c.execute("SELECT * FROM treatment_history WHERE patient_id = ? ORDER BY start_date ASC", (patient_id,))
        treatments = _hydrate_treatment_rows(c.fetchall())

        # 15. Prior Clinical History
        c.execute("SELECT * FROM prior_clinical_history WHERE patient_id = ?", (patient_id,))
        prior_history = c.fetchone()

        # 16. Alerts
        c.execute(
            "SELECT * FROM smart_alerts WHERE patient_id = ? AND acknowledged = 0 AND COALESCE(active, 1) = 1 ORDER BY alert_date DESC",
            (patient_id,),
        )
        alerts = _hydrate_alert_rows(c.fetchall())

        # 17. Pivotal Study Matching
        c.execute("SELECT * FROM pivotal_study_matching WHERE patient_id = ? ORDER BY evaluation_date DESC", (patient_id,))
        pivotal_matches = [dict(row) for row in c.fetchall()]

        latest_assessment = _fetch_latest_clinical_assessment(c, patient_id)
        c.execute(
            "SELECT * FROM patient_state_timeline WHERE patient_id = ? ORDER BY created_at ASC, id ASC",
            (patient_id,),
        )
        state_timeline = _hydrate_timeline_rows(c.fetchall())

        c.execute(
            "SELECT * FROM followup_agenda_items WHERE patient_id = ? ORDER BY COALESCE(due_at, ''), id ASC",
            (patient_id,),
        )
        agenda_items = _hydrate_agenda_rows(c.fetchall())

        c.execute(
            "SELECT * FROM scheduled_events WHERE patient_id = ? ORDER BY due_date ASC, id ASC",
            (patient_id,),
        )
        scheduled_events = _hydrate_scheduled_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM stage_visit_records WHERE patient_id = ? ORDER BY visit_date DESC, id DESC",
            (patient_id,),
        )
        stage_visits = _hydrate_stage_visit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM response_assessments WHERE patient_id = ? ORDER BY assessment_date DESC, id DESC",
            (patient_id,),
        )
        response_assessments = _hydrate_response_assessment_rows(c.fetchall())

        c.execute(
            "SELECT * FROM lesion_tracking WHERE patient_id = ? ORDER BY first_detected_date ASC, id ASC",
            (patient_id,),
        )
        lesion_tracking_rows = c.fetchall()
        c.execute(
            '''
            SELECT lm.* FROM lesion_measurements lm
            JOIN lesion_tracking lt ON lt.id = lm.lesion_id
            WHERE lt.patient_id = ?
            ORDER BY lm.measurement_date ASC, lm.id ASC
            ''',
            (patient_id,),
        )
        lesion_measurement_rows = c.fetchall()
        lesion_tracking, lesion_measurements = _hydrate_lesion_rows(lesion_tracking_rows, lesion_measurement_rows)

        c.execute(
            "SELECT * FROM biomarker_longitudinal WHERE patient_id = ? ORDER BY sample_date ASC, id ASC",
            (patient_id,),
        )
        biomarker_longitudinal = _hydrate_biomarker_rows(c.fetchall())

        c.execute(
            "SELECT * FROM data_provenance WHERE patient_id = ? ORDER BY source_date DESC, id DESC",
            (patient_id,),
        )
        data_provenance = _hydrate_provenance_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_events WHERE patient_id = ? ORDER BY event_date DESC, id DESC",
            (patient_id,),
        )
        patient_events = _hydrate_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM clinical_signal_snapshots WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        latest_signal_snapshot = _hydrate_signal_rows(c.fetchall())

        c.execute(
            "SELECT * FROM state_transition_proposals WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        transition_proposals = _hydrate_transition_rows(c.fetchall())

        c.execute(
            "SELECT * FROM recommendation_audit WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC",
            (patient_id,),
        )
        recommendation_audit = _hydrate_recommendation_audit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM clinical_decision_captures WHERE patient_id = ? ORDER BY decision_finalized_at DESC, id DESC",
            (patient_id,),
        )
        clinical_decision_captures = _hydrate_clinical_decision_capture_rows(c.fetchall())

        c.execute(
            "SELECT * FROM tumor_board_outcomes WHERE patient_id = ? ORDER BY discussion_date DESC, id DESC",
            (patient_id,),
        )
        tumor_board_outcomes = _hydrate_tumor_board_outcome_rows(c.fetchall())

        c.execute(
            """
            SELECT * FROM therapeutic_window_events
            WHERE patient_id = ?
            ORDER BY CASE WHEN window_closed_at IS NULL THEN 0 ELSE 1 END ASC,
                     COALESCE(updated_at, created_at, window_opened_at) DESC,
                     id DESC
            """,
            (patient_id,),
        )
        therapeutic_window_events = _hydrate_therapeutic_window_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM treatment_adverse_events WHERE patient_id = ? ORDER BY COALESCE(event_date, '') DESC, id DESC",
            (patient_id,),
        )
        treatment_adverse_events = _hydrate_treatment_adverse_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM outcome_events WHERE patient_id = ? AND COALESCE(active, 1) = 1 ORDER BY COALESCE(event_date, '') DESC, id DESC",
            (patient_id,),
        )
        outcome_events = _hydrate_outcome_rows(c.fetchall())

        c.execute(
            "SELECT * FROM adjudication_snapshots WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        adjudication_snapshots = _hydrate_adjudication_snapshot_rows(c.fetchall())

        c.execute(
            "SELECT * FROM trial_benchmark_snapshots WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        trial_benchmark_snapshots = _hydrate_trial_benchmark_snapshot_rows(c.fetchall())

        c.execute(
            "SELECT * FROM source_documents WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        source_documents = _hydrate_source_document_rows(c.fetchall())

        c.execute(
            '''
            SELECT * FROM document_extraction_candidates
            WHERE patient_id = ?
            ORDER BY document_id DESC, id ASC
            ''',
            (patient_id,),
        )
        document_candidates = _hydrate_document_candidate_rows(c.fetchall())

        c.execute(
            "SELECT * FROM document_verification_tasks WHERE patient_id = ? ORDER BY updated_at DESC, id DESC",
            (patient_id,),
        )
        document_verification_tasks = _hydrate_document_task_rows(c.fetchall())

        c.execute(
            "SELECT * FROM verified_document_facts WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        verified_document_facts = _hydrate_verified_fact_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_clinical_facts WHERE patient_id = ? ORDER BY fact_key ASC, updated_at DESC, id DESC",
            (patient_id,),
        )
        patient_clinical_facts = _hydrate_patient_clinical_fact_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_fact_lineage_events WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        patient_fact_lineage_events = _hydrate_patient_fact_lineage_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_fact_conflicts WHERE patient_id = ? ORDER BY updated_at DESC, created_at DESC, id DESC",
            (patient_id,),
        )
        patient_fact_conflicts = [dict(row) for row in c.fetchall()]

        c.execute(
            "SELECT * FROM patient_consents WHERE patient_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        consent_row = c.fetchone()
        consent_summary = dict(consent_row) if consent_row else {}
        if consent_summary:
            c.execute(
                "SELECT * FROM consent_signature_evidence WHERE consent_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (consent_summary.get("id"),),
            )
            evidence_row = c.fetchone()
            consent_evidence = dict(evidence_row) if evidence_row else {}
            if consent_evidence:
                consent_evidence["audit_metadata"] = _parse_json_blob(consent_evidence.pop("audit_metadata_json", None), {})
            consent_summary["evidence"] = consent_evidence
        else:
            consent_summary = {"status": "missing", "required_for_new_patients": True}

        c.execute(
            "SELECT * FROM operational_outcome_events WHERE patient_id = ? ORDER BY event_date DESC, id DESC",
            (patient_id,),
        )
        operational_outcomes = [dict(row) for row in c.fetchall()]
        for item in operational_outcomes:
            item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})

        c.execute(
            "SELECT * FROM clavien_dindo_events WHERE patient_id = ? ORDER BY surgery_date DESC, id DESC",
            (patient_id,),
        )
        clavien_events = [dict(row) for row in c.fetchall()]
        for item in clavien_events:
            item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})

        c.execute(
            "SELECT * FROM functional_recovery_snapshots WHERE patient_id = ? ORDER BY snapshot_date DESC, id DESC",
            (patient_id,),
        )
        functional_recovery = [dict(row) for row in c.fetchall()]
        for item in functional_recovery:
            item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})

        conn.close()

        identity_dict = dict(identity)
        latest_survival_status = survival_status_rows[0] if survival_status_rows else {}
        identity_dict["vital_status"] = _first_nonempty(
            latest_survival_status.get("vital_status"),
            identity_dict.get("vital_status"),
        )
        identity_dict["date_of_death"] = _first_nonempty(
            latest_survival_status.get("date_of_death"),
            identity_dict.get("date_of_death"),
        )
        identity_dict["cause_of_death"] = _first_nonempty(
            latest_survival_status.get("cause_of_death"),
            identity_dict.get("cause_of_death"),
        )
        identity_dict["last_contact_date"] = _first_nonempty(
            latest_survival_status.get("last_contact_date"),
            identity_dict.get("last_contact_date"),
        )
        identity_dict["last_contact_status"] = _first_nonempty(
            latest_survival_status.get("last_contact_status"),
            identity_dict.get("last_contact_status"),
        )
        identity_dict["death_source"] = _first_nonempty(
            latest_survival_status.get("death_source"),
            identity_dict.get("death_source"),
        )

        biopsy_history = list(biopsies)
        if structured_biopsy_sessions:
            existing_dates = {
                (str(item.get("biopsy_date") or "")[:10], str(item.get("biopsy_context") or ""))
                for item in biopsy_history
                if isinstance(item, dict)
            }
            for session in structured_biopsy_sessions:
                key = (str(session.get("biopsy_date") or "")[:10], str(session.get("biopsy_context") or ""))
                if key not in existing_dates:
                    biopsy_history.append(
                        {
                            "biopsy_date": session.get("biopsy_date"),
                            "biopsy_type": session.get("biopsy_type"),
                            "biopsy_context": session.get("biopsy_context"),
                            "total_cores": session.get("total_cores"),
                            "positive_cores": session.get("total_positive"),
                            "max_core_involvement_pct": session.get("max_involvement_pct"),
                            "isup_grade": session.get("highest_isup"),
                            "systematic_cores": session.get("systematic_cores", []),
                            "targeted_cores": session.get("targeted_cores", []),
                            "targets": session.get("targets", []),
                            "mri_pathology_links": session.get("mri_pathology_links", []),
                            "session_key": session.get("session_key"),
                            "biopsy_route": session.get("biopsy_route"),
                            "mri_pirads_at_biopsy": session.get("mri_pirads_at_biopsy"),
                        }
                    )
            biopsy_history = sorted(biopsy_history, key=lambda item: str(item.get("biopsy_date") or ""))

        active_surveillance_legacy = dict(as_record) if as_record else {}
        if active_surveillance_protocol:
            active_surveillance_legacy.update(
                {
                    "enrollment_date": active_surveillance_protocol.get("enrollment_date"),
                    "enrollment_protocol": active_surveillance_protocol.get("enrollment_protocol"),
                    "current_status": active_surveillance_protocol.get("current_status") or active_surveillance_protocol.get("status"),
                    "exit_date": active_surveillance_protocol.get("exit_date"),
                    "exit_reason": active_surveillance_protocol.get("exit_reason"),
                    "exit_treatment": active_surveillance_protocol.get("exit_treatment"),
                }
            )

        radiation_history = list(radiation)
        if radiotherapy_courses_detailed:
            existing_rt_dates = {
                (str(item.get("rt_date") or item.get("rt_start_date") or "")[:10], str(item.get("rt_context") or item.get("rt_intent") or ""))
                for item in radiation_history
                if isinstance(item, dict)
            }
            for course in radiotherapy_courses_detailed:
                key = (str(course.get("rt_start_date") or "")[:10], str(course.get("rt_intent") or ""))
                if key not in existing_rt_dates:
                    radiation_history.append(
                        {
                            "rt_date": course.get("rt_start_date"),
                            "rt_context": course.get("rt_intent"),
                            "rt_technique": course.get("modality"),
                            "target": course.get("target_volume"),
                            "total_dose_gy": course.get("total_dose_gy"),
                            "fractions": course.get("fractions"),
                            "dose_per_fraction_gy": course.get("dose_per_fraction_gy"),
                            "concurrent_adt": course.get("concurrent_adt"),
                            "toxicity": course.get("toxicity", []),
                            "mdt_site_details": course.get("mdt_site_details", []),
                        }
                    )
            radiation_history = sorted(radiation_history, key=lambda item: str(item.get("rt_date") or item.get("rt_start_date") or ""))

        patient_record = {
            'identity': identity_dict,
            'baseline': baseline_dict,
            'demographics': dict(demographics) if demographics else {},
            'family_history': family_history,
            'imaging': imaging,
            'psma_structured_profile': psma_structured_profile,
            'mri_facts': mri_facts,
            'genomics': dict(genomics) if genomics else {},
            'genomic_reports': genomic_reports,
            'biopsies': biopsy_history,
            'structured_biopsy_sessions': structured_biopsy_sessions,
            'diagnostic_plans': diagnostic_plans,
            'biopsy_triggers': biopsy_triggers,
            'active_surveillance': active_surveillance_legacy,
            'active_surveillance_protocol': active_surveillance_protocol,
            'bcr': dict(bcr) if bcr else {},
            'surgery': dict(surgery) if surgery else {},
            'radiation': radiation_history,
            'radiotherapy_courses_detailed': radiotherapy_courses_detailed,
            'radiotherapy_courses': radiotherapy_courses_detailed,
            'rt_courses': radiotherapy_courses_detailed,
            'pros': pros,
            'follow_ups': follow_ups,
            'treatments': treatments,
            'prior_history': _decorate_prior_history(prior_history),
            'alerts': alerts,
            'pivotal_matches': pivotal_matches,
            'latest_assessment': latest_assessment,
            'state_timeline': state_timeline,
            'care_overlays': _decorate_prior_history(prior_history).get("care_overlays", []),
            'agenda_items': agenda_items,
            'scheduled_events': scheduled_events,
            'stage_visits': stage_visits,
            'response_assessments': response_assessments,
            'lesion_tracking': lesion_tracking,
            'lesion_measurements': lesion_measurements,
            'biomarker_longitudinal': biomarker_longitudinal,
            'psa_series': _derive_psa_series(biomarker_longitudinal, follow_ups, baseline_dict, dict(identity)),
            'testosterone_series': _derive_testosterone_series(biomarker_longitudinal, follow_ups, baseline_dict, dict(identity)),
            'data_provenance': data_provenance,
            'patient_events': patient_events,
            'latest_signal_snapshot': latest_signal_snapshot[0] if latest_signal_snapshot else {},
            'transition_proposals': transition_proposals,
            'recommendation_audit': recommendation_audit,
            'clinical_decision_captures': clinical_decision_captures,
            'tumor_board_outcomes': tumor_board_outcomes,
            'therapeutic_window_events': therapeutic_window_events,
            'treatment_adverse_events': treatment_adverse_events,
            'outcome_events': outcome_events,
            'latest_adjudication_snapshot': adjudication_snapshots[0] if adjudication_snapshots else {},
            'latest_trial_benchmark_snapshot': trial_benchmark_snapshots[0] if trial_benchmark_snapshots else {},
            'source_documents': source_documents,
            'document_candidates': document_candidates,
            'document_verification_tasks': document_verification_tasks,
            'verified_document_facts': verified_document_facts,
            'patient_clinical_facts': patient_clinical_facts,
            'patient_fact_lineage_events': patient_fact_lineage_events,
            'patient_fact_conflicts': patient_fact_conflicts,
            'survival_status_detail': latest_survival_status,
            'survival_status_history': survival_status_rows,
            'survival_anchor_events': survival_anchor_events,
            'vital_status': identity_dict.get("vital_status") or latest_survival_status.get("vital_status"),
            'date_of_death': identity_dict.get("date_of_death") or latest_survival_status.get("date_of_death"),
            'cause_of_death': identity_dict.get("cause_of_death") or latest_survival_status.get("cause_of_death"),
            'last_contact_date': identity_dict.get("last_contact_date") or latest_survival_status.get("last_contact_date"),
            'last_contact_status': identity_dict.get("last_contact_status") or latest_survival_status.get("last_contact_status"),
            'skeletal_event_profile': skeletal_event_profile,
            'skeletal_events': structured_skeletal_events,
            'sre_events': structured_skeletal_events,
            'bone_modifying_agent_courses': bone_modifying_agent_courses,
            'bone_modifying_agent': bone_modifying_agent_courses[-1] if bone_modifying_agent_courses else {},
            'bone_health_snapshots': bone_health_snapshots,
            'bone_health': bone_health_snapshots[-1] if bone_health_snapshots else {},
            'radiation_details': radiotherapy_courses_detailed,
            'consent_summary': consent_summary,
            'consent_evidence': consent_summary.get("evidence", {}),
            'operational_outcomes': operational_outcomes,
            'clavien_dindo_events': clavien_events,
            'functional_recovery_snapshots': functional_recovery,
        }
        testosterone_series = patient_record.get("testosterone_series") or []
        testosterone_candidates = [
            point
            for point in testosterone_series
            if _is_present(point.get("sample_date")) and point.get("value") is not None
        ]
        followup_testosterone_candidates = [
            point
            for point in testosterone_candidates
            if str(point.get("entry_origin") or "").strip() == "follow_up_visit"
        ]
        if followup_testosterone_candidates:
            testosterone_candidates = followup_testosterone_candidates
        non_baseline_testosterone_candidates = [
            point
            for point in testosterone_candidates
            if str(point.get("context") or "").strip().lower()
            not in {"baseline", "diagnostic", "pretratamiento", "pretreatment"}
        ]
        if non_baseline_testosterone_candidates:
            testosterone_candidates = non_baseline_testosterone_candidates
        latest_testosterone_point = max(
            testosterone_candidates,
            key=lambda point: str(point.get("sample_date") or ""),
            default={},
        )
        patient_record["latest_testosterone_value"] = latest_testosterone_point.get("value")
        patient_record["latest_testosterone_date"] = latest_testosterone_point.get("sample_date") or ""
        if not include_derivatives:
            return patient_record
        return build_patient_record_derivatives(
            patient_record,
            include_ledger=include_ledger,
        )
    except Exception as e:
        logger.error(f"Error fetching full patient record: {e}")
        return None


def load_patient_record_core(nss_or_id, *, include_ledger=False):
    return get_patient_full_record(
        nss_or_id,
        include_derivatives=False,
        include_ledger=include_ledger,
    )


def build_patient_record_derivatives(record, *, include=None, include_ledger=True):
    if not record:
        return record
    patient_record = dict(record)
    latest_assessment = dict(patient_record.get("latest_assessment") or {})
    prior_history = _decorate_prior_history(patient_record.get("prior_history"))
    patient_record["prior_history"] = prior_history

    from prostanet.domains.patient_tracking.clinical_kernel_snapshot_builder import (
        build_patient_kernel_snapshot,
    )
    from prostanet.domains.patient_tracking.clinical_ledger_builder import (
        attach_patient_clinical_ledger_histories,
        build_patient_clinical_ledger_bundle,
    )
    from prostanet.domains.patient_tracking.governance_read_model_builder import (
        build_patient_governance_context,
    )
    from prostanet.domains.patient_tracking.schedule_read_model_builder import (
        build_patient_schedule_context,
    )

    kernel_snapshot = build_patient_kernel_snapshot(
        patient_record,
        latest_assessment=latest_assessment,
    )
    patient_record.update(kernel_snapshot)
    reconciliation = dict(kernel_snapshot.get("reconciliation") or {})
    state = (
        reconciliation.get("reconciled_state")
        or latest_assessment.get("state")
        or prior_history.get("current_state")
        or "diagnostic_workup"
    )
    patient_record.update(
        build_patient_schedule_context(
            patient_record,
            latest_assessment=latest_assessment,
            reconciliation=reconciliation,
        )
    )
    patient_record.update(
        build_patient_governance_context(
            patient_record,
            latest_assessment=latest_assessment,
            reconciliation=reconciliation,
            longitudinal_truth_snapshot=patient_record.get("longitudinal_truth_snapshot") or {},
        )
    )
    patient_record["clinical_ledger_bundle"] = build_patient_clinical_ledger_bundle(patient_record)
    if include_ledger:
        patient_record = attach_patient_clinical_ledger_histories(patient_record)
    return patient_record


def get_patient_state_timeline(nss_or_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return None
        c.execute(
            "SELECT * FROM patient_state_timeline WHERE patient_id = ? ORDER BY created_at ASC, id ASC",
            (identity["id"],),
        )
        rows = _hydrate_timeline_rows(c.fetchall())
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error fetching patient state timeline: {e}")
        return None


def recompute_patient_care_plan(nss_or_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return False, "Paciente no encontrado"

        patient_id = identity["id"]
        assessment = _fetch_latest_clinical_assessment(c, patient_id)
        if not assessment:
            conn.close()
            return False, "No existe una evaluación clínica modular para este paciente"

        from prostanet.application.module_registry import ModuleRegistry

        registry = ModuleRegistry()
        from prostanet.domains.patient_tracking.event_graph import (
            build_processing_summary,
            derive_management_intent_status,
            derive_timeline_event_kind,
            merge_record_into_assessment_payload,
        )

        record = get_patient_full_record(patient_id)
        enriched_payload = merge_record_into_assessment_payload(
            assessment.get("input_snapshot", {}),
            _build_runtime_neutral_patient_record(record),
        )
        updated_result = registry.evaluate_module(assessment["module_id"], enriched_payload)
        updated_guidelines = registry.get_guidelines_metadata()
        c.execute(
            '''
            UPDATE clinical_assessments
            SET state = ?, input_snapshot = ?, result_snapshot = ?, guideline_versions = ?, status = ?
            WHERE id = ?
            ''',
            (
                updated_result.get("state", assessment.get("state")),
                _json_blob(enriched_payload),
                _json_blob(updated_result),
                _json_blob(updated_guidelines),
                assessment.get("status", "linked"),
                assessment["id"],
            ),
        )
        assessment["state"] = updated_result.get("state", assessment.get("state"))
        assessment["input_snapshot"] = enriched_payload
        assessment["result_snapshot"] = updated_result
        assessment["guideline_versions"] = updated_guidelines
        snapshot = _assessment_longitudinal_snapshot(assessment)
        processing = build_processing_summary(assessment.get("state"), enriched_payload, record)
        management_intent_status = derive_management_intent_status(assessment.get("state"), updated_result, record)
        event_kind = derive_timeline_event_kind(assessment.get("state"), updated_result, record)
        _ensure_prior_history_row(c, patient_id)
        c.execute(
            '''
            UPDATE prior_clinical_history
            SET latest_assessment_id = ?,
                assessment_source = ?,
                assessment_module = ?,
                assessment_state = ?,
                assessment_summary = ?,
                recommendation_family = ?,
                management_intent_status = ?,
                current_state = ?,
                transition_reason = ?,
                objective_progression_json = ?,
                monitoring_plan_json = ?,
                care_overlays_json = ?,
                latest_guideline_snapshot_json = ?
            WHERE patient_id = ?
            ''',
            (
                assessment["id"],
                "clinical_wizard",
                assessment.get("module_id"),
                assessment.get("state"),
                snapshot["summary"],
                snapshot.get("recommendation_family", ""),
                management_intent_status,
                snapshot["current_state"],
                snapshot["transition_reason"],
                _json_blob(snapshot["objective_progression"]),
                _json_blob(snapshot["monitoring_plan"]),
                _json_blob(snapshot["care_overlays"]),
                _json_blob({
                    **snapshot["guideline_snapshot"],
                    "decision_quality": snapshot.get("decision_quality", {}),
                    "validated_algorithms": snapshot.get("validated_algorithms", []),
                    "processing_summary": processing,
                }),
                patient_id,
            ),
        )
        _record_patient_state_transition(
            c,
            patient_id,
            assessment["id"],
            assessment.get("state"),
            event_kind,
            management_intent_status,
            f"Recomputación longitudinal: {snapshot['transition_reason']}",
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            {
                **snapshot["guideline_snapshot"],
                "decision_quality": snapshot.get("decision_quality", {}),
                "validated_algorithms": snapshot.get("validated_algorithms", []),
                "processing_summary": processing,
            },
        )
        conn.commit()
        conn.close()
        return True, assessment
    except Exception as e:
        import traceback as _tb
        logger.error(f"Error recomputing patient care plan: {e}\n{''.join(_tb.format_exception(e))}")
        return False, str(e)


def check_and_generate_alerts(patient_id):
    """Recalcula y persiste la salida canónica de alertas del copiloto."""
    try:
        bundle = refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return [alert.get("alert_key") or alert.get("title") for alert in bundle.get("copilot_alerts", [])]
    except Exception as e:
        logger.error(f"Error generating canonical alerts: {e}")
        return []


def export_patient_data(nss, format='dict'):
    """
    Exporta datos completos del paciente para análisis.
    format: 'dict' para Python, 'json' para JSON string, 'csv_ready' para lista plana
    """
    record = get_patient_full_record(nss)
    if not record:
        return None

    if format == 'json':
        return json.dumps(record, indent=2, default=str, ensure_ascii=False)
    elif format == 'csv_ready':
        # Flatten para CSV
        flat = {}
        flat.update({f"id_{k}": v for k, v in record.get('identity', {}).items()})
        flat.update({f"demo_{k}": v for k, v in record.get('demographics', {}).items()})
        flat.update({f"base_{k}": v for k, v in record.get('baseline', {}).items()})
        flat.update({f"gen_{k}": v for k, v in record.get('genomics', {}).items()})
        flat.update({f"surg_{k}": v for k, v in record.get('surgery', {}).items()})
        flat.update({f"as_{k}": v for k, v in record.get('active_surveillance', {}).items()})
        flat.update({f"bcr_{k}": v for k, v in record.get('bcr', {}).items()})
        flat['n_followups'] = len(record.get('follow_ups', []))
        flat['n_biopsies'] = len(record.get('biopsies', []))
        flat['n_imaging'] = len(record.get('imaging', []))
        flat['n_mri_facts'] = len(record.get('mri_facts', []))
        flat['n_diagnostic_plans'] = len(record.get('diagnostic_plans', []))
        flat['n_biopsy_triggers'] = len(record.get('biopsy_triggers', []))
        flat['n_treatments'] = len(record.get('treatments', []))
        flat['n_alerts'] = len(record.get('alerts', []))
        return flat
    else:
        return record


def save_pivotal_matching(patient_id, match_data):
    """Guarda resultado de matching con estudio pivotal."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO pivotal_study_matching (
                patient_id, study_name, eligible, eligibility_details,
                study_arm, expected_outcome, applicability_to_patient
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            match_data.get('study_name', match_data.get('name', '')),
            int(match_data.get('eligible', False)),
            json.dumps(match_data.get('criteria_details', match_data.get('eligibility_details', {}))),
            match_data.get('study_arm', 'experimental'),
            match_data.get('expected_outcome', match_data.get('key_result', '')),
            match_data.get('applicability', match_data.get('applicability_to_patient', ''))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving pivotal matching: {e}")
        return False


if __name__ == "__main__":
    init_tracking_db()
