from ombrebrain.adapters.migration import migrate_bucket_tree
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.protocol.schemas import MemoryType


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_migration_converts_dynamic_and_permanent_markdown(tmp_path) -> None:
    bucket_root = tmp_path / "buckets"
    _write(bucket_root / "dynamic" / "d.md", "---\ntype: dynamic\nimportance: 4\n---\nhello dynamic")
    _write(bucket_root / "permanent" / "p.md", "---\ntype: permanent\nimportance: 9\n---\nhello permanent")
    fabric = MemoryFabric.open(tmp_path / "fabric")

    report = migrate_bucket_tree(bucket_root, fabric)

    assert tuple(item.path for item in report.converted) == ("dynamic/d.md", "permanent/p.md")
    assert report.skipped == ()
    assert report.errors == ()
    assert report.vector_rebuild_required is True
    assert [event.memory_type for event in fabric.replay_events()] == [
        MemoryType.DYNAMIC,
        MemoryType.PERMANENT,
    ]


def test_migration_skips_non_markdown_files(tmp_path) -> None:
    bucket_root = tmp_path / "buckets"
    _write(bucket_root / "letters" / "note.txt", "plain text")
    fabric = MemoryFabric.open(tmp_path / "fabric")

    report = migrate_bucket_tree(bucket_root, fabric)

    assert report.converted == ()
    assert report.skipped[0].path == "letters/note.txt"
    assert report.skipped[0].reason == "not markdown"


def test_migration_records_per_file_errors_and_continues(tmp_path) -> None:
    bucket_root = tmp_path / "buckets"
    _write(bucket_root / "dynamic" / "bad.md", "---\ntype: dynamic\nimportance: nope\n---\nbad")
    _write(bucket_root / "plans" / "ok.md", "---\ntype: plan\n---\nok")
    fabric = MemoryFabric.open(tmp_path / "fabric")

    report = migrate_bucket_tree(bucket_root, fabric)

    assert tuple(item.path for item in report.converted) == ("plans/ok.md",)
    assert report.errors[0].path == "dynamic/bad.md"
    assert "invalid literal" in report.errors[0].message
    assert [event.content for event in fabric.replay_events()] == ["ok"]


def test_migration_empty_tree_reports_no_vector_rebuild(tmp_path) -> None:
    fabric = MemoryFabric.open(tmp_path / "fabric")

    report = migrate_bucket_tree(tmp_path / "missing-buckets", fabric)

    assert report.converted == ()
    assert report.skipped == ()
    assert report.errors == ()
    assert report.vector_rebuild_required is False
