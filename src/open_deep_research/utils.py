"""Utility functions and helpers for the Deep Research agent."""

import asyncio
import logging
import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Literal, Optional

import aiohttp
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    MessageLikeRepresentation,
    filter_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import (
    BaseTool,
    InjectedToolArg,
    StructuredTool,
    ToolException,
    tool,
)
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.config import get_store
from mcp import McpError
from tavily import AsyncTavilyClient

from open_deep_research.configuration import Configuration, SearchAPI
from open_deep_research.prompts import summarize_webpage_prompt
from open_deep_research.state import ResearchComplete, Summary

##########################
# Model Configuration Utils
##########################
def supports_structured_output(model_name: str) -> bool:
    """Check if a model supports structured output (JSON mode)."""
    model_name = model_name.lower()

    # Qwen models support structured output
    if model_name.startswith("qwen-"):
        return True

    # DeepSeek models currently don't support structured output
    if model_name.startswith("deepseek-"):
        return False

    # OpenAI, Anthropic, Google models generally support structured output
    if any(provider in model_name for provider in ["gpt", "claude", "gemini", "openai", "anthropic"]):
        return True

    # Default to False for unknown models to be safe
    return False

def get_configured_chat_model_with_structured_output(model_name: str, max_tokens: int, api_key: str, output_schema=None, with_retry_attempts: int = 3):
    """Get a chat model with structured output support, with fallback for unsupported models."""
    base_model = get_configured_chat_model(model_name, max_tokens, api_key)

    if output_schema and supports_structured_output(model_name):
        # Model supports structured output
        return base_model.with_structured_output(output_schema).with_retry(stop_after_attempt=with_retry_attempts)
    elif output_schema:
        # Model doesn't support structured output, use text output with JSON parsing
        from langchain_core.output_parsers import PydanticOutputParser
        parser = PydanticOutputParser(pydantic_object=output_schema)
        return (base_model | parser).with_retry(stop_after_attempt=with_retry_attempts)
    else:
        # No structured output needed
        return base_model.with_retry(stop_after_attempt=with_retry_attempts)

def get_configured_chat_model(model_name: str, max_tokens: int, api_key: str):
    """Get a properly configured chat model with special handling for Qwen and DeepSeek."""

    # Handle special model configurations (Qwen and DeepSeek)
    if model_name.lower().startswith(("qwen-", "deepseek-")):
        model_config = get_model_config(model_name)
        if model_config:
            # 明确指定模型提供者
            model_provider = "openai"
            return init_chat_model(
                model=model_config["model"],
                model_provider=model_provider,
                max_tokens=max_tokens,
                api_key=api_key,
                base_url=model_config["base_url"],
                **model_config.get("model_kwargs", {})
            )

    # Default model initialization
    return init_chat_model(
        model=model_name,
        max_tokens=max_tokens,
        api_key=api_key,
    )

##########################
# Tavily Search Tool Utils
##########################
TAVILY_SEARCH_DESCRIPTION = (
    "A search engine optimized for comprehensive, accurate, and trusted results. "
    "Useful for when you need to answer questions about current events."
)
@tool(description=TAVILY_SEARCH_DESCRIPTION)
async def tavily_search(
    queries: List[str],
    max_results: Annotated[int, InjectedToolArg] = 5,
    topic: Annotated[Literal["general", "news", "finance"], InjectedToolArg] = "general",
    config: RunnableConfig = None
) -> str:
    """Fetch and summarize search results from Tavily search API.

    Args:
        queries: List of search queries to execute
        max_results: Maximum number of results to return per query
        topic: Topic filter for search results (general, news, or finance)
        config: Runtime configuration for API keys and model settings

    Returns:
        Formatted string containing summarized search results
    """
    # Step 1: Execute search queries asynchronously
    search_results = await tavily_search_async(
        queries,
        max_results=max_results,
        topic=topic,
        include_raw_content=True,
        config=config
    )
    
    # Step 2: Deduplicate results by URL to avoid processing the same content multiple times
    unique_results = {}
    for response in search_results:
        for result in response['results']:
            url = result['url']
            if url not in unique_results:
                unique_results[url] = {**result, "query": response['query']}
    
    # Step 3: Set up the summarization model with configuration
    configurable = Configuration.from_runnable_config(config)
    
    # Character limit to stay within model token limits (configurable)
    max_char_to_include = configurable.max_content_length
    
    # Initialize summarization model with retry logic (支持DeepSeek等不支持结构化输出的模型)
    model_api_key = get_api_key_for_model(configurable.summarization_model, config)

    summarization_model = get_configured_chat_model_with_structured_output(
        configurable.summarization_model,
        configurable.summarization_model_max_tokens,
        model_api_key,
        Summary,
        configurable.max_structured_output_retries
    )
    
    # Step 4: Create summarization tasks (skip empty content)
    async def noop():
        """No-op function for results without raw content."""
        return None
    
    summarization_tasks = [
        noop() if not result.get("raw_content") 
        else summarize_webpage(
            summarization_model, 
            result['raw_content'][:max_char_to_include]
        )
        for result in unique_results.values()
    ]
    
    # Step 5: Execute all summarization tasks in parallel
    summaries = await asyncio.gather(*summarization_tasks)
    
    # Step 6: Combine results with their summaries
    summarized_results = {
        url: {
            'title': result['title'], 
            'content': result['content'] if summary is None else summary
        }
        for url, result, summary in zip(
            unique_results.keys(), 
            unique_results.values(), 
            summaries
        )
    }
    
    # Step 7: Format the final output
    if not summarized_results:
        return "No valid search results found. Please try different search queries or use a different search API."
    
    formatted_output = "Search results: \n\n"
    for i, (url, result) in enumerate(summarized_results.items()):
        formatted_output += f"\n\n--- SOURCE {i+1}: {result['title']} ---\n"
        formatted_output += f"URL: {url}\n\n"
        formatted_output += f"SUMMARY:\n{result['content']}\n\n"
        formatted_output += "\n\n" + "-" * 80 + "\n"
    
    return formatted_output

