"""SessionEngine Protocol —— deepagents 的隔离边界（架构 §2.5 支线 E）。

本文件**不导入 deepagents**。定义本项目自己的会话接口；deepagents 的具体实现
放在 infra/deepagents_engine.py（依赖 [agent]+[vfs] extra）。core/tools/skills/session/cli
只依赖此抽象，未来可整体换裸 LangGraph（B1b 退路）而不动业务层。

**v0.1 同步**（架构 §11.3 as-built 决策）：Mirage `LangchainWorkspace` 的 fs 方法是
`asyncio.run()` 同步包装，故会话用同步 `.invoke()/.stream()` 驱动，prompt() 是同步生成器；
不可用 `.ainvoke()`（会在运行中的事件循环里再调 asyncio.run 而报错）。异步化留待后续。

事件流贴近通用 coding-agent harness 形态（turn_start/text_delta/tool_*/agent_end，架构 §2.3）。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

EventType = Literal[
    "turn_start",
    "text_delta",
    "tool_start",
    "tool_end",
    "agent_end",
    "error",
]


@dataclass
class SessionEvent:
    """会话运行期的一个流式事件。"""

    type: EventType
    text: str = ""  # text_delta 的增量；error 的消息
    tool_name: str = ""  # tool_start / tool_end
    is_error: bool = False  # tool_end
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SessionEngine(Protocol):
    """一次隔离会话的运行接口。一个实例 == 一个隔离 session。

    持久化协调（架构 §2.5 支线 A）：工作区文件落 Mirage VFS（单一真相）；会话线程态由
    实现内部 checkpointer 持有；snapshot() 须把二者一并打包，便于跨进程恢复。
    """

    @property
    def session_id(self) -> str: ...

    def prompt(self, message: str) -> Iterator[SessionEvent]:
        """投入一条用户消息，同步流式产出事件直到 agent_end。"""
        ...

    def snapshot(self, path: str) -> None:
        """把工作区 + 会话线程态序列化到 path（跨进程恢复）。"""
        ...

    def close(self) -> None:
        """释放资源（VFS、连接等）。"""
        ...
