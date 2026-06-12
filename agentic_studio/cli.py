"""CLI 入口。子命令：
- info / chat（debug 入口）/ research（DeepResearch，gen 家族）
- write（通用 runtime 对话：/能力 @plugin 约定，--session 续跑）
- brief（grounded-write 一次性驱动：plugin + scope JSON）
- sessions（列举持久会话）"""

from __future__ import annotations

import os
import sys
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from rich import print as rprint

# 静音 deepagents 0.6.7 调 Mirage backend 旧方法 `ls_info` 的弃用告警（每次 ls 刷屏）。
# 根因见 §11.5 支线 F：deepagents 0.7.0 改名 ls，Mirage 仍用 ls_info；已 pin <0.7。
try:
    from langchain_core._api import LangChainDeprecationWarning

    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
except Exception:
    warnings.filterwarnings("ignore", message=r".*ls_info.*")

# Windows 控制台常为 gbk：模型输出可能含 emoji（如 ✅）导致 UnicodeEncodeError 崩溃。
# 保持原编码（中文照常显示），仅把编不了的字符替换为占位符而非崩溃。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

app = typer.Typer(
    add_completion=False, help="agentic-studio: workspace-based agent runtime（chat / research）"
)


@app.command()
def info() -> None:
    """打印版本与已就绪的核心契约（冒烟用）。"""
    from agentic_studio import __version__
    from agentic_studio.core import IndexEntry, Session, TaskSpec  # noqa: F401

    rprint(f"[bold green]agentic-studio[/] v{__version__}")
    rprint("core ready: TaskSpec / IndexEntry / Session / Turn / WorkflowManifest")


def _parse_db_specs(items: list[str]) -> list[tuple[str, str]]:
    """把 --db 的取值解析成 [(alias, dsn)]。支持 'alias=DSN' 或纯 DSN（别名取库名）。"""
    specs: list[tuple[str, str]] = []
    for raw in items:
        raw = raw.strip()
        if not raw:
            continue
        # 仅当 '=' 出现在 '://' 之前才当 alias=DSN，避免误吃 DSN 查询参数里的 '='
        if "://" in raw and "=" in raw.split("://", 1)[0]:
            alias, dsn = raw.split("=", 1)
            alias = alias.strip()
        else:
            dsn = raw
            alias = urlparse(dsn).path.lstrip("/") or f"db{len(specs) + 1}"
        specs.append((alias, dsn))
    return specs


def _db_system_prompt(specs: list[tuple[str, str]]) -> str:
    """多库交互规范：读结构优先 → 抽样 → run_sql；禁 python open。"""
    lines = [f"本会话已连接 {len(specs)} 个只读 Postgres（VFS 挂在 /db/<别名>）："]
    lines += [f"  - {alias} → /db/{alias}" for alias, _ in specs]
    lines += [
        "",
        "与数据库交互的规范：",
        "1) 先用 list_databases 工具确认有哪些库。",
        "2) 读结构（务必先做）：cat /db/<别名>/database.json 看跨表外键；"
        "cat /db/<别名>/public/tables/<表>/schema.json 看列/类型/主外键。",
        "3) 看几行样例：head /db/<别名>/public/tables/<表>/rows.jsonl（会下推成 SQL，便宜）。",
        "4) JOIN / 聚合 / 跨表过滤：用 run_sql(database=<别名>, sql=...)（只读，自动加 LIMIT）；"
        "写 SQL 前必须已读过相关表的 schema.json，避免列名/连接键猜错。",
        "5) 禁止用 Python open('/db/...') / os.listdir 读库——那是真实子进程，看不见 VFS。",
        "6) 别整表遍历：先用聚合或更紧的 WHERE 缩小范围。",
    ]
    return "\n".join(lines)


def _require_model_key(model: str) -> None:
    """校验所选模型 provider 的 API key 已在环境里，否则报错退出。"""
    provider = model.split(":", 1)[0]
    key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider)
    if key_env and not os.environ.get(key_env):
        rprint(f"[red]{key_env} 未设置[/] —— 在 agentic-studio/.env 里填（见 .env.example）")
        raise typer.Exit(1)


def _stream_session(sess, message: str) -> None:
    """流式打印一个会话的事件直到 agent_end，结束后关闭会话。"""
    try:
        for ev in sess.prompt(message):
            if ev.type == "text_delta":
                print(ev.text, end="", flush=True)
            elif ev.type == "tool_start":
                rprint(f"\n[cyan][tool> {ev.tool_name}][/]")
            elif ev.type == "tool_end":
                rprint(f"[dim][tool< {ev.tool_name} {'ERR' if ev.is_error else 'ok'}][/]")
            elif ev.type == "error":
                rprint(f"\n[red][x] {ev.text}[/]")
            elif ev.type == "agent_end":
                print()
    finally:
        sess.close()


