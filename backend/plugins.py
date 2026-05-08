import re
import json
import time
from abc import ABC
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage


class BasePlugin(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.active = True

    def init(self, context: Dict[str, Any]) -> None:
        return None

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        return messages

    def after_response(self, response: str, context: Dict[str, Any]) -> str:
        return response


class MemoryPlugin(BasePlugin):
    name = "memory"

    @staticmethod
    def _extract_digest_summary(messages: List[Any], max_chars: int = 200) -> Optional[str]:
        """
        Create a brief digest of older conversations by extracting key topics.
        """
        if not messages or len(messages) < 2:
            return None
        
        # Collect all text from older messages
        all_text = " ".join([msg.message for msg in messages if hasattr(msg, 'message')])
        if len(all_text) < 50:
            return None
        
        # Remove URLs and artifacts
        all_text = re.sub(r"https?://\S+", "", all_text)
        all_text = re.sub(r"<[^>]+>", "", all_text)
        all_text = re.sub(r"[*_`~]", "", all_text)
        
        # Extract important terms (longer terms, avoid common words)
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "i", "you", "me", "it", 
                      "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "that", "this"}
        words = re.findall(r"\b[a-z]{4,}\b", all_text.lower())
        word_freq = {}
        for w in words:
            if w not in stop_words:
                word_freq[w] = word_freq.get(w, 0) + 1
        
        # Get top keywords
        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        keywords = [w[0] for w in top_words if w[1] >= 2]
        
        if not keywords:
            return None
        
        # Build digest
        digest = f"Earlier discussion topics: {', '.join(keywords)}"
        return digest[:max_chars] if len(digest) > max_chars else digest

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        session_history = context.get("session_history") or []
        if not session_history:
            return messages

        # Adaptive window: STRICT mode gets 4 messages, STANDARD 6, ENHANCED 10
        mode = context.get("agent_mode", "STANDARD")
        window_size = {"STRICT": 4, "STANDARD": 6, "ENHANCED": 10}.get(mode, 6)

        recent_history = session_history[-window_size:]

        if len(session_history) > window_size:
            old_count = len(session_history) - window_size
            
            # Create digest from older messages
            older_messages = session_history[:-window_size]
            digest = self._extract_digest_summary(older_messages)
            
            if digest:
                summary = (
                    f"[CONVERSATION HISTORY]\n"
                    f"Total older messages: {old_count}\n"
                    f"Summary: {digest}"
                )
            else:
                summary = (
                    f"--- CONTEXT: There are {old_count} older messages hidden to save memory. ---"
                )
            messages.append(SystemMessage(content=summary))

        history_block = []
        for msg in recent_history:
            role = "User" if msg.role == "user" else "Assistant"
            text = msg.message
            # Strip artifacts
            text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
            text = re.sub(r"<call:.*?</call>", "", text, flags=re.DOTALL)
            text = re.sub(r"--- SOURCE URL:.*?---", "", text, flags=re.DOTALL)
            text = re.sub(r"https?://\S+", "[link]", text)
            text = " ".join(text.split()).strip()
            if text:
                history_block.append(f"{role}: {text}")

        if history_block:
            # Inject history as a single block for better context tracking in small models
            messages.append(SystemMessage(content="RECENT CONVERSATION HISTORY:\n" + "\n".join(history_block)))
        
        return messages


class TranslatorPlugin(BasePlugin):
    """
    Multi-strategy language detection + translation plugin.
    
    Detection priority:
      1. Greeting override (short text)
      2. Script analysis (Cyrillic, Arabic, CJK, Hebrew...)
      3. langdetect with Confidence scoring
      4. Heuristics
    """
    name = "translator"

    _CYR_UKRA = set("їєґЇЄҐ")
    _CYR_KAZ  = set("әғқңөұүһӘҒҚҢӨҰҮҺ")
    _COMMON_GREETINGS = {
        "selam": "tr", "merhaba": "tr", "nasîlsîn": "tr", "nasilsin": "tr", "naber": "tr",
        "iyiyim": "tr", "hello": "en", "hi": "en", "hey": "en", "good": "en",
        "привет": "ru", "салем": "kk", "сәлем": "kk", "привіт": "uk"
    }

    def _detect_by_script(self, text: str) -> Optional[str]:
        """Identify language from Unicode script block if dominant."""
        ranges = [
            ("ar",  [(0x0600, 0x06FF), (0x0750, 0x077F)]),
            ("zh",  [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)]),
            ("ja",  [(0x3040, 0x30FF)]),
            ("ko",  [(0xAC00, 0xD7AF)]),
            ("he",  [(0x0590, 0x05FF)]),
            ("el",  [(0x0370, 0x03FF)]),
            ("th",  [(0x0E00, 0x0E7F)]),
            ("ka",  [(0x10A0, 0x10FF)]),
            ("hy",  [(0x0530, 0x058F)]),
            ("cyr", [(0x0400, 0x04FF)]),
        ]
        counts: dict = {}
        for ch in text:
            cp = ord(ch)
            for lang, rngs in ranges:
                if any(lo <= cp <= hi for lo, hi in rngs):
                    counts[lang] = counts.get(lang, 0) + 1
                    break

        if not counts:
            return None
        dominant, count = max(counts.items(), key=lambda x: x[1])
        if count / max(len(text), 1) < 0.10:
            return None

        if dominant == "cyr":
            # Check unique Kazakh chars first
            kaz = sum(1 for c in text if c in self._CYR_KAZ)
            # Check unique Ukrainian chars
            ukr = sum(1 for c in text if c in self._CYR_UKRA)
            if kaz > 0: return "kk"
            if ukr > 0: return "uk"
            # 'i' check
            if "і" in text or "І" in text:
                return "uk" 
            return "ru"

        if dominant == "zh":
            if any(0x3040 <= ord(c) <= 0x30FF for c in text):
                return "ja"

        return dominant

    def _detect_language(self, text: str) -> str:
        # 1. Greeting map
        clean_text = text.strip().lower().replace("?", "").replace("!", "")
        if clean_text in self._COMMON_GREETINGS:
            return self._COMMON_GREETINGS[clean_text]
        
        # Turkish detection for short messages with no unique chars but common patterns
        tr_patterns = ["nedir", "kimdir", "neler", "nasil", "niye", "oyunculari", "hakkinda", "kadrosu", "film"]
        if any(p in clean_text for p in tr_patterns):
            return "tr"

        # 2. Script analysis
        script_lang = self._detect_by_script(text)
        if script_lang:
            return script_lang

        # 3. langdetect
        try:
            from langdetect import detect_langs, DetectorFactory
            DetectorFactory.seed = 0
            candidates = detect_langs(text)
            if not candidates:
                return "en"
            detected, prob = candidates[0].lang, candidates[0].prob

            # 4. Heuristics for Turkish
            # check common Turkish specific chars
            tr_chars = sum(1 for c in text.lower() if c in "ğüşıöçâîû")
            if tr_chars >= 1:
                return "tr"
            
            # Short ambiguous text logic
            if len(text) < 50 and detected in {"id", "so", "tl", "sw", "af", "nl"}:
                if any(word in clean_text.split() for word in ["nasılsın", "naber", "selam", "merhaba"]):
                    return "tr"

            return detected
        except Exception:
            return "en"

    def _already_in_target_lang(self, text: str, lang: str) -> bool:
        if lang == "en":
            return True
        if lang in ("ru", "uk", "bg", "mk", "sr", "kk"):
            return sum(1 for c in text if 0x0400 <= ord(c) <= 0x04FF) / max(len(text), 1) > 0.20
        if lang in ("ar", "fa", "ur"):
            return sum(1 for c in text if 0x0600 <= ord(c) <= 0x06FF) / max(len(text), 1) > 0.20
        if lang in ("zh", "ja", "ko"):
            cjk = sum(1 for c in text if (0x4E00 <= ord(c) <= 0x9FFF) or
                      (0x3040 <= ord(c) <= 0x30FF) or (0xAC00 <= ord(c) <= 0xD7AF))
            return cjk / max(len(text), 1) > 0.15
        if lang == "tr":
            return sum(1 for c in text.lower() if c in "ğüşıöçâîû") >= 2
        return False

    def init(self, context: Dict[str, Any]) -> None:
        context.setdefault("original_lang", "en")
        context.setdefault("translated_input", None)

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        input_text = context.get("input_text", "")
        if not input_text:
            return messages
        try:
            detected = self._detect_language(input_text)
            if detected != "en":
                from deep_translator import GoogleTranslator
                context["original_lang"] = detected
                context["detected_lang"] = detected  # For other plugins like InternetPlugin
                try:
                    translated = GoogleTranslator(source=detected, target="en").translate(input_text)
                except Exception:
                    translated = GoogleTranslator(source="auto", target="en").translate(input_text)
                context["translated_input"] = translated or input_text
            else:
                context["original_lang"] = "en"
                context["detected_lang"] = "en"
                context["translated_input"] = input_text
        except Exception:
            context["translated_input"] = input_text
        return messages

    def after_response(self, response: str, context: Dict[str, Any]) -> str:
        original_lang = context.get("original_lang", "en")
        if not original_lang or original_lang == "en":
            return response
        if self._already_in_target_lang(response, original_lang):
            return response
        try:
            from deep_translator import GoogleTranslator
            try:
                result = GoogleTranslator(source="en", target=original_lang).translate(response)
            except Exception:
                result = GoogleTranslator(source="auto", target=original_lang).translate(response)
            return result or response
        except Exception:
            return response


