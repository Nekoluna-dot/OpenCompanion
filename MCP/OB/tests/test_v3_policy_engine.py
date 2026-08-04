from ombrebrain.app.execution import ExecutionEnvelope
from ombrebrain.app.profiles import build_default_legacy_profiles
from ombrebrain.domain.commands import CommandKind, MemoryCommand, MemoryCommandRouter
from ombrebrain.policy.engine import PolicyEngine


def test_policy_engine_evaluates_command_plan_from_envelope() -> None:
    command = MemoryCommand.new(kind=CommandKind.HOLD, payload={"content_length": 5})
    plan = MemoryCommandRouter.default().plan(command)
    envelope = ExecutionEnvelope(module="tools.hold", operation="hold", permissions=("mcp:call",))

    verdict = PolicyEngine.default(build_default_legacy_profiles()).evaluate(envelope, plan)

    assert verdict["contract"]["command_kind"] == "hold"
    assert verdict["allowed"] in (True, False)
    assert "tool-payload-privacy" in verdict["contract"]["protected_surfaces"]
    assert "buckets" in verdict["contract"]["projection_surfaces"]


def test_policy_engine_denies_missing_required_permission() -> None:
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload={"bucket_id": "b1"})
    plan = MemoryCommandRouter.default().plan(command)
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        permissions=("mcp:call",),
        required_permissions=("memory:write",),
    )

    verdict = PolicyEngine.default(build_default_legacy_profiles()).evaluate(envelope, plan)

    assert verdict["allowed"] is False
    assert verdict["effective_allowed"] is True
    assert verdict["metadata"]["audit_only"] is True
    assert verdict["metadata"]["enforcement_mode"] == "audit"
    assert verdict["metadata"]["effective_allowed"] is True
    assert "memory:write" in verdict["missing_permissions"]


def test_policy_engine_enforce_mode_makes_policy_deny_effective() -> None:
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload={"bucket_id": "b1"})
    plan = MemoryCommandRouter.default().plan(command)
    envelope = ExecutionEnvelope(
        module="tools.trace",
        operation="trace",
        permissions=("mcp:call",),
        required_permissions=("memory:write",),
    )

    verdict = PolicyEngine.default(
        build_default_legacy_profiles(),
        enforcement_mode="enforce",
    ).evaluate(envelope, plan)

    assert verdict["allowed"] is False
    assert verdict["effective_allowed"] is False
    assert verdict["metadata"]["audit_only"] is False
    assert verdict["metadata"]["enforcement_mode"] == "enforce"
    assert verdict["metadata"]["effective_allowed"] is False


def test_policy_engine_marks_protected_projection_write_as_audit_deny() -> None:
    command = MemoryCommand.new(kind=CommandKind.MIGRATE, payload={"source": "package"})
    plan = MemoryCommandRouter.default().plan(command)
    envelope = ExecutionEnvelope(module="migrate_engine", operation="apply", permissions=("memory:write",))

    verdict = PolicyEngine.default(build_default_legacy_profiles()).evaluate(envelope, plan)

    assert verdict["allowed"] is False
    assert "buckets" in verdict["protected_surfaces"] or "vector-database" in verdict["protected_surfaces"]


def test_policy_engine_verdict_is_json_safe() -> None:
    command = MemoryCommand.new(kind=CommandKind.BREATH, payload={"query": "x"})
    plan = MemoryCommandRouter.default().plan(command)
    envelope = ExecutionEnvelope(module="tools.breath", operation="breath", permissions=("mcp:call",))

    verdict = PolicyEngine.default(build_default_legacy_profiles()).evaluate(envelope, plan)

    assert verdict["contract"]["metadata"]["profile_module"] == "tools.*"
    assert isinstance(verdict["metadata"]["program"]["instructions"], list)
