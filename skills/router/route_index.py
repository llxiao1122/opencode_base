import json, faiss, numpy as np
from pathlib import Path
from typing import Optional

from skills.shared.embedder import create_embedder


class RouteIndexManager:
    def __init__(self):
        self._emb = None
        self.index: Optional[faiss.Index] = None
        self.route_labels: list[str] = []

    def embed(self, texts, is_query=True):
        if self._emb is None:
            self._emb = create_embedder()
        raw = self._emb.encode(texts, is_query=is_query)
        return np.asarray(raw, dtype=np.float32).reshape(1, -1) if isinstance(texts, str) else np.asarray(raw, dtype=np.float32)

    def build(self, seeds_path: Path):
        seeds, labels = [], []
        raw = json.loads(seeds_path.read_text(encoding="utf-8"))
        for route, data in raw.items():
            for seed in data["seeds"]:
                seeds.append(seed)
                labels.append(route)
        if not seeds:
            raise ValueError("route_seeds.json is empty")

        if self._emb is None:
            self._emb = create_embedder()
        vecs = self.embed(seeds, is_query=False)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        vecs = np.ascontiguousarray(vecs, dtype=np.float32)
        faiss.normalize_L2(vecs)

        self.index = faiss.IndexFlatIP(self._emb.dim)
        self.index.add(vecs)
        self.route_labels = labels

    def search(self, query_vec: np.ndarray, k: int = 3):
        if self.index is None:
            raise RuntimeError("RouteIndexManager not built")
        return self.index.search(query_vec, k)
