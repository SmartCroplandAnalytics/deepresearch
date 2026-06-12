"""判断队列数据模型（架构 §8）—— 把压倒性复杂度转成按杠杆排序、可逐条处置的人裁决项。

§8 标注：入队判据是开放问题（triage 难），v0.1 用启发式产条目。本模块只定**数据契约**，
不假装解决 triage。纯 pydantic（core 层），可序列化到 judgment_queue.md / json。
"""

from __future__ import annotations

import zlib

from pydantic import BaseModel, Field

# 杠杆排序（越大越优先呈递给人）：矛盾/方向 > 未核实/悬空引用 > 缺口 > 格式
LEVERAGE: dict[str, int] = {
    "contradiction": 5,       # 源↔源 或 论断↔源 冲突（§8 保真层）
    "direction": 5,           # 方向/取舍是否要改（宏观）
    "ungrounded_number": 5,   # 正文数字未见于本节证据（确定性护栏，疑编造/改写）
    "unverified": 4,          # 载荷性但未核实的论断
    "dangling_cite": 4,       # 引用了不存在/不在证据中的 [id]
    "gap": 3,                 # 覆盖缺口 / 字数不足 / key_question 未答
    "format": 1,              # 风格/格式
}


class JudgmentItem(BaseModel):
    """一条待人裁决的高杠杆枢纽（§2.5 边界二的产物）。"""

    id: str
    type: str                                   # 见 LEVERAGE 的键（contradiction/gap/…）
    ref: str = ""                               # 定位：section id / node id / anchor
    detail: str = ""                            # 是什么问题
    suggested_action: str = ""                  # 建议动作（gather / compose / 核对 …）
    leverage: int = 1                           # 排序权重（默认按 type 取 LEVERAGE）
    status: str = "open"                        # open | resolved | dismissed
    meta: dict = Field(default_factory=dict)

    @classmethod
    def make(
        cls, type: str, ref: str, detail: str, action: str = "", **meta: object
    ) -> JudgmentItem:
        # 稳定 id：crc32（str 的 hash() 每进程随机化，跨进程不可比）
        n = zlib.crc32(f"{type}|{ref}|{detail}".encode()) % 100000
        return cls(
            id=f"{type}-{ref}-{n}",
            type=type, ref=ref, detail=detail,
            suggested_action=action,
            leverage=LEVERAGE.get(type, 1),
            meta=dict(meta),
        )