class InternetPlugin(BasePlugin):
    """
    Enhanced Internet Plugin with:
    - Intelligent intent detection
    - Rate limiting
    - Security filtering
    - Query optimization
    - Result caching
    - Fallback strategies
    - Monitoring & analytics
    """
    name = "internet"
    
    # Rate limits by mode
    RATE_LIMITS = {
        "STRICT": {"per_minute": 2, "per_hour": 10},    # Small models - conservative
        "STANDARD": {"per_minute": 5, "per_hour": 30},  # Medium models
        "ENHANCED": {"per_minute": 10, "per_hour": 60}, # Large models
    }
    
    # Queries that definitely need internet
    FACTUAL_KEYWORDS = {
        "en": ["who", "which", "what", "when", "where", "how many", "latest", "current", "price", "news", "weather", "stock", "score", "born", "died", "released", "founded"],
        "tr": ["kim", "ne", "nerede", "nasıl", "kaç", "fiyat", "haber", "hava", "borsa", "doğum", "ölüm", "kuruluş", "oyunculari", "kadrosu", "film", "dizi"],
    }
    
    # Queries that should NOT use internet (model can answer from knowledge)
    NON_INTERNET_KEYWORDS = {
        "en": ["explain", "how does", "what is the concept", "define", "describe", "calculate", "compare", "write code", "generate"],
        "tr": ["açıkla", "nasıl çalışır", "tanım", "hesapla", "karşılaştır", "kod yaz", "oluştur"],
    }
    
    # Blocked query patterns (security)
    BLOCKED_PATTERNS = [
        r"(hack|exploit|bypass|inject).*",
        r"(malware|virus|ransomware).*",
        r"(bomb|weapon|explosive).*",
        r"(illegal|drugs|porn|child).*",
        r"(credential|password|auth).*steal",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._search_cache: Dict[str, str] = {}
        self._request_counts: Dict[str, List[float]] = {}  # timestamps
        self._blocked_count = 0
        self._total_searches = 0
        self._successful_searches = 0

    def init(self, context: Dict[str, Any]) -> None:
        context["internet_enabled"] = True
        context["search_cache"] = {}
        context["search_stats"] = {"total": 0, "blocked": 0, "cached": 0, "failed": 0}
        
    def _clean_query(self, query: str) -> str:
        """Optimize search query - remove noise, keep key terms."""
        # Remove quotes, extra spaces, special chars that hurt search
        query = re.sub(r'["\'“”‘’]', "", query)
        query = re.sub(r'\s+', " ", query).strip()
        # Limit length - very long queries don't work well
        if len(query) > 200:
            query = query[:200]
        return query

    def _is_safe_query(self, query: str) -> bool:
        """Security check - block harmful queries."""
        query_lower = query.lower()
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, query_lower):
                return False
        return True

    def _needs_internet(self, query: str, detected_lang: str = "en") -> bool:
        """Intelligent detection - does this query really need internet?"""
        query_lower = query.lower()
        
        # Check non-internet keywords first
        keywords = self.NON_INTERNET_KEYWORDS.get(detected_lang, self.NON_INTERNET_KEYWORDS["en"])
        for kw in keywords:
            if kw in query_lower:
                return False
        
        # Check factual keywords - these need internet
        factual = self.FACTUAL_KEYWORDS.get(detected_lang, self.FACTUAL_KEYWORDS["en"])
        for kw in factual:
            if kw in query_lower:
                return True
        
        # Check question patterns that typically need current info
        question_patterns = [
            r"^\s*(who|what|where|when|how)\s+(is|are|was|were|do|does|did)",  # English
            r"^\s*(kim|ne|nerede|nasıl|niye)\s",  # Turkish
            r"\?$",  # Questions with ?
        ]
        for pattern in question_patterns:
            if re.search(pattern, query_lower):
                return True
        
        # Default: allow internet for unknown cases
        return True

    def _check_rate_limit(self, context: Dict[str, Any], mode: str) -> tuple[bool, str]:
        """Check if we've hit rate limits. Returns (allowed, reason)."""
        now = time.time()
        limits = self.RATE_LIMITS.get(mode, self.RATE_LIMITS["STANDARD"])
        
        # Get request history (agent-based for rate limiting)
        session_key = f"agent_{context.get('agent_id', 'default')}"
        if session_key not in self._request_counts:
            self._request_counts[session_key] = []
        
        # Clean old timestamps
        self._request_counts[session_key] = [
            t for t in self._request_counts[session_key]
            if now - t < 3600  # Keep last hour
        ]
        
        recent = self._request_counts[session_key]
        
        # Check per-minute limit
        minute_ago = now - 60
        per_minute = sum(1 for t in recent if t > minute_ago)
        if per_minute >= limits["per_minute"]:
            return False, f"Rate limit: {limits['per_minute']}/min reached"
        
        # Check per-hour limit
        per_hour = len(recent)
        if per_hour >= limits["per_hour"]:
            return False, f"Rate limit: {limits['per_hour']}/hour reached"
        
        return True, ""

    def _get_cached_result(self, query: str) -> Optional[str]:
        """Get cached search result if available."""
        cache_key = query.lower().strip()
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]
        return None

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        input_text = context.get("translated_input") or context.get("input_text", "")
        mode = context.get("agent_mode", "STANDARD")
        
        # Determine detected language
        detected_lang = context.get("detected_lang", "en")
        
        # STRICT mode: intelligent filtering for small models
        if mode == "STRICT":
            needs_internet = self._needs_internet(input_text, detected_lang)
            if not needs_internet:
                context["internet_enabled"] = False
                context["internet_blocked_reason"] = "Knowledge-based query - no internet needed"
                return messages
            context["internet_enabled"] = True
        
        # Rate limiting check for all modes
        allowed, reason = self._check_rate_limit(context, mode)
        if not allowed:
            context["internet_enabled"] = False
            context["internet_blocked_reason"] = reason
            return messages
        
        # Security check
        if not self._is_safe_query(input_text):
            context["internet_enabled"] = False
            context["internet_blocked_reason"] = "Query blocked for security"
            self._blocked_count += 1
            return messages
        
        context["internet_enabled"] = True
        return messages

    def after_response(self, response: str, context: Dict[str, Any]) -> str:
        """Track search statistics and update cache."""
        stats = context.get("search_stats", {})
        
        # Track if search was actually used
        tools_used = context.get("tools_used", [])
        if "search" in tools_used:
            self._total_searches += 1
            self._successful_searches += 1
            stats["total"] = stats.get("total", 0) + 1
        
        stats["blocked"] = self._blocked_count
        context["search_stats"] = stats
        
        return response


