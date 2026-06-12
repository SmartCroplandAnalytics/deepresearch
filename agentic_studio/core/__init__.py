"""core/ — 稳定数据契约（产品语义层）。

纯 Pydantic v2，零 infra 依赖。对应架构文档 §5「核心数据契约」与 §6。
"""

from agentic_studio.core.index import IndexEntry
from agentic_studio.core.judgment import JudgmentItem
from agentic_studio.core.state import Session, SessionState, Turn, TurnDecision
from agentic_studio.core.task import ResearchScope, TaskSpec
from agentic_studio.core.workflow import (
    DEFAULT_REGISTRY,
    ControlMode,
    ResearchBrief,
    RuntimeWorkflowSpec,
    WorkflowManifest,
    WorkflowRegistry,
    build_default_registry,
)

__all__ = [
    # index
    "IndexEntry",
    # judgment
    "JudgmentItem",
    # task
    "TaskSpec",
    "ResearchScope",
    # state
    "Session",
    "SessionState",
    "Turn",
    "TurnDecision",
    # workflow
    "ControlMode",
    "WorkflowManifest",
    "RuntimeWorkflowSpec",
    "WorkflowRegistry",
    "ResearchBrief",
    "build_default_registry",
    "DEFAULT_REGISTRY",
]
