# -*- coding: utf-8 -*-
"""OpenCompanion 启动器 + 配置 + 数据管理 一体化面板。

用法：
    python scripts/launcher.py
    或双击 启动器.bat

包含：
    1. 启动器（第一页）：一键启动/停止 main.py（机器人），窗口内实时查看日志；
       快捷打开 调试面板 :8080（LLM 原始请求/响应）与 OmbreBrain 后台 :18001
       （日记 / 信件 / 长期记忆查看与管理）。支持 OB 后台独立启动/停止、
       运行时间查看、机器人退出后自动重启（可关闭，设置自动保存）。
    2. 机器人配置：config.ini 全字段 + MCP 工具源启停，逐键写回保留注释，
       文件被外部修改时自动实时刷新。
    3. OmbreBrain 配置：MCP/OB/config.yaml（dehydration / embedding）。
    4. 数据管理：清空 weilink 数据（%USERPROFILE%\.weilink）、对话存档、
       OB 记忆、日志、运行锁；恢复出厂设置（清全部用户数据并把 API 密钥
       替换为占位符）。

其他：
    - 启动时检测残留运行锁（异常关闭）并自动修复。
    - 关闭窗口二次确认，并停止子进程 / 释放运行锁。
    - 全程 try/catch，避免界面异常导致机器人进程被连带终止。
"""

from __future__ import annotations

import configparser
import json
import os
import re
import queue
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
CONFIG_INI = ROOT / "config.ini"
OB_CONFIG_YAML = ROOT / "MCP" / "OB" / "config.yaml"
BOT_PY = ROOT / "runtime" / "python" / "python.exe"
LOCK_PATH = ROOT / "data" / "bot.lock"
LOG_DIR = ROOT / "logs"
CONV_DIR_DEFAULT = ROOT / "conversation"
OB_BUCKETS = ROOT / "MCP" / "OB" / "buckets"
WEILINK_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".weilink"
SETTINGS_PATH = ROOT / "data" / "launcher_settings.json"

DEHYDRATION_KEYS = ["api_key", "base_url", "model", "max_tokens", "temperature", "timeout_seconds"]
EMBEDDING_KEYS = ["api_key", "base_url", "model", "dim", "enabled", "timeout_seconds"]

# 需要关注的端口
WATCH_PORTS = [
    (8000, "MCP 服务器"),
    (8080, "调试面板"),
    (18001, "OmbreBrain 后台"),
]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PAD = {"padx": 8, "pady": 4}

DPI_SCALE = 1.0


