"""实验②：大文档分层检索探针（de-risk ADR §13/§14 的"大文档=子语料"分形索引）。

问题：当参考是大文档（书稿，几十万字）时，doc-level 一篇一向量太粗、读整篇爆上下文。
办法：把文档按标题切成"节"（叶节点），跨所有文档汇成一个节点池，**节点级 Hop-0 召回**。
本探针验两件事：
  1. 节点级全文 embedding 能否把一个 query 路由到正确的节（cross-doc recall@k）。
  2. 洞 B：用"节全文"向量 vs 用"前200字"向量，召回差多少。

ground truth（自监督）：抽 S 个节，让 LLM 为每个节生成一个**足够特定**（含该节具体细节）
的中文问题；gold = 该节。在全部节里检索，看 gold 排第几。

注：洞 A（脏文档鲁棒性：扫描件/烂结构）本探针**不处理**——假设 md 标题基本可用；
仅对超长节按字数切窗（embedding 上限所需，非语义分块）。

用法：
  uv run python scripts/experiments/largedoc_retrieval_probe.py --queries 40 --model deepseek:deepseek-chat
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass
from agentic_studio.infra.corpus.embed import Embedder, cosine_topk  # noqa: E402
from agentic_studio.infra.llm import get_chat_model  # noqa: E402

DOCS_DIR = "E:/Project/Tsaiyber/Agent Cutting-Edge R&D/agentic-research/test"
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
MAX_CHARS = 3000   # 叶节点上限（超出按窗切，bge-m3 token 上限所需）
OVERLAP = 300
MIN_SECTION = 200  # 太短的节不作 query 源


def split_sections(text: str, doc: str) -> list[dict]:
    """按 md 标题切节；维护标题面包屑；超长节按字数切窗。返回叶节点列表。"""
    lines = text.split("\n")
    stack: list[tuple[int, str]] = []   # (level, title)
    cur: list[str] = []
    cur_crumb = ""
    sections: list[dict] = []

    def flush():
        body = "\n".join(cur).strip()
        if body:
            sections.append({"doc": doc, "crumb": cur_crumb, "text": body})

    for ln in lines:
        m = HEADING.match(ln)
        if m:
            flush()
            cur = []
            level = len(m.group(1))
            title = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_crumb = " > ".join(t for _, t in stack)
            cur = [ln]
        else:
            cur.append(ln)
    flush()
    if not sections:  # 无标题：整篇作一节
        sections = [{"doc": doc, "crumb": doc, "text": text.strip()}]

    # 超长节切窗
    leaves: list[dict] = []
    for s in sections:
        t = s["text"]
        if len(t) <= MAX_CHARS:
            leaves.append(s)
            continue
        i = 0
        while i < len(t):
            leaves.append({"doc": s["doc"], "crumb": s["crumb"] + " [窗]", "text": t[i : i + MAX_CHARS]})
            i += MAX_CHARS - OVERLAP
    return leaves


def embed_text(node: dict) -> str:
    """节全文（含面包屑作上下文）。"""
    return f"{node['crumb']}\n{node['text']}"


def head200(node: dict) -> str:
    return f"{node['crumb']}\n{node['text'][:200]}"


GEN_SYS = (
    "下面是某文档中的一节。请生成**一个**用户可能会问、且**只能/最适合由这节内容回答**的中文问题。"
    "要求：包含该节的一个具体细节（数据/专名/事件），使问题足够特定；不要照抄原文整句；只输出问题本身。"
)


def gen_query(model, node: dict) -> str | None:
    try:
        r = model.invoke([("system", GEN_SYS), ("human", node["text"][:1500])])
        q = getattr(r, "content", str(r)).strip().splitlines()[0].strip()
        return q or None
    except Exception as e:
        print(f"  [genq error] {e}", file=sys.stderr)
        return None


def embed_cached(emb: Embedder, texts: list[str], tag: str, cache_dir: Path):
    """embed 并缓存（按 texts+tag 指纹）——大语料 embed 几十分钟，缓存后复用。"""
    import hashlib

    import numpy as np

    fp = hashlib.sha256(("||".join(texts) + tag).encode("utf-8")).hexdigest()[:16]
    p = cache_dir / f"emb_{tag}_{fp}.npz"
    if p.exists():
        print(f"  embedding 缓存命中：{p.name}")
        return np.load(p)["m"]
    m = emb.encode(texts, batch_size=64)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(p, m=m)
    return m


def recall_at(ranks: list[int], k: int) -> float:
    return sum(1 for r in ranks if r is not None and r < k) / len(ranks) if ranks else 0.0


def mrr(ranks: list[int]) -> float:
    return sum(1.0 / (r + 1) for r in ranks if r is not None) / len(ranks) if ranks else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--model", default="deepseek:deepseek-chat")
    ap.add_argument("--docs", default=DOCS_DIR)
    args = ap.parse_args()
    load_dotenv()

    files = sorted(Path(args.docs).rglob("*.md"))
    nodes: list[dict] = []
    for f in files:
        nodes += split_sections(f.read_text(encoding="utf-8", errors="ignore"), f.name)
    nodes = [n for n in nodes if len(n["text"].strip()) >= 30]  # 丢弃空/OCR垃圾标题节
    print(f"{len(files)} 份文档 → {len(nodes)} 个叶节点")
    sizes = sorted(len(n["text"]) for n in nodes)
    print(f"节大小（字）: min={sizes[0]} 中位={sizes[len(sizes)//2]} max={sizes[-1]}")

    emb = Embedder()
    cache_dir = Path(__file__).resolve().parents[2] / ".cache" / "experiments" / "emb_cache"
    print("embedding 节全文 …")
    full_mat = embed_cached(emb, [embed_text(n) for n in nodes], "full", cache_dir)
    print("embedding 前200字 …")
    h200_mat = embed_cached(emb, [head200(n) for n in nodes], "h200", cache_dir)

    rng = random.Random(0)
    cand = [i for i, n in enumerate(nodes) if len(n["text"]) >= MIN_SECTION]
    picks = rng.sample(cand, min(args.queries, len(cand)))
    model = get_chat_model(args.model, temperature=0.3)

    results = []
    for j, gi in enumerate(picks):
        q = gen_query(model, nodes[gi])
        if not q:
            continue
        qv = emb.encode([q])[0]
        rank_full = [i for i, _ in cosine_topk(qv, full_mat, len(nodes))].index(gi)
        rank_h200 = [i for i, _ in cosine_topk(qv, h200_mat, len(nodes))].index(gi)
        results.append({"q": q, "gold": gi, "doc": nodes[gi]["doc"],
                        "crumb": nodes[gi]["crumb"], "rank_full": rank_full, "rank_h200": rank_h200})
        if (j + 1) % 10 == 0:
            print(f"  query {j+1}/{len(picks)}")

    rf = [r["rank_full"] for r in results]
    rh = [r["rank_h200"] for r in results]
    print(f"\n=== 路由召回（{len(results)} 个 query，在 {len(nodes)} 节中检索）===")
    print(f"{'':>14} | R@1   R@5   R@10  MRR")
    print(f"{'节全文向量':>14} | {recall_at(rf,1):.2f}  {recall_at(rf,5):.2f}  {recall_at(rf,10):.2f}  {mrr(rf):.2f}")
    print(f"{'前200字向量':>14} | {recall_at(rh,1):.2f}  {recall_at(rh,5):.2f}  {recall_at(rh,10):.2f}  {mrr(rh):.2f}")
    worse = sum(1 for r in results if r["rank_h200"] > r["rank_full"])
    print(f"  洞 B：前200字向量比全文向量排名更差的 query = {worse}/{len(results)}")

    out = Path(__file__).resolve().parents[2] / ".cache" / "experiments" / "largedoc_retrieval_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已存：{out}")


if __name__ == "__main__":
    main()
