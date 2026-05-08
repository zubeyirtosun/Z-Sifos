import os
from typing import List, Dict, Any
from .client import MCPClient

# Configuration for free/open-source MCP servers
# We focus on search and data extraction as requested by the user.

MCP_SERVERS_CONFIG = [
    {
        "id": "duckduckgo",
        "command": "npx",
        "args": ["-y", "duckduckgo-mcp-server"],
        "enabled": True,
        "description": "Popular community DuckDuckGo search server (Free)"
    },
    # We can add more here later, e.g. wikipedia, github (if user provides token), etc.
]

def get_enabled_mcp_clients() -> List[MCPClient]:
    clients = []
    for config in MCP_SERVERS_CONFIG:
        if config.get("enabled", True):
            clients.append(
                MCPClient(
                    command=config["command"],
                    args=config["args"],
                    env=os.environ.copy()
                )
            )
    return clients
