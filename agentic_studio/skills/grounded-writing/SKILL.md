---
name: grounded-writing
description: 有据写作能力（/grounded-writing @<plugin> <需求>）——按领域 plugin 的大纲与数据源做 grounded 撰写：证据驱动、引用纪律、数字护栏、判断队列、诚实缺口。任何"基于数据/语料写文档"的请求都经本能力执行。
version: 0.2
kind: capability
---

# grounded-writing 能力（/-workflow）

本 skill 是**能力级 policy**：定义对话 agent 如何驾驭 grounded-write 工具集。
领域知识（写什么、数据在哪、scope 有哪些维度、文风）**全部在领域 plugin** 里——
调用形态：`/grounded-writing @<plugin名> <自然语言需求>`。

## 工具集（gw_*）

- `gw_plugins()`：列出已挂载的领域 plugin（名称+简介）。
- `gw_scope_schema(plugin)`：该 plugin 声明的 scope 维度（参数/类型/默认值/说明）+ 可选章节。
- `gw_availability(plugin)`：该 plugin 数据源**实际覆盖**（层级/对象/年份），用于诚实判断"能不能做"。
- `gw_generate(plugin, scope)`：按 scope 生成全篇（产物落工作区 /manuscript.md 等）。
- `gw_revise(plugin, section_id, instruction)`：**单节修订**（重取证据+重写该节+整篇重装配）。
- `gw_judgments()` / `gw_resolve_judgment(item_id, resolution, note)`：查看/处置判断队列。

## 执行流程

1. **拉起 plugin**：用户 `@` 了 plugin 就用它；没有则 `gw_plugins()` 选最匹配的，拿不准先问。
   读该 plugin 的 SKILL.md（在 /skills/<plugin>/SKILL.md）——**意图→scope 的解析规则在那里**。
2. **意图 → scope dict**：按 plugin 声明的维度从用户话里抽参数（`gw_scope_schema` 可查）；
   用户没说的不要传（用 plugin 默认值）。**不确定数据是否覆盖**（某地区/层级/年份）时先
   `gw_availability`，没有就如实告知 + 给可行替代，不要假装能做。
3. **执行**：`gw_generate(plugin, scope)` 一次生成；**同一需求不要重复生成**。
   局部改动（"第X节补/改…"）用 `gw_revise`，不要重跑全篇。
4. **如实汇报**：报范围、产出路径、数据缺口、判断队列条数。

## 汇报纪律（硬约束）

- **数字只有两个合法来源**：gw_generate/gw_revise 返回的正文，或你刚用 read_file 读到的
  工作区文件。**严禁自己改写、四舍五入、换算或编造任何数字**（你脑中的数字一律不可信）。
- gw_generate 返回**全文**时：只引用该正文。返回**摘要 + 读稿指引**时：汇报前必须先
  `read_file /manuscript.md`（或相关节），只引用读到的内容。
- 判断队列里的高杠杆项（contradiction / ungrounded_number）要主动向用户摆出来；
  用户裁决后用 `gw_resolve_judgment` 记录处置。
- 缺数据 = 明确说缺数据。宁可缺口，不可凑数。
