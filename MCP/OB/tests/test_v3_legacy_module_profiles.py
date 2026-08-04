from ombrebrain.app.profiles import build_default_legacy_profiles


def test_default_profiles_cover_remaining_core_modules() -> None:
    registry = build_default_legacy_profiles()

    for name in (
        "decay_engine",
        "dehydrator",
        "embedding_engine",
        "import_memory",
        "migrate_engine",
        "migration_engine",
        "github_sync",
    ):
        profile = registry.get(name)
        assert profile.module == name
        assert profile.files
        assert profile.behavior_contract == "external-behavior-stable"


def test_default_profiles_cover_tools_web_frontend_and_deploy_surfaces() -> None:
    registry = build_default_legacy_profiles()

    for name in (
        "tools.*",
        "web.*",
        "frontend.dashboard",
        "deploy.*",
        "dockerfile",
        "config.templates",
    ):
        assert registry.get(name).module == name

    deploy_profile = registry.get("deploy.*")
    assert "deployment-user-overrides" in deploy_profile.protected_surfaces
    assert "host-port-mapping" in deploy_profile.side_effects


def test_profile_registry_can_find_profiles_by_file_path() -> None:
    registry = build_default_legacy_profiles()

    assert registry.profile_for_path("src/tools/breath/__init__.py").module == "tools.*"
    assert registry.profile_for_path("frontend/dashboard.html").module == "frontend.dashboard"
    assert registry.profile_for_path("deploy/docker-compose.yml").module == "deploy.*"

