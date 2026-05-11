"""TNM Staging Engine — ensamblaje modular de estadificación TNM para cáncer de próstata.

Provee:
- Ensamblaje T + N + M desde datos del paciente
- Metadata visual (severity, imagen, descripción) para cada componente
- Backward-compatibility con el campo legacy ``dre_suspicious`` (binario)

Referencia: AJCC Cancer Staging Manual, 8th Edition (2017); NCCN 5.2026.
"""

from __future__ import annotations

from typing import Any

from prostanet.shared.metastatic_profile import build_metastatic_profile, summarize_metastatic_profile
from prostanet.shared.tnm_metastatic_renderer import render_m_stage_visual

# ── T-Stage Data ─────────────────────────────────────────────────────────────

TNM_T_DATA: dict[str, dict[str, Any]] = {
    "T1": {
        "label": "T1",
        "short": "No palpable",
        "desc": "Tumor no palpable ni visible por imagen, detectado por PSA elevado",
        "severity": "low",
        "image": "real_stage/t1_real.png",
        "color": "#10b981",
    },
    "T1c": {
        "label": "T1c",
        "short": "Detectado por PSA",
        "desc": "Tumor detectado por biopsia indicada por PSA elevado, no palpable al tacto rectal",
        "severity": "low",
        "image": "real_stage/t1_real.png",
        "color": "#10b981",
    },
    "T2a": {
        "label": "T2a",
        "short": "≤50% un lóbulo",
        "desc": "Tumor afecta la mitad o menos de un lóbulo prostático",
        "severity": "low",
        "image": "real_stage/t2a_real.png",
        "color": "#10b981",
    },
    "T2b": {
        "label": "T2b",
        "short": ">50% un lóbulo",
        "desc": "Tumor afecta más de la mitad de un lóbulo prostático",
        "severity": "intermediate",
        "image": "real_stage/t2b_real.png",
        "color": "#f59e0b",
    },
    "T2c": {
        "label": "T2c",
        "short": "Ambos lóbulos",
        "desc": "Tumor afecta ambos lóbulos prostáticos",
        "severity": "intermediate",
        "image": "real_stage/t2c_real.png",
        "color": "#f59e0b",
    },
    "T3": {
        "label": "T3",
        "short": "Extensión extracapsular",
        "desc": "Extensión del tumor fuera de la cápsula prostática",
        "severity": "high",
        "image": "real_stage/t3_real.png",
        "color": "#f43f5e",
    },
    "T3a": {
        "label": "T3a",
        "short": "Extensión extracapsular",
        "desc": "Extensión extracapsular unilateral o bilateral sin invasión de vesículas seminales",
        "severity": "high",
        "image": "real_stage/t3_real.png",
        "color": "#f43f5e",
    },
    "T3b": {
        "label": "T3b",
        "short": "Vesículas seminales",
        "desc": "Invasión de una o ambas vesículas seminales",
        "severity": "high",
        "image": "real_stage/t3_real.png",
        "color": "#f43f5e",
    },
    "T4": {
        "label": "T4",
        "short": "Órganos adyacentes",
        "desc": "Tumor fijado o que invade vejiga, recto, pared pélvica u otros órganos adyacentes",
        "severity": "very_high",
        "image": "real_stage/t4_real.png",
        "color": "#dc2626",
    },
}

# ── N-Stage Data ─────────────────────────────────────────────────────────────

TNM_N_DATA: dict[str, dict[str, Any]] = {
    "N0": {
        "label": "N0",
        "short": "Sin afectación",
        "desc": "Sin metástasis en ganglios linfáticos regionales",
        "severity": "low",
        "image": None,
        "color": "#10b981",
    },
    "N1": {
        "label": "N1",
        "short": "Ganglios afectados",
        "desc": "Metástasis en ganglios linfáticos regionales",
        "severity": "high",
        "image": "real_stage/n1_real.png",
        "color": "#f43f5e",
    },
}

# ── M-Stage Data ─────────────────────────────────────────────────────────────

TNM_M_DATA: dict[str, dict[str, Any]] = {
    "M0": {
        "label": "M0",
        "short": "Sin metástasis",
        "desc": "Sin metástasis a distancia",
        "severity": "low",
        "image": None,
        "color": "#10b981",
    },
    "M1": {
        "label": "M1",
        "short": "Metástasis a distancia",
        "desc": "Metástasis a distancia con distribución anatómica incompleta",
        "severity": "very_high",
        "image": None,
        "color": "#dc2626",
    },
    "M1a": {
        "label": "M1a",
        "short": "Ganglios no regionales",
        "desc": "Metástasis en ganglios linfáticos no regionales",
        "severity": "high",
        "image": None,
        "color": "#f43f5e",
    },
    "M1b": {
        "label": "M1b",
        "short": "Metástasis ósea",
        "desc": "Metástasis ósea con distribución axial / apendicular",
        "severity": "very_high",
        "image": None,
        "color": "#dc2626",
    },
    "M1c": {
        "label": "M1c",
        "short": "Metástasis visceral",
        "desc": "Metástasis visceral con detalle por órgano afectado",
        "severity": "very_high",
        "image": None,
        "color": "#dc2626",
    },
}

