#!/usr/bin/env python3
"""一个大脑、多人共用、记忆隔离 —— 跨平台一键启动器。

每个人 = 一个独立 OB 实例：独立数据目录（OMBRE_VAULT_DIR）+ 独立端口（OMBRE_PORT）。
本启动器读一份 owners 配置，为每个人拉起一个 `python src/server.py` 子进程，并自动注入
OMBRE_OWNER_NAME / OMBRE_OWNER_COUNT，前端据此显示归属徽标（≥2 人才显示）。

用法：
    python deploy/multi_owner.py                     # 读 deploy/owners.yaml
    python deploy/multi_owner.py path/to/owners.yaml # 指定配置

owners.yaml 示例见 deploy/owners.example.yaml。API Key / 密码等敏感配置仍走各自
数据目录下的 config.yaml 或进程环境（.env / 平台环境变量），本启动器原样继承父进程环境。

Windows / Linux / macOS 通用（只依赖 Python + PyYAML，二者本来就是 OB 的依赖）。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

# Windows 控制台默认 GBK，无法编码 ✓ / → / 中文标点等，会让 print 直接崩。
# 统一把标准输出改成 UTF-8（Python 3.7+），保证三平台输出一致、不因字符编码报错。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover - 老 Python / 非常规流
        pass

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    sys.exit(1)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER = os.path.join(_REPO_ROOT, "src", "server.py")
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, "deploy", "owners.yaml")


def load_owners(config_path: str) -> list[dict[str, Any]]:
    """读 owners 配置，返回 [{name, port, vault}, ...]（已校验、vault 转绝对路径）。"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"找不到配置文件：{config_path}\n"
            f"复制 deploy/owners.example.yaml 为 deploy/owners.yaml 再改。"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    owners = data.get("owners")
    if not isinstance(owners, list) or not owners:
        raise ValueError("配置里 `owners` 必须是非空列表。")

    cfg_dir = os.path.dirname(os.path.abspath(config_path))
    parsed: list[dict[str, Any]] = []
    for i, o in enumerate(owners):
        if not isinstance(o, dict):
            raise ValueError(f"第 {i + 1} 个 owner 必须是映射（name/port/vault）。")
        name = str(o.get("name", "")).strip()
        if not name:
            raise ValueError(f"第 {i + 1} 个 owner 缺 name。")
        try:
            port = int(o["port"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"owner「{name}」的 port 必须是整数。")
        vault_raw = str(o.get("vault", "")).strip()
        if not vault_raw:
            raise ValueError(f"owner「{name}」缺 vault（数据目录）。")
        # 相对路径按配置文件所在目录解析，跟人的直觉一致
        vault = vault_raw if os.path.isabs(vault_raw) else os.path.normpath(os.path.join(cfg_dir, vault_raw))
        parsed.append({"name": name, "port": port, "vault": vault})

    _validate(parsed)
    return parsed


def _validate(owners: list[dict[str, Any]]) -> None:
    """端口、数据目录都必须两两不同，否则会互相串/抢端口。"""
    ports = [o["port"] for o in owners]
    dup_ports = {p for p in ports if ports.count(p) > 1}
    if dup_ports:
        raise ValueError(f"端口重复：{sorted(dup_ports)}——每个人必须用不同端口。")
    vaults = [os.path.normcase(o["vault"]) for o in owners]
    dup_vaults = {v for v in vaults if vaults.count(v) > 1}
    if dup_vaults:
        raise ValueError(f"数据目录重复：{sorted(dup_vaults)}——每个人必须用不同目录，否则记忆会串。")


def build_env(owner: dict[str, Any], owner_count: int, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """为某个 owner 的实例构造环境变量（继承父进程环境 + 注入本人的隔离变量）。"""
    env = dict(os.environ if base_env is None else base_env)
    env["OMBRE_OWNER_NAME"] = owner["name"]
    env["OMBRE_OWNER_COUNT"] = str(owner_count)
    env["OMBRE_PORT"] = str(owner["port"])
    env["OMBRE_VAULT_DIR"] = owner["vault"]
    # 每个实例的 config.yaml 放各自数据目录下，互不覆盖
    env["OMBRE_CONFIG_PATH"] = os.path.join(owner["vault"], "config.yaml")
    return env


def main(argv: list[str]) -> int:
    config_path = argv[1] if len(argv) > 1 else _DEFAULT_CONFIG
    owners = load_owners(config_path)
    count = len(owners)

    print(f"启动 {count} 个隔离实例（一个大脑多人共用，记忆互不串）：\n")
    print(f"  {'归属者':<12} {'端口':<8} 数据目录")
    print(f"  {'-' * 12} {'-' * 8} {'-' * 40}")
    for o in owners:
        print(f"  {o['name']:<12} {o['port']:<8} {o['vault']}")
    print()

    procs: list[subprocess.Popen] = []
    for o in owners:
        env = build_env(o, count)
        os.makedirs(o["vault"], exist_ok=True)
        p = subprocess.Popen([sys.executable, _SERVER], env=env, cwd=_REPO_ROOT)
        procs.append(p)
        print(f"  ✓ {o['name']} → http://localhost:{o['port']}  (pid {p.pid})")
    print("\n全部已拉起。Ctrl+C 停止所有实例。\n")

    def _shutdown(*_a):
        print("\n正在停止所有实例…")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (ValueError, AttributeError):  # pragma: no cover - 某些平台无 SIGTERM
        pass

    # 任一实例退出即整体收摊，避免留下半死状态
    while True:
        for p in procs:
            code = p.poll()
            if code is not None:
                print(f"\n⚠️ 有实例退出（pid {p.pid}, code {code}），停止其余实例。")
                _shutdown()
        try:
            procs[0].wait(timeout=2)
        except subprocess.TimeoutExpired:
            continue


if __name__ == "__main__":
    sys.exit(main(sys.argv))
