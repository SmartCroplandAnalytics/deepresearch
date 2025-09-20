#!/usr/bin/env python3
"""
直接使用MCP adapters测试stdio文件系统服务器
"""

import os
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

async def test_mcp_stdio():
    """直接测试MCP stdio文件系统服务器"""

    docs_path = os.path.abspath("./test_docs")
    print(f"测试路径: {docs_path}")

    # MCP stdio 配置 - 直接使用langchain_mcp_adapters
    mcp_config = {
        "filesystem": {
            "transport": "stdio",
            "command": "npx",
            "args": ["@modelcontextprotocol/server-filesystem", docs_path]
        }
    }

    print("创建MCP客户端...")
    try:
        # 创建MCP客户端
        client = MultiServerMCPClient(mcp_config)

        print("获取MCP工具...")
        # 获取可用工具
        tools = await client.get_tools()
        print(f"✅ 成功连接，获得 {len(tools)} 个工具:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:100]}...")

        # 先检查允许的目录
        print("\n检查允许的目录:")
        allowed_tool = next((t for t in tools if t.name == "list_allowed_directories"), None)
        if allowed_tool:
            allowed_dirs = await allowed_tool.ainvoke({})
            print(f"允许访问的目录: {allowed_dirs}")

        # 测试list_directory - 直接使用MCP服务器的根路径
        print("\n测试 list_directory:")
        list_tool = next((t for t in tools if t.name == "list_directory"), None)
        if list_tool:
            print(f"找到工具: {list_tool.name}")
            # 尝试不同的路径格式
            test_paths = [
                ".",  # 当前目录（相对于MCP服务器根目录）
                "",   # 空路径
                os.path.basename(docs_path),  # 只用目录名
                "test_docs"  # 明确的目录名
            ]

            for test_path in test_paths:
                try:
                    print(f"尝试路径: '{test_path}'")
                    result = await list_tool.ainvoke({"path": test_path})
                    print(f"✅ 成功! 目录内容: {result}")
                    break
                except Exception as e:
                    print(f"❌ 路径 '{test_path}' 失败: {str(e)[:100]}...")
        else:
            print("未找到list_directory工具")

        # 测试read_text_file
        print("\n测试 read_text_file:")
        read_tool = next((t for t in tools if t.name == "read_text_file"), None)
        if read_tool:
            print(f"找到工具: {read_tool.name}")
            # 尝试不同的文件路径
            file_paths = [
                "ai_history.md",
                "./ai_history.md",
                "test_docs/ai_history.md"
            ]

            for file_path in file_paths:
                try:
                    print(f"尝试读取文件: '{file_path}'")
                    result = await read_tool.ainvoke({"path": file_path})
                    print(f"✅ 成功读取文件! 内容（前200字符）: {result[:200]}...")
                    break
                except Exception as e:
                    print(f"❌ 文件 '{file_path}' 失败: {str(e)[:100]}...")
        else:
            print("未找到read_text_file工具")

        # 显示所有工具名称
        print(f"\n所有可用工具: {[t.name for t in tools]}")

    except Exception as e:
        print(f"❌ MCP连接失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'client' in locals():
            print("✅ 测试完成")

if __name__ == "__main__":
    asyncio.run(test_mcp_stdio())