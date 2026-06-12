# deepresearch（engineering 分支）— agentic-studio 实现

> 本分支的实现整体来自 agentic-studio 的 engineering 分支（三层 runtime/能力/plugin）。
> 旧的 open_deep_research（LangGraph deep researcher）实现在 **main 分支**。
> 设计文档：`docs/engineering.md`（工程规范，怎么搭）、`docs/architecture.md`（设计原理）。

## 架构（三层）

- **runtime**（`agentic_studio/workflows/chat_runtime.py` + `session/build.py::build_chat_session`）：
  通用对话 harness。会话 = DeepAgentsSession（deepagents + Mirage VFS + langgraph thread），
  不绑定任何领域；能力工具按 `capabilities=[...]` 注入；`system_prompt=` 可被产品层覆盖（场景化提示）。
- **能力**（grounded-writing）：`gw_*` 工具集（plugins/scope_schema/availability/generate/revise/
  judgments/resolve_judgment），全部以 plugin 名为参数。确定性护栏：number_check / cite_check /
  修复环 / 判断队列；图表确定性渲染（不经 LLM）。
- **plugin（领域）**：`agentic_studio/skills/<domain>/` = SKILL.md + outline.yaml（大纲+scope schema+
  图表声明）+ style.md + datasource.yaml（数据源声明）。本项目的 plugin：
  **cropland-spatiotemporal（耕地时空演变简报）**，对接 SmartCroplandAnalytics backend 的
  PostgreSQL（视图 `vw_region_time_indicator_raw/derived`，由 backend 迁移 003 建）。

## Session 管理

- 一会话一 workspace 目录；线程态 SqliteSaver 落 `<workspace>/.thread.sqlite`；
  元信息 `.session.json`（`infra/session_registry.py`）。
- **续跑** = 同 session_id + 同 workspace_root 重建会话（跨进程恢复对话记忆）。
- 产物（= 对话的"暂存区"）：`/manuscript.md`、`/evidence/`、`/judgment_queue.{md,json}`、
  `/figures/*.png`、`brief_state.json`。

## 常用命令

```bash
uv sync --extra agent --extra vfs --extra pg --extra viz --extra dev   # 安装（不要 embed，torch 很重）
uv run pytest -q                                                       # 零网络回归（40 例）
uv run agentic-studio write "写一份成都市2020-2023耕地变化简报" -s demo  # runtime 对话（续跑加 -s 同id）
uv run agentic-studio brief cropland-spatiotemporal --scope '{"regions":["成都市"]}'  # 一次性驱动
uv run agentic-studio sessions                                         # 列举持久会话
uv run ruff check .                                                    # lint
```

## 环境（.env，不进库）

- `DEEPSEEK_API_KEY`（默认模型 deepseek:deepseek-chat；reasoner 工具调用弱，勿跑 agentic loop）
- `CROPLAND_DSN`：`postgresql://...@localhost:5432/smart_cropland_analytics`（与 backend 同库；
  MetricStore 只读+白名单+参数化，agent 永不见 SQL/DSN）
- `TAVILY_API_KEY`（可选，web 搜索）；`AS_WORKSPACE_ROOT`（会话工作区根，缺省 `./.workspaces`）

## 约束（改代码前必读）

- 分层不变量：deepagents/langgraph/mirage/docling **只准在 `infra/` import**；core 纯 pydantic。
- 意图理解的领域维度（年份/地区等）写在 plugin 的 SKILL.md/outline.yaml，**不得进能力层**。
- 提示词全部在 `agentic_studio/prompts/*.md`（string.Template）；改提示 = 改文件不动代码。
- 写作会话 `allow_exec=False`（防子进程读 env/DSN 绕过 MetricStore），/skills /corpus 强制只读。
- 新数据源 = 实现 provider + 注册 `infra/data/providers.py::_BUILDERS`；plugin 侧只写 yaml。
