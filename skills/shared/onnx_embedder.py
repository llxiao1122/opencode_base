"""
shared/onnx_embedder.py — ONNX-based sentence embedder.

Replaceable with sentence_transformers for development.
"""
from pathlib import Path
from typing import Optional
import numpy as np


_BASE = Path(__file__).resolve().parent.parent.parent


class ONNXEmbedder:
    """Generic ONNX sentence embedder for any BERT-like model."""

    def __init__(self, model_path: Optional[str] = None,
                 tokenizer_id: Optional[str] = None,
                 max_length: int = 128):
        model_path = model_path or str(_BASE / "data" / "models" / "model.onnx")
        tokenizer_id = tokenizer_id or "shibing624/text2vec-base-chinese"
        self._model_path = model_path
        self._tokenizer_id = tokenizer_id
        self._max_length = max_length
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
        self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_id)

    def encode(
        self, texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False
    ):
        self._lazy_init()
        if isinstance(texts, str):
            texts = [texts]

        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self._tokenizer(
                batch, return_tensors="np", padding=True, truncation=True,
                max_length=self._max_length
            )
            out = self._session.run(None, {
                "input_ids": inputs["input_ids"],
                "attention_mask": inputs["attention_mask"],
            })
            last_hidden = out[0]
            mask = inputs["attention_mask"][:, :, None]
            masked = last_hidden * mask
            summed = masked.sum(axis=1)
            counts = mask.sum(axis=1)
            pooled = summed / np.maximum(counts, 1)
            if normalize_embeddings:
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                pooled /= np.maximum(norms, 1e-12)
            all_vecs.append(pooled)

        result = np.concatenate(all_vecs, axis=0)
        return result if len(texts) > 1 else result[0]

