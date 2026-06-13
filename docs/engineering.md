# agentic-studio 工程设计：对话 + grounded-write 整合

> 本文是**工程/整合规范**（怎么搭），与 `architecture.md`（为什么——控制论地基、§1–§24 设计原理）互补。
> 范围：把已验证的 grounded-write 能力内核，与已有 deepagents/Mirage 平台，在一个**对话外壳**下整合成生产形态。
> 分支：`engineering`（基于 `master` baseline `34e09ea`）。状态：设计稿，待评审后编码。

---

## 1. 总体形态

三个生产需求——**① session 管理、② 工作空间 VFS、③ 对话 + grounded-writing**——映射到三层，且平台已能承接（接口已核，见 §3）。

```
对话 Session（DeepAgentsSession = langgraph thread + checkpointer）          ── ① session 管理
│
├─ Workspace VFS（Mirage，DiskResource 挂在 "/"；workspace_root 即真实磁盘目录）── ② 工作空间
│    ├─ /manuscript.md   /evidence/{manifest.json,pool.md}   /plan.md   /judgment_queue.md
│    │        ↑ grounded-write 往 workspace_root 磁盘写，agent VFS 在 "/" 立即可见
│    ├─ /corpus       （只读挂语料源目录；亦可纯内存 CorpusService，不必挂）
│    ├─ /db/<alias>   （只读 Postgres VFS + run_sql 工具）
│    └─ /skills       （SKILL.md，SkillsMiddleware 扫描）
│
├─ 工具/能力（经 build_session(tools=…) 注入 create_deep_agent）
│    ├─ grounded-write 工具集：research / write_section / revise / assemble / grounded_write
│    │        ↑ 包已验证的 fanout+compose（确定性护栏不丢），读写 VFS 与共享证据池
│    ├─ run_sql · list_databases（DB 通道）· web 搜索/抓取
│    └─ deepagents 自带文件工具 ls/read/write/edit（细改 manuscript 用）
│
└─ policy = grounded-write SKILL.md：draft-first、何时研究/写、呈递判断队列、接受注入   ── ③ 对话+grounded-writing
```

**论点落地（harness-1）**：平台 = harness（持会话+VFS 可恢复态、调工具、加载 skill）；确定性研究/写作循环 = 能力（当工具调）；SKILL.md = policy；**workspace VFS = 共享状态**（对话轮次与 grounded-write 产出读写同一份）。外层 deepagents 对话 ReAct + 内层确定性循环 = hybrid。

---

## 2. 分层与模块边界

