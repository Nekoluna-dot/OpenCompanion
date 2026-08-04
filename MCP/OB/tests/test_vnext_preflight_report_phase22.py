from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def test_vnext_preflight_report_summarizes_new_contracts(tmp_path):
    from ombrebrain.maintenance import VNextPreflightReportBuilder

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    report = VNextPreflightReportBuilder(runtime).build()

    assert report["ok"] is True
    assert report["summary"]["ok"] == report["check_count"]
    assert report["summary"]["error"] == 0
    assert report["checks"]["public_tools"]["ok"] is True
    assert report["checks"]["ledger_mirror"]["ok"] is True
    assert report["checks"]["trace_catalog_projection"]["ok"] is True
    assert report["checks"]["sqlite_projection"]["ok"] is True
    assert report["checks"]["vector_projection"]["ok"] is True
    assert report["checks"]["ledger_replay"]["ok"] is True
    assert report["checks"]["ledger_property"]["ok"] is True
    assert report["checks"]["ledger_property"]["checked_events"] == 100
    assert report["checks"]["rust_kernel_scaffold"]["ok"] is True
    assert report["checks"]["policy_verdicts"]["ok"] is True
    assert report["checks"]["plugin_capability_enforcement"]["ok"] is True
    assert report["checks"]["formal_invariants"]["ok"] is True
    assert report["checks"]["context_serialization"]["ok"] is True
    assert report["checks"]["tool_output_humility"]["ok"] is True
    assert report["checks"]["tool_output_humility"]["receipt"]["route"]["subsystem"] == "cue_driven_surfacing"
    assert report["checks"]["tool_output_humility"]["receipt"]["route"]["scope"]["source"] == "mcp"
    assert report["checks"]["retrieval_scoring"]["ok"] is True
    assert report["checks"]["retrieval_scoring"]["hidden_score"]["surface_score"] == 0.0
    assert report["checks"]["retrieval_scoring"]["ranked"][0]["bucket_id"] == "visible"
    assert report["checks"]["code_standards"]["ok"] is True
    assert report["checks"]["command_boundary"]["ok"] is True
    assert report["checks"]["runtime_command_boundary"]["ok"] is True
    assert report["checks"]["runtime_command_boundary"]["receipt_count"] == 0
    assert report["checks"]["observability_boundary"]["ok"] is True
    assert report["checks"]["crash_recovery"]["ok"] is True
    assert report["checks"]["replication_contract"]["ok"] is True
    assert report["checks"]["migration_preservation"]["ok"] is True
    assert report["checks"]["surface_context"]["ok"] is True
    assert report["checks"]["surface_context"]["compiler_version"] == "surface-context.v1"
    assert report["checks"]["surface_context"]["formal_invariants"]["ok"] is True
    assert report["checks"]["surface_context"]["bundle"]["items"][0]["instructional_force"] == "none"
    assert report["checks"]["adr_requirements"]["ok"] is True
    assert report["checks"]["red_lines"]["ok"] is True
    assert report["checks"]["preflight_cli_diagnostics"]["ok"] is True
    assert report["checks"]["preflight_coverage_expansion"]["ok"] is True
    assert report["checks"]["preflight_report_self"]["ok"] is True
    assert report["checks"]["vnext_coverage"]["ok"] is True
    assert report["checks"]["vnext_coverage"]["schema"] == "vnext-coverage.v1"
    assert report["checks"]["vnext_coverage"]["phase_count"] >= 30
    assert report["checks"]["vnext_coverage"]["local_completion_percent"] == 100.0
    assert report["checks"]["vnext_coverage"]["preflight_covered_count"] == report["checks"]["vnext_coverage"]["phase_count"]
    assert report["checks"]["vnext_coverage"]["preflight_gap_count"] == 0
    assert report["checks"]["vnext_coverage"]["preflight_coverage_percent"] == 100.0
    assert not any(item["phase_key"] == "phase_1" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_5b" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_6a" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_7a" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_7c" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_22" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_23" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_25" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert not any(item["phase_key"] == "phase_26" for item in report["checks"]["vnext_coverage"]["preflight_gaps"])
    assert report["checks"]["vnext_coverage"]["next_preflight_targets"] == []


def test_vnext_preflight_report_evaluates_runtime_command_boundary_receipts(tmp_path):
    from ombrebrain.maintenance import VNextPreflightReportBuilder

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_execution_event(
        ExecutionEnvelope(module="tools.hold", operation="hold", payload={"content_length": 5}),
        ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str"),
    )

    report = VNextPreflightReportBuilder(runtime).build()
    check = report["checks"]["runtime_command_boundary"]

    assert report["ok"] is True
    assert check["ok"] is True
    assert check["status"] == "ok"
    assert check["candidate_event_count"] == 1
    assert check["receipt_count"] == 1
    assert check["invalid_receipt_count"] == 0
    assert check["reports"][0]["ok"] is True
    assert check == runtime.debug_command_boundary_health()


def test_vnext_preflight_report_warns_about_legacy_events_without_boundary_receipts(tmp_path):
    from ombrebrain.maintenance import VNextPreflightReportBuilder

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content="legacy operation without command boundary",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_execution", "tools.hold", "hold"),
            metadata={
                "command_plan": {
                    "command_id": "cmd_old",
                    "command_kind": "hold",
                    "writes_memory": True,
                    "policy_tags": [],
                    "projections": [],
                }
            },
        )
    )

    report = VNextPreflightReportBuilder(runtime).build()
    check = report["checks"]["runtime_command_boundary"]

    assert report["ok"] is True
    assert report["summary"]["warning"] == 1
    assert check["ok"] is True
    assert check["status"] == "warning"
    assert check["missing_receipt_count"] == 1


