import pytest


def test_plugin_manifest_parses_plugin_type_and_capability_flags():
    from ombrebrain.plugins import PluginManifest

    manifest = PluginManifest.from_dict(
        {
            "name": "affective-graph-projection",
            "version": "0.1.0",
            "type": "projection",
            "capabilities": {
                "read_surfaceable": True,
                "read_archive": False,
                "write_trace": False,
                "admin_erase": False,
                "issue_commands": False,
                "set_current_emotion": False,
            },
        }
    )

    assert manifest.plugin_type == "projection"
    assert manifest.capabilities == ("read_surfaceable",)
    assert manifest.to_dict()["plugin_type"] == "projection"


def test_plugin_agency_boundary_allows_infrastructure_plugin_types():
    from ombrebrain.plugins import PluginAgencyBoundary, PluginManifest

    manifest = PluginManifest.from_dict(
        {
            "name": "migration-auditor",
            "version": "1.0.0",
            "plugin_type": "migration_checker",
            "capabilities": ["read_surfaceable"],
        }
    )

    decision = PluginAgencyBoundary.default().evaluate(manifest)

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.forbidden_capabilities == ()


def test_plugin_agency_boundary_rejects_forbidden_plugin_type():
    from ombrebrain.plugins import PluginAgencyBoundary, PluginManifest

    manifest = PluginManifest.from_dict(
        {
            "name": "personality-core",
            "version": "1.0.0",
            "type": "personality_engine",
            "capabilities": ["read_surfaceable"],
        }
    )

    decision = PluginAgencyBoundary.default().evaluate(manifest)

    assert decision.allowed is False
    assert decision.reason == "forbidden plugin type"
    assert decision.forbidden_plugin_type == "personality_engine"


@pytest.mark.parametrize(
    "capability",
    [
        "issue_commands",
        "set_current_emotion",
        "create_autonomous_goal",
        "belief_updater",
        "answer_controller",
        "user_scoring",
    ],
)
def test_plugin_agency_boundary_rejects_forbidden_cognitive_capabilities(capability):
    from ombrebrain.plugins import PluginAgencyBoundary, PluginManifest

    manifest = PluginManifest.from_dict(
        {
            "name": "cognitive-plugin",
            "version": "1.0.0",
            "type": "projection",
            "capabilities": ["read_surfaceable", capability],
        }
    )

    decision = PluginAgencyBoundary.default().evaluate(manifest)

    assert decision.allowed is False
    assert capability in decision.forbidden_capabilities


def test_plugin_sandbox_uses_agency_boundary_before_registration():
    from ombrebrain.plugins import PluginManifest, PluginRuntime

    manifest = PluginManifest.from_dict(
        {
            "name": "goal-maker",
            "version": "1.0.0",
            "type": "autonomous_goal",
            "capabilities": ["read_surfaceable"],
        }
    )
    runtime = PluginRuntime.default()

    with pytest.raises(PermissionError, match="forbidden plugin type"):
        runtime.register(manifest, {"read_surfaceable": lambda payload: payload})


def test_plugin_sandbox_decision_reports_agency_denial():
    from ombrebrain.plugins import PluginManifest, PluginSandbox

    manifest = PluginManifest.from_dict(
        {
            "name": "emotion-setter",
            "version": "1.0.0",
            "type": "projection",
            "capabilities": {
                "read_surfaceable": True,
                "set_current_emotion": True,
            },
        }
    )

    decision = PluginSandbox.default().evaluate(manifest)
    data = decision.to_dict()

    assert decision.allowed is False
    assert decision.reason == "forbidden cognitive capability"
    assert data["agency"]["forbidden_capabilities"] == ["set_current_emotion"]


def test_plugins_package_exports_agency_boundary_symbols():
    from ombrebrain.plugins import PluginAgencyBoundary, PluginAgencyDecision

    assert PluginAgencyBoundary.default() is not None
    assert PluginAgencyDecision is not None
