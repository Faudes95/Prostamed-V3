# -*- coding: utf-8 -*-
"""
Módulo de biopsia estructurada con mapa por sextante y concordancia MRI.

Captura detallada de cilindros por ubicación anatómica, tipo de biopsia
(sistemática/dirigida/fusión), concordancia con lesión MRI y detección
de upgrade histológico entre biopsias secuenciales.

Referencia:
  NCCN 2026 Early Detection 3.2026
  EAU 2026 Prostate Cancer Diagnosis
  PI-RADS v2.1 (ACR/ESUR)
  PRECISE Recommendations for MRI in Active Surveillance
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from prostanet.shared.gleason_profile import derive_gleason_score, derive_isup_grade

logger = logging.getLogger(__name__)

# ── Constantes anatómicas ────────────────────────────────────────────────────

SEXTANT_LOCATIONS = (
    "right_base", "right_mid", "right_apex",
    "left_base", "left_mid", "left_apex",
)

BIOPSY_TYPES = ("systematic", "mri_targeted", "fusion", "saturation")
BIOPSY_ROUTES = ("transperineal", "transrectal")
BIOPSY_CONTEXTS = ("diagnostic", "confirmatory_as", "followup_as", "rebiopsy")
COMPLICATIONS = ("none", "infection", "bleeding", "retention", "pain", "other")


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class BiopsyCore:
    """Representa un cilindro individual de biopsia prostática."""
    core_id: str
    location_sextant: str  # una de SEXTANT_LOCATIONS o "targeted_N"
    core_type: str  # "systematic" | "targeted"
    core_length_mm: float | None = None
    tumor_length_mm: float | None = None
    involvement_pct: float | None = None
    gleason_primary: int | None = None
    gleason_secondary: int | None = None
    isup_grade: int | None = None
    positive: bool = False
    mri_target_concordance: bool | None = None  # solo para targeted cores
    cribriform_pattern: bool = False
    intraductal_carcinoma: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StructuredBiopsyResult:
    """Resultado completo de una sesión de biopsia prostática estructurada."""
    biopsy_date: str = ""
    biopsy_type: str = ""  # una de BIOPSY_TYPES
    biopsy_route: str = ""  # una de BIOPSY_ROUTES
    biopsy_context: str = ""  # una de BIOPSY_CONTEXTS
    mri_pirads_at_biopsy: int | None = None
    systematic_cores: list[BiopsyCore] = field(default_factory=list)
    targeted_cores: list[BiopsyCore] = field(default_factory=list)
    complications: list[str] = field(default_factory=list)
    # ── Agregados computados ──
    highest_gleason_sum: int | None = None
    highest_isup: int | None = None
    total_positive: int = 0
    total_cores: int = 0
    max_involvement_pct: float | None = None
    percent_positive_cores: float | None = None
    targeted_positive_count: int = 0
    targeted_total_count: int = 0
    targeted_concordance_rate: float | None = None
    any_cribriform: bool = False
    any_intraductal: bool = False
    sextant_map: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "biopsy_date": self.biopsy_date,
            "biopsy_type": self.biopsy_type,
            "biopsy_route": self.biopsy_route,
            "biopsy_context": self.biopsy_context,
            "mri_pirads_at_biopsy": self.mri_pirads_at_biopsy,
            "systematic_cores": [c.to_dict() for c in self.systematic_cores],
            "targeted_cores": [c.to_dict() for c in self.targeted_cores],
            "complications": list(self.complications),
            "highest_gleason_sum": self.highest_gleason_sum,
            "highest_isup": self.highest_isup,
            "total_positive": self.total_positive,
            "total_cores": self.total_cores,
            "max_involvement_pct": self.max_involvement_pct,
            "percent_positive_cores": self.percent_positive_cores,
            "targeted_positive_count": self.targeted_positive_count,
            "targeted_total_count": self.targeted_total_count,
            "targeted_concordance_rate": self.targeted_concordance_rate,
            "any_cribriform": self.any_cribriform,
            "any_intraductal": self.any_intraductal,
            "sextant_map": dict(self.sextant_map),
        }


# ── Funciones auxiliares ─────────────────────────────────────────────────────

def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Servicio principal ───────────────────────────────────────────────────────

class StructuredBiopsyService:
    """Servicio de biopsia estructurada con mapeo por sextante e integración clínica."""

    @staticmethod
    def parse_core(data: dict[str, Any], index: int, core_type: str) -> BiopsyCore:
        """Parsea un diccionario de datos en un BiopsyCore."""
        prefix = f"{'S' if core_type == 'systematic' else 'T'}{index + 1}"
        location = data.get("location_sextant", data.get("location", ""))
        gleason_p = _safe_int(data.get("gleason_primary"))
        gleason_s = _safe_int(data.get("gleason_secondary"))
        isup = _safe_int(data.get("isup_grade")) or derive_isup_grade(gleason_p, gleason_s)
        positive = data.get("positive", False)
        if isinstance(positive, str):
            positive = positive.lower() in ("true", "1", "si", "sí", "yes", "positivo")

        return BiopsyCore(
            core_id=data.get("core_id", prefix),
            location_sextant=location,
            core_type=core_type,
            core_length_mm=_safe_float(data.get("core_length_mm")),
            tumor_length_mm=_safe_float(data.get("tumor_length_mm")),
            involvement_pct=_safe_float(data.get("involvement_pct")),
            gleason_primary=gleason_p,
            gleason_secondary=gleason_s,
            isup_grade=isup,
            positive=positive,
            mri_target_concordance=data.get("mri_target_concordance") if core_type == "targeted" else None,
            cribriform_pattern=bool(data.get("cribriform_pattern", False)),
            intraductal_carcinoma=bool(data.get("intraductal_carcinoma", False)),
        )

    @staticmethod
    def parse_structured_biopsy(data: dict[str, Any]) -> StructuredBiopsyResult:
        """Parsea los datos crudos de biopsia en una StructuredBiopsyResult con agregados."""
        systematic = [
            StructuredBiopsyService.parse_core(core, i, "systematic")
            for i, core in enumerate(data.get("systematic_cores", []))
        ]
        targeted = [
            StructuredBiopsyService.parse_core(core, i, "targeted")
            for i, core in enumerate(data.get("targeted_cores", []))
        ]

        result = StructuredBiopsyResult(
            biopsy_date=data.get("biopsy_date", ""),
            biopsy_type=data.get("biopsy_type", ""),
            biopsy_route=data.get("biopsy_route", ""),
            biopsy_context=data.get("biopsy_context", "diagnostic"),
            mri_pirads_at_biopsy=_safe_int(data.get("mri_pirads_at_biopsy")),
            systematic_cores=systematic,
            targeted_cores=targeted,
            complications=data.get("complications", []),
        )
        StructuredBiopsyService._compute_aggregates(result)
        return result

    @staticmethod
    def _compute_aggregates(result: StructuredBiopsyResult) -> None:
        """Computa agregados sobre los cilindros."""
        all_cores = result.systematic_cores + result.targeted_cores
        result.total_cores = len(all_cores)
        result.total_positive = sum(1 for c in all_cores if c.positive)
        result.percent_positive_cores = (
            round((result.total_positive / result.total_cores) * 100, 1)
            if result.total_cores > 0 else None
        )

        # Gleason / ISUP más alto
        gleason_sums = [
            derive_gleason_score(c.gleason_primary, c.gleason_secondary)
            for c in all_cores if c.positive
        ]
        result.highest_gleason_sum = max((g for g in gleason_sums if g is not None), default=None)
        isups = [c.isup_grade for c in all_cores if c.positive and c.isup_grade is not None]
        result.highest_isup = max(isups, default=None)

        # Máximo involvement
        involvements = [c.involvement_pct for c in all_cores if c.involvement_pct is not None]
        result.max_involvement_pct = max(involvements, default=None)

        # Targeted cores
        result.targeted_total_count = len(result.targeted_cores)
        result.targeted_positive_count = sum(1 for c in result.targeted_cores if c.positive)
        concordant = [c for c in result.targeted_cores if c.mri_target_concordance is not None]
        if concordant:
            result.targeted_concordance_rate = round(
                sum(1 for c in concordant if c.mri_target_concordance) / len(concordant) * 100, 1
            )

        # Patrones adversos
        result.any_cribriform = any(c.cribriform_pattern for c in all_cores if c.positive)
        result.any_intraductal = any(c.intraductal_carcinoma for c in all_cores if c.positive)

        # Mapa por sextante
        result.sextant_map = StructuredBiopsyService.compute_sextant_map(all_cores)

    @staticmethod
    def compute_sextant_map(cores: list[BiopsyCore]) -> dict[str, dict[str, Any]]:
        """Construye resumen por sextante anatómico."""
        smap: dict[str, dict[str, Any]] = {}
        for sextant in SEXTANT_LOCATIONS:
            sextant_cores = [c for c in cores if c.location_sextant == sextant]
            if not sextant_cores:
                smap[sextant] = {"total": 0, "positive": 0, "max_gleason": None, "max_involvement": None}
                continue
            positive = [c for c in sextant_cores if c.positive]
            gleason_sums = [
                _gleason_sum(c.gleason_primary, c.gleason_secondary)
                for c in positive
            ]
            involvements = [c.involvement_pct for c in positive if c.involvement_pct is not None]
            smap[sextant] = {
                "total": len(sextant_cores),
                "positive": len(positive),
                "max_gleason": max((g for g in gleason_sums if g is not None), default=None),
                "max_involvement": max(involvements, default=None),
            }
        return smap

    @staticmethod
    def evaluate_upgrade_from_previous(
        current: StructuredBiopsyResult,
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Evalúa upgrade histológico comparando con biopsia previa."""
        if not previous:
            return {"upgrade": False, "from_isup": None, "to_isup": current.highest_isup, "volume_increase": False, "detail": "Sin biopsia previa para comparar"}

        prev_isup = _safe_int(previous.get("highest_isup") or previous.get("isup_grade"))
        curr_isup = current.highest_isup
        upgrade = False
        if prev_isup is not None and curr_isup is not None:
            upgrade = curr_isup > prev_isup

        prev_positive_pct = _safe_float(previous.get("percent_positive_cores"))
        curr_positive_pct = current.percent_positive_cores
        volume_increase = False
        if prev_positive_pct is not None and curr_positive_pct is not None:
            volume_increase = curr_positive_pct > prev_positive_pct + 10  # >10% aumento

        detail_parts = []
        if upgrade:
            detail_parts.append(f"Upgrade de ISUP {prev_isup} a ISUP {curr_isup}")
        if volume_increase:
            detail_parts.append(f"Aumento de volumen: {prev_positive_pct:.0f}% → {curr_positive_pct:.0f}% cores positivos")

        return {
            "upgrade": upgrade,
            "from_isup": prev_isup,
            "to_isup": curr_isup,
            "volume_increase": volume_increase,
            "detail": "; ".join(detail_parts) if detail_parts else "Sin cambios significativos",
        }

    @staticmethod
    def check_mri_concordance(result: StructuredBiopsyResult) -> dict[str, Any]:
        """Evalúa concordancia entre lesión MRI y biopsia dirigida."""
        if not result.targeted_cores:
            return {"concordant": None, "concordance_rate": None, "missed_lesions": 0, "detail": "Sin biopsias dirigidas"}

        concordant_cores = [c for c in result.targeted_cores if c.mri_target_concordance is not None]
        if not concordant_cores:
            return {"concordant": None, "concordance_rate": None, "missed_lesions": 0, "detail": "Concordancia no documentada"}

        hits = sum(1 for c in concordant_cores if c.mri_target_concordance)
        rate = round(hits / len(concordant_cores) * 100, 1)
        missed = len(concordant_cores) - hits

        concordant = rate >= 50  # ≥50% de cores dirigidos confirman lesión MRI
        pirads = result.mri_pirads_at_biopsy
        detail = f"Concordancia MRI-biopsia: {rate:.0f}% ({hits}/{len(concordant_cores)} cores)"
        if pirads and pirads >= 4 and missed > 0:
            detail += f". PI-RADS {pirads} con {missed} cores dirigidos sin confirmación — considerar rebiopsia"

        return {
            "concordant": concordant,
            "concordance_rate": rate,
            "missed_lesions": missed,
            "pirads_at_biopsy": pirads,
            "detail": detail,
        }

    @staticmethod
    def evaluate_biopsy_alerts(
        patient_id: int,
        result: StructuredBiopsyResult,
        previous_biopsy: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Genera alertas clínicas basadas en los hallazgos de biopsia."""
        # Importar ClinicalAlert de forma lazy para evitar circular imports
        from prostanet.domains.patient_tracking.alert_engine import ClinicalAlert

        alerts: list[ClinicalAlert] = []

        # 1. Upgrade Gleason vs biopsia previa
        upgrade_eval = StructuredBiopsyService.evaluate_upgrade_from_previous(result, previous_biopsy)
        if upgrade_eval["upgrade"]:
            severity = "critical" if (upgrade_eval["to_isup"] or 0) >= 4 else "warning"
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_gleason_upgrade",
                severity=severity,
                category="pathology",
                title=f"Upgrade histológico: ISUP {upgrade_eval['from_isup']} → {upgrade_eval['to_isup']}",
                message=upgrade_eval["detail"],
                recommended_action="Reevaluar elegibilidad de vigilancia activa. Considerar tratamiento definitivo si ISUP ≥3.",
                guideline_reference="NCCN 2026 AS reclassification; EAU 2026 AS",
                triggering_value=f"ISUP {upgrade_eval['to_isup']}",
                threshold=f"Previo ISUP {upgrade_eval['from_isup']}",
            ))

        # 2. Enfermedad de alto volumen
        if result.percent_positive_cores and result.percent_positive_cores > 50:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_high_volume",
                severity="warning",
                category="pathology",
                title=f"Alto volumen tumoral: {result.percent_positive_cores:.0f}% cores positivos",
                message=f"{result.total_positive}/{result.total_cores} cores positivos. Considerar tratamiento definitivo.",
                recommended_action="Evaluar prostatectomía radical o radioterapia definitiva. Discutir en tumor board si aplica.",
                guideline_reference="NCCN 2026; EAU 2026 high-volume localized",
                triggering_value=f"{result.percent_positive_cores:.0f}%",
                threshold=">50% cores positivos",
            ))
        if result.max_involvement_pct and result.max_involvement_pct > 70:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_high_core_involvement",
                severity="warning",
                category="pathology",
                title=f"Involucramiento máximo por cilindro: {result.max_involvement_pct:.0f}%",
                message="Cilindro con >70% de involucramiento tumoral sugiere enfermedad significativa.",
                recommended_action="Factor adverso para vigilancia activa. Considerar tratamiento definitivo.",
                guideline_reference="NCCN 2026 AS; EAU 2026 AS criteria",
                triggering_value=f"{result.max_involvement_pct:.0f}%",
                threshold=">70%",
            ))

        # 3. Discordancia MRI-target
        mri_conc = StructuredBiopsyService.check_mri_concordance(result)
        if (mri_conc["concordant"] is False
                and result.mri_pirads_at_biopsy
                and result.mri_pirads_at_biopsy >= 4):
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_mri_discordance",
                severity="warning",
                category="imaging_pathology_correlation",
                title=f"Discordancia MRI-biopsia (PI-RADS {result.mri_pirads_at_biopsy})",
                message=mri_conc["detail"],
                recommended_action="Considerar rebiopsia dirigida con técnica alternativa o seguimiento cercano con MRI a 6 meses.",
                guideline_reference="PI-RADS v2.1; EAU 2026 repeat biopsy",
                triggering_value=f"Concordancia {mri_conc['concordance_rate']:.0f}%",
                threshold="PI-RADS ≥4 con biopsia negativa",
            ))

        # 4. Patrones adversos (cribriforme, intraductal)
        if result.any_cribriform or result.any_intraductal:
            patterns = []
            if result.any_cribriform:
                patterns.append("patrón cribriforme")
            if result.any_intraductal:
                patterns.append("carcinoma intraductal")
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_adverse_pattern",
                severity="warning",
                category="pathology",
                title=f"Histología adversa detectada: {', '.join(patterns)}",
                message="Estos patrones se asocian con biología más agresiva y excluyen protocolos conservadores de vigilancia activa.",
                recommended_action="Excluir de VA conservadora (PRIAS/Epstein). Considerar tratamiento definitivo o VA intensificada.",
                guideline_reference="NCCN 2026 adverse histology; Kweldam 2016 cribriform; EAU 2026 IDC",
                triggering_value=", ".join(patterns),
                threshold="Cualquier patrón adverso",
            ))

        # 5. Complicación documentada (info para métricas institucionales)
        significant_complications = [c for c in result.complications if c not in ("none", "")]
        if significant_complications:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="biopsy_complication",
                severity="info",
                category="safety",
                title=f"Complicación de biopsia: {', '.join(significant_complications)}",
                message=f"Vía: {result.biopsy_route}. Tipo: {result.biopsy_type}.",
                recommended_action="Documentar para métricas institucionales de calidad.",
                guideline_reference="EAU 2026 biopsy complications",
                triggering_value=", ".join(significant_complications),
                threshold="Cualquier complicación",
            ))

        return [a.to_dict() for a in alerts]

    @staticmethod
    def build_biopsy_summary_for_profile(result: StructuredBiopsyResult) -> dict[str, Any]:
        """Construye resumen de biopsia para mostrar en el perfil del paciente."""
        sextant_visual = {}
        for sextant, data in result.sextant_map.items():
            if data["total"] == 0:
                sextant_visual[sextant] = {"status": "no_sample", "tone": "muted"}
            elif data["positive"] == 0:
                sextant_visual[sextant] = {"status": "negative", "tone": "success"}
            else:
                max_g = data.get("max_gleason")
                tone = "danger" if (max_g and max_g >= 8) else "warning" if (max_g and max_g >= 7) else "info"
                sextant_visual[sextant] = {
                    "status": "positive",
                    "tone": tone,
                    "cores": f"{data['positive']}/{data['total']}",
                    "max_gleason": max_g,
                    "max_involvement": data.get("max_involvement"),
                }

        return {
            "biopsy_date": result.biopsy_date,
            "biopsy_type": result.biopsy_type,
            "biopsy_route": result.biopsy_route,
            "biopsy_context": result.biopsy_context,
            "total_cores": result.total_cores,
            "total_positive": result.total_positive,
            "percent_positive": result.percent_positive_cores,
            "highest_gleason": result.highest_gleason_sum,
            "highest_isup": result.highest_isup,
            "max_involvement_pct": result.max_involvement_pct,
            "any_cribriform": result.any_cribriform,
            "any_intraductal": result.any_intraductal,
            "targeted_concordance_rate": result.targeted_concordance_rate,
            "sextant_map": sextant_visual,
            "complications": result.complications,
        }
