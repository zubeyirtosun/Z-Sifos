import asyncio
import logging
import json
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

class MCPClient:
    """
    A client to interact with MCP servers via stdio.
    """
    def __init__(self, command: str, args: List[str] = None, env: Dict[str, str] = None):
        self.server_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env
        )
        self.session: Optional[ClientSession] = None
        self._exit_stack = None

    async def connect(self):
        """Pre-connect to the server if needed, though we usually use the context manager."""
        logger.info(f"Connecting to MCP server: {self.server_params.command} {' '.join(self.server_params.args)}")
        
    @asynccontextmanager
    async def get_session(self):
        try:
            async with asyncio.timeout(10.0): # 10s connection timeout
                async with stdio_client(self.server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        yield session
        except (asyncio.TimeoutError, Exception) as e:
            logger.error(f"MCP server {self.server_params.command} connection failed: {e}")
            yield None

    async def list_tools(self) -> List[Dict[str, Any]]:
        try:
            async with self.get_session() as session:
                if not session:
                    return []
                result = await session.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.inputSchema
                    }
                    for tool in result.tools
                ]
        except Exception as e:
            logger.error(f"Failed to list tools from MCP server {self.server_params.command}: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        try:
            async with self.get_session() as session:
                if not session:
                    return {"error": "MCP session unavailable"}
                async with asyncio.timeout(30.0): # 30s execution timeout
                    result = await session.call_tool(tool_name, arguments)
                    return result.content
        except asyncio.TimeoutError:
            logger.error(f"MCP tool {tool_name} call timed out.")
            return {"error": "Timeout"}
        except Exception as e:
            logger.error(f"Failed to call tool {tool_name} on MCP server {self.server_params.command}: {e}")
            return {"error": str(e)}
