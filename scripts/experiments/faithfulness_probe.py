"""实验①：保真验证可行性探针（de-risk ADR §8 / §19.1 的"唯一警讯"）。

问题：给"论断 + 它引用的源"，LLM 能否稳定判 supported / contradicted / not_mentioned，
尤其能否**抓住被篡改的论断**（"看着 grounded、实则曲解源"是 grounded-write 的核心风险）。

设计（确定性 ground truth，不信任 LLM 生成的标签）：
  从语料抽 N 篇有摘要的，每篇造三类 item——
  · supported     : 摘要里的一句真论断（逐字，支持的下限/sanity floor）
  · contradicted  : 把那句**程序化篡改**（数字翻倍 / 反义词替换 → 强矛盾）
  · not_mentioned : 取**另一篇**摘要的一句（对本源未提及）
  跑 verifier（claim + 源摘要 → 三态），出混淆矩阵；对比单 verifier(temp=0)
  vs 3 票对抗式(temp>0 取多数)。重点指标 = contradicted 召回（漏掉 = 危险）。

用法：
  uv run python scripts/experiments/faithfulness_probe.py --n 20 --model deepseek:deepseek-chat
  （需 .env 里的 DEEPSEEK_API_KEY；--no-ensemble 省一半调用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
for _s in (sys.stdout, sys.stderr):  # Windows gbk 控制台：保证中文/符号可输出
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass
from agentic_studio.infra.corpus.loader import load_card_index  # noqa: E402
from agentic_studio.infra.llm import get_chat_model  # noqa: E402

LABELS = ("supported", "contradicted", "not_mentioned")
SENT_SPLIT = re.compile(r"[。．.!?！？;；\n]+")
NUM = re.compile(r"\d+(?:\.\d+)?")
# 中英反义对（造强矛盾用）：(原, 替换)，双向各试
ANTONYMS = [
    ("提高", "降低"), ("增大", "减小"), ("增加", "减少"), ("上升", "下降"),
    ("加快", "减慢"), ("有效", "无效"), ("显著", "微弱"), ("正相关", "负相关"),
    ("大于", "小于"), ("高于", "低于"), ("稳定", "失稳"), ("成功", "失败"),
    ("increase", "decrease"), ("higher", "lower"), ("positive", "negative"),
    ("effective", "ineffective"), ("stable", "unstable"), ("rise", "fall"),
]

VERIFY_SYS = (
    "你是严格的事实核查员。给你一条「论断」和一段「来源」。"
    "只依据来源判断论断与来源的关系，三选一：\n"
    "- supported：来源明确支持该论断\n"
    "- contradicted：来源与该论断在数值/方向/事实上相反或冲突\n"
    "- not_mentioned：来源既不支持也不否定（未涉及）\n"
    "严禁臆测来源之外的信息。只输出 JSON：{\"label\":\"...\",\"reason\":\"不超过15字\"}"
)


# 样板文（版权 / 著录 / 投稿信息）——绝不能当作 claim
BOILERPLATE = re.compile(
    r"elsevier|springer|wiley|©|copyright|rights reserved|版权|中图分类号|文献标识码|"
    r"文章编号|doi\s*[:：]|issn|received|accepted|published|作者简介|基金项目|通信作者",
    re.IGNORECASE,
)
CJK = re.compile(r"[一-鿿]")
WORD = re.compile(r"[A-Za-z]{2,}")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text or "") if len(s.strip()) >= 12]


def is_good_claim(s: str) -> bool:
    """排除样板文与"数字/标点为主"的非论断句。"""
    if BOILERPLATE.search(s):
        return False
    cjk = len(CJK.findall(s))
    words = len(WORD.findall(s))
    return cjk >= 10 or words >= 6  # 有足够实义内容


def _find_term(s: str, term: str) -> tuple[int, int] | None:
    """定位 term；ASCII 词用词边界（避免 rainfall 里的 fall 被误中），CJK 用子串。"""
    if term.isascii() and term.isalpha():
        m = re.search(r"\b" + re.escape(term) + r"\b", s, re.IGNORECASE)
        return (m.start(), m.end()) if m else None
    i = s.find(term)
    return (i, i + len(term)) if i >= 0 else None


def has_antonym(s: str) -> tuple[str, str] | None:
    for a, b in ANTONYMS:
        if _find_term(s, a) or _find_term(s, b):
            return a, b
    return None


def pick_claim_sentence(abstract: str) -> str | None:
    """取一句**有实义**的论断；优先可造语义矛盾（含方向/反义词），其次含数字，再次最长。"""
    sents = [s for s in sentences(abstract) if is_good_claim(s)]
    if not sents:
        return None
    sem = [s for s in sents if has_antonym(s)]
    if sem:
        return max(sem, key=len)
    num = [s for s in sents if NUM.search(s)]
    return max(num or sents, key=len)


def corrupt(sentence: str) -> tuple[str, str] | None:
    """程序化造强矛盾。**优先反义/方向（语义难例）**，其次数字。造不出返回 None。"""
    pair = has_antonym(sentence)
    if pair:
        a, b = pair
        for src, dst in ((a, b), (b, a)):
            span = _find_term(sentence, src)
            if span:
                i, j = span
                return sentence[:i] + dst + sentence[j:], f"antonym:{src}->{dst}"
    m = NUM.search(sentence)
    if m:
        val = float(m.group())
        new = val * 2 + 1
        new_s = str(int(new)) if val.is_integer() else f"{new:.2f}"
        return sentence[: m.start()] + new_s + sentence[m.end() :], "number"
    return None


def parse_label(text: str) -> str | None:
    t = (text or "").strip().strip("`")
    if t.startswith("json"):
        t = t[4:]
    try:
        obj = json.loads(t[t.find("{") : t.rfind("}") + 1])
        lab = str(obj.get("label", "")).strip().lower()
        if lab in LABELS:
            return lab
    except Exception:
        pass
    for lab in LABELS:  # 回退：文本里找标签词
        if lab in (text or "").lower():
            return lab
    return None


def verify(model, claim: str, source: str) -> str | None:
    user = f"【来源】\n{source}\n\n【论断】\n{claim}"
    try:
        resp = model.invoke([("system", VERIFY_SYS), ("human", user)])
        return parse_label(getattr(resp, "content", str(resp)))
    except Exception as e:
        print(f"  [verify error] {e}", file=sys.stderr)
        return None


def majority(labels: list[str]) -> str | None:
    labels = [x for x in labels if x]
    if not labels:
        return None
    return Counter(labels).most_common(1)[0][0]


def build_items(corpus, n: int) -> list[dict]:
    entries = [e for e in corpus.all() if len((e.abstract or "")) >= 60]
    items: list[dict] = []
    k = len(entries)
    for i, e in enumerate(entries):
        if len([x for x in items if x["gold"] == "contradicted"]) >= n:
            break
        claim = pick_claim_sentence(e.abstract)
        if not claim:
            continue
        corr = corrupt(claim)
        if not corr:
            continue  # 只在能造强矛盾时收这篇，保证 ground truth 干净
        other = entries[(i + k // 2) % k]  # 取较远的一篇做 not_mentioned
        other_claim = pick_claim_sentence(other.abstract)
        if not other_claim or other.doc_id == e.doc_id:
            continue
        src = e.abstract
        items.append({"doc": e.doc_id, "gold": "supported", "claim": claim, "src": src, "m": "verbatim"})
        items.append({"doc": e.doc_id, "gold": "contradicted", "claim": corr[0], "src": src, "m": corr[1]})
        items.append({"doc": e.doc_id, "gold": "not_mentioned", "claim": other_claim, "src": src, "m": f"from:{other.doc_id}"})
    return items


def confusion(items: list[dict], key: str) -> dict:
    cm: dict[str, Counter] = {g: Counter() for g in LABELS}
    for it in items:
        pred = it.get(key)
        if pred:
            cm[it["gold"]][pred] += 1
    return cm


def report(name: str, items: list[dict], key: str) -> None:
    cm = confusion(items, key)
    hdr = "gold\\pred"
    print(f"\n=== {name} ===")
    print(f"{hdr:>16} | " + " ".join(f"{l:>13}" for l in LABELS) + " | recall")
    total_correct = total = 0
    for g in LABELS:
        row = cm[g]
        n = sum(row.values())
        rec = row[g] / n if n else 0.0
        total_correct += row[g]
        total += n
        print(f"{g:>16} | " + " ".join(f"{row[l]:>13}" for l in LABELS) + f" | {rec:5.2f} ({row[g]}/{n})")
    print(f"  overall acc = {total_correct}/{total} = {total_correct/total:.2f}" if total else "  (no preds)")
    # 关键风险：contradicted 漏判（被判成非 contradicted）
    miss = sum(v for k, v in cm["contradicted"].items() if k != "contradicted")
    print(f"  [!] contradicted 漏判（危险）= {miss}/{sum(cm['contradicted'].values())}")
    by_m: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for it in items:
        if it["gold"] == "contradicted":
            mk = it["m"].split(":")[0]
            by_m[mk][1] += 1
            if it.get(key) == "contradicted":
                by_m[mk][0] += 1
    if by_m:
        print("      按篡改方法召回: " + ", ".join(f"{k} {c}/{n}" for k, (c, n) in by_m.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="contradicted item 目标数（每篇造 3 类）")
    ap.add_argument("--model", default="deepseek:deepseek-chat")
    ap.add_argument("--cards", default="E:/WorkSpace/堰塞湖专著/洪水预测篇/index/cards.json")
    ap.add_argument("--abstracts", default="E:/WorkSpace/堰塞湖专著/洪水预测篇/index/abstracts.json")
    ap.add_argument("--no-ensemble", action="store_true")
    ap.add_argument("--ensemble-k", type=int, default=3)
    args = ap.parse_args()

    load_dotenv()
    corpus = load_card_index(args.cards, args.abstracts)
    items = build_items(corpus, args.n)
    print(f"语料 {len(corpus.order)} 篇 → 造 {len(items)} 个 test item（{len(items)//3} 篇 × 3 类）")
    methods = Counter(it["m"].split(":")[0] for it in items if it["gold"] == "contradicted")
    print(f"contradicted 篡改方法分布：{dict(methods)}")

    m0 = get_chat_model(args.model, temperature=0.0)
    for i, it in enumerate(items):
        it["single"] = verify(m0, it["claim"], it["src"])
        if (i + 1) % 10 == 0:
            print(f"  single {i+1}/{len(items)}")
    report("单 verifier (temp=0)", items, "single")

    if not args.no_ensemble:
        mk = get_chat_model(args.model, temperature=0.7)
        for i, it in enumerate(items):
            votes = [verify(mk, it["claim"], it["src"]) for _ in range(args.ensemble_k)]
            it["votes"] = votes
            it["ensemble"] = majority(votes)
            if (i + 1) % 10 == 0:
                print(f"  ensemble {i+1}/{len(items)}")
        report(f"{args.ensemble_k} 票对抗式 (temp=0.7, 取多数)", items, "ensemble")

    out = Path(__file__).resolve().parents[2] / ".cache" / "experiments" / "faithfulness_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已存：{out}")


if __name__ == "__main__":
    main()
