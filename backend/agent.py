import json
import re
import time
import logging
from typing import Generator, Optional, List, Dict, Any, Tuple
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from backend.providers import get_provider_llm
from backend.plugins import PluginManager
from backend.tools import get_internet_tools
from backend.intelligence.orchestrator import orchestrator
import logging
import asyncio

# ---------------------------------------------------------------------------
# AdaptivePromptLayer
# ---------------------------------------------------------------------------

def _parse_param_billions(param_size_str: str) -> float:
    """Parse model param string like '1.5B', '7B', '405M' → float (in billions)."""
    if not param_size_str or param_size_str == "Unknown":
        return 0.0
    s = param_size_str.strip().upper()
    try:
        if s.endswith("B"):
            return float(s[:-1])
        if s.endswith("M"):
            return float(s[:-1]) / 1000.0
        return float(s)
    except ValueError:
        return 0.0


def determine_agent_mode(
    model_metadata: Optional[str] = None,
    provider: str = "ollama",
    model_name: str = "",
    override: Optional[str] = None,
) -> str:
    """
    Priority: override > model_metadata > live Ollama query > STANDARD default.
    """
    VALID_MODES = {"STRICT", "STANDARD", "ENHANCED"}

    if override and override.upper() in VALID_MODES:
        return override.upper()

    if model_metadata:
        try:
            meta = json.loads(model_metadata)
            params = _parse_param_billions(meta.get("size", ""))
            if params > 0:
                if params <= 2.0:
                    return "STRICT"
                if params <= 8.0:
                    return "STANDARD"
                return "ENHANCED"
        except Exception:
            pass

    if provider.lower() == "ollama" and model_name:
        try:
            import requests as _req
            import os as _os
            ollama_url = _os.environ.get("OLLAMA_API_URL", "http://127.0.0.1:11434")
            resp = _req.post(
                f"{ollama_url}/api/show",
                json={"name": model_name},
                timeout=3,
            )
            if resp.ok:
                data = resp.json()
                size_str = data.get("details", {}).get("parameter_size", "")
                params = _parse_param_billions(size_str)
                if params > 0:
                    if params <= 2.0:
                        return "STRICT"
                    if params <= 8.0:
                        return "STANDARD"
                    return "ENHANCED"
        except Exception:
            pass

    return "STANDARD"


# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

_FEW_SHOT_STRICT = """
Examples:
- 2+2 = 4
- Paris = France capital
- Use <call:search>query</call> if you need current info.
Answer directly.""".strip()

# Ultra-light prompt for very small models (<1B params)
_LIGHTWEIGHT_STRICT_PROMPT = """Answer these rules:
- Be SHORT. 
- If you don't know, say "I don't know".
- Don't use tags. Just answer.
- Example: "2+2 = 4"
- Example: "Paris" for "capital of France"
Answer now:""".strip()

