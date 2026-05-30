from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from prostanet.domains.patient_tracking.mhspc_frontline_reference import component_metadata


PALLIATIVE_TRACKS = {"concurrent_palliative_care", "hospice_pathway", "supportive_only"}


ADVANCED_STATE_SCOPE = [
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
    "advanced",
]

# EPIC 8 — ámbito de terapias focales (HIFU / crio / TULSA). Son opciones de
# tratamiento local en escenarios seleccionados (intermedio favorable
# unilateral, NCCN PROS-C cat 2B) y por eso se incluyen en el catálogo con
# state_scope acotado para no contaminar flujos sistémicos avanzados.
FOCAL_STATE_SCOPE = [
    "localized_initial",
    "focal_therapy",
]

THERAPY_CLASS_LABELS = {
    "observation": "Observación / sin sistémico",
    "androgen_axis": "Eje androgénico",
    "triplet": "Tripletes / intensificación",
    "taxane": "Taxanos",
    "parp": "PARP / precisión",
    "radioligand": "Radioligandos / radiofármacos",
    "immunotherapy": "Inmunoterapia",
    "focal_ablation": "Terapia focal local",
    "platinum_chemotherapy": "Quimioterapia basada en platino",
    "clinical_trial": "Ensayo clínico",
}

THERAPY_CLASS_ORDER = {
    "observation": 0,
    "androgen_axis": 1,
    "triplet": 2,
    "taxane": 3,
    "parp": 4,
    "radioligand": 5,
    "immunotherapy": 6,
    "focal_ablation": 7,
    "platinum_chemotherapy": 8,
    "clinical_trial": 9,
}

