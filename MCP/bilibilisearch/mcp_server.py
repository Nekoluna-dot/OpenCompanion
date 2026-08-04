#!/usr/bin/env python3
"""
Bilibili MCP Server
B站数据采集 MCP 服务（免登录子集：搜索 / 热门 / 详情 / 评论）
"""

import json

from mcp.server.fastmcp import FastMCP
from bilibili_api import search, hot, video, comment

mcp = FastMCP("bilibili-mcp")


# ========== Tool 1: 搜索视频 ==========

@mcp.tool()
async def bili_search(keyword: str, num: int = 5, order: str = "totalrank") -> str:
    """
    搜索B站视频（免登录）。

    Args:
        keyword: 搜索关键词，如"AI Agent"、"大模型教程"
        num: 返回视频数量，最多5条
        order: 排序方式 totalrank=综合 click=播放量 pubdate=最新 dm=弹幕
    
    Returns:
        JSON格式的视频列表，包含标题、BV号、播放量、评论数、UP主等
    """
    order_map = {
        "totalrank": search.OrderVideo.TOTALRANK,
        "click": search.OrderVideo.CLICK,
        "pubdate": search.OrderVideo.PUBDATE,
        "dm": search.OrderVideo.DM,
    }
    order_enum = order_map.get(order, search.OrderVideo.TOTALRANK)

    result = await search.search_by_type(
        keyword=keyword,
        search_type=search.SearchObjectType.VIDEO,
        page=1,
        order_type=order_enum,
    )

    videos = []
    for item in result.get("result", [])[: max(1, min(num, 5))]:
        title = item.get("title", "").replace('<em class="keyword">', "").replace("</em>", "")
        videos.append({
            "bvid": item.get("bvid", ""),
            "aid": item.get("aid", 0),
            "title": title,
            "author": item.get("author", ""),
            "play": item.get("play", 0),
            "review": item.get("review", 0),
            "danmaku": item.get("video_review", 0),
            "duration": item.get("duration", ""),
            "description": item.get("description", "")[:200],
        })

    return json.dumps({"keyword": keyword, "count": len(videos), "videos": videos}, ensure_ascii=False)


# ========== 热门视频 ==========

@mcp.tool()
async def bili_hot_videos(ps: int = 3) -> str:
    """
    获取B站当前热门视频列表（游客登录）。

    Args:
        ps: 返回条数，最多3条

    Returns:
        热门视频列表，包含标题、播放量、UP主等
    """
    result = await hot.get_hot_videos(pn=1, ps=50)
    videos = []
    for item in result.get("list", [])[: max(1, min(ps, 3))]:
        stat = item.get("stat", {})
        videos.append({
            "bvid": item.get("bvid", ""),
            "title": item.get("title", ""),
            "author": item.get("owner", {}).get("name", ""),
            "play": stat.get("view", 0),
            "like": stat.get("like", 0),
            "duration": item.get("duration", 0),
            "tname": item.get("tname", ""),
        })
    return json.dumps({"count": len(videos), "videos": videos}, ensure_ascii=False)


# ========== 视频详情（含热门评论，一次调用） ==========

@mcp.tool()
async def bili_video_info(bvid: str, comments: int = 3) -> str:
    """
    查一个B站视频：详情 + 热门评论，一次调用返回（游客登录）。

    Args:
        bvid: 视频BV号，如"BV1uNk1YxEJQ"
        comments: 附带的热门评论条数，默认3，0=不要评论，最多10

    Returns:
        JSON：标题、简介（无简介则提示）、UP主、时长、播放/弹幕/评论/收藏/投币/点赞/分享数、标签，以及热门评论列表。
    """
    v = video.Video(bvid=bvid)
    info = await v.get_info()
    stat = info.get("stat", {})
    description = (info.get("desc") or "").strip()
    if not description:
        description = "该视频没有提供简介"

    out = {
        "bvid": info.get("bvid"),
        "aid": info.get("aid"),
        "title": info.get("title"),
        "description": description,
        "author": info.get("owner", {}).get("name"),
        "duration": info.get("duration"),
        "pages": len(info.get("pages", [])),
        "tags": [t.get("tag_name") for t in info.get("tag", []) if t.get("tag_name")],
        "stat": {
            "view": stat.get("view", 0),
            "danmaku": stat.get("danmaku", 0),
            "reply": stat.get("reply", 0),
            "favorite": stat.get("favorite", 0),
            "coin": stat.get("coin", 0),
            "like": stat.get("like", 0),
            "share": stat.get("share", 0),
        },
    }

    n = max(0, min(int(comments or 0), 10))
    out["comments"] = []
    if n > 0 and info.get("aid"):
        try:
            resp = await comment.get_comments(
                oid=info["aid"],
                type_=comment.CommentResourceType.VIDEO,
                page_index=1,
                order=comment.OrderType.LIKE,
            )
            for r in (resp.get("replies") or [])[:n]:
                content = r.get("content", {})
                out["comments"].append({
                    "user": r.get("member", {}).get("uname", ""),
                    "content": content.get("message", ""),
                    "like": r.get("like", 0),
                })
        except Exception:
            out["comments"] = []

    return json.dumps(out, ensure_ascii=False)


# ========== 评论区 ==========

@mcp.tool()
async def bili_comments(bvid: str, num: int = 20) -> str:
    """
    获取B站视频的热门评论（游客登录，低频调用避免风控）。

    Args:
        bvid: 视频BV号，如"BV1uNk1YxEJQ"
        num: 获取评论数量，默认20，最多30
    
    Returns:
        JSON格式的评论列表，包含用户名、评论内容、点赞数、回复数、时间
    """
    v = video.Video(bvid=bvid)
    info = await v.get_info()
    aid = info["aid"]

    comments = []
    page = 1
    while len(comments) < num and page <= 3:
        try:
            resp = await comment.get_comments(
                oid=aid,
                type_=comment.CommentResourceType.VIDEO,
                page_index=page,
                order=comment.OrderType.LIKE,
            )
            replies = resp.get("replies") or []
            if not replies:
                break

            for r in replies:
                member = r.get("member", {})
                content = r.get("content", {})
                c = {
                    "rpid": r.get("rpid", 0),
                    "user": member.get("uname", ""),
                    "content": content.get("message", ""),
                    "like": r.get("like", 0),
                    "reply_count": r.get("rcount", 0),
                    "time": r.get("ctime", 0),
                }
                comments.append(c)

            page += 1
        except Exception as e:
            break

    return json.dumps({"bvid": bvid, "count": len(comments[:num]), "comments": comments[:num]}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")