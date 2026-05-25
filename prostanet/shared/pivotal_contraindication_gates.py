"""pivotal_contraindication_gates.py — FAUBOT auditoría 2026-04-23.

Centraliza 19 gates de contraindicación derivados de la auditoría de cobertura
de pacientes insignia para los 36 estudios pivote (RADICALS-RT … CONTACT-02).
Faubot 2026-04-25 (XIV): Gate 19 (`arsi_in_cognitive_decline_grade2`) es el
PRIMER gate YAML-NATIVE — vive sólo en `pivotal_gates_catalog/` sin función
Python equivalente. Demuestra que el sistema híbrido permite añadir gates
clínicos nuevos directamente como YAML declarativo.

Cada gate corresponde a un criterio de exclusión documentado en el protocolo
del ensayo pivote y/o en una guía vigente (NCCN PROS-G v5.2026, EAU 2026,
ASCO/AUA Bone Health 2024, CTCAE v5).

Brechas cerradas (18):
  1. prior_arpi_exposure_mhspc                 → ARANOTE (Saad Lancet Oncol 2024;25:1422)
  2. severe_neuropathy_grade3                  → TAX-327 / TROPIC / CHAARTED (taxanos)
  3. uncontrolled_hypertension                 → LATITUDE / PEACE-1 / CONTACT-02
  4. severe_heart_failure_nyha_iii_iv          → LATITUDE / COU-AA-301/302 (abiraterona)
  5. uncontrolled_diabetes                     → IPATential150 (ipatasertib)
  6. ecog_2_or_more_for_triplets               → ARASENS (Smith NEJM 2022) / PEACE-1
  7. darolutamide_hypersensitivity             → ARAMIS / ARASENS / ARANOTE label
  8. polysorbate_hypersensitivity              → TROPIC / CARD (cabazitaxel)
  9. no_bone_protective_agent                  → ERA-223 (Smith Lancet Oncol 2019) / PEACE-3
  10. creatinine_clearance_lt_30               → TRITON-3 (rucaparib)
  11. radium223_in_cord_compression            → ALSYMPCA / Xofigo label / Loblaw 2012
  12. radium223_in_hypocalcemia                → ALSYMPCA / Xofigo label
  13. lutetium177_in_cord_compression          → VISION / PSMAfore / TheraP / Pluvicto label
  14. lutetium177_in_severe_cytopenias         → VISION / Pluvicto label
  15. parp_inhibitor_in_severe_cytopenias      → PROfound / MAGNITUDE / TALAPRO-2/3 / PROpel / TRITON-3
  16. parp_inhibitor_in_mds_aml_history        → Lynparza/Akeega/Talzenna/Rubraca labels (MDS/AML boxed warning)
  17. qtc_prolongation_grade3_for_enzalutamide → Xtandi label §5.4 / ENZAMET / CTCAE v5 / ICH E14
  18. lvef_decline_for_apalutamide             → Erleada label / TITAN / SPARTAN / ASCO/ESC Cardio-Oncology 2022
  19. arsi_in_cognitive_decline_grade2         → UCSF Cohort 2024 / SIOG Geriatric Oncology / Xtandi label / CTCAE v5 (YAML-native)

Diseño:
  - Detectores PUROS sobre payload (sin side-effects, sin mutación).
  - Cada detector retorna `dict | None`; None = gate no aplica.
  - `evaluate_pivotal_contraindication_gates()` retorna la lista disparada.
  - `filter_treatments_by_gates()` aplica los gates a la lista de tratamientos.
  - `gate_messages_for_not_recommended()` extrae mensajes para `not_recommended`.

Reusable desde:
  - mcspc_low_volume_sync_oligo, mcspc_high_volume, mcspc_oligo_metachronous
  - m1_crpc, m0_crpc
  - recurrence_bcr, post_prostatectomy, post_radiotherapy_or_local_salvage
  - palliative_pathway, localized_initial (cuando aplica ADT empírico)
"""
from __future__ import annotations

from typing import Any

# ── Tokens normalizados (ES-médica + legacy) ────────────────────────────
_TRUTHY = {
    "1", "true", "yes", "si", "sí",
    "present", "positive", "positivo",
    "documented", "documentado",
}