def setup_dpi() -> float:
    """启用系统 DPI 感知并返回缩放比例（96dpi 为 1.0）。必须在创建 Tk 窗口前调用。"""
    global DPI_SCALE, _PAD
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 系统 DPI 感知
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
        DPI_SCALE = max(1.0, dpi / 96.0)
    except Exception:  # noqa: BLE001
        DPI_SCALE = 1.0
    _PAD = {"padx": int(8 * DPI_SCALE), "pady": int(4 * DPI_SCALE)}
    return DPI_SCALE


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.scale = DPI_SCALE
        # 字体按缩放比放大（Tk 字体单位为 point，缩放后随 DPI 同步）
        if DPI_SCALE != 1.0:
            try:
                base = float(root.tk.call("tk", "scaling"))
                root.tk.call("tk", "scaling", base * DPI_SCALE)
            except tk.TclError:
                pass
        root.title("OpenCompanion 启动器")
        # 固定窗口大小，避免控件被拉伸遮挡
        W, H = int(960 * self.scale), int(800 * self.scale)
        root.geometry(f"{W}x{H}")
        root.minsize(W, H)
        root.maxsize(W, H)
        root.resizable(False, False)

        self.bot_proc: subprocess.Popen | None = None
        self.ob_proc: subprocess.Popen | None = None
        self.log_q: queue.Queue[tuple[str, str]] = queue.Queue()
        self._logfile_pos: dict[str, int] = {}
        self._tail_files: dict[str, str] = {}
        self._closing = False
        self._manual_stop = False
        self._restart_pending = False
        self._auto_restart = tk.BooleanVar(value=self._load_settings().get("auto_restart_bot", True))
        self._bot_start_time: float | None = None

        self._build_ui()
        self._clear_log_files()
        self._load_all()
        self._check_stale_lock()
        self._refresh_status()
        self._refresh_ports()
        self.root.after(100, self._drain_logs)
        self.root.after(2000, self._poll_status)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _clear_log_files(self) -> None:
        """每次新启动时清空日志文件，日志窗口从空白开始。"""
        try:
            for name in ("launcher_bot.log", "launcher_ob.log", "bot.log"):
                p = LOG_DIR / name
                if p.exists():
                    p.write_text("", encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb = nb

        self.tab_launch = ttk.Frame(nb)
        self.tab_ini = ttk.Frame(nb)
        self.tab_yaml = ttk.Frame(nb)
        self.tab_data = ttk.Frame(nb)
        nb.add(self.tab_launch, text="启动器")
        nb.add(self.tab_ini, text="机器人配置")
        nb.add(self.tab_yaml, text="OmbreBrain 配置")
        nb.add(self.tab_data, text="数据管理")

        self._build_launch_tab()
        self._build_ini_tab()
        self._build_yaml_tab()
        self._build_data_tab()

        # 配置实时刷新：周期检查文件 mtime，外部修改后自动重载
        self._ini_mtime = self._mtime(CONFIG_INI)
        self._yaml_mtime = self._mtime(OB_CONFIG_YAML)

        # 切到配置页时实时刷新一次，保证文件被外部修改后能看到最新值
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_current_tab())

    def _refresh_current_tab(self) -> None:
        """切换标签页时，刷新当前配置页为磁盘最新内容。"""
        idx = self.nb.index(self.nb.select())
        if idx == 1:  # 机器人配置
            self._load_ini()
        elif idx == 2:  # OmbreBrain 配置
            self._load_yaml()

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    @staticmethod
    def _load_settings() -> dict:
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = self._load_settings()
            data["auto_restart_bot"] = bool(self._auto_restart.get())
            SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _check_stale_lock(self) -> None:
        """启动时检测：锁文件存在但进程未运行 => 异常关闭，提示并修复。"""
        if not LOCK_PATH.exists():
            return
        pid = None
        try:
            pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = None
        if pid is not None and pid > 0 and pid_alive(pid):
            return
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
        messagebox.showwarning(
            "检测到异常关闭",
            "上次机器人可能未正常退出（运行锁残留且进程已结束）。\n\n"
            "运行锁已自动修复，可正常启动机器人。")

    def _on_close(self) -> None:
        """关闭窗口：二次确认，并停止子进程 / 释放运行锁。"""
        if not messagebox.askyesno("退出启动器", "确定要退出启动器吗？\n\n机器人正在运行时会被一并停止。"):
            return
        self._closing = True
        try:
            if self.bot_proc and self.bot_proc.poll() is None:
                self._kill_tree(self.bot_proc.pid)
            if self.ob_proc and self.ob_proc.poll() is None:
                self._kill_tree(self.ob_proc.pid)
        except Exception:  # noqa: BLE001
            pass
        try:
            if LOCK_PATH.exists():
                LOCK_PATH.unlink()
        except OSError:
            pass
        self.root.destroy()

    def _build_launch_tab(self) -> None:
        f = self.tab_launch

        # 状态栏
        top = ttk.Frame(f)
        top.pack(fill="x", **_PAD)
        self.lbl_status = ttk.Label(top, text="状态：未知", font=("", 11, "bold"))
        self.lbl_status.pack(side="left")

        # 快捷启动网页面板（第一页）
        web = ttk.LabelFrame(f, text="快捷启动（网页面板）", padding=8)
        web.pack(fill="x", **{"padx": 8, "pady": 4})

        def web_row(btn_text: str, url: str, desc: str):
            r = ttk.Frame(web)
            r.pack(fill="x", pady=3)
            ttk.Button(r, text=btn_text, width=22,
                       command=lambda: self._open_url(int(url.rsplit(":", 1)[1]))).pack(side="left")
            ttk.Label(r, text=desc).pack(side="left", padx=8)

        web_row("调试面板  :8080", "http://127.0.0.1:8080",
                "查看每次 LLM 请求的原始上下文与响应（[web] 开启后生效）")
        web_row("OmbreBrain  :18001", "http://127.0.0.1:18001",
                "长期记忆后台：查看日记、信件、记忆桶，管理 OmbreBrain")

        # 机器人控制
        ctrl = ttk.Frame(f)
        ctrl.pack(fill="x", **_PAD)
        self.btn_start = ttk.Button(ctrl, text="启动机器人", command=self.start_bot)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(ctrl, text="停止机器人", command=self.stop_bot, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_ob = ttk.Button(ctrl, text="启动 OB 后台", command=self.start_ob)
        self.btn_ob.pack(side="left")
        self.btn_ob_stop = ttk.Button(ctrl, text="停止 OB 后台", command=self.stop_ob, state="disabled")
        self.btn_ob_stop.pack(side="left", padx=6)
        ttk.Checkbutton(ctrl, text="退出后自动重启机器人", variable=self._auto_restart,
                        command=self._save_settings).pack(side="left", padx=8)
        ttk.Button(ctrl, text="清空日志窗口", command=self._clear_log_view).pack(side="right")

        # 运行时间
        run_row = ttk.Frame(f)
        run_row.pack(fill="x", **_PAD)
        ttk.Label(run_row, text="运行时间：").pack(side="left")
        self.lbl_uptime = ttk.Label(run_row, text="--")
        self.lbl_uptime.pack(side="left")
        ttk.Label(run_row, text="  （仅统计由本启动器启动的进程）", foreground="#888").pack(side="left", padx=6)

        # 端口检测
        port_box = ttk.LabelFrame(f, text="端口占用检测", padding=8)
        port_box.pack(fill="x", **{"padx": 8, "pady": 4})
        self._port_rows: list[tuple[int, str, ttk.Label, ttk.Button]] = []
        for port, desc in WATCH_PORTS:
            r = ttk.Frame(port_box)
            r.pack(fill="x", pady=1)
            lbl = ttk.Label(r, text=f"{desc}  :{port}  检测中...", foreground="#888")
            lbl.pack(side="left")
            btn = ttk.Button(r, text="--", state="disabled",
                             command=lambda p=port: self._kill_owner(p))
            btn.pack(side="right")
            self._port_rows.append((port, desc, lbl, btn))
        ttk.Button(port_box, text="重新检测", command=self._refresh_ports).pack(anchor="w")

        ttk.Label(f, text="运行日志（机器人 / OB 的实时输出）", font=("", 9)).pack(anchor="w", padx=8)
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, padx=8, pady=4)
        self.txt_log = tk.Text(wrap, height=20, wrap="none", state="disabled",
                               font=("Consolas", 9))
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, command=self.txt_log.yview)
        sb.pack(side="right", fill="y")
        self.txt_log.configure(yscrollcommand=sb.set)
        sbx = ttk.Scrollbar(wrap, orient="horizontal", command=self.txt_log.xview)
        sbx.pack(side="bottom", fill="x")
        self.txt_log.configure(xscrollcommand=sbx.set)

        tip = ttk.Label(f, text="提示：OmbreBrain 后台（18001）里可以查看她写给你的信和日记；"
                               "OB 随机器人内置的 ombre MCP 一起启动，若单独启动请先停止机器人避免端口冲突。",
                        foreground="#888", wraplength=760, justify="left")
        tip.pack(anchor="w", padx=8, pady=2)

    def _scroll_frame(self, parent: ttk.Frame):
        """带垂直滚动条的 Canvas 容器；内层 frame 宽度跟随视口，避免右半被裁掉。"""
        canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(event):
            canvas.itemconfigure(win, width=event.width)

        canvas.bind("<Configure>", _sync)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind_all("<MouseWheel>",
                       lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
                       if e.widget is canvas or e.widget is inner else None)
        return canvas, inner

    def _build_ini_tab(self) -> None:
        f = self.tab_ini
        # 底部按钮栏先打包（side=bottom），避免占用 Canvas 的横向空间
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", padx=8, pady=6)
        ttk.Button(bar, text="重新读取", command=self._load_ini).pack(side="left")
        ttk.Label(bar, text="（文件被外部修改时自动刷新）", foreground="#888").pack(side="left", padx=6)
        ttk.Button(bar, text="保存机器人配置", command=self.save_ini).pack(side="right")
        canvas, inner = self._scroll_frame(f)

        self.ini_widgets: dict[str, dict[str, tk.Widget]] = {}

        # platform
        g = self._ini_group(inner, "[platform]")
        self.ini_widgets["platform"] = {
            "name": self._entry_row(g, "name", "wechat"),
        }

        # llmapi
        g = self._ini_group(inner, "[llmapi] 主模型 API")
        self.ini_widgets["llmapi"] = {
            "base_url": self._entry_row(g, "base_url", "https://api.deepseek.com/chat/completions"),
            "api_key": self._entry_row(g, "api_key", "", show="*"),
            "model": self._entry_row(g, "model", "deepseek-v4-flash"),
        }
        w = self._ini_group(inner, "[llmapi] 可选 / 开关")
        llm = self.ini_widgets["llmapi"]
        llm["thinking"] = self._bool_row(w, "thinking", "思考模式（reasoning）")
        llm["reasoning_effort"] = self._combo_row(w, "reasoning_effort", ["low", "high", "max"])
        llm["use_proxy"] = self._bool_row(w, "use_proxy", "使用系统代理（false=强制直连）")
        llm["enable_image"] = self._bool_row(w, "enable_image", "接收图片消息并送入 LLM 理解")
        llm["enable_video"] = self._bool_row(w, "enable_video", "接收视频消息并送入 LLM 理解（视频须 <50MB）")
        llm["clean_paren"] = self._bool_row(w, "clean_paren", "发送前删除括号内神态/动作描写")
        llm["split_newline"] = self._bool_row(w, "split_newline", "把 \\n 视为气泡分隔符")
        llm["compact_token_limit"] = self._entry_row(w, "compact_token_limit", "250000")

        # mcp
        g = self._ini_group(inner, "[mcp]")
        self.ini_widgets["mcp"] = {
            "enabled": self._bool_row(g, "enabled", "启动 MCP 服务器"),
            "transport": self._combo_row(g, "transport", ["streamable-http", "sse"]),
            "host": self._entry_row(g, "host", "127.0.0.1"),
            "port": self._entry_row(g, "port", "8000"),
            "token": self._entry_row(g, "token", ""),
            "account_tools_enabled": self._bool_row(g, "account_tools_enabled", "启用 weilink 账号管理工具"),
        }

        # mcpsources（仅启停勾选，保留原始值）
        g = self._ini_group(inner, "[mcpsources] 外部 MCP 工具源（勾选=启用）")
        self.mcpsrc_vars: dict[str, tuple[tk.BooleanVar, str]] = {}
        box = ttk.Frame(g)
        box.pack(fill="x", **_PAD)
        self.mcpsrc_holder = box

        # conversation
        g = self._ini_group(inner, "[conversation]")
        self.ini_widgets["conversation"] = {
            "enabled": self._bool_row(g, "enabled", "持久化对话上下文"),
            "dir": self._entry_row(g, "dir", "conversation"),
        }

        # web
        g = self._ini_group(inner, "[web] 调试面板")
        self.ini_widgets["web"] = {
            "enabled": self._bool_row(g, "enabled", "启用调试面板"),
            "host": self._entry_row(g, "host", "127.0.0.1"),
            "port": self._entry_row(g, "port", "8080"),
            "max_records": self._entry_row(g, "max_records", "50"),
        }

    def _build_yaml_tab(self) -> None:
        f = self.tab_yaml
        # 底部按钮栏先打包（side=bottom），避免占用 Canvas 的横向空间
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", padx=8, pady=6)
        ttk.Button(bar, text="重新读取", command=self._load_yaml).pack(side="left")
        ttk.Label(bar, text="（文件被外部修改时自动刷新）", foreground="#888").pack(side="left", padx=6)
        ttk.Button(bar, text="保存 OmbreBrain 配置", command=self.save_yaml).pack(side="right")
        canvas, inner = self._scroll_frame(f)

        self.yaml_widgets: dict[str, dict[str, tk.Widget]] = {}

        g = self._ini_group(inner, "dehydration  文本理解（LLM 压缩记忆）")
        self.yaml_widgets["dehydration"] = {k: self._entry_row(g, k, "") for k in DEHYDRATION_KEYS}

        g = self._ini_group(inner, "embedding  向量记忆")
        self.yaml_widgets["embedding"] = {k: self._entry_row(g, k, "") for k in EMBEDDING_KEYS}

        ttk.Label(inner, text="提示：embedding 可用 DeepSeek 之外的厂商（如 SiliconFlow），需支持 bge-m3。",
                  foreground="#888").pack(anchor="w", padx=8)

    def _build_data_tab(self) -> None:
        f = self.tab_data
        info = ttk.LabelFrame(f, text="数据路径（从环境变量 / 配置文件自动解析）", padding=8)
        info.pack(fill="x", **{"padx": 8, "pady": 6})
        rows = [
            ("weilink 数据", WEILINK_DIR),
            ("对话存档", CONV_DIR_DEFAULT),
            ("OB 记忆", OB_BUCKETS),
            ("运行日志", LOG_DIR),
        ]
        self.data_path_labels = []
        for name, p in rows:
            lbl = ttk.Label(info, text=f"{name}:")
            lbl.pack(anchor="w")
            sub = ttk.Label(info, text=f"   {p}  ({self._size_str(p)})", foreground="#444")
            sub.pack(anchor="w", padx=(12, 0))
            self.data_path_labels.append(sub)

        ops = ttk.LabelFrame(f, text="快捷删除", padding=8)
        ops.pack(fill="both", expand=True, **{"padx": 8, "pady": 6})

        def row(btn_text: str, desc: str, target, cmd):
            fr = ttk.Frame(ops)
            fr.pack(fill="x", pady=3)
            ttk.Button(fr, text=btn_text, command=lambda: cmd(target, desc)).pack(side="left")
            ttk.Label(fr, text=desc).pack(side="left", padx=8)

        row("清空 weilink 数据", "删除 %USERPROFILE%\\.weilink（微信登录态、消息库，删除后需重新扫码）", WEILINK_DIR, self._delete_path)
        row("清空对话存档", "删除 conversation/（历史对话上下文）", CONV_DIR_DEFAULT, self._delete_path)
        row("清空 OB 记忆", "删除 MCP/OB/buckets（长期记忆，删除后不可恢复）", OB_BUCKETS, self._delete_path)
        row("清空运行日志", "删除 logs/（机器人日志文件）", LOG_DIR, self._delete_path)
        row("释放运行锁", "删除 data/bot.lock（机器人异常退出残留锁时用）", LOCK_PATH, self._delete_path)
        row("打开数据目录", "在文件管理器中打开项目目录", ROOT, self._open_folder)

        reset = ttk.LabelFrame(f, text="恢复出厂设置", padding=8)
        reset.pack(fill="both", expand=True, **{"padx": 8, "pady": 6})
        ttk.Label(reset, text="清空全部用户数据（weilink / 对话 / OB 记忆 / 日志 / 运行锁），\n"
                              "并把 config.ini、config.yaml 中的 API 密钥替换为占位符。\n"
                              "程序文件与运行环境不受影响，需重新配置密钥。",
                  justify="left").pack(anchor="w")
        ttk.Button(reset, text="恢复出厂设置", command=self._factory_reset).pack(anchor="w", pady=6)

    # ------------------------------------------------------------------
    # 通用控件
    # ------------------------------------------------------------------
    def _ini_group(self, parent: ttk.Frame, title: str) -> ttk.LabelFrame:
        g = ttk.LabelFrame(parent, text=title, padding=8)
        g.pack(fill="x", **{"padx": 6, "pady": 4})
        g.columnconfigure(1, weight=1)
        return g

    def _entry_row(self, parent, key: str, default: str, show: str = "") -> ttk.Entry:
        ttk.Label(parent, text=key).grid(row=parent.grid_size()[1], column=0, sticky="e", **_PAD)
        var = tk.StringVar(value=default)
        entry = ttk.Entry(parent, textvariable=var, width=70, show=show)
        entry.grid(row=parent.grid_size()[1] - 1, column=1, sticky="we", **_PAD)
        return entry

    def _bool_row(self, parent, key: str, label: str) -> ttk.Checkbutton:
        var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(parent, text=f"{key}  —  {label}", variable=var)
        cb.grid(row=parent.grid_size()[1], column=1, sticky="w", **_PAD)
        return cb

    def _combo_row(self, parent, key: str, values: list[str]) -> ttk.Combobox:
        ttk.Label(parent, text=key).grid(row=parent.grid_size()[1], column=0, sticky="e", **_PAD)
        cb = ttk.Combobox(parent, values=values, width=67, state="readonly")
        cb.set(values[0])
        cb.grid(row=parent.grid_size()[1] - 1, column=1, sticky="we", **_PAD)
        return cb

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def _load_all(self) -> None:
        self._load_ini()
        self._load_yaml()

    def _load_ini(self) -> None:
        if not CONFIG_INI.exists():
            return
        cp = configparser.ConfigParser()
        cp.read(CONFIG_INI, encoding="utf-8")
        secs = self.ini_widgets
        for sec, fields in secs.items():
            if not cp.has_section(sec):
                continue
            for key, w in fields.items():
                if not cp.has_option(sec, key):
                    continue
                if isinstance(w, ttk.Combobox):
                    w.set(cp.get(sec, key))
                elif isinstance(w, ttk.Entry):
                    w.delete(0, "end")
                    w.insert(0, cp.get(sec, key))
                elif isinstance(w, ttk.Checkbutton):
                    if cp.getboolean(sec, key) and not w.instate(("selected",)):
                        w.invoke()
                    elif not cp.getboolean(sec, key) and w.instate(("selected",)):
                        w.invoke()

        # mcpsources 勾选区（含被注释禁用的，可重新启用）
        for child in self.mcpsrc_holder.winfo_children():
            child.destroy()
        self.mcpsrc_vars.clear()
        enabled = {}
        if cp.has_section("mcpsources"):
            enabled = dict(cp.items("mcpsources"))
        raw_lines = self._read_section_lines(CONFIG_INI, "mcpsources")
        # 已启用源：直接来自 configparser
        for name, raw in enabled.items():
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.mcpsrc_holder, text=f"{name} = {raw[:60]}", variable=var)
            cb.pack(anchor="w")
            self.mcpsrc_vars[name] = (var, raw)
        # 被注释禁用的源：解析 #name = ...
        for raw in raw_lines:
            s = raw.strip()
            if not s.startswith("#"):
                continue
            body = s.lstrip("#").strip()
            if "=" not in body:
                continue
            name = body.split("=", 1)[0].strip()
            if name in self.mcpsrc_vars:
                continue
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.mcpsrc_holder, text=f"{name} = {body[body.index('=') + 1:].strip()[:60]}  (已禁用)",
                                 variable=var)
            cb.pack(anchor="w")
            self.mcpsrc_vars[name] = (var, body)

    @staticmethod
    def _read_section_lines(path: Path, section: str) -> list[str]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[str] = []
        in_sec = False
        for line in lines:
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                in_sec = s[1:-1].strip().lower() == section
                continue
            if in_sec and s:
                # 只收集形如 `name = ...`（或 `#name = ...`）的源条目，跳过说明注释
                if "=" in s.lstrip("#"):
                    cand = s.lstrip("#").split("=", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z0-9_.-]+", cand):
                        out.append(line)
        return out
    def _load_yaml(self) -> None:
        if not OB_CONFIG_YAML.exists():
            return
        text = OB_CONFIG_YAML.read_text(encoding="utf-8")
        for sec, fields in self.yaml_widgets.items():
            block = self._yaml_block(text, sec)
            if block is None:
                continue
            for key, w in fields.items():
                m = re.search(rf"^\s*{key}\s*:\s*(.*?)\s*$", block, re.MULTILINE)
                if not m:
                    continue
                val = m.group(1).strip()
                if isinstance(w, ttk.Entry):
                    w.delete(0, "end")
                    w.insert(0, val)

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def save_ini(self) -> None:
        try:
            updates: dict[str, dict[str, str]] = {}
            for sec, fields in self.ini_widgets.items():
                updates[sec] = {}
                for key, w in fields.items():
                    if isinstance(w, ttk.Combobox) or isinstance(w, ttk.Entry):
                        updates[sec][key] = w.get().strip()
                    elif isinstance(w, ttk.Checkbutton):
                        updates[sec][key] = "true" if w.instate(("selected",)) else "false"
            self._persist_ini(updates)
            self._ini_mtime = self._mtime(CONFIG_INI)
            messagebox.showinfo("完成", "config.ini 已保存。")
            self._prompt_restart_if_running()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    def _persist_ini(self, updates: dict[str, dict[str, str]]) -> None:
        """逐行写回 config.ini：仅替换目标键值 / 注释切换 mcpsources，保留注释与其他内容。"""
        lines = CONFIG_INI.read_text(encoding="utf-8").splitlines()
        cur_section: str | None = None
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                cur_section = stripped[1:-1].strip().lower()
                out.append(line)
                continue
            if cur_section is None:
                out.append(line)
                continue
            sec_updates = updates.get(cur_section)
            # mcpsources：注释/取消注释整行
            if cur_section == "mcpsources":
                matched = None
                if "=" in stripped:
                    name = stripped.split("=", 1)[0].strip()
                    matched = self.mcpsrc_vars.get(name)
                if matched is None and stripped.startswith("#") and "=" in stripped.lstrip("#"):
                    name = stripped.lstrip("#").split("=", 1)[0].strip()
                    matched = self.mcpsrc_vars.get(name)
                if matched is not None:
                    var, raw = matched
                    if var.get():
                        out.append(line.lstrip("#"))
                    else:
                        out.append("#" + line.lstrip("#"))
                    continue
                out.append(line)
                continue
            if not sec_updates or not stripped or stripped.startswith("#") or "=" not in stripped:
                out.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in sec_updates:
                out.append(f"{key} = {sec_updates[key]}")
                sec_updates.pop(key)
            else:
                out.append(line)
        # 节内缺少的键：追加到对应节末尾
        for sec, kv in updates.items():
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
        CONFIG_INI.write_text("\n".join(out) + "\n", encoding="utf-8")

    def save_yaml(self) -> None:
        try:
            if not OB_CONFIG_YAML.exists():
                raise FileNotFoundError(str(OB_CONFIG_YAML))
            text = OB_CONFIG_YAML.read_text(encoding="utf-8")
            for sec, fields in self.yaml_widgets.items():
                block = self._yaml_block(text, sec)
                if block is None:
                    raise RuntimeError(f"config.yaml 中未找到 {sec}: 段")
                new_block = block
                for key, w in fields.items():
                    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)(.*)$", re.MULTILINE)
                    new_block = pattern.sub(lambda m: f"{m.group(1)}{w.get().strip()}", new_block, count=1)
                text = text.replace(block, new_block)
            OB_CONFIG_YAML.write_text(text, encoding="utf-8")
            self._yaml_mtime = self._mtime(OB_CONFIG_YAML)
            messagebox.showinfo("完成", "config.yaml 已保存。")
            self._prompt_restart_if_running()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    @staticmethod
    def _yaml_block(text: str, section: str) -> str | None:
        m = re.search(rf"^({section}:.*?)(?=^\S+:)", text, re.MULTILINE | re.DOTALL)
        return m.group(1) if m else None

    def _prompt_restart_if_running(self) -> None:
        """保存配置后，若机器人正在运行则提示需要重启；确认后自动重启。"""
        if not self._bot_running():
            return
        if messagebox.askyesno("需要重启机器人",
                               "机器人正在运行，保存的配置需要重启才能生效。\n\n"
                               "是否现在重启机器人？"):
            pid = None
            try:
                pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                pid = None
            if pid and pid_alive(pid):
                self._kill_tree(pid)
            self.root.after(1500, self.start_bot)

    # ------------------------------------------------------------------
    # 机器人 / OB 进程
    # ------------------------------------------------------------------
    def start_bot(self) -> None:
        try:
            self._start_bot_impl()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("启动失败", f"{exc}")

    def _start_bot_impl(self) -> None:
        if self.bot_proc and self.bot_proc.poll() is None:
            messagebox.showinfo("提示", "机器人已在运行。")
            return
        if LOCK_PATH.exists():
            try:
                old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                old_pid = 0
            if old_pid > 0 and pid_alive(old_pid):
                if not messagebox.askyesno("检测到运行中的 bot",
                                           f"已有 bot 进程 (PID {old_pid}) 正在运行。\n"
                                           "是否先停止它再启动新的？"):
                    return
                self._kill_tree(old_pid)
        if not BOT_PY.exists():
            messagebox.showerror("错误", f"未找到运行时 Python：{BOT_PY}")
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_file = (LOG_DIR / "launcher_bot.log").open("ab")
        self.bot_proc = subprocess.Popen(
            [str(BOT_PY), "main.py"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=out_file,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._bot_out_file = out_file
        self._tail_file_start(LOG_DIR / "launcher_bot.log")
        self._manual_stop = False
        self._restart_pending = False
        self._bot_start_time = time.time()
        self._log("[launcher]", "机器人启动中... 日志 → logs/launcher_bot.log")
        self._refresh_status()

    def stop_bot(self) -> None:
        try:
            if not self.bot_proc or self.bot_proc.poll() is not None:
                messagebox.showinfo("提示", "机器人未在运行。")
                return
            self._manual_stop = True
            pid = self.bot_proc.pid
            self._kill_tree(pid)
            self._log("[launcher]", f"已发送停止信号 PID {pid}")
        except Exception:  # noqa: BLE001
            pass

    def stop_ob(self) -> None:
        try:
            if not self.ob_proc or self.ob_proc.poll() is not None:
                messagebox.showinfo("提示", "OB 后台未在运行。")
                return
            pid = self.ob_proc.pid
            self._kill_tree(pid)
            self._log("[launcher]", f"已发送停止信号 PID {pid}")
        except Exception:  # noqa: BLE001
            pass

    def start_ob(self) -> None:
        try:
            self._start_ob_impl()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("启动失败", f"{exc}")

    def _start_ob_impl(self) -> None:
        if self.ob_proc and self.ob_proc.poll() is None:
            messagebox.showinfo("提示", "OB 后台已在运行。")
            return
        if self.bot_proc and self.bot_proc.poll() is None:
            messagebox.showwarning("端口冲突", "机器人正在运行（已内置 OB）。\n请先停止机器人再单独启动 OB，否则 18001 端口冲突。")
            return
        if not BOT_PY.exists():
            messagebox.showerror("错误", "未找到运行时 Python。")
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_file = (LOG_DIR / "launcher_ob.log").open("ab")
        self.ob_proc = subprocess.Popen(
            [str(BOT_PY), "MCP/OB/src/server.py"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=out_file,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._ob_out_file = out_file
        self._tail_file_start(LOG_DIR / "launcher_ob.log", "OB")
        self._log("[launcher]", "OB 后台启动中，请稍候... http://127.0.0.1:18001")

    def _pump(self, proc: subprocess.Popen, tag: str) -> None:
        """块式读取子进程输出：同时识别 \\n 与 \\r（二维码/进度条不会卡住日志）。"""
        try:
            if proc.stdout is not None:
                pending = b""
                while True:
                    chunk = proc.stdout.read(1024)
                    if not chunk:
                        break
                    pending += chunk
                    while b"\n" in pending:
                        raw, _, pending = pending.partition(b"\n")
                        self.log_q.put((tag, strip_ansi(raw.decode("utf-8", errors="replace").rstrip())))
                    # \r 分隔的进度/二维码，按行刷新
                    while b"\r" in pending:
                        raw, _, pending = pending.partition(b"\r")
                        self.log_q.put((tag, strip_ansi(raw.decode("utf-8", errors="replace").rstrip())))
                if pending:
                    self.log_q.put((tag, strip_ansi(pending.decode("utf-8", errors="replace").rstrip())))
        except Exception:
            pass
        finally:
            self.log_q.put((tag, "--- 进程退出 ---"))

    def _kill_tree(self, pid: int) -> None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass

    # ------------------------------------------------------------------
    # 端口检测
    # ------------------------------------------------------------------
    def _port_pids(self) -> dict[int, list[int]]:
        """用 netstat 检测端口 → 占用 PID 列表。"""
        try:
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        result: dict[int, list[int]] = {}
        for raw in out.splitlines():
            line = raw.strip()
            if "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            addr = parts[1]
            if ":" not in addr:
                continue
            port = addr.rsplit(":", 1)[-1]
            try:
                port = int(port)
            except ValueError:
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if port in WATCH_PORTS or port not in result:
                result.setdefault(port, []).append(pid)
        return result

    def _kill_pid(self, pid: int) -> None:
        """按 PID 杀死进程（含子进程树）。"""
        self._kill_tree(pid)
        self._log("launcher", f"已杀死 PID {pid}")
        self._refresh_ports()

    def _kill_owner(self, port: int) -> None:
        """杀掉占用指定端口的进程，二次确认。"""
        try:
            pids = self._port_pids().get(port, [])
        except Exception:  # noqa: BLE001
            pids = []
        if not pids:
            messagebox.showinfo("提示", f"端口 {port} 当前空闲。")
            self._refresh_ports()
            return
        if not messagebox.askyesno("杀死进程",
                                   f"端口 {port} 被以下进程占用：\nPID: {', '.join(map(str, pids))}\n\n"
                                   "确定要杀死这些进程吗？"):
            return
        for pid in pids:
            self._kill_pid(pid)
        messagebox.showinfo("完成", f"已尝试杀死端口 {port} 的占用进程。")

    def _refresh_ports(self) -> None:
        """刷新端口状态显示。"""
        try:
            pids = self._port_pids()
        except Exception:  # noqa: BLE001
            pids = {}
        for port, desc, lbl, btn in self._port_rows:
            owners = pids.get(port, [])
            if not owners:
                lbl.configure(text=f"{desc}  :{port}  空闲", foreground="#2e7d32")
                btn.configure(state="disabled", text="--")
                continue
            try:
                proc = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {owners[0]}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ).stdout.strip()
                name = proc.split(",")[0].strip('"') if proc else "?"
            except (OSError, subprocess.SubprocessError):
                name = "?"
            pids_txt = ", ".join(str(p) for p in owners)
            lbl.configure(text=f"{desc}  :{port}  被占用  PID={pids_txt}  ({name})",
                          foreground="#c62828")
            btn.configure(state="normal", text=f"杀死 {owners[0]}")

    # ------------------------------------------------------------------
    # 日志显示
    # ------------------------------------------------------------------
    _QR_BLOCK_RE = re.compile(r"[█▀▄▐▌▪▫▬■□▮▯⣿⣠⣤⣦⣧⣩⣫⣭⣮⣯⣰⣱⣲⣳⣴⣵⣶⣷]")

    # 日志标签 → 颜色（模拟控制台配色）
    _LOG_COLORS = {
        "INFO": "#2e7d32",
        "Info": "#2e7d32",
        "RECEIVE": "#2e7d32",
        "Receive": "#2e7d32",
        "SEND": "#2e7d32",
        "Send": "#2e7d32",
        "WARNING": "#b58900",
        "Warning": "#b58900",
        "CONTROLLER": "#b58900",
        "Controller": "#b58900",
        "ERROR": "#c62828",
        "Error": "#c62828",
        "CONFIG": "#00838f",
        "Config": "#00838f",
        "REPLY": "#00838f",
        "Reply": "#00838f",
        "LLM": "#00838f",
        "LLM STATS": "#00838f",
        "MCP": "#8e24aa",
        "AGENT": "#8e24aa",
        "Agent": "#8e24aa",
        "TOOL": "#8e24aa",
        "Tool": "#8e24aa",
        "OUTPUT": "#1565c0",
        "Output": "#1565c0",
        "USED TIME": "#b58900",
        "PROTO": "#616161",
        "LAUNCHER": "#616161",
        "DEFAULT": "#000000",
    }

    def _is_qr_line(self, line: str) -> bool:
        """二维码行：包含 Unicode 半块/块字符且几乎无其他文本（去空格后全是块字符）。"""
        stripped = line.strip()
        if len(stripped) < 4:
            return False
        blocks = self._QR_BLOCK_RE.findall(stripped)
        return len(blocks) >= 4 and len(blocks) >= len(stripped) * 0.5

    def _log(self, tag: str, message: str) -> None:
        """启动器自身消息入队，走统一着色渲染。"""
        self.log_q.put((tag.strip("[]"), message))

    def _append_log_line(self, text: str, color: str | None = None) -> None:
        self.txt_log.configure(state="normal")
        if color:
            tag = f"c_{color}"
            if tag not in self.txt_log.tag_names():
                self.txt_log.tag_configure(tag, foreground=color)
            self.txt_log.insert("end", text + "\n", tag)
        else:
            self.txt_log.insert("end", text + "\n")
        self.txt_log.configure(state="disabled")

    def _drain_logs(self) -> None:
        try:
            while True:
                tag, line = self.log_q.get_nowait()
                # 二维码行原样输出（不加水印前缀），保证可扫码
                if self._is_qr_line(line):
                    self._append_log_line(line)
                    continue
                # 按日志标签着色，模拟控制台颜色
                color = self._LOG_COLORS.get("DEFAULT")
                for key in self._LOG_COLORS:
                    if key in line:
                        color = self._LOG_COLORS[key]
                        break
                if tag and tag not in ("bot.log", "launcher_bot.log", "launcher_ob.log"):
                    line = f"[{tag}] {line}"
                self._append_log_line(line, color)
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_logs)

    def _clear_log_view(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------------
    # 状态轮询
    # ------------------------------------------------------------------
    def _poll_status(self) -> None:
        try:
            self._check_restart()
            self._refresh_status()
            self._watch_configs()
            self._tail_bot_log()
            # 端口检测较重，每 4 个轮询周期（约 8 秒）刷新一次
            self._poll_count = getattr(self, "_poll_count", 0) + 1
            if self._poll_count % 4 == 0:
                self._refresh_ports()
        except Exception:  # noqa: BLE001
            pass
        self.root.after(2000, self._poll_status)

    def _check_restart(self) -> None:
        """机器人进程异常退出后，若开启自动重启则拉起（手动停止不触发）。"""
        if self._closing or not self.bot_proc:
            return
        if self.bot_proc.poll() is None:
            return
        if self._manual_stop or not self._auto_restart.get():
            return
        if self._restart_pending:
            return
        self._restart_pending = True
        self._log("[launcher]", "检测到机器人进程已退出，3 秒后自动重启...")
        self.root.after(3000, self._restart_bot)

    def _restart_bot(self) -> None:
        try:
            self._restart_pending = False
            if self._closing:
                return
            if not self._auto_restart.get():
                return
            self.start_bot()
        except Exception:  # noqa: BLE001
            self._restart_pending = False
            self._log("[launcher]", "自动重启失败，请手动启动。")

    def _tail_bot_log(self) -> None:
        """滚动读取已跟踪的日志文件，把子进程 / 外部启动的 bot 日志也显示出来。"""
        # 外部 bot（未通过本启动器启动）也显示 logs/bot.log
        self._ensure_tail(LOG_DIR / "bot.log", "bot.log")
        for path, tag in list(self._tail_files.items()):
            self._read_tail(Path(path), tag)

    def _tail_file_start(self, path: Path, tag: str | None = None) -> None:
        """标记一个文件从当前位置开始跟踪（不重放历史）。"""
        tag = tag or path.name
        try:
            self._tail_files[str(path)] = tag
            self._logfile_pos[str(path)] = path.stat().st_size
        except OSError:
            pass

    def _ensure_tail(self, path: Path, tag: str) -> None:
        """确保文件被跟踪；从 0 开始（重放已有内容）。"""
        key = str(path)
        if key in self._tail_files:
            return
        self._tail_files[key] = tag
        self._logfile_pos[key] = 0
        try:
            size = path.stat().st_size
            # 首次跟踪只显示最近若干行，避免刷屏
            if size > 0:
                self._logfile_pos[key] = max(0, size - 4096)
        except OSError:
            self._logfile_pos[key] = 0

    def _read_tail(self, path: Path, tag: str) -> None:
        if not path.exists():
            return
        key = str(path)
        try:
            size = path.stat().st_size
            pos = self._logfile_pos.get(key, 0)
            if size < pos:
                pos = 0  # 文件被轮换/清空
            with path.open("rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
            self._logfile_pos[key] = size
            if chunk:
                for raw in chunk.split(b"\n"):
                    # 保留行首空格（二维码用空格当边框/亮色模块），只去尾部换行
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        self.log_q.put((tag, line))
        except OSError:
            self._logfile_pos[key] = 0

    def _watch_configs(self) -> None:
        """配置文件被外部修改（含 bot 运行时写回）后自动刷新界面。

        仅当用户不在对应配置页时自动重载，避免覆盖正在编辑的内容。
        """
        idx = self.nb.index(self.nb.select())
        ini_m = self._mtime(CONFIG_INI)
        yaml_m = self._mtime(OB_CONFIG_YAML)
        if ini_m != self._ini_mtime:
            self._ini_mtime = ini_m
            if idx != 1:
                self._load_ini()
        if yaml_m != self._yaml_mtime:
            self._yaml_mtime = yaml_m
            if idx != 2:
                self._load_yaml()

    def _bot_running(self) -> bool:
        """根据 data/bot.lock 判断机器人是否在运行。"""
        if not LOCK_PATH.exists():
            return False
        try:
            pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return False
        return pid > 0 and pid_alive(pid)

    def _refresh_status(self) -> None:
        running = self._bot_running()
        standalone_ob = self.ob_proc is not None and self.ob_proc.poll() is None
        # 机器人运行时内置 OB 后台（18001）同时启动，因此视为 OB 运行中
        ob_running = running or standalone_ob
        if running:
            text, color = "● 机器人运行中", "#2e7d32"
        else:
            text, color = "○ 机器人未运行", "#c62828"
        if ob_running:
            note = "OB 后台运行中（随机器人）" if running else "OB 后台运行中（独立启动）"
            text += f"   |  {note}"
        self.lbl_status.configure(text=text, foreground=color)
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        # OB 启动按钮：机器人运行（内置 OB）或已独立启动时禁用
        self.btn_ob.configure(state="disabled" if running or standalone_ob else "normal")
        # OB 停止按钮：仅能停止独立启动的 OB；内置 OB 随机器人停止
        self.btn_ob_stop.configure(state="normal" if standalone_ob else "disabled")
        self._update_uptime()

    def _update_uptime(self) -> None:
        """显示机器人已运行时长（由本启动器启动的进程）。"""
        if (self.bot_proc and self.bot_proc.poll() is None
                and self._bot_start_time is not None):
            secs = max(0, int(time.time() - self._bot_start_time))
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            self.lbl_uptime.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self.lbl_uptime.configure(text="--")

    def _open_url(self, port: int) -> None:
        webbrowser.open(f"http://127.0.0.1:{port}")

    # ------------------------------------------------------------------
    # 数据管理
    # ------------------------------------------------------------------
    def _size_str(self, p: Path) -> str:
        if not p.exists():
            return "不存在"
        total = 0
        if p.is_dir():
            for f in p.rglob("*"):
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    pass
        else:
            try:
                total = p.stat().st_size
            except OSError:
                pass
        for unit in ("B", "KB", "MB", "GB"):
            if total < 1024:
                return f"{total:.1f}{unit}"
            total /= 1024
        return f"{total:.1f}TB"

    def _refresh_data_paths(self) -> None:
        for lbl, p in zip(self.data_path_labels,
                          [WEILINK_DIR, CONV_DIR_DEFAULT, OB_BUCKETS, LOG_DIR]):
            lbl.configure(text=f"   {p}  ({self._size_str(p)})")

    def _delete_path(self, target: Path, desc: str) -> None:
        if not target.exists():
            messagebox.showinfo("提示", f"路径不存在：\n{target}")
            return
        if not messagebox.askyesno("确认删除", f"确定要删除吗？\n\n{desc}\n\n{target}"):
            return
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            self._refresh_data_paths()
            messagebox.showinfo("完成", f"已删除：\n{target}")
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc))

    def _open_folder(self, target: Path, desc: str = "") -> None:
        os.startfile(str(target))  # noqa: S606

    def _factory_reset(self) -> None:
        """恢复出厂设置：删全部用户数据、日志，API 密钥替换为占位符。"""
        if not messagebox.askyesno(
                "恢复出厂设置",
                "将清空全部用户数据并重置 API 密钥，此操作不可恢复！\n\n"
                "删除：weilink 数据 / 对话存档 / OB 记忆 / 日志 / 运行锁\n"
                "重置：config.ini、config.yaml 中的 API 密钥为占位符"):
            return
        if not messagebox.askyesno("最后确认", "再次确认：真的要恢复出厂设置吗？"):
            return
        if self.bot_proc and self.bot_proc.poll() is None:
            self._kill_tree(self.bot_proc.pid)
        if self.ob_proc and self.ob_proc.poll() is None:
            self._kill_tree(self.ob_proc.pid)
        try:
            for p in [WEILINK_DIR, CONV_DIR_DEFAULT, OB_BUCKETS, LOG_DIR]:
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
            if LOCK_PATH.exists():
                LOCK_PATH.unlink()
            self._replace_api_keys()
            self._load_ini()
            self._load_yaml()
            self._refresh_data_paths()
            self._refresh_status()
            messagebox.showinfo("完成", "已恢复出厂设置。\n\n请重新配置 API 密钥后再启动机器人。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("恢复失败", str(exc))

    def _replace_api_keys(self) -> None:
        """把 config.ini / config.yaml 中的密钥替换为占位符。"""
        PLACEHOLDER = "sk-REPLACE_ME"
        # config.ini
        if CONFIG_INI.exists():
            lines = CONFIG_INI.read_text(encoding="utf-8").splitlines()
            out: list[str] = []
            cur = ""
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    cur = stripped[1:-1].strip().lower()
                if ("=" in stripped and not stripped.startswith("#")
                        and (cur in ("llmapi", "mcp"))):
                    key = stripped.split("=", 1)[0].strip()
                    if key == "api_key":
                        out.append(f"{key} = {PLACEHOLDER}")
                        continue
                    if key == "token":
                        # MCP 服务器默认开放、不鉴权，恢复出厂后置空
                        out.append(f"{key} = ")
                        continue
                out.append(line)
            CONFIG_INI.write_text("\n".join(out) + "\n", encoding="utf-8")
        # config.yaml
        if OB_CONFIG_YAML.exists():
            text = OB_CONFIG_YAML.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^(\s*api_key\s*:\s*).*$", rf"\1{PLACEHOLDER}", text)
            OB_CONFIG_YAML.write_text(text, encoding="utf-8")
        # MCP/OB/.env
        env_path = ROOT / "MCP" / "OB" / ".env"
        if env_path.exists():
            try:
                lines = env_path.read_text(encoding="utf-8").splitlines()
                out = []
                for line in lines:
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k = s.split("=", 1)[0].strip()
                        if k in ("OMBRE_COMPRESS_API_KEY", "OMBRE_EMBED_API_KEY"):
                            out.append(f"{k}={PLACEHOLDER}")
                            continue
                    out.append(line)
                env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
            except OSError:
                pass


def main() -> None:
    try:
        setup_dpi()
        root = tk.Tk()
        app = LauncherApp(root)
        root.mainloop()
    except Exception:  # noqa: BLE001
        try:
            import traceback

            traceback.print_exc()
            messagebox.showerror("启动器异常", "启动器发生未捕获异常，已记录到控制台。")
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
