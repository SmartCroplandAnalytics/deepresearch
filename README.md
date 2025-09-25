# 深度研究工具使用指南

## 🚀 快速开始

```bash
# 基础使用
python research.py "你的研究问题"

# 使用Qwen模型 + 思考模式
python research.py "复杂问题分析" --model qwen:plus-think

# 仅使用本地文档，禁用网络搜索
python research.py "项目代码分析" --docs-path ./src --no-search

# 交互式选择文档路径
python research.py "本地研究" --interactive-docs
```

## 📋 功能特性

### ✅ 支持的模型

| 模型类型 | 模型名称 | 特点 |
|---------|---------|------|
| **Qwen Fast** | `qwen:flash` | 快速推理，适合简单任务 |
| **Qwen Fast+Think** | `qwen:flash-think` | 快速推理 + 思考模式 |
| **Qwen Plus** | `qwen:plus` | 均衡能力，适合复杂任务 |
| **Qwen Plus+Think** | `qwen:plus-think` | 高级推理 + 思考模式 |
| **DeepSeek Chat** | `deepseek:chat` | 轻量对话模型 |
| **DeepSeek Reasoning** | `deepseek:reasoning` | 推理专用模型（默认）|

### 🔧 核心功能

- **🤖 可配置模型** - 支持Qwen/DeepSeek全系列模型
- **💬 交互式澄清** - 遵循LangGraph标准工作流
- **📁 本地文档读取** - 通过MCP协议访问本地文件
- **🌐 可开关搜索** - 互联网搜索可禁用
- **⚡ 流式输出** - 实时显示研究进度
- **🔄 并发处理** - 多线程加速研究过程

## 🎯 使用场景

### 1. 学术研究
```bash
python research.py "量子计算的最新发展" --model qwen:plus-think
```

### 2. 代码分析
```bash
python research.py "分析这个项目的架构设计" --docs-path ./src --no-search
```

### 3. 快速查询
```bash
python research.py "Python异步编程基础" --model qwen:flash --no-clarify
```

### 4. 离线研究
```bash
python research.py "本地文档分析" --interactive-docs --no-search
```

## ⚙️ 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `question` | 研究问题或主题 | **必需** |
| `--model` | 使用的模型 | `deepseek:reasoning` |
| `--no-search` | 禁用互联网搜索 | `False` |
| `--search-api` | 搜索引擎选择 | `tavily` |
| `--no-clarify` | 跳过交互式澄清 | `False` |
| `--docs-path` | 本地文档路径 | `None` |
| `--interactive-docs` | 交互式选择文档 | `False` |
| `--max-concurrent` | 最大并发数 | `5` |
| `--max-iterations` | 最大研究轮次 | `6` |

## 🔧 环境配置

确保`.env`文件包含以下配置：

```env
# API密钥
QWEN_API_KEY=your_qwen_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
TAVILY_API_KEY=your_tavily_api_key

# API端点
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 可选：LangSmith追踪
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_PROJECT=your_project_name
LANGSMITH_TRACING=false
```

## 💡 使用技巧

### 1. 模型选择建议
- **简单查询**: `qwen:flash`
- **复杂分析**: `qwen:plus-think`
- **代码理解**: `deepseek:reasoning`
- **成本优化**: `deepseek:chat`

### 2. 搜索策略
- 使用 `--no-search` 处理敏感或私有信息
- 本地文档研究时禁用搜索避免信息泄露
- 网络搜索增强信息完整性

### 3. 文档路径设置
- 使用绝对路径避免路径问题
- 支持递归读取子目录文件
- 推荐使用`--interactive-docs`便捷选择

## 🔍 研究工作流

1. **💬 澄清阶段** - 理解用户意图，必要时询问澄清
2. **📝 计划阶段** - 生成结构化研究计划
3. **🔬 研究阶段** - 并发执行搜索和文档分析
4. **📄 报告阶段** - 综合生成最终研究报告

## 🚨 注意事项

- 首次使用需要配置对应的API密钥
- 思考模式(think)会消耗更多tokens但提供更深入分析
- 本地文档功能需要安装Node.js和相关MCP服务器
- 大型文档集合建议调整`--max-concurrent`参数

## 🛠 故障排除

### 常见问题

1. **API密钥错误**
   ```
   解决: 检查.env文件中的API密钥配置
   ```

2. **MCP服务器启动失败**
   ```
   解决: 确保安装了Node.js和@modelcontextprotocol/server-filesystem
   npm install -g @modelcontextprotocol/server-filesystem
   ```

3. **模型不可用**
   ```
   解决: 使用 --model 参数查看支持的模型列表
   ```

## 📞 获取帮助

```bash
# 查看完整帮助信息
python research.py --help

# 查看支持的模型
python research.py "test" --model invalid_model
```