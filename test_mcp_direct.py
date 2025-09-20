#!/usr/bin/env python3
"""
直接测试MCP文件系统服务器
"""

import os
import asyncio
from open_deep_research.utils import load_mcp_tools

async def test_mcp_direct():
    """直接测试MCP工具"""

    docs_path = os.path.abspath("./test_docs")
    print(f"测试路径: {docs_path}")

    # MCP配置
    mcp_config = {
        "url": f"stdio://npx @modelcontextprotocol/server-filesystem {docs_path}",
        "tools": ["read_text_file", "list_directory", "search_files"],
        "auth_required": False
    }

    print("加载MCP工具...")
    try:
        # 创建配置对象
        config = {"configurable": {"mcp_config": mcp_config}}
        existing_tool_names = set()

        tools = await load_mcp_tools(config, existing_tool_names)
        print(f"✅ 成功加载 {len(tools)} 个MCP工具:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        # 测试list_directory
        print("\n测试 list_directory:")
        list_tool = next((t for t in tools if t.name == "list_directory"), None)
        if list_tool:
            result = await list_tool.ainvoke({"path": "."})
            print(f"目录内容: {result}")

        # 测试read_text_file
        print("\n测试 read_text_file:")
        read_tool = next((t for t in tools if t.name == "read_text_file"), None)
        if read_tool:
            result = await read_tool.ainvoke({"path": "ai_history.md"})
            print(f"文件内容（前200字符）: {result[:200]}...")

    except Exception as e:
        print(f"❌ MCP工具加载失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_direct())