from __future__ import annotations


class ReportingService:
    def build_module_report(self, result: dict) -> dict:
        return {
            "summary": result.get("report_sections", {}).get("summary", ""),
            "structured_summary": result.get("report_sections", {}).get("structured_summary", {}),
            "nccn": result.get("nccn_primary", {}),
            "eau": result.get("eau_comparison", {}),
            "evidence": result.get("evidence_trace", []),
        }
