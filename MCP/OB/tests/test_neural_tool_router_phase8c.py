import pytest

from ombrebrain.domain.commands import CommandKind


def test_neural_tool_router_maps_encoding_tools():
    from ombrebrain.app.neural_router import NeuralSubsystem, NeuralToolRouter

    router = NeuralToolRouter.default()

    hold = router.route("hold")
    grow = router.route("grow")

    assert hold.public_tool == "hold"
    assert hold.subsystem == NeuralSubsystem.ENGRAM_ENCODING
    assert grow.subsystem == NeuralSubsystem.ENGRAM_ENCODING
    assert hold.command_kind == CommandKind.HOLD
    assert hold.writes_memory is True
    assert hold.may_drive_action is False


def test_neural_tool_router_maps_read_and_replay_tools():
    from ombrebrain.app.neural_router import NeuralSubsystem, NeuralToolRouter

    router = NeuralToolRouter.default()

    breath = router.route("breath")
    pulse = router.route("pulse")
    dream = router.route("dream")

    assert breath.subsystem == NeuralSubsystem.CUE_DRIVEN_SURFACING
    assert breath.surface_budget == "normal"
    assert breath.writes_memory is False
    assert "surface-policy" in breath.policy_boundaries
    assert pulse.subsystem == NeuralSubsystem.HOMEOSTATIC_MONITORING
    assert pulse.writes_memory is False
    assert dream.subsystem == NeuralSubsystem.OFFLINE_REPLAY
    assert "sedimentation-only" in dream.policy_boundaries


def test_neural_tool_router_maps_reconsolidation_and_landmark_tools():
    from ombrebrain.app.neural_router import NeuralSubsystem, NeuralToolRouter

    router = NeuralToolRouter.default()

    trace = router.route("trace")
    anchor = router.route("anchor")
    release = router.route("release")

    assert trace.subsystem == NeuralSubsystem.RECONSOLIDATION
    assert trace.command_kind == CommandKind.TRACE
    assert "append-only-reconstruction" in trace.policy_boundaries
    assert anchor.subsystem == NeuralSubsystem.LANDMARK_NETWORK
    assert release.subsystem == NeuralSubsystem.LANDMARK_NETWORK
    assert "non-cognition-boundary" in anchor.policy_boundaries


def test_neural_tool_router_maps_self_letter_and_plan_boundaries():
    from ombrebrain.app.neural_router import NeuralSubsystem, NeuralToolRouter

    router = NeuralToolRouter.default()

    self_route = router.route("I")
    letter = router.route("letter_write")
    plan = router.route("plan")

    assert self_route.public_tool == "I"
    assert self_route.subsystem == NeuralSubsystem.SELF_DESCRIPTION_MEMORY
    assert "non-cognition-boundary" in self_route.policy_boundaries
    assert letter.subsystem == NeuralSubsystem.ARTIFACT_TRACE
    assert "raw-artifact-preserved" in letter.policy_boundaries
    assert plan.subsystem == NeuralSubsystem.UNRESOLVED_TENSION_MEMORY
    assert "no-agency-boundary" in plan.policy_boundaries
    assert plan.may_drive_action is False


def test_neural_tool_route_is_json_safe_and_preserves_public_tool_name():
    from ombrebrain.app.neural_router import NeuralToolRouter

    data = NeuralToolRouter.default().route("letter_read").to_dict()

    assert data["public_tool"] == "letter_read"
    assert data["subsystem"] == "artifact_trace"
    assert data["may_drive_action"] is False
    assert isinstance(data["policy_boundaries"], list)


def test_neural_tool_router_rejects_forbidden_tool_names():
    from ombrebrain.app.neural_router import NeuralToolRouter, ToolRouteError

    router = NeuralToolRouter.default()

    with pytest.raises(ToolRouteError, match="forbidden"):
        router.route("total_recall")

    with pytest.raises(ToolRouteError, match="unknown"):
        router.route("hippocampal_recall")


def test_app_package_exports_neural_tool_router():
    from ombrebrain.app import NeuralToolRouter, NeuralSubsystem

    assert NeuralToolRouter.default() is not None
    assert NeuralSubsystem.CUE_DRIVEN_SURFACING.value == "cue_driven_surfacing"
