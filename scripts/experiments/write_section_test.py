"""写作微环测（架构 §6/§8）：给一节规格 + 证据，跑 compose→measure→expand→cite-check→判断队列。
含 count_words / cite_check 纯单测（确定性自检）。证据为测试 fixture（验机制，非事实准确性）。

uv run python scripts/experiments/write_section_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from agentic_studio.infra.writing import cite_check, count_words, write_section  # noqa: E402

MODEL = "deepseek:deepseek-chat"

SECTION = {
    "id": "3.2",
    "title": "堰塞体溃决机理物理试验",
    "content": "从库容、背水面坡度、筑坝材料级配等关键参数，阐述其对溃口流量过程与溃决历时的影响",
    "key_question": "库容、坡度、级配如何影响溃口峰值流量与溃决历时？",
    "word_count": 700,
}
# 测试 fixture（id 取自研究子环真实命中，正文为简化示意——本测验机制非事实）
EVIDENCE = [
    {"id": "3231077949", "title": "库容对溃决过程影响的大尺度试验",
     "text": "开展3种不同库容的大尺度堰塞坝溃决试验。结果表明：库容越大，溃口峰值流量越大、溃决历时越长，且过程线更平缓。"},
    {"id": "0617100087", "title": "背水面坡度对溃决过程影响机理大尺度试验",
     "text": "背水面坡度对溃决过程影响显著：坡度越陡，溯源下切速率越快，溃口展宽提前，峰值流量出现时间更早。"},
    {"id": "2806901857", "title": "堰塞坝溃决模拟研究综述与展望",
     "text": "堰塞坝几何形态、粒径级配和库容共同决定溃决机理的复杂性；级配越宽、细颗粒含量越高，坝体抗冲性越强，溃决越缓。"},
]


def unit_checks() -> None:
    assert count_words("溃决机理 dam breach 试验") == 6 + 2, count_words("溃决机理 dam breach 试验")
    cc = cite_check("库容大[3231077949]，坡度陡[0617100087]，但[FAKE999]不存在。", ["3231077949", "0617100087"])
    assert cc["dangling"] == ["FAKE999"], cc
    assert "2806901857" not in cc["cited"]
    print("✓ count_words / cite_check 单测通过")


def main() -> None:
    load_dotenv()
    unit_checks()
    print(f"\n写作微环：节 {SECTION['id']} 目标 {SECTION['word_count']} 字，证据 {len(EVIDENCE)} 条\n")

    def on_event(kind: str, info: dict) -> None:
        print(f"[W] {kind} {info}")

    text, items, stats = write_section(SECTION, EVIDENCE, MODEL, on_event=on_event)

    print("\n===== 正文 =====")
    print(text)
    print("\n===== 统计 =====")
    print(stats)
    print("\n===== 判断队列 =====")
    for it in items:
        print(f"  [{it.type} L{it.leverage}] {it.detail} → {it.suggested_action}")
    if not items:
        print("  （空：字数达标、引用全部解析）")


if __name__ == "__main__":
    main()
