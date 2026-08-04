from __future__ import annotations

from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.domain.commands import CommandKind, MemoryCommand, MemoryCommandRouter
from ombrebrain.eventsourcing import EventSourcedMemoryKernel
from ombrebrain.protocol.schemas import MemoryType


def test_event_sourced_kernel_builds_command_event_projection_envelope() -> None:
    command = MemoryCommand.new(kind=CommandKind.HOLD, payload={"bucket_id": "b1", "content": "hello"})
    plan = MemoryCommandRouter.default().plan(command)

    envelope = EventSourcedMemoryKernel.default().prepare(
        module="tools.hold",
        operation="hold",
        command_plan=plan,
        legacy_metadata={"bucket_id": "b1"},
    )

    assert envelope.event.memory_type == MemoryType.TRACE
    assert envelope.event.metadata["event_sourced"]["command_id"] == plan.command_id
    assert envelope.event.metadata["event_sourced"]["mode"] == "command_event_projection"
    assert tuple(mutation.surface for mutation in envelope.projection_batch) == (
        "memory_fabric",
        "buckets",
        "embeddings",
        "dashboard",
    )


def test_event_sourced_kernel_serializes_json_safe_metadata() -> None:
    command = MemoryCommand.new(kind="breath", payload={"query": {"nested": {"x": 1}}})
    plan = MemoryCommandRouter.default().plan(command)

    envelope = EventSourcedMemoryKernel.default().prepare(
        module="tools.breath",
        operation="breath",
        command_plan=plan,
        legacy_metadata={"non_json": object()},
    )

    data = envelope.to_dict()

    assert data["event"]["metadata"]["event_sourced"]["legacy_metadata"]["non_json"].startswith("<object")
    assert data["projection_batch"][0]["surface"] == "memory_fabric"


def test_legacy_runtime_trace_events_include_event_sourced_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent"})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["event_sourced_kernel"]["command_id"] == metadata["command_plan"]["command_id"]
    assert metadata["event_sourced_kernel"]["mode"] == "command_event_projection"
    assert metadata["event_sourced_kernel"]["projection_count"] == len(metadata["command_plan"]["projections"])


def test_legacy_runtime_execution_events_include_event_sourced_metadata(tmp_path) -> None:
    from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome

    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.hold", operation="hold", payload={"bucket_id": "b1"})
    outcome = ExecutionOutcome(ok=True, phase_history=("completed",), result_type="str")

    runtime.record_execution_event(envelope, outcome)

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["event_sourced_kernel"]["module"] == "tools.hold"
    assert metadata["event_sourced_kernel"]["operation"] == "hold"
