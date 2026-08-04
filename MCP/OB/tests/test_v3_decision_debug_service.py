import subprocess
import sys

from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.decision.debug import DecisionDebugService
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def test_decision_debug_service_lists_and_replays_runtime_records(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", payload={"query": "x"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")
    runtime.record_execution_event(envelope, outcome)

    listing = runtime.debug_decisions(limit=5)
    record = listing["records"][0]
    replay = runtime.replay_decision(record["id"])

    assert listing["ok"] is True
    assert listing["count"] == 1
    assert record["module"] == "tools.breath"
    assert replay["ok"] is True
    assert replay["replay"]["ok"] is True
    assert replay["record"]["command_id"] == record["command_id"]


def test_decision_debug_service_filters_by_module_and_operation(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})
    runtime.record_execution_event(
        ExecutionEnvelope(module="web.config_api", operation="save-port", payload={"host_port": 8001}),
        ExecutionOutcome(ok=True, phase_history=("completed",), result_type="dict"),
    )

    listing = runtime.debug_decisions(limit=10, module="web.config_api", operation="save-port")

    assert listing["count"] == 1
    assert listing["records"][0]["module"] == "web.config_api"
    assert listing["records"][0]["operation"] == "save-port"


def test_decision_debug_service_reports_missing_identifier(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    result = runtime.debug_decision("missing")

    assert result["ok"] is False
    assert result["error"] == "decision_not_found"


def test_decision_debug_service_tolerates_malformed_decision_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="test",
            memory_type=MemoryType.TRACE,
            content="bad decision metadata",
            visibility=Visibility.INTERNAL,
            source_chain=("test",),
            metadata={"decision_record": "not-a-dict"},
        )
    )

    listing = DecisionDebugService(runtime.fabric).list_records(limit=5)

    assert listing["ok"] is True
    assert listing["count"] == 0
    assert listing["problems"][0]["error"] == "invalid_decision_record"


def test_decision_debug_service_rejects_records_without_command_id(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.fabric.append_event(
        MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="test",
            memory_type=MemoryType.TRACE,
            content="partial decision metadata",
            visibility=Visibility.INTERNAL,
            source_chain=("test",),
            metadata={"decision_record": {"module": "tools.breath", "operation": "breath"}},
        )
    )

    listing = DecisionDebugService(runtime.fabric).list_records(limit=5)

    assert listing["count"] == 0
    assert listing["problems"][0]["error"] == "invalid_decision_record"
    assert "command id" in listing["problems"][0]["reason"]


def test_decision_debug_reads_are_side_effect_free(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    runtime.record_tool_event("breath", {"query": "x"})
    before = runtime.fabric.next_index()
    record_id = runtime.debug_decisions(limit=1)["records"][0]["id"]

    runtime.debug_decision(record_id)
    runtime.replay_decision(record_id)

    assert runtime.fabric.next_index() == before


def test_debug_decision_cli_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "tools/debug_decision.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "list" in result.stdout
    assert "replay" in result.stdout
