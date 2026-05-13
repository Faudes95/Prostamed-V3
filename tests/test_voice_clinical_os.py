# IEC 62304 §5.7 (software system testing).

import sqlite3
import io
import json
from pathlib import Path


def _seed_patient(db_path, nss="VOICE-001"):
    import tracking_db

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date) VALUES (?, ?, ?, DATE('now'))",
        (nss, "Paciente Voz Segura", "1958-02-03"),
    )
    patient_id = cur.lastrowid
    cur.execute(
        "INSERT INTO clinical_baseline (patient_id, baseline_psa, testosterone_baseline, tnm_stage) VALUES (?, ?, ?, ?)",
        (patient_id, 1.2, 410, "TxNxMx"),
    )
    conn.commit()
    conn.close()
    return nss, patient_id


def test_voice_os_requires_consent_before_review(app_client):
    client, db_path = app_client
    nss, _patient_id = _seed_patient(db_path)

    created = client.post(f"/api/patients/{nss}/voice/encounters", json={"ui_surface": "test"}).get_json()
    assert created["success"] is True

    session_key = created["session"]["session_key"]
    blocked = client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/review",
        json={"transcript_text": "PSA 3.2 el 2026-05-11"},
    )
    assert blocked.status_code == 400
    assert blocked.get_json()["error"] == "voice_consent_required"


def test_voice_os_review_commit_writes_only_accepted_biomarkers(app_client):
    client, db_path = app_client
    nss, patient_id = _seed_patient(db_path, nss="VOICE-002")

    created = client.post(f"/api/patients/{nss}/voice/encounters", json={"ui_surface": "test"}).get_json()
    session_key = created["session"]["session_key"]

    consent = client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )
    assert consent.status_code == 200
    assert consent.get_json()["session"]["consent_status"] == "signed"

    review = client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/review",
        json={
            "transcript_text": "APE 4.2 ng/mL el 2026-05-11 y testosterona 38 ng/dL. ECOG 1.",
        },
    )
    assert review.status_code == 200
    body = review.get_json()
    candidates = body["candidates"]
    assert {item["field_name"] for item in candidates} >= {"psa", "testosterone", "ecog"}

    accepted = [item["candidate_key"] for item in candidates if item["field_name"] in {"psa", "testosterone"}]
    committed = client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/commit",
        json={"accepted_candidate_keys": accepted, "verified_by": "Dr Test"},
    )
    assert committed.status_code == 200
    committed_body = committed.get_json()
    assert committed_body["session"]["status"] == "signed"
    assert len(committed_body["write_results"]) == 2

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT biomarker_type, value, sample_date, lab_source FROM biomarker_longitudinal WHERE patient_id = ? ORDER BY id ASC",
        (patient_id,),
    )
    rows = cur.fetchall()
    cur.execute("SELECT transcript_envelope_json FROM voice_transcript_segments")
    encrypted_blob = cur.fetchone()[0]
    cur.execute("SELECT event_type FROM patient_events WHERE patient_id = ? ORDER BY id ASC", (patient_id,))
    events = [row[0] for row in cur.fetchall()]
    conn.close()

    assert [row[0] for row in rows] == ["PSA", "TESTOSTERONA"]
    assert rows[0][1] == 4.2
    assert rows[1][1] == 38
    assert "APE 4.2" not in encrypted_blob
    assert "voice_encounter_committed" in events


