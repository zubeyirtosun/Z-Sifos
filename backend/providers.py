import os
import asyncio
import requests
import json
from typing import List, Dict, Any, Generator, AsyncIterator
from langchain_ollama import ChatOllama
from langchain_community.llms import LlamaCpp
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
import httpx

OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434")

class ModelProvider:
    """Base class for all model providers."""
    def get_llm(self, model_name: str):
        raise NotImplementedError

class OllamaProvider(ModelProvider):
    def get_llm(self, model_name: str):
        return ChatOllama(
            model=model_name,
            temperature=0.3, # Slightly lower for stability
            base_url=OLLAMA_API_URL,
            timeout=120.0,
            num_ctx=2048,
            repeat_penalty=1.2, # Slightly higher for small models
            stop=["</thought>", "</call>", "Observation:", "\nUser:", "\nHuman:"]
        )

class LlamaCppProvider(ModelProvider):
    def get_llm(self, model_name: str):
        if not model_name:
            raise ValueError("LlamaCpp provider requires a GGUF model path as model_name.")
        if os.path.exists(model_name) or model_name.endswith(".gguf"):
            return LlamaCpp(model_path=model_name, temperature=0.7)
        raise ValueError("LlamaCpp provider expects a GGUF model file path.")

# Global cache for LLM instances to prevent the overhead of recreation
_LLM_CACHE: Dict[str, Any] = {}

def get_provider_llm(provider_name: str, model_name: str):
    cache_key = f"{provider_name}:{model_name}"
    if cache_key in _LLM_CACHE:
        return _LLM_CACHE[cache_key]

    llm = None
    if provider_name.lower() == "ollama":
        # Use custom wrapper for Qwen models (they have thinking mode)
        if "qwen" in model_name.lower():
            llm = AsyncOllamaWithThinking(
                model=model_name,
                base_url=OLLAMA_API_URL,
                temperature=0.3,
                num_ctx=2048,
                repeat_penalty=1.2,
            )
        else:
            llm = OllamaProvider().get_llm(model_name)
    elif provider_name.lower() in {"llamacpp", "llama_cpp"}:
        llm = LlamaCppProvider().get_llm(model_name)
    
    if llm:
        _LLM_CACHE[cache_key] = llm
        return llm
        
    raise ValueError(f"Bilinmeyen provider: {provider_name}")

def get_model_info(model_name: str, provider: str) -> Dict[str, Any]:
    """Model hakkında teknik detayları döner (size, context vb)."""
    if provider.lower() == "ollama":
        try:
            resp = requests.post(f"{OLLAMA_API_URL}/api/show", json={"name": model_name}, timeout=5)
            if resp.ok:
                data = resp.json()
                details = data.get("details", {})
                params = data.get("parameters", "")
                # Basit bir parsing ile context'i bulmaya çalış
                context = "4096 (Default)"
                if "num_ctx" in params:
                    context = params.split("num_ctx")[1].split("\n")[0].strip()
                
                return {
                    "size": details.get("parameter_size", "Unknown"),
                    "format": details.get("format", "Unknown"),
                    "family": details.get("family", "Unknown"),
                    "context": context
                }
        except Exception: pass
    
    elif provider.lower() in ["llamacpp", "hf"]:
        # HF API'den basitçe çek
        try:
            resp = requests.get(f"https://huggingface.co/api/models/{model_name}", timeout=5)
            if resp.ok:
                data = resp.json()
                return {
                    "size": f"{data.get('downloads', 0)} downloads",
                    "format": "GGUF",
                    "context": "Varies by GGUF"
                }
        except Exception: pass
        
    return {"size": "Unknown", "context": "Unknown"}

def pull_model_stream(model_name: str, provider: str) -> Generator[str, None, None]:
    """Model indirme sürecini SSE stream olarak döner."""
    if provider.lower() == "ollama":
        url = f"{OLLAMA_API_URL}/api/pull"
        try:
            with requests.post(url, json={"name": model_name}, stream=True, timeout=None) as r:
                for line in r.iter_lines():
                    if line:
                        data = json.loads(line)
                        status = data.get("status", "")
                        completed = data.get("completed", 0)
                        total = data.get("total", 0)
                        percentage = 0
                        if total > 0:
                            percentage = int((completed / total) * 100)
                        
                        yield f"data: {json.dumps({'status': status, 'percentage': percentage})}\n\n"
                        if status == "success":
                            break
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
    else:
        yield f"data: {json.dumps({'status': 'error', 'message': 'Only Ollama pull is supported via API for now.'})}\n\n"

def get_provider_models(provider_name: str) -> List[str]:
    """Yüklü modelleri listeler."""
    if provider_name.lower() == "ollama":
        try:
            resp = requests.get(f"{OLLAMA_API_URL}/api/tags", timeout=5)
            if resp.ok:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception: pass
        return ["llama3.2:1b", "phi3"]
    return ["/models/default.gguf"]