THERAPY_REGIMENS = [
    {
        "regimen_code": "ADT_MONO",
        "label_clinico": "ADT sola",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": [
            "mHSPC_initial",
            "mHSPC_post_docetaxel",
            "m0_CRPC_first_line",
            "mCRPC_first_line",
            "mCRPC_post_ARPI_pre_taxane",
            "mCRPC_post_taxane",
            "later_line",
        ],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT"],
        "evidence_tags": ["backbone", "legacy"],
    },
    {
        "regimen_code": "ADT_ABIRATERONE",
        "label_clinico": "ADT + abiraterona",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Abiraterona"],
        "evidence_tags": ["LATITUDE", "PEACE-1"],
    },
    {
        "regimen_code": "ADT_ENZALUTAMIDE",
        "label_clinico": "ADT + enzalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Enzalutamida"],
        "evidence_tags": ["ARCHES", "ENZAMET"],
    },
    {
        "regimen_code": "ADT_APALUTAMIDE",
        "label_clinico": "ADT + apalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Apalutamida"],
        "evidence_tags": ["TITAN"],
    },
    {
        "regimen_code": "ADT_DAROLUTAMIDE",
        "label_clinico": "ADT + darolutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Darolutamida"],
        "evidence_tags": ["ARANOTE"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL",
        "label_clinico": "ADT + docetaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel"],
        "evidence_tags": ["CHAARTED", "STAMPEDE"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE",
        "label_clinico": "ADT + docetaxel + darolutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel", "Darolutamida"],
        "evidence_tags": ["ARASENS"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL_ABIRATERONE",
        "label_clinico": "ADT + docetaxel + abiraterona",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel", "Abiraterona"],
        "evidence_tags": ["PEACE-1"],
    },
    {
        "regimen_code": "DOCETAXEL",
        "label_clinico": "Docetaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "taxane",
        "contains_adt": False,
        "agents": ["Docetaxel"],
        "evidence_tags": ["TAX327"],
    },
    {
        "regimen_code": "CABAZITAXEL",
        "label_clinico": "Cabazitaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "taxane",
        "contains_adt": False,
        "agents": ["Cabazitaxel"],
        "evidence_tags": ["CARD", "TROPIC"],
    },
    {
        "regimen_code": "OLAPARIB",
        "label_clinico": "Olaparib",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_ARPI_pre_taxane", "mCRPC_post_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Olaparib"],
        "evidence_tags": ["PROfound"],
    },
    {
        "regimen_code": "TALAZOPARIB_ENZALUTAMIDE",
        "label_clinico": "Talazoparib + enzalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Talazoparib", "Enzalutamida"],
        "evidence_tags": ["TALAPRO-2"],
    },
    {
        "regimen_code": "NIRAPARIB_ABIRATERONE",
        "label_clinico": "Niraparib + abiraterona",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Niraparib", "Abiraterona"],
        "evidence_tags": ["MAGNITUDE"],
    },
    # EPIC 9 Group C (GAP-5) — TALAPRO-3 (Agarwal ASCO GU 2025 LBA18):
    # primera combinación PARPi+ARPI+ADT positiva en mHSPC HRR-mutado
    # (HR≈0.67 rPFS). Diferenciada de TALAZOPARIB_ENZALUTAMIDE (mCRPC,
    # TALAPRO-2) por incluir ADT y por aplicar solo a mHSPC HRR+.
    # hrr_required=True y regulatory_pending=True sinalizan al motor que
    # (a) debe bloquearse si HRR no es trazable, (b) la UI debe mostrar
    # badge "pendiente aprobación regulatoria" hasta que FDA/EMA
    # emitan etiqueta formal.
    {
        "regimen_code": "ADT_TALAZO_ENZA_HRR",
        "label_clinico": "ADT + talazoparib + enzalutamida (HRR+)",
        "state_scope": [
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume_sync",
            "mcspc_high_volume_metachronous",
            "mcspc_high_volume",
        ],
        "management_tracks": ["on_parp", "on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial"],
        "therapy_class": "parp",
        "contains_adt": True,
        "agents": ["ADT", "Talazoparib", "Enzalutamida"],
        "evidence_tags": ["TALAPRO-3", "pivotal_abstract"],
        "hrr_required": True,
        "regulatory_pending": True,
        "reference_dosing": {
            "Talazoparib": "0.5 mg oral al día",
            "Enzalutamida": "160 mg oral al día",
        },
    },
    {
        "regimen_code": "RUCAPARIB",
        "label_clinico": "Rucaparib",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_ARPI_pre_taxane", "mCRPC_post_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Rucaparib"],
        "evidence_tags": ["TRITON2", "TRITON-3"],
    },
    {
        "regimen_code": "LU177_PSMA617",
        "label_clinico": "Lutecio-177 PSMA-617",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_lu177", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "mCRPC_post_Lu177", "later_line"],
        "therapy_class": "radioligand",
        "contains_adt": False,
        "agents": ["Lu177-PSMA-617"],
        "evidence_tags": ["VISION", "PSMAfore"],
    },
    {
        "regimen_code": "RADIUM223",
        "label_clinico": "Radio-223",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_lu177", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "radioligand",
        "contains_adt": False,
        "agents": ["Radio-223"],
        "evidence_tags": ["ALSYMPCA"],
    },
    {
        "regimen_code": "PEMBROLIZUMAB",
        "label_clinico": "Pembrolizumab",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "immunotherapy",
        "contains_adt": False,
        "agents": ["Pembrolizumab"],
        "evidence_tags": ["MSI-H", "dMMR", "TMB-high", "KEYNOTE-158", "KEYNOTE-199"],
    },
    {
        # Auditoría Pacientes Insignia 2026-04-21 (§A.4) — IMPACT.
        "regimen_code": "SIPULEUCEL_T",
        "label_clinico": "Sipuleucel-T",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["first_line_mcrpc", "post_arpi_pre_taxane"],
        "therapy_class": "cellular_immunotherapy",
        "contains_adt": False,
        "agents": ["Sipuleucel-T"],
        "evidence_tags": ["IMPACT", "Kantoff-2010"],
    },
    {
        # Auditoría Pacientes Insignia 2026-04-21 (§A.4) — CONTACT-02.
        "regimen_code": "CABOZANTINIB_ATEZOLIZUMAB",
        "label_clinico": "Cabozantinib + Atezolizumab",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["post_arpi_pre_taxane", "mCRPC_post_taxane"],
        "therapy_class": "io_tki_combo",
        "contains_adt": False,
        "agents": ["Cabozantinib", "Atezolizumab"],
        "evidence_tags": ["CONTACT-02", "Agarwal-2024"],
    },
    {
        "regimen_code": "CARBOPLATIN_ETOPOSIDE_NEPC",
        "label_clinico": "Carboplatino + etopósido (NEPC)",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "platinum_chemotherapy",
        "contains_adt": False,
        "agents": ["Carboplatino", "Etopósido"],
        "evidence_tags": ["Aparicio-2013", "Aggarwal-2018", "Beltran-2016", "NCCN-PROS-J"],
    },
    {
        "regimen_code": "CISPLATIN_DOCETAXEL_NEPC",
        "label_clinico": "Cisplatino + docetaxel (NEPC)",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "platinum_chemotherapy",
        "contains_adt": False,
        "agents": ["Cisplatino", "Docetaxel"],
        "evidence_tags": ["Aparicio-2013", "Aggarwal-2018", "NCCN-PROS-J"],
    },
    {
        "regimen_code": "CARBOPLATIN_ETOPOSIDE",
        "label_clinico": "Carboplatino ± etopósido (rechallenge HRR)",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "platinum_chemotherapy",
        "contains_adt": False,
        "agents": ["Carboplatino", "Etopósido"],
        "evidence_tags": ["Schmid-2022", "Mateo-2020"],
    },
    {
        "regimen_code": "CLINICAL_TRIAL_POST_PARP",
        "label_clinico": "Ensayo clínico dirigido post-PARP",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "clinical_trial",
        "contains_adt": False,
        "agents": ["Ensayo"],
        "evidence_tags": ["NCCN-PROS-11"],
    },
    {
        "regimen_code": "FOCAL_HIFU",
        "label_clinico": "HIFU focal (ultrasonido focalizado de alta intensidad)",
        "state_scope": FOCAL_STATE_SCOPE,
        "management_tracks": ["focal_post_procedure"],
        "line_contexts": ["localized_focal"],
        "therapy_class": "focal_ablation",
        "contains_adt": False,
        "agents": ["HIFU"],
        "evidence_tags": ["NCCN-PROS-C-2B", "Stabile-2019", "Guillaumier-2018"],
    },
    {
        "regimen_code": "FOCAL_CRYOABLATION",
        "label_clinico": "Crioablación focal",
        "state_scope": FOCAL_STATE_SCOPE,
        "management_tracks": ["focal_post_procedure"],
        "line_contexts": ["localized_focal"],
        "therapy_class": "focal_ablation",
        "contains_adt": False,
        "agents": ["Crioablación"],
        "evidence_tags": ["NCCN-PROS-C-2B", "Ward-2012"],
    },
    {
        "regimen_code": "FOCAL_TULSA",
        "label_clinico": "TULSA-Pro (ultrasonido transuretral)",
        "state_scope": FOCAL_STATE_SCOPE,
        "management_tracks": ["focal_post_procedure"],
        "line_contexts": ["localized_focal"],
        "therapy_class": "focal_ablation",
        "contains_adt": False,
        "agents": ["TULSA-Pro"],
        "evidence_tags": ["NCCN-PROS-C-2B", "Klotz-2021"],
    },
]

