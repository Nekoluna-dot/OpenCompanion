import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

API_URL = "https://uapis.cn/api/v1/misc/weather"


@mcp.tool()
def get_weather() -> str:
    """查当前天气（地区/天气/温度/风速）。问天气、想建议户外活动或提醒带伞时用。"""
    try:
        resp = httpx.get(API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(f"Failed to fetch weather data: {e}") from e

    region = f"{data.get('province', '')} {data.get('city', '')}".strip()
    return (
        f"地区: {region} | 天气: {data.get('weather', '')} | "
        f"温度: {data.get('temperature', '')}°C | "
        f"风速: {data.get('wind_direction', '')} {data.get('wind_power', '')}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
