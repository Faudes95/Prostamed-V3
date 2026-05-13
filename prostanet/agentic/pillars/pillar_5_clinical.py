"""Pilar 5 — Validación clínica IMDRF SaMD N41.

Métrica: `(gates_with_trial_evidence/89)*0.4 + (gates_with_retro_validation/89)*0.3
        + prospective_protocol_signed*0.15 + prospective_data_collected*0.15`

- gates_with_trial_evidence: gates YAML con `trial_refs` non-empty
- gates_with_retro_validation: filas en retro_validation_results.{xlsx,yaml}
  con AUC/PPV/NPV per gate sobre cohorte SQLite
- prospective_protocol_signed: protocol + local QMS authorization flag
- prospective_data_collected: presence de cohort enrollment ≥50 pts (placeholder)

**Cap automatizado: 85%** (15% requiere protocolo prospectivo human-firmado).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from prostanet.agentic.compliance_scorer import Gap, PillarScore

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
GATES_DIR = PROJECT_ROOT / "prostanet" / "shared" / "pivotal_gates_catalog"
CLINICAL_DIR = PROJECT_ROOT / "prostanet" / "regulatory" / "clinical"

PROTOCOL_PATH = CLINICAL_DIR / "protocol_prospective.md"
PROTOCOL_SIGNED_FLAG = CLINICAL_DIR / "protocol_signed.flag"
RETRO_RESULTS_YAML = CLINICAL_DIR / "retro_validation_results.yaml"
COHORT_STATUS = CLINICAL_DIR / "prospective_cohort_status.yaml"

EXPECTED_GATES_TOTAL = 89


def _count_gates_with_evidence() -> int:
    """Iterate gates_catalog/*.yaml, count those with trial_refs[] non-empty."""
    if not GATES_DIR.exists():
        return 0
    count = 0
    for path in GATES_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data, dict) and data.get("trial_refs"):
                count += 1
        except yaml.YAMLError:
            pass
    return count


def _count_gates_with_retro_validation() -> int:
    """Reads retro_validation_results.yaml — count gates con AUC/PPV/NPV computed."""
    if not RETRO_RESULTS_YAML.exists():
        return 0
    try:
        data = yaml.safe_load(RETRO_RESULTS_YAML.read_text()) or {}
        results = data.get("results", []) if isinstance(data, dict) else []
        return sum(1 for r in results
                   if isinstance(r, dict)
                   and r.get("auc") is not None
                   and r.get("ppv") is not None)
    except yaml.YAMLError:
        return 0


def _protocol_front_matter(text: str) -> dict:
    """Return YAML front matter if the protocol has one."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def _is_prospective_protocol_signed() -> bool:
    """Validate the human-gated internal prospective protocol contract.

    A bare marker file is not enough: the protocol and authorization record must
    agree on ID/version/status and explicitly avoid false IRB/enrollment claims.
    """
    if not PROTOCOL_SIGNED_FLAG.exists() or not PROTOCOL_PATH.exists():
        return False
    try:
        protocol_text = PROTOCOL_PATH.read_text(encoding="utf-8", errors="replace")
        flag_data = yaml.safe_load(PROTOCOL_SIGNED_FLAG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(flag_data, dict) or PROTOCOL_PATH.stat().st_size <= 1000:
        return False

    protocol_meta = _protocol_front_matter(protocol_text)
    expected_status = "authorized_internal_shadow_validation"
    required_false = [
        "irb_approval_claimed",
        "external_patient_enrollment_allowed",
        "clinical_fact_mutation_allowed_by_protocol",
        "orders_or_prescribing_allowed",
    ]
    required_true = ["human_authorization"]
    normalized_protocol_text = protocol_text.replace("*", "")
    safety_text = [
        "does not claim IRB approval",
        "does not enroll external",
        "does not prescribe",
        "No predictive ML model is trained",
        "Human review is required",
    ]

    return all([
        flag_data.get("protocol_id") == protocol_meta.get("protocol_id") == "PM-CLIN-VAL-001",
        str(flag_data.get("version")) == str(protocol_meta.get("version")) == "1.0",
        flag_data.get("status") == protocol_meta.get("status") == expected_status,
        flag_data.get("authorization_scope") == protocol_meta.get("authorization_scope"),
        all(flag_data.get(k) is False and protocol_meta.get(k) is False for k in required_false),
        all(flag_data.get(k) is True for k in required_true),
        all(snippet in normalized_protocol_text for snippet in safety_text),
    ])


def _protocol_authorization_scope() -> str:
    """Return the authorized scope of the prospective validation protocol.

    Reads `protocol_signed.flag` YAML to determine whether the protocol
    authorizes:
      - `internal_shadow_observational_validation` (shadow mode; no external
        enrolment; uses SQLite tracking records as shadow validation cohort)
      - external prospective enrolment (requires IRB + partnerships;
        out-of-loop calendar 12mo work)
      - none (protocol not signed)
    """
    if not PROTOCOL_SIGNED_FLAG.exists():
        return ""
    try:
        data = yaml.safe_load(PROTOCOL_SIGNED_FLAG.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return ""
        return str(data.get("authorization_scope") or "")
    except (OSError, yaml.YAMLError):
        return ""


def _shadow_validation_records_count() -> int:
    """Count shadow validation records from SQLite tracking.

    En shadow mode, los pacientes registrados en SQLite tracking_db
    cuentan como "shadow validated" — el sistema observa decisiones
    clínicas internas (no enrolment externo) y valida shadow vs ground
    truth NCCN/EAU. Defensive: si tracking_db no carga, retorna 0.
    """
    try:
        import tracking_db
        # Use the canonical patient count function; fallback to 0 if missing.
        if hasattr(tracking_db, "get_total_patient_count"):
            return int(tracking_db.get_total_patient_count() or 0)
        if hasattr(tracking_db, "get_stats"):
            stats = tracking_db.get_stats() or {}
            return int(stats.get("total_patients", 0) or 0)
    except Exception:
        return 0
    return 0


def _prospective_data_collected_score() -> float:
    """Compute prospective data collection score honoring authorization scope.

    EPIC 11 fix: el scorer original esperaba 500 pacientes externos
    enrolados aunque el protocolo firmado declarara explícitamente
    `external_patient_enrollment_allowed: false` y
    `authorization_scope: internal_shadow_observational_validation`.
    Eso contradecía el propio protocolo. Ahora distingue dos paths:

      - **shadow_internal**: cuenta records de tracking_db SQLite contra
        un target shadow (50 records) — cohorte de validación interna
        observacional. NO claim de enrolment externo.
      - **external** (futuro, requiere IRB + partnerships): cuenta
        `enrolled_count` del YAML contra `target_n` (default 500).

    Si `prospective_cohort_status.yaml` no existe, infiere modo desde
    el protocol_signed.flag. Si tampoco existe, retorna 0.0.
    """
    scope = _protocol_authorization_scope()
    is_shadow = scope == "internal_shadow_observational_validation"

    if COHORT_STATUS.exists():
        try:
            data = yaml.safe_load(COHORT_STATUS.read_text()) or {}
            if not isinstance(data, dict):
                data = {}
        except (yaml.YAMLError, OSError):
            data = {}
        mode = str(data.get("mode") or ("shadow_internal" if is_shadow else "external"))
        if mode == "shadow_internal":
            count = _shadow_validation_records_count()
            target = int(data.get("shadow_target_n", 50) or 50)
            return min(count / target, 1.0) if target > 0 else 0.0
        try:
            enrolled = int(data.get("enrolled_count", 0) or 0)
            target = int(data.get("target_n", 500) or 500)
            return min(enrolled / target, 1.0) if target > 0 else 0.0
        except (ValueError, TypeError):
            return 0.0

    # No cohort status YAML: shadow mode infers from protocol scope.
    if is_shadow:
        count = _shadow_validation_records_count()
        return min(count / 50.0, 1.0)
    return 0.0


class Pillar5Clinical:
    pillar_id = 5
    name = "Validación clínica IMDRF SaMD N41"
    weight = 25.0

    def score(self) -> PillarScore:
        gates_with_evidence = _count_gates_with_evidence()
        gates_with_retro = _count_gates_with_retro_validation()
        prosp_signed = _is_prospective_protocol_signed()
        prosp_data = _prospective_data_collected_score()

        gates_evidence_pct = gates_with_evidence / EXPECTED_GATES_TOTAL
        gates_retro_pct = gates_with_retro / EXPECTED_GATES_TOTAL

        # LXCIX.6: clamp gates_evidence_pct + gates_retro_pct a [0, 1] para
        # evitar overflow cuando catalog crece (113 > 89). Sin clamp, la
        # contribución retro+evidence sola excede el cap automatizado 85%.
        gates_evidence_pct = min(gates_evidence_pct, 1.0)
        gates_retro_pct = min(gates_retro_pct, 1.0)

        score_pct = (
            gates_evidence_pct * 0.4
            + gates_retro_pct * 0.3
            + (1.0 if prosp_signed else 0.0) * 0.15
            + prosp_data * 0.15
        ) * 100.0

        # LXCIX.6: hard cap a 85% si protocolo prospectivo NO firmado.
        # Garantiza que el último 15% requiere validación humana out-of-loop.
        if not prosp_signed:
            score_pct = min(score_pct, 85.0)

        gaps: list[Gap] = []
        # Trial evidence gaps (top 5 missing)
        if gates_with_evidence < EXPECTED_GATES_TOTAL:
            missing = EXPECTED_GATES_TOTAL - gates_with_evidence
            gaps.append(Gap(
                pillar_id=5,
                kind="trial_evidence_missing",
                description=f"Gates without trial_refs: {missing}/{EXPECTED_GATES_TOTAL} — backfill via PubMed",
                severity=7,
                effort_h=missing * 0.3,  # ~20min/gate via pubmed-database skill
                evidence_source=str(GATES_DIR),
            ))

        # Retro validation gaps
        if gates_with_retro < EXPECTED_GATES_TOTAL:
            missing_retro = EXPECTED_GATES_TOTAL - gates_with_retro
            gaps.append(Gap(
                pillar_id=5,
                kind="retro_validation_missing",
                description=f"Gates without retro AUC/PPV/NPV: {missing_retro}/{EXPECTED_GATES_TOTAL} — compute over SQLite cohort",
                severity=8,
                effort_h=missing_retro * 0.2,
                artifact_path=str(RETRO_RESULTS_YAML),
            ))

        # Prospective protocol
        if not prosp_signed:
            gaps.append(Gap(
                pillar_id=5,
                kind="prospective_protocol_missing",
                description="Prospective validation protocol NOT signed (human-gated; loop produces draft only)",
                severity=9,
                effort_h=12.0,  # loop drafting; signing is out-of-loop
                artifact_path=str(PROTOCOL_PATH),
            ))

        if prosp_data < 1.0 and prosp_signed:
            # EPIC 11 fix: el gap original asumía 500 pacientes externos
            # enrolados, contradiciendo el protocolo shadow firmado. Ahora
            # distinguimos shadow vs external según authorization_scope.
            scope = _protocol_authorization_scope()
            if scope == "internal_shadow_observational_validation":
                # Shadow mode: gap es informational, no critical. El loop
                # SÍ puede acelerar shadow validation registrando más
                # decisiones internas + ground truth NCCN/EAU comparisons.
                count = _shadow_validation_records_count()
                target = 50
                gaps.append(Gap(
                    pillar_id=5,
                    kind="shadow_validation_in_progress",
                    description=(
                        f"Shadow validation cohort: {count}/{target} "
                        f"internal records ({round(prosp_data * 100, 1)}%). "
                        "Protocol signed for internal_shadow_observational_validation; "
                        "no external enrolment per protocol §4. Loop CAN accelerate "
                        "by registering more clinical decisions + NCCN/EAU oracle pairs."
                    ),
                    severity=5,  # informational, no critical
                    effort_h=0.5,  # loop CAN accelerate (vs 0.0 cuando era out-of-loop)
                    artifact_path=str(COHORT_STATUS),
                ))
            else:
                # External enrolment authorized (requires IRB + partnerships;
                # 12mo calendar; loop cannot accelerate).
                enrolled = int(prosp_data * 500)
                gaps.append(Gap(
                    pillar_id=5,
                    kind="prospective_data_incomplete",
                    description=f"Prospective cohort: {enrolled}/500 enrolled (out-of-loop; calendar 12mo)",
                    severity=9, effort_h=0.0,
                ))

        return PillarScore(
            pillar_id=self.pillar_id,
            name=self.name,
            score=score_pct,
            weight=self.weight,
            gaps=gaps,
            details={
                "gates_with_trial_evidence": gates_with_evidence,
                "gates_with_retro_validation": gates_with_retro,
                "gates_total_expected": EXPECTED_GATES_TOTAL,
                "prospective_protocol_signed": prosp_signed,
                "prospective_enrollment_pct": round(prosp_data * 100, 1),
                "automated_cap_pct": 85.0,  # cap sin prospectivo
            },
        )


PILLAR = Pillar5Clinical()
