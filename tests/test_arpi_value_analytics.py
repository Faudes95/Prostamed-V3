from __future__ import annotations

import json
import sqlite3
import subprocess
import sys


def _seed_arpi_value_cohort(db_path):
    import tracking_db

    patient_ids = []
    for idx, (decline, psa50, psa90, ecog_change) in enumerate(
        [
            (80.0, 1, 0, -1),
            (65.0, 1, 0, -1),
            (55.0, 1, 0, 0),
            (30.0, 0, 0, 1),
            (10.0, 0, 0, None),
        ],
        start=1,
    ):
        nss = f"ARPI-VALUE-{idx:03d}"
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO patient_identity (
                    nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason
                ) VALUES (?, ?, ?, ?, 1, 'unit_test')
                """,
                (nss, f"Paciente Valor ARPI {idx}", "1960-01-01", "2026-01-01"),
            )
            patient_id = cursor.lastrowid
            conn.commit()
        patient_ids.append(patient_id)
        started = tracking_db.start_or_update_treatment_course(
            nss,
            {
                "regimen_code": "ADT_ABIRATERONE",
                "line_of_therapy_number": 1,
                "line_of_therapy_context": "mHSPC_initial",
                "start_date": "2026-01-01",
                "doses_received_before_unit": 0,
                "local_doses_administered": 4,
                "unit_name": "Unidad local",
                "referral_target": "HGZ",
            },
        )
        assert started["success"] is True
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO arpi_response_windows (
                    patient_id, regimen_code, target_weeks, target_date,
                    line_start_date, baseline_psa, actual_psa, actual_psa_date,
                    psa_decline_pct, psa50_response, psa90_response,
                    actual_ecog, baseline_ecog, ecog_change_from_baseline,
                    window_offset_days, evidence_quality, computed_at
                ) VALUES (?, ?, 24, '2026-06-17', '2026-01-01', 100.0, ?, '2026-06-16',
                          ?, ?, ?, ?, 2, ?, -1, 'in_window', '2026-06-17T00:00:00Z')
                """,
                (
                    patient_id,
                    "ADT_ABIRATERONE",
                    100.0 - decline,
                    decline,
                    psa50,
                    psa90,
                    None if ecog_change is None else 2 + ecog_change,
                    ecog_change,
                ),
            )
            conn.commit()
    return patient_ids


