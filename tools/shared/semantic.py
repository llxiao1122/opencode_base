"""
shared/semantic.py — Unified semantic matcher.

Reuses all-MiniLM-L6-v2 (same model as MemoryCore) with lazy loading.
Keyword-first, semantic-fallback strategy. No LLM, pure vector math.

Usage:
    from shared.semantic import classify

    # Fallback when keywords miss
    route = "event"
    if not matched_by_keyword:
        route = classify(text, {
            "profile": ["这个人怎么样", "性格", "能力评价", "表现如何"],
            "task": ["今天要做什么", "工作安排", "待办事项"],
            "knowledge": ["制度规定", "操作规程", "标准流程"],
        }, fallback="event")
"""

import numpy as np
from pathlib import Path

__all__ = ["classify", "score", "SemanticMatcher"]

_inst = None


def _get_matcher():
    global _inst
    if _inst is None:
        _inst = SemanticMatcher()
    return _inst


def classify(text: str, anchors: dict, fallback: str = "", threshold: float = 0.55) -> str:
    """Quick helper: classify text into one of the anchor categories."""
    return _get_matcher().classify(text, anchors, fallback=fallback, threshold=threshold)


def score(text: str, category_labels: list[str]) -> float:
    """Score how well text matches a set of category labels."""
    return _get_matcher().score(text, category_labels)


class SemanticMatcher:
    """Lazy-loading semantic matcher using all-MiniLM-L6-v2."""

    def __init__(self):
        self._model = None
        self._cache = {}

    @property
    def _dim(self):
        return 384

    def _load_model(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer('all-MiniLM-L6-v2')

    def _embed(self, texts: list[str]) -> np.ndarray:
        self._load_model()
        if isinstance(texts, str):
            texts = [texts]
        vecs = self._model.encode(texts, normalize_embeddings=True)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        return vecs.astype(np.float32)

    def _anchor_key(self, name: str, anchors: tuple) -> str:
        import hashlib
        return hashlib.sha256(f"{name}:{'|'.join(sorted(anchors))}".encode()).hexdigest()[:12]

    def score(self, text: str, category_labels: list[str]) -> float:
        """Score how well text matches category labels. Returns 0.0~1.0."""
        if not text or not category_labels:
            return 0.0
        key = self._anchor_key("score", tuple(category_labels))
        if key not in self._cache:
            labels_vec = self._embed(category_labels)
            self._cache[key] = labels_vec.mean(axis=0)
        anchor = self._cache[key]
        qvec = self._embed([text])[0]
        return float(np.dot(qvec, anchor))

    def classify(self, text: str, anchors: dict, fallback: str = "", threshold: float = 0.55) -> str:
        """Classify text into one of the anchor categories.

        Args:
            text: query text
            anchors: {category_name: [label1, label2, ...]}
            fallback: return if no category scores above threshold
            threshold: minimum similarity score (0.55 works for all-MiniLM-L6-v2 on Chinese)
        """
        if not text or not anchors:
            return fallback

        best_cat = fallback
        best_score = threshold

        for cat, labels in anchors.items():
            s = self.score(text, labels)
            if s > best_score:
                best_score = s
                best_cat = cat

        return best_cat