@app.command()
def chat(
    message: str = typer.Argument(..., help="发给 agent 的一句话"),
    workspace: str = typer.Option("", "--workspace", "-w", help="工作区目录（默认临时目录）"),
    model: str = typer.Option("deepseek:deepseek-chat", "--model", "-m"),
    db: list[str] = typer.Option(
        None, "--db", help="可重复：'alias=DSN' 或纯 DSN（别名取库名）。每个挂为只读 /db/<alias>"
    ),
    web: bool = typer.Option(
        False, "--web/--no-web", help="联网搜索（默认关；provider 见 AS_WEB_PROVIDER）"
    ),
) -> None:
    """起一个隔离会话并发一条消息，流式打印（需 .env 里的 API key）。"""
    load_dotenv()
    _require_model_key(model)

    from agentic_studio.core import TaskSpec
    from agentic_studio.session import build_session

    sid = f"chat-{uuid.uuid4().hex[:8]}"
    # 默认工作区不放 C 盘：env AS_WORKSPACE_ROOT，否则当前目录下 .workspaces/（运行于 E: 仓库内）。
    base = os.environ.get("AS_WORKSPACE_ROOT") or str(Path.cwd() / ".workspaces")
    ws = workspace or str(Path(base) / sid)
    task = TaskSpec(task_id=sid, workspace_path=ws)
    specs = _parse_db_specs(db or [])
    sys_prompt = _db_system_prompt(specs) if specs else None
    sess = build_session(
        task, model=model, db_specs=specs, system_prompt=sys_prompt, enable_web=web
    )
    db_note = ("  db=" + ",".join(a for a, _ in specs)) if specs else ""
    web_note = "  web=on" if web else ""
    rprint(f"[dim]workspace={ws}  session={sess.session_id}  model={model}{db_note}{web_note}[/]\n")
    _stream_session(sess, message)


@app.command()
def research(
    topic: str = typer.Argument(..., help="研究主题 / 问题"),
    workspace: str = typer.Option("", "--workspace", "-w", help="工作区目录（默认临时目录）"),
    model: str = typer.Option("deepseek:deepseek-chat", "--model", "-m"),
    requirements: str = typer.Option("", "--requirements", help="内容要求（指令注入：要覆盖什么）"),
    structure: str = typer.Option("", "--structure", help="结构 / outline 约束"),
    style: str = typer.Option("", "--style", help="风格要求（语气 / 术语 / 参考文档）"),
    corpus: list[str] = typer.Option(None, "--corpus", help="本地语料 VFS 路径（可重复）"),
    web: bool = typer.Option(True, "--web/--no-web", help="是否用互联网搜索（需 TAVILY_API_KEY）"),
    db: list[str] = typer.Option(
        None, "--db", help="可重复 'alias=DSN'：挂只读 /db/<alias> 作结构化来源"
    ),
) -> None:
    """DeepResearch（gen 家族）：主题 → 带引用的多节研究报告（两阶段、文件化、落工作区）。"""
    load_dotenv()
    _require_model_key(model)
    if web and not os.environ.get("TAVILY_API_KEY"):
        rprint(
            "[yellow]TAVILY_API_KEY 未设置：无 web 来源，仅用 --corpus / --db 本地来源。[/]"
        )

    from agentic_studio.core import ResearchScope, TaskSpec
    from agentic_studio.core.workflow import ResearchBrief
    from agentic_studio.session.runner import build_workflow_session, deepresearch_opening

    sid = f"research-{uuid.uuid4().hex[:8]}"
    base = os.environ.get("AS_WORKSPACE_ROOT") or str(Path.cwd() / ".workspaces")
    ws = workspace or str(Path(base) / sid)
    brief = ResearchBrief(
        topic=topic,
        content_requirements=requirements,
        structure=structure or None,
        style_guide=style or None,
        source_scope=ResearchScope(
            vfs_includes=list(corpus or []), use_web_search=web, mcp_servers=[]
        ),
    )
    specs = _parse_db_specs(db or [])
    task = TaskSpec(
        task_id=sid,
        workflow_id="deepresearch",
        workspace_path=ws,
        inputs=brief.model_dump(),
        research_scope=brief.source_scope,
    )
    sess = build_workflow_session(task, model=model, db_specs=specs)
    db_note = ("  db=" + ",".join(a for a, _ in specs)) if specs else ""
    rprint(
        f"[dim]workspace={ws}  session={sess.session_id}  model={model}  "
        f"web={'on' if web else 'off'}{db_note}[/]\n"
    )
    _stream_session(sess, deepresearch_opening(brief))


