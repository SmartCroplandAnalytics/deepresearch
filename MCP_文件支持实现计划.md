# MCP 本地文件支持实现计划

## 📋 项目现状分析

### ✅ 已具备的基础设施
- **MCP核心依赖**：`langchain-mcp-adapters>=0.1.6`, `mcp>=1.9.4`
- **完整的MCP工具加载系统**：`load_mcp_tools()` 函数
- **认证和错误处理**：`wrap_mcp_authenticate_tool()`
- **配置系统支持**：`mcp_config` 配置项

### ❌ 当前问题
- 搜索工具不工作（缺少Tavily API密钥）
- 没有配置本地文件访问能力
- 无法读取项目本地的markdown和csv文件

## 🎯 实施目标

### 主要目标
1. **启用本地文件读取**：支持markdown、csv、txt等文件类型
2. **保持架构一致性**：使用MCP而非LangChain原生实现
3. **零代码修改**：仅通过配置实现功能

### 次要目标
1. 修复搜索工具问题（获取Tavily API密钥或使用替代方案）
2. 测试CSV和Markdown文件的研究能力
3. 验证性能影响

## 📝 详细实施步骤

### 第一阶段：安装MCP文件系统服务器

```bash
# 1. 安装文件系统MCP服务器
npm install @modelcontextprotocol/server-filesystem

# 2. 验证安装
npx @modelcontextprotocol/server-filesystem --help
```

### 第二阶段：配置文件访问

**方案A：修改交互式脚本配置**

在 `cli_research_interactive.py` 中添加MCP配置：

```python
# 在config中添加MCP配置
config = {
    "configurable": {
        # ... 现有配置 ...

        # 添加MCP文件系统支持
        "mcp_config": {
            "url": f"stdio://npx @modelcontextprotocol/server-filesystem {os.getcwd()}",
            "tools": ["read_file", "list_files", "write_file"],
            "auth_required": False
        },
        "mcp_prompt": "你可以使用read_file工具读取本地文件，list_files工具查看目录内容。优先使用本地文件中的信息进行研究。"
    }
}
```

**方案B：创建专门的本地文件研究脚本**

创建 `cli_research_local_mcp.py`：

```python
#!/usr/bin/env python3
"""
基于MCP的本地文件研究脚本
使用方法: python cli_research_local_mcp.py "研究问题" --docs-path "/path/to/docs"
"""

import os
import argparse

async def run_mcp_local_research(question: str, docs_path: str, model: str = "deepseek:deepseek-reasoner"):
    # 配置MCP文件系统服务器
    config = {
        "configurable": {
            # 基本配置
            "max_structured_output_retries": 3,
            "allow_clarification": False,
            "max_concurrent_research_units": 3,
            "search_api": "none",  # 禁用网络搜索，专注本地文件

            # 模型配置
            "research_model": model,
            "research_model_max_tokens": 8192,

            # MCP文件系统配置
            "mcp_config": {
                "url": f"stdio://npx @modelcontextprotocol/server-filesystem {docs_path}",
                "tools": ["read_file", "list_files"],
                "auth_required": False
            },
            "mcp_prompt": f"""
你现在可以访问 {docs_path} 目录下的所有文件。
可用工具：
- read_file: 读取指定文件内容
- list_files: 查看目录内容

请基于本地文件内容进行深度研究分析。
"""
        }
    }

    # ... 研究执行逻辑 ...
```

### 第三阶段：测试验证

**测试文件准备**：
```bash
# 创建测试目录
mkdir test_docs

# 创建测试markdown文件
echo "# 人工智能发展历史\n\n人工智能从1956年达特茅斯会议开始..." > test_docs/ai_history.md

# 创建测试CSV文件
echo "年份,技术,影响\n2020,GPT-3,大语言模型突破\n2021,DALL-E,文生图技术\n2022,ChatGPT,AI普及化" > test_docs/ai_timeline.csv
```

