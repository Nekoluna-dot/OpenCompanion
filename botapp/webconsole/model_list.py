"""网页控制台：从 OpenAI 兼容 API 拉取可用模型列表。

用于「机器人配置」页的 model 字段：填好 base_url / api_key 后点「自动获取」，
由后端请求 {base_url}/models（OpenAI 兼容），把返回的模型 id 列表回传前端下拉选择。

- 兼容 base_url 直接指向具体端点的情况（/chat/completions、/responses 等）：
  自动回退到同源根路径 + /v1/models。
- 依次尝试若干候选地址，全部失败时返回 {"ok": False, "error": ...}。
- 网络请求带超时；解码统一 errors="replace"，避免非 UTF-8 响应抛异常。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 15.0

# 具体端点后缀：base_url 若以这些结尾，说明填的是完整端点而非根地址
_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/responses",
    "/embeddings",
    "/models",
)

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def _normalize_base(base_url: str) -> str:
    """补全协议头并去掉尾部斜杠。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.lower().startswith(("http://", "https://")):
        host = base.split("/", 1)[0].split(":", 1)[0].lower()
        scheme = "http" if host in _LOCAL_HOSTS or host.endswith(".local") else "https"
        base = f"{scheme}://{base}"
    return base


def _candidate_urls(base_url: str) -> list[str]:
    """由用户填写的 base_url 推导出若干可能的 /models 地址（按优先级）。"""
    base = _normalize_base(base_url)
    if not base:
        return []

    urls: list[str] = []
    low = base.lower()
    if low.endswith("/models"):
        urls.append(base)
    elif low.endswith(_ENDPOINT_SUFFIXES):
        # 完整端点：取同源根，分别尝试 /v1/models 与 /models
        parsed = urllib.parse.urlsplit(base)
        root = f"{parsed.scheme}://{parsed.netloc}"
        urls.append(root + "/v1/models")
        urls.append(root + "/models")
    else:
        # 根地址（可能已含 /v1）
        urls.append(base + "/models")
        if not low.endswith("/v1"):
            urls.append(base + "/v1/models")

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _extract_models(obj) -> list[str]:
    """从 /models 响应中提取模型 id 列表（兼容 data/models 与 id/name/model 字段）。"""
    if not isinstance(obj, dict):
        return []
    data = obj.get("data")
    if data is None:
        data = obj.get("models")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str):
            mid = item
        elif isinstance(item, dict):
            mid = item.get("id") or item.get("name") or item.get("model")
        else:
            continue
        mid = str(mid or "").strip()
        if mid and mid not in out:
            out.append(mid)
    return out


def fetch_models(base_url: str, api_key: str = "") -> dict:
    """请求 base_url 对应的 /models 端点。

    成功返回 {"ok": True, "models": [...], "endpoint": url}；
    失败返回 {"ok": False, "error": "..."}（不抛异常，交由调用方回传前端）。
    """
    candidates = _candidate_urls(base_url)
    if not candidates:
        return {"ok": False, "error": "请先填写 API 地址（base_url）"}

    headers = {"Accept": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    last_error = ""
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            last_error = f"HTTP {e.code}: {detail or e.reason}"
            continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            last_error = str(getattr(e, "reason", e) or e)
            continue
        try:
            obj = json.loads(body)
        except ValueError:
            last_error = f"响应不是合法 JSON（{url}）"
            continue
        models = _extract_models(obj)
        if models:
            return {"ok": True, "models": models, "endpoint": url}
        last_error = f"未从 {url} 解析到模型列表"
    return {"ok": False, "error": last_error or "获取模型列表失败"}