def _seed_comparative_treatment_value_registry(db_path):
    import tracking_db

    configs = [
        (
            "ABIR",
            "ADT_ABIRATERONE",
            "mHSPC_initial",
            [70.0, 60.0, 55.0, 35.0, 20.0],
            [72.0, 62.0, 57.0, 38.0, 22.0],
        ),
        (
            "DARO",
            "ADT_DOCETAXEL_DAROLUTAMIDE",
            "mHSPC_initial",
            [95.0, 92.0, 80.0, 65.0, 45.0],
            [96.0, 93.0, 82.0, 68.0, 48.0],
        ),
    ]
    patient_ids = []
    for prefix, regimen, context, declines_12, declines_24 in configs:
        for idx, (decline_12, decline_24) in enumerate(zip(declines_12, declines_24), start=1):
            nss = f"REG-VALUE-{prefix}-{idx:03d}"
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO patient_identity (
                        nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason
                    ) VALUES (?, ?, ?, ?, 1, 'unit_test')
                    """,
                    (nss, f"Paciente Registro Valor {prefix} {idx}", "1960-01-01", "2026-01-01"),
                )
                patient_id = cursor.lastrowid
                conn.commit()
            patient_ids.append(patient_id)
            started = tracking_db.start_or_update_treatment_course(
                nss,
                {
                    "regimen_code": regimen,
                    "line_of_therapy_number": 1,
                    "line_of_therapy_context": context,
                    "start_date": "2026-01-01",
                    "doses_received_before_unit": 0,
                    "local_doses_administered": 4,
                    "unit_name": "Unidad local",
                    "referral_target": "HGZ",
                },
            )
            assert started["success"] is True
            treatment_id = started["course"]["appended_id"]
            if idx == 1:
                tracking_db.append_treatment_dose_administration(
                    nss,
                    {
                        "treatment_history_id": treatment_id,
                        "dose_date": "2026-01-20",
                        "unit_name": "Unidad local",
                        "referral_target": "HGZ",
                    },
                )
                tracking_db.append_treatment_dose_administration(
                    nss,
                    {
                        "treatment_history_id": treatment_id,
                        "dose_date": "2026-02-01",
                        "unit_name": "Unidad local",
                        "referral_target": "HGZ",
                    },
                )
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.cursor()
                if idx == 1:
                    cursor.execute(
                        """
                        INSERT INTO treatment_adverse_events (
                            patient_id, treatment_id, regimen_code, cycle_number,
                            ctcae_term, ctcae_grade, attribution, seriousness,
                            hospitalization, dose_modification_triggered, event_date, notes
                        ) VALUES (?, ?, ?, 2, 'fatigue', 3, 'probable', 'grade3',
                                  0, 1, '2026-02-10', 'Toxicidad G3 comparativa')
                        """,
                        (patient_id, treatment_id, regimen),
                    )
                if prefix == "ABIR" and idx == 2:
                    cursor.execute(
                        """
                        UPDATE treatment_history
                        SET end_date = '2026-04-01',
                            outcome = 'Discontinued',
                            discontinuation_reason = 'toxicidad limitante'
                        WHERE id = ?
                        """,
                        (treatment_id,),
                    )
                for weeks, target_date, actual_date, decline in (
                    (12, "2026-03-26", "2026-03-25", decline_12),
                    (24, "2026-06-18", "2026-06-17", decline_24),
                ):
                    baseline_ecog = 2 if prefix == "ABIR" else 1
                    ecog_change = -1 if idx <= (2 if prefix == "ABIR" else 3) else 0
                    actual_ecog = baseline_ecog + ecog_change
                    cursor.execute(
                        """
                        INSERT INTO arpi_response_windows (
                            patient_id, regimen_code, target_weeks, target_date,
                            line_start_date, baseline_psa, actual_psa, actual_psa_date,
                            psa_decline_pct, psa50_response, psa90_response,
                            actual_ecog, baseline_ecog, ecog_change_from_baseline,
                            window_offset_days, evidence_quality, computed_at
                        ) VALUES (?, ?, ?, ?, '2026-01-01', 100.0, ?, ?,
                                  ?, ?, ?, ?, ?, ?, -1, 'in_window', '2026-06-18T00:00:00Z')
                        """,
                        (
                            patient_id,
                            regimen,
                            weeks,
                            target_date,
                            100.0 - decline,
                            actual_date,
                            decline,
                            1 if decline >= 50.0 else 0,
                            1 if decline >= 90.0 else 0,
                            actual_ecog,
                            baseline_ecog,
                            ecog_change,
                        ),
                    )
                conn.commit()
    return patient_ids


def test_arpi_value_analytics_links_spend_doses_psa_and_ecog(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        aggregate_arpi_value_by_response,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_arpi_value_cohort(db_path)

        bundle = aggregate_arpi_value_by_response(weeks=24)
        abiraterone = bundle["by_arpi"]["ABIRATERONE"]

        assert bundle["kpi_id"] == "arpi_value_24wk"
        assert bundle["summary"]["n_patients"] == 5
        assert bundle["summary"]["priced_local_arpi_doses_to_window"] == 20
        assert bundle["summary"]["partial_cost_patient_count"] == 5
        assert bundle["summary"]["estimated_spend_to_window_mxn"] == 195000.0
        assert bundle["summary"]["cost_per_psa50_responder_mxn"] == 65000.0
        assert bundle["summary"]["cost_per_ecog_improved_patient_mxn"] == 97500.0
        assert abiraterone["suppressed"] is False
        assert abiraterone["n"] == 5
        assert abiraterone["total_local_doses_to_window"] == 20
        assert abiraterone["priced_local_doses_to_window"] == 20
        assert abiraterone["partial_cost_patient_count"] == 5
        assert abiraterone["psa50_rate"]["successes"] == 3
        assert abiraterone["ecog_improvement_rate"]["successes"] == 2
    finally:
        tracking_db.configure_db_path(original)


def test_treatment_value_registry_compares_molecule_regimen_and_adjusts_baseline(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_treatment_value_registry,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        registry = build_treatment_value_registry(weeks_list=(12, 24))
        week24 = registry["windows"]["24"]
        abiraterone = week24["by_molecule"]["ABIRATERONE"]
        darolutamide_regimen = week24["by_regimen"]["ADT_DOCETAXEL_DAROLUTAMIDE"]

        assert registry["kpi_id"] == "treatment_value_registry_12_24wk"
        assert registry["cohort_builder"]["version"] == "cohort_builder_v2"
        assert set(registry["windows"]) == {"12", "24"}
        assert week24["summary"]["n_patients"] == 10
        assert week24["summary"]["psa50_responder_count"] == 7
        assert week24["summary"]["psa90_responder_count"] == 2
        assert week24["summary"]["discontinuation_count"] == 1
        assert week24["summary"]["high_grade_toxicity_count"] == 2
        assert week24["summary"]["referral_delay_patient_count"] == 2
        assert abiraterone["n"] == 5
        assert abiraterone["psa50_rate"]["successes"] == 3
        assert darolutamide_regimen["n"] == 5
        assert darolutamide_regimen["psa90_rate"]["successes"] == 2
        assert darolutamide_regimen["cost_per_psa50_responder_mxn"] == 261250.0
        assert darolutamide_regimen["adjusted_by_baseline_state"]["metrics"]["psa50_rate"]["adjusted_rate"] is not None
        assert registry["completeness_tower"]["version"] == "epidemiology_completeness_tower_v2"
        assert registry["longitudinal_outcomes"]["line_persistence_days"]["n"] == 10
        assert registry["economic_layer"]["cost_per_non_responder_mxn"] is not None
        assert registry["capture_worklist"]["version"] == "epidemiology_capture_worklist_v2"
        assert registry["capture_worklist"]["open_gap_count"] > 0
        assert registry["capture_worklist"]["unreviewed_gap_count"] > 0
        assert any(item["capture_url"].startswith("/longitudinal-capture/") for item in registry["capture_worklist"]["items"])
        assert registry["operational_gap_latency"]["version"] == "operational_gap_latency_v1"
        assert registry["operational_gap_latency"]["source_clinical_facts_mutated"] is False
        latency_domains = {item["key"]: item for item in registry["operational_gap_latency"]["domains"]}
        assert latency_domains["psa_response_window"]["coverage_pct"] == 100.0
        assert latency_domains["referral_after_dose4"]["max_days_to_close"] == 31
        assert registry["research_governance"]["status"] in {
            "auditable_exploratory",
            "exploratory_insufficient_for_inference",
            "poster_or_manuscript_ready",
        }

        first_row = next(
            row for row in week24["patient_rows"]
            if row["patient_ref"] == "REG-VALUE-ABIR-001"
        )
        assert first_row["high_grade_toxicity_to_window"] is True
        assert first_row["referral_status"] == "delayed_to_critical"
        assert first_row["referral_delay_days"] == 31
    finally:
        tracking_db.configure_db_path(original)


def test_epidemiology_command_center_assembles_final_dashboard_bundle(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_epidemiology_command_center,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        dashboard = build_epidemiology_command_center(weeks_list=(12, 24, 36, 52), trace_limit=25)

        assert dashboard["version"] == "epidemiology_command_center_v2"
        assert dashboard["kpi_id"] == "grand_epidemiology_dashboard_v2"
        assert dashboard["primary_window_weeks"] == 24
        assert dashboard["source_clinical_facts_mutated"] is False
        assert dashboard["external_order_created"] is False
        assert dashboard["model_trained"] is False
        assert {row["week"] for row in dashboard["outcome_matrix"]} == {12, 24, 36, 52}
        assert dashboard["comparison_panel"]["primary_window_weeks"] == 24
        assert dashboard["comparison_panel"]["adjustment_method"]
        assert dashboard["bias_and_readiness"]["causal_readiness"]["version"] == "causal_readiness_v2"
        assert dashboard["completeness_tower"]["version"] == "epidemiology_completeness_tower_v2"
        assert dashboard["economic_layer"]["version"] == "institutional_economic_layer_v2"
        assert dashboard["operational_gap_latency"]["version"] == "operational_gap_latency_v1"
        assert any(item["key"] == "operational_latency" for item in dashboard["executive_kpis"])
        assert len(dashboard["patient_metric_trace"]) == 20
        assert dashboard["metric_provenance"]["version"] == "metric_provenance_binding_v1"
        assert dashboard["metric_provenance"]["source_mode"] == "live_cohort_exploratory"
        assert dashboard["metric_provenance"]["summary"]["metric_count"] >= 8

        filtered = build_epidemiology_command_center(
            weeks_list=(12, 24, 36, 52),
            filters={"patient_ref": "REG-VALUE-DARO-001"},
            trace_limit=25,
        )
        impact = filtered["capture_impact_bridge"]
        assert impact["version"] == "treatment_value_capture_impact_v1"
        assert impact["source_mode"] == "live_capture_delta"
        assert impact["after"]["patient_contributes_to_registry"] is True
        assert impact["after"]["active_window_count"] == 2
        assert any(row["patient_ref"] == "REG-VALUE-DARO-001" for row in impact["patient_metric_trace"])
        impact_kpi = next(item for item in filtered["executive_kpis"] if item["key"] == "capture_impact")
        assert impact_kpi["value"] == "Si"
    finally:
        tracking_db.configure_db_path(original)


def test_epidemiology_metric_provenance_binds_dashboard_to_governed_freeze(tmp_path):
    import tracking_db
    from prostanet.domains.platform_readiness.research_pack_materializer import (
        freeze_research_pack_materializer,
    )
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_epidemiology_command_center,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        frozen = freeze_research_pack_materializer(
            limit=50,
            title="Metric provenance test freeze",
            created_by="unit_test",
            governance_status="audit_ready",
            clinical_objective="Validar procedencia de metricas epidemiologicas",
            research_question="Puede cada KPI citar freeze, hash, diccionario y lineage?",
            methodology_note="Prueba unitaria read-only de metric provenance.",
            responsible="unit_test",
        )
        assert frozen["success"] is True
        freeze_key = frozen["freeze_key"]

        dashboard = build_epidemiology_command_center(
            weeks_list=(12, 24, 36, 52),
            trace_limit=25,
            source_freeze_key=freeze_key,
        )
        provenance = dashboard["metric_provenance"]

        assert provenance["source_mode"] == "governed_freeze_bound"
        assert provenance["source_freeze_key"] == freeze_key
        assert provenance["payload_sha256"] == frozen["payload_sha256"]
        assert provenance["cohort_binding_status"]["status"] in {
            "freeze_covers_or_exceeds_dashboard_n",
            "freeze_contextual_binding_review_n",
        }
        assert provenance["summary"]["metrics_bound_to_freeze"] == provenance["summary"]["metric_count"]
        assert provenance["summary"]["reconstructable_metric_count"] >= 1
        assert provenance["pack_inventory"]["subject_count_from_rows"] >= 5

        first_metric = provenance["metrics"][0]
        assert first_metric["source_freeze_key"] == freeze_key
        assert first_metric["payload_sha256"] == frozen["payload_sha256"]
        assert first_metric["suppression_policy"]
        assert first_metric["data_dictionary_refs"]
        assert first_metric["row_family_refs"]
        assert "patient_ref" not in json.dumps(provenance, ensure_ascii=False)
        assert "REG-VALUE-" not in json.dumps(provenance, ensure_ascii=False)
        assert "Paciente Registro Valor" not in json.dumps(provenance, ensure_ascii=False)
    finally:
        tracking_db.configure_db_path(original)


def test_epidemiology_metric_snapshot_pack_is_reproducible_and_no_phi(tmp_path):
    import tracking_db
    from prostanet.domains.platform_readiness.research_pack_materializer import (
        freeze_research_pack_materializer,
    )
    from prostanet.domains.population_intelligence.epidemiology_metric_snapshot import (
        build_epidemiology_metric_snapshot_pack,
        build_statistical_reproduction_pack,
        build_statistical_reproduction_pack_zip_bytes,
        freeze_epidemiology_metric_snapshot_pack,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        frozen_source = freeze_research_pack_materializer(
            limit=50,
            title="Snapshot source freeze",
            created_by="unit_test",
            governance_status="audit_ready",
        )
        assert frozen_source["success"] is True

        pack = build_epidemiology_metric_snapshot_pack(
            weeks_list=(12, 24, 36, 52),
            filters={"molecule": "DAROLUTAMIDE", "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE"},
            trace_limit=25,
            source_freeze_key=frozen_source["freeze_key"],
        )

        assert pack["version"] == "epidemiology_metric_snapshot_pack_v1"
        assert pack["snapshot_type"] == "epidemiology_metric_snapshot_v1"
        assert pack["source_clinical_facts_mutated"] is False
        assert pack["external_order_created"] is False
        assert pack["model_trained"] is False
        assert pack["summary"]["no_phi_status"] == "pass"
        assert pack["summary"]["governance_status"] == "exploratory"
        assert pack["summary"]["approval_status"] == "draft"
        assert pack["governance"]["human_approval"]["methodology_version"] == "epi_snapshot_methods_v1.0"
        assert pack["governance"]["human_approval"]["signature_present"] is False
        assert pack["no_phi_scan"]["direct_identifier_key_count"] == 0
        assert pack["no_phi_scan"]["exact_phi_hit_count"] == 0
        assert set(pack["files"]) >= {
            "snapshot.json",
            "executive_kpis.csv",
            "outcome_matrix.csv",
            "metric_provenance.csv",
            "methodology.json",
        }
        assert all(len(value) == 64 for value in pack["snapshot_hashes"].values())
        assert pack["metric_provenance"]["source_freeze_key"] == frozen_source["freeze_key"]
        assert pack["frozen_dashboard"]["patient_metric_trace_summary"]["patient_level_rows_omitted_for_no_phi"] is True

        serialized = json.dumps(pack, ensure_ascii=False)
        assert '"patient_metric_trace":' not in serialized
        assert '"patient_ref":' not in serialized
        assert '"patient_name":' not in serialized
        assert '"profile_url":' not in serialized
        assert "REG-VALUE-" not in serialized
        assert "Paciente Registro Valor" not in serialized
        assert "/patient_profile/" not in serialized

        first = freeze_epidemiology_metric_snapshot_pack(
            weeks_list=(12, 24, 36, 52),
            filters={"molecule": "DAROLUTAMIDE", "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE"},
            trace_limit=25,
            source_freeze_key=frozen_source["freeze_key"],
            created_by="unit_test",
            title="Snapshot Darolutamida",
        )
        second = freeze_epidemiology_metric_snapshot_pack(
            weeks_list=(12, 24, 36, 52),
            filters={"molecule": "DAROLUTAMIDE", "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE"},
            trace_limit=25,
            source_freeze_key=frozen_source["freeze_key"],
            created_by="unit_test",
            title="Snapshot Darolutamida",
        )
        assert first["success"] is True
        assert first["created"] is True
        assert first["freeze_key"].startswith("episnap_")
        assert second["success"] is True
        assert second["created"] is False
        assert first["freeze_key"] == second["freeze_key"]
        assert first["payload_sha256"] == second["payload_sha256"]
        assert first["freeze"]["payload"]["summary"]["no_phi_status"] == "pass"

        blocked = freeze_epidemiology_metric_snapshot_pack(
            weeks_list=(12, 24, 36, 52),
            filters={"molecule": "DAROLUTAMIDE"},
            trace_limit=25,
            source_freeze_key=frozen_source["freeze_key"],
            governance_status="poster_ready",
            approval_status="human_reviewed",
        )
        assert blocked["success"] is False
        assert blocked["error"] == "epidemiology_metric_snapshot_governance_incomplete"
        assert "poster_or_publication_ready_requires_approved_research_use" in blocked["governance_errors"]

        approved = freeze_epidemiology_metric_snapshot_pack(
            weeks_list=(12, 24, 36, 52),
            filters={"molecule": "DAROLUTAMIDE"},
            trace_limit=25,
            source_freeze_key=frozen_source["freeze_key"],
            governance_status="poster_ready",
            approval_status="approved_research_use",
            approved_by="unit_test_reviewer",
            reviewer_role="uro_oncology_clinician",
            approval_note="Revision metodologica suficiente para poster interno.",
            methodology_version="epi_snapshot_methods_v1.1",
            signed_at="2026-05-28T12:00:00Z",
        )
        assert approved["success"] is True
        human_approval = approved["freeze"]["payload"]["governance"]["human_approval"]
        assert human_approval["governance_status"] == "poster_ready"
        assert human_approval["approval_status"] == "approved_research_use"
        assert human_approval["signature_present"] is True
        assert human_approval["methodology_version"] == "epi_snapshot_methods_v1.1"

        reproduction_pack = build_statistical_reproduction_pack(approved["freeze"])
        assert reproduction_pack["version"] == "statistical_reproduction_notebook_pack_v1"
        assert reproduction_pack["checks"]["all_checks_passed"] is True
        assert reproduction_pack["checks"]["kpi_matrix_match"] is True
        assert reproduction_pack["checks"]["filters_hash_match"] is True
        assert reproduction_pack["checks"]["provenance_hash_match"] is True
        assert reproduction_pack["checks"]["db_accessed"] is False
        assert reproduction_pack["checks"]["no_phi_scan"]["status"] == "pass"
        assert "reproduce_snapshot.py" in reproduction_pack["files"]
        assert "reproduction_notebook.ipynb" in reproduction_pack["files"]
        assert "reproduction_report.md" in reproduction_pack["files"]

        repro_zip = build_statistical_reproduction_pack_zip_bytes(approved["freeze"])
        extract_dir = tmp_path / "reproduction_pack"
        extract_dir.mkdir()
        import zipfile
        import io

        with zipfile.ZipFile(io.BytesIO(repro_zip)) as archive:
            archive.extractall(extract_dir)
            names = set(archive.namelist())
        assert {
            "snapshot.json",
            "reproduce_snapshot.py",
            "reproduction_notebook.ipynb",
            "reproduction_manifest.json",
        } <= names
        executed = subprocess.run(
            [sys.executable, "reproduce_snapshot.py"],
            cwd=extract_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        executed_checks = json.loads(executed.stdout)
        assert executed_checks["all_checks_passed"] is True
        assert executed_checks["db_accessed"] is False
        assert (extract_dir / "reproduction_report.md").exists()
        assert (extract_dir / "reconstructed_kpi_matrix.json").exists()
    finally:
        tracking_db.configure_db_path(original)


def test_treatment_value_registry_filters_and_traces_patient_metrics(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_treatment_value_registry,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        registry = build_treatment_value_registry(
            weeks_list=(12, 24),
            filters={"molecule": "DAROLUTAMIDE", "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE"},
            trace_limit=20,
        )

        assert registry["active_filters"]["molecule"] == "DAROLUTAMIDE"
        assert registry["active_filters"]["regimen"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
        assert {item["code"] for item in registry["filter_options"]["regimens"]} == {
            "ADT_ABIRATERONE",
            "ADT_DOCETAXEL_DAROLUTAMIDE",
        }
        assert registry["windows"]["24"]["summary"]["n_patients"] == 5
        assert registry["windows"]["24"]["summary"]["regimen_count"] == 1
        assert registry["windows"]["24"]["summary"]["psa90_rate_pct"] == 40.0
        assert any(
            item["group_type"] == "regimen"
            and item["key"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
            and item["windows"]["24"]["n"] == 5
            for item in registry["cohort_matrix"]
        )
        assert len(registry["patient_metric_trace"]) == 10
        assert all(row["molecule"] == "DAROLUTAMIDE" for row in registry["patient_metric_trace"])
        assert all(row["profile_url"].endswith("?v=2") for row in registry["patient_metric_trace"])
        assert any("PSA90" in row["metric_flags"] for row in registry["patient_metric_trace"])

        psa90_registry = build_treatment_value_registry(
            weeks_list=(12, 24),
            filters={"metric": "psa90", "age_band": "age_65_74"},
            trace_limit=20,
        )
        assert psa90_registry["active_filters"]["metric"] == "psa90"
        assert psa90_registry["active_filters"]["age_band"] == "age_65_74"
        assert psa90_registry["windows"]["24"]["summary"]["n_patients"] == 2
        assert all(row["psa90_response"] is True for row in psa90_registry["patient_metric_trace"])
    finally:
        tracking_db.configure_db_path(original)


def test_treatment_value_research_pack_builds_methods_dictionary_and_dataset(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_treatment_value_research_pack,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        pack = build_treatment_value_research_pack(
            weeks_list=(12, 24),
            filters={"molecule": "DAROLUTAMIDE", "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE"},
            trace_limit=20,
        )

        assert pack["version"] == "treatment_value_research_pack_v2"
        assert pack["cohort_definition"]["patient_count_primary_window"] == 5
        assert pack["cohort_definition"]["trace_row_count"] == 10
        assert pack["readiness"]["research_grade"] in {
            "lista_para_poster_articulo",
            "auditable_exploratoria",
            "requiere_captura_antes_de_inferencia",
            "insuficiente_para_investigacion",
        }
        assert "propensity" in pack["methods"]["statistical_note"]
        assert any(row["field"] == "patient_ref" for row in pack["data_dictionary"])
        assert all(row["molecule"] == "DAROLUTAMIDE" for row in pack["dataset"]["rows"])
        assert pack["export_manifest"]["patient_level_primary_key"] == ["patient_ref", "week", "regimen_code"]
    finally:
        tracking_db.configure_db_path(original)


def test_treatment_value_research_pack_freeze_is_idempotent(tmp_path):
    import tracking_db
    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_treatment_value_research_pack,
    )

    original = tracking_db.get_db_path()
    db_path = tmp_path / "tracking.db"
    try:
        tracking_db.configure_db_path(str(db_path))
        tracking_db.init_tracking_db()
        _seed_comparative_treatment_value_registry(db_path)

        pack = build_treatment_value_research_pack(
            weeks_list=(12, 24),
            filters={
                "molecule": "DAROLUTAMIDE",
                "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE",
            },
            trace_limit=20,
        )
        first = tracking_db.freeze_treatment_value_research_pack(
            pack,
            title="Cohorte Darolutamida congelada",
            created_by="unit_test",
        )
        second = tracking_db.freeze_treatment_value_research_pack(
            pack,
            title="Cohorte Darolutamida congelada",
            created_by="unit_test",
        )

        assert first["success"] is True
        assert first["created"] is True
        assert second["success"] is True
        assert second["created"] is False
        assert first["freeze_key"] == second["freeze_key"]
        assert first["payload_sha256"] == second["payload_sha256"]
        assert first["source_clinical_facts_mutated"] is False
        assert first["external_order_created"] is False
        assert first["model_trained"] is False
        assert first["freeze"]["payload"]["version"] == "treatment_value_research_pack_v2"
        assert first["freeze"]["patient_count_primary_window"] == 5
        assert first["freeze"]["trace_row_count"] == 10

        detail = tracking_db.get_research_cohort_freeze(first["freeze_key"])
        assert detail["payload_sha256"] == first["payload_sha256"]
        assert detail["payload"]["dataset"]["row_count"] == 10
        assert tracking_db.list_research_cohort_freezes(limit=5)[0]["freeze_key"] == first["freeze_key"]
    finally:
        tracking_db.configure_db_path(original)


def test_arpi_value_endpoint_exposes_patient_rows(app_client):
    client, db_path = app_client
    _seed_arpi_value_cohort(db_path)

    response = client.get("/api/analytics/arpi-real-world-value?weeks=24")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["summary"]["n_patients"] == 5
    assert payload["by_arpi"]["ABIRATERONE"]["suppressed"] is False
    assert len(payload["patient_rows"]) == 5

    compact = client.get("/api/analytics/arpi-real-world-value?weeks=24&include_rows=0")
    assert compact.status_code == 200
    assert "patient_rows" not in compact.get_json()


def test_treatment_value_registry_endpoint_exposes_12_24_windows(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    response = client.get("/api/analytics/treatment-value-registry?weeks=12,24&include_rows=0")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["kpi_id"] == "treatment_value_registry_12_24wk"
    assert set(payload["windows"]) == {"12", "24"}
    assert "patient_rows" not in payload["windows"]["24"]
    assert payload["windows"]["12"]["summary"]["n_patients"] == 10
    assert payload["windows"]["24"]["by_regimen"]["ADT_ABIRATERONE"]["n"] == 5

    filtered = client.get(
        "/api/analytics/treatment-value-registry"
        "?weeks=12,24&molecule=DAROLUTAMIDE&regimen=ADT_DOCETAXEL_DAROLUTAMIDE&trace_limit=20"
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.get_json()
    assert filtered_payload["active_filters"]["molecule"] == "DAROLUTAMIDE"
    assert filtered_payload["windows"]["24"]["summary"]["n_patients"] == 5
    assert filtered_payload["windows"]["24"]["summary"]["psa90_rate_pct"] == 40.0
    assert all(row["molecule"] == "DAROLUTAMIDE" for row in filtered_payload["patient_metric_trace"])

    csv_response = client.get(
        "/api/analytics/treatment-value-registry"
        "?weeks=12,24&molecule=DAROLUTAMIDE&format=csv&trace_limit=20"
    )
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.content_type
    csv_body = csv_response.get_data(as_text=True)
    assert "patient_ref" in csv_body
    assert "profile_url" in csv_body
    assert "REG-VALUE-DARO" in csv_body


def test_epidemiology_command_center_endpoint_exposes_final_panel(app_client):
    client, db_path = app_client
    from prostanet.domains.platform_readiness.research_pack_materializer import (
        freeze_research_pack_materializer,
    )

    _seed_comparative_treatment_value_registry(db_path)

    response = client.get("/api/analytics/epidemiology-command-center?weeks=12,24,36,52&trace_limit=25")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["version"] == "epidemiology_command_center_v2"
    assert payload["primary_window_weeks"] == 24
    assert len(payload["executive_kpis"]) >= 8
    assert {row["week"] for row in payload["outcome_matrix"]} == {12, 24, 36, 52}
    assert payload["comparison_panel"]["primary_window_weeks"] == 24
    assert payload["bias_and_readiness"]["causal_readiness"]["status"] in {
        "descriptive_only",
        "adjusted_exploratory_ready",
        "propensity_ready_candidate",
    }
    assert payload["economic_layer"]["cost_per_non_responder_mxn"] is not None
    assert payload["operational_gap_latency"]["version"] == "operational_gap_latency_v1"
    assert any(item["key"] == "operational_latency" for item in payload["executive_kpis"])
    assert payload["capture_impact_bridge"]["source_mode"] == "patient_filter_required"
    assert payload["metric_provenance"]["source_mode"] == "live_cohort_exploratory"
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False

    frozen = freeze_research_pack_materializer(
        limit=50,
        title="Endpoint provenance freeze",
        created_by="unit_test",
        governance_status="audit_ready",
        research_question="Endpoint provenance binding",
    )
    assert frozen["success"] is True
    provenance_response = client.get(
        f"/api/analytics/epidemiology-command-center/provenance?weeks=12,24,36,52&source_freeze_key={frozen['freeze_key']}&trace_limit=25"
    )
    assert provenance_response.status_code == 200
    provenance = provenance_response.get_json()
    assert provenance["success"] is True
    assert provenance["version"] == "metric_provenance_binding_v1"
    assert provenance["source_freeze_key"] == frozen["freeze_key"]
    assert provenance["payload_sha256"] == frozen["payload_sha256"]
    assert provenance["summary"]["metrics_bound_to_freeze"] == provenance["summary"]["metric_count"]

    csv_response = client.get("/api/analytics/epidemiology-command-center?weeks=12,24&format=csv&trace_limit=20")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.content_type
    csv_body = csv_response.get_data(as_text=True)
    assert "patient_ref" in csv_body
    assert "REG-VALUE-DARO" in csv_body

    patient_response = client.get(
        "/api/analytics/epidemiology-command-center?weeks=12,24,36,52"
        "&patient_ref=REG-VALUE-DARO-001&trace_limit=25"
    )
    assert patient_response.status_code == 200
    patient_payload = patient_response.get_json()
    assert patient_payload["capture_impact_bridge"]["source_mode"] == "live_capture_delta"
    assert patient_payload["capture_impact_bridge"]["after"]["patient_contributes_to_registry"] is True
    assert any(item["key"] == "capture_impact" for item in patient_payload["executive_kpis"])


def test_epidemiology_snapshot_pack_endpoint_freezes_and_downloads_no_phi_zip(app_client, tmp_path):
    import io
    import zipfile

    client, db_path = app_client
    from prostanet.domains.platform_readiness.research_pack_materializer import (
        freeze_research_pack_materializer,
    )

    _seed_comparative_treatment_value_registry(db_path)
    frozen_source = freeze_research_pack_materializer(
        limit=50,
        title="Endpoint snapshot source freeze",
        created_by="unit_test",
        governance_status="audit_ready",
    )
    assert frozen_source["success"] is True

    response = client.get(
        "/api/analytics/epidemiology-command-center/snapshot-pack"
        f"?weeks=12,24,36,52&molecule=DAROLUTAMIDE&source_freeze_key={frozen_source['freeze_key']}&trace_limit=25"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["version"] == "epidemiology_metric_snapshot_pack_v1"
    assert payload["summary"]["no_phi_status"] == "pass"
    assert payload["metric_provenance"]["source_freeze_key"] == frozen_source["freeze_key"]

    csv_response = client.get(
        "/api/analytics/epidemiology-command-center/snapshot-pack"
        "?weeks=12,24&format=metric_provenance_csv&trace_limit=20"
    )
    assert csv_response.status_code == 200
    csv_body = csv_response.get_data(as_text=True)
    assert "metric_id" in csv_body
    assert "REG-VALUE-" not in csv_body

    freeze_response = client.post(
        "/api/analytics/epidemiology-command-center/snapshot-pack/freeze",
        json={
            "weeks": "12,24,36,52",
            "molecule": "DAROLUTAMIDE",
            "source_freeze_key": frozen_source["freeze_key"],
            "trace_limit": 25,
            "title": "Snapshot endpoint Darolutamida",
            "created_by": "unit_test",
            "governance_status": "audit_ready",
            "approval_status": "human_reviewed",
            "approved_by": "unit_test_reviewer",
            "reviewer_role": "uro_oncology_clinician",
            "approval_note": "Revision humana local para auditoria interna.",
            "methodology_version": "epi_snapshot_methods_v1.1",
            "signed_at": "2026-05-28T12:00:00Z",
        },
    )
    assert freeze_response.status_code == 200
    freeze_payload = freeze_response.get_json()
    assert freeze_payload["success"] is True
    assert freeze_payload["freeze_key"].startswith("episnap_")
    assert freeze_payload["source_clinical_facts_mutated"] is False
    assert freeze_payload["external_order_created"] is False
    assert freeze_payload["model_trained"] is False
    freeze_key = freeze_payload["freeze_key"]

    list_response = client.get("/api/analytics/epidemiology-command-center/snapshot-pack/freezes?limit=5")
    assert list_response.status_code == 200
    listed = list_response.get_json()["freezes"]
    assert listed[0]["freeze_key"] == freeze_key
    assert listed[0]["download_allowed"] is True
    assert listed[0]["human_approval"]["approval_status"] == "human_reviewed"
    assert listed[0]["methodology_version"] == "epi_snapshot_methods_v1.1"
    assert "payload" not in listed[0]

    detail_response = client.get(f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze_key}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["freeze"]
    assert detail["registry_type"] == "epidemiology_metric_snapshot_v1"
    assert detail["payload"]["summary"]["no_phi_status"] == "pass"
    assert detail["payload"]["governance"]["human_approval"]["signature_present"] is True
    assert detail["payload"]["methodology"]["methodology_version"] == "epi_snapshot_methods_v1.1"

    download = client.get(f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze_key}/download")
    assert download.status_code == 200
    assert "application/zip" in download.content_type
    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        names = set(archive.namelist())
        assert {"snapshot.json", "metric_provenance.csv", "outcome_matrix.csv"} <= names
        assert "governance.json" in names
        zip_text = "\n".join(archive.read(name).decode("utf-8") for name in names)
    assert "REG-VALUE-" not in zip_text
    assert "Paciente Registro Valor" not in zip_text
    assert "/patient_profile/" not in zip_text
    assert '"patient_ref":' not in zip_text

    reproduction = client.get(
        f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze_key}/reproduction-pack"
    )
    assert reproduction.status_code == 200
    reproduction_payload = reproduction.get_json()
    assert reproduction_payload["success"] is True
    assert reproduction_payload["version"] == "statistical_reproduction_notebook_pack_v1"
    assert reproduction_payload["checks"]["all_checks_passed"] is True
    assert "files" not in reproduction_payload

    repro_download = client.get(
        f"/api/analytics/epidemiology-command-center/snapshot-pack/freezes/{freeze_key}/reproduction-pack/download"
    )
    assert repro_download.status_code == 200
    assert "application/zip" in repro_download.content_type
    repro_dir = tmp_path / "endpoint_repro"
    repro_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(repro_download.data)) as archive:
        repro_names = set(archive.namelist())
        assert {
            "snapshot.json",
            "governance.json",
            "reproduce_snapshot.py",
            "reproduction_notebook.ipynb",
            "reproduction_report.md",
            "reproduction_manifest.json",
        } <= repro_names
        repro_text = "\n".join(archive.read(name).decode("utf-8") for name in repro_names)
        archive.extractall(repro_dir)
    assert "REG-VALUE-" not in repro_text
    assert "Paciente Registro Valor" not in repro_text
    assert "/patient_profile/" not in repro_text
    executed = subprocess.run(
        [sys.executable, "reproduce_snapshot.py"],
        cwd=repro_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(executed.stdout)["all_checks_passed"] is True


def test_treatment_value_research_pack_endpoint_exports_json_csv_and_dictionary(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    response = client.get(
        "/api/analytics/treatment-value-registry/research-pack"
        "?weeks=12,24&molecule=DAROLUTAMIDE&regimen=ADT_DOCETAXEL_DAROLUTAMIDE&trace_limit=20"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["version"] == "treatment_value_research_pack_v2"
    assert payload["cohort_definition"]["patient_count_primary_window"] == 5
    assert payload["dataset"]["row_count"] == 10
    assert payload["data_dictionary"][0]["field"] == "week"
    assert "methods" in payload
    assert "bias_and_completeness" in payload

    csv_response = client.get(
        "/api/analytics/treatment-value-registry/research-pack"
        "?weeks=12,24&molecule=DAROLUTAMIDE&format=csv&trace_limit=20"
    )
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.content_type
    csv_body = csv_response.get_data(as_text=True)
    assert "patient_ref" in csv_body
    assert "REG-VALUE-DARO" in csv_body

    dictionary_response = client.get(
        "/api/analytics/treatment-value-registry/research-pack?weeks=12,24&format=dictionary_csv"
    )
    assert dictionary_response.status_code == 200
    dictionary_body = dictionary_response.get_data(as_text=True)
    assert "definition" in dictionary_body
    assert "psa50_response" in dictionary_body


def test_treatment_value_research_pack_freeze_endpoint_is_reproducible(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    response = client.post(
        "/api/analytics/treatment-value-registry/research-pack/freeze",
        json={
            "weeks": "12,24",
            "molecule": "DAROLUTAMIDE",
            "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "trace_limit": 20,
            "title": "Cohorte Darolutamida V2",
            "created_by": "unit_test",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["created"] is True
    assert payload["freeze_key"].startswith("tvpack_")
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    freeze_key = payload["freeze_key"]

    duplicate = client.post(
        "/api/analytics/treatment-value-registry/research-pack/freeze",
        json={
            "weeks": "12,24",
            "molecule": "DAROLUTAMIDE",
            "regimen": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "trace_limit": 20,
            "title": "Cohorte Darolutamida V2",
            "created_by": "unit_test",
        },
    ).get_json()
    assert duplicate["created"] is False
    assert duplicate["freeze_key"] == freeze_key

    list_response = client.get("/api/analytics/treatment-value-registry/research-pack/freezes?limit=5")
    assert list_response.status_code == 200
    freezes = list_response.get_json()["freezes"]
    assert freezes[0]["freeze_key"] == freeze_key
    assert "payload" not in freezes[0]

    detail_response = client.get(f"/api/analytics/treatment-value-registry/research-pack/freezes/{freeze_key}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()["freeze"]
    assert detail["payload_sha256"] == payload["payload_sha256"]
    assert detail["payload"]["dataset"]["row_count"] == 10
    assert detail["payload"]["cohort_definition"]["active_filters"]["molecule"] == "DAROLUTAMIDE"


def test_treatment_value_registry_gap_review_records_patient_event(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    registry = client.get("/api/analytics/treatment-value-registry?weeks=12,24&trace_limit=50").get_json()
    item = registry["capture_worklist"]["items"][0]
    assert item["detected_at"]
    assert item["detection_anchor"] == "response_window_target_date"
    assert item["audit_state"] == "open_unreviewed"
    assert item["days_open"] is not None
    assert item["owner_role"]
    assert item["assigned_to"] == item["owner_role"]
    assert item["due_date"]
    assert item["sla_policy"]
    assert item["sla_state"] in {"overdue_unreviewed", "due_soon_unreviewed", "on_track_unreviewed", "sla_unknown"}

    response = client.post(
        "/api/analytics/treatment-value-registry/gap-review",
        json={
            "patient_ref": item["patient_ref"],
            "gap_key": item["gap_key"],
            "closure_status": "followup_scheduled",
            "clinical_note": "Se programo captura dirigida para completar readiness.",
            "reviewed_by": "unit_test",
            "detected_at": item["detected_at"],
            "detection_anchor": item["detection_anchor"],
            "target_weeks": item["target_weeks"],
            "regimen_code": item["regimen_code"],
            "molecule": item["molecule"],
            "selected_action_key": "registry_gap_review",
            "assigned_to": "registro_epidemiologia",
            "owner_role": item["owner_role"],
            "due_date": item["due_date"],
            "sla_days": item["sla_days"],
            "sla_policy": item["sla_policy"],
            "acknowledged_missing_fields": [item["gap_key"]],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False

    refreshed = client.get("/api/analytics/treatment-value-registry?weeks=12,24&trace_limit=50").get_json()
    reviewed = [
        row for row in refreshed["capture_worklist"]["items"]
        if row["patient_ref"] == item["patient_ref"] and row["gap_key"] == item["gap_key"]
    ][0]
    assert reviewed["closure_status"] == "followup_scheduled"
    assert reviewed["reviewed"] is True
    assert reviewed["audit_state"] == "reviewed_still_missing"
    assert reviewed["reviewed_by"] == "unit_test"
    assert reviewed["detected_at"] == item["detected_at"]
    assert reviewed["review_latency_days"] is not None
    assert reviewed["acknowledged_missing_fields"] == [item["gap_key"]]
    assert reviewed["assigned_to"] == "registro_epidemiologia"
    assert reviewed["owner_role"] == item["owner_role"]
    assert reviewed["due_date"] == item["due_date"]
    assert reviewed["sla_state"] in {"overdue_reviewed_still_missing", "due_soon_reviewed_still_missing", "reviewed_pending_capture", "sla_unknown"}
    assert refreshed["capture_worklist"]["reviewed_gap_count"] >= 1
    assert refreshed["capture_worklist"]["sla_by_owner"]
    assert refreshed["operational_gap_latency"]["summary"]["reviewed_capture_worklist_count"] >= 1
    assert "sla_overdue_gap_count" in refreshed["operational_gap_latency"]["summary"]

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            """
            SELECT event_type, status, payload_json
            FROM patient_events
            WHERE event_type = 'epidemiology_readiness_gap_reviewed'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    assert row[0] == "epidemiology_readiness_gap_reviewed"
    assert row[1] == "followup_scheduled"
    assert item["gap_key"] in row[2]
    event_payload = json.loads(row[2])
    assert event_payload["source_clinical_facts_mutated"] is False
    assert event_payload["external_order_created"] is False
    assert event_payload["model_trained"] is False
    assert event_payload["detected_at"] == item["detected_at"]
    assert event_payload["target_weeks"] == str(item["target_weeks"])
    assert event_payload["selected_action_key"] == "registry_gap_review"
    assert event_payload["assigned_to"] == "registro_epidemiologia"
    assert event_payload["owner_role"] == item["owner_role"]
    assert event_payload["due_date"] == item["due_date"]
    assert event_payload["sla_policy"] == item["sla_policy"]


