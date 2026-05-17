"""EPIC 40 — Cortana dictation hub composite endpoint tests.

Verifica que POST /api/voice/cortana-dictation/<patient_nss>:
- Corre los 4 extractores (ECOG/castration/HRR/PSMA-PET) en una sola transcripción
- dry_run mode: retorna extracciones sin escribir DB
- apply mode: persiste captures + computa Trial Matcher diff
- 404 si paciente no existe
- 400 si transcript missing o apply_mode inválido
- Composite cascade end-to-end: rich dictation → 4 captures → newly_eligible trials
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client():
    from app import app, create_app
    create_app()
    return app.test_client()


@pytest.fixture(scope="module")
def test_patient_ref():
    """A patient with m1_crpc state + ARPI active for full cascade test."""
    return "VAL-687e8a23-046"


# ─────────────────── Endpoint registration ───────────────────


class TestEndpointRegistration:
    def test_endpoint_registered(self, client):
        rules = [r.rule for r in client.application.url_map.iter_rules()
                 if 'cortana-dictation' in str(r.rule)]
        assert '/api/voice/cortana-dictation/<patient_ref>' in rules


# ─────────────────── Dry-run extraction ───────────────────


class TestDryRunMode:
    def test_dry_run_with_rich_dictation_extracts_all_4_fields(
        self, client, test_patient_ref
    ):
        dictation = (
            "Paciente con ECOG 2, HRR positivo BRCA2 patogénica, "
            "PSMA-PET positivo metastásico 8 lesiones SUVmax 22, "
            "castración confirmada testosterona 18 ng/dL"
        )
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": dictation, "apply_mode": "dry_run"},
        )
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert b["apply_mode"] == "dry_run"
        assert b["actionable_count"] == 4
        ext = b["extractions"]
        assert ext["ecog"]["value"] == 2
        assert ext["castration"]["status"] == "confirmed_castrate"
        assert ext["hrr"]["status"] == "positive"
        assert ext["hrr"]["gene"] == "BRCA2"
        assert ext["psma_pet"]["status"] == "positive_metastatic"
        assert ext["psma_pet"]["lesion_count"] == 8
        # NO captures_applied or trial_matches_diff in dry_run mode
        assert "captures_applied" not in b
        assert "trial_matches_diff" not in b

    def test_dry_run_partial_dictation(self, client, test_patient_ref):
        """Only some fields detectable in transcript."""
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": "ECOG 1, sin otros cambios", "apply_mode": "dry_run"},
        )
        b = r.get_json()
        assert b["actionable_count"] == 1
        assert b["extractions"]["ecog"]["value"] == 1
        assert b["extractions"]["hrr"]["status"] is None
        assert b["extractions"]["castration"]["status"] is None
        assert b["extractions"]["psma_pet"]["status"] is None

    def test_dry_run_no_signal(self, client, test_patient_ref):
        """Dictation con ningún signal clínico → actionable_count=0."""
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": "Paciente acude para control rutinario.", "apply_mode": "dry_run"},
        )
        b = r.get_json()
        assert b["actionable_count"] == 0


# ─────────────────── Apply mode + trial matcher diff ───────────────────


class TestApplyMode:
    def test_apply_mode_with_full_dictation_unlocks_trials(
        self, client, test_patient_ref
    ):
        """End-to-end compound value cascade:
        Rich dictation → 4 captures → Trial Matcher diff con newly_eligible.

        Patient VAL-687e8a23-046 (m1_crpc + ENZALUTAMIDE active) +
        HRR BRCA2 capture should unlock PROfound and TRITON-3.
        """
        dictation = (
            "Paciente con ECOG 2, HRR positivo BRCA2 patogénica, "
            "PSMA-PET positivo metastásico 12 lesiones SUVmax 25, "
            "castración confirmada testosterona 18"
        )
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": dictation, "apply_mode": "apply"},
        )
        assert r.status_code == 200
        b = r.get_json()
        assert b["success"] is True
        assert b["apply_mode"] == "apply"
        assert b["actionable_count"] == 4
        # 4 captures applied
        assert b["captures_applied_count"] == 4
        # Trial matcher diff present
        diff = b["trial_matches_diff"]
        assert "before_count" in diff
        assert "after_count" in diff
        assert isinstance(diff["newly_eligible"], list)
        # Specific compound-value expectations: BRCA2+ unlocks PROfound/TRITON-3
        # (idempotent: if previously applied, may already be in unchanged_eligible)
        all_eligible_after = set(diff["newly_eligible"]) | set(diff["unchanged_eligible"])
        assert "PROfound" in all_eligible_after, (
            f"HRR BRCA2 capture should unlock PROfound (PARP first-line). "
            f"newly_eligible={diff['newly_eligible']}, "
            f"unchanged_eligible={diff['unchanged_eligible']}"
        )

    def test_apply_persists_captures(self, client, test_patient_ref):
        """Verify that apply mode actually writes to DB via record_*_capture."""
        import tracking_db as _td
        # Reset state with a fresh dictation
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": "ECOG 3, paciente desconditioned", "apply_mode": "apply"},
        )
        b = r.get_json()
        assert b["success"] is True
        # Verify ECOG persisted
        latest = _td.get_latest_ecog_for_patient(test_patient_ref)
        assert latest is not None
        assert latest["value"] == 3


# ─────────────────── Error paths ───────────────────


class TestErrorPaths:
    def test_patient_not_found(self, client):
        r = client.post(
            "/api/voice/cortana-dictation/NONEXISTENT99999",
            json={"transcript": "ECOG 2", "apply_mode": "dry_run"},
        )
        assert r.status_code == 404
        assert r.get_json()["error"] == "patient_not_found"

    def test_missing_transcript(self, client, test_patient_ref):
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "no_transcript_available"

    def test_invalid_apply_mode(self, client, test_patient_ref):
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={"transcript": "ECOG 1", "apply_mode": "force"},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid_apply_mode"
        assert "valid" in r.get_json()


# ─────────────────── Compound value validation ───────────────────


class TestCompoundValueCascade:
    """Verifica que combinaciones específicas de dictation desbloquean trials
    específicos. Documenta los compound-value paths principales."""

    def test_hrr_brca2_unlocks_parp_trials(self, client, test_patient_ref):
        """HRR BRCA2 positive en mCRPC → PROfound + TALAPRO-2 + TRITON-3."""
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={
                "transcript": "HRR positivo BRCA2 patogénica",
                "apply_mode": "apply",
            },
        )
        b = r.get_json()
        diff = b.get("trial_matches_diff", {})
        all_eligible = set(diff.get("newly_eligible", [])) | set(diff.get("unchanged_eligible", []))
        parp_trials = {"PROfound", "TALAPRO-2", "TRITON-3", "MAGNITUDE", "PROpel"}
        assert all_eligible & parp_trials, (
            f"BRCA2 should unlock at least one PARP trial. all_eligible={all_eligible}"
        )

    def test_psma_positive_unlocks_lu177_trials(self, client, test_patient_ref):
        """PSMA-PET positivo metastásico en mCRPC → VISION o PSMAfore (según taxane hx)."""
        r = client.post(
            f"/api/voice/cortana-dictation/{test_patient_ref}",
            json={
                "transcript": "PSMA-PET positivo metastásico, SUVmax 22",
                "apply_mode": "apply",
            },
        )
        b = r.get_json()
        diff = b.get("trial_matches_diff", {})
        all_eligible = set(diff.get("newly_eligible", [])) | set(diff.get("unchanged_eligible", []))
        lu177_trials = {"VISION", "PSMAfore", "TheraP"}
        assert all_eligible & lu177_trials, (
            f"PSMA+ should unlock at least one Lu-177 trial. all_eligible={all_eligible}"
        )
