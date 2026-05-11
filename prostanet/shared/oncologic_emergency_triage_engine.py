"""oncologic_emergency_triage_engine.py — Triaje pre-biopsia y oncológico.

Centraliza el cribado de emergencias oncológicas en cáncer de próstata.
Reusable desde ``diagnostic_workup``, ``localized_initial``, ``mcspc_*``,
``m1_crpc``, ``m0_crpc``, ``recurrence_bcr``, ``palliative_pathway``.

Brecha clínica reportada (2026-04-23): paciente con APE 5000 ng/mL + DRE
con próstata fija y pétrea sin biopsia llega a ProstaNet sin cribado de
emergencias (compresión medular, hidronefrosis bilateral, hipercalcemia,
hematuria severa, fractura patológica, retención refractaria) — campos
existían como huérfanos en ``palliative_pathway`` pero no se activaban
fuera de la vía paliativa.

Referencias:
  - NCCN Oncologic Emergencies Guidelines v3.2026
  - Loblaw DA et al. ASCO 2012 — Metastatic Spinal Cord Compression
    *J Clin Oncol* 2012;30:1581-7
  - ASCO/AUA Bone Health Guidelines 2024 (Saylor PJ et al, JCO 2024)
  - EAU 2026 §6.5.5 — Hidronefrosis y retención urinaria
"""
from __future__ import annotations

from typing import Any

# ── Helpers privados (no duplican públicos pero unifican normalización) ─
_TRUTHY_YES = {"sí", "si", "yes", "1", "true", "verdadero"}


def _norm(value: Any) -> str:
    """Normaliza a minúsculas + strip; vacíos → ''."""
    if value in (None, "", [], {}):
        return ""
    return str(value).strip().lower()


