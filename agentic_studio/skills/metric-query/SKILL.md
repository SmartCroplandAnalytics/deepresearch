---
name: metric-query
description: 指标库查询能力——正常对话里直接查数据库某指标在某地区某年的真值（经 MetricStore 安全中介，只读+白名单+参数化，与简报证据同源同值）。用户问"数据库里 XX 指标的值是多少"时用本能力。
version: 0.1
kind: capability
---

# metric-query 能力（正常对话查库真值）

本 skill 让对话 agent 在**普通对话**里就能像简报一样从指标库取数——**不是** grounded-writing
的一部分，不生成文档，只回答"数据库里这个值是多少"。取数走与简报**完全相同**的安全中介
（MetricStore：只读连接 + 指标/地区白名单 + 参数化查询，agent 不写 SQL、不见 DSN），
所以对话里查到的值与简报正文引用的证据**逐字一致**。

## 工具集（db_*，均以领域 plugin 名为参数）

- `db_indicators(plugin)`：列出该库可查的**全部指标**（code — 名称（单位）[原始/派生]）。
  不确定指标 code 时先用它（例：找到 `SLOPE_0_2_AREA` = 2°以下坡度耕地面积）。
- `db_series(plugin, code, region="", years="")`：查某指标在某地区的**历年真值**
  （含确定性派生量：累计变化/变化率/年均）。region 缺省=该领域默认地区；years 形如
  `"2020-2023"`。**这是"数据库里这个值是多少"的权威答案。**
- `db_compare(plugin, code, year, parent="")`：某指标某年在 parent 下各子地区的值（降序）。
- `db_coverage(plugin)`：该库实际覆盖的地区层级与年份（判断"有没有这个粒度/年份"）。

## 执行纪律（硬约束）

- 用户问某指标/某地区/某年的数值 → 直接调 `db_series`（或 `db_compare`），把返回文本里的
  数字**逐字**报给用户，**严禁改写、四舍五入、换算或编造**。
- 不知道指标 code 时先 `db_indicators` 查；不确定地区/年份是否有数据时先 `db_coverage`。
- 查不到（白名单外的指标、维表外的地区、未覆盖的年份）就**如实说没有**，并给可行替代，不要凑数。
