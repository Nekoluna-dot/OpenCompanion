"""网页控制台：数据管理（对应 launcher.py 的数据管理页）。

路径 / 大小统计 / 快捷删除 / 恢复出厂设置（密钥替换为占位符）。
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from botapp.webconsole.config_edit import CONFIG_INI, OB_CONFIG_YAML

_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCK_PATH = _ROOT / "data" / "bot.lock"
_LOG_DIR = _ROOT / "logs"
_CONV_DIR = _ROOT / "conversation"
_OB_BUCKETS = _ROOT / "MCP" / "OB" / "buckets"
_WEILINK_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".weilink"
_OB_ENV = _ROOT / "MCP" / "OB" / ".env"

PLACEHOLDER = "sk-REPLACE_ME"


def _platform_name() -> str:
    """读取 [platform] name（即当前启用的平台适配器）。"""
    cp = configparser.ConfigParser()
    try:
        if CONFIG_INI.exists():
            cp.read(CONFIG_INI, encoding="utf-8-sig")
        if cp.has_section("platform"):
            return (cp.get("platform", "name", fallback="wechat") or "wechat").strip()
    except (OSError, configparser.Error, ValueError):
        pass
    return "wechat"


def _platform_dir() -> tuple[str, Path]:
    """返回 (平台名, 平台数据目录)。

    目录以适配器类在代码里声明的 ``data_dir`` 为准（每个适配器必须标明
    自己的数据文件存在哪）；未声明则回退 ``~/.<平台名>``。
    """
    name = _platform_name()
    raw = ""
    try:
        from botapp.platform.registry import platform_data_dir

        raw = platform_data_dir(name)
    except Exception:
        raw = ""
    if not raw:
        raw = str(Path(os.path.expanduser("~")) / f".{name}")
    return name, Path(os.path.expandvars(os.path.expanduser(raw)))


def _size_str(path: Path) -> str:
    if not path.exists():
        return "不存在"
    total = 0
    if path.is_dir():
        for f in path.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
    else:
        try:
            total = path.stat().st_size
        except OSError:
            pass
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.1f}{unit}"
        total /= 1024
    return f"{total:.1f}TB"


def data_paths() -> list[dict]:
    name, pdir = _platform_dir()
    rows = [
        (f"平台数据（{name} · 登录态/消息库）", str(pdir)),
        ("对话存档", str(_CONV_DIR)),
        ("OB 记忆", str(_OB_BUCKETS)),
        ("运行日志", str(_LOG_DIR)),
    ]
    return [
        {"label": label, "path": p, "size": _size_str(Path(p)), "exists": Path(p).exists()}
        for label, p in rows
    ]


def delete_path(target: str) -> str:
    """删除指定路径（仅限白名单），返回结果文本。"""
    path = Path(target)
    allowed = {
        str(_platform_dir()[1]),
        str(_CONV_DIR),
        str(_OB_BUCKETS),
        str(_LOG_DIR),
        str(_LOCK_PATH),
    }
    if str(path) not in allowed:
        raise PermissionError(f"不允许删除路径: {target}")
    if not path.exists():
        return f"路径不存在：{target}"
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    return f"已删除：{target}"


def _platform_data_dirs() -> list[Path]:
    """返回应随“清全部用户数据”一并清除的平台数据目录。"""
    _, pdir = _platform_dir()
    out = [pdir]
    for extra in (_WEILINK_DIR,):  # 历史/其他平台的既有目录也顺手清
        if extra not in out:
            out.append(extra)
    return out


def factory_reset() -> str:
    """恢复出厂设置：清全部用户数据 + API 密钥替换为占位符。"""
    for p in _platform_data_dirs() + [_CONV_DIR, _OB_BUCKETS, _LOG_DIR]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    try:
        _LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    _replace_api_keys()
    _prune_missing_sources()
    return "已恢复出厂设置。请重新配置 API 密钥后再启动机器人。"


def factory_reset_full() -> str:
    """彻底恢复出厂：在 factory_reset 基础上再清空 data/ 目录(含登录密码、
    webconsole 设置、事件库、睡前仪式记录)并把 config.ini 重置为 git 初始版本
    (不可用时退化为密钥打码)。

    注意：此操作不可逆，调用方必须在 UI 上做强确认。
    """
    # 1. 清用户数据(平台/对话/OB记忆/日志/锁)
    for p in _platform_data_dirs() + [_CONV_DIR, _OB_BUCKETS, _LOG_DIR]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    try:
        _LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    # 2. 清空 data/ 目录全部内容(目录本身保留)
    data_dir = _ROOT / "data"
    if data_dir.exists():
        for item in data_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                pass

    # 3. config.ini 重置为 git 初始版本; git 不可用则退化为密钥打码
    default_cfg = _git_default_config()
    if default_cfg:
        try:
            CONFIG_INI.write_text(_sanitize_mcpsources(default_cfg), encoding="utf-8")
        except OSError:
            _replace_api_keys()
    else:
        _replace_api_keys()
    # OB 独立配置(config.yaml/.env)密钥打码
    _replace_ob_keys()

    return (
        "已彻底恢复出厂设置：全部用户数据与 data/ 目录已清空，"
        "config.ini 已重置为默认，登录密码已清除。"
        "请重新配置 API 密钥并重新设置登录密码。"
    )


def _git_default_config() -> str | None:
    """从 git 历史取项目初始 config.ini 作为出厂默认(git 不可用返回 None)。"""
    try:
        r = subprocess.run(
            ["git", "show", "HEAD:config.ini"],
            capture_output=True,
            cwd=str(_ROOT),
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0 and r.stdout:
            text = r.stdout.decode("utf-8", errors="ignore")
            if text.strip():
                return text
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _stdio_exists(value: str) -> bool:
    """stdio 描述的脚本文件是否仍在项目里（args 里的路径相对项目根判定）。

    URL 型 MCP 源不涉及本地文件，返回 True（保留）。
    """
    value = value.strip().strip('"').strip("'")
    if not value.startswith("{"):
        return True  # http:// URL 或普通字符串
    try:
        obj = json.loads(value)
    except (ValueError, TypeError):
        return True
    if not isinstance(obj, dict):
        return True
    args = obj.get("args")
    if not isinstance(args, list):
        return True
    for arg in args:
        arg = str(arg).strip().strip('"').strip("'")
        if not arg:
            continue
        p = Path(arg)
        if not p.is_absolute():
            p = _ROOT / p
        if p.exists():
            return True
    return False


def _sanitize_mcpsources(text: str) -> str:
    """出厂重置后注释掉指向已不存在脚本的 stdio MCP 源，避免误启用。"""
    lines = text.splitlines()
    in_mcp = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_mcp = s[1:-1].strip().lower() == "mcpsources"
            continue
        if not in_mcp:
            continue
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        name = s.split("=", 1)[0].strip()
        value = s.split("=", 1)[1]
        if not _stdio_exists(value):
            lines[i] = f"# {line.lstrip()}"
    return "\n".join(lines)


def _prune_missing_sources() -> None:
    """就地注释掉 config.ini 里指向已不存在脚本的 MCP 源。"""
    try:
        if not CONFIG_INI.exists():
            return
        text = CONFIG_INI.read_text(encoding="utf-8")
        out = _sanitize_mcpsources(text)
        if out != text:
            CONFIG_INI.write_text(out, encoding="utf-8")
    except OSError:
        pass


def _replace_api_keys() -> None:
    if CONFIG_INI.exists():
        lines = CONFIG_INI.read_text(encoding="utf-8").splitlines()
        out = []
        cur = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                cur = stripped[1:-1].strip().lower()
            if ("=" in stripped and not stripped.startswith("#")
                    and cur in ("llmapi", "mcp")):
                key = stripped.split("=", 1)[0].strip()
                if key == "api_key":
                    out.append(f"{key} = {PLACEHOLDER}")
                    continue
                if key == "token":
                    out.append(f"{key} = ")
                    continue
            out.append(line)
        CONFIG_INI.write_text("\n".join(out) + "\n", encoding="utf-8")
    _replace_ob_keys()


def _replace_ob_keys() -> None:
    if OB_CONFIG_YAML.exists():
        text = OB_CONFIG_YAML.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*api_key\s*:\s*).*$", rf"\1{PLACEHOLDER}", text)
        OB_CONFIG_YAML.write_text(text, encoding="utf-8")
    if _OB_ENV.exists():
        try:
            lines = _OB_ENV.read_text(encoding="utf-8").splitlines()
            out = []
            for line in lines:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k = s.split("=", 1)[0].strip()
                    if k in ("OMBRE_COMPRESS_API_KEY", "OMBRE_EMBED_API_KEY"):
                        out.append(f"{k}={PLACEHOLDER}")
                        continue
                out.append(line)
            _OB_ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
        except OSError:
            pass
