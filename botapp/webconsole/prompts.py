"""网页控制台：prompt / prompt_extra 在线预设管理。

预设以文件夹形式存放在 _ROOT/prompts/ 下,每个预设含:
  - prompt.txt
  - prompt_extra.txt
  - manifest.json (元数据: name/description/created_at)

切换预设 = 把目标预设的两份文件复制到 _ROOT 根目录覆盖,机器人下一轮对话即生效。
启动时若 prompts/ 不存在或缺 default/, 自动把当前根目录的 prompt.txt/prompt_extra.txt 迁入 default/。
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
from pathlib import Path


def _safe_name(name: str) -> str:
    """只允许字母/数字/中文/下划线/连字符/点, 禁止 / \\ .. 防止路径穿越。"""
    if not name or not isinstance(name, str):
        raise ValueError("预设名不能为空")
    if re.search(r"[\\/]|(\.\.)", name) or name in (".", ".."):
        raise ValueError(f"非法预设名: {name}")
    if not re.match(r"^[\w\-\. \u4e00-\u9fff]{1,64}$", name):
        raise ValueError(f"预设名包含非法字符: {name}")
    return name


class PromptsManager:
    ACTIVE_FILE = ".active"

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._dir = self._root / "prompts"
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        """确保 prompts/ 目录与 default/ 预设存在(初次启动时自动迁移根目录的 prompt)。"""
        self._dir.mkdir(exist_ok=True)
        default = self._dir / "default"
        if not default.exists():
            default.mkdir(parents=True)
            manifest = {
                "name": "default",
                "description": "默认预设(初次启动时从根目录 prompt.txt / prompt_extra.txt 迁移)",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            (default / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for fname in ("prompt.txt", "prompt_extra.txt"):
                src = self._root / fname
                if src.exists():
                    (default / fname).write_text(
                        src.read_text(encoding="utf-8"), encoding="utf-8"
                    )
        # 激活文件
        if not (self._dir / self.ACTIVE_FILE).exists():
            (self._dir / self.ACTIVE_FILE).write_text("default", encoding="utf-8")

    # -- 内部工具 ----------------------------------------------------
    def _read_active(self) -> str:
        f = self._dir / self.ACTIVE_FILE
        return f.read_text(encoding="utf-8").strip() if f.exists() else "default"

    def _write_active(self, name: str) -> None:
        (self._dir / self.ACTIVE_FILE).write_text(name, encoding="utf-8")

    def _read_manifest(self, p: Path) -> dict:
        f = p / "manifest.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _preset_dir(self, name: str) -> Path:
        _safe_name(name)
        p = self._dir / name
        return p

    # -- 对外 API ----------------------------------------------------
    def list_presets(self) -> list[dict]:
        active = self._read_active()
        out = []
        if not self._dir.exists():
            return out
        for p in sorted(self._dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            if p.name.startswith("."):
                continue
            if not (p / "prompt.txt").exists():
                continue
            meta = self._read_manifest(p)
            out.append({
                "name": p.name,
                "description": str(meta.get("description", "")),
                "created_at": str(meta.get("created_at", "")),
                "active": p.name == active,
            })
        return out

    def active_name(self) -> str:
        return self._read_active()

    def read_preset(self, name: str) -> dict:
        p = self._preset_dir(name)
        if not p.exists():
            raise FileNotFoundError(f"预设不存在: {name}")
        return {
            "name": name,
            "description": str(self._read_manifest(p).get("description", "")),
            "prompt": (p / "prompt.txt").read_text(encoding="utf-8") if (p / "prompt.txt").exists() else "",
            "extra": (p / "prompt_extra.txt").read_text(encoding="utf-8") if (p / "prompt_extra.txt").exists() else "",
        }

    def save_preset(self, name: str, prompt: str, extra: str, description: str = "") -> dict:
        """新建或覆盖一个预设(不会影响当前激活)。"""
        p = self._preset_dir(name)
        p.mkdir(parents=True, exist_ok=True)
        (p / "prompt.txt").write_text(prompt or "", encoding="utf-8")
        (p / "prompt_extra.txt").write_text(extra or "", encoding="utf-8")
        meta = self._read_manifest(p)
        meta.update({
            "name": name,
            "description": description or meta.get("description", ""),
        })
        if "created_at" not in meta:
            meta["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        meta["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        (p / "manifest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"name": name, "description": meta["description"]}

    def delete_preset(self, name: str) -> str:
        p = self._preset_dir(name)
        if name == "default":
            raise ValueError("默认预设不可删除")
        if name == self._read_active():
            raise ValueError("当前激活的预设不可删除, 请先切换到其他预设")
        if not p.exists():
            raise FileNotFoundError(f"预设不存在: {name}")
        shutil.rmtree(p)
        return f"已删除预设: {name}"

    def activate(self, name: str) -> str:
        """切换激活: 把目标预设的 prompt.txt/prompt_extra.txt 复制到根目录覆盖。"""
        p = self._preset_dir(name)
        if not p.exists():
            raise FileNotFoundError(f"预设不存在: {name}")
        for fname in ("prompt.txt", "prompt_extra.txt"):
            src = p / fname
            dst = self._root / fname
            if src.exists():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        self._write_active(name)
        return f"已切换到预设: {name}, 下一轮对话生效"

    def import_current(self, name: str, description: str = "") -> dict:
        """把当前根目录的 prompt.txt / prompt_extra.txt 另存为新预设(不会切换激活)。"""
        prompt = (self._root / "prompt.txt").read_text(encoding="utf-8") if (self._root / "prompt.txt").exists() else ""
        extra = (self._root / "prompt_extra.txt").read_text(encoding="utf-8") if (self._root / "prompt_extra.txt").exists() else ""
        return self.save_preset(name, prompt, extra, description)