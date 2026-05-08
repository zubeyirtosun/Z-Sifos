import asyncio
import re
import logging
from typing import List, Dict, Any, Callable, Optional, Type
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
import httpx
from duckduckgo_search import DDGS
from backend.http_client import HttpClientManager

logger = logging.getLogger(__name__)

class BaseTool:
    """
    Standardize tool definition with validation, discovery hints, and execution logic.
    """
    name: str = ""
    description: str = ""
    search_hints: List[str] = [] # Keywords/sentences for intent classification
    input_schema: Optional[Type[BaseModel]] = None

    async def execute_async(self, **kwargs) -> Any:
        raise NotImplementedError("Each tool must implement its own execute_async method.")

    def execute(self, **kwargs) -> Any:
        return asyncio.run(self.execute_async(**kwargs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "search_hints": self.search_hints,
            "input_schema": self.input_schema.model_json_schema() if self.input_schema else None
        }

# --- Standardized Tools ---

class SearchInput(BaseModel):
    query: str = Field(..., description="Arama yapılacak terim veya cümle")
    max_results: int = Field(default=3, description="Dönülecek maksimum sonuç sayısı")

class WebSearchTool(BaseTool):
    name = "search"
    description = "Herhangi bir konu hakkında internette genel arama yapar. Güncel bilgiler ve linkler sağlar."
    search_hints = ["Bugün hava nasıl?", "En son haberler neler?", "İnternette ara", "Search the web", "Latest news"]
    input_schema = SearchInput

    async def execute_async(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        try:
            def sync_search():
                with DDGS() as ddgs:
                    # In v6.x, .text() returns a generator of results
                    return list(ddgs.text(query, max_results=max_results))
            
            raw_results = await asyncio.to_thread(sync_search)
            results = []
            for r in raw_results:
                results.append({
                    "title": r.get("title", ""),
                    "link": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

class ScrapeInput(BaseModel):
    urls: List[str] = Field(..., description="Okunacak URL listesi")
    query: Optional[str] = Field(default="", description="İçerik içinde aranacak anahtar kelime veya soru")

class WebScrapeTool(BaseTool):
    name = "scrape"
    description = "Belirli bir web sitesinin içeriğini okumak için kullanılır. Link listesi alır."
    search_hints = ["Bu linkte ne yazıyor?", "Sayfayı oku", "Web sitesini incele", "Scrape the website"]
    input_schema = ScrapeInput

    async def execute_async(self, urls: List[str], query: str = "", max_chars: int = 1500) -> str:
        if not urls:
            return ""

        keywords = set(re.findall(r'\w{4,}', query.lower())) if query else set()
        client = await HttpClientManager.get_client()

        async def fetch_content(url: str) -> str:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                # Use a specific timeout for EACH site to prevent one site from blocking others
                response = await client.get(url, headers=headers, timeout=10.0, follow_redirects=True)
                if response.status_code != 200:
                    return f"URL: {url} (Hata: {response.status_code})"
                
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
                    tag.decompose()
                    
                paragraphs = [p.get_text(strip=True) for p in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'li']) if len(p.get_text()) > 40]
                
                if keywords and paragraphs:
                    scored = sorted([(sum(1 for k in keywords if k in p.lower()), p) for p in paragraphs], key=lambda x: x[0], reverse=True)
                    selected = []
                    curr_len = 0
                    for score, p in scored:
                        if score > 0 or not selected:
                            selected.append(p)
                            curr_len += len(p)
                            if curr_len >= max_chars: break
                    text = " ".join(selected)
                else:
                    text = " ".join(paragraphs)

                return f"--- SOURCE: {url} ---\nCONTENT: {text[:max_chars]}...\n"
            except Exception as e:
                return f"URL: {url} (Error: {str(e)})"

        # Use TaskGroup for high performance parallel scraping
        tasks = []
        async with asyncio.TaskGroup() as tg:
            for url in urls:
                tasks.append(tg.create_task(fetch_content(url)))
        
        results = [t.result() for t in tasks]
        return "\n".join(results)

# --- Registry ---

class MCPTool(BaseTool):
    """
    Wraps an external tool discovered via MCP.
    """
    def __init__(self, name: str, description: str, client: Any, input_schema_dict: Dict[str, Any] = None):
        self.name = name
        self.description = description
        self.client = client
        # Schema conversion could be more complex, but for now we store the dict
        self.schema_dict = input_schema_dict

    async def execute_async(self, **kwargs) -> Any:
        return await self.client.call_tool(self.name, kwargs)

    def execute(self, **kwargs) -> Any:
        # Compatibility for synchronous callers
        return asyncio.run(self.execute_async(**kwargs))

TOOL_REGISTRY: Dict[str, BaseTool] = {
    "search": WebSearchTool(),
    "scrape": WebScrapeTool()
}

def get_internet_tools(mcp_enabled: bool = True):
    """Compatibility layer for existing code."""
    # This remains sync for now to avoid breaking existing specialist nodes
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "func": tool.execute
        } for name, tool in TOOL_REGISTRY.items()
        if mcp_enabled or not name.startswith("mcp_")
    ]

async def sync_mcp_tools():
    """Discovers tools from enabled MCP servers and adds them to registry."""
    from .mcp.servers import get_enabled_mcp_clients
    clients = get_enabled_mcp_clients()
    for client in clients:
        tools = await client.list_tools()
        for t in tools:
            # We prefix mcp tools to avoid name collisions
            mcp_name = f"mcp_{t['name']}"
            TOOL_REGISTRY[mcp_name] = MCPTool(
                name=t['name'],
                description=t['description'],
                client=client,
                input_schema_dict=t.get('input_schema')
            )
            logger.info(f"Registered MCP tool: {mcp_name}")

