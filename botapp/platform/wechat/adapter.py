"""微信平台适配器：封装 weilink SDK，实现 PlatformAdapter 接口"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from botapp.console import console
from botapp.platform.base import (
    BotMessage,
    MessageHandler,
    PlatformAdapter,
    PlatformStatus,
    SendQuotaExhausted,
)

# 重连相关
_RECONNECT_DELAY_S = 5    # 会话过期后等待几秒再重连（让服务端稳定）
_RECONNECT_MAX_RETRIES = 5  # 连续重连失败达到该次数后停止，提示人工处理
_RECONNECT_FAST_SEC = 10  # 判定「快速失败」的时间阈值（秒内又断开）

# 消息回环防护：weilink 的 store 兜底分发会把 bot 自己发出去的消息
# 当成「对方发来的新消息」重新派发（store_sent 写入的行没有 message_id，
# 且 store-watch 不做 direction=1 过滤）。这里用「文本等于本 bot 最近
# 发给同一用户的消息」来识别并丢弃回环，避免无限复读。
_ECHO_WINDOW_MS = 60_000  # 判定为回环的时间窗口（毫秒）


class WeChatAdapter(PlatformAdapter):
    """weilink 微信平台适配器（会话过期自动重连，token 复用免扫码）。"""

    name = "wechat"

    #: 微信登录态/消息库等数据存放位置（weilink SDK 的默认数据目录）
    data_dir = str(os.path.expanduser(
        os.path.expandvars(os.environ.get("USERPROFILE", str(os.path.expanduser("~"))))
    )) + os.sep + ".weilink"

    def __init__(self, config) -> None:
        from weilink import WeiLink

        self._config = config
        self._wl = WeiLink(message_store=True)
        self._handler: MessageHandler | None = None
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._detail = "未启动"
        # 每用户最近消息缓存 {user_id: deque[(msg_id, create_time_ms, text, kind)]}
        # 用于 iLink 引用消息兜底：协议只回传被引用的类型/时间戳/ID，不回传原文
        self._recent: dict[str, deque] = {}

    # ── 生命周期 ─────────────────────────────────────────────
    def start(self) -> None:
        """启动平台：独立线程执行登录 + 长轮询 + 会话过期重连循环。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="wechat-conn", daemon=True
        )
        self._thread.start()
        console.config("微信平台适配器已启动")

    def stop(self) -> None:
        """停止平台连接（等待线程退出）。"""
        self._stop_flag.set()
        self._wl.stop()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def close(self) -> None:
        """完全释放 weilink 资源。"""
        self.stop()
        try:
            self._wl.close()
        except Exception:
            pass

    # ── 收发 ─────────────────────────────────────────────────
    def send(self, to: str, text: str) -> None:
        try:
            self._wl.send(to, text)
        except Exception as e:
            # 平台每轮最多 N 条出站消息（quota exhausted）时，转换为
            # 平台无关异常，供机器人核心优雅停止，而不是线程崩溃。
            from weilink._protocol import QuotaExhaustedError

            if isinstance(e, QuotaExhaustedError):
                raise SendQuotaExhausted(str(e)) from e
            raise
        self._remember(to, None, int(time.time() * 1000), text, "text")

    def send_typing(self, user_id: str) -> None:
        self._wl.send_typing(user_id)

    def stop_typing(self, user_id: str) -> None:
        self._wl.stop_typing(user_id)

    def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler
        self._wl.on_message(self._dispatch)

    # ── 用户/消息库 ──────────────────────────────────────────
    def resolve_user_id(self, user_id: str) -> str:
        """把去 @ 后缀的短用户 ID 还原为完整 ID（如 xxx@im.wechat）。"""
        if "@" in user_id:
            return user_id
        try:
            tokens = self._wl._context_tokens
        except AttributeError:
            return user_id
        for full in tokens:
            if full.split("@", 1)[0] == user_id:
                return full
        return user_id

    def clear_chat_history(self) -> str:
        """清空 weilink 消息库（history 工具的数据源）。"""
        store = getattr(self._wl, "_message_store", None)
        if store is None:
            return "消息库未启用，没有可清空的聊天记录。"
        with store._lock:
            store._conn.execute("DELETE FROM messages")
            store._conn.commit()
        return "已清空全部历史聊天记录。"

    def clear_user_data(self, user_id: str) -> str:
        """清除指定用户在本平台侧的所有数据：消息库记录 + 语音文件 + 引用缓存。"""
        removed = []
        store = getattr(self._wl, "_message_store", None)
        if store is not None:
            with store._lock:
                cur = store._conn.execute(
                    "DELETE FROM messages WHERE user_id = ?", (user_id,)
                )
                store._conn.commit()
                if cur.rowcount:
                    removed.append(f"消息库 {cur.rowcount} 条")
        # 该用户的语音下载文件
        try:
            from pathlib import Path as _Path

            voice_dir = _Path("data") / "voice"
            if voice_dir.is_dir():
                prefix = user_id.split("@", 1)[0] + "_"
                n = 0
                for f in voice_dir.glob(f"{prefix}*"):
                    f.unlink(missing_ok=True)
                    n += 1
                if n:
                    removed.append(f"语音 {n} 个")
        except OSError:
            pass
        # 引用兜底缓存
        self._recent.pop(user_id, None)
        return "、".join(removed) if removed else "无"

    def context_tokens(self) -> dict[str, str]:
        try:
            return dict(self._wl._context_tokens)
        except AttributeError:
            return {}

    def mcp_client(self):
        """返回 weilink 实例（供 MCP 服务器共享，重连复用同一实例）。"""
        return self._wl

    # ── 媒体发送 ──────────────────────────────────────────────
    _SILK_MAGIC = b"\x02#!SILK_V3"

    @staticmethod
    def _is_silk_file(path: str) -> bool:
        """判断文件是否是微信 SILK v3 语音（含 \x02#!SILK_V3 魔数）。"""
        try:
            with open(path, "rb") as f:
                return f.read(10) == WeChatAdapter._SILK_MAGIC
        except OSError:
            return False

    def send_media(self, user_id: str, kind: str, path: str) -> tuple[bool, str]:
        """发送媒体给用户（voice 自动转 SILK），返回 (成功, 结果文本)。"""
        if not path or not os.path.isfile(path):
            return False, f"媒体文件不存在: {path}"

        if kind == "voice":
            # 语音必须转成微信 SILK v3 格式，否则客户端不播放
            try:
                from botapp.silk import audio_to_silk

                silk_path = path
                if not self._is_silk_file(path):
                    silk_path = os.path.splitext(path)[0] + ".silk"
                    ok, info = audio_to_silk(path, silk_path)
                    if not ok:
                        return False, f"语音格式转换失败: {info}"
                    path = silk_path
            except Exception as e:
                return False, f"语音格式转换异常: {e}"

        try:
            kwargs: dict = {}
            if kind == "image":
                kwargs["image"] = open(path, "rb").read()
            elif kind == "voice":
                kwargs["voice"] = open(path, "rb").read()
            elif kind == "file":
                kwargs["file"] = open(path, "rb").read()
                kwargs["file_name"] = os.path.basename(path)
            elif kind == "video":
                kwargs["video"] = open(path, "rb").read()
            else:
                return False, f"不支持的媒体类型: {kind}"

            result = self._wl.send(user_id, auto_recv=True, **kwargs)
            ok = bool(getattr(result, "success", True))
            return ok, ("发送成功" if ok else f"发送失败: {result}")
        except Exception as e:
            return False, f"发送媒体失败: {e}"

    # ── 平台内建工具 / MCP 服务器 ─────────────────────────────
    def _tool_functions(self):
        """返回 weilink 内建工具函数列表（LLM 侧不暴露，仅 MCP 服务器对外使用）。"""
        import weilink.server.app as server_app

        return list(server_app._TOOL_FUNCTIONS)

    def platform_tool_registry(self):
        """构建 weilink 内建工具注册表（含 send/recv 等），应用账号工具过滤。"""
        import weilink.server.app as server_app

        # 先同步工具函数列表（应用账号工具过滤），再构建注册表
        server_app._TOOL_FUNCTIONS = self._tool_functions()
        return server_app.build_registry()

    def run_mcp_server(self, transport: str, host: str, port: int, token: str | None) -> None:
        """运行 weilink 的 MCP 服务器（后台线程调用，阻塞直到退出）。

        复用本适配器持有的 weilink 实例，避免双实例争抢 poll 锁。
        """
        import weilink.server.app as server_app

        # 共享平台底层连接，run_mcp 内部检测到 _wl 非空则跳过创建
        server_app._wl = self.mcp_client()
        # 应用账号工具过滤，使 MCP 服务器暴露的工具与 LLM 工具层一致
        server_app._TOOL_FUNCTIONS = self._tool_functions()

        from weilink.server.app import run_mcp

        run_mcp(
            transport=transport,
            host=host,
            port=port,
            token=token or None,
        )

    # ── 状态 ─────────────────────────────────────────────────
    def status(self) -> PlatformStatus:
        return PlatformStatus(
            name=self.name, connected=self._connected, detail=self._detail
        )

    # ── 内部 ─────────────────────────────────────────────────
    def _remember(
        self,
        user_id: str,
        msg_id: str | None,
        create_time_ms: int | None,
        text: str,
        kind: str,
    ) -> None:
        """把一条消息记入该用户的最近消息缓存（引用兜底数据源）。"""
        entry = self._recent.setdefault(user_id, deque(maxlen=30))
        entry.append((msg_id, create_time_ms or 0, text, kind))

    def _resolve_replied(self, user_id: str, ref) -> tuple[str, str]:
        """解析引用消息内容，返回 (replied_text, replied_type)。

        iLink 引用只回传被引用消息的类型/时间戳/ID，不回传原文。
        因此按优先级匹配该用户最近消息缓存：msg_id 精确 → 时间窗最近 →
        最近一条。匹配不到或非文本时给占位标记。
        """
        if ref is None:
            return "", ""
        # 类型优先以 ref.msg_type 为准（服务端会给，如 TEXT/IMAGE...）
        ref_type = (
            ref.msg_type.name.lower()
            if hasattr(ref.msg_type, "name")
            else "text"
        )
        ref_id = getattr(ref, "msg_id", None)
        ref_ts = getattr(ref, "create_time_ms", None)

        # 1. ref 自带原文（理论上 iLink 不回传，兜底处理）
        if ref.text:
            return ref.text, ref_type
        if ref.image is not None:
            return "[图片]", "image"
        if ref.voice is not None:
            return "[语音]", "voice"
        if ref.file is not None:
            return f"[文件:{ref.file.file_name}]", "file"
        if ref.video is not None:
            return "[视频]", "video"

        cache = self._recent.get(user_id)
        if not cache:
            return "", ""

        # 2. msg_id 精确匹配
        if ref_id:
            for msg_id, _ts, text, _kind in reversed(cache):
                if msg_id == ref_id:
                    return text or "[消息]", ref_type
        # 3. create_time_ms 时间窗内最近一条（60s，同 weixin_oc 窗口）
        if ref_ts:
            best = None
            best_dist = None
            for _mid, ts, text, _kind in cache:
                if not ts:
                    continue
                dist = abs(ts - ref_ts)
                if dist > 60_000:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = (text, _kind)
            if best is not None:
                return best[0] or "[消息]", best[1] or ref_type
        # 4. 最近一条兜底
        if cache:
            text = cache[-1][2]
            return text or "[消息]", cache[-1][3] or ref_type
        return "", ""

    def _download_voice(self, msg) -> str:
        """下载语音消息原始字节到 data/voice/，返回文件路径（失败返回空串）。

        微信服务端转写为空时兜底：把音频文件落地，供后续自行处理（转写/人听）。
        """
        try:
            from pathlib import Path as _Path

            raw = self._wl.download(msg)
        except Exception as e:
            console.warn(f"语音下载失败: {e}")
            return ""
        if not raw:
            return ""
        voice_dir = _Path("data") / "voice"
        voice_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._voice_suffix(getattr(msg.voice, "encode_type", 0))
        path = voice_dir / f"{msg.from_user.split('@', 1)[0]}_{int(time.time() * 1000)}{suffix}"
        path.write_bytes(raw)
        return str(path)

    def _download_image(self, msg) -> str:
        """下载图片消息原始字节到 data/image/，返回文件路径（失败返回空串）。"""
        try:
            from pathlib import Path as _Path

            raw = self._wl.download(msg)
        except Exception as e:
            console.warn(f"图片下载失败: {e}")
            return ""
        if not raw:
            return ""
        img_dir = _Path("data") / "image"
        img_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._image_suffix(raw)
        path = (
            img_dir
            / f"{msg.from_user.split('@', 1)[0]}_{int(time.time() * 1000)}{suffix}"
        )
        path.write_bytes(raw)
        return str(path)

    def _download_video(self, msg) -> str:
        """下载视频消息原始字节到 data/video/，返回文件路径（失败返回空串）。"""
        try:
            from pathlib import Path as _Path

            raw = self._wl.download(msg)
        except Exception as e:
            console.warn(f"视频下载失败: {e}")
            return ""
        if not raw:
            return ""
        vid_dir = _Path("data") / "video"
        vid_dir.mkdir(parents=True, exist_ok=True)
        path = (
            vid_dir
            / f"{msg.from_user.split('@', 1)[0]}_{int(time.time() * 1000)}.mp4"
        )
        path.write_bytes(raw)
        return str(path)

    @staticmethod
    def _image_suffix(raw: bytes) -> str:
        """按图片文件头识别后缀（默认 .jpg）。"""
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return ".png"
        if raw[:4] == b"GIF8":
            return ".gif"
        if raw[:2] == b"BM":
            return ".bmp"
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return ".webp"
        return ".jpg"

    @staticmethod
    def _voice_suffix(encode_type: int) -> str:
        """按语音编码类型给下载文件一个合理后缀（weilink 注释定义）。"""
        return {
            1: ".pcm",
            2: ".adpcm",
            4: ".speex",
            5: ".amr",
            6: ".silk",
            7: ".mp3",
        }.get(encode_type, ".bin")

    def _is_own_echo(self, user_id: str, text: str, now_ms: int | None = None) -> bool:
        """判断一条入站消息是否本 bot 最近发给同一用户的消息回环。

        weilink 的 store 兜底分发/bot 自身消息回推会把本 bot 发出去的消息
        当作新入站消息重新派发给 handler。判定依据：文本精确等于本 bot
        最近发给该用户的消息（send 时 _remember 的条目 msg_id 为 None），
        且在时间窗口内。完整文本精确匹配 + 限时，误杀用户真实消息的概率极低。
        """
        if not text:
            return False
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        cache = self._recent.get(user_id)
        if not cache:
            return False
        for entry_msg_id, create_time_ms, prev_text, kind in cache:
            if entry_msg_id is not None:  # 只认本 bot 发出的记录
                continue
            if kind != "text" or prev_text != text:
                continue
            if create_time_ms and now_ms - create_time_ms <= _ECHO_WINDOW_MS:
                return True
        return False

    def _dispatch(self, msg) -> None:
        """把 weilink Message 转换为 BotMessage 后交给机器人处理器。"""
        if self._handler is None:
            return

        # 回环防护：忽略本 bot 自己消息被重新派发回来的入站消息
        if self._is_own_echo(msg.from_user, msg.text or ""):
            console.warn(
                f"丢弃自回环消息（{msg.from_user}）: "
                f"{str(msg.text or '')[:40]}..."
            )
            return

        text = msg.text or ""
        msg_type = (
            msg.msg_type.name.lower() if hasattr(msg.msg_type, "name") else "text"
        )
        voice_path = ""
        image_path = ""
        video_path = ""

        # 图片消息：下载图片供 LLM 理解（受 enable_image 控制）
        if getattr(msg, "image", None) is not None:
            if not getattr(self._config, "enable_image", False):
                console.info(f"收到图片消息但 enable_image=false，忽略: {msg.from_user}")
                return  # 未开启图片接收，忽略图片消息
            image_path = self._download_image(msg)
            if not image_path:
                console.warn("图片下载失败，忽略该图片消息")
                return
            text = "[图片]"

        # 视频消息：下载视频供 LLM 理解（受 enable_video 控制）
        if getattr(msg, "video", None) is not None:
            if not getattr(self._config, "enable_video", False):
                console.info(f"收到视频消息但 enable_video=false，忽略: {msg.from_user}")
                return  # 未开启视频接收，忽略视频消息
            video_path = self._download_video(msg)
            if not video_path:
                console.warn("视频下载失败，忽略该视频消息")
                return
            text = "[视频]"

        # 语音消息：优先用微信服务端转写；转写为空则下载音频供后续处理
        if getattr(msg, "voice", None) is not None:
            voice = msg.voice
            voice_text = (voice.text or "").strip()
            if voice_text:
                text = f"[语音内容] {voice_text}"
            else:
                voice_path = self._download_voice(msg)
                text = f"语音识别不清"

        if not text:
            return

        ref = getattr(msg, "ref_msg", None)
        replied_text, replied_type = self._resolve_replied(msg.from_user, ref)
        self._remember(
            msg.from_user,
            getattr(msg, "message_id", None),
            getattr(msg, "timestamp", None),
            text,
            msg_type,
        )
        extra: dict = {}
        if voice_path:
            extra["voice_path"] = voice_path
        if image_path:
            extra["image_path"] = image_path
        if video_path:
            extra["video_path"] = video_path
        self._handler(
            BotMessage(
                from_user=msg.from_user,
                text=text,
                msg_type=msg_type,
                raw=msg,
                replied_text=replied_text,
                replied_type=replied_type,
                image_path=image_path,
                video_path=video_path,
                extra=extra,
            )
        )

    def _run_loop(self) -> None:
        """登录 + 长轮询 + 会话过期自动重连的主循环。"""
        consecutive_failures = 0
        while not self._stop_flag.is_set():
            if self._wl._default_session.bot_info is None:
                try:
                    self._wl.login()
                except Exception as e:
                    console.error(f"微信登录失败: {e}")
                    self._detail = f"登录失败: {e}"
                    time.sleep(_RECONNECT_DELAY_S)
                    continue
            self._connected = True
            self._detail = "已连接"
            console.info("机器人已就绪，等待消息... (Ctrl+C 退出)")

            started_at = time.monotonic()
            try:
                self._wl.run_background()
                self._wl._dispatcher_stop.wait()
            except Exception as e:
                console.error(f"长轮询异常: {e}")
                self._detail = f"异常: {e}"
            finally:
                self._connected = False
                try:
                    self._wl.stop()
                except Exception:
                    pass

            duration = time.monotonic() - started_at
            if self._stop_flag.is_set():
                break
            console.warn("检测到会话过期，准备自动重连...")
            self._detail = "会话过期，准备重连"

            if duration < _RECONNECT_FAST_SEC:
                consecutive_failures += 1
                console.warn(
                    f"连接仅维持 {duration:.0f}s 即再次过期 "
                    f"（连续 {consecutive_failures}/{_RECONNECT_MAX_RETRIES} 次）"
                )
                if consecutive_failures >= _RECONNECT_MAX_RETRIES:
                    console.warn(
                        "自动重连多次失败，会话 token 可能已失效，"
                        "强制重新扫码登录（生成新二维码）..."
                    )
                    self._detail = "强制重新扫码登录"
                    try:
                        self._wl.login(force=True)
                        consecutive_failures = 0
                        time.sleep(_RECONNECT_DELAY_S)
                        console.info("扫码登录完成，继续连接...")
                        continue
                    except Exception as e:
                        console.error(f"强制扫码登录失败: {e}")
                        self._detail = f"重新扫码失败: {e}"
                        time.sleep(_RECONNECT_DELAY_S)
                        continue
            else:
                consecutive_failures = 0

            time.sleep(_RECONNECT_DELAY_S)
            console.info("正在重连...")

    def _is_connected(self) -> bool:
        return self._connected

