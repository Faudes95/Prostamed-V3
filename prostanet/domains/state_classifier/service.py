from __future__ import annotations

from datetime import datetime

from prostanet.domains.post_radiotherapy_or_local_salvage.logic import (
    build_post_rt_failure_definition,
)
from prostanet.shared.metastatic_profile import (
    derive_legacy_metastasis,
    derive_mhspc_burden_context,
    resolve_metastatic_state_context,
)
from prostanet.shared.staging_requirements_engine import (
    staging_complete,
    staging_required,
)
from prostanet.shared.systemic_progression import (
    build_progression_gate,
    normalize_castrate_status,
    resolve_systemic_progression_context,
)


MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}


class StateClassifierService:
    def classify(self, payload: dict) -> dict:
        burden_context = derive_mhspc_burden_context(payload)
        known_cancer_diagnosis = self._is_true(payload.get("known_cancer_diagnosis", 1))
        prior_negative_biopsy = self._is_true(payload.get("prior_negative_biopsy"))
        metastasis_site, metastasis_count, m_substage = derive_legacy_metastasis(payload)
        metastatic_state_context = resolve_metastatic_state_context(payload)
        systemic_progression_context = str(payload.get("systemic_progression_context", "") or "")
        current_adt_context = str(payload.get("current_adt_context", "none") or "none")
        castrate_status = self._normalize_castrate_status(payload)
        progression_pattern = str(payload.get("progression_pattern", "biochemical_only") or "biochemical_only")
        conventional_imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()
        legacy_crpc_signal = self._is_true(payload.get("castration_resistant"))
        if not known_cancer_diagnosis:
            metastasis_site = "M0"
            metastasis_count = 0
            prior_prostatectomy = False
            prior_radiation = False
            bcr2 = False
            metachronous = False
            volume_disease = "low"
            burden_context = {
                **burden_context,
                "volume_disease": "low",
                "volume_reason": "",
                "oligometastatic_operational": False,
            }
            systemic_progression_context = "none"
            current_adt_context = "none"
            castrate_status = "unknown"
            progression_pattern = "biochemical_only"
            conventional_imaging_status = "NOT_RESTAGED"
            legacy_crpc_signal = False
        else:
            prior_prostatectomy = self._is_true(payload.get("prior_prostatectomy"))
            prior_radiation = self._is_true(payload.get("prior_radiation"))
            bcr_detected = self._is_true(payload.get("bcr_detected"))
            bcr2 = self._is_true(payload.get("bcr2"))
            metachronous = self._is_true(payload.get("metachronous_metastasis"))
            volume_disease = str(burden_context.get("volume_disease") or "low").lower()
        metachronous_known = self._is_metachronous_known(payload) if known_cancer_diagnosis else False
        if not known_cancer_diagnosis:
            bcr_detected = False
        systemic_progression_context_resolved = resolve_systemic_progression_context(
            systemic_progression_context,
            legacy_crpc_signal=legacy_crpc_signal,
            line_of_therapy=payload.get("line_of_therapy"),
        )
        castration_resistant = systemic_progression_context_resolved == "confirmed_crpc"
        legacy_crpc_shortcut = self._use_legacy_crpc_shortcut(
            payload,
            legacy_crpc_signal=legacy_crpc_signal,
        )
        on_adt = current_adt_context != "none"

        metastatic = (
            bool(metastatic_state_context.get("metastatic_known"))
            or burden_context.get("metastasis_count", 0) not in (None, 0)
            or str(burden_context.get("m_substage_resolved") or m_substage).upper() not in {"", "M0"}
            or metastasis_site.upper() not in {"M0", "", "NONE", "NO"}
        )
        phenotype_state = self._resolve_phenotype_state(
            known_cancer_diagnosis=known_cancer_diagnosis,
            prior_negative_biopsy=prior_negative_biopsy,
            prior_prostatectomy=prior_prostatectomy,
            prior_radiation=prior_radiation,
            bcr_detected=bcr_detected,
            bcr2=bcr2,
            castration_resistant=castration_resistant,
            castrate_status=castrate_status,
            conventional_imaging_status=conventional_imaging_status,
            metastatic=metastatic,
            metachronous=metachronous,
            metachronous_known=metachronous_known,
            burden_context=burden_context,
            metastasis_count=metastasis_count,
            legacy_crpc_shortcut=legacy_crpc_shortcut,
            payload=payload,
        )
        psma_only_upstaging = metastatic_state_context.get("metastatic_detection_basis") == "psma_only"
        restaging_update_required = bool(
            metastatic_state_context.get("restaging_update_required") or psma_only_upstaging
        )
        progression_gate = build_progression_gate(
            systemic_progression_context=systemic_progression_context_resolved,
            on_adt=on_adt,
            castrate_status=castrate_status,
            progression_pattern=progression_pattern,
            prior_prostatectomy=prior_prostatectomy,
            prior_radiation=prior_radiation,
            phenotype_state=phenotype_state if phenotype_state in MHSPC_STATES else "",
        )

        if not known_cancer_diagnosis:
            module = phenotype_state
        elif progression_gate.get("progression_gate_active") and phenotype_state in MHSPC_STATES:
            module = phenotype_state
        elif progression_gate.get("progression_gate_active") and not legacy_crpc_shortcut:
            module = "adt_progression_verification"
        else:
            module = phenotype_state

        # Brecha M-staging gate — 2026-04-22:
        # Expone flags `staging_required_flag` y `staging_completed_flag` para
        # consumo de los servicios downstream (localized_initial, diagnostic_workup,
        # m0_crpc, recurrence_bcr) que aplican Gate A. NO modifica el routing del
        # phenotype porque la decisión clínica (bloquear emisión curativa) ocurre
        # dentro de cada servicio con `staging_gap_descriptor()`. Aquí sólo
        # publicamos la señal para auditoría / UI.
        staging_req_info = staging_required(payload) if known_cancer_diagnosis else {
            "required": False, "tier": "not_required", "risk_band": "n/a", "reasons": [],
        }
        staging_comp_info = staging_complete(payload) if known_cancer_diagnosis else {
            "complete": False, "modalities_done": [], "missing": [],
        }
        staging_gap_active = bool(
            staging_req_info.get("required")
            and not (staging_comp_info.get("complete") and self._is_true(payload.get("imaging_negative_metastases")))
            and not metastatic
        )

        return {
            "state": module,
            "classification_reason": self._reason_for(
                module,
                burden_context=burden_context,
                metachronous=metachronous,
                progression_gate=progression_gate,
                phenotype_state=phenotype_state,
                payload=payload,
            ),
            "derived_metastatic_context": {
                **burden_context,
                "metastatic_stage_resolved": metastatic_state_context.get("metastatic_stage_resolved"),
                "metastatic_detection_basis": metastatic_state_context.get("metastatic_detection_basis"),
                "restaging_update_required": restaging_update_required,
                "restaging_update_reason": metastatic_state_context.get("restaging_update_reason"),
            },
            "phenotype_state": phenotype_state,
            "metastatic_detection_basis": metastatic_state_context.get("metastatic_detection_basis"),
            "psma_only_upstaging": psma_only_upstaging,
            "restaging_update_required": restaging_update_required,
            "staging_required_flag": bool(staging_req_info.get("required")),
            "staging_completed_flag": bool(staging_comp_info.get("complete")),
            "staging_gap_active": staging_gap_active,
            "staging_risk_band": staging_req_info.get("risk_band"),
            "staging_reasons": staging_req_info.get("reasons") or [],
            "staging_modalities_done": staging_comp_info.get("modalities_done") or [],
            "staging_missing_modalities": staging_comp_info.get("missing") or [],
            **progression_gate,
        }

    @staticmethod
    def _is_true(value) -> bool:
        return str(value).lower() in {"1", "true", "yes", "si", "on"}

    @staticmethod
    def _is_metachronous_known(payload: dict) -> bool:
        # Guard SC-1 (FAUBOT FASE 6): distinguir "sincrónica" explícita de
        # "metacronía indeterminada" para permitir la etiqueta genérica
        # `mcspc_high_volume` cuando el dato no está capturado.
        # NOTA CRÍTICA: usar `payload.get(key)` directamente (no `... or ""`)
        # porque el int `0` es falsy en Python y `0 or ""` colapsa a `""`,
        # enmascarando una respuesta explícita "no metacrónico / sincrónico".
        candidate_fields = (
            "metachronous_metastasis",
            "metastatic_timing",
            "disease_onset_pattern",
            "de_novo_metastatic",
            "synchronous_metastasis",
        )
        known_tokens = {
            "1", "0", "true", "false", "yes", "no", "si", "on", "off",
            "sync", "synchronous", "metachronous",
            "sincronica", "sincrónica", "metacronica", "metacrónica",
            "de_novo", "de-novo", "denovo",
        }
        for key in candidate_fields:
            raw = payload.get(key)
            if raw is None:
                continue
            value = str(raw).strip().lower()
            if value in known_tokens:
                return True
        return False

    @staticmethod
    def _is_screening_context(payload: dict) -> bool:
        """EPIC 8 — detecta contexto de screening pre-diagnóstico.

        Ruta ``screening`` aplica sólo cuando el paciente no tiene diagnóstico
        conocido y existe una señal explícita de detección temprana:

        1. ``screening_context`` truthy (flag directo del formulario de
           screening poblacional).
        2. ``encounter_type == "screening"``.
        3. ``psa_baseline_ng_ml`` capturado (indica registro formal de PSA
           basal de referencia, típico de early detection NCCN v2.2026).

        Si hay sospecha activa (PSA ≥ 4, DRE sospechoso, lesión PI-RADS ≥ 3)
        el flujo debe seguir por ``diagnostic_workup`` para forzar biopsia,
        aun con ``screening_context=1``. Este helper no entra en esa lógica
        porque la rama previa ya deriva a workup si hay biopsia ordenada —
        aquí nos enfocamos sólo en detectar el encuentro preventivo.
        """
        if StateClassifierService._is_true(payload.get("screening_context")):
            return True
        encounter = str(payload.get("encounter_type") or "").strip().lower()
        if encounter == "screening":
            return True
        psa_baseline = StateClassifierService._safe_float(payload.get("psa_baseline_ng_ml"))
        if psa_baseline is not None:
            # Un PSA basal registrado sin workup activo se interpreta como
            # encuentro de screening.
            workup_requested = StateClassifierService._is_true(
                payload.get("diagnostic_workup_requested")
            ) or StateClassifierService._is_true(payload.get("biopsy_scheduled"))
            if not workup_requested:
                return True
        return False

    @staticmethod
    def _has_recurrence_signal(payload: dict) -> bool:
        return StateClassifierService._has_confirmed_post_rp_bcr(payload)

    @staticmethod
    def _has_post_rt_recurrence_signal(payload: dict) -> bool:
        failure = build_post_rt_failure_definition(payload)
        return bool(
            failure.get("phoenix_threshold_reached")
            or str(failure.get("failure_confirmation_basis") or "")
            in {"biopsy_proven_local_failure", "radiographic_local_failure", "phoenix_confirmed"}
        )

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(value) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _psa_history_points(payload: dict) -> list[dict]:
        points: list[dict] = []

        def _append(value, sample_date="", source="psa"):
            numeric = StateClassifierService._safe_float(value)
            if numeric is None:
                return
            points.append(
                {
                    "value": numeric,
                    "sample_date": str(sample_date or "")[:10],
                    "source": source,
                }
            )

        for row in payload.get("psa_history") or []:
            if isinstance(row, dict):
                _append(
                    row.get("value"),
                    row.get("date") or row.get("sample_date") or row.get("fact_date"),
                    row.get("source") or "psa_history",
                )
        longitudinal_bundle = dict(payload.get("psa_longitudinal_bundle") or {})
        for row in (longitudinal_bundle.get("points") or longitudinal_bundle.get("series") or []):
            if isinstance(row, dict):
                _append(
                    row.get("value") or row.get("psa"),
                    row.get("date") or row.get("sample_date"),
                    row.get("source") or "psa_longitudinal_bundle",
                )
        for row in payload.get("biomarker_longitudinal") or []:
            if not isinstance(row, dict):
                continue
            biomarker_type = str(row.get("biomarker_type") or "").strip().upper()
            if biomarker_type and biomarker_type != "PSA":
                continue
            _append(
                row.get("value"),
                row.get("date") or row.get("sample_date") or row.get("fact_date"),
                row.get("source") or "biomarker_longitudinal",
            )
        _append(payload.get("psa_postop"), payload.get("psa_postop_date") or payload.get("visit_date"), "psa_postop")
        _append(payload.get("psa_current", payload.get("psa")), payload.get("psa_current_date") or payload.get("visit_date"), "psa_current")
        return sorted(
            points,
            key=lambda item: (
                0 if item.get("sample_date") else 1,
                str(item.get("sample_date") or ""),
                str(item.get("source") or ""),
            ),
        )

    @staticmethod
    def _has_confirmatory_post_rp_series(payload: dict) -> bool:
        threshold_points = [
            item
            for item in StateClassifierService._psa_history_points(payload)
            if (StateClassifierService._safe_float(item.get("value")) or 0) >= 0.2
        ]
        if len(threshold_points) < 2:
            return False
        first_date = StateClassifierService._parse_date(threshold_points[0].get("sample_date"))
        last_date = StateClassifierService._parse_date(threshold_points[-1].get("sample_date"))
        if first_date and last_date and last_date >= first_date:
            return True
        return len(threshold_points) >= 2

    @staticmethod
    def _has_structured_bcr_confirmation(payload: dict) -> bool:
        structured = dict(payload.get("bcr") or payload.get("biochemical_recurrence") or {})
        if StateClassifierService._is_true(structured.get("bcr_detected")):
            return True
        bcr_psa = StateClassifierService._safe_float(
            structured.get("bcr_psa", payload.get("bcr_psa"))
        )
        if bcr_psa is not None and bcr_psa >= 0.2:
            if any(
                str(value or "").strip()
                for value in [
                    structured.get("bcr_definition", payload.get("bcr_definition")),
                    structured.get("bcr_date", payload.get("bcr_date")),
                    structured.get("salvage_date", payload.get("salvage_date")),
                ]
            ):
                return True
        return False

    @staticmethod
    def _has_confirmed_post_rp_bcr(payload: dict) -> bool:
        if StateClassifierService._has_structured_bcr_confirmation(payload):
            return True
        psa_postop = StateClassifierService._safe_float(payload.get("psa_postop"))
        psa_current = StateClassifierService._safe_float(payload.get("psa_current", payload.get("psa")))
        confirmatory_series = StateClassifierService._has_confirmatory_post_rp_series(payload)
        trigger_value = max(value for value in [psa_postop, psa_current] if value is not None) if any(
            value is not None for value in [psa_postop, psa_current]
        ) else None
        if StateClassifierService._is_true(payload.get("bcr_confirmed")):
            return True
        if confirmatory_series:
            return True
        if trigger_value is None or trigger_value < 0.2:
            return False
        return False

    @staticmethod
    def _reason_for(
        module: str,
        *,
        burden_context: dict | None = None,
        metachronous: bool = False,
        progression_gate: dict[str, object] | None = None,
        phenotype_state: str = "",
        payload: dict | None = None,
    ) -> str:
        burden_context = burden_context or {}
        progression_gate = progression_gate or {}
        payload = payload or {}
        volume_reason = str(burden_context.get("volume_reason") or "").strip()
        reasons = {
            "screening": "Encuentro de screening / detección temprana: no hay diagnóstico de cáncer y el paciente está siendo evaluado para iniciar o continuar PSA basal según NCCN Early Detection v2.2026.",
            "focal_therapy": "Candidatura a terapia focal selectiva (HIFU / crioablación / TULSA) evaluada contra NCCN PROS-C categoría 2B; requiere lesión unilateral dominante y perfil intermedio favorable.",
            "diagnostic_workup": "No existe confirmación histológica previa y se requiere un estudio diagnóstico estructurado antes de entrar a una ruta terapéutica.",
            "post_negative_biopsy_followup": "Existe una biopsia prostática benigna previa sin diagnóstico confirmado de cáncer y debe priorizarse seguimiento de baja intensidad o reactivación diagnóstica según la nueva sospecha.",
            "localized_initial": "No se detectaron tratamientos locales previos ni marcadores de enfermedad avanzada.",
            "post_prostatectomy": "Se detectó prostatectomía radical previa sin señal de recurrencia bioquímica que desplace el caso fuera del seguimiento postoperatorio.",
            "recurrence_bcr": "Se documentó recurrencia bioquímica o segunda recurrencia bioquímica sin metástasis después de tratamiento local.",
            "post_radiotherapy_or_local_salvage": "Se detectó radioterapia previa con señal de recurrencia; debe separarse la ruta post-RT para confirmar Phoenix, restadificar y priorizar salvage local, MDT o redirección sistémica.",
            "post_radiotherapy_followup": "Se detectó radioterapia radical previa sin señal de recurrencia bioquímica; corresponde el protocolo de seguimiento post-RT con monitoreo de PSA, toxicidad tardía RTOG/EORTC y vigilancia de segundos primarios pélvicos.",
            "mcspc_oligo_metachronous": f"Se detectó enfermedad metastásica sensible a la castración, oligometastásica y metacrónica. {volume_reason}".strip(),
            "mcspc_low_volume_sync_oligo": f"Se detectó enfermedad metastásica sensible a la castración con patrón de bajo volumen u oligometastásico sincrónico. {volume_reason}".strip(),
            "mcspc_high_volume_sync": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen sincrónica / de novo. {volume_reason}".strip(),
            "mcspc_high_volume_metachronous": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen metacrónica. {volume_reason}".strip(),
            "mcspc_high_volume": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen. {volume_reason}".strip(),
            "adt_progression_verification": "Se detectó progresión bajo terapia de privación androgénica o una etiqueta de CRPC sin castración confirmada, por lo que primero debe verificarse testosterona en rango de castración y reestadificación convencional.",
            "m0_crpc": "Se detectó enfermedad resistente a la castración sin metástasis.",
            "m1_crpc": "Se detectó enfermedad resistente a la castración con metástasis.",
        }
        reason = reasons.get(module, "El módulo fue seleccionado por el clasificador de estado clínico.")
        if module == "post_prostatectomy":
            psa_postop = StateClassifierService._safe_float(payload.get("psa_postop", payload.get("psa_current")))
            if psa_postop is not None and 0.1 <= psa_postop < 0.2:
                reason = "Se detecta PSA posprostatectomía bajo pero todavía no BCR confirmada; mantener seguimiento postoperatorio con vigilancia reforzada."
            elif (
                psa_postop is not None
                and psa_postop >= 0.2
                and not StateClassifierService._has_confirmed_post_rp_bcr(payload)
            ):
                reason = "Se detecta un PSA posprostatectomía aislado en rango de BCR, pero todavía sin soporte confirmatorio suficiente; mantener seguimiento postoperatorio con vigilancia reforzada y cierre confirmatorio."
        if module == "post_radiotherapy_or_local_salvage":
            failure = build_post_rt_failure_definition(payload)
            if str(failure.get("phoenix_confirmation_status") or "") == "threshold_only_unconfirmed":
                reason = "Se detectó radioterapia previa con umbral Phoenix alcanzado o señal local post-RT, pero el salvage curativo sigue pendiente de confirmación longitudinal/restadificación."
            elif failure.get("bounce_suspected"):
                reason = "Se detectó radioterapia previa con señal bioquímica compatible con bounce; abrir el carril post-RT para confirmar antes de liberar salvage curativo."
        if module == "mcspc_low_volume_sync_oligo" and not metachronous and burden_context.get("oligometastatic_operational"):
            reason = f"{reason} Patrón operativo oligometastásico sincrónico (<=5 lesiones sin criterio de alto volumen).".strip()
        if progression_gate.get("progression_gate_active"):
            gate_reason = str(progression_gate.get("progression_gate_reason") or "").strip()
            if gate_reason and module == phenotype_state and module in MHSPC_STATES:
                return f"{reason} {gate_reason}".strip()
        return reason

    @staticmethod
    def _normalize_castrate_status(payload: dict) -> str:
        return normalize_castrate_status(
            payload.get("castrate_testosterone_status", "unknown"),
            testosterone_value=payload.get("testosterone_value"),
            castrate_confirmed_flag=payload.get("castrate_testosterone_confirmed"),
        )

    @staticmethod
    def _use_legacy_crpc_shortcut(payload: dict, *, legacy_crpc_signal: bool) -> bool:
        if not legacy_crpc_signal:
            return False
        explicit_progression_context = str(payload.get("systemic_progression_context", "") or "").strip()
        explicit_castrate_status = str(payload.get("castrate_testosterone_status", "") or "").strip()
        explicit_testosterone_value = payload.get("testosterone_value")
        explicit_conventional_imaging = str(payload.get("conventional_imaging_status", "") or "").strip()
        explicit_adt_context = str(payload.get("current_adt_context", "") or "").strip()
        explicit_castration_confirmation = payload.get("castrate_testosterone_confirmed")
        if explicit_progression_context:
            return False
        if explicit_castrate_status:
            return False
        if explicit_testosterone_value not in (None, ""):
            return False
        if explicit_conventional_imaging:
            return False
        if explicit_adt_context:
            return False
        if explicit_castration_confirmation not in (None, ""):
            return False
        return True

    @staticmethod
    def _resolve_phenotype_state(
        *,
        known_cancer_diagnosis: bool,
        prior_negative_biopsy: bool,
        prior_prostatectomy: bool,
        prior_radiation: bool,
        bcr_detected: bool,
        bcr2: bool,
        castration_resistant: bool,
        castrate_status: str,
        conventional_imaging_status: str,
        metastatic: bool,
        metachronous: bool,
        metachronous_known: bool = False,
        burden_context: dict,
        metastasis_count: int,
        legacy_crpc_shortcut: bool,
        payload: dict,
    ) -> str:
        metastatic_basis = str(resolve_metastatic_state_context(payload).get("metastatic_detection_basis") or "")
        psma_only_upstaging = metastatic_basis == "psma_only"
        if not known_cancer_diagnosis:
            if prior_negative_biopsy:
                return "post_negative_biopsy_followup"
            # EPIC 8 — ruta screening: pre-diagnóstico con señal de detección
            # temprana (screening_context=1, encounter_type=screening, o
            # psa_baseline_ng_ml documentado sin sospecha activa de cáncer).
            if StateClassifierService._is_screening_context(payload):
                return "screening"
            return "diagnostic_workup"
        if castration_resistant and (legacy_crpc_shortcut or castrate_status == "confirmed_castrate"):
            if legacy_crpc_shortcut:
                return "m1_crpc" if metastatic else "m0_crpc"
            if psma_only_upstaging and conventional_imaging_status != "M1":
                return "adt_progression_verification"
            if conventional_imaging_status == "M1" or metastatic:
                return "m1_crpc"
            if conventional_imaging_status == "M0":
                return "m0_crpc"
        if metastatic:
            volume_disease = str(burden_context.get("volume_disease") or "low").lower()
            if volume_disease == "high":
                # Guard SC-1: si el dato de metacronía no está capturado, no
                # asumir sincronía por defecto — retornar etiqueta genérica
                # para que la decisión sistémica no se fuerce al carril sync.
                if not metachronous_known:
                    return "mcspc_high_volume"
                return "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"
            if metachronous and burden_context.get("oligometastatic_operational"):
                return "mcspc_oligo_metachronous"
            if metachronous and metastasis_count and metastasis_count <= 5:
                return "mcspc_oligo_metachronous"
            return "mcspc_low_volume_sync_oligo"
        if prior_radiation and not prior_prostatectomy and StateClassifierService._has_post_rt_recurrence_signal(payload):
            return "post_radiotherapy_or_local_salvage"
        if bcr2 or bcr_detected or (prior_prostatectomy and StateClassifierService._has_recurrence_signal(payload)):
            return "recurrence_bcr"
        if prior_prostatectomy:
            return "post_prostatectomy"
        if prior_radiation:
            return "post_radiotherapy_followup"
        return "localized_initial"
