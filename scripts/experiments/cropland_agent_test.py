"""对话 demo（裸 langgraph 外壳）：/grounded-writing @plugin 意图 → scope → 执行 → 诚实无数据。

会话**不绑定 plugin**：薄 runtime 系统提示 + list_skills/launch_skill + gw_* 能力工具。
  PYTHONUTF8=1 uv run --extra pg --extra viz python scripts/experiments/cropland_agent_test.py
（DSN 经 env CROPLAND_DSN，由 plugin 的 datasource.yaml 声明 dsn_env）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

from agentic_studio.workflows.chat_runtime import build_react_agent  # noqa: E402

SKILLS = "agentic_studio/skills"
WORKSPACE = ".cache/cropland_agent"
MODEL = "deepseek:deepseek-chat"


def say(agent, cfg, msg: str) -> None:
    print(f"\n{'=' * 70}\n>>> 用户：{msg}\n{'-' * 70}")
    out = agent.invoke({"messages": [("user", msg)]}, config=cfg)
    for m in out["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            print(f"  [调用工具] {tc['name']}({str(tc['args'])[:200]})")
        if type(m).__name__ == "ToolMessage":
            print(f"  [工具返回] {str(m.content)[:300]}")
    final = out["messages"][-1]
    print(f"<<< 助手：{getattr(final, 'content', '')}")


def main() -> None:
    load_dotenv(".env")
    agent = build_react_agent(WORKSPACE, MODEL, skills_root=SKILLS)
    cfg = {"configurable": {"thread_id": "demo-1"}, "recursion_limit": 40}

    # 轮1：/能力 @plugin 约定 + 自然语言 → 意图解析（按 plugin SKILL 维度）→ gw_generate
    say(agent, cfg,
        "/grounded-writing @cropland-spatiotemporal 帮我写一份成都市2020到2023年"
        "耕地数量变化和结构变化的简报")
    # 轮2：区县 → 诚实无数据
    say(agent, cfg, "那巴中市恩阳区的耕地情况能一起做吗？")


if __name__ == "__main__":
    main()
