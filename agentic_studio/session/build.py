"""把 TaskSpec 装配成一个 SessionEngine（架构 §5.1）。

v0.1 用 deepagents 引擎（B1a）。换裸 LangGraph（B1b）只需在此换一个引擎实现，
业务侧（cli/tools/skills）不动——因为返回类型是 infra.session.SessionEngine Protocol。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from agentic_studio.core import TaskSpec
from agentic_studio.infra.session import SessionEngine

DEFAULT_MODEL = "deepseek:deepseek-chat"


def build_session(
    task: TaskSpec,
    *,
    model: str = DEFAULT_MODEL,
    skills: list[str] | None = None,
    skills_dir: str | None = None,
    tools: Sequence[Callable | Any] | None = None,
    enable_web: bool = False,
    system_prompt: str | None = None,
    db_specs: list[tuple[str, str]] | None = None,
) -> SessionEngine:
    """根据 TaskSpec 构造一个隔离会话。

    - db_specs=[(alias, dsn), ...]：每个库挂为只读 /db/<alias>。
    - skills_dir：仓库内 skill 源目录，只读挂为 /skills 并加入 create_deep_agent(skills=…)。
    - enable_web：追加 Tavily web 搜索/抓取工具（缺 key 时静默跳过）。
    """
    # 延迟 import：只有真正建会话时才拉起 deepagents/mirage（重依赖）。
    from agentic_studio.infra.deepagents_engine import DeepAgentsSession
    from agentic_studio.infra.resources import build_db_registry

    skills_sources = list(skills or [])
    skills_mounts: dict[str, str] = {}
    if skills_dir:
        skills_sources.append("/skills")
        skills_mounts["/skills"] = str(skills_dir)

    tool_list: list[Any] = list(tools or [])
    if enable_web:
        from agentic_studio.infra.web import make_web_tools

        tool_list += make_web_tools()

    return DeepAgentsSession(
        session_id=task.task_id,
        workspace_root=task.workspace_path,
        model=model,
        tools=tool_list,
        skills=skills_sources or None,
        skills_mounts=skills_mounts or None,
        system_prompt=system_prompt,
        db_registry=build_db_registry(db_specs or []),
    )


def build_chat_session(
    workspace_root: str,
    model: str = DEFAULT_MODEL,
    *,
    skills_root: str,
    capabilities: Sequence[str] = ("grounded-writing",),
    corpus_dir: str | None = None,
    session_id: str = "chat",
    system_prompt: str | None = None,
) -> SessionEngine:
    """通用 runtime 对话会话（统一 workspace），**不绑死任何 plugin**（工程规范 §13）。

    - 薄系统提示（prompts/runtime_sys.md：VFS 约定、`/能力 @plugin` 消息约定、诚实底线）；
      能力 policy 经 /skills 的 SKILL.md 按需拉起；能力工具按 capabilities 列表注入。
    - system_prompt 可覆盖默认 runtime 提示：场景化产品层（如固定单一 plugin 的对话服务）
      在调用侧拼自己的提示词；runtime 本身仍不绑定领域。
    - /skills、/corpus 由引擎强制只读挂载；**allow_exec=False**（写作会话不给命令执行，
      防经子进程读 env/DSN 绕过安全中介）。
    - 持久线程态 SqliteSaver 落 workspace/.thread.sqlite；closers **传引用**（能力工具
      运行中途登记的连接关闭器也会在 close 时执行）。
    """
    from agentic_studio import prompts
    from agentic_studio.infra.deepagents_engine import (
        DeepAgentsSession,
        make_sqlite_checkpointer,
    )
    from agentic_studio.infra.session_registry import write_session_meta
    from agentic_studio.workflows.chat_runtime import build_capability_tools

    tools, closers = build_capability_tools(
        skills_root, workspace_root, model, capabilities, full_body=False
    )
    mounts = {"/skills": str(skills_root)}
    if corpus_dir:
        mounts["/corpus"] = corpus_dir
    write_session_meta(workspace_root, session_id, plugin=",".join(capabilities))
    return DeepAgentsSession(
        session_id=session_id,
        workspace_root=workspace_root,
        model=model,
        tools=tools,
        system_prompt=system_prompt or prompts.load("runtime_sys"),
        skills_mounts=mounts,
        checkpointer=make_sqlite_checkpointer(workspace_root),
        allow_exec=False,
        closers=closers,
    )
