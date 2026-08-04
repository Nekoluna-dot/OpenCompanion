"""数据目录持久性自检回归测试（谨慎加固 A1）。

记忆最怕「以为存住了其实没有」。Docker 里若数据目录没挂持久卷，容器重建就全丢。
检测三态：裸机=本地持久 / Docker 未挂载=易失 / Docker 已挂载=持久。只提示不阻断。
"""
import pytest

import web._shared as sh


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    monkeypatch.setattr(sh, "_in_docker_cache", None)
    yield


def test_bare_metal_is_local_persistent(monkeypatch):
    monkeypatch.setattr(sh, "_in_docker_cache", False)
    res = sh.data_dir_persistence("/home/me/ombre/buckets")
    assert res["persistent"] is True
    assert res["mode"] == "local"


def test_docker_unmounted_is_ephemeral(monkeypatch):
    monkeypatch.setattr(sh, "_in_docker_cache", True)
    monkeypatch.setattr(sh.os.path, "ismount", lambda p: False)
    res = sh.data_dir_persistence("/app/buckets")
    assert res["persistent"] is False
    assert res["mode"] == "ephemeral"
    assert "丢" in res["note"]


def test_docker_mounted_is_persistent(monkeypatch):
    monkeypatch.setattr(sh, "_in_docker_cache", True)
    monkeypatch.setattr(sh.os.path, "ismount", lambda p: True)
    monkeypatch.delenv("OMBRE_HOST_VAULT_DIR", raising=False)
    res = sh.data_dir_persistence("/app/buckets")
    assert res["persistent"] is True
    assert res["mode"] == "volume"


def test_docker_explicit_host_mount(monkeypatch):
    monkeypatch.setattr(sh, "_in_docker_cache", True)
    monkeypatch.setattr(sh.os.path, "ismount", lambda p: True)
    monkeypatch.setenv("OMBRE_HOST_VAULT_DIR", "/host/ombre")
    res = sh.data_dir_persistence("/app/buckets")
    assert res["persistent"] is True
    assert res["mode"] == "host_mount"
