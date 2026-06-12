"""DeepAgentsSession —— SessionEngine 的 deepagents 实现（架构 §5.1、§11）。

**唯一允许 import deepagents / langgraph / mirage 的业务级文件**（连同同目录其它 infra 适配）。
组装：每 session 一个 Mirage Workspace（隔离 VFS）→ LangchainWorkspace backend →
create_deep_agent（+ checkpointer 做会话线程持久化）。运行用同步 `.stream()`（支线 F）。
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver
from mirage.resource.disk import DiskResource
from mirage.types import MountMode
from mirage.workspace.workspace import Workspace

from agentic_studio.infra.llm import resolve_model
from agentic_studio.infra.mirage_backend import StudioBackend
from agentic_studio.infra.resources import DbHandle, mounts_for
from agentic_studio.infra.session import SessionEvent


def make_sqlite_checkpointer(workspace_root: str) -> Any:
    """持久线程态：SqliteSaver 落 `<workspace>/.thread.sqlite`（同 thread_id 跨进程续跑）。

    底层 sqlite 连接由 DeepAgentsSession.close() 统一关闭（checkpointer.conn）。
    langgraph 依赖只出现在 infra（架构 §2.5 支线 E）。
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(workspace_root).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(Path(workspace_root) / ".thread.sqlite"), check_same_thread=False
    )
    return SqliteSaver(conn)


