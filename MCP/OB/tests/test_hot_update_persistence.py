"""热更新持久性检测回归测试（用户反馈 #1）。

Docker 下 /api/do-update 若从持久卷上的代码运行（repo_root 在数据卷内），热更新
写盘后能扛过容器重建；若回退到镜像内置代码，则是易失的。前端据此如实提示。
"""

import pytest

import web.meta as meta
import web._shared as sh


@pytest.fixture(autouse=True)
def _restore():
    old_docker = sh._in_docker_cache
    old_root = sh.repo_root
    old_cfg = sh.config
    yield
    sh._in_docker_cache = old_docker
    sh.repo_root = old_root
    sh.config = old_cfg


def _setup(monkeypatch, *, in_docker, repo_root, buckets_dir):
    monkeypatch.setattr(sh, "_in_docker_cache", in_docker)
    monkeypatch.setattr(sh, "repo_root", repo_root)
    monkeypatch.setattr(sh, "config", {"buckets_dir": buckets_dir})


def test_bare_metal_is_persistent(monkeypatch):
    _setup(monkeypatch, in_docker=False, repo_root="/home/me/ombre", buckets_dir="/home/me/ombre/buckets")
    res = meta._hot_update_persistence()
    assert res["persistent"] is True
    assert res["mode"] == "bare"


def test_docker_running_from_volume_is_persistent(monkeypatch):
    # 播种成功：repo_root = CODE_DIR = <buckets>/_app，在数据卷内
    _setup(monkeypatch, in_docker=True,
           repo_root="/app/buckets/_app", buckets_dir="/app/buckets")
    res = meta._hot_update_persistence()
    assert res["persistent"] is True
    assert res["mode"] == "volume"


def test_docker_running_from_dedicated_code_volume_is_persistent(monkeypatch):
    _setup(monkeypatch, in_docker=True,
           repo_root="/app/ombre-code/_app", buckets_dir="/app/buckets")
    monkeypatch.setattr(meta, "_path_is_mounted_volume", lambda _path: True)
    res = meta._hot_update_persistence()
    assert res["persistent"] is True
    assert res["mode"] == "code-volume"


def test_docker_running_from_image_is_ephemeral(monkeypatch):
    # 播种失败回退：repo_root = /app（镜像内置），不在数据卷内
    _setup(monkeypatch, in_docker=True,
           repo_root="/app", buckets_dir="/app/buckets")
    monkeypatch.setattr(meta, "_path_is_mounted_volume", lambda _path: False)
    res = meta._hot_update_persistence()
    assert res["persistent"] is False
    assert res["mode"] == "ephemeral"
    assert "回退" in res["note"] or "重建" in res["note"]


def test_docker_sibling_path_not_mistaken_for_volume(monkeypatch):
    # /app/buckets_evil 不能被 /app/buckets 前缀误判为卷内
    _setup(monkeypatch, in_docker=True,
           repo_root="/app/buckets_evil/_app", buckets_dir="/app/buckets")
    monkeypatch.setattr(meta, "_path_is_mounted_volume", lambda _path: False)
    res = meta._hot_update_persistence()
    assert res["persistent"] is False
    assert res["mode"] == "ephemeral"


def test_mountinfo_detects_nested_code_volume(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "21 1 0:1 / / rw - overlay overlay rw\n"
        "37 21 0:42 / /app/ombre-code rw - ext4 /dev/sda rw\n",
        encoding="utf-8",
    )

    assert meta._path_is_mounted_volume(
        "/app/ombre-code/_app", str(mountinfo)
    ) is True
    assert meta._path_is_mounted_volume("/app", str(mountinfo)) is False


def test_mountinfo_decodes_escaped_spaces(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "37 21 0:42 / /app/code\\040volume rw - ext4 /dev/sda rw\n",
        encoding="utf-8",
    )

    assert meta._path_is_mounted_volume(
        "/app/code volume/_app", str(mountinfo)
    ) is True