沿用架构不变量 3（deepagents/langgraph/mirage/docling **只在 infra/**；core 纯 pydantic）。

| 层 | 模块 | 状态 | 职责 |
|---|---|---|---|
| core | `core/{task,workflow,judgment,index,state}.py` | 有 | 纯 pydantic 契约。本期**新增** `SessionSpec`（会话装配规范，见 §6） |
| 能力内核 | `infra/research/*`、`infra/writing/compose.py` | 有（已验证） | fanout、研究子环、compose 微环。**不改逻辑**，仅被工具层调用 |
| **工具层（新）** | `infra/grounded_write_tools.py` | **新建** | `CorpusService`（会话级语料+证据池）+ `make_grounded_write_tools(svc, workspace_root)` → LangChain 工具列表 |
| 平台 | `infra/{deepagents_engine,mirage_backend,session,resources,db_tools,web}.py` | 有 | 会话引擎、VFS、DB 通道。**新增**持久 checkpointer（§6） |
| 装配 | `session/build.py`、`session/runner.py` | 有 | **扩展** `build_session` / 新增 grounded-write 会话构建器 |
| policy | `skills/grounded-write/SKILL.md` | **新建** | 对话 agent 怎么驾驭工具集（draft-first、判断队列、注入） |
| 入口 | `cli.py` | 有 | **新增** `write` 对话子命令（区别于 `research` 的 deepresearch） |

**新建文件清单**：`infra/grounded_write_tools.py`、`skills/grounded-write/SKILL.md`、`core` 里的 `SessionSpec`、（§6）持久 checkpointer 适配 + session 注册表。

---

## 3. 平台接口（已核准，编码依据）

源：`infra/deepagents_engine.py`。

- **workspace_root = 真实磁盘目录**：`DiskResource(root=workspace_root)` 挂 `/`。⇒ grounded-write 写 `workspace_root/manuscript.md` 等，agent VFS `/manuscript.md` 立即可见，**零额外管道**。
- **工具注入**：`DeepAgentsSession(tools=[...])` → `create_deep_agent(tools=…)`。grounded-write 工具直接进列表。
- **DB**：`db_registry` → 各库挂 `/db/<alias>`（只读）+ `make_db_tools` 注入 `run_sql`/`list_databases`。
- **skill**：`skills_mounts={"/skills": <host>}` 挂只读 + `create_deep_agent(skills=[...])`。
- **事件**：`prompt(msg)` 产 `turn_start / text_delta / tool_start / tool_end / agent_end / error`。
- **缺口**：`checkpointer=InMemorySaver()` 不跨进程；`snapshot()` 仅打包 workspace，线程态未持久 → §6 待补。

---

## 4. Workspace VFS 布局

一会话一目录（`workspace_root`），既是 grounded-write 产出地，也是 agent/用户共享读写面。

```
<workspace_root>/
  manuscript.md            正文（[N] 编号 + 参考文献）；grounded-write 写、agent 可细改
  plan.md                  大纲/scope 计划（澄清+planning 产出）
  evidence/
    manifest.json          node_id → {title, importance, scopes, notes}（去重证据池元信息）
    pool.md                bridge 排序的人读视图
    <section>.md           （可选）逐节导出的引用证据
  judgment_queue.md        判断队列（按杠杆排序，GATE② 给人裁决）
  .session.json            SessionSpec 快照（corpus 配置、model、created、title）——供续跑
```

全文经 node_id 回 CorpusService 取（§5），不冗存进 manifest（轻量、可审计）。

---

## 5. grounded-write 工具集（D1 = 拆开多工具）

工厂 `make_grounded_write_tools(svc: CorpusService, workspace_root: str) -> list[Tool]`，每个工具是薄包装：调已验证内核 + 读写 VFS/池 + 回简短结构化结果给对话 agent。

| 工具 | 签名（语义） | 内核调用 | 副作用 |
|---|---|---|---|
| `research` | `research(scope: str, depth: int=2, width: int=5) -> {evidence, bridges, top}` | `research_fanout` | 合并进 `svc.pool`，写 `evidence/manifest.json`+`pool.md` |
| `write_section` | `write_section(section_id, title, spec, target_words?) -> {words, dangling, items}` | `PoolSelector.select` + `compose.write_section` | 更新 `manuscript.md` 该节，追加判断项 |
| `revise` | `revise(section_id, instruction) -> {...}` | 回边：按指令重研究该 scope 或重写该节 | 更新对应节 + 证据 |
| `assemble` | `assemble() -> {path}` | `grounded_write.assemble` | `[node_id]→[N]` 重编号 + 参考文献，定稿 `manuscript.md` |
| `grounded_write` | `grounded_write(outline: list[section]) -> {...}` | `generate_v0`（研究→写→assemble 全量） | 一次产出 v0（便捷组合） |

**判断队列**：工具把产出的 `JudgmentItem` 累加写 `judgment_queue.md`（按 `leverage` 排序）；对话 agent 据 SKILL.md 把高杠杆项摆给用户（GATE②）。

**细粒度修改**：normal 文件工具（read/edit `manuscript.md`）覆盖"agent+大纲就能改"的轻量场景——不必每次走 research。

---

## 6. CorpusService 与会话生命周期

### 6.1 CorpusService（会话级，§D2）
```
CorpusService:
  searcher: CorpusSearcher | MdNodeSearcher   # bge-m3 矩阵，建一次（.cache 命中秒级）
  pool: dict[node_id, dict]                    # 跨工具调用累积的去重证据池（fanout 合并入）
  selector: PoolSelector                       # 池增长后重建，供 write_section 选材
  merge(new_pool)                              # research 工具调用后并入（merge_pools 语义）
```
开会话时按 `SessionSpec.corpus` 建一次，注入所有 grounded-write 工具的闭包；**绝不每次工具调用重建矩阵**。

### 6.2 SessionSpec（core，新增，纯 pydantic）
```
SessionSpec:
  session_id: str
  workspace_root: str
  corpus: CorpusRef        # cards/abstracts 路径 或 md 书目录 + tag + embed_cache
  model: str
  db_specs: list[(alias, dsn)] = []
  title: str = ""
  created: str             # 由调用方传时间戳（脚本内不可 Date.now，外部注入）
```
开会话时落 `<workspace_root>/.session.json`。

### 6.3 持久化与续跑（§D3，缺口修复）
- **线程态**：`InMemorySaver` → langgraph 持久 checkpointer（首选 `SqliteSaver`，库放 `<workspace_root>/.thread.sqlite`）。在 `deepagents_engine` 加 `checkpointer` 注入点。
- **workspace**：已在磁盘。
- **续跑** = 读 `.session.json` → 重开 workspace 目录 + 同 `thread_id` 的 checkpointer + 重建 CorpusService（矩阵从 `.cache` 秒回、池从 `evidence/manifest.json` + node_id 回取重建）。
- **session 注册表**：一个轻量 `sessions.json`（或 sqlite）：`session_id → {workspace_root, title, created}`，供 `list` / `resume`。

---

## 7. 对话 policy = `grounded-write` SKILL.md

把"对话怎么驾驭工具集"externalize 成 skill（= 提示词/DAG 分离落到对话层），而非硬编码进引擎。要点：
- **draft-first**：先按信息地平线产 v0，不追求一次完备（架构边界一）。
- **节奏**：澄清大纲 → `research` 铺证据池 → 逐节 `write_section` → `assemble` → 把 `judgment_queue.md` 高杠杆项摆给用户。
- **接注入**：用户给修改意图 → `revise(section, 指令)` 回边，不重跑全篇。
- **何时呈人（GATE②）**：矛盾/方向/未核实载荷论断入队呈递；微观可自纠的不打扰（架构 §8 判断队列）。

内层循环的提示词（`loop._system`、`fanout._PLAN_SYS`、`compose._COMPOSE_SYS`、`verify.VERIFY_SYS`）后续收进 `prompts/` registry（独立工序，不阻塞本整合）。

---

## 8. 一个对话轮的数据流

```
用户:"用 /corpus 写一份关于 X 的报告"
  → 对话 agent（依 SKILL.md）：澄清/定大纲 → 写 plan.md
  → 调 research("X 的子范围…")  → fanout 15~18 并行 → 合并入 svc.pool → 写 evidence/
  → 逐节 write_section(...)      → PoolSelector 选材 → compose 微环 → 写 manuscript.md 各节 + 判断项
  → assemble()                   → [N] 重编号 + 参考文献 → 定稿 manuscript.md
  → agent 回复摘要 + 摆出 judgment_queue.md 高杠杆项
用户:"第3节论点太弱，补 Y"
  → revise("3", "补 Y")          → 回边重研究/重写该节 → 更新 manuscript + evidence
（全程 workspace VFS 是单一真相源；会话线程态由 checkpointer 持久，可续跑）
```

---

## 9. 关键决策记录（本次已定）

- **D1 拆开多工具**（research/write_section/revise/assemble + grounded_write 组合）——对话驱动、注入/回边自然。
- **D2 CorpusService 会话级**——矩阵建一次、跨调用复用、池累积。
- **D3 持久 checkpointer（SqliteSaver）+ session 注册表**——支持续跑/列举。
- **D4 工具在 `infra/grounded_write_tools.py`**——deepagents/mirage 仍只在 infra，核心保持纯。
- **D5 对话 policy = SKILL.md**——提示词/DAG 分离落到对话层。
- **LangGraph 立场**（2026-06-10）：不整体采用；deepagents 已在 agent 节点层 = langgraph。仅当宏观生命周期出现具体失败（注入循环续不上、人环 gate 要持久暂停）时，经既有 `ControlMode`/`graph_factory` 缝把那一段毕业成显式图。微循环与动态深度 fanout 维持手搓。

---

## 10. 里程碑 / 构建次序

1. **M1 工具层**：`infra/grounded_write_tools.py`（`CorpusService` + `make_grounded_write_tools`）。单测：脱离会话直接调工具，验证写 VFS + 池累积 + 判断项。
2. **M2 对话纵切**：`SessionSpec` + grounded-write 会话构建器 + `cli write` 子命令 + 最小 `grounded-write` SKILL.md。端到端：对话里触发研究→写→assemble→判断队列，真实语料跑通。
3. **M3 注入回边**：`revise` 工具 + SKILL.md 注入节奏。验证"第N节补X"回边更新。
4. **M4 持久化**：SqliteSaver checkpointer + session 注册表 + `cli list/resume`。验证跨进程续跑。
5. **（增量）** 内层 prompts registry；GATE② 显式 interrupt（若 M3 暴露需求）；全文/数值/公式通路（已 defer）。

---

## 11. 开放项

- **持久 checkpointer**：langgraph `SqliteSaver` 与 deepagents `create_deep_agent` 的兼容性需实测（M4 第一件事）。
- **GATE② 人环暂停**：v0 用"agent 摆队列、用户下轮回话"的软形态；若需硬暂停/恢复（长任务跨会话），再上 langgraph `interrupt()`。
- **全文/数值/公式 grounding**：已 defer（首期散文/报告类）。见 `architecture.md` §13.1/§14 与记忆 `fulltext-formula-path-decision`。
- **多会话共享语料**：同一 corpus 的 CorpusService 是否跨会话单例（省内存/重建）——M4 后按需。

---

## 12. 能力 vs plugin + 安全 DB 取数（已落地并验证，2026-06-10）

### 12.1 分层：grounded-write 是**能力**，领域是**plugin（skill-set）**
- **能力（通用引擎）**：研究/写作/验证/判断队列 + 驱动器，领域无关。
- **plugin（渐进式 skill-set）**：把某领域的全部特化打包——**从哪取数、数据格式、大纲模板、文风**。
  落在 `skills/<domain>/`：`SKILL.md`（入口，渐进式指针）+ `outline.yaml`（大纲+每节指标绑定）+ `style.md`（文风）。
  能力消费 plugin → 换 plugin 即换领域。首个 plugin：`skills/cropland-spatiotemporal/`（耕地时空演变简报）。
- 驱动器 `workflows/grounded_brief.py::run_brief(plugin_dir, store, model, workspace)`：领域无关，读 plugin
  → 逐叶子节按 `evidence` 规格取数 → `write_section(style=…)` 撰写 → 装配引用 + 数据来源脚注。

### 12.2 安全 DB 访问（**agent 不写 SQL、不直连库**）
`infra/data/metric_store.py::MetricStore`——结构化数据的安全中介层：
- **只读**：连接即 `SET default_transaction_read_only=on` + `statement_timeout`（服务端拒写/拒慢）。
- **白名单**：indicator_code 必在库内 `*_meta`、region 必在 region 维表，否则拒绝；表名写死（两个宽表视图）、值走参数占位符、无字符串拼接。
- **具名查询**：只暴露 `series(code,region)`/`by_region(code,year)` 等原语，**不暴露 run_sql**。
- **产物是证据**：`as_evidence()`→`{id,title,text,importance=very_high,source}`，与语料证据同构，喂 write_section；
  agent 全程只见证据行，永不见 SQL。这是架构「DB 双通道」面向 grounded-write 的**安全版**（区别于会给 agent SQL 的 Mirage `run_sql` 工具）。

### 12.3 已验证（端到端，`scripts/experiments/cropland_brief_test.py`）
四川省耕地时空演变简报，13 节按大纲、24 条 DB 证据、deepseek 撰写：
- ✅ 数字全部 grounded 自 DB（FARMLAND_AREA 2019=7840.75 等核对一致）、引用 `[N]` + 数据来源脚注完整。
- ✅ 三道安全护栏实测拦截（未知指标 / 未知地区 / 写操作）。
- ✅ 人均耕地（库内无人口指标）**如实标注数据缺口、不杜撰** → 判断队列 gap。
- ✅ **保真层抓到模型自算的派生数错误**（破碎度年度变化、坡度累计量）→ 判断队列（按杠杆排序：矛盾 L5 > 未核实 L4 > 缺口 L3）。
- **发现**：简报需大量派生量（变化量/占比/累计），模型会自行计算并可能算错；当前由 in-loop verify 逐条核对升队列。
  后续可加**确定性派生层**（变化量/占比由 MetricStore 算好作为证据，减少模型算术），降低这类 contradiction。

### 12.4 接入说明
- DSN 经 env `CROPLAND_DSN` 注入（不硬编码密码）。`MetricStore` 依赖 `psycopg`（运行时 `--with "psycopg[binary]"`，后续进 `pg` extra）。

### 12.5 scope 参数化 + 对话 agent（M2 langgraph 竖切，已验证 2026-06-10）
**scope 参数化**（`grounded_brief.BriefScope`）：`{regions:[多地区可对比], years:(lo,hi), breakdown, sections:[顶层章节]}`。
- `MetricStore.series(code,region,years=)` 支持年份过滤；`available_regions()`/`has_data(region)` 暴露数据存在性。
- 实测：库内**仅省级(1)+市州级(21)有数据，区县无**；成都市 2020–2023 / 成都+绵阳对比 取数正确。

**对话 agent**（`workflows/cropland_agent.py`，langgraph `create_react_agent`，按用户定的"session 内对话层用 langgraph"）：
- **policy = SKILL.md**（plugin 的 SKILL.md 挂为系统提示）+ 职责指引（意图→scope→执行→诚实）。
- **工具**：`data_availability()`（诚实数据存在性）+ `generate_brief(regions,year_from,year_to,breakdown,sections)`（按 scope 拉起 `run_brief`）。
- 会话记忆 `MemorySaver`（thread；跨进程持久 → SqliteSaver，M4）。

**已验证（`scripts/experiments/cropland_agent_test.py`，两轮对话）**：
- 轮1「成都市2020到2023耕地数量和结构变化」→ agent 先 `data_availability` → 正确解析 `generate_brief(['成都市'],2020,2023,breakdown=False,['1','3'])` → 4 节/13 证据，如实报人均缺口。
- 轮2「巴中市恩阳区能做吗」→ 识别区县 → **如实告知"数据库只到市州级、无区县数据"** + 给替代（巴中市）。
- ⇒ **意图→拉起 skill→按 scope 执行→无数据诚实提示** 全链路通（goal 三部分达成）。
- 已知小瑕：弱模型偶发多余工具调用（已在指引加约束收敛）；单地区时"市州下钻"节在 breakdown=off 下空→标 gap（合理，后续可对单地区跳过下钻节）。

### 12.6 统一 workspace（Mirage，已落地并验证 2026-06-10）
两种对话外壳共用同一组工具（`cropland_agent._make_brief_tools`）：
- `build_brief_agent`：裸 langgraph（无 VFS，快速验证）。
- **`build_brief_session`：DeepAgentsSession（Mirage 统一 workspace）** —— 这是「统一 workspace」的落点。
  - 一个 Mirage VFS workspace 同时挂：`/`（产物，DiskResource(workspace_root)）、`/skills`（技能源目录）、`/corpus`（参考文档+md/txt，只读）。
  - 产物 `/manuscript.md`+`/evidence/`+`/judgment_queue.md` = **workspace-as-state**；agent 经 VFS 文件工具（ls/read_file）读 skill、读参考文档、读产物再汇报（**read-from-artifact**，结构性防"谈没读过的文件"那类失真）。
  - **DB 仍经 MetricStore 安全取数**（不挂 run_sql）——三类源（DB / 参考文档 / md-txt）在同一 workspace 各司其职。

**实测（`scripts/experiments/cropland_session_test.py`）**：agent `ls /` → `/corpus /skills`；`ls /skills` → 3 个技能（含 cropland-spatiotemporal）；`ls /corpus` → reference.md + 耕地简报 md；read SKILL/outline/style；生成简报落 VFS `/manuscript.md`（成都真实数 486.47→499.60，无虚构）+ `/evidence/`+`/judgment_queue.md`。⇒ **统一 workspace（参考文档+DB+md/txt + 产物状态面）成立**。

### 12.7 待办（已完成 2026-06-10）
- ✅ **持久 checkpointer**：`DeepAgentsSession` 加 `checkpointer` 参数（默认 InMemorySaver）；`build_brief_session`
  用 `SqliteSaver`（`langgraph-checkpoint-sqlite`）落 `workspace/.thread.sqlite`。`infra/session_registry.py`
  写/列 `.session.json`。**实测**：session 关闭后用同 session_id+workspace 重开，记得上轮事实（"张三"）→ 跨重开恢复。
- ✅ **确定性派生层**：`MetricStore._summarize` 把期初/期末/累计变化/变化率%/年均算好写进证据，模型直接引用。
  **实测**：成都累计+13.13万亩/+2.70%/年均+4.38；破碎度年均**+0.01**（修正模型曾错的+0.02）。
- ✅ **skill 动态拉起**：`_make_brief_tools` 加 `list_skills()`+`launch_skill(name)`——人把 skill 放 `/skills` 即挂载，
  agent 按需拉起其 SKILL.md。**实测**：列出 3 个挂载 skill；launch 返回 SKILL.md / 诚实拒绝不存在。

### 12.8 残留小项（已全部在 §13 清掉，2026-06-10）
- ~~模型偶把区间首年误标"三调2019"~~ → §13 确定性数字护栏（number_check）100% 覆盖正文数字。
- ~~单地区 scope 下市州下钻节空→gap~~ → outline 节支持 `optional: true`，无证据时整节跳过。
- ~~SqliteSaver 连接 close 不关~~ → `DeepAgentsSession.close()` 关 checkpointer.conn + 调用方 closers。

---

## 13. 最终三层形态：runtime / 能力（/-workflow）/ plugin（2026-06-10 重构落地）

> 本节是对 §12 形态的一次**架构收口**（用户定调：runtime/harness 是更高抽象；grounded-writing
> 是一个类似 `/` 命令的 workflow；意图理解的维度（年份/地区）不得写进能力层——不是所有任务都有）。

### 13.1 三层（调用形态：`/<能力> @<plugin> <自然语言需求>`）
- **runtime（`workflows/chat_runtime.py`）**：通用对话 harness。**session 不绑定任何 plugin/领域**；
  系统提示是**薄 runtime 约定**（`prompts/runtime_sys.md`：VFS 约定、`/x @y` 消息约定、诚实底线）。
  日常对话 = 不拉起能力时的默认态。能力工具按列表注入：`build_chat_session(capabilities=[...])`，
  `CAPABILITY_TOOLSETS` 注册表（新 workflow 如 GIS 分析 = 再注册一个工具工厂 + 能力 SKILL.md）。
- **能力（grounded-writing）**：`skills/grounded-writing/SKILL.md`（能力 policy）+ `gw_*` 工具集
  （plugins/scope_schema/availability/generate/revise/judgments/resolve_judgment），全部以
  **plugin 名为参数**——挂进 /skills 即可被任何会话消费。`core/workflow.py` 注册 manifest
  `grounded-write`（与 deepresearch 平级）。
- **plugin（领域）**：`skills/<domain>/` = SKILL.md（领域知识+意图→scope 维度解释）+ outline.yaml
  （大纲+证据绑定+**scope schema**）+ style.md + **datasource.yaml**（数据源声明）。

### 13.2 scope 泛化（年份/地区不进能力层）
- plugin 在 `outline.yaml: scope.params` 声明自己的维度（type/default/check/desc + label 模板）；
  能力层只做 **schema 校验**（`grounded_brief.validate_scope`：未知键拒绝、类型归一、check 校验器）
  与 **绑定**（证据规格里 `$param` 替换、`when:` 门控、provider `fanout_keys` 列表展开——多地区
  对比即 region 列表展开）。`sections` 是唯一能力级保留键（大纲是能力概念）。
- 意图理解（自然语言→scope dict）发生在**对话层**、按 plugin SKILL.md；实测 deepseek 把章节 id
  写错（"1 耕地数量变化"）被校验拒绝并**自纠**为 ["1","3"]。

### 13.3 数据源 plugin 化（EvidenceProvider）
- `datasource.yaml`（kind/dsn_env/views/meta_tables/region_table/default_region/source_name）→
  `infra/data/providers.py::build_provider_set` 组装 `ProviderSet{providers, validators,
  availability, close}`；`MetricStore` 全配置化（`MetricSourceConfig`，标识符白名单正则设防），
  **不再含任何领域字面量**。`gw_availability` 动态生成（county 无数据是查出来的，不再硬编码）。
- 新数据源 = 实现 provider + 在 `_BUILDERS` 注册；plugin 侧只写 yaml。

### 13.4 确定性数字护栏（P0，比 LLM verifier 更强的数值子集）
- `compose.number_check`：成稿后抽取正文全部载荷数字（≥3 位或带小数点；剥引用标记；数值相等容差），
  逐个核对**必须出现在本节证据文本中**，否则 `ungrounded_number`（L5）入队。零 LLM 成本、100% 覆盖。
- **实测抓到真实编造**："突破499万亩"（四舍五入）、"486.48"（凭空小数）→ 入队呈人。
  一并闭掉旧残留："三调2019" 年份误标、expand 重写污染、verifier 每节 5 条抽查上限外的漏网。

### 13.5 修订回边 + 判断队列消费（产用闭环）
- `run_brief` 落 `brief_state.json`（节稿状态）+ `evidence/manifest.json`（**证据全文快照**，审计链）
  + `judgment_queue.json`（结构化，status 流转）；叶子节 ThreadPool 并行（装配顺序确定）。
- `revise_section(plugin, ws, section_id, instruction)`：单节重取证据+重写+整篇确定性重装配
  （实测：按指令修正破碎度表述，未着地数字 0）。`load_queue`/`set_judgment_status` +
  `gw_judgments`/`gw_resolve_judgment` = GATE② 消费半边（resolved/dismissed 流转）。

### 13.6 安全收口（execute 旁路）
- 实证：deepagents 0.6.7 对 SandboxBackendProtocol（Mirage LangchainWorkspace）注册 `execute` 工具，
  Mirage 虚拟 shell 内建**真子进程 python 执行**——可读 env/任意磁盘（含 .env 的 DSN/密钥），绕过
  MetricStore。修法：`StudioBackend(allow_exec=False)` 在 backend 层挡掉（`DeepAgentsSession` 透传），
  写作会话一律禁用。**实测**：会话内调 execute 返回拒绝文案，DSN 未泄露。
- 其余 P0：证据/判断 id 改 crc32 稳定哈希（str hash() 每进程随机化 + 万分之一截断撞 id 会让引用
  指错地区——已修）；`close()` 关 SqliteSaver 连接与 closers。

### 13.7 提示词/框架解耦
- `agentic_studio/prompts/` registry（string.Template，$var，JSON 花括号安全）：compose/expand/
  verify/scope_note/research_plan/research_loop/runtime_sys 全部外置为 .md。改提示 = 改文件不动代码。

### 13.8 接入与回归网
- CLI：`write`（runtime 对话，--session 续跑）、`brief`（一次性驱动）、`sessions`（列举）。
- `tests/`（pytest，26 例全过）：number_check（编造/四舍五入/枚举噪声/越界年份）、装配重编号、
  稳定 id、_summarize、scope 校验/绑定/门控/展开/标签、plugin lint、配置标识符防线。
- 端到端实测（真库+deepseek）：驱动器（成都 2020-2023 章节4：7 证据、未着地数字 0、verifier 抓到
  1 条矛盾入队）→ revise 回边 → 裸 runtime 两轮（自纠+诚实区县拒绝）→ 统一 workspace 会话
  （/-约定、read-from-artifact 汇报、产物+.thread.sqlite 落盘）→ execute 拒绝。

### 13.9 已知边界（诚实记录）
- 每个新能力的**安全中介要逐能力建**（MetricStore 模式可照搬，但无法自动生成）。
- 长任务无后台 job 形态（会话同步流式；Mirage jobs 可后接）。
- 判断队列条目较多时呈报体验可再做分组/聚合（§13.10 修复环已大幅降噪：19→1-2 项）；
  deepseek 对 dict 参数偶有格式偏差，靠校验错误信息自纠（已实测可收敛）。

### 13.10 第二遍修复（深度评审后全量整改，2026-06-10）

对 §13 形态做了一轮找茬式评审（A 真 bug / B 安全 / C 边角 / D 架构），除 D16 外全部修复并验证：

**开闭环补全（D15，控制论收口）**：`write_section` 增**确定性自纠环**——compose/expand 后跑
cite_check + number_check，违例则一次定向修复（`prompts/repair_sys.md`）→ **复检**，修不好才
升级入队。安全性质：传感器确定性 ⇒ 修复骗不过复检（LLM verifier 的结论仍保持开环→呈人，防
Goodhart）。层级：内环=确定性传感器+有界修复+复检（自动）；中环=LLM 传感器（只检测）；外环=人
（队列→revise）。**实测**：队列从 19 项降到 1-2 项（剩 verifier 矛盾与字数 gap，全是该人看的）。

**A 真 bug**：① closers 改持引用（原构造时拷贝，运行中途注册的 MetricStore 关闭器全丢）；
② gw_generate 幂等改读 brief_state.json（plugin+归一化 scope 相等才命中；原内存签名跨 plugin
会把 B 的稿件当 A 的返回，且跨进程无效）；③ generate/revise 加 per-workspace 锁（防同轮并发
工具调用交错写产物）；④ 单节故障降级：`_gather` 广义兜底（数据源异常→该节缺口）、`work()`
整体兜底（LLM 故障→error 节+入队，整篇照常）、MetricStore 断线自动重连（互斥单飞）；
⑤ revise 校验 plugin↔state 一致 + scope 重建复用 validate_scope（删启发式）；⑥ revise 后该节
旧 open 判断项自动 superseded（指向已替换文本的条目失效，同 id 复现会盖回 open）。

**B 安全/一致性**：/skills、/corpus 按挂载点强制只读（Mirage `(resource, MountMode.READ)`）——
原实现 docstring 写只读、实际可写，等于把 SKILL.md（policy）暴露成自我修改注入面。
**实测**：会话内 edit/write /skills/... 不落盘。psycopg3 线程模型（threadsafety=2、内部锁、
并行节 DB 串行化）写进 docstring。

**C 边角**：空列表 scope 参数回退默认（防 [] 静默全缺口稿）；plugin 元数据与数据源懒加载分离
（查 schema/列 plugin 不再要求 DSN 可连）；number_check **单位感知**（短整数带量纲单位照核，
"增加21万亩"不再漏）；style.md 时间锚点改条件式（证据无 2019 不再诱导"三调"误标）；覆盖已有
稿件时提示原范围；`_gather` 按证据 id 去重（years 夹成同年的重复规格）。

**D17 溯源（轻量，按用户要求不复杂化）**：brief_state.run = {model, prompts_fingerprint
（prompts/*.md 内容 crc32）, started, finished, parallel}；revise 盖 revised 时间戳。

**D18 分层归位**：会话装配移回 `session/build.py::build_chat_session`（SqliteSaver 构造下沉
`infra/deepagents_engine.make_sqlite_checkpointer`）；workflows/chat_runtime 只留工具工厂
（`build_capability_tools`）与裸调试外壳。

**D20 回包分模式**：VFS 外壳 full_body=False——generate 返回摘要+“先 read_file 再汇报”硬指引
（不整篇回灌上下文）；裸外壳保持全文回包（无文件工具，那是它唯一的 grounding 通道）。
**实测**：会话 agent 先读 /manuscript.md 再汇报，数字全部对上真库。

**D19 回归网**：tests/test_run_brief.py 编排级测试（假 provider+假模型，零网络）：端到端产物
/溯源/跳过/缺口、数据源故障降级、LLM 故障降级、修复环修好不入队、修不好升级入队、revise
supersede、错 plugin 拒绝。共 34 例全过。

**D16（corpus provider）不在本批**：与 fulltext/公式路线（已 defer）绑定，EvidenceProvider
插槽已就位，单独立项。

---

## 14. 确定性图表（figures/tables，2026-06-13）

简报图表走与数字护栏同一哲学：**图表不经 LLM**——由数据源 renderer 从 MetricStore 查询结果
直接渲染（表=markdown 直出；图=**Plotly figure JSON** 落到 workspace `figures/*.plotly.json`，
前端 plotly.js 交互式渲染、PNG 客户端导出，服务端不依赖任何渲染后端），数字**构造即有据**；
模型只被告知"本节将附哪些图表"，行文用「下图/下表」衔接，不画图、不填表。
（2026-06-13 由 matplotlib 改为 Plotly：对话与简报统一交互式图表，导出用 PNG。）

- **声明在 plugin**：outline.yaml 每节 `figures:` / `tables:`，kind 由 datasource 的 renderer
  提供（metric_postgres：`line_chart` / `bar_chart` / `series_table` / `by_region_table`），
  同样吃 `$param` 绑定与 `when:` 门控；列表值（多地区）由 renderer 决定合并画（折线多线对比）
  还是分别画（条形一地区一图）——不走证据 fanout。
- **能力层**（`infra/writing/artifacts.py` + grounded_brief `_render_artifacts`）：领域无关的
  md_table/绘图原语 + 编号占位 `[[图]]`/`[[表]]`（CJK token，避开 `[id]` 引用正则，不会被装配
  重编号误吃），`number_artifacts` 在装配时按全文顺序替换为 图1/表1…；state 保留占位 →
  revise 重装配后编号仍全局一致。renderer 构造纯 dict 的 Plotly figure（data+layout，无全局态，
  节级并行安全），落 `*.plotly.json`；markdown 仍用 `![标题](figures/x.plotly.json)` 引用，
  前端按扩展名识别为交互图；中文字体走浏览器（plotly.js 端渲染，无需服务端字体）。
- **lint**：渲染 kind 未注册、code 不在白名单、声明了图但缺 plotly（viz extra）→ 载入期
  fail-fast；运行期单个图表失败只入 format 队列项、不毁节。
- **依赖**：extra `viz = [plotly]`。对话侧 chat 能力的 `render_chart` 沙箱同样产 Plotly figure JSON
  （隔离子进程跑用户 plotly 代码，环境白名单剥离密钥/DSN）——对话与简报图表完全同栈。
- **实测**（四川省第 1 章，真库）：图1-3/表1-3 全局编号正确穿插，中文无豆腐块；by_region 分区
  表含确定性"变化量"列。护栏顺带抓到模型自算市州净增减（7.31/10.96/2.14/0.69，证据只有两年
  原值）→ L5 入队呈人——**已知噪声源**：分区类证据暂无确定性派生量（series 有 `_summarize`，
  region_evidence 没有跨年 delta），后续可加"分区变化"派生证据 kind 来消化这类自算冲动。
