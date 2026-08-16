"""主动问候调度器：轮询 revive MCP 引擎，决定是否主动打扰用户。

MCP stdio 服务器是被动响应，无法主动推送，因此由 bot 端后台线程
周期性调用 revive 的 love_tick 工具，三阶段决策（泊松 + 信息增益 +
贝叶斯）判定"该不该、什么时候主动问候"：

    - love_tick 返回 should_send=True 时，以 system 口吻让 LLM 像真人
      一样主动发起对话（不暴露"定时/系统"机制），生成的消息直接发送；
    - 发送后调用 love_record_send 记录未回复计数；
    - 用户回复时由 OpenCompanion.on_message 调用 record_user_reply，
      把回复速度/长度反馈给引擎做贝叶斯学习。

用户列表来自 revive 的 love_list_users（有引擎状态的用户），
避免 conversation 存档文件名（@ 会被替换成 _）与用户 ID 不一致。
"""

import json
import threading
import time
from datetime import datetime

from botapp.console import console

_NAMESPACE = "revive"
_POLL_INTERVAL = 60.0  # 轮询间隔（秒）；love_tick 内部有 check_interval 节奏控制


class ReviveTrigger:
    """后台线程调度器：定期检测 revive 决策，到期主动问候。"""

    def __init__(self, bot, interval: float = _POLL_INTERVAL) -> None:
        self._bot = bot
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 每个用户上次的 (渴望度原始值, 效用)，变化时输出 BrainStatusUpdate
        self._last_sig: dict[str, tuple[float, float]] = {}

    def start(self) -> None:
        """启动后台轮询线程（daemon，随主进程退出）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="revive-trigger", daemon=True
        )
        self._thread.start()
        console.config(
            f"主动问候决策器已启动"
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_all()
            except Exception as e:
                console.warn(f"主动问候检测出错: {e}")
            self._stop.wait(self._interval)

    def _invoke(
        self,
        name: str,
        args: dict,
        quiet: bool = False,
        quiet_result: bool = False,
    ) -> str:
        """调用 revive MCP 工具，把返回结果解析成中文摘要输出。

        quiet=True 时不打印"调用"行（轮询类工具，减少噪音）；
        quiet_result=True 时连返回摘要也不打印（love_tick 的决策输出
        由 _check_user 按变化统一控制，避免每轮刷屏）。
        """
        tool_name = f"{_NAMESPACE}-{name}"
        if not quiet:
            try:
                console.plugins(f"调用 {tool_name}: {json.dumps(args, ensure_ascii=False)}")
            except (TypeError, ValueError):
                console.plugins(f"调用 {tool_name}: {args}")
        raw = self._bot.tools.call_tool(tool_name, args)
        if not quiet_result:
            try:
                console.plugins(self._summarize(name, raw))
            except Exception:
                console.plugins(f"返回 {tool_name}: {raw[:400]}")
        return raw

    @staticmethod
    def _summarize(name: str, raw) -> str:
        """把 revive 工具返回解析成中文摘要（单行紧凑）。"""
        data = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return f"返回 {name}: {raw[:400]}"

        if isinstance(data, dict) and "error" in data:
            return f"返回 {name}: 错误 {data['error']}"

        # 单行格式：返回 name: k=v k=v ...
        if isinstance(data, dict):
            zh = {
                "inferred_state_zh": "状态",
                "confidence": "置信度",
                "observations": "观测数",
                "learned_params": "已学习",
                "message": "消息",
            }
            parts = [f"{zh.get(k, k)}={v}" for k, v in data.items()]
            return f"返回 {name}: " + " | ".join(parts)
        return f"返回 {name}: {str(data)[:400]}"

    def _check_all(self) -> None:
        """遍历有 revive 引擎状态的用户，逐个检查是否该主动问候。"""
        for user_id in self._list_users():
            try:
                self._check_user(user_id)
            except Exception as e:
                console.warn(f"主动问候检测用户失败 {user_id}: {e}")

    def _list_users(self) -> list[str]:
        """调用 revive 获取有引擎状态的用户 ID 列表。

        兼容两种返回形态：
          - JSON 数组字符串：["uid1", "uid2"]
          - 裸字符串：单用户时 MCP 可能直接返回 "uid"（非 JSON）
        """
        try:
            raw = self._invoke(
                "love_list_users", {}, quiet=True, quiet_result=True
            )
        except Exception as e:
            console.warn(f"获取 revive 用户列表失败: {e}")
            return []
        return self._parse_users(raw)

    @staticmethod
    def _parse_users(raw) -> list[str]:
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return []
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                return [s.strip('"\' ')]
            if isinstance(data, dict) and "error" in data:
                return []
            if isinstance(data, list):
                return [u for u in data if isinstance(u, str)]
            if isinstance(data, str):
                return [data]
        elif isinstance(raw, list):
            return [u for u in raw if isinstance(u, str)]
        return []

    def _check_user(self, user_id: str) -> None:
        """对单个用户跑一次 love_tick；should_send 则主动问候。

        决策日志只输出状态变化：渴望度/效用任何一项变化才发
        BrainStatusUpdate（含升/降百分比），两项都不变则完全静默。
        """
        try:
            raw = self._invoke(
                "love_tick", {"user_id": user_id}, quiet=True, quiet_result=True
            )
        except Exception as e:
            console.warn(f"调用 love_tick 失败 {user_id}: {e}")
            return
        decision = self._parse_decision(raw)
        if decision is None:
            console.warn(f"love_tick 返回无法解析 {user_id}: {raw[:120]}")
            return
        text = self._status_changed(user_id, decision)
        if text is not None:
            console.plugins(text)
        if not decision.get("should_send"):
            return
        full_id = self._bot.resolve_user_id(user_id)
        self._greet(full_id, decision)

    def _status_changed(self, user_id: str, decision: dict) -> str | None:
        """渴望度/效用相对上次是否变化；变化则返回 BrainStatusUpdate 文本。

        格式：渴望度30% (↑20%) | 效用 0.00 →
          - 渴望度：显示当前值 + 与上次相比的百分点升降（↑20% / ↓10%）；
          - 效用：显示当前值，变化则标注 ↑/↓ 差值，不变则 →；
          - 首次见到该用户时输出基线（标记"首次"）；
          - should_send=True 是重大事件，无论如何都输出。
        渴望度用原始值 1% 阈值：引擎浮点微抖（42.4%→42.6%）不算变化，
        避免取整边界造成"↑1%"的假更新。
        """
        prob = float(decision.get("probability", 0))
        util = round(float(decision.get("send_utility", 0)), 2)
        should = bool(decision.get("should_send"))
        pct = round(prob * 100)
        last = self._last_sig.get(user_id)
        if last is None:
            self._last_sig[user_id] = (prob, util)
            return f"BrainStatusUpdate: 渴望度{pct}% (首次) | 效用 {util:.2f} →"
        last_prob, last_util = last
        self._last_sig[user_id] = (prob, util)
        if abs(prob - last_prob) < 0.01 and util == last_util and not should:
            return None
        if abs(prob - last_prob) >= 0.01:
            delta = pct - round(last_prob * 100)
            prob_part = f"渴望度{pct}% ({'↑' if delta > 0 else '↓'}{abs(delta)}%)"
        else:
            prob_part = f"渴望度{pct}% (→)"
        if util != last_util:
            delta = util - last_util
            util_part = f"效用 {util:.2f} {'↑' if delta > 0 else '↓'}{abs(delta):.2f}"
        else:
            util_part = f"效用 {util:.2f} →"
        return f"BrainStatusUpdate: {prob_part} | {util_part}"

    @staticmethod
    def _parse_decision(raw) -> dict | None:
        """从 love_tick 返回中解析决策 dict；解析失败返回 None。"""
        try:
            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(data, dict) and "should_send" in data:
            return data
        return None

    # ------------------------------------------------------------------
    def _greet(self, user_id: str, decision: dict) -> None:
        """以系统口吻让 LLM 自然主动问候，发送结果并反馈给引擎。"""
        user_state = decision.get("user_state_zh") or decision.get("user_state") or "未知"
        utility = decision.get("send_utility", 0)
        silence_h = float(decision.get("silence_hours", 0) or 0)
        if silence_h >= 1:
            silence_text = f"{silence_h:.1f} 小时"
        else:
            silence_text = f"{silence_h * 60:.0f} 分钟"
        now_str = datetime.now().strftime("%H:%M")
        console.plugins(
            f"主动问候触发: {user_id} 状态={user_state} 效用={utility:.2f}"
            f" 安静了 {silence_text}"
        )
        system_extra = (
            f"[系统主动问候] 现在 {now_str}，对方已 {silence_text} 没回消息。"
            "主动发一条全新消息：轻轻催一下、关心一下或找个新话题。"
            "直接输出这条消息即可，系统会自动发送并记录，不要调用任何工具。"
            "要求：不顺着对方上一条内容接话；绝不重复自己说过的话；"
            "要像等了对方一阵子才主动开口；自然，不暴露任何机制；用中文。"
        )
        try:
            self._bot.typing.start(user_id)
            # persist=True：主动问候写入对话历史，让 LLM 知道自己发过什么，
            # 避免后续（再次主动问候/用户回复时）重复同样的话。
            reply = self._bot._run_agent(
                user_id, "(system proactive greeting)", system_extra, persist=True
            )
        except Exception as e:
            console.error(f"主动问候生成失败: {e}")
            reply = ""
        finally:
            self._bot.typing.stop(user_id)
        if not reply or reply.strip() == "<none>":
            console.warn(f"主动问候跳过（空/<none>）: {user_id}")
            return
        self._bot.send_parts(user_id, self._bot._split_reply(reply))
        console.reply(user_id, reply)
        # 反馈引擎：记录已发送（未回复计数 +1）
        try:
            self._invoke(
                "love_record_send",
                {"user_id": user_id, "message": reply[:100]},
            )
        except Exception as e:
            console.warn(f"love_record_send 失败 {user_id}: {e}")

    # ------------------------------------------------------------------
    def record_user_reply(self, user_id: str, text: str) -> None:
        """用户回复时调用：估算回复速度/长度并反馈给 revive 引擎。

        在 OpenCompanion.on_message 收到普通消息时调用。用回复文本长度估算
        reply_length（0-1），reply_speed 用固定中值（无发送时间戳可考，
        由引擎的沉默时长观测兜底）。
        """
        if not text:
            return
        length = max(0.0, min(1.0, len(text) / 200.0))
        try:
            self._invoke(
                "love_record_reply",
                {
                    "user_id": user_id,
                    "reply_speed": 0.5,
                    "reply_length": round(length, 3),
                    "message": text[:100],
                },
            )
        except Exception as e:
            console.warn(f"love_record_reply 失败 {user_id}: {e}")


def on_user_reply(bot, user_id: str, text: str) -> None:
    """模块级用户回复钩子（由 PluginManager 注册，manifest on_user_reply）。

    优先复用已实例化的 ReviveTrigger（bot.revive）；找不到时不做任何事，
    避免 plugin 系统重构后对旧路径造成影响。
    """
    trigger = getattr(bot, "revive", None)
    if trigger is None:
        return
    trigger.record_user_reply(user_id, text)
