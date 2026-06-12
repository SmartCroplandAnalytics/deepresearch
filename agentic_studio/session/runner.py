"""WorkflowRunner —— 薄分派（架构 §5.3）。按 manifest.control_mode 选运行方式。

- CLOSED_LOOP：`build_session`（挂 skill 源目录 + 按需 web/db）→ 返回 `SessionEngine`，
  由调用方（CLI）流式驱动。
- HYBRID / GRAPH：`spec.graph_factory()`（v0.1 未实现，留 NotImplementedError；§5.2 按证据毕业）。

不新增与 SessionEngine 平级的 GraphEngine：图只在某 workflow 需要时由其私有 graph_factory 出现。
"""

from __future__ import annotations

from pathlib import Path

from agentic_studio.core import TaskSpec
from agentic_studio.core.workflow import (
    DEFAULT_REGISTRY,
    ControlMode,
    ResearchBrief,
    WorkflowRegistry,
)
from agentic_studio.infra.session import SessionEngine
from agentic_studio.session.build import DEFAULT_MODEL, build_session

# 仓库内 skill 源目录：agentic_studio/skills（只读挂为 /skills，供 SkillsMiddleware 扫描）
SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def build_workflow_session(
    task: TaskSpec,
    *,
    model: str = DEFAULT_MODEL,
    db_specs: list[tuple[str, str]] | None = None,
    registry: WorkflowRegistry = DEFAULT_REGISTRY,
) -> SessionEngine:
    """按 task.workflow_id 装配会话（v0.1 仅 CLOSED_LOOP）。"""
    spec = registry.get(task.workflow_id)
    manifest = spec.manifest
    if manifest.control_mode != ControlMode.CLOSED_LOOP:
        raise NotImplementedError(
            f"workflow '{manifest.workflow_id}' control_mode={manifest.control_mode.value}："
            "graph_factory 尚未实现（§5.2：先 CLOSED_LOOP，按实测失败缝再毕业）。"
        )
    enable_web = ("web_search" in manifest.tools) and bool(
        getattr(task.research_scope, "use_web_search", True)
    )
    return build_session(
        task,
        model=model,
        skills_dir=str(SKILLS_DIR),
        enable_web=enable_web,
        db_specs=db_specs,
    )


def deepresearch_opening(brief: ResearchBrief) -> str:
    """把 ResearchBrief 渲染成 deepresearch 的开场指令（指令注入，§5.5）。"""
    lines = [
        "用 deep-research skill 对下面的主题做一次完整深度研究（两阶段、文件化、带引用）。",
        f"主题：{brief.topic}",
    ]
    if brief.content_requirements:
        lines.append(f"内容要求：{brief.content_requirements}")
    if brief.structure:
        lines.append(f"结构要求：{brief.structure}")
    if brief.style_guide:
        lines.append(f"风格要求：{brief.style_guide}")

    scope = brief.source_scope
    sources: list[str] = []
    if scope.use_web_search:
        sources.append("互联网（web 搜索 / 抓取工具）")
    if scope.vfs_includes:
        sources.append(f"本地语料路径：{', '.join(scope.vfs_includes)}")
    if scope.mcp_servers:
        sources.append(f"MCP：{', '.join(scope.mcp_servers)}")
    lines.append("可用来源：" + ("；".join(sources) if sources else "互联网"))
    lines.append("工作区即当前 VFS 根目录。先 ls 工作区、读 SKILL.md，再开始 Stage 1。")
    return "\n".join(lines)
