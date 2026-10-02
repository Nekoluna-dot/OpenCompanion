"""网页控制台：OmbreBrain 后台（18001）只读代理。

OB 的 /api/buckets、/api/letters 需要 dashboard session cookie
（/auth/login 登录获取）。本模块在内存中持有 cookie（http.cookiejar），
把网页控制台的请求转发给 OB，避免前端直接跨端口访问与凭据暴露。

仅暴露只读端点（桶列表/详情、信件列表）；写入类操作（钉选、
删除、归档）在 OB 自带后台 18001 完成。
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OB_HOST = "127.0.0.1"
OB_PORT = 18001
_OB_PASS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ob_pass.json"


class ObProxy:
    def __init__(self, host: str = OB_HOST, port: int = OB_PORT) -> None:
        self._base = f"http://{host}:{port}"
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj)
        )

    # ------------------------------------------------------------------
    # 密码持久化（登录/设置成功后自动保存，下次免输入；密码错误时重新输入覆盖）
    # ------------------------------------------------------------------
    def _save_password(self, password: str) -> None:
        try:
            _OB_PASS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _OB_PASS_PATH.write_text(
                json.dumps({"password": password}, ensure_ascii=False), encoding="utf-8"
            )
            try:
                os.chmod(_OB_PASS_PATH, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    def _load_password(self) -> str:
        try:
            d = json.loads(_OB_PASS_PATH.read_text(encoding="utf-8"))
            return str(d.get("password", "")) or ""
        except (OSError, ValueError):
            return ""

    def login_saved(self) -> bool:
        """用上次保存的密码尝试自动登录（成功返回 True）。"""
        pw = self._load_password()
        if not pw:
            return False
        try:
            r = self.login(pw)
        except RuntimeError:
            return False
        return bool(r.get("ok"))

    # ------------------------------------------------------------------
    # 基础请求
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout: float = 8.0) -> tuple[int, dict]:
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                code = resp.getcode()
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                raw = e.read().decode("utf-8", errors="replace")
            except OSError:
                raw = ""
        except OSError as e:
            raise RuntimeError(f"OmbreBrain 后台未连接（{self._base}）: {e}") from e
        try:
            obj = json.loads(raw) if raw else {}
        except ValueError:
            obj = {}
        return code, obj

    def _get(self, path: str, params: dict | None = None, timeout: float = 8.0) -> dict:
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None and v != ""})
            if qs:
                path += "?" + qs
        code, obj = self._request("GET", path, timeout=timeout)
        return {"code": code, "body": obj}

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------
    def status(self) -> dict:
        code, obj = self._request("GET", "/auth/status", timeout=4.0)
        if code != 200:
            return {"ok": False, "error": obj.get("error", f"HTTP {code}")}
        return {"ok": True, "authenticated": obj.get("authenticated", False),
                "setup_needed": obj.get("setup_needed", False)}

    def login(self, password: str) -> dict:
        if not password:
            return {"ok": False, "error": "密码不能为空"}
        code, obj = self._request("POST", "/auth/login", {"password": password})
        if code == 200 and obj.get("ok"):
            self._save_password(password)
            return {"ok": True}
        return {"ok": False, "error": obj.get("error", f"HTTP {code}")}

    def setup(self, password: str) -> dict:
        if not password or len(password) < 6:
            return {"ok": False, "error": "密码至少 6 位"}
        code, obj = self._request("POST", "/auth/setup", {"password": password})
        if code == 200 and obj.get("ok"):
            self._save_password(password)
            return {"ok": True}
        return {"ok": False, "error": obj.get("error", f"HTTP {code}")}

    def logout(self) -> None:
        try:
            self._request("POST", "/auth/logout", timeout=4.0)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # 只读数据
    # ------------------------------------------------------------------
    def buckets(self, bucket_type: str = "", limit: int = 200) -> dict:
        r = self._get("/api/buckets", {"type": bucket_type, "limit": limit})
        if r["code"] != 200:
            return {"ok": False, "error": self._error_text(r)}
        data = r["body"]
        if not isinstance(data, list):
            return {"ok": False, "error": "返回格式异常"}
        return {"ok": True, "buckets": data}

    def bucket(self, bucket_id: str) -> dict:
        import urllib.parse as _up

        r = self._get("/api/bucket/" + _up.quote(bucket_id, safe=""))
        if r["code"] != 200:
            return {"ok": False, "error": self._error_text(r)}
        return {"ok": True, "bucket": r["body"]}

    def letters(self, author: str = "") -> dict:
        r = self._get("/api/letters", {"author": author})
        if r["code"] != 200:
            return {"ok": False, "error": self._error_text(r)}
        body = r["body"]
        if not isinstance(body, dict):
            return {"ok": False, "error": "返回格式异常"}
        return {"ok": True, "letters": body.get("letters", []), "total": body.get("total", 0)}

    @staticmethod
    def _error_text(r: dict) -> str:
        body = r.get("body") or {}
        msg = body.get("error") if isinstance(body, dict) else ""
        if isinstance(msg, str) and msg:
            return msg
        return f"HTTP {r.get('code')}"
