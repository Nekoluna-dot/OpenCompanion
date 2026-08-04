from __future__ import annotations

import pytest

from ombrebrain.plugins import PluginManifest, PluginRuntime, PluginSandbox
from ombrebrain.kernel.errors import PolicyViolation


def test_plugin_manifest_parses_capabilities_and_surfaces() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "weather-easter-egg",
            "version": "1.0.0",
            "capabilities": ["tools.breath"],
            "requested_surfaces": ["memory_fabric"],
            "side_effect_mode": "write_side_channel",
        }
    )

    assert manifest.name == "weather-easter-egg"
    assert manifest.capabilities == ("tools.breath",)
    assert manifest.requested_surfaces == ("memory_fabric",)


def test_plugin_sandbox_rejects_protected_legacy_writes() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "unsafe-writer",
            "version": "1.0.0",
            "capabilities": ["tools.trace"],
            "requested_surfaces": ["buckets"],
            "side_effect_mode": "write_legacy_state",
        }
    )

    decision = PluginSandbox.default().evaluate(manifest)

    assert decision.allowed is False
    assert decision.reason == "protected surface legacy write rejected"
    assert "buckets" in decision.protected_surfaces


def test_plugin_runtime_executes_declared_read_only_handler() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "reader",
            "version": "1.0.0",
            "capabilities": ["tools.search"],
            "requested_surfaces": [],
            "side_effect_mode": "read_only",
        }
    )
    runtime = PluginRuntime.default()
    runtime.register(manifest, {"tools.search": lambda payload: {"ok": True, "payload": payload}})

    result = runtime.execute("reader", "tools.search", {"query": "x"})

    assert result == {"ok": True, "payload": {"query": "x"}}


def test_plugin_runtime_rejects_undeclared_capability_execution() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "reader",
            "version": "1.0.0",
            "capabilities": ["tools.search"],
            "requested_surfaces": [],
            "side_effect_mode": "read_only",
        }
    )
    runtime = PluginRuntime.default()
    runtime.register(manifest, {"tools.search": lambda payload: payload})

    with pytest.raises(PermissionError):
        runtime.execute("reader", "tools.breath", {"query": "x"})


def test_plugin_runtime_audit_mode_records_missing_capability_permissions_without_blocking() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "breath-reader",
            "version": "1.0.0",
            "capabilities": ["tools.breath"],
            "requested_surfaces": [],
            "side_effect_mode": "write_side_channel",
        }
    )
    calls: list[dict[str, object]] = []
    runtime = PluginRuntime.default()
    runtime.register(manifest, {"tools.breath": lambda payload: calls.append(payload) or {"ok": True}})

    result = runtime.execute("breath-reader", "tools.breath", {"query": "x"})
    decision = runtime.last_execution_decision()

    assert result == {"ok": True}
    assert calls == [{"query": "x"}]
    assert decision is not None
    assert decision.allowed is False
    assert decision.effective_allowed is True
    assert decision.audit_only is True
    assert "tools:breath" in decision.missing_permissions
    assert "memory:write" in decision.missing_permissions
    assert "buckets" in decision.protected_surfaces


def test_plugin_runtime_enforce_mode_blocks_missing_capability_permission() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "breath-reader",
            "version": "1.0.0",
            "capabilities": ["tools.breath"],
            "requested_surfaces": [],
            "side_effect_mode": "write_side_channel",
        }
    )
    calls: list[dict[str, object]] = []
    runtime = PluginRuntime.default(enforcement_mode="enforce")
    runtime.register(manifest, {"tools.breath": lambda payload: calls.append(payload) or {"ok": True}})

    with pytest.raises(PolicyViolation, match="plugin policy denied"):
        runtime.execute("breath-reader", "tools.breath", {"query": "x"})

    decision = runtime.last_execution_decision()
    assert calls == []
    assert decision is not None
    assert decision.allowed is False
    assert decision.effective_allowed is False
    assert decision.audit_only is False
    assert "tools:breath" in decision.missing_permissions


def test_plugin_runtime_enforce_mode_allows_when_scope_has_required_permissions() -> None:
    manifest = PluginManifest.from_dict(
        {
            "name": "breath-reader",
            "version": "1.0.0",
            "capabilities": ["tools.breath"],
            "requested_surfaces": [],
            "side_effect_mode": "write_side_channel",
        }
    )
    runtime = PluginRuntime.default(enforcement_mode="enforce")
    runtime.register(manifest, {"tools.breath": lambda payload: {"ok": True, "payload": payload}})

    result = runtime.execute(
        "breath-reader",
        "tools.breath",
        {"query": "x"},
        permissions=("tools:breath", "memory:write"),
        actor_name="plugin-test",
        source="tests",
    )
    decision = runtime.last_execution_decision()

    assert result == {"ok": True, "payload": {"query": "x"}}
    assert decision is not None
    assert decision.allowed is True
    assert decision.effective_allowed is True
    assert decision.audit_only is False
    assert decision.missing_permissions == ()
