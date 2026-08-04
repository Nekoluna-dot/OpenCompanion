import threading

from botapp.config import AppConfig
from botapp.console import console
from botapp.platform.base import PlatformAdapter

"""这个是给微信适配器打的补丁 后续会删"""
class McpServer:
    def __init__(self, platform: PlatformAdapter, config: AppConfig) -> None:
        self._platform = platform
        self._config = config
        self._thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动 MCP 服务器（后台守护线程，不阻塞）。"""
        if self._started:
            return
        self._apply_compat_patch()

        cfg = self._config
        self._thread = threading.Thread(
            target=self._run,
            args=(
                self._platform,
                cfg.mcp_transport,
                cfg.mcp_host,
                cfg.mcp_port,
                cfg.mcp_token,
            ),
            daemon=True,
            name="mcp-server",
        )
        self._thread.start()
        self._started = True

        console.mcp(
            f"服务器已启动: {cfg.mcp_transport}://{cfg.mcp_host}:{cfg.mcp_port}"
            + (f"  (Bearer token 鉴权)" if cfg.mcp_token else "")
        )

    def stop(self) -> None:
        """停止 MCP 服务器（后台线程为守护线程，通常随进程退出）。"""
        self._started = False

    # ------------------------------------------------------------------
    @staticmethod
    def _apply_compat_patch() -> None:
        """mcp 2.x 兼容补丁：McpError 改名 MCPError，toolregistry-server 仍用旧名。"""
        try:
            import mcp.shared.exceptions as _mcp_exc
            from mcp.shared.exceptions import MCPError as _MCPError

            if not hasattr(_mcp_exc, "McpError"):
                _mcp_exc.McpError = _MCPError
        except (ImportError, AttributeError):
            pass

    @staticmethod
    def _run(
        platform: PlatformAdapter,
        transport: str,
        host: str,
        port: int,
        token: str,
    ) -> None:
        try:
            platform.run_mcp_server(
                transport=transport,
                host=host,
                port=port,
                token=token or None,
            )
        except Exception as e:
            console.mcp(f"服务器异常退出: {e}")
