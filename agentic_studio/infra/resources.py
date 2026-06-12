"""额外 VFS 挂载 + 数据库注册表 —— 把异构数据源挂进会话工作区（Mirage 的核心能力）。

一个会话可连接**多个** Postgres：每个库挂为只读 `/db/<alias>`（表暴露为
`/db/<alias>/public/tables/<t>/{schema.json, rows.jsonl}`）。这是「数据访问统一经
Mirage VFS」（不变量 5）在 DB 上的体现：结构/抽样走文件视图，JOIN/聚合走 run_sql
（复用同一个只读连接池，见 infra/db_tools.py）。仅 infra 可 import mirage。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DB_ROOT = "/db"


@dataclass
class DbHandle:
    """一个已连接数据库的登记项（注册表的一行）。"""

    alias: str
    dsn: str
    resource: Any  # mirage PostgresResource（懒连接）

    @property
    def mount(self) -> str:
        """VFS 挂载点，如 /db/crop。"""
        return f"{DB_ROOT}/{self.alias}"

    @property
    def masked_dsn(self) -> str:
        """脱敏 DSN（隐藏密码），用于展示给 agent / 日志。"""
        return re.sub(r"(://[^:/@]+:)[^@/]*(@)", r"\1***\2", self.dsn)


def build_db_registry(specs: list[tuple[str, str]]) -> list[DbHandle]:
    """specs = [(alias, dsn), ...] → 一组 DbHandle（构造 Mirage PostgresResource，懒连接）。"""
    if not specs:
        return []
    from mirage.resource.postgres import PostgresResource
    from mirage.resource.postgres.config import PostgresConfig

    return [
        DbHandle(alias=alias, dsn=dsn, resource=PostgresResource(PostgresConfig(dsn=dsn)))
        for alias, dsn in specs
    ]


def mounts_for(registry: list[DbHandle]) -> dict[str, Any]:
    """把注册表转成 Mirage Workspace 的 mount→resource 字典（挂在 /db/<alias>）。"""
    return {h.mount: h.resource for h in registry}
