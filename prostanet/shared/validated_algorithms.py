from __future__ import annotations

from typing import Any

from clinical_scores import (
    briganti_lni,
    calculate_capra_s,
    capra_score,
    damico_classification,
    kattan_organ_confined,
    mskcc_bcr_post_rp,
    partin_tables,
)


LOCALIZED_MODULES = {"localized_initial"}
POSTLOCAL_MODULES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
ADVANCED_MODULES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}


def _present(value: Any) -> bool:
    return value not in (None, "", "No aplica", "No realizado", "Desconocido", "Desconocida")


def _dre_present(payload: dict[str, Any]) -> bool:
    return any(
        _present(payload.get(field))
        for field in ("dre_suspicious", "dre_finding", "clinical_tstage_dre_estimate")
    )


def _algorithm_entry(
    *,
    key: str,
    name: str,
    integration_mode: str,
    status: str,
    stage: str,
    summary: str,
    clinical_use: str,
    source_label: str,
    source_url: str,
    inputs_missing: list[str] | None = None,
    evidence_note: str = "",
    result_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "integration_mode": integration_mode,
        "status": status,
        "stage": stage,
        "summary": summary,
        "clinical_use": clinical_use,
        "source_label": source_label,
        "source_url": source_url,
        "inputs_missing": inputs_missing or [],
        "evidence_note": evidence_note,
        "result_snapshot": result_snapshot or {},
    }


def _summarize_capra(score: dict[str, Any]) -> str:
    value = score.get("score")
    risk = score.get("risk_group") or score.get("interpretacion") or score.get("category")
    if value in (None, ""):
        return "CAPRA no calculable con los datos actuales."
    if risk:
        return f"CAPRA {value}/10, {risk}."
    return f"CAPRA {value}/10."


def _summarize_capra_s(score: dict[str, Any]) -> str:
    value = score.get("score")
    risk = score.get("risk_group") or score.get("interpretacion") or score.get("category")
    if value in (None, ""):
        return "CAPRA-S no calculable con los datos actuales."
    if risk:
        return f"CAPRA-S {value}/12, {risk}."
    return f"CAPRA-S {value}/12."


def _summarize_damico(score: dict[str, Any]) -> str:
    risk = score.get("risk_group")
    if not risk:
        return "D'Amico no calculable con los datos actuales."
    return f"D'Amico {risk.lower()}, riesgo basal de recurrencia bioquímica en localizado."


def _summarize_partin(result: dict[str, Any]) -> str:
    oc = result.get("oc_prob")
    ece = result.get("ece_prob")
    lni = result.get("lni_prob")
    if oc is None:
        return "Tablas de Partin no calculables con los datos actuales."
    return f"Partin: organo confinado {oc}%, extension extracapsular {ece}%, riesgo ganglionar {lni}%."


def _summarize_msk(result: dict[str, Any]) -> str:
    oc = result.get("probabilidad_organo_confinado") or result.get("probabilidad_raw")
    if oc in (None, ""):
        return "Nomograma MSKCC preoperatorio no calculable con los datos actuales."
    return f"MSKCC preoperatorio: probabilidad de enfermedad organo-confinada {oc}%."


def _summarize_briganti(result: dict[str, Any]) -> str:
    risk = result.get("risk_pct") or result.get("probabilidad_lni") or result.get("probabilidad_raw")
    if risk in (None, ""):
        return "Briganti no calculable con los datos actuales."
    return f"Briganti: riesgo ganglionar estimado {risk}%."


def _summarize_mskcc_post_rp(result: dict[str, Any]) -> str:
    bcr_free = result.get("bcr_free_5y")
    if bcr_free in (None, ""):
        return "MSKCC BCR post-RP no calculable con los datos actuales."
    return f"MSKCC post-RP: libre de recurrencia bioquímica a 5 años {bcr_free}."


def _external_classifier_entry(payload: dict[str, Any], stage: str) -> dict[str, Any]:
    classifier = str(payload.get("genomic_classifier", "No realizado"))
    result = str(payload.get("genomic_classifier_result", "No aplica"))
    if classifier != "No realizado":
        return _algorithm_entry(
            key="external_genomic_classifier",
            name=classifier,
            integration_mode="external_result",
            status="documentado" if _present(result) else "pendiente_de_resultado",
            stage=stage,
            summary=(
                f"{classifier} documentado con resultado {result}."
                if _present(result)
                else f"{classifier} solicitado o capturado sin resultado estructurado."
            ),
            clinical_use="Refina la conversacion entre vigilancia activa, tratamiento local y rescate cuando el caso es limítrofe.",
            source_label=f"{classifier} externo",
            source_url="",
            evidence_note="Se integra como resultado externo documentado y no sustituye la recomendacion primaria de guias.",
            result_snapshot={"classifier": classifier, "result": result},
        )
    decipher_risk = str(payload.get("decipher_risk", "No realizado"))
    if decipher_risk != "No realizado":
        return _algorithm_entry(
            key="external_decipher",
            name="Decipher",
            integration_mode="external_result",
            status="documentado",
            stage=stage,
            summary=f"Decipher documentado con riesgo {decipher_risk}.",
            clinical_use="Refina vigilancia activa, adyuvancia o rescate segun el contexto clinico.",
            source_label="Decipher externo",
            source_url="https://decipherbio.com/",
            evidence_note="Se integra como resultado externo documentado y no se calcula localmente.",
            result_snapshot={"decipher_risk": decipher_risk, "decipher_score": payload.get("decipher_score")},
        )
    return _algorithm_entry(
        key="external_genomic_classifier",
        name="Decipher / Oncotype DX Prostate / Prolaris",
        integration_mode="external_result",
        status="no_documentado",
        stage=stage,
        summary="No existe un resultado genómico externo documentado todavía.",
        clinical_use="Puede refinar vigilancia activa, tratamiento local o rescate cuando el escenario es biológicamente limítrofe.",
        source_label="Genomica tisular externa",
        source_url="",
        evidence_note="Estas firmas se tratan como resultados externos documentados y nunca como calculos locales.",
    )