def _build_system_prompt(tools: Dict[str, Any], mode: str, internet_enabled: bool, model_name: str = "") -> str:
    # Ultra-light mode detection for very small models (<1B params)
    is_tiny_model = any(x in (model_name or "").lower() for x in ["0.8b", "0.5b", "1b", "tiny", "mini"])
    
    if is_tiny_model and mode == "STRICT":
        return _LIGHTWEIGHT_STRICT_PROMPT
    
    tool_desc = ""
    if internet_enabled and tools:
        tool_lines = [f"- {t['name']}: {t['description']}" for t in tools.values()]
        tool_desc = "AVAILABLE TOOLS:\n" + "\n".join(tool_lines)

    internet_rule = (
        "5. For questions about specific people, movies, events, news, prices, or current data:\n"
        "   - If internet is enabled: ALWAYS search first.\n"
        "   - If internet is disabled: say 'I cannot verify this without internet access. My training data may be outdated or inaccurate.'\n"
        "   - NEVER invent names, dates, or facts you are not 100% certain about.\n"
    ) if not internet_enabled else (
        "5. For questions about specific people, movies, events, news — ALWAYS use the 'search' tool.\n"
        "   Do NOT answer from memory for factual questions about real-world entities. Verify first.\n"
    )

    # Only include XML tag format instructions when tools are actually available.
    # When tools are disabled, the model MUST answer directly without any tags.
    if internet_enabled and tools:
        format_rule = (
            "- **FORMAT:** When using tools, wrap reasoning in <thought>...</thought> and tool calls in <call:TOOL_NAME>...</call>.\n"
            "- Anything OUTSIDE these tags is your FINAL ANSWER — stream it directly.\n"
        )
    else:
        format_rule = (
            "- **FORMAT:** Reply DIRECTLY. Do NOT use any XML tags like <thought> or <call>.\n"
            "- Just write your answer in plain text.\n"
        )

    base = (
        "You are a helpful AI Assistant. Always respond in the SAME LANGUAGE as the user.\n\n"
        "## RULES:\n"
        "- NEVER invent information. If you are not certain, say so clearly.\n"
        "- For facts you are 100% certain about (definitions, math, well-known science): reply DIRECTLY.\n"
        "- If you don't know something, say 'I don't know' instead of guessing.\n"
        f"{format_rule}"
        f"{internet_rule}"
        "- Rely on conversation history for context.\n"
    )

    if mode == "STRICT":
        # Only suggest enabling internet if it's currently DISABLED
        uncertain_msg = (
            "say 'I'm not sure about this. Please enable internet search for accurate information.'"
            if not internet_enabled else
            "ALWAYS use the 'search' tool to find the answer. DO NOT GUESS."
        )
        directive = (
            "\n## MODE: STRICT (Small Model — ≤2B params)\n"
            "- Give SHORT, DIRECT answers. No lengthy explanations.\n"
            f"- When uncertain about any fact: {uncertain_msg}\n"
            f"\n{_FEW_SHOT_STRICT}\n"
        )
    elif mode == "ENHANCED":
        directive = (
            "\n## MODE: ENHANCED\n"
            "- Provide detailed, well-structured answers with source citations.\n"
            "- Always verify factual claims about real people/events with search when available.\n"
        )
    else:
        directive = (
            "\n## MODE: STANDARD\n"
            "- Give complete, helpful answers.\n"
            "- If uncertain about specific facts, acknowledge it.\n"
        )

    return base + directive + ("\n\n" + tool_desc if tool_desc else "")


# ---------------------------------------------------------------------------
# CustomAgentExecutor
# ---------------------------------------------------------------------------