async def tavily_search_async(
    search_queries, 
    max_results: int = 5, 
    topic: Literal["general", "news", "finance"] = "general", 
    include_raw_content: bool = True, 
    config: RunnableConfig = None
):
    """Execute multiple Tavily search queries asynchronously.
    
    Args:
        search_queries: List of search query strings to execute
        max_results: Maximum number of results per query
        topic: Topic category for filtering results
        include_raw_content: Whether to include full webpage content
        config: Runtime configuration for API key access
        
    Returns:
        List of search result dictionaries from Tavily API
    """
    # Initialize the Tavily client with API key from config
    tavily_client = AsyncTavilyClient(api_key=get_tavily_api_key(config))
    
    # Create search tasks for parallel execution
    search_tasks = [
        tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic
        )
        for query in search_queries
    ]
    
    # Execute all search queries in parallel and return results
    search_results = await asyncio.gather(*search_tasks)
    return search_results

async def summarize_webpage(model: BaseChatModel, webpage_content: str) -> str:
    """Summarize webpage content using AI model with timeout protection.
    
    Args:
        model: The chat model configured for summarization
        webpage_content: Raw webpage content to be summarized
        
    Returns:
        Formatted summary with key excerpts, or original content if summarization fails
    """
    try:
        # Create prompt with current date context
        prompt_content = summarize_webpage_prompt.format(
            webpage_content=webpage_content, 
            date=get_today_str()
        )
        
        # Execute summarization with timeout to prevent hanging
        summary = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content=prompt_content)]),
            timeout=60.0  # 60 second timeout for summarization
        )
        
        # Format the summary with structured sections
        formatted_summary = (
            f"<summary>\n{summary.summary}\n</summary>\n\n"
            f"<key_excerpts>\n{summary.key_excerpts}\n</key_excerpts>"
        )
        
        return formatted_summary
        
    except asyncio.TimeoutError:
        # Timeout during summarization - return original content
        logging.warning("Summarization timed out after 60 seconds, returning original content")
        return webpage_content
    except Exception as e:
        # Other errors during summarization - log and return original content
        logging.warning(f"Summarization failed with error: {str(e)}, returning original content")
        return webpage_content

##########################
# Reflection Tool Utils
##########################

@tool(description="Strategic reflection tool for research planning")
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"

##########################
# MCP Utils
##########################

async def get_mcp_access_token(
    supabase_token: str,
    base_mcp_url: str,
) -> Optional[Dict[str, Any]]:
    """Exchange Supabase token for MCP access token using OAuth token exchange.
    
    Args:
        supabase_token: Valid Supabase authentication token
        base_mcp_url: Base URL of the MCP server
        
    Returns:
        Token data dictionary if successful, None if failed
    """
    try:
        # Prepare OAuth token exchange request data
        form_data = {
            "client_id": "mcp_default",
            "subject_token": supabase_token,
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "resource": base_mcp_url.rstrip("/") + "/mcp",
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        }
        
        # Execute token exchange request
        async with aiohttp.ClientSession() as session:
            token_url = base_mcp_url.rstrip("/") + "/oauth/token"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            
            async with session.post(token_url, headers=headers, data=form_data) as response:
                if response.status == 200:
                    # Successfully obtained token
                    token_data = await response.json()
                    return token_data
                else:
                    # Log error details for debugging
                    response_text = await response.text()
                    logging.error(f"Token exchange failed: {response_text}")
                    
    except Exception as e:
        logging.error(f"Error during token exchange: {e}")
    
    return None

async def get_tokens(config: RunnableConfig):
    """Retrieve stored authentication tokens with expiration validation.
    
    Args:
        config: Runtime configuration containing thread and user identifiers
        
    Returns:
        Token dictionary if valid and not expired, None otherwise
    """
    store = get_store()
    
    # Extract required identifiers from config
    thread_id = config.get("configurable", {}).get("thread_id")
    if not thread_id:
        return None
        
    user_id = config.get("metadata", {}).get("owner")
    if not user_id:
        return None
    
    # Retrieve stored tokens
    tokens = await store.aget((user_id, "tokens"), "data")
    if not tokens:
        return None
    
    # Check token expiration
    expires_in = tokens.value.get("expires_in")  # seconds until expiration
    created_at = tokens.created_at  # datetime of token creation
    current_time = datetime.now(timezone.utc)
    expiration_time = created_at + timedelta(seconds=expires_in)
    
    if current_time > expiration_time:
        # Token expired, clean up and return None
        await store.adelete((user_id, "tokens"), "data")
        return None

    return tokens.value

async def set_tokens(config: RunnableConfig, tokens: dict[str, Any]):
    """Store authentication tokens in the configuration store.
    
    Args:
        config: Runtime configuration containing thread and user identifiers
        tokens: Token dictionary to store
    """
    store = get_store()
    
    # Extract required identifiers from config
    thread_id = config.get("configurable", {}).get("thread_id")
    if not thread_id:
        return
        
    user_id = config.get("metadata", {}).get("owner")
    if not user_id:
        return
    
    # Store the tokens
    await store.aput((user_id, "tokens"), "data", tokens)