class DocumentPlugin(BasePlugin):
    name = "document"

    def __init__(self, agent_id: int) -> None:
        super().__init__()
        self.agent_id = agent_id

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        input_text = context.get("translated_input") or context.get("input_text", "")
        if not input_text:
            return messages

        try:
            from backend.rag import retrieve_chunks_with_reranking
            
            # Get agent mode for re-ranking heuristics
            agent_mode = context.get("agent_mode", "STANDARD")
            
            # Use re-ranking for STANDARD and ENHANCED modes, skip for STRICT (latency-sensitive)
            use_reranker = agent_mode in ["STANDARD", "ENHANCED"]
            
            chunks, reranking_metadata = retrieve_chunks_with_reranking(
                self.agent_id,
                input_text,
                top_k=3,
                use_reranker=use_reranker,
                initial_k_multiplier=5.0,  # Get 15 candidates before re-ranking
            )
            
            if chunks:
                rag_context = "\n\n".join(
                    f"[Document: {c['filename']}]\n{c['text']}" for c in chunks
                )
                rag_msg = (
                    "[RELEVANT DOCUMENT CONTEXT]\n"
                    "Use the following excerpts from the user's uploaded files.\n"
                    f"{rag_context}"
                )
                messages.append(SystemMessage(content=rag_msg))
                context["rag_sources"] = [c["filename"] for c in chunks]
                
                # Track re-ranking metrics for later
                context["rag_reranking_metadata"] = reranking_metadata
                
                # If significant improvement, boost confidence in RAG sources
                if reranking_metadata.get("reranking_applied"):
                    context["rag_reranking_applied"] = True
                    
        except Exception:
            pass
        return messages



