"""EPIC 36 — Voice quick-capture intent extraction tests.

Cubre los 4 extractores (ECOG/castration/HRR/PSMA-PET) sobre Spanish + EN
dictation samples. Verifica:
- Detección correcta de valores numéricos y palabras (cero/uno/dos)
- Auto-clasificación cuando solo se da una pista (testo<50 → castrate)
- Conservadurismo cuando no hay pista clara (status=None, confidence=0)
- No-fabricación cuando el dictado es ambiguo
"""
from __future__ import annotations

import pytest

from prostanet.voice.quick_capture_intent import (
    extract_castration,
    extract_ecog,
    extract_for_field,
    extract_hrr,
    extract_psma_pet,
    EXTRACTOR_VERSION,
)


# ─────────────────── ECOG ───────────────────


class TestExtractECOG:
    @pytest.mark.parametrize("text,expected", [
        ("ECOG 2", 2),
        ("ecog 0", 0),
        ("ECOG de 1", 1),
        ("ECOG: 3", 3),
        ("performance status 4", 4),
        ("performance status 0", 0),
        ("estado funcional 2", 2),
        ("PS 1", 1),
        ("p.s. 2", 2),
    ])
    def test_numeric_ecog_extracted(self, text, expected):
        r = extract_ecog(text)
        assert r["value"] == expected
        assert r["confidence"] >= 0.85
        assert r["source_pattern"] == "numeric"

    @pytest.mark.parametrize("text,expected", [
        ("ECOG dos", 2),
        ("ECOG cero", 0),
        ("ECOG uno", 1),
        ("ECOG cuatro", 4),
        ("performance status tres", 3),
    ])
    def test_word_ecog_extracted(self, text, expected):
        r = extract_ecog(text)
        assert r["value"] == expected
        assert r["confidence"] >= 0.80
        assert r["source_pattern"] == "word"

    @pytest.mark.parametrize("text", [
        "",
        "el paciente luce bien",
        "ECOG 9",  # out of range — regex requires [0-4]
        "performance score okay",
        "ECOG diecinueve",
    ])
    def test_no_ecog_detected(self, text):
        r = extract_ecog(text)
        assert r["value"] is None
        assert r["confidence"] == 0.0

    def test_long_transcript_with_ecog(self):
        text = "Paciente acude para revisión, refiere astenia leve, ECOG 1, sin pérdida de peso significativa"
        r = extract_ecog(text)
        assert r["value"] == 1
        assert "ecog 1" in r["transcript_excerpt"].lower()


# ─────────────────── Castration ───────────────────


class TestExtractCastration:
    def test_confirmed_castration_explicit(self):
        r = extract_castration("Paciente con castración confirmada")
        assert r["status"] == "confirmed_castrate"
        assert r["confidence"] >= 0.85

    def test_non_castrate(self):
        r = extract_castration("Paciente no castrado, testosterona elevada")
        assert r["status"] == "non_castrate"
        assert r["confidence"] >= 0.80

    def test_pending_castration(self):
        r = extract_castration("Pendiente de castración tras inicio ADT")
        assert r["status"] == "pending"

    def test_testo_value_extracted(self):
        r = extract_castration("Testosterona 22 ng/dL")
        assert r["testosterone_value"] == 22.0
        assert r["testosterone_unit"] == "ng/dL"
        # Auto-infers castrate from value < 50
        assert r["status"] == "confirmed_castrate"

    def test_testo_value_high_infers_non_castrate(self):
        r = extract_castration("Testosterona 280 ng/dl")
        assert r["testosterone_value"] == 280.0
        assert r["status"] == "non_castrate"

    def test_testo_nmol_unit(self):
        r = extract_castration("Testo 1.5 nmol/L")
        assert r["testosterone_value"] == 1.5
        assert r["testosterone_unit"] == "nmol/L"

    def test_status_and_testo_both_present(self):
        r = extract_castration("Castración confirmada, testosterona 18")
        assert r["status"] == "confirmed_castrate"
        assert r["testosterone_value"] == 18.0

    def test_no_castration_signal(self):
        r = extract_castration("Hoy revisamos PSA")
        assert r["status"] is None
        assert r["testosterone_value"] is None


