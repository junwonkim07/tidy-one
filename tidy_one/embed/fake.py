"""Deterministic stand-in for TextEncoder in tests: hashed bag of character bigrams.

Texts that share words land near each other, so ranking tests are meaningful without a model.
"""

from __future__ import annotations

import hashlib

import numpy as np


class FakeEncoder:
    def __init__(self, dim: int = 1024, model_id: str = "kure-v1"):
        self.dim = dim
        self.model_id = model_id

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        t = "".join(text.lower().split())
        grams = [t[i : i + 2] for i in range(max(1, len(t) - 1))] or [t]
        for g in grams:
            h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode_passages(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        return np.stack([self._one(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self._one(text)
