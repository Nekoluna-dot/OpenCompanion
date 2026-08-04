"""热更新重启前编译自检 + 自动回滚（谨慎加固 B2）。

裸机没有 entrypoint 守护，坏更新 execv 进去会一直崩。重启前先字节编译新代码，
不通过就从 _prev 还原、放弃重启，保住可用状态。
"""


import web.meta as meta


def test_compile_check_passes_on_good_code(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n", encoding="utf-8")
    (src / "pkg").mkdir()
    (src / "pkg" / "b.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    assert meta._compile_check_dir(str(src)) is None


def test_compile_check_catches_syntax_error(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text("ok = 1\n", encoding="utf-8")
    (src / "bad.py").write_text("def broken(:\n  pass\n", encoding="utf-8")
    err = meta._compile_check_dir(str(src))
    assert err is not None
    assert "bad.py" in err


def test_compile_check_ignores_pycache(tmp_path):
    src = tmp_path / "src"
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__" / "junk.py").write_text("def (:\n", encoding="utf-8")  # 语法错但应被忽略
    (src / "real.py").write_text("y = 2\n", encoding="utf-8")
    assert meta._compile_check_dir(str(src)) is None


def test_restore_from_prev_recovers_src_frontend_version_and_requirements(tmp_path):
    repo = tmp_path
    src = repo / "src"
    src.mkdir()
    front = repo / "frontend"
    front.mkdir()
    prev = repo / "_prev"
    (prev / "src").mkdir(parents=True)
    (prev / "frontend").mkdir(parents=True)
    (prev / "src" / "server.py").write_text("GOOD_OLD = 1\n", encoding="utf-8")
    (prev / "frontend" / "app.js").write_text("// old\n", encoding="utf-8")
    (prev / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (prev / "requirements.txt").write_text("old-dependency==1\n", encoding="utf-8")

    # 当前是坏版本
    (src / "server.py").write_text("BROKEN(:\n", encoding="utf-8")
    (front / "app.js").write_text("// broken\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("broken-dependency==9\n", encoding="utf-8")

    ok = meta._restore_from_prev(str(repo), str(prev), str(src), str(front))
    assert ok is True
    assert (src / "server.py").read_text(encoding="utf-8") == "GOOD_OLD = 1\n"
    assert (front / "app.js").read_text(encoding="utf-8") == "// old\n"
    assert (repo / "VERSION").read_text(encoding="utf-8") == "1.0.0\n"
    assert (src / "VERSION").read_text(encoding="utf-8") == "1.0.0\n"
    assert (repo / "requirements.txt").read_text(encoding="utf-8") == "old-dependency==1\n"


def test_restore_returns_false_without_prev(tmp_path):
    repo = tmp_path
    src = repo / "src"
    src.mkdir()
    front = repo / "frontend"
    front.mkdir()
    assert meta._restore_from_prev(str(repo), str(repo / "_prev"), str(src), str(front)) is False