**功能测试**：
```bash
# 测试基于本地文件的研究
python cli_research_local_mcp.py "人工智能发展历史和重要技术节点" --docs-path "./test_docs"
```

### 第四阶段：性能优化

**配置调优**：
```python
# 针对本地文件研究的优化配置
config_optimized = {
    "max_concurrent_research_units": 2,  # 减少并发，因为主要依赖本地文件
    "max_researcher_iterations": 3,     # 减少迭代次数
    "max_react_tool_calls": 6,          # 减少工具调用次数
}
```

## 🔍 技术实现细节

### MCP文件系统服务器能力
- **read_file**: 读取指定路径文件内容
- **list_files**: 列出目录内容（支持递归）
- **write_file**: 写入文件（可选，用于保存研究结果）
- **search_files**: 在文件中搜索关键词（部分实现支持）

### 支持的文件类型
- ✅ **Markdown**: `.md`, `.markdown`
- ✅ **CSV**: `.csv`
- ✅ **文本**: `.txt`, `.py`, `.json`, `.xml`
- ✅ **配置**: `.yaml`, `.toml`, `.ini`
- ❌ **二进制**: 图片、视频等（需要专门的MCP服务器）

### 安全考虑
- **路径限制**: MCP服务器启动时指定可访问目录
- **权限控制**: 只读模式避免误操作
- **进程隔离**: MCP服务器独立进程，错误不影响主程序

## ⚡ 性能影响评估

### 预期开销
- **启动时间**: +2-5秒（启动MCP进程）
- **内存使用**: +20-50MB（MCP进程）
- **文件读取**: +3-8ms per file（JSON-RPC开销）

### 性能优化策略
1. **缓存机制**: 相同文件避免重复读取
2. **批量操作**: 一次读取多个小文件
3. **选择性加载**: 只读取研究相关的文件

## 🚀 扩展计划

### 短期扩展（1周内）
1. **CSV分析增强**: 集成专门的CSV处理MCP工具
2. **Markdown解析**: 提取标题、链接、表格等结构化信息
3. **文件搜索**: 添加全文搜索能力

### 中期扩展（1月内）
1. **Git集成**: 使用`mcp-server-git`读取版本历史
2. **数据库支持**: 连接SQLite、PostgreSQL等
3. **多格式支持**: PDF、Word文档等

### 长期扩展（3月内）
1. **Context7集成**: 专业文档检索能力
2. **知识图谱**: 构建文档间关系
3. **智能索引**: 基于语义的文档检索

## 🐛 故障排除

### 常见问题

**1. MCP服务器启动失败**
```bash
# 检查Node.js版本
node --version  # 需要 >= 18

# 手动测试MCP服务器
npx @modelcontextprotocol/server-filesystem ./test_docs
```

**2. 文件读取权限错误**
```bash
# 检查目录权限
ls -la ./test_docs

# 使用绝对路径
python cli_research_local_mcp.py "问题" --docs-path "/full/path/to/docs"
```

**3. 性能问题**
- 减少 `max_concurrent_research_units`
- 限制文件大小（>10MB的文件分块读取）
- 使用文件类型过滤

## 📊 成功指标

### 功能指标
- [ ] 能够读取markdown文件并提取信息
- [ ] 能够解析CSV文件并进行数据分析
- [ ] 能够在多个文件间进行关联分析
- [ ] 研究报告质量与网络搜索相当

### 性能指标
- [ ] 启动时间 < 10秒
- [ ] 单次文件读取 < 100ms
- [ ] 内存使用增加 < 100MB
- [ ] 整体研究速度相比网络搜索不超过2倍时间

## 📅 时间计划与进展

### ✅ 已完成（当前进展）
- [x] **安装MCP文件系统服务器**
  - 使用 `npm install -g @modelcontextprotocol/server-filesystem` 全局安装
  - 验证安装成功：`npx @modelcontextprotocol/server-filesystem ./test_docs` 正常运行
