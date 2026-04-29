"""Gestor de listas de medicación concomitante (EPIC 2 FAUBOT).

Unifica la captura heterogénea (string libre, lista de dicts, lista de
``MedicationEntry``) en una representación estructurada y expone un mapa
de metabolismo CYP para que ``ddi_engine`` pueda generar alertas reales
por fármaco + terapia oncológica candidata.

Fuentes del mapeo CYP:
  * PharmGKB (https://www.pharmgkb.org)
  * DrugBank Online 2025
  * Etiquetas FDA (Zytiga §7, Xtandi §7, Nubeqa §7, Erleada §7)
  * Flockhart Table (Indiana University 2024)

El mapa no pretende ser exhaustivo; cubre los CYPs relevantes para el
corredor oncológico de próstata (CYP3A4/5, CYP2D6, CYP2C8, CYP2C9,
CYP2C19) y los fármacos de mayor prevalencia en el paciente con
cáncer de próstata (opioides, anticoagulantes, antihipertensivos,
psicotrópicos, antifúngicos, inmunosupresores).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from prostanet.shared.contracts import MedicationEntry


# ── Mapa CYP (sustrato / inhibidor / inductor) ──────────────────────────────
#
# Cada entrada sigue la forma {cyp: {"substrate": bool, "inhibitor": str|None,
# "inducer": str|None}} donde inhibidor/inductor es "strong", "moderate" o
# "weak".
CYP_METABOLISM_MAP: dict[str, dict[str, Any]] = {
    # ── ARPI / terapias hormonales ─────────────────────────────────────────
    "abiraterona": {
        "CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None},
        "CYP2D6": {"substrate": False, "inhibitor": "strong", "inducer": None},
        "CYP2C8": {"substrate": False, "inhibitor": "strong", "inducer": None},
    },
    "enzalutamida": {
        "CYP3A4": {"substrate": True, "inhibitor": None, "inducer": "strong"},
        "CYP2C9": {"substrate": False, "inhibitor": None, "inducer": "moderate"},
        "CYP2C19": {"substrate": False, "inhibitor": None, "inducer": "moderate"},
        "CYP2B6": {"substrate": False, "inhibitor": None, "inducer": "moderate"},
    },
    "apalutamida": {
        "CYP3A4": {"substrate": True, "inhibitor": None, "inducer": "strong"},
        "CYP2C9": {"substrate": False, "inhibitor": None, "inducer": "moderate"},
        "CYP2C19": {"substrate": False, "inhibitor": None, "inducer": "moderate"},
    },
    "darolutamida": {
        "CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None},
    },

    # ── Quimio / citotóxicos ───────────────────────────────────────────────
    "docetaxel": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},
    "cabazitaxel": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},

    # ── PARPi ──────────────────────────────────────────────────────────────
    "olaparib": {"CYP3A4": {"substrate": True, "inhibitor": "weak", "inducer": None}},
    "rucaparib": {
        "CYP3A4": {"substrate": True, "inhibitor": "moderate", "inducer": None},
        "CYP1A2": {"substrate": False, "inhibitor": "moderate", "inducer": None},
        "CYP2D6": {"substrate": False, "inhibitor": "moderate", "inducer": None},
    },
    "talazoparib": {"CYP3A4": {"substrate": False, "inhibitor": None, "inducer": None}},
    "niraparib": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},

    # ── Anticoagulantes / cardio ───────────────────────────────────────────
    "warfarina": {
        "CYP2C9": {"substrate": True, "inhibitor": None, "inducer": None},
        "CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None},
    },
    "apixaban": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},
    "rivaroxaban": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},
    "metoprolol": {"CYP2D6": {"substrate": True, "inhibitor": None, "inducer": None}},
    "atorvastatina": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},
    "simvastatina": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},
    "rosuvastatina": {"CYP3A4": {"substrate": False, "inhibitor": None, "inducer": None}},
    "pravastatina": {"CYP3A4": {"substrate": False, "inhibitor": None, "inducer": None}},

    # ── Psicotrópicos ──────────────────────────────────────────────────────
    "citalopram": {"CYP2C19": {"substrate": True, "inhibitor": None, "inducer": None}},
    "escitalopram": {"CYP2C19": {"substrate": True, "inhibitor": None, "inducer": None}},
    "sertralina": {"CYP2D6": {"substrate": True, "inhibitor": "weak", "inducer": None}},
    "fluoxetina": {
        "CYP2D6": {"substrate": True, "inhibitor": "strong", "inducer": None},
        "CYP3A4": {"substrate": False, "inhibitor": "weak", "inducer": None},
    },
    "paroxetina": {"CYP2D6": {"substrate": True, "inhibitor": "strong", "inducer": None}},
    "bupropion": {"CYP2D6": {"substrate": True, "inhibitor": "strong", "inducer": None}},

    # ── Opioides ───────────────────────────────────────────────────────────
    "codeina": {"CYP2D6": {"substrate": True, "inhibitor": None, "inducer": None}},
    "tramadol": {"CYP2D6": {"substrate": True, "inhibitor": None, "inducer": None}},
    "oxicodona": {"CYP2D6": {"substrate": True, "inhibitor": None, "inducer": None}},
    "morfina": {"CYP3A4": {"substrate": False, "inhibitor": None, "inducer": None}},
    "fentanilo": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": None}},

    # ── Antifúngicos / antibióticos / antivirales con DDI relevantes ───────
    "ketoconazol": {"CYP3A4": {"substrate": False, "inhibitor": "strong", "inducer": None}},
    "itraconazol": {"CYP3A4": {"substrate": False, "inhibitor": "strong", "inducer": None}},
    "fluconazol": {"CYP3A4": {"substrate": False, "inhibitor": "moderate", "inducer": None}},
    "claritromicina": {"CYP3A4": {"substrate": False, "inhibitor": "strong", "inducer": None}},
    "rifampicina": {"CYP3A4": {"substrate": False, "inhibitor": None, "inducer": "strong"}},

    # ── Hormonales / supportives ───────────────────────────────────────────
    "tamoxifeno": {"CYP2D6": {"substrate": True, "inhibitor": None, "inducer": None}},
    "carbamazepina": {"CYP3A4": {"substrate": True, "inhibitor": None, "inducer": "strong"}},

    # ── Bone-modifying / Ra-223 ────────────────────────────────────────────
    "zoledronato": {},
    "denosumab": {},
    "radium_223": {},
}


# Alias (nombres comerciales / ortografías) → clave canónica.
_MEDICATION_ALIASES = {
    "zytiga": "abiraterona",
    "abiraterone": "abiraterona",
    "xtandi": "enzalutamida",
    "enzalutamide": "enzalutamida",
    "erleada": "apalutamida",
    "apalutamide": "apalutamida",
    "nubeqa": "darolutamida",
    "darolutamide": "darolutamida",
    "lynparza": "olaparib",
    "rubraca": "rucaparib",
    "talzenna": "talazoparib",
    "zejula": "niraparib",
    "taxotere": "docetaxel",
    "jevtana": "cabazitaxel",
    "xofigo": "radium_223",
    "radio_223": "radium_223",
    "xgeva": "denosumab",
    "prolia": "denosumab",
    "zometa": "zoledronato",
    "zoledronic_acid": "zoledronato",
    "warfarin": "warfarina",
    "eliquis": "apixaban",
    "xarelto": "rivaroxaban",
    "lexapro": "escitalopram",
    "celexa": "citalopram",
    "zoloft": "sertralina",
    "prozac": "fluoxetina",
    "paxil": "paroxetina",
    "wellbutrin": "bupropion",
    "tylex": "codeina",
    "codeine": "codeina",
    "morphine": "morfina",
    "fentanyl": "fentanilo",
    "oxycodone": "oxicodona",
    "tamoxifen": "tamoxifeno",
}


def _canonical_name(name: str) -> str:
    token = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _MEDICATION_ALIASES.get(token, token)


def parse_medication_entry(raw: Any) -> MedicationEntry | None:
    """Convierte un string / dict / MedicationEntry en ``MedicationEntry``.

    Acepta:
      * ``"atorvastatina 40 mg"`` (string libre)
      * ``{"name": "warfarin", "dose": "5 mg", "frequency": "QD"}``
      * ``MedicationEntry(...)``
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, MedicationEntry):
        return raw
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("drug") or raw.get("medication") or ""
        if not name:
            return None
        return MedicationEntry(
            name=_canonical_name(name),
            dose=str(raw.get("dose") or ""),
            frequency=str(raw.get("frequency") or raw.get("freq") or ""),
            route=str(raw.get("route") or ""),
            start_date=str(raw.get("start_date") or ""),
            end_date=str(raw.get("end_date") or ""),
            indication=str(raw.get("indication") or ""),
            prescriber=str(raw.get("prescriber") or ""),
            status=str(raw.get("status") or "active"),
            atc_code=str(raw.get("atc_code") or ""),
            source=str(raw.get("source") or "manual"),
        )
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        parts = name.split()
        return MedicationEntry(
            name=_canonical_name(parts[0]),
            dose=" ".join(parts[1:]) if len(parts) > 1 else "",
            source="free_text",
        )
    return None


