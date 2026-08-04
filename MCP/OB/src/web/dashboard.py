"""
========================================
web/dashboard.py — 仪表板页面 + 静态资源 + 健康检查
========================================

承载根路径仪表板、前端静态资源（icon/favicon/manifest/字体）、/favicon.ico 跳转、
以及 /health 健康检查。

对外暴露：register(mcp)。
========================================
"""

import os
import html as _html

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh


def register(mcp) -> None:

    @mcp.custom_route("/", methods=["GET"])
    async def root_dashboard(request: Request) -> Response:
        """Serve dashboard HTML directly at root.

        历史上 / 会 307 → /dashboard，但叠加 Cloudflare Tunnel 的 Always Use HTTPS /
        Page Rule 时容易触发 ERR_TOO_MANY_REDIRECTS。直接返回 HTML，少一次跳转，
        既能修复回环，也省一个 RTT。
        """
        from starlette.responses import HTMLResponse
        dashboard_path = os.path.join(sh.repo_root, "frontend", "dashboard.html")
        try:
            with open(dashboard_path, "r", encoding="utf-8") as f:
                html = f.read()
            # U-09 fix: cache-bust static SVG assets so logo updates are visible
            # without manual hard-refresh after upgrade. 只动字面量 /static/*.svg URL。
            for asset in ("/static/icon.svg", "/static/favicon.svg"):
                html = html.replace(asset, f"{asset}?v={sh.version}")
            # 别让浏览器缓存仪表板 HTML：否则改了 dashboard.html 重新下发后，
            # 用户看到的还是旧版面（U-09 只 cache-bust 了 SVG，HTML 本身没设）。
            # HTML 很小、又是每次从磁盘读，禁缓存代价可忽略，省掉「为什么改了没生效」。
            return HTMLResponse(
                html,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        except FileNotFoundError:
            # 走到这里 = 部署目录里缺 frontend/dashboard.html。它本应随仓库一起下发
            # （已纳入 git，未被 .gitignore 排除），最常见原因是克隆/部署了旧版本。
            return HTMLResponse(
                "<h1>dashboard.html not found</h1>"
                f"<p>Expected at: <code>{_html.escape(dashboard_path)}</code></p>"
                "<p>This file ships with the repo (it is committed and NOT git-ignored). "
                "A missing file almost always means an outdated checkout — "
                "run <code>git pull origin main</code> / re-clone, or rebuild your Docker image, "
                "then restart.</p>",
                status_code=404,
            )

    # iter 1.7 §C/§H: serve frontend static assets (icon.svg, favicon.svg, manifest.json)
    # 安全要点：必须白名单过滤文件名，绝不能让 request 直接拼路径，
    # 否则会被 ?name=../../etc/passwd 这种「目录穿越」攻击拿走任意文件。
    @mcp.custom_route("/static/{name}", methods=["GET"])
    async def static_asset(request: Request) -> Response:
        from starlette.responses import Response as _Resp, JSONResponse
        name = request.path_params.get("name", "")
        allowed = {
            "icon.svg": "image/svg+xml",
            "favicon.svg": "image/svg+xml",
            "manifest.json": "application/manifest+json",
            "RRPL.ttf": "font/truetype",
        }
        if name not in allowed:
            return JSONResponse({"error": "not found"}, status_code=404)
        path = os.path.join(sh.repo_root, "frontend", name)
        try:
            with open(path, "rb") as f:
                return _Resp(f.read(), media_type=allowed[name])
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)

    # 浏览器打开任意页都会自动请求 /favicon.ico，301 永久重定向到 SVG 版本。
    @mcp.custom_route("/favicon.ico", methods=["GET"])
    async def favicon_redirect(request: Request) -> Response:
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/static/favicon.svg", status_code=301)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> Response:
        from starlette.responses import JSONResponse
        try:
            stats = await sh.bucket_mgr.get_stats()
            return JSONResponse({
                "status": "ok",
                "buckets": stats["permanent_count"] + stats["dynamic_count"],
                "decay_engine": "running" if sh.decay_engine.is_running else "stopped",
            })
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
