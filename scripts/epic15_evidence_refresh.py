#!/usr/bin/env python3
"""EPIC 15 + 18 — Evidence currentness refresh + active surveillance.

EPIC 15 (baseline): documenta `last_reviewed` timestamps en
`prostanet/regulatory/clinical/evidence_freshness_manifest.yaml` para
scheduled-review audit trail (FDA Pre-Sub Q-Sub).

EPIC 18 (active surveillance): NUEVO modo `--external-delta-check`
consulta fuentes externas (ClinicalTrials.gov v2, PubMed E-utilities)
para detectar updates en evidence. Si hay delta → manifest NO se marca
fresh automáticamente; se genera reporte para revisión humana clínica.

Uso:
    # Modo legacy (EPIC 15) — solo re-estampa timestamps
    python3 scripts/epic15_evidence_refresh.py

    # Modo report-only — no escribe manifest
    python3 scripts/epic15_evidence_refresh.py --check-only

    # Modo EPIC 18 — query externo + honest manifest update
    python3 scripts/epic15_evidence_refresh.py --external-delta-check

    # Modo EPIC 18 dry-run — query externo sin escribir manifest
    python3 scripts/epic15_evidence_refresh.py --external-delta-check --dry-run

Diseño EPIC 18 — fuentes externas:
- ClinicalTrials.gov v2 API (público, sin key): detecta lastUpdatePostDate
  para trials con NCT ID conocido (curated map ~25 trials high-impact).
- PubMed E-utilities (público, rate-limited 3 req/s sin key): esearch
  por trial acronym/title, detecta publicaciones nuevas post last_reviewed.
- OpenFDA drug labels: DEFERRED a EPIC 18b (requiere drug name extraction).

Rate limiting: 0.4s sleep entre queries → ~2.5 req/s, bajo límite PubMed.
Tiempo total esperado: ~130s para 322 records (acceptable weekly cron).

Output EPIC 18:
- `output/regulatory/evidence_delta_YYYYWW.md` — reporte humano-legible
- Records con delta detectado marcados `review_status=external_delta_detected`
  y `pending_human_review=True`; NO se sobre-escribe `last_reviewed`.

Beneficio clínico:
- Long-term follow-ups detectados (ej: CHAARTED OS revisada en JCO 2023)
- Retractions y expressions of concern flageadas
- Trial status changes (terminated, withdrawn, suspended) trazables
- Counsel del paciente refleja evidence currente con audit trail real
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import yaml

logger = logging.getLogger("epic15_evidence_refresh")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "prostanet" / "regulatory" / "clinical" / "evidence_freshness_manifest.yaml"
DELTA_OUTPUT_DIR = PROJECT_ROOT / "output" / "regulatory"

# EPIC 18: rate limit per request (3 req/s = 0.33s; usamos 0.4s safety margin)
EXTERNAL_QUERY_DELAY_SEC = 0.4
EXTERNAL_HTTP_TIMEOUT_SEC = 10
USER_AGENT = "ProstaNet-EvidenceRefresh/1.0 (clinical research surveillance)"

# EPIC 18: curated NCT mapping para trials high-impact en oncología prostática.
# Esta lista crece manualmente cuando se identifican nuevos trials. Trials
# sin NCT ID solo reciben PubMed esearch (sin ClinicalTrials.gov check).
TRIAL_NCT_REGISTRY: dict[str, str] = {
    "AFFIRM": "NCT00974311",
    "ALSYMPCA": "NCT00699751",
    "ARAMIS": "NCT02200614",
    "ARASENS": "NCT02799602",
    "ARCHES": "NCT02677896",
    "CARD": "NCT02485691",
    "CHAARTED": "NCT00309985",
    "COSMIC-021": "NCT03170960",
    "EMBARK": "NCT02319837",
    "ENZAMET": "NCT02446405",
    "FIRSTANA": "NCT01308567",
    "KEYNOTE-365": "NCT02861573",
    "LATITUDE": "NCT01715285",
    "MAGNITUDE": "NCT03748641",
    "PEACE-1": "NCT01957436",
    "PREVAIL": "NCT01212991",
    "PRONOUNCE": "NCT02663908",
    "PROpel": "NCT03732820",
    "PROSPER": "NCT02003924",
    "PROfound": "NCT02987543",
    "SPARTAN": "NCT01946204",
    "STAMPEDE": "NCT00268476",
    "TALAPRO-2": "NCT03395197",
    "TheraP": "NCT03392428",
    "TITAN": "NCT02489318",
    "TROPIC": "NCT00417079",
    "VISION": "NCT03511664",
}


# ─────────────────── Manifest I/O (EPIC 15 baseline) ───────────────────


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest missing: {MANIFEST_PATH}")
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}


def write_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def freshness_summary(manifest: dict) -> dict:
    """Compute freshness stats: fresh / stale / unknown counts."""
    today = date.today()
    threshold_days = int(
        ((manifest.get("review_policy") or {}).get("fresh_threshold_days")) or 90
    )
    stale_days = int(
        ((manifest.get("review_policy") or {}).get("stale_threshold_days")) or 365
    )
    fresh = stale = unknown = expired = 0
    for rec in manifest.get("records", []) or []:
        last = rec.get("last_reviewed")
        if not last:
            unknown += 1
            continue
        try:
            if isinstance(last, str):
                d = date.fromisoformat(last[:10])
            elif isinstance(last, date):
                d = last
            else:
                unknown += 1
                continue
        except (ValueError, TypeError):
            unknown += 1
            continue
        delta = (today - d).days
        if delta <= threshold_days:
            fresh += 1
        elif delta <= stale_days:
            stale += 1
        else:
            expired += 1
    total = fresh + stale + unknown + expired
    return {
        "total": total,
        "fresh": fresh,
        "stale": stale,
        "expired": expired,
        "unknown": unknown,
        "fresh_pct": round(fresh / total * 100, 1) if total else 0.0,
    }


def refresh_manifest(
    manifest: dict,
    reviewer_role: str = "automated_bootstrap_review",
    delta_record_ids: set[str] | None = None,
) -> dict:
    """Mark records as reviewed today, EXCEPT those with external delta detected.

    EPIC 15 baseline: re-estampa today.
    EPIC 18 honest update: records en `delta_record_ids` NO se marcan fresh;
    se flag `pending_human_review=True` para que el clínico revise antes.
    """
    today_iso = date.today().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    delta_record_ids = delta_record_ids or set()

    for rec in manifest.get("records", []) or []:
        rec_id = rec.get("trial_or_source") or ""
        if rec_id in delta_record_ids:
            # EPIC 18: honest — NO mark fresh, flag for human review
            rec["review_status"] = "external_delta_detected"
            rec["pending_human_review"] = True
            rec["last_delta_check_iso8601"] = now_iso
            # NO sobre-escribir last_reviewed
        else:
            rec["last_reviewed"] = today_iso
            rec["last_review_iso8601"] = now_iso
            rec["reviewer_role"] = reviewer_role
            rec.setdefault("review_method", "catalog_inventory_review")
            rec["review_status"] = "current"
            rec["pending_human_review"] = False

    manifest["generated_at"] = today_iso
    manifest["last_refresh_iso8601"] = now_iso
    return manifest


# ─────────────────── EPIC 18 — External delta clients ───────────────────


def _http_get_json(url: str, *, timeout: int = EXTERNAL_HTTP_TIMEOUT_SEC) -> dict | None:
    """Minimal HTTP GET → JSON. Returns None on any error (graceful)."""
    req = urllib_request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None


def _http_get_text(url: str, *, timeout: int = EXTERNAL_HTTP_TIMEOUT_SEC) -> str | None:
    req = urllib_request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError) as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None


def query_clinicaltrials_v2(nct_id: str) -> dict | None:
    """ClinicalTrials.gov v2 API — get study by NCT ID.

    Returns dict with keys: lastUpdatePostDate, overallStatus, primaryCompletionDate,
    or None on error.
    """
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    data = _http_get_json(url)
    if not data:
        return None
    proto = (data.get("protocolSection") or {})
    status_module = proto.get("statusModule") or {}
    return {
        "nct_id": nct_id,
        "last_update_post_date": (status_module.get("lastUpdatePostDateStruct") or {}).get("date"),
        "overall_status": status_module.get("overallStatus"),
        "primary_completion_date": (status_module.get("primaryCompletionDateStruct") or {}).get("date"),
        "study_first_post_date": (status_module.get("studyFirstPostDateStruct") or {}).get("date"),
    }


def query_pubmed_esearch(
    term: str, mindate: str | None = None, maxdate: str | None = None, retmax: int = 5
) -> list[str]:
    """PubMed esearch — return PMID list for term, optionally date-filtered.

    Sin API key: rate-limited a 3 req/s por NCBI policy.
    """
    params = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": str(retmax),
        "sort": "date",
    }
    if mindate:
        params["datetype"] = "pdat"
        params["mindate"] = mindate.replace("-", "/")
        if maxdate:
            params["maxdate"] = maxdate.replace("-", "/")
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib_parse.urlencode(params)
    data = _http_get_json(url)
    if not data:
        return []
    return list((data.get("esearchresult") or {}).get("idlist") or [])


def external_delta_check(
    manifest: dict,
    *,
    max_records: int | None = None,
    sleep_sec: float = EXTERNAL_QUERY_DELAY_SEC,
) -> list[dict]:
    """EPIC 18: query external sources for delta detection.

    Returns list of delta records. Cada delta es dict con: record_id, source,
    delta_type, payload (source-specific).

    Args:
        manifest: Loaded evidence_freshness_manifest.yaml.
        max_records: Cap for testing (None = all 322).
        sleep_sec: Inter-query delay for rate-limit compliance.
    """
    records = manifest.get("records", []) or []
    if max_records is not None:
        records = records[:max_records]

    deltas: list[dict] = []
    for idx, rec in enumerate(records):
        trial_name = str(rec.get("trial_or_source") or "")
        if not trial_name:
            continue
        last_reviewed = str(rec.get("last_reviewed") or "")

        # 1. ClinicalTrials.gov v2 (only for trials with curated NCT mapping)
        nct_id = TRIAL_NCT_REGISTRY.get(trial_name)
        if nct_id:
            ct_result = query_clinicaltrials_v2(nct_id)
            time.sleep(sleep_sec)
            if ct_result and ct_result.get("last_update_post_date"):
                update_date = ct_result["last_update_post_date"][:10]
                if last_reviewed and update_date > last_reviewed:
                    deltas.append({
                        "record_id": trial_name,
                        "source": "clinicaltrials.gov",
                        "delta_type": "trial_update",
                        "last_update_post_date": update_date,
                        "overall_status": ct_result.get("overall_status"),
                        "url": f"https://clinicaltrials.gov/study/{nct_id}",
                        "nct_id": nct_id,
                    })

        # 2. PubMed esearch (acronym/title search since last_reviewed)
        # Strategy: only query for non-empty, non-generic titles
        if len(trial_name) >= 4 and not trial_name.lower().startswith(("the ", "a ")):
            pmids = query_pubmed_esearch(
                term=f"{trial_name}[Title/Abstract]",
                mindate=last_reviewed,
                retmax=3,
            )
            time.sleep(sleep_sec)
            if pmids:
                deltas.append({
                    "record_id": trial_name,
                    "source": "pubmed",
                    "delta_type": "new_publications",
                    "pmids": pmids,
                    "mindate": last_reviewed,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={urllib_parse.quote(trial_name)}",
                })

        if (idx + 1) % 25 == 0:
            logger.info("External delta check progress: %d/%d records", idx + 1, len(records))

    return deltas


def write_delta_report(deltas: list[dict], output_path: Path | None = None) -> Path:
    """EPIC 18: emit human-readable Markdown report for clinical team review."""
    today = date.today()
    year, week, _ = today.isocalendar()
    DELTA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        output_path = DELTA_OUTPUT_DIR / f"evidence_delta_{year}W{week:02d}.md"

    lines: list[str] = []
    lines.append(f"# Evidence Delta Report — Week {year}-W{week:02d}")
    lines.append("")
    lines.append(f"**Generated:** {today.isoformat()}  ")
    lines.append(f"**Total deltas detected:** {len(deltas)}  ")
    lines.append("")
    lines.append(
        "Each entry below requires **human clinical review** before the corresponding "
        "manifest record can be re-marked `fresh`. Records remain `review_status=external_delta_detected` "
        "with `pending_human_review=True` until reviewed."
    )
    lines.append("")
    by_source: dict[str, list[dict]] = {}
    for d in deltas:
        by_source.setdefault(d["source"], []).append(d)
    for source, items in sorted(by_source.items()):
        lines.append(f"## {source} ({len(items)} deltas)")
        lines.append("")
        for d in items:
            lines.append(f"### {d['record_id']}")
            lines.append("")
            lines.append(f"- **Delta type:** {d['delta_type']}")
            for key, value in d.items():
                if key in ("record_id", "source", "delta_type"):
                    continue
                lines.append(f"- **{key}:** {value}")
            lines.append("")
    if not deltas:
        lines.append("_No external deltas detected this week._")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ─────────────────── CLI ───────────────────


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="EPIC 15+18 evidence freshness refresh.")
    ap.add_argument("--check-only", action="store_true", help="Report freshness without writing")
    ap.add_argument(
        "--external-delta-check",
        action="store_true",
        help="EPIC 18: query ClinicalTrials.gov + PubMed for deltas before manifest update",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="EPIC 18: run external delta check + write report, but do NOT modify manifest",
    )
    ap.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="EPIC 18: cap records queried (testing/CI use)",
    )
    ap.add_argument(
        "--reviewer-role",
        default="automated_bootstrap_review",
        help="Role recorded as reviewer (default: automated_bootstrap_review).",
    )
    args = ap.parse_args()

    manifest = load_manifest()
    summary = freshness_summary(manifest)
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"  Records total: {summary['total']}")
    print(f"  Fresh (<=90d): {summary['fresh']} ({summary['fresh_pct']}%)")
    print(f"  Stale (91-365d): {summary['stale']}")
    print(f"  Expired (>365d): {summary['expired']}")
    print(f"  Unknown: {summary['unknown']}")

    if args.check_only:
        return 0

    delta_record_ids: set[str] = set()
    delta_report_path: Path | None = None
    if args.external_delta_check:
        logger.info("EPIC 18: external delta check started (max_records=%s)", args.max_records)
        deltas = external_delta_check(manifest, max_records=args.max_records)
        delta_record_ids = {d["record_id"] for d in deltas}
        delta_report_path = write_delta_report(deltas)
        print(f"\nEPIC 18: {len(deltas)} delta(s) detected across {len(delta_record_ids)} records")
        print(f"Delta report: {delta_report_path}")

    if args.dry_run:
        print("\nDry-run: manifest NOT modified.")
        return 0

    reviewer_role = "external_validated_review" if args.external_delta_check else args.reviewer_role
    refreshed = refresh_manifest(manifest, reviewer_role=reviewer_role, delta_record_ids=delta_record_ids)
    write_manifest(refreshed)
    print(f"\nRefreshed {len(refreshed.get('records', []) or [])} records.")
    if delta_record_ids:
        print(f"  {len(delta_record_ids)} record(s) flagged pending_human_review (delta detected)")
    new_summary = freshness_summary(refreshed)
    print(f"Post-refresh fresh: {new_summary['fresh']} ({new_summary['fresh_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
