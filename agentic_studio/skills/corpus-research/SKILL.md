---
name: corpus-research
description: Research a topic against an indexed local corpus — use semantic_search (cross-lingual) to discover relevant documents, read_doc to read originals, then distill cited evidence. Use as the research sub-agent inside a corpus-grounded writing workflow (e.g. monograph / outline-grounded-write). Cite every claim to a real doc_id; never fabricate.
---

# Corpus research：导航索引 → 读原文 → 带引用的证据

把一个研究 scope 变成一份**带 [doc_id] 引用的证据笔记**。工具：`semantic_search`（跨语言语义召回，发现哪些文档相关）、`keyword_search`（精确 FTS：作者/术语/DOI）、`read_doc(doc_id[, grep])`（读原文，文内 grep 定位段落）。

## 导航硬规则（借 Corpus2Skill，严格执行）

1. **发现**用 `semantic_search`（中文查询可召回英文论文）；精确命中用 `keyword_search`。
2. **scan ≥2 个查询角度**再承诺，不要只搜一次就下结论。
3. **先 `read_doc` ≥1 篇再下论断**；只有摘要不足以支撑的具体数据/方法，必须读原文确认。
4. **每条 claim 必须追溯到你检索/读过的文档**（其摘要或全文）；**绝不捏造**候选里没有的来源、数字、引文。
5. 用 **`[doc_id]`**（文献真实 id）引用；优先**高 IF / 高被引 / 新近 / 一手**来源；**冲突要点出，不要抹平**。
6. `read_doc` 的 `grep` 用来在全文里定位具体段落/引文。

## 产出

结构化证据笔记：按子主题组织的**关键数据 / 结论 / 方法 / 对比**，每条紧跟 `[doc_id]`；不写综述散文。
不丢来源——下游写作与重编号引用都依赖这些 `[doc_id]`。
