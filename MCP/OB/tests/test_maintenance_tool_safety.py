import importlib.util
from pathlib import Path
import sqlite3

import frontmatter
import pytest



def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"maintenance_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnose = _load_script("diagnose_permanent_reads")
permanent_fix = _load_script("fix_unpinned_permanent")
feel_migration = _load_script("migrate_feel_domain")


@pytest.mark.asyncio
async def test_feel_migration_is_read_only_by_default(monkeypatch):
    class Manager:
        updated = []

        async def list_all(self, include_archive=False):
            assert include_archive is True
            return [{"id": "feel-1", "metadata": {"type": "feel", "domain": []}}]

        async def update(self, bucket_id, **updates):
            self.updated.append((bucket_id, updates))

    manager = Manager()
    monkeypatch.setattr(feel_migration, "load_config", lambda: {})
    monkeypatch.setattr(feel_migration, "BucketManager", lambda _config: manager)

    await feel_migration.main()

    assert manager.updated == []


@pytest.mark.asyncio
async def test_permanent_fix_dry_run_preserves_bucket_bytes(monkeypatch, tmp_path):
    permanent_dir = tmp_path / "permanent"
    permanent_dir.mkdir()
    bucket_path = permanent_dir / "memory.md"
    post = frontmatter.Post(
        "verbatim memory",
        id="memory-1",
        name="Memory",
        type="permanent",
        pinned=False,
        protected=False,
    )
    bucket_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    original = bucket_path.read_bytes()

    class Manager:
        def __init__(self):
            self.dynamic_dir = str(tmp_path / "dynamic")
            self.permanent_dir = str(permanent_dir)

        def _move_bucket(self, *_args):
            pytest.fail("dry-run must not move bucket files")

    monkeypatch.setattr(permanent_fix, "load_config", lambda: {})
    monkeypatch.setattr(permanent_fix, "BucketManager", lambda _config: Manager())

    await permanent_fix.audit(force_demote=False)

    assert bucket_path.read_bytes() == original


def test_diagnostic_reads_embedding_database_without_mutating_it(tmp_path):
    db_path = tmp_path / "embeddings.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE embeddings (bucket_id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO embeddings VALUES ('memory-1')")
    connection.commit()
    connection.close()
    original = db_path.read_bytes()

    ids = diagnose._read_embedding_ids({
        "buckets_dir": str(tmp_path),
        "embedding": {"db_path": str(db_path)},
    })

    assert ids == {"memory-1"}
    assert db_path.read_bytes() == original