def get_provider_library(provider_name: str) -> List[Dict[str, Any]]:
    """Kütüphaneden keşfedilecek popüler modelleri döner."""
    if provider_name.lower() == "ollama":
        # Popüler Ollama modelleri (İndirilmemiş olabilirler)
        return [
            {"name": "llama3.2", "description": "Meta's latest Llama 3.2 (3B)", "size": "2.0GB"},
            {"name": "llama3.2:1b", "description": "Llama 3.2 ultra-lightweight (1B)", "size": "1.3GB"},
            {"name": "mistral", "description": "Mistral 7B - High performance", "size": "4.1GB"},
            {"name": "phi3", "description": "Microsoft Phi-3 Mini (3.8B)", "size": "2.3GB"},
            {"name": "gemma2:2b", "description": "Google Gemma 2 (2B)", "size": "1.6GB"},
            {"name": "codellama", "description": "Meta Code Llama for coding", "size": "3.8GB"},
            {"name": "neural-chat", "description": "Intel's fine-tuned Mistral", "size": "4.1GB"},
            {"name": "qwen2:0.5b", "description": "Alibaba Qwen 2 ultra-small", "size": "352MB"}
        ]
    elif provider_name.lower() in ["llamacpp", "hf"]:
        try:
            # Hugging Face GGUF modellerini ara
            url = "https://huggingface.co/api/models?library=gguf&sort=downloads&direction=-1&limit=20"
            resp = requests.get(url, timeout=10)
            if resp.ok:
                return [
                    {
                        "name": m["id"], 
                        "description": f"Downloads: {m.get('downloads', 0)}", 
                        "size": "GGUF Format"
                    } for m in resp.json()
                ]
        except Exception as e:
            print(f"HF Search Error: {e}")
    return []

def get_provider_metadata():
    return [
        {"name": "ollama", "label": "Ollama", "description": "Local Ollama models wrapper."},
        {"name": "llamacpp", "label": "LlamaCpp / HF", "description": "Local GGUF models or HF models."}
    ]

def check_ollama_status() -> Dict[str, Any]:
    """Ollama servisinin çalışıp çalışmadığını kontrol eder. /api/tags kontrolü daha güvenilirdir."""
    try:
        # Root yerine /api/tags kontrolü yapalım, daha kesin sonuç verir
        resp = requests.get(f"{OLLAMA_API_URL}/api/tags", timeout=2)
        is_online = resp.ok
        return {
            "running": is_online,
            "installed": True, # Yanıt geliyorsa kurulu ve çalışıyordur
            "status": "online" if is_online else "offline",
            "url": OLLAMA_API_URL
        }
    except Exception as e:
        # Bağlantı reddedildiyse veya hata varsa
        return {
            "running": False,
            "installed": False, 
            "status": "offline",
            "error": str(e),
            "url": OLLAMA_API_URL
        }


class AsyncOllamaWithThinking:
    """Custom async Ollama wrapper that handles Qwen thinking mode."""
    
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", **kwargs):
        self.model = model
        self.model_name = model  # For compatibility with agent code
        self.base_url = base_url
        self.kwargs = kwargs
    
    async def astream(self, messages: List[BaseMessage]) -> AsyncIterator[Any]:
        """Stream response, extracting thinking field for Qwen models."""
        url = f"{self.base_url}/api/chat"
        
        # Convert langchain messages to Ollama format
        ollama_messages = []
        role_map = {"human": "user", "ai": "assistant", "system": "system"}
        for msg in messages:
            if hasattr(msg, "content"):
                role = role_map.get(msg.type, msg.type)
                content = msg.content
                
                # Handle dict content from agent (e.g., {"type": "text", "text": "..."})
                if isinstance(content, dict):
                    content = content.get("text", str(content))
                elif isinstance(content, list):
                    # Handle list content (for vision)
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            text_parts.append(item.get("text", ""))
                        else:
                            text_parts.append(str(item))
                    content = " ".join(text_parts)
                
                ollama_messages.append({"role": role, "content": content})
        
        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": self.kwargs.get("temperature", 0.3),
                "num_ctx": self.kwargs.get("num_ctx", 2048),
                "repeat_penalty": self.kwargs.get("repeat_penalty", 1.2),
            }
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        msg_data = data.get("message", {})
                        
                        # Extract content - prioritize content, fall back to thinking
                        content = msg_data.get("content", "")
                        thinking = msg_data.get("thinking", "")
                        
                        # Use thinking if content is empty (Qwen thinking mode)
                        if not content and thinking:
                            content = thinking
                        
                        if content:
                            # Create a simple object that mimics langchain's chunk
                            class Chunk:
                                def __init__(self, content):
                                    self.content = content
                            yield Chunk(content)
                            
                    except json.JSONDecodeError:
                        continue
