"""TaskSpec / ResearchScope —— workflow 的统一入口规范（架构 §6.4）。

由 CLI/API 在任务启动时构造，写入 workspace/.task.json。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResearchScope(BaseModel):
    """本次任务可用的数据源范围。"""

    vfs_includes: list[str] = Field(default_factory=list, description="纳入索引的 VFS 路径")
    use_web_search: bool = True
    mcp_servers: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    """统一任务规范。

    - workflow_id: 选 WorkflowManifest。
    - inputs: 由 RuntimeWorkflowSpec.input_model 校验。
    """

    task_id: str
    workflow_id: str = "chat"
    workspace_path: str
    inputs: dict[str, Any] = Field(default_factory=dict)

    research_scope: ResearchScope = Field(default_factory=ResearchScope)
    config: dict[str, Any] = Field(default_factory=dict)