async def fetch_tokens(config: RunnableConfig) -> dict[str, Any]:
    """Fetch and refresh MCP tokens, obtaining new ones if needed.
    
    Args:
        config: Runtime configuration with authentication details
        
    Returns:
        Valid token dictionary, or None if unable to obtain tokens
    """
    # Try to get existing valid tokens first
    current_tokens = await get_tokens(config)
    if current_tokens:
        return current_tokens
    
    # Extract Supabase token for new token exchange
    supabase_token = config.get("configurable", {}).get("x-supabase-access-token")
    if not supabase_token:
        return None
    
    # Extract MCP configuration
    mcp_config = config.get("configurable", {}).get("mcp_config")
    if not mcp_config or not mcp_config.get("url"):
        return None
    
    # Exchange Supabase token for MCP tokens
    mcp_tokens = await get_mcp_access_token(supabase_token, mcp_config.get("url"))
    if not mcp_tokens:
        return None

    # Store the new tokens and return them
    await set_tokens(config, mcp_tokens)
    return mcp_tokens

def wrap_mcp_authenticate_tool(tool: StructuredTool) -> StructuredTool:
    """Wrap MCP tool with comprehensive authentication and error handling.
    
    Args:
        tool: The MCP structured tool to wrap
        
    Returns:
        Enhanced tool with authentication error handling
    """
    original_coroutine = tool.coroutine
    
    async def authentication_wrapper(**kwargs):
        """Enhanced coroutine with MCP error handling, pool management, and user-friendly messages."""
        from datetime import datetime

        def _find_mcp_error_in_exception_chain(exc: BaseException) -> McpError | None:
            """Recursively search for MCP errors in exception chains."""
            if isinstance(exc, McpError):
                return exc

            # Handle ExceptionGroup (Python 3.11+) by checking attributes
            if hasattr(exc, 'exceptions'):
                for sub_exception in exc.exceptions:
                    if found_error := _find_mcp_error_in_exception_chain(sub_exception):
                        return found_error
            return None

        # Check if this tool has a pool attached (for MCP tools)
        pool = getattr(tool, '_mcp_pool', None)

        try:
            # If pool exists, acquire a client for this tool call
            if pool:
                print(f"[{datetime.now()}] 🔧 Tool '{tool.name}': Acquiring client from pool...")
                client = await pool.acquire()
                print(f"[{datetime.now()}] 🔧 Tool '{tool.name}': Client acquired")

            try:
                # Execute the original tool functionality with timeout protection
                import asyncio
                # Different timeouts for different operations
                timeout = 120.0  # Default: 2 minutes for file operations
                if tool.name == "list_directory":
                    timeout = 60.0  # 1 minute for listing directories

                result = await asyncio.wait_for(
                    original_coroutine(**kwargs),
                    timeout=timeout
                )

                return result
            finally:
                # Always release client back to pool after tool execution
                if pool:
                    await pool.release(client)
                    print(f"[{datetime.now()}] 🔧 Tool '{tool.name}': Client released")

        except asyncio.TimeoutError:
            # MCP tool call timed out
            raise ToolException(
                f"MCP tool '{tool.name}' timed out after {timeout} seconds. "
                "The operation may be taking too long or encountering issues."
            )

        except BaseException as original_error:
            # Search for MCP-specific errors in the exception chain
            mcp_error = _find_mcp_error_in_exception_chain(original_error)
            if not mcp_error:
                # Not an MCP error, re-raise the original exception
                raise original_error
            
            # Handle MCP-specific error cases
            error_details = mcp_error.error
            error_code = getattr(error_details, "code", None)
            error_data = getattr(error_details, "data", None) or {}
            
            # Check for authentication/interaction required error
            if error_code == -32003:  # Interaction required error code
                message_payload = error_data.get("message", {})
                error_message = "Required interaction"
                
                # Extract user-friendly message if available
                if isinstance(message_payload, dict):
                    error_message = message_payload.get("text") or error_message
                
                # Append URL if provided for user reference
                if url := error_data.get("url"):
                    error_message = f"{error_message} {url}"
                
                raise ToolException(error_message) from original_error
            
            # For other MCP errors, re-raise the original
            raise original_error
    
    # Replace the tool's coroutine with our enhanced version
    tool.coroutine = authentication_wrapper
    return tool

