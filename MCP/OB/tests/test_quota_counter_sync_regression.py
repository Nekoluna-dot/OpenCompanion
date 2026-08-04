"""配额计数器同步回归测试 —— 按用户反馈的精确复现路径走。

反馈场景（v2.3.22，Render）：
1. pinned：取消钉选到 17 个后仍订不上新的，报「有 24 个 pin」
   → 旧根因：取消钉选后残留的 type=permanent 也被算进 pinned 配额。
2. importance≥9：trace(bucket_id, importance=7) 降级后，hold(importance=9)
   仍报「已有 84 条 ≥9（硬上限 24）」自动降为 8；实际 breath 只剩 18 条
   → 旧根因：pinned/protected（importance 锁 10）也被算进 ≥9 配额，且计数不实时。

当前实现的两条硬保证（本文件锁死，防止回退）：
- 配额计数每次实时从盘上数（无缓存计数器），trace 改完立即生效；
- pinned 只数 metadata.pinned，type=permanent 不占 pinned 配额；
  importance≥9 配额排除 pinned/protected。
"""
from unittest.mock import MagicMock

import pytest

import tools._runtime as rt
from tools._common import (
    count_high_importance,
    count_pinned,
    enforce_high_importance_quota,
    enforce_pinned_quota,
)
from tools.trace.core import trace_core


class EchoDehydrator:
    async def dehydrate(self, content, meta=None):
        return content


def install_runtime(bucket_mgr, limits=None):
    rt.config = {"surfacing": {}, "limits": limits or {}}
    rt.bucket_mgr = bucket_mgr
    rt.dehydrator = EchoDehydrator()
    rt.logger = MagicMock()
    rt.fire_webhook = None
    rt.mark_op = None


# ------------------------------------------------------------
# ① pinned 配额：trace 解钉后必须立刻能钉新的
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_unpin_via_trace_frees_pinned_quota(bucket_mgr):
    # 上限设小（3）让测试轻量；语义与默认 20 一致
    install_runtime(bucket_mgr, limits={"max_pinned": 3})

    ids = []
    for i in range(3):
        ids.append(await bucket_mgr.create(content=f"核心准则 {i}", pinned=True))

    # 满额：钉新桶被拒（enforce 返回 False = 走普通桶）
    assert await count_pinned() == 3
    assert await enforce_pinned_quota(True) is False

    # 复现步骤：trace(bucket_id, pinned=0) 解钉一个
    await trace_core(ids[0], pinned=0)

    # 计数必须实时下降，且立刻能钉新的——不允许残留旧计数
    assert await count_pinned() == 2
    assert await enforce_pinned_quota(True) is True


@pytest.mark.asyncio
async def test_permanent_type_does_not_occupy_pinned_quota(bucket_mgr):
    """旧根因锁死：解钉后桶留在 permanent 类型/目录，不得再占 pinned 配额。

    （用户实际 17 个 pin 却被报 24：多出来的就是这类残留。）"""
    install_runtime(bucket_mgr, limits={"max_pinned": 3})

    # 2 个真 pinned + 2 个曾 pinned 后解钉的（type 仍是 permanent）
    await bucket_mgr.create(content="真钉 A", pinned=True)
    await bucket_mgr.create(content="真钉 B", pinned=True)
    for i in range(2):
        bid = await bucket_mgr.create(content=f"曾钉 {i}", pinned=True)
        await trace_core(bid, pinned=0)

    # 只数 metadata.pinned=True 的：2，不是 4
    assert await count_pinned() == 2
    # 2 < 3 → 还能钉
    assert await enforce_pinned_quota(True) is True


# ------------------------------------------------------------
# ② importance≥9 配额：trace 降级后计数必须实时同步
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_trace_demote_frees_high_importance_quota(bucket_mgr, monkeypatch):
    install_runtime(bucket_mgr)
    # 上限收小到 3，复刻「超限自动降级」再「trace 释放后恢复」的完整链路
    monkeypatch.setattr("tools._common._HIGH_IMP_HARD_CAP", 3)
    monkeypatch.setattr("tools._common._HIGH_IMP_SOFT_WARN", 3)

    ids = []
    for i in range(3):
        ids.append(await bucket_mgr.create(content=f"重要记忆 {i}", importance=9))

    # 满额：新 hold(importance=9) 被自动降级为 8（OB-I001 行为）
    assert await count_high_importance() == 3
    assert await enforce_high_importance_quota(9) == 8

    # 复现步骤：trace(bucket_id, importance=7) 降级一条
    await trace_core(ids[0], importance=7)

    # 计数实时同步 → 新的 importance=9 不再被误降
    assert await count_high_importance() == 2
    assert await enforce_high_importance_quota(9) == 9


@pytest.mark.asyncio
async def test_pinned_not_counted_in_high_importance_quota(bucket_mgr):
    """旧根因锁死：pinned/protected（importance 锁 10）不占 ≥9 配额。

    （用户实际 18 条 ≥9 却被报 84：虚高部分就是 pinned/permanent 混入。）"""
    install_runtime(bucket_mgr)

    await bucket_mgr.create(content="钉住的核心", pinned=True)      # importance 锁 10
    await bucket_mgr.create(content="普通高重要", importance=9)

    assert await count_high_importance() == 1
