"""表情包清单 MCP 服务器：列出 data/emojis/ 目录下可发送的表情包文件。

供 LLM 浏览可用表情包后，配合 weilink 内置 send 工具的 image_path
参数发送（文本 + 表情包可同时发）。
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("emoji")

BASE_DIR = Path(__file__).resolve().parent.parent
EMOJI_DIR = BASE_DIR / "data" / "emojis"

_IMAGE_EXTS = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@mcp.tool()
def list_emojis(keyword: str = "") -> list[str]:
    """List emoji image file paths the user can send.

    Call this before sending an emoji, then pass the returned path to the
    send tool's image_path (text can be included at the same time).

    Args:
        keyword: Filter by filename (e.g. "cat"); empty = all emojis.
    """
    if not EMOJI_DIR.is_dir():
        return []
    files = sorted(
        p.resolve().as_posix()
        for p in EMOJI_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )
    if keyword:
        kw = keyword.lower()
        files = [f for f in files if kw in Path(f).name.lower()]
    return files


if __name__ == "__main__":
    mcp.run(transport="stdio")
