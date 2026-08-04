import sqlite3

import frontmatter

from vault_health import inspect_vault


def _write(path, bucket_id, content="memory"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        frontmatter.dumps(frontmatter.Post(content, id=bucket_id, type="dynamic")),
        encoding="utf-8",
    )


def _db(path, ids=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE embeddings (
                bucket_id TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.executemany(
            "INSERT INTO embeddings VALUES (?, '[0.1]', 'now', 'hash')",
            [(item,) for item in ids],
        )


def test_vault_health_reports_clean_source_and_projection(tmp_path):
    vault = tmp_path / "vault"
    _write(vault / "dynamic" / "general" / "one.md", "one")
    db = vault / "embeddings.db"
    _db(db, ["one"])

    report = inspect_vault(str(vault), str(db))

    assert report["status"] == "ok"
    assert report["markdown"]["file_count"] == 1
    assert report["sqlite"]["quick_check_ok"] is True
    assert report["sqlite"]["missing_unqueued_count"] == 0


def test_vault_health_distinguishes_pending_missing_and_orphan_vectors(tmp_path):
    vault = tmp_path / "vault"
    _write(vault / "dynamic" / "general" / "one.md", "one")
    _write(vault / "dynamic" / "general" / "two.md", "two")
    db = vault / "embeddings.db"
    _db(db, ["one", "gone"])

    queued = inspect_vault(str(vault), str(db), pending_ids={"two"})
    assert queued["status"] == "warning"
    assert queued["sqlite"]["orphan_ids"] == ["gone"]
    assert queued["sqlite"]["missing_active_ids"] == ["two"]
    assert queued["sqlite"]["missing_unqueued_count"] == 0

    unqueued = inspect_vault(str(vault), str(db))
    assert unqueued["sqlite"]["missing_unqueued_ids"] == ["two"]


def test_vault_health_reports_parse_errors_and_duplicate_ids(tmp_path):
    vault = tmp_path / "vault"
    _write(vault / "dynamic" / "general" / "one.md", "same")
    _write(vault / "archive" / "general" / "old.md", "same")
    bad = vault / "dynamic" / "general" / "bad.md"
    bad.write_bytes(b"\xff\xfe")

    report = inspect_vault(str(vault), str(vault / "missing.db"))

    assert report["status"] == "error"
    assert report["markdown"]["duplicate_id_count"] == 1
    assert report["markdown"]["parse_error_count"] == 1
