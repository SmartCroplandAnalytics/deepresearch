#!/usr/bin/env python3
"""
工作版本：基于MCP的本地文件研究脚本
使用方法: python cli_research_mcp_working.py "研究问题" --docs-path "./test_docs"
"""

import os
import argparse
import asyncio
import uuid
from datetime import datetime
from langchain_mcp_adapters.client import MultiServerMCPClient

async def run_mcp_local_research(question: str, docs_path: str):
    """基于MCP的本地文件研究 - 简化版本直接使用MCP工具"""

    # 验证文档路径
    if not os.path.exists(docs_path):
        print(f"错误: 指定的路径不存在: {docs_path}")
        return None

    abs_docs_path = os.path.abspath(docs_path)
    print(f"研究问题: {question}")
    print(f"文档路径: {abs_docs_path}")
    print("=" * 60)

    # MCP配置 - 使用我们测试成功的格式
    mcp_config = {
        "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", abs_docs_path]
        }
    }

    print("创建MCP客户端...")
    try:
        # 创建MCP客户端
        client = MultiServerMCPClient(mcp_config)

        # 获取工具
        tools = await client.get_tools()
        print(f"✅ 成功连接，获得 {len(tools)} 个MCP工具")

        # 获取工具引用
        list_tool = next((t for t in tools if t.name == "list_directory"), None)
        read_tool = next((t for t in tools if t.name == "read_text_file"), None)

        if not list_tool or not read_tool:
            print("❌ 缺少必要的MCP工具")
            return

        # 第一步：列出可用文件
        print("\n📁 扫描可用文件...")
        try:
            # 使用我们测试成功的路径格式
            base_dir = os.path.basename(abs_docs_path)
            files_result = await list_tool.ainvoke({"path": base_dir})
            print(f"发现文件: {files_result}")
        except Exception as e:
            print(f"❌ 无法列出文件: {e}")
            return

        # 第二步：读取所有相关文件
        print("\n📖 读取文件内容...")
        file_contents = {}

        # 根据文件列表提取文件名
        file_names = []
        for line in files_result.split('\n'):
            if '[FILE]' in line:
                # 提取文件名
                file_name = line.split('[FILE]')[1].strip()
                file_names.append(file_name)

        for file_name in file_names:
            try:
                # 使用正确的路径格式
                file_path = f"{base_dir}/{file_name}"
                print(f"  读取文件: {file_path}")
                content = await read_tool.ainvoke({"path": file_path})
                file_contents[file_name] = content
                print(f"  ✅ 成功读取 {file_name} ({len(content)} 字符)")
            except Exception as e:
                print(f"  ❌ 读取 {file_name} 失败: {e}")

        # 第三步：基于文件内容生成研究报告
        print("\n📝 生成研究报告...")
        report = generate_research_report(question, file_contents)

        # 第四步：保存报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"mcp_research_report_{timestamp}.md"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\n📊 研究报告:")
        print("=" * 60)
        print(report)
        print("=" * 60)
        print(f"📁 报告已保存至: {report_filename}")

        return report

    except Exception as e:
        print(f"❌ MCP研究失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def generate_research_report(question: str, file_contents: dict) -> str:
    """基于文件内容生成研究报告"""

    report = f"""# 本地文档研究报告

**研究问题**: {question}
**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**数据来源**: 本地MCP文件系统

---

## 📊 数据概览

基于以下本地文件进行研究分析：
"""

    # 添加文件概览
    for filename, content in file_contents.items():
        report += f"- **{filename}**: {len(content)} 字符\n"

    report += "\n---\n\n## 📋 详细分析\n\n"

    # 分析每个文件
    for filename, content in file_contents.items():
        report += f"### 📄 {filename}\n\n"

        if filename.endswith('.md'):
            # Markdown文件 - 提取关键信息
            lines = content.split('\n')
            headers = [line for line in lines if line.startswith('#')]
            if headers:
                report += "**主要章节**:\n"
                for header in headers[:10]:  # 限制显示前10个标题
                    report += f"- {header.strip()}\n"

            # 提取前几段内容
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip() and not p.startswith('#')]
            if paragraphs:
                report += f"\n**内容摘要**: {paragraphs[0][:300]}...\n\n"

        elif filename.endswith('.csv'):
            # CSV文件 - 分析数据结构
            lines = content.split('\n')
            if lines:
                header = lines[0]
                report += f"**数据结构**: {header}\n"
                report += f"**数据行数**: {len(lines) - 1}\n"

                # 显示前几行数据
                if len(lines) > 1:
                    report += "\n**样本数据**:\n```\n"
                    for line in lines[1:min(6, len(lines))]:  # 显示前5行数据
                        if line.strip():
                            report += f"{line}\n"
                    report += "```\n\n"

        else:
            # 其他文件类型 - 显示前几行
            lines = content.split('\n')
            report += f"**文件类型**: {filename.split('.')[-1] if '.' in filename else '未知'}\n"
            report += f"**内容预览**: {content[:200]}...\n\n"

    # 添加综合分析
    report += "---\n\n## 🔍 综合分析\n\n"

    if question.lower() in ['总结本地文档内容', '文档内容总结', '本地文档总结']:
        report += "根据扫描的本地文档，发现以下主要内容:\n\n"

        # 基于文件内容进行简单的关键词分析
        all_content = ' '.join(file_contents.values()).lower()

        if 'ai' in all_content or '人工智能' in all_content:
            report += "- 🤖 **人工智能相关**: 文档包含AI发展历史和技术信息\n"

        if '时间' in all_content or '年份' in all_content or 'year' in all_content:
            report += "- 📅 **时间线信息**: 包含历史发展时间线数据\n"

        if 'csv' in str(file_contents.keys()).lower():
            report += "- 📊 **结构化数据**: 包含CSV格式的数据文件\n"

        if 'md' in str(file_contents.keys()).lower():
            report += "- 📝 **文档说明**: 包含Markdown格式的说明文档\n"

    else:
        # 针对特定问题的分析
        report += f"针对问题「{question}」的分析:\n\n"
        report += "基于本地文档内容，可以提供以下相关信息:\n\n"

        # 简单的关键词匹配
        for filename, content in file_contents.items():
            relevant_content = []
            for line in content.split('\n'):
                # 简单的相关性检查
                question_words = question.lower().split()
                if any(word in line.lower() for word in question_words if len(word) > 2):
                    relevant_content.append(line.strip())

            if relevant_content:
                report += f"**从 {filename} 中找到的相关信息**:\n"
                for item in relevant_content[:5]:  # 限制显示前5个相关项
                    if item:
                        report += f"- {item}\n"
                report += "\n"

    # 结论
    report += "---\n\n## 📌 结论\n\n"
    report += f"✅ 成功读取了 {len(file_contents)} 个本地文件\n"
    report += f"✅ 所有数据来源于本地MCP文件系统，确保了数据隐私\n"
    report += f"✅ 研究基于实际的本地文档内容，而非网络搜索结果\n\n"

    report += "---\n\n*本报告由MCP本地文件研究系统生成*"

    return report

def main():
    parser = argparse.ArgumentParser(description="基于MCP的本地文件研究工具（工作版本）")
    parser.add_argument("question", help="研究问题或主题")
    parser.add_argument("--docs-path", default="./test_docs", help="要研究的文档目录路径")

    args = parser.parse_args()

    # 运行本地文件研究
    result = asyncio.run(run_mcp_local_research(args.question, args.docs_path))

    if result:
        print("\n✅ 研究完成!")
    else:
        print("\n❌ 研究失败!")

if __name__ == "__main__":
    main()