REGIMEN_LOOKUP = {item["regimen_code"]: item for item in THERAPY_REGIMENS}
REGIMEN_LABEL_LOOKUP = {item["regimen_code"]: item["label_clinico"] for item in THERAPY_REGIMENS}

TRIAL_BACKBONE_MAP = {
    "ARASENS": {
        "regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE",
        "note": "Backbone del ensayo ARASENS en mHSPC intensificado.",
    },
    "ARANOTE": {
        "regimen_code": "ADT_DAROLUTAMIDE",
        "note": "Backbone del ensayo ARANOTE en mHSPC sensible a castración.",
    },
    "PEACE-1": {
        "regimen_code": "ADT_DOCETAXEL_ABIRATERONE",
        "note": "Backbone del ensayo PEACE-1 en mHSPC de novo/intensificado.",
    },
    "PSMAFORE": {
        "regimen_code": "LU177_PSMA617",
        "note": "Radioligando evaluado en PSMAfore para mCRPC PSMA+ post-ARPI y pre-taxano.",
    },
    "VISION": {
        "regimen_code": "LU177_PSMA617",
        "note": "Radioligando evaluado en VISION para mCRPC PSMA+ en línea avanzada.",
    },
    "TALAPRO-2": {
        "regimen_code": "TALAZOPARIB_ENZALUTAMIDE",
        "note": "Backbone biomarcado de TALAPRO-2 en mCRPC.",
    },
    "EMBARK": {
        "regimen_code": "ADT_ENZALUTAMIDE",
        "label": "Enzalutamida 160 mg VO diaria +/- leuprolida 22.5 mg cada 12 semanas",
        "dose": "Enzalutamida 160 mg VO diaria +/- leuprolida 22.5 mg IM/SC cada 12 semanas",
        "route": "Oral +/- Intramuscular/Subcutánea",
        "schedule": "Administración continua en ciclos de 12 semanas",
        "duration": "Hasta progresión o pausa protocolizada por respuesta de PSA",
        "note": "Backbone del ensayo EMBARK para recurrencia bioquímica de alto riesgo no metastásica cuando no domina una ruta curativa local inmediata.",
    },
    "RTOG 9601": {
        "label": "RT de salvage + bicalutamida",
        "description": "Radioterapia de salvage del lecho prostático combinada con bicalutamida prolongada.",
        "dose": "RT 64.8 Gy + bicalutamida 150 mg VO diaria",
        "route": "Radioterapia externa + Oral",
        "schedule": "36 fracciones de RT + bicalutamida diaria",
        "duration": "24 meses de bicalutamida",
        "total_dose_gy": "64.8 Gy",
        "fractions": "36 fracciones",
        "note": "Ensayo pivote que respaldó intensificar la RT de salvage con antiandrógeno prolongado en recurrencia bioquímica post-RP seleccionada.",
    },
    "GETUG-AFU 16": {
        "label": "RT de salvage + goserelina",
        "description": "Radioterapia de salvage del lecho prostático con supresión androgénica corta.",
        "dose": "RT 66 Gy + goserelina 10.8 mg SC cada 3 meses",
        "route": "Radioterapia externa + Subcutánea",
        "schedule": "33 fracciones de RT + 2 aplicaciones de goserelina",
        "duration": "6 meses",
        "total_dose_gy": "66 Gy",
        "fractions": "33 fracciones",
        "note": "Ensayo pivote que respalda añadir ADT corta a RT de salvage en BCR post-prostatectomía.",
    },
    "SPPORT": {
        "label": "RT de lecho + ganglios pélvicos + ADT corta",
        "description": "Prostate bed RT con cobertura ganglionar pélvica y supresión androgénica corta.",
        "dose": "Lecho 64.8-70.2 Gy + pelvis 45 Gy + ADT 4-6 meses",
        "route": "Radioterapia externa + Supresión androgénica",
        "schedule": "RT diaria al lecho/ganglios + ADT corta concomitante",
        "duration": "4-6 meses de ADT",
        "total_dose_gy": "64.8-70.2 Gy lecho; 45 Gy pelvis",
        "fractions": "25-39 fracciones según plan",
        "note": "SPPORT/NRG 0534 apoya ampliar volumen ganglionar y añadir ADT corta en salvage seleccionado.",
    },
    "RADICALS-HD": {
        "label": "RT de salvage + ADT prolongada adaptada al riesgo",
        "description": "Comparó distintas duraciones de ADT asociadas a radioterapia postoperatoria.",
        "dose": "RT postoperatoria + ADT 6-24 meses según brazo",
        "route": "Radioterapia externa + Supresión androgénica",
        "schedule": "RT postoperatoria con intensificación hormonal adaptada al riesgo",
        "duration": "6 vs 24 meses",
        "note": "RADICALS-HD informa la discusión moderna de duración hormonal postoperatoria más allá del molde histórico de RTOG 9601.",
    },
    "RADICALS-RT": {
        "label": "Estrategia de salvage temprano vs RT adyuvante",
        "description": "Comparó RT adyuvante inmediata frente a RT de salvage temprana post-RP.",
        "dose": "52.5 Gy/20 fracciones o 66 Gy/33 fracciones",
        "route": "Radioterapia externa",
        "schedule": "RT adyuvante inmediata o salvage temprana según el brazo",
        "note": "Estudio comparativo que respalda reservar RT para rescate temprano cuando sea posible.",
    },
    "RAVES": {
        "label": "Salvage temprano post-RP",
        "description": "Comparó RT adyuvante frente a RT de salvage temprana post-prostatectomía.",
        "dose": "64 Gy",
        "route": "Radioterapia externa",
        "schedule": "32 fracciones de RT",
        "fractions": "32 fracciones",
        "note": "Refuerza la estrategia de rescate temprano en lugar de adyuvancia rutinaria.",
    },
    "ARTISTIC": {
        "label": "Meta-análisis de salvage temprano",
        "description": "Meta-análisis de RADICALS-RT, RAVES y GETUG-17 que favorece rescate temprano sobre adyuvancia rutinaria.",
        "note": "No define un backbone único; contextualiza por qué conviene activar salvage temprano cuando la ventana local sigue abierta.",
    },
    "EMPIRE-1": {
        "label": "Reestadificación dirigida para planear salvage",
        "description": "Estrategia de imagen avanzada para rediseñar la RT de salvage según enfermedad oculta.",
        "route": "Imagen molecular",
        "schedule": "Reestadificación dirigida antes de RT de salvage",
        "note": "EMPIRE-1 modifica la planificación del salvage; no representa un backbone sistémico independiente.",
    },
}

