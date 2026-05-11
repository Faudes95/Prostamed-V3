# -*- coding: utf-8 -*-
"""
Mapa canónico de metabolismo CYP para fármacos oncológicos y concomitantes
relevantes en cáncer de próstata (EPIC 4 DDI-G1).

Propósito
---------
Servir como *single source of truth* sobre qué isoenzima CYP procesa cada
fármaco y en qué rol: sustrato, inhibidor o inductor (con fortaleza). El
motor :mod:`prostanet.shared.ddi_engine` consume esta tabla como fallback
estructural cuando una regla en ``_DDI_RULES`` no cubre un par específico,
y permite que futuras expansiones consulten metabolismo sin reimplementar
heurísticas.

Referencias primarias
---------------------
- **FDA Zytiga (abiraterone)** §7.1 — inhibidor CYP2D6 fuerte, CYP2C8 y
  CYP2C19 moderado.
- **FDA Xtandi (enzalutamida)** §7.2 — inductor CYP3A4 fuerte, CYP2C9 y
  CYP2C19 moderado; sustrato CYP2C8/CYP3A4.
- **FDA Erleada (apalutamida)** §7.1-§7.2 — inductor CYP3A4 y CYP2C19
  fuerte; sustrato CYP2C8/CYP3A4.
- **FDA Nubeqa (darolutamida)** §7 — poca interacción; sustrato CYP3A4,
  P-gp, BCRP; inhibidor leve OATP1B1.
- **FDA Lynparza (olaparib)** §7 — sustrato CYP3A4 (principal), P-gp.
- **FDA Talzenna (talazoparib)** §7 — sustrato P-gp, BCRP.
- **FDA Jevtana (cabazitaxel)** §7 — sustrato CYP3A4 (80-90%).
- **FDA Taxotere (docetaxel)** §7 — sustrato CYP3A4 principal.
- **Flockhart Drug Interactions Table (2024)** — psicofármacos,
  antiepilépticos, antiarrítmicos.
- **PharmGKB / DrugBank** — sustratos/inhibidores/inductores cuando FDA
  labels no lo discriminan.

Estructura
----------
``CYP_METABOLISM`` es un dict ``{drug_name: entry}`` con:

.. code-block:: python

    {
      "substrates":  {"CYP3A4": "major"|"minor", ...},
      "inhibitors":  {"CYP2D6": "strong"|"moderate"|"weak", ...},
      "inducers":    {"CYP3A4": "strong"|"moderate"|"weak", ...},
      "transporters": {"P-gp": "substrate"|"inhibitor"|"inducer", ...},
      "notes": "texto libre (opcional)",
    }

Helpers expuestos
-----------------
- :func:`get_cyp_role`: consulta rápida de sustrato/inhibidor/inductor.
- :func:`shares_cyp_path`: devuelve True si dos fármacos convergen sobre
  la misma isoenzima (útil para inferir conflicto pendiente de regla
  explícita).
- :func:`enzyme_impact_for_pair`: clasifica si un fármaco concomitante
  afectará el aclaramiento del oncológico propuesto (útil en
  :mod:`ddi_engine._DDI_RULES` como fallback cuando no hay regla dura).

Nombres normalizados al español/minúscula para coincidir con el resto
del motor DDI (``drug_a``/``drug_b`` en ``_DDI_RULES``).
"""
from __future__ import annotations

from typing import Any

# Severidad/fortaleza (para consistencia con PharmGKB/FDA).
StrengthLiteral = str  # "strong" | "moderate" | "weak" | "major" | "minor"


