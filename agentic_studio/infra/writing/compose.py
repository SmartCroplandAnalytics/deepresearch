"""写作子环 · 自主写作微环（架构 §6/§8 微观自纠）。

compose（按证据写一节）→ measure→expand（字数软目标，差不多即可）→ cite-check（[id] 解析）
→ 产出判断队列条目（悬空引用 / 字数缺口）。verify/矛盾检测的载荷论断由研究侧或收尾保真补。

`count_words`/`cite_check` 是确定性自检（agent 微观闭环的"传感器"，§8）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from agentic_studio import prompts
from agentic_studio.core.judgment import JudgmentItem
from agentic_studio.infra.llm import get_chat_model

_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z]+")
_CITE = re.compile(r"\[([0-9A-Za-z_]+)\]")
_SENT = re.compile(r"[^。！？\n]+")
_DIGIT = re.compile(r"\d")
_NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?")
# 量纲单位：短整数（<3位）通常是枚举噪声（"21个市州"），但跟着量纲单位（面积/比例/金额）
# 就是载荷数字（"增加21万亩"），不论位数都核。计数单位（个/座/类）刻意不收——枚举常见且低害。
_UNITS = ("万亩", "公顷", "平方公里", "亩", "万元", "亿元", "%", "％")
MAX_VERIFY = 5  # 每节最多核对的载荷论断数（控成本）
MAX_NUM_ITEMS = 8  # 每节最多入队的 ungrounded_number 条目（防刷屏）

MAX_EXPAND = 3
MAX_REPAIR = 1  # 确定性违例的定向修复轮数（内环自纠；修不好才升级入队）
TOL = 0.15  # 字数容差："差不多就行"


def count_words(text: str) -> int:
    """CJK 字 + 英文词（中文专著的字数口径，仿手稿测量）。"""
    return len(_CJK.findall(text or "")) + len(_WORD.findall(text or ""))


def cite_check(text: str, valid_ids: list[str]) -> dict:
    """检查正文里的 [id] 引用是否都在证据集中。"""
    cited = set(_CITE.findall(text or ""))
    valid = set(valid_ids)
    return {
        "cited": sorted(cited),
        "dangling": sorted(cited - valid),       # 引用了不在证据中的 id（危险）
        "uncited_evidence": sorted(valid - cited),  # 给了但没用上的证据
    }


def number_check(text: str, evidence_texts: list[str]) -> list[tuple[str, str]]:
    """确定性数字护栏：正文里的载荷数字必须**逐字**出现在本节证据中。

    比 LLM verifier 更强的子集检查（零成本、100% 覆盖数字）：扩写改坏、
    四舍五入、自行计算、年份误标全在此被抓。返回 [(数字token, 所在句)]。
    - 短整数（<3 位且无小数点）默认跳过（枚举噪声），**但带量纲单位的照核**（"21万亩"）。
    - 引用标记 [id]（可含数字）先剥掉再查。
    - 容差：字符串相等 或 数值相等（1.20 vs 1.2）。
    """
    ev_tokens: set[str] = set()
    for t in evidence_texts:
        ev_tokens.update(_NUM_TOKEN.findall(t or ""))
    ev_floats: set[float] = set()
    for t in ev_tokens:
        try:
            ev_floats.add(float(t))
        except ValueError:
            pass
    bad: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sent in _SENT.findall(text or ""):
        plain = _CITE.sub("", sent)
        for m in _NUM_TOKEN.finditer(plain):
            tok = m.group(0)
            load_bearing = ("." in tok or len(tok) >= 3
                            or plain[m.end():m.end() + 4].startswith(_UNITS))
            if not load_bearing:
                continue
            if tok in ev_tokens or tok in seen:
                continue
            try:
                if float(tok) in ev_floats:
                    continue
            except ValueError:
                continue
            seen.add(tok)
            bad.append((tok, sent.strip()))
    return bad


def _load_bearing(text: str, valid_ids: list[str]) -> list[tuple[str, list[str]]]:
    """抽"带引用 + 含数字"的载荷论断（客观可查子集）→ [(句, 引用的id)]。"""
    out: list[tuple[str, list[str]]] = []
    valid = set(valid_ids)
    for sent in _SENT.findall(text):
        cids = [i for i in _CITE.findall(sent) if i in valid]
        if cids and _DIGIT.search(sent):
            out.append((sent.strip(), cids))
    return out


def _ev_block(evidence: list[dict]) -> str:
    return "\n".join(
        f"[{e['id']}]<{e.get('importance', 'fair')}> {e.get('title', '')}: {e.get('text', '')}"
        for e in evidence
    )


def compose_section(
    model: Any, section: dict, ev_block: str, lang: str, target: int, style: str = ""
) -> str:
    sys = prompts.render("compose_sys", lang=lang, target=target or 800)
    if style:
        sys += f"\n\n【文风指南（须遵循）】\n{style}"
    user = (
        f"【章节规格】\n标题：{section.get('title', '')}\n"
        f"内容要求：{section.get('content', '')}\n"
        f"key_question：{section.get('key_question', '')}\n\n"
        f"【证据】(只能引用这些 id)\n{ev_block}"
    )
    return getattr(model.invoke([("system", sys), ("human", user)]), "content", "").strip()


def expand_section(
    model: Any, ev_block: str, text: str, wc: int, target: int, lang: str, style: str = ""
) -> str:
    sys = prompts.render("expand_sys", wc=wc, target=target, lang=lang)
    if style:
        sys += f"\n\n【文风指南（须遵循）】\n{style}"
    user = f"【证据】\n{ev_block}\n\n【当前正文】\n{text}"
    return getattr(model.invoke([("system", sys), ("human", user)]), "content", "").strip()


def repair_section(
    model: Any,
    ev_block: str,
    text: str,
    dangling: list[str],
    ungrounded: list[tuple[str, str]],
    lang: str,
    style: str = "",
) -> str:
    """确定性违例的定向修复（内环自纠）：只修列出的违例处，修完由调用方**复检**。

    安全性质：传感器（cite_check/number_check）是确定性的，修复结果骗不过复检——
    这是它可以自动闭环、而 LLM verifier 的结论不能自动闭环的根本区别。
    """
    sys = prompts.render("repair_sys", lang=lang)
    if style:
        sys += f"\n\n【文风指南（须遵循）】\n{style}"
    issues = []
    if ungrounded:
        issues.append("未着地数字（不在证据中）：\n" + "\n".join(
            f"- {tok}（出处句：{sent[:50]}）" for tok, sent in ungrounded
        ))
    if dangling:
        issues.append("悬空引用（不在证据集）：" + "、".join(f"[{d}]" for d in dangling))
    user = (
        f"【证据】(数字与 id 一律以此为准)\n{ev_block}\n\n"
        f"【当前正文】\n{text}\n\n【确定性核查违例】\n" + "\n".join(issues)
    )
    return getattr(model.invoke([("system", sys), ("human", user)]), "content", "").strip()


def write_section(
    section: dict,
    evidence: list[dict],
    model_spec: str,
    *,
    lang: str = "中文",
    style: str = "",  # 文风指南（plugin 供，policy 外置）；附加进 compose/expand 系统提示
    max_expand: int = MAX_EXPAND,
    max_repair: int = MAX_REPAIR,  # 确定性违例（cite/number）的定向修复轮数（内环自纠）
    verifier: Any = None,  # 有 .verify(claim, source)→(verdict,reason) 则 in-loop 保真（§8）
    on_event: Callable[[str, Any], None] | None = None,
) -> tuple[str, list[JudgmentItem], dict]:
    """写一节：compose → 字数环（measure→expand）→ **自纠环**（cite/number 违例→定向修复→复检）
    → 残留违例 + verifier 结论入判断队列。返回 (正文, 判断队列条目, 统计)。
    """
    model = get_chat_model(model_spec, temperature=0.4)
    valid_ids = [e["id"] for e in evidence]
    ev = _ev_block(evidence)
    sid = section.get("id", "?")
    target = section.get("word_count") or 0

    text = compose_section(model, section, ev, lang, target, style)
    if on_event:
        on_event("compose", {"section": sid, "wc": count_words(text)})

    for _ in range(max_expand):
        if not target:
            break
        wc = count_words(text)
        if wc >= target * (1 - TOL):
            break
        if on_event:
            on_event("expand", {"section": sid, "wc": wc, "target": target})
        text = expand_section(model, ev, text, wc, target, lang, style)

    # ── 确定性自纠环（内环闭环，§8 微观自纠）：cite/number 违例 → 定向修复 → **复检** ──
    # 传感器是确定性的（修复结果骗不过复检），所以可以自动闭环；修不好的才升级入队呈人。
    ev_texts = [e.get("text", "") for e in evidence]
    repair_rounds = 0
    cc = cite_check(text, valid_ids)
    ungrounded = number_check(text, ev_texts)
    for _ in range(max_repair):
        if not cc["dangling"] and not ungrounded:
            break
        if on_event:
            on_event("repair", {"section": sid, "dangling": cc["dangling"],
                                "ungrounded": [t for t, _ in ungrounded]})
        text = repair_section(model, ev, text, cc["dangling"], ungrounded, lang, style)
        repair_rounds += 1
        cc = cite_check(text, valid_ids)
        ungrounded = number_check(text, ev_texts)

    # ── 确定性自检 → 判断队列条目（仅修复后仍存活的违例）──
    items: list[JudgmentItem] = []
    for d in cc["dangling"]:
        items.append(JudgmentItem.make(
            "dangling_cite", sid, f"引用了证据集外的 [{d}]", "核对来源或删除该引用",
        ))
    # 强度错配：本节无直接证据、全为佐证（佐证合法，但须让人知道是佐证口径）
    direct = [e for e in evidence if e.get("importance") in ("very_high", "high")]
    if evidence and not direct:
        items.append(JudgmentItem.make(
            "unverified", sid,
            "本节无直接证据、全为佐证/类比（措辞已按佐证口径）",
            "按需补 research 取直接证据，或确认维持佐证口径",
        ))
    wc = count_words(text)
    if target and wc < target * (1 - TOL):
        items.append(JudgmentItem.make(
            "gap", sid, f"字数不足 {wc}/{target}（已扩 {max_expand} 轮）", "补研究或人工补写",
        ))

    # 数字护栏（修复后残留）：正文数字必须逐字见于本节证据（编造/改写/四舍五入/年份误标）
    for tok, sent in ungrounded[:MAX_NUM_ITEMS]:
        items.append(JudgmentItem.make(
            "ungrounded_number", sid,
            f"数字 {tok} 未见于本节证据：{sent[:48]}…",
            "核对证据原文，改回证据中的数字或删除该表述",
        ))
    if len(ungrounded) > MAX_NUM_ITEMS:
        items.append(JudgmentItem.make(
            "ungrounded_number", sid,
            f"另有 {len(ungrounded) - MAX_NUM_ITEMS} 个数字未见于证据（仅入队前几个）",
            "整体复核本节数字",
        ))

    # 保真 in-loop：核对"带引用 + 含数字"的载荷论断是否真被所引证据支持（§8）
    verified = 0
    if verifier is not None:
        ev_text = {e["id"]: e.get("text", "") for e in evidence}
        for sent, cids in _load_bearing(text, valid_ids)[:MAX_VERIFY]:
            src = "\n".join(ev_text.get(c, "") for c in cids)
            claim = _CITE.sub("", sent).strip()
            verdict, _r = verifier.verify(claim, src)
            verified += 1
            if verdict != "supported":
                items.append(JudgmentItem.make(
                    "contradiction" if verdict == "contradicted" else "unverified",
                    sid,
                    f"载荷论断未被所引[{','.join(cids)}]支持（{verdict}）：{claim[:36]}…",
                    "核对来源数字/事实或修正措辞",
                ))
            if on_event:
                on_event("verify", {"section": sid, "verdict": verdict, "claim": claim[:28]})
    stats = {"word_count": wc, "target": target, "verified": verified,
             "ungrounded_numbers": len(ungrounded), "repair_rounds": repair_rounds, **cc}
    if on_event:
        on_event("done", {"section": sid, "wc": wc, "dangling": cc["dangling"],
                          "items": len(items)})
    return text, items, stats
