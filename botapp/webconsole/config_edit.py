"""网页控制台：config.ini / config.yaml 的读写编辑（对应 launcher.py 的配置页）。

- config.ini：结构化字段编辑 + mcpsources 勾选启停（含被注释禁用的源）
- 逐行写回保留注释与其他内容；yaml 按段替换目标键值
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_INI = _ROOT / "config.ini"
OB_CONFIG_YAML = _ROOT / "MCP" / "OB" / "config.yaml"

# 结构化编辑的字段（key -> 控件类型）
INI_SECTIONS: dict[str, dict[str, str]] = {
    "platform": {"name": "text"},
    "llmapi": {
        "base_url": "text",
        "api_key": "password",
        "model": "text",
        "api_type": "combo",
        "search_enabled": "bool",
        "thinking": "bool",
        "reasoning_effort": "combo",
        "use_proxy": "bool",
        "enable_image": "bool",
        "enable_video": "bool",
        "clean_paren": "bool",
        "split_newline": "bool",
        "compact_token_limit": "text",
    },
    "mcp": {
        "enabled": "bool",
        "transport": "combo",
        "host": "text",
        "port": "text",
        "token": "password",
    },
    "conversation": {"enabled": "bool", "dir": "text"},
    "web": {"enabled": "bool", "host": "text", "port": "text", "max_records": "text"},
}

COMBO_VALUES = {
    "api_type": ["chat", "responses"],
    "reasoning_effort": ["low", "high", "max"],
    "transport": ["streamable-http", "sse"],
}

# config.yaml 结构化编辑的段与字段（{字段名: 控件类型}，与 INI_SECTIONS 同构，
# 前端 buildForm 按此渲染；用数组会导致字段名显示为索引 0/1/2...）
YAML_SECTIONS = {
    "dehydration": {
        "api_key": "password",
        "base_url": "text",
        "model": "text",
        "max_tokens": "text",
        "temperature": "text",
        "timeout_seconds": "text",
    },
    "embedding": {
        "api_key": "password",
        "base_url": "text",
        "model": "text",
        "dim": "text",
        "enabled": "bool",
        "timeout_seconds": "text",
    },
}


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


# ---------------------------------------------------------------------------
# config.ini
# ---------------------------------------------------------------------------
def read_ini() -> dict:
    """读取 config.ini：结构化字段 + mcpsources 启停列表 + 原始文本 + 中文描述。"""
    values: dict[str, dict[str, str]] = {}
    cp = configparser.ConfigParser()
    if CONFIG_INI.exists():
        cp.read(CONFIG_INI, encoding="utf-8-sig")
    for sec, fields in INI_SECTIONS.items():
        values[sec] = {}
        for key in fields:
            values[sec][key] = cp.get(sec, key, fallback="") if cp.has_section(sec) else ""

    enabled = {}
    if cp.has_section("mcpsources"):
        enabled = {k: v.strip() for k, v in cp.items("mcpsources")}
    sources = []
    seen = set()
    for name, raw in enabled.items():
        sources.append({"name": name, "raw": raw, "enabled": True})
        seen.add(name)
    for raw in _section_lines(CONFIG_INI, "mcpsources"):
        s = raw.strip()
        if not s.startswith("#"):
            continue
        body = s.lstrip("#").strip()
        if "=" not in body:
            continue
        name = body.split("=", 1)[0].strip()
        if name in seen:
            continue
        sources.append({"name": name, "raw": body[body.index("=") + 1:].strip(), "enabled": False})
        seen.add(name)

    raw_text = ""
    try:
        raw_text = CONFIG_INI.read_text(encoding="utf-8")
    except OSError:
        pass
    return {
        "values": values,
        "sources": sources,
        "raw": raw_text,
        "schema": INI_SECTIONS,
        "combo": COMBO_VALUES,
        "descs": _read_descs(),
        "exists": CONFIG_INI.exists(),
        "mtime": _mtime(CONFIG_INI),
    }


def _looks_like_value(val: str) -> bool:
    """判断注释中 = 后的内容是否像配置值（URL/JSON/数字/路径/布尔）。"""
    if not val:
        return True
    if val.startswith(("http://", "https://", "{", "[", '"', "'")):
        return True
    if val in ("true", "false", "on", "off"):
        return True
    if val.startswith(("./", "../", "/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", val):
        return True
    try:
        float(val)
        return True
    except ValueError:
        return False


def _read_descs() -> dict[str, dict[str, str]]:
    """解析 config.ini 每个键上方的连续 # 注释块，作为字段的中文描述。

    规则：键行上方紧邻的注释行（不含被注释掉的示例键，如 "#calc = ..."）。
    """
    descs: dict[str, dict[str, str]] = {}
    try:
        lines = CONFIG_INI.read_text(encoding="utf-8").splitlines()
    except OSError:
        return descs
    cur_sec: str | None = None
    pending: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            cur_sec = stripped[1:-1].strip().lower()
            pending = []
            continue
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            # 被注释掉的示例键（#key = http://... / {"..."} 等）不是描述，跳过；
            # 中文说明里出现 "false = 默认禁用" 这类（= 后是中文）仍视为描述
            if "=" in body:
                cand = body.split("=", 1)[0].strip()
                val = body[body.index("=") + 1:].strip()
                if re.fullmatch(r"[A-Za-z0-9_.-]+", cand) and _looks_like_value(val):
                    pending = []
                    continue
            if cur_sec and body:
                pending.append(body)
            continue
        if "=" in stripped and cur_sec:
            key = stripped.split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z0-9_.-]+", key) and pending:
                descs.setdefault(cur_sec, {})[key] = " ".join(pending)
        pending = []
    return descs


def _section_lines(path: Path, section: str) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    in_sec = False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_sec = s[1:-1].strip().lower() == section
            continue
        if in_sec and s:
            if "=" in s.lstrip("#"):
                cand = s.lstrip("#").split("=", 1)[0].strip()
                if re.fullmatch(r"[A-Za-z0-9_.-]+", cand):
                    out.append(line)
    return out


def save_ini(values: dict[str, dict[str, str]] | None, sources: list[dict] | None, raw: str | None) -> None:
    """保存 config.ini。

    values 非 None：逐行替换结构化字段；sources 非 None：按勾选注释/取消注释；
    raw 非 None：整文件覆盖。
    """
    if raw is not None:
        CONFIG_INI.write_text(raw, encoding="utf-8")
        return

    if not CONFIG_INI.exists():
        lines = []
    else:
        lines = CONFIG_INI.read_text(encoding="utf-8").splitlines()

    sources_enabled = {s["name"]: bool(s.get("enabled")) for s in (sources or [])}
    cur_section = None
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            cur_section = stripped[1:-1].strip().lower()
            out.append(line)
            continue
        if cur_section is None:
            out.append(line)
            continue
        # mcpsources：按勾选状态注释/取消注释整行
        if cur_section == "mcpsources" and sources_enabled:
            name = None
            body = stripped.lstrip("#")
            if "=" in body:
                cand = body.split("=", 1)[0].strip()
                if cand in sources_enabled:
                    name = cand
            if name is not None:
                if sources_enabled[name]:
                    out.append(body)
                else:
                    out.append("#" + body)
                sources_enabled.pop(name)
                continue
            out.append(line)
            continue
        if not values or not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        sec_updates = values.get(cur_section)
        if not sec_updates:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in sec_updates:
            out.append(f"{key} = {sec_updates[key]}")
            sec_updates.pop(key)
        else:
            out.append(line)

    # 节内缺少的键：追加到对应节末尾
    if values:
        for sec, kv in values.items():
            if not kv:
                continue
            last_idx = -1
            for i, l in enumerate(out):
                s = l.strip()
                if s.startswith("[") and s.endswith("]") and s[1:-1].strip().lower() == sec:
                    last_idx = i
            if last_idx < 0:
                out.append("")
                out.append(f"[{sec}]")
                last_idx = len(out) - 1
            j = last_idx + 1
            while j < len(out) and not (out[j].strip().startswith("[") and out[j].strip().endswith("]")):
                j += 1
            for k, v in kv.items():
                out.insert(j, f"{k} = {v}")
                j += 1

    # 勾选中但文件里被注释成不存在的新源：追加到 [mcpsources] 节
    if sources_enabled:
        for name, enabled in sources_enabled.items():
            if not enabled:
                continue
            src = next((s for s in sources if s["name"] == name), None)
            if src is None:
                continue
            last_idx = -1
            for i, l in enumerate(out):
                s = l.strip()
                if s.startswith("[") and s.endswith("]") and s[1:-1].strip().lower() == "mcpsources":
                    last_idx = i
            if last_idx < 0:
                out.append("")
                out.append("[mcpsources]")
                last_idx = len(out) - 1
            j = last_idx + 1
            while j < len(out) and not (out[j].strip().startswith("[") and out[j].strip().endswith("]")):
                j += 1
            out.insert(j, f"{name} = {src['raw']}")
            sources_enabled.pop(name)

    CONFIG_INI.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------
def read_yaml() -> dict:
    """读取 config.yaml：结构化字段 + 原始文本。"""
    values = {}
    text = ""
    if OB_CONFIG_YAML.exists():
        text = OB_CONFIG_YAML.read_text(encoding="utf-8")
        for sec, keys in YAML_SECTIONS.items():
            block = _yaml_block(text, sec)
            values[sec] = {}
            for key in keys:
                m = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", block, re.MULTILINE) if block else None
                values[sec][key] = m.group(1).strip() if m else ""
    return {
        "values": values,
        "raw": text,
        "schema": YAML_SECTIONS,
        "exists": OB_CONFIG_YAML.exists(),
        "mtime": _mtime(OB_CONFIG_YAML),
    }


def save_yaml(values: dict[str, dict[str, str]] | None, raw: str | None) -> None:
    if raw is not None:
        OB_CONFIG_YAML.write_text(raw, encoding="utf-8")
        return
    if not OB_CONFIG_YAML.exists():
        raise FileNotFoundError(str(OB_CONFIG_YAML))
    text = OB_CONFIG_YAML.read_text(encoding="utf-8")
    for sec, kv in (values or {}).items():
        block = _yaml_block(text, sec)
        if block is None:
            continue
        new_block = block
        for key, val in kv.items():
            pattern = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)(.*)$", re.MULTILINE)
            new_block = pattern.sub(lambda m, v=val: f"{m.group(1)}{v.strip()}", new_block, count=1)
        text = text.replace(block, new_block)
    OB_CONFIG_YAML.write_text(text, encoding="utf-8")


def _yaml_block(text: str, section: str) -> str | None:
    m = re.search(rf"^({re.escape(section)}:.*?)(?=^\S+:)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else None
