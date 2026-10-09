---
name: cropland-spatiotemporal
description: 「耕地时空演变智能分析报告」领域 plugin（配合 /grounded-writing）——四川省耕地数量、结构、流量、质量与破碎度变化，数据来自耕地指标数据库。用户要写/更新耕地时空演变智能分析报告时使用。
version: 0.3
kind: grounded-write-plugin
---

# 耕地时空演变智能分析报告 plugin

本 skill 是 **grounded-writing 能力的领域 plugin**：只装领域知识，流程纪律见能力 SKILL
（`/skills/grounded-writing/SKILL.md`）。调用：`/grounded-writing @cropland-spatiotemporal <需求>`。

## 渐进式资源
- 大纲 + 指标绑定 + **scope schema** + **图表声明**：[`outline.yaml`](./outline.yaml)
  （每节 `figures:`/`tables:` 声明折线图/条形图/数据表——**确定性渲染、数据直出、不经模型**，
  PNG 落工作区 `figures/`，编号装配时全文统一）
- 文风（政务数据智能分析报告体）：[`style.md`](./style.md)
- 数据源声明（安全中介，agent 不碰 SQL）：[`datasource.yaml`](./datasource.yaml)

## 意图 → scope（本领域的维度）
从用户话里抽这些参数（即 outline.yaml 的 scope schema）：
- `regions`（list）：省/市州，可多个对比，如 `["成都市","绵阳市"]`。缺省=四川省。
- `years`（[起,止]）：如"2020到2023年"→ `[2020,2023]`。缺省=全部年份。
- `breakdown`（bool）：要不要"分市州下钻"。缺省=要。
- `sections`（list，保留键）：只写哪些章——1 耕地数量变化、2 耕地结构变化、
  3 耕地流量变化、4 耕地质量变化、5 耕地破碎度变化。缺省=全部。

例：「写2020-2023年成都市耕地数量和结构变化」→
`gw_generate("cropland-spatiotemporal", {"regions":["成都市"],"years":[2020,2023],"breakdown":false,"sections":["1","2"]})`

## 领域注意事项
- 数据粒度：指标库目前**只到市（州）级**（用 `gw_availability` 核实，不要凭记忆断言）；
  用户要区县时如实说明，并提议改用所属市州。
- 单个市州做 scope 时，"分区下钻"无下级数据，分区节会自动跳过——不必解释为缺口。
- 指标体系：32 个原始 + 21 个派生指标（FARMLAND_AREA、二级类、SLOPE_*、流入流出、
  破碎度、稳定耕地等），证据已含确定性派生量（累计/变化率/年均），直接引用、不要自算。
- 人均耕地需常住人口数据，库内暂无 → 该节固定为数据缺口，如实说明即可。
