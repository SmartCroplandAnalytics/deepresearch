"""workflows/ —— 每个 workflow 私有的编排（graph_factory / orchestrator），架构 §5.3。

GRAPH/HYBRID 控制模式的 workflow 在此放自己的外层编排；节点内可起 session / 调工具。
不新增与 SessionEngine 平级的全局引擎——编排是 per-workflow 的。

- grounded_write：corpus 路（研究子环 → 写作微环）
- grounded_brief：plugin 路（大纲 + scope schema + EvidenceProvider）= grounded-write 能力驱动器
- chat_runtime：通用对话外壳（runtime/harness；能力按列表注入，/能力 @plugin 约定）
"""

from agentic_studio.workflows.grounded_write import assemble, generate_v0

__all__ = ["generate_v0", "assemble"]
