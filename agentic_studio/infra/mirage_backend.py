"""StudioBackend —— Mirage backend 的三处加固（架构 §11.5 支线 F 正解）。

1. **新方法名**：deepagents 0.6.7 见 backend 只有旧名 `ls_info` 会刷弃用告警（0.7.0 要求 `ls`）。
   这里直接实现 `ls`/`als` 返回 `LsResult`，消告警 + 兼容 0.7。
2. **常驻事件循环**：Mirage 原 `LangchainWorkspace._run` 每次 `asyncio.run()` 开新循环，而 asyncpg
   连接池绑定在创建它的循环上 → 多次/并行 DB 读会 `InterfaceError: another operation in progress`
   或循环失效。改为一个跑在独立线程里的常驻循环，所有协程经 run_coroutine_threadsafe 提交：
   连接池只在该循环创建、跨调用有效，并行工具调用也安全（asyncpg 池分配独立连接）。
3. **execute 闸门（allow_exec）**：LangchainWorkspace 实现 SandboxBackendProtocol，deepagents
   会注册 `execute` 工具；而 Mirage 虚拟 shell 含真子进程的 python 执行内建——能读环境变量与
   任意磁盘路径（含 .env 的 DSN/密钥），可绕过 MetricStore 等安全中介。不需要命令执行的会话
   （写作 runtime）传 allow_exec=False，把 execute 在 backend 层挡掉。

仅 infra 可 import mirage/deepagents（架构 §2.5 支线 E）。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from deepagents.backends.protocol import ExecuteResponse, LsResult
from mirage.agents.langchain.backend import LangchainWorkspace

_EXEC_DENIED = (
    "本会话已禁用命令执行（execute）。请改用文件工具：ls / read_file / write_file / "
    "edit_file / grep / glob；数据取数走会话提供的具名工具。"
)


class StudioBackend(LangchainWorkspace):
    def __init__(self, *args: Any, allow_exec: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._allow_exec = allow_exec
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="studio-backend-loop"
        )
        self._loop_thread.start()

    # —— execute 闸门 ——
    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if not self._allow_exec:
            return ExecuteResponse(output=_EXEC_DENIED, exit_code=1)
        return super().execute(command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:  # noqa: ASYNC109
        if not self._allow_exec:
            return ExecuteResponse(output=_EXEC_DENIED, exit_code=1)
        return await super().aexecute(command, timeout=timeout)

    def _run(self, coro):
        # 覆盖 Mirage 的 asyncio.run(coro)：提交到常驻循环，线程安全、复用同一 asyncpg 池。
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    # —— deepagents 新方法名 ——
    def ls(self, path: str) -> LsResult:
        return LsResult(entries=self.ls_info(path))

    async def als(self, path: str) -> LsResult:
        return LsResult(entries=await self.als_info(path))

    def shutdown(self) -> None:
        """停掉常驻循环线程。"""
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        thread = getattr(self, "_loop_thread", None)
        if thread is not None:
            thread.join(timeout=2)
