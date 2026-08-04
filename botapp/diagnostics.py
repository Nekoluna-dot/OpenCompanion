#这里是个补丁 专属微信适配器的 后续会合进去
import logging
import time

import weilink._protocol as _proto

from botapp.console import console

_orig_post = _proto.post
_orig_get = _proto.get

# 心跳轮询端点
_GETUPDATES = _proto.EP_GET_UPDATES
_TRANSIENT_HINTS = (
    "ssl",
    "eof",
)
_RETRY_DELAYS = (1.0, 2.0)


def _is_transient(exc) -> bool:
    msg = str(getattr(exc, "errmsg", "") or exc).lower()
    return any(hint in msg for hint in _TRANSIENT_HINTS)


def _timed_post(endpoint, *args, **kwargs):
    t = time.perf_counter()
    result = _post_with_retry(endpoint, args, kwargs)
    if endpoint != _GETUPDATES:
        console.proto("POST", endpoint, (time.perf_counter() - t) * 1000)
    return result


def _post_with_retry(endpoint, args, kwargs):
    try:
        return _orig_post(endpoint, *args, **kwargs)
    except _proto.ILinkError as e:
        if not _is_transient(e):
            raise
        for delay in _RETRY_DELAYS:
            time.sleep(delay)
            try:
                result = _orig_post(endpoint, *args, **kwargs)
                console.warn(
                    f"{endpoint} 重连成功!）"
                )
                return result
            except _proto.ILinkError as e2:
                if not _is_transient(e2):
                    raise
        raise


def _timed_get(endpoint, *args, **kwargs):
    t = time.perf_counter()
    result = _orig_get(endpoint, *args, **kwargs)
    console.proto("GET", endpoint, (time.perf_counter() - t) * 1000)
    return result


class _NoPollTraceback(logging.Filter):
    """丢掉 weilink.client 轮询循环里"瞬时网络/SSL 错误"的全量 traceback。

    其他错误（会话过期、业务异常等）保留原样输出。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.getMessage().startswith("Polling error in dispatcher"):
            return True
        # 有异常信息且非瞬时 → 真 bug，保留完整 traceback；其余（瞬时/无异常）丢弃
        if record.exc_info and not _is_transient(record.exc_info[1]):
            return True
        return False


def install() -> None:
    """启用协议请求打点 + 瞬时错误重试 + 轮询 traceback 过滤（幂等）。"""
    _proto.post = _timed_post
    _proto.get = _timed_get
    logger = logging.getLogger("weilink.client")
    if not any(isinstance(f, _NoPollTraceback) for f in logger.filters):
        logger.addFilter(_NoPollTraceback())
