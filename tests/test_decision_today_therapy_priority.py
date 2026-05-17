"""BUG FIX smoke 2026-05-17 — DECISION_TODAY prioriza therapy decisions
sobre molecular refiners (biomarker_gate / psma_gate / arpi_safety).

Pre-fix: `_top_autodrive_item` retornaba el PRIMER item del queue sin filtrar
tipo. Resultado clínico: paciente mcspc_low_volume_sync_oligo mostraba
"Biomarcadores accionables" como decisión today, cuando la decisión correcta
es "Doblete ADT+ARPI" (STAMPEDE/ENZAMET v2026 NCCN PROS-7).

Post-fix: dos pasadas — primero busca primary therapy decision
(_is_primary_therapy_item), luego fallback a primer refiner si no hay therapy
visible (estados pre-diagnóstico, screening).
"""
from __future__ import annotations

import pytest

from prostanet.domains.patient_tracking.clinical_decision_today_fusion_kernel import (
    _is_primary_therapy_item,
    _top_autodrive_item,
)


class TestIsPrimaryTherapyItem:
    """Heurística de clasificación therapy vs refiner."""

    @pytest.mark.parametrize("item,expected,reason", [
        # NEGATIVE — refiners / gates
        ({"key": "biomarker_gate"}, False, "biomarker_gate is refiner"),
        ({"key": "psma_gate"}, False, "psma_gate is refiner"),
        ({"key": "arpi_safety"}, False, "arpi_safety is refiner"),
        ({"key": "docetaxel_cbc"}, False, "docetaxel_cbc is refiner"),
        ({"key": "lab_pending"}, False, "lab_pending is refiner"),
        ({"key": "hrr_capture"}, False, "hrr_capture is refiner"),
        ({"key": "imaging_followup"}, False, "imaging_followup is refiner"),
        ({"key": "safety_alert"}, False, "safety_alert is refiner"),
        ({"key": "psa_safety_gate"}, False, "_gate suffix is refiner"),
        ({"key": "molecular_biomarker"}, False, "biomarker substring is refiner"),
        # POSITIVE — primary therapy decisions
        ({"key": "arpi_doublet", "category": "therapy"},
         True, "arpi_doublet category=therapy"),
        ({"key": "triplet_docetaxel_arpi"}, True, "triplet keyword in key"),
        ({"action_key": "tumor_board:arpi_doublet"},
         True, "tumor_board: action_key prefix"),
        ({"action_key": "therapy:start_adt"}, True, "therapy: action_key prefix"),
        ({"action_key": "recommendation:salvage_rt"},
         True, "recommendation: action_key prefix"),
        ({"clinical_role": "mhspc_systemic"}, True, "mhspc_systemic clinical_role"),
        ({"clinical_role": "local_therapy_salvage"},
         True, "local_therapy clinical_role"),
        ({"lane": "recommendation_today"}, True, "recommendation_today lane"),
        ({"key": "salvage_rt_decision"}, True, "salvage_rt keyword"),
        ({"key": "active_surveillance_continue"}, True, "active_surveillance keyword"),
        ({"key": "primary_rt_decision"}, True, "primary_rt keyword"),
        ({"key": "sbrt_oligomet"}, True, "sbrt keyword (STOMP/ORIOLE)"),
        ({"key": "mdt_planning"}, True, "mdt keyword"),
    ])
    def test_classification(self, item, expected, reason):
        assert _is_primary_therapy_item(item) is expected, reason

    def test_non_mapping_returns_false(self):
        assert _is_primary_therapy_item("not a dict") is False
        assert _is_primary_therapy_item(None) is False
        assert _is_primary_therapy_item([]) is False


