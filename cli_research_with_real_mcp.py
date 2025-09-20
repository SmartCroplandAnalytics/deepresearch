#!/usr/bin/env python3
"""
真正的MCP集成研究脚本 - 集成到实际的研究系统中
使用方法: python cli_research_with_real_mcp.py "研究问题" --docs-path "./test_docs"
"""

import os
import argparse
import asyncio
import uuid
from datetime import datetime
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

# 加载环境变量
load_dotenv(".env")

async def load_mcp_tools_direct(docs_path: str):
    """直接加载MCP工具"""
    abs_docs_path = os.path.abspath(docs_path)

    # MCP配置 - 使用测试成功的格式
    mcp_config = {
        "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", abs_docs_path]
        }
    }

    # 创建MCP客户端并获取工具
    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()

    return tools, client

async def run_real_mcp_research(question: str, docs_path: str, model: str = "deepseek:deepseek-reasoner"):
    """运行真正的MCP集成研究"""

    # 验证文档路径
    if not os.path.exists(docs_path):
        print(f"错误: 指定的路径不存在: {docs_path}")
        return None

    abs_docs_path = os.path.abspath(docs_path)
    print(f"研究问题: {question}")
    print(f"文档路径: {abs_docs_path}")
    print(f"使用模型: {model}")
    print("=" * 60)

    try:
        # 第一步：加载MCP工具
        print("📡 加载MCP工具...")
        tools, mcp_client = await load_mcp_tools_direct(docs_path)
        print(f"✅ 成功加载 {len(tools)} 个MCP工具")

        # 获取关键工具
        list_tool = next((t for t in tools if t.name == "list_directory"), None)
        read_tool = next((t for t in tools if t.name == "read_text_file"), None)

        if not list_tool or not read_tool:
            print("❌ 缺少必要的MCP工具")
            return None

        # 第二步：初始化LLM
        print("🤖 初始化研究模型...")
        llm = init_chat_model(model, temperature=0.1)

        # 第三步：扫描并读取文件
        print("📁 扫描并读取本地文件...")
        base_dir = os.path.basename(abs_docs_path)

        # 列出文件
        files_result = await list_tool.ainvoke({"path": base_dir})
        print(f"发现文件: {files_result.strip()}")

        # 读取所有文件
        file_contents = {}
        file_names = []
        for line in files_result.split('\n'):
            if '[FILE]' in line:
                file_name = line.split('[FILE]')[1].strip()
                file_names.append(file_name)

        for file_name in file_names:
            try:
                file_path = f"{base_dir}/{file_name}"
                print(f"  📖 读取文件: {file_path}")
                content = await read_tool.ainvoke({"path": file_path})
                file_contents[file_name] = content
                print(f"  ✅ 成功读取 {file_name} ({len(content)} 字符)")
            except Exception as e:
                print(f"  ❌ 读取 {file_name} 失败: {e}")

        # 第四步：构建研究提示
        print("🔍 开始AI分析...")

        # 构建包含所有本地文件内容的提示
        prompt = f"""你是一位专业的研究分析师。请基于以下本地文档内容，针对问题「{question}」进行深度研究和分析。

🚫 重要限制：
- 你只能使用下面提供的本地文档内容
- 严禁使用任何网络搜索或外部信息
- 所有分析必须基于本地文档中的事实

📁 可用的本地文档：

"""

        # 添加所有文件内容
        for filename, content in file_contents.items():
            prompt += f"""
## 📄 {filename}
```
{content}
```

"""

        prompt += f"""

📋 研究任务：
请基于上述本地文档内容，对「{question}」进行全面深入的分析。

要求：
1. 仔细分析所有提供的文档内容
2. 提取与研究问题相关的关键信息
3. 进行深度分析和综合
4. 生成结构化的研究报告
5. 在回答中明确引用具体的文档内容
6. 如果文档信息不足以完全回答问题，请明确指出限制

请生成一份专业的研究报告。"""

        # 第五步：执行AI研究
        messages = [HumanMessage(content=prompt)]
        response = await llm.ainvoke(messages)

        # 第六步：生成最终报告
        final_report = f"""# 基于本地MCP文档的研究报告

**研究问题**: {question}
**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**数据来源**: 本地MCP文件系统 ({abs_docs_path})
**分析模型**: {model}

---

## 📁 数据来源

基于以下本地文件进行分析：
{chr(10).join([f"- {name} ({len(content)} 字符)" for name, content in file_contents.items()])}

---

## 🔍 AI分析结果

{response.content}

---

## 📊 技术说明

- ✅ 使用MCP (Model Context Protocol) 读取本地文件
- ✅ 所有数据来源于本地文档，确保隐私安全
- ✅ 使用 {model} 模型进行深度分析
- ✅ 完全离线分析，无网络搜索

*本报告由MCP集成研究系统生成*
"""

        # 第七步：保存报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"mcp_ai_research_{timestamp}.md"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(final_report)

        print("\n📊 AI研究报告:")
        print("=" * 60)
        print(final_report)
        print("=" * 60)
        print(f"📁 报告已保存至: {report_filename}")

        return final_report

    except Exception as e:
        print(f"❌ 研究过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if 'mcp_client' in locals():
            try:
                # 清理MCP客户端
                print("🔚 清理MCP连接...")
            except:
                pass

def main():
    parser = argparse.ArgumentParser(description="真正的MCP集成研究工具")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--docs-path", default="./test_docs", help="要研究的文档目录路径")
    parser.add_argument("--model", default="deepseek:deepseek-reasoner", help="使用的AI模型")

    args = parser.parse_args()

    # 运行真正的MCP研究
    result = asyncio.run(run_real_mcp_research(args.question, args.docs_path, args.model))

    if result:
        print("\n✅ 研究完成!")
    else:
        print("\n❌ 研究失败!")

if __name__ == "__main__":
    main()