from ombrebrain.domain.commands import CommandKind
from ombrebrain.policy.contracts import CapabilityContract, SurfaceAccess, SurfaceAccessVerdict, VerdictSeverity


def test_capability_contract_is_json_safe() -> None:
    contract = CapabilityContract(
        command_id="cmd_1",
        command_kind=CommandKind.HOLD,
        module="tools.hold",
        operation="hold",
        permissions=("mcp:call",),
        required_permissions=("mcp:call",),
        capabilities=("tools.hold",),
        side_effects=("bucket-create",),
        protected_surfaces=("tool-payload-privacy",),
        writes_memory=True,
        projection_surfaces=("buckets",),
        surface_access=(SurfaceAccess(surface="buckets", access="write", protected=False),),
        metadata={"nested": {"ok": True}},
    )

    data = contract.to_dict()

    assert data["command_kind"] == "hold"
    assert data["permissions"] == ["mcp:call"]
    assert data["surface_access"][0]["surface"] == "buckets"
    assert data["metadata"] == {"nested": {"ok": True}}


def test_surface_access_verdict_serializes_missing_permissions() -> None:
    verdict = SurfaceAccessVerdict(
        allowed=False,
        severity=VerdictSeverity.DENY,
        reasons=("missing permission",),
        required_permissions=("memory:write",),
        missing_permissions=("memory:write",),
        protected_surfaces=("buckets",),
        projection_surfaces=("buckets",),
    )

    data = verdict.to_dict()

    assert data["allowed"] is False
    assert data["severity"] == "deny"
    assert data["missing_permissions"] == ["memory:write"]
    assert data["protected_surfaces"] == ["buckets"]


def test_policy_package_exports_policy_vm_symbols() -> None:
    from ombrebrain.policy import CapabilityContract, PolicyEngine, PolicyVM

    assert CapabilityContract is not None
    assert PolicyEngine is not None
    assert PolicyVM is not None