def _txt(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return _norm(value)
    return ""


# ── Detectores individuales de emergencia ──────────────────────────────
def _detect_cord_compression(payload: dict) -> dict | None:
    """Compresión medular sospechada o establecida.

    Trigger: spinal_cord_compression=Sí, debilidad MMII moderada/severa,
    o síntomas neurológicos sugerentes (debilidad, anestesia silla de
    montar, retención/incontinencia nueva).
    """
    cord = _txt(payload, "spinal_cord_compression", "epidural_compression")
    weakness = _txt(payload, "lower_limb_weakness")
    symptoms = _txt(payload, "cord_compression_symptoms")
    triggered = (
        cord in _TRUTHY_YES
        or any(kw in weakness for kw in ("moderada", "severa", "paresia"))
        or any(
            kw in symptoms
            for kw in (
                "debilidad",
                "anestesia",
                "retención urinaria nueva",
                "retencion urinaria nueva",
                "incontinencia fecal",
            )
        )
    )
    if not triggered:
        return None
    return {
        "code": "cord_compression",
        "name": "Sospecha de compresión medular",
        "severity": "critical",
        "tta_hours": 24,
        "actions": [
            "RM columna completa urgente <24 h (con/sin gadolinio)",
            "Dexametasona 16 mg IV bolo + 4 mg c/6 h hasta diagnóstico",
            "Consulta oncología radioterápica + neurocirugía simultánea",
            "Si confirmación: RT urgente 30 Gy/10 fx o cirugía descompresiva (Patchell criteria) + ADT",
            "NO retrasar dexametasona esperando RM",
        ],
        "evidence_tag": "loblaw_2012",
        "rationale": (
            "Demora >24 h se asocia a paraplejia irreversible (Loblaw ASCO 2012)."
        ),
    }


def _detect_obstructive_uropathy(payload: dict) -> dict | None:
    """Hidronefrosis obstructiva (bilateral con IRA = crítica)."""
    val = _txt(payload, "obstructive_uropathy_severity", "obstructive_uropathy")
    if "bilateral" in val and "ira" in val:
        return {
            "code": "obstructive_uropathy_bilateral",
            "name": "Hidronefrosis bilateral con insuficiencia renal aguda",
            "severity": "critical",
            "tta_hours": 24,
            "actions": [
                "Nefrostomía percutánea bilateral o catéteres JJ urgentes",
                "Hidratación + corrección electrolítica",
                "Iniciar ADT empírico (degarelix/relugolix) tras drenaje",
                "Considerar RT pélvica hemostática si componente hemorrágico",
            ],
            "evidence_tag": "nccn_oncologic_emergencies",
            "rationale": "IRA obstructiva post-renal puede ser irreversible si no se drena <48 h.",
        }
    if "unilateral severa" in val:
        return {
            "code": "obstructive_uropathy_unilateral",
            "name": "Hidronefrosis unilateral severa",
            "severity": "high",
            "tta_hours": 72,
            "actions": [
                "Catéter JJ o nefrostomía según función renal contralateral",
                "Iniciar ADT empírico si APE elevado + cT4",
            ],
            "evidence_tag": "eau_2026_6_5_5",
        }
    return None


def _detect_pathological_fracture(payload: dict) -> dict | None:
    """Fractura patológica documentada."""
    val = _txt(payload, "pathological_fracture_present", "pathological_fracture_risk")
    if not val or "no" == val or "desconocido" in val:
        return None
    if "sí" in val or "si" in val:
        site = "no especificado"
        if "—" in val:
            site = val.split("—")[-1].strip()
        elif "-" in val:
            parts = val.split("-")
            if len(parts) > 1:
                site = parts[-1].strip()
        return {
            "code": "pathological_fracture",
            "name": f"Fractura patológica ({site})",
            "severity": "high",
            "tta_hours": 48,
            "actions": [
                "Ortopedia oncológica para fijación profiláctica/post-fractura (Mirels score si pendiente)",
                "RT post-fijación 8 Gy/1 fx o 30 Gy/10 fx",
                "Iniciar agente óseo: denosumab 120 mg SC c/4 sem o zoledronato 4 mg IV c/4 sem",
                "Suplementar vitamina D + calcio (si no hipercalcémico)",
            ],
            "evidence_tag": "asco_aua_bone_health_2024",
        }
    return None


def _detect_severe_hematuria(payload: dict) -> dict | None:
    """Hematuria severa con coágulos / retención por coágulos."""
    val = _txt(payload, "gross_hematuria_severity", "hematuria_severe")
    if "retención por coágulos" in val or "retencion por coagulos" in val or "con coágulos" in val or "con coagulos" in val:
        return {
            "code": "severe_hematuria",
            "name": "Hematuria severa con coágulos",
            "severity": "high",
            "tta_hours": 24,
            "actions": [
                "Sonda Foley 3 vías + irrigación continua con SF",
                "Cistoscopia + RTU hemostática si coágulos refractarios",
                "RT hemostática pélvica 30 Gy/10 fx + ADT empírico si tumor primario sangrante",
                "Considerar embolización selectiva arterias prostáticas si refractario",
            ],
            "evidence_tag": "nccn_oncologic_emergencies",
        }
    return None


def _detect_hypercalcemia(payload: dict) -> dict | None:
    """Hipercalcemia maligna (Ca >12 = crítica, 10.5-12 = alta)."""
    val = _txt(payload, "hypercalcemia_present")
    if not val or val == "no" or "desconocido" in val:
        return None
    if "sí" in val or "si" in val:
        severity = "critical" if ">12" in val else "high"
        return {
            "code": "hypercalcemia",
            "name": "Hipercalcemia maligna",
            "severity": severity,
            "tta_hours": 24 if severity == "critical" else 48,
            "actions": [
                "Hidratación SF 200-300 mL/h hasta diuresis 100-150 mL/h",
                "Zoledronato 4 mg IV (dosis única; ajustar a aclaramiento) o denosumab 120 mg SC",
                "Calcitonina 4-8 UI/kg SC c/12 h primeras 48 h si Ca >14",
                "Iniciar ADT empírico (relugolix/degarelix evita flare)",
                "Evitar tiazidas, suplementos de calcio y vitamina D",
            ],
            "evidence_tag": "nccn_oncologic_emergencies",
        }
    return None


def _detect_acute_urinary_retention(payload: dict) -> dict | None:
    """Retención urinaria aguda — refractaria (high) o sondaje (moderate)."""
    val = _txt(payload, "acute_urinary_retention")
    if "refractaria" in val:
        return {
            "code": "acute_urinary_retention_refractory",
            "name": "Retención urinaria refractaria",
            "severity": "high",
            "tta_hours": 24,
            "actions": [
                "Cistostomía suprapúbica si sondaje uretral imposible",
                "ADT empírico (degarelix preferente — descenso rápido sin flare)",
                "RT pélvica paliativa 30 Gy/10 fx si tumor primario obstructivo",
                "Considerar RTU paliativa si masa prostática >100 g",
            ],
            "evidence_tag": "eau_2026_6_5_5",
        }
    if "sondaje requerido" in val:
        return {
            "code": "acute_urinary_retention",
            "name": "Retención urinaria aguda (sondada)",
            "severity": "moderate",
            "tta_hours": 72,
            "actions": [
                "Sondaje vesical permanente provisional",
                "Iniciar ADT temprano si APE elevado + cT3-T4",
                "Programar manejo definitivo (RTU, RT, ADT escalonado)",
            ],
            "evidence_tag": "eau_2026_6_5_5",
        }
    return None


_DETECTORS = (
    _detect_cord_compression,
    _detect_obstructive_uropathy,
    _detect_pathological_fracture,
    _detect_severe_hematuria,
    _detect_hypercalcemia,
    _detect_acute_urinary_retention,
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2}


def detect_oncologic_emergencies(payload: dict) -> list[dict]:
    """Retorna lista de emergencias detectadas, ordenadas por severidad."""
    if not isinstance(payload, dict):
        return []
    found = [det(payload) for det in _DETECTORS]
    found = [e for e in found if e is not None]
    found.sort(key=lambda e: _SEVERITY_ORDER.get(e.get("severity", ""), 99))
    return found


def emergency_triage_descriptor(payload: dict) -> dict | None:
    """Descriptor unificado para emisión en services y UI.

    Retorna ``None`` si no hay emergencia; ``dict`` con resumen + lista de
    emergencias si sí.
    """
    emergencies = detect_oncologic_emergencies(payload)
    if not emergencies:
        return None
    critical = [e for e in emergencies if e["severity"] == "critical"]
    high = [e for e in emergencies if e["severity"] == "high"]
    moderate = [e for e in emergencies if e["severity"] == "moderate"]
    return {
        "any_emergency": True,
        "critical_count": len(critical),
        "high_count": len(high),
        "moderate_count": len(moderate),
        "max_severity": emergencies[0]["severity"],
        "min_tta_hours": min(e["tta_hours"] for e in emergencies),
        "emergencies": emergencies,
        "requires_immediate_referral": bool(critical or high),
    }