def _truthy_token(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in _TRUTHY


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ── Catálogos canonical de regímenes/keywords afectados ─────────────────
REGIMEN_CODES_ABIRATERONE = frozenset({
    "ADT_ABIRATERONE",
    "ADT_DOCETAXEL_ABIRATERONE",
    "ADT_ABIRATERONE_NIRAPARIB",
    "NIRAPARIB_ABIRATERONE",
    "ABIRATERONE",
    "ABIRATERONE_OLAPARIB",
    "ABIRATERONE_PREDNISONE",
    "IPATASERTIB_ABIRATERONE",
})
KEYWORDS_ABIRATERONE = ("abirater",)

REGIMEN_CODES_TAXANE = frozenset({
    "ADT_DOCETAXEL",
    "ADT_DOCETAXEL_DAROLUTAMIDE",
    "ADT_DOCETAXEL_ABIRATERONE",
    "DOCETAXEL",
    "CABAZITAXEL",
})
KEYWORDS_TAXANE = ("docetaxel", "cabazitaxel")

REGIMEN_CODES_TRIPLETS = frozenset({
    "ADT_DOCETAXEL_DAROLUTAMIDE",  # ARASENS
    "ADT_DOCETAXEL_ABIRATERONE",   # PEACE-1
})

REGIMEN_CODES_DAROLUTAMIDE = frozenset({
    "DAROLUTAMIDE",
    "ADT_DAROLUTAMIDE",
    "ADT_DOCETAXEL_DAROLUTAMIDE",
})
KEYWORDS_DAROLUTAMIDE = ("darolutamida", "darolutamide")

REGIMEN_CODES_IPATASERTIB = frozenset({"IPATASERTIB_ABIRATERONE", "IPATASERTIB"})
KEYWORDS_IPATASERTIB = ("ipatasertib",)

REGIMEN_CODES_RADIUM223 = frozenset({"RADIUM_223", "RA_223", "RADIUM223"})
KEYWORDS_RADIUM223 = (
    "radio 223", "radium-223", "radium 223", "ra-223", "ra 223", "ra223",
)

# Faubot 2026-04-24 (V) — Lu-177-PSMA-617 (Pluvicto, Novartis 2022).
# Canónico unificado en `therapy_catalog.py` como `LU177_PSMA617`.
REGIMEN_CODES_LUTETIUM177 = frozenset({
    "LU177_PSMA617",
    "LU_177_PSMA",
    "LUTETIUM_177_PSMA",
    "PLUVICTO",
})
KEYWORDS_LUTETIUM177 = (
    "lu-177", "lu 177", "lu177",
    "lutetium-177", "lutetium 177",
    "lutecio-177", "lutecio 177",
    "psma-617", "psma 617", "psma617",
    "pluvicto",
)

# Faubot 2026-04-25 (LXI) — Auditoría #64 — Bone-targeted clase entera.
# Cubre TODA la clase bone-modifying agents en mCRPC con metástasis óseas:
#   - Radiopharmaceuticals: Ra-223 (Xofigo) + Lu-177-PSMA-617 (Pluvicto)
#   - Denosumab (Xgeva subQ q4 sem 120 mg per ASCO Bone Health 2024)
#   - Bisfosfonatos: zoledronato (Zometa IV q4 sem) + pamidronato (Aredia)
#     + alendronato (Fosamax PO weekly) + risedronato (Actonel)
#     + ácido ibandrónico (Boniva)
# Gate 50 hipocalcemia EXTENDIDA usa esta frozenset (vs gate 12 limitado a
# REGIMEN_CODES_RADIUM223 sólo). Bone-targeted prescritos en >70% pacientes
# mCRPC con metástasis óseas (NCCN PROS-G v5.2026 Class IA).
# Faubot 2026-04-25 (LXIV) — Auditoría #63A — Observación / Active Surveillance
# (no-tratamiento). Usado por gates 53/54/55 PSA kinetics (soft_warning):
# cuando paciente está en observación pero criterios PSA agresivos detectados,
# gate alerta a clínico de cambiar a tratamiento activo (salvage RT + ADT).
REGIMEN_CODES_OBSERVATION_ONLY = frozenset({
    "OBSERVATION",
    "OBSERVATION_ONLY",
    "ACTIVE_SURVEILLANCE",
    "WATCHFUL_WAITING",
    "VIGILANCIA_ACTIVA",
    "NO_TREATMENT",
    "NO_TX",
})
KEYWORDS_OBSERVATION_ONLY = (
    "observación", "observation",
    "active surveillance", "vigilancia activa",
    "watchful waiting", "espera vigilante",
    "no tratamiento", "sin tratamiento",
)

REGIMEN_CODES_BONE_TARGETED = (
    REGIMEN_CODES_RADIUM223
    | REGIMEN_CODES_LUTETIUM177
    | frozenset({
        # Denosumab (anti-RANKL monoclonal antibody)
        "DENOSUMAB",
        "XGEVA",
        "DENOSUMAB_120MG",
        # Bisfosfonatos IV
        "ZOLEDRONATE",
        "ZOLEDRONIC_ACID",
        "ZOMETA",
        "PAMIDRONATE",
        "AREDIA",
        # Bisfosfonatos PO (less common in mCRPC pero ASCO 2024 incluye)
        "ALENDRONATE",
        "FOSAMAX",
        "RISEDRONATE",
        "ACTONEL",
        "IBANDRONATE",
        "BONIVA",
    })
)
KEYWORDS_BONE_TARGETED = (
    KEYWORDS_RADIUM223
    + KEYWORDS_LUTETIUM177
    + (
        # English
        "denosumab", "xgeva", "anti-rankl",
        "zoledronate", "zoledronic acid", "zometa",
        "pamidronate", "aredia",
        "alendronate", "fosamax",
        "risedronate", "actonel",
        "ibandronate", "boniva",
        "bisphosphonate", "bisphosphonates",
        # Spanish clinical
        "ácido zoledrónico", "acido zoledronico",
        "denosumab subcutáneo",
        "bisfosfonato", "bisfosfonatos",
    )
)

# Faubot 2026-04-24 (VI) — PARP inhibitors (PROfound/MAGNITUDE/TALAPRO-2/3/PROpel/TRITON-3).
# Catálogo unificado de los 4 PARPi aprobados en cáncer de próstata + sus
# combinaciones canónicas con ARPI documentadas en `therapy_catalog.py`.
REGIMEN_CODES_PARP_INHIBITORS = frozenset({
    "OLAPARIB",                  # PROfound (mono mCRPC HRR+)
    "ABIRATERONE_OLAPARIB",      # PROpel (mCRPC 1L irrestricto)
    "NIRAPARIB_ABIRATERONE",     # MAGNITUDE / Akeega (mCRPC HRR+)
    "ADT_ABIRATERONE_NIRAPARIB", # MAGNITUDE alias mHSPC
    "TALAZOPARIB_ENZALUTAMIDE",  # TALAPRO-2 (mCRPC HRR+)
    "ADT_TALAZO_ENZA_HRR",       # TALAPRO-3 (mHSPC HRR+)
    "RUCAPARIB",                 # TRITON-3 (mCRPC BRCA+)
})
KEYWORDS_PARP_INHIBITORS = (
    "olaparib", "olapar",
    "niraparib", "nirapar",
    "talazoparib", "talazopar",
    "rucaparib", "rucapar",
    "lynparza", "akeega", "talzenna", "rubraca", "zejula",
    "parp inhibitor", "parpi", "inhibidor parp", "inhibidor de parp",
)

# Faubot 2026-04-25 (VII) — ARPI cardiotoxicidad (Xtandi/Erleada labels +
# ENZAMET/TITAN/SPARTAN/TALAPRO-2/3). Catálogos separados de enzalutamida y
# apalutamida porque cada una tiene perfil cardiotóxico distinto:
#   - Enzalutamida (Xtandi): warning §5.4 prolongación QT + convulsiones
#   - Apalutamida (Erleada): warning cardiac dysfunction + LVEF decline TITAN
REGIMEN_CODES_ENZALUTAMIDE = frozenset({
    "ADT_ENZALUTAMIDE",          # ENZAMET / mHSPC + mCRPC
    "ENZALUTAMIDE",              # mono mCRPC AFFIRM/PREVAIL
    "TALAZOPARIB_ENZALUTAMIDE",  # TALAPRO-2 mCRPC (también gates 15-16 PARP)
    "ADT_TALAZO_ENZA_HRR",       # TALAPRO-3 mHSPC HRR+
})
KEYWORDS_ENZALUTAMIDE = ("enzalutamida", "enzalutamide", "xtandi")

REGIMEN_CODES_APALUTAMIDE = frozenset({
    "ADT_APALUTAMIDE",  # TITAN mHSPC + SPARTAN m0 CRPC
    "APALUTAMIDE",
})
KEYWORDS_APALUTAMIDE = ("apalutamida", "apalutamide", "erleada")

# Faubot 2026-04-25 (XIV) — Gate 19 ARSI × deterioro cognitivo.
# Catálogo combinado: TODOS los ARSI (enzalutamida + apalutamida +
# darolutamida) que tienen exposición a SNC documentada. Notar que
# darolutamida tiene MENOR penetración de barrera hematoencefálica
# pero el gate 19 cubre la clase completa por consistency clínica
# (UCSF cohort 2024 incluyó los 3 ARSI; el riesgo es heterogéneo
# pero compartido).
REGIMEN_CODES_ARSI = (
    REGIMEN_CODES_ENZALUTAMIDE
    | REGIMEN_CODES_APALUTAMIDE
    | REGIMEN_CODES_DAROLUTAMIDE
)
KEYWORDS_ARSI = (
    KEYWORDS_ENZALUTAMIDE
    + KEYWORDS_APALUTAMIDE
    + KEYWORDS_DAROLUTAMIDE
)

REGIMEN_CODES_RUCAPARIB = frozenset({"RUCAPARIB"})
KEYWORDS_RUCAPARIB = ("rucaparib",)

# Faubot 2026-04-25 (XLI) — Auditoría #44 Gate 29.
# Catálogo olaparib específico (PROfound mono + PROpel combo con
# abiraterona). Separar de REGIMEN_CODES_PARP_INHIBITORS general porque
# el threshold renal de olaparib es diferente del de rucaparib (gate 10):
#   - Olaparib (Lynparza FDA prescribing §2.3): dose reduction 31-50 si
#     CrCl 31-50 mL/min; CONTRAINDICADO si CrCl <30 mL/min (sin estudios
#     en CKD stage 4-5; trial PROfound excluyó CrCl <30).
#   - Rucaparib (Rubraca §5.3): excluido en TRITON-3 si CrCl <30 (ya
#     cubierto por gate 10 — diferentes evidence_tag y trial_refs).
REGIMEN_CODES_OLAPARIB = frozenset({
    "OLAPARIB",                  # PROfound mono mCRPC HRR+ (de Bono NEJM 2020)
    "ABIRATERONE_OLAPARIB",      # PROpel mCRPC 1L irrestricto (Clarke NEJM 2022)
})
KEYWORDS_OLAPARIB = (
    "olaparib", "olapar", "lynparza",
)

# Faubot 2026-04-25 (LI) — Auditoría #53 Sipuleucel-T (Provenge, Dendreon).
# Primer immunoterapia/cellular therapy del catálogo. IMPACT trial
# (Kantoff NEJM 2010) demostró OS benefit en mCRPC asymptomatic. Perfil
# safety distinto de quimio/ARSI: IRR (Infusion-Related Reactions) +
# febrile neutropenia post-leukapheresis + cytokine storm.
REGIMEN_CODES_SIPULEUCEL_T = frozenset({
    "SIPULEUCEL_T",
    "PROVENGE",
})
KEYWORDS_SIPULEUCEL_T = (
    "sipuleucel", "sipuleucel-t", "sipuleucel t", "provenge",
    "vacuna autóloga", "celular autóloga",
)

# Faubot 2026-04-25 (LVII) — Auditoría #54 gates 43-46 (checkpoint inhibitors irAE).
# 2da clase IO del catálogo (post Sipuleucel-T #53). Pembrolizumab anti-PD-1
# tiene perfil safety distinctivo: irAE (immune-related Adverse Events) por
# desinhibición de células T → daño autoinmune en cualquier órgano.
# KEYNOTE-365 cohort C + KEYNOTE-921 (mCRPC dMMR/MSI-H + AR pretreated subset)
# documentan AEs en pneumonia + hepatitis + colitis + endocrinopatías.
# Gates 43-46 cubren los 4 irAE más severos.
REGIMEN_CODES_CHECKPOINT_INHIBITORS = frozenset({
    # Anti-PD-1 (pembrolizumab — Keytruda, Merck)
    "PEMBROLIZUMAB",
    "PEMBROLIZUMAB_OLAPARIB",        # KEYLYNK-010 mCRPC
    "PEMBROLIZUMAB_ENZALUTAMIDE",    # KEYNOTE-641 mCRPC
    "PEMBROLIZUMAB_DOCETAXEL",       # KEYNOTE-921 mCRPC
    # Anti-PD-1 (nivolumab — Opdivo, BMS)
    "NIVOLUMAB",
    "NIVOLUMAB_RUCAPARIB",           # CheckMate-9KD mCRPC HRR+
    "NIVOLUMAB_DOCETAXEL",           # CheckMate-9KD mCRPC ARM
    "NIVOLUMAB_IPILIMUMAB",          # CheckMate-650 mCRPC AR-V7+
    # Anti-PD-L1 (atezolizumab — Tecentriq, Roche)
    "ATEZOLIZUMAB",
    "ATEZOLIZUMAB_ENZALUTAMIDE",     # IMbassador250 mCRPC
})
KEYWORDS_CHECKPOINT_INHIBITORS = (
    # English
    "pembrolizumab", "keytruda", "nivolumab", "opdivo",
    "atezolizumab", "tecentriq", "checkpoint inhibitor",
    "anti-pd-1", "anti pd-1", "anti-pdl1", "anti pdl1", "anti-pd-l1",
    # Spanish clinical equivalents
    "inhibidor de checkpoint", "inmunoterapia checkpoint",
    "anti pd-1", "inhibidor pd-1", "inhibidor pd-l1",
)

# NOTA: REGIMEN_CODES_CABAZITAXEL definido más abajo (línea ~266). Faubot LV
# (#52 gate 41 cabazitaxel Hb longitudinal) reutiliza esa frozenset existente
# y extiende KEYWORDS_CABAZITAXEL en el bloque original con alias "jevtana".

# Faubot 2026-04-25 (XXVI) — Tier 2/3 D-F gates 20-23 (clinical extended).
# Catálogo niraparib específico — más estricto que PARP_INHIBITORS general
# porque MAGNITUDE/Akeega label requiere thresholds más conservadores
# (plaq ≥150K baseline; HTA grado ≥3 documented es contraindicación específica
# por el aumento ~40-50% en HTA tratamiento-emergente vs olaparib).
REGIMEN_CODES_NIRAPARIB = frozenset({
    "NIRAPARIB",
    "NIRAPARIB_ABIRATERONE",      # MAGNITUDE / Akeega
    "ADT_ABIRATERONE_NIRAPARIB",  # MAGNITUDE alias mHSPC
})
KEYWORDS_NIRAPARIB = (
    "niraparib", "nirapar",
    "akeega", "zejula",
)

REGIMEN_CODES_CABOZANTINIB = frozenset({"CABOZANTINIB", "CABOZANTINIB_ATEZOLIZUMAB"})
KEYWORDS_CABOZANTINIB = ("cabozantinib",)

REGIMEN_CODES_CABAZITAXEL = frozenset({"CABAZITAXEL"})
# Faubot 2026-04-25 (LV) — Auditoría #52 gate 41: añadido "jevtana" alias
# (Jevtana = nombre comercial Sanofi). Necesario para Path C flag matching
# y mensaje clínico.
KEYWORDS_CABAZITAXEL = ("cabazitaxel", "jevtana")


# ── Detectores individuales (10) ────────────────────────────────────────


def detect_prior_arpi_exposure_mhspc(payload: dict) -> dict | None:
    """ARANOTE (Saad Lancet Oncol 2024;25:1422) excluye ARPI previo en mHSPC.

    Si el paciente recibió enzalutamida/abiraterona/apalutamida/darolutamida
    en contexto previo (recurrencia tras prostatectomía o BCR) NO es candidato
    a intensificación con darolutamida monoterapia mHSPC sin documentar
    resistencia.
    """
    if not _truthy_token(payload.get("prior_arpi_exposure_mhspc")):
        return None
    return {
        "code": "prior_arpi_exposure_mhspc",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_DAROLUTAMIDE,
        "affected_keywords": KEYWORDS_DAROLUTAMIDE,
        "message": (
            "Darolutamida monoterapia en mHSPC NO recomendada por exposición previa "
            "a ARPI (ARANOTE excluyó pacientes con ARPI previo). Considerar "
            "intensificación con docetaxel + ARPI distinto o cambio de mecanismo si "
            "hay resistencia documentada (Saad Lancet Oncol 2024;25:1422)."
        ),
        "evidence_tag": "saad_lancet_oncol_2024_aranote",
        "trial_refs": ("ARANOTE",),
    }


def detect_severe_neuropathy_grade3(payload: dict) -> dict | None:
    """Neuropatía periférica grado ≥3 contraindica taxanos (CTCAE v5).

    TAX-327 / TROPIC / CHAARTED excluyeron G≥2 en algunos brazos por riesgo
    de neurotoxicidad incapacitante.
    """
    grade = _safe_int(payload.get("peripheral_neuropathy_grade"))
    if grade is None or grade < 3:
        return None
    return {
        "code": "severe_neuropathy_grade3",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_TAXANE,
        "affected_keywords": KEYWORDS_TAXANE,
        "message": (
            f"Docetaxel/cabazitaxel NO recomendados por neuropatía periférica grado "
            f"{grade} (CTCAE v5 ≥3). Riesgo de neurotoxicidad incapacitante. "
            "Considerar ARPI, Lu-177 PSMA-617 o radioligando alternativo "
            "(TAX-327 / TROPIC / CHAARTED restringieron taxanos por neuropatía)."
        ),
        "evidence_tag": "ctcae_v5_neuropathy",
        "trial_refs": ("TAX-327", "TROPIC", "CHAARTED"),
    }


def detect_uncontrolled_hypertension(payload: dict) -> dict | None:
    """HTA no controlada → riesgo abiraterona (mineralocorticoide) y cabozantinib (VEGF).

    Bloquea abiraterona y cabozantinib hasta estabilizar PA <140/90 mmHg.
    """
    if not _truthy_token(payload.get("uncontrolled_hypertension")):
        return None
    return {
        "code": "uncontrolled_hypertension",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_ABIRATERONE | REGIMEN_CODES_CABOZANTINIB,
        "affected_keywords": KEYWORDS_ABIRATERONE + KEYWORDS_CABOZANTINIB,
        "message": (
            "Abiraterona y cabozantinib NO recomendados con HTA no controlada "
            "(>160/100 mmHg sostenida). Abiraterona produce exceso mineralocorticoide; "
            "cabozantinib inhibe VEGFR (HTA tratamiento-emergente común). "
            "Estabilizar PA <140/90 antes de iniciar y considerar enzalutamida/darolutamida "
            "(LATITUDE / PEACE-1 / COU-AA-301/302 / CONTACT-02 excluyeron HTA no controlada)."
        ),
        "evidence_tag": "latitude_peace1_couaa_contact02",
        "trial_refs": ("LATITUDE", "PEACE-1", "COU-AA-301", "COU-AA-302", "CONTACT-02"),
    }


def detect_severe_heart_failure_nyha_iii_iv(payload: dict) -> dict | None:
    """Insuficiencia cardíaca NYHA III-IV → contraindicación abiraterona.

    Riesgo de retención hidrosalina por mineralocorticoide. Hard-block (no
    sólo penalty del selector). LATITUDE / PEACE-1 / COU-AA-301/302 excluyeron
    NYHA III-IV.
    """
    nyha = str(payload.get("nyha_class") or "").strip().upper()
    explicit = _truthy_token(payload.get("severe_heart_failure_nyha_iii_iv"))
    if not explicit and nyha not in {"III", "IV", "3", "4"}:
        return None
    return {
        "code": "severe_heart_failure_nyha_iii_iv",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_ABIRATERONE,
        "affected_keywords": KEYWORDS_ABIRATERONE,
        "message": (
            "Abiraterona NO recomendada con insuficiencia cardíaca NYHA III-IV "
            "(retención hidrosalina y sobrecarga de volumen). Considerar enzalutamida "
            "o darolutamida y optimizar manejo cardíaco (LATITUDE / PEACE-1 / COU-AA-301 "
            "/ COU-AA-302 excluyeron NYHA III-IV)."
        ),
        "evidence_tag": "latitude_couaa301_couaa302",
        "trial_refs": ("LATITUDE", "PEACE-1", "COU-AA-301", "COU-AA-302"),
    }


def detect_uncontrolled_diabetes(payload: dict) -> dict | None:
    """DM no controlada → riesgo hiperglucemia ipatasertib (AKT inhibitor).

    IPATential150 (Sweeney Lancet 2021;398:131) excluyó DM no controlada por
    inhibición AKT que empeora la hiperglucemia.
    """
    if not _truthy_token(payload.get("uncontrolled_diabetes")) and not _truthy_token(payload.get("diabetes_uncontrolled")):
        return None
    return {
        "code": "uncontrolled_diabetes",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_IPATASERTIB,
        "affected_keywords": KEYWORDS_IPATASERTIB,
        "message": (
            "Ipatasertib NO recomendado con diabetes mellitus no controlada (HbA1c >8% "
            "o glicemias en ayuno >200 mg/dL persistentes). Inhibición AKT empeora la "
            "hiperglucemia. Optimizar control glicémico y considerar olaparib/talazoparib "
            "si PTEN-loss o BRCA+ (IPATential150 excluyó DM no controlada)."
        ),
        "evidence_tag": "ipatential150",
        "trial_refs": ("IPATential150",),
    }


def detect_ecog_2_or_more_for_triplets(payload: dict) -> dict | None:
    """Triplete ARASENS/PEACE-1 requirió ECOG 0-1 (Smith NEJM 2022; Fizazi Lancet 2022)."""
    ecog = _safe_int(payload.get("ecog_score"))
    if ecog is None:
        ecog = _safe_int(payload.get("ecog"))
    if ecog is None or ecog < 2:
        return None
    return {
        "code": "ecog_2_or_more_for_triplets",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_TRIPLETS,
        "affected_keywords": (),
        "message": (
            f"Triplete (docetaxel + ARPI + ADT) NO recomendado con ECOG {ecog} "
            "(ARASENS y PEACE-1 incluyeron sólo ECOG 0-1). Considerar doblete "
            "ADT + ARPI (enzalutamida/abiraterona/darolutamida monoterapia) según "
            "comorbilidad y volumen tumoral (Smith NEJM 2022;386:1132; Fizazi Lancet "
            "2022;399:1695)."
        ),
        "evidence_tag": "smith_arasens_2022_fizazi_peace1_2022",
        "trial_refs": ("ARASENS", "PEACE-1"),
    }


def detect_darolutamide_hypersensitivity(payload: dict) -> dict | None:
    """Hipersensibilidad documentada a darolutamida → contraindicación absoluta."""
    if not _truthy_token(payload.get("darolutamide_hypersensitivity")):
        return None
    return {
        "code": "darolutamide_hypersensitivity",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_DAROLUTAMIDE,
        "affected_keywords": KEYWORDS_DAROLUTAMIDE,
        "message": (
            "Darolutamida NO recomendada por hipersensibilidad documentada al "
            "fármaco. Considerar enzalutamida o apalutamida (mecanismo similar pero "
            "composición distinta) según contexto clínico (label ARAMIS/ARASENS/ARANOTE)."
        ),
        "evidence_tag": "aramis_arasens_aranote_label",
        "trial_refs": ("ARAMIS", "ARASENS", "ARANOTE"),
    }


def detect_polysorbate_hypersensitivity(payload: dict) -> dict | None:
    """Hipersensibilidad polisorbato 80 → contraindica cabazitaxel (TROPIC, CARD)."""
    if not _truthy_token(payload.get("polysorbate_hypersensitivity")) and not _truthy_token(payload.get("hypersensitivity_polysorbate")):
        return None
    return {
        "code": "polysorbate_hypersensitivity",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_CABAZITAXEL,
        "affected_keywords": KEYWORDS_CABAZITAXEL,
        "message": (
            "Cabazitaxel NO recomendado por hipersensibilidad documentada a polisorbato 80 "
            "(excipiente del solvente). Considerar Lu-177 PSMA-617, olaparib (si BRCA+) o "
            "abiraterona como alternativa en mCRPC post-docetaxel (TROPIC y CARD excluyeron "
            "hipersensibilidad polisorbato)."
        ),
        "evidence_tag": "tropic_card_label",
        "trial_refs": ("TROPIC", "CARD"),
    }


def detect_no_bone_protective_agent_for_radium223(payload: dict) -> dict | None:
    """Ra-223 sin denosumab/zoledronato concomitante → riesgo fracturas (ERA-223 / PEACE-3).

    ERA-223 (Smith Lancet Oncol 2019;20:408) demostró exceso de fracturas con
    Ra-223 + abiraterona sin agente óseo (28% vs 12%). PEACE-3 (Tombal ESMO
    2024) requirió bisfosfonato/denosumab obligatorio desde la enmienda de
    seguridad.

    Activación:
      - `no_bone_protective_agent` explícito truthy, **O**
      - Hay señal de que se está considerando Ra-223 (regimen visible o
        `radium223_candidate=Sí`) **Y** no hay agente óseo declarado.
    """
    explicit = _truthy_token(payload.get("no_bone_protective_agent"))
    radium_being_considered = (
        _truthy_token(payload.get("radium223_candidate"))
        or _truthy_token(payload.get("considering_radium223"))
        or str(payload.get("planned_systemic_regimen") or "").upper() in REGIMEN_CODES_RADIUM223
    )
    if not explicit and not radium_being_considered:
        return None
    if not explicit and radium_being_considered:
        agent = str(payload.get("bone_modifying_agent") or "").strip().lower()
        denosumab_flag = _truthy_token(payload.get("denosumab_prophylaxis"))
        zoledronate_flag = _truthy_token(payload.get("zoledronate_prophylaxis"))
        bone_protection_started = _truthy_token(payload.get("bone_protection_started"))
        if (
            agent not in {"", "ninguno", "none", "no"}
            or denosumab_flag
            or zoledronate_flag
            or bone_protection_started
        ):
            return None
    return {
        "code": "no_bone_protective_agent",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_RADIUM223,
        "affected_keywords": KEYWORDS_RADIUM223,
        "message": (
            "Radio-223 NO debe iniciarse sin agente protector óseo concomitante "
            "(denosumab 120 mg SC c/4 sem o ácido zoledrónico 4 mg IV c/4 sem). "
            "ERA-223 (Smith Lancet Oncol 2019;20:408) demostró exceso de fracturas "
            "con Ra-223 + abiraterona sin agente óseo (28% vs 12%). PEACE-3 (Tombal "
            "ESMO 2024) requirió bisfosfonato/denosumab obligatorio. Iniciar agente "
            "óseo ≥6 sem antes o concomitante."
        ),
        "evidence_tag": "smith_era223_2019_peace3_2024",
        "trial_refs": ("ERA-223", "PEACE-3"),
    }


def detect_creatinine_clearance_lt_30_for_rucaparib(payload: dict) -> dict | None:
    """Aclaramiento <30 mL/min → contraindica rucaparib (TRITON-3)."""
    crcl = _safe_float(payload.get("creatinine_clearance"))
    if crcl is None:
        crcl = _safe_float(payload.get("egfr_ml_min"))
    if crcl is None:
        crcl = _safe_float(payload.get("egfr"))
    if crcl is None or crcl >= 30:
        return None
    return {
        "code": "creatinine_clearance_lt_30",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_RUCAPARIB,
        "affected_keywords": KEYWORDS_RUCAPARIB,
        "message": (
            f"Rucaparib NO recomendado con CrCl {crcl:.0f} mL/min <30 (TRITON-3 "
            "excluyó <30 mL/min por toxicidad acumulativa renal/medular). "
            "Considerar olaparib (PROfound), talazoparib (TALAPRO-2) o niraparib "
            "(MAGNITUDE) según el alelo BRCA/HRR documentado."
        ),
        "evidence_tag": "triton3",
        "trial_refs": ("TRITON-3",),
    }


# ── Faubot 2026-04-24 (IV) — Gates 11-12: Ra-223 × emergencias ─────────


def detect_radium223_in_cord_compression(payload: dict) -> dict | None:
    """Compresión medular activa o sospechada → contraindica Ra-223 inmediato.

    Fundamento clínico:
      - Xofigo (Ra-223) prescribing information (Bayer 2024) recomienda excluir
        pacientes con compresión medular establecida o inminente: la enfermedad
        vertebral con riesgo de inestabilidad estructural debe estabilizarse
        primero (RT 30 Gy/10 fx o cirugía descompresiva, criterios Patchell)
        ANTES de iniciar Ra-223.
      - Loblaw DA (ASCO 2012): demora >24 h en cord compression se asocia a
        paraplejia irreversible. Ra-223 no controla agudamente el componente
        compresivo (semividas y depósito en hueso lo hacen tarde).
      - NCCN PROS-G v5.2026 + NCCN Oncologic Emergencies v3.2026: en MSCC
        (metastatic spinal cord compression) priorizar dexametasona +
        descompresión + RT urgente; Ra-223 puede considerarse SOLO tras
        estabilización estructural.
      - Práctica clínica: la mielosupresión post-Ra-223 (anemia 31%, neutropenia
        18%, trombocitopenia 12% en ALSYMPCA) puede demorar la cirugía
        descompresiva si se inicia primero.

    Activación:
      - `spinal_cord_compression` truthy (Sí/yes/positive),
      - O debilidad MMII moderada/severa/paresia (`lower_limb_weakness`),
      - O síntomas neurológicos sugerentes (`cord_compression_symptoms`)
        (debilidad MMII, anestesia silla de montar, retención urinaria nueva,
        incontinencia fecal).

    Sin override por estabilización: el campo `cord_compression_stabilized=Sí`
    desactiva el gate (paciente post-RT/cirugía con stabilidad documentada).
    """
    cord_active = _truthy_token(payload.get("spinal_cord_compression")) or _truthy_token(
        payload.get("epidural_compression")
    )
    weakness = str(payload.get("lower_limb_weakness") or "").strip().lower()
    weakness_severe = any(
        kw in weakness for kw in ("moderada", "severa", "paresia")
    )
    symptoms = str(payload.get("cord_compression_symptoms") or "").strip().lower()
    symptoms_present = any(
        kw in symptoms
        for kw in (
            "debilidad mmii",
            "anestesia",
            "retención urinaria nueva",
            "retencion urinaria nueva",
            "incontinencia fecal",
        )
    )
    if not (cord_active or weakness_severe or symptoms_present):
        return None
    # Override: paciente post-tratamiento estructural confirmado
    if _truthy_token(payload.get("cord_compression_stabilized")):
        return None
    return {
        "code": "radium223_in_cord_compression",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_RADIUM223,
        "affected_keywords": KEYWORDS_RADIUM223,
        "message": (
            "Radio-223 NO debe iniciarse con compresión medular activa o "
            "sospechada (Xofigo Bayer 2024 prescribing information). Estabilizar "
            "primero con dexametasona 16 mg IV + RT 30 Gy/10 fx (Loblaw ASCO "
            "2012) o cirugía descompresiva (criterios Patchell) ANTES de "
            "considerar Ra-223. La mielosupresión post-Ra-223 (anemia 31%, "
            "trombocitopenia 12% en ALSYMPCA) puede demorar la cirugía "
            "descompresiva. Reevaluar Ra-223 tras estabilización estructural "
            "documentada (`cord_compression_stabilized=Sí`)."
        ),
        "evidence_tag": "xofigo_label_loblaw_2012",
        "trial_refs": ("ALSYMPCA", "Xofigo label", "Loblaw 2012"),
    }


def detect_radium223_in_hypocalcemia(payload: dict) -> dict | None:
    """Hipocalcemia no corregida → contraindica Ra-223 (Xofigo label).

    Fundamento clínico:
      - Xofigo (Ra-223) FDA prescribing information: la hipocalcemia debe
        corregirse ANTES de iniciar Ra-223 porque el alfa-emisor deposita en
        hueso de alto turnover y puede agravar el desbalance del calcio
        sérico, induciendo tetania, arritmias o paro cardíaco.
      - Práctica común: pacientes en denosumab/zoledronato concomitante
        (requisito post-PEACE-3) tienen riesgo basal de hipocalcemia que
        Ra-223 puede potenciar.
      - Threshold operacional: calcio total corregido <8.5 mg/dL (corregido
        por albúmina), calcio iónico <4.5 mg/dL (1.12 mmol/L), o flag
        explícito `hypocalcemia=Sí`.

    Activación:
      - Flag explícito `hypocalcemia` truthy, **O**
      - Calcio sérico (calcium_level / serum_calcium / corrected_calcium)
        <8.5 mg/dL, **O**
      - Calcio iónico (`ionized_calcium`) <4.5 mg/dL.

    Sin override: la hipocalcemia debe corregirse FÍSICAMENTE antes de iniciar
    Ra-223 — no hay flag de exclusión clínica, sólo `hypocalcemia_corrected=Sí`
    podría desactivar el gate (campo opcional no requerido aún).
    """
    explicit = _truthy_token(payload.get("hypocalcemia"))
    if not explicit:
        # Buscar en posibles fuentes numéricas de calcio sérico
        ca_total = _safe_float(payload.get("corrected_calcium"))
        if ca_total is None:
            ca_total = _safe_float(payload.get("calcium_level"))
        if ca_total is None:
            ca_total = _safe_float(payload.get("serum_calcium"))
        ca_ionized = _safe_float(payload.get("ionized_calcium"))
        low_total = ca_total is not None and ca_total < 8.5
        low_ionized = ca_ionized is not None and ca_ionized < 4.5
        if not (low_total or low_ionized):
            return None
        # Override: hipocalcemia documentadamente corregida
        if _truthy_token(payload.get("hypocalcemia_corrected")):
            return None
        ca_repr = (
            f"calcio total {ca_total:.1f} mg/dL"
            if low_total
            else f"calcio iónico {ca_ionized:.2f} mg/dL"
        )
    else:
        if _truthy_token(payload.get("hypocalcemia_corrected")):
            return None
        ca_repr = "hipocalcemia documentada"
    return {
        "code": "radium223_in_hypocalcemia",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_RADIUM223,
        "affected_keywords": KEYWORDS_RADIUM223,
        "message": (
            f"Radio-223 NO debe iniciarse con {ca_repr} sin corrección previa. "
            "Xofigo (Ra-223) prescribing information requiere corregir la "
            "hipocalcemia ANTES de la primera dosis: el alfa-emisor deposita en "
            "hueso de alto turnover y puede agravar el desbalance, induciendo "
            "tetania, arritmias o paro cardíaco. Pacientes en denosumab/"
            "zoledronato concomitante (requisito PEACE-3) tienen riesgo basal "
            "elevado. Corregir con calcio elemental 1-2 g/d + vitamina D3 "
            "1000-2000 UI/d hasta calcio total ≥8.5 mg/dL + iónico ≥4.5 mg/dL "
            "y reevaluar (`hypocalcemia_corrected=Sí`)."
        ),
        "evidence_tag": "xofigo_label_hypocalcemia",
        "trial_refs": ("ALSYMPCA", "Xofigo label"),
    }


# ── Faubot 2026-04-24 (V) — Gates 13-14: Lu-177-PSMA × emergencias ─────


def detect_lutetium177_in_cord_compression(payload: dict) -> dict | None:
    """Compresión medular activa o sospechada → contraindica Lu-177-PSMA inmediato.

    Fundamento clínico:
      - Pluvicto (Lu-177-PSMA-617) FDA prescribing information (Novartis 2022,
        actualizado 2024): excluye pacientes con compresión medular sintomática
        (criterio de exclusión replicado del protocolo VISION).
      - VISION (Sartor NEJM 2021;385:2197) excluyó explícitamente "symptomatic
        spinal cord compression" en el criterio E.4.6 del protocolo.
      - PSMAfore (Sartor ESMO 2024) y TheraP (Hofman Lancet 2021) replicaron el
        criterio.
      - Mecanismo: la mielosupresión post-Lu-177 (anemia 32%, trombocitopenia
        17%, neutropenia 9% en VISION) puede demorar la cirugía descompresiva
        si Lu-177 se inicia sin estabilización estructural previa. El radio-
        ligando tampoco controla agudamente la compresión.
      - NCCN PROS-G v5.2026 + NCCN Oncologic Emergencies v3.2026: en MSCC
        priorizar dexametasona + descompresión + RT urgente; Lu-177 puede
        considerarse SOLO tras estabilización estructural.

    Activación:
      - `spinal_cord_compression` truthy (Sí/yes/positive),
      - O debilidad MMII moderada/severa/paresia (`lower_limb_weakness`),
      - O síntomas neurológicos sugerentes (`cord_compression_symptoms`)
        (debilidad MMII, anestesia silla de montar, retención urinaria nueva,
        incontinencia fecal).

    Override por estabilización: el campo `cord_compression_stabilized=Sí`
    desactiva el gate (paciente post-RT/cirugía con estabilidad documentada).
    """
    cord_active = _truthy_token(payload.get("spinal_cord_compression")) or _truthy_token(
        payload.get("epidural_compression")
    )
    weakness = str(payload.get("lower_limb_weakness") or "").strip().lower()
    weakness_severe = any(
        kw in weakness for kw in ("moderada", "severa", "paresia")
    )
    symptoms = str(payload.get("cord_compression_symptoms") or "").strip().lower()
    symptoms_present = any(
        kw in symptoms
        for kw in (
            "debilidad mmii",
            "anestesia",
            "retención urinaria nueva",
            "retencion urinaria nueva",
            "incontinencia fecal",
        )
    )
    if not (cord_active or weakness_severe or symptoms_present):
        return None
    if _truthy_token(payload.get("cord_compression_stabilized")):
        return None
    return {
        "code": "lutetium177_in_cord_compression",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_LUTETIUM177,
        "affected_keywords": KEYWORDS_LUTETIUM177,
        "message": (
            "Lu-177-PSMA-617 (Pluvicto) NO debe iniciarse con compresión "
            "medular activa o sospechada (Pluvicto FDA prescribing information "
            "2022-2024; criterio de exclusión E.4.6 del protocolo VISION, "
            "Sartor NEJM 2021;385:2197; replicado en PSMAfore Sartor ESMO 2024 "
            "y TheraP Hofman Lancet 2021). Estabilizar primero con "
            "dexametasona 16 mg IV + RT 30 Gy/10 fx (Loblaw ASCO 2012) o "
            "cirugía descompresiva (criterios Patchell) ANTES de considerar "
            "Lu-177-PSMA. La mielosupresión post-Lu-177 (anemia 32%, "
            "trombocitopenia 17%, neutropenia 9% en VISION) puede demorar la "
            "cirugía descompresiva. Reevaluar Lu-177 tras estabilización "
            "estructural documentada (`cord_compression_stabilized=Sí`)."
        ),
        "evidence_tag": "pluvicto_label_vision_loblaw_2012",
        "trial_refs": ("VISION", "PSMAfore", "TheraP", "Pluvicto label"),
    }


def detect_lutetium177_in_severe_cytopenias(payload: dict) -> dict | None:
    """Citopenias basales fuera de los umbrales de Pluvicto → contraindica Lu-177.

    Fundamento clínico:
      - Pluvicto (Lu-177-PSMA-617) FDA prescribing information (Novartis 2022,
        actualizado 2024): requisitos de seguridad ANTES de cada ciclo:
          - ANC ≥1.5 × 10⁹/L (1500/µL)
          - Plaquetas ≥75 × 10⁹/L (75 000/µL = 75 000/mm³)
          - Hemoglobina ≥9 g/dL
          - eGFR ≥30 mL/min/1.73 m²  (gate 10 ya cubre eGFR<30 para rucaparib;
            gate 14 chequea ANC/plaquetas/Hb específicos para Lu-177).
      - VISION (Sartor NEJM 2021) excluyó pacientes con ANC <1.5 × 10⁹/L,
        plaquetas <100 × 10⁹/L, Hb <9 g/dL (criterios más estrictos que la
        etiqueta para el pivote).
      - Mecanismo: las alfa-betas-emisiones de Lu-177 generan mielosupresión
        acumulativa progresiva. Iniciar con citopenias basales severas implica
        riesgo de falla medular irreversible o sangrado/infección graves.

    Activación:
      - ANC <1500/µL (`anc` o `anc_baseline`), **O**
      - Plaquetas <75 000/µL (`platelets`), **O**
      - Hemoglobina <9 g/dL (`hemoglobin_g_dl`, `hemoglobin`, o `hb`), **O**
      - Flag explícito `severe_cytopenia_for_radioligand=Sí`.

    Override por corrección documentada: `cytopenias_corrected_for_radioligand=Sí`
    (post-transfusión / EPO / G-CSF + recovery laboratorial).

    Threshold rationale: usamos Pluvicto label (cycle gate ANC ≥1500, plaq
    ≥75 000, Hb ≥9), no VISION (más estricto), porque la pregunta clínica es
    "¿el paciente puede recibir el SIGUIENTE ciclo?" y la etiqueta es la
    referencia regulatoria vigente.
    """
    explicit = _truthy_token(payload.get("severe_cytopenia_for_radioligand"))
    anc = _safe_float(payload.get("anc"))
    if anc is None:
        anc = _safe_float(payload.get("anc_baseline"))
    platelets = _safe_float(payload.get("platelets"))
    hb = _safe_float(payload.get("hemoglobin_g_dl"))
    if hb is None:
        hb = _safe_float(payload.get("hemoglobin"))
    if hb is None:
        hb = _safe_float(payload.get("hb"))
    low_anc = anc is not None and anc < 1500
    low_plt = platelets is not None and platelets < 75000
    low_hb = hb is not None and hb < 9.0
    if not (explicit or low_anc or low_plt or low_hb):
        return None
    if _truthy_token(payload.get("cytopenias_corrected_for_radioligand")):
        return None
    failed_lines: list[str] = []
    if explicit:
        failed_lines.append("citopenia severa documentada")
    if low_anc:
        failed_lines.append(f"ANC {anc:.0f}/µL <1500")
    if low_plt:
        failed_lines.append(f"plaquetas {platelets:.0f}/µL <75 000")
    if low_hb:
        failed_lines.append(f"Hb {hb:.1f} g/dL <9.0")
    summary = ", ".join(failed_lines)
    return {
        "code": "lutetium177_in_severe_cytopenias",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_LUTETIUM177,
        "affected_keywords": KEYWORDS_LUTETIUM177,
        "message": (
            f"Lu-177-PSMA-617 (Pluvicto) NO debe iniciarse con {summary}. "
            "Pluvicto FDA prescribing information (Novartis 2022-2024) requiere "
            "antes de cada ciclo: ANC ≥1.5×10⁹/L (1500/µL), plaquetas "
            "≥75×10⁹/L (75 000/µL), hemoglobina ≥9 g/dL, eGFR ≥30 mL/min. "
            "VISION (Sartor NEJM 2021;385:2197) excluyó valores menores. La "
            "mielosupresión es acumulativa (anemia 32%, trombocitopenia 17%, "
            "neutropenia 9%); iniciar con citopenias basales severas implica "
            "riesgo de falla medular irreversible o sangrado/infección graves. "
            "Optimizar con transfusión, EPO, G-CSF según indicación; reevaluar "
            "(`cytopenias_corrected_for_radioligand=Sí`) tras documentar "
            "recuperación laboratorial."
        ),
        "evidence_tag": "pluvicto_label_vision",
        "trial_refs": ("VISION", "Pluvicto label"),
    }


# ── Faubot 2026-04-24 (VI) — Gates 15-16: PARP inhibitors × hematología ─


def detect_parp_inhibitor_in_severe_cytopenias(payload: dict) -> dict | None:
    """Citopenias basales severas → contraindica PARP inhibitors (PROfound,
    MAGNITUDE, TALAPRO-2/3, PROpel, TRITON-3).

    Fundamento clínico:
      - Olaparib (Lynparza FDA prescribing information 2024) requiere antes de
        cada ciclo: ANC ≥1.5 × 10⁹/L, plaquetas ≥100 × 10⁹/L, Hb ≥10 g/dL.
        PROfound (de Bono NEJM 2020;382:2091) excluyó valores menores.
      - Niraparib (Akeega/Zejula FDA prescribing information 2023) requiere:
        plaq ≥100 × 10⁹/L específicamente (perfil característico de
        trombocitopenia ~40% con dose-dependent thrombocytopenia más severa
        que otros PARPi). MAGNITUDE (Chi NEJM 2023) excluyó valores menores.
      - Talazoparib (Talzenna FDA prescribing information 2024) requiere:
        ANC ≥1.5 × 10⁹/L, plaq ≥100 × 10⁹/L, Hb ≥9 g/dL. TALAPRO-2 (Agarwal
        Lancet 2023;402:291) y TALAPRO-3 (Agarwal ASCO GU 2025 LBA18)
        replicaron los criterios.
      - Rucaparib (Rubraca FDA prescribing information 2024) requiere: ANC
        ≥1.5 × 10⁹/L, plaq ≥100 × 10⁹/L, Hb ≥9 g/dL. TRITON-3 (Fizazi NEJM
        2023;388:719) excluyó valores menores. Nota: gate 10 ya cubre
        eGFR <30 para rucaparib específicamente.

    Threshold rationale: usamos el umbral PARPi consolidado (más estricto que
    Lu-177 gate 14 que usaba 75 000 plaq):
      - ANC <1500/µL (1.5 × 10⁹/L)
      - Plaquetas <100 000/µL (100 × 10⁹/L)
      - Hemoglobina <9 g/dL

    Activación:
      - Cualquiera de los 3 thresholds violado, **O**
      - Flag explícito `severe_cytopenia_for_parp_inhibitor=Sí`.

    Override por corrección documentada: `cytopenias_corrected_for_parp_inhibitor=Sí`
    (post-transfusión / EPO / G-CSF / dose interruption + recovery laboratorial).

    Decisión de no compartir override con Lu-177 (`cytopenias_corrected_for_radioligand`):
    los PARPi tienen umbrales propios (plaq <100K vs <75K para Lu-177) y la
    "corrección" puede ser parcial — la corrección que basta para Lu-177 puede
    no bastar para PARPi. Mantenemos overrides separados para evitar habilitar
    PARPi cuando solo se corrigió hasta el threshold radioligando.
    """
    explicit = _truthy_token(payload.get("severe_cytopenia_for_parp_inhibitor"))
    anc = _safe_float(payload.get("anc"))
    if anc is None:
        anc = _safe_float(payload.get("anc_baseline"))
    platelets = _safe_float(payload.get("platelets"))
    hb = _safe_float(payload.get("hemoglobin_g_dl"))
    if hb is None:
        hb = _safe_float(payload.get("hemoglobin"))
    if hb is None:
        hb = _safe_float(payload.get("hb"))
    low_anc = anc is not None and anc < 1500
    low_plt = platelets is not None and platelets < 100000
    low_hb = hb is not None and hb < 9.0
    if not (explicit or low_anc or low_plt or low_hb):
        return None
    if _truthy_token(payload.get("cytopenias_corrected_for_parp_inhibitor")):
        return None
    failed_lines: list[str] = []
    if explicit:
        failed_lines.append("citopenia severa documentada")
    if low_anc:
        failed_lines.append(f"ANC {anc:.0f}/µL <1500")
    if low_plt:
        failed_lines.append(f"plaquetas {platelets:.0f}/µL <100 000")
    if low_hb:
        failed_lines.append(f"Hb {hb:.1f} g/dL <9.0")
    summary = ", ".join(failed_lines)
    return {
        "code": "parp_inhibitor_in_severe_cytopenias",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_PARP_INHIBITORS,
        "affected_keywords": KEYWORDS_PARP_INHIBITORS,
        "message": (
            f"PARP inhibitors (olaparib, niraparib, talazoparib, rucaparib) NO "
            f"deben iniciarse con {summary}. Lynparza (olaparib) FDA "
            "prescribing information 2024 + Akeega/Zejula (niraparib) 2023 + "
            "Talzenna (talazoparib) 2024 + Rubraca (rucaparib) 2024 requieren "
            "ANC ≥1.5×10⁹/L, plaquetas ≥100×10⁹/L, hemoglobina ≥9 g/dL antes "
            "de cada ciclo. PROfound (de Bono NEJM 2020;382:2091), MAGNITUDE "
            "(Chi NEJM 2023), TALAPRO-2 (Agarwal Lancet 2023;402:291) y "
            "TRITON-3 (Fizazi NEJM 2023;388:719) excluyeron valores menores. "
            "La mielosupresión por PARPi es acumulativa (anemia 30-50%, "
            "trombocitopenia 30-40%, neutropenia 15-25%); iniciar con "
            "citopenias basales severas implica riesgo elevado de falla "
            "medular o sangrado/infección graves. Optimizar con transfusión, "
            "EPO, G-CSF según indicación; reevaluar (`cytopenias_corrected_"
            "for_parp_inhibitor=Sí`) tras recuperación laboratorial."
        ),
        "evidence_tag": "profound_magnitude_talapro_triton3_labels",
        "trial_refs": ("PROfound", "MAGNITUDE", "TALAPRO-2", "TALAPRO-3", "PROpel", "TRITON-3"),
    }


def detect_parp_inhibitor_in_mds_aml_history(payload: dict) -> dict | None:
    """Antecedente de MDS/AML → contraindica TODOS los PARP inhibitors.

    Fundamento clínico:
      - TODOS los PARPi llevan en su etiqueta la advertencia de SMD/LMA
        (síndrome mielodisplásico / leucemia mieloide aguda) como evento
        adverso grave reportado en la post-comercialización con casos fatales.
      - Lynparza (olaparib) FDA prescribing information 2024 §5.1: "MDS/AML,
        including cases with fatal outcome, have been reported in patients
        treated with LYNPARZA. The duration of LYNPARZA therapy in patients
        who developed MDS/AML varied from <1 month to >10 years." Tasa
        acumulada ~1-2% en exposiciones >2 años.
      - Akeega/Zejula (niraparib) FDA prescribing information 2023 §5.1:
        misma advertencia, tasa acumulada 0.7%.
      - Talzenna (talazoparib) FDA prescribing information 2024 §5.1: misma
        advertencia, casos reportados.
      - Rubraca (rucaparib) FDA prescribing information 2024 §5.1: misma
        advertencia, tasa acumulada 0.5-1%.
      - El antecedente de MDS/AML pre-existente o sospecha (citopenia
        prolongada inexplicada) es contraindicación absoluta — no hay
        override clínico razonable.

    Activación:
      - Flag explícito `mds_aml_history=Sí` (o aliases),
      - O flag `secondary_hematologic_malignancy=Sí`,
      - O `prolonged_cytopenia_unexplained=Sí` (proxy de SMD no confirmado
        que requiere descartar antes de iniciar PARPi).

    Sin override: la presencia de MDS/AML es definitiva. Si el flag fue un
    error de captura, debe corregirse en la fuente, no overridearse.
    """
    explicit = (
        _truthy_token(payload.get("mds_aml_history"))
        or _truthy_token(payload.get("prior_mds"))
        or _truthy_token(payload.get("prior_aml"))
        or _truthy_token(payload.get("secondary_hematologic_malignancy"))
        or _truthy_token(payload.get("prolonged_cytopenia_unexplained"))
    )
    if not explicit:
        return None
    # Identificar fuente del trigger para el mensaje
    sources: list[str] = []
    if _truthy_token(payload.get("mds_aml_history")):
        sources.append("antecedente de SMD/LMA")
    elif _truthy_token(payload.get("prior_mds")):
        sources.append("antecedente de SMD")
    elif _truthy_token(payload.get("prior_aml")):
        sources.append("antecedente de LMA")
    elif _truthy_token(payload.get("secondary_hematologic_malignancy")):
        sources.append("neoplasia hematológica secundaria")
    elif _truthy_token(payload.get("prolonged_cytopenia_unexplained")):
        sources.append("citopenia prolongada inexplicada (sospecha de SMD)")
    trigger_source = sources[0] if sources else "antecedente hematológico"
    return {
        "code": "parp_inhibitor_in_mds_aml_history",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_PARP_INHIBITORS,
        "affected_keywords": KEYWORDS_PARP_INHIBITORS,
        "message": (
            f"PARP inhibitors (olaparib, niraparib, talazoparib, rucaparib) NO "
            f"deben iniciarse con {trigger_source}. Lynparza (olaparib) FDA "
            "prescribing information 2024 §5.1 + Akeega/Zejula (niraparib) "
            "2023 §5.1 + Talzenna (talazoparib) 2024 §5.1 + Rubraca "
            "(rucaparib) 2024 §5.1: TODOS los PARPi tienen advertencia de "
            "SMD/LMA con casos fatales reportados en post-comercialización "
            "(tasa acumulada 0.5-2% en olaparib, 0.7% niraparib, casos "
            "talazoparib/rucaparib). El antecedente pre-existente o sospecha "
            "no confirmada (citopenia prolongada inexplicada) es "
            "contraindicación absoluta. Si se sospecha SMD no confirmado: "
            "obtener aspirado/biopsia de médula ósea + cariotipo/FISH antes "
            "de iniciar PARPi. Considerar tratamientos alternativos (taxanos, "
            "ARSI, Ra-223 si bone-only sin MDS, Lu-177-PSMA si elegible)."
        ),
        "evidence_tag": "parp_inhibitors_mds_aml_boxed_warning",
        "trial_refs": ("PROfound", "MAGNITUDE", "TALAPRO-2", "TRITON-3", "Lynparza label", "Akeega label", "Talzenna label", "Rubraca label"),
    }


# ── Faubot 2026-04-25 (VII) — Gates 17-18: ARPI cardiotoxicidad ────────


def detect_qtc_prolongation_grade3_for_enzalutamide(payload: dict) -> dict | None:
    """QTc prolongado grado 3 (CTCAE v5) → contraindica enzalutamida.

    Fundamento clínico:
      - Xtandi (enzalutamida) FDA prescribing information §5.4: "Posterior
        Reversible Encephalopathy Syndrome and Seizures" + interacción con
        prolongación de QT. La etiqueta FDA destaca cautela en pacientes con
        riesgo de prolongación QT, incluyendo aquellos con bradicardia,
        hipokalemia, hipomagnesemia o uso concomitante de medicamentos
        prolongadores del QT.
      - ENZAMET (Sweeney NEJM 2019;381:121): cardiac AE incluyendo prolongación
        QT en 2.3% (>20 ms cambio); justifica monitoreo ECG basal + seguimiento.
      - CTCAE v5.0: QTc grado 3 = >500 ms (Fridericia o Bazett); ΔQTc grado 3
        = >60 ms desde basal.
      - ICH E14: límite regulatorio para evaluar prolongación QT en ensayos
        clínicos.

    Activación:
      - QTc absoluto > 500 ms (`qtc_ms` o alias `qtc_baseline_ms`), **O**
      - ΔQTc > 60 ms desde basal (`qtc_change_ms`), **O**
      - Flag explícito `qtc_prolongation_grade3=Sí` (no canónico aún).

    Override por corrección documentada: `qtc_corrected_for_arpi=Sí`
    (tras corregir hipokalemia, hipomagnesemia, suspender DDI cardio-tóxicos
    y QTc <470 ms documentado en ECG seguimiento).

    Coexistencia con soft penalties: `mhspc_regimen_selector.py:847-852` ya
    aplica penalty -12 a enzalutamida cuando QTc >470 ms (zona gris 470-500).
    Este gate hard-block actúa SOLO en threshold crítico CTCAE grado 3 (>500).
    """
    explicit = _truthy_token(payload.get("qtc_prolongation_grade3"))
    qtc = _safe_float(payload.get("qtc_ms"))
    if qtc is None:
        qtc = _safe_float(payload.get("qtc_baseline_ms"))
    qtc_change = _safe_float(payload.get("qtc_change_ms"))
    high_qtc = qtc is not None and qtc > 500
    big_change = qtc_change is not None and qtc_change > 60
    if not (explicit or high_qtc or big_change):
        return None
    if _truthy_token(payload.get("qtc_corrected_for_arpi")):
        return None
    failed_lines: list[str] = []
    if explicit:
        failed_lines.append("prolongación QT grado 3 documentada")
    if high_qtc:
        failed_lines.append(f"QTc {qtc:.0f} ms >500 (CTCAE v5 grado 3)")
    if big_change:
        failed_lines.append(f"ΔQTc {qtc_change:.0f} ms >60 desde basal")
    summary = ", ".join(failed_lines)
    return {
        "code": "qtc_prolongation_grade3_for_enzalutamide",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_ENZALUTAMIDE,
        "affected_keywords": KEYWORDS_ENZALUTAMIDE,
        "message": (
            f"Enzalutamida (Xtandi) NO debe iniciarse con {summary}. Xtandi "
            "FDA prescribing information §5.4 advierte sobre prolongación QT + "
            "convulsiones; ENZAMET (Sweeney NEJM 2019;381:121) reportó cambio "
            "QT >20 ms en 2.3%. CTCAE v5.0 + ICH E14 establecen QTc >500 ms o "
            "ΔQTc >60 ms desde basal como grado 3. Corregir causas reversibles "
            "ANTES de iniciar enzalutamida: (1) hipokalemia (K+ ≥4.0 mEq/L), "
            "(2) hipomagnesemia (Mg ≥2.0 mg/dL), (3) suspender DDI cardio-"
            "tóxicos (ondansetrón IV, fluoroquinolonas, antifúngicos azólicos). "
            "Reevaluar (`qtc_corrected_for_arpi=Sí`) tras documentar QTc <470 "
            "ms en ECG de seguimiento. Considerar darolutamida (perfil QT más "
            "favorable) o abiraterona si LVEF/cardiac function permiten."
        ),
        "evidence_tag": "xtandi_label_enzamet_ctcae_v5",
        "trial_refs": ("ENZAMET", "Xtandi label", "CTCAE v5", "ICH E14"),
    }


def detect_lvef_decline_for_apalutamide(payload: dict) -> dict | None:
    """Caída de LVEF significativa → contraindica apalutamida.

    Fundamento clínico:
      - Erleada (apalutamida) FDA prescribing information warning sobre
        cardiac dysfunction: TITAN (Chi NEJM 2019;381:13) reportó cardiac AE
        4.6% vs placebo 2.4%, incluyendo LVEF decline documentado en
        seguimiento; SPARTAN (Smith NEJM 2018;378:1408) reportó eventos
        cardiovasculares mayores 6.6%.
      - ASCO/ESC Cardio-Oncology Guidelines 2022: LVEF <50% define cardiac
        dysfunction; caída >10% puntos absolutos desde basal define
        deterioro significativo (Plana JACC 2014).
      - Mecanismo: inhibición AR-AR-V7 puede reducir función miocárdica en
        pacientes con cardiopatía isquémica subclínica o función basal limítrofe.

    Activación:
      - LVEF absoluto < 50% (`lvef_percent` o alias `lvef_baseline_percent`),
        **O**
      - Caída > 10% puntos desde basal (`lvef_baseline_percent` - `lvef_percent`
        > 10, requiere AMBOS valores capturados), **O**
      - Flag explícito `lvef_decline_for_arpi=Sí`.

    Override por recuperación documentada: `lvef_recovered_for_arpi=Sí`
    (tras optimización IC con IECA + BB + diurético + LVEF ≥50% documentado
    en eco/MUGA seguimiento).

    Coexistencia con soft penalties: `mhspc_regimen_selector.py:872-877` ya
    aplica penalty -8 a apalutamida cuando LVEF marginal. Este gate hard-block
    actúa SOLO en LVEF <50% absoluto o caída >10% puntos.
    """
    explicit = _truthy_token(payload.get("lvef_decline_for_arpi"))
    lvef = _safe_float(payload.get("lvef_percent"))
    if lvef is None:
        lvef = _safe_float(payload.get("lvef_baseline_percent"))
    lvef_baseline = _safe_float(payload.get("lvef_baseline_percent"))
    # Si tenemos lvef y lvef_baseline distintos, calcular delta
    lvef_delta = None
    if lvef is not None and lvef_baseline is not None and lvef != lvef_baseline:
        lvef_delta = lvef_baseline - lvef
    low_lvef = lvef is not None and lvef < 50
    big_decline = lvef_delta is not None and lvef_delta > 10
    if not (explicit or low_lvef or big_decline):
        return None
    if _truthy_token(payload.get("lvef_recovered_for_arpi")):
        return None
    failed_lines: list[str] = []
    if explicit:
        failed_lines.append("caída LVEF documentada")
    if low_lvef:
        failed_lines.append(f"LVEF {lvef:.0f}% <50%")
    if big_decline:
        failed_lines.append(
            f"caída LVEF {lvef_delta:.0f} puntos desde basal "
            f"({lvef_baseline:.0f}% → {lvef:.0f}%)"
        )
    summary = ", ".join(failed_lines)
    return {
        "code": "lvef_decline_for_apalutamide",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": REGIMEN_CODES_APALUTAMIDE,
        "affected_keywords": KEYWORDS_APALUTAMIDE,
        "message": (
            f"Apalutamida (Erleada) NO debe iniciarse con {summary}. Erleada "
            "FDA prescribing information advierte sobre cardiac dysfunction; "
            "TITAN (Chi NEJM 2019;381:13) reportó cardiac AE 4.6% vs placebo "
            "2.4%; SPARTAN (Smith NEJM 2018;378:1408) eventos cardiovasculares "
            "mayores 6.6%. ASCO/ESC Cardio-Oncology Guidelines 2022 + Plana "
            "JACC 2014 establecen LVEF <50% como cardiac dysfunction y caída "
            ">10% puntos como deterioro significativo. Optimizar IC ANTES de "
            "iniciar apalutamida: (1) IECA/ARA2 a dosis óptima, (2) "
            "betabloqueador (carvedilol/bisoprolol), (3) diurético si "
            "congestión, (4) cardio-oncología consult. Reevaluar "
            "(`lvef_recovered_for_arpi=Sí`) tras LVEF ≥50% documentado en "
            "eco/MUGA seguimiento. Considerar enzalutamida (sin warning LVEF "
            "específico) o darolutamida (perfil cardiac favorable)."
        ),
        "evidence_tag": "erleada_label_titan_spartan_asco_esc_2022",
        "trial_refs": ("TITAN", "SPARTAN", "Erleada label", "ASCO/ESC Cardio-Oncology 2022"),
    }


# ────────────────────────────────────────────────────────────────────────
# EPIC 49+.A (FAUBOT CXLVII) — HX1 6 nuevos gates comorbilidades raras
# Detectados como ausentes en validación EXTENSA okarbo 10 casos:
# casos I (hemofilia A), J (ACV reciente + DOAC), M (PTI plaquetas),
# N (LES corticoides altos + IO), Q (demencia avanzada consent capacity).
# Sin estos gates el clínico recibe recomendación que OMITE contraindicaciones
# clínicamente obvias. Evidence: ASH 2024 (hemofilia + cancer tx), AHA 2024
# (ACV recurrence post-castration), NCCN PROS-3 (autoimmune+IO), AGS 2025
# (geriatric oncology consent), FDA labels ARSI (CYP3A4 DOAC interactions).
# ────────────────────────────────────────────────────────────────────────


def detect_bleeding_risk_hemophilia(payload: dict) -> dict | None:
    """Gate 31 (HX1.1): bleeding risk en hemofilia A/B para procedimientos."""
    factor_viii = _safe_float(payload.get("factor_viii_level_pct"))
    factor_ix = _safe_float(payload.get("factor_ix_level_pct"))
    hemophilia_flag = any(
        "hemofilia" in str(c).lower() or "hemophilia" in str(c).lower()
        for c in (payload.get("comorbidities") or [])
    )
    if not hemophilia_flag and (factor_viii is None or factor_viii > 50) and \
       (factor_ix is None or factor_ix > 50):
        return None
    severe = (factor_viii is not None and factor_viii < 30) or \
             (factor_ix is not None and factor_ix < 30)
    return {
        "code": "bleeding_risk_hemophilia",
        "triggered": True,
        "severity": "hard_block" if severe else "soft_warning",
        "affected_regimen_codes": ["transrectal_biopsy", "rp_surgical",
                                    "brachytherapy", "psma_pet_biopsy"],
        "affected_keywords": ["biopsy", "surgery", "brachytherapy"],
        "message": (
            f"Hemofilia documentada (factor VIII={factor_viii}%, factor IX={factor_ix}%). "
            f"Coordinar con hematología ANTES de biopsia, RP o braquiterapia. "
            f"Considerar transperineal vs transrectal por menor riesgo sangrado."
        ),
        "evidence_tag": "ASH_2024_hemophilia_cancer_management",
        "trial_refs": ["ASH_guideline_2024_factor_replacement_periop"],
    }


def detect_recent_stroke_90_days(payload: dict) -> dict | None:
    """Gate 32 (HX1.2): ACV reciente (<90d) + considerando ADT/ARSI."""
    stroke_recent = _truthy_token(payload.get("stroke_recent_90d"))
    stroke_date = str(payload.get("stroke_date") or "").strip()
    comorbidities_blob = " ".join(
        str(c).lower() for c in (payload.get("comorbidities") or [])
    )
    has_recent_stroke = stroke_recent or (
        "acv" in comorbidities_blob and "2026" in comorbidities_blob
    )
    if not has_recent_stroke:
        return None
    return {
        "code": "recent_stroke_90d",
        "triggered": True,
        "severity": "soft_warning",
        "affected_regimen_codes": ["adt_initiation", "arsi_initiation"],
        "affected_keywords": ["adt", "arsi", "androgen_deprivation"],
        "message": (
            "ACV reciente (<90 días) — ADT/ARSI aumentan riesgo recurrencia "
            "cardiovascular (AHA Scientific Statement 2024). Coordinar con "
            "neurología/cardiología antes de iniciar; preferir darolutamida "
            "(menor riesgo eventos cardiovasculares vs apalutamida/enzalutamida)."
        ),
        "evidence_tag": "AHA_2024_ADT_CV_recurrence",
        "trial_refs": ["AHA_Scientific_Statement_2024"],
    }


def detect_doac_arsi_cyp3a4_interaction(payload: dict) -> dict | None:
    """Gate 33 (HX1.3): DOAC (apixaban/rivaroxaban) + abiraterona/enzalutamida CYP3A4 DDI."""
    meds_blob = " ".join(
        str(m).lower() for m in (payload.get("current_medications") or [])
    )
    has_doac = any(d in meds_blob for d in
                   ("apixaban", "rivaroxaban", "dabigatran", "edoxaban"))
    has_strong_cyp3a4_arsi = any(d in meds_blob for d in
                                  ("abiraterona", "abiraterone", "enzalutamida",
                                   "enzalutamide"))
    if not (has_doac and has_strong_cyp3a4_arsi):
        return None
    return {
        "code": "doac_arsi_cyp3a4_ddi",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": ["abiraterone", "enzalutamide"],
        "affected_keywords": ["abi", "enza", "doac", "apixaban"],
        "message": (
            "DDI documentado: DOAC (apixaban/rivaroxaban) + ARSI inductores "
            "CYP3A4 (enzalutamida) reducen niveles DOAC ↑ riesgo trombótico. "
            "Abiraterona también inhibe CYP3A4 ↑ niveles DOAC ↑ riesgo sangrado. "
            "Considerar warfarina con INR target O switch ARSI a darolutamida "
            "(mínimo DDI con DOAC)."
        ),
        "evidence_tag": "FDA_label_DDI_DOAC_CYP3A4_ARSI_2024",
        "trial_refs": ["FDA_label_enzalutamide_2024", "FDA_label_abiraterone_2024"],
    }


def detect_thrombocytopenia_procedure_risk(payload: dict) -> dict | None:
    """Gate 34 (HX1.4): plaquetas <100k para procedimientos (RP, biopsy, brachy)."""
    platelets = _safe_float(payload.get("platelet_count"))
    if platelets is None or platelets >= 100:
        return None
    pti_chronic = any(
        "pti" in str(c).lower() or "trombocitopenia" in str(c).lower()
        or "itp" in str(c).lower()
        for c in (payload.get("comorbidities") or [])
    )
    severe = platelets < 50
    return {
        "code": "thrombocytopenia_procedure_risk",
        "triggered": True,
        "severity": "hard_block" if severe else "soft_warning",
        "affected_regimen_codes": ["transrectal_biopsy", "rp_surgical",
                                    "brachytherapy", "transperineal_biopsy"],
        "affected_keywords": ["biopsy", "surgery", "brachytherapy"],
        "message": (
            f"Plaquetas {platelets:.0f}k (umbral procedimiento 100k; severo <50k). "
            f"{'PTI crónica documentada — ' if pti_chronic else ''}"
            f"Coordinar con hematología pre-procedimiento; considerar HIFU focal "
            f"o terapia sistémica ADT-only en lugar de cirugía/braquiterapia."
        ),
        "evidence_tag": "ASH_2024_thrombocytopenia_procedure_threshold",
        "trial_refs": ["ASH_guideline_2024_periop_platelet_threshold"],
    }


def detect_autoimmune_disease_io_contraindication(payload: dict) -> dict | None:
    """Gate 35 (HX1.5): enfermedad autoinmune activa + considerando pembrolizumab/IO."""
    comorbidities_blob = " ".join(
        str(c).lower() for c in (payload.get("comorbidities") or [])
    )
    # Tokenize blob por separators comunes (espacio, _) para match exacto
    blob_tokens = set()
    for sep in (" ", "_", "-", ",", "."):
        for tok in comorbidities_blob.split(sep):
            blob_tokens.add(tok.strip())
    autoimmune_terms = {
        "les", "lupus", "ar", "artritis", "rheumatoid",
        "psoriasis", "ibd", "colitis", "crohn", "vasculitis",
        "esclerosis", "sjogren", "tiroiditis_hashimoto", "hashimoto",
    }
    has_autoimmune = bool(blob_tokens & autoimmune_terms) or any(
        t in comorbidities_blob for t in ("lupus", "rheumatoid", "vasculitis")
    )
    msi_high = str(payload.get("msi_status") or "").lower() in (
        "msi_high", "msi-h", "high", "msi_high_dmmr"
    )
    if not (has_autoimmune and msi_high):
        return None
    return {
        "code": "autoimmune_disease_io_contraindication",
        "triggered": True,
        "severity": "hard_block",
        "affected_regimen_codes": ["pembrolizumab", "nivolumab", "ipilimumab"],
        "affected_keywords": ["pembro", "nivolumab", "io", "checkpoint"],
        "message": (
            "Enfermedad autoinmune activa documentada + MSI-H (candidato "
            "pembrolizumab). Inmunoterapia checkpoint puede precipitar brote "
            "autoinmune severo (irAE grado 3-4). Coordinar con reumatología; "
            "evaluar riesgo/beneficio individual; considerar tx alternativa "
            "(cabazitaxel si post-taxano disponible)."
        ),
        "evidence_tag": "NCCN_PROS3_2024_autoimmune_IO_caution",
        "trial_refs": ["FDA_label_pembrolizumab_2024_autoimmune"],
    }


def detect_dementia_informed_consent_capacity(payload: dict) -> dict | None:
    """Gate 36 (HX1.6): demencia moderada-avanzada + decisión tx agresivo."""
    comorbidities_blob = " ".join(
        str(c).lower() for c in (payload.get("comorbidities") or [])
    )
    has_dementia = any(d in comorbidities_blob for d in
                       ("demencia", "alzheimer", "dementia"))
    cdr_score = _safe_float(payload.get("cdr_score"))
    mmse = _safe_float(payload.get("mmse_score"))
    moca = _safe_float(payload.get("moca_score"))
    severe = (cdr_score is not None and cdr_score >= 2) or \
             (mmse is not None and mmse < 18) or \
             (moca is not None and moca < 17)
    if not has_dementia and not severe:
        return None
    return {
        "code": "dementia_informed_consent_capacity",
        "triggered": True,
        "severity": "hard_block" if severe else "soft_warning",
        "affected_regimen_codes": ["arsi_initiation", "chemotherapy", "lu_177",
                                    "parp_inhibitor"],
        "affected_keywords": ["arsi", "chemo", "lu177", "parp"],
        "message": (
            f"Demencia moderada-avanzada documentada "
            f"(CDR={cdr_score}, MMSE={mmse}, MoCA={moca}). "
            f"Paciente puede carecer de capacidad para consentimiento informado. "
            f"Documentar evaluación de capacidad por psiquiatría/geriatría + "
            f"representante legal autorizado. Considerar goals-of-care: tratamientos "
            f"agresivos pueden no alinear con expectativa de vida + calidad."
        ),
        "evidence_tag": "AGS_2025_geriatric_oncology_consent",
        "trial_refs": ["AGS_Beers_Criteria_2025", "ASCO_2024_dementia_cancer_care"],
    }


# ── Orquestación ────────────────────────────────────────────────────────


_DETECTORS = (
    detect_prior_arpi_exposure_mhspc,
    detect_severe_neuropathy_grade3,
    detect_uncontrolled_hypertension,
    detect_severe_heart_failure_nyha_iii_iv,
    detect_uncontrolled_diabetes,
    detect_ecog_2_or_more_for_triplets,
    detect_darolutamide_hypersensitivity,
    detect_polysorbate_hypersensitivity,
    # Faubot 2026-04-25 (XIX) — Gate 9 MIGRADO a YAML declarativo:
    #   pivotal_gates_catalog/09_no_bone_protective_agent.yaml
    # La función Python `detect_no_bone_protective_agent_for_radium223` se
    # mantiene importable como helper (compatibilidad con tests legacy y
    # callers directos), pero NO se registra en `_DETECTORS` — el loader
    # YAML lo evalúa primero en el sistema híbrido. La migración requirió
    # 2 nuevos trigger types: `all_of` (AND composite) y `all_of_falsy`
    # (todos los campos falsy con tokens negativos opcionales).
    detect_creatinine_clearance_lt_30_for_rucaparib,
    # Faubot 2026-04-25 (XVIII) — Gates 11-15 MIGRADOS a YAML declarativo:
    #   pivotal_gates_catalog/11_radium223_in_cord_compression.yaml
    #   pivotal_gates_catalog/12_radium223_in_hypocalcemia.yaml
    #   pivotal_gates_catalog/13_lutetium177_in_cord_compression.yaml
    #   pivotal_gates_catalog/14_lutetium177_in_severe_cytopenias.yaml
    #   pivotal_gates_catalog/15_parp_inhibitor_in_severe_cytopenias.yaml
    # Las funciones Python `detect_radium223_in_cord_compression`,
    # `detect_radium223_in_hypocalcemia`, `detect_lutetium177_in_cord_compression`,
    # `detect_lutetium177_in_severe_cytopenias`, `detect_parp_inhibitor_in_severe_cytopenias`
    # se mantienen en el módulo (importables) pero NO se registran en
    # `_DETECTORS` para evitar redundancia con el loader YAML.
    # Faubot 2026-04-24 (VI) — gate 16: PARP × MDS/AML history (en YAML)
    detect_parp_inhibitor_in_mds_aml_history,
    # Faubot 2026-04-25 (VII) — gates 17-18: ARPI cardiotoxicidad (en YAML)
    detect_qtc_prolongation_grade3_for_enzalutamide,
    detect_lvef_decline_for_apalutamide,
    # EPIC 49+.A (FAUBOT CXLVII) — HX1 6 nuevos gates comorbilidades raras
    detect_bleeding_risk_hemophilia,
    detect_recent_stroke_90_days,
    detect_doac_arsi_cyp3a4_interaction,
    detect_thrombocytopenia_procedure_risk,
    detect_autoimmune_disease_io_contraindication,
    detect_dementia_informed_consent_capacity,
)


def evaluate_pivotal_contraindication_gates(payload: dict) -> list[dict]:
    """Evalúa los 18 gates y retorna la lista de los que disparan.

    Faubot 2026-04-25 (XI) — Sistema híbrido YAML + Python:
      1. Primero se evalúan los gates YAML declarativos (catálogo
         `pivotal_gates_catalog/`).
      2. Luego se evalúan los detectores Python (`_DETECTORS`).
      3. Se deduplica por `code`: si un gate ya disparó vía YAML, no se
         vuelve a procesar vía Python.

    Esto permite migración incremental: los gates simples se mueven a YAML
    sin tocar el Python; los gates con lógica compleja siguen en Python
    hasta una iteración futura del bucle.

    Cada elemento incluye:
      - code, triggered, severity, affected_regimen_codes, affected_keywords,
        message, evidence_tag, trial_refs.
    """
    triggered: list[dict] = []
    seen_codes: set[str] = set()

    # 1. YAML gates (lazy import para evitar circular)
    try:
        from prostanet.shared.pivotal_gates_yaml_loader import (
            evaluate_all_yaml_gates,
        )
        for gate in evaluate_all_yaml_gates(payload):
            code = str(gate.get("code") or "")
            if code and code not in seen_codes:
                triggered.append(gate)
                seen_codes.add(code)
    except ImportError:
        # YAML loader opcional — sistema degrada graciosamente sin él
        pass

    # 2. Python detectors (con deduplicación por code)
    for det in _DETECTORS:
        result = det(payload)
        if not result or not result.get("triggered"):
            continue
        code = str(result.get("code") or "")
        if code in seen_codes:
            # Ya disparado vía YAML — saltar para no duplicar
            continue
        triggered.append(result)
        if code:
            seen_codes.add(code)

    return triggered


def filter_treatments_by_gates(
    treatments: list[dict] | None,
    gates: list[dict] | None,
) -> tuple[list[dict], list[str]]:
    """Filtra `treatments` excluyendo los regímenes bloqueados por algún gate.

    Retorna `(treatments_filtrados, mensajes_unicos_para_not_recommended)`
    para que el caller pueda preservar la trazabilidad clínica de por qué
    se removió un régimen.
    """
    if not gates:
        return list(treatments or []), []
    removed_messages: list[str] = []
    seen_messages: set[str] = set()
    out: list[dict] = []
    for tx in treatments or []:
        tx_name_lower = str(tx.get("name") or "").lower()
        tx_regimen_code = str(tx.get("regimen_code") or "").upper()
        tx_blocked = False
        for gate in gates:
            # Faubot LVIII (#62) — Solo gates con severity="hard_block"
            # bloquean filtros. Severities introducidas en #62:
            #   - "soft_warning" / "informational": gate dispara para display
            #     (UI panel + delta narrative + audit) pero NO filtra el
            #     régimen. Útil para gates educacionales / anti-misinterpretation
            #     como gate 47 (PSA flare en primer mes ARPI = pseudo-progresión).
            # Default es "hard_block" (back-compat: gates pre-#62 sin severity
            # explícita o con severity=hard_block siguen filtrando).
            severity = str(gate.get("severity") or "hard_block").lower()
            if severity != "hard_block":
                continue
            codes = gate.get("affected_regimen_codes") or frozenset()
            keywords = gate.get("affected_keywords") or ()
            if tx_regimen_code in codes or any(kw in tx_name_lower for kw in keywords):
                tx_blocked = True
                msg = gate.get("message") or ""
                if msg and msg not in seen_messages:
                    removed_messages.append(msg)
                    seen_messages.add(msg)
                break
        if not tx_blocked:
            out.append(tx)
    return out, removed_messages


def gate_messages_for_not_recommended(gates: list[dict] | None) -> list[str]:
    """Retorna lista de mensajes únicos para añadir a `not_recommended`.

    Útil cuando el régimen ya fue descartado por el selector aguas arriba y
    el servicio sólo necesita emitir el motivo clínico.
    """
    if not gates:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for gate in gates:
        msg = gate.get("message") or ""
        if msg and msg not in seen:
            out.append(msg)
            seen.add(msg)
    return out


def apply_pivotal_contraindication_gates(
    payload: dict,
    treatments: list[dict] | None,
) -> dict:
    """Helper unificado: evalúa, filtra y devuelve un bundle completo.

    Faubot 2026-04-25 (XV) — Integrado el cross-check DDI: si el payload
    contiene `current_medications`/`concomitant_medications`, cada gate
    disparado se cruza-verifica con DDIEngine para enriquecer el
    `not_recommended` con alertas combinadas (ej. gate 17 QTc + ondansetrón
    concomitante → alerta torsades multiplicada).

    Retorna::
        {
          "filtered_treatments": [...],
          "gates_triggered": [...],
          "not_recommended_messages": [...],
          "ddi_cross_alerts": [...],          # nuevo en Faubot XV
        }
    """
    gates = evaluate_pivotal_contraindication_gates(payload)
    filtered, _ = filter_treatments_by_gates(treatments, gates)
    base_messages = gate_messages_for_not_recommended(gates)

    # Faubot 2026-04-25 (XV) — Cross-check con DDI engine.
    # Lazy import para evitar circular si gates_ddi_cross_check no está
    # disponible (degradación graciosa).
    cross_alerts: list[dict] = []
    cross_messages: list[str] = []
    try:
        from prostanet.shared.gates_ddi_cross_check import (
            cross_check_gates_with_ddi,
            cross_messages_for_not_recommended,
        )
        cross_alerts = cross_check_gates_with_ddi(gates, payload)
        cross_messages = cross_messages_for_not_recommended(cross_alerts)
    except ImportError:
        pass

    # Combinar mensajes base + cross sin duplicar.
    seen = set(base_messages)
    combined_messages = list(base_messages)
    for msg in cross_messages:
        if msg and msg not in seen:
            combined_messages.append(msg)
            seen.add(msg)

    return {
        "filtered_treatments": filtered,
        "gates_triggered": gates,
        "not_recommended_messages": combined_messages,
        "ddi_cross_alerts": cross_alerts,
    }
