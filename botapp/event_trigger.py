import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from botapp.console import console

_TIME_FORMAT = "%Y-%m-%d %H:%M"
_ROUGH_WINDOW_MIN = 20  # 粗略事件允许的浮动窗口（分钟）
_EXACT_PAST_WINDOW_MIN = 15  # 精确事件允许的过期触发窗口（分钟）
_FIRED_PATH = Path(__file__).resolve().parent.parent / "data" / "fired_events.json"


class EventTrigger:


    def __init__(self, bot, interval: int = 60) -> None:
        self._bot = bot
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 已触发过的事件 id（持久化到 data/fired_events.json，重启不重复触发）
        self._fired: set[str] = set(self._load_fired())
        self._fired_lock = threading.Lock()
        # 经 capability 解析的实际工具名；能力未启用时保持 None（轮询直接跳过）
        self._ns = self._resolve_namespace()

    def _resolve_namespace(self) -> str | None:
        """从 capabilities 解析 event 能力所在的 namespace 前缀。"""
        caps = getattr(self._bot.tools, "capabilities", None)
        if caps is None:
            return None
        for tool in caps.tools("event"):
            if tool.endswith("-list_users") or tool.endswith("-query_events"):
                return tool.rsplit("-", 1)[0]
        return None

    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动后台轮询线程（daemon，随主进程退出）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="event-trigger", daemon=True
        )
        self._thread.start()
        console.config(
            f"事件触发器已启动（每次对齐整分钟 :00 秒触发检测，间隔 {self._interval}s）"
        )


    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        # 事件能力未启用时直接退出轮询（避免每 60s 空转）
        if self._ns is None:
            console.warn("事件能力未启用（检查 [mcpsources] 的 capability=event），事件提醒关闭")
            return
        # 先立即检测一次，之后对齐整分钟（HH:MM:00）触发
        while not self._stop.is_set():
            try:
                self._check_all()
            except Exception as e:
                console.warn(f"事件检测出错: {e}")
            self._stop.wait(self._until_next_minute())

    @staticmethod
    def _until_next_minute() -> float:
        """返回距离下一个整分钟（HH:MM:00）的剩余秒数。"""
        now = time.time()
        next_minute = (int(now) // 60 + 1) * 60
        return max(0.5, next_minute - now)

    # ------------------------------------------------------------------
    def _check_all(self) -> None:
        users = self._list_users()
        for user_id in users:
            self._check_user(user_id)

    def _list_users(self) -> list[str]:

        try:
            raw = self._bot.tools.call_tool(f"{self._ns}-list_users", {})
        except Exception as e:
            console.warn(f"获取事件用户列表失败: {e}")
            return []
        if isinstance(raw, str):
            import json

            s = raw.strip()
            if not s:
                return []
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                # 非 JSON：视为单个用户 ID（去掉可能的前后引号）
                return [s.strip('"\' ')]
            if isinstance(data, dict) and "error" in data:
                return []
            if isinstance(data, list):
                return [u for u in data if isinstance(u, str)]
            if isinstance(data, str):
                return [data]
        return []

    def _check_user(self, user_id: str) -> None:
        events = self._query_due_events(user_id)
        now = datetime.now()
        # 事件用完整用户 ID 触发（发送/输入态需要，见 OpenCompanion.resolve_user_id）
        full_id = self._bot.resolve_user_id(user_id)
        for event in events:
            event_id = event.get("id")
            if not event_id or event_id in self._fired:
                continue
            if self._is_due(event, now):
                with self._fired_lock:
                    self._fired.add(event_id)
                    self._save_fired()
                self._bot.on_event_reminder(full_id, event)

    # ------------------------------------------------------------------
    def _load_fired(self) -> list[str]:
        """加载已触发事件 ID（重启后不重复触发）。"""
        try:
            data = json.loads(_FIRED_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_fired(self) -> None:
        """把已触发事件 ID 原子写入 data/fired_events.json。"""
        try:
            _FIRED_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _FIRED_PATH.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(sorted(self._fired), ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(_FIRED_PATH)
        except OSError as e:
            console.warn(f"已触发事件持久化失败: {e}")

    # ------------------------------------------------------------------
    def _query_due_events(self, user_id: str) -> list[dict]:

        now = datetime.now()
        now_str = now.strftime(_TIME_FORMAT)
        exact_from = (now - timedelta(minutes=_EXACT_PAST_WINDOW_MIN)).strftime(_TIME_FORMAT)
        rough_from = (now - timedelta(minutes=_ROUGH_WINDOW_MIN)).strftime(_TIME_FORMAT)
        events = []
        events += self._query(user_id, time_type="精确", time_from=exact_from, time_to=now_str)
        events += self._query(user_id, time_type="粗略", time_from=rough_from, time_to=now_str)
        return events

    def _query(
        self,
        user_id: str,
        *,
        time_type: str,
        time_from: str,
        time_to: str,
    ) -> list[dict]:
        """调用 event_logger 范围查询；返回解析后的事件列表。"""
        try:
            raw = self._bot.tools.call_tool(
                f"{self._ns}-query_events",
                {
                    "user_id": user_id,
                    "time_type": time_type,
                    "time_from": time_from,
                    "time_to": time_to,
                    "limit": 200,
                },
            )
        except Exception as e:
            console.warn(f"查询事件失败 {user_id}: {e}")
            return []
        events = self._extract_events(raw)
        if events is None:
            console.warn(f"事件返回格式无法解析 {user_id}: {raw[:120]}")
            return []
        return events

    @staticmethod
    def _extract_events(raw) -> list[dict] | None:
        """从 MCP 返回值中解析事件列表；解析失败返回 None。

        兼容两种形态：
          - call_tool 直接返回的 JSON 字符串（可能是单事件 dict 或事件数组）
          - MCP TextContent 列表（[{"type":"text","text":"{json}"}]）
        """
        import json

        try:
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, list):
                data = raw
            else:
                data = raw
        except (json.JSONDecodeError, TypeError):
            return None

        # 递归解包 MCP TextContent 容器：{"type":"text","text":"{json}"}
        for _ in range(8):
            if isinstance(data, list) and data and all(
                isinstance(i, dict) and i.get("type") == "text" for i in data
            ):
                parsed_items = []
                for i in data:
                    try:
                        parsed_items.append(json.loads(i.get("text", "")))
                    except (json.JSONDecodeError, TypeError):
                        return None
                data = parsed_items
            elif isinstance(data, dict) and "text" in data and "type" in data:
                try:
                    data = json.loads(data["text"])
                except (json.JSONDecodeError, TypeError):
                    return None
            else:
                break

        if isinstance(data, dict):
            if "error" in data:
                return []
            if "events" in data and isinstance(data["events"], list):
                return data["events"]
            # 单条事件 dict（含 id 字段）→ 包装成列表
            if "id" in data:
                return [data]
            return []
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict)]
        return None

    # ------------------------------------------------------------------
    def _is_due(self, event: dict, now: datetime) -> bool:
        """判断事件当前是否已到期可触发。"""
        try:
            t = datetime.strptime(event.get("time", ""), _TIME_FORMAT)
        except (ValueError, TypeError):
            return False
        if event.get("time_type") == "粗略":
            # 粗略事件：time ~ time+20 分钟内触发（近似浮动）
            return t <= now <= t + timedelta(minutes=_ROUGH_WINDOW_MIN)
        # 精确事件：到达时间即触发，且尽量不过期太久（24h 内）
        return t <= now <= t + timedelta(hours=24)
