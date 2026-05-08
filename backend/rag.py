"""
rag.py — Local RAG (Retrieval-Augmented Generation) pipeline.

Features:
  - Text extraction from PDF, TXT, DOCX, MD files
  - Recursive character-level chunking (512 tokens, 10% overlap)
  - Local embedding via sentence-transformers (nomic-embed-text or all-MiniLM)
  - Cosine similarity retrieval (no external vector DB required)
  - Chunk metadata stored in SQLite, embeddings stored as numpy arrays in files

Design choice: No FAISS dependency by default — pure numpy cosine similarity
is fast enough for hundreds of chunks per agent. For 10k+ chunks, FAISS can be
enabled by setting USE_FAISS=True.
"""

import os
import json
import re
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional

# Base directories
_PROJECT_ROOT = Path(__file__).parent.parent
EMBED_STORE_DIR = _PROJECT_ROOT / "data" / "embeddings"
UPLOAD_DIR = _PROJECT_ROOT / "data" / "uploads"

EMBED_STORE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Embedding model — falls back gracefully if not installed
_EMBED_MODEL = None
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # ~90MB, fast, good quality


def _get_embed_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBED_MODEL = SentenceTransformer(_EMBED_MODEL_NAME)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )
    return _EMBED_MODEL


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

def extract_text(file_path: str, filename: str) -> str:
    """Extract plain text from uploaded file."""
    ext = Path(filename).suffix.lower()

    if ext in (".txt", ".md", ".rst", ".csv"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            # Fallback — try pdfminer
            try:
                from pdfminer.high_level import extract_text as pdfminer_extract
                return pdfminer_extract(file_path)
            except ImportError:
                return "[PDF support requires: pip install pypdf]"

    if ext in (".docx", ".doc"):
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return "[DOCX support requires: pip install python-docx]"

    # Attempt generic text read
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return "[Unsupported file format]"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = 600,
    overlap: int = 60,
) -> List[str]:
    """
    Recursive character-level chunking that preserves semantic boundaries.
    Tries to split by double newline, then single newline, then sentence, then space.
    """
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]
    chunks = []
    
    def _split_recursive(current_text: str):
        if len(current_text) <= chunk_size:
            chunks.append(current_text.strip())
            return

        # Find best separator
        separator = " "
        for sep in separators:
            if sep in current_text:
                separator = sep
                break
        
        # Split into candidates
        parts = current_text.split(separator)
        current_chunk = ""
        
        for part in parts:
            candidate = (current_chunk + separator + part) if current_chunk else part
            if len(candidate) <= chunk_size:
                current_chunk = candidate
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # Overlap logic
                    overlap_size = min(overlap, len(current_chunk))
                    overlap_text = current_chunk[-overlap_size:]
                    current_chunk = (overlap_text + separator + part) if overlap_text else part
                else:
                    # Single part is too long, force split it
                    _split_recursive(part)
        
        if current_chunk:
            chunks.append(current_chunk.strip())

    _split_recursive(text)
    return [c for c in chunks if len(c) > 10]


# ---------------------------------------------------------------------------
# Embedding & Storage
# ---------------------------------------------------------------------------

def _embed_texts(texts: List[str]) -> np.ndarray:
    """Embed a list of texts, returns (N, D) float32 array."""
    model = _get_embed_model()
    return model.encode(texts, normalize_embeddings=True).astype(np.float32)