# MCP Client Pool for handling concurrent access
class MCPClientPool:
    """True resource pool for MCP clients with acquire/release semantics.

    Best practice: Each researcher acquires an exclusive MCP client from the pool,
    uses it for the entire research session, then releases it back. This prevents
    stdio conflicts while allowing true parallelism up to pool_size.

    Architecture:
    - pool_size clients are pre-created (based on CPU cores)
    - asyncio.Queue manages available clients
    - Researcher acquires → uses exclusively → releases
    """

    def __init__(self, mcp_config: dict, pool_size: int):
        """Initialize MCP client pool.

        Args:
            mcp_config: MCP server configuration
            pool_size: Maximum number of concurrent MCP clients (based on CPU cores)
        """
        self.mcp_config = mcp_config
        self.pool_size = pool_size
        self.available_clients = asyncio.Queue(maxsize=pool_size)  # Queue of available clients
        self.all_clients: list = []  # All created clients (for cleanup)
        self.init_lock = asyncio.Lock()  # Protect pool initialization
        self.initialized = False
        self.cached_tools: list = []  # Cached tool list to avoid repeated get_tools() calls

        from datetime import datetime
        print(f"[{datetime.now()}] 🏊 MCP Pool: Created with size {pool_size} (CPU-based)")

    async def _initialize_pool(self):
        """Pre-create all clients in the pool and cache the tool list (lazy initialization on first use)."""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from datetime import datetime

        async with self.init_lock:
            if self.initialized:
                return

            print(f"[{datetime.now()}] 🏊 MCP Pool: Initializing {self.pool_size} clients...")

            # Create the first client and get tools from it ONCE
            print(f"[{datetime.now()}] 🔌 MCP Pool: Creating client #1/{self.pool_size}...")
            first_client = MultiServerMCPClient(self.mcp_config)

            # Register for cleanup
            global _mcp_clients
            _mcp_clients.append(first_client)
            self.all_clients.append(first_client)

            # Get tools ONCE from the first client and cache
            print(f"[{datetime.now()}] 📋 MCP Pool: Fetching tool list from first client...")
            try:
                self.cached_tools = await asyncio.wait_for(first_client.get_tools(), timeout=60.0)
                print(f"[{datetime.now()}] ✅ MCP Pool: Cached {len(self.cached_tools)} tools")
            except Exception as e:
                print(f"[{datetime.now()}] ⚠️  MCP Pool: Failed to get tools: {e}")
                self.cached_tools = []

            # Put first client into available queue
            await self.available_clients.put(first_client)
            print(f"[{datetime.now()}] ✅ MCP Pool: Client #1 ready")

            # Create remaining clients (no need to get_tools from each)
            for i in range(1, self.pool_size):
                print(f"[{datetime.now()}] 🔌 MCP Pool: Creating client #{i+1}/{self.pool_size}...")
                client = MultiServerMCPClient(self.mcp_config)

                # Register for cleanup
                _mcp_clients.append(client)
                self.all_clients.append(client)

                # Put into available queue
                await self.available_clients.put(client)
                print(f"[{datetime.now()}] ✅ MCP Pool: Client #{i+1} ready")

            self.initialized = True
            print(f"[{datetime.now()}] 🏊 MCP Pool: All {self.pool_size} clients initialized")

    async def acquire(self):
        """Acquire an exclusive MCP client from the pool.

        Blocks if all clients are in use. Returns a client that the caller
        owns exclusively until release() is called.

        Returns:
            MCP client instance for exclusive use
        """
        from datetime import datetime

        # Lazy initialize pool on first acquire
        if not self.initialized:
            await self._initialize_pool()

        # Wait for available client (blocks if pool is full)
        client = await self.available_clients.get()
        current_available = self.available_clients.qsize()
        print(f"[{datetime.now()}] 🏊 MCP Pool: Acquired client (available: {current_available}/{self.pool_size})")

        return client

    async def release(self, client):
        """Release a client back to the pool.

        Args:
            client: The MCP client to return to the pool
        """
        from datetime import datetime

        await self.available_clients.put(client)
        current_available = self.available_clients.qsize()
        print(f"[{datetime.now()}] 🏊 MCP Pool: Released client (available: {current_available}/{self.pool_size})")

    async def get_cached_tools(self):
        """Get the cached tool list without calling get_tools().

        This method ensures pool is initialized and returns the pre-cached tool list,
        avoiding stdio contention when multiple researchers request tools simultaneously.

        Returns:
            List of cached tools from the pool
        """
        from datetime import datetime

        # Ensure pool is initialized (will cache tools on first call)
        if not self.initialized:
            await self._initialize_pool()

        print(f"[{datetime.now()}] 📋 MCP Pool: Returning {len(self.cached_tools)} cached tools")
        return self.cached_tools

    async def get_tools_from_client(self, client):
        """Get tools from a specific client (deprecated - use get_cached_tools instead).

        Args:
            client: MCP client to get tools from

        Returns:
            List of tools from the client
        """
        from datetime import datetime

        try:
            tools = await asyncio.wait_for(client.get_tools(), timeout=30.0)
            print(f"[{datetime.now()}] ✅ MCP Pool: Got {len(tools)} tools from client")
            return tools
        except asyncio.TimeoutError:
            print(f"[{datetime.now()}] ⚠️  MCP Pool: Client get_tools timed out after 30 seconds")
            raise
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  MCP Pool: Client get_tools failed: {e}")
            raise

# Global registry
_mcp_clients: list = []  # All created MCP clients (for cleanup)
_mcp_client_pools: dict = {}  # Pools by config hash (one pool per docs_path)
_cleanup_registered = False


def _calculate_mcp_pool_size() -> int:
    """Calculate optimal MCP client pool size based on CPU cores.

    Strategy:
    - 1-4 cores: pool_size = 2 (minimal parallelism)
    - 5-8 cores: pool_size = 3 (moderate parallelism)
    - 9-16 cores: pool_size = 5 (good parallelism)
    - 17+ cores: pool_size = 8 (high parallelism)

    Returns:
        Optimal pool size for current system
    """
    import os
    from datetime import datetime

    cpu_count = os.cpu_count() or 4  # Default to 4 if detection fails

    if cpu_count <= 4:
        pool_size = 2
    elif cpu_count <= 8:
        pool_size = 3
    elif cpu_count <= 16:
        pool_size = 5
    else:
        pool_size = 8

    print(f"[{datetime.now()}] 💻 System: Detected {cpu_count} CPU cores → MCP pool size = {pool_size}")
    return pool_size