def test_voice_os_audio_upload_is_encrypted_and_local_first(app_client, monkeypatch):
    monkeypatch.setenv("VOICE_STT_DISABLE", "1")
    client, db_path = app_client
    nss, _patient_id = _seed_patient(db_path, nss="VOICE-003")

    created = client.post(f"/api/patients/{nss}/voice/encounters", json={"ui_surface": "test"}).get_json()
    session_key = created["session"]["session_key"]
    client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/consent",
        json={"spoken_text": "Autorizo la captura clínica por voz en ProstaMed."},
    )

    payload = b"not-a-real-audio-but-sensitive-raw-bytes"
    uploaded = client.post(
        f"/api/patients/{nss}/voice/encounters/{session_key}/audio",
        data={"audio": (io.BytesIO(payload), "voice.webm"), "transcribe": "true"},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    body = uploaded.get_json()
    assert body["audio"]["stored"] is True
    assert body["audio"]["encrypted"] is True
    assert body["audio"]["transcription_status"] in {"requires_local_stt", "stt_error", "empty_transcript", "transcribed"}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT encrypted_audio_path FROM voice_encounter_sessions WHERE session_key = ?", (session_key,))
    encrypted_path = cur.fetchone()[0]
    conn.close()

    stored = Path(encrypted_path)
    assert stored.exists()
    stored_payload = json.loads(stored.read_text(encoding="utf-8"))
    assert stored_payload["envelope"]["algorithm"] == "AES-256-GCM"
    assert "sensitive-raw-bytes" not in stored.read_text(encoding="utf-8")


def test_voice_os_templates_are_visible():
    profile = Path("templates/patient_profile_v2.html").read_text(encoding="utf-8")
    longitudinal = Path("templates/demos/longitudinal_capture_v2_demo.html").read_text(encoding="utf-8")
    hub = Path("templates/demos/stage_clinical_center_v2_redesign.html").read_text(encoding="utf-8")
    js = Path("static/js/prostamed_voice_os.js").read_text(encoding="utf-8")

    assert "Cortana clínica" in profile
    assert "data-pm2-voice-os" in profile
    assert "data-pm2-voice-os" in longitudinal
    assert "Cortana clínica de ingreso" in hub
    assert 'data-voice-mode="intake"' in hub
    assert 'data-voice-action="record"' in profile
    assert 'data-voice-action="stop"' in longitudinal
    assert 'data-voice-action="apply"' in hub
    assert 'data-voice-action="toggle-auto"' in hub
    assert 'data-voice-action="undo"' in hub
    assert 'data-voice-change-log' in hub
    assert "pm2-btn-icon" in hub
    assert "● Grabar" not in hub
    assert "■ Detener" not in hub
    assert "/audio" in js
    assert "/api/clinical-hub/voice/encounters" in js
    assert "/voice/encounters" in js
    assert "accepted_candidate_keys" in js
    assert "partial_audio_buffering" in js
    assert "recorder.start()" in js
    assert "recorder.stop()" in js
    assert "transcribiendo audio final" in js
    assert "prostanet:voice-intake-undo" in js


def test_voice_os_permissions_policy_allows_microphone_only_on_voice_surfaces(app_client):
    client, db_path = app_client
    nss, _patient_id = _seed_patient(db_path, nss="VOICE-004")

    hub = client.get("/clinical-hub")
    profile = client.get(f"/patient_profile/{nss}?v=2")
    patients = client.get("/patients")

    assert "microphone=(self)" in hub.headers["Permissions-Policy"]
    assert "microphone=(self)" in profile.headers["Permissions-Policy"]
    assert "microphone=()" in patients.headers["Permissions-Policy"]


def test_clinical_hub_voice_intake_review_apply_does_not_require_patient(app_client):
    client, _db_path = app_client

    created = client.post("/api/clinical-hub/voice/encounters", json={"ui_surface": "clinical_hub_classifier"})
    assert created.status_code == 200
    session_id = created.get_json()["session"]["session_id"]

    consent = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )
    assert consent.status_code == 200

    review = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/review",
        json={
            "transcript_text": (
                "Adenocarcinoma confirmado. PSA basal 12.4 el 2026-05-11, "
                "Gleason 4+3, cT2c cN0 M0. Paciente bajo ADT con testosterona 38."
            )
        },
    )
    assert review.status_code == 200
    candidates = review.get_json()["candidates"]
    fields = {item["field_name"] for item in candidates}
    assert {"known_cancer_diagnosis", "psa_baseline_ng_ml", "gleason_primary", "gleason_secondary", "clinical_tstage", "nodal_status", "testosterone_value"} <= fields

    accepted = [item["candidate_key"] for item in candidates]
    applied = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/apply",
        json={"accepted_candidate_keys": accepted},
    )
    assert applied.status_code == 200
    body = applied.get_json()
    assert body["fields"]["known_cancer_diagnosis"] == "1"
    assert body["fields"]["psa_baseline_ng_ml"] == 12.4
    assert body["fields"]["gleason_primary"] == "4"
    assert body["fields"]["gleason_secondary"] == "3"
    assert body["fields"]["clinical_tstage"] == "cT2c"
    assert body["fields"]["nodal_status"] == "N0"
    assert body["provenance"]["source"] == "clinical_hub_voice_intake"


