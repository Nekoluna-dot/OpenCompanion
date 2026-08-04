from pathlib import Path

from ombrebrain.maintenance.code_fingerprint import fingerprint_code_tree


def _tree(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "src" / "server.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "frontend" / "dashboard.html").write_text("<h1>one</h1>\n", encoding="utf-8")


def test_fingerprint_is_stable_and_content_sensitive(tmp_path):
    _tree(tmp_path)

    first = fingerprint_code_tree(tmp_path)
    second = fingerprint_code_tree(tmp_path)
    (tmp_path / "src" / "server.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed = fingerprint_code_tree(tmp_path)

    assert first == second
    assert changed != first
    assert len(first) == 64


def test_fingerprint_includes_relative_paths(tmp_path):
    _tree(tmp_path)
    original = fingerprint_code_tree(tmp_path)
    source = tmp_path / "src" / "server.py"
    renamed = tmp_path / "src" / "renamed.py"
    source.rename(renamed)

    assert fingerprint_code_tree(tmp_path) != original


def test_fingerprint_ignores_runtime_bytecode(tmp_path):
    _tree(tmp_path)
    original = fingerprint_code_tree(tmp_path)
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir()
    (cache / "server.cpython-312.pyc").write_bytes(b"generated")

    assert fingerprint_code_tree(tmp_path) == original
