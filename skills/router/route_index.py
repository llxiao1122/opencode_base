import json, faiss, numpy as np
from pathlib import Path
from typing import Optional


class _FallbackEmbedder:
    _dim = 384

    def encode(self, texts, normalize_embeddings=True):
        if isinstance(texts, str):
            texts = [texts]
        vecs = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, t in enumerate(texts):
            code = sum(ord(c) * (j + 1) for j, c in enumerate(t.lower()))
            np.random.seed(code & 0x7FFFFFFF)
            vecs[i] = np.random.randn(self._dim)
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs /= norms
        return vecs


class RouteIndexManager:
    _fallback_dim = 384

    def __init__(self):
        self._embed_fn: Optional[callable] = None
        self.index: Optional[faiss.Index] = None
        self.route_labels: list[str] = []

    def _load_embedder(self):
        if self._embed_fn is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dim = 384
            self._embed_fn = lambda texts: np.asarray(
                self._model.encode(texts, normalize_embeddings=True)
            ).astype(np.float32)
            return
        except Exception:
            pass
        try:
            from skills.shared.onnx_embedder import ONNXEmbedder
            self._model = ONNXEmbedder()
            self._dim = 768
            self._embed_fn = lambda texts: np.asarray(
                self._model.encode(texts, normalize_embeddings=True)
            ).astype(np.float32)
            return
        except Exception:
            fb = _FallbackEmbedder()
            self._dim = fb._dim
            self._embed_fn = fb.encode

    def embed(self, texts):
        self._load_embedder()
        return self._embed_fn(texts)

    def build(self, seeds_path: Path):
        seeds, labels = [], []
        raw = json.loads(seeds_path.read_text(encoding="utf-8"))
        for route, data in raw.items():
            for seed in data["seeds"]:
                seeds.append(seed)
                labels.append(route)
        if not seeds:
            raise ValueError("route_seeds.json is empty")

        self._load_embedder()
        vecs = self.embed(seeds)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        vecs = np.ascontiguousarray(vecs, dtype=np.float32)
        faiss.normalize_L2(vecs)

        self.index = faiss.IndexFlatIP(self._dim)
        self.index.add(vecs)
        self.route_labels = labels

    def search(self, query_vec: np.ndarray, k: int = 3):
        if self.index is None:
            raise RuntimeError("RouteIndexManager not built")
        return self.index.search(query_vec, k)
