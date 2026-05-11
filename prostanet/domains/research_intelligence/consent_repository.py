from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


DEFAULT_CONSENT_TEXT = """
CONSENTIMIENTO INFORMADO PARA USO SECUNDARIO DE DATOS CLÍNICOS

Autorizo que la información clínica capturada en ProstaNet pueda utilizarse de forma
institucional para investigación observacional, mejora de calidad, auditoría clínica y
generación de métricas epidemiológicas, manteniendo controles de confidencialidad,
trazabilidad y gobernanza de acceso. Esta autorización no modifica por sí misma mis
decisiones terapéuticas ni sustituye el consentimiento clínico para procedimientos.
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_current_consent_version() -> dict[str, Any]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM consent_versions
        WHERE active = 1
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            """
            INSERT INTO consent_versions (
                version_code, title, consent_text, html_snapshot, effective_at, active
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                "2026.1",
                "Consentimiento institucional de uso secundario de datos",
                DEFAULT_CONSENT_TEXT.strip(),
                DEFAULT_CONSENT_TEXT.strip().replace("\n", "<br>"),
                _now_iso(),
            ),
        )
        conn.commit()
        cursor.execute(
            """
            SELECT * FROM consent_versions
            WHERE active = 1
            ORDER BY effective_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
    conn.close()
    return dict(row)


def create_intake_draft(payload: dict[str, Any], *, source_context: str = "wizard") -> dict[str, Any]:
    version = ensure_current_consent_version()
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO patient_intake_drafts (
            source_context, nss, full_name, assessment_id, payload_json, status, consent_version_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            source_context,
            str(payload.get("nss", "")).strip(),
            str(payload.get("full_name", "")).strip(),
            payload.get("assessment_id"),
            json.dumps(payload, ensure_ascii=False, default=str),
            version["version_code"],
            _now_iso(),
            _now_iso(),
        ),
    )
    draft_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "draft_id": int(draft_id),
        "status": "draft",
        "consent_version": _serialize_consent_version(version),
    }


def get_intake_draft(draft_id: int) -> dict[str, Any] | None:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patient_intake_drafts WHERE id = ?", (int(draft_id),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    draft = dict(row)
    draft["payload"] = json.loads(draft.pop("payload_json", "{}") or "{}")
    version = ensure_current_consent_version()
    if draft.get("consent_version_code"):
        draft["consent_version"] = _serialize_consent_version(version) if draft["consent_version_code"] == version["version_code"] else {"version_code": draft["consent_version_code"]}
    return draft


def sign_intake_draft(
    draft_id: int,
    *,
    signer_name: str,
    signature_data_url: str,
    accepted: bool,
    audit_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = get_intake_draft(draft_id)
    if not draft:
        raise ValueError("Borrador de ingreso no encontrado.")
    if not accepted:
        raise ValueError("Debe aceptar el consentimiento para continuar.")
    version = ensure_current_consent_version()
    signer_name = str(signer_name or "").strip()
    if not signer_name:
        raise ValueError("Se requiere el nombre del paciente para firmar el consentimiento.")
    signature_data_url = str(signature_data_url or "").strip()
    if not signature_data_url.startswith("data:image/"):
        raise ValueError("La firma electrónica es obligatoria.")
    signed_at = _now_iso()
    content_hash = hashlib.sha256(
        f"{version['version_code']}|{version['consent_text']}|{draft['nss']}|{signer_name}|{signed_at}|{signature_data_url}".encode("utf-8")
    ).hexdigest()
    evidence = {
        "version_code": version["version_code"],
        "signer_name": signer_name,
        "signed_at": signed_at,
        "signature_data_url": signature_data_url,
        "content_hash": content_hash,
        "audit_metadata": dict(audit_metadata or {}),
    }
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE patient_intake_drafts
        SET status = 'signed', signature_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(evidence, ensure_ascii=False, default=str), _now_iso(), int(draft_id)),
    )
    conn.commit()
    conn.close()
    return {
        "draft_id": int(draft_id),
        "status": "signed",
        "evidence": evidence,
        "consent_version": _serialize_consent_version(version),
    }


def finalize_intake_draft(draft_id: int) -> dict[str, Any]:
    draft = get_intake_draft(draft_id)
    if not draft:
        raise ValueError("Borrador de ingreso no encontrado.")
    evidence = json.loads(draft.get("signature_json") or "{}")
    if not evidence.get("signature_data_url"):
        raise ValueError("No es posible abrir expediente sin consentimiento firmado.")
    payload = dict(draft.get("payload") or {})
    assessment = None
    if payload.get("assessment_id") not in (None, ""):
        from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

        assessment = ClinicalAssessmentService().get_draft(int(float(payload["assessment_id"])))
    patient_id, message, _registration_metadata = tracking_db.register_new_patient(payload, assessment=assessment)
    if patient_id is None:
        raise ValueError(message or "No fue posible registrar al paciente.")
    if assessment and payload.get("assessment_id") not in (None, ""):
        from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

        ClinicalAssessmentService().attach_to_patient(int(float(payload["assessment_id"])), int(patient_id))
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO patient_consents (
            patient_id, consent_version_code, status, signer_name, signed_at, content_hash, created_at
        ) VALUES (?, ?, 'signed', ?, ?, ?, ?)
        """,
        (
            int(patient_id),
            evidence.get("version_code"),
            evidence.get("signer_name"),
            evidence.get("signed_at"),
            evidence.get("content_hash"),
            _now_iso(),
        ),
    )
    consent_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO consent_signature_evidence (
            patient_id, consent_id, signature_data_url, evidence_html, audit_metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(patient_id),
            int(consent_id),
            evidence.get("signature_data_url"),
            build_signature_html_snapshot(draft, evidence),
            json.dumps(evidence.get("audit_metadata") or {}, ensure_ascii=False, default=str),
            _now_iso(),
        ),
    )
    cursor.execute(
        """
        UPDATE patient_intake_drafts
        SET status = 'finalized', patient_id = ?, finalized_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (int(patient_id), _now_iso(), _now_iso(), int(draft_id)),
    )
    conn.commit()
    conn.close()
    return {
        "patient_id": int(patient_id),
        "message": message,
        "consent": get_patient_consent_summary(int(patient_id)),
    }


def build_signature_html_snapshot(draft: dict[str, Any], evidence: dict[str, Any]) -> str:
    version = ensure_current_consent_version()
    return (
        f"<h2>{version['title']}</h2>"
        f"<p><strong>Paciente:</strong> {draft.get('full_name') or draft.get('nss')}</p>"
        f"<p><strong>Versión:</strong> {version['version_code']}</p>"
        f"<p><strong>Fecha:</strong> {evidence.get('signed_at')}</p>"
        f"<div>{version['consent_text'].strip().replace(chr(10), '<br>')}</div>"
        f"<img alt='Firma del paciente' src='{evidence.get('signature_data_url')}' style='max-width:320px;border:1px solid #ccc;border-radius:12px;margin-top:12px;'/>"
    )


def get_patient_consent_summary(patient_id: int) -> dict[str, Any]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM patient_consents
        WHERE patient_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (int(patient_id),),
    )
    consent_row = cursor.fetchone()
    if not consent_row:
        conn.close()
        return {"status": "missing", "required_for_new_patients": True}
    consent = dict(consent_row)
    cursor.execute(
        """
        SELECT * FROM consent_signature_evidence
        WHERE consent_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (int(consent["id"]),),
    )
    evidence_row = cursor.fetchone()
    conn.close()
    evidence = dict(evidence_row) if evidence_row else {}
    if evidence:
        evidence["audit_metadata"] = json.loads(evidence.pop("audit_metadata_json", "{}") or "{}")
    consent["evidence"] = evidence
    consent["required_for_new_patients"] = True
    return consent


def _serialize_consent_version(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "version_code": version.get("version_code"),
        "title": version.get("title"),
        "consent_text": version.get("consent_text"),
        "html_snapshot": version.get("html_snapshot"),
        "effective_at": version.get("effective_at"),
    }
