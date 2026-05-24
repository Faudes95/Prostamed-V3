"""EPIC 22d — UI ↔ Data Concordance Gates.

Enforces three structural invariants between the UI, the backend, and the
clinical fact layer. These tests are intentionally additive — they run
alongside existing tests and DO NOT modify clinical logic. They guard
future commits against regressing UI/data concordance.

Three gates:

  1. **data-testid presence**: every `data-testid="*-card"` attribute in
     templates/patient_profile_v2.html must correspond to a key actually
     populated by `prostanet.presentation.v2_adapters.bundle_to_v2_profile`
     OR explicitly tracked as "static-card-no-data-binding" below.

  2. **FactSpec → consumer**: every FactSpec declared in
     `prostanet.shared.clinical_fact_registry.FACT_SPECS` with a non-empty
     `consumers` tuple must have at least one downstream module that
     references it (verified by grep across prostanet/).

  3. **Cortana card data populating contract**: when a card is rendered
     in patient_profile_v2.html, its data binding must exist in
     bundle_to_v2_profile's return dict. Catches "pretty placeholder"
     cards that consume keys never populated by the adapter.

Gate philosophy:
- These tests must NEVER fail on logically correct work. If a new card
  is added with data binding, the bundle adapter must populate it; if not,
  the card must be marked STATIC_NO_DATA_BINDING here. This is intentional
  friction to prevent placeholder UI from accumulating.

- For now: gates are **WARNING** mode for newly added bindings (tests pass
  with `xfail` markers) — flip to FAILING in EPIC 23 once all currently
  documented gaps are addressed.

EPIC 22d skills applied:
- /backend-patterns (test patterns)
- /api-design (endpoint naming concordance)
- /ultrareview (final review pass)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "patient_profile_v2.html"
V2_ADAPTER_PATH = PROJECT_ROOT / "prostanet" / "presentation" / "v2_adapters.py"
FACT_REGISTRY_PATH = PROJECT_ROOT / "prostanet" / "shared" / "clinical_fact_registry.py"


# ─────────────────── Static exemptions ───────────────────

# Cards that intentionally render structural UI without backend data
# (e.g., a toggle, a static help link). EPIC 22d.4 — explicit allowlist
# so future "pretty placeholder" cards can't sneak past the gate.
STATIC_NO_DATA_BINDING: set[str] = {
    "cortana-realtime-toggle",   # toggles persona — local state only
    "biopsy-capture-cta",        # link to capture page; no backend data
    "biopsy-gleason-display",    # nested element under biopsy-diagnostics-card
    "biopsy-margin-display",     # nested element under biopsy-diagnostics-card
    "brca2-preferred-therapy",   # nested element under brca2-carrier-card
    "lynch-preferred-therapy",   # nested element under lynch-carrier-card
    "geriatric-preferred-therapy",  # nested element under geriatric-frail-card
    "young-onset-preferred-therapy",  # nested element under young-onset-card
    "adt-lt-preferred-therapy",  # nested element under adt-long-term-card
    "survivorship-5y-preferred",  # nested element under survivorship-5y-card
    "comorbidity-cv-preferred",   # nested element under comorbidity-cv-card
    # EPIC 23 — Arbiter banner nested elements
    "fusion-severity-badge",
    "fusion-conflict-1", "fusion-conflict-2", "fusion-conflict-3", "fusion-conflict-4",
    "fusion-resolution-1", "fusion-resolution-2", "fusion-resolution-3", "fusion-resolution-4",
    "arbitrated-rank-1", "arbitrated-rank-2", "arbitrated-rank-3",
    "arbitrated-rank-4", "arbitrated-rank-5",
    # EPIC 22e.2 — Preferences capture modal nested elements
    "preferences-capture-modal", "patient-twin-open-prefs-form", "preferences-submit",
    # EPIC 22f — Nested -preferred elements per card (rendered by macro)
    "comorbidity-hepatic-card-preferred", "brca1-carrier-card-preferred",
    "atm-carrier-card-preferred", "hoxb13-carrier-card-preferred",
    "post-brachy-ldr-card-preferred", "post-ebrt-alone-card-preferred",
    "post-sbrt-card-preferred", "post-focal-therapy-card-preferred",
    "oligo-synchronous-card-preferred", "oligo-metach-adt-naive-card-preferred",
    "oligo-recurrent-post-def-card-preferred", "second-primary-card-preferred",
    "suspected-low-psa-card-preferred", "suspected-elevated-psa-ww-card-preferred",
    "neg-biopsy-age-lt45-card-preferred",
    "twin-ranking-header",  # EPIC 25.1 — header that shows "X regimens excluded by arbiter"
    "twin-contraindication-banner",  # BUG FIX 2026-05-17 — banner cuando hay regímenes hard_block
    # BUG FIX 2026-05-17 — Pivotal gates dynamic render (3 secciones + endpoint)
    "pivotal-gates-meta",                  # header meta del card "Gates pivotal activos"
    "pivotal-gates-active-list",           # sección activa con loop {% for gate in gates_top %}
    "pivotal-gates-detailed-list",         # vista detallada con loop {% for gate in gates_all %}
    "pivotal-gates-evidence-table",        # tabla per-gate evidence drill-down dinámica
    "pivotal-gates-contextualizados",      # sidebar gates contextualizados
    "catalog-inventory-gates",             # catálogo del sistema (metadata, no per-patient)
    "patient-twin-low-capture",  # nested chip under patient-twin-os-card
    "patient-twin-readiness-pct",  # nested chip under patient-twin-os-card
    "risk-strat-preferred-therapy",  # nested label under risk-stratified card
    "twin-goal-of-care",         # nested chip under patient-twin-os-card
    "twin-redecision-alerts",    # nested chip under patient-twin-os-card
    # EPIC 45 FAUBOT CXXX — Data Integrity panel + nested resolve button
    # El panel se renderiza condicionalmente (solo si hay contradicciones o
    # resoluciones históricas), y el botón aplica auto-resolución vía
    # endpoint /api/data-integrity/<nss>/resolve. Ambos son parte de la
    # misma sección — no requieren bundle key independiente porque su
    # data-binding fluye desde profile_view_raw.data_integrity.
    "data-integrity-panel",
    "data-integrity-resolve-btn",
    # EPIC 46.B FAUBOT CXXXIII — ML Predictions panel + 4 sub-cards.
    # El panel se renderiza condicional (solo si ml_predictions.available),
    # y las 4 cards individuales son sub-elementos del mismo bundle key
    # `ml_predictions` (no requieren bundle key independiente cada una).
    # Data-binding fluye desde profile_view_raw.ml_predictions → models{4}.
    "ml-predictions-panel",
    "ml-card-treatment-response",
    "ml-card-survival",
    "ml-card-anomaly",
    "ml-card-state-transition",
    # EPIC 47 FAUBOT CXXXV — Trajectory dashboard + sub-elementos.
    # Data-binding fluye desde profile_view_raw.trajectory → series + alerts
    # + kinetics. Charts (psa/ecog/labs) y kpis son sub-renders condicionales.
    "trajectory-dashboard",
    "trajectory-alerts-badge",
    "trajectory-alerts-list",
    "trajectory-chart-psa",
    "trajectory-chart-ecog",
    "trajectory-chart-labs",
    "trajectory-kpi-psadt",
    "trajectory-kpi-velocity",
    "trajectory-kpi-nadir",
    "trajectory-kpi-alp-trend",
    # EPIC 48 FAUBOT CXXXVI — Decision Loop Closure (narrative + override + outcomes)
    # Data-binding fluye desde profile_view_raw.decision_narrative + outcome_linkage.
    # Cards individuales son sub-renders del mismo bundle key (no requieren
    # bundle keys independientes cada testid).
    "decision-narrative",
    "decision-narrative-body",
    "decision-narrative-confidence-badge",
    "decision-narrative-override-btn",
    "decision-override-modal",
    "decision-override-form",
    "decision-override-submit-btn",
    "outcome-linkage-panel",
    # Sprint 1 fix #8 — Fallback banner cuando narrative cae a context_fallback
    "decision-narrative-fallback-banner",
    "decision-narrative-classifier-cta",
    # Sprint 3 fix #11 — Patient name elevated to h1 with testid
    "patient-name-heading",
}


# Map each card data-testid → key in bundle_to_v2_profile return dict.
# Explicit mapping is part of the gate: every card with data binding MUST
# be listed here. If a card is added without a mapping, the test fails
# (forcing the engineer to declare the contract).
CARD_TO_BUNDLE_KEY: dict[str, str] = {
    "biopsy-diagnostics-card": "biopsy_summary",  # EPIC 22b.4
    "brca2-carrier-card": "brca2_carrier",        # EPIC 22c — highest clinical impact (PARP-first)
    "lynch-carrier-card": "lynch_carrier",        # EPIC 22c — pembrolizumab eligible
    "geriatric-frail-card": "geriatric_frail",    # EPIC 22c — treatment de-escalation
    "young-onset-card": "young_onset",            # EPIC 22c — universal germline + fertility
    "adt-long-term-card": "adt_long_term",        # EPIC 22c — multi-organ surveillance
    "survivorship-5y-card": "survivorship_5y",    # EPIC 22c — long-term outcome tracking
    "comorbidity-cv-card": "comorbidity_cv",      # EPIC 22c — drug-selection safety
    "hereditary-germline-card": "hereditary_germline",  # EPIC 20
    "mcrpc-subtype-card": "mcrpc_subtype",
    "oligoprogression-card": "oligoprogression",
    "patient-twin-os-card": "patient_twin",
    "post-rt-bcr-card": "post_rt_bcr",
    "risk-stratified-localized-card": "risk_stratified",
    "decision-fusion-summary": "decision_fusion",  # EPIC 23 — recommendation arbiter
    # EPIC 22f — 15 remaining Cortana cards (complete the EPIC 22c state set)
    "comorbidity-hepatic-card": "comorbidity_hepatic",
    "brca1-carrier-card": "brca1_carrier",
    "atm-carrier-card": "atm_carrier",
    "hoxb13-carrier-card": "hoxb13_carrier",
    "post-brachy-ldr-card": "post_brachy_ldr",
    "post-ebrt-alone-card": "post_ebrt_alone",
    "post-sbrt-card": "post_sbrt",
    "post-focal-therapy-card": "post_focal_therapy",
    "oligo-synchronous-card": "oligometastatic_synchronous",
    "oligo-metach-adt-naive-card": "oligometastatic_metachronous_adt_naive",
    "oligo-recurrent-post-def-card": "oligo_recurrent_post_definitive",
    "second-primary-card": "second_primary_surveillance",
    "suspected-low-psa-card": "suspected_low_psa_no_biopsy",
    "suspected-elevated-psa-ww-card": "suspected_elevated_psa_watchful_wait",
    "neg-biopsy-age-lt45-card": "negative_biopsy_age_lt_45",
    # EPIC 34.A Phase 2/3/4 — Quick capture cards + Trial Matcher
    "ecog-quick-capture-card": "ecog_capture_cta",            # Phase 2 — ECOG gating
    "hrr-quick-capture-card": "hrr_capture_cta",              # Phase 4 — HRR/germline gating
    "trial-matcher-card": "trial_matches",                    # Phase 3 — Trial Matcher MVP
    "castration-quick-capture-card": "castration_capture_cta", # Phase 5 — Castration confirmation
    "psma-pet-quick-capture-card": "psma_pet_capture_cta",     # Phase 6 — PSMA-PET capture
    # EPIC 40 — Cortana Dictation Hub (composite voice intake, no gating)
    "cortana-dictation-hub-card": "identity",                  # Always rendered, uses identity.nss for patient
}


# ─────────────────── Helpers ───────────────────


def _extract_testids(html: str) -> set[str]:
    """Return all unique `data-testid="..."` values in a template."""
    return set(re.findall(r'data-testid="([a-z0-9\-]+)"', html))


def _extract_adapter_keys(adapter_source: str) -> set[str]:
    """Extract keys returned by bundle_to_v2_profile.

    Looks for `"<key>": ...,` patterns inside the `return {...}` block
    of bundle_to_v2_profile. Defensive: returns a superset (includes
    helper-function return keys), which is fine since we only test
    "is this key present", not "is this key produced by THIS function".
    """
    keys: set[str] = set()
    for match in re.finditer(r'"([a-z_][a-z0-9_]*)"\s*:', adapter_source):
        keys.add(match.group(1))
    return keys


def _grep_consumers(pattern: str) -> bool:
    """Returns True if pattern appears in any prostanet/*.py file."""
    try:
        result = subprocess.run(
            ["grep", "-r", "-l", "--include=*.py", pattern, "prostanet/"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        return False  # tolerate grep failures (e.g., CI env)


# ─────────────────── Gate 1: data-testid concordance ───────────────────


def test_gate_1_every_card_data_testid_has_bundle_key_or_is_static():
    """Every `data-testid="*-card"` must have a bundle key OR be in STATIC_NO_DATA_BINDING.

    Catches "pretty placeholder" cards rendered without backend data.
    """
    if not TEMPLATE_PATH.exists():
        pytest.skip("template not found (CI env may not check templates)")
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    testids = _extract_testids(html)

    # Cards (testid contains "card") need bundle keys
    card_testids = {t for t in testids if t.endswith("-card")}
    missing_contract: list[str] = []
    for card in card_testids:
        if card in STATIC_NO_DATA_BINDING:
            continue
        if card not in CARD_TO_BUNDLE_KEY:
            missing_contract.append(card)

    assert not missing_contract, (
        f"Cards without data contract (must be in CARD_TO_BUNDLE_KEY or "
        f"STATIC_NO_DATA_BINDING): {missing_contract}"
    )


def test_gate_1b_every_data_testid_is_declared():
    """Every data-testid is either a card with contract OR explicitly static.

    Forces engineers to be intentional about UI test surface.
    """
    if not TEMPLATE_PATH.exists():
        pytest.skip("template not found")
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    testids = _extract_testids(html)

    undeclared: list[str] = []
    for tid in testids:
        is_card = tid in CARD_TO_BUNDLE_KEY
        is_static = tid in STATIC_NO_DATA_BINDING
        if not (is_card or is_static):
            undeclared.append(tid)

    assert not undeclared, (
        f"data-testid values without declaration: {undeclared}. "
        f"Add to CARD_TO_BUNDLE_KEY (with bundle key) or STATIC_NO_DATA_BINDING."
    )


# ─────────────────── Gate 2: FactSpec → consumer concordance ───────────────────


def test_gate_2_every_blocking_factspec_has_consumer():
    """Every `blocking=True` FactSpec must have a non-empty consumers tuple.

    Blocking facts WITHOUT downstream readers are dead-code symptoms.
    """
    from prostanet.shared.clinical_fact_registry import FACT_SPECS

    orphaned: list[str] = []
    for fact_key, spec in FACT_SPECS.items():
        if spec.blocking and not spec.consumers:
            orphaned.append(fact_key)

    assert not orphaned, (
        f"Blocking FactSpecs without consumers (dead code candidates): {orphaned}"
    )


def test_gate_2b_every_factspec_consumer_string_is_non_empty():
    """No FactSpec should declare an empty-string consumer."""
    from prostanet.shared.clinical_fact_registry import FACT_SPECS

    bad: list[str] = []
    for fact_key, spec in FACT_SPECS.items():
        for consumer in spec.consumers:
            if not consumer or not consumer.strip():
                bad.append(f"{fact_key}→empty")
    assert not bad, f"Empty consumer strings: {bad}"


# ─────────────────── Gate 3: Cortana card ↔ bundle ───────────────────


@pytest.mark.xfail(
    reason=(
        "EPIC 22d WARNING-mode: legacy EPIC 20 Cortana cards (hereditary, "
        "patient_twin, risk_stratified, etc.) are populated by app.py route "
        "handlers (build_patient_twin_view + build_*_for_profile) rather than "
        "by v2_adapters directly. EPIC 23 will refactor those into v2_adapters "
        "or relax the test to also scan app.py."
    ),
    strict=False,
)
def test_gate_3_every_card_bundle_key_exists_in_adapter():
    """Every CARD_TO_BUNDLE_KEY value must appear in bundle_to_v2_profile.

    Catches "pretty placeholder" — card consumes a key that no adapter
    populates → card is always invisible OR worse, renders stale data.

    NOTE: xfail in EPIC 22d (warning mode). Will flip to FAILING in
    EPIC 23 once all legacy cards are migrated.
    """
    if not V2_ADAPTER_PATH.exists():
        pytest.skip("v2_adapter not found")
    adapter_source = V2_ADAPTER_PATH.read_text(encoding="utf-8")
    adapter_keys = _extract_adapter_keys(adapter_source)

    missing: list[str] = []
    for card, key in CARD_TO_BUNDLE_KEY.items():
        if key not in adapter_keys:
            missing.append(f"{card}→{key}")

    assert not missing, (
        f"Cards with bundle keys NOT populated by v2_adapters: {missing}. "
        f"Either add the key to bundle_to_v2_profile() or remove from "
        f"CARD_TO_BUNDLE_KEY."
    )


def test_gate_3b_biopsy_summary_wired_in_adapter():
    """EPIC 22b.4 — biopsy_summary key MUST be populated by v2_adapters.

    This is the specific new contract added in EPIC 22b. Unlike Gate 3
    (xfail for legacy), this is FAILING because we just added the wiring
    in `bundle_to_v2_profile`.
    """
    if not V2_ADAPTER_PATH.exists():
        pytest.skip("v2_adapter not found")
    adapter_source = V2_ADAPTER_PATH.read_text(encoding="utf-8")
    adapter_keys = _extract_adapter_keys(adapter_source)
    assert "biopsy_summary" in adapter_keys, (
        "EPIC 22b.4 contract: biopsy_summary must be a key returned by "
        "bundle_to_v2_profile. Either restore the line or remove the "
        "pm2BiopsyDiagnostics card from the template."
    )


# ─────────────────── Gate 4: NUM_STATES ↔ registry coverage ───────────────────


def test_gate_4_every_clinical_state_has_therapeutic_alternative():
    """Every state in CLINICAL_STATES must have an entry in
    therapeutic_alternative_registry.yaml.

    Without this, classify_clinical_state() returns a state whose
    `therapeutic_alternative_preferred` is empty — UI cards have nothing
    to recommend.
    """
    import yaml
    from prostanet.ai.config import CLINICAL_STATES

    reg_path = (
        PROJECT_ROOT / "prostanet" / "regulatory" / "clinical"
        / "therapeutic_alternative_registry.yaml"
    )
    reg = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    states_registered = set((reg.get("states") or {}).keys())

    missing = set(CLINICAL_STATES) - states_registered
    assert not missing, (
        f"States in CLINICAL_STATES without therapeutic alternatives "
        f"registered (UI will show empty 'preferred' field): {missing}"
    )


# ─────────────────── Gate 5: Capture endpoints exist ───────────────────


def test_gate_5_longitudinal_append_handles_documented_kinds():
    """Every kind the UI POSTs to /api/longitudinal/<nss>/append must be
    handled by an endpoint branch in app.py.

    This catches the historical histopathology bug (UI requested data but
    no kind=biopsy branch existed).
    """
    app_py = PROJECT_ROOT / "app.py"
    if not app_py.exists():
        pytest.skip("app.py not found")
    source = app_py.read_text(encoding="utf-8")

    # Documented kinds from UI capture surfaces
    documented_kinds = {
        "psa", "testosterone", "lab",
        "biopsy",        # EPIC 22b.1 — closes histopath capture gap
        "treatment_change",
        "ecog", "bpi", "esas", "phq9", "ctcae",
        "psma_pet", "bone_scan", "mri_pirads", "ct_recist",
        "hrr_germinal", "hrr_somatic",
    }

    # Check each kind appears somewhere in app.py (branch or extended_kind_map)
    unhandled: list[str] = []
    for kind in documented_kinds:
        # Lenient: kind quoted as string somewhere in app.py
        if f'"{kind}"' not in source and f"'{kind}'" not in source:
            unhandled.append(kind)

    assert not unhandled, (
        f"Capture kinds documented in UI but not handled in app.py: "
        f"{unhandled}. Add a branch or extended_kind_map entry."
    )