class TestTopAutodriveItemFix:
    """Validación end-to-end del fix de prioritización."""

    def test_mcspc_low_volume_doublet_wins_over_biomarker_gate(self):
        """CASO REPORTADO: paciente mcspc_low_volume_sync_oligo (NSS 3344557788)
        mostraba 'Biomarcadores accionables' como decisión today. Debe ser
        'Doblete ADT + ARPI' del Tumor Board."""
        autodrive = {"today_queue": [
            {"key": "biomarker_gate", "title": "Biomarcadores accionables",
             "action_key": "gate:biomarker"},
            {"key": "arpi_doublet", "title": "Doblete ADT + ARPI",
             "action_key": "tumor_board:arpi_doublet", "category": "therapy",
             "clinical_role": "mhspc_systemic"},
        ]}
        top = _top_autodrive_item(autodrive)
        assert top.get("key") == "arpi_doublet"
        assert top.get("title") == "Doblete ADT + ARPI"

    def test_pre_diagnostic_falls_back_to_first_refiner(self):
        """Estados pre-diagnóstico (no therapy decisions yet) deben caer
        al primer refiner del queue."""
        autodrive = {"today_queue": [
            {"key": "biopsy_pending", "title": "Biopsia pendiente",
             "action_key": "pathway:biopsy"},
            {"key": "biomarker_gate", "title": "Biomarcadores accionables"},
        ]}
        top = _top_autodrive_item(autodrive)
        # No primary therapy → Pass 2 retorna primer item no-kernel
        assert top.get("key") in ("biopsy_pending", "biomarker_gate")

    def test_post_rp_bcr_salvage_rt_wins_over_arpi_safety(self):
        """post_rp_bcr: salvage RT (therapy) gana sobre arpi_safety (refiner)."""
        autodrive = {"today_queue": [
            {"key": "arpi_safety", "title": "Seguridad ARPI"},
            {"key": "salvage_rt_decision", "title": "Salvage RT a fossa",
             "action_key": "tumor_board:salvage_rt", "category": "therapy",
             "clinical_role": "local_therapy_salvage"},
        ]}
        top = _top_autodrive_item(autodrive)
        assert top.get("key") == "salvage_rt_decision"

    def test_kernel_self_reference_skipped(self):
        """El propio decision_today no debe seleccionarse a sí mismo."""
        autodrive = {"today_queue": [
            {"key": "kernel_self", "action_key": "decision_today:fusion_kernel"},
            {"key": "arpi_doublet", "title": "Doblete ADT+ARPI",
             "category": "therapy"},
        ]}
        top = _top_autodrive_item(autodrive)
        assert top.get("key") == "arpi_doublet"

    def test_empty_queue_returns_empty_dict(self):
        assert _top_autodrive_item({"today_queue": []}) == {}
        assert _top_autodrive_item({}) == {}

    def test_falls_back_from_autodrive_actions_alias(self):
        """`autodrive_actions` es alias legacy de `today_queue`."""
        autodrive = {"autodrive_actions": [
            {"key": "arpi_doublet", "title": "Doblete", "category": "therapy"},
        ]}
        top = _top_autodrive_item(autodrive)
        assert top.get("key") == "arpi_doublet"

    def test_mcrpc_psma_lu177_wins_over_safety_gates(self):
        """mcrpc_psma_eligible_lu177: VISION/PSMAfore decision gana sobre safety
        refiners cuando coexisten."""
        autodrive = {"today_queue": [
            {"key": "arpi_safety", "title": "Seguridad ARPI"},
            {"key": "biomarker_gate", "title": "Biomarcadores accionables"},
            {"key": "lu177_psma_decision", "title": "Iniciar Lu-177 PSMA-617",
             "action_key": "tumor_board:lu177_psma",
             "clinical_role": "mcrpc_systemic"},
        ]}
        top = _top_autodrive_item(autodrive)
        assert top.get("key") == "lu177_psma_decision"

    def test_first_therapy_item_wins_over_later_therapy(self):
        """Si hay múltiples therapy items, gana el PRIMERO (queue order
        preservado para therapy items entre sí)."""
        autodrive = {"today_queue": [
            {"key": "psma_gate"},
            {"key": "arpi_doublet", "title": "Doblete ADT+ARPI", "category": "therapy"},
            {"key": "triplet_docetaxel_arpi", "title": "Triplete",
             "category": "therapy"},
        ]}
        top = _top_autodrive_item(autodrive)
        # Primero entre therapy items
        assert top.get("key") == "arpi_doublet"