def normalize_medication_list(raw: Any) -> list[MedicationEntry]:
    """Normaliza entradas heterogéneas en una lista de ``MedicationEntry``."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, MedicationEntry):
        return [raw]
    if isinstance(raw, str):
        parts = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
        out = [parse_medication_entry(part) for part in parts]
        return [m for m in out if m]
    if isinstance(raw, Iterable):
        out = []
        for item in raw:
            entry = parse_medication_entry(item)
            if entry is not None:
                out.append(entry)
        return out
    entry = parse_medication_entry(raw)
    return [entry] if entry else []


def summarize_medication_list(meds: Iterable[MedicationEntry]) -> dict[str, Any]:
    """Produce métricas para el profile (cuenta, catálogo, fármacos
    sin metabolismo mapeado) sin evaluar interacciones."""
    total = 0
    catalogued = 0
    known: list[str] = []
    unknown: list[str] = []
    for med in meds:
        total += 1
        if med.name in CYP_METABOLISM_MAP:
            catalogued += 1
            known.append(med.name)
        else:
            unknown.append(med.name)
    return {
        "total": total,
        "catalogued": catalogued,
        "uncatalogued": total - catalogued,
        "catalogued_names": sorted(set(known)),
        "uncatalogued_names": sorted(set(unknown)),
    }


def lookup_cyp_profile(name: str) -> dict[str, Any]:
    """Devuelve el perfil CYP canónico para un fármaco."""
    key = _canonical_name(name)
    return {"canonical_name": key, "cyp": CYP_METABOLISM_MAP.get(key, {})}


__all__ = [
    "CYP_METABOLISM_MAP",
    "lookup_cyp_profile",
    "normalize_medication_list",
    "parse_medication_entry",
    "summarize_medication_list",
]