class CustomAgentExecutor:
    def __init__(
        self,
        llm,
        plugin_manager: PluginManager,
        mode: str = "STANDARD",
    ):
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.mode = mode
        self.all_tools = {t["name"]: t for t in get_internet_tools(mcp_enabled=plugin_manager.context.get("mcp_enabled", True))}
        self.max_iterations = {"STRICT": 3, "STANDARD": 5, "ENHANCED": 7}.get(mode, 5)

    def _extract_tool_call(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract (tool_name, query) from <call:tool_name>query</call>."""
        match = re.search(r"<call:(\w+)>(.*?)</call>", text, re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        match = re.search(r"<call:(\w+)>(.*?)$", text, re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return None

    def _clean_for_display(self, text: str) -> str:
        """Remove internal ReAct tags and junk patterns from final output."""
        # Remove thought tags but extract content for potential fallback
        thought_match = re.search(r"<thought\s*>(.*?)</thought\s*>", text, re.DOTALL | re.IGNORECASE)
        extracted_thought = thought_match.group(1).strip() if thought_match else ""
        
        # Remove thought tags completely (both opening and closing)
        text = re.sub(r"</?thought\s*>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<call:.*?(?:</call\s*>|$)", " ", text, flags=re.DOTALL | re.IGNORECASE)
        
        # If cleaned text is empty but we have extracted thought, use it
        if not text.strip() and extracted_thought:
            return extracted_thought
        text = re.sub(r"Thought:\s*", "", text)
        text = re.sub(r"Action:\s*", "", text)
        text = re.sub(r"Observation:\s*", "", text)
        
        # Remove fake continuation patterns (model hallucinating chat format)
        text = re.sub(r"Verilen.*?konuşmaya\s+devam.*?(?=\S{20,}|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"(Kullanıcı:|Asistan:).*", "", text, flags=re.DOTALL)
        
        # Remove system prompt echoes
        text = re.sub(r"You are a helpful.*?\n+", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"## CRITICAL RULES:.*?\n+", "", text, flags=re.DOTALL)
        
        # Clean multiple spaces
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _prune_context(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Keep system message and adaptive N most recent messages based on mode."""
        # Adaptive windows based on mode to balance context vs speed/token limit
        max_messages = 10  # Default (STRICT)
        if self.mode == "STANDARD":
            max_messages = 15
        elif self.mode == "ENHANCED":
            max_messages = 25

        if len(messages) <= max_messages + 1:
            return messages
        
        system_msg = messages[0] if isinstance(messages[0], SystemMessage) else None
        recent_msgs = messages[-(max_messages):]
        
        if system_msg:
            return [system_msg] + recent_msgs
        return recent_msgs

    async def predict(self, input_text: str, images: Optional[List[str]] = None, planning_mode: bool = False, plan_approved: bool = False) -> str:
        """Non-streaming asynchronous prediction. Returns full response text."""
        full_response = ""
        async for chunk in self.predict_stream(input_text, images=images, planning_mode=planning_mode, plan_approved=plan_approved):
            if chunk["type"] == "token":
                full_response += chunk["content"]
        # Extra cleaning for accumulated response
        full_response = self._clean_for_display(full_response)
        return full_response

    async def predict_stream(
        self, input_text: str, images: Optional[List[str]] = None, planning_mode: bool = False, plan_approved: bool = False
    ) -> Any: # AsyncGenerator[Dict[str, Any], None]
        logger = logging.getLogger(__name__)
        logger.info(f"[AGENT] predict_stream started for: {input_text[:30]}..., mode={self.mode}")
        
        context = {
            "input_text": input_text,
            "original_lang": "en",
            "translated_input": None,
            "agent_mode": self.mode,
        }
        self.plugin_manager.context.update(context)
        self.plugin_manager.init()

        human_content = [{"type": "text", "text": input_text}]
        if images:
            for img_b64 in images:
                human_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{img_b64}"})

        # Fast heuristic intent detection for small models (skip heavy orchestrator)
        graph_updates = {}  # Default empty for STRICT mode
        
        if self.mode == "STRICT":
            detected_intent = "CHAT"
            intent_score = 0.5
            is_factual_intent = False
            
            # Quick keyword check
            user_lower = input_text.lower()
            factual_keywords = ["kim", "ne", "nerede", "nasıl", "kaç", "fiyat", "haber", "who", "what", "where", "when", "how", "price", "news"]
            doc_keywords = ["dosya", "pdf", "döküman", "belge", "document", "file", "yükle"]
            task_keywords = ["kod", "yaz", "hesapla", "çöz", "code", "write", "calculate", "solve"]
            
            for kw in factual_keywords:
                if kw in user_lower:
                    detected_intent = "SEARCH"
                    intent_score = 0.7
                    is_factual_intent = True
                    break
            else:
                for kw in doc_keywords:
                    if kw in user_lower:
                        detected_intent = "DOCUMENT"
                        intent_score = 0.6
                        break
                else:
                    for kw in task_keywords:
                        if kw in user_lower:
                            detected_intent = "TASK"
                            intent_score = 0.6
        else:
            # Standard flow for STANDARD/ENHANCED modes
            initial_state = {
                "messages": [HumanMessage(content=human_content)],
                "intent": "CHAT",
                "intent_score": 0.0,
                "active_expert": "generalist",
                "data_pool": {},
                "final_answer": "",
                "metadata": [],
                "planning_mode": planning_mode,
                "plan_approved": plan_approved,
                "execution_plan": ""
            }
            
            graph_updates = orchestrator.invoke(initial_state)
            detected_intent = graph_updates.get("intent", "CHAT")
            intent_score = graph_updates.get("intent_score", 0.0)
            is_factual_intent = (detected_intent == "SEARCH" and intent_score > 0.45)
        
        # Handle metadata yield (both modes)
        if self.mode != "STRICT":
            for meta in graph_updates.get("metadata", []):
                yield meta
        
        self.plugin_manager.context["detected_intent"] = detected_intent
        self.plugin_manager.context["intent_score"] = intent_score
        self.plugin_manager.context["active_expert"] = graph_updates.get("active_expert", "generalist")

        internet_enabled = self.plugin_manager.context.get("internet_enabled", False)

        messages: List[BaseMessage] = [
            SystemMessage(
                content=_build_system_prompt(
                    self.all_tools if internet_enabled else {},
                    self.mode,
                    internet_enabled,
                    getattr(self.llm, 'model_name', ''),
                )
            )
        ]
        messages = self.plugin_manager.before_prompt(messages)
        user_input = self.plugin_manager.context.get("translated_input") or input_text
        
        # Check if internet was blocked by plugin and notify model
        blocked_reason = self.plugin_manager.context.get("internet_blocked_reason")
        if not internet_enabled and blocked_reason:
            messages.append(SystemMessage(
                content=f"[SYSTEM] Note: Internet access is disabled for this request. Reason: {blocked_reason}. Answer based on your knowledge or say you don't know."
            ))
        
        should_trigger_guard = (
            (self.mode == "STRICT" and internet_enabled) or 
            (self.mode == "STANDARD" and internet_enabled and is_factual_intent)
        )
        
        if should_trigger_guard:
            factual_keywords = [
                "who", "which", "what", "cast", "actor", "played", "movie", "film", 
                "names", "list", "how many", "when", "date", "year", "price", "news",
                "kim", "oyuncu", "film", "kimdir", "nedir", "ne zaman", "oyuncuları", "kadrosu"
            ]
            has_factual_keyword = any(k in user_input.lower() for k in factual_keywords)
            
            if is_factual_intent or has_factual_keyword:
                messages.append(SystemMessage(content=(
                    "[CRITICAL DIRECTIVE - ENGLISH ONLY]\n"
                    "DETECTED: Factual query about real-world entities.\n"
                    "RULE: You MUST use the 'search' tool. DO NOT rely on memory.\n"
                    "DO NOT simulate search results. You MUST output a real <call:search> tag.\n"
                    "If you cannot search, say you don't know. DO NOT INVENT FACTS."
                )))

        if images and "moondream" not in self.llm.model_name.lower():
            from backend.providers import get_provider_llm
            vision_llm = get_provider_llm("ollama", "moondream")
            current_llm = vision_llm
        else:
            current_llm = self.llm
        
        logger.info(f"[AGENT] Using LLM: {getattr(current_llm, 'model_name', 'unknown')}, tools={'enabled' if internet_enabled else 'disabled'}")

        messages.append(HumanMessage(content=human_content))
        messages = self._prune_context(messages)

        seen_thoughts = []  # For Loop Breaker
        total_tokens_yielded = 0  # Track if any final answer tokens were sent
        accumulated_thought = ""  # Collect thought content as fallback
        
        # Global output limits by mode — generous enough to not truncate good answers
        # but still prevent infinite loops. Set high; the loop-breaker handles runaway outputs.
        MAX_OUTPUT_CHARS = {"STRICT": 2000, "STANDARD": 6000, "ENHANCED": 12000}

        for iteration in range(self.max_iterations):
            logger.info(f"[AGENT] Iteration {iteration + 1}/{self.max_iterations}")
            raw_text = ""
            in_thought = False
            in_call = False
            
            # For tiny models in STRICT mode - only 1 iteration needed
            model_name = getattr(current_llm, 'model_name', '') or ''
            is_tiny = any(x in model_name.lower() for x in ['0.8b', '0.5b', '1b', 'tiny'])
            if is_tiny and iteration > 0:
                break  # Tiny models only need 1 iteration
            
            try:
                # Real-time streaming parser
                logger.info(f"[AGENT] Calling LLM astream...")
                async for chunk in current_llm.astream(messages):
                    # Handle Qwen-style thinking mode or get content directly
                    token = ""
                    if hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                    
                    if not token or (isinstance(token, str) and not token.strip()):
                        continue
                    
                    raw_text += token
                    logger.info(f"[AGENT] Token: {repr(token[:30])}..., total: {len(raw_text)}")
                    
                    # Global output limit check (Enforced for all tokens)
                    max_chars = MAX_OUTPUT_CHARS.get(self.mode, 3000)
                    if len(raw_text) > max_chars:
                        yield {"type": "status", "content": f"Maksimum çıktı sınırı aşıldı ({max_chars} chars)."}
                        break

                    # Global loop/repetition detection
                    if len(raw_text) > 200:
                        window = raw_text[-200:].lower()
                        words = window.split()
                        if len(words) > 10:
                            unique_words = set(words)
                            if len(unique_words) / len(words) < 0.25:  # Over 75% repetition of words
                                yield {"type": "status", "content": "Döngü tespit edildi, akış sonlandırılıyor."}
                                break


                    # Detect tag transitions (highly flexible for small models)
                    # Also detect if we're in thinking mode (Qwen-style)
                    if not in_thought and not in_call:
                        if re.search(r"<thought", raw_text[-20:], re.IGNORECASE):
                            in_thought = True
                            continue
                        
                        if re.search(r"<call:", raw_text[-20:], re.IGNORECASE):
                            in_call = True
                            continue

                        # Qwen-style thinking detection - if token contains question words and no <call:>
                        if "analyze the request" in token.lower() or "determine" in token.lower():
                            # Likely in thinking mode - check if it's looping
                            if len(raw_text) > 100:
                                # Check for repetitive patterns
                                recent = raw_text[-150:].lower()
                                words = recent.split()
                                if len(words) > 10:
                                    unique_ratio = len(set(words)) / len(words)
                                    if unique_ratio < 0.3:  # Too repetitive
                                        yield {"type": "status", "content": "Döngü tespit edildi, cevaba geçiliyor..."}
                                        in_thought = False
                                        break
                        
                        # Safety: If we've seen > 10 chars and NO tags, force 'token' type
                        if len(raw_text) > 10 and not in_thought and not in_call:
                            # If it starts to output tool calls, wait and let tags be detected
                            if "<" in raw_text[-10:]:
                                continue
                            # If the model started outputting without tags, yield it as answer
                            yield {"type": "token", "content": token}
                            continue

                    if in_thought:
                        # Check for tool call in thinking mode too
                        if re.search(r"<call:\s*search", raw_text, re.IGNORECASE):
                            in_thought = False
                            in_call = True
                            break
                        
                        if re.search(r"</thought", raw_text[-20:], re.IGNORECASE):
                            in_thought = False
                            # Check if any answer was generated AFTER thought closes
                            # If not, force break and use thought content as answer
                            after_thought = re.sub(r"<thought\s*>.*?</thought\s*>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
                            if not after_thought or len(after_thought) < 5:
                                # Thought closed but no answer after it - use thought as final
                                yield {"type": "status", "content": "Düşünme tamamlandı, cevap oluşturuluyor..."}
                                break
                            # Repetition Check
                            thought_match = re.search(r"<thought\s*>(.*?)</thought\s*>", raw_text, re.DOTALL | re.IGNORECASE)
                            if thought_match:
                                normalized = " ".join(thought_match.group(1).split()).lower()
                                if normalized in seen_thoughts:
                                    yield {"type": "status", "content": "Tekrar eden düşünce yolu kapatıldı."}
                                    messages.append(SystemMessage(content="[SYSTEM] Avoid repeating previous thoughts. Try a new angle."))
                                    break # Retry iteration
                                seen_thoughts.append(normalized)
                            continue
                        
                        # Safety Valve: Character limit for thought - much lower for small models
                        if len(raw_text) > 600:
                            yield {"type": "status", "content": "Düşünme sınırı aşıldı, cevaba geçiliyor..."}
                            in_thought = False
                            break
                            
                        # Safety Valve: Real-time loop detection - trigger earlier
                        if len(raw_text) > 150:
                            window = raw_text[-150:].lower()
                            # Check for repetitive words (looping pattern)
                            words = window.split()
                            if len(words) > 5:
                                unique_words = set(words)
                                if len(unique_words) / len(words) < 0.25:  # 75% repetition
                                    yield {"type": "status", "content": "Döngü tespit edildi, cevap zorlanıyor..."}
                                    in_thought = False
                                    messages.append(SystemMessage(content="[SYSTEM] STOP repeating. Give SHORT answer now. No analysis."))
                                    break
                        
                        # BLOCK: System prompt leak detection
                        if any(pattern in raw_text.lower() for pattern in ["## core rules", "## critical rules", "format:", "mandatory protocol"]):
                            yield {"type": "status", "content": "Sistem sızıntısı tespit edildi, yeniden deneniyor..."}
                            in_thought = False
                            messages.append(SystemMessage(content="[SYSTEM] Do NOT repeat system instructions. Just answer the user's question directly."))
                            break

                        # Yield tokens for UI thought section
                        clean_token = token.replace("<thought>", "").replace("</thought>", "")
                        if clean_token:
                            accumulated_thought += clean_token
                            yield {"type": "thought", "content": clean_token}

                    elif not in_call:
                        if re.search(r"<call:", raw_text, re.IGNORECASE):
                            in_call = True
                            continue
                            
                        # Yield tokens for final answer UI
                        clean_token = token.replace("<thought>", "").replace("</thought>", "").replace("<call:", "").replace("</call>", "")
                        if clean_token:
                            total_tokens_yielded += 1
                            yield {"type": "token", "content": clean_token}

                    if in_call and re.search(r"</call\s*>", raw_text, re.IGNORECASE):
                        in_call = False
                        break 
                
                # Check for runaway repetition in small models (no tags used)
                if not in_thought and not in_call and iteration == 0:
                    lines = [l.strip() for l in raw_text.split(".") if len(l.strip()) > 10]
                    if len(lines) > 3 and len(set(lines)) < len(lines) / 2:
                        yield {"type": "status", "content": "Tekrar eden düşünce engellendi."}
                        break

            except Exception as e:
                yield {"type": "error", "content": f"Stream Error: {str(e)}"}
                return

            # Extract tool call
            tool_call = self._extract_tool_call(raw_text) if internet_enabled else None
            
            if tool_call:
                tool_name, raw_query = tool_call
                # Robust cleaning of hallucinated key-value or JSON query parameters
                query = raw_query.strip()
                if query.startswith("{"):
                    try:
                        import json
                        data = json.loads(query)
                        if isinstance(data, dict):
                            query = data.get("query") or data.get("search_query") or data.get("q") or query
                    except Exception:
                        pass
                else:
                    match_q = re.search(r'^(?:query|search_query|q)\s*=\s*["\'](.*?)["\']\s*$', query, re.DOTALL | re.IGNORECASE)
                    if match_q:
                        query = match_q.group(1).strip()
                    else:
                        match_q2 = re.search(r'^(?:query|search_query|q)\s*=\s*(.*?)\s*$', query, re.DOTALL | re.IGNORECASE)
                        if match_q2:
                            query = match_q2.group(1).strip()
                            
                if tool_name in self.all_tools:
                    # Update tools_used in plugin context for confidence tracking
                    self.plugin_manager.context.setdefault("tools_used", []).append(tool_name)
                    
                    # Dynamic timeout based on query complexity and mode
                    def get_timeout(tool: str, query: str, mode: str) -> float:
                        query_length = len(query)
                        is_simple_query = query_length < 30 and not any(c in query.lower() for c in ["?", "who", "what", "which", "how", "kim", "ne", "nasıl"])
                        
                        if tool == "search":
                            if mode == "STRICT":
                                return 8.0 if is_simple_query else 12.0
                            elif mode == "STANDARD":
                                return 10.0 if is_simple_query else 15.0
                            else:  # ENHANCED
                                return 12.0 if is_simple_query else 18.0
                        elif tool == "scrape":
                            if mode == "STRICT":
                                return 10.0 if is_simple_query else 15.0
                            elif mode == "STANDARD":
                                return 12.0 if is_simple_query else 18.0
                            else:
                                return 15.0 if is_simple_query else 25.0
                        return 15.0
                    
                    try:
                        tool_func = self.all_tools[tool_name].get("execute_async") or self.all_tools[tool_name].get("func")
                        if tool_name == "search":
                            search_timeout = get_timeout("search", query, self.mode)
                            yield {"type": "status", "content": f"Web taranıyor: '{query}' (max {int(search_timeout)}s)"}
                            results = []
                            try:
                                results = await asyncio.wait_for(
                                    tool_func(query) if asyncio.iscoroutinefunction(tool_func) else asyncio.to_thread(tool_func, query),
                                    timeout=search_timeout
                                )
                            except asyncio.TimeoutError:
                                yield {"type": "status", "content": f"Arama {int(search_timeout)}s içinde tamamlanamadı."}

                            if results:
                                obs_parts = [f"[{r['title']}] {r['snippet']} — {r['link']}" for r in results[:4]]
                                observation = "\n".join(obs_parts)
                                # Automatic concurrent scrape - early exit if good results
                                urls = [r["link"] for r in results[:min(3, len(results))]]
                                yield {"type": "status", "content": f"{len(urls)} kaynak okunuyor..."}
                                scrape_func = self.all_tools.get("scrape", {}).get("execute_async") or self.all_tools.get("scrape", {}).get("func")
                                if scrape_func:
                                    scrape_timeout = get_timeout("scrape", query, self.mode)
                                    try:
                                        scraped_data = await asyncio.wait_for(
                                            scrape_func(urls, query=query),
                                            timeout=scrape_timeout
                                        )
                                        observation += "\n\n" + scraped_data
                                    except asyncio.TimeoutError:
                                        yield {"type": "status", "content": f"Scrape {int(scrape_timeout)}s aştı, kısmi sonuçlarla devam ediliyor."}
                            else:
                                observation = "No results found."
                        else:
                            # Generic tool call
                            observation = await tool_func(**json.loads(query) if isinstance(query, str) and query.startswith("{") else {"query": query})
                        
                        # Ensure unclosed call tags are cleanly closed for history representation
                        history_text = raw_text
                        if "<call:" in history_text and "</call" not in history_text:
                            match_tag = re.search(r"<call:(\w+)>", history_text, re.IGNORECASE)
                            if match_tag:
                                history_text = history_text.strip() + f"</call>"
                        
                        messages.append(AIMessage(content=history_text))
                        
                        # Use HumanMessage instead of SystemMessage to guarantee Ollama API preserves the context.
                        # Wrap with clean English prefixes to prevent small parameter model confusion,
                        # and strictly prohibit XML tag continuation or repetition.
                        messages.append(HumanMessage(
                            content=(
                                f"[SYSTEM OBSERVATION] Search Results:\n{observation[:4000]}\n\n"
                                "DIRECTIVE: Search is complete. Based on the search results above, answer the user's question directly in Turkish as a single short sentence. "
                                "Completely ignore your outdated training data. DO NOT use any XML tags (<thought> or <call>). Reply with the final answer only!"
                            )
                        ))
                    except Exception as e:
                        history_text = raw_text
                        if "<call:" in history_text and "</call" not in history_text:
                            match_tag = re.search(r"<call:(\w+)>", history_text, re.IGNORECASE)
                            if match_tag:
                                history_text = history_text.strip() + f"</call>"
                        messages.append(AIMessage(content=history_text))
                        messages.append(HumanMessage(content=f"[SYSTEM ERROR] Tool Execution Error: {str(e)}"))
                else:
                    break
            else:
                final_answer = self._clean_for_display(raw_text)
                final_answer = self.plugin_manager.after_response(final_answer)
                
                # Output Stalling Fix: Handle small models that get stuck in thought tags
                # Check if we have accumulated thoughts but no final answer tokens
                has_significant_thought = len(accumulated_thought.strip()) > 20
                final_answer_is_empty = not final_answer or len(final_answer.strip()) < 10
                
                if total_tokens_yielded == 0 and has_significant_thought and final_answer_is_empty:
                    # Model only produced thought content - extract the ANSWER from it
                    thought_content = accumulated_thought.strip()
                    
                    # Try to extract the final answer from thinking content
                    # Look for patterns like "Answer:", "is 4", "= 4", etc.
                    answer_match = None
                    for pattern in [r"=\s*(\d+)", r"Answer:\s*(.+?)(?:\n|$)", r"The answer is[:\s]+(.+?)(?:\n|$)", r"Final answer[:\s]+(.+?)(?:\n|$)", r"is\s+(\d+)\.?$"]:
                        match = re.search(pattern, thought_content, re.IGNORECASE | re.MULTILINE)
                        if match:
                            answer_match = match.group(1).strip()
                            break
                    
                    # If we found an answer, use it. Otherwise, just use the first few lines
                    if answer_match and len(answer_match) < 50:
                        extracted = answer_match
                    else:
                        # Last resort: take just the last 50 chars as the answer
                        extracted = thought_content[-100:] if len(thought_content) > 100 else thought_content
                        # Remove thinking process, keep just the result
                        lines = [l.strip() for l in extracted.split('\n') if l.strip() and not l.startswith(('Analyze', 'Determine', 'Check', 'Wait', 'The', 'I ', 'This'))]
                        if lines:
                            extracted = lines[-1] if len(lines) > 1 else lines[0]
                    
                    if extracted:
                        yield {"type": "token", "content": extracted}
                elif total_tokens_yielded == 0 and final_answer:
                    # No tokens yielded but we have some final answer text - use it
                    yield {"type": "token", "content": final_answer}
                
                yield {"type": "status", "content": "complete"}
                break
        else:
            yield {"type": "status", "content": "Maksimum işlem limitine ulaşıldı."}


def build_agent(
    model_name: str,
    provider: str,
    plugin_names: list,
    session_history: list = None,
    agent_id: int = None,
    model_metadata: str = None,
    mode_override: str = None,
    **kwargs
):
    mode = determine_agent_mode(
        model_metadata=model_metadata,
        provider=provider,
        model_name=model_name,
        override=mode_override,
    )
    llm = get_provider_llm(provider, model_name)
    plugin_manager = PluginManager.from_names(
        plugin_names,
        session_history=session_history,
        agent_id=agent_id,
        agent_mode=mode,
    )
    plugin_manager.init()
    plugin_manager.context["mcp_enabled"] = kwargs.get("mcp_enabled", True)
    if agent_id:
        plugin_manager.context["agent_id"] = agent_id
    return CustomAgentExecutor(llm, plugin_manager, mode=mode)
