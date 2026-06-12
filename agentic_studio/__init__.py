"""agentic-studio — write/modify/fill 文档生产 agent 会话层。

分层纪律（见 docs/architecture-review-2026-06-session-layer.md §2.5 支线 E）：
- core/   纯数据契约（Pydantic），不导入任何 infra / 第三方 agent 库。
- infra/  适配层：deepagents / langgraph / mirage / docling 只在此出现，藏在 Protocol 之后。
- tools/  自写差异化工具（三粒度检索等），依赖 core，不依赖 deepagents。
- skills/ SKILL.md（能力 skill）。
- session/ 组装 deep agent、运行会话（依赖 infra 的 Protocol）。
- cli/    入口。
"""

__version__ = "0.1.0"