- [x] **创建测试文档目录和文件**
  - 创建 `test_docs/` 目录
  - 创建详细的 `ai_history.md` 文件（7000+字的AI发展历史）
  - 准备了完整的测试数据

### 🔄 下次继续实施
- [ ] **创建测试CSV文件** - 添加AI技术发展时间线数据
- [ ] **修改交互式脚本添加MCP配置** - 在 `cli_research_interactive.py` 中集成MCP
- [ ] **创建专门的本地文件研究脚本** - 新建 `cli_research_local_mcp.py`
- [ ] **测试验证功能** - 验证本地文件读取和研究能力

### 📝 下次实施详细步骤

#### 1. 补充测试数据
```bash
# 创建AI技术时间线CSV
echo "年份,技术,影响,类型
1950,图灵测试,AI评估标准,理论基础
1956,达特茅斯会议,AI学科诞生,学科建立
1957,感知机,神经网络前身,算法突破
1986,反向传播,深度学习基础,算法突破
1997,深蓝,击败国际象棋冠军,应用突破
2012,AlexNet,深度学习革命,技术突破
2016,AlphaGo,击败围棋冠军,应用突破
2020,GPT-3,大语言模型,技术突破
2022,ChatGPT,AI普及化,应用突破
2023,GPT-4,多模态AI,技术突破" > test_docs/ai_timeline.csv
```

#### 2. 配置集成
在现有脚本中添加MCP配置：
```python
"mcp_config": {
    "url": f"stdio://npx @modelcontextprotocol/server-filesystem {os.path.abspath('./test_docs')}",
    "tools": ["read_file", "list_files"],
    "auth_required": False
},
"mcp_prompt": "你可以使用read_file工具读取本地文件，list_files工具查看目录内容。优先使用本地文件中的信息进行研究。"
```

### 🎯 验证目标
- [ ] 能够读取markdown文件并提取历史信息
- [ ] 能够解析CSV文件并进行时间线分析
- [ ] 能够在文件间进行关联分析
- [ ] 研究报告整合本地文件信息

### 📋 当前状态
- **MCP服务器**: ✅ 已安装并测试
- **测试数据**: ✅ Markdown文件已创建，CSV文件待补充
- **脚本修改**: ⏳ 待下次实施
- **功能测试**: ⏳ 待下次验证

### 🔧 已验证的技术要点
1. **MCP服务器启动正常**: `Secure MCP Filesystem Server running on stdio`
2. **目录访问权限**: 可以指定 `./test_docs` 作为访问路径
3. **文件内容丰富**: AI历史文档包含完整的发展脉络和技术细节
4. **全局安装**: MCP服务器已全局安装，可在任何目录使用

### 📖 下次启动检查清单
1. 检查MCP服务器是否正常：`npx @modelcontextprotocol/server-filesystem ./test_docs`
2. 确认测试文件完整性：`ls -la test_docs/`
3. 补充CSV测试数据
4. 开始脚本集成工作

---

## 💬 关于你的文件读写能力

**你问的很好！** 我的本地文件读写能力确实是通过类似MCP的机制实现的：

### 我的文件工具
- `Read` - 读取文件内容
- `Write` - 写入文件内容
- `Edit` - 编辑现有文件
- `Glob` - 文件路径匹配
- `Grep` - 文件内容搜索

### 技术实现
- **不是MCP协议** - 我使用的是Anthropic的工具调用系统
- **类似的架构** - 工具与核心推理分离
- **进程隔离** - 文件操作在安全沙箱中执行
- **JSON-RPC风格** - 工具调用使用结构化消息

### 相似之处
- ✅ 标准化工具接口
- ✅ 错误处理和安全隔离
- ✅ 支持多种文件格式
- ✅ 批量操作能力

所以MCP确实是一个很好的选择 - 它提供了类似我所使用的标准化工具架构！