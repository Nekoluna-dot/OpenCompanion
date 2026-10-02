#!/usr/bin/env python3
"""构建期下载 cloudflared 二进制（镜像自带 python，无需 curl / apt-get update）。

背景（用户反馈 #3）：旧 Dockerfile 为了拿 curl 去下 cloudflared，先跑
`apt-get update && apt-get install curl ca-certificates`，这一步会打到 Debian
镜像源，间歇性 502 导致**整个镜像构建失败**，每次升级都要手动注释掉那几行。

cloudflared 本来就是从 GitHub Releases 直接下载的静态二进制，跟 apt 无关。这里改用
python:slim 自带的 python（系统已含 ca-certificates）直接下载，并做指数退避重试，
从根上避开 apt。不需要 Tunnel 的用户可在构建时 `--build-arg INSTALL_CLOUDFLARED=0`
完全跳过本步骤。

用法：python fetch_cloudflared.py <目标路径>
"""
from __future__ import annotations

import platform
import shutil
import sys
import time
import urllib.request

# platform.machine() → cloudflared release 资产的架构后缀
_ARCH_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "i686": "386",
    "i386": "386",
}


def cloudflared_arch(machine: str | None = None) -> str:
    m = (machine or platform.machine()).lower()
    if m not in _ARCH_MAP:
        raise SystemExit(f"不支持的架构：{m!r}（cloudflared 无对应发行资产）")
    return _ARCH_MAP[m]


def release_url(arch: str) -> str:
    return f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"


def download(url: str, dest: str, *, attempts: int = 5) -> None:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OmbreBrain-Build"})
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310
                shutil.copyfileobj(r, f)
            print(f"[fetch_cloudflared] 下载成功（第 {attempt} 次尝试）：{url}")
            return
        except Exception as e:  # noqa: BLE001 - 构建期尽量重试，最后一击才失败
            last = e
            print(f"[fetch_cloudflared] 第 {attempt}/{attempts} 次失败：{e}")
            if attempt < attempts:
                time.sleep(attempt * 3)
    raise SystemExit(f"[fetch_cloudflared] 重试 {attempts} 次仍失败：{last}")


def main(argv: list[str]) -> int:
    dest = argv[1] if len(argv) > 1 else "/usr/local/bin/cloudflared"
    arch = cloudflared_arch()
    download(release_url(arch), dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