def _agent_embed_dir(agent_id: int) -> Path:
    d = EMBED_STORE_DIR / str(agent_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(agent_id: int) -> Path:
    return _agent_embed_dir(agent_id) / "meta.json"


def _load_meta(agent_id: int) -> List[Dict[str, Any]]:
    p = _meta_path(agent_id)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return []


def _save_meta(agent_id: int, meta: List[Dict[str, Any]]) -> None:
    with open(_meta_path(agent_id), "w") as f:
        json.dump(meta, f)


def _embeddings_path(agent_id: int) -> Path:
    return _agent_embed_dir(agent_id) / "embeddings.npy"


def _load_embeddings(agent_id: int) -> Optional[np.ndarray]:
    p = _embeddings_path(agent_id)
    if p.exists():
        return np.load(str(p))
    return None


def _save_embeddings(agent_id: int, embeddings: np.ndarray) -> None:
    np.save(str(_embeddings_path(agent_id)), embeddings)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def index_document(
    agent_id: int,
    file_path: str,
    filename: str,
    doc_id: int,
) -> int:
    """
    Extract, chunk, embed and store a document for an agent.
    Returns the number of chunks created.
    """
    raw_text = extract_text(file_path, filename)
    chunks = chunk_text(raw_text)

    if not chunks:
        return 0

    new_embeddings = _embed_texts(chunks)

    # Load existing data
    existing_meta = _load_meta(agent_id)
    existing_embeddings = _load_embeddings(agent_id)

    # Remove any old entries for this doc_id (re-indexing support)
    keep_indices = [i for i, m in enumerate(existing_meta) if m.get("doc_id") != doc_id]
    filtered_meta = [existing_meta[i] for i in keep_indices]
    filtered_embeddings = (
        existing_embeddings[keep_indices]
        if existing_embeddings is not None and len(keep_indices) > 0
        else None
    )

    # Build new meta entries
    new_meta = [
        {
            "doc_id": doc_id,
            "filename": filename,
            "chunk_idx": i,
            "text": chunk,
        }
        for i, chunk in enumerate(chunks)
    ]

    combined_meta = filtered_meta + new_meta
    combined_embeddings = (
        np.vstack([filtered_embeddings, new_embeddings])
        if filtered_embeddings is not None and len(filtered_embeddings) > 0
        else new_embeddings
    )

    _save_meta(agent_id, combined_meta)
    _save_embeddings(agent_id, combined_embeddings)

    return len(chunks)


def retrieve_chunks(
    agent_id: int,
    query: str,
    top_k: int = 4,
) -> List[Dict[str, Any]]:
    """
    Retrieve the most relevant chunks for a query.
    Uses FAISS (IVF for large scale, Flat for medium) if installed.
    Falls back to pure numpy for small collections.
    """
    meta = _load_meta(agent_id)
    embeddings = _load_embeddings(agent_id)

    if not meta or embeddings is None or len(embeddings) == 0:
        return []

    query_embedding = _embed_texts([query])[0]
    num_chunks = len(embeddings)
    dim = embeddings.shape[1]
    
    # Use FAISS if installed and we have enough data to justify it
    use_faiss = num_chunks > 100
    
    if use_faiss:
        try:
            import faiss
            # Strategy: IVF for large (1000+), Flat for small-medium (100-1000)
            if num_chunks > 1000:
                nlist = int(np.sqrt(num_chunks)) # Heuristic for number of clusters
                quantizer = faiss.IndexFlatIP(dim)
                index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)
                index.train(embeddings)
                index.add(embeddings)
                index.nprobe = min(10, nlist) # Search top 10 clusters
            else:
                index = faiss.IndexFlatIP(dim)
                index.add(embeddings)
            
            scores, indices = index.search(query_embedding.reshape(1, -1), top_k)
            top_indices = indices[0]
            scores = scores[0]
        except ImportError:
            use_faiss = False
        except Exception as e:
            print(f"[RAG] FAISS search error: {e}")
            use_faiss = False

    if not use_faiss:
        # Cosine similarity (embeddings are already normalized)
        scores_arr = embeddings @ query_embedding
        k = min(top_k, len(scores_arr))
        top_indices = np.argpartition(scores_arr, -k)[-k:]
        top_indices = top_indices[np.argsort(scores_arr[top_indices])[::-1]]
        scores = scores_arr[top_indices]

    results = []
    for i, idx in enumerate(top_indices):
        if idx < 0: continue
        score = float(scores[i])
        if score < 0.20: # Slightly lower threshold for semantic chunking
            continue
        m = meta[idx]
        results.append({
            "filename": m["filename"],
            "text": m["text"],
            "score": round(score, 4),
            "doc_id": m["doc_id"],
        })
    return results


