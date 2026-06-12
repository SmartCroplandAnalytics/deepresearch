"""全文源 v0 测（架构 §13.1/§8）：节点级 md 书 → 研究→写作→in-loop verify（对真实节全文）。
对比"摘要源"那轮，看 verify 是否更精准（队列不再因源太薄而过报）。

uv run python scripts/experiments/md_v0_test.py
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

from agentic_studio.infra.research.md_corpus import MdNodeSearcher  # noqa: E402
from agentic_studio.infra.research.verify import Verifier  # noqa: E402
from agentic_studio.workflows.grounded_write import generate_v0  # noqa: E402

DOCS = "E:/Project/Tsaiyber/Agent Cutting-Edge R&D/agentic-research/test"
MODEL = "deepseek:deepseek-chat"
WS = ".cache/md_v0_test"

SECTIONS = [
    {"id": "1.1", "title": "三峡库区水文化遗产的类型与代表性遗产",
     "content": "梳理三峡库区水文化遗产的主要类型与代表性遗产（如白鹤梁题刻等），及其价值与保护利用现状",
     "key_question": "三峡库区有哪些代表性水文化遗产？其价值与保护现状如何？", "word_count": 700},
]
MILESTONES = {"research_start", "R:end_search", "write_start", "W:verify", "W:done", "section_done"}


def main() -> None:
    load_dotenv()
    print("加载三峡 md 书 + 节点级 embed（首次 ~2-3min）…")
    searcher = MdNodeSearcher(DOCS, tag="sanxia")
    verifier = Verifier(MODEL)
    print(f"节点 {len(searcher.ids)}（节级、全文）。生成 v0（{len(SECTIONS)} 节）。\n")

    def on_event(kind: str, info: dict) -> None:
        if kind in MILESTONES:
            print(f"[{kind}] {info}")

    res = generate_v0(SECTIONS, searcher, verifier, MODEL, WS, on_event=on_event)

    print("\n========== 成稿 ==========\n")
    print(Path(res["manuscript_path"]).read_text(encoding="utf-8"))
    print("\n========== 判断队列 ==========\n")
    print((Path(WS) / "judgment_queue.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
