import importlib

from decay_engine import DecayEngine
from dehydrator import Dehydrator
from embedding_engine import EmbeddingEngine
from github_sync import GitHubSync
from import_memory import ImportEngine
from migrate_engine import MigrateEngine
from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.app.legacy_wiring import attach_v3_runtime_to_components, build_v3_runtime


def _config(tmp_path):
    return {
        "buckets_dir": str(tmp_path / "buckets"),
        "embedding": {"enabled": False},
        "dehydration": {},
        "decay": {},
    }


def test_core_legacy_engines_accept_v3_runtime_attachment(tmp_path) -> None:
    cfg = _config(tmp_path)
    embedding = EmbeddingEngine(cfg)
    dehydrator = Dehydrator(cfg)
    decay = DecayEngine(cfg, bucket_mgr=object())
    import_engine = ImportEngine(cfg, object(), dehydrator, embedding)
    migrate_engine = MigrateEngine(cfg, object(), embedding)
    github = GitHubSync(token="token", repo="owner/repo")
    runtime = LegacyRuntime.from_config(cfg)

    attached = attach_v3_runtime_to_components(
        runtime,
        embedding,
        dehydrator,
        decay,
        import_engine,
        migrate_engine,
        github,
    )

    assert attached == 6
    for component in (embedding, dehydrator, decay, import_engine, migrate_engine, github):
        assert component.v3_runtime is runtime


def test_migration_engine_module_accepts_v3_runtime_attachment(tmp_path) -> None:
    runtime = LegacyRuntime.from_config(_config(tmp_path))
    migration_engine = importlib.import_module("migration_engine")

    migration_engine.attach_v3_runtime(runtime)

    assert migration_engine.get_v3_runtime() is runtime


def test_build_v3_runtime_attaches_extra_components(tmp_path) -> None:
    class Component:
        def __init__(self):
            self.v3_runtime = None

        def attach_v3_runtime(self, runtime) -> None:
            self.v3_runtime = runtime

    component = Component()
    runtime = build_v3_runtime(_config(tmp_path), components=(component,))

    assert component.v3_runtime is runtime

