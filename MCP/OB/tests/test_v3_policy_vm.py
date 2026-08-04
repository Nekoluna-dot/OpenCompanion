from ombrebrain.domain.commands import CommandKind
from ombrebrain.policy.contracts import CapabilityContract, SurfaceAccess, VerdictSeverity
from ombrebrain.policy.vm import PolicyInstruction, PolicyOpcode, PolicyProgram, PolicyVM


def _contract(**overrides):
    data = dict(
        command_id="cmd_1",
        command_kind=CommandKind.HOLD,
        module="tools.hold",
        operation="hold",
        permissions=("mcp:call",),
        required_permissions=("mcp:call",),
        capabilities=("tools.hold",),
        side_effects=(),
        protected_surfaces=(),
        writes_memory=False,
        projection_surfaces=("dashboard",),
        surface_access=(),
        hot_update_safe=True,
        cluster_safe=True,
    )
    data.update(overrides)
    return CapabilityContract(**data)


def test_policy_vm_allows_matching_permissions() -> None:
    program = PolicyProgram((PolicyInstruction(PolicyOpcode.REQUIRE_PERMISSION, "mcp:call"),))

    verdict = PolicyVM.default().evaluate(program, _contract())

    assert verdict.allowed is True
    assert verdict.severity == VerdictSeverity.ALLOW


def test_policy_vm_denies_missing_permission() -> None:
    program = PolicyProgram((PolicyInstruction(PolicyOpcode.REQUIRE_PERMISSION, "memory:write"),))

    verdict = PolicyVM.default().evaluate(program, _contract())

    assert verdict.allowed is False
    assert verdict.severity == VerdictSeverity.DENY
    assert "memory:write" in verdict.missing_permissions


def test_policy_vm_warns_protected_surface() -> None:
    program = PolicyProgram((PolicyInstruction(PolicyOpcode.WARN_PROTECTED_SURFACE, "buckets"),))

    verdict = PolicyVM.default().evaluate(
        program,
        _contract(protected_surfaces=("buckets",), surface_access=(SurfaceAccess("buckets", "read", protected=True),)),
    )

    assert verdict.allowed is True
    assert verdict.severity == VerdictSeverity.WARN
    assert "buckets" in verdict.protected_surfaces


def test_policy_vm_denies_protected_write() -> None:
    program = PolicyProgram((PolicyInstruction(PolicyOpcode.DENY_PROTECTED_WRITE, "buckets"),))

    verdict = PolicyVM.default().evaluate(
        program,
        _contract(writes_memory=True, surface_access=(SurfaceAccess("buckets", "write", protected=True),)),
    )

    assert verdict.allowed is False
    assert verdict.severity == VerdictSeverity.DENY


def test_policy_vm_warns_hot_update_and_cluster_unsafe() -> None:
    program = PolicyProgram(
        (
            PolicyInstruction(PolicyOpcode.WARN_HOT_UPDATE_UNSAFE, "hot_update_safe"),
            PolicyInstruction(PolicyOpcode.WARN_CLUSTER_UNSAFE, "cluster_safe"),
        )
    )

    verdict = PolicyVM.default().evaluate(program, _contract(hot_update_safe=False, cluster_safe=False))

    assert verdict.allowed is True
    assert verdict.severity == VerdictSeverity.WARN
    assert any("hot-update unsafe" in reason for reason in verdict.reasons)
    assert any("cluster unsafe" in reason for reason in verdict.reasons)
