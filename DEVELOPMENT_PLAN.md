%23 当前功能开发计划

## 背景与目标
- 提升“深度研究”在本地资料利用、报告生成可控性与可观测性上的体验。
- 保持架构简洁：沿用 LangGraph 子图 + 工具绑定（Tavily/MCP），以配置驱动为主（`Configuration`）。

## 近期里程碑（1–2 周）
- 报告模板定制化（高优先级）
  - 在 `src/open_deep_research/prompts.py` 将 `final_report_generation_prompt` 拆分为模板片段：`header_template`、`section_template`、`summary_template`。
  - 在 `Configuration` 增加可选字段：`report_header`, `report_section_style`, `report_footer`（或 `report_template_path`）。
  - CLI 支持 `--report-template`（优先级：CLI > env > 默认）。
  - 验收：给定模板，报告包含指定开头、分段主题与结尾摘要。
- 本地文件能力增强（高优先级）
  - 支持多目录：`--docs-path` 接受逗号分隔路径；`mcp_config` 生成多个 server-filesystem 实例。
  - 新增“文件优先”选项：`prefer_local_files=True`，并在 `mcp_prompt` 中显式提示优先级。
  - 验收：多目录文件可被列出/读取，研究优先使用本地证据。
- 日志与可观测性（中优先级）
  - 在研究者阶段输出“工具调用日志”（工具名、参数摘要、用时）。
  - 失败重试与截断点可观测（沿用现有 token-limit 处理，打印截断比例）。

## 中期计划（3–4 周）
- 文档类型扩展
  - PDF/Markdown 优化：若启用可选解析（`pymupdf`/`markdownify`），在读到二进制/长文时走解析后再交由模型。
  - 可选：接入 PDF 专用 MCP 连接器（若存在）。
- 搜索策略与预算
  - 依据问题复杂度自适应 `max_react_tool_calls`；引入“已覆盖证据阈值”提前停止。
- 预设与配置
  - 提供常用预设（快速综述/严格综述/本地优先）到 `langgraph.json` 与 README。

## 测试与验收
- 单测：
  - 模板注入（快照对比生成的 prompt 片段）。
  - 多目录 MCP（模拟配置，校验工具清单与优先级提示）。
- 集成/手动：
  - `pytest -q`；`python cli_research.py "主题" --docs-path test_docs --report-template examples/template.md`。
  - `ruff check .`，`mypy src` 无新增告警（tests 允许忽略 pydocstyle/UP）。

## 风险与规避
- 不同模型对工具调用偏好差异大：通过 `mcp_prompt` 明确指令，并加入少量示例。
- 大文件上下文超限：保留/完善分段读取与逐段摘要策略；必要时截断并提示来源完整性。

## 交付物
- 代码：配置项、CLI 参数、模板样例（`examples/template.md`）。
- 文档：更新 `README.md` 与 `AGENTS.md` 中的“报告模板”“本地文件”章节。