def test_patient_profile_epidemiology_gap_sla_snapshot_and_template_contract(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    registry = client.get("/api/analytics/treatment-value-registry?weeks=12,24&trace_limit=50").get_json()
    item = registry["capture_worklist"]["items"][0]

    from prostanet.domains.population_intelligence.arpi_value_analytics import (
        build_patient_epidemiology_gap_sla,
    )

    snapshot = build_patient_epidemiology_gap_sla(item["patient_ref"], weeks_list=(12, 24))
    assert snapshot["version"] == "patient_epidemiology_gap_sla_v1"
    assert snapshot["source_clinical_facts_mutated"] is False
    assert snapshot["external_order_created"] is False
    assert snapshot["model_trained"] is False
    assert snapshot["summary"]["active_gap_count"] >= 1
    assert snapshot["summary"]["owner_count"] >= 1
    assert snapshot["items"][0]["owner_role"]
    assert snapshot["items"][0]["due_date"]
    assert snapshot["items"][0]["capture_url"].startswith(f"/longitudinal-capture/{item['patient_ref']}")
    assert snapshot["next_surfaces"]["profile_v2"] == f"/patient_profile/{item['patient_ref']}?v=2"

    response = client.get(f"/api/patients/{item['patient_ref']}/epidemiology-gap-sla")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["snapshot"]["version"] == "patient_epidemiology_gap_sla_v1"
    assert payload["snapshot"]["summary"]["active_gap_count"] >= 1

    template = open("templates/patient_profile_v2.html", encoding="utf-8").read()
    assert 'data-testid="v2-epidemiology-gap-sla-panel"' in template
    assert 'data-testid="profile-epi-sla-items"' in template
    assert "epidemiology-gap-sla" in template
    assert "pm2-profile-gap-review-btn" in template


def test_treatment_value_capture_impact_links_patient_capture_to_population_delta(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)

    patient_ref = "REG-VALUE-DARO-001"
    response = client.get(
        f"/api/analytics/treatment-value-registry/capture-impact?patient_ref={patient_ref}&weeks=12,24&trace_limit=20"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["version"] == "treatment_value_capture_impact_v1"
    assert payload["patient_ref"] == patient_ref
    assert payload["source_clinical_facts_mutated"] is False
    assert payload["external_order_created"] is False
    assert payload["model_trained"] is False
    assert payload["external_transfer_performed"] is False
    assert payload["after"]["patient_contributes_to_registry"] is True
    assert payload["after"]["active_window_count"] == 2
    assert payload["after"]["estimated_spend_mxn"] > 0
    assert payload["windows"]["24"]["patient_contributes"] is True
    assert payload["windows"]["24"]["patient_contribution"]["patient_count"] == 1
    assert payload["windows"]["24"]["population_delta"]["patient_count_delta"] == 1
    assert payload["windows"]["24"]["patient_regimens"] == ["ADT_DOCETAXEL_DAROLUTAMIDE"]
    assert "treatment_value_registry_v2" in payload["refreshed_surfaces"]
    assert payload["next_surfaces"]["profile_v2"] == f"/patient_profile/{patient_ref}?v=2"
    assert any(row["patient_ref"] == patient_ref and row["week"] == 24 for row in payload["patient_metric_trace"])


def test_epidemiology_gap_capture_persists_structured_sources_and_recalculates_worklist(app_client):
    client, db_path = app_client
    _seed_comparative_treatment_value_registry(db_path)
    patient_ref = "REG-VALUE-DARO-001"

    before = client.get(
        f"/api/analytics/treatment-value-registry?weeks=12,24&patient_ref={patient_ref}&trace_limit=20"
    ).get_json()
    before_gaps = {
        item["gap_key"]
        for item in before["capture_worklist"]["items"]
        if item["patient_ref"] == patient_ref
    }
    assert {"survival_status", "metastatic_context", "comorbidity"} <= before_gaps

    survival = client.post(
        f"/api/longitudinal/{patient_ref}/append",
        json={
            "kind": "epidemiology_gap",
            "payload": {
                "gap_key": "survival_status",
                "decision_field": "vital_status",
                "last_contact_date": "2026-06-20",
                "last_contact_status": "clinic_visit",
                "vital_status": "alive",
            },
        },
    )
    assert survival.status_code == 200
    survival_payload = survival.get_json()
    assert survival_payload["success"] is True
    assert survival_payload["source_clinical_facts_mutated"] is True
    assert survival_payload["external_order_created"] is False
    assert survival_payload["model_trained"] is False
    assert survival_payload["epidemiology_gap_sla"]["version"] == "patient_epidemiology_gap_sla_v1"
    assert "survival_status" not in {
        item["gap_key"]
        for item in survival_payload["epidemiology_gap_sla"]["items"]
    }
    assert survival_payload["next_surfaces"]["profile_v2"] == f"/patient_profile/{patient_ref}?v=2&refresh=1"

    profile_after_survival = client.get(f"/api/patients/{patient_ref}/epidemiology-gap-sla").get_json()
    assert "survival_status" not in {
        item["gap_key"]
        for item in profile_after_survival["snapshot"]["items"]
    }

    registry_after_survival = client.get(
        f"/api/analytics/treatment-value-registry?weeks=12,24&patient_ref={patient_ref}&trace_limit=20"
    ).get_json()
    assert "survival_status" not in {
        item["gap_key"]
        for item in registry_after_survival["capture_worklist"]["items"]
    }

    command_after_survival = client.get(
        f"/api/analytics/epidemiology-command-center?weeks=12,24&patient_ref={patient_ref}&trace_limit=20"
    ).get_json()
    assert "survival_status" not in {
        item["gap_key"]
        for item in command_after_survival["bias_and_readiness"]["capture_worklist"]["items"]
    }

    metastatic = client.post(
        f"/api/longitudinal/{patient_ref}/append",
        json={
            "kind": "epidemiology_gap",
            "payload": {
                "gap_key": "metastatic_context",
                "decision_field": "volume_disease",
                "metastasis_assessment_date": "2026-06-20",
                "metastasis_site": "M1b",
                "m_substage_resolved": "M1b",
                "volume_disease": "high",
                "metastasis_count": 5,
                "metastasis_document_source": "unit_test_psma",
            },
        },
    )
    assert metastatic.status_code == 200
    assert metastatic.get_json()["structured_writes"][0]["target"] == "clinical_baseline"

    comorbidity = client.post(
        f"/api/longitudinal/{patient_ref}/append",
        json={
            "kind": "epidemiology_gap",
            "payload": {
                "gap_key": "comorbidity",
                "decision_field": "comorbidities",
                "comorbidities_text": "Hipertension; Diabetes mellitus",
            },
        },
    )
    assert comorbidity.status_code == 200

    after = client.get(
        f"/api/analytics/treatment-value-registry?weeks=12,24&patient_ref={patient_ref}&trace_limit=20"
    ).get_json()
    after_gaps = {
        item["gap_key"]
        for item in after["capture_worklist"]["items"]
        if item["patient_ref"] == patient_ref
    }
    assert "survival_status" not in after_gaps
    assert "metastatic_context" not in after_gaps
    assert "comorbidity" not in after_gaps
    trace_row = next(row for row in after["patient_metric_trace"] if row["patient_ref"] == patient_ref and row["week"] == 24)
    assert trace_row["baseline_state_components"]["metastatic_volume"] == "high"
    assert trace_row["baseline_state_components"]["comorbidity_band"] == "comorbidity_1_2"

    with sqlite3.connect(str(db_path)) as conn:
        identity = conn.execute(
            "SELECT vital_status, last_contact_date FROM patient_identity WHERE nss = ?",
            (patient_ref,),
        ).fetchone()
        baseline = conn.execute(
            """
            SELECT volume_disease, metastasis_site, comorbidities_json
            FROM clinical_baseline cb
            JOIN patient_identity pi ON pi.id = cb.patient_id
            WHERE pi.nss = ?
            ORDER BY cb.id DESC LIMIT 1
            """,
            (patient_ref,),
        ).fetchone()
        event_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM patient_events pe
            JOIN patient_identity pi ON pi.id = pe.patient_id
            WHERE pi.nss = ?
              AND pe.event_type = 'epidemiology_readiness_gap_captured'
            """,
            (patient_ref,),
        ).fetchone()[0]
    assert identity == ("alive", "2026-06-20")
    assert baseline[0] == "high"
    assert baseline[1] == "M1b"
    assert "Hipertension" in baseline[2]
    assert event_count == 3

    profile_after_all = client.get(f"/api/patients/{patient_ref}/epidemiology-gap-sla").get_json()
    assert profile_after_all["snapshot"]["summary"]["active_gap_count"] == 0


def test_treatment_value_registry_v2_population_template_contract():
    from pathlib import Path

    template = Path("templates/treatment_value_registry_v2.html").read_text(encoding="utf-8")
    assert 'data-testid="population-treatment-value-v2"' in template
    assert 'data-testid="tv-cohort-builder-v2"' in template
    assert 'data-testid="tv-filter-molecule"' in template
    assert 'data-testid="tv-filter-regimen"' in template
    assert 'data-testid="tv-cohort-table"' in template
    assert 'data-testid="tv-patient-trace"' in template
    assert 'data-testid="tv-completeness-tower"' in template
    assert 'data-testid="tv-research-governance"' in template
    assert 'data-testid="tv-capture-worklist"' in template
    assert 'data-testid="tv-capture-impact-delta"' in template
    assert "/api/analytics/treatment-value-registry/capture-impact" in template
    assert "renderCaptureImpact" in template
    assert "/api/analytics/treatment-value-registry/gap-review" in template
    assert "tv-gap-review-btn" in template
    assert 'data-testid="tv-research-pack-json"' in template
    assert 'data-testid="tv-research-pack-csv"' in template
    assert 'data-testid="tv-research-pack-dictionary"' in template
    assert 'data-testid="tv-freeze-cohort"' in template
    assert 'data-testid="tv-freeze-workspace"' in template
    assert "/api/analytics/treatment-value-registry/research-pack" in template
    assert "/api/analytics/treatment-value-registry/research-pack/freeze" in template
    assert "/api/analytics/treatment-value-registry/research-pack/freezes" in template
    assert "Exportar CSV" in template
    assert "/api/analytics/treatment-value-registry" in template

    command_center = Path("templates/epidemiology_command_center_v2.html").read_text(encoding="utf-8")
    assert 'data-testid="epidemiology-command-center-v2"' in command_center
    assert 'data-testid="epi-global-filters"' in command_center
    assert 'data-testid="epi-kpi-grid"' in command_center
    assert 'data-testid="epi-metric-provenance"' in command_center
    assert 'data-testid="epi-capture-impact-bridge"' in command_center
    assert 'data-testid="epi-operational-latency"' in command_center
    assert 'data-testid="epi-outcome-matrix"' in command_center
    assert 'data-testid="epi-comparison-panel"' in command_center
    assert 'data-testid="epi-completeness-tower"' in command_center
    assert 'data-testid="epi-bias-readiness"' in command_center
    assert 'data-testid="epi-economic-layer"' in command_center
    assert 'data-testid="epi-patient-trace"' in command_center
    assert 'data-testid="epi-research-workspace"' in command_center
    assert 'data-testid="epi-snapshot-pack-workspace"' in command_center
    assert 'data-testid="epi-snapshot-governance-controls"' in command_center
    assert 'data-testid="epi-freeze-snapshot"' in command_center
    assert 'data-testid="epi-export-json"' in command_center
    assert 'data-testid="epi-export-csv"' in command_center
    assert 'data-testid="epi-snapshot-json"' in command_center
    assert "/api/analytics/epidemiology-command-center" in command_center
    assert "/api/analytics/epidemiology-command-center/snapshot-pack" in command_center
    assert "/api/analytics/epidemiology-command-center/snapshot-pack/freeze" in command_center
    assert "/api/analytics/epidemiology-command-center/snapshot-pack/freezes" in command_center
    assert "reproduction-pack/download" in command_center
    assert "renderOperationalLatency" in command_center
    assert 'data-testid="epi-reproduction-pack-download"' in command_center
    assert "epiSnapshotGovernanceStatus" in command_center
    assert "epiSnapshotApprovalStatus" in command_center
    assert "epiSnapshotMethodologyVersion" in command_center
    assert "renderCaptureImpact" in command_center
    assert "initFiltersFromUrl" in command_center
    assert "epiSourceFreezeKey" in command_center
    assert "renderProvenance" in command_center
    assert "freezeSnapshot" in command_center
    assert "/population/treatment-value-registry" in command_center

    sidebar = Path("templates/components/pm2_sidebar.html").read_text(encoding="utf-8")
    assert "/population/epidemiology-command-center" in sidebar
    assert "epidemiology_command" in sidebar

    longitudinal = Path("templates/demos/longitudinal_capture_v2_demo.html").read_text(encoding="utf-8")
    assert 'data-testid="epidemiology-registry-capture"' in longitudinal
    assert 'data-testid="epidemiology-gap-sla-after-capture"' in longitudinal
    assert "pm2-readiness-lane-epidemiology_registry" in longitudinal
    assert "epidemiology_gap" in longitudinal
    assert "pm2RenderEpidemiologyGapSla" in longitudinal
    assert "form.querySelectorAll('input, select, textarea')" in longitudinal
    assert "form.querySelectorAll('input:not([type=\"hidden\"]), select, textarea')" in longitudinal
    assert "textarea[required]" in longitudinal


def test_treatment_value_registry_population_route_renders_v2(app_client):
    client, _db_path = app_client

    response = client.get("/population/treatment-value-registry")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-testid="population-treatment-value-v2"' in body
    assert 'data-testid="tv-filter-molecule"' in body
    assert "/api/analytics/treatment-value-registry" in body


def test_epidemiology_command_center_population_route_renders_v2(app_client):
    client, _db_path = app_client

    response = client.get("/population/epidemiology-command-center")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-testid="epidemiology-command-center-v2"' in body
    assert 'data-testid="epi-global-filters"' in body
    assert "/api/analytics/epidemiology-command-center" in body


def test_arpi_windows_refresh_after_longitudinal_psa_and_ecog_capture(app_client):
    client, db_path = app_client
    nss = "ARPI-AUTO-REFRESH"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO patient_identity (
                nss, full_name, dob, diagnosis_date, is_synthetic, synthetic_flag_reason
            ) VALUES (?, ?, ?, ?, 1, 'unit_test')
            """,
            (nss, "Paciente Auto Refresh ARPI", "1960-01-01", "2025-11-01"),
        )
        conn.commit()

    start = client.post(
        f"/api/patients/{nss}/treatment-course",
        json={
            "regimen_code": "ADT_ABIRATERONE",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "start_date": "2025-11-01",
            "local_doses_administered": 4,
            "unit_name": "Unidad local",
            "referral_target": "HGZ",
        },
    )
    assert start.status_code == 200

    baseline_psa = client.post(
        f"/api/longitudinal/{nss}/append",
        json={"kind": "psa", "payload": {"sample_date": "2025-11-01", "value": 100.0}},
    )
    assert baseline_psa.status_code == 200
    assert baseline_psa.get_json()["arpi_response_windows"]["windows_computed"] == 3

    actual_psa = client.post(
        f"/api/longitudinal/{nss}/append",
        json={"kind": "psa", "payload": {"sample_date": "2026-04-18", "value": 35.0}},
    )
    assert actual_psa.status_code == 200
    actual_psa_payload = actual_psa.get_json()
    assert actual_psa_payload["arpi_response_windows"]["windows_upserted"] >= 1
    capture_impact = actual_psa_payload["treatment_value_capture_impact"]
    assert capture_impact["version"] == "treatment_value_capture_impact_v1"
    assert capture_impact["after"]["patient_contributes_to_registry"] is True
    assert "treatment_value_registry_v2" in capture_impact["refreshed_surfaces"]

    ecog_baseline = client.post(
        f"/api/patients/{nss}/ecog-capture",
        json={"sample_date": "2025-11-01", "ecog_value": 2},
    )
    assert ecog_baseline.status_code == 200

    ecog_actual = client.post(
        f"/api/patients/{nss}/ecog-capture",
        json={"sample_date": "2026-04-18", "ecog_value": 1},
    )
    assert ecog_actual.status_code == 200
    assert ecog_actual.get_json()["arpi_response_windows"]["windows_upserted"] >= 1
    assert ecog_actual.get_json()["treatment_value_capture_impact"]["kind_appended"] == "ecog"

    value = client.get("/api/analytics/arpi-real-world-value?weeks=24")
    assert value.status_code == 200
    payload = value.get_json()
    row = next(item for item in payload["patient_rows"] if item["patient_ref"] == nss)
    assert row["psa_decline_pct"] == 65.0
    assert row["psa50_response"] is True
    assert row["actual_ecog_date"] == "2026-04-18"
    assert row["ecog_evidence_quality"] == "in_window"
    assert row["ecog_change_from_baseline"] == -1
    assert row["local_dose_count_to_window"] == 4
    assert row["priced_local_dose_count"] == 4
    assert row["first_priced_local_dose_date_to_window"] == "2025-11-01"
    assert row["partial_cost_dose_count"] == 4
    assert row["spend_to_window_mxn"] == 39000.0
    assert payload["summary"]["cost_per_psa50_responder_mxn"] == 39000.0
    assert payload["summary"]["cost_per_ecog_improved_patient_mxn"] == 39000.0

    registry = client.get(
        f"/api/analytics/treatment-value-registry?weeks=24&patient_ref={nss}&trace_limit=10"
    )
    assert registry.status_code == 200
    latency_domains = {
        item["key"]: item
        for item in registry.get_json()["operational_gap_latency"]["domains"]
    }
    assert latency_domains["ecog_response_window"]["source"] == "arpi_response_windows.actual_ecog_date"
    assert latency_domains["ecog_response_window"]["median_days_to_close"] == 0
    assert latency_domains["dose_cost_trace"]["source"] == "treatment_dose_administrations + medication_price_catalog"
    assert latency_domains["dose_cost_trace"]["median_days_to_close"] == 0
    before_toxicity_gaps = {
        item["gap_key"]
        for item in registry.get_json()["capture_worklist"]["items"]
        if item["patient_ref"] == nss
    }
    assert "toxicity_ctcae" in before_toxicity_gaps

    ctcae_review = client.post(
        f"/api/longitudinal/{nss}/append",
        json={
            "kind": "ctcae",
            "payload": {
                "sample_date": "2026-04-18",
                "grade": 0,
                "term": "Sin toxicidad clinica relevante",
                "toxicity_status": "sin toxicidad",
                "regimen_code": "ADT_ABIRATERONE",
            },
        },
    )
    assert ctcae_review.status_code == 200
    assert ctcae_review.get_json()["treatment_value_capture_impact"]["kind_appended"] == "ctcae"

    after_registry = client.get(
        f"/api/analytics/treatment-value-registry?weeks=24&patient_ref={nss}&include_rows=1&trace_limit=10"
    )
    assert after_registry.status_code == 200
    after_payload = after_registry.get_json()
    after_gaps = {
        item["gap_key"]
        for item in after_payload["capture_worklist"]["items"]
        if item["patient_ref"] == nss
    }
    assert "toxicity_ctcae" not in after_gaps
    after_row = after_payload["windows"]["24"]["patient_rows"][0]
    assert after_row["toxicity_event_count_to_window"] == 0
    assert after_row["toxicity_review_documented"] is True
    assert after_row["toxicity_absence_documented"] is True
    assert after_row["high_grade_toxicity_to_window"] is False
    after_latency_domains = {
        item["key"]: item
        for item in after_payload["operational_gap_latency"]["domains"]
    }
    assert after_latency_domains["toxicity_surveillance"]["source"] == "treatment_adverse_events + CTCAE_TOXICITY"
    assert after_latency_domains["toxicity_surveillance"]["median_days_to_close"] == 0