def test_vnext_preflight_report_rejects_invalid_runtime_command_boundary_receipts(tmp_path):
    from ombrebrain.maintenance import VNextPreflightReportBuilder

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content="legacy operation with bad command boundary",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_execution", "tools.hold", "hold"),
            metadata={
                "command_boundary": {
                    "receipt": {
                        "command_id": "cmd_bad",
                        "command_kind": "hold",
                        "stages": ["command", "policy_preflight", "receipt"],
                        "events": [],
                        "ledger_appended": False,
                    }
                }
            },
        )
    )

    report = VNextPreflightReportBuilder(runtime).build()
    check = report["checks"]["runtime_command_boundary"]

    assert report["ok"] is False
    assert report["summary"]["error"] == 1
    assert check["ok"] is False
    assert check["status"] == "error"
    assert check["invalid_receipt_count"] == 1
    assert {issue["code"] for issue in check["issues"]} >= {"mutation_without_events", "mutation_without_ledger_append"}


def test_vnext_preflight_report_detects_red_line_override(tmp_path):
    from ombrebrain.maintenance import VNextPreflightReportBuilder
    from ombrebrain.policy import RedLineFeatureSpec

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    report = VNextPreflightReportBuilder(runtime).build(
        red_line_features=[
            RedLineFeatureSpec(name="unsafe", claims=("total recall through ordinary API",)),
        ]
    )

    assert report["ok"] is False
    assert report["summary"]["error"] == 1
    assert report["checks"]["red_lines"]["ok"] is False
    assert report["checks"]["red_lines"]["violation_count"] == 1


def test_v3_maintenance_report_includes_vnext_preflight(tmp_path):
    from ombrebrain.maintenance.report import V3MaintenanceReportBuilder

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    report = V3MaintenanceReportBuilder(runtime).build()

    assert "vnext_preflight" in report
    assert report["vnext_preflight"]["ok"] is True
    assert report["ok"] is True


def test_maintenance_package_exports_vnext_preflight_builder():
    from ombrebrain.maintenance import VNextCoverageMatrix, VNextPreflightReportBuilder

    assert VNextPreflightReportBuilder is not None
    coverage = VNextCoverageMatrix.default().evaluate({"formal_invariants": {}, "red_lines": {}})
    assert coverage["schema"] == "vnext-coverage.v1"
    assert coverage["phase_count"] >= 30
    assert coverage["preflight_gap_count"] >= 1
    assert coverage["preflight_gaps"][0]["phase_key"] == "phase_1"
    assert any(item["phase_key"] == "phase_1" for item in coverage["items"])
    assert any(item["phase_key"] == "phase_25" for item in coverage["items"])
    assert any(item["phase_key"] == "phase_26" for item in coverage["items"])
