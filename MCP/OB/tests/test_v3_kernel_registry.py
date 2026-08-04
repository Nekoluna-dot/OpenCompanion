import json

import pytest

from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.errors import CapabilityLoadError, PolicyViolation
from ombrebrain.kernel.registry import CapabilityManifest, CapabilityRegistry


def test_registry_registers_and_returns_manifest():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(
        name="memory.write",
        version="3.0.0",
        permissions=("memory:write",),
        writes_memory=True,
        cluster_safe=True,
    )

    registry.register(manifest, handler=lambda context, payload: {"ok": True})

    assert registry.get("memory.write").manifest == manifest


def test_capability_manifest_hot_update_safe_defaults_false_and_can_be_enabled():
    default_manifest = CapabilityManifest(name="memory.read", version="3.0.0")
    safe_manifest = CapabilityManifest(name="memory.cache", version="3.0.0", hot_update_safe=True)

    assert default_manifest.hot_update_safe is False
    assert safe_manifest.hot_update_safe is True


def test_registry_rejects_duplicate_capability():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(name="mcp.search", version="3.0.0")
    registry.register(manifest, handler=lambda context, payload: payload)

    with pytest.raises(CapabilityLoadError):
        registry.register(manifest, handler=lambda context, payload: payload)


def test_dispatch_requires_permission():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(name="memory.write", version="3.0.0", permissions=("memory:write",))
    registry.register(manifest, handler=lambda context, payload: payload)
    context = OmbreContext(request_id="r1", actor_name="tester", permissions=())

    with pytest.raises(PolicyViolation):
        registry.dispatch("memory.write", context, {"content": "blocked"})


def test_dispatch_returns_handler_result_when_allowed():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(name="memory.write", version="3.0.0", permissions=("memory:write",))
    registry.register(manifest, handler=lambda context, payload: {"actor": context.actor_name, **payload})
    context = OmbreContext(request_id="r1", actor_name="tester", permissions=("memory:write",))

    assert registry.dispatch("memory.write", context, {"content": "stored"}) == {
        "actor": "tester",
        "content": "stored",
    }


def test_registry_rejects_missing_dependencies():
    registry = CapabilityRegistry()
    manifest = CapabilityManifest(name="memory.read", version="3.0.0", dependencies=("memory.index",))

    with pytest.raises(CapabilityLoadError):
        registry.register(manifest, handler=lambda context, payload: payload)


def test_context_safe_config_redacts_sensitive_keys():
    context = OmbreContext(
        request_id="r1",
        actor_name="tester",
        permissions=("config:read",),
        config_snapshot={
            "api_key": "secret",
            "nested": {"access_token": "token", "public": "visible"},
            "plain": "kept",
        },
    )

    assert context.safe_config() == {
        "api_key": "***",
        "nested": {"access_token": "***", "public": "visible"},
        "plain": "kept",
    }


def test_context_safe_config_redacts_nested_sensitive_keys():
    context = OmbreContext(
        request_id="r1",
        actor_name="tester",
        config_snapshot={
            "api_key": "abc",
            "database": {"password": "pw", "host": "localhost"},
            "providers": [{"credential_file": "secret.json", "name": "local"}],
        },
    )

    safe = context.safe_config()

    assert safe["api_key"] == "***"
    assert safe["database"]["password"] == "***"
    assert safe["database"]["host"] == "localhost"
    assert safe["providers"][0]["credential_file"] == "***"
    assert safe["providers"][0]["name"] == "local"


def test_context_safe_config_redacts_headers_without_mutating_source_and_stays_json_serializable():
    raw = {
        "headers": {
            "Authorization": "Bearer abc",
            "Cookie": "sid=1",
            "set-cookie": "sid=2",
        },
        "items": ({"password": "pw", "name": "ok"},),
    }
    context = OmbreContext(request_id="r1", actor_name="tester", config_snapshot=raw)

    safe = context.safe_config()

    assert raw["headers"]["Authorization"] == "Bearer abc"
    assert raw["headers"]["Cookie"] == "sid=1"
    assert raw["headers"]["set-cookie"] == "sid=2"
    assert raw["items"][0]["password"] == "pw"
    assert safe["headers"]["Authorization"] == "***"
    assert safe["headers"]["Cookie"] == "***"
    assert safe["headers"]["set-cookie"] == "***"
    assert safe["items"][0]["password"] == "***"
    assert safe["items"][0]["name"] == "ok"
    json.dumps(safe)


def test_kernel_package_exports_core_types():
    from ombrebrain.kernel import OmbreContext as ExportedContext
    from ombrebrain.kernel import CapabilityManifest as ExportedManifest
    from ombrebrain.kernel import CapabilityRegistry as ExportedRegistry

    assert ExportedContext is OmbreContext
    assert ExportedManifest is CapabilityManifest
    assert ExportedRegistry is CapabilityRegistry