class DisclaimerPlugin(BasePlugin):
    """Anti-hallucination guard for small models."""
    name = "disclaimer"

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        internet_enabled = context.get("internet_enabled", False)
        mode = context.get("agent_mode", "STANDARD")
        
        if not internet_enabled and mode == "STRICT":
            reminder = (
                "\n[IMPORTANT]: Internet is DISCONNECTED. If you don't know a fact "
                "(people, movies, specific names), say 'I don't know'. DO NOT hallucinate."
            )
            # Find last HumanMessage which is usually the current query
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    msg.content += reminder
                    break
        return messages


class ConfidencePlugin(BasePlugin):
    """
    Tracks response sources (tool usage, RAG, memory) and computes 
    confidence score & hallucination flags.
    """
    name = "confidence"

    def before_prompt(self, messages: List[Any], context: Dict[str, Any]) -> List[Any]:
        # Initialize tracking
        context["tools_used"] = []
        context["response_confidence"] = 1.0
        context["response_flags"] = []
        context["response_sources"] = ["memory"]  # Default: conversation history
        return messages

    def after_response(self, response: str, context: Dict[str, Any]) -> str:
        """
        Post-process to compute confidence & flags based on response content and context.
        """
        mode = context.get("agent_mode", "STANDARD")
        internet_enabled = context.get("internet_enabled", False)
        tools_used = context.get("tools_used", [])
        rag_sources = context.get("rag_sources", [])

        # Start with base confidence
        confidence = 1.0
        flags = []
        sources = ["memory"]

        # Reduce confidence for STRICT mode (small models are less reliable)
        if mode == "STRICT":
            confidence -= 0.15

        # If internet was used, increase confidence for factual claims
        if "search" in tools_used or "scrape" in tools_used:
            sources.append("tool:internet")
            confidence = min(1.0, confidence + 0.2)
        elif internet_enabled and any(keyword in response.lower() for keyword in 
                                        ["according to", "web shows", "internet", "result"]):
            # Despite being available, internet wasn't used for a claim that looks like web content
            flags.append("possible_hallucination")
            confidence = max(0.4, confidence - 0.25)

        # If RAG was used
        if rag_sources:
            sources.append("rag")
            confidence = min(1.0, confidence + 0.15)
            
            # Boost confidence if ML re-ranking was applied (better relevance)
            reranking_applied = context.get("rag_reranking_applied", False)
            if reranking_applied:
                reranking_metadata = context.get("rag_reranking_metadata", {})
                # If re-ranking moved the best result up significantly (+0.05 score improvement),
                # add extra confidence bonus
                score_improvement = reranking_metadata.get("score_improvement", 0.0)
                if score_improvement > 0.05:
                    confidence = min(1.0, confidence + 0.1)
                    flags.append("rag_optimized")

        # Detect uncertain language patterns
        uncertain_patterns = [
            r"\bi\s+think\b",      # "i think"
            r"\bi\s+believe\b",    # "i believe"
            r"\bprobably\b",       # "probably"
            r"\bmight\b",          # "might"
            r"\bcould\b",          # "could"
            r"\bnot\s+sure\b",     # "not sure"
            r"\bunsure\b"          # "unsure"
        ]
        if any(re.search(pat, response.lower()) for pat in uncertain_patterns):
            flags.append("uncertain_context")
            confidence = max(0.5, confidence - 0.1)

        # Detect Simulated Tool Hallucination (English/Turkish patterns)
        simulation_patterns = [
            r"search\s+query", r"searching\s+for", r"action\s*:", 
            r"observation\s*:", r"thought\s*:", r"arama\s+yapıyorum",
            r"sonuçları\s+alıyorum", r"arama\s+sorgusu"
        ]
        if not tools_used and any(re.search(pat, response.lower()) for pat in simulation_patterns):
            flags.append("simulated_tool_hallucination")
            confidence = max(0.1, confidence - 0.6) # Heavy penalty for lying about tools

        # Detect if asked about specific people/events but no search was done
        # Only flag in STRICT mode (small models ≤2B) and when confidence is already low
        # Avoids false positives in STANDARD/ENHANCED models
        if (not internet_enabled and mode == "STRICT" and confidence < 0.6 and
                any(keyword in response.lower() for keyword in
                    ["which actor", "cast", "oscar", "born in", "released in"])):
            if "search" not in tools_used:
                flags.append("requires_verification")
                confidence = max(0.3, confidence - 0.15)

        # Store computed values back in context for main.py to use
        context["response_confidence"] = max(0.0, min(1.0, confidence))
        context["response_flags"] = flags
        context["response_sources"] = list(set(sources))  # Deduplicate

        return response


