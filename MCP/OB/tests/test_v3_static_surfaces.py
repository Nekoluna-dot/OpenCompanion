from ombrebrain.policy.static_surfaces import StaticSurfacePolicy, SurfaceRisk


def test_static_surface_policy_classifies_frontend_dashboard() -> None:
    policy = StaticSurfacePolicy.default()

    decision = policy.classify("frontend/dashboard.html")

    assert decision.profile_module == "frontend.dashboard"
    assert decision.risk == SurfaceRisk.OPERATOR_UI
    assert decision.protected is False
    assert "host-port-form" in decision.controls
    assert "oauth-toggle" in decision.controls


def test_static_surface_policy_protects_deployment_user_overrides() -> None:
    policy = StaticSurfacePolicy.default()

    decision = policy.classify("deploy/docker-compose.user.yml")

    assert decision.profile_module == "deploy.*"
    assert decision.risk == SurfaceRisk.DEPLOYMENT
    assert decision.protected is True
    assert decision.reason == "deployment-user-overrides"


def test_static_surface_policy_marks_deploy_and_docker_as_advanced_surfaces() -> None:
    policy = StaticSurfacePolicy.default()

    compose = policy.classify("deploy/docker-compose.yml")
    dockerfile = policy.classify("Dockerfile")

    assert compose.protected is False
    assert "host-port-mapping" in compose.side_effects
    assert dockerfile.profile_module == "dockerfile"
    assert dockerfile.risk == SurfaceRisk.DEPLOYMENT


def test_static_surface_policy_allows_templates_but_identifies_config_surface() -> None:
    policy = StaticSurfacePolicy.default()

    decision = policy.classify("config.example.yaml")

    assert decision.profile_module == "config.templates"
    assert decision.protected is False
    assert "config" in decision.controls