def test_intake_voice_extractor_respects_negated_diagnosis():
    from prostanet.voice.intent_extractor import extract_intake_classifier_candidates

    candidates = extract_intake_classifier_candidates(
        "Sin diagnóstico confirmado, sospecha clínica por APE 8.2, biopsia programada.",
        session_key="intake-test-negated",
    )
    known_values = [item["value"] for item in candidates if item["field_name"] == "known_cancer_diagnosis"]
    field_names = {item["field_name"] for item in candidates}

    assert known_values == ["0"]
    assert "diagnosis_date" not in field_names
    assert "biopsy_scheduled" in field_names
    assert not any(item["field_name"] == "known_cancer_diagnosis" and item["value"] == "1" for item in candidates)


def test_intake_voice_extractor_biopsy_negative_is_prediagnostic():
    from prostanet.voice.intent_extractor import extract_intake_classifier_candidates

    candidates = extract_intake_classifier_candidates(
        "Paciente con biopsia negativa y seguimiento por PSA 5.4.",
        session_key="intake-test-negative-biopsy",
    )
    fields = {item["field_name"]: item["value"] for item in candidates}

    assert fields["known_cancer_diagnosis"] == "0"
    assert fields["prior_negative_biopsy"] == "1"
    assert fields.get("histology_subtype") is None


def test_intake_voice_extractor_positive_classifier_fields_without_implicit_date():
    from prostanet.voice.intent_extractor import extract_intake_classifier_candidates

    candidates = extract_intake_classifier_candidates(
        "Adenocarcinoma confirmado. PSA basal 12.4, Gleason 4+3, cT2c cN0 M0, testosterona 38.",
        session_key="intake-test-positive",
    )
    fields = {item["field_name"]: item["value"] for item in candidates}

    assert fields["known_cancer_diagnosis"] == "1"
    assert fields["psa_baseline_ng_ml"] == 12.4
    assert fields["gleason_primary"] == "4"
    assert fields["gleason_secondary"] == "3"
    assert fields["clinical_tstage"] == "cT2c"
    assert fields["nodal_status"] == "N0"
    assert fields["metastasis_site"] == "M0"
    assert fields["testosterone_value"] == 38
    assert fields["castrate_testosterone_status"] == "confirmed_castrate"
    assert "diagnosis_date" not in fields


def test_clinical_hub_voice_review_negation_returns_no_contradiction(app_client):
    client, _db_path = app_client

    created = client.post("/api/clinical-hub/voice/encounters", json={"ui_surface": "clinical_hub_classifier"})
    session_id = created.get_json()["session"]["session_id"]
    client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )

    review = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/review",
        json={"transcript_text": "No hay diagnóstico confirmado; sospecha clínica por APE alto."},
    )
    assert review.status_code == 200
    body = review.get_json()

    assert body["fields"]["known_cancer_diagnosis"] == "0"
    assert not any(
        item["field_name"] == "known_cancer_diagnosis" and item["value"] == "1"
        for item in body["candidates"]
    )
    assert body["transcript_full"].startswith("No hay diagnóstico confirmado")