_SKILLS_DEFAULT = str(Path(__file__).parent / "skills")


@app.command()
def write(
    message: str = typer.Argument(
        ..., help="对话消息（形如 '/grounded-writing @<plugin> 需求'，或普通聊天）"
    ),
    session: str = typer.Option(
        "studio", "--session", "-s", help="会话 id（同 id+workspace = 续跑）"
    ),
    workspace: str = typer.Option("", "--workspace", "-w", help="工作区（默认按会话 id 定位）"),
    model: str = typer.Option("deepseek:deepseek-chat", "--model", "-m"),
    skills_dir: str = typer.Option(
        _SKILLS_DEFAULT, "--skills", help="skills 根目录（能力+plugin 同处）"
    ),
    corpus: str = typer.Option("", "--corpus", help="只读参考文档目录（挂 /corpus）"),
) -> None:
    """通用 runtime 对话会话（统一 workspace；session 不绑定 plugin，能力按需拉起）。"""
    load_dotenv()
    _require_model_key(model)

    from agentic_studio.session import build_chat_session

    base = os.environ.get("AS_WORKSPACE_ROOT") or str(Path.cwd() / ".workspaces")
    ws = workspace or str(Path(base) / f"write-{session}")
    sess = build_chat_session(
        ws, model, skills_root=skills_dir,
        corpus_dir=corpus or None, session_id=session,
    )
    rprint(f"[dim]workspace={ws}  session={session}  model={model}[/]\n")
    _stream_session(sess, message)


@app.command()
def brief(
    plugin: str = typer.Argument(..., help="领域 plugin：skills 目录下的名字，或 plugin 目录路径"),
    scope: str = typer.Option(
        "{}", "--scope",
        help='scope JSON（键见 plugin 的 scope schema），如 \'{"regions":["成都市"]}\'',
    ),
    workspace: str = typer.Option("", "--workspace", "-w"),
    model: str = typer.Option("deepseek:deepseek-chat", "--model", "-m"),
    skills_dir: str = typer.Option(_SKILLS_DEFAULT, "--skills"),
) -> None:
    """一次性跑 grounded-write 驱动器（不经对话；产物落 workspace）。"""
    import json as _json

    load_dotenv()
    _require_model_key(model)

    from agentic_studio.infra.research.verify import Verifier
    from agentic_studio.workflows.grounded_brief import run_brief

    plugin_dir = plugin if Path(plugin).is_dir() else str(Path(skills_dir) / plugin)
    base = os.environ.get("AS_WORKSPACE_ROOT") or str(Path.cwd() / ".workspaces")
    ws = workspace or str(Path(base) / f"brief-{Path(plugin_dir).name}")
    try:
        def _ev(k: str, a: dict) -> None:
            if k in ("section", "section_done"):
                rprint(f"[dim][{k}] {a}[/]")

        res = run_brief(
            plugin_dir, model, ws,
            scope=_json.loads(scope or "{}"), verifier=Verifier(model), on_event=_ev,
        )
    except (ValueError, RuntimeError) as e:
        rprint(f"[red]{e}[/]")
        raise typer.Exit(1) from e
    rprint(f"\n[bold green]完成[/] 范围：{res['scope']}  节：{res['sections']}"
           f"（跳过 {res['skipped'] or '无'}）  证据：{res['evidence']}  "
           f"判断队列：{res['judgment_items']}")
    rprint(f"manuscript: {res['manuscript_path']}")


@app.command()
def sessions(
    base: str = typer.Option(
        "", "--base", help="会话工作区根（默认 AS_WORKSPACE_ROOT 或 ./.workspaces）"
    ),
) -> None:
    """列举持久会话（各 workspace 的 .session.json）。"""
    from agentic_studio.infra.session_registry import list_sessions

    root = base or os.environ.get("AS_WORKSPACE_ROOT") or str(Path.cwd() / ".workspaces")
    rows = list_sessions(root)
    if not rows:
        rprint(f"[dim]{root} 下没有持久会话[/]")
        return
    for r in rows:
        rprint(f"- [bold]{r.get('session_id')}[/]  {r.get('workspace')}  "
               f"created={r.get('created')}  capabilities={r.get('plugin', '')}")


if __name__ == "__main__":
    app()
