from ombrebrain.domain.commands import (
    CommandKind,
    MemoryCommand,
    MemoryCommandRouter,
    ProjectionKind,
)


def test_memory_command_id_is_deterministic_and_payload_sanitized() -> None:
    command_a = MemoryCommand.new(
        kind=CommandKind.HOLD,
        payload={"content_length": 12, "api_key": "secret"},
        actor_name="legacy-tool",
        source="tools.hold",
    )
    command_b = MemoryCommand.new(
        kind=CommandKind.HOLD,
        payload={"api_key": "secret", "content_length": 12},
        actor_name="legacy-tool",
        source="tools.hold",
    )

    assert command_a.id == command_b.id
    assert command_a.payload["api_key"] == "[REDACTED]"


def test_router_plans_hold_as_write_to_event_bucket_and_vector_projection() -> None:
    router = MemoryCommandRouter.default()
    command = MemoryCommand.new(kind=CommandKind.HOLD, payload={"content_length": 24})

    plan = router.plan(command)

    assert plan.command_kind == CommandKind.HOLD
    assert plan.writes_memory is True
    assert tuple(step.kind for step in plan.projections) == (
        ProjectionKind.FABRIC_EVENT,
        ProjectionKind.BUCKET_MARKDOWN,
        ProjectionKind.VECTOR_INDEX,
        ProjectionKind.DASHBOARD_STATE,
    )


def test_router_plans_breath_as_read_only_dashboard_projection() -> None:
    router = MemoryCommandRouter.default()
    command = MemoryCommand.new(kind=CommandKind.BREATH, payload={"query": "x"})

    plan = router.plan(command)

    assert plan.writes_memory is False
    assert tuple(step.kind for step in plan.projections) == (
        ProjectionKind.FABRIC_EVENT,
        ProjectionKind.DASHBOARD_STATE,
    )


def test_router_plans_trace_delete_to_bucket_and_vector_projection() -> None:
    router = MemoryCommandRouter.default()
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload={"delete": True, "bucket_id": "abc"})

    plan = router.plan(command)

    assert plan.writes_memory is True
    assert plan.policy_tags == ("trace-delete", "vector-delete")
    assert ProjectionKind.VECTOR_INDEX in tuple(step.kind for step in plan.projections)

