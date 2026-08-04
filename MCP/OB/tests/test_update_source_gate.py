"""热更新来源白名单 + 自动 pip 安装闸门（安全加固 #2）。

do-update 会把远端 zip 覆盖到 src/ 并（旧行为）自动 pip install，等于把「谁能改
config.update」放大成 RCE。默认只信官方仓、自动 pip 默认关闭。
"""
import pytest

import web.meta as meta
import web._shared as sh


@pytest.fixture(autouse=True)
def _restore():
    old = sh.config
    yield
    sh.config = old


def test_official_repo_allowed(monkeypatch):
    monkeypatch.delenv("OMBRE_ALLOW_CUSTOM_UPDATE_REPO", raising=False)
    assert meta._update_repo_allowed("P0luz/Ombre-Brain")
    assert meta._update_repo_allowed("p0luz/ombre-brain")   # 大小写不敏感
    assert meta._update_repo_allowed("/P0luz/Ombre-Brain/")  # 容忍多余斜杠


def test_foreign_repo_rejected_by_default(monkeypatch):
    monkeypatch.delenv("OMBRE_ALLOW_CUSTOM_UPDATE_REPO", raising=False)
    assert not meta._update_repo_allowed("attacker/evil")
    assert not meta._update_repo_allowed("p0luz/ombre-brain-evil")


def test_foreign_repo_allowed_via_optin(monkeypatch):
    monkeypatch.setenv("OMBRE_ALLOW_CUSTOM_UPDATE_REPO", "1")
    assert meta._update_repo_allowed("myfork/ombre-brain")


def test_pip_install_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OMBRE_UPDATE_ALLOW_PIP", raising=False)
    monkeypatch.setattr(sh, "config", {})
    assert meta._pip_install_allowed() is False


def test_pip_install_enabled_via_config(monkeypatch):
    monkeypatch.delenv("OMBRE_UPDATE_ALLOW_PIP", raising=False)
    monkeypatch.setattr(sh, "config", {"update": {"allow_pip_install": True}})
    assert meta._pip_install_allowed() is True


def test_pip_install_enabled_via_env(monkeypatch):
    monkeypatch.setattr(sh, "config", {})
    monkeypatch.setenv("OMBRE_UPDATE_ALLOW_PIP", "1")
    assert meta._pip_install_allowed() is True


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ("2.6.1", "v2.4.6", True),
        ("2.6.1", "2.6.1", False),
        ("2.6.1", "2.7.0", False),
        ("2.6", "2.6.0", False),
        ("dev", "2.4.6", False),
    ],
)
def test_hot_update_downgrade_guard(current, target, expected):
    assert meta._is_version_downgrade(current, target) is expected


def test_hot_update_defaults_to_same_main_branch_as_version_check():
    source = open(meta.__file__, encoding="utf-8").read()
    assert '_ucfg.get("channel") or "branch"' in source
