# -*- coding: utf-8 -*-
"""回复清洗：修复模型流式输出退化 / 标签写坏，避免乱码发到用户端。

背景：用户反馈过几类"乱码"，都不是字节编码问题（llm.py 的 SSE 读取是
按行解码的，安全），而是模型在长中文回复时输出退化（repetition /
转义泄漏），或把约定标签 <SEP> 写坏，系统原样转发给用户：

  * `<SEP "那你你最近有什么有趣的事情想分享的呀？嗯。`  ← <SEP> 写坏成 `<SEP "`
  * `... \\u "耶,\\u "forgettable" \\u "吗耶 \\u "耶 ...`   ← \\u 转义泄漏 + 短串死循环
  * `对SEP若怀念起来他"的事`                              ← <SEP> 的尖括号被吞
  * `祝你好运/name>抽中大奖了`                            ← 残留的落单闭合标签

本模块在发送前统一修复，正常回复不受影响。
"""
from __future__ import annotations

import re

from botapp.console import console

_SEP = "<SEP>"

# 被写坏的 <SEP>：尖括号内可含空格/大小写/多余字符（`<SEP "`、`<sep>`、`<S E P>`）
# 只吞掉紧随其后的空白/引号（`<SEP "`），绝不吞正文
_SEP_BROKEN_RE = re.compile(r"<\s*S\s*E\s*P\b[\s\x22\x27\u2018\u2019\u201c\u201d]{0,4}>?", re.IGNORECASE)

# 残留的成对/落单标签（</name>、<letter>、<dream> 等）一律剥掉；
# 负向前瞻排除合法的 <SEP>。
_TAG_RE = re.compile(r"<(?!SEP[ >])/?[A-Za-z][A-Za-z0-9_\-]{0,24}\s*/?>")
# 落单闭合标签丢了左尖括号的形态（如 `祝你好运/name>`）
_ORPHAN_CLOSE_RE = re.compile(r"(?<![A-Za-z0-9])/?[A-Za-z][A-Za-z0-9_\-]{0,24}>")

# 夹在汉字之间的裸 SEP（模型把 <SEP> 的尖括号吞了，如 "对SEP若"）
_SEP_BARE_RE = re.compile(r"(?<=[\u4e00-\u9fff])SEP(?=[\u4e00-\u9fff])")

# 退化的转义残留：模型把 \u / \n / \t 转义当普通文本吐出（如 \u "耶）
_ESC_LEAK_RE = re.compile(r"\\u[0-9a-fA-F]{4}|\\u\s*[\x22\x27]?|\\[nrt]")

# 气泡段首尾的残缺引号 / 尖括号（坏标记残留）
_EDGE_JUNK_RE = re.compile(r"^[\s\x22\x27<>]+|[\s\x22\x27<>]+$")


def repair_reply(text: str) -> str:
    """截断退化输出并清掉转义残留（在标记处理之后、切分之前调用）。

    1. 转义泄漏：从第一处 ``\\u`` 起整段截断——前面正常，后面是退化噪声。
    2. 短串死循环：同一 2~12 字片段连续重复 >= 8 次，从重复起点截断。
    3. 清掉残余转义、汉字之间的裸 SEP。
    """
    if not text:
        return text
    if text.count("\\u") >= 3:
        cut = text.find("\\u")
        if cut > 0:
            console.warn("检测到回复退化(转义泄漏)，已截断")
            text = text[:cut]
    if len(text) < 20000:
        m = re.search(r"(.{2,12}?)\1{7,}", text)
        if m and m.start() > 0:
            console.warn("检测到回复退化(重复循环)，已截断")
            text = text[: m.start()]
    text = _ESC_LEAK_RE.sub("", text)
    text = _SEP_BARE_RE.sub("", text)
    return text


def split_reply(reply: str, config) -> list[str]:
    """清洗并切分回复为多条气泡（供 robot._split_reply 调用）。

    0. repair_reply：截断流式退化。
    1. 把写坏的 <SEP> 归一化为 <SEP>。
    2. 按 split_newline 决定是否把换行也当分隔符，否则只按 <SEP>。
    3. 每段剥掉残留标签、清洗括号内文本、去段首尾残缺引号，trim 后过滤空段。
    """
    reply = repair_reply(reply)
    reply = _SEP_BROKEN_RE.sub(_SEP, reply)
    if getattr(config, "split_newline", False):
        parts = re.split(r"<SEP>|\n+", reply)
    else:
        parts = reply.split(_SEP)
    clean: list[str] = []
    for p in parts:
        p = _TAG_RE.sub("", p)
        p = _ORPHAN_CLOSE_RE.sub("", p)
        if getattr(config, "clean_paren", True):
            p = re.sub(r"[（(][^（）()]*[）)]", "", p)
        p = _EDGE_JUNK_RE.sub("", p).strip()
        if p:
            clean.append(p)
    return clean
