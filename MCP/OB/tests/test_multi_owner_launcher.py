"""多人启动器 deploy/multi_owner.py 的逻辑测试（不真正拉子进程）。

覆盖：owners 配置解析、校验（端口/目录去重）、每个实例环境变量的注入是否正确。
"""
import importlib.util
import os

import pytest

_LAUNCHER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "multi_owner.py"
)
_spec = importlib.util.spec_from_file_location("multi_owner", _LAUNCHER)
mo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mo)


def _write(tmp_path, text):
    p = tmp_path / "owners.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_owners_parses_and_resolves_vault(tmp_path):
    cfg = _write(tmp_path, """
owners:
  - name: 小明
    port: 18001
    vault: ./buckets-ming
  - name: 小红
    port: 18002
    vault: ./buckets-hong
""")
    owners = mo.load_owners(cfg)
    assert [o["name"] for o in owners] == ["小明", "小红"]
    assert [o["port"] for o in owners] == [18001, 18002]
    # 相对路径按配置文件目录解析成绝对路径
    assert owners[0]["vault"] == os.path.normpath(str(tmp_path / "buckets-ming"))
    assert os.path.isabs(owners[0]["vault"])


def test_duplicate_ports_rejected(tmp_path):
    cfg = _write(tmp_path, """
owners:
  - name: a
    port: 18001
    vault: ./va
  - name: b
    port: 18001
    vault: ./vb
""")
    with pytest.raises(ValueError, match="端口重复"):
        mo.load_owners(cfg)


def test_duplicate_vaults_rejected(tmp_path):
    cfg = _write(tmp_path, """
owners:
  - name: a
    port: 18001
    vault: ./shared
  - name: b
    port: 18002
    vault: ./shared
""")
    with pytest.raises(ValueError, match="数据目录重复"):
        mo.load_owners(cfg)


def test_missing_name_rejected(tmp_path):
    cfg = _write(tmp_path, """
owners:
  - port: 18001
    vault: ./va
""")
    with pytest.raises(ValueError, match="缺 name"):
        mo.load_owners(cfg)


def test_empty_owners_rejected(tmp_path):
    cfg = _write(tmp_path, "owners: []\n")
    with pytest.raises(ValueError, match="非空列表"):
        mo.load_owners(cfg)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        mo.load_owners(str(tmp_path / "nope.yaml"))


def test_build_env_injects_isolation_vars():
    owner = {"name": "小明", "port": 18001, "vault": "/data/ming"}
    env = mo.build_env(owner, owner_count=2, base_env={"EXISTING": "keep"})
    assert env["OMBRE_OWNER_NAME"] == "小明"
    assert env["OMBRE_OWNER_COUNT"] == "2"
    assert env["OMBRE_PORT"] == "18001"
    assert env["OMBRE_VAULT_DIR"] == "/data/ming"
    assert env["OMBRE_CONFIG_PATH"] == os.path.join("/data/ming", "config.yaml")
    # 继承父环境
    assert env["EXISTING"] == "keep"


def test_build_env_count_matches_people(tmp_path):
    cfg = _write(tmp_path, """
owners:
  - name: a
    port: 1
    vault: ./va
  - name: b
    port: 2
    vault: ./vb
  - name: c
    port: 3
    vault: ./vc
""")
    owners = mo.load_owners(cfg)
    envs = [mo.build_env(o, len(owners), base_env={}) for o in owners]
    assert all(e["OMBRE_OWNER_COUNT"] == "3" for e in envs)
