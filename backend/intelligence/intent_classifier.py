import logging
import numpy as np
from typing import Dict, List, Tuple
from pathlib import Path

# Reuse RAG embedding logic
try:
    from backend.rag import _get_embed_model
except ImportError:
    # Fallback if rag.py is not reachable or different structure
    _get_embed_model = None

logger = logging.getLogger(__name__)

# --- Intent Definitions ---
# Each intent has a list of 'anchor' sentences that define its semantic space.
INTENTS = {
    "GREETING": [
        "Merhaba", "Selam", "Naber?", "Günaydın", "İyi akşamlar", "Selamun aleyküm",
        "Hello", "Hi", "Greetings", "Hey there", "Good morning", "How's it going?"
    ],
    "SEARCH": [
        "Bugün hava nasıl?", "Jumanji filminin oyuncuları kimler?", "En son haberler neler?",
        "İnternette ara", "Who is the president?", "Latest stock prices", "Search the web",
        "Fact check this", "Dünya kupasını kim kazandı?", "Bana güncel bilgileri ver",
        "Kim olduğunu söyle", "Nedir?", "Kimdir?", "Tarihi", "Fiyatı ne kadar?"
    ],
    "DOCUMENT": [
        "Dökümanda ne yazıyor?", "Bu PDF'i özetle", "Dosyalarımda ara", "Yüklediğim dosyada",
        "What does the document say?", "Summarize my files", "Search in my data",
        "Find info in uploaded files", "Dökümana göre cevapla", "Dökümü özetler misin?",
        "Dosyada ne anlatılıyor?", "Metne göre", "Belgedeki bilgiler"
    ],
    "TASK": [
        "Bana kod yaz", "Şu hesabı yap", "Analiz et", "Create a function",
        "Write a python script", "Solve this math problem", "Data analysis",
        "Build a project", "Kod örneği ver", "Script oluştur", "Hesapla"
    ],
    "CHAT": [
        "Bana bir hikaye anlat", "Nasılsın?", "Hadi sohbet edelim", "Geyik yapalım",
        "Tell me a story", "Talk to me", "Let's chat", "What do you think about AI?",
        "Just conversation", "Sıkıldım", "Bir fıkra anlat", "Neler yapabilirsin?"
    ]
}

class IntentClassifier:
    def __init__(self):
        self.model = None
        self.intent_embeddings = {}
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            if _get_embed_model:
                self.model = _get_embed_model()
            else:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
            
            # Pre-calculate embeddings for all intent anchors
            for intent, anchors in INTENTS.items():
                embeddings = self.model.encode(anchors, convert_to_tensor=True)
                # Store the mean embedding for each intent category
                self.intent_embeddings[intent] = embeddings.mean(dim=0)
            
            self._initialized = True
            logger.info("IntentClassifier initialized successfully with anchors.")
        except Exception as e:
            logger.error(f"Failed to initialize IntentClassifier: {e}")

    def classify(self, text: str) -> Tuple[str, float]:
        """
        Classifies the input text into one of the predefined intents.
        Returns (intent_name, confidence_score).
        """
        if not self._initialized:
            self._initialize()
        
        if not self.model:
            return "CHAT", 0.0

        try:
            from sentence_transformers import util
            query_emb = self.model.encode(text, convert_to_tensor=True)
            
            best_intent = "CHAT"
            best_score = -1.0
            
            for intent, intent_emb in self.intent_embeddings.items():
                score = util.cos_sim(query_emb, intent_emb).item()
                if score > best_score:
                    best_score = score
                    best_intent = intent
            
            # Heuristic: If confidence is too low, default to CHAT
            if best_score < 0.25:
                return "CHAT", best_score
                
            return best_intent, round(best_score, 4)
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return "CHAT", 0.0

# Singleton instance
classifier = IntentClassifier()

def get_intent(text: str) -> Dict[str, Any]:
    intent, score = classifier.classify(text)
    return {"intent": intent, "score": score}
