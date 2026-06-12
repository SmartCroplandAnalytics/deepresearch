"""Session / Turn —— 会话生命周期状态（架构 §5.4 + §10）。

注意持久化分层（架构 §2.5 支线 A）：
- 工作区文件（artifacts）→ Mirage VFS（单一真相）；
- 会话线程 / agent 运行态 → deepagents checkpointer；
- 本 Session 模型是「产品语义层的会话摘要」，持久化到 workspace/.session.json，
  用于 CLI resume 决定从哪个 mode/round 继续。snapshot 时需与 checkpointer 一并打包。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from agentic_studio.core.task import TaskSpec


class SessionState(str, Enum):
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class TurnDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    FURTHER = "further"


class Turn(BaseModel):
    """modify 模式中的一轮用户交互。"""

    turn_id: str
    user_input: str
    intent: dict = Field(default_factory=dict)
    edits_proposed: list[dict] = Field(default_factory=list)
    diff_path: str | None = None
    user_decision: TurnDecision | None = None
    timestamp: datetime


class Session(BaseModel):
    """一次完整任务的生命周期。"""

    session_id: str
    task_spec: TaskSpec
    state: SessionState = SessionState.RUNNING
    current_round: int = 0
    current_stage: str | None = None
    thread_id: str | None = Field(
        default=None, description="deepagents checkpointer 的 thread_id（支线 A：会话线程态）"
    )
    turns: list[Turn] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
