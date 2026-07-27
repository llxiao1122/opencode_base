"""
shared/embedder.py — Unified embedding interface.

Fallback chain: ONNX (INT8 bge-small-zh) → deterministic FallbackEmbedder.
Zero PyTorch dependency at inference time.

Usage:
    from skills.shared.embedder import create_embedder
    emb = create_embedder()
    vec = emb.encode("query text", is_query=True)     # returns np.ndarray
"""

import logging
from pathlib import Path
from typing import Optional, List, Union

import numpy as np

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent.parent
_MODEL_DIR = _BASE / "data" / "models" / "bge-small-zh-int8"
_DIM = 512
_BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class ONNXEmbedder:
    dim = _DIM

    def __init__(self, model_dir: Optional[Path] = None):
        model_dir = model_dir or _MODEL_DIR
        self._model_path = str(model_dir / "model.onnx")
        self._tokenizer_path = str(model_dir)
        self._session = None
        self._tokenizer = None

    def _lazy_init(self):
        if self._session is not None:
            return
        from onnxruntime import InferenceSession
        from transformers import AutoTokenizer

        self._session = InferenceSession(
            self._model_path, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_path)

    def encode(
        self,
        texts: Union[str, List[str]],
        normalize_embeddings: bool = True,
        batch_size: int = 32,
        is_query: bool = False,
    ) -> np.ndarray:
        self._lazy_init()
        if isinstance(texts, str):
            texts = [texts]

        if is_query:
            texts = [_BGE_QUERY_PREFIX + t for t in texts]

        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self._tokenizer(
                batch,
                return_tensors="np",
                padding=True,
                truncation=True,
                max_length=128,
            )
            out = self._session.run(None, {
                "input_ids": inputs["input_ids"],
                "attention_mask": inputs["attention_mask"],
                "token_type_ids": inputs.get("token_type_ids"),
            })
            last_hidden = out[0]
            # CLS pooling (token 0)
            pooled = last_hidden[:, 0, :]
            if normalize_embeddings:
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                pooled /= np.maximum(norms, 1e-12)
            all_vecs.append(pooled)

        result = np.concatenate(all_vecs, axis=0)
        return result if len(texts) > 1 else result[0]


class FallbackEmbedder:
    dim = _DIM

    def encode(
        self,
        texts: Union[str, List[str]],
        normalize_embeddings: bool = True,
        batch_size: int = 32,
        is_query: bool = False,
    ) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        vecs = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for c in t.lower():
                xi = hash(c) % self.dim
                vecs[i, xi] += 1.0
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs /= norms
        return vecs if len(texts) > 1 else vecs[0]


_EMBEDDER_CACHE: Optional[Union[ONNXEmbedder, FallbackEmbedder]] = None


def create_embedder() -> Union[ONNXEmbedder, FallbackEmbedder]:
    global _EMBEDDER_CACHE
    if _EMBEDDER_CACHE is not None:
        return _EMBEDDER_CACHE
    if _MODEL_DIR.exists() and (_MODEL_DIR / "model.onnx").exists():
        try:
            emb = ONNXEmbedder()
            emb._lazy_init()
            _EMBEDDER_CACHE = emb
            logger.info("ONNXEmbedder ready (dim=%d)", emb.dim)
            return emb
        except Exception as e:
            logger.warning("ONNXEmbedder init failed: %s", e)
    _EMBEDDER_CACHE = FallbackEmbedder()
    logger.warning("Using FallbackEmbedder (dim=%d)", _EMBEDDER_CACHE.dim)
    return _EMBEDDER_CACHE
