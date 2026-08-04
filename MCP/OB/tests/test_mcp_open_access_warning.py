"""MCP 关闭鉴权时必须显著告警（安全加固 #7）。

mcp_require_auth=false → /mcp 全裸奔，任何能连端口的人都能读写全部记忆。
该分支的启动日志必须是 WARNING 级并讲清风险，避免用户无意识地把大脑暴露到公网。
源码级护栏（与 test_dashboard_update_source.py 同风格），不需真启动服务。
"""
from pathlib import Path

_SERVER = Path(__file__).resolve().parents[1] / "src" / "server.py"


def _disabled_branch() -> str:
    src = _SERVER.read_text(encoding="utf-8")
    # 定位启动装配处「关闭鉴权」分支：锚在告警唯一措辞上，向前取到分支的 else/logger 调用。
    idx = src.index("MCP 认证已关闭")
    window = src[idx - 400: idx + 400]
    return window


def test_disabled_branch_uses_warning_not_info():
    win = _disabled_branch()
    assert "logger.warning" in win
    # 该分支不应仅用 info 轻描淡写
    assert "logger.info(\"MCP auth disabled" not in win


def test_warning_mentions_risk_terms():
    win = _disabled_branch()
    for term in ("读写", "记忆", "0.0.0.0"):
        assert term in win, f"缺少风险措辞：{term}"