def test_clinical_hub_voice_audio_chunk_contract_is_non_persistent(app_client, monkeypatch):
    monkeypatch.setenv("VOICE_STT_DISABLE", "1")
    client, _db_path = app_client

    created = client.post("/api/clinical-hub/voice/encounters", json={"ui_surface": "clinical_hub_classifier"})
    session_id = created.get_json()["session"]["session_id"]
    client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )

    uploaded = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/audio",
        data={
            "audio": (io.BytesIO(b"fake-webm-chunk"), "voice.webm"),
            "transcribe": "true",
            "chunk_index": "3",
            "final": "false",
            "auto_apply": "true",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    body = uploaded.get_json()
    assert body["audio"]["stored"] is True
    assert body["audio"]["encrypted"] is True
    assert body["audio"]["transcription_status"] == "requires_local_stt"
    assert body["chunk_index"] == "3"
    assert body["final"] is False
    assert body["fields"] == {}


def test_clinical_hub_voice_partial_decode_buffers_instead_of_stt_error(app_client, monkeypatch):
    from prostanet.voice.stt_engine import LocalSTTEngine

    client, _db_path = app_client
    monkeypatch.delenv("VOICE_STT_DISABLE", raising=False)
    monkeypatch.setattr(LocalSTTEngine, "is_available", lambda self: True)

    def _raise_decode_error(self, *args, **kwargs):
        raise RuntimeError("stt_transcription_failed:InvalidDataError")

    monkeypatch.setattr(LocalSTTEngine, "transcribe_bytes", _raise_decode_error)

    created = client.post("/api/clinical-hub/voice/encounters", json={"ui_surface": "clinical_hub_classifier"})
    session_id = created.get_json()["session"]["session_id"]
    client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )

    partial = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/audio",
        data={
            "audio": (io.BytesIO(b"partial-webm-chunk"), "voice.webm"),
            "transcribe": "true",
            "chunk_index": "1",
            "final": "false",
        },
        content_type="multipart/form-data",
    )
    partial_body = partial.get_json()
    assert partial.status_code == 200
    assert partial_body["audio"]["transcription_status"] == "partial_audio_buffering"
    assert partial_body["audio"]["stt_status_detail"] == "decode_pending"

    final = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/audio",
        data={
            "audio": (io.BytesIO(b"final-webm-chunk"), "voice.webm"),
            "transcribe": "true",
            "chunk_index": "2",
            "final": "true",
        },
        content_type="multipart/form-data",
    )
    final_body = final.get_json()
    assert final.status_code == 200
    assert final_body["audio"]["transcription_status"] == "stt_error"
    assert final_body["audio"]["stt_status_detail"] == "decode_failed"


def test_clinical_hub_voice_final_audio_transcribes_and_prefills(app_client, monkeypatch):
    from prostanet.voice.stt_engine import LocalSTTEngine, TranscriptSegment

    client, _db_path = app_client
    monkeypatch.delenv("VOICE_STT_DISABLE", raising=False)
    monkeypatch.setattr(LocalSTTEngine, "is_available", lambda self: True)
    monkeypatch.setattr(
        LocalSTTEngine,
        "transcribe_bytes",
        lambda self, *args, **kwargs: [
            TranscriptSegment(index=0, text="sin diagnóstico confirmado, sospecha clínica por APE alto")
        ],
    )

    created = client.post("/api/clinical-hub/voice/encounters", json={"ui_surface": "clinical_hub_classifier"})
    session_id = created.get_json()["session"]["session_id"]
    client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/consent",
        json={"spoken_text": "Sí autorizo la captura clínica por voz en ProstaMed."},
    )

    response = client.post(
        f"/api/clinical-hub/voice/encounters/{session_id}/audio",
        data={
            "audio": (io.BytesIO(b"complete-webm-recording"), "voice.webm"),
            "transcribe": "true",
            "chunk_index": "4",
            "final": "true",
            "auto_apply": "true",
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["audio"]["transcription_status"] == "transcribed"
    assert body["transcript_delta"] == "sin diagnóstico confirmado, sospecha clínica por APE alto"
    assert body["fields"]["known_cancer_diagnosis"] == "0"


def test_voice_stt_health_endpoint_reports_local_checks(app_client):
    client, _db_path = app_client

    response = client.get("/api/voice/stt/health")
    assert response.status_code == 200
    body = response.get_json()

    assert body["success"] is True
    assert body["local_first"] is True
    assert {"faster_whisper", "pyav", "ctranslate2"} <= set(body["checks"])