def _text_of(content: Any) -> str:
    """从 LangChain 消息 content 取纯文本（str 或 Anthropic content-block 列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if isinstance(blk, str):
                parts.append(blk)
            elif isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(str(blk.get("text", "")))
        return "".join(parts)
    return ""


class DeepAgentsSession:
    """实现 agentic_studio.infra.session.SessionEngine（同步）。"""

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: str,
        model: str,
        tools: Sequence[Callable | Any] | None = None,
        skills: list[str] | None = None,
        subagents: Sequence[Any] | None = None,
        system_prompt: str | None = None,
        mount_mode: MountMode = MountMode.EXEC,
        db_registry: list[DbHandle] | None = None,
        skills_mounts: dict[str, str] | None = None,
        checkpointer: Any = None,
        allow_exec: bool = True,
        closers: Sequence[Callable[[], None]] | None = None,
    ) -> None:
        self._sid = session_id
        Path(workspace_root).mkdir(parents=True, exist_ok=True)
        self._root = workspace_root
        self._db_registry = db_registry or []
        # 持引用而非拷贝：工具工厂会在会话运行中途 append 关闭器（如 plugin 首次取数时
        # 才建的 MetricStore.close）——拷贝会把这些晚注册的关闭器漏掉。
        self._closers: list[Callable[[], None]] = closers if closers is not None else []
        # 一 session 一 Workspace = 隔离 VFS。EXEC 以支持 grep/glob/bash（经 ws.execute）。
        # 挂在 "/"：deepagents 文件工具按根路径写（如 /notes.md），须与挂载点对齐。
        # db_registry：把多个 Postgres 各挂为只读 /db/<alias>（结构/抽样走文件视图）。
        resources: dict[str, Any] = {"/": DiskResource(root=workspace_root)}
        resources.update(mounts_for(self._db_registry))
        # skill/语料源目录（如 /skills、/corpus）**强制只读**（Mirage 按挂载点模式元组）：
        # 这些是仓库/用户资料，且 SKILL.md 是 agent 的 policy——可写=自我修改 policy 的注入面。
        for _vfs, _host in (skills_mounts or {}).items():
            resources[_vfs] = (DiskResource(root=_host), MountMode.READ)
        self._ws = Workspace(
            resources=resources,
            mode=mount_mode,
            session_id=session_id,
        )
        # allow_exec=False：把 deepagents 的 execute 工具在 backend 层禁掉。Mirage 虚拟 shell
        # 含真子进程的 python 执行内建，能读 env/任意磁盘路径 → 可绕过 MetricStore 等安全
        # 中介拿到 DSN/密钥；不需要命令执行的会话（如写作 runtime）必须关掉。
        self._backend = StudioBackend(self._ws, session_id=session_id, allow_exec=allow_exec)
        # DB 的 SQL 通道：run_sql/list_databases 复用 backend 常驻 loop + 各库只读池。
        tool_list: list[Any] = list(tools or [])
        if self._db_registry:
            from agentic_studio.infra.db_tools import make_db_tools

            tool_list += make_db_tools(self._db_registry, self._backend._run)
        self._checkpointer = checkpointer or InMemorySaver()
        self._agent = create_deep_agent(
            model=resolve_model(model),
            backend=self._backend,
            tools=tool_list,
            skills=skills,
            subagents=list(subagents) if subagents else None,
            system_prompt=system_prompt,
            checkpointer=self._checkpointer,
        )
        self._config: dict[str, Any] = {"configurable": {"thread_id": session_id}}

    @property
    def session_id(self) -> str:
        return self._sid

    def prompt(self, message: str) -> Iterator[SessionEvent]:
        yield SessionEvent(type="turn_start")
        agent_input = {"messages": [{"role": "user", "content": message}]}
        started_tools: set[str] = set()
        # 兜底：万一其它 backend 方法（grep_raw/glob_info）也触发弃用告警，统一压住。
        # 主因 ls_info 已由 StudioBackend 用新名 ls 根治。
        warnings.simplefilter("ignore")
        try:
            for stream_mode, chunk in self._agent.stream(
                agent_input, config=self._config, stream_mode=["messages", "updates"]
            ):
                if stream_mode == "messages":
                    msg, _meta = chunk
                    kind = type(msg).__name__
                    # 助手文本增量
                    delta = _text_of(getattr(msg, "content", ""))
                    if delta:
                        yield SessionEvent(type="text_delta", text=delta)
                    # 工具调用开始（AI chunk 上出现 tool_call_chunks）
                    for tc in getattr(msg, "tool_call_chunks", None) or []:
                        name = tc.get("name")
                        tcid = tc.get("id") or name
                        if name and tcid not in started_tools:
                            started_tools.add(tcid)
                            yield SessionEvent(type="tool_start", tool_name=name)
                    # 工具结果（ToolMessage）
                    if kind == "ToolMessage":
                        yield SessionEvent(
                            type="tool_end",
                            tool_name=getattr(msg, "name", ""),
                            is_error=getattr(msg, "status", "") == "error",
                        )
                # "updates" 模式暂不展开；保留以便将来取 subagent/中断事件
        except Exception as exc:  # noqa: BLE001 —— 顶层把异常转成 error 事件，不吞
            yield SessionEvent(type="error", text=f"{type(exc).__name__}: {exc}")
            return
        yield SessionEvent(type="agent_end")

    def snapshot(self, path: str) -> None:
        # 工作区文件已在 DiskResource(root) 落盘；此处补打包会话线程态（checkpointer）。
        # v0.1：InMemorySaver 不跨进程；持久 checkpointer（如 sqlite）留待 §10 开放项。
        # Mirage snapshot 打包工作区：
        import asyncio

        snap = getattr(self._ws, "snapshot", None)
        if snap is not None:
            asyncio.run(snap(path))

    def close(self) -> None:
        import asyncio
        import inspect

        # 先关各库的只读连接池（须在 backend 常驻 loop 停掉之前，经同一 loop 提交）。
        for h in self._db_registry:
            try:
                self._backend._run(h.resource.accessor.close())
            except Exception:
                pass
        # 调用方注册的资源关闭器（如各 plugin 的 MetricStore 连接）。
        for c in self._closers:
            try:
                c()
            except Exception:
                pass
        # 持久 checkpointer 的底层连接（SqliteSaver.conn；InMemorySaver 无此属性，跳过）。
        conn = getattr(self._checkpointer, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        try:
            closer = getattr(self._ws, "close", None) or getattr(self._ws, "aclose", None)
            if closer is not None:
                if inspect.iscoroutinefunction(closer):
                    asyncio.run(closer())
                else:
                    closer()
        except Exception:
            pass
        try:
            self._backend.shutdown()
        except Exception:
            pass