def retrieve_chunks_with_reranking(
    agent_id: int,
    query: str,
    top_k: int = 5,
    use_reranker: bool = True,
    initial_k_multiplier: float = 5.0,  # Get 5x more chunks for re-ranking
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Retrieve chunks and optionally re-rank using a CrossEncoder model.
    
    This two-stage approach:
    1. Fast stage: Retrieve ~50-100 candidates via cosine similarity
    2. Smart stage (optional): Re-rank candidates with cross-encoder for better relevance
    
    Returns:
        Tuple of (ranked_chunks, reranking_metadata)
        where metadata includes:
          - reranking_applied: bool
          - reranking_time_ms: float
          - score_improvement: float
          - best_moved_positions: int
    
    Example:
        >>> chunks, metadata = retrieve_chunks_with_reranking(
        ...     agent_id=1, query="Python tutorial", top_k=5, use_reranker=True
        ... )
        >>> print(f"Found {len(chunks)} chunks in {metadata['reranking_time_ms']:.1f}ms")
    """
    import time
    
    start_time = time.time()
    metadata = {
        "reranking_applied": False,
        "reranking_time_ms": 0.0,
        "score_improvement": 0.0,
        "best_moved_positions": -1,
    }
    
    # Stage 1: Fast dense retrieval with lower threshold
    initial_k = max(int(top_k * initial_k_multiplier), 10)
    initial_chunks = retrieve_chunks(agent_id, query, top_k=initial_k)
    
    if not initial_chunks:
        return [], metadata
    
    # Stage 2: Optional ML re-ranking
    if use_reranker and len(initial_chunks) >= 2:
        try:
            from backend.rag_ranker import (
                rank_chunks_with_cross_encoder,
                compute_reranking_metrics,
                should_use_reranking,
            )
            
            # Check if re-ranking makes sense for this mode
            # (This is a heuristic to skip expensive re-ranking in STRICT mode)
            # Note: agent_mode would come from context, here we just check chunk count
            if should_use_reranking("STANDARD", len(initial_chunks)):
                reranked_chunks = rank_chunks_with_cross_encoder(
                    query=query,
                    chunks=initial_chunks,
                    top_k=top_k,
                    batch_size=32,
                )
                
                # Compute improvement metrics
                metrics = compute_reranking_metrics(initial_chunks, reranked_chunks)
                
                metadata.update({
                    "reranking_applied": True,
                    "score_improvement": metrics.get("score_improvement", 0.0),
                    "best_moved_positions": metrics.get("best_chunk_moved_positions", -1),
                })
                
                final_chunks = reranked_chunks
            else:
                final_chunks = initial_chunks[:top_k]
        except Exception as e:
            # If re-ranking fails, fall back to original results
            print(f"[RAG] Re-ranking failed, falling back to cosine similarity: {e}")
            final_chunks = initial_chunks[:top_k]
    else:
        final_chunks = initial_chunks[:top_k]
    
    # Record timing
    elapsed_ms = (time.time() - start_time) * 1000
    metadata["reranking_time_ms"] = round(elapsed_ms, 2)
    
    return final_chunks, metadata


def delete_document_chunks(agent_id: int, doc_id: int) -> None:
    """Remove all chunks belonging to a document."""
    existing_meta = _load_meta(agent_id)
    existing_embeddings = _load_embeddings(agent_id)

    keep_indices = [i for i, m in enumerate(existing_meta) if m.get("doc_id") != doc_id]
    filtered_meta = [existing_meta[i] for i in keep_indices]

    _save_meta(agent_id, filtered_meta)

    if existing_embeddings is not None and len(keep_indices) > 0:
        _save_embeddings(agent_id, existing_embeddings[keep_indices])
    elif existing_embeddings is not None:
        # All gone
        p = _embeddings_path(agent_id)
        if p.exists():
            p.unlink()


def list_agent_documents(agent_id: int) -> List[Dict[str, Any]]:
    """List unique documents indexed for an agent."""
    meta = _load_meta(agent_id)
    seen: Dict[int, Dict] = {}
    for m in meta:
        doc_id = m["doc_id"]
        if doc_id not in seen:
            seen[doc_id] = {"doc_id": doc_id, "filename": m["filename"], "chunks": 0}
        seen[doc_id]["chunks"] += 1
    return list(seen.values())