# ── DRE → T-Stage Mapping ───────────────────────────────────────────────────

_DRE_FINDING_TO_TSTAGE: dict[str, str | None] = {
    "Normal": None,
    "T1 - No palpable (detectado por PSA)": "T1",
    "T2a - Afecta ≤50% de un lóbulo": "T2a",
    "T2b - Afecta >50% de un lóbulo": "T2b",
    "T2c - Afecta ambos lóbulos": "T2c",
    "T3 - Extensión fuera de la cápsula": "T3",
    "T4 - Invade órganos adyacentes": "T4",
}

# ── Severity → Tailwind Classes ──────────────────────────────────────────────

SEVERITY_CLASSES: dict[str, dict[str, str]] = {
    "low": {
        "bg": "bg-emerald-500/10",
        "border": "border-emerald-500/30",
        "text": "text-emerald-300",
        "badge_bg": "bg-emerald-500",
    },
    "intermediate": {
        "bg": "bg-amber-500/10",
        "border": "border-amber-500/30",
        "text": "text-amber-300",
        "badge_bg": "bg-amber-500",
    },
    "high": {
        "bg": "bg-rose-500/10",
        "border": "border-rose-500/30",
        "text": "text-rose-300",
        "badge_bg": "bg-rose-500",
    },
    "very_high": {
        "bg": "bg-red-600/10",
        "border": "border-red-600/30",
        "text": "text-red-300",
        "badge_bg": "bg-red-600",
    },
}