def _cleanup_all_mcp_clients():
    """Cleanup all MCP clients, pools, and their Node.js subprocesses when process exits"""
    global _mcp_clients, _mcp_client_pools
    from datetime import datetime
    import subprocess
    import sys

    # Clear the pools
    _mcp_client_pools.clear()

    if _mcp_clients:
        print(f"\n[{datetime.now()}] 🧹 Cleaning up {len(_mcp_clients)} MCP client(s)...")

        for idx, client in enumerate(_mcp_clients):
            try:
                print(f"[{datetime.now()}] 🧹 Cleaning up MCP client {idx + 1}/{len(_mcp_clients)}...")

                # Try to access the underlying MCP server processes
                if hasattr(client, '_clients'):
                    # MultiServerMCPClient has _clients dict
                    for server_name, server_client in client._clients.items():
                        print(f"[{datetime.now()}]    📡 Server: {server_name}")
                        # Try to terminate the subprocess if it exists
                        if hasattr(server_client, '_process') and server_client._process:
                            try:
                                server_client._process.terminate()
                                print(f"[{datetime.now()}]    ✓ Terminated subprocess for {server_name}")
                            except:
                                pass

                # Try standard close methods
                if hasattr(client, 'close'):
                    client.close()
                    print(f"[{datetime.now()}]    ✓ Called close() on client")
                elif hasattr(client, 'cleanup'):
                    client.cleanup()
                    print(f"[{datetime.now()}]    ✓ Called cleanup() on client")

            except Exception as e:
                print(f"[{datetime.now()}] ⚠️ Error cleaning up MCP client {idx + 1}: {e}")

        _mcp_clients.clear()

        # Additional: Kill any remaining Node.js MCP processes
        try:
            if sys.platform == "win32":
                # Windows: Find and kill node.exe processes running MCP server
                result = subprocess.run(
                    'wmic process where "name=\'node.exe\' AND CommandLine LIKE \'%modelcontextprotocol%\'" get ProcessId /format:csv',
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.stdout:
                    lines = result.stdout.strip().split('\n')[1:]  # Skip header
                    killed_count = 0
                    for line in lines:
                        if line.strip():
                            parts = line.split(',')
                            if len(parts) >= 2:
                                pid = parts[-1].strip()
                                try:
                                    subprocess.run(f'taskkill /PID {pid} /F', shell=True,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    killed_count += 1
                                except:
                                    pass
                    if killed_count > 0:
                        print(f"[{datetime.now()}] 🧹 Killed {killed_count} orphan Node.js MCP process(es)")
            else:
                # Unix/Linux/Mac: Find and kill node processes
                subprocess.run(
                    "pkill -f 'node.*modelcontextprotocol'",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️ Error during orphan process cleanup: {e}")

        print(f"[{datetime.now()}] ✅ MCP cleanup completed")

def _register_cleanup_handlers():
    """Register cleanup handlers for process exit"""
    global _cleanup_registered

    if _cleanup_registered:
        return

    import atexit
    import signal

    # Register atexit handler for normal exit
    atexit.register(_cleanup_all_mcp_clients)

    # Register signal handlers for forced termination
    def signal_handler(signum, frame):
        from datetime import datetime
        print(f"\n[{datetime.now()}] 🛑 Received signal {signum}, cleaning up...")
        _cleanup_all_mcp_clients()
        import sys
        sys.exit(0)

    # Handle common termination signals
    try:
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # kill command
    except (AttributeError, ValueError):
        # Some signals may not be available on all platforms
        pass

    _cleanup_registered = True

async def load_mcp_tools(
    config: RunnableConfig,
    existing_tool_names: set[str],
) -> list[BaseTool]:
    """Load and configure MCP (Model Context Protocol) tools with authentication.

    Args:
        config: Runtime configuration containing MCP server details
        existing_tool_names: Set of tool names already in use to avoid conflicts

    Returns:
        List of configured MCP tools ready for use
    """
    global _mcp_clients

    # Register cleanup handlers on first call
    _register_cleanup_handlers()

    configurable = Configuration.from_runnable_config(config)
    
    # Step 1: Handle authentication if required
    if configurable.mcp_config and configurable.mcp_config.auth_required:
        mcp_tokens = await fetch_tokens(config)
    else:
        mcp_tokens = None
    
    # Step 2: Validate configuration requirements
    mcp_config = configurable.mcp_config
    if not mcp_config or not mcp_config.tools:
        return []

    # Validate based on transport type
    if mcp_config.transport == "stdio":
        # For stdio: need command and args
        config_valid = (
            mcp_config.command and
            mcp_config.args and
            (mcp_tokens or not mcp_config.auth_required)
        )
    else:
        # For http: need URL
        config_valid = (
            mcp_config.url and
            (mcp_tokens or not mcp_config.auth_required)
        )

    if not config_valid:
        return []

    # Step 3: Set up MCP server connection based on transport
    if mcp_config.transport == "stdio":
        # Configure stdio MCP server
        mcp_server_config = {
            "filesystem_server": {
                "transport": "stdio",
                "command": mcp_config.command,
                "args": mcp_config.args
            }
        }
        if mcp_config.cwd:
            mcp_server_config["filesystem_server"]["cwd"] = mcp_config.cwd
    else:
        # Configure HTTP MCP server (original logic)
        server_url = mcp_config.url.rstrip("/") + "/mcp"

        # Configure authentication headers if tokens are available
        auth_headers = None
        if mcp_tokens:
            auth_headers = {"Authorization": f"Bearer {mcp_tokens['access_token']}"}

        mcp_server_config = {
            "server_1": {
                "url": server_url,
                "headers": auth_headers,
                "transport": "streamable_http"
            }
        }
    # TODO: When Multi-MCP Server support is merged in OAP, update this code
    
    # Step 4: Load tools from MCP server using resource pool
    try:
        import asyncio
        import time
        import json
        import hashlib
        from datetime import datetime

        # Create a cache key based on MCP server config
        config_json = json.dumps(mcp_server_config, sort_keys=True)
        cache_key = hashlib.md5(config_json.encode()).hexdigest()

        print(f"[{datetime.now()}] 🔌 MCP: Starting MCP pool access (cache_key: {cache_key[:8]}...)")
        start_time = time.time()

        # Get or create a resource pool for this configuration
        global _mcp_client_pools
        if cache_key not in _mcp_client_pools:
            pool_size = _calculate_mcp_pool_size()
            _mcp_client_pools[cache_key] = MCPClientPool(mcp_server_config, pool_size)
            print(f"[{datetime.now()}] 🏊 MCP: Created new pool for cache_key {cache_key[:8]} (total pools: {len(_mcp_client_pools)})")

        pool = _mcp_client_pools[cache_key]

        # Get cached tools from pool (initialized once, reused by all researchers)
        # This avoids stdio contention when multiple researchers request tools simultaneously
        available_mcp_tools = await pool.get_cached_tools()

        # Attach pool reference to each tool for later acquire/release during tool calls
        for tool in available_mcp_tools:
            tool._mcp_pool = pool

    except asyncio.TimeoutError:
        print(f"[{datetime.now()}] ⚠️  MCP: Pool access timed out")
        warnings.warn(
            f"MCP pool access timed out - skipping MCP tools"
        )
        return []
    except Exception as e:
        # If MCP server connection fails, return empty list
        print(f"[{datetime.now()}] ❌ MCP: Connection failed: {str(e)}")
        warnings.warn(
            f"MCP server connection failed: {str(e)} - skipping MCP tools"
        )
        return []
    
    # Step 5: Filter and configure tools
    configured_tools = []
    for mcp_tool in available_mcp_tools:
        # Skip tools with conflicting names
        if mcp_tool.name in existing_tool_names:
            warnings.warn(
                f"MCP tool '{mcp_tool.name}' conflicts with existing tool name - skipping"
            )
            continue
        
        # Only include tools specified in configuration
        if mcp_tool.name not in set(mcp_config.tools):
            continue
        
        # Wrap tool with authentication handling and add to list
        enhanced_tool = wrap_mcp_authenticate_tool(mcp_tool)
        configured_tools.append(enhanced_tool)
    
    return configured_tools


##########################
# Tool Utils
##########################

async def get_search_tool(search_api: SearchAPI):
    """Configure and return search tools based on the specified API provider.
    
    Args:
        search_api: The search API provider to use (Anthropic, OpenAI, Tavily, or None)
        
    Returns:
        List of configured search tool objects for the specified provider
    """
    if search_api == SearchAPI.ANTHROPIC:
        # Anthropic's native web search with usage limits
        return [{
            "type": "web_search_20250305", 
            "name": "web_search", 
            "max_uses": 5
        }]
        
    elif search_api == SearchAPI.OPENAI:
        # OpenAI's web search preview functionality
        return [{"type": "web_search_preview"}]
        
    elif search_api == SearchAPI.TAVILY:
        # Configure Tavily search tool with metadata
        search_tool = tavily_search
        search_tool.metadata = {
            **(search_tool.metadata or {}), 
            "type": "search", 
            "name": "web_search"
        }
        return [search_tool]
        
    elif search_api == SearchAPI.NONE:
        # No search functionality configured
        return []
        
    # Default fallback for unknown search API types
    return []
    
async def get_all_tools(config: RunnableConfig):
    """Assemble complete toolkit including research, search, and MCP tools.
    
    Args:
        config: Runtime configuration specifying search API and MCP settings
        
    Returns:
        List of all configured and available tools for research operations
    """
    # Start with core research tools
    tools = [tool(ResearchComplete), think_tool]
    
    # Add configured search tools
    configurable = Configuration.from_runnable_config(config)
    search_api = SearchAPI(get_config_value(configurable.search_api))
    search_tools = await get_search_tool(search_api)
    tools.extend(search_tools)
    
    # Track existing tool names to prevent conflicts
    existing_tool_names = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search") 
        for tool in tools
    }
    
    # Add MCP tools if configured
    mcp_tools = await load_mcp_tools(config, existing_tool_names)
    tools.extend(mcp_tools)
    
    return tools

def get_notes_from_tool_calls(messages: list[MessageLikeRepresentation]):
    """Extract notes from tool call messages."""
    return [tool_msg.content for tool_msg in filter_messages(messages, include_types="tool")]

##########################
# Model Provider Native Websearch Utils
##########################

def anthropic_websearch_called(response):
    """Detect if Anthropic's native web search was used in the response.
    
    Args:
        response: The response object from Anthropic's API
        
    Returns:
        True if web search was called, False otherwise
    """
    try:
        # Navigate through the response metadata structure
        usage = response.response_metadata.get("usage")
        if not usage:
            return False
        
        # Check for server-side tool usage information
        server_tool_use = usage.get("server_tool_use")
        if not server_tool_use:
            return False
        
        # Look for web search request count
        web_search_requests = server_tool_use.get("web_search_requests")
        if web_search_requests is None:
            return False
        
        # Return True if any web search requests were made
        return web_search_requests > 0
        
    except (AttributeError, TypeError):
        # Handle cases where response structure is unexpected
        return False

def openai_websearch_called(response):
    """Detect if OpenAI's web search functionality was used in the response.
    
    Args:
        response: The response object from OpenAI's API
        
    Returns:
        True if web search was called, False otherwise
    """
    # Check for tool outputs in the response metadata
    tool_outputs = response.additional_kwargs.get("tool_outputs")
    if not tool_outputs:
        return False
    
    # Look for web search calls in the tool outputs
    for tool_output in tool_outputs:
        if tool_output.get("type") == "web_search_call":
            return True
    
    return False


##########################
# Token Limit Exceeded Utils
##########################

def is_token_limit_exceeded(exception: Exception, model_name: str = None) -> bool:
    """Determine if an exception indicates a token/context limit was exceeded.
    
    Args:
        exception: The exception to analyze
        model_name: Optional model name to optimize provider detection
        
    Returns:
        True if the exception indicates a token limit was exceeded, False otherwise
    """
    error_str = str(exception).lower()
    
    # Step 1: Determine provider from model name if available
    provider = None
    if model_name:
        model_str = str(model_name).lower()
        if model_str.startswith('openai:'):
            provider = 'openai'
        elif model_str.startswith('anthropic:'):
            provider = 'anthropic'
        elif model_str.startswith('gemini:') or model_str.startswith('google:'):
            provider = 'gemini'
    
    # Step 2: Check provider-specific token limit patterns
    if provider == 'openai':
        return _check_openai_token_limit(exception, error_str)
    elif provider == 'anthropic':
        return _check_anthropic_token_limit(exception, error_str)
    elif provider == 'gemini':
        return _check_gemini_token_limit(exception, error_str)
    
    # Step 3: If provider unknown, check all providers
    return (
        _check_openai_token_limit(exception, error_str) or
        _check_anthropic_token_limit(exception, error_str) or
        _check_gemini_token_limit(exception, error_str)
    )

def _check_openai_token_limit(exception: Exception, error_str: str) -> bool:
    """Check if exception indicates OpenAI token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is an OpenAI exception
    is_openai_exception = (
        'openai' in exception_type.lower() or 
        'openai' in module_name.lower()
    )
    
    # Check for typical OpenAI token limit error types
    is_request_error = class_name in ['BadRequestError', 'InvalidRequestError']
    
    if is_openai_exception and is_request_error:
        # Look for token-related keywords in error message
        token_keywords = ['token', 'context', 'length', 'maximum context', 'reduce']
        if any(keyword in error_str for keyword in token_keywords):
            return True
    
    # Check for specific OpenAI error codes
    if hasattr(exception, 'code') and hasattr(exception, 'type'):
        error_code = getattr(exception, 'code', '')
        error_type = getattr(exception, 'type', '')
        
        if (error_code == 'context_length_exceeded' or
            error_type == 'invalid_request_error'):
            return True
    
    return False

def _check_anthropic_token_limit(exception: Exception, error_str: str) -> bool:
    """Check if exception indicates Anthropic token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is an Anthropic exception
    is_anthropic_exception = (
        'anthropic' in exception_type.lower() or 
        'anthropic' in module_name.lower()
    )
    
    # Check for Anthropic-specific error patterns
    is_bad_request = class_name == 'BadRequestError'
    
    if is_anthropic_exception and is_bad_request:
        # Anthropic uses specific error messages for token limits
        if 'prompt is too long' in error_str:
            return True
    
    return False

def _check_gemini_token_limit(exception: Exception, error_str: str) -> bool:
    """Check if exception indicates Google/Gemini token limit exceeded."""
    # Analyze exception metadata
    exception_type = str(type(exception))
    class_name = exception.__class__.__name__
    module_name = getattr(exception.__class__, '__module__', '')
    
    # Check if this is a Google/Gemini exception
    is_google_exception = (
        'google' in exception_type.lower() or 
        'google' in module_name.lower()
    )
    
    # Check for Google-specific resource exhaustion errors
    is_resource_exhausted = class_name in [
        'ResourceExhausted', 
        'GoogleGenerativeAIFetchError'
    ]
    
    if is_google_exception and is_resource_exhausted:
        return True
    
    # Check for specific Google API resource exhaustion patterns
    if 'google.api_core.exceptions.resourceexhausted' in exception_type.lower():
        return True
    
    return False

# NOTE: This may be out of date or not applicable to your models. Please update this as needed.
MODEL_TOKEN_LIMITS = {
    "openai:gpt-4.1-mini": 1047576,
    "openai:gpt-4.1-nano": 1047576,
    "openai:gpt-4.1": 1047576,
    "openai:gpt-4o-mini": 128000,
    "openai:gpt-4o": 128000,
    "openai:o4-mini": 200000,
    "openai:o3-mini": 200000,
    "openai:o3": 200000,
    "openai:o3-pro": 200000,
    "openai:o1": 200000,
    "openai:o1-pro": 200000,
    "anthropic:claude-opus-4": 200000,
    "anthropic:claude-sonnet-4": 200000,
    "anthropic:claude-3-7-sonnet": 200000,
    "anthropic:claude-3-5-sonnet": 200000,
    "anthropic:claude-3-5-haiku": 200000,
    "google:gemini-1.5-pro": 2097152,
    "google:gemini-1.5-flash": 1048576,
    # DeepSeek models
    "deepseek-chat": 128000,
    "deepseek-reasoner": 128000,
    "deepseek:chat": 128000,
    "deepseek:reasoning": 128000,
    # Qwen models
    "qwen-plus": 128000,
    "qwen-flash": 128000,
    "qwen:plus": 128000,
    "qwen:flash": 128000,
    "qwen:plus-think": 128000,
    "qwen:flash-think": 128000,
    "google:gemini-pro": 32768,
    "cohere:command-r-plus": 128000,
    "cohere:command-r": 128000,
    "cohere:command-light": 4096,
    "cohere:command": 4096,
    "mistral:mistral-large": 32768,
    "mistral:mistral-medium": 32768,
    "mistral:mistral-small": 32768,
    "mistral:mistral-7b-instruct": 32768,
    "ollama:codellama": 16384,
    "ollama:llama2:70b": 4096,
    "ollama:llama2:13b": 4096,
    "ollama:llama2": 4096,
    "ollama:mistral": 32768,
    "bedrock:us.amazon.nova-premier-v1:0": 1000000,
    "bedrock:us.amazon.nova-pro-v1:0": 300000,
    "bedrock:us.amazon.nova-lite-v1:0": 300000,
    "bedrock:us.amazon.nova-micro-v1:0": 128000,
    "bedrock:us.anthropic.claude-3-7-sonnet-20250219-v1:0": 200000,
    "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0": 200000,
    "bedrock:us.anthropic.claude-opus-4-20250514-v1:0": 200000,
    "anthropic.claude-opus-4-1-20250805-v1:0": 200000,
}

def get_model_token_limit(model_string):
    """Look up the token limit for a specific model.
    
    Args:
        model_string: The model identifier string to look up
        
    Returns:
        Token limit as integer if found, None if model not in lookup table
    """
    # Search through known model token limits
    for model_key, token_limit in MODEL_TOKEN_LIMITS.items():
        if model_key in model_string:
            return token_limit
    
    # Model not found in lookup table
    return None

def remove_up_to_last_ai_message(messages: list[MessageLikeRepresentation]) -> list[MessageLikeRepresentation]:
    """Truncate message history by removing up to the last AI message.
    
    This is useful for handling token limit exceeded errors by removing recent context.
    
    Args:
        messages: List of message objects to truncate
        
    Returns:
        Truncated message list up to (but not including) the last AI message
    """
    # Search backwards through messages to find the last AI message
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            # Return everything up to (but not including) the last AI message
            return messages[:i]
    
    # No AI messages found, return original list
    return messages

##########################
# Misc Utils
##########################

def get_today_str() -> str:
    """Get current date formatted for display in prompts and outputs.
    
    Returns:
        Human-readable date string in format like 'Mon Jan 15, 2024'
    """
    now = datetime.now()
    return f"{now:%a} {now:%b} {now.day}, {now:%Y}"

def get_config_value(value):
    """Extract value from configuration, handling enums and None values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    elif isinstance(value, dict):
        return value
    else:
        return value.value

def get_api_key_for_model(model_name: str, config: RunnableConfig):
    """Get API key for a specific model from environment or config."""
    should_get_from_config = os.getenv("GET_API_KEYS_FROM_CONFIG", "false")
    model_name = model_name.lower()
    if should_get_from_config.lower() == "true":
        api_keys = config.get("configurable", {}).get("apiKeys", {})
        if not api_keys:
            return None
        if model_name.startswith("openai:"):
            return api_keys.get("OPENAI_API_KEY")
        elif model_name.startswith("anthropic:"):
            return api_keys.get("ANTHROPIC_API_KEY")
        elif model_name.startswith("google"):
            return api_keys.get("GOOGLE_API_KEY")
        elif model_name.startswith("qwen:"):
            return api_keys.get("QWEN_API_KEY")
        elif model_name.startswith("deepseek:"):
            return api_keys.get("DEEPSEEK_API_KEY")
        return None
    else:
        if model_name.startswith("openai:"):
            return os.getenv("OPENAI_API_KEY")
        elif model_name.startswith("anthropic:"):
            return os.getenv("ANTHROPIC_API_KEY")
        elif model_name.startswith("google"):
            return os.getenv("GOOGLE_API_KEY")
        elif model_name.startswith(("qwen-", "qwen:")):
            return os.getenv("QWEN_API_KEY")
        elif model_name.startswith(("deepseek-", "deepseek:")):
            return os.getenv("DEEPSEEK_API_KEY")
        return None

def get_model_config(model_name: str) -> dict:
    """Get model configuration for Qwen and DeepSeek models."""
    model_name = model_name.lower()

    # Qwen 模型配置
    if model_name.startswith("qwen-"):
        config = {
            "model": model_name,
            "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        }
        return config

    # DeepSeek 模型配置
    elif model_name.startswith("deepseek-"):
        config = {
            "model": model_name,
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        }
        return config

    return {}

# 保持向后兼容
def get_qwen_model_config(model_name: str) -> dict:
    """Get Qwen model configuration - deprecated, use get_model_config instead."""
    return get_model_config(model_name)

def get_tavily_api_key(config: RunnableConfig):
    """Get Tavily API key from environment or config."""
    should_get_from_config = os.getenv("GET_API_KEYS_FROM_CONFIG", "false")
    if should_get_from_config.lower() == "true":
        api_keys = config.get("configurable", {}).get("apiKeys", {})
        if not api_keys:
            return None
        return api_keys.get("TAVILY_API_KEY")
    else:
        return os.getenv("TAVILY_API_KEY")
