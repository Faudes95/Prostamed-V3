from __future__ import annotations


class GuidelineComparisonService:
    def compare(self, nccn: dict, eau: dict) -> dict:
        nccn_label = nccn.get("label") or nccn.get("risk_group") or nccn.get("scenario")
        eau_label = eau.get("label") or eau.get("risk_group") or eau.get("scenario")
        nccn_key = self._canonical_label(nccn.get("risk_group") or nccn_label)
        eau_key = self._canonical_label(eau.get("risk_group") or eau_label)
        if not nccn_label or not eau_label:
            status = "incomplete"
            summary = "Comparacion incompleta por datos insuficientes."
        elif nccn_key == eau_key:
            status = "coincide"
            summary = "NCCN 2026 y EAU 2026 coinciden en la categoria principal."
        else:
            status = "diferencia_de_guias"
            summary = f"NCCN 2026 prioriza '{nccn_label}' mientras EAU 2026 reporta '{eau_label}'."
        return {
            "status": status,
            "summary": summary,
            "nccn_label": nccn_label,
            "eau_label": eau_label,
        }

    @staticmethod
    def _canonical_label(label: str | None) -> str:
        normalized = str(label or "").strip().upper()
        aliases = {
            "FAVORABLE INTERMEDIATE": "INTERMEDIATE_FAVORABLE",
            "INTERMEDIATE (FAVORABLE)": "INTERMEDIATE_FAVORABLE",
            "UNFAVORABLE INTERMEDIATE": "INTERMEDIATE_UNFAVORABLE",
            "INTERMEDIATE (UNFAVORABLE)": "INTERMEDIATE_UNFAVORABLE",
            "LOW": "LOW",
            "HIGH": "HIGH",
            "VERY HIGH": "VERY_HIGH",
            "REGIONAL N1M0": "REGIONAL_N1M0",
            "M0 CRPC": "M0_CRPC",
            "M1 CRPC": "M1_CRPC",
            "MCSPC HIGH-VOLUME": "MCSPC_HIGH_VOLUME",
            "MCSPC LOW-VOLUME / SYNCHRONOUS OLIGOMETASTATIC": "MCSPC_LOW_VOLUME",
            "MCSPC OLIGOMETASTATIC METACHRONOUS": "MCSPC_OLIGO_METACHRONOUS",
        }
        return aliases.get(normalized, normalized)
