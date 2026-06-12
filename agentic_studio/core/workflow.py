"""Workflow 层契约 —— 产品语义底层（架构 §5）。

两层分离（§5.1，避免把可序列化配置和运行时 Python 对象混在一起）：
- `WorkflowManifest`（Pydantic，可进 .task.json / registry / CLI / 插件）：稳定契约，
  `input_schema_id` 是**字符串**，不持 Python class。
- `RuntimeWorkflowSpec`（dataclass，装配态）：才允许持 `input_model`（Pydantic class）
  与 `graph_factory`。

ControlMode 只回答一个问题：外层流程由谁控制（§5.2）。默认 CLOSED_LOOP，按实测失败缝毕业。
当前注册：deepresearch、grounded-write（均 CLOSED_LOOP；后者是 /-workflow，领域经 plugin 参数化）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

from agentic_studio.core.task import ResearchScope


class ControlMode(str, Enum):
    CLOSED_LOOP = "closed_loop"  # agent + skill 自主推进
    HYBRID = "hybrid"  # 小图控制阶段，节点里仍跑 agent
    GRAPH = "graph"  # workflow 自己拥有完整图


class WorkflowManifest(BaseModel):
    """稳定、可序列化的 workflow 契约。注册一个新任务 = 注册一个 manifest。"""

    workflow_id: str
    artifact_family: str = "document"          # 首批只有 "document"
    action: str = "gen"                        # document 内先只有 "gen" / "edit"
    control_mode: ControlMode = ControlMode.CLOSED_LOOP
    input_schema_id: str = ""  # 解析为 RuntimeWorkflowSpec.input_model（如 ResearchBrief）
    skills: list[str] = Field(default_factory=list)       # 该 workflow 期望的 skill（目录名）
    tools: list[str] = Field(default_factory=list)        # 逻辑工具 id（runner 解析为实际工具）
    validators: list[str] = Field(default_factory=list)   # 完成判据 / hard gate（workflow 契约）
    workspace_template: str | None = None
    output_artifacts: list[str] = Field(default_factory=list)


@dataclass
class RuntimeWorkflowSpec:
    """装配态：manifest + 解析出的 Python class / graph factory。"""

    manifest: WorkflowManifest
    input_model: type[BaseModel]
    graph_factory: Callable[[], object] | None = None  # 仅 HYBRID/GRAPH


# ──────────────────────────── 文档 workflow 的输入 schema ────────────────────────────


class ResearchBrief(BaseModel):
    """deepresearch 的 input_schema（架构 §5.5）：指令注入，可从文档或对话灌入。"""

    topic: str
    content_requirements: str = Field(default="", description="要覆盖什么（可详细注入）")
    structure: str | None = Field(default=None, description="outline / 章节约束；None = 自由")
    style_guide: str | None = Field(default=None, description="语气/术语，或指向一篇参考文档")
    source_scope: ResearchScope = Field(default_factory=ResearchScope)
    output_constraints: dict = Field(default_factory=dict, description="长度/格式")


class GroundedWriteRequest(BaseModel):
    """grounded-write 的 input_schema：领域 plugin + scope dict。

    scope 的**维度由 plugin 声明**（outline.yaml 的 scope schema），故这里是开放 dict；
    校验发生在能力层（grounded_brief.validate_scope），不在契约层预设年份/地区等领域概念。
    """

    plugin: str = Field(description="领域 plugin 名（skills 目录下的 skill-set）")
    scope: dict = Field(
        default_factory=dict, description="范围参数（键见 plugin 的 scope schema）+ 保留键 sections"
    )


# ──────────────────────────── Registry ────────────────────────────


@dataclass
class WorkflowRegistry:
    """workflow_id → RuntimeWorkflowSpec。"""

    _specs: dict[str, RuntimeWorkflowSpec] = field(default_factory=dict)

    def register(self, spec: RuntimeWorkflowSpec) -> None:
        self._specs[spec.manifest.workflow_id] = spec

    def get(self, workflow_id: str) -> RuntimeWorkflowSpec:
        if workflow_id not in self._specs:
            raise KeyError(
                f"未知 workflow '{workflow_id}'。已注册：{', '.join(self._specs) or '（空）'}"
            )
        return self._specs[workflow_id]

    def list_ids(self) -> list[str]:
        return list(self._specs)


def build_default_registry() -> WorkflowRegistry:
    """内置 workflow（v0.1：先 deepresearch；modify/fill 后续注册）。"""
    reg = WorkflowRegistry()
    reg.register(
        RuntimeWorkflowSpec(
            manifest=WorkflowManifest(
                workflow_id="deepresearch",
                artifact_family="document",
                action="gen",
                control_mode=ControlMode.CLOSED_LOOP,
                input_schema_id="ResearchBrief",
                skills=["deep-research"],
                tools=["web_search", "web_read"],
                validators=["report_exists", "source_floor", "citations_resolve"],
                workspace_template="deep-research",
                output_artifacts=["report.md", "knowledge_base/"],
            ),
            input_model=ResearchBrief,
            graph_factory=None,
        )
    )
    reg.register(
        RuntimeWorkflowSpec(
            manifest=WorkflowManifest(
                workflow_id="grounded-write",
                artifact_family="document",
                action="gen",
                control_mode=ControlMode.CLOSED_LOOP,
                input_schema_id="GroundedWriteRequest",
                skills=["grounded-writing"],  # 能力 SKILL；领域 plugin 经 scope.plugin 动态选
                tools=["gw_generate", "gw_revise", "gw_availability", "gw_scope_schema",
                       "gw_judgments", "gw_resolve_judgment"],
                validators=["citations_resolve", "numbers_grounded", "queue_emitted"],
                workspace_template="grounded-brief",
                output_artifacts=["manuscript.md", "evidence/manifest.json",
                                  "judgment_queue.json", "brief_state.json"],
            ),
            input_model=GroundedWriteRequest,
            graph_factory=None,
        )
    )
    return reg


DEFAULT_REGISTRY = build_default_registry()
