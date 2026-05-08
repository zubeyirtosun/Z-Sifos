import sqlite3
import json
import time
import os
import numpy as np
from typing import Optional, Dict, Any
from sentence_transformers import SentenceTransformer

class SemanticCache:
    def __init__(self, db_path: str = "semantic_cache.db", model_name: str = "all-MiniLM-L6-v2"):
        self.db_path = os.path.join(os.path.dirname(__file__), "..", "..", db_path)
        self.model = SentenceTransformer(model_name)
        self._init_db()
        self.ttl = 24 * 3600  # 24 hours in seconds

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                embedding BLOB,
                response TEXT,
                created_at FLOAT
            )
        """)
        conn.commit()
        conn.close()

    def _cosine_similarity(self, v1, v2):
        return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

    def get(self, query: str, threshold: float = 0.92) -> Optional[Dict[str, Any]]:
        """Retrieve cached response if semantic similarity is above threshold."""
        query_embedding = self.model.encode(query)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # We fetch items that hasn't expired
        current_time = time.time()
        cursor.execute("SELECT id, query, embedding, response, created_at FROM cache WHERE created_at > ?", (current_time - self.ttl,))
        rows = cursor.fetchall()
        
        best_match = None
        max_sim = 0
        
        for row in rows:
            cached_id, cached_query, cached_emb_blob, cached_resp, created_at = row
            cached_emb = np.frombuffer(cached_emb_blob, dtype=np.float32)
            
            sim = self._cosine_similarity(query_embedding, cached_emb)
            if sim > threshold and sim > max_sim:
                max_sim = sim
                best_match = json.loads(cached_resp)
        
        conn.close()
        return best_match

    def set(self, query: str, response: Dict[str, Any]):
        """Cache a response with its embedding."""
        embedding = self.model.encode(query).astype(np.float32)
        emb_blob = embedding.tobytes()
        resp_json = json.dumps(response)
        current_time = time.time()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cache (query, embedding, response, created_at) VALUES (?, ?, ?, ?)",
            (query, emb_blob, resp_json, current_time)
        )
        conn.commit()
        conn.close()

# Singleton instance
cache_manager = SemanticCache()
