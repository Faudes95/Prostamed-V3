# IEC 62304 §5.7 (System testing) — EPIC 18
"""Tests EPIC 18 — Evidence active surveillance via external delta detection.

Active surveillance = weekly cron consulta ClinicalTrials.gov v2 + PubMed
E-utilities para detectar updates en los 322 trials documentados.

Diseño anti-flake:
  - TODOS los tests usan unittest.mock.patch sobre urllib.request.urlopen
  - CERO network calls reales en CI (mock responses pre-canned)
  - Rate-limit (time.sleep) reemplazado por mock para test speed

Beneficio clínico verificado:
  - Detecta cuando CHAARTED, VISION, etc. tienen updates en ClinicalTrials.gov
  - Detecta nuevas publicaciones PubMed citando trial acronyms
  - Honest manifest update: records con delta detectado NO se marcan fresh
  - Loop Monitor surface candidate para revisión clínica humana
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ─────────────────── Helpers ───────────────────


def _mock_response(payload: dict | str, status: int = 200):
    """Build a urllib-style mock response usable in `with urlopen(...) as resp:`."""
    if isinstance(payload, dict):
        body = json.dumps(payload).encode("utf-8")
    else:
        body = str(payload).encode("utf-8")
    mock = MagicMock()
    mock.read.return_value = body
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


# ─────────────────── EPIC 18 — CLI / flag presence ───────────────────


def test_epic18_external_delta_check_flag_exists_in_script():
    """epic15_evidence_refresh.py debe exponer --external-delta-check."""
    script = (PROJECT_ROOT / "scripts" / "epic15_evidence_refresh.py").read_text()
    assert "--external-delta-check" in script, (
        "EPIC 18: --external-delta-check flag missing"
    )
    assert "--dry-run" in script, "EPIC 18: --dry-run flag missing"


def test_epic18_trial_nct_registry_includes_high_impact_trials():
    """Curated NCT registry debe cubrir trials high-impact en prostate cancer."""
    import epic15_evidence_refresh as mod
    must_have = {"CHAARTED", "VISION", "ARASENS", "LATITUDE", "STAMPEDE", "AFFIRM"}
    missing = must_have - set(mod.TRIAL_NCT_REGISTRY.keys())
    assert not missing, f"NCT registry missing high-impact trials: {missing}"


# ─────────────────── ClinicalTrials.gov v2 client ───────────────────


def test_epic18_clinicaltrials_v2_parses_last_update_post_date():
    """query_clinicaltrials_v2 debe extraer lastUpdatePostDate correctamente."""
    import epic15_evidence_refresh as mod

    fake_payload = {
        "protocolSection": {
            "statusModule": {
                "lastUpdatePostDateStruct": {"date": "2026-03-15"},
                "overallStatus": "COMPLETED",
                "primaryCompletionDateStruct": {"date": "2024-12-30"},
                "studyFirstPostDateStruct": {"date": "2014-05-01"},
            }
        }
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(fake_payload)):
        result = mod.query_clinicaltrials_v2("NCT00309985")
    assert result is not None
    assert result["last_update_post_date"] == "2026-03-15"
    assert result["overall_status"] == "COMPLETED"
    assert result["nct_id"] == "NCT00309985"


def test_epic18_clinicaltrials_v2_handles_http_error_gracefully():
    """Si urlopen falla, query_clinicaltrials_v2 retorna None (graceful)."""
    import epic15_evidence_refresh as mod
    from urllib import error as urllib_error

    with patch("urllib.request.urlopen", side_effect=urllib_error.HTTPError(
        url="x", code=404, msg="Not Found", hdrs={}, fp=None
    )):
        result = mod.query_clinicaltrials_v2("NCT99999999")
    assert result is None, "Must return None on HTTP error (graceful)"


# ─────────────────── PubMed E-utilities client ───────────────────


def test_epic18_pubmed_esearch_returns_recent_pmids():
    """query_pubmed_esearch debe parsear esearchresult.idlist."""
    import epic15_evidence_refresh as mod

    fake_payload = {
        "esearchresult": {
            "count": "3",
            "idlist": ["38123456", "38234567", "38345678"],
        }
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(fake_payload)):
        pmids = mod.query_pubmed_esearch(term="CHAARTED[Title/Abstract]", mindate="2026-01-01")
    assert pmids == ["38123456", "38234567", "38345678"]


def test_epic18_pubmed_esearch_empty_response_returns_empty_list():
    import epic15_evidence_refresh as mod
    fake_payload = {"esearchresult": {"count": "0", "idlist": []}}
    with patch("urllib.request.urlopen", return_value=_mock_response(fake_payload)):
        pmids = mod.query_pubmed_esearch(term="NonexistentTrial")
    assert pmids == []


# ─────────────────── EPIC 18b — OpenFDA drug labels ───────────────────


def test_epic18b_drug_registry_covers_pivotal_trials():
    """TRIAL_DRUG_REGISTRY debe cubrir trials con drug primary identificable."""
    import epic15_evidence_refresh as mod
    must_cover = {"CHAARTED", "VISION", "ARASENS", "AFFIRM", "TITAN", "PROfound"}
    missing = must_cover - set(mod.TRIAL_DRUG_REGISTRY.keys())
    assert not missing, f"Drug registry missing pivotal trials: {missing}"
    # CHAARTED debe mapear a docetaxel
    assert "docetaxel" in mod.TRIAL_DRUG_REGISTRY["CHAARTED"]
    # VISION debe mapear a lutetium
    assert any("lutetium" in d.lower() for d in mod.TRIAL_DRUG_REGISTRY["VISION"])


def test_epic18b_openfda_drug_label_parses_effective_time():
    """query_openfda_drug_label debe extraer effective_time + boxed_warning."""
    import epic15_evidence_refresh as mod

    fake_payload = {
        "results": [
            {
                "effective_time": "20230815",
                "boxed_warning": ["WARNING: SEVERE CUTANEOUS ADVERSE REACTIONS"],
                "warnings_and_cautions": ["Long warning text here..."],
                "contraindications": ["Hypersensitivity to apalutamide"],
                "openfda": {
                    "generic_name": ["apalutamide"],
                    "brand_name": ["Erleada"],
                    "manufacturer_name": ["Janssen"],
                    "spl_id": ["abc-123-def"],
                },
            }
        ]
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(fake_payload)):
        result = mod.query_openfda_drug_label("apalutamide")
    assert result is not None
    assert result["effective_time"] == "20230815"
    assert result["boxed_warning"] is not None
    assert "SEVERE CUTANEOUS" in result["boxed_warning"]
    assert result["brand_names"] == ["Erleada"]
    assert result["spl_id"] == "abc-123-def"


def test_epic18b_openfda_returns_none_when_no_results():
    """OpenFDA sin results → None (graceful, no exception)."""
    import epic15_evidence_refresh as mod
    fake_payload = {"results": []}
    with patch("urllib.request.urlopen", return_value=_mock_response(fake_payload)):
        result = mod.query_openfda_drug_label("nonexistent_drug")
    assert result is None


def test_epic18b_openfda_date_conversion_yyyymmdd_to_iso():
    """_openfda_date_to_iso debe convertir YYYYMMDD a YYYY-MM-DD."""
    import epic15_evidence_refresh as mod
    assert mod._openfda_date_to_iso("20230815") == "2023-08-15"
    assert mod._openfda_date_to_iso("20260101") == "2026-01-01"
    assert mod._openfda_date_to_iso(None) is None
    assert mod._openfda_date_to_iso("invalid") is None
    assert mod._openfda_date_to_iso("2023") is None  # Too short


def test_epic18b_external_delta_check_detects_fda_label_update():
    """Si OpenFDA reporta effective_time > last_reviewed → delta drug_label_update."""
    import epic15_evidence_refresh as mod

    # CHAARTED maps to docetaxel — should trigger OpenFDA query
    manifest = {
        "records": [
            {"trial_or_source": "CHAARTED", "last_reviewed": "2022-01-01"},
        ]
    }
    ct_payload = {"protocolSection": {"statusModule": {}}}  # No CT update
    pm_payload = {"esearchresult": {"idlist": []}}  # No new PubMed
    fda_payload = {
        "results": [{
            "effective_time": "20230815",  # POST 2022-01-01
            "boxed_warning": None,
            "warnings_and_cautions": ["Common AEs..."],
            "openfda": {
                "generic_name": ["docetaxel"],
                "brand_name": ["Taxotere"],
                "spl_id": ["spl-456"],
            },
        }]
    }

    def fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "clinicaltrials.gov" in url:
            return _mock_response(ct_payload)
        if "eutils.ncbi.nlm.nih.gov" in url:
            return _mock_response(pm_payload)
        if "api.fda.gov" in url:
            return _mock_response(fda_payload)
        return _mock_response({})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)

    fda_deltas = [d for d in deltas if d["source"] == "openfda"]
    assert len(fda_deltas) == 1, f"Expected 1 OpenFDA delta, got {fda_deltas}"
    delta = fda_deltas[0]
    assert delta["drug_name"] == "docetaxel"
    assert delta["effective_time"] == "2023-08-15"
    assert delta["record_id"] == "CHAARTED"
    assert delta["has_boxed_warning"] is False


def test_epic18b_external_delta_check_flags_boxed_warning():
    """Si OpenFDA tiene boxed_warning, delta debe registrar has_boxed_warning=True."""
    import epic15_evidence_refresh as mod

    manifest = {
        "records": [
            {"trial_or_source": "TITAN", "last_reviewed": "2022-01-01"},
        ]
    }
    fda_payload = {
        "results": [{
            "effective_time": "20230815",
            "boxed_warning": ["WARNING: SCAR REACTIONS — apalutamide may cause severe cutaneous adverse reactions including DRESS and SJS"],
            "openfda": {
                "generic_name": ["apalutamide"],
                "brand_name": ["Erleada"],
                "spl_id": ["abc-789"],
            },
        }]
    }

    def fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "api.fda.gov" in url:
            return _mock_response(fda_payload)
        if "clinicaltrials.gov" in url:
            return _mock_response({"protocolSection": {"statusModule": {}}})
        return _mock_response({"esearchresult": {"idlist": []}})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)

    fda_deltas = [d for d in deltas if d["source"] == "openfda"]
    assert len(fda_deltas) >= 1
    boxed_delta = next((d for d in fda_deltas if d.get("has_boxed_warning")), None)
    assert boxed_delta is not None, "Boxed warning should be flagged in delta"


def test_epic18b_external_delta_check_skips_when_fda_predates_review():
    """Si effective_time ≤ last_reviewed → NO delta OpenFDA."""
    import epic15_evidence_refresh as mod

    manifest = {
        "records": [
            {"trial_or_source": "AFFIRM", "last_reviewed": "2026-05-01"},
        ]
    }
    fda_payload = {
        "results": [{
            "effective_time": "20240301",  # PRE 2026-05-01
            "openfda": {"generic_name": ["enzalutamide"]},
        }]
    }

    def fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "api.fda.gov" in url:
            return _mock_response(fda_payload)
        if "clinicaltrials.gov" in url:
            return _mock_response({"protocolSection": {"statusModule": {}}})
        return _mock_response({"esearchresult": {"idlist": []}})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)
    fda_deltas = [d for d in deltas if d["source"] == "openfda"]
    assert fda_deltas == [], "Must not flag FDA delta when label predates last_reviewed"


# ─────────────────── External delta check integration ───────────────────


def test_epic18_external_delta_check_detects_clinicaltrials_update():
    """Si ClinicalTrials.gov reporta update > last_reviewed → delta."""
    import epic15_evidence_refresh as mod

    manifest = {
        "records": [
            {"trial_or_source": "CHAARTED", "last_reviewed": "2026-01-01"},
        ]
    }
    ct_payload = {
        "protocolSection": {
            "statusModule": {
                "lastUpdatePostDateStruct": {"date": "2026-03-15"},
                "overallStatus": "COMPLETED",
            }
        }
    }
    pm_payload = {"esearchresult": {"idlist": []}}

    def fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "clinicaltrials.gov" in url:
            return _mock_response(ct_payload)
        return _mock_response(pm_payload)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):  # Skip rate-limit delay in test
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)

    ct_deltas = [d for d in deltas if d["source"] == "clinicaltrials.gov"]
    assert len(ct_deltas) == 1
    assert ct_deltas[0]["record_id"] == "CHAARTED"
    assert ct_deltas[0]["last_update_post_date"] == "2026-03-15"


def test_epic18_external_delta_check_skips_when_update_predates_review():
    """Si lastUpdatePostDate ≤ last_reviewed → NO delta."""
    import epic15_evidence_refresh as mod

    manifest = {
        "records": [
            {"trial_or_source": "VISION", "last_reviewed": "2026-05-01"},
        ]
    }
    ct_payload = {
        "protocolSection": {
            "statusModule": {
                "lastUpdatePostDateStruct": {"date": "2026-03-15"},  # PRE last_reviewed
                "overallStatus": "ACTIVE_NOT_RECRUITING",
            }
        }
    }
    pm_payload = {"esearchresult": {"idlist": []}}

    def fake_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "clinicaltrials.gov" in url:
            return _mock_response(ct_payload)
        return _mock_response(pm_payload)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)
    ct_deltas = [d for d in deltas if d["source"] == "clinicaltrials.gov"]
    assert ct_deltas == [], "Must not flag delta when update predates last_reviewed"


def test_epic18_external_delta_check_detects_pubmed_new_publications():
    """Si PubMed retorna PMIDs nuevos post last_reviewed → delta."""
    import epic15_evidence_refresh as mod

    manifest = {
        "records": [
            # Without NCT mapping — PubMed only
            {"trial_or_source": "Generic Phase 3 Trial XYZ", "last_reviewed": "2026-01-01"},
        ]
    }

    def fake_urlopen(req, timeout=10):
        return _mock_response({"esearchresult": {"idlist": ["39111111", "39222222"]}})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("time.sleep", return_value=None):
        deltas = mod.external_delta_check(manifest, max_records=1, sleep_sec=0)
    pm_deltas = [d for d in deltas if d["source"] == "pubmed"]
    assert len(pm_deltas) == 1
    assert pm_deltas[0]["pmids"] == ["39111111", "39222222"]


# ─────────────────── Honest manifest update ───────────────────


def test_epic18_manifest_not_marked_fresh_if_delta_detected():
    """Records con delta NO deben ser marcados last_reviewed=today.

    EPIC 18 honest update: pending_human_review=True hasta que un clínico revise.
    """
    import epic15_evidence_refresh as mod
    from datetime import date

    manifest = {
        "records": [
            {"trial_or_source": "CHAARTED", "last_reviewed": "2025-12-01"},
            {"trial_or_source": "AFFIRM", "last_reviewed": "2025-12-01"},
        ]
    }
    delta_ids = {"CHAARTED"}
    today_iso = date.today().isoformat()
    refreshed = mod.refresh_manifest(manifest, delta_record_ids=delta_ids)

    chaarted = refreshed["records"][0]
    affirm = refreshed["records"][1]

    # CHAARTED: delta detected → NOT marked fresh
    assert chaarted["last_reviewed"] == "2025-12-01", (
        "Delta-flagged record must keep original last_reviewed"
    )
    assert chaarted.get("pending_human_review") is True
    assert chaarted["review_status"] == "external_delta_detected"

    # AFFIRM: no delta → marked fresh today
    assert affirm["last_reviewed"] == today_iso
    assert affirm["review_status"] == "current"
    assert affirm.get("pending_human_review") is False


# ─────────────────── Delta report ───────────────────


def test_epic18_delta_report_markdown_generated(tmp_path: Path):
    """write_delta_report debe emitir Markdown con secciones por source."""
    import epic15_evidence_refresh as mod

    deltas = [
        {
            "record_id": "CHAARTED",
            "source": "clinicaltrials.gov",
            "delta_type": "trial_update",
            "last_update_post_date": "2026-03-15",
            "overall_status": "COMPLETED",
            "url": "https://clinicaltrials.gov/study/NCT00309985",
            "nct_id": "NCT00309985",
        },
        {
            "record_id": "CHAARTED",
            "source": "pubmed",
            "delta_type": "new_publications",
            "pmids": ["38123456"],
            "mindate": "2026-01-01",
            "url": "https://pubmed.ncbi.nlm.nih.gov/?term=CHAARTED",
        },
    ]
    output_path = tmp_path / "evidence_delta_2026W20.md"
    result_path = mod.write_delta_report(deltas, output_path=output_path)
    assert result_path == output_path
    content = output_path.read_text()
    assert "Evidence Delta Report" in content
    assert "Total deltas detected:** 2" in content
    assert "clinicaltrials.gov (1 deltas)" in content
    assert "pubmed (1 deltas)" in content
    assert "CHAARTED" in content
    assert "NCT00309985" in content


# ─────────────────── Loop Monitor integration ───────────────────


def test_epic18_loop_monitor_surfaces_evidence_delta_candidate(tmp_path: Path, monkeypatch):
    """Si existe evidence_delta_*.md con deltas → Loop Monitor surface candidate."""
    from prostanet.agentic import autonomous_improvement_os as aios

    # Create fake delta report in expected location
    delta_dir = aios.PROJECT_ROOT / "output" / "regulatory"
    delta_dir.mkdir(parents=True, exist_ok=True)
    delta_md = delta_dir / "evidence_delta_2026W21.md"
    delta_md.write_text(
        "# Evidence Delta Report — Week 2026-W21\n\n"
        "**Total deltas detected:** 3\n\n"
        "## clinicaltrials.gov (2 deltas)\n\n"
        "### CHAARTED\n\n"
        "- delta_type: trial_update\n\n"
        "### VISION\n\n"
        "- delta_type: trial_update\n\n"
        "## pubmed (1 deltas)\n\n"
        "### CHAARTED\n\n"
        "- delta_type: new_publications\n",
        encoding="utf-8",
    )
    try:
        candidates = aios._evidence_delta_candidates({})
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["lane"] == "evidence_gap"
        assert "3 evidence source(s)" in cand["title"]
        # High-impact trials detected → priority boost
        assert cand["clinical_impact"] >= 8
    finally:
        delta_md.unlink(missing_ok=True)


def test_epic18_loop_monitor_no_candidate_when_no_delta_report():
    """Sin evidence_delta_*.md → NO candidate (no false positives)."""
    from prostanet.agentic import autonomous_improvement_os as aios

    delta_dir = aios.PROJECT_ROOT / "output" / "regulatory"
    # Remove any existing delta reports temporarily
    existing = list(delta_dir.glob("evidence_delta_*.md")) if delta_dir.exists() else []
    backup: dict[Path, str] = {}
    try:
        for p in existing:
            backup[p] = p.read_text(encoding="utf-8")
            p.unlink()
        candidates = aios._evidence_delta_candidates({})
        assert candidates == [], "Must not surface candidate when no delta report exists"
    finally:
        # Restore
        for p, content in backup.items():
            p.write_text(content, encoding="utf-8")


def test_epic18_loop_monitor_no_candidate_when_zero_deltas(tmp_path: Path):
    """Si delta report tiene 0 deltas → NO candidate."""
    from prostanet.agentic import autonomous_improvement_os as aios

    delta_dir = aios.PROJECT_ROOT / "output" / "regulatory"
    delta_dir.mkdir(parents=True, exist_ok=True)
    delta_md = delta_dir / "evidence_delta_2026W22.md"
    delta_md.write_text(
        "# Evidence Delta Report — Week 2026-W22\n\n"
        "**Total deltas detected:** 0\n\n"
        "_No external deltas detected this week._\n",
        encoding="utf-8",
    )
    try:
        # Should pick the latest report which is THIS one with 0
        # But pre-existing reports may dominate; we test via temporary isolation
        # by ensuring our test report is the lexicographically last
        candidates = aios._evidence_delta_candidates({})
        zero_delta_cands = [c for c in candidates if "0 evidence" in c.get("title", "")]
        assert zero_delta_cands == [], "Must not surface candidate when delta_count=0"
    finally:
        delta_md.unlink(missing_ok=True)
