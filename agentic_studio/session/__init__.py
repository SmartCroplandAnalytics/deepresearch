"""session/ —— 会话装配层。

把 TaskSpec 装配成一个运行中的会话（选 infra 实现、挂 skills/tools/backend）。
本层可依赖 infra（选具体引擎），但对外返回 SessionEngine Protocol，业务侧只认抽象。
"""

from agentic_studio.session.build import DEFAULT_MODEL, build_chat_session, build_session
from agentic_studio.session.runner import build_workflow_session, deepresearch_opening

__all__ = [
    "build_session",
    "build_chat_session",
    "DEFAULT_MODEL",
    "build_workflow_session",
    "deepresearch_opening",
]