REGIMEN_ALIASES = {
    "adt mono": "ADT_MONO",
    "solo adt": "ADT_MONO",
    "solo terapia de privacion androgenica": "ADT_MONO",
    "solo terapia de privación androgénica": "ADT_MONO",
    "adt + abiraterona": "ADT_ABIRATERONE",
    "abiraterona + adt": "ADT_ABIRATERONE",
    "abiraterone + adt": "ADT_ABIRATERONE",
    "adt + abiraterone": "ADT_ABIRATERONE",
    "adt + enzalutamida": "ADT_ENZALUTAMIDE",
    "enzalutamida + adt": "ADT_ENZALUTAMIDE",
    "adt + enzalutamide": "ADT_ENZALUTAMIDE",
    "enzalutamide + adt": "ADT_ENZALUTAMIDE",
    "adt + apalutamida": "ADT_APALUTAMIDE",
    "apalutamida + adt": "ADT_APALUTAMIDE",
    "adt + apalutamide": "ADT_APALUTAMIDE",
    "apalutamide + adt": "ADT_APALUTAMIDE",
    "adt + darolutamida": "ADT_DAROLUTAMIDE",
    "darolutamida + adt": "ADT_DAROLUTAMIDE",
    "adt + darolutamide": "ADT_DAROLUTAMIDE",
    "darolutamide + adt": "ADT_DAROLUTAMIDE",
    "adt + docetaxel": "ADT_DOCETAXEL",
    "docetaxel + adt": "ADT_DOCETAXEL",
    "adt + docetaxel + darolutamida": "ADT_DOCETAXEL_DAROLUTAMIDE",
    "docetaxel + darolutamida + adt": "ADT_DOCETAXEL_DAROLUTAMIDE",
    "adt + docetaxel + abiraterona": "ADT_DOCETAXEL_ABIRATERONE",
    "docetaxel + abiraterona + adt": "ADT_DOCETAXEL_ABIRATERONE",
    "docetaxel": "DOCETAXEL",
    "cabazitaxel": "CABAZITAXEL",
    "olaparib": "OLAPARIB",
    "talazoparib + enzalutamida": "TALAZOPARIB_ENZALUTAMIDE",
    "talazoparib + enzalutamide": "TALAZOPARIB_ENZALUTAMIDE",
    "niraparib + abiraterona": "NIRAPARIB_ABIRATERONE",
    "niraparib + abiraterone": "NIRAPARIB_ABIRATERONE",
    # EPIC 9 Group C (GAP-5) — TALAPRO-3 aliases
    "adt + talazoparib + enzalutamida": "ADT_TALAZO_ENZA_HRR",
    "adt + talazoparib + enzalutamide": "ADT_TALAZO_ENZA_HRR",
    "talazoparib + enzalutamida + adt": "ADT_TALAZO_ENZA_HRR",
    "talazoparib + enzalutamide + adt": "ADT_TALAZO_ENZA_HRR",
    "talapro-3": "ADT_TALAZO_ENZA_HRR",
    "talapro3": "ADT_TALAZO_ENZA_HRR",
    "rucaparib": "RUCAPARIB",
    "lutecio-177 psma-617": "LU177_PSMA617",
    "lu177 psma617": "LU177_PSMA617",
    "lu177_psma617": "LU177_PSMA617",
    "lu177_psma-617": "LU177_PSMA617",
    "lu177_psma617": "LU177_PSMA617",
    "lu177_psma-617": "LU177_PSMA617",
    "lu-177 psma-617": "LU177_PSMA617",
    "lu 177 psma 617": "LU177_PSMA617",
    "lutecio 177 psma 617": "LU177_PSMA617",
    "lutecio-177 dirigido al antígeno prostático específico de membrana": "LU177_PSMA617",
    "lu177": "LU177_PSMA617",
    "pluvicto": "LU177_PSMA617",
    "radio-223": "RADIUM223",
    "radium-223": "RADIUM223",
    "radium223": "RADIUM223",
    "radio 223": "RADIUM223",
    "pembrolizumab": "PEMBROLIZUMAB",
    # Auditoría Pacientes Insignia 2026-04-21 (§A.4) — IMPACT + CONTACT-02.
    "sipuleucel": "SIPULEUCEL_T",
    "sipuleucel t": "SIPULEUCEL_T",
    "sipuleucel-t": "SIPULEUCEL_T",
    "cabozantinib + atezolizumab": "CABOZANTINIB_ATEZOLIZUMAB",
    "cabozantinib atezolizumab": "CABOZANTINIB_ATEZOLIZUMAB",
    "cabo atezo": "CABOZANTINIB_ATEZOLIZUMAB",
    "acetato de abiraterona": "ADT_ABIRATERONE",
    "carboplatino + etoposido": "CARBOPLATIN_ETOPOSIDE_NEPC",
    "carboplatino + etopósido": "CARBOPLATIN_ETOPOSIDE_NEPC",
    "carboplatin + etoposide": "CARBOPLATIN_ETOPOSIDE_NEPC",
    "carboplatin etoposide nepc": "CARBOPLATIN_ETOPOSIDE_NEPC",
    "carbo etopósido": "CARBOPLATIN_ETOPOSIDE_NEPC",
    "cisplatino + docetaxel": "CISPLATIN_DOCETAXEL_NEPC",
    "cisplatin + docetaxel": "CISPLATIN_DOCETAXEL_NEPC",
    "cisplatino docetaxel nepc": "CISPLATIN_DOCETAXEL_NEPC",
    "carbo rechallenge": "CARBOPLATIN_ETOPOSIDE",
    "carboplatino rechallenge": "CARBOPLATIN_ETOPOSIDE",
    "ensayo post parp": "CLINICAL_TRIAL_POST_PARP",
    "ensayo clínico post parp": "CLINICAL_TRIAL_POST_PARP",
    "hifu": "FOCAL_HIFU",
    "hifu focal": "FOCAL_HIFU",
    "ultrasonido focalizado": "FOCAL_HIFU",
    "ultrasonido focalizado de alta intensidad": "FOCAL_HIFU",
    "high intensity focused ultrasound": "FOCAL_HIFU",
    "crioablacion": "FOCAL_CRYOABLATION",
    "crioablación": "FOCAL_CRYOABLATION",
    "crio": "FOCAL_CRYOABLATION",
    "crio focal": "FOCAL_CRYOABLATION",
    "cryoablation": "FOCAL_CRYOABLATION",
    "tulsa": "FOCAL_TULSA",
    "tulsa pro": "FOCAL_TULSA",
    "tulsa-pro": "FOCAL_TULSA",
    "ultrasonido transuretral": "FOCAL_TULSA",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").replace("-", " ").lower()


def therapy_catalog_entries() -> list[dict[str, Any]]:
    return deepcopy(THERAPY_REGIMENS)


def regimen_label(regimen_code: Any) -> str:
    normalized = normalize_regimen_code(regimen_code)
    if normalized in REGIMEN_LABEL_LOOKUP:
        return REGIMEN_LABEL_LOOKUP[normalized]
    return str(regimen_code or "")


def trial_backbone(trial_name: Any) -> dict[str, Any]:
    normalized_trial = str(trial_name or "").strip().upper()
    config = TRIAL_BACKBONE_MAP.get(normalized_trial)
    if not config:
        return {}
    regimen_code = str(config.get("regimen_code") or "").strip()
    regimen_bundle = regimen_metadata_bundle(regimen_code) if regimen_code else {}
    label = (
        config.get("label")
        or regimen_bundle.get("regimen_label")
        or regimen_label(regimen_code)
        or str(trial_name or normalized_trial)
    )
    return {
        "recommended_trial_backbone": regimen_code or label,
        "recommended_trial_backbone_label": label,
        "recommended_trial_backbone_source": str(trial_name or normalized_trial),
        "recommended_trial_backbone_note": config.get("note", "Corresponde al esquema usado en el estudio pivote comparable; no sustituye la decisión clínica individual."),
        "recommended_trial_backbone_description": config.get("description") or regimen_bundle.get("description", ""),
        "recommended_trial_backbone_dose": config.get("dose") or regimen_bundle.get("dose", ""),
        "recommended_trial_backbone_route": config.get("route") or regimen_bundle.get("route", ""),
        "recommended_trial_backbone_schedule": config.get("schedule") or regimen_bundle.get("schedule", ""),
        "recommended_trial_backbone_duration": config.get("duration", ""),
        "recommended_trial_backbone_total_dose_gy": config.get("total_dose_gy", ""),
        "recommended_trial_backbone_fractions": config.get("fractions", ""),
        "recommended_trial_backbone_component_drugs": list(config.get("component_drugs") or regimen_bundle.get("component_drugs") or []),
    }


def summarize_trial_backbones(trial_names: list[str]) -> dict[str, Any]:
    bundles = [trial_backbone(item) for item in trial_names if trial_backbone(item)]
    if not bundles:
        return {}
    labels: list[str] = []
    regimens: list[str] = []
    sources: list[str] = []
    notes: list[str] = []
    for bundle in bundles:
        label = str(bundle.get("recommended_trial_backbone_label") or "")
        regimen = str(bundle.get("recommended_trial_backbone") or "")
        source = str(bundle.get("recommended_trial_backbone_source") or "")
        note = str(bundle.get("recommended_trial_backbone_note") or "")
        if label and label not in labels:
            labels.append(label)
        if regimen and regimen not in regimens:
            regimens.append(regimen)
        if source and source not in sources:
            sources.append(source)
        if note and note not in notes:
            notes.append(note)
    return {
        "recommended_trial_backbone": regimens,
        "recommended_trial_backbone_label": " · ".join(labels),
        "recommended_trial_backbone_source": ", ".join(sources),
        "recommended_trial_backbone_note": " ".join(notes) or "Corresponde al esquema usado en el estudio pivote comparable; no sustituye la decisión clínica individual.",
    }


def normalize_regimen_code(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("regimen_code", "drug_scheme", "value", "current_treatment", "label_clinico", "label"):
            nested = value.get(key)
            if nested not in (None, "", {}, []):
                return normalize_regimen_code(nested)
        return ""
    text = str(value or "").strip()
    if not text:
        return ""
    if text in {"[object Object]", "[object object]", "object Object", "object object"}:
        return ""
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            return normalize_regimen_code(parsed)
    if text in REGIMEN_LOOKUP:
        return text
    upper_text = text.upper()
    if upper_text in REGIMEN_LOOKUP:
        return upper_text
    if text == upper_text and any(token in text for token in ("_", "-")) and " " not in text:
        return text

    normalized = _normalize_text(text)
    compact = normalized.replace(" ", "")
    if normalized in REGIMEN_ALIASES:
        return REGIMEN_ALIASES[normalized]
    if text in REGIMEN_LABEL_LOOKUP.values():
        for regimen_code, label in REGIMEN_LABEL_LOOKUP.items():
            if label == text:
                return regimen_code

    fuzzy_tokens = {
        "abirater": "ADT_ABIRATERONE",
        "enzalut": "ADT_ENZALUTAMIDE",
        "apalut": "ADT_APALUTAMIDE",
        "darolut": "ADT_DAROLUTAMIDE",
        "cabazit": "CABAZITAXEL",
        "docetax": "DOCETAXEL",
        "olapar": "OLAPARIB",
        "talazopar": "TALAZOPARIB_ENZALUTAMIDE",
        "nirapar": "NIRAPARIB_ABIRATERONE",
        "rucapar": "RUCAPARIB",
        "pembro": "PEMBROLIZUMAB",
        "pluvicto": "LU177_PSMA617",
        "lutec": "LU177_PSMA617",
        "lu177": "LU177_PSMA617",
        "radium": "RADIUM223",
        "radio223": "RADIUM223",
        "carboplatino etopos": "CARBOPLATIN_ETOPOSIDE_NEPC",
        "carboplatin etopos": "CARBOPLATIN_ETOPOSIDE_NEPC",
        "cisplatino docetax": "CISPLATIN_DOCETAXEL_NEPC",
        "cisplatin docetax": "CISPLATIN_DOCETAXEL_NEPC",
        "ensayo post parp": "CLINICAL_TRIAL_POST_PARP",
    }
    for token, regimen_code in fuzzy_tokens.items():
        if token in normalized or token in compact:
            if regimen_code == "DOCETAXEL" and "adt" in normalized:
                return "ADT_DOCETAXEL"
            return regimen_code
    if "adt" in normalized:
        return "ADT_MONO"
    return text


def regimen_components(regimen_code: Any) -> list[dict[str, Any]]:
    normalized = normalize_regimen_code(regimen_code)
    regimen = REGIMEN_LOOKUP.get(normalized)
    if not regimen:
        return []
    return [component_metadata(str(agent)) for agent in list(regimen.get("agents") or [])]


def _join_component_values(components: list[dict[str, Any]], key: str) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for component in components:
        value = str(component.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return " + ".join(values)


def _join_component_keys(components: list[dict[str, Any]]) -> str:
    keys: list[str] = []
    seen: set[str] = set()
    for component in components:
        value = str(component.get("imss_key") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        keys.append(value)
    return " / ".join(keys)


def _format_component_summary(components: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for component in components:
        label = str(component.get("drug_name") or "").strip()
        details = " · ".join(
            value
            for value in [
                str(component.get("dose") or "").strip(),
                str(component.get("route") or "").strip(),
                str(component.get("schedule") or "").strip(),
            ]
            if value
        )
        imss_key = str(component.get("imss_key") or "").strip()
        suffix = f" Clave IMSS: {imss_key}." if imss_key else ""
        if label and details:
            parts.append(f"{label}: {details}.{suffix}".strip())
        elif label:
            parts.append(f"{label}.{suffix}".strip())
    return " ".join(parts)


def regimen_metadata_bundle(regimen_code: Any) -> dict[str, Any]:
    normalized = normalize_regimen_code(regimen_code)
    regimen = REGIMEN_LOOKUP.get(normalized)
    if not regimen:
        return {}
    components = regimen_components(normalized)
    metadata_sources = {
        str(item.get("metadata_source") or "").strip()
        for item in components
        if str(item.get("metadata_source") or "").strip()
    }
    return {
        "regimen_code": normalized,
        "regimen_label": regimen_label(normalized),
        "therapy_class": regimen.get("therapy_class", ""),
        "component_drugs": components,
        "description": _format_component_summary(components) or regimen_label(normalized),
        "dose": _join_component_values(components, "dose"),
        "route": _join_component_values(components, "route"),
        "schedule": _join_component_values(components, "schedule"),
        "imss_key": _join_component_keys(components),
        "clave_imss": _join_component_keys(components),
        "duration": str(regimen.get("duration") or ""),
        "metadata_source": "institutional_ingested_document"
        if "institutional_ingested_document" in metadata_sources
        else ("current_catalog" if metadata_sources else ""),
        "evidence_tags": list(regimen.get("evidence_tags") or []),
        "agents": list(regimen.get("agents") or []),
    }


def build_treatment_option(
    *,
    name: str,
    priority: str,
    notes: str = "",
    regimen_code: Any = None,
    description: str = "",
    dose: str = "",
    route: str = "",
    schedule: str = "",
    component_drugs: list[dict[str, Any]] | None = None,
    imss_key: str = "",
    clave_imss: str = "",
    metadata_source: str = "",
    therapy_class: str = "",
    evidence_tags: list[str] | None = None,
    selection_rationale: list[str] | None = None,
    contraindication_reasons: list[str] | None = None,
    duration: str = "",
    rank: int | None = None,
    eligibility_status: str = "",
    family_code: str = "",
    family_label: str = "",
    molecule_or_backbone: str = "",
    why_this_rank: list[str] | None = None,
    hard_blocks: list[str] | None = None,
    caution_flags: list[str] | None = None,
    ranking_score: float | None = None,
    family_rank: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_regimen_code(regimen_code or name)
    bundle = regimen_metadata_bundle(normalized) if normalized in REGIMEN_LOOKUP else {}
    resolved_regimen_code = bundle.get("regimen_code") or normalized or str(regimen_code or "")
    resolved_component_drugs = list(component_drugs or bundle.get("component_drugs") or [])
    resolved_regimen_label = bundle.get("regimen_label") or name
    option = {
        "name": name or resolved_regimen_label,
        "priority": priority,
        "notes": notes,
        "description": description or bundle.get("description") or notes or name,
        "regimen_code": resolved_regimen_code,
        "regimen_label": resolved_regimen_label,
        "display_label": resolved_regimen_label,
        "component_drugs": resolved_component_drugs,
        "dose": dose or bundle.get("dose", ""),
        "dosis": dose or bundle.get("dose", ""),
        "route": route or bundle.get("route", ""),
        "via": route or bundle.get("route", ""),
        "schedule": schedule or bundle.get("schedule", ""),
        "imss_key": imss_key or bundle.get("imss_key", ""),
        "clave_imss": clave_imss or imss_key or bundle.get("clave_imss", bundle.get("imss_key", "")),
        "duration": duration or bundle.get("duration", ""),
        "selection_rationale": list(selection_rationale or []),
        "contraindication_reasons": list(contraindication_reasons or []),
        "metadata_source": metadata_source or bundle.get("metadata_source", ""),
        "therapy_class": therapy_class or bundle.get("therapy_class", ""),
        "evidence_tags": list(evidence_tags or bundle.get("evidence_tags") or []),
        "rank": rank,
        "eligibility_status": eligibility_status,
        "family_code": family_code,
        "family_label": family_label,
        "molecule_or_backbone": molecule_or_backbone or (bundle.get("regimen_label", "") or name),
        "why_this_rank": list(why_this_rank or []),
        "hard_blocks": list(hard_blocks or []),
        "caution_flags": list(caution_flags or []),
        "ranking_score": ranking_score,
        "family_rank": family_rank,
    }
    if not option["description"]:
        option["description"] = notes or name
    return option


def therapy_select_options(
    *,
    state: str | None = None,
    management_track: str | None = None,
    line_context: str | None = None,
    include_empty: bool = True,
) -> list[dict[str, Any]]:
    state_key = str(state or "").strip()
    track_key = str(management_track or "").strip()
    line_key = str(line_context or "").strip()
    options: list[dict[str, Any]] = []
    if include_empty:
        options.append(
            {
                "value": "",
                "label": "Sin esquema sistémico confirmado",
                "group": THERAPY_CLASS_LABELS["observation"],
                "therapy_class": "observation",
                "state_scope": ADVANCED_STATE_SCOPE,
                "management_tracks": [],
                "line_contexts": [],
                "contains_adt": False,
                "agents": [],
                "evidence_tags": [],
            }
        )

    filtered = []
    for item in THERAPY_REGIMENS:
        state_ok = not state_key or state_key in item["state_scope"] or ("advanced" in item["state_scope"] and state_key in ADVANCED_STATE_SCOPE)
        acceptable_tracks = set(item["management_tracks"] or [])
        if track_key in PALLIATIVE_TRACKS:
            acceptable_tracks.update({"palliative_overlay", "systemic_surveillance"})
        track_ok = not track_key or not acceptable_tracks or track_key in acceptable_tracks
        if not (state_ok and track_ok):
            continue
        filtered.append(item)

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        context_match = 0
        if line_key:
            contexts = item.get("line_contexts") or []
            if line_key in contexts:
                context_match = -1
        return (
            THERAPY_CLASS_ORDER.get(item.get("therapy_class", ""), 99),
            context_match,
            str(item.get("label_clinico") or item.get("regimen_code") or ""),
        )

    for item in sorted(filtered, key=sort_key):
        options.append(
            {
                "value": item["regimen_code"],
                "label": item["label_clinico"],
                "group": THERAPY_CLASS_LABELS.get(item["therapy_class"], item["therapy_class"]),
                "therapy_class": item["therapy_class"],
                "state_scope": deepcopy(item["state_scope"]),
                "management_tracks": deepcopy(item["management_tracks"]),
                "line_contexts": deepcopy(item["line_contexts"]),
                "contains_adt": bool(item["contains_adt"]),
                "agents": deepcopy(item["agents"]),
                "evidence_tags": deepcopy(item["evidence_tags"]),
            }
        )
    return options