def _canonical_t_stage_label(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    for key in sorted(TNM_T_DATA.keys(), key=len, reverse=True):
        if upper == key.upper():
            return key
    for key in sorted(TNM_T_DATA.keys(), key=len, reverse=True):
        if upper.startswith(key.upper()):
            return key
    return None


def _canonical_n_stage_label(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    for key in sorted(TNM_N_DATA.keys(), key=len, reverse=True):
        if upper == key.upper():
            return key
    for key in sorted(TNM_N_DATA.keys(), key=len, reverse=True):
        if f"{key.upper()}M" in upper or upper.endswith(key.upper()):
            return key
    return None


def _canonical_m_stage_label(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    for key in sorted(TNM_M_DATA.keys(), key=len, reverse=True):
        if upper == key.upper():
            return key
    for key in sorted(TNM_M_DATA.keys(), key=len, reverse=True):
        if upper.endswith(key.upper()) or key.upper() in upper:
            return key
    return None


class TNMEngine:
    """Ensambla estadificación TNM completa y provee metadata visual."""

    # ── Public API ───────────────────────────────────────────────────────────

    @staticmethod
    def assemble(patient_data: dict[str, Any]) -> dict[str, Any]:
        """Ensambla TNM completo desde datos del paciente.

        Campos leídos (en orden de prioridad):
        - ``clinical_tstage``, ``tnm_stage`` (para T)
        - ``dre_finding`` (nuevo) / ``dre_suspicious`` (legacy)
        - ``nodal_status`` (para N)
        - ``metastasis_site`` (para M)

        Returns dict con:
            t_stage, n_stage, m_stage, tnm_composite,
            t_data, n_data, m_data, severity_classes, has_data
        """
        t_stage = TNMEngine._resolve_t_stage(patient_data)
        n_stage = TNMEngine._resolve_n_stage(patient_data)
        m_stage = TNMEngine._resolve_m_stage(patient_data)

        has_data = bool(t_stage or n_stage or m_stage)

        t_data = TNM_T_DATA.get(t_stage, {}) if t_stage else {}
        n_data = TNM_N_DATA.get(n_stage, TNM_N_DATA.get("N0", {})) if n_stage else TNM_N_DATA.get("N0", {})
        m_data = TNM_M_DATA.get(m_stage, TNM_M_DATA.get("M0", {})) if m_stage else TNM_M_DATA.get("M0", {})
        metastatic_profile = build_metastatic_profile(patient_data)
        if str(m_stage or "").startswith("M1") and str(metastatic_profile.get("m_substage_resolved") or "M0") == "M0":
            metastatic_profile = {
                **metastatic_profile,
                "m_substage_resolved": m_stage,
                "legacy_metastasis_site": "M1" if m_stage == "M1" else metastatic_profile.get("legacy_metastasis_site") or "M1",
                "legacy_metastasis_count": max(int(metastatic_profile.get("legacy_metastasis_count") or 0), 1),
                "metastatic_truth_status": metastatic_profile.get("metastatic_truth_status") or "derived",
                "metastatic_burden_summary": m_data.get("desc"),
            }
        if m_data and str(m_data.get("label") or "").startswith("M1"):
            visual = render_m_stage_visual(metastatic_profile)
            m_data = {
                **m_data,
                "image_src": visual.get("image_src"),
                "visual_mode": visual.get("visual_mode"),
                "summary": visual.get("summary"),
                "desc": visual.get("summary") or summarize_metastatic_profile(metastatic_profile) or m_data.get("desc"),
                "metastatic_profile": metastatic_profile,
            }

        # Composite label
        t_label = t_data.get("label", t_stage or "Tx")
        n_label = n_data.get("label", n_stage or "Nx")
        m_label = m_data.get("label", m_stage or "Mx")
        tnm_composite = f"{t_label}{n_label}{m_label}"

        # Overall severity (worst of T, N, M)
        severity_order = {"low": 0, "intermediate": 1, "high": 2, "very_high": 3}
        overall_severity = max(
            t_data.get("severity", "low"),
            n_data.get("severity", "low"),
            m_data.get("severity", "low"),
            key=lambda s: severity_order.get(s, 0),
        )

        return {
            "has_data": has_data,
            "t_stage": t_stage,
            "n_stage": n_stage or "N0",
            "m_stage": m_stage or "M0",
            "tnm_composite": tnm_composite,
            "t_data": t_data,
            "n_data": n_data,
            "m_data": m_data,
            "metastatic_profile": metastatic_profile,
            "overall_severity": overall_severity,
            "severity_classes": SEVERITY_CLASSES.get(overall_severity, SEVERITY_CLASSES["low"]),
        }

    @staticmethod
    def dre_to_tstage(dre_value: str | None) -> str | None:
        """Backward compatibility: mapea DRE legacy a T-stage.

        - ``"0"`` / ``"Normal"`` → None
        - ``"1"`` (sospechoso legacy) → ``"T2a"`` (estimación conservadora)
        - ``"T2a - Afecta ..."`` → ``"T2a"``
        - ``"T3a"`` etc. → pass-through
        """
        if not dre_value or str(dre_value).strip() in ("", "0", "Normal"):
            return None
        if str(dre_value).strip() == "1":
            return "T2a"  # Legacy sospechoso → estimación conservadora
        # Intentar mapeo por nombre descriptivo
        mapped = _DRE_FINDING_TO_TSTAGE.get(str(dre_value).strip())
        if mapped is not None:
            return mapped
        # Pass-through si ya es un T-stage válido
        return _canonical_t_stage_label(dre_value)

    @staticmethod
    def get_t_image_path(t_stage: str | None) -> str | None:
        """Retorna ruta relativa de imagen para el T-stage."""
        if not t_stage:
            return None
        data = TNM_T_DATA.get(t_stage, {})
        img = data.get("image")
        return f"/static/img/tnm/{img}" if img else None

    @staticmethod
    def severity_to_classes(severity: str) -> dict[str, str]:
        """Retorna clases Tailwind para un nivel de severity."""
        return SEVERITY_CLASSES.get(severity, SEVERITY_CLASSES["low"])

    # ── Private Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_t_stage(data: dict[str, Any]) -> str | None:
        """Resuelve T-stage desde múltiples fuentes de datos."""
        # 1. clinical_tstage explícito (localized_initial schema)
        tstage = data.get("clinical_tstage")
        if tstage and str(tstage).strip().upper().startswith("T"):
            return _canonical_t_stage_label(tstage)

        # 2. tnm_stage (clinical_baseline)
        tnm = data.get("tnm_stage")
        if tnm and str(tnm).strip().upper().startswith("T"):
            # Extraer T component de algo como "T2aN0M0"
            return _canonical_t_stage_label(tnm)

        # 3. dre_finding (nuevo) o dre_suspicious (legacy)
        dre = data.get("dre_finding") or data.get("dre_suspicious")
        if dre:
            return TNMEngine.dre_to_tstage(str(dre))

        return None

    @staticmethod
    def _resolve_n_stage(data: dict[str, Any]) -> str | None:
        """Resuelve N-stage."""
        nodal = data.get("nodal_status")
        if nodal:
            canonical = _canonical_n_stage_label(nodal)
            if canonical:
                return canonical
        tnm = data.get("tnm_stage")
        if tnm:
            canonical = _canonical_n_stage_label(tnm)
            if canonical:
                return canonical
        return "N0"

    @staticmethod
    def _resolve_m_stage(data: dict[str, Any]) -> str | None:
        """Resuelve M-stage."""
        metastatic_profile = build_metastatic_profile(data)
        resolved = str(metastatic_profile.get("m_substage_resolved") or "")
        if resolved in TNM_M_DATA and (
            resolved != "M0"
            or any(data.get(field) not in (None, "", [], {}) for field in ("metastasis_site", "metastatic_profile_json", "bone_sites", "visceral_sites"))
        ):
            return resolved
        meta = data.get("metastasis_site")
        if meta:
            canonical = _canonical_m_stage_label(meta)
            if canonical:
                return canonical
        tnm = data.get("tnm_stage")
        if tnm:
            canonical = _canonical_m_stage_label(tnm)
            if canonical:
                return canonical
        if not meta:
            return "M0"
        meta_str = str(meta).strip()
        if meta_str.upper().startswith("M1"):
            return meta_str.upper()[:3] if len(meta_str) >= 3 and meta_str[2:3].isalpha() else "M1"
        if meta_str.upper() == "M0":
            return "M0"
        # Si tiene un sitio de metástasis específico (Hueso, Visceral, etc.)
        if meta_str and meta_str.upper() not in ("M0", "NO", "NINGUNO", "NONE", ""):
            return "M1"
        return "M0"