class PluginManager:
    def __init__(
        self,
        plugins: Optional[List[BasePlugin]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.plugins = plugins or []
        self.context = context or {}

    def init(self) -> None:
        for plugin in self.plugins:
            plugin.init(self.context)

    def before_prompt(self, messages: List[Any]) -> List[Any]:
        for plugin in self.plugins:
            messages = plugin.before_prompt(messages, self.context)
        return messages

    def after_response(self, response: str) -> str:
        for plugin in self.plugins:
            if plugin.active:
                response = plugin.after_response(response, self.context)
        return response

    @classmethod
    def from_names(
        cls,
        names: List[str],
        session_history: Optional[List[Any]] = None,
        agent_id: Optional[int] = None,
        agent_mode: str = "STANDARD",
    ) -> "PluginManager":
        plugins_to_load = []
        context = {
            "session_history": session_history or [],
            "agent_mode": agent_mode,
            "internet_enabled": False,
            "rag_sources": [],
            "tools_used": [],
            "response_confidence": 1.0,
            "response_flags": [],
            "response_sources": [],
        }

        # Plugin class mapping
        plugin_classes = {
            "translator": TranslatorPlugin,
            "memory": MemoryPlugin,
            "internet": InternetPlugin,
            "document": lambda: DocumentPlugin(agent_id=agent_id) if agent_id else None,
        }

        # Load plugins in user's specified order, respecting dependencies
        # Translator must run before Document (needs translated_input)
        loaded = set()
        
        # First load plugins that user specified (respecting their order)
        for name in names:
            if name in plugin_classes and name not in loaded:
                if name == "document" and agent_id:
                    plugin = plugin_classes[name]()
                    if plugin:
                        plugins_to_load.append(plugin)
                        loaded.add(name)
                else:
                    plugins_to_load.append(plugin_classes[name]())
                    loaded.add(name)

        # Always add disclaimer and confidence tracker for safety (at the end)
        plugins_to_load.append(DisclaimerPlugin())
        plugins_to_load.append(ConfidencePlugin())

        return cls(plugins=plugins_to_load, context=context)