# ─────────────────── HRR ───────────────────


class TestExtractHRR:
    def test_hrr_positive_brca2(self):
        r = extract_hrr("HRR positivo, BRCA2 patogénica")
        assert r["status"] == "positive"
        assert r["gene"] == "BRCA2"
        assert r["confidence"] >= 0.85

    def test_brca1_pathogenic(self):
        r = extract_hrr("Variante patogénica BRCA1 confirmada")
        assert r["status"] == "positive"
        assert r["gene"] == "BRCA1"

    def test_hrr_negative_wild_type(self):
        r = extract_hrr("HRR negativo, wild type")
        assert r["status"] == "negative"

    def test_atm_carrier(self):
        r = extract_hrr("Paciente con variante patogénica en ATM")
        assert r["status"] == "positive"
        assert r["gene"] == "ATM"

    def test_no_test_performed(self):
        r = extract_hrr("No se ha realizado HRR aún")
        assert r["status"] == "not_tested"

    def test_only_gene_no_status(self):
        """Gene name alone without 'positive/negative' context — gene captured,
        status remains None (conservadurismo)."""
        r = extract_hrr("Mutación CDK12 en estudio molecular")
        assert r["gene"] == "CDK12"
        assert r["status"] is None  # No status keyword


# ─────────────────── PSMA-PET ───────────────────


class TestExtractPSMA:
    def test_psma_metastatic_explicit(self):
        r = extract_psma_pet("PSMA-PET positivo metastásico")
        assert r["status"] == "positive_metastatic"
        assert r["confidence"] >= 0.85

    def test_psma_oligometastatic(self):
        r = extract_psma_pet("PSMA PET oligometástasico")
        assert r["status"] == "positive_oligometastatic"

    def test_psma_local_recurrence(self):
        r = extract_psma_pet("PSMA positivo en cama prostática, recurrencia local")
        assert r["status"] == "positive_local_recurrence"

    def test_psma_negative(self):
        r = extract_psma_pet("PSMA-PET negativo, sin actividad PSMA")
        assert r["status"] == "negative"

    def test_lesion_count_extracted(self):
        r = extract_psma_pet("PSMA-PET positivo metastásico, 8 lesiones")
        assert r["status"] == "positive_metastatic"
        assert r["lesion_count"] == 8

    def test_lesion_count_word(self):
        r = extract_psma_pet("PSMA oligometastasico, tres lesiones")
        assert r["status"] == "positive_oligometastatic"
        assert r["lesion_count"] == 3

    def test_suvmax_extracted(self):
        r = extract_psma_pet("PSMA-PET positivo metastásico, SUVmax 22.5")
        assert r["suv_max_value"] == 22.5

    def test_auto_classify_oligo_from_count(self):
        """Si solo se da count ≤5 sin status keyword, infiere oligometastatic."""
        r = extract_psma_pet("Se detectaron 3 lesiones en PSMA")
        assert r["status"] == "positive_oligometastatic"
        assert r["lesion_count"] == 3

    def test_auto_classify_metastatic_from_count(self):
        """Count > 5 sin status keyword → infiere metastatic."""
        r = extract_psma_pet("Se detectaron 12 lesiones en PSMA")
        assert r["status"] == "positive_metastatic"
        assert r["lesion_count"] == 12

    def test_pending_psma(self):
        r = extract_psma_pet("Pendiente PSMA-PET, ordenado hoy")
        assert r["status"] == "pending"

    def test_full_dictation(self):
        text = ("Paciente con BCR post-RP. Realizamos PSMA-PET positivo "
                "metastásico, 6 lesiones, SUVmax 18.4, Galio-68 PSMA-11")
        r = extract_psma_pet(text)
        assert r["status"] == "positive_metastatic"
        assert r["lesion_count"] == 6
        assert r["suv_max_value"] == 18.4


