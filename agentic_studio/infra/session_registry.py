"""会话注册表 —— 支持列举/续跑持久会话（配合 SqliteSaver 跨进程恢复）。

每个会话在其 workspace 根写 `.session.json`（session_id/workspace/title/created/plugin）。
续跑 = 用同一 session_id + 同一 workspace_root 重建 DeepAgentsSession（其 .thread.sqlite 内
对应 thread 的 checkpoint 被加载，对话接着上次继续）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_META = ".session.json"


def write_session_meta(
    workspace_root: str, session_id: str, *, title: str = "", plugin: str = ""
) -> None:
    """在 workspace 根写会话元信息（已存在则保留原 created）。"""
    p = Path(workspace_root)
    p.mkdir(parents=True, exist_ok=True)
    f = p / _META
    created = ""
    if f.exists():
        try:
            created = json.loads(f.read_text(encoding="utf-8")).get("created", "")
        except Exception:  # noqa: BLE001
            pass
    f.write_text(json.dumps({
        "session_id": session_id,
        "workspace": str(p),
        "title": title,
        "plugin": plugin,
        "created": created or datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def list_sessions(base_dir: str) -> list[dict]:
    """扫 base_dir 下各 workspace 的 .session.json，返回会话列表（按 created 倒序）。"""
    out: list[dict] = []
    for f in Path(base_dir).glob(f"*/{_META}"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out, key=lambda d: d.get("created", ""), reverse=True)
