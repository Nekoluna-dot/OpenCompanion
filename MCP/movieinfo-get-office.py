import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("movieinfo-get-office")

API_URL = "https://uapis.cn/api/v1/misc/movie-box-office"
TOP_N = 3


@mcp.tool()
def get_movie_box_office(top_n: int = TOP_N) -> list[str]:
    """Get the top N box-office movies right now.

    Use for small talk about popular movies or when the user asks what to
    watch. Returns movie name strings.

    Args:
        top_n: How many movies to return. Default 3.
    """
    try:
        resp = httpx.get(API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RuntimeError(f"Failed to fetch movie data: {e}") from e

    items = data.get("list", [])
    return [item.get("movie_name", "") for item in items[:top_n] if item.get("movie_name")]


if __name__ == "__main__":
    mcp.run(transport="stdio")