# ── Base de datos canónica ───────────────────────────────────────────
CYP_METABOLISM: dict[str, dict[str, Any]] = {
    # ── ARPIs (anti-andrógenos de segunda generación) ───────────────
    "abiraterona": {
        "substrates": {"CYP3A4": "major", "SULT2A1": "major"},
        "inhibitors": {
            "CYP2D6": "strong",   # FDA Zytiga §7.1
            "CYP2C8": "moderate",
            "CYP2C19": "moderate",
            "CYP1A2": "weak",
        },
        "inducers": {},
        "transporters": {"OATP1B1": "inhibitor"},
        "notes": "Inhibidor CYP2D6 fuerte; bloquea activación de pro-drogas (codeína, tamoxifeno).",
    },
    "enzalutamida": {
        "substrates": {"CYP2C8": "major", "CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {
            "CYP3A4": "strong",   # FDA Xtandi §7.2
            "CYP2C9": "moderate",
            "CYP2C19": "moderate",
            "UGT1A1": "weak",
        },
        "transporters": {"P-gp": "inducer"},
        "notes": "Inductor CYP3A4 fuerte; reduce eficacia de estatinas, DOACs, opioides CYP3A4.",
    },
    "apalutamida": {
        "substrates": {"CYP2C8": "major", "CYP3A4": "major"},
        "inhibitors": {"CYP2D6": "moderate"},
        "inducers": {
            "CYP3A4": "strong",   # FDA Erleada §7.2
            "CYP2C19": "strong",
            "CYP2C9": "moderate",
            "UGT": "moderate",
        },
        "transporters": {"P-gp": "inducer", "BCRP": "inducer", "OATP1B1": "inducer"},
        "notes": "Inductor simétrico a enzalutamida + inductor CYP2C19 fuerte (clopidogrel, escitalopram, omeprazol).",
    },
    "darolutamida": {
        "substrates": {"CYP3A4": "major", "UGT1A9": "major"},
        "inhibitors": {"BCRP": "weak", "OATP1B1": "weak"},
        "inducers": {},
        "transporters": {"P-gp": "substrate", "BCRP": "substrate"},
        "notes": "Perfil farmacocinético limpio — baja penetración BHE, menos DDI que enza/apalutamida.",
    },

    # ── Taxanos ──────────────────────────────────────────────────────
    "docetaxel": {
        "substrates": {"CYP3A4": "major", "CYP3A5": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Sustrato CYP3A4 dominante — sensible a inhibidores/inductores fuertes.",
    },
    "cabazitaxel": {
        "substrates": {"CYP3A4": "major", "CYP2C8": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Metabolismo CYP3A4 80-90%; mayor hematotoxicidad basal que docetaxel.",
    },

    # ── PARP inhibidores ─────────────────────────────────────────────
    "olaparib": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {"CYP3A4": "weak"},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Inhibidores CYP3A4 fuertes exigen reducir dosis a 200 mg BID (FDA Lynparza §2.4).",
    },
    "rucaparib": {
        "substrates": {"CYP3A4": "major", "CYP2D6": "minor", "CYP1A2": "minor"},
        "inhibitors": {"CYP1A2": "weak", "CYP2C9": "weak", "CYP2C19": "weak", "CYP3A4": "weak"},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Rucaparib inhibe moderadamente varios CYP; evaluar exposición a sustratos de ventana terapéutica estrecha.",
    },
    "niraparib": {
        "substrates": {"CES1": "major", "CES2": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate", "BCRP": "substrate"},
        "notes": "Metabolismo por carboxilesterasas — menos susceptible a inhibidores CYP3A4 pero sensible a inductores.",
    },
    "talazoparib": {
        "substrates": {},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate", "BCRP": "substrate"},
        "notes": "Metabolismo mínimo; depende de P-gp. Inhibidores P-gp (ketoconazol, ritonavir) requieren reducir dosis.",
    },

    # ── Radioligandos / radiofármacos ────────────────────────────────
    "radium_223": {
        "substrates": {},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Excreción intestinal; no metabolismo CYP. Interacciones farmacodinámicas (remodelado óseo con bifosfonatos/denosumab).",
    },
    "lutetium_177": {
        "substrates": {},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Radioligando PSMA; sin metabolismo CYP. Monitorizar función renal y médula ósea.",
    },

    # ── Inhibidores/inductores concomitantes de alto impacto ─────────
    "ketoconazol": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {
            "CYP3A4": "strong",
            "CYP2C9": "moderate",
            "CYP1A2": "weak",
        },
        "inducers": {},
        "transporters": {"P-gp": "inhibitor"},
        "notes": "Prototipo de inhibidor CYP3A4 fuerte; hepatotoxicidad aditiva con abiraterona.",
    },
    "itraconazol": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {"CYP3A4": "strong"},
        "inducers": {},
        "transporters": {"P-gp": "inhibitor"},
        "notes": "Inhibidor CYP3A4 fuerte; obliga a reducir dosis de olaparib, cabazitaxel.",
    },
    "fluconazol": {
        "substrates": {"CYP3A4": "minor"},
        "inhibitors": {"CYP3A4": "moderate", "CYP2C9": "strong", "CYP2C19": "moderate"},
        "inducers": {},
        "transporters": {},
        "notes": "Alternativa frecuente a ketoconazol/itraconazol en pacientes oncológicos (menor inhibición CYP3A4).",
    },
    "claritromicina": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {"CYP3A4": "strong"},
        "inducers": {},
        "transporters": {"P-gp": "inhibitor"},
        "notes": "Inhibidor CYP3A4 fuerte; obliga a reducir olaparib / evitar docetaxel/cabazitaxel.",
    },
    "rifampicina": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {
            "CYP3A4": "strong",
            "CYP2C9": "strong",
            "CYP2C19": "moderate",
            "CYP2B6": "moderate",
        },
        "transporters": {"P-gp": "inducer", "OATP1B1": "inducer"},
        "notes": "Prototipo de inductor CYP3A4 fuerte; contraindica abiraterona por pérdida de exposición >50%.",
    },
    "carbamazepina": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {
            "CYP3A4": "strong",
            "CYP2C9": "strong",
            "CYP2C19": "moderate",
            "UGT": "moderate",
        },
        "transporters": {"P-gp": "inducer"},
        "notes": "Antiepiléptico inductor fuerte; preferir levetiracetam si se requiere manejo neurológico.",
    },
    "fenitoina": {
        "substrates": {"CYP2C9": "major", "CYP2C19": "major"},
        "inhibitors": {},
        "inducers": {"CYP3A4": "strong", "CYP2C9": "strong"},
        "transporters": {"P-gp": "inducer"},
        "notes": "Antiepiléptico inductor fuerte; reduce eficacia de abiraterona, enzalutamida, docetaxel.",
    },
    "st_johns_wort": {
        "substrates": {},
        "inhibitors": {},
        "inducers": {"CYP3A4": "strong", "CYP2C9": "moderate"},
        "transporters": {"P-gp": "inducer"},
        "notes": "Herbolario inductor fuerte; contraindica la mayoría de ARPIs y PARPi.",
    },

    # ── Antidepresivos / SSRI ─────────────────────────────────────────
    "fluoxetina": {
        "substrates": {"CYP2D6": "major", "CYP2C9": "minor"},
        "inhibitors": {"CYP2D6": "strong", "CYP2C19": "moderate"},
        "inducers": {},
        "transporters": {},
        "notes": "Inhibidor CYP2D6 fuerte; bloquea activación de tamoxifeno y codeína.",
    },
    "paroxetina": {
        "substrates": {"CYP2D6": "major"},
        "inhibitors": {"CYP2D6": "strong"},
        "inducers": {},
        "transporters": {},
        "notes": "Inhibidor CYP2D6 fuerte.",
    },
    "sertralina": {
        "substrates": {"CYP2B6": "major", "CYP2C19": "minor", "CYP2D6": "minor"},
        "inhibitors": {"CYP2D6": "weak"},
        "inducers": {},
        "transporters": {},
        "notes": "Perfil DDI limpio; alternativa preferida en pacientes bajo ARPIs/abiraterona.",
    },
    "citalopram": {
        "substrates": {"CYP2C19": "major", "CYP3A4": "minor", "CYP2D6": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Sensible a inductores CYP2C19 (enzalutamida, apalutamida) e inhibidores CYP2C19 (abiraterona).",
    },
    "escitalopram": {
        "substrates": {"CYP2C19": "major", "CYP3A4": "minor", "CYP2D6": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Mismo perfil que citalopram; alternativa sertralina si hay ARPI inductor CYP2C19.",
    },
    "bupropion": {
        "substrates": {"CYP2B6": "major"},
        "inhibitors": {"CYP2D6": "moderate"},
        "inducers": {},
        "transporters": {},
        "notes": "Antidepresivo que baja umbral convulsivo; riesgo aditivo con enzalutamida/apalutamida.",
    },

    # ── Antiplaquetarios / anticoagulantes ───────────────────────────
    "clopidogrel": {
        "substrates": {"CYP2C19": "major", "CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Pro-droga; activación depende de CYP2C19. Inductores (enza/apa) alteran respuesta antiagregante.",
    },
    "warfarina": {
        "substrates": {"CYP2C9": "major", "CYP3A4": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Ventana terapéutica estrecha; INR debe monitorizarse semanalmente al iniciar ARPI/abiraterona.",
    },
    "apixaban": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Sustrato dual CYP3A4/P-gp; inductores fuertes (enza, rifampicina) causan falla anticoagulante.",
    },
    "rivaroxaban": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"P-gp": "substrate"},
        "notes": "Mismo perfil que apixaban.",
    },

    # ── Estatinas ────────────────────────────────────────────────────
    "simvastatina": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"OATP1B1": "substrate"},
        "notes": "Sustrato CYP3A4 sensible; obliga switch a rosuvastatina con ARPI inductor.",
    },
    "atorvastatina": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"OATP1B1": "substrate"},
        "notes": "Sustrato CYP3A4 moderado.",
    },
    "rosuvastatina": {
        "substrates": {"CYP2C9": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"OATP1B1": "substrate", "BCRP": "substrate"},
        "notes": "Independiente de CYP3A4; alternativa segura con enza/apa/abiraterona.",
    },
    "pravastatina": {
        "substrates": {},
        "inhibitors": {},
        "inducers": {},
        "transporters": {"OATP1B1": "substrate"},
        "notes": "No metabolismo CYP; alternativa segura.",
    },

    # ── Antiarrítmicos / QTc ─────────────────────────────────────────
    "amiodarona": {
        "substrates": {"CYP3A4": "major", "CYP2C8": "major"},
        "inhibitors": {"CYP2C9": "moderate", "CYP2D6": "moderate", "CYP3A4": "moderate", "P-gp": "moderate"},
        "inducers": {},
        "transporters": {"P-gp": "inhibitor"},
        "notes": "Prolongador QTc y multi-inhibidor CYP; interacción seria con abiraterona (QTc aditivo).",
    },
    "metadona": {
        "substrates": {"CYP3A4": "major", "CYP2B6": "major", "CYP2D6": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Opioide con prolongación QTc; dual mecanismo de DDI con ARPIs (QTc + CYP3A4 inducción).",
    },
    "moxifloxacino": {
        "substrates": {"CYP3A4": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Fluoroquinolona con potencial QTc máximo entre las fluoroquinolonas.",
    },

    # ── Opioides ─────────────────────────────────────────────────────
    "codeina": {
        "substrates": {"CYP2D6": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Pro-droga; requiere CYP2D6 para conversión a morfina (analgésico activo).",
    },
    "oxicodona": {
        "substrates": {"CYP3A4": "major", "CYP2D6": "moderate"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Componente CYP2D6 activo (oxymorfona); puede atenuarse con abiraterona.",
    },
    "tramadol": {
        "substrates": {"CYP2D6": "major", "CYP3A4": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Pro-droga; riesgo convulsivo añadido — contraindicado con enza/apa + historia convulsiva.",
    },
    "fentanilo": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Sustrato CYP3A4; analgesia impredecible con inductores.",
    },
    "morfina": {
        "substrates": {"UGT2B7": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Glucuronidación hepática; sin dependencia CYP — alternativa segura.",
    },
    "hidromorfona": {
        "substrates": {"UGT2B7": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Misma vía glucurónida que morfina; seguro con ARPIs.",
    },

    # ── Cardiovasculares ─────────────────────────────────────────────
    "metoprolol": {
        "substrates": {"CYP2D6": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Sustrato CYP2D6 dominante; bradicardia si abiraterona concomitante.",
    },
    "bisoprolol": {
        "substrates": {"CYP3A4": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Menor dependencia CYP2D6; alternativa a metoprolol con abiraterona.",
    },
    "carvedilol": {
        "substrates": {"CYP2D6": "major", "CYP2C9": "moderate"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Parcialmente dependiente CYP2D6; monitorizar FC con abiraterona.",
    },

    # ── Otros de interés clínico ─────────────────────────────────────
    "tamoxifeno": {
        "substrates": {"CYP3A4": "major", "CYP2D6": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Pro-droga; activación a endoxifeno requiere CYP2D6. Bloqueado por abiraterona, fluoxetina, paroxetina, bupropion.",
    },
    "ondansetron": {
        "substrates": {"CYP3A4": "major", "CYP1A2": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Antiemético con prolongación QTc; riesgo aditivo con abiraterona/enza.",
    },
    "dexametasona": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {"CYP3A4": "moderate"},
        "transporters": {"P-gp": "inducer"},
        "notes": "Concomitante habitual con abiraterona; inducción moderada — monitorizar exposición ARPI.",
    },
    "espironolactona": {
        "substrates": {"CYP3A4": "major"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Contraindicada con abiraterona — activa parcialmente receptor androgénico.",
    },
    "omeprazol": {
        "substrates": {"CYP2C19": "major", "CYP3A4": "moderate"},
        "inhibitors": {"CYP2C19": "moderate"},
        "inducers": {},
        "transporters": {},
        "notes": "Sustrato CYP2C19; perdido con enza/apa inductor.",
    },
    "pantoprazol": {
        "substrates": {"CYP2C19": "moderate", "CYP3A4": "minor"},
        "inhibitors": {},
        "inducers": {},
        "transporters": {},
        "notes": "Menos dependencia CYP2C19; alternativa a omeprazol con ARPI inductor.",
    },
}


_VALID_ROLES = {"substrates", "inhibitors", "inducers", "transporters"}


def _normalize_name(name: str) -> str:
    key = (name or "").strip().lower()
    # Aliases críticos; el normalizador completo vive en medication_list.
    aliases = {
        "lu177": "lutetium_177",
        "lu-177": "lutetium_177",
        "ra223": "radium_223",
        "ra-223": "radium_223",
        "zytiga": "abiraterona",
        "xtandi": "enzalutamida",
        "erleada": "apalutamida",
        "nubeqa": "darolutamida",
        "lynparza": "olaparib",
        "talzenna": "talazoparib",
        "jevtana": "cabazitaxel",
        "hierba_de_san_juan": "st_johns_wort",
    }
    return aliases.get(key, key)


def get_cyp_role(drug: str, role: str, enzyme: str | None = None) -> Any:
    """Retorna metadata de metabolismo para ``drug`` en ``role``.

    Args:
        drug: nombre del fármaco (se normaliza minúscula + aliases).
        role: "substrates" | "inhibitors" | "inducers" | "transporters".
        enzyme: si se pasa, devuelve la fortaleza específica (o ``None``
            si no aplica). Si se omite, devuelve el dict completo del
            rol.

    Returns:
        ``str`` (fortaleza), ``dict`` completo, o ``None`` si el fármaco
        o el rol no están registrados.
    """
    if role not in _VALID_ROLES:
        raise ValueError(f"role inválido: {role}; usar {sorted(_VALID_ROLES)}")
    entry = CYP_METABOLISM.get(_normalize_name(drug))
    if not entry:
        return None
    role_data = entry.get(role) or {}
    if enzyme is None:
        return dict(role_data)
    return role_data.get(enzyme)


def shares_cyp_path(drug_a: str, drug_b: str) -> set[str]:
    """Retorna el conjunto de isoenzimas/transportadores compartidos
    entre ambos fármacos (independiente del rol).

    Útil para detectar convergencia metabólica que podría no estar
    explicitada en ``_DDI_RULES``.
    """
    entry_a = CYP_METABOLISM.get(_normalize_name(drug_a)) or {}
    entry_b = CYP_METABOLISM.get(_normalize_name(drug_b)) or {}
    enzymes_a: set[str] = set()
    enzymes_b: set[str] = set()
    for role in _VALID_ROLES:
        enzymes_a.update((entry_a.get(role) or {}).keys())
        enzymes_b.update((entry_b.get(role) or {}).keys())
    return enzymes_a & enzymes_b


def enzyme_impact_for_pair(onco_drug: str, concomitant: str) -> dict[str, Any]:
    """Clasifica cómo ``concomitant`` afectará el aclaramiento del
    oncológico ``onco_drug``.

    Devuelve::

        {
          "effect": "induction" | "inhibition" | "none",
          "strength": "strong" | "moderate" | "weak" | "",
          "enzyme": "<enzima impactada>",
          "direction": "reduces_onco_exposure" | "increases_onco_exposure" | "",
          "notes": str,
        }

    Regla:
    - Si el oncológico es SUSTRATO mayor/menor de una enzima E, y el
      concomitante es INHIBIDOR de E → aumenta exposición (toxicidad).
    - Si el concomitante es INDUCTOR de E → reduce exposición (falla
      terapéutica).
    - Se elige la enzima donde el oncológico sea SUSTRATO mayor; si no
      existe, se busca entre los menores.

    Permite que ``ddi_engine`` emita alertas de fallback cuando no hay
    regla explícita — evitando perder pares obvios.
    """
    onco = CYP_METABOLISM.get(_normalize_name(onco_drug)) or {}
    comed = CYP_METABOLISM.get(_normalize_name(concomitant)) or {}

    onco_substrates = onco.get("substrates") or {}
    if not onco_substrates:
        return {"effect": "none", "strength": "", "enzyme": "", "direction": "", "notes": ""}

    # Evaluar enzimas donde onco sea sustrato, empezando por majors.
    sorted_subs = sorted(
        onco_substrates.items(),
        key=lambda kv: 0 if kv[1] == "major" else 1,
    )

    comed_inhibitors = comed.get("inhibitors") or {}
    comed_inducers = comed.get("inducers") or {}

    for enzyme, sub_strength in sorted_subs:
        if enzyme in comed_inducers:
            return {
                "effect": "induction",
                "strength": comed_inducers[enzyme],
                "enzyme": enzyme,
                "direction": "reduces_onco_exposure",
                "notes": (
                    f"{concomitant} induce {enzyme}; {onco_drug} es sustrato "
                    f"{sub_strength} — considerar pérdida de eficacia."
                ),
            }
        if enzyme in comed_inhibitors:
            return {
                "effect": "inhibition",
                "strength": comed_inhibitors[enzyme],
                "enzyme": enzyme,
                "direction": "increases_onco_exposure",
                "notes": (
                    f"{concomitant} inhibe {enzyme}; {onco_drug} es sustrato "
                    f"{sub_strength} — vigilar toxicidad."
                ),
            }
    return {"effect": "none", "strength": "", "enzyme": "", "direction": "", "notes": ""}


# ── EPIC 9 Group E (GAP-10) — auditoría de cobertura CYP2C19 ─────────
#
# Requisito del plan: "auditar cobertura CYP2C19 (91 pairs actuales);
# añadir abiraterone+clopidogrel, documentar escitalopram/citalopram
# (metabolizados CYP2C19) sin inductores activos en catálogo oncológico".
#
# Cierre (2026-04-19):
# - abiraterona+clopidogrel registrado en ``_DDI_RULES`` con severity
#   ``major`` (no ``moderate`` como sugería el plan). Elevamos a major
#   porque la pérdida de activación antiagregante en un paciente con
#   indicación de clopidogrel es un evento clínicamente mayor (riesgo
#   trombótico, no cosmético). Ref: ``ddi_engine.py:515-520`` +
#   FDA Zytiga §7.2 / Plavix label §7.
# - citalopram y escitalopram quedan registrados en ``CYP_METABOLISM``
#   como sustratos mayores CYP2C19 + 2 sustratos menores adicionales
#   (CYP3A4, CYP2D6). Los inductores relevantes del catálogo
#   oncológico son enzalutamida (moderate) y apalutamida (strong);
#   ambos cubiertos en ``_DDI_RULES`` (enza+citalopram line 167,
#   enza+escitalopram line 172, apa+citalopram line 177,
#   apa+escitalopram line 320). Darolutamida NO tiene inducción
#   CYP2C19 documentada (ref: FDA Nubeqa §7) — no requiere regla.
# - Abiraterona es INHIBIDOR CYP2C19 moderado (FDA Zytiga §7.2):
#   aumenta exposición de sustratos → abiraterona+citalopram,
#   +escitalopram, +clopidogrel, +omeprazol cubiertos.
#
# El dict ``CYP2C19_COVERAGE`` materializa la auditoría para uso
# programático (tests, governance) y expone el conteo de reglas
# registradas por eje (inducción + inhibición).
CYP2C19_COVERAGE: dict[str, Any] = {
    "closure_status": "complete",
    "gap_reference": "EPIC 9 Group E — GAP-10",
    "audit_date": "2026-04-19",
    "oncology_perpetrators": {
        "enzalutamida": {"role": "inducer", "strength": "moderate", "label_ref": "FDA Xtandi §7.2"},
        "apalutamida": {"role": "inducer", "strength": "strong", "label_ref": "FDA Erleada §7.2"},
        "abiraterona": {"role": "inhibitor", "strength": "moderate", "label_ref": "FDA Zytiga §7.2"},
        "darolutamida": {"role": "neutral", "strength": None, "label_ref": "FDA Nubeqa §7"},
    },
    "cyp2c19_substrates_catalog": {
        "citalopram": {"dependence": "major", "clinical_risk": "qtc_prolongation"},
        "escitalopram": {"dependence": "major", "clinical_risk": "qtc_prolongation"},
        "clopidogrel": {"dependence": "major_activation", "clinical_risk": "antiplatelet_failure_thrombosis"},
        "omeprazol": {"dependence": "major", "clinical_risk": "pk_minor_clinical"},
    },
    "registered_pairs": [
        # Inductores CYP2C19 (enza/apa) → sustratos pierden eficacia
        {"pair": ("enzalutamida", "citalopram"), "severity": "major", "effect": "loss_of_efficacy"},
        {"pair": ("enzalutamida", "escitalopram"), "severity": "major", "effect": "loss_of_efficacy"},
        {"pair": ("enzalutamida", "clopidogrel"), "severity": "major", "effect": "paradoxical_activation"},
        {"pair": ("apalutamida", "citalopram"), "severity": "major", "effect": "loss_of_efficacy"},
        {"pair": ("apalutamida", "escitalopram"), "severity": "major", "effect": "loss_of_efficacy"},
        {"pair": ("apalutamida", "clopidogrel"), "severity": "major", "effect": "paradoxical_activation"},
        # Inhibidor CYP2C19 (abiraterona) → sustratos aumentan exposición
        {"pair": ("abiraterona", "citalopram"), "severity": "major", "effect": "increased_exposure_qtc"},
        {"pair": ("abiraterona", "escitalopram"), "severity": "major", "effect": "increased_exposure_qtc"},
        {"pair": ("abiraterona", "clopidogrel"), "severity": "major", "effect": "loss_of_activation"},
        {"pair": ("abiraterona", "omeprazol"), "severity": "moderate", "effect": "increased_exposure"},
    ],
    "total_pairs": 10,
    "notes": (
        "Cobertura completa sobre los 4 sustratos CYP2C19 clínicamente "
        "relevantes en próstata × 3 perpetradores oncológicos activos. "
        "Darolutamida sin reglas por perfil CYP neutro (FDA Nubeqa §7). "
        "Abiraterona+clopidogrel se mantiene como 'major' (no 'moderate') "
        "por riesgo trombótico clínico, no PK aislado."
    ),
}


__all__ = [
    "CYP_METABOLISM",
    "CYP2C19_COVERAGE",
    "get_cyp_role",
    "shares_cyp_path",
    "enzyme_impact_for_pair",
]