# ─────────────────── Dispatch ───────────────────


class TestDispatch:
    def test_extract_for_field_ecog(self):
        r = extract_for_field("ECOG 1", "ecog")
        assert r["value"] == 1

    def test_extract_for_field_castration(self):
        r = extract_for_field("castración confirmada", "castration")
        assert r["status"] == "confirmed_castrate"

    def test_extract_for_field_unknown_raises(self):
        with pytest.raises(KeyError):
            extract_for_field("test", "unknown_field")

    def test_all_extractors_return_extractor_version(self):
        for field in ("ecog", "castration", "hrr", "psma_pet"):
            r = extract_for_field("dummy text", field)
            assert "extractor_version" in r
            assert r["extractor_version"] == EXTRACTOR_VERSION


# ─────────────────── No fabrication / conservadurismo ───────────────────


class TestNoFabrication:
    """Verifica que extractores NO devuelvan valores fabricados ante input ambiguo."""

    @pytest.mark.parametrize("field,text", [
        ("ecog", "paciente con disnea"),
        ("castration", "PSA 12 ng/mL hoy"),
        ("hrr", "ningún antecedente familiar"),
        ("psma_pet", "TAC de tórax sin novedad"),
    ])
    def test_unrelated_dictation_returns_no_value(self, field, text):
        r = extract_for_field(text, field)
        # value/status remains None — NO fabrication
        primary = r.get("value", r.get("status"))
        assert primary is None
        assert r["confidence"] == 0.0

    def test_empty_transcript_returns_no_value(self):
        for field in ("ecog", "castration", "hrr", "psma_pet"):
            r = extract_for_field("", field)
            primary = r.get("value", r.get("status"))
            assert primary is None


# ─────────────────── HTTP endpoint integration ───────────────────


class TestVoiceQuickCaptureEndpoint:
    """Integration tests for POST /api/voice/quick-capture/<field>."""

    @pytest.fixture(scope="class")
    def client(self):
        from app import app, create_app
        create_app()
        return app.test_client()

    def test_endpoint_registered(self, client):
        rules = [r.rule for r in client.application.url_map.iter_rules()
                 if 'voice/quick-capture' in str(r.rule)]
        assert '/api/voice/quick-capture/<field>' in rules

    def test_json_transcript_ecog(self, client):
        r = client.post('/api/voice/quick-capture/ecog',
                         json={'transcript': 'paciente con ECOG 2'})
        assert r.status_code == 200
        b = r.get_json()
        assert b['success'] is True
        assert b['field'] == 'ecog'
        assert b['extraction']['value'] == 2
        assert b['transcript_source'] == 'json_input'

    def test_json_transcript_psma_full(self, client):
        r = client.post('/api/voice/quick-capture/psma_pet',
                         json={'transcript': 'PSMA-PET positivo metastásico 8 lesiones SUVmax 22.5'})
        assert r.status_code == 200
        b = r.get_json()
        assert b['extraction']['status'] == 'positive_metastatic'
        assert b['extraction']['lesion_count'] == 8
        assert b['extraction']['suv_max_value'] == 22.5

    def test_invalid_field_returns_400(self, client):
        r = client.post('/api/voice/quick-capture/foo_bar',
                         json={'transcript': 'x'})
        assert r.status_code == 400
        b = r.get_json()
        assert b['error'] == 'invalid_field'
        assert 'ecog' in b['valid_fields']

    def test_missing_transcript_returns_400(self, client):
        r = client.post('/api/voice/quick-capture/ecog', json={})
        assert r.status_code == 400
        b = r.get_json()
        assert b['error'] == 'no_transcript_available'

    def test_patient_ref_echoed_back(self, client):
        r = client.post('/api/voice/quick-capture/ecog',
                         json={'transcript': 'ECOG 1', 'patient_ref': 'TEST123'})
        b = r.get_json()
        assert b['patient_ref'] == 'TEST123'
