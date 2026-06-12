"""统一 workspace demo（通用 chat runtime）：薄系统提示 + 能力按列表注入 + /能力 @plugin 约定。

会话不绑定任何 plugin：/skills 挂全部 skill（能力+领域），agent 按消息约定自行拉起；
产物落 VFS /manuscript.md、/evidence/，agent 经文件工具读产物再汇报（read-from-artifact）。
命令执行（execute）已禁用（allow_exec=False，防经子进程绕过安全中介）。

  PYTHONUTF8=1 uv run --extra pg --extra viz python scripts/experiments/cropland_session_test.py
（DSN 经 env CROPLAND_DSN，由 plugin 的 datasource.yaml 声明 dsn_env）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from agentic_studio.session import build_chat_session  # noqa: E402

SKILLS = "agentic_studio/skills"
WORKSPACE = str(Path.cwd() / ".cache" / "cropland_session")
CORPUS = "E:/WorkSpace/SmartCroplandAnalytics/deepresearch/test_docs"
MODEL = "deepseek:deepseek-chat"


def stream(sess, msg: str) -> None:
    print(f"\n{'=' * 70}\n>>> 用户：{msg}\n{'-' * 70}")
    for ev in sess.prompt(msg):
        if ev.type == "text_delta":
            print(ev.text, end="", flush=True)
        elif ev.type == "tool_start":
            print(f"\n  [工具→ {ev.tool_name}]")
        elif ev.type == "tool_end":
            print(f"  [工具← {ev.tool_name} {'ERR' if ev.is_error else 'ok'}]")
        elif ev.type == "error":
            print(f"\n  [x] {ev.text}")
        elif ev.type == "agent_end":
            print()


def main() -> None:
    load_dotenv(".env")
    sess = build_chat_session(
        WORKSPACE, MODEL, skills_root=SKILLS, corpus_dir=CORPUS, session_id="cs-demo"
    )
    print(f"统一 workspace：{WORKSPACE}（/ = 产物；/skills = 技能；/corpus = 参考文档）")
    try:
        stream(sess, "先 ls 一下工作区和 /corpus 看看有什么")
        stream(sess, "/grounded-writing @cropland-spatiotemporal 写成都市2020到2023年"
                     "耕地数量变化和结构变化的简报，写好后读 /manuscript.md 把要点讲给我")
    finally:
        sess.close()
    print("\n===== workspace 落盘 =====")
    for p in sorted(Path(WORKSPACE).rglob("*")):
        if p.is_file():
            print("  ", p.relative_to(WORKSPACE))


if __name__ == "__main__":
    main()