def _erspc_entry(module_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    missing = [
        field
        for field in ("age", "psa")
        if not _present(payload.get(field))
    ]
    if not _dre_present(payload):
        missing.append("dre_suspicious")
    if module_id == "post_negative_biopsy_followup" and not _present(payload.get("prior_biopsy_count")):
        missing.append("prior_biopsy_count")
    status = "listo_para_calculadora" if not missing else "faltan_datos"
    summary = (
        "Entradas suficientes para correr ERSPC Risk Calculator en deteccion temprana / rebiopsia."
        if not missing
        else f"Faltan datos para ERSPC: {', '.join(missing)}."
    )
    clinical_use = (
        "Refina el umbral de biopsia o rebiopsia junto con MRI, PSAD, antecedente de biopsia y factores familiares."
    )
    return _algorithm_entry(
        key="erspc",
        name="ERSPC Risk Calculator",
        integration_mode="external_calculator",
        status=status,
        stage=module_id,
        summary=summary,
        clinical_use=clinical_use,
        source_label="ERSPC",
        source_url="https://www.prostatecancer-riskcalculator.com/",
        inputs_missing=missing,
        evidence_note="Se recomienda como refinador libre y validado; la recomendacion primaria sigue anclada a NCCN/EAU.",
    )


def _predict_entry(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [
        field
        for field in ("age", "psa", "clinical_tstage", "isup_grade", "life_expectancy_years")
        if not _present(payload.get(field))
    ]
    status = "listo_para_calculadora" if not missing else "faltan_datos"
    summary = (
        "Entradas suficientes para correr PREDICT Prostate y discutir beneficio absoluto de tratamiento."
        if not missing
        else f"Faltan datos para PREDICT Prostate: {', '.join(missing)}."
    )
    return _algorithm_entry(
        key="predict_prostate",
        name="PREDICT Prostate",
        integration_mode="external_calculator",
        status=status,
        stage="localized_initial",
        summary=summary,
        clinical_use="Apoya la conversacion de beneficio absoluto, expectativa de vida y trade-offs entre vigilancia y tratamiento local.",
        source_label="PREDICT Prostate",
        source_url="https://prostate.predict.nhs.uk/",
        inputs_missing=missing,
        evidence_note="Se usa como calculadora validada de apoyo para decision compartida; no sustituye la clasificacion primaria por guias.",
    )


def _localized_algorithms(payload: dict[str, Any]) -> list[dict[str, Any]]:
    capra = capra_score(payload)
    damico = damico_classification(payload)
    briganti = briganti_lni(payload)
    partin = partin_tables(payload)
    msk = kattan_organ_confined(payload)
    items = [
        _algorithm_entry(
            key="capra",
            name="CAPRA",
            integration_mode="local_computation",
            status="calculado",
            stage="localized_initial",
            summary=_summarize_capra(capra),
            clinical_use="Refina la conversacion de riesgo biologico antes de decidir vigilancia activa, cirugia o radioterapia.",
            source_label="CAPRA (UCSF)",
            source_url="https://urology.ucsf.edu/research/cancer/prostate-cancer-risk-assessment-and-the-ucla-prostate-cancer-index",
            evidence_note="Se usa como capa de refinamiento y no desplaza la recomendacion primaria NCCN/EAU.",
            result_snapshot=capra,
        ),
        _algorithm_entry(
            key="damico",
            name="D'Amico",
            integration_mode="local_computation",
            status="calculado",
            stage="localized_initial",
            summary=_summarize_damico(damico),
            clinical_use="Ordena el riesgo clinico basal de localizado y sirve como comparador clasico de cohortes pretratamiento.",
            source_label="D'Amico",
            source_url="https://pubmed.ncbi.nlm.nih.gov/9827722/",
            evidence_note="Se integra como clasificador clinico basal y no sustituye la recomendacion primaria por guias.",
            result_snapshot=damico,
        ),
        _algorithm_entry(
            key="briganti",
            name="Briganti",
            integration_mode="local_computation",
            status="calculado",
            stage="localized_initial",
            summary=_summarize_briganti(briganti),
            clinical_use="Refina el riesgo ganglionar y la discusion sobre linfadenectomia pelvica extendida.",
            source_label="Briganti",
            source_url="https://uroweb.org/guidelines/prostate-cancer/chapter/diagnostic-evaluation",
            evidence_note="Se usa como refinador de riesgo ganglionar compatible con el enfoque europeo.",
            result_snapshot=briganti,
        ),
        _algorithm_entry(
            key="partin",
            name="Tablas de Partin",
            integration_mode="local_computation",
            status="calculado",
            stage="localized_initial",
            summary=_summarize_partin(partin),
            clinical_use="Apoya counseling quirurgico sobre organo-confinamiento, extension extracapsular y riesgo ganglionar.",
            source_label="Partin Tables",
            source_url="https://pubmed.ncbi.nlm.nih.gov/28318271/",
            evidence_note="Sirven como nomograma patologico de apoyo y no reemplazan la estratificacion primaria por guias.",
            result_snapshot=partin,
        ),
        _algorithm_entry(
            key="mskcc_preop",
            name="MSKCC pre-radical prostatectomy nomogram",
            integration_mode="local_computation",
            status="calculado",
            stage="localized_initial",
            summary=_summarize_msk(msk),
            clinical_use="Refina counseling preoperatorio y expectativa de hallazgos patologicos.",
            source_label="MSKCC",
            source_url="https://www.mskcc.org/nomograms/prostate/pre_op",
            evidence_note="Funciona como benchmark de producto y refinador preoperatorio compatible con la evaluacion modular.",
            result_snapshot=msk,
        ),
        _predict_entry(payload),
        _external_classifier_entry(payload, "localized_initial"),
    ]
    return items


def _postlocal_algorithms(payload: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    capra_s = calculate_capra_s(payload)
    if _present(capra_s.get("score")):
        items.append(
            _algorithm_entry(
                key="capra_s",
                name="CAPRA-S",
                integration_mode="local_computation",
                status="calculado",
                stage=stage,
                summary=_summarize_capra_s(capra_s),
                clinical_use="Refina riesgo posoperatorio y la urgencia de vigilancia estrecha o rescate temprano.",
                source_label="CAPRA-S (UCSF)",
                source_url="https://urology.ucsf.edu/research/cancer/prostate-cancer-risk-assessment-and-the-ucla-prostate-cancer-index",
                evidence_note="Solo es valido en el contexto posoperatorio correcto.",
                result_snapshot=capra_s,
            )
        )
    if all(_present(payload.get(field)) for field in ("psa", "pathology_gleason_primary", "pathology_gleason_secondary", "surgical_margin", "ece_status", "svi_status", "lni_status")):
        msk_post = mskcc_bcr_post_rp(payload)
        items.append(
            _algorithm_entry(
                key="mskcc_bcr_post_rp",
                name="MSKCC BCR post-RP",
                integration_mode="local_computation",
                status="calculado",
                stage=stage,
                summary=_summarize_mskcc_post_rp(msk_post),
                clinical_use="Refina el riesgo posoperatorio de recurrencia bioquímica y la conversación sobre vigilancia o rescate.",
                source_label="MSKCC post-RP",
                source_url="https://www.mskcc.org/nomograms/prostate/post_op",
                evidence_note="Se calcula con los coeficientes oficiales publicados por MSKCC para el modelo postoperatorio.",
                result_snapshot=msk_post,
            )
        )
    items.append(_external_classifier_entry(payload, stage))
    return items


def _advanced_classifier_history(payload: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    items = []
    classifier = _external_classifier_entry(payload, stage)
    items.append(classifier)
    if stage in ADVANCED_MODULES:
        items.append(
            _algorithm_entry(
                key="advanced_precision_note",
                name="Firmas tisulares historicas",
                integration_mode="external_result",
                status="contextual",
                stage=stage,
                summary="Las firmas tisulares documentadas pueden conservar valor longitudinal, pero no ordenan por si solas la secuencia sistemica avanzada.",
                clinical_use="Se usan como contexto biologico historico y para trazabilidad, mientras la secuencia avanzada depende sobre todo de biomarcadores accionables, PSMA, linea terapeutica y seguridad.",
                source_label="NCCN / EAU 2026",
                source_url="",
                evidence_note="No se usan como selector primario de secuencia avanzada salvo evidencia directa y trazable para ese contexto.",
            )
        )
    return items


def build_validated_algorithms(module_id: str, payload: dict[str, Any], result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if module_id in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return [_erspc_entry(module_id, payload)]
    if module_id in LOCALIZED_MODULES:
        return _localized_algorithms(payload)
    if module_id in POSTLOCAL_MODULES:
        return _postlocal_algorithms(payload, module_id)
    if module_id in ADVANCED_MODULES:
        return _advanced_classifier_history(payload, module_id)
    return []
