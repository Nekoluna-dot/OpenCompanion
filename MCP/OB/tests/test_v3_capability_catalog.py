from ombrebrain.capabilities.catalog import foundation_capabilities, register_foundation_capabilities
from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.registry import CapabilityRegistry


def test_foundation_capability_catalog_contains_expected_names() -> None:
    manifests = foundation_capabilities()

    assert tuple(manifest.name for manifest in manifests) == (
        "deployment.local",
        "mcp.aggregate",
        "tools.search",
        "tools.breath",
        "web.dashboard",
        "oauth.control",
        "hot_update.apply",
    )


def test_foundation_capability_dependencies_come_before_dependents() -> None:
    manifests = foundation_capabilities()
    positions = {manifest.name: index for index, manifest in enumerate(manifests)}

    for manifest in manifests:
        for dependency in manifest.dependencies:
            assert positions[dependency] < positions[manifest.name]


def test_foundation_capabilities_declare_update_and_cluster_safety() -> None:
    by_name = {manifest.name: manifest for manifest in foundation_capabilities()}

    assert by_name["mcp.aggregate"].hot_update_safe is True
    assert by_name["tools.search"].cluster_safe is True
    assert by_name["tools.breath"].writes_memory is True
    assert by_name["oauth.control"].hot_update_safe is False
    assert by_name["hot_update.apply"].cluster_safe is False


def test_register_foundation_capabilities_dispatches_manifest_metadata() -> None:
    registry = CapabilityRegistry()
    registered = register_foundation_capabilities(registry)
    context = OmbreContext(
        request_id="req",
        actor_name="codex",
        permissions=tuple(
            permission
            for manifest in foundation_capabilities()
            for permission in manifest.permissions
        ),
    )

    payload = registry.dispatch("tools.search", context, {"query": "permanent"})

    assert registered == tuple(manifest.name for manifest in foundation_capabilities())
    assert registry.names() == tuple(sorted(registered))
    assert payload["name"] == "tools.search"
    assert payload["writes_memory"] is False
    assert payload["payload"] == {"query": "permanent"}
