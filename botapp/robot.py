import json
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta

from botapp.config import AppConfig
from botapp.console import console
from botapp.llm import LLMClient
from botapp.messenger import MessageSender
from botapp.platform.base import BotMessage, PlatformAdapter, SendQuotaExhausted
from botapp.store import ConversationStore
from botapp.tools import McpTools, _BASE_DIR
from botapp.typing import TypingIndicator

_MAX_AGENT_ROUNDS = 5

# 用户消息末尾的系统时间戳（见 _build_messages），用于判断是否"新一轮对话"
_SYSTIME_RE = re.compile(r"systime:(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
# 角色扮演时 LLM 常用括号描述神态/动作（如（微笑）(摸摸头)），发送前清洗掉
_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")
# 距上一条用户消息超过该小时数 → 视为新一轮对话，注入 breath 引导
_NEW_CONVO_BREATH_HOURS = 2

#这个回复分隔符必须要在prompt_extra.txt里面告诉LLM怎么用 否则它不会用的
_SEP = "<SEP>"
_SEP_DELAY_BASE = 3.0        # 首段阅读基准（首段字数 → 3s）
_SEP_DELAY_MAX = 4.0         # 正常等待上限
_SEP_LONG_MIN = 100           # 超长段阈值（字）
_SEP_LONG_DELAY_MIN = 10.0   # 超长段随机下限
_SEP_LONG_DELAY_MAX = 20.0   # 超长段随机上限

# 合并窗口：4~8s 自适应。待合并消息越多等待越久（最多 8s），
# 消息少时尽快处理（最少 4s）。窗口内连发的消息合并为一条
# 发送给 LLM（<SEP> 分隔）
_MERGE_WINDOW_MIN = 2.0
_MERGE_WINDOW_MAX = 5.0
# 单次合并的最大消息条数，超过立即处理，防止积压
_MAX_MERGE = 10

# 特殊标签：LLM 回复 <none> 表示选择不回复（不执行发送）
_NONE_TAG = "<none>"
# 特殊标签：LLM 回复 <stop> 表示终止事件追催提醒（第 3 次起生效）
_STOP_TAG = "<stop>"

# 上下文压缩（context compaction）：
# 历史消息总 token 数（估算，1 字符≈1 token）超过阈值时，以 system
# 口吻让 LLM 总结全部对话（心情/感觉/进展/起因经过结果/对聊天对象的
# 感觉/上一步/下一步等），并要求用工具 userfilerecord-add_record 写入
# 档案；总结替代旧历史，只保留最近 _COMPACT_KEEP_ROUNDS 轮完整对话。
# 阈值可配置：config.ini [llmapi] compact_token_limit（默认 20 万），
# 或对话指令 /修改上下文限制 <数值>（支持 k/万/w 后缀）。
_COMPACT_TOKEN_LIMIT = 250000  # 默认触发阈值 这个并不是按照中文2个英文一个这样估算的 纯纯按字符个数算
_COMPACT_KEEP_ROUNDS = 10      # 总结后保留的最近完整轮数
_COMPACT_MARK = "[对话总结]"   # 历史中总结记录的标记前缀
# 事件提醒的 system 指令标记：提醒轮次写历史时，带此标记的 system 消息
# 也会存入上下文（_save_history 保留），使后续轮次能看到提醒指令本身。
_REMINDER_SYS_MARK = "[系统主动提醒]"
# 主动问候（revive）的 system 指令标记：同提醒，随轮次写入上下文。
_GREET_SYS_MARK = "[系统主动问候]"


def _compact_prompt(archive_tool: str = "") -> str:
    """构建上下文压缩指令（档案工具名动态注入，不硬编码）。"""
    archive_clause = ""
    if archive_tool:
        archive_clause = (
            f"1. 调用工具 {archive_tool} 把对方的档案存入归档："
            "user_id 必须是系统提示里给出的当前对话用户 ID，"
            "contact 填你对对方的称呼，"
            "content 只能包含对话中提到的对方的性格特征、爱好、偏好、"
            "令人印象深刻的事（如兴趣、性格、喜好、难忘的事件）。"
            "不要把聊天内容摘要写在这里。\n"
        )
    return (
        "[上下文压缩指令]\n"
        "对话上下文即将被压缩。请仔细回顾你和对方的全部对话，然后做两件事：\n"
        f"{archive_clause}"
        "2. 然后返回一段用中文写的对话内容结构化摘要"
        "（不要发给对方；它会替换旧的上下文）。必须包含：\n"
        "- 之前聊了什么\n"
        "- 你的心情和感受\n"
        "- 正在做什么\n"
        "- 做这件事的感受\n"
        "- 你和对方是怎么认识的\n"
        "- 起因、经过、结果\n"
        "- 你对聊天对象的感受\n"
        "- 最后进行到哪一步\n"
        "- 接下来要做什么\n"
        "保持简洁。\n"
    )

# 事件提醒追催机制：
# 第 N 次提醒后等 _REMINDER_DELAYS[N-1] 秒，期间用户没回复就再次提醒。
# 总提醒次数上限 _REMINDER_MAX_COUNT（含首次提醒）。
_REMINDER_MAX_COUNT = 3        # 总提醒次数上限（含首次提醒）
_FORGET_CONFIRM_TTL = 120      # /清除记忆 确认有效期（秒）
_REMINDER_DELAYS = [60, 60, 120]  # 各次提醒后的等待

_CMD_HELP = "/help"
_CMD_CONTROL = "/控制"
_CMD_CONTROL_ALT = "/参数配置"  # 别名：与 /控制 等价
_CMD_CLEAR = "/清除上下文"
_CMD_CLEAR_ALT = "/清空上下文"  # 别名：与 /清除上下文 等价
_CMD_CLEAR_CHAT = "/清空聊天记录"
_CMD_RESET = "/重置"
_CMD_FORGET = "/清除记忆"
_CMD_CONFIRM_FORGET = "/确认清除记忆"  # 用户确认后真正执行清除
_CMD_MEMORY_VIEW = "/看记忆"          # 查看记忆日记内容
_CMD_MEMORY_DELETE = "/删记忆"        # 删除单条记忆（移入归档）
_CMD_MEMORY_RESTORE = "/恢复记忆"     # 把已删记忆从归档恢复
_CMD_DIARY = "/日记"                  # 手动触发：后台写今日记忆日记
_CMD_SLEEP = "/睡觉"                  # 手动触发：消化最近 48 小时心事（等同 <dream>）
_CMD_LETTER = "/写信"                 # 手动触发：后台写信会话（等同 <letter>）
_CMD_COMPACT = "/缩减上下文"
_CMD_COMPACT_LIMIT = "/修改上下文限制"
_CMD_INFO = "/info"

_CONTROL_HELP = (
    "可用指令：\n"
    f"  {_CMD_HELP}  显示本帮助\n"
    f"  {_CMD_CONTROL}  查看/修改 LLM 配置\n"
    f"  {_CMD_COMPACT}  手动总结压缩上下文\n"
    f"  {_CMD_COMPACT_LIMIT} <数值>  修改压缩触发阈值（支持 k/万/w 后缀）\n"
    f"  {_CMD_INFO}  查看上下文/工具/CPU/GPU 状态\n"
    f"  {_CMD_CLEAR}  清空你的全部对话上下文\n"
    f"  {_CMD_CLEAR_CHAT}  清空全部历史聊天记录（消息库）\n"
    f"  {_CMD_RESET}    仅回退你发的上一句话\n"
    f"  {_CMD_FORGET}  清除与你有关的全部记忆（需 {_CMD_CONFIRM_FORGET} 确认）\n"
    f"  {_CMD_MEMORY_VIEW}  查看我记住了哪些事\n"
    f"  {_CMD_MEMORY_DELETE} <ID>  删除某一条记忆\n"
    f"  {_CMD_MEMORY_RESTORE} <ID>  恢复被删的记忆\n"
    f"  {_CMD_DIARY}  回顾今天，把值得记住的事写进记忆日记\n"
    f"  {_CMD_SLEEP}  消化最近的心事（睡前用）\n"
    f"  {_CMD_LETTER}  后台写一封长信（不会发给你）\n"
    "其他内容将作为普通对话继续。"
)

_LLMAPI_HELP = (
    "当前 LLM 配置：\n"
    "  可通过对话修改（立即生效，持久化到 config.ini）：\n"
    f"    {_CMD_CONTROL} model=模型名\n"
    f"    {_CMD_CONTROL} thinking=true|false\n"
    f"    {_CMD_CONTROL} reasoning_effort=low|high|max\n"
    f"    {_CMD_CONTROL} api_type=chat|responses（responses 支持原生联网搜索）\n"
    f"    {_CMD_CONTROL} search_enabled=true|false（仅 responses 生效，按次计费）\n"
    f"    {_CMD_CONTROL} compact_token_limit=数值（支持 k/万/w 后缀）\n"
    f"  用法示例：{_CMD_CONTROL} thinking=false"
)


class OpenCompanion:
    def __init__(self, platform: PlatformAdapter, config: AppConfig) -> None:
        self._platform = platform
        self._config = config
        self.typing = TypingIndicator(platform)
        self.messenger = MessageSender(platform)
        self.llm = LLMClient(config)
        self.tools = McpTools(self._platform, config)
        self._tool_defs = self.tools.list_openai_tools()

        # 回复特殊标记 → 系统动作（如提示词里约定道晚安时输出 <dream>，
        # 系统后台执行 dream 并剥掉标记）。注册表见 _register_default_markers。
        from botapp.markers import ReplyMarkers

        self.markers = ReplyMarkers(self.tools)
        self._register_default_markers()

        # 对话存档：启用时按用户持久化到 conversation/ 目录
        self.store: ConversationStore | None = None
        if config.conversation_enabled:
            self.store = ConversationStore(config.conversation_dir)
            console.config(f"对话存档目录: {self.store.directory}")

        # RAW 调试视图：记录每次 LLM 请求的原始上下文与响应
        self.rawview = None
        if config.web_enabled:
            from botapp.rawview import RawViewServer

            self.rawview = RawViewServer(config)
            self.rawview.start()

        # 短时连续消息合并缓冲：{user_id: {"texts": [..], "timer": Timer|None}}
        self._buffers: dict[str, dict] = {}
        self._buffer_lock = threading.Lock()

        # 事件提醒追催状态：{user_id: {"event": dict, "count": int,
        #   "timer": Timer|None, "last_sent": float}}
        self._reminder_state: dict[str, dict] = {}
        self._reminder_lock = threading.Lock()

        # 清除记忆两阶段确认：{user_id: {"waiting": bool, "requested_at": float}}
        self._forget_state: dict[str, dict] = {}
        self._forget_lock = threading.Lock()

        # <letter> 写信心会话防重入：{user_id}
        self._letter_running: set[str] = set()
        self._letter_lock = threading.Lock()

        # /日记 会话防重入：{user_id}
        self._diary_running: set[str] = set()

        # /睡觉 消化会话防重入：{user_id}
        self._dream_running: set[str] = set()

        # 每日睡前仪式防重入（DailyRitual 单线程触发，普通布尔即可）
        self._ritual_running = False

        # 同一用户的 LLM 生成/发送串行锁（RLock 可重入）：
        # 用户消息线程、主动追问、事件提醒都可能并发调用
        # _run_agent，不串行会并发读写历史 → 互相污染、回复只发最后一条
        self._user_locks: dict[str, threading.RLock] = {}
        self._user_locks_guard = threading.Lock()
        # 发送锁：分气泡发送按用户排队，上一轮气泡发完才发下一轮，
        # 生成阶段不持发送锁，因此下一轮可先生成回复再排队发送
        self._send_locks: dict[str, threading.RLock] = {}

        # 主动问候调度：由插件系统加载 revive 插件（plugins/revive/），
        # 注册 MCP 源并实例化后台调度器；main.py 调用 plugins.start()
        from botapp.plugins import PluginManager

        # 用户回复钩子：插件声明 on_user_reply 后由 PluginManager 注册，
        # 每条用户消息都会广播（见 on_message），主代码不硬编码插件名。
        self._user_reply_hooks: list[callable] = []
        self.plugins = PluginManager(self.tools, bot=self)
        self.plugins.load_all()
        self.plugins.instantiate_triggers(self)
        self.plugins.instantiate_reply_hooks()

    # ------------------------------------------------------------------
    def register(self) -> None:
        """把消息处理器注册到平台适配器。"""
        self._platform.on_message(self.on_message)

    def close(self) -> None:
        """清理本 bot 实例的后台资源（进程退出时调用）。

        取消所有事件追催计时器与消息合并缓冲计时器。
        注意：不关闭平台适配器（由调用方管理）。
        """
        with self._reminder_lock:
            for state in self._reminder_state.values():
                if state.get("timer") is not None:
                    state["timer"].cancel()
            self._reminder_state.clear()
        with self._buffer_lock:
            for buf in self._buffers.values():
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            self._buffers.clear()
        if getattr(self, "plugins", None) is not None:
            self.plugins.stop()

    def resolve_user_id(self, user_id: str) -> str:
        """把短用户 ID（去 @ 后缀）还原为完整可发送的 ID（委托平台适配器）。

        事件存档为了文件/路径安全只存短 ID，但发送消息和输入态必须用
        完整 ID（如 xxx@im.wechat）才能命中会话上下文。
        """
        return self._platform.resolve_user_id(user_id)

    def on_event_reminder(self, user_id: str, event: dict) -> None:
        """定时事件到期：自动唤起对话，以系统身份让 LLM 主动提醒用户。

        提醒指令以 system role 注入：LLM 模拟真人自然主动唤起对话，
        不暴露「定时任务/系统提醒」机制；生成的文本直接作为发给用户的消息。
        该轮对话写入历史，保持上下文连贯。
        """
        console.mcp(f"事件到期触发提醒: {user_id} {event.get('action')}")
        time_str = event.get("time", "")
        action = event.get("action", "")
        content = event.get("content", "")
        promise = content if content else action
        system_extra = (
            f"你的手机闹钟响了，备注是你当初自己写下的：{action}。"
            f"现在是 {time_str}，正是你答应对方的时间——当初你答应过：【{promise}】。"
            "闹钟响了就得兑现。像平时聊天一样把这句话自然发出去，系统会自动发送。"
            "不要说『我设了闹钟』之类的话；不要调用任何工具；不要暴露任何机制。"
            "像真人一样开口，用中文，直接输出你要说的话。"
        )
        try:
            self.typing.start(user_id)
            reply = self._run_agent(
                user_id, "(system active reminder)", system_extra, persist=True
            )
        except Exception as e:
            console.error(f"事件提醒生成失败: {e}")
            reply = f"提醒: {action}" + (f"\n{content}" if content else "")
        finally:
            self.typing.stop(user_id)
        if reply and reply.strip() == _NONE_TAG:
            console.warn(f"事件提醒被 LLM 跳过（<none>）: {user_id}")
            return
        if reply:
            self.send_parts(user_id, self._split_reply(reply))
            console.reply(user_id, reply)
            self._schedule_reminder_followup(user_id, event)
        else:
            console.warn("事件提醒生成为空，跳过发送")

    # ------------------------------------------------------------------
    # 事件提醒追催：发送后一段时间没收到用户回复，就再次提醒，最多 8 次，
    # 间隔 60s → 360s 递增；用户一旦回复立即取消后续追催。
    # ------------------------------------------------------------------
    def _schedule_reminder_followup(self, user_id: str, event: dict) -> None:
        """注册/重置该用户的追催状态（首次提醒已发出，开始等待回复）。"""
        with self._reminder_lock:
            state = self._reminder_state.get(user_id)
            if state is None:
                state = {"event": event, "count": 1, "timer": None,
                         "last_sent": time.time()}
                self._reminder_state[user_id] = state
            else:
                if state["timer"] is not None:
                    state["timer"].cancel()
                    state["timer"] = None
                state["event"] = event
                state["count"] = 1
                state["last_sent"] = time.time()
        self._arm_reply_check(user_id, state)

    def _arm_reply_check(self, user_id: str, state: dict) -> None:
        """等待 _REMINDER_DELAYS[count-1] 秒：期间用户没回复则安排下一次追催。

        第 1 次提醒后 10s（快速判定没收到），之后间隔 60s → 360s 递增。
        """
        with self._reminder_lock:
            if user_id not in self._reminder_state:
                return  # 用户已回复，已取消
            idx = state["count"] - 1  # 第 count 次提醒后的等待
            if idx >= len(_REMINDER_DELAYS):
                return  # 已达最后间隔，不再安排（由 check 收尾清理）
            delay = _REMINDER_DELAYS[idx]
            if state["timer"] is not None:
                state["timer"].cancel()
            timer = threading.Timer(
                delay, self._reminder_reply_check, args=(user_id,),
            )
            timer.daemon = True
            state["timer"] = timer
            timer.start()

    def _reminder_reply_check(self, user_id: str) -> None:
        """10s 后检查：用户仍没回复（状态未被取消）→ 若未达上限则再次提醒。"""
        with self._reminder_lock:
            state = self._reminder_state.get(user_id)
            if state is None:
                return
            if state["count"] >= _REMINDER_MAX_COUNT:
                self._reminder_state.pop(user_id, None)
                return
        self._remind_again(user_id, state)

    def _remind_again(self, user_id: str, state: dict) -> None:
        """用户没回复，以系统口吻再提醒一次（间隔按 count 递增）。"""
        event = state["event"]
        with self._reminder_lock:
            count = state["count"] + 1
            state["count"] = count
            state["last_sent"] = time.time()
        console.mcp(
            f"事件追催提醒 ({count}/{_REMINDER_MAX_COUNT}): {user_id} {event.get('action')}"
        )
        time_str = event.get("time", "")
        action = event.get("action", "")
        content = event.get("content", "")
        if count >= 3:
            stop_clause = (
                "如果继续提醒已经没有意义（他显然不会回），"
                "你可以单独输出 <stop> 结束，系统会关闭后续闹钟，不要再发其他内容。"
            )
        else:
            stop_clause = ""
        system_extra = (
            f"你的手机闹钟又响了，备注还是当初那句：{action}，这已是第 {count} 次响铃。"
            f"现在是 {time_str}，你之前已经提醒过他 {count - 1} 次，他还没回，可能没看到。"
            "这次开口比上次更醒目一点，带一两个具体细节帮他想起这件事。"
            "不要说『我设了闹钟』之类的话；不要调用任何工具；不要暴露任何机制。"
            "像真人一样再次开口，用中文，直接输出你要说的话。"
            + (("\n" + stop_clause) if stop_clause else "")
        )
        try:
            self.typing.start(user_id)
            reply = self._run_agent(
                user_id, "(system active reminder)", system_extra, persist=True
            )
        except Exception as e:
            console.error(f"事件追催提醒生成失败: {e}")
            reply = f"提醒: {action}" + (f"\n{content}" if content else "")
        finally:
            self.typing.stop(user_id)
        if reply and _STOP_TAG in reply:
            clean = reply.replace(_STOP_TAG, "").strip()
            if state["count"] >= 3:
                # 第 3 次起 <stop> 生效：终止后续追催
                console.warn(f"事件追催被 LLM 用 <stop> 终止: {user_id}")
                if clean:
                    self.send_parts(user_id, self._split_reply(clean))
                    console.reply(user_id, clean)
                self._cancel_reminder(user_id)
                return
            # 第 2 次时 <stop> 未启用：只剥离标签，跳过本次发送但继续追催
            console.warn(f"追催 #{state['count']} 的 <stop> 未启用（第 3 次起生效）: {user_id}")
            if clean:
                self.send_parts(user_id, self._split_reply(clean))
                console.reply(user_id, clean)
            self._arm_reply_check(user_id, state)
            return
        if reply and reply.strip() == _NONE_TAG:
            console.warn(f"事件追催提醒被 LLM 跳过（<none>）: {user_id}")
            self._cancel_reminder(user_id)
            return
        if reply:
            self.send_parts(user_id, self._split_reply(reply))
            console.reply(user_id, reply)
            self._arm_reply_check(user_id, state)
        else:
            console.warn("事件追催提醒生成为空，跳过发送")
            self._cancel_reminder(user_id)

    def _cancel_reminder(self, user_id: str) -> None:
        """取消该用户的所有后续追催。"""
        with self._reminder_lock:
            state = self._reminder_state.pop(user_id, None)
            if state is not None and state["timer"] is not None:
                state["timer"].cancel()

    def on_message(self, msg: BotMessage) -> None:
        """处理一条收到的平台消息。"""
        if not msg.text:
            return

        t0 = time.perf_counter()
        console.recv(msg.from_user, msg.text)

        # 系统控制指令优先处理，不进入 LLM，也不取消事件提醒安排
        # （否则 /info 之类指令会把已设定的提醒追催清掉）
        control_reply = self._handle_control(msg.from_user, msg.text)
        if control_reply is not None:
            self.messenger.send(msg.from_user, control_reply)
            console.control(msg.from_user, control_reply)
            console.timing({"控制指令": time.perf_counter() - t0})
            return

        # 非清除记忆指令的普通消息：取消待确认状态（用户放弃或改主意）
        with self._forget_lock:
            self._forget_state.pop(msg.from_user, None)

        # 用户回复了消息：取消事件提醒追催（说明已收到提醒）
        if msg.from_user in self._reminder_state:
            self._cancel_reminder(msg.from_user)
        # 用户回复了消息：广播给所有注册了 on_user_reply 钩子的插件
        # （如 revive 引擎做贝叶斯学习）。插件通过 PluginManager 注册钩子，
        # 主代码不硬编码任何插件名。
        for hook in self._user_reply_hooks:
            try:
                hook(msg.from_user, msg.text)
            except Exception as e:
                console.warn(f"用户回复钩子执行失败: {e}")
        # 短时连续消息合并：所有消息先进缓冲，窗口 4~8s 自适应
        # （1 条等 4s，每多一条 +0.5s，封顶 8s），窗口内静默到期后
        # 合并为一条（<SEP> 分隔）再交给 LLM；超过上限立即处理。
        # 图片/视频消息不走合并缓冲（媒体需跟随独立路径），直接处理。
        if msg.image_path or msg.video_path:
            self._process_message(
                msg.from_user,
                msg.text,
                image_path=msg.image_path,
                video_path=msg.video_path,
            )
            return
        with self._buffer_lock:
            buf = self._buffers.get(msg.from_user)
            if buf is None:
                buf = {"texts": [], "timer": None, "entered": 0.0}
                self._buffers[msg.from_user] = buf
            if not buf["texts"]:
                # 新一批的第一条消息：重置批起始时间（上一批 flush 后
                # buf 会保留，entered 不可复用）
                buf["entered"] = time.perf_counter()
            buf["texts"].append(self._with_reply_context(msg))
            if len(buf["texts"]) >= _MAX_MERGE:
                # 积压超过上限：立即合并处理，不再等待窗口
                merged = " <SEP> ".join(buf["texts"])
                count = len(buf["texts"])
                wait = time.perf_counter() - buf["entered"]
                buf["texts"] = []
                if buf["timer"] is not None:
                    buf["timer"].cancel()
                    buf["timer"] = None
                console.merge(wait, count)
                self._process_message(msg.from_user, merged)
            else:
                # 动态窗口：1 条 3s，每多一条 +0.5s，封顶 5s
                wait = min(
                    _MERGE_WINDOW_MAX,
                    _MERGE_WINDOW_MIN + 0.5 * (len(buf["texts"]) - 1),
                )
                if buf["timer"] is not None:
                    buf["timer"].cancel()
                timer = threading.Timer(
                    wait, self._flush_buffer, args=(msg.from_user,)
                )
                timer.daemon = True
                buf["timer"] = timer
                timer.start()

    # ------------------------------------------------------------------
    def _with_reply_context(self, msg: BotMessage) -> str:
        """把「用户引用/回复的消息」拼到文本前，让 LLM 知道上下文。

        微信引用消息时，weilink 的 ref_msg 携带被引用内容。这里用
        [引用: ...] 前缀显式标注，避免 LLM 把原文当成新消息。
        """
        if not msg.replied_text:
            return msg.text
        return f"[用户引用了你之前发的消息: {msg.replied_text}]\n{msg.text}"

    # ------------------------------------------------------------------
    def _flush_buffer(self, user_id: str) -> None:
        """合并窗口到期：把缓冲中追加的消息合并处理（无则关闭缓冲）。"""
        with self._buffer_lock:
            buf = self._buffers.get(user_id)
            if buf is None:
                return
            texts = buf["texts"]
            entered = buf["entered"]
            buf["texts"] = []
            buf["timer"] = None
            if not texts:
                del self._buffers[user_id]
                return
        console.merge(time.perf_counter() - entered, len(texts))
        merged = " <SEP> ".join(texts)
        self._process_message(user_id, merged)

    def _process_message(self, user_id: str, user_text: str, image_path: str = "", video_path: str = "") -> None:
        """处理一条（可能合并后的）用户消息：输入中 → LLM → 发送。

        生成与发送解耦：
        - 生成阶段由 _run_agent 按用户串行（保证历史安全），但不受
          上一轮分气泡发送等待阻塞——下一轮可先生成好 LLM 回复；
        - 发送阶段经 send_parts 按用户排队，上一轮所有气泡发完才发
          下一轮，避免气泡互相穿插造成混乱。
        """
        t0 = time.perf_counter()

        # 显示「正在输入中」
        t = time.perf_counter()
        self.typing.start(user_id)
        typing_dur = time.perf_counter() - t

        # LLM agent 循环：生成 →（有 tool_calls）执行工具 → 回传 → 继续
        reply = ""
        t = time.perf_counter()
        try:
            reply = self._run_agent(
                user_id, user_text, image_path=image_path, video_path=video_path
            )
            if reply.strip() == _NONE_TAG:
                console.warn(f"LLM 选择不回复（<none>）: {user_id}")
                reply = ""
            console.generated(len(reply))
        except Exception as e:
            reply = f"抱歉，出错了：{e}"
        finally:
            # 取消输入状态
            self.typing.stop(user_id)
        generate_dur = time.perf_counter() - t

        # 按 <SEP> 分割回复，经发送队列逐条发出（气泡间按字数等待）
        t = time.perf_counter()
        parts = self._split_reply(reply)
        self.send_parts(user_id, parts)
        send_dur = time.perf_counter() - t
        total_dur = time.perf_counter() - t0

        console.timing(
            {
                "输入中": typing_dur,
                "生成": generate_dur,
                f"发送x{len(parts)}": send_dur,
                "总计": total_dur,
            }
        )
        if parts:
            console.reply(user_id, parts[0] if parts else reply)

    # ------------------------------------------------------------------
    # 回复分割（<SEP> 多气泡）
    # ------------------------------------------------------------------
    def send_parts(self, user_id: str, parts: list[str]) -> None:
        """按用户串行发送多条气泡（<SEP> 分段的回复）。

        发送加每用户锁：上一轮回复的所有气泡发完，下一轮才开始，
        避免气泡互相穿插。气泡间等待由段文字数决定（首段定基准）。
        """
        if not parts:
            return
        with self._get_send_lock(user_id):
            # 首段字数决定阅读速度基准：首段 3s 读完
            base_chars = max(1, len(parts[0]))
            try:
                self.messenger.send(user_id, parts[0])
            except SendQuotaExhausted as e:
                console.warn(f"发送配额已满，本次回复剩余气泡暂缓发送: {e}")
                return
            for part in parts[1:]:
                time.sleep(self._sep_delay(part, base_chars))
                try:
                    self.messenger.send(user_id, part)
                except SendQuotaExhausted as e:
                    console.warn(f"发送配额已满，剩余气泡暂缓发送: {e}")
                    return

    def _get_send_lock(self, user_id: str) -> threading.RLock:
        """获取某用户的发送串行锁（惰性创建，线程安全）。"""
        with self._user_locks_guard:
            lock = self._send_locks.get(user_id)
            if lock is None:
                lock = threading.RLock()
                self._send_locks[user_id] = lock
            return lock

    def _split_reply(self, reply: str) -> list[str]:
        """清洗并切分回复为多条气泡消息。

        1. 清洗（config.clean_paren）：删除括号内文本
           （中文（）与英文()，角色扮演神态描写）。
        2. 切分（config.split_newline）：把 \n\n、\n 视为气泡分隔符；
           否则只按 <SEP> 切分。
        每条 trim 后过滤空段；无分隔符时返回整条作为单条消息。
        """
        if getattr(self._config, "clean_paren", True):
            reply = _PAREN_RE.sub("", reply)
        if getattr(self._config, "split_newline", False):
            parts = [p.strip() for p in re.split(r"<SEP>|\n+", reply)]
        else:
            parts = [p.strip() for p in reply.split(_SEP)]
        return [p for p in parts if p]

    @staticmethod
    def _sep_delay(part: str, base_chars: int) -> float:
        """按段文字数计算发送间隔。

        首段字数确定基础阅读速度（首段 3s 读完），后续每段等待 =
        该段字数 × 3s ÷ 首段字数，正常封顶 _SEP_DELAY_MAX(4s)。
        超长段（≥_SEP_LONG_MIN 字）特殊处理：随机 10~20s。
        """
        length = len(part)
        if length >= _SEP_LONG_MIN:
            return random.uniform(_SEP_LONG_DELAY_MIN, _SEP_LONG_DELAY_MAX)
        return min(_SEP_DELAY_MAX, _SEP_DELAY_BASE * length / base_chars)

    # ------------------------------------------------------------------
    # 回复特殊标记注册表：提示词里约定的暗号 → 系统动作
    # ------------------------------------------------------------------
    def _register_default_markers(self) -> None:
        """注册内置标记。新增标记 = 在这里 register + 提示词里写清楚用途。"""
        self.markers.register("letter", self._marker_letter)

    def _marker_letter(self, user_id: str = "") -> str:
        """<letter> 说不出口的话：当前回复照常发送，后台另起一轮写信心会话。

        写信心会话 persist=False（系统消息不加入上下文、不发送给用户），
        LLM 在该轮内调用 letter_write 工具把心里话写成信永久保存。
        """
        if not user_id:
            return "未指定用户，无法写信"
        with self._letter_lock:
            if user_id in self._letter_running:
                return "信件写作已在进行"
            self._letter_running.add(user_id)
        threading.Thread(
            target=self._run_letter_session, args=(user_id,), daemon=True
        ).start()
        return "信件写作会话已后台启动"

    def _run_letter_session(self, user_id: str) -> None:
        """系统另起一轮写信心会话：persist=False，不加入上下文、不发送给用户。"""
        names = self._memory_tool_names()
        task_instruction = (
            "现在静下心来，写一封真正的信给那个重要的人。\n"
            "有些话当面说不出口，用记忆工具写下来：author 固定填 ai，"
            "把心里话完整写在 content 里。这封信只有你能看到，永远不会被发给对方。"
            + (f"\n可用记忆工具：{names}" if names else "")
        )
        try:
            reply = self._run_task_session(user_id, task_instruction, "信件")
            console.mcp(f"信件会话完成: {str(reply)[:100]}")
        except Exception as e:
            console.warn(f"信件会话失败: {e}")
        finally:
            with self._letter_lock:
                self._letter_running.discard(user_id)

    def _run_task_session(
        self,
        user_id: str,
        task_instruction: str,
        task_name: str,
        context: str | None = None,
    ) -> str:
        """
        系统提示注入后不会展现在上下文中
        """
        with self._get_user_lock(user_id):
            prompt = self._config.reload_prompt()
            extra = self._config.reload_prompt_extra()
            if context is not None:
                background = context
            else:
                background = (
                    "以下是过去的对话记录，只作背景参考，"
                    "不需要回复其中任何一条：\n"
                    f"{self._recent_diary_context(user_id)}"
                )
            messages = [
                {
                    "role": "system",
                    "content": f"{prompt}\n{extra}\n当前对话用户 ID: {user_id}",
                },
                {
                    "role": "user",
                    "content": (
                        "[系统指令 - 内部任务，这不是聊天消息，"
                        "不要回复用户]\n"
                        f"{task_instruction}\n"
                        f"{background}\n"
                        "执行完毕后只回复一句简短的收尾语即可"
                        "（这句回复不会被发送）。"
                    ),
                },
            ]
            task_seen: dict = {}
            for _round in range(1, _MAX_AGENT_ROUNDS + 1):
                console.agent_round(_round)

                # RAW 调试视图：内部任务会话也展示思考/回复/工具调用
                rawview = self.rawview
                result = None
                if rawview is not None:
                    rawview.begin_stream(user_id, list(messages), self._tool_defs)
                try:
                    result = self.llm.stream_chat(
                        messages,
                        tools=self._tool_defs,
                        on_chunk=rawview.on_chunk if rawview is not None else None,
                    )
                finally:
                    if rawview is not None:
                        rawview.finish_stream(result.raw if result is not None else {})
                if not result.has_tool_calls:
                    reply = self.markers.process(result.content, user_id=user_id)
                    return reply
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(
                                    call["arguments"], ensure_ascii=False
                                ),
                            },
                        }
                        for call in result.tool_calls
                    ],
                }
                if result.reasoning_content:
                    assistant_msg["reasoning_content"] = result.reasoning_content
                messages.append(assistant_msg)
                self._execute_tool_calls(
                    user_id, messages, result.tool_calls, task_seen, auto_send=False
                )
            raise RuntimeError(
                f"{task_name}会话工具调用超过 {_MAX_AGENT_ROUNDS} 轮上限。"
            )

    def _recent_diary_context(self, user_id: str, limit: int | None = None) -> str:
        """对话记录（只读背景，供内部任务会话使用）；默认载入全部上下文。"""
        if self.store is None:
            return "(无对话记录)"
        try:
            history = self.store.load(user_id)
        except Exception:
            return "(无对话记录)"
        if limit is not None:
            history = history[-limit:]
        lines = []
        for m in history:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:200]
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"我: {content}")
        return "\n".join(lines) or "(无对话记录)"

    # ------------------------------------------------------------------
    # 系统控制指令
    # ------------------------------------------------------------------
    def _handle_control(self, user_id: str, text: str) -> str | None:
        """处理系统控制指令；非指令返回 None（继续正常对话）。

        /help、/清除上下文（及 /清空上下文 别名）、/重置 直接识别，
        无需任何模式切换。
        """
        cmd = text.strip()
        if cmd.lower() == _CMD_HELP:
            return _CONTROL_HELP
        if cmd == _CMD_CONTROL or cmd == _CMD_CONTROL_ALT or cmd.startswith(_CMD_CONTROL + " ") or cmd.startswith(_CMD_CONTROL_ALT + " "):
            return self._handle_llmapi_config(cmd)
        if cmd in (_CMD_CLEAR, _CMD_CLEAR_ALT):
            if self.store is not None:
                self.store.delete(user_id)
            return "已清除你的全部对话上下文。"
        if cmd == _CMD_CLEAR_CHAT:
            return self._clear_chat_history()
        if cmd == _CMD_FORGET:
            return self._request_forget(user_id)
        if cmd == _CMD_CONFIRM_FORGET:
            return self._confirm_forget(user_id)
        if cmd == _CMD_MEMORY_VIEW:
            return self._memory_view()
        if cmd == _CMD_MEMORY_DELETE or cmd.startswith(_CMD_MEMORY_DELETE + " "):
            return self._memory_delete(cmd)
        if cmd == _CMD_MEMORY_RESTORE or cmd.startswith(_CMD_MEMORY_RESTORE + " "):
            return self._memory_restore(cmd)
        if cmd == _CMD_DIARY:
            return self._cmd_diary(user_id)
        if cmd == _CMD_SLEEP:
            return self._cmd_sleep(user_id)
        if cmd == _CMD_LETTER:
            return self._marker_letter(user_id)
        if cmd == _CMD_RESET:
            removed = self._reset_last_user_message(user_id)
            return (
                "已回退你发的上一句话。"
                if removed
                else "没有可回退的消息。"
            )
        if cmd == _CMD_COMPACT:
            result = self._compact_context(user_id)
            if result is None:
                return "上下文压缩失败: 没有可压缩的对话上下文。"
            return (
                "上下文压缩完成。\n"
                f"总结前上下文总量: {result['before']:,} tokens\n"
                f"总结后上下文总量: {result['after']:,} tokens"
            )
        if cmd == _CMD_COMPACT_LIMIT or cmd.startswith(_CMD_COMPACT_LIMIT + " "):
            return self._handle_compact_limit(cmd)
        if cmd == _CMD_INFO:
            return self._info_summary(user_id)
        return None

    def _clear_chat_history(self) -> str:
        """清空平台侧历史聊天记录（委托平台适配器，如 weilink 消息库）。"""
        return self._platform.clear_chat_history()

    # ------------------------------------------------------------------
    # 能力工具：经 capabilities 调用记忆/档案/事件等能力，不硬编码工具名
    # ------------------------------------------------------------------
    def _cap_tool(self, capability: str, tool: str, args: dict) -> str:
        """调用某能力下的工具；能力未注册时返回错误提示而不是抛异常。

        主代码通过能力名 + 工具简称调用，实际工具全名（namespace-xxx）
        由 CapabilityRegistry 从 config.ini/插件 manifest 解析。
        """
        name = self.tools.capabilities.tool(capability, tool)
        if name is None:
            return json.dumps(
                {"error": f"能力 {capability}/{tool} 未启用（检查 [mcpsources] 配置）"},
                ensure_ascii=False,
            )
        return self.tools.call_tool(name, args)

    def _memory_unavailable(self) -> str:
        """记忆能力未启用时的提示（供依赖记忆的命令返回）。"""
        return "记忆系统未启用。请检查 [mcpsources] 中是否配置了 capability=memory 的源。"

    def _memory_tool_names(self) -> str:
        """返回当前生效的记忆工具清单（供任务指令/提示词动态引用）。

        从 capability 注册表取实际工具全名，未启用时返回空串。
        主代码不再硬编码 ombre-* 之类的具体名字。
        """
        if not self.tools.capabilities.has("memory"):
            return ""
        return ", ".join(self.tools.capabilities.tools("memory"))

    def _memory_short_names(self) -> str:
        """返回记忆工具的简称清单（LLM 可直接按名调用，无需知道 namespace）。"""
        if not self.tools.capabilities.has("memory"):
            return ""
        return ", ".join(self.tools.capabilities.tools("memory"))

    # ------------------------------------------------------------------
    # /看记忆 /删记忆 /恢复记忆：查看与管理记忆日记
    # ------------------------------------------------------------------
    def _memory_view(self) -> str:
        """列出记忆日记内容：状态摘要 + 每条记忆一行（目录模式，不调 LLM）。"""
        if not self.tools.capabilities.has("memory"):
            return self._memory_unavailable()
        pulse = self._cap_tool("memory", "breath", {})
        catalog = self._cap_tool("memory", "breath", {"catalog": True, "max_results": 50})
        lines = ["【记忆日记状态】", str(pulse).strip(), "", "【记住了这些事】"]
        cat_text = str(catalog).strip()
        if not cat_text or cat_text.startswith("{"):
            lines.append("（暂无记忆）")
        else:
            lines.append(cat_text)
        lines.append("")
        lines.append(f"删除某条：{_CMD_MEMORY_DELETE} <ID>（从上面的结果里复制 ID）")
        return "\n".join(lines)

    def _memory_delete(self, cmd: str) -> str:
        """删除单条记忆（trace delete=True，实际是移入归档，可用恢复指令找回）。"""
        if not self.tools.capabilities.has("memory"):
            return self._memory_unavailable()
        parts = cmd.split()
        if len(parts) < 2:
            return (
                f"用法：{_CMD_MEMORY_DELETE} <记忆ID>\n"
                f"先发 {_CMD_MEMORY_VIEW} 查看记忆和它们的 ID。"
            )
        bid = parts[1]
        return str(self._cap_tool("memory", "trace", {"bucket_id": bid, "delete": True}))

    def _memory_restore(self, cmd: str) -> str:
        """把已删除（归档）的记忆恢复回来。"""
        if not self.tools.capabilities.has("memory"):
            return self._memory_unavailable()
        parts = cmd.split()
        if len(parts) < 2:
            return (
                f"用法：{_CMD_MEMORY_RESTORE} <记忆ID>\n"
                f"先发 {_CMD_MEMORY_VIEW} 查看记忆和它们的 ID。"
            )
        bid = parts[1]
        return str(self._cap_tool("memory", "trace", {"bucket_id": bid, "restore": True}))

    # ------------------------------------------------------------------
    # /日记 /睡觉 /写信：手动触发记忆系统动作（等同 <dream>/<letter> 暗号）
    # ------------------------------------------------------------------
    def _cmd_diary(self, user_id: str) -> str:
        """/日记 手动触发：后台另起一轮，把今天值得记住的事写进记忆日记。

        会话 persist=False（系统消息不加入上下文、不发送给用户），
        LLM 在该轮内回顾今天的对话并用 hold 工具记下值得记住的事。
        """
        if not user_id:
            return "未指定用户，无法写日记"
        with self._letter_lock:
            if user_id in self._diary_running:
                return "日记会话已在进行"
            self._diary_running.add(user_id)
        threading.Thread(
            target=self._run_diary_session, args=(user_id,), daemon=True
        ).start()
        return "日记会话已后台启动，正在回顾今天……"

    def _run_diary_session(self, user_id: str) -> None:
        """系统另起一轮写今日记忆日记：persist=False，不加入上下文、不发送给用户。"""
        names = self._memory_tool_names()
        task_instruction = (
            "现在为今天写一篇记忆日记。回顾今天和这个人的对话，把值得记住的事"
            "——对方的喜好、约定、重要经历、你真实的感受——用记忆工具记下来，"
            "一两条就够，用你自己的话写，不要编造。"
            + (f"\n可用记忆工具：{names}" if names else "")
        )
        try:
            reply = self._run_task_session(user_id, task_instruction, "日记")
            console.mcp(f"日记会话完成: {str(reply)[:100]}")
        except Exception as e:
            console.warn(f"日记会话失败: {e}")
        finally:
            with self._letter_lock:
                self._diary_running.discard(user_id)

    def _cmd_sleep(self, user_id: str) -> str:
        """/睡觉 手动触发 <dream>：把最近 48 小时的记忆梦喂回模型真正消化。

        消化内容是记忆日记的私密内容，只进后台日志，不发给用户。
        """
        if not user_id:
            return "未指定用户，无法触发消化"
        if not self.tools.capabilities.has("memory"):
            return self._memory_unavailable()
        with self._letter_lock:
            if user_id in self._dream_running:
                return "消化会话已在进行"
            self._dream_running.add(user_id)
        try:
            dream_text = str(self._cap_tool("memory", "dream", {}))
        except Exception as e:
            with self._letter_lock:
                self._dream_running.discard(user_id)
            return f"消化失败: {e}"
        if not dream_text or "没有需要消化" in dream_text:
            with self._letter_lock:
                self._dream_running.discard(user_id)
            return "最近没有需要消化的新记忆，晚安。"
        threading.Thread(
            target=self._run_dream_session, args=(user_id, dream_text), daemon=True
        ).start()
        return "好啦，今天的心事都消化完了，晚安。"

    def _run_dream_session(self, user_id: str, dream_text: str) -> None:
        """后台真正消化：把 dream 文本喂回 LLM，让它读、想、沉淀。"""
        names = self._memory_tool_names()
        task_instruction = (
            "下面是最近 48 小时值得回味的记忆梦（只读背景，不需要回复）。"
            "现在慢慢消化它：沉进去想一遍；真正放下的用记忆工具标记 "
            "digest=1 让它不再反复想起；有新的感悟用记忆工具写下来。"
            + (f"\n可用记忆工具：{names}" if names else "")
        )
        try:
            reply = self._run_task_session(
                user_id, task_instruction, "消化", context=dream_text
            )
            console.mcp(f"消化会话完成: {str(reply)[:100]}")
        except Exception as e:
            console.warn(f"消化会话失败: {e}")
        finally:
            with self._letter_lock:
                self._dream_running.discard(user_id)

    # ------------------------------------------------------------------
    # 每日睡前仪式：凌晨定时检查（信 + dream 消化）
    # ------------------------------------------------------------------
    def run_daily_ritual(self) -> None:
        """每日 4:00 由 DailyRitual 触发：近 24 小时已做过睡前检查则跳过，
        否则后台起一个内部任务会话：dream 消化 → hold 日记 → letter_write 写信，
        并在 data/bedtime_ritual.jsonl 记录本次检查。
        """
        if self._ritual_running:
            console.mcp("睡前仪式已在进行，跳过本次")
            return
        if self._ritual_checked_done():
            console.mcp("睡前仪式检查：近 24 小时已检查过，跳过")
            return
        self._ritual_running = True
        try:
            names = self._memory_tool_names()
            task_instruction = (
                "现在是每天的睡前仪式时间，请完成今天的心事收尾：\n"
                "1. 先用记忆工具消化最近 48 小时的心事，看看今天都经历了什么；\n"
                "2. 然后根据消化内容用记忆工具写一篇今天的日记（给自己的零散记录）；\n"
                "3. 最后用记忆工具写一封信（author 固定填 ai）——写给谁都可以："
                "自己、重要的人、任何人，把今天想说的话完整写下来。\n"
                "如果今天已经写过信、也消化过了，直接回复 <none> 表示无需执行。"
                + (f"\n可用记忆工具：{names}" if names else "")
            )
            console.mcp("睡前仪式：开始 dream → 日记 → 写信会话")
            reply = self._run_task_session("", task_instruction, "睡前仪式")
            console.mcp(f"睡前仪式完成: {str(reply)[:100]}")
        except Exception as e:
            console.warn(f"睡前仪式失败: {e}")
        finally:
            self._ritual_record()
            self._ritual_running = False

    def _ritual_checked_done(self) -> bool:
        """近 24 小时内是否已做过睡前检查（看 data/bedtime_ritual.jsonl 最后一条）。"""
        try:
            record = _BASE_DIR / "data" / "bedtime_ritual.jsonl"
            if not record.exists():
                return False
            lines = [
                l
                for l in record.read_text(encoding="utf-8", errors="ignore")
                .splitlines()
                if l.strip()
            ]
            if not lines:
                return False
            last_time = datetime.fromisoformat(json.loads(lines[-1]).get("time", ""))
            return datetime.now() - last_time < timedelta(hours=24)
        except Exception:
            return False

    def _ritual_record(self) -> None:
        """把本次睡前检查追加到 data/bedtime_ritual.jsonl。"""
        try:
            record = _BASE_DIR / "data" / "bedtime_ritual.jsonl"
            record.parent.mkdir(parents=True, exist_ok=True)
            with open(record, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "result": "done",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception as e:
            console.warn(f"睡前检查记录写入失败: {e}")

    # ------------------------------------------------------------------
    # /清除记忆：两阶段确认后清除该用户全部相关数据
    # ------------------------------------------------------------------
    def _request_forget(self, user_id: str) -> str:
        """第一阶段：标记等待确认，回复确认指令。"""
        with self._forget_lock:
            self._forget_state[user_id] = {
                "waiting": True,
                "requested_at": time.monotonic(),
            }
        return (
            f"清除记忆将删除与你有关的全部内容：\n"
            f"  · 对话历史存档\n"
            f"  · 用户档案（{_CMD_CONTROL} 记录的性格/爱好/待办等）\n"
            f"  · 话题兴趣、待办清单、日程事件\n"
            f"  · 平台侧消息记录、语音文件\n"
            f"  · 长期情感记忆（全部记忆数据，无论谁记录的）\n"
            f"  此操作不可恢复。确认请回复：{_CMD_CONFIRM_FORGET}\n"
            f"  （{_FORGET_CONFIRM_TTL} 秒内有效，取消请直接说别的事）"
        )

    def _confirm_forget(self, user_id: str) -> str:
        """第二阶段：确认后真正清除该用户全部数据。"""
        with self._forget_lock:
            state = self._forget_state.get(user_id)
            if state is None or not state.get("waiting"):
                return (
                    f"没有待确认的清除请求。如需清除请先发送 {_CMD_FORGET}。"
                )
            if time.monotonic() - state.get("requested_at", 0) > _FORGET_CONFIRM_TTL:
                del self._forget_state[user_id]
                return "确认已过期，如需清除请重新发送 /清除记忆。"
            del self._forget_state[user_id]
        return self._clear_user_all(user_id)

    def _clear_user_all(self, user_id: str) -> str:
        """清除指定用户的全部相关数据，返回清理摘要。

        MCP 插件数据按各插件 storage_info 声明删除；未声明 storage_info 的
        插件进入兼容模式：无法删除，但会列出插件名提示用户。
        """
        results: list[str] = []
        compat_plugins: list[str] = []

        # 1. 对话历史存档
        if self.store is not None:
            self.store.delete(user_id)
            results.append("对话存档")
        # 2. 平台侧数据（消息库 + 语音 + 引用缓存）
        platform_result = self._platform.clear_user_data(user_id)
        if platform_result and platform_result != "无":
            results.append(f"平台数据({platform_result})")
        # 3. 外部 MCP 插件数据：按各插件 storage_info 声明删除
        self._clear_mcp_user_data(user_id, results, compat_plugins)
        # 4. 内存状态：追催提醒 / 合并缓冲 / 清除确认
        self._cancel_reminder(user_id)
        with self._buffer_lock:
            self._buffers.pop(user_id, None)
        with self._forget_lock:
            self._forget_state.pop(user_id, None)
        # 5. 已触发事件 id（fired_events.json 只记 id 不记用户，无法精确区分，
        #    跳过；靠事件自然过期兜底，不影响功能）
        msg = "已清除与你有关的全部记忆。" + (
            "（具体清理: " + "、".join(results) + "）" if results else ""
        )
        if compat_plugins:
            msg += (
                "\n兼容模式：以下插件未声明数据存储位置，无法删除其数据："
                + "、".join(compat_plugins)
            )
        return msg

    def _clear_mcp_user_data(
        self, user_id: str, results: list[str], compat_plugins: list[str]
    ) -> None:
        """按各外部 MCP 源的 storage_info 声明删除该用户数据。

        插件实现 storage_info(user_id) 并返回 {"user_data": [...]}，bot 依
        声明删除：
          - {"kind": "file", "path": "..."}   删除指定文件
          - {"kind": "db", "path": "...", "table": "...",
             "user_column": "...", "user_value": "..."}
                                                删除表中该用户的全部行
        未实现 storage_info 的插件进入兼容模式，数据无法删除。
        """
        try:
            declarations = self.tools.get_storage_declarations(user_id)
        except Exception as e:
            console.warn(f"获取 MCP 存储声明失败: {e}")
            return

        for item in declarations:
            name = item["name"]
            if not item["declared"]:
                compat_plugins.append(name)
                continue
            if item["error"]:
                console.warn(f"MCP 源 {name} storage_info 调用失败: {item['error']}")
                compat_plugins.append(name)
                continue
            declaration = item["declaration"] or {}
            user_data = declaration.get("user_data") or []
            removed = False
            for entry in user_data:
                kind = entry.get("kind")
                try:
                    if kind == "file" and self._storage_delete_file(entry):
                        removed = True
                    elif kind == "dir" and self._storage_delete_dir(entry):
                        removed = True
                    elif kind == "db" and self._storage_delete_db_rows(entry):
                        removed = True
                except Exception as e:
                    console.warn(f"MCP 源 {name} 删除 {kind} 数据失败: {e}")
            if removed:
                results.append(name)

    @staticmethod
    def _storage_delete_file(entry: dict) -> bool:
        """删除 storage_info 声明里的单个文件，返回是否删除了文件。"""
        from pathlib import Path as _Path

        path = _Path(entry.get("path", ""))
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _storage_delete_dir(entry: dict) -> bool:
        """清空 storage_info 声明里的目录（保留目录本身，让服务自动重建），
        返回是否清理了内容。占用中的文件（如 DB）跳过，不阻塞整体删除。"""
        import shutil
        from pathlib import Path as _Path

        path = _Path(entry.get("path", ""))
        if not path.is_dir():
            return False
        count = 0
        for child in path.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            except OSError:
                continue
            count += 1
        return count > 0

    @staticmethod
    def _storage_delete_db_rows(entry: dict) -> bool:
        """删除 storage_info 声明里数据库表中的用户行，返回是否删除了行。"""
        import sqlite3
        from pathlib import Path as _Path

        path = _Path(entry.get("path", ""))
        table = entry.get("table", "")
        column = entry.get("user_column", "")
        value = entry.get("user_value", "")
        if not path.exists() or not table or not column:
            return False
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE {column} = ?", (value,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # /info：上下文占用统计 + CPU/GPU + 工具列表
    # ------------------------------------------------------------------
    def _info_summary(self, user_id: str) -> str:
        """快速查看：上下文窗口大小/占比、工具调用次数与占比、CPU/GPU、工具列表。"""
        history = self._load_history(user_id)
        limit = getattr(self._config, "compact_token_limit", _COMPACT_TOKEN_LIMIT)
        stats = self._context_stats(history)
        total = stats["total"]

        lines = ["[上下文]"]
        lines.append(
            f"当前 {total:,} / {limit:,} tokens（{100.0 * total / limit if limit else 0:.1f}%）"
        )
        if total > 0:
            for label, key in (
                ("用户输入", "user"),
                ("LLM 输出", "assistant"),
                ("工具结果", "tool"),
            ):
                v = stats[key]
                lines.append(f"  {label}: {v:,} tokens（{100.0 * v / total:.1f}%）")
        else:
            lines.append("  （暂无对话上下文）")
        lines.append(f"  工具调用: {stats['tool_calls']} 次")

        cpu = self._cpu_usage()
        gpu = self._gpu_usage()
        lines.append(
            "[系统] "
            + (f"CPU: {cpu:.1f}%" if cpu >= 0 else "CPU: 不可用")
            + (f"  GPU: {gpu:.0f}%" if gpu is not None else "  GPU: 不可用")
        )

        tools = [t["function"]["name"] for t in self._tool_defs]
        lines.append(f"[工具] {len(tools)} 个:")
        lines.append(", ".join(tools))
        return "\n".join(lines)

    @staticmethod
    def _context_stats(history: list[dict]) -> dict:
        """按角色统计上下文 token 与工具调用次数（1 字符≈1 token 估算）。

        用户输入 = user 消息；LLM 输出 = assistant 的 content + 思考内容 +
        工具调用参数；工具结果 = tool 消息。
        """
        user_tokens = assistant_tokens = tool_tokens = tool_calls = 0
        for m in history:
            role = m.get("role")
            content = m.get("content")
            if role == "user":
                user_tokens += OpenCompanion._estimate_tokens(content)
            elif role == "assistant":
                t = OpenCompanion._estimate_tokens(content)
                t += OpenCompanion._estimate_tokens(m.get("reasoning_content"))
                tcs = m.get("tool_calls")
                if tcs:
                    tool_calls += len(tcs)
                    t += sum(
                        OpenCompanion._estimate_tokens(c.get("function", {}).get("arguments"))
                        for c in tcs
                    )
                assistant_tokens += t
            elif role == "tool":
                tool_tokens += OpenCompanion._estimate_tokens(content)
        total = user_tokens + assistant_tokens + tool_tokens
        return {
            "total": total,
            "user": user_tokens,
            "assistant": assistant_tokens,
            "tool": tool_tokens,
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _cpu_usage() -> float:
        """瞬时 CPU 使用率（%）。跨平台实现：Windows 用 GetSystemTimes，POSIX 用 /proc/stat。"""
        if os.name == "nt":
            return OpenCompanion._cpu_usage_windows()
        return OpenCompanion._cpu_usage_posix()

    @staticmethod
    def _cpu_usage_windows() -> float:
        """Windows：两次 GetSystemTimes 采样差值。"""
        try:
            import ctypes

            class _FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", ctypes.c_uint32),
                    ("dwHighDateTime", ctypes.c_uint32),
                ]

            def _sample():
                ft_idle, ft_kernel, ft_user = (
                    _FILETIME(),
                    _FILETIME(),
                    _FILETIME(),
                )
                ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(ft_idle),
                    ctypes.byref(ft_kernel),
                    ctypes.byref(ft_user),
                )
                return ft_idle, ft_kernel, ft_user

            idle1, kernel1, user1 = _sample()
            import time as _t

            _t.sleep(0.1)
            idle2, kernel2, user2 = _sample()

            def _us(ft) -> int:
                return (ft.dwHighDateTime << 32 | ft.dwLowDateTime) // 10

            idle = _us(idle2) - _us(idle1)
            kernel = _us(kernel2) - _us(kernel1)
            user = _us(user2) - _us(user1)
            total = kernel + user
            if total <= 0:
                return 0.0
            return 100.0 * (1 - idle / total)
        except Exception:
            return -1.0

    @staticmethod
    def _cpu_usage_posix() -> float:
        """POSIX：两次 /proc/stat 采样差值（Linux/容器内可用）。"""
        try:
            import time as _t

            def _sample():
                with open("/proc/stat", "r", encoding="utf-8") as f:
                    parts = f.readline().split()
                if not parts or not parts[0].startswith("cpu"):
                    raise OSError("unexpected /proc/stat format")
                nums = [int(x) for x in parts[1:]]
                total = sum(nums)
                # 列: user nice system idle iowait irq softirq steal ...
                idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
                return total, idle

            total1, idle1 = _sample()
            _t.sleep(0.1)
            total2, idle2 = _sample()
            dt_total = total2 - total1
            dt_idle = idle2 - idle1
            if dt_total <= 0:
                return 0.0
            return max(0.0, min(100.0, 100.0 * (1 - dt_idle / dt_total)))
        except Exception:
            return -1.0

    @staticmethod
    def _gpu_usage() -> float | None:
        """NVIDIA GPU 使用率（%）；无 GPU 或不可用时返回 None。"""
        import subprocess

        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if out.returncode == 0 and out.stdout.strip():
                return float(out.stdout.strip().splitlines()[0])
        except Exception:
            pass
        return None

    def _handle_llmapi_config(self, cmd: str) -> str:
        """处理 /控制（/参数配置）指令：查看或修改 LLM 配置（立即生效 + 持久化）。"""
        for prefix in (_CMD_CONTROL, _CMD_CONTROL_ALT):
            if cmd == prefix or cmd.startswith(prefix + " "):
                arg = cmd[len(prefix):].strip()
                break
        else:
            return _LLMAPI_HELP
        if not arg:
            c = self._config
            return (
                f"当前 LLM 配置：\n"
                f"  model = {c.model}\n"
                f"  thinking = {c.thinking}\n"
                f"  reasoning_effort = {c.reasoning_effort}\n"
                f"  compact_token_limit = {c.compact_token_limit}\n"
                + _LLMAPI_HELP
            )
        if "=" not in arg:
            return _LLMAPI_HELP
        key, _, value = arg.partition("=")
        try:
            return self._config.set_llmapi(key, value)
        except ValueError as e:
            return f"设置失败：{e}"

    def _handle_compact_limit(self, cmd: str) -> str:
        """处理 /修改上下文限制 指令：查看或修改压缩触发阈值。"""
        arg = cmd[len(_CMD_COMPACT_LIMIT):].strip()
        if not arg:
            return (
                f"当前上下文压缩触发阈值: {self._config.compact_token_limit:,} tokens\n"
                f"用法: {_CMD_COMPACT_LIMIT} <数值>，支持 k/万/w 后缀，如 200k、20万"
            )
        try:
            return self._config.set_llmapi("compact_token_limit", arg)
        except ValueError as e:
            return f"设置失败：{e}"

    def _load_history(self, user_id: str) -> list[dict]:
        """加载该用户的对话历史（优先从存档读取）。"""
        if self.store is not None:
            return self.store.load(user_id)
        return []

    def _reset_last_user_message(self, user_id: str) -> bool:
        """仅回退用户发的上一句话。

        找到历史中最后一条 role=user 的消息（即 AI 最后回复的那轮
        用户输入），把该条及其之后的 assistant/tool 消息一并删除，
        并同步到存档。
        """
        hist = self._load_history(user_id)
        if not hist:
            return False
        for i in range(len(hist) - 1, -1, -1):
            if hist[i].get("role") == "user":
                del hist[i:]
                if self.store is not None:
                    self.store.save(user_id, hist)
                return True
        return False

    # ------------------------------------------------------------------
    # 上下文压缩（context compaction）
    # ------------------------------------------------------------------
    @staticmethod
    def _estimate_tokens(content) -> int:
        """粗略估算单条消息的 token 数（1 字符 ≈ 1 token）。

        中文每字约 1~1.5 token，英文约 4 字符/token，此估算偏保守，
        实际精度不影响功能（阈值可自定义）。
        """
        if not isinstance(content, str) or not content:
            return 0
        return len(content)

    def _context_tokens(self, history: list[dict]) -> int:
        """历史全部消息（含工具调用/工具结果/总结记录）的估算总 token 数。"""
        return sum(self._estimate_tokens(m.get("content")) for m in history)

    def _should_compact(self, user_id: str) -> bool:
        """历史估算 token 数是否已超过压缩触发阈值。"""
        history = self._load_history(user_id)
        limit = getattr(self._config, "compact_token_limit", _COMPACT_TOKEN_LIMIT)
        return self._context_tokens(history) >= limit

    def _compact_context(self, user_id: str) -> dict | None:
        """让 LLM 以 system 口吻总结全部对话并写入档案，然后压缩历史。

        总结文本作为 [对话总结] system 消息保留（跨重启的记忆），
        只保留最近 _COMPACT_KEEP_ROUNDS 轮完整对话。
        返回 {"before": 压缩前 token 数, "after": 压缩后 token 数}，失败返回 None。
        """
        history = self._load_history(user_id)
        if not history:
            return None
        before = self._context_tokens(history)
        console.warn(f"开始总结压缩上下文: {user_id}")
        prompt = self._config.reload_prompt()
        prompt = f"{prompt}\n{self._config.reload_prompt_extra()}"
        archive_tool = self.tools.capabilities.tool("archive", "add_record") or ""
        messages = [
            {"role": "system", "content": f"{prompt}\n当前对话用户 ID: {user_id}"},
            {"role": "system", "content": _compact_prompt(archive_tool)},
        ]
        messages.extend(history)

        # 独立 agent 循环：允许调用工具（写档案），最终取纯文本总结
        summary = ""
        try:
            seen_calls: dict = {}
            for _round in range(1, _MAX_AGENT_ROUNDS + 1):
                result = self.llm.stream_chat(messages, tools=self._tool_defs)
                if not result.has_tool_calls:
                    summary = result.content or ""
                    break
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(
                                    call["arguments"], ensure_ascii=False
                                ),
                            },
                        }
                        for call in result.tool_calls
                    ],
                }
                if result.reasoning_content:
                    assistant_msg["reasoning_content"] = result.reasoning_content
                messages.append(assistant_msg)
                self._execute_tool_calls(
                    user_id, messages, result.tool_calls, seen_calls, auto_send=False
                )
        except Exception as e:
            console.error(f"自动总结失败: {e}")
        if not summary:
            console.warn("自动总结生成为空，仅保留最近对话")

        new_history = []
        if summary:
            new_history.append(
                {"role": "system", "content": f"{_COMPACT_MARK}\n{summary}"}
            )
        keep = history[-_COMPACT_KEEP_ROUNDS * 2 :]
        new_history.extend(keep)
        if self.store is not None:
            self.store.save(user_id, new_history)
        after = self._context_tokens(new_history)
        console.warn(f"上下文已压缩: 保留最近 {_COMPACT_KEEP_ROUNDS} 轮 + 总结")
        return {"before": before, "after": after}

    # ------------------------------------------------------------------
    # LLM agent 循环
    # ------------------------------------------------------------------
    def _handle_auto_send(self, user_id: str, output: str) -> str:
        """识别工具返回里的 auto_send 标记，直接发送媒体并改写给 LLM 的结果。

        MCP 工具（如 tts）生成媒体后返回
        {"auto_send": {"kind": "voice"|"image"|..., "path": "..."}}，
        bot 直接调用平台适配器的媒体发送把媒体发给当前用户，不再让 LLM
        二次调用 send，节省一次 agent 往返。返回给 LLM 的文本改为提示
        "已自动发送"，避免模型重复调 send。
        """
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return output
        if not isinstance(data, dict) or "auto_send" not in data:
            return output

        spec = data["auto_send"]
        if not isinstance(spec, dict):
            return output
        kind = spec.get("kind", "voice")
        path = spec.get("path", "")
        if not path:
            return output

        # 发送媒体（格式转换如语音→SILK 由平台适配器内部处理）；
        # 成功后回传给 LLM 一个明确的完成提示
        ok, result = self._platform.send_media(user_id, kind, path)
        if ok:
            console.auto_send(user_id, kind, path)
            data["text"] = data.get("text") or f"{kind} 已自动发送，无需再调 send"
            if isinstance(data.get("auto_send"), dict):
                data["auto_send"]["path"] = path
            return json.dumps(data, ensure_ascii=False)
        # 发送失败：把错误原样给 LLM，让它决定降级
        console.warn(f"auto_send {kind} 失败: {result}")
        return json.dumps({"error": result}, ensure_ascii=False)

    def _run_agent(
        self,
        user_id: str,
        user_text: str,
        system_extra: str = "",
        persist: bool = True,
        image_path: str = "",
        video_path: str = "",
    ) -> str:
        """标准的工具调用 agent 循环（同一用户串行执行）。

        用户消息合并线程 / 主动追问 / 事件提醒都可能从不同线程
        并发调用本方法。若不同一用户串行，多次 LLM 生成会并发读写同一份
        历史，导致上下文互相污染、回复只发最后一条。
        """
        with self._get_user_lock(user_id):
            return self._run_agent_inner(
                user_id, user_text, system_extra, persist, image_path, video_path
            )

    def _get_user_lock(self, user_id: str) -> threading.RLock:
        """获取某用户的串行锁（惰性创建，线程安全）。"""
        with self._user_locks_guard:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = threading.RLock()
                self._user_locks[user_id] = lock
            return lock

    def _run_agent_inner(
        self,
        user_id: str,
        user_text: str,
        system_extra: str = "",
        persist: bool = True,
        image_path: str = "",
        video_path: str = "",
    ) -> str:
        """标准的工具调用 agent 循环（需已持用户串行锁）。

        基于该用户的完整历史构建 messages，带 tools 调 LLM → 若有
        tool_calls 则逐个执行并回传结果 → 重复直到 LLM 返回纯文本。
        persist=True 时把本轮（用户输入 + assistant 工具调用 + tool 结果 +
        最终回复）写入历史；persist=False（系统唤起，如追问/提醒）则
        不写历史，仅生成一条消息供发送，不污染上下文。

        system_extra: 可选，追加一条 system 角色指令（用于系统主动提醒）。
        """
        # 普通对话每满 50 轮：先让 LLM 总结对话并写档案，压缩旧上下文
        if not system_extra and self._should_compact(user_id):
            self._compact_context(user_id)

        messages = self._build_messages(user_id, user_text, system_extra, image_path, video_path)
        seen_calls: dict = {}

        for _round in range(1, _MAX_AGENT_ROUNDS + 1):
            console.agent_round(_round)

            # RAW 调试视图：流式会话（实时展示思考/回复/工具调用）
            rawview = self.rawview
            result = None
            if rawview is not None:
                rawview.begin_stream(user_id, list(messages), self._tool_defs)
            try:
                result = self.llm.stream_chat(
                    messages,
                    tools=self._tool_defs,
                    on_chunk=rawview.on_chunk if rawview is not None else None,
                )
            finally:
                if rawview is not None:
                    rawview.finish_stream(result.raw if result is not None else {})

            if not result.has_tool_calls:
                reply = result.content
                # 特殊标记（<dream> 等）：先执行系统动作并剥掉标记，
                # 再处理 <none>（选择不回复）
                reply = self.markers.process(reply, user_id=user_id)
                if reply.strip() != _NONE_TAG:
                    messages.append({"role": "assistant", "content": reply})
                if persist:
                    self._save_history(user_id, messages)
                return reply

            # 记录 assistant 的工具调用（V4 要求带 reasoning_content 回传，否则下轮 400）
            assistant_msg: dict = {
                "role": "assistant",
                "content": result.content or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                        },
                    }
                    for call in result.tool_calls
                ],
            }
            if result.reasoning_content:
                assistant_msg["reasoning_content"] = result.reasoning_content
            messages.append(assistant_msg)

            # 逐个执行并回传结果（同名同参的重复调用会被拦截提示）
            self._execute_tool_calls(user_id, messages, result.tool_calls, seen_calls)

        raise RuntimeError(f"工具调用超过 {_MAX_AGENT_ROUNDS} 轮上限。")

    def _execute_tool_calls(
        self,
        user_id: str,
        messages: list[dict],
        tool_calls: list[dict],
        seen: dict,
        auto_send: bool = True,
    ) -> None:
        """执行一轮工具调用并回传结果（防重复调用）。

        同一轮内（跨 agent round）已用完全相同参数调用过的工具不重复执行：
        直接回一条系统警告，阻止 LLM 反复查同一个结果、空转浪费轮次。
        """
        for call in tool_calls:
            name = call["name"]
            args_json = json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False)
            console.tool_call(name, args_json)
            key = (name, args_json)
            dup = seen.get(key, 0)
            seen[key] = dup + 1
            if dup > 0:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": (
                            f"（系统）你本轮已经用完全相同的参数调用过工具 {name}，"
                            "再次调用结果不会改变。请立即停止重复调用工具，"
                            "直接基于已有信息回答。"
                        ),
                    }
                )
                continue
            t_tool = time.perf_counter()
            output = self.tools.call_tool(name, call["arguments"])
            console.tool_result(name, time.perf_counter() - t_tool, output)
            if auto_send:
                output = self._handle_auto_send(user_id, output)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                }
            )

    def _build_messages(self, user_id: str, user_text: str, system_extra: str = "", image_path: str = "", video_path: str = "") -> list[dict]:
        history = self._load_history(user_id)
        prompt = self._config.reload_prompt()
        # 自动追加尾部指令（合并消息 + <none> 等规则，来自 prompt_extra.txt）
        prompt = f"{prompt}\n{self._config.reload_prompt_extra()}"
        messages = [
            {"role": "system", "content": f"{prompt}\n当前对话用户 ID: {user_id}"}
        ]
        if system_extra:
            messages.append({"role": "system", "content": system_extra})
        elif (
            not user_text.startswith("(system ")
            and self._is_new_conversation(history)
        ):
            names = self._memory_tool_names()
            guidance = (
                "（系统）对方隔了很久才重新找你，这是新一轮对话的开始。"
                "先用工具回想一遍相关记忆，然后自然地和对方聊起来。"
            )
            if names:
                guidance += f"\n可用记忆工具：{names}。"
            messages.append({"role": "system", "content": guidance})
        messages.extend(history)
        if not user_text.startswith("(system "):
            stamp = time.strftime("%Y-%m-%d %H:%M")
            user_msg = {"role": "user", "content": f"{user_text} systime:{stamp}"}
            # 图片/视频消息：把本地媒体转成多模态 content 数组（data URL）
            media_parts: list[dict] = []
            if image_path and self._config.enable_image:
                img_payload = self._build_image_content(image_path)
                if img_payload is not None:
                    media_parts.append(
                        {"type": "image_url", "image_url": {"url": img_payload}}
                    )
            if video_path and self._config.enable_video:
                vid_payload = self._build_video_content(video_path)
                if vid_payload is not None:
                    media_parts.append(
                        {"type": "video_url", "video_url": {"url": vid_payload}}
                    )
            if media_parts:
                user_msg["content"] = [
                    {"type": "text", "text": f"{user_text} systime:{stamp}"},
                    *media_parts,
                ]
            messages.append(user_msg)
        return messages

    @staticmethod
    def _build_image_content(image_path: str) -> str | None:
        """把本地图片读取为 data URL（失败返回 None）。"""
        import base64
        import mimetypes

        try:
            with open(image_path, "rb") as f:
                data = f.read()
        except OSError as e:
            console.warn(f"读取图片失败: {e}")
            return None
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    @staticmethod
    def _build_video_content(video_path: str) -> str | None:
        """把本地视频读取为 data URL（失败返回 None，视频须 <50MB）。"""
        import base64
        import mimetypes

        try:
            with open(video_path, "rb") as f:
                data = f.read()
        except OSError as e:
            console.warn(f"读取视频失败: {e}")
            return None
        if len(data) > 50 * 1024 * 1024:
            console.warn(f"视频过大（>50MB），无法送入模型: {video_path}")
            return None
        mime = mimetypes.guess_type(video_path)[0] or "video/mp4"
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    def _is_new_conversation(self, history: list[dict]) -> bool:
        """无历史 → True；最后一条用户消息距今超过阈值 → True；否则 False。"""
        if not history:
            return True
        last_user = next(
            (m for m in reversed(history) if m.get("role") == "user"), None
        )
        if last_user is None:
            return False
        m = _SYSTIME_RE.search(str(last_user.get("content", "")))
        if not m:
            return False
        try:
            last_time = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        except ValueError:
            return False
        return datetime.now() - last_time > timedelta(hours=_NEW_CONVO_BREATH_HOURS)

    def _save_history(self, user_id: str, messages: list[dict]) -> None:
        """把本轮完整对话（含工具调用）保存为该用户的新历史。

        存档前剥离：system 提示词（保留压缩标记）、tool 工具结果消息、
        带 tool_calls 的 assistant 消息、reasoning_content——工具结果
        已被 LLM 消化进最终回复，历史里无需重复堆积；本轮会话内
        （发送请求）仍保留完整消息，协议要求 tool_calls 与结果配对回传。

        启用存档时写入 conversation/ 目录，实现跨重启连续对话。
        """
        history = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                # 只保留长期有效的压缩总结；问候/提醒指令是时间敏感的临时
                # 指令（含"现在几点"等过期信息），不持久化，避免历史堆积
                # 与时间误导。当轮会话消息流仍完整（不受影响）。
                if (
                    isinstance(m.get("content"), str)
                    and m["content"].startswith(_COMPACT_MARK)
                ):
                    history.append(m)
                continue
            if role == "tool":
                continue
            if role == "assistant" and m.get("tool_calls"):
                continue
            m2 = dict(m)
            m2.pop("reasoning_content", None)
            # 图片/视频消息的 content 是多模态数组：历史里只保留文本部分，
            # 避免把 base64 媒体数据写进 conversation 存档。
            content = m2.get("content")
            if isinstance(content, list):
                texts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                m2["content"] = "".join(texts)
            history.append(m2)
        if self.store is not None:
            self.store.save(user_id, history)
