"""记忆桶原子写回归测试（记忆安全红蓝测试）。

普通 open("w") 写到一半被杀 / 断电会把整条记忆截断。改用 tmp + os.replace 原子写，
保证读者/崩溃只看到「旧的完整版」或「新的完整版」，绝不半截。
"""
import os

import pytest

from bucket_manager import _atomic_write_text


def test_writes_content(tmp_path):
    p = tmp_path / "sub" / "mem.md"
    _atomic_write_text(str(p), "hello 记忆")
    assert p.read_text(encoding="utf-8") == "hello 记忆"


def test_no_tmp_left_after_success(tmp_path):
    p = tmp_path / "mem.md"
    _atomic_write_text(str(p), "x")
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []


def test_overwrites_fully(tmp_path):
    p = tmp_path / "mem.md"
    _atomic_write_text(str(p), "老的完整内容啊啊啊啊")
    _atomic_write_text(str(p), "新")
    assert p.read_text(encoding="utf-8") == "新"


def test_failure_preserves_original_and_cleans_tmp(tmp_path, monkeypatch):
    p = tmp_path / "mem.md"
    _atomic_write_text(str(p), "原始完整记忆")

    # 模拟就位阶段崩溃：os.replace 抛错。原文件必须原样保留、tmp 不残留。
    import bucket_manager
    monkeypatch.setattr(bucket_manager.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        _atomic_write_text(str(p), "半截的新内容")

    assert p.read_text(encoding="utf-8") == "原始完整记忆"
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []
