# Deep Research Agent

基于 LangGraph 的深度研究智能体 - 支持多模型、本地文档和可配置搜索的自动化研究系统。

[![Python](https://img.shields.io/badge/Python-3.13+-blue?style=for-the-badge&logo=python)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-latest-green?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

## 🚀 主要特性

- **多模型支持**: Qwen (Flash/Plus) + DeepSeek (Chat/Reasoner) 全系列模型
- **本地文档研究**: 通过 MCP 协议访问本地文件系统进行离线研究
- **灵活搜索配置**: 支持 Tavily 搜索或完全禁用网络搜索
- **交互式澄清**: 遵循 LangGraph 标准工作流的智能问题澄清
- **流式输出**: 实时显示研究进度和阶段信息
- **并发处理**: 多线程并发研究加速信息收集

### ✨ 研究工作流

- **💬 澄清阶段**: 理解用户意图,必要时询问澄清问题
- **📝 计划阶段**: 生成结构化研究计划和子任务
- **🔬 研究阶段**: 并发执行搜索和文档分析任务
- **📄 报告阶段**: 综合所有信息生成最终研究报告

## 📁 项目结构

```text
deepresearch/
├── src/
│   ├── open_deep_research/      # 核心研究引擎
│   │   ├── deep_researcher.py   # LangGraph 主图实现
│   │   ├── configuration.py     # 配置管理
│   │   ├── state.py            # 状态定义
│   │   ├── prompts.py          # 提示词模板
│   │   └── utils.py            # 工具函数
│   ├── legacy/                  # 历史实现
│   │   ├── graph.py            # 计划-执行工作流
│   │   └── multi_agent.py      # 多智能体架构
│   └── security/               # 认证模块
├── tests/                       # 测试套件
├── mcp_runtime/                 # MCP 本地文档服务器
├── research.py                  # 命令行入口
├── langgraph.json              # LangGraph 配置
└── pyproject.toml              # 项目依赖
```

## 🚀 快速开始

### 环境要求
- Python 3.13+
- Node.js (用于 MCP 本地文档服务器)
- uv (Python 包管理器)

### 安装和配置

```bash
# 1. 安装依赖
cd deepresearch
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件,填入必要的 API 密钥

# 3. 安装 MCP 文件系统服务器 (可选,用于本地文档研究)
cd mcp_runtime
npm install @modelcontextprotocol/server-filesystem
cd ..
```

### 环境变量配置

在 `.env` 文件中配置以下内容:

```env
# API 密钥
QWEN_API_KEY=your_qwen_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
TAVILY_API_KEY=your_tavily_api_key

# API 端点
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 可选: LangSmith 追踪
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=deep-research
LANGSMITH_TRACING=false
```

## 🛠️ 使用方法

### 基本用法

```bash
# 基础研究 (需要指定模型和最大 tokens)
uv run python research.py "研究问题" --model qwen-plus --max-tokens 4096

# 使用推理模型进行深度分析
uv run python research.py "复杂问题分析" --model deepseek-reasoner --max-tokens 8192

# 快速研究 (跳过澄清)
uv run python research.py "快速查询" --model qwen-flash --max-tokens 2048 --no-clarify
```

### 本地文档研究

```bash
# 指定本地文档路径
uv run python research.py "分析项目架构" --docs-path ./src --model qwen-plus --max-tokens 4096

# 交互式选择文档路径
uv run python research.py "代码分析" --interactive-docs --model deepseek-chat --max-tokens 8192

# 仅使用本地文档,禁用网络搜索
uv run python research.py "本地文档研究" --docs-path ./src --no-search --model qwen-plus --max-tokens 4096
```

### 高级配置

```bash
# 完整配置示例
uv run python research.py "深度研究主题" \
  --model qwen-plus \
  --max-tokens 8192 \
  --docs-path ./src \
  --search-api tavily \
  --max-concurrent 8 \
  --max-iterations 10
```

## ⚙️ 命令行参数

| 参数 | 说明 | 默认值 | 必需 |
|------|------|--------|------|
| `question` | 研究问题或主题 | - | ✅ |
| `--model` | 使用的模型 | - | ✅ |
| `--max-tokens` | 模型最大输出 tokens | - | ✅ |
| `--no-search` | 禁用互联网搜索 | `False` | ❌ |
| `--search-api` | 搜索引擎 (tavily/none) | `tavily` | ❌ |
| `--no-clarify` | 跳过交互式澄清 | `False` | ❌ |
| `--docs-path` | 本地文档路径 | `None` | ❌ |
| `--interactive-docs` | 交互式选择文档 | `False` | ❌ |
| `--max-concurrent` | 最大并发研究单元数 | `8` | ❌ |
| `--max-iterations` | 最大研究轮次 | `10` | ❌ |

## 🤖 支持的模型

| 模型名称 | 标识符 | 特点 | 推荐场景 |
|---------|--------|------|---------|
| **Qwen Flash** | `qwen-flash` | 快速推理,低成本 | 简单查询、快速研究 |
| **Qwen Plus** | `qwen-plus` | 均衡能力,高质量 | 复杂分析、报告生成 |
| **DeepSeek Chat** | `deepseek-chat` | 轻量对话,高性价比 | 一般对话、代码理解 |
| **DeepSeek Reasoner** | `deepseek-reasoner` | 深度推理,逻辑强 | 复杂推理、学术研究 |

### 模型选择建议

- **简单查询**: `qwen-flash` + `2048 tokens`
- **复杂分析**: `qwen-plus` + `4096-8192 tokens`
- **代码理解**: `deepseek-chat` + `4096 tokens`
- **深度推理**: `deepseek-reasoner` + `8192 tokens`

## 💡 使用场景

### 1. 学术研究
```bash
uv run python research.py "量子计算的最新发展趋势" \
  --model deepseek-reasoner \
  --max-tokens 8192
```

### 2. 代码分析
```bash
uv run python research.py "分析这个项目的架构设计模式" \
  --docs-path ./src \
  --no-search \
  --model qwen-plus \
  --max-tokens 4096
```

### 3. 快速查询
```bash
uv run python research.py "Python 异步编程基础概念" \
  --model qwen-flash \
  --max-tokens 2048 \
  --no-clarify
```

### 4. 离线研究
```bash
uv run python research.py "本地文档内容总结" \
  --interactive-docs \
  --no-search \
  --model deepseek-chat \
  --max-tokens 4096
```

## 🔍 研究流程详解

### 阶段 1: 💬 澄清阶段
- 分析用户问题的完整性和明确性
- 必要时向用户询问澄清问题
- 可通过 `--no-clarify` 跳过

### 阶段 2: 📝 计划阶段
- 根据问题生成结构化研究计划
- 分解为多个可并发的研究单元
- 确定搜索策略和文档范围

### 阶段 3: 🔬 研究阶段
- 并发执行多个研究单元
- 支持网络搜索和本地文档读取
- 实时收集和整理研究资料

### 阶段 4: 📄 报告阶段
- 综合所有研究结果
- 生成结构化研究报告
- 使用 `qwen-plus` 确保高质量输出

## 🚨 注意事项

### API 密钥
- 首次使用需配置对应模型的 API 密钥
- Tavily 搜索需要 `TAVILY_API_KEY`
- 建议使用 LangSmith 追踪调试

### 本地文档功能
- 需要安装 Node.js 和 MCP 文件系统服务器
- Windows 系统路径会自动转换为兼容格式
- 支持递归读取子目录文件

### Token 配置
- 根据任务复杂度合理设置 `--max-tokens`
- 推理模型建议使用 8192+ tokens
- Flash 模型适合 2048-4096 tokens

### 并发控制
- 默认并发数为 8,适合深度研究
- 可通过 `--max-concurrent` 调整
- 注意 API 速率限制

## 🛠 故障排除

### 常见问题

**API 密钥错误**
```bash
# 检查 .env 文件中的密钥配置
cat .env | grep API_KEY
```

**MCP 服务器启动失败**
```bash
# 确保安装了 Node.js 和 MCP 服务器
cd mcp_runtime
npm install @modelcontextprotocol/server-filesystem
```

**模型不可用**
```bash
# 查看支持的模型列表
uv run python research.py "test" --model invalid --max-tokens 2048
```

**文档路径不存在**
```bash
# 使用交互式选择
uv run python research.py "test" --interactive-docs --model qwen-plus --max-tokens 4096
```

### 调试模式

```bash
# 启用 LangSmith 追踪
export LANGSMITH_TRACING=true
export LANGSMITH_PROJECT=my-research-debug

# 运行研究
uv run python research.py "debug test" --model qwen-flash --max-tokens 2048
```

## 📚 开发指南

### 安装开发依赖
```bash
uv sync
uv add --dev mypy ruff pytest
```

### 运行测试
```bash
# 运行评估测试
uv run python tests/run_evaluate.py

# 代码检查
uv run ruff check src/
uv run mypy src/
```

### 使用 LangGraph Studio
```bash
# 启动可视化调试界面
uvx langgraph dev
```

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

## 🙏 致谢

本项目 Fork 自 [LangChain Open Deep Research](https://github.com/langchain-ai/open-deep-research),在此基础上进行了中文化和模型适配。

---

💡 **提示**: 更多问题请查看 [CLAUDE.md](CLAUDE.md) 或提交 Issue。
