"""
knowledge/indexer.py — FAISS vector index for knowledge chunks.

Uses sentence-transformers (all-MiniLM-L6-v2, 384-dim) for embeddings.
Maintains an independent FAISS index — does NOT share episodic/semantic indices.
Supports add and full rebuild (FAISS does not support true deletion).
"""

import faiss
import numpy as np
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
INDEX_PATH = TOOLS_DIR.parent / "state" / "knowledge" / "semantic_knowledge.index"

DIM = 384

_embed_model = None


def _model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _embed(text: str) -> np.ndarray:
    vec = _model().encode([text], normalize_embeddings=True)
    return np.array(vec, dtype=np.float32)


def rebuild(chunks: list) -> int:
    """Full rebuild of FAISS index from all knowledge chunks.

    Args:
        chunks: list of dicts with at least {"text": str}

    Returns:
        number of chunks indexed
    """
    if not chunks:
        _clear_index()
        return 0

    vectors = np.vstack([_embed(c["text"]) for c in chunks])
    index = faiss.IndexFlatIP(DIM)
    index.add(vectors)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    return len(chunks)


def search(query: str, top_k: int = 5) -> list:
    """Search knowledge index. Returns list of (score, chunk_id) pairs."""
    if not INDEX_PATH.exists():
        return []

    index = faiss.read_index(str(INDEX_PATH))
    if index.ntotal == 0:
        return []

    qvec = _embed(query)
    distances, indices = index.search(qvec, min(top_k, index.ntotal))
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0:
            continue
        results.append((round(float(dist), 3), int(idx)))
    return results


def _clear_index():
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()
