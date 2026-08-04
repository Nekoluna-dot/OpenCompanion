from ombrebrain.app.command_bridge import LegacyCommandBridge
from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.domain.commands import CommandKind, ProjectionKind


def test_legacy_command_bridge_maps_tool_modules_to_command_kinds() -> None:
    bridge = LegacyCommandBridge.default()

    hold = bridge.plan_from_envelope(ExecutionEnvelope(module="tools.hold", operation="hold"))
    breath = bridge.plan_from_envelope(ExecutionEnvelope(module="tools.breath", operation="breath"))
    trace = bridge.plan_from_envelope(ExecutionEnvelope(module="tools.trace", operation="trace"))

    assert hold.command_kind == CommandKind.HOLD
    assert breath.command_kind == CommandKind.BREATH
    assert trace.command_kind == CommandKind.TRACE


def test_legacy_command_bridge_maps_web_and_github_surfaces() -> None:
    bridge = LegacyCommandBridge.default()

    web = bridge.plan_from_envelope(ExecutionEnvelope(module="web.config_api", operation="save-port"))
    sync = bridge.plan_from_envelope(ExecutionEnvelope(module="github_sync", operation="sync"))

    assert web.command_kind == CommandKind.WEB_ROUTE
    assert sync.command_kind == CommandKind.SYNC
    assert ProjectionKind.EXTERNAL_NETWORK in tuple(step.kind for step in sync.projections)


def test_runtime_execution_event_includes_command_plan_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})
    envelope = ExecutionEnvelope(module="tools.hold", operation="hold", payload={"content_length": 8})

    runtime.record_execution_event(
        envelope,
        ExecutionOutcome(ok=True, phase_history=("received", "completed"), result_type="str"),
    )

    event = runtime.fabric.replay_events()[0]
    command_plan = event.metadata["command_plan"]
    assert command_plan["command_kind"] == CommandKind.HOLD.value
    assert command_plan["writes_memory"] is True
    assert command_plan["projections"][1]["kind"] == ProjectionKind.BUCKET_MARKDOWN.value
