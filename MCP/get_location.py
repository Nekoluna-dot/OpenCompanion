import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("geo-location")

API_URL = "https://uapis.cn/api/v1/network/myip"


@mcp.tool()
def get_user_location() -> str:
    """查对方大致在哪个省市。想聊天气、本地话题，或对方问"我在哪"时用。"""
    try:
        resp = httpx.get(API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(f"Failed to fetch location data: {e}") from e

    region = data.get("region", "")
    if not region:
        return "无法获取位置"
    return f"他/她位于{region}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
