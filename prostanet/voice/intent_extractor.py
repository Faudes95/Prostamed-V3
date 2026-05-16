"""Deterministic clinical extraction for reviewed voice transcripts."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Mapping


EXTRACTOR_VERSION = "voice-deterministic-v1.0"


def _num(raw: str) -> float | None:
    try:
        return float(str(raw or "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _iso_date(text: str) -> str:
    text = str(text or "")
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", text)
    if m:
        day, month, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date.today().isoformat()


def _explicit_iso_date(text: str) -> str:
    text = str(text or "")
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", text)
    if m:
        day, month, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return ""


def _excerpt(text: str, start: int, end: int, radius: int = 80) -> str:
    left = max(start - radius, 0)
    right = min(end + radius, len(text))
    return " ".join(text[left:right].split())


def _candidate(
    *,
    session_key: str,
    field_name: str,
    fact_group: str,
    target_result_type: str,
    value: Any,
    value_display: str,
    confidence: float,
    evidence_excerpt: str,
    page_ref: str,
) -> dict[str, Any]:
    basis = f"{session_key}|{field_name}|{value_display}|{evidence_excerpt}"
    return {
        "candidate_key": "voice:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:18],
        "field_name": field_name,
        "fact_group": fact_group,
        "target_result_type": target_result_type,
        "value": value,
        "value_display": value_display,
        "confidence": confidence,
        "status": "draft",
        "extraction_method": EXTRACTOR_VERSION,
        "evidence_excerpt": evidence_excerpt,
        "page_ref": page_ref,
    }


def _classifier_candidate(
    *,
    transcript: str,
    match: re.Match[str] | None,
    session_key: str,
    field_name: str,
    value: Any,
    label: str,
    confidence: float = 0.78,
) -> dict[str, Any]:
    if match:
        evidence = _excerpt(transcript, match.start(), match.end())
        page_ref = f"voice:{match.start()}-{match.end()}"
    else:
        evidence = transcript[:160]
        page_ref = "voice:0-0"
    return _candidate(
        session_key=session_key,
        field_name=field_name,
        fact_group="classifier_prefill",
        target_result_type="classifier_prefill",
        value=value,
        value_display=f"{label}: {value}",
        confidence=confidence,
        evidence_excerpt=evidence,
        page_ref=page_ref,
    )


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _first_match(text: str, *patterns: str) -> re.Match[str] | None:
    matches = []
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            matches.append(match)
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.start())[0]


def _biomarker_candidate(
    *,
    transcript: str,
    match: re.Match[str],
    session_key: str,
    kind: str,
    field_name: str,
    label: str,
    unit: str,
    confidence: float = 0.86,
) -> dict[str, Any] | None:
    value = _num(match.group("value"))
    if value is None or value < 0:
        return None
    local_text = _excerpt(transcript, match.start(), match.end(), radius=90)
    sample_date = _iso_date(local_text if re.search(r"\d", local_text) else transcript)
    payload = {
        "kind": kind,
        "date": sample_date,
        "value": value,
        "unit": unit,
        "context": "voice_reviewed",
    }
    return _candidate(
        session_key=session_key,
        field_name=field_name,
        fact_group="biomarker_longitudinal",
        target_result_type="longitudinal_biomarker",
        value=payload,
        value_display=f"{label} {value:g} {unit} · {sample_date}",
        confidence=confidence,
        evidence_excerpt=local_text,
        page_ref=f"voice:{match.start()}-{match.end()}",
    )


def extract_voice_candidates(
    transcript: str,
    *,
    session_key: str,
    patient: Mapping[str, Any] | None = None,
    field_specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return candidate facts, never final writes.

    This deterministic v1 deliberately extracts only high-signal longitudinal
    facts that can be reviewed by a clinician. It does not infer diagnosis,
    treatment eligibility, trial eligibility, or therapy lines without explicit
    words in the transcript.
    """

    text = str(transcript or "").strip()
    if not text:
        return []
    candidates: list[dict[str, Any]] = []
    patterns = [
        (
            "psa",
            "psa",
            "PSA",
            "ng/mL",
            re.compile(r"\b(?:psa|ape)\s*(?:actual|nuevo|de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I),
        ),
        (
            "testosterone",
            "testosterone",
            "Testosterona",
            "ng/dL",
            re.compile(r"\btestosterona\s*(?:actual|de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I),
        ),
        (
            "hb",
            "hemoglobin",
            "Hemoglobina",
            "g/dL",
            re.compile(r"\b(?:hb|hemoglobina)\s*(?:de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I),
        ),
        (
            "alp",
            "alp",
            "Fosfatasa alcalina",
            "U/L",
            re.compile(r"\b(?:alp|fosfatasa\s+alcalina)\s*(?:de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I),
        ),
        (
            "ldh",
            "ldh",
            "LDH",
            "U/L",
            re.compile(r"\bldh\s*(?:de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I),
        ),
    ]
    for kind, field_name, label, unit, pattern in patterns:
        for match in pattern.finditer(text):
            item = _biomarker_candidate(
                transcript=text,
                match=match,
                session_key=session_key,
                kind=kind,
                field_name=field_name,
                label=label,
                unit=unit,
            )
            if item:
                candidates.append(item)

    ecog_pattern = re.compile(r"\becog\s*(?:de|=|:)?\s*(?P<value>[0-4])\b", re.I)
    for match in ecog_pattern.finditer(text):
        value = int(match.group("value"))
        candidates.append(
            _candidate(
                session_key=session_key,
                field_name="ecog",
                fact_group="performance_status",
                target_result_type="longitudinal_biomarker",
                value={"kind": "ecog", "date": _iso_date(text), "value": value, "unit": "", "context": "voice_reviewed"},
                value_display=f"ECOG {value} · {_iso_date(text)}",
                confidence=0.82,
                evidence_excerpt=_excerpt(text, match.start(), match.end()),
                page_ref=f"voice:{match.start()}-{match.end()}",
            )
        )

    ctcae_pattern = re.compile(
        r"\b(?:toxicidad|ctcae|evento adverso)\b(?P<context>.{0,80}?)\bgrado\s*(?P<value>[1-5])\b",
        re.I,
    )
    for match in ctcae_pattern.finditer(text):
        grade = int(match.group("value"))
        candidates.append(
            _candidate(
                session_key=session_key,
                field_name="ctcae",
                fact_group="toxicity",
                target_result_type="longitudinal_biomarker",
                value={
                    "kind": "ctcae",
                    "date": _iso_date(text),
                    "grade": grade,
                    "term": "voice_documented_toxicity",
                    "context": match.group("context").strip(),
                },
                value_display=f"Toxicidad CTCAE grado {grade}",
                confidence=0.74,
                evidence_excerpt=_excerpt(text, match.start(), match.end()),
                page_ref=f"voice:{match.start()}-{match.end()}",
            )
        )

    line_pattern = re.compile(
        r"\bl[ií]nea\s*(?P<line>\d+).{0,80}?\b(?:inicia|inicio|empez[oó]|tratamiento|esquema)\b.{0,80}?(?P<regimen>adt|darolutamida|enzalutamida|apalutamida|abiraterona|docetaxel|cabazitaxel|olaparib|lutecio|lu-177)",
        re.I,
    )
    for match in line_pattern.finditer(text):
        line = int(match.group("line"))
        regimen = match.group("regimen").lower()
        start_date = _iso_date(_excerpt(text, match.start(), match.end(), radius=120))
        candidates.append(
            _candidate(
                session_key=session_key,
                field_name="line_of_therapy",
                fact_group="treatment_history",
                target_result_type="treatment_change",
                value={
                    "line_of_therapy_number": line,
                    "drug_scheme": regimen,
                    "start_date": start_date,
                    "context": "voice_reviewed",
                },
                value_display=f"Línea {line} · {regimen} · {start_date}",
                confidence=0.68,
                evidence_excerpt=_excerpt(text, match.start(), match.end(), radius=120),
                page_ref=f"voice:{match.start()}-{match.end()}",
            )
        )

    # Deduplicate by field/date/value display while preserving order.
    unique: list[dict[str, Any]] = []
    seen = set()
    for item in candidates:
        marker = (item["field_name"], item["target_result_type"], item["value_display"])
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(item)
    return unique


def extract_intake_classifier_candidates(
    transcript: str,
    *,
    session_key: str,
) -> list[dict[str, Any]]:
    """Extract temporary classifier prefill candidates from an intake dictation.

    These candidates are deliberately not final clinical facts. The hub UI can
    apply them to visible classifier fields after clinician review, then the
    normal classifier/wizard/register flow remains authoritative.
    """

    text = str(transcript or "").strip()
    if not text:
        return []
    candidates: list[dict[str, Any]] = []

    def add(field_name: str, value: Any, label: str, match: re.Match[str] | None = None, confidence: float = 0.78) -> None:
        candidates.append(
            _classifier_candidate(
                transcript=text,
                match=match,
                session_key=session_key,
                field_name=field_name,
                value=value,
                label=label,
                confidence=confidence,
            )
        )

    # EPIC 23.fix bug — `sospechoso` in "tacto rectal sospechoso" must NOT
    # trigger negative_diagnosis_match (it's a DRE finding, not a diagnosis-
    # suspicion modifier). We add a negative lookbehind for "rectal\s+".
    negative_diagnosis_match = _first_match(
        text,
        r"\b(?:sin|no(?:\s+(?:tiene|hay|cuenta\s+con))?|a[uú]n\s+sin)\s+(?:(?:diagn[oó]stico|c[aá]ncer)(?:\s+de\s+pr[oó]stata)?\s+)?(?:oncol[oó]gico\s+)?confirmad[oa]\b",
        r"\b(?:diagn[oó]stico|c[aá]ncer)(?:\s+de\s+pr[oó]stata)?\s+no\s+confirmad[oa]\b",
        r"\b(?:sin|no)\s+confirmar\b",
        # `sospecha/sospechoso` only counts as negative-diagnosis if NOT
        # preceded by "tacto rectal" (then it's a DRE finding).
        r"(?<!rectal\s)\b(?:sospecha|workup|evaluaci[oó]n diagn[oó]stica)\b",
    )
    screening_match = _first_match(text, r"\b(screening|tamizaje|detecci[oó]n temprana)\b")
    negative_biopsy_match = _first_match(text, r"\bbiopsia\s+(?:previa\s+)?(?:negativa|benigna)\b")
    # EPIC 23.fix bug — recognize "adenocarcinoma intraductal" as a confirmed
    # diagnosis. Intraductal carcinoma IS a confirmed pathology subtype
    # (aggressive marker), NOT a "suspicion". Without this match the entire
    # downstream cascade (histology + diagnosis_date + PSA classification)
    # silently fails on this VERY common dictation pattern.
    positive_diagnosis_match = _first_match(
        text,
        r"\bbiopsia\s+(?:positiva|confirmatoria|confirmada)\b",
        r"\badenocarcinoma\s+(?:confirmado|por\s+biopsia|intraductal|ductal|acinar|de\s+pr[oó]stata)\b",
        r"\badenocarcinoma\b(?=\s*[,\.]?\s*(?:con|de|en))",  # "adenocarcinoma, con ..." / "adenocarcinoma de"
        r"\bcarcinoma\s+intraductal\b",
        r"\bc[aá]ncer\s+(?:de\s+pr[oó]stata\s+)?(?:confirmado|intraductal)\b",
        r"\bdiagn[oó]stico\s+(?:oncol[oó]gico\s+)?confirmado\b",
        r"\bingresar(?:emos|é)\s+(?:a\s+)?un\s+paciente\s+con\b",  # explicit clinician phrasing
    )

    if screening_match:
        add("known_cancer_diagnosis", "0", "Sin diagnóstico confirmado", None, 0.76)
        add("encounter_type", "screening", "Tipo de encuentro", None, 0.76)
        add("screening_context", "1", "Screening", None, 0.76)
    if negative_diagnosis_match:
        add("known_cancer_diagnosis", "0", "Sin diagnóstico confirmado", negative_diagnosis_match, 0.86)
    if negative_biopsy_match:
        add("known_cancer_diagnosis", "0", "Sin diagnóstico confirmado", negative_biopsy_match, 0.86)
        add("prior_negative_biopsy", "1", "Biopsia previa negativa", negative_biopsy_match, 0.9)
    if _has(text, r"\bbiopsia\s+(?:programada|agendada)\b"):
        add("biopsy_scheduled", "1", "Biopsia programada", None, 0.82)
    if positive_diagnosis_match and not negative_diagnosis_match and not negative_biopsy_match and not screening_match:
        add("known_cancer_diagnosis", "1", "Diagnóstico confirmado", positive_diagnosis_match, 0.86)
    # EPIC 23.fix — recognize intraductal as a distinct histology subtype
    # BEFORE the generic adenocarcinoma fallback. Intraductal carcinoma
    # has aggressive prognosis + may indicate cribriform pattern + germline
    # BRCA2 association (NCCN 2026 PROS-A).
    if _has(text, r"\b(?:adenocarcinoma|carcinoma)\s+intraductal\b"):
        add("histology_subtype", "Adenocarcinoma intraductal", "Subtipo histológico", None, 0.88)
        add("histology_aggressive_variant", "1", "Variante histológica agresiva", None, 0.85)
    elif _has(text, r"\badenocarcinoma\s+ductal\b"):
        add("histology_subtype", "Adenocarcinoma ductal", "Subtipo histológico", None, 0.82)
    elif _has(text, r"\badenocarcinoma\b") and not negative_diagnosis_match:
        add("histology_subtype", "Adenocarcinoma acinar", "Subtipo histológico", None, 0.72)

    # EPIC 23.fix — "antígeno" is the clinical Spanish synonym for PSA.
    # Pre-EPIC23 the regex only matched "psa"/"ape". Common clinician
    # dictation says "antígeno prostático específico de X" or
    # "antígeno prebiopsia de Y", both unhandled. Adds "antigeno"
    # alias + pre-biopsia/post-biopsia context normalization.
    # EPIC 23.fix — Capture the MODIFIER as a named group so we know which
    # variant the clinician dictated (baseline vs current vs bcr) without
    # relying on a wide excerpt that may contain both contexts.
    psa_pattern = re.compile(
        r"\b(?:psa|ape|ant[ií]geno(?:\s+prost[aá]tico(?:\s+espec[ií]fico)?)?)\b"
        r"(?:\s+(?P<modifier>"
        r"basal|actual|reciente|hoy|al\s+diagn[oó]stico|diagn[oó]stico|"
        r"pre[-\s]?biopsia|prebiopsia|post[-\s]?biopsia|bcr|"
        r"recurrencia\s+bioqu[ií]mica"
        r"))?"
        r"(?:\s+(?:de|en|fue|es|=|:))*"
        r"\s*(?P<value>\d+(?:[\.,]\d+)?)",
        re.I,
    )
    for match in psa_pattern.finditer(text):
        value = _num(match.group("value"))
        if value is None:
            continue
        modifier = (match.group("modifier") or "").lower().strip()
        # Classify by the modifier token captured immediately after PSA alias.
        if any(tok in modifier for tok in ("pre-biopsia", "prebiopsia", "pre biopsia",
                                            "basal", "diagn", "al diagn")):
            add("psa_baseline_ng_ml", value, "PSA basal pre-biopsia / al diagnóstico", match, 0.88)
        elif any(tok in modifier for tok in ("actual", "reciente", "hoy")):
            add("psa", value, "PSA actual", match, 0.86)
        elif any(tok in modifier for tok in ("bcr", "recurrencia")):
            add("bcr_psa", value, "PSA al momento de BCR", match, 0.86)
        elif modifier == "":
            # No modifier — disambiguate by surrounding context (tight window).
            # EPIC 23.fix: require POSITIVE diagnosis AND NOT negative match
            # so "paciente sin cáncer confirmado, PSA 6.5" routes PSA to
            # `psa` (current sospecha), not `psa_baseline_ng_ml`.
            confirmed_dx = bool(positive_diagnosis_match) and not bool(negative_diagnosis_match)
            if confirmed_dx or (
                _has(text, r"\badenocarcinoma\b")
                and not _has(text, r"\b(?:sin|no(?:\s+(?:tiene|hay))?)\s+adenocarcinoma\b")
            ):
                # Patient has confirmed Dx → unmodified PSA is baseline
                add("psa_baseline_ng_ml", value, "PSA basal al diagnóstico", match, 0.80)
            else:
                add("psa", value, "PSA actual de sospecha", match, 0.78)
        else:
            add("psa", value, "PSA actual", match, 0.78)

    testosterone_pattern = re.compile(r"\btestosterona\s*(?:actual|de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I)
    for match in testosterone_pattern.finditer(text):
        value = _num(match.group("value"))
        if value is None:
            continue
        add("testosterone_value", value, "Testosterona", match, 0.88)
        add("castrate_testosterone_status", "confirmed_castrate" if value < 50 else "not_castrate", "Castración bioquímica", match, 0.82)

    psad_pattern = re.compile(r"\bpsad|densidad\s+de\s+psa\s*(?:de|=|:)?\s*(?P<value>\d+(?:[\.,]\d+)?)", re.I)
    for match in psad_pattern.finditer(text):
        value = _num(match.group("value"))
        if value is not None:
            add("psad", value, "Densidad de PSA", match, 0.82)

    # EPIC 23.fix — DRE / tacto rectal capture (completely missing pre-EPIC23).
    # Patterns:
    #   "tacto rectal sospechoso" / "tacto rectal anormal"      → suspicious=true
    #   "tacto rectal normal" / "DRE normal" / "tacto rectal sin alteraciones" → suspicious=false
    #   "exploración digital rectal" / "DRE" stand-alone with adjective.
    dre_suspicious_pattern = re.compile(
        r"\b(?:tacto\s+rectal|dre|exploraci[oó]n\s+digital\s+rectal|examen\s+rectal\s+digital)\s+"
        r"(?:con\s+|presenta\s+|muestra\s+|revela\s+)?"  # EPIC 23.fix: optional connector
        r"(?P<finding>sospechos[oa]|anormal|positiv[oa]|n[oó]dulo|nodular|induraci[oó]n|indurad[oa]|asim[eé]tric[oa]|positivo|firme|dur[oa]|p[eé]treo)",
        re.I,
    )
    dre_normal_pattern = re.compile(
        r"\b(?:tacto\s+rectal|dre|exploraci[oó]n\s+digital\s+rectal|examen\s+rectal\s+digital)\s+"
        r"(?P<finding>normal|negativ[oa]|sin\s+alteraciones|sin\s+hallazgos|liso|simetric[oa])",
        re.I,
    )
    for match in dre_suspicious_pattern.finditer(text):
        finding = match.group("finding")
        add("dre_suspicious", "1", "Tacto rectal sospechoso", match, 0.92)
        add("dre_finding_description", finding.lower(), "Hallazgo DRE", match, 0.88)
    for match in dre_normal_pattern.finditer(text):
        # Only record if no suspicious match already fired in same dictation
        already_suspicious = any(
            (c.get("field_name") == "dre_suspicious" and str(c.get("value")) == "1") for c in candidates
        )
        if not already_suspicious:
            add("dre_suspicious", "0", "Tacto rectal normal", match, 0.92)
            add("dre_finding_description", match.group("finding").lower(), "Hallazgo DRE", match, 0.88)

    pirads_pattern = re.compile(r"\bpi[- ]?rads\s*(?P<value>[2-5])\b", re.I)
    for match in pirads_pattern.finditer(text):
        add("pirads_score", match.group("value"), "PI-RADS", match, 0.86)

    diagnosis_date = _explicit_iso_date(text)
    if diagnosis_date and positive_diagnosis_match and _has(text, r"\b(fecha|diagn[oó]stico|biopsia|confirmado|adenocarcinoma)\b"):
        add("diagnosis_date", diagnosis_date, "Fecha de diagnóstico", None, 0.68)

    gleason_pattern = re.compile(r"\bgleason\s*(?P<primary>[3-5])\s*(?:\+|mas|más)\s*(?P<secondary>[3-5])\b", re.I)
    for match in gleason_pattern.finditer(text):
        add("gleason_primary", match.group("primary"), "Gleason primario", match, 0.9)
        add("gleason_secondary", match.group("secondary"), "Gleason secundario", match, 0.9)

    t_stage_pattern = re.compile(r"\bcT\s*(?P<value>[1-4][abc]?)\b", re.I)
    for match in t_stage_pattern.finditer(text):
        add("clinical_tstage", f"cT{match.group('value').lower()}", "cT clínico", match, 0.84)

    # EPIC 25.7 (GodiBot CORTANA-INTAKE-013) — pT (pathologic T-stage), Charlson,
    # cribriform pattern. Pre-EPIC25 these clinically common dictation patterns
    # were silently ignored.
    pt_stage_pattern = re.compile(r"\bpT\s*(?P<value>[1-4][abc]?)\b", re.I)
    for match in pt_stage_pattern.finditer(text):
        add("pathologic_t_stage", f"pT{match.group('value').lower()}",
            "pT patológico", match, 0.88)
        add("tumor_stage_at_rp", f"pT{match.group('value').lower()}",
            "pT en pieza RP", match, 0.86)

    charlson_pattern = re.compile(r"\bcharlson\s*(?:de|=|:)?\s*(?P<value>\d+)\b", re.I)
    for match in charlson_pattern.finditer(text):
        add("charlson_score", match.group("value"), "Charlson Comorbidity Index",
            match, 0.90)

    # Cribriform pattern — NCCN PROS-3 v2026 unfavorable-IR trigger
    if _has(text, r"\b(?:patr[oó]n\s+)?cribriform[eo](?:\s+pattern)?\b"):
        add("cribriform_pattern", "1", "Patrón cribriforme presente",
            None, 0.88)
        add("histology_aggressive_variant", "1",
            "Variante histológica agresiva (cribriform)", None, 0.85)

    # Intraductal carcinoma (often dictated alongside Gleason — different keyword
    # from "adenocarcinoma intraductal" already handled in EPIC 23.fix)
    if _has(text, r"\bcarcinoma\s+intraductal\b"):
        add("intraductal_carcinoma", "1",
            "Carcinoma intraductal documentado", None, 0.90)
    n_stage_pattern = re.compile(r"\bcN\s*(?P<value>[01xX])\b", re.I)
    for match in n_stage_pattern.finditer(text):
        value = match.group("value").upper().replace("X", "x")
        add("nodal_status", f"N{value}", "cN clínico", match, 0.84)

    if _has(text, r"\b(prostatectom[ií]a|post[- ]?rp|post prostatectom[ií]a)\b"):
        add("prior_local_therapy", "prostatectomy", "Terapia local previa", None, 0.86)
    if _has(text, r"\b(braquiterapia)\b"):
        add("prior_local_therapy", "brachytherapy", "Terapia local previa", None, 0.86)
    elif _has(text, r"\b(radioterapia|post[- ]?rt)\b"):
        add("prior_local_therapy", "radiation", "Terapia local previa", None, 0.84)
    if _has(text, r"\b(bcr|recurrencia bioqu[ií]mica|phoenix)\b"):
        add("bcr_detected", "1", "BCR documentada", None, 0.82)
        explicit_date = _explicit_iso_date(text)
        if explicit_date:
            add("bcr_date", explicit_date, "Fecha de BCR", None, 0.64)
    if _has(text, r"\bphoenix\b"):
        add("failure_confirmation_basis", "phoenix_confirmed", "Base de confirmación post-RT", None, 0.76)

    if _has(text, r"\bM0\b|sin met[aá]stasis|imagen convencional m0"):
        add("metastatic_disease_known", "0", "Enfermedad metastásica conocida", None, 0.78)
        add("metastasis_site", "M0", "Resumen cM", None, 0.78)
        add("conventional_imaging_status", "M0", "Imagen convencional", None, 0.72)
    if _has(text, r"\bM1a\b|ganglios\s+no\s+regionales|retroperitoneal"):
        add("metastatic_disease_known", "1", "Enfermedad metastásica conocida", None, 0.86)
        add("metastasis_site", "M1a", "Resumen cM", None, 0.86)
        add("nonregional_nodal_metastasis_present", "1", "Ganglios no regionales", None, 0.84)
        add("nonregional_nodal_site", "retroperitoneal", "Cadena ganglionar no regional", None, 0.62)
    if _has(text, r"\bM1b\b|met[aá]stasis\s+[oó]sea|lesiones?\s+[oó]seas?|hueso"):
        add("metastatic_disease_known", "1", "Enfermedad metastásica conocida", None, 0.86)
        add("metastasis_site", "M1b", "Resumen cM", None, 0.82)
        add("bone_metastasis_present", "1", "Metástasis óseas", None, 0.84)
    if _has(text, r"\bM1c\b|met[aá]stasis\s+visceral|h[ií]gado|pulm[oó]n|visceral"):
        add("metastatic_disease_known", "1", "Enfermedad metastásica conocida", None, 0.88)
        add("metastasis_site", "M1c", "Resumen cM", None, 0.88)
        add("visceral_metastasis_present", "1", "Metástasis viscerales", None, 0.86)
        if _has(text, r"h[ií]gado|hep[aá]tic"):
            add("visceral_site", "liver", "Órgano visceral predominante", None, 0.72)
        elif _has(text, r"pulm[oó]n|pulmonar"):
            add("visceral_site", "lung", "Órgano visceral predominante", None, 0.72)

    count_patterns = [
        ("nonregional_nodal_count", r"(?P<value>\d+)\s+(?:ganglios?|adenopat[ií]as?)\s+(?:no\s+regionales|retroperitoneales)", "Lesiones ganglionares"),
        ("bone_axial_count", r"(?P<value>\d+)\s+lesiones?\s+(?:axiales|en\s+columna|en\s+pelvis)", "Lesiones óseas axiales"),
        ("bone_appendicular_count", r"(?P<value>\d+)\s+lesiones?\s+(?:apendiculares|en\s+costillas|en\s+f[eé]mur|en\s+h[uú]mero)", "Lesiones óseas apendiculares"),
        ("visceral_lesion_count", r"(?P<value>\d+)\s+lesiones?\s+viscerales", "Lesiones viscerales"),
    ]
    for field_name, pattern, label in count_patterns:
        for match in re.finditer(pattern, text, re.I):
            value = _num(match.group("value"))
            if value is not None:
                add(field_name, int(value), label, match, 0.82)

    if _has(text, r"\b(adt|deprivaci[oó]n androg[eé]nica|leuprolide|goserelina|degarelix|relugolix)\b"):
        add("current_adt_context", "medical_adt_continuous", "Contexto ADT", None, 0.82)
    if _has(text, r"\borquiectom[ií]a\b"):
        add("current_adt_context", "orchiectomy", "Contexto ADT", None, 0.86)
    if _has(text, r"\bcrpc|resistente\s+a\s+castraci[oó]n\b"):
        add("systemic_progression_context", "confirmed_crpc", "Contexto de progresión", None, 0.86)
    elif _has(text, r"\bprogresi[oó]n\s+bajo\s+adt|progresi[oó]n\s+con\s+castraci[oó]n\b"):
        add("systemic_progression_context", "progression_on_adt_verify_castration", "Contexto de progresión", None, 0.78)
    if _has(text, r"\bprogresi[oó]n\s+bioqu[ií]mica\b"):
        add("progression_pattern", "biochemical_only", "Patrón de progresión", None, 0.72)
    if _has(text, r"\bimagen\s+convencional\s+M1\b"):
        add("conventional_imaging_status", "M1", "Imagen convencional", None, 0.78)

    priority = {
        "known_cancer_diagnosis": {"0": 30 if (negative_diagnosis_match or negative_biopsy_match or screening_match) else 0, "1": 20},
        "metastasis_site": {"M1c": 40, "M1b": 30, "M1a": 20, "M0": 10},
        "metastatic_disease_known": {"1": 20, "0": 10},
        "current_adt_context": {"orchiectomy": 30, "medical_adt_continuous": 20},
    }
    selected: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for item in candidates:
        field = str(item.get("field_name") or "")
        value = str(item.get("value"))
        existing = selected.get(field)
        if not existing:
            selected[field] = item
            continue
        existing_value = str(existing.get("value"))
        if existing_value == value:
            if float(item.get("confidence") or 0) > float(existing.get("confidence") or 0):
                selected[field] = item
            continue
        item_score = priority.get(field, {}).get(value, int(float(item.get("confidence") or 0) * 100))
        existing_score = priority.get(field, {}).get(existing_value, int(float(existing.get("confidence") or 0) * 100))
        conflicts.append({"field_name": field, "kept": value if item_score > existing_score else existing_value, "rejected": existing_value if item_score > existing_score else value})
        if item_score > existing_score:
            selected[field] = item

    unique: list[dict[str, Any]] = []
    seen = set()
    for item in candidates:
        marker = (item["field_name"], str(item["value"]))
        if marker in seen:
            continue
        if selected.get(item["field_name"], {}).get("candidate_key") != item.get("candidate_key"):
            continue
        seen.add(marker)
        unique.append(item)
    return unique
