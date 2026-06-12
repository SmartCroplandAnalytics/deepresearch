"""装配（确定性）：[证据/节点 id] → [N] 按首次出现重编号 + 参考/来源列表。

能力级共享——corpus 路（grounded_write）与 plugin 路（grounded_brief）唯一的差别是
"id 如何渲染成一条参考条目"，以 `ref_of` 回调注入；重编号逻辑只此一份。
"""

from __future__ import annotations

import re
from collections.abc import Callable

_CITE = re.compile(r"\[([0-9A-Za-z_]+)\]")


def assemble(
    drafted: list[dict],
    ref_of: Callable[[str], str],
    *,
    ref_heading: str = "## 参考文献",
) -> tuple[str, str]:
    """drafted=[{heading, text}] →（正文带 [N]，参考列表 md）。[N] 按全文首次出现序。"""
    order: list[str] = []
    for d in drafted:
        for nid in _CITE.findall(d["text"]):
            if nid not in order:
                order.append(nid)
    num = {nid: i + 1 for i, nid in enumerate(order)}

    parts = []
    for d in drafted:
        text = _CITE.sub(
            lambda m: f"[{num[m.group(1)]}]" if m.group(1) in num else m.group(0), d["text"]
        )
        parts.append(f"{d['heading']}\n\n{text}\n")
    body = "\n".join(parts)

    refs = [ref_heading, ""] + [f"[{num[nid]}] {ref_of(nid)}" for nid in order]
    return body, "\n".join(refs)
