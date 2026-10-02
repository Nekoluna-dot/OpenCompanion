"""
========================================
tools/grow/__init__.py — grow 工具入口
========================================

grow 是「我把一段长内容整理进记忆」。短内容（<30 字）走 shortpath，
跳过 LLM 拆分省 API；长内容走 core，调 dehydrator.digest 拆成 2~6 条
独立事件桶。

关键行为：
- 入口做 content 校验
- 按 strip 后长度 < 30 字判断走哪个分支

不做什么（边界）：
- 不做 token 级别预算（grow 关心的是「拆几条」而不是「展示多少」）
- 不返回结构化数据，统一中文短句

对外暴露：dispatch(content) → str
========================================
"""

from typing import Optional

from .. import _runtime as rt
from .._common import check_grow_input_size, check_grow_items_payload
from .shortpath import grow_shortpath
from .core import grow_core, grow_items


async def dispatch(content: str = "", items: Optional[list] = None) -> str:
    await rt.decay_engine.ensure_started()

    # 预拆分模式：上层 AI 已拆好 N 条最终正文 → 逐字入库，跳过 digest 的二次改写。
    # 传了 items（非空列表）即走此路；不传则行为与旧版完全一致（向后兼容）。
    if isinstance(items, list) and len(items) > 0:
        err = check_grow_items_payload(items)
        if err:
            return err
        return await grow_items(items)

    if not content or not content.strip():
        return "内容为空，无法整理。"

    err = check_grow_input_size(content)
    if err:
        return err

    if len(content.strip()) < 30:
        return await grow_shortpath(content)
    return await grow_core(content)
