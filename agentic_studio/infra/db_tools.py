"""DB 工具集 —— 只读 run_sql + list_databases（架构「DB 双通道」之 SQL 通道）。

设计要点：
- **复用 Mirage 的只读连接池**：`PostgresResource.accessor.pool()` 建池时
  `server_settings={"default_transaction_read_only": "on"}`，写/DDL 被服务端拒绝。
  run_sql 不另起 asyncpg 客户端 → 同池、同 DSN、同只读强制（不变量 5）。
- **同一个事件循环**：池绑定在 StudioBackend 的常驻 loop 上，所有协程经 `submit`
  （= backend._run，run_coroutine_threadsafe）提交，避免 asyncpg 跨循环 InterfaceError。
- **纵深护栏**：单语句、LIMIT 上限、statement_timeout、显式拒写关键字（服务端只读之外再加一层）。

仅 infra 可 import mirage/langchain（架构 §3 分层）。run_sql 天生 infra-coupled（碰池/loop），
故放 infra/ 而非 tools/（后者是只依赖 core 的纯函数）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.tools import tool

from agentic_studio.infra.resources import DbHandle

# 起手即拒的写/DDL 关键字（服务端只读已挡，这层给出更清晰的错误，省一次往返）
_WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "create", "alter", "truncate",
    "grant", "revoke", "copy", "comment", "reindex", "vacuum", "refresh",
    "call", "do", "merge", "lock", "set",
)
_STATEMENT_TIMEOUT_MS = 15_000
_MAX_OUTPUT_CHARS = 8_000


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)  # 保精度（面积/金额），与 rows.jsonl 一致
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(o))} bytes>"
    return str(o)


async def _exec_readonly(resource: Any, sql: str) -> list[dict[str, Any]]:
    """在只读事务里跑一条 SQL，带 statement_timeout。"""
    pool = await resource.accessor.pool()
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            await conn.execute(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}")
            rows = await conn.fetch(sql)
    return [dict(r) for r in rows]


def make_db_tools(
    registry: list[DbHandle],
    submit: Callable[[Coroutine[Any, Any, Any]], Any],
) -> list[Any]:
    """构造 [list_databases, run_sql]。

    submit: 把协程提交到 StudioBackend 常驻 loop 并阻塞取结果（= backend._run）。
    """
    by_alias = {h.alias: h for h in registry}
    aliases = sorted(by_alias)

    @tool
    def list_databases() -> str:
        """列出本会话已连接的只读数据库：别名、VFS 挂载点、脱敏 DSN。

        与库交互前先看这里。浏览结构：cat <mount>/database.json（跨表外键）、
        cat <mount>/public/tables/<表>/schema.json（列/类型/主外键）。
        """
        if not registry:
            return "（本会话未连接任何数据库）"
        lines = [f"已连接 {len(registry)} 个只读数据库："]
        for h in registry:
            lines.append(f"- {h.alias}: 挂载于 {h.mount}  ({h.masked_dsn})")
        return "\n".join(lines)

    @tool
    def run_sql(database: str, sql: str, limit: int = 200) -> str:
        """对指定数据库执行**只读** SQL（用于 JOIN / 聚合 / 跨表过滤）。

        - database: 库别名（见 list_databases）。
        - sql: 单条 SELECT/WITH 语句。写操作/DDL 会被拒。
        - limit: 返回行上限（默认 200，自动外包一层 LIMIT）。

        写 SQL 前先读对应库的 schema.json（列名/外键），避免列名/连接键猜错。
        不要用 python open('/db/...') 读库——那是真实子进程，看不见 VFS。
        """
        handle = by_alias.get(database)
        if handle is None:
            return f"错误：未知数据库 '{database}'。可用别名：{', '.join(aliases) or '（无）'}"

        q = sql.strip().rstrip(";").strip()
        if not q:
            return "错误：sql 为空。"
        if ";" in q:
            return "错误：一次只允许单条语句。"
        low = q.lstrip("( \t\n").lower()
        if low.startswith(_WRITE_KEYWORDS):
            return "错误：只读连接，禁止写入 / DDL（INSERT/UPDATE/DELETE/CREATE/... 均不允许）。"

        # 自动外包 LIMIT 上限（SELECT/WITH）；其它（EXPLAIN/TABLE/SHOW）原样跑
        capped = q
        if low.startswith(("select", "with", "table")):
            capped = f"SELECT * FROM (\n{q}\n) AS _wrapped LIMIT {int(limit)}"

        try:
            rows = submit(_exec_readonly(handle.resource, capped))
        except Exception as exc:  # noqa: BLE001 —— DB 错误回传给 agent 修
            return f"SQL 执行失败（{database}）：{type(exc).__name__}: {exc}"

        body = json.dumps(rows, default=_json_default, ensure_ascii=False)
        out = f"{len(rows)} row(s) from {database} (limit {limit}):\n{body}"
        if len(out) > _MAX_OUTPUT_CHARS:
            out = out[:_MAX_OUTPUT_CHARS] + "\n…(已截断，请用聚合/更紧的 WHERE 缩小结果)"
        return out

    return [list_databases, run_sql]
