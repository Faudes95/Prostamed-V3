# -*- coding: utf-8 -*-
"""
Motor de interacciones farmacológicas (DDI) para oncología de próstata.

Verifica interacciones CYP3A4, riesgo QTc, umbral convulsivo y
pares de fármacos críticos. Incluye mapa de formulario IMSS/ISSSTE.

Reference:
  NCCN 5.2026 — Drug interaction documentation requirement
  PharmGKB / DrugBank — CYP metabolism data
  Fizazi K et al. — Abiraterone hepatotoxicity
  Shore ND et al. — Darolutamida seizure profile
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DDIAlert:
    """Interacción farmacológica detectada.

    Campos nuevos EPIC 4:
      * ``category``: etiqueta fisiopatológica (cyp3a4_induction,
        cyp2c19_induction, qtc_prolongation, seizure_threshold,
        bone_remodeling, pharmacodynamic_aldosterone, …). Habilita al
        motor de alertas clasificar hacia familias UI específicas.
      * ``alert_family``: asignación determinista a una familia consumida
        por ``alert_engine``: ``ddi_critical`` | ``ddi_major`` |
        ``ddi_moderate`` | ``ddi_qtc`` | ``ddi_seizure`` |
        ``ddi_bone_health``.
    """

    severity: str  # "contraindicated" | "major" | "moderate"
    drug_a: str
    drug_b: str
    mechanism: str
    clinical_impact: str
    recommended_action: str
    alternative: str = ""
    reference: str = ""
    category: str = ""
    alert_family: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Mapping severidad+categoría → familia de alerta (EPIC 4) ──
# ``ddi_qtc`` y ``ddi_seizure`` tienen prioridad sobre ``ddi_critical`` /
# ``ddi_major`` porque son sub-tipos clínicamente accionables distintos
# (ECG, neurología).
_CATEGORY_TO_FAMILY: dict[str, str] = {
    "qtc_prolongation": "ddi_qtc",
    "seizure_threshold": "ddi_seizure",
    "bone_remodeling": "ddi_bone_health",
}


def classify_alert_family(severity: str, category: str = "") -> str:
    """Determina la familia de alerta (UI/alert_engine) para una DDI.

    Las familias ``qtc`` / ``seizure`` / ``bone_health`` sobrescriben el
    mapeo genérico por severidad porque pueblan UIs especializadas
    (tarjeta ECG, neurología, DXA/bone health).
    """
    cat = str(category or "").strip().lower()
    if cat in _CATEGORY_TO_FAMILY:
        return _CATEGORY_TO_FAMILY[cat]
    sev = str(severity or "").strip().lower()
    if sev == "contraindicated":
        return "ddi_critical"
    if sev == "major":
        return "ddi_major"
    if sev == "moderate":
        return "ddi_moderate"
    return "ddi_info"


# ── Base de datos de interacciones críticas en oncología de próstata ──
_DDI_RULES: list[dict[str, Any]] = [
    # CYP3A4 — Abiraterona
    {"drug_a": "abiraterona", "drug_b": "ketoconazol", "severity": "contraindicated",
     "mechanism": "Abiraterona es inhibidor CYP3A4 + ketoconazol es inhibidor CYP3A4 fuerte",
     "impact": "Hepatotoxicidad severa aditiva", "action": "No coadministrar. Usar antifúngico alternativo (fluconazol tópico).",
     "alternative": "Fluconazol tópico", "ref": "Fizazi K et al. / PharmGKB"},
    {"drug_a": "abiraterona", "drug_b": "warfarina", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2C8 — altera metabolismo de warfarina",
     "impact": "Riesgo de sangrado por aumento de INR", "action": "Monitorear INR cada 1-2 semanas al iniciar. Considerar DOAC.",
     "alternative": "Rivaroxaban, apixaban", "ref": "PharmGKB / NCCN 5.2026"},
    {"drug_a": "abiraterona", "drug_b": "simvastatina", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP3A4 — aumenta niveles de estatinas metabolizadas por CYP3A4",
     "impact": "Riesgo de miopatía/rabdomiólisis", "action": "Cambiar a rosuvastatina o pravastatina (no CYP3A4).",
     "alternative": "Rosuvastatina, pravastatina", "ref": "DrugBank"},
    # CYP3A4 — Enzalutamida (inductor)
    {"drug_a": "enzalutamida", "drug_b": "warfarina", "severity": "major",
     "mechanism": "Enzalutamida es inductor CYP3A4 fuerte — reduce niveles de warfarina",
     "impact": "Pérdida de eficacia anticoagulante → riesgo trombótico", "action": "Monitorear INR frecuente. Considerar DOAC o ajustar dosis.",
     "alternative": "Apixaban con monitoreo", "ref": "PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "omeprazol", "severity": "moderate",
     "mechanism": "Enzalutamida induce CYP2C19 — reduce niveles de omeprazol",
     "impact": "Pérdida de eficacia del IBP", "action": "Considerar dosis doble de IBP o cambiar a pantoprazol.",
     "alternative": "Pantoprazol dosis ajustada", "ref": "PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "midazolam", "severity": "major",
     "mechanism": "Enzalutamida induce CYP3A4 — reduce niveles de benzodiacepinas CYP3A4",
     "impact": "Pérdida de eficacia sedante", "action": "Usar lorazepam (no CYP3A4) si se necesita benzodiacepina.",
     "alternative": "Lorazepam", "ref": "DrugBank"},
    # Olaparib
    {"drug_a": "olaparib", "drug_b": "itraconazol", "severity": "major",
     "mechanism": "Itraconazol es inhibidor CYP3A4 fuerte — aumenta niveles de olaparib",
     "impact": "Toxicidad hematológica aumentada", "action": "Reducir dosis de olaparib 50% o evitar inhibidor CYP3A4 fuerte.",
     "alternative": "Fluconazol (inhibidor CYP3A4 moderado)", "ref": "PharmGKB / Label FDA"},
    # Docetaxel
    {"drug_a": "docetaxel", "drug_b": "abiraterona", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP3A4 — docetaxel se metaboliza por CYP3A4",
     "impact": "Aumento potencial de toxicidad hematológica de docetaxel (neutropenia)",
     "action": "Monitorear hemograma estrechamente durante triplete ADT+docetaxel+abiraterona. Considerar ajuste de dosis si toxicidad grado 3-4.",
     "alternative": "Secuenciar en lugar de combinar cuando sea posible", "ref": "PharmGKB / ARASENS protocol safety"},
    {"drug_a": "docetaxel", "drug_b": "ketoconazol", "severity": "major",
     "mechanism": "Ketoconazol inhibe CYP3A4 — aumenta exposición a docetaxel",
     "impact": "Neutropenia severa aumentada", "action": "Evitar coadministración. Antifúngico alternativo.",
     "alternative": "Fluconazol", "ref": "Label FDA docetaxel"},
    # QTc prolongation
    {"drug_a": "enzalutamida", "drug_b": "ondansetrón", "severity": "moderate",
     "mechanism": "Ambos pueden prolongar QTc",
     "impact": "Riesgo de arritmia", "action": "ECG basal y a las 2 semanas. Considerar granisetron.",
     "alternative": "Granisetron", "ref": "NCCN Antiemesis"},
    {"drug_a": "abiraterona", "drug_b": "amiodarona", "severity": "major",
     "mechanism": "Riesgo aditivo de prolongación QTc + interacción CYP",
     "impact": "Arritmia potencialmente fatal", "action": "Monitoreo ECG estrecho. Considerar alternativa antiarrítmica.",
     "alternative": "Consultar cardiología", "ref": "PharmGKB"},
    # Seizure risk
    {"drug_a": "enzalutamida", "drug_b": "tramadol", "severity": "major",
     "mechanism": "Tramadol baja umbral convulsivo + enzalutamida tiene riesgo convulsivo 0.9%",
     "impact": "Riesgo convulsivo aumentado", "action": "Evitar tramadol. Usar morfina o hidromorfona.",
     "alternative": "Morfina, hidromorfona", "ref": "NCCN Pain / Shore ND 2019"},
    {"drug_a": "apalutamida", "drug_b": "tramadol", "severity": "major",
     "mechanism": "Apalutamida puede bajar umbral convulsivo + tramadol es proconvulsivo",
     "impact": "Riesgo convulsivo aumentado", "action": "Evitar tramadol. Cambiar a opioide sin efecto proconvulsivo.",
     "alternative": "Morfina, oxicodona", "ref": "SPARTAN safety data"},
    # ── CYP2D6 (metoprolol/codeina/oxicodona) — bloqueados por abiraterona/fluoxetina/paroxetina/bupropion
    {"drug_a": "abiraterona", "drug_b": "metoprolol", "severity": "major",
     "mechanism": "Abiraterona es inhibidor fuerte de CYP2D6 — metoprolol es sustrato CYP2D6",
     "impact": "Exposición a metoprolol incrementada — bradicardia, hipotensión, bloqueo",
     "action": "Reducir dosis de metoprolol 50% y monitorizar FC/PA. Considerar bisoprolol (menos dependiente CYP2D6).",
     "alternative": "Bisoprolol, carvedilol", "ref": "FDA Zytiga §7.1 / PharmGKB"},
    {"drug_a": "fluoxetina", "drug_b": "tamoxifeno", "severity": "major",
     "mechanism": "Fluoxetina es inhibidor fuerte CYP2D6 — tamoxifeno requiere CYP2D6 para activarse a endoxifeno",
     "impact": "Pérdida de eficacia antitumoral (endoxifeno ≈ activo)",
     "action": "Cambiar a venlafaxina o escitalopram (bajo impacto CYP2D6).",
     "alternative": "Venlafaxina, escitalopram", "ref": "Flockhart Table 2024 / DrugBank"},
    {"drug_a": "paroxetina", "drug_b": "tamoxifeno", "severity": "major",
     "mechanism": "Paroxetina es inhibidor fuerte CYP2D6",
     "impact": "Pérdida de eficacia de tamoxifeno",
     "action": "Cambiar a venlafaxina o escitalopram.",
     "alternative": "Venlafaxina", "ref": "Flockhart Table 2024"},
    {"drug_a": "bupropion", "drug_b": "tamoxifeno", "severity": "major",
     "mechanism": "Bupropion inhibe CYP2D6",
     "impact": "Reducción de conversión a endoxifeno",
     "action": "Evitar bupropion en pacientes con tamoxifeno adyuvante.",
     "alternative": "Vortioxetina, mirtazapina", "ref": "Flockhart Table 2024"},
    # ── CYP2C19 — enzalutamida/apalutamida inducen → pérdida eficacia citalopram/escitalopram/clopidogrel
    {"drug_a": "enzalutamida", "drug_b": "citalopram", "severity": "major",
     "mechanism": "Enzalutamida induce CYP2C19 — citalopram es sustrato CYP2C19",
     "impact": "Reducción de exposición — pérdida de eficacia antidepresiva",
     "action": "Monitorizar respuesta a los 4–6 semanas; considerar cambio a sertralina (no dependiente CYP2C19).",
     "alternative": "Sertralina, mirtazapina", "ref": "Xtandi label §7.2 / PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "escitalopram", "severity": "major",
     "mechanism": "Enzalutamida induce CYP2C19 — escitalopram sustrato CYP2C19",
     "impact": "Pérdida de eficacia antidepresiva",
     "action": "Monitorizar respuesta; considerar sertralina.",
     "alternative": "Sertralina", "ref": "Xtandi label §7.2"},
    {"drug_a": "apalutamida", "drug_b": "citalopram", "severity": "major",
     "mechanism": "Apalutamida induce CYP2C19 — citalopram sustrato",
     "impact": "Pérdida de eficacia antidepresiva",
     "action": "Monitorizar respuesta; considerar sertralina.",
     "alternative": "Sertralina", "ref": "Erleada label §7.2"},
    # ── Warfarina (CYP2C9/CYP3A4) — muchos moduladores
    {"drug_a": "apalutamida", "drug_b": "warfarina", "severity": "major",
     "mechanism": "Apalutamida induce CYP2C9 y CYP3A4",
     "impact": "Pérdida de eficacia anticoagulante",
     "action": "Monitorizar INR semanal las primeras 4 semanas; considerar apixaban/rivaroxaban.",
     "alternative": "Apixaban, rivaroxaban", "ref": "Erleada label §7.2"},
    # ── Estatinas CYP3A4 + enzalutamida inductor
    {"drug_a": "enzalutamida", "drug_b": "atorvastatina", "severity": "moderate",
     "mechanism": "Enzalutamida induce CYP3A4 — atorvastatina es sustrato CYP3A4",
     "impact": "Reducción de eficacia hipolipemiante",
     "action": "Monitorizar perfil lipídico; aumentar dosis o cambiar a rosuvastatina.",
     "alternative": "Rosuvastatina, pravastatina", "ref": "PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "simvastatina", "severity": "moderate",
     "mechanism": "Enzalutamida induce CYP3A4",
     "impact": "Reducción de eficacia",
     "action": "Cambiar a rosuvastatina (no CYP3A4).",
     "alternative": "Rosuvastatina, pravastatina", "ref": "PharmGKB"},
    # ── DOAC CYP3A4 — apixaban/rivaroxaban con enzalutamida/apalutamida
    {"drug_a": "enzalutamida", "drug_b": "apixaban", "severity": "major",
     "mechanism": "Enzalutamida induce CYP3A4 y P-gp — apixaban sustrato dual",
     "impact": "Exposición reducida — falla anticoagulante",
     "action": "Evitar apixaban; considerar enoxaparina o ajuste por hematología.",
     "alternative": "Enoxaparina", "ref": "FDA Eliquis §7"},
    {"drug_a": "enzalutamida", "drug_b": "rivaroxaban", "severity": "major",
     "mechanism": "Enzalutamida induce CYP3A4 y P-gp — rivaroxaban sustrato dual",
     "impact": "Exposición reducida — falla anticoagulante",
     "action": "Evitar rivaroxaban; considerar enoxaparina.",
     "alternative": "Enoxaparina", "ref": "FDA Xarelto §7"},
    {"drug_a": "apalutamida", "drug_b": "apixaban", "severity": "major",
     "mechanism": "Apalutamida induce CYP3A4 y P-gp",
     "impact": "Falla anticoagulante",
     "action": "Evitar apixaban.",
     "alternative": "Enoxaparina", "ref": "FDA Eliquis §7"},
    # ── Opioides CYP3A4 (fentanilo, oxicodona) + enzalutamida inductor
    {"drug_a": "enzalutamida", "drug_b": "fentanilo", "severity": "moderate",
     "mechanism": "Enzalutamida induce CYP3A4 — fentanilo sustrato CYP3A4",
     "impact": "Reducción de analgesia — riesgo de síndrome de abstinencia si se suspende enzalutamida",
     "action": "Ajustar dosis; preferir morfina (glucuronidación, no CYP3A4).",
     "alternative": "Morfina, hidromorfona", "ref": "PharmGKB"},
    # ── Abiraterona + dexametasona (steroide sustrato CYP3A4)
    {"drug_a": "abiraterona", "drug_b": "rifampicina", "severity": "contraindicated",
     "mechanism": "Rifampicina induce CYP3A4 potente — reduce abiraterona > 50%",
     "impact": "Pérdida de eficacia antineoplásica",
     "action": "Evitar rifampicina; usar alternativa antimicrobiana no inductora.",
     "alternative": "Doxiciclina", "ref": "FDA Zytiga §7.1"},
    # ── Darolutamida (menos interacciones, pero mantiene algunas)
    {"drug_a": "darolutamida", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4",
     "impact": "Reducción de exposición a darolutamida",
     "action": "Evitar rifampicina durante el tratamiento.",
     "alternative": "Doxiciclina", "ref": "FDA Nubeqa §7"},
    # ── PARP inhibidores con inhibidores potentes CYP3A4
    {"drug_a": "rucaparib", "drug_b": "ketoconazol", "severity": "major",
     "mechanism": "Ketoconazol inhibe CYP3A4 — rucaparib sustrato CYP3A4",
     "impact": "Toxicidad hematológica aumentada",
     "action": "Reducir dosis de rucaparib; preferir fluconazol.",
     "alternative": "Fluconazol", "ref": "FDA Rubraca §7"},
    {"drug_a": "talazoparib", "drug_b": "ketoconazol", "severity": "major",
     "mechanism": "Ketoconazol inhibe P-gp y CYP3A4 — talazoparib sustrato P-gp",
     "impact": "Toxicidad hematológica",
     "action": "Reducir talazoparib a 0.75 mg/d o evitar ketoconazol.",
     "alternative": "Fluconazol", "ref": "FDA Talzenna §7"},
    # ── Niraparib / Olaparib con rifampicina (CYP3A4 inductor)
    {"drug_a": "olaparib", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4 — olaparib sustrato",
     "impact": "Pérdida de eficacia antitumoral",
     "action": "Evitar rifampicina; alternativas antibióticas.",
     "alternative": "Doxiciclina", "ref": "FDA Lynparza §7"},
    # ── Ra-223 + denosumab / bifosfonato — fractura atípica
    {"drug_a": "radium_223", "drug_b": "denosumab", "severity": "moderate",
     "mechanism": "Ambos actúan sobre remodelado óseo — riesgo teórico de fracturas atípicas reportado en ERA-223",
     "impact": "Aumento de fracturas atípicas si se combinan sin monitoreo",
     "action": "Continuar denosumab con calcio/vitamina D; monitorizar DXA y fracturas; evitar combinación con abiraterona+prednisona+Ra-223.",
     "alternative": "Priorizar bifosfonato EV (zoledronato) con calcio/vitD", "ref": "ERA-223 Smith 2019"},
    {"drug_a": "radium_223", "drug_b": "abiraterona", "severity": "contraindicated",
     "mechanism": "Combinación Ra-223 + abiraterona + prednisona incrementó fracturas y mortalidad (ERA-223)",
     "impact": "Aumento de fracturas y muerte",
     "action": "No combinar Ra-223 con abiraterona; secuenciar.",
     "alternative": "Secuenciar (ARPI → Ra-223 tras progresión ósea)", "ref": "Smith 2019 Lancet Oncol (ERA-223)"},
    # ── Docetaxel + tamoxifeno / fluoxetina (CYP2D6 y 3A4 juntos)
    {"drug_a": "docetaxel", "drug_b": "itraconazol", "severity": "major",
     "mechanism": "Itraconazol inhibe CYP3A4",
     "impact": "Neutropenia severa",
     "action": "Evitar itraconazol; preferir fluconazol tópico.",
     "alternative": "Fluconazol", "ref": "FDA Taxotere §7"},
    {"drug_a": "docetaxel", "drug_b": "claritromicina", "severity": "major",
     "mechanism": "Claritromicina inhibidor CYP3A4 fuerte",
     "impact": "Neutropenia severa por exposición elevada",
     "action": "Cambiar a azitromicina.",
     "alternative": "Azitromicina", "ref": "FDA Taxotere §7"},

    # ══════════════════════════════════════════════════════════════════
    # EPIC 4 — Expansión comprehensiva (2026-04-18)
    # Añade ~30 reglas para cerrar CYP2D6 pro-drug blocking, CYP2C19
    # inducción clopidogrel, PARP-CYP3A4 extendido, cabazitaxel CYP3A4,
    # apalutamida CYP3A4 inducción simétrica a enzalutamida, QTc cascade
    # (moxifloxacino, metadona), Ra-223+zoledronato, aldosterona axis.
    # ══════════════════════════════════════════════════════════════════

    # ── CYP2D6 pro-drug blocking (abiraterona inhibidor fuerte) ──
    {"drug_a": "abiraterona", "drug_b": "codeina", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2D6 — codeína es pro-droga que requiere CYP2D6 para activarse a morfina",
     "impact": "Pérdida de analgesia — el pro-droga queda sin activar",
     "action": "Cambiar a morfina directa, hidromorfona u oxicodona de liberación inmediata.",
     "alternative": "Morfina, hidromorfona", "ref": "FDA Zytiga §7.1 / Flockhart Table 2024",
     "category": "cyp2d6_prodrug_block"},
    {"drug_a": "abiraterona", "drug_b": "oxicodona", "severity": "moderate",
     "mechanism": "Oxicodona tiene componente CYP2D6 dependiente (oxymorfona); abiraterona inhibe CYP2D6",
     "impact": "Analgesia atenuada vs concentración parental elevada",
     "action": "Titular oxicodona por respuesta clínica, monitorizar sedación; considerar hidromorfona.",
     "alternative": "Hidromorfona, morfina", "ref": "PharmGKB / Flockhart Table",
     "category": "cyp2d6_prodrug_block"},
    {"drug_a": "apalutamida", "drug_b": "metoprolol", "severity": "moderate",
     "mechanism": "Apalutamida es inhibidor moderado CYP2D6 — metoprolol sustrato",
     "impact": "Bradicardia e hipotensión moderadas en pacientes susceptibles",
     "action": "Monitorizar FC/PA; considerar bisoprolol o carvedilol si toxicidad.",
     "alternative": "Bisoprolol, carvedilol", "ref": "FDA Erleada §7.1",
     "category": "cyp2d6_substrate_block"},
    {"drug_a": "fluoxetina", "drug_b": "codeina", "severity": "major",
     "mechanism": "Fluoxetina inhibe CYP2D6 fuerte — impide activación de codeína a morfina",
     "impact": "Pérdida de analgesia",
     "action": "Cambiar a morfina o hidromorfona.",
     "alternative": "Morfina", "ref": "Flockhart Table 2024",
     "category": "cyp2d6_prodrug_block"},

    # ── CYP2C19 — enzalutamida/apalutamida inductoras vs clopidogrel (efecto paradójico) ──
    {"drug_a": "enzalutamida", "drug_b": "clopidogrel", "severity": "major",
     "mechanism": "Enzalutamida induce CYP2C19; clopidogrel requiere CYP2C19 para activar al metabolito tiol",
     "impact": "Exposición al metabolito activo variable — riesgo hemorrágico aumentado cuando se añade inductor, o falla antiagregante si se suspende bruscamente",
     "action": "Revisar indicación antiagregante; considerar ácido acetilsalicílico si adecuado o prasugrel/ticagrelor (no CYP2C19 dependiente).",
     "alternative": "AAS, prasugrel, ticagrelor", "ref": "Xtandi label §7.2 / PharmGKB",
     "category": "cyp2c19_induction"},
    {"drug_a": "apalutamida", "drug_b": "clopidogrel", "severity": "major",
     "mechanism": "Apalutamida induce CYP2C19 — clopidogrel sustrato dependiente para activación",
     "impact": "Respuesta antiagregante impredecible",
     "action": "Cambiar a AAS, prasugrel o ticagrelor.",
     "alternative": "AAS, prasugrel, ticagrelor", "ref": "Erleada label §7.2",
     "category": "cyp2c19_induction"},
    {"drug_a": "apalutamida", "drug_b": "escitalopram", "severity": "major",
     "mechanism": "Apalutamida induce CYP2C19 — escitalopram sustrato CYP2C19",
     "impact": "Pérdida de eficacia antidepresiva",
     "action": "Monitorizar respuesta a las 4-6 semanas; considerar sertralina.",
     "alternative": "Sertralina, mirtazapina", "ref": "Erleada label §7.2",
     "category": "cyp2c19_induction"},

    # ── PARP-CYP3A4 extendido ──
    {"drug_a": "niraparib", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4 — niraparib sustrato CYP3A4",
     "impact": "Reducción de exposición a niraparib — pérdida de eficacia antitumoral",
     "action": "Evitar rifampicina; usar doxiciclina u otro antimicrobiano no inductor.",
     "alternative": "Doxiciclina", "ref": "FDA Zejula §7",
     "category": "cyp3a4_induction"},
    {"drug_a": "rucaparib", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4 — rucaparib sustrato CYP3A4",
     "impact": "Pérdida de eficacia antitumoral",
     "action": "Evitar rifampicina; alternativas antibióticas.",
     "alternative": "Doxiciclina", "ref": "FDA Rubraca §7",
     "category": "cyp3a4_induction"},
    {"drug_a": "olaparib", "drug_b": "claritromicina", "severity": "major",
     "mechanism": "Claritromicina inhibidor CYP3A4 fuerte — olaparib sustrato",
     "impact": "Toxicidad hematológica aumentada (neutropenia/anemia/trombocitopenia)",
     "action": "Reducir olaparib 50% (200 mg BID si dosis plena); preferir azitromicina.",
     "alternative": "Azitromicina", "ref": "FDA Lynparza §7 / Patel 2022",
     "category": "cyp3a4_inhibition"},
    {"drug_a": "niraparib", "drug_b": "itraconazol", "severity": "major",
     "mechanism": "Itraconazol inhibe CYP3A4 fuerte — niraparib parcialmente CYP3A4",
     "impact": "Riesgo de trombocitopenia grado 3-4",
     "action": "Preferir fluconazol; monitorizar plaquetas semanal.",
     "alternative": "Fluconazol", "ref": "FDA Zejula §7",
     "category": "cyp3a4_inhibition"},
    {"drug_a": "olaparib", "drug_b": "fentanilo", "severity": "moderate",
     "mechanism": "Ambos son sustratos CYP3A4 — competencia metabólica",
     "impact": "Exposición olaparib y fentanilo potencialmente alteradas",
     "action": "Monitorizar analgesia + toxicidad hematológica; titular fentanilo.",
     "alternative": "Morfina (glucuronidación)", "ref": "PharmGKB",
     "category": "cyp3a4_competition"},

    # ── Cabazitaxel CYP3A4 (equivalente docetaxel, mayor hematotoxicidad) ──
    {"drug_a": "cabazitaxel", "drug_b": "ketoconazol", "severity": "major",
     "mechanism": "Ketoconazol inhibe CYP3A4 fuerte — cabazitaxel sustrato CYP3A4",
     "impact": "Neutropenia febril aumentada (cabazitaxel tiene mayor hematotoxicidad basal que docetaxel)",
     "action": "Evitar ketoconazol sistémico; considerar fluconazol tópico.",
     "alternative": "Fluconazol tópico", "ref": "FDA Jevtana §7",
     "category": "cyp3a4_inhibition"},
    {"drug_a": "cabazitaxel", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4 — reduce cabazitaxel",
     "impact": "Pérdida de eficacia antineoplásica",
     "action": "Evitar rifampicina; elegir antimicrobiano alternativo.",
     "alternative": "Doxiciclina", "ref": "FDA Jevtana §7",
     "category": "cyp3a4_induction"},
    {"drug_a": "cabazitaxel", "drug_b": "claritromicina", "severity": "major",
     "mechanism": "Claritromicina inhibidor CYP3A4 fuerte",
     "impact": "Neutropenia severa",
     "action": "Cambiar a azitromicina.",
     "alternative": "Azitromicina", "ref": "FDA Jevtana §7",
     "category": "cyp3a4_inhibition"},
    {"drug_a": "cabazitaxel", "drug_b": "itraconazol", "severity": "major",
     "mechanism": "Itraconazol inhibe CYP3A4 fuerte",
     "impact": "Neutropenia febril aumentada",
     "action": "Preferir fluconazol tópico; monitorizar hemograma estrecho.",
     "alternative": "Fluconazol", "ref": "FDA Jevtana §7",
     "category": "cyp3a4_inhibition"},

    # ── Apalutamida inducción CYP3A4 (simétrica a enzalutamida) ──
    {"drug_a": "apalutamida", "drug_b": "atorvastatina", "severity": "moderate",
     "mechanism": "Apalutamida induce CYP3A4 — atorvastatina sustrato CYP3A4",
     "impact": "Reducción de efecto hipolipemiante",
     "action": "Monitorizar LDL; cambiar a rosuvastatina si persiste el objetivo no alcanzado.",
     "alternative": "Rosuvastatina, pravastatina", "ref": "FDA Erleada §7.2",
     "category": "cyp3a4_induction"},
    {"drug_a": "apalutamida", "drug_b": "simvastatina", "severity": "moderate",
     "mechanism": "Apalutamida induce CYP3A4",
     "impact": "Reducción de eficacia",
     "action": "Cambiar a rosuvastatina (no CYP3A4).",
     "alternative": "Rosuvastatina, pravastatina", "ref": "FDA Erleada §7.2",
     "category": "cyp3a4_induction"},
    {"drug_a": "apalutamida", "drug_b": "midazolam", "severity": "major",
     "mechanism": "Apalutamida induce CYP3A4 — benzodiacepinas CYP3A4 pierden eficacia",
     "impact": "Sedación inadecuada en procedimientos",
     "action": "Usar lorazepam (no CYP3A4); ajustar dosis de midazolam si necesario.",
     "alternative": "Lorazepam", "ref": "FDA Erleada §7.2",
     "category": "cyp3a4_induction"},
    {"drug_a": "apalutamida", "drug_b": "rivaroxaban", "severity": "major",
     "mechanism": "Apalutamida induce CYP3A4 y P-gp — rivaroxaban sustrato dual",
     "impact": "Falla anticoagulante",
     "action": "Evitar rivaroxaban; considerar enoxaparina o ajuste por hematología.",
     "alternative": "Enoxaparina", "ref": "FDA Xarelto §7",
     "category": "cyp3a4_induction"},
    {"drug_a": "apalutamida", "drug_b": "fentanilo", "severity": "moderate",
     "mechanism": "Apalutamida induce CYP3A4 — fentanilo sustrato",
     "impact": "Reducción de analgesia",
     "action": "Titular fentanilo o cambiar a morfina (glucuronidación).",
     "alternative": "Morfina, hidromorfona", "ref": "FDA Erleada §7.2",
     "category": "cyp3a4_induction"},

    # ── QTc cascade — metadona / moxifloxacino ──
    {"drug_a": "enzalutamida", "drug_b": "metadona", "severity": "major",
     "mechanism": "Metadona prolonga QTc + enzalutamida induce CYP3A4 reduciendo metadona (efecto dual)",
     "impact": "Arritmia ventricular / pérdida de analgesia",
     "action": "ECG basal y a las 2 semanas; considerar morfina o hidromorfona; si metadona es imprescindible, ajustar dosis y monitorizar QTc cada 4 semanas.",
     "alternative": "Morfina, hidromorfona", "ref": "PharmGKB / NCCN Pain Management",
     "category": "qtc_prolongation"},
    {"drug_a": "abiraterona", "drug_b": "metadona", "severity": "major",
     "mechanism": "Metadona prolonga QTc; abiraterona tiene potencial QTc moderado",
     "impact": "Arritmia ventricular",
     "action": "ECG basal y seriado; preferir opioide alternativo.",
     "alternative": "Morfina, hidromorfona", "ref": "PharmGKB",
     "category": "qtc_prolongation"},
    {"drug_a": "abiraterona", "drug_b": "moxifloxacino", "severity": "major",
     "mechanism": "Riesgo aditivo de prolongación QTc",
     "impact": "Torsades de pointes potencial",
     "action": "Preferir levofloxacino o ciprofloxacino (menor impacto QTc); si moxifloxacino imprescindible, ECG basal y 48h.",
     "alternative": "Levofloxacino", "ref": "PharmGKB / FDA moxifloxacin label",
     "category": "qtc_prolongation"},
    {"drug_a": "enzalutamida", "drug_b": "moxifloxacino", "severity": "major",
     "mechanism": "Ambos con potencial QTc y competencia CYP3A4",
     "impact": "Torsades de pointes potencial",
     "action": "Preferir levofloxacino o ciprofloxacino; si moxifloxacino imprescindible, ECG seriado.",
     "alternative": "Levofloxacino", "ref": "PharmGKB",
     "category": "qtc_prolongation"},
    {"drug_a": "abiraterona", "drug_b": "ondansetron", "severity": "moderate",
     "mechanism": "Ambos pueden prolongar QTc",
     "impact": "Riesgo de arritmia moderado",
     "action": "ECG basal; preferir granisetron si persiste el uso crónico.",
     "alternative": "Granisetron", "ref": "NCCN Antiemesis / PharmGKB",
     "category": "qtc_prolongation"},

    # ── Bone remodeling — Ra-223 + zoledronato ──
    {"drug_a": "radium_223", "drug_b": "zoledronato", "severity": "moderate",
     "mechanism": "Ambos actúan sobre remodelado óseo; señal de fractura atípica menos pronunciada que con denosumab pero posible",
     "impact": "Riesgo teórico de fractura atípica / osteonecrosis maxilar aumentado",
     "action": "Continuar con calcio/vitamina D; DXA basal + evaluación odontológica; considerar espaciar administración.",
     "alternative": "Mantener zoledronato cada 12 semanas en lugar de mensual", "ref": "ERA-223 Smith 2019 / ALSYMPCA safety",
     "category": "bone_remodeling"},

    # ── Pharmacodynamic — abiraterona + espironolactona ──
    {"drug_a": "abiraterona", "drug_b": "espironolactona", "severity": "contraindicated",
     "mechanism": "Espironolactona activa parcialmente el receptor androgénico y tiene actividad glucocorticoidea que antagoniza la supresión de CYP17 por abiraterona",
     "impact": "Pérdida de eficacia antineoplásica y riesgo hormonal imprevisible",
     "action": "No coadministrar. Cambiar a eplerenona (selectivo mineralocorticoide) o amiloride si se necesita diurético ahorrador de potasio.",
     "alternative": "Eplerenona, amiloride", "ref": "FDA Zytiga §5.4 / Attard JCO 2009",
     "category": "pharmacodynamic_aldosterone"},

    # ── Inductores adicionales de CYP3A4 (carbamazepina / fenitoína) ──
    {"drug_a": "docetaxel", "drug_b": "rifampicina", "severity": "major",
     "mechanism": "Rifampicina induce CYP3A4 — reduce docetaxel hasta 50%",
     "impact": "Pérdida de eficacia antineoplásica",
     "action": "Evitar rifampicina durante quimioterapia.",
     "alternative": "Doxiciclina", "ref": "FDA Taxotere §7",
     "category": "cyp3a4_induction"},
    {"drug_a": "docetaxel", "drug_b": "carbamazepina", "severity": "major",
     "mechanism": "Carbamazepina induce CYP3A4",
     "impact": "Reducción de exposición a docetaxel",
     "action": "Si antiepiléptico imprescindible, preferir levetiracetam (no CYP3A4).",
     "alternative": "Levetiracetam, lacosamida", "ref": "PharmGKB",
     "category": "cyp3a4_induction"},
    {"drug_a": "enzalutamida", "drug_b": "carbamazepina", "severity": "major",
     "mechanism": "Inducción aditiva de CYP3A4 (ambos inductores) — aumenta catabolismo mutuo y de otros sustratos",
     "impact": "Pérdida de eficacia de otros fármacos CYP3A4 compartidos",
     "action": "Preferir levetiracetam o lacosamida; revisar medicación concomitante CYP3A4.",
     "alternative": "Levetiracetam", "ref": "PharmGKB",
     "category": "cyp3a4_induction"},
    {"drug_a": "abiraterona", "drug_b": "carbamazepina", "severity": "major",
     "mechanism": "Carbamazepina induce CYP3A4 — reduce abiraterona",
     "impact": "Pérdida de eficacia",
     "action": "Cambiar antiepiléptico a levetiracetam o lacosamida.",
     "alternative": "Levetiracetam", "ref": "FDA Zytiga §7.1",
     "category": "cyp3a4_induction"},
    {"drug_a": "enzalutamida", "drug_b": "fenitoina", "severity": "major",
     "mechanism": "Fenitoína induce CYP3A4 — reduce enzalutamida",
     "impact": "Pérdida de eficacia",
     "action": "Preferir levetiracetam; si fenitoína imprescindible, monitorizar respuesta PSA.",
     "alternative": "Levetiracetam", "ref": "Xtandi label §7.2",
     "category": "cyp3a4_induction"},

    # ══════════════════════════════════════════════════════════════════
    # EPIC 4 P0 DDI-G3 — Abiraterona es INHIBIDOR CYP2C19 (no inductor)
    # FDA Zytiga §7.2: impacto opuesto a enzalutamida/apalutamida.
    # Aumenta exposición de sustratos CYP2C19 → efecto adverso dosis-
    # dependiente (toxicidad SSRI, sangrado clopidogrel).
    # ══════════════════════════════════════════════════════════════════
    {"drug_a": "abiraterona", "drug_b": "citalopram", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2C19 moderado — citalopram es sustrato CYP2C19",
     "impact": "Exposición elevada — riesgo aditivo de prolongación QTc (citalopram tiene techo de 40 mg/d, 20 mg si >60 años)",
     "action": "Mantener citalopram ≤20 mg/d; ECG basal y 2 semanas; considerar sertralina (perfil DDI más limpio).",
     "alternative": "Sertralina, mirtazapina", "ref": "FDA Zytiga §7.2 / FDA Celexa QTc warning 2011",
     "category": "cyp2c19_inhibition"},
    {"drug_a": "abiraterona", "drug_b": "escitalopram", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2C19 — escitalopram sustrato CYP2C19",
     "impact": "Exposición incrementada — vigilar QTc y efectos serotoninérgicos",
     "action": "Mantener escitalopram ≤10 mg/d; ECG basal; considerar sertralina.",
     "alternative": "Sertralina", "ref": "FDA Zytiga §7.2 / PharmGKB",
     "category": "cyp2c19_inhibition"},
    {"drug_a": "abiraterona", "drug_b": "clopidogrel", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2C19 — clopidogrel es pro-droga que requiere CYP2C19 para activar metabolito tiol",
     "impact": "Pérdida de activación antiagregante — riesgo trombótico aumentado",
     "action": "Considerar AAS, prasugrel o ticagrelor (no CYP2C19 dependiente). Si clopidogrel imprescindible, considerar prueba de respuesta plaquetaria.",
     "alternative": "AAS, prasugrel, ticagrelor", "ref": "FDA Zytiga §7.2 / Plavix label §7",
     "category": "cyp2c19_inhibition"},
    {"drug_a": "abiraterona", "drug_b": "omeprazol", "severity": "moderate",
     "mechanism": "Abiraterona inhibe CYP2C19 — omeprazol sustrato CYP2C19 principal",
     "impact": "Exposición elevada de omeprazol — raramente clínicamente relevante",
     "action": "Considerar pantoprazol si efectos adversos emergen.",
     "alternative": "Pantoprazol", "ref": "FDA Zytiga §7.2",
     "category": "cyp2c19_inhibition"},

    # ── Abiraterona + Tamoxifeno (CYP2D6 prodrug block) ──
    {"drug_a": "abiraterona", "drug_b": "tamoxifeno", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2D6 fuerte — tamoxifeno requiere CYP2D6 para activarse a endoxifeno (metabolito activo)",
     "impact": "Pérdida de eficacia antitumoral del tamoxifeno (raro en próstata; relevante si paciente tiene ca de mama concomitante o ginecomastia farmacológica tratada con tamoxifeno)",
     "action": "Si tamoxifeno es para ginecomastia por ADT, considerar suspender o reemplazar por RT de mama preventiva; si es terapia adyuvante oncológica (ca de mama), reemplazar por anastrozol/letrozol.",
     "alternative": "Anastrozol (ca mama) / RT mama (ginecomastia)", "ref": "FDA Zytiga §7.1 / Flockhart Table 2024",
     "category": "cyp2d6_prodrug_block"},

    # ══════════════════════════════════════════════════════════════════
    # EPIC 4 P0 DDI-G7 — Bupropion baja umbral convulsivo y enzalutamida
    # /apalutamida tienen riesgo convulsivo basal (0.9% y 0.6%). La
    # combinación genera riesgo aditivo clínicamente significativo.
    # ══════════════════════════════════════════════════════════════════
    {"drug_a": "enzalutamida", "drug_b": "bupropion", "severity": "major",
     "mechanism": "Bupropion baja umbral convulsivo (dosis-dependiente) + enzalutamida tiene riesgo convulsivo basal 0.9%",
     "impact": "Riesgo convulsivo aumentado — relevante en pacientes con factores adicionales (metástasis cerebrales, epilepsia previa, benzodiacepinas en retirada)",
     "action": "Evitar bupropion durante tratamiento con enzalutamida. Alternativas: sertralina (depresión), vareniclina (cese tabáquico).",
     "alternative": "Sertralina, vareniclina", "ref": "FDA Xtandi §5.2 / FDA Wellbutrin seizure warning / Shore ND 2019",
     "category": "seizure_threshold"},
    {"drug_a": "apalutamida", "drug_b": "bupropion", "severity": "major",
     "mechanism": "Bupropion baja umbral convulsivo + apalutamida tiene riesgo convulsivo basal 0.6% (SPARTAN)",
     "impact": "Riesgo convulsivo aditivo",
     "action": "Evitar bupropion. Alternativas: sertralina (depresión), vareniclina (tabaco).",
     "alternative": "Sertralina, vareniclina", "ref": "FDA Erleada §5.4 / SPARTAN safety",
     "category": "seizure_threshold"},
]


# ── Formulario por institución (México) ──
_FORMULARY: dict[str, dict[str, dict[str, Any]]] = {
    "IMSS": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "apalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "darolutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 85000, "exception_path": "Solicitar dictamen de alta especialidad con justificación ARAMIS"},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "olaparib": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 95000, "exception_path": "Solicitar excepción con resultado PROfound-eligible y reporte molecular"},
        "pembrolizumab": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 120000, "exception_path": "Solicitar excepción con resultado MSI-H/dMMR confirmado"},
        "lu177_psma": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 150000, "exception_path": "Referir a centro con medicina nuclear (CMN SXXI, CMN La Raza)"},
        "radium223": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
    },
    "ISSSTE": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "apalutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 78000, "exception_path": "Solicitar por comité farmacoterapéutico"},
        "darolutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 85000, "exception_path": "Solicitar por comité farmacoterapéutico con justificación ARAMIS/ARASENS"},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "olaparib": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 95000, "exception_path": "Solicitar por comité con reporte molecular PROfound-eligible"},
        "pembrolizumab": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 120000, "exception_path": "Solicitar por comité con MSI-H confirmado"},
        "lu177_psma": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 150000, "exception_path": "Referir a centro de medicina nuclear con capacidad"},
        "radium223": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 90000, "exception_path": "Solicitar por comité con criterios ALSYMPCA"},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
    },
    "privado": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 45000},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 8000},
        "apalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 78000},
        "darolutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 85000},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 3000},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 65000},
        "olaparib": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 95000},
        "pembrolizumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 120000},
        "lu177_psma": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 150000},
        "radium223": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 90000},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 500},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 12000},
    },
}


class DDIEngine:
    """Motor de verificación de interacciones farmacológicas."""

    @classmethod
    def check_interactions(cls, oncology_drugs: list[str],
                           concomitant_medications: list[str],
                           seizure_history: bool = False) -> list[DDIAlert]:
        """Verifica interacciones entre fármacos oncológicos y medicamentos concomitantes."""
        alerts: list[DDIAlert] = []
        all_drugs = [d.lower().strip() for d in oncology_drugs + concomitant_medications if d]
        all_drug_set = set(all_drugs)

        for rule in _DDI_RULES:
            a = rule["drug_a"]
            b = rule["drug_b"]
            if a in all_drugs and b in all_drugs:
                category = rule.get("category", "")
                # Fallback heurístico para reglas legacy sin categoría:
                # detectar qtc / seizure a partir del texto del mecanismo.
                if not category:
                    text = f"{rule.get('mechanism','')} {rule.get('impact','')}".lower()
                    if "qtc" in text or "arritmia" in text or "torsades" in text:
                        category = "qtc_prolongation"
                    elif "umbral convulsivo" in text or "convulsi" in text or "seizure" in text:
                        category = "seizure_threshold"
                    elif "óseo" in text or "fractura atípica" in text or "remodelado" in text:
                        category = "bone_remodeling"
                    elif "inductor" in text or "induce" in text:
                        category = "cyp3a4_induction" if "cyp3a4" in text else category
                    elif "inhibidor" in text or "inhibe" in text:
                        category = "cyp3a4_inhibition" if "cyp3a4" in text else category
                alerts.append(DDIAlert(
                    severity=rule["severity"],
                    drug_a=rule["drug_a"].title(),
                    drug_b=rule["drug_b"].title(),
                    mechanism=rule["mechanism"],
                    clinical_impact=rule["impact"],
                    recommended_action=rule["action"],
                    alternative=rule.get("alternative", ""),
                    reference=rule.get("ref", ""),
                    category=category,
                    alert_family=classify_alert_family(rule["severity"], category),
                ))

        # Seizure risk check
        if seizure_history:
            for drug in all_drugs:
                if drug in {"enzalutamida", "apalutamida"}:
                    alerts.append(DDIAlert(
                        severity="contraindicated",
                        drug_a=drug.title(),
                        drug_b="Historia de convulsiones",
                        mechanism=f"{drug.title()} baja umbral convulsivo (0.9% enzalutamida, 0.6% apalutamida)",
                        clinical_impact="Riesgo convulsivo inaceptable",
                        recommended_action=f"Contraindicar {drug.title()}. Preferir darolutamida (0.2% seizures, baja penetración BHE).",
                        alternative="Darolutamida",
                        reference="SPARTAN, PROSPER safety data / Shore ND 2019",
                        category="seizure_threshold",
                        alert_family="ddi_seizure",
                    ))
            # Triple check: seizure_history + ARPI proconvulsivo + tramadol = contraindicación absoluta
            arpi_proconvulsivo = all_drug_set & {"enzalutamida", "apalutamida"}
            if arpi_proconvulsivo and "tramadol" in all_drug_set:
                arpi_name = next(iter(arpi_proconvulsivo)).title()
                alerts.append(DDIAlert(
                    severity="contraindicated",
                    drug_a=f"{arpi_name} + Tramadol",
                    drug_b="Historia de convulsiones",
                    mechanism=f"Triple riesgo convulsivo: {arpi_name} (proconvulsivo) + tramadol (baja umbral) + historia de convulsiones",
                    clinical_impact="Riesgo convulsivo inaceptablemente alto — combinación triple absolutamente contraindicada",
                    recommended_action=f"Suspender {arpi_name} y tramadol. Cambiar a darolutamida + opioide sin efecto proconvulsivo (morfina, hidromorfona).",
                    alternative="Darolutamida + morfina/hidromorfona",
                    reference="SPARTAN safety / Shore ND 2019 / NCCN Pain Management",
                    category="seizure_threshold",
                    alert_family="ddi_seizure",
                ))

        return alerts

    @classmethod
    def check_formulary(cls, drug_name: str, institution: str = "IMSS") -> dict[str, Any]:
        """Verifica disponibilidad en formulario institucional."""
        inst = institution.upper()
        if inst not in _FORMULARY:
            inst = "IMSS"
        formulary = _FORMULARY[inst]

        drug_key = drug_name.lower().strip().replace("-", "").replace(" ", "_")
        # Fuzzy match
        for key in formulary:
            if key in drug_key or drug_key in key:
                entry = formulary[key]
                return {
                    "drug": drug_name,
                    "institution": inst,
                    "available": entry["available"],
                    "cuadro_basico": entry["cuadro_basico"],
                    "generic_available": entry.get("generic", False),
                    "monthly_cost_mxn": entry.get("monthly_cost_mxn", 0),
                    "exception_path": entry.get("exception_path", ""),
                }
        return {
            "drug": drug_name,
            "institution": inst,
            "available": False,
            "cuadro_basico": False,
            "generic_available": False,
            "monthly_cost_mxn": 0,
            "exception_path": "Fármaco no encontrado en formulario — verificar disponibilidad con farmacia institucional.",
        }

    @classmethod
    def check_medication_list(
        cls,
        medications: Any,
        therapy_candidate: Any = None,
        *,
        seizure_history: bool = False,
    ) -> list[DDIAlert]:
        """Evalúa DDI entre una lista estructurada de medicación concomitante
        (``MedicationEntry``, dicts o strings) y una terapia oncológica
        candidata.

        Usa ``medication_list.normalize_medication_list`` para homologar
        aliases comerciales (Lexapro → escitalopram, Zytiga → abiraterona),
        de forma que los match contra ``_DDI_RULES`` sean robustos.

        Parámetros:
            medications: Iterable heterogéneo (string libre, list[dict],
                list[MedicationEntry]). Puede venir del campo ``medication_list``
                del schema o del legacy ``current_medications``.
            therapy_candidate: Fármaco oncológico propuesto (string o
                list[str]).
            seizure_history: Si ``True`` activa los gates de umbral
                convulsivo (enzalutamida/apalutamida + tramadol, etc).

        Retorna ``list[DDIAlert]`` ordenada por severidad (contraindicated
        primero).
        """
        # Lazy import para evitar ciclo con contracts → ddi_engine en boot.
        from prostanet.shared.medication_list import normalize_medication_list

        normalized = normalize_medication_list(medications)
        concomitant_names = [entry.name for entry in normalized if entry.name]

        if therapy_candidate is None:
            oncology = []
        elif isinstance(therapy_candidate, str):
            oncology = [therapy_candidate]
        else:
            oncology = [str(item).strip() for item in therapy_candidate if str(item).strip()]

        alerts = cls.check_interactions(
            oncology_drugs=oncology,
            concomitant_medications=concomitant_names,
            seizure_history=seizure_history,
        )

        severity_order = {"contraindicated": 0, "major": 1, "moderate": 2}
        alerts.sort(key=lambda a: severity_order.get(a.severity, 3))
        return alerts

    @classmethod
    def compute_regimen_ddi_matrix(
        cls,
        medications: Any,
        regimen_candidates: list[str],
        *,
        seizure_history: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Construye ``ddi_regimen_matrix`` real-time para ``arpi_selection_engine``.

        Para cada código de régimen candidato evalúa la lista de
        medicaciones concomitantes + el fármaco oncológico del régimen
        y retorna el peor gate:

          * ``status``: ``"contraindicated"`` | ``"major"`` | ``"caution"``
            (moderate) | ``"none"`` — usado por ``_safety_adjustment``.
          * ``families``: set de familias de alerta detectadas
            (``ddi_critical``, ``ddi_major``, ``ddi_qtc``,
            ``ddi_seizure``, ``ddi_bone_health``).
          * ``alerts``: lista de ``DDIAlert.to_dict()`` para surface UI.
          * ``alert_count``, ``contraindicated_count``, ``major_count``.

        Esto convierte ``ddi_review_status`` de binario a real-time
        para cada regimen candidato sin requerir cálculo externo.
        """
        # Lazy import para evitar ciclo.
        from prostanet.shared.medication_list import normalize_medication_list

        normalized = normalize_medication_list(medications)
        concomitant_names = [entry.name for entry in normalized if entry.name]
        if not concomitant_names:
            return {}

        matrix: dict[str, dict[str, Any]] = {}
        severity_rank = {"contraindicated": 3, "major": 2, "moderate": 1}
        status_label = {3: "contraindicated", 2: "major", 1: "caution"}

        for regimen_code in regimen_candidates:
            if not regimen_code:
                continue
            oncology_drug = cls._regimen_to_oncology_drug(regimen_code)
            if not oncology_drug:
                continue
            alerts = cls.check_interactions(
                oncology_drugs=[oncology_drug],
                concomitant_medications=concomitant_names,
                seizure_history=seizure_history,
            )
            worst = 0
            families: set[str] = set()
            for al in alerts:
                worst = max(worst, severity_rank.get(al.severity, 0))
                if al.alert_family:
                    families.add(al.alert_family)
            matrix[regimen_code] = {
                "status": status_label.get(worst, "none"),
                "families": sorted(families),
                "alerts": [a.to_dict() for a in alerts],
                "alert_count": len(alerts),
                "contraindicated_count": sum(1 for a in alerts if a.severity == "contraindicated"),
                "major_count": sum(1 for a in alerts if a.severity == "major"),
                "oncology_drug": oncology_drug,
            }
        return matrix

    @staticmethod
    def _regimen_to_oncology_drug(regimen_code: str) -> str:
        """Mapea código canónico de régimen (p.ej. ``ADT_ENZALUTAMIDE``)
        al fármaco oncológico activo para búsqueda en ``_DDI_RULES``.

        Regimenes combinados se representan por su ARPI/quimio central
        porque las reglas DDI aplican sobre el metabolizado principal.
        Los nombres devueltos coinciden con ``drug_a``/``drug_b`` en
        ``_DDI_RULES`` (español, minúscula, sin acentos).
        """
        code = (regimen_code or "").upper()
        if not code:
            return ""
        # Orden importa: rutas con PARP_ARPI deben mapear al PARP para
        # que olaparib/rucaparib/etc. sean el eje; cabazitaxel y
        # docetaxel preceden al ARPI en triplete.
        mapping = [
            ("CABAZITAXEL", "cabazitaxel"),
            ("DOCETAXEL", "docetaxel"),
            ("OLAPARIB", "olaparib"),
            ("RUCAPARIB", "rucaparib"),
            ("NIRAPARIB", "niraparib"),
            ("TALAZOPARIB", "talazoparib"),
            ("ABIRATERONE", "abiraterona"),
            ("ABIRATERONA", "abiraterona"),
            ("APALUTAMIDE", "apalutamida"),
            ("APALUTAMIDA", "apalutamida"),
            ("DAROLUTAMIDE", "darolutamida"),
            ("DAROLUTAMIDA", "darolutamida"),
            ("ENZALUTAMIDE", "enzalutamida"),
            ("ENZALUTAMIDA", "enzalutamida"),
            ("RADIUM", "radium_223"),
            ("LU177", "lutetium_177"),
            ("PEMBROLIZUMAB", "pembrolizumab"),
        ]
        for needle, drug in mapping:
            if needle in code:
                return drug
        return ""

    @classmethod
    def full_review(cls, patient: dict[str, Any]) -> dict[str, Any]:
        """Revisión completa de DDI y formulario para un paciente."""
        # Extract medications
        current_meds_raw = patient.get("current_medications") or ""
        if isinstance(current_meds_raw, str):
            current_meds = [m.strip() for m in current_meds_raw.replace(";", ",").split(",") if m.strip()]
        else:
            current_meds = list(current_meds_raw)

        oncology_drugs_raw = patient.get("oncology_drugs") or patient.get("current_treatment") or ""
        if isinstance(oncology_drugs_raw, str):
            oncology_drugs = [m.strip() for m in oncology_drugs_raw.replace(";", ",").split(",") if m.strip()]
        else:
            oncology_drugs = list(oncology_drugs_raw)

        seizure = str(patient.get("comorbidity_seizure") or patient.get("seizure_history") or "0")
        seizure_history = seizure.lower() in {"1", "true", "yes", "si"}

        # Check interactions
        ddi_alerts = cls.check_interactions(oncology_drugs, current_meds, seizure_history)

        # Check formulary for each oncology drug
        institution = str(patient.get("institution") or patient.get("institucion") or "IMSS")
        formulary_results = []
        for drug in oncology_drugs:
            formulary_results.append(cls.check_formulary(drug, institution))

        return {
            "ddi_alerts": [a.to_dict() for a in ddi_alerts],
            "ddi_count": len(ddi_alerts),
            "contraindicated_count": sum(1 for a in ddi_alerts if a.severity == "contraindicated"),
            "formulary": formulary_results,
            "institution": institution,
            "has_data": len(oncology_drugs) > 0 or len(current_meds) > 0,
            "ddi_reviewed": len(ddi_alerts) >= 0,  # Mark as reviewed
        }


# ── EPIC 4 P0 DDI-G2: alias module-level para consumo externo ──
# Permite `from prostanet.shared.ddi_engine import evaluate_medication_list`
# sin ligarse a la clase, manteniendo backward compat con
# `DDIEngine.check_medication_list` (usado por alert_engine y
# clinical_decision_governance).
evaluate_medication_list = DDIEngine.check_medication_list


__all__ = [
    "DDIAlert",
    "DDIEngine",
    "classify_alert_family",
    "evaluate_medication_list",
]